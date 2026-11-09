"""Umbrales de las reglas nuevas de alertas versionados en threshold_config (§5.1 «regla de gobierno», RF-009).

La ALT-002 observada (salidas mínimas y persistencia de la ocupación) y el detector de rupturas de comportamiento
(CUSUM de RF-009) leían sus parámetros de los valores por omisión del código (alertas.UMBRALES_POR_DEFECTO): no se
veían en GET /thresholds, no quedaban ligados a umbrales_version y PUT /thresholds los rechazaba por desconocidos.
Esta migración crea una versión nueva del conjunto completo de threshold_config que los agrega, de modo que se
gobiernan igual que los demás (cambio sin recompilar, historial y aprobación por versión).

Los valores están copiados aquí (una migración no depende del código que evoluciona); una prueba verifica que
coinciden con los del código. Si un parámetro ya estaba vigente, se conserva su valor.

Bajada: borra solo las filas que creó esta migración y, si no queda ninguna vigente, vuelve vigente la última
versión anterior. Las versiones creadas después por PUT /thresholds se conservan (son decisiones de la operación).

Solo toca el esquema propio ai_frecuencias.

Revision ID: 0007
Revises: 0006
"""
from __future__ import annotations

import json

import sqlalchemy as sa

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

CREADO_POR = "migracion_0007"
MOTIVO = ("Umbrales de la ALT-002 observada y de la ruptura de comportamiento (RF-009) versionados; antes eran "
          "valores por omisión del código")

# nombre, valor, descripción: los de app/servicios/alertas.py (UMBRALES_POR_DEFECTO) al crear la migración.
UMBRALES_0007 = [
    ("salidas_minimas_ocupacion", 2, "ALT-002 observada: salidas mínimas en la hora para medir la ocupación"),
    ("persistencia_ocupacion_horas", 2, "ALT-002 observada: horas seguidas sobre la ocupación crítica (backtest)"),
    ("ruptura_k", 0.5, "RF-009 ruptura: holgura k del CUSUM (en desviaciones robustas)"),
    ("ruptura_h", 6.0, "RF-009 ruptura: umbral h del CUSUM (backtest de falsas alarmas sin cambio)"),
    ("ruptura_dias_referencia", 28, "RF-009 ruptura: días de referencia para la media y la escala robustas"),
    ("ruptura_cambio_minimo", 0.08, "RF-009 ruptura: cambio medio mínimo del residuo relativo (backtest)"),
    ("ruptura_dias_reinicio", 7, "RF-009 ruptura: días de espera tras detectar, antes de fijar el nivel nuevo"),
]


def upgrade() -> None:
    conexion = op.get_bind()
    version = conexion.execute(sa.text(
        "SELECT COALESCE(MAX(version), 0) FROM ai_frecuencias.threshold_config")).scalar()
    vigentes = {n: (v, d) for n, v, d in conexion.execute(sa.text(
        "SELECT nombre, valor, descripcion FROM ai_frecuencias.threshold_config WHERE vigente")).all()}
    for nombre, valor, descripcion in UMBRALES_0007:
        vigentes.setdefault(nombre, (valor, descripcion))
    conexion.execute(sa.text("UPDATE ai_frecuencias.threshold_config SET vigente = false WHERE vigente"))
    for nombre, (valor, descripcion) in vigentes.items():
        conexion.execute(
            sa.text(
                "INSERT INTO ai_frecuencias.threshold_config "
                "(nombre, valor, descripcion, version, vigente, creado_por, motivo) "
                "VALUES (:n, CAST(:v AS jsonb), :d, :ver, true, :c, :m)"
            ),
            {"n": nombre, "v": json.dumps(valor), "d": descripcion, "ver": int(version) + 1, "c": CREADO_POR,
             "m": MOTIVO},
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
