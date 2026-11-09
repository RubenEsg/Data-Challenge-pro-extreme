"""Variables del pronóstico (versión FEATURE_VERSION), sin fuga de información.

Regla: la fila (ruta, fecha D, hora h) solo usa pasajeros de fechas <= D - 7 días (rezagos de una semana o más) y el
calendario, que se conoce por adelantado. Por eso la misma variable vale igual en el entrenamiento y en la operación,
y un pronóstico hecho en cualquier instante del día D (o hasta 7 días antes) no ve nada posterior a ese instante.

Variables:
- hora, dia_semana (0 = lunes), mes, ruta_cod, tipo_dia, festivo, carnaval, semana_santa, vacaciones,
  navidad, primero_enero
- lag7, lag14: pasajeros de la misma hora hace 7 y 14 días
- b8: la regla manual (línea base B1) = media de la misma hora y el mismo día de la semana de las 8 semanas anteriores
- m4: lo mismo con 4 semanas; sd8: desviación de esas 8 semanas
- nivel_7_13, nivel_7_34: media de la misma hora en los días D-13..D-7 y D-34..D-7 (nivel reciente, todos los días)
- dia_lag7: total del día D-7 de la ruta (todas las horas)
"""

from __future__ import annotations

import numpy as np
import pandas as pd

FEATURE_VERSION = "fv1-2026-11-08"
CODIGO_RUTA = {"SILENCIO": 0, "CRA 54": 1, "CL 72": 2}
CALENDARIO = ["tipo_dia", "festivo", "carnaval", "semana_santa", "vacaciones", "navidad", "primero_enero"]
REZAGOS = ["lag7", "lag14", "b8", "m4", "sd8", "nivel_7_13", "nivel_7_34", "dia_lag7"]
COLUMNAS_MODELO = ["ruta_cod", "hora", "dia_semana", "mes"] + CALENDARIO + REZAGOS
CATEGORICAS = ["ruta_cod"]
DIAS_EXTRA = 7  # se pueden construir variables hasta 7 días después del último dato


def _media_semanas(w: pd.DataFrame, semanas: int) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Suma, conteo y suma de cuadrados de los valores de la misma hora en las `semanas` semanas anteriores."""
    suma = pd.DataFrame(0.0, index=w.index, columns=w.columns)
    cuad = suma.copy()
    cuenta = suma.copy()
    for k in range(1, semanas + 1):
        x = w.shift(7 * k)
        suma += x.fillna(0.0)
        cuad += (x**2).fillna(0.0)
        cuenta += x.notna().astype(float)
    return suma, cuenta, cuad


def construir_variables(serie: pd.DataFrame, dias_extra: int = DIAS_EXTRA) -> pd.DataFrame:
    """Tabla ruta x fecha x hora con el objetivo (pasajeros, puede faltar) y las variables COLUMNAS_MODELO.

    `serie` necesita ruta, fecha, hora, pasajeros; si trae `excluido`, esas horas cuentan como dato faltante.
    Agrega `dias_extra` días después del último dato para poder pronosticar la semana siguiente.
    """
    s = serie.copy()
    s["fecha"] = pd.to_datetime(s["fecha"])
    if "excluido" in s.columns:
        s.loc[s["excluido"].fillna(0).astype(int) == 1, "pasajeros"] = np.nan
    w = s.set_index(["fecha", "ruta", "hora"])["pasajeros"].astype(float).unstack(["ruta", "hora"])
    ini, fin = pd.Timestamp(w.index.min()), pd.Timestamp(w.index.max())
    fechas = pd.date_range(ini, periods=(fin - ini).days + 1 + int(dias_extra), freq="D")
    w = w.reindex(fechas).sort_index(axis=1)

    feats: dict[str, pd.DataFrame] = {"lag7": w.shift(7), "lag14": w.shift(14)}
    suma8, cuenta8, cuad8 = _media_semanas(w, 8)
    b8 = suma8 / cuenta8.where(cuenta8 > 0)
    feats["b8"] = b8
    var8 = (cuad8 - cuenta8 * b8**2) / (cuenta8 - 1).where(cuenta8 > 1)
    feats["sd8"] = np.sqrt(var8.clip(lower=0))
    suma4, cuenta4, _ = _media_semanas(w, 4)
    feats["m4"] = suma4 / cuenta4.where(cuenta4 > 0)
    w7 = w.shift(7)
    feats["nivel_7_13"] = w7.rolling(7, min_periods=1).mean()
    feats["nivel_7_34"] = w7.rolling(28, min_periods=1).mean()
    dia = w.T.groupby(level="ruta").sum(min_count=1).T.shift(7)
    feats["dia_lag7"] = pd.DataFrame({col: dia[col[0]] for col in w.columns}, index=w.index)[w.columns]

    largo = pd.DataFrame({"pasajeros": w.stack(["ruta", "hora"], future_stack=True)})
    for nombre, m in feats.items():
        m = pd.DataFrame(np.asarray(m, dtype=float), index=w.index, columns=w.columns)
        largo[nombre] = m.stack(["ruta", "hora"], future_stack=True)
    largo = largo.reset_index().rename(columns={"level_0": "fecha"})
    largo["hora"] = largo["hora"].astype(int)

    cal_cols = [c for c in CALENDARIO if c in s.columns]
    cal = s[["fecha", "ruta", "hora"] + cal_cols].drop_duplicates(["fecha", "ruta", "hora"])
    largo = largo.merge(cal, on=["fecha", "ruta", "hora"], how="left")
    dsem = largo["fecha"].dt.dayofweek
    tipo_calc = np.where(dsem == 6, 2, np.where(dsem == 5, 1, 0))
    largo["tipo_dia"] = largo.get("tipo_dia", pd.Series(np.nan, index=largo.index)).fillna(pd.Series(tipo_calc))
    for c in CALENDARIO[1:]:
        largo[c] = largo[c].fillna(0) if c in largo.columns else 0
    largo["ruta_cod"] = largo["ruta"].map(CODIGO_RUTA).fillna(-1).astype(int)
    largo["dia_semana"] = dsem.astype(int)
    largo["mes"] = largo["fecha"].dt.month.astype(int)
    for c in CALENDARIO:
        largo[c] = largo[c].astype(int)
    largo["fecha"] = largo["fecha"].dt.date
    return largo[["ruta", "fecha", "hora", "pasajeros"] + [c for c in COLUMNAS_MODELO if c not in ("hora",)]]


def matriz_x(tabla: pd.DataFrame) -> pd.DataFrame:
    """Columnas en el orden que espera el modelo (preprocesamiento único para entrenar e inferir)."""
    return tabla[COLUMNAS_MODELO].astype(float)
