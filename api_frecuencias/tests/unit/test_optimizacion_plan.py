"""Plan del día con el modelo activo (optimizacion.plan_dia) y gobierno de la franja (§5.1, §10.1-§10.3, §18).

- plan_dia: pronóstico horario del modelo activo para cualquier fecha con variables, parámetros de threshold_config
  como cotas del MILP (headway mínimo y máximo efectivo), explicación por hora, viabilidad, sobreoferta y memoria.
- recomendacion_franja: la espera máxima cambia la recomendación (supuesto S12), la ocupación objetivo mínima marca la
  sobreoferta y las dos líneas base de §10.3 (literal y ajustada) van con su nombre.
"""
import math
from datetime import date

import pytest

from app.servicios import datos
from app.servicios import optimizacion as O

UMBRALES = {"headway_minimo_min": 2.0, "headway_maximo_min": 10.0, "espera_max_min": 5.0,
            "ocupacion_objetivo_min": 0.65, "ocupacion_objetivo_max": 0.85}
CLAVES_HORA = {"hora", "salidas", "headway_min", "pasajeros_previstos", "pasajeros_p10", "pasajeros_p90",
               "limites_activos", "demanda_diseno", "margen", "viable", "motivo", "sobreoferta", "fuente_pronostico",
               "model_id", "calibracion_version", "headway_minimo_min", "headway_maximo_min", "maximo_salidas_headway",
               "minimo_salidas_headway", "salidas_sin_tope", "limitada_por_headway_minimo", "vehiculos_requeridos"}


def _pronostico(base=400.0, picos=None):
    """Pronóstico horario sintético {hora, p10, p50, p90} (4-20 h); `picos` = {hora: p50}."""
    picos = picos or {}
    return [{"hora": h, "p10": 0.8 * picos.get(h, base), "p50": picos.get(h, base), "p90": 1.25 * picos.get(h, base)}
            for h in range(4, 21)]


@pytest.fixture(autouse=True)
def _memoria_vacia():
    O.limpiar_cache_plan()
    yield
    O.limpiar_cache_plan()


def test_plan_dia_usa_el_pronostico_horario_del_modelo_activo():
    """D3: el plan sale del modelo ACTIVO (P10/P50/P90 de cada hora con h = 60 y sin factor intradía) y lo dice."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from app.servicios import inferencia

    plan = O.plan_dia("2025-11-19", "CRA 54", umbrales=UMBRALES, umbrales_version=None)
    activo = inferencia.modelo_activo()
    assert plan["fuente_pronostico"] == "modelo_activo" and plan["model_id"] == plan["modelo"] == activo
    assert plan["calibracion_version"] and plan["estado_solver"] == "Optimal"
    assert [h["hora"] for h in plan["horas"]] == list(range(4, 21))
    for h in plan["horas"]:
        assert CLAVES_HORA <= set(h)
        assert h["model_id"] == activo and h["fuente_pronostico"] == "modelo_activo"
        assert h["pasajeros_p10"] <= h["pasajeros_previstos"] <= h["pasajeros_p90"]
        assert h["minimo_salidas_headway"] <= h["salidas"] <= h["maximo_salidas_headway"]
    siete = next(h for h in plan["horas"] if h["hora"] == 7)
    directa = inferencia.predecir("CRA 54", datetime(2025, 11, 19, 7, tzinfo=ZoneInfo("America/Bogota")), 60,
                                  usar_nowcast=False)
    assert siete["pasajeros_previstos"] == pytest.approx(directa["pasajeros"], abs=0.01)
    assert siete["pasajeros_p90"] == pytest.approx(directa["p90"], abs=0.01)
    assert plan["salidas_dia"] == sum(h["salidas"] for h in plan["horas"])
    # fuera de 2025 también hay plan (el E12 precalculado solo cubre 2025)
    enero = O.plan_dia("2026-01-05", "SILENCIO", umbrales=UMBRALES, umbrales_version=None)
    assert enero["fuente_pronostico"] == "modelo_activo" and enero["tipo_dia"] == "Laboral"
    with pytest.raises(ValueError):
        O.plan_dia("2026-01-05", "SILENCIO", umbrales=UMBRALES, umbrales_version=None, pronostico="E12")


def test_plan_dia_toma_los_umbrales_gobernados_como_cotas_del_milp():
    """§5.1 regla de gobierno y §10.2: nmin = ceil(minutos / headway máximo efectivo), tope = floor(minutos / headway
    mínimo); cada parámetro dice su fuente (threshold_config vN o el código)."""
    pron = _pronostico()
    plan = O.plan_dia("2025-11-19", "CL 72", umbrales=UMBRALES, umbrales_version=7, pronostico_horario=pron,
                      model_id="modelo_prueba")
    assert plan["model_id"] == "modelo_prueba" and plan["umbrales_version"] == 7
    p = plan["parametros"]
    assert p["headway_minimo_min"] == {"valor": 2.0, "fuente": "threshold_config v7"}
    assert p["costo_bus_hora_cop"]["fuente"] == "código (valor por omisión)"      # la tabla de prueba no lo trae
    assert "S12" in p["headway_maximo_efectivo_min"]["fuente"] and p["elasticidad"]["valor"] == 0.5
    for h in plan["horas"]:
        m = h["minutos_operados"]
        assert h["minimo_salidas_headway"] == math.ceil(m / 10.0 - 1e-9)
        assert h["maximo_salidas_headway"] == math.floor(m / 2.0 + 1e-9)
    # un PUT /thresholds que sube el headway mínimo baja el tope y cambia el plan
    estricto = O.plan_dia("2025-11-19", "CL 72", umbrales=dict(UMBRALES, headway_minimo_min=6.0),
                          umbrales_version=8, pronostico_horario=_pronostico(picos={5: 3000.0}))
    cinco = next(h for h in estricto["horas"] if h["hora"] == 5)
    assert cinco["maximo_salidas_headway"] == math.floor(cinco["minutos_operados"] / 6.0 + 1e-9)
    assert cinco["salidas"] <= cinco["maximo_salidas_headway"] and cinco["limitada_por_headway_minimo"]
    assert cinco["viable"] is False and "headway mínimo gobernado de 6,00 min" in cinco["motivo"]
    assert 5 in estricto["horas_no_viables"] and not estricto["viable"]


def test_bajar_la_espera_maxima_cambia_el_plan():
    """D1: headway máximo efectivo = min(headway_maximo_min, 2 × espera_max_min); con 3 min de espera el plan no deja
    ninguna hora con más de 6 min entre salidas."""
    pron = _pronostico(base=150.0)
    cinco = O.plan_dia("2025-11-23", "CL 72", umbrales=UMBRALES, umbrales_version=None, pronostico_horario=pron)
    tres = O.plan_dia("2025-11-23", "CL 72", umbrales=dict(UMBRALES, espera_max_min=3.0), umbrales_version=None,
                      pronostico_horario=pron)
    assert cinco["headway_maximo_min"] == 10.0 and tres["headway_maximo_min"] == 6.0
    assert tres["salidas_dia"] > cinco["salidas_dia"]
    assert all(h["headway_min"] <= 6.0 + 0.01 for h in tres["horas"] if h["salidas"] > 0)
    assert any(h["headway_min"] > 6.0 for h in cinco["horas"] if h["salidas"] > 0)
    assert all("headway_maximo" in h["limites_activos"] for h in tres["horas"]
               if h["minutos_operados"] > 0 and h["salidas"] == h["minimo_salidas_headway"])


def test_plan_dia_marca_sobreoferta_con_su_motivo():
    """§5.1 ocupación objetivo 65 %: con demanda baja el headway máximo impone más oferta de la necesaria."""
    plan = O.plan_dia("2025-11-19", "CL 72", umbrales=UMBRALES, umbrales_version=None,
                      pronostico_horario=_pronostico(base=120.0))
    marcadas = [h for h in plan["horas"] if h["sobreoferta"]]
    assert marcadas and plan["horas_sobreoferta"] == [h["hora"] for h in marcadas]
    for h in marcadas:
        assert h["ocupacion_esperada"] < 0.65 and "65 %" in h["motivo_sobreoferta"]
        assert "espera máxima" in h["motivo_sobreoferta"] and "headway_maximo" in h["limites_activos"]
        assert h["viable"] is True                     # la sobreoferta es informativa, no hace inviable la hora
    sin_marca = O.plan_dia("2025-11-19", "CL 72", umbrales=dict(UMBRALES, ocupacion_objetivo_min=0.05),
                           umbrales_version=None, pronostico_horario=_pronostico(base=120.0))
    assert sin_marca["horas_sobreoferta"] == []


def test_plan_dia_explica_cada_hora():
    """§1 «por qué se generó»: límites activos, demanda de diseño, margen (una salida menos / más) y viabilidad."""
    plan = O.plan_dia("2025-11-19", "SILENCIO", umbrales=UMBRALES, umbrales_version=None,
                      pronostico_horario=_pronostico(base=700.0))
    for h in plan["horas"]:
        m = h["margen"]
        assert m["demanda_diseno_pax_h"] == pytest.approx(h["demanda_diseno"], abs=0.1)
        assert m["capacidad_efectiva_pax_h"] == pytest.approx(h["salidas"] * 50 * 0.85, abs=0.1)
        assert set(m) >= {"una_salida_menos", "una_salida_mas", "holgura_pax_h", "cobertura_demanda_diseno"}
        assert h["viable"] is (h["motivo"] is None)
    assert "MILP D5" in plan["formulacion"] and "modelo activo" in plan["formulacion"]


def test_plan_dia_memoria_por_modelo_calibracion_y_umbrales(monkeypatch):
    calculos = []
    original = O._calcular_plan
    monkeypatch.setattr(O, "_calcular_plan", lambda *a, **k: calculos.append(1) or original(*a, **k))
    pron = _pronostico()
    a = O.plan_dia("2025-11-19", "CL 72", umbrales=UMBRALES, umbrales_version=3, pronostico_horario=pron)
    b = O.plan_dia("2025-11-19", "CL 72", umbrales=UMBRALES, umbrales_version=3, pronostico_horario=pron)
    assert a == b and len(calculos) == 1
    O.plan_dia("2025-11-19", "CL 72", umbrales=UMBRALES, umbrales_version=4, pronostico_horario=pron)
    assert len(calculos) == 2                          # otra versión de umbrales es otro plan


def test_plan_dia_errores():
    with pytest.raises(ValueError, match="Ruta desconocida"):
        O.plan_dia("2025-11-19", "RUTA X", umbrales=UMBRALES, umbrales_version=None, pronostico_horario=_pronostico())
    with pytest.raises(ValueError, match="pronostico"):
        O.plan_dia("2025-11-19", "CL 72", umbrales=UMBRALES, umbrales_version=None, pronostico="otro")


def test_fila_plan_y_plan_desde_filas_ida_y_vuelta():
    """Lo que el ciclo persiste (origen = 'plan_dia') reconstruye el mismo plan en GET /recommendations/plan."""
    plan = O.plan_dia("2025-11-19", "CL 72", umbrales=UMBRALES, umbrales_version=2, pronostico_horario=_pronostico())
    filas = [O.fila_plan(plan, h) for h in plan["horas"]]
    assert {f["origen"] for f in filas} == {"plan_dia"} and all(f["buses_hora"] == f["detalle"]["hora_plan"]["salidas"]
                                                                for f in filas)
    for f in filas:
        f["execution_id"], f["creado_en"] = "e1", "2025-11-18T23:00:00-05:00"
    vuelta = O.plan_desde_filas(list(reversed(filas)))
    assert vuelta["horas"] == plan["horas"] and vuelta["salidas_dia"] == plan["salidas_dia"]
    assert vuelta["model_id"] == plan["model_id"] and vuelta["execution_id"] == "e1"
    # filas sin el detalle completo: se arman desde las columnas
    simples = [{k: v for k, v in f.items() if k != "detalle"} | {"detalle": {}} for f in filas]
    minimo = O.plan_desde_filas(simples)
    assert [h["salidas"] for h in minimo["horas"]] == [h["salidas"] for h in plan["horas"]]
    # el formato del ciclo diario (construir_recomendacion: detalle = {entradas, salida con hora_plan})
    ciclo = [{k: v for k, v in f.items() if k != "detalle"}
             | {"detalle": {"entradas": {"model_id": plan["model_id"], "fuente_pronostico": "modelo_activo",
                                         "salidas_dia": plan["salidas_dia"]},
                            "salida": {"buses_hora": f["buses_hora"], "hora_plan": f["detalle"]["hora_plan"]}}}
             for f in filas]
    del_ciclo = O.plan_desde_filas(ciclo)
    assert del_ciclo["horas"] == plan["horas"] and del_ciclo["modelo"] == plan["model_id"]
    assert del_ciclo["vehiculos_hora_pico"] == plan["vehiculos_hora_pico"]
    # el resumen del ciclo no trae programadas, flota ni costo: se rehacen con las horas (antes salían «—»)
    assert plan["salidas_programadas_dia"] and plan["costo_total_cop"] > 0
    assert del_ciclo["salidas_programadas_dia"] == pytest.approx(plan["salidas_programadas_dia"], abs=0.05)
    assert del_ciclo["flota_disponible"] == plan["flota_disponible"]
    assert del_ciclo["costo_total_cop"] == pytest.approx(plan["costo_total_cop"], abs=0.1)
    for nombre, valor in plan["componentes_costo_cop"].items():
        assert del_ciclo["componentes_costo_cop"][nombre] == pytest.approx(valor, abs=0.1)
    assert del_ciclo["buses_en_ruta_pico"] == plan["buses_en_ruta_pico"]
    assert del_ciclo["definicion_vehiculos"] == plan["definicion_vehiculos"] == O.DEFINICION_VEHICULOS
    assert del_ciclo["tipo_dia"] == plan["tipo_dia"] and del_ciclo["viable"] is plan["viable"]


def test_una_sola_salida_no_tiene_intervalo_y_no_es_no_viable():
    """Una hora con una sola salida (o con menos minutos operados que el headway mínimo, como SILENCIO a las 4 h del
    domingo y del festivo: 0,2 min) no tiene intervalo que verificar: no es «no viable» por eso, como en
    respuesta._problemas_intervalo, y no pide cientos de vehículos."""
    assert O._cotas_hora(0.18, 2.0, 10.0) == (1, 1)
    assert O._cotas_hora(3.0, 2.0, 2.5) == (2, 1)            # sin nivel entero de verdad: sigue siendo no viable
    assert O._cotas_hora(0.0, 2.0, 10.0) == (0, 0)
    for fecha in ("2025-11-23", "2025-12-08"):                 # domingo y festivo (Inmaculada Concepción)
        plan = O.plan_dia(fecha, "SILENCIO", umbrales=UMBRALES, umbrales_version=None,
                          pronostico_horario=_pronostico(100.0))
        assert plan["tipo_dia"] == "Domingo/festivo"
        cuatro = next(h for h in plan["horas"] if h["hora"] == 4)
        assert cuatro["minutos_operados"] < UMBRALES["headway_minimo_min"] and cuatro["salidas"] == 1
        assert cuatro["viable"] is True and cuatro["motivo"] is None and cuatro["sin_intervalo"] is True
        assert 4 not in plan["horas_no_viables"]
        assert cuatro["vehiculos_requeridos"] == math.ceil(cuatro["tiempo_ciclo_min"] / 60 - 1e-9) <= 3
        assert plan["vehiculos_hora_pico"] <= plan["flota_disponible"]
        assert all(h["sin_intervalo"] is (h["salidas"] == 1) for h in plan["horas"])


def test_vehiculos_con_el_ritmo_de_la_hora_y_su_definicion():
    """§10.3: vehículos = ceil(ciclo / headway) con headway = 60 / salidas por hora. En una hora completa es la fórmula
    literal; en una hora de apertura o cierre no se dispara por el intervalo corto. El plan dice qué mide cada cifra."""
    assert O.vehiculos_requeridos_hora(163.64, 2) == 6         # 2 salidas en 4,5 min: 6, no ceil(163,64 / 2,24) = 74
    assert O.vehiculos_requeridos_hora(200.0, 6) == math.ceil(200.0 / 10.0) == 20
    assert O.vehiculos_requeridos_hora(200.0, 0) == 0
    plan = O.plan_dia("2025-11-23", "CRA 54", umbrales=UMBRALES, umbrales_version=None,
                      pronostico_horario=_pronostico(100.0))
    for h in plan["horas"]:
        if h["salidas"]:
            assert h["vehiculos_requeridos"] == O.vehiculos_requeridos_hora(h["tiempo_ciclo_min"], h["salidas"])
        if h["minutos_operados"] == 60.0 and h["headway_min"]:
            assert h["vehiculos_requeridos"] == math.ceil(h["tiempo_ciclo_min"] / h["headway_min"] - 1e-9)
        assert h["flota_disponible"] == plan["flota_disponible"] and h["costo_hora_cop"] is not None
    assert plan["vehiculos_hora_pico"] == max(h["vehiculos_requeridos"] for h in plan["horas"])
    assert plan["vehiculos_hora_pico"] <= plan["flota_disponible"]
    assert plan["buses_en_ruta_pico"] == max(h["buses_en_ruta_max"] for h in plan["horas"])
    assert plan["buses_en_ruta_pico"] <= plan["flota_disponible"] + plan["holgura_flota"] + 1e-6
    assert "60 / salidas" in plan["definicion_vehiculos"] and "buses_en_ruta_pico" in plan["definicion_vehiculos"]
    assert plan["costo_total_cop"] == pytest.approx(sum(h["costo_hora_cop"] for h in plan["horas"]), abs=0.1)


def test_insumos_plan_es_publico_y_son_los_del_plan():
    """insumos_plan es la API pública de los insumos por hora del MILP (la respuesta compara ofertas con ellos);
    _insumos_activo queda como alias del nombre anterior."""
    assert O._insumos_activo is O.insumos_plan
    pron = _pronostico(300.0, {7: 900.0})
    tb = O.insumos_plan("2025-11-19", "CRA 54", pron)
    assert tb["hora"].tolist() == list(range(4, 21))
    assert {"hora", "ciclo", "dist", "minutos", "pax_pred", "cv_d4", "capacidad", "mu", "s"} <= set(tb.columns)
    siete = tb.set_index("hora").loc[7]
    assert siete["p50"] == 900.0 and siete["mu"] == pytest.approx(math.log(siete["factor_carga"] * 900.0))
    plan = O.plan_dia("2025-11-19", "CRA 54", umbrales=UMBRALES, umbrales_version=None, pronostico_horario=pron)
    h7 = next(h for h in plan["horas"] if h["hora"] == 7)
    assert h7["factor_carga"] == pytest.approx(siete["factor_carga"], abs=1e-4)
    assert h7["tiempo_ciclo_min"] == pytest.approx(siete["ciclo"], abs=0.01)
    # con el diccionario {hora: {p10, p50, p90}} y los parámetros gobernados: mismas filas y las cotas de cada hora
    por_hora = {h["hora"]: {"p10": h["p10"], "p50": h["p50"], "p90": h["p90"]} for h in pron}
    acotada = O.insumos_plan(date(2025, 11, 19), "CRA 54", por_hora, O.parametros_plan(UMBRALES, None))
    assert {"nmin", "tope_headway", "nmax"} <= set(acotada.columns)
    assert acotada["mu"].tolist() == pytest.approx(tb["mu"].tolist())
    assert len(O.insumos_plan("2025-03-11", "CRA 54", None, pronostico="E12")) == 17


def test_insumos_plan_sin_pronostico_usa_el_del_modelo_activo(monkeypatch):
    """Sin pronóstico, insumos_plan toma el del modelo activo, el mismo de plan_dia (memoria de 2 min)."""
    pedidos = []

    def memorizado(fecha, ruta, model_id):
        pedidos.append((fecha, ruta, model_id))
        return _pronostico(250.0), "modelo", "v2"

    monkeypatch.setattr(O, "_pronostico_memorizado", memorizado)
    tb = O.insumos_plan("2025-11-19", "CL 72", None)
    assert pedidos == [(date(2025, 11, 19), "CL 72", None)]
    assert tb["p50"].tolist() == [250.0] * 17


# ------------------------------------------------------------------ franja de §10.2
def _franja(umbrales, demanda=500.0, **kw):
    info = datos.ruta_info("CL 72")
    solicitud = {"flota_disponible": 200}
    r, _ = O.recomendacion_franja(info, umbrales, None, hora=11, fecha=date(2025, 11, 19), demanda_hora=demanda,
                                  demanda_p90=1.2 * demanda, demanda_p10=0.8 * demanda, solicitud=solicitud,
                                  usar_tipologias=False, **kw)
    return r


def test_bajar_la_espera_maxima_cambia_la_recomendacion_de_franja():
    """D1 / S12: con espera_max_min = 5 el headway máximo es 10 min; con 3 min pasa a 6 min y la recomendación sube."""
    cinco, tres = _franja(UMBRALES), _franja(dict(UMBRALES, espera_max_min=3.0))
    assert cinco["parametros"]["headway_max"] == 10.0 and tres["parametros"]["headway_max"] == 6.0
    assert cinco["headway_min"] == 10.0 and tres["headway_min"] <= 6.0
    assert tres["buses_hora"] > cinco["buses_hora"]
    hmax = tres["contexto_franja"]["headway_maximo"]
    assert hmax["manda"] == "espera_max_min" and hmax["dos_por_espera_min"] == 6.0
    # una espera que pide menos que el headway mínimo: manda el mínimo y se dice
    corta = O.headway_maximo_efectivo(dict(UMBRALES, espera_max_min=0.5))
    assert corta["valor"] == 2.0 and corta["manda"] == "headway_minimo_min" and corta["nota"]


def test_sobreoferta_en_la_franja():
    """§5.1: la ocupación objetivo mínima (65 %) se usa; bajo ese valor la franja sale marcada con su motivo."""
    baja = _franja(UMBRALES, demanda=300.0)
    assert baja["viable"] and baja["sobreoferta"] is True and "65 %" in baja["motivo_sobreoferta"]
    fila = next(x for x in baja["restricciones"] if x["nombre"] == "ocupacion_objetivo_minima")
    assert fila["activa"] and fila["valor"] < 0.65 and "ocupacion_objetivo_minima" not in baja["limites_activos"]
    assert any(t.startswith("Sobreoferta") for t in baja["explicacion"])
    alta = _franja(UMBRALES, demanda=1500.0)
    assert alta["sobreoferta"] is False and alta["motivo_sobreoferta"] is None


def test_lineas_base_literal_y_ajustada_con_su_nombre():
    """§10.3 literal: ceil(demanda puntual / capacidad efectiva) con factor 1; la ajustada usa la carga crítica."""
    r = O.optimizar("SILENCIO", 7, 669, demanda_p90=759, demanda_p10=600, tiempo_ciclo_min=260, flota_disponible=45,
                    frecuencia_actual_min=7.4)
    literal, ajustada = r["linea_base_10_3_literal"], r["linea_base_10_3"]
    assert literal["nombre"].startswith("§10.3 literal") and ajustada["nombre"].startswith("§10.3 ajustada")
    assert literal["buses_hora"] == math.ceil(669 / 42.5 - 1e-9) == 16 and literal["factor_carga"] == 1.0
    assert ajustada["buses_hora"] == math.ceil(0.410 * 759 / 42.5 - 1e-9) and ajustada["criterio_demanda"] == "p90"
    assert any("literal (factor 1, demanda puntual)" in t for t in r["explicacion"])
