"""Monitoreo del modelo (§9.4), foto de variables (§11.2) y política de aprendizaje continuo (RF-018, RF-019).

GET /api/v1/monitoring                 filas de monitoreo por ejecución (filtros, paginación y orden)
GET /api/v1/monitoring/export          las mismas filas en CSV o XLSX (RF-017)
GET /api/v1/monitoring/policy          decisión vigente de la política (reentrenar, retadores en sombra)
GET /api/v1/monitoring/feature-snapshots   foto de variables por ejecución o predicción (RNF-011)
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import obtener_sesion
from app.esquemas import Pagina, Salida
from app.modelos_db import FotoVariables, MonitoreoModelo
from app.routers.comun import ErrorApi, ParametrosPagina, exportar, paginar

router = APIRouter(prefix="/monitoring", tags=["monitoreo del modelo"])


class MonitoreoSalida(Salida):   # Salida: §8.1, instantes del JSONB en -05:00
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())
    id: int
    execution_id: uuid.UUID | None = None
    model_id: str
    rol: str
    fecha_corte: date | None = None
    desde: date | None = None
    hasta: date | None = None
    ventana_dias: int
    n_observaciones: int | None = None
    n_predicciones: int | None = None
    predicciones_ventana: int | None = None
    wape_movil: float | None = Field(None, description="WAPE móvil (fracción) de la ventana; alimenta ALT-010")
    mae_movil: float | None = None
    sesgo_pct: float | None = Field(None, description="Sesgo (fracción): suma(p - y) / suma(y)")
    cobertura_p10_p90: float | None = Field(None, description="Cobertura de la banda calibrada (fracción)")
    psi: dict = Field(default_factory=dict)
    psi_max: float | None = None
    psi_variable_max: str | None = None
    alertas_total: int | None = None
    alertas_descartadas: int | None = None
    pct_descartadas: float | None = None
    estado: str
    motivos: list = Field(default_factory=list)
    umbrales_version: int | None = None
    detalle: dict = Field(default_factory=dict)
    creado_en: datetime


class FotoSalida(Salida):
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())
    id: int
    execution_id: uuid.UUID | None = None
    prediction_id: uuid.UUID | None = None
    model_id: str | None = None
    ruta: str
    sentido: str | None = None
    segmento: int | None = None
    horizonte_min: int | None = None
    ventana_inicio: datetime
    ventana_fin: datetime
    fecha: date
    hora: int
    features: dict
    feature_version: str
    data_cutoff: datetime | None = None
    creado_en: datetime


Familia = Annotated[Literal["horario", "corto_plazo"] | None, Query(
    description="horario (el modelo del plan del día siguiente) o corto_plazo (30, 60 y 120 min); sin él, los dos")]


def _filtrar(model_id, rol, estado, desde, hasta, execution_id, familia=None):
    consulta = select(MonitoreoModelo)
    if familia == "corto_plazo":     # el monitoreo del corto plazo lleva detalle.familia (monitoreo_corto_plazo.py)
        consulta = consulta.where(MonitoreoModelo.detalle["familia"].astext == "corto_plazo")
    elif familia == "horario":
        consulta = consulta.where(MonitoreoModelo.detalle["familia"].astext.is_distinct_from("corto_plazo"))
    if model_id:
        consulta = consulta.where(MonitoreoModelo.model_id == model_id)
    if rol:
        consulta = consulta.where(MonitoreoModelo.rol == rol)
    if estado:
        consulta = consulta.where(MonitoreoModelo.estado == estado)
    if desde:
        consulta = consulta.where(MonitoreoModelo.hasta >= desde)
    if hasta:
        consulta = consulta.where(MonitoreoModelo.hasta <= hasta)
    if execution_id:
        consulta = consulta.where(MonitoreoModelo.execution_id == execution_id)
    return consulta


@router.get("", response_model=Pagina[MonitoreoSalida],
            summary="Monitoreo por ejecución: deriva (PSI), error móvil, cobertura, volumen y alertas descartadas")
def listar(model_id: str | None = None, rol: Literal["activo", "sombra"] | None = None,
           estado: Literal["ok", "aviso", "alerta", "sin_datos"] | None = None,
           desde: date | None = Query(None, description="Fin de ventana desde (fecha de datos)"),
           hasta: date | None = Query(None, description="Fin de ventana hasta (fecha de datos)"),
           execution_id: uuid.UUID | None = None, familia: Familia = None, pagina: ParametrosPagina = Depends(),
           sesion: Session = Depends(obtener_sesion)):
    return paginar(sesion, _filtrar(model_id, rol, estado, desde, hasta, execution_id, familia), MonitoreoModelo,
                   pagina, "-creado_en")


@router.get("/export", summary="Exportar el monitoreo filtrado (CSV o XLSX)",
            response_class=__import__("fastapi").responses.Response)
def exportar_monitoreo(formato: Literal["csv", "xlsx"] = "csv", model_id: str | None = None,
                       rol: Literal["activo", "sombra"] | None = None,
                       estado: Literal["ok", "aviso", "alerta", "sin_datos"] | None = None,
                       desde: date | None = None, hasta: date | None = None, execution_id: uuid.UUID | None = None,
                       familia: Familia = None, orden: str | None = None, sesion: Session = Depends(obtener_sesion)):
    return exportar(sesion, _filtrar(model_id, rol, estado, desde, hasta, execution_id, familia), MonitoreoModelo,
                    formato, "monitoreo", orden, "-creado_en")


@router.get("/policy", summary="Política de aprendizaje continuo: ¿reentrenar?, retadores en sombra y umbrales")
def politica_vigente(sesion: Session = Depends(obtener_sesion)) -> dict[str, Any]:
    from app.esquemas import bogota_profundo
    from app.servicios import ejecucion, politica

    version, umbrales = ejecucion.umbrales_vigentes(sesion)
    decision = politica.decidir_reentreno(sesion, umbrales)
    sombra = [{"model_id": c.model_id, "sombra": (c.metricas or {}).get("sombra"), "creado_en": c.creado_en}
              for c in politica.en_sombra(sesion)]
    # §8.1: todo instante (también los guardados en UTC dentro de metricas.sombra) sale en America/Bogota (-05:00)
    return bogota_profundo(ejecucion.json_seguro({"umbrales_version": version, "decision": decision,
                                                  "en_sombra": sombra,
                                                  "umbrales": politica.umbrales_politica(umbrales)}))


@router.get("/feature-snapshots", response_model=Pagina[FotoSalida],
            summary="Foto de variables (§11.2) por ejecución, predicción o ruta, con fecha de corte y versión")
def fotos(execution_id: uuid.UUID | None = None, prediction_id: uuid.UUID | None = None, ruta: str | None = None,
          desde: date | None = None, hasta: date | None = None, pagina: ParametrosPagina = Depends(),
          sesion: Session = Depends(obtener_sesion)):
    if not (execution_id or prediction_id or ruta):
        raise ErrorApi(422, "filtro_requerido", "Indique execution_id, prediction_id o ruta")
    consulta = select(FotoVariables)
    if execution_id:
        consulta = consulta.where(FotoVariables.execution_id == execution_id)
    if prediction_id:
        consulta = consulta.where(FotoVariables.prediction_id == prediction_id)
    if ruta:
        consulta = consulta.where(FotoVariables.ruta == ruta)
    if desde:
        consulta = consulta.where(FotoVariables.fecha >= desde)
    if hasta:
        consulta = consulta.where(FotoVariables.fecha <= hasta)
    return paginar(sesion, consulta, FotoVariables, pagina, "ventana_inicio")
