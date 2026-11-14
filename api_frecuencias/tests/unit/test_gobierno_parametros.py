"""Gobierno de los parámetros del plan y de la operación (§5.1 «regla de gobierno», §3.1 «Gestión operacional», §6.1,
§6.2, §10.2), sin base de datos.

- Tarifa, elasticidad y suavidad del MILP de D5 (PARAMETROS_PLAN) se leen de threshold_config cuando la versión los
  trae; sin ellos el plan es exactamente el de D5 (paridad), y el MILP del plan no lee ninguna clave de param_d5 que
  no esté gobernada.
- Flota disponible y tiempo de ciclo (app/servicios/flota_ciclo.py): claves, prioridad, validación y efecto en la
  franja de §10.2 y en el plan del día.
- Headway vigente de rutas.frecuenciadespachos y su diferencia con el recomendado, en la franja y en cada hora del plan,
  con la fuente real del valor: la exportación empaquetada o, en modo integrado, la tabla rutas de la base de Extreme.
- La tolerancia de los datos tardíos de la calidad (OPOR-001) es el umbral de §5.1 «datos atrasados» de
  threshold_config, el mismo de ALT-009.
"""
from datetime import date

import pytest

from app.servicios import datos
from app.servicios import flota_ciclo as F
from app.servicios import optimizacion as O
from app.servicios.motor_d5 import comun as C

UMBRALES = {"headway_minimo_min": 2.0, "headway_maximo_min": 10.0, "espera_max_min": 5.0,
            "ocupacion_objetivo_min": 0.65, "ocupacion_objetivo_max": 0.85, "ocupacion_critica": 0.9}
FECHA = "2025-11-19"                      # miércoles laboral con variables del modelo
CLAVES_MILP = {"COSTO_BUS_HORA", "COSTO_KM", "VALOR_TIEMPO_ESPERA", "PENALIDAD_SOBRECARGA"} | {
    clave for clave, _d in O.PARAMETROS_PLAN.values()}


def _pronostico(base=400.0, picos=None):
    picos = picos or {}
    return [{"hora": h, "p10": 0.8 * picos.get(h, base), "p50": picos.get(h, base), "p90": 1.25 * picos.get(h, base)}
            for h in range(4, 21)]


def _plan(umbrales, ruta="CRA 54", version=None, pronostico=None):
    return O.plan_dia(FECHA, ruta, umbrales=umbrales, umbrales_version=version,
                      pronostico_horario=pronostico or _pronostico(900.0, {6: 1700.0, 7: 1800.0, 17: 1500.0}))


@pytest.fixture(autouse=True)
def _memoria_vacia():
    O.limpiar_cache_plan()
    yield
    O.limpiar_cache_plan()


# ------------------------------------------------------------------ parámetros del plan en threshold_config
def test_parametros_del_plan_por_omision_son_los_de_d5():
    d5 = C.param_d5(fuente=True)
    gob = O.parametros_plan(UMBRALES, None)
    for nombre, (clave, descripcion) in O.PARAMETROS_PLAN.items():
        assert gob[nombre]["valor"] == float(d5[clave]) and gob[nombre]["fuente"].startswith(O.FUENTE_D5)
        assert descripcion and O.descripcion_parametro(nombre) == descripcion
    assert gob["tarifa_cop"]["valor"] == 3182.0 and gob["elasticidad"]["valor"] == 0.5
    assert (gob["delta_suavidad"]["valor"], gob["hora_inicio_suavidad"]["valor"]) == (6.0, 7.0)
    assert O.descripcion_parametro("peso_tiempo_espera") == O.PARAMETROS_OBJETIVO["peso_tiempo_espera"][1]
    assert O.descripcion_parametro("no_existe") is None


def test_parametros_del_plan_salen_de_la_version_vigente():
    u = dict(UMBRALES, tarifa_cop=2900, elasticidad=0.4, delta_suavidad=3, hora_inicio_suavidad=6)
    gob = O.parametros_plan(u, 12)
    assert gob["tarifa_cop"] == {"valor": 2900.0, "fuente": "threshold_config v12"}
    assert gob["elasticidad"] == {"valor": 0.4, "fuente": "threshold_config v12"}
    assert gob["delta_suavidad"]["valor"] == 3.0 and gob["hora_inicio_suavidad"]["valor"] == 6.0
    p = O._p_milp(gob, True)
    assert (p["TARIFA"], p["ELASTICIDAD"], p["DELTA"], p["HORA_INICIO_SUAVIDAD"]) == (2900.0, 0.4, 3.0, 6.0)
    # con los supuestos de D5 (fuente_costos=False) la tarifa es la de D5, como el bus-hora y el km
    supuestos = O.parametros_plan(u, 12, fuente_costos=False)
    assert supuestos["tarifa_cop"]["valor"] == float(C.param_d5(fuente=False)["TARIFA"])
    assert supuestos["delta_suavidad"]["valor"] == 3.0


def test_sin_version_nueva_el_milp_recibe_exactamente_los_parametros_de_d5():
    """Paridad: con los valores por omisión (o sembrados por la migración 0010) el MILP recibe las mismas cifras de
    param_d5 para la tarifa, la elasticidad y la suavidad, así que el plan no cambia."""
    d5 = C.param_d5(fuente=True)
    sin = O._p_milp(O.parametros_plan(UMBRALES, None), True)
    sembrados = dict(UMBRALES, tarifa_cop=3182.0, elasticidad=0.5, delta_suavidad=6, hora_inicio_suavidad=7)
    con = O._p_milp(O.parametros_plan(sembrados, 3), True)
    for clave, _d in O.PARAMETROS_PLAN.values():
        assert sin[clave] == con[clave] == d5[clave]
    a, b = _plan(UMBRALES), _plan(sembrados, version=3)
    assert [h["salidas"] for h in a["horas"]] == [h["salidas"] for h in b["horas"]]
    assert a["componentes_costo_cop"] == b["componentes_costo_cop"]


def test_el_milp_del_plan_solo_lee_claves_gobernadas():
    """§5.1 «todos los umbrales se guardan en PostgreSQL»: al resolver el plan, el MILP de D5 lee solo los costos de
    §10.2 y los parámetros de PARAMETROS_PLAN, y cada uno llega de threshold_config (no queda ninguno del código)."""
    from app.servicios.motor_d5 import milp, plan_base

    u = dict(UMBRALES, tarifa_cop=3001.0, elasticidad=0.45, delta_suavidad=5.5, hora_inicio_suavidad=8,
             costo_bus_hora_cop=25000.0, costo_km_cop=1900.0, valor_tiempo_espera_cop_h=6500.0,
             penalidad_sobreocupacion_cop=9000.0)
    gob = O.parametros_plan(u, 4)
    leidas = set()

    class Registro(dict):
        def __getitem__(self, clave):
            leidas.add(clave)
            return super().__getitem__(clave)

    p = Registro(O._p_milp(gob, True))
    tb = O._con_cotas(O.insumos_plan(FECHA, "CRA 54", _pronostico()).reset_index(drop=True), gob)
    x, estado, _h, _c = milp.resolver_dia_detalle(plan_base.entradas_d5(tb), tb["ciclo"].values,
                                                  float(tb["flota_disp"].iloc[0]), p)
    assert estado == "Optimal" and len(x) == 17
    assert leidas and leidas <= CLAVES_MILP, leidas - CLAVES_MILP
    esperado = {"COSTO_BUS_HORA": 25000.0, "COSTO_KM": 1900.0, "VALOR_TIEMPO_ESPERA": 6500.0,
                "PENALIDAD_SOBRECARGA": 9000.0, "TARIFA": 3001.0, "ELASTICIDAD": 0.45, "DELTA": 5.5,
                "HORA_INICIO_SUAVIDAD": 8.0}
    assert {k: dict.__getitem__(p, k) for k in esperado} == esperado
    assert all(gob[n]["fuente"] == "threshold_config v4" for n in O.PARAMETROS_PLAN)


def test_cambiar_la_suavidad_la_tarifa_o_la_elasticidad_cambia_el_plan():
    base = _plan(UMBRALES)
    suave = _plan(dict(UMBRALES, delta_suavidad=2), version=5)
    salidas = [h["salidas"] for h in suave["horas"]]
    assert salidas != [h["salidas"] for h in base["horas"]]
    assert suave["parametros"]["delta_suavidad"] == {"valor": 2.0, "fuente": "threshold_config v5"}
    minutos = [h["minutos_operados"] for h in suave["horas"]]
    for i in range(1, 17):          # la suavidad rige desde la transición 6 -> 7 h, con delta 2 salidas por hora
        if suave["horas"][i]["hora"] >= 7 and minutos[i] > 0 and minutos[i - 1] > 0:
            cambio = salidas[i] / (minutos[i] / 60) - salidas[i - 1] / (minutos[i - 1] / 60)
            assert abs(cambio) <= 2 + 1e-6, (suave["horas"][i]["hora"], cambio)
    sin_ingreso = _plan(dict(UMBRALES, elasticidad=0), version=6)
    assert sin_ingreso["componentes_costo_cop"]["ingreso"] == 0.0
    assert sin_ingreso["parametros"]["elasticidad"]["fuente"] == "threshold_config v6"
    tarifa_cero = _plan(dict(UMBRALES, tarifa_cop=0), version=7)
    assert tarifa_cero["componentes_costo_cop"]["ingreso"] == 0.0
    assert [h["salidas"] for h in tarifa_cero["horas"]] == [h["salidas"] for h in sin_ingreso["horas"]]
    tarde = _plan(dict(UMBRALES, hora_inicio_suavidad=21), version=8)
    assert tarde["parametros"]["hora_inicio_suavidad"]["valor"] == 21.0 and "suavidad" not in {
        a for h in tarde["horas"] for a in h["limites_activos"]}


def test_una_suavidad_gobernada_sin_solucion_no_entrega_un_plan():
    """Con la suavidad de D5 el MILP del plan siempre tiene solución (la flota tiene holgura), pero una suavidad
    gobernada más estricta puede dejarlo sin solución: un delta de 0,05 salidas/h, o la suavidad desde la transición
    de las 4 h un domingo de SILENCIO (0,18 min operados a las 4 h: una salida es un ritmo de 333 salidas/h). Antes el
    plan salía con estado «Infeasible» y horas «viables», o fallaba dentro del motor («334 is not in list»); ahora no
    hay plan y el ValueError dice qué parámetros revisar (el ciclo lo registra como advertencia de la ruta)."""
    domingo = "2025-11-16"
    for umbrales, version in ((dict(UMBRALES, delta_suavidad=0.05), 40), (dict(UMBRALES, hora_inicio_suavidad=5), 41)):
        with pytest.raises(ValueError, match="sin un plan factible") as error:
            O.plan_dia(domingo, "SILENCIO", umbrales=umbrales, umbrales_version=version,
                       pronostico_horario=_pronostico())
        assert "delta_suavidad" in str(error.value) and "PUT /api/v1/thresholds" in str(error.value)
    # con la suavidad de D5 el mismo domingo sí tiene plan
    plan = O.plan_dia(domingo, "SILENCIO", umbrales=UMBRALES, umbrales_version=42, pronostico_horario=_pronostico())
    assert plan["estado_solver"] == "Optimal" and plan["tipo_dia"] == "Domingo/festivo"


@pytest.mark.parametrize("valores", [{"elasticidad": 1.2}, {"elasticidad": -0.1}, {"delta_suavidad": 0},
                                     {"delta_suavidad": -3}, {"hora_inicio_suavidad": 3},
                                     {"hora_inicio_suavidad": 4}, {"hora_inicio_suavidad": 5},
                                     {"hora_inicio_suavidad": 7.5}, {"hora_inicio_suavidad": 22},
                                     {"tarifa_cop": -1}, {"tarifa_cop": "mucho"}])
def test_parametros_del_plan_invalidos(valores):
    with pytest.raises(ValueError):
        O.validar_parametros_plan(valores)


def test_parametros_del_plan_validos():
    O.validar_parametros_plan({"elasticidad": 0, "delta_suavidad": 0.5, "hora_inicio_suavidad": 21,
                               "tarifa_cop": 0, "ocupacion_critica": 0.9})
    O.validar_parametros_plan({"elasticidad": 1, "hora_inicio_suavidad": 6.0})


# ------------------------------------------------------------------ flota y tiempo de ciclo gobernados
def test_claves_de_flota_y_ciclo():
    assert F.clave_flota(16, "Laboral") == "flota_override.16.LABORAL"
    assert F.clave_flota("2") == "flota_override.2.TODOS"
    assert F.clave_ciclo(21, "Domingo/festivo", 7) == "ciclo_override.21.DOMINGO_FESTIVO.7"
    assert F.clave_ciclo(21, "sabado") == "ciclo_override.21.SABADO.TODAS"
    for malo in ({"tipo_dia": "Lunes"}, {"hora": 3}, {"hora": 21}):
        with pytest.raises(ValueError):
            F.clave_ciclo(2, **malo)
    assert F.partes("ciclo_override.16.LABORAL.TODAS") == ("tiempo_ciclo_min", 16, "LABORAL", "TODAS")
    assert F.partes("flota_override.16.SABADO") == ("flota", 16, "SABADO", None)
    for malo in ("flota_override.16", "flota_override.x.LABORAL", "ciclo_override.16.LABORAL.25",
                 "ciclo_override.16.LUNES.7", "capacidad_override.2.TODAS", "flota_override.16.LABORAL.7"):
        assert F.partes(malo) is None, malo


@pytest.mark.parametrize(("parametro", "valor", "esperado"), [("flota", 40, 40), ("flota", 40.0, 40),
                                                              ("tiempo_ciclo_min", 250, 250.0),
                                                              ("tiempo_ciclo_min", "180.5", 180.5)])
def test_valor_valido(parametro, valor, esperado):
    assert F.valor_valido(parametro, valor) == esperado


@pytest.mark.parametrize(("parametro", "valor"), [("flota", 0), ("flota", 40.5), ("flota", 5000), ("flota", "x"),
                                                  ("tiempo_ciclo_min", 5), ("tiempo_ciclo_min", 900),
                                                  ("tiempo_ciclo_min", float("nan")), ("tiempo_ciclo_min", None)])
def test_valor_invalido(parametro, valor):
    with pytest.raises(ValueError):
        F.valor_valido(parametro, valor)


def test_ajustes_vigentes_prioridad_y_valores_invalidos_ignorados(caplog):
    umbrales = {"flota_override.16.TODOS": 70, "flota_override.16.LABORAL": 60, "flota_override.2.SABADO": 0,
                "ciclo_override.16.LABORAL.7": 300, "ciclo_override.16.LABORAL.TODAS": 260,
                "ciclo_override.16.TODOS.8": 240, "ciclo_override.16.TODOS.TODAS": 230,
                "ciclo_override.16.TODOS.99": 200, "ocupacion_critica": 0.9}
    aj = F.ajustes(umbrales)
    assert "flota_override.2.SABADO" not in aj and "ciclo_override.16.TODOS.99" not in aj
    assert "ignorado" in caplog.text
    laboral_7 = F.de_la_franja(16, "Laboral", 7, umbrales, 11)
    assert laboral_7["flota_disponible"] == {"valor": 60, "fuente": "ajuste_local",
                                             "clave": "flota_override.16.LABORAL", "umbrales_version": 11}
    assert laboral_7["tiempo_ciclo_min"]["clave"] == "ciclo_override.16.LABORAL.7"
    assert F.de_la_franja(16, "Laboral", 8, umbrales, 11)["tiempo_ciclo_min"]["valor"] == 260   # el tipo de día manda
    sabado_8 = F.de_la_franja(16, "Sábado", 8, umbrales, 11)
    assert sabado_8["flota_disponible"]["valor"] == 70 and sabado_8["tiempo_ciclo_min"]["valor"] == 240
    assert F.de_la_franja(16, "Sábado", 22, umbrales, 11)["tiempo_ciclo_min"]["valor"] == 230   # fuera de 4..20
    assert F.de_la_franja(2, "Laboral", 7, umbrales, 11) == {} and F.de_la_franja(None, "Laboral", 7, umbrales, 1) == {}
    dia = F.del_dia(16, "Laboral", umbrales, 11)
    assert dia["flota"]["valor"] == 60 and set(dia["ciclo"]) == set(F.HORAS)
    assert dia["ciclo"][7]["valor"] == 300 and dia["ciclo"][9]["valor"] == 260
    assert F.del_dia(21, "Laboral", umbrales, 11) is None and F.del_dia(16, "Laboral", {}, None) is None


def test_validar_ajustes_de_un_cambio_de_umbrales():
    F.validar_ajustes({"flota_override.16.LABORAL": 60, "ocupacion_critica": 0.9})
    for malo in ({"flota_override.16.LABORAL": 0}, {"ciclo_override.16.LABORAL.7": 5},
                 {"flota_override.16.LUNES": 40}):
        with pytest.raises(ValueError):
            F.validar_ajustes(malo)


def test_vista_vigente_con_el_dato_empaquetado_y_el_ajuste():
    p = datos.parametros_operativos("CRA 54", "Laboral").set_index("hora")
    sin = F.vigente(16, "Laboral", umbrales={}, umbrales_version=None)
    (ruta,) = sin
    (laboral,) = ruta["por_tipo_dia"]
    assert (ruta["ruta"], ruta["idruta"], laboral["tipo_dia"]) == ("CRA 54", 16, "Laboral")
    assert laboral["flota"] == laboral["flota_catalogo"] == int(p["flota"].max())
    assert laboral["flota_fuente"] == "catalogo"
    assert [h["hora"] for h in laboral["horas"]] == list(range(4, 21))
    assert laboral["horas"][3]["tiempo_ciclo_min"] == round(float(p.loc[7, "tiempo_ciclo_min"]), 2)
    con = F.vigente(16, None, umbrales={"flota_override.16.LABORAL": 60, "ciclo_override.16.TODOS.7": 300},
                    umbrales_version=21)[0]
    tipos = {t["tipo_dia"]: t for t in con["por_tipo_dia"]}
    assert set(tipos) == {"Laboral", "Sábado", "Domingo/festivo"} and con["umbrales_version"] == 21
    assert (tipos["Laboral"]["flota"], tipos["Laboral"]["flota_fuente"]) == (60, "ajuste_local")
    assert tipos["Sábado"]["flota_fuente"] == "catalogo"
    assert all(t["horas"][3]["tiempo_ciclo_min"] == 300 and t["horas"][3]["fuente"] == "ajuste_local"
               for t in tipos.values())
    assert con["ajustes"] == {"ciclo_override.16.TODOS.7": 300.0, "flota_override.16.LABORAL": 60}
    assert len(F.vigente(None, None, umbrales={}, umbrales_version=None)) == 3
    with pytest.raises(KeyError):
        F.vigente(999, None, umbrales={}, umbrales_version=None)


def test_fijar_valida_antes_de_tocar_la_base():
    class SinBase:
        def __getattr__(self, nombre):
            raise AssertionError("no debía llegar a la base")

    casos = [((16, "Laboral", None, {}, "x", "motivo"), ValueError),
             ((16, "Laboral", 7, {"flota": 40}, "x", "motivo"), ValueError),
             ((16, "Laboral", None, {"otro": 1}, "x", "motivo"), ValueError),
             ((16, "Laboral", None, {"flota": 0}, "x", "motivo"), ValueError),
             ((16, "Laboral", None, {"flota": 40}, "x", " "), ValueError),
             ((999, "Laboral", None, {"flota": 40}, "x", "motivo"), KeyError)]
    for argumentos, error in casos:
        with pytest.raises(error):
            F.fijar(SinBase(), *argumentos)


def test_la_flota_gobernada_cambia_la_viabilidad_de_la_franja():
    """La franja de §10.2 usa la flota y el ciclo del ajuste vigente: CRA 54 a las 7 h deja de ser viable con 40
    vehículos y con un ciclo de 150 min pide menos vehículos."""
    info = datos.ruta_info("CRA 54")

    def franja(umbrales):
        return O.recomendacion_franja(info, umbrales, 30, hora=7, fecha=date(2025, 3, 4), demanda_hora=1000,
                                      demanda_p90=1180, demanda_p10=850)

    base, entradas = franja(UMBRALES)
    assert base["viable"] and entradas["flota_disponible"] == 79 and "ajuste_operativo" not in base["contexto_franja"]
    corta, entradas = franja(dict(UMBRALES, **{"flota_override.16.LABORAL": 40}))
    assert entradas["flota_disponible"] == 40 and corta["contexto_franja"]["flota_disponible"] == 40
    assert corta["viable"] is False and "40 vehículos" in corta["motivo"]
    ajuste = corta["contexto_franja"]["ajuste_operativo"]["flota_disponible"]
    assert (ajuste["clave"], ajuste["umbrales_version"]) == ("flota_override.16.LABORAL", 30)
    rapido, entradas = franja(dict(UMBRALES, **{"ciclo_override.16.LABORAL.7": 150}))
    assert entradas["tiempo_ciclo_min"] == 150 and rapido["vehiculos_requeridos"] < base["vehiculos_requeridos"]
    sabado, entradas = franja(dict(UMBRALES, **{"flota_override.16.SABADO": 40}))     # otro tipo de día: no aplica
    assert entradas["flota_disponible"] == 79 and sabado["buses_hora"] == base["buses_hora"]


def test_la_flota_y_el_ciclo_gobernados_cambian_el_plan_del_dia():
    base = _plan(UMBRALES)
    assert base["flota_y_ciclo"]["flota_disponible"]["fuente"] == O.FUENTE_FLOTA_CICLO
    corta = _plan(dict(UMBRALES, **{"flota_override.16.TODOS": 55, "ciclo_override.16.LABORAL.7": 300}), version=9)
    assert corta["flota_disponible"] == 55 and all(h["flota_disponible"] == 55 for h in corta["horas"])
    assert corta["buses_en_ruta_pico"] <= 55 + corta["holgura_flota"] + 1e-6 < base["buses_en_ruta_pico"]
    assert [h["salidas"] for h in corta["horas"]] != [h["salidas"] for h in base["horas"]]
    siete = next(h for h in corta["horas"] if h["hora"] == 7)
    assert siete["tiempo_ciclo_min"] == 300.0
    fyc = corta["flota_y_ciclo"]
    assert fyc["flota_disponible"] == {"valor": 55.0, "fuente": "ajuste_local", "clave": "flota_override.16.TODOS"}
    assert fyc["tiempo_ciclo_min"]["horas_con_ajuste_local"] == {"7": 300.0}
    assert fyc["tiempo_ciclo_min"]["claves"] == ["ciclo_override.16.LABORAL.7"]
    # el ajuste de un domingo no toca el plan de un miércoles
    otro = _plan(dict(UMBRALES, **{"flota_override.16.DOMINGO_FESTIVO": 20}), version=10)
    assert [h["salidas"] for h in otro["horas"]] == [h["salidas"] for h in base["horas"]]


def test_la_capacidad_gobernada_tambien_rige_el_plan_del_dia():
    """La capacidad por bus de toda la ruta (PUT /catalogos/capacidad, la misma que usa la franja) rige también el plan
    del día: cada hora la usa, el plan dice su fuente y la respuesta del reto compara ofertas con ella."""
    from app.servicios import respuesta

    base = _plan(UMBRALES)
    assert base["flota_y_ciclo"]["capacidad_por_bus"] == {"valor": 50.0, "fuente": O.FUENTE_FLOTA_CICLO,
                                                          "clave": None}
    umbrales = dict(UMBRALES, **{"capacidad_override.16.TODAS": 30})
    chica = _plan(umbrales, version=12)
    assert chica["flota_y_ciclo"]["capacidad_por_bus"] == {"valor": 30.0, "fuente": "ajuste_local",
                                                           "clave": "capacidad_override.16.TODAS"}
    assert all(h["capacidad_efectiva"] == pytest.approx(h["salidas"] * 30 * 0.85, abs=0.1) for h in chica["horas"])
    assert sum(h["salidas"] for h in chica["horas"]) > sum(h["salidas"] for h in base["horas"])
    tipologia = _plan(dict(UMBRALES, **{"capacidad_override.16.BUSETA": 30}), version=13)   # solo una tipología
    assert tipologia["flota_y_ciclo"]["capacidad_por_bus"]["fuente"] == O.FUENTE_FLOTA_CICLO
    tb = respuesta._tabla_comparacion(chica, "CRA 54", date(2025, 11, 19), umbrales, 12, "modelo_activo")
    assert set(tb["capacidad"]) == {30.0}
    assert respuesta._capacidad_del_plan({}, 50.0) == 50.0


def test_el_plan_e12_tambien_usa_la_flota_gobernada():
    plan = O.plan_dia("2025-03-11", "CRA 54", umbrales=dict(UMBRALES, **{"flota_override.16.LABORAL": 50}),
                      umbrales_version=2, pronostico="E12")
    assert plan["flota_disponible"] == 50 and plan["flota_y_ciclo"]["flota_disponible"]["fuente"] == "ajuste_local"
    assert plan["flota_y_ciclo"]["tiempo_ciclo_min"]["fuente"] == O.FUENTE_FLOTA_CICLO_E12


# ------------------------------------------------------------------ headway vigente de rutas.frecuenciadespachos
def test_headway_vigente_de_frecuenciadespachos():
    assert O.frecuenciadespachos_min(datos.ruta_info("SILENCIO")) == 5.0
    for valor in (None, "", "x", 0, -2, float("inf")):
        assert O.frecuenciadespachos_min({"frecuenciadespachos_tabla_rutas": valor}) is None
    assert O.frecuenciadespachos_min({"frecuenciadespachos_tabla_rutas": "7,5"}) == 7.5
    assert O.comparacion_frecuenciadespachos(3.53, 5.0) == {"frecuenciadespachos_min": 5.0,
                                                             "diferencia_frecuenciadespachos_min": -1.47,
                                                             "cambio_frecuenciadespachos": "reducir_intervalo"}
    assert O.comparacion_frecuenciadespachos(10.0, 5.0)["cambio_frecuenciadespachos"] == "ampliar_intervalo"
    assert O.comparacion_frecuenciadespachos(None, 5.0)["diferencia_frecuenciadespachos_min"] is None
    assert O.comparacion_frecuenciadespachos(4.0, None)["diferencia_frecuenciadespachos_min"] is None


def test_la_franja_compara_con_frecuenciadespachos_y_conserva_el_intervalo_programado():
    info = datos.ruta_info("CL 72")
    r, _ = O.recomendacion_franja(info, UMBRALES, None, hora=11, fecha=date(2025, 11, 19), demanda_hora=500,
                                  demanda_p90=600, demanda_p10=400, solicitud={"flota_disponible": 200},
                                  usar_tipologias=False)
    assert r["viable"] and r["frecuenciadespachos_min"] == 5.0
    assert r["diferencia_frecuenciadespachos_min"] == round(r["headway_min"] - 5.0, 2)
    assert r["cambio_frecuenciadespachos"] in ("reducir_intervalo", "ampliar_intervalo", "mantener")
    assert r["fuente_frecuenciadespachos"] == O.FUENTE_FRECUENCIADESPACHOS
    assert r["diferencia_min"] == pytest.approx(r["headway_min"] - r["frecuencia_actual_min"], abs=0.011)   # sigue
    assert any("rutas.frecuenciadespachos" in t for t in r["explicacion"])
    no_viable, _ = O.recomendacion_franja(info, dict(UMBRALES, headway_minimo_min=30, headway_maximo_min=30,
                                                     espera_max_min=15), None, hora=7, fecha=date(2025, 11, 19),
                                          demanda_hora=3000, demanda_p90=3500)
    assert no_viable["viable"] is False and no_viable["frecuenciadespachos_min"] == 5.0
    assert no_viable["diferencia_frecuenciadespachos_min"] is None and no_viable["diferencia_min"] is None


def test_cada_hora_del_plan_compara_con_frecuenciadespachos_y_se_persiste():
    plan = _plan(UMBRALES, ruta="SILENCIO", version=2)
    assert plan["frecuenciadespachos_min"] == 5.0 and "rutas.frecuenciadespachos" in plan["fuente_frecuenciadespachos"]
    for h in plan["horas"]:
        assert h["frecuenciadespachos_min"] == 5.0
        if h["headway_min"] is None:
            assert h["diferencia_frecuenciadespachos_min"] is None
        else:
            assert h["diferencia_frecuenciadespachos_min"] == round(h["headway_min"] - 5.0, 2)
    filas = [O.fila_plan(plan, h) for h in plan["horas"]]
    assert all(f["frecuenciadespachos_min"] == 5.0 for f in filas)
    assert [f["diferencia_frecuenciadespachos_min"] for f in filas] == [
        h["diferencia_frecuenciadespachos_min"] for h in plan["horas"]]
    from app.servicios import ejecucion

    fila = ejecucion._fila_plan(plan["horas"][5])
    assert fila["frecuenciadespachos_min"] == 5.0 and "diferencia_frecuenciadespachos_min" in fila
    resumen = ejecucion._parametros_del_plan(plan)
    assert resumen["tarifa_cop"] == {"valor": 3182.0, "fuente": plan["parametros"]["tarifa_cop"]["fuente"]}
    assert ejecucion._parametros_del_plan({}) is None


class _FuenteConRutas:
    """Fuente en modo integrado cuya tabla rutas trae `filas` (fuentes.frecuencias_despacho la lee con este método)."""

    def __init__(self, filas):
        self.filas, self._motor = filas, object()

    def _engine(self):
        return self._motor

    def leer_contexto(self, nombre):
        assert nombre == "frecuencias"
        import pandas as pd

        return pd.DataFrame(self.filas)


def _modo_integrado(monkeypatch, ruta: str, frecuencia):
    """datos.ruta_info en modo integrado: la tabla rutas de la fuente trae `frecuencia` para `ruta` (None = la fuente
    responde pero no trae valor para la ruta, así que rige el catálogo empaquetado)."""
    from app.servicios import fuentes, segmentos

    idruta = next(int(r["idruta"]) for r in datos.catalogo_rutas() if r["ruta"] == ruta)
    monkeypatch.setattr(segmentos, "fuente_configurada", lambda: True)
    monkeypatch.setattr(segmentos, "fuente",
                        lambda motor=None: _FuenteConRutas([{"idruta": idruta, "frecuenciadespachos": frecuencia}]))
    fuentes.limpiar_frecuencias()


@pytest.fixture
def _sin_frecuencias_en_memoria():
    from app.servicios import fuentes

    fuentes.limpiar_frecuencias()
    yield
    fuentes.limpiar_frecuencias()


def test_la_fuente_del_headway_vigente_de_la_franja_es_la_real(monkeypatch, _sin_frecuencias_en_memoria):
    """(j) La franja dice de dónde salió el headway vigente: la exportación empaquetada en modo offline o cuando la
    fuente no trae valor para la ruta, y la tabla rutas de la base de Extreme cuando el valor salió de ahí."""
    def franja():
        r, _ = O.recomendacion_franja(datos.ruta_info("CL 72"), UMBRALES, None, hora=11, fecha=date(2025, 11, 19),
                                      demanda_hora=500, demanda_p90=600, demanda_p10=400,
                                      solicitud={"flota_disponible": 200}, usar_tipologias=False)
        return r

    offline = franja()
    assert offline["frecuenciadespachos_min"] == 5.0
    assert offline["fuente_frecuenciadespachos"] == O.FUENTE_FRECUENCIADESPACHOS
    _modo_integrado(monkeypatch, "CL 72", "12")
    en_vivo = franja()
    assert en_vivo["frecuenciadespachos_min"] == 12.0
    assert en_vivo["fuente_frecuenciadespachos"] == O.FUENTE_FRECUENCIADESPACHOS_EN_VIVO
    assert "rutas.frecuenciadespachos" in en_vivo["fuente_frecuenciadespachos"]
    assert "exportación empaquetada" not in en_vivo["fuente_frecuenciadespachos"]
    assert en_vivo["diferencia_frecuenciadespachos_min"] == round(en_vivo["headway_min"] - 12.0, 2)
    _modo_integrado(monkeypatch, "CL 72", None)                       # la fuente no trae valor: rige el catálogo
    respaldo = franja()
    assert respaldo["frecuenciadespachos_min"] == 5.0
    assert respaldo["fuente_frecuenciadespachos"] == O.FUENTE_FRECUENCIADESPACHOS
    assert O.fuente_frecuenciadespachos(None) == O.FUENTE_FRECUENCIADESPACHOS


def test_la_fuente_del_headway_vigente_del_plan_es_la_real_y_entra_en_la_memoria(monkeypatch,
                                                                                    _sin_frecuencias_en_memoria):
    """(j) El plan del día dice la misma fuente que la franja, y la memoria del plan no devuelve el plan calculado
    con otra fuente: el headway vigente y su fuente son parte de la clave."""
    offline = _plan(UMBRALES, ruta="SILENCIO", version=2)
    assert offline["fuente_frecuenciadespachos"] == O.FUENTE_FRECUENCIADESPACHOS
    assert offline["frecuenciadespachos_min"] == 5.0
    _modo_integrado(monkeypatch, "SILENCIO", "7,5")                  # sin vaciar la memoria del plan
    en_vivo = _plan(UMBRALES, ruta="SILENCIO", version=2)
    assert en_vivo["fuente_frecuenciadespachos"] == O.FUENTE_FRECUENCIADESPACHOS_EN_VIVO
    assert en_vivo["frecuenciadespachos_min"] == 7.5
    assert {h["frecuenciadespachos_min"] for h in en_vivo["horas"]} == {7.5}
    assert [h["salidas"] for h in en_vivo["horas"]] == [h["salidas"] for h in offline["horas"]]  # el MILP no cambia
    _modo_integrado(monkeypatch, "SILENCIO", None)
    respaldo = _plan(UMBRALES, ruta="SILENCIO", version=2)
    assert respaldo["fuente_frecuenciadespachos"] == O.FUENTE_FRECUENCIADESPACHOS
    assert respaldo["frecuenciadespachos_min"] == 5.0


def test_las_franjas_del_ciclo_usan_el_headway_vigente_del_plan(monkeypatch, _sin_frecuencias_en_memoria):
    """(j) en el ciclo: _con_datos_nuevos recomienda la franja de cada ruta con la información de
    datos.frecuencia_vigente (ejecucion._info_de_las_rutas), la misma con que el plan del día lee el headway vigente:
    en modo integrado, el de la tabla rutas de la fuente, y la franja y su fila de recommendation lo dicen; offline, o
    si la fuente no trae valor para la ruta, el del catálogo empaquetado. Antes la franja del ciclo tomaba siempre el
    catálogo empaquetado y, en modo integrado, comparaba con otro valor que el plan del mismo ciclo."""
    import uuid

    from app.servicios import ejecucion

    usadas: list[tuple[str, dict]] = []
    for paso in ("_error_y_monitoreo", "_ocupacion_actual", "_particion_de_la_foto", "_alertas_de_pronostico",
                 "_notificar_nuevas", "plan_y_respuesta", "_avance"):
        monkeypatch.setattr(ejecucion, paso, lambda *a, **k: {})
    monkeypatch.setattr(ejecucion, "alertas_observadas", lambda *a, **k: ([], 0, {}))
    monkeypatch.setattr(ejecucion, "_pronostico_y_recomendacion",
                        lambda s, c, ruta, info, *a: usadas.append((ruta, info)))

    def ciclo() -> dict[str, dict]:
        usadas.clear()
        c = ejecucion._Ciclo(execution_id=uuid.uuid4(), p={"rutas": ["CL 72", "SILENCIO"], "horizontes": [60],
                                                           "instante": "2025-11-19T10:00:00-05:00"},
                             fuente=None, df=None, validos=None, errores=[], marca_anterior=None, marca_nueva=None,
                             filas_leidas=0, filas_validas=0, version_u=2, umbrales=UMBRALES, model_id=None,
                             metricas={})
        ejecucion._con_datos_nuevos(None, c)
        return dict(usadas)

    offline = ciclo()
    assert offline["CL 72"].get("frecuencia_fuente") == datos.FRECUENCIA_EMPAQUETADA
    assert O.frecuenciadespachos_min(offline["CL 72"]) == 5.0
    _modo_integrado(monkeypatch, "CL 72", "12")
    en_vivo = ciclo()
    assert en_vivo["CL 72"].get("frecuencia_fuente") == datos.FRECUENCIA_DE_LA_FUENTE
    assert O.frecuenciadespachos_min(en_vivo["CL 72"]) == 12.0
    franja, _ = O.recomendacion_franja(en_vivo["CL 72"], UMBRALES, None, hora=11, fecha=date(2025, 11, 19),
                                       demanda_hora=500, demanda_p90=600, demanda_p10=400,
                                       solicitud={"flota_disponible": 200}, usar_tipologias=False)
    assert (franja["frecuenciadespachos_min"], franja["fuente_frecuenciadespachos"]) == (
        12.0, O.FUENTE_FRECUENCIADESPACHOS_EN_VIVO)
    assert en_vivo["SILENCIO"].get("frecuencia_fuente") == datos.FRECUENCIA_EMPAQUETADA   # la fuente no la trae
    assert O.frecuenciadespachos_min(en_vivo["SILENCIO"]) == 5.0


# ------------------------------------------------------------------ respuesta del reto con la tarifa gobernada
def test_la_respuesta_usa_la_tarifa_con_que_se_resolvio_el_plan():
    from app.servicios import respuesta

    d5 = C.param_d5(fuente=True)
    plan = {"parametros": {"tarifa_cop": {"valor": 2800.0, "fuente": "threshold_config v14"},
                           "costo_bus_hora_cop": {"valor": 25000.0, "fuente": "threshold_config v14"}}}
    params = respuesta._costos_del_plan(plan, d5)
    assert params["TARIFA"] == 2800.0 and params["COSTO_BUS_HORA"] == 25000.0 and params["COSTO_KM"] == d5["COSTO_KM"]
    nota = respuesta._nota_recaudo(params["TARIFA"], params, 1000.0)
    assert "2.800 COP" in nota and "threshold_config v14" in nota and "§19" in nota and "Extreme" in nota
    viejo = respuesta._costos_del_plan({}, d5)          # plan persistido sin parámetros: la tarifa de D5
    assert viejo["TARIFA"] == d5["TARIFA"] and viejo["FUENTE_TARIFA"] is None
    assert "threshold_config v" not in respuesta._nota_recaudo(viejo["TARIFA"], viejo, 1000.0)
    # una tarifa gobernada de 0 no vuelve a la de D5: el recaudo queda «sin dato», como el MILP la usó
    gobernada = {"parametros": {"tarifa_cop": {"valor": 0.0, "fuente": "threshold_config v15"}}}
    cero = respuesta._costos_del_plan(gobernada, d5)
    assert cero["TARIFA"] == 0.0
    assert respuesta._nota_recaudo(cero["TARIFA"], cero, 1.0) == respuesta.NOTA_TARIFA_SIN_DATO


# ------------------------------------------------------------------ tolerancia de oportunidad de la calidad (§5.1)
def _lote_con_un_dato_tardio():
    """Tres horas de CRA 54 del 10-03-2025; la de las 6 h llegó un día después del cierre del día."""
    import pandas as pd

    cierre = pd.Timestamp("2025-03-10 23:59:59", tz="America/Bogota")
    return pd.DataFrame({"ruta": ["CRA 54"] * 3, "fecha": [date(2025, 3, 10)] * 3, "hora": [6, 7, 8],
                         "pasajeros": [100.0, 101.0, 102.0], "salidas": pd.array([5] * 3, dtype="Int16"),
                         "ultima_actualizacion": [cierre + pd.Timedelta(days=1), cierre, cierre]})


def test_la_tolerancia_de_oportunidad_es_el_umbral_gobernado_de_datos_atrasados():
    """El dato tardío (OPOR-001) se mide con periodos_atraso × periodo_ingesta_min de threshold_config, el umbral de
    §5.1 «datos atrasados» que usa ALT-009; con los valores sembrados (2 × 1.440 min) es la misma tolerancia de
    siempre, y el ciclo (ejecucion.validar_calidad) la toma de la versión vigente."""
    from datetime import timedelta

    from app.servicios import calidad as Q
    from app.servicios import ejecucion
    from app.servicios.alertas import UMBRALES_POR_DEFECTO

    sembrados = {"periodos_atraso": 2, "periodo_ingesta_min": 1440.0}
    assert Q.retraso_maximo_de(sembrados) == Q.RETRASO_MAXIMO == timedelta(days=2)
    assert {n: UMBRALES_POR_DEFECTO[n] for n in sembrados} == sembrados
    assert Q.retraso_maximo_de({"periodos_atraso": 1, "periodo_ingesta_min": 720}) == timedelta(hours=12)
    invalidos = (None, {}, {"periodos_atraso": 2}, {"periodos_atraso": 0, "periodo_ingesta_min": 1440},
                 {"periodos_atraso": "x", "periodo_ingesta_min": 1440},
                 {"periodos_atraso": float("nan"), "periodo_ingesta_min": 1440},
                 {"periodos_atraso": float("inf"), "periodo_ingesta_min": 1440})
    for invalido in invalidos:
        assert Q.retraso_maximo_de(invalido) == Q.RETRASO_MAXIMO, invalido

    def tardios(umbrales):
        validos, errores = ejecucion.validar_calidad(_lote_con_un_dato_tardio(), "L1", None, umbrales)
        assert len(validos) == 3                            # la oportunidad no bloquea
        return [(e["llave"]["hora"], e["detalle"]) for e in errores if e["codigo"] == "OPOR-001"]

    assert tardios(sembrados) == [] and tardios(None) == []
    [(hora, detalle)] = tardios({"periodos_atraso": 1, "periodo_ingesta_min": 720})
    assert hora == 6 and "tolerancia 12:00:00" in detalle
    assert ejecucion.validar_calidad(None, "L0", None, sembrados) == (None, [])
