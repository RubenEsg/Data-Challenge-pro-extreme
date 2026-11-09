"""Registro de modelos (RF-018, RF-019): consulta, reentrenamiento como job, activación controlada y reversión.

La fuente de verdad del modelo activo es ai_frecuencias.model_registry: las ejecuciones y /predictions/run pasan
siempre el model_id activo a inferencia.predecir(); el registro en disco de inferencia no se modifica desde aquí.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import obtener_sesion
from app.esquemas import (
    EjecucionSalida,
    ModeloSalida,
    Pagina,
    SolicitudActivacion,
    SolicitudEntrenamiento,
    SolicitudReversion,
)
from app.modelos_db import RegistroModelo
from app.routers.comun import ErrorApi, ParametrosPagina, no_encontrado, paginar
from app.servicios import ejecucion as servicio

router = APIRouter(prefix="/models", tags=["modelos"])
log = logging.getLogger("api_frecuencias.modelos")


def _wape(metricas: dict) -> float:
    w = float(metricas["wape"])
    return w / 100.0 if w > 1.5 else w


def _auditar(modelo: RegistroModelo, evento: str, **datos) -> None:
    modelo.auditoria = [*(modelo.auditoria or []), servicio.json_seguro(
        {"evento": evento, "en": servicio.ahora().isoformat(), **datos})]


@router.get("", response_model=Pagina[ModeloSalida], summary="Consultar el registro de modelos")
def listar(estado: str | None = None, tipo: str | None = None, pagina: ParametrosPagina = Depends(),
           sesion: Session = Depends(obtener_sesion)):
    servicio.sembrar_registro(sesion)
    consulta = select(RegistroModelo)
    if estado:
        consulta = consulta.where(RegistroModelo.estado == estado)
    if tipo:
        consulta = consulta.where(RegistroModelo.tipo == tipo)
    return paginar(sesion, consulta, RegistroModelo, pagina, "-creado_en")


@router.post("/train", response_model=EjecucionSalida, status_code=202,
             summary="Entrenar un modelo candidato con los datos validados hasta una fecha (job)")
def entrenar(solicitud: SolicitudEntrenamiento, tareas: BackgroundTasks, request: Request,
             sesion: Session = Depends(obtener_sesion)):
    e = servicio.crear_ejecucion(sesion, "entrenamiento", solicitud.model_dump(mode="json"),
                                 getattr(request.state, "correlation_id", None))
    tareas.add_task(servicio.ejecutar, e.execution_id)
    return e


@router.post("/rollback", response_model=ModeloSalida, summary="Revertir al modelo activo anterior")
def revertir(solicitud: SolicitudReversion, sesion: Session = Depends(obtener_sesion)):
    activo = servicio.modelo_activo(sesion)
    if activo is None or not activo.anterior_model_id:
        raise ErrorApi(409, "sin_version_anterior", "No hay un modelo activo con versión anterior para revertir")
    previo = sesion.scalar(select(RegistroModelo).where(RegistroModelo.model_id == activo.anterior_model_id))
    if previo is None:
        raise no_encontrado("El modelo", activo.anterior_model_id)
    activo.estado = "retirado"
    _auditar(activo, "revertido", usuario=solicitud.usuario, motivo=solicitud.motivo, vuelve_a=previo.model_id)
    sesion.flush()
    previo.estado = "activo"
    previo.aprobado_por = solicitud.usuario
    previo.activado_en = servicio.ahora()
    _auditar(previo, "reactivado_por_reversion", usuario=solicitud.usuario, motivo=solicitud.motivo,
             desde=activo.model_id)
    sesion.commit()
    return previo


@router.get("/{model_id}", response_model=ModeloSalida, summary="Ficha de un modelo")
def uno(model_id: str, sesion: Session = Depends(obtener_sesion)):
    m = sesion.scalar(select(RegistroModelo).where(RegistroModelo.model_id == model_id))
    if m is None:
        raise no_encontrado("El modelo", model_id)
    return m


@router.post("/{model_id}/activate", response_model=ModeloSalida,
             summary="Activar una versión: solo si su WAPE ≤ el del activo en la misma validación temporal")
def activar(model_id: str, solicitud: SolicitudActivacion, sesion: Session = Depends(obtener_sesion)):
    from app.servicios import inferencia

    cand = sesion.scalar(select(RegistroModelo).where(RegistroModelo.model_id == model_id).with_for_update())
    if cand is None:
        raise no_encontrado("El modelo", model_id)
    if cand.estado == "activo":
        raise ErrorApi(409, "ya_activo", f"El modelo {model_id} ya está activo")
    activo = servicio.modelo_activo(sesion)
    corte = cand.data_cutoff.astimezone(servicio.ZONA).date() if cand.data_cutoff else None
    desde = solicitud.validacion_desde or ((corte + timedelta(days=1)) if corte else None)
    hasta = solicitud.validacion_hasta or ((desde + timedelta(days=27)) if desde else None)
    if desde is None or hasta is None:
        raise ErrorApi(422, "sin_ventana_validacion", "Indique validacion_desde y validacion_hasta")
    try:
        from app.servicios import datos

        _, ultimo = datos.rango_fechas()
        hasta = min(hasta, ultimo)
    except Exception:  # noqa: BLE001 - sin rango conocido se usa la ventana pedida
        log.warning("No se pudo leer el rango de fechas de los datos", exc_info=True)
    if desde > hasta:
        raise ErrorApi(409, "sin_datos_validacion", f"No hay datos de validación posteriores al corte {corte}")
    _, umbrales = servicio.umbrales_vigentes(sesion)
    try:
        m_c = inferencia.evaluar(cand.model_id, desde, hasta)
        m_a = inferencia.evaluar(activo.model_id, desde, hasta) if activo else None
    except Exception as exc:  # noqa: BLE001
        raise ErrorApi(409, "validacion_fallida", f"No fue posible evaluar en {desde}..{hasta}: {exc}") from exc
    comparacion = servicio.json_seguro({
        "ventana": {"desde": desde, "hasta": hasta}, "candidato": m_c, "activo": m_a,
        "activo_model_id": activo.model_id if activo else None, "wape_max": umbrales.get("wape_max")})
    motivo = None
    wape_c = _wape(m_c)
    if activo is not None and wape_c > _wape(m_a) + 1e-12:
        motivo = (f"WAPE del candidato {wape_c:.2%} > WAPE del activo {activo.model_id} {_wape(m_a):.2%} "
                  f"en la validación {desde}..{hasta}")
    elif umbrales.get("wape_max") is not None and wape_c > float(umbrales["wape_max"]):
        motivo = f"WAPE del candidato {wape_c:.2%} supera la tolerancia wape_max {float(umbrales['wape_max']):.2%}"
    if motivo:
        cand.estado = "rechazado"
        cand.motivo = motivo
        _auditar(cand, "activacion_rechazada", usuario=solicitud.aprobado_por, motivo=motivo, comparacion=comparacion)
        sesion.commit()
        raise ErrorApi(409, "activacion_rechazada", motivo, comparacion)
    if activo is not None:
        activo.estado = "retirado"
        _auditar(activo, "retirado", reemplazado_por=cand.model_id, usuario=solicitud.aprobado_por)
        sesion.flush()
    cand.estado = "activo"
    cand.aprobado_por = solicitud.aprobado_por
    cand.activado_en = servicio.ahora()
    cand.anterior_model_id = activo.model_id if activo else cand.anterior_model_id
    cand.motivo = solicitud.motivo
    cand.metricas = {**(cand.metricas or {}), "validacion_activacion": comparacion}
    _auditar(cand, "activado", usuario=solicitud.aprobado_por, motivo=solicitud.motivo, comparacion=comparacion)
    sesion.commit()
    return cand
