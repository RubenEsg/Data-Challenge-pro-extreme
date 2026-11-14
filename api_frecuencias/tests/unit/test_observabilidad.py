"""RNF-006: líneas de log JSON con correlation_id, execution_id, worker_id y trace_id; spans de cada etapa de una
ejecución (InMemorySpanExporter) sin depender del cuerpo del ciclo."""
import io
import json
import logging
from types import SimpleNamespace

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app import observabilidad as O


@pytest.fixture(scope="module")
def memoria():
    proveedor = O.configurar_trazas("ninguno")
    exportador = InMemorySpanExporter()
    proveedor.add_span_processor(SimpleSpanProcessor(exportador))
    yield exportador
    exportador.shutdown()


@pytest.fixture
def salida_logs():
    manejador = O.configurar_logs("INFO")
    flujo = io.StringIO()
    manejador.setStream(flujo)
    yield flujo
    logging.getLogger().removeHandler(manejador)


def _lineas(flujo):
    return [json.loads(x) for x in flujo.getvalue().splitlines() if x.strip()]


def test_linea_de_log_json_con_todos_los_ids(memoria, salida_logs):
    token = O.correlation_id_var.set("cid-prueba-1")
    try:
        with O.ejecucion_en_curso("1b0c-ejecucion", "frecuencia"):
            O.marcar_etapa("1b0c-ejecucion", "calidad", 25)
            logging.getLogger("api_frecuencias.ejecucion").info("filas validadas %s", 10, extra={"ruta": "R1"})
            esperado = trace.get_current_span().get_span_context()
    finally:
        O.correlation_id_var.reset(token)
    linea = _lineas(salida_logs)[-1]
    assert linea["mensaje"] == "filas validadas 10" and linea["nivel"] == "INFO"
    assert linea["logger"] == "api_frecuencias.ejecucion" and linea["ruta"] == "R1"
    assert linea["correlation_id"] == "cid-prueba-1" and linea["execution_id"] == "1b0c-ejecucion"
    assert linea["worker_id"] and ":" in linea["worker_id"]
    assert linea["trace_id"] == format(esperado.trace_id, "032x") and len(linea["trace_id"]) == 32
    assert linea["span_id"] == format(esperado.span_id, "016x")
    assert "ts" in linea


def test_log_fuera_de_contexto_lleva_las_claves_en_null(salida_logs):
    logging.getLogger("api_frecuencias").warning("sin contexto")
    linea = _lineas(salida_logs)[-1]
    assert {"correlation_id", "execution_id", "worker_id", "trace_id", "span_id"} <= set(linea)
    assert linea["execution_id"] is None and linea["trace_id"] is None


def test_excepcion_queda_en_el_json(salida_logs):
    try:
        raise ValueError("dato malo")
    except ValueError:
        logging.getLogger("api_frecuencias").exception("fallo controlado")
    linea = _lineas(salida_logs)[-1]
    assert linea["nivel"] == "ERROR" and "ValueError: dato malo" in linea["excepcion"]


def test_worker_id_de_la_cola_tiene_prioridad():
    token = O.worker_id_var.set("replica-a:123:abc")
    try:
        assert O.worker_id() == "replica-a:123:abc"
    finally:
        O.worker_id_var.reset(token)


def test_instrumentar_ejecucion_produce_un_span_por_etapa(memoria):
    memoria.clear()
    llamadas = []
    modulo = SimpleNamespace()

    def _avance(execution_id, progreso, etapa, **campos):
        llamadas.append((etapa, progreso))

    def _ciclo_frecuencia(execution_id):
        modulo._avance(execution_id, 10, "lectura_incremental", filas_leidas=120)
        modulo._avance(execution_id, 25, "calidad", filas_leidas=120)
        modulo._incorporar_historico(None, None, execution_id)
        modulo._avance(execution_id, 45, "prediccion")
        with O.span("sql.simulado"):
            pass
        modulo._avance(execution_id, 70, "alertas")
        modulo._avance(execution_id, 85, "notificaciones")

    def _ciclo_entrenamiento(execution_id):
        modulo._avance(execution_id, 20, "entrenamiento")
        raise RuntimeError("entrenamiento falló")

    modulo._avance, modulo._ciclo_frecuencia, modulo._ciclo_entrenamiento = _avance, _ciclo_frecuencia, \
        _ciclo_entrenamiento
    modulo._incorporar_historico = lambda s, v, e: 7
    hechas = O.instrumentar_ejecucion(modulo, optimizacion=SimpleNamespace())
    assert {"ejecucion._ciclo_frecuencia", "ejecucion._avance", "ejecucion._incorporar_historico"} <= set(hechas)
    assert O.instrumentar_ejecucion(modulo, optimizacion=SimpleNamespace()) == []       # idempotente

    modulo._ciclo_frecuencia("e-123")
    with pytest.raises(RuntimeError):
        modulo._ciclo_entrenamiento("e-456")
    spans = {s.name: s for s in memoria.get_finished_spans()}
    raiz = spans["ejecucion.ciclo_frecuencia"]
    etapas = ["ejecucion.lectura_incremental", "ejecucion.calidad", "ejecucion.prediccion", "ejecucion.alertas",
              "ejecucion.notificaciones"]
    for nombre in etapas:
        s = spans[nombre]
        assert s.parent.span_id == raiz.context.span_id and s.context.trace_id == raiz.context.trace_id
        assert s.attributes["execution_id"] == "e-123"
    assert spans["ejecucion.lectura_incremental"].attributes["filas_leidas"] == 120
    assert spans["ejecucion.incorporar_historico"].parent.span_id == spans["ejecucion.calidad"].context.span_id
    assert spans["sql.simulado"].parent.span_id == spans["ejecucion.prediccion"].context.span_id
    assert raiz.attributes["execution_id"] == "e-123" and raiz.attributes["worker_id"]
    fin = {n: spans[n].end_time for n in etapas}
    assert all(fin[a] <= spans[b].start_time for a, b in zip(etapas, etapas[1:], strict=False))   # en orden
    assert spans["ejecucion.ciclo_entrenamiento"].status.status_code.name == "ERROR"
    assert spans["ejecucion.entrenamiento"].status.status_code.name == "ERROR"
    assert [e for e, _ in llamadas][-1] == "entrenamiento"
    assert O.execution_id_var.get() is None            # el contexto se limpia al terminar


def test_el_hilo_de_la_cola_continua_la_traza_de_quien_encolo(memoria):
    import threading

    memoria.clear()
    with O.trazador().start_as_current_span("POST /api/v1/frequency/executions") as http:
        O.recordar_encolada("e-cola-1", "cid-cola-1")
    vistos = {}

    def trabajador():                                  # hilo nuevo: sin contexto heredado de la petición
        with O.ejecucion_en_curso("e-cola-1", "frecuencia"):
            vistos["cid"] = O.correlation_id_var.get()

    hilo = threading.Thread(target=trabajador)
    hilo.start()
    hilo.join()
    ciclo = next(s for s in memoria.get_finished_spans() if s.name == "ejecucion.ciclo_frecuencia")
    assert ciclo.context.trace_id == http.get_span_context().trace_id
    assert ciclo.parent.span_id == http.get_span_context().span_id
    assert ciclo.attributes["correlation_id"] == "cid-cola-1" and vistos["cid"] == "cid-cola-1"


def test_el_ciclo_que_encola_el_refresco_de_segmentos_no_cambia_el_id_de_su_etapa(memoria, monkeypatch):
    """Un ciclo de frecuencia con datos nuevos encola el refresco de segmentos (crear_ejecucion instrumentado anota el
    execution_id NUEVO en el span actual). Eso pasa en un span propio, hijo de la última etapa: la etapa del ciclo
    conserva su execution_id y la traza sigue de punta a punta."""
    from contextlib import nullcontext

    from app.servicios import segmentos_refresco as R

    memoria.clear()

    def solicitar(_s, parametros, *_a, **_k):
        O.anotar(execution_id="seg-1")                   # lo que hace crear_ejecucion instrumentado
        return SimpleNamespace(execution_id="seg-1"), True

    monkeypatch.setattr(R.segmentos, "fuente_configurada", lambda: True)
    monkeypatch.setattr(R, "solicitar", solicitar)
    monkeypatch.setattr(R, "sesion_contexto", nullcontext)
    with O.ejecucion_en_curso("ciclo-1", "frecuencia"):
        O.marcar_etapa("ciclo-1", "notificaciones", 85)
        assert R.encolar_tras_ciclo("ciclo-1") == "seg-1"
    spans = {s.name: s for s in memoria.get_finished_spans()}
    etapa = spans["ejecucion.notificaciones"]
    assert etapa.attributes["execution_id"] == "ciclo-1"           # antes quedaba «seg-1»
    encolado = spans["ejecucion.encolar_refresco_segmentos"]
    assert encolado.attributes["execution_id"] == "seg-1" and encolado.attributes["ciclo"] == "ciclo-1"
    assert encolado.parent.span_id == etapa.context.span_id


def test_exportador_desconocido_se_rechaza():
    with pytest.raises(ValueError):
        O.configurar_trazas("zipkin")


def test_exportadores_configurables(monkeypatch):
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.trace.export import ConsoleSpanExporter

    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://jaeger:4318")
    otlp = O._exportador("otlp")
    assert isinstance(otlp, OTLPSpanExporter) and otlp._endpoint == "http://jaeger:4318/v1/traces"
    assert isinstance(O._exportador("consola"), ConsoleSpanExporter)
    assert O._exportador("ninguno") is None
