"""Modelos de demanda: entrenamiento, registro, carga verificada, predicción y evaluación (especificación §9).

- Línea base (§9.1): B1 = regla manual (media de la misma hora y día de la semana de las 8 semanas anteriores) y
  B2 = última semana (misma hora hace 7 días). No tienen artefacto: se calculan con las variables b8 y lag7.
- Candidato tabular: HistGradientBoostingRegressor (pérdida Poisson) + dos modelos de cuantiles (P10 y P90, RF-006).
- División cronológica (§9.3): entrenamiento <= hasta, validación los 61 días siguientes, prueba el resto.
- Artefactos: datos/modelos/<model_id>/modelo.joblib + manifest.json (sha256, feature_version, data_cutoff, métricas,
  semilla, hiperparámetros, filas). cargar() lee el artefacto UNA vez y verifica el hash (§9.2).
- predecir(): pronóstico horario repartido en [instante, instante + horizonte] con el perfil intrahorario (fracción de
  subidas en la primera media hora, datos/perfil_intrahorario.parquet; 0,5 si falta), ajustado con un factor intradía
  calculado con observado / esperado en las 2 h previas (recortado a 0,8-1,25), usando solo horas cerradas.
- Banda v1 (respaldo, CALIBRACION_BANDA=v1, y la de los modelos sin calibración versionada): conformal móvil (CQR)
  por ruta: puntaje s = max(lo - y, y - hi) / max(p, 1) en los 56 días previos al día del pronóstico, solo días fuera
  de muestra (posteriores al corte del modelo); q = cuantil de nivel ceil((n + 1) * 0,8) / n; lo' = max(0, lo - q p),
  hi' = hi + q p. Con menos de 14 días queda sin ajustar. Se devuelven la banda calibrada (p10/p90), la del modelo
  (p10_modelo/p90_modelo) y el ajuste (q).
- Calibración versionada por grupo (v2, la vigente del modelo activo): si el manifiesto trae la clave «calibracion»,
  se lee su archivo (SHA-256
  verificado) con un cuantil conformal por bloque horario ajustado solo con la validación
  (scripts/calibrar_por_grupo.py) y se aplica después del modelo, igual con sklearn u ONNX. Cada predicción dice qué
  versión produjo su banda (calibracion_version); CALIBRACION_BANDA=v1 vuelve al conformal móvil por ruta.
  entrenar() ajusta esa misma calibración con la validación de CADA modelo nuevo (ajustar_calibracion_grupo y
  escribir_calibracion, las funciones que usa el script), así que la sombra y la compuerta comparan al candidato y al
  activo con el mismo tipo de banda.
- Varias versiones de variables (variables.VERSIONES): cargar() acepta cualquier versión registrada, así que volver a
  un modelo fv1 sigue funcionando con el código fv2 (RF-019).
- Explicación local (RF-015): en modelos sin variables categóricas (fv2) se calcula SHAP TreeExplainer (exacto en la
  escala log del modelo Poisson): base x producto de factores = pronóstico de la hora. En fv1 se usa la importancia
  por permutación del manifiesto.
- Datos recientes (RF-013, §9.5): con una sesión de la base de resultados (argumento `sesion` o el bloque
  `with con_sesion(s):`), tabla_variables() arma las variables y los valores reales con politica.serie_validada: la
  serie empaquetada con las horas VALIDADAS de demanda_observada encima. Solo se recalculan los días tocados por lo
  nuevo y los 56 días siguientes (los rezagos llegan hasta 8 semanas), con caché por la huella del histórico. Así un
  día validado nuevo actualiza las variables y se puede pronosticar, evaluar, monitorear y pasar la compuerta después
  del fin del Parquet. Sin sesión (scripts de evidencia y pruebas unitarias) se usa solo la serie empaquetada;
  INFERENCIA_SERIE=validada hace que el proceso abra su propia sesión (solo ve lo ya confirmado).
- predecir_horas(): el mismo pronóstico de predecir() para varias horas de una ruta en un solo lote (una llamada a
  los tres modelos y a SHAP); devuelve los mismos diccionarios, hora por hora.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import subprocess  # nosec B404
import threading
import time
from collections import OrderedDict
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, date, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.inspection import permutation_importance

from . import datos, variables

ZONA = ZoneInfo("America/Bogota")
LOG = logging.getLogger("api_frecuencias.inferencia")
HORIZONTES = (30, 60, 120)
NOWCAST_MIN, NOWCAST_MAX = 0.8, 1.25
NOWCAST_VENTANA_H = 2
NOWCAST_MIN_ESPERADOS = 50.0  # con menos pasajeros esperados en las 2 h previas el factor queda en 1
# factor = clip(1 + peso * (observado / esperado - 1), 0,8, 1,25). El peso se calibra en la validación de cada modelo
# (entrenar); con la razón sin encoger (peso 1) el error sube, como ya advertía sistema_tiempo_real/nowcast.py.
NOWCAST_PESO_DEFECTO = 0.1
NOWCAST_PESOS = (0.0, 0.1, 0.2, 0.3, 0.5, 1.0)
DIAS_VALIDACION = 61
CONFORMAL_VENTANA_DIAS = 56
CONFORMAL_MIN_DIAS = 14
COBERTURA_OBJETIVO = 0.80
FRANJAS = (("04-05", 4, 5), ("06-08 pico", 6, 8), ("09-16 valle", 9, 16), ("17-19 pico", 17, 19), ("20", 20, 20))
SHAP_FILAS_GLOBAL = 1000
DESCRIPCION_VARIABLE = {
    "b8": "la media de 8 semanas (regla manual)",
    "m4": "la media de 4 semanas",
    "lag7": "la misma hora hace 7 días",
    "lag14": "la misma hora hace 14 días",
    "sd8": "la variabilidad de 8 semanas",
    "nivel_7_13": "el nivel de la semana anterior",
    "nivel_7_34": "el nivel de las 4 semanas anteriores",
    "dia_lag7": "el total del día hace 7 días",
    "hora": "la hora",
    "dia_semana": "el día de la semana",
    "mes": "el mes",
    "ruta_cod": "la ruta",
    "tipo_dia": "el tipo de día",
    "festivo": "el festivo",
    "carnaval": "el Carnaval",
    "semana_santa": "la Semana Santa",
    "vacaciones": "las vacaciones",
    "navidad": "la Navidad",
    "primero_enero": "el 1 de enero",
    "nov_impacto": "la novedad vial (% de impacto)",
    "nov_sube": "la novedad marcada SUBE",
    "vispera_festivo": "la víspera de festivo",
    "post_festivo": "el día posterior a festivo",
}
LEARNING_RATE_SKLEARN = 0.1   # valor por defecto de HistGradientBoostingRegressor
HIPER_DEFECTO = {
    "learning_rate": 0.05,
    "max_iter": 400,
    "max_leaf_nodes": 31,
    "min_samples_leaf": 40,
    "l2_regularization": 1.0,
}
LINEAS_BASE = {
    "b1_manual_8sem": {
        "variable": "b8",
        "descripcion": "Regla manual de Sobusa: media de la misma hora y el mismo día "
        "de la semana de las 8 semanas anteriores",
    },
    "b2_ultima_semana": {"variable": "lag7", "descripcion": "Última semana: pasajeros de la misma hora hace 7 días"},
}
REFERENCIAS_PROYECTO = [
    {
        "model_id": "ref_B1_regla_manual",
        "wape_pct": 20.04,
        "fuente": "app/DATOS.md (C1); experimentos/E11_modelo_mejorado/resultados.json",
    },
    {"model_id": "ref_E1_lightgbm", "wape_pct": 14.40, "fuente": "experimentos/E1_lgbm_salida/README.md"},
    {
        "model_id": "ref_experimento11_lightgbm",
        "wape_pct": 13.94,
        "fuente": "app/DATOS.md (C1); experimentos/E11_modelo_mejorado (experimento 11 del informe académico)",
    },
    {
        "model_id": "ref_experimento12_hibrido",
        "wape_pct": 13.62,
        "fuente": "app/DATOS.md (C1, C18); experimentos/E12_comparacion_modelos (experimento 12 del informe académico)",
    },
]
NOTA_REFERENCIAS = (
    "Modelos del informe académico (WAPE horario de todo 2025 con horizonte de una semana y validación mensual "
    "expansiva). Se registran como referencia y no se ejecutan dentro de la API; no se comparan número a número con "
    "el modelo de la API (hgb_fv2_20250831_s42, un solo corte y prueba de nov-dic 2025), porque el protocolo es otro."
)
DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
ARCHIVO_MANIFIESTO = "manifest.json"
ARCHIVO_PERFIL = "perfil_intrahorario.parquet"
ARCHIVO_CALIBRACION = "calibracion_v2.json"
# esquema de la calibración versionada (v2): un cuantil conformal por bloque horario, con al menos 30 puntajes por
# grupo (con menos se usa el cuantil global «*»); es el que adoptó scripts/calibrar_por_grupo.py para el activo
CALIBRACION_GRUPOS_DEFECTO = ("bloque",)
CALIBRACION_MIN_GRUPO = 30
CALIBRACION_PUNTAJE = "s = max(P10 - y, y - P90) / max(P50, 1)"
CALIBRACION_APLICACION = "P10' = max(0, min(P10 - q·max(P50, 1), P50)); P90' = max(P90 + q·max(P50, 1), P50)"


class ErrorIntegridadModelo(RuntimeError):
    """El sha256 del artefacto no coincide con el del manifiesto."""


class ModeloNoEncontrado(LookupError):
    """No existe el modelo pedido."""


_CACHE_MODELOS: dict[str, dict] = {}
_CANDADO = threading.Lock()
_CANDADO_AUX = threading.Lock()  # explicador SHAP y puntajes conformal (se crean una vez por modelo)


# ----------------------------------------------------------------------------------------------- utilidades
def _sha256(ruta: Path) -> str:
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for bloque in iter(lambda: f.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()


def smape(y, yhat) -> float | None:
    """sMAPE (%) = media de 2|p - y| / (|y| + |p|); 0 cuando y = p = 0."""
    y = np.asarray(y, dtype=float)
    yhat = np.asarray(yhat, dtype=float)
    if len(y) == 0:
        return None
    den = np.abs(y) + np.abs(yhat)
    r = np.where(den > 0, 2 * np.abs(yhat - y) / np.where(den > 0, den, 1.0), 0.0)
    return float(r.mean() * 100)


def franja_de(horas) -> np.ndarray:
    h = np.asarray(horas, dtype=int)
    return np.select([(h >= a) & (h <= b) for _, a, b in FRANJAS], [n for n, _, _ in FRANJAS], "fuera")


def metricas(y, yhat, horas=None, rutas=None, p10=None, p90=None) -> dict:
    """MAE, RMSE, WAPE (%), sMAPE (%), sesgo (%), por ruta, por franja y en pico (6-8 y 17-19 h) frente a valle."""
    y = np.asarray(y, dtype=float)
    yhat = np.asarray(yhat, dtype=float)

    def _basicas(m):
        if m.sum() == 0:
            return {"n": 0, "mae": None, "rmse": None, "wape": None, "smape": None, "sesgo_pct": None}
        e = yhat[m] - y[m]
        tot = y[m].sum()
        return {
            "n": int(m.sum()),
            "mae": round(float(np.abs(e).mean()), 3),
            "rmse": round(float(np.sqrt((e**2).mean())), 3),
            "wape": round(float(np.abs(e).sum() / tot * 100), 3) if tot > 0 else None,
            "smape": round(smape(y[m], yhat[m]), 3),
            "sesgo_pct": round(float(e.sum() / tot * 100), 3) if tot > 0 else None,
        }

    todo = np.ones(len(y), dtype=bool)
    out = _basicas(todo)
    if p10 is not None and p90 is not None:
        lo, hi = np.asarray(p10, dtype=float), np.asarray(p90, dtype=float)
        out["cobertura_p10_p90"] = round(float(((y >= lo) & (y <= hi)).mean() * 100), 2)
        out["bajo_p10_pct"] = round(float((y < lo).mean() * 100), 2)
        out["sobre_p90_pct"] = round(float((y > hi).mean() * 100), 2)
    if rutas is not None:
        rutas = np.asarray(rutas)
        out["por_ruta"] = {str(r): _basicas(rutas == r) for r in sorted(set(rutas))}
    if horas is not None:
        pico = np.isin(np.asarray(horas), datos.HORAS_PICO)
        out["pico"] = _basicas(pico)
        out["valle"] = _basicas(~pico)
        fr = franja_de(horas)
        out["por_franja"] = {n: _basicas(fr == n) for n, _, _ in FRANJAS if (fr == n).any()}
    return out


def variables_de(serie: pd.DataFrame, contexto: pd.DataFrame | None = None) -> pd.DataFrame:
    """La tabla de variables de `serie` (variables.construir_variables con el contexto de todas las rutas) con las
    novedades viales de rutas dadas encima (§11.2, novedades.aplicar_por_ruta y datos/novedades_por_ruta.parquet). Es
    el mismo paso al entrenar y al inferir; sin novedades por ruta (Sobusa) la tabla es exactamente la de siempre."""
    from app.servicios import novedades

    return novedades.aplicar_por_ruta(variables.construir_variables(serie, contexto=contexto),
                                      datos.novedades_por_ruta())


@lru_cache(maxsize=2)
def _tabla_bundled(ruta_archivo: str, mtime: float, mtime_contexto: float, mtime_novedades: float = -1.0
                   ) -> pd.DataFrame:
    tabla = variables_de(datos.demanda_horaria(), contexto=datos.contexto_operacional())
    tabla = tabla.set_index(["ruta", "fecha", "hora"]).sort_index()
    tabla.attrs["origen"] = "serie empaquetada (datos/demanda_horaria.parquet)"
    tabla.attrs["huella"] = ("empaquetada", ruta_archivo, mtime, mtime_contexto, mtime_novedades)
    return tabla


# sesión de la base de resultados que usan las variables dentro de un bloque `with con_sesion(s):` (el ciclo diario,
# el monitoreo, la sombra y la compuerta la ponen; ven también lo que la transacción de `s` aún no confirma)
_SESION_DATOS: ContextVar = ContextVar("inferencia_sesion_datos", default=None)
_CACHE_TABLAS: OrderedDict = OrderedDict()
_CANDADO_TABLAS = threading.Lock()
_TABLAS_MAX = 3
# los rezagos de un día D usan pasajeros de D-56 a D-7 (b8 y sd8: 8 semanas): un dato nuevo del día X cambia las
# variables de X+7 a X+56 y el valor real de X
VENTANA_REZAGOS_DIAS = 56
ENTORNO_SERIE = "INFERENCIA_SERIE"


@contextmanager
def con_sesion(sesion) -> Iterator:
    """Dentro del bloque, tabla_variables(), predecir(), evaluar() y lo que se apoya en ellas usan la serie validada
    de `sesion` (Parquet empaquetado con demanda_observada encima)."""
    token = _SESION_DATOS.set(sesion)
    try:
        yield sesion
    finally:
        _SESION_DATOS.reset(token)


def _tabla_empaquetada() -> pd.DataFrame:
    archivo = datos.carpeta_datos() / "demanda_horaria.parquet"
    return _tabla_bundled(str(archivo), archivo.stat().st_mtime, datos.huella_archivo("contexto_operacional.parquet"),
                          datos.huella_archivo("novedades_por_ruta.parquet"))


def tabla_variables(sesion=None) -> pd.DataFrame:
    """Variables por (ruta, fecha, hora) con el objetivo real (pasajeros) y los rezagos de todas las versiones.

    Con `sesion` (o dentro de `with con_sesion(s):`) es la serie VALIDADA: el Parquet empaquetado con las horas de
    demanda_observada encima (politica.serie_validada), recalculando solo los días tocados. Sin sesión es la serie
    empaquetada; con INFERENCIA_SERIE=validada el proceso abre su propia sesión de solo lectura."""
    s = sesion if sesion is not None else _SESION_DATOS.get()
    base = _tabla_empaquetada()
    if s is None:
        if os.environ.get(ENTORNO_SERIE, "").strip().lower() != "validada":
            return base
        return _tabla_con_sesion_propia(base)
    return _tabla_validada(s, base)


def _tabla_con_sesion_propia(base: pd.DataFrame) -> pd.DataFrame:
    """INFERENCIA_SERIE=validada sin sesión: una sesión corta propia (lo ya confirmado); si la base no responde se
    usa la serie empaquetada y queda en el registro."""
    try:
        from app.db import sesion_contexto

        with sesion_contexto() as s:
            return _tabla_validada(s, base)
    except Exception as exc:  # noqa: BLE001 - sin base de resultados se pronostica con la serie empaquetada
        LOG.warning("serie validada no disponible (se usa la empaquetada): %s", exc)
        return base


def _tabla_validada(s, base: pd.DataFrame) -> pd.DataFrame:
    from . import politica

    huella = politica.huella_observados(s)
    if huella[0] == 0:
        return base
    clave = (base.attrs.get("huella"), huella)
    with _CANDADO_TABLAS:
        if clave in _CACHE_TABLAS:
            _CACHE_TABLAS.move_to_end(clave)
            return _CACHE_TABLAS[clave]
    tabla = tabla_con_observados(base, datos.demanda_horaria(), politica.observados_validados(s))
    tabla.attrs["huella"] = ("validada", *clave)
    with _CANDADO_TABLAS:
        _CACHE_TABLAS[clave] = tabla
        while len(_CACHE_TABLAS) > _TABLAS_MAX:
            _CACHE_TABLAS.popitem(last=False)
    return tabla


def tabla_con_observados(base: pd.DataFrame, serie_base: pd.DataFrame, obs: pd.DataFrame) -> pd.DataFrame:
    """Tabla de variables de la serie validada sin recalcular lo que no cambió: las filas anteriores al primer día
    tocado salen de `base` (la tabla de `serie_base`) y desde ese día se recalculan con la serie unida (función pura;
    da lo mismo que variables_de sobre toda la serie unida)."""
    from . import politica

    serie, info = politica.superponer_observados(serie_base, obs)
    tocadas = info["fechas_tocadas"]
    if not tocadas:
        tabla = base.copy()
        tabla.attrs = dict(base.attrs, origen="serie empaquetada (demanda_observada no cambia ningún valor)")
        return tabla
    d_min = tocadas[0]
    sub = serie[serie["fecha"] >= d_min - timedelta(days=VENTANA_REZAGOS_DIAS)]
    nuevo = variables_de(sub, contexto=datos.contexto_operacional())
    nuevo = nuevo[nuevo["fecha"] >= d_min].set_index(["ruta", "fecha", "hora"])
    previo = base[np.asarray([f < d_min for f in base.index.get_level_values("fecha")], dtype=bool)]
    tabla = pd.concat([previo, nuevo[base.columns]]).sort_index()
    tabla.attrs = {"origen": "serie validada: datos/demanda_horaria.parquet con ai_frecuencias.demanda_observada "
                             "encima (politica.serie_validada)",
                   "filas_demanda_observada": info["filas_demanda_observada"],
                   "filas_con_valor_distinto": info["filas_con_valor_distinto"],
                   "recalculado_desde": str(d_min), "ultimo_dato": str(max(serie["fecha"]))}
    return tabla


def rango_tabla(tabla: pd.DataFrame) -> tuple[date, date]:
    """Primer y último día con variables en la tabla (el último incluye los 7 días que se pueden pronosticar)."""
    fechas = tabla.index.get_level_values("fecha")
    return min(fechas), max(fechas)


def ultimo_dato_real(tabla: pd.DataFrame) -> date | None:
    """Último día con pasajeros reales en la tabla."""
    con = tabla["pasajeros"].notna().to_numpy()
    if not con.any():
        return None
    return max(tabla.index.get_level_values("fecha")[con])


def _filas_utiles(tabla: pd.DataFrame) -> pd.DataFrame:
    t = tabla.reset_index() if "ruta" not in tabla.columns else tabla
    return t[t["pasajeros"].notna() & t["b8"].notna()].copy()


def _modelo_hgb(
    perdida: str, semilla: int, hiper: dict, cuantil: float | None = None, version: str | None = None
) -> HistGradientBoostingRegressor:
    extra = {"quantile": cuantil} if perdida == "quantile" else {}
    cols = variables.columnas(version)
    cats = [cols.index(c) for c in variables.categoricas(version)] or None  # fv2: ruta_cod ordinal
    # la tasa de aprendizaje va explícita con el valor de los hiperparámetros (0,05 en HIPER_DEFECTO), así que el modelo
    # no cambia; si un llamador no la trae, 0,1 es el valor por defecto de scikit-learn, el mismo que se usaba antes
    resto = {k: v for k, v in hiper.items() if k != "learning_rate"}
    return HistGradientBoostingRegressor(
        loss=perdida,
        learning_rate=hiper.get("learning_rate", LEARNING_RATE_SKLEARN),
        random_state=semilla,
        early_stopping=False,
        categorical_features=cats,
        **resto,
        **extra,
    )


def calibrar_nowcast(parte: pd.DataFrame, pred: np.ndarray, pesos=NOWCAST_PESOS) -> dict:
    """WAPE de la hora h pronosticada a las h:00 con el factor de las horas h-1 y h-2 (cerradas), para cada peso."""
    d = parte[["ruta", "fecha", "hora", "pasajeros"]].copy()
    d["pred"] = np.asarray(pred, dtype=float)
    previa = d.rename(columns={"pasajeros": "o", "pred": "e"})
    a = d.merge(previa.assign(hora=previa["hora"] + 1), on=["ruta", "fecha", "hora"], how="left")
    a = a.merge(previa.assign(hora=previa["hora"] + 2), on=["ruta", "fecha", "hora"], how="left", suffixes=("1", "2"))
    obs, esp = a["o1"] + a["o2"], a["e1"] + a["e2"]
    ok = (obs.notna() & (esp >= NOWCAST_MIN_ESPERADOS)).to_numpy()
    v = (a["hora"] >= 6).to_numpy()
    y = a["pasajeros"].to_numpy(float)
    razon = np.where(ok, obs / esp.where(esp > 0, 1.0), 1.0)
    res = {}
    for k in pesos:
        f = np.where(ok, np.clip(1 + k * (razon - 1), NOWCAST_MIN, NOWCAST_MAX), 1.0)
        yh = a["pred"].to_numpy(float) * f
        res[str(k)] = (
            round(float(np.abs(yh[v] - y[v]).sum() / y[v].sum() * 100), 3) if v.any() and y[v].sum() > 0 else None
        )
    validos = {k: w for k, w in res.items() if w is not None}
    mejor = float(min(validos, key=validos.get)) if validos else NOWCAST_PESO_DEFECTO
    return {"peso": mejor, "wape_por_peso": res, "regla": "factor = clip(1 + peso*(obs/esp - 1), 0,8, 1,25)"}


def _pred_linea_base(nombre: str, t: pd.DataFrame) -> np.ndarray:
    var = LINEAS_BASE[nombre]["variable"]
    return t[var].fillna(t["b8"]).to_numpy(dtype=float)


# ----------------------------------------------------------------------------------------------- registro
def _ruta_registro(dir_modelos: Path) -> Path:
    return dir_modelos / "registro.json"


def registro(dir_modelos: Path | None = None) -> dict:
    dm = Path(dir_modelos) if dir_modelos else datos.carpeta_modelos()
    ruta = _ruta_registro(dm)
    if ruta.exists():
        return json.loads(ruta.read_text(encoding="utf-8"))
    return {"activo": "b1_manual_8sem", "modelos": {}, "historial_activacion": []}


def _guardar_registro(reg: dict, dir_modelos: Path) -> None:
    dir_modelos.mkdir(parents=True, exist_ok=True)
    reg["referencias_proyecto"] = {"nota": NOTA_REFERENCIAS, "modelos": REFERENCIAS_PROYECTO}
    for nombre, info in LINEAS_BASE.items():
        reg["modelos"].setdefault(
            nombre,
            {
                "model_id": nombre,
                "tipo": "linea_base",
                "estado": "referencia",
                "descripcion": info["descripcion"],
                "artefacto": None,
                "feature_version": variables.FEATURE_VERSION,
            },
        )
    _ruta_registro(dir_modelos).write_text(json.dumps(reg, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def modelo_activo(dir_modelos: Path | None = None) -> str:
    return registro(dir_modelos).get("activo") or "b1_manual_8sem"


def id_libre(model_id: str, dir_modelos: Path, protegidos: set[str] | None = None) -> str:
    """Nunca se sobrescribe un modelo activo (del registro en disco o de `protegidos`, p. ej. el activo de
    model_registry): si el id coincide, se usa <id>_r2, <id>_r3... (la primera carpeta libre)."""
    bloqueados = set(protegidos or ()) | {registro(dir_modelos).get("activo")}
    if model_id not in bloqueados:
        return model_id
    n = 2
    while f"{model_id}_r{n}" in bloqueados or (dir_modelos / f"{model_id}_r{n}").exists():
        n += 1
    return f"{model_id}_r{n}"


def listar_modelos(dir_modelos: Path | None = None) -> list[dict]:
    reg = registro(dir_modelos)
    filas = [dict(m, activo=(k == reg.get("activo"))) for k, m in reg.get("modelos", {}).items()]
    for nombre, info in LINEAS_BASE.items():
        if nombre not in reg.get("modelos", {}):
            filas.append(
                {
                    "model_id": nombre,
                    "tipo": "linea_base",
                    "descripcion": info["descripcion"],
                    "activo": reg.get("activo") == nombre,
                }
            )
    filas += [
        dict(r, tipo="referencia_proyecto", ejecutable_en_api=False, nota=NOTA_REFERENCIAS)
        for r in REFERENCIAS_PROYECTO
    ]
    return filas


def activar(model_id: str, usuario: str = "sistema", motivo: str = "", dir_modelos: Path | None = None) -> dict:
    """Activa una versión registrada (también sirve para volver atrás, RF-019)."""
    dm = Path(dir_modelos) if dir_modelos else datos.carpeta_modelos()
    reg = registro(dm)
    if model_id not in reg.get("modelos", {}) and model_id not in LINEAS_BASE:
        raise ModeloNoEncontrado(f"Modelo no registrado: {model_id}")
    anterior = reg.get("activo")
    reg["activo"] = model_id
    _sincronizar_estados(reg)
    reg.setdefault("historial_activacion", []).append(
        {
            "en": datetime.now(UTC).isoformat(timespec="seconds"),
            "de": anterior,
            "a": model_id,
            "usuario": usuario,
            "motivo": motivo,
        }
    )
    _guardar_registro(reg, dm)
    return {"activo": model_id, "anterior": anterior}


def _sincronizar_estados(reg: dict) -> None:
    """Un solo modelo con estado 'activo' (el de reg['activo']); los candidatos que lo fueron pasan a 'candidato'."""
    for k, m in reg.get("modelos", {}).items():
        if m.get("tipo") == "linea_base":
            continue
        if k == reg.get("activo"):
            m["estado"] = "activo"
        elif m.get("estado") == "activo":
            m["estado"] = "candidato"


# ----------------------------------------------------------------------------------------------- entrenamiento
def entrenar(
    hasta: date = date(2025, 8, 31),
    semilla: int = 42,
    *,
    serie: pd.DataFrame | None = None,
    dir_modelos: Path | None = None,
    hiper: dict | None = None,
    activar_si_mejora: bool = False,
    version: str | None = None,
    contexto: pd.DataFrame | None = None,
    ids_protegidos: set[str] | None = None,
    calibrar: bool = True,
    calibracion_grupos: tuple[str, ...] | None = None,
) -> dict:
    """Entrena el candidato (punto + P10 + P90) con datos <= hasta, lo compara con B1/B2 y lo guarda.

    `ids_protegidos` (p. ej. el activo de model_registry) y el activo del registro en disco nunca se sobrescriben: si
    el id calculado coincide con uno de ellos, el modelo nuevo se guarda como <id>_r2, <id>_r3...

    `version` = versión de variables (por defecto variables.FEATURE_VERSION). Escribe el artefacto y su manifiesto en
    dir_modelos/<model_id>/ y actualiza registro.json. Por defecto el modelo queda como CANDIDATO: la activación pasa
    por la gobernanza (POST /models/{id}/activate o scripts/entrenar.py). activar_si_mejora=True lo activa en el
    registro en disco si mejora a B1 en validación (uso del script de línea de comandos).

    Con calibrar=True (por defecto) el modelo nuevo trae su propia calibración por grupo (v2), ajustada con SU
    validación (los 61 días posteriores al corte) y versionada junto al artefacto con su SHA-256; los grupos son
    `calibracion_grupos` (por defecto CALIBRACION_GRUPOS_DEFECTO, el esquema de la calibración del activo).
    """
    version = variables.version_valida(version)
    cols = variables.columnas(version)
    dm = Path(dir_modelos) if dir_modelos else datos.carpeta_modelos()
    hp = dict(HIPER_DEFECTO, **(hiper or {}))
    serie = datos.demanda_horaria() if serie is None else serie
    tr, va, te = _particion_cronologica(serie, contexto, hasta)
    modelos, seg_entrenamiento = _ajustar_modelos(tr, semilla, hp, version)
    punto = modelos["punto"]
    # la selección y la compuerta usan solo la validación: la prueba reservada no se mide al entrenar (la reporta
    # únicamente scripts/evaluar_modelo.py, como informe)
    met = {"validacion": _evaluar_parte(modelos, va, version)}
    nowcast = _nowcast_de_validacion(punto, va, version)
    muestra = va.sample(min(3000, len(va)), random_state=semilla)
    importancia = _importancia_permutacion(punto, muestra, semilla, version)
    explicabilidad = _importancia_shap(punto, variables.matriz_x(muestra.head(SHAP_FILAS_GLOBAL), version), version)
    wape_c = met["validacion"]["candidato"]["wape"]
    wape_b1 = met["validacion"]["b1_manual_8sem"]["wape"]
    supera = wape_c is not None and wape_b1 is not None and wape_c < wape_b1

    model_id = id_libre(f"hgb_{version.split('-')[0]}_{hasta:%Y%m%d}_s{semilla}", dm, ids_protegidos)
    carpeta = dm / model_id
    referencia_psi = _referencia_deriva(punto, tr, hasta, version)
    carpeta.mkdir(parents=True, exist_ok=True)
    artefacto = carpeta / "modelo.joblib"
    sha = _guardar_artefacto(artefacto, modelos, version)
    manifiesto = {
        "model_id": model_id,
        "tipo": "candidato",
        "algoritmo": "hist_gradient_boosting",
        # sin «estado»: la fuente de verdad del estado es registro.json (y model_registry en la base de resultados)
        "artefacto": "modelo.joblib",
        "sha256": sha,
        "feature_version": version,
        "data_cutoff": str(hasta),
        "semilla": semilla,
        "hiperparametros": hp,
        "perdidas": {"punto": "poisson", "p10": "quantile 0.1", "p90": "quantile 0.9"},
        "variables": cols,
        "categoricas": variables.categoricas(version),
        "descripcion_variables": variables.VERSIONES[version]["descripcion"],
        "explicabilidad": explicabilidad,
        "referencia_psi": referencia_psi,
        "conformal": dict(META_CONFORMAL_V1),
        "filas_entrenamiento": len(tr),
        "filas_validacion": len(va),
        "filas_prueba": len(te),
        "particion": _particion_texto(tr, te, hasta),
        "nota_prueba_reservada": "la prueba reservada no se evalúa al entrenar ni en la compuerta: su informe lo "
                                 "escribe scripts/evaluar_modelo.py en la clave «evaluacion»",
        "metricas": met,
        "supera_linea_base_validacion": bool(supera),
        "nowcast": nowcast,
        "importancia_global": importancia,
        "nota_importancia": "aumento del MAE (pasajeros) al permutar la variable en 3000 horas de validación",
        "segundos_entrenamiento": seg_entrenamiento,
        "creado_en": datetime.now(UTC).isoformat(timespec="seconds"),
        "versiones": {"sklearn": __import__("sklearn").__version__, "pandas": pd.__version__, "numpy": np.__version__},
        "version_datos": _version_datos(serie),
        **huellas_codigo(),
        "version_contexto": {
            "contexto_operacional_mtime": datos.huella_archivo("contexto_operacional.parquet"),
            "novedades_por_ruta_mtime": datos.huella_archivo("novedades_por_ruta.parquet"),
            "perfil_intrahorario_mtime": datos.huella_archivo(ARCHIVO_PERFIL),
        },
    }
    (carpeta / ARCHIVO_MANIFIESTO).write_text(
        json.dumps(manifiesto, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    calibracion = None
    if calibrar:   # la banda del candidato se calibra igual que la del activo, con su propia validación
        calibracion = _calibrar_al_entrenar(carpeta, model_id, modelos, va, version, calibracion_grupos)
    decision = _decision_entrenamiento(supera, activar_si_mejora)
    _registrar_entrenamiento(dm, dict(manifiesto, estado=_estado_inicial(supera, activar_si_mejora)), met, decision,
                             activar=supera and activar_si_mejora)
    with _CANDADO:  # la llave de la caché es "<carpeta>::<model_id>": se invalida la versión anterior del artefacto
        _CACHE_MODELOS.pop(f"{dm.resolve()}::{model_id}", None)
        _CACHE_MODELOS.pop(model_id, None)
    return {
        "model_id": model_id,
        "tipo": manifiesto["tipo"],
        "metricas": met,
        "artefacto": str(artefacto),
        "sha256": sha,
        "feature_version": version,
        "data_cutoff": hasta,
        "supera_linea_base": bool(supera),
        "decision": decision,
        "manifiesto": str(carpeta / ARCHIVO_MANIFIESTO),
        "calibracion": calibracion,
    }


META_CONFORMAL_V1 = {
    "metodo": "CQR móvil por ruta",
    "ventana_dias": CONFORMAL_VENTANA_DIAS,
    "minimo_dias": CONFORMAL_MIN_DIAS,
    "cobertura_objetivo": COBERTURA_OBJETIVO,
    "solo_dias_fuera_de_muestra": True,
}
CLAVES_REGISTRO = (
    "model_id",
    "tipo",
    "algoritmo",
    "estado",
    "artefacto",
    "sha256",
    "feature_version",
    "data_cutoff",
    "semilla",
    "supera_linea_base_validacion",
    "creado_en",
)


class CorteSinDatos(ValueError):
    """El corte pedido no deja filas útiles para entrenar (<= corte) o para validar (los 61 días siguientes)."""

    def __init__(self, hasta: date, entrenamiento: int, validacion: int) -> None:
        super().__init__("No hay datos suficientes para entrenar y validar con ese corte")
        self.hasta, self.entrenamiento, self.validacion = hasta, entrenamiento, validacion


def _particion_cronologica(
    serie: pd.DataFrame, contexto: pd.DataFrame | None, hasta: date
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """División cronológica (§9.3): entrenamiento <= hasta, validación los 61 días siguientes y prueba el resto. Una
    serie sin filas no deja nada para entrenar ni para validar: es el mismo CorteSinDatos (con ella las variables no se
    pueden armar)."""
    if serie.empty:
        raise CorteSinDatos(hasta, 0, 0)
    t = _filas_utiles(variables_de(serie, contexto=contexto))
    t = t[t["fecha"] <= serie["fecha"].max()]
    fin_val = hasta + timedelta(days=DIAS_VALIDACION)
    tr, va, te = t[t["fecha"] <= hasta], t[(t["fecha"] > hasta) & (t["fecha"] <= fin_val)], t[t["fecha"] > fin_val]
    if len(tr) == 0 or len(va) == 0:
        raise CorteSinDatos(hasta, len(tr), len(va))
    return tr, va, te


def corte_sin_datos(serie: pd.DataFrame, hasta: date, contexto: pd.DataFrame | None = None) -> dict | None:
    """¿Se puede entrenar y validar con `serie` y el corte `hasta`? None si sí; si no, el motivo con el que entrenar()
    fallaría y las filas útiles que deja cada parte. Corre la partición del entrenamiento (_particion_cronologica, la
    misma que usa entrenar), no una copia de su regla: quien decide pedir un entrenamiento lo sabe antes de
    encolarlo."""
    try:
        _particion_cronologica(serie, contexto, hasta)
    except CorteSinDatos as exc:
        return {"motivo": str(exc), "corte": exc.hasta, "filas_entrenamiento": exc.entrenamiento,
                "filas_validacion": exc.validacion}
    return None


def _particion_texto(tr: pd.DataFrame, te: pd.DataFrame, hasta: date) -> dict:
    fin_val = hasta + timedelta(days=DIAS_VALIDACION)
    return {
        "entrenamiento": f"{tr['fecha'].min()} a {hasta}",
        "validacion": f"{hasta + timedelta(days=1)} a {fin_val}",
        "prueba": f"{te['fecha'].min()} a {te['fecha'].max()}" if len(te) else None,
    }


def _ajustar_modelos(tr: pd.DataFrame, semilla: int, hp: dict, version: str) -> tuple[dict, float]:
    """Los tres modelos del candidato (punto Poisson, P10 y P90), en ese orden y con la misma semilla."""
    x_tr, y_tr = variables.matriz_x(tr, version), tr["pasajeros"].to_numpy(float)
    t0 = time.perf_counter()
    modelos = {
        "punto": _modelo_hgb("poisson", semilla, hp, version=version).fit(x_tr, y_tr),
        "p10": _modelo_hgb("quantile", semilla, hp, 0.1, version=version).fit(x_tr, y_tr),
        "p90": _modelo_hgb("quantile", semilla, hp, 0.9, version=version).fit(x_tr, y_tr),
    }
    return modelos, round(time.perf_counter() - t0, 2)


def _predecir_tres(modelos: dict, parte: pd.DataFrame, version: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    x = variables.matriz_x(parte, version)
    return _ordenar(modelos["punto"].predict(x), modelos["p10"].predict(x), modelos["p90"].predict(x))


def _evaluar_parte(modelos: dict, parte: pd.DataFrame, version: str) -> dict:
    """Métricas del candidato y de las líneas base en una parte de la división ({} si la parte está vacía)."""
    if len(parte) == 0:
        return {}
    p, lo, hi = _predecir_tres(modelos, parte, version)
    args = {"horas": parte["hora"].to_numpy(), "rutas": parte["ruta"].to_numpy()}
    res = {"candidato": metricas(parte["pasajeros"], p, p10=lo, p90=hi, **args)}
    for nombre in LINEAS_BASE:
        res[nombre] = metricas(parte["pasajeros"], _pred_linea_base(nombre, parte), **args)
    res["desde"], res["hasta"] = str(parte["fecha"].min()), str(parte["fecha"].max())
    return res


def _nowcast_de_validacion(punto, va: pd.DataFrame, version: str) -> dict:
    """Peso del factor intradía elegido en la validación (la prueba reservada no se mira al entrenar)."""
    nowcast = calibrar_nowcast(va, punto.predict(variables.matriz_x(va, version)))
    nowcast["calibrado_en"] = f"validación {va['fecha'].min()} a {va['fecha'].max()}"
    return nowcast


ARCHIVOS_CODIGO = ("variables.py", "inferencia.py")
NORMALIZACION_CODIGO = "texto UTF-8 con fin de línea LF (CRLF y CR pasan a LF antes del SHA-256)"


def sha256_codigo(texto: str) -> str:
    """SHA-256 de un archivo de código con el fin de línea normalizado a LF: igual en Windows, Linux y macOS."""
    return hashlib.sha256(texto.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")).hexdigest()


def sin_docstring_de_modulo(texto: str) -> str:
    """El código sin el docstring del módulo (la documentación puede cambiar sin cambiar el preprocesamiento)."""
    import ast

    texto = texto.replace("\r\n", "\n").replace("\r", "\n")
    cuerpo = ast.parse(texto).body
    if cuerpo and isinstance(cuerpo[0], ast.Expr) and isinstance(getattr(cuerpo[0], "value", None), ast.Constant) \
            and isinstance(cuerpo[0].value.value, str):
        return "\n".join(texto.split("\n")[cuerpo[0].end_lineno:])
    return texto


def _git(*args: str) -> str | None:
    try:
        # argumentos fijos de este módulo (rev-parse y status): no hay entrada externa
        r = subprocess.run(["git", *args], cwd=Path(__file__).parent,  # noqa: S603, S607  # nosec B603 B607
                           capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def huellas_codigo() -> dict:
    """Huellas del código que entrena e infiere, independientes del sistema operativo, y el commit de git (§9.3):
    codigo_sha256 (archivo completo con LF), codigo_sin_docstring_sha256 (sin el docstring del módulo) y
    codigo_commit con codigo_sin_cambios_locales (False si esos archivos tenían cambios sin confirmar)."""
    textos = {n: Path(__file__).with_name(n).read_text(encoding="utf-8") for n in ARCHIVOS_CODIGO}
    commit = _git("rev-parse", "HEAD")
    estado = _git("status", "--porcelain", "--", *ARCHIVOS_CODIGO) if commit else None
    return {
        "codigo_sha256": {n: sha256_codigo(t) for n, t in textos.items()},
        "codigo_sin_docstring_sha256": {n: sha256_codigo(sin_docstring_de_modulo(t)) for n, t in textos.items()},
        "codigo_normalizacion": NORMALIZACION_CODIGO,
        "codigo_commit": commit,
        "codigo_sin_cambios_locales": None if estado is None else estado == "",
    }


def _importancia_permutacion(punto, muestra: pd.DataFrame, semilla: int, version: str) -> list[dict]:
    """Aumento del MAE al permutar cada variable en la muestra de validación (3 repeticiones)."""
    pi = permutation_importance(
        punto,
        variables.matriz_x(muestra, version),
        muestra["pasajeros"].to_numpy(float),
        n_repeats=3,
        random_state=semilla,
        scoring="neg_mean_absolute_error",
    )
    return sorted(
        (
            {"variable": c, "aumento_mae": round(float(v), 3)}
            for c, v in zip(variables.columnas(version), pi.importances_mean, strict=False)
        ),
        key=lambda x: -x["aumento_mae"],
    )


def _referencia_deriva(punto, tr: pd.DataFrame, hasta: date, version: str) -> dict:
    """Referencia de deriva (PSI) con los 365 días de entrenamiento anteriores al corte (monitoreo §9.4)."""
    from . import monitoreo

    t_ref = tr[tr["fecha"] > hasta - timedelta(days=monitoreo.REFERENCIA_DIAS)]
    pred = punto.predict(variables.matriz_x(t_ref, version)) if len(t_ref) else np.zeros(0)
    return monitoreo.construir_referencia(t_ref, pred)


def _guardar_artefacto(artefacto: Path, modelos: dict, version: str) -> str:
    """Guarda modelo.joblib (los tres modelos y sus columnas) y devuelve su SHA-256."""
    joblib.dump(
        {
            "punto": modelos["punto"],
            "p10": modelos["p10"],
            "p90": modelos["p90"],
            "columnas": variables.columnas(version),
            "feature_version": version,
            "codigo_ruta": variables.CODIGO_RUTA,
        },
        artefacto,
        compress=3,
    )
    return _sha256(artefacto)


def _version_datos(serie: pd.DataFrame) -> dict:
    return {
        "sha256_serie": _huella_serie(serie),
        "filas_serie": len(serie),
        "desde": str(serie["fecha"].min()),
        "hasta": str(serie["fecha"].max()),
    }


def _estado_inicial(supera: bool, activar_si_mejora: bool) -> str:
    return "activo" if (supera and activar_si_mejora) else "candidato"


def _decision_entrenamiento(supera: bool, activar_si_mejora: bool) -> str:
    if not supera:
        return "se conserva el activo: no mejora a B1 en validación"
    if activar_si_mejora:
        return "activado: mejora a B1 en validación"
    return "candidato: mejora a B1 en validación; la activación pasa por la gobernanza"


def _registrar_entrenamiento(dm: Path, manifiesto: dict, met: dict, decision: str, activar: bool) -> None:
    """Ficha del modelo en registro.json; con activar=True (script de línea de comandos) también lo activa."""
    model_id = manifiesto["model_id"]
    reg = registro(dm)
    reg.setdefault("modelos", {})[model_id] = {k: manifiesto[k] for k in CLAVES_REGISTRO}
    reg["modelos"][model_id]["wape_validacion"] = met["validacion"]["candidato"]["wape"]
    if activar and reg.get("activo") != model_id:
        anterior = reg.get("activo")
        reg["activo"] = model_id
        reg.setdefault("historial_activacion", []).append(
            {
                "en": manifiesto["creado_en"],
                "de": anterior,
                "a": model_id,
                "usuario": "entrenamiento",
                "motivo": decision,
            }
        )
    _sincronizar_estados(reg)
    _guardar_registro(reg, dm)


def _calibrar_al_entrenar(
    carpeta: Path, model_id: str, modelos: dict, va: pd.DataFrame, version: str, grupos: tuple[str, ...] | None
) -> dict:
    """Calibración v2 del modelo recién entrenado, ajustada con SU validación y versionada junto al artefacto. El
    resumen guarda la cobertura y el ancho medio en esa misma validación (referencia: es la muestra del ajuste)."""
    banda = _predecir_tres(modelos, va, version)
    cal = calibracion_de_validacion(model_id, va, banda, tuple(grupos or CALIBRACION_GRUPOS_DEFECTO),
                                    script="app/servicios/inferencia.py (entrenar)",
                                    evidencia=f"{ARCHIVO_MANIFIESTO} del modelo, clave «calibracion.resumen»")
    p, lo, hi = banda
    lo2, hi2 = aplicar_conformal(p, lo, hi, q_calibracion(cal, va)[0])
    y = va["pasajeros"].to_numpy(float)
    resumen = {"validacion_ajuste": {
        "cobertura_modelo_pct": round(float(((y >= lo) & (y <= hi)).mean() * 100), 2),
        "cobertura_pct": round(float(((y >= lo2) & (y <= hi2)).mean() * 100), 2),
        "ancho_medio_modelo": round(float((hi - lo).mean()), 1),
        "ancho_medio": round(float((hi2 - lo2).mean()), 1),
        "nota": "en la misma muestra del ajuste; la sombra y la compuerta miden la banda fuera de muestra"}}
    return escribir_calibracion(carpeta, cal, resumen)


def _importancia_shap(punto, x: pd.DataFrame, version: str) -> dict:
    """Media de |SHAP| (escala log) por variable en una muestra de validación; solo si SHAP es exacto."""
    if variables.categoricas(version):
        return {
            "shap_local": False,
            "motivo": "ruta_cod es categórica nativa: TreeExplainer no es exacto (error de hasta 1,30 en escala log); "
            "se usa la importancia por permutación",
        }
    try:
        import shap

        ex = shap.TreeExplainer(punto)
        sv = np.asarray(ex.shap_values(x), dtype=float)
        base = float(np.ravel(ex.expected_value)[0])
        rec = base + sv.sum(axis=1)
        crudo = np.log(np.clip(punto.predict(x), 1e-12, None))
        media = np.abs(sv).mean(axis=0)
        return {
            "shap_local": True,
            "version_shap": shap.__version__,
            "base_log": round(base, 6),
            "base_pasajeros": round(math.exp(base), 2),
            "filas": len(x),
            "error_reconstruccion_log_max": float(np.abs(rec - crudo).max()) if len(x) else None,
            "media_abs_shap_log": sorted(
                ({"variable": c, "media_abs": round(float(v), 4)} for c, v in zip(x.columns, media, strict=False)),
                key=lambda d: -d["media_abs"],
            ),
        }
    except Exception as exc:  # noqa: BLE001 - la explicación no debe impedir entrenar
        return {"shap_local": False, "motivo": f"SHAP no disponible: {exc}"}


def _huella_serie(serie: pd.DataFrame) -> str:
    """sha256 del contenido de la serie usada (ruta, fecha, hora, pasajeros): versión de los datos de entrenamiento."""
    s = serie[["ruta", "fecha", "hora", "pasajeros"]].sort_values(["ruta", "fecha", "hora"]).astype(str)
    return hashlib.sha256(pd.util.hash_pandas_object(s, index=False).to_numpy().tobytes()).hexdigest()


def _ordenar(p, lo, hi):
    p = np.clip(np.asarray(p, float), 0, None)
    lo = np.clip(np.minimum(np.asarray(lo, float), p), 0, None)
    hi = np.maximum(np.asarray(hi, float), p)
    return p, lo, hi


# ----------------------------------------------------------------------------------------------- carga
def cargar(model_id: str | None = None, dir_modelos: Path | None = None) -> dict:
    """Carga el modelo una sola vez (caché en memoria) y verifica su sha256 contra el manifiesto."""
    dm = Path(dir_modelos) if dir_modelos else datos.carpeta_modelos()
    mid = model_id or modelo_activo(dm)
    from . import onnx_motor  # MOTOR_INFERENCIA=sklearn|onnx (§9.1 «exportado a ONNX», §9.2)

    motor = onnx_motor.motor_configurado()
    clave = (f"{dm.resolve()}::{mid}" + ("::onnx" if motor == "onnx" else "")
             + ("::v1" if preferencia_calibracion() == "v1" else ""))
    with _CANDADO:
        if clave in _CACHE_MODELOS:
            return _CACHE_MODELOS[clave]
        if mid in LINEAS_BASE:
            info = {
                "model_id": mid,
                "tipo": "linea_base",
                "feature_version": variables.FEATURE_VERSION,
                "data_cutoff": None,
                "manifiesto": {"descripcion": LINEAS_BASE[mid]["descripcion"]},
            }
            _CACHE_MODELOS[clave] = info
            return info
        carpeta = dm / mid
        ruta_man = carpeta / ARCHIVO_MANIFIESTO
        if not ruta_man.exists():
            raise ModeloNoEncontrado(f"No existe el manifiesto del modelo {mid} en {carpeta}")
        man = json.loads(ruta_man.read_text(encoding="utf-8"))
        artefacto = carpeta / man["artefacto"]
        sha = _sha256(artefacto)
        if sha != man["sha256"]:
            raise ErrorIntegridadModelo(
                f"El hash del artefacto de {mid} no coincide con el manifiesto "
                f"(esperado {man['sha256'][:12]}..., calculado {sha[:12]}...)"
            )
        version = man.get("feature_version")
        if version not in variables.VERSIONES:
            raise ErrorIntegridadModelo(
                f"{mid} usa variables {version}, que el código no tiene registradas ({sorted(variables.VERSIONES)})"
            )
        if man.get("variables") and list(man["variables"]) != variables.columnas(version):
            raise ErrorIntegridadModelo(f"{mid}: las variables del manifiesto no coinciden con la versión {version}")
        obj = joblib.load(artefacto)
        info = {
            "model_id": mid,
            "tipo": man["tipo"],
            "feature_version": version,
            "data_cutoff": date.fromisoformat(man["data_cutoff"]),
            "sha256": sha,
            "manifiesto": man,
            "punto": obj["punto"],
            "p10": obj["p10"],
            "p90": obj["p90"],
            "columnas": variables.columnas(version),
            "shap_exacto": not variables.categoricas(version),
            "motor": "sklearn",
            # calibración versionada de la banda (clave «calibracion» del manifiesto, con su SHA-256); None = v1
            "calibracion": cargar_calibracion(carpeta, man),
        }
        if motor == "onnx":  # mismas salidas con ONNX Runtime; SHAP sigue usando el árbol de sklearn
            info["punto_sklearn"] = info["punto"]
            info.update(onnx_motor.cargar_sesiones(carpeta, man), motor="onnx")
        _CACHE_MODELOS[clave] = info
        return info


def precalentar(model_id: str | None = None) -> dict:
    """Carga el modelo activo y las variables al arrancar la API (la primera predicción no paga ese costo)."""
    t0 = time.perf_counter()
    info = cargar(model_id)
    tabla_variables()
    try:  # la primera predicción no paga la calibración conformal ni el explicador SHAP
        _puntajes_conformal(info)
        _explicador(info)
    except Exception as exc:  # noqa: BLE001
        LOG.warning("precalentar: conformal/SHAP no disponibles: %s", exc)
    return {"model_id": info["model_id"], "segundos": round(time.perf_counter() - t0, 2)}


def limpiar_cache() -> None:
    with _CANDADO:
        _CACHE_MODELOS.clear()
    with _CANDADO_TABLAS:
        _CACHE_TABLAS.clear()
    _tabla_bundled.cache_clear()
    _perfil.cache_clear()


def _version_modelo(modelo: dict) -> str:
    return modelo.get("feature_version") if modelo.get("feature_version") in variables.VERSIONES else variables.FV1


def _predecir_filas(modelo: dict, filas: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    if modelo["tipo"] == "linea_base":
        p = _pred_linea_base(modelo["model_id"], filas)
        sd = filas["sd8"].fillna(0).to_numpy(float)
        return _ordenar(p, p - 1.2816 * sd, p + 1.2816 * sd)
    x = variables.matriz_x(filas, _version_modelo(modelo))
    return _ordenar(modelo["punto"].predict(x), modelo["p10"].predict(x), modelo["p90"].predict(x))


def _predecir_punto(modelo: dict, filas: pd.DataFrame) -> np.ndarray:
    """Solo el pronóstico puntual (lo que necesita el factor intradía)."""
    if modelo["tipo"] == "linea_base":
        return np.clip(_pred_linea_base(modelo["model_id"], filas), 0, None)
    return np.clip(modelo["punto"].predict(variables.matriz_x(filas, _version_modelo(modelo))), 0, None)


# ----------------------------------------------------------------------------------------------- conformal (P10-P90)
def puntajes_conformal(p, lo, hi, y) -> np.ndarray:
    """Puntaje CQR relativo: s = max(lo - y, y - hi) / max(p, 1) (negativo si y cae dentro de la banda)."""
    p, lo, hi, y = (np.asarray(v, dtype=float) for v in (p, lo, hi, y))
    return np.maximum(lo - y, y - hi) / np.maximum(p, 1.0)


def cuantil_conformal(s, cobertura: float = COBERTURA_OBJETIVO) -> float | None:
    """Cuantil de nivel ceil((n + 1) * cobertura) / n (garantía de muestra finita del conformal partido): el
    k-ésimo menor puntaje con k = ceil((n + 1) * cobertura), recortado a n."""
    s = np.asarray(s, dtype=float)
    s = s[~np.isnan(s)]
    n = len(s)
    if n == 0:
        return None
    k = min(n, max(1, math.ceil((n + 1) * cobertura - 1e-9)))
    return float(np.partition(s, k - 1)[k - 1])


def aplicar_conformal(p, lo, hi, q: float | None) -> tuple[np.ndarray, np.ndarray]:
    """lo' = max(0, lo - q * max(p, 1)), hi' = hi + q * max(p, 1), con lo' <= p <= hi'."""
    p, lo, hi = (np.asarray(v, dtype=float) for v in (p, lo, hi))
    if q is None:
        return lo, hi
    esc = np.maximum(p, 1.0)
    return np.clip(np.minimum(lo - q * esc, p), 0, None), np.maximum(hi + q * esc, p)


def cuantiles_conformal_movil(
    puntajes: pd.DataFrame,
    claves,
    ventana_dias: int = CONFORMAL_VENTANA_DIAS,
    minimo_dias: int = CONFORMAL_MIN_DIAS,
    cobertura: float = COBERTURA_OBJETIVO,
) -> dict:
    """q por (ruta, fecha) con los puntajes de la misma ruta en [fecha - ventana, fecha - 1] (sin el propio día).

    `puntajes`: columnas ruta, fecha, s (o el índice de _indice_puntajes). Devuelve
    {(ruta, fecha): {aplicado, q, dias_calibracion, n, motivo}}.
    """
    por_ruta = puntajes if isinstance(puntajes, dict) else _indice_puntajes(puntajes)
    out = {}
    vacio = (np.array([], dtype="datetime64[D]"), np.array([], dtype=float))
    for ruta, fecha in claves:
        f, s = por_ruta.get(ruta, vacio)
        d = np.datetime64(pd.Timestamp(fecha).date(), "D")
        i0 = np.searchsorted(f, d - np.timedelta64(int(ventana_dias), "D"), "left")
        i1 = np.searchsorted(f, d, "left")
        dias = len(np.unique(f[i0:i1]))
        if dias < minimo_dias:
            out[(ruta, fecha)] = {
                "aplicado": False,
                "q": None,
                "dias_calibracion": int(dias),
                "n": int(i1 - i0),
                "motivo": f"solo {dias} día(s) fuera de muestra con dato en los {ventana_dias} días previos "
                f"(mínimo {minimo_dias}): banda del modelo sin ajustar",
            }
            continue
        q = cuantil_conformal(s[i0:i1], cobertura)
        out[(ruta, fecha)] = {
            "aplicado": True,
            "q": round(float(q), 6),
            "dias_calibracion": int(dias),
            "n": int(i1 - i0),
            "motivo": None,
        }
    return out


def _indice_puntajes(puntajes: pd.DataFrame) -> dict:
    """{ruta: (fechas datetime64[D] ordenadas, puntajes)} para buscar la ventana con searchsorted."""
    por_ruta = {}
    if len(puntajes):
        pz = puntajes.dropna(subset=["s"]).copy()
        pz["f"] = pd.to_datetime(pz["fecha"]).to_numpy(dtype="datetime64[D]")
        for r, g in pz.sort_values("f", kind="stable").groupby("ruta"):
            por_ruta[r] = (g["f"].to_numpy(), g["s"].to_numpy(float))
    return por_ruta


def _puntajes_conformal(modelo: dict) -> pd.DataFrame:
    """Puntajes de los días con dato real posteriores al corte del modelo (fuera de muestra). Una vez por modelo y por
    versión de la tabla de variables (un día validado nuevo suma sus puntajes)."""
    tabla = tabla_variables()
    huella = tabla.attrs.get("huella")
    if "_puntajes_conformal" in modelo and modelo.get("_puntajes_huella") == huella:
        return modelo["_puntajes_conformal"]
    with _CANDADO_AUX:
        if "_puntajes_conformal" not in modelo or modelo.get("_puntajes_huella") != huella:
            modelo["_puntajes_huella"] = huella
            t = _filas_utiles(tabla)
            if modelo.get("data_cutoff") is not None:
                t = t[t["fecha"] > modelo["data_cutoff"]]
            if len(t):
                p, lo, hi = _predecir_filas(modelo, t)
                s = puntajes_conformal(p, lo, hi, t["pasajeros"].to_numpy(float))
            else:
                s = np.zeros(0)
            pz = pd.DataFrame({"ruta": t["ruta"].to_numpy(), "fecha": t["fecha"].to_numpy(), "s": s})
            modelo["_indice_conformal"] = _indice_puntajes(pz)
            modelo["_conformal_q"] = {}
            modelo["_puntajes_conformal"] = pz
    return modelo["_puntajes_conformal"]


def ajuste_conformal(modelo: dict, ruta: str, fecha: date) -> dict:
    """Ajuste conformal de la banda para una ruta y el día del pronóstico (usa solo días anteriores)."""
    _puntajes_conformal(modelo)
    cache = modelo.setdefault("_conformal_q", {})
    clave = (ruta, fecha)
    if clave not in cache:
        cache[clave] = cuantiles_conformal_movil(modelo["_indice_conformal"], [clave])[clave]
    return dict(cache[clave], cobertura_objetivo=COBERTURA_OBJETIVO, ventana_dias=CONFORMAL_VENTANA_DIAS)


# ------------------------------------------------------------------ calibración por grupo versionada (Mondrian, v2)
# Un cuantil conformal por grupo (bloque horario, ruta, hora o tipo de día), ajustado solo con la validación por
# scripts/calibrar_por_grupo.py y guardado junto al modelo (calibracion_v2.json, SHA-256 en el manifiesto). Se aplica
# DESPUÉS del modelo, igual con MOTOR_INFERENCIA=sklearn u onnx; el artefacto y sus hashes no cambian.
CALIBRACION_GRUPOS = ("bloque", "ruta", "hora", "tipo")
CALIBRACION_V1 = f"v1: conformal móvil (CQR) por ruta, {CONFORMAL_VENTANA_DIAS} días previos"


def preferencia_calibracion() -> str:
    """CALIBRACION_BANDA=v1 fuerza el conformal móvil por ruta aunque el modelo traiga una calibración versionada."""
    return "v1" if os.environ.get("CALIBRACION_BANDA", "").strip().lower() == "v1" else "manifiesto"


def cargar_calibracion(carpeta: Path, man: dict) -> dict | None:
    """Lee la calibración versionada del manifiesto (clave «calibracion») y verifica su SHA-256 (§9.2)."""
    meta = man.get("calibracion")
    if not meta or preferencia_calibracion() == "v1":
        return None
    archivo = carpeta / str(meta.get("archivo") or "")
    if not archivo.is_file():
        raise ErrorIntegridadModelo(f"Falta el archivo de calibración {meta.get('archivo')} de {man.get('model_id')}")
    sha = _sha256(archivo)
    if sha != meta.get("sha256"):
        raise ErrorIntegridadModelo(
            f"El hash de la calibración {archivo.name} no coincide con el manifiesto "
            f"(esperado {str(meta.get('sha256'))[:12]}..., calculado {sha[:12]}...)")
    cal = json.loads(archivo.read_text(encoding="utf-8"))
    grupos = [str(g) for g in cal.get("grupos") or []]
    q = {str(k): float(v) for k, v in (cal.get("q") or {}).items()}
    if not grupos or set(grupos) - set(CALIBRACION_GRUPOS) or "*" not in q:
        raise ErrorIntegridadModelo(f"Calibración {archivo.name} inválida: grupos {grupos}, sin cuantil global «*»")
    return {"version": str(cal.get("version") or meta.get("version")), "nombre": cal.get("nombre"), "grupos": grupos,
            "q": q, "archivo": archivo.name, "sha256": sha, "ajustado_con": cal.get("ajustado_con"),
            "cobertura_objetivo": float(cal.get("cobertura_objetivo", COBERTURA_OBJETIVO))}


def grupos_calibracion(filas: pd.DataFrame, grupos) -> np.ndarray:
    """Clave de grupo de cada fila («06-08 pico», «CRA 54|09-16 valle», …), la misma del ajuste."""
    partes = []
    for g in grupos:
        if g == "bloque":
            partes.append(franja_de(filas["hora"].to_numpy()).astype(str))
        elif g == "ruta":
            partes.append(filas["ruta"].astype(str).to_numpy())
        elif g == "hora":
            partes.append(filas["hora"].astype(int).astype(str).to_numpy())
        elif g == "tipo":
            partes.append(filas["tipo_dia"].astype(int).map(datos.TIPOS_DIA).astype(str).to_numpy())
        else:
            raise ValueError(f"grupo de calibración desconocido: {g!r}")
    return np.array(["|".join(map(str, x)) for x in zip(*partes, strict=True)], dtype=object)


def q_calibracion(calibracion: dict, filas: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Cuantil de cada fila según su grupo (el global «*» si el grupo no tenía puntajes suficientes)."""
    claves = grupos_calibracion(filas, calibracion["grupos"])
    q = calibracion["q"]
    return np.array([q.get(k, q["*"]) for k in claves], dtype=float), claves


def calibrar_filas(modelo: dict, ruta: str, fecha: date, filas: pd.DataFrame) -> tuple[dict, float | np.ndarray | None]:
    """Ajuste de la banda de unas filas: la calibración versionada del modelo (v2) si la trae; si no, el conformal
    móvil por ruta (v1). Devuelve (detalle para la trazabilidad, q escalar o por fila)."""
    cal = modelo.get("calibracion")
    if cal:
        q, claves = q_calibracion(cal, filas)
        return ({"aplicado": True, "version": cal["version"], "metodo": cal["nombre"], "q": float(q[0]),
                 "q_por_hora": [round(float(x), 6) for x in q], "grupos": [str(c) for c in claves],
                 "archivo": cal["archivo"], "sha256": cal["sha256"], "ajustado_con": cal["ajustado_con"],
                 "motivo": None, "cobertura_objetivo": cal["cobertura_objetivo"]}, q)
    conf = dict(ajuste_conformal(modelo, ruta, fecha), version="v1", metodo=CALIBRACION_V1)
    return conf, conf.get("q")


def ajustar_calibracion_grupo(
    filas: pd.DataFrame, puntajes, grupos, cobertura: float = COBERTURA_OBJETIVO, minimo: int = CALIBRACION_MIN_GRUPO
) -> dict:
    """{"q": {grupo: q}, "n": {grupo: n}}: cuantil conformal de muestra finita de cada grupo con al menos `minimo`
    puntajes; «*» = cuantil global (respaldo de los grupos pequeños). Lo usan entrenar() y calibrar_por_grupo.py."""
    g = grupos_calibracion(filas, grupos)
    s = np.asarray(puntajes, dtype=float)
    q = {"*": cuantil_conformal(s, cobertura)}
    n = {}
    for k in sorted(set(g)):
        m = g == k
        n[k] = int(m.sum())
        if n[k] >= minimo:
            q[k] = cuantil_conformal(s[m], cobertura)
    return {"q": {k: round(float(v), 6) for k, v in q.items() if v is not None}, "n": n}


def calibracion_de_validacion(
    model_id: str,
    filas: pd.DataFrame,
    banda: tuple,
    grupos=CALIBRACION_GRUPOS_DEFECTO,
    *,
    script: str,
    evidencia: str,
    ventana: tuple[date, date] | None = None,
) -> dict:
    """Calibración v2 (el contenido de calibracion_v2.json) ajustada con las filas de validación de un modelo y su
    banda sin calibrar (P50, P10, P90). `ventana` = (desde, hasta) que se informa; por defecto, la de las filas."""
    p, lo, hi = banda
    s = puntajes_conformal(p, lo, hi, filas["pasajeros"].to_numpy(float))
    ajuste = ajustar_calibracion_grupo(filas, s, grupos)
    desde, hasta = ventana or (filas["fecha"].min(), filas["fecha"].max())
    return {
        "version": "v2",
        "nombre": f"conformal de Mondrian por {' × '.join(grupos)}",
        "model_id": model_id,
        "metodo": "CQR de Mondrian (conformal partido por grupo)",
        "puntaje": CALIBRACION_PUNTAJE,
        "aplicacion": CALIBRACION_APLICACION,
        "grupos": list(grupos),
        "cobertura_objetivo": COBERTURA_OBJETIVO,
        "minimo_por_grupo": CALIBRACION_MIN_GRUPO,
        "ajustado_con": f"validación {desde} a {hasta} ({len(filas)} horas); la prueba reservada no se usa",
        "q": ajuste["q"],
        "n_por_grupo": ajuste["n"],
        "generado_en": datetime.now(ZONA).isoformat(timespec="seconds"),
        "script": script,
        "evidencia": evidencia,
    }


def escribir_calibracion(carpeta: Path, calibracion: dict, resumen: dict | None = None) -> dict:
    """calibracion_v2.json en la carpeta del modelo + su SHA-256 en manifest.json (clave «calibracion»). No toca el
    artefacto ni los ONNX: sus hashes quedan iguales (si cambiaran, se detiene sin escribir el manifiesto)."""
    archivo = carpeta / ARCHIVO_CALIBRACION
    archivo.write_text(json.dumps(calibracion, ensure_ascii=False, indent=1), encoding="utf-8")
    sha = _sha256(archivo)
    ruta_man = carpeta / ARCHIVO_MANIFIESTO
    man = json.loads(ruta_man.read_text(encoding="utf-8"))
    antes = (man["sha256"], json.dumps(man.get("onnx"), sort_keys=True))
    man["calibracion"] = {
        "version": calibracion["version"],
        "archivo": archivo.name,
        "sha256": sha,
        "nombre": calibracion["nombre"],
        "grupos": calibracion["grupos"],
        "ajustado_con": calibracion["ajustado_con"],
        "anterior": f"v1: conformal móvil (CQR) por ruta, {CONFORMAL_VENTANA_DIAS} días (clave «conformal»)",
        "registrado_en": calibracion["generado_en"],
        "resumen": resumen or {},
        "evidencia": calibracion["evidencia"],
    }
    if antes != (man["sha256"], json.dumps(man.get("onnx"), sort_keys=True)):
        raise RuntimeError("La calibración no puede cambiar el hash del artefacto ni el de los ONNX")
    ruta_man.write_text(json.dumps(man, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return {"version": calibracion["version"], "archivo": archivo.name, "sha256": sha,
            "grupos": calibracion["grupos"], "ajustado_con": calibracion["ajustado_con"]}


# ----------------------------------------------------------------------------------------------- explicación SHAP
def _explicador(modelo: dict):
    """shap.TreeExplainer del modelo de punto, creado una sola vez (solo versiones sin categóricas: SHAP exacto)."""
    if modelo.get("tipo") == "linea_base" or not modelo.get("shap_exacto"):
        return None
    if "_explicador" in modelo:
        return modelo["_explicador"]
    with _CANDADO_AUX:
        if "_explicador" not in modelo:
            try:
                import shap

                modelo["_explicador"] = shap.TreeExplainer(modelo.get("punto_sklearn", modelo["punto"]))
            except Exception:  # noqa: BLE001 - sin shap se usa la importancia global
                modelo["_explicador"] = None
    return modelo["_explicador"]


def explicar_filas(modelo: dict, filas: pd.DataFrame) -> dict | None:
    """Valores SHAP (escala log) por fila: base + suma(phi) = log(pronóstico). None si el modelo no es explicable."""
    ex = _explicador(modelo)
    if ex is None or len(filas) == 0:
        return None
    x = variables.matriz_x(filas, _version_modelo(modelo))
    with _CANDADO_AUX:
        sv = np.asarray(ex.shap_values(x), dtype=float)
        base = float(np.ravel(ex.expected_value)[0])
    return {"base_log": base, "phi": sv, "columnas": list(x.columns), "x": x.to_numpy(float)}


def _num_valor(v: float) -> float | None:
    return None if v is None or (isinstance(v, float) and math.isnan(v)) else round(float(v), 2)


_SIN_CALCULAR = object()   # explicación SHAP todavía no calculada (predecir la calcula; predecir_horas la trae en lote)


def _explicar_lote(modelo: dict, filas: pd.DataFrame) -> tuple[dict | None, str | None]:
    """SHAP de todas las filas en una llamada: (resultado de explicar_filas, error)."""
    try:
        return explicar_filas(modelo, filas), None
    except Exception as exc:  # noqa: BLE001 - la explicación nunca impide el pronóstico
        return None, str(exc)


def _rebanar_shap(e: dict | None, a: int, b: int) -> dict | None:
    if e is None:
        return None
    return {"base_log": e["base_log"], "phi": e["phi"][a:b], "columnas": e["columnas"], "x": e["x"][a:b]}


def _explicacion_local(modelo: dict, filas: pd.DataFrame, fr: np.ndarray, p: np.ndarray, i: int,
                       e=_SIN_CALCULAR, error: str | None = None) -> dict:
    """Las 5 variables que más mueven el pronóstico de la hora principal (fila i), con factor multiplicativo exacto.

    pronóstico_hora = base x producto(exp(phi)); efecto_pasajeros reparte (pronóstico - base) en proporción a phi
    (escala log), así que la suma de efectos (top 5 + resto) es exactamente pronóstico - base.
    """
    if modelo.get("tipo") == "linea_base":
        return {"metodo": "regla", "detalle": LINEAS_BASE[modelo["model_id"]]["descripcion"]}
    if e is _SIN_CALCULAR:
        e, error = _explicar_lote(modelo, filas)
    if error is not None:
        e = None
        motivo = f"SHAP falló: {error}"
    else:
        motivo = (
            "ruta_cod categórica nativa (fv1): TreeExplainer no es exacto; se muestra la importancia global por "
            "permutación del manifiesto"
            if not modelo.get("shap_exacto")
            else "SHAP no está disponible en este entorno; se muestra la importancia global por permutación"
        )
    if e is None:
        imp = (modelo.get("manifiesto") or {}).get("importancia_global") or []
        return {"metodo": "importancia_global_permutacion", "motivo": motivo, "importancia_global": imp[:5]}
    phi, base_log, cols, x = e["phi"], e["base_log"], e["columnas"], e["x"]
    base = math.exp(base_log)
    s_tot = float(phi[i].sum())
    pron = math.exp(base_log + s_tot)
    g = (math.expm1(s_tot) / s_tot) if abs(s_tot) > 1e-12 else 1.0
    orden = np.argsort(-np.abs(phi[i]))
    top = orden[:5]
    factores = [
        {
            "variable": cols[j],
            "descripcion": DESCRIPCION_VARIABLE.get(cols[j], cols[j]),
            "valor": _num_valor(x[i, j]),
            "phi_log": round(float(phi[i, j]), 6),
            "factor_multiplicativo": round(math.exp(float(phi[i, j])), 4),
            "efecto_pasajeros": round(base * g * float(phi[i, j]), 1),
        }
        for j in top
    ]
    resto = s_tot - float(phi[i, top].sum())
    w = fr * np.asarray(p, dtype=float)
    w = w / w.sum() if w.sum() > 0 else np.full(len(fr), 1.0 / max(len(fr), 1))
    agregado = (w[:, None] * phi).sum(axis=0)
    orden_v = np.argsort(-np.abs(agregado))[:5]
    frase = "; ".join(
        f"{f['descripcion'][0].upper() + f['descripcion'][1:]} "
        f"({_num(f['valor'], 0) if f['valor'] is not None else 's/d'})"
        f" {'sube' if f['factor_multiplicativo'] >= 1 else 'reduce'} ×{_num(f['factor_multiplicativo'])}"
        for f in factores[:3]
    )
    return {
        "metodo": "shap_tree_exacto",
        "hora": int(filas.iloc[i]["hora"]),
        "fecha": str(filas.iloc[i]["fecha"]),
        "base_pasajeros": round(base, 2),
        "pronostico_hora": round(pron, 2),
        "factores": factores,
        "factor_resto": round(math.exp(resto), 4),
        "efecto_resto_pasajeros": round(base * g * resto, 1),
        "error_reconstruccion_rel": float(abs(pron - float(p[i])) / max(pron, 1e-9)),
        "ventana_ponderada": [
            {"variable": cols[j], "factor_multiplicativo": round(math.exp(float(agregado[j])), 4)} for j in orden_v
        ],
        "frase": frase,
    }


# ----------------------------------------------------------------------------------------------- perfil intrahorario
@lru_cache(maxsize=2)
def _perfil(ruta_archivo: str, mtime: float) -> dict:
    p = datos.perfil_intrahorario()
    return {
        (str(r.ruta), int(r.tipo_dia), int(r.hora)): float(r.fraccion_primera_media)
        for r in p.itertuples()
        if not pd.isna(r.fraccion_primera_media)
    }


def perfil_intrahorario() -> dict:
    """{(ruta, tipo_dia, hora): fracción de las subidas de la hora en la primera media hora}; vacío si falta."""
    archivo = datos.carpeta_datos() / ARCHIVO_PERFIL
    return _perfil(str(archivo), datos.huella_archivo(ARCHIVO_PERFIL))


def fraccion_hora(ini_min: float, fin_min: float, primera_media: float = 0.5) -> float:
    """Fracción de la demanda de la hora en [ini_min, fin_min) (minutos 0-60), con densidad uniforme dentro de cada
    media hora: primera_media en [0, 30) y 1 - primera_media en [30, 60). Con 0,5 es el prorrateo por minutos."""
    a1 = max(0.0, min(fin_min, 30.0) - max(ini_min, 0.0))
    a2 = max(0.0, min(fin_min, 60.0) - max(ini_min, 30.0))
    return primera_media * a1 / 30.0 + (1.0 - primera_media) * a2 / 30.0


# ----------------------------------------------------------------------------------------------- predicción
def _a_bogota(instante: datetime | str) -> datetime:
    if isinstance(instante, str):
        instante = datetime.fromisoformat(instante)
    instante = pd.Timestamp(instante).to_pydatetime()
    if instante.tzinfo is None:
        return instante.replace(tzinfo=ZONA)
    return instante.astimezone(ZONA)


def _tipo_dia_tabla(tabla: pd.DataFrame | None, ruta: str, f: date, h: int) -> int:
    if tabla is not None:
        try:
            return int(tabla.at[(ruta, f, h), "tipo_dia"])
        except (KeyError, ValueError, TypeError):
            pass
    return datos.tipo_dia_de(f)


def _tramos(
    inicio: datetime, fin: datetime, ruta: str | None = None, tabla: pd.DataFrame | None = None
) -> list[tuple[date, int, float]]:
    """Horas (fecha, hora) que cruzan [inicio, fin) con la fracción de la demanda de la hora que cae en la ventana.

    Sin `ruta` (o sin perfil) la fracción es minutos / 60. Con `ruta` se usa el perfil intrahorario: la primera media
    hora lleva la fracción observada de subidas (por ruta, tipo de día y hora) y la segunda el resto.
    """
    perfil = perfil_intrahorario() if ruta is not None else {}
    out = []
    h = inicio.replace(minute=0, second=0, microsecond=0)
    while h < fin:
        sig = h + timedelta(hours=1)
        a = (max(h, inicio) - h).total_seconds() / 60.0
        b = (min(sig, fin) - h).total_seconds() / 60.0
        if b - a > 0:
            primera = 0.5
            if perfil and (a > 0 or b < 60):
                primera = perfil.get((ruta, _tipo_dia_tabla(tabla, ruta, h.date(), h.hour), h.hour), 0.5)
            out.append((h.date(), h.hour, fraccion_hora(a, b, primera)))
        h = sig
    return out


def _filas_variables(tabla: pd.DataFrame, ruta: str, tramos: list) -> pd.DataFrame:
    claves = [(ruta, f, h) for f, h, _ in tramos if h in datos.HORAS_SERVICIO]
    if not claves:
        return pd.DataFrame(columns=list(tabla.columns) + ["ruta", "fecha", "hora"])
    faltan = [c for c in claves if c not in tabla.index]
    if faltan:
        lo, hi = rango_tabla(tabla)
        raise ValueError(
            f"Sin variables para {faltan[0][1]} {faltan[0][2]}:00: el pronóstico cubre {lo} a {hi} "
            f"(rezagos de 7 días o más sobre {tabla.attrs.get('origen', 'la serie')})"
        )
    return tabla.loc[claves].reset_index()


def _num(x: float, dec: int = 2) -> str:
    """Número con coma decimal (es-CO)."""
    return f"{x:.{dec}f}".replace(".", ",")


def _observado(
    serie: pd.DataFrame | None, ruta: str, f: date, h: int, tabla: pd.DataFrame | None = None
) -> float | None:
    if serie is None and tabla is not None:
        try:
            v = tabla.at[(ruta, f, h), "pasajeros"]  # las horas excluidas ya vienen como faltantes
        except KeyError:
            return None
        return None if pd.isna(v) else float(v)
    if serie is None:
        serie = datos.demanda_horaria(desde=f, hasta=f, rutas=[ruta])
    fila = serie[(serie["ruta"] == ruta) & (serie["fecha"] == f) & (serie["hora"] == h)]
    if fila.empty or pd.isna(fila["pasajeros"].iloc[0]):
        return None
    if "excluido" in fila.columns and int(fila["excluido"].iloc[0]) == 1:
        return None
    return float(fila["pasajeros"].iloc[0])


def _tramos_cerrados(ruta: str, instante: datetime, tabla: pd.DataFrame) -> list[tuple[date, int, float]]:
    """Horas de servicio de las 2 h previas al instante que ya cerraron (sin fuga)."""
    inicio = instante - timedelta(hours=NOWCAST_VENTANA_H)
    return [
        (f, h, fr)
        for f, h, fr in _tramos(inicio, instante, ruta, tabla)
        if h in datos.HORAS_SERVICIO
        and datetime(f.year, f.month, f.day, h, tzinfo=ZONA) + timedelta(hours=1) <= instante
    ]


def _observado_y_esperado(
    ruta: str, tramos: list, modelo: dict, tabla: pd.DataFrame, serie_observada: pd.DataFrame | None
) -> tuple[float, float, list[dict]]:
    """Pasajeros observados y esperados (ponderados por la fracción de cada hora) en las horas cerradas con dato."""
    obs = esp = 0.0
    usados: list[dict] = []
    if not tramos:
        return obs, esp, usados
    try:
        filas = _filas_variables(tabla, ruta, tramos)
    except ValueError:
        return obs, esp, usados
    if not len(filas):
        return obs, esp, usados
    p = _predecir_punto(modelo, filas)
    for (f, h, fr), pe in zip(tramos, p, strict=False):
        o = _observado(serie_observada, ruta, f, h, tabla)
        if o is None:
            continue
        obs += fr * o
        esp += fr * float(pe)
        usados.append(
            {
                "fecha": str(f),
                "hora": h,
                "fraccion": round(fr, 3),
                "observado": o,
                "esperado": round(float(pe), 1),
            }
        )
    return obs, esp, usados


def factor_nowcast(
    ruta: str, instante: datetime, modelo: dict, tabla: pd.DataFrame, serie_observada: pd.DataFrame | None = None
) -> dict:
    """observado / esperado en las 2 h previas, solo con horas cerradas antes del instante (sin fuga)."""
    tramos = _tramos_cerrados(ruta, instante, tabla)
    peso = float((modelo.get("manifiesto") or {}).get("nowcast", {}).get("peso", NOWCAST_PESO_DEFECTO))
    obs, esp, usados = _observado_y_esperado(ruta, tramos, modelo, tabla, serie_observada)
    if usados and esp >= NOWCAST_MIN_ESPERADOS:
        crudo = obs / esp
        return {
            "factor": float(np.clip(1 + peso * (crudo - 1), NOWCAST_MIN, NOWCAST_MAX)),
            "razon_cruda": round(crudo, 4),
            "peso": peso,
            "observado_2h": round(obs, 1),
            "esperado_2h": round(esp, 1),
            "horas": usados,
            "aplicado": True,
        }
    return {
        "factor": 1.0,
        "razon_cruda": None,
        "observado_2h": round(obs, 1),
        "esperado_2h": round(esp, 1),
        "horas": usados,
        "aplicado": False,
        "peso": peso,
    }


def _nowcast_neutro() -> dict:
    """Factor intradía 1 cuando se pide el pronóstico sin nowcast."""
    return {
        "factor": 1.0,
        "aplicado": False,
        "observado_2h": None,
        "esperado_2h": None,
        "horas": [],
        "razon_cruda": None,
        "peso": None,
    }


def _ruta_y_horizonte(ruta: str, horizonte_min: int) -> str:
    """Valida el horizonte (30, 60 o 120 min) y devuelve el nombre canónico de la ruta."""
    if int(horizonte_min) not in HORIZONTES:
        raise ValueError(f"horizonte_min debe ser uno de {HORIZONTES}")
    try:
        return datos.ruta_info(ruta)["ruta"]
    except KeyError as exc:
        raise ValueError(str(exc)) from exc


def _banda_de_filas(modelo: dict, ruta: str, fecha: date, filas: pd.DataFrame, pred: tuple | None = None) -> tuple:
    """(P50, P10 y P90 del modelo por hora, detalle de la calibración, q) de las horas de servicio de la ventana.
    `pred` = (P50, P10, P90) ya calculados en lote (predecir_horas); si no, se predicen aquí."""
    if not len(filas):
        vacio = np.zeros(0)
        conf = {"aplicado": False, "q": None, "motivo": "fuera de servicio", "cobertura_objetivo": COBERTURA_OBJETIVO,
                "version": None}
        return vacio, vacio, vacio, conf, None
    p, lo_m, hi_m = _predecir_filas(modelo, filas) if pred is None else pred
    try:   # v2 (por grupo, versionada con el modelo) o v1 (conformal móvil por ruta)
        conf, q_banda = calibrar_filas(modelo, ruta, fecha, filas)
    except Exception as exc:  # noqa: BLE001 - la calibración nunca debe impedir el pronóstico
        LOG.warning("conformal no disponible para %s %s: %s", ruta, fecha, exc)
        conf = {"aplicado": False, "q": None, "motivo": f"calibración no disponible: {exc}", "version": None,
                "cobertura_objetivo": COBERTURA_OBJETIVO, "ventana_dias": CONFORMAL_VENTANA_DIAS}
        q_banda = None
    return p, lo_m, hi_m, conf, q_banda


def _sin_dato(v, dec: int | None = None) -> float | None:
    if pd.isna(v):
        return None
    return float(v) if dec is None else round(float(v), dec)


def _hora_principal(filas: pd.DataFrame, fr: np.ndarray, inst: datetime) -> dict:
    """Variables de la hora que más pesa en la ventana (o la marca de fuera de servicio)."""
    if not len(filas):
        return {"hora": inst.hour, "dia_semana": DIAS[inst.weekday()], "fuera_de_servicio": True}
    r = filas.iloc[int(np.argmax(fr))]
    return {
        "fecha": str(r["fecha"]),
        "hora": int(r["hora"]),
        "dia_semana": DIAS[int(r["dia_semana"])],
        "tipo_dia": datos.TIPOS_DIA[int(r["tipo_dia"])],
        "festivo": bool(r["festivo"]),
        "lag7": _sin_dato(r["lag7"]),
        "b8_regla_manual": _sin_dato(r["b8"], 1),
        "nivel_7_34": _sin_dato(r["nivel_7_34"], 1),
    }


def _frases_hora(principal: dict, hay_filas: bool) -> list[str]:
    if not hay_filas:
        return ["La ventana cae fuera del horario de salidas (4-20 h): demanda 0"]
    frases = [
        f"Hora {principal['hora']}:00 del {principal['dia_semana']} ({principal['tipo_dia'].lower()}"
        f"{', festivo' if principal['festivo'] else ''})"
    ]
    if principal["lag7"] is not None:
        frases.append(f"Misma hora hace 7 días: {principal['lag7']:.0f} pasajeros")
    if principal["b8_regla_manual"] is not None:
        frases.append(f"Regla manual (media de 8 semanas): {principal['b8_regla_manual']:.0f} pasajeros")
    return frases


def _frase_nowcast(nc: dict, k: float) -> str:
    if not nc["aplicado"]:
        return "Sin observaciones suficientes en las 2 h previas: factor intradía 1,00"
    return (
        f"Factor intradía {_num(k)}: observado {nc['observado_2h']:.0f} frente a esperado "
        f"{nc['esperado_2h']:.0f} en las 2 h previas (razón {_num(nc['razon_cruda'])}, peso "
        f"{_num(nc['peso'], 1)}, recortado a {_num(NOWCAST_MIN, 1)}-{_num(NOWCAST_MAX)})"
    )


def _frase_ventana(horizonte_min: int, con_perfil: bool, horas_servicio: int) -> str:
    reparto = "con el perfil intrahorario (subidas por media hora, 2024)" if con_perfil else "por minutos"
    return f"Ventana de {int(horizonte_min)} min repartida {reparto} sobre {horas_servicio} hora(s) de servicio"


def _frase_banda(conf: dict, lo_modelo: float, hi_modelo: float) -> str:
    """Cómo se calibró la banda P10-P90 (v2 por grupo, v1 conformal móvil o sin calibrar)."""
    if conf.get("aplicado") and conf.get("q_por_hora"):
        return (
            f"Banda P10-P90 calibrada ({conf['metodo']}, versión {conf['version']}, {conf['ajustado_con']}): "
            f"ajuste {_num(conf['q'], 3)} x pronóstico en la hora principal; banda del modelo "
            f"{lo_modelo:.0f}-{hi_modelo:.0f}"
        )
    if conf.get("aplicado"):
        return (
            f"Banda P10-P90 calibrada (conformal móvil de {CONFORMAL_VENTANA_DIAS} días, {conf['dias_calibracion']}"
            f" días fuera de muestra): ajuste {_num(conf['q'], 3)} x pronóstico; banda del modelo "
            f"{lo_modelo:.0f}-{hi_modelo:.0f}"
        )
    return f"Banda P10-P90 del modelo sin calibrar: {conf.get('motivo')}"


def _frases_modelo(expl_local: dict | None, modelo: dict) -> list[str]:
    frases = []
    if expl_local and expl_local.get("metodo") == "shap_tree_exacto":
        frases.append(
            f"Explicación local (SHAP) de la hora {expl_local['hora']}:00: base {expl_local['base_pasajeros']:.0f} "
            f"pasajeros; {expl_local['frase']}"
        )
    imp = (modelo.get("manifiesto") or {}).get("importancia_global") or []
    if imp:
        frases.append("Variables más influyentes del modelo: " + ", ".join(x["variable"] for x in imp[:3]))
    return frases


def _detalle_por_hora(servicio: list, p, lo, hi, lo_m, hi_m) -> list[dict]:
    return [
        {
            "fecha": str(f),
            "hora": h,
            "fraccion": round(x, 3),
            "pasajeros_hora": round(float(a), 1),
            "p10_hora": round(float(b), 1),
            "p90_hora": round(float(c), 1),
            "p10_modelo_hora": round(float(bm), 1),
            "p90_modelo_hora": round(float(cm), 1),
        }
        for (f, h, x), a, b, c, bm, cm in zip(servicio, p, lo, hi, lo_m, hi_m, strict=False)
    ]


def predecir(
    ruta: str,
    instante: datetime,
    horizonte_min: int,
    model_id: str | None = None,
    *,
    usar_nowcast: bool = True,
    serie_observada: pd.DataFrame | None = None,
    dir_modelos: Path | None = None,
) -> dict:
    """Pasajeros esperados en [instante, instante + horizonte] para la ruta, con P10/P90 y explicación.

    Campos añadidos (el contrato anterior no cambia): p10_modelo / p90_modelo (banda sin calibrar), ajuste_conformal
    (q), cobertura_objetivo, explicacion_local (SHAP) y, en variables, el detalle conformal y la explicación local.
    """
    t0 = time.perf_counter()
    ruta = _ruta_y_horizonte(ruta, horizonte_min)
    modelo = cargar(model_id, dir_modelos)
    tabla = tabla_variables()
    v = _ventana(ruta, _a_bogota(instante), horizonte_min, tabla)
    banda = _banda_de_filas(modelo, ruta, v["inst"].date(), v["filas"])
    nc = factor_nowcast(ruta, v["inst"], modelo, tabla, serie_observada) if usar_nowcast else _nowcast_neutro()
    r = _resultado(ruta, horizonte_min, modelo, v, banda, nc)
    r["latencia_ms"] = round((time.perf_counter() - t0) * 1000, 2)
    return r


def predecir_horas(
    ruta: str,
    inicios,
    model_id: str | None = None,
    *,
    horizonte_min: int = 60,
    usar_nowcast: bool = False,
    serie_observada: pd.DataFrame | None = None,
    dir_modelos: Path | None = None,
    sesion=None,
) -> list[dict]:
    """predecir() para varios instantes de una ruta en un solo lote: arma las filas de todas las ventanas, llama una
    vez a los tres modelos y a SHAP, calibra por fila y devuelve, en el orden de `inicios`, los mismos diccionarios que
    predecir(ruta, inicio, horizonte_min, model_id, usar_nowcast=...) (latencia_ms es la del lote repartida).
    Por defecto es la hora de servicio que empieza en cada inicio (60 min, sin factor intradía), como el contexto de las
    alertas observadas y el plan del día. Con `sesion` usa la serie validada de esa sesión."""
    if sesion is not None:
        with con_sesion(sesion):
            return predecir_horas(ruta, inicios, model_id, horizonte_min=horizonte_min, usar_nowcast=usar_nowcast,
                                  serie_observada=serie_observada, dir_modelos=dir_modelos)
    t0 = time.perf_counter()
    ruta = _ruta_y_horizonte(ruta, horizonte_min)
    modelo = cargar(model_id, dir_modelos)
    tabla = tabla_variables()
    ventanas = [_ventana(ruta, _a_bogota(i), horizonte_min, tabla) for i in inicios]
    con_filas = [v["filas"] for v in ventanas if len(v["filas"])]
    pred = e_lote = error = None
    if con_filas:
        todas = pd.concat(con_filas, ignore_index=True)
        pred = _predecir_filas(modelo, todas)
        if modelo.get("tipo") != "linea_base":
            e_lote, error = _explicar_lote(modelo, todas)
    salida, a = [], 0
    for v in ventanas:
        b = a + len(v["filas"])
        trozo = None if pred is None or b == a else tuple(x[a:b] for x in pred)
        banda = _banda_de_filas(modelo, ruta, v["inst"].date(), v["filas"], trozo)
        nc = factor_nowcast(ruta, v["inst"], modelo, tabla, serie_observada) if usar_nowcast else _nowcast_neutro()
        salida.append(_resultado(ruta, horizonte_min, modelo, v, banda, nc, shap=(_rebanar_shap(e_lote, a, b), error)))
        a = b
    latencia = round((time.perf_counter() - t0) * 1000 / max(len(salida), 1), 2)
    for r in salida:
        r["latencia_ms"] = latencia
    return salida


def _ventana(ruta: str, inst: datetime, horizonte_min: int, tabla: pd.DataFrame) -> dict:
    """Horas que cruzan [inst, inst + horizonte] con su fracción, y las variables de las horas de servicio."""
    fin = inst + timedelta(minutes=int(horizonte_min))
    tramos = _tramos(inst, fin, ruta, tabla)
    return {"inst": inst, "fin": fin, "filas": _filas_variables(tabla, ruta, tramos),
            "servicio": [(f, h, fr) for f, h, fr in tramos if h in datos.HORAS_SERVICIO]}


def _resultado(ruta: str, horizonte_min: int, modelo: dict, v: dict, banda: tuple, nc: dict,
               shap: tuple | None = None) -> dict:
    """Diccionario de predecir() a partir de la ventana, la banda del modelo calibrada y el factor intradía.
    `shap` = (explicación SHAP de las filas de la ventana, error) cuando ya se calculó en lote."""
    inst, fin, filas, servicio = v["inst"], v["fin"], v["filas"], v["servicio"]
    hay_filas = len(filas) > 0
    p, lo_m, hi_m, conf, q_banda = banda
    lo, hi = aplicar_conformal(p, lo_m, hi_m, q_banda)
    fr = np.array([x[2] for x in servicio], dtype=float)
    if conf.get("q_por_hora") and len(fr):   # v2: el ajuste que se informa es el de la hora principal de la ventana
        conf["q"] = conf["q_por_hora"][int(np.argmax(fr))]
    base, base_lo, base_hi = float((fr * p).sum()), float((fr * lo).sum()), float((fr * hi).sum())
    base_lo_m, base_hi_m = float((fr * lo_m).sum()), float((fr * hi_m).sum())
    k = nc["factor"]

    principal = _hora_principal(filas, fr, inst)
    con_perfil = bool(perfil_intrahorario())
    explicacion = _frases_hora(principal, hay_filas)
    explicacion.append(_frase_nowcast(nc, k))
    explicacion.append(_frase_ventana(horizonte_min, con_perfil, len(servicio)))
    if hay_filas:
        explicacion.append(_frase_banda(conf, base_lo_m * k, base_hi_m * k))
    expl_local = None
    if hay_filas:
        e, error = shap if shap is not None else (_SIN_CALCULAR, None)
        expl_local = _explicacion_local(modelo, filas, fr, p, int(np.argmax(fr)), e, error)
    explicacion += _frases_modelo(expl_local, modelo)

    por_hora = _detalle_por_hora(servicio, p, lo, hi, lo_m, hi_m)
    conformal = dict(conf)
    return {
        "ruta": ruta,
        "instante": inst,
        "horizonte_min": int(horizonte_min),
        "ventana_inicio": inst,
        "ventana_fin": fin,
        "pasajeros": round(base * k, 2),
        "p10": round(base_lo * k, 2),
        "p90": round(base_hi * k, 2),
        "p10_modelo": round(base_lo_m * k, 2),
        "p90_modelo": round(base_hi_m * k, 2),
        "ajuste_conformal": conf.get("q"),
        "cobertura_objetivo": COBERTURA_OBJETIVO,
        "calibracion_version": conf.get("version"),
        "pasajeros_sin_ajuste": round(base, 2),
        "model_id": modelo["model_id"],
        "tipo_modelo": modelo["tipo"],
        "feature_version": modelo["feature_version"],
        "data_cutoff": modelo["data_cutoff"],
        "generated_at": datetime.now(UTC),
        "latencia_ms": None,   # lo pone predecir() o predecir_horas()
        "explicacion": explicacion,
        "explicacion_local": expl_local,
        "variables": dict(
            principal,
            factor_nowcast=round(k, 4),
            nowcast_aplicado=nc["aplicado"],
            observado_2h=nc["observado_2h"],
            esperado_2h=nc["esperado_2h"],
            razon_cruda=nc["razon_cruda"],
            horas_nowcast=nc["horas"],
            por_hora=por_hora,
            perfil_intrahorario=con_perfil,
            p10_modelo=round(base_lo_m * k, 2),
            p90_modelo=round(base_hi_m * k, 2),
            conformal=conformal,
            calibracion_version=conf.get("version"),
            explicacion_local=expl_local,
        ),
    }


# ----------------------------------------------------------------------------------------------- evaluación
def importancia(model_id: str | None = None, dir_modelos: Path | None = None) -> dict:
    """Importancia global del modelo: permutación (aumento del MAE) y, en fv2, media de |SHAP| (para GET importance)."""
    modelo = cargar(model_id, dir_modelos)
    man = modelo.get("manifiesto") or {}
    return {
        "model_id": modelo["model_id"],
        "feature_version": modelo["feature_version"],
        "permutacion": man.get("importancia_global") or [],
        "nota_permutacion": man.get("nota_importancia"),
        "shap": man.get("explicabilidad") or {"shap_local": False, "motivo": "modelo sin artefacto (línea base)"},
    }


def evaluacion_registrada(model_id: str | None = None, dir_modelos: Path | None = None) -> dict:
    """Evaluación guardada en el manifiesto por scripts/evaluar_modelo.py (para GET evaluation); {} si no la hay."""
    modelo = cargar(model_id, dir_modelos)
    man = modelo.get("manifiesto") or {}
    return {"model_id": modelo["model_id"], "metricas_entrenamiento": man.get("metricas"),
            "evaluacion": man.get("evaluacion") or {}}


def evaluar(model_id: str | None, desde: date, hasta: date, dir_modelos: Path | None = None, *,
            sesion=None, rutas: list[str] | None = None) -> dict:
    """Métricas del modelo (o de una línea base) sobre los datos reales entre desde y hasta. Con `sesion` (o dentro
    de con_sesion) los valores reales y las variables son los de la serie validada (lo que llegó y pasó la calidad).
    Con `rutas`, solo las filas de esas rutas (el trabajo de una ruta de una ejecución partida, RNF-005): cada fila se
    pronostica sola, así que las métricas de una ruta son las mismas que en la evaluación de todas."""
    if sesion is not None:
        with con_sesion(sesion):
            return evaluar(model_id, desde, hasta, dir_modelos, rutas=rutas)
    modelo = cargar(model_id, dir_modelos)
    desde, hasta = pd.Timestamp(desde).date(), pd.Timestamp(hasta).date()
    tabla = tabla_variables()
    t = _filas_utiles(tabla)
    t = t[(t["fecha"] >= desde) & (t["fecha"] <= hasta)]
    if rutas:
        t = t[t["ruta"].isin(list(rutas))]
    if t.empty:
        raise ValueError(f"No hay datos reales entre {desde} y {hasta}")
    p, lo, hi = _predecir_filas(modelo, t)
    m = metricas(t["pasajeros"], p, horas=t["hora"].to_numpy(), rutas=t["ruta"].to_numpy(), p10=lo, p90=hi)
    try:  # cobertura con la banda calibrada (conformal móvil, solo días anteriores a cada día evaluado)
        claves = list(dict.fromkeys(zip(t["ruta"], t["fecha"], strict=False)))
        _puntajes_conformal(modelo)
        qs = cuantiles_conformal_movil(modelo["_indice_conformal"], claves)
        q = np.array([qs[(r, f)]["q"] if qs[(r, f)]["q"] is not None else np.nan
                      for r, f in zip(t["ruta"], t["fecha"], strict=False)], dtype=float)
        ok = ~np.isnan(q)
        esc = np.maximum(p, 1.0)
        lo_c = np.where(ok, np.clip(np.minimum(lo - np.nan_to_num(q) * esc, p), 0, None), lo)
        hi_c = np.where(ok, np.maximum(hi + np.nan_to_num(q) * esc, p), hi)
        y = t["pasajeros"].to_numpy(float)
        cubre_v1 = round(float(((y >= lo_c) & (y <= hi_c)).mean() * 100), 2)
        m["calibracion_version"] = "v1"
        if modelo.get("calibracion"):   # v2 versionada con el modelo (la que usa predecir); v1 queda como referencia
            m["cobertura_p10_p90_conformal_v1"] = cubre_v1
            lo_c, hi_c = aplicar_conformal(p, lo, hi, q_calibracion(modelo["calibracion"], t)[0])
            ok = np.ones(len(t), dtype=bool)
            m["calibracion_version"] = modelo["calibracion"]["version"]
        m["cobertura_p10_p90_conformal"] = round(float(((y >= lo_c) & (y <= hi_c)).mean() * 100), 2)
        m["horas_con_ajuste_conformal_pct"] = round(float(ok.mean() * 100), 2)
    except Exception as exc:  # noqa: BLE001 - la cobertura calibrada es informativa
        LOG.warning("evaluar: sin cobertura conformal: %s", exc)
    m.update(
        {
            "model_id": modelo["model_id"],
            "desde": desde,
            "hasta": hasta,
            "fuera_de_muestra": modelo["data_cutoff"] is None or desde > modelo["data_cutoff"],
            "origen_datos": tabla.attrs.get("origen"),
        }
    )
    return m
