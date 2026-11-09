"""Evidencia de la migración 0005 (§5.1, §10.2): los pesos de la función objetivo, versionados desde la instalación.

En una base PostgreSQL LOCAL y temporal (nunca la del reto): instala el esquema desde cero (alembic downgrade base +
upgrade head), lee GET /api/v1/thresholds recién instalado, llama POST /api/v1/recommendations/calculate para ver de
qué versión de umbrales toma los pesos α, β, γ y δ, baja a 0004 (los parámetros de §10.2 dejan de estar vigentes) y
vuelve a subir. Escribe docs/evidencias/modelo/pesos_objetivo_0005.json y, al final, borra la base temporal.

Uso (desde EntregaFinal/api_frecuencias, con DATABASE_URL apuntando al servidor local de pruebas):
  python scripts/evidencia_0005.py [--base ai_frecuencias_evidencia_0005] [--salida docs/evidencias/modelo]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402

SALIDA = RAIZ / "docs" / "evidencias" / "modelo"
LOCALES = {"localhost", "127.0.0.1"}
CONSULTA_VIGENTES = ("SELECT nombre, valor, version, creado_por FROM ai_frecuencias.threshold_config WHERE vigente "
                     "ORDER BY nombre")


def preparar_base(nombre: str):
    """Crea (si no existe) la base temporal en el MISMO servidor local de DATABASE_URL y devuelve su URL."""
    from app.config import Ajustes

    url = make_url(Ajustes().database_url)
    if url.host not in LOCALES:
        raise SystemExit("evidencia_0005 solo corre contra un servidor PostgreSQL local de pruebas")
    url_p = url.set(database=nombre)
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        if not c.execute(text("SELECT 1 FROM pg_database WHERE datname=:n"), {"n": nombre}).scalar():
            c.execute(text(f'CREATE DATABASE "{nombre}"'))
    admin.dispose()
    return url, url_p


def borrar_base(url, nombre: str) -> None:
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as c:
            c.execute(text(f'DROP DATABASE IF EXISTS "{nombre}" WITH (FORCE)'))
    finally:
        admin.dispose()


def vigentes(motor) -> dict:
    with motor.connect() as c:
        return {n: {"valor": v, "version": ver, "creado_por": cp}
                for n, v, ver, cp in c.execute(text(CONSULTA_VIGENTES)).all()}


def resumen_version(filas: dict, nombres: list[str]) -> dict:
    return {"version_vigente": sorted({x["version"] for x in filas.values()}),
            "parametros_10_2_vigentes": sorted(set(nombres) & set(filas))}


def main(argv=None) -> dict:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--base", default="ai_frecuencias_evidencia_0005", help="base temporal en el servidor local")
    ap.add_argument("--salida", type=Path, default=SALIDA)
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    url, url_p = preparar_base(args.base)
    os.environ["DATABASE_URL"] = url_p.render_as_string(hide_password=False)
    os.environ["REANUDAR_EJECUCIONES"] = "false"
    os.environ["AUTH_HABILITADA"] = "false"
    from alembic.config import Config

    from alembic import command

    cfg = Config(str(RAIZ / "alembic.ini"))
    cfg.set_main_option("script_location", str(RAIZ / "alembic"))
    cfg.set_main_option("sqlalchemy.url", os.environ["DATABASE_URL"].replace("%", "%%"))
    motor = create_engine(url_p)
    try:
        command.downgrade(cfg, "base")
        command.upgrade(cfg, "head")
        from fastapi.testclient import TestClient

        from app.main import app
        from app.servicios.optimizacion import PARAMETROS_OBJETIVO

        with TestClient(app) as cl:
            umbrales = cl.get("/api/v1/thresholds").json()
            calc = cl.post("/api/v1/recommendations/calculate", json={
                "ruta": "SILENCIO", "hora": 7, "demanda_hora": 669, "demanda_p90": 759, "fecha": "2025-03-11"}).json()
        subida = vigentes(motor)
        command.downgrade(cfg, "0004")
        bajada = vigentes(motor)
        command.upgrade(cfg, "head")
        resubida = vigentes(motor)
    finally:
        motor.dispose()
        from app.db import motor as motor_app

        motor_app().dispose()   # la API de prueba suelta sus conexiones antes de borrar la base temporal
        borrar_base(url, args.base)
    nombres = list(PARAMETROS_OBJETIVO)
    salida = {
        "generado": datetime.now(ZoneInfo("America/Bogota")).isoformat(timespec="seconds"),
        "base": f"PostgreSQL local de pruebas (base temporal {args.base}, borrada al terminar)",
        "script": "scripts/evidencia_0005.py",
        "get_thresholds_tras_instalar": {"version": umbrales.get("version"),
                                         "valores_10_2": {n: umbrales["valores"].get(n) for n in nombres}},
        "valores_del_codigo": {n: v for n, (v, _) in PARAMETROS_OBJETIVO.items()},
        "coinciden_con_el_codigo": all(float(umbrales["valores"].get(n)) == v
                                       for n, (v, _) in PARAMETROS_OBJETIVO.items()),
        "calculate_fuente_de_los_pesos": (calc.get("objetivo") or {}).get("pesos"),
        "calculate_umbrales_version": calc.get("umbrales_version"),
        "subida": resumen_version(subida, nombres),
        "bajada_a_0004": dict(resumen_version(bajada, nombres),
                              creado_por=sorted({x["creado_por"] for x in bajada.values()})),
        "nueva_subida": resumen_version(resubida, nombres),
    }
    args.salida.mkdir(parents=True, exist_ok=True)
    (args.salida / "pesos_objetivo_0005.json").write_text(json.dumps(salida, ensure_ascii=False, indent=1,
                                                                     default=str), encoding="utf-8")
    print(json.dumps({k: salida[k] for k in ("coinciden_con_el_codigo", "subida", "bajada_a_0004", "nueva_subida",
                                              "calculate_umbrales_version")}, ensure_ascii=False))
    return salida


if __name__ == "__main__":
    main()
