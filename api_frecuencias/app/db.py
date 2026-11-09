"""Conexión a la base de resultados propia (PostgreSQL local, esquema ai_frecuencias).

TIMESTAMPTZ se guarda en UTC; la sesión usa America/Bogota para presentar las fechas con su zona (-05:00).
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import obtener_ajustes

_motor: Engine | None = None
_fabrica: sessionmaker[Session] | None = None

MENSAJE_SIN_URL = (
    "Falta DATABASE_URL: defina la URL de la base de resultados (esquema ai_frecuencias) en la variable de entorno "
    "DATABASE_URL o en el archivo .env (vea .env.example). El código no trae una URL por omisión."
)


def url_resultados() -> str:
    """URL de la base de resultados; falla con un mensaje claro si DATABASE_URL no está definida."""
    url = obtener_ajustes().database_url.strip()
    if not url:
        raise RuntimeError(MENSAJE_SIN_URL)
    return url


def motor() -> Engine:
    global _motor, _fabrica
    if _motor is None:
        _motor = create_engine(
            url_resultados(),
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=5,
            connect_args={"options": "-c timezone=America/Bogota", "connect_timeout": 5},
        )
        _fabrica = sessionmaker(bind=_motor, expire_on_commit=False)
    return _motor


def nueva_sesion() -> Session:
    motor()
    if _fabrica is None:  # pragma: no cover - motor() siempre la crea
        raise RuntimeError("No se pudo crear la fábrica de sesiones")
    return _fabrica()


@contextmanager
def sesion_contexto() -> Iterator[Session]:
    sesion = nueva_sesion()
    try:
        yield sesion
        sesion.commit()
    except Exception:
        sesion.rollback()
        raise
    finally:
        sesion.close()


def obtener_sesion() -> Iterator[Session]:
    """Dependencia de FastAPI: una sesión por petición."""
    sesion = nueva_sesion()
    try:
        yield sesion
    finally:
        sesion.close()


def base_disponible() -> bool:
    try:
        with motor().connect() as conexion:
            conexion.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
