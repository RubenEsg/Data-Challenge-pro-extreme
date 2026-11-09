"""Fuga temporal (§14.1 «Datos/ML … fuga temporal»; §16 «Calidad de datos: no fuga»).

1. Ninguna variable usa datos posteriores al instante de predicción: si se alteran los pasajeros POSTERIORES a un
   corte, las variables de cualquier fecha hasta corte + 7 días (los rezagos son de 7 días o más) no cambian, y sí
   cambian desde corte + 8 días (la prueba es sensible).
2. Las variables de calendario y contexto no dependen de los pasajeros.
3. Entrenamiento, validación y prueba son estrictamente cronológicos y sin solape (manifiesto del modelo activo y
   partición recalculada).
"""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

pytestmark = pytest.mark.datos_ml

CORTES = [date(2024, 6, 30), date(2025, 8, 31), date(2025, 10, 31)]


def _perturbar_despues(serie: pd.DataFrame, corte: date, semilla: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(semilla)
    otra = serie.copy()
    futuro = pd.to_datetime(otra["fecha"]).dt.date > corte
    otra.loc[futuro, "pasajeros"] = rng.integers(0, 5000, int(futuro.sum())).astype(float)
    return otra


@pytest.mark.parametrize("corte", CORTES, ids=[str(c) for c in CORTES])
def test_variables_no_usan_datos_posteriores_al_corte(serie, corte):
    from app.servicios import datos, variables

    contexto = datos.contexto_operacional()
    base = variables.construir_variables(serie, contexto=contexto).set_index(["ruta", "fecha", "hora"]).sort_index()
    alterada = variables.construir_variables(_perturbar_despues(serie, corte), contexto=contexto)
    alterada = alterada.set_index(["ruta", "fecha", "hora"]).sort_index()
    cols = [c for c in variables.TODAS if c in base.columns and c != "hora"]
    fechas = base.index.get_level_values("fecha")

    hasta_7 = fechas <= corte + timedelta(days=7)          # el pronóstico de esos días solo ve datos ≤ corte
    a, b = base.loc[hasta_7, cols], alterada.loc[hasta_7, cols]
    iguales = (a == b) | (a.isna() & b.isna())
    assert iguales.all().all(), f"variables que cambian con datos futuros: {list(iguales.columns[~iguales.all()])}"

    dia_8 = fechas == corte + timedelta(days=8)
    assert not base.loc[dia_8, "lag7"].equals(alterada.loc[dia_8, "lag7"]), "la prueba no es sensible al cambio"


def test_calendario_y_contexto_no_dependen_de_los_pasajeros(serie):
    from app.servicios import datos, variables

    contexto = datos.contexto_operacional()
    base = variables.construir_variables(serie, contexto=contexto)
    otra = serie.copy()
    otra["pasajeros"] = otra["pasajeros"] * 3 + 11
    alterada = variables.construir_variables(otra, contexto=contexto)
    cols = ["ruta_cod", "dia_semana", "mes", *variables.CALENDARIO, *variables.CONTEXTO]
    pd.testing.assert_frame_equal(base[cols].reset_index(drop=True), alterada[cols].reset_index(drop=True))


def test_particion_del_modelo_activo_es_cronologica(manifiesto_activo):
    part = manifiesto_activo["particion"]
    ini_tr, fin_tr = (date.fromisoformat(x) for x in part["entrenamiento"].split(" a "))
    ini_va, fin_va = (date.fromisoformat(x) for x in part["validacion"].split(" a "))
    ini_te, fin_te = (date.fromisoformat(x) for x in part["prueba"].split(" a "))
    corte = date.fromisoformat(manifiesto_activo["data_cutoff"])
    assert ini_tr <= fin_tr == corte < ini_va <= fin_va < ini_te <= fin_te
    assert ini_va == corte + timedelta(days=1) and ini_te == fin_va + timedelta(days=1)
    m = manifiesto_activo["metricas"]
    assert date.fromisoformat(m["validacion"]["desde"]) > corte
    # la prueba reservada empieza después de la validación y no se mide al entrenar
    assert ini_te > date.fromisoformat(m["validacion"]["hasta"]) and "prueba" not in m


def test_particion_recalculada_sin_solape(tabla, manifiesto_activo):
    """La misma regla de inferencia.entrenar(): train ≤ corte < validación ≤ corte + 61 d < prueba."""
    from app.servicios import inferencia

    corte = date.fromisoformat(manifiesto_activo["data_cutoff"])
    fin_val = corte + timedelta(days=inferencia.DIAS_VALIDACION)
    t = inferencia._filas_utiles(tabla)
    tr, va, te = t[t["fecha"] <= corte], t[(t["fecha"] > corte) & (t["fecha"] <= fin_val)], t[t["fecha"] > fin_val]
    assert tr["fecha"].max() < va["fecha"].min() and va["fecha"].max() < te["fecha"].min()
    assert len(tr) == manifiesto_activo["filas_entrenamiento"]
    assert len(va) == manifiesto_activo["filas_validacion"] and len(te) == manifiesto_activo["filas_prueba"]
