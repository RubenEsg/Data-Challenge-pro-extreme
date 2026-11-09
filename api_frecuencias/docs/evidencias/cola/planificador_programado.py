"""§14.2 «la ejecución programada procesa lo nuevo o modificado desde la última marca y actualiza predicciones,
recomendaciones y alertas»: evidencia con el PLANIFICADOR (APScheduler, cron cada minuto), sin ningún POST manual.

Qué hace (todo en una base LOCAL desechable y en una copia temporal de datos/, nunca en el repositorio):
1. Migra desde cero la base indicada y arranca la API en este proceso (lifespan real: cola de trabajos y planificador
   con PLAN_EJECUCION_CRON='*/1 * * * *'). La fuente es el Parquet de la copia temporal, cortado en --corte.
2. Franja 1 (programada): carga inicial del histórico hasta --corte.
3. Llega información: se agrega el día siguiente al corte (filas nuevas) y se modifican tres filas del día del
   corte (una por ruta, con ultima_actualizacion posterior a la marca de agua). La fuente vuelve a leer el archivo.
4. La siguiente franja programada lee SOLO lo nuevo o modificado (filas_leidas > 0) y deja predicciones,
   recomendaciones y alertas nuevas; la franja posterior, sin llegada, lee 0 filas y no reprocesa el histórico.

Uso (desde EntregaFinal/api_frecuencias; la URL de la base local solo por el entorno o el .env):
  python docs/evidencias/cola/planificador_programado.py --base-datos ai_frecuencias_pruebas_planificador \
      --salida docs/evidencias/cola/planificador_programado.txt --json docs/evidencias/cola/planificador_programado.json
  --raiz permite correr el mismo guion con otra copia del código (por ejemplo, un worktree congelado).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import time
from datetime import date, datetime, timedelta
from pathlib import Path

RAIZ_REPO = Path(__file__).resolve().parents[3]
HOSTS_LOCALES = {"localhost", "127.0.0.1", "db", "::1"}
LINEAS: list[str] = []


def log(texto: str = "") -> None:
    LINEAS.append(texto)
    print(texto, flush=True)


def _url_servidor(raiz: Path) -> str:
    crudo = os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL") or ""
    if not crudo:
        from app.config import Ajustes

        crudo = Ajustes().database_url
    if not crudo:
        raise SystemExit("Defina TEST_DATABASE_URL o DATABASE_URL (PostgreSQL local)")
    from sqlalchemy.engine import make_url

    if make_url(crudo).host not in HOSTS_LOCALES:
        raise SystemExit("solo corre contra un PostgreSQL local")
    return crudo


def preparar_datos(raiz: Path, corte: date) -> tuple[Path, object]:
    import pandas as pd

    tmp = Path(tempfile.mkdtemp(prefix="planificador_programado_"))
    copia = tmp / "datos"
    shutil.copytree(raiz / "datos", copia)
    completo = pd.read_parquet(copia / "demanda_horaria.parquet")
    completo[completo["fecha"] <= corte].reset_index(drop=True).to_parquet(copia / "demanda_horaria.parquet",
                                                                           index=False)
    return copia, completo


def llegada(copia: Path, completo, corte: date) -> dict:
    """Agrega el día siguiente al corte y modifica tres filas del día del corte (una por ruta)."""
    import pandas as pd

    nuevo_dia = corte + timedelta(days=1)
    base = completo[completo["fecha"] <= nuevo_dia].copy().reset_index(drop=True)
    marca_mod = pd.Timestamp(datetime.combine(nuevo_dia, datetime.min.time()).replace(hour=12)).tz_localize(
        "America/Bogota")
    modificadas = []
    for ruta in sorted(base["ruta"].unique()):
        idx = base[(base["fecha"] == corte) & (base["ruta"] == ruta) & (base["hora"] == 7)].index
        if len(idx):
            i = idx[0]
            antes = float(base.at[i, "pasajeros"])
            base.at[i, "pasajeros"] = antes + 25.0
            base.at[i, "ultima_actualizacion"] = marca_mod
            modificadas.append({"ruta": ruta, "fecha": corte.isoformat(), "hora": 7, "pasajeros_antes": antes,
                                "pasajeros_despues": antes + 25.0})
    temporal = copia / "demanda_horaria.parquet.tmp"
    base.to_parquet(temporal, index=False)
    os.replace(temporal, copia / "demanda_horaria.parquet")        # la fuente nunca ve un archivo a medio escribir
    return {"dia_nuevo": nuevo_dia.isoformat(), "filas_nuevas": int((base["fecha"] == nuevo_dia).sum()),
            "filas_modificadas": modificadas}


def ejecuciones_programadas(motor) -> list[dict]:
    from sqlalchemy import text

    with motor.connect() as c:
        filas = c.execute(text(
            "SELECT e.execution_id, e.estado, e.programada_para, e.creado_en, e.terminado_en, e.filas_leidas, "
            "e.filas_validas, e.marca_agua_anterior, e.marca_agua_nueva, e.worker_id, e.metricas, e.mensaje, "
            "(SELECT count(*) FROM ai_frecuencias.prediction p WHERE p.execution_id = e.execution_id) AS pred, "
            "(SELECT count(*) FROM ai_frecuencias.recommendation r WHERE r.execution_id = e.execution_id) AS rec, "
            "(SELECT count(*) FROM ai_frecuencias.alert a WHERE a.execution_id = e.execution_id) AS alertas "
            "FROM ai_frecuencias.execution_log e WHERE e.tipo = 'frecuencia' "
            "AND e.parametros->>'origen' = 'planificador' ORDER BY e.programada_para"))
        return [dict(f._mapping) for f in filas]


def esperar(motor, condicion, limite_s: float, motivo: str) -> list[dict]:
    t0 = time.monotonic()
    while time.monotonic() - t0 < limite_s:
        filas = ejecuciones_programadas(motor)
        if condicion(filas):
            return filas
        time.sleep(2)
    raise SystemExit(f"tiempo agotado esperando {motivo}")


def _version_codigo(raiz: Path) -> str:
    """Commit del código probado (y si tiene cambios sin confirmar), para que la evidencia diga qué se midió."""
    import subprocess

    try:
        commit = subprocess.run(["git", "-C", str(raiz), "rev-parse", "--short", "HEAD"], capture_output=True,  # noqa: S603, S607
                                text=True, timeout=20, check=True).stdout.strip()
        sucio = subprocess.run(["git", "-C", str(raiz), "status", "--porcelain", "--", "."], capture_output=True,  # noqa: S603, S607
                               text=True, timeout=20, check=True).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "sin git"
    return f"commit {commit}" + (" con cambios sin confirmar" if sucio else "")


def _hora(x) -> str:
    return x.astimezone().strftime("%H:%M:%S") if x else "-"


def describir(e: dict) -> str:
    lectura = (e["metricas"] or {}).get("lectura") or {}
    nota = (e["metricas"] or {}).get("nota") or ""
    obs = (e["metricas"] or {}).get("alertas_observadas") or {}
    return (f"   franja {_hora(e['programada_para'])[:5]}  estado={e['estado']}  filas_leidas={e['filas_leidas']}  "
            f"filas_validas={e['filas_validas']}  predicciones={e['pred']}  recomendaciones={e['rec']}  "
            f"alertas={e['alertas']}  marca_agua {e['marca_agua_anterior']} -> {e['marca_agua_nueva']}  "
            f"worker={e['worker_id']}  terminada={_hora(e['terminado_en'])}"
            + (f"\n      lectura={json.dumps(lectura, ensure_ascii=False, default=str)}" if lectura else "")
            + (f"\n      alertas_observadas={json.dumps(obs, ensure_ascii=False, default=str)[:300]}" if obs else "")
            + (f"\n      nota: {nota}" if nota else ""))


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--raiz", type=Path, default=RAIZ_REPO, help="raíz del código de la API que se prueba")
    p.add_argument("--base-datos", default="ai_frecuencias_pruebas_planificador")
    p.add_argument("--corte", type=date.fromisoformat, default=date(2025, 11, 24))
    p.add_argument("--salida", type=Path)
    p.add_argument("--json", type=Path)
    a = p.parse_args()
    raiz = a.raiz.resolve()
    sys.path.insert(0, str(raiz))
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url

    url = make_url(_url_servidor(raiz))
    if a.base_datos in {"ai_frecuencias", url.database}:
        raise SystemExit("use una base desechable aparte")
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = :n"),
                  {"n": a.base_datos})
        c.execute(text(f'DROP DATABASE IF EXISTS "{a.base_datos}"'))
        c.execute(text(f'CREATE DATABASE "{a.base_datos}"'))
    admin.dispose()
    url_base = url.set(database=a.base_datos).render_as_string(hide_password=False)
    copia, completo = preparar_datos(raiz, a.corte)
    os.environ.update({
        "DATABASE_URL": url_base, "DATA_DIR": str(copia), "MODELOS_DIR": str(copia / "modelos"),
        "FUENTE": "parquet", "PLANIFICADOR_HABILITADO": "true", "PLAN_EJECUCION_CRON": "*/1 * * * *",
        # cola real: un trabajador consume lo que encola el planificador (como en docker compose)
        "PLAN_REENTRENAMIENTO_CRON": "0 3 1 1 *", "AUTH_HABILITADA": "false", "REANUDAR_EJECUCIONES": "true",
        "TRABAJADORES": "1", "OTEL_EXPORTADOR": "ninguno", "MAX_REINTENTOS": "1", "SONDEO_COLA_SEGUNDOS": "1",
        "ENTORNO": "local"})
    os.environ.pop("FUENTE_DATABASE_URL", None)
    from alembic.config import Config

    from alembic import command

    cfg = Config(str(raiz / "alembic.ini"))
    cfg.set_main_option("script_location", str(raiz / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url_base.replace("%", "%%"))
    command.upgrade(cfg, "head")
    motor = create_engine(url_base)
    from fastapi.testclient import TestClient

    from app.main import app
    from app.servicios import datos

    log(f"§14.2 · ejecución PROGRAMADA que procesa lo nuevo o modificado ({datetime.now():%Y-%m-%d %H:%M:%S}, "
        "Windows 11, PostgreSQL 14 local)")
    log(f"Base local desechable {a.base_datos}, migrada desde cero; datos en una copia temporal (fuente Parquet "
        f"cortada en {a.corte}); código: {_version_codigo(raiz)}")
    log("Planificador interno (APScheduler) con PLAN_EJECUCION_CRON='*/1 * * * *': ninguna ejecución se crea con "
        "POST; todas las de abajo las encola el planificador (parametros.origen = planificador).")
    log()
    resumen: dict = {"corte": a.corte.isoformat(), "franjas": []}
    with TestClient(app) as cliente:
        estado = cliente.get("/api/v1/scheduler").json()
        log(f"GET /api/v1/scheduler -> habilitado={estado.get('habilitado')} "
            f"activo_en_esta_replica={estado.get('activo_en_esta_replica')} trabajos="
            f"{json.dumps(estado.get('trabajos'), ensure_ascii=False)}")
        log()
        log("1) Franja programada con la carga inicial (histórico hasta el corte)")
        filas = esperar(motor, lambda f: any(x["estado"] in ("ok", "error") for x in f), 420, "la primera franja")
        primera = next(x for x in filas if x["estado"] in ("ok", "error"))
        log(describir(primera))
        filas = esperar(motor, lambda f: not any(x["estado"] in ("en_cola", "corriendo") for x in f), 420,
                        "que la cola quede libre")
        for x in filas:
            if x["execution_id"] != primera["execution_id"]:
                log(describir(x) + "   (franja que corrió antes de la llegada)")
        # la llegada cae a mitad de minuto, con la cola libre: la franja que la procesa es la siguiente del cron
        while not (5 <= datetime.now().second <= 40) or any(
                x["estado"] in ("en_cola", "corriendo") for x in ejecuciones_programadas(motor)):
            time.sleep(1)
        log()
        log("2) Llega información nueva y modificada (sin tocar la API)")
        info = llegada(copia, completo, a.corte)
        datos.limpiar_cache()
        instante_llegada = datetime.now().astimezone()
        log(f"   {_hora(instante_llegada)}: día {info['dia_nuevo']} agregado ({info['filas_nuevas']} filas nuevas) y "
            f"{len(info['filas_modificadas'])} filas del {a.corte} modificadas: "
            f"{json.dumps(info['filas_modificadas'], ensure_ascii=False)}")
        log()
        log("3) Siguiente franja programada: lee solo lo nuevo o modificado")
        filas = esperar(motor, lambda f: any(x["creado_en"] > instante_llegada and x["estado"] in ("ok", "error")
                                             for x in f), 300, "la franja posterior a la llegada")
        tras = next(x for x in filas if x["creado_en"] > instante_llegada and x["estado"] in ("ok", "error"))
        log(describir(tras))
        log()
        log("4) Franja siguiente, sin llegada: 0 filas, no reprocesa el histórico")
        filas = esperar(motor, lambda f: any(x["creado_en"] > tras["terminado_en"] and x["estado"] in ("ok", "error")
                                             for x in f), 300, "la franja sin llegada")
        sin = next(x for x in filas if x["creado_en"] > tras["terminado_en"] and x["estado"] in ("ok", "error"))
        log(describir(sin))
        estado = cliente.get("/api/v1/scheduler").json()
        todas = ejecuciones_programadas(motor)
        with motor.connect() as c:
            totales = {t: c.execute(text(f"SELECT count(*) FROM ai_frecuencias.{t}")).scalar()  # noqa: S608  # nosec B608  # nombres fijos
                       for t in ("prediction", "recommendation", "alert", "demanda_observada")}
            manuales = c.execute(text("SELECT count(*) FROM ai_frecuencias.execution_log WHERE tipo = 'frecuencia' "
                                      "AND coalesce(parametros->>'origen', '') <> 'planificador'")).scalar()
    log()
    log("GET /api/v1/scheduler al final -> franjas_recientes (las encoló el planificador, una por minuto):")
    for f in estado.get("franjas_recientes") or []:
        log(f"   {f.get('programada_para')}  {f.get('tipo')}  {f.get('estado')}  intentos={f.get('intentos')}  "
            f"execution_id={f.get('execution_id')}")
    log(f"Ejecuciones de frecuencia creadas por el planificador: {len(todas)}; creadas a mano (POST): {manuales}")
    log("   franja  estado  filas_leidas  predicciones  recomendaciones  alertas")
    for x in todas:
        log(f"   {_hora(x['programada_para'])[:5]}   {x['estado']:<6}  {x['filas_leidas'] or 0:>12}  {x['pred']:>12}  "
            f"{x['rec']:>15}  {x['alertas']:>7}")
    log(f"Totales en la base: {json.dumps(totales, ensure_ascii=False)}")
    esperado = (primera["filas_validas"] or 0) + info["filas_nuevas"]
    log(f"   demanda_observada = {primera['filas_validas']} (carga inicial) + {info['filas_nuevas']} (día nuevo) = "
        f"{esperado}: las {len(info['filas_modificadas'])} filas modificadas se actualizaron en su lugar, sin duplicar")
    comprobaciones = [
        ("la carga inicial la hizo una franja programada", primera["estado"] == "ok" and primera["filas_leidas"] > 0),
        ("tras la llegada, la franja programada leyó solo lo nuevo o modificado",
         tras["estado"] == "ok" and 0 < tras["filas_leidas"] <= info["filas_nuevas"] + len(info["filas_modificadas"])),
        ("esa franja creó predicciones, recomendaciones y alertas nuevas",
         tras["pred"] > 0 and tras["rec"] > 0 and tras["alertas"] > 0),
        ("la marca de agua avanzó", tras["marca_agua_nueva"] is not None and tras["marca_agua_anterior"] is not None
         and tras["marca_agua_nueva"] > tras["marca_agua_anterior"]),
        ("sin llegada, la franja siguiente leyó 0 filas", sin["estado"] == "ok" and sin["filas_leidas"] == 0),
        ("las filas modificadas no se duplicaron en demanda_observada", totales["demanda_observada"] == esperado),
        ("ninguna ejecución de frecuencia se creó con POST", manuales == 0),
    ]
    for nombre, ok in comprobaciones:
        log(f"   [{'OK' if ok else 'FALLA'}] {nombre}")
    log()
    log("RESULTADO: " + ("TODO OK" if all(ok for _, ok in comprobaciones) else "HAY FALLAS"))
    resumen.update({"llegada": info, "franjas": [{k: (str(v) if not isinstance(v, (int, float, type(None))) else v)
                                                  for k, v in x.items() if k != "metricas"} for x in todas],
                    "totales": totales, "manuales": manuales,
                    "comprobaciones": {n: ok for n, ok in comprobaciones}})
    if a.salida:
        a.salida.parent.mkdir(parents=True, exist_ok=True)
        a.salida.write_text("\n".join(LINEAS) + "\n", encoding="utf-8")
    if a.json:
        a.json.parent.mkdir(parents=True, exist_ok=True)
        a.json.write_text(json.dumps(resumen, ensure_ascii=False, indent=1, default=str) + "\n", encoding="utf-8")
    motor.dispose()
    shutil.rmtree(copia.parent, ignore_errors=True)
    if not all(ok for _, ok in comprobaciones):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
