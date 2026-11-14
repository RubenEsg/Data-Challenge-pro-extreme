"""Pruebas de integración contra el PostgreSQL LOCAL (docker compose, servicio «db»).

Usan una base aparte, ai_frecuencias_pruebas (o TEST_DATABASE_NAME), en el mismo servidor local; la crean si no
existe y la migran desde cero. La URL sale de TEST_DATABASE_URL o, si no está, de DATABASE_URL (entorno o .env).

Se omiten, con el motivo en el informe de pytest y sin errores, cuando:
- no hay ninguna URL (checkout limpio sin .env): defina TEST_DATABASE_URL, por ejemplo
  postgresql+psycopg://sobusa:<clave>@localhost:5433/ai_frecuencias, o copie .env.example a .env;
- la URL no apunta a localhost/127.0.0.1/db: nunca se conectan a la base del reto;
- el PostgreSQL local no responde.

La clave de la base nunca se muestra: el fixture «migrada» entrega la URL completa para conectarse, pero su repr (lo
que pytest imprime en un traceback o con --showlocals) la oculta, igual que los motivos de omisión.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

RAIZ = Path(__file__).resolve().parents[2]
HOSTS_LOCALES = {"localhost", "127.0.0.1", "db", "::1"}
SIN_URL = ("no hay base local de pruebas. Defina TEST_DATABASE_URL (por ejemplo "
           "postgresql+psycopg://sobusa:<clave>@localhost:5433/ai_frecuencias) o DATABASE_URL en .env "
           "(ver .env.example) y levante el servicio «db» con docker compose")


class UrlOculta(str):
    """URL completa para conectarse (str); su repr oculta la clave, para que no quede en tracebacks ni en el CI."""

    def __repr__(self) -> str:
        return repr(_sin_clave(str(self)))


def _sin_clave(url: str) -> str:
    try:
        return make_url(url).render_as_string(hide_password=True)
    except Exception:  # noqa: BLE001
        return "<url inválida>"


def _url_base() -> str:
    if os.environ.get("TEST_DATABASE_URL"):
        return os.environ["TEST_DATABASE_URL"]
    from app.config import Ajustes

    return Ajustes().database_url


def _preparar() -> tuple[str | None, str | None]:
    """(URL de la base de pruebas, motivo de omisión). Nunca lanza: la omisión la aplican los fixtures."""
    crudo = (_url_base() or "").strip()
    if not crudo:
        return None, SIN_URL
    try:
        url = make_url(crudo)
    except Exception:  # noqa: BLE001
        return None, f"TEST_DATABASE_URL o DATABASE_URL no es una URL válida; {SIN_URL}"
    if url.host not in HOSTS_LOCALES:
        return None, f"las pruebas solo corren contra un PostgreSQL local (host={url.host!r})"
    url_pruebas = url.set(database=os.environ.get("TEST_DATABASE_NAME", "ai_frecuencias_pruebas"))
    try:
        admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT",
                              connect_args={"connect_timeout": 3})
        with admin.connect() as c:
            existe = c.execute(text("SELECT 1 FROM pg_database WHERE datname = :n"),
                               {"n": url_pruebas.database}).scalar()
            if not existe:
                c.execute(text(f'CREATE DATABASE "{url_pruebas.database}"'))
        admin.dispose()
    except Exception as exc:  # noqa: BLE001
        detalle = str(exc).splitlines()[0] if str(exc) else type(exc).__name__
        return None, (f"PostgreSQL local no disponible en {url.host}:{url.port}: {type(exc).__name__}: "
                      f"{detalle.replace(url.password or '<sin clave>', '***')}")
    return UrlOculta(url_pruebas.render_as_string(hide_password=False)), None


URL_PRUEBAS, MOTIVO_OMISION = _preparar()


def requerir_base() -> str:
    """URL de la base de pruebas, u omite la prueba que la pide con el motivo (nunca AttributeError ni la clave)."""
    if URL_PRUEBAS is None:
        pytest.skip(f"pruebas de integración omitidas: {MOTIVO_OMISION or SIN_URL}")
    return URL_PRUEBAS


@pytest.fixture(scope="session", autouse=True)
def _base_local_de_pruebas():
    """Sin base local, todo el paquete de integración se omite con un motivo claro (en vez de fallar)."""
    requerir_base()


os.environ["DATABASE_URL"] = URL_PRUEBAS or ""
os.environ["REANUDAR_EJECUCIONES"] = "false"
os.environ["MAX_REINTENTOS"] = "1"

# §7.2: claves de PRUEBA nuevas en cada corrida (nunca en el repositorio); el entorno solo lleva sus hashes.
# La autenticación queda apagada salvo en tests/integracion/test_seguridad.py, que la enciende; aun así el cliente
# envía siempre la clave admin, de modo que las pruebas pasan igual con AUTH_HABILITADA=true.
CLAVES_PRUEBA = {rol: secrets.token_urlsafe(32) for rol in ("operador", "analista", "admin")}
os.environ["API_KEYS"] = json.dumps({hashlib.sha256(clave.encode()).hexdigest(): {"usuario": f"prueba_{rol}",
                                                                                "rol": rol}
                                     for rol, clave in CLAVES_PRUEBA.items()})
os.environ.setdefault("AUTH_HABILITADA", "false")
os.environ["SOBUSA_API_KEY"] = CLAVES_PRUEBA["admin"]


def _alembic(*args: str) -> None:
    from alembic.config import Config

    from alembic import command

    cfg = Config(str(RAIZ / "alembic.ini"))
    cfg.set_main_option("script_location", str(RAIZ / "alembic"))
    cfg.set_main_option("sqlalchemy.url", requerir_base().replace("%", "%%"))
    getattr(command, args[0])(cfg, *args[1:])


@pytest.fixture(scope="session")
def migrada():
    from app.config import obtener_ajustes

    requerir_base()
    obtener_ajustes.cache_clear()
    _alembic("downgrade", "base")
    _alembic("upgrade", "head")
    return URL_PRUEBAS


@pytest.fixture(scope="session")
def cliente(migrada):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app, headers={"X-API-Key": CLAVES_PRUEBA["admin"]}) as c:
        yield c


@pytest.fixture
def claves_prueba() -> dict[str, str]:
    return dict(CLAVES_PRUEBA)


@pytest.fixture(autouse=True)
def sin_registro_en_disco(monkeypatch):
    """La activación sincroniza el registro en disco de inferencia; en pruebas no se toca."""
    try:
        from app.servicios import inferencia

        monkeypatch.setattr(inferencia, "activar", lambda *a, **k: {"activo": a[0] if a else None})
    except Exception:  # noqa: BLE001
        pass


@pytest.fixture
def sesion(migrada):
    from app.db import nueva_sesion

    s = nueva_sesion()
    yield s
    s.close()


def restituir_umbrales(sesion, version: int) -> None:
    """threshold_config como estaba: sin las versiones que creó la prueba y con la anterior vigente. Restaurar los
    valores con otro PUT dejaría vigente una versión creada por PUT, y las pruebas de bajada de las migraciones
    (test_api_integracion::test_migracion_0005 y ::test_migracion_0007) suponen que la vigente es la de una migración.
    Ninguna prueba de integración deja vigente una versión que creó, en cualquier orden: las que crean versiones con
    PUT /thresholds, con los ajustes locales de PUT /catalogos/capacidad y /catalogos/flota o con
    ejecucion.nueva_version_umbrales lo llaman al terminar, directamente (consolidados, ALT-003, retención, ciclo
    intradía, convivencia con la capa de segmentos y gobierno de parámetros) o con el fixture umbrales_restituidos
    (gobierno de parámetros, recomendaciones, catálogos, seguridad y las de umbrales de test_api_integracion.py)."""
    sesion.rollback()
    sesion.execute(text("DELETE FROM ai_frecuencias.threshold_config WHERE version > :v"), {"v": version})
    sesion.execute(text("UPDATE ai_frecuencias.threshold_config SET vigente = (version = :v)"), {"v": version})
    sesion.commit()


@pytest.fixture
def umbrales_restituidos(sesion):
    """La versión vigente de threshold_config al empezar la prueba; al terminar, aunque falle, restituir_umbrales con
    ella (borra las versiones que la prueba creó y deja vigente la de antes)."""
    from app.servicios import ejecucion

    sesion.rollback()
    version, _ = ejecucion.umbrales_vigentes(sesion)
    sesion.rollback()
    yield version
    restituir_umbrales(sesion, version)
