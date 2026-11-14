"""Gobierno de los parámetros contra el PostgreSQL local, con la autenticación encendida (§5.1 «regla de gobierno»,
§3.1 «Gestión operacional», §6.1, §6.2, §10.2).

- Migración 0010: siembra en threshold_config la tarifa, la elasticidad y la suavidad del plan (los valores del
  código), agrega a recommendation el headway vigente de rutas.frecuenciadespachos y su diferencia, y su bajada deja
  todo como estaba.
- Todo umbral o parámetro que el código usa con un valor por omisión está en la versión vigente de threshold_config.
- PUT /thresholds cambia tarifa, elasticidad y suavidad sin reiniciar ni recompilar: el siguiente plan
  (POST /respuesta/calcular, leído con GET /recommendations/plan) los usa con su fuente y la respuesta del reto recauda
  con la tarifa nueva.
- PUT /catalogos/flota (admin) registra una versión nueva de la flota o del ciclo, firmada y con motivo; la franja de
  §10.2 y el plan del día la usan; el historial muestra cada cambio.
- La recomendación guarda y expone el headway vigente de rutas.frecuenciadespachos junto al intervalo programado.
- El ciclo marca los datos tardíos (OPOR-001) con el umbral vigente de §5.1 «datos atrasados», no con una cifra del
  código.

Las respuestas reales quedan como evidencia con tests/evidencia.guardar_evidencia (en docs/evidencias/ solo con
GENERAR_EVIDENCIAS=1). Cada prueba deja los parámetros como los encontró.
"""
from __future__ import annotations

import importlib.util
import io
import json
import uuid
from datetime import date

import pytest
from sqlalchemy import func, select, text

from app.modelos_db import Recomendacion, Umbral
from tests.evidencia import guardar_evidencia
from tests.integracion.conftest import restituir_umbrales

FECHA = "2025-10-15"                         # miércoles laboral con variables del modelo (respuesta del reto)
CUERPO = {"ruta": "CRA 54", "hora": 7, "fecha": "2025-03-04", "demanda_hora": 1000, "demanda_p90": 1180,
          "demanda_p10": 850}


@pytest.fixture
def auth(cliente, monkeypatch):
    from app.config import obtener_ajustes

    monkeypatch.setattr(obtener_ajustes(), "auth_habilitada", True)
    return cliente


def _h(clave: str) -> dict:
    return {"X-API-Key": clave}


def _guardar(nombre: str, datos) -> None:
    guardar_evidencia(nombre, json.dumps(datos, ensure_ascii=False, indent=1, default=str) + "\n")


def _migracion_0010():
    from tests.integracion.conftest import RAIZ

    spec = importlib.util.spec_from_file_location(
        "m0010", RAIZ / "alembic" / "versions" / "0010_parametros_plan_y_frecuenciadespachos.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def _plan_por_api(cliente, cabeceras: dict, ruta: str, fecha: str) -> dict:
    """El plan del día como lo pide la operación: POST /respuesta/calcular (la cola lo calcula con los parámetros
    vigentes y lo persiste) y GET /recommendations/plan (lo lee de lo persistido)."""
    r = cliente.post("/api/v1/respuesta/calcular", json={"fecha": fecha, "rutas": [ruta]}, headers=cabeceras)
    assert r.status_code == 202, r.text[:300]
    e = cliente.get(f"/api/v1/frequency/executions/{r.json()['execution_id']}", headers=cabeceras).json()
    assert e["estado"] == "ok", e
    plan = cliente.get("/api/v1/recommendations/plan", params={"ruta": ruta, "fecha": fecha}, headers=cabeceras)
    assert plan.status_code == 200, plan.text[:300]
    return plan.json()


def _salidas(plan: dict) -> list[int]:
    return [h["salidas"] for h in plan["horas"]]


# ---------------------------------------------------------------- migración 0010
def test_migracion_0010_siembra_los_parametros_del_plan_y_las_columnas(migrada, sesion):
    """La 0010 copia los valores del código (param_d5 y PARAMETROS_PLAN), crea UNA versión nueva vigente, agrega las
    dos columnas de recommendation y bajarla borra solo sus filas y sus columnas."""
    from app.servicios.motor_d5 import comun as C
    from app.servicios.optimizacion import PARAMETROS_PLAN
    from tests.integracion.conftest import _alembic

    m = _migracion_0010()
    d5 = C.param_d5(fuente=True)
    assert {n: (v, d) for n, v, d in m.PARAMETROS_0010} == {n: (d5[clave], descripcion)
                                                             for n, (clave, descripcion) in PARAMETROS_PLAN.items()}

    def vigentes():
        sesion.expire_all()
        filas = sesion.execute(select(Umbral.nombre, Umbral.valor, Umbral.version, Umbral.creado_por)
                               .where(Umbral.vigente)).all()
        return {f.nombre: f for f in filas}

    def de_la_0010():
        return sesion.scalar(select(func.count()).select_from(Umbral).where(Umbral.creado_por == m.CREADO_POR))

    def columnas() -> set[str]:
        with sesion.get_bind().connect() as c:
            return set(c.execute(text("SELECT column_name FROM information_schema.columns WHERE table_schema = "
                                      "'ai_frecuencias' AND table_name = 'recommendation'")).scalars())

    assert set(m.COLUMNAS_0010) <= columnas() and set(PARAMETROS_PLAN) <= set(vigentes())
    sesion.commit()
    try:
        _alembic("downgrade", m.down_revision)
        assert de_la_0010() == 0 and not set(m.COLUMNAS_0010) & columnas()
        antes = vigentes()
        assert antes and len({f.version for f in antes.values()}) == 1
    finally:
        sesion.rollback()
        _alembic("upgrade", "head")
    despues = vigentes()
    assert set(m.COLUMNAS_0010) <= columnas()
    assert len({f.version for f in despues.values()}) == 1 and set(antes) | set(PARAMETROS_PLAN) <= set(despues)
    assert {n: despues[n].valor for n, _v, _d in m.PARAMETROS_0010 if n not in antes} == {
        n: v for n, v, _d in m.PARAMETROS_0010 if n not in antes}
    assert de_la_0010() == len(set(antes) | set(PARAMETROS_PLAN))     # el conjunto completo, en UNA versión


def test_todos_los_umbrales_que_usa_el_codigo_estan_en_postgresql(migrada, sesion):
    """§5.1 «todos los umbrales se guardan en PostgreSQL»: los umbrales de las alertas, del monitoreo y de la política
    de aprendizaje, los pesos y costos de §10.2, los parámetros del plan y la tolerancia de oportunidad de la calidad
    están en la versión vigente de threshold_config, con su descripción (el código solo guarda el valor por omisión de
    una instalación sin migrar)."""
    from app.servicios import consolidados, monitoreo, politica, retencion
    from app.servicios.alertas import UMBRALES_POR_DEFECTO
    from app.servicios.optimizacion import PARAMETROS_OBJETIVO, PARAMETROS_PLAN

    filas = {f.nombre: f for f in sesion.scalars(select(Umbral).where(Umbral.vigente))}
    grupos = {"alertas (alertas.UMBRALES_POR_DEFECTO)": set(UMBRALES_POR_DEFECTO) - {"version"},
              "monitoreo (monitoreo.UMBRALES_DEFECTO)": set(monitoreo.UMBRALES_DEFECTO),
              "política de aprendizaje (politica.UMBRALES_DEFECTO)": set(politica.UMBRALES_DEFECTO),
              "función objetivo §10.2 (optimizacion.PARAMETROS_OBJETIVO)": set(PARAMETROS_OBJETIVO),
              "plan del día (optimizacion.PARAMETROS_PLAN)": set(PARAMETROS_PLAN),
              "headway §5.1": {"headway_minimo_min", "headway_maximo_min"},
              "oportunidad de la calidad §6.3 (calidad.retraso_maximo_de)": {"periodos_atraso", "periodo_ingesta_min"},
              "retención de datos §18 (retencion.PARAMETROS)": set(retencion.PARAMETROS),
              "contraste de los consolidados §6.3 y §11.2 (consolidados.TOLERANCIAS_POR_DEFECTO)":
                  set(consolidados.TOLERANCIAS_POR_DEFECTO)}
    faltan = {g: sorted(n - set(filas)) for g, n in grupos.items() if n - set(filas)}
    assert not faltan, faltan
    assert all(filas[n].descripcion for g in grupos.values() for n in g)
    assert len({f.version for f in filas.values()}) == 1
    _guardar("gobierno/umbrales_en_postgresql.json", {
        "version_vigente": next(iter(filas.values())).version,
        "grupos": {g: {n: {"valor": filas[n].valor, "creado_por": filas[n].creado_por,
                           "descripcion": filas[n].descripcion} for n in sorted(nombres)}
                   for g, nombres in grupos.items()}})


# ---------------------------------------------------------------- tarifa, elasticidad y suavidad por PUT /thresholds
def test_put_thresholds_cambia_tarifa_elasticidad_y_suavidad_y_el_siguiente_plan_los_usa(auth, claves_prueba, sesion):
    from app.servicios.optimizacion import PARAMETROS_PLAN

    admin, analista = _h(claves_prueba["admin"]), _h(claves_prueba["analista"])
    antes = auth.get("/api/v1/thresholds", headers=admin).json()
    originales = {n: antes["valores"][n] for n in PARAMETROS_PLAN}
    detalle = {d["nombre"]: d for d in antes["detalle"]}
    assert all(detalle[n]["descripcion"] == PARAMETROS_PLAN[n][1] for n in PARAMETROS_PLAN)
    plan_antes = _plan_por_api(auth, analista, "CRA 54", FECHA)
    assert plan_antes["umbrales_version"] == antes["version"]
    assert plan_antes["parametros"]["delta_suavidad"] == {"valor": float(originales["delta_suavidad"]),
                                                          "fuente": f"threshold_config v{antes['version']}"}
    for valores in ({"elasticidad": 1.5}, {"delta_suavidad": 0}, {"hora_inicio_suavidad": 7.5},
                    {"hora_inicio_suavidad": 5}, {"tarifa_cop": -1}):
        malo = auth.put("/api/v1/thresholds", json={"valores": valores, "motivo": "inválido"}, headers=admin)
        assert malo.status_code == 422 and malo.json()["error"]["codigo"] == "umbral_invalido", valores
    nuevos = {"tarifa_cop": 2800, "elasticidad": 0.3, "delta_suavidad": 2}
    assert auth.put("/api/v1/thresholds", json={"valores": nuevos, "motivo": "x"}, headers=analista).status_code == 403
    r = auth.put("/api/v1/thresholds", json={"valores": nuevos, "creado_por": "suplantador",
                                             "motivo": "§5.1: parámetros del plan sin recompilar"}, headers=admin)
    assert r.status_code == 200, r.text
    version = r.json()["version"]
    try:
        assert r.json()["estado"] == "propuesta" and version == antes["version"] + 1
        plan = _plan_por_api(auth, analista, "CRA 54", FECHA)
        assert plan["umbrales_version"] == version
        fuente = f"threshold_config v{version}"
        assert {n: plan["parametros"][n] for n in nuevos} == {n: {"valor": float(v), "fuente": fuente}
                                                              for n, v in nuevos.items()}
        assert plan["parametros"]["hora_inicio_suavidad"]["fuente"] == fuente      # el conjunto completo
        assert _salidas(plan) != _salidas(plan_antes)
        minutos = [h["minutos_operados"] for h in plan["horas"]]
        for i in range(1, len(minutos)):                   # la suavidad de 2 salidas por hora rige desde las 7 h
            if plan["horas"][i]["hora"] >= 7 and minutos[i] > 0 and minutos[i - 1] > 0:
                cambio = _salidas(plan)[i] / (minutos[i] / 60) - _salidas(plan)[i - 1] / (minutos[i - 1] / 60)
                assert abs(cambio) <= 2 + 1e-6
        respuesta = auth.get("/api/v1/respuesta", params={"ruta": "CRA 54", "fecha": FECHA}, headers=analista)
        assert respuesta.status_code == 200, respuesta.text[:300]
        (bloque,) = respuesta.json()["rutas"]
        fr = bloque["flota_y_recaudo"]
        assert fr["tarifa_neta_cop"] == 2800.0
        assert fr["recaudo_esperado_cop"] == round(bloque["pasajeros_esperados"]["dia"] * 2800)
        assert fuente in fr["nota"] and respuesta.json()["trazabilidad"]["umbrales_version"] == version
        historia = auth.get("/api/v1/thresholds/history", params={"nombre": "delta_suavidad"}, headers=admin).json()
        assert historia[0]["version"] == version and historia[0]["valor"] == 2
        assert historia[0]["creado_por"] == "prueba_admin"                    # firma el autenticado
        # §5.1: la versión queda «propuesta» hasta que el área operativa la aprueba, como cualquier umbral
        aprobada = auth.post(f"/api/v1/thresholds/{version}/aprobar", headers=admin,
                             json={"comentario": "validación de los parámetros del plan (prueba)"})
        assert aprobada.status_code == 200 and aprobada.json()["estado"] == "aprobada"
        assert aprobada.json()["aprobado_por"] == "prueba_admin"
        _guardar("gobierno/parametros_plan_gobernados.json", {
            "antes": {"umbrales_version": antes["version"], "parametros": {n: plan_antes["parametros"][n]
                                                                           for n in PARAMETROS_PLAN},
                      "salidas_por_hora": _salidas(plan_antes), "componentes_costo_cop":
                          plan_antes["componentes_costo_cop"]},
            "put_thresholds": {"valores": nuevos, "version_nueva": version, "estado": r.json()["estado"]},
            "despues": {"umbrales_version": plan["umbrales_version"], "parametros": {n: plan["parametros"][n]
                                                                                    for n in PARAMETROS_PLAN},
                        "salidas_por_hora": _salidas(plan), "componentes_costo_cop": plan["componentes_costo_cop"]},
            "respuesta_reto": {"tarifa_neta_cop": fr["tarifa_neta_cop"], "recaudo_esperado_cop":
                               fr["recaudo_esperado_cop"], "nota": fr["nota"]},
            "historial_delta_suavidad": historia[:2]})
    finally:
        restituir_umbrales(sesion, antes["version"])


# ---------------------------------------------------------------- flota y tiempo de ciclo por la API
def _tipo(salida: dict, tipo_dia: str) -> dict:
    return next(t for t in salida["por_tipo_dia"] if t["tipo_dia"] == tipo_dia)


def _franja(cliente, cabeceras: dict) -> dict:
    r = cliente.post("/api/v1/recommendations/calculate", json=CUERPO, headers=cabeceras)
    assert r.status_code == 201, r.text[:300]
    return r.json()


def _resumen_franja(x: dict) -> dict:
    return {k: x.get(k) for k in ("umbrales_version", "viable", "buses_hora", "headway_min", "vehiculos_requeridos",
                                  "motivo")} | {"contexto_franja": {k: (x.get("contexto_franja") or {}).get(k) for k in
                                                                    ("flota_disponible", "tiempo_ciclo_min",
                                                                     "ajuste_operativo")}}


def _validaciones_flota(cliente, admin: dict) -> list[dict]:
    casos = [({"idruta": 999, "flota": 40, "motivo": "ruta inexistente"}, 422, "ruta_desconocida"),
             ({"idruta": 16, "flota": 0, "motivo": "flota cero"}, 422, "validacion"),
             ({"idruta": 16, "tiempo_ciclo_min": 5, "motivo": "ciclo de 5 min"}, 422, "validacion"),
             ({"idruta": 16, "flota": 40, "hora": 7, "motivo": "hora sin ciclo"}, 422, "ajuste_invalido"),
             ({"idruta": 16, "motivo": "sin cambios"}, 422, "ajuste_invalido"),
             ({"idruta": 16, "flota": 40, "motivo": ""}, 422, "validacion"),
             ({"idruta": 16, "tipo_dia": "Lunes", "flota": 40, "motivo": "tipo de día"}, 422, "validacion"),
             ({"idruta": 16, "tipo_dia": "Sábado", "flota": None, "motivo": "no existe"}, 404, "ajuste_inexistente")]
    salida = []
    for cuerpo, estado, codigo in casos:
        r = cliente.put("/api/v1/catalogos/flota", json=cuerpo, headers=admin)
        assert (r.status_code, r.json()["error"]["codigo"]) == (estado, codigo), (cuerpo, r.text[:300])
        salida.append({"cuerpo": cuerpo, "estado": r.status_code, "codigo": codigo})
    return salida


def test_flota_y_ciclo_por_la_api_versionados_auditados_y_usados_por_la_franja_y_el_plan(auth, claves_prueba,
                                                                                         sesion, umbrales_restituidos):
    """Los retiros del final son parte de lo que se prueba (el historial los registra); umbrales_restituidos borra
    después todas las versiones que creó la prueba."""
    admin, analista, operador = (_h(claves_prueba[r]) for r in ("admin", "analista", "operador"))
    antes = auth.get("/api/v1/thresholds", headers=admin).json()
    inicial = auth.get("/api/v1/catalogos/flota", params={"idruta": 16, "tipo_dia": "Laboral"}, headers=operador)
    assert inicial.status_code == 200, inicial.text[:300]
    laboral = _tipo(inicial.json()[0], "Laboral")
    assert (laboral["flota"], laboral["flota_fuente"]) == (79, "catalogo") and len(laboral["horas"]) == 17
    otra = auth.get("/api/v1/catalogos/flota", params={"idruta": 999}, headers=operador)
    assert otra.status_code == 404 and otra.json()["error"]["codigo"] == "no_encontrado"
    cuerpo = {"idruta": 16, "tipo_dia": "Laboral", "flota": 40, "motivo": "Flota operativa confirmada (prueba)",
              "creado_por": "suplantador"}
    for rol in ("operador", "analista"):
        r = auth.put("/api/v1/catalogos/flota", json=cuerpo, headers=_h(claves_prueba[rol]))
        assert r.status_code == 403 and r.json()["error"]["detalle"]["rol_requerido"] == "admin"
    franja_antes, plan_antes = _franja(auth, analista), _plan_por_api(auth, analista, "CRA 54", FECHA)
    assert franja_antes["viable"] and franja_antes["contexto_franja"]["flota_disponible"] == 79
    try:
        r = auth.put("/api/v1/catalogos/flota", json=cuerpo, headers=admin)
        assert r.status_code == 200, r.text[:300]
        con_flota = r.json()
        assert con_flota["umbrales_version"] == antes["version"] + 1
        laboral = _tipo(con_flota, "Laboral")
        assert (laboral["flota"], laboral["flota_catalogo"], laboral["flota_fuente"], laboral["flota_clave"]) == (
            40, 79, "ajuste_local", "flota_override.16.LABORAL")
        assert _tipo(con_flota, "Sábado")["flota_fuente"] == "catalogo"
        detalle = auth.get("/api/v1/catalogos/rutas/16", headers=operador).json()["flota_y_ciclo"]
        assert _tipo(detalle, "Laboral")["flota"] == 40 and detalle["umbrales_version"] == con_flota["umbrales_version"]
        # el resto del conjunto gobernado no cambia; la versión nueva queda «propuesta» hasta su aprobación (§5.1)
        despues = auth.get("/api/v1/thresholds", headers=admin).json()
        assert despues["version"] == con_flota["umbrales_version"] and despues["estado"] == "propuesta"
        assert {k: v for k, v in despues["valores"].items() if not k.startswith("flota_override.")} == \
            antes["valores"]
        # la franja de §10.2 usa la flota nueva desde la versión siguiente: con 40 vehículos ya no es viable
        franja = _franja(auth, analista)
        assert franja["umbrales_version"] == con_flota["umbrales_version"]
        ajuste = franja["contexto_franja"]["ajuste_operativo"]["flota_disponible"]
        assert (franja["contexto_franja"]["flota_disponible"], ajuste["clave"]) == (40, "flota_override.16.LABORAL")
        assert franja["viable"] is False and "40 vehículos" in franja["motivo"]
        # el plan del día también
        plan = _plan_por_api(auth, analista, "CRA 54", FECHA)
        assert plan["umbrales_version"] == con_flota["umbrales_version"] and plan["flota_disponible"] == 40
        assert plan["flota_y_ciclo"]["flota_disponible"] == {"valor": 40.0, "fuente": "ajuste_local",
                                                             "clave": "flota_override.16.LABORAL"}
        assert plan["buses_en_ruta_pico"] <= 40 + (plan["holgura_flota"] or 0.0) + 1e-6 < plan_antes[
            "buses_en_ruta_pico"]
        assert _salidas(plan) != _salidas(plan_antes) and all(h["flota_disponible"] == 40 for h in plan["horas"])
        # ciclo de las 7 h
        r = auth.put("/api/v1/catalogos/flota", headers=admin,
                     json={"idruta": 16, "tipo_dia": "Laboral", "hora": 7, "tiempo_ciclo_min": 150,
                           "motivo": "Ciclo medido en la hora pico (prueba)"})
        assert r.status_code == 200, r.text[:300]
        siete = _tipo(r.json(), "Laboral")["horas"][3]
        assert (siete["hora"], siete["tiempo_ciclo_min"], siete["fuente"]) == (7, 150.0, "ajuste_local")
        con_ciclo = _franja(auth, analista)
        assert con_ciclo["contexto_franja"]["tiempo_ciclo_min"] == 150
        assert con_ciclo["vehiculos_requeridos"] < franja_antes["vehiculos_requeridos"]
        validaciones = _validaciones_flota(auth, admin)
        historial = auth.get("/api/v1/catalogos/flota/historial", params={"idruta": 16}, headers=operador)
        assert historial.status_code == 200 and int(historial.headers["X-Total-Count"]) == len(historial.json())
        eventos = historial.json()
        assert [(e["parametro"], e["tipo_dia"], e["hora"], e["accion"], e["valor_anterior"], e["valor_nuevo"])
                for e in eventos[:2]] == [("tiempo_ciclo_min", "Laboral", 7, "creado", None, 150.0),
                                          ("flota", "Laboral", None, "creado", None, 40.0)]
        assert {e["creado_por"] for e in eventos[:2]} == {"prueba_admin"}               # el cuerpo no suplanta
        assert eventos[1]["motivo"] == cuerpo["motivo"] and eventos[0]["creado_en"].endswith("-05:00")
        n = sesion.execute(text("SELECT count(*) FROM ai_frecuencias.threshold_config WHERE vigente AND "
                                "(nombre LIKE 'flota_override.%' OR nombre LIKE 'ciclo_override.%')")).scalar()
        assert n == 2                                                           # vive solo en ai_frecuencias
        _guardar("gobierno/ajuste_flota_ciclo.json", {
            "antes": {"umbrales_version": antes["version"], "flota_laboral_cra54": _tipo(inicial.json()[0],
                                                                                         "Laboral")["flota"],
                      "franja_7h": _resumen_franja(franja_antes),
                      "plan_del_dia": {"flota_disponible": plan_antes["flota_disponible"], "buses_en_ruta_pico":
                                       plan_antes["buses_en_ruta_pico"], "salidas_por_hora": _salidas(plan_antes)}},
            "roles": "operador y analista: 403 «prohibido» (rol_requerido admin); admin: 200",
            "put_flota_40": {"umbrales_version": con_flota["umbrales_version"], "laboral": {
                k: laboral[k] for k in ("flota", "flota_catalogo", "flota_fuente", "flota_clave")}},
            "franja_7h_con_flota_40": _resumen_franja(franja),
            "plan_del_dia_con_flota_40": {"flota_disponible": plan["flota_disponible"], "flota_y_ciclo":
                                          plan["flota_y_ciclo"], "buses_en_ruta_pico": plan["buses_en_ruta_pico"],
                                          "salidas_por_hora": _salidas(plan)},
            "put_ciclo_7h_150": siete, "franja_7h_con_ciclo_150": _resumen_franja(con_ciclo),
            "validaciones": validaciones, "historial": eventos[:4]})
    finally:
        for retiro in ({"idruta": 16, "tipo_dia": "Laboral", "flota": None, "motivo": "fin de la prueba"},
                       {"idruta": 16, "tipo_dia": "Laboral", "hora": 7, "tiempo_ciclo_min": None,
                        "motivo": "fin de la prueba"}):
            auth.put("/api/v1/catalogos/flota", json=retiro, headers=admin)
    final = auth.get("/api/v1/catalogos/flota", params={"idruta": 16}, headers=operador).json()[0]
    assert final["ajustes"] == {} and _tipo(final, "Laboral")["flota_fuente"] == "catalogo"
    eventos = auth.get("/api/v1/catalogos/flota/historial", params={"idruta": 16, "limite": 2},
                       headers=operador).json()
    assert {e["accion"] for e in eventos} == {"retirado"}


# ---------------------------------------------------------------- un cambio del conjunto gobernado a la vez
def _en_paralelo(primero, segundo) -> list[str]:
    """Corre primero(sesión) y segundo(sesión) en dos hilos, cada uno con su sesión. El segundo arranca cuando el
    primero ya leyó y escribió su versión y está por confirmarla (su commit espera 1 s): los dos cambios se solapan.
    Devuelve los errores de los dos."""
    import threading
    import time

    from app.db import nueva_sesion

    por_confirmar, errores = threading.Event(), []
    a, b = nueva_sesion(), nueva_sesion()
    confirmar = a.commit

    def commit_lento():
        por_confirmar.set()
        time.sleep(1.0)
        confirmar()

    a.commit = commit_lento

    def correr(funcion, s, esperar: bool):
        try:
            if esperar:
                por_confirmar.wait(10)
            funcion(s)
        except Exception as exc:  # noqa: BLE001 - la prueba informa el error
            errores.append(repr(exc))
        finally:
            por_confirmar.set()
            s.close()

    hilos = [threading.Thread(target=correr, args=(primero, a, False)),
             threading.Thread(target=correr, args=(segundo, b, True))]
    for hilo in hilos:
        hilo.start()
    for hilo in hilos:
        hilo.join(30)
    return errores


def test_dos_cambios_simultaneos_del_conjunto_gobernado_no_pierden_parametros(migrada, sesion, umbrales_restituidos):
    """§5.1 «se versionan»: dos cambios a la vez (dos ajustes locales, o un ajuste y un PUT /thresholds) se aplican uno
    después del otro, cada uno sobre la versión que dejó el anterior (ejecucion.bloquear_umbrales). Sin el candado, el
    segundo ajuste dejaba una versión con solo su parámetro (el resto del conjunto dejaba de regir) y el segundo PUT
    /thresholds chocaba con la unicidad de (nombre, version). La prueba comprueba que el retiro deja los valores de
    antes; umbrales_restituidos borra después las versiones que creó."""
    from app.servicios import catalogos, ejecucion

    flota, ciclo = "flota_override.16.LABORAL", "ciclo_override.16.LABORAL.7"

    def ajuste(clave, valor):
        return lambda s: catalogos.versionar_ajustes(s, {clave: valor}, "prueba", "concurrencia (prueba)",
                                                     lambda nombre: f"prueba de concurrencia: {nombre}")

    def umbral(s):
        ejecucion.nueva_version_umbrales(s, {"ocupacion_critica": 0.95}, "prueba", "concurrencia (prueba)")

    def vigentes():
        sesion.rollback()
        return ejecucion.umbrales_vigentes(sesion)

    version, antes = vigentes()
    try:
        assert _en_paralelo(ajuste(flota, 40), ajuste(ciclo, 150)) == []
        assert vigentes() == (version + 2, dict(antes, **{flota: 40, ciclo: 150}))
        assert _en_paralelo(ajuste(flota, None), umbral) == []
        assert vigentes() == (version + 4, dict(antes, **{ciclo: 150, "ocupacion_critica": 0.95}))
        assert len(set(sesion.scalars(select(Umbral.version).where(Umbral.vigente)))) == 1
    finally:
        _, ahora = vigentes()
        retiro = {k: None for k in (flota, ciclo) if k in ahora}
        if retiro:
            catalogos.versionar_ajustes(sesion, retiro, "prueba", "fin de la prueba", str)
        ejecucion.nueva_version_umbrales(sesion, {"ocupacion_critica": antes["ocupacion_critica"]}, "prueba",
                                         "restituir")
    assert vigentes()[1] == antes


# ---------------------------------------------------------------- headway vigente de rutas.frecuenciadespachos
def test_la_recomendacion_guarda_el_headway_vigente_de_frecuenciadespachos(auth, claves_prueba, sesion):
    from app.servicios import ejecucion, optimizacion

    analista = _h(claves_prueba["analista"])
    cuerpo = dict(CUERPO, ruta="CL 72", hora=11, demanda_hora=500, demanda_p90=600, demanda_p10=400,
                  flota_disponible=200, tipologias=False)
    r = auth.post("/api/v1/recommendations/calculate", json=cuerpo, headers=analista)
    assert r.status_code == 201, r.text[:300]
    x = r.json()
    assert x["viable"] and x["frecuenciadespachos_min"] == 5.0
    assert x["diferencia_frecuenciadespachos_min"] == round(x["headway_min"] - 5.0, 2)
    assert x["cambio_frecuenciadespachos"] and "rutas.frecuenciadespachos" in x["fuente_frecuenciadespachos"]
    assert x["frecuencia_actual_min"] and x["diferencia_min"] is not None        # la comparación de antes sigue
    sesion.expire_all()
    fila = sesion.get(Recomendacion, uuid.UUID(x["recommendation_id"]))
    assert (fila.frecuenciadespachos_min, fila.diferencia_frecuenciadespachos_min) == (
        5.0, x["diferencia_frecuenciadespachos_min"])
    listado = auth.get("/api/v1/recommendations", params={"ruta": "CL 72", "limite": 1, "orden": "-creado_en"},
                       headers=analista).json()["items"][0]
    assert listado["recommendation_id"] == x["recommendation_id"]
    assert listado["frecuenciadespachos_min"] == 5.0 and listado["diferencia_frecuenciadespachos_min"] is not None
    csv = auth.get("/api/v1/recommendations/export", params={"formato": "csv", "ruta": "CL 72"}, headers=analista)
    cabecera = csv.content.decode("utf-8-sig").splitlines()[0].split(",")
    assert {"frecuenciadespachos_min", "diferencia_frecuenciadespachos_min", "frecuencia_actual_min"} <= set(cabecera)
    # el plan del día persistido: cada hora con su headway vigente y la diferencia
    version, umbrales = ejecucion.umbrales_vigentes(sesion)
    plan = optimizacion.plan_dia("2031-03-12", "CL 72", umbrales=umbrales, umbrales_version=version,
                                 pronostico_horario=[{"hora": h, "p10": 160.0, "p50": 200.0, "p90": 250.0}
                                                     for h in range(4, 21)])
    try:
        ejecucion.persistir_plan_dia(sesion, None, version, "CL 72", date(2031, 3, 12), plan)
        sesion.commit()
        filas = sesion.scalars(select(Recomendacion).where(Recomendacion.ruta == "CL 72",
                                                           Recomendacion.fecha == date(2031, 3, 12),
                                                           Recomendacion.origen == "plan_dia")).all()
        assert len(filas) == 17 and all(f.frecuenciadespachos_min == 5.0 for f in filas)
        assert all(f.diferencia_frecuenciadespachos_min == round(f.headway_min - 5.0, 2) for f in filas
                   if f.headway_min is not None)
        leido = auth.get("/api/v1/recommendations/plan", params={"ruta": "CL 72", "fecha": "2031-03-12"},
                         headers=analista)
        assert leido.status_code == 200, leido.text[:300]
        leido = leido.json()
        assert leido["frecuenciadespachos_min"] == 5.0 and leido["parametros"]["tarifa_cop"]["fuente"].startswith(
            "threshold_config")
        assert leido["flota_y_ciclo"]["flota_disponible"]["fuente"] == optimizacion.FUENTE_FLOTA_CICLO
        assert all(h["frecuenciadespachos_min"] == 5.0 for h in leido["horas"])
        _guardar("gobierno/frecuenciadespachos.json", {
            "franja": {"solicitud": cuerpo, "headway_min": x["headway_min"],
                       "frecuencia_actual_min (intervalo programado observado)": x["frecuencia_actual_min"],
                       "diferencia_min": x["diferencia_min"], "frecuenciadespachos_min": x["frecuenciadespachos_min"],
                       "diferencia_frecuenciadespachos_min": x["diferencia_frecuenciadespachos_min"],
                       "cambio_frecuenciadespachos": x["cambio_frecuenciadespachos"],
                       "fuente_frecuenciadespachos": x["fuente_frecuenciadespachos"],
                       "explicacion": [t for t in x["explicacion"] if "frecuenciadespachos" in t]},
            "fila_recommendation": {"frecuenciadespachos_min": fila.frecuenciadespachos_min,
                                    "diferencia_frecuenciadespachos_min": fila.diferencia_frecuenciadespachos_min},
            "cabecera_exportacion_csv": cabecera,
            "plan_del_dia": [{k: h.get(k) for k in ("hora", "salidas", "headway_min", "frecuencia_actual_min",
                                                    "frecuenciadespachos_min", "diferencia_frecuenciadespachos_min",
                                                    "cambio_frecuenciadespachos")} for h in leido["horas"]]})
    finally:
        sesion.rollback()
        sesion.execute(text("DELETE FROM ai_frecuencias.recommendation WHERE ruta = 'CL 72' AND fecha = :f AND "
                            "origen = 'plan_dia'"), {"f": date(2031, 3, 12)})
        sesion.commit()


def test_exportacion_xlsx_de_recomendaciones_trae_las_columnas_nuevas(auth, claves_prueba):
    import openpyxl

    analista = _h(claves_prueba["analista"])
    assert auth.post("/api/v1/recommendations/calculate", json=CUERPO, headers=analista).status_code == 201
    xlsx = auth.get("/api/v1/recommendations/export", params={"formato": "xlsx", "ruta": "CRA 54"}, headers=analista)
    assert xlsx.status_code == 200
    hoja = openpyxl.load_workbook(io.BytesIO(xlsx.content)).active
    encabezados = [c.value for c in hoja[1]]
    assert {"frecuenciadespachos_min", "diferencia_frecuenciadespachos_min"} <= set(encabezados)


# ---------------------------------------------------------------- tolerancia de oportunidad de la calidad (§5.1, §6.3)
class _FuenteFija:
    """Entrega siempre el mismo lote y devuelve la marca de agua recibida (no la mueve)."""

    def __init__(self, df):
        self.df = df

    def leer_incremental(self, marca_agua=None, hasta=None):
        return self.df.copy(), marca_agua


def test_el_ciclo_mide_los_datos_tardios_con_el_umbral_vigente_de_datos_atrasados(auth, claves_prueba, sesion,
                                                                                 monkeypatch):
    """§5.1 «datos atrasados» gobierna también la oportunidad de §6.3: con los valores sembrados (2 períodos de 1.440
    min) un registro que llegó 36 h después del cierre de su día no es tardío; una versión nueva con 1 período (PUT
    /thresholds, sin reiniciar) hace que el siguiente ciclo lo marque OPOR-001, no bloqueante, con la tolerancia
    nueva."""
    import pandas as pd
    from sqlalchemy import delete

    from app.modelos_db import Alerta, DemandaObservada, Ejecucion, ErrorCalidad, Prediccion
    from app.servicios import datos, ejecucion

    admin, analista = _h(claves_prueba["admin"]), _h(claves_prueba["analista"])
    dia = date(2024, 6, 12)
    tramo = datos.demanda_horaria(desde=date(2024, 6, 10), hasta=dia).reset_index(drop=True)
    tardia = tramo.index[(tramo["ruta"] == "CRA 54") & (tramo["fecha"] == dia) & (tramo["hora"] == 7)]
    tramo.loc[tardia, "ultima_actualizacion"] = tramo.loc[tardia, "ultima_actualizacion"] + pd.Timedelta(hours=36)
    monkeypatch.setattr(ejecucion, "obtener_fuente", lambda: _FuenteFija(tramo))
    antes = auth.get("/api/v1/thresholds", headers=admin).json()
    originales = {n: antes["valores"][n] for n in ("periodos_atraso", "periodo_ingesta_min")}
    ids: list[str] = []

    def tardios() -> list[dict]:
        r = auth.post("/api/v1/frequency/executions", json={"hasta": dia.isoformat()}, headers=analista)
        assert r.status_code == 202, r.text[:300]
        ids.append(r.json()["execution_id"])
        e = auth.get(f"/api/v1/frequency/executions/{ids[-1]}", headers=analista).json()
        assert e["estado"] == "ok", e.get("mensaje")
        return auth.get(f"/api/v1/frequency/executions/{ids[-1]}/errors", params={"codigo": "OPOR-001"},
                        headers=analista).json()["items"]

    try:
        assert originales == {"periodos_atraso": 2, "periodo_ingesta_min": 1440.0}
        assert tardios() == []                                  # 36 h de retraso: dentro de 2 × 1.440 min
        r = auth.put("/api/v1/thresholds", headers=admin, json={
            "valores": {"periodos_atraso": 1}, "motivo": "§5.1 datos atrasados: un período de ingesta (prueba)"})
        assert r.status_code == 200, r.text[:300]
        (error,) = tardios()
        assert (error["llave"]["ruta"], error["llave"]["hora"], error["bloqueante"]) == ("CRA 54", 7, False)
        assert error["dimension"] == "oportunidad" and "tolerancia 1 day, 0:00:00" in error["detalle"]
        _guardar("gobierno/oportunidad_gobernada.json", {
            "lote": "tramo empaquetado 10 a 12-06-2024; CRA 54 del 12-06-2024 a las 7 h llegó 36 h después del cierre",
            "con_la_version_sembrada": {"umbrales_version": antes["version"], **originales, "OPOR-001": []},
            "put_thresholds": {"valores": {"periodos_atraso": 1}, "version_nueva": r.json()["version"],
                               "estado": r.json()["estado"]},
            "con_la_version_nueva": {"OPOR-001": [{k: error[k] for k in ("codigo", "dimension", "llave", "campo",
                                                                          "bloqueante", "detalle")}]}})
    finally:
        sesion.rollback()
        for modelo in (DemandaObservada, Alerta, Recomendacion, Prediccion, ErrorCalidad, Ejecucion):
            sesion.execute(delete(modelo).where(modelo.execution_id.in_(ids)))
        sesion.commit()
        restituir_umbrales(sesion, antes["version"])
