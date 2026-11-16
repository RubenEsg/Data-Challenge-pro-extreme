"""No regresión del modelo activo (§14.1 «Datos/ML»; §14.2 «el modelo supera la línea base en la métrica principal»;
§9 métricas; E05 «artefacto versionado, entrenamiento reproducible y métricas»).

El artefacto versionado del modelo activo se vuelve a evaluar sobre la prueba RESERVADA de su manifiesto (fechas
posteriores a la validación, que nunca se usaron para entrenar) y debe reproducir el informe que dejó
scripts/evaluar_modelo.py (clave «evaluacion» del manifiesto) dentro de la tolerancia, seguir por debajo de la línea
base B1 (regla manual de Sobusa) y conservar la cobertura de la banda. La prueba es un reporte informativo: se consultó
al comparar fv2 con fv1 (docs/evidencias/modelo/decision_fv2.md); entrenar() y la compuerta ya no la miden.
"""
from __future__ import annotations

import hashlib
from datetime import date

import pytest

pytestmark = pytest.mark.datos_ml

TOLERANCIA_WAPE_PP = 0.5      # puntos porcentuales de WAPE frente al manifiesto
TOLERANCIA_COBERTURA_PP = 2.0


def _prueba(manifiesto: dict) -> tuple[date, date]:
    desde, hasta = (x.strip() for x in manifiesto["particion"]["prueba"].split(" a "))
    return date.fromisoformat(desde), date.fromisoformat(hasta)


def _informe_prueba(manifiesto: dict) -> dict:
    """Métricas del modelo en la prueba reservada según scripts/evaluar_modelo.py (n, mae, wape y cobertura)."""
    ev = manifiesto["evaluacion"]["prueba_reservada"]
    return dict(ev["global"]["cand"], cobertura_p10_p90=ev["cobertura"]["cand"]["banda_modelo"]["cobertura_pct"])


def test_artefacto_integro_sha256(datos_copia, registro, manifiesto_activo):
    activo = registro["activo"]
    artefacto = datos_copia / "modelos" / activo / manifiesto_activo["artefacto"]
    assert hashlib.sha256(artefacto.read_bytes()).hexdigest() == manifiesto_activo["sha256"]
    assert registro["modelos"][activo]["sha256"] == manifiesto_activo["sha256"]
    assert registro["modelos"][activo]["estado"] == "activo"


def test_wape_en_la_prueba_reservada_dentro_de_tolerancia(manifiesto_activo):
    from app.servicios import inferencia

    desde, hasta = _prueba(manifiesto_activo)
    esperado = _informe_prueba(manifiesto_activo)
    m = inferencia.evaluar(manifiesto_activo["model_id"], desde, hasta)
    assert m["fuera_de_muestra"] is True and m["n"] == esperado["n"]
    assert abs(m["wape"] - esperado["wape"]) <= TOLERANCIA_WAPE_PP, (m["wape"], esperado["wape"])
    assert abs(m["mae"] - esperado["mae"]) <= 0.05 * esperado["mae"], (m["mae"], esperado["mae"])


def test_supera_a_las_lineas_base_en_la_prueba_reservada(manifiesto_activo):
    from app.servicios import inferencia

    desde, hasta = _prueba(manifiesto_activo)
    modelo = inferencia.evaluar(manifiesto_activo["model_id"], desde, hasta)
    for linea_base in ("b1_manual_8sem", "b2_ultima_semana"):
        base = inferencia.evaluar(linea_base, desde, hasta)
        assert base["n"] == modelo["n"]
        assert modelo["wape"] < base["wape"], f"no supera a {linea_base}: {modelo['wape']} vs {base['wape']}"
    assert manifiesto_activo["supera_linea_base_validacion"] is True


def test_cobertura_de_la_banda_p10_p90_estable(manifiesto_activo):
    from app.servicios import inferencia

    desde, hasta = _prueba(manifiesto_activo)
    esperado = _informe_prueba(manifiesto_activo).get("cobertura_p10_p90")
    if esperado is None:
        pytest.skip("el manifiesto no registra la cobertura de la banda")
    m = inferencia.evaluar(manifiesto_activo["model_id"], desde, hasta)
    assert abs(m["cobertura_p10_p90"] - esperado) <= TOLERANCIA_COBERTURA_PP
    assert 60 <= m["cobertura_p10_p90"] <= 95, "una banda P10-P90 debe cubrir cerca del 80 %"


def test_calibracion_versionada_reproduce_su_evidencia(manifiesto_activo):
    """La banda calibrada que usa la API (v2, calibracion_v2.json) reproduce en la prueba reservada la cobertura que
    registró scripts/calibrar_por_grupo.py; la calibración no cambia el pronóstico (mismo WAPE)."""
    from app.servicios import inferencia

    cal = manifiesto_activo.get("calibracion")
    if not cal:
        pytest.skip("el modelo activo no tiene calibración versionada")
    desde, hasta = _prueba(manifiesto_activo)
    m = inferencia.evaluar(manifiesto_activo["model_id"], desde, hasta)
    registrada = cal["resumen"]["prueba_reservada_solo_reporte"]
    assert m["calibracion_version"] == cal["version"]
    assert abs(m["cobertura_p10_p90_conformal"] - registrada[cal["version"]]["cobertura_pct"]) <= 0.1
    assert abs(m["cobertura_p10_p90_conformal_v1"] - registrada["v1"]["cobertura_pct"]) <= 0.1
    assert m["wape"] == pytest.approx(_informe_prueba(manifiesto_activo)["wape"], abs=0.005)
    assert 60 <= m["cobertura_p10_p90_conformal"] <= 95


def test_el_entrenamiento_del_activo_no_guarda_metricas_de_la_prueba(manifiesto_activo):
    """La sección de entrenamiento solo trae la validación; la historia de la prueba reservada queda declarada."""
    assert set(manifiesto_activo["metricas"]) == {"validacion"} and "prueba" not in manifiesto_activo["nowcast"]
    assert "informativo" in manifiesto_activo["historial_prueba_reservada"]
    assert "estado" not in manifiesto_activo


def test_validacion_no_empeora_entre_versiones_registradas(registro):
    """Ningún modelo activado tiene peor WAPE de validación que los candidatos ANTERIORES a él de la misma fecha de
    corte. Un candidato posterior y mejor (fv3, registrado en sombra) no lo incumple: su activación es de la
    gobernanza."""
    activo = registro["modelos"][registro["activo"]]
    mismos = [m for m in registro["modelos"].values() if m.get("tipo") == "candidato"
              and m.get("data_cutoff") == activo.get("data_cutoff") and m.get("wape_validacion") is not None
              and str(m.get("creado_en", "")) <= str(activo.get("creado_en", ""))]
    assert activo["wape_validacion"] <= min(m["wape_validacion"] for m in mismos) + 1e-9
