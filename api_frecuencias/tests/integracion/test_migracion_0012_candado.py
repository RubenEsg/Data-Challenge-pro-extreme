"""Integración: la migración 0012 espera el candado de los escritores de threshold_config al subir y al bajar (§5.1
«se versionan», como PUT /thresholds y las migraciones 0013 y 0014).

Otra conexión toma el candado de ejecucion.bloquear_umbrales (como un PUT /thresholds de otra réplica a mitad del
despliegue) y la migración corre en un hilo: mientras el candado esté tomado, la migración no avanza (su conexión
espera un candado de asesoría en pg_locks) y la revisión de alembic no cambia; al soltarlo, termina. Lo que venga
después de la 0012 se baja antes y vuelve a subir al final (upgrade head), como en test_migracion_0012_sube_y_baja.
"""
from __future__ import annotations

import importlib.util
import threading
import time

from sqlalchemy import create_engine, text

ESPERA_S = 2.0


def _migracion_0012():
    from tests.integracion.conftest import RAIZ

    spec = importlib.util.spec_from_file_location(
        "m0012_candado", RAIZ / "alembic" / "versions" / "0012_retencion_y_ventana_segmentos.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def _revision(motor) -> str:
    with motor.connect() as c:
        return c.execute(text("SELECT version_num FROM ai_frecuencias.alembic_version")).scalar()


def _esperando_un_candado(motor) -> int:
    """Conexiones de ESTA base que esperan un candado de asesoría (la migración bloqueada)."""
    with motor.connect() as c:
        return int(c.execute(text(
            "SELECT count(*) FROM pg_locks l JOIN pg_database d ON d.oid = l.database "
            "WHERE l.locktype = 'advisory' AND NOT l.granted AND d.datname = current_database()")).scalar())


def _migrar_con_el_candado_tomado(motor, sql_candado: str, paso: str, destino: str) -> None:
    """Toma el candado en otra conexión, corre la migración en un hilo y comprueba que espera hasta soltarlo."""
    from tests.integracion.conftest import _alembic

    errores: list[BaseException] = []

    def migrar() -> None:
        try:
            _alembic(paso, destino)
        except BaseException as exc:  # noqa: BLE001 - el hilo informa la falla a la prueba
            errores.append(exc)

    antes = _revision(motor)
    hilo = threading.Thread(target=migrar, name=f"migracion-{paso}", daemon=True)
    with motor.connect() as dueno:
        dueno.execute(text(sql_candado))                 # transacción abierta: el candado queda tomado
        hilo.start()
        limite = time.monotonic() + 30
        while _esperando_un_candado(motor) == 0 and hilo.is_alive() and time.monotonic() < limite:
            time.sleep(0.1)
        hilo.join(timeout=ESPERA_S)
        assert hilo.is_alive(), f"la migración ({paso} a {destino}) no esperó el candado: {errores}"
        assert _esperando_un_candado(motor) >= 1
        assert _revision(motor) == antes                 # nada se aplicó mientras el candado está tomado
        dueno.rollback()                                 # suelta el candado
    hilo.join(timeout=180)
    assert not hilo.is_alive() and not errores, errores
    assert _revision(motor) == destino


def test_la_0012_espera_el_candado_de_threshold_config_al_bajar_y_al_subir(migrada, sesion):
    from app.servicios.ejecucion import SQL_CANDADO_UMBRALES
    from tests.integracion.conftest import _alembic

    m = _migracion_0012()
    assert m.CANDADO_UMBRALES == SQL_CANDADO_UMBRALES.text
    sesion.commit()
    motor = create_engine(migrada)
    try:
        _alembic("downgrade", m.revision)                # lo que venga después de la 0012 queda fuera
        assert _revision(motor) == m.revision
        _migrar_con_el_candado_tomado(motor, m.CANDADO_UMBRALES, "downgrade", m.down_revision)
        _migrar_con_el_candado_tomado(motor, m.CANDADO_UMBRALES, "upgrade", m.revision)
    finally:
        sesion.rollback()
        _alembic("upgrade", "head")
        motor.dispose()
    with sesion.get_bind().connect() as c:
        assert c.execute(text("SELECT count(*) FROM ai_frecuencias.threshold_config WHERE vigente")).scalar() > 0
