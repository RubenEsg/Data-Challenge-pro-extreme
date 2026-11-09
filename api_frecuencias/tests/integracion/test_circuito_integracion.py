"""RNF-010 con conexiones reales: una fuente PostgreSQL que rechaza la conexión (puerto cerrado) abre el circuito, que
se ve en /health y /metrics; tras el reinicio, un ensayo contra el PostgreSQL LOCAL lo cierra. La evidencia
(seguridad/resiliencia.txt) va a docs/evidencias solo con GENERAR_EVIDENCIAS=1 (tests/evidencia.py); si no, a un
directorio temporal. Nunca toca la base del reto."""
from __future__ import annotations

import socket
import time

import pytest
from sqlalchemy import create_engine

from tests.evidencia import guardar_evidencia


def _puerto_cerrado() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]          # al cerrar el socket nadie escucha en ese puerto: conexión rechazada


@pytest.fixture
def circuito_corto(cliente, monkeypatch):
    from app.config import obtener_ajustes
    from app.servicios import circuito

    monkeypatch.setattr(obtener_ajustes(), "circuito_fuente_reinicio_s", 1.5)
    circuito.reiniciar_todos()
    circuito.registrar_integraciones()
    yield circuito
    circuito.reiniciar_todos()
    circuito.registrar_integraciones()


def _estado_metricas(cliente) -> str:
    lineas = [x for x in cliente.get("/metrics").text.splitlines()
              if x.startswith("api_circuito") and 'integracion="fuente_postgres"' in x]
    return "\n".join(f"    {x}" for x in lineas)


def test_circuito_de_la_fuente_con_conexiones_reales(cliente, circuito_corto, migrada):
    from app.servicios import fuentes

    caida = fuentes.FuentePostgresSoloLectura(
        url=f"postgresql+psycopg://lector@127.0.0.1:{_puerto_cerrado()}/no_existe?connect_timeout=2")
    sana = fuentes.FuentePostgresSoloLectura(url=migrada, motor=create_engine(migrada, pool_size=1, max_overflow=0))
    registro = ["RNF-010 · circuit breaker de la fuente PostgreSQL (fallos_max=3, reinicio 1,5 s en esta prueba)",
                f"1) cerrado al inicio: /health -> {cliente.get('/health').json()['integraciones']['fuente_postgres']}"]
    for i in range(3):
        t0 = time.perf_counter()
        with pytest.raises(Exception) as exc:
            caida.consultar("SELECT 1")
        registro.append(f"   fallo de conexión {i + 1}: {type(exc.value).__name__} en {time.perf_counter() - t0:.3f} s")
    salud = cliente.get("/health").json()
    assert salud["integraciones"]["fuente_postgres"]["estado"] == "abierto" and salud["estado"] == "degradado"
    t0 = time.perf_counter()
    with pytest.raises(circuito_corto.CircuitoAbierto):
        caida.consultar("SELECT 1")
    rapido = time.perf_counter() - t0
    assert rapido < 0.05
    registro += [f"2) abierto: la 4.ª llamada falla rápido con CircuitoAbierto en {rapido * 1000:.2f} ms sin conectar",
                 f"   /health -> estado={salud['estado']} fuente_postgres={salud['integraciones']['fuente_postgres']}",
                 "   /metrics:", _estado_metricas(cliente)]
    with pytest.raises(fuentes.OperacionNoPermitida):
        sana.consultar("DELETE FROM rutas")                # error de datos: no cuenta para el circuito
    time.sleep(1.6)
    salud = cliente.get("/health").json()
    assert salud["integraciones"]["fuente_postgres"]["estado"] == "semiabierto"
    registro.append(f"3) tras el reinicio: /health -> fuente_postgres={salud['integraciones']['fuente_postgres']}")
    filas = sana.consultar("SELECT 1 AS uno")                 # ensayo semiabierto contra el PostgreSQL local
    assert filas.iloc[0]["uno"] == 1
    salud = cliente.get("/health").json()
    assert salud["integraciones"]["fuente_postgres"]["estado"] == "cerrado" and salud["estado"] == "ok"
    registro += [f"4) ensayo bien (SELECT 1 local) -> cerrado: /health -> estado={salud['estado']} "
                 f"fuente_postgres={salud['integraciones']['fuente_postgres']}", "   /metrics:",
                 _estado_metricas(cliente)]
    guardar_evidencia("seguridad/resiliencia.txt", "\n".join(registro) + "\n")
