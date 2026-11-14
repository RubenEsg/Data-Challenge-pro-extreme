"""§10.1 «ocupación actual» en la operación PROGRAMADA (10.1-d): el ciclo intradía con el PLANIFICADOR real
(APScheduler) y la cola real (un trabajador en segundo plano), sin ningún POST, en un día comprimido.

Qué hace (en una base LOCAL desechable y en una copia temporal de datos/, nunca en el repositorio):
1. Crea desde cero la base indicada, la migra y arranca la API en este proceso (lifespan real: cola de trabajos y
   planificador) con FUENTE=postgres (la captura en vivo, la que habilita el ciclo intradía) y el ciclo diario y el
   reentrenamiento fuera de la ventana de la prueba.
2. El día se comprime: APScheduler dispara el trabajo intradía cada minuto real y cada disparo es la hora siguiente del
   22/10/2025 (8:05, 9:05, 10:05 y 11:05). La tarea calcula su franja con el PLAN_INTRADIA_CRON por omisión
   («5 6-20 * * *») sobre ese reloj, y cada disparo se repite dos segundos después, como si viniera de otra réplica.
3. La captura «en vivo» es de prueba: la serie empaquetada del 22/10/2025 y de los dos días previos, donde cada hora
   llega (ultima_actualizacion) 2 min después de cerrar, y la lectura de cada ciclo solo ve lo que había llegado a su
   instante. Para las franjas que pide el ciclo, viajes por segmento como los que escribe tg_timbrada_segmento: CL 72 al
   100 % a las 7 y 8 h y al 50 % a las 6 y 9 h (tests/integracion/test_ocupacion_ciclo.py). progvehiculos no se
   conoce: una hora cuenta como completa a las 6 h de su fin.
4. Mientras los ciclos corren, mide la latencia de una consulta paginada (GET /api/v1/recommendations, 50 filas) con un
   ciclo en curso y sin él (RNF-002), y guarda la duración y lo que escribió cada ciclo.

Comprueba que cada franja se encola una sola vez (la segunda réplica no encola nada), con instante = la franja y
parametros.intradia; que la cola los procesa de uno en uno y cada uno lee solo la hora que llegó; que la restricción
reactiva actúa a las 8 h (con la ocupación de las 7 h) y a las 9 h (con la de las 8 h), en el plan del día en curso y en
las recomendaciones de 30 y 60 min de esa hora (la de 120 min es de la hora siguiente), y que a las 10:05, con la
ocupación de las 9 h bajo el umbral, no actúa y lo dice; que la ALT-002 del episodio de las 7 y 8 h sale a las 9:05 en
el segmento crítico, con la hora de las 7 que midió y guardó el ciclo de las 8:05; que ningún ciclo intradía guarda
monitoreo, lee los consolidados ni pide el refresco de segmentos, ni alerta horas que todavía no pasaron; y que la
consulta paginada sigue bajo los 2 s de p95 con un ciclo en curso.

Uso (desde EntregaFinal/api_frecuencias; la URL del PostgreSQL local sale de DATABASE_URL o del .env y no se imprime):
  python scripts/evidencia_planificador_intradia.py --base-datos ai_frecuencias_pruebas_intradia \
      --salida docs/evidencias/ocupacion/planificador_intradia.txt \
      --json docs/evidencias/ocupacion/planificador_intradia.json
Lo corre, con PRUEBA_PLANIFICADOR=1, la prueba
tests/integracion/test_planificador_programado.py::test_el_ciclo_intradia_programado_aplica_la_ocupacion_actual.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import statistics
import sys
import tempfile
import time
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

Z = ZoneInfo("America/Bogota")
CRON_POR_OMISION = "5 6-20 * * *"
HORA_INICIAL = 8                 # la primera franja: el --dia a las 8:05
FRANJAS = 4                      # 8:05, 9:05, 10:05 y 11:05
LLEGADA = timedelta(minutes=2)   # cada hora llega 2 min después de cerrar
RUTA = "CL 72"
LIMITE_RNF002_S = 2.0
LINEAS: list[str] = []


def log(texto: str = "") -> None:
    LINEAS.append(texto)
    print(texto, flush=True)


# ---------------------------------------------------------------- base local desechable
def base_nueva(nombre: str) -> str:
    """La URL de una base LOCAL recién creada (la borra si existía) y migrada hasta head. Nunca se imprime."""
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url

    from scripts import cola_servidor

    url = cola_servidor.url_local(nombre)
    if nombre in {"ai_frecuencias", "postgres"} or not nombre.startswith("ai_frecuencias_pruebas"):
        raise SystemExit("use una base desechable aparte (ai_frecuencias_pruebas_…)")
    admin = create_engine(make_url(url).set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = :n"), {"n": nombre})
        c.execute(text(f'DROP DATABASE IF EXISTS "{nombre}"'))
    admin.dispose()
    cola_servidor.preparar_base(url)
    return url


# ---------------------------------------------------------------- la captura en vivo de prueba y el reloj comprimido
def serie_con_llegada(dia: date):
    """La serie empaquetada del día y los dos previos con la llegada de cada hora: su cierre + LLEGADA."""
    import pandas as pd

    from app.servicios import datos

    tramo = datos.demanda_horaria(desde=dia - timedelta(days=2), hasta=dia).copy()
    cierre = pd.to_datetime(tramo["fecha"]) + pd.to_timedelta(tramo["hora"].astype(int) + 1, unit="h")
    tramo["ultima_actualizacion"] = (cierre + LLEGADA).dt.tz_localize(Z)
    return tramo


def captura_en_vivo(estado: SimpleNamespace) -> None:
    """La fuente de cada ciclo ve solo las horas que habían llegado a SU instante (el del trabajo que la cola acaba de
    entregar) y trae viajes por segmento para las franjas que pide; el refresco de segmentos queda anotado."""
    from app.modelos_db import Ejecucion
    from app.servicios import ejecucion, fuentes, segmentos_refresco
    from tests.integracion.test_ocupacion_ciclo import viajes_sinteticos

    class FuenteEnVivo(fuentes.FuenteParquet):
        def leer_carga_segmentos(self, franjas):
            estado.pedidas.append({"instante": estado.instante.isoformat(),
                                   "horas": sorted(h for r, f, h in franjas if r == RUTA and f == estado.dia)})
            return fuentes.seudonimizar_conductores(viajes_sinteticos(franjas))

        def viajes(self, ruta, desde, hasta):     # progvehiculos no se conoce: rige la duración máxima del viaje
            return None

    def obtener():
        llegadas = estado.tramo[estado.tramo["ultima_actualizacion"] <= estado.instante]
        f = FuenteEnVivo(cargador=lambda: llegadas.copy())
        f.proceso = estado.proceso
        return f

    leer_lote = ejecucion._leer_lote

    def leer_con_su_instante(s, execution_id):
        estado.instante = ejecucion.a_instante((s.get(Ejecucion, execution_id).parametros or {})["instante"])
        return leer_lote(s, execution_id)

    ejecucion.obtener_fuente = obtener
    ejecucion._leer_lote = leer_con_su_instante
    segmentos_refresco.encolar_tras_ciclo = estado.refrescos.append


def reloj_comprimido(estado: SimpleNamespace, dia: date) -> None:
    """El disparo k (minutos reales desde el primero) es el --dia a las (HORA_INICIAL + k):05; cada uno se repite dos
    segundos después como otra réplica. Después de FRANJAS disparos, nada."""
    from app.servicios import planificador

    tarea = planificador.tarea_ciclo_intradia

    def tarea_del_dia_comprimido(ahora=None):
        real = datetime.now(Z).replace(second=0, microsecond=0)
        estado.primer_disparo = estado.primer_disparo or real
        k = round((real - estado.primer_disparo).total_seconds() / 60)
        if k >= FRANJAS:
            return None
        simulado = datetime(dia.year, dia.month, dia.day, HORA_INICIAL + k, 5, 9, tzinfo=Z)
        nuevo = tarea(simulado)
        otra_replica = tarea(simulado + timedelta(seconds=2))
        estado.disparos.append({"simulado": simulado.isoformat(), "execution_id": str(nuevo) if nuevo else None,
                                "segunda_replica_encolo": otra_replica is not None})
        return nuevo

    planificador.tarea_ciclo_intradia = tarea_del_dia_comprimido


# ---------------------------------------------------------------- lo que dejó cada ciclo
def ejecuciones(motor) -> list[dict]:
    from sqlalchemy import text

    with motor.connect() as c:
        filas = c.execute(text(
            "SELECT e.execution_id, e.estado, e.programada_para, e.parametros, e.metricas, e.filas_leidas, "
            "e.worker_id, e.mensaje, "
            "(SELECT count(*) FROM ai_frecuencias.prediction p WHERE p.execution_id = e.execution_id) AS pred, "
            "(SELECT count(*) FROM ai_frecuencias.model_monitoring m WHERE m.execution_id = e.execution_id) AS mon, "
            "(SELECT count(*) FROM ai_frecuencias.feature_snapshot f WHERE f.execution_id = e.execution_id) AS foto, "
            "(SELECT count(*) FROM ai_frecuencias.recommendation r WHERE r.execution_id = e.execution_id) AS recs, "
            "(SELECT count(*) FROM ai_frecuencias.ocupacion_segmento o WHERE o.execution_id = e.execution_id) AS ocup, "
            "(SELECT max(a.ventana_fin) FROM ai_frecuencias.alert a WHERE a.execution_id = e.execution_id "
            " AND a.origen = 'observado') AS fin_alertas, "
            "(SELECT json_agg(json_build_object('inicio', a.ventana_inicio, 'fin', a.ventana_fin, "
            " 'metodo', a.variables ->> 'metodo_ocupacion') ORDER BY a.ventana_inicio) "
            " FROM ai_frecuencias.alert a WHERE a.execution_id = e.execution_id AND a.origen = 'observado' "
            " AND a.codigo = 'ALT-002' AND a.ruta = 'CL 72') AS alt002, "
            "(SELECT min(a.reclamado_en) FROM ai_frecuencias.execution_attempt a "
            " WHERE a.execution_id = e.execution_id) AS reclamado, "
            "(SELECT max(a.terminado_en) FROM ai_frecuencias.execution_attempt a "
            " WHERE a.execution_id = e.execution_id) AS fin_intento "
            "FROM ai_frecuencias.execution_log e WHERE e.tipo = 'frecuencia' ORDER BY e.programada_para"))
        return [dict(f._mapping) for f in filas]


def recomendaciones_de_la_franja(motor, execution_id) -> list[dict]:
    from sqlalchemy import text

    with motor.connect() as c:
        return [dict(f) for f in c.execute(text(
            "SELECT p.horizonte_min, r.hora, r.buses_hora, r.detalle -> 'salida' -> 'restriccion_reactiva' AS rr "
            "FROM ai_frecuencias.recommendation r JOIN ai_frecuencias.prediction p "
            "ON p.prediction_id = r.prediction_id WHERE r.execution_id = :e AND r.ruta = :ruta AND r.origen = 'franja' "
            "ORDER BY p.horizonte_min"), {"e": execution_id, "ruta": RUTA}).mappings()]


def plan_de_la_hora(motor, execution_id, hora: int) -> int | None:
    from sqlalchemy import text

    with motor.connect() as c:
        return c.execute(text(
            "SELECT buses_hora FROM ai_frecuencias.recommendation WHERE execution_id = :e AND ruta = :ruta "
            "AND origen = 'plan_dia' AND hora = :h"), {"e": execution_id, "ruta": RUTA, "h": hora}).scalar()


def _restriccion_del_plan(m: dict) -> dict:
    """La restricción reactiva de RUTA que resumen las métricas del plan del día ({} si no la hay)."""
    rutas = (m.get("plan_dia") or {}).get("rutas") or {}
    return (rutas.get(RUTA) or {}).get("restriccion_reactiva") or {}


def _duracion_s(x: dict) -> float | None:
    """Del reclamo de la cola al cierre del intento."""
    if not (x["fin_intento"] and x["reclamado"]):
        return None
    return (x["fin_intento"] - x["reclamado"]).total_seconds()


def resumen_del_ciclo(motor, x: dict) -> dict:
    m, p = x["metricas"] or {}, x["parametros"] or {}
    reactiva = _restriccion_del_plan(m)
    dur = _duracion_s(x)
    franja = x["programada_para"].astimezone(Z)
    return {"execution_id": str(x["execution_id"]), "franja": franja.isoformat(), "instante": p.get("instante"),
            "intradia": p.get("intradia"), "estado": x["estado"], "filas_leidas": x["filas_leidas"],
            "predicciones": x["pred"], "recomendaciones": x["recs"], "filas_foto_variables": x["foto"],
            "filas_ocupacion_segmento": x["ocup"], "filas_monitoreo": x["mon"],
            "consolidados": "consolidados" in (m.get("calidad") or {}), "nota_intradia": bool(m.get("intradia")),
            "fin_alertas_observadas": x["fin_alertas"].astimezone(Z).isoformat() if x["fin_alertas"] else None,
            "alt002_observadas_cl72": x["alt002"] or [],
            "restriccion_plan": {k: reactiva.get(k) for k in ("aplica", "hora_cerrada", "hora_aplica",
                                                              "ocupacion_observada", "salidas_minimas", "motivo")},
            "salidas_plan_en_la_hora": plan_de_la_hora(motor, x["execution_id"], franja.hour),
            "recomendaciones_franja": [{"horizonte_min": f["horizonte_min"], "hora": f["hora"],
                                        "buses_hora": f["buses_hora"], "restriccion_reactiva": f["rr"]}
                                       for f in recomendaciones_de_la_franja(motor, x["execution_id"])],
            "duracion_s": None if dur is None else round(dur, 2),
            "duracion_etapas_s": {k: (m.get(k) or {}).get("duracion_s") for k in ("plan_dia", "respuesta")},
            "worker_id": x["worker_id"], "reclamado": x["reclamado"], "fin_intento": x["fin_intento"]}


# ---------------------------------------------------------------- espera con la latencia de la consulta paginada
def hay_ciclo_corriendo(motor) -> bool:
    from sqlalchemy import text

    with motor.connect() as c:
        return bool(c.execute(text("SELECT count(*) FROM ai_frecuencias.execution_log "
                                   "WHERE tipo = 'frecuencia' AND estado = 'corriendo'")).scalar())


def esperar_midiendo(cliente, motor, limite_s: float) -> tuple[list[dict], list[dict]]:
    """Espera a que terminen FRANJAS ciclos; entre tanto, mide GET /api/v1/recommendations (50 filas)."""
    muestras: list[dict] = []
    t0 = time.monotonic()
    while time.monotonic() - t0 < limite_s:
        con_ciclo = hay_ciclo_corriendo(motor)
        inicio = time.perf_counter()
        r = cliente.get("/api/v1/recommendations", params={"limite": 50})
        muestras.append({"s": time.perf_counter() - inicio, "con_ciclo": con_ciclo, "estado": r.status_code})
        filas = ejecuciones(motor)
        if sum(1 for x in filas if x["estado"] in ("ok", "error")) >= FRANJAS:
            return filas, muestras
        time.sleep(0.25)
    raise SystemExit(f"tiempo agotado esperando {FRANJAS} ciclos intradía")


def latencias(muestras: list[dict]) -> dict:
    def resumen(xs: list[float]) -> dict:
        if not xs:
            return {"n": 0}
        orden = sorted(xs)
        p95 = orden[min(len(orden) - 1, int(round(0.95 * (len(orden) - 1))))]
        return {"n": len(xs), "p50_s": round(statistics.median(xs), 3), "p95_s": round(p95, 3),
                "max_s": round(max(xs), 3)}

    return {"con_ciclo_en_curso": resumen([m["s"] for m in muestras if m["con_ciclo"]]),
            "sin_ciclo": resumen([m["s"] for m in muestras if not m["con_ciclo"]]),
            "respuestas_no_200": sum(1 for m in muestras if m["estado"] != 200)}


# ---------------------------------------------------------------- comprobaciones
def _reactiva(r: dict) -> tuple:
    rr = r["restriccion_plan"]
    return rr.get("aplica"), rr.get("hora_cerrada"), rr.get("hora_aplica")


def _franja_con_piso(r: dict) -> bool:
    """Las recomendaciones de 30 y 60 min (hora principal = la de la franja) aplican la restricción; la de 120 min
    (hora principal = la siguiente) no la recibe."""
    hora = datetime.fromisoformat(r["franja"]).hour
    por_h = {f["horizonte_min"]: f for f in r["recomendaciones_franja"]}
    con_piso = all(por_h.get(h, {}).get("hora") == hora and (por_h[h]["restriccion_reactiva"] or {}).get("aplicada")
                   for h in (30, 60))
    return con_piso and por_h.get(120, {}).get("hora") == hora + 1 and not por_h[120]["restriccion_reactiva"]


def _hora_de(instante: str) -> int:
    return datetime.fromisoformat(instante).astimezone(Z).hour


def _alt002_del_episodio(r: dict) -> bool:
    """El ciclo alerta el episodio de CL 72 de las 7 y las 8 h (al 100 % en el segmento crítico): la hora de las 7 la
    midió el ciclo anterior y quedó guardada (ejecucion.ocupacion_del_dia); la de las 8, este."""
    return any(_hora_de(a["inicio"]) == HORA_INICIAL - 1 and _hora_de(a["fin"]) == HORA_INICIAL + 1
               and a["metodo"] == "segmento_critico" for a in r["alt002_observadas_cl72"])


def _solo_horas_cerradas(pedidas: list[dict]) -> bool:
    """Cada ciclo pidió la ocupación solo de horas ya cerradas a su instante y, desde el segundo, solo la hora que
    acababa de llegar (8, 9 y 10 h)."""
    cerradas = all(h + 1 <= datetime.fromisoformat(p["instante"]).hour for p in pedidas for h in p["horas"])
    return cerradas and [p["horas"] for p in pedidas[1:FRANJAS]] == [[h] for h in range(HORA_INICIAL, 11)]


def comprobaciones(resumen: list[dict], estado: SimpleNamespace, lat: dict, programado: dict) -> list[tuple]:
    franjas = [r["franja"] for r in resumen]
    trabajos = {t["id"]: t for t in programado.get("trabajos") or []}
    seguidas = all(a["fin_intento"] <= b["reclamado"] for a, b in zip(resumen, resumen[1:], strict=False))
    ocho, nueve, diez, once = resumen[:FRANJAS]
    return [
        ("el planificador tiene el trabajo ciclo_intradia", "ciclo_intradia" in trabajos),
        ("una fila por franja: la segunda réplica no encoló nada",
         len(set(franjas)) == len(franjas) == FRANJAS
         and not any(d["segunda_replica_encolo"] for d in estado.disparos)),
        ("cada ciclo es intradía, con instante = su franja",
         all(r["intradia"] is True and r["instante"] == r["franja"] and r["nota_intradia"] for r in resumen)),
        ("todos terminaron «ok» y la cola los procesó de uno en uno",
         all(r["estado"] == "ok" for r in resumen) and seguidas),
        ("el primero leyó el histórico y cada siguiente solo la hora que llegó (3 rutas)",
         ocho["filas_leidas"] > 3 and all(r["filas_leidas"] == 3 for r in resumen[1:])),
        ("la ocupación actual se midió solo en horas cerradas, y cada vez la de la hora que llegó",
         _solo_horas_cerradas(estado.pedidas)),
        ("8:05: la restricción actúa a las 8 h con la ocupación de las 7 h", _reactiva(ocho) == (True, 7, 8)),
        ("9:05: actúa a las 9 h con la ocupación de las 8 h", _reactiva(nueve) == (True, 8, 9)),
        ("10:05: con la ocupación de las 9 h bajo el umbral no actúa y lo dice",
         _reactiva(diez) == (False, 9, 10) and "por debajo del umbral" in (diez["restriccion_plan"]["motivo"] or "")),
        ("11:05: sin viajes medidos en la hora que llegó, el plan es el de siempre", _reactiva(once) == (None,) * 3),
        ("el plan del día en curso no baja del piso en la hora en que actúa",
         all(r["salidas_plan_en_la_hora"] >= r["restriccion_plan"]["salidas_minimas"] for r in (ocho, nueve))),
        ("las de 30 y 60 min de esa hora aplican la misma restricción; la de 120 min no",
         _franja_con_piso(ocho) and _franja_con_piso(nueve)),
        ("9:05: ALT-002 del episodio de las 7 y 8 h en el segmento crítico, con la hora de las 7 que midió el ciclo "
         "de las 8:05", not ocho["alt002_observadas_cl72"] and _alt002_del_episodio(nueve)),
        ("ningún ciclo intradía guardó monitoreo, leyó los consolidados ni pidió el refresco de segmentos",
         all(r["filas_monitoreo"] == 0 and not r["consolidados"] for r in resumen) and estado.refrescos == []),
        ("ninguna alerta observada por horas que todavía no pasaron",
         all(r["fin_alertas_observadas"] is None or r["fin_alertas_observadas"] <= r["franja"][:13] + ":00:00-05:00"
             for r in resumen)),
        (f"la consulta paginada con un ciclo en curso: p95 < {LIMITE_RNF002_S:.0f} s (RNF-002) y siempre 200",
         lat["con_ciclo_en_curso"].get("n", 0) > 0 and lat["con_ciclo_en_curso"]["p95_s"] < LIMITE_RNF002_S
         and lat["respuestas_no_200"] == 0),
    ]


# ---------------------------------------------------------------- informe
def lineas_de_la_recomendacion(f: dict) -> list[str]:
    """La recomendación de una franja (30, 60 o 120 min) con su restricción reactiva, si la tocó."""
    x = f["restriccion_reactiva"] or {}
    cabeza = f"      recomendación de {f['horizonte_min']} min (hora {f['hora']}): {f['buses_hora']} buses/h; "
    if not x:
        return [cabeza + "sin restricción en esta hora"]
    lineas = [cabeza + f"restricción aplicada={x.get('aplicada')} sin piso={x.get('buses_hora_sin_piso')} "
                       f"pedidas={x.get('salidas_pedidas')} piso={x.get('salidas_minimas')} "
                       f"limitada_por_flota={x.get('limitada_por_flota')}"]
    if x.get("formula"):
        lineas.append(f"         fórmula: {x['formula']}")
    return lineas


def informe(resumen: list[dict], lat: dict, revision: list[tuple], programado: dict) -> None:
    ciclo = next((t for t in programado.get("trabajos") or [] if t["id"] == "ciclo_intradia"), {})
    log(f"GET /api/v1/scheduler -> ciclo_intradia cron={ciclo.get('cron')!r} próxima={ciclo.get('proxima')}")
    log()
    log("Ciclos intradía encolados por el planificador y procesados por la cola:")
    for r in resumen:
        rr = r["restriccion_plan"]
        log(f"   franja {r['franja']}  estado={r['estado']}  filas_leidas={r['filas_leidas']}  "
            f"predicciones={r['predicciones']}  recomendaciones={r['recomendaciones']}  "
            f"foto_variables={r['filas_foto_variables']}  ocupacion_segmento={r['filas_ocupacion_segmento']}  "
            f"monitoreo={r['filas_monitoreo']}  duración={r['duracion_s']} s  worker={r['worker_id']}")
        log(f"      restricción del plan: aplica={rr['aplica']} hora_cerrada={rr['hora_cerrada']} "
            f"hora_aplica={rr['hora_aplica']} salidas_minimas={rr['salidas_minimas']}; salidas del plan a esa hora: "
            f"{r['salidas_plan_en_la_hora']}")
        log(f"      motivo: {rr['motivo']}")
        for a in r["alt002_observadas_cl72"]:
            log(f"      ALT-002 observada de CL 72 abierta en este ciclo: {_hora_de(a['inicio'])}:00 a "
                f"{_hora_de(a['fin'])}:00, medida con {a['metodo']}")
        for f in r["recomendaciones_franja"]:
            for linea in lineas_de_la_recomendacion(f):
                log(linea)
    log()
    log(f"Consulta paginada GET /api/v1/recommendations (50 filas): con un ciclo en curso "
        f"{json.dumps(lat['con_ciclo_en_curso'])}; sin ciclo {json.dumps(lat['sin_ciclo'])}")
    log()
    for nombre, ok in revision:
        log(f"   [{'OK' if ok else 'FALLA'}] {nombre}")
    log()
    log("RESULTADO: " + ("TODO OK" if all(ok for _, ok in revision) else "HAY FALLAS"))


def entorno(url: str, datos_tmp: Path) -> None:
    os.environ.update({
        "DATABASE_URL": url, "DATA_DIR": str(datos_tmp), "MODELOS_DIR": str(datos_tmp / "modelos"),
        "FUENTE": "postgres", "PLANIFICADOR_HABILITADO": "true", "PLAN_INTRADIA_CRON": "*/1 * * * *",
        "PLAN_EJECUCION_CRON": "0 3 1 1 *", "PLAN_REENTRENAMIENTO_CRON": "0 3 1 1 *", "PLAN_RETENCION_CRON": "",
        "AUTH_HABILITADA": "false", "REANUDAR_EJECUCIONES": "true", "TRABAJADORES": "1", "OTEL_EXPORTADOR": "ninguno",
        "MAX_REINTENTOS": "1", "SONDEO_COLA_SEGUNDOS": "1", "ENTORNO": "local",
        "SEUDONIMO_SECRETO": f"evidencia-{uuid.uuid4().hex}"})
    os.environ.pop("FUENTE_DATABASE_URL", None)


def correr(cliente, motor, estado: SimpleNamespace) -> tuple[list[dict], dict, dict]:
    from app.config import obtener_ajustes

    # APScheduler quedó disparando cada minuto real; desde aquí la tarea calcula la franja con el cron por omisión
    obtener_ajustes().plan_intradia_cron = CRON_POR_OMISION
    programado = cliente.get("/api/v1/scheduler").json()
    filas, muestras = esperar_midiendo(cliente, motor, 600)
    hechas = [x for x in filas if x["estado"] in ("ok", "error")][:FRANJAS]
    return [resumen_del_ciclo(motor, x) for x in hechas], latencias(muestras), programado


def main(argv=None) -> None:
    a = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    a.add_argument("--base-datos", default="ai_frecuencias_pruebas_intradia")
    a.add_argument("--salida", type=Path)
    a.add_argument("--json", type=Path)
    args = a.parse_args(argv)
    from sqlalchemy import create_engine

    from tests.integracion.test_ocupacion_ciclo import DIA  # el día de los viajes por segmento de prueba

    url = base_nueva(args.base_datos)
    tmp = Path(tempfile.mkdtemp(prefix="planificador_intradia_"))
    shutil.copytree(RAIZ / "datos", tmp / "datos")
    entorno(url, tmp / "datos")
    motor = create_engine(url)
    estado = SimpleNamespace(dia=DIA, tramo=serie_con_llegada(DIA), instante=None, pedidas=[], refrescos=[],
                             disparos=[], primer_disparo=None, proceso=f"evidencia-intradia-{uuid.uuid4().hex[:8]}")
    captura_en_vivo(estado)
    reloj_comprimido(estado, DIA)
    from fastapi.testclient import TestClient

    from app.main import app

    log(f"§10.1 · ciclo intradía PROGRAMADO con la ocupación actual ({datetime.now():%Y-%m-%d %H:%M:%S}, Windows 11, "
        "PostgreSQL local)")
    log(f"Base local desechable {args.base_datos}, migrada desde cero; datos en una copia temporal. Planificador real "
        "(APScheduler) y cola real (TRABAJADORES=1): ninguna ejecución se crea con POST. Día comprimido: cada minuto "
        f"real es la hora siguiente del {DIA} desde las {HORA_INICIAL}:05, con la franja calculada con "
        f"PLAN_INTRADIA_CRON por omisión «{CRON_POR_OMISION}»; cada hora llega 2 min después de cerrar.")
    try:
        with TestClient(app) as cliente:
            resumen, lat, programado = correr(cliente, motor, estado)
    finally:
        motor.dispose()
        shutil.rmtree(tmp, ignore_errors=True)
    revision = comprobaciones(resumen, estado, lat, programado)
    informe(resumen, lat, revision, programado)
    datos_json = {"dia": DIA.isoformat(), "cron_por_omision": CRON_POR_OMISION, "franjas": resumen,
                  "disparos": estado.disparos, "horas_de_ocupacion_pedidas": estado.pedidas,
                  "refrescos_pedidos": len(estado.refrescos), "latencia_consulta_paginada": lat,
                  "comprobaciones": {n: ok for n, ok in revision}}
    for destino, texto in ((args.salida, "\n".join(LINEAS) + "\n"),
                           (args.json, json.dumps(datos_json, ensure_ascii=False, indent=1, default=str) + "\n")):
        if destino:
            destino.parent.mkdir(parents=True, exist_ok=True)
            destino.write_text(texto, encoding="utf-8")
    if not all(ok for _, ok in revision):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
