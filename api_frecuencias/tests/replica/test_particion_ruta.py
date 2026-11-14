"""Lectura incremental por ruta contra la réplica de Extreme (RNF-005, §11.2, §11.3), SOLO LECTURA como lector_ia.

El trabajo de una ruta lee con el MISMO SELECT de la lista blanca (variante «r.nombre = ANY(:rutas)») en la
transacción READ ONLY con statement_timeout de siempre. Estas pruebas comprueban sobre los datos reales de la réplica
que lo que entrega la lectura de una ruta es exactamente lo que entrega la lectura de todas las rutas para esa ruta,
desde la carga inicial y desde una marca intermedia, y que el plan de la variante por ruta se puede explicar como
lector_ia. No escriben nada en la réplica.
"""
from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd
import pytest

from scripts import replica_comun as rc

psycopg = pytest.importorskip("psycopg")
CLAVE = ["ruta", "fecha", "hora"]
VALORES = ["pasajeros", "salidas", "subidas", "bajadas", "id_estacionalidad"]


def _url_lector() -> str:
    url = rc.url_rol("lector_ia")
    if not url:
        pytest.skip("falta LECTOR_IA_PASSWORD")
    return url.replace("postgresql://", "postgresql+psycopg://")


def _fuente():
    from app.servicios.fuentes import FuentePostgresSoloLectura

    return FuentePostgresSoloLectura(url=_url_lector(), tabla="demanda_segmentos")


def _ordenado(d: pd.DataFrame) -> pd.DataFrame:
    return d[CLAVE + VALORES].sort_values(CLAVE).reset_index(drop=True)


@pytest.fixture(scope="module")
def completa(cargada):
    f = _fuente()
    d, _ = f.leer_incremental(None)
    f._engine().dispose()
    return d


def test_lectura_de_una_ruta_es_la_completa_filtrada_por_esa_ruta(completa):
    from app.servicios.fuentes import Particion

    assert completa["ruta"].nunique() >= 2
    for ruta in sorted(completa["ruta"].unique())[:3]:
        f = _fuente()
        lectura = f.leer_particion(Particion(proceso="sobusa", rutas=(ruta,)))
        f._engine().dispose()
        assert set(lectura.df["ruta"]) == {ruta}
        pd.testing.assert_frame_equal(_ordenado(lectura.df), _ordenado(completa[completa["ruta"] == ruta]),
                                      check_dtype=False)
        assert lectura.marcas[ruta] == pd.Timestamp(completa.loc[completa["ruta"] == ruta,
                                                                  "ultima_actualizacion"].max()).to_pydatetime()
        assert f.resumen_lectura["particion"] == [ruta] and f.resumen_lectura["nuevas"] == len(lectura.df)


def test_desde_una_marca_intermedia_la_ruta_lee_lo_mismo_que_la_lectura_de_siempre(completa):
    from app.servicios.fuentes import Particion

    ruta = completa["ruta"].value_counts().index[0]
    marcas = completa.loc[completa["ruta"] == ruta, "ultima_actualizacion"].sort_values()
    marca = pd.Timestamp(marcas.iloc[len(marcas) // 2]).to_pydatetime()
    legado = _fuente()
    d_legado, _ = legado.leer_incremental(marca)
    legado._engine().dispose()
    f = _fuente()
    lectura = f.leer_particion(Particion(proceso="sobusa", rutas=(ruta,), marcas={ruta: marca}))
    f._engine().dispose()
    pd.testing.assert_frame_equal(_ordenado(lectura.df), _ordenado(d_legado[d_legado["ruta"] == ruta]),
                                  check_dtype=False)


def test_la_variante_por_ruta_se_explica_como_lector_en_solo_lectura(cargada):
    from sqlalchemy import create_engine

    from app.servicios.fuentes import FuentePostgresSoloLectura, validar_solo_select
    from scripts import replica_explain as rx

    motor = create_engine(_url_lector(), pool_size=1, max_overflow=0)
    try:
        f = FuentePostgresSoloLectura(url=_url_lector(), tabla="demanda_segmentos", motor=motor)
        compilado = f.consulta_incremental(con_rutas=True).compile(dialect=motor.dialect)
        sql, params = str(compilado), dict(compilado.params)
        assert validar_solo_select(sql) and "%(rutas)s" in sql
        params.update(marca=datetime(2023, 2, 26, tzinfo=UTC), limite=1000, proceso="sobusa", rutas=["CRA 54"])
        r = rx.explicar(motor, sql, params)
    finally:
        motor.dispose()
    assert "Execution Time" in r["texto"] and r["escaneos"] and r["ms_ejecucion"] >= 0
