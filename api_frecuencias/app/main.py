"""API de frecuencias Sobusa (backend del reto): FastAPI + PostgreSQL (esquema ai_frecuencias).

Arranque local:  uvicorn app.main:app --port 8000   (requiere DATABASE_URL y «alembic upgrade head»)
"""
from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, REGISTRY, Counter, Histogram, generate_latest
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import __version__, observabilidad, seguridad
from app.config import obtener_ajustes
from app.db import base_disponible, sesion_contexto
from app.observabilidad import correlation_id_var
from app.routers import alertas, catalogos, ejecuciones, modelos, planificador, predicciones, umbrales
from app.routers.comun import ErrorApi
from app.servicios import circuito
from app.servicios import cola as _cola

PETICIONES = Counter("api_peticiones_total", "Peticiones HTTP", ["metodo", "ruta", "estado"])
LATENCIA = Histogram("api_latencia_segundos", "Latencia de las peticiones HTTP", ["metodo", "ruta"])
# RNF-006 / §7.2: además de HTTP, /metrics expone las ejecuciones por tipo y resultado, la duración de cada etapa y de
# cada intento (entrenamientos incluidos), los reintentos y la profundidad de la cola (app/servicios/cola.py y
# app/servicios/ejecucion.py). El colector de la cola se registra una sola vez por proceso.
if not any(isinstance(c, _cola.ColectorCola) for c in list(getattr(REGISTRY, "_collector_to_names", {}))):
    REGISTRY.register(_cola.ColectorCola())

observabilidad.configurar_logs(obtener_ajustes().log_nivel)   # structlog JSON con correlation/execution/trace id
log = logging.getLogger("api_frecuencias.http")


@asynccontextmanager
async def ciclo_de_vida(_app: FastAPI):
    from app.servicios import cola
    from app.servicios import planificador as plan_interno

    registro = logging.getLogger("api_frecuencias")
    sembrados: dict = {}
    try:   # RNF-008: al actualizar una instalación, los modelos nuevos de la imagen llegan al volumen de modelos
        from app.servicios import modelos_imagen

        sembrados = modelos_imagen.sembrar()
        if sembrados:
            registro.info("Modelos de la imagen copiados al volumen: %s", sembrados)
    except Exception:  # noqa: BLE001 - la API arranca aunque la copia falle (queda en el log)
        registro.exception("No se pudieron copiar los modelos de la imagen al volumen")
    if base_disponible():
        from app.servicios import ejecucion

        try:
            # RNF-001: lo que dejó el proceso anterior de esta réplica y lo de reservas vencidas vuelve a la cola
            pendientes = ejecucion.recuperar_interrumpidas()
            with sesion_contexto() as s:
                ejecucion.sembrar_registro(s)
                if sembrados.get("horarios"):
                    ejecucion.registrar_sembrados(s, sembrados["horarios"])
                from app.servicios import gobierno_corto_plazo

                gobierno_corto_plazo.sembrar(s)     # la familia corto_plazo en model_registry (RF-019)
            registro.info("Arranque: %s ejecuciones reencoladas", len(pendientes))
        except Exception:  # noqa: BLE001 - la API arranca aunque la recuperación falle (queda en el log)
            registro.exception("No se pudo recuperar el estado al arrancar")
    # cola en PostgreSQL (RNF-005: N réplicas sin duplicar) y planificador interno (§7.2), si están habilitados
    cola.iniciar()
    try:
        plan_interno.iniciar()
    except Exception:  # noqa: BLE001 - sin planificador la API sigue atendiendo (queda en el log)
        registro.exception("No se pudo iniciar el planificador")
    try:
        yield
    finally:
        plan_interno.detener()
        devueltas = cola.detener()
        if devueltas:
            registro.info("Apagado ordenado: %s ejecuciones devueltas a la cola", len(devueltas))


ajustes = obtener_ajustes()
app = FastAPI(
    title="API de frecuencias Sobusa",
    version=__version__,
    description=("Backend del reto de frecuencias (Extreme Technologies v1.5): lectura incremental, calidad, "
                 "pronóstico de demanda 30/60/120 min, recomendación de frecuencia y flota, alertas ALT-001..010, "
                 "registro y activación controlada de modelos. Resultados en el esquema ai_frecuencias."),
    lifespan=ciclo_de_vida,
    **seguridad.rutas_documentacion(ajustes),   # §12.1: Swagger solo en local, pruebas o demo (en producción, 404)
)
observabilidad.configurar(app, ajustes)          # trazas OTel de HTTP, SQLAlchemy y las etapas de cada ejecución
circuito.registrar_integraciones()               # RNF-010: los circuitos se ven en /health y /metrics desde el inicio
seguridad.advertir_configuracion()


@app.middleware("http")
async def correlation_id(request: Request, call_next):
    cid = request.headers.get("X-Correlation-Id") or str(uuid.uuid4())
    token = correlation_id_var.set(cid)
    request.state.correlation_id = cid
    observabilidad.anotar(correlation_id=cid)   # el span HTTP se busca en Jaeger por correlation_id
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
        principal = getattr(request.state, "principal", None)
        log.info("peticion", extra={"metodo": request.method, "ruta": request.url.path, "estado": estado,
                                    "duracion_ms": round(duracion * 1000, 2),
                                    "usuario": principal.usuario if principal else None,
                                    "rol": principal.rol if principal else None})
        correlation_id_var.reset(token)


from app import openapi_doc  # noqa: E402

# §12.1/RNF-009: OpenAPI veraz (errores uniformes, tipos de contenido, rol mínimo) y guarda del byte NUL (422)
openapi_doc.instalar(app)
_openapi_base = app.openapi


def _openapi_con_exportaciones() -> dict:
    """Las exportaciones que arma routers/comun.exportar documentan X-Total-Count y X-Truncado (tope de filas)."""
    from app.routers.comun import documentar_exportaciones

    return documentar_exportaciones(_openapi_base(), prefijos_excluidos=("/api/v1/catalogos", "/api/v1/segmentos",
                                                                         "/api/v1/respuesta"))


app.openapi = _openapi_con_exportaciones  # type: ignore[method-assign]


def _error(status: int, codigo: str, mensaje: str, detalle=None, request: Request | None = None) -> JSONResponse:
    cid = getattr(request.state, "correlation_id", None) if request else correlation_id_var.get()
    return JSONResponse(status_code=status, content={"error": {"codigo": codigo, "mensaje": mensaje,
                                                               "detalle": detalle, "correlation_id": cid}},
                        headers={"X-Correlation-Id": cid} if cid else None)


@app.exception_handler(ErrorApi)
async def _manejar_error_api(request: Request, exc: ErrorApi):
    respuesta = _error(exc.status, exc.codigo, exc.mensaje, exc.detalle, request)
    if exc.status == 401:                         # RFC 9110 §11.6.1: un 401 dice cómo autenticarse
        respuesta.headers["WWW-Authenticate"] = f'ApiKey header="{seguridad.CABECERA}"'
    return respuesta


@app.exception_handler(RequestValidationError)
async def _manejar_validacion(request: Request, exc: RequestValidationError):
    detalle = [{"campo": ".".join(str(x) for x in e.get("loc", [])), "mensaje": e.get("msg"), "tipo": e.get("type")}
               for e in exc.errors()]
    return _error(422, "validacion", "La solicitud no es válida", detalle, request)


@app.exception_handler(StarletteHTTPException)
async def _manejar_http(request: Request, exc: StarletteHTTPException):
    codigos = {400: "cuerpo_ilegible", 404: "no_encontrado", 405: "metodo_no_permitido"}
    return _error(exc.status_code, codigos.get(exc.status_code, "http"), str(exc.detail), None, request)


@app.exception_handler(Exception)
async def _manejar_inesperado(request: Request, exc: Exception):
    logging.getLogger("api_frecuencias").exception("Error no controlado")
    return _error(500, "error_interno", "Error interno; consulte el log con el correlation_id", None, request)


PREFIJO = "/api/v1"
from app.routers import monitoreo as _monitoreo, pronostico_segmentos as _segmentos  # noqa: E402,I001
from app.routers import pronostico_corto_plazo as _corto_plazo  # noqa: E402,I001

# /predictions/segmentos y /predictions/corto-plazo van ANTES de predicciones (si no, /predictions/{prediction_id}
# las captura)
for modulo in (ejecuciones, _segmentos, _corto_plazo, predicciones, alertas, modelos, umbrales, planificador, catalogos,
               _monitoreo):
    # §7.2: toda ruta de /api/v1 exige X-API-Key y el rol que fija la matriz de app/seguridad.py
    app.include_router(modulo.router, prefix=PREFIJO, dependencies=[Depends(seguridad.autenticar)])
# RNF-005: marcas de agua por proceso y ruta (GET /api/v1/frequency/watermarks)
app.include_router(ejecuciones.router_marcas, prefix=PREFIJO, dependencies=[Depends(seguridad.autenticar)])
from app.routers import segmentos as _capa_segmentos  # noqa: E402,I001 §6.1/§6.2 capa analítica
app.include_router(_capa_segmentos.router, prefix=PREFIJO, dependencies=[Depends(seguridad.autenticar)])
from app.routers import respuesta as _respuesta  # noqa: E402,I001 §20 respuesta a la pregunta final del reto
app.include_router(_respuesta.router, prefix=PREFIJO, dependencies=[Depends(seguridad.autenticar)])
from app.routers import retencion as _retencion  # noqa: E402,I001 §18 retención de datos (política y tarea)
app.include_router(_retencion.router, prefix=PREFIJO, dependencies=[Depends(seguridad.autenticar)])


@app.get("/health", tags=["sistema"], summary="Estado del servicio y de la base")
def salud():
    ok = base_disponible()
    integraciones = circuito.estados()           # RNF-010: un circuito abierto degrada, pero la API sigue viva
    abierto = any(c["estado"] != "cerrado" for c in integraciones.values())
    cuerpo = {"estado": "ok" if ok and not abierto else "degradado", "base_datos": "ok" if ok else "sin_conexion",
              "version": __version__, "fuente": obtener_ajustes().fuente, "integraciones": integraciones}
    return JSONResponse(cuerpo, status_code=200 if ok else 503)


@app.get("/metrics", tags=["sistema"], summary="Métricas Prometheus", include_in_schema=True,
         dependencies=[Depends(seguridad.proteger_metricas)])
def metricas():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
