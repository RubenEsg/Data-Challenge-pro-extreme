"""Plantilla del volumen acordado de RNF-002 con el código final: ejecuciones REALES del ciclo diario en una base
local nueva (su nombre debe empezar por ai_frecuencias_pruebas), para que scripts/sembrar_volumen.py la replique hasta
un año o más.

Igual que scripts/medir_ciclo.py: copia temporal de datos/, FUENTE=parquet, sin red ni notificaciones reales, la API
en este proceso (TestClient) y POST /api/v1/frequency/executions con cada corte: carga inicial hasta 2024-12-31 (dos
años de la serie), 30 cortes diarios del 2025-01-01 al 2025-01-30, un corte hasta el 2025-12-31 y una repetición sin
filas nuevas: 33 ejecuciones, como la plantilla de docs/evidencias/pruebas/k6_volumen.txt. No imprime la URL.

Uso (desde api_frecuencias/): python docs/evidencias/pruebas/plantilla_volumen.py <base> [--json resumen.json]
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import time
from datetime import date, timedelta
from pathlib import Path

RAIZ = Path.cwd()
sys.path.insert(0, str(RAIZ))
PREFIJO = "ai_frecuencias_pruebas"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("base")
    p.add_argument("--json", type=Path)
    a = p.parse_args()
    assert a.base.startswith(PREFIJO), "solo bases de pruebas"
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url

    from app.config import Ajustes

    u = make_url(Ajustes().database_url)
    assert u.host in ("127.0.0.1", "localhost") and u.port == 5433, "solo el PostgreSQL local de pruebas"
    url = u.set(database=a.base).render_as_string(hide_password=False)
    admin = create_engine(u.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text(f'DROP DATABASE IF EXISTS "{a.base}" WITH (FORCE)'))
        c.execute(text(f'CREATE DATABASE "{a.base}"'))
    admin.dispose()
    temporal = Path(tempfile.mkdtemp(prefix="plantilla_volumen_"))
    shutil.copytree(RAIZ / "datos", temporal / "datos")
    os.environ.update({
        "DATABASE_URL": url, "DATA_DIR": str(temporal / "datos"), "MODELOS_DIR": str(temporal / "datos" / "modelos"),
        "FUENTE": "parquet", "FUENTE_DATABASE_URL": "", "REANUDAR_EJECUCIONES": "false", "TRABAJADORES": "0",
        "AUTH_HABILITADA": "false", "NOTIFICACIONES": "ninguna", "PLANIFICADOR_HABILITADO": "false",
        "OTEL_EXPORTADOR": "ninguno", "ENTORNO": "pruebas", "CATALOGOS_FUENTE": "archivos",
        "CATALOGOS_DATABASE_URL": "", "LOG_NIVEL": "WARNING"})
    try:
        from alembic.config import Config

        from alembic import command

        cfg = Config(str(RAIZ / "alembic.ini"))
        cfg.set_main_option("script_location", str(RAIZ / "alembic"))
        cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
        command.upgrade(cfg, "head")
        from fastapi.testclient import TestClient

        from app.main import app

        cortes = [date(2024, 12, 31)] + [date(2025, 1, 1) + timedelta(days=i) for i in range(30)]
        cortes += [date(2025, 12, 31), date(2025, 12, 31)]
        corridas = []
        t_total = time.perf_counter()
        with TestClient(app) as cliente:
            for i, hasta in enumerate(cortes, start=1):
                t0 = time.perf_counter()
                r = cliente.post("/api/v1/frequency/executions", json={"hasta": hasta.isoformat(), "notificar": False})
                r.raise_for_status()
                e = cliente.get(f"/api/v1/frequency/executions/{r.json()['execution_id']}").json()
                fila = {"n": i, "hasta": hasta.isoformat(), "estado": e.get("estado"), "filas": e.get("filas_leidas"),
                        "predicciones": e.get("predicciones"), "recomendaciones": e.get("recomendaciones"),
                        "alertas": e.get("alertas"), "segundos": round(time.perf_counter() - t0, 1)}
                corridas.append(fila)
                print(json.dumps(fila, ensure_ascii=False), flush=True)
        m = create_engine(url)
        with m.connect() as c:
            conteos = {t: int(c.execute(text(f"SELECT count(*) FROM ai_frecuencias.{t}")).scalar())  # noqa: S608
                       for t in ("execution_log", "execution_attempt", "prediction", "recommendation", "alert",
                                 "alert_history", "feature_snapshot")}
        m.dispose()
        resumen = {"base": a.base, "corridas": corridas, "conteos": conteos,
                   "segundos": round(time.perf_counter() - t_total, 1)}
        print(json.dumps({"conteos": conteos, "segundos": resumen["segundos"]}, ensure_ascii=False))
        if a.json:
            a.json.write_text(json.dumps(resumen, ensure_ascii=False, indent=1), encoding="utf-8")
    finally:
        shutil.rmtree(temporal, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
