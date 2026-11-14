"""Backtest de la restricción reactiva de ocupación observada (§10.1 «ocupación actual»; app/servicios/ocupacion.py).

Qué se mide (con las exportaciones de 2023-01-01 a 2023-02-27, las únicas con subidas y bajadas por segmento; nada se
consulta a la base del reto): la regla es una restricción de SEGURIDAD, no un re-pronóstico (el backtest del proyecto
ya mostró que re-pronosticar dentro del día no mejora la precisión). Si en una hora cerrada la ocupación observada del
segmento crítico alcanza el umbral crítico (0,90), la hora siguiente no baja de ceil(carga crítica observada /
(50 × 0,85)) salidas. Para cada ruta, día y hora se calcula la ocupación observada exactamente como en el ciclo
(ocupacion.calcular_observada sobre los viajes no cancelados de la franja) y:

1. Persistencia: con qué frecuencia la hora siguiente a una hora sobre el umbral también lo está, frente a la tasa
   base de horas sobre el umbral (si la regla dispara sobre algo que persiste o sobre ruido).
2. Frente a la operación real: cuántas salidas habría agregado la regla a las que de verdad salieron en la hora
   siguiente y, con la carga crítica observada en esa hora repartida entre las salidas (supuesto: la demanda no
   cambia con la oferta), cuántas horas sobre el umbral y cuántos pasajeros por encima de la ocupación crítica
   quedarían con y sin la regla. Es una aproximación contrafactual, declarada.
3. Frente al plan del día (opcional, --plan): el plan con el modelo activo de los días con disparos, la hora siguiente
   con y sin el piso, y en una muestra el camino real del código (optimizacion.plan_dia con ocupacion_actual) para
   comprobar que el MILP resuelve (óptimo), que la hora queda en max(plan, piso) y cuánto cambian las salidas y el
   costo del día.
4. En tiempo real: 1 a 3 usan la hora cerrada con TODOS sus viajes completos, pero un viaje de Sobusa dura unas 4 h y
   en un ciclo intradía a las (h+1):05 o (h+1):30 los viajes de la hora h van por la mitad. Como en la carga inicial
   todos los segmentos de un viaje quedan en el bloque del fin del viaje (hallazgo H10), la hora a la que cada segmento
   llegaría por el trigger se aproxima con la salida del viaje más la fracción de su duración que corresponde al km del
   final del segmento; se repite la medición de la hora h solo con lo ya recorrido y se compara con 1.

Salidas: docs/evidencias/ocupacion/backtest_restriccion_reactiva.json y .md.

Uso:  python scripts/backtest_ocupacion_reactiva.py [--origen ../../datos] [--plan] [--muestra 12]
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from scripts import preparar_ocupacion_segmentos as prep  # noqa: E402

Z = ZoneInfo("America/Bogota")
CAPACIDAD, OCUPACION_OBJETIVO, CRITICA, MINIMO_VIAJES = 50.0, 0.85, 0.90, 2
UMBRALES = {"headway_minimo_min": 2.0, "headway_maximo_min": 10.0, "espera_max_min": 5.0,
            "ocupacion_objetivo_min": 0.65, "ocupacion_objetivo_max": OCUPACION_OBJETIVO,
            "ocupacion_critica": CRITICA}


MINUTOS_TIEMPO_REAL = (5, 30)   # el ciclo intradía a las (h+1):05 y a las (h+1):30


def filas_de_los_viajes(origen: Path) -> pd.DataFrame:
    """Filas viaje × segmento de los viajes no cancelados con su franja, como las entrega el ciclo, y `llega`: la hora a
    la que el segmento llegaría por el trigger (salida del viaje + la fracción de su duración que corresponde al km del
    final del segmento; el bloque de la exportación es el del fin del viaje, H10)."""
    viajes = prep.cargar_viajes(origen)
    filas, catalogo = prep.cargar_segmentos(origen, viajes)
    viajes = viajes[viajes["cancelada"] == "N"].set_index("id_viaje")
    filas = filas[filas["id_viaje"].isin(viajes.index)]
    filas = filas.join(viajes[["ruta", "idruta", "fecha", "hora", "fechainicio", "fechafin"]], on="id_viaje")
    catalogo = catalogo.drop_duplicates(["idruta", "nro_segmento"])
    largo = catalogo["idruta"].map(catalogo.groupby("idruta")["longitud_m"].sum())
    catalogo = catalogo.assign(fraccion=(catalogo["km_inicio"] * 1000 + catalogo["longitud_m"]) / largo)
    filas = filas.merge(catalogo[["idruta", "nro_segmento", "fraccion"]], on=["idruta", "nro_segmento"], how="left")
    filas["llega"] = filas["fechainicio"] + (filas["fechafin"] - filas["fechainicio"]) * filas["fraccion"]
    filas["vehiculo"], filas["conductor"], filas["terminado"] = None, None, True
    return filas


def criticos_de(filas: pd.DataFrame) -> pd.DataFrame:
    """Por ruta, fecha y hora de salida: el segmento crítico observado (como en el ciclo) con su ocupación media, la
    carga crítica de la hora (Σ de la carga de los viajes en ese segmento) y los viajes medidos."""
    from app.servicios import ocupacion

    tabla = ocupacion.calcular_observada(filas[list(ocupacion.COLUMNAS_FILAS)],
                                         {r: CAPACIDAD for r in filas["ruta"].unique()})
    c = tabla[tabla["critico"]].copy()
    c["fecha"] = pd.to_datetime(c["fecha"]).dt.date
    return c[["ruta", "fecha", "hora", "nro_segmento", "sentido", "nro_viajes", "carga_media", "carga_total",
              "ocupacion_media"]].sort_values(["ruta", "fecha", "hora"]).reset_index(drop=True)


def horas_observadas(origen: Path, filas: pd.DataFrame | None = None) -> pd.DataFrame:
    """criticos_de con los viajes completos (lo que se sabe cuando todos los viajes de la hora terminaron)."""
    return criticos_de(filas if filas is not None else filas_de_los_viajes(origen))


def _piso(carga_total: float) -> int:
    return math.ceil(carga_total / (CAPACIDAD * OCUPACION_OBJETIVO) - 1e-9)


def _en_tiempo_real(filas: pd.DataFrame, pares: pd.DataFrame, minutos: int) -> dict:
    """La medición de la hora h con lo que el trigger habría escrito a las (h+1):mm, en los mismos pares de horas."""
    corte = (pd.to_datetime(filas["fecha"]) + pd.to_timedelta(filas["hora"].astype(int) + 1, unit="h")
             + pd.Timedelta(minutes=minutos))
    vista = criticos_de(filas[filas["llega"] <= corte])
    llave = ["ruta", "fecha", "hora"]
    x = pares[llave + ["dispara", "piso", "sobre_sig"]].merge(vista, on=llave, how="left")
    x["dispara_tr"] = (x["nro_viajes"].fillna(0) >= MINIMO_VIAJES) & (x["ocupacion_media"].fillna(0) >= CRITICA)
    ambos = x[x["dispara"] & x["dispara_tr"]]
    piso_tr = sum(_piso(c) for c in ambos["carga_total"])
    nuevos = x[x["dispara_tr"]]
    return {"corte": f"(h+1):{minutos:02d}", "disparos_con_viajes_completos": int(x["dispara"].sum()),
            "de_esos_disparan_en_tiempo_real": int(len(ambos)),
            "piso_en_tiempo_real_sobre_piso_completo": round(piso_tr / max(int(ambos["piso"].sum()), 1), 3),
            "disparos_en_tiempo_real": int(len(nuevos)),
            "hora_siguiente_sobre_umbral_si_dispara_en_tiempo_real": round(float(nuevos["sobre_sig"].mean()), 4)
            if len(nuevos) else None}


def frente_al_tiempo_real(filas: pd.DataFrame, pares: pd.DataFrame) -> dict:
    """4. La regla con los viajes de la hora cerrada todavía en curso (ciclo intradía real), frente a 1."""
    viajes = filas.drop_duplicates("id_viaje")
    dur = (viajes["fechafin"] - viajes["fechainicio"]).dt.total_seconds() / 60
    return {"duracion_mediana_del_viaje_min": round(float(dur.median()), 0),
            "cortes": [_en_tiempo_real(filas, pares, m) for m in MINUTOS_TIEMPO_REAL],
            "supuesto": ("cada segmento llega por el trigger cuando el viaje lo termina de recorrer: salida + la "
                         "fracción de la duración del viaje que corresponde al km del final del segmento; solo se mide "
                         "la hora h (si tuviera menos de 2 viajes medidos, el ciclo miraría la anterior)")}


def pares_de_horas(h: pd.DataFrame) -> pd.DataFrame:
    """Cada hora con la siguiente del mismo día (las dos con al menos MINIMO_VIAJES viajes medidos)."""
    h = h[h["nro_viajes"] >= MINIMO_VIAJES]
    sig = h.assign(hora=h["hora"] - 1)
    p = h.merge(sig, on=["ruta", "fecha", "hora"], suffixes=("", "_sig"))
    p["dispara"] = p["ocupacion_media"] >= CRITICA
    p["piso"] = [math.ceil(c / (CAPACIDAD * OCUPACION_OBJETIVO) - 1e-9) for c in p["carga_total"]]
    p["sobre_sig"] = p["ocupacion_media_sig"] >= CRITICA
    return p


def _exceso(carga_total: float, salidas: float) -> float:
    """Pasajeros en el segmento crítico por encima de la ocupación crítica con esas salidas (carga repartida)."""
    return max(0.0, carga_total - CRITICA * CAPACIDAD * salidas)


def frente_a_la_operacion(p: pd.DataFrame) -> dict:
    """Persistencia y efecto contrafactual frente a las salidas que de verdad salieron en la hora siguiente."""
    d = p[p["dispara"]].copy()
    d["con_regla"] = d[["nro_viajes_sig", "piso"]].max(axis=1)
    d["agregadas"] = d["con_regla"] - d["nro_viajes_sig"]
    occ_con = d["carga_total_sig"] / (d["con_regla"] * CAPACIDAD)
    exceso_sin = sum(_exceso(c, n) for c, n in zip(d["carga_total_sig"], d["nro_viajes_sig"], strict=True))
    exceso_con = sum(_exceso(c, n) for c, n in zip(d["carga_total_sig"], d["con_regla"], strict=True))
    base = float(p["sobre_sig"].mean())
    persistencia = float(d["sobre_sig"].mean()) if len(d) else None
    return {
        "pares_de_horas": int(len(p)), "disparos": int(len(d)),
        "disparos_por_ruta": d.groupby("ruta").size().to_dict(),
        "tasa_base_hora_siguiente_sobre_umbral": round(base, 4),
        "persistencia_hora_siguiente_sobre_umbral_si_dispara": None if persistencia is None else round(persistencia, 4),
        "lift": None if not persistencia or not base else round(persistencia / base, 2),
        "disparos_que_agregarian_salidas": int((d["agregadas"] > 0).sum()),
        "salidas_agregadas": int(d["agregadas"].sum()),
        "salidas_reales_en_las_horas_con_disparo": int(d["nro_viajes_sig"].sum()),
        "horas_siguientes_sobre_umbral_sin_regla": int(d["sobre_sig"].sum()),
        "horas_siguientes_sobre_umbral_con_regla": int((occ_con >= CRITICA).sum()),
        "pasajeros_sobre_la_ocupacion_critica_sin_regla": round(exceso_sin, 1),
        "pasajeros_sobre_la_ocupacion_critica_con_regla": round(exceso_con, 1),
        "salidas_agregadas_donde_no_hacia_falta": int(d.loc[~d["sobre_sig"], "agregadas"].sum()),
        "supuesto": ("la carga crítica observada de la hora siguiente se reparte por igual entre sus salidas y no "
                     "cambia con la oferta (aproximación contrafactual)")}


def _plan(fecha, ruta: str, **kw) -> dict:
    from app.servicios import optimizacion

    return optimizacion.plan_dia(fecha, ruta, umbrales=UMBRALES, umbrales_version=None, **kw)


def _caso_real(fila, h: pd.DataFrame, base: dict) -> dict:
    """El camino real del código para un disparo: restricción reactiva con el instante en la hora siguiente y plan."""
    from app.servicios import ocupacion

    del_dia = h[(h["ruta"] == fila.ruta) & (h["fecha"] == fila.fecha)]
    observada = {(r.fecha, int(r.hora)): {"nro_viajes": int(r.nro_viajes), "ocupacion_media": float(r.ocupacion_media),
                                          "carga_total": float(r.carga_total), "capacidad": CAPACIDAD,
                                          "nro_segmento": int(r.nro_segmento), "id_segmento": 0,
                                          "sentido": r.sentido} for r in del_dia.itertuples(index=False)}
    instante = datetime(fila.fecha.year, fila.fecha.month, fila.fecha.day, int(fila.hora) + 1, 5, tzinfo=Z)
    reactiva = ocupacion.restriccion_reactiva(observada, fila.fecha, instante, UMBRALES)
    plan = _plan(fila.fecha, fila.ruta, ocupacion_actual=reactiva)
    x = {hh["hora"]: hh["salidas"] for hh in plan["horas"]}
    xb = {hh["hora"]: hh["salidas"] for hh in base["horas"]}
    sig = int(fila.hora) + 1
    r = plan["ocupacion_actual"] or {}
    return {"ruta": fila.ruta, "fecha": str(fila.fecha), "hora_cerrada": int(fila.hora), "hora_aplica": sig,
            "ocupacion_observada": round(float(fila.ocupacion_media), 4), "piso": r.get("salidas_minimas"),
            "aplica": r.get("aplica"), "estado_solver": plan["estado_solver"], "plan_sin_piso": xb.get(sig),
            "plan_con_piso": x.get(sig),
            "hora_igual_a_max_plan_piso": x.get(sig) == max(xb.get(sig, 0), r.get("salidas_minimas") or 0),
            "otras_horas_cambiadas": sum(1 for k in x if k != sig and x[k] != xb.get(k)),
            "salidas_dia_delta": plan["salidas_dia"] - base["salidas_dia"],
            "costo_dia_delta_cop": round(plan["costo_total_cop"] - base["costo_total_cop"], 2)}


def frente_al_plan(p: pd.DataFrame, h: pd.DataFrame, muestra: int) -> dict:
    """El plan del día con el modelo activo en los días con disparo: la hora siguiente con y sin el piso y, en una
    muestra, el camino real del código."""
    from app.servicios import optimizacion

    d = p[p["dispara"]].copy()
    t0 = time.perf_counter()
    planes, errores = {}, []
    for ruta, fecha in sorted({(r, f) for r, f in zip(d["ruta"], d["fecha"], strict=True)}):
        try:
            planes[(ruta, fecha)] = _plan(fecha, ruta)
        except ValueError as exc:
            errores.append({"ruta": ruta, "fecha": str(fecha), "error": str(exc)})
    filas = []
    for f in d.itertuples(index=False):
        base = planes.get((f.ruta, f.fecha))
        if base is None:
            continue
        hora = next(x for x in base["horas"] if x["hora"] == int(f.hora) + 1)
        piso = min(int(f.piso), int(hora["maximo_salidas_headway"]))
        filas.append({"x_plan": hora["salidas"], "piso": piso, "sube": piso > hora["salidas"],
                      "agregadas": max(0, piso - hora["salidas"])})
    t = pd.DataFrame(filas)
    elegidos = d[d.apply(lambda r: (r["ruta"], r["fecha"]) in planes, axis=1)]
    elegidos = elegidos.sort_values("ocupacion_media", ascending=False).head(muestra)
    casos = [_caso_real(f, h, planes[(f.ruta, f.fecha)]) for f in elegidos.itertuples(index=False)]
    optimizacion.limpiar_cache_plan()
    return {"dias_ruta_con_disparo": len(planes), "errores_del_plan": errores,
            "disparos_evaluados": int(len(t)), "disparos_en_que_el_piso_sube_el_plan": int(t["sube"].sum()),
            "salidas_agregadas_al_plan": int(t["agregadas"].sum()),
            "salidas_del_plan_en_esas_horas": int(t["x_plan"].sum()),
            "muestra_camino_real": casos,
            "muestra_optima": all(c["estado_solver"] == "Optimal" for c in casos),
            "muestra_hora_igual_a_max_plan_piso": sum(1 for c in casos if c["hora_igual_a_max_plan_piso"]),
            "segundos": round(time.perf_counter() - t0, 1)}


def _c(x, d=1) -> str:
    return f"{x:,.{d}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _texto_costo(casos: list[dict]) -> str:
    """Lo que cuesta el piso en el MILP del día (suavidad y flota) en la muestra del camino real."""
    con_cambio = [c for c in casos if c["plan_con_piso"] != c["plan_sin_piso"]]
    if not con_cambio:
        return "- En la muestra el piso no cambió el plan (el plan ya programaba esas salidas)."
    otras = sum(1 for c in con_cambio if c["otras_horas_cambiadas"])
    costo = max(c["costo_dia_delta_cop"] for c in con_cambio)
    return (f"- Cuando el piso sube la hora ({len(con_cambio)} casos), el MILP cambia también otras horas en {otras} "
            f"(la suavidad y la flota en ruta: con la flota activa el piso se cumple quitando salidas a otras horas) y "
            f"el costo del día del MILP sube hasta {_c(costo, 0)} COP; es el precio de la seguridad, y la restricción "
            "lo dice en el plan.")


def _informe_tiempo_real(t: dict | None) -> list[str]:
    """La sección 4: la regla con los viajes de la hora cerrada todavía en curso."""
    if not t:
        return []
    lineas = ["", "## En tiempo real: la hora cerrada con sus viajes todavía en curso", "",
              "Las cifras frente a la operación y frente al plan usan la hora cerrada con todos sus viajes completos. "
              f"Un viaje dura unas {_c(t['duracion_mediana_del_viaje_min'], 0)} min (mediana), así que en un ciclo "
              "intradía los viajes de "
              "la hora h van por la mitad cuando se programa la hora siguiente. Supuesto: " + t["supuesto"] + ".", "",
              "| Ciclo intradía a las | Disparos con viajes completos | Siguen disparando | Piso en tiempo real / "
              "piso completo | Disparos en tiempo real | Hora siguiente sobre el umbral si dispara |",
              "|---|---|---|---|---|---|"]
    for c in t["cortes"]:
        sig = c["hora_siguiente_sobre_umbral_si_dispara_en_tiempo_real"]
        lineas.append(f"| {c['corte']} | {c['disparos_con_viajes_completos']} | {c['de_esos_disparan_en_tiempo_real']} "
                      f"| {_c(c['piso_en_tiempo_real_sobre_piso_completo'], 2)} | {c['disparos_en_tiempo_real']} | "
                      f"{'-' if sig is None else _c(100 * sig) + ' %'} |")
    lineas += ["", "Las cifras de efecto de las secciones anteriores son una cota superior: en la operación la regla "
               "actúa con los viajes que ya pasaron por el segmento crítico."]
    return lineas


def informe(r: dict) -> str:
    o = r["frente_a_la_operacion"]
    lineas = [
        "# Backtest de la restricción reactiva de ocupación observada (§10.1)", "",
        f"Generado por `scripts/backtest_ocupacion_reactiva.py` el {r['generado_en']} con los viajes por segmento de "
        f"{r['periodo']}. Es una restricción de seguridad, no un re-pronóstico: el backtest del proyecto ya mostró que "
        "re-pronosticar dentro del día no mejora la precisión. Regla: si la ocupación observada del segmento crítico "
        f"en una hora cerrada es ≥ {_c(100 * CRITICA, 0)} %, la hora siguiente no baja de ceil(carga crítica / "
        f"({_c(CAPACIDAD, 0)} × {_c(OCUPACION_OBJETIVO, 2)})) salidas.", "",
        "## Persistencia y efecto frente a la operación real", "",
        f"- Pares de horas seguidas medidos: {o['pares_de_horas']}; disparos: {o['disparos']} "
        f"({', '.join(f'{k}: {v}' for k, v in o['disparos_por_ruta'].items())}).",
        f"- La hora siguiente queda sobre el umbral en el "
        f"{_c(100 * o['persistencia_hora_siguiente_sobre_umbral_si_dispara'])} % de los disparos, frente a una tasa "
        f"base de {_c(100 * o['tasa_base_hora_siguiente_sobre_umbral'])} % (lift {_c(o['lift'], 2)}).",
        f"- La regla agregaría {o['salidas_agregadas']} salidas en {o['disparos_que_agregarian_salidas']} de los "
        f"{o['disparos']} disparos, sobre {o['salidas_reales_en_las_horas_con_disparo']} salidas reales en esas horas; "
        f"{o['salidas_agregadas_donde_no_hacia_falta']} de ellas en horas que no quedaron sobre el umbral.",
        f"- Horas siguientes sobre el umbral: {o['horas_siguientes_sobre_umbral_sin_regla']} sin la regla y "
        f"{o['horas_siguientes_sobre_umbral_con_regla']} con ella; pasajeros por encima de la ocupación crítica en el "
        f"segmento crítico: {_c(o['pasajeros_sobre_la_ocupacion_critica_sin_regla'])} sin la regla y "
        f"{_c(o['pasajeros_sobre_la_ocupacion_critica_con_regla'])} con ella.",
        f"- Supuesto: {o['supuesto']}."]
    plan = r.get("frente_al_plan")
    if plan:
        lineas += ["", "## Frente al plan del día con el modelo activo", "",
                   f"- Días-ruta con disparo: {plan['dias_ruta_con_disparo']} (errores del plan: "
                   f"{len(plan['errores_del_plan'])}).",
                   f"- El piso sube la hora siguiente del plan en {plan['disparos_en_que_el_piso_sube_el_plan']} de "
                   f"{plan['disparos_evaluados']} disparos y agrega {plan['salidas_agregadas_al_plan']} salidas a "
                   f"{plan['salidas_del_plan_en_esas_horas']}.",
                   f"- Camino real del código en {len(plan['muestra_camino_real'])} disparos: todos óptimos = "
                   f"{plan['muestra_optima']}; la hora queda en max(plan, piso) en "
                   f"{plan['muestra_hora_igual_a_max_plan_piso']}.",
                   _texto_costo(plan["muestra_camino_real"]), "",
                   "| Ruta | Fecha | Hora | Ocupación observada | Piso | Plan sin piso | Plan con piso | Otras horas "
                   "cambiadas | Δ salidas día | Δ costo día (COP) |", "|---|---|---|---|---|---|---|---|---|---|"]
        lineas += [f"| {c['ruta']} | {c['fecha']} | {c['hora_aplica']} | {_c(100 * c['ocupacion_observada'], 0)} % | "
                   f"{c['piso']} | {c['plan_sin_piso']} | {c['plan_con_piso']} | {c['otras_horas_cambiadas']} | "
                   f"{c['salidas_dia_delta']} | {_c(c['costo_dia_delta_cop'], 0)} |"
                   for c in plan["muestra_camino_real"]]
    lineas += _informe_tiempo_real(r.get("frente_al_tiempo_real"))
    lineas += ["", "## Limitaciones", ""] + [f"- {x}" for x in r["limitaciones"]]
    return "\n".join(lineas) + "\n"


LIMITACIONES = [
    "Solo hay subidas y bajadas por segmento de 2023-01-01 a 2023-02-27; el efecto en otros meses no se midió.",
    "El efecto frente a la operación es contrafactual: supone que la carga de la hora siguiente se reparte por igual "
    "entre sus salidas y que la demanda no cambia con la oferta.",
    "La hora se mide por salida del viaje; en un ciclo intradía real la última hora cerrada llega con el retraso de "
    "la duración del viaje (la regla aplica a la siguiente hora todavía programable, a lo sumo 2 h después): la "
    "sección «En tiempo real» lo mide con el avance de cada viaje, y el camino real del código de la muestra usa la "
    "hora cerrada completa.",
    "El plan con el modelo activo en 2023 está dentro del periodo de entrenamiento del modelo: sirve para comprobar "
    "que el piso no rompe el MILP, no para medir la precisión.",
]


def main(argv=None) -> dict:
    a = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    a.add_argument("--origen", type=Path, default=prep._origen_por_omision())
    a.add_argument("--plan", action="store_true", help="evalúa también el plan del día con el modelo activo")
    a.add_argument("--muestra", type=int, default=12)
    a.add_argument("--salida", type=Path, default=prep.EVIDENCIA)
    args = a.parse_args(argv)
    filas = filas_de_los_viajes(args.origen)
    h = horas_observadas(args.origen, filas)
    p = pares_de_horas(h)
    r = {"generado_en": datetime.now().astimezone().isoformat(timespec="seconds"),
         "script": "scripts/backtest_ocupacion_reactiva.py", "periodo": f"{h['fecha'].min()} a {h['fecha'].max()}",
         "regla": {"umbral_critico": CRITICA, "ocupacion_objetivo_max": OCUPACION_OBJETIVO, "capacidad": CAPACIDAD,
                   "minimo_viajes_medidos": MINIMO_VIAJES},
         "frente_a_la_operacion": frente_a_la_operacion(p), "frente_al_tiempo_real": frente_al_tiempo_real(filas, p),
         "limitaciones": LIMITACIONES}
    if args.plan:
        r["frente_al_plan"] = frente_al_plan(p, h, args.muestra)
    args.salida.mkdir(parents=True, exist_ok=True)
    (args.salida / "backtest_restriccion_reactiva.json").write_text(
        json.dumps(r, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    (args.salida / "backtest_restriccion_reactiva.md").write_text(informe(r), encoding="utf-8")
    print(json.dumps({k: v for k, v in r.items() if k != "limitaciones"}, ensure_ascii=False, indent=1,
                     default=str)[:6000])
    return r


if __name__ == "__main__":
    main()
