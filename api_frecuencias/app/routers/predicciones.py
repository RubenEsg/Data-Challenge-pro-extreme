"""Predicciones (RF-005, RF-006, RF-015) y recomendaciones (RF-007, RF-008) con consulta y exportación (RF-016/017)."""
from __future__ import annotations

import uuid
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import obtener_sesion
from app.esquemas import (
    Pagina,
    PrediccionRespuesta,
    PrediccionSalida,
    RecomendacionSalida,
    SolicitudPrediccion,
    SolicitudRecomendacion,
)
from app.modelos_db import Prediccion, Recomendacion
from app.routers.comun import ErrorApi, ParametrosPagina, exportar, no_encontrado, paginar
from app.servicios import ejecucion as servicio

router = APIRouter(tags=["predicciones y recomendaciones"])
Formato = Literal["csv", "xlsx"]


def _info_ruta(ruta: str) -> dict:
    from app.servicios import datos

    try:
        return datos.ruta_info(ruta)
    except KeyError as exc:
        raise ErrorApi(404, "ruta_desconocida", str(exc).strip("'\"")) from exc


@router.post("/predictions/run", response_model=PrediccionRespuesta, status_code=201,
             summary="Inferencia para una ruta y un horizonte (incluye la recomendación derivada)")
def correr_prediccion(solicitud: SolicitudPrediccion, sesion: Session = Depends(obtener_sesion)):
    from app.servicios import inferencia, optimizacion

    info = _info_ruta(solicitud.ruta)
    ruta = info["ruta"]
    activo = servicio.modelo_activo(sesion)
    model_id = solicitud.model_id or (activo.model_id if activo else None)
    instante = servicio.a_instante(solicitud.instante)
    try:
        r = inferencia.predecir(ruta, instante, solicitud.horizonte_min, model_id=model_id)
    except LookupError as exc:
        raise ErrorApi(404, "modelo_no_encontrado", str(exc).strip("'\""), {"model_id": model_id}) from exc
    except ValueError as exc:
        raise ErrorApi(422, "prediccion_invalida", str(exc)) from exc
    pred = servicio.guardar_prediccion(sesion, r, ruta=ruta, instante=instante,
                                       horizonte_min=solicitud.horizonte_min, model_id=model_id, execution_id=None)
    rec = None
    if solicitud.incluir_recomendacion:
        version_u, umbrales = servicio.umbrales_vigentes(sesion)
        entradas = servicio.parametros_recomendacion(info, umbrales)
        rec_d = optimizacion.recomendar(ruta, pred.hora, demanda_hora=pred.pasajeros, demanda_p90=pred.p90, **entradas)
        rec = servicio.construir_recomendacion(rec_d, ruta=ruta, fecha=pred.fecha, hora=pred.hora,
                                               demanda_hora=pred.pasajeros, demanda_p90=pred.p90, execution_id=None,
                                               prediction_id=pred.prediction_id, umbrales_version=version_u,
                                               entradas=entradas)
        sesion.add(rec)
    sesion.commit()
    salida = PrediccionRespuesta.model_validate(pred)
    salida.recomendacion = RecomendacionSalida.model_validate(rec) if rec is not None else None
    return salida


def _filtrar_predicciones(ruta, desde, hasta, horizonte_min, execution_id, model_id):
    consulta = select(Prediccion)
    if ruta:
        consulta = consulta.where(Prediccion.ruta == ruta)
    if desde:
        consulta = consulta.where(Prediccion.fecha >= desde)
    if hasta:
        consulta = consulta.where(Prediccion.fecha <= hasta)
    if horizonte_min:
        consulta = consulta.where(Prediccion.horizonte_min == horizonte_min)
    if execution_id:
        consulta = consulta.where(Prediccion.execution_id == execution_id)
    if model_id:
        consulta = consulta.where(Prediccion.model_id == model_id)
    return consulta


@router.get("/predictions", response_model=Pagina[PrediccionSalida], summary="Consultar pronósticos por filtros")
def listar_predicciones(ruta: str | None = None, desde: date | None = None, hasta: date | None = None,
                        horizonte_min: int | None = Query(None), execution_id: uuid.UUID | None = None,
                        model_id: str | None = None, pagina: ParametrosPagina = Depends(),
                        sesion: Session = Depends(obtener_sesion)):
    consulta = _filtrar_predicciones(ruta, desde, hasta, horizonte_min, execution_id, model_id)
    return paginar(sesion, consulta, Prediccion, pagina, "-generated_at")


@router.get("/predictions/export", summary="Exportar pronósticos filtrados (CSV o XLSX)",
            response_class=__import__("fastapi").responses.Response)
def exportar_predicciones(formato: Formato = "csv", ruta: str | None = None, desde: date | None = None,
                          hasta: date | None = None, horizonte_min: int | None = None,
                          execution_id: uuid.UUID | None = None, model_id: str | None = None,
                          orden: str | None = None, sesion: Session = Depends(obtener_sesion)):
    consulta = _filtrar_predicciones(ruta, desde, hasta, horizonte_min, execution_id, model_id)
    return exportar(sesion, consulta, Prediccion, formato, "predicciones", orden, "-generated_at")


@router.get("/predictions/{prediction_id}", response_model=PrediccionSalida, summary="Una predicción")
def una_prediccion(prediction_id: uuid.UUID, sesion: Session = Depends(obtener_sesion)):
    pred = sesion.get(Prediccion, prediction_id)
    if pred is None:
        raise no_encontrado("La predicción", prediction_id)
    return pred


@router.post("/recommendations/calculate", response_model=RecomendacionSalida, status_code=201,
             summary="Calcular frecuencia y flota (§10.3) con las restricciones y umbrales vigentes")
def calcular(solicitud: SolicitudRecomendacion, sesion: Session = Depends(obtener_sesion)):
    from app.servicios import optimizacion

    info = _info_ruta(solicitud.ruta)
    version_u, umbrales = servicio.umbrales_vigentes(sesion)
    entradas = servicio.parametros_recomendacion(info, umbrales)
    for campo in ("capacidad", "ocupacion_objetivo", "tiempo_ciclo_min", "headway_min", "headway_max",
                  "frecuencia_actual_min"):
        valor = getattr(solicitud, campo)
        if valor is not None:
            entradas[campo] = valor
    if solicitud.flota_disponible is not None:
        entradas["flota_disponible"] = solicitud.flota_disponible
    if solicitud.prediction_id is not None and sesion.get(Prediccion, solicitud.prediction_id) is None:
        raise no_encontrado("La predicción", solicitud.prediction_id)
    try:
        r = optimizacion.recomendar(info["ruta"], solicitud.hora, demanda_hora=solicitud.demanda_hora,
                                    demanda_p90=solicitud.demanda_p90, **entradas)
    except ValueError as exc:
        raise ErrorApi(422, "parametros_invalidos", str(exc)) from exc
    rec = servicio.construir_recomendacion(
        r, ruta=info["ruta"], fecha=solicitud.fecha or servicio.ahora().astimezone(servicio.ZONA).date(),
        hora=solicitud.hora, demanda_hora=solicitud.demanda_hora, demanda_p90=solicitud.demanda_p90,
        execution_id=None, prediction_id=solicitud.prediction_id, umbrales_version=version_u, entradas=entradas)
    sesion.add(rec)
    sesion.commit()
    return rec


def _filtrar_recomendaciones(ruta, desde, hasta, viable, execution_id):
    consulta = select(Recomendacion)
    if ruta:
        consulta = consulta.where(Recomendacion.ruta == ruta)
    if desde:
        consulta = consulta.where(Recomendacion.fecha >= desde)
    if hasta:
        consulta = consulta.where(Recomendacion.fecha <= hasta)
    if viable is not None:
        consulta = consulta.where(Recomendacion.viable == viable)
    if execution_id:
        consulta = consulta.where(Recomendacion.execution_id == execution_id)
    return consulta


@router.get("/recommendations", response_model=Pagina[RecomendacionSalida], summary="Consultar recomendaciones")
def listar_recomendaciones(ruta: str | None = None, desde: date | None = None, hasta: date | None = None,
                           viable: bool | None = None, execution_id: uuid.UUID | None = None,
                           pagina: ParametrosPagina = Depends(), sesion: Session = Depends(obtener_sesion)):
    consulta = _filtrar_recomendaciones(ruta, desde, hasta, viable, execution_id)
    return paginar(sesion, consulta, Recomendacion, pagina, "-creado_en")


@router.get("/recommendations/export", summary="Exportar recomendaciones filtradas (CSV o XLSX)",
            response_class=__import__("fastapi").responses.Response)
def exportar_recomendaciones(formato: Formato = "csv", ruta: str | None = None, desde: date | None = None,
                             hasta: date | None = None, viable: bool | None = None,
                             execution_id: uuid.UUID | None = None, orden: str | None = None,
                             sesion: Session = Depends(obtener_sesion)):
    consulta = _filtrar_recomendaciones(ruta, desde, hasta, viable, execution_id)
    return exportar(sesion, consulta, Recomendacion, formato, "recomendaciones", orden, "-creado_en")
