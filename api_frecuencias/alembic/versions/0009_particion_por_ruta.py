"""Partición del ciclo por ruta (RNF-005 «procesamiento particionable por ruta y fecha»).

1. execution_log gana la partición de cada trabajo:
   - ruta: la única ruta que el trabajo lee, procesa y bloquea (NULL = todas las rutas, como hasta ahora);
   - padre_id: la ejecución partida a la que pertenece el trabajo de una ruta;
   - particion: en la ejecución madre, cómo se partió («ruta»); NULL en los trabajos y en las ejecuciones sin partir.
   El trabajo de una ruta y la fecha (`hasta` de sus parámetros) son la unidad que reparten las réplicas: dos trabajos
   de la misma ruta nunca corren a la vez (app/servicios/cola.py) y los de rutas distintas sí, en réplicas
   distintas. La madre corre al final, cuando terminan sus trabajos, y cierra lo que es del modelo (monitoreo y
   política), una vez por ejecución.
2. marca_agua_ruta guarda la marca de agua por proceso y ruta y las huellas de la ventana de solape de esa ruta
   (app/servicios/fuentes.py): la lectura incremental de un trabajo parte de la marca de SU ruta. La fila con
   ruta = '*' es la frontera de las lecturas de todas las rutas del proceso (la que usan las rutas sin marca propia).
   execution_id es el trabajo que movió la marca (§9.5: la marca de la última ejecución exitosa); si se borra ese
   trabajo, la fila se borra con él y la ruta vuelve a leer desde la frontera o desde la carga inicial.
3. Siembra (para no releer todo): la marca de agua global que existía (la mayor marca_agua_nueva de las ejecuciones
   de frecuencia «ok», con las huellas de esa ejecución) pasa a cada ruta conocida del histórico propio
   (demanda_observada, con su proceso; «sobusa» si no lo trae) y a la frontera '*' de cada proceso y de «todos los
   procesos» (FUENTE_PROCESO=*). Cada ruta recibe solo las huellas de sus llaves (ruta|fecha|hora).

Bajada: borra marca_agua_ruta y las columnas nuevas. Si las marcas por ruta quedaron desfasadas, antes de bajar corra
una ejecución sin partir (todas las rutas): deja todas las marcas en la misma frontera, que es lo que vuelve a leer
la marca global de antes.

Solo toca el esquema propio ai_frecuencias.

Revision ID: 0009
Revises: 0008
"""
from __future__ import annotations

import json

import sqlalchemy as sa

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

E = "ai_frecuencias"
# Copiados aquí (una migración no depende del código que evoluciona): app/servicios/fuentes.PROCESO_DEFECTO y la
# llave de la frontera de las lecturas de todas las rutas (ejecucion.RUTA_FRONTERA).
PROCESO_DEFECTO = "sobusa"
FRONTERA = "*"
ORIGEN = "migracion_0009"

DDL = f"""
ALTER TABLE {E}.execution_log
    ADD COLUMN ruta      TEXT,
    ADD COLUMN padre_id  UUID REFERENCES {E}.execution_log(execution_id) ON DELETE CASCADE,
    ADD COLUMN particion TEXT CHECK (particion IN ('ruta'));

COMMENT ON COLUMN {E}.execution_log.ruta IS
    'RNF-005: ruta que el trabajo lee, procesa y bloquea; NULL = todas las rutas';
COMMENT ON COLUMN {E}.execution_log.padre_id IS
    'RNF-005: ejecución partida a la que pertenece este trabajo por ruta';
COMMENT ON COLUMN {E}.execution_log.particion IS
    'RNF-005: en la ejecución madre, cómo se partió (ruta); NULL = trabajo o ejecución sin partir';

CREATE INDEX ix_execution_log_padre ON {E}.execution_log (padre_id) WHERE padre_id IS NOT NULL;
CREATE INDEX ix_execution_log_frecuencia_activa ON {E}.execution_log (ruta, creado_en)
    WHERE tipo = 'frecuencia' AND estado IN ('en_cola', 'corriendo');

CREATE TABLE {E}.marca_agua_ruta (
    proceso        TEXT NOT NULL,
    ruta           TEXT NOT NULL,
    marca_agua     TIMESTAMPTZ NOT NULL,
    estado_fuente  JSONB,
    execution_id   UUID REFERENCES {E}.execution_log(execution_id) ON DELETE CASCADE,
    origen         TEXT NOT NULL DEFAULT 'ejecucion' CHECK (origen IN ('ejecucion', '{ORIGEN}')),
    actualizado_en TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (proceso, ruta)
);
COMMENT ON TABLE {E}.marca_agua_ruta IS
    'RNF-005: marca de agua de la lectura incremental por proceso y ruta (ruta = ''*'': frontera de las lecturas de '
    'todas las rutas del proceso)';
COMMENT ON COLUMN {E}.marca_agua_ruta.estado_fuente IS
    'Huellas de la ventana de solape de la ruta (app/servicios/fuentes.py): una fila tardía o modificada se entrega '
    'exactamente una vez';
COMMENT ON COLUMN {E}.marca_agua_ruta.execution_id IS
    'Trabajo que movió la marca a este valor (NULL si vino de la migración): §9.5, la marca es la de la última '
    'ejecución exitosa; si ese trabajo se borra, la ruta vuelve a la frontera o a la carga inicial (nunca se salta datos)';
"""


def _marca_global(conexion):
    """La marca de agua global de antes (la que leía ejecucion.ultima_marca_agua) y las huellas de esa ejecución."""
    return conexion.execute(sa.text(
        f"SELECT marca_agua_nueva, metricas -> 'fuente_estado' AS estado FROM {E}.execution_log "  # nosec B608  # E es la constante del esquema; sin entradas
        "WHERE tipo = 'frecuencia' AND estado = 'ok' AND marca_agua_nueva IS NOT NULL "
        "ORDER BY marca_agua_nueva DESC, terminado_en DESC NULLS LAST LIMIT 1")).first()


def _estado_de_la_ruta(estado, ruta: str):
    """Las huellas de una ruta (llaves «ruta|fecha|hora») del estado global; None si no hay estado."""
    if not isinstance(estado, dict):
        return None
    huellas = {k: h for k, h in (estado.get("huellas") or {}).items() if str(k).split("|", 1)[0] == ruta}
    return {**estado, "huellas": huellas}


def _sembrar(conexion) -> None:
    fila = _marca_global(conexion)
    if fila is None:
        return
    marca, estado = fila.marca_agua_nueva, fila.estado
    rutas = conexion.execute(sa.text(
        f"SELECT DISTINCT coalesce(idproceso, :defecto) AS proceso, ruta FROM {E}.demanda_observada"),  # nosec B608  # E es la constante del esquema; valores por parámetro
        {"defecto": PROCESO_DEFECTO}).all()
    procesos = sorted({p for p, _ in rutas} | {PROCESO_DEFECTO})
    insertar = sa.text(
        f"INSERT INTO {E}.marca_agua_ruta (proceso, ruta, marca_agua, estado_fuente, origen) "  # nosec B608  # E es la constante del esquema; valores por parámetro
        "VALUES (:proceso, :ruta, :marca, CAST(:estado AS jsonb), :origen) ON CONFLICT (proceso, ruta) DO NOTHING")
    filas = [(p, r, _estado_de_la_ruta(estado, r)) for p, r in rutas]
    filas += [(p, FRONTERA, estado) for p in [*procesos, FRONTERA]]
    for proceso, ruta, estado_ruta in filas:
        conexion.execute(insertar, {"proceso": proceso, "ruta": ruta, "marca": marca, "origen": ORIGEN,
                                    "estado": None if estado_ruta is None else json.dumps(estado_ruta)})


def upgrade() -> None:
    op.execute(DDL)
    _sembrar(op.get_bind())


def downgrade() -> None:
    op.execute(f"DROP TABLE IF EXISTS {E}.marca_agua_ruta")
    op.execute(f"DROP INDEX IF EXISTS {E}.ix_execution_log_frecuencia_activa")
    op.execute(f"DROP INDEX IF EXISTS {E}.ix_execution_log_padre")
    op.execute(f"ALTER TABLE {E}.execution_log DROP COLUMN IF EXISTS particion, DROP COLUMN IF EXISTS padre_id, "
               "DROP COLUMN IF EXISTS ruta")
