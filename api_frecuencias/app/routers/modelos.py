"""Registro de modelos (RF-018, RF-019): consulta, reentrenamiento como job, activación controlada y reversión.

La fuente de verdad del modelo activo es ai_frecuencias.model_registry: las ejecuciones y /predictions/run pasan
siempre el model_id activo a inferencia.predecir(); el registro en disco de inferencia no se modifica desde aquí.

La activación manual no puede saltarse la gobernanza: aplica la misma compuerta de cuatro criterios que la sombra
(politica.compuerta), solo en una ventana posterior a todo lo que vio el candidato (corte + 61 días de validación) y
sobre la serie validada; un modelo rechazado o todavía en sombra necesita forzar=true con motivo, auditado.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request
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
from app.seguridad import Principal, autenticar, usuario_auditoria
from app.servicios import ejecucion as servicio

router = APIRouter(prefix="/models", tags=["modelos"])
log = logging.getLogger("api_frecuencias.modelos")
RECURSO_MODELO = "El modelo"  # sujeto de los mensajes 404 uniformes (no_encontrado)


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
def revertir(solicitud: SolicitudReversion, sesion: Session = Depends(obtener_sesion),
             principal: Principal = Depends(autenticar)):
    usuario = usuario_auditoria(principal, solicitud.usuario)   # RNF-011: la auditoría usa el autenticado
    activo = servicio.modelo_activo(sesion)
    if activo is None or not activo.anterior_model_id:
        raise ErrorApi(409, "sin_version_anterior", "No hay un modelo activo con versión anterior para revertir")
    previo = sesion.scalar(select(RegistroModelo).where(RegistroModelo.model_id == activo.anterior_model_id))
    if previo is None:
        raise no_encontrado(RECURSO_MODELO, activo.anterior_model_id)
    activo.estado = "retirado"
    _auditar(activo, "revertido", usuario=usuario, motivo=solicitud.motivo, vuelve_a=previo.model_id)
    sesion.flush()
    previo.estado = "activo"
    previo.aprobado_por = usuario
    previo.activado_en = servicio.ahora()
    _auditar(previo, "reactivado_por_reversion", usuario=usuario, motivo=solicitud.motivo,
             desde=activo.model_id)
    sesion.commit()
    return previo


@router.get("/{model_id}", response_model=ModeloSalida, summary="Ficha de un modelo")
def uno(model_id: str, sesion: Session = Depends(obtener_sesion)):
    m = sesion.scalar(select(RegistroModelo).where(RegistroModelo.model_id == model_id))
    if m is None:
        raise no_encontrado(RECURSO_MODELO, model_id)
    return m


@router.post("/{model_id}/activate", response_model=ModeloSalida,
             summary="Activar una versión con la compuerta de cuatro criterios, en una ventana posterior a todo lo que "
                     "vio el candidato")
def activar(model_id: str, solicitud: SolicitudActivacion,
            forzar: bool = Query(False, description="Activa aunque la compuerta no apruebe, o un modelo rechazado o "
                                                    "todavía en sombra; exige motivo y queda auditado"),
            sesion: Session = Depends(obtener_sesion), principal: Principal = Depends(autenticar)):
    """Misma compuerta que la sombra (politica.compuerta): WAPE ≤ el del activo y ≤ wape_max, cobertura P10-P90
    calibrada en [cobertura_aviso, cobertura_max] y |sesgo| ≤ sesgo_max, los dos modelos en la MISMA ventana. La
    ventana empieza después del corte del candidato más sus 61 días de validación (o el fin de la serie de su sombra):
    una ventana dentro de la muestra da 422. Un modelo rechazado o en sombra solo se activa con forzar=true y motivo."""
    aprobado_por = usuario_auditoria(principal, solicitud.aprobado_por)   # RNF-011: quién aprueba es el autenticado
    forzar = forzar or bool(getattr(solicitud, "forzar", False))
    if forzar and not (solicitud.motivo or "").strip():
        raise ErrorApi(422, "motivo_requerido", "forzar=true exige un motivo, que queda en la auditoría")
    cand = sesion.scalar(select(RegistroModelo).where(RegistroModelo.model_id == model_id).with_for_update())
    if cand is None:
        raise no_encontrado(RECURSO_MODELO, model_id)
    if cand.estado == "activo":
        raise ErrorApi(409, "ya_activo", f"El modelo {model_id} ya está activo")
    _exigir_forzar(cand, forzar)
    activo = servicio.modelo_activo(sesion)
    desde, hasta, limite = _ventana_validacion(cand, solicitud, sesion)
    version_u, umbrales = servicio.umbrales_vigentes(sesion)
    comp = _compuerta_en_la_ventana(cand, activo, desde, hasta, umbrales, sesion)
    comparacion = servicio.json_seguro({
        "ventana": {"desde": desde, "hasta": hasta}, "limite_en_muestra": limite,
        "candidato": comp["metricas_candidato"], "activo": comp["metricas_activo"],
        "activo_model_id": activo.model_id if activo else None, "wape_max": umbrales.get("wape_max"),
        "umbrales_version": version_u, "compuerta": {k: comp[k] for k in ("aprobado", "criterios", "calibracion")},
        "forzada": bool(forzar and not comp["aprobado"])})
    fallidos = [c["criterio"] for c in comp["criterios"] if not c["ok"]]
    if fallidos and not forzar:
        cand.estado = "rechazado"
        cand.motivo = f"compuerta de activación no aprobada en {desde}..{hasta}: " + "; ".join(fallidos)
        _auditar(cand, "activacion_rechazada", usuario=aprobado_por, motivo=cand.motivo, comparacion=comparacion)
        sesion.commit()
        raise ErrorApi(409, "activacion_rechazada", cand.motivo, comparacion)
    if forzar:
        _auditar(cand, "activacion_forzada", usuario=aprobado_por, motivo=solicitud.motivo,
                 criterios_no_cumplidos=fallidos, estado_previo=cand.estado)
    from app.servicios import politica

    politica.activar_modelo(sesion, cand, activo, aprobado_por, solicitud.motivo or "compuerta de activación aprobada",
                            comparacion, hasta)
    sesion.commit()
    return cand


def _exigir_forzar(cand: RegistroModelo, forzar: bool) -> None:
    """Un modelo que ya falló una compuerta (rechazado) o cuya sombra no ha terminado solo se activa con forzar=true:
    así no se puede probar una ventana tras otra hasta que alguna apruebe, ni saltarse la sombra."""
    if forzar:
        return
    if cand.estado == "rechazado":
        raise ErrorApi(409, "requiere_forzar",
                       f"El modelo {cand.model_id} ya fue rechazado ({cand.motivo}); para activarlo use forzar=true "
                       "con un motivo (queda auditado)", {"estado": cand.estado})
    sombra = ((cand.metricas or {}).get("sombra") or {}).get("estado")
    if sombra == "en_sombra":
        raise ErrorApi(409, "requiere_forzar",
                       f"El modelo {cand.model_id} sigue en sombra: la compuerta de sombra decide al terminar la "
                       "ventana; para activarlo antes use forzar=true con un motivo", {"sombra": sombra})


def _limite_en_muestra(cand: RegistroModelo) -> date | None:
    """Último día que el candidato ya usó: su corte más los 61 días de validación (con ellos se ajustan la calibración
    de la banda y el peso del factor intradía) o, si es mayor, el fin de la serie de su sombra."""
    from app.servicios import politica

    corte = cand.data_cutoff.astimezone(servicio.ZONA).date() if cand.data_cutoff else None
    if corte is None:
        return politica.datos_vistos_hasta(cand)
    limite = corte + timedelta(days=politica.DIAS_VALIDACION)
    sombra = (cand.metricas or {}).get("sombra") or {}
    if sombra.get("estado") not in (None, "no_aplica") and sombra.get("datos_hasta"):
        limite = max(limite, politica._fecha(sombra["datos_hasta"]))
    return limite


def _ventana_validacion(cand: RegistroModelo, solicitud: SolicitudActivacion,
                        sesion: Session) -> tuple[date, date, date | None]:
    """La ventana pedida o, por defecto, los 28 días posteriores a lo que vio el candidato, recortada al último dato
    validado. 422 si empieza dentro de la muestra del candidato (antes o en su corte + validación)."""
    limite = _limite_en_muestra(cand)
    desde = solicitud.validacion_desde or ((limite + timedelta(days=1)) if limite else None)
    hasta = solicitud.validacion_hasta or ((desde + timedelta(days=27)) if desde else None)
    if desde is None or hasta is None:
        raise ErrorApi(422, "sin_ventana_validacion", "Indique validacion_desde y validacion_hasta")
    if limite is not None and desde <= limite:
        corte = cand.data_cutoff.astimezone(servicio.ZONA).date() if cand.data_cutoff else None
        raise ErrorApi(422, "ventana_en_muestra",
                       f"La validación debe empezar después del {limite}: el candidato se entrenó hasta el {corte} y "
                       f"usó hasta el {limite} para calibrar su banda (comparar ahí sería medirlo dentro de la "
                       "muestra)",
                       servicio.json_seguro({"validacion_desde": desde, "data_cutoff": corte,
                                             "limite_en_muestra": limite}))
    hasta = _recortar_al_ultimo_dato(hasta, sesion)
    if desde > hasta:
        raise ErrorApi(409, "sin_datos_validacion",
                       f"Todavía no hay datos validados después del {limite} para comparar al candidato")
    return desde, hasta, limite


def _recortar_al_ultimo_dato(hasta: date, sesion: Session) -> date:
    """Último día con dato real de la serie validada (Parquet con demanda_observada encima)."""
    try:
        from app.servicios import inferencia

        ultimo = inferencia.ultimo_dato_real(inferencia.tabla_variables(sesion))
        return hasta if ultimo is None else min(hasta, ultimo)
    except Exception:  # noqa: BLE001 - sin rango conocido se usa la ventana pedida
        log.warning("No se pudo leer el último dato validado", exc_info=True)
        return hasta


def _compuerta_en_la_ventana(cand: RegistroModelo, activo: RegistroModelo | None, desde: date, hasta: date,
                             umbrales: dict, sesion: Session) -> dict:
    """politica.compuerta en la ventana (los dos modelos, cada uno con su banda calibrada, sobre lo validado)."""
    from app.servicios import politica

    try:
        return politica.compuerta(cand.model_id, activo.model_id if activo else None, desde, hasta, umbrales,
                                  sesion=sesion)
    except Exception as exc:  # noqa: BLE001
        raise ErrorApi(409, "validacion_fallida", f"No fue posible evaluar en {desde}..{hasta}: {exc}") from exc


# ---------------------------------------------------------------- evaluación e importancia (§9.3, §9.4)
def _modelo_en_disco(model_id: str):
    from app.servicios import inferencia

    try:
        inferencia.cargar(model_id)
    except LookupError as exc:
        raise ErrorApi(404, "modelo_no_encontrado", str(exc).strip("'\""), {"model_id": model_id}) from exc
    except inferencia.ErrorIntegridadModelo as exc:
        raise ErrorApi(409, "integridad_modelo", str(exc), {"model_id": model_id}) from exc
    return inferencia


@router.get("/{model_id}/evaluation", summary="Evaluación del modelo: la registrada y, con desde/hasta, la de una "
                                              "ventana sobre datos reales (MAE, RMSE, WAPE, sMAPE, sesgo, cobertura)")
def evaluacion(model_id: str, desde: date | None = None, hasta: date | None = None,
               sesion: Session = Depends(obtener_sesion)):
    inferencia = _modelo_en_disco(model_id)
    salida = inferencia.evaluacion_registrada(model_id)
    if desde or hasta:
        if not (desde and hasta) or desde > hasta:
            raise ErrorApi(422, "ventana_invalida", "Indique desde y hasta (desde <= hasta)")
        try:   # sobre la serie validada: también los días que llegaron después del Parquet empaquetado
            salida["ventana"] = inferencia.evaluar(model_id, desde, hasta, sesion=sesion)
        except ValueError as exc:
            raise ErrorApi(422, "sin_datos", str(exc)) from exc
    return servicio.json_seguro(salida)


@router.get("/{model_id}/importance", summary="Importancia global: permutación (aumento del MAE) y media de |SHAP|")
def importancia(model_id: str):
    inferencia = _modelo_en_disco(model_id)
    return servicio.json_seguro(inferencia.importancia(model_id))
