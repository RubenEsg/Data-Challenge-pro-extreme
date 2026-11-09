"""Cola de trabajos en PostgreSQL para N réplicas (RNF-001, RNF-004, RNF-005, §7.1).

execution_log pasa a ser también la cola: cada réplica reclama filas «en_cola» con
SELECT … FOR UPDATE SKIP LOCKED y una reserva (lease) que vence; si la réplica muere, otra retoma el trabajo al
vencer la reserva. execution_attempt deja la traza de cada intento (quién lo reclamó y cómo terminó), que es la
evidencia de «exactamente una vez». programada_para identifica la franja del planificador: el índice único parcial
impide encolar dos veces la misma franja aunque varias réplicas disparen el mismo cron.

Solo toca el esquema propio ai_frecuencias.

Revision ID: 0002
Revises: 0001
"""
from __future__ import annotations

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

E = "ai_frecuencias"

DDL = f"""
ALTER TABLE {E}.execution_log
    ADD COLUMN worker_id        TEXT,
    ADD COLUMN lease_hasta      TIMESTAMPTZ,
    ADD COLUMN disponible_desde TIMESTAMPTZ,
    ADD COLUMN programada_para  TIMESTAMPTZ;

COMMENT ON COLUMN {E}.execution_log.worker_id IS 'Réplica/hilo que tiene reservado el trabajo (réplica:pid:arranque:hilo)';
COMMENT ON COLUMN {E}.execution_log.lease_hasta IS 'Fin de la reserva; el trabajador la renueva mientras corre';
COMMENT ON COLUMN {E}.execution_log.disponible_desde IS 'Espera de reintento (backoff): no se reclama antes';
COMMENT ON COLUMN {E}.execution_log.programada_para IS 'Franja del planificador interno (una fila por franja y tipo)';

CREATE INDEX ix_execution_log_en_cola ON {E}.execution_log (disponible_desde, creado_en)
    WHERE estado = 'en_cola';
CREATE INDEX ix_execution_log_corriendo ON {E}.execution_log (lease_hasta)
    WHERE estado = 'corriendo';
CREATE UNIQUE INDEX ux_execution_log_programada ON {E}.execution_log (tipo, programada_para)
    WHERE programada_para IS NOT NULL;

CREATE TABLE {E}.execution_attempt (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    execution_id  UUID NOT NULL REFERENCES {E}.execution_log(execution_id) ON DELETE CASCADE,
    intento       INTEGER NOT NULL,
    worker_id     TEXT NOT NULL,
    reclamado_en  TIMESTAMPTZ NOT NULL DEFAULT now(),
    terminado_en  TIMESTAMPTZ,
    resultado     TEXT NOT NULL DEFAULT 'corriendo' CHECK (resultado IN
                  ('corriendo','ok','error','reintento','reserva_perdida','abandonado')),
    detalle       TEXT,
    CONSTRAINT ux_execution_attempt UNIQUE (execution_id, intento)
);
CREATE INDEX ix_execution_attempt_worker ON {E}.execution_attempt (worker_id, reclamado_en DESC);
"""


def upgrade() -> None:
    op.execute(DDL)


def downgrade() -> None:
    op.execute(f"DROP TABLE IF EXISTS {E}.execution_attempt CASCADE")
    op.execute(f"DROP INDEX IF EXISTS {E}.ux_execution_log_programada")
    op.execute(f"DROP INDEX IF EXISTS {E}.ix_execution_log_corriendo")
    op.execute(f"DROP INDEX IF EXISTS {E}.ix_execution_log_en_cola")
    op.execute(f"ALTER TABLE {E}.execution_log DROP COLUMN IF EXISTS programada_para, "
               "DROP COLUMN IF EXISTS disponible_desde, DROP COLUMN IF EXISTS lease_hasta, "
               "DROP COLUMN IF EXISTS worker_id")
