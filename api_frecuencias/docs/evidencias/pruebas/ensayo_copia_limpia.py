"""Ensayo del CI en una copia limpia del repositorio, como lo ve GitHub Actions o un jurado al clonar.

Uso (desde EntregaFinal/api_frecuencias, con el venv y el PostgreSQL local de pruebas arriba):
    .venv\\Scripts\\python docs\\evidencias\\pruebas\\ensayo_copia_limpia.py --destino <carpeta temporal> [--caida]

1. Copia SOLO lo que git versiona («git ls-files -co --exclude-standard» de la API y de .github/workflows), con el fin
   de línea de un checkout de Linux: lo que git guarda normalizado llega con LF y lo marcado «-text» (datos/modelos/**,
   que se verifica con su SHA-256) llega byte a byte. Sin .env, sin la carpeta datos/ de la raíz y sin dash_app/.
2. Corre scripts/ci_local.py dentro de la copia (los mismos pasos del job «pruebas» del flujo) con un entorno sin
   variables del proyecto y la réplica inalcanzable a propósito (puerto cerrado y un contenedor que no existe).
3. Con --caida corre además el segundo job del flujo: PRUEBA_CAIDA=1 PRUEBA_PLANIFICADOR=1 pytest
   tests/integracion/test_caida.py tests/integracion/test_planificador_programado.py.
La base de pruebas es TEST_DATABASE_NAME (por omisión ai_frecuencias_pruebas_copia_limpia) en el PostgreSQL LOCAL de
TEST_DATABASE_URL o, si falta, del DATABASE_URL del .env; la URL nunca se imprime. Nada se escribe en el repositorio:
la copia, el log y los reportes quedan en --destino.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess  # noqa: S404 - solo git y el propio intérprete, con argumentos fijos
import sys
import time
from pathlib import Path

API = Path(__file__).resolve().parents[3]
HOSTS_LOCALES = {"localhost", "127.0.0.1", "::1"}
# variables del proyecto que una máquina limpia no tiene (se quitan del entorno heredado)
DEL_PROYECTO = ("DATABASE", "CATALOGOS", "REPLICA", "FUENTE", "LECTOR", "ESCRITOR", "OPERACIONAL", "DATA_DIR",
                "MODELOS_DIR", "API_KEY", "SOBUSA", "SEUDONIMO", "AUTH_", "DOCS_", "ENTORNO")


def _git(*args: str, cwd: Path) -> bytes:
    return subprocess.run(["git", "-c", "core.quotepath=off", *args], cwd=cwd, capture_output=True,  # noqa: S603, S607
                          check=True).stdout


def copiar(destino: Path) -> tuple[Path, int, int]:
    raiz = Path(_git("rev-parse", "--show-toplevel", cwd=API).decode().strip())
    api_rel = API.relative_to(raiz).as_posix()
    rutas = [api_rel, ".github/workflows"]
    archivos = [a for a in _git("ls-files", "-co", "--exclude-standard", "-z", *rutas, cwd=raiz).decode().split("\0")
                if a]
    indice = {}
    for registro in _git("ls-files", "--eol", "-z", *rutas, cwd=raiz).decode().split("\0"):
        if "\t" in registro:
            info, ruta = registro.split("\t", 1)
            indice[ruta] = " ".join(info.split())
    if destino.exists():
        shutil.rmtree(destino)
    copiados = a_lf = 0
    for rel in archivos:
        origen = raiz / rel
        if not origen.is_file():
            continue
        contenido = origen.read_bytes()
        info = indice.get(rel, "")
        byte_a_byte = ("attr/-text" in info or "eol=crlf" in info or (info and not info.startswith("i/lf"))
                       or rel.startswith(f"{api_rel}/datos/modelos/") or b"\0" in contenido[:8000])
        if not byte_a_byte and b"\r\n" in contenido:
            contenido = contenido.replace(b"\r\n", b"\n")
            a_lf += 1
        final = destino / rel
        final.parent.mkdir(parents=True, exist_ok=True)
        final.write_bytes(contenido)
        copiados += 1
    return destino / api_rel, copiados, a_lf


def url_local() -> str:
    from sqlalchemy.engine import make_url

    url = os.environ.get("TEST_DATABASE_URL", "")
    if not url and (API / ".env").exists():
        for linea in (API / ".env").read_text(encoding="utf-8").splitlines():
            if linea.startswith("DATABASE_URL="):
                url = linea.split("=", 1)[1].strip().strip("'\"")
    if not url or make_url(url).host not in HOSTS_LOCALES:
        raise SystemExit("Hace falta un PostgreSQL LOCAL de pruebas (TEST_DATABASE_URL o DATABASE_URL del .env)")
    return url


def entorno(base: str) -> dict:
    env = {k: v for k, v in os.environ.items() if not any(p in k.upper() for p in DEL_PROYECTO)}
    env.update({"TEST_DATABASE_URL": url_local(), "TEST_DATABASE_NAME": base, "REANUDAR_EJECUCIONES": "false",
                "PYTHONDONTWRITEBYTECODE": "1", "TESTCONTAINERS": env.get("TESTCONTAINERS", "1"),
                "SCHEMATHESIS_EJEMPLOS": env.get("SCHEMATHESIS_EJEMPLOS", "10"), "PYTHONIOENCODING": "utf-8",
                "OPERACIONAL_PUERTO_HOST": "5499", "REPLICA_CONTENEDOR": "no_existe_copia_limpia"})
    if os.name != "nt":
        env["TZ"] = "America/Bogota"          # en Windows la zona del equipo ya es la de Bogotá
    return env


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--destino", required=True, help="carpeta temporal fuera del repositorio")
    p.add_argument("--caida", action="store_true", help="corre también el job de caída (RNF-001)")
    p.add_argument("--base", default=os.environ.get("TEST_DATABASE_NAME", "ai_frecuencias_pruebas_copia_limpia"))
    a = p.parse_args()
    destino = Path(a.destino).resolve()
    if destino == API or API in destino.parents:
        raise SystemExit("--destino debe quedar fuera del repositorio")
    copia, n, a_lf = copiar(destino / "repo")
    salida = destino / "salida"
    salida.mkdir(parents=True, exist_ok=True)
    print(f"Copia limpia: {n} archivos ({a_lf} con LF como en Linux); .env presente: {(copia / '.env').exists()}; "
          f"datos/ de la raíz presente: {(copia.parents[1] / 'datos').exists()}", flush=True)
    env = entorno(a.base)
    t0 = time.perf_counter()
    r = subprocess.run([sys.executable, "scripts/ci_local.py", "--salida", str(salida / "ci_local.txt"),  # noqa: S603
                        "--reportes", str(salida / "reportes")], cwd=copia, env=env)
    print(f"ci_local: código {r.returncode} en {time.perf_counter() - t0:.1f} s", flush=True)
    codigo = r.returncode
    if a.caida:
        from sqlalchemy.engine import make_url

        env_caida = dict(env, PRUEBA_CAIDA="1", PRUEBA_PLANIFICADOR="1",
                         DATABASE_URL=make_url(env["TEST_DATABASE_URL"]).set(database=a.base)
                         .render_as_string(hide_password=False))
        t0 = time.perf_counter()
        with (salida / "caida.txt").open("w", encoding="utf-8") as log:
            rc = subprocess.run([sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-rfEs",  # noqa: S603
                                 "tests/integracion/test_caida.py",
                                 "tests/integracion/test_planificador_programado.py"],
                                cwd=copia, env=env_caida, stdout=log, stderr=subprocess.STDOUT)
        print(f"caida: código {rc.returncode} en {time.perf_counter() - t0:.1f} s", flush=True)
        codigo = codigo or rc.returncode
    print(f"Log y reportes en {salida}")
    return codigo


if __name__ == "__main__":
    sys.exit(main())
