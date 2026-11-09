"""Utilidades compartidas de la réplica operacional (scripts/replica_*.py y tests/replica).

Solo se conectan a un servidor LOCAL (la réplica en el puerto 5434 o el servicio «operacional» de compose): nunca a la
base compartida del reto. Las claves salen del entorno o del .env local y nunca se imprimen.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from urllib.parse import quote, urlsplit

RAIZ = Path(__file__).resolve().parents[1]
HOSTS_LOCALES = {"localhost", "127.0.0.1", "::1", "operacional"}
CONTENEDOR = "sobusa_rep-operacional-1"

# Escrituras que lector_ia NO puede hacer. Cada una se prueba dos veces: con la sesión por defecto (transacción de
# solo lectura) y después de desactivar default_transaction_read_only (debe fallar por permisos).
ESCRITURAS_LECTOR = [
    ("update", "UPDATE public.timbradas_consolidado SET subidas = subidas WHERE false"),
    ("insert", "INSERT INTO public.timbradas_consolidado (proceso) VALUES ('x')"),
    ("delete", "DELETE FROM public.timbradas_consolidado WHERE false"),
    ("truncate", "TRUNCATE public.timbradas_consolidado"),
    ("copy_from", "COPY public.timbradas_consolidado (proceso) FROM STDIN"),
    ("create_public", "CREATE TABLE public.intruso (x int)"),
    ("create_temp", "CREATE TEMP TABLE intruso (x int)"),
    ("create_ai_frecuencias", "CREATE TABLE ai_frecuencias.intruso (x int)"),
    ("create_schema", "CREATE SCHEMA intruso"),
    ("alter_table", "ALTER TABLE public.timbradas_consolidado ADD COLUMN intruso int"),
    ("drop_table", "DROP TABLE public.timbradas_consolidado"),
    ("lock_exclusivo", "LOCK TABLE public.timbradas_consolidado IN ACCESS EXCLUSIVE MODE"),
    ("nextval", "SELECT nextval('public.timbradas_anio_id_timbrada_anio_seq')"),
    ("fn_insert_timbradas_anio", "SELECT public.fn_insert_timbradas_anio(1)"),
    ("fn_consolidar_timbradas_historicas", "SELECT public.fn_consolidar_timbradas_historicas()"),
    ("fn_segmentar_ruta", "SELECT public.fn_segmentar_ruta(2, 'distancia', 500, 0.2, 0.2)"),
]


def _env_local() -> dict[str, str]:
    """Valores del .env local SIN copiarlos a os.environ (no altera la configuración de otras pruebas)."""
    try:
        from dotenv import dotenv_values
    except ImportError:  # pragma: no cover
        return {}
    archivo = RAIZ / ".env"
    return {k: v for k, v in dotenv_values(archivo).items() if v} if archivo.exists() else {}


def valor(nombre: str, defecto: str | None = None) -> str | None:
    """Variable del entorno o, si no está, del .env local."""
    return os.environ.get(nombre) or _env_local().get(nombre) or defecto


def _verificar_local(url: str) -> str:
    url = url.replace("postgresql+psycopg://", "postgresql://")
    host = urlsplit(url).hostname
    if host not in HOSTS_LOCALES:
        raise ValueError(f"la réplica solo se usa en un servidor local (host={host!r})")
    return url


def url_rol(rol: str) -> str | None:
    """URL de la réplica para extreme_dba, lector_ia o escritor_ia (None si falta la clave)."""
    if rol == "extreme_dba" and valor("REPLICA_URL"):
        return _verificar_local(valor("REPLICA_URL"))
    variable = {"extreme_dba": "OPERACIONAL_PASSWORD", "lector_ia": "LECTOR_IA_PASSWORD",
                "escritor_ia": "ESCRITOR_IA_PASSWORD"}[rol]
    clave = valor(variable)
    if not clave:
        return None
    host = valor("REPLICA_HOST", "localhost")
    puerto = valor("OPERACIONAL_PUERTO_HOST", "5434")
    return _verificar_local(f"postgresql://{rol}:{quote(clave, safe='')}@{host}:{puerto}/operacional")


def contenedor() -> str:
    return os.environ.get("REPLICA_CONTENEDOR", CONTENEDOR)


def psql(base: str, *args: str, timeout: int = 300) -> subprocess.CompletedProcess:
    """psql DENTRO del contenedor de la réplica (como extreme_dba): el comportamiento real de psql con los scripts."""
    cmd = ["docker", "exec", contenedor(), "psql", "-X", "-U", "extreme_dba", "-d", base, *args]
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",  # noqa: S603
                          timeout=timeout, check=False)


def docker_disponible() -> bool:
    try:
        r = subprocess.run(["docker", "inspect", "-f", "{{.State.Running}}", contenedor()],  # noqa: S603, S607
                           capture_output=True, text=True, timeout=15, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return r.returncode == 0 and r.stdout.strip() == "true"
