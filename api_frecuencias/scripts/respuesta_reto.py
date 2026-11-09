"""Evidencia de la respuesta a la pregunta final del reto (§20) con los datos históricos y recientes.

1) En el proceso, con el código de producción:
   - una base TEMPORAL en el PostgreSQL local (se crea, se migra con «alembic upgrade head» y se borra al final) y
     una COPIA temporal de datos/ (DATA_DIR y MODELOS_DIR apuntan a la copia: nada se escribe en datos/);
   - el ciclo diario corre una vez hasta el último día de la serie empaquetada (deja demanda_observada, predicciones
     y alertas, como en operación);
   - para cada fecha se encola una ejecución de tipo «respuesta» y se corre con el protocolo de la cola (reserva,
     precalcular() y cierre «ok» con cerca); después se lee como GET /api/v1/respuesta, es decir, desde la foto de
     ai_frecuencias.respuesta_reto.
   Escribe en docs/evidencias/respuesta/ respuesta_<fecha>.json (la respuesta de la API más «contraste_observado»,
   que la API no devuelve) y respuesta_reto.md (las tablas por día, ruta y franja).
2) Por HTTP (--en-vivo): uvicorn en 127.0.0.1:8503 contra la misma base, con la autenticación encendida y claves
   generadas para la corrida (no se guardan). Deja api_en_vivo.txt y api_respuesta_<ruta>_<fecha>.json: 401 sin
   clave, 403 del operador en el POST, 202 del analista, sondeo de la ejecución, 200 desde la foto, 404
   «sin_calcular», 422 y la exportación.

Fechas por omisión: un laboral, un sábado y un domingo de noviembre de 2025 (posteriores al corte del modelo,
2025-08-31) y el día siguiente al último dato de la API («datos recientes»), que el plan calcula con el modelo activo.

Uso:  python scripts/respuesta_reto.py [--fechas 2025-11-19 ...] [--en-vivo] [--conservar-base]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from datetime import date, datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
SALIDA = RAIZ / "docs" / "evidencias" / "respuesta"
FECHAS_2025 = ("2025-11-19", "2025-11-22", "2025-11-23")
BASE_TEMPORAL = "ai_frecuencias_evidencia_respuesta"
HOSTS_LOCALES = {"localhost", "127.0.0.1", "db", "::1"}
PUERTO = int(os.environ.get("RESPUESTA_RETO_PUERTO", "8503"))   # el puerto se cambia con RESPUESTA_RETO_PUERTO


# ---------------------------------------------------------------------------------------------------- entorno
def _preparar_copia() -> Path:
    destino = Path(tempfile.mkdtemp(prefix="respuesta_reto_"))
    shutil.copytree(RAIZ / "datos", destino / "datos")
    os.environ["DATA_DIR"] = str(destino / "datos")
    os.environ["MODELOS_DIR"] = str(destino / "datos" / "modelos")
    return destino


def _url_local():
    from sqlalchemy.engine import make_url

    from app.config import Ajustes

    url = make_url(os.environ.get("TEST_DATABASE_URL") or Ajustes().database_url)
    if url.host not in HOSTS_LOCALES:
        raise SystemExit("La evidencia solo corre contra un PostgreSQL local (nunca contra la base del reto)")
    return url


def _crear_base(url) -> str:
    from sqlalchemy import create_engine, text

    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text(f'DROP DATABASE IF EXISTS "{BASE_TEMPORAL}" WITH (FORCE)'))
        c.execute(text(f'CREATE DATABASE "{BASE_TEMPORAL}"'))
    admin.dispose()
    return url.set(database=BASE_TEMPORAL).render_as_string(hide_password=False)


def _borrar_base(url) -> None:
    from sqlalchemy import create_engine, text

    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text(f'DROP DATABASE IF EXISTS "{BASE_TEMPORAL}" WITH (FORCE)'))
    admin.dispose()


def _migrar(url_base: str) -> None:
    from alembic.config import Config

    from alembic import command

    cfg = Config(str(RAIZ / "alembic.ini"))
    cfg.set_main_option("script_location", str(RAIZ / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url_base.replace("%", "%%"))
    command.upgrade(cfg, "head")


# ---------------------------------------------------------------------------------------------------- cálculo
def _correr_en_la_cola(execution_id) -> str:
    """El protocolo de la cola: reserva, el trabajo y el cierre con cerca (cola.procesar con la ejecución dada)."""
    from app.servicios import cola

    return cola.procesar(execution_id) or "sin estado"


def _ciclo_diario(hasta: date) -> dict:
    """Una ejecución del ciclo diario (tipo «frecuencia») hasta `hasta`: deja demanda_observada, predicciones y
    alertas en la base temporal, como en operación."""
    from app.db import nueva_sesion
    from app.modelos_db import Ejecucion
    from app.servicios import ejecucion

    s = nueva_sesion()
    try:
        e = ejecucion.crear_ejecucion(s, "frecuencia", {"hasta": hasta.isoformat(), "horizontes": [30, 60, 120],
                                                        "notificar": False}, "evidencia-respuesta")
        eid = e.execution_id
    finally:
        s.close()
    t0 = time.perf_counter()
    estado = _correr_en_la_cola(eid)
    s = nueva_sesion()
    try:
        fila = s.get(Ejecucion, eid)
        return {"execution_id": str(eid), "estado": estado, "segundos": round(time.perf_counter() - t0, 1),
                "mensaje": fila.mensaje if fila else None}
    finally:
        s.close()


def _calcular(fecha: date) -> dict:
    """Encola la ejecución «respuesta» de la fecha y la corre con el protocolo de la cola."""
    from app.db import nueva_sesion
    from app.modelos_db import Ejecucion
    from app.servicios import respuesta

    s = nueva_sesion()
    try:
        e, _nueva = respuesta.solicitar_calculo(s, fecha, None, "evidencia-respuesta")
        eid = e.execution_id
    finally:
        s.close()
    t0 = time.perf_counter()
    estado = _correr_en_la_cola(eid)
    s = nueva_sesion()
    try:
        fila = s.get(Ejecucion, eid)
        return {"execution_id": str(eid), "estado": estado, "segundos": round(time.perf_counter() - t0, 1),
                "mensaje": fila.mensaje if fila else None}
    finally:
        s.close()


def _contraste(ruta: str, fecha: date, por_hora: list[dict]) -> dict:
    """Pasajeros observados del día (serie empaquetada) frente al pronóstico y su banda."""
    from app.servicios import datos

    serie = datos.demanda_horaria(desde=fecha, hasta=fecha, rutas=[ruta])
    obs = {int(h): float(p) for h, p, ex in zip(serie["hora"], serie["pasajeros"],
                                                serie.get("excluido", [0] * len(serie)), strict=False)
           if p == p and not int(ex or 0)}
    horas = [p for p in por_hora if p["hora"] in obs]
    if not horas:
        return {"horas_con_dato": 0}
    dentro = sum(1 for p in horas if p["p10"] <= obs[p["hora"]] <= p["p90"])
    real = sum(obs[p["hora"]] for p in horas)
    esperado = sum(p["esperado"] for p in horas)
    error_abs = sum(abs(obs[p["hora"]] - p["esperado"]) for p in horas)
    return {"horas_con_dato": len(horas), "observado_dia": round(real, 1), "esperado_dia": round(esperado, 1),
            "error_dia_pct": round(100 * (esperado - real) / real, 2) if real else None,
            "wape_horario_pct": round(100 * error_abs / real, 2) if real else None,
            "horas_dentro_p10_p90": dentro}


# ---------------------------------------------------------------------------------------------------- markdown
def _n(x, d: int = 1) -> str:
    """Número en formato colombiano, redondeado «mitad hacia arriba» (7.524,5 -> 7.525), igual en todas las tablas;
    el formato de Python redondea al par y daría 7.524."""
    if x is None:
        return "—"
    from decimal import ROUND_HALF_UP, Decimal

    valor = Decimal(str(x)).quantize(Decimal(1).scaleb(-d), rounding=ROUND_HALF_UP)
    return f"{valor:,.{d}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _fila_resumen(resp: dict, r: dict, c: dict) -> str:
    rd, pe, v, fr = r["resumen_despacho"], r["pasajeros_esperados"], r["vehiculos"], r["flota_y_recaudo"]
    no_v = [str(h["hora"]) for h in r["cada_cuanto_despachar"] if not h["viable"]]
    costo = fr["costo_operativo_cop"]
    costo_hoy = fr["costo_operativo_actual_cop"]
    recaudo = fr["recaudo_esperado_cop"]
    return (f"| {resp['fecha']} | {resp['tipo_dia']} | {r['ruta']} | {rd['salidas_dia_recomendadas']} / "
            f"{_n(rd['salidas_dia_programadas'])} | {_n(rd['headway_pico_min'], 2)} ({rd['hora_pico']} h) / "
            f"{_n(rd['headway_valle_min'], 2)} | {_n(pe['dia'], 0)} ({_n(pe['p10'], 0)}–{_n(pe['p90'], 0)}) | "
            f"{_n(c.get('observado_dia'), 0)} | {v['requeridos_pico']} ({v['hora_pico']} h) / {v['flota_disponible']} "
            f"| {v['requeridos_pico_10_3']} | {_n(fr['vehiculos_hora_ahorrados'])} | "
            f"{_n(costo / 1e6 if costo else None, 2)} / {_n(costo_hoy / 1e6 if costo_hoy else None, 2)} | "
            f"{_n(fr['espera_media_min'], 2)} / {_n(fr['espera_media_actual_min'], 2)} | "
            f"{_n(fr['sobreocupacion_pasajeros'])} / {_n(fr['sobreocupacion_pasajeros_actual'])} | "
            f"{_n(recaudo / 1e6 if recaudo else None, 2)} | {', '.join(no_v) or 'ninguna'} |")


def _markdown(resultados: list[dict], ciclo: dict, segundos: float) -> str:
    primero = resultados[0]["respuesta"]
    t = primero["trazabilidad"]
    l1 = ["# Respuesta a la pregunta final del reto (§20): evidencia por día, ruta y franja", "",
          "Generado con `scripts/respuesta_reto.py` con el código de producción: base temporal en el PostgreSQL local "
          "(migrada con `alembic upgrade head`), copia temporal de `datos/`, una corrida del ciclo diario y, para "
          "cada fecha, una ejecución de tipo «respuesta» en la cola (`POST /api/v1/respuesta/calcular`). Las cifras "
          "se leen después como `GET /api/v1/respuesta`, desde la foto guardada en `ai_frecuencias.respuesta_reto`. "
          "Cada día tiene su respuesta completa en `respuesta_<fecha>.json`.", "",
          f"> {primero['pregunta']}", "",
          f"- Modelo: `{t['model_id']}` (variables `{t['feature_version']}`, corte {t['data_cutoff']}, calibración de "
          f"la banda P10–P90 `{t.get('calibracion_version') or 'sin dato'}`).",
          f"- Pronóstico del plan: `{t.get('fuente_pronostico')}`; versión de umbrales {t.get('umbrales_version')}; "
          f"datos hasta {t.get('datos_hasta')}.",
          f"- Ciclo diario previo: ejecución `{ciclo.get('execution_id')}`, estado {ciclo.get('estado')}, "
          f"{_n(ciclo.get('segundos'))} s.",
          f"- Tiempo total de los cálculos de la respuesta en la cola: {_n(segundos)} s.", "",
          "| Fecha | Tipo de día | Ejecución «respuesta» | Estado | Segundos | Generada |", "|---|---|---|---|---|---|"]
    for res in resultados:
        resp, calc = res["respuesta"], res["calculo"]
        l1.append(f"| {resp['fecha']} | {resp['tipo_dia']} | `{calc['execution_id']}` | {calc['estado']} | "
                  f"{_n(calc['segundos'])} | {resp['generado_en']} |")
    l1 += ["", "## Resumen por día y ruta", "",
           "| Fecha | Tipo de día | Ruta | Salidas recomendadas / programadas | Headway pico / valle (min) | "
           "Pasajeros esperados (P10–P90) | Observados | Vehículos en ruta (pico) / flota | §10.3 | "
           "Vehículos-hora ahorrados | Costo operativo plan / hoy (millones COP) | Espera media plan / hoy (min) | "
           "Sobreocupación plan / hoy (pasajeros) | Recaudo esperado (millones COP) | Horas no viables |",
           "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for res in resultados:
        for r in res["respuesta"]["rutas"]:
            l1.append(_fila_resumen(res["respuesta"], r, res["contraste_observado"].get(r["ruta"], {})))
    l1 += ["", "Vehículos en ruta (pico): máximo de buses en ruta a la vez con el plan (conteo de D5 cada 15 min). "
           "§10.3: máximo de ceil(ciclo / headway), que supone que la frecuencia de la hora dura un ciclo completo. "
           "Vehículos-hora ahorrados: programado menos recomendado (negativo = el plan usa más). Recaudo: pasajeros "
           "esperados × tarifa neta 3.182 COP (tarifa pública 2026 × 0,86; Extreme no suministró la tarifa, §19). "
           "Observados: «—» cuando el día no tiene datos (el día siguiente al último dato).", ""]
    l1 += ["## Contraste con los pasajeros observados", "",
           "| Fecha | Ruta | Observados | Esperados | Error del día | WAPE horario | Horas dentro de P10–P90 |",
           "|---|---|---|---|---|---|---|"]
    for res in resultados:
        for ruta, c in res["contraste_observado"].items():
            if not c.get("horas_con_dato"):
                l1.append(f"| {res['respuesta']['fecha']} | {ruta} | sin datos todavía | — | — | — | — |")
                continue
            l1.append(f"| {res['respuesta']['fecha']} | {ruta} | {_n(c.get('observado_dia'), 0)} | "
                      f"{_n(c.get('esperado_dia'), 0)} | {_n(c.get('error_dia_pct'), 1)} % | "
                      f"{_n(c.get('wape_horario_pct'), 1)} % | {c.get('horas_dentro_p10_p90')} de "
                      f"{c.get('horas_con_dato')} |")
    l1 += ["", "## Cada cuánto despachar, por franja", "",
           "Headway de la franja = minutos operados / salidas de la franja (recomendado y programado).", "",
           "| Fecha | Tipo de día | Ruta | Franja | Salidas recomendadas | Salidas programadas | "
           "Headway recomendado (min) | Headway programado (min) | Horas no viables |",
           "|---|---|---|---|---|---|---|---|---|"]
    for res in resultados:
        resp = res["respuesta"]
        for r in resp["rutas"]:
            for f in r["resumen_despacho"]["por_franja"]:
                l1.append(f"| {resp['fecha']} | {resp['tipo_dia']} | {r['ruta']} | {f['franja']} | {f['salidas']} | "
                          f"{_n(f['salidas_programadas'])} | {_n(f['headway_min'], 2)} | "
                          f"{_n(f['headway_actual_min'], 2)} | "
                          f"{', '.join(str(h) for h in f['horas_no_viables']) or 'ninguna'} |")
    l1 += ["", "## Atención inmediata en el momento de la consulta", "",
           "| Fecha consultada | Ruta | Abiertas ahora (por severidad) | Detectadas en la fecha consultada |",
           "|---|---|---|---|"]
    for res in resultados:
        resp = res["respuesta"]
        for r in resp["rutas"]:
            a = r.get("atencion_resumen") or {}
            sev = ", ".join(f"{k} {v}" for k, v in sorted((a.get("abiertas_ahora_por_severidad") or {}).items()))
            l1.append(f"| {resp['fecha']} | {r['ruta']} | {a.get('abiertas_ahora', 0)} ({sev or 'ninguna'}) | "
                      f"{a.get('de_la_fecha', 0)} |")
    l1 += ["", "«Abiertas ahora»: alertas sin cerrar ni descartar en `ai_frecuencias.alert` en el instante de la "
           "consulta, de cualquier fecha (las dejó el ciclo diario previo). «Detectadas en la fecha consultada»: las "
           "de ese día de Bogotá, en cualquier estado.", ""]
    for res in (resultados[0], resultados[-1]):
        resp = res["respuesta"]
        for r in resp["rutas"]:
            pron = {p["hora"]: p for p in r["pasajeros_esperados"]["por_hora"]}
            l1 += [f"### {r['ruta']} ({resp['fecha']}, {resp['tipo_dia'].lower()}): detalle por hora", "",
                   "| Hora | Franja | Headway recomendado | Buses/h | Headway programado | Buses/h programados | "
                   "Pasajeros esperados (P10–P90) | Viable | Motivo |", "|---|---|---|---|---|---|---|---|---|"]
            for h in r["cada_cuanto_despachar"]:
                p = pron.get(h["hora"], {})
                l1.append(f"| {h['hora']} | {h['franja']} | {_n(h['headway_min'], 2)} | {h['buses_hora']} | "
                          f"{_n(h['headway_actual_min'], 2)} | {_n(h['buses_hora_actual'], 2)} | "
                          f"{_n(p.get('esperado'), 0)} ({_n(p.get('p10'), 0)}–{_n(p.get('p90'), 0)}) | "
                          f"{'sí' if h['viable'] else 'no'} | {h['motivo']} |")
            l1.append("")
    l1 += ["## Limitaciones declaradas por la respuesta", ""] + [f"- {x}" for x in resultados[-1]["respuesta"]
                                                                  ["limitaciones"]] + [""]
    return "\n".join(l1)


# ---------------------------------------------------------------------------------------------------- en vivo
def _esperar_api(base: str, segundos: float = 120.0) -> None:
    import httpx

    limite = time.monotonic() + segundos
    while time.monotonic() < limite:
        try:
            if httpx.get(f"{base}/health", timeout=2.0).status_code < 500:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    raise SystemExit(f"La API no respondió en {base}")


def _en_vivo(url_base: str, fecha_reciente: date, fecha_2025: date) -> list[str]:
    """La respuesta por HTTP: POST calcular → sondeo de la ejecución → GET desde la foto, con la autenticación."""
    import httpx

    claves = {rol: secrets.token_urlsafe(32) for rol in ("operador", "analista", "admin")}
    entorno = dict(os.environ, DATABASE_URL=url_base, AUTH_HABILITADA="true", TRABAJADORES="1",
                   REANUDAR_EJECUCIONES="true", PLANIFICADOR_HABILITADO="false",
                   API_KEYS=json.dumps({hashlib.sha256(c.encode()).hexdigest(): {"usuario": f"evidencia_{r}", "rol": r}
                                        for r, c in claves.items()}))
    base = f"http://127.0.0.1:{PUERTO}"
    comando = [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(PUERTO),
               "--log-level", "warning"]
    proceso = subprocess.Popen(comando, cwd=str(RAIZ), env=entorno,  # noqa: S603 - comando fijo, sin entrada externa
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    lineas = [f"Respuesta a la pregunta del reto por HTTP: uvicorn en 127.0.0.1:{PUERTO} contra la base temporal "
              f"{BASE_TEMPORAL} (migrada con «alembic upgrade head», con el ciclo diario ya corrido), autenticación "
              "encendida, un trabajador de la cola y claves de operador y analista generadas para la corrida (no se "
              "guardan). Datos: copia temporal de datos/ (DATA_DIR y MODELOS_DIR).",
              f"Fecha de la corrida: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} (hora local)", ""]
    try:
        _esperar_api(base)
        op, an = {"X-API-Key": claves["operador"]}, {"X-API-Key": claves["analista"]}
        with httpx.Client(base_url=base, timeout=120.0) as c:
            r = c.get("/api/v1/respuesta")
            lineas.append(f"GET /api/v1/respuesta sin X-API-Key -> {r.status_code} {r.json()['error']['codigo']}")
            r = c.post("/api/v1/respuesta/calcular", json={"fecha": fecha_2025.isoformat()}, headers=op)
            lineas.append(f"POST /api/v1/respuesta/calcular (operador) -> {r.status_code} "
                          f"{r.json()['error']['codigo']}")
            r = c.get("/api/v1/respuesta", params={"ruta": "KRA 99"}, headers=op)
            lineas.append(f"GET /api/v1/respuesta?ruta=KRA 99 (operador) -> {r.status_code} "
                          f"{r.json()['error']['codigo']}")
            r = c.get("/api/v1/respuesta", params={"fecha": "2025-03-04"}, headers=op)
            e = r.json()["error"]
            lineas.append(f"GET /api/v1/respuesta?fecha=2025-03-04 (operador, sin foto) -> {r.status_code} "
                          f"{e['codigo']}: {e['mensaje']}")
            lineas.append(f"  pista: {e['detalle'].get('pista')} con "
                          f"{json.dumps(e['detalle'].get('cuerpo_sugerido'), ensure_ascii=False)} (rol "
                          f"{e['detalle'].get('rol_requerido')})")
            for fecha, rutas in ((fecha_reciente, None), (fecha_2025, ["CRA 54"])):
                cuerpo = {"fecha": fecha.isoformat()} | ({"rutas": rutas} if rutas else {})
                t0 = time.perf_counter()
                r = c.post("/api/v1/respuesta/calcular", json=cuerpo, headers=an)
                post_ms = (time.perf_counter() - t0) * 1000
                job = r.json()
                lineas.append(f"POST /api/v1/respuesta/calcular {json.dumps(cuerpo, ensure_ascii=False)} (analista) -> "
                              f"{r.status_code} en {post_ms:.0f} ms, execution_id {job['execution_id']}, estado "
                              f"{job['estado']}")
                estado, sondeos = job["estado"], 0
                while estado in ("en_cola", "corriendo") and time.perf_counter() - t0 < 600:
                    time.sleep(1.0)
                    sondeos += 1
                    estado = c.get(job["consultar_estado"], headers=an).json()["estado"]
                lineas.append(f"  GET {job['consultar_estado']} -> «{estado}» tras {sondeos} sondeos "
                              f"({time.perf_counter() - t0:.1f} s desde el POST)")
                params = {"fecha": fecha.isoformat()} | ({"ruta": rutas[0]} if rutas else {})
                tiempos = []
                for _ in range(21):
                    t1 = time.perf_counter()
                    r = c.get("/api/v1/respuesta", params=params, headers=op)
                    tiempos.append((time.perf_counter() - t1) * 1000)
                datos = r.json()
                correlacion = "presente" if r.headers.get("X-Correlation-Id") else "ausente"
                lineas.append(f"GET /api/v1/respuesta {json.dumps(params, ensure_ascii=False)} (operador) -> "
                              f"{r.status_code}, 21 lecturas de la foto: mediana {statistics.median(tiempos):.0f} ms, "
                              f"máximo {max(tiempos):.0f} ms; X-Correlation-Id {correlacion}")
                t = datos["trazabilidad"]
                lineas.append(f"  fecha {datos['fecha']} ({datos['tipo_dia']}), generado_en {datos['generado_en']}, "
                              f"consultado_en {datos['consultado_en']}")
                lineas.append(f"  trazabilidad: model_id {t['model_id']}, calibracion_version "
                              f"{t['calibracion_version']}, fuente_pronostico {t['fuente_pronostico']}, "
                              f"umbrales_version {t['umbrales_version']}, execution_id {t['execution_id']}, "
                              f"datos_hasta {t['datos_hasta']}")
                for ruta in datos["rutas"]:
                    rd, a = ruta["resumen_despacho"], ruta["atencion_resumen"]
                    lineas.append(f"  {ruta['ruta']}: {rd['salidas_dia_recomendadas']} salidas (programadas "
                                  f"{rd['salidas_dia_programadas']}), headway pico {rd['headway_pico_min']} min a las "
                                  f"{rd['hora_pico']} h, {ruta['pasajeros_esperados']['dia']:.0f} pasajeros, "
                                  f"{ruta['vehiculos']['requeridos_pico']} vehículos de "
                                  f"{ruta['vehiculos']['flota_disponible']}; abiertas ahora {a['abiertas_ahora']} "
                                  f"{json.dumps(a['abiertas_ahora_por_severidad'], ensure_ascii=False)}, de la fecha "
                                  f"{a['de_la_fecha']}")
                    for x in ruta["atencion_inmediata"][:3]:
                        lineas.append(f"    {x['codigo']} {x['severidad']} {x['estado']} ({x['alcance']}) detectada "
                                      f"{x['detectada_en']}")
                if rutas:
                    nombre = f"api_respuesta_{rutas[0].replace(' ', '')}_{fecha.isoformat()}.json"
                    (SALIDA / nombre).write_text(json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8")
                    lineas.append(f"  cuerpo completo en {nombre}")
            r = c.get("/api/v1/respuesta/export", params={"formato": "csv", "fecha": fecha_reciente.isoformat()},
                      headers=op)
            filas = r.content.decode("utf-8-sig").strip().splitlines()
            lineas.append(f"GET /api/v1/respuesta/export?formato=csv&fecha={fecha_reciente.isoformat()} -> "
                          f"{r.status_code}, {len(filas) - 1} filas; encabezado: {filas[0]}")
            r = c.get("/api/v1/respuesta/export", params={"formato": "xlsx", "fecha": fecha_reciente.isoformat()},
                      headers=op)
            lineas.append(f"GET /api/v1/respuesta/export?formato=xlsx&fecha={fecha_reciente.isoformat()} -> "
                          f"{r.status_code} {r.headers.get('content-type')} ({len(r.content)} bytes)")
    finally:
        proceso.terminate()
        try:
            proceso.wait(timeout=20)
        except subprocess.TimeoutExpired:
            proceso.kill()
    return lineas


# ---------------------------------------------------------------------------------------------------- principal
def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--fechas", nargs="*", default=None, help="fechas ISO; por omisión, las de 2025 y el día siguiente "
                                                             "al último dato")
    p.add_argument("--en-vivo", action="store_true", help=f"también por HTTP con uvicorn en el puerto {PUERTO}")
    p.add_argument("--conservar-base", action="store_true", help="no borrar la base temporal al terminar")
    args = p.parse_args()
    copia = _preparar_copia()
    sys.path.insert(0, str(RAIZ))
    os.environ["REANUDAR_EJECUCIONES"] = "false"           # en el proceso, la cola se procesa aquí mismo
    os.environ["AUTH_HABILITADA"] = "false"
    url = _url_local()
    url_base = _crear_base(url)
    os.environ["DATABASE_URL"] = url_base
    try:
        from app.config import obtener_ajustes

        obtener_ajustes.cache_clear()
        _migrar(url_base)
        from app.db import nueva_sesion
        from app.servicios import datos, ejecucion, respuesta

        s = nueva_sesion()
        try:
            ejecucion.sembrar_registro(s)
        finally:
            s.close()
        ultima_serie = max(datos.demanda_horaria()["fecha"])
        ciclo = _ciclo_diario(ultima_serie)
        print(f"Ciclo diario hasta {ultima_serie}: {ciclo['estado']} en {ciclo['segundos']} s")
        s = nueva_sesion()
        try:
            reciente = respuesta.fecha_por_omision(s)
        finally:
            s.close()
        fechas = [date.fromisoformat(x) for x in (args.fechas or FECHAS_2025)]
        if args.fechas is None:
            fechas.append(reciente)
        SALIDA.mkdir(parents=True, exist_ok=True)
        resultados, t0 = [], time.perf_counter()
        for fecha in fechas:
            calc = _calcular(fecha)
            s = nueva_sesion()
            try:
                resp = respuesta.leer(s, None, fecha)
            finally:
                s.close()
            contraste = {r["ruta"]: _contraste(r["ruta"], fecha, r["pasajeros_esperados"]["por_hora"])
                         for r in resp["rutas"]}
            resultados.append({"respuesta": resp, "contraste_observado": contraste, "calculo": calc})
            (SALIDA / f"respuesta_{fecha.isoformat()}.json").write_text(
                json.dumps({**resp, "contraste_observado": contraste, "calculo_en_la_cola": calc}, ensure_ascii=False,
                           indent=1), encoding="utf-8")
            print(f"{fecha} ({resp['tipo_dia']}, {calc['estado']} en {calc['segundos']} s): " + "; ".join(
                f"{r['ruta']} {r['resumen_despacho']['salidas_dia_recomendadas']} salidas, "
                f"{r['pasajeros_esperados']['dia']:.0f} pasajeros" for r in resp["rutas"]))
        segundos = sum(r["calculo"]["segundos"] for r in resultados)
        (SALIDA / "respuesta_reto.md").write_text(_markdown(resultados, ciclo, segundos), encoding="utf-8")
        print(f"Evidencia en {SALIDA} ({time.perf_counter() - t0:.1f} s)")
        if args.en_vivo:
            lineas = _en_vivo(url_base, reciente, date.fromisoformat(FECHAS_2025[0]))
            (SALIDA / "api_en_vivo.txt").write_text("\n".join(lineas) + "\n", encoding="utf-8")
            print("\n".join(lineas))
    finally:
        if not args.conservar_base:
            _borrar_base(url)
        shutil.rmtree(copia, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
