"""Modelos ORM del esquema ai_frecuencias (la DDL oficial está en alembic/versions/0001)."""
from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    MetaData,
    Numeric,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.config import ESQUEMA


class Base(DeclarativeBase):
    metadata = MetaData(schema=ESQUEMA)


def _ahora():
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class RegistroModelo(Base):
    __tablename__ = "model_registry"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    model_id: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    version: Mapped[str] = mapped_column(Text, nullable=False)
    tipo: Mapped[str] = mapped_column(Text, nullable=False)
    artefacto: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(Text, nullable=False)
    feature_version: Mapped[str] = mapped_column(Text, nullable=False)
    data_cutoff: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metricas: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    estado: Mapped[str] = mapped_column(Text, nullable=False, default="candidato")
    aprobado_por: Mapped[str | None] = mapped_column(Text)
    activado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    anterior_model_id: Mapped[str | None] = mapped_column(Text)
    motivo: Mapped[str | None] = mapped_column(Text)
    auditoria: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    execution_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    creado_en: Mapped[datetime] = _ahora()


class Ejecucion(Base):
    __tablename__ = "execution_log"
    execution_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tipo: Mapped[str] = mapped_column(Text, nullable=False, default="frecuencia")
    estado: Mapped[str] = mapped_column(Text, nullable=False, default="en_cola")
    etapa: Mapped[str | None] = mapped_column(Text)
    progreso: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False, default=0)
    intentos: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    marca_agua_anterior: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    marca_agua_nueva: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    data_cutoff: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    filas_leidas: Mapped[int | None] = mapped_column(Integer)
    filas_validas: Mapped[int | None] = mapped_column(Integer)
    model_id: Mapped[str | None] = mapped_column(Text)
    feature_version: Mapped[str | None] = mapped_column(Text)
    umbrales_version: Mapped[int | None] = mapped_column(Integer)
    parametros: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    metricas: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    correlation_id: Mapped[str | None] = mapped_column(Text)
    mensaje: Mapped[str | None] = mapped_column(Text)
    creado_en: Mapped[datetime] = _ahora()
    iniciado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    terminado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    actualizado_en: Mapped[datetime] = _ahora()


class ErrorCalidad(Base):
    __tablename__ = "data_quality_error"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    execution_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{ESQUEMA}.execution_log.execution_id", ondelete="CASCADE")
    )
    lote: Mapped[str] = mapped_column(Text, nullable=False)
    fila: Mapped[int | None] = mapped_column(BigInteger)
    campo: Mapped[str | None] = mapped_column(Text)
    codigo: Mapped[str] = mapped_column(Text, nullable=False)
    dimension: Mapped[str] = mapped_column(Text, nullable=False)
    detalle: Mapped[str | None] = mapped_column(Text)
    creado_en: Mapped[datetime] = _ahora()


class DemandaObservada(Base):
    __tablename__ = "demanda_observada"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ruta: Mapped[str] = mapped_column(Text, nullable=False)
    fecha: Mapped[date] = mapped_column(Date, nullable=False)
    hora: Mapped[int] = mapped_column(Integer, nullable=False)
    pasajeros: Mapped[float | None] = mapped_column(Float)
    salidas: Mapped[int | None] = mapped_column(Integer)
    ultima_actualizacion: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    execution_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    cargado_en: Mapped[datetime] = _ahora()


class Prediccion(Base):
    __tablename__ = "prediction"
    prediction_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    execution_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{ESQUEMA}.execution_log.execution_id", ondelete="SET NULL")
    )
    ruta: Mapped[str] = mapped_column(Text, nullable=False)
    instante: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    horizonte_min: Mapped[int] = mapped_column(Integer, nullable=False)
    objetivo: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    fecha: Mapped[date] = mapped_column(Date, nullable=False)
    hora: Mapped[int] = mapped_column(Integer, nullable=False)
    pasajeros: Mapped[float] = mapped_column(Float, nullable=False)
    p10: Mapped[float | None] = mapped_column(Float)
    p90: Mapped[float | None] = mapped_column(Float)
    model_id: Mapped[str] = mapped_column(Text, nullable=False)
    feature_version: Mapped[str | None] = mapped_column(Text)
    data_cutoff: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    latencia_ms: Mapped[float | None] = mapped_column(Float)
    explicacion: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    variables: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    creado_en: Mapped[datetime] = _ahora()


class Recomendacion(Base):
    __tablename__ = "recommendation"
    recommendation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    execution_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{ESQUEMA}.execution_log.execution_id", ondelete="SET NULL")
    )
    prediction_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{ESQUEMA}.prediction.prediction_id", ondelete="SET NULL")
    )
    ruta: Mapped[str] = mapped_column(Text, nullable=False)
    fecha: Mapped[date] = mapped_column(Date, nullable=False)
    hora: Mapped[int] = mapped_column(Integer, nullable=False)
    demanda_hora: Mapped[float | None] = mapped_column(Float)
    demanda_p90: Mapped[float | None] = mapped_column(Float)
    buses_hora: Mapped[int | None] = mapped_column(Integer)
    headway_min: Mapped[float | None] = mapped_column(Float)
    vehiculos_requeridos: Mapped[int | None] = mapped_column(Integer)
    capacidad_efectiva: Mapped[float | None] = mapped_column(Float)
    ocupacion_esperada: Mapped[float | None] = mapped_column(Float)
    viable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    motivo: Mapped[str | None] = mapped_column(Text)
    frecuencia_actual_min: Mapped[float | None] = mapped_column(Float)
    diferencia_min: Mapped[float | None] = mapped_column(Float)
    formula: Mapped[str | None] = mapped_column(Text)
    umbrales_version: Mapped[int | None] = mapped_column(Integer)
    detalle: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    creado_en: Mapped[datetime] = _ahora()


class Alerta(Base):
    __tablename__ = "alert"
    alert_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    codigo: Mapped[str] = mapped_column(Text, nullable=False)
    execution_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{ESQUEMA}.execution_log.execution_id", ondelete="SET NULL")
    )
    empresa: Mapped[str | None] = mapped_column(Text)
    ruta: Mapped[str | None] = mapped_column(Text)
    sentido: Mapped[str | None] = mapped_column(Text)
    viaje: Mapped[str | None] = mapped_column(Text)
    conductor: Mapped[str | None] = mapped_column(Text)
    vehiculo: Mapped[str | None] = mapped_column(Text)
    detectada_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ventana_inicio: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ventana_fin: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    horizonte_min: Mapped[int | None] = mapped_column(Integer)
    severidad: Mapped[str] = mapped_column(Text, nullable=False)
    estado: Mapped[str] = mapped_column(Text, nullable=False, default="nueva")
    observado: Mapped[float | None] = mapped_column(Float)
    esperado: Mapped[float | None] = mapped_column(Float)
    umbral: Mapped[float | None] = mapped_column(Float)
    puntaje: Mapped[float | None] = mapped_column(Float)
    explicacion: Mapped[str | None] = mapped_column(Text)
    variables: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    recomendacion: Mapped[str | None] = mapped_column(Text)
    asignado_a: Mapped[str | None] = mapped_column(Text)
    comentarios: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    clave_dedup: Mapped[str] = mapped_column(Text, nullable=False)
    ocurrencias: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    ultima_deteccion: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    creado_en: Mapped[datetime] = _ahora()
    actualizado_en: Mapped[datetime] = _ahora()


class HistorialAlerta(Base):
    __tablename__ = "alert_history"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    alert_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{ESQUEMA}.alert.alert_id", ondelete="CASCADE"), nullable=False
    )
    accion: Mapped[str] = mapped_column(Text, nullable=False)
    estado_anterior: Mapped[str | None] = mapped_column(Text)
    estado_nuevo: Mapped[str] = mapped_column(Text, nullable=False)
    usuario: Mapped[str] = mapped_column(Text, nullable=False)
    comentario: Mapped[str | None] = mapped_column(Text)
    asignado_a: Mapped[str | None] = mapped_column(Text)
    detalle: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    creado_en: Mapped[datetime] = _ahora()


class Umbral(Base):
    __tablename__ = "threshold_config"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    nombre: Mapped[str] = mapped_column(Text, nullable=False)
    valor: Mapped[object] = mapped_column(JSONB, nullable=False)
    descripcion: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    vigente: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    creado_por: Mapped[str] = mapped_column(Text, nullable=False)
    motivo: Mapped[str | None] = mapped_column(Text)
    creado_en: Mapped[datetime] = _ahora()


class Notificacion(Base):
    __tablename__ = "notification_log"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    execution_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{ESQUEMA}.execution_log.execution_id", ondelete="SET NULL")
    )
    alert_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{ESQUEMA}.alert.alert_id", ondelete="SET NULL")
    )
    canal: Mapped[str] = mapped_column(Text, nullable=False)
    destinatario: Mapped[str | None] = mapped_column(Text)
    asunto: Mapped[str | None] = mapped_column(Text)
    mensaje: Mapped[str | None] = mapped_column(Text)
    estado: Mapped[str] = mapped_column(Text, nullable=False, default="simulado")
    simulado: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    detalle: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    creado_en: Mapped[datetime] = _ahora()
