"""Observabilidad (RNF-006, §7.2): logs JSON con structlog y trazas OpenTelemetry de las operaciones críticas.

Logs: cada línea es un objeto JSON con ts, nivel, logger, mensaje y los identificadores correlation_id,
execution_id, worker_id, trace_id y span_id (null cuando no aplican). Los módulos siguen usando logging estándar;
structlog da formato a todo, también a uvicorn. Un solo manejador, en la raíz: nada se duplica.

Trazas: TracerProvider con service.name = OTEL_SERVICE_NAME y exportador OTEL_EXPORTADOR = ninguno | consola | otlp
(OTLP/HTTP a OTEL_EXPORTER_OTLP_ENDPOINT, por ejemplo http://jaeger:4318). Se instrumentan el HTTP (FastAPI),
SQLAlchemy (cada sentencia) y cada etapa de una ejecución. Las etapas salen de _avance(execution_id, progreso, etapa)
de app.servicios.ejecucion: cada cambio de etapa cierra el span anterior y abre «ejecucion.<etapa>», hijo de
«ejecucion.ciclo_frecuencia» o «ejecucion.ciclo_entrenamiento». Así las trazas no dependen del cuerpo del
ciclo, que puede cambiar, sino del registro de avance, que es el contrato del job.
"""
from __future__ import annotations

import contextvars
import functools
import logging
import os
import socket
import sys
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Any

import structlog
from opentelemetry import context as otel_context
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

correlation_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("correlation_id", default=None)
execution_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("execution_id", default=None)
worker_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("worker_id", default=None)

NOMBRE_TRAZADOR = "api_frecuencias"
EXPORTADORES = ("ninguno", "consola", "otlp")
_log_etapas = logging.getLogger("api_frecuencias.ejecucion.etapas")
_candado = threading.Lock()
_proveedor = None


# ---------------------------------------------------------------- identificadores
def worker_id() -> str:
    """worker_id del hilo actual: el de la cola si hay un trabajo reservado, si no réplica:pid."""
    propio = worker_id_var.get()
    if propio:
        return propio
    cola = sys.modules.get("app.servicios.cola")
    actual = getattr(cola, "trabajador_actual", None)
    if actual is not None:
        try:
            valor = actual.get()
            if valor:
                return str(valor)
        except LookupError:
            pass
    replica = os.environ.get("TRABAJADOR_ID") or os.environ.get("HOSTNAME") or socket.gethostname() or "replica"
    return f"{replica}:{os.getpid()}"


def ids_de_traza() -> tuple[str | None, str | None]:
    ctx = trace.get_current_span().get_span_context()
    if not ctx.is_valid:
        return None, None
    return format(ctx.trace_id, "032x"), format(ctx.span_id, "016x")


def _agregar_ids(_logger, _metodo, evento: dict) -> dict:
    evento.setdefault("correlation_id", correlation_id_var.get())
    evento.setdefault("execution_id", execution_id_var.get())
    evento.setdefault("worker_id", worker_id())
    trace_id, span_id = ids_de_traza()
    evento.setdefault("trace_id", trace_id)
    evento.setdefault("span_id", span_id)
    return evento


def _marca_tiempo(_logger, _metodo, evento: dict) -> dict:
    """ISO-8601 con zona (§12.1), en la hora local del proceso (TZ=America/Bogota en el contenedor)."""
    evento.setdefault("ts", datetime.now().astimezone().isoformat(timespec="milliseconds"))
    return evento


def _nombres_en_espanol(_logger, _metodo, evento: dict) -> dict:
    """Mantiene las claves del formato anterior (ts, nivel, logger, mensaje) para no romper consultas de logs."""
    evento.pop("message", None)            # copia de LogRecord.message que agrega ExtraAdder
    evento.pop("color_message", None)      # variante con colores ANSI que agrega uvicorn
    if "event" in evento:
        evento["mensaje"] = evento.pop("event")
    if "level" in evento:
        evento["nivel"] = str(evento.pop("level")).upper()
    if "exception" in evento:
        evento["excepcion"] = evento.pop("exception")
    return evento


# ---------------------------------------------------------------- logs
def configurar_logs(nivel: str = "INFO") -> logging.Handler:
    previos = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.ExtraAdder(),
        _agregar_ids,
        _marca_tiempo,
    ]
    formato = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=previos,
        processors=[structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                    structlog.processors.format_exc_info, _nombres_en_espanol,
                    structlog.processors.JSONRenderer(ensure_ascii=False, default=str)],
    )
    structlog.configure(
        processors=[*previos[:3], _agregar_ids, previos[-1], structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(), wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True)
    raiz = logging.getLogger()
    for previo in [h for h in raiz.handlers if getattr(h, "_api_frecuencias", False)]:
        raiz.removeHandler(previo)
    manejador = logging.StreamHandler()
    manejador.setFormatter(formato)
    manejador._api_frecuencias = True  # type: ignore[attr-defined]
    raiz.addHandler(manejador)
    if raiz.level == logging.NOTSET or raiz.level > logging.WARNING:
        raiz.setLevel(logging.WARNING)
    for nombre in ("api_frecuencias", "ai_frecuencias"):
        lg = logging.getLogger(nombre)
        lg.handlers[:] = []
        lg.setLevel(nivel)
        lg.propagate = True
    for nombre in ("uvicorn", "uvicorn.error", "alembic"):
        lg = logging.getLogger(nombre)
        lg.handlers[:] = []
        lg.setLevel(logging.INFO)
        lg.propagate = True
    acceso = logging.getLogger("uvicorn.access")       # el middleware ya registra cada petición con sus ids
    acceso.handlers[:] = []
    acceso.setLevel(logging.WARNING)
    acceso.propagate = True
    return manejador


# ---------------------------------------------------------------- trazas
def _exportador(nombre: str):
    if nombre == "consola":
        from opentelemetry.sdk.trace.export import ConsoleSpanExporter

        return ConsoleSpanExporter()
    if nombre == "otlp":
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        return OTLPSpanExporter()          # OTEL_EXPORTER_OTLP_ENDPOINT / _TRACES_ENDPOINT (estándar OTel)
    return None


def configurar_trazas(exportador: str = "ninguno", servicio: str = "api-frecuencias", version: str = "",
                      entorno: str = "local"):
    """Proveedor global (una vez por proceso). Siempre es el del SDK, para que los ids lleguen a los logs aunque
    no se exporte nada; los procesadores se agregan según el exportador."""
    global _proveedor
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor

    exportador = (exportador or "ninguno").strip().lower()
    if exportador not in EXPORTADORES:
        raise ValueError(f"OTEL_EXPORTADOR desconocido: {exportador!r} (use {', '.join(EXPORTADORES)})")
    with _candado:
        if _proveedor is None:
            actual = trace.get_tracer_provider()
            if isinstance(actual, TracerProvider):
                _proveedor = actual
            else:
                _proveedor = TracerProvider(resource=Resource.create({
                    "service.name": servicio, "service.version": version, "deployment.environment": entorno}))
                trace.set_tracer_provider(_proveedor)
            exp = _exportador(exportador)
            if exp is not None:
                procesador = SimpleSpanProcessor(exp) if exportador == "consola" else BatchSpanProcessor(exp)
                _proveedor.add_span_processor(procesador)
    return _proveedor


def instrumentar_http(app) -> None:
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

    if not getattr(app, "_is_instrumented_by_opentelemetry", False):
        FastAPIInstrumentor.instrument_app(app, excluded_urls="health,metrics", exclude_spans=["receive", "send"])


def instrumentar_sqlalchemy(motor) -> None:
    from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

    instrumentador = SQLAlchemyInstrumentor()
    if not instrumentador.is_instrumented_by_opentelemetry:
        instrumentador.instrument(engine=motor, enable_commenter=False)


def trazador():
    return trace.get_tracer(NOMBRE_TRAZADOR)


def anotar(**atributos: Any) -> None:
    """Agrega atributos al span actual (si hay uno que se esté grabando)."""
    actual = trace.get_current_span()
    if actual.is_recording():
        for k, v in atributos.items():
            if v is not None:
                actual.set_attribute(k, v if isinstance(v, (str, bool, int, float)) else str(v))


@contextmanager
def span(nombre: str, **atributos: Any) -> Iterator[Any]:
    """Span hijo del contexto actual con atributos simples (None se omite)."""
    with trazador().start_as_current_span(nombre) as s:
        for k, v in atributos.items():
            if v is not None:
                s.set_attribute(k, v if isinstance(v, (str, bool, int, float)) else str(v))
        yield s


# ---------------------------------------------------------------- etapas de una ejecución
class _Etapas(threading.local):
    def __init__(self):
        self.pila: list[dict[str, Any]] = []


_etapas = _Etapas()


def _cerrar_etapa(marco: dict[str, Any], error: BaseException | None = None) -> None:
    abierto = marco.pop("etapa", None)
    if abierto is None:
        return
    s, token = abierto
    if error is not None:
        s.record_exception(error)
        s.set_status(Status(StatusCode.ERROR, f"{type(error).__name__}: {error}"[:200]))
    otel_context.detach(token)
    s.end()


def marcar_etapa(execution_id: Any, etapa: str, progreso: float | None = None, **atributos: Any) -> None:
    """Cierra el span de la etapa anterior y abre «ejecucion.<etapa>» como hijo del span de la ejecución."""
    if not _etapas.pila or str(execution_id) != _etapas.pila[-1]["execution_id"]:
        return
    marco = _etapas.pila[-1]
    _cerrar_etapa(marco)
    s = trazador().start_span(f"ejecucion.{etapa}", context=marco["contexto"])
    s.set_attribute("execution_id", marco["execution_id"])
    s.set_attribute("etapa", etapa)
    if progreso is not None:
        s.set_attribute("progreso", float(progreso))
    for k, v in atributos.items():
        if isinstance(v, (str, bool, int, float)):
            s.set_attribute(k, v)
    marco["etapa"] = (s, otel_context.attach(trace.set_span_in_context(s)))
    _log_etapas.info("etapa %s", etapa, extra={"etapa": etapa, "progreso": progreso, **atributos})


# execution_id -> (contexto del span que la encoló, correlation_id): el hilo de la cola no hereda el contexto de la
# petición, así que al encolar se guarda aquí y el ciclo lo retoma como padre (misma traza de punta a punta).
_encoladas: dict[str, tuple[Any, str | None]] = {}
_MAX_ENCOLADAS = 2000


def recordar_encolada(execution_id: Any, correlation_id: str | None = None) -> None:
    ctx = trace.get_current_span().get_span_context()
    with _candado:
        if len(_encoladas) >= _MAX_ENCOLADAS:
            _encoladas.pop(next(iter(_encoladas)))
        _encoladas[str(execution_id)] = (ctx if ctx.is_valid else None, correlation_id or correlation_id_var.get())


def _de_la_base(eid: str) -> tuple[str | None, str | None]:
    """Otra réplica tomó la ejecución: correlation_id y traceparent W3C de quien la encoló están en execution_log
    (una lectura por ejecución). Sin la columna traceparent (base anterior a la migración 0004) lee solo el id."""
    try:
        import uuid

        from sqlalchemy import text

        from app.db import sesion_contexto

        uuid.UUID(eid)
        for sql in ("SELECT correlation_id, traceparent FROM ai_frecuencias.execution_log "
                    "WHERE execution_id = CAST(:e AS uuid)",
                    "SELECT correlation_id, NULL FROM ai_frecuencias.execution_log "
                    "WHERE execution_id = CAST(:e AS uuid)"):
            try:
                with sesion_contexto() as s:
                    fila = s.execute(text(sql), {"e": eid}).first()
                return (fila[0], fila[1]) if fila else (None, None)
            except Exception:  # noqa: BLE001 - base anterior a la migración 0004: se prueba la consulta sin traceparent
                logging.getLogger("api_frecuencias").debug("Lectura de traza no disponible con esta consulta",
                                                           exc_info=True)
                continue
    except Exception:  # noqa: BLE001 - la observabilidad nunca hace fallar una ejecución
        logging.getLogger("api_frecuencias").debug("Sin correlation_id/traceparent en la base", exc_info=True)
    return None, None


def _correlation_id_de_la_base(eid: str) -> str | None:
    return _de_la_base(eid)[0]


def contexto_w3c(traceparent: str | None):
    """Contexto OpenTelemetry a partir de un traceparent W3C guardado (None si falta o no es válido)."""
    if not traceparent:
        return None
    from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

    contexto = TraceContextTextMapPropagator().extract({"traceparent": traceparent})
    return contexto if trace.get_current_span(contexto).get_span_context().is_valid else None


@contextmanager
def ejecucion_en_curso(execution_id: Any, tipo: str) -> Iterator[Any]:
    """Span «ejecucion.ciclo_<tipo>» con execution_id, worker_id y correlation_id; los logs llevan el execution_id.

    RNF-006: el span continúa la traza de la petición que encoló la ejecución. En la misma réplica el contexto se
    retoma de memoria; si la toma otra réplica (u otro proceso tras un reinicio), del traceparent W3C guardado en
    execution_log al crearla. El atributo «traza_origen» dice cuál de los dos se usó (memoria, execution_log o
    nueva)."""
    eid = str(execution_id)
    with _candado:
        padre, cid_encolada = _encoladas.pop(eid, (None, None))
    cid = correlation_id_var.get() or cid_encolada
    sin_traza_activa = not trace.get_current_span().get_span_context().is_valid
    contexto, origen = None, "nueva" if sin_traza_activa else "heredada"
    if padre is not None and sin_traza_activa:
        contexto, origen = trace.set_span_in_context(trace.NonRecordingSpan(padre)), "memoria"
    elif sin_traza_activa or not cid:
        cid_base, traceparent = _de_la_base(eid)
        cid = cid or cid_base
        remoto = contexto_w3c(traceparent) if sin_traza_activa else None
        if remoto is not None:
            contexto, origen = remoto, "execution_log"
    token_eid, token_cid = execution_id_var.set(eid), correlation_id_var.set(cid)
    with trazador().start_as_current_span(f"ejecucion.ciclo_{tipo}", context=contexto) as s:
        s.set_attribute("execution_id", eid)
        s.set_attribute("tipo", tipo)
        s.set_attribute("worker_id", worker_id())
        s.set_attribute("traza_origen", origen)
        if cid:
            s.set_attribute("correlation_id", cid)
        marco = {"execution_id": eid, "contexto": otel_context.get_current()}
        _etapas.pila.append(marco)
        error: BaseException | None = None
        try:
            yield s
        except BaseException as exc:
            error = exc
            raise
        finally:
            _cerrar_etapa(marco, error)
            _etapas.pila.remove(marco)
            correlation_id_var.reset(token_cid)
            execution_id_var.reset(token_eid)


def _envolver(modulo, nombre: str, fabrica: Callable[[Callable], Callable]) -> bool:
    original = getattr(modulo, nombre, None)
    if original is None or getattr(original, "_otel_envuelto", False):
        return False
    envuelta = functools.wraps(original)(fabrica(original))
    envuelta._otel_envuelto = True  # type: ignore[attr-defined]
    envuelta._otel_original = original  # type: ignore[attr-defined]
    setattr(modulo, nombre, envuelta)
    return True


def instrumentar_ejecucion(ejecucion=None, optimizacion=None) -> list[str]:
    """Envuelve, sin tocar su código, las funciones de ejecucion.py que delimitan el job y sus etapas."""
    if ejecucion is None:
        from app.servicios import ejecucion
    if optimizacion is None:
        try:
            from app.servicios import optimizacion
        except ImportError:  # pragma: no cover
            optimizacion = None

    hechas: list[str] = []

    def ciclo(tipo: str):
        def fabrica(original):
            def envuelta(execution_id, *args, **kwargs):
                with ejecucion_en_curso(execution_id, tipo):
                    return original(execution_id, *args, **kwargs)
            return envuelta
        return fabrica

    def avance(original):
        def envuelta(execution_id, progreso, etapa, *args, **kwargs):
            resultado = original(execution_id, progreso, etapa, *args, **kwargs)
            filas = {k: v for k, v in kwargs.items() if k in ("filas_leidas", "filas_validas")}
            marcar_etapa(execution_id, etapa, progreso, **filas)
            return resultado
        return envuelta

    def subspan(nombre_span: str):
        def fabrica(original):
            def envuelta(*args, **kwargs):
                with span(nombre_span, execution_id=execution_id_var.get()):
                    return original(*args, **kwargs)
            return envuelta
        return fabrica

    def creacion(original):
        def envuelta(*args, **kwargs):
            e = original(*args, **kwargs)
            if getattr(e, "execution_id", None) is not None:
                recordar_encolada(e.execution_id, getattr(e, "correlation_id", None))
                anotar(execution_id=str(e.execution_id))
            return e
        return envuelta

    for nombre, fabrica in (("crear_ejecucion", creacion),
                            ("_ciclo_frecuencia", ciclo("frecuencia")),
                            ("_ciclo_entrenamiento", ciclo("entrenamiento")),
                            ("_avance", avance),
                            ("_incorporar_historico", subspan("ejecucion.incorporar_historico")),
                            ("_guardar_errores", subspan("ejecucion.guardar_errores_calidad")),
                            ("_notificar", subspan("ejecucion.notificar"))):
        if _envolver(ejecucion, nombre, fabrica):
            hechas.append(f"ejecucion.{nombre}")
    if optimizacion is not None and _envolver(optimizacion, "recomendar", subspan("optimizacion.recomendar")):
        hechas.append("optimizacion.recomendar")
    return hechas


def configurar(app=None, ajustes=None) -> None:
    """Punto único de arranque: logs JSON, proveedor de trazas e instrumentación de HTTP, SQLAlchemy y el job."""
    from app import __version__
    from app.config import obtener_ajustes

    ajustes = ajustes or obtener_ajustes()
    configurar_logs(ajustes.log_nivel)
    configurar_trazas(ajustes.otel_exportador, ajustes.otel_service_name, __version__, ajustes.entorno)
    if app is not None:
        instrumentar_http(app)
    try:
        from app.db import motor

        instrumentar_sqlalchemy(motor())
    except Exception:  # noqa: BLE001 - sin motor (URL inválida) la API arranca igual; queda en el log
        logging.getLogger("api_frecuencias").warning("No se pudo instrumentar SQLAlchemy", exc_info=True)
    instrumentar_ejecucion()


__all__ = ["configurar", "configurar_logs", "configurar_trazas", "correlation_id_var", "execution_id_var",
           "worker_id_var", "worker_id", "ids_de_traza", "span", "marcar_etapa", "ejecucion_en_curso",
           "instrumentar_ejecucion"]
