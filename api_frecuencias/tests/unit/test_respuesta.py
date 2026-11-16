"""Respuesta a la pregunta final del reto (§20): composición, contrato, viabilidad, regla D1 de la espera, fecha por
omisión con los datos recientes, alertas «abiertas ahora» y de la fecha, 422 por ruta, 404 «sin_calcular» y §8.1 (todo
instante en -05:00). Sin base de datos: la sesión es None (sin alertas ni umbrales) o una sesión falsa."""
from __future__ import annotations

import math
import re
from datetime import date, timedelta

import pytest
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from app.servicios import respuesta

FECHA = date(2025, 10, 15)          # miércoles laboral, posterior al corte del modelo (2025-08-31)
PREGUNTA_SPEC = ("con los datos históricos y recientes, ¿cada cuánto despachar buses para optimizar la flota y el "
                 "recaudo? ¿Cuántos pasajeros y vehículos se esperan, y qué situaciones requieren atención inmediata?")
CLAVES = {"pregunta", "fecha", "tipo_dia", "generado_en", "consultado_en", "trazabilidad", "rutas", "limitaciones"}
CLAVES_RUTA = {"ruta", "idruta", "cada_cuanto_despachar", "resumen_despacho", "pasajeros_esperados", "vehiculos",
               "flota_y_recaudo", "atencion_inmediata", "alertas_de_la_fecha", "atencion_resumen"}
CLAVES_HORA = {"hora", "franja", "headway_min", "buses_hora", "headway_actual_min", "buses_hora_actual", "viable",
               "motivo"}
CLAVES_TRAZA = {"model_id", "feature_version", "data_cutoff", "calibracion_version", "fuente_pronostico",
                "umbrales_version", "execution_id", "datos_hasta", "fuentes"}
INSTANTE = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?")


@pytest.fixture(scope="module")
def silencio() -> dict:
    return respuesta.componer(None, "SILENCIO", FECHA)


def _instantes(valor, camino="$"):
    if isinstance(valor, dict):
        for k, v in valor.items():
            yield from _instantes(v, f"{camino}.{k}")
    elif isinstance(valor, list):
        for v in valor:
            yield from _instantes(v, f"{camino}[]")
    elif isinstance(valor, str):
        m = INSTANTE.fullmatch(valor.strip())
        if m:
            yield camino, valor, m.group(1)


def _plan_referencia(ruta: str, fecha: date, respuesta_ruta: dict) -> dict:
    """El mismo plan que usa la respuesta (plan_dia con el pronóstico del modelo activo que trae la propia respuesta,
    o el respaldo E12)."""
    traz = respuesta_ruta["trazabilidad"]
    pron = [dict(p) for p in respuesta_ruta["rutas"][0]["pasajeros_esperados"]["por_hora"]]
    plan, _fuente = respuesta._plan(ruta, fecha, {}, None, respuesta.pronostico_plan(), pron, traz["model_id"],
                                    traz["calibracion_version"])
    return plan


def test_contrato_y_pregunta_literal(silencio):
    assert CLAVES <= set(silencio)
    assert silencio["pregunta"] == PREGUNTA_SPEC == respuesta.PREGUNTA
    assert silencio["fecha"] == "2025-10-15" and silencio["tipo_dia"] == "Laboral"
    traz = silencio["trazabilidad"]
    assert CLAVES_TRAZA <= set(traz)
    assert traz["execution_id"] is None and len(traz["fuentes"]) >= 6
    assert traz["calibracion_version"] == "v2" and traz["fuente_pronostico"] in ("modelo_activo", "E12")
    assert any("respuesta_reto" in f for f in traz["fuentes"])
    assert any("demanda_observada" in f for f in traz["fuentes"])
    (ruta,) = silencio["rutas"]
    assert CLAVES_RUTA <= set(ruta) and ruta["ruta"] == "SILENCIO" and ruta["idruta"] == 2
    assert [h["hora"] for h in ruta["cada_cuanto_despachar"]] == list(range(4, 21))
    assert all(CLAVES_HORA <= set(h) for h in ruta["cada_cuanto_despachar"])
    assert set(ruta["resumen_despacho"]) >= {"salidas_dia_recomendadas", "salidas_dia_programadas",
                                              "headway_pico_min", "headway_valle_min", "hora_pico"}
    assert set(ruta["pasajeros_esperados"]) >= {"dia", "p10", "p90", "por_hora"}
    assert set(ruta["vehiculos"]) >= {"requeridos_pico", "flota_disponible", "hora_pico"}
    assert set(ruta["flota_y_recaudo"]) >= {"recaudo_esperado_cop", "costo_operativo_cop",
                                            "vehiculos_hora_ahorrados", "nota"}
    assert ruta["atencion_inmediata"] == [] and ruta["alertas_de_la_fecha"] == []      # sin base no hay alertas
    assert ruta["atencion_resumen"]["abiertas_ahora"] == 0 and "Abiertas ahora" in ruta["atencion_resumen"]["nota"]
    assert silencio["limitaciones"] and all(isinstance(x, str) for x in silencio["limitaciones"])


def test_cada_cifra_sale_del_plan_del_dia_y_de_lo_programado(silencio):
    plan = _plan_referencia("SILENCIO", FECHA, silencio)
    (ruta,) = silencio["rutas"]
    horas = ruta["cada_cuanto_despachar"]
    for h, p in zip(horas, plan["horas"], strict=True):
        assert h["buses_hora"] == p["salidas"] and h["headway_min"] == p["headway_min"]
        assert h["headway_actual_min"] == p["frecuencia_actual_min"]
        assert h["buses_hora_actual"] == p["salidas_programadas"]
        assert h["franja"] == respuesta.franja_de(h["hora"])
    resumen = ruta["resumen_despacho"]
    assert resumen["salidas_dia_recomendadas"] == plan["salidas_dia"] == sum(h["buses_hora"] for h in horas)
    assert resumen["salidas_dia_programadas"] == plan["salidas_programadas_dia"]
    pico = max((h for h in horas if h["buses_hora"]), key=lambda h: h["buses_hora"])
    assert resumen["headway_pico_min"] == pico["headway_min"]
    valle = sorted(h["headway_min"] for h in horas if 9 <= h["hora"] <= 16 and h["headway_min"])
    assert resumen["headway_valle_min"] == pytest.approx(valle[len(valle) // 2] if len(valle) % 2 else
                                                         (valle[len(valle) // 2 - 1] + valle[len(valle) // 2]) / 2,
                                                         abs=0.01)
    franjas = resumen["por_franja"]
    assert [f["franja"] for f in franjas] == [n for n, _i, _f in respuesta.FRANJAS]
    assert sum(f["salidas"] for f in franjas) == resumen["salidas_dia_recomendadas"]
    assert sum(f["salidas_programadas"] for f in franjas) == pytest.approx(resumen["salidas_dia_programadas"], abs=0.3)
    fr = ruta["flota_y_recaudo"]
    assert fr["costo_operativo_cop"] == round(plan["componentes_costo_cop"]["op"])
    assert fr["vehiculos_hora_ahorrados"] == pytest.approx(fr["vehiculos_hora_actuales"]
                                                           - fr["vehiculos_hora_recomendados"], abs=0.11)
    ciclo = {p["hora"]: p["tiempo_ciclo_min"] for p in plan["horas"]}
    vh = sum(h["buses_hora"] * ciclo[h["hora"]] / 60 for h in horas)
    assert fr["vehiculos_hora_recomendados"] == pytest.approx(vh, rel=1e-3)


def test_pasajeros_con_banda_y_recaudo_con_la_tarifa_de_d5(silencio):
    from app.servicios.motor_d5 import comun as motor_comun

    (ruta,) = silencio["rutas"]
    pax = ruta["pasajeros_esperados"]
    assert [p["hora"] for p in pax["por_hora"]] == list(range(4, 21))
    assert all(0 <= p["p10"] <= p["esperado"] <= p["p90"] for p in pax["por_hora"])
    assert pax["dia"] == pytest.approx(sum(p["esperado"] for p in pax["por_hora"]), abs=0.2)
    assert pax["p10"] <= pax["dia"] <= pax["p90"]
    tarifa = motor_comun.param_d5(fuente=True)["TARIFA"]
    fr = ruta["flota_y_recaudo"]
    assert fr["tarifa_neta_cop"] == tarifa == 3182.0
    assert fr["recaudo_esperado_cop"] == round(pax["dia"] * tarifa)
    assert "§19" in fr["nota"] and "Extreme" in fr["nota"]


def test_pasajeros_son_los_del_modelo_activo(silencio):
    from datetime import datetime

    from app.servicios import inferencia

    (ruta,) = silencio["rutas"]
    h7 = next(p for p in ruta["pasajeros_esperados"]["por_hora"] if p["hora"] == 7)
    r = inferencia.predecir("SILENCIO", datetime(2025, 10, 15, 7, tzinfo=respuesta.servicio.ZONA), 60,
                            model_id=silencio["trazabilidad"]["model_id"], usar_nowcast=False)
    assert h7["esperado"] == round(r["pasajeros"], 1) and h7["p90"] == round(r["p90"], 1)
    assert silencio["trazabilidad"]["model_id"] == r["model_id"]


def test_vehiculos_frente_a_la_flota(silencio):
    (ruta,) = silencio["rutas"]
    v = ruta["vehiculos"]
    assert v["requeridos_pico"] <= v["flota_disponible"]              # el MILP respeta la flota (holgura 0)
    assert v["requeridos_pico_10_3"] >= v["requeridos_pico"]          # §10.3 supone el ciclo completo
    assert 4 <= v["hora_pico"] <= 23 and v["nota"]


def test_viabilidad_marca_y_explica():
    ok = {"salidas": 6, "headway_min": 10.0}
    assert respuesta._viabilidad(ok, 30.0, 45.0, "Optimal", 2.0, 10.0)[0] is True
    v, m = respuesta._viabilidad({"salidas": 34, "headway_min": 1.76}, 60.0, 79.0, "Optimal", 2.0, 10.0)
    assert v is False and "mínimo de 2,0 min" in m
    v, m = respuesta._viabilidad(ok, 50.0, 45.0, "Optimal", 2.0, 10.0)
    assert v is False and "flota disponible es 45" in m
    v, m = respuesta._viabilidad(ok, 30.0, 45.0, "Infeasible", 2.0, 10.0)
    assert v is False and "Infeasible" in m
    v, m = respuesta._viabilidad({"salidas": 0, "headway_min": None}, 0.0, 45.0, "Optimal", 2.0, 10.0)
    assert v is True and "sin salidas" in m


def test_espera_maxima_acota_el_headway_maximo_d1():
    """D1 (supuesto S12): headway máximo efectivo = min(política del tipo de día, headway_maximo_min,
    2 × espera_max_min). Bajar la espera máxima baja el máximo y vuelve no viable una hora que antes lo era."""
    from app.servicios.motor_d5 import comun as motor_comun

    params = motor_comun.param_d5(fuente=True)
    assert respuesta._limites_headway(params, "Domingo/festivo", {})[1] == 15.0
    assert respuesta._limites_headway(params, "Domingo/festivo", {"espera_max_min": 5.0})[1] == 10.0
    assert respuesta._limites_headway(params, "Laboral", {"espera_max_min": 3.0}) == (2.0, 6.0)
    assert respuesta._limites_headway(params, "Laboral", {"headway_maximo_min": 8.0, "headway_minimo_min": 3})[1] == 8
    hora = {"salidas": 6, "headway_min": 10.0}
    assert respuesta._viabilidad(hora, 10.0, 45.0, "Optimal", *respuesta._limites_headway(params, "Laboral", {}))[0]
    v, m = respuesta._viabilidad(hora, 10.0, 45.0, "Optimal",
                                 *respuesta._limites_headway(params, "Laboral", {"espera_max_min": 3.0}))
    assert v is False and "mayor que el máximo de 6,0 min" in m


def test_headway_minimo_gobernado_cambia_la_viabilidad():
    """El headway mínimo gobernado es una restricción del plan (§10.2): con 5 min ninguna hora de dos o más salidas
    baja de 5 min, y las horas donde la demanda pedía más salidas salen no viables con su motivo."""
    model_id = respuesta.modelo_vigente(None)["model_id"]
    flojo = respuesta._bloque_ruta("CRA 54", FECHA, model_id, {}, None)
    estricto = respuesta._bloque_ruta("CRA 54", FECHA, model_id, {"headway_minimo_min": 5.0}, None)
    filas = estricto["cada_cuanto_despachar"]
    assert all(h["headway_min"] >= 5.0 - 0.01 for h in filas if h["buses_hora"] >= 2)
    limitadas = [h for h in filas if "headway mínimo gobernado de 5,00 min" in (h["motivo"] or "")]
    assert limitadas and all(not h["viable"] for h in limitadas)
    for h in limitadas:
        assert "permite como máximo" in h["motivo"] and "mejor aproximación ejecutable" in h["motivo"]
    assert sum(h["buses_hora"] for h in filas) < sum(h["buses_hora"] for h in flojo["cada_cuanto_despachar"])


def test_festivo_entre_semana_se_declara_en_limitaciones():
    festivo = respuesta.componer(None, "CL 72", date(2025, 11, 17))     # lunes festivo (Independencia de Cartagena)
    assert festivo["tipo_dia"] == "Domingo/festivo"
    assert any("es festivo" in x for x in festivo["limitaciones"])
    domingo = respuesta.componer(None, "CL 72", date(2025, 11, 23))
    assert not any("es festivo" in x for x in domingo["limitaciones"])


def test_fecha_por_omision_es_el_dia_siguiente_al_ultimo_dato():
    from app.servicios import datos, variables

    ultima = max(datos.demanda_horaria()["fecha"])
    assert respuesta.ultima_fecha_datos(None) == ultima
    assert respuesta.fecha_por_omision(None) == ultima + timedelta(days=1)
    assert respuesta.rango_calculable(None) == (min(datos.demanda_horaria()["fecha"]),
                                                ultima + timedelta(days=variables.DIAS_EXTRA))
    fechas = respuesta.fechas_disponibles()
    assert fechas and FECHA in fechas
    if respuesta._plan_dia_disponible() is not None and respuesta.pronostico_plan() == "activo":
        assert respuesta.fecha_por_omision(None) in fechas          # datos recientes: se puede planear el día siguiente
    for f in (date(2030, 1, 1),):
        with pytest.raises(respuesta.SinDatos):
            respuesta.componer(None, "SILENCIO", f)
    with pytest.raises(ValueError):
        respuesta.componer(None, "RUTA X", FECHA)


def test_fecha_por_omision_considera_la_demanda_observada_de_la_base():
    class Sesion:
        def __init__(self, valor):
            self.valor = valor

        def scalar(self, _consulta):
            return self.valor

        def begin_nested(self):      # la lectura va en un punto de guardado: nunca revierte la sesión de quien llama
            from contextlib import nullcontext

            return nullcontext()

        def rollback(self):
            raise AssertionError("ultima_fecha_datos no debe revertir la sesión del ciclo")

    ultima = respuesta.ultima_fecha_datos(None)
    assert respuesta.fecha_por_omision(Sesion(ultima + timedelta(days=3))) == ultima + timedelta(days=4)
    assert respuesta.fecha_por_omision(Sesion(None)) == ultima + timedelta(days=1)
    assert respuesta.fecha_por_omision(Sesion(date(2024, 1, 1))) == ultima + timedelta(days=1)


def test_todo_instante_en_bogota(silencio):
    encontrados = list(_instantes(silencio))
    assert any(c == "$.generado_en" for c, _v, _z in encontrados)
    assert any(c.endswith("consultado_en") for c, _v, _z in encontrados)
    assert all(z in ("-05:00", "-0500") for _c, _v, z in encontrados), encontrados


class _SesionFalsa:
    def __init__(self, filas):
        self.filas, self.consultas = filas, []

    def scalars(self, consulta):
        from types import SimpleNamespace

        self.consultas.append(str(consulta.compile(compile_kwargs={"literal_binds": True})))
        return SimpleNamespace(all=lambda: self.filas)


def _alerta_falsa(**campos):
    import uuid
    from datetime import UTC, datetime
    from types import SimpleNamespace

    base = {"alert_id": uuid.uuid4(), "codigo": "ALT-002", "severidad": "critica", "estado": "nueva",
            "ruta": "SILENCIO", "origen": "pronostico", "detectada_en": datetime(2025, 10, 15, 12, 30, tzinfo=UTC),
            "ventana_inicio": datetime(2025, 10, 15, 13, 0, tzinfo=UTC), "explicacion": "x", "recomendacion": "y"}
    return SimpleNamespace(**(base | campos))


def test_alertas_abiertas_ahora_criticas_primero_y_en_bogota():
    """Con una sesión falsa: el servicio pide las abiertas, críticas primero, las rotula «abierta ahora» y presenta
    detectada_en en -05:00."""
    s = _SesionFalsa([_alerta_falsa()])
    (fila,) = respuesta.atencion_inmediata(s, "SILENCIO")
    assert fila["detectada_en"] == "2025-10-15T07:30:00-05:00" and fila["codigo"] == "ALT-002"
    assert fila["alcance"] == respuesta.ALCANCE_ABIERTAS == "abierta ahora"
    sql = s.consultas[0]
    assert "NOT IN ('cerrada', 'descartada')" in sql and "CASE" in sql and "'SILENCIO'" in sql
    assert sql.index("CASE") < sql.index("detectada_en DESC")
    assert respuesta.atencion_inmediata(None, "SILENCIO") == []


def test_alertas_de_la_fecha_usan_el_dia_de_bogota():
    s = _SesionFalsa([_alerta_falsa(estado="cerrada")])
    (fila,) = respuesta.alertas_de_la_fecha(s, "SILENCIO", FECHA)
    assert fila["alcance"] == respuesta.ALCANCE_FECHA and fila["estado"] == "cerrada"
    assert fila["ventana_inicio"] == "2025-10-15T08:00:00-05:00"
    sql = s.consultas[0]
    assert "2025-10-15 00:00:00-05:00" in sql and "2025-10-15 23:59:59.999999-05:00" in sql
    assert "NOT IN" not in sql                       # de la fecha: en cualquier estado
    assert respuesta.alertas_de_la_fecha(None, "SILENCIO", FECHA) == []


def test_tabla_plana_una_fila_por_ruta_y_hora(silencio):
    filas = respuesta.tabla_plana(silencio)
    assert len(filas) == 17 and {f["ruta"] for f in filas} == {"SILENCIO"}
    assert all(f["generado_en"].endswith("-05:00") for f in filas)
    assert all(math.isfinite(f["pasajeros_esperados"]) for f in filas)
    assert {"model_id", "calibracion_version", "fuente_pronostico", "umbrales_version", "execution_id"} <= set(filas[0])


def test_payload_de_la_foto_no_guarda_alertas(silencio):
    (bloque,) = silencio["rutas"]
    payload = respuesta._payload_ruta(silencio, bloque)
    assert set(payload) == {"fecha", "tipo_dia", "generado_en", "trazabilidad", "limitaciones", "ruta"}
    assert not {"atencion_inmediata", "alertas_de_la_fecha", "atencion_resumen"} & set(payload["ruta"])
    assert payload["ruta"]["cada_cuanto_despachar"] == bloque["cada_cuanto_despachar"]


def test_leer_sin_base_es_sin_calcular_con_la_pista():
    with pytest.raises(respuesta.SinCalcular) as error:
        respuesta.leer(None, "CRA 54", FECHA)
    detalle = error.value.detalle
    assert detalle["pista"] == "POST /api/v1/respuesta/calcular" and detalle["rol_requerido"] == "analista"
    assert detalle["cuerpo_sugerido"] == {"fecha": "2025-10-15", "rutas": ["CRA 54"]}


# ---------------------------------------------------------------- router (sin base): 422 por ruta y 404 sin_calcular
@pytest.fixture(scope="module")
def cliente_router():
    from app.db import obtener_sesion
    from app.routers import respuesta as router_respuesta
    from app.routers.comun import ErrorApi

    app = FastAPI()
    app.include_router(router_respuesta.router, prefix="/api/v1")
    app.dependency_overrides[obtener_sesion] = lambda: None

    @app.exception_handler(ErrorApi)
    async def _error(_r: Request, exc: ErrorApi):
        return JSONResponse(status_code=exc.status, content={"error": {"codigo": exc.codigo, "mensaje": exc.mensaje,
                                                                       "detalle": exc.detalle}})

    @app.exception_handler(RequestValidationError)
    async def _validacion(_r: Request, exc: RequestValidationError):
        return JSONResponse(status_code=422, content={"error": {"codigo": "validacion",
                                                                "detalle": [list(e["loc"]) for e in exc.errors()]}})

    return TestClient(app)


def test_router_ruta_fuera_de_la_lista_blanca_422(cliente_router):
    for valor in ("RUTA X", "silencio", "1; DROP TABLE x"):
        r = cliente_router.get("/api/v1/respuesta", params={"ruta": valor})
        assert r.status_code == 422 and r.json()["error"]["codigo"] == "validacion", valor
        assert ["query", "ruta"] in r.json()["error"]["detalle"]
    assert cliente_router.get("/api/v1/respuesta", params={"fecha": "2025-13-01"}).status_code == 422
    r = cliente_router.post("/api/v1/respuesta/calcular", json={"fecha": "2025-11-19", "rutas": ["RUTA X"]})
    assert r.status_code == 422


def test_router_sin_foto_404_sin_calcular_con_la_pista(cliente_router):
    r = cliente_router.get("/api/v1/respuesta", params={"fecha": "2025-11-19", "ruta": "CL 72"})
    assert r.status_code == 404
    error = r.json()["error"]
    assert error["codigo"] == "sin_calcular"
    assert error["detalle"]["pista"] == "POST /api/v1/respuesta/calcular"
    assert error["detalle"]["fecha"] == "2025-11-19"
    r = cliente_router.get("/api/v1/respuesta")                    # sin fecha: el día siguiente al último dato
    assert r.status_code == 404 and r.json()["error"]["detalle"]["fecha"] == \
        respuesta.fecha_por_omision(None).isoformat()
    assert cliente_router.get("/api/v1/respuesta/export", params={"fecha": "2030-01-01"}).status_code == 404


def test_hora_limitada_por_el_headway_minimo_es_no_viable_con_su_motivo():
    """CRA 54, 19-nov-2025, con un mínimo gobernado de 3 min: toda hora donde la demanda pide más salidas de las que
    permite floor(minutos / 3) sale no viable, programa ese tope (mejor aproximación ejecutable) y lo dice."""
    model_id = respuesta.modelo_vigente(None)["model_id"]
    bloque = respuesta._bloque_ruta("CRA 54", date(2025, 11, 19), model_id, {"headway_minimo_min": 3.0}, None)
    limitadas = [h for h in bloque["cada_cuanto_despachar"] if "headway mínimo gobernado" in (h["motivo"] or "")]
    assert limitadas
    for h in limitadas:
        assert h["viable"] is False and h["headway_min"] >= 3.0 - 0.01
        pedidas = int(re.search(r"pide (\d+) salidas", h["motivo"]).group(1))
        maximo = int(re.search(r"permite como máximo (\d+)", h["motivo"]).group(1))
        assert pedidas > maximo == h["buses_hora"]
    otras = [h for h in bloque["cada_cuanto_despachar"] if h not in limitadas and h["buses_hora"] >= 2]
    assert all(h["headway_min"] >= 3.0 - 0.01 for h in otras)


def test_dia_siguiente_al_ultimo_dato_con_el_modelo_activo():
    """«Datos recientes»: el día siguiente al último dato se planea con el pronóstico del modelo activo; plan y
    pasajeros salen del mismo pronóstico hora por hora."""
    if respuesta._plan_dia_disponible() is None or respuesta.pronostico_plan() != "activo":
        pytest.skip("sin optimizacion.plan_dia el plan solo existe para 2025")
    fecha = respuesta.fecha_por_omision(None)
    r = respuesta.componer(None, "CRA 54", fecha)
    assert r["fecha"] == fecha.isoformat() and r["trazabilidad"]["fuente_pronostico"] == "modelo_activo"
    assert r["trazabilidad"]["datos_hasta"] == (fecha - timedelta(days=1)).isoformat()
    plan = _plan_referencia("CRA 54", fecha, r)
    (ruta,) = r["rutas"]
    por_hora = {p["hora"]: p for p in ruta["pasajeros_esperados"]["por_hora"]}
    for h, fila in zip(plan["horas"], ruta["cada_cuanto_despachar"], strict=True):
        # «esperado» va con un decimal y «pasajeros_previstos» con dos: difieren a lo más en el redondeo (0,05)
        assert h["pasajeros_previstos"] == pytest.approx(por_hora[h["hora"]]["esperado"], abs=0.05 + 1e-9)
        assert fila["buses_hora"] == h["salidas"] and fila["headway_min"] == h["headway_min"]
    assert any("mismo pronóstico" in x for x in r["limitaciones"])


def test_sin_plan_dia_el_respaldo_es_e12_y_solo_2025(monkeypatch):
    monkeypatch.setattr(respuesta, "_plan_dia_disponible", lambda: None)
    r = respuesta.componer(None, "CL 72", date(2025, 11, 19))
    assert r["trazabilidad"]["fuente_pronostico"] == "E12" and "E12" in r["limitaciones"][0]
    with pytest.raises(respuesta.SinDatos):
        respuesta.componer(None, "CL 72", respuesta.fecha_por_omision(None))


def test_sin_carga_critica_la_sobreocupacion_queda_en_null():
    import pandas as pd

    tb = pd.DataFrame([{"hora": 7, "ciclo": 120.0, "dist": 60.0, "minutos": 60.0, "pax_pred": 500.0, "cv_d4": 0.6}])
    r = respuesta._comparacion_oferta(tb, {7: 6.0}, {"COSTO_BUS_HORA": 26400.0, "COSTO_KM": 1991.0})
    assert r["sobreocupacion_pasajeros"] is None and r["vehiculos_hora"] == pytest.approx(12.0)
    assert r["espera_media_min"] == pytest.approx(60 / 6 / 2 * (1 + 0.6 ** 2))
    assert r["costo_operativo_cop"] == pytest.approx(12.0 * 26400.0 + 6 * 60.0 * 1991.0)


def test_la_foto_reutiliza_el_plan_que_el_ciclo_acaba_de_calcular(monkeypatch):
    """El ciclo diario pasa a precalcular los planes que acaba de persistir (filas origen = 'plan_dia'): la respuesta
    los usa tal cual, sin volver a resolver el MILP, y dice las mismas salidas hora por hora que ese plan."""
    from app.servicios import optimizacion

    model_id = respuesta.modelo_vigente(None)["model_id"]
    del_ciclo = optimizacion.plan_dia(FECHA, "CRA 54", umbrales={}, umbrales_version=None, model_id=model_id)
    sin_planes = respuesta.componer(None, "CRA 54", FECHA)

    def no_resolver(*_a, **_k):
        raise AssertionError("la foto no debe volver a resolver el plan que trae el ciclo")

    monkeypatch.setattr(optimizacion, "plan_dia", no_resolver)
    planes = {"CRA 54": del_ciclo}
    con_planes = respuesta.componer(None, "CRA 54", FECHA, planes=planes)
    assert planes["CRA 54"] is del_ciclo

    def sin_atencion(r):     # las alertas llevan el instante de la consulta; el resto debe coincidir exactamente
        return [{k: v for k, v in b.items() if k not in ("atencion_inmediata", "alertas_de_la_fecha",
                                                         "atencion_resumen")} for b in r["rutas"]]

    assert sin_atencion(con_planes) == sin_atencion(sin_planes)       # mismo resultado que calculándolo
    filas = con_planes["rutas"][0]["cada_cuanto_despachar"]
    assert [f["buses_hora"] for f in filas] == [h["salidas"] for h in del_ciclo["horas"]]
    assert [f["headway_min"] for f in filas] == [h["headway_min"] for h in del_ciclo["horas"]]


def test_la_foto_del_ciclo_queda_con_la_version_de_umbrales_del_ciclo(monkeypatch):
    """§5.1 con RNF-005: el ciclo pasa a precalcular la versión de umbrales de su ejecución (en una ejecución partida
    por ruta, la fijada al crearla). La foto queda con esa versión y reutiliza el plan del ciclo aunque la vigente sea
    otra (aquí, sin base, no hay vigente)."""
    from app.servicios import optimizacion

    model_id = respuesta.modelo_vigente(None)["model_id"]
    del_ciclo = optimizacion.plan_dia(FECHA, "CRA 54", umbrales={}, umbrales_version=7, model_id=model_id)

    def no_resolver(*_a, **_k):
        raise AssertionError("la foto no debe volver a resolver el plan que trae el ciclo")

    monkeypatch.setattr(optimizacion, "plan_dia", no_resolver)
    r = respuesta.componer(None, "CRA 54", FECHA, planes={"CRA 54": del_ciclo}, umbrales=(7, {}))
    assert r["trazabilidad"]["umbrales_version"] == 7
    filas = r["rutas"][0]["cada_cuanto_despachar"]
    assert [f["buses_hora"] for f in filas] == [h["salidas"] for h in del_ciclo["horas"]]


def test_la_foto_dice_que_planes_reutilizo_y_cuales_volvio_a_resolver():
    """C2: el plan de otro modelo (el modelo activo cambió entre el plan del ciclo y la foto) se vuelve a resolver con
    el modelo de la foto y lo reemplaza; la respuesta lo dice en «planes», con el motivo. Uno que sirve se reutiliza y
    una ruta sin plan se calcula aquí."""
    from app.servicios import optimizacion

    model_id = respuesta.modelo_vigente(None)["model_id"]
    del_ciclo = optimizacion.plan_dia(FECHA, "CRA 54", umbrales={}, umbrales_version=None, model_id=model_id)
    planes = {"CRA 54": dict(del_ciclo, model_id="modelo_anterior")}
    r = respuesta.componer(None, fecha=FECHA, rutas=["CRA 54", "CL 72"], planes=planes)
    uso = r["planes"]
    assert (uso["reutilizados"], uso["recalculados"], uso["calculados"]) == ([], ["CRA 54"], ["CL 72"])
    assert "modelo_anterior" in uso["motivos"]["CRA 54"] and model_id in uso["motivos"]["CRA 54"]
    assert set(uso["motivos"]) == {"CRA 54"}
    assert planes["CRA 54"]["model_id"] == model_id and set(planes) == {"CRA 54", "CL 72"}   # el nuevo lo reemplaza
    otra = respuesta.componer(None, fecha=FECHA, rutas=["CRA 54"], planes={"CRA 54": del_ciclo})
    assert otra["planes"] == {"reutilizados": ["CRA 54"], "recalculados": [], "calculados": [], "motivos": {}}
    assert "planes" not in respuesta._payload_ruta(r, r["rutas"][0])       # no va en la foto guardada


def test_el_plan_vuelto_a_resolver_conserva_la_restriccion_reactiva_del_ciclo():
    """§10.1 con C2: el plan de un ciclo intradía trae el piso de la ocupación actual (ocupacion_actual). Si la foto lo
    vuelve a resolver porque el modelo activo cambió, lo hace con la misma restricción: la hora en que actúa no baja
    del piso y el plan nuevo lo dice."""
    from app.servicios import ocupacion, optimizacion

    model_id = respuesta.modelo_vigente(None)["model_id"]
    reactiva = {"aplica": True, "hora_aplica": 9, "hora_cerrada": 8, "segmento": 34, "ocupacion_observada": 0.97,
                "carga_critica_pax_h": 2400.0, "umbral_critico": 0.9, "fecha_plan": FECHA.isoformat(),
                "motivo": "En la última hora cerrada la ocupación observada fue 97 %.",
                "naturaleza": ocupacion.NATURALEZA_REACTIVA}
    optimizacion.limpiar_cache_plan()
    sin_piso = optimizacion.plan_dia(FECHA, "CRA 54", umbrales={}, umbrales_version=None, model_id=model_id)
    del_ciclo = optimizacion.plan_dia(FECHA, "CRA 54", umbrales={}, umbrales_version=None, model_id=model_id,
                                      ocupacion_actual=reactiva)
    piso = del_ciclo["ocupacion_actual"]["salidas_minimas"]
    nueve = {h["hora"]: h["salidas"] for h in sin_piso["horas"]}[9]
    assert del_ciclo["ocupacion_actual"]["aplica"] is True and piso > nueve         # el piso sí cambia la hora
    planes = {"CRA 54": dict(del_ciclo, model_id="modelo_anterior")}
    r = respuesta.componer(None, fecha=FECHA, rutas=["CRA 54"], planes=planes)
    assert r["planes"]["recalculados"] == ["CRA 54"]
    nuevo = planes["CRA 54"]
    assert nuevo["model_id"] == model_id and nuevo["ocupacion_actual"]["aplica"] is True
    assert {h["hora"]: h["salidas"] for h in nuevo["horas"]}[9] >= piso
    filas = {f["hora"]: f["buses_hora"] for f in r["rutas"][0]["cada_cuanto_despachar"]}
    assert filas[9] >= piso                                                          # la foto dice lo mismo
    assert respuesta._reactiva_del_plan(sin_piso) is None and respuesta._reactiva_del_plan(None) is None


def test_el_motivo_de_volver_a_resolver_el_plan():
    plan = {"horas": [{"hora": 4}], "fuente_pronostico": "modelo_activo", "model_id": "m1", "umbrales_version": 3}
    assert respuesta._motivo_no_reutilizable(plan, "m1", 3, "activo") is None
    assert "m1" in respuesta._motivo_no_reutilizable(plan, "m2", 3, "activo")
    assert "versión de umbrales" in respuesta._motivo_no_reutilizable(plan, "m1", 4, "activo")
    assert "pronóstico" in respuesta._motivo_no_reutilizable(plan, "m1", 3, "E12")
    assert "horas" in respuesta._motivo_no_reutilizable({"horas": []}, "m1", 3, "activo")
    assert respuesta.reutilizacion_del_plan(None, plan, "m1", 3, "activo") == {"estado": "calculado", "motivo": None}
    assert respuesta.reutilizacion_del_plan(plan, plan, "m1", 3, "activo")["estado"] == "reutilizado"
    otro = dict(plan)
    assert respuesta.reutilizacion_del_plan(plan, otro, "m1", 3, "activo")["motivo"].startswith("el plan del día")


def test_un_plan_de_otro_modelo_o_version_no_se_reutiliza():
    plan = {"horas": [{"hora": 4}], "fuente_pronostico": "modelo_activo", "model_id": "m1", "umbrales_version": 3}
    assert respuesta._plan_reutilizable(plan, "m1", 3, "activo")
    assert not respuesta._plan_reutilizable(plan, "m2", 3, "activo")
    assert not respuesta._plan_reutilizable(plan, "m1", 4, "activo")
    assert not respuesta._plan_reutilizable(plan, "m1", 3, "E12")
    assert not respuesta._plan_reutilizable(dict(plan, fuente_pronostico="E12"), "m1", 3, "activo")
    assert not respuesta._plan_reutilizable(None, "m1", 3, "activo")
