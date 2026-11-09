"""Dimensiones de §8.3, trazabilidad de la calidad, llaves naturales, aprobación de umbrales y respuesta del reto.

1. §8.3 «mantener id_ruta, proceso, id_dia_semana e id_estacionalidad como dimensiones, sin cambiar su semántica»:
   prediction, recommendation, alert, demanda_observada y feature_snapshot ganan
   - idruta INTEGER (rutas.idruta), idempresa INTEGER (rutas.idempresa, nulo si Extreme no lo trae),
   - idproceso TEXT (la llave de "Procesos", que en Extreme es la columna de texto rutas.proceso; se guarda tal cual),
   - id_dia_semana INTEGER 1..7 (ISO, como dias_semana) e id_estacionalidad INTEGER (nulo si no hay vigencia),
   con un índice (idruta, fecha) o (idruta, detectada_en). Las filas existentes se rellenan con la correspondencia
   nombre -> idruta del catálogo de la API (datos/catalogo_rutas.json) y el proceso de la tabla rutas exportada
   (rutas.parquet: «sobusa» en las tres rutas, idempresa nulo), copiados aquí como en la 0005: una migración no
   depende del código que evoluciona. El día ISO sale de la fecha local. La estacionalidad queda nula: las vigencias
   de estacionalidades_anio exportadas son de otro proceso (hallazgo H1). Desde esta versión el ciclo escribe las
   cinco columnas en cada fila nueva (app/servicios/dimensiones.py).
2. recommendation: origen ('franja' de §10.2 o 'plan_dia', el plan del día siguiente que persiste el ciclo),
   UNIQUE (execution_id, prediction_id) cuando ambos existen y UNIQUE (execution_id, ruta, fecha, hora) del plan.
3. alert: CHECK de la máquina de estados (antes solo vivía en el código) e índice compuesto (viaje, detectada_en)
   de §8.1.
4. data_quality_error: llave (JSONB con las columnas llave del registro), valor (texto) y bloqueante, para que un
   error lleve al registro exacto (§6.3, §14.2).
5. threshold_config: aprobado_por y aprobado_en (§5.1: los valores requieren validación del área operativa).
6. execution_log.tipo admite 'respuesta' (la foto de la respuesta del reto se calcula en la cola, §7.1).
7. Tabla nueva respuesta_reto: la foto persistida de la respuesta a la pregunta del reto por fecha y ruta, con el
   modelo, la calibración, la versión de umbrales, la ejecución y la fuente del pronóstico (§20).

Bajada: quita todo lo anterior. Antes borra las filas que no caben en el esquema 0005: las recomendaciones
origen='plan_dia' (se recalculan en el ciclo) y las ejecuciones tipo 'respuesta' (con sus intentos).

Solo toca el esquema propio ai_frecuencias.

Revision ID: 0006
Revises: 0005
"""
from __future__ import annotations

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

E = "ai_frecuencias"
TABLAS_DIMENSIONES = ("prediction", "recommendation", "alert", "demanda_observada", "feature_snapshot")
# rutas del reto: nombre -> (idruta, proceso, idempresa). idruta de datos/catalogo_rutas.json; proceso e idempresa
# de la tabla rutas exportada (rutas.parquet). Una prueba verifica que idruta coincide con el catálogo de la API.
RUTAS_0006 = {
    "SILENCIO": (2, "sobusa", None),
    "CRA 54": (16, "sobusa", None),
    "CL 72": (21, "sobusa", None),
}
# fecha local que fija el día de la semana de cada tabla
FECHA_LOCAL = {
    "prediction": "fecha",
    "recommendation": "fecha",
    "demanda_observada": "fecha",
    "feature_snapshot": "fecha",
    "alert": "(COALESCE(ventana_inicio, detectada_en) AT TIME ZONE 'America/Bogota')::date",
}
INDICE_DIMENSION = {
    "prediction": ("ix_prediction_idruta_fecha", "(idruta, fecha, hora)"),
    "recommendation": ("ix_recommendation_idruta_fecha", "(idruta, fecha, hora)"),
    "demanda_observada": ("ix_demanda_observada_idruta_fecha", "(idruta, fecha, hora)"),
    "feature_snapshot": ("ix_feature_snapshot_idruta_fecha", "(idruta, fecha, hora)"),
    "alert": ("ix_alert_idruta_detectada", "(idruta, detectada_en DESC)"),
}
ESTADOS_ALERTA = ("nueva", "reconocida", "asignada", "cerrada", "descartada")


def _mapeo_sql() -> str:
    filas = []
    for ruta, (idruta, proceso, idempresa) in RUTAS_0006.items():
        texto_ruta = ruta.replace("'", "''")
        texto_proceso = "NULL" if proceso is None else "'" + proceso.replace("'", "''") + "'"
        texto_empresa = "NULL" if idempresa is None else str(int(idempresa))
        filas.append(f"('{texto_ruta}', {int(idruta)}, {texto_proceso}, {texto_empresa}::integer)")
    return "(VALUES " + ", ".join(filas) + ") AS m(ruta, idruta, idproceso, idempresa)"


def _dimensiones_up(tabla: str) -> None:
    op.execute(f"""
ALTER TABLE {E}.{tabla}
    ADD COLUMN idruta            INTEGER,
    ADD COLUMN idempresa         INTEGER,
    ADD COLUMN idproceso         TEXT,
    ADD COLUMN id_dia_semana     INTEGER CONSTRAINT ck_{tabla}_id_dia_semana CHECK (id_dia_semana BETWEEN 1 AND 7),
    ADD COLUMN id_estacionalidad INTEGER
""")
    op.execute(f"""
UPDATE {E}.{tabla} t
   SET idruta = m.idruta, idproceso = m.idproceso, idempresa = m.idempresa
  FROM {_mapeo_sql()}
 WHERE t.ruta = m.ruta
""")
    op.execute(f"UPDATE {E}.{tabla} SET id_dia_semana = EXTRACT(ISODOW FROM {FECHA_LOCAL[tabla]})::integer")
    nombre, columnas = INDICE_DIMENSION[tabla]
    op.execute(f"CREATE INDEX {nombre} ON {E}.{tabla} {columnas}")
    op.execute(f"COMMENT ON COLUMN {E}.{tabla}.idruta IS '§8.3 rutas.idruta de Extreme (dimensión, sin cambiar su "
               f"semántica)'")
    op.execute(f"COMMENT ON COLUMN {E}.{tabla}.idproceso IS '§8.3 llave de \"Procesos\" (rutas.proceso, texto en "
               f"Extreme, p. ej. sobusa)'")
    op.execute(f"COMMENT ON COLUMN {E}.{tabla}.id_dia_semana IS '§8.3 día ISO 1 = lunes … 7 = domingo (dias_semana) "
               f"de la fecha local America/Bogota'")
    op.execute(f"COMMENT ON COLUMN {E}.{tabla}.id_estacionalidad IS '§8.3 estacionalidades_anio vigente para el "
               f"proceso; nula si no hay (H1)'")


def _dimensiones_down(tabla: str) -> None:
    nombre, _ = INDICE_DIMENSION[tabla]
    op.execute(f"DROP INDEX IF EXISTS {E}.{nombre}")
    op.execute(f"""
ALTER TABLE {E}.{tabla}
    DROP COLUMN IF EXISTS id_estacionalidad,
    DROP COLUMN IF EXISTS id_dia_semana,
    DROP COLUMN IF EXISTS idproceso,
    DROP COLUMN IF EXISTS idempresa,
    DROP COLUMN IF EXISTS idruta
""")


def upgrade() -> None:
    for tabla in TABLAS_DIMENSIONES:
        _dimensiones_up(tabla)

    estados = ", ".join(f"'{e}'" for e in ESTADOS_ALERTA)
    op.execute(f"""
ALTER TABLE {E}.recommendation
    ADD COLUMN origen TEXT NOT NULL DEFAULT 'franja'
        CONSTRAINT ck_recommendation_origen CHECK (origen IN ('franja', 'plan_dia'));
COMMENT ON COLUMN {E}.recommendation.origen IS 'franja = recomendación de §10.2 de una predicción; plan_dia = plan del día siguiente por hora que persiste el ciclo diario (prediction_id nulo)';
CREATE UNIQUE INDEX ux_recommendation_prediccion ON {E}.recommendation (execution_id, prediction_id)
    WHERE execution_id IS NOT NULL AND prediction_id IS NOT NULL;
CREATE UNIQUE INDEX ux_recommendation_plan_dia ON {E}.recommendation (execution_id, ruta, fecha, hora)
    WHERE origen = 'plan_dia';

ALTER TABLE {E}.alert ADD CONSTRAINT ck_alert_estado CHECK (estado IN ({estados}));
CREATE INDEX ix_alert_viaje_fecha ON {E}.alert (viaje, detectada_en DESC);

ALTER TABLE {E}.data_quality_error
    ADD COLUMN llave      JSONB,
    ADD COLUMN valor      TEXT,
    ADD COLUMN bloqueante BOOLEAN;
COMMENT ON COLUMN {E}.data_quality_error.llave IS 'Columnas llave del registro con error (JSON), para ubicarlo en la fuente';
COMMENT ON COLUMN {E}.data_quality_error.valor IS 'Valor observado que incumple la regla (texto)';
COMMENT ON COLUMN {E}.data_quality_error.bloqueante IS 'true: el registro no entra al histórico; false: advertencia';

ALTER TABLE {E}.threshold_config
    ADD COLUMN aprobado_por TEXT,
    ADD COLUMN aprobado_en  TIMESTAMPTZ;
COMMENT ON COLUMN {E}.threshold_config.aprobado_por IS '§5.1 quién del área operativa validó la versión (nulo = propuesta)';

ALTER TABLE {E}.execution_log DROP CONSTRAINT IF EXISTS execution_log_tipo_check;
ALTER TABLE {E}.execution_log ADD CONSTRAINT ck_execution_log_tipo
    CHECK (tipo IN ('frecuencia', 'entrenamiento', 'respuesta'));

CREATE TABLE {E}.respuesta_reto (
    id                  BIGSERIAL PRIMARY KEY,
    fecha               DATE NOT NULL,
    ruta                TEXT NOT NULL,
    idruta              INTEGER,
    payload             JSONB NOT NULL,
    model_id            TEXT,
    calibracion_version TEXT,
    umbrales_version    INTEGER,
    execution_id        UUID REFERENCES {E}.execution_log(execution_id) ON DELETE SET NULL,
    fuente_pronostico   TEXT,
    generado_en         TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ux_respuesta_reto_clave UNIQUE (fecha, ruta, model_id, umbrales_version)
);
CREATE INDEX ix_respuesta_reto_fecha ON {E}.respuesta_reto (fecha DESC);
COMMENT ON TABLE {E}.respuesta_reto IS '§20 foto de la respuesta a la pregunta del reto por fecha y ruta, con modelo, calibración, umbrales y ejecución';
""")


def downgrade() -> None:
    op.execute(f"""
DROP TABLE IF EXISTS {E}.respuesta_reto;

DELETE FROM {E}.execution_log WHERE tipo NOT IN ('frecuencia', 'entrenamiento');
ALTER TABLE {E}.execution_log DROP CONSTRAINT IF EXISTS ck_execution_log_tipo;
ALTER TABLE {E}.execution_log ADD CONSTRAINT execution_log_tipo_check CHECK (tipo IN ('frecuencia', 'entrenamiento'));

ALTER TABLE {E}.threshold_config DROP COLUMN IF EXISTS aprobado_en, DROP COLUMN IF EXISTS aprobado_por;
ALTER TABLE {E}.data_quality_error DROP COLUMN IF EXISTS bloqueante, DROP COLUMN IF EXISTS valor,
    DROP COLUMN IF EXISTS llave;

DROP INDEX IF EXISTS {E}.ix_alert_viaje_fecha;
ALTER TABLE {E}.alert DROP CONSTRAINT IF EXISTS ck_alert_estado;

DELETE FROM {E}.recommendation WHERE origen = 'plan_dia';
DROP INDEX IF EXISTS {E}.ux_recommendation_plan_dia;
DROP INDEX IF EXISTS {E}.ux_recommendation_prediccion;
ALTER TABLE {E}.recommendation DROP CONSTRAINT IF EXISTS ck_recommendation_origen;
ALTER TABLE {E}.recommendation DROP COLUMN IF EXISTS origen;
""")
    for tabla in reversed(TABLAS_DIMENSIONES):
        _dimensiones_down(tabla)


# ayuda de las pruebas: columnas que agrega la migración por tabla
COLUMNAS_0006 = {
    **{t: ("idruta", "idempresa", "idproceso", "id_dia_semana", "id_estacionalidad") for t in TABLAS_DIMENSIONES},
    "data_quality_error": ("llave", "valor", "bloqueante"),
    "threshold_config": ("aprobado_por", "aprobado_en"),
}
__all__ = ["COLUMNAS_0006", "RUTAS_0006", "downgrade", "upgrade"]
