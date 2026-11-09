"""Estructura completa de la alerta (especificación v1.5, §5.3, §8.1, §9.4 y §18) y umbrales afinados (§5.1).

ai_frecuencias.alert ya tenía identificador, código, empresa, ruta, sentido, viaje, conductor, vehículo, detección,
ventana, horizonte, severidad, estado, observado, esperado, umbral, puntaje, explicación, variables, recomendación,
usuario asignado y comentarios (la bitácora es alert_history). Esta migración agrega lo que faltaba:

- origen: de dónde sale la alerta (pronóstico, dato observado, calidad del dato o modelo).
- tendencia, tendencia_pendiente y serie_reciente: §9.4 exige mostrar la tendencia junto al valor real, el esperado,
  el umbral y la recomendación; serie_reciente guarda los valores real/esperado de las horas analizadas.
- probabilidad y metodo_puntaje: §5.3 «probabilidad o puntuación de anomalía»; metodo_puntaje dice cómo se calculó
  el puntaje (exceso relativo, z robusto, probabilidad con la banda P10-P90 calibrada…), para que no sea opaco.
- variables_influyentes: lista ordenada [{variable, valor, efecto}] (SHAP del pronóstico o insumos de la regla).
- ubicacion geography(Point,4326) con índice GiST (§8.1) para las alertas ligadas a un lugar (p. ej. el punto de
  despacho de la ruta en ALT-006). Sin PostGIS (despliegue sin Docker) se guarda como EWKT en TEXT, sin índice.
- conductor solo admite una referencia SEUDONIMIZADA (§18 «Exposición de datos»): HMAC-SHA256 con un secreto del
  entorno (SEUDONIMO_SECRETO), con el formato cnd_<24 hex>, o NULL. Nunca un nombre ni un documento: un CHECK lo
  impide en la base. Los valores previos que no cumplan el formato se borran (no debía haberlos).
- índice (codigo, ruta, ventana_inicio) para la deduplicación por episodio y la persistencia.

Umbrales: crea una versión nueva de threshold_config (la anterior queda en el histórico) con los parámetros de las
reglas observadas ALT-005..ALT-009 y los valores afinados con scripts/backtest_alertas.py sobre 2025
(docs/evidencias/alertas/backtest_alertas.md).

Solo toca el esquema propio ai_frecuencias (y crea la extensión postgis si falta y el rol puede hacerlo).

Revision ID: 0003
Revises: 0002
"""
from __future__ import annotations

import json
import logging

import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

E = "ai_frecuencias"
LOG = logging.getLogger("alembic.0003")
PATRON_CONDUCTOR = "^cnd_[0-9a-f]{24}$"

# Parámetros nuevos o afinados (versión siguiente de threshold_config). Los valores salen del backtest de 2025.
UMBRALES_0003 = [
    ("persistencia_horas", 2, "ALT-005/ALT-007: horas seguidas (mismo sentido) que debe sostenerse la desviación "
                              "antes de alertar; backtest 2025"),
    ("alt005_exigir_p10", 1, "ALT-005: 1 = además de caer bajo (1 - caida_demanda) × patrón, la demanda real debe "
                             "quedar bajo el P10 calibrado del modelo"),
    ("z_anomalia", 3.5, "ALT-008: |z robusto| (mediana y 1,4826 × MAD del mismo tipo de día, 8 semanas previas); "
                        "afinado con el backtest 2025 (antes 3,0)"),
    ("escala_minima_z", 0.05, "ALT-008: escala mínima del z robusto como fracción de la mediana (evita z enormes "
                              "con MAD casi nula)"),
    ("semanas_referencia", 8, "ALT-008: semanas previas que forman la referencia del mismo tipo de día"),
    ("minimo_dias_referencia", 4, "ALT-008: días mínimos del mismo tipo en la referencia para evaluar"),
    ("tolerancia_salidas", 0.5, "ALT-006: déficit relativo de salidas tolerado en una hora frente a 60 / intervalo "
                                "programado; afinado con el backtest 2025 (antes 0,20)"),
    ("salidas_minimas_esperadas", 2, "ALT-006: no se evalúa el déficit por conteo en horas con menos salidas "
                                     "esperadas (bordes del servicio)"),
    ("pendiente_tendencia", 0.05, "§9.4 tendencia: cambio relativo por hora a partir del cual la serie se declara "
                                  "al alza o a la baja"),
]


def _tiene_postgis(conexion) -> str | None:
    """Esquema donde vive postgis (None si no está ni se puede instalar)."""
    esquema = conexion.execute(sa.text(
        "SELECT n.nspname FROM pg_extension e JOIN pg_namespace n ON n.oid = e.extnamespace "
        "WHERE e.extname = 'postgis'")).scalar()
    if esquema:
        return esquema
    disponible = conexion.execute(sa.text(
        "SELECT 1 FROM pg_available_extensions WHERE name = 'postgis'")).scalar()
    if not disponible:
        return None
    try:
        with conexion.begin_nested():
            conexion.execute(sa.text("CREATE EXTENSION IF NOT EXISTS postgis"))
    except DBAPIError as exc:  # sin privilegio: lo instala el responsable de la base
        LOG.warning("No se pudo crear la extensión postgis (%s); ubicacion queda como EWKT en TEXT", exc.orig)
        return None
    return conexion.execute(sa.text(
        "SELECT n.nspname FROM pg_extension e JOIN pg_namespace n ON n.oid = e.extnamespace "
        "WHERE e.extname = 'postgis'")).scalar()


def upgrade() -> None:
    conexion = op.get_bind()
    esquema_postgis = _tiene_postgis(conexion)
    tipo_ubicacion = f"{esquema_postgis}.geography(Point,4326)" if esquema_postgis else "TEXT"

    # §18: ningún dato personal del conductor en claro; lo que no sea un seudónimo se borra antes del CHECK.
    op.execute(f"UPDATE {E}.alert SET conductor = NULL WHERE conductor IS NOT NULL "
               f"AND conductor !~ '{PATRON_CONDUCTOR}'")
    op.execute(f"""
ALTER TABLE {E}.alert
    ADD COLUMN origen                TEXT NOT NULL DEFAULT 'pronostico'
                                     CHECK (origen IN ('pronostico','observado','calidad_datos','modelo')),
    ADD COLUMN tendencia             TEXT CHECK (tendencia IN ('al_alza','a_la_baja','estable','sin_datos')),
    ADD COLUMN tendencia_pendiente   DOUBLE PRECISION,
    ADD COLUMN serie_reciente        JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN probabilidad          DOUBLE PRECISION CHECK (probabilidad IS NULL OR probabilidad BETWEEN 0 AND 1),
    ADD COLUMN metodo_puntaje        TEXT,
    ADD COLUMN variables_influyentes JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN ubicacion             {tipo_ubicacion},
    ADD CONSTRAINT ck_alert_conductor_seudonimo CHECK (conductor IS NULL OR conductor ~ '{PATRON_CONDUCTOR}');

CREATE INDEX ix_alert_codigo_ruta_ventana ON {E}.alert (codigo, ruta, ventana_inicio DESC);
CREATE INDEX ix_alert_origen_estado ON {E}.alert (origen, estado, detectada_en DESC);

COMMENT ON TABLE {E}.alert IS 'Alertas ALT-001..ALT-010 (§5.2) con la estructura obligatoria de §5.3; bitácora en alert_history';
COMMENT ON COLUMN {E}.alert.alert_id IS '§5.3 identificador único';
COMMENT ON COLUMN {E}.alert.codigo IS '§5.3 código de alerta (catálogo §5.2)';
COMMENT ON COLUMN {E}.alert.empresa IS '§5.3 empresa operadora';
COMMENT ON COLUMN {E}.alert.ruta IS '§5.3 ruta (nombre del catálogo; id_ruta en variables cuando aplica)';
COMMENT ON COLUMN {E}.alert.sentido IS '§5.3 sentido del recorrido, cuando aplique';
COMMENT ON COLUMN {E}.alert.viaje IS '§5.3 viaje: progvehiculos.idprogramacion, cuando aplique';
COMMENT ON COLUMN {E}.alert.conductor IS '§5.3/§18 referencia SEUDONIMIZADA del conductor (HMAC-SHA256 con secreto del entorno, cnd_<24 hex>) o NULL; nunca nombre ni documento';
COMMENT ON COLUMN {E}.alert.vehiculo IS '§5.3 vehículo (identificador interno), cuando aplique';
COMMENT ON COLUMN {E}.alert.detectada_en IS '§5.3 fecha y hora de detección (UTC; se presenta en America/Bogota)';
COMMENT ON COLUMN {E}.alert.ventana_inicio IS '§5.3 inicio de la ventana analizada';
COMMENT ON COLUMN {E}.alert.ventana_fin IS '§5.3 fin de la ventana analizada';
COMMENT ON COLUMN {E}.alert.horizonte_min IS '§5.3 horizonte de predicción en minutos (0 = dato observado)';
COMMENT ON COLUMN {E}.alert.severidad IS '§5.3 severidad: informativa, preventiva o critica';
COMMENT ON COLUMN {E}.alert.estado IS '§5.3 estado: nueva, reconocida, asignada, cerrada o descartada';
COMMENT ON COLUMN {E}.alert.observado IS '§5.3/§9.4 valor observado (real)';
COMMENT ON COLUMN {E}.alert.esperado IS '§5.3/§9.4 valor esperado';
COMMENT ON COLUMN {E}.alert.umbral IS '§5.3/§9.4 umbral aplicado (versión en variables.umbrales_version)';
COMMENT ON COLUMN {E}.alert.puntaje IS '§5.3 puntuación de anomalía 0..1 (0,5 en el umbral); método en metodo_puntaje';
COMMENT ON COLUMN {E}.alert.probabilidad IS '§5.3 probabilidad del evento (p. ej. demanda > capacidad con la banda P10-P90 calibrada), cuando aplique';
COMMENT ON COLUMN {E}.alert.metodo_puntaje IS 'Cómo se calculó puntaje/probabilidad (alertas nunca opacas, §9.4)';
COMMENT ON COLUMN {E}.alert.explicacion IS '§5.3 explicación en lenguaje operativo';
COMMENT ON COLUMN {E}.alert.variables IS 'Insumos cuantitativos de la regla activada (RF-015)';
COMMENT ON COLUMN {E}.alert.variables_influyentes IS '§5.3 variables influyentes ordenadas [{{variable, valor, efecto}}]';
COMMENT ON COLUMN {E}.alert.tendencia IS '§9.4 tendencia de la serie analizada: al_alza, a_la_baja, estable o sin_datos';
COMMENT ON COLUMN {E}.alert.tendencia_pendiente IS '§9.4 cambio relativo por hora de la serie analizada';
COMMENT ON COLUMN {E}.alert.serie_reciente IS '§9.4 valores real/esperado de las horas analizadas';
COMMENT ON COLUMN {E}.alert.recomendacion IS '§5.3 recomendación (acción sugerida de §5.2)';
COMMENT ON COLUMN {E}.alert.asignado_a IS '§5.3 usuario asignado';
COMMENT ON COLUMN {E}.alert.comentarios IS '§5.3 comentarios; la bitácora de cambios está en alert_history';
COMMENT ON COLUMN {E}.alert.origen IS 'Origen: pronostico (ALT-001..004), observado (ALT-005..008), calidad_datos (ALT-009) o modelo (ALT-010)';
COMMENT ON COLUMN {E}.alert.ubicacion IS '§8.1 lugar de la alerta (geography Point 4326, índice GiST), cuando aplique';
COMMENT ON COLUMN {E}.alert.clave_dedup IS '§18 deduplicación: una sola alerta abierta por clave (código, ruta, ventana o episodio)';
""")
    if esquema_postgis:
        op.execute(f"CREATE INDEX ix_alert_ubicacion ON {E}.alert USING GIST (ubicacion)")

    version = conexion.execute(sa.text(f"SELECT COALESCE(MAX(version), 0) FROM {E}.threshold_config")).scalar()
    vigentes = {n: (v, d) for n, v, d in conexion.execute(sa.text(
        f"SELECT nombre, valor, descripcion FROM {E}.threshold_config WHERE vigente")).all()}
    for nombre, valor, descripcion in UMBRALES_0003:
        vigentes[nombre] = (valor, descripcion)
    conexion.execute(sa.text(f"UPDATE {E}.threshold_config SET vigente = false WHERE vigente"))
    for nombre, (valor, descripcion) in vigentes.items():
        conexion.execute(
            sa.text(
                f"INSERT INTO {E}.threshold_config (nombre, valor, descripcion, version, vigente, creado_por, motivo) "
                "VALUES (:n, CAST(:v AS jsonb), :d, :ver, true, 'migracion_0003', "
                "'Reglas observadas ALT-005..ALT-009 y umbrales afinados con scripts/backtest_alertas.py (2025)')"
            ),
            {"n": nombre, "v": json.dumps(valor), "d": descripcion, "ver": int(version) + 1},
        )


def downgrade() -> None:
    conexion = op.get_bind()
    nuevos = [n for n, _, _ in UMBRALES_0003]
    conexion.execute(sa.text(f"DELETE FROM {E}.threshold_config WHERE creado_por = 'migracion_0003'"))
    conexion.execute(sa.text(f"DELETE FROM {E}.threshold_config WHERE nombre = ANY(:n) AND nombre NOT IN "
                             f"('z_anomalia', 'tolerancia_salidas')"), {"n": nuevos})
    hay_vigentes = conexion.execute(sa.text(f"SELECT count(*) FROM {E}.threshold_config WHERE vigente")).scalar()
    if not hay_vigentes:
        conexion.execute(sa.text(
            f"UPDATE {E}.threshold_config SET vigente = true "
            f"WHERE version = (SELECT MAX(version) FROM {E}.threshold_config)"))
    op.execute(f"DROP INDEX IF EXISTS {E}.ix_alert_ubicacion")
    op.execute(f"DROP INDEX IF EXISTS {E}.ix_alert_origen_estado")
    op.execute(f"DROP INDEX IF EXISTS {E}.ix_alert_codigo_ruta_ventana")
    op.execute(f"""
ALTER TABLE {E}.alert
    DROP CONSTRAINT IF EXISTS ck_alert_conductor_seudonimo,
    DROP COLUMN IF EXISTS ubicacion,
    DROP COLUMN IF EXISTS variables_influyentes,
    DROP COLUMN IF EXISTS metodo_puntaje,
    DROP COLUMN IF EXISTS probabilidad,
    DROP COLUMN IF EXISTS serie_reciente,
    DROP COLUMN IF EXISTS tendencia_pendiente,
    DROP COLUMN IF EXISTS tendencia,
    DROP COLUMN IF EXISTS origen
""")
