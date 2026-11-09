"""POST/GET /api/v1/frequency/executions: lectura incremental, predicción y optimización como job."""
from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.db import obtener_sesion
from app.esquemas import EjecucionDetalle, EjecucionSalida, ErrorCalidadSalida, Pagina, SolicitudEjecucion
from app.modelos_db import Alerta, Ejecucion, ErrorCalidad, Prediccion, Recomendacion
from app.routers.comun import ErrorApi, ParametrosPagina, no_encontrado, paginar
from app.servicios import ejecucion as servicio

router = APIRouter(prefix="/frequency/executions", tags=["ejecuciones"])


def _inicio_del_dia(dia: date) -> datetime:
    """00:00 del día en America/Bogota (los filtros de fecha se leen en la zona de la operación, §8.1)."""
    return datetime.combine(dia, time(0), tzinfo=servicio.ZONA)


@router.post("", response_model=EjecucionSalida, status_code=202,
             summary="Ejecutar lectura incremental, predicción y optimización (job en segundo plano)")
def crear(solicitud: SolicitudEjecucion, tareas: BackgroundTasks, request: Request,
          sesion: Session = Depends(obtener_sesion)):
    e = servicio.crear_ejecucion(sesion, "frecuencia", solicitud.model_dump(mode="json"),
                                 getattr(request.state, "correlation_id", None))
    tareas.add_task(servicio.ejecutar, e.execution_id)
    return e


@router.get("", response_model=Pagina[EjecucionSalida], summary="Listar ejecuciones")
def listar(estado: str | None = None, tipo: str | None = None,
           desde: date | None = Query(None, description="Creadas desde este día (incluido, America/Bogota)"),
           hasta: date | None = Query(None, description="Creadas hasta este día (incluido, America/Bogota)"),
           model_id: str | None = Query(None, description="Modelo con el que corrió la ejecución"),
           pagina: ParametrosPagina = Depends(), sesion: Session = Depends(obtener_sesion)):
    if desde and hasta and desde > hasta:
        raise ErrorApi(422, "rango_invalido", "desde no puede ser posterior a hasta",
                       {"desde": desde.isoformat(), "hasta": hasta.isoformat()})
    consulta = select(Ejecucion)
    if estado:
        consulta = consulta.where(Ejecucion.estado == estado)
    if tipo:
        consulta = consulta.where(Ejecucion.tipo == tipo)
    if desde:
        consulta = consulta.where(Ejecucion.creado_en >= _inicio_del_dia(desde))
    if hasta and hasta < date.max:          # 9999-12-31 no tiene día siguiente: equivale a no acotar
        consulta = consulta.where(Ejecucion.creado_en < _inicio_del_dia(hasta + timedelta(days=1)))
    if model_id:
        consulta = consulta.where(Ejecucion.model_id == model_id)
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
    salida.predicciones = sesion.scalar(select(func.count()).select_from(Prediccion)
                                        .where(Prediccion.execution_id == execution_id)) or 0
    por_origen = dict(sesion.execute(select(Recomendacion.origen, func.count())
                                     .where(Recomendacion.execution_id == execution_id)
                                     .group_by(Recomendacion.origen)).all())
    salida.recomendaciones = int(por_origen.get("franja", 0))
    salida.recomendaciones_plan_dia = int(por_origen.get("plan_dia", 0))
    salida.alertas = sesion.scalar(select(func.count()).select_from(Alerta)
                                   .where(Alerta.execution_id == execution_id)) or 0
    return salida


@router.get("/{execution_id}/errors", response_model=Pagina[ErrorCalidadSalida],
            summary="Errores de calidad de la ejecución por lote, fila, llave y causa")
def errores(execution_id: uuid.UUID, lote: str | None = None, dimension: str | None = None,
            codigo: str | None = Query(None),
            idruta: int | None = Query(None, ge=0, le=2_147_483_647,
                                       description="Solo los errores de registros de esta ruta (§8.3 idruta)"),
            bloqueante: bool | None = Query(None, description="true: solo los que rechazan la fila"),
            pagina: ParametrosPagina = Depends(), sesion: Session = Depends(obtener_sesion)):
    if sesion.get(Ejecucion, execution_id) is None:
        raise no_encontrado("La ejecución", execution_id)
    consulta = select(ErrorCalidad).where(ErrorCalidad.execution_id == execution_id)
    for col, val in ((ErrorCalidad.lote, lote), (ErrorCalidad.dimension, dimension), (ErrorCalidad.codigo, codigo)):
        if val:
            consulta = consulta.where(col == val)
    if bloqueante is not None:
        consulta = consulta.where(ErrorCalidad.bloqueante.is_(bloqueante))
    if idruta is not None:
        # la llave del registro trae el nombre de la ruta (esquema de demanda) o id_ruta (consolidado de Extreme)
        from app.servicios import dimensiones

        nombre = next((r for r, f in dimensiones.mapa_rutas().items() if f["idruta"] == idruta), None)
        condiciones = [ErrorCalidad.llave["id_ruta"].astext == str(idruta),
                       ErrorCalidad.llave["idruta"].astext == str(idruta)]
        if nombre is not None:
            condiciones.append(ErrorCalidad.llave["ruta"].astext == nombre)
        consulta = consulta.where(or_(*condiciones))
    return paginar(sesion, consulta, ErrorCalidad, pagina, "id")
