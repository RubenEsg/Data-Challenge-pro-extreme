"""Pruebas de app/servicios/inferencia.py: reproducibilidad, hash, contrato de predecir y nowcast sin fuga."""

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd
import pytest

from app.servicios import datos, inferencia, variables

ZONA = inferencia.ZONA
HIPER_RAPIDO = {"max_iter": 25, "max_leaf_nodes": 15, "min_samples_leaf": 20}
CAMPOS = (
    "pasajeros",
    "p10",
    "p90",
    "model_id",
    "feature_version",
    "data_cutoff",
    "generated_at",
    "latencia_ms",
    "explicacion",
    "variables",
)
HAY_MODELO = (datos.carpeta_modelos() / "registro.json").exists() and (
    datos.carpeta_datos() / "demanda_horaria.parquet"
).exists()
requiere_modelo = pytest.mark.skipif(not HAY_MODELO, reason="falta el modelo entrenado (scripts/entrenar.py)")


def serie_juguete(dias: int = 150) -> pd.DataFrame:
    rng = np.random.default_rng(7)
    filas = []
    for i in range(dias):
        f = date(2025, 1, 1) + timedelta(days=i)
        for ruta, escala in (("SILENCIO", 1.0), ("CRA 54", 2.0), ("CL 72", 0.6)):
            for h in range(4, 21):
                media = escala * (300 + 400 * np.exp(-((h - 7) ** 2) / 4) + 300 * np.exp(-((h - 17) ** 2) / 6))
                media *= 0.6 if f.weekday() == 6 else 1.0
                filas.append(
                    {
                        "ruta": ruta,
                        "fecha": f,
                        "hora": h,
                        "pasajeros": float(rng.poisson(media)),
                        "excluido": 0,
                        "festivo": 0,
                        "tipo_dia": 2 if f.weekday() == 6 else (1 if f.weekday() == 5 else 0),
                    }
                )
    return pd.DataFrame(filas)


@pytest.fixture(scope="module")
def serie():
    return serie_juguete()


def _entrenar(serie, carpeta):
    return inferencia.entrenar(date(2025, 4, 15), 42, serie=serie, dir_modelos=carpeta, hiper=HIPER_RAPIDO)


def test_entrenamiento_reproducible_con_semilla(serie, tmp_path):
    a = _entrenar(serie, tmp_path / "a")
    b = _entrenar(serie, tmp_path / "b")
    assert a["model_id"] == b["model_id"]
    assert a["metricas"]["validacion"]["candidato"] == b["metricas"]["validacion"]["candidato"]
    ma = inferencia.cargar(a["model_id"], tmp_path / "a")
    mb = inferencia.cargar(b["model_id"], tmp_path / "b")
    x = variables.matriz_x(inferencia._filas_utiles(variables.construir_variables(serie)).tail(200))
    for k in ("punto", "p10", "p90"):
        np.testing.assert_array_equal(ma[k].predict(x), mb[k].predict(x))
    man = json.loads((tmp_path / "a" / a["model_id"] / "manifest.json").read_text(encoding="utf-8"))
    for campo in (
        "sha256",
        "feature_version",
        "data_cutoff",
        "metricas",
        "semilla",
        "hiperparametros",
        "filas_entrenamiento",
    ):
        assert campo in man
    assert man["semilla"] == 42 and man["data_cutoff"] == "2025-04-15"


def test_metricas_comparan_con_la_linea_base(serie, tmp_path):
    r = _entrenar(serie, tmp_path)
    v = r["metricas"]["validacion"]
    for nombre in ("candidato", "b1_manual_8sem", "b2_ultima_semana"):
        for campo in ("mae", "rmse", "wape", "por_ruta", "pico", "valle"):
            assert campo in v[nombre]
    assert "cobertura_p10_p90" in v["candidato"]
    man = json.loads(Path(r["manifiesto"]).read_text(encoding="utf-8"))
    assert man["nowcast"]["peso"] in inferencia.NOWCAST_PESOS
    assert {x["variable"] for x in man["importancia_global"]} == set(variables.COLUMNAS_MODELO)


def test_hash_distinto_impide_cargar(serie, tmp_path):
    r = _entrenar(serie, tmp_path)
    artefacto = tmp_path / r["model_id"] / "modelo.joblib"
    with open(artefacto, "ab") as f:
        f.write(b"alterado")
    inferencia.limpiar_cache()
    with pytest.raises(inferencia.ErrorIntegridadModelo):
        inferencia.cargar(r["model_id"], tmp_path)


def test_modelo_se_carga_una_sola_vez(serie, tmp_path):
    r = _entrenar(serie, tmp_path)
    inferencia.limpiar_cache()
    with mock.patch.object(inferencia.joblib, "load", wraps=inferencia.joblib.load) as espia:
        m1 = inferencia.cargar(r["model_id"], tmp_path)
        m2 = inferencia.cargar(r["model_id"], tmp_path)
    assert m1 is m2
    assert espia.call_count == 1


def test_modelo_inexistente(tmp_path):
    with pytest.raises(inferencia.ModeloNoEncontrado):
        inferencia.cargar("no_existe", tmp_path)


def test_registro_activar_y_volver_atras(serie, tmp_path):
    r = _entrenar(serie, tmp_path)
    reg = inferencia.registro(tmp_path)
    assert r["model_id"] in reg["modelos"] and "b1_manual_8sem" in reg["modelos"]
    inferencia.activar("b1_manual_8sem", "prueba", "volver atrás", tmp_path)
    assert inferencia.modelo_activo(tmp_path) == "b1_manual_8sem"
    inferencia.activar(r["model_id"], "prueba", "reactivar", tmp_path)
    assert inferencia.modelo_activo(tmp_path) == r["model_id"]
    assert inferencia.registro(tmp_path)["historial_activacion"][-1]["a"] == r["model_id"]
    with pytest.raises(inferencia.ModeloNoEncontrado):
        inferencia.activar("no_existe", dir_modelos=tmp_path)
    filas = inferencia.listar_modelos(tmp_path)
    refs = [m for m in filas if m["tipo"] == "referencia_proyecto"]
    assert {"ref_E11_modelo_final", "ref_E12_hibrido"} <= {m["model_id"] for m in refs}
    assert all(m["ejecutable_en_api"] is False for m in refs)
    assert next(m for m in filas if m["model_id"] == r["model_id"])["tipo"] == "candidato"


def test_metricas_definicion():
    m = inferencia.metricas([100, 200, 0], [110, 180, 10], horas=[7, 12, 4], rutas=["A", "A", "B"])
    assert m["mae"] == pytest.approx(40 / 3, abs=1e-3)
    assert m["wape"] == pytest.approx(40 / 300 * 100, abs=1e-3)
    assert m["pico"]["n"] == 1 and m["valle"]["n"] == 2


@requiere_modelo
def test_predecir_devuelve_el_contrato():
    for h in inferencia.HORIZONTES:
        r = inferencia.predecir("CRA 54", datetime(2025, 11, 12, 7, 30, tzinfo=ZONA), h)
        for campo in CAMPOS:
            assert campo in r, campo
        assert 0 <= r["p10"] <= r["pasajeros"] <= r["p90"]
        assert r["generated_at"].tzinfo is not None
        assert isinstance(r["explicacion"], list) and all(isinstance(x, str) for x in r["explicacion"])
        assert {"hora", "dia_semana", "lag7", "factor_nowcast"} <= set(r["variables"])
        assert inferencia.NOWCAST_MIN <= r["variables"]["factor_nowcast"] <= inferencia.NOWCAST_MAX


@requiere_modelo
def test_predecir_valida_entradas():
    with pytest.raises(ValueError):
        inferencia.predecir("CRA 54", datetime(2025, 11, 12, 7, 0), 45)
    with pytest.raises(ValueError):
        inferencia.predecir("RUTA X", datetime(2025, 11, 12, 7, 0), 60)


@requiere_modelo
def test_fuera_de_servicio_es_cero():
    r = inferencia.predecir("CL 72", datetime(2025, 12, 1, 2, 0), 30)
    assert r["pasajeros"] == 0


@requiere_modelo
def test_linea_base_prorratea_la_regla_manual():
    inst = datetime(2025, 11, 12, 7, 30, tzinfo=ZONA)
    r = inferencia.predecir("SILENCIO", inst, 60, model_id="b1_manual_8sem", usar_nowcast=False)
    t = inferencia.tabla_variables()
    esperado = (
        0.5 * t.at[("SILENCIO", date(2025, 11, 12), 7), "b8"] + 0.5 * t.at[("SILENCIO", date(2025, 11, 12), 8), "b8"]
    )
    assert r["pasajeros"] == pytest.approx(esperado, abs=0.01)


@requiere_modelo
def test_nowcast_no_usa_datos_posteriores_al_instante():
    inst = datetime(2025, 11, 12, 9, 30, tzinfo=ZONA)
    obs = datos.demanda_horaria(desde=date(2025, 11, 12), hasta=date(2025, 11, 12), rutas=["CRA 54"])
    r1 = inferencia.predecir("CRA 54", inst, 120, serie_observada=obs)
    futuro = obs.copy()
    m = futuro["hora"] >= 9  # la hora 9 aún no ha cerrado a las 9:30
    futuro.loc[m, "pasajeros"] = futuro.loc[m, "pasajeros"] * 5
    r2 = inferencia.predecir("CRA 54", inst, 120, serie_observada=futuro)
    assert r1["pasajeros"] == r2["pasajeros"] and r1["variables"]["factor_nowcast"] == r2["variables"]["factor_nowcast"]
    pasado = obs.copy()
    pasado.loc[pasado["hora"].isin([7, 8]), "pasajeros"] *= 3
    r3 = inferencia.predecir("CRA 54", inst, 120, serie_observada=pasado)
    assert r3["variables"]["factor_nowcast"] > r1["variables"]["factor_nowcast"]
    assert r3["variables"]["factor_nowcast"] <= inferencia.NOWCAST_MAX
    assert all(h["hora"] < 9 for h in r1["variables"]["horas_nowcast"])


@requiere_modelo
def test_evaluar_reporta_metricas():
    e = inferencia.evaluar(None, date(2025, 11, 1), date(2025, 11, 30))
    for campo in ("mae", "rmse", "wape", "por_ruta", "pico", "valle"):
        assert campo in e
    b = inferencia.evaluar("b1_manual_8sem", date(2025, 11, 1), date(2025, 11, 30))
    assert e["wape"] < b["wape"]
