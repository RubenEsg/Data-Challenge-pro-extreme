"""El modelo de corto plazo que sirve la API (spec v1.5 §9.2, §9.3, RF-005): artefactos íntegros, el mismo código de
variables con que se entrenó, los mismos datos, y que reproduce la prueba reservada del experimento E14 en una muestra
fija de sus predicciones guardadas (datos/corto_plazo/muestra_prueba_e14.csv; la comparación completa, 168.210
predicciones, está en docs/evidencias/modelo/corto_plazo_reproduccion.md). Usa la copia temporal de datos/."""
from __future__ import annotations

import hashlib
import json
import shutil
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

pytestmark = pytest.mark.datos_ml
TOLERANCIA = 0.006           # la prueba guardó sus predicciones redondeadas a dos decimales
BOGOTA = ZoneInfo("America/Bogota")


@pytest.fixture(scope="module")
def cp(datos_copia):
    from app.servicios import corto_plazo

    corto_plazo.limpiar_cache()
    yield corto_plazo
    corto_plazo.limpiar_cache()


@pytest.fixture(scope="module")
def manifiesto(cp) -> dict:
    activo = cp.modelo_activo()
    return json.loads((cp.carpeta_modelos() / activo / cp.ARCHIVO_MANIFIESTO).read_text(encoding="utf-8"))


def _sha256(ruta: Path) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def test_artefactos_integros_registro_y_codigo_del_entrenamiento(cp, manifiesto):
    from app.servicios import variables_corto_plazo as V

    reg = cp.registro()
    assert reg["activo"] == cp.MODEL_ID_E14 and reg["historial_activacion"][-1]["a"] == cp.MODEL_ID_E14
    assert manifiesto["feature_version"] == V.VERSION_VARIABLES and manifiesto["semilla"] == V.SEMILLA
    assert manifiesto["data_cutoff"] == "2025-06-30" and manifiesto["estructura"]["sentido"] == "suma_de_segmentos"
    assert len(manifiesto["artefactos"]) == 18
    for a in manifiesto["artefactos"].values():
        assert _sha256(cp.carpeta_modelos() / manifiesto["model_id"] / a["archivo"]) == a["sha256"]
    huellas = cp.huellas_codigo()
    assert manifiesto["huella_codigo"]["variables_corto_plazo.py_sin_docstring"] == \
        huellas["variables_corto_plazo.py_sin_docstring"], \
        ("variables_corto_plazo.py cambió desde el entrenamiento: corra scripts/verificar_corto_plazo.py (debe seguir "
         "reproduciendo la prueba) y scripts/entrenar_corto_plazo.py --solo-registrar")
    modelo = cp.cargar()
    assert modelo["model_id"] == cp.MODEL_ID_E14 and len(modelo["arboles"]) == 18


def test_los_datos_son_los_del_entrenamiento(cp, manifiesto):
    for nombre, sha in manifiesto["version_datos"].items():
        assert _sha256(cp.carpeta_datos() / nombre) == sha, nombre


def test_reproduce_la_muestra_de_la_prueba_reservada(cp):
    from app.servicios import variables_corto_plazo as V

    m = pd.read_csv(cp.carpeta_datos() / "muestra_prueba_e14.csv")
    assert len(m) == 120 and set(m["nivel"]) == {"ruta", "sentido"}
    for fila in m.itertuples():
        with cp.sin_calidad():      # la prueba se midió con los datos tal cual, sin la regla VAL-009
            dia = cp._dia(cp.MODEL_ID_E14, cp.idruta_de(fila.ruta), cp.dia_de_fecha(date.fromisoformat(fila.fecha)),
                          int(fila.horizonte_min))
        j = int(np.flatnonzero(V.INSTANTES == fila.instante)[0])
        g = 0 if fila.nivel == "ruta" else ["ida", "regreso"].index(fila.sentido)
        n = dia[fila.nivel]
        assert n["y"][j, g] == pytest.approx(fila.real, abs=TOLERANCIA)
        for col, clave in (("pronostico", "p"), ("p10", "p10"), ("p90", "p90")):
            assert float(n[clave][j, g]) == pytest.approx(getattr(fila, col), abs=TOLERANCIA), (fila, col)
        assert float(n["base"]["promedio_dia_hora"][j, g]) == pytest.approx(fila.promedio_dia_hora, abs=TOLERANCIA)


def test_el_pronostico_de_un_instante(cp):
    r = cp.pronosticar("CRA 54", datetime(2025, 7, 7, 7, 10, tzinfo=BOGOTA), 60)
    assert r["instante"].startswith("2025-07-07T07:00") and r["ventana"]["hasta"].startswith("2025-07-07T08:00")
    assert r["p10"] <= r["pasajeros"] <= r["p90"] and r["dia_con_datos"] and not r["en_muestra"]
    assert r["real"] is not None and r["promedio_dia_hora"] is not None and r["franja"] == "06-08 pico"
    assert len(r["segmentos"]) == 123 and [s["sentido"] for s in r["sentidos"]] == ["ida", "regreso"]
    for s in r["sentidos"]:     # cada sentido es la suma de sus segmentos
        suma = sum(x["pasajeros"] for x in r["segmentos"] if x["sentido"] == s["sentido"])
        assert s["pasajeros"] == pytest.approx(suma, abs=0.1 * len(r["segmentos"]))
    exp = r["explicacion"]
    assert len(exp["factores"]) == 5 and exp["valor_base"] > 0
    assert {"variable", "factor", "sentido"} <= set(exp["factores"][0])
    # la explicación es exacta: la base por el producto de todos los factores da el pronóstico (TreeSHAP)
    modelo = cp.cargar()
    dia = cp._dia(cp.MODEL_ID_E14, 16, cp.dia_de_fecha(date(2025, 7, 7)), 60)
    x = dia["ruta"]["x"][6, 0]
    contrib = modelo["arboles"]["ruta_h60_r16"].predict(x[None, :], pred_contrib=True)[0]
    assert float(np.exp(contrib.sum())) == pytest.approx(float(dia["ruta"]["p"][6, 0]), rel=1e-4)
    assert r["observado"]["ultimos_15_min"] is not None and r["latencia_ms"] >= 0
    sin = cp.pronosticar("CRA 54", datetime(2025, 7, 7, 7, tzinfo=BOGOTA), 60, incluir_segmentos=False)
    assert "segmentos" not in sin and sin["pasajeros"] == r["pasajeros"]


def test_la_regla_de_calidad_excluye_los_dos_registros_imposibles(cp):
    """RF-004 y §6.3 (VAL-009): con el tope de 1.000 subidas por segmento y bloque de 15 minutos solo caen los dos
    registros imposibles de la base (los dos en CRA 54) y el pronóstico ya no los usa; sin la regla, el de la prueba
    reservada."""
    excluidas = [c for idr in (2, 16, 21) for c in cp.serie_completa(idr).excluidas]
    assert [(c["idruta"], c["fecha"], c["subidas"]) for c in excluidas] == [
        (16, "2024-05-26", 97157.0), (16, "2025-07-05", 28782.0)]
    instante = datetime(2025, 7, 5, 8, tzinfo=BOGOTA)
    con = cp.pronosticar("CRA 54", instante, 30, incluir_segmentos=False)
    with cp.sin_calidad():
        sin = cp.pronosticar("CRA 54", instante, 30, incluir_segmentos=False)
    assert sin["observado"]["ultimos_15_min"] > 28_000 > 1_000 > con["observado"]["ultimos_15_min"]
    assert abs(con["pasajeros"] - con["real"]) < abs(sin["pasajeros"] - sin["real"])
    assert con["calidad"]["regla"] == "VAL-009" and con["calidad"]["celdas_excluidas"][0]["nro_segmento"] == 4
    assert sin["calidad"] is None


def test_la_marca_de_agua_oculta_lo_no_leido(cp):
    """En el ciclo, lo que la ejecución todavía no leyó del día no existe: a las 04:00 con la marca del día anterior
    el pronóstico es el mismo (antes de las 04:00 no sube nadie), pero lo real de la ventana no se muestra."""
    instante = datetime(2025, 10, 15, 4, tzinfo=BOGOTA)
    leido = cp.pronosticar("CRA 54", instante, 60, incluir_segmentos=False,
                           hasta=datetime(2025, 10, 14, 23, 59, 59, tzinfo=BOGOTA))
    todo = cp.pronosticar("CRA 54", instante, 60, incluir_segmentos=False)
    assert leido["pasajeros"] == todo["pasajeros"] and leido["real"] is None and todo["real"] is not None
    assert leido["datos_hasta"].startswith("2025-10-14T23:59:59")
    assert cp.bloques_leidos(date(2025, 10, 15), datetime(2025, 10, 15, 9, 14, tzinfo=BOGOTA)) == 36
    assert cp.bloques_leidos(date(2025, 10, 15), datetime(2025, 10, 15, 9, 15, tzinfo=BOGOTA)) == 37


def test_la_importancia_global(cp):
    imp = cp.importancia_global(cp.cargar())["por_nivel"]
    assert set(imp) == {"ruta", "segmento"} and set(imp["ruta"]) == {"30", "60", "120"}
    ruta60 = imp["ruta"]["60"]
    assert sum(x["ganancia"] for x in ruta60) == pytest.approx(1.0, abs=0.01)
    assert ruta60[0]["variable"] == "p15" and ruta60[0]["descripcion"].startswith("lo que subió")


def test_la_curva_del_dia_y_la_cobertura(cp):
    d = cp.pronosticar_dia("SILENCIO", date(2025, 10, 15), 30)
    assert len(d["instantes"]) == 35 and d["instantes"][0]["instante"].startswith("2025-10-15T04:00")
    assert d["instantes"][-1]["instante"].startswith("2025-10-15T21:00") and not d["en_muestra"]
    cob = cp.cobertura()
    assert cob["desde"] == date(2023, 2, 26) and cob["hasta"] == date(2025, 12, 31)
    assert cob["fuera_de_muestra_desde"] == date(2025, 7, 1)
    with pytest.raises(cp.FueraDeCobertura):
        cp.pronosticar("SILENCIO", datetime(2023, 1, 20, 8, tzinfo=BOGOTA), 60)      # sin 8 semanas de historia
    with pytest.raises(cp.FueraDeCobertura):
        cp.pronosticar("SILENCIO", datetime(2026, 1, 5, 8, tzinfo=BOGOTA), 60)       # después del panel
    assert cp.pronosticar("SILENCIO", datetime(2024, 5, 8, 8, tzinfo=BOGOTA), 60)["en_muestra"]


def test_un_artefacto_alterado_no_se_usa(cp, tmp_path, monkeypatch):
    destino = tmp_path / "modelos"
    shutil.copytree(cp.carpeta_modelos(), destino / "corto_plazo")
    archivo = next((destino / "corto_plazo" / cp.MODEL_ID_E14).glob("ruta_h60_*.txt.gz"))
    contenido = bytearray(archivo.read_bytes())
    contenido[-5] ^= 0xFF
    archivo.write_bytes(bytes(contenido))
    monkeypatch.setenv("MODELOS_DIR", str(destino))
    with pytest.raises(cp.ErrorCortoPlazo, match="SHA-256"):
        cp.cargar()
    man = destino / "corto_plazo" / cp.MODEL_ID_E14 / cp.ARCHIVO_MANIFIESTO
    datos_man = json.loads(man.read_text(encoding="utf-8"))
    man.write_text(json.dumps(dict(datos_man, feature_version="otra")), encoding="utf-8")
    with pytest.raises(cp.ErrorCortoPlazo, match="variables"):
        cp.cargar()


def test_ninguna_variable_mira_el_futuro_con_la_serie_real(cp):
    """Lo mismo que pronostico_corto_plazo/comprobar_fuga.py, en un día de la prueba: alterar lo que pasa desde las
    10:00 no cambia nada de lo que el modelo ve hasta las 10:00."""
    from app.servicios import variables_corto_plazo as V

    r = cp.serie(21)
    d = cp.dia_de_fecha(date(2025, 9, 10))
    base = r.recorte(d - V.ARRANQUE, d)
    y2, sal2 = base.y.copy(), base.sal.copy()
    y2[-1, 40:] *= 3
    sal2[-1, 40:] += 5
    alterada = V.Ruta(base.idruta, base.nombre, y2, sal2, base.seg, base.cal, base.ok)
    for nivel in ("ruta", "segmento"):
        a = V.variables(base, nivel, 120, "completo")
        b = V.variables(alterada, nivel, 120, "completo")
        mira = (a["dia"] < V.ARRANQUE) | (a["instante"] <= 40)
        assert np.array_equal(a["x"][mira], b["x"][mira], equal_nan=True), nivel


def test_el_modelo_en_onnx_da_lo_mismo_que_lightgbm(cp, monkeypatch):
    """§9.1 y §9.2: la exportación a ONNX de los 18 artefactos está íntegra (SHA-256 de manifest_onnx.json) y, con
    MOTOR_INFERENCIA=onnx, el pronóstico de un día entero (ruta, sentidos y segmentos) es el de LightGBM en la
    precisión de float32."""
    activo = cp.modelo_activo()
    man = json.loads((cp.carpeta_modelos() / activo / cp.CARPETA_ONNX / cp.ARCHIVO_ONNX).read_text(encoding="utf-8"))
    assert man["paridad"] and len(man["artefactos"]) == 18
    for a in man["artefactos"].values():
        assert _sha256(cp.carpeta_modelos() / activo / cp.CARPETA_ONNX / a["archivo"]) == a["sha256"]
    with cp.sin_calidad():
        lgb = cp._dia(activo, 21, cp.dia_de_fecha(date(2025, 9, 17)), 120)
        monkeypatch.setenv("MOTOR_INFERENCIA", "onnx")
        cp.limpiar_cache()
        try:
            assert cp.cargar()["motor"] == "onnx"
            onx = cp._dia(activo, 21, cp.dia_de_fecha(date(2025, 9, 17)), 120)
        finally:
            monkeypatch.delenv("MOTOR_INFERENCIA")
            cp.limpiar_cache()
    for nivel in ("ruta", "sentido", "segmento"):
        np.testing.assert_allclose(onx[nivel]["p"], lgb[nivel]["p"], rtol=1e-5, atol=1e-4)
        np.testing.assert_allclose(onx[nivel]["p90"], lgb[nivel]["p90"], rtol=1e-5, atol=1e-4)
