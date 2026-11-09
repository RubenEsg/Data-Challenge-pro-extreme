"""RNF-002 y §14.1 «Carga»: siembra una base LOCAL aparte con el volumen acordado (un año de resultados) para k6.

El «dataset acordado» de las pruebas de carga es el volumen de un año de operación del ciclo diario: unas 365
ejecuciones, cada una con sus predicciones, recomendaciones y alertas. Este script lo arma con filas REALES de la
API: toma las ejecuciones que ya hay en la base (con sus intentos, errores de calidad, predicciones,
recomendaciones, alertas, historial de alertas y fotos de variables) y hace copias hasta llegar a --ejecuciones
ejecuciones. Cada copia k (k = 1, 2, ...):
- lleva identificadores nuevos (UUID) y conserva las relaciones (ejecución → predicción → recomendación, alerta →
  historial, ejecución → intentos);
- corre todas las fechas y horas k × --paso-dias días hacia atrás (7 por omisión: se conserva el día de la semana);
- solo sale de ejecuciones en estado terminal: nunca se replica una ejecución «en_cola» o «corriendo».

Higiene: solo corre contra un PostgreSQL local (localhost, 127.0.0.1 o db) y se niega a tocar la base principal
(ai_frecuencias) o la base configurada en DATABASE_URL. La clave nunca se imprime. Nunca toca la base del reto.

Uso típico (clona una base de pruebas que ya tiene ejecuciones reales del ciclo y la lleva al volumen de un año):
  python scripts/sembrar_volumen.py --base-datos ai_frecuencias_volumen --plantilla ai_frecuencias_pruebas_k6 \
      --ejecuciones 365 --recrear
  (después: alembic upgrade head con DATABASE_URL apuntando a esa base, si la plantilla venía de una versión vieja)
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, make_url

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

E = "ai_frecuencias"
HOSTS_LOCALES = {"localhost", "127.0.0.1", "db", "::1"}
# Tablas que se replican, en orden de llaves foráneas. Las de identificador UUID reciben uno nuevo por copia.
TABLAS = ["execution_log", "execution_attempt", "data_quality_error", "prediction", "recommendation", "alert",
          "alert_history", "feature_snapshot"]
LLAVES_UUID = {"execution_log": "execution_id", "prediction": "prediction_id",
               "recommendation": "recommendation_id", "alert": "alert_id"}
ESTADOS_ACTIVOS = ("en_cola", "corriendo")
TIPOS_FECHA = {"timestamp with time zone", "timestamp without time zone", "date"}
TIPOS_TEXTO = {"text", "character varying"}


def _url_servidor() -> URL:
    crudo = os.environ.get("TEST_DATABASE_URL") or ""
    if not crudo:
        from app.config import Ajustes

        crudo = Ajustes().database_url
    if not crudo:
        raise SystemExit("Defina DATABASE_URL o TEST_DATABASE_URL (PostgreSQL local) en el entorno o en .env")
    url = make_url(crudo)
    if url.host not in HOSTS_LOCALES:
        raise SystemExit(f"sembrar_volumen solo corre contra un PostgreSQL local (host={url.host!r})")
    return url


def _protegida(nombre: str, url: URL) -> bool:
    return nombre in {"ai_frecuencias", url.database, "postgres", "template0", "template1"}


def preparar_base(url: URL, nombre: str, plantilla: str | None, recrear: bool) -> None:
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        existe = c.execute(text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": nombre}).scalar()
        if existe and recrear:
            c.execute(text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = :n"), {"n": nombre})
            c.execute(text(f'DROP DATABASE "{nombre}"'))
            existe = False
        if not existe:
            if plantilla:
                if _protegida(plantilla, url):
                    raise SystemExit(f"la plantilla {plantilla!r} es una base protegida")
                c.execute(text(f'CREATE DATABASE "{nombre}" TEMPLATE "{plantilla}"'))
            else:
                c.execute(text(f'CREATE DATABASE "{nombre}"'))
    admin.dispose()


def _columnas(c, tabla: str) -> list[dict]:
    return [dict(r._mapping) for r in c.execute(text(
        "SELECT column_name, data_type, column_default, is_identity, is_generated FROM information_schema.columns "
        "WHERE table_schema = :e AND table_name = :t ORDER BY ordinal_position"), {"e": E, "t": tabla})]


def _llaves_foraneas(c) -> dict[tuple[str, str], str]:
    """(tabla, columna) -> tabla referenciada, solo entre las tablas que se replican y hacia llaves UUID."""
    filas = c.execute(text(
        "SELECT cl.relname AS tabla, a.attname AS columna, rf.relname AS ref "
        "FROM pg_constraint k JOIN pg_class cl ON cl.oid = k.conrelid JOIN pg_class rf ON rf.oid = k.confrelid "
        "JOIN pg_attribute a ON a.attrelid = k.conrelid AND a.attnum = ANY(k.conkey) "
        "WHERE k.contype = 'f' AND k.connamespace = CAST(:e AS regnamespace)"), {"e": E})
    return {(f.tabla, f.columna): f.ref for f in filas if f.tabla in TABLAS and f.ref in LLAVES_UUID}


def _unicos(c, tabla: str) -> list[list[str]]:
    filas = c.execute(text(
        "SELECT array_agg(a.attname::text ORDER BY a.attnum) AS cols FROM pg_index i "
        "JOIN pg_class cl ON cl.oid = i.indrelid JOIN pg_attribute a ON a.attrelid = i.indrelid "
        "AND a.attnum = ANY(i.indkey) WHERE i.indisunique AND NOT i.indisprimary AND cl.relname = :t "
        "AND cl.relnamespace = CAST(:e AS regnamespace) GROUP BY i.indexrelid"), {"t": tabla, "e": E})
    return [list(f.cols) for f in filas]


def _contar(c) -> dict[str, int]:
    return {t: c.execute(text(f"SELECT count(*) FROM {E}.{t}")).scalar() for t in TABLAS}  # noqa: S608  # nosec B608  # nombres fijos de TABLAS


def _tramo(c) -> tuple[str, str]:
    lo, hi = c.execute(text(f"SELECT min(instante), max(instante) FROM {E}.prediction")).one()  # noqa: S608  # nosec B608  # esquema fijo
    if lo is None:
        raise SystemExit("la base no tiene predicciones que replicar: corra antes el ciclo "
                         "(POST /frequency/executions)")
    return lo.date().isoformat(), hi.date().isoformat()


def _expresiones(tabla: str, columnas: list[dict], fks: dict, unicos: list[list[str]], dias: int, k: int):
    """Lista de (columna, expresión SQL) y los JOIN de mapeo que necesita."""
    pk = LLAVES_UUID.get(tabla)
    mapeadas = {col: ref for (t, col), ref in fks.items() if t == tabla}
    if pk:
        mapeadas[pk] = tabla
    a_sufijar: set[str] = set()
    tipos = {x["column_name"]: x["data_type"] for x in columnas}
    for cols in unicos:
        # un índice único con una llave nueva o una fecha corrida ya no choca; si no, se marca su texto con ~volk
        if not any(col in mapeadas or tipos.get(col) in TIPOS_FECHA for col in cols):
            texto = [col for col in cols if tipos.get(col) in TIPOS_TEXTO]
            if texto:
                a_sufijar.add(texto[0])
    salida, joins = [], []
    for x in columnas:
        col = x["column_name"]
        if x["is_generated"] == "ALWAYS":
            continue
        if col == "id" and (x["is_identity"] == "YES" or (x["column_default"] or "").startswith("nextval(")):
            continue
        if col in mapeadas:
            alias = f"m_{col}"
            joins.append(f"LEFT JOIN pg_temp.mapa_{mapeadas[col]} {alias} ON {alias}.viejo = t.{col}")
            salida.append((col, f"{alias}.nuevo"))
        elif x["data_type"] == "date":
            salida.append((col, f"t.{col} - {dias * k}"))
        elif x["data_type"] in TIPOS_FECHA:
            salida.append((col, f"t.{col} - INTERVAL '{dias * k} days'"))
        elif col in a_sufijar:
            salida.append((col, f"t.{col} || '~vol{k}'"))
        else:
            salida.append((col, f"t.{col}"))
    return salida, joins


def replicar(c, ejecuciones_objetivo: int, paso_dias: int) -> dict:
    desde, hasta = _tramo(c)
    fks = _llaves_foraneas(c)
    meta = {t: (_columnas(c, t), _unicos(c, t)) for t in TABLAS}
    activos = ", ".join(f"'{x}'" for x in ESTADOS_ACTIVOS)
    # instantánea de las filas originales: las copias se hacen siempre desde ellas, nunca desde otra copia
    c.execute(text(f"CREATE TEMP TABLE base_execution_log AS SELECT execution_id AS id FROM {E}.execution_log "  # noqa: S608  # nosec B608  # constantes del módulo
                   f"WHERE estado NOT IN ({activos})"))
    base_ejecuciones = c.execute(text("SELECT count(*) FROM pg_temp.base_execution_log")).scalar()
    if not base_ejecuciones:
        raise SystemExit("la base no tiene ejecuciones terminadas que replicar")
    copias = max(1, math.ceil(ejecuciones_objetivo / base_ejecuciones))
    bloque = paso_dias
    for t, pk in LLAVES_UUID.items():
        if t != "execution_log":
            c.execute(text(f"CREATE TEMP TABLE base_{t} AS SELECT {pk} AS id FROM {E}.{t}"))  # noqa: S608  # nosec B608  # constantes del módulo
    filtros = {"execution_log": "t.execution_id IN (SELECT id FROM pg_temp.base_execution_log)",
               "execution_attempt": "t.execution_id IN (SELECT id FROM pg_temp.base_execution_log)",
               "data_quality_error": "t.execution_id IN (SELECT id FROM pg_temp.base_execution_log)",
               "prediction": "t.prediction_id IN (SELECT id FROM pg_temp.base_prediction)",
               "recommendation": "t.recommendation_id IN (SELECT id FROM pg_temp.base_recommendation)",
               "alert": "t.alert_id IN (SELECT id FROM pg_temp.base_alert)",
               "alert_history": "t.alert_id IN (SELECT id FROM pg_temp.base_alert)",
               "feature_snapshot": "t.prediction_id IN (SELECT id FROM pg_temp.base_prediction)"}
    for k in range(1, copias):
        for t in LLAVES_UUID:
            c.execute(text(f"DROP TABLE IF EXISTS pg_temp.mapa_{t}"))
            c.execute(text(f"CREATE TEMP TABLE mapa_{t} AS SELECT id AS viejo, gen_random_uuid() AS nuevo "  # noqa: S608  # nosec B608  # constantes del módulo
                           f"FROM pg_temp.base_{t}"))
            c.execute(text(f"CREATE INDEX ON pg_temp.mapa_{t} (viejo)"))
        corrimiento = f"INTERVAL '{bloque * k} days'"
        c.execute(text(f"SELECT {E}.asegurar_particion_feature_snapshot(x) FROM (SELECT DISTINCT "  # noqa: S608  # nosec B608  # constantes del módulo
                       f"date_trunc('day', ventana_inicio - {corrimiento}) AS x FROM {E}.feature_snapshot t "
                       f"WHERE {filtros['feature_snapshot']}) d"))
        for t in TABLAS:
            columnas, unicos = meta[t]
            expr, joins = _expresiones(t, columnas, fks, unicos, bloque, k)
            nombres = ", ".join(col for col, _ in expr)
            valores = ", ".join(v for _, v in expr)
            pk = LLAVES_UUID.get(t)
            condicion = filtros[t] + (f" AND m_{pk}.nuevo IS NOT NULL" if pk else "")
            if t in ("execution_attempt", "data_quality_error"):
                condicion += " AND m_execution_id.nuevo IS NOT NULL"
            if t == "alert_history":
                condicion += " AND m_alert_id.nuevo IS NOT NULL"
            c.execute(text(f"INSERT INTO {E}.{t} ({nombres}) SELECT {valores} FROM {E}.{t} t "  # noqa: S608  # nosec B608  # columnas leídas del catálogo
                           f"{' '.join(joins)} WHERE {condicion}"))
    lo, hi = _tramo(c)
    return {"ejecuciones_originales": base_ejecuciones, "copias_totales": copias, "paso_dias": paso_dias,
            "tramo_original": [desde, hasta], "tramo_sembrado": [lo, hi]}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--base-datos", required=True, help="base LOCAL aparte que se siembra (nunca ai_frecuencias)")
    p.add_argument("--plantilla", help="base local con ejecuciones reales que se clona primero (CREATE ... TEMPLATE)")
    p.add_argument("--recrear", action="store_true", help="borra y vuelve a crear --base-datos")
    p.add_argument("--ejecuciones", type=int, default=365,
                   help="ejecuciones del ciclo que debe tener la base (por omisión 365: un año de corridas diarias)")
    p.add_argument("--paso-dias", type=int, default=7, help="días que se corre cada copia respecto de la anterior")
    p.add_argument("--json", type=Path, help="archivo con el resumen de la siembra")
    a = p.parse_args()
    url = _url_servidor()
    if _protegida(a.base_datos, url):
        raise SystemExit(f"{a.base_datos!r} es una base protegida: use una base aparte para la carga")
    t0 = time.perf_counter()
    preparar_base(url, a.base_datos, a.plantilla, a.recrear)
    motor = create_engine(url.set(database=a.base_datos))
    with motor.begin() as c:
        antes = _contar(c)
        resumen = replicar(c, a.ejecuciones, max(1, a.paso_dias))
        despues = _contar(c)
        c.execute(text(f"ANALYZE {E}.execution_log, {E}.prediction, {E}.recommendation, {E}.alert, "  # noqa: S608  # nosec B608  # esquema fijo
                       f"{E}.alert_history, {E}.feature_snapshot"))
        tamano = c.execute(text("SELECT pg_size_pretty(pg_database_size(current_database()))")).scalar()
    motor.dispose()
    servidor = url.set(database=a.base_datos).render_as_string(hide_password=True)
    resumen.update({"base": a.base_datos, "servidor": servidor,
                    "plantilla": a.plantilla, "filas_antes": antes, "filas_despues": despues,
                    "tamano_base": tamano, "segundos": round(time.perf_counter() - t0, 1)})
    texto = json.dumps(resumen, ensure_ascii=False, indent=1)
    print(texto)
    if a.json:
        a.json.parent.mkdir(parents=True, exist_ok=True)
        a.json.write_text(texto + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
