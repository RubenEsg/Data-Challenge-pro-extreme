"""Esquemas Pydantic de entrada y salida de la API (JSON UTF-8, fechas ISO-8601 con zona)."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")
Horizonte = Literal[30, 60, 120]


class Salida(BaseModel):
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())


class ErrorDetalle(BaseModel):
    codigo: str
    mensaje: str
    detalle: Any = None
    correlation_id: str | None = None


class RespuestaError(BaseModel):
    error: ErrorDetalle


class Pagina(BaseModel, Generic[T]):
    total: int
    limite: int
    desplazamiento: int
    items: list[T]


# ---------------------------------------------------------------- ejecuciones
class SolicitudEjecucion(BaseModel):
    hasta: date | None = Field(None, description="Fecha máxima de datos disponibles (simula la llegada diaria)")
    instante: datetime | None = Field(None, description="Instante de referencia de la predicción; por defecto, "
                                                        "el día siguiente al corte de datos a las 06:00")
    rutas: list[str] | None = Field(None, description="Rutas a procesar; por defecto todas las del catálogo")
    horizontes: list[Horizonte] = Field(default_factory=lambda: [30, 60, 120])
    model_id: str | None = Field(None, description="Modelo a usar; por defecto el activo del registro")
    notificar: bool = True


class EjecucionSalida(Salida):
    execution_id: uuid.UUID
    tipo: str
    estado: str
    etapa: str | None = None
    progreso: float
    intentos: int
    marca_agua_anterior: datetime | None = None
    marca_agua_nueva: datetime | None = None
    data_cutoff: datetime | None = None
    filas_leidas: int | None = None
    filas_validas: int | None = None
    model_id: str | None = None
    feature_version: str | None = None
    umbrales_version: int | None = None
    parametros: dict = Field(default_factory=dict)
    metricas: dict = Field(default_factory=dict)
    correlation_id: str | None = None
    mensaje: str | None = None
    creado_en: datetime
    iniciado_en: datetime | None = None
    terminado_en: datetime | None = None
    actualizado_en: datetime


class ErrorCalidadSalida(Salida):
    id: int
    execution_id: uuid.UUID
    lote: str
    fila: int | None = None
    campo: str | None = None
    codigo: str
    dimension: str
    detalle: str | None = None
    creado_en: datetime


class EjecucionDetalle(EjecucionSalida):
    errores_por_dimension: dict[str, int] = Field(default_factory=dict)
    errores_muestra: list[ErrorCalidadSalida] = Field(default_factory=list)
    predicciones: int = 0
    recomendaciones: int = 0
    alertas: int = 0


# ---------------------------------------------------------------- predicciones
class SolicitudPrediccion(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    ruta: str
    instante: datetime
    horizonte_min: Horizonte = 60
    model_id: str | None = None
    incluir_recomendacion: bool = True


class RecomendacionSalida(Salida):
    recommendation_id: uuid.UUID
    execution_id: uuid.UUID | None = None
    prediction_id: uuid.UUID | None = None
    ruta: str
    fecha: date
    hora: int
    demanda_hora: float | None = None
    demanda_p90: float | None = None
    buses_hora: int | None = None
    headway_min: float | None = None
    vehiculos_requeridos: int | None = None
    capacidad_efectiva: float | None = None
    ocupacion_esperada: float | None = None
    viable: bool
    motivo: str | None = None
    frecuencia_actual_min: float | None = None
    diferencia_min: float | None = None
    formula: str | None = None
    umbrales_version: int | None = None
    detalle: dict = Field(default_factory=dict)
    creado_en: datetime


class PrediccionSalida(Salida):
    prediction_id: uuid.UUID
    execution_id: uuid.UUID | None = None
    ruta: str
    instante: datetime
    horizonte_min: int
    objetivo: datetime
    fecha: date
    hora: int
    pasajeros: float
    p10: float | None = None
    p90: float | None = None
    model_id: str
    feature_version: str | None = None
    data_cutoff: datetime | None = None
    generated_at: datetime
    latencia_ms: float | None = None
    explicacion: list = Field(default_factory=list)
    variables: dict = Field(default_factory=dict)
    creado_en: datetime


class PrediccionRespuesta(PrediccionSalida):
    recomendacion: RecomendacionSalida | None = None


class SolicitudRecomendacion(BaseModel):
    ruta: str
    hora: int = Field(..., ge=0, le=23)
    demanda_hora: float = Field(..., ge=0)
    demanda_p90: float | None = Field(None, ge=0)
    fecha: date | None = None
    capacidad: int | None = Field(None, gt=0)
    ocupacion_objetivo: float | None = Field(None, gt=0, le=1)
    tiempo_ciclo_min: float | None = Field(None, gt=0)
    flota_disponible: int | None = Field(None, ge=0)
    headway_min: float | None = Field(None, gt=0)
    headway_max: float | None = Field(None, gt=0)
    frecuencia_actual_min: float | None = Field(None, gt=0)
    prediction_id: uuid.UUID | None = None


# ---------------------------------------------------------------- alertas
class AlertaSalida(Salida):
    alert_id: uuid.UUID
    codigo: str
    execution_id: uuid.UUID | None = None
    empresa: str | None = None
    ruta: str | None = None
    sentido: str | None = None
    viaje: str | None = None
    conductor: str | None = None
    vehiculo: str | None = None
    detectada_en: datetime
    ventana_inicio: datetime | None = None
    ventana_fin: datetime | None = None
    horizonte_min: int | None = None
    severidad: str
    estado: str
    observado: float | None = None
    esperado: float | None = None
    umbral: float | None = None
    puntaje: float | None = None
    explicacion: str | None = None
    variables: dict = Field(default_factory=dict)
    recomendacion: str | None = None
    asignado_a: str | None = None
    comentarios: list = Field(default_factory=list)
    clave_dedup: str
    ocurrencias: int
    ultima_deteccion: datetime | None = None
    creado_en: datetime
    actualizado_en: datetime


class SolicitudEstadoAlerta(BaseModel):
    accion: Literal["reconocer", "asignar", "comentar", "cerrar", "descartar"]
    usuario: str = Field(..., min_length=1)
    comentario: str | None = None
    asignado_a: str | None = None


class HistorialSalida(Salida):
    id: int
    alert_id: uuid.UUID
    accion: str
    estado_anterior: str | None = None
    estado_nuevo: str
    usuario: str
    comentario: str | None = None
    asignado_a: str | None = None
    detalle: dict = Field(default_factory=dict)
    creado_en: datetime


# ---------------------------------------------------------------- modelos
class ModeloSalida(Salida):
    model_id: str
    version: str
    tipo: str
    artefacto: str
    sha256: str
    feature_version: str
    data_cutoff: datetime | None = None
    metricas: dict = Field(default_factory=dict)
    estado: str
    aprobado_por: str | None = None
    activado_en: datetime | None = None
    anterior_model_id: str | None = None
    motivo: str | None = None
    auditoria: list = Field(default_factory=list)
    creado_en: datetime


class SolicitudActivacion(BaseModel):
    aprobado_por: str = Field(..., min_length=1)
    validacion_desde: date | None = None
    validacion_hasta: date | None = None
    motivo: str | None = None


class SolicitudReversion(BaseModel):
    usuario: str = Field(..., min_length=1)
    motivo: str | None = None


class SolicitudEntrenamiento(BaseModel):
    hasta: date
    semilla: int = 42
    solicitado_por: str | None = None


# ---------------------------------------------------------------- umbrales
class UmbralSalida(Salida):
    nombre: str
    valor: Any
    descripcion: str | None = None
    version: int
    vigente: bool
    creado_por: str
    motivo: str | None = None
    creado_en: datetime


class UmbralesVigentes(BaseModel):
    version: int
    valores: dict[str, Any]
    detalle: list[UmbralSalida]


class SolicitudUmbrales(BaseModel):
    valores: dict[str, Any] = Field(..., min_length=1)
    creado_por: str = Field(..., min_length=1)
    motivo: str | None = None
