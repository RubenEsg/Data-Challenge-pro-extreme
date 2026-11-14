"""EXPLAIN de las consultas incrementales como lector_ia y propuesta de índices (E07, §8.3, §14.1 «Rendimiento»).

Solo leen: el EXPLAIN corre en la transacción READ ONLY de la API. La propuesta de índices se revisa como texto; se
aplica y se mide solo con scripts/replica_explain.py (como extreme_dba, dueño de la base) y se borra al terminar.
La excepción, solo con REPLICA_PRUEBAS_ESCRITURA=1: una prueba crea TODA la propuesta dentro de una transacción de
extreme_dba que se revierte (como scripts/replica_indices_candidatos.py) y comprueba que la lectura compuesta no
empeora con ella y con las estadísticas al día.
"""
from __future__ import annotations

import os
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


def test_sin_la_union_final_de_rutas_la_lectura_compuesta_entrega_las_mismas_filas_en_el_mismo_orden(cargada, lector,
                                                                                                     motor_lector):
    """§8.3, H12. fuentes._SQL_DEMANDA_SEGMENTOS dejó de unir rutas en la consulta final para quitar un plan malo. Aquí
    se comprueba que solo cambió el plan: con el bloque de llegada de la réplica, la lectura de hoy y la formulación
    anterior (scripts.replica_indices_candidatos.con_union_final_de_rutas) entregan las mismas columnas y las mismas
    filas, en el mismo orden. Solo lee, como lector_ia."""
    import pandas as pd

    from scripts import replica_indices_candidatos as R

    todas = R.consultas(motor_lector, R.contexto(lector))
    hoy, antes = todas["demanda_segmentos_bloque"], todas["demanda_segmentos_bloque" + R.CON_UNION_FINAL]
    assert antes.referencia and hoy.sql != antes.sql and hoy.params == antes.params
    with motor_lector.connect() as c:
        c.exec_driver_sql("SET TRANSACTION READ ONLY")
        filas_hoy = pd.DataFrame(c.exec_driver_sql(hoy.sql, hoy.params).mappings().all())
        filas_antes = pd.DataFrame(c.exec_driver_sql(antes.sql, antes.params).mappings().all())
    assert len(filas_hoy) > 1000 and list(filas_hoy.columns) == list(filas_antes.columns)
    assert filas_hoy.equals(filas_antes)


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


@pytest.mark.skipif(os.environ.get("REPLICA_PRUEBAS_ESCRITURA") != "1",
                    reason="crea los índices de la propuesta como extreme_dba en una transacción que se revierte y "
                           "corre ANALYZE: REPLICA_PRUEBAS_ESCRITURA=1")
def test_con_la_propuesta_entera_y_las_estadisticas_al_dia_la_lectura_compuesta_no_empeora(cargada, admin):
    """§8.3, H12. El defecto: con la propuesta ENTERA y ANALYZE, la lectura demanda_segmentos del bloque grande elegía
    un ciclo anidado con Materialize (PostgreSQL estimaba unas 60 filas en `viajes ⋈ rutas` donde hay 13.304): 88
    millones de filas descartadas en el filtro de la unión y 9,3 s en vez de 3,5 s. Medir cada índice por separado no lo
    veía. Ahora la lectura no vuelve a unir rutas: con toda la propuesta y las estadísticas al día, en una transacción
    que se revierte, ninguna de sus variantes empeora ni descarta filas en el filtro de una unión."""
    from scripts import replica_indices_candidatos as R
    from scripts.replica_simular_llegada import candado

    claves = ("demanda_segmentos_bloque", "demanda_segmentos_una_ruta_bloque", "demanda_segmentos_sin_novedades")
    motor = R._motor_dba()
    try:
        with candado(admin, espera_s=600):
            todas = R.consultas(motor, R.contexto(admin))
            r = R.medir_propuesta_entera(motor, [todas[k] for k in claves])
            quedaron = R._indices_al_terminar(admin)
    finally:
        motor.dispose()
    assert "error" not in r, r.get("error")
    assert quedaron == [] and list(r["creados"]) == rx._indices_propuestos()      # toda la propuesta, y se revirtió
    comparacion = R.comparar(r)
    assert R.empeoran(comparacion) == [], {k: (v["ms_sin"], v["ms_con"]) for k, v in comparacion.items()}
    for clave in claves:
        assert comparacion[clave]["descartadas_por_union_con"] == 0, (clave, comparacion[clave])
    bloque = comparacion["demanda_segmentos_bloque"]
    assert bloque["filas"] > 1000 and bloque["usa_indice"]


def test_la_replica_no_conserva_los_indices_propuestos(cargada, admin):
    """§8.3/§11.3: la réplica sigue fiel a Extreme (los índices se aplican solo para medir y se borran)."""
    with sim_candado(admin), admin.cursor() as cur:
        cur.execute("SELECT indexname FROM pg_indexes WHERE indexname = ANY(%s)", (rx._indices_propuestos(),))
        assert cur.fetchall() == []


def sim_candado(admin):
    from scripts.replica_simular_llegada import candado

    return candado(admin, espera_s=300)
