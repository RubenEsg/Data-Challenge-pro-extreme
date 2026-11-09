"""API de frecuencias Sobusa (backend del reto): FastAPI + PostgreSQL (esquema ai_frecuencias).

Arranque local:  uvicorn app.main:app --port 8000   (requiere DATABASE_URL y «alembic upgrade head»)
"""
from __future__ import annotations

import contextvars
import json
import logging
import threading
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import __version__
from app.config import obtener_ajustes
from app.db import base_disponible, sesion_contexto
from app.routers import alertas, ejecuciones, modelos, predicciones, umbrales
from app.routers.comun import ErrorApi

correlation_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("correlation_id", default=None)

PETICIONES = Counter("api_peticiones_total", "Peticiones HTTP", ["metodo", "ruta", "estado"])
LATENCIA = Histogram("api_latencia_segundos", "Latencia de las peticiones HTTP", ["metodo", "ruta"])


class FormatoJson(logging.Formatter):
    def format(self, registro: logging.LogRecord) -> str:
        datos = {"ts": self.formatTime(registro, "%Y-%m-%dT%H:%M:%S%z"), "nivel": registro.levelname,
                 "logger": registro.name, "mensaje": registro.getMessage(),
                 "correlation_id": correlation_id_var.get()}
        for campo in ("metodo", "ruta", "estado", "duracion_ms"):
            if hasattr(registro, campo):
                datos[campo] = getattr(registro, campo)
        if registro.exc_info:
            datos["excepcion"] = self.formatException(registro.exc_info)
        return json.dumps(datos, ensure_ascii=False)


def _configurar_logs() -> None:
    manejador = logging.StreamHandler()
    manejador.setFormatter(FormatoJson())
    raiz = logging.getLogger("api_frecuencias")
    raiz.handlers[:] = [manejador]
    raiz.setLevel(obtener_ajustes().log_nivel)
    raiz.propagate = False


_configurar_logs()
log = logging.getLogger("api_frecuencias.http")


@asynccontextmanager
async def ciclo_de_vida(_app: FastAPI):
    ajustes = obtener_ajustes()
    if base_disponible():
        from app.servicios import ejecucion

        try:
            pendientes = ejecucion.recuperar_interrumpidas()
            with sesion_contexto() as s:
                ejecucion.sembrar_registro(s)
            if pendientes and ajustes.reanudar_ejecuciones:
                def _reanudar():
                    for ident in pendientes:
                        ejecucion.ejecutar(ident)
                threading.Thread(target=_reanudar, name="reanudar-ejecuciones", daemon=True).start()
            logging.getLogger("api_frecuencias").info("Arranque: %s ejecuciones reencoladas", len(pendientes))
        except Exception:  # noqa: BLE001 - la API arranca aunque la recuperación falle (queda en el log)
            logging.getLogger("api_frecuencias").exception("No se pudo recuperar el estado al arrancar")
    yield


ajustes = obtener_ajustes()
app = FastAPI(
    title="API de frecuencias Sobusa",
    version=__version__,
    description=("Backend del reto de frecuencias (Extreme Technologies v1.5): lectura incremental, calidad, "
                 "pronóstico de demanda 30/60/120 min, recomendación de frecuencia y flota, alertas ALT-001..010, "
                 "registro y activación controlada de modelos. Resultados en el esquema ai_frecuencias."),
    lifespan=ciclo_de_vida,
    docs_url="/docs" if ajustes.docs_habilitados else None,
    redoc_url=None,
    openapi_url="/openapi.json" if ajustes.docs_habilitados else None,
)


@app.middleware("http")
async def correlation_id(request: Request, call_next):
    cid = request.headers.get("X-Correlation-Id") or str(uuid.uuid4())
    token = correlation_id_var.set(cid)
    request.state.correlation_id = cid
    inicio = time.perf_counter()
    estado = 500
    try:
        respuesta = await call_next(request)
        estado = respuesta.status_code
        respuesta.headers["X-Correlation-Id"] = cid
        return respuesta
    finally:
        ruta = request.scope.get("route").path if request.scope.get("route") else request.url.path
        duracion = time.perf_counter() - inicio
        PETICIONES.labels(request.method, ruta, str(estado)).inc()
        LATENCIA.labels(request.method, ruta).observe(duracion)
        log.info("peticion", extra={"metodo": request.method, "ruta": request.url.path, "estado": estado,
                                    "duracion_ms": round(duracion * 1000, 2)})
        correlation_id_var.reset(token)


def _error(status: int, codigo: str, mensaje: str, detalle=None, request: Request | None = None) -> JSONResponse:
    cid = getattr(request.state, "correlation_id", None) if request else correlation_id_var.get()
    return JSONResponse(status_code=status, content={"error": {"codigo": codigo, "mensaje": mensaje,
                                                               "detalle": detalle, "correlation_id": cid}},
                        headers={"X-Correlation-Id": cid} if cid else None)


@app.exception_handler(ErrorApi)
async def _manejar_error_api(request: Request, exc: ErrorApi):
    return _error(exc.status, exc.codigo, exc.mensaje, exc.detalle, request)


@app.exception_handler(RequestValidationError)
async def _manejar_validacion(request: Request, exc: RequestValidationError):
    detalle = [{"campo": ".".join(str(x) for x in e.get("loc", [])), "mensaje": e.get("msg"), "tipo": e.get("type")}
               for e in exc.errors()]
    return _error(422, "validacion", "La solicitud no es válida", detalle, request)


@app.exception_handler(StarletteHTTPException)
async def _manejar_http(request: Request, exc: StarletteHTTPException):
    codigos = {404: "no_encontrado", 405: "metodo_no_permitido"}
    return _error(exc.status_code, codigos.get(exc.status_code, "http"), str(exc.detail), None, request)


@app.exception_handler(Exception)
async def _manejar_inesperado(request: Request, exc: Exception):
    logging.getLogger("api_frecuencias").exception("Error no controlado")
    return _error(500, "error_interno", "Error interno; consulte el log con el correlation_id", None, request)


PREFIJO = "/api/v1"
for modulo in (ejecuciones, predicciones, alertas, modelos, umbrales):
    app.include_router(modulo.router, prefix=PREFIJO)


@app.get("/health", tags=["sistema"], summary="Estado del servicio y de la base")
def salud():
    ok = base_disponible()
    cuerpo = {"estado": "ok" if ok else "degradado", "base_datos": "ok" if ok else "sin_conexion",
              "version": __version__, "fuente": obtener_ajustes().fuente}
    return JSONResponse(cuerpo, status_code=200 if ok else 503)


@app.get("/metrics", tags=["sistema"], summary="Métricas Prometheus", include_in_schema=True)
def metricas():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
