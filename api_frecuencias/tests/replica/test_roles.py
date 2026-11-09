"""Roles de la IA en la réplica (§11.3): lector_ia solo lee; escritor_ia solo escribe en ai_frecuencias.

Cada escritura de lector_ia se intenta dos veces: con la sesión por defecto (transacción de solo lectura) y después
de quitar ese modo, que cualquier sesión puede cambiar; ahí la garantía real es que solo tiene GRANT SELECT."""
from __future__ import annotations

import uuid

import psycopg
import pytest

from scripts.replica_comun import ESCRITURAS_LECTOR

ERRORES_PERMITIDOS = (psycopg.errors.ReadOnlySqlTransaction, psycopg.errors.InsufficientPrivilege)


def _intentar(cx, sql: str) -> None:
    with cx.transaction(), cx.cursor() as cur:
        if sql.startswith("COPY"):
            with cur.copy(sql) as cp:
                cp.write_row(("x",))
        else:
            cur.execute(sql)


@pytest.mark.parametrize(("nombre", "sql"), ESCRITURAS_LECTOR, ids=[e[0] for e in ESCRITURAS_LECTOR])
def test_lector_no_escribe_con_sesion_por_defecto(lector, nombre, sql):
    with pytest.raises(ERRORES_PERMITIDOS):
        _intentar(lector, sql)


@pytest.mark.parametrize(("nombre", "sql"), ESCRITURAS_LECTOR, ids=[e[0] for e in ESCRITURAS_LECTOR])
def test_lector_no_escribe_sin_solo_lectura(lector, nombre, sql):
    with lector.cursor() as cur:
        cur.execute("SET default_transaction_read_only = off")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        _intentar(lector, sql)


def test_lector_configuracion_de_sesion(lector):
    with lector.cursor() as cur:
        valores = {}
        for p in ("default_transaction_read_only", "statement_timeout", "idle_in_transaction_session_timeout",
                  "lock_timeout", "TimeZone"):
            cur.execute(f"SHOW {p}")
            valores[p] = cur.fetchone()[0]
    assert valores == {"default_transaction_read_only": "on", "statement_timeout": "30s",
                       "idle_in_transaction_session_timeout": "1min", "lock_timeout": "5s",
                       "TimeZone": "America/Bogota"}


def test_lector_lee_tablas_y_postgis(lector, cargada):
    with cargada.cursor() as cur:
        cur.execute("SELECT count(*) FROM public.timbradas_consolidado")
        esperado = cur.fetchone()[0]
    with lector.cursor() as cur:
        cur.execute("SELECT count(*) FROM public.timbradas_consolidado")
        assert cur.fetchone()[0] == esperado > 0
        cur.execute("SELECT count(*) FROM public.timbradas_segmentos WHERE id_viaje = 0")
        assert cur.fetchone()[0] == 0
        cur.execute("SELECT round(sum(ST_Length(geom::geography))) FROM public.rutasgeograficas")
        assert cur.fetchone()[0] > 0


def test_lector_lee_tablas_nuevas_por_privilegios_por_defecto(admin, lector):
    """ALTER DEFAULT PRIVILEGES: una tabla que extreme_dba cree después también es legible (y solo legible)."""
    tabla = f"public.prueba_dp_{uuid.uuid4().hex[:8]}"
    with admin.cursor() as cur:
        cur.execute(f"CREATE TABLE {tabla} (x int)")
        cur.execute(f"INSERT INTO {tabla} VALUES (1)")
    try:
        with lector.cursor() as cur:
            cur.execute(f"SELECT count(*) FROM {tabla}")
            assert cur.fetchone()[0] == 1
            cur.execute("SET default_transaction_read_only = off")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            _intentar(lector, f"INSERT INTO {tabla} VALUES (2)")
    finally:
        with admin.cursor() as cur:
            cur.execute(f"DROP TABLE {tabla}")


def test_escritor_escribe_en_ai_frecuencias(escritor):
    tabla = f"ai_frecuencias.prueba_{uuid.uuid4().hex[:8]}"
    with escritor.cursor() as cur:
        cur.execute(f"CREATE TABLE {tabla} (x int)")
        try:
            cur.execute(f"INSERT INTO {tabla} VALUES (1), (2)")
            cur.execute(f"SELECT sum(x) FROM {tabla}")
            assert cur.fetchone()[0] == 3
            cur.execute("CREATE TEMP TABLE paso_ingesta (x int)")  # staging de la ingesta (COPY + ON CONFLICT)
        finally:
            cur.execute(f"DROP TABLE {tabla}")


@pytest.mark.parametrize("sql", [
    "SELECT count(*) FROM public.timbradas_consolidado",
    "INSERT INTO public.timbradas_consolidado (proceso) VALUES ('x')",
    "UPDATE public.progvehiculos SET observacion = observacion WHERE false",
    "CREATE TABLE public.intruso (x int)",
    "SELECT public.fn_consolidar_timbradas_historicas()",
], ids=["select", "insert", "update", "create_public", "fn_consolidar"])
def test_escritor_no_toca_tablas_de_extreme(escritor, sql):
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        _intentar(escritor, sql)


def test_escritor_no_crea_esquemas(escritor):
    """Contrato para el modo integrado: escritor_ia es dueño de ai_frecuencias pero no puede crear esquemas, y
    PostgreSQL revisa ese permiso ANTES del IF NOT EXISTS. Alembic no debe emitir CREATE SCHEMA si el esquema existe."""
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        _intentar(escritor, "CREATE SCHEMA IF NOT EXISTS ai_frecuencias")
    with escritor.cursor() as cur:
        cur.execute("SELECT nspowner::regrole::text FROM pg_namespace WHERE nspname = 'ai_frecuencias'")
        assert cur.fetchone()[0] == "escritor_ia"


def test_public_no_puede_conectarse_ni_crear(admin):
    with admin.cursor() as cur:
        cur.execute("""SELECT has_database_privilege('public', current_database(), 'CONNECT'),
                              has_database_privilege('public', current_database(), 'TEMPORARY'),
                              has_schema_privilege('public', 'public', 'CREATE')""")
        assert cur.fetchone() == (False, False, False)
