"""Ensayo local de la integración continua (spec v1.5 §14.2 «las pruebas automatizadas pasan en integración
continua», RNF-007, RNF-014, E08): los MISMOS pasos del flujo .github/workflows/api_frecuencias.yml, sin gh ni Actions.

Uso (desde EntregaFinal/api_frecuencias, con el venv):
    python scripts/ci_local.py              # todos los pasos; escribe el log y los reportes
    python scripts/ci_local.py openapi      # solo «OpenAPI sin deriva» (sale con 1 si docs/openapi.json no está al día)
    python scripts/ci_local.py resumen reportes/pytest.xml reportes/coverage.xml   # Markdown (GITHUB_STEP_SUMMARY)

Pasos: 1) ruff sobre todo el repositorio  2) bandit -ll sobre app/ y scripts/  3) alembic upgrade → downgrade →
upgrade en una base local DE PRUEBAS  4) pytest con
cobertura ≥ 85 % y junit (unitarias, integración, contrato, datos/ML y Testcontainers con TESTCONTAINERS=1)
5) OpenAPI sin deriva. Cada paso guarda su código de salida (sin tuberías: no hay «tail» que oculte un fallo).
La base de pruebas es TEST_DATABASE_NAME (por omisión ai_frecuencias_pruebas_ci) en el PostgreSQL local de
DATABASE_URL o TEST_DATABASE_URL; nunca se conecta a otra máquina y nunca imprime la URL (lleva la clave).
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import time
import xml.etree.ElementTree as ET  # noqa: S405 - solo lee reportes junit/cobertura que genera este mismo script
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
UMBRAL_COBERTURA = 85
HOSTS_LOCALES = {"localhost", "127.0.0.1", "db", "::1"}


# ---------------------------------------------------------------- OpenAPI sin deriva
def _normalizar(doc: dict) -> str:
    return json.dumps(doc, ensure_ascii=False, sort_keys=True, indent=1)


def diferencias_openapi(versionado: dict, generado: dict) -> list[str]:
    difs = []
    rutas_v = {(m, p) for p, ops in versionado.get("paths", {}).items() for m in ops}
    rutas_g = {(m, p) for p, ops in generado.get("paths", {}).items() for m in ops}
    difs += [f"operación nueva sin versionar: {m.upper()} {p}" for m, p in sorted(rutas_g - rutas_v)]
    difs += [f"operación versionada que ya no existe: {m.upper()} {p}" for m, p in sorted(rutas_v - rutas_g)]
    for m, p in sorted(rutas_v & rutas_g):
        if _normalizar(versionado["paths"][p][m]) != _normalizar(generado["paths"][p][m]):
            difs.append(f"operación cambiada: {m.upper()} {p}")
    comp_v = versionado.get("components", {})
    comp_g = generado.get("components", {})
    for grupo in sorted(set(comp_v) | set(comp_g)):
        a, b = comp_v.get(grupo, {}), comp_g.get(grupo, {})
        for nombre in sorted(set(a) | set(b)):
            if nombre not in a:
                difs.append(f"components.{grupo}.{nombre}: nuevo sin versionar")
            elif nombre not in b:
                difs.append(f"components.{grupo}.{nombre}: ya no existe")
            elif _normalizar(a[nombre]) != _normalizar(b[nombre]):
                difs.append(f"components.{grupo}.{nombre}: cambiado")
    for clave in ("openapi", "info"):
        if _normalizar({clave: versionado.get(clave)}) != _normalizar({clave: generado.get(clave)}):
            difs.append(f"{clave}: cambiado")
    return difs


def verificar_openapi(ruta: Path) -> tuple[int, str]:
    os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://sin-conexion@localhost:1/x")
    sys.path.insert(0, str(RAIZ))
    from app.main import app

    generado = app.openapi()
    versionado = json.loads(ruta.read_text(encoding="utf-8"))
    difs = diferencias_openapi(versionado, generado)
    if not difs:
        return 0, f"OpenAPI sin deriva: {ruta.name} coincide con el generado ({len(generado['paths'])} rutas)."
    texto = [f"DERIVA: {ruta.name} no coincide con el OpenAPI que genera el código ({len(difs)} diferencias).",
             "Regenérelo con: python -c \"import json; from app.main import app; "
             "open('docs/openapi.json','w',encoding='utf-8').write(json.dumps(app.openapi(), ensure_ascii=False, "
             "indent=2))\"", *[f"  - {d}" for d in difs[:60]]]
    if len(difs) > 60:
        texto.append(f"  … y {len(difs) - 60} más")
    return 1, "\n".join(texto)


# ---------------------------------------------------------------- resumen de junit y cobertura
def resumen(junit: Path, cobertura: Path | None) -> str:
    raiz = ET.parse(junit).getroot()  # nosec B314  # XML local generado por pytest/coverage en esta corrida  # noqa: S314 - archivo local generado por pytest
    suites = [raiz] if raiz.tag == "testsuite" else list(raiz.iter("testsuite"))
    tot = {k: sum(int(s.get(k, 0)) for s in suites) for k in ("tests", "failures", "errors", "skipped")}
    tiempo = sum(float(s.get("time", 0)) for s in suites)
    por_nivel: dict[str, dict[str, int]] = {}
    for caso in raiz.iter("testcase"):
        partes = (caso.get("classname") or "").split(".")
        nivel = partes[1] if len(partes) > 1 and partes[0] == "tests" else "otros"
        d = por_nivel.setdefault(nivel, {"pruebas": 0, "fallas": 0, "omitidas": 0})
        d["pruebas"] += 1
        if caso.find("failure") is not None or caso.find("error") is not None:
            d["fallas"] += 1
        elif caso.find("skipped") is not None:
            d["omitidas"] += 1
    lineas = ["### Pruebas de la API de frecuencias", "",
              f"**{tot['tests']} pruebas**: {tot['tests'] - tot['failures'] - tot['errors'] - tot['skipped']} pasan, "
              f"{tot['failures']} fallan, {tot['errors']} con error y {tot['skipped']} omitidas o xfail, "
              f"en {tiempo:.1f} s.", "", "| Nivel (§14.1) | Pruebas | Fallas | Omitidas/xfail |",
              "|---|---:|---:|---:|"]
    lineas += [f"| {n} | {d['pruebas']} | {d['fallas']} | {d['omitidas']} |" for n, d in sorted(por_nivel.items())]
    if cobertura and cobertura.exists():
        cov = ET.parse(cobertura).getroot()  # nosec B314  # XML local generado por pytest/coverage en esta corrida  # noqa: S314 - archivo local generado por coverage.py
        pct = float(cov.get("line-rate", 0)) * 100
        lineas += ["", f"**Cobertura de líneas de app/**: {pct:.1f} % (umbral {UMBRAL_COBERTURA} %, "
                       f"{cov.get('lines-covered')} de {cov.get('lines-valid')} líneas)."]
    return "\n".join(lineas)


# ---------------------------------------------------------------- base local de pruebas
def url_base_pruebas() -> str:
    """URL de la base de pruebas en el PostgreSQL LOCAL (la crea si no existe). Nunca se imprime."""
    sys.path.insert(0, str(RAIZ))
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url

    if os.environ.get("TEST_DATABASE_URL"):
        base = os.environ["TEST_DATABASE_URL"]
    else:
        from app.config import Ajustes

        base = Ajustes().database_url
    url = make_url(base)
    if url.host not in HOSTS_LOCALES:
        raise SystemExit(f"ci_local solo corre contra un PostgreSQL local (host={url.host!r})")
    nombre = os.environ.get("TEST_DATABASE_NAME", "ai_frecuencias_pruebas_ci")
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT",
                          connect_args={"connect_timeout": 5})
    with admin.connect() as c:
        if not c.execute(text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": nombre}).scalar():
            c.execute(text(f'CREATE DATABASE "{nombre}"'))
    admin.dispose()
    return url.set(database=nombre).render_as_string(hide_password=False)


# ---------------------------------------------------------------- pasos
def correr(nombre: str, comando: list[str], log, entorno: dict | None = None, permitido: tuple[int, ...] = (0,)):
    log.write(f"\n## {nombre}\n$ {' '.join(comando)}\n")
    log.flush()
    t0 = time.perf_counter()
    r = subprocess.run(comando, cwd=RAIZ, env=entorno or os.environ.copy(),  # noqa: S603 - comandos fijos del CI
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                       errors="replace")
    seg = time.perf_counter() - t0
    log.write(r.stdout[-20000:] if len(r.stdout) > 20000 else r.stdout)
    estado = "OK" if r.returncode in permitido else "FALLA"
    log.write(f"\n[{estado}] {nombre}: código de salida {r.returncode} en {seg:.1f} s\n")
    log.flush()
    print(f"[{estado}] {nombre}: código {r.returncode} en {seg:.1f} s", flush=True)
    return {"paso": nombre, "codigo": r.returncode, "segundos": round(seg, 1), "ok": r.returncode in permitido}


def todo(salida: Path, reportes: Path, rapido: bool) -> int:
    reportes.mkdir(parents=True, exist_ok=True)
    salida.parent.mkdir(parents=True, exist_ok=True)
    py = sys.executable
    pasos = []
    with salida.open("w", encoding="utf-8") as log:
        log.write(f"# Ensayo local del CI de la API de frecuencias\nInicio: {datetime.now().astimezone().isoformat()}\n"
                  f"Python {platform.python_version()} en {platform.platform()}\n"
                  f"Flujo equivalente: .github/workflows/api_frecuencias.yml (job «pruebas»)\n")
        pasos.append(correr("ruff (estilo, errores y reglas S de seguridad)",
                            [py, "-m", "ruff", "check", ".", "--output-format", "concise"], log))
        pasos.append(correr("bandit (seguridad, severidad media o mayor)",
                            [py, "-m", "bandit", "-r", "app", "scripts", "-c", "pyproject.toml", "-ll", "-q"], log))
        entorno = os.environ.copy()
        entorno["DATABASE_URL"] = url_base_pruebas()
        entorno.update({"REANUDAR_EJECUCIONES": "false", "PYTHONDONTWRITEBYTECODE": "1"})
        alembic = [py, "-m", "alembic"]
        for paso in (["upgrade", "head"], ["downgrade", "base"], ["upgrade", "head"]):
            pasos.append(correr(f"alembic {' '.join(paso)}", alembic + paso, log, entorno))
        entorno_pytest = dict(entorno)
        entorno_pytest.setdefault("TESTCONTAINERS", "1")
        entorno_pytest.pop("DATABASE_URL")          # el conftest de integración arma la URL de su base de pruebas
        comando = [py, "-m", "pytest", "-p", "no:cacheprovider", "-rfE", "--cov=app",
                   f"--cov-report=xml:{reportes / 'coverage.xml'}", "--cov-report=term:skip-covered",
                   f"--cov-fail-under={UMBRAL_COBERTURA}", f"--junitxml={reportes / 'pytest.xml'}"]
        if rapido:
            comando += ["-m", "not testcontainers"]
        pasos.append(correr("pytest con cobertura ≥ 85 % y junit", comando, log, entorno_pytest))
        codigo, texto = verificar_openapi(RAIZ / "docs" / "openapi.json")
        log.write(f"\n## OpenAPI sin deriva\n{texto}\n[{'OK' if codigo == 0 else 'FALLA'}] OpenAPI sin deriva\n")
        print(f"[{'OK' if codigo == 0 else 'FALLA'}] OpenAPI sin deriva", flush=True)
        pasos.append({"paso": "OpenAPI sin deriva", "codigo": codigo, "segundos": 0, "ok": codigo == 0})
        if (reportes / "pytest.xml").exists():
            log.write("\n## Resumen (lo que el CI publica en GITHUB_STEP_SUMMARY)\n")
            log.write(resumen(reportes / "pytest.xml", reportes / "coverage.xml") + "\n")
        log.write("\n## Pasos\n| Paso | Código | Segundos | Resultado |\n|---|---:|---:|---|\n")
        log.writelines(f"| {p['paso']} | {p['codigo']} | {p['segundos']} | {'OK' if p['ok'] else 'FALLA'} |\n"
                       for p in pasos)
        fallidos = [p["paso"] for p in pasos if not p["ok"]]
        log.write(f"\nFin: {datetime.now().astimezone().isoformat()}. "
                  f"{'CI EN VERDE' if not fallidos else 'CI EN ROJO por: ' + '; '.join(fallidos)}\n")
    (reportes / "pasos.json").write_text(json.dumps(pasos, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0 if not fallidos else 1


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("accion", nargs="?", default="todo", choices=["todo", "openapi", "resumen"])
    p.add_argument("archivos", nargs="*", help="resumen: junit.xml [coverage.xml]")
    p.add_argument("--salida", default=str(RAIZ / "reportes" / "tmp" / "ci_local" / "ci_local.txt"))
    p.add_argument("--reportes", default=str(RAIZ / "reportes" / "tmp" / "ci_local"))
    p.add_argument("--rapido", action="store_true", help="sin las pruebas de Testcontainers")
    a = p.parse_args()
    if a.accion == "openapi":
        codigo, texto = verificar_openapi(Path(a.archivos[0]) if a.archivos else RAIZ / "docs" / "openapi.json")
        print(texto)
        return codigo
    if a.accion == "resumen":
        print(resumen(Path(a.archivos[0]), Path(a.archivos[1]) if len(a.archivos) > 1 else None))
        return 0
    return todo(Path(a.salida), Path(a.reportes), a.rapido)


if __name__ == "__main__":
    sys.exit(main())
