"""Pruebas de integración contra el PostgreSQL LOCAL (docker compose, servicio «db»).

Usan una base aparte, ai_frecuencias_pruebas, en el mismo servidor local; la crean si no existe y la migran desde
cero. Nunca se conectan a la base del reto: si la URL no apunta a localhost/127.0.0.1/db, las pruebas se omiten.
Si la base local no responde, se omiten con un mensaje claro.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

RAIZ = Path(__file__).resolve().parents[2]
HOSTS_LOCALES = {"localhost", "127.0.0.1", "db", "::1"}


def _url_base() -> str:
    if os.environ.get("TEST_DATABASE_URL"):
        return os.environ["TEST_DATABASE_URL"]
    from app.config import Ajustes

    return Ajustes().database_url


def _preparar() -> str | None:
    try:
        url = make_url(_url_base())
    except Exception:  # noqa: BLE001
        return None
    if url.host not in HOSTS_LOCALES:
        pytest.skip(f"Las pruebas solo corren contra un PostgreSQL local (host={url.host!r})", allow_module_level=True)
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
        pytest.skip(f"PostgreSQL local no disponible: {exc}", allow_module_level=True)
    return url_pruebas.render_as_string(hide_password=False)


URL_PRUEBAS = _preparar()
os.environ["DATABASE_URL"] = URL_PRUEBAS or ""
os.environ["REANUDAR_EJECUCIONES"] = "false"
os.environ["MAX_REINTENTOS"] = "1"


def _alembic(*args: str) -> None:
    from alembic.config import Config

    from alembic import command

    cfg = Config(str(RAIZ / "alembic.ini"))
    cfg.set_main_option("script_location", str(RAIZ / "alembic"))
    cfg.set_main_option("sqlalchemy.url", URL_PRUEBAS.replace("%", "%%"))
    getattr(command, args[0])(cfg, *args[1:])


@pytest.fixture(scope="session")
def migrada():
    from app.config import obtener_ajustes

    obtener_ajustes.cache_clear()
    _alembic("downgrade", "base")
    _alembic("upgrade", "head")
    return URL_PRUEBAS


@pytest.fixture(scope="session")
def cliente(migrada):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


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
