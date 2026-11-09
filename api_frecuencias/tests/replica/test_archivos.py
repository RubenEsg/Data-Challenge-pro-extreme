"""Archivos de la réplica (sin base de datos; corren también en CI): DDL generado al día, finales de línea, sintaxis
de los .sh de inicialización y que las herramientas de la réplica nunca apunten a un servidor que no sea local."""
from __future__ import annotations

import shutil
import subprocess

import pytest

from scripts import replica_comun as rc

REPLICA = rc.RAIZ / "replica"


def test_ddl_generado_al_dia():
    """replica/initdb/10_base_operacional.sql es exactamente lo que genera scripts/replica_generar_ddl.py."""
    from scripts import replica_generar_ddl as g

    if not (g.DATOS / "Procesos.parquet").exists():
        pytest.skip("exportaciones Parquet no disponibles")
    assert g.SALIDA.read_bytes().decode("utf-8") == g.generar()


@pytest.mark.parametrize("carpeta", ["initdb", "errata"])
def test_inicializacion_con_finales_lf_y_utf8(carpeta):
    """Los .sh y .sql corren dentro del contenedor Linux: un CRLF rompe bash («$'\\r': command not found»)."""
    archivos = sorted((REPLICA / carpeta).glob("*.*"))
    assert archivos
    for archivo in archivos:
        contenido = archivo.read_bytes()
        assert b"\r\n" not in contenido, archivo.name
        contenido.decode("utf-8")


def test_scripts_de_extreme_conservan_crlf():
    """La copia es byte a byte: los originales de Extreme traen CRLF y así deben quedar (replica/.gitattributes)."""
    for archivo in (REPLICA / "extreme").glob("*.sql"):
        assert b"\r\n" in archivo.read_bytes(), archivo.name
    assert "extreme/** -text" in (REPLICA / ".gitattributes").read_text(encoding="utf-8")


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash no disponible")
@pytest.mark.parametrize("script", ["20_scripts_extreme.sh", "30_roles.sh"])
def test_sh_sintaxis_valida(script):
    r = subprocess.run(["bash", "-n", str(REPLICA / "initdb" / script)], capture_output=True, text=True,
                       check=False)
    assert r.returncode == 0, r.stderr


@pytest.mark.parametrize("url", [
    "postgresql://extreme_dba:x@servidor-del-reto.amazonaws.com:5432/dataset",
    "postgresql+psycopg://lector_ia:x@10.0.0.8:5432/operacional",
])
def test_nunca_un_servidor_que_no_sea_local(url):
    with pytest.raises(ValueError, match="servidor local"):
        rc._verificar_local(url)


def test_servidor_local_aceptado():
    assert rc._verificar_local("postgresql+psycopg://lector_ia:x@localhost:5434/operacional").startswith(
        "postgresql://")


def test_claves_solo_de_ejemplo_en_env_example():
    """El .env.example solo trae marcadores para la réplica; las claves reales viven en el .env local (ignorado)."""
    ejemplo = (rc.RAIZ / ".env.example").read_text(encoding="utf-8")
    for variable in ("OPERACIONAL_PASSWORD", "LECTOR_IA_PASSWORD", "ESCRITOR_IA_PASSWORD"):
        linea = next(x for x in ejemplo.splitlines() if x.startswith(f"{variable}="))
        assert linea.split("=", 1)[1].startswith("cambie_"), variable
