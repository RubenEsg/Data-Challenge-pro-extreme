"""Pruebas de la réplica operacional de Extreme (servicio «operacional», perfil compose «integracion», puerto 5434).

Marcador «replica». Se omiten (con el motivo) si la réplica no está disponible: hacen falta las claves en el entorno
o en el .env local (OPERACIONAL_PASSWORD, LECTOR_IA_PASSWORD, ESCRITOR_IA_PASSWORD, o REPLICA_URL para extreme_dba) y
un servidor LOCAL que responda. Nunca se conectan a la base compartida del reto.

Las pruebas que muestran el comportamiento real de psql con los scripts de Extreme usan «docker exec» sobre el
contenedor de la réplica (REPLICA_CONTENEDOR, por defecto sobusa_rep-operacional-1) y bases desechables
«validacion_*» que se borran al terminar. La réplica cargada no se modifica: lo que se escribe en ella para probar
se hace en transacciones que se deshacen, o en tablas de prueba que se borran.
"""
from __future__ import annotations

import uuid
from collections.abc import Callable, Iterator

import pytest

from scripts import replica_comun as rc

psycopg = pytest.importorskip("psycopg")


def pytest_configure(config):
    config.addinivalue_line("markers", "replica: pruebas contra la réplica operacional local (puerto 5434)")


def pytest_collection_modifyitems(config, items):
    for item in items:
        if "tests/replica" in item.nodeid.replace("\\", "/"):
            item.add_marker(pytest.mark.replica)


def _conectar(url: str | None, motivo: str, **kw):
    if not url:
        pytest.skip(f"réplica no configurada: falta {motivo} en el entorno o en el .env")
    try:
        return psycopg.connect(url, connect_timeout=3, **kw)
    except psycopg.OperationalError as exc:
        pytest.skip(f"réplica operacional no disponible en {url.split('@')[-1]}: {str(exc).splitlines()[0]}")


@pytest.fixture(scope="session")
def admin():
    cx = _conectar(rc.url_rol("extreme_dba"), "OPERACIONAL_PASSWORD (o REPLICA_URL)", autocommit=True)
    with cx.cursor() as cur:
        cur.execute("SELECT to_regclass('replica_meta.paso') IS NOT NULL")
        if not cur.fetchone()[0]:
            cx.close()
            pytest.skip("el servidor de la réplica no tiene replica_meta: no es la réplica operacional")
    yield cx
    cx.close()


@pytest.fixture(scope="session")
def cargada(admin):
    with admin.cursor() as cur:
        cur.execute("SELECT count(*) FROM replica_meta.carga")
        if cur.fetchone()[0] == 0:
            pytest.skip("la réplica no está cargada: ejecute python -m scripts.replica_cargar")
    return admin


@pytest.fixture
def lector(admin):
    cx = _conectar(rc.url_rol("lector_ia"), "LECTOR_IA_PASSWORD", autocommit=True)
    yield cx
    cx.close()


@pytest.fixture
def escritor(admin):
    cx = _conectar(rc.url_rol("escritor_ia"), "ESCRITOR_IA_PASSWORD", autocommit=True)
    yield cx
    cx.close()


@pytest.fixture
def base_desechable(admin) -> Iterator[Callable[..., str]]:
    """Crea bases vacías «validacion_*» en el servidor de la réplica, con 00_extensiones y 10_base_operacional.

    Devuelve una función que crea la base y entrega su nombre. Requiere docker (psql dentro del contenedor)."""
    if not rc.docker_disponible():
        pytest.skip(f"docker no disponible o contenedor {rc.contenedor()} detenido")
    creadas: list[str] = []

    def crear() -> str:
        nombre = f"validacion_{uuid.uuid4().hex[:10]}"
        with admin.cursor() as cur:
            cur.execute(f'CREATE DATABASE "{nombre}"')
        creadas.append(nombre)
        for archivo in ("00_extensiones.sql", "10_base_operacional.sql"):
            r = rc.psql(nombre, "-q", "-v", "ON_ERROR_STOP=1", "-f", f"/docker-entrypoint-initdb.d/{archivo}")
            assert r.returncode == 0, r.stdout + r.stderr
        return nombre

    yield crear
    with admin.cursor() as cur:
        for nombre in creadas:
            cur.execute(f'DROP DATABASE IF EXISTS "{nombre}" WITH (FORCE)')


def url_base(nombre: str) -> str:
    """URL de extreme_dba hacia otra base del mismo servidor de la réplica."""
    url = rc.url_rol("extreme_dba")
    return url.rsplit("/", 1)[0] + f"/{nombre}"
