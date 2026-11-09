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
    assert {"ref_experimento11_lightgbm", "ref_experimento12_hibrido"} <= {m["model_id"] for m in refs}
    assert all(m["ejecutable_en_api"] is False for m in refs)
    assert not any("modelo_final" in m["model_id"] for m in refs) and "otro" in refs[0]["nota"]
    assert next(m for m in filas if m["model_id"] == r["model_id"])["tipo"] == "candidato"


def test_metricas_definicion():
    m = inferencia.metricas([100, 200, 0], [110, 180, 10], horas=[7, 12, 4], rutas=["A", "A", "B"])
    assert m["mae"] == pytest.approx(40 / 3, abs=1e-3)
    assert m["wape"] == pytest.approx(40 / 300 * 100, abs=1e-3)
    assert m["pico"]["n"] == 1 and m["valle"]["n"] == 2
    assert set(m["por_franja"]) == {"04-05", "06-08 pico", "09-16 valle"}
    assert m["smape"] == pytest.approx((20 / 210 + 40 / 380 + 2) / 3 * 100, abs=1e-3)


def test_smape_es_cero_si_el_pronostico_es_exacto():
    assert inferencia.smape([0, 5, 100], [0, 5, 100]) == 0.0
    assert inferencia.smape([], []) is None


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
def test_linea_base_reparte_la_regla_manual_con_el_perfil_intrahorario():
    inst = datetime(2025, 11, 12, 7, 30, tzinfo=ZONA)
    r = inferencia.predecir("SILENCIO", inst, 60, model_id="b1_manual_8sem", usar_nowcast=False)
    t = inferencia.tabla_variables()
    perfil = inferencia.perfil_intrahorario()
    f = date(2025, 11, 12)
    tipo = int(t.at[("SILENCIO", f, 7), "tipo_dia"])
    s7, s8 = perfil.get(("SILENCIO", tipo, 7), 0.5), perfil.get(("SILENCIO", tipo, 8), 0.5)
    esperado = (1 - s7) * t.at[("SILENCIO", f, 7), "b8"] + s8 * t.at[("SILENCIO", f, 8), "b8"]
    assert r["pasajeros"] == pytest.approx(esperado, abs=0.01)


@requiere_modelo
def test_sin_perfil_el_reparto_es_por_minutos(monkeypatch):
    monkeypatch.setattr(inferencia, "perfil_intrahorario", lambda: {})
    inst = datetime(2025, 11, 12, 7, 30, tzinfo=ZONA)
    r = inferencia.predecir("SILENCIO", inst, 60, model_id="b1_manual_8sem", usar_nowcast=False)
    t = inferencia.tabla_variables()
    esperado = (
        0.5 * t.at[("SILENCIO", date(2025, 11, 12), 7), "b8"] + 0.5 * t.at[("SILENCIO", date(2025, 11, 12), 8), "b8"]
    )
    assert r["pasajeros"] == pytest.approx(esperado, abs=0.01)
    assert r["variables"]["perfil_intrahorario"] is False


def test_fraccion_hora_las_dos_medias_horas_suman_la_hora():
    for s in (0.05, 0.3, 0.5, 0.535, 0.95):
        assert inferencia.fraccion_hora(0, 30, s) + inferencia.fraccion_hora(30, 60, s) == pytest.approx(1.0)
        assert inferencia.fraccion_hora(0, 60, s) == pytest.approx(1.0)
        assert inferencia.fraccion_hora(0, 30, s) == pytest.approx(s)
    for a, b in ((0, 15), (10, 40), (45, 60), (30, 60)):
        assert inferencia.fraccion_hora(a, b, 0.5) == pytest.approx((b - a) / 60)  # cae al prorrateo por minutos
    ini = datetime(2025, 11, 12, 7, 0, tzinfo=ZONA)
    tramos = inferencia._tramos(ini, ini + timedelta(minutes=30), "CRA 54")
    perfil = inferencia.perfil_intrahorario()
    assert tramos[0][2] == pytest.approx(perfil.get(("CRA 54", 0, 7), 0.5))
    completo = inferencia._tramos(ini, ini + timedelta(minutes=120), "CRA 54")
    assert [x[2] for x in completo] == pytest.approx([1.0, 1.0])


# ------------------------------------------------------------------------------- versiones de variables (fv1 / fv2)
def test_modelo_fv1_sigue_cargando_y_prediciendo_con_codigo_fv2(serie, tmp_path):
    """Reversión (RF-019): el código registra fv1 y fv2; un modelo fv1 se carga y predice con sus columnas."""
    assert variables.FEATURE_VERSION == variables.FV2
    r1 = inferencia.entrenar(date(2025, 4, 15), 42, serie=serie, dir_modelos=tmp_path, hiper=HIPER_RAPIDO,
                             version=variables.FV1)
    r2 = _entrenar(serie, tmp_path)
    assert r1["model_id"].startswith("hgb_fv1_") and r2["model_id"].startswith("hgb_fv2_")
    m1 = inferencia.cargar(r1["model_id"], tmp_path)
    m2 = inferencia.cargar(r2["model_id"], tmp_path)
    assert m1["feature_version"] == variables.FV1 and m2["feature_version"] == variables.FV2
    assert m1["punto"].n_features_in_ == len(variables.COLUMNAS_FV1)
    assert m2["punto"].n_features_in_ == len(variables.COLUMNAS_FV2)
    assert m1["shap_exacto"] is False and m2["shap_exacto"] is True
    filas = inferencia._filas_utiles(variables.construir_variables(serie)).tail(50)
    for m in (m1, m2):
        p, lo, hi = inferencia._predecir_filas(m, filas)
        assert len(p) == 50 and (lo <= p).all() and (p <= hi).all()
    man = json.loads((tmp_path / r1["model_id"] / "manifest.json").read_text(encoding="utf-8"))
    assert man["variables"] == variables.COLUMNAS_FV1 and man["categoricas"] == ["ruta_cod"]


def test_cargar_rechaza_version_no_registrada(serie, tmp_path):
    r = _entrenar(serie, tmp_path)
    ruta = tmp_path / r["model_id"] / "manifest.json"
    man = json.loads(ruta.read_text(encoding="utf-8"))
    man["feature_version"] = "fv9-2099-01-01"
    ruta.write_text(json.dumps(man), encoding="utf-8")
    inferencia.limpiar_cache()
    with pytest.raises(inferencia.ErrorIntegridadModelo):
        inferencia.cargar(r["model_id"], tmp_path)


@requiere_modelo
def test_modelo_fv1_empaquetado_predice_con_codigo_actual():
    reg = inferencia.registro()
    fv1 = [k for k, m in reg["modelos"].items() if m.get("feature_version") == variables.FV1 and m.get("artefacto")]
    if not fv1:
        pytest.skip("no hay modelo fv1 empaquetado")
    r = inferencia.predecir("CRA 54", datetime(2025, 11, 12, 7, 30, tzinfo=ZONA), 60, model_id=fv1[0])
    assert r["feature_version"] == variables.FV1 and r["pasajeros"] > 0
    assert r["explicacion_local"]["metodo"] == "importancia_global_permutacion"


# ------------------------------------------------------------------------------- explicación local SHAP
def test_shap_base_por_factores_reconstruye_el_pronostico(serie, tmp_path):
    r = _entrenar(serie, tmp_path)
    m = inferencia.cargar(r["model_id"], tmp_path)
    filas = inferencia._filas_utiles(variables.construir_variables(serie)).tail(40)
    e = inferencia.explicar_filas(m, filas)
    assert e is not None and e["phi"].shape == (40, len(variables.COLUMNAS_FV2))
    reconstruido = np.exp(e["base_log"]) * np.prod(np.exp(e["phi"]), axis=1)
    pred = m["punto"].predict(variables.matriz_x(filas, variables.FV2))
    assert np.max(np.abs(reconstruido - pred) / np.maximum(pred, 1e-9)) < 1e-6
    man = json.loads(Path(r["manifiesto"]).read_text(encoding="utf-8"))
    assert man["explicabilidad"]["shap_local"] is True
    assert man["explicabilidad"]["error_reconstruccion_log_max"] < 1e-6
    assert {x["variable"] for x in man["explicabilidad"]["media_abs_shap_log"]} == set(variables.COLUMNAS_FV2)


@requiere_modelo
def test_predecir_trae_explicacion_local_y_banda_calibrada():
    r = inferencia.predecir("CL 72", datetime(2025, 11, 12, 8, 0, tzinfo=ZONA), 60)
    for campo in ("p10_modelo", "p90_modelo", "ajuste_conformal", "cobertura_objetivo", "explicacion_local"):
        assert campo in r, campo
    assert 0 <= r["p10"] <= r["pasajeros"] <= r["p90"]
    assert r["p10_modelo"] <= r["pasajeros"] <= r["p90_modelo"]
    c = r["variables"]["conformal"]
    assert c["cobertura_objetivo"] == 0.8 and r["calibracion_version"] == c["version"]
    if c["version"] == "v2":   # calibración versionada por bloque horario (calibracion_v2.json del modelo)
        assert c["archivo"] == "calibracion_v2.json" and len(c["q_por_hora"]) == len(c["grupos"]) >= 1
    else:                      # v1: conformal móvil por ruta
        assert c["ventana_dias"] == inferencia.CONFORMAL_VENTANA_DIAS
    if c["aplicado"]:
        assert r["ajuste_conformal"] == c["q"]
    el = r["explicacion_local"]
    if el["metodo"] == "shap_tree_exacto":
        assert len(el["factores"]) == 5 and el["error_reconstruccion_rel"] < 1e-6
        efectos = sum(f["efecto_pasajeros"] for f in el["factores"]) + el["efecto_resto_pasajeros"]
        assert efectos == pytest.approx(el["pronostico_hora"] - el["base_pasajeros"], abs=0.5)
        assert "variables" in r and r["variables"]["explicacion_local"] == el


# ------------------------------------------------------------------------------- conformal móvil
def _puntajes_sinteticos(dias: int = 150, semilla: int = 3) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Banda del modelo demasiado estrecha (cubre ~50 %) con residuos heterocedásticos que cambian por día."""
    rng = np.random.default_rng(semilla)
    filas = []
    for d in range(dias):
        f = date(2025, 1, 1) + timedelta(days=d)
        sigma = 0.10 + 0.10 * (1 + np.sin(d / 20))  # el ruido relativo cambia con el tiempo
        for h in range(4, 21):
            p = 200 + 300 * np.exp(-((h - 7) ** 2) / 6)
            y = p * (1 + rng.normal(0, sigma))
            filas.append({"ruta": "SILENCIO", "fecha": f, "hora": h, "p": p, "lo": p * 0.93, "hi": p * 1.07, "y": y})
    d = pd.DataFrame(filas)
    d["s"] = inferencia.puntajes_conformal(d["p"], d["lo"], d["hi"], d["y"])
    return d, d[["ruta", "fecha", "s"]]


def test_conformal_lleva_la_cobertura_al_80_por_ciento():
    d, pz = _puntajes_sinteticos()
    qs = inferencia.cuantiles_conformal_movil(pz, list(dict.fromkeys(zip(d["ruta"], d["fecha"], strict=False))))
    d["q"] = [qs[(r, f)]["q"] for r, f in zip(d["ruta"], d["fecha"], strict=False)]
    e = d[d["q"].notna()].copy()
    lo, hi = inferencia.aplicar_conformal(e["p"], e["lo"], e["hi"], None)
    cub_original = ((e["y"] >= lo) & (e["y"] <= hi)).mean()
    lo_c = np.clip(np.minimum(e["lo"] - e["q"] * np.maximum(e["p"], 1), e["p"]), 0, None)
    hi_c = np.maximum(e["hi"] + e["q"] * np.maximum(e["p"], 1), e["p"])
    cub = ((e["y"] >= lo_c) & (e["y"] <= hi_c)).mean()
    assert cub_original < 0.6
    assert abs(cub - 0.80) <= 0.02, cub


def test_conformal_sin_dias_suficientes_no_ajusta_y_registra_el_motivo():
    _, pz = _puntajes_sinteticos(dias=20)
    r = inferencia.cuantiles_conformal_movil(pz, [("SILENCIO", date(2025, 1, 10)), ("SILENCIO", date(2025, 1, 20))])
    a, b = r[("SILENCIO", date(2025, 1, 10))], r[("SILENCIO", date(2025, 1, 20))]
    assert a["aplicado"] is False and a["q"] is None and "mínimo 14" in a["motivo"] and a["dias_calibracion"] == 9
    assert b["aplicado"] is True and b["dias_calibracion"] == 19
    otra = inferencia.cuantiles_conformal_movil(pz, [("CL 72", date(2025, 1, 20))])[("CL 72", date(2025, 1, 20))]
    assert otra["aplicado"] is False  # la calibración es por ruta


def test_conformal_no_usa_el_mismo_dia_ni_posteriores():
    _, pz = _puntajes_sinteticos()
    d0 = date(2025, 3, 15)
    base = inferencia.cuantiles_conformal_movil(pz, [("SILENCIO", d0)])[("SILENCIO", d0)]
    alterado = pz.copy()
    alterado.loc[alterado["fecha"] >= d0, "s"] = 99.0
    otro = inferencia.cuantiles_conformal_movil(alterado, [("SILENCIO", d0)])[("SILENCIO", d0)]
    assert base == otro and base["dias_calibracion"] == inferencia.CONFORMAL_VENTANA_DIAS


def test_cuantil_conformal_nivel_de_muestra_finita():
    s = np.arange(1, 11, dtype=float)  # n = 10 -> nivel ceil(11 * 0,8) / 10 = 0,9 -> valor 9
    assert inferencia.cuantil_conformal(s) == 9.0
    assert inferencia.cuantil_conformal([]) is None
    lo, hi = inferencia.aplicar_conformal([100.0], [90.0], [110.0], 0.1)
    assert lo[0] == pytest.approx(80.0) and hi[0] == pytest.approx(120.0)
    lo, hi = inferencia.aplicar_conformal([100.0], [90.0], [110.0], -0.5)  # q negativo estrecha sin cruzar p
    assert lo[0] == pytest.approx(100.0) and hi[0] == pytest.approx(100.0)


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
    for campo in ("smape", "por_franja", "cobertura_p10_p90", "cobertura_p10_p90_conformal", "bajo_p10_pct"):
        assert campo in e, campo
    b = inferencia.evaluar("b1_manual_8sem", date(2025, 11, 1), date(2025, 11, 30))
    assert e["wape"] < b["wape"]


def _script_evaluar_modelo():
    import importlib.util

    ruta = Path(__file__).resolve().parents[2] / "scripts" / "evaluar_modelo.py"
    spec = importlib.util.spec_from_file_location("evaluar_modelo_prueba", ruta)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_bootstrap_por_bloques_es_reproducible_y_contiene_la_estimacion():
    ev = _script_evaluar_modelo()
    rng = np.random.default_rng(11)
    filas = []
    for d in range(60):
        f = date(2025, 1, 1) + timedelta(days=d)
        for h in range(4, 21):
            y = float(rng.poisson(300))
            filas.append({"fecha": f, "y": y, "a": y * (1 + rng.normal(0, 0.10)), "b": y * (1 + rng.normal(0, 0.20))})
    df = pd.DataFrame(filas)
    r1 = ev.bootstrap(df, ["a", "b"], ["b"])
    r2 = ev.bootstrap(df, ["a", "b"], ["b"])
    assert r1 == r2 and r1["B"] == 2000 and r1["bloque_dias"] == 7 and r1["dias"] == 60
    for c in ("a", "b"):
        w = ev.met(df["y"], df[c])["wape"]
        assert r1[c]["ic95"][0] <= w <= r1[c]["ic95"][1]
    assert r1["a_menos_b"]["ic95"][1] < 0 and r1["a_menos_b"]["p_mejora"] > 0.95
    assert ev.met([0, 5, 100], [0, 5, 100])["smape"] == 0.0


@requiere_modelo
def test_fv2_activo_no_empeora_a_fv1_en_validacion():
    """La compuerta de activación: el fv2 registrado tiene WAPE de validación <= al del fv1 (misma ventana y filas)."""
    reg = inferencia.registro()
    activo = reg["modelos"].get(reg["activo"], {})
    fv1 = reg["modelos"].get("hgb_fv1_20250831_s42")
    if activo.get("feature_version") != variables.FV2 or fv1 is None:
        pytest.skip("el registro empaquetado no tiene fv2 activo y fv1 de referencia")
    assert activo["wape_validacion"] <= fv1["wape_validacion"]
    assert activo["estado"] == "activo" and fv1["estado"] != "activo"
    assert sum(1 for m in reg["modelos"].values() if m.get("estado") == "activo") == 1


def test_entrenar_por_defecto_deja_candidato_y_no_toca_el_activo(serie, tmp_path):
    """El trabajo de entrenamiento de la API registra un candidato: activar es decisión de la gobernanza (RF-019)."""
    r = _entrenar(serie, tmp_path)
    reg = inferencia.registro(tmp_path)
    assert reg["activo"] == "b1_manual_8sem" and reg["modelos"][r["model_id"]]["estado"] == "candidato"
    assert r["decision"].startswith(("candidato", "se conserva"))
    r2 = inferencia.entrenar(date(2025, 4, 15), 42, serie=serie, dir_modelos=tmp_path / "cli", hiper=HIPER_RAPIDO,
                             activar_si_mejora=True)
    reg2 = inferencia.registro(tmp_path / "cli")
    if r2["supera_linea_base"]:
        assert reg2["activo"] == r2["model_id"] and reg2["modelos"][r2["model_id"]]["estado"] == "activo"
    assert sum(1 for m in reg2["modelos"].values() if m.get("estado") == "activo") <= 1


def test_hiperparametros_explicitos_y_sin_cambio_de_modelo():
    """La tasa de aprendizaje va explícita en cada estimador y vale lo mismo que en HIPER_DEFECTO (y que en los
    hiperparámetros del manifiesto del activo): el modelo entrenado no cambia."""
    for perdida, cuantil in (("poisson", None), ("quantile", 0.1), ("quantile", 0.9)):
        m = inferencia._modelo_hgb(perdida, 42, dict(inferencia.HIPER_DEFECTO), cuantil, version=variables.FV2)
        assert m.learning_rate == inferencia.HIPER_DEFECTO["learning_rate"] == 0.05
        assert m.max_iter == inferencia.HIPER_DEFECTO["max_iter"] and m.random_state == 42
    rapido = inferencia._modelo_hgb("poisson", 7, dict(inferencia.HIPER_DEFECTO, learning_rate=0.2, max_iter=5))
    assert rapido.learning_rate == 0.2 and rapido.max_iter == 5


def test_frases_de_la_explicacion_en_orden():
    """La explicación de predecir conserva sus frases y su orden (hora, factor intradía, ventana, banda, modelo)."""
    r = inferencia.predecir("CRA 54", datetime(2025, 11, 12, 7, 10, tzinfo=inferencia.ZONA), 60)
    e = r["explicacion"]
    assert e[0].startswith("Hora 7:00 del") and any(x.startswith("Misma hora hace 7 días") for x in e[:3])
    i_ventana = next(i for i, x in enumerate(e) if x.startswith("Ventana de 60 min repartida"))
    assert e[i_ventana - 1].startswith(("Factor intradía", "Sin observaciones suficientes"))
    assert e[i_ventana + 1].startswith("Banda P10-P90")
    fuera = inferencia.predecir("CL 72", datetime(2025, 11, 20, 21, 30, tzinfo=inferencia.ZONA), 30)
    assert fuera["explicacion"][0].startswith("La ventana cae fuera del horario") and fuera["pasajeros"] == 0
    assert not any(x.startswith("Banda P10-P90") for x in fuera["explicacion"])


def test_sin_tasa_de_aprendizaje_se_usa_la_de_scikit_learn():
    from sklearn.ensemble import HistGradientBoostingRegressor

    m = inferencia._modelo_hgb("poisson", 1, {"max_iter": 3})
    assert m.learning_rate == HistGradientBoostingRegressor().learning_rate == inferencia.LEARNING_RATE_SKLEARN


# ------------------------------------------------------------------ prueba reservada fuera del entrenamiento (§9.3)
def test_entrenar_no_mide_la_prueba_reservada_y_el_manifiesto_no_guarda_estado(serie, tmp_path):
    """La selección y la compuerta usan solo la validación: entrenar() no calcula métricas de la prueba reservada
    (las reporta scripts/evaluar_modelo.py). El estado vive en el registro, no en el manifiesto."""
    r = _entrenar(serie, tmp_path)
    assert set(r["metricas"]) == {"validacion"}
    man = json.loads(Path(r["manifiesto"]).read_text(encoding="utf-8"))
    assert set(man["metricas"]) == {"validacion"} and "prueba" not in man["nowcast"]
    assert "estado" not in man and "prueba" in man["particion"] and "evaluar_modelo.py" in man["nota_prueba_reservada"]
    ficha = inferencia.registro(tmp_path)["modelos"][r["model_id"]]
    assert ficha["estado"] == "candidato" and "wape_prueba" not in ficha and ficha["wape_validacion"] is not None
    assert man["codigo_normalizacion"].startswith("texto UTF-8 con fin de línea LF")
    assert set(man["codigo_sha256"]) == set(man["codigo_sin_docstring_sha256"]) == {"variables.py", "inferencia.py"}


def test_huella_del_codigo_no_depende_del_fin_de_linea():
    """§9.3 «registrar el código»: el SHA-256 se calcula con LF, así que un clon de Windows (CRLF) y uno de Linux dan
    el mismo valor; sin el docstring del módulo, cambiar solo la documentación no cambia la huella."""
    lf = '"""Doc."""\n\nimport os\n\n\ndef f():\n    return 1\n'
    assert inferencia.sha256_codigo(lf) == inferencia.sha256_codigo(lf.replace("\n", "\r\n"))
    otro_doc = lf.replace('"""Doc."""', '"""Documentación nueva,\nmás larga."""')
    assert inferencia.sha256_codigo(lf) != inferencia.sha256_codigo(otro_doc)
    assert (inferencia.sha256_codigo(inferencia.sin_docstring_de_modulo(lf))
            == inferencia.sha256_codigo(inferencia.sin_docstring_de_modulo(otro_doc.replace("\n", "\r\n"))))
    assert inferencia.sin_docstring_de_modulo("x = 1\n") == "x = 1\n"


@requiere_modelo
def test_preprocesamiento_es_el_del_entrenamiento_del_activo():
    """§9.2: el preprocesamiento (variables.py, sin su docstring y con LF) es el mismo con el que se entrenó el
    modelo activo; el manifiesto registra además el commit y la forma de normalizar."""
    activo = inferencia.modelo_activo()
    man = json.loads((datos.carpeta_modelos() / activo / "manifest.json").read_text(encoding="utf-8"))
    texto = Path(variables.__file__).read_text(encoding="utf-8")
    assert man["codigo_sin_docstring_sha256"]["variables.py"] == inferencia.sha256_codigo(
        inferencia.sin_docstring_de_modulo(texto))
    assert "LF" in man["codigo_normalizacion"] and "codigo_commit" in man and "estado" not in man


# ------------------------------------------------------------------ datos recientes en la inferencia (RF-013)
def _observados_sinteticos(desde: date, nuevo: date) -> pd.DataFrame:
    """Horas «validadas» de la serie desde `desde` (una corregida) y un día `nuevo` posterior al Parquet."""
    s = datos.demanda_horaria(desde=desde)
    obs = s[["ruta", "fecha", "hora", "pasajeros", "salidas"]].copy()
    obs.loc[obs["fecha"] == desde + timedelta(days=3), "pasajeros"] *= 1.1
    ultimo = s[s["fecha"] == s["fecha"].max()][["ruta", "fecha", "hora", "pasajeros", "salidas"]].copy()
    return pd.concat([obs, ultimo.assign(fecha=nuevo)], ignore_index=True)


@requiere_modelo
def test_variables_con_lo_validado_son_las_de_recalcular_toda_la_serie():
    """Solo se recalculan los días tocados (y sus rezagos): el resultado es idéntico a reconstruir la tabla con toda la
    serie validada, y la tabla llega 7 días más allá del último día validado."""
    from app.servicios import politica

    base, serie = inferencia.tabla_variables(), datos.demanda_horaria()
    nuevo = max(serie["fecha"]) + timedelta(days=9)
    obs = _observados_sinteticos(max(serie["fecha"]) - timedelta(days=20), nuevo)
    incremental = inferencia.tabla_con_observados(base, serie, obs)
    unida, info = politica.superponer_observados(serie, obs)
    completa = variables.construir_variables(unida, contexto=datos.contexto_operacional())
    completa = completa.set_index(["ruta", "fecha", "hora"]).sort_index()
    pd.testing.assert_frame_equal(incremental[completa.columns], completa, check_dtype=False)
    assert inferencia.rango_tabla(incremental)[1] == nuevo + timedelta(days=variables.DIAS_EXTRA)
    assert inferencia.ultimo_dato_real(incremental) == nuevo and info["filas_con_valor_distinto"] > 0
    fila = incremental.loc[("CRA 54", nuevo + timedelta(days=7), 6)]
    assert fila["lag7"] == obs[(obs["ruta"] == "CRA 54") & (obs["fecha"] == nuevo) & (obs["hora"] == 6)][
        "pasajeros"].iloc[0]
    sin_cambios = inferencia.tabla_con_observados(base, serie, serie[serie["fecha"] >= nuevo - timedelta(days=60)][
        ["ruta", "fecha", "hora", "pasajeros", "salidas"]])
    pd.testing.assert_frame_equal(sin_cambios, base)


@requiere_modelo
def test_sin_la_serie_validada_el_pronostico_despues_del_parquet_dice_su_rango():
    fin = inferencia.rango_tabla(inferencia.tabla_variables())[1]
    with pytest.raises(ValueError, match=f"cubre .* a {fin}"):
        inferencia.predecir("CRA 54", datetime.combine(fin + timedelta(days=1), datetime.min.time()).replace(
            hour=6, tzinfo=ZONA), 60)


@requiere_modelo
def test_predecir_horas_es_predecir_hora_por_hora():
    """El lote (una llamada a los modelos y a SHAP) devuelve exactamente lo mismo que predecir() en cada hora."""
    inicios = [datetime(2025, 12, 18, h, tzinfo=ZONA) for h in range(3, 22)]   # incluye horas fuera de servicio
    lote = inferencia.predecir_horas("CL 72", inicios)
    for a, inicio in zip(lote, inicios, strict=True):
        b = inferencia.predecir("CL 72", inicio, 60, usar_nowcast=False)
        assert {k: v for k, v in a.items() if k not in ("generated_at", "latencia_ms")} == \
            {k: v for k, v in b.items() if k not in ("generated_at", "latencia_ms")}, inicio
        assert a["latencia_ms"] >= 0
    con_nowcast = inferencia.predecir_horas("SILENCIO", [datetime(2025, 12, 18, 9, 20, tzinfo=ZONA)],
                                            horizonte_min=120, usar_nowcast=True)[0]
    directo = inferencia.predecir("SILENCIO", datetime(2025, 12, 18, 9, 20, tzinfo=ZONA), 120)
    assert con_nowcast["pasajeros"] == directo["pasajeros"] and con_nowcast["variables"] == directo["variables"]
    assert inferencia.predecir_horas("SILENCIO", []) == []
