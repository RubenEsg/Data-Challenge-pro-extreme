"""app/servicios/modelos_imagen.py: al actualizar una instalación, los modelos nuevos de la imagen llegan al volumen."""
from __future__ import annotations

import json
from pathlib import Path

from app.servicios import modelos_imagen


def _registro(carpeta: Path, activo: str | None, modelos: list[str], con_carpetas: bool = True) -> None:
    carpeta.mkdir(parents=True, exist_ok=True)
    reg = {"activo": activo, "modelos": {m: {"model_id": m, "estado": "activo" if m == activo else "candidato"}
                                         for m in modelos}, "historial_activacion": []}
    (carpeta / "registro.json").write_text(json.dumps(reg), encoding="utf-8")
    if con_carpetas:
        for m in modelos:
            (carpeta / m).mkdir(exist_ok=True)
            (carpeta / m / "manifest.json").write_text(json.dumps({"model_id": m}), encoding="utf-8")


def _leer(ruta: Path) -> dict:
    return json.loads(ruta.read_text(encoding="utf-8"))


def test_copia_lo_que_falta_sin_cambiar_el_activo(tmp_path):
    imagen, volumen = tmp_path / "imagen", tmp_path / "volumen"
    _registro(imagen, "hgb_fv2", ["hgb_fv1", "hgb_fv2", "hgb_fv3"])
    _registro(imagen / "corto_plazo", "cp_1", ["cp_1"])
    _registro(imagen / "segmentos", "seg_1", ["seg_1"])
    _registro(volumen, "hgb_local", ["hgb_fv1", "hgb_local"])          # la instalación vieja: otro activo
    (volumen / "hgb_fv1" / "manifest.json").write_text('{"model_id": "hgb_fv1", "local": true}', encoding="utf-8")

    hechos = modelos_imagen.sembrar(imagen, volumen)

    assert hechos == {"horarios": ["hgb_fv2", "hgb_fv3"], "segmentos": ["seg_1"], "corto_plazo": ["cp_1"]}
    reg = _leer(volumen / "registro.json")
    assert reg["activo"] == "hgb_local"                                  # el activo no cambia
    assert reg["modelos"]["hgb_fv2"]["estado"] == "candidato"            # aunque en la imagen fuera el activo
    assert reg["historial_siembra"][0]["modelos"] == ["hgb_fv2", "hgb_fv3"]
    assert (volumen / "hgb_fv3" / "manifest.json").exists()
    assert _leer(volumen / "hgb_fv1" / "manifest.json")["local"] is True    # lo que ya estaba no se sobrescribe
    # sin registro en el volumen, el de la imagen se copia tal cual, con su activo
    assert _leer(volumen / "corto_plazo" / "registro.json")["activo"] == "cp_1"
    assert (volumen / "segmentos" / "seg_1" / "manifest.json").exists()
    # la segunda vez no hay nada que copiar
    assert modelos_imagen.sembrar(imagen, volumen) == {}


def test_sin_carpeta_de_la_imagen_no_hace_nada(tmp_path, monkeypatch):
    monkeypatch.setenv("MODELOS_IMAGEN_DIR", str(tmp_path / "no_existe"))
    assert modelos_imagen.sembrar(destino=tmp_path / "volumen") == {}
    assert not (tmp_path / "volumen").exists()


def test_la_misma_carpeta_no_se_copia_sobre_si_misma(tmp_path):
    _registro(tmp_path, "m", ["m"])
    assert modelos_imagen.sembrar(tmp_path, tmp_path) == {}


def test_ficha_sin_carpeta_entra_al_registro(tmp_path):
    imagen, volumen = tmp_path / "imagen", tmp_path / "volumen"
    _registro(imagen, "b1", ["b1"], con_carpetas=False)                  # las líneas base no tienen carpeta
    _registro(volumen, "m", ["m"])
    assert modelos_imagen.sembrar(imagen, volumen) == {"horarios": ["b1"]}
    assert "b1" in _leer(volumen / "registro.json")["modelos"]
    assert not (volumen / "b1").exists()
