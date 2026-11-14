"""Mínimo de probabilidad de ALT-003 de pronóstico versionado en threshold_config (§5.1 «regla de gobierno», §5.2,
§18 «Alertas excesivas»).

ALT-003 (frecuencia insuficiente) se emitía con solo el nivel de servicio del optimizador: la frecuencia actual no
cubre la carga crítica de diseño (cuantil 0,90), es decir, P(carga crítica > capacidad efectiva) > 0,10. En el backtest
del ciclo de las 6:00 su precisión quedaba bajo la tasa base de todas las franjas (lift 0,75). El diagnóstico
(scripts/variantes_alt003.py, docs/evidencias/alertas/backtest_alertas_pronostico.md) muestra que ALT-003 nunca se
emite donde sale ALT-001 (§18: va incluida en ella), así que su tasa base es la de las franjas donde puede emitirse; y
el mínimo de probabilidad se eligió en una ventana de validación (15/09 a 31/10/2025) estrictamente anterior a la de
evaluación (01/11 a 31/12/2025), sin fuga: 0,30.

Esta migración crea una versión nueva del conjunto completo de threshold_config con alt003_probabilidad_minima. La
versión nace PROPUESTA (aprobado_por nulo): la aprueba el área operativa con POST /thresholds/{version}/aprobar. El
valor está copiado aquí (una migración no depende del código que evoluciona); una prueba verifica que coincide con el
de alertas.UMBRALES_POR_DEFECTO. Si el parámetro ya estaba vigente (lo puso un PUT anterior), se conserva su valor.

Bajada: borra solo las filas que creó esta migración y, si no queda ninguna vigente, vuelve vigente la última
versión anterior. Las versiones creadas después por PUT /thresholds se conservan (son decisiones de la operación).

Subida y bajada toman primero el candado de los escritores de threshold_config (el de ejecucion.bloquear_umbrales,
copiado aquí): un PUT /thresholds de otra réplica de la API durante el despliegue espera y parte de la versión que deja
la migración, en vez de intercalarse con ella.

Solo toca el esquema propio ai_frecuencias.

Revision ID: 0014
Revises: 0013
"""
from __future__ import annotations

import json

import sqlalchemy as sa

from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None

E = "ai_frecuencias"
CREADO_POR = "migracion_0014"
# El candado de transacción de ejecucion.SQL_CANDADO_UMBRALES (una prueba verifica que es el mismo texto).
CANDADO_UMBRALES = "SELECT pg_advisory_xact_lock(hashtext('ai_frecuencias.threshold_config'))"
MOTIVO = ("ALT-003 de pronóstico: mínimo de probabilidad de superar la capacidad efectiva elegido sin fuga "
          "(validación 15/09-31/10/2025, evaluación 11-12/2025; docs/evidencias/alertas/backtest_alertas_pronostico.md)")

# nombre, valor, descripción: el de app/servicios/alertas.py (UMBRALES_POR_DEFECTO) al crear la migración.
UMBRALES_0014 = [
    ("alt003_probabilidad_minima", 0.30,
     "ALT-003: probabilidad mínima de que la carga crítica supere la capacidad efectiva de la frecuencia actual "
     "(capacidad × ocupación objetivo máxima) para alertar; 0,10 = solo el nivel de servicio 0,90 del optimizador "
     "(elegida sin fuga: scripts/variantes_alt003.py)"),
]


def upgrade() -> None:
    conexion = op.get_bind()
    conexion.execute(sa.text(CANDADO_UMBRALES))
    version = conexion.execute(sa.text(f"SELECT COALESCE(MAX(version), 0) FROM {E}.threshold_config")).scalar()
    vigentes = {n: (v, d) for n, v, d in conexion.execute(sa.text(
        f"SELECT nombre, valor, descripcion FROM {E}.threshold_config WHERE vigente")).all()}
    for nombre, valor, descripcion in UMBRALES_0014:
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
