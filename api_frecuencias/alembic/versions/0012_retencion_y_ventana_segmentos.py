"""Retención automática de datos (§18 «Exposición de datos → retención») y huellas de la ventana de solape del refresco
de segmentos (§6.1, §7.1, RNF-004).

1. execution_log.tipo admite 'retencion': la tarea de retención es un trabajo de la cola (app/servicios/retencion.py),
   con reserva, latido, reintento e intentos auditados. La lista se lee de la restricción vigente y se le agrega el
   tipo (la bajada lo quita), como la 0008, para no pisar tipos que agreguen otras migraciones encadenadas.
2. retencion_registro: la bitácora de la tarea, una fila por acción de cada corrida (partición separada y borrada o
   archivada, filas borradas de una tabla, tabla que se conserva por política, acción pospuesta), con el corte, las
   filas, los bytes, la versión de los parámetros y si fue una simulación. No lleva llave foránea a execution_log: la
   propia retención borra ejecuciones viejas y la bitácora de lo que hizo debe sobrevivirlas.
3. threshold_config: versión nueva del conjunto completo con los parámetros de la política (PARAMETROS_0012, copiados
   de app/servicios/retencion.py PARAMETROS; una prueba verifica que coinciden): 13 meses en caliente para la foto de
   variables, los resultados, las alertas cerradas y los registros de ejecución, el modo de las particiones viejas
   (separar y borrar, o separar y archivar) y si la corrida programada aplica la política o solo la simula. Así la
   política se gobierna como cualquier umbral: GET /thresholds la muestra con su historial, PUT /thresholds la cambia
   (rol admin, auditado) y POST /thresholds/{version}/aprobar la aprueba. Si un parámetro ya estaba vigente, se
   conserva su valor.
4. segmento_estadistica_refresco.huellas_solape: las huellas por fecha de la ventana de solape que dejó cada refresco
   de la agregación de segmentos (app/servicios/segmentos_refresco.py). El refresco siguiente compara las de la fuente
   con estas y solo relee las fechas que cambiaron; si ninguna cambió, termina «sin_cambios» sin reescribir nada.

Bajada: quita la columna, borra la bitácora, las ejecuciones 'retencion' (con sus intentos) y el tipo de la
restricción, y las filas de threshold_config que creó esta migración (si no queda ninguna vigente, vuelve vigente la
última versión anterior; las versiones creadas después por PUT /thresholds se conservan: son decisiones de la operación).

Subida y bajada toman primero el candado de los escritores de threshold_config (el de ejecucion.bloquear_umbrales,
copiado aquí, como en las migraciones 0013 y 0014): un PUT /thresholds de otra réplica de la API durante el despliegue
espera y parte de la versión que deja la migración, en vez de intercalarse con ella (dos versiones con el mismo número
o una versión vigente sin los parámetros de la otra).

Solo toca el esquema propio ai_frecuencias.

Revision ID: 0012
Revises: 0011
"""
from __future__ import annotations

import json
import re

import sqlalchemy as sa

from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None

E = "ai_frecuencias"
TIPO = "retencion"
RESTRICCION = "ck_execution_log_tipo"
CREADO_POR = "migracion_0012"
# El candado de transacción de ejecucion.SQL_CANDADO_UMBRALES (una prueba verifica que es el mismo texto).
CANDADO_UMBRALES = "SELECT pg_advisory_xact_lock(hashtext('ai_frecuencias.threshold_config'))"
MOTIVO = ("Política de retención (§18): 13 meses en caliente, particiones mensuales viejas de feature_snapshot con "
          "DETACH y DROP, y resultados, alertas cerradas y registros de ejecución anteriores al corte")
TIPOS_BASE = ["frecuencia", "entrenamiento", "respuesta", "segmentos"]

# nombre, valor, descripción: los de app/servicios/retencion.py (PARAMETROS) al crear la migración
PARAMETROS_0012 = [
    ("retencion_meses_foto", 13, "§18 retención: meses en caliente de feature_snapshot. Las particiones mensuales "
                                 "enteras anteriores al corte se separan (DETACH PARTITION) y se borran (DROP) o se "
                                 "archivan; 0 = no se recorta"),
    ("retencion_meses_resultados", 13, "§18 retención: meses de prediction, recommendation, respuesta_reto y "
                                       "segmento_estadistica_refresco (por su fecha de creación); lo que cuelga de "
                                       "ellas por llave foránea se borra con ellas; 0 = no se recorta"),
    ("retencion_meses_alertas", 13, "§18 retención: meses de las alertas cerradas o descartadas (con su historial) y "
                                    "de notification_log; una alerta abierta nunca se borra; 0 = no se recorta"),
    ("retencion_meses_ejecuciones", 13, "§18 retención: meses de execution_log terminado (con sus intentos, errores "
                                        "de calidad y filas de monitoreo); nunca la que sostiene una marca de agua, un "
                                        "modelo, el histórico validado o un resultado que se conserva, ni la última de "
                                        "cada tipo; 0 = no se recorta"),
    ("retencion_archivar_particiones", 0, "§18 retención: 1 = la partición vieja de feature_snapshot solo se separa y "
                                          "queda como tabla <partición>_archivo para archivarla (pg_dump); 0 = se "
                                          "separa y se borra"),
    ("retencion_aplicar_programada", 1, "§18 retención: 1 = la corrida del planificador aplica la política; 0 = solo "
                                        "la simula y deja el informe en retencion_registro"),
]

DDL = f"""
CREATE TABLE {E}.retencion_registro (
    id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    execution_id      UUID,
    simulado          BOOLEAN NOT NULL,
    grupo             TEXT NOT NULL CHECK (grupo IN ('foto', 'resultados', 'alertas', 'ejecuciones', 'derivada')),
    objeto            TEXT NOT NULL,
    accion            TEXT NOT NULL CHECK (accion IN ('separar_y_borrar', 'separar_y_archivar', 'borrar_filas',
                                                      'conservar', 'pospuesta')),
    corte             TIMESTAMPTZ,
    filas             BIGINT NOT NULL DEFAULT 0,
    bytes             BIGINT,
    umbrales_version  INTEGER,
    detalle           JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    creado_en         TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_retencion_registro_reciente ON {E}.retencion_registro (creado_en DESC, id DESC);
CREATE INDEX ix_retencion_registro_ejecucion ON {E}.retencion_registro (execution_id);
COMMENT ON TABLE {E}.retencion_registro IS
    '§18 retención: bitácora de la tarea de retención, una fila por acción de cada corrida (simulada o aplicada)';
COMMENT ON COLUMN {E}.retencion_registro.execution_id IS
    'Corrida que dejó la fila (sin llave foránea: la bitácora sobrevive a la retención de execution_log)';

ALTER TABLE {E}.segmento_estadistica_refresco ADD COLUMN huellas_solape JSONB;
COMMENT ON COLUMN {E}.segmento_estadistica_refresco.huellas_solape IS
    'Huellas por fecha de la ventana de solape (marca - FUENTE_SOLAPE_MIN): el refresco siguiente solo relee las '
    'fechas cuyas huellas cambiaron';
"""


def _tipos_vigentes(conexion) -> list[str]:
    """Tipos de trabajo que admite hoy la restricción de execution_log (en su orden)."""
    definicion = conexion.execute(sa.text(
        "SELECT pg_get_constraintdef(c.oid) FROM pg_constraint c "
        "WHERE c.conname = :n AND c.conrelid = CAST(:t AS regclass)"),
        {"n": RESTRICCION, "t": f"{E}.execution_log"}).scalar()
    return re.findall(r"'([^']+)'", definicion or "")


def _reemplazar_tipos(tipos: list[str]) -> None:
    lista = ", ".join("'" + re.sub(r"[^a-z_]", "", t) + "'" for t in tipos)
    op.execute(f"ALTER TABLE {E}.execution_log DROP CONSTRAINT IF EXISTS {RESTRICCION}")
    op.execute(f"ALTER TABLE {E}.execution_log ADD CONSTRAINT {RESTRICCION} CHECK (tipo IN ({lista}))")


def _nueva_version(conexion) -> None:
    version = conexion.execute(sa.text(f"SELECT COALESCE(MAX(version), 0) FROM {E}.threshold_config")).scalar()
    vigentes = {n: (v, d) for n, v, d in conexion.execute(sa.text(
        f"SELECT nombre, valor, descripcion FROM {E}.threshold_config WHERE vigente")).all()}
    for nombre, valor, descripcion in PARAMETROS_0012:
        vigentes.setdefault(nombre, (valor, descripcion))
    conexion.execute(sa.text(f"UPDATE {E}.threshold_config SET vigente = false WHERE vigente"))
    for nombre, (valor, descripcion) in vigentes.items():
        conexion.execute(
            sa.text(f"INSERT INTO {E}.threshold_config (nombre, valor, descripcion, version, vigente, creado_por, "
                    "motivo) VALUES (:n, CAST(:v AS jsonb), :d, :ver, true, :c, :m)"),
            {"n": nombre, "v": json.dumps(valor), "d": descripcion, "ver": int(version) + 1, "c": CREADO_POR,
             "m": MOTIVO},
        )


def upgrade() -> None:
    conexion = op.get_bind()
    conexion.execute(sa.text(CANDADO_UMBRALES))       # antes de leer la versión vigente (bloquear_umbrales)
    tipos = _tipos_vigentes(conexion) or list(TIPOS_BASE)
    if TIPO not in tipos:
        _reemplazar_tipos([*tipos, TIPO])
    op.execute(DDL)
    _nueva_version(conexion)


def downgrade() -> None:
    conexion = op.get_bind()
    conexion.execute(sa.text(CANDADO_UMBRALES))       # antes de tocar threshold_config (bloquear_umbrales)
    conexion.execute(sa.text(f"DELETE FROM {E}.threshold_config WHERE creado_por = :c"), {"c": CREADO_POR})
    hay_vigentes = conexion.execute(sa.text(f"SELECT count(*) FROM {E}.threshold_config WHERE vigente")).scalar()
    if not hay_vigentes:
        conexion.execute(sa.text(
            f"UPDATE {E}.threshold_config SET vigente = true "
            f"WHERE version = (SELECT MAX(version) FROM {E}.threshold_config)"))
    op.execute(f"ALTER TABLE {E}.segmento_estadistica_refresco DROP COLUMN IF EXISTS huellas_solape")
    op.execute(f"DROP TABLE IF EXISTS {E}.retencion_registro")
    op.execute(f"DELETE FROM {E}.execution_log WHERE tipo = '{TIPO}'")
    tipos = [t for t in _tipos_vigentes(conexion) if t != TIPO]
    _reemplazar_tipos(tipos or list(TIPOS_BASE))


__all__ = ["CANDADO_UMBRALES", "CREADO_POR", "PARAMETROS_0012", "TIPO", "downgrade", "upgrade"]
