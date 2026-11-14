"""/api/v1/segmentos: capa analítica de segmentos y zonas tarifarias (§6.1, §6.2, §11.2), en solo lectura.

Autenticación y rol: los GET exigen al menos «operador» (app/seguridad.py, registro en main.py). Paginación con
limite/desplazamiento, orden con lista blanca y exportación CSV o XLSX (RF-017).

§7.1 y RNF-004: GET /estadisticas y su exportación leen la agregación materializada en el esquema propio
(app/servicios/segmentos.py) y nunca agregan timbradas_segmentos dentro de la petición. La agregación la calcula el
trabajo «segmentos» de la cola (app/servicios/segmentos_refresco.py): lo programa el planificador, lo encola el ciclo
diario cuando llegan datos nuevos y lo pide POST /estadisticas/refrescar (rol analista, 202 con el execution_id). La
respuesta dice de cuándo es la agregación (actualizado_en); si todavía no existe, responde 200 con «disponible: false»
y el refresco encolado en vez de bloquear.

Sin base operacional configurada (modo offline, FUENTE_DATABASE_URL vacía) y sin agregación guardada responde 200
con «disponible: false» y la razón, en vez de un 5xx: la capa analítica solo existe en modo integrado
(docker-compose.integracion.yml). Los errores de las bases (caída, timeout, circuito abierto) responden 503.
"""
from __future__ import annotations

import uuid
from datetime import date
from typing import Literal

import pandas as pd
from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from app.db import obtener_sesion
from app.routers.comun import ErrorApi, ParametrosPagina
from app.servicios import segmentos as servicio
from app.servicios import segmentos_refresco as refresco

router = APIRouter(prefix="/segmentos", tags=["segmentos"])
ENTERO_MAX = 2_147_483_647          # INTEGER de PostgreSQL
BIGINT_MAX = 9_223_372_036_854_775_807
RUTA_EJECUCIONES = "/api/v1/frequency/executions"


def _filtros(idruta: int | None = Query(None, ge=0, le=ENTERO_MAX, description="idruta (2, 16 o 21)"),
             desde: date | None = Query(None, description="Fecha inicial (timbradas_segmentos.fecha)"),
             hasta: date | None = Query(None, description="Fecha final"),
             id_segmento: int | None = Query(None, ge=0, le=BIGINT_MAX, description="rutas_segmentos.id"),
             id_estacionalidad: int | None = Query(None, ge=0, le=BIGINT_MAX,
                                                   description="estacionalidades.id_estacionalidad"),
             id_dia_semana: int | None = Query(None, ge=1, le=7, description="Día ISO: 1 lunes … 7 domingo"),
             hora: int | None = Query(None, ge=0, le=23, description="Hora del bloque (hora_inicio)")) -> dict:
    return {"idruta": idruta, "desde": desde, "hasta": hasta, "id_segmento": id_segmento,
            "id_estacionalidad": id_estacionalidad, "id_dia_semana": id_dia_semana, "hora": hora}


class SolicitudRefresco(BaseModel):
    modo: Literal["auto", "completo", "incremental", "rango"] = Field(
        "auto", description="auto (incremental, o completo si cambiaron los catálogos o pasó el plazo), completo, "
                            "incremental o rango (desde y hasta obligatorios)")
    desde: date | None = Field(None, description="Solo con modo rango: primera fecha a releer")
    hasta: date | None = Field(None, description="Solo con modo rango: última fecha a releer")

    @model_validator(mode="after")
    def _rango_coherente(self):
        refresco.validar_parametros(self.model_dump())
        return self


class RefrescoEnCola(BaseModel):
    execution_id: uuid.UUID
    tipo: str
    estado: str
    nueva: bool = Field(description="false si ya había un refresco igual en cola (no se duplica)")
    modo: str
    desde: str | None = None
    hasta: str | None = None
    creado_en: str | None = Field(None, description="Instante en que se encoló (-05:00)")
    consultar_estado: str = Field(description="Ruta para seguir el progreso y el resultado del trabajo")
    consultar_estadisticas: str = Field(description="Ruta que sirve la agregación cuando termine")


def _no_disponible(exc: Exception, pagina: ParametrosPagina) -> dict:
    return {"total": 0, "limite": pagina.limite, "desplazamiento": pagina.desplazamiento, "items": [],
            "disponible": False, "nota": str(exc), "actualizado_en": None}


def _llamar(funcion, *args, **kwargs):
    try:
        return funcion(*args, **kwargs)
    except ValueError as exc:
        raise ErrorApi(422, "parametro_invalido", str(exc)) from exc
    except servicio.FuenteNoConfigurada:
        raise
    except Exception as exc:  # noqa: BLE001 - base caída, timeout o circuito abierto: dependencia no disponible
        raise ErrorApi(503, "fuente_no_disponible", "La base de resultados o la operacional no respondió; reintente "
                       "más tarde", {"error": type(exc).__name__}) from exc


def _en_cola(e, nueva: bool) -> dict:
    from app.servicios.respuesta import instante_bogota

    p = e.parametros or {}
    return {"execution_id": e.execution_id, "tipo": e.tipo, "estado": e.estado, "nueva": nueva,
            "modo": p.get("modo") or "auto", "desde": p.get("desde"), "hasta": p.get("hasta"),
            "creado_en": instante_bogota(e.creado_en),
            "consultar_estado": f"{RUTA_EJECUCIONES}/{e.execution_id}",
            "consultar_estadisticas": "/api/v1/segmentos/estadisticas"}


def _encolar(sesion: Session, tareas: BackgroundTasks, request: Request, parametros: dict, **kw) -> dict:
    """Encola (o reutiliza) un refresco y, si es nuevo, lo despacha con ejecucion.ejecutar. FuenteNoConfigurada sube."""
    from app.servicios import ejecucion

    e, nueva = _llamar(refresco.solicitar, sesion, parametros, getattr(request.state, "correlation_id", None), **kw)
    if nueva:
        tareas.add_task(ejecucion.ejecutar, e.execution_id)
    return _en_cola(e, nueva)


def _sin_agregacion(sesion: Session, tareas: BackgroundTasks, request: Request, pagina: ParametrosPagina) -> dict:
    """La agregación todavía no existe: lo dice y encola el refresco (sin base operacional, solo lo dice)."""
    try:
        en_cola = _encolar(sesion, tareas, request, {"modo": "auto", "origen": "consulta"}, cualquiera_en_curso=True)
    except servicio.FuenteNoConfigurada as exc:
        return _no_disponible(exc, pagina)
    nota = ("La agregación de segmentos todavía no se ha calculado: el refresco quedó en la cola y la consulta "
            "responderá en cuanto termine (ver consultar_estado)")
    return {**_no_disponible(RuntimeError(nota), pagina), "refresco": en_cola}


DESCRIPCION = (
    "Promedio, máximo y mínimo de subidas, bajadas y pasajeros por segmento × estacionalidad × día ISO × hora (§6.1), "
    "desde la agregación materializada que calcula el trabajo «segmentos» de la cola (nunca se agrega "
    "timbradas_segmentos dentro de la petición, §7.1). `actualizado_en` dice de cuándo es; `materializacion` trae "
    "el período cubierto y la ejecución que la calculó. Con `desde`/`hasta` se vuelve a agregar solo ese rango desde "
    "el grano diario, con el mismo resultado que la agregación directa. Si la agregación todavía no existe responde "
    "200 con `disponible: false` y el refresco encolado en `refresco`.")


@router.get("/estadisticas", summary="Promedio, máximo y mínimo de subidas, bajadas y pasajeros por segmento, "
                                     "estacionalidad, día, hora", description=DESCRIPCION)
def estadisticas(tareas: BackgroundTasks, request: Request, filtros: dict = Depends(_filtros),
                 pagina: ParametrosPagina = Depends(), sesion: Session = Depends(obtener_sesion)) -> dict:
    respuesta = _llamar(servicio.consultar, sesion, orden=pagina.orden, limite=pagina.limite,
                        desplazamiento=pagina.desplazamiento, **filtros)
    return respuesta if respuesta is not None else _sin_agregacion(sesion, tareas, request, pagina)


def _exportacion_sin_agregacion(sesion: Session, tareas: BackgroundTasks, request: Request) -> pd.DataFrame:
    """Sin agregación: con base operacional, 503 «agregacion_pendiente» y el refresco en cola; sin ella, el archivo
    sale vacío con sus columnas (como antes en modo offline)."""
    try:
        en_cola = _encolar(sesion, tareas, request, {"modo": "auto", "origen": "exportacion"},
                           cualquiera_en_curso=True)
    except servicio.FuenteNoConfigurada:
        return pd.DataFrame(columns=[c.strip() for c in servicio.COLUMNAS.split(",")])
    raise ErrorApi(503, "agregacion_pendiente", "La agregación de segmentos todavía se está calculando; descargue "
                   "cuando termine el refresco", {"execution_id": str(en_cola["execution_id"]),
                                                  "consultar_estado": en_cola["consultar_estado"]})


@router.get("/estadisticas/export", summary="Exportar las estadísticas por segmento (CSV o XLSX)",
            response_class=Response)
def exportar_estadisticas(tareas: BackgroundTasks, request: Request, filtros: dict = Depends(_filtros),
                          formato: Literal["csv", "xlsx"] = "csv", orden: str | None = None,
                          sesion: Session = Depends(obtener_sesion)) -> Response:
    df = _llamar(servicio.consultar_df, sesion, orden=orden, **filtros)
    if df is None:
        df = _exportacion_sin_agregacion(sesion, tareas, request)
    contenido, tipo, nombre = servicio.exportar(df, formato, "estadisticas_segmentos")
    return Response(contenido, media_type=tipo, headers={"Content-Disposition": f'attachment; filename="{nombre}"'})


@router.post("/estadisticas/refrescar", response_model=RefrescoEnCola, status_code=202,
             summary="Refrescar la agregación de segmentos (job en la cola, rol analista)",
             description="Encola un trabajo «segmentos» que relee timbradas_segmentos con el usuario de solo lectura "
                         "(por tramos de fechas que caben en el statement_timeout) y reemplaza la agregación "
                         "materializada que sirve GET /api/v1/segmentos/estadisticas. Responde 202 con el "
                         "execution_id; el progreso y el resultado se ven en GET /api/v1/frequency/executions/{id}. "
                         "Si ya hay un refresco igual en cola, devuelve ese. 503 «fuente_no_configurada» sin la base "
                         "operacional (FUENTE_DATABASE_URL).")
def refrescar(tareas: BackgroundTasks, request: Request, solicitud: SolicitudRefresco | None = None,
              sesion: Session = Depends(obtener_sesion)):
    solicitud = solicitud or SolicitudRefresco()
    parametros = {**solicitud.model_dump(mode="json"), "origen": "api"}
    try:
        return _encolar(sesion, tareas, request, parametros)
    except servicio.FuenteNoConfigurada as exc:
        raise ErrorApi(503, "fuente_no_configurada", str(exc)) from exc


@router.get("/zonas", summary="Demanda por zona tarifaria (timbradas_anio_zonas / timbradas_consolidado_zonas)")
def zonas(nivel: Literal["anio", "consolidado"] = "consolidado",
          idruta: int | None = Query(None, ge=0, le=ENTERO_MAX), id_dia_semana: int | None = Query(None, ge=1, le=7),
          pagina: ParametrosPagina = Depends()) -> dict:
    try:
        return _llamar(servicio.zonas, nivel=nivel, idruta=idruta, id_dia_semana=id_dia_semana, limite=pagina.limite,
                       desplazamiento=pagina.desplazamiento)
    except servicio.FuenteNoConfigurada as exc:
        return _no_disponible(exc, pagina)
