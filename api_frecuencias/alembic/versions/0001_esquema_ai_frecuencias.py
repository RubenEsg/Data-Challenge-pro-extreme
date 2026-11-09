"""Esquema ai_frecuencias: registro de modelos, predicciones, recomendaciones, alertas,
bitácora de ejecuciones, errores de calidad, umbrales versionados y notificaciones.

Solo crea objetos en el esquema propio ai_frecuencias; no toca tablas operacionales.

Revision ID: 0001
Revises:
"""
from __future__ import annotations

import json

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

E = "ai_frecuencias"

DDL = f"""
CREATE TABLE {E}.model_registry (
    id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    model_id          TEXT NOT NULL UNIQUE,
    version           TEXT NOT NULL,
    tipo              TEXT NOT NULL CHECK (tipo IN ('linea_base','candidato')),
    artefacto         TEXT NOT NULL,
    sha256            TEXT NOT NULL,
    feature_version   TEXT NOT NULL,
    data_cutoff       TIMESTAMPTZ,
    metricas          JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    estado            TEXT NOT NULL DEFAULT 'candidato'
                      CHECK (estado IN ('activo','candidato','rechazado','retirado')),
    aprobado_por      TEXT,
    activado_en       TIMESTAMPTZ,
    anterior_model_id TEXT REFERENCES {E}.model_registry(model_id),
    motivo            TEXT,
    auditoria         JSONB NOT NULL DEFAULT '[]'::jsonb,
    execution_id      UUID,
    creado_en         TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX ux_model_registry_un_activo ON {E}.model_registry (estado) WHERE estado = 'activo';

CREATE TABLE {E}.execution_log (
    execution_id        UUID PRIMARY KEY,
    tipo                TEXT NOT NULL DEFAULT 'frecuencia' CHECK (tipo IN ('frecuencia','entrenamiento')),
    estado              TEXT NOT NULL DEFAULT 'en_cola' CHECK (estado IN ('en_cola','corriendo','ok','error')),
    etapa               TEXT,
    progreso            NUMERIC(5,2) NOT NULL DEFAULT 0 CHECK (progreso BETWEEN 0 AND 100),
    intentos            INTEGER NOT NULL DEFAULT 0,
    marca_agua_anterior TIMESTAMPTZ,
    marca_agua_nueva    TIMESTAMPTZ,
    data_cutoff         TIMESTAMPTZ,
    filas_leidas        INTEGER,
    filas_validas       INTEGER,
    model_id            TEXT,
    feature_version     TEXT,
    umbrales_version    INTEGER,
    parametros          JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    metricas            JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    correlation_id      TEXT,
    mensaje             TEXT,
    creado_en           TIMESTAMPTZ NOT NULL DEFAULT now(),
    iniciado_en         TIMESTAMPTZ,
    terminado_en        TIMESTAMPTZ,
    actualizado_en      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_execution_log_estado ON {E}.execution_log (estado, creado_en DESC);
CREATE INDEX ix_execution_log_tipo_fin ON {E}.execution_log (tipo, estado, terminado_en DESC);

CREATE TABLE {E}.data_quality_error (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    execution_id UUID NOT NULL REFERENCES {E}.execution_log(execution_id) ON DELETE CASCADE,
    lote         TEXT NOT NULL,
    fila         BIGINT,
    campo        TEXT,
    codigo       TEXT NOT NULL,
    dimension    TEXT NOT NULL CHECK (dimension IN
                 ('completitud','validez','unicidad','consistencia','oportunidad','relacional')),
    detalle      TEXT,
    creado_en    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_dq_error_ejecucion ON {E}.data_quality_error (execution_id, lote, fila);

-- Histórico validado propio (copia de lo leído); la clave natural evita duplicar cargas repetidas.
CREATE TABLE {E}.demanda_observada (
    id                   BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ruta                 TEXT NOT NULL,
    fecha                DATE NOT NULL,
    hora                 INTEGER NOT NULL CHECK (hora BETWEEN 0 AND 23),
    pasajeros            DOUBLE PRECISION,
    salidas              INTEGER,
    ultima_actualizacion TIMESTAMPTZ,
    execution_id         UUID REFERENCES {E}.execution_log(execution_id) ON DELETE SET NULL,
    cargado_en           TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ux_demanda_observada_clave UNIQUE (ruta, fecha, hora)
);

CREATE TABLE {E}.prediction (
    prediction_id   UUID PRIMARY KEY,
    execution_id    UUID REFERENCES {E}.execution_log(execution_id) ON DELETE SET NULL,
    ruta            TEXT NOT NULL,
    instante        TIMESTAMPTZ NOT NULL,
    horizonte_min   INTEGER NOT NULL CHECK (horizonte_min IN (30,60,120)),
    objetivo        TIMESTAMPTZ NOT NULL,
    fecha           DATE NOT NULL,
    hora            INTEGER NOT NULL,
    pasajeros       DOUBLE PRECISION NOT NULL,
    p10             DOUBLE PRECISION,
    p90             DOUBLE PRECISION,
    model_id        TEXT NOT NULL,
    feature_version TEXT,
    data_cutoff     TIMESTAMPTZ,
    generated_at    TIMESTAMPTZ NOT NULL,
    latencia_ms     DOUBLE PRECISION,
    explicacion     JSONB NOT NULL DEFAULT '[]'::jsonb,
    variables       JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    creado_en       TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ux_prediction_ejecucion UNIQUE (execution_id, ruta, instante, horizonte_min)
);
CREATE INDEX ix_prediction_ruta_fecha ON {E}.prediction (ruta, fecha, hora);
CREATE INDEX ix_prediction_generada ON {E}.prediction (generated_at DESC);

CREATE TABLE {E}.recommendation (
    recommendation_id     UUID PRIMARY KEY,
    execution_id          UUID REFERENCES {E}.execution_log(execution_id) ON DELETE SET NULL,
    prediction_id         UUID REFERENCES {E}.prediction(prediction_id) ON DELETE SET NULL,
    ruta                  TEXT NOT NULL,
    fecha                 DATE NOT NULL,
    hora                  INTEGER NOT NULL,
    demanda_hora          DOUBLE PRECISION,
    demanda_p90           DOUBLE PRECISION,
    buses_hora            INTEGER,
    headway_min           DOUBLE PRECISION,
    vehiculos_requeridos  INTEGER,
    capacidad_efectiva    DOUBLE PRECISION,
    ocupacion_esperada    DOUBLE PRECISION,
    viable                BOOLEAN NOT NULL DEFAULT true,
    motivo                TEXT,
    frecuencia_actual_min DOUBLE PRECISION,
    diferencia_min        DOUBLE PRECISION,
    formula               TEXT,
    umbrales_version      INTEGER,
    detalle               JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    creado_en             TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_recommendation_ruta_fecha ON {E}.recommendation (ruta, fecha, hora);

CREATE TABLE {E}.alert (
    alert_id         UUID PRIMARY KEY,
    codigo           TEXT NOT NULL CHECK (codigo ~ '^ALT-0[0-9]{{2}}$'),
    execution_id     UUID REFERENCES {E}.execution_log(execution_id) ON DELETE SET NULL,
    empresa          TEXT,
    ruta             TEXT,
    sentido          TEXT,
    viaje            TEXT,
    conductor        TEXT,
    vehiculo         TEXT,
    detectada_en     TIMESTAMPTZ NOT NULL,
    ventana_inicio   TIMESTAMPTZ,
    ventana_fin      TIMESTAMPTZ,
    horizonte_min    INTEGER,
    severidad        TEXT NOT NULL CHECK (severidad IN ('informativa','preventiva','critica')),
    estado           TEXT NOT NULL DEFAULT 'nueva',
    observado        DOUBLE PRECISION,
    esperado         DOUBLE PRECISION,
    umbral           DOUBLE PRECISION,
    puntaje          DOUBLE PRECISION,
    explicacion      TEXT,
    variables        JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    recomendacion    TEXT,
    asignado_a       TEXT,
    comentarios      JSONB NOT NULL DEFAULT '[]'::jsonb,
    clave_dedup      TEXT NOT NULL,
    ocurrencias      INTEGER NOT NULL DEFAULT 1,
    ultima_deteccion TIMESTAMPTZ,
    creado_en        TIMESTAMPTZ NOT NULL DEFAULT now(),
    actualizado_en   TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- Deduplicación: una sola alerta abierta por clave.
CREATE UNIQUE INDEX ux_alert_dedup_abiertas ON {E}.alert (clave_dedup)
    WHERE estado NOT IN ('cerrada','descartada');
CREATE INDEX ix_alert_estado ON {E}.alert (estado, severidad, detectada_en DESC);
CREATE INDEX ix_alert_ruta_fecha ON {E}.alert (ruta, detectada_en DESC);

CREATE TABLE {E}.alert_history (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    alert_id        UUID NOT NULL REFERENCES {E}.alert(alert_id) ON DELETE CASCADE,
    accion          TEXT NOT NULL,
    estado_anterior TEXT,
    estado_nuevo    TEXT NOT NULL,
    usuario         TEXT NOT NULL,
    comentario      TEXT,
    asignado_a      TEXT,
    detalle         JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    creado_en       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_alert_history_alerta ON {E}.alert_history (alert_id, creado_en);

CREATE TABLE {E}.threshold_config (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    nombre      TEXT NOT NULL,
    valor       JSONB NOT NULL,
    descripcion TEXT,
    version     INTEGER NOT NULL,
    vigente     BOOLEAN NOT NULL DEFAULT true,
    creado_por  TEXT NOT NULL,
    motivo      TEXT,
    creado_en   TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ux_threshold_nombre_version UNIQUE (nombre, version)
);
CREATE UNIQUE INDEX ux_threshold_vigente ON {E}.threshold_config (nombre) WHERE vigente;

CREATE TABLE {E}.notification_log (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    execution_id UUID REFERENCES {E}.execution_log(execution_id) ON DELETE SET NULL,
    alert_id     UUID REFERENCES {E}.alert(alert_id) ON DELETE SET NULL,
    canal        TEXT NOT NULL,
    destinatario TEXT,
    asunto       TEXT,
    mensaje      TEXT,
    estado       TEXT NOT NULL DEFAULT 'simulado',
    simulado     BOOLEAN NOT NULL DEFAULT true,
    detalle      JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    creado_en    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_notification_log_alerta ON {E}.notification_log (alert_id, creado_en);
"""

# Parámetros de la sección 5.1 con los valores iniciales sugeridos (versión 1).
#   Los nombres coinciden con app/servicios/alertas.UMBRALES_POR_DEFECTO y con optimizacion.recomendar().
UMBRALES_INICIALES = [
    ("ocupacion_objetivo_min", 0.65, "§5.1 Ocupación objetivo: límite inferior del rango deseado (fracción)"),
    ("ocupacion_objetivo_max", 0.85, "§5.1 Ocupación objetivo: límite superior; capacidad efectiva = capacidad × valor"),
    ("ocupacion_critica", 0.90, "§5.1 Ocupación crítica: riesgo de sobreocupación (≥)"),
    ("baja_utilizacion", 0.30, "§5.1 Baja utilización: despacho potencialmente ineficiente (<)"),
    ("espera_max_min", 5.0, "§5.1 Espera máxima objetivo (minutos)"),
    ("headway_minimo_min", 2.0, "§5.1 Headway mínimo (minutos); lo define la operación: valor supuesto del equipo"),
    ("headway_maximo_min", 10.0, "Headway máximo (minutos) = 2 × espera máxima; valor supuesto del equipo"),
    ("error_pronostico", 0.15, "§5.1 Error de pronóstico: desviación relativa pronóstico vs. consolidado (≥)"),
    ("periodos_atraso", 2, "§5.1 Datos atrasados: períodos de ingesta sin recepción antes de alertar"),
    ("periodo_ingesta_min", 1440.0, "Duración de un período de ingesta (minutos); la actualización es diaria"),
    ("caida_demanda", 0.30, "ALT-005: caída relativa frente al patrón histórico (≥)"),
    ("demanda_minima_patron", 10.0, "ALT-005: no se evalúa con patrones de demanda muy bajos"),
    ("tolerancia_despacho_min", 5.0, "ALT-006: minutos de tolerancia sobre el headway programado"),
    ("tolerancia_salidas", 0.20, "ALT-006: déficit relativo de salidas tolerado"),
    ("z_anomalia", 3.0, "ALT-008: |z| del consolidado frente a su referencia"),
    ("wape_max", 0.20, "ALT-010: WAPE móvil máximo tolerado (≈ WAPE de la regla manual B1, 20,04 %)"),
]


def upgrade() -> None:
    op.execute(f"DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = '{E}') THEN CREATE SCHEMA {E}; END IF; END $$")  # noqa: E501  [integracion] escritor_ia sin CREATE en la base
    op.execute(DDL)
    conexion = op.get_bind()
    import sqlalchemy as sa

    for nombre, valor, descripcion in UMBRALES_INICIALES:
        conexion.execute(
            sa.text(
                f"INSERT INTO {E}.threshold_config (nombre, valor, descripcion, version, vigente, creado_por, motivo) "
                "VALUES (:n, CAST(:v AS jsonb), :d, 1, true, 'migracion_0001', "
                "'Valores iniciales sugeridos por la especificación v1.5, sección 5.1')"
            ),
            {"n": nombre, "v": json.dumps(valor), "d": descripcion},
        )


def downgrade() -> None:
    for tabla in (
        "notification_log",
        "threshold_config",
        "alert_history",
        "alert",
        "recommendation",
        "prediction",
        "demanda_observada",
        "data_quality_error",
        "execution_log",
        "model_registry",
    ):
        op.execute(f"DROP TABLE IF EXISTS {E}.{tabla} CASCADE")
