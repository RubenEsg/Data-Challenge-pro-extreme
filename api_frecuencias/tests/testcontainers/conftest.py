"""Integración con Testcontainers (spec v1.5 §14.1 «Integración»: Testcontainers PostgreSQL/PostGIS).

Cada sesión levanta un PostgreSQL 14 + PostGIS 3.4 efímero, con la misma imagen del docker-compose y del servicio
de CI (postgis/postgis:14-3.4). El esquema ai_frecuencias se crea con Alembic desde cero y las pruebas ejercitan
las migraciones, los repositorios (modelos SQLAlchemy y servicios) y la API (TestClient) contra ese contenedor.

Marcador «testcontainers». No corren por omisión: la suite normal sigue usando la base local compartida (puerto 5433)
y no paga los ~20 s de arranque del contenedor. Se activan con TESTCONTAINERS=1, como hacen el CI y
scripts/ci_local.py. Sin Docker se omiten con su motivo. El contenedor no publica nada fijo: Docker le asigna un
puerto libre y Ryuk lo borra al terminar, aunque el proceso muera.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import shutil
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]
IMAGEN = os.environ.get("TESTCONTAINERS_IMAGEN", "postgis/postgis:14-3.4")

# RF-018c: un ciclo de prueba no encola el reentrenamiento del corto plazo (del orden de 15 minutos); las pruebas de
# esa política lo encienden (tests/integracion/test_reentreno_corto_plazo.py)
os.environ.setdefault("REENTRENO_CORTO_PLAZO_EN_CICLO", "false")
ACTIVAS = os.environ.get("TESTCONTAINERS", "").strip().lower() in ("1", "true", "si", "sí")

# claves de PRUEBA de esta sesión (nunca en el repositorio); el entorno solo lleva sus hashes
CLAVES = {rol: secrets.token_urlsafe(32) for rol in ("operador", "analista", "admin")}
API_KEYS = json.dumps({hashlib.sha256(c.encode()).hexdigest(): {"usuario": f"tc_{rol}", "rol": rol}
                       for rol, c in CLAVES.items()})


def alembic(url: str, *args: str) -> None:
    """Ejecuta un comando de Alembic (upgrade, downgrade, current…) contra la URL dada."""
    from alembic.config import Config

    from alembic import command

    cfg = Config(str(RAIZ / "alembic.ini"))
    cfg.set_main_option("script_location", str(RAIZ / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    getattr(command, args[0])(cfg, *args[1:])


def revision_head() -> str:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    cfg = Config(str(RAIZ / "alembic.ini"))
    cfg.set_main_option("script_location", str(RAIZ / "alembic"))
    cabezas = ScriptDirectory.from_config(cfg).get_heads()
    assert len(cabezas) == 1, f"Alembic debe tener una sola cabeza: {cabezas}"
    return cabezas[0]


@pytest.fixture(scope="session")
def url_contenedor():
    """URL de un PostGIS 14-3.4 recién creado (vacío). Si Docker no responde, las pruebas se omiten."""
    if not ACTIVAS:   # se decide aquí y no al importar: un skip en el conftest rompería la colección de la suite
        pytest.skip("Pruebas con Testcontainers apagadas: defina TESTCONTAINERS=1 "
                    "(el CI y scripts/ci_local.py lo hacen)")
    try:  # 4.15: el módulo nuevo es testcontainers.community.postgres; el antiguo queda como respaldo
        from testcontainers.community.postgres import PostgresContainer
    except ImportError:  # pragma: no cover - versiones anteriores de testcontainers
        from testcontainers.postgres import PostgresContainer
    try:
        contenedor = PostgresContainer(IMAGEN, username="sobusa", password=secrets.token_urlsafe(16),
                                       dbname="ai_frecuencias", driver="psycopg")
        contenedor.with_env("TZ", "America/Bogota")
        contenedor.start()
    except Exception as exc:  # noqa: BLE001 - sin Docker no hay contenedor: se omite con el motivo
        pytest.skip(f"Docker o la imagen {IMAGEN} no están disponibles: {exc}")
    try:
        yield contenedor.get_connection_url()
    finally:
        contenedor.stop()


@pytest.fixture(scope="module")
def entorno_contenedor(url_contenedor, tmp_path_factory):
    """Apunta la API al contenedor y a una COPIA de datos/ (nada escribe en el repositorio); restaura al salir.

    El motor de app.db es global: se guarda el de la base local, se usa uno nuevo contra el contenedor y al terminar
    se devuelve el original, para que el resto de la suite siga en la base compartida.
    """
    from app import db
    from app.config import obtener_ajustes
    from app.servicios import datos, inferencia

    copia = tmp_path_factory.mktemp("datos_tc") / "datos"
    shutil.copytree(RAIZ / "datos", copia)
    mp = pytest.MonkeyPatch()
    previo = (db._motor, db._fabrica)
    for nombre, valor in {"DATABASE_URL": url_contenedor, "DATA_DIR": str(copia),
                          "MODELOS_DIR": str(copia / "modelos"), "REANUDAR_EJECUCIONES": "false",
                          "MAX_REINTENTOS": "1", "AUTH_HABILITADA": "true", "API_KEYS": API_KEYS,
                          "PLANIFICADOR_HABILITADO": "false", "FUENTE": "parquet"}.items():
        mp.setenv(nombre, valor)
    obtener_ajustes.cache_clear()
    datos.limpiar_cache()
    inferencia.limpiar_cache()
    db._motor, db._fabrica = None, None
    try:
        yield {"url": url_contenedor, "datos": copia}
    finally:
        if db._motor is not None:
            db._motor.dispose()
        db._motor, db._fabrica = previo
        mp.undo()
        obtener_ajustes.cache_clear()
        datos.limpiar_cache()
        inferencia.limpiar_cache()


@pytest.fixture(scope="module")
def migrado(entorno_contenedor):
    """Esquema creado con Alembic desde cero en el contenedor."""
    alembic(entorno_contenedor["url"], "upgrade", "head")
    return entorno_contenedor


@pytest.fixture(scope="module")
def cliente_tc(migrado):
    """TestClient con autenticación ENCENDIDA y la clave admin de esta sesión."""
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app, headers={"X-API-Key": CLAVES["admin"]}) as c:
        yield c


@pytest.fixture
def claves_tc() -> dict[str, str]:
    return dict(CLAVES)
