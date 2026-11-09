"""Calibración condicional versionada de la banda P10-P90 (§9.3 cuantiles, §9.4 cobertura, §9.2 hash verificado).

La calibración v2 (un cuantil conformal por bloque horario, ajustado solo con la validación) vive junto al modelo en
calibracion_v2.json, con su SHA-256 en manifest.json. Las pruebas usan una COPIA temporal de la carpeta del modelo:
ninguna escribe en datos/.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from app.servicios import inferencia

RAIZ = Path(__file__).resolve().parents[2]
ACTIVO = "hgb_fv2_20250831_s42"
ORIGEN = RAIZ / "datos" / "modelos" / ACTIVO
INSTANTE = datetime(2025, 11, 20, 6, 30, tzinfo=inferencia.ZONA)

pytestmark = pytest.mark.skipif(not (ORIGEN / "manifest.json").exists(), reason="sin el modelo activo empaquetado")


def _manifiesto(carpeta: Path = ORIGEN) -> dict:
    return json.loads((carpeta / "manifest.json").read_text(encoding="utf-8"))


@pytest.fixture
def carpeta(tmp_path, monkeypatch):
    """Copia de la carpeta del modelo activo (la caché de modelos usa la ruta, así que no choca con datos/)."""
    monkeypatch.delenv("CALIBRACION_BANDA", raising=False)
    monkeypatch.setenv("MOTOR_INFERENCIA", "sklearn")
    destino = tmp_path / "modelos"
    shutil.copytree(ORIGEN, destino / ACTIVO)
    return destino


def test_manifiesto_registra_la_calibracion_y_no_toca_el_artefacto():
    man = _manifiesto()
    cal = man.get("calibracion")
    assert cal and cal["version"] == "v2" and cal["grupos"] == ["bloque"]
    archivo = ORIGEN / cal["archivo"]
    assert hashlib.sha256(archivo.read_bytes()).hexdigest() == cal["sha256"]
    contenido = json.loads(archivo.read_text(encoding="utf-8"))
    assert contenido["model_id"] == ACTIVO and "*" in contenido["q"]
    assert "validación" in contenido["ajustado_con"] and "prueba reservada no se usa" in contenido["ajustado_con"]
    # el artefacto y los ONNX conservan sus hashes (la calibración se aplica después del modelo)
    assert inferencia._sha256(ORIGEN / man["artefacto"]) == man["sha256"]
    for a in (man.get("onnx") or {}).get("archivos", {}).values():
        assert inferencia._sha256(ORIGEN / a["archivo"]) == a["sha256"]
    registro = json.loads((ORIGEN.parent / "registro.json").read_text(encoding="utf-8"))
    assert registro["activo"] == ACTIVO and registro["modelos"][ACTIVO]["sha256"] == man["sha256"]


def test_hash_alterado_impide_cargar(carpeta):
    archivo = carpeta / ACTIVO / _manifiesto(carpeta / ACTIVO)["calibracion"]["archivo"]
    archivo.write_text(archivo.read_text(encoding="utf-8") + " ", encoding="utf-8")
    with pytest.raises(inferencia.ErrorIntegridadModelo, match="calibración"):
        inferencia.cargar(ACTIVO, carpeta)


def test_falta_el_archivo_de_calibracion(carpeta):
    (carpeta / ACTIVO / _manifiesto(carpeta / ACTIVO)["calibracion"]["archivo"]).unlink()
    with pytest.raises(inferencia.ErrorIntegridadModelo, match="Falta"):
        inferencia.cargar(ACTIVO, carpeta)


def test_grupos_de_calibracion():
    filas = pd.DataFrame({"ruta": ["CRA 54", "SILENCIO", "CL 72"], "hora": [4, 7, 20], "tipo_dia": [0, 1, 2]})
    assert list(inferencia.grupos_calibracion(filas, ["bloque"])) == ["04-05", "06-08 pico", "20"]
    assert list(inferencia.grupos_calibracion(filas, ["ruta", "hora"])) == ["CRA 54|4", "SILENCIO|7", "CL 72|20"]
    tipos = inferencia.grupos_calibracion(filas, ["tipo", "bloque"])
    assert tipos[0] == f"{inferencia.datos.TIPOS_DIA[0]}|04-05"
    with pytest.raises(ValueError):
        inferencia.grupos_calibracion(filas, ["clima"])


def test_cuantil_por_grupo_con_respaldo_global():
    q = {"*": 0.05, "06-08 pico": -0.02}
    filas = pd.DataFrame({"ruta": ["X", "X"], "hora": [7, 12], "tipo_dia": [0, 0]})
    valores, claves = inferencia.q_calibracion({"grupos": ["bloque"], "q": q}, filas)
    assert list(claves) == ["06-08 pico", "09-16 valle"]
    assert valores.tolist() == [-0.02, 0.05]        # el bloque sin cuantil propio usa el global


def test_ajuste_del_script_es_el_conformal_de_cada_grupo():
    from scripts import calibrar_por_grupo as cal

    t = pd.DataFrame({"ruta": ["A"] * 110, "hora": [7] * 100 + [12] * 10, "tipo_dia": [0] * 110})
    s = np.r_[np.arange(100) / 100.0, np.full(10, 5.0)]
    r = cal.ajustar(t, s, ("bloque",), inferencia)
    # k = ceil((n + 1) * 0,8): 81.º menor de 0,00 … 0,99 = 0,80; el bloque de 10 puntajes queda con el global
    assert r["q"]["06-08 pico"] == pytest.approx(0.80)
    assert "09-16 valle" not in r["q"] and r["n"]["09-16 valle"] == 10
    assert r["q"]["*"] == pytest.approx(inferencia.cuantil_conformal(s))


def test_predecir_aplica_v2_y_dice_la_version(carpeta):
    r = inferencia.predecir("CRA 54", INSTANTE, 120, model_id=ACTIVO, dir_modelos=carpeta)
    cal = json.loads((carpeta / ACTIVO / "calibracion_v2.json").read_text(encoding="utf-8"))
    assert r["calibracion_version"] == "v2" and r["variables"]["calibracion_version"] == "v2"
    conf = r["variables"]["conformal"]
    assert conf["version"] == "v2" and conf["archivo"] == "calibracion_v2.json"
    for h, g, qh in zip(r["variables"]["por_hora"], conf["grupos"], conf["q_por_hora"], strict=True):
        assert g == str(inferencia.franja_de([h["hora"]])[0]) and qh == pytest.approx(cal["q"][g])
        esc = max(h["pasajeros_hora"], 1.0)
        assert h["p90_hora"] == pytest.approx(max(h["p90_modelo_hora"] + qh * esc, h["pasajeros_hora"]), abs=0.15)
        assert h["p10_hora"] == pytest.approx(
            max(min(h["p10_modelo_hora"] - qh * esc, h["pasajeros_hora"]), 0.0), abs=0.15)
    assert r["ajuste_conformal"] == pytest.approx(cal["q"]["06-08 pico"])
    assert any("versión v2" in e for e in r["explicacion"])


def test_calibracion_v1_por_variable_de_entorno(carpeta, monkeypatch):
    monkeypatch.setenv("CALIBRACION_BANDA", "v1")
    r = inferencia.predecir("CRA 54", INSTANTE, 60, model_id=ACTIVO, dir_modelos=carpeta)
    assert r["calibracion_version"] == "v1" and "q_por_hora" not in r["variables"]["conformal"]
    assert r["variables"]["conformal"]["metodo"] == inferencia.CALIBRACION_V1


def test_la_calibracion_no_cambia_el_pronostico_ni_el_wape(carpeta, monkeypatch):
    desde, hasta = date(2025, 11, 1), date(2025, 11, 14)
    v2 = inferencia.evaluar(ACTIVO, desde, hasta, dir_modelos=carpeta)
    p2 = inferencia.predecir("SILENCIO", INSTANTE, 60, model_id=ACTIVO, dir_modelos=carpeta)
    monkeypatch.setenv("CALIBRACION_BANDA", "v1")
    v1 = inferencia.evaluar(ACTIVO, desde, hasta, dir_modelos=carpeta)
    p1 = inferencia.predecir("SILENCIO", INSTANTE, 60, model_id=ACTIVO, dir_modelos=carpeta)
    assert v2["wape"] == v1["wape"] and v2["mae"] == v1["mae"]
    assert v2["cobertura_p10_p90"] == v1["cobertura_p10_p90"]           # banda del modelo, sin calibrar
    assert v2["calibracion_version"] == "v2" and v1["calibracion_version"] == "v1"
    assert v2["cobertura_p10_p90_conformal_v1"] == v1["cobertura_p10_p90_conformal"]
    assert p2["pasajeros"] == p1["pasajeros"] and p2["p90"] != p1["p90"]


@pytest.fixture(scope="module")
def candidato(tmp_path_factory):
    """Un candidato entrenado con la serie de juguete en una carpeta temporal (nunca en datos/modelos)."""
    from tests.unit.test_inferencia import HIPER_RAPIDO, serie_juguete

    destino = tmp_path_factory.mktemp("candidatos")
    serie = serie_juguete()
    r = inferencia.entrenar(date(2025, 4, 15), 42, serie=serie, dir_modelos=destino, hiper=HIPER_RAPIDO)
    return {"r": r, "carpeta": destino, "serie": serie}


def test_cada_candidato_entrenado_trae_su_calibracion_versionada(candidato):
    """§9.5: el candidato sale con su calibración por grupo ajustada con SU validación, junto a su artefacto."""
    r, carpeta = candidato["r"], candidato["carpeta"] / candidato["r"]["model_id"]
    man = _manifiesto(carpeta)
    meta = man["calibracion"]
    archivo = carpeta / meta["archivo"]
    assert meta["archivo"] == inferencia.ARCHIVO_CALIBRACION and meta["version"] == "v2"
    assert hashlib.sha256(archivo.read_bytes()).hexdigest() == meta["sha256"] == r["calibracion"]["sha256"]
    assert inferencia._sha256(carpeta / man["artefacto"]) == man["sha256"] == r["sha256"]   # artefacto intacto
    cal = json.loads(archivo.read_text(encoding="utf-8"))
    assert cal["model_id"] == r["model_id"] and cal["grupos"] == list(inferencia.CALIBRACION_GRUPOS_DEFECTO)
    desde_val, hasta_val = (x.strip() for x in man["particion"]["validacion"].split(" a "))
    assert cal["ajustado_con"].startswith(f"validación {desde_val} a ")
    assert date.fromisoformat(cal["ajustado_con"].split(" a ")[1][:10]) <= date.fromisoformat(hasta_val)
    assert meta["resumen"]["validacion_ajuste"]["cobertura_pct"] > 0


def test_la_calibracion_del_candidato_es_el_ajuste_de_su_validacion(candidato):
    """El cuantil de cada grupo es el conformal de los puntajes de la validación del candidato (la misma función que
    usa scripts/calibrar_por_grupo.py), y cargar() lo verifica y lo aplica."""
    from scripts import calibrar_por_grupo as script

    r, raiz = candidato["r"], candidato["carpeta"]
    _, va, _ = inferencia._particion_cronologica(candidato["serie"], None, date(2025, 4, 15))
    modelo = inferencia.cargar(r["model_id"], raiz)
    p, lo, hi = inferencia._predecir_filas(modelo, va)
    s = inferencia.puntajes_conformal(p, lo, hi, va["pasajeros"].to_numpy(float))
    cal = json.loads((raiz / r["model_id"] / inferencia.ARCHIVO_CALIBRACION).read_text(encoding="utf-8"))
    assert cal["q"] == script.ajustar(va, s, ("bloque",), inferencia)["q"]
    assert cal["q"] == inferencia.ajustar_calibracion_grupo(va, s, ("bloque",))["q"]
    assert modelo["calibracion"]["version"] == "v2" and modelo["calibracion"]["q"] == cal["q"]
    pred = inferencia.predecir("CRA 54", INSTANTE, 60, model_id=r["model_id"], dir_modelos=raiz)
    assert pred["calibracion_version"] == "v2" and pred["variables"]["conformal"]["sha256"] == cal_sha(raiz, r)


def cal_sha(raiz: Path, r: dict) -> str:
    return hashlib.sha256((raiz / r["model_id"] / inferencia.ARCHIVO_CALIBRACION).read_bytes()).hexdigest()


def test_la_evaluacion_del_candidato_usa_su_calibracion(candidato):
    """La sombra y la compuerta evalúan al candidato con su propia banda v2 (y reportan v1 como referencia)."""
    m = inferencia.evaluar(candidato["r"]["model_id"], date(2025, 11, 1), date(2025, 11, 7),
                           dir_modelos=candidato["carpeta"])
    assert m["calibracion_version"] == "v2"
    assert m["horas_con_ajuste_conformal_pct"] == pytest.approx(100.0)
    assert "cobertura_p10_p90_conformal_v1" in m and 0 <= m["cobertura_p10_p90_conformal"] <= 100


def test_entrenar_sin_calibrar_y_con_otros_grupos(tmp_path):
    from tests.unit.test_inferencia import HIPER_RAPIDO, serie_juguete

    serie = serie_juguete()
    r = inferencia.entrenar(date(2025, 4, 15), 42, serie=serie, dir_modelos=tmp_path / "a", hiper=HIPER_RAPIDO,
                            calibrar=False)
    assert r["calibracion"] is None and "calibracion" not in _manifiesto(tmp_path / "a" / r["model_id"])
    assert inferencia.cargar(r["model_id"], tmp_path / "a")["calibracion"] is None      # banda v1
    r2 = inferencia.entrenar(date(2025, 4, 15), 42, serie=serie, dir_modelos=tmp_path / "b", hiper=HIPER_RAPIDO,
                             calibracion_grupos=("ruta", "bloque"))
    assert _manifiesto(tmp_path / "b" / r2["model_id"])["calibracion"]["grupos"] == ["ruta", "bloque"]
    assert r2["metricas"] == r["metricas"]          # la calibración no cambia el modelo ni sus métricas


def test_onnx_aplica_la_misma_calibracion(carpeta, monkeypatch):
    pytest.importorskip("onnxruntime")
    if not _manifiesto(carpeta / ACTIVO).get("onnx"):
        pytest.skip("el modelo no tiene exportación ONNX")
    a = inferencia.predecir("CL 72", INSTANTE, 30, model_id=ACTIVO, dir_modelos=carpeta)
    monkeypatch.setenv("MOTOR_INFERENCIA", "onnx")
    b = inferencia.predecir("CL 72", INSTANTE, 30, model_id=ACTIVO, dir_modelos=carpeta)
    assert b["calibracion_version"] == a["calibracion_version"] == "v2"
    for k in ("pasajeros", "p10", "p90"):
        assert b[k] == pytest.approx(a[k], rel=1e-3)


def test_script_calibra_cualquier_modelo_con_model_id(tmp_path):
    """scripts/calibrar_por_grupo.py --model-id: el mismo análisis para otro modelo, con evidencia propia (lleva el id)
    y sin tocar sus archivos si no se pide --escribir."""
    from scripts import calibrar_por_grupo as script

    otro = "hgb_fv1_20250831_s42"
    carpeta = inferencia.datos.carpeta_modelos() / otro
    if not (carpeta / "manifest.json").exists():
        pytest.skip("sin el modelo fv1 empaquetado")
    antes = {p.name: inferencia._sha256(p) for p in carpeta.iterdir() if p.is_file()}
    r = script.main(["--model-id", otro, "--salida", str(tmp_path)])
    assert r["model_id"] == otro and r["calibracion"]["model_id"] == otro
    assert (tmp_path / f"calibracion_condicional_{otro}.json").exists()
    assert not (tmp_path / "calibracion_condicional.json").exists()       # la evidencia del activo no se toca
    assert r["calibracion"]["evidencia"].endswith(f"calibracion_condicional_{otro}.json")
    assert {p.name: inferencia._sha256(p) for p in carpeta.iterdir() if p.is_file()} == antes
