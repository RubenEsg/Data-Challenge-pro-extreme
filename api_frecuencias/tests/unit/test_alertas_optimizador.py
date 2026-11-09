"""Las alertas de pronóstico ALT-001..ALT-004 miden la ocupación igual que el optimizador (§5.1-§5.3, §9.4, §10.2).

Antes, ALT-001/002/004 comparaban los abordajes por hora con buses/h × 50 puestos, sin el factor de carga crítica que
usa el optimizador: SILENCIO a las 7 h salía «crítica, 164,6 %» mientras la recomendación de la misma franja decía
71,9 % y proponía bajar a 7 buses/h. Ahora la ocupación de la alerta es la de comparacion_actual del optimizador
(factor de carga × demanda / capacidad ofrecida) y ALT-003 sale del nivel de servicio, no del número de buses.
"""
from datetime import date

import pytest

from app.servicios import alertas as A

FECHA = date(2025, 10, 16)          # jueves laboral


def franja(demanda, p90, p10=None, hora=7, fecha=FECHA):
    return {"fecha": fecha, "hora": hora, "demanda_hora": demanda, "p90_hora": p90,
            "p10_hora": demanda * 0.9 if p10 is None else p10, "fuente": "variables.por_hora"}


def prediccion(pasajeros):
    return {"pasajeros": pasajeros, "p10": pasajeros * 0.9, "p90": pasajeros * 1.1, "model_id": "hgb_prueba"}


def rec_sintetica(*, factor, cap_ofrecida, ocupacion, cumple, carga_diseno, viable=True, buses=7, occ_obj=0.85):
    """La parte de la salida de optimizacion.recomendacion_franja que leen las alertas."""
    return {"buses_hora": buses, "viable": viable, "factor_carga": factor,
            "parametros": {"ocupacion_objetivo": occ_obj, "ocupacion_critica": 0.9},
            "demanda": {"factor_carga": factor, "carga_critica_diseno": carga_diseno},
            "contexto_franja": {"factor_carga": {"factor_carga": factor, "fuente": "mediana 2025 (prueba)"}},
            "comparacion_actual": {"actual": {"capacidad_ofrecida": cap_ofrecida, "ocupacion_esperada": ocupacion,
                                              "cumple_nivel_servicio": cumple}}}


def codigos(c):
    return {a["codigo"] for a in A.evaluar_alertas(c)}


def una(c, codigo):
    al = [a for a in A.evaluar_alertas(c) if a["codigo"] == codigo]
    assert len(al) == 1, f"{codigo} no se disparó"
    return al[0]


# ---------------------------------------------------------------- con el optimizador real (datos empaquetados)
def _recomendacion_real(ruta, demanda, p90, hora=7, fecha=FECHA):
    """recomendacion_franja con los umbrales por omisión (los de §5.1) y los parámetros empaquetados de la franja."""
    from app.servicios import datos, optimizacion

    info = {r["ruta"]: r for r in datos.catalogo_rutas()}[ruta]
    umbrales = {k: v for k, v in A.UMBRALES_POR_DEFECTO.items() if k != "version"}
    return optimizacion.recomendacion_franja(dict(info, ruta=ruta), umbrales, None, hora=hora, fecha=fecha,
                                             demanda_hora=demanda, demanda_p90=p90, demanda_p10=demanda * 0.9)


def test_silencio_7h_la_alerta_y_la_recomendacion_dicen_la_misma_ocupacion():
    """El caso de la verificación: SILENCIO 7 h, 669 pasajeros/h (P90 759). Sin el factor, la alerta decía 164,6 %;
    con él coincide con la ocupación que el optimizador calcula para la frecuencia actual y no hay ALT-001/ALT-002."""
    rec, ent = _recomendacion_real("SILENCIO", 669.0, 759.0)
    c = A.contexto_pronostico("SILENCIO", 60, franja(669.0, 759.0), prediccion(669.0), ent, rec)
    ocup_optimizador = rec["comparacion_actual"]["actual"]["ocupacion_esperada"]
    assert c["ocupacion_esperada"] == pytest.approx(ocup_optimizador)
    assert c["factor_carga"] == pytest.approx(rec["factor_carga"]) and 0.2 < c["factor_carga"] < 0.7
    assert ocup_optimizador < 0.9
    assert "ALT-001" not in codigos(c) and "ALT-002" not in codigos(c)
    # la lectura anterior (sin factor) sí la habría disparado: la contradicción era real
    sin_factor = {k: v for k, v in c.items() if k not in ("factor_carga", "ocupacion_esperada")}
    assert {"ALT-001", "ALT-002"} <= codigos(sin_factor)
    antes = una(sin_factor, "ALT-002")["esperado"]
    try:
        from tests.evidencia import guardar_evidencia
    except ImportError:            # sin el módulo compartido la prueba no escribe evidencia
        return
    actual = rec["comparacion_actual"]["actual"]
    guardar_evidencia("alertas/caso_silencio_7h.json", {
        "caso": "SILENCIO, 16/10/2025 (jueves laboral), 7 h: 669 pasajeros/h, P90 759",
        "frecuencia_programada_buses_h": actual["buses_hora"],
        "capacidad_ofrecida_puestos_h": actual["capacidad_ofrecida"],
        "factor_carga": rec["factor_carga"], "ocupacion_optimizador_frecuencia_actual": ocup_optimizador,
        "ocupacion_alerta_ahora": c["ocupacion_esperada"], "alertas_ahora": sorted(codigos(c)),
        "ocupacion_alerta_sin_factor": antes, "alertas_sin_factor": sorted(codigos(sin_factor)),
        "recomendacion_buses_h": rec["buses_hora"], "recomendacion_ocupacion": rec["ocupacion_esperada"],
        "prueba": "tests/unit/test_alertas_optimizador.py::test_silencio_7h_la_alerta_y_la_recomendacion_dicen_la_"
                  "misma_ocupacion"})


def test_alt002_esperada_coincide_con_la_ocupacion_del_optimizador_cuando_dispara():
    rec, ent = _recomendacion_real("SILENCIO", 2_400.0, 2_700.0)
    c = A.contexto_pronostico("SILENCIO", 60, franja(2_400.0, 2_700.0), prediccion(2_400.0), ent, rec)
    a = una(c, "ALT-002")
    assert a["esperado"] == pytest.approx(rec["comparacion_actual"]["actual"]["ocupacion_esperada"], abs=1e-4)
    assert a["observado"] is None and a["variables"]["tipo_ocupacion"] == "esperada"
    assert "factor de carga" in a["explicacion"] and "misma ocupación que calcula el optimizador" in a["explicacion"]


# ---------------------------------------------------------------- ALT-001 con la carga crítica
ENT = {"capacidad": 50, "frecuencia_actual_min": 7.38}          # 8,13 buses/h -> 406,5 puestos/h


@pytest.mark.parametrize("p90,dispara", [(991.0, False), (992.0, True)])   # 0,41 × 992 = 406,7 > 406,5
def test_alt001_frontera_con_el_factor_de_carga(p90, dispara):
    rec = rec_sintetica(factor=0.41, cap_ofrecida=406.5, ocupacion=0.41 * 669 / 406.5, cumple=True,
                        carga_diseno=0.41 * p90)
    c = A.contexto_pronostico("SILENCIO", 60, franja(669.0, p90), prediccion(669.0), ENT, rec)
    assert ("ALT-001" in codigos(c)) is dispara


def test_alt001_sin_valor_observado_y_la_proyeccion_en_esperado():
    rec = rec_sintetica(factor=0.41, cap_ofrecida=406.5, ocupacion=0.41 * 900 / 406.5, cumple=False,
                        carga_diseno=0.41 * 1_100)
    c = A.contexto_pronostico("SILENCIO", 60, franja(900.0, 1_100.0), prediccion(900.0), ENT, rec)
    a = una(c, "ALT-001")
    assert a["observado"] is None                               # es un pronóstico (§5.3)
    assert a["esperado"] == pytest.approx(0.41 * 1_100, abs=1e-3)
    assert a["umbral"] == pytest.approx(60 / 7.38 * 50, abs=1e-3)
    assert a["severidad"] == "preventiva"                       # 0,41 × 900 = 369 < 406,5: el puntual cabe
    v = a["variables"]
    assert v["carga_critica_proyectada"] == pytest.approx(451.0) and v["factor_carga"] == pytest.approx(0.41)
    assert v["valor_observado"].startswith("no aplica")
    assert "P90" in a["metodo_puntaje"] and "factor de carga" in a["metodo_puntaje"]
    assert "1.100,0 pasajeros/h × factor de carga 0,410 = 451,0 pasajeros/h" in a["explicacion"]


def test_alt001_critica_si_la_carga_del_puntual_supera_la_capacidad():
    rec = rec_sintetica(factor=0.41, cap_ofrecida=406.5, ocupacion=0.41 * 1_000 / 406.5, cumple=False,
                        carga_diseno=0.41 * 1_150)
    c = A.contexto_pronostico("SILENCIO", 60, franja(1_000.0, 1_150.0), prediccion(1_000.0), ENT, rec)
    assert una(c, "ALT-001")["severidad"] == "critica"           # 0,41 × 1.000 = 410 > 406,5


def test_alt004_usa_la_misma_ocupacion_con_factor():
    # 300 pasajeros/h × 0,41 / 406,5 = 30,3 % (sin factor serían 73,8 %): justo sobre el mínimo, sin alerta
    rec = rec_sintetica(factor=0.41, cap_ofrecida=406.5, ocupacion=0.41 * 300 / 406.5, cumple=True,
                        carga_diseno=0.41 * 330, buses=6)
    c = A.contexto_pronostico("SILENCIO", 60, franja(300.0, 330.0), prediccion(300.0), ENT, rec)
    assert "ALT-004" not in codigos(c)
    rec = rec_sintetica(factor=0.41, cap_ofrecida=406.5, ocupacion=0.41 * 250 / 406.5, cumple=True,
                        carga_diseno=0.41 * 280, buses=6)
    a = una(A.contexto_pronostico("SILENCIO", 60, franja(250.0, 280.0), prediccion(250.0), ENT, rec), "ALT-004")
    assert a["esperado"] == pytest.approx(0.41 * 250 / 406.5, abs=1e-4) and a["observado"] is None


# ---------------------------------------------------------------- ALT-003 por nivel de servicio
ENT_CRA = {"capacidad": 50, "frecuencia_actual_min": 60 / 20.4}   # 20,4 buses/h -> 1.020 puestos/h


def test_alt003_en_franja_inviable_por_nivel_de_servicio():
    """CRA 54 a las 7 h: la recomendación no es viable (mejor aproximación 17 buses/h, menos que los 20,4 actuales) y
    la frecuencia actual no cubre el nivel de servicio. Con la regla anterior (actual < recomendada) no salía nada."""
    rec = rec_sintetica(factor=0.453, cap_ofrecida=1_020.0, ocupacion=0.453 * 1_900 / 1_020, cumple=False,
                        carga_diseno=0.453 * 2_100, viable=False, buses=17)
    c = A.contexto_pronostico("CRA 54", 60, franja(1_900.0, 2_100.0), prediccion(1_900.0), ENT_CRA, rec)
    a = una(c, "ALT-003")
    assert "ALT-001" not in codigos(c)                 # 0,453 × 2.100 = 951 < 1.020: no supera la capacidad
    assert a["severidad"] == "preventiva"
    assert a["observado"] == pytest.approx(20.4)
    necesarios = 0.453 * 2_100 / (0.85 * 50)
    assert a["umbral"] == pytest.approx(necesarios, abs=1e-3) and a["esperado"] == pytest.approx(necesarios, abs=1e-3)
    assert "no es viable" in a["explicacion"] and "escalar" in a["explicacion"]
    assert a["variables"]["fuente_nivel_servicio"].startswith("optimizador")
    assert a["variables"]["cumple_nivel_servicio"] is False


def test_alt003_no_sale_si_la_actual_cumple_aunque_se_recomienden_mas_buses():
    rec = rec_sintetica(factor=0.453, cap_ofrecida=1_020.0, ocupacion=0.5, cumple=True, carga_diseno=700.0, buses=22)
    c = A.contexto_pronostico("CRA 54", 60, franja(1_200.0, 1_400.0), prediccion(1_200.0), ENT_CRA, rec)
    assert "ALT-003" not in codigos(c)


def test_alt003_sale_si_la_actual_no_cumple_aunque_se_recomienden_menos_buses():
    rec = rec_sintetica(factor=0.453, cap_ofrecida=1_020.0, ocupacion=0.8, cumple=False, carga_diseno=900.0,
                        viable=True, buses=24)
    a = una(A.contexto_pronostico("CRA 54", 60, franja(1_800.0, 1_990.0), prediccion(1_800.0), ENT_CRA, rec),
            "ALT-003")
    assert "se recomiendan 24 buses/h" in a["explicacion"]


def test_alt003_sin_optimizador_calcula_el_nivel_de_servicio_con_el_p90():
    # contexto plano: 8 buses/h × 50 × 0,85 = 340 < P90 350 (factor 1) -> no cumple
    base = {"ruta": "X", "buses_hora_actual": 8, "capacidad": 50, "demanda_prevista": 300.0, "p90": 350.0}
    assert "ALT-003" in codigos(base)
    assert "ALT-003" not in codigos(dict(base, buses_hora_actual=9))     # 382,5 ≥ 350


def test_alt003_queda_dentro_de_alt001_en_la_misma_franja():
    """§18 una alerta por fenómeno: si la carga crítica proyectada supera la capacidad (ALT-001), la frecuencia
    insuficiente (ALT-003) es la misma situación con menos fuerza: sale solo ALT-001 y lo anota."""
    rec = rec_sintetica(factor=0.453, cap_ofrecida=1_020.0, ocupacion=0.453 * 2_000 / 1_020, cumple=False,
                        carga_diseno=0.453 * 2_300, viable=False, buses=17)
    c = A.contexto_pronostico("CRA 54", 60, franja(2_000.0, 2_300.0), prediccion(2_000.0), ENT_CRA, rec)
    al = A.evaluar_alertas(c)
    assert "ALT-003" not in {a["codigo"] for a in al}
    a1 = next(a for a in al if a["codigo"] == "ALT-001")
    assert a1["variables"]["incluye_alt003"]["buses_hora_necesarios_nivel_servicio"] == pytest.approx(
        0.453 * 2_300 / (0.85 * 50), abs=0.01)
    assert "tampoco cubre el nivel de servicio" in a1["explicacion"]
