"""Modelo por segmento y sentido (§9.1, §9.2, §9.3; protocolo docs/evidencias/modelo/segmentos_protocolo.md).

1. La partición es cronológica y sin solape, la misma en el código, en el manifiesto y en la evidencia.
2. Sin fuga: las variables de la validación y la prueba (fracción B0 y subidas de su celda) solo dependen del
   entrenamiento; alterar las subidas posteriores al corte no las cambia (y alterar el entrenamiento sí: la prueba es
   sensible). Las filas de entrenamiento usan la fracción B0 fuera de pliegue.
3. El artefacto activo pasa la verificación (SHA-256, versión de variables, huella del código) y el registro tiene la
   línea base B0.
4. Reentrenar con el entrenamiento reproduce las métricas de validación registradas; el activo supera a B0 en la
   prueba y su banda tiene la cobertura medida en la prueba cerca del 80 %.
Usan la copia temporal de datos/ (DATA_DIR y MODELOS_DIR) del conftest.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

pytestmark = pytest.mark.datos_ml

RAIZ = Path(__file__).resolve().parents[2]
EVIDENCIA = RAIZ / "docs" / "evidencias" / "modelo" / "segmentos_modelo.json"


@pytest.fixture(scope="module")
def ms(datos_copia):
    from app.servicios import modelo_segmentos

    modelo_segmentos.limpiar_cache()
    yield modelo_segmentos
    modelo_segmentos.limpiar_cache()


@pytest.fixture(scope="module")
def es(datos_copia):
    from scripts import entrenar_segmentos

    return entrenar_segmentos


@pytest.fixture(scope="module")
def celdas(es):
    return es.cargar_celdas()


@pytest.fixture(scope="module")
def registro_seg(ms) -> dict:
    return ms.registro()


@pytest.fixture(scope="module")
def manifiestos(ms, registro_seg) -> dict:
    return {mid: json.loads((ms.carpeta() / mid / ms.ARCHIVO_MANIFIESTO).read_text(encoding="utf-8"))
            for mid in registro_seg["modelos"]}


def test_particion_cronologica_sin_solape_y_la_misma_en_todas_partes(ms, celdas, manifiestos):
    p = ms.PARTICION
    assert p["entrenamiento"][0] <= p["entrenamiento"][1] < p["validacion"][0] <= p["validacion"][1] \
        < p["prueba"][0] <= p["prueba"][1]
    assert p["entrenamiento"][0] == min(celdas["fecha"]) and p["prueba"][1] == max(celdas["fecha"])
    texto = {k: f"{a} a {b}" for k, (a, b) in p.items()}
    assert all(m["particion_evaluacion"] == texto for m in manifiestos.values())
    assert json.loads(EVIDENCIA.read_text(encoding="utf-8"))["particion"] == texto


def _filas_eval(es, celdas, ventana: str) -> pd.DataFrame:
    from app.servicios import modelo_segmentos as ms

    segs = es.segmentos_de(celdas)
    cal = ms.calendario_serie(min(celdas["fecha"]), max(celdas["fecha"]))
    return es.preparar_evaluacion(es.ventana(celdas, "entrenamiento"), es.ventana(celdas, ventana), segs, cal)


@pytest.mark.parametrize("ventana", ["validacion", "prueba"])
def test_variables_fuera_de_muestra_no_usan_datos_posteriores_al_corte(es, ms, celdas, ventana):
    """§9.3 «ninguna variable usa información posterior»: la fracción B0 de la validación y la prueba sale solo del
    entrenamiento."""
    corte = ms.PARTICION["entrenamiento"][1]
    rng = np.random.default_rng(7)
    futuro = celdas.copy()
    despues = futuro["fecha"] > corte
    futuro.loc[despues, "subidas"] = rng.integers(0, 50, int(despues.sum())).astype(float)
    base, alterada = _filas_eval(es, celdas, ventana), _filas_eval(es, futuro, ventana)
    claves = [*ms.CLAVES_HORA, "id_segmento"]
    columnas = [c for c in ms.COLUMNAS if c not in claves]
    a = base.set_index(claves).sort_index()[columnas]
    b = alterada.set_index(claves).reindex(a.index)[columnas]
    pd.testing.assert_frame_equal(a, b)
    pasado = celdas.copy()
    pasado.loc[pasado["fecha"] <= corte, "subidas"] *= np.where(pasado.loc[pasado["fecha"] <= corte,
                                                                           "nro_segmento"] == 1, 3.0, 1.0)
    c = _filas_eval(es, pasado, ventana).set_index(claves).reindex(a.index)
    assert not np.allclose(a["log_fraccion_base"], c["log_fraccion_base"]), "la prueba no es sensible"


def test_filas_de_entrenamiento_usan_la_fraccion_b0_fuera_de_pliegue(es, ms, celdas):
    """La fracción B0 de una fila de entrenamiento no depende de las subidas de su propio pliegue de 7 días."""
    from app.servicios import modelo_segmentos

    segs = es.segmentos_de(celdas)
    cal = modelo_segmentos.calendario_serie(min(celdas["fecha"]), max(celdas["fecha"]))
    ent = es.ventana(celdas, "entrenamiento")
    inicio = ms.PARTICION["entrenamiento"][0]
    pl = ms.pliegues(ent["fecha"], inicio)
    otra = ent.copy()
    otra.loc[pl == 2, "subidas"] = otra.loc[pl == 2, "subidas"] * 4 + 1
    claves = [*ms.CLAVES_HORA, "id_segmento"]
    a = es.preparar_ajuste(ent, segs, cal, inicio).set_index(claves).sort_index()
    b = es.preparar_ajuste(otra, segs, cal, inicio).set_index(claves).reindex(a.index)
    en_2 = (a["pliegue"] == 2).to_numpy()
    assert en_2.any() and np.allclose(a.loc[en_2, "fraccion_base"], b.loc[en_2, "fraccion_base"])
    assert not np.allclose(a.loc[~en_2, "fraccion_base"], b.loc[~en_2, "fraccion_base"])


def test_artefacto_activo_integro_y_registro_con_linea_base(ms, registro_seg, manifiestos):
    from app.servicios import inferencia

    activo = registro_seg["activo"]
    assert activo in registro_seg["modelos"] and registro_seg["historial_activacion"][-1]["a"] == activo
    tipos = {m["tipo"]: k for k, m in registro_seg["modelos"].items()}
    assert ms.TIPO_REPARTO in tipos and registro_seg["modelos"][tipos[ms.TIPO_REPARTO]]["estado"] in (
        "linea_base", "activo")
    for mid, man in manifiestos.items():
        assert ms._sha256(ms.carpeta() / mid / man["artefacto"]) == man["sha256"] == registro_seg["modelos"][mid][
            "sha256"]
        assert man["feature_version"] == ms.VERSION_VARIABLES and man["variables"] == ms.COLUMNAS
        assert man["semilla"] == ms.SEMILLA and man["version_datos"]["sha256"]
    texto = Path(ms.__file__).read_text(encoding="utf-8")
    huella = inferencia.sha256_codigo(inferencia.sin_docstring_de_modulo(texto))
    assert manifiestos[activo]["codigo_sha256"]["modelo_segmentos.py_sin_docstring"] == huella, \
        "modelo_segmentos.py cambió desde el entrenamiento: vuelva a correr scripts/entrenar_segmentos.py"
    modelo = ms.cargar()
    assert modelo["model_id"] == activo and modelo["sha256"] == manifiestos[activo]["sha256"]


def test_reentrenar_reproduce_la_validacion_registrada(es, ms, celdas, registro_seg, manifiestos):
    """§9.3 «registrar semilla, versión de datos, hiperparámetros y código»: con los mismos datos y semilla, el tipo
    activo ajustado con el entrenamiento da en la validación las métricas que quedaron en su manifiesto."""
    man = manifiestos[registro_seg["activo"]]
    assert man["version_datos"]["sha256"] == es.huella(ms.datos.carpeta_datos() / es.ARCHIVO_CELDAS)
    segs = es.segmentos_de(celdas)
    cal = ms.calendario_serie(min(celdas["fecha"]), max(celdas["fecha"]))
    ent = es.ventana(celdas, "entrenamiento")
    x_ent = es.preparar_ajuste(ent, segs, cal, ms.PARTICION["entrenamiento"][0])
    x_val = es.preparar_evaluacion(ent, es.ventana(celdas, "validacion"), segs, cal)
    modelo = {"tipo": man["tipo"], **ms.ajustar(man["tipo"], x_ent)}
    m = es.metricas(x_val, ms.fracciones_previstas(modelo, x_val))
    for k in ("wape_segmento_hora", "wape_sentido_hora", "mae_segmento_hora"):     # holgura: otra plataforma de CI
        assert m[k] == pytest.approx(man["metricas_validacion"][k], abs=0.05), k


def test_activo_supera_al_reparto_fijo_y_su_banda_cubre_cerca_del_80(registro_seg, manifiestos, ms):
    activo = manifiestos[registro_seg["activo"]]
    b0 = next(m for m in manifiestos.values() if m["tipo"] == ms.TIPO_REPARTO)
    if activo["tipo"] != ms.TIPO_REPARTO:
        assert activo["metricas_prueba"]["wape_segmento_hora"] < b0["metricas_prueba"]["wape_segmento_hora"]
        assert activo["metricas_validacion"]["wape_segmento_hora"] < b0["metricas_validacion"]["wape_segmento_hora"]
        assert activo["metricas_prueba"]["wape_sentido_hora"] <= b0["metricas_prueba"]["wape_sentido_hora"] + 0.25
    banda = activo["banda"]
    assert 70 <= banda["cobertura_prueba_pct"] <= 90 and 70 <= banda["cobertura_prueba_sentido_pct"] <= 95
    assert 70 <= banda["cobertura_compuesta_ruta_activa_pct"] <= 90


def test_sesgo_por_condicion_y_su_composicion_con_la_ruta(es):
    """§9.3 «sesgo por … sentido, segmento y condición operacional»: el análisis separa franja, tipo de día y Carnaval,
    por sentido y por segmento, y compone con el sesgo de la ruta como (1 + r) · (1 + f) − 1."""
    x = pd.DataFrame({"ruta": "SILENCIO", "fecha": date(2023, 2, 22), "hora": 7, "tipo_dia": 0, "carnaval": 0,
                      "sentido": ["ida", "regreso"], "id_segmento": [1, 2], "nro_segmento": [1, 2],
                      "y": [100.0, 100.0], "total": [200.0, 200.0]})
    out = es.sesgo_por_condicion(x, np.array([0.55, 0.45]), "total")
    assert set(out) == {"franja=06-08 pico", "tipo_dia=laboral", "carnaval=sin_carnaval"}
    franja = out["franja=06-08 pico"]
    assert franja["por_sentido"]["ida"]["sesgo_pct"] == 10.0 and franja["por_sentido"]["regreso"]["sesgo_pct"] == -10.0
    assert franja["segmentos"]["sesgo_abs_mediano_pct"] == 10.0 and franja["sesgo_pct"] == 0.0
    comp = es.componer(out, {"sesgo_pct": {"franja=06-08 pico": 5.0, "tipo_dia=sabado": 1.0}})
    assert set(comp) == {"franja=06-08 pico"}
    assert comp["franja=06-08 pico"]["ida"]["sesgo_compuesto_pct"] == pytest.approx(15.5)
    assert comp["franja=06-08 pico"]["regreso"]["sesgo_compuesto_pct"] == pytest.approx(-5.5)


def test_evidencia_trae_el_sesgo_por_sentido_segmento_y_condicion():
    ev = json.loads(EVIDENCIA.read_text(encoding="utf-8"))
    activo = ev["activacion"]["activo_candidato"]
    cond = ev["prueba"][activo]["sesgo_por_condicion"]
    assert {"franja=06-08 pico", "franja=17-19 pico", "tipo_dia=laboral", "tipo_dia=sabado",
            "tipo_dia=domingo_festivo", "carnaval=carnaval", "carnaval=sin_carnaval"} <= set(cond)
    assert all(set(v["por_sentido"]) == {"ida", "regreso"} and v["segmentos"]["segmentos"] > 0
               for v in cond.values())
    assert set(ev["prueba"][activo]["sesgo_por_condicion_b2"]) == set(cond)
    comp = ev["prueba"][activo]["sesgo_compuesto_con_ruta_2025"]
    assert {"franja=06-08 pico", "tipo_dia=sabado"} <= set(comp) and "carnaval=carnaval" not in comp
    assert ev["prueba"]["sesgo_ruta_2025"]["model_id"].startswith("hgb_")


def test_ventanas_de_varias_horas_suman_solo_horas_consecutivas_completas(datos_copia):
    """La banda de la API se aplica a ventanas que cruzan 2 o 3 horas: la agregación de la evidencia suma y, μ y el
    total de horas consecutivas, y descarta las ventanas a las que les falta una hora."""
    from app.servicios import modelo_segmentos as ms
    from scripts import evaluar_banda_ventanas_segmentos as bv

    a, b = date(2023, 2, 20), date(2023, 2, 21)
    x = pd.DataFrame({"ruta": "SILENCIO", "fecha": [a] * 6 + [b] * 4, "hora": [6, 6, 7, 7, 8, 8, 6, 6, 8, 8],
                      "id_segmento": [1, 2] * 5, "sentido": ["ida", "regreso"] * 5,
                      "y": [3.0, 7, 4, 6, 5, 15, 1, 1, 2, 2], "total": [10.0, 10, 10, 10, 20, 20, 2, 2, 4, 4]})
    v = bv.ventanas(x, np.full(len(x), 0.5), 2)
    assert set(v["fecha"]) == {a} and sorted(set(v["h0"])) == [6, 7]       # el 21 no tiene la hora 7
    primera = v[(v["h0"] == 6) & (v["id_segmento"] == 1)].iloc[0]
    assert (primera["y"], primera["mu"], primera["total"]) == (7.0, 10.0, 20.0)
    banda = ms.calibrar_banda(np.arange(60, dtype=float), np.full(60, 30.0))
    cov = bv.cobertura_ventanas(v, {"segmento": banda, "sentido": banda})
    assert cov["segmento"]["n"] == 4 and cov["sentido"]["n"] == 4


def test_evidencia_de_la_banda_en_ventanas_de_varias_horas(registro_seg):
    """§3.1 «por franja horaria»: la cobertura de la banda en ventanas de 1 hora es la de segmentos_modelo.json y la de
    2 y 3 horas está medida (con los modelos del entrenamiento y la banda de la validación)."""
    ev = json.loads((EVIDENCIA.parent / "segmentos_banda_ventanas.json").read_text(encoding="utf-8"))
    modelo = json.loads(EVIDENCIA.read_text(encoding="utf-8"))
    act = ev["activo_candidato"]
    assert ev["activo"] == registro_seg["activo"] and ev["bandas_iguales_a_segmentos_modelo"]
    for nivel in ("segmento", "sentido"):
        assert ev["cobertura"][act]["1h"][nivel]["cobertura_pct"] == \
            modelo["prueba"][act]["banda_total_real"][nivel]["cobertura_pct"]
        for h in ("2h", "3h"):
            medida = ev["cobertura"][act][h][nivel]
            assert medida["n"] > 0 and 70 <= medida["cobertura_pct"] <= 90
    m = modelo["prueba"]["metricas"]
    ic = ev["ic95_prueba_wape_segmento_hora_vs_B0"]
    assert ic["diferencia_pp"] == pytest.approx(m[act]["wape_segmento_hora"] - m["B0"]["wape_segmento_hora"], abs=0.01)
    assert ic["ic95_pp"][0] <= ic["diferencia_pp"] <= ic["ic95_pp"][1]


def test_evidencia_coincide_con_el_registro(registro_seg):
    ev = json.loads(EVIDENCIA.read_text(encoding="utf-8"))
    assert ev["activacion"]["activo"] == registro_seg["activo"]
    assert {p["model_id"]: p["sha256"] for p in ev["produccion"]} == {
        k: m["sha256"] for k, m in registro_seg["modelos"].items()}
    assert ev["validacion"]["eleccion"]["elegido"] in ev["validacion"]["metricas"]
    assert ev["prueba"]["composicion_con_ruta_activa"]["replicas"] >= 10
    assert date.fromisoformat(ev["particion"]["prueba"].split(" a ")[1]) == date(2023, 2, 27)
