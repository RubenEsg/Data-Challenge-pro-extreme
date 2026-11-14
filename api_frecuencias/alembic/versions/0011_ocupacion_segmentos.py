"""Ocupación actual de los buses por segmento (§10.1 «ocupación actual por segmento, estacionalidad actual, día de la
semana y hora»; §5.2 ALT-002 «ocupación observada»).

timbradas_segmentos.pasajeros no es la ocupación (hallazgo H9), pero las subidas y bajadas por segmento de cada viaje
sí permiten derivarla en la capa propia (§11.1; método en app/servicios/ocupacion.py). El ciclo de frecuencia lee, en
solo lectura, los viajes de las franjas (ruta, fecha, hora de salida) que le entregó la lectura incremental, calcula
la carga a bordo al salir de cada segmento y guarda aquí una fila por ruta, fecha, hora de salida y segmento:

- ocupacion_segmento: viajes medidos, carga media y máxima a bordo, puestos por bus con que se calculó la ocupación,
  ocupación media y máxima, el viaje de la carga máxima, el sentido aproximado del segmento, las dimensiones de §8.3
  (id_dia_semana ISO de la fecha e id_estacionalidad vigente; nula para Sobusa sin la armonización de H1) y la marca
  «critico» en el segmento con la mayor carga media de la franja (el que lee el optimizador y ALT-002). Una franja
  releída se reemplaza completa en la misma transacción del ciclo: nunca queda duplicada ni a medias.
  execution_id dice qué ejecución la calculó (sin llave foránea, como segmento_estadistica_dia, para que borrar una
  ejecución no reescriba sus filas).

Bajada: borra la tabla.

Solo toca el esquema propio ai_frecuencias.

Revision ID: 0011
Revises: 0010
"""
from __future__ import annotations

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None

E = "ai_frecuencias"
TABLA = "ocupacion_segmento"

DDL = f"""
CREATE TABLE {E}.{TABLA} (
    ruta               TEXT             NOT NULL,
    idruta             INTEGER          NOT NULL,
    fecha              DATE             NOT NULL,
    hora               SMALLINT         NOT NULL CHECK (hora BETWEEN 0 AND 23),
    nro_segmento       INTEGER          NOT NULL CHECK (nro_segmento > 0),
    id_segmento        BIGINT           NOT NULL,
    sentido            TEXT             CHECK (sentido IN ('ida', 'regreso')),
    id_dia_semana      SMALLINT         CHECK (id_dia_semana BETWEEN 1 AND 7),
    id_estacionalidad  BIGINT,
    nro_viajes         INTEGER          NOT NULL CHECK (nro_viajes > 0),
    carga_media        DOUBLE PRECISION NOT NULL CHECK (carga_media >= 0),
    carga_max          DOUBLE PRECISION NOT NULL CHECK (carga_max >= 0),
    capacidad          DOUBLE PRECISION NOT NULL CHECK (capacidad > 0),
    ocupacion_media    DOUBLE PRECISION NOT NULL CHECK (ocupacion_media >= 0),
    ocupacion_max      DOUBLE PRECISION NOT NULL CHECK (ocupacion_max >= 0),
    id_viaje_max       BIGINT,
    critico            BOOLEAN          NOT NULL DEFAULT false,
    execution_id       UUID,
    actualizado_en     TIMESTAMPTZ      NOT NULL DEFAULT now(),
    CONSTRAINT pk_ocupacion_segmento PRIMARY KEY (ruta, fecha, hora, nro_segmento)
);
CREATE INDEX ix_ocupacion_segmento_critico ON {E}.{TABLA} (ruta, fecha, hora) WHERE critico;
CREATE INDEX ix_ocupacion_segmento_idruta_fecha ON {E}.{TABLA} (idruta, fecha);
CREATE INDEX ix_ocupacion_segmento_ejecucion ON {E}.{TABLA} (execution_id);
COMMENT ON TABLE {E}.{TABLA} IS
    '§10.1 ocupación actual por segmento: carga a bordo derivada de subidas y bajadas por segmento de cada viaje (H9); la escribe el ciclo de frecuencia';
COMMENT ON COLUMN {E}.{TABLA}.critico IS
    'Segmento con la mayor carga media de la franja (ruta, fecha, hora de salida): el que usan el optimizador y ALT-002';
COMMENT ON COLUMN {E}.{TABLA}.sentido IS
    'Aproximado: ida si el punto medio del segmento cae en la primera mitad de la longitud del ciclo de la ruta';
"""


def upgrade() -> None:
    op.execute(DDL)


def downgrade() -> None:
    op.execute(f"DROP TABLE IF EXISTS {E}.{TABLA}")


__all__ = ["TABLA", "downgrade", "upgrade"]
