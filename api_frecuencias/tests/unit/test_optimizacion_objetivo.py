"""Función objetivo de §10.2 (pesos versionados), MILP de la franja frente a la enumeración exacta, viabilidad (§18
«Recomendación inviable»), tipologías de capacidad (§10.1), escenarios (RF-008) y sensibilidad (§10.3)."""
import json
import math
import re

import pytest

from app.servicios import optimizacion as O


def opt(**kw):
    base = dict(ruta="CRA 54", hora=7, demanda_hora=600, demanda_p90=720, capacidad=50, ocupacion_objetivo=0.85,
                ocupacion_critica=0.90, tiempo_ciclo_min=120, flota_disponible=60, headway_min=2, headway_max=10,
                frecuencia_actual_min=None, factor_carga=1.0, km_ciclo=40, cv_intervalos=0.5)
    base.update(kw)
    return O.optimizar(**base)


# ------------------------------------------------------------------ parámetros versionados
def test_parametros_por_omision_threshold_config_y_solicitud():
    p = O.parametros_objetivo()
    assert set(p) == set(O.PARAMETROS_OBJETIVO)
    assert all(v["fuente"].startswith("código") for v in p.values())
    p = O.parametros_objetivo({"peso_tiempo_espera": 2.5, "ocupacion_critica": 0.9}, version=7)
    assert p["peso_tiempo_espera"] == {"valor": 2.5, "fuente": "threshold_config v7"}
    p = O.parametros_objetivo({"peso_tiempo_espera": 2.5}, version=7, sobrescribir={"beta": 4, "nivel_servicio": 0.95})
    assert p["peso_tiempo_espera"] == {"valor": 4.0, "fuente": "solicitud"}
    assert p["nivel_servicio"]["valor"] == 0.95


@pytest.mark.parametrize("valores", [{"zeta": 1}, {"nivel_servicio": 1.2}, {"nivel_servicio": 0.3},
                                     {"alfa": -1}, {"alfa": 0, "beta": 0, "gamma": 0, "delta": 0}])
def test_parametros_invalidos(valores):
    with pytest.raises(ValueError):
        O.parametros_objetivo(sobrescribir=valores)


def test_costos_por_omision_son_los_de_d5_con_fuente():
    from app.servicios.motor_d5 import comun as C

    P = C.param_d5(fuente=True)
    defecto = {n: v for n, (v, _d) in O.PARAMETROS_OBJETIVO.items()}
    assert defecto["costo_bus_hora_cop"] == pytest.approx(P["COSTO_BUS_HORA"], abs=0.01)
    assert defecto["costo_km_cop"] == pytest.approx(P["COSTO_KM"], abs=0.01)
    assert defecto["valor_tiempo_espera_cop_h"] == P["VALOR_TIEMPO_ESPERA"]
    assert defecto["penalidad_sobreocupacion_cop"] == P["PENALIDAD_SOBRECARGA"]


def test_datos_de_ruta_coinciden_con_insumos_d5():
    pd = pytest.importorskip("pandas")
    from app.servicios.motor_d5 import comun as C

    archivo = C.DATOS / "insumos_d5_2025.parquet"
    if not archivo.exists():
        pytest.skip("sin insumos de D5")
    d = pd.read_parquet(archivo).groupby("ruta")[["dist", "cv_d4"]].median()
    for ruta in O.KM_CICLO:
        assert O.KM_CICLO[ruta] == pytest.approx(d.loc[ruta, "dist"], abs=0.05)
        assert O.CV_INTERVALOS[ruta] == pytest.approx(d.loc[ruta, "cv_d4"], abs=0.001)


# ------------------------------------------------------------------ función objetivo y solver
def test_componentes_de_la_funcion_objetivo():
    r = opt(frecuencia_actual_min=6)
    k = r["buses_hora"]
    p = {n: v for n, (v, _d) in O.PARAMETROS_OBJETIVO.items()}
    comp = r["componentes_cop"]
    assert comp["costo_operativo"] == pytest.approx(k * (120 / 60 * p["costo_bus_hora_cop"] + 40 * p["costo_km_cop"]),
                                                    abs=0.02)
    assert comp["tiempo_espera"] == pytest.approx(600 * (60 / k) / 2 * 1.25 / 60 * p["valor_tiempo_espera_cop_h"],
                                                  abs=0.02)
    assert comp["desviacion_frecuencia"] == pytest.approx(abs(k - 10) * p["costo_cambio_frecuencia_cop"], abs=0.02)
    assert r["costo_total_ponderado_cop"] == pytest.approx(sum(comp.values()), abs=0.1)
    assert r["objetivo"]["expresion"].startswith("min α·costo_operativo + β·tiempo_espera")
    assert r["headway_min"] == pytest.approx(60 / k, abs=0.01)
    assert r["vehiculos_requeridos"] == math.ceil(120 * k / 60 - 1e-9)


@pytest.mark.parametrize("caso", [
    dict(),
    dict(demanda_hora=1000, demanda_p90=1200, flota_disponible=200),
    dict(demanda_hora=40, demanda_p90=None),
    dict(frecuencia_actual_min=4, parametros={"delta": 3}),
    dict(parametros={"beta": 6, "gamma": 2}),
    dict(tipologias=[{"codigo": "A", "nombre": "a", "capacidad": 46, "disponibles": 8},
                     {"codigo": "B", "nombre": "b", "capacidad": 72, "disponibles": 5}], flota_disponible=13,
         demanda_hora=200, demanda_p90=240),
    dict(tipologias=[{"codigo": "A", "nombre": "a", "capacidad": 46, "disponibles": 30},
                     {"codigo": "B", "nombre": "b", "capacidad": 58, "disponibles": 6},
                     {"codigo": "C", "nombre": "c", "capacidad": 72, "disponibles": 4}],
         demanda_hora=700, demanda_p90=820, flota_disponible=40, parametros={"gamma": 3}),
    dict(tipologias=[{"codigo": "A", "nombre": "a", "capacidad": 46, "disponibles": 8},
                     {"codigo": "B", "nombre": "b", "capacidad": 72, "disponibles": 5}], flota_disponible=13),
])
def test_milp_coincide_con_la_enumeracion_exacta(caso):
    r = opt(verificar=True, **caso)
    v = r["solver"]["verificacion_enumeracion"]
    assert v["coinciden"] is True, v
    if r["viable"]:
        assert r["solver"]["estado"] == "Optimal"
    else:                                   # el último caso no tiene solución: los dos métodos lo confirman
        assert r["solver"]["estado"] == "Infeasible" and v["optimo_enumeracion_cop"] is None


def test_pesos_mueven_la_solucion_en_la_direccion_esperada():
    base = opt()["buses_hora"]
    assert opt(parametros={"beta": 50})["buses_hora"] > base            # la espera pesa más: más buses
    assert opt(parametros={"alfa": 10})["buses_hora"] <= base           # el costo pesa más: nunca más buses
    cerca = opt(frecuencia_actual_min=60 / 22, parametros={"delta": 50})
    assert cerca["buses_hora"] == 22                                   # δ grande: se queda en la programada
    piso = opt(frecuencia_actual_min=60 / 14, parametros={"delta": 50})
    assert piso["buses_hora"] == base                  # pero nunca baja del nivel de servicio por seguir la programada
    solo_costo = opt(parametros={"beta": 0, "gamma": 0, "delta": 0})
    assert "nivel_servicio" in solo_costo["limites_activos"] or "headway_maximo" in solo_costo["limites_activos"]


def test_nivel_de_servicio_usa_el_p90_calibrado():
    r = opt(demanda_hora=600, demanda_p90=720)
    assert r["demanda"]["carga_critica_diseno"] == pytest.approx(720, rel=1e-6)   # nivel 0,90 = P90
    assert r["demanda"]["criterio"] == "banda P90 calibrada"
    r95 = opt(demanda_hora=600, demanda_p90=720, parametros={"nivel_servicio": 0.95})
    s = math.log(720 / 600) / O.Z90
    assert r95["demanda"]["carga_critica_diseno"] == pytest.approx(600 * math.exp(1.6448536 * s), rel=1e-5)
    assert r95["buses_hora"] >= r["buses_hora"]
    sin_banda = opt(demanda_hora=600, demanda_p90=None)
    assert sin_banda["demanda"]["carga_critica_diseno"] == pytest.approx(600)
    solo_p10 = opt(demanda_hora=600, demanda_p90=None, demanda_p10=500)
    assert solo_p10["demanda"]["sigma_log"] > 0
    # la capacidad efectiva ofrecida cubre siempre la carga de diseño
    for x in (r, r95, sin_banda, solo_p10):
        assert x["capacidad_ofrecida"] * 0.85 >= x["demanda"]["carga_critica_diseno"] - 1e-6


def test_linea_base_10_3_intacta_al_lado():
    r = opt()
    b = O.recomendar("CRA 54", 7, 600, demanda_p90=720, capacidad=50, ocupacion_objetivo=0.85, tiempo_ciclo_min=120,
                     flota_disponible=60, headway_min=2, headway_max=10, factor_carga=1.0)
    assert r["linea_base_10_3"]["buses_hora"] == b["buses_hora"]
    assert r["linea_base_10_3"]["formula"] == b["formula"]
    assert "Línea base §10.3" in r["formula"]


# ------------------------------------------------------------------ viabilidad (§18): nunca una cifra forzada
def test_inviable_por_headway_minimo_sin_cifra_forzada():
    r = opt(demanda_hora=3000, demanda_p90=3600, flota_disponible=None, headway_min=3)
    assert r["viable"] is False and "headway mínimo" in r["motivo"]
    aprox = r["mejor_aproximacion"]
    assert aprox["buses_hora"] == 20 and aprox["cobertura_nivel_servicio"] < 1 and "NO cumple" in aprox["aviso"]
    # las cifras son la aproximación ejecutable: nunca violan el headway mínimo (no se fuerza la demanda)
    assert r["buses_hora"] == 20 and r["headway_min"] >= 3 and r["vehiculos_requeridos"] == 40
    assert "cubre el" in r["motivo"] and r["explicacion"][0].startswith("No viable")


def test_inviable_porque_la_flota_no_alcanza_ni_el_headway_maximo():
    r = opt(demanda_hora=50, demanda_p90=60, tiempo_ciclo_min=240, flota_disponible=10, headway_max=10)
    assert r["viable"] is False and "headway máximo" in r["motivo"] and "flota" in r["motivo"].lower()
    # nada es ejecutable: ninguna cifra
    assert r["buses_hora"] is None and r["vehiculos_requeridos"] is None and r["mejor_aproximacion"] is None


def test_inviable_porque_la_flota_no_cubre_el_nivel_de_servicio():
    r = opt(demanda_hora=1200, demanda_p90=1400, tiempo_ciclo_min=120, flota_disponible=40)
    assert r["viable"] is False and "cobertura" in r["motivo"]
    assert r["mejor_aproximacion"]["vehiculos_requeridos"] <= 40 and r["vehiculos_requeridos"] <= 40
    assert r["buses_hora"] == 20                                   # floor(40 × 60 / 120): toda la flota


def test_limites_de_headway_sin_un_entero_posible():
    r = opt(headway_min=7.6, headway_max=7.9)
    assert r["viable"] is False and "entero" in r["motivo"] and r["buses_hora"] is None


def test_demanda_nula_da_el_servicio_minimo():
    r = opt(demanda_hora=0, demanda_p90=None)
    assert r["viable"] is True and r["buses_hora"] == 6 and r["headway_min"] == pytest.approx(10)
    assert "headway_maximo" in r["limites_activos"]


def test_restricciones_activas_y_margen():
    r = opt(demanda_hora=900, demanda_p90=1080, parametros={"beta": 0.2})
    nombres = {x["nombre"]: x for x in r["restricciones"]}
    assert {"headway_minimo", "headway_maximo", "nivel_servicio", "flota_disponible", "duracion_ciclo"} <= set(nombres)
    assert nombres["nivel_servicio"]["activa"] is True and "nivel_servicio" in r["limites_activos"]
    assert r["margen"]["un_bus_menos"]["factible"] is False
    assert r["margen"]["un_bus_mas"]["delta_total_ponderado_cop"] >= 0          # el óptimo no mejora con un bus más
    assert any("Límites que mandan" in t for t in r["explicacion"])


# ------------------------------------------------------------------ tipologías (§10.1)
def test_tipologias_sin_placas_y_reparto_de_la_flota():
    texto = O.ARCHIVO_TIPOLOGIAS.read_text(encoding="utf-8")
    assert not re.search(r"\b[A-Z]{3}\d{3}\b", texto)                 # ninguna placa en el archivo versionado
    datos = json.loads(texto)
    assert {r: sum(f["vehiculos"] for f in filas) for r, filas in datos["rutas"].items()} == {
        "SILENCIO": 137, "CRA 54": 187, "CL 72": 150}                  # = insumos_sobusa/analisis_flota.md
    t = O.tipologias_ruta("CRA 54", 79)
    assert sum(x["disponibles"] for x in t) == 79
    assert [x["codigo"] for x in t] == ["T1", "T2", "T3", "T4"]
    assert O.tipologias_ruta("RUTA X") == []


def test_tipologias_grandes_en_el_pico_y_pequenas_en_el_valle():
    tipos = O.tipologias_ruta("SILENCIO", 45)
    pico = opt(ruta="SILENCIO", demanda_hora=700, demanda_p90=850, tiempo_ciclo_min=250, flota_disponible=45,
               tipologias=tipos, factor_carga=None)
    valle = opt(ruta="SILENCIO", demanda_hora=60, demanda_p90=80, tiempo_ciclo_min=250, flota_disponible=45,
                tipologias=tipos, factor_carga=None)
    asign_pico = {a["codigo"]: a["buses_hora"] for a in pico["tipologias"]["asignacion"]}
    asign_valle = {a["codigo"]: a["buses_hora"] for a in valle["tipologias"]["asignacion"]}
    assert pico["viable"] and valle["viable"]
    assert asign_pico["T4"] > asign_valle["T4"]                        # el pico usa más buses de 72 puestos
    maximos = {a["codigo"]: a["maximo_buses_hora"] for a in valle["tipologias"]["asignacion"]}
    assert asign_valle["T1"] == maximos["T1"] and asign_valle["T2"] == maximos["T2"]   # el valle agota los pequeños
    assert valle["capacidad_ofrecida"] < pico["capacidad_ofrecida"]
    for r in (pico, valle):
        usados = sum(a["vehiculos"] for a in r["tipologias"]["asignacion"])
        assert usados == r["vehiculos_requeridos"] <= 45
        for a in r["tipologias"]["asignacion"]:
            assert a["vehiculos"] <= a["disponibles"]
    assert any("Asignación de capacidad sugerida" in t for t in pico["explicacion"])


# ------------------------------------------------------------------ escenarios (RF-008) y sensibilidad
def test_comparacion_con_la_frecuencia_actual_programada():
    r = opt(frecuencia_actual_min=4)
    c = O.comparar_actual(r, 4, 50)
    assert c["actual"]["rotulo"] == "frecuencia actual (programada)"
    assert c["actual"]["buses_hora"] == pytest.approx(15)
    assert c["actual"]["espera_media_min"] == pytest.approx(4 / 2 * 1.25, abs=1e-3)
    assert c["actual"]["vehiculos_requeridos"] == 30
    assert c["diferencia"]["buses_hora"] == pytest.approx(r["buses_hora"] - 15)
    assert c["recomendada"]["total_ponderado_cop"] == r["costo_total_ponderado_cop"]
    assert O.comparar_actual(r, None, 50) is None


def test_que_pasa_si_con_mas_demanda_y_otros_pesos():
    kw = dict(ruta="CRA 54", hora=7, demanda_hora=600, demanda_p90=720, capacidad=50, tiempo_ciclo_min=120,
              flota_disponible=80, headway_min=2, headway_max=10, factor_carga=1.0, km_ciclo=40, cv_intervalos=0.5)
    base = O.optimizar(**kw)
    mas = O.que_pasa_si(kw, {"factor_demanda": 1.5}, base)
    assert mas["resultado"]["buses_hora"] >= base["buses_hora"]
    assert mas["diferencia_frente_a_base"]["buses_hora"] == mas["resultado"]["buses_hora"] - base["buses_hora"]
    espera = O.que_pasa_si(kw, {"pesos": {"beta": 50}}, base)
    assert espera["resultado"]["buses_hora"] > base["buses_hora"]
    sin_flota = O.que_pasa_si(kw, {"flota_disponible": 5}, base)
    assert sin_flota["resultado"]["viable"] is False and sin_flota["diferencia_frente_a_base"] is None


def test_sensibilidad_cubre_pesos_nivel_de_servicio_y_demanda():
    kw = dict(ruta="CL 72", hora=7, demanda_hora=500, demanda_p90=600, capacidad=50, tiempo_ciclo_min=200,
              flota_disponible=45, headway_min=2, headway_max=10)
    s = O.sensibilidad(kw)
    assert len(s["variaciones"]) == len(O.VARIACIONES_SENSIBILIDAD) == 23
    parametros = {f["parametro"] for f in s["variaciones"]}
    assert {"peso_costo_operativo", "peso_tiempo_espera", "peso_sobreocupacion", "peso_desviacion_frecuencia",
            "nivel_servicio", "factor_demanda", "ocupacion_objetivo"} <= parametros
    assert all("buses_hora" in f or "error" in f for f in s["variaciones"])
    assert "variaciones cambian" in s["resumen"]


def test_resumen_plan_d5_por_hora():
    plan = O.resumen_plan_d5("CRA 54", "2025-03-11", modelo="E1")
    assert [h["hora"] for h in plan["horas"]] == list(range(4, 21))
    assert plan["salidas_dia"] == sum(h["salidas"] for h in plan["horas"])
    assert plan["estado_solver"] == "Optimal" and plan["costo_total_cop"] > 0
    for h in plan["horas"]:     # §10.3: ceil(ciclo / headway) con headway = 60 / salidas por hora
        if h["headway_min"]:
            assert h["vehiculos_requeridos"] == math.ceil(h["tiempo_ciclo_min"] * h["salidas"] / 60 - 1e-9)
            assert h["vehiculos_requeridos"] <= math.ceil(h["tiempo_ciclo_min"] / h["headway_min"] - 1e-9)
    assert plan["vehiculos_hora_pico"] == max(h["vehiculos_requeridos"] for h in plan["horas"])
    assert plan["definicion_vehiculos"] == O.DEFINICION_VEHICULOS_10_3


# ------------------------------------------------------------------ fuentes de la franja
def test_recomendacion_franja_usa_la_hora_el_tipo_de_dia_y_la_capacidad_gobernada():
    from datetime import date

    from app.servicios import datos

    info = datos.ruta_info("CRA 54")
    umbrales = {"ocupacion_objetivo_max": 0.85, "headway_minimo_min": 2.0, "headway_maximo_min": 10.0,
                "ocupacion_critica": 0.9, "peso_tiempo_espera": 2.0}
    r, e = O.recomendacion_franja(info, umbrales, 4, hora=11, fecha=date(2025, 3, 15), demanda_hora=1200,
                                  demanda_p90=1400)
    ctx = O.contexto_franja("CRA 54", date(2025, 3, 15), 11)
    assert ctx["tipo_dia"] == "Sábado" and {k: r["contexto_franja"][k] for k in ctx} == ctx
    # §10.1: factor de carga crítica histórico de la ruta, el tipo de día y la hora (no una constante por ruta)
    carga = O.factor_carga_franja("CRA 54", date(2025, 3, 15), 11)
    assert r["contexto_franja"]["factor_carga"] == carga and carga["dias"] >= 10
    assert e["factor_carga"] == carga["factor_carga"] == r["demanda"]["factor_carga"]
    assert O.factor_carga_franja("CRA 54", date(2025, 3, 11), 5)["factor_carga"] > O.factor_carga_franja(
        "CRA 54", date(2025, 3, 11), 11)["factor_carga"]        # la madrugada concentra más la carga
    assert e["tiempo_ciclo_min"] == ctx["tiempo_ciclo_min"]
    assert e["frecuencia_actual_min"] == ctx["frecuencia_actual_min"]
    assert r["objetivo"]["pesos"]["beta"]["fuente"] == "threshold_config v4"
    assert r["capacidad_gobernada"]["fuente"] == "catalogo" and e["capacidad"] == 50
    # ajuste local versionado del catálogo: tipología pedida > toda la ruta > flota
    umbrales |= {"capacidad_override.16.T4": 80, "capacidad_override.16.TODAS": 55}
    r, e = O.recomendacion_franja(info, umbrales, 5, hora=11, fecha=date(2025, 3, 15), demanda_hora=1200,
                                  demanda_p90=1400)
    caps = {t["codigo"]: t["capacidad"] for t in e["tipologias"]}
    assert e["capacidad"] == 55 and caps["T4"] == 80 and caps["T1"] == 55
    # una capacidad explícita en la solicitud desactiva las tipologías (escenario homogéneo)
    r, e = O.recomendacion_franja(info, umbrales, 5, hora=11, fecha=date(2025, 3, 15), demanda_hora=1200,
                                  solicitud={"capacidad": 60})
    assert e["capacidad"] == 60 and e["tipologias"] is None and r["tipologias"] is None
    # fuera del horario de D1 (4-20 h) rige el catálogo diario
    assert O.contexto_franja("CRA 54", date(2025, 3, 15), 2) == {}


# ------------------------------------------------------------------ memoria de soluciones del MILP
def test_memoria_del_milp_reutiliza_la_solucion_sin_cambiar_el_resultado(monkeypatch):
    """Una franja idéntica no vuelve a llamar a CBC y da exactamente el mismo resultado; otra franja sí lo llama, y un
    estado que depende del tiempo (corte por tiempo) no se guarda."""
    from unittest import mock

    O.limpiar_memoria_milp()
    llamado = mock.Mock(wraps=O._resolver_milp_cbc)
    monkeypatch.setattr(O, "_resolver_milp_cbc", llamado)
    a, b = opt(frecuencia_actual_min=6), opt(frecuencia_actual_min=6)
    assert llamado.call_count == 1
    sin_tiempo = {k: v for k, v in a["solver"].items() if k != "segundos"}
    assert sin_tiempo == {k: v for k, v in b["solver"].items() if k != "segundos"}
    assert {k: v for k, v in a.items() if k != "solver"} == {k: v for k, v in b.items() if k != "solver"}
    opt(frecuencia_actual_min=6, demanda_hora=700)
    assert llamado.call_count == 2
    monkeypatch.setattr(O, "_resolver_milp_cbc", mock.Mock(return_value=(None, "Not Solved", 20.0)))
    opt(demanda_hora=650)
    opt(demanda_hora=650)
    assert O._resolver_milp_cbc.call_count == 4    # franja y relajada, dos veces: «Not Solved» no se guarda
