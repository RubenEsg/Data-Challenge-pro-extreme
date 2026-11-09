"""Pruebas de optimizacion.recomendar (fórmulas de §10.3, viabilidad, RF-008) y de plan_dia_d5 (MILP de D5)."""
import math
from unittest import mock

import pytest

from app.servicios import optimizacion as O


def rec(**kw):
    base = dict(ruta="CRA 54", hora=7, demanda_hora=300, demanda_p90=None, capacidad=50, ocupacion_objetivo=0.85,
                tiempo_ciclo_min=120, flota_disponible=40, headway_min=2, headway_max=10, frecuencia_actual_min=None,
                factor_carga=1.0)                   # fórmula literal de §10.3 sobre la demanda
    base.update(kw)
    return O.recomendar(**base)


def test_factor_de_carga_critica_por_ruta():
    r = rec(demanda_hora=1000, factor_carga=None, flota_disponible=None)
    assert r["factor_carga"] == O.FACTOR_CARGA_CRITICA["CRA 54"] and r["fuente_factor_carga"].startswith("ruta")
    assert r["buses_hora"] == math.ceil(1000 * 0.453 / 42.5 - 1e-9)
    assert r["ocupacion_esperada"] == pytest.approx(1000 * 0.453 / (r["buses_hora"] * 50), abs=1e-4)
    assert "carga_critica = 0,453" in r["formula"]
    assert rec(ruta="OTRA", factor_carga=None)["factor_carga"] == 1.0
    with pytest.raises(ValueError):
        rec(factor_carga=1.5)


def test_formulas_basicas_de_la_especificacion():
    r = rec(demanda_hora=300)
    assert r["capacidad_efectiva"] == pytest.approx(42.5)
    assert r["buses_hora"] == math.ceil(300 / 42.5) == 8
    assert r["headway_min"] == pytest.approx(7.5)
    assert r["vehiculos_requeridos"] == math.ceil(120 / 7.5) == 16
    assert r["ocupacion_esperada"] == pytest.approx(300 / (8 * 50), abs=1e-4)
    assert r["viable"] is True and r["motivo"] is None
    assert "ceil" in r["formula"] and "42,5" in r["formula"]


def test_usa_el_p90_para_absorber_la_incertidumbre():
    r = rec(demanda_hora=300, demanda_p90=380)
    assert r["criterio_demanda"] == "p90"
    assert r["buses_hora"] == math.ceil(380 / 42.5) == 9
    # la ocupación esperada se calcula con la demanda puntual, no con el P90
    assert r["ocupacion_esperada"] == pytest.approx(300 / (9 * 50), abs=1e-4)


def test_p90_menor_que_la_puntual_no_reduce_la_oferta():
    assert rec(demanda_hora=300, demanda_p90=100)["buses_hora"] == 8


def test_demanda_baja_respeta_el_headway_maximo():
    r = rec(demanda_hora=10, headway_max=10)
    assert r["buses_hora"] == 6 and r["headway_min"] == pytest.approx(10)
    assert r["buses_hora_demanda"] == 1 and r["viable"] is True


def test_demanda_cero_da_el_servicio_minimo():
    r = rec(demanda_hora=0, headway_max=15)
    assert r["buses_hora"] == 4 and r["headway_min"] == pytest.approx(15)
    assert r["headway_demanda_min"] is None


def test_headway_minimo_inalcanzable_es_inviable_sin_forzar():
    r = rec(demanda_hora=2000, headway_min=3, flota_disponible=None)
    assert r["viable"] is False
    assert "headway mínimo" in r["motivo"]
    assert r["buses_hora"] == 20 and r["headway_min"] >= 3      # nunca viola el límite
    assert r["buses_hora_demanda"] == math.ceil(2000 / 42.5)


def test_flota_insuficiente_es_inviable_con_motivo():
    r = rec(demanda_hora=300, tiempo_ciclo_min=120, flota_disponible=10)
    assert r["viable"] is False and "flota" in r["motivo"].lower()
    assert r["vehiculos_requeridos"] == 16
    assert r["buses_hora_factible"] == 5                       # floor(10 * 60 / 120)
    assert r["headway_factible_min"] == pytest.approx(12)


def test_flota_justa_es_viable():
    r = rec(demanda_hora=300, tiempo_ciclo_min=120, flota_disponible=16)
    assert r["viable"] is True


def test_comparacion_con_la_frecuencia_actual_rf008():
    r = rec(demanda_hora=300, frecuencia_actual_min=10)
    assert r["frecuencia_actual_min"] == 10
    assert r["diferencia_min"] == pytest.approx(-2.5)
    assert r["cambio"] == "reducir_intervalo"
    assert r["buses_hora_actual"] == pytest.approx(6)
    assert rec(demanda_hora=300, frecuencia_actual_min=7.5)["cambio"] == "mantener"
    assert rec(demanda_hora=50, frecuencia_actual_min=5)["cambio"] == "ampliar_intervalo"


def test_sin_ciclo_no_calcula_vehiculos():
    r = rec(tiempo_ciclo_min=None, flota_disponible=None)
    assert r["vehiculos_requeridos"] is None and r["viable"] is True


@pytest.mark.parametrize("campo,valor", [("capacidad", 0), ("capacidad", -5), ("ocupacion_objetivo", 0),
                                         ("ocupacion_objetivo", 1.2), ("demanda_hora", -1), ("headway_min", 0),
                                         ("headway_max", 1), ("demanda_hora", "abc"), ("demanda_hora", float("nan")),
                                         ("headway_min", 90), ("frecuencia_actual_min", 0)])
def test_entradas_invalidas_lanzan_error(campo, valor):
    kw = {campo: valor}
    if campo == "headway_min" and valor == 90:
        kw["headway_max"] = 120
    with pytest.raises(ValueError):
        rec(**kw)


def test_flota_que_ni_siquiera_cumple_el_headway_maximo():
    r = rec(demanda_hora=10, tiempo_ciclo_min=120, flota_disponible=5, headway_max=10)
    assert r["viable"] is False and "headway máximo" in r["motivo"]
    assert r["buses_hora_factible"] == 2 and r["headway_factible_min"] == pytest.approx(30)


def test_escenarios_de_sensibilidad():
    base = dict(ruta="CRA 54", hora=7, demanda_hora=300, demanda_p90=360, capacidad=50, tiempo_ciclo_min=120,
                flota_disponible=40, headway_min=2, headway_max=10, frecuencia_actual_min=8, factor_carga=1.0)
    tabla = O.escenarios(base, ocupaciones=(0.65, 0.85), factores_demanda=(1.0, 1.5))
    assert len(tabla) == 4
    por = {(t["ocupacion_objetivo"], t["factor_demanda"]): t for t in tabla}
    assert por[(0.65, 1.0)]["buses_hora"] == math.ceil(360 / 32.5)
    assert por[(0.85, 1.5)]["buses_hora"] == math.ceil(540 / 42.5)
    # menos ocupación objetivo o más demanda -> nunca menos buses
    assert por[(0.65, 1.5)]["buses_hora"] >= por[(0.85, 1.5)]["buses_hora"] >= por[(0.85, 1.0)]["buses_hora"]


def test_plan_dia_d5_devuelve_headways_por_hora():
    plan = O.plan_dia_d5("SILENCIO", "2025-03-10", modelo="E1")
    assert [p["hora"] for p in plan] == list(range(4, 21))
    for p in plan:
        assert p["salidas"] >= 0
        assert len(p["despachos"]) == p["salidas"]
        assert all(d.startswith(f"{p['hora']:02d}:") for d in p["despachos"])
        if p["salidas"] > 0 and p["minutos_operados"] > 0:
            assert p["headway_min"] == pytest.approx(p["minutos_operados"] / p["salidas"], abs=0.01)
        else:
            assert p["headway_min"] is None
    assert plan[0]["estado_solver"] == "Optimal"


def test_plan_dia_d5_reutiliza_el_milp(monkeypatch):
    from app.servicios.motor_d5 import plan_base
    llamado = mock.Mock(wraps=plan_base.plan_ruta)
    monkeypatch.setattr(plan_base, "plan_ruta", llamado)
    O.plan_dia_d5("CL 72", "2025-03-11", modelo="E1")
    assert llamado.call_count == 1
    assert llamado.call_args.args[1] == "CL 72"


def test_plan_dia_d5_errores():
    with pytest.raises(ValueError):
        O.plan_dia_d5("RUTA X", "2025-03-10")
    with pytest.raises(ValueError):
        O.plan_dia_d5("CL 72", "2025-03-10", modelo="ZZ")
    with pytest.raises(ValueError):
        O.plan_dia_d5("CL 72", "2030-01-01")


# ------------------------------------------------------------------ festivos entre semana
def test_festivo_entre_semana_usa_la_programacion_de_domingo_o_festivo():
    """El 17-nov-2025 es lunes festivo (Independencia de Cartagena): la programación de comparación, el contexto de la
    franja y el factor de carga usan los parámetros de domingo o festivo, el mismo tipo de día del plan D5."""
    from datetime import date

    festivo, domingo, lunes = date(2025, 11, 17), date(2025, 11, 16), date(2025, 11, 10)
    assert O.es_festivo(festivo) and not O.es_festivo(lunes)
    assert O.tipo_dia_operacion(festivo) == 2 and O.tipo_dia_operacion(lunes) == 0
    assert O.tipo_dia_operacion(None) == 0
    assert O._intervalos_programados("SILENCIO", festivo) == O._intervalos_programados("SILENCIO", domingo)
    assert O._intervalos_programados("SILENCIO", festivo) != O._intervalos_programados("SILENCIO", lunes)
    ctx = O.contexto_franja("SILENCIO", festivo, 7)
    assert ctx["tipo_dia"] == "Domingo/festivo" and ctx == O.contexto_franja("SILENCIO", domingo, 7)
    assert O.factor_carga_franja("CRA 54", festivo, 11) == O.factor_carga_franja("CRA 54", domingo, 11)
    plan = O.resumen_plan_d5("SILENCIO", festivo)
    assert plan["tipo_dia"] == "Domingo/festivo"
    programado = O._intervalos_programados("SILENCIO", domingo)
    for h in plan["horas"]:
        if h["frecuencia_actual_min"] is not None:
            assert h["frecuencia_actual_min"] == round(programado[h["hora"]], 2)


# ------------------------------------------------------------------ headway mínimo gobernado en el plan D5
def test_plan_d5_respeta_el_headway_minimo_gobernado():
    """§10.2 «sujeto a headway mínimo»: D5 admitía hasta 35 salidas por hora donde la operación ya las tuvo; con el
    tope ninguna hora pasa de floor(minutos / headway mínimo) y la hora que la demanda pedía más queda marcada."""
    plan = O.resumen_plan_d5("CRA 54", "2025-11-19")          # 5 h: D5 sin tope pedía 34 salidas (1,76 min)
    assert plan["headway_minimo_min"] == 2.0 and plan["estado_solver"] == "Optimal"
    for h in plan["horas"]:
        assert h["salidas"] <= h["maximo_salidas_headway"]
        assert h["maximo_salidas_headway"] >= math.floor(h["minutos_operados"] / 2.0 + 1e-9)
        if h["salidas"] >= 2:
            assert h["headway_min"] >= 2.0 - 0.01
    cinco = next(h for h in plan["horas"] if h["hora"] == 5)
    assert cinco["limitada_por_headway_minimo"] and cinco["salidas_sin_tope"] > cinco["maximo_salidas_headway"]
    assert cinco["salidas"] == cinco["maximo_salidas_headway"] == 30 and cinco["headway_min"] == 2.0
    assert plan["horas_limitadas_por_headway_minimo"] == [5]
    # un mínimo gobernado más laxo deja el plan de D5 tal cual (sin horas limitadas)
    laxo = O.resumen_plan_d5("CRA 54", "2025-11-19", headway_min=1.5)
    assert laxo["horas_limitadas_por_headway_minimo"] == []
    assert next(h for h in laxo["horas"] if h["hora"] == 5)["salidas"] == cinco["salidas_sin_tope"]
    # sin horas por encima del tope, el plan es exactamente el de D5
    plan_cl72 = O.resumen_plan_d5("CL 72", "2025-11-19")
    assert all(h["salidas"] == h["salidas_sin_tope"] for h in plan_cl72["horas"])
