"""Entorno de Alembic: migra solo el esquema propio ai_frecuencias (tabla de versiones incluida)."""
from __future__ import annotations

from logging.config import fileConfig

from sqlalchemy import create_engine, pool, text

from alembic import context
from app.config import ESQUEMA, obtener_ajustes
from app.modelos_db import Base

config = context.config
if config.config_file_name is not None:
    # disable_existing_loggers=False: no apaga los loggers de la API cuando la migración corre en el mismo proceso
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def _url() -> str:
    return config.get_main_option("sqlalchemy.url") or obtener_ajustes().database_url


def run_migrations_offline() -> None:
    context.configure(
        url=_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        version_table_schema=ESQUEMA,
        include_schemas=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    motor = create_engine(_url(), poolclass=pool.NullPool)
    with motor.connect() as conexion:
        conexion.execute(text(f"CREATE SCHEMA IF NOT EXISTS {ESQUEMA}"))
        conexion.commit()
        context.configure(
            connection=conexion,
            target_metadata=target_metadata,
            version_table_schema=ESQUEMA,
            include_schemas=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
