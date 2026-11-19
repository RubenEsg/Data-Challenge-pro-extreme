"""Integración: la ocupación actual en la operación PROGRAMADA (§10.1, 10.1-d) y los bordes del día en curso.

La fuente es la de tests/integracion/test_ocupacion_ciclo.py: la Parquet real (22/10/2025 y los dos días previos, con un
proceso propio para no mezclar sus marcas de agua con las de otras pruebas) más, para las franjas que pide el ciclo,
viajes con subidas y bajadas por segmento (CL 72 al 100 % a las 7 y 8 h). La fuente no conoce los viajes del día de
progvehiculos (viajes() devuelve None): una hora cerrada cuenta como completa a las 6 h de su fin.

- El planificador encola el ciclo intradía (planificador.tarea_ciclo_intradia, idempotente) con instante = la franja:
  el plan del día EN CURSO y la recomendación de 30 min de la hora siguiente usan la restricción reactiva; el ciclo no
  evalúa el error del modelo, no guarda monitoreo ni aplica la política, no lee los consolidados y no pide el refresco
  de segmentos; mide solo las horas cerradas y no alerta horas que todavía no pasaron.
- Partido por ruta (RNF-005), la madre y su trabajo usan la versión de umbrales fijada al encolarlo aunque llegue un
  PUT /thresholds antes de que corran.
- Una franja que llega con otro ciclo de frecuencia corriendo espera en la cola y lee desde la marca que deja el otro.
- Un episodio observado que el área operativa cerró no se vuelve a abrir cuando el día se relee sin nada nuevo.
- La foto de la respuesta dice qué planes del ciclo reutilizó y cuáles volvió a resolver si el modelo activo cambió a
  mitad de la ejecución (C2).
"""
from __future__ import annotations

import threading
import time
import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from app.db import sesion_contexto
from tests.integracion.conftest import restituir_umbrales
from tests.integracion.test_ocupacion_ciclo import CARGAS, DIA, viajes_sinteticos

E = "ai_frecuencias"
EJECUCIONES: list[uuid.UUID] = []
PREFIJO = "prueba-tiempo-real-"


@pytest.fixture
def fuente(monkeypatch, sesion):
    from zoneinfo import ZoneInfo

    from app.servicios import datos, ejecucion, fuentes, segmentos_refresco

    tramo = datos.demanda_horaria(desde=DIA - timedelta(days=2), hasta=DIA)
    estado = SimpleNamespace(tramo=tramo, proceso=f"{PREFIJO}{uuid.uuid4().hex[:8]}", pedidas=[], refrescos=[],
                             zona=ZoneInfo("America/Bogota"))

    class FuenteEnVivo(fuentes.FuenteParquet):
        def leer_carga_segmentos(self, franjas):
            estado.pedidas.append(list(franjas))
            return fuentes.seudonimizar_conductores(viajes_sinteticos(franjas))

        def viajes(self, ruta, desde, hasta):     # progvehiculos no se conoce: rige la duración máxima del viaje
            return None

    def obtener():
        f = FuenteEnVivo(cargador=lambda: estado.tramo.copy())
        f.proceso = estado.proceso
        return f

    from app.config import obtener_ajustes

    monkeypatch.setattr(ejecucion, "obtener_fuente", obtener)
    # la captura en vivo (FUENTE=postgres) es la que habilita el ciclo intradía; la fuente del ciclo es la de prueba
    monkeypatch.setattr(obtener_ajustes(), "fuente", "postgres")
    monkeypatch.setattr(segmentos_refresco, "encolar_tras_ciclo", lambda eid: estado.refrescos.append(eid))
    monkeypatch.setenv("SEUDONIMO_SECRETO", "secreto-de-prueba-tiempo-real")
    try:
        yield estado
    finally:
        _limpiar(sesion)


def _limpiar(sesion) -> None:
    sesion.rollback()
    ids = [str(e) for e in EJECUCIONES]
    if ids:
        hijos = [str(x) for x in sesion.execute(text(
            f"SELECT execution_id FROM {E}.execution_log WHERE padre_id = ANY(CAST(:i AS uuid[]))"),
            {"i": ids}).scalars()]
        todos = ids + hijos
        for tabla in ("ocupacion_segmento", "demanda_observada", "alert", "recommendation", "prediction",
                      "respuesta_reto", "feature_snapshot", "model_monitoring", "notification_log"):
            sesion.execute(text(f"DELETE FROM {E}.{tabla} WHERE execution_id = ANY(CAST(:i AS uuid[]))"),
                           {"i": todos})
        sesion.execute(text(f"DELETE FROM {E}.execution_log WHERE execution_id = ANY(CAST(:i AS uuid[]))"),
                       {"i": hijos + ids})
    sesion.execute(text(f"DELETE FROM {E}.marca_agua_ruta WHERE proceso LIKE :p"), {"p": PREFIJO + "%"})
    sesion.commit()
    EJECUCIONES.clear()


def _franja(hora: int, minuto: int = 5, segundos: int = 7, dia=DIA) -> datetime:
    from zoneinfo import ZoneInfo

    return datetime(dia.year, dia.month, dia.day, hora, minuto, segundos, tzinfo=ZoneInfo("America/Bogota"))


def _encolar_y_procesar(ahora: datetime) -> uuid.UUID:
    """La franja del ciclo intradía como la encola el planificador y su proceso por la cola (sin hilos: la misma
    reserva, reintento y cierre con cerca). Encolar dos veces la misma franja (otra réplica) no encola nada."""
    from app.servicios import ejecucion, planificador

    eid = planificador.tarea_ciclo_intradia(ahora)
    assert eid is not None
    EJECUCIONES.append(eid)
    assert planificador.tarea_ciclo_intradia(ahora + timedelta(seconds=3)) is None       # otra réplica: nada nuevo
    with sesion_contexto() as s:
        trabajos = [r[0] for r in s.execute(text(f"SELECT execution_id FROM {E}.execution_log WHERE padre_id = :p "
                                                 "ORDER BY creado_en"), {"p": eid}).all()]
    ejecucion.ejecutar(eid, trabajos)
    return eid


def _ejecucion(cliente, eid) -> dict:
    return cliente.get(f"/api/v1/frequency/executions/{eid}").json()


def _contar(sesion, tabla: str, eid) -> int:
    return int(sesion.execute(text(f"SELECT count(*) FROM {E}.{tabla} WHERE execution_id = :e"),
                              {"e": str(eid)}).scalar())


# ---------------------------------------------------------------- el ciclo intradía programado
def test_el_ciclo_intradia_programado_aplica_la_ocupacion_actual_en_el_plan_y_en_la_franja(cliente, fuente, sesion):
    eid = _encolar_y_procesar(_franja(9))
    e = _ejecucion(cliente, eid)
    assert e["estado"] == "ok", e["mensaje"]
    assert e["parametros"]["intradia"] is True and e["parametros"]["instante"] == "2025-10-22T09:05:00-05:00"
    with sesion_contexto() as s:
        programada = s.execute(text(f"SELECT programada_para FROM {E}.execution_log WHERE execution_id = :e"),
                               {"e": str(eid)}).scalar()
    assert programada == _franja(9, segundos=0)
    m = e["metricas"]
    # lo que es del modelo y lo que se lee una vez al día lo hace el ciclo diario
    assert m["intradia"]["nota"].startswith("Ciclo intradía") and "evaluacion_error" not in m
    assert "politica" not in (m.get("monitoreo") or {}) and _contar(sesion, "model_monitoring", eid) == 0
    assert "consolidados" not in (m.get("calidad") or {}) and fuente.refrescos == []
    # la ocupación actual: solo las horas cerradas a las 9:05 (6, 7 y 8 h; la de las 9 sigue abierta)
    assert m["ocupacion_segmentos"]["franjas_con_ocupacion"] == 3
    assert max(h for _, _, h in fuente.pedidas[0]) == 8
    # el plan es el del día en curso y la restricción reactiva actúa a las 9 h (la carga observada a las 8 h)
    reactiva = m["plan_dia"]["rutas"]["CL 72"]["restriccion_reactiva"]
    assert m["plan_dia"]["fecha"] == str(DIA) and reactiva["aplica"] is True
    assert (reactiva["hora_cerrada"], reactiva["hora_aplica"]) == (8, 9) and reactiva["salidas_minimas"] == 15
    plan = cliente.get("/api/v1/recommendations/plan", params={"ruta": "CL 72", "fecha": str(DIA)}).json()
    nueve = next(h for h in plan["horas"] if h["hora"] == 9)
    assert nueve["salidas"] >= 15 and plan["ocupacion_actual"]["aplica"] is True
    # las recomendaciones de 30 y 60 min (ventanas 9:05-9:35 y 9:05-10:05: su hora principal es la de las 9) reciben la
    # misma restricción (la misma carga y las mismas salidas pedidas; en la franja, acotadas además por lo que la flota
    # sostiene con el ciclo); la de 120 min (9:05-11:05, hora principal 10), no
    filas = sesion.execute(text(
        f"SELECT r.hora, r.buses_hora, r.detalle, p.horizonte_min FROM {E}.recommendation r JOIN {E}.prediction p "
        f"ON p.prediction_id = r.prediction_id WHERE r.execution_id = :e AND r.ruta = 'CL 72' AND r.origen = 'franja'"),
        {"e": str(eid)}).mappings().all()
    por_horizonte = {f["horizonte_min"]: f for f in filas}
    for horizonte in (30, 60):
        fila = por_horizonte[horizonte]
        assert fila["hora"] == 9
        restriccion = fila["detalle"]["salida"]["restriccion_reactiva"]
        assert restriccion["salidas_pedidas"] == plan["ocupacion_actual"]["salidas_pedidas"] == 15
        assert restriccion["salidas_minimas"] <= 15 and restriccion["motivo"]
        assert restriccion["aplicada"] is True, restriccion["motivo"]
        assert fila["buses_hora"] == restriccion["salidas_minimas"] > restriccion["buses_hora_sin_piso"]
        assert restriccion["limitada_por_flota"] is (restriccion["salidas_minimas"] < 15)
    assert por_horizonte[120]["hora"] == 10
    assert "restriccion_reactiva" not in por_horizonte[120]["detalle"]["salida"]
    # ninguna alerta observada por horas que todavía no pasaron: las ventanas terminan a más tardar a las 9:00
    fin_ventanas = sesion.execute(text(
        f"SELECT max(ventana_fin) FROM {E}.alert WHERE execution_id = :e AND origen = 'observado'"),
        {"e": str(eid)}).scalar()
    assert fin_ventanas is None or fin_ventanas <= _franja(9, minuto=0, segundos=0)
    obs = m["alertas_observadas"]
    assert str(DIA) in obs["dias_evaluados"]["CL 72"] and obs["horas_con_viajes_en_curso"] > 0
    assert obs["por_codigo"].get("ALT-002", 0) >= 1                   # la de las 7 y 8 h, medida en el segmento


def test_el_ciclo_intradia_partido_por_ruta_usa_la_version_de_umbrales_fijada(cliente, fuente, sesion, monkeypatch):
    """RNF-005 con §5.1: la madre del ciclo intradía fija la versión de umbrales al encolarse; un PUT /thresholds que
    llega antes de que corra (ocupacion_critica 1,4: con ella no habría restricción) no cambia lo que usa."""
    from app.config import obtener_ajustes
    from app.servicios import planificador

    antes = cliente.get("/api/v1/thresholds").json()
    monkeypatch.setattr(obtener_ajustes(), "plan_particion", "ruta")
    monkeypatch.setattr(obtener_ajustes(), "plan_intradia_cron", "6 6-20 * * *")
    monkeypatch.setattr(planificador, "rutas_de_la_particion", lambda: ["CL 72"])
    eid = planificador.tarea_ciclo_intradia(_franja(9, minuto=6))
    EJECUCIONES.append(eid)
    try:
        r = cliente.put("/api/v1/thresholds", json={"valores": {"ocupacion_critica": 1.4}, "motivo": "prueba"})
        assert r.status_code in (200, 201), r.text
        from app.servicios import ejecucion

        trabajos = [t["execution_id"] for t in _ejecucion(cliente, eid)["trabajos"]]
        ejecucion.ejecutar(eid, [uuid.UUID(t) for t in trabajos])
        madre, trabajo = _ejecucion(cliente, eid), _ejecucion(cliente, trabajos[0])
        assert madre["estado"] == "ok" and trabajo["estado"] == "ok", (madre["mensaje"], trabajo["mensaje"])
        assert madre["umbrales_version"] == trabajo["umbrales_version"] == antes["version"]
        assert trabajo["parametros"]["intradia"] is True and madre["metricas"]["intradia"]["nota"]
        reactiva = trabajo["metricas"]["plan_dia"]["rutas"]["CL 72"]["restriccion_reactiva"]
        assert reactiva["aplica"] is True                      # con la versión fijada (0,90), no con la nueva (1,4)
        assert _contar(sesion, "model_monitoring", eid) == 0 and fuente.refrescos == []
    finally:
        restituir_umbrales(sesion, antes["version"])


def test_un_ciclo_intradia_sin_datos_nuevos_no_rehace_el_plan(cliente, fuente, sesion):
    """Sin nada nuevo desde la marca (la hora siguiente no trajo viajes), el ciclo intradía no repite predicciones, plan
    ni foto: sin ocupación nueva su plan sería el mismo. Sí mide la frescura de los datos (ALT-009)."""
    primera = _encolar_y_procesar(_franja(9))
    segunda = _encolar_y_procesar(_franja(10))
    e = _ejecucion(cliente, segunda)
    assert e["estado"] == "ok" and e["filas_leidas"] == 0 and e["metricas"]["intradia"]["nota"]
    assert "Sin datos nuevos" in e["metricas"]["nota"] and "plan_dia" not in e["metricas"]
    assert _contar(sesion, "prediction", segunda) == 0 and _contar(sesion, "recommendation", segunda) == 0
    assert e["marca_agua_anterior"] == _ejecucion(cliente, primera)["marca_agua_nueva"]


def test_una_medicion_de_la_manana_no_restringe_la_ultima_hora_del_dia(cliente, fuente):
    """A las 20:05 la última hora cerrada con viajes medidos es la de las 9 (la fuente de prueba solo tiene viajes de
    6 a 9 h): está a más de 2 h de la siguiente programable y no restringe el plan; lo dice."""
    e = _ejecucion(cliente, _encolar_y_procesar(_franja(20)))
    reactiva = e["metricas"]["plan_dia"]["rutas"]["CL 72"]["restriccion_reactiva"]
    assert e["estado"] == "ok" and reactiva["aplica"] is False and "no sirve para programar" in reactiva["motivo"]
    assert e["metricas"]["ocupacion_segmentos"]["franjas_con_ocupacion"] == len(CARGAS)


def test_una_franja_que_llega_con_otro_ciclo_corriendo_espera_y_lee_desde_su_marca(cliente, fuente, sesion):
    """El ciclo diario (aquí, hasta el día anterior) y la franja intradía se procesan a la vez en dos hilos: la cola
    no entrega la franja mientras el otro corre (cola._RECLAMAR) y, al tomarla, lee desde la marca que dejó el otro."""
    from app.servicios import cola, ejecucion, planificador

    diaria = ejecucion.crear_ejecucion(sesion, "frecuencia", {"hasta": str(DIA - timedelta(days=1)),
                                                              "notificar": False}, None).execution_id
    EJECUCIONES.append(diaria)
    intradia = planificador.tarea_ciclo_intradia(_franja(9))
    EJECUCIONES.append(intradia)
    hilos = [threading.Thread(target=cola.procesar, args=(diaria,)),
             threading.Thread(target=cola.procesar, args=(intradia,))]
    hilos[0].start()
    time.sleep(0.5)
    hilos[1].start()
    for h in hilos:
        h.join(timeout=600)
    d, i = _ejecucion(cliente, diaria), _ejecucion(cliente, intradia)
    assert d["estado"] == "ok" and i["estado"] == "ok", (d["mensaje"], i["mensaje"])
    intentos = {str(r.execution_id): r for r in sesion.execute(text(
        f"SELECT execution_id, reclamado_en, terminado_en FROM {E}.execution_attempt WHERE execution_id = "
        "ANY(CAST(:i AS uuid[]))"), {"i": [str(diaria), str(intradia)]}).all()}
    assert intentos[str(diaria)].terminado_en <= intentos[str(intradia)].reclamado_en     # nunca a la vez
    assert i["marca_agua_anterior"] == d["marca_agua_nueva"]                             # lee desde su marca
    assert i["filas_leidas"] == len(fuente.tramo[fuente.tramo["fecha"] == DIA])         # solo el día que faltaba


# ---------------------------------------------------------------- una franja que quedó atrás en la cola
def test_una_franja_intradia_con_otra_posterior_en_la_cola_se_omite_sin_leer(cliente, fuente, sesion):
    """RNF-001: si la cola entrega una franja intradía cuando la siguiente ya espera (la cola estuvo detenida), la vieja
    ya no sirve para programar la hora en curso: se cierra «ok» sin leer la fuente ni mover la marca, y la siguiente lee
    todo desde la misma marca con su instante."""
    from app.servicios import cola, ejecucion, planificador

    vieja = planificador.tarea_ciclo_intradia(_franja(9))
    nueva = planificador.tarea_ciclo_intradia(_franja(10))
    EJECUCIONES.extend([vieja, nueva])
    cola.procesar(vieja)
    v = _ejecucion(cliente, vieja)
    assert v["estado"] == "ok" and v["filas_leidas"] == 0 and v["marca_agua_nueva"] is None, v["mensaje"]
    omitida = v["metricas"]["intradia"]
    assert omitida["omitida"].startswith("Franja intradía omitida") and v["mensaje"] == omitida["omitida"]
    assert ejecucion.a_instante(omitida["franja_posterior"]) == _franja(10, segundos=0)
    assert fuente.pedidas == [] and _contar(sesion, "prediction", vieja) == 0
    cola.procesar(nueva)
    n = _ejecucion(cliente, nueva)
    assert n["estado"] == "ok" and "omitida" not in n["metricas"]["intradia"]
    assert n["filas_leidas"] == len(fuente.tramo) and _contar(sesion, "prediction", nueva) > 0   # lo que dejó la vieja
    assert n["metricas"]["plan_dia"]["fecha"] == str(DIA)


def test_la_franja_de_la_noche_que_quedo_en_la_cola_no_le_quita_los_datos_al_ciclo_diario(cliente, fuente, sesion,
                                                                                          monkeypatch):
    """El cambio de día con la ejecución partida por ruta (RNF-005): la franja intradía de las 20:05 sigue en la cola
    cuando el planificador encola el ciclo diario de las 5:15. El trabajo de la ruta de la franja vieja se omite (la
    franja es la de su madre) y el ciclo diario lee todo lo del día anterior y lo evalúa completo."""
    from app.config import obtener_ajustes
    from app.servicios import ejecucion, planificador

    monkeypatch.setattr(obtener_ajustes(), "plan_particion", "ruta")
    monkeypatch.setattr(obtener_ajustes(), "plan_ejecucion_cron", "15 5 * * *")
    monkeypatch.setattr(planificador, "rutas_de_la_particion", lambda: ["CL 72"])
    noche = planificador.tarea_ciclo_intradia(_franja(20))
    diaria = planificador.tarea_ejecucion_diaria(_franja(5, minuto=15, dia=DIA + timedelta(days=1)))
    EJECUCIONES.extend([noche, diaria])
    for madre in (noche, diaria):
        ejecucion.ejecutar(madre, [uuid.UUID(t["execution_id"]) for t in _ejecucion(cliente, madre)["trabajos"]])
    trabajo_noche = _ejecucion(cliente, _ejecucion(cliente, noche)["trabajos"][0]["execution_id"])
    assert trabajo_noche["estado"] == "ok" and trabajo_noche["filas_leidas"] == 0
    assert ejecucion.a_instante(trabajo_noche["metricas"]["intradia"]["franja_posterior"]) == _franja(
        5, minuto=15, segundos=0, dia=DIA + timedelta(days=1))
    assert _ejecucion(cliente, noche)["estado"] == "ok"
    trabajo_diario = _ejecucion(cliente, _ejecucion(cliente, diaria)["trabajos"][0]["execution_id"])
    assert trabajo_diario["estado"] == "ok", trabajo_diario["mensaje"]
    assert trabajo_diario["filas_leidas"] == int((fuente.tramo["ruta"] == "CL 72").sum())
    assert str(DIA) in trabajo_diario["metricas"]["alertas_observadas"]["dias_evaluados"]["CL 72"]


# ---------------------------------------------------------------- la recomendación a pedido (POST /predictions/run)
def test_la_recomendacion_a_pedido_usa_la_ocupacion_medida_antes_de_su_instante(cliente, fuente, sesion):
    """§10.1 fuera del ciclo: POST /predictions/run de CL 72 a las 9:10 recibe la misma restricción reactiva que el
    ciclo intradía de las 9:05, con la ocupación de las 8 h que ese ciclo guardó, si se midió antes de su instante
    (§9.3: ninguna medición posterior al instante). Sin una medición anterior, la recomendación es la de siempre."""
    eid = _encolar_y_procesar(_franja(9))
    ids: list[str] = []

    def pedir(instante: str) -> dict:
        r = cliente.post("/api/v1/predictions/run", json={"ruta": "CL 72", "instante": instante, "horizonte_min": 30,
                                                          "modelo": "horario"})
        assert r.status_code == 201, r.text
        ids.append(r.json()["prediction_id"])
        return r.json()["recomendacion"]

    try:
        # el ciclo guardó la ocupación con el reloj de la base: para un instante de 2025 es posterior y no entra
        assert "restriccion_reactiva" not in pedir("2025-10-22T09:10:00-05:00")["detalle"]["salida"]
        sesion.execute(text(f"UPDATE {E}.ocupacion_segmento SET actualizado_en = :t WHERE execution_id = :e"),
                       {"t": _franja(9, minuto=6), "e": str(eid)})
        sesion.commit()
        rec = pedir("2025-10-22T09:10:00-05:00")              # medida a las 9:06, antes del instante
        rr = rec["detalle"]["salida"]["restriccion_reactiva"]
        assert (rr["hora_cerrada"], rr["hora_aplica"], rr["salidas_pedidas"]) == (8, 9, 15) and rr["aplicada"] is True
        assert rec["hora"] == 9 and rec["buses_hora"] == rr["salidas_minimas"] > rr["buses_hora_sin_piso"]
        assert "restriccion_reactiva" not in pedir("2025-10-22T09:05:30-05:00")["detalle"]["salida"]   # posterior
    finally:
        sesion.rollback()
        sesion.execute(text(f"DELETE FROM {E}.recommendation WHERE prediction_id = ANY(CAST(:i AS uuid[]))"),
                       {"i": ids})
        sesion.execute(text(f"DELETE FROM {E}.prediction WHERE prediction_id = ANY(CAST(:i AS uuid[]))"), {"i": ids})
        sesion.commit()


# ---------------------------------------------------------------- (b) un episodio cerrado no se vuelve a abrir
def test_un_episodio_cerrado_no_se_reabre_al_releer_el_dia(cliente, fuente, sesion):
    primera = _encolar_y_procesar(_franja(9))
    clave, alert_id = sesion.execute(text(
        f"SELECT clave_dedup, alert_id FROM {E}.alert WHERE execution_id = :e AND codigo = 'ALT-002' "
        "AND origen = 'observado' ORDER BY ventana_inicio LIMIT 1"), {"e": str(primera)}).one()
    sesion.execute(text(f"UPDATE {E}.alert SET estado = 'cerrada' WHERE alert_id = :a"), {"a": alert_id})
    sesion.commit()
    fuente.proceso = f"{PREFIJO}{uuid.uuid4().hex[:8]}"              # otra marca: se releen las mismas franjas
    segunda = _encolar_y_procesar(_franja(9, minuto=5, dia=DIA) + timedelta(hours=1))
    obs = _ejecucion(cliente, segunda)["metricas"]["alertas_observadas"]
    assert obs["episodios_cerrados_sin_cambio"] >= 1
    abiertas = sesion.execute(text(f"SELECT count(*) FROM {E}.alert WHERE clave_dedup = :c AND estado <> 'cerrada'"),
                              {"c": clave}).scalar()
    assert abiertas == 0


def _alt002_abiertas(sesion) -> list:
    return sesion.execute(text(
        f"SELECT alert_id, clave_dedup, ventana_inicio, ventana_fin, ocurrencias FROM {E}.alert "
        "WHERE codigo = 'ALT-002' AND origen = 'observado' AND ruta = 'CL 72' "
        "AND estado NOT IN ('cerrada', 'descartada') "
        "AND ventana_inicio >= :d AND ventana_inicio < :d + interval '1 day' ORDER BY ventana_inicio"),
        {"d": _franja(0, minuto=0, segundos=0)}).mappings().all()


def _vuelven_a_llegar(fuente, horas) -> None:
    """La captura en vivo vuelve a traer esas horas de CL 72 del día (sus viajes siguen sumando pasajeros): llegan
    después de todo lo que ya se leyó."""
    import pandas as pd

    tramo = fuente.tramo
    filas = (tramo["ruta"] == "CL 72") & (tramo["fecha"] == DIA) & tramo["hora"].isin(list(horas))
    llegada = pd.to_datetime(tramo["ultima_actualizacion"]).max() + pd.Timedelta(minutes=30)
    tramo["ultima_actualizacion"] = tramo["ultima_actualizacion"].where(~filas, llegada)
    tramo.loc[filas, "pasajeros"] = tramo.loc[filas, "pasajeros"] + 1


def test_alt002_junta_su_persistencia_con_la_ocupacion_que_guardo_el_ciclo_anterior(cliente, fuente, sesion):
    """(b) y §10.1 con llegada progresiva: el ciclo de las 8:05 mide la hora de las 7 (CL 72 al 100 %) y el de las 9:05
    solo trae la de las 8 (también al 100 %). Con la ocupación que guardó el ciclo anterior (ocupacion_del_dia), la
    hora de las 7 sigue medida en su segmento crítico, así que ALT-002 junta sus 2 h de persistencia: sin ella, cada
    ciclo veía una hora sola y el episodio nunca se alertaba."""
    import pandas as pd

    completo = fuente.tramo
    marca = pd.to_datetime(completo["ultima_actualizacion"]).max()
    fuente.tramo = completo[(completo["fecha"] != DIA) | (completo["hora"] < 8)].copy()   # a las 8:05, hasta las 7 h
    primera = _encolar_y_procesar(_franja(8))
    assert _alt002_abiertas(sesion) == [] and max(h for _, f, h in fuente.pedidas[-1] if f == DIA) == 7
    sesion.rollback()
    fuente.tramo = completo.copy()
    filas = (fuente.tramo["fecha"] == DIA) & (fuente.tramo["hora"] >= 8)                  # llega la hora de las 8
    fuente.tramo["ultima_actualizacion"] = fuente.tramo["ultima_actualizacion"].where(
        ~filas, marca + pd.Timedelta(minutes=30))
    segunda = _encolar_y_procesar(_franja(9))
    assert {h for r, _, h in fuente.pedidas[-1] if r == "CL 72"} == {8}                  # solo se mide la que llegó
    (alerta,) = _alt002_abiertas(sesion)
    assert (alerta["ventana_inicio"], alerta["ventana_fin"]) == (_franja(7, minuto=0, segundos=0),
                                                                 _franja(9, minuto=0, segundos=0))
    variables = sesion.execute(text(f"SELECT execution_id, variables FROM {E}.alert WHERE alert_id = :a"),
                               {"a": alerta["alert_id"]}).one()
    assert str(variables[0]) == str(segunda) and str(variables[0]) != str(primera)
    assert variables[1]["metodo_ocupacion"] == "segmento_critico"
    assert set(variables[1]["ocupacion_por_hora"]) == {"07:00", "08:00"}


def _viajes_de_progvehiculos(ruta, desde, hasta):
    """Los viajes del día de CL 72 como los lee la fuente de progvehiculos (idconductor en claro, antes de
    seudonimizar): los mismos ids, vehículos y conductores de los viajes por segmento sintéticos (viajes_sinteticos),
    terminados, con su salida en la hora de cada uno."""
    import pandas as pd

    from tests.integracion.test_ocupacion_ciclo import CARGAS

    filas = [{"viaje": 90_000_000 + hora * 100 + i, "vehiculo": f"VH{(hora * 100 + i) % 1000:03d}",
              "idconductor": 700_000 + i, "salida": datetime(DIA.year, DIA.month, DIA.day, hora, 5 * i),
              "salida_real": datetime(DIA.year, DIA.month, DIA.day, hora, 5 * i + 1), "finalizado": "S",
              "cancelada": "N", "excedeplazosalida": None, "numeropasajeros": carga, "filas_segmento": 11}
             for hora, cargas in CARGAS.items() for i, carga in enumerate(cargas)] if ruta == "CL 72" else []
    d = pd.DataFrame(filas, columns=["viaje", "vehiculo", "idconductor", "salida", "salida_real", "finalizado",
                                     "cancelada", "excedeplazosalida", "numeropasajeros", "filas_segmento"])
    ini, fin = desde.replace(tzinfo=None), hasta.replace(tzinfo=None)
    return d[(pd.to_datetime(d["salida"]) >= ini) & (pd.to_datetime(d["salida"]) < fin)].reset_index(drop=True)


def test_alt002_con_la_hora_pico_medida_por_el_ciclo_anterior_identifica_su_viaje(cliente, fuente, sesion, monkeypatch):
    """§5.3 con la ocupación guardada: el ciclo de las 8:05 mide la hora de las 7 y el de las 9:05 la de las 8, las dos
    con CL 72 al 100 %. La hora pico del episodio es la de las 7, que midió el ciclo anterior, y
    ai_frecuencias.ocupacion_segmento guarda solo el id de su viaje más cargado. Con los viajes del día que la fuente
    ya lee en solo lectura (progvehiculos, §5.3), ALT-002 lo identifica: el viaje, su vehículo y el seudónimo de su
    conductor, el mismo que da la lectura por segmento (fuentes.seudonimos). Antes salía «segmento_sin_viaje»."""
    import pandas as pd

    from app.servicios import ejecucion, fuentes

    original = ejecucion.obtener_fuente

    def con_viajes():
        f = original()
        f.viajes = lambda ruta, desde, hasta: fuentes.seudonimizar_viajes(_viajes_de_progvehiculos(ruta, desde, hasta))
        return f

    monkeypatch.setattr(ejecucion, "obtener_fuente", con_viajes)
    completo = fuente.tramo
    marca = pd.to_datetime(completo["ultima_actualizacion"]).max()
    fuente.tramo = completo[(completo["fecha"] != DIA) | (completo["hora"] < 8)].copy()   # a las 8:05, hasta las 7 h
    _encolar_y_procesar(_franja(8))
    sesion.rollback()
    fuente.tramo = completo.copy()
    filas = (fuente.tramo["fecha"] == DIA) & (fuente.tramo["hora"] >= 8)                  # llega la hora de las 8
    fuente.tramo["ultima_actualizacion"] = fuente.tramo["ultima_actualizacion"].where(
        ~filas, marca + pd.Timedelta(minutes=30))
    _encolar_y_procesar(_franja(9))
    (alerta,) = _alt002_abiertas(sesion)
    fila = sesion.execute(text(f"SELECT viaje, vehiculo, conductor, variables FROM {E}.alert WHERE alert_id = :a"),
                          {"a": alerta["alert_id"]}).one()
    sesion.rollback()
    assert fila.variables["hora_pico"].startswith(f"{DIA}T07:00")            # la hora que midió el ciclo de las 8:05
    assert (fila.viaje, fila.vehiculo) == ("90000707", "VH707")             # el de 53 pasajeros a bordo
    assert fila.conductor == fuentes.seudonimos([700_007])[0] and fila.conductor.startswith("cnd_")
    ident = fila.variables["identificacion_5_3"]
    assert (ident["resultado"], ident["variante"], ident["viaje_medido_por"]) == (
        "identificado", "segmento_critico", "ciclo_anterior")


def test_un_episodio_de_alt002_que_empieza_antes_en_el_ciclo_siguiente_no_se_duplica(cliente, fuente, sesion,
                                                                                      monkeypatch):
    """(b) sin duplicar: el ciclo de las 9:05 abre la ALT-002 del episodio de las 7 y 8 h. En el de las 10:05 vuelven
    las 6 y las 9 h, y las dos quedan al 100 %: la racha ahora empieza a las 6 h y su clave de episodio es otra. Como su
    ventana se cruza con la de la alerta abierta del mismo código y ruta (ejecucion.clave_del_episodio), se actualiza
    esa alerta en lugar de abrir otra por las mismas horas. Su ventana pasa a cubrir todo el episodio, de 6 a 10 h (el
    inicio no se quedaba en las 7 h), la bitácora lo dice y el ciclo de las 10:05 no la vuelve a notificar."""
    from tests.integracion import test_ocupacion_ciclo as base

    _encolar_y_procesar(_franja(9))
    (abierta,) = _alt002_abiertas(sesion)
    assert abierta["ventana_inicio"] == _franja(7, minuto=0, segundos=0)
    sesion.rollback()
    monkeypatch.setitem(base.CARGAS, 6, [50] * 12)              # los viajes de las 6 terminan con CL 72 al 100 %
    monkeypatch.setitem(base.CARGAS, 9, [50] * 12)              # y el episodio sigue a las 9 h
    _vuelven_a_llegar(fuente, (6, 9))
    segunda = _encolar_y_procesar(_franja(10))
    e = _ejecucion(cliente, segunda)
    assert e["estado"] == "ok" and e["filas_leidas"] == 2, e["mensaje"]
    assert sorted(h for _, _, h in fuente.pedidas[-1]) == [6, 9]         # solo se relee lo que llegó
    abiertas = _alt002_abiertas(sesion)
    assert len(abiertas) == 1, [(a["clave_dedup"], a["ventana_fin"]) for a in abiertas]   # una alerta del episodio
    (sigue,) = abiertas
    assert sigue["alert_id"] == abierta["alert_id"] and sigue["ocurrencias"] == 2
    assert sigue["ventana_fin"] == _franja(10, minuto=0, segundos=0)    # el episodio llega hasta las 10 h
    assert sigue["ventana_inicio"] == _franja(6, minuto=0, segundos=0)  # y empieza a las 6 h: cubre todas sus horas
    assert e["metricas"]["alertas_observadas"]["episodios_con_otro_inicio"] == 1
    cambios = [d for (d,) in sesion.execute(text(
        f"SELECT detalle FROM {E}.alert_history WHERE alert_id = :a AND accion = 'redeteccion'"),
        {"a": abierta["alert_id"]}).all()]
    assert [(d["antes"]["ventana_inicio"], d["despues"]["ventana_inicio"]) for d in cambios] == [
        (_franja(7, minuto=0, segundos=0).isoformat(), _franja(6, minuto=0, segundos=0).isoformat())]
    avisos = sesion.execute(text(f"SELECT execution_id FROM {E}.notification_log WHERE alert_id = :a"),
                            {"a": abierta["alert_id"]}).scalars().all()
    sesion.rollback()
    assert len(avisos) <= 1 and str(segunda) not in {str(x) for x in avisos}   # el episodio no se notifica dos veces


# ---------------------------------------------------------------- (c) planes reutilizados y vueltos a resolver
def test_la_foto_dice_que_plan_volvio_a_resolver_si_el_modelo_activo_cambio_a_mitad(cliente, fuente, sesion,
                                                                                    monkeypatch):
    """C2: entre el plan del ciclo y la foto de la respuesta se activa otro modelo (otra réplica, otra sesión): la foto
    lo ve, vuelve a resolver el plan con él y las métricas lo dicen con el motivo."""
    from app.servicios import inferencia, respuesta

    with sesion_contexto() as s:
        activo = s.execute(text(f"SELECT model_id FROM {E}.model_registry WHERE estado = 'activo' "
                                "AND familia = 'horario'")).scalar()
        registrados = set(s.execute(text(f"SELECT model_id FROM {E}.model_registry")).scalars())
    otro = next(f["model_id"] for f in inferencia.listar_modelos()          # otro modelo empaquetado, ejecutable
                if f.get("tipo") == "candidato" and f.get("ejecutable_en_api", True) and f["model_id"] != activo
                and f["model_id"] in registrados)
    assert activo and otro
    original = respuesta.precalcular

    def con_cambio_de_modelo(*args, **kwargs):
        with sesion_contexto() as s:       # otra transacción, confirmada: el ciclo la ve en su sesión
            s.execute(text(f"UPDATE {E}.model_registry SET estado = 'candidato' WHERE model_id = :m"), {"m": activo})
            s.execute(text(f"UPDATE {E}.model_registry SET estado = 'activo' WHERE model_id = :m"), {"m": otro})
        return original(*args, **kwargs)

    monkeypatch.setattr(respuesta, "precalcular", con_cambio_de_modelo)
    try:
        r = cliente.post("/api/v1/frequency/executions", json={"hasta": str(DIA), "rutas": ["CL 72"],
                                                               "notificar": False})
        assert r.status_code == 202, r.text
        EJECUCIONES.append(uuid.UUID(r.json()["execution_id"]))
        e = _ejecucion(cliente, r.json()["execution_id"])
    finally:
        with sesion_contexto() as s:
            s.execute(text(f"UPDATE {E}.model_registry SET estado = 'candidato' WHERE model_id = :m"), {"m": otro})
            s.execute(text(f"UPDATE {E}.model_registry SET estado = 'activo' WHERE model_id = :m"), {"m": activo})
    foto = e["metricas"]["respuesta"]
    assert e["estado"] == "ok" and foto["model_id"] == otro, foto
    assert foto["planes_reutilizados"] == [] and foto["planes_recalculados"] == ["CL 72"]
    assert activo in foto["motivos_recalculo"]["CL 72"] and otro in foto["motivos_recalculo"]["CL 72"]
    assert e["metricas"]["plan_dia"]["rutas"]["CL 72"]["model_id"] == activo       # el plan del ciclo, del anterior
