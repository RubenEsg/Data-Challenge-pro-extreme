"""Monitoreo del modelo, foto de variables particionada y trazabilidad (§9.2, §9.4, §9.5, §11.2, §8.1, RNF-011).

- model_monitoring: una fila por ejecución y modelo (rol activo o sombra) con el error móvil (WAPE, MAE, sesgo), la
  cobertura P10-P90, la deriva (PSI por variable y máximo), el volumen de predicciones, el porcentaje de alertas
  descartadas (alert_history) y el estado ok / aviso / alerta con sus motivos. Alimenta ALT-010 y la política de
  reentrenamiento (app/servicios/politica.py).
- prediction: p10_modelo y p90_modelo (banda del modelo sin calibrar), ajuste_conformal (q del CQR móvil) y
  explicacion_local (SHAP) como columnas propias; hasta ahora viajaban dentro de variables (JSONB).
- feature_snapshot (§11.2 «La foto de variables se guarda en ai_frecuencias con fecha de corte y versión»): el vector
  exacto que vio el modelo por predicción y hora, con feature_version y data_cutoff. PARTITION BY RANGE
  (ventana_inicio) con particiones MENSUALES en UTC (§8.1 «particionamiento mensual de las tablas de alta
  volumetría»). Volumen: hoy son ~20 filas por ejecución (3 rutas × 3 horizontes × 1-3 horas), pero el diseño de
  §9.1 llega a ruta × sentido × segmento × ventana: con ~130 segmentos por ruta, 2 sentidos, 3 horizontes y
  ejecuciones horarias (la frecuencia es parametrizable, §9.5) son ~47.000 filas por ruta y día, ~17 millones por
  ruta y año (~1,5 KB de JSONB cada una). El mes es la unidad natural de consulta (evaluación móvil, auditoría) y de
  retención: una partición vieja se separa o se borra con DETACH/DROP PARTITION sin VACUUM masivo (§18 «retención»).
  asegurar_particion_feature_snapshot(ts) crea la partición del mes de ts si falta (la llama el ciclo antes de
  escribir); la migración deja creada la del mes actual.
- execution_log.traceparent: contexto W3C de la traza de quien encoló la ejecución, para que la réplica que la tome
  continúe la misma traza (RNF-006).
- threshold_config: versión nueva del conjunto completo con los umbrales del monitoreo y de la política de
  reentrenamiento (sombra, compuerta y reversión). La anterior queda en el histórico.

Solo toca el esquema propio ai_frecuencias.

Revision ID: 0004
Revises: 0003
"""
from __future__ import annotations

import json

import sqlalchemy as sa

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

E = "ai_frecuencias"

DDL = f"""
CREATE TABLE {E}.model_monitoring (
    id                   BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    execution_id         UUID REFERENCES {E}.execution_log(execution_id) ON DELETE CASCADE,
    model_id             TEXT NOT NULL,
    rol                  TEXT NOT NULL DEFAULT 'activo' CHECK (rol IN ('activo','sombra')),
    fecha_corte          DATE,
    desde                DATE,
    hasta                DATE,
    ventana_dias         INTEGER NOT NULL,
    n_observaciones      INTEGER,
    n_predicciones       INTEGER,
    predicciones_ventana INTEGER,
    wape_movil           DOUBLE PRECISION,
    mae_movil            DOUBLE PRECISION,
    sesgo_pct            DOUBLE PRECISION,
    cobertura_p10_p90    DOUBLE PRECISION,
    psi                  JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    psi_max              DOUBLE PRECISION,
    psi_variable_max     TEXT,
    alertas_total        INTEGER,
    alertas_descartadas  INTEGER,
    pct_descartadas      DOUBLE PRECISION,
    estado               TEXT NOT NULL CHECK (estado IN ('ok','aviso','alerta','sin_datos')),
    motivos              JSONB NOT NULL DEFAULT '[]'::jsonb,
    umbrales_version     INTEGER,
    detalle              JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    creado_en            TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_model_monitoring_modelo ON {E}.model_monitoring (model_id, rol, creado_en DESC);
CREATE INDEX ix_model_monitoring_estado ON {E}.model_monitoring (estado, creado_en DESC);
CREATE UNIQUE INDEX ux_model_monitoring_ejecucion ON {E}.model_monitoring (execution_id, model_id, rol)
    WHERE execution_id IS NOT NULL;
COMMENT ON TABLE {E}.model_monitoring IS '§9.4 monitoreo por ejecución: deriva (PSI), error móvil, cobertura, volumen y alertas descartadas';
COMMENT ON COLUMN {E}.model_monitoring.wape_movil IS 'WAPE (fracción) de los últimos ventana_dias días observados; alimenta ALT-010';
COMMENT ON COLUMN {E}.model_monitoring.psi IS 'PSI por variable con su umbral efectivo (máx. del fijo y del ruido propio de la referencia)';

ALTER TABLE {E}.prediction
    ADD COLUMN p10_modelo        DOUBLE PRECISION,
    ADD COLUMN p90_modelo        DOUBLE PRECISION,
    ADD COLUMN ajuste_conformal  DOUBLE PRECISION,
    ADD COLUMN explicacion_local JSONB;
COMMENT ON COLUMN {E}.prediction.p10_modelo IS 'Límite inferior del modelo de cuantiles antes de la calibración conformal';
COMMENT ON COLUMN {E}.prediction.p90_modelo IS 'Límite superior del modelo de cuantiles antes de la calibración conformal';
COMMENT ON COLUMN {E}.prediction.ajuste_conformal IS 'q del CQR móvil por ruta (56 días previos fuera de muestra); NULL = sin ajustar';
COMMENT ON COLUMN {E}.prediction.explicacion_local IS 'RF-015/§9.4 explicación local SHAP exacta de la hora principal';

CREATE TABLE {E}.feature_snapshot (
    id              BIGINT GENERATED ALWAYS AS IDENTITY,
    execution_id    UUID REFERENCES {E}.execution_log(execution_id) ON DELETE CASCADE,
    prediction_id   UUID REFERENCES {E}.prediction(prediction_id) ON DELETE CASCADE,
    model_id        TEXT,
    ruta            TEXT NOT NULL,
    sentido         TEXT,
    segmento        INTEGER,
    horizonte_min   INTEGER,
    ventana_inicio  TIMESTAMPTZ NOT NULL,
    ventana_fin     TIMESTAMPTZ NOT NULL,
    fecha           DATE NOT NULL,
    hora            INTEGER NOT NULL CHECK (hora BETWEEN 0 AND 23),
    features        JSONB NOT NULL,
    feature_version TEXT NOT NULL,
    data_cutoff     TIMESTAMPTZ,
    creado_en       TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (id, ventana_inicio)
) PARTITION BY RANGE (ventana_inicio);
CREATE INDEX ix_feature_snapshot_ejecucion ON {E}.feature_snapshot (execution_id);
CREATE INDEX ix_feature_snapshot_prediccion ON {E}.feature_snapshot (prediction_id);
CREATE INDEX ix_feature_snapshot_ruta_fecha ON {E}.feature_snapshot (ruta, fecha, hora);
COMMENT ON TABLE {E}.feature_snapshot IS '§11.2 foto de variables por predicción y hora, con fecha de corte y versión; particiones mensuales (UTC) por ventana_inicio';

CREATE OR REPLACE FUNCTION {E}.asegurar_particion_feature_snapshot(ts TIMESTAMPTZ) RETURNS TEXT
LANGUAGE plpgsql AS $$
DECLARE
    inicio TIMESTAMPTZ := date_trunc('month', ts AT TIME ZONE 'UTC') AT TIME ZONE 'UTC';
    fin    TIMESTAMPTZ := (date_trunc('month', ts AT TIME ZONE 'UTC') + INTERVAL '1 month') AT TIME ZONE 'UTC';
    nombre TEXT := 'feature_snapshot_' || to_char(ts AT TIME ZONE 'UTC', 'YYYYMM');
BEGIN
    IF to_regclass('{E}.' || nombre) IS NULL THEN
        EXECUTE format('CREATE TABLE IF NOT EXISTS {E}.%I PARTITION OF {E}.feature_snapshot '
                       'FOR VALUES FROM (%L) TO (%L)', nombre, inicio, fin);
    END IF;
    RETURN nombre;
END $$;
COMMENT ON FUNCTION {E}.asegurar_particion_feature_snapshot(TIMESTAMPTZ) IS 'Crea (si falta) la partición mensual UTC de feature_snapshot que contiene ts';
SELECT {E}.asegurar_particion_feature_snapshot(now());

ALTER TABLE {E}.execution_log ADD COLUMN traceparent TEXT;
COMMENT ON COLUMN {E}.execution_log.traceparent IS 'W3C traceparent de quien encoló la ejecución (RNF-006: la réplica que la toma continúa la traza)';
"""

# Umbrales nuevos (versión siguiente de threshold_config). Fracciones salvo días y banderas 0/1.
UMBRALES_0004 = [
    ("psi_aviso", 0.10, "§9.4 deriva: PSI a partir del cual se avisa (umbral efectivo = máx. con el ruido p50 de la "
                        "referencia)"),
    ("psi_alerta", 0.25, "§9.4 deriva: PSI de alerta (umbral efectivo = máx. con el ruido p95 de la referencia)"),
    ("cobertura_min", 0.70, "§9.4 cobertura P10-P90 mínima: por debajo el monitoreo queda en alerta"),
    ("cobertura_aviso", 0.75, "§9.4 cobertura P10-P90 de aviso; también es el mínimo de la compuerta de activación"),
    ("cobertura_max", 0.90, "§9.4 cobertura P10-P90 máxima (banda demasiado ancha); máximo de la compuerta"),
    ("wape_aviso", 0.18, "§9.4 WAPE móvil de aviso (antes de la tolerancia wape_max de ALT-010)"),
    ("monitoreo_ventana_dias", 28, "§9.4 días observados de la ventana móvil del monitoreo"),
    ("descartadas_aviso", 0.50, "§9.4 fracción de alertas descartadas de la ventana que genera aviso"),
    ("descartadas_minimo", 5, "§9.4 alertas mínimas en la ventana para evaluar el porcentaje de descartadas"),
    ("reentreno_periodicidad_dias", 28, "RF-018 reentrenar cada N días de datos nuevos (backtest: 48 días > 20 % "
                                        "en 2024 con el modelo congelado)"),
    ("reentreno_dias_degradacion", 3, "RF-018 reentrenar si el WAPE móvil supera wape_max en N ejecuciones seguidas"),
    ("reentreno_en_ciclo", 1, "RF-018 1 = el ciclo diario encola el reentrenamiento cuando la política lo decide"),
    ("sombra_dias", 14, "§9.5/§18 días que el retador predice en sombra antes de la compuerta de activación"),
    ("sesgo_max", 0.05, "RF-019 compuerta: |sesgo| máximo del retador en la ventana de sombra"),
    ("activacion_automatica", 1, "RF-019 1 = el retador que pasa la compuerta se activa (auditado); 0 = espera a un "
                                 "admin"),
    ("reversion_ventana_dias", 7, "§18 rollback: días de datos tras una activación en que se vigila la degradación"),
    ("reversion_minimo_dias", 3, "§18 rollback: días mínimos tras la activación para evaluar la reversión"),
]


def upgrade() -> None:
    op.execute(DDL)
    conexion = op.get_bind()
    version = conexion.execute(sa.text(f"SELECT COALESCE(MAX(version), 0) FROM {E}.threshold_config")).scalar()
    vigentes = {n: (v, d) for n, v, d in conexion.execute(sa.text(
        f"SELECT nombre, valor, descripcion FROM {E}.threshold_config WHERE vigente")).all()}
    for nombre, valor, descripcion in UMBRALES_0004:
        vigentes.setdefault(nombre, (valor, descripcion))
    conexion.execute(sa.text(f"UPDATE {E}.threshold_config SET vigente = false WHERE vigente"))
    for nombre, (valor, descripcion) in vigentes.items():
        conexion.execute(
            sa.text(
                f"INSERT INTO {E}.threshold_config (nombre, valor, descripcion, version, vigente, creado_por, motivo) "
                "VALUES (:n, CAST(:v AS jsonb), :d, :ver, true, 'migracion_0004', "
                "'Monitoreo del modelo (§9.4) y política de aprendizaje continuo (RF-018, RF-019, §9.5)')"
            ),
            {"n": nombre, "v": json.dumps(valor), "d": descripcion, "ver": int(version) + 1},
        )


def downgrade() -> None:
    conexion = op.get_bind()
    conexion.execute(sa.text(f"DELETE FROM {E}.threshold_config WHERE creado_por = 'migracion_0004'"))
    conexion.execute(sa.text(f"DELETE FROM {E}.threshold_config WHERE nombre = ANY(:n)"),
                     {"n": [n for n, _, _ in UMBRALES_0004]})
    hay_vigentes = conexion.execute(sa.text(f"SELECT count(*) FROM {E}.threshold_config WHERE vigente")).scalar()
    if not hay_vigentes:
        conexion.execute(sa.text(
            f"UPDATE {E}.threshold_config SET vigente = true "
            f"WHERE version = (SELECT MAX(version) FROM {E}.threshold_config)"))
    op.execute(f"ALTER TABLE {E}.execution_log DROP COLUMN IF EXISTS traceparent")
    op.execute(f"DROP TABLE IF EXISTS {E}.feature_snapshot CASCADE")
    op.execute(f"DROP FUNCTION IF EXISTS {E}.asegurar_particion_feature_snapshot(TIMESTAMPTZ)")
    op.execute(f"ALTER TABLE {E}.prediction DROP COLUMN IF EXISTS explicacion_local, "
               "DROP COLUMN IF EXISTS ajuste_conformal, DROP COLUMN IF EXISTS p90_modelo, "
               "DROP COLUMN IF EXISTS p10_modelo")
    op.execute(f"DROP TABLE IF EXISTS {E}.model_monitoring CASCADE")
