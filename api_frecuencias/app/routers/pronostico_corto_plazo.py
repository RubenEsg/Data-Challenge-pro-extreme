"""Pronóstico de corto plazo: las subidas de los próximos 30, 60 y 120 minutos por ruta, sentido y segmento, con lo
observado hasta el instante (spec v1.5 §2.2 «predecir la demanda para horizontes configurables de 30, 60 y 120
minutos», RF-005, RF-006, §3.1 M3, §9.1, §9.2, §9.4, §12.3).

Es el modelo del experimento E14, elegido en la validación de enero a junio de 2025 y medido una sola vez en la prueba
reservada de julio a diciembre de 2025 (app/servicios/corto_plazo.py; registro datos/modelos/corto_plazo, artefactos
con SHA-256 verificados al cargar). El modelo horario de /predictions/run sigue siendo el del plan del día siguiente.

POST /api/v1/predictions/corto-plazo                 pronostica y guarda (ruta, sentidos y segmentos)
GET  /api/v1/predictions/corto-plazo                 consulta los pronósticos guardados por filtros
GET  /api/v1/predictions/corto-plazo/export          los mismos filtros en CSV o XLSX
GET  /api/v1/predictions/corto-plazo/calcular        pronostica sin guardar (lo usa el tablero)
GET  /api/v1/predictions/corto-plazo/dia             la curva del día, cada media hora de 04:00 a 21:00
GET  /api/v1/predictions/corto-plazo/modelo          la versión activa con su prueba reservada y su cobertura
"""
from __future__ import annotations

import math
import uuid
from datetime import date, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import obtener_sesion
from app.esquemas import (
    DESC_CP_INSTANTE,
    DESC_CP_RUTA,
    DiaCortoPlazo,
    IntervaloConfianza,
    ModeloCortoPlazo,
    Pagina,
    PrediccionCortoPlazoSalida,
    PronosticoCortoPlazo,
    RecomendacionResumen,
    SolicitudCortoPlazo,
)
from app.modelos_db import PrediccionCortoPlazo
from app.routers.comun import ErrorApi, HorizonteConsulta, ParametrosPagina, exportar, paginar
from app.servicios import corto_plazo as cp
from app.servicios import ejecucion as servicio

router = APIRouter(tags=["pronóstico de corto plazo"])
RUTA = "/predictions/corto-plazo"
Formato = Literal["csv", "xlsx"]
Nivel = Literal["ruta", "sentido", "segmento"]
HorizonteObligatorio = Annotated[int, Query(ge=30, le=120, json_schema_extra={"enum": [30, 60, 120]},
                                            description="Horizonte en minutos: 30, 60 o 120")]


def _info_ruta(ruta: str) -> dict:
    from app.servicios import datos

    try:
        return datos.ruta_info(ruta)
    except KeyError as exc:
        raise ErrorApi(404, "ruta_desconocida", str(exc).strip("'\"")) from exc


def _horizonte(h: int) -> int:
    if h not in (30, 60, 120):
        raise ErrorApi(422, "horizonte_invalido", f"Horizonte {h}: el pronóstico de corto plazo es a 30, 60 o 120 "
                                                  "minutos", {"horizonte_min": h})
    return h


def modelo_de_la_familia(sesion: Session, model_id: str | None) -> str | None:
    """El model_id pedido o, si falta, el activo de la familia corto_plazo en model_registry (la fuente de verdad del
    ciclo de vida, RF-019); sin registro en la base, el activo del registro en disco."""
    if model_id:
        return model_id
    try:
        activo = servicio.modelo_activo(sesion, "corto_plazo")
    except Exception:  # noqa: BLE001 - sin la tabla (base vieja) rige el registro en disco
        return None
    return activo.model_id if activo else None


def _calcular(ruta: str, instante: datetime, horizonte_min: int, model_id: str | None,
              incluir_segmentos: bool, sesion: Session | None = None) -> dict:
    """El pronóstico del servicio, con lo leído por la lectura incremental y los errores en el formato uniforme de la
    API."""
    pedido = model_id
    try:
        if sesion is not None:
            model_id = modelo_de_la_familia(sesion, model_id)
            with cp.con_sesion(sesion):
                return cp.pronosticar(ruta, instante, horizonte_min, model_id=model_id,
                                      incluir_segmentos=incluir_segmentos)
        return cp.pronosticar(ruta, instante, horizonte_min, model_id=model_id, incluir_segmentos=incluir_segmentos)
    except cp.ModeloCortoPlazoNoEncontrado as exc:
        model_id = pedido
        if model_id is None:
            raise _no_disponible(exc) from exc
        raise ErrorApi(404, "modelo_no_encontrado", str(exc).strip("'\""), {"model_id": model_id}) from exc
    except cp.FueraDeCobertura as exc:
        raise ErrorApi(422, "fuera_de_cobertura", str(exc)) from exc
    except (cp.ErrorCortoPlazo, OSError) as exc:
        raise _no_disponible(exc) from exc


def _no_disponible(exc: Exception) -> ErrorApi:
    return ErrorApi(503, "pronostico_no_disponible", f"Modelo de corto plazo no disponible: {exc}")


def _con_recomendacion(sesion: Session, r: dict, info: dict) -> None:
    try:
        r["recomendacion"] = cp.recomendacion(sesion, r, info)
    except ValueError as exc:
        raise ErrorApi(422, "parametros_invalidos", str(exc)) from exc


def _claves_12_3(r: dict, grupo_id: uuid.UUID | None) -> dict:
    """Las claves del ejemplo de §12.3 (camelCase), además de los campos del pronóstico."""
    rec = r.get("recomendacion")
    resumen = None
    if rec is not None:
        resumen = (RecomendacionResumen(headwayMinutes=rec.get("headway_min"), busesPerHour=rec.get("buses_hora"),
                                        vehiclesRequired=rec.get("vehiculos_requeridos"), viable=True)
                   if rec.get("viable") else RecomendacionResumen(viable=False, reason=rec.get("motivo")))
    return dict(r, grupo_id=grupo_id, predictionId=grupo_id, routeId=r["ruta"], generatedAt=r["generated_at"],
                horizonMinutes=r["horizonte_min"], predictedPassengers=int(round(float(r["pasajeros"]))),
                confidenceInterval=IntervaloConfianza(lower=int(math.floor(float(r["p10"]) + 1e-9)),
                                                      upper=int(math.ceil(float(r["p90"]) - 1e-9))),
                modelVersion=r["model_id"], recommendation=resumen,
                explanation=[f["variable"] for f in r["explicacion"]["factores"]])


@router.post(RUTA, response_model=PronosticoCortoPlazo, status_code=201,
             summary="Pronóstico a 30, 60 o 120 minutos por ruta, sentido y segmento (se guarda)")
def pronosticar(solicitud: SolicitudCortoPlazo, sesion: Session = Depends(obtener_sesion)):
    info = _info_ruta(solicitud.ruta)
    r = _calcular(info["ruta"], solicitud.instante, solicitud.horizonte_min, solicitud.model_id,
                  solicitud.incluir_segmentos, sesion)
    r["generated_at"] = servicio.ahora().astimezone(cp.ZONA).isoformat(timespec="seconds")
    rec_d = None
    if solicitud.incluir_recomendacion:
        try:
            franja, rec_d, entradas, version_u = cp.recomendacion_completa(sesion, r, info)
        except ValueError as exc:
            raise ErrorApi(422, "parametros_invalidos", str(exc)) from exc
        rec_d["franja_prediccion"] = franja
        r["recomendacion"] = cp.resumen_recomendacion(franja, rec_d, version_u)
    grupo = cp.guardar(sesion, r)
    if rec_d is not None:            # la recomendación de §10.2 también queda en recommendation (origen corto_plazo)
        sesion.flush()
        sesion.add(servicio.construir_recomendacion(
            rec_d, ruta=info["ruta"], fecha=franja["fecha"], hora=franja["hora"], demanda_hora=franja["demanda_hora"],
            demanda_p90=franja["p90_hora"], execution_id=None, prediction_id=None, umbrales_version=version_u,
            entradas=dict(entradas, prediccion_corto_plazo={"grupo_id": str(grupo),
                                                            "prediction_id": str(r["prediction_id"])}),
            origen="corto_plazo", prediction_corto_plazo_id=r["prediction_id"]))
    sesion.commit()
    return _claves_12_3(r, grupo)


@router.get(f"{RUTA}/calcular", response_model=PronosticoCortoPlazo,
            summary="Pronóstico a 30, 60 o 120 minutos sin guardarlo (consulta del tablero)")
def calcular(ruta: Annotated[str, Query(description=DESC_CP_RUTA)],
             instante: Annotated[datetime, Query(description=DESC_CP_INSTANTE)],
             horizonte_min: HorizonteObligatorio = 60, model_id: str | None = None,
             incluir_segmentos: bool = True, incluir_recomendacion: bool = True,
             sesion: Session = Depends(obtener_sesion)):
    info = _info_ruta(ruta)
    r = _calcular(info["ruta"], instante, _horizonte(horizonte_min), model_id, incluir_segmentos, sesion)
    r["generated_at"] = servicio.ahora().astimezone(cp.ZONA).isoformat(timespec="seconds")
    if incluir_recomendacion:
        _con_recomendacion(sesion, r, info)
    return _claves_12_3(r, None)


@router.get(f"{RUTA}/dia", response_model=DiaCortoPlazo,
            summary="La curva del día: el pronóstico de cada media hora de 04:00 a 21:00, por ruta y sentido")
def dia(ruta: Annotated[str, Query(description=DESC_CP_RUTA)], fecha: date,
        horizonte_min: HorizonteObligatorio = 60, model_id: str | None = None,
        sesion: Session = Depends(obtener_sesion)):
    info = _info_ruta(ruta)
    pedido = model_id
    try:
        model_id = modelo_de_la_familia(sesion, model_id)
        with cp.con_sesion(sesion):
            return cp.pronosticar_dia(info["ruta"], fecha, _horizonte(horizonte_min), model_id=model_id)
    except cp.ModeloCortoPlazoNoEncontrado as exc:
        model_id = pedido
        if model_id is None:
            raise _no_disponible(exc) from exc
        raise ErrorApi(404, "modelo_no_encontrado", str(exc).strip("'\""), {"model_id": model_id}) from exc
    except cp.FueraDeCobertura as exc:
        raise ErrorApi(422, "fuera_de_cobertura", str(exc)) from exc
    except (cp.ErrorCortoPlazo, OSError) as exc:
        raise _no_disponible(exc) from exc


@router.get(f"{RUTA}/modelo", response_model=ModeloCortoPlazo,
            summary="Versión activa del modelo de corto plazo: artefactos, datos, prueba reservada y cobertura")
def modelo(sesion: Session = Depends(obtener_sesion)):
    try:
        m = cp.cargar(modelo_de_la_familia(sesion, None))
        reg = cp.registro()
        with cp.con_sesion(sesion):
            cob = cp.cobertura()
            excluidas = [c for idr in cp.V.RUTAS for c in cp.serie_completa(idr).excluidas]
            tope = cp.tope_actual()
        return dict(cp.ficha(m), activo=m["model_id"], historial_activacion=reg.get("historial_activacion") or [],
                    cobertura={k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in cob.items()},
                    importancia_global=cp.importancia_global(m),
                    calidad={"regla": "VAL-009", "tope_subidas_bloque_segmento": tope,
                             "celdas_excluidas_del_panel": excluidas})
    except (cp.ErrorCortoPlazo, cp.ModeloCortoPlazoNoEncontrado, OSError) as exc:
        raise _no_disponible(exc) from exc


def _filtrar(ruta, idruta, nivel, sentido, nro_segmento, horizonte_min, desde, hasta, grupo_id, execution_id,
             model_id):
    consulta = select(PrediccionCortoPlazo)
    for columna, valor in ((PrediccionCortoPlazo.ruta, ruta), (PrediccionCortoPlazo.idruta, idruta),
                           (PrediccionCortoPlazo.nivel, nivel), (PrediccionCortoPlazo.sentido, sentido),
                           (PrediccionCortoPlazo.nro_segmento, nro_segmento),
                           (PrediccionCortoPlazo.horizonte_min, horizonte_min),
                           (PrediccionCortoPlazo.grupo_id, grupo_id), (PrediccionCortoPlazo.execution_id, execution_id),
                           (PrediccionCortoPlazo.model_id, model_id)):
        if valor is not None:
            consulta = consulta.where(columna == valor)
    if desde:
        consulta = consulta.where(PrediccionCortoPlazo.fecha >= desde)
    if hasta:
        consulta = consulta.where(PrediccionCortoPlazo.fecha <= hasta)
    return consulta


IdRuta = Annotated[int | None, Query(ge=1, le=2_147_483_647, description="rutas.idruta")]
NroSegmento = Annotated[int | None, Query(ge=1, le=10_000)]


def filtros(ruta: str | None = None, idruta: IdRuta = None, nivel: Nivel | None = None,
            sentido: Literal["ida", "regreso"] | None = None, nro_segmento: NroSegmento = None,
            horizonte_min: HorizonteConsulta = None, desde: date | None = None, hasta: date | None = None,
            grupo_id: uuid.UUID | None = None, execution_id: uuid.UUID | None = None,
            model_id: str | None = None) -> tuple:
    """RF-016: filtros de la consulta de pronósticos de corto plazo guardados."""
    return (ruta, idruta, nivel, sentido, nro_segmento, horizonte_min, desde, hasta, grupo_id, execution_id, model_id)


@router.get(RUTA, response_model=Pagina[PrediccionCortoPlazoSalida],
            summary="Consultar pronósticos de corto plazo guardados por filtros")
def listar(f: tuple = Depends(filtros), pagina: ParametrosPagina = Depends(),
           sesion: Session = Depends(obtener_sesion)):
    return paginar(sesion, _filtrar(*f), PrediccionCortoPlazo, pagina, "-generated_at")


@router.get(f"{RUTA}/export", summary="Exportar pronósticos de corto plazo filtrados (CSV o XLSX)",
            response_class=__import__("fastapi").responses.Response)
def exportar_corto_plazo(formato: Formato = "csv", f: tuple = Depends(filtros), orden: str | None = None,
                         sesion: Session = Depends(obtener_sesion)):
    return exportar(sesion, _filtrar(*f), PrediccionCortoPlazo, formato, "pronosticos_corto_plazo", orden,
                    "-generated_at")
