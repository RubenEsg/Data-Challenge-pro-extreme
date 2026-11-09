"""RNF-006 entre réplicas: la réplica que toma una ejecución de la cola continúa la traza W3C de la petición que la
encoló, aunque no comparta memoria con ella.

La petición POST /api/v1/frequency/executions guarda el traceparent en execution_log. Para simular otra réplica se
borra el registro en memoria de la réplica que encoló y el trabajo se reclama y se corre desde otro hilo (contexto
vacío, otro worker_id) con cola.reclamar + cola.correr_reclamo, el mismo camino de los trabajadores. Con el
exportador en memoria de OpenTelemetry se comprueba que el span «ejecucion.ciclo_frecuencia» tiene el mismo trace_id
del span HTTP y que su padre es exactamente el span guardado en el traceparent.
"""
from __future__ import annotations

import re
import threading
import uuid
from datetime import date

import pytest
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

pytestmark = pytest.mark.integracion
TRACEPARENT = re.compile(r"00-([0-9a-f]{32})-([0-9a-f]{16})-[0-9a-f]{2}")


@pytest.fixture
def memoria(cliente):
    from app import observabilidad

    exportador = InMemorySpanExporter()
    observabilidad.configurar_trazas().add_span_processor(SimpleSpanProcessor(exportador))
    yield exportador
    exportador.shutdown()


def test_otra_replica_continua_la_traza_desde_execution_log(cliente, memoria, monkeypatch):
    from app import observabilidad
    from app.db import sesion_contexto
    from app.modelos_db import Ejecucion
    from app.servicios import cola, datos, ejecucion, fuentes

    tramo = datos.demanda_horaria(desde=date(2025, 2, 24), hasta=date(2025, 3, 4))
    monkeypatch.setattr(ejecucion, "obtener_fuente", lambda: fuentes.FuenteParquet(cargador=lambda: tramo.copy()))
    monkeypatch.setattr(ejecucion, "ejecutar", lambda *a, **k: None)      # queda en la cola: nadie la procesa aquí
    cid = f"rnf006-{uuid.uuid4()}"
    r = cliente.post("/api/v1/frequency/executions", headers={"X-Correlation-Id": cid},
                     json={"instante": "2025-03-03T07:00:00-05:00", "rutas": [datos.catalogo_rutas()[0]["ruta"]],
                           "horizontes": [60], "notificar": False})
    assert r.status_code == 202, r.text
    eid = r.json()["execution_id"]
    with sesion_contexto() as s:
        traceparent = s.get(Ejecucion, uuid.UUID(eid)).traceparent
    m = TRACEPARENT.fullmatch(traceparent or "")
    assert m, f"execution_log.traceparent no es W3C: {traceparent!r}"
    traza_peticion, span_peticion = int(m.group(1), 16), int(m.group(2), 16)
    http = [s for s in memoria.get_finished_spans() if s.attributes.get("correlation_id") == cid]
    assert http and {s.context.trace_id for s in http} == {traza_peticion}, "el traceparent no es el de la petición"

    with observabilidad._candado:                     # la otra réplica no tiene el registro en memoria
        observabilidad._encoladas.pop(eid, None)
    resultado: dict = {}

    def replica_b():                                  # hilo nuevo = contexto vacío, sin span activo
        reclamo = cola.reclamar("replica-b:1", execution_id=uuid.UUID(eid))
        resultado["reclamo"] = reclamo is not None
        resultado["estado"] = cola.correr_reclamo(reclamo) if reclamo else None

    hilo = threading.Thread(target=replica_b)
    hilo.start()
    hilo.join(timeout=300)
    assert resultado.get("reclamo"), "la réplica B no pudo reclamar la ejecución"
    assert resultado["estado"] == "ok", resultado
    ciclo = [s for s in memoria.get_finished_spans()
             if s.name == "ejecucion.ciclo_frecuencia" and s.attributes.get("execution_id") == eid]
    assert len(ciclo) == 1, [s.name for s in memoria.get_finished_spans()][-20:]
    ciclo = ciclo[0]
    assert ciclo.context.trace_id == traza_peticion, "el trabajador abrió una traza nueva (RNF-006)"
    assert ciclo.parent is not None and ciclo.parent.span_id == span_peticion and ciclo.parent.is_remote
    assert ciclo.attributes["traza_origen"] == "execution_log"
    assert ciclo.attributes["correlation_id"] == cid
    etapas = [s for s in memoria.get_finished_spans()
              if s.context.trace_id == traza_peticion and s.name.startswith("ejecucion.") and s is not ciclo]
    assert {"ejecucion.lectura_incremental", "ejecucion.prediccion"} <= {s.name for s in etapas}
    print("EVIDENCIA_RNF006", {"execution_id": eid, "correlation_id": cid,
                               "traceparent_guardado": traceparent,
                               "trace_id_peticion": f"{traza_peticion:032x}",
                               "trace_id_trabajador": f"{ciclo.context.trace_id:032x}",
                               "padre_del_ciclo": f"{ciclo.parent.span_id:016x}",
                               "padre_remoto": ciclo.parent.is_remote,
                               "traza_origen": ciclo.attributes["traza_origen"],
                               "worker_id": ciclo.attributes["worker_id"],
                               "etapas_en_la_misma_traza": sorted({s.name for s in etapas})})


def test_misma_replica_continua_la_traza_desde_memoria(cliente, memoria, monkeypatch):
    """En la réplica que encoló, el contexto se retoma de memoria (sin leer la base) y la traza es la misma."""
    from app import observabilidad

    llamadas = []
    monkeypatch.setattr(observabilidad, "_de_la_base", lambda eid: llamadas.append(eid) or (None, None))
    with observabilidad.trazador().start_as_current_span("peticion_simulada") as s:
        eid = str(uuid.uuid4())
        observabilidad.recordar_encolada(eid, "cid-memoria")
        traza = s.get_span_context().trace_id
    resultado = {}

    def trabajador():
        with observabilidad.ejecucion_en_curso(eid, "frecuencia") as span:
            resultado["traza"] = span.get_span_context().trace_id
            resultado["origen"] = span.attributes.get("traza_origen")

    hilo = threading.Thread(target=trabajador)
    hilo.start()
    hilo.join(timeout=30)
    assert resultado == {"traza": traza, "origen": "memoria"} and not llamadas


def test_traceparent_invalido_abre_traza_nueva_sin_fallar(monkeypatch):
    from app import observabilidad

    assert observabilidad.contexto_w3c(None) is None
    assert observabilidad.contexto_w3c("no-es-un-traceparent") is None
    assert observabilidad.contexto_w3c("00-" + "0" * 32 + "-" + "0" * 16 + "-01") is None
    valido = observabilidad.contexto_w3c("00-" + "a" * 32 + "-" + "b" * 16 + "-01")
    from opentelemetry import trace

    assert trace.get_current_span(valido).get_span_context().trace_id == int("a" * 32, 16)
