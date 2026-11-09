"""Unidad de la cola (sin base): identidad de réplica, espera de reintento, bucle del trabajador y despacho."""
from __future__ import annotations

import threading
import time
import uuid
from types import SimpleNamespace

from app.servicios import cola


def _ajustes(**k):
    base = dict(trabajador_id="", lease_segundos=30.0, sondeo_cola_segundos=0.01, max_reintentos=3,
                trabajadores_efectivos=1)
    return SimpleNamespace(**(base | k))


def test_espera_reintento_exponencial_con_tope():
    assert [cola.espera_reintento(n) for n in (1, 2, 3, 4)] == [2.0, 4.0, 8.0, 16.0]
    assert cola.espera_reintento(20) == 60.0
    assert cola.espera_reintento(1, base=0.5) == 0.5


def test_identidad_sin_dos_puntos_y_proceso(monkeypatch):
    monkeypatch.setattr(cola, "obtener_ajustes", lambda: _ajustes(trabajador_id="api:réplica 1"))
    assert cola.identidad_replica() == "api-r-plica-1"
    replica, pid, arranque = cola.identidad_proceso().split(":")
    assert replica == "api-r-plica-1" and pid.isdigit() and len(arranque) == 6


def test_identidad_por_omision_es_el_equipo(monkeypatch):
    monkeypatch.setattr(cola, "obtener_ajustes", lambda: _ajustes())
    monkeypatch.setenv("HOSTNAME", "contenedor-7f3a")
    assert cola.identidad_replica() == "contenedor-7f3a"


def test_trabajador_reclama_corre_y_para(monkeypatch):
    monkeypatch.setattr(cola, "obtener_ajustes", lambda: _ajustes())
    trabajos = [cola.Reclamo(uuid.uuid4(), "frecuencia", 1, "w"), cola.Reclamo(uuid.uuid4(), "entrenamiento", 1, "w")]
    barridos = []
    monkeypatch.setattr(cola, "liberar_vencidas", lambda *a: barridos.append(1) or [])
    monkeypatch.setattr(cola, "reclamar", lambda *a, **k: trabajos.pop(0) if trabajos else None)
    monkeypatch.setattr(cola, "correr_reclamo", lambda r, **k: "ok")
    parada = threading.Event()
    t = cola.Trabajador(1, parada, worker_id="r:1:abcdef:t1", lease_s=1.5, sondeo_s=0.01)
    t.start()
    fin = time.monotonic() + 5
    while len(t.hechos) < 2 and time.monotonic() < fin:
        time.sleep(0.01)
    parada.set()
    t.join(timeout=5)
    assert not t.is_alive() and [r for _, r in t.hechos] == ["ok", "ok"] and barridos


def test_trabajador_sobrevive_a_la_base_caida(monkeypatch):
    monkeypatch.setattr(cola, "obtener_ajustes", lambda: _ajustes())
    llamadas = []

    def falla(*a, **k):
        llamadas.append(1)
        raise ConnectionError("base caída")

    monkeypatch.setattr(cola, "liberar_vencidas", falla)
    parada = threading.Event()
    t = cola.Trabajador(1, parada, worker_id="r:1:abcdef:t1", lease_s=1.5, sondeo_s=0.01)
    t.start()
    time.sleep(0.2)
    parada.set()
    t.join(timeout=5)
    assert not t.is_alive() and llamadas  # no murió: esperó y siguió intentando


def test_correr_reclamo_clasifica_fallos(monkeypatch):
    from app.servicios import ejecucion

    monkeypatch.setattr(cola, "obtener_ajustes", lambda: _ajustes())
    monkeypatch.setattr(cola, "renovar", lambda *a, **k: True)
    vistos = []
    monkeypatch.setattr(cola, "_registrar_fallo", lambda r, exc, definitiva, espera: vistos.append(
        (type(exc).__name__, definitiva, espera)) or ("error" if definitiva else "reintento"))

    def transitorio(_):
        raise RuntimeError("x")

    def configuracion(_):
        raise ejecucion.ErrorNoReintentable("FUENTE desconocida")

    monkeypatch.setattr(ejecucion, "_ciclo_frecuencia", transitorio)
    assert cola.correr_reclamo(cola.Reclamo(uuid.uuid4(), "frecuencia", 1, "w"), max_reintentos=3) == "reintento"
    assert cola.correr_reclamo(cola.Reclamo(uuid.uuid4(), "frecuencia", 3, "w"), max_reintentos=3) == "error"
    monkeypatch.setattr(ejecucion, "_ciclo_frecuencia", configuracion)
    assert cola.correr_reclamo(cola.Reclamo(uuid.uuid4(), "frecuencia", 1, "w"), max_reintentos=3) == "error"
    assert vistos == [("RuntimeError", False, 2.0), ("RuntimeError", True, 8.0), ("ErrorNoReintentable", True, 2.0)]
    assert cola.trabajador_actual.get() is None  # el contexto del trabajador se limpia siempre


def test_correr_reclamo_pone_el_trabajador_en_contexto(monkeypatch):
    from app.servicios import ejecucion

    monkeypatch.setattr(cola, "obtener_ajustes", lambda: _ajustes())
    monkeypatch.setattr(cola, "renovar", lambda *a, **k: True)
    visto = {}
    monkeypatch.setattr(ejecucion, "_ciclo_entrenamiento",
                        lambda i: visto.setdefault("w", cola.trabajador_actual.get()))
    assert cola.correr_reclamo(cola.Reclamo(uuid.uuid4(), "entrenamiento", 1, "r:1:abcdef:t9")) == "ok"
    assert visto["w"] == "r:1:abcdef:t9"


def test_ejecutar_despacha_a_la_cola_o_procesa_aqui(monkeypatch):
    from app.servicios import ejecucion

    procesadas = []
    monkeypatch.setattr(cola, "procesar", lambda i, **k: procesadas.append(i))
    ident = uuid.uuid4()
    monkeypatch.setattr(ejecucion, "obtener_ajustes", lambda: _ajustes(trabajadores_efectivos=2))
    ejecucion.ejecutar(ident)
    assert procesadas == []  # con trabajadores: la toma cualquier réplica desde la cola
    monkeypatch.setattr(ejecucion, "obtener_ajustes", lambda: _ajustes(trabajadores_efectivos=0))
    ejecucion.ejecutar(ident)
    assert procesadas == [ident]


def test_trabajadores_efectivos():
    from app.config import Ajustes

    assert Ajustes(trabajadores=2, reanudar_ejecuciones=True).trabajadores_efectivos == 2
    assert Ajustes(trabajadores=2, reanudar_ejecuciones=False).trabajadores_efectivos == 0
    assert Ajustes(trabajadores=-1, reanudar_ejecuciones=True).trabajadores_efectivos == 0


def test_iniciar_sin_trabajadores_no_arranca_hilos(monkeypatch):
    monkeypatch.setattr(cola, "obtener_ajustes", lambda: _ajustes(trabajadores_efectivos=0))
    assert cola.iniciar() == [] and cola.detener() == []
