"""Endpoints de optimización contra el PostgreSQL local, con cada rol (§7.2): POST /recommendations/calculate (§10.2,
§10.1, RF-008, §10.3), GET /recommendations/plan (plan del día con el modelo activo, leído de lo persistido), las
claves de §12.3 en POST /predictions/run y los filtros por idruta.

Las respuestas reales quedan como evidencia con tests/evidencia.guardar_evidencia: en docs/evidencias/optimizacion/
solo con GENERAR_EVIDENCIAS=1; si no, en un directorio temporal (correr la suite no cambia el repositorio)."""
from __future__ import annotations

import json
from datetime import date

import pytest

from tests.evidencia import guardar_evidencia

CLAVES_12_3 = {"predictionId", "routeId", "generatedAt", "horizonMinutes", "predictedPassengers", "confidenceInterval",
               "modelVersion", "recommendation", "explanation"}
CLAVES_RECOMENDACION_12_3 = {"headwayMinutes", "busesPerHour", "vehiclesRequired", "viable", "reason"}


@pytest.fixture
def auth(cliente, monkeypatch):
    from app.config import obtener_ajustes

    monkeypatch.setattr(obtener_ajustes(), "auth_habilitada", True)
    return cliente


def _h(clave):
    return {"X-API-Key": clave}


def _guardar(nombre: str, datos) -> None:
    guardar_evidencia(f"optimizacion/{nombre}", json.dumps(datos, ensure_ascii=False, indent=1, default=str) + "\n")


CUERPO = {"ruta": "CRA 54", "hora": 7, "fecha": "2025-03-04", "demanda_hora": 1000, "demanda_p90": 1180,
          "demanda_p10": 850}


def test_calculate_por_rol_con_funcion_objetivo_y_explicacion(auth, claves_prueba):
    r = auth.post("/api/v1/recommendations/calculate", json=CUERPO, headers=_h(claves_prueba["operador"]))
    assert r.status_code == 403 and r.json()["error"]["detalle"]["rol_requerido"] == "analista"
    assert auth.post("/api/v1/recommendations/calculate", json=CUERPO, headers=_h("")).status_code == 401
    for rol in ("analista", "admin"):
        r = auth.post("/api/v1/recommendations/calculate", json=CUERPO, headers=_h(claves_prueba[rol]))
        assert r.status_code == 201, r.text
    x = r.json()
    # campos de siempre (Dash y demos) + la explicación de §10.2
    for campo in ("recommendation_id", "buses_hora", "headway_min", "vehiculos_requeridos", "viable", "motivo",
                  "formula", "umbrales_version", "frecuencia_actual_min", "diferencia_min", "detalle"):
        assert campo in x
    assert x["metodo"] == "funcion_objetivo_10_2" and x["solver"]["estado"] == "Optimal"
    assert set(x["objetivo"]["pesos"]) == {"alfa", "beta", "gamma", "delta"}
    assert all(p["fuente"] for p in x["objetivo"]["pesos"].values())
    assert {c["nombre"] for c in x["restricciones"]} >= {"headway_minimo", "headway_maximo", "nivel_servicio",
                                                         "flota_disponible", "duracion_ciclo",
                                                         "ocupacion_objetivo_minima"}
    assert x["explicacion"] and x["linea_base_10_3"]["formula"].startswith("capacidad_efectiva")
    # §10.3: las dos líneas base, cada una con su nombre
    assert x["linea_base_10_3"]["nombre"].startswith("§10.3 ajustada")
    assert x["linea_base_10_3_literal"]["nombre"].startswith("§10.3 literal")
    assert x["linea_base_10_3_literal"]["factor_carga"] == 1.0
    assert x["sobreoferta"] in (True, False)
    assert x["contexto_franja"]["tipo_dia"] == "Laboral"                 # 4-mar-2025 es martes
    assert x["contexto_franja"]["headway_maximo"]["valor"] == 10.0       # min(10, 2 × 5)
    assert x["frecuencia_actual_min"] == x["contexto_franja"]["frecuencia_actual_min"]
    asign = x["tipologias"]["asignacion"]
    assert sum(a["buses_hora"] for a in asign) == x["buses_hora"]
    assert sum(a["vehiculos"] for a in asign) == x["vehiculos_requeridos"] <= x["contexto_franja"]["flota_disponible"]
    comp = x["comparacion_actual"]
    assert comp["actual"]["rotulo"] == "frecuencia actual (programada)" and "diferencia" in comp
    _guardar("ejemplo_calculate.json", {"solicitud": CUERPO, "respuesta": {k: v for k, v in x.items()
                                                                           if k != "detalle"}})


def test_calculate_inviable_se_marca_y_explica(auth, claves_prueba):
    cuerpo = dict(CUERPO, demanda_hora=6000, demanda_p90=7000, demanda_p10=5000)
    r = auth.post("/api/v1/recommendations/calculate", json=cuerpo, headers=_h(claves_prueba["analista"]))
    assert r.status_code == 201, r.text
    x = r.json()
    assert x["viable"] is False and x["motivo"] and x["explicacion"][0].startswith("No viable")
    aprox = x["mejor_aproximacion"]
    assert aprox and aprox["cobertura_nivel_servicio"] < 1 and aprox["aviso"].startswith("Mejor aproximación")
    assert x["buses_hora"] == aprox["buses_hora"]                     # las cifras son las de la aproximación rotulada
    assert x["vehiculos_requeridos"] <= x["contexto_franja"]["flota_disponible"]     # nunca viola la flota
    assert x["sobreoferta"] is False
    _guardar("ejemplo_calculate_no_viable.json", {"solicitud": cuerpo, "respuesta": {k: v for k, v in x.items()
                                                                                     if k != "detalle"}})


def test_escenario_que_pasa_si_y_sensibilidad(auth, claves_prueba):
    cuerpo = dict(CUERPO, escenario={"factor_demanda": 1.3, "pesos": {"beta": 3}}, sensibilidad=True)
    r = auth.post("/api/v1/recommendations/calculate", json=cuerpo, headers=_h(claves_prueba["analista"]))
    assert r.status_code == 201, r.text
    x = r.json()
    esc = x["escenario"]
    assert esc["escenario"] == {"factor_demanda": 1.3, "pesos": {"beta": 3.0}}
    assert esc["resultado"]["buses_hora"] >= x["buses_hora"]
    assert len(x["sensibilidad"]["variaciones"]) == 23 and x["sensibilidad"]["base"]["buses_hora"] == x["buses_hora"]
    # lo guardado cabe en una celda de Excel (la exportación XLSX pone el JSON de detalle en una celda)
    assert len(json.dumps(x["detalle"], ensure_ascii=False)) < 32767
    malo = auth.post("/api/v1/recommendations/calculate", json=dict(CUERPO, pesos={"zeta": 1}),
                     headers=_h(claves_prueba["analista"]))
    assert malo.status_code == 422 and malo.json()["error"]["codigo"] == "parametros_invalidos"
    _guardar("ejemplo_escenario_y_sensibilidad.json", {"solicitud": cuerpo, "escenario": esc,
                                                       "sensibilidad": x["sensibilidad"]})


def test_pesos_versionados_con_put_thresholds(auth, claves_prueba, umbrales_restituidos):
    admin, analista = _h(claves_prueba["admin"]), _h(claves_prueba["analista"])
    antes = auth.get("/api/v1/thresholds", headers=admin).json()
    assert auth.put("/api/v1/thresholds", json={"valores": {"peso_tiempo_espera": 4}, "creado_por": "x"},
                    headers=analista).status_code == 403
    malo = auth.put("/api/v1/thresholds", json={"valores": {"nivel_servicio": 1.4}, "creado_por": "x"}, headers=admin)
    assert malo.status_code == 422 and malo.json()["error"]["codigo"] == "umbral_invalido"
    r = auth.put("/api/v1/thresholds", json={"valores": {"peso_tiempo_espera": 30, "nivel_servicio": 0.95},
                                             "creado_por": "x", "motivo": "prueba §10.2"}, headers=admin)
    assert r.status_code == 200, r.text
    version = r.json()["version"]
    assert version == antes["version"] + 1 and r.json()["valores"]["peso_tiempo_espera"] == 30
    historia = auth.get("/api/v1/thresholds/history", params={"nombre": "peso_tiempo_espera"}, headers=admin).json()
    assert historia[0]["version"] == version and historia[0]["creado_por"] == "prueba_admin"
    x = auth.post("/api/v1/recommendations/calculate", json=CUERPO, headers=analista).json()
    assert x["umbrales_version"] == version
    assert x["objetivo"]["pesos"]["beta"] == {"simbolo": "β", "nombre": "peso_tiempo_espera", "valor": 30.0,
                                              "fuente": f"threshold_config v{version}"}
    # α viene sembrado por la migración 0005 y la versión nueva lo conserva: también sale de threshold_config
    assert x["objetivo"]["pesos"]["alfa"] == {"simbolo": "α", "nombre": "peso_costo_operativo", "valor": 1.0,
                                              "fuente": f"threshold_config v{version}"}
    assert x["demanda"]["nivel_servicio"] == 0.95
    # la solicitud puede probar otros pesos sin tocar la versión vigente
    y = auth.post("/api/v1/recommendations/calculate", json=dict(CUERPO, pesos={"beta": 1}), headers=analista).json()
    assert y["objetivo"]["pesos"]["beta"]["fuente"] == "solicitud" and y["umbrales_version"] == version
    assert x["buses_hora"] > y["buses_hora"]               # con la espera 30 veces más cara se despacha más seguido
    _guardar("pesos_versionados.json", {"version": version, "pesos_vigentes": x["objetivo"]["pesos"],
                                        "con_beta_30_y_nivel_0_95": {"buses_hora": x["buses_hora"],
                                                                     "headway_min": x["headway_min"],
                                                                     "componentes_cop": x["detalle"]["salida"]
                                                                     .get("componentes_cop")},
                                        "con_beta_1_en_la_solicitud": {"buses_hora": y["buses_hora"],
                                                                       "headway_min": y["headway_min"],
                                                                       "componentes_cop": y["detalle"]["salida"]
                                                                       .get("componentes_cop")}})
    # umbrales_restituidos borra al terminar la versión creada (no afecta a las demás pruebas)


def test_espera_maxima_gobernada_cambia_la_recomendacion(auth, claves_prueba, umbrales_restituidos):
    """§5.1 y S12: un PUT /thresholds que baja espera_max_min baja el headway máximo efectivo y cambia la franja. Al
    terminar, umbrales_restituidos deja vigente la versión de antes."""
    admin, analista = _h(claves_prueba["admin"]), _h(claves_prueba["analista"])
    cuerpo = dict(CUERPO, hora=11, demanda_hora=250, demanda_p90=300, demanda_p10=200, tipologias=False,
                  flota_disponible=200)
    antes = auth.post("/api/v1/recommendations/calculate", json=cuerpo, headers=analista).json()
    r = auth.put("/api/v1/thresholds", json={"valores": {"espera_max_min": 3}, "creado_por": "x",
                                             "motivo": "prueba S12"}, headers=admin)
    assert r.status_code == 200, r.text
    despues = auth.post("/api/v1/recommendations/calculate", json=cuerpo, headers=analista).json()
    assert antes["headway_min"] == 10.0 and despues["headway_min"] <= 6.0
    assert despues["buses_hora"] > antes["buses_hora"]
    assert despues["contexto_franja"]["headway_maximo"]["manda"] == "espera_max_min"
    assert antes["sobreoferta"] is True and "65 %" in antes["motivo_sobreoferta"]


def _persistir_plan(sesion, ruta: str, fecha: str):
    """Simula el cierre del ciclo diario: plan_dia con los umbrales vigentes y una fila por hora (origen 'plan_dia')."""
    from sqlalchemy import delete

    from app.modelos_db import Recomendacion
    from app.servicios import ejecucion, optimizacion

    version, umbrales = ejecucion.umbrales_vigentes(sesion)
    plan = optimizacion.plan_dia(fecha, ruta, umbrales=umbrales, umbrales_version=version)
    sesion.execute(delete(Recomendacion).where(Recomendacion.ruta == ruta,
                                               Recomendacion.fecha == date.fromisoformat(plan["fecha"]),
                                               Recomendacion.origen == "plan_dia"))
    for h in plan["horas"]:
        sesion.add(Recomendacion(**optimizacion.fila_plan(plan, h)))
    sesion.commit()
    return plan


def test_plan_del_dia_se_lee_de_lo_persistido_con_cada_rol(auth, claves_prueba, sesion):
    """D5 (§7.1): el GET no resuelve el MILP. Sin plan persistido responde 404 «sin_calcular» con la pista; con las
    filas del ciclo (origen = 'plan_dia') devuelve el plan del modelo activo con la explicación de cada hora."""
    params = {"ruta": "CRA 54", "fecha": "2025-11-19"}
    assert auth.get("/api/v1/recommendations/plan", params=params, headers=_h("")).status_code == 401
    otra = auth.get("/api/v1/recommendations/plan", params={"ruta": "CL 72", "fecha": "2031-02-03"},
                    headers=_h(claves_prueba["operador"]))
    assert otra.status_code == 404 and otra.json()["error"]["codigo"] == "sin_calcular"
    assert otra.json()["error"]["detalle"]["pista"] == "POST /api/v1/respuesta/calcular"
    plan = _persistir_plan(sesion, "CRA 54", "2025-11-19")
    for rol in ("operador", "analista", "admin"):
        r = auth.get("/api/v1/recommendations/plan", params=params, headers=_h(claves_prueba[rol]))
        assert r.status_code == 200, r.text
    x = r.json()
    assert [h["hora"] for h in x["horas"]] == list(range(4, 21)) and x["estado_solver"] == "Optimal"
    assert x["fuente_pronostico"] == "modelo_activo" and x["model_id"] == plan["model_id"]
    assert x["calibracion_version"] == plan["calibracion_version"] and x["origen"].startswith("plan_dia")
    assert x["calculado_en"].endswith("-05:00")                         # §8.1: instantes en la hora de Bogotá
    assert x["salidas_dia"] == sum(h["salidas"] for h in x["horas"]) == plan["salidas_dia"]
    assert x["vehiculos_hora_pico"] > 0 and x["parametros"]["headway_minimo_min"]["fuente"].startswith("threshold")
    assert x["definicion_vehiculos"] and x["buses_en_ruta_pico"] <= x["flota_disponible"] + x["holgura_flota"] + 1e-6
    assert x["salidas_programadas_dia"] and x["costo_total_cop"] > 0
    for h in x["horas"]:
        assert {"limites_activos", "demanda_diseno", "margen", "viable", "motivo", "sobreoferta"} <= set(h)
        assert h["viable"] is (h["motivo"] is None)
    assert x["horas_no_viables"] == [h["hora"] for h in x["horas"] if not h["viable"]]
    # el listado filtra el plan por origen e idruta (§8.3)
    filas = auth.get("/api/v1/recommendations", params={"origen": "plan_dia", "idruta": 16, "desde": "2025-11-19",
                                                        "hasta": "2025-11-19", "limite": 50},
                     headers=_h(claves_prueba["operador"])).json()
    assert filas["items"] and {f["ruta"] for f in filas["items"]} == {"CRA 54"}
    r = auth.get("/api/v1/recommendations/plan", params=dict(params, ruta="RUTA X"),
                 headers=_h(claves_prueba["operador"]))
    assert r.status_code == 404 and r.json()["error"]["codigo"] == "ruta_desconocida"
    _guardar("ejemplo_plan_d5.json", x)


def test_plan_del_dia_con_las_filas_del_ciclo_trae_programadas_flota_y_costo(auth, claves_prueba, sesion):
    """Las filas que persiste el ciclo diario (ejecucion.guardar_plan_dia, con un resumen parcial) bastan para que GET
    /recommendations/plan muestre salidas programadas, flota disponible, costo del día y la definición de los
    vehículos de la hora pico (antes salían «—»)."""
    from types import SimpleNamespace

    from sqlalchemy import delete

    from app.modelos_db import Recomendacion
    from app.servicios import ejecucion, optimizacion

    version, umbrales = ejecucion.umbrales_vigentes(sesion)
    plan = optimizacion.plan_dia("2025-11-23", "SILENCIO", umbrales=umbrales, umbrales_version=version)
    sesion.execute(delete(Recomendacion).where(Recomendacion.ruta == "SILENCIO",
                                               Recomendacion.fecha == date(2025, 11, 23),
                                               Recomendacion.origen == "plan_dia"))
    ejecucion.guardar_plan_dia(sesion, SimpleNamespace(execution_id=None, version_u=version), "SILENCIO",
                               date(2025, 11, 23), plan)
    sesion.commit()
    r = auth.get("/api/v1/recommendations/plan", params={"ruta": "SILENCIO", "fecha": "2025-11-23"},
                 headers=_h(claves_prueba["operador"]))
    assert r.status_code == 200, r.text
    x = r.json()
    assert x["salidas_programadas_dia"] == pytest.approx(plan["salidas_programadas_dia"], abs=0.05)
    assert x["flota_disponible"] == plan["flota_disponible"] > 0
    assert x["costo_total_cop"] == pytest.approx(plan["costo_total_cop"], abs=0.1)
    assert set(x["componentes_costo_cop"]) == {"op", "espera", "sobrecarga", "ingreso"}
    assert x["definicion_vehiculos"] == optimizacion.DEFINICION_VEHICULOS
    assert x["vehiculos_hora_pico"] <= x["flota_disponible"] and x["buses_en_ruta_pico"] <= x["flota_disponible"]
    # domingo: la hora 4 de SILENCIO tiene una sola salida, sin intervalo que verificar, y no es «no viable» por eso
    cuatro = next(h for h in x["horas"] if h["hora"] == 4)
    assert cuatro["salidas"] == 1 and cuatro["sin_intervalo"] is True and cuatro["viable"] is True
    assert 4 not in x["horas_no_viables"]
    sesion.execute(delete(Recomendacion).where(Recomendacion.ruta == "SILENCIO",
                                               Recomendacion.fecha == date(2025, 11, 23),
                                               Recomendacion.origen == "plan_dia"))
    sesion.commit()


def test_listado_de_recomendaciones_documenta_el_filtro_origen(cliente):
    """GET /recommendations lista los dos orígenes; la descripción OpenAPI del endpoint y del filtro «origen» dice qué
    es cada uno y cómo separarlos."""
    esquema = cliente.app.openapi()
    for ruta in ("/api/v1/recommendations", "/api/v1/recommendations/export"):
        operacion = esquema["paths"][ruta]["get"]
        origen = next(p for p in operacion["parameters"] if p["name"] == "origen")
        assert "«franja»" in origen["description"] and "«plan_dia»" in origen["description"]
        assert "ambos orígenes" in origen["description"]
    descripcion = esquema["paths"]["/api/v1/recommendations"]["get"]["description"]
    assert "origen=franja" in descripcion and "/recommendations/plan" in descripcion


def test_predictions_run_pronostica_con_la_serie_validada_de_la_sesion(auth, claves_prueba, monkeypatch):
    """RF-013: POST /predictions/run predice dentro de inferencia.con_sesion(sesion), así que usa la serie
    validada (Parquet empaquetado ∪ demanda_observada) y puede pronosticar después del fin del Parquet."""
    from app.servicios import inferencia

    vistas = []
    original = inferencia.predecir

    def espia(*args, **kwargs):
        vistas.append(inferencia._SESION_DATOS.get())
        return original(*args, **kwargs)

    monkeypatch.setattr(inferencia, "predecir", espia)
    cuerpo = {"ruta": "CL 72", "instante": "2025-03-04T09:00:00-05:00", "horizonte_min": 60,
              "incluir_recomendacion": False}
    r = auth.post("/api/v1/predictions/run", json=cuerpo, headers=_h(claves_prueba["analista"]))
    assert r.status_code == 201, r.text
    assert vistas and vistas[0] is not None                     # la sesión de la petición, no la serie empaquetada
    assert inferencia._SESION_DATOS.get() is None               # el contexto se cierra al terminar


def test_plan_del_dia_en_modo_sincrono_de_pruebas(auth, claves_prueba, monkeypatch):
    """El cálculo dentro del GET existe solo como bandera interna de pruebas (nunca por HTTP): cualquier fecha con
    variables (también de 2026) y la opción E12 de laboratorio; sin variables, 404 «plan_no_disponible»."""
    from app.routers import predicciones

    monkeypatch.setattr(predicciones, "CALCULO_SINCRONO_PRUEBAS", True)
    operador = _h(claves_prueba["operador"])
    r = auth.get("/api/v1/recommendations/plan", params={"ruta": "SILENCIO", "fecha": "2026-01-05"}, headers=operador)
    assert r.status_code == 200, r.text
    assert r.json()["fuente_pronostico"] == "modelo_activo" and r.json()["tipo_dia"] == "Laboral"
    e12 = auth.get("/api/v1/recommendations/plan", params={"ruta": "CRA 54", "fecha": "2025-03-11",
                                                           "pronostico": "E12"}, headers=operador)
    assert e12.status_code == 200 and e12.json()["fuente_pronostico"] == "E12"
    r = auth.get("/api/v1/recommendations/plan", params={"ruta": "CRA 54", "fecha": "2030-01-01"}, headers=operador)
    assert r.status_code == 404 and r.json()["error"]["codigo"] == "plan_no_disponible"


def test_predictions_run_trae_las_claves_de_12_3(auth, claves_prueba):
    cuerpo = {"ruta": "CRA 54", "instante": "2025-03-04T06:30:00-05:00", "horizonte_min": 60}
    assert auth.post("/api/v1/predictions/run", json=cuerpo,
                     headers=_h(claves_prueba["operador"])).status_code == 403
    r = auth.post("/api/v1/predictions/run", json=cuerpo, headers=_h(claves_prueba["analista"]))
    assert r.status_code == 201, r.text
    x = r.json()
    assert CLAVES_12_3 <= set(x)
    assert set(x["confidenceInterval"]) == {"lower", "upper"}
    assert set(x["recommendation"]) == CLAVES_RECOMENDACION_12_3
    assert x["predictionId"] == x["prediction_id"] and x["routeId"] == "CRA 54" and x["horizonMinutes"] == 60
    assert x["generatedAt"].endswith("-05:00")
    assert x["predictedPassengers"] == round(x["pasajeros"]) and x["modelVersion"] == x["model_id"]
    assert x["confidenceInterval"]["lower"] <= x["predictedPassengers"] <= x["confidenceInterval"]["upper"]
    rec = x["recomendacion"]
    if rec["viable"]:
        assert x["recommendation"] == {"headwayMinutes": rec["headway_min"], "busesPerHour": rec["buses_hora"],
                                       "vehiclesRequired": rec["vehiculos_requeridos"], "viable": True,
                                       "reason": None}
    else:
        assert x["recommendation"]["viable"] is False and x["recommendation"]["busesPerHour"] is None
    assert x["explanation"] and all(isinstance(v, str) for v in x["explanation"])
    # los campos de siempre siguen (el Dash y las demos los usan)
    for campo in ("prediction_id", "pasajeros", "p10", "p90", "model_id", "explicacion", "variables",
                  "recomendacion"):
        assert campo in x
    franja = rec["detalle"]["salida"]["franja_prediccion"]
    assert rec["hora"] == franja["hora"] and rec["demanda_hora"] == pytest.approx(franja["demanda_hora"])
    # §8.3: el listado de predicciones filtra por idruta
    lista = auth.get("/api/v1/predictions", params={"idruta": 16, "limite": 5},
                     headers=_h(claves_prueba["operador"])).json()
    assert lista["items"] and {p["ruta"] for p in lista["items"]} == {"CRA 54"}
    ejemplo = {k: x[k] for k in ("predictionId", "routeId", "generatedAt", "horizonMinutes", "predictedPassengers",
                                 "confidenceInterval", "modelVersion", "recommendation", "explanation")}
    _guardar("ejemplo_prediccion_12_3.json", {"solicitud": cuerpo, "claves_12_3": ejemplo,
                                              "recomendacion_viable": rec["viable"], "motivo": rec["motivo"],
                                              "franja": franja})


def test_predictions_run_con_franja_inviable_no_presenta_la_aproximacion(auth, claves_prueba, monkeypatch):
    """§10.3 último párrafo y §18: si la franja no es viable, el bloque §12.3 dice viable=false con el motivo y no
    muestra cifras; la mejor aproximación ejecutable queda rotulada en la recomendación (mejor_aproximacion)."""
    from app.routers import predicciones

    original = predicciones.servicio.umbrales_vigentes

    def estrictos(sesion):          # headway mínimo de 30 min: a lo sumo 2 buses/h en la hora pico de CRA 54
        version, umbrales = original(sesion)
        return version, dict(umbrales, headway_minimo_min=30.0, headway_maximo_min=30.0, espera_max_min=15.0)

    monkeypatch.setattr(predicciones.servicio, "umbrales_vigentes", estrictos)
    cuerpo = {"ruta": "CRA 54", "instante": "2025-11-19T06:00:00-05:00", "horizonte_min": 60}
    r = auth.post("/api/v1/predictions/run", json=cuerpo, headers=_h(claves_prueba["analista"]))
    assert r.status_code == 201, r.text
    x = r.json()
    bloque, rec = x["recommendation"], x["recomendacion"]
    assert rec["viable"] is False and rec["motivo"]
    assert bloque == {"headwayMinutes": None, "busesPerHour": None, "vehiclesRequired": None, "viable": False,
                      "reason": rec["motivo"]}
    aprox = rec["detalle"]["salida"]["mejor_aproximacion"]
    assert aprox is None or aprox["aviso"].startswith("Mejor aproximación")
    _guardar("ejemplo_prediccion_12_3_no_viable.json", {"solicitud": cuerpo, "umbrales": "headway mínimo 30 min",
                                                        "recommendation": bloque, "motivo": rec["motivo"],
                                                        "mejor_aproximacion": aprox})
