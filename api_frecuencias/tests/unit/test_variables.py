"""Pruebas de app/servicios/variables.py: la línea base es la regla manual y ninguna variable usa el futuro."""

from datetime import date, timedelta

import numpy as np
import pandas as pd

from app.servicios import variables

INICIO = date(2025, 1, 1)


def serie_juguete(dias: int = 120, semilla: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(semilla)
    filas = []
    for i in range(dias):
        f = INICIO + timedelta(days=i)
        for ruta in ("SILENCIO", "CL 72"):
            for h in (5, 6, 7):
                filas.append(
                    {
                        "ruta": ruta,
                        "fecha": f,
                        "hora": h,
                        "pasajeros": float(rng.integers(100, 1000)),
                        "excluido": 0,
                        "festivo": 0,
                        "tipo_dia": 0,
                    }
                )
    return pd.DataFrame(filas)


def _fila(tabla, ruta, f, h):
    t = tabla[(tabla["ruta"] == ruta) & (tabla["fecha"] == f) & (tabla["hora"] == h)]
    assert len(t) == 1
    return t.iloc[0]


def test_b8_es_la_regla_manual_de_8_semanas():
    s = serie_juguete()
    t = variables.construir_variables(s)
    d = INICIO + timedelta(days=100)
    previas = [
        s[(s["ruta"] == "SILENCIO") & (s["fecha"] == d - timedelta(days=7 * k)) & (s["hora"] == 6)]["pasajeros"].iloc[0]
        for k in range(1, 9)
    ]
    fila = _fila(t, "SILENCIO", d, 6)
    assert fila["b8"] == np.mean(previas)
    assert fila["m4"] == np.mean(previas[:4])
    assert fila["lag7"] == previas[0]
    assert fila["lag14"] == previas[1]
    assert np.isclose(fila["sd8"], np.std(previas, ddof=1))


def test_b8_ignora_horas_excluidas():
    s = serie_juguete()
    d = INICIO + timedelta(days=100)
    m = (s["ruta"] == "CL 72") & (s["fecha"] == d - timedelta(days=14)) & (s["hora"] == 7)
    s.loc[m, "excluido"] = 1
    t = variables.construir_variables(s)
    previas = [
        s[(s["ruta"] == "CL 72") & (s["fecha"] == d - timedelta(days=7 * k)) & (s["hora"] == 7)]["pasajeros"].iloc[0]
        for k in range(1, 9)
        if k != 2
    ]
    assert np.isclose(_fila(t, "CL 72", d, 7)["b8"], np.mean(previas))


def test_ninguna_variable_usa_datos_posteriores_al_corte():
    s = serie_juguete()
    d = INICIO + timedelta(days=90)
    base = variables.construir_variables(s)
    alterada = s.copy()
    futuro = alterada["fecha"] > d - timedelta(days=7)  # todo lo que pasa desde 6 días antes (incluido el propio día D)
    alterada.loc[futuro, "pasajeros"] = alterada.loc[futuro, "pasajeros"] * 7 + 12345
    otra = variables.construir_variables(alterada)
    for ruta in ("SILENCIO", "CL 72"):
        for h in (5, 6, 7):
            a, b = _fila(base, ruta, d, h), _fila(otra, ruta, d, h)
            for c in variables.REZAGOS:
                assert (pd.isna(a[c]) and pd.isna(b[c])) or np.isclose(a[c], b[c]), (ruta, h, c)


def test_variables_existen_hasta_7_dias_despues_del_ultimo_dato():
    s = serie_juguete(60)
    t = variables.construir_variables(s)
    ultimo = s["fecha"].max()
    fila = _fila(t, "SILENCIO", ultimo + timedelta(days=7), 6)
    assert pd.isna(fila["pasajeros"]) and not pd.isna(fila["lag7"])
    assert list(variables.matriz_x(t).columns) == variables.COLUMNAS_MODELO
