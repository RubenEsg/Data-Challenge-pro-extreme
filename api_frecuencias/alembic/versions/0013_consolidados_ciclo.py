"""Consolidados de Extreme en el ciclo diario: bajadas en el histórico, marca de agua por tabla y tolerancias del
contraste versionadas (§5.2 ALT-008, §6.1, §6.3, §7.3 paso 3, §9.5, §11.2).

1. demanda_observada guarda, además de pasajeros y salidas, lo que trae la lectura integrada demanda_segmentos
   (app/servicios/fuentes.py) de cada franja:
   - bajadas_viajes: Σ numerobajadas de los viajes válidos que salen en esa hora (finalizado 'S', no cancelado, dato
     <= 300, ceros incluidos): la definición de pasajeros aplicada a los descensos (§6.1 «Bajadas: descensos
     consolidados»). Es la que usan ALT-008 y el contraste con timbradas_consolidado;
   - subidas y bajadas: Σ de timbradas_segmentos de los viajes de la franja (lo que escribe el trigger de Extreme);
   - viajes_con_timbradas: cuántos viajes de la franja tienen timbradas (la cobertura de las dos anteriores).
   Las filas que ya existían quedan con las cuatro columnas nulas (la migración no lee la base de Extreme).
2. marca_agua_tabla: la marca de agua y las huellas de la ventana de solape de la lectura incremental de cada tabla
   consolidada (timbradas_consolidado, timbradas_segmentos_anio y timbradas_segmentos_consolidado) por proceso
   (§6.1 «ultima_actualizacion: marca para la lectura incremental»). Como marca_agua_ruta, la deja el ciclo en la
   transacción de sus resultados; execution_id es la ejecución que la movió y, si se borra, la marca se borra con ella.
3. threshold_config: versión nueva del conjunto completo con las tolerancias del contraste de los consolidados con la
   agregación propia (app/servicios/consolidados.py, TOLERANCIAS_POR_DEFECTO). Los valores están copiados aquí (una
   migración no depende del código que evoluciona); una prueba verifica que coinciden. Si un parámetro ya estaba
   vigente, se conserva su valor.

Bajada: borra marca_agua_tabla, las cuatro columnas y solo las filas de threshold_config que creó esta migración (si
no queda ninguna vigente, vuelve vigente la última versión anterior; las versiones creadas después por PUT /thresholds
se conservan).

La subida, antes de leer la versión vigente, y la bajada, antes de borrar sus filas, toman el candado de los
escritores de threshold_config (el de ejecucion.bloquear_umbrales, copiado aquí): un PUT /thresholds de otra réplica
de la API durante el despliegue espera y parte de la versión que deja la migración, en vez de intercalarse con ella.

Solo toca el esquema propio ai_frecuencias.

Revision ID: 0013
Revises: 0012
"""
from __future__ import annotations

import json

import sqlalchemy as sa

from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None

E = "ai_frecuencias"
CREADO_POR = "migracion_0013"
# El candado de transacción de ejecucion.SQL_CANDADO_UMBRALES (una prueba verifica que es el mismo texto).
CANDADO_UMBRALES = "SELECT pg_advisory_xact_lock(hashtext('ai_frecuencias.threshold_config'))"
MOTIVO = ("Tolerancias del contraste de los consolidados de Extreme con la agregación propia (§6.3, §11.2), "
          "versionadas desde su creación")

# nombre, valor, descripción: los de app/servicios/consolidados.py (TOLERANCIAS_POR_DEFECTO) al crear la migración.
UMBRALES_0013 = [
    ("contraste_tolerancia", 0.15, "Contraste de los consolidados de Extreme con la agregación propia (§6.3, §11.2): "
                                   "diferencia relativa de un promedio por viaje o de los viajes por día desde la que "
                                   "se registra la incidencia en data_quality_error (no bloqueante)"),
    ("contraste_tolerancia_grosera", 0.50, "Contraste de los consolidados: diferencia relativa grosera; la incidencia "
                                           "es bloqueante y la llave del consolidado queda fuera del análisis"),
    ("contraste_viajes_minimos", 30, "Contraste de los consolidados: viajes mínimos de cada lado de una llave para "
                                     "comparar sus promedios y sus viajes por día (con menos, la diferencia es ruido)"),
]
# columnas que agrega a demanda_observada (ayuda de las pruebas)
COLUMNAS_0013 = {
    "bajadas_viajes": ("DOUBLE PRECISION", "§6.1 Bajadas: Σ numerobajadas de los viajes válidos de la franja (dato <= "
                                           "300), la definición de pasajeros aplicada a los descensos"),
    "subidas": ("DOUBLE PRECISION", "Σ subidas de timbradas_segmentos de los viajes de la franja (trigger de Extreme)"),
    "bajadas": ("DOUBLE PRECISION", "Σ bajadas de timbradas_segmentos de los viajes de la franja (trigger de Extreme)"),
    "viajes_con_timbradas": ("INTEGER", "Viajes de la franja con timbradas en timbradas_segmentos (cobertura de "
                                        "subidas y bajadas)"),
}

DDL_MARCA = f"""
CREATE TABLE {E}.marca_agua_tabla (
    proceso        TEXT NOT NULL,
    tabla          TEXT NOT NULL,
    marca_agua     TIMESTAMPTZ NOT NULL,
    estado_fuente  JSONB,
    execution_id   UUID REFERENCES {E}.execution_log(execution_id) ON DELETE CASCADE,
    filas_leidas   INTEGER,
    actualizado_en TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (proceso, tabla)
);
COMMENT ON TABLE {E}.marca_agua_tabla IS
    '§6.1: marca de agua (ultima_actualizacion) y huellas de la lectura incremental de cada tabla consolidada de Extreme';
"""


def _nueva_version(conexion) -> None:
    conexion.execute(sa.text(CANDADO_UMBRALES))
    version = conexion.execute(sa.text(f"SELECT COALESCE(MAX(version), 0) FROM {E}.threshold_config")).scalar()
    vigentes = {n: (v, d) for n, v, d in conexion.execute(sa.text(
        f"SELECT nombre, valor, descripcion FROM {E}.threshold_config WHERE vigente")).all()}
    for nombre, valor, descripcion in UMBRALES_0013:
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
    for columna, (tipo, comentario) in COLUMNAS_0013.items():
        op.execute(f"ALTER TABLE {E}.demanda_observada ADD COLUMN {columna} {tipo}")
        op.execute(f"COMMENT ON COLUMN {E}.demanda_observada.{columna} IS '{comentario}'")
    op.execute(DDL_MARCA)
    _nueva_version(op.get_bind())


def downgrade() -> None:
    conexion = op.get_bind()
    conexion.execute(sa.text(CANDADO_UMBRALES))
    conexion.execute(sa.text(f"DELETE FROM {E}.threshold_config WHERE creado_por = :c"), {"c": CREADO_POR})
    hay_vigentes = conexion.execute(sa.text(f"SELECT count(*) FROM {E}.threshold_config WHERE vigente")).scalar()
    if not hay_vigentes:
        conexion.execute(sa.text(
            f"UPDATE {E}.threshold_config SET vigente = true "
            f"WHERE version = (SELECT MAX(version) FROM {E}.threshold_config)"))
    op.execute(f"DROP TABLE IF EXISTS {E}.marca_agua_tabla")
    for columna in reversed(COLUMNAS_0013):
        op.execute(f"ALTER TABLE {E}.demanda_observada DROP COLUMN IF EXISTS {columna}")


__all__ = ["CANDADO_UMBRALES", "COLUMNAS_0013", "CREADO_POR", "UMBRALES_0013", "downgrade", "upgrade"]
