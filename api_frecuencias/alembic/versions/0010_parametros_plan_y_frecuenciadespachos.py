"""Parámetros del plan del día versionados en threshold_config y headway vigente de rutas.frecuenciadespachos en
recommendation (§5.1 «regla de gobierno», §6.1 y §6.2).

1. threshold_config: versión nueva del conjunto completo con los parámetros del MILP de D5 que seguían en el código
   (app/servicios/motor_d5/comun.py, param_d5): tarifa_cop (tarifa neta, 3.182 COP de datos/costos_fuente.json),
   elasticidad (0,5), delta_suavidad (6) y hora_inicio_suavidad (7). Desde aquí el plan del día los lee de la versión
   vigente (app/servicios/optimizacion.py, PARAMETROS_PLAN), GET /thresholds los muestra con su historial, PUT
   /thresholds los cambia sin recompilar y cada plan queda ligado a umbrales_version con la fuente «threshold_config
   vN». Los valores están copiados aquí (una migración no depende del código que evoluciona); una prueba verifica que
   coinciden con param_d5. Si un parámetro ya estaba vigente (lo puso un PUT anterior), se conserva su valor. Los
   ajustes de flota y de ciclo (flota_override, ciclo_override; app/servicios/flota_ciclo.py) no necesitan siembra:
   sin ajuste rige el dato empaquetado.
2. recommendation: frecuenciadespachos_min (el headway vigente de rutas.frecuenciadespachos, en minutos) y
   diferencia_frecuenciadespachos_min (headway recomendado − vigente), junto a frecuencia_actual_min y diferencia_min
   (el intervalo programado observado), que no cambian. Las filas anteriores quedan con las dos columnas nulas.

Bajada: borra solo las filas de threshold_config que creó esta migración y, si no queda ninguna vigente, vuelve vigente
la última versión anterior (las versiones creadas después por PUT /thresholds se conservan: son decisiones de la
operación); quita las dos columnas de recommendation.

Solo toca el esquema propio ai_frecuencias.

Revision ID: 0010
Revises: 0009
"""
from __future__ import annotations

import json

import sqlalchemy as sa

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

E = "ai_frecuencias"
CREADO_POR = "migracion_0010"
MOTIVO = ("Parámetros del plan del día (tarifa, elasticidad y suavidad del MILP de D5) versionados; antes eran valores "
          "del código (motor_d5.comun.param_d5)")

# nombre, valor, descripción: los de app/servicios/optimizacion.py (PARAMETROS_PLAN) y motor_d5.comun.param_d5 con los
# costos con fuente, al crear la migración.
PARAMETROS_0010 = [
    ("tarifa_cop", 3182.0, "Tarifa neta por pasajero (COP 2026): la tarifa pública del Área Metropolitana (3.700) × "
                           "0,86 que retiene el operador (datos/costos_fuente.json). Ingreso perdido del plan del día "
                           "(§10.2) y recaudo de la respuesta del reto"),
    ("elasticidad", 0.5, "Elasticidad de la demanda frente a la oferta del plan del día: fracción de los pasajeros que "
                         "se pierde por unidad relativa de oferta recortada frente a la programada (β estimada ≈ 0,70 "
                         "sin validar en campo; 0,5 por prudencia)"),
    ("delta_suavidad", 6, "Suavidad del plan del día: cambio máximo de salidas por hora entre dos horas seguidas, "
                          "|x_h / f_h - x_(h-1) / f_(h-1)| <= delta_suavidad"),
    ("hora_inicio_suavidad", 7, "Hora desde la que rige la suavidad del plan del día (se aplica a la transición de la "
                                "hora anterior a esta; 21 = sin suavidad)"),
]
# columnas que agrega a recommendation (ayuda de las pruebas)
COLUMNAS_0010 = {
    "frecuenciadespachos_min": "§6.2 headway vigente tomado de la frecuencia de despachos (rutas.frecuenciadespachos, "
                               "minutos)",
    "diferencia_frecuenciadespachos_min": "§6.2 headway recomendado − headway vigente de rutas.frecuenciadespachos "
                                          "(minutos)",
}


def _nueva_version(conexion) -> None:
    version = conexion.execute(sa.text(f"SELECT COALESCE(MAX(version), 0) FROM {E}.threshold_config")).scalar()
    vigentes = {n: (v, d) for n, v, d in conexion.execute(sa.text(
        f"SELECT nombre, valor, descripcion FROM {E}.threshold_config WHERE vigente")).all()}
    for nombre, valor, descripcion in PARAMETROS_0010:
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
    for columna, comentario in COLUMNAS_0010.items():
        op.execute(f"ALTER TABLE {E}.recommendation ADD COLUMN {columna} DOUBLE PRECISION")
        op.execute(f"COMMENT ON COLUMN {E}.recommendation.{columna} IS '{comentario}'")
    _nueva_version(op.get_bind())


def downgrade() -> None:
    conexion = op.get_bind()
    conexion.execute(sa.text(f"DELETE FROM {E}.threshold_config WHERE creado_por = :c"), {"c": CREADO_POR})
    hay_vigentes = conexion.execute(sa.text(f"SELECT count(*) FROM {E}.threshold_config WHERE vigente")).scalar()
    if not hay_vigentes:
        conexion.execute(sa.text(
            f"UPDATE {E}.threshold_config SET vigente = true "
            f"WHERE version = (SELECT MAX(version) FROM {E}.threshold_config)"))
    for columna in reversed(COLUMNAS_0010):
        op.execute(f"ALTER TABLE {E}.recommendation DROP COLUMN IF EXISTS {columna}")


__all__ = ["COLUMNAS_0010", "CREADO_POR", "PARAMETROS_0010", "downgrade", "upgrade"]
