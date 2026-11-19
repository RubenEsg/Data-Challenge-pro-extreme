"""Pronóstico de corto plazo (RF-005, §9.1-§9.3): variables sin fuga, el corte de un día, el instante, la banda, el
registro, el guardado de un pronóstico y su recomendación. Con datos sintéticos, sin base de datos."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

from app.servicios import corto_plazo as cp
from app.servicios import variables_corto_plazo as V

BOGOTA = ZoneInfo("America/Bogota")


def _ruta_sintetica(dias: int = 70, segmentos: int = 6, semilla: int = 1) -> V.Ruta:
    rng = np.random.default_rng(semilla)
    y = rng.poisson(3.0, size=(dias, V.BLOQUES, segmentos)).astype(np.float32)
    y[:, :16] = 0                                         # sin servicio de madrugada
    sal = rng.poisson(2.0, size=(dias, V.BLOQUES)).astype(np.float32)
    seg = pd.DataFrame({"nro_segmento": np.arange(1, segmentos + 1),
                        "sentido": ["ida"] * (segmentos // 2) + ["regreso"] * (segmentos - segmentos // 2),
                        "minutos_desde_inicio": np.linspace(0, 60, segmentos), "km_inicio": np.arange(segmentos) * 0.5})
    fechas = pd.date_range(V.DIA0, periods=dias, freq="D")
    cal = pd.DataFrame({"fecha": fechas, **{c: 0 for c in V.CALENDARIO}})
    cal["dia_semana"], cal["mes"], cal["dia_mes"] = fechas.dayofweek, fechas.month, fechas.day
    ok = V.dias_con_datos(y.sum(axis=(1, 2)))
    return V.Ruta(2, "SILENCIO", y, sal, seg, cal, ok)


@pytest.mark.parametrize("nivel", ["ruta", "sentido", "segmento"])
def test_ninguna_variable_usa_lo_que_pasa_despues_del_instante(nivel):
    """§9.3 «ninguna variable usa información posterior al instante de predicción»: se altera todo lo que pasa desde
    el bloque t del día d (y los días siguientes) y las variables y líneas base de los instantes <= t no cambian."""
    r = _ruta_sintetica()
    d, bloque = 65, 40                                    # 10:00 del día 65
    antes = V.variables(r, nivel, 60, "completo")
    y2, sal2 = r.y.copy(), r.sal.copy()
    y2[d, bloque:] += 50
    y2[d + 1:] += 50
    sal2[d, bloque:] += 9
    sal2[d + 1:] += 9
    alterada = V.Ruta(r.idruta, r.nombre, y2, sal2, r.seg, r.cal, r.ok)
    despues = V.variables(alterada, nivel, 60, "completo")
    mira = (antes["dia"] < d) | ((antes["dia"] == d) & (antes["instante"] <= bloque))
    assert np.array_equal(antes["x"][mira], despues["x"][mira], equal_nan=True)
    for k in antes["base"]:
        assert np.array_equal(antes["base"][k][mira], despues["base"][k][mira], equal_nan=True)
    # y el futuro sí cambia el objetivo de ese instante (la prueba altera algo que importa)
    j = (antes["dia"] == d) & (antes["instante"] == bloque)
    assert not np.array_equal(antes["y"][j], despues["y"][j])


@pytest.mark.parametrize("nivel", ["ruta", "segmento"])
def test_un_dia_con_sus_56_dias_anteriores_da_lo_mismo_que_la_serie_entera(nivel):
    r = _ruta_sintetica()
    d = 66
    entera = V.variables(r, nivel, 30, "completo")
    corte = V.variables(r.recorte(d - V.ARRANQUE, d), nivel, 30, "completo")
    n = len(V.INSTANTES) * entera["forma"][2]
    assert entera["nombres"] == corte["nombres"]
    assert np.array_equal(entera["x"][d * n:(d + 1) * n], corte["x"][-n:], equal_nan=True)


def test_variables_por_nivel_y_su_orden():
    r = _ruta_sintetica()
    ruta = V.variables(r, "ruta", 60, "completo")
    seg = V.variables(r, "segmento", 60, "completo")
    assert ruta["nombres"][:5] == ["l7", "l14", "m4", "m8", "sd8"] and ruta["nombres"][-1] == "instante"
    assert {"p15", "hoy", "rhoy", "sal60"} <= set(ruta["nombres"]) and len(ruta["nombres"]) == 32
    assert {"R_p30", "sal_llegan", "arriba30", "vec_m4", "nro_segmento"} <= set(seg["nombres"])
    assert len(seg["nombres"]) == 49
    assert V.variables(r, "ruta", 60, "semanal")["nombres"][:5] == ruta["nombres"][:5]
    with pytest.raises(ValueError):
        V.variables(r, "ruta", 60, "otro")


def test_dias_sin_datos_y_franjas():
    total = np.array([100.0] * 60 + [2.0] + [100.0] * 5)
    ok = V.dias_con_datos(total)
    assert not ok[60] and ok[59] and ok[61]
    assert V.franja_de(28) == "06-08 pico" and V.franja_de(40) == "09-16 valle" and V.franja_de(90) is None


def test_banda_conformal_rodea_el_pronostico():
    cal = {"cortes": [10.0, 100.0], "q": {"0": [-1.5, 1.2], "1": [-1.0, 1.0], "2": [-0.8, 0.9]}}
    p = np.array([0.0, 5.0, 50.0, 500.0])
    lo, hi = V.conformal_aplicar(p, cal)
    assert (lo <= p).all() and (p <= hi).all() and (lo >= 0).all()
    assert hi[3] == pytest.approx(500 + 0.9 * np.sqrt(501))


def test_metricas():
    m = V.metricas(np.array([10.0, 20.0]), np.array([12.0, 18.0]))
    assert m["wape"] == pytest.approx(4 / 30 * 100, abs=1e-3) and m["sesgo_pct"] == 0.0 and m["n"] == 2
    assert V.metricas(np.array([0.0]), np.array([1.0])) == {"n": 1}


def test_instante_se_lleva_a_la_media_hora_de_bogota():
    f, b, usado = cp.instante_local(datetime(2025, 7, 7, 7, 10, tzinfo=BOGOTA))
    assert (f, b, usado.strftime("%H:%M")) == (date(2025, 7, 7), 28, "07:00")
    f, b, usado = cp.instante_local(datetime(2025, 7, 7, 12, 45, tzinfo=ZoneInfo("UTC")))   # 07:45 en Bogotá
    assert (b, usado.strftime("%H:%M")) == (30, "07:30")
    _f, b, _u = cp.instante_local(datetime(2025, 7, 7, 21, 20))                              # sin zona: Bogotá
    assert b == 84
    for fuera in (datetime(2025, 7, 7, 3, 59, tzinfo=BOGOTA), datetime(2025, 7, 7, 21, 30, tzinfo=BOGOTA)):
        with pytest.raises(cp.FueraDeCobertura):
            cp.instante_local(fuera)


def test_ruta_por_nombre_o_idruta():
    assert cp.idruta_de("CRA 54") == 16 and cp.idruta_de("21") == 21 and cp.idruta_de(2) == 2
    with pytest.raises(cp.FueraDeCobertura):
        cp.idruta_de("RUTA X")
    assert cp.clave_artefacto("segmento", 120, 16) == "segmento_h120_r16"


def test_registro_propio_con_historial(tmp_path, monkeypatch):
    monkeypatch.setenv("MODELOS_DIR", str(tmp_path))
    assert cp.registro() == {"activo": None, "modelos": {}, "historial_activacion": []} and cp.modelo_activo() is None
    with pytest.raises(cp.ErrorCortoPlazo):
        cp.cargar()
    man = {"model_id": "cp_prueba", "tipo": cp.TIPO, "feature_version": V.VERSION_VARIABLES}
    reg = cp.registrar(man, activar=True, motivo="prueba")
    assert reg["activo"] == "cp_prueba" and reg["modelos"]["cp_prueba"]["estado"] == "activo"
    reg = cp.registrar(dict(man, model_id="cp_otro"), activar=False, motivo="candidato")
    assert reg["modelos"]["cp_otro"]["estado"] == "candidato" and len(reg["historial_activacion"]) == 1
    with pytest.raises(cp.ModeloCortoPlazoNoEncontrado):
        cp.cargar("no_existe")
    with pytest.raises(cp.ModeloCortoPlazoNoEncontrado):      # registrado, sin manifiesto
        cp.cargar("cp_otro")
    huellas = cp.huellas_codigo()
    assert set(huellas) == {"variables_corto_plazo.py", "variables_corto_plazo.py_sin_docstring", "corto_plazo.py",
                            "corto_plazo.py_sin_docstring"}


def test_horizonte_fuera_de_30_60_120():
    with pytest.raises(cp.FueraDeCobertura):
        cp.pronosticar("CRA 54", datetime(2025, 7, 7, 7, tzinfo=BOGOTA), 45)
    with pytest.raises(cp.FueraDeCobertura):
        cp.pronosticar_dia("CRA 54", date(2025, 7, 7), 90)


class _Sesion:
    def __init__(self):
        self.filas = []

    def add(self, fila):
        self.filas.append(fila)


def _pronostico() -> dict:
    celda = {"pasajeros": 120.0, "p10": 100.0, "p90": 140.0, "promedio_dia_hora": 110.0, "ultima_semana": 115.0,
             "real": 118.0}
    return {"ruta": "CRA 54", "idruta": 16, "instante": "2025-07-07T07:00:00-05:00", "horizonte_min": 60,
            "ventana": {"desde": "2025-07-07T07:00:00-05:00", "hasta": "2025-07-07T08:00:00-05:00"},
            "franja": "06-08 pico", "model_id": "cp_prueba", "feature_version": V.VERSION_VARIABLES,
            "data_cutoff": "2025-06-30", "en_muestra": False, "dia_con_datos": True, "generated_at":
            "2025-11-18T10:00:00-05:00", "latencia_ms": 12.0, **celda,
            "sentidos": [dict(celda, sentido="ida"), dict(celda, sentido="regreso")],
            "segmentos": [dict(celda, nro_segmento=k, sentido="ida", km_inicio=0.5 * k) for k in (1, 2, 3)],
            "observado": {"ultimos_15_min": 30.0}, "explicacion": {"factores": []}, "recomendacion": {"buses_hora": 6}}


def test_guardar_escribe_la_ruta_sus_sentidos_y_sus_segmentos():
    s = _Sesion()
    grupo = cp.guardar(s, _pronostico(), execution_id=None)
    assert isinstance(grupo, uuid.UUID) and len(s.filas) == 1 + 2 + 3
    assert [f.nivel for f in s.filas] == ["ruta", "sentido", "sentido", "segmento", "segmento", "segmento"]
    assert {f.grupo_id for f in s.filas} == {grupo} and len({f.prediction_id for f in s.filas}) == 6
    ruta = s.filas[0]
    assert ruta.sentido is None and ruta.nro_segmento is None and ruta.recomendacion == {"buses_hora": 6}
    assert ruta.fecha == date(2025, 7, 7) and ruta.objetivo.hour == 8 and ruta.data_cutoff == date(2025, 6, 30)
    assert ruta.variables["observado"] == {"ultimos_15_min": 30.0}
    assert s.filas[3].nro_segmento == 1 and s.filas[3].sentido == "ida" and s.filas[1].sentido == "ida"


def test_recomendacion_lleva_la_ventana_a_ritmo_por_hora(monkeypatch):
    from app.servicios import ejecucion, ocupacion

    pedidos = {}

    def recomendar(info, franja, umbrales, version, reactiva):
        pedidos.update(franja)
        return {"buses_hora": 7, "headway_min": 8.6, "vehiculos_requeridos": 9, "viable": True,
                "fecha": date(2025, 7, 7)}, {}

    monkeypatch.setattr(ejecucion, "umbrales_vigentes", lambda s: (3, {"ocupacion_critica": 0.9}))
    monkeypatch.setattr(ocupacion, "reactiva_guardada", lambda *a, **k: None)
    monkeypatch.setattr(ejecucion, "recomendacion_con_ocupacion", recomendar)
    r = dict(_pronostico(), horizonte_min=30, pasajeros=300.0, p10=250.0, p90=360.0,
             instante="2025-07-07T07:40:00-05:00")
    rec = cp.recomendacion(object(), r, {"ruta": "CRA 54"})
    assert pedidos["demanda_hora"] == 600.0 and pedidos["p90_hora"] == 720.0 and pedidos["p10_hora"] == 500.0
    assert pedidos["hora"] == 7 and rec["hora"] == 7 and rec["umbrales_version"] == 3     # punto medio 07:55
    assert rec["buses_hora"] == 7 and rec["viable"] is True and "ritmo por hora" in rec["fuente"]
    r = dict(r, instante="2025-07-07T21:00:00-05:00", horizonte_min=120)                   # punto medio 22:00
    assert cp.recomendacion(object(), r, {"ruta": "CRA 54"})["hora"] == 20                   # última hora de servicio
