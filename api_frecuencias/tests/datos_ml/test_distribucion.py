"""Distribución de los datos y de las variables (§14.1 «Datos/ML»; §9 variables del modelo; RF-002 calidad).

Contrato de la serie horaria (columnas, claves únicas, rangos), variables sin NaN donde no se permiten, rangos de
cada variable y deriva (PSI) entre la ventana de entrenamiento y las de validación y prueba.
"""
from __future__ import annotations

from datetime import timedelta

import numpy as np
import pandas as pd
import pytest

pytestmark = pytest.mark.datos_ml

PSI_MAXIMO = 0.10   # < 0,10 = sin cambio relevante (regla usual de PSI); 0,10-0,25 vigilar; > 0,25 reentrenar


def psi(referencia, actual, cortes: int = 10) -> float:
    """Population Stability Index con deciles de la referencia."""
    q = np.quantile(np.asarray(referencia, float), np.linspace(0, 1, cortes + 1))
    q[0], q[-1] = -np.inf, np.inf
    q = np.unique(q)
    pr = np.clip(np.histogram(referencia, q)[0] / len(referencia), 1e-4, None)
    pa = np.clip(np.histogram(actual, q)[0] / len(actual), 1e-4, None)
    return float(((pa - pr) * np.log(pa / pr)).sum())


def test_psi_es_cero_para_la_misma_distribucion_y_crece_con_un_desplazamiento():
    rng = np.random.default_rng(42)
    a = rng.normal(100, 10, 5000)
    assert psi(a, a) == pytest.approx(0, abs=1e-9)
    assert psi(a, a + 15) > 0.25


# ---------------------------------------------------------------- serie de entrada
def test_serie_cumple_el_contrato_de_columnas_y_claves(serie):
    from app.servicios import datos, variables

    assert set(datos.COLUMNAS_CONTRATO) <= set(serie.columns)
    claves = ["ruta", "fecha", "hora"]
    assert serie[claves + ["pasajeros", "salidas"]].notna().all().all(), "NaN en claves u objetivo"
    assert not serie.duplicated(claves).any(), "clave (ruta, fecha, hora) duplicada"
    assert set(serie["ruta"]) <= set(variables.CODIGO_RUTA), "ruta fuera del catálogo del modelo"
    assert serie["hora"].between(min(datos.HORAS_SERVICIO), max(datos.HORAS_SERVICIO)).all()
    assert (serie["pasajeros"] >= 0).all() and (serie["salidas"] >= 0).all()


def test_serie_sin_huecos_de_dias(serie):
    fechas = pd.to_datetime(serie["fecha"]).dt.normalize()
    for ruta, f in fechas.groupby(serie["ruta"]):
        dias = pd.date_range(f.min(), f.max(), freq="D")
        faltan = dias.difference(f.unique())
        assert len(faltan) / len(dias) < 0.01, f"{ruta}: {len(faltan)} días sin datos"


# ---------------------------------------------------------------- variables (fv2)
def test_variables_de_calendario_y_contexto_sin_nan_y_en_rango(tabla):
    from app.servicios import variables

    rangos = {"ruta_cod": (0, 2), "hora": (4, 20), "dia_semana": (0, 6), "mes": (1, 12), "tipo_dia": (0, 2),
              "nov_impacto": (0, 100), "nov_sube": (0, 1)}
    binarias = [c for c in variables.CALENDARIO[1:] + ["vispera_festivo", "post_festivo"]]
    for c in list(rangos) + binarias:
        assert tabla[c].notna().all(), f"{c} tiene NaN"
    for c, (lo, hi) in rangos.items():
        assert tabla[c].between(lo, hi).all(), f"{c} fuera de [{lo}, {hi}]"
    for c in binarias:
        assert set(tabla[c].unique()) <= {0, 1}, f"{c} no es binaria"


def test_rezagos_no_negativos_y_completos_despues_del_arranque(tabla):
    from app.servicios import variables

    for c in variables.REZAGOS:
        assert (tabla[c].dropna() >= 0).all(), f"{c} negativo"
    inicio = pd.Timestamp(min(tabla["fecha"])) + timedelta(days=63)   # 8 semanas + 7 días de rezago
    utiles = tabla[(pd.to_datetime(tabla["fecha"]) >= inicio) & tabla["pasajeros"].notna()]
    nan = utiles[variables.REZAGOS].isna().mean()
    assert (nan < 0.01).all(), f"rezagos con NaN después del arranque: {nan[nan >= 0.01].to_dict()}"
    assert utiles[["b8", "m4", "nivel_7_13", "nivel_7_34"]].notna().all().all()


def test_matriz_x_coincide_con_el_manifiesto_del_modelo_activo(tabla, manifiesto_activo):
    from app.servicios import variables

    x = variables.matriz_x(tabla, manifiesto_activo["feature_version"])
    assert list(x.columns) == manifiesto_activo["variables"], "columnas u orden distintos a los del entrenamiento"
    assert all(t == np.float64 for t in x.dtypes)
    assert np.isfinite(x.to_numpy()[~np.isnan(x.to_numpy())]).all(), "valores infinitos en la matriz"


def test_deriva_psi_entre_entrenamiento_validacion_y_prueba(tabla, manifiesto_activo):
    corte = pd.Timestamp(manifiesto_activo["data_cutoff"])
    f = pd.to_datetime(tabla["fecha"])
    utiles = tabla[tabla["pasajeros"].notna()]
    f = f[utiles.index]
    referencia = utiles[(f > corte - pd.Timedelta(days=243)) & (f <= corte)]            # 8 meses antes del corte
    ventanas = {"validacion": utiles[(f > corte) & (f <= corte + pd.Timedelta(days=61))],
                "prueba": utiles[f > corte + pd.Timedelta(days=61)]}
    resultados = {}
    for nombre, parte in ventanas.items():
        assert len(parte) > 1000, f"ventana {nombre} vacía"
        for c in ("pasajeros", "b8", "lag7", "nivel_7_34"):
            resultados[(nombre, c)] = psi(referencia[c].dropna(), parte[c].dropna())
    altos = {k: round(v, 4) for k, v in resultados.items() if v >= PSI_MAXIMO}
    assert not altos, f"deriva (PSI ≥ {PSI_MAXIMO}): {altos}"
