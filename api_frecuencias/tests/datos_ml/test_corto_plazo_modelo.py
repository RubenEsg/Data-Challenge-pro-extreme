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
