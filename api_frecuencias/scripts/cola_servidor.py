"""Réplicas locales de la API para las pruebas de cola, réplicas y caída (RNF-001, RNF-005).

Como programa: lanza UNA réplica (uvicorn) con pausas opcionales inyectadas en la lectura incremental y en cada
predicción, para que un SIGKILL caiga con certeza DENTRO de esa etapa. La inyección vive solo aquí (el código de
la API no cambia):

    python scripts/cola_servidor.py --puerto 8103 --pausa-lectura 3 --pausa-prediccion 0.8

Como módulo: Replica (arrancar, esperar /health, matar sin aviso), Cliente HTTP (envía X-API-Key si existe
SOBUSA_API_KEY) y utilidades de base. Solo contra un PostgreSQL LOCAL: la URL sale de app.config (archivo .env
local o DATABASE_URL) con la base de pruebas indicada, y nunca se imprime.

Nota Windows: Popen.kill() es TerminateProcess, el equivalente de SIGKILL (kill -9): el proceso muere sin correr
finally, atexit ni el apagado de uvicorn, y PostgreSQL revierte su transacción abierta al cortarse la conexión.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
HOSTS_LOCALES = {"localhost", "127.0.0.1", "db", "::1"}
sys.path.insert(0, str(RAIZ))


# ---------------------------------------------------------------- base local de pruebas
def url_local(base_datos: str) -> str:
    """URL de la base LOCAL de pruebas (misma regla que tests/integracion/conftest.py)."""
    from sqlalchemy.engine import make_url

    from app.config import Ajustes

    url = make_url(os.environ.get("DATABASE_URL") or Ajustes().database_url)
    if url.host not in HOSTS_LOCALES:
        raise SystemExit(f"Solo contra un PostgreSQL local (host={url.host!r})")
    return url.set(database=base_datos).render_as_string(hide_password=False)


def preparar_base(url: str) -> None:
    """Crea la base si no existe y la migra hasta head (alembic)."""
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url

    u = make_url(url)
    admin = create_engine(u.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        if not c.execute(text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": u.database}).scalar():
            c.execute(text(f'CREATE DATABASE "{u.database}"'))
    admin.dispose()
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=RAIZ, check=True,  # noqa: S603
                   env=os.environ | {"DATABASE_URL": url}, capture_output=True)


def motor(url: str):
    from sqlalchemy import create_engine

    return create_engine(url, pool_pre_ping=True, connect_args={"options": "-c timezone=America/Bogota"})


# ---------------------------------------------------------------- réplicas
class Replica:
    def __init__(self, nombre: str, puerto: int, url: str, carpeta_logs: Path, **entorno: str):
        self.nombre, self.puerto, self.url = nombre, puerto, url
        self.log_path = carpeta_logs / f"replica_{nombre}.log"
        self.log_path.unlink(missing_ok=True)  # cada corrida empieza su propio log
        self.entorno = entorno
        self.proc: subprocess.Popen | None = None
        self.arranques = 0

    def arrancar(self, pausa_lectura: float = 0.0, pausa_prediccion: float = 0.0) -> float:
        env = os.environ | {
            "DATABASE_URL": self.url, "TRABAJADOR_ID": self.nombre, "REANUDAR_EJECUCIONES": "true",
            "TRABAJADORES": "1", "MAX_REINTENTOS": "3", "AUTH_HABILITADA": "false", "LOG_NIVEL": "INFO",
            "PLANIFICADOR_HABILITADO": "false", "PYTHONIOENCODING": "utf-8"} | self.entorno
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        salida = open(self.log_path, "a", encoding="utf-8")  # noqa: SIM115 - vive mientras viva el proceso
        salida.write(f"\n===== arranque {self.arranques + 1} de {self.nombre} ({time.strftime('%H:%M:%S')}) =====\n")
        salida.flush()
        t0 = time.time()
        self.proc = subprocess.Popen(  # noqa: S603
            [sys.executable, str(Path(__file__).resolve()), "--puerto", str(self.puerto),
             "--pausa-lectura", str(pausa_lectura), "--pausa-prediccion", str(pausa_prediccion)],
            cwd=RAIZ, env=env, stdout=salida, stderr=subprocess.STDOUT)
        self.arranques += 1
        self.esperar_salud()
        return time.time() - t0

    def esperar_salud(self, limite_s: float = 120.0) -> None:
        fin = time.time() + limite_s
        while time.time() < fin:
            if self.proc is not None and self.proc.poll() is not None:
                raise RuntimeError(f"La réplica {self.nombre} terminó al arrancar (ver {self.log_path})")
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{self.puerto}/health", timeout=3) as r:  # nosec B310  # URL fija a 127.0.0.1  # noqa: S310
                    if r.status == 200:
                        return
            except (urllib.error.URLError, OSError):
                pass
            time.sleep(0.3)
        raise TimeoutError(f"La réplica {self.nombre} no respondió /health")

    def matar(self) -> None:
        """SIGKILL (TerminateProcess en Windows): sin apagado ordenado."""
        if self.proc is not None and self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait(timeout=30)

    def volcar_log(self) -> None:
        """El log ya está en log_path (el proceso escribe ahí)."""

    def parar(self) -> None:
        self.matar()


class ReplicaDocker(Replica):
    """La misma réplica dentro de un contenedor Linux de la imagen de la API: matar() = docker kill (SIGKILL real).

    La URL de la base se pasa en un --env-file temporal (carpeta ignorada por git) que se borra al parar; el
    contenedor se elimina al final. Reiniciar = docker start del MISMO contenedor (misma identidad de réplica).
    """

    def __init__(self, nombre: str, puerto: int, url: str, carpeta_logs: Path, imagen: str, **entorno: str):
        super().__init__(nombre, puerto, url, carpeta_logs, **entorno)
        self.imagen, self.contenedor = imagen, f"sobusa_cola_{nombre}"
        self.env_file = carpeta_logs / f"{nombre}.env"
        subprocess.run(["docker", "rm", "-f", self.contenedor], capture_output=True)  # noqa: S603,S607

    def arrancar(self, pausa_lectura: float = 0.0, pausa_prediccion: float = 0.0) -> float:
        from sqlalchemy.engine import make_url

        t0 = time.time()
        if self.arranques:
            subprocess.run(["docker", "start", self.contenedor], check=True, capture_output=True)  # noqa: S603,S607
        else:
            env = {"DATABASE_URL": make_url(self.url).set(host="host.docker.internal").render_as_string(
                       hide_password=False),
                   "TRABAJADOR_ID": self.nombre, "REANUDAR_EJECUCIONES": "true", "TRABAJADORES": "1",
                   "MAX_REINTENTOS": "3", "AUTH_HABILITADA": "false", "LOG_NIVEL": "INFO",
                   "PLANIFICADOR_HABILITADO": "false"} | self.entorno
            self.env_file.parent.mkdir(parents=True, exist_ok=True)
            self.env_file.write_text("\n".join(f"{k}={v}" for k, v in env.items()) + "\n", encoding="utf-8")
            subprocess.run(["docker", "run", "-d", "--name", self.contenedor, "--env-file", str(self.env_file),  # noqa: S603,S607
                            "-p", f"127.0.0.1:{self.puerto}:8000", "-v", f"{RAIZ / 'scripts'}:/app/scripts:ro",
                            self.imagen, "python", "scripts/cola_servidor.py", "--puerto", "8000", "--host",
                            "0.0.0.0", "--pausa-lectura", str(pausa_lectura),  # nosec B104  # solo dentro del contenedor de prueba  # noqa: S104 - dentro del contenedor
                            "--pausa-prediccion", str(pausa_prediccion)], check=True, capture_output=True)
        self.arranques += 1
        self.esperar_salud()
        return time.time() - t0

    def matar(self) -> None:
        """docker kill: SIGKILL al proceso de la API dentro del contenedor Linux."""
        subprocess.run(["docker", "kill", self.contenedor], capture_output=True)  # noqa: S603,S607

    def volcar_log(self) -> None:
        r = subprocess.run(["docker", "logs", self.contenedor], capture_output=True, text=True,  # noqa: S603,S607
                           encoding="utf-8", errors="replace")
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.log_path.write_text(r.stdout + r.stderr, encoding="utf-8")

    def parar(self) -> None:
        if self.arranques:
            self.volcar_log()
        subprocess.run(["docker", "rm", "-f", self.contenedor], capture_output=True)  # noqa: S603,S607
        self.env_file.unlink(missing_ok=True)


class Cliente:
    def __init__(self, puerto: int):
        self.base = f"http://127.0.0.1:{puerto}"

    def pedir(self, metodo: str, ruta: str, cuerpo: dict | None = None, cid: str = "prueba-cola") -> dict:
        cabeceras = {"Content-Type": "application/json", "X-Correlation-Id": cid}
        if os.environ.get("SOBUSA_API_KEY"):
            cabeceras["X-API-Key"] = os.environ["SOBUSA_API_KEY"]
        datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
        req = urllib.request.Request(self.base + ruta, data=datos, method=metodo,  # noqa: S310 - 127.0.0.1
                                     headers=cabeceras)
        with urllib.request.urlopen(req, timeout=30) as r:  # nosec B310  # URL fija a 127.0.0.1  # noqa: S310 - solo 127.0.0.1
            return json.loads(r.read().decode())


def lineas_de_log(ruta: Path, claves: tuple[str, ...]) -> list[str]:
    """Líneas del log de una réplica que contienen alguna clave, como «hora réplica mensaje» (logs JSON o texto)."""
    salida = []
    for x in ruta.read_text(encoding="utf-8", errors="replace").splitlines():
        if not any(c in x.lower() for c in claves):
            continue
        try:
            d = json.loads(x)
            mensaje = d.get("mensaje") or d.get("message")
            salida.append(f"{str(d.get('ts', ''))[11:19]} {d.get('worker_id') or ''} {mensaje}")
        except ValueError:
            salida.append(x.strip()[:240])
    return salida


# ---------------------------------------------------------------- servidor con pausas inyectadas
def servir(puerto: int, pausa_lectura: float, pausa_prediccion: float, host: str = "127.0.0.1") -> None:
    if pausa_lectura > 0:
        from app.servicios import fuentes

        leer = fuentes.FuenteParquet.leer_incremental

        def leer_lento(self, *a, **k):
            time.sleep(pausa_lectura)
            return leer(self, *a, **k)

        fuentes.FuenteParquet.leer_incremental = leer_lento
    if pausa_prediccion > 0:
        from app.servicios import inferencia

        predecir = inferencia.predecir

        def predecir_lento(*a, **k):
            r = predecir(*a, **k)
            time.sleep(pausa_prediccion)
            return r

        inferencia.predecir = predecir_lento
    import uvicorn

    uvicorn.run("app.main:app", host=host, port=puerto, log_level="warning")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--puerto", type=int, required=True)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--pausa-lectura", type=float, default=0.0)
    p.add_argument("--pausa-prediccion", type=float, default=0.0)
    a = p.parse_args()
    servir(a.puerto, a.pausa_lectura, a.pausa_prediccion, a.host)


if __name__ == "__main__":
    main()
