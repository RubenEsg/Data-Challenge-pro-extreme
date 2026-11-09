"""Integración de la cola (RNF-001, RNF-004, RNF-005): réplicas, reservas que vencen, reintentos, cerca y planificador.

Cada «réplica» es un hilo Trabajador con su propia identidad y sus propias conexiones a la base LOCAL de pruebas.
El cuerpo del ciclo se reemplaza por uno corto que cierra con cola.cerrar_ok (la misma cerca que el ciclo real).
"""
from __future__ import annotations

import threading
import time
import uuid
from collections import Counter
from datetime import datetime, timedelta

import pytest
from sqlalchemy import text

E = "ai_frecuencias"


@pytest.fixture
def cola_limpia(migrada):
    """Ninguna fila pendiente de otras pruebas: los trabajadores de estas pruebas solo ven sus trabajos."""
    from app.db import sesion_contexto

    def limpiar():
        with sesion_contexto() as s:
            s.execute(text(f"UPDATE {E}.execution_log SET estado = 'error', worker_id = NULL, lease_hasta = NULL, "
                           "mensaje = 'limpieza de prueba' WHERE estado IN ('en_cola', 'corriendo')"))

    limpiar()
    yield
    limpiar()


def _crear(n: int, tipo: str) -> list[uuid.UUID]:
    from app.db import sesion_contexto
    from app.servicios import ejecucion

    ids = []
    with sesion_contexto() as s:
        for _ in range(n):
            ids.append(ejecucion.crear_ejecucion(s, tipo, {"prueba": "cola"}, "prueba-cola").execution_id)
    return ids


def _intentos(ids) -> list[tuple]:
    from app.db import sesion_contexto

    with sesion_contexto() as s:
        return s.execute(text(f"SELECT execution_id, intento, worker_id, resultado FROM {E}.execution_attempt "
                              "WHERE execution_id = ANY(CAST(:ids AS uuid[])) ORDER BY execution_id, intento"),
                         {"ids": [str(i) for i in ids]}).all()


def _estados(ids) -> Counter:
    from app.db import sesion_contexto

    with sesion_contexto() as s:
        return Counter(s.execute(text(f"SELECT estado FROM {E}.execution_log "
                                      "WHERE execution_id = ANY(CAST(:ids AS uuid[]))"),
                                 {"ids": [str(i) for i in ids]}).scalars())


@pytest.fixture
def ciclo_falso(monkeypatch):
    """Ciclo corto: cuenta cuántas veces se CONFIRMA cada ejecución y la concurrencia de 'frecuencia'."""
    from app.db import sesion_contexto
    from app.servicios import cola, ejecucion

    estado = {"confirmadas": Counter(), "frec_activas": 0, "frec_max": 0, "fallar": set()}
    cerrojo = threading.Lock()

    def fabricar(tipo: str):
        def ciclo(execution_id):
            if tipo == "frecuencia":
                with cerrojo:
                    estado["frec_activas"] += 1
                    estado["frec_max"] = max(estado["frec_max"], estado["frec_activas"])
            try:
                time.sleep(0.03)
                if execution_id in estado["fallar"]:
                    estado["fallar"].discard(execution_id)
                    raise RuntimeError("falla transitoria simulada")
                with sesion_contexto() as s:
                    cola.cerrar_ok(s, execution_id, {"estado": "ok", "etapa": "terminada", "progreso": 100,
                                                     "terminado_en": ejecucion.ahora()})
                with cerrojo:
                    estado["confirmadas"][execution_id] += 1
            finally:
                if tipo == "frecuencia":
                    with cerrojo:
                        estado["frec_activas"] -= 1
        return ciclo

    monkeypatch.setattr(ejecucion, "_ciclo_frecuencia", fabricar("frecuencia"))
    monkeypatch.setattr(ejecucion, "_ciclo_entrenamiento", fabricar("entrenamiento"))
    return estado


def _esperar(ids, limite_s: float = 90.0) -> Counter:
    fin = time.monotonic() + limite_s
    while time.monotonic() < fin:
        estados = _estados(ids)
        if estados.get("ok", 0) + estados.get("error", 0) == len(ids):
            return estados
        time.sleep(0.1)
    return _estados(ids)


def test_dos_replicas_sin_duplicados(cola_limpia, ciclo_falso):
    from app.servicios import cola

    ids = _crear(30, "entrenamiento") + _crear(10, "frecuencia")
    parada = threading.Event()
    replicas = [cola.Trabajador(1, parada, worker_id="replica-a:1001:aaaaaa:t1", lease_s=5, sondeo_s=0.05),
                cola.Trabajador(2, parada, worker_id="replica-b:1002:bbbbbb:t1", lease_s=5, sondeo_s=0.05)]
    for r in replicas:
        r.start()
    try:
        estados = _esperar(ids)
    finally:
        parada.set()
        for r in replicas:
            r.join(timeout=10)
    assert estados == Counter({"ok": 40})
    intentos = _intentos(ids)
    ok_por_ejecucion = Counter(i.execution_id for i in intentos if i.resultado == "ok")
    assert set(ok_por_ejecucion) == set(ids) and set(ok_por_ejecucion.values()) == {1}
    assert set(ciclo_falso["confirmadas"].values()) == {1} and len(ciclo_falso["confirmadas"]) == 40
    por_replica = Counter(i.worker_id.split(":")[0] for i in intentos)
    assert por_replica["replica-a"] > 0 and por_replica["replica-b"] > 0 and sum(por_replica.values()) == 40
    assert ciclo_falso["frec_max"] == 1  # las de frecuencia nunca corren a la vez (marca de agua)


def test_reserva_vencida_se_reclama(cola_limpia, ciclo_falso):
    from app.servicios import cola

    (ident,) = _crear(1, "entrenamiento")
    muerto = cola.reclamar("muerta:2001:cccccc:t1", lease_s=0.3, execution_id=ident)
    assert muerto is not None and muerto.intentos == 1
    assert cola.reclamar("replica-b:2002:dddddd:t1", lease_s=5) is None  # reservada: nadie más la toma
    time.sleep(0.6)  # la réplica «murió»: nadie renueva la reserva
    assert ident in cola.liberar_vencidas(max_reintentos=3)
    r = cola.reclamar("replica-b:2002:dddddd:t1", lease_s=5)
    assert r is not None and r.execution_id == ident and r.intentos == 2
    assert cola.correr_reclamo(r, lease_s=5) == "ok"
    assert [(i.intento, i.worker_id.split(":")[0], i.resultado) for i in _intentos([ident])] == [
        (1, "muerta", "abandonado"), (2, "replica-b", "ok")]


def test_reintento_con_espera(cola_limpia, ciclo_falso):
    from app.db import sesion_contexto
    from app.servicios import cola

    (ident,) = _crear(1, "entrenamiento")
    ciclo_falso["fallar"].add(ident)
    r = cola.reclamar("replica-a:3001:eeeeee:t1", lease_s=5)
    assert cola.correr_reclamo(r, lease_s=5, max_reintentos=3, base_espera=0.6) == "reintento"
    with sesion_contexto() as s:
        fila = s.execute(text(f"SELECT estado, disponible_desde > now() AS en_espera, worker_id "
                              f"FROM {E}.execution_log WHERE execution_id = :i"), {"i": ident}).one()
    assert fila.estado == "en_cola" and fila.en_espera and fila.worker_id is None
    assert cola.reclamar("replica-b:3002:ffffff:t1", lease_s=5) is None  # todavía en espera (backoff)
    time.sleep(0.8)
    r2 = cola.reclamar("replica-b:3002:ffffff:t1", lease_s=5)
    assert r2 is not None and r2.intentos == 2 and cola.correr_reclamo(r2, lease_s=5) == "ok"
    assert [i.resultado for i in _intentos([ident])] == ["reintento", "ok"]


def test_reintentos_agotados_queda_error(cola_limpia, ciclo_falso):
    from app.servicios import cola

    (ident,) = _crear(1, "entrenamiento")
    ciclo_falso["fallar"].add(ident)
    r = cola.reclamar("replica-a:3101:aaaaaa:t1", lease_s=5)
    assert cola.correr_reclamo(r, lease_s=5, max_reintentos=1) == "error"
    assert _estados([ident]) == Counter({"error": 1})


def test_reinicio_no_roba_trabajo_vivo(cola_limpia):
    from app.servicios import cola

    (ident,) = _crear(1, "entrenamiento")
    assert cola.reclamar("viva:4001:aaaaaa:t1", lease_s=30, execution_id=ident) is not None
    assert ident not in cola.liberar_vencidas(max_reintentos=3)  # su reserva sigue vigente
    assert ident not in cola.liberar_propias("otra", "4002:bbbbbb", 3)  # otra réplica que reinicia
    assert ident not in cola.liberar_propias("viva", "4001:aaaaaa", 3)  # el mismo proceso vivo
    # la MISMA réplica reinició (proceso nuevo): lo de su proceso anterior vuelve a la cola al instante
    assert ident in cola.liberar_propias("viva", "4003:cccccc", 3)
    assert _estados([ident]) == Counter({"en_cola": 1})


def test_cerca_impide_resultados_duplicados(cola_limpia):
    from app.db import sesion_contexto
    from app.modelos_db import ErrorCalidad
    from app.servicios import cola

    (ident,) = _crear(1, "frecuencia")
    lenta = cola.reclamar("lenta:5001:aaaaaa:t1", lease_s=30, execution_id=ident)
    with sesion_contexto() as s:  # la reserva de la réplica lenta «vence» y otra réplica la retoma
        s.execute(text(f"UPDATE {E}.execution_log SET lease_hasta = now() - interval '1 second' "
                       "WHERE execution_id = :i"), {"i": ident})
    assert ident in cola.liberar_vencidas(max_reintentos=3)
    nueva = cola.reclamar("rapida:5002:bbbbbb:t1", lease_s=30, execution_id=ident)
    assert nueva is not None and nueva.intentos == 2

    token = cola.trabajador_actual.set(lenta.worker_id)
    try:
        with pytest.raises(cola.ReservaPerdida), sesion_contexto() as s:
            s.add(ErrorCalidad(execution_id=ident, lote="lenta", codigo="X", dimension="validez"))
            cola.cerrar_ok(s, ident, {"estado": "ok", "progreso": 100})
    finally:
        cola.trabajador_actual.reset(token)
    token = cola.trabajador_actual.set(nueva.worker_id)
    try:
        with sesion_contexto() as s:
            s.add(ErrorCalidad(execution_id=ident, lote="rapida", codigo="X", dimension="validez"))
            cola.cerrar_ok(s, ident, {"estado": "ok", "progreso": 100})
    finally:
        cola.trabajador_actual.reset(token)
    with sesion_contexto() as s:
        lotes = s.execute(text(f"SELECT lote FROM {E}.data_quality_error WHERE execution_id = :i"),
                          {"i": ident}).scalars().all()
    assert lotes == ["rapida"]  # los resultados del intento viejo se revirtieron completos
    assert _estados([ident]) == Counter({"ok": 1})


def test_procesar_sin_trabajadores_usa_la_reserva(cola_limpia, ciclo_falso):
    from app.servicios import cola

    (ident,) = _crear(1, "frecuencia")
    assert cola.procesar(ident) == "ok"
    assert cola.procesar(ident) == "ok"  # ya terminada: no la vuelve a correr
    assert ciclo_falso["confirmadas"][ident] == 1
    assert [i.resultado for i in _intentos([ident])] == ["ok"]


def test_apagado_ordenado_devuelve_el_trabajo_y_la_cerca_evita_el_doble_cierre(cola_limpia, monkeypatch):
    from app.db import sesion_contexto
    from app.servicios import cola, ejecucion

    adentro, confirmadas = threading.Event(), Counter()

    def ciclo_lento(execution_id):
        adentro.set()
        time.sleep(1.5)  # sigue corriendo cuando llega el SIGTERM
        with sesion_contexto() as s:
            cola.cerrar_ok(s, execution_id, {"estado": "ok", "progreso": 100})
        confirmadas[execution_id] += 1

    monkeypatch.setattr(ejecucion, "_ciclo_entrenamiento", ciclo_lento)
    (ident,) = _crear(1, "entrenamiento")
    hilos = cola.iniciar(1)
    try:
        assert adentro.wait(15)
        devueltas = cola.detener(espera_s=0.2)  # apagado ordenado: no espera a que termine
    finally:
        for h in hilos:
            h.join(timeout=15)
    assert devueltas == [ident] and _estados([ident]) == Counter({"en_cola": 1})
    assert confirmadas[ident] == 0  # el intento viejo no pudo cerrar: la cerca lo revirtió
    assert [i.resultado for i in _intentos([ident])] == ["abandonado"]


# ---------------------------------------------------------------- planificador
def test_planificador_una_fila_por_franja_con_dos_replicas(cola_limpia):
    from app.db import sesion_contexto
    from app.servicios import planificador

    franja = datetime(2026, 1, 5, 5, 15, tzinfo=planificador.ZONA) + timedelta(minutes=uuid.uuid4().int % 100000)
    resultados: list = []
    barrera = threading.Barrier(2)

    def replica():
        barrera.wait()
        resultados.append(planificador.encolar_franja("frecuencia", franja, {"origen": "prueba"}, "prueba"))

    hilos = [threading.Thread(target=replica) for _ in range(2)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()
    assert sum(r is not None for r in resultados) == 1
    assert planificador.encolar_franja("frecuencia", franja, {}, "otra vez") is None
    with sesion_contexto() as s:
        n = s.execute(text(f"SELECT count(*) FROM {E}.execution_log WHERE tipo = 'frecuencia' "
                           "AND programada_para = :f"), {"f": franja}).scalar()
    assert n == 1


def test_tarea_diaria_idempotente(cola_limpia, monkeypatch):
    from app.servicios import planificador

    class Aj:
        plan_ejecucion_cron = "*/1 * * * *"

    monkeypatch.setattr(planificador, "obtener_ajustes", lambda: Aj())
    ahora = datetime(2026, 2, 1, 6, 0, 20, tzinfo=planificador.ZONA) + timedelta(minutes=uuid.uuid4().int % 50000)
    primero = planificador.tarea_ejecucion_diaria(ahora)
    segundo = planificador.tarea_ejecucion_diaria(ahora + timedelta(seconds=15))  # otra réplica, algo después
    assert primero is not None and segundo is None


def test_endpoint_scheduler(cliente):
    r = cliente.get("/api/v1/scheduler")
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert {t["id"] for t in cuerpo["trabajos"]} == {"ejecucion_diaria", "reentrenamiento"}
    assert "por_estado" in cuerpo["cola"] and cuerpo["zona"] == "America/Bogota"
