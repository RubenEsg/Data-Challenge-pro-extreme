"""Pruebas de datos y ML (spec v1.5 §14.1 «Datos/ML | Pruebas de distribución y no regresión | Variables, métricas y
fuga temporal»). No necesitan base de datos: usan la serie y el modelo empaquetados en datos/, leídos desde una COPIA
temporal (DATA_DIR y MODELOS_DIR), de modo que ninguna prueba puede escribir en el repositorio.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="package")
def datos_copia(tmp_path_factory):
    from app.servicios import datos, inferencia

    copia = tmp_path_factory.mktemp("datos_ml") / "datos"
    shutil.copytree(RAIZ / "datos", copia)
    mp = pytest.MonkeyPatch()
    mp.setenv("DATA_DIR", str(copia))
    mp.setenv("MODELOS_DIR", str(copia / "modelos"))
    datos.limpiar_cache()
    inferencia.limpiar_cache()
    try:
        yield copia
    finally:
        mp.undo()
        datos.limpiar_cache()
        inferencia.limpiar_cache()


@pytest.fixture(scope="package")
def serie(datos_copia):
    from app.servicios import datos

    return datos.demanda_horaria()


@pytest.fixture(scope="package")
def tabla(serie):
    from app.servicios import datos, variables

    return variables.construir_variables(serie, contexto=datos.contexto_operacional())


@pytest.fixture(scope="package")
def registro(datos_copia) -> dict:
    return json.loads((datos_copia / "modelos" / "registro.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="package")
def manifiesto_activo(datos_copia, registro) -> dict:
    activo = registro["activo"]
    return json.loads((datos_copia / "modelos" / activo / "manifest.json").read_text(encoding="utf-8"))
