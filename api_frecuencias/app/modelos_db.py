"""Modelos ORM del esquema ai_frecuencias (la DDL oficial está en alembic/versions/0001)."""
from __future__ import annotations

import re
import struct
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
from sqlalchemy.types import UserDefinedType

from app.config import ESQUEMA

# acción de las claves foráneas opcionales: si se borra la fila referida, la referencia queda en NULL
AL_BORRAR_NULO = "SET NULL"


class Base(DeclarativeBase):
    metadata = MetaData(schema=ESQUEMA)


def _ahora():
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class PuntoGeografico(UserDefinedType):
    """geography(Point,4326) de PostGIS <-> {"type": "Point", "coordinates": [lon, lat]} (GeoJSON).

    Se escribe como EWKT («SRID=4326;POINT(lon lat)»), que psycopg envía sin tipo y PostgreSQL convierte a geography;
    se lee el HEXEWKB que devuelve PostGIS. Sin PostGIS la migración 0003 deja la columna en TEXT con el mismo EWKT.
    """

    cache_ok = True

    def get_col_spec(self, **kw):
        return "geography(Point,4326)"

    def bind_processor(self, dialect):
        def procesar(valor):
            if valor is None or isinstance(valor, str):
                return valor
            if isinstance(valor, dict):
                lon, lat = (valor["coordinates"][:2] if "coordinates" in valor else (valor["lon"], valor["lat"]))
            else:
                lon, lat = valor
            lon, lat = float(lon), float(lat)
            if not (-180 <= lon <= 180 and -90 <= lat <= 90):
                raise ValueError(f"Coordenadas fuera de rango: lon={lon}, lat={lat}")
            return f"SRID=4326;POINT({lon!r} {lat!r})"
        return procesar

    def result_processor(self, dialect, coltype):
        return punto_geojson


def punto_geojson(valor):
    """HEXEWKB (PostGIS) o EWKT/WKT de un punto -> {"type": "Point", "coordinates": [lon, lat]}."""
    if valor is None or isinstance(valor, dict):
        return valor
    texto = str(valor).strip()
    m = re.search(r"POINT\s*\(\s*([-+0-9.eE]+)\s+([-+0-9.eE]+)\s*\)", texto, re.IGNORECASE)
    if m:
        return {"type": "Point", "coordinates": [float(m.group(1)), float(m.group(2))]}
    try:
        b = bytes.fromhex(texto)
        orden = "<" if b[0] == 1 else ">"
        tipo = struct.unpack(orden + "I", b[1:5])[0]
        inicio = 9 if tipo & 0x20000000 else 5
        lon, lat = struct.unpack(orden + "dd", b[inicio:inicio + 16])
    except (ValueError, IndexError, struct.error):
        return None
    return {"type": "Point", "coordinates": [lon, lat]}


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
    # migración 0016: horario (el del plan del día siguiente) o corto_plazo (30, 60 y 120 min); un activo por familia
    familia: Mapped[str] = mapped_column(Text, nullable=False, default="horario", server_default="horario")


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
    # cola de trabajos (migración 0002): reserva con vencimiento, espera de reintento y franja del planificador
    worker_id: Mapped[str | None] = mapped_column(Text)
    lease_hasta: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    disponible_desde: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    programada_para: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # migración 0004: contexto W3C de la traza de quien encoló (RNF-006)
    traceparent: Mapped[str | None] = mapped_column(Text)
    # migración 0009 (RNF-005): ruta del trabajo (NULL = todas), ejecución partida a la que pertenece y, en la madre,
    # cómo se partió
    ruta: Mapped[str | None] = mapped_column(Text)
    padre_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{ESQUEMA}.execution_log.execution_id", ondelete="CASCADE"))
    particion: Mapped[str | None] = mapped_column(Text)


class MarcaAguaRuta(Base):
    """Marca de agua de la lectura incremental por proceso y ruta (migración 0009, RNF-005). ruta = '*' es la
    frontera de las lecturas de todas las rutas del proceso; estado_fuente, las huellas de la ventana de solape."""

    __tablename__ = "marca_agua_ruta"
    proceso: Mapped[str] = mapped_column(Text, primary_key=True)
    ruta: Mapped[str] = mapped_column(Text, primary_key=True)
    marca_agua: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    estado_fuente: Mapped[dict | None] = mapped_column(JSONB)
    # §9.5: el trabajo que movió la marca a este valor; si se borra, la marca se borra con él
    execution_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{ESQUEMA}.execution_log.execution_id", ondelete="CASCADE"))
    origen: Mapped[str] = mapped_column(Text, nullable=False, default="ejecucion")
    actualizado_en: Mapped[datetime] = _ahora()


class IntentoEjecucion(Base):
    """Traza de cada intento reclamado de la cola (migración 0002): quién lo tomó y cómo terminó."""

    __tablename__ = "execution_attempt"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    execution_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{ESQUEMA}.execution_log.execution_id", ondelete="CASCADE"), nullable=False
    )
    intento: Mapped[int] = mapped_column(Integer, nullable=False)
    worker_id: Mapped[str] = mapped_column(Text, nullable=False)
    reclamado_en: Mapped[datetime] = _ahora()
    terminado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resultado: Mapped[str] = mapped_column(Text, nullable=False, default="corriendo")
    detalle: Mapped[str | None] = mapped_column(Text)


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
    # migración 0006: llave del registro (columnas llave), valor observado y si el error bloquea la fila (§6.3)
    llave: Mapped[dict | None] = mapped_column(JSONB)
    valor: Mapped[str | None] = mapped_column(Text)
    bloqueante: Mapped[bool | None] = mapped_column(Boolean)


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
    # migración 0006: dimensiones de §8.3 (app/servicios/dimensiones.py)
    idruta: Mapped[int | None] = mapped_column(Integer)
    idempresa: Mapped[int | None] = mapped_column(Integer)
    idproceso: Mapped[str | None] = mapped_column(Text)
    id_dia_semana: Mapped[int | None] = mapped_column(Integer)
    id_estacionalidad: Mapped[int | None] = mapped_column(Integer)
    # migración 0013 (§6.1, §9.5): bajadas de los viajes válidos (Σ numerobajadas, la definición de pasajeros) y las
    # subidas y bajadas de timbradas_segmentos de la franja con su cobertura (viajes con timbradas)
    bajadas_viajes: Mapped[float | None] = mapped_column(Float)
    subidas: Mapped[float | None] = mapped_column(Float)
    bajadas: Mapped[float | None] = mapped_column(Float)
    viajes_con_timbradas: Mapped[int | None] = mapped_column(Integer)


class MarcaAguaTabla(Base):
    """Marca de agua de la lectura incremental de cada tabla consolidada de Extreme por proceso (migración 0013, §6.1
    «ultima_actualizacion»): timbradas_consolidado, timbradas_segmentos_anio y timbradas_segmentos_consolidado, con las
    huellas de la ventana de solape. La deja el ciclo en la transacción de sus resultados."""

    __tablename__ = "marca_agua_tabla"
    proceso: Mapped[str] = mapped_column(Text, primary_key=True)
    tabla: Mapped[str] = mapped_column(Text, primary_key=True)
    marca_agua: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    estado_fuente: Mapped[dict | None] = mapped_column(JSONB)
    execution_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{ESQUEMA}.execution_log.execution_id", ondelete="CASCADE"))
    filas_leidas: Mapped[int | None] = mapped_column(Integer)
    actualizado_en: Mapped[datetime] = _ahora()


class Prediccion(Base):
    __tablename__ = "prediction"
    prediction_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    execution_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{ESQUEMA}.execution_log.execution_id", ondelete=AL_BORRAR_NULO)
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
    # migración 0004: banda del modelo sin calibrar, ajuste conformal y explicación local (RF-006, RF-015)
    p10_modelo: Mapped[float | None] = mapped_column(Float)
    p90_modelo: Mapped[float | None] = mapped_column(Float)
    ajuste_conformal: Mapped[float | None] = mapped_column(Float)
    explicacion_local: Mapped[dict | None] = mapped_column(JSONB)
    # migración 0006: dimensiones de §8.3 (app/servicios/dimensiones.py)
    idruta: Mapped[int | None] = mapped_column(Integer)
    idempresa: Mapped[int | None] = mapped_column(Integer)
    idproceso: Mapped[str | None] = mapped_column(Text)
    id_dia_semana: Mapped[int | None] = mapped_column(Integer)
    id_estacionalidad: Mapped[int | None] = mapped_column(Integer)


class PrediccionCortoPlazo(Base):
    """migración 0015: pronóstico de corto plazo (30, 60 y 120 min) por ruta, sentido y segmento (RF-005, RF-006)."""
    __tablename__ = "prediction_corto_plazo"
    prediction_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    grupo_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    execution_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{ESQUEMA}.execution_log.execution_id", ondelete=AL_BORRAR_NULO)
    )
    ruta: Mapped[str] = mapped_column(Text, nullable=False)
    idruta: Mapped[int] = mapped_column(Integer, nullable=False)
    nivel: Mapped[str] = mapped_column(Text, nullable=False)
    sentido: Mapped[str | None] = mapped_column(Text)
    nro_segmento: Mapped[int | None] = mapped_column(Integer)
    instante: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    horizonte_min: Mapped[int] = mapped_column(Integer, nullable=False)
    objetivo: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    fecha: Mapped[date] = mapped_column(Date, nullable=False)
    franja: Mapped[str | None] = mapped_column(Text)
    pasajeros: Mapped[float] = mapped_column(Float, nullable=False)
    p10: Mapped[float | None] = mapped_column(Float)
    p90: Mapped[float | None] = mapped_column(Float)
    promedio_dia_hora: Mapped[float | None] = mapped_column(Float)
    ultima_semana: Mapped[float | None] = mapped_column(Float)
    model_id: Mapped[str] = mapped_column(Text, nullable=False)
    feature_version: Mapped[str] = mapped_column(Text, nullable=False)
    data_cutoff: Mapped[date | None] = mapped_column(Date)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    latencia_ms: Mapped[float | None] = mapped_column(Float)
    explicacion: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    variables: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    recomendacion: Mapped[dict | None] = mapped_column(JSONB)
    creado_en: Mapped[datetime] = _ahora()
    # migración 0016: dimensiones de §8.3 y el id_segmento de rutas_segmentos
    idempresa: Mapped[int | None] = mapped_column(Integer)
    idproceso: Mapped[str | None] = mapped_column(Text)
    id_dia_semana: Mapped[int | None] = mapped_column(Integer)
    id_estacionalidad: Mapped[int | None] = mapped_column(Integer)
    id_segmento: Mapped[int | None] = mapped_column(BigInteger)


class Subidas15Min(Base):
    """migración 0016: subidas por ruta, día, bloque de 15 minutos y segmento que leyó el ciclo (corto plazo)."""
    __tablename__ = "subidas_15min"
    idruta: Mapped[int] = mapped_column(Integer, primary_key=True)
    fecha: Mapped[date] = mapped_column(Date, primary_key=True)
    bloque: Mapped[int] = mapped_column(Integer, primary_key=True)
    nro_segmento: Mapped[int] = mapped_column(Integer, primary_key=True)
    subidas: Mapped[float] = mapped_column(Float, nullable=False)


class Salidas15Min(Base):
    """migración 0016: viajes que iniciaron en cada bloque de 15 minutos (la oferta ya observada)."""
    __tablename__ = "salidas_15min"
    idruta: Mapped[int] = mapped_column(Integer, primary_key=True)
    fecha: Mapped[date] = mapped_column(Date, primary_key=True)
    bloque: Mapped[int] = mapped_column(Integer, primary_key=True)
    salidas: Mapped[float] = mapped_column(Float, nullable=False)


class Lectura15Min(Base):
    """migración 0016: por ruta y día, hasta qué instante se leyó, de dónde, en qué ejecución y qué se excluyó."""
    __tablename__ = "lectura_15min"
    idruta: Mapped[int] = mapped_column(Integer, primary_key=True)
    fecha: Mapped[date] = mapped_column(Date, primary_key=True)
    hasta: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    fuente: Mapped[str] = mapped_column(Text, nullable=False)
    execution_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{ESQUEMA}.execution_log.execution_id", ondelete=AL_BORRAR_NULO))
    celdas: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    subidas: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    excluidas: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    leido_en: Mapped[datetime] = _ahora()


class Recomendacion(Base):
    __tablename__ = "recommendation"
    recommendation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    execution_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{ESQUEMA}.execution_log.execution_id", ondelete=AL_BORRAR_NULO)
    )
    prediction_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{ESQUEMA}.prediction.prediction_id", ondelete=AL_BORRAR_NULO)
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
    # migración 0006: franja (§10.2, de una predicción) o plan_dia (plan del día siguiente que persiste el ciclo)
    origen: Mapped[str] = mapped_column(Text, nullable=False, default="franja", server_default="franja")
    # migración 0016: origen 'corto_plazo' -> la fila de la ruta del pronóstico de corto plazo
    prediction_corto_plazo_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{ESQUEMA}.prediction_corto_plazo.prediction_id", ondelete=AL_BORRAR_NULO))
    # dimensiones de §8.3 (app/servicios/dimensiones.py)
    idruta: Mapped[int | None] = mapped_column(Integer)
    idempresa: Mapped[int | None] = mapped_column(Integer)
    idproceso: Mapped[str | None] = mapped_column(Text)
    id_dia_semana: Mapped[int | None] = mapped_column(Integer)
    id_estacionalidad: Mapped[int | None] = mapped_column(Integer)
    # migración 0010 (§6.1 y §6.2): headway vigente de rutas.frecuenciadespachos y recomendado − vigente
    frecuenciadespachos_min: Mapped[float | None] = mapped_column(Float)
    diferencia_frecuenciadespachos_min: Mapped[float | None] = mapped_column(Float)


class Alerta(Base):
    __tablename__ = "alert"
    alert_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    codigo: Mapped[str] = mapped_column(Text, nullable=False)
    execution_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{ESQUEMA}.execution_log.execution_id", ondelete=AL_BORRAR_NULO)
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
    # migración 0003: estructura completa de §5.3 y §9.4 (tendencia), ubicación §8.1 y seudónimo §18
    origen: Mapped[str] = mapped_column(Text, nullable=False, default="pronostico")
    tendencia: Mapped[str | None] = mapped_column(Text)
    tendencia_pendiente: Mapped[float | None] = mapped_column(Float)
    serie_reciente: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    probabilidad: Mapped[float | None] = mapped_column(Float)
    metodo_puntaje: Mapped[str | None] = mapped_column(Text)
    variables_influyentes: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    ubicacion: Mapped[dict | None] = mapped_column(PuntoGeografico())
    # migración 0006: dimensiones de §8.3 (app/servicios/dimensiones.py)
    idruta: Mapped[int | None] = mapped_column(Integer)
    idempresa: Mapped[int | None] = mapped_column(Integer)
    idproceso: Mapped[str | None] = mapped_column(Text)
    id_dia_semana: Mapped[int | None] = mapped_column(Integer)
    id_estacionalidad: Mapped[int | None] = mapped_column(Integer)


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
    # migración 0006: validación del área operativa (§5.1); nulo = versión propuesta
    aprobado_por: Mapped[str | None] = mapped_column(Text)
    aprobado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Notificacion(Base):
    __tablename__ = "notification_log"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    execution_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{ESQUEMA}.execution_log.execution_id", ondelete=AL_BORRAR_NULO)
    )
    alert_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{ESQUEMA}.alert.alert_id", ondelete=AL_BORRAR_NULO)
    )
    canal: Mapped[str] = mapped_column(Text, nullable=False)
    destinatario: Mapped[str | None] = mapped_column(Text)
    asunto: Mapped[str | None] = mapped_column(Text)
    mensaje: Mapped[str | None] = mapped_column(Text)
    estado: Mapped[str] = mapped_column(Text, nullable=False, default="simulado")
    simulado: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    detalle: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    creado_en: Mapped[datetime] = _ahora()


# ---------------------------------------------------------------- migración 0004
class MonitoreoModelo(Base):
    """§9.4: deriva, error móvil, cobertura, volumen y alertas descartadas por ejecución y modelo (activo o sombra)."""

    __tablename__ = "model_monitoring"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    execution_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{ESQUEMA}.execution_log.execution_id", ondelete="CASCADE"))
    model_id: Mapped[str] = mapped_column(Text, nullable=False)
    rol: Mapped[str] = mapped_column(Text, nullable=False, default="activo")
    fecha_corte: Mapped[date | None] = mapped_column(Date)
    desde: Mapped[date | None] = mapped_column(Date)
    hasta: Mapped[date | None] = mapped_column(Date)
    ventana_dias: Mapped[int] = mapped_column(Integer, nullable=False)
    n_observaciones: Mapped[int | None] = mapped_column(Integer)
    n_predicciones: Mapped[int | None] = mapped_column(Integer)
    predicciones_ventana: Mapped[int | None] = mapped_column(Integer)
    wape_movil: Mapped[float | None] = mapped_column(Float)
    mae_movil: Mapped[float | None] = mapped_column(Float)
    sesgo_pct: Mapped[float | None] = mapped_column(Float)
    cobertura_p10_p90: Mapped[float | None] = mapped_column(Float)
    psi: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    psi_max: Mapped[float | None] = mapped_column(Float)
    psi_variable_max: Mapped[str | None] = mapped_column(Text)
    alertas_total: Mapped[int | None] = mapped_column(Integer)
    alertas_descartadas: Mapped[int | None] = mapped_column(Integer)
    pct_descartadas: Mapped[float | None] = mapped_column(Float)
    estado: Mapped[str] = mapped_column(Text, nullable=False)
    motivos: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    umbrales_version: Mapped[int | None] = mapped_column(Integer)
    detalle: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    creado_en: Mapped[datetime] = _ahora()


class FotoVariables(Base):
    """§11.2 feature snapshot: vector exacto de variables por predicción y hora (tabla particionada por mes)."""

    __tablename__ = "feature_snapshot"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ventana_inicio: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    execution_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{ESQUEMA}.execution_log.execution_id", ondelete="CASCADE"))
    prediction_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{ESQUEMA}.prediction.prediction_id", ondelete="CASCADE"))
    model_id: Mapped[str | None] = mapped_column(Text)
    ruta: Mapped[str] = mapped_column(Text, nullable=False)
    sentido: Mapped[str | None] = mapped_column(Text)
    segmento: Mapped[int | None] = mapped_column(Integer)
    horizonte_min: Mapped[int | None] = mapped_column(Integer)
    ventana_fin: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    fecha: Mapped[date] = mapped_column(Date, nullable=False)
    hora: Mapped[int] = mapped_column(Integer, nullable=False)
    features: Mapped[dict] = mapped_column(JSONB, nullable=False)
    feature_version: Mapped[str] = mapped_column(Text, nullable=False)
    data_cutoff: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    creado_en: Mapped[datetime] = _ahora()
    # migración 0006: dimensiones de §8.3 (app/servicios/dimensiones.py)
    idruta: Mapped[int | None] = mapped_column(Integer)
    idempresa: Mapped[int | None] = mapped_column(Integer)
    idproceso: Mapped[str | None] = mapped_column(Text)
    id_dia_semana: Mapped[int | None] = mapped_column(Integer)
    id_estacionalidad: Mapped[int | None] = mapped_column(Integer)


# ---------------------------------------------------------------- migración 0006
class RespuestaReto(Base):
    """§20: foto persistida de la respuesta a la pregunta del reto por fecha y ruta (GET /respuesta solo la lee)."""

    __tablename__ = "respuesta_reto"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    fecha: Mapped[date] = mapped_column(Date, nullable=False)
    ruta: Mapped[str] = mapped_column(Text, nullable=False)
    idruta: Mapped[int | None] = mapped_column(Integer)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    model_id: Mapped[str | None] = mapped_column(Text)
    calibracion_version: Mapped[str | None] = mapped_column(Text)
    umbrales_version: Mapped[int | None] = mapped_column(Integer)
    execution_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{ESQUEMA}.execution_log.execution_id", ondelete=AL_BORRAR_NULO))
    fuente_pronostico: Mapped[str | None] = mapped_column(Text)
    generado_en: Mapped[datetime] = _ahora()


# ---------------------------------------------------------------- migración 0011
class OcupacionSegmento(Base):
    """§10.1 ocupación actual por segmento: carga a bordo de los viajes de una franja (ruta, fecha, hora de salida) al
    salir de cada segmento, derivada de sus subidas y bajadas (app/servicios/ocupacion.py; hallazgo H9). critico marca
    el segmento con la mayor carga media de la franja."""

    __tablename__ = "ocupacion_segmento"
    ruta: Mapped[str] = mapped_column(Text, primary_key=True)
    fecha: Mapped[date] = mapped_column(Date, primary_key=True)
    hora: Mapped[int] = mapped_column(Integer, primary_key=True)
    nro_segmento: Mapped[int] = mapped_column(Integer, primary_key=True)
    idruta: Mapped[int] = mapped_column(Integer, nullable=False)
    id_segmento: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sentido: Mapped[str | None] = mapped_column(Text)
    id_dia_semana: Mapped[int | None] = mapped_column(Integer)
    id_estacionalidad: Mapped[int | None] = mapped_column(BigInteger)
    nro_viajes: Mapped[int] = mapped_column(Integer, nullable=False)
    carga_media: Mapped[float] = mapped_column(Float, nullable=False)
    carga_max: Mapped[float] = mapped_column(Float, nullable=False)
    capacidad: Mapped[float] = mapped_column(Float, nullable=False)
    ocupacion_media: Mapped[float] = mapped_column(Float, nullable=False)
    ocupacion_max: Mapped[float] = mapped_column(Float, nullable=False)
    id_viaje_max: Mapped[int | None] = mapped_column(BigInteger)
    critico: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    execution_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    actualizado_en: Mapped[datetime] = _ahora()


# ---------------------------------------------------------------- migración 0012
class RegistroRetencion(Base):
    """§18 retención: bitácora de la tarea de retención (app/servicios/retencion.py), una fila por acción de cada
    corrida, simulada o aplicada. execution_id sin llave foránea: la bitácora sobrevive a la retención de
    execution_log."""

    __tablename__ = "retencion_registro"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    execution_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    simulado: Mapped[bool] = mapped_column(Boolean, nullable=False)
    grupo: Mapped[str] = mapped_column(Text, nullable=False)
    objeto: Mapped[str] = mapped_column(Text, nullable=False)
    accion: Mapped[str] = mapped_column(Text, nullable=False)
    corte: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    filas: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    bytes: Mapped[int | None] = mapped_column(BigInteger)
    umbrales_version: Mapped[int | None] = mapped_column(Integer)
    detalle: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    creado_en: Mapped[datetime] = _ahora()
