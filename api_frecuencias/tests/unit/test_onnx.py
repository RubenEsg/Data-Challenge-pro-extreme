"""ONNX (§9.1, §9.2): exportación con Exp para Poisson, paridad con scikit-learn, SHA-256 y MOTOR_INFERENCIA."""
from __future__ import annotations

import json
from datetime import date, datetime

import numpy as np
import pytest

pytest.importorskip("onnxruntime")
pytest.importorskip("skl2onnx")

from app.servicios import datos, inferencia, onnx_motor, variables  # noqa: E402
from scripts import exportar_onnx  # noqa: E402

HIPER_RAPIDO = {"max_iter": 25, "max_leaf_nodes": 15, "min_samples_leaf": 20}


@pytest.fixture(scope="module")
def modelo_tmp(tmp_path_factory):
    """Modelo fv2 pequeño entrenado con la serie real en una carpeta temporal (nunca en datos/modelos)."""
    carpeta = tmp_path_factory.mktemp("modelos_onnx")
    serie = datos.demanda_horaria(desde=date(2025, 1, 1), hasta=date(2025, 12, 31))
    r = inferencia.entrenar(date(2025, 8, 31), 42, serie=serie, dir_modelos=carpeta, hiper=HIPER_RAPIDO)
    return carpeta, r["model_id"]


def test_motor_configurado(monkeypatch):
    monkeypatch.delenv("MOTOR_INFERENCIA", raising=False)
    assert onnx_motor.motor_configurado() == "sklearn"
    monkeypatch.setenv("MOTOR_INFERENCIA", "ONNX")
    assert onnx_motor.motor_configurado() == "onnx"
    monkeypatch.setenv("MOTOR_INFERENCIA", "tensorrt")
    with pytest.raises(onnx_motor.MotorNoDisponible):
        onnx_motor.motor_configurado()


def test_exportacion_paridad_y_sha(modelo_tmp, monkeypatch):
    carpeta, mid = modelo_tmp
    ev = exportar_onnx.exportar(mid, carpeta, filas=800)
    assert ev["aprobada"]
    for parte in onnx_motor.PARTES:
        d = ev["paridad"][parte]
        # la regla de numpy.isclose: en cada fila |onnx - sklearn| <= 0,01 + 1e-3 * |sklearn| (exceso <= 0)
        assert d["max_exceso_tolerancia"] <= 0 and d["max_abs"] < 0.02
        assert d["wape_onnx"] == pytest.approx(d["wape_sklearn"], abs=1e-3)
    man = json.loads((carpeta / mid / "manifest.json").read_text(encoding="utf-8"))
    assert set(man["onnx"]["archivos"]) == {"punto", "p10", "p90"}
    for a in man["onnx"]["archivos"].values():
        assert onnx_motor.sha256(carpeta / mid / a["archivo"]) == a["sha256"]
    assert man["sha256"] == inferencia._sha256(carpeta / mid / "modelo.joblib")   # el joblib no cambia
    assert man["onnx"]["archivos"]["punto"]["enlace"].startswith("exp")


def test_motor_onnx_predice_igual_que_sklearn(modelo_tmp, monkeypatch):
    carpeta, mid = modelo_tmp
    if not (carpeta / mid / "modelo_punto.onnx").exists():
        exportar_onnx.exportar(mid, carpeta, filas=300)
    inst = datetime(2025, 10, 6, 7, 0, tzinfo=inferencia.ZONA)
    monkeypatch.setenv("MOTOR_INFERENCIA", "sklearn")
    a = inferencia.predecir("SILENCIO", inst, 60, model_id=mid, dir_modelos=carpeta)
    monkeypatch.setenv("MOTOR_INFERENCIA", "onnx")
    m = inferencia.cargar(mid, carpeta)
    assert m["motor"] == "onnx" and isinstance(m["punto"], onnx_motor.ModeloOnnx)
    b = inferencia.predecir("SILENCIO", inst, 60, model_id=mid, dir_modelos=carpeta)
    for k in ("pasajeros", "p10", "p90"):
        assert b[k] == pytest.approx(a[k], abs=0.05)
    assert b["explicacion_local"]["metodo"] == "shap_tree_exacto"     # SHAP sigue con el árbol de sklearn
    x = variables.matriz_x(inferencia._filas_utiles(inferencia.tabla_variables()).head(50), m["feature_version"])
    assert np.allclose(m["punto"].predict(x), m["punto_sklearn"].predict(x), atol=0.01)


def test_onnx_alterado_se_rechaza(modelo_tmp, tmp_path, monkeypatch):
    carpeta, mid = modelo_tmp
    if not (carpeta / mid / "modelo_punto.onnx").exists():
        exportar_onnx.exportar(mid, carpeta, filas=300)
    man = json.loads((carpeta / mid / "manifest.json").read_text(encoding="utf-8"))
    a = man["onnx"]["archivos"]["p10"]
    with pytest.raises(onnx_motor.MotorNoDisponible, match="SHA-256"):
        onnx_motor.ModeloOnnx(carpeta / mid / a["archivo"], "0" * 64)
    with pytest.raises(onnx_motor.MotorNoDisponible, match="no tiene exportación"):
        onnx_motor.cargar_sesiones(carpeta / mid, {"model_id": mid})


def test_fv1_no_es_exportable(tmp_path):
    serie = datos.demanda_horaria(desde=date(2025, 1, 1), hasta=date(2025, 12, 31))
    r = inferencia.entrenar(date(2025, 8, 31), 7, serie=serie, dir_modelos=tmp_path, hiper=HIPER_RAPIDO,
                            version=variables.FV1)
    with pytest.raises(SystemExit, match="categóricas"):
        exportar_onnx.exportar(r["model_id"], tmp_path, filas=100)
