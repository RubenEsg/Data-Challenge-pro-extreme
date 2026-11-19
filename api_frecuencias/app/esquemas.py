"""Esquemas Pydantic de entrada y salida de la API (JSON UTF-8, fechas ISO-8601 con zona)."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Generic, Literal, TypeVar
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_serializer

T = TypeVar("T")
Horizonte = Literal[30, 60, 120]
# los campos de auditoría del cuerpo son opcionales: con autenticación manda el principal (RNF-011)
AUDITORIA_OPCIONAL = "Opcional: con autenticación la auditoría registra SIEMPRE al usuario de la clave (RNF-011)"
# §8.3: dimensiones que guardan las tablas de resultados (app/servicios/dimensiones.py)
DESC_IDRUTA = "§8.3 rutas.idruta de Extreme"
DESC_IDEMPRESA = "§8.3 rutas.idempresa (nulo si Extreme no lo trae)"
DESC_IDPROCESO = "§8.3 llave de Procesos (rutas.proceso, texto en Extreme)"
DESC_DIA_SEMANA = "§8.3 día ISO 1 = lunes … 7 = domingo de la fecha local"
DESC_ESTACIONALIDAD = "§8.3 estacionalidades_anio vigente para el proceso (nula si no hay)"
# §6.1 y §6.2: el headway vigente que fija la tabla rutas de Extreme, además del intervalo programado observado
DESC_FRECUENCIADESPACHOS = ("§6.2 headway vigente tomado de la frecuencia de despachos: rutas.frecuenciadespachos de "
                            "la ruta, en minutos (§6.1). La comparación con el intervalo programado observado sigue en "
                            "frecuencia_actual_min y diferencia_min")
DESC_DIFERENCIA_FRECUENCIADESPACHOS = ("§6.2 headway recomendado − headway vigente de rutas.frecuenciadespachos, en "
                                       "minutos (negativo: despachar más seguido); nula si no hay headway recomendado "
                                       "(no viable o sin salidas)")
DESC_CAMBIO_FRECUENCIADESPACHOS = ("Sentido del cambio frente a rutas.frecuenciadespachos: reducir_intervalo, "
                                   "ampliar_intervalo o mantener (±0,05 min)")
DESC_OCUPACION_HISTORICA = ("§10.1 ocupación histórica: el segmento crítico de la ruta (mayor carga media a bordo) en "
                            "el día de la semana de operación y la hora, con su sentido aproximado, su carga media, "
                            "P50, P90 y máxima y su ocupación con los puestos de la recomendación (subidas y bajadas "
                            "por segmento de cada viaje, 2023-01-01 a 2023-02-27; texto = la frase de la explicación)")
DESC_RESTRICCION_REACTIVA = ("§10.1 ocupación actual, solo en la hora en que actúa: la ocupación observada del "
                             "segmento crítico en la última hora cerrada superó el umbral crítico y estas salidas no "
                             "bajan de las que exige esa carga (piso del MILP; activa = el piso manda). Es una "
                             "restricción de seguridad, no un re-pronóstico")
DESC_OCUPACION_ACTUAL = ("§10.1 ocupación actual: la restricción reactiva que evaluó el ciclo con la ocupación "
                         "observada por segmento (si aplicó, en qué hora y con qué salidas mínimas, o por qué no); "
                         "nula si el plan se calculó sin ocupación observada")


class Salida(BaseModel):
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())

    @model_serializer(mode="wrap")
    def _instantes_en_bogota(self, siguiente):
        """§8.1: todo instante de la respuesta (columnas y JSONB anidados: comentarios, variables, métricas,
        detalle) sale en America/Bogota (-05:00), aunque se haya guardado o calculado en UTC."""
        return bogota_profundo(siguiente(self))


ZONA_PRESENTACION = ZoneInfo("America/Bogota")
# claves JSONB que guardan horas locales de Bogotá; en filas antiguas venían sin zona («2025-10-15 14:00»)
CLAVES_HORA_LOCAL = frozenset({"horas_faltantes"})


def bogota_profundo(valor: Any, local: bool = False) -> Any:
    """Recorre dict/list y presenta cada instante (datetime o texto ISO con zona) en America/Bogota. Con local=True,
    un instante sin zona se interpreta como hora de Bogotá. Fechas, horas y prosa quedan iguales."""
    if isinstance(valor, dict):
        return {k: bogota_profundo(v, local or k in CLAVES_HORA_LOCAL) for k, v in valor.items()}
    if isinstance(valor, list):
        return [bogota_profundo(v, local) for v in valor]
    if isinstance(valor, datetime):
        return _datetime_bogota(valor, local)
    if not _parece_instante(valor):
        return valor
    return _texto_local_bogota(valor) if local else _instante_bogota(valor)


def _parece_instante(valor: Any) -> bool:
    """Solo un texto con forma «AAAA-MM-DDTHH:MM…» puede ser un instante: el resto se devuelve sin intentar leerlo."""
    return isinstance(valor, str) and len(valor) >= 16 and valor[4] == "-" and valor[10] in "T "


def _datetime_bogota(valor: datetime, local: bool) -> datetime:
    """datetime con zona -> el mismo instante en Bogotá; sin zona, se interpreta como hora de Bogotá si local=True."""
    if valor.tzinfo is None:
        return valor.replace(tzinfo=ZONA_PRESENTACION) if local else valor
    return valor.astimezone(ZONA_PRESENTACION)


def _texto_local_bogota(valor: str) -> str:
    """Texto ISO de una clave de hora local: sin zona es hora de Bogotá; con zona se lleva a Bogotá."""
    try:
        instante = datetime.fromisoformat(valor)
    except ValueError:
        return valor
    if instante.tzinfo is None:
        return instante.replace(tzinfo=ZONA_PRESENTACION).isoformat()
    return instante.astimezone(ZONA_PRESENTACION).isoformat()


def _instante_bogota(valor: Any) -> Any:
    """Texto ISO con zona -> el mismo instante en America/Bogota; cualquier otro valor queda igual."""
    if not isinstance(valor, str):
        return valor
    try:
        instante = datetime.fromisoformat(valor)
    except ValueError:
        return valor
    return instante.astimezone(ZONA_PRESENTACION).isoformat() if instante.tzinfo else valor


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
    plan_dia: bool = Field(True, description="Al cerrar con datos nuevos, calcular y guardar el plan del día siguiente "
                                             "por ruta y hora (recommendation.origen = plan_dia) y la foto de la "
                                             "respuesta del reto")
    particion: Literal["ninguna", "ruta"] = Field(
        "ninguna", description="RNF-005. «ruta»: la ejecución se parte en un trabajo por ruta (las de `rutas` o, sin "
                               "`rutas`, todas las del catálogo) de la fecha `hasta`; cada trabajo lee solo su ruta "
                               "desde la marca de agua de esa ruta, las réplicas procesan rutas distintas a la vez y "
                               "dos trabajos de la misma ruta nunca corren a la vez. «ninguna»: un solo trabajo de "
                               "todas las rutas (`rutas` limita entonces la predicción, no la lectura)")


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
    # migración 0009 (RNF-005): partición del trabajo
    ruta: str | None = Field(None, description="Ruta del trabajo: la única que lee, procesa y bloquea; null = todas "
                                               "las rutas (ejecución sin partir) o la ejecución madre")
    padre_id: uuid.UUID | None = Field(None, description="Ejecución partida (madre) a la que pertenece este trabajo")
    particion: str | None = Field(None, description="En la ejecución madre, cómo se partió («ruta»); null en los "
                                                    "trabajos y en las ejecuciones sin partir")


class TrabajoEjecucion(Salida):
    """Un trabajo por ruta de una ejecución partida (RNF-005)."""

    execution_id: uuid.UUID
    ruta: str | None = None
    estado: str
    etapa: str | None = None
    progreso: float
    intentos: int
    marca_agua_anterior: datetime | None = None
    marca_agua_nueva: datetime | None = None
    filas_leidas: int | None = None
    filas_validas: int | None = None
    model_id: str | None = None
    mensaje: str | None = None
    creado_en: datetime
    iniciado_en: datetime | None = None
    terminado_en: datetime | None = None


class EjecucionCreada(EjecucionSalida):
    trabajos: list[TrabajoEjecucion] = Field(
        default_factory=list, description="RNF-005: los trabajos por ruta de una ejecución partida (vacío si no se "
                                          "partió). La madre termina cuando terminan todos")


class MarcaAguaSalida(Salida):
    """Marca de agua de la lectura incremental por proceso y ruta (RNF-005, migración 0009)."""

    proceso: str = Field(description="Proceso (operador) que se lee: FUENTE_PROCESO, «*» = todos")
    ruta: str = Field(description="Ruta; «*» es la frontera de las lecturas de todas las rutas del proceso")
    marca_agua: datetime
    execution_id: uuid.UUID | None = Field(None, description="Trabajo que dejó la marca (null si vino de la migración)")
    origen: str = Field(description="ejecucion o migracion_0009 (marca global de antes, sembrada por ruta)")
    huellas: int = Field(0, description="Huellas de la ventana de solape guardadas para la ruta")
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
    # migración 0006: el registro exacto (columnas llave), el valor observado y si bloquea la fila (§6.3, §14.2)
    llave: dict | None = Field(None, description="Columnas llave del registro con error (ruta, fecha, hora o la llave "
                                                 "de 7 columnas del consolidado)")
    valor: str | None = Field(None, description="Valor observado que incumple la regla")
    bloqueante: bool | None = Field(None, description="true: el registro no entra al histórico; false: advertencia")


class EjecucionDetalle(EjecucionCreada):
    """Detalle de una ejecución; en una ejecución partida, los conteos suman los de la madre y sus trabajos."""

    errores_por_dimension: dict[str, int] = Field(default_factory=dict)
    errores_muestra: list[ErrorCalidadSalida] = Field(default_factory=list)
    predicciones: int = 0
    recomendaciones: int = Field(0, description="Recomendaciones de franja (§10.2), una por predicción")
    recomendaciones_plan_dia: int = Field(0, description="Horas del plan del día siguiente guardadas por el ciclo "
                                                         "(recommendation con origen = plan_dia)")
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
    # migración 0006: origen de la fila y dimensiones de §8.3
    origen: str = Field("franja", description="franja (§10.2, ligada a su predicción) o plan_dia (plan del día "
                                              "siguiente que guarda el ciclo, sin predicción)")
    idruta: int | None = Field(None, description=DESC_IDRUTA)
    idempresa: int | None = Field(None, description=DESC_IDEMPRESA)
    idproceso: str | None = Field(None, description=DESC_IDPROCESO)
    id_dia_semana: int | None = Field(None, description=DESC_DIA_SEMANA)
    id_estacionalidad: int | None = Field(None, description=DESC_ESTACIONALIDAD)
    # migración 0010: §6.2 «headway vigente, tomado de la frecuencia de despachos, y su diferencia con la recomendada»
    frecuenciadespachos_min: float | None = Field(None, description=DESC_FRECUENCIADESPACHOS)
    diferencia_frecuenciadespachos_min: float | None = Field(None, description=DESC_DIFERENCIA_FRECUENCIADESPACHOS)


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
    # migración 0004: banda del modelo sin calibrar, ajuste conformal (q) y explicación local SHAP
    p10_modelo: float | None = None
    p90_modelo: float | None = None
    ajuste_conformal: float | None = None
    explicacion_local: dict | None = None
    # migración 0006: dimensiones de §8.3
    idruta: int | None = Field(None, description=DESC_IDRUTA)
    idempresa: int | None = Field(None, description=DESC_IDEMPRESA)
    idproceso: str | None = Field(None, description=DESC_IDPROCESO)
    id_dia_semana: int | None = Field(None, description=DESC_DIA_SEMANA)
    id_estacionalidad: int | None = Field(None, description=DESC_ESTACIONALIDAD)


class IntervaloConfianza(BaseModel):
    """§12.3 confidenceInterval: banda P10-P90 calibrada (lower redondeado hacia abajo, upper hacia arriba)."""
    lower: int | None = None
    upper: int | None = None


class RecomendacionResumen(BaseModel):
    """§12.3 recommendation: la recomendación de §10.2 de la franja. Si no es viable, viable=false con el motivo y las
    cifras en None: la mejor aproximación ejecutable no se presenta como recomendación (va en mejor_aproximacion)."""
    headwayMinutes: float | None = None
    busesPerHour: int | None = None
    vehiclesRequired: int | None = None
    viable: bool | None = None
    reason: str | None = Field(None, description="Motivo de la no viabilidad (§10.3, §18)")


class PrediccionRespuesta(PrediccionSalida):
    recomendacion: RecomendacionSalida | None = None
    # §12.3 «Ejemplo de respuesta de predicción»: las mismas claves del ejemplo, además de los campos anteriores
    predictionId: uuid.UUID | None = None
    routeId: str | None = None
    generatedAt: str | None = Field(None, description="ISO-8601 con la zona de Bogotá (-05:00)")
    horizonMinutes: int | None = None
    predictedPassengers: int | None = None
    confidenceInterval: IntervaloConfianza | None = None
    modelVersion: str | None = None
    recommendation: RecomendacionResumen | None = None
    explanation: list[str] = Field(default_factory=list, description="Variables principales del pronóstico")


# ---------------------------------------------------------------- pronóstico de corto plazo (30, 60 y 120 minutos)
DESC_CP_INSTANTE = ("Instante t del pronóstico (hora de Bogotá si no trae zona). Se redondea hacia abajo a la media "
                    "hora; cubre de 04:00 a 21:00, las medias horas en que se eligió y se midió el modelo")
DESC_CP_RUTA = "Ruta del catálogo (SILENCIO, CRA 54 o CL 72) o su idruta"


class SolicitudCortoPlazo(BaseModel):
    """RF-005: las subidas de la ventana [t, t + horizonte) por ruta, sentido y segmento, con lo observado hasta t."""
    model_config = ConfigDict(protected_namespaces=())
    ruta: str = Field(..., description=DESC_CP_RUTA)
    instante: datetime = Field(..., description=DESC_CP_INSTANTE)
    horizonte_min: Horizonte = 60
    model_id: str | None = Field(None, description="Versión registrada del modelo de corto plazo (la activa si falta)")
    incluir_segmentos: bool = Field(True, description="Incluir el pronóstico de cada segmento de 500 m")
    incluir_recomendacion: bool = Field(True, description="Incluir la recomendación de §10.2 con este pronóstico")


class CeldaCortoPlazo(BaseModel):
    pasajeros: float | None = Field(None, description="Subidas pronosticadas en la ventana (P50 del modelo de Poisson)")
    p10: float | None = Field(None, description="Límite inferior de la banda P10-P90 (conformal, ajustada en la "
                                                "validación)")
    p90: float | None = Field(None, description="Límite superior de la banda P10-P90")
    promedio_dia_hora: float | None = Field(None, description="Línea base de §9.1: promedio de la misma ventana en "
                                                              "las 8 semanas anteriores (mismo día y hora)")
    ultima_semana: float | None = Field(None, description="Línea base de §9.1: la misma ventana hace 7 días")
    real: float | None = Field(None, description="Subidas que hubo en la ventana, si ya están en los datos (solo "
                                                 "para comparar; el pronóstico no las usa)")


class SentidoCortoPlazo(CeldaCortoPlazo):
    sentido: str = Field(..., description="ida o regreso (aproximado por la mitad del ciclo, supuesto S9)")


class SegmentoCortoPlazo(CeldaCortoPlazo):
    nro_segmento: int
    sentido: str
    km_inicio: float = Field(..., description="Kilómetro del ciclo en que empieza el segmento")
    lat: float | None = None
    lon: float | None = None


class FactorCortoPlazo(BaseModel):
    variable: str
    descripcion: str
    valor: float | None = None
    contribucion_log: float = Field(..., description="Contribución TreeSHAP en la escala log del modelo de Poisson")
    factor: float = Field(..., description="exp(contribución): factor por el que la variable multiplica el pronóstico")
    sentido: Literal["sube", "baja"]


class ExplicacionCortoPlazo(BaseModel):
    metodo: str
    valor_base: float | None = Field(None, description="Pronóstico sin ninguna variable (exp del valor esperado)")
    factores: list[FactorCortoPlazo] = Field(default_factory=list)


class ObservadoCortoPlazo(BaseModel):
    """Lo que ya se sabe en el instante, en toda la ruta."""
    ultimos_15_min: float | None = None
    ultimos_30_min: float | None = None
    ultimos_60_min: float | None = None
    ultimas_2_horas: float | None = None
    acumulado_hoy: float | None = None
    habitual_acumulado: float | None = Field(None, description="Lo acumulado a esta hora en las 4 semanas anteriores")
    salidas_ultima_hora: float | None = None


class VentanaCortoPlazo(BaseModel):
    desde: datetime
    hasta: datetime


class PronosticoCortoPlazo(Salida, CeldaCortoPlazo):
    """Pronóstico de corto plazo de una ruta en un instante y un horizonte (RF-005, RF-006, §9.2, §9.4, §12.3)."""
    grupo_id: uuid.UUID | None = Field(None, description="Identificador del pronóstico guardado (nulo si se calculó "
                                                         "sin guardar)")
    ruta: str
    idruta: int = Field(..., description=DESC_IDRUTA)
    instante_solicitado: datetime
    instante: datetime = Field(..., description="Instante usado (la media hora)")
    horizonte_min: int
    ventana: VentanaCortoPlazo
    franja: str | None = None
    model_id: str
    feature_version: str
    data_cutoff: date | None = Field(None, description="Último día con que se entrenó el modelo")
    en_muestra: bool = Field(..., description="La fecha está dentro del periodo de entrenamiento del modelo")
    dia_con_datos: bool = Field(..., description="El día trae eventos de conteo (si no, lo real no se compara)")
    generated_at: datetime | None = None
    latencia_ms: float | None = None
    sentidos: list[SentidoCortoPlazo] = Field(default_factory=list)
    segmentos: list[SegmentoCortoPlazo] = Field(default_factory=list)
    observado: ObservadoCortoPlazo
    explicacion: ExplicacionCortoPlazo
    recomendacion: dict | None = Field(None, description="§10.2 con este pronóstico llevado a ritmo por hora")
    # §12.3 «Ejemplo de respuesta de predicción»
    predictionId: uuid.UUID | None = None
    routeId: str | None = None
    generatedAt: str | None = Field(None, description="ISO-8601 con la zona de Bogotá (-05:00)")
    horizonMinutes: int | None = None
    predictedPassengers: int | None = None
    confidenceInterval: IntervaloConfianza | None = None
    modelVersion: str | None = None
    recommendation: RecomendacionResumen | None = None
    explanation: list[str] = Field(default_factory=list, description="Variables que más mueven este pronóstico")


class PuntoDiaCortoPlazo(CeldaCortoPlazo):
    instante: datetime
    franja: str | None = None
    sentidos: list[SentidoCortoPlazo] = Field(default_factory=list)


class DiaCortoPlazo(Salida):
    """La curva del día: el pronóstico de cada media hora de 04:00 a 21:00, por ruta y por sentido."""
    ruta: str
    idruta: int
    fecha: date
    horizonte_min: int
    model_id: str
    en_muestra: bool
    dia_con_datos: bool
    instantes: list[PuntoDiaCortoPlazo]


class PrediccionCortoPlazoSalida(Salida):
    prediction_id: uuid.UUID
    grupo_id: uuid.UUID
    execution_id: uuid.UUID | None = None
    ruta: str
    idruta: int = Field(..., description=DESC_IDRUTA)
    nivel: Literal["ruta", "sentido", "segmento"]
    sentido: str | None = None
    nro_segmento: int | None = None
    instante: datetime
    horizonte_min: int
    objetivo: datetime
    fecha: date
    franja: str | None = None
    pasajeros: float
    p10: float | None = None
    p90: float | None = None
    promedio_dia_hora: float | None = None
    ultima_semana: float | None = None
    model_id: str
    feature_version: str
    data_cutoff: date | None = None
    generated_at: datetime
    latencia_ms: float | None = None
    explicacion: dict = Field(default_factory=dict)
    variables: dict = Field(default_factory=dict)
    recomendacion: dict | None = None
    creado_en: datetime


class ModeloCortoPlazo(Salida):
    """§9.2: la versión del modelo de corto plazo con su fecha de corte, sus artefactos (SHA-256), sus datos y las
    cifras de su prueba reservada."""
    model_config = ConfigDict(protected_namespaces=())
    model_id: str
    tipo: str | None = None
    feature_version: str | None = None
    data_cutoff: date | None = None
    entrenado_con: str | None = None
    semilla: int | None = None
    estructura: dict = Field(default_factory=dict)
    banda: str | None = None
    sha256: dict = Field(default_factory=dict)
    version_datos: dict = Field(default_factory=dict)
    metricas_prueba: dict = Field(default_factory=dict)
    origen: dict = Field(default_factory=dict)
    evaluacion: str | None = None
    activo: str | None = None
    historial_activacion: list = Field(default_factory=list)
    cobertura: dict = Field(default_factory=dict, description="Fechas que se pueden pronosticar y las de la prueba")


class EscenarioRecomendacion(BaseModel):
    """RF-008 «qué pasa si»: el mismo cálculo con la demanda, los pesos u otras restricciones cambiadas."""
    factor_demanda: float | None = Field(None, gt=0, le=5, description="Multiplica la demanda puntual y su banda")
    pesos: dict[str, float] | None = Field(None, description="alfa, beta, gamma, delta (o sus nombres en "
                                                             "threshold_config) con el valor nuevo")
    nivel_servicio: float | None = Field(None, ge=0.5, lt=1)
    ocupacion_objetivo: float | None = Field(None, gt=0, le=1)
    flota_disponible: int | None = Field(None, ge=0)
    capacidad: int | None = Field(None, gt=0)
    tiempo_ciclo_min: float | None = Field(None, gt=0)
    headway_min: float | None = Field(None, gt=0)
    headway_max: float | None = Field(None, gt=0)


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
    # §10.2 (función objetivo), §10.1 (tipologías), RF-008 (escenarios) y §10.3 (sensibilidad); todos opcionales
    demanda_p10: float | None = Field(None, ge=0)
    nivel_servicio: float | None = Field(None, ge=0.5, lt=1, description="Por omisión, el de threshold_config "
                                                                         "(0,90 = P90 calibrado)")
    ocupacion_critica: float | None = Field(None, gt=0, le=1.5)
    pesos: dict[str, float] | None = Field(None, description="α, β, γ, δ para esta solicitud (alfa, beta, gamma, "
                                                             "delta); por omisión los vigentes de threshold_config")
    tipologias: bool = Field(True, description="§10.1: asignar la capacidad por tipología con la flota de la ruta")
    escenario: EscenarioRecomendacion | None = None
    sensibilidad: bool = Field(False, description="Incluir el análisis de sensibilidad (unas 25 resoluciones)")


class RecomendacionCalculada(RecomendacionSalida):
    """Respuesta de POST /recommendations/calculate: la recomendación guardada y su explicación completa."""
    metodo: str | None = None
    objetivo: dict | None = None
    demanda: dict | None = None
    solver: dict | None = None
    restricciones: list[dict] = Field(default_factory=list)
    limites_activos: list[str] = Field(default_factory=list)
    tipologias: dict | None = None
    margen: dict | None = None
    linea_base_10_3: dict | None = Field(None, description="§10.3 ajustada: carga crítica (factor de carga × P90)")
    linea_base_10_3_literal: dict | None = Field(None, description="§10.3 literal: factor 1 y demanda puntual")
    sobreoferta: bool | None = Field(None, description="Ocupación esperada menor que ocupacion_objetivo_min (§5.1)")
    motivo_sobreoferta: str | None = None
    mejor_aproximacion: dict | None = None
    comparacion_actual: dict | None = None
    escenario: dict | None = None
    sensibilidad: dict | None = None
    contexto_franja: dict | None = Field(None, description="Ciclo, flota e intervalo programado de la franja con su "
                                                           "fuente; ajuste_operativo dice si la flota o el ciclo "
                                                           "vienen del ajuste local versionado (PUT /catalogos/flota)")
    capacidad_gobernada: dict | None = None
    cambio_frecuenciadespachos: str | None = Field(None, description=DESC_CAMBIO_FRECUENCIADESPACHOS)
    fuente_frecuenciadespachos: str | None = Field(None, description="De dónde sale el headway vigente (§6.1)")
    ocupacion_historica: dict | None = Field(None, description=DESC_OCUPACION_HISTORICA)
    explicacion: list[str] = Field(default_factory=list)


class PlanHora(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    hora: int
    salidas: int
    despachos: list[str] = Field(default_factory=list)
    headway_min: float | None = None
    programar: int | None = None
    pasajeros_previstos: float | None = None
    minutos_operados: float | None = None
    tiempo_ciclo_min: float | None = None
    vehiculos_requeridos: int | None = None
    frecuencia_actual_min: float | None = None
    salidas_programadas: float | None = None
    diferencia_salidas: float | None = None
    estado_solver: str | None = None
    tipo_dia: str | None = None
    modelo: str | None = None
    # pronóstico del modelo activo y gobierno de la hora (§10.1-§10.3, §5.1)
    pasajeros_p10: float | None = None
    pasajeros_p90: float | None = None
    fuente_pronostico: str | None = Field(None, description="modelo_activo o E12 (opción de laboratorio)")
    model_id: str | None = None
    calibracion_version: str | None = None
    headway_minimo_min: float | None = None
    headway_maximo_min: float | None = Field(None, description="Headway máximo efectivo: min(headway_maximo_min, "
                                                               "2 × espera_max_min)")
    minimo_salidas_headway: int | None = None
    maximo_salidas_headway: int | None = None
    salidas_sin_tope: int | None = None
    limitada_por_headway_minimo: bool | None = None
    factor_carga: float | None = None
    demanda_diseno: float | None = Field(None, description="Carga crítica de diseño (pasajeros/h en el punto de "
                                                           "carga máxima al nivel de servicio)")
    capacidad_efectiva: float | None = None
    ocupacion_esperada: float | None = None
    buses_en_ruta_max: float | None = None
    limites_activos: list[str] = Field(default_factory=list)
    margen: dict | None = None
    sin_intervalo: bool | None = Field(None, description="Una sola salida en la hora: no hay intervalo entre salidas "
                                                         "que verificar, así que el headway mínimo no aplica")
    flota_disponible: float | None = Field(None, description="Flota disponible del día (la misma en todas las horas)")
    costo_hora_cop: float | None = Field(None, description="Costo de D5 de la hora sin ponderar (COP)")
    componentes_costo_cop: dict[str, float] | None = Field(None, description="Operación, espera, sobrecarga e "
                                                                             "ingreso perdido de la hora (COP)")
    viable: bool | None = None
    motivo: str | None = None
    sobreoferta: bool | None = Field(None, description="Ocupación esperada menor que ocupacion_objetivo_min (§5.1)")
    motivo_sobreoferta: str | None = None
    frecuenciadespachos_min: float | None = Field(None, description=DESC_FRECUENCIADESPACHOS)
    diferencia_frecuenciadespachos_min: float | None = Field(None, description=DESC_DIFERENCIA_FRECUENCIADESPACHOS)
    cambio_frecuenciadespachos: str | None = Field(None, description=DESC_CAMBIO_FRECUENCIADESPACHOS)
    ocupacion_historica: dict | None = Field(None, description=DESC_OCUPACION_HISTORICA)
    restriccion_reactiva: dict | None = Field(None, description=DESC_RESTRICCION_REACTIVA)


class PlanDia(BaseModel):
    """GET /recommendations/plan: plan del día por hora (MILP de D5, pronóstico del modelo activo) y su resumen."""
    model_config = ConfigDict(protected_namespaces=())
    ruta: str
    fecha: date
    modelo: str
    tipo_dia: str | None = None
    estado_solver: str | None = None
    flota_disponible: float | None = None
    holgura_flota: float | None = None
    salidas_dia: int
    salidas_programadas_dia: float | None = None
    vehiculos_hora_pico: int | None = Field(None, description="Máximo por hora de ceil(ciclo / headway) de §10.3, con "
                                                              "headway = 60 / salidas por hora")
    buses_en_ruta_pico: float | None = Field(None, description="Máximo de buses en ruta a la vez con el plan (conteo "
                                                               "de D5 cada 15 min, el que limita la flota del MILP)")
    definicion_vehiculos: str | None = Field(None, description="Qué mide vehiculos_hora_pico y qué mide "
                                                               "buses_en_ruta_pico")
    componentes_costo_cop: dict[str, float] = Field(default_factory=dict)
    costo_total_cop: float | None = None
    fuente_costos: str | None = None
    formulacion: str | None = None
    fuente_pronostico: str | None = None
    model_id: str | None = None
    calibracion_version: str | None = None
    umbrales_version: int | None = None
    headway_minimo_min: float | None = None
    headway_maximo_min: float | None = None
    horas_limitadas_por_headway_minimo: list[int] = Field(default_factory=list)
    horas_no_viables: list[int] = Field(default_factory=list)
    horas_sobreoferta: list[int] = Field(default_factory=list)
    viable: bool | None = None
    parametros: dict | None = Field(None, description="Parámetros del MILP con la fuente de cada uno (threshold_config "
                                                      "vN o el código): límites de headway, costos y pesos de §10.2, "
                                                      "tarifa, elasticidad y suavidad")
    flota_y_ciclo: dict | None = Field(None, description="De dónde salen la flota disponible, el ciclo de cada hora y "
                                                         "la capacidad por bus: el ajuste local versionado (PUT "
                                                         "/catalogos/flota y PUT /catalogos/capacidad) o el dato "
                                                         "empaquetado")
    frecuenciadespachos_min: float | None = Field(None, description=DESC_FRECUENCIADESPACHOS)
    fuente_frecuenciadespachos: str | None = None
    ocupacion_actual: dict | None = Field(None, description=DESC_OCUPACION_ACTUAL)
    insumos_operativos: str | None = None
    execution_id: str | None = None
    calculado_en: datetime | None = None
    origen: str | None = None
    horas: list[PlanHora]


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
    # migración 0003: §5.3 completa, §9.4 (nunca opaca: tendencia y método del puntaje) y §8.1 (ubicación)
    origen: str | None = Field(None, description="pronostico, observado, calidad_datos o modelo")
    tendencia: str | None = Field(None, description="al_alza, a_la_baja, estable o sin_datos (§9.4)")
    tendencia_pendiente: float | None = Field(None, description="Cambio relativo por hora de la serie analizada")
    serie_reciente: list = Field(default_factory=list, description="Valores real/esperado de las horas analizadas")
    probabilidad: float | None = Field(None, description="Probabilidad del evento (0..1), cuando aplica (§5.3)")
    metodo_puntaje: str | None = Field(None, description="Cómo se calcularon el puntaje y la probabilidad")
    variables_influyentes: list = Field(default_factory=list, description="[{variable, valor, efecto}] (§5.3)")
    ubicacion: dict | None = Field(None, description="GeoJSON Point (lon, lat) del lugar de la alerta (§8.1)")
    # migración 0006: dimensiones de §8.3 (día y estacionalidad de la ventana analizada)
    idruta: int | None = Field(None, description=DESC_IDRUTA)
    idempresa: int | None = Field(None, description=DESC_IDEMPRESA)
    idproceso: str | None = Field(None, description=DESC_IDPROCESO)
    id_dia_semana: int | None = Field(None, description=DESC_DIA_SEMANA)
    id_estacionalidad: int | None = Field(None, description=DESC_ESTACIONALIDAD)


class SolicitudEstadoAlerta(BaseModel):
    accion: Literal["reconocer", "asignar", "comentar", "cerrar", "descartar"]
    usuario: str | None = Field(None, min_length=1, description=AUDITORIA_OPCIONAL)
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

    @field_validator("auditoria", mode="after")
    @classmethod
    def _auditoria_en_bogota(cls, entradas: list) -> list:
        """§8.1: la auditoría guarda instantes en UTC; la API los presenta en America/Bogota (-05:00)."""
        return [{**e, "en": _instante_bogota(e["en"])} if isinstance(e, dict) and "en" in e else e
                for e in entradas]


class SolicitudActivacion(BaseModel):
    aprobado_por: str | None = Field(None, min_length=1, description=AUDITORIA_OPCIONAL)
    validacion_desde: date | None = None
    validacion_hasta: date | None = None
    motivo: str | None = None


class SolicitudReversion(BaseModel):
    usuario: str | None = Field(None, min_length=1, description=AUDITORIA_OPCIONAL)
    motivo: str | None = None


class SolicitudEntrenamiento(BaseModel):
    hasta: date
    semilla: int = 42
    solicitado_por: str | None = None
    # con datos_hasta la serie se trunca ahí (solo datos ya validados) y el candidato pasa a sombra (§9.5)
    datos_hasta: date | None = Field(None, description="Último día de datos validados que se usan (validación = "
                                                       "hasta+1 .. datos_hasta); el candidato queda en sombra")


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
    # migración 0006: validación del área operativa (§5.1); nulo = versión propuesta, sin aprobar
    aprobado_por: str | None = None
    aprobado_en: datetime | None = None


class UmbralesVigentes(Salida):
    version: int
    valores: dict[str, Any]
    detalle: list[UmbralSalida]
    estado: Literal["propuesta", "aprobada"] = Field(
        "propuesta", description="§5.1: los valores son referencias iniciales hasta que el área operativa aprueba la "
                                 "versión con POST /thresholds/{version}/aprobar (rol admin)")
    aprobado_por: str | None = None
    aprobado_en: datetime | None = None


class SolicitudAprobacionUmbrales(BaseModel):
    aprobado_por: str | None = Field(None, min_length=1, description=AUDITORIA_OPCIONAL)
    comentario: str | None = Field(None, description="Constancia de la validación (acta, fecha de la reunión, etc.)")


class SolicitudUmbrales(BaseModel):
    valores: dict[str, Any] = Field(..., min_length=1)
    creado_por: str | None = Field(None, min_length=1, description=AUDITORIA_OPCIONAL)
    motivo: str | None = None
