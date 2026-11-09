"""tests/evidencia.py: la evidencia que escriben las pruebas va a un directorio temporal salvo con GENERAR_EVIDENCIAS=1,
y nunca sale de docs/evidencias. Ninguna de estas pruebas escribe en el repositorio (DOCS_EVIDENCIAS se redirige)."""
from __future__ import annotations

import json

import pytest

from tests import evidencia


@pytest.fixture
def aislada(tmp_path, monkeypatch):
    """docs/evidencias falso y un temporal nuevo por prueba."""
    monkeypatch.setattr(evidencia, "DOCS_EVIDENCIAS", tmp_path / "docs_evidencias")
    monkeypatch.setattr(evidencia, "_temporal", None)
    monkeypatch.delenv("GENERAR_EVIDENCIAS", raising=False)
    monkeypatch.delenv("EVIDENCIAS_DIR", raising=False)
    return tmp_path


def test_sin_variable_escribe_en_un_temporal_y_no_en_docs(aislada):
    ruta = evidencia.guardar_evidencia("seguridad/matriz.txt", "hola\n")
    assert ruta.read_text(encoding="utf-8") == "hola\n"
    assert not (aislada / "docs_evidencias").exists()
    assert ruta.parent.name == "seguridad" and ruta.parent.parent == evidencia.directorio_evidencias()


def test_con_generar_evidencias_escribe_en_docs_evidencias(aislada, monkeypatch):
    monkeypatch.setenv("GENERAR_EVIDENCIAS", "1")
    ruta = evidencia.guardar_evidencia("cola/x.json", {"n": 1, "texto": "señal"})
    assert ruta == aislada / "docs_evidencias" / "cola" / "x.json"
    assert json.loads(ruta.read_text(encoding="utf-8")) == {"n": 1, "texto": "señal"}
    assert "señal" in ruta.read_text(encoding="utf-8")          # sin escapar acentos


def test_evidencias_dir_elige_el_temporal(aislada, monkeypatch):
    monkeypatch.setenv("EVIDENCIAS_DIR", str(aislada / "elegido"))
    ruta = evidencia.guardar_evidencia("a/b.bin", b"\x00\x01")
    assert ruta == aislada / "elegido" / "a" / "b.bin" and ruta.read_bytes() == b"\x00\x01"


@pytest.mark.parametrize("mala", ["../fuera.txt", "seguridad/../../fuera.txt", "/abs/x.txt", "C:/x.txt", ""])
def test_rechaza_rutas_que_salen_de_docs_evidencias(aislada, mala):
    with pytest.raises(ValueError, match="docs/evidencias"):
        evidencia.guardar_evidencia(mala, "x")


def test_otro_valor_de_la_variable_no_activa_la_escritura(aislada, monkeypatch):
    monkeypatch.setenv("GENERAR_EVIDENCIAS", "true")
    assert not evidencia.generando_evidencias()
    ruta = evidencia.guardar_evidencia("x.txt", "y")
    assert not (aislada / "docs_evidencias").exists() and ruta.exists()
