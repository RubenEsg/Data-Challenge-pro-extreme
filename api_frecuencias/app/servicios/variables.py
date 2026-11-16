"""Variables del pronóstico, por versión (VERSIONES), sin fuga de información.

Regla: la fila (ruta, fecha D, hora h) solo usa pasajeros de fechas <= D - 7 días (rezagos de una semana o más) y el
calendario/contexto, que se conoce por adelantado. Por eso la misma variable vale igual en el entrenamiento y en la
operación. Como las variables del día D usan el día D - 7 completo, el pronóstico del día D se puede hacer desde el
cierre del día D - 7 (unos 6 días antes) y en cualquier instante del día D, sin ver nada posterior.

En operación la serie es la VALIDADA (inferencia.tabla_variables con una sesión: el Parquet empaquetado con
demanda_observada encima), así que un día que llega y pasa la calidad entra en los rezagos de los 56 días siguientes.

Supuesto de las novedades viales (nov_impacto, nov_sube): se usan las del MISMO día objetivo, lo que supone que se
conocen por adelantado. Se cumple en los datos: novedades_viales_fecha no trae fecha de registro, pero sus 25 días son
eventos programados con antelación en Barranquilla (los cuatro días de Carnaval de 2023, 2024 y 2025, sus eventos
previos de febrero y los partidos de la Selección en el estadio Metropolitano: 2023-09-07, 2023-10-12, 2023-11-16,
2024-09-10, 2024-10-15, 2024-11-19, 2025-03-25 y 2025-06-06; detalle en
docs/evidencias/modelo/contexto_operacional.json).
Una novedad imprevista (un cierre por accidente) no debe entrar como variable del día: si Extreme agrega la fecha de
registro, hay que filtrar por fecha de registro <= instante del pronóstico.

Variables de fv1 (fv1-2026-11-08, ruta_cod categórica nativa del HGB):
- hora, dia_semana (0 = lunes), mes, ruta_cod, tipo_dia, festivo, carnaval, semana_santa, vacaciones,
  navidad, primero_enero
- lag7, lag14: pasajeros de la misma hora hace 7 y 14 días
- b8: la regla manual (línea base B1) = media de la misma hora y el mismo día de la semana de las 8 semanas anteriores
- m4: lo mismo con 4 semanas; sd8: desviación de esas 8 semanas
- nivel_7_13, nivel_7_34: media de la misma hora en los días D-13..D-7 y D-34..D-7 (nivel reciente, todos los días)
- dia_lag7: total del día D-7 de la ruta (todas las horas)

fv2 (fv2-2026-11-09) = fv1 + contexto operacional, con ruta_cod ORDINAL (sin categorical_features): así la explicación
SHAP TreeExplainer es exacta y el modelo se puede exportar a ONNX.
- nov_impacto: porcentaje_impacto de la novedad vial (novedades_viales_fecha) si la hora cruza [hora_inicio, hora_fin],
  0 si no; nov_sube: la novedad está marcada SUBE. novedades_viales_ruta está vacía: aplican a las 3 rutas.
- vispera_festivo / post_festivo: el día siguiente / anterior es festivo (calendario de la serie unido a los
  FESTIVO_NACIONAL de estacionalidades_anio; es calendario, no usa pasajeros).
Se descartaron FIESTA_ATLANTICO (empeora el WAPE) y puente (no aporta): ver docs/evidencias/modelo.

fv3 (fv3-2026-11-16) = fv2 + calendario académico (datos/calendario_academico.csv, con la fuente de cada periodo; es
calendario publicado con antelación, no usa pasajeros), las variables de calendario de E11:
- vac_escolar: el día cae en un receso de los colegios oficiales de Barranquilla.
- vac_univ: el día cae fuera de los periodos de clases universitarias (mediana de inicio y fin entre universidades).
- frac_vac_escolar_ventana, frac_vac_univ_ventana, frac_especial_ventana: fracción de los 4 días de referencia de los
  rezagos (D-7, D-14, D-21 y D-28) que eran receso escolar, vacaciones universitarias o festivo / Carnaval / Semana
  Santa. Le dicen al modelo si la base de las semanas anteriores viene de un periodo distinto al del día objetivo
  (el regreso a clases, el inicio de vacaciones).
Fuera de los años que cubre el calendario las dos primeras y sus fracciones quedan como dato faltante (el HGB los
admite); hay que añadir las filas del año siguiente a calendario_academico.csv. Se eligió con la validación y los
backtests congelados de 2024 y 2025 (docs/evidencias/modelo/decision_fv3.md). Los pesos a días atípicos de E11 no
aportaron sobre los calendarios y no se usan.

construir_variables() arma el superconjunto de columnas; matriz_x(tabla, version) elige las de cada versión, de modo
que un modelo fv1 sigue cargando y prediciendo con el código actual (reversión, RF-019).
"""

from __future__ import annotations

from datetime import timedelta

import numpy as np
import pandas as pd

FV1 = "fv1-2026-11-08"
FV2 = "fv2-2026-11-09"
FV3 = "fv3-2026-11-16"
FEATURE_VERSION = FV3  # versión con la que se entrenan los modelos nuevos
CODIGO_RUTA = {"SILENCIO": 0, "CRA 54": 1, "CL 72": 2}
CALENDARIO = ["tipo_dia", "festivo", "carnaval", "semana_santa", "vacaciones", "navidad", "primero_enero"]
REZAGOS = ["lag7", "lag14", "b8", "m4", "sd8", "nivel_7_13", "nivel_7_34", "dia_lag7"]
CONTEXTO = ["nov_impacto", "nov_sube", "vispera_festivo", "post_festivo"]
COLUMNAS_FV1 = ["ruta_cod", "hora", "dia_semana", "mes"] + CALENDARIO + REZAGOS
COLUMNAS_FV2 = COLUMNAS_FV1 + CONTEXTO
ACADEMICO = ["vac_escolar", "vac_univ", "frac_vac_escolar_ventana", "frac_vac_univ_ventana", "frac_especial_ventana"]
COLUMNAS_FV3 = COLUMNAS_FV2 + ACADEMICO
DIAS_REFERENCIA = (7, 14, 21, 28)  # días de referencia de la ventana de rezagos (las 4 mismas semanas)
VERSIONES: dict[str, dict] = {
    FV1: {
        "columnas": COLUMNAS_FV1,
        "categoricas": ["ruta_cod"],
        "descripcion": "calendario + rezagos de 7 días o más; ruta_cod categórica nativa",
    },
    FV2: {
        "columnas": COLUMNAS_FV2,
        "categoricas": [],
        "descripcion": "fv1 + novedades viales y víspera/día posterior a festivo; ruta_cod ordinal (SHAP exacto)",
    },
    FV3: {
        "columnas": COLUMNAS_FV3,
        "categoricas": [],
        "descripcion": "fv2 + calendario escolar y universitario y su peso en la ventana de rezagos",
    },
}
COLUMNAS_MODELO = VERSIONES[FEATURE_VERSION]["columnas"]
CATEGORICAS = VERSIONES[FEATURE_VERSION]["categoricas"]
TODAS = list(dict.fromkeys(c for v in VERSIONES.values() for c in v["columnas"]))
DIAS_EXTRA = 7  # se pueden construir variables hasta 7 días después del último dato


def version_valida(version: str | None) -> str:
    v = version or FEATURE_VERSION
    if v not in VERSIONES:
        raise KeyError(f"Versión de variables desconocida: {v!r}. Registradas: {sorted(VERSIONES)}")
    return v


def columnas(version: str | None = None) -> list[str]:
    return list(VERSIONES[version_valida(version)]["columnas"])


def categoricas(version: str | None = None) -> list[str]:
    return list(VERSIONES[version_valida(version)]["categoricas"])


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


def _contexto_por_defecto() -> pd.DataFrame | None:
    try:
        from . import datos

        return datos.contexto_operacional()
    except Exception:  # noqa: BLE001 - sin archivo de contexto las variables valen 0
        return None


def _agregar_contexto(largo: pd.DataFrame, s: pd.DataFrame, contexto: pd.DataFrame | None) -> pd.DataFrame:
    """nov_impacto, nov_sube, vispera_festivo y post_festivo (y festivo/tipo_dia de los días sin calendario)."""
    festivos = set(pd.to_datetime(s.loc[s.get("festivo", pd.Series(0, index=s.index)).fillna(0) == 1, "fecha"]))
    if contexto is not None and len(contexto):
        c = contexto.copy()
        c["fecha"] = pd.to_datetime(c["fecha"])
        c["hora"] = c["hora"].astype(int)
        cols = [x for x in ("nov_impacto", "nov_sube", "festivo_oficial") if x in c.columns]
        largo = largo.merge(c[["fecha", "hora"] + cols].drop_duplicates(["fecha", "hora"]), on=["fecha", "hora"],
                            how="left")
        if "festivo_oficial" in largo.columns:
            festivos |= set(largo.loc[largo["festivo_oficial"].fillna(0) == 1, "fecha"])
            # días sin calendario en la serie (la semana siguiente al último dato): festivo del calendario oficial
            sin_cal = largo["festivo"].isna() & (largo["festivo_oficial"].fillna(0) == 1)
            largo.loc[sin_cal, "festivo"] = 1
            largo.loc[sin_cal, "tipo_dia"] = 2
            largo = largo.drop(columns="festivo_oficial")
    for x in ("nov_impacto", "nov_sube"):
        largo[x] = largo[x].fillna(0.0).astype(float) if x in largo.columns else 0.0
    largo["vispera_festivo"] = (largo["fecha"] + timedelta(days=1)).isin(festivos).astype(int)
    largo["post_festivo"] = (largo["fecha"] - timedelta(days=1)).isin(festivos).astype(int)
    return largo


def _academico_por_defecto() -> pd.DataFrame | None:
    try:
        from . import datos

        return datos.calendario_academico()
    except Exception:  # noqa: BLE001 - sin calendario académico las variables fv3 quedan como dato faltante
        return None


def dias_academicos(calendario: pd.DataFrame | None, fechas: pd.DatetimeIndex) -> pd.DataFrame:
    """vac_escolar y vac_univ de cada fecha de `fechas` (índice del resultado). Cada tipo del calendario cubre del 1 de
    enero del año de su primer periodo al 31 de diciembre del año del último; fuera de eso el valor es NaN (no se
    sabe)."""
    out = pd.DataFrame(np.nan, index=fechas, columns=["vac_escolar", "vac_univ"])
    if calendario is None or not len(calendario):
        return out
    c = calendario.copy()
    c["inicio"], c["fin"] = pd.to_datetime(c["inicio"]), pd.to_datetime(c["fin"])
    # (tipo, columna, valor dentro del periodo, valor fuera): un receso escolar es vacación; un periodo de clases no
    for tipo, col, dentro, fuera in (("escolar_receso", "vac_escolar", 1.0, 0.0),
                                     ("universitario_clases", "vac_univ", 0.0, 1.0)):
        g = c[c["tipo"] == tipo]
        if not len(g):
            continue
        desde = pd.Timestamp(year=int(g["inicio"].min().year), month=1, day=1)
        hasta = pd.Timestamp(year=int(g["fin"].max().year), month=12, day=31)
        v = np.where((fechas >= desde) & (fechas <= hasta), fuera, np.nan)
        for r in g.itertuples():
            v[(fechas >= r.inicio) & (fechas <= r.fin)] = dentro
        out[col] = v
    return out


def _agregar_academico(largo: pd.DataFrame, calendario: pd.DataFrame | None) -> pd.DataFrame:
    """Variables fv3: vac_escolar, vac_univ y la fracción de los 4 días de referencia de los rezagos (D-7, D-14, D-21,
    D-28) en receso escolar, en vacaciones universitarias y especiales (festivo, Carnaval o Semana Santa). Un día de
    referencia anterior a la serie o fuera del calendario deja la fracción en NaN. `largo` trae fecha como Timestamp y
    el calendario de la serie ya completo."""
    fechas = pd.DatetimeIndex(largo["fecha"])
    todas = pd.date_range(fechas.min() - timedelta(days=max(DIAS_REFERENCIA)), fechas.max(), freq="D")
    dias = dias_academicos(calendario, todas)
    especial = (largo[["festivo", "carnaval", "semana_santa"]].max(axis=1) > 0).groupby(fechas).max()
    dias["especial"] = especial.astype(float).reindex(todas)
    for col, nuevo in (("vac_escolar", "frac_vac_escolar_ventana"), ("vac_univ", "frac_vac_univ_ventana"),
                       ("especial", "frac_especial_ventana")):
        dias[nuevo] = sum(dias[col].shift(k) for k in DIAS_REFERENCIA) / len(DIAS_REFERENCIA)
    for c in ACADEMICO:
        largo[c] = dias[c].reindex(fechas).to_numpy()
    return largo


def construir_variables(
    serie: pd.DataFrame, dias_extra: int = DIAS_EXTRA, contexto: pd.DataFrame | None = None,
    academico: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Tabla ruta x fecha x hora con el objetivo (pasajeros, puede faltar) y las variables de TODAS las versiones.

    `serie` necesita ruta, fecha, hora, pasajeros; si trae `excluido`, esas horas cuentan como dato faltante.
    `contexto` (fecha, hora, nov_impacto, nov_sube, festivo_oficial); por defecto datos.contexto_operacional().
    `academico` (tipo, inicio, fin: el calendario de datos.calendario_academico(), que es el valor por defecto).
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
    for c in CALENDARIO:
        if c not in largo.columns:
            largo[c] = np.nan
    largo = _agregar_contexto(largo, s, _contexto_por_defecto() if contexto is None else contexto)
    dsem = largo["fecha"].dt.dayofweek
    tipo_calc = np.where(dsem == 6, 2, np.where(dsem == 5, 1, 0))
    largo["tipo_dia"] = largo["tipo_dia"].fillna(pd.Series(tipo_calc, index=largo.index))
    for c in CALENDARIO[1:]:
        largo[c] = largo[c].fillna(0)
    largo["ruta_cod"] = largo["ruta"].map(CODIGO_RUTA).fillna(-1).astype(int)
    largo["dia_semana"] = dsem.astype(int)
    largo["mes"] = largo["fecha"].dt.month.astype(int)
    for c in CALENDARIO:
        largo[c] = largo[c].astype(int)
    largo = _agregar_academico(largo, _academico_por_defecto() if academico is None else academico)
    largo["fecha"] = largo["fecha"].dt.date
    return largo[["ruta", "fecha", "hora", "pasajeros"] + [c for c in TODAS if c not in ("hora",)]]


def matriz_x(tabla: pd.DataFrame, version: str | None = None) -> pd.DataFrame:
    """Columnas de la versión, en el orden que espera el modelo (preprocesamiento único para entrenar e inferir)."""
    return tabla[columnas(version)].astype(float)
