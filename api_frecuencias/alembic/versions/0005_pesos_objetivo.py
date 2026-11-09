"""Pesos y costos de la función objetivo de §10.2 versionados desde el inicio (§5.1 «regla de gobierno»).

min α·costo_operativo + β·tiempo_espera + γ·penalización_sobreocupación + δ·desviación_frecuencia: hasta ahora los
pesos α, β, γ, δ, el nivel de servicio y los costos regían desde el código (optimizacion.PARAMETROS_OBJETIVO) hasta el
primer PUT /thresholds. Esta migración crea una versión nueva del conjunto completo de threshold_config con esos
valores, de modo que GET /thresholds los muestra (y su historial) desde la instalación, se cambian sin recompilar y
cada recomendación queda ligada a umbrales_version con la fuente «threshold_config vN».

Los valores están copiados aquí (una migración no depende del código que evoluciona); una prueba verifica que
coinciden con los del código. Si un parámetro ya estaba vigente (lo puso un PUT anterior), se conserva su valor.

Bajada: borra solo las filas que creó esta migración y, si no queda ninguna vigente, vuelve vigente la última
versión anterior. Las versiones creadas después por PUT /thresholds se conservan (son decisiones de la operación).

Solo toca el esquema propio ai_frecuencias.

Revision ID: 0005
Revises: 0004
"""
from __future__ import annotations

import json

import sqlalchemy as sa

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

CREADO_POR = "migracion_0005"

# nombre, valor, descripción: los mismos de app/servicios/optimizacion.py (PARAMETROS_OBJETIVO) al crear la migración.
PESOS_0005 = [
    ("peso_costo_operativo", 1.0, "§10.2 α: peso del costo operativo (COP/h) en la función objetivo"),
    ("peso_tiempo_espera", 1.0, "§10.2 β: peso del costo del tiempo de espera de los pasajeros (COP/h)"),
    ("peso_sobreocupacion", 1.0, "§10.2 γ: peso de la penalización por sobreocupación esperada (COP/h)"),
    ("peso_desviacion_frecuencia", 1.0, "§10.2 δ: peso de la desviación frente a la frecuencia programada (COP/h)"),
    ("nivel_servicio", 0.90, "§10.2 nivel de servicio: probabilidad de que la carga crítica quepa en la capacidad "
                             "efectiva; 0,90 = P90 calibrado del modelo"),
    ("costo_bus_hora_cop", 26400.22, "Costo de un bus-hora de conductor (COP 2026, costos/ con fuente; datos/"
                                     "costos_fuente.json)"),
    ("costo_km_cop", 1991.24, "Costo evitable por km recorrido (COP 2026, costos/ con fuente)"),
    ("valor_tiempo_espera_cop_h", 7000.0, "Valor del tiempo de espera de un pasajero (COP por hora; supuesto de D5)"),
    ("penalidad_sobreocupacion_cop", 10000.0, "Penalidad por pasajero esperado por encima de la ocupación crítica "
                                              "(COP; supuesto de D5)"),
    ("costo_cambio_frecuencia_cop", 26400.22, "Costo de apartarse 1 bus/h de la frecuencia programada (COP; supuesto "
                                              "del equipo: 1 bus-hora de conductor por reprogramación)"),
]


def upgrade() -> None:
    conexion = op.get_bind()
    version = conexion.execute(sa.text(
        "SELECT COALESCE(MAX(version), 0) FROM ai_frecuencias.threshold_config")).scalar()
    vigentes = {n: (v, d) for n, v, d in conexion.execute(sa.text(
        "SELECT nombre, valor, descripcion FROM ai_frecuencias.threshold_config WHERE vigente")).all()}
    for nombre, valor, descripcion in PESOS_0005:
        vigentes.setdefault(nombre, (valor, descripcion))
    conexion.execute(sa.text("UPDATE ai_frecuencias.threshold_config SET vigente = false WHERE vigente"))
    for nombre, (valor, descripcion) in vigentes.items():
        conexion.execute(
            sa.text(
                "INSERT INTO ai_frecuencias.threshold_config "
                "(nombre, valor, descripcion, version, vigente, creado_por, motivo) "
                "VALUES (:n, CAST(:v AS jsonb), :d, :ver, true, :c, "
                "'Pesos y costos de la función objetivo de §10.2 versionados desde la instalación (§5.1)')"
            ),
            {"n": nombre, "v": json.dumps(valor), "d": descripcion, "ver": int(version) + 1, "c": CREADO_POR},
        )


def downgrade() -> None:
    conexion = op.get_bind()
    conexion.execute(sa.text("DELETE FROM ai_frecuencias.threshold_config WHERE creado_por = :c"), {"c": CREADO_POR})
    hay_vigentes = conexion.execute(sa.text(
        "SELECT count(*) FROM ai_frecuencias.threshold_config WHERE vigente")).scalar()
    if not hay_vigentes:
        conexion.execute(sa.text(
            "UPDATE ai_frecuencias.threshold_config SET vigente = true "
            "WHERE version = (SELECT MAX(version) FROM ai_frecuencias.threshold_config)"))
