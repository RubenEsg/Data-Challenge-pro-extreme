"""Alertas de pronóstico del ciclo (ALT-001..ALT-004): demanda y capacidad en las mismas unidades (pasajeros y
puestos POR HORA), ventana de la alerta = hora recomendada y una sola alerta por franja aunque la miren varios
horizontes (§5.1, §5.2, §9.4, §18 «alertas excesivas»)."""
from datetime import date, datetime, timedelta

import pytest

from app.servicios import alertas as A

FECHA = date(2025, 10, 16)
# frecuencia programada de 6 min -> 10 buses/h × 50 puestos = 500 puestos por hora
ENTRADAS = {"capacidad": 50, "frecuencia_actual_min": 6.0}
REC = {"buses_hora": 10}


def franja(demanda_hora, p90_hora=None, p10_hora=None, hora=6):
    return {"fecha": FECHA, "hora": hora, "demanda_hora": demanda_hora,
            "p10_hora": demanda_hora * 0.9 if p10_hora is None else p10_hora,
            "p90_hora": demanda_hora * 1.1 if p90_hora is None else p90_hora,
            "fuente": "variables.por_hora (hora principal de la ventana)"}


def prediccion(pasajeros_ventana):
    return {"pasajeros": pasajeros_ventana, "p10": pasajeros_ventana * 0.9, "p90": pasajeros_ventana * 1.1,
            "model_id": "hgb_prueba"}


def ctx(h, fr, ventana=300.0, entradas=None, rec=None, **extra):
    return A.contexto_pronostico("CRA 54", h, fr, prediccion(ventana), entradas or ENTRADAS, rec or REC, **extra)


def codigos(c):
    return {a["codigo"] for a in A.evaluar_alertas(c)}


def una(c, codigo):
    al = [a for a in A.evaluar_alertas(c) if a["codigo"] == codigo]
    assert len(al) == 1, f"{codigo} no se disparó"
    return al[0]


def test_el_contexto_usa_la_demanda_por_hora_de_la_franja_y_su_hora():
    c = ctx(120, franja(450.0, 480.0, 420.0, hora=6), ventana=1_000.0)
    assert c["demanda_prevista"] == 450.0
    assert (c["p10"], c["p90"]) == (420.0, 480.0)
    assert c["unidad_demanda"] == "pasajeros/h"
    assert c["demanda_ventana"] == 1_000.0          # la ventana de 120 min queda para la trazabilidad
    assert c["buses_hora_actual"] == pytest.approx(10.0)
    assert c["ventana_inicio"] == datetime(2025, 10, 16, 6, 0, tzinfo=A.ZONA)
    assert c["ventana_fin"] - c["ventana_inicio"] == timedelta(hours=1)
    assert c["horizonte_min"] == 120


@pytest.mark.parametrize("h", [60, 120])
def test_la_ventana_de_la_alerta_es_la_hora_recomendada(h):
    # a las 6:00 la franja de 60 y de 120 min es la hora 6, no la hora del fin de la ventana (7 h u 8 h)
    a = una(ctx(h, franja(600.0, 650.0)), "ALT-001")
    assert a["ventana_inicio"].astimezone(A.ZONA).hour == 6
    assert a["clave_dedup"] == A.clave_dedup("ALT-001", "CRA 54", a["ventana_inicio"], a["ventana_fin"])


def test_la_fecha_de_la_franja_puede_venir_como_texto():
    c = ctx(60, dict(franja(300.0), fecha="2025-10-16"))
    assert c["ventana_inicio"] == datetime(2025, 10, 16, 6, 0, tzinfo=A.ZONA)


@pytest.mark.parametrize("p90,dispara", [(500.0, False), (500.1, True)])
def test_alt001_frontera_p90_por_hora_frente_a_capacidad_por_hora(p90, dispara):
    assert ("ALT-001" in codigos(ctx(60, franja(400.0, p90)))) is dispara


@pytest.mark.parametrize("demanda,severidad", [(500.0, "preventiva"), (500.1, "critica")])
def test_alt001_critica_solo_si_el_pronostico_puntual_por_hora_supera(demanda, severidad):
    assert una(ctx(60, franja(demanda, 560.0)), "ALT-001")["severidad"] == severidad


def test_la_demanda_de_la_ventana_larga_ya_no_dispara_alt001():
    # 120 min: 900 pasajeros en la ventana de 2 h frente a 500 puestos por hora. Antes se comparaba 900 con 500 y
    # salían ALT-001 y ALT-002 (ocupación 180 %); con la demanda por hora de la franja (400, P90 430: 80 %) no hay
    # riesgo.
    c = ctx(120, franja(400.0, 430.0), ventana=900.0)
    assert "ALT-001" not in codigos(c)
    assert "ALT-002" not in codigos(c)


def test_la_ventana_corta_no_esconde_la_sobreocupacion():
    # 30 min: 240 pasajeros en media hora (la mitad de la hora) no deben ocultar 480 por hora (96 % de 500)
    a = una(ctx(30, franja(480.0, 520.0), ventana=240.0), "ALT-002")
    assert a["esperado"] == pytest.approx(0.96)
    assert a["observado"] is None                  # es una ocupación esperada, no observada


@pytest.mark.parametrize("demanda,dispara", [(449.9, False), (450.0, True)])
def test_alt002_frontera_ocupacion_por_hora(demanda, dispara):
    # ocupación esperada = demanda por hora / capacidad por hora; umbral crítico 90 % de 500 = 450
    assert ("ALT-002" in codigos(ctx(60, franja(demanda, 499.0)))) is dispara


@pytest.mark.parametrize("demanda,dispara", [(149.9, True), (150.0, False)])
def test_alt004_frontera_baja_utilizacion_por_hora(demanda, dispara):
    # 30 % de 500 puestos por hora = 150; la recomendación (6 buses/h) está por debajo de la oferta (10)
    c = ctx(60, franja(demanda, 200.0), rec={"buses_hora": 6})
    assert ("ALT-004" in codigos(c)) is dispara


def test_alt001_explica_el_factor_real_de_buses_por_hora():
    # frecuencia de 2,26 min -> 26,55 buses/h: 1.327 puestos/h. Antes se leía «27 buses/h × 50 puestos».
    c = ctx(60, franja(1_380.0, 1_450.0), entradas={"capacidad": 50, "frecuencia_actual_min": 2.26})
    a = una(c, "ALT-001")
    assert "1.327 puestos/h = 26,5 buses/h × 50 puestos" in a["explicacion"]
    assert "27 buses/h" not in a["explicacion"]
    assert "franja 06:00-07:00" in a["explicacion"]
    assert "pasajeros/h" in a["explicacion"]
    assert a["umbral"] == pytest.approx(60 / 2.26 * 50, abs=1e-3)
    assert a["variables"]["unidad_demanda"] == "pasajeros/h"
    assert a["variables"]["demanda_ventana"] == 300.0       # la ventana del horizonte queda a la vista
    assert "unidad_demanda" not in una(dict(c, unidad_demanda=None, demanda_ventana=None), "ALT-001")["variables"]


def test_alt002_explica_el_calculo_de_la_ocupacion_esperada():
    a = una(ctx(60, franja(460.0, 499.0)), "ALT-002")
    assert "460,0 pasajeros/h ÷ 500 puestos/h" in a["explicacion"]


def test_varios_horizontes_en_la_misma_franja_dan_una_sola_alerta():
    fr = franja(520.0, 560.0)
    contextos = [ctx(h, fr, ventana=v) for h, v in ((30, 250.0), (60, 520.0), (120, 1_100.0))]
    al = [a for a in A.evaluar_pronostico(contextos) if a["codigo"] == "ALT-001"]
    assert len(al) == 1
    assert al[0]["horizonte_min"] == 30                      # el pronóstico más cercano a esa hora
    assert al[0]["variables"]["horizontes_min"] == [30, 60, 120]


def test_se_queda_el_horizonte_mas_corto_aunque_llegue_despues():
    fr = franja(520.0, 560.0)
    al = [a for a in A.evaluar_pronostico([ctx(120, fr), ctx(60, fr)]) if a["codigo"] == "ALT-001"]
    assert len(al) == 1
    assert al[0]["horizonte_min"] == 60
    assert al[0]["variables"]["horizontes_min"] == [60, 120]


def test_franjas_distintas_dan_alertas_distintas():
    contextos = [ctx(60, franja(520.0, 560.0, hora=6)), ctx(120, franja(530.0, 570.0, hora=7))]
    al = [a for a in A.evaluar_pronostico(contextos) if a["codigo"] == "ALT-001"]
    assert sorted(a["ventana_inicio"].hour for a in al) == [6, 7]
    assert all(a["variables"]["horizontes_min"] == [a["horizonte_min"]] for a in al)


def test_evaluar_pronostico_sin_contextos():
    assert A.evaluar_pronostico([]) == []
    assert A.evaluar_pronostico(None) == []


def test_alt010_se_evalua_una_vez_por_ruta():
    fr = franja(300.0)
    contextos = [ctx(30, fr, wape_movil=0.35), ctx(60, fr), ctx(120, fr)]
    al = [a for a in A.evaluar_pronostico(contextos) if a["codigo"] == "ALT-010"]
    assert len(al) == 1


def test_tendencia_por_horizonte_usa_tasas_horarias_sin_doble_conversion():
    from app.servicios.ejecucion import tendencia_por_horizonte

    fr = franja(500.0)
    contextos = [ctx(30, fr, ventana=240.0), ctx(60, fr, ventana=500.0), ctx(120, fr, ventana=1_100.0)]
    tendencia_por_horizonte(contextos)
    serie = contextos[0]["serie_reciente"]
    assert [p["horizonte_min"] for p in serie] == [30, 60, 120]
    assert [p["pasajeros_por_hora"] for p in serie] == [480.0, 500.0, 550.0]   # ventana × 60 / horizonte
    assert A.tendencia(contextos[0]["serie_tendencia"])[0] == "al_alza"


def test_tendencia_por_horizonte_sin_demanda_de_ventana_usa_la_horaria():
    from app.servicios.ejecucion import tendencia_por_horizonte

    contextos = [{"ruta": "X", "horizonte_min": 120, "demanda_prevista": 450.0}]
    tendencia_por_horizonte(contextos)
    assert contextos[0]["serie_reciente"] == [{"horizonte_min": 120, "pasajeros_por_hora": 450.0}]


# ---------------------------------------------------------------- funciones extraídas del motor (mismo resultado)
@pytest.mark.parametrize("esp,obs,minimo,esperado", [
    (4, 2, 2, False),     # déficit 50 % = tolerancia: no supera
    (4, 1, 2, True),      # 75 % > 50 %
    (1, 0, 2, False),     # menos salidas esperadas que el mínimo
    (0, 0, 0, False),     # sin salidas esperadas no hay déficit
    (None, 1, 0, False),
    (3, None, 0, False),
])
def test_deficit_de_salidas(esp, obs, minimo, esperado):
    assert A._deficit_salidas(esp, obs, A.UMBRALES_POR_DEFECTO, minimo) is esperado


def test_horas_sin_salidas_seguidas_se_cortan_si_no_son_contiguas():
    t = datetime(2025, 10, 15, 8, 0, tzinfo=A.ZONA)
    horas = [A.contexto_hora(t, 100, salidas_observadas=0), A.contexto_hora(t + timedelta(hours=1), 100,
                                                                             salidas_observadas=0),
             A.contexto_hora(t + timedelta(hours=3), 100, salidas_observadas=0)]
    ceros = 0
    vistos = []
    for i in range(len(horas)):
        ceros = A._ceros_seguidos(horas, i, ceros)
        vistos.append(ceros)
    assert vistos == [1, 2, 1]


def test_minutos_sin_despacho_usa_la_cota_solo_si_se_esperaban_salidas():
    t = datetime(2025, 10, 15, 8, 0, tzinfo=A.ZONA)
    assert A._minutos_sin_despacho(A.contexto_hora(t, 1, salidas_esperadas=4), 2) == (120.0, True)
    assert A._minutos_sin_despacho(A.contexto_hora(t, 1, salidas_esperadas=0.5), 2) == (None, False)
    h = dict(A.contexto_hora(t, 1, salidas_esperadas=4), minutos_desde_ultimo_despacho=17)
    assert A._minutos_sin_despacho(h, 2) == (17, False)


def test_peor_z_toma_el_primer_campo_con_el_mayor_valor_absoluto():
    zs = [("subidas", 10, 5.0, -4.0), ("bajadas", 12, 5.0, 4.0), ("nro_viajes", 3, 9.0, 1.0)]
    assert A._peor_z(zs) == (-4.0, ("subidas", 10, 5.0))
    assert A._peor_z([]) == (0.0, None)


@pytest.mark.parametrize("usuario", [None, "", "   "])
def test_toda_accion_exige_usuario(usuario):
    with pytest.raises(ValueError):
        A.cambiar_estado("nueva", "reconocer", usuario)


def test_estado_desconocido_y_accion_desconocida():
    with pytest.raises(A.TransicionInvalida, match="Estado desconocido"):
        A.cambiar_estado("perdida", "reconocer", "op")
    with pytest.raises(A.TransicionInvalida, match="Acción desconocida"):
        A.cambiar_estado("nueva", "borrar", "op")


def test_asignar_exige_a_quien_y_comentar_no_cambia_el_estado():
    with pytest.raises(ValueError, match="asignado_a"):
        A.cambiar_estado("reconocida", "asignar", "op", asignado_a="  ")
    nuevo, entrada = A.cambiar_estado({"id": "a1", "estado": "asignada"}, "comentar", "op", comentario="visto")
    assert nuevo == "asignada"
    assert entrada["alerta_id"] == "a1"
    assert entrada["estado_anterior"] == entrada["estado_nuevo"] == "asignada"
    with pytest.raises(A.TransicionInvalida, match="No se puede comentar"):
        A.cambiar_estado("cerrada", "comentar", "op", comentario="tarde")
    with pytest.raises(A.TransicionInvalida, match="ninguna"):
        A.cambiar_estado("descartada", "cerrar", "op")
