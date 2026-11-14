"""Monitoreo del modelo (§9.4): PSI, umbral calibrado con el ruido propio, estado ok/aviso/alerta y foto de
variables."""
from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from app.servicios import datos, inferencia, monitoreo, variables

HAY_MODELO = (datos.carpeta_modelos() / "registro.json").exists()
requiere_modelo = pytest.mark.skipif(not HAY_MODELO, reason="falta el modelo empaquetado")


def test_psi_distribuciones_iguales_casi_cero_y_desplazada_alta():
    rng = np.random.default_rng(0)
    ref = monitoreo.referencia(rng.normal(100, 10, 20000))
    assert sum(ref["proporciones"]) == pytest.approx(1.0)
    assert len(ref["cortes"]) == monitoreo.BINS - 1
    assert monitoreo.psi(ref, rng.normal(100, 10, 5000)) < 0.01
    assert monitoreo.psi(ref, rng.normal(110, 10, 5000)) > 0.25          # una desviación estándar
    assert monitoreo.psi(ref, np.array([np.nan])) is None


def test_umbral_efectivo_usa_el_ruido_de_la_referencia():
    """Una variable diaria y estacional (como dia_lag7) trae su propio ruido: su umbral sube; las horarias no."""
    rng = np.random.default_rng(1)
    fechas = pd.date_range("2024-09-01", periods=364, freq="D")
    estacional = 1000 + 400 * np.sin(np.arange(364) / 58.0)                # nivel que cambia por estaciones
    t = pd.DataFrame({"fecha": np.repeat(fechas.date, 17), "hora": np.tile(np.arange(4, 21), 364)})
    t["dia_lag7"] = np.repeat(estacional, 17)
    t["lag7"] = rng.normal(300, 50, len(t))
    t["pasajeros"] = t["lag7"] + rng.normal(0, 5, len(t))
    ref = monitoreo.construir_referencia(t, t["pasajeros"].to_numpy())
    assert ref["variables"]["dia_lag7"]["ruido_p95"] > 0.25 > ref["variables"]["lag7"]["ruido_p95"]
    ventana = t[t["fecha"] >= date(2025, 8, 4)]
    u = monitoreo.umbrales_monitoreo({})
    d = monitoreo.deriva(ref, ventana, ventana["pasajeros"].to_numpy(), u)
    assert d["dia_lag7"]["umbral_alerta"] == pytest.approx(max(0.25, ref["variables"]["dia_lag7"]["ruido_p95"]))
    assert d["lag7"]["umbral_alerta"] == 0.25 and d["lag7"]["nivel"] == "ok"
    assert d["dia_lag7"]["dispara_reentreno"] is False and d["lag7"]["dispara_reentreno"] is True


def _m(**k):
    base = {"wape_movil": 0.12, "cobertura_p10_p90": 0.80, "psi": {}, "alertas_total": 0, "pct_descartadas": None}
    return base | k


@pytest.mark.parametrize("metricas, estado, texto", [
    (_m(), "ok", None),
    (_m(wape_movil=0.21), "alerta", "ALT-010"),
    (_m(wape_movil=0.19), "aviso", "wape_aviso"),
    (_m(cobertura_p10_p90=0.65), "alerta", "cobertura_min"),
    (_m(cobertura_p10_p90=0.72), "aviso", "cobertura_aviso"),
    (_m(cobertura_p10_p90=0.95), "aviso", "banda muy ancha"),
    (_m(psi={"lag7": {"psi": 0.4, "umbral_aviso": 0.1, "umbral_alerta": 0.25, "nivel": "alerta",
                      "dispara_reentreno": True}}), "alerta", "deriva en lag7"),
    (_m(psi={"dia_lag7": {"psi": 1.1, "umbral_aviso": 0.2, "umbral_alerta": 0.9, "nivel": "alerta",
                          "dispara_reentreno": False}}), "ok", None),
    (_m(alertas_total=10, pct_descartadas=0.6), "aviso", "descartadas"),
    (_m(alertas_total=3, pct_descartadas=1.0), "ok", None),               # pocas alertas: no se evalúa
])
def test_estado_del_monitoreo(metricas, estado, texto):
    e, motivos = monitoreo.estado_de(metricas, {"wape_max": 0.20})
    assert e == estado
    if texto:
        assert any(texto in m for m in motivos), motivos
    else:
        assert motivos == []


def test_sin_datos_en_la_ventana():
    assert monitoreo.estado_de({"estado": "sin_datos", "motivos": ["x"]}) == ("sin_datos", ["x"])


@requiere_modelo
def test_calcular_con_el_modelo_activo_fuera_de_muestra():
    m = monitoreo.calcular(inferencia.modelo_activo(), date(2025, 10, 31), {"wape_max": 0.20})
    assert m["n_observaciones"] == 28 * 3 * 17
    assert 0.05 < m["wape_movil"] < 0.30 and 0.5 < m["cobertura_p10_p90"] <= 1
    assert set(m["wape_por_ruta"]) == set(datos.nombres_rutas())
    assert {"lag7", "b8", "m4", "sd8", "nivel_7_34", "dia_lag7", "objetivo", "prediccion"} <= set(m["psi"])
    assert m["psi_variable_max"] != "dia_lag7"                              # dia_lag7 no dispara
    assert m["fuera_de_muestra"] is True


@requiere_modelo
def test_foto_de_variables_es_el_vector_que_vio_el_modelo():
    mid = inferencia.modelo_activo()
    modelo = inferencia.cargar(mid)
    inst = datetime(2025, 10, 6, 6, 30, tzinfo=inferencia.ZONA)
    pred = SimpleNamespace(model_id=mid, instante=inst, horizonte_min=60, ruta="SILENCIO")
    filas = monitoreo.filas_snapshot(pred)
    assert [(f["fecha"], f["hora"]) for f in filas] == [(date(2025, 10, 6), 6), (date(2025, 10, 6), 7)]
    tabla = inferencia.tabla_variables()
    x = variables.matriz_x(tabla.loc[[("SILENCIO", date(2025, 10, 6), 6)]].reset_index(),
                           inferencia._version_modelo(modelo))
    feats = filas[0]["features"]
    assert all(feats[c] == pytest.approx(float(x.iloc[0][c])) for c in x.columns)
    assert filas[0]["feature_version"] == modelo["feature_version"]
    assert 0 < feats["_fraccion_ventana"] < 1


# ------------------------------------------------------------------ foto por segmento y sentido (§7.3 paso 4)
def test_foto_por_segmento_se_apaga_con_la_configuracion(monkeypatch):
    from app import config

    monkeypatch.setattr(config, "obtener_ajustes", lambda: SimpleNamespace(foto_segmentos=False))
    estado: dict = {}
    assert monitoreo._modelo_foto_segmentos(estado) is None and estado["estado"] == "apagada"


def test_foto_por_segmento_sin_modelo_queda_omitida(monkeypatch, tmp_path):
    from app.servicios import modelo_segmentos

    monkeypatch.setenv("MODELOS_DIR", str(tmp_path))            # carpeta sin registro de segmentos
    modelo_segmentos.limpiar_cache()
    estado: dict = {}
    assert monitoreo._modelo_foto_segmentos(estado) is None
    assert estado["estado"] == "omitida" and "segmentos" in estado["avisos"][0]


@pytest.mark.parametrize("contenido", ['{"activo": "x", "modelos": {', "no es json"])
def test_foto_por_segmento_con_registro_corrupto_queda_omitida_sin_tumbar_el_ciclo(monkeypatch, tmp_path, contenido):
    """El modelo de segmentos se carga fuera del punto de guardado de la foto: un registro que no es JSON válido
    (ValueError, no LookupError ni RuntimeError) solo omite las filas por segmento; antes salía de guardar_snapshot y
    tumbaba el ciclo de §14.2."""
    from app.servicios import modelo_segmentos

    (tmp_path / "segmentos").mkdir()
    (tmp_path / "segmentos" / modelo_segmentos.ARCHIVO_REGISTRO).write_text(contenido, encoding="utf-8")
    monkeypatch.setenv("MODELOS_DIR", str(tmp_path))
    modelo_segmentos.limpiar_cache()
    seg, modelo = monitoreo._inicio_foto_segmentos({})
    assert modelo is None and seg["estado"] == "omitida" and seg["filas"] == 0
    assert seg["avisos"][0].startswith("sin modelo de segmentos")


def test_foto_por_segmento_sin_horas_de_servicio_no_escribe(monkeypatch):
    """Una ventana sin horas de servicio con demanda no tiene filas por segmento: no se envía nada y sigue «ok»."""
    from app.servicios import modelo_segmentos

    def no_escribe(*_a, **_k):
        pytest.fail("no debía escribir")

    monkeypatch.setattr(modelo_segmentos, "filas_foto", lambda *_a, **_k: [])
    sesion = SimpleNamespace(flush=no_escribe, execute=no_escribe)
    estado: dict = {"estado": "ok", "filas": 0}
    pred = SimpleNamespace(ruta="SILENCIO", horizonte_min=30)
    assert monitoreo._foto_segmentos(sesion, pred, None, None, {"model_id": "x"}, None, estado) == 0
    assert estado == {"estado": "ok", "filas": 0}


def test_foto_por_segmento_que_falla_no_escribe_y_avisa(monkeypatch):
    """Si las filas por segmento fallan, no se escribe nada de ellas (la de la ruta sigue) y queda el aviso."""
    from app.servicios import modelo_segmentos

    def falla(*_a, **_k):
        raise RuntimeError("variables de segmento no disponibles (simulado)")

    monkeypatch.setattr(modelo_segmentos, "filas_foto", falla)
    sesion = SimpleNamespace(execute=lambda *_a, **_k: pytest.fail("no debía escribir"))
    pred = SimpleNamespace(ruta="SILENCIO", horizonte_min=60)
    estado: dict = {"estado": "ok", "filas": 0}
    assert monitoreo._foto_segmentos(sesion, pred, None, None, {"model_id": "x"}, None, estado) == 0
    assert estado["estado"] == "fallo" and "simulado" in estado["avisos"][0]
    assert monitoreo._foto_segmentos(sesion, pred, None, None, None, None, estado) == 0    # sin modelo: nada
