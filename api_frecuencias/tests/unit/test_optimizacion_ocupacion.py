"""§10.1 en el optimizador: factor de carga por día de la semana con el de tipo de día como respaldo, segmento crítico
histórico en la explicación de la franja y del plan, y la ocupación actual como restricción reactiva del plan del día
(piso del MILP), sin cambiar el plan cuando no hay ocupación observada (paridad).
"""
from __future__ import annotations

import math
from datetime import date

import pytest

from app.servicios import datos, ocupacion
from app.servicios import optimizacion as O

UMBRALES = {"headway_minimo_min": 2.0, "headway_maximo_min": 10.0, "espera_max_min": 5.0,
            "ocupacion_objetivo_min": 0.65, "ocupacion_objetivo_max": 0.85, "ocupacion_critica": 0.9}
DIA = date(2025, 11, 19)          # miércoles


def _pronostico(base=150.0):
    return [{"hora": h, "p10": 0.8 * base, "p50": base, "p90": 1.25 * base} for h in range(4, 21)]


def _reactiva(hora_aplica=9, carga=900.0, aplica=True):
    return {"aplica": aplica, "hora_aplica": hora_aplica, "hora_cerrada": hora_aplica - 1, "segmento": 34,
            "ocupacion_observada": 0.97, "carga_critica_pax_h": carga, "umbral_critico": 0.9,
            "motivo": "En la última hora cerrada la ocupación observada fue 97 %.",
            "naturaleza": ocupacion.NATURALEZA_REACTIVA}


@pytest.fixture(autouse=True)
def _memoria_vacia():
    O.limpiar_cache_plan()
    yield
    O.limpiar_cache_plan()


# ---------------------------------------------------------------- factor de carga por día de la semana
def test_el_factor_de_carga_es_por_dia_de_la_semana_con_el_tipo_de_dia_de_respaldo(monkeypatch):
    lunes, miercoles = date(2025, 11, 10), date(2025, 11, 12)
    f_lunes = O.factor_carga_franja("SILENCIO", lunes, 7)
    f_miercoles = O.factor_carga_franja("SILENCIO", miercoles, 7)
    assert f_lunes["nivel"] == f_miercoles["nivel"] == "dia_semana"
    assert (f_lunes["id_dia_semana"], f_miercoles["id_dia_semana"]) == (1, 3)
    assert f_lunes["dias"] >= O.MIN_DIAS_FACTOR and "mediana 2025" in f_lunes["fuente"]
    dias = O._factores_carga_dia()
    assert (f_lunes["factor_carga"], f_miercoles["factor_carga"]) == (
        round(dias[("SILENCIO", 1, 7)][0], 4), round(dias[("SILENCIO", 3, 7)][0], 4))
    # los días laborales de una ruta y hora no tienen todos el mismo factor (por eso se desagrega)
    assert len({round(dias[("CRA 54", d, 7)][0], 3) for d in range(1, 6)}) > 1
    # sin fecha, o sin la celda del día, el factor de antes (ruta, tipo de día, hora)
    tipo = O._factores_carga_hora()[("SILENCIO", "L", 7)]
    assert O.factor_carga_franja("SILENCIO", None, 7) == {"factor_carga": round(tipo[0], 4), "dias": tipo[1],
                                                          "nivel": "tipo_dia", "id_dia_semana": None,
                                                          "fuente": O.FUENTE_FACTOR_TIPO}
    monkeypatch.setattr(O, "_factores_carga_dia", lambda: {})
    respaldo = O.factor_carga_franja("SILENCIO", lunes, 7)
    assert respaldo["nivel"] == "tipo_dia" and respaldo["factor_carga"] == round(tipo[0], 4)
    assert respaldo["id_dia_semana"] == 1


def test_el_dia_de_operacion_de_un_festivo_es_7():
    assert O.dia_semana_operacion(date(2025, 11, 17)) == 7          # lunes festivo
    assert O.dia_semana_operacion(date(2025, 11, 16)) == 7          # domingo
    assert O.dia_semana_operacion(date(2025, 11, 15)) == 6
    assert O.dia_semana_operacion(DIA) == 3 and O.dia_semana_operacion(None) is None


# ---------------------------------------------------------------- segmento crítico en la explicación
def test_la_franja_explica_cual_es_el_segmento_critico_y_su_ocupacion_historica():
    info = datos.ruta_info("CRA 54")
    r, _ = O.recomendacion_franja(info, UMBRALES, 4, hora=6, fecha=DIA, demanda_hora=1400, demanda_p90=1600)
    h = r["ocupacion_historica"]
    assert h == ocupacion.segmento_critico_historico("CRA 54", DIA, 6, 50)
    assert h["nivel"] == "dia_semana" and h["id_dia_semana"] == 3
    assert r["explicacion"][-1] == h["texto"] and "Segmento crítico histórico" in h["texto"]
    assert r["contexto_franja"]["factor_carga"]["nivel"] == "dia_semana"


def test_sin_perfil_la_franja_no_cambia_su_explicacion(monkeypatch):
    info = datos.ruta_info("CRA 54")
    monkeypatch.setattr(ocupacion, "segmento_critico_historico", lambda *a, **k: None)
    r, _ = O.recomendacion_franja(info, UMBRALES, 4, hora=6, fecha=DIA, demanda_hora=1400, demanda_p90=1600)
    assert r["ocupacion_historica"] is None
    assert not any("Segmento crítico" in t for t in r["explicacion"])


def test_cada_hora_del_plan_trae_su_segmento_critico_historico():
    plan = O.plan_dia(DIA, "CRA 54", umbrales=UMBRALES, umbrales_version=None, pronostico_horario=_pronostico())
    seis = next(h for h in plan["horas"] if h["hora"] == 6)
    assert seis["ocupacion_historica"]["nro_segmento"] == ocupacion.segmento_critico_historico(
        "CRA 54", DIA, 6, 50)["nro_segmento"]
    assert all(h["restriccion_reactiva"] is None for h in plan["horas"])
    assert plan["ocupacion_actual"] is None and "Restricción reactiva" not in plan["formulacion"]


# ---------------------------------------------------------------- paridad: sin ocupación observada, el mismo plan
def test_sin_ocupacion_observada_o_si_no_aplica_el_plan_es_el_mismo():
    pron = _pronostico()
    base = O.plan_dia(DIA, "CL 72", umbrales=UMBRALES, umbrales_version=None, pronostico_horario=pron)
    O.limpiar_cache_plan()
    no_aplica = O.plan_dia(DIA, "CL 72", umbrales=UMBRALES, umbrales_version=None, pronostico_horario=pron,
                           ocupacion_actual=_reactiva(aplica=False))
    assert [h["salidas"] for h in no_aplica["horas"]] == [h["salidas"] for h in base["horas"]]
    assert no_aplica["costo_total_cop"] == base["costo_total_cop"] and no_aplica["ocupacion_actual"]["aplica"] is False
    assert all(h["restriccion_reactiva"] is None for h in no_aplica["horas"])


def test_sin_piso_el_milp_recibe_la_misma_tabla_y_el_plan_e12_no_cambia():
    """Paridad del MILP: sin restricción reactiva, o si no aplica, las entradas del MILP son la MISMA tabla (el plan es
    el de siempre, con el motor de D5 sin cambios); la opción de laboratorio E12 tampoco cambia."""
    gob = O.parametros_plan(UMBRALES, None)
    tb = O._con_cotas(O.insumos_plan(DIA, "CL 72", _pronostico()).reset_index(drop=True), gob)
    assert O._aplicar_reactiva(tb, None, gob) is None and (tb["piso_reactivo"] == 0).all()
    assert O._con_piso_reactivo(tb) is tb
    no = _reactiva(aplica=False)
    assert O._aplicar_reactiva(tb, no, gob) is no and O._con_piso_reactivo(tb) is tb
    e12 = O.plan_dia(DIA, "SILENCIO", umbrales=UMBRALES, umbrales_version=None, pronostico="E12")
    O.limpiar_cache_plan()
    e12_no = O.plan_dia(DIA, "SILENCIO", umbrales=UMBRALES, umbrales_version=None, pronostico="E12",
                        ocupacion_actual=no)
    assert [h["salidas"] for h in e12_no["horas"]] == [h["salidas"] for h in e12["horas"]]
    assert e12["ocupacion_actual"] is None and e12_no["costo_total_cop"] == e12["costo_total_cop"]


# ---------------------------------------------------------------- restricción reactiva en el MILP del plan
def test_la_restriccion_reactiva_sube_las_salidas_de_la_hora_siguiente():
    pron = _pronostico()
    base = O.plan_dia(DIA, "CL 72", umbrales=UMBRALES, umbrales_version=None, pronostico_horario=pron)
    nueve = next(h for h in base["horas"] if h["hora"] == 9)
    carga = 50 * 0.85 * (nueve["salidas"] + 4)              # pide 4 salidas más de las que el plan programaba
    plan = O.plan_dia(DIA, "CL 72", umbrales=UMBRALES, umbrales_version=None, pronostico_horario=pron,
                      ocupacion_actual=_reactiva(9, carga))
    r = plan["ocupacion_actual"]
    assert r["aplica"] is True and r["salidas_minimas"] == r["salidas_pedidas"] == math.ceil(carga / 42.5 - 1e-9)
    assert "ceil(" in r["formula"] and r["limitada_por_headway_minimo"] is False
    h9 = next(h for h in plan["horas"] if h["hora"] == 9)
    assert h9["salidas"] >= r["salidas_minimas"] > nueve["salidas"]
    assert h9["restriccion_reactiva"]["activa"] is True and "ocupacion_observada" in h9["limites_activos"]
    assert h9["margen"]["una_salida_menos"]["factible"] is False          # el piso es una cota dura
    assert all(h["restriccion_reactiva"] is None for h in plan["horas"] if h["hora"] != 9)
    assert "Restricción reactiva de ocupación observada" in plan["formulacion"] and plan["estado_solver"] == "Optimal"


def test_la_restriccion_reactiva_se_acota_por_el_headway_minimo():
    plan = O.plan_dia(DIA, "CL 72", umbrales=UMBRALES, umbrales_version=None, pronostico_horario=_pronostico(),
                      ocupacion_actual=_reactiva(9, 50_000.0))
    r = plan["ocupacion_actual"]
    h9 = next(h for h in plan["horas"] if h["hora"] == 9)
    assert r["limitada_por_headway_minimo"] is True and r["salidas_pedidas"] > r["salidas_minimas"]
    assert r["salidas_minimas"] == h9["maximo_salidas_headway"] == h9["salidas"]
    assert "acotado por el headway mínimo" in r["formula"]


def test_la_sobreoferta_que_impone_el_piso_reactivo_lo_dice():
    """Si el piso reactivo fuerza la hora por encima de lo que el pronóstico necesita, la marca de sobreoferta (§5.1)
    nombra la restricción reactiva como causa, no el costo del MILP."""
    plan = O.plan_dia(DIA, "CL 72", umbrales=UMBRALES, umbrales_version=None, pronostico_horario=_pronostico(),
                      ocupacion_actual=_reactiva(9, 50_000.0))
    h9 = next(h for h in plan["horas"] if h["hora"] == 9)
    assert h9["sobreoferta"] is True and "ocupacion_observada" in h9["limites_activos"]
    assert "restricción reactiva de ocupación observada" in h9["motivo_sobreoferta"]
    assert "costo de la espera" not in h9["motivo_sobreoferta"]
    sin_piso = [h for h in plan["horas"] if h["hora"] != 9 and h["sobreoferta"]]
    assert all("restricción reactiva" not in h["motivo_sobreoferta"] for h in sin_piso)


def test_si_con_el_piso_no_hay_solucion_el_plan_se_resuelve_sin_el(monkeypatch):
    original = O._resolver_plan

    def resolver(tb, p_milp):
        if (tb["piso_reactivo"] > 0).any():
            raise ValueError("El MILP del plan del día terminó en «Infeasible»")
        return original(tb, p_milp)

    monkeypatch.setattr(O, "_resolver_plan", resolver)
    plan = O.plan_dia(DIA, "CL 72", umbrales=UMBRALES, umbrales_version=None, pronostico_horario=_pronostico(),
                      ocupacion_actual=_reactiva(9, 900.0))
    assert plan["ocupacion_actual"]["aplica"] is False and "No se pudo aplicar" in plan["ocupacion_actual"]["motivo"]
    assert all(h["restriccion_reactiva"] is None for h in plan["horas"])


def test_una_hora_sin_operacion_no_recibe_el_piso():
    plan = O.plan_dia(DIA, "CL 72", umbrales=UMBRALES, umbrales_version=None, pronostico_horario=_pronostico(),
                      ocupacion_actual=_reactiva(21, 900.0))
    assert plan["ocupacion_actual"]["aplica"] is False and "no se opera" in plan["ocupacion_actual"]["motivo"]


def test_el_plan_persistido_conserva_la_ocupacion_historica_y_la_actual():
    plan = O.plan_dia(DIA, "CL 72", umbrales=UMBRALES, umbrales_version=2, pronostico_horario=_pronostico(),
                      ocupacion_actual=_reactiva(9, 900.0))
    filas = [O.fila_plan(plan, h) for h in plan["horas"]]
    rehecho = O.plan_desde_filas(filas)
    assert rehecho["ocupacion_actual"]["aplica"] is True
    h9 = next(h for h in rehecho["horas"] if h["hora"] == 9)
    assert h9["restriccion_reactiva"]["salidas_minimas"] == plan["ocupacion_actual"]["salidas_minimas"]
    assert h9["ocupacion_historica"] == next(h for h in plan["horas"] if h["hora"] == 9)["ocupacion_historica"]
