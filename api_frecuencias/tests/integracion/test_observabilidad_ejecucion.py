"""RNF-006 de punta a punta: POST /frequency/executions deja una traza con el span HTTP, el ciclo, cada etapa y las
sentencias SQL, y líneas de log JSON con correlation_id, execution_id, worker_id y trace_id. La evidencia
(seguridad/traza_ejecucion.json y seguridad/logs_json_ejecucion.txt) va a docs/evidencias solo con
GENERAR_EVIDENCIAS=1 (tests/evidencia.py); si no, a un directorio temporal."""
from __future__ import annotations

import io
import json
import logging
from datetime import date

import pytest
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from tests.evidencia import guardar_evidencia

ETAPAS = ("lectura_incremental", "calidad", "prediccion", "alertas", "notificaciones")


@pytest.fixture
def memoria(cliente):
    from app import observabilidad

    exportador = InMemorySpanExporter()
    observabilidad.configurar_trazas().add_span_processor(SimpleSpanProcessor(exportador))
    yield exportador
    exportador.shutdown()


@pytest.fixture
def logs_json(cliente):
    from app import observabilidad

    raiz = logging.getLogger()
    manejador = next((h for h in raiz.handlers if getattr(h, "_api_frecuencias", False)), None) \
        or observabilidad.configurar_logs("INFO")
    flujo = io.StringIO()
    anterior = manejador.setStream(flujo)
    yield flujo
    manejador.setStream(anterior)


@pytest.fixture
def fuente_tramo(monkeypatch):
    from app.servicios import datos, ejecucion, fuentes

    tramo = datos.demanda_horaria(desde=date(2025, 2, 24), hasta=date(2025, 3, 4))
    monkeypatch.setattr(ejecucion, "obtener_fuente", lambda: fuentes.FuenteParquet(cargador=lambda: tramo.copy()))
    return tramo


def test_traza_de_una_ejecucion_con_sus_etapas_y_logs_con_ids(cliente, memoria, logs_json, fuente_tramo):
    from app.servicios import datos

    ruta = datos.catalogo_rutas()[0]["ruta"]
    r = cliente.post("/api/v1/frequency/executions", headers={"X-Correlation-Id": "evid-traza-1"},
                     json={"instante": "2025-03-03T07:00:00-05:00", "rutas": [ruta], "horizontes": [60]})
    assert r.status_code == 202, r.text
    eid = r.json()["execution_id"]
    detalle = cliente.get(f"/api/v1/frequency/executions/{eid}").json()
    assert detalle["estado"] in ("ok", "en_cola", "corriendo"), detalle
    spans = memoria.get_finished_spans()
    ciclo = [s for s in spans if s.name == "ejecucion.ciclo_frecuencia" and s.attributes.get("execution_id") == eid]
    if not ciclo:
        pytest.skip("la ejecución quedó en la cola de otra réplica: no corrió en este proceso")
    ciclo = ciclo[0]
    traza = ciclo.context.trace_id
    de_la_traza = [s for s in spans if s.context.trace_id == traza]
    nombres = {s.name for s in de_la_traza}
    for etapa in ETAPAS:
        assert f"ejecucion.{etapa}" in nombres, (etapa, sorted(nombres))
    etapas = {s.name: s for s in de_la_traza if s.name.startswith("ejecucion.") and s.parent
              and s.parent.span_id == ciclo.context.span_id}
    assert all(s.attributes["execution_id"] == eid for s in etapas.values())
    sql = [s for s in de_la_traza if s.attributes.get("db.system") == "postgresql"
           or s.attributes.get("db.system.name") == "postgresql"]
    assert sql, "SQLAlchemy no dejó spans"
    http = [s for s in de_la_traza if s.attributes.get("correlation_id") == "evid-traza-1"]
    assert http, "el span HTTP debe llevar el correlation_id"

    lineas = [json.loads(x) for x in logs_json.getvalue().splitlines() if x.strip().startswith("{")]
    con_todo = [x for x in lineas if x.get("execution_id") == eid and x.get("correlation_id") == "evid-traza-1"
                and x.get("trace_id") == format(traza, "032x") and x.get("worker_id")]
    peticion = [x for x in lineas if x.get("mensaje") == "peticion" and x.get("correlation_id") == "evid-traza-1"]
    assert peticion and peticion[0]["trace_id"] == format(traza, "032x")

    inicio = min(s.start_time for s in de_la_traza)

    def fila(s):
        return {"nombre": s.name, "span_id": format(s.context.span_id, "016x"),
                "padre": format(s.parent.span_id, "016x") if s.parent else None,
                "inicio_ms": round((s.start_time - inicio) / 1e6, 2),
                "duracion_ms": round((s.end_time - s.start_time) / 1e6, 2),
                "estado": s.status.status_code.name,
                "atributos": {k: v for k, v in s.attributes.items()
                              if k in ("execution_id", "correlation_id", "worker_id", "etapa", "progreso",
                                       "filas_leidas", "http.route", "http.request.method",
                                       "http.response.status_code", "db.system", "db.system.name",
                                       "db.statement", "db.query.text", "tipo")}}

    guardar_evidencia("seguridad/traza_ejecucion.json", json.dumps({
        "servicio": "api-frecuencias", "trace_id": format(traza, "032x"), "execution_id": eid,
        "correlation_id": "evid-traza-1", "spans": len(de_la_traza), "spans_sql": len(sql),
        "etapas": [n for n in (f"ejecucion.{e}" for e in ETAPAS)],
        "detalle": sorted((fila(s) for s in de_la_traza), key=lambda x: x["inicio_ms"])},
        ensure_ascii=False, indent=1, default=str))
    guardar_evidencia("seguridad/logs_json_ejecucion.txt",
                      "\n".join(json.dumps(x, ensure_ascii=False) for x in (peticion + con_todo)[:40]) + "\n")
    assert {x["mensaje"] for x in con_todo} >= {f"etapa {e}" for e in ETAPAS}, [x["mensaje"] for x in con_todo]
