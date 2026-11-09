"""El backtest de alertas (docs/evidencias/alertas/backtest_alertas*.json) se reproduce con el código actual.

Corre scripts/backtest_alertas.py sobre la copia temporal de datos/ (modelo activo, su calibración versionada y el
mismo periodo) y compara, código por código, las alertas por ruta y día con la evidencia publicada. Si cambia el
modelo, la calibración de la banda o una regla, la prueba falla hasta que se vuelva a generar la evidencia.

El resumen de la reproducción se guarda con tests/evidencia.guardar_evidencia: en un directorio temporal por omisión
y en docs/evidencias/alertas/ solo con GENERAR_EVIDENCIAS=1 (correr la prueba no ensucia el repositorio).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.datos_ml

RAIZ = Path(__file__).resolve().parents[2]
EVIDENCIA = RAIZ / "docs" / "evidencias" / "alertas" / "backtest_alertas.json"
EVIDENCIA_PRONOSTICO = RAIZ / "docs" / "evidencias" / "alertas" / "backtest_alertas_pronostico.json"


def _guardar(ruta_relativa: str, contenido) -> Path | None:
    """guardar_evidencia (C6) si el módulo compartido existe; si no, nada (la prueba no depende de escribir)."""
    try:
        from tests.evidencia import guardar_evidencia
    except ImportError:
        return None
    return guardar_evidencia(ruta_relativa, contenido)


@pytest.mark.skipif(not EVIDENCIA.exists(), reason="sin la evidencia del backtest")
def test_backtest_reproduce_la_evidencia(datos_copia, manifiesto_activo, tmp_path):
    from scripts import backtest_alertas

    publicado = json.loads(EVIDENCIA.read_text(encoding="utf-8"))
    if publicado.get("model_id") != manifiesto_activo["model_id"]:
        pytest.skip("la evidencia es de otro modelo")
    r = backtest_alertas.main(["--sin-sensibilidad", "--salida", str(tmp_path)])
    assert r["periodo"] == publicado["periodo"]
    assert r["por_defecto"]["dias_ruta"] == publicado["por_defecto"]["dias_ruta"]
    cal = manifiesto_activo.get("calibracion")
    assert r["calibracion_version"] == publicado.get("calibracion_version", "v1") == (cal["version"] if cal else "v1")
    comparacion = {}
    for codigo, v in publicado["por_defecto"]["por_codigo"].items():
        ahora = r["por_defecto"]["por_codigo"][codigo]
        comparacion[codigo] = {"publicado": v["alertas"], "reproducido": ahora["alertas"],
                               "precision_publicada": v["precision_proxy"], "precision": ahora["precision_proxy"]}
        assert ahora["alertas"] == v["alertas"], codigo
        assert ahora["precision_proxy"] == v["precision_proxy"], codigo
    assert r["por_defecto"]["observadas_por_ruta_dia"] == publicado["por_defecto"]["observadas_por_ruta_dia"]
    # la persistencia y el P10 siguen bajando las alertas ALT-005..ALT-009 frente a las reglas anteriores (§18)
    assert (r["por_defecto"]["observadas_por_ruta_dia_005_009"]
            < r["reglas_anteriores"]["observadas_por_ruta_dia_005_009"] / 5)
    # el detector de rupturas se reproduce: mismas detecciones y misma tasa de falsas alarmas sin cambio
    assert r["por_defecto"]["rupturas"] == publicado["por_defecto"]["rupturas"]
    assert (r["detector_rupturas"]["falsas_alarmas_sin_cambio"]
            == publicado["detector_rupturas"]["falsas_alarmas_sin_cambio"])
    ruta = _guardar("alertas/reproduccion_backtest.json", {
        "periodo": r["periodo"], "model_id": r["model_id"], "calibracion_version": r["calibracion_version"],
        "observadas_por_ruta_dia": r["por_defecto"]["observadas_por_ruta_dia"], "por_codigo": comparacion,
        "reproduce_la_evidencia": True})
    assert ruta is None or ruta.exists()


def test_backtest_de_pronostico_compara_unidades_por_hora(datos_copia, tmp_path):
    """Modo --pronostico en dos días: las tres ventanas de las 6:00 miran la misma franja, la variante actual da a lo
    sumo una alerta de cada código por ruta y día y nunca más ALT-001/ALT-002 que la comparación anterior."""
    from datetime import date

    from scripts import backtest_alertas

    r = backtest_alertas.pronostico(date(2025, 10, 14), date(2025, 10, 15), tmp_path)
    assert r["dias_ruta"] == 6
    assert r["con_factor_carga"] is True
    assert len({k.split("->")[1] for k in r["franja_por_horizonte"]}) == 1
    antes, ahora = r["variantes"]["ventana"]["por_codigo"], r["variantes"]["franja"]["por_codigo"]
    for codigo in backtest_alertas.CODIGOS_PRONOSTICO:
        assert ahora[codigo]["alertas"] <= r["dias_ruta"], codigo
        assert ahora[codigo]["evaluables"] <= ahora[codigo]["alertas"], codigo
    for codigo in ("ALT-001", "ALT-002"):
        assert ahora[codigo]["alertas"] <= antes[codigo]["alertas"], codigo
    assert (tmp_path / "backtest_alertas_pronostico.md").exists()


@pytest.mark.skipif(not EVIDENCIA_PRONOSTICO.exists(), reason="sin la evidencia del backtest de pronóstico")
def test_evidencia_de_pronostico_publicada():
    """La evidencia publicada mide con la carga crítica del optimizador: una alerta por franja, confirmación con lo
    real en las mismas unidades y más discriminación (lift) que la comparación anterior."""
    publicado = json.loads(EVIDENCIA_PRONOSTICO.read_text(encoding="utf-8"))
    assert publicado["con_factor_carga"] is True
    ahora = publicado["variantes"]["franja"]["por_codigo"]
    antes = publicado["variantes"]["ventana"]["por_codigo"]
    sin_factor = publicado["antes_sin_factor"]["por_codigo"]
    assert ahora["ALT-001"]["por_ruta_dia"] < sin_factor["ALT-001"]["por_ruta_dia"]
    assert ahora["ALT-002"]["por_ruta_dia"] < sin_factor["ALT-002"]["por_ruta_dia"]
    assert ahora["ALT-001"]["por_ruta_dia"] < antes["ALT-001"]["por_ruta_dia"] / 2
    assert ahora["ALT-002"]["por_ruta_dia"] < antes["ALT-002"]["por_ruta_dia"] / 2
    for codigo in ("ALT-001", "ALT-002"):
        assert ahora[codigo]["lift"] > antes[codigo]["lift"], codigo
    assert publicado["festivos_entre_semana"], "el periodo trae festivos entre semana (tratados como festivo)"


@pytest.mark.skipif(not EVIDENCIA.exists(), reason="sin la evidencia del backtest")
def test_evidencia_observada_incluye_ocupacion_y_rupturas():
    """ALT-002 con la ocupación observada y el detector de rupturas (RF-009) están en la evidencia publicada, con su
    tasa de falsas alarmas sin cambio y su potencia frente a cambios inyectados."""
    publicado = json.loads(EVIDENCIA.read_text(encoding="utf-8"))
    por_codigo = publicado["por_defecto"]["por_codigo"]
    assert por_codigo["ALT-002"]["alertas"] > 0 and por_codigo["ALT-002"]["lift"] > 1.5
    assert "ALT-007 ruptura" in por_codigo
    det = publicado["detector_rupturas"]
    assert det["falsas_alarmas_sin_cambio"]["por_100_dias_ruta"] <= 2.0
    assert det["potencia_cambios_inyectados"]["-20%"]["tasa"] >= 0.9
