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


# ------------------------------------------------------------------------------- fv2: contexto operacional
VACIO = pd.DataFrame(columns=["fecha", "hora", "nov_impacto", "nov_sube", "festivo_oficial"])


def _contexto(filas: list[dict]) -> pd.DataFrame:
    base = {"nov_impacto": 0.0, "nov_sube": 0, "festivo_oficial": 0}
    return pd.DataFrame([dict(base, **f) for f in filas])


def test_nov_impacto_vale_el_porcentaje_dentro_de_la_ventana_y_cero_fuera():
    s = serie_juguete()
    d = INICIO + timedelta(days=50)
    ctx = _contexto([{"fecha": d, "hora": 6, "nov_impacto": 80.0, "nov_sube": 1},
                     {"fecha": d, "hora": 7, "nov_impacto": 80.0, "nov_sube": 1}])
    t = variables.construir_variables(s, contexto=ctx)
    for ruta in ("SILENCIO", "CL 72"):  # novedades_viales_ruta está vacía: aplica a todas las rutas
        assert _fila(t, ruta, d, 6)["nov_impacto"] == 80.0 and _fila(t, ruta, d, 6)["nov_sube"] == 1
        assert _fila(t, ruta, d, 5)["nov_impacto"] == 0.0 and _fila(t, ruta, d, 5)["nov_sube"] == 0
        assert _fila(t, ruta, d + timedelta(days=1), 6)["nov_impacto"] == 0.0
    sin = variables.construir_variables(s, contexto=VACIO)
    assert (sin["nov_impacto"] == 0).all()


def test_vispera_y_post_festivo_usan_solo_el_calendario():
    s = serie_juguete()
    d = INICIO + timedelta(days=60)
    s.loc[s["fecha"] == d, "festivo"] = 1
    t = variables.construir_variables(s, contexto=VACIO)
    assert _fila(t, "SILENCIO", d - timedelta(days=1), 6)["vispera_festivo"] == 1
    assert _fila(t, "SILENCIO", d + timedelta(days=1), 6)["post_festivo"] == 1
    assert _fila(t, "SILENCIO", d, 6)["vispera_festivo"] == 0
    otra = s.copy()
    otra.loc[otra["fecha"] >= d - timedelta(days=1), "pasajeros"] *= 9  # pasajeros posteriores: no cambian nada
    t2 = variables.construir_variables(otra, contexto=VACIO)
    for c in variables.CONTEXTO + ["festivo", "tipo_dia"]:
        assert (t[c].to_numpy() == t2[c].to_numpy()).all(), c


def test_festivo_oficial_marca_la_semana_siguiente_al_ultimo_dato():
    s = serie_juguete(60)
    ultimo = s["fecha"].max()
    futuro = ultimo + timedelta(days=3)  # sin calendario en la serie: lo da estacionalidades_anio
    ctx = _contexto([{"fecha": futuro, "hora": h, "festivo_oficial": 1} for h in range(4, 21)])
    t = variables.construir_variables(s, contexto=ctx)
    f = _fila(t, "SILENCIO", futuro, 6)
    assert f["festivo"] == 1 and f["tipo_dia"] == 2
    assert _fila(t, "SILENCIO", futuro - timedelta(days=1), 6)["vispera_festivo"] == 1
    assert _fila(t, "SILENCIO", futuro + timedelta(days=1), 6)["post_festivo"] == 1


def test_matriz_x_elige_las_columnas_de_cada_version():
    t = variables.construir_variables(serie_juguete(60), contexto=VACIO)
    assert list(variables.matriz_x(t, variables.FV1).columns) == variables.COLUMNAS_FV1
    assert list(variables.matriz_x(t, variables.FV2).columns) == variables.COLUMNAS_FV2
    assert variables.COLUMNAS_FV2[: len(variables.COLUMNAS_FV1)] == variables.COLUMNAS_FV1
    assert variables.categoricas(variables.FV1) == ["ruta_cod"] and variables.categoricas(variables.FV2) == []
    try:
        variables.matriz_x(t, "fv0-desconocida")
    except KeyError:
        pass
    else:
        raise AssertionError("una versión no registrada debe fallar")
