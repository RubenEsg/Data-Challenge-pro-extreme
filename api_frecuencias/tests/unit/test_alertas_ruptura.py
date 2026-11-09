"""ALT-002 con la ocupación OBSERVADA de cada hora cerrada (§5.2 «ocupación esperada u observada») y la ruptura de
comportamiento de RF-009 (CUSUM sobre los residuos diarios real - pronóstico)."""
from datetime import date, datetime, timedelta

import pytest

from app.servicios import alertas as A

DIA = date(2025, 10, 16)          # jueves laboral


def hora(h, pasajeros, salidas, esperado=None, nueva=True, programadas=None, **extra):
    inicio = datetime.combine(DIA, datetime.min.time().replace(hour=h), tzinfo=A.ZONA)
    x = A.contexto_hora(inicio, pasajeros, esperado, None, None, salidas, programadas, None, nueva=nueva)
    x.update(extra)
    return x


def ctx(horas, **extra):
    c = {"ruta": "CRA 54", "empresa": "SOBUSA", "detectada_en": datetime(2025, 10, 16, 21, tzinfo=A.ZONA),
         "capacidad": 50, "factor_carga_por_hora": {h: 0.45 for h in range(4, 21)}, "horas": horas}
    c.update(extra)
    return c


def de_codigo(alertas, codigo):
    return [a for a in alertas if a["codigo"] == codigo]


# ---------------------------------------------------------------- ALT-002 observada
def test_ocupacion_observada_de_una_hora():
    h = hora(7, 1_200, 10)
    assert A.ocupacion_observada_hora(h, 0.45, 50, 2) == pytest.approx(0.45 * 1_200 / (10 * 50))
    assert A.ocupacion_observada_hora(hora(7, 1_200, 1), 0.45, 50, 2) is None        # menos de 2 salidas
    assert A.ocupacion_observada_hora(hora(4, 300, 3), 0.45, 50, 2) is None          # hora de borde (4 h)
    assert A.ocupacion_observada_hora(hora(7, None, 10), 0.45, 50, 2) is None
    assert A.ocupacion_observada_hora(hora(7, 1_200, 10), None, 50, 2) is None


def test_alt002_observada_en_produccion_con_origen_observado():
    # 7 h: 0,45 × 1.200 / (10 × 50) = 108 %; 8 h: 0,45 × 1.050 / 500 = 94,5 %; 9 h: 54 % (2 h seguidas ≥ 90 %)
    horas = [hora(6, 500, 10), hora(7, 1_200, 10, esperado=900, programadas=12), hora(8, 1_050, 10),
             hora(9, 600, 10)]
    al = de_codigo(A.evaluar_observadas(ctx(horas)), "ALT-002")
    assert len(al) == 1
    a = al[0]
    assert a["origen"] == "observado" and a["severidad"] == "critica" and a["horizonte_min"] == 0
    assert a["observado"] == pytest.approx(1.08)                   # la peor hora del episodio
    assert a["esperado"] == pytest.approx(0.45 * 900 / (12 * 50))  # el pronóstico con la oferta programada
    assert a["variables"]["tipo_ocupacion"] == "observada"
    assert a["variables"]["ocupacion_observada"] == pytest.approx(1.08)
    assert a["variables"]["persistencia_horas"] == 2
    assert "factor de carga 0,450 × 1.200 pasajeros ÷ (10 salidas × 50 puestos)" in a["explicacion"]
    assert a["ventana_inicio"].hour == 7 and a["ventana_fin"].hour == 9
    assert a["clave_dedup"] == A.clave_episodio("ALT-002", "CRA 54", a["ventana_inicio"])


def test_alt002_observada_una_hora_aislada_no_basta():
    # persistencia de 2 h (backtest: 1,61 -> 0,69 alertas por ruta y día con el mismo lift)
    assert de_codigo(A.evaluar_observadas(ctx([hora(7, 1_200, 10), hora(8, 600, 10)])), "ALT-002") == []
    assert de_codigo(A.evaluar_observadas(ctx([hora(7, 1_200, 10)]), {"persistencia_ocupacion_horas": 1}),
                     "ALT-002")


def test_alt002_observada_agrupa_horas_seguidas_en_un_episodio():
    al = de_codigo(A.evaluar_observadas(ctx([hora(7, 1_100, 10), hora(8, 1_050, 10), hora(9, 300, 10)])), "ALT-002")
    assert len(al) == 1
    assert al[0]["variables"]["horas_episodio"] == 2
    assert al[0]["observado"] == pytest.approx(0.99)                # la peor hora del episodio


def test_alt002_observada_no_repite_episodios_viejos():
    al = A.evaluar_observadas(ctx([hora(7, 1_200, 10, nueva=False), hora(8, 1_200, 10, nueva=False)]))
    assert de_codigo(al, "ALT-002") == []


def test_alt002_observada_bajo_el_umbral_o_sin_salidas_suficientes():
    assert de_codigo(A.evaluar_observadas(ctx([hora(7, 990, 10), hora(8, 990, 10)])), "ALT-002") == []  # 89,1 %
    assert de_codigo(A.evaluar_observadas(ctx([hora(7, 1_200, 1), hora(8, 1_200, 1)])), "ALT-002") == []


def test_alt002_observada_toma_el_factor_del_optimizador_si_el_contexto_no_lo_trae():
    from app.servicios import optimizacion

    fc = optimizacion.factor_carga_franja("CRA 54", DIA, 7)
    fc8 = optimizacion.factor_carga_franja("CRA 54", DIA, 8)
    assert fc is not None and fc8 is not None
    pasajeros = 1.0 * 10 * 50 / fc["factor_carga"] * 1.05          # 105 % con el factor de la franja
    c = ctx([hora(7, pasajeros, 10), hora(8, 10 * 50 / fc8["factor_carga"], 10)])
    del c["factor_carga_por_hora"]
    a = de_codigo(A.evaluar_observadas(c), "ALT-002")[0]
    assert a["observado"] == pytest.approx(1.05, abs=1e-3)
    assert "mediana 2025" in a["variables"]["fuente_factor_carga"]


def test_alt002_observada_usa_la_capacidad_del_catalogo_si_falta():
    c = ctx([hora(7, 1_200, 10), hora(8, 1_200, 10)])
    del c["capacidad"]
    a = de_codigo(A.evaluar_observadas(c), "ALT-002")[0]
    assert a["variables"]["fuente_capacidad"]


# ---------------------------------------------------------------- RF-009: CUSUM
def _ruido(i):
    """Ruido determinista en [-0,03, 0,03] (sin azar: la prueba es reproducible)."""
    return ((i * 37) % 13 - 6) / 200.0


def serie(dias, cambio_desde=None, cambio=0.0, inicio=date(2025, 9, 1), nuevas_desde=None):
    out = []
    for i in range(dias):
        esp = 10_000.0
        r = _ruido(i) + (cambio if cambio_desde is not None and i >= cambio_desde else 0.0)
        f = inicio + timedelta(days=i)
        out.append({"fecha": f, "observado": esp * (1 + r), "esperado": esp,
                    "nueva": nuevas_desde is None or i >= nuevas_desde})
    return out


def test_cusum_no_detecta_en_una_serie_estable():
    assert A.detectar_rupturas(serie(90))["detecciones"] == []


def test_cusum_detecta_una_caida_sostenida_y_estima_el_inicio():
    r = A.detectar_rupturas(serie(70, cambio_desde=45, cambio=-0.15))
    assert len(r["detecciones"]) >= 1
    d = r["detecciones"][0]
    assert d["lado"] == -1
    assert date(2025, 9, 1) + timedelta(days=44) <= d["fecha_inicio"] <= date(2025, 9, 1) + timedelta(days=47)
    assert d["fecha_deteccion"] <= date(2025, 9, 1) + timedelta(days=50)          # a lo sumo 5 días de retardo
    assert -0.20 < d["cambio_medio"] < -0.05
    assert r["referencia"]["dias"] == A.UMBRALES_POR_DEFECTO["ruptura_dias_referencia"]
    # el cambio se sostiene 25 días: es UNA ruptura, no una alerta cada pocos días
    assert len(r["detecciones"]) == 1


def test_cusum_detecta_un_alza_sostenida():
    d = A.detectar_rupturas(serie(70, cambio_desde=40, cambio=0.12))["detecciones"][0]
    assert d["lado"] == 1 and d["cambio_medio"] > 0.05


def test_cusum_sin_dias_suficientes_no_evalua():
    assert A.detectar_rupturas(serie(20)) == {"referencia": None, "detecciones": []}


def test_cusum_ignora_un_cambio_menor_que_el_minimo():
    assert A.detectar_rupturas(serie(90, cambio_desde=40, cambio=-0.03))["detecciones"] == []


def test_ruptura_genera_alt007_variante_con_su_metodo():
    s = serie(70, cambio_desde=45, cambio=-0.15, nuevas_desde=45)     # la detección cae en un día nuevo
    al = de_codigo(A.evaluar_observadas({"ruta": "CL 72", "serie_diaria": s}), "ALT-007")
    assert len(al) == 1
    a = al[0]
    assert a["variables"]["variante"] == "ruptura_comportamiento"
    assert a["variables"]["sentido_desviacion"] == "-"
    assert "CUSUM" in a["metodo_puntaje"] and "k" in a["metodo_puntaje"]
    assert a["origen"] == "observado" and a["severidad"] == "preventiva"
    assert "Ruptura de comportamiento" in a["explicacion"] and "por debajo" in a["explicacion"]
    assert a["variables"]["h"] == A.UMBRALES_POR_DEFECTO["ruptura_h"]
    assert a["umbral"] == pytest.approx(a["esperado"] - A.UMBRALES_POR_DEFECTO["ruptura_cambio_minimo"], abs=1e-4)
    assert a["observado"] < a["umbral"]                       # mismas unidades: residuo relativo
    assert a["clave_dedup"].startswith("ALT-007|CL 72|") and a["clave_dedup"].endswith("|ruptura")
    assert 0.5 <= a["puntaje"] <= 1.0


def test_ruptura_vieja_no_se_vuelve_a_alertar():
    s = serie(70, cambio_desde=45, cambio=-0.15, nuevas_desde=69)       # solo el último día es nuevo
    det = A.detectar_rupturas(s)["detecciones"][-1]
    assert det["fecha_deteccion"] < s[-1]["fecha"]
    assert de_codigo(A.evaluar_observadas({"ruta": "CL 72", "serie_diaria": s}), "ALT-007") == []


def test_serie_diaria_ruta_arma_real_y_pronostico_por_dia_completo(monkeypatch):
    """La serie del ciclo: días completos de demanda_observada con el pronóstico en lote (predecir_horas)."""
    from app.servicios import datos, inferencia

    horas = list(datos.HORAS_SERVICIO)
    dias = [date(2025, 10, 1) + timedelta(days=i) for i in range(3)]
    filas = [(d, h, 100.0) for d in dias for h in horas if not (d == dias[1] and h == 9)]   # el día 2 está incompleto

    class Sesion:
        def execute(self, _consulta):
            class R:
                def all(self_inner):
                    return filas
            return R()

    llamadas = []

    def predecir_horas(ruta, inicios, model_id=None, **kw):
        llamadas.append((ruta, len(inicios), kw.get("horizonte_min")))
        return [{"pasajeros": 90.0} for _ in inicios]

    monkeypatch.setattr(inferencia, "predecir_horas", predecir_horas)
    s = A.serie_diaria_ruta(Sesion(), "CL 72", dias[-1], "hgb_x", nuevas={dias[-1]})
    assert [x["fecha"] for x in s] == [dias[0], dias[2]]
    assert s[0]["observado"] == 100.0 * len(horas) and s[0]["esperado"] == 90.0 * len(horas)
    assert [x["nueva"] for x in s] == [False, True]
    assert llamadas == [("CL 72", 2 * len(horas), 60)]                  # un solo lote


def test_serie_diaria_ruta_sin_base_devuelve_vacio():
    assert A.serie_diaria_ruta(None, "CL 72", date(2025, 10, 1)) == []


def test_alt002_observada_se_explica_con_lo_observado_aunque_la_esperada_sea_mayor():
    # pronóstico con la oferta programada: 0,45 × 1.400 / (10 × 50) = 126 %; observada 0,45 × 1.100 / 500 = 99 %
    horas = [hora(7, 1_100, 10, esperado=1_400, programadas=10), hora(8, 1_100, 10, esperado=1_400, programadas=10)]
    a = de_codigo(A.evaluar_observadas(ctx(horas)), "ALT-002")[0]
    assert a["variables"]["tipo_ocupacion"] == "observada"
    assert a["explicacion"].startswith("La ocupación observada (99,0 %)")
    assert a["observado"] == pytest.approx(0.99) and a["esperado"] == pytest.approx(1.26)
