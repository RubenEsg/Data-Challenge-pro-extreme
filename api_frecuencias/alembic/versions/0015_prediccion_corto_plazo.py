"""Pronósticos de corto plazo: las subidas de los próximos 30, 60 y 120 minutos por ruta, sentido y segmento, con lo
observado hasta el instante (spec v1.5 §2.2, RF-005, RF-006 «guardar la predicción puntual, el límite inferior, el
límite superior y la versión del modelo», §3.1 M3, §9.2 «cada predicción guarda model_id, feature_version,
data_cutoff, generated_at, horizonte y latencia»).

- prediction_corto_plazo: una fila por pronóstico y nivel. Un pronóstico (grupo_id) de una ruta en un instante y un
  horizonte guarda la fila de la ruta entera (nivel «ruta», con la explicación local y la recomendación), las dos
  de sus sentidos (nivel «sentido») y la de cada segmento oficial de 500 m (nivel «segmento»). Cada fila lleva el
  pronóstico (pasajeros = subidas de la ventana), la banda P10-P90, las dos líneas base de §9.1 (promedio por día y
  hora, última semana), el modelo con su versión de variables y su fecha de corte, cuándo se generó y cuánto tardó.
  execution_id dice qué ejecución del ciclo lo generó (nulo si se pidió con POST /predictions/corto-plazo).

Es una tabla aparte de prediction (el modelo horario de siete días, el del plan del día): las dos se consultan por
separado y ninguna cambia a la otra.

Bajada: borra la tabla.

Solo toca el esquema propio ai_frecuencias.

Revision ID: 0015
Revises: 0014
"""
from __future__ import annotations

from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None

E = "ai_frecuencias"
TABLA = "prediction_corto_plazo"

DDL = f"""
CREATE TABLE {E}.{TABLA} (
    prediction_id      UUID             PRIMARY KEY,
    grupo_id           UUID             NOT NULL,
    execution_id       UUID             REFERENCES {E}.execution_log(execution_id) ON DELETE SET NULL,
    ruta               TEXT             NOT NULL,
    idruta             INTEGER          NOT NULL,
    nivel              TEXT             NOT NULL CHECK (nivel IN ('ruta', 'sentido', 'segmento')),
    sentido            TEXT             CHECK (sentido IN ('ida', 'regreso')),
    nro_segmento       INTEGER          CHECK (nro_segmento > 0),
    instante           TIMESTAMPTZ      NOT NULL,
    horizonte_min      INTEGER          NOT NULL CHECK (horizonte_min IN (30, 60, 120)),
    objetivo           TIMESTAMPTZ      NOT NULL,
    fecha              DATE             NOT NULL,
    franja             TEXT,
    pasajeros          DOUBLE PRECISION NOT NULL CHECK (pasajeros >= 0),
    p10                DOUBLE PRECISION,
    p90                DOUBLE PRECISION,
    promedio_dia_hora  DOUBLE PRECISION,
    ultima_semana      DOUBLE PRECISION,
    model_id           TEXT             NOT NULL,
    feature_version    TEXT             NOT NULL,
    data_cutoff        DATE,
    generated_at       TIMESTAMPTZ      NOT NULL,
    latencia_ms        DOUBLE PRECISION,
    explicacion        JSONB            NOT NULL DEFAULT '{{}}'::jsonb,
    variables          JSONB            NOT NULL DEFAULT '{{}}'::jsonb,
    recomendacion      JSONB,
    creado_en          TIMESTAMPTZ      NOT NULL DEFAULT now(),
    CONSTRAINT ck_prediction_corto_plazo_nivel CHECK (
        (nivel = 'ruta' AND sentido IS NULL AND nro_segmento IS NULL)
        OR (nivel = 'sentido' AND sentido IS NOT NULL AND nro_segmento IS NULL)
        OR (nivel = 'segmento' AND sentido IS NOT NULL AND nro_segmento IS NOT NULL)),
    CONSTRAINT ck_prediction_corto_plazo_banda CHECK (p10 IS NULL OR p90 IS NULL OR p10 <= p90)
);
CREATE UNIQUE INDEX ux_prediction_corto_plazo_grupo
    ON {E}.{TABLA} (grupo_id, nivel, COALESCE(sentido, ''), COALESCE(nro_segmento, 0));
CREATE INDEX ix_prediction_corto_plazo_ruta_instante ON {E}.{TABLA} (ruta, instante, horizonte_min, nivel);
CREATE INDEX ix_prediction_corto_plazo_fecha ON {E}.{TABLA} (fecha, nivel);
CREATE INDEX ix_prediction_corto_plazo_generada ON {E}.{TABLA} (generated_at DESC);
CREATE INDEX ix_prediction_corto_plazo_ejecucion ON {E}.{TABLA} (execution_id);
COMMENT ON TABLE {E}.{TABLA} IS
    'Pronóstico de corto plazo (30, 60 y 120 minutos) por ruta, sentido y segmento con lo observado hasta el instante (RF-005, RF-006, §9.2)';
COMMENT ON COLUMN {E}.{TABLA}.pasajeros IS
    'Subidas pronosticadas en la ventana [instante, instante + horizonte) (P50 del modelo de Poisson)';
COMMENT ON COLUMN {E}.{TABLA}.grupo_id IS
    'Un pronóstico de una ruta en un instante y un horizonte: la fila de la ruta, las de sus sentidos y las de sus segmentos';
COMMENT ON COLUMN {E}.{TABLA}.sentido IS
    'Aproximado: ida si el punto medio del segmento cae en la primera mitad de la longitud del ciclo de la ruta (S9)';
"""


def upgrade() -> None:
    op.execute(DDL)


def downgrade() -> None:
    op.execute(f"DROP TABLE IF EXISTS {E}.{TABLA}")


__all__ = ["TABLA", "downgrade", "upgrade"]
