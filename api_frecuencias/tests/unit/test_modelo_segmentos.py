"""Modelo por segmento y sentido (app/servicios/modelo_segmentos.py; §3.1, §9.1, §9.2, §9.3, §7.3 paso 4).

Reparto fijo B0 con respaldo jerárquico (y que reproduce datos/reparto_segmentos.parquet), codificación fuera de
pliegue, malla con ceros, HGB Poisson con exposición, variantes jerárquicas, banda conformal de Mondrian y su
composición con la banda de la ruta, artefacto con SHA-256 y registro, desagregación de una ventana y filas de la foto.
No necesitan base de datos.
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from app.servicios import datos
from app.servicios import modelo_segmentos as ms

RUTA = "SILENCIO"
SEGMENTOS = pd.DataFrame({"ruta": RUTA, "id_segmento": [11, 12, 13, 14], "nro_segmento": [1, 2, 3, 4],
                          "sentido": ["ida", "ida", "regreso", "regreso"], "km_inicio": [0.0, 0.5, 1.0, 1.5],
                          "longitud_m": 500.0, "pos_rel": [0.125, 0.375, 0.625, 0.875]})
INICIO = date(2023, 1, 2)


def _calendario(dias: int, vacaciones_hasta: int | None = None) -> pd.DataFrame:
    fechas = [INICIO + timedelta(days=d) for d in range(dias)]
    vacaciones = [int(vacaciones_hasta is not None and d < vacaciones_hasta) for d in range(dias)]
    return pd.DataFrame({"fecha": fechas, "tipo_dia": [datos.tipo_dia_de(f) for f in fechas],
                         "dia_semana": [f.weekday() for f in fechas], "festivo": 0, "vacaciones": vacaciones,
                         "carnaval": 0})


def _celdas(dias: int = 28, horas=(6, 7), pesos=None, total: int = 400, semilla: int = 0,
            vacaciones_hasta: int | None = None) -> pd.DataFrame:
    """Subidas Poisson por segmento; con vacaciones_hasta, el primer segmento pesa más en vacaciones."""
    rng = np.random.default_rng(semilla)
    cal = _calendario(dias, vacaciones_hasta).set_index("fecha")
    filas = []
    for fecha, c in cal.iterrows():
        w = np.array(pesos or [0.4, 0.3, 0.2, 0.1], dtype=float)
        if c["vacaciones"]:
            w = np.array([0.55, 0.2, 0.15, 0.1])
        for h in horas:
            for seg, wi in zip(SEGMENTOS["id_segmento"], w / w.sum(), strict=True):
                filas.append({"ruta": RUTA, "fecha": fecha, "hora": h, "tipo_dia": int(c["tipo_dia"]),
                              "id_segmento": int(seg), "subidas": float(rng.poisson(total * wi))})
    return pd.DataFrame(filas)


def _matriz(celdas: pd.DataFrame, cal: pd.DataFrame, oof: bool) -> pd.DataFrame:
    m = ms.malla(celdas, SEGMENTOS).merge(cal.drop(columns="tipo_dia"), on="fecha", how="left")
    if not oof:
        return ms.matriz(m, ms.fracciones_base(celdas, SEGMENTOS))
    m["pliegue"] = ms.pliegues(m["fecha"], INICIO)
    return ms.matriz(m, ms.codificar_fuera_de_pliegue(celdas, SEGMENTOS, INICIO))


HIPER_PRUEBA = {"learning_rate": 0.1, "max_iter": 60, "max_leaf_nodes": 7, "min_samples_leaf": 10,
                "l2_regularization": 1.0}


# ------------------------------------------------------------------------------------------------ reparto fijo B0
def test_reparto_fijo_suma_uno_y_usa_el_respaldo_jerarquico():
    c = _celdas(dias=7, horas=(6, 7, 20))
    c.loc[c["hora"] == 20, "subidas"] = 1.0          # 4 subidas por hora 20 y día: celda fina con < MIN_SUBIDAS
    fb = ms.fracciones_base(c, SEGMENTOS)
    assert np.allclose(fb.groupby(ms.CLAVES_CELDA)["fraccion"].sum(), 1.0)
    laboral = fb[(fb["tipo_dia"] == 0)]
    assert set(laboral.loc[laboral["hora"] == 7, "nivel"]) == {"ruta_tipo_dia_hora"}
    assert set(laboral.loc[laboral["hora"] == 20, "nivel"]) == {"ruta_tipo_dia"}
    # una celda que no está en los datos (sábado a las 5) se codifica con el respaldo, sin huecos
    objetivo = pd.DataFrame({"ruta": [RUTA], "tipo_dia": [1], "hora": [5]})
    otra = ms.fracciones_base(c, SEGMENTOS, objetivo=objetivo)
    assert len(otra) == 4 and otra["fraccion"].sum() == pytest.approx(1.0) and otra["subidas_celda"].eq(0).all()
    assert set(otra["nivel"]) <= {"ruta_tipo_dia", "ruta"}


def test_reparto_fijo_sin_datos_reparte_por_igual():
    vacias = pd.DataFrame({"ruta": [RUTA] * 4, "tipo_dia": 0, "hora": 7, "id_segmento": SEGMENTOS["id_segmento"],
                           "subidas": 0.0})
    fb = ms.fracciones_base(vacias, SEGMENTOS)
    assert np.allclose(fb["fraccion"], 0.25)


def test_reparto_fijo_reproduce_el_reparto_empaquetado():
    """Las celdas versionadas (datos/subidas_segmento_hora.parquet) con la regla B0 dan exactamente
    datos/reparto_segmentos.parquet, el reparto que usaba la API (scripts/preparar_segmentos.py)."""
    celdas = pd.read_parquet(datos.carpeta_datos() / "subidas_segmento_hora.parquet")
    segs = celdas.drop_duplicates("id_segmento")[["ruta", "id_segmento"]]
    fb = ms.fracciones_base(celdas.astype({"subidas": float}), segs)
    r = pd.read_parquet(datos.carpeta_datos() / "reparto_segmentos.parquet")
    m = r.merge(fb, on=["ruta", "tipo_dia", "hora", "id_segmento"], suffixes=("_r", "_n"))
    assert len(m) == len(r) == len(fb)
    assert np.allclose(m["fraccion_r"], m["fraccion_n"], atol=1e-12)
    assert (m["nivel_r"] == m["nivel_n"]).all() and (m["subidas_celda_r"] == m["subidas_celda_n"]).all()


def test_codificacion_fuera_de_pliegue_no_mira_su_propio_pliegue():
    """§9.3 sin fuga: la fracción B0 de las filas de un pliegue no cambia si se alteran las subidas de ese pliegue
    (y sí cambia la de los otros pliegues: la prueba es sensible)."""
    c = _celdas(dias=21)
    pl = ms.pliegues(c["fecha"], INICIO)
    assert sorted(set(pl.tolist())) == [0, 1, 2]
    otra = c.copy()
    otra.loc[pl == 1, "subidas"] *= np.where(otra.loc[pl == 1, "id_segmento"] == 11, 5.0, 1.0)
    a = ms.codificar_fuera_de_pliegue(c, SEGMENTOS, INICIO).set_index(["pliegue", *ms.CLAVES_CELDA, "id_segmento"])
    b = ms.codificar_fuera_de_pliegue(otra, SEGMENTOS, INICIO).set_index(["pliegue", *ms.CLAVES_CELDA, "id_segmento"])
    pd.testing.assert_series_equal(a.loc[1, "fraccion"], b.loc[1, "fraccion"])
    assert not np.allclose(a.loc[0, "fraccion"], b.loc[0, "fraccion"])


def test_malla_cruza_todos_los_segmentos_con_ceros_y_el_total():
    c = _celdas(dias=2, horas=(7,))
    c = c[~((c["fecha"] == INICIO) & (c["id_segmento"] == 14))]      # el segmento 14 no aparece ese día
    m = ms.malla(c, SEGMENTOS)
    assert len(m) == 2 * 4
    fila = m[(m["fecha"] == INICIO) & (m["id_segmento"] == 14)].iloc[0]
    assert fila["y"] == 0.0
    assert np.allclose(m.groupby(["fecha"])["y"].sum(), m.groupby(["fecha"])["total"].first())


# ------------------------------------------------------------------------------------------------ modelos
@pytest.mark.parametrize("tipo", ms.TIPOS)
def test_cada_tipo_reparte_toda_la_hora(tipo):
    cal = _calendario(28)
    x = _matriz(_celdas(), cal, oof=True)
    modelo = {"tipo": tipo, **ms.ajustar(tipo, x, HIPER_PRUEBA)}
    assert (modelo["regresor"] is None) == (tipo == ms.TIPO_REPARTO)
    assert (modelo["regresor_sentido"] is not None) == (tipo == ms.TIPO_JERARQUICO)
    f = ms.fracciones_previstas(modelo, x)
    assert (f >= 0).all() and np.allclose(pd.Series(f).groupby([x["fecha"], x["hora"]]).sum(), 1.0)


def test_tipo_desconocido_falla():
    with pytest.raises(ValueError, match="desconocido"):
        ms.ajustar("lineal", pd.DataFrame())


def test_hgb_con_exposicion_aprende_lo_que_el_reparto_fijo_no_ve():
    """El reparto fijo mezcla vacaciones y clases; el HGB con offset log(T · B0) aprende la corrección por la
    variable vacaciones y queda más cerca de la fracción verdadera en los dos regímenes."""
    cal = _calendario(42, vacaciones_hasta=21)
    c = _celdas(dias=42, vacaciones_hasta=21, total=2000)
    x = _matriz(c, cal, oof=True)
    modelo = {"tipo": ms.TIPO_OFFSET_REPARTO, **ms.ajustar(ms.TIPO_OFFSET_REPARTO, x, HIPER_PRUEBA)}
    x_eval = _matriz(c, cal, oof=False)
    f = ms.fracciones_previstas(modelo, x_eval)
    verdad = np.where(x_eval["vacaciones"] == 1, 0.55, 0.40)
    primero = (x_eval["id_segmento"] == 11).to_numpy()
    err_modelo = np.abs(f[primero] - verdad[primero]).mean()
    err_b0 = np.abs(x_eval["fraccion_base"].to_numpy()[primero] - verdad[primero]).mean()
    assert err_modelo < 0.65 * err_b0       # B0 se equivoca 0,075 en cada régimen; el modelo, cerca de la mitad


def test_jerarquico_toma_el_sentido_de_su_modelo_y_reparte_dentro():
    cal = _calendario(28)
    x = _matriz(_celdas(), cal, oof=True)
    dentro = {"tipo": ms.TIPO_DENTRO_SENTIDO, **ms.ajustar(ms.TIPO_DENTRO_SENTIDO, x, HIPER_PRUEBA)}
    f = ms.fracciones_previstas(dentro, x)
    ida = (x["sentido"] == "ida").to_numpy()
    b0_ida = pd.Series(np.where(ida, x["fraccion_base"], 0.0)).groupby([x["fecha"], x["hora"]]).transform("sum")
    m_ida = pd.Series(np.where(ida, f, 0.0)).groupby([x["fecha"], x["hora"]]).transform("sum")
    assert np.allclose(m_ida, b0_ida)     # hgb_dentro_del_sentido conserva la fracción del sentido de B0
    t = ms.tabla_sentido(x, ms.CLAVES_HORA)
    assert len(t) == 2 * x.drop_duplicates(ms.CLAVES_HORA).shape[0] and {"y", "total"} <= set(t.columns)


# ------------------------------------------------------------------------------------------------ banda
def test_cuantiles_conformales_con_correccion_de_muestra_finita():
    s = np.arange(1, 101, dtype=float)
    assert ms.cuantiles_conformales(s) == (10.0, 91.0)      # ⌊101·0,1⌋ = 10 y ⌈101·0,9⌉ = 91
    assert ms.cuantiles_conformales([]) is None
    assert ms.cuantiles_conformales([3.0]) == (3.0, 3.0)


def test_banda_mondrian_usa_el_global_en_tramos_chicos():
    rng = np.random.default_rng(1)
    mu = np.concatenate([np.full(400, 2.0), np.full(10, 500.0)])
    y = rng.poisson(mu)
    b = ms.calibrar_banda(y, mu)
    assert b["tramos"]["1"]["propio"] and b["tramos"]["1"]["n"] == 400
    assert not b["tramos"]["5"]["propio"] and b["tramos"]["5"]["q_hi"] == b["global"]["q_hi"]
    lo, hi = ms.banda_compuesta(np.full(400, 1.0), mu[:400], mu[:400], mu[:400], b)
    assert 0.75 <= float(((y[:400] >= lo) & (y[:400] <= hi)).mean()) <= 0.95


def test_banda_compuesta_crece_con_la_banda_de_la_ruta_y_no_es_negativa():
    b = ms.calibrar_banda(np.array([0, 1, 2, 3, 4, 5] * 20, dtype=float), np.full(120, 2.5))
    f = np.array([0.01, 0.2])
    lo0, hi0 = ms.banda_compuesta(f, 100.0, 100.0, 100.0, b)           # total conocido: solo el reparto
    lo1, hi1 = ms.banda_compuesta(f, 100.0, 60.0, 150.0, b)            # con la banda de la ruta
    assert (lo1 <= lo0).all() and (hi1 >= hi0).all() and (lo1 >= 0).all()
    assert (lo0 <= f * 100).all() and (f * 100 <= hi0).all()
    lo2, hi2 = ms.banda_compuesta(f, 0.0, 0.0, 0.0, b)                 # fuera de servicio
    assert (lo2 == 0).all() and (hi2 == 0).all()


# ------------------------------------------------------------------------------------------------ artefacto y registro
def _guardar_pequeno(dm, tipo=ms.TIPO_REPARTO, activar=True, model_id="seg_prueba"):
    cal = _calendario(14)
    c = _celdas(dias=14)
    x = _matriz(c, cal, oof=True)
    cod = ms.fracciones_base(c, SEGMENTOS)
    banda = {"segmento": ms.calibrar_banda(x["y"], x["total"] * x["fraccion_base"]),
             "sentido": ms.calibrar_banda([100.0] * 60, [100.0] * 60)}
    contenido = {"tipo": tipo, **ms.ajustar(tipo, x, HIPER_PRUEBA), "codificacion": cod, "segmentos": SEGMENTOS,
                 "banda": banda}
    man = ms.guardar(contenido, {"model_id": model_id, "tipo": tipo, "periodo_datos": "2023-01-02 a 2023-01-15",
                                 "banda": {"metodo": ms.METODO_BANDA, "cobertura_prueba_pct": 80.0}}, dm)
    ms.registrar(man, activar=activar, motivo="prueba", dir_modelos=dm)
    return man


def test_guardar_registrar_y_cargar_verifica_sha256(tmp_path):
    ms.limpiar_cache()
    with pytest.raises(ms.ErrorModeloSegmentos, match="activo"):
        ms.cargar(dir_modelos=tmp_path)
    man = _guardar_pequeno(tmp_path)
    reg = ms.registro(tmp_path)
    assert reg["activo"] == "seg_prueba" and reg["modelos"]["seg_prueba"]["estado"] == "activo"
    assert reg["historial_activacion"][-1]["motivo"] == "prueba"
    modelo = ms.cargar(dir_modelos=tmp_path)
    assert modelo["sha256"] == man["sha256"] and modelo["tipo"] == ms.TIPO_REPARTO
    assert ms.cargar("seg_prueba", tmp_path) is modelo             # una sola carga (caché)
    assert ms.ficha(modelo)["cobertura_prueba_pct"] == 80.0
    with pytest.raises(ms.ModeloSegmentosNoEncontrado):
        ms.cargar("no_existe", tmp_path)
    ms.limpiar_cache()
    (tmp_path / "seg_prueba" / ms.ARCHIVO_ARTEFACTO).write_bytes(b"alterado")
    with pytest.raises(ms.ErrorModeloSegmentos, match="SHA-256"):
        ms.cargar(dir_modelos=tmp_path)


def test_cargar_rechaza_otra_version_de_variables_y_manifiesto_ausente(tmp_path):
    ms.limpiar_cache()
    _guardar_pequeno(tmp_path)
    ruta_man = tmp_path / "seg_prueba" / ms.ARCHIVO_MANIFIESTO
    man = json.loads(ruta_man.read_text(encoding="utf-8"))
    ruta_man.write_text(json.dumps(dict(man, feature_version="sv0")), encoding="utf-8")
    with pytest.raises(ms.ErrorModeloSegmentos, match="sv0"):
        ms.cargar(dir_modelos=tmp_path)
    ruta_man.unlink()
    with pytest.raises(ms.ModeloSegmentosNoEncontrado, match="manifiesto"):
        ms.cargar(dir_modelos=tmp_path)
    ms.limpiar_cache()


def test_registro_marca_linea_base_candidato_y_activo(tmp_path):
    ms.limpiar_cache()
    _guardar_pequeno(tmp_path, model_id="seg_b0", activar=False)
    _guardar_pequeno(tmp_path, tipo=ms.TIPO_OFFSET_TOTAL, model_id="seg_hgb", activar=False)
    reg = ms.registro(tmp_path)
    assert reg["activo"] is None and reg["modelos"]["seg_b0"]["estado"] == "linea_base"
    assert reg["modelos"]["seg_hgb"]["estado"] == "candidato"
    _guardar_pequeno(tmp_path, tipo=ms.TIPO_OFFSET_TOTAL, model_id="seg_hgb", activar=True)
    assert ms.modelo_activo(tmp_path) == "seg_hgb"
    ms.limpiar_cache()


# ------------------------------------------------------------------------------------------------ una ventana
def _tramos():
    return [(date(2025, 9, 16), 7, 300.0), (date(2025, 9, 16), 8, 100.0)]


def test_tramos_de_prediccion_normalizan_al_total_de_la_ventana():
    v = {"factor_nowcast": 1.1,
         "por_hora": [{"fecha": "2025-09-16", "hora": 7, "fraccion": 1.0, "pasajeros_hora": 600},
                      {"fecha": "2025-09-16", "hora": 8, "fraccion": 0.5, "pasajeros_hora": 400}]}
    t = ms.tramos_de_prediccion(v, 1000.0)
    assert t[0][0] == date(2025, 9, 16) and sum(x for _, _, x in t) == pytest.approx(1000.0)
    assert t[0][2] / t[1][2] == pytest.approx(3.0)
    assert ms.tramos_de_prediccion({}, 10.0) == []


def test_calendario_de_tabla_y_su_respaldo():
    tabla = pd.DataFrame({"ruta": [RUTA], "fecha": [date(2025, 9, 16)], "hora": [7], "tipo_dia": [0],
                          "dia_semana": [1], "festivo": [0], "vacaciones": [1], "carnaval": [0]}).set_index(
        ["ruta", "fecha", "hora"])
    assert ms.calendario_de_tabla(tabla, RUTA, date(2025, 9, 16), 7)["vacaciones"] == 1
    otro = ms.calendario_de_tabla(tabla, RUTA, date(2025, 9, 21), 7)          # domingo sin fila
    assert otro == {"tipo_dia": 2, "dia_semana": 6, "festivo": 0, "vacaciones": 0, "carnaval": 0}
    assert ms.calendario_de_tabla(None, RUTA, date(2025, 9, 20), 7)["tipo_dia"] == 1


@pytest.fixture(scope="module")
def activo():
    """El modelo de segmentos activo empaquetado en datos/modelos/segmentos (artefacto verificado)."""
    ms.limpiar_cache()
    return ms.cargar()


def test_modelo_empaquetado_reparte_la_ventana_y_suma_la_ruta(activo):
    def cal(f, h):
        return ms.calendario_de_tabla(None, "CRA 54", f, h)

    d = ms.desagregar_ventana(activo, "CRA 54", _tramos(), 400.0, 320.0, 480.0, cal)
    assert d["suma_segmentos"] == pytest.approx(400.0, abs=1e-6)
    assert len(d["segmentos"]) == 123 and {s["sentido"] for s in d["sentidos"]} == {"ida", "regreso"}
    assert sum(s["pasajeros"] for s in d["sentidos"]) == pytest.approx(400.0, abs=1e-2)
    assert sum(s["fraccion"] for s in d["segmentos"]) == pytest.approx(1.0, abs=1e-4)
    assert all(s["p10"] <= s["pasajeros"] <= s["p90"] for s in d["segmentos"] + d["sentidos"])
    angosta = ms.desagregar_ventana(activo, "CRA 54", _tramos(), 400.0, 400.0, 400.0, cal)
    assert sum(s["p90"] - s["p10"] for s in angosta["sentidos"]) < sum(s["p90"] - s["p10"] for s in d["sentidos"])
    assert "2023-01-01" in d["periodo_reparto"] and d["segmentos"][0]["nivel_reparto"].startswith("ruta")


def test_ventana_vacia_y_ruta_sin_segmentos(activo):
    def cal(f, h):
        return ms.calendario_de_tabla(None, "CL 72", f, h)

    assert ms.desagregar_ventana(activo, "CL 72", [], 0.0, None, None, cal)["segmentos"] == []
    with pytest.raises(ms.RutaSinSegmentos):
        ms.desagregar_ventana(activo, "NO EXISTE", _tramos(), 10.0, None, None, cal)


def test_filas_foto_por_segmento_con_sentido_y_segmento(activo):
    """§7.3 paso 4: una fila por segmento, con sentido y segmento llenos y las variables del modelo de segmentos."""
    pred = SimpleNamespace(ruta="SILENCIO", pasajeros=500.0, p10=400.0, p90=620.0, variables={
        "por_hora": [{"fecha": "2025-09-16", "hora": 7, "fraccion": 1.0, "pasajeros_hora": 500.0}]})
    filas = ms.filas_foto(pred, None, activo)
    assert len(filas) == 135 and all(f["sentido"] in ("ida", "regreso") and f["segmento"] for f in filas)
    assert {f["feature_version"] for f in filas} == {ms.VERSION_VARIABLES}
    assert {f["model_id"] for f in filas} == {activo["model_id"]}
    assert (filas[0]["fecha"], filas[0]["hora"]) == (date(2025, 9, 16), 7)
    assert set(filas[0]["features"]) == {"nro_segmento", "fraccion_base", "subidas_celda", "fraccion", "pasajeros",
                                         "p10", "p90"}
    assert sum(f["features"]["pasajeros"] for f in filas) == pytest.approx(500.0, abs=0.1)
    sin_horas = SimpleNamespace(ruta="SILENCIO", pasajeros=0.0, p10=None, p90=None, variables={})
    assert ms.filas_foto(sin_horas, None, activo) == []


# ------------------------------------------------------------------------------------------------ errores en la API
@pytest.mark.parametrize(("pedido", "error", "estado", "codigo"), [
    ("seg_x", ms.ModeloSegmentosNoEncontrado("Modelo de segmentos no registrado: seg_x"), 404, "modelo_no_encontrado"),
    (None, ms.ModeloSegmentosNoEncontrado("No existe el manifiesto del modelo de segmentos seg_activo"), 503,
     "reparto_no_disponible"),
    (None, json.JSONDecodeError("Expecting value", "{", 1), 503, "reparto_no_disponible"),
    (None, ms.ErrorModeloSegmentos("no coincide con el SHA-256"), 503, "reparto_no_disponible"),
])
def test_api_clasifica_los_errores_del_modelo_de_segmentos(monkeypatch, pedido, error, estado, codigo):
    """GET /predictions/segmentos: 404 solo si el cliente pidió un model_id que no está; que al activo le falte el
    manifiesto o que el registro no sea JSON válido es una degradación del servidor (503), no un 500 sin código."""
    from app.routers import pronostico_segmentos
    from app.routers.comun import ErrorApi

    def falla(*_a, **_k):
        raise error

    monkeypatch.setattr(ms, "cargar", falla)
    with pytest.raises(ErrorApi) as exc:
        pronostico_segmentos.modelo_de_segmentos(pedido)
    assert (exc.value.status, exc.value.codigo) == (estado, codigo)
