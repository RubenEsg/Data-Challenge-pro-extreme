"""Monitoreo del modelo (§9.4, RF-018 «evaluar periódicamente», ALT-010, §18 «Deriva») y foto de variables (§11.2).

En cada ejecución de frecuencia con datos nuevos se guarda una fila en ai_frecuencias.model_monitoring con:
- error móvil: WAPE, MAE y sesgo del modelo activo en los últimos `monitoreo_ventana_dias` días observados (28);
- cobertura de la banda P10-P90 calibrada (conformal) en esa ventana;
- deriva de datos: PSI de 10 bins de las variables principales, del objetivo y de la predicción frente a la
  referencia del modelo (los 365 días de entrenamiento anteriores a su corte; manifest['referencia_psi'] o, en los
  modelos que no la traen, calculada al vuelo con el mismo procedimiento);
- volumen de predicciones (de la ejecución y de la ventana) y porcentaje de alertas descartadas (alert_history);
- estado ok / aviso / alerta con sus motivos. El WAPE móvil por ruta alimenta ALT-010.

PSI = Σ (p_actual - p_ref) · ln(p_actual / p_ref), con los cortes de cuantiles de la referencia (proporciones
recortadas a 1e-4). Umbral efectivo por variable = max(umbral fijo, ruido propio): el ruido es el PSI de las ventanas
contiguas de 28 días DENTRO de la propia referencia (p50 para aviso, p95 para alerta). Así una variable diaria y
estacional no dispara falsas alarmas.

Investigación de dia_lag7 (docs/evidencias/monitoreo/psi_dia_lag7.json): su PSI frente al año de referencia va de
0,28 a 1,15 (sep-dic 2025), pero las ventanas contiguas de 28 días del MISMO año de entrenamiento ya dan p50 0,133 y
máximo 1,63, mientras 28 días tomados al azar dan 0,08. No es un error de datos: es una variable diaria (una por
ruta y día, repetida en las 17 horas), muy autocorrelacionada y estacional, que en 4 semanas solo ve una estación.
Por eso se reporta con su umbral calibrado, pero NO dispara el reentrenamiento (DISPARADORES_PSI).

La foto de variables (feature snapshot) guarda, por predicción y hora, el vector exacto que vio el modelo
(variables.matriz_x), con feature_version y data_cutoff, en la tabla particionada por mes
ai_frecuencias.feature_snapshot. Desde sv1 (§7.3 paso 4) guarda además, por predicción, una fila por segmento con
sentido y segmento llenos: las variables y el pronóstico del modelo de segmentos activo para la ventana
(app/servicios/modelo_segmentos.py, filas_foto). Si esas filas fallan, solo se omiten ellas: la foto de la ruta queda y
las métricas lo dicen en feature_snapshot_segmentos (FOTO_SEGMENTOS=false las apaga).
"""
from __future__ import annotations

import logging
import math
import time
from datetime import UTC, date, datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd

LOG = logging.getLogger("api_frecuencias.monitoreo")
BINS = 10
VENTANA_DIAS = 28
REFERENCIA_DIAS = 365
VARIABLES_PSI = ("lag7", "b8", "m4", "sd8", "nivel_7_34", "dia_lag7")
# dia_lag7 queda informativa (ver la investigación del docstring); el resto puede disparar el reentrenamiento
DISPARADORES_PSI = ("lag7", "b8", "m4", "sd8", "nivel_7_34", "objetivo", "prediccion")
UMBRALES_DEFECTO: dict[str, float] = {
    "psi_aviso": 0.10,
    "psi_alerta": 0.25,
    "cobertura_min": 0.70,
    "cobertura_aviso": 0.75,
    "cobertura_max": 0.90,
    "wape_aviso": 0.18,
    "wape_max": 0.20,
    "monitoreo_ventana_dias": 28,
    "descartadas_aviso": 0.50,
    "descartadas_minimo": 5,
}
PROP_MIN = 1e-4


# ----------------------------------------------------------------------------------------------- PSI
def referencia(valores, bins: int = BINS) -> dict:
    """Cortes de cuantiles (bins - 1 cortes únicos) y proporciones de la referencia."""
    v = np.asarray(valores, dtype=float)
    v = v[~np.isnan(v)]
    if len(v) == 0:
        return {"cortes": [], "proporciones": [1.0], "n": 0}
    cortes = np.unique(np.quantile(v, np.linspace(0, 1, bins + 1)[1:-1]))
    props = np.bincount(np.searchsorted(cortes, v, "right"), minlength=len(cortes) + 1) / len(v)
    return {"cortes": [float(c) for c in cortes], "proporciones": [float(p) for p in props], "n": int(len(v))}


def psi(ref: dict, valores) -> float | None:
    """PSI de `valores` frente a la referencia {cortes, proporciones}; None si no hay valores."""
    v = np.asarray(valores, dtype=float)
    v = v[~np.isnan(v)]
    if len(v) == 0 or not ref.get("proporciones"):
        return None
    cortes = np.asarray(ref["cortes"], dtype=float)
    pr = np.clip(np.asarray(ref["proporciones"], dtype=float), PROP_MIN, None)
    pc = np.bincount(np.searchsorted(cortes, v, "right"), minlength=len(cortes) + 1) / len(v)
    pc = np.clip(pc, PROP_MIN, None)
    return float(((pc - pr) * np.log(pc / pr)).sum())


def _columnas_psi(t: pd.DataFrame, pred: np.ndarray) -> dict[str, np.ndarray]:
    cols = {v: t[v].to_numpy(float) for v in VARIABLES_PSI if v in t.columns}
    cols["objetivo"] = t["pasajeros"].to_numpy(float)
    cols["prediccion"] = np.asarray(pred, dtype=float)
    return cols


def construir_referencia(t_ref: pd.DataFrame, pred_ref: np.ndarray, ventana_dias: int = VENTANA_DIAS) -> dict:
    """Referencia PSI por variable + ruido propio: PSI de cada ventana contigua de `ventana_dias` días de la propia
    referencia frente a la referencia completa (p50 y p95)."""
    cols = _columnas_psi(t_ref, pred_ref)
    fechas = pd.to_datetime(t_ref["fecha"]).to_numpy(dtype="datetime64[D]")
    out: dict[str, Any] = {"variables": {}, "desde": str(t_ref["fecha"].min()), "hasta": str(t_ref["fecha"].max()),
                           "filas": int(len(t_ref)), "bins": BINS, "ventana_ruido_dias": int(ventana_dias)}
    if len(t_ref) == 0:
        return out
    for nombre, v in cols.items():
        ref = referencia(v)
        ref.update(_resumen_ruido(_ruido_por_ventana(ref, v, fechas, ventana_dias)))
        out["variables"][nombre] = ref
    return out


def _ruido_por_ventana(ref: dict, v: np.ndarray, fechas: np.ndarray, ventana_dias: int) -> list[float]:
    """PSI de cada ventana contigua y completa de `ventana_dias` días de la referencia frente a la referencia entera."""
    ruido = []
    ini, fin = fechas.min(), fechas.max() + np.timedelta64(1, "D")
    k = 0
    while ini + np.timedelta64((k + 1) * ventana_dias, "D") <= fin:
        a = ini + np.timedelta64(k * ventana_dias, "D")
        m = (fechas >= a) & (fechas < a + np.timedelta64(ventana_dias, "D"))
        x = psi(ref, v[m]) if m.any() else None
        if x is not None:
            ruido.append(x)
        k += 1
    return ruido


def _resumen_ruido(ruido: list[float]) -> dict:
    if not ruido:
        return {"ruido_p50": 0.0, "ruido_p95": 0.0, "ruido_max": 0.0, "ventanas_ruido": 0}
    return {"ruido_p50": round(float(np.quantile(ruido, 0.5)), 4),
            "ruido_p95": round(float(np.quantile(ruido, 0.95)), 4),
            "ruido_max": round(float(max(ruido)), 4), "ventanas_ruido": len(ruido)}


def referencia_modelo(modelo: dict) -> dict:
    """manifest['referencia_psi'] o, si el modelo no la trae, los 365 días anteriores a su corte (una vez por
    modelo)."""
    from app.servicios import inferencia

    if "_referencia_psi" in modelo:
        return modelo["_referencia_psi"]
    man = modelo.get("manifiesto") or {}
    if man.get("referencia_psi", {}).get("variables"):
        ref = dict(man["referencia_psi"], origen="manifiesto")
    else:
        t = inferencia._filas_utiles(inferencia.tabla_variables())
        corte = modelo.get("data_cutoff") or t["fecha"].max()
        t_ref = t[(t["fecha"] > corte - timedelta(days=REFERENCIA_DIAS)) & (t["fecha"] <= corte)]
        pred_ref = inferencia._predecir_punto(modelo, t_ref) if len(t_ref) else np.zeros(0)
        ref = dict(construir_referencia(t_ref, pred_ref), origen="calculada al vuelo (el manifiesto no la trae)")
    modelo["_referencia_psi"] = ref
    return ref


def deriva(ref: dict, t: pd.DataFrame, pred: np.ndarray, umbrales: dict) -> dict:
    """PSI por variable con su umbral efectivo y su nivel (ok / aviso / alerta)."""
    cols = _columnas_psi(t, pred)
    aviso, alerta = float(umbrales["psi_aviso"]), float(umbrales["psi_alerta"])
    out = {}
    for nombre, v in cols.items():
        r = (ref.get("variables") or {}).get(nombre)
        if not r:
            continue
        x = psi(r, v)
        u_av = max(aviso, float(r.get("ruido_p50", 0.0)))
        u_al = max(alerta, float(r.get("ruido_p95", 0.0)))
        out[nombre] = {"psi": None if x is None else round(x, 4), "umbral_aviso": round(u_av, 4),
                       "umbral_alerta": round(u_al, 4), "nivel": _nivel_psi(x, u_av, u_al),
                       "dispara_reentreno": nombre in DISPARADORES_PSI}
    return out


def _nivel_psi(x: float | None, umbral_aviso: float, umbral_alerta: float) -> str:
    if x is None:
        return "sin_datos"
    if x > umbral_alerta:
        return "alerta"
    return "aviso" if x > umbral_aviso else "ok"


# ----------------------------------------------------------------------------------------------- cálculo
def _frac(x: float | None) -> float | None:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return None
    return float(x) / 100.0


def umbrales_monitoreo(umbrales: dict | None) -> dict:
    u = dict(UMBRALES_DEFECTO)
    for k, v in (umbrales or {}).items():
        try:
            u[k] = float(v)
        except (TypeError, ValueError):
            continue
    return u


def calcular(model_id: str | None, hasta: date, umbrales: dict | None = None, dir_modelos=None, *,
             sesion=None) -> dict:
    """Métricas de monitoreo del modelo en [hasta - ventana + 1, hasta]. Con `sesion` (o dentro de
    inferencia.con_sesion) el error, la cobertura y la deriva se miden sobre la serie validada (lo que llegó y pasó la
    calidad, encima del Parquet); sin sesión, sobre la serie empaquetada."""
    from app.servicios import inferencia

    if sesion is not None:
        with inferencia.con_sesion(sesion):
            return calcular(model_id, hasta, umbrales, dir_modelos)
    u = umbrales_monitoreo(umbrales)
    ventana = int(u["monitoreo_ventana_dias"])
    hasta = pd.Timestamp(hasta).date()
    desde = hasta - timedelta(days=ventana - 1)
    modelo = inferencia.cargar(model_id, dir_modelos)
    tabla = inferencia.tabla_variables()
    base = {"model_id": modelo["model_id"], "desde": desde, "hasta": hasta, "ventana_dias": ventana,
            "origen_datos": tabla.attrs.get("origen")}
    t = inferencia._filas_utiles(tabla)
    t = t[(t["fecha"] >= desde) & (t["fecha"] <= hasta)]
    if t.empty:
        return dict(base, estado="sin_datos", motivos=["no hay datos observados en la ventana"], n_observaciones=0,
                    psi={}, wape_por_ruta={})
    ev = inferencia.evaluar(modelo["model_id"], desde, hasta, dir_modelos)
    pred = inferencia._predecir_punto(modelo, t)
    ref = referencia_modelo(modelo)
    psi_vars = deriva(ref, t, pred, u)
    cobertura = _frac(ev.get("cobertura_p10_p90_conformal", ev.get("cobertura_p10_p90")))
    wape_por_ruta = {r: _frac(m.get("wape")) for r, m in (ev.get("por_ruta") or {}).items()
                     if m.get("wape") is not None}
    out = dict(
        base,
        n_observaciones=int(len(t)),
        wape_movil=_frac(ev.get("wape")),
        mae_movil=ev.get("mae"),
        sesgo_pct=_frac(ev.get("sesgo_pct")),
        cobertura_p10_p90=cobertura,
        calibracion_version=ev.get("calibracion_version"),
        cobertura_modelo=_frac(ev.get("cobertura_p10_p90")),
        wape_por_ruta=wape_por_ruta,
        psi=psi_vars,
        referencia_psi={"origen": ref.get("origen"), "desde": ref.get("desde"), "hasta": ref.get("hasta"),
                        "filas": ref.get("filas")},
        fuera_de_muestra=ev.get("fuera_de_muestra"),
    )
    disp = {k: v for k, v in psi_vars.items() if v["dispara_reentreno"] and v["psi"] is not None}
    if disp:
        k_max = max(disp, key=lambda k: disp[k]["psi"])
        out["psi_max"], out["psi_variable_max"] = disp[k_max]["psi"], k_max
    else:
        out["psi_max"], out["psi_variable_max"] = None, None
    return out


def estado_de(m: dict, umbrales: dict | None = None) -> tuple[str, list[str]]:
    """ok / aviso / alerta con los motivos (orden: error, cobertura, deriva, alertas descartadas)."""
    if m.get("estado") == "sin_datos":
        return "sin_datos", list(m.get("motivos") or [])
    u = umbrales_monitoreo(umbrales)
    alerta: list[str] = []
    aviso: list[str] = []
    partes = (_motivos_wape(m.get("wape_movil"), u), _motivos_cobertura(m.get("cobertura_p10_p90"), u),
              _motivos_deriva(m.get("psi") or {}), _motivos_descartadas(m, u))
    for de_alerta, de_aviso in partes:
        alerta += de_alerta
        aviso += de_aviso
    if alerta:
        return "alerta", alerta + aviso
    return ("aviso", aviso) if aviso else ("ok", [])


def _motivos_wape(w: float | None, u: dict) -> tuple[list[str], list[str]]:
    """(motivos de alerta, motivos de aviso) por el WAPE móvil."""
    if w is not None and w > u["wape_max"]:
        return [f"WAPE móvil {w:.1%} > wape_max {u['wape_max']:.1%} (ALT-010)"], []
    if w is not None and w > u["wape_aviso"]:
        return [], [f"WAPE móvil {w:.1%} > wape_aviso {u['wape_aviso']:.1%}"]
    return [], []


def _motivos_cobertura(c: float | None, u: dict) -> tuple[list[str], list[str]]:
    """(motivos de alerta, motivos de aviso) por la cobertura P10-P90 calibrada."""
    if c is None:
        return [], []
    if c < u["cobertura_min"]:
        return [f"cobertura P10-P90 {c:.1%} < cobertura_min {u['cobertura_min']:.0%}"], []
    if c < u["cobertura_aviso"]:
        return [], [f"cobertura P10-P90 {c:.1%} < cobertura_aviso {u['cobertura_aviso']:.0%}"]
    if c > u["cobertura_max"]:
        return [], [f"cobertura P10-P90 {c:.1%} > cobertura_max {u['cobertura_max']:.0%} (banda muy ancha)"]
    return [], []


def _motivos_deriva(psi_vars: dict) -> tuple[list[str], list[str]]:
    """(motivos de alerta, motivos de aviso) por la deriva de las variables que disparan el reentrenamiento."""
    alerta, aviso = [], []
    for nombre, d in psi_vars.items():
        if not d.get("dispara_reentreno"):
            continue
        if d["nivel"] == "alerta":
            alerta.append(f"deriva en {nombre}: PSI {d['psi']:.3f} > {d['umbral_alerta']:.3f}")
        elif d["nivel"] == "aviso":
            aviso.append(f"deriva leve en {nombre}: PSI {d['psi']:.3f} > {d['umbral_aviso']:.3f}")
    return alerta, aviso


def _motivos_descartadas(m: dict, u: dict) -> tuple[list[str], list[str]]:
    """Aviso si muchas alertas de la ventana terminaron descartadas (posibles falsos positivos)."""
    pct, tot = m.get("pct_descartadas"), m.get("alertas_total") or 0
    if pct is not None and tot >= u["descartadas_minimo"] and pct > u["descartadas_aviso"]:
        return [], [f"{pct:.0%} de las alertas de la ventana fueron descartadas (posibles falsos positivos)"]
    return [], []


# ----------------------------------------------------------------------------------------------- base de datos
def alertas_descartadas(s, desde: datetime) -> dict:
    """Alertas creadas desde `desde` y cuántas terminaron descartadas (transiciones de alert_history)."""
    from sqlalchemy import func, select

    from app.modelos_db import Alerta, HistorialAlerta

    total = s.scalar(select(func.count()).select_from(Alerta).where(Alerta.creado_en >= desde)) or 0
    filas = s.execute(
        select(Alerta.codigo, func.count(func.distinct(HistorialAlerta.alert_id)))
        .join(HistorialAlerta, HistorialAlerta.alert_id == Alerta.alert_id)
        .where(Alerta.creado_en >= desde, HistorialAlerta.estado_nuevo == "descartada")
        .group_by(Alerta.codigo)).all()
    por_codigo = {c: int(n) for c, n in filas}
    desc = sum(por_codigo.values())
    return {"alertas_total": int(total), "alertas_descartadas": int(desc),
            "pct_descartadas": (desc / total) if total else None, "descartadas_por_codigo": por_codigo}


def _volumen_ventana(s, desde: date, hasta: date) -> int:
    from sqlalchemy import func, select

    from app.modelos_db import Prediccion

    return int(s.scalar(select(func.count()).select_from(Prediccion)
                        .where(Prediccion.fecha >= desde, Prediccion.fecha <= hasta + timedelta(days=1))) or 0)


def registrar(s, *, execution_id, model_id: str | None, hasta: date, umbrales: dict | None,
              umbrales_version: int | None, rol: str = "activo", n_predicciones: int | None = None):
    """Calcula y guarda la fila de monitoreo (en la transacción de `s`). Devuelve (fila ORM, dict de métricas)."""
    from app.modelos_db import MonitoreoModelo
    from app.servicios.ejecucion import json_seguro

    m = calcular(model_id, hasta, umbrales, sesion=s)   # sobre lo validado de la base, también lo de este ciclo
    m.update(alertas_descartadas(s, datetime.now(UTC) - timedelta(days=int(m["ventana_dias"]))))
    m["predicciones_ventana"] = _volumen_ventana(s, m["desde"], m["hasta"])
    estado, motivos = estado_de(m, umbrales)
    m["estado"], m["motivos"] = estado, motivos
    fila = MonitoreoModelo(
        execution_id=execution_id, model_id=m["model_id"], rol=rol, fecha_corte=m["hasta"], desde=m["desde"],
        hasta=m["hasta"], ventana_dias=m["ventana_dias"], n_observaciones=m.get("n_observaciones"),
        n_predicciones=n_predicciones, predicciones_ventana=m["predicciones_ventana"],
        wape_movil=m.get("wape_movil"), mae_movil=m.get("mae_movil"), sesgo_pct=m.get("sesgo_pct"),
        cobertura_p10_p90=m.get("cobertura_p10_p90"), psi=json_seguro(m.get("psi") or {}),
        psi_max=m.get("psi_max"), psi_variable_max=m.get("psi_variable_max"),
        alertas_total=m["alertas_total"], alertas_descartadas=m["alertas_descartadas"],
        pct_descartadas=m["pct_descartadas"], estado=estado, motivos=json_seguro(motivos),
        umbrales_version=umbrales_version,
        detalle=json_seguro({"wape_por_ruta": m.get("wape_por_ruta"), "referencia_psi": m.get("referencia_psi"),
                             "cobertura_modelo": m.get("cobertura_modelo"),
                             "descartadas_por_codigo": m.get("descartadas_por_codigo"),
                             "fuera_de_muestra": m.get("fuera_de_muestra"), "origen_datos": m.get("origen_datos")}))
    s.add(fila)
    s.flush()
    return fila, m


def en_ciclo(s, execution_id, model_id: str | None, validos, umbrales: dict, umbrales_version: int | None,
             fallos: list, *, hasta: date | None = None) -> dict:
    """Paso de monitoreo del ciclo diario (antes de predecir, para que ALT-010 use el WAPE móvil por ruta).

    Guarda la fila del modelo activo y la de cada retador en sombra. Nunca detiene el ciclo: un fallo queda en
    `fallos` y el ciclo sigue (la evaluación del error sobre lo nuevo ya quedó en las métricas). La ventana termina en
    el último día de `validos` o en `hasta` (la ejecución madre de una ejecución partida por ruta, RNF-005).
    """
    if hasta is None:
        if validos is None or len(validos) == 0:
            return {}
        hasta = max(validos["fecha"])
    if not model_id:
        return {}
    try:
        with s.begin_nested():
            fila, m = registrar(s, execution_id=execution_id, model_id=model_id, hasta=hasta, umbrales=umbrales,
                                umbrales_version=umbrales_version)
    except Exception as exc:  # noqa: BLE001
        LOG.warning("monitoreo no disponible: %s", exc, exc_info=True)
        fallos.append({"etapa": "monitoreo", "error": str(exc)})
        return {}
    sombras = []
    from app.servicios import politica

    for cand in politica.en_sombra(s):
        try:
            with s.begin_nested():
                f_s, m_s = registrar(s, execution_id=execution_id, model_id=cand.model_id, hasta=hasta,
                                     umbrales=umbrales, umbrales_version=umbrales_version, rol="sombra")
            sombras.append({"model_id": cand.model_id, "id": f_s.id, "estado": m_s["estado"],
                            "wape_movil": m_s.get("wape_movil")})
        except Exception as exc:  # noqa: BLE001
            fallos.append({"etapa": "monitoreo_sombra", "model_id": cand.model_id, "error": str(exc)})
    return {"id": fila.id, "estado": m["estado"], "motivos": m["motivos"], "wape_movil": m.get("wape_movil"),
            "cobertura_p10_p90": m.get("cobertura_p10_p90"), "psi_max": m.get("psi_max"),
            "psi_variable_max": m.get("psi_variable_max"), "wape_por_ruta": m.get("wape_por_ruta") or {},
            "hasta": hasta, "sombra": sombras}


def en_ciclo_de_ruta(s, model_id: str | None, validos, umbrales: dict, fallos: list, ruta: str) -> dict:
    """El trabajo de UNA ruta de una ejecución partida (RNF-005): el WAPE móvil de SU ruta para ALT-010, con la misma
    ventana y la misma serie validada que calcular() (la métrica de una ruta no depende de las demás), SIN guardar la
    fila de monitoreo ni la del retador: la ejecución madre las guarda una vez por ejecución, así «las últimas n
    ejecuciones» de la política siguen siendo días y no rutas."""
    from app.servicios import inferencia

    if validos is None or len(validos) == 0 or not model_id:
        return {}
    u = umbrales_monitoreo(umbrales)
    hasta = pd.Timestamp(max(validos["fecha"])).date()
    desde = hasta - timedelta(days=int(u["monitoreo_ventana_dias"]) - 1)
    base = {"ruta": ruta, "desde": desde, "hasta": hasta, "sombra": [], "fila_guardada": False}
    try:
        with s.begin_nested():
            ev = inferencia.evaluar(model_id, desde, hasta, sesion=s, rutas=[ruta])
    except ValueError:      # sin datos observados de la ruta en la ventana (calcular: «sin_datos»)
        return dict(base, estado="sin_datos", wape_por_ruta={})
    except Exception as exc:  # noqa: BLE001 - sin monitoreo ALT-010 no se evalúa; el trabajo sigue
        LOG.warning("monitoreo del trabajo de ruta no disponible: %s", exc, exc_info=True)
        fallos.append({"etapa": "monitoreo", "ruta": ruta, "error": str(exc)})
        return {}
    wape = _frac(((ev.get("por_ruta") or {}).get(ruta) or {}).get("wape"))
    return dict(base, wape_movil_ruta=wape, wape_por_ruta={} if wape is None else {ruta: wape})


# ----------------------------------------------------------------------------------------------- foto de variables
def filas_snapshot(prediccion) -> list[dict]:
    """Vector de variables de cada hora de la ventana de la predicción (el mismo que vio el modelo)."""
    from app.servicios import inferencia, variables

    modelo = inferencia.cargar(prediccion.model_id)
    version = inferencia._version_modelo(modelo)
    tabla = inferencia.tabla_variables()
    inicio = prediccion.instante
    fin = inicio + timedelta(minutes=int(prediccion.horizonte_min))
    inst = inferencia._a_bogota(inicio)
    tramos = inferencia._tramos(inst, inferencia._a_bogota(fin), prediccion.ruta, tabla)
    filas = inferencia._filas_variables(tabla, prediccion.ruta, tramos)
    if len(filas) == 0:
        return []
    x = variables.matriz_x(filas, version)
    fr = {(f, h): fr for f, h, fr in tramos}
    out = []
    for (_, r), (_, xr) in zip(filas.iterrows(), x.iterrows(), strict=False):
        feats = {c: (None if pd.isna(v) else float(v)) for c, v in xr.items()}
        feats["_fraccion_ventana"] = round(float(fr.get((r["fecha"], int(r["hora"])), 0.0)), 4)
        out.append({"fecha": r["fecha"], "hora": int(r["hora"]), "features": feats, "feature_version": version})
    return out


CAMPOS_DIMENSIONES = ("idruta", "idempresa", "idproceso", "id_dia_semana", "id_estacionalidad")


def dimensiones_foto(ruta: str, fecha) -> dict:
    """Dimensiones de §8.3 de una fila de la foto (app/servicios/dimensiones.py); {} si el módulo o el modelo de la
    tabla todavía no las tienen (la foto se guarda igual, sin ellas)."""
    from app.modelos_db import FotoVariables

    if not all(hasattr(FotoVariables, c) for c in CAMPOS_DIMENSIONES):
        return {}
    try:
        from app.servicios import dimensiones
    except ImportError:
        return {}
    d = dimensiones.dimensiones(ruta, fecha)
    return {c: d.get(c) for c in CAMPOS_DIMENSIONES}


def _inicio_foto_segmentos(segmentos: dict | None) -> tuple[dict, dict | None]:
    """(estado de la foto por segmento, modelo de segmentos activo o None)."""
    seg = {} if segmentos is None else segmentos
    seg.update(estado="ok", filas=0)
    return seg, _modelo_foto_segmentos(seg)


def _modelo_foto_segmentos(estado: dict):
    """Modelo de segmentos activo para la foto, o None (apagada por FOTO_SEGMENTOS o sin modelo: queda en estado).

    Se llama fuera del punto de guardado de la foto: cualquier error al cargar el modelo (registro o manifiesto que no
    son JSON válido, artefacto que no se puede deserializar) solo omite las filas por segmento, nunca el ciclo."""
    from app.config import obtener_ajustes
    from app.servicios import modelo_segmentos

    if not obtener_ajustes().foto_segmentos:
        estado["estado"] = "apagada"
        return None
    try:
        modelo = modelo_segmentos.cargar()
    except Exception as exc:  # noqa: BLE001 - la foto por segmento no debe tumbar el ciclo (§14.2)
        estado.update(estado="omitida", avisos=[f"sin modelo de segmentos: {exc}"[:300]])
        return None
    estado["model_id"] = modelo["model_id"]
    return modelo


def _foto_segmentos(s, p, execution_id, data_cutoff, modelo: dict | None, tabla, estado: dict) -> int:
    """Filas por segmento y sentido de la predicción `p` (§7.3 paso 4). Un fallo, al calcularlas o al escribirlas,
    omite solo estas filas y queda en estado["avisos"]; la foto de la ruta no se toca: sus filas se envían antes y las
    de los segmentos van en su propio punto de guardado."""
    from sqlalchemy import insert
    from sqlalchemy.exc import SQLAlchemyError

    from app.modelos_db import FotoVariables
    from app.servicios import modelo_segmentos

    if modelo is None:
        return 0
    try:
        valores = _valores_foto_segmentos(p, execution_id, data_cutoff, modelo_segmentos.filas_foto(p, tabla, modelo))
    except Exception as exc:  # noqa: BLE001 - la foto por segmento no debe tumbar la de la ruta
        return _fallo_foto_segmentos(p, exc, estado)
    if not valores:
        return 0
    s.flush()      # las filas de la ruta de esta predicción quedan fuera del punto de guardado de los segmentos
    try:
        with s.begin_nested():
            s.execute(insert(FotoVariables), valores)
    except SQLAlchemyError as exc:
        return _fallo_foto_segmentos(p, exc, estado)
    return len(valores)


def _valores_foto_segmentos(p, execution_id, data_cutoff, filas: list[dict]) -> list[dict]:
    """Filas de feature_snapshot (con las dimensiones de §8.3) de las variables por segmento de la predicción `p`."""
    from app.servicios.ejecucion import json_seguro

    if not filas:
        return []
    dims = dimensiones_foto(p.ruta, filas[0]["fecha"])
    return [{"execution_id": execution_id, "prediction_id": p.prediction_id, "model_id": f["model_id"], "ruta": p.ruta,
             "sentido": f["sentido"], "segmento": f["segmento"], "horizonte_min": p.horizonte_min,
             "ventana_inicio": p.instante, "ventana_fin": p.objetivo, "fecha": f["fecha"], "hora": f["hora"],
             "features": json_seguro(f["features"]), "feature_version": f["feature_version"],
             "data_cutoff": data_cutoff, **dims} for f in filas]


def _fallo_foto_segmentos(p, exc: Exception, estado: dict) -> int:
    """Registra que no quedaron las filas por segmento de `p` (aviso en las métricas de la ejecución); devuelve 0."""
    LOG.warning("foto por segmento no guardada (%s, %s min): %s", p.ruta, p.horizonte_min, exc, exc_info=True)
    estado["estado"] = "fallo"
    estado.setdefault("avisos", []).append(f"{p.ruta} {p.horizonte_min} min: {exc}"[:300])
    return 0


ESPERA_LOCK_PARTICION = "500ms"      # menor que deadlock_timeout (1 s): cede antes de que PostgreSQL aborte a nadie


def asegurar_particion_previa(instante: datetime, espera_s: float = 30.0) -> bool:
    """RNF-005: crea (si falta) la partición mensual de feature_snapshot del instante de las predicciones en una
    transacción CORTA y propia, ANTES de que el trabajo escriba predicciones. Crear una partición clona las llaves
    foráneas de feature_snapshot y pide ShareRowExclusiveLock sobre prediction y execution_log: dentro de la
    transacción larga de un trabajo, con el trabajo de otra ruta escribiendo a la vez, eso es un interbloqueo. Aquí
    espera como mucho ESPERA_LOCK_PARTICION por intento (menos que deadlock_timeout: si un trabajo vecino tiene
    predicciones sin confirmar, cede sin que PostgreSQL aborte a nadie) y reintenta hasta `espera_s`. True si la
    partición existe al terminar; si no, guardar_snapshot la intenta crear dentro del ciclo, como antes."""
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    from app.db import motor

    inicio = instante.astimezone(UTC)
    nombre = f"ai_frecuencias.feature_snapshot_{inicio:%Y%m}"
    limite = time.monotonic() + espera_s
    while True:
        try:
            with motor().connect() as conexion:
                if conexion.execute(text("SELECT to_regclass(:n)"), {"n": nombre}).scalar() is not None:
                    return True
                conexion.execute(text(f"SET LOCAL lock_timeout = '{ESPERA_LOCK_PARTICION}'"))   # constante
                conexion.execute(text("SELECT ai_frecuencias.asegurar_particion_feature_snapshot(:t)"),
                                 {"t": inicio})
                conexion.commit()
                return True
        except DBAPIError as exc:     # candado ocupado (55P03) o carrera con otra réplica: se reintenta
            if time.monotonic() >= limite:
                LOG.warning("partición %s no creada antes del ciclo: %s", nombre, str(exc).splitlines()[0])
                return False
            time.sleep(0.3)


def guardar_snapshot(s, execution_id, data_cutoff, fallos: list | None = None,
                     advertencias: list | None = None, segmentos: dict | None = None) -> int:
    """Escribe la foto de variables de todas las predicciones de la ejecución (§11.2), con las dimensiones de §8.3 y
    las variables de la serie validada de `s` (las mismas que vio el modelo), más una fila por segmento y sentido de
    cada predicción (§7.3 paso 4; su conteo y su estado van en `segmentos`). Va en un punto de guardado: si falla, se
    deshace solo la foto, el ciclo sigue y el fallo queda en `fallos` y en `advertencias` (métricas de la ejecución).
    Devuelve las filas escritas (ruta y segmento)."""
    from sqlalchemy import select, text

    from app.modelos_db import FotoVariables, Prediccion
    from app.servicios import inferencia
    from app.servicios.ejecucion import json_seguro

    preds = s.scalars(select(Prediccion).where(Prediccion.execution_id == execution_id)).all()
    n = 0
    seg, modelo_seg = _inicio_foto_segmentos(segmentos)
    try:
        with s.begin_nested(), inferencia.con_sesion(s):
            meses = set()
            tabla_seg = inferencia.tabla_variables()
            for p in preds:
                inicio = p.instante.astimezone(UTC)
                mes = inicio.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
                if mes not in meses:
                    s.execute(text("SELECT ai_frecuencias.asegurar_particion_feature_snapshot(:t)"), {"t": inicio})
                    meses.add(mes)
                for f in filas_snapshot(p):
                    s.add(FotoVariables(
                        execution_id=execution_id, prediction_id=p.prediction_id, model_id=p.model_id, ruta=p.ruta,
                        sentido=None, segmento=None, horizonte_min=p.horizonte_min, ventana_inicio=p.instante,
                        ventana_fin=p.objetivo, fecha=f["fecha"], hora=f["hora"],
                        features=json_seguro(f["features"]), feature_version=f["feature_version"] or "",
                        data_cutoff=data_cutoff, **dimensiones_foto(p.ruta, f["fecha"])))
                    n += 1
                k = _foto_segmentos(s, p, execution_id, data_cutoff, modelo_seg, tabla_seg, seg)
                seg["filas"] += k
                n += k
            s.flush()
    except Exception as exc:  # noqa: BLE001 - la foto no debe tumbar el ciclo; queda como fallo parcial
        LOG.warning("feature snapshot no guardado: %s", exc, exc_info=True)
        if fallos is not None:
            fallos.append({"etapa": "feature_snapshot", "error": str(exc)})
        if advertencias is not None:
            advertencias.append(f"foto de variables (§11.2) no guardada: {exc}"[:500])
        seg.update(estado="fallo", filas=0)
        return 0
    return n


def foto_del_ciclo(s, execution_id, data_cutoff, predicciones: int, fallos: list) -> dict[str, Any]:
    """Filas de la foto de variables de las predicciones de la ejecución, con las de cada segmento y sentido (§7.3
    paso 4; su conteo y su estado van en feature_snapshot_segmentos) y, si no quedó, la advertencia: la ejecución
    termina «ok», pero sus métricas dicen que la foto no se guardó. En una ejecución partida (RNF-005) la llama cada
    trabajo de ruta con SUS predicciones, así que cada fila (de la ruta o de un segmento) se escribe una sola vez."""
    advertencias: list[str] = []
    segmentos: dict[str, Any] = {}
    out: dict[str, Any] = {"feature_snapshot_filas": (guardar_snapshot(s, execution_id, data_cutoff, fallos,
                                                                       advertencias, segmentos) if predicciones else 0)}
    if segmentos:   # §7.3 paso 4: filas por segmento y sentido (incluidas en feature_snapshot_filas)
        out["feature_snapshot_segmentos"] = segmentos
    if advertencias:
        out.update(advertencias=advertencias, feature_snapshot_estado="fallo")
    return out


def cerrar_ciclo(s, execution_id, data_cutoff, predicciones: int, monitoreo: dict, umbrales: dict,
                 umbrales_version: int | None, fallos: list, *, ejecuciones: list | None = None,
                 foto: bool = True) -> dict:
    """Al final del ciclo (misma transacción que los resultados): foto de variables, volumen de predicciones de la
    ejecución, predicciones del retador en sombra y decisiones de la política (reentreno, compuerta, reversión).

    La madre de una ejecución partida (RNF-005) pasa `ejecuciones` (sus trabajos por ruta: el retador predice lo que
    predijeron ellos) y foto=False (cada trabajo ya guardó la foto de sus predicciones)."""
    from app.modelos_db import MonitoreoModelo
    from app.servicios import politica

    out: dict[str, Any] = {k: v for k, v in (monitoreo or {}).items() if k != "wape_por_ruta"}
    out.update(foto_del_ciclo(s, execution_id, data_cutoff, predicciones if foto else 0, fallos))
    if monitoreo.get("id"):
        fila = s.get(MonitoreoModelo, monitoreo["id"])
        if fila is not None:
            fila.n_predicciones = int(predicciones)
            s.flush()
            fila.predicciones_ventana = _volumen_ventana(s, fila.desde, fila.hasta)  # ya con las de esta ejecución
    for sm in monitoreo.get("sombra") or []:
        try:
            with s.begin_nested():
                politica.predecir_en_sombra(s, execution_id, sm, ejecuciones=ejecuciones)
        except Exception as exc:  # noqa: BLE001
            fallos.append({"etapa": "prediccion_sombra", "model_id": sm.get("model_id"), "error": str(exc)})
    if monitoreo.get("hasta") is not None:
        try:
            with s.begin_nested():
                out["politica"] = politica.despues_del_ciclo(s, execution_id, monitoreo, umbrales, umbrales_version)
        except Exception as exc:  # noqa: BLE001
            LOG.warning("política de aprendizaje continuo no aplicada: %s", exc, exc_info=True)
            fallos.append({"etapa": "politica", "error": str(exc)})
    return out
