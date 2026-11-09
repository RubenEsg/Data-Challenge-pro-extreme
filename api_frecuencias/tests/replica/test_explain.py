"""EXPLAIN de las consultas incrementales como lector_ia y propuesta de índices (E07, §8.3, §14.1 «Rendimiento»).

Solo leen: el EXPLAIN corre en la transacción READ ONLY de la API. La propuesta de índices se revisa como texto; se
aplica y se mide solo con scripts/replica_explain.py (como extreme_dba, dueño de la base) y se borra al terminar.
"""
from __future__ import annotations

import re
from datetime import UTC, datetime

import pytest

from scripts import replica_comun as rc
from scripts import replica_explain as rx

psycopg = pytest.importorskip("psycopg")


@pytest.fixture(scope="module")
def motor_lector():
    url = rc.url_rol("lector_ia")
    if not url:
        pytest.skip("falta LECTOR_IA_PASSWORD")
    from sqlalchemy import create_engine

    m = create_engine(url.replace("postgresql://", "postgresql+psycopg://"), pool_size=1, max_overflow=0)
    yield m
    m.dispose()


@pytest.mark.parametrize("tabla", rx.TABLAS)
def test_sql_incremental_compilado_es_select_con_parametros(tabla):
    from sqlalchemy import create_engine

    from app.servicios.fuentes import FuentePostgresSoloLectura, validar_solo_select

    motor = create_engine("postgresql+psycopg://lector_ia@localhost/x")       # solo el dialecto, no conecta
    f = FuentePostgresSoloLectura(url="postgresql+psycopg://lector_ia@localhost/x", tabla=tabla, motor=motor)
    sql, params = rx.sql_compilado(f, motor)
    assert validar_solo_select(sql)
    assert "%(marca)s" in sql                          # la marca va como parámetro, nunca como texto
    assert re.search(r"\d{4}-\d{2}-\d{2}", sql) is None


def test_explain_analyze_buffers_como_lector(cargada, motor_lector):
    from app.servicios.fuentes import FuentePostgresSoloLectura

    for tabla in ("timbradas_consolidado", "demanda_segmentos"):
        f = FuentePostgresSoloLectura(url="postgresql+psycopg://lector_ia@localhost/x", tabla=tabla,
                                      motor=motor_lector)
        sql, params = rx.sql_compilado(f, motor_lector)
        params.update(marca=datetime(2026, 8, 14, 5, 52, tzinfo=UTC), limite=1000)
        r = rx.explicar(motor_lector, sql, params)
        assert "Execution Time" in r["texto"] and "Buffers" in r["texto"]
        assert r["escaneos"] and r["ms_ejecucion"] >= 0


def test_propuesta_de_indices_solo_crea_indices_concurrentes_en_tablas_de_lectura():
    sentencias = [s.strip() for s in rx.PROPUESTA_SQL.split(";") if s.strip()
                  and not all(x.strip().startswith("--") for x in s.strip().splitlines())]
    cuerpos = ["\n".join(x for x in s.splitlines() if not x.strip().startswith("--")).strip() for s in sentencias]
    assert len(cuerpos) == 7
    for c in cuerpos:
        assert c.startswith("CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_ia_")
        assert re.search(r"ON public\.(timbradas_\w+|progvehiculos) ", c)
        assert not re.search(r"\b(ALTER|DROP|TRIGGER|FUNCTION|UPDATE|DELETE|INSERT)\b", c)
    archivo = rx.PROPUESTA
    if archivo.exists():
        assert archivo.read_text(encoding="utf-8") == rx.PROPUESTA_SQL


def test_la_replica_no_conserva_los_indices_propuestos(cargada, admin):
    """§8.3/§11.3: la réplica sigue fiel a Extreme (los índices se aplican solo para medir y se borran)."""
    with sim_candado(admin), admin.cursor() as cur:
        cur.execute("SELECT indexname FROM pg_indexes WHERE indexname = ANY(%s)", (rx._indices_propuestos(),))
        assert cur.fetchall() == []


def sim_candado(admin):
    from scripts.replica_simular_llegada import candado

    return candado(admin, espera_s=300)
