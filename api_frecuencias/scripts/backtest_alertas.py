"""Backtest de las alertas sobre 2025 (§18 «Alertas excesivas»): observadas ALT-005..ALT-009 y, con --pronostico,
las de pronóstico ALT-001..ALT-004 del ciclo diario.

Reproduce, día a día y ruta a ruta, lo que hace el ciclo (ejecucion.contexto_observado + alertas.evaluar_observadas):
cada hora cerrada de servicio (4-20 h) con el pronóstico del modelo para esa hora y su banda P10-P90 CALIBRADA
(conformal móvil de inferencia, que solo usa días anteriores), las salidas observadas frente a 60 / intervalo
programado y el consolidado del día frente al mismo tipo de día de las 8 semanas previas (z robusto).

Mide por código:
- cuántas veces se dispara: alertas por ruta y día y por día (las 3 rutas);
- un indicador de precisión frente a lo que pasó después (no hay incidentes etiquetados, se declara): la condición
  sigue en la hora siguiente al episodio (ALT-005, ALT-006, ALT-007) o el día está marcado como especial/excluido
  (ALT-008), comparado con la tasa base de la condición en una hora cualquiera (lift = precisión / tasa base);
- la proporción en días de calendario especial (festivo, carnaval, Semana Santa, vacaciones, Navidad, 1 de enero);
- la sensibilidad a cada umbral (uno a la vez, el resto en su valor por defecto), para afinar los valores por defecto
  que la migración 0003 versiona en threshold_config.

No escribe en datos/: con --corte entrena un modelo temporal en un directorio aparte (MODELOS_DIR temporal).

Uso (desde EntregaFinal/api_frecuencias):
  python scripts/backtest_alertas.py                      # modelo activo (fv2, corte 2025-08-31): fuera de muestra
  python scripts/backtest_alertas.py --corte 2024-12-31   # fv2 temporal con corte 2024-12-31: casi todo 2025
  python scripts/backtest_alertas.py --pronostico         # ALT-001..ALT-004 del ciclo diario, antes y ahora
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from collections import defaultdict
from datetime import date, datetime, timedelta
from datetime import time as dtime
from pathlib import Path
from zoneinfo import ZoneInfo

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

ZONA = ZoneInfo("America/Bogota")
SALIDA = RAIZ / "docs" / "evidencias" / "alertas"
HORAS_EVAL = range(4, 21)
ESPECIALES = ("festivo", "carnaval", "semana_santa", "vacaciones", "navidad", "primero_enero")
VARIACIONES = {
    "persistencia_horas": [1, 2, 3],
    "persistencia_ocupacion_horas": [1, 2, 3],
    "ruptura_h": [4.0, 5.0, 6.0],
    "ruptura_cambio_minimo": [0.05, 0.08],
    "alt005_exigir_p10": [0, 1],
    "caida_demanda": [0.2, 0.3, 0.4],
    "error_pronostico": [0.15, 0.25],
    "tolerancia_salidas": [0.2, 0.35, 0.5],
    "z_anomalia": [3.0, 3.5, 4.0],
}


def _pronosticos(modelo, inferencia, tabla, desde, hasta):
    """Pronóstico por hora y banda calibrada (igual que predecir(…, 60, usar_nowcast=False) desde la hora en punto):
    la calibración versionada del modelo (v2, un cuantil por bloque horario) o, si no la trae, el conformal móvil por
    ruta (v1)."""
    t = tabla.reset_index() if "ruta" not in tabla.columns else tabla.copy()
    t = t[(t["fecha"] >= desde) & (t["fecha"] <= hasta) & t["b8"].notna()].copy()
    p, lo, hi = inferencia._predecir_filas(modelo, t)
    if modelo.get("calibracion"):
        lo2, hi2 = inferencia.aplicar_conformal(p, lo, hi, inferencia.q_calibracion(modelo["calibracion"], t)[0])
        t["esperado"], t["p10"], t["p90"], t["calibrada"] = p, lo2, hi2, True
        return t[["ruta", "fecha", "hora", "esperado", "p10", "p90", "calibrada"]]
    inferencia._puntajes_conformal(modelo)
    claves = sorted(set(zip(t["ruta"], t["fecha"], strict=False)))
    qs = inferencia.cuantiles_conformal_movil(modelo["_indice_conformal"], claves)
    q = np.array([qs[(r, f)]["q"] if qs[(r, f)]["aplicado"] else np.nan
                  for r, f in zip(t["ruta"], t["fecha"], strict=False)], dtype=float)
    lo2, hi2 = lo.copy(), hi.copy()
    m = ~np.isnan(q)
    if m.any():
        esc = np.maximum(p[m], 1.0)
        lo2[m] = np.clip(np.minimum(lo[m] - q[m] * esc, p[m]), 0, None)
        hi2[m] = np.maximum(hi[m] + q[m] * esc, p[m])
    t["esperado"], t["p10"], t["p90"], t["calibrada"] = p, lo2, hi2, m
    return t[["ruta", "fecha", "hora", "esperado", "p10", "p90", "calibrada"]]


def _factores_por_dia():
    """{(ruta, letra del tipo de día, hora): factor de carga} del optimizador (optimizacion.factor_carga_franja)."""
    from app.servicios import optimizacion

    return {k: round(min(max(v[0], 0.05), 1.0), 4) for k, v in optimizacion._factores_carga_hora().items()}


def series_diarias(h, datos):
    """{ruta: [{fecha, observado, esperado}]} de los días con todas las horas de servicio con real y pronóstico."""
    completas = h.dropna(subset=["pasajeros", "esperado"])
    g = (completas.groupby(["ruta", "fecha"]).agg(observado=("pasajeros", "sum"), esperado=("esperado", "sum"),
                                                   horas=("hora", "count")).reset_index())
    g = g[g["horas"] >= len(datos.HORAS_SERVICIO)].sort_values(["ruta", "fecha"])
    return {r: [{"fecha": f, "observado": float(o), "esperado": float(e)}
                for f, o, e in zip(x["fecha"], x["observado"], x["esperado"], strict=False)]
            for r, x in g.groupby("ruta")}


def _contextos(serie, pron, parametros, datos, alertas, desde, hasta, semanas=8):
    """{(ruta, fecha): contexto de evaluar_observadas} y la tabla horaria usada (para la precisión).

    Cada contexto lleva, como en el ciclo, la capacidad del catálogo y el factor de carga de la franja (ALT-002 con la
    ocupación observada) y la serie diaria de la ruta hasta ese día (ruptura de comportamiento, RF-009)."""
    s = serie.copy()
    s["fecha"] = pd.to_datetime(s["fecha"]).dt.date
    s = s[s["hora"].isin(list(datos.HORAS_SERVICIO))]
    s["especial"] = s[list(ESPECIALES)].max(axis=1).astype(int)
    h = s.merge(pron, on=["ruta", "fecha", "hora"], how="left")
    td_txt = h["tipo_dia"].map(datos.TIPOS_DIA)
    h["intervalo"] = [parametros.get((r, t, int(x))) for r, t, x in zip(h["ruta"], td_txt, h["hora"], strict=False)]
    diarios = (s.groupby(["ruta", "fecha"]).agg(subidas=("pasajeros", "sum"), nro_viajes=("salidas", "sum"),
                                                 horas=("hora", "count"), tipo_dia=("tipo_dia", "first"),
                                                 especial=("especial", "max"), excluido=("excluido", "max"))
               .reset_index())
    factores = _factores_por_dia()
    capacidades = {x["ruta"]: float(x.get("capacidad") or 50) for x in datos.catalogo_rutas()}
    ctxs = {}
    h = h[(h["fecha"] >= desde) & (h["fecha"] <= hasta)].sort_values(["ruta", "fecha", "hora"])
    por_ruta = series_diarias(h, datos)
    for (ruta, fecha), g in h.groupby(["ruta", "fecha"], sort=False):
        horas = []
        for x in g.itertuples(index=False):
            inicio = datetime.combine(fecha, dtime(int(x.hora)), tzinfo=ZONA)
            obs = None if pd.isna(x.pasajeros) else float(x.pasajeros)
            interv = None if x.intervalo is None or pd.isna(x.intervalo) else float(x.intervalo)
            horas.append(alertas.contexto_hora(
                inicio, obs, None if pd.isna(x.esperado) else float(x.esperado),
                None if pd.isna(x.p10) else float(x.p10), None if pd.isna(x.p90) else float(x.p90),
                None if pd.isna(x.salidas) else int(x.salidas), (60.0 / interv) if interv else None, interv))
        d = diarios[(diarios["ruta"] == ruta)]
        hoy = d[d["fecha"] == fecha]
        td = int(hoy["tipo_dia"].iloc[0])
        ref = d[(d["fecha"] < fecha) & (d["fecha"] >= fecha - timedelta(weeks=semanas)) & (d["tipo_dia"] == td)
                & (d["horas"] >= len(datos.HORAS_SERVICIO))]
        inicio_dia = datetime.combine(fecha, dtime(0), tzinfo=ZONA)
        faltan = [f"{fecha} {x:02d}:00" for x in datos.HORAS_SERVICIO if x not in set(g["hora"].astype(int))]
        letra = "LSD"[td]
        ctxs[(ruta, fecha)] = {
            "ruta": ruta, "empresa": "Sobusa", "detectada_en": inicio_dia + timedelta(days=1, hours=6),
            "tolerancia_tiempo_min": 0, "horas": horas, "capacidad": capacidades.get(ruta, 50.0),
            "factor_carga_por_hora": {x: factores[(ruta, letra, x)] for x in datos.HORAS_SERVICIO
                                      if (ruta, letra, x) in factores},
            "fuente_factor_carga": "mediana 2025 de carga crítica / abordajes por ruta, tipo de día y hora",
            "serie_diaria": [dict(x, nueva=x["fecha"] == fecha) for x in por_ruta.get(ruta, []) if x["fecha"] <= fecha],
            "consolidado": {"fecha": fecha, "inicio": inicio_dia, "fin": inicio_dia + timedelta(days=1),
                            "subidas": float(hoy["subidas"].iloc[0]), "nro_viajes": float(hoy["nro_viajes"].iloc[0]),
                            "referencia_valores": {"subidas": ref["subidas"].astype(float).tolist(),
                                                   "nro_viajes": ref["nro_viajes"].astype(float).tolist()},
                            "serie": ref["subidas"].astype(float).tolist()[-6:] + [float(hoy["subidas"].iloc[0])]},
            "datos": {"horas_faltantes": faltan, "campos_faltantes": [], "fecha": fecha},
        }
    return ctxs, h, diarios


def _ocupacion_hora(x, u, alertas, factores, capacidades):
    """Ocupación observada de una fila horaria con el factor de su franja (None si no se puede medir)."""
    f = factores.get((x.ruta, "LSD"[int(x.tipo_dia)], int(x.hora)))
    hh = {"observado": None if pd.isna(x.pasajeros) else float(x.pasajeros),
          "salidas_observadas": None if pd.isna(x.salidas) else float(x.salidas),
          "borde_servicio": int(x.hora) in alertas.HORAS_BORDE}
    return alertas.ocupacion_observada_hora(hh, f, capacidades.get(x.ruta, 50.0), u["salidas_minimas_ocupacion"])


def _condiciones(h, u, alertas):
    """Condición por hora (para la tasa base y la confirmación en la hora siguiente)."""
    from app.servicios import datos

    factores = _factores_por_dia()
    capacidades = {x["ruta"]: float(x.get("capacidad") or 50) for x in datos.catalogo_rutas()}
    out = {}
    for x in h.itertuples(index=False):
        obs, esp = (None if pd.isna(x.pasajeros) else float(x.pasajeros)), (None if pd.isna(x.esperado) else
                                                                             float(x.esperado))
        p10, p90 = (None if pd.isna(x.p10) else float(x.p10)), (None if pd.isna(x.p90) else float(x.p90))
        c005 = alertas._cumple_005(obs, esp, p10, u)
        s007 = alertas._signo_007({"observado": obs, "esperado": esp, "p10": p10, "p90": p90}, u)
        interv = None if x.intervalo is None or pd.isna(x.intervalo) else float(x.intervalo)
        se = (60.0 / interv) if interv else None
        so = None if pd.isna(x.salidas) else float(x.salidas)
        c006 = int(x.hora) not in alertas.HORAS_BORDE and se is not None and so is not None and se >= 1 and (
            so == 0 or (se >= float(u["salidas_minimas_esperadas"]) and se - so >= 1
                        and (se - so) / se > float(u["tolerancia_salidas"])))
        occ = _ocupacion_hora(x, u, alertas, factores, capacidades)
        c002 = None if occ is None else occ >= float(u["ocupacion_critica"])
        out[(x.ruta, x.fecha, int(x.hora))] = (c005, s007, c006, c002)
    return out


def _confirmar_ruptura(a, series, u, dias=14):
    """¿El nivel nuevo se sostuvo? El residuo medio de los `dias` días siguientes a la detección se aparta del nivel
    anterior en el mismo sentido al menos la mitad del cambio mínimo. None si quedan menos de 7 días para medirlo."""
    v = a["variables"]
    det = date.fromisoformat(v["fecha_deteccion"])
    despues = [(x["observado"] - x["esperado"]) / x["esperado"] for x in series.get(a["ruta"], [])
               if det < x["fecha"] <= det + timedelta(days=dias) and x["esperado"] > 0]
    if len(despues) < 7:
        return None
    signo = 1 if v["sentido_desviacion"] == "+" else -1
    nivel_anterior = v["residuo_medio_tramo"] - v["cambio_medio"]
    return signo * (float(np.mean(despues)) - nivel_anterior) >= float(u["ruptura_cambio_minimo"]) / 2


def _clave_codigo(a):
    return "ALT-007 ruptura" if a["variables"].get("variante") == "ruptura_comportamiento" else a["codigo"]


def correr(ctxs, h, diarios, umbrales, alertas, series=None):
    u = alertas._umbrales(umbrales)
    cond = _condiciones(h, u, alertas)
    especiales = {(r, f): int(e) for r, f, e in zip(diarios["ruta"], diarios["fecha"], diarios["especial"],
                                                     strict=False)}
    excluidos = {(r, f): int(e) for r, f, e in zip(diarios["ruta"], diarios["fecha"], diarios["excluido"],
                                                    strict=False)}
    por_codigo = defaultdict(lambda: {"n": 0, "confirmadas": 0, "evaluables": 0, "especial": 0, "horas": 0})
    series = series or {}
    detalle_rupturas = []
    for (ruta, fecha), ctx in ctxs.items():
        for a in alertas.evaluar_observadas(ctx, u):
            clave = _clave_codigo(a)
            c = por_codigo[clave]
            c["n"] += 1
            c["especial"] += especiales.get((ruta, fecha), 0)
            if clave == "ALT-007 ruptura":
                real = _confirmar_ruptura(a, series, u)
                if real is not None:
                    c["evaluables"] += 1
                    c["confirmadas"] += int(real)
                detalle_rupturas.append({k: a["variables"].get(k) for k in (
                    "fecha_inicio_cambio", "fecha_deteccion", "sentido_desviacion", "cambio_medio",
                    "residuo_medio_tramo", "estadistico_cusum")} | {"ruta": ruta, "confirmada": real})
            elif clave in ("ALT-002", "ALT-005", "ALT-006", "ALT-007"):
                # precisión proxy: ¿la condición siguió en la hora posterior a la DETECCIÓN (cuando se cumplió la
                # persistencia)? = el episodio duró más horas que las necesarias para alertar.
                k = int(float(u["persistencia_ocupacion_horas" if clave == "ALT-002" else "persistencia_horas"]))
                n_h = int(a["variables"].get("horas_seguidas") or a["variables"].get("horas_episodio") or 1)
                det = 1 if (clave == "ALT-006" and a["variables"].get("por_tiempo")) else k
                c["horas"] += n_h
                siguiente = a["ventana_inicio"] + timedelta(hours=det)
                if siguiente.date() == a["ventana_inicio"].date() and siguiente.hour in HORAS_EVAL:
                    c["evaluables"] += 1
                    c["confirmadas"] += int(n_h > det)
            elif clave == "ALT-008":
                c["evaluables"] += 1
                c["confirmadas"] += int(excluidos.get((ruta, fecha), 0) or especiales.get((ruta, fecha), 0))
    vals = list(cond.values())
    medibles = [v[3] for v in vals if v[3] is not None]
    base = {"ALT-005": float(np.mean([v[0] for v in vals])) if vals else None,
            "ALT-007": float(np.mean([v[1] != 0 for v in vals])) if vals else None,
            "ALT-006": float(np.mean([v[2] for v in vals])) if vals else None,
            "ALT-002": float(np.mean(medibles)) if medibles else None,
            "ALT-008": float(np.mean([bool(excluidos.get(k, 0) or especiales.get(k, 0)) for k in ctxs])) if ctxs
            else None}
    dias_ruta = len(ctxs)
    dias = len({f for _, f in ctxs})
    res = {}
    for codigo in CODIGOS_OBSERVADOS:
        c = por_codigo.get(codigo, {"n": 0, "confirmadas": 0, "evaluables": 0, "especial": 0, "horas": 0})
        prec = c["confirmadas"] / c["evaluables"] if c["evaluables"] else None
        res[codigo] = {
            "alertas": c["n"], "por_ruta_dia": round(c["n"] / dias_ruta, 4) if dias_ruta else None,
            "por_dia_3_rutas": round(c["n"] / dias, 3) if dias else None,
            "horas_en_alerta": c["horas"],
            "pct_dias_especiales": round(100 * c["especial"] / c["n"], 1) if c["n"] else None,
            "precision_proxy": None if prec is None else round(prec, 4), "evaluables": c["evaluables"],
            "tasa_base": None if base.get(codigo) is None else round(base[codigo], 4),
            "lift": round(prec / base[codigo], 2) if prec is not None and base.get(codigo) else None}
    total = sum(v["alertas"] for v in res.values())
    sin_nuevas = sum(v["alertas"] for c, v in res.items() if c in CODIGOS_ANTERIORES)
    return {"por_codigo": res, "dias_ruta": dias_ruta, "dias": dias,
            "observadas_por_ruta_dia": round(total / dias_ruta, 3) if dias_ruta else None,
            "observadas_por_ruta_dia_005_009": round(sin_nuevas / dias_ruta, 3) if dias_ruta else None,
            "rupturas": detalle_rupturas}


CODIGOS_OBSERVADOS = ("ALT-002", "ALT-005", "ALT-006", "ALT-007", "ALT-007 ruptura", "ALT-008", "ALT-009")
CODIGOS_ANTERIORES = ("ALT-005", "ALT-006", "ALT-007", "ALT-008", "ALT-009")
CODIGOS_SENSIBILIDAD = ("ALT-002", "ALT-005", "ALT-006", "ALT-007", "ALT-007 ruptura", "ALT-008")


def ejemplos(ctxs, umbrales, alertas):
    """La primera alerta de cada código (estructura completa de §5.3, tal como la guardaría el ciclo)."""
    vistos = {}
    for ctx in ctxs.values():
        for a in alertas.evaluar_observadas(ctx, umbrales):
            vistos.setdefault(_clave_codigo(a), a)
        if len(vistos) >= 6:
            break
    return [vistos[c] for c in sorted(vistos)]


def _falsas_por_variante(series, u, alertas, permutaciones=50, semilla=11):
    """Falsas alarmas sin cambio (por 100 días-ruta, 50 permutaciones) para h = 4, 5 y 6 y cambio mínimo 5 % y 8 %:
    la evidencia de la elección de h y del cambio mínimo."""
    n_ref = int(float(u["ruptura_dias_referencia"]))
    salida = {}
    for h in (4.0, 5.0, 6.0):
        for minimo in (0.05, 0.08):
            v = dict(u, ruptura_h=h, ruptura_cambio_minimo=minimo)
            rng = np.random.default_rng(semilla)
            falsas = dias = 0
            for _, s in sorted(series.items()):
                if len(s) <= n_ref:
                    continue
                cabeza, cola = s[:n_ref], s[n_ref:]
                for _ in range(permutaciones):
                    orden = rng.permutation(len(cola))
                    mezcla = cabeza + [dict(cola[j], fecha=cola[i]["fecha"]) for i, j in enumerate(orden)]
                    falsas += len(alertas.detectar_rupturas(mezcla, v)["detecciones"])
                    dias += len(cola)
            salida[f"h={h:g}, cambio_minimo={minimo:.0%}"] = round(100 * falsas / dias, 3) if dias else None
    return salida


def evaluar_detector(series, umbrales, alertas, permutaciones=200, semilla=7):
    """El detector de rupturas (RF-009) en tres pruebas: las detecciones reales de 2025 (las cuenta correr), su tasa
    de falsas alarmas SIN cambio (permutando los días vigilados de cada ruta: misma distribución, sin ruptura) y su
    potencia frente a cambios de nivel inyectados (−10 %, −20 % y +15 % desde un día dado)."""
    u = alertas._umbrales(umbrales)
    n_ref = int(float(u["ruptura_dias_referencia"]))
    rng = np.random.default_rng(semilla)
    falsas, dias_vigilados = 0, 0
    for _, s in sorted(series.items()):
        if len(s) <= n_ref:
            continue
        cabeza, cola = s[:n_ref], s[n_ref:]
        for _ in range(permutaciones):
            orden = rng.permutation(len(cola))
            mezcla = cabeza + [dict(cola[j], fecha=cola[i]["fecha"]) for i, j in enumerate(orden)]
            falsas += len(alertas.detectar_rupturas(mezcla, u)["detecciones"])
            dias_vigilados += len(cola)
    potencia = {}
    for cambio in (-0.10, -0.20, 0.15):
        detectadas, retardos, casos = 0, [], 0
        for _, s in sorted(series.items()):
            for desde in (10, 25, 40):
                i0 = n_ref + desde
                if i0 + 14 >= len(s):
                    continue
                casos += 1
                mod = [dict(x, observado=x["observado"] * (1 + cambio)) if i >= i0 else dict(x)
                       for i, x in enumerate(s)]
                dets = [d for d in alertas.detectar_rupturas(mod, u)["detecciones"]
                        if s[i0]["fecha"] <= d["fecha_deteccion"] <= s[i0 + 14]["fecha"]
                        and d["lado"] == (1 if cambio > 0 else -1)]
                if dets:
                    detectadas += 1
                    retardos.append((dets[0]["fecha_deteccion"] - s[i0]["fecha"]).days)
        potencia[f"{cambio:+.0%}"] = {"casos": casos, "detectadas_en_14_dias": detectadas,
                                      "tasa": round(detectadas / casos, 3) if casos else None,
                                      "retardo_mediano_dias": float(np.median(retardos)) if retardos else None}
    return {"parametros": {k: u[k] for k in ("ruptura_k", "ruptura_h", "ruptura_dias_referencia",
                                              "ruptura_cambio_minimo", "ruptura_dias_reinicio")},
            "falsas_por_100_segun_h_y_cambio_minimo": _falsas_por_variante(series, u, alertas),
            "falsas_alarmas_sin_cambio": {
                "permutaciones_por_ruta": permutaciones, "dias_vigilados": dias_vigilados, "detecciones": falsas,
                "por_100_dias_ruta": round(100 * falsas / dias_vigilados, 3) if dias_vigilados else None},
            "potencia_cambios_inyectados": potencia}


CODIGOS_PRONOSTICO = ("ALT-001", "ALT-002", "ALT-003", "ALT-004")
VARIANTES_PRONOSTICO = ("ventana", "franja")
METODO_VARIANTE = {
    "ventana": ("demanda de la VENTANA de 30/60/120 min frente a la capacidad POR HORA; ventana de la alerta = hora "
                "del fin de la ventana (7 h y 8 h en 60 y 120 min, no la hora recomendada); una alerta por horizonte"),
    "franja": ("alertas.contexto_pronostico + evaluar_pronostico (lo que hace hoy el ciclo): carga crítica POR HORA "
               "de la franja recomendada (factor de carga del optimizador × P10/P50/P90 por hora) frente a la "
               "capacidad POR HORA ofrecida; ALT-003 por el nivel de servicio de la frecuencia actual "
               "(comparacion_actual); ventana de la alerta = la hora recomendada; los horizontes que caen en la misma "
               "franja dan una sola alerta"),
}


def _contexto_ventana(ruta, inicio, h, r, entradas, rec_d):
    """El contexto de las alertas de pronóstico como lo armaba el ciclo antes de la corrección (solo para comparar):
    la demanda de la ventana de h minutos frente a la capacidad por hora, con la ventana en la hora del objetivo."""
    frec = entradas.get("frecuencia_actual_min")
    return {"ruta": ruta, "empresa": "Sobusa", "detectada_en": inicio - timedelta(hours=6), "ventana_inicio": inicio,
            "ventana_fin": inicio + timedelta(hours=1), "horizonte_min": int(h), "demanda_prevista": r["pasajeros"],
            "p10": r["p10"], "p90": r["p90"], "capacidad": entradas["capacidad"],
            "buses_hora_actual": (60.0 / frec) if frec else None, "buses_hora_recomendado": rec_d.get("buses_hora"),
            "model_id": r["model_id"]}


def _observado_horario(datos):
    """{(ruta, fecha, hora): pasajeros observados} de la serie horaria (para confirmar ALT-001 y ALT-002)."""
    s = datos.demanda_horaria()
    fechas = pd.to_datetime(s["fecha"]).dt.date
    return {(r, f, int(h)): (None if pd.isna(p) else float(p))
            for r, f, h, p in zip(s["ruta"], fechas, s["hora"], s["pasajeros"], strict=False)}


def _real_en_la_hora(ctx, observado):
    """(pasajeros reales en la hora de la ventana, capacidad por hora del contexto, factor de carga) o None si falta
    alguno. El factor es el de la franja (1 en los contextos sin factor)."""
    if not ctx.get("buses_hora_actual") or ctx.get("capacidad") is None:
        return None
    ini = ctx["ventana_inicio"].astimezone(ZONA)
    obs = observado.get((ctx["ruta"], ini.date(), ini.hour))
    if obs is None:
        return None
    return obs, float(ctx["buses_hora_actual"]) * float(ctx["capacidad"]), float(ctx.get("factor_carga") or 1.0)


def _condiciones_reales(ctx, observado, u):
    """{código: lo observado en la hora confirmó la condición}, con la carga crítica real = factor de carga × pasajeros
    reales (las mismas unidades de la alerta): ALT-001 carga real > capacidad por hora; ALT-002 ocupación real ≥
    ocupacion_critica; ALT-003 carga real > capacidad efectiva (capacidad × ocupación objetivo máxima); ALT-004
    ocupación real < baja_utilizacion. Vacío si no hay dato real."""
    par = _real_en_la_hora(ctx, observado)
    if par is None:
        return {}
    obs, cap, factor = par
    carga = factor * obs
    occ_max = float(ctx.get("ocupacion_objetivo_max") or u["ocupacion_objetivo_max"])
    return {"ALT-001": carga > cap, "ALT-002": carga / cap >= float(u["ocupacion_critica"]),
            "ALT-003": carga > cap * occ_max, "ALT-004": carga / cap < float(u["baja_utilizacion"])}


def _pronosticos_ruta_dia(ruta, info, instante, cache, medidas):
    """Las predicciones de 30/60/120 min de una ruta a las 6:00 con su franja y su recomendación (recomendacion_franja,
    en caché por franja). Devuelve {variante: [contextos]}."""
    from types import SimpleNamespace

    from app.routers.predicciones import _franja_de_la_prediccion
    from app.servicios import alertas, ejecucion, inferencia, optimizacion

    ctxs = {v: [] for v in VARIANTES_PRONOSTICO}
    for h in (30, 60, 120):
        try:
            r = inferencia.predecir(ruta, instante, h, usar_nowcast=False)
        except ValueError:
            continue
        objetivo = (instante + timedelta(minutes=h)).astimezone(ZONA)
        pred = SimpleNamespace(variables=ejecucion.json_seguro(r["variables"]), fecha=objetivo.date(),
                               hora=objetivo.hour, pasajeros=r["pasajeros"], p10=r["p10"], p90=r["p90"],
                               horizonte_min=h)
        franja = _franja_de_la_prediccion(pred)
        clave = (ruta, franja["fecha"], franja["hora"], franja["demanda_hora"], franja["p90_hora"])
        if clave not in cache:
            t1 = time.perf_counter()
            cache[clave] = optimizacion.recomendacion_franja(
                dict(info, ruta=ruta), medidas["u"], None, hora=franja["hora"], fecha=franja["fecha"],
                demanda_hora=franja["demanda_hora"], demanda_p90=franja["p90_hora"], demanda_p10=franja["p10_hora"])
            medidas["seg_milp"] += time.perf_counter() - t1
            medidas["n_milp"] += 1
        rec, ent = cache[clave]
        medidas["buses"][h].append(rec.get("buses_hora"))
        medidas["viables"].append(bool(rec.get("viable", True)))
        medidas["franjas"][f"{h}->{franja['hora']:02d} h"] += 1
        ctxs["ventana"].append(_contexto_ventana(ruta, objetivo.replace(minute=0, second=0, microsecond=0), h, r,
                                                 ent, rec))
        ctxs["franja"].append(alertas.contexto_pronostico(ruta, h, franja, r, ent, rec, empresa="Sobusa",
                                                          detectada_en=instante))
    return ctxs


def _contar_variante(v, ctxs, observado, u, acum):
    """Cuenta las alertas de la variante v en una ruta-día y su confirmación con lo observado en la hora de la
    alerta; la tasa base es la de la condición en las horas distintas que miran los contextos."""
    from app.servicios import alertas

    if v == "franja":
        lista = alertas.evaluar_pronostico(ctxs, u)
    else:
        lista = [a for c in ctxs for a in alertas.evaluar_alertas(c, u)]
    por_h = {c["horizonte_min"]: c for c in ctxs}
    for a in lista:
        if a["codigo"] not in CODIGOS_PRONOSTICO:
            continue
        acum["conteo"][a["codigo"]] += 1
        real = _condiciones_reales(por_h[a["horizonte_min"]], observado, u).get(a["codigo"])
        if real is not None:
            acum["evaluables"][a["codigo"]] += 1
            acum["confirmadas"][a["codigo"]] += int(real)
    horas = {(c["ruta"], c["ventana_inicio"]): c for c in ctxs}
    for c in horas.values():
        for codigo, real in _condiciones_reales(c, observado, u).items():
            acum["base_n"][codigo] += 1
            acum["base_si"][codigo] += int(real)


def _resumen_variante(acum, dias_ruta):
    salida = {}
    for c in CODIGOS_PRONOSTICO:
        n, ev, conf = acum["conteo"][c], acum["evaluables"][c], acum["confirmadas"][c]
        fila = {"alertas": n, "por_ruta_dia": round(n / dias_ruta, 3) if dias_ruta else None}
        if c in CODIGOS_PRONOSTICO:
            prec = conf / ev if ev else None
            base = acum["base_si"][c] / acum["base_n"][c] if acum["base_n"][c] else None
            fila.update({"evaluables": ev, "confirmadas": conf,
                         "precision_real": None if prec is None else round(prec, 4),
                         "tasa_base_real": None if base is None else round(base, 4),
                         "lift": round(prec / base, 2) if prec is not None and base else None})
        salida[c] = fila
    return salida


def _antes_pronostico(anterior: Path) -> dict | None:
    """Cifras de corridas anteriores del modo --pronostico (se conservan entre corridas)."""
    if not anterior.exists():
        return None
    try:
        previo = json.loads(anterior.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if previo.get("antes"):
        return previo["antes"]
    var = previo.get("variantes") or {}
    if "anterior" not in var:
        return None
    return {"generado": previo.get("generado"),
            "recomendar_ventana": {c: v.get("por_ruta_dia") for c, v in var["anterior"]["por_codigo"].items()},
            "metodo": var["anterior"].get("metodo")}


def _antes_sin_factor(anterior: Path) -> dict | None:
    """Las cifras de la corrida anterior a la ocupación con factor de carga (abordajes / capacidad, ALT-003 por número
    de buses); se conservan entre corridas."""
    if not anterior.exists():
        return None
    try:
        previo = json.loads(anterior.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if previo.get("con_factor_carga"):
        return previo.get("antes_sin_factor")
    franja = (previo.get("variantes") or {}).get("franja") or {}
    return {"generado": previo.get("generado"),
            "recomendaciones_viables_pct": previo.get("recomendaciones_viables_pct"),
            "por_codigo": {c: {k: v.get(k) for k in ("alertas", "por_ruta_dia", "precision_real", "lift")}
                           for c, v in (franja.get("por_codigo") or {}).items()}}


def _festivos_entre_semana(desde, hasta) -> list[str]:
    """Festivos de lunes a sábado del periodo: el plan y la recomendación los tratan como domingo o festivo."""
    from app.servicios import optimizacion

    salida, d = [], desde
    while d <= hasta:
        if d.weekday() < 6 and optimizacion.es_festivo(d):
            salida.append(str(d))
        d += timedelta(days=1)
    return salida


def pronostico(desde, hasta, salida: Path) -> dict:
    """ALT-001..ALT-004 del ciclo diario (6:00 del día, horizontes 30/60/120 min, recomendacion_franja) con el
    contexto ANTERIOR (demanda de la ventana frente a capacidad por hora) y el ACTUAL (demanda por hora de la franja
    frente a capacidad por hora, una alerta por franja). ALT-001 y ALT-002 se confirman con la demanda real de la
    hora de la alerta: real > capacidad por hora y ocupación real ≥ 90 %."""
    from app.servicios import alertas, datos, inferencia

    t0 = time.perf_counter()
    u = dict(alertas.UMBRALES_POR_DEFECTO)
    catalogo = {x["ruta"]: x for x in datos.catalogo_rutas()}
    observado = _observado_horario(datos)
    acum = {v: {k: defaultdict(int) for k in ("conteo", "evaluables", "confirmadas", "base_n", "base_si")}
            for v in VARIANTES_PRONOSTICO}
    medidas = {"u": u, "seg_milp": 0.0, "n_milp": 0, "buses": defaultdict(list), "viables": [],
               "franjas": defaultdict(int)}
    dias_ruta, cache = 0, {}
    d = desde
    while d <= hasta:
        instante = datetime.combine(d, dtime(6, 0), tzinfo=ZONA)
        for ruta, info in catalogo.items():
            dias_ruta += 1
            ctxs = _pronosticos_ruta_dia(ruta, info, instante, cache, medidas)
            for v in VARIANTES_PRONOSTICO:
                _contar_variante(v, ctxs[v], observado, u, acum[v])
        d += timedelta(days=1)
    res = {"generado": datetime.now(ZONA).isoformat(timespec="seconds"), "periodo": [str(desde), str(hasta)],
           "dias_ruta": dias_ruta, "instante": "6:00 de cada día (el instante por omisión del ciclo diario)",
           "horizontes_min": [30, 60, 120], "umbrales": "alertas.UMBRALES_POR_DEFECTO (versión 0003)",
           "calibracion_banda": (inferencia.cargar(None).get("calibracion") or {}).get("version", "v1"),
           "recomendacion": "recomendacion_franja(): §10.2 (MILP) con la demanda por hora de la franja",
           "franja_por_horizonte": dict(sorted(medidas["franjas"].items(), key=_por_horizonte)),
           "buses_hora_medios_por_horizonte": {str(h): round(float(np.mean([b for b in xs if b is not None])), 2)
                                               for h, xs in sorted(medidas["buses"].items())},
           "recomendaciones_viables_pct": round(100 * float(np.mean(medidas["viables"])), 1),
           "nota_precision": ("cada alerta se confirma con la demanda REAL de su hora, en las mismas unidades: carga "
                              "crítica real = factor de carga × pasajeros reales; ALT-001 si superó la capacidad por "
                              "hora (buses/h programados × 50 puestos), ALT-002 si la ocupación real llegó al 90 %, "
                              "ALT-003 si superó la capacidad efectiva (× 85 %) y ALT-004 si la ocupación real quedó "
                              "bajo el 30 %; la tasa base es la de esa condición en las horas que miran los contextos "
                              "(lift = precisión / tasa base)."),
           "variantes": {v: {"metodo": METODO_VARIANTE[v], "por_codigo": _resumen_variante(acum[v], dias_ruta)}
                         for v in VARIANTES_PRONOSTICO},
           "milp": {"llamadas": medidas["n_milp"],
                    "segundos_medios": round(medidas["seg_milp"] / medidas["n_milp"], 3) if medidas["n_milp"]
                    else None}}
    res["antes"] = _antes_pronostico(salida / "backtest_alertas_pronostico.json")
    res["con_factor_carga"] = True
    res["antes_sin_factor"] = _antes_sin_factor(salida / "backtest_alertas_pronostico.json")
    res["festivos_entre_semana"] = _festivos_entre_semana(desde, hasta)
    res["duracion_s"] = round(time.perf_counter() - t0, 1)
    salida.mkdir(parents=True, exist_ok=True)
    (salida / "backtest_alertas_pronostico.json").write_text(json.dumps(res, ensure_ascii=False, indent=1,
                                                                        default=str), encoding="utf-8")
    (salida / "backtest_alertas_pronostico.md").write_text(informe_pronostico(res), encoding="utf-8")
    return res


def _por_horizonte(par):
    """Orden numérico de las claves «30->06 h», «60->06 h», «120->06 h»."""
    return int(par[0].split("->")[0])


def _celda(x, d=3):
    return "—" if x is None else f"{x:.{d}f}".replace(".", ",")


def informe_pronostico(r: dict) -> str:
    f = _celda
    a, n = r["variantes"]["ventana"]["por_codigo"], r["variantes"]["franja"]["por_codigo"]
    lin = [f"# Alertas de pronóstico ALT-001..ALT-004 del ciclo diario ({r['periodo'][0]} a {r['periodo'][1]})", "",
           f"Generado {r['generado']} con `scripts/backtest_alertas.py --pronostico` ({f(r['duracion_s'], 1)} s). "
           f"{r['dias_ruta']} días-ruta; instante {r['instante']}; horizontes 30, 60 y 120 min; umbrales "
           f"{r['umbrales']}; banda calibrada {r['calibracion_banda']}; recomendación {r['recomendacion']}.", "",
           f"- **Antes de la corrección**: {r['variantes']['ventana']['metodo']}.",
           f"- **Ahora**: {r['variantes']['franja']['metodo']}.", "",
           "| Código | Antes: alertas | Antes: por ruta y día | Ahora: alertas | Ahora: por ruta y día |",
           "|---|---|---|---|---|"]
    for c in CODIGOS_PRONOSTICO:
        lin.append(f"| {c} | {a[c]['alertas']} | {f(a[c]['por_ruta_dia'])} | {n[c]['alertas']} | "
                   f"{f(n[c]['por_ruta_dia'])} |")
    lin += ["", "Confirmación con la demanda real de la hora de la alerta (" + r["nota_precision"] + ")", "",
            "| Código | Variante | Evaluables | Confirmadas | Precisión | Tasa base | Lift |",
            "|---|---|---|---|---|---|---|"]
    for c in CODIGOS_PRONOSTICO:
        for etiqueta, v in (("antes", a[c]), ("ahora", n[c])):
            lin.append(f"| {c} | {etiqueta} | {v['evaluables']} | {v['confirmadas']} | {f(v['precision_real'])} | "
                       f"{f(v['tasa_base_real'])} | {f(v['lift'], 2)} |")
    sf = r.get("antes_sin_factor")
    if sf:
        lin += ["", f"Antes de medir con el factor de carga (corrida del {sf['generado']}: ocupación = abordajes / "
                    "capacidad, ALT-003 por número de buses): "
                    + ", ".join(f"{c} {f(v.get('por_ruta_dia'))}" for c, v in sf["por_codigo"].items())
                    + " alertas por ruta y día."]
    if r.get("festivos_entre_semana") is not None:
        lin += ["", f"Festivos entre semana del periodo ({len(r['festivos_entre_semana'])}, tratados como domingo o "
                    "festivo en la programación y el factor de carga): "
                    + (", ".join(r["festivos_entre_semana"]) or "ninguno") + "."]
    lin += ["", "Franja recomendada por horizonte (horizonte -> hora principal de la ventana, número de "
                "predicciones): " + ", ".join(f"{k}: {v}" for k, v in sorted(r["franja_por_horizonte"].items(),
                                                                                key=_por_horizonte)) + ".",
            "", "Buses/h recomendados en promedio por horizonte: "
                + ", ".join(f"{h} min {f(b, 2)}" for h, b in r["buses_hora_medios_por_horizonte"].items())
                + f". Recomendaciones viables: {f(r['recomendaciones_viables_pct'], 1)} %. MILP: "
                  f"{r['milp']['llamadas']} franjas distintas, {f(r['milp']['segundos_medios'])} s de media.", ""]
    antes = r.get("antes")
    if antes:
        lin += [f"Antes de la recomendación por franja (corrida del {antes['generado']}, recomendar() con la demanda "
                "de la ventana): " + ", ".join(f"{c} {f(v)}" for c, v in antes["recomendar_ventana"].items())
                + " alertas por ruta y día.", ""]
    return "\n".join(lin)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--corte", type=date.fromisoformat, default=None,
                    help="entrena un fv2 temporal con este corte en un directorio aparte (no toca datos/modelos)")
    ap.add_argument("--desde", type=date.fromisoformat, default=None)
    ap.add_argument("--hasta", type=date.fromisoformat, default=date(2025, 12, 31))
    ap.add_argument("--salida", type=Path, default=SALIDA)
    ap.add_argument("--sin-sensibilidad", action="store_true")
    ap.add_argument("--pronostico", action="store_true",
                    help="ALT-001..ALT-004 del ciclo diario con la recomendación anterior y la actual")
    args = ap.parse_args(argv)

    from app.servicios import alertas, datos, inferencia

    if args.pronostico:
        modelo = inferencia.cargar(None)
        corte = modelo["data_cutoff"]
        r = pronostico(args.desde or (corte + timedelta(days=inferencia.CONFORMAL_MIN_DIAS + 1)), args.hasta,
                       args.salida)
        print(informe_pronostico(r))
        return r

    t0 = time.perf_counter()
    if args.corte:
        tmp = Path(tempfile.mkdtemp(prefix="backtest_alertas_"))
        info = inferencia.entrenar(args.corte, semilla=42, dir_modelos=tmp)
        modelo = inferencia.cargar(info["model_id"], tmp)
        etiqueta = f"fv2 temporal (corte {args.corte}, semilla 42, en {tmp.name})"
    else:
        modelo = inferencia.cargar(None)
        etiqueta = f"modelo activo {modelo['model_id']}"
    corte = modelo.get("data_cutoff")
    corte = corte if isinstance(corte, date) else pd.Timestamp(corte).date()
    desde = args.desde or (corte + timedelta(days=inferencia.CONFORMAL_MIN_DIAS + 1))
    tabla = inferencia.tabla_variables()
    pron = _pronosticos(modelo, inferencia, tabla, desde, args.hasta)
    par = datos.parametros_operativos()
    parametros = {(r, t, int(x)): float(v) for r, t, x, v in zip(par["ruta"], par["tipo_dia"], par["hora"],
                                                                  par["intervalo_programado_min"], strict=False)}
    serie = datos.demanda_horaria()
    ctxs, h, diarios = _contextos(serie, pron, parametros, datos, alertas, desde, args.hasta)
    series = series_diarias(h, datos)

    por_defecto = {k: v for k, v in alertas.UMBRALES_POR_DEFECTO.items() if k != "version"}
    anteriores = dict(por_defecto, persistencia_horas=1, alt005_exigir_p10=0, tolerancia_salidas=0.2, z_anomalia=3.0)
    cal = modelo.get("calibracion")
    resultado = {
        "generado": datetime.now(ZONA).isoformat(timespec="seconds"), "modelo": etiqueta,
        "model_id": modelo["model_id"], "data_cutoff": str(corte), "periodo": [str(desde), str(args.hasta)],
        "calibracion_version": cal["version"] if cal else "v1",
        "calibracion": (f"{cal['nombre']} ({cal['archivo']}, SHA-256 {cal['sha256'][:12]}…)" if cal else
                        inferencia.CALIBRACION_V1),
        "banda_calibrada_pct_horas": round(100 * float(pron["calibrada"].mean()), 1),
        "festivos_entre_semana": _festivos_entre_semana(desde, args.hasta),
        "tolerancia_tiempo_min": "Procesos.toleranciatiempo = 0 en la exportación: se usa tolerancia_despacho_min",
        "nota_precision": ("No hay incidentes etiquetados: la precisión se aproxima con la persistencia de la "
                           "condición en la hora siguiente a la DETECCIÓN, es decir, el episodio dura más horas que "
                           "las necesarias para alertar (ALT-005/006/007), o con el día marcado como especial o "
                           "excluido (ALT-008); lift = precisión / tasa base de la condición en una hora cualquiera. "
                           "Una alerta no confirmada se cuenta como falso positivo (§18)."),
        "umbrales_por_defecto": por_defecto,
        "por_defecto": correr(ctxs, h, diarios, por_defecto, alertas, series),
        "detector_rupturas": evaluar_detector(series, por_defecto, alertas),
        "ejemplos": ejemplos(ctxs, por_defecto, alertas),
        "reglas_anteriores": {"umbrales": {k: anteriores[k] for k in ("persistencia_horas", "alt005_exigir_p10",
                                                                     "tolerancia_salidas", "z_anomalia")},
                              **correr(ctxs, h, diarios, anteriores, alertas)},
    }
    if not args.sin_sensibilidad:
        sens = {}
        for nombre, valores in VARIACIONES.items():
            for v in valores:
                r = correr(ctxs, h, diarios, dict(por_defecto, **{nombre: v}), alertas, series)
                sens[f"{nombre}={v}"] = {c: {k: r["por_codigo"][c][k] for k in ("por_ruta_dia", "precision_proxy",
                                                                                 "lift")}
                                         for c in CODIGOS_SENSIBILIDAD}
        resultado["sensibilidad"] = sens
    resultado["duracion_s"] = round(time.perf_counter() - t0, 1)
    args.salida.mkdir(parents=True, exist_ok=True)
    sufijo = f"_corte_{args.corte}" if args.corte else ""
    resultado["antes_del_cambio"] = antes_del_cambio(args.salida / f"backtest_alertas{sufijo}.json", resultado)
    (args.salida / f"backtest_alertas{sufijo}.json").write_text(
        json.dumps(resultado, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    (args.salida / f"backtest_alertas{sufijo}.md").write_text(informe(resultado), encoding="utf-8")
    print(informe(resultado))
    return resultado


def antes_del_cambio(anterior: Path, actual: dict) -> dict | None:
    """Cifras de la corrida anterior cuando cambió la calibración de la banda (se conservan entre corridas)."""
    if not anterior.exists():
        return None
    try:
        previo = json.loads(anterior.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if previo.get("antes_del_cambio") and previo.get("calibracion_version", "v1") == actual["calibracion_version"]:
        return previo["antes_del_cambio"]
    if previo.get("calibracion_version", "v1") == actual["calibracion_version"]:
        return None
    pd_ = previo.get("por_defecto") or {}
    return {"generado": previo.get("generado"), "calibracion_version": previo.get("calibracion_version", "v1"),
            "periodo": previo.get("periodo"), "observadas_por_ruta_dia": pd_.get("observadas_por_ruta_dia"),
            "por_codigo": {c: {k: v.get(k) for k in ("alertas", "por_ruta_dia", "precision_proxy", "lift")}
                           for c, v in (pd_.get("por_codigo") or {}).items()},
            "reglas_anteriores_por_ruta_dia": (previo.get("reglas_anteriores") or {}).get("observadas_por_ruta_dia")}


def _coma(x, d=3):
    return "—" if x is None else f"{x:.{d}f}".replace(".", ",")


def _informe_detector(r):
    """Sección del detector de rupturas: detecciones reales, falsas alarmas sin cambio y potencia."""
    det = r.get("detector_rupturas")
    if not det:
        return []
    fa, pot, par = det["falsas_alarmas_sin_cambio"], det["potencia_cambios_inyectados"], det["parametros"]
    lin = ["## Detector de rupturas de comportamiento (RF-009)", "",
           "CUSUM tabular de dos lados sobre el residuo diario relativo (real - pronóstico) / pronóstico de cada "
           f"ruta, "
           f"estandarizado con la mediana y 1,4826·MAD de los primeros {par['ruptura_dias_referencia']} días; k = "
           f"{_coma(par['ruptura_k'], 1)}, h = {_coma(par['ruptura_h'], 1)}, cambio mínimo "
           f"{_coma(100 * par['ruptura_cambio_minimo'], 0)} % y {par['ruptura_dias_reinicio']} días de espera tras "
           "cada detección (un cambio sostenido es una sola ruptura).", "",
           "| Ruta | Inicio estimado | Detección | Sentido | Cambio medio | CUSUM | Se sostuvo 14 días |",
           "|---|---|---|---|---|---|---|"]
    for x in r["por_defecto"].get("rupturas") or []:
        conf = "—" if x["confirmada"] is None else ("sí" if x["confirmada"] else "no")
        lin.append(f"| {x['ruta']} | {x['fecha_inicio_cambio']} | {x['fecha_deteccion']} | {x['sentido_desviacion']} | "
                   f"{_coma(100 * x['cambio_medio'], 1)} % | {_coma(x['estadistico_cusum'], 2)} | {conf} |")
    if not r["por_defecto"].get("rupturas"):
        lin.append("| — | — | — | — | — | — | — |")
    lin += ["", f"Falsas alarmas sin cambio (los días vigilados de cada ruta permutados {fa['permutaciones_por_ruta']} "
                f"veces: misma distribución de residuos, sin ruptura): {fa['detecciones']} detecciones en "
                f"{fa['dias_vigilados']} días-ruta = {_coma(fa['por_100_dias_ruta'])} por cada 100 días-ruta.", "",
            "| Cambio inyectado | Casos | Detectados en 14 días | Tasa | Retardo mediano (días) |",
            "|---|---|---|---|---|"]
    for k, v in pot.items():
        lin.append(f"| {k} | {v['casos']} | {v['detectadas_en_14_dias']} | {_coma(v['tasa'])} | "
                   f"{_coma(v['retardo_mediano_dias'], 1)} |")
    variantes = det.get("falsas_por_100_segun_h_y_cambio_minimo") or {}
    if variantes:
        lin += ["", "Falsas alarmas sin cambio por cada 100 días-ruta según h y el cambio mínimo (50 permutaciones por "
                    "ruta; la elección de los valores por omisión): "
                    + "; ".join(f"{k}: {_coma(v)}" for k, v in variantes.items()) + "."]
    return lin + [""]


def _fila(c, v):
    def f(x, d=3):
        return "—" if x is None else f"{x:.{d}f}".replace(".", ",")
    return (f"| {c} | {v['alertas']} | {f(v['por_ruta_dia'])} | {f(v['por_dia_3_rutas'], 2)} | "
            f"{f(v['precision_proxy'])} | {f(v['tasa_base'])} | {f(v['lift'], 2)} | "
            f"{'—' if v['pct_dias_especiales'] is None else str(v['pct_dias_especiales']).replace('.', ',') + ' %'} |")


def informe(r):
    cab = ("| Código | Alertas | Por ruta y día | Por día (3 rutas) | Precisión proxy | Tasa base | Lift | "
           "En días especiales |\n|---|---|---|---|---|---|---|---|")
    lin = ["# Backtest de alertas observadas: ALT-002 (ocupación observada), ALT-005..ALT-009 y rupturas "
           f"({r['periodo'][0]} a {r['periodo'][1]})", "",
           f"Generado {r['generado']} con scripts/backtest_alertas.py. Modelo: {r['modelo']} (corte "
           f"{r['data_cutoff']}). Banda P10-P90 calibrada en el "
           f"{str(r['banda_calibrada_pct_horas']).replace('.', ',')} "
           f"% de las horas. {r['por_defecto']['dias_ruta']} días-ruta, {r['por_defecto']['dias']} días.", "",
           f"Calibración de la banda: {r.get('calibracion_version', 'v1')} — "
           f"{r.get('calibracion', 'conformal móvil por ruta')}. ALT-005 y ALT-007 dependen de esa banda; ALT-006, "
           "ALT-008 y ALT-009 no.", ""]
    a = r.get("antes_del_cambio")
    if a:
        def g(x, d=3):
            return "—" if x is None else f"{x:.{d}f}".replace(".", ",")
        lin += [f"**Antes del cambio** (calibración {a['calibracion_version']}, corrida del {a['generado']}): "
                f"{g(a['observadas_por_ruta_dia'])} alertas observadas por ruta y día; "
                + "; ".join(f"{c} {g(v['por_ruta_dia'], 4)} por ruta y día (precisión {g(v['precision_proxy'])}, lift "
                            f"{g(v['lift'], 2)})" for c, v in a["por_codigo"].items() if v.get("alertas"))
                + (f". Reglas anteriores: {g(a['reglas_anteriores_por_ruta_dia'])}." if
                   a.get("reglas_anteriores_por_ruta_dia") is not None else "."), ""]
    if r.get("festivos_entre_semana") is not None:
        lin += [f"Festivos entre semana del periodo ({len(r['festivos_entre_semana'])}): "
                + (", ".join(r["festivos_entre_semana"]) or "ninguno") + ". Cuentan como domingo o festivo para la "
                "programación, el factor de carga y la referencia del consolidado.", ""]
    lin += [r["nota_precision"], "", f"ALT-006: {r['tolerancia_tiempo_min']}.", "",
           "## Umbrales por defecto (versionados en threshold_config por la migración 0003)", "", cab]
    lin += [_fila(c, v) for c, v in r["por_defecto"]["por_codigo"].items()]
    pdx = r["por_defecto"]
    lin += ["", f"Alertas observadas por ruta y día (todas): {_coma(pdx['observadas_por_ruta_dia'])}; solo ALT-005 a "
                f"ALT-009 (las que ya medía la versión anterior): {_coma(pdx.get('observadas_por_ruta_dia_005_009'))}.",
            "", "- ALT-002 observada: ocupación = factor de carga de la franja × pasajeros / (salidas × puestos) "
                "≥ 90 % "
                "en horas con al menos 2 salidas (no en la primera ni en la última hora de servicio); precisión proxy: "
                "el episodio sigue en la hora siguiente.",
            "- ALT-007 ruptura (RF-009): CUSUM de dos lados sobre el residuo diario relativo; precisión proxy: el "
            "nivel "
            "nuevo se sostiene en los 14 días siguientes (ver la sección del detector).", ""]
    lin += _informe_detector(r)
    lin += ["## Reglas anteriores (sin persistencia, sin P10, tolerancia de salidas 20 %, |z| 3,0)", "", cab]
    lin += [_fila(c, v) for c, v in r["reglas_anteriores"]["por_codigo"].items()]
    ra = r["reglas_anteriores"]
    lin += ["", f"Alertas observadas por ruta y día (todas): {_coma(ra['observadas_por_ruta_dia'])}; solo ALT-005 a "
                f"ALT-009: {_coma(ra.get('observadas_por_ruta_dia_005_009'))}."]
    if r.get("sensibilidad"):
        lin += ["", "## Sensibilidad (un umbral a la vez; por ruta y día / precisión proxy / lift)", "",
                "| Variación | " + " | ".join(CODIGOS_SENSIBILIDAD) + " |",
                "|---|" + "---|" * len(CODIGOS_SENSIBILIDAD)]
        for k, v in r["sensibilidad"].items():
            celdas = []
            for c in CODIGOS_SENSIBILIDAD:
                x = v[c]
                celdas.append(" / ".join("—" if x[m] is None else f"{x[m]:.3f}".replace(".", ",")
                                         for m in ("por_ruta_dia", "precision_proxy", "lift")))
            lin.append(f"| {k} | " + " | ".join(celdas) + " |")
    if r.get("ejemplos"):
        lin += ["", "## Un ejemplo por código (lo que vería el operador, §9.4)", "",
                "| Código | Ruta | Ventana | Real | Esperado | Umbral | Tendencia | Explicación |",
                "|---|---|---|---|---|---|---|---|"]
        for a in r["ejemplos"]:
            ini, fin = a["ventana_inicio"], a["ventana_fin"]
            ventana = f"{ini:%Y-%m-%d %H:%M}-{fin:%H:%M}" if hasattr(ini, "strftime") else str(ini)
            lin.append(f"| {a['codigo']} | {a['ruta']} | {ventana} | {a['observado']} | {a['esperado']} | "
                       f"{a['umbral']} | {a['tendencia']} | {a['explicacion']} |")
    lin += ["", f"Duración: {str(r['duracion_s']).replace('.', ',')} s.", ""]
    return "\n".join(lin)


if __name__ == "__main__":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    main()
