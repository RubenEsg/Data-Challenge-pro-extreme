"""La migración 0012 (retención, §18) versiona threshold_config con el candado de sus escritores (§5.1 «se
versionan»): ejecucion.bloquear_umbrales, el mismo de PUT /thresholds y de las migraciones 0013 y 0014.

Sin base: la migración corre contra una conexión de prueba que anota cada sentencia. El candado debe ser la PRIMERA
sentencia, tanto al subir como al bajar (antes de leer la versión vigente o de borrar las filas propias). La prueba de
integración tests/integracion/test_migracion_0012_candado.py comprueba con PostgreSQL que de verdad espera.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

RAIZ = Path(__file__).resolve().parents[2]
VERSIONES = RAIZ / "alembic" / "versions"
RESTRICCION = "CHECK ((tipo = ANY (ARRAY['frecuencia'::text, 'entrenamiento'::text, 'respuesta'::text, " \
              "'segmentos'::text])))"


def _migracion(archivo: str):
    spec = importlib.util.spec_from_file_location(archivo.split("_", 1)[0], VERSIONES / archivo)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


class _Conexion:
    """Anota cada sentencia; responde lo mínimo que lee la 0012 (restricción de tipos, versión y vigentes)."""

    def __init__(self) -> None:
        self.sentencias: list[str] = []

    def execute(self, sentencia, parametros=None):
        texto = str(getattr(sentencia, "text", sentencia))
        self.sentencias.append(texto)
        if "pg_get_constraintdef" in texto:
            valor = RESTRICCION
        elif "count(*)" in texto:
            valor = 1
        else:
            valor = 3
        return SimpleNamespace(scalar=lambda: valor, all=lambda: [("ocupacion_critica", 0.9, "umbral")])


@pytest.fixture
def m0012(monkeypatch):
    m = _migracion("0012_retencion_y_ventana_segmentos.py")
    conexion = _Conexion()
    monkeypatch.setattr(m, "op", SimpleNamespace(get_bind=lambda: conexion, execute=conexion.sentencias.append))
    return m, conexion


def test_el_candado_es_el_de_los_escritores_de_threshold_config():
    from app.servicios.ejecucion import SQL_CANDADO_UMBRALES

    for archivo in ("0012_retencion_y_ventana_segmentos.py", "0013_consolidados_ciclo.py",
                    "0014_alt003_probabilidad_minima.py"):
        assert _migracion(archivo).CANDADO_UMBRALES == SQL_CANDADO_UMBRALES.text, archivo


@pytest.mark.parametrize("paso", ["upgrade", "downgrade"])
def test_la_0012_toma_el_candado_antes_de_cualquier_otra_sentencia(m0012, paso):
    m, conexion = m0012
    getattr(m, paso)()
    assert conexion.sentencias[0] == m.CANDADO_UMBRALES
    assert sum(1 for s in conexion.sentencias if s == m.CANDADO_UMBRALES) == 1          # una vez por paso
    assert any("threshold_config" in s for s in conexion.sentencias[1:])                 # y después versiona
