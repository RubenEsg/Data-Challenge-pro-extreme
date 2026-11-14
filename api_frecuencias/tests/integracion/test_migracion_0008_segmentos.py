"""Migración 0008, agregación materializada de la capa de segmentos (§6.1, §7.1, RNF-002, RNF-004): sube y baja.

En una base vacía y desechable del mismo PostgreSQL local, para no dejar a medias la base compartida de la suite: sube
a 0008 (tres tablas, sus índices y el tipo «segmentos» en ck_execution_log_tipo), siembra una ejecución «segmentos»
con su intento y su refresco y una «frecuencia» con el suyo, sube a head, baja a 0007 (se va todo lo de la 0008, con
las ejecuciones «segmentos» y su intento; la «frecuencia» queda), vuelve a 0008 y termina en head. Solo usa nombres de
revisión y head: las migraciones posteriores a la 0010 suben y bajan dentro de la misma prueba.
"""
from __future__ import annotations

import importlib.util
import re
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

E = "ai_frecuencias"
RAIZ = Path(__file__).resolve().parents[2]
TABLAS_0008 = {"segmento_estadistica_dia", "segmento_estadistica", "segmento_estadistica_refresco"}
INDICES_0008 = {
    "pk_segmento_estadistica_dia", "ix_segmento_estadistica_dia_fecha", "ix_segmento_estadistica_dia_ruta_fecha",
    "ux_segmento_estadistica_clave", "ix_segmento_estadistica_orden", "ix_segmento_estadistica_segmento",
    "ix_segmento_estadistica_dia_hora", "segmento_estadistica_refresco_pkey",
    "ix_segmento_estadistica_refresco_reciente",
}
TIPOS_0007 = {"frecuencia", "entrenamiento", "respuesta"}     # ck_execution_log_tipo antes de la 0008 (la deja la 0006)
EN_0008 = {"version": "0008", "tablas": TABLAS_0008, "indices": INDICES_0008, "tipos": TIPOS_0007 | {"segmentos"}}


def _config(url: str | None = None):
    from alembic.config import Config

    cfg = Config(str(RAIZ / "alembic.ini"))
    cfg.set_main_option("script_location", str(RAIZ / "alembic"))
    if url:
        cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return cfg


def _migrar(url: str, accion: str, revision: str) -> None:
    from alembic import command

    getattr(command, accion)(_config(url), revision)


def _cabeza() -> str:
    from alembic.script import ScriptDirectory

    return ScriptDirectory.from_config(_config()).get_current_head()


@pytest.fixture
def base_vacia(migrada):
    """Base vacía en el mismo servidor local que la de pruebas; se borra al terminar, pase lo que pase."""
    url = make_url(str(migrada))
    nombre = f"{url.database}_m0008_{uuid.uuid4().hex[:6]}"
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text(f'CREATE DATABASE "{nombre}"'))
    try:
        yield url.set(database=nombre).render_as_string(hide_password=False)
    finally:
        with admin.connect() as c:
            c.execute(text(f'DROP DATABASE IF EXISTS "{nombre}" WITH (FORCE)'))
        admin.dispose()


def _foto(url: str) -> dict:
    """Lo que la 0008 crea o borra en el esquema propio, leído del catálogo de PostgreSQL, y las ejecuciones."""
    motor = create_engine(url)
    try:
        with motor.connect() as c:
            def nombres(sql: str, buscados: set[str]) -> set[str]:
                return set(c.execute(text(sql), {"e": E, "n": sorted(buscados)}).scalars())

            restriccion = c.execute(text("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = "
                                         "'ck_execution_log_tipo' AND conrelid = CAST(:t AS regclass)"),
                                    {"t": f"{E}.execution_log"}).scalar()
            return {
                "version": c.execute(text(f"SELECT version_num FROM {E}.alembic_version")).scalar(),
                "tablas": nombres("SELECT tablename FROM pg_tables WHERE schemaname = :e "
                                  "AND tablename = ANY(CAST(:n AS text[]))", TABLAS_0008),
                "indices": nombres("SELECT indexname FROM pg_indexes WHERE schemaname = :e "
                                   "AND indexname = ANY(CAST(:n AS text[]))", INDICES_0008),
                "tipos": set(re.findall(r"'([^']+)'", restriccion or "")),
                "ejecuciones": dict(c.execute(text(f"SELECT tipo, count(*) FROM {E}.execution_log GROUP BY tipo"))
                                    .all()),
                "intentos": c.execute(text(f"SELECT count(*) FROM {E}.execution_attempt")).scalar(),
            }
    finally:
        motor.dispose()


def _sembrar(url: str) -> None:
    """En 0008: una ejecución «segmentos» con su intento y su refresco, y una «frecuencia» con su intento."""
    motor = create_engine(url)
    try:
        with motor.begin() as c:
            for tipo in ("segmentos", "frecuencia"):
                ident = uuid.uuid4()
                c.execute(text(f"INSERT INTO {E}.execution_log (execution_id, tipo, estado, progreso, intentos) "
                               "VALUES (:i, :t, 'ok', 100, 1)"), {"i": ident, "t": tipo})
                c.execute(text(f"INSERT INTO {E}.execution_attempt (execution_id, intento, worker_id, resultado) "
                               "VALUES (:i, 1, 'prueba-0008', 'ok')"), {"i": ident})
            c.execute(text(f"INSERT INTO {E}.segmento_estadistica_refresco (execution_id, modo, fecha_min, "
                           "fecha_max, filas_dia, filas) SELECT execution_id, 'completo', DATE '2025-03-01', "
                           f"DATE '2025-03-02', 48, 24 FROM {E}.execution_log WHERE tipo = 'segmentos'"))
    finally:
        motor.dispose()


def test_migracion_0008_segmentos_materializados_sube_y_baja(base_vacia):
    spec = importlib.util.spec_from_file_location(
        "m0008", RAIZ / "alembic" / "versions" / "0008_segmentos_materializados.py")
    m0008 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m0008)
    assert (m0008.revision, m0008.down_revision) == ("0008", "0007")
    assert set(m0008.TABLAS_0008) == TABLAS_0008 and m0008.TIPO == "segmentos"

    _migrar(base_vacia, "upgrade", "0008")
    foto = _foto(base_vacia)
    assert {k: foto[k] for k in EN_0008} == EN_0008
    _sembrar(base_vacia)
    _migrar(base_vacia, "upgrade", "head")                   # las posteriores suben con los datos de la 0008
    foto = _foto(base_vacia)
    assert foto["version"] == _cabeza() and foto["tablas"] == TABLAS_0008 and "segmentos" in foto["tipos"]

    _migrar(base_vacia, "downgrade", "0007")                 # baja también las posteriores, sean las que sean
    foto = _foto(base_vacia)
    assert foto["version"] == "0007" and foto["tablas"] == set() and foto["indices"] == set()
    assert foto["tipos"] == TIPOS_0007
    assert foto["ejecuciones"] == {"frecuencia": 1} and foto["intentos"] == 1   # solo la «segmentos» y su intento

    _migrar(base_vacia, "upgrade", "0008")
    foto = _foto(base_vacia)
    assert {k: foto[k] for k in EN_0008} == EN_0008
    assert foto["ejecuciones"] == {"frecuencia": 1}
    _migrar(base_vacia, "upgrade", "head")
    assert _foto(base_vacia)["version"] == _cabeza()
