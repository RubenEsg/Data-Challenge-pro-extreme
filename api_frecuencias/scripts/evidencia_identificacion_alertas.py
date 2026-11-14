"""Evidencia de §5.3 «Empresa, ruta, sentido, viaje, conductor y vehículo, cuando aplique» con datos reales.

Lee la réplica LOCAL de la base de Extreme en SOLO LECTURA como lector_ia (fuentes.FuentePostgresSoloLectura: lista
blanca, READ ONLY, statement_timeout, ROLLBACK); nunca la base compartida del reto ni escribe en ninguna base.

A. ALT-006 en el periodo del backtest de observadas (15/09 a 31/12/2025): los contextos del ciclo con la serie
   empaquetada (scripts/backtest_alertas._contextos) y, para cada ruta y día con ALT-006, los viajes de ese día de
   progvehiculos (FuentePostgresSoloLectura.viajes sin conteo de segmentos: la capa de segmentos no cubre 2025). Mide
   cuántas ALT-006 identifican el despacho (cancelado, tardío o sin finalizar), cuántas no tienen ninguno (déficit de
   programación) y comprueba que los viajes válidos de la ventana son las salidas de la serie horaria.
B. ALT-009 en la lectura integrada de la réplica (demanda_segmentos, la capa de segmentos de enero y febrero de 2023):
   las horas de servicio que no llegan (ningún viaje con timbradas de segmento) y los viajes de esas horas, con su
   conteo de filas de timbradas_segmentos.
C. El sentido: qué parte de los segmentos de su ruta toca cada viaje en timbradas_segmentos. El supuesto S9 parte el
   ciclo en dos mitades; un viaje que toca más de la mitad recorre los dos sentidos.
D. La variante «segmento_critico» de ALT-002 observada (alertas.VARIANTES_5_3): con la ocupación actual por segmento
   del ciclo integrado (fuentes.leer_carga_segmentos + app/servicios/ocupacion.py, lo mismo que hace
   ejecucion.con_ocupacion_por_segmento) sobre las franjas de la capa de segmentos de la réplica, cuántas horas traen el
   segmento crítico con su sentido aproximado y su viaje más cargado, y las ALT-002 que salen, con su identificación.

Escribe docs/evidencias/alertas/identificacion_viajes.json y .md, con la tabla de qué campos aplican a cada regla y a
cada variante. El conductor sale de las fuentes solo como seudónimo (HMAC con SEUDONIMO_SECRETO) y esta evidencia no
copia ninguno: solo cuenta cuántas alertas lo traen.

Uso (desde EntregaFinal/api_frecuencias, con la réplica levantada y LECTOR_IA_PASSWORD en el .env):
  python scripts/evidencia_identificacion_alertas.py
"""
from __future__ import annotations

import json
import os
import sys
import time
from collections import Counter
from datetime import date, datetime, timedelta
from datetime import time as dtime
from pathlib import Path
from zoneinfo import ZoneInfo

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

ZONA = ZoneInfo("America/Bogota")
SALIDA = RAIZ / "docs" / "evidencias" / "alertas"
DESDE_2025, HASTA_2025 = date(2025, 9, 15), date(2025, 12, 31)
MAX_EJEMPLOS = 5


def _secreto() -> None:
    """SEUDONIMO_SECRETO del .env local si el entorno no lo trae (sin él el conductor sale nulo); nunca se muestra."""
    if os.environ.get("SEUDONIMO_SECRETO"):
        return
    archivo = RAIZ / ".env"
    if archivo.exists():
        for linea in archivo.read_text(encoding="utf-8").splitlines():
            if linea.startswith("SEUDONIMO_SECRETO="):
                os.environ["SEUDONIMO_SECRETO"] = linea.split("=", 1)[1].strip()


def fuente_replica(tabla: str):
    """FuentePostgresSoloLectura sobre la réplica local como lector_ia (la URL se arma aquí y no se imprime)."""
    from app.servicios.fuentes import FuentePostgresSoloLectura
    from scripts import replica_comun as rc

    url = rc.url_rol("lector_ia")
    if not url:
        raise SystemExit("Falta LECTOR_IA_PASSWORD (réplica local): no se puede medir con datos reales.")
    return FuentePostgresSoloLectura(url=url.replace("postgresql://", "postgresql+psycopg://", 1), tabla=tabla,
                                     statement_timeout_ms=180000)


def _dia(fecha: date) -> tuple[datetime, datetime]:
    inicio = datetime.combine(fecha, dtime(0), tzinfo=ZONA)
    return inicio, inicio + timedelta(days=1)


def _viajes(fuente, ruta: str, fecha: date, con_segmentos: bool) -> list[dict]:
    from app.servicios import alertas

    tabla = fuente.viajes(ruta, *_dia(fecha), con_segmentos=con_segmentos)
    return [alertas.viaje_de_fila(f) for f in tabla.to_dict("records")]


def _iso(v):
    return v.isoformat() if hasattr(v, "isoformat") else v


def _ejemplo(a: dict) -> dict:
    """Lo que la evidencia muestra de una alerta: sin el seudónimo (solo si lo trae)."""
    v = a["variables"]
    return {"codigo": a["codigo"], "ruta": a["ruta"], "clave_dedup": a["clave_dedup"],
            "ventana_inicio": _iso(a.get("ventana_inicio")), "ventana_fin": _iso(a.get("ventana_fin")),
            "viaje": a["viaje"], "vehiculo": a["vehiculo"], "conductor_seudonimizado": bool(a["conductor"]),
            "identificacion_5_3": v["identificacion_5_3"], "explicacion": a["explicacion"]}


# ---------------------------------------------------------------- A. ALT-006 con la serie empaquetada de 2025
def _contextos_2025():
    from app.servicios import alertas, datos, inferencia
    from scripts import backtest_alertas as B

    modelo = inferencia.cargar(None)
    pron = B._pronosticos(modelo, inferencia, inferencia.tabla_variables(), DESDE_2025, HASTA_2025)
    par = datos.parametros_operativos()
    parametros = {(r, t, int(x)): float(v) for r, t, x, v in zip(par["ruta"], par["tipo_dia"], par["hora"],
                                                                  par["intervalo_programado_min"], strict=False)}
    ctxs, _h, _d = B._contextos(datos.demanda_horaria(), pron, parametros, datos, alertas, DESDE_2025, HASTA_2025)
    return ctxs


def _registrar_006(a: dict, acum: dict) -> None:
    v = a["variables"]
    ident = v["identificacion_5_3"]
    acum["alertas"] += 1
    acum["resultado"][ident.get("rol_viaje") or ident["resultado"]] += 1
    acum["con_viaje"] += int(a["viaje"] is not None)
    acum["con_conductor"] += int(a["conductor"] is not None)
    ventana = v["viajes_ventana"]
    acum["salidas_iguales"] += int(ventana["valido"] == round(float(v.get("salidas_observadas") or 0)))
    acum["con_ultimo_despacho"] += int(v.get("ultimo_despacho_previo") is not None)
    if len(acum["ejemplos"]) < MAX_EJEMPLOS and a["viaje"] is not None:
        acum["ejemplos"].append(_ejemplo(a))


def medir_alt006() -> dict:
    """Las ALT-006 del periodo, cada una con los viajes reales de su ruta y su día."""
    from app.servicios import alertas

    t0 = time.perf_counter()
    u = alertas._umbrales(None)
    fuente = fuente_replica("timbradas_consolidado")          # no lee la capa de segmentos: sin conteo
    acum = {"alertas": 0, "con_viaje": 0, "con_conductor": 0, "salidas_iguales": 0, "con_ultimo_despacho": 0,
            "resultado": Counter(), "ejemplos": [], "dias_ruta_leidos": 0}
    for (ruta, fecha), ctx in sorted(_contextos_2025().items()):
        if not any(a["codigo"] == "ALT-006" for a in alertas.evaluar_observadas(ctx, u)):
            continue
        acum["dias_ruta_leidos"] += 1
        con_viajes = dict(ctx, viajes=_viajes(fuente, ruta, fecha, con_segmentos=False))
        for a in alertas.evaluar_observadas(con_viajes, u):
            if a["codigo"] == "ALT-006":
                _registrar_006(a, acum)
    acum["resultado"] = dict(acum["resultado"])
    acum["duracion_s"] = round(time.perf_counter() - t0, 1)
    return acum


# ---------------------------------------------------------------- B. ALT-009 con la lectura integrada de 2023
def _horas_faltantes(d) -> dict:
    """{(ruta, fecha): [horas de servicio que faltan hasta la última que llegó]} de la lectura demanda_segmentos (la
    misma regla de ejecucion.contexto_observado)."""
    from app.servicios import datos

    salida = {}
    for (ruta, fecha), g in d.groupby(["ruta", "fecha"]):
        presentes = {int(h) for h in g["hora"]}
        ultima = max(presentes)
        faltan = [h for h in datos.HORAS_SERVICIO if h <= ultima and h not in presentes]
        if faltan:
            salida[(str(ruta), fecha)] = faltan
    return salida


def _registrar_009(a: dict, acum: dict) -> None:
    v = a["variables"]
    ident, faltan = v["identificacion_5_3"], v["viajes_con_datos_faltantes"]
    acum["alertas"] += 1
    acum["resultado"][ident["resultado"]] += 1
    acum["con_viaje"] += int(a["viaje"] is not None)
    acum["con_conductor"] += int(a["conductor"] is not None)
    acum["viajes_incompletos"] += faltan["total"]
    acum["incompletos_en_horas_faltantes"] += faltan["en_horas_faltantes"]
    acum["programados_en_horas_faltantes"] += faltan["programados_en_horas_faltantes"]
    acum["horas_sin_viajes_programados"] += len(v.get("horas_sin_viajes_programados") or [])
    for x in faltan["lista"]:
        acum["motivos"].update(x["faltantes"])
    if len(acum["ejemplos"]) < MAX_EJEMPLOS and a["viaje"] is not None:
        acum["ejemplos"].append(_ejemplo(a))


def lectura_integrada():
    """La lectura integrada del ciclo (demanda_segmentos) de toda la réplica, con la fecha como date."""
    from app.servicios import fuentes

    fuente = fuente_replica(fuentes.TABLA_CICLO)
    d, _ = fuente.leer_incremental(None)
    d["fecha"] = [x if isinstance(x, date) else date.fromisoformat(str(x)[:10]) for x in d["fecha"]]
    return fuente, d


def medir_alt009(fuente, d) -> dict:
    """Las ALT-009 por horas faltantes de la lectura integrada (lo que el ciclo con FUENTE=postgres no recibe) con
    los viajes de esas horas y su conteo de segmentos."""
    from app.servicios import alertas

    t0 = time.perf_counter()
    faltantes = _horas_faltantes(d)
    acum = {"filas_leidas": len(d), "dias_ruta": int(d.groupby(["ruta", "fecha"]).ngroups),
            "dias_ruta_con_horas_faltantes": len(faltantes), "horas_faltantes": sum(map(len, faltantes.values())),
            "periodo": [str(min(d["fecha"])), str(max(d["fecha"]))], "alertas": 0, "con_viaje": 0,
            "con_conductor": 0, "viajes_incompletos": 0, "incompletos_en_horas_faltantes": 0,
            "programados_en_horas_faltantes": 0, "dias_ruta_sin_alerta": 0, "horas_sin_viajes_programados": 0,
            "resultado": Counter(), "motivos": Counter(), "ejemplos": []}
    for (ruta, fecha), horas in sorted(faltantes.items()):
        inicio, _fin = _dia(fecha)
        ctx = {"ruta": ruta, "empresa": "SOBUSA", "detectada_en": inicio + timedelta(days=1, hours=6),
               "viajes": _viajes(fuente, ruta, fecha, con_segmentos=True),
               "datos": {"minutos_sin_datos": None, "campos_faltantes": [], "fecha": fecha,
                         "horas_faltantes": [(inicio + timedelta(hours=h)).isoformat() for h in horas]}}
        emitidas = [a for a in alertas.evaluar_observadas(ctx) if a["codigo"] == "ALT-009"]
        if not emitidas:            # ninguna hora faltante tenía servicio programado: nada que capturar
            acum["dias_ruta_sin_alerta"] += 1
            acum["horas_sin_viajes_programados"] += len(horas)
        for a in emitidas:
            _registrar_009(a, acum)
    acum["resultado"], acum["motivos"] = dict(acum["resultado"]), dict(acum["motivos"])
    acum["duracion_s"] = round(time.perf_counter() - t0, 1)
    return acum


# ---------------------------------------------------------------- D. ALT-002 medida en el segmento crítico (§10.1)
def _horas_del_dia(fecha: date, g, resumen: dict) -> list[dict]:
    """Las horas de una ruta y un día del lote integrado, cada una con el resumen de su segmento crítico si tiene
    ocupación medida por segmento (lo que hace ejecucion.con_ocupacion_por_segmento en el ciclo)."""
    from app.servicios import alertas

    inicio = datetime.combine(fecha, dtime(0), tzinfo=ZONA)
    horas = []
    for x in g.sort_values("hora").itertuples(index=False):
        h = alertas.contexto_hora(inicio + timedelta(hours=int(x.hora)), float(x.pasajeros), None, None, None,
                                  int(x.salidas))
        if (fecha, int(x.hora)) in resumen:
            h["segmento_critico"] = resumen[(fecha, int(x.hora))]
        horas.append(h)
    return horas


def _registrar_segmento(seg: dict, acum: dict) -> None:
    viaje = seg.get("viaje") or {}
    acum["horas_con_segmento_critico"] += 1
    acum["con_sentido"] += int(bool(seg.get("sentido")))
    acum["con_viaje_mas_cargado"] += int(viaje.get("id_viaje") is not None)
    acum["con_vehiculo"] += int(viaje.get("vehiculo") is not None)
    acum["con_conductor_seudonimizado"] += int(viaje.get("conductor") is not None)
    acum["ocupacion_media_maxima"] = max(acum["ocupacion_media_maxima"], float(seg.get("ocupacion_media") or 0.0))


def _registrar_002(a: dict, acum: dict) -> None:
    v = a["variables"]
    metodo = v.get("metodo_ocupacion") or "?"
    acum["alt002_por_metodo"][metodo] += 1
    if (v.get("identificacion_5_3") or {}).get("variante") != "segmento_critico":
        return
    acum["alt002_segmento_critico"] += 1
    acum["alt002_con_sentido"] += int(bool(a.get("sentido")))
    acum["alt002_con_viaje"] += int(a.get("viaje") is not None)
    acum["alt002_con_conductor"] += int(a.get("conductor") is not None)
    if len(acum["ejemplos"]) < MAX_EJEMPLOS:
        acum["ejemplos"].append(_ejemplo(a) | {"sentido": a.get("sentido")})


def medir_alt002_segmento(fuente, d) -> dict:
    """ALT-002 observada con la ocupación actual por segmento de cada día de la capa de segmentos de la réplica: lee
    viaje × segmento de las franjas del día (fuentes.leer_carga_segmentos, solo lectura, conductor seudonimizado), arma
    el segmento crítico de cada hora (ocupacion.calcular_observada y resumen_por_hora) y evalúa las reglas
    observadas."""
    from app.servicios import alertas, ocupacion

    t0 = time.perf_counter()
    capacidades = ocupacion.capacidades_de(sorted({str(r) for r in d["ruta"]}), None, None)
    acum = {"dias": 0, "franjas": int(len(d)), "horas_con_segmento_critico": 0, "con_sentido": 0,
            "con_viaje_mas_cargado": 0, "con_vehiculo": 0, "con_conductor_seudonimizado": 0,
            "ocupacion_media_maxima": 0.0, "alt002_por_metodo": Counter(), "alt002_segmento_critico": 0,
            "alt002_con_sentido": 0, "alt002_con_viaje": 0, "alt002_con_conductor": 0, "ejemplos": []}
    for fecha, del_dia in d.groupby("fecha"):
        acum["dias"] += 1
        filas = fuente.leer_carga_segmentos([(str(r), fecha, int(h)) for r, h in zip(del_dia["ruta"], del_dia["hora"],
                                                                                      strict=True)])
        por_ruta = ocupacion.resumen_por_hora(ocupacion.calcular_observada(filas, capacidades), filas)
        for ruta, g in del_dia.groupby("ruta"):
            resumen = por_ruta.get(str(ruta), {})
            for seg in resumen.values():
                _registrar_segmento(seg, acum)
            ctx = {"ruta": str(ruta), "empresa": "SOBUSA", "detectada_en": datetime.combine(
                fecha, dtime(0), tzinfo=ZONA) + timedelta(days=1, hours=6), "horas": _horas_del_dia(fecha, g, resumen)}
            for a in alertas.evaluar_observadas(ctx):
                if a["codigo"] == "ALT-002":
                    _registrar_002(a, acum)
    acum["alt002_por_metodo"] = dict(acum["alt002_por_metodo"])
    acum["ocupacion_media_maxima"] = round(acum["ocupacion_media_maxima"], 4)
    acum["duracion_s"] = round(time.perf_counter() - t0, 1)
    return acum


# ---------------------------------------------------------------- C. el sentido: cada viaje recorre el circuito
_SQL_CIRCUITO = """
WITH por_viaje AS (
    SELECT ts.id_viaje, rs.idruta, rs.id_config, COUNT(DISTINCT ts.id_segmento) AS tocados
      FROM timbradas_segmentos ts
      JOIN rutas_segmentos rs ON rs.id = ts.id_segmento
     GROUP BY ts.id_viaje, rs.idruta, rs.id_config
), configuracion AS (
    SELECT id_config, COUNT(*) AS segmentos FROM rutas_segmentos GROUP BY id_config
)
SELECT r.nombre AS ruta, COUNT(*) AS viajes, MAX(c.segmentos) AS segmentos_ruta,
       percentile_cont(0.1) WITHIN GROUP (ORDER BY CAST(p.tocados AS double precision) / c.segmentos) AS p10,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY CAST(p.tocados AS double precision) / c.segmentos) AS mediana,
       AVG(CASE WHEN 2 * p.tocados > c.segmentos THEN 1.0 ELSE 0.0 END) AS mas_de_medio_circuito
  FROM por_viaje p
  JOIN configuracion c ON c.id_config = p.id_config
  JOIN rutas r ON r.idruta = p.idruta
 GROUP BY r.nombre
 ORDER BY r.nombre
"""


def medir_circuito() -> dict:
    """§5.3 «sentido»: la parte de los segmentos de su ruta (su configuración) que toca cada viaje en
    timbradas_segmentos. Un segmento sin subidas ni bajadas puede no tener fila, así que la parte medida es una cota
    inferior del recorrido."""
    from app.servicios import fuentes

    t0 = time.perf_counter()
    d = fuente_replica(fuentes.TABLA_CICLO).consultar(_SQL_CIRCUITO)
    filas = [{"ruta": str(f["ruta"]), "viajes": int(f["viajes"]), "segmentos_ruta": int(f["segmentos_ruta"]),
              "p10": round(float(f["p10"]), 3), "mediana": round(float(f["mediana"]), 3),
              "mas_de_medio_circuito": round(float(f["mas_de_medio_circuito"]), 4)} for f in d.to_dict("records")]
    return {"por_ruta": filas, "duracion_s": round(time.perf_counter() - t0, 1)}


def _fraccion(x: float) -> str:
    return f"{x:.3f}".replace(".", ",")


def _informe_circuito(c: dict | None) -> list[str]:
    """La sección C del informe: el sentido no aplica porque cada viaje recorre los dos sentidos."""
    if not c:
        return []
    lin = ["", "## C. El sentido: cada viaje recorre el circuito (réplica, capa de segmentos)", "",
           "Parte de los segmentos de su ruta que toca cada viaje en `timbradas_segmentos` (cota inferior: un segmento "
           "sin subidas ni bajadas puede no tener fila). El supuesto S9 parte el ciclo en dos mitades (ida y regreso): "
           "un viaje que toca más de la mitad recorre los dos sentidos, así que ni la alerta de un viaje ni la de la "
           f"ruta tienen un solo sentido (medido en {str(c['duracion_s']).replace('.', ',')} s).", "",
           "| Ruta | Viajes | Segmentos de la ruta | P10 de la parte tocada | Mediana | Viajes con más de medio "
           "circuito |", "|---|---|---|---|---|---|"]
    return lin + [f"| {x['ruta']} | {x['viajes']} | {x['segmentos_ruta']} | {_fraccion(x['p10'])} | "
                  f"{_fraccion(x['mediana'])} | {_pct(x['mas_de_medio_circuito'], 1)} |" for x in c["por_ruta"]]


def _informe_segmento(s: dict | None) -> list[str]:
    """La sección D del informe: la variante «segmento_critico» de ALT-002 con la ocupación medida por segmento."""
    if not s:
        return []
    metodos = ", ".join(f"{k}: {v}" for k, v in sorted(s["alt002_por_metodo"].items())) or "ninguna"
    return ["", "## D. ALT-002 medida en el segmento crítico (réplica, ocupación actual por segmento)", "",
            f"Las {s['franjas']} franjas de la capa de segmentos ({s['dias']} días), leídas viaje × segmento con "
            "`fuentes.leer_carga_segmentos` (solo lectura, el conductor ya seudonimizado) y resumidas con "
            "`app/servicios/ocupacion.py` como en el ciclo integrado; cada hora lleva su segmento crítico "
            f"(`ejecucion.con_ocupacion_por_segmento`) y se evalúan las reglas observadas "
            f"({str(s['duracion_s']).replace('.', ',')} s).", "",
            "| Medida | Valor |", "|---|---|",
            f"| Horas con segmento crítico medido | {s['horas_con_segmento_critico']} |",
            f"| … con sentido aproximado | {s['con_sentido']} "
            f"({_pct(s['con_sentido'], s['horas_con_segmento_critico'])}) |",
            f"| … con el viaje más cargado | {s['con_viaje_mas_cargado']} "
            f"({_pct(s['con_viaje_mas_cargado'], s['horas_con_segmento_critico'])}) |",
            f"| … con su vehículo | {s['con_vehiculo']} |",
            f"| … con el seudónimo de su conductor | {s['con_conductor_seudonimizado']} |",
            f"| Ocupación media máxima del segmento crítico en una hora | "
            f"{_pct(s['ocupacion_media_maxima'], 1)} |",
            f"| ALT-002 observadas por método | {metodos} |",
            f"| ALT-002 con la variante segmento_critico | {s['alt002_segmento_critico']} |",
            f"| … con sentido / viaje / conductor | {s['alt002_con_sentido']} / {s['alt002_con_viaje']} / "
            f"{s['alt002_con_conductor']} |"]


# ---------------------------------------------------------------- informe
def _tabla_reglas() -> list[dict]:
    from app.servicios import alertas

    return [{"codigo": c, "nombre": alertas.CATALOGO[c][0], "aplica": list(aplica), "motivo": motivo,
             "sentido": alertas.SENTIDO_NO_APLICA} for c, (aplica, motivo) in alertas.IDENTIFICACION_5_3.items()]


def _tabla_variantes() -> list[dict]:
    """Las variantes de una regla con otra identificación (alertas.VARIANTES_5_3): la ALT-002 observada medida en el
    segmento crítico nombra su sentido aproximado y su viaje más cargado."""
    from app.servicios import alertas

    return [{"codigo": c, "variante": v, "nombre": alertas.CATALOGO[c][0], "aplica": list(aplica), "motivo": motivo,
             "sentido": sentido} for (c, v), (aplica, motivo, sentido) in alertas.VARIANTES_5_3.items()]


def _pct(a, b) -> str:
    return "—" if not b else f"{100 * a / b:.1f}".replace(".", ",") + " %"


def informe(r: dict) -> str:
    a6, a9 = r["alt006"], r["alt009"]
    lin = ["# §5.3 Empresa, ruta, sentido, viaje, conductor y vehículo, cuando aplique", "",
           f"Generado {r['generado']} con `scripts/evidencia_identificacion_alertas.py`, leyendo la réplica local en "
           "solo lectura como `lector_ia` (el mismo SELECT de la lista blanca que usa el ciclo, "
           "`fuentes.FuentePostgresSoloLectura.viajes`). El conductor solo sale como seudónimo (HMAC con "
           "`SEUDONIMO_SECRETO`, §18) y esta evidencia no copia ninguno.", "",
           "## Qué campos aplican a cada regla (`alertas.IDENTIFICACION_5_3` y `alertas.VARIANTES_5_3`)", "",
           "La empresa (catálogo) y la ruta (con su `idruta`) aplican a todas. El sentido no aplica a las reglas por "
           "ruta de este motor: " + r["reglas"][0]["sentido"].removeprefix("no aplica: ") + " (medido en la sección "
           "C). La excepción son las variantes de `VARIANTES_5_3`: la ALT-002 observada medida en el segmento crítico "
           "de la hora (§10.1) lleva el sentido aproximado de ese segmento y el viaje más cargado en él (sección D). "
           "Cada alerta lo dice en `variables.identificacion_5_3`.", "",
           "| Código | Alerta | Viaje, vehículo y conductor | Por qué |", "|---|---|---|---|"]
    for x in r["reglas"]:
        lin.append(f"| {x['codigo']} | {x['nombre']} | {'aplican' if x['aplica'] else 'no aplican'} | {x['motivo']} |")
    lin += ["", "| Código | Variante | Campos que aplican | Sentido | Por qué |", "|---|---|---|---|---|"]
    lin += [f"| {x['codigo']} | `{x['variante']}` | {', '.join(x['aplica'])} | {x['sentido']} | {x['motivo']} |"
            for x in r.get("variantes") or []]
    lin += ["", "Cuando aplican, la alerta guarda el viaje (`progvehiculos.idprogramacion`), el vehículo "
                "(`idvehiculo`) y el seudónimo del conductor del viaje principal, y en `variables` la lista de los "
                "viajes de la ventana (hasta 10) con su estado, su retraso y su seudónimo.", "",
            f"## A. ALT-006 con los viajes reales ({r['periodo_2025'][0]} a {r['periodo_2025'][1]})", "",
            "Contextos del ciclo con la serie empaquetada (los del backtest de observadas) y los viajes de cada ruta y "
            f"día con ALT-006 ({a6['dias_ruta_leidos']} días-ruta leídos en "
            f"{str(a6['duracion_s']).replace('.', ',')} s).", "",
            "| Medida | Valor |", "|---|---|",
            f"| ALT-006 | {a6['alertas']} |",
            f"| Con viaje, vehículo y conductor | {a6['con_viaje']} ({_pct(a6['con_viaje'], a6['alertas'])}) |",
            f"| Con seudónimo del conductor | {a6['con_conductor']} |"]
    lin += [f"| Rol del viaje: {k} | {v} |" for k, v in sorted(a6["resultado"].items())]
    lin += [f"| Viajes válidos de la ventana = salidas de la serie horaria | {a6['salidas_iguales']} de "
            f"{a6['alertas']} |",
            f"| Con el último despacho antes de la ventana | {a6['con_ultimo_despacho']} |", "",
            "«cancelado»: el despacho programado de la ventana que se canceló (despacho ausente); «tardio»: salió "
            "fuera del plazo (`excedeplazosalida`) o con un retraso de la salida real mayor que la tolerancia; "
            "«sin_viaje_cancelado_ni_tardio»: todos los viajes programados salieron a tiempo, el déficit es de "
            "programación y la alerta no inventa un viaje (deja el último despacho en `variables`).", "",
            f"## B. ALT-009 con la lectura integrada de la réplica ({a9['periodo'][0]} a {a9['periodo'][1]})", "",
            f"`demanda_segmentos` (lo que lee el ciclo con `FUENTE=postgres`): {a9['filas_leidas']} horas de "
            f"{a9['dias_ruta']} días-ruta; {a9['dias_ruta_con_horas_faltantes']} días-ruta con "
            f"{a9['horas_faltantes']} horas de servicio que no llegaron hasta la última que sí llegó (ningún viaje "
            "de la hora con timbradas de segmento, o ningún viaje). Con los viajes del día, ALT-009 descarta las "
            "horas sin ningún viaje programado no cancelado (no había servicio que capturar) y, en las que quedan, "
            "identifica el viaje con datos faltantes.", "",
            "| Medida | Valor |", "|---|---|",
            f"| Días-ruta sin ALT-009: ninguna de sus horas faltantes tenía un viaje programado no cancelado | "
            f"{a9['dias_ruta_sin_alerta']} |",
            f"| Horas faltantes descartadas por no tener servicio programado | {a9['horas_sin_viajes_programados']} |",
            f"| ALT-009 por horas faltantes | {a9['alertas']} |",
            f"| Con viaje, vehículo y conductor | {a9['con_viaje']} ({_pct(a9['con_viaje'], a9['alertas'])}) |",
            f"| Con seudónimo del conductor | {a9['con_conductor']} |",
            f"| Viajes programados en las horas faltantes | {a9['programados_en_horas_faltantes']} |",
            f"| Viajes con datos faltantes en esas horas | {a9['incompletos_en_horas_faltantes']} |",
            f"| Viajes con datos faltantes en esos días | {a9['viajes_incompletos']} |"]
    lin += [f"| Resultado: {k} | {v} |" for k, v in sorted(a9["resultado"].items())]
    lin += [f"| Motivo (en la lista de cada alerta): {k} | {v} |" for k, v in sorted(a9["motivos"].items())]
    lin += _informe_circuito(r.get("circuito"))
    lin += _informe_segmento(r.get("alt002_segmento"))
    lin += ["", "## Ejemplos (sin el seudónimo)", ""]
    for x in a6["ejemplos"][:2] + a9["ejemplos"][:2] + (r.get("alt002_segmento") or {}).get("ejemplos", [])[:2]:
        lin.append(f"- {x['codigo']} {x['ruta']} ({x['clave_dedup']}): viaje {x['viaje']}, vehículo "
                   f"{x['vehiculo']}, conductor seudonimizado: {'sí' if x['conductor_seudonimizado'] else 'no'}. "
                   f"{x['explicacion']}")
    lin += ["", "## Limitaciones", "",
            "- En el modo empaquetado (sin réplica ni exportación de `progvehiculos`) la serie es horaria: las "
            "alertas salen igual, con `identificacion_5_3.resultado = fuente_sin_viajes`.",
            "- El conteo de segmentos solo se usa cuando el ciclo lee la capa de segmentos (`demanda_segmentos`); "
            "con la serie empaquetada de 2025 no se informa, porque la capa de la réplica solo cubre enero y "
            "febrero de 2023.",
            "- Sin `SEUDONIMO_SECRETO` el conductor queda nulo (nunca en claro).",
            "- El descarte de las horas sin servicio programado solo se hace cuando la fuente trae los viajes del día; "
            "sin ellos (la fuente no los expone, o no trae ninguno de ese día: `fuente_sin_viajes_del_dia`), ALT-009 "
            "cuenta toda hora faltante, como antes.",
            "- La sección C usa la capa de segmentos de la réplica (enero y febrero de 2023); el sentido por segmento "
            "es la aproximación geométrica del supuesto S9, que debe confirmar Extreme.", ""]
    return "\n".join(lin)


def main() -> dict:
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    _secreto()
    fuente, integrada = lectura_integrada()
    r = {"generado": datetime.now(ZONA).isoformat(timespec="seconds"), "fuente": "réplica local, lector_ia",
         "reglas": _tabla_reglas(), "variantes": _tabla_variantes(), "periodo_2025": [str(DESDE_2025), str(HASTA_2025)],
         "alt006": medir_alt006(), "alt009": medir_alt009(fuente, integrada), "circuito": medir_circuito(),
         "alt002_segmento": medir_alt002_segmento(fuente, integrada)}
    SALIDA.mkdir(parents=True, exist_ok=True)
    (SALIDA / "identificacion_viajes.json").write_text(json.dumps(r, ensure_ascii=False, indent=1, default=str),
                                                      encoding="utf-8")
    (SALIDA / "identificacion_viajes.md").write_text(informe(r), encoding="utf-8")
    print(informe(r))
    return r


if __name__ == "__main__":
    main()
