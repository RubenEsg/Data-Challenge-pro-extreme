"""Modelo supervisado de la demanda por segmento y sentido (§3.1 «Predicción de demanda: por ruta, sentido, segmento y
franja horaria → pronóstico e intervalo de confianza», §9.1, §9.2, §9.3 y §7.3 paso 4).

Qué pronostica: la FRACCIÓN de las subidas de la ruta que cae en cada segmento en una hora (fecha, hora de salida). El
pronóstico de un segmento es esa fracción por el pronóstico de la ruta (modelo activo, con su banda calibrada), hora
por hora de la ventana; el de un sentido es la suma de sus segmentos. La fracción se normaliza a 1 en cada hora, así
que la suma de los segmentos es exactamente el pronóstico de la ruta.

Modelos (registro propio en datos/modelos/segmentos/registro.json; cada uno con artefacto, manifest.json y SHA-256,
que cargar() verifica antes de usarlo, §9.2):
- reparto fijo (línea base B0): fracción histórica por (ruta, tipo de día, hora) con respaldo (ruta, tipo de día) y
  (ruta) si la celda tiene menos de MIN_SUBIDAS subidas (la regla de scripts/preparar_segmentos.py).
- HGB Poisson con desplazamiento: gradient boosting con pérdida de Poisson sobre las subidas del segmento con el total
  de la ruta como exposición. «hgb_offset_reparto» usa log(T · fracción B0) (aprende una corrección multiplicativa del
  reparto) y «hgb_offset_total» usa log(T) (aprende la fracción). HistGradientBoostingRegressor no acepta
  desplazamiento: se ajusta y / e con peso e, que tiene la misma devianza de Poisson que y con offset log e.
- Jerárquicos: fracción del sentido × reparto dentro del sentido (el de «hgb_offset_total» normalizado en cada
  sentido). «hgb_dentro_del_sentido» toma la fracción del sentido de B0; «hgb_jerarquico» la toma de un segundo HGB
  Poisson por hora y sentido (exposición T · fracción B0 del sentido, COLUMNAS_SENTIDO, HIPER_SENTIDO).
Variables (VERSION_VARIABLES): ruta, número y posición del segmento en el ciclo, sentido, hora, tipo de día, día de la
semana, festivo, vacaciones, Carnaval, la fracción B0 y las subidas de su celda. Todas se conocen antes del día
pronosticado: el calendario es el de la serie y la fracción B0 sale del periodo de ajuste. En las filas de
entrenamiento la fracción B0 se calcula fuera de pliegue (pliegues de DIAS_PLIEGUE días) para que tenga el mismo
ruido que fuera de muestra.

Banda P10-P90: conformal de Mondrian por tramo de la demanda esperada μ = T · f (CORTES_MU), puntaje
s = (y − μ) / √(μ + 1), cuantiles 10 % y 90 % con la corrección de muestra finita, ajustados en la validación, por
separado para segmento y sentido. Con el pronóstico de la ruta (P10, P50, P90) se compone en cuadratura (supuesto de
independencia entre el error de la ruta y el del reparto): μ̂ = f · P50 y semiancho √((f (P50 − P10))² + (q √(μ̂+1))²).

Sentido: aproximación geométrica (supuesto S9; las exportaciones no traen sentido). Partición, regla de elección y
resultados: docs/evidencias/modelo/segmentos_protocolo.md y segmentos_modelo.md (scripts/entrenar_segmentos.py).
"""
from __future__ import annotations

import hashlib
import json
import math
import threading
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

from . import datos, variables

VERSION_VARIABLES = "sv1-2026-11-09"
CALENDARIO = ("tipo_dia", "dia_semana", "festivo", "vacaciones", "carnaval")
COLUMNAS = ["ruta_cod", "nro_segmento", "pos_rel", "sentido_cod", "hora", *CALENDARIO, "log_fraccion_base",
            "log_subidas_celda"]
CLAVES_CELDA = ["ruta", "tipo_dia", "hora"]
CLAVES_HORA = ["ruta", "fecha", "hora"]
MIN_SUBIDAS = 200
FRACCION_MIN = 1e-6
DIAS_PLIEGUE = 7
SENTIDOS = {"ida": 0, "regreso": 1}
TIPO_REPARTO = "reparto_fijo"
TIPO_OFFSET_REPARTO = "hgb_offset_reparto"
TIPO_OFFSET_TOTAL = "hgb_offset_total"
TIPO_DENTRO_SENTIDO = "hgb_dentro_del_sentido"
TIPO_JERARQUICO = "hgb_jerarquico"
TIPOS = (TIPO_REPARTO, TIPO_OFFSET_REPARTO, TIPO_OFFSET_TOTAL, TIPO_DENTRO_SENTIDO, TIPO_JERARQUICO)
HIPER_DEFECTO = {"learning_rate": 0.05, "max_iter": 300, "max_leaf_nodes": 31, "min_samples_leaf": 100,
                 "l2_regularization": 1.0}
# Modelo del sentido (solo hgb_jerarquico): una fila por hora y sentido, árboles chicos (pocas filas)
COLUMNAS_SENTIDO = ["ruta_cod", "sentido_cod", "hora", *CALENDARIO, "log_fraccion_base"]
HIPER_SENTIDO = {"learning_rate": 0.05, "max_iter": 100, "max_leaf_nodes": 7, "min_samples_leaf": 200,
                 "l2_regularization": 1.0}
SEMILLA = 42
# Partición cronológica fijada antes de mirar la prueba (docs/evidencias/modelo/segmentos_protocolo.md)
PARTICION = {"entrenamiento": (date(2023, 1, 1), date(2023, 2, 8)),
             "validacion": (date(2023, 2, 9), date(2023, 2, 17)),
             "prueba": (date(2023, 2, 18), date(2023, 2, 27))}
REGLA_ELECCION = {"bootstrap_replicas": 1000, "semilla": SEMILLA, "nivel_ic": 0.95,
                  "tolerancia_wape_sentido_pp": 0.25,
                  "texto": "elegible si mejora el WAPE por segmento y hora de B0 con el IC95 bootstrap por días de la "
                           "validación por debajo de 0 y no empeora el WAPE por sentido y hora en más de 0,25 pp; gana "
                           "el elegible de menor WAPE; sin elegibles sigue B0. Salvaguarda: si el elegido es peor que "
                           "B0 en la prueba, no se activa."}
COBERTURA_OBJETIVO = 0.80
CORTES_MU = (1.0, 3.0, 10.0, 30.0, 100.0, 300.0, 1000.0)
MIN_GRUPO_BANDA = 50
METODO_BANDA = ("conformal de Mondrian por tramo de μ = T·f, puntaje (y − μ)/√(μ + 1), cuantiles 10 % y 90 % con "
                "corrección de muestra finita; compuesta en cuadratura con la banda P10-P90 de la ruta")
ARCHIVO_ARTEFACTO = "modelo.joblib"
ARCHIVO_MANIFIESTO = "manifest.json"
ARCHIVO_REGISTRO = "registro.json"
CLAVES_REGISTRO = ("model_id", "tipo", "estado", "artefacto", "sha256", "feature_version", "periodo_datos",
                   "semilla", "metricas_validacion", "metricas_prueba", "creado_en")
_CACHE: dict[str, dict] = {}
_CANDADO = threading.Lock()


DESCRIPCIONES = {
    TIPO_REPARTO: "reparto fijo B0: fracción histórica de subidas por ruta, tipo de día y hora",
    TIPO_OFFSET_REPARTO: "HGB Poisson con exposición T · fracción B0 (corrección multiplicativa del reparto)",
    TIPO_OFFSET_TOTAL: "HGB Poisson con exposición T (fracción del segmento)",
    TIPO_DENTRO_SENTIDO: "fracción del sentido de B0 × reparto dentro del sentido de un HGB Poisson",
    TIPO_JERARQUICO: "fracción del sentido de un HGB Poisson por hora y sentido × reparto dentro del sentido de un HGB "
                     "Poisson"}


class ModeloSegmentosNoEncontrado(LookupError):
    """El model_id no está en el registro de segmentos, o falta su manifiesto."""


class RutaSinSegmentos(LookupError):
    """El modelo de segmentos no tiene segmentos para la ruta pedida."""


class ErrorModeloSegmentos(RuntimeError):
    """No hay modelo de segmentos activo, o su artefacto no pasa la verificación (SHA-256 o versión de variables)."""


# ----------------------------------------------------------------------------------------------- reparto fijo (B0)
def _sumas(celdas: pd.DataFrame, claves: list[str], nombre: str) -> pd.Series:
    return celdas.groupby(claves)["subidas"].sum().rename(nombre)


def fracciones_base(celdas: pd.DataFrame, segmentos: pd.DataFrame,
                    objetivo: pd.DataFrame | None = None) -> pd.DataFrame:
    """Reparto fijo B0 (§9.1 línea base) por (ruta, tipo_dia, hora, id_segmento): fracción de las subidas de la celda
    con respaldo (ruta, tipo de día) y (ruta) si la celda tiene menos de MIN_SUBIDAS; suma 1 en cada celda.

    `celdas` (ruta, tipo_dia, hora, id_segmento, subidas) es el periodo de ajuste; `objetivo`, las celdas (ruta,
    tipo_dia, hora) que se codifican (por omisión, las de `celdas`). Columnas: fraccion, nivel, subidas_celda."""
    cel = (celdas if objetivo is None else objetivo)[CLAVES_CELDA].drop_duplicates()
    b = cel.merge(segmentos[["ruta", "id_segmento"]], on="ruta")
    seg = ["id_segmento"]
    for nombre, claves in (("s3", CLAVES_CELDA + seg), ("t3", CLAVES_CELDA), ("s2", ["ruta", "tipo_dia", *seg]),
                           ("t2", ["ruta", "tipo_dia"]), ("s1", ["ruta", *seg]), ("t1", ["ruta"])):
        b = b.join(_sumas(celdas, claves, nombre), on=claves)
    b = b.fillna({"s3": 0.0, "t3": 0.0, "s2": 0.0, "t2": 0.0, "s1": 0.0, "t1": 0.0})
    nivel = np.where(b["t3"] >= MIN_SUBIDAS, "ruta_tipo_dia_hora",
                     np.where(b["t2"] >= MIN_SUBIDAS, "ruta_tipo_dia", "ruta"))
    frac = np.where(nivel == "ruta_tipo_dia_hora", b["s3"] / b["t3"].where(b["t3"] > 0),
                    np.where(nivel == "ruta_tipo_dia", b["s2"] / b["t2"].where(b["t2"] > 0),
                             b["s1"] / b["t1"].where(b["t1"] > 0)))
    b["fraccion"] = pd.Series(frac, index=b.index).fillna(0.0)
    suma = b.groupby(CLAVES_CELDA)["fraccion"].transform("sum")
    n_seg = b.groupby(CLAVES_CELDA)["fraccion"].transform("size")
    b["fraccion"] = np.where(suma > 0, b["fraccion"] / suma.where(suma > 0, 1.0), 1.0 / n_seg)
    b["nivel"] = nivel
    b["subidas_celda"] = b["t3"].astype(int)
    return b[[*CLAVES_CELDA, "id_segmento", "fraccion", "nivel", "subidas_celda"]]


def pliegues(fechas, inicio: date, dias: int = DIAS_PLIEGUE) -> np.ndarray:
    """Pliegue de cada fecha: bloques de `dias` días corridos desde `inicio` (codificación fuera de pliegue)."""
    f = pd.to_datetime(pd.Series(fechas)).dt.normalize()
    return ((f - pd.Timestamp(inicio)).dt.days // int(dias)).to_numpy(dtype=int)


def codificar_fuera_de_pliegue(celdas: pd.DataFrame, segmentos: pd.DataFrame, inicio: date,
                               dias: int = DIAS_PLIEGUE) -> pd.DataFrame:
    """Fracción B0 de las celdas de cada pliegue calculada SIN las fechas de ese pliegue (columna «pliegue»): así la
    variable tiene en el entrenamiento el ruido que tiene fuera de muestra."""
    pl = pliegues(celdas["fecha"], inicio, dias)
    partes = [fracciones_base(celdas[pl != k], segmentos, objetivo=celdas[pl == k]).assign(pliegue=k)
              for k in sorted(set(pl.tolist()))]
    return pd.concat(partes, ignore_index=True)


# ----------------------------------------------------------------------------------------------- malla y variables
def calendario_serie(desde: date | None = None, hasta: date | None = None) -> pd.DataFrame:
    """Calendario por fecha de la serie empaquetada (tipo de día, día de la semana, festivo, vacaciones, Carnaval)."""
    d = datos.demanda_horaria(desde=desde, hasta=hasta)
    cal = d.groupby("fecha", as_index=False)[["tipo_dia", "festivo", "vacaciones", "carnaval"]].max()
    cal["dia_semana"] = pd.to_datetime(cal["fecha"]).dt.dayofweek
    return cal[["fecha", *CALENDARIO]].astype({c: int for c in CALENDARIO})


def malla(celdas: pd.DataFrame, segmentos: pd.DataFrame) -> pd.DataFrame:
    """Cada hora (ruta, fecha, hora) con subidas, cruzada con TODOS los segmentos de su ruta: y = subidas del segmento
    (0 si no hubo) y total = T, el total de la ruta en esa hora."""
    tot = (celdas.groupby([*CLAVES_HORA, "tipo_dia"], as_index=False)["subidas"].sum()
           .rename(columns={"subidas": "total"}))
    tot = tot[tot["total"] > 0]
    m = tot.merge(segmentos[["ruta", "id_segmento", "nro_segmento", "sentido", "pos_rel"]], on="ruta")
    y = celdas.groupby([*CLAVES_HORA, "id_segmento"])["subidas"].sum().rename("y")
    return m.join(y, on=[*CLAVES_HORA, "id_segmento"]).fillna({"y": 0.0})


def matriz(m: pd.DataFrame, codificacion: pd.DataFrame) -> pd.DataFrame:
    """Une la fracción B0 (por pliegue si la codificación lo trae) y arma las COLUMNAS del modelo (preprocesamiento
    único para entrenar, evaluar e inferir, §9.2). `m` trae ruta, hora, id_segmento, nro_segmento, sentido, pos_rel y
    el CALENDARIO."""
    claves = [*CLAVES_CELDA, "id_segmento", *(["pliegue"] if "pliegue" in codificacion.columns else [])]
    x = m.merge(codificacion[[*claves, "fraccion", "subidas_celda", "nivel"]], on=claves, how="left")
    x = x.rename(columns={"fraccion": "fraccion_base"}).fillna({"fraccion_base": 0.0, "subidas_celda": 0,
                                                                "nivel": "sin_reparto"})
    x["ruta_cod"] = x["ruta"].map(variables.CODIGO_RUTA).fillna(-1).astype(int)
    x["sentido_cod"] = x["sentido"].map(SENTIDOS).fillna(0).astype(int)
    x["log_fraccion_base"] = np.log(np.maximum(x["fraccion_base"].to_numpy(float), FRACCION_MIN))
    x["log_subidas_celda"] = np.log1p(x["subidas_celda"].to_numpy(float))
    return x


# ----------------------------------------------------------------------------------------------- ajuste y predicción
def exposicion(tipo: str, x: pd.DataFrame) -> np.ndarray:
    """Exposición e del modelo Poisson: T · fracción B0 (offset_reparto) o T (offset_total)."""
    t = x["total"].to_numpy(float)
    if tipo == TIPO_OFFSET_REPARTO:
        return t * np.maximum(x["fraccion_base"].to_numpy(float), FRACCION_MIN)
    return t


def _poisson(x: pd.DataFrame, columnas: list[str], e: np.ndarray, hiper: dict, semilla: int):
    """HGB con pérdida de Poisson: objetivo y / e con peso e (equivale a y con offset log e)."""
    reg = HistGradientBoostingRegressor(loss="poisson", random_state=semilla, early_stopping=False, **hiper)
    reg.fit(x[columnas].astype(float), x["y"].to_numpy(float) / e, sample_weight=e)
    return reg


def tabla_sentido(x: pd.DataFrame, claves: list[str]) -> pd.DataFrame:
    """Una fila por hora y sentido: fracción B0 del sentido (suma de sus segmentos), variables y, si están, subidas y
    total de la ruta."""
    agg = {"fraccion_base": ("fraccion_base", "sum"),
           **{c: (c, "first") for c in ("ruta_cod", "sentido_cod", "hora", *CALENDARIO) if c not in claves}}
    if "y" in x.columns:
        agg.update(y=("y", "sum"), total=("total", "first"))
    t = x.groupby([*claves, "sentido"], as_index=False).agg(**agg)
    t["log_fraccion_base"] = np.log(np.maximum(t["fraccion_base"].to_numpy(float), FRACCION_MIN))
    return t


def ajustar(tipo: str, x: pd.DataFrame, hiper: dict | None = None, semilla: int = SEMILLA) -> dict:
    """Regresores del tipo: {"regresor": HGB por segmento (None en B0), "regresor_sentido": HGB por sentido (solo
    hgb_jerarquico)}. Los tipos jerárquicos reparten dentro del sentido con el HGB de offset log T."""
    if tipo not in TIPOS:
        raise ValueError(f"Tipo de modelo de segmentos desconocido: {tipo!r} ({TIPOS})")
    if tipo == TIPO_REPARTO:
        return {"regresor": None, "regresor_sentido": None}
    exp = TIPO_OFFSET_REPARTO if tipo == TIPO_OFFSET_REPARTO else TIPO_OFFSET_TOTAL
    reg = _poisson(x, COLUMNAS, exposicion(exp, x), hiper or HIPER_DEFECTO, semilla)
    sentido = None
    if tipo == TIPO_JERARQUICO:
        t = tabla_sentido(x, CLAVES_HORA)
        e = t["total"].to_numpy(float) * np.maximum(t["fraccion_base"].to_numpy(float), FRACCION_MIN)
        sentido = _poisson(t, COLUMNAS_SENTIDO, e, HIPER_SENTIDO, semilla)
    return {"regresor": reg, "regresor_sentido": sentido}


def _normalizar(v: np.ndarray, x: pd.DataFrame, claves: list[str]) -> np.ndarray:
    suma = pd.Series(v).groupby([x[c].to_numpy() for c in claves]).transform("sum").to_numpy(float)
    return np.where(suma > 0, v / np.where(suma > 0, suma, 1.0), 0.0)


def _fraccion_sentido(modelo: dict, x: pd.DataFrame, claves: list[str]) -> np.ndarray:
    """Fracción de la hora que va a cada sentido (la de B0 o la del HGB de sentido), alineada con las filas de x."""
    t = tabla_sentido(x, claves)
    base = np.maximum(t["fraccion_base"].to_numpy(float), FRACCION_MIN)
    reg = modelo.get("regresor_sentido")
    cruda = base if reg is None else reg.predict(t[COLUMNAS_SENTIDO].astype(float)) * base
    t["fs"] = _normalizar(cruda, t, claves)
    return x[[*claves, "sentido"]].merge(t[[*claves, "sentido", "fs"]], on=[*claves, "sentido"],
                                         how="left")["fs"].to_numpy(float)


def fracciones_previstas(modelo: dict, x: pd.DataFrame, claves: list[str] | None = None) -> np.ndarray:
    """Fracción prevista de cada fila, normalizada a 1 dentro de cada hora (claves; por omisión ruta, fecha, hora).
    En los tipos jerárquicos: fracción del sentido × reparto dentro del sentido."""
    claves = claves or CLAVES_HORA
    base = x["fraccion_base"].to_numpy(float)
    tipo = modelo["tipo"]
    if tipo == TIPO_REPARTO:
        return _normalizar(base, x, claves)
    tasa = modelo["regresor"].predict(x[COLUMNAS].astype(float))
    if tipo == TIPO_OFFSET_REPARTO:
        return _normalizar(tasa * np.maximum(base, FRACCION_MIN), x, claves)
    if tipo == TIPO_OFFSET_TOTAL:
        return _normalizar(tasa, x, claves)
    return _normalizar(tasa, x, [*claves, "sentido"]) * _fraccion_sentido(modelo, x, claves)


# ----------------------------------------------------------------------------------------------- banda conformal
def puntaje(y, mu) -> np.ndarray:
    mu = np.asarray(mu, float)
    return (np.asarray(y, float) - mu) / np.sqrt(mu + 1.0)


def tramo_mu(mu) -> np.ndarray:
    return np.searchsorted(np.asarray(CORTES_MU), np.asarray(mu, float), side="right")


def cuantiles_conformales(s) -> tuple[float, float] | None:
    """(q10, q90) del puntaje con la corrección de muestra finita: el ⌊(n+1)·0,1⌋-ésimo y el ⌈(n+1)·0,9⌉-ésimo
    menores (cobertura ≥ 80 % si el futuro es intercambiable con la calibración); None sin datos."""
    s = np.sort(np.asarray(s, float))
    n = len(s)
    if n == 0:
        return None
    cola = (1.0 - COBERTURA_OBJETIVO) / 2.0
    k_lo = max(1, math.floor((n + 1) * cola))
    k_hi = min(n, math.ceil((n + 1) * (1.0 - cola)))
    return float(s[k_lo - 1]), float(s[k_hi - 1])


def calibrar_banda(y, mu) -> dict:
    """Cuantiles del puntaje por tramo de μ (Mondrian); un tramo con menos de MIN_GRUPO_BANDA filas usa los globales."""
    s, t = puntaje(y, mu), tramo_mu(mu)
    glob = cuantiles_conformales(s) or (0.0, 0.0)
    tramos = {}
    for k in range(len(CORTES_MU) + 1):
        sel = t == k
        propio = cuantiles_conformales(s[sel]) if int(sel.sum()) >= MIN_GRUPO_BANDA else None
        q = propio or glob
        tramos[str(k)] = {"q_lo": round(q[0], 6), "q_hi": round(q[1], 6), "n": int(sel.sum()),
                          "propio": propio is not None}
    return {"metodo": METODO_BANDA, "cobertura_objetivo": COBERTURA_OBJETIVO, "cortes_mu": list(CORTES_MU),
            "n": int(len(s)), "global": {"q_lo": round(glob[0], 6), "q_hi": round(glob[1], 6)}, "tramos": tramos}


def _cuantiles_de(banda: dict, mu: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    k = tramo_mu(mu)
    lo = np.array([banda["tramos"][str(i)]["q_lo"] for i in range(len(CORTES_MU) + 1)], dtype=float)
    hi = np.array([banda["tramos"][str(i)]["q_hi"] for i in range(len(CORTES_MU) + 1)], dtype=float)
    return lo[k], hi[k]


def banda_compuesta(f, p50, p10, p90, banda: dict) -> tuple[np.ndarray, np.ndarray]:
    """P10-P90 de un segmento (o sentido) con fracción f y pronóstico de la ruta (P10, P50, P90): μ̂ = f · P50 y
    semiancho √((f (P50 − P10))² + (q √(μ̂ + 1))²) a cada lado. Con P10 = P90 = P50 (total conocido) queda solo la
    banda conformal del reparto."""
    f, p50, p10, p90 = (np.asarray(v, float) for v in (f, p50, p10, p90))
    mu = f * p50
    q_lo, q_hi = _cuantiles_de(banda, mu)
    raiz = np.sqrt(mu + 1.0)
    abajo = np.sqrt((f * np.maximum(p50 - p10, 0.0)) ** 2 + (np.maximum(-q_lo, 0.0) * raiz) ** 2)
    arriba = np.sqrt((f * np.maximum(p90 - p50, 0.0)) ** 2 + (np.maximum(q_hi, 0.0) * raiz) ** 2)
    sin_demanda = np.broadcast_to(p50 <= 0, mu.shape)      # ruta sin pronóstico (fuera de servicio): banda [0, 0]
    return np.where(sin_demanda, 0.0, np.maximum(mu - abajo, 0.0)), np.where(sin_demanda, 0.0, mu + arriba)


# ----------------------------------------------------------------------------------------------- artefacto y registro
def carpeta(dir_modelos: Path | None = None) -> Path:
    return Path(dir_modelos) if dir_modelos else datos.carpeta_modelos() / "segmentos"


def _sha256(ruta: Path) -> str:
    h = hashlib.sha256()
    with ruta.open("rb") as f:
        for bloque in iter(lambda: f.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()


def registro(dir_modelos: Path | None = None) -> dict:
    ruta = carpeta(dir_modelos) / ARCHIVO_REGISTRO
    if ruta.exists():
        return json.loads(ruta.read_text(encoding="utf-8"))
    return {"activo": None, "modelos": {}, "historial_activacion": []}


def modelo_activo(dir_modelos: Path | None = None) -> str | None:
    return registro(dir_modelos).get("activo")


def guardar(contenido: dict, manifiesto: dict, dir_modelos: Path | None = None) -> dict:
    """Escribe el artefacto (joblib) y su manifiesto con el SHA-256 (§9.2, §9.3 «registrar … artefacto»)."""
    destino = carpeta(dir_modelos) / manifiesto["model_id"]
    destino.mkdir(parents=True, exist_ok=True)
    artefacto = destino / ARCHIVO_ARTEFACTO
    joblib.dump(contenido, artefacto, compress=3)
    man = dict(manifiesto, artefacto=ARCHIVO_ARTEFACTO, sha256=_sha256(artefacto), feature_version=VERSION_VARIABLES)
    (destino / ARCHIVO_MANIFIESTO).write_text(json.dumps(man, ensure_ascii=False, indent=2, default=str),
                                              encoding="utf-8")
    return man


def _estado_registro(es_activo: bool, tipo: str | None) -> str:
    if es_activo:
        return "activo"
    return "linea_base" if tipo == TIPO_REPARTO else "candidato"


def registrar(manifiesto: dict, *, activar: bool, motivo: str, usuario: str = "entrenamiento",
              dir_modelos: Path | None = None) -> dict:
    """Agrega el modelo al registro de segmentos; con activar=True queda activo y la decisión va al historial."""
    reg = registro(dir_modelos)
    mid = manifiesto["model_id"]
    reg.setdefault("modelos", {})[mid] = {k: manifiesto.get(k) for k in CLAVES_REGISTRO}
    if activar:
        reg.setdefault("historial_activacion", []).append(
            {"en": datetime.now(UTC).isoformat(timespec="seconds"), "de": reg.get("activo"), "a": mid,
             "usuario": usuario, "motivo": motivo})
        reg["activo"] = mid
    for k, m in reg["modelos"].items():
        m["estado"] = _estado_registro(k == reg.get("activo"), m.get("tipo"))
    ruta = carpeta(dir_modelos) / ARCHIVO_REGISTRO
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(reg, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return reg


def cargar(model_id: str | None = None, dir_modelos: Path | None = None) -> dict:
    """Carga el modelo de segmentos una sola vez (caché) y verifica su SHA-256 y su versión de variables (§9.2)."""
    dm = carpeta(dir_modelos)
    reg = registro(dm)
    mid = model_id or reg.get("activo")
    if not mid:
        raise ErrorModeloSegmentos(f"No hay modelo de segmentos activo en {dm}: ejecute scripts/entrenar_segmentos.py")
    if mid not in reg.get("modelos", {}):
        raise ModeloSegmentosNoEncontrado(f"Modelo de segmentos no registrado: {mid}")
    clave = f"{dm.resolve()}::{mid}"
    with _CANDADO:
        if clave in _CACHE:
            return _CACHE[clave]
        info = _leer_verificado(dm / mid, mid)
        _CACHE[clave] = info
        return info


def _leer_verificado(carpeta_modelo: Path, mid: str) -> dict:
    ruta_man = carpeta_modelo / ARCHIVO_MANIFIESTO
    if not ruta_man.exists():
        raise ModeloSegmentosNoEncontrado(f"No existe el manifiesto del modelo de segmentos {mid}")
    man = json.loads(ruta_man.read_text(encoding="utf-8"))
    artefacto = carpeta_modelo / man["artefacto"]
    sha = _sha256(artefacto) if artefacto.exists() else None
    if sha != man.get("sha256"):
        raise ErrorModeloSegmentos(f"El artefacto del modelo de segmentos {mid} no coincide con el SHA-256 de su "
                                   "manifiesto")
    if man.get("feature_version") != VERSION_VARIABLES:
        raise ErrorModeloSegmentos(f"{mid} usa variables {man.get('feature_version')}; el código tiene "
                                   f"{VERSION_VARIABLES}")
    obj = joblib.load(artefacto)
    return {"model_id": mid, "tipo": man["tipo"], "manifiesto": man, "sha256": sha, "regresor": obj.get("regresor"),
            "regresor_sentido": obj.get("regresor_sentido"), "codificacion": obj["codificacion"],
            "segmentos": obj["segmentos"], "banda": obj["banda"], "periodo_datos": man.get("periodo_datos")}


def limpiar_cache() -> None:
    with _CANDADO:
        _CACHE.clear()


def ficha(modelo: dict) -> dict:
    """Versión del modelo de segmentos que acompaña cada pronóstico (§9.2: model_id, feature_version, hash)."""
    man = modelo["manifiesto"]
    banda = man.get("banda") or {}
    return {"model_id": modelo["model_id"], "tipo": modelo["tipo"], "feature_version": man.get("feature_version"),
            "sha256": modelo["sha256"], "periodo_datos": man.get("periodo_datos"),
            "entrenado_con": man.get("entrenado_con"), "banda": banda.get("metodo"),
            "cobertura_prueba_pct": banda.get("cobertura_prueba_pct"),
            "evaluacion": "docs/evidencias/modelo/segmentos_modelo.md"}


# ----------------------------------------------------------------------------------------------- una ventana
def tramos_de_prediccion(variables_pred: dict, pasajeros: float | None) -> list[tuple[date, int, float]]:
    """[(fecha, hora, pasajeros de la ventana en esa hora)] desde variables['por_hora'] de una predicción (con el
    factor intradía), normalizado al total de la ventana."""
    k = float(variables_pred.get("factor_nowcast") or 1.0)
    t = [(pd.Timestamp(h["fecha"]).date(), int(h["hora"]), float(h["fraccion"]) * float(h["pasajeros_hora"]) * k)
         for h in variables_pred.get("por_hora") or []]
    suma = sum(x for _, _, x in t)
    if suma > 0 and pasajeros is not None:
        t = [(f, h, x * float(pasajeros) / suma) for f, h, x in t]
    return t


def calendario_de_tabla(tabla: pd.DataFrame | None, ruta: str, fecha: date, hora: int) -> dict[str, int]:
    """Calendario de la hora pronosticada desde la tabla de variables de la ruta (se conoce por adelantado); sin fila,
    el tipo de día del calendario y el resto en 0."""
    try:
        fila = tabla.loc[(ruta, fecha, hora)]
        return {c: int(fila[c]) for c in CALENDARIO}
    except (AttributeError, KeyError, TypeError, ValueError):
        return {"tipo_dia": datos.tipo_dia_de(fecha), "dia_semana": fecha.weekday(), "festivo": 0, "vacaciones": 0,
                "carnaval": 0}


def segmentos_de_ruta(modelo: dict, ruta: str) -> pd.DataFrame:
    seg = modelo["segmentos"]
    seg = seg[seg["ruta"] == ruta]
    if seg.empty:
        raise RutaSinSegmentos(f"No hay segmentos para la ruta {ruta} en el modelo {modelo['model_id']}")
    return seg


def filas_ventana(modelo: dict, ruta: str, tramos: list[tuple[date, int, float]],
                  calendario_de: Callable[[date, int], dict]) -> pd.DataFrame:
    """Una fila por hora de la ventana y segmento de la ruta, con las variables del modelo y la fracción prevista."""
    seg = segmentos_de_ruta(modelo, ruta)
    horas = pd.DataFrame([{"fecha": f, "hora": int(h), "demanda": float(d), **calendario_de(f, int(h))}
                          for f, h, d in tramos])
    x = matriz(horas.assign(ruta=ruta).merge(seg, on="ruta"), modelo["codificacion"])
    x["f"] = fracciones_previstas(modelo, x, ["fecha", "hora"])
    return x


def _resumen_segmentos(x: pd.DataFrame) -> pd.DataFrame:
    x = x.assign(pasajeros=x["demanda"] * x["f"], pasajeros_base=x["demanda"] * x["fraccion_base"])
    principal = x.loc[x.groupby("id_segmento")["demanda"].idxmax(), ["id_segmento", "nivel"]].set_index("id_segmento")
    g = (x.groupby(["id_segmento", "nro_segmento", "sentido", "km_inicio", "longitud_m"], as_index=False)
         [["pasajeros", "pasajeros_base"]].sum())
    return g.join(principal, on="id_segmento").sort_values("nro_segmento")


def desagregar_ventana(modelo: dict, ruta: str, tramos: list[tuple[date, int, float]], pasajeros: float | None,
                       p10: float | None, p90: float | None,
                       calendario_de: Callable[[date, int], dict]) -> dict[str, Any]:
    """Pronóstico por segmento y sentido de una ventana: fracción prevista por el modelo, hora por hora, por la
    demanda de la ruta; banda P10-P90 conformal compuesta con la de la ruta. La suma de los segmentos es la ruta.
    Una ventana sin horas (fuera de servicio) no tiene segmentos."""
    if not tramos:
        segmentos_de_ruta(modelo, ruta)
        return {"segmentos": [], "sentidos": [], "suma_segmentos": 0.0, "periodo_reparto": modelo.get("periodo_datos")}
    return desagregar_filas(modelo, filas_ventana(modelo, ruta, tramos, calendario_de), pasajeros, p10, p90)


def desagregar_filas(modelo: dict, x: pd.DataFrame, pasajeros: float | None, p10: float | None,
                     p90: float | None) -> dict[str, Any]:
    """desagregar_ventana() con las filas ya armadas por filas_ventana()."""
    g = _resumen_segmentos(x)
    total = float(g["pasajeros"].sum())
    p50 = float(pasajeros) if pasajeros is not None else total
    lo_r, hi_r = (p50 if p10 is None else float(p10)), (p50 if p90 is None else float(p90))
    g["fraccion"] = g["pasajeros"] / total if total > 0 else 0.0
    g["fraccion_reparto"] = g["pasajeros_base"] / total if total > 0 else 0.0
    g["p10"], g["p90"] = banda_compuesta(g["fraccion"], p50, lo_r, hi_r, modelo["banda"]["segmento"])
    s = g.groupby("sentido", as_index=False).agg(pasajeros=("pasajeros", "sum"), fraccion=("fraccion", "sum"),
                                                 segmentos=("id_segmento", "size"))
    s["p10"], s["p90"] = banda_compuesta(s["fraccion"], p50, lo_r, hi_r, modelo["banda"]["sentido"])
    return {"segmentos": [_segmento_json(r) for r in g.to_dict("records")],
            "sentidos": [{"sentido": r["sentido"], "pasajeros": round(r["pasajeros"], 3),
                          "fraccion": round(r["fraccion"], 6), "segmentos": int(r["segmentos"]),
                          "p10": round(r["p10"], 3), "p90": round(r["p90"], 3)} for r in s.to_dict("records")],
            "suma_segmentos": round(total, 3), "periodo_reparto": modelo.get("periodo_datos")}


def _segmento_json(r: dict) -> dict:
    return {"id_segmento": int(r["id_segmento"]), "nro_segmento": int(r["nro_segmento"]), "sentido": r["sentido"],
            "km_inicio": round(float(r["km_inicio"]), 3), "longitud_m": round(float(r["longitud_m"]), 1),
            "fraccion": round(float(r["fraccion"]), 6), "pasajeros": round(float(r["pasajeros"]), 3),
            "p10": round(float(r["p10"]), 3), "p90": round(float(r["p90"]), 3), "nivel_reparto": str(r["nivel"]),
            "fraccion_reparto": round(float(r["fraccion_reparto"]), 6)}


# ----------------------------------------------------------------------------------------------- foto de variables
def filas_foto(prediccion, tabla: pd.DataFrame | None, modelo: dict | None = None) -> list[dict]:
    """§7.3 paso 4 y §11.2: variables por segmento y sentido de la ventana de una predicción, una fila por segmento
    (sentido y segmento llenos), con la fecha y la hora de la primera hora de servicio de la ventana.

    Cada fila guarda solo lo propio del segmento (número, fracción B0 y subidas de su celda, fracción prevista,
    pasajeros y banda); la hora y el calendario de la ventana, comunes a todos los segmentos, ya están en las filas de
    la ruta de la misma predicción. Así la foto crece unos 0,4 kB por segmento (docs/evidencias/monitoreo/
    foto_segmentos.json)."""
    modelo = modelo or cargar()
    tramos = [t for t in tramos_de_prediccion(prediccion.variables or {}, prediccion.pasajeros) if t[2] > 0]
    if not tramos:
        return []

    def calendario_de(f: date, h: int) -> dict:
        return calendario_de_tabla(tabla, prediccion.ruta, f, h)

    x = filas_ventana(modelo, prediccion.ruta, tramos, calendario_de)
    d = desagregar_filas(modelo, x, prediccion.pasajeros, prediccion.p10, prediccion.p90)
    fecha, hora = tramos[0][0], tramos[0][1]
    celda = x.drop_duplicates("id_segmento").set_index("id_segmento")["subidas_celda"]
    return [{"sentido": s["sentido"], "segmento": s["id_segmento"], "fecha": fecha, "hora": hora,
             "feature_version": VERSION_VARIABLES, "model_id": modelo["model_id"],
             "features": {"nro_segmento": s["nro_segmento"], "fraccion_base": s["fraccion_reparto"],
                          "subidas_celda": int(celda.at[s["id_segmento"]]), "fraccion": s["fraccion"],
                          "pasajeros": s["pasajeros"], "p10": s["p10"], "p90": s["p90"]}}
            for s in d["segmentos"]]
