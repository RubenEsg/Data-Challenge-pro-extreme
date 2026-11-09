"""Alertas (RF-009..RF-011): consulta por filtros, gestión de estado e historial."""
from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import obtener_sesion
from app.esquemas import AlertaSalida, HistorialSalida, Pagina, SolicitudEstadoAlerta
from app.modelos_db import Alerta, HistorialAlerta
from app.routers.comun import ErrorApi, ParametrosPagina, no_encontrado, paginar
from app.servicios.ejecucion import ZONA, ahora, json_seguro

router = APIRouter(prefix="/alerts", tags=["alertas"])


@router.get("", response_model=Pagina[AlertaSalida], summary="Listar alertas por estado, nivel, ruta y fecha")
def listar(estado: str | None = None, severidad: str | None = None, codigo: str | None = None,
           ruta: str | None = None, desde: date | None = None, hasta: date | None = None,
           pagina: ParametrosPagina = Depends(), sesion: Session = Depends(obtener_sesion)):
    consulta = select(Alerta)
    for col, val in ((Alerta.estado, estado), (Alerta.severidad, severidad), (Alerta.codigo, codigo),
                     (Alerta.ruta, ruta)):
        if val:
            consulta = consulta.where(col == val)
    if desde:
        consulta = consulta.where(Alerta.detectada_en >= datetime.combine(desde, time(0), tzinfo=ZONA))
    if hasta:
        consulta = consulta.where(Alerta.detectada_en < datetime.combine(hasta + timedelta(days=1), time(0),
                                                                         tzinfo=ZONA))
    return paginar(sesion, consulta, Alerta, pagina, "-detectada_en")


@router.get("/{alert_id}", response_model=AlertaSalida, summary="Una alerta")
def una(alert_id: uuid.UUID, sesion: Session = Depends(obtener_sesion)):
    a = sesion.get(Alerta, alert_id)
    if a is None:
        raise no_encontrado("La alerta", alert_id)
    return a


@router.patch("/{alert_id}/status", response_model=AlertaSalida,
              summary="Reconocer, asignar, comentar, cerrar o descartar (queda en la bitácora)")
def cambiar(alert_id: uuid.UUID, solicitud: SolicitudEstadoAlerta, sesion: Session = Depends(obtener_sesion)):
    from app.servicios import alertas

    a = sesion.get(Alerta, alert_id, with_for_update=True)
    if a is None:
        raise no_encontrado("La alerta", alert_id)
    try:
        nuevo, entrada = alertas.cambiar_estado({"id": str(a.alert_id), "estado": a.estado}, solicitud.accion,
                                                solicitud.usuario, solicitud.comentario, solicitud.asignado_a)
    except alertas.TransicionInvalida as exc:
        raise ErrorApi(409, "transicion_invalida", str(exc), {"estado_actual": a.estado}) from exc
    except ValueError as exc:
        raise ErrorApi(422, "datos_incompletos", str(exc)) from exc
    anterior = a.estado
    a.estado = nuevo
    if solicitud.accion == "asignar":
        a.asignado_a = solicitud.asignado_a
    if solicitud.comentario:
        a.comentarios = [*a.comentarios, {"usuario": solicitud.usuario, "comentario": solicitud.comentario,
                                          "accion": solicitud.accion, "en": ahora().isoformat()}]
    a.actualizado_en = ahora()
    sesion.add(HistorialAlerta(alert_id=a.alert_id, accion=solicitud.accion, estado_anterior=anterior,
                               estado_nuevo=nuevo, usuario=solicitud.usuario, comentario=solicitud.comentario,
                               asignado_a=solicitud.asignado_a, detalle=json_seguro(entrada)))
    sesion.commit()
    return a


@router.get("/{alert_id}/history", response_model=list[HistorialSalida], summary="Bitácora de cambios de la alerta")
def historial(alert_id: uuid.UUID, sesion: Session = Depends(obtener_sesion)):
    if sesion.get(Alerta, alert_id) is None:
        raise no_encontrado("La alerta", alert_id)
    return sesion.scalars(select(HistorialAlerta).where(HistorialAlerta.alert_id == alert_id)
                          .order_by(HistorialAlerta.creado_en, HistorialAlerta.id)).all()
