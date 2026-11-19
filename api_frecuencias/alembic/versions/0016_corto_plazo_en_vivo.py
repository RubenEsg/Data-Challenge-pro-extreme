"""El pronóstico de corto plazo dentro del ciclo: lo leído cada 15 minutos, su calidad, su recomendación y su ciclo de
vida (spec v1.5 RF-004, RF-005, RF-013, RF-018, RF-019, §7.3 pasos 2 a 7, §8.3, §9.2, §9.5, §11.2).

1. subidas_15min, salidas_15min y lectura_15min: lo que cada ciclo lee para el modelo de corto plazo (subidas por
   ruta, día, bloque de 15 minutos y segmento oficial; salidas por bloque; y, por ruta y día, hasta qué instante se
   leyó, de qué fuente, en qué ejecución y cuántas celdas se excluyeron por calidad). app/servicios/panel_corto_plazo.py.
2. recommendation: el origen 'corto_plazo' (la recomendación de §10.2 hecha con el pronóstico de corto plazo de la
   ventana) y prediction_corto_plazo_id, la fila de la ruta de ese pronóstico.
3. prediction_corto_plazo: las dimensiones de §8.3 que ya tienen las demás tablas (idempresa, idproceso,
   id_dia_semana, id_estacionalidad) y el id_segmento de rutas_segmentos de cada segmento.
4. model_registry: la familia del modelo ('horario', el del plan del día siguiente; 'corto_plazo', el de 30, 60 y 120
   minutos) y un activo POR FAMILIA (antes, un solo activo en toda la tabla).
5. threshold_config: cp_tope_subidas_bloque_segmento (VAL-009), versión nueva del conjunto completo, como la 0014; si el
   parámetro ya estaba vigente, se conserva su valor.

Bajada: deshace cada paso (las filas de recommendation con origen 'corto_plazo' y los modelos de corto plazo del
registro se borran; las versiones de threshold_config creadas por esta migración también).

Solo toca el esquema propio ai_frecuencias.

Revision ID: 0016
Revises: 0015
"""
from __future__ import annotations

import json

import sqlalchemy as sa

from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None

E = "ai_frecuencias"
CREADO_POR = "migracion_0016"
CANDADO_UMBRALES = "SELECT pg_advisory_xact_lock(hashtext('ai_frecuencias.threshold_config'))"
MOTIVO = ("Corto plazo (VAL-009): tope de subidas de un segmento en un bloque de 15 minutos; por encima, la celda se "
          "excluye del pronóstico y queda en data_quality_error (app/servicios/panel_corto_plazo.py)")
# nombre, valor, descripción: el de app/servicios/panel_corto_plazo.py al crear la migración (una prueba lo verifica).
UMBRALES_0016 = [
    ("cp_tope_subidas_bloque_segmento", 1000.0,
     "Corto plazo (VAL-009): subidas máximas creíbles de un segmento de 500 m en un bloque de 15 minutos; una celda por "
     "encima se excluye del pronóstico y queda en data_quality_error"),
]

DDL = f"""
CREATE TABLE {E}.subidas_15min (
    idruta        INTEGER          NOT NULL,
    fecha         DATE             NOT NULL,
    bloque        SMALLINT         NOT NULL CHECK (bloque BETWEEN 0 AND 95),
    nro_segmento  SMALLINT         NOT NULL CHECK (nro_segmento > 0),
    subidas       DOUBLE PRECISION NOT NULL CHECK (subidas >= 0),
    PRIMARY KEY (idruta, fecha, bloque, nro_segmento)
);
CREATE TABLE {E}.salidas_15min (
    idruta   INTEGER          NOT NULL,
    fecha    DATE             NOT NULL,
    bloque   SMALLINT         NOT NULL CHECK (bloque BETWEEN 0 AND 95),
    salidas  DOUBLE PRECISION NOT NULL CHECK (salidas >= 0),
    PRIMARY KEY (idruta, fecha, bloque)
);
CREATE TABLE {E}.lectura_15min (
    idruta        INTEGER          NOT NULL,
    fecha         DATE             NOT NULL,
    hasta         TIMESTAMPTZ      NOT NULL,
    fuente        TEXT             NOT NULL,
    execution_id  UUID             REFERENCES {E}.execution_log(execution_id) ON DELETE SET NULL,
    celdas        INTEGER          NOT NULL DEFAULT 0,
    subidas       DOUBLE PRECISION NOT NULL DEFAULT 0,
    excluidas     INTEGER          NOT NULL DEFAULT 0,
    leido_en      TIMESTAMPTZ      NOT NULL DEFAULT now(),
    PRIMARY KEY (idruta, fecha)
);
CREATE INDEX ix_lectura_15min_ejecucion ON {E}.lectura_15min (execution_id);
COMMENT ON TABLE {E}.subidas_15min IS
    'Subidas por ruta, día, bloque de 15 minutos y segmento oficial que leyó el ciclo para el pronóstico de corto plazo (RF-005, RF-013)';
COMMENT ON TABLE {E}.salidas_15min IS 'Viajes que iniciaron en cada bloque de 15 minutos (la oferta ya observada)';
COMMENT ON TABLE {E}.lectura_15min IS
    'Por ruta y día: hasta qué instante se leyó, de qué fuente, en qué ejecución y cuántas celdas se excluyeron (VAL-009)';

ALTER TABLE {E}.recommendation DROP CONSTRAINT IF EXISTS ck_recommendation_origen;
ALTER TABLE {E}.recommendation ADD CONSTRAINT ck_recommendation_origen
    CHECK (origen IN ('franja', 'plan_dia', 'corto_plazo'));
ALTER TABLE {E}.recommendation ADD COLUMN prediction_corto_plazo_id UUID
    REFERENCES {E}.prediction_corto_plazo(prediction_id) ON DELETE SET NULL;
CREATE INDEX ix_recommendation_corto_plazo ON {E}.recommendation (prediction_corto_plazo_id)
    WHERE prediction_corto_plazo_id IS NOT NULL;
COMMENT ON COLUMN {E}.recommendation.prediction_corto_plazo_id IS
    'origen = corto_plazo: la fila de la ruta del pronóstico de corto plazo con que se hizo la recomendación';

ALTER TABLE {E}.prediction_corto_plazo
    ADD COLUMN idempresa INTEGER, ADD COLUMN idproceso TEXT, ADD COLUMN id_dia_semana INTEGER,
    ADD COLUMN id_estacionalidad INTEGER, ADD COLUMN id_segmento BIGINT;
COMMENT ON COLUMN {E}.prediction_corto_plazo.id_segmento IS 'rutas_segmentos.id del segmento (nivel segmento)';

ALTER TABLE {E}.model_registry ADD COLUMN familia TEXT NOT NULL DEFAULT 'horario'
    CHECK (familia IN ('horario', 'corto_plazo'));
DROP INDEX IF EXISTS {E}.ux_model_registry_un_activo;
CREATE UNIQUE INDEX ux_model_registry_un_activo ON {E}.model_registry (familia) WHERE estado = 'activo';
COMMENT ON COLUMN {E}.model_registry.familia IS
    'horario = el modelo del plan del día siguiente (siete días de antelación); corto_plazo = el de 30, 60 y 120 minutos';
"""

DDL_BAJADA = f"""
DELETE FROM {E}.model_registry WHERE familia = 'corto_plazo';
DROP INDEX IF EXISTS {E}.ux_model_registry_un_activo;
CREATE UNIQUE INDEX ux_model_registry_un_activo ON {E}.model_registry (estado) WHERE estado = 'activo';
ALTER TABLE {E}.model_registry DROP COLUMN IF EXISTS familia;
ALTER TABLE {E}.prediction_corto_plazo
    DROP COLUMN IF EXISTS idempresa, DROP COLUMN IF EXISTS idproceso, DROP COLUMN IF EXISTS id_dia_semana,
    DROP COLUMN IF EXISTS id_estacionalidad, DROP COLUMN IF EXISTS id_segmento;
DELETE FROM {E}.recommendation WHERE origen = 'corto_plazo';
DROP INDEX IF EXISTS {E}.ix_recommendation_corto_plazo;
ALTER TABLE {E}.recommendation DROP COLUMN IF EXISTS prediction_corto_plazo_id;
ALTER TABLE {E}.recommendation DROP CONSTRAINT IF EXISTS ck_recommendation_origen;
ALTER TABLE {E}.recommendation ADD CONSTRAINT ck_recommendation_origen CHECK (origen IN ('franja', 'plan_dia'));
DROP TABLE IF EXISTS {E}.lectura_15min;
DROP TABLE IF EXISTS {E}.salidas_15min;
DROP TABLE IF EXISTS {E}.subidas_15min;
"""


def upgrade() -> None:
    op.execute(DDL)
    conexion = op.get_bind()
    conexion.execute(sa.text(CANDADO_UMBRALES))
    version = conexion.execute(sa.text(f"SELECT COALESCE(MAX(version), 0) FROM {E}.threshold_config")).scalar()
    vigentes = {n: (v, d) for n, v, d in conexion.execute(sa.text(
        f"SELECT nombre, valor, descripcion FROM {E}.threshold_config WHERE vigente")).all()}
    if all(nombre in vigentes for nombre, _, _ in UMBRALES_0016):
        return
    for nombre, valor, descripcion in UMBRALES_0016:
        vigentes.setdefault(nombre, (valor, descripcion))
    conexion.execute(sa.text(f"UPDATE {E}.threshold_config SET vigente = false WHERE vigente"))
    for nombre, (valor, descripcion) in vigentes.items():
        conexion.execute(
            sa.text(f"INSERT INTO {E}.threshold_config (nombre, valor, descripcion, version, vigente, creado_por, "
                    "motivo) VALUES (:n, CAST(:v AS jsonb), :d, :ver, true, :c, :m)"),
            {"n": nombre, "v": json.dumps(valor), "d": descripcion, "ver": int(version) + 1, "c": CREADO_POR,
             "m": MOTIVO},
        )


def downgrade() -> None:
    conexion = op.get_bind()
    conexion.execute(sa.text(CANDADO_UMBRALES))
    conexion.execute(sa.text(f"DELETE FROM {E}.threshold_config WHERE creado_por = :c"), {"c": CREADO_POR})
    hay_vigentes = conexion.execute(sa.text(f"SELECT count(*) FROM {E}.threshold_config WHERE vigente")).scalar()
    if not hay_vigentes:
        conexion.execute(sa.text(
            f"UPDATE {E}.threshold_config SET vigente = true "
            f"WHERE version = (SELECT MAX(version) FROM {E}.threshold_config)"))
    op.execute(DDL_BAJADA)
