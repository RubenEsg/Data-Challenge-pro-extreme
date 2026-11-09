"""Umbrales operativos de §5.1 guardados en PostgreSQL y versionados (regla de gobierno)."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import obtener_sesion
from app.esquemas import SolicitudUmbrales, UmbralesVigentes, UmbralSalida
from app.modelos_db import Umbral
from app.routers.comun import ErrorApi
from app.servicios import ejecucion as servicio

router = APIRouter(prefix="/thresholds", tags=["umbrales"])


def _vigentes(sesion: Session) -> UmbralesVigentes:
    filas = sesion.scalars(select(Umbral).where(Umbral.vigente).order_by(Umbral.nombre)).all()
    return UmbralesVigentes(version=max((f.version for f in filas), default=0),
                            valores={f.nombre: f.valor for f in filas},
                            detalle=[UmbralSalida.model_validate(f) for f in filas])


@router.get("", response_model=UmbralesVigentes, summary="Umbrales vigentes y su versión")
def vigentes(sesion: Session = Depends(obtener_sesion)):
    return _vigentes(sesion)


@router.get("/history", response_model=list[UmbralSalida], summary="Histórico de versiones de los umbrales")
def historial(nombre: str | None = None, sesion: Session = Depends(obtener_sesion)):
    consulta = select(Umbral).order_by(Umbral.version.desc(), Umbral.nombre)
    if nombre:
        consulta = consulta.where(Umbral.nombre == nombre)
    return sesion.scalars(consulta.limit(1000)).all()


@router.put("", response_model=UmbralesVigentes, summary="Cambiar umbrales: crea una versión nueva del conjunto")
def cambiar(solicitud: SolicitudUmbrales, sesion: Session = Depends(obtener_sesion)):
    try:
        servicio.nueva_version_umbrales(sesion, solicitud.valores, solicitud.creado_por, solicitud.motivo)
    except ValueError as exc:
        sesion.rollback()
        raise ErrorApi(422, "umbral_invalido", str(exc)) from exc
    return _vigentes(sesion)
