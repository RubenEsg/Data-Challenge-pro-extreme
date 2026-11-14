"""Agregación materializada de la capa analítica de segmentos (§6.1, §7.1, RNF-002, RNF-004).

GET /api/v1/segmentos/estadisticas agregaba timbradas_segmentos de la base de Extreme dentro de cada petición (8,8 s en
frío y 11,9 s en caliente sobre la réplica: docs/evidencias/pruebas/k6_volumen.txt). Desde esta versión la agregación
la calcula un trabajo de la cola (tipo «segmentos», app/servicios/segmentos.py) que lee la base de Extreme con el
usuario de solo lectura, por tramos de fechas, y la guarda en el esquema propio:

1. segmento_estadistica_dia: el grano diario segmento × fecha × hora (una fila por segmento, día y hora, con la
   estacionalidad vigente en la fecha y el día ISO). Guarda medidas sumables (viajes, sumas, máximos y mínimos), así
   que cualquier rango de fechas se vuelve a agregar exacto, sin leer la tabla de Extreme. execution_id (sin llave
   foránea, para que borrar una ejecución no reescriba cientos de miles de filas) dice qué refresco escribió la fila.
2. segmento_estadistica: el grano de la respuesta segmento × estacionalidad × día de la semana × hora, con los mismos
   campos y tipos que la agregación directa (promedios redondeados a 3 decimales, totales NUMERIC), e índices para los
   filtros y el orden por omisión. Responde las consultas sin rango de fechas.
3. segmento_estadistica_refresco: la marca de cada refresco terminado (ejecución, modo, cuándo, período cubierto,
   filas, marca de agua de la fuente y huella de los catálogos que fijan las dimensiones). La API la devuelve como
   «actualizado_en».
4. execution_log.tipo admite 'segmentos'. La lista se lee de la restricción vigente y se le agrega el tipo nuevo (la
   bajada lo quita), para no pisar tipos que agreguen otras migraciones encadenadas.

Bajada: borra las tres tablas, las ejecuciones 'segmentos' (con sus intentos) y quita el tipo de la restricción.

Solo toca el esquema propio ai_frecuencias.

Revision ID: 0008
Revises: 0007
"""
from __future__ import annotations

import re

import sqlalchemy as sa

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

E = "ai_frecuencias"
TIPO = "segmentos"
RESTRICCION = "ck_execution_log_tipo"
TABLAS_0008 = ("segmento_estadistica_dia", "segmento_estadistica", "segmento_estadistica_refresco")

DDL = f"""
CREATE TABLE {E}.segmento_estadistica_dia (
    id_segmento        BIGINT   NOT NULL,
    idruta             INTEGER  NOT NULL,
    nro_segmento       INTEGER  NOT NULL,
    fecha              DATE     NOT NULL,
    id_estacionalidad  BIGINT,
    id_dia_semana      SMALLINT NOT NULL CHECK (id_dia_semana BETWEEN 1 AND 7),
    hora               SMALLINT NOT NULL CHECK (hora BETWEEN 0 AND 23),
    nro_viajes         INTEGER  NOT NULL CHECK (nro_viajes > 0),
    suma_subidas       NUMERIC  NOT NULL,
    max_subidas        BIGINT   NOT NULL,
    min_subidas        BIGINT   NOT NULL,
    suma_bajadas       NUMERIC  NOT NULL,
    max_bajadas        BIGINT   NOT NULL,
    min_bajadas        BIGINT   NOT NULL,
    suma_pasajeros     NUMERIC  NOT NULL,
    max_pasajeros      BIGINT   NOT NULL,
    min_pasajeros      BIGINT   NOT NULL,
    execution_id       UUID,
    CONSTRAINT pk_segmento_estadistica_dia PRIMARY KEY (id_segmento, fecha, hora)
);
CREATE INDEX ix_segmento_estadistica_dia_fecha ON {E}.segmento_estadistica_dia (fecha);
CREATE INDEX ix_segmento_estadistica_dia_ruta_fecha ON {E}.segmento_estadistica_dia (idruta, fecha);
COMMENT ON TABLE {E}.segmento_estadistica_dia IS
    '§6.1 grano diario de timbradas_segmentos (viaje × segmento × hora sumado por día); lo escribe el trabajo segmentos';

CREATE TABLE {E}.segmento_estadistica (
    id_segmento        BIGINT   NOT NULL,
    idruta             INTEGER  NOT NULL,
    nro_segmento       INTEGER  NOT NULL,
    id_estacionalidad  BIGINT,
    id_dia_semana      SMALLINT NOT NULL,
    hora               SMALLINT NOT NULL,
    nro_viajes         BIGINT   NOT NULL,
    dias               BIGINT   NOT NULL,
    prom_subidas       NUMERIC  NOT NULL,
    max_subidas        BIGINT   NOT NULL,
    min_subidas        BIGINT   NOT NULL,
    prom_bajadas       NUMERIC  NOT NULL,
    max_bajadas        BIGINT   NOT NULL,
    min_bajadas        BIGINT   NOT NULL,
    prom_pasajeros     NUMERIC  NOT NULL,
    max_pasajeros      BIGINT   NOT NULL,
    min_pasajeros      BIGINT   NOT NULL,
    subidas            NUMERIC  NOT NULL,
    bajadas            NUMERIC  NOT NULL,
    primera_fecha      DATE     NOT NULL,
    ultima_fecha       DATE     NOT NULL
);
CREATE UNIQUE INDEX ux_segmento_estadistica_clave ON {E}.segmento_estadistica
    (id_segmento, COALESCE(id_estacionalidad, -1), id_dia_semana, hora);
CREATE INDEX ix_segmento_estadistica_orden ON {E}.segmento_estadistica
    (idruta, nro_segmento, id_estacionalidad, id_dia_semana, hora, id_segmento);
CREATE INDEX ix_segmento_estadistica_segmento ON {E}.segmento_estadistica (id_segmento);
CREATE INDEX ix_segmento_estadistica_dia_hora ON {E}.segmento_estadistica (id_dia_semana, hora);
COMMENT ON TABLE {E}.segmento_estadistica IS
    '§6.1 promedio, máximo y mínimo por segmento × estacionalidad × día ISO × hora; respuesta de GET /segmentos/estadisticas';

CREATE TABLE {E}.segmento_estadistica_refresco (
    id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    execution_id      UUID REFERENCES {E}.execution_log(execution_id) ON DELETE SET NULL,
    modo              TEXT NOT NULL CHECK (modo IN ('completo', 'incremental', 'rango', 'sin_cambios')),
    actualizado_en    TIMESTAMPTZ NOT NULL DEFAULT now(),
    fecha_min         DATE,
    fecha_max         DATE,
    filas_dia         BIGINT NOT NULL DEFAULT 0,
    filas             BIGINT NOT NULL DEFAULT 0,
    fechas_releidas   INTEGER NOT NULL DEFAULT 0,
    marca_fuente      TIMESTAMPTZ,
    huella_catalogos  TEXT,
    duracion_s        NUMERIC(10, 3)
);
CREATE INDEX ix_segmento_estadistica_refresco_reciente ON {E}.segmento_estadistica_refresco (actualizado_en DESC);
COMMENT ON TABLE {E}.segmento_estadistica_refresco IS
    'Marca de cada refresco terminado de la agregación de segmentos (la API la devuelve como actualizado_en)';
"""


def _tipos_vigentes(conexion) -> list[str]:
    """Tipos de trabajo que admite hoy la restricción de execution_log (en su orden)."""
    definicion = conexion.execute(sa.text(
        "SELECT pg_get_constraintdef(c.oid) FROM pg_constraint c "
        "WHERE c.conname = :n AND c.conrelid = CAST(:t AS regclass)"),
        {"n": RESTRICCION, "t": f"{E}.execution_log"}).scalar()
    return re.findall(r"'([^']+)'", definicion or "")


def _reemplazar_tipos(conexion, tipos: list[str]) -> None:
    lista = ", ".join("'" + re.sub(r"[^a-z_]", "", t) + "'" for t in tipos)
    op.execute(f"ALTER TABLE {E}.execution_log DROP CONSTRAINT IF EXISTS {RESTRICCION}")
    op.execute(f"ALTER TABLE {E}.execution_log ADD CONSTRAINT {RESTRICCION} CHECK (tipo IN ({lista}))")


def upgrade() -> None:
    conexion = op.get_bind()
    tipos = _tipos_vigentes(conexion) or ["frecuencia", "entrenamiento", "respuesta"]
    if TIPO not in tipos:
        _reemplazar_tipos(conexion, [*tipos, TIPO])
    op.execute(DDL)


def downgrade() -> None:
    conexion = op.get_bind()
    for tabla in reversed(TABLAS_0008):
        op.execute(f"DROP TABLE IF EXISTS {E}.{tabla}")
    op.execute(f"DELETE FROM {E}.execution_log WHERE tipo = '{TIPO}'")
    tipos = [t for t in _tipos_vigentes(conexion) if t != TIPO]
    _reemplazar_tipos(conexion, tipos or ["frecuencia", "entrenamiento", "respuesta"])
