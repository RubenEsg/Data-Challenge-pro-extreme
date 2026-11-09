"""POST/GET /api/v1/frequency/executions: lectura incremental, predicción y optimización como job."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import obtener_sesion
from app.esquemas import EjecucionDetalle, EjecucionSalida, ErrorCalidadSalida, Pagina, SolicitudEjecucion
from app.modelos_db import Alerta, Ejecucion, ErrorCalidad, Prediccion, Recomendacion
from app.routers.comun import ParametrosPagina, no_encontrado, paginar
from app.servicios import ejecucion as servicio

router = APIRouter(prefix="/frequency/executions", tags=["ejecuciones"])


@router.post("", response_model=EjecucionSalida, status_code=202,
             summary="Ejecutar lectura incremental, predicción y optimización (job en segundo plano)")
def crear(solicitud: SolicitudEjecucion, tareas: BackgroundTasks, request: Request,
          sesion: Session = Depends(obtener_sesion)):
    e = servicio.crear_ejecucion(sesion, "frecuencia", solicitud.model_dump(mode="json"),
                                 getattr(request.state, "correlation_id", None))
    tareas.add_task(servicio.ejecutar, e.execution_id)
    return e


@router.get("", response_model=Pagina[EjecucionSalida], summary="Listar ejecuciones")
def listar(estado: str | None = None, tipo: str | None = None, pagina: ParametrosPagina = Depends(),
           sesion: Session = Depends(obtener_sesion)):
    consulta = select(Ejecucion)
    if estado:
        consulta = consulta.where(Ejecucion.estado == estado)
    if tipo:
        consulta = consulta.where(Ejecucion.tipo == tipo)
    return paginar(sesion, consulta, Ejecucion, pagina, "-creado_en")


@router.get("/{execution_id}", response_model=EjecucionDetalle, summary="Corte, estado, métricas y errores")
def detalle(execution_id: uuid.UUID, sesion: Session = Depends(obtener_sesion)):
    e = sesion.get(Ejecucion, execution_id)
    if e is None:
        raise no_encontrado("La ejecución", execution_id)
    salida = EjecucionDetalle.model_validate(e)
    salida.errores_por_dimension = dict(sesion.execute(
        select(ErrorCalidad.dimension, func.count()).where(ErrorCalidad.execution_id == execution_id)
        .group_by(ErrorCalidad.dimension)).all())
    salida.errores_muestra = [ErrorCalidadSalida.model_validate(x) for x in sesion.scalars(
        select(ErrorCalidad).where(ErrorCalidad.execution_id == execution_id).order_by(ErrorCalidad.id).limit(20))]
    for campo, modelo in (("predicciones", Prediccion), ("recomendaciones", Recomendacion), ("alertas", Alerta)):
        setattr(salida, campo, sesion.scalar(select(func.count()).select_from(modelo)
                                             .where(modelo.execution_id == execution_id)) or 0)
    return salida


@router.get("/{execution_id}/errors", response_model=Pagina[ErrorCalidadSalida],
            summary="Errores de calidad de la ejecución por lote, fila y causa")
def errores(execution_id: uuid.UUID, lote: str | None = None, dimension: str | None = None,
            codigo: str | None = Query(None), pagina: ParametrosPagina = Depends(),
            sesion: Session = Depends(obtener_sesion)):
    if sesion.get(Ejecucion, execution_id) is None:
        raise no_encontrado("La ejecución", execution_id)
    consulta = select(ErrorCalidad).where(ErrorCalidad.execution_id == execution_id)
    for col, val in ((ErrorCalidad.lote, lote), (ErrorCalidad.dimension, dimension), (ErrorCalidad.codigo, codigo)):
        if val:
            consulta = consulta.where(col == val)
    return paginar(sesion, consulta, ErrorCalidad, pagina, "id")
