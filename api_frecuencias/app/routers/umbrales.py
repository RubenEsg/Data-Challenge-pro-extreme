"""Umbrales operativos de §5.1 guardados en PostgreSQL y versionados (regla de gobierno).

§5.1 dice que los valores son referencias iniciales y requieren validación del área operativa: cada versión nace
«propuesta» (aprobado_por nulo) y el área operativa la aprueba con POST /thresholds/{version}/aprobar (rol admin),
que firma aprobado_por y aprobado_en en todas las filas de esa versión.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Path
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db import obtener_sesion
from app.esquemas import SolicitudAprobacionUmbrales, SolicitudUmbrales, UmbralesVigentes, UmbralSalida
from app.modelos_db import Umbral
from app.routers.comun import ErrorApi, no_encontrado
from app.seguridad import Principal, autenticar, usuario_auditoria
from app.servicios import ejecucion as servicio

router = APIRouter(prefix="/thresholds", tags=["umbrales"])


def _resumen(filas: list[Umbral], version: int) -> UmbralesVigentes:
    aprobada = next((f for f in filas if f.aprobado_por), None)
    return UmbralesVigentes(version=version, valores={f.nombre: f.valor for f in filas},
                            detalle=[UmbralSalida.model_validate(f) for f in filas],
                            estado="aprobada" if aprobada else "propuesta",
                            aprobado_por=aprobada.aprobado_por if aprobada else None,
                            aprobado_en=aprobada.aprobado_en if aprobada else None)


def _vigentes(sesion: Session) -> UmbralesVigentes:
    filas = sesion.scalars(select(Umbral).where(Umbral.vigente).order_by(Umbral.nombre)).all()
    return _resumen(list(filas), max((f.version for f in filas), default=0))


@router.get("", response_model=UmbralesVigentes, summary="Umbrales vigentes, su versión y si están aprobados")
def vigentes(sesion: Session = Depends(obtener_sesion)):
    return _vigentes(sesion)


@router.get("/history", response_model=list[UmbralSalida], summary="Histórico de versiones de los umbrales")
def historial(nombre: str | None = None, sesion: Session = Depends(obtener_sesion)):
    consulta = select(Umbral).order_by(Umbral.version.desc(), Umbral.nombre)
    if nombre:
        consulta = consulta.where(Umbral.nombre == nombre)
    return sesion.scalars(consulta.limit(1000)).all()


@router.put("", response_model=UmbralesVigentes, summary="Cambiar umbrales: crea una versión nueva del conjunto")
def cambiar(solicitud: SolicitudUmbrales, sesion: Session = Depends(obtener_sesion),
            principal: Principal = Depends(autenticar)):
    creado_por = usuario_auditoria(principal, solicitud.creado_por)   # RNF-011: la versión la firma el autenticado
    try:
        servicio.nueva_version_umbrales(sesion, solicitud.valores, creado_por, solicitud.motivo)
    except ValueError as exc:
        sesion.rollback()
        raise ErrorApi(422, "umbral_invalido", str(exc)) from exc
    return _vigentes(sesion)


@router.post("/{version}/aprobar", response_model=UmbralesVigentes,
             summary="Aprobar una versión de umbrales (validación del área operativa, §5.1)",
             description="Firma aprobado_por (el usuario autenticado) y aprobado_en en todas las filas de la versión. "
                         "Es idempotente: si la versión ya estaba aprobada, conserva la primera aprobación y la "
                         "devuelve. La respuesta describe la versión aprobada, vigente o no.")
def aprobar(version: int = Path(..., ge=1, le=2_147_483_647, description="Versión de threshold_config"),
            solicitud: SolicitudAprobacionUmbrales | None = None, sesion: Session = Depends(obtener_sesion),
            principal: Principal = Depends(autenticar)):
    filas = list(sesion.scalars(select(Umbral).where(Umbral.version == version).order_by(Umbral.nombre)).all())
    if not filas:
        raise no_encontrado("La versión de umbrales", version)
    if not any(f.aprobado_por for f in filas):
        solicitud = solicitud or SolicitudAprobacionUmbrales()
        quien = usuario_auditoria(principal, solicitud.aprobado_por)
        valores = {"aprobado_por": quien, "aprobado_en": servicio.ahora()}
        if solicitud.comentario:
            valores["motivo"] = " · ".join(x for x in (filas[0].motivo, f"Aprobación: {solicitud.comentario}") if x)
        sesion.execute(update(Umbral).where(Umbral.version == version).values(**valores))
        sesion.commit()
        filas = list(sesion.scalars(select(Umbral).where(Umbral.version == version).order_by(Umbral.nombre)).all())
    return _resumen(filas, version)
