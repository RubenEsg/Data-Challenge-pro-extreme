"""Integración: el ciclo de frecuencia con la ocupación ACTUAL por segmento (§10.1, §5.2 ALT-002, §5.3; H9).

La fuente de prueba es la Parquet real (22/10/2025 y los dos días previos, con un proceso propio para no mezclar sus
marcas de agua con las de otras pruebas) más, para las franjas que pide el ciclo, viajes con subidas y bajadas por
segmento como los que escribe tg_timbrada_segmento: en CL 72 suben 25 pasajeros por viaje a las 6 y a las 9 h y 50
(100 % de 50 puestos) a las 7 y a las 8 h, entre los segmentos 30 y 34, y bajan entre el 35 y el 40. El conductor llega
seudonimizado, como lo deja fuentes.FuentePostgresSoloLectura.leer_carga_segmentos.

Con una ejecución intradía (instante 09:30 del mismo día):
- la ocupación por segmento de las franjas YA CERRADAS (6, 7 y 8 h; la de las 9 h sigue abierta a las 9:30 y no se lee
  ni se guarda) queda en ai_frecuencias.ocupacion_segmento con el segmento crítico marcado, y una relectura de las
  mismas franjas la reemplaza sin duplicarla;
- ALT-002 observada se mide en el segmento crítico y lleva el segmento, el sentido, el viaje, el vehículo y el
  conductor seudónimo del viaje más cargado;
- el plan del día no baja, a las 9 h, de las salidas que exige la carga observada a las 8 h (restricción reactiva) y
  GET /recommendations/plan lo devuelve con su explicación;
- lo mismo con la ejecución partida por ruta (RNF-005): el trabajo de la ruta lo hace con la versión de umbrales de su
  ejecución.
"""
from __future__ import annotations

import math
import uuid
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
from sqlalchemy import text

Z = ZoneInfo("America/Bogota")
DIA = date(2025, 10, 22)          # miércoles
INSTANTE = "2025-10-22T09:30:00-05:00"
CARGAS = {6: [25] * 6, 7: [48, 50, 52, 49, 51, 50, 47, 53, 50, 50], 8: [50] * 12, 9: [25] * 6}
ESTACIONALIDAD = 7
EJECUCIONES: list[uuid.UUID] = []


def viajes_sinteticos(franjas) -> pd.DataFrame:
    """Filas viaje × segmento de CL 72 para las franjas pedidas (las demás rutas y horas no traen viajes)."""
    from app.servicios import ocupacion

    cat = ocupacion.catalogo_segmentos()
    ids = dict(zip(cat.loc[cat["idruta"] == 21, "nro_segmento"], cat.loc[cat["idruta"] == 21, "id_segmento"],
                   strict=True))
    filas = []
    for ruta, fecha, hora in franjas:
        for i, carga in enumerate(CARGAS.get(hora, []) if ruta == "CL 72" and fecha == DIA else []):
            viaje = 90_000_000 + hora * 100 + i
            subidas = [carga // 5 + (1 if k < carga % 5 else 0) for k in range(5)]
            bajadas = [carga // 6 + (1 if k < carga % 6 else 0) for k in range(6)]
            pares = [(30 + k, s, 0) for k, s in enumerate(subidas)] + [(35 + k, 0, b) for k, b in enumerate(bajadas)]
            filas += [{"ruta": ruta, "idruta": 21, "fecha": fecha, "hora": hora, "id_viaje": viaje,
                       "vehiculo": f"VH{viaje % 1000:03d}", "conductor": 700_000 + i, "terminado": True,
                       "id_segmento": int(ids[nro]), "nro_segmento": nro, "subidas": s, "bajadas": b}
                      for nro, s, b in pares]
    return pd.DataFrame(filas)


@pytest.fixture
def fuente_segmentos(monkeypatch, sesion):
    from app.servicios import datos, ejecucion, fuentes

    tramo = datos.demanda_horaria(desde=DIA - timedelta(days=2), hasta=DIA)
    # la lectura integrada trae la estacionalidad vigente de cada franja (estacionalidades_anio; aquí, la 7)
    tramo["id_estacionalidad"] = [ESTACIONALIDAD if f == DIA else None for f in tramo["fecha"]]
    estado = SimpleNamespace(tramo=tramo, proceso=f"prueba-ocupacion-{uuid.uuid4().hex[:8]}", pedidas=[])

    class FuenteConSegmentos(fuentes.FuenteParquet):
        def leer_carga_segmentos(self, franjas):
            estado.pedidas.append(list(franjas))
            return fuentes.seudonimizar_conductores(viajes_sinteticos(franjas))

    def obtener():
        f = FuenteConSegmentos(cargador=lambda: estado.tramo.copy())
        f.proceso = estado.proceso
        return f

    monkeypatch.setattr(ejecucion, "obtener_fuente", obtener)
    monkeypatch.setenv("SEUDONIMO_SECRETO", "secreto-de-prueba-ocupacion")
    try:
        yield estado
    finally:
        _limpiar(sesion, estado)


def _limpiar(sesion, estado) -> None:
    """Deja la base como estaba: lo que escribieron las ejecuciones de la prueba y las marcas de su proceso."""
    sesion.rollback()
    ids = [str(e) for e in EJECUCIONES]
    if ids:
        trabajos = [str(x) for x in sesion.execute(text(
            "SELECT execution_id FROM ai_frecuencias.execution_log WHERE padre_id = ANY(CAST(:i AS uuid[]))"),
            {"i": ids}).scalars()]
        todos = ids + trabajos
        for tabla in ("ocupacion_segmento", "demanda_observada", "alert", "recommendation", "prediction",
                      "respuesta_reto", "feature_snapshot", "model_monitoring", "notification_log"):
            sesion.execute(text(f"DELETE FROM ai_frecuencias.{tabla} WHERE execution_id = ANY(CAST(:i AS uuid[]))"),
                           {"i": todos})
        sesion.execute(text("DELETE FROM ai_frecuencias.marca_agua_ruta WHERE proceso LIKE 'prueba-ocupacion-%'"))
        sesion.execute(text("DELETE FROM ai_frecuencias.execution_log WHERE execution_id = ANY(CAST(:i AS uuid[]))"),
                       {"i": trabajos + ids})
        sesion.commit()
    EJECUCIONES.clear()


def _correr(cliente, **extra) -> dict:
    cuerpo = {"hasta": str(DIA), "instante": INSTANTE, "rutas": ["CL 72"], "notificar": False, **extra}
    r = cliente.post("/api/v1/frequency/executions", json=cuerpo)
    assert r.status_code == 202, r.text
    EJECUCIONES.append(uuid.UUID(r.json()["execution_id"]))
    e = cliente.get(f"/api/v1/frequency/executions/{r.json()['execution_id']}").json()
    assert e["estado"] == "ok", e.get("mensaje")
    return e


def _filas(sesion, execution_id) -> list:
    return sesion.execute(text(
        "SELECT ruta, hora, nro_segmento, id_segmento, critico, nro_viajes, carga_media, ocupacion_media, sentido, "
        "id_dia_semana, id_estacionalidad, capacidad, id_viaje_max FROM ai_frecuencias.ocupacion_segmento "
        "WHERE execution_id = :e ORDER BY hora, nro_segmento"), {"e": str(execution_id)}).mappings().all()


def _alt002_del_episodio(cliente) -> dict:
    r = cliente.get("/api/v1/alerts", params={"codigo": "ALT-002", "ruta": "CL 72", "limite": 500})
    assert r.status_code == 200, r.text
    for a in r.json()["items"]:
        ini = datetime.fromisoformat(a["ventana_inicio"]).astimezone(Z)
        if a["horizonte_min"] == 0 and ini.date() == DIA and ini.hour == 7:
            return a
    raise AssertionError("no aparece la ALT-002 observada de las 7 h")


def test_el_ciclo_guarda_la_ocupacion_por_segmento_y_la_usa_en_alt002_y_en_el_plan(cliente, fuente_segmentos,
                                                                                    sesion):
    from app.servicios import alertas, ocupacion

    e = _correr(cliente)
    m = e["metricas"]["ocupacion_segmentos"]
    cerradas = (6, 7, 8)                                           # a las 9:30 la hora de las 9 todavía no cerró
    assert m["franjas_con_ocupacion"] == 3 and m["viajes"] == sum(len(CARGAS[h]) for h in cerradas)
    assert {r for r, f, _ in fuente_segmentos.pedidas[0]} == {"SILENCIO", "CRA 54", "CL 72"}
    assert {f for _, f, _ in fuente_segmentos.pedidas[0]} == {DIA}     # solo el último día de cada ruta
    assert max(h for _, _, h in fuente_segmentos.pedidas[0]) == 8      # ni la hora en curso ni las posteriores
    filas = _filas(sesion, e["execution_id"])
    assert m["filas_guardadas"] == len(filas) == 3 * 11            # 3 franjas × segmentos 30..40
    criticos = {f["hora"]: f for f in filas if f["critico"]}
    assert set(criticos) == set(cerradas) and all(f["nro_segmento"] == 34 for f in criticos.values())
    assert criticos[8]["ocupacion_media"] == pytest.approx(1.0) and criticos[8]["nro_viajes"] == 12
    assert criticos[7]["ocupacion_media"] == pytest.approx(sum(CARGAS[7]) / len(CARGAS[7]) / 50)
    sentido = ocupacion.catalogo_segmentos().set_index(["idruta", "nro_segmento"]).loc[(21, 34), "sentido"]
    assert {f["sentido"] for f in criticos.values()} == {sentido} and {f["id_dia_semana"] for f in filas} == {3}
    assert {f["capacidad"] for f in filas} == {50.0}
    assert {f["id_estacionalidad"] for f in filas} == {ESTACIONALIDAD}    # la estacionalidad actual de la lectura

    # ALT-002 observada medida en el segmento crítico, con el viaje, el vehículo y el conductor seudónimo
    a = _alt002_del_episodio(cliente)
    assert a["variables"]["metodo_ocupacion"] == "segmento_critico" and a["observado"] == pytest.approx(1.0)
    assert a["sentido"] == sentido and a["viaje"] is not None and a["vehiculo"].startswith("VH")
    assert alertas.PATRON_SEUDONIMO.match(a["conductor"])                # nunca el identificador en claro
    assert a["variables"]["segmento_critico"] == 34 and "segmento crítico 34" in a["explicacion"]

    # el plan del día: a las 9 h no menos de ceil(600 / (50 × 0,85)) = 15 salidas (12 viajes × 50 a bordo a las 8 h)
    plan = cliente.get("/api/v1/recommendations/plan", params={"ruta": "CL 72", "fecha": str(DIA)}).json()
    reactiva = plan["ocupacion_actual"]
    assert reactiva["aplica"] is True, reactiva
    assert (reactiva["hora_cerrada"], reactiva["hora_aplica"]) == (8, 9) and reactiva["segmento"] == 34
    esperadas = math.ceil(600 / (reactiva["capacidad_plan"] * reactiva["ocupacion_objetivo_max"]) - 1e-9)
    assert reactiva["salidas_minimas"] == esperadas
    nueve = next(h for h in plan["horas"] if h["hora"] == 9)
    assert nueve["salidas"] >= esperadas and nueve["restriccion_reactiva"]["salidas_minimas"] == esperadas
    assert nueve["ocupacion_historica"]["nro_segmento"] >= 1 and "Segmento crítico histórico" in \
        nueve["ocupacion_historica"]["texto"]
    assert e["metricas"]["plan_dia"]["rutas"]["CL 72"]["restriccion_reactiva"]["aplica"] is True

    # releer las mismas franjas (otra marca de agua) las reemplaza: mismas filas, ninguna duplicada
    fuente_segmentos.proceso = f"prueba-ocupacion-{uuid.uuid4().hex[:8]}"
    e2 = _correr(cliente)
    assert _filas(sesion, e["execution_id"]) == []
    assert len(_filas(sesion, e2["execution_id"])) == len(filas)
    total = sesion.execute(text("SELECT count(*) FROM ai_frecuencias.ocupacion_segmento WHERE ruta = 'CL 72' AND "
                                "fecha = :f"), {"f": DIA}).scalar()
    assert total == len(filas)
    assert _alt002_del_episodio(cliente)["ocurrencias"] >= 2       # la misma alerta, sin duplicarla


def test_la_ejecucion_partida_por_ruta_calcula_la_ocupacion_en_el_trabajo_de_la_ruta(cliente, fuente_segmentos,
                                                                                     sesion):
    madre = _correr(cliente, particion="ruta")
    assert [t["ruta"] for t in madre["trabajos"]] == ["CL 72"]
    trabajo = cliente.get(f"/api/v1/frequency/executions/{madre['trabajos'][0]['execution_id']}").json()
    m = trabajo["metricas"]["ocupacion_segmentos"]
    assert trabajo["estado"] == "ok" and m["franjas_con_ocupacion"] == 3     # las horas cerradas a las 9:30
    assert {r for r, _, _ in fuente_segmentos.pedidas[-1]} == {"CL 72"}       # el trabajo lee solo su ruta
    assert len(_filas(sesion, trabajo["execution_id"])) == 3 * 11
    plan = trabajo["metricas"]["plan_dia"]["rutas"]["CL 72"]
    assert plan["restriccion_reactiva"]["aplica"] is True and plan["restriccion_reactiva"]["salidas_minimas"] >= 13
    assert trabajo["umbrales_version"] == madre["umbrales_version"]


def test_el_ciclo_de_la_madrugada_mide_el_dia_que_acaba_de_terminar(cliente, fuente_segmentos, sesion):
    """El ciclo programado de las 5:15 ya trae la franja de las 4 h del día en curso (sus viajes, de unas 3,5 h, van
    por la mitad y ninguno ha terminado). La ocupación actual del día que acaba de terminar se mide y se guarda igual:
    la ventana de franjas es de 24 h, no el último día del lote. Y las alertas observadas evalúan ese día completo,
    no solo el último del lote (ejecucion.contextos_observados): ALT-002 de las 7 y 8 h del día anterior se mide en su
    segmento crítico aunque el lote cruce la medianoche."""
    manana = DIA + timedelta(days=1)
    madrugada = fuente_segmentos.tramo[(fuente_segmentos.tramo["ruta"] == "CL 72")
                                       & (fuente_segmentos.tramo["fecha"] == DIA)
                                       & (fuente_segmentos.tramo["hora"] == 4)].copy()
    madrugada = madrugada.assign(fecha=manana, pasajeros=0.0, salidas=0,       # 2025-10-23 05:10, la misma zona
                                 ultima_actualizacion=madrugada["ultima_actualizacion"] + pd.Timedelta("5h10min1s"))
    fuente_segmentos.tramo = pd.concat([fuente_segmentos.tramo, madrugada], ignore_index=True)
    e = _correr(cliente, hasta=str(manana), instante="2025-10-23T05:15:00-05:00")
    pedidas = [(f, h) for r, f, h in fuente_segmentos.pedidas[0] if r == "CL 72"]
    assert (manana, 4) in pedidas and {(DIA, h) for h in CARGAS} <= set(pedidas)
    m = e["metricas"]["ocupacion_segmentos"]
    filas = _filas(sesion, e["execution_id"])
    assert m["franjas_con_ocupacion"] == 4 and len(filas) == 4 * 11
    criticos = {f["hora"]: f for f in filas if f["critico"]}
    assert set(criticos) == set(CARGAS) and criticos[8]["ocupacion_media"] == pytest.approx(1.0)
    assert {f["id_dia_semana"] for f in filas} == {3}                    # el miércoles que acaba de terminar
    # el plan es el de mañana: la ocupación de hoy no lo restringe (solo dentro del mismo día) y lo dice
    reactiva = e["metricas"]["plan_dia"]["rutas"]["CL 72"]["restriccion_reactiva"]
    assert reactiva["aplica"] is False and "no hay una hora cerrada" in reactiva["motivo"]
    # (b) el día anterior, completo, también se evalúa en las alertas observadas, con la ocupación por segmento
    obs = e["metricas"]["alertas_observadas"]
    assert {str(DIA), str(manana)} <= set(obs["dias_evaluados"]["CL 72"])
    a = _alt002_del_episodio(cliente)
    assert a["execution_id"] == e["execution_id"] and a["variables"]["metodo_ocupacion"] == "segmento_critico"


def test_sin_viajes_por_segmento_el_ciclo_sigue_igual(cliente, fuente_segmentos, sesion, monkeypatch):
    from app.servicios import ejecucion, fuentes

    def obtener():
        f = fuentes.FuenteParquet(cargador=lambda: fuente_segmentos.tramo.copy())
        f.proceso = f"prueba-ocupacion-{uuid.uuid4().hex[:8]}"
        return f

    monkeypatch.setattr(ejecucion, "obtener_fuente", obtener)
    e = _correr(cliente)
    assert "modo offline" in e["metricas"]["ocupacion_segmentos"]["nota"] and _filas(sesion, e["execution_id"]) == []
    plan = cliente.get("/api/v1/recommendations/plan", params={"ruta": "CL 72", "fecha": str(DIA)}).json()
    assert plan["ocupacion_actual"] is None
    assert all(h["restriccion_reactiva"] is None for h in plan["horas"])
