"""Integración de la partición por ruta y fecha (RNF-005): marca de agua por proceso y ruta, candado por ruta en la
cola y en el ciclo, ejecución partida en trabajos por ruta con su madre, equivalencia con la ejecución sin partir y
migración 0009.

La fuente es la Parquet real (un tramo de la serie empaquetada) con un PROCESO propio en cada prueba: sus marcas por
ruta (ai_frecuencias.marca_agua_ruta) no se mezclan con las de otras pruebas de la misma base. Las pruebas de la cola
usan un ciclo corto que cierra con la misma cerca del ciclo real (cola.cerrar_ok).
"""
from __future__ import annotations

import importlib.util
import json
import threading
import time
import uuid
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url

from app.modelos_db import Alerta, Ejecucion, MarcaAguaRuta, MonitoreoModelo, Prediccion, Recomendacion

E = "ai_frecuencias"
RAIZ = Path(__file__).resolve().parents[2]
RUTAS = ("SILENCIO", "CRA 54", "CL 72")


# ---------------------------------------------------------------- utilidades
@pytest.fixture
def fuente_propia(monkeypatch):
    """Fuente Parquet real (tramo 2025-02-24 … 2025-03-06) con un proceso propio que la prueba puede cambiar."""
    from app.servicios import datos, ejecucion, fuentes

    tramo = datos.demanda_horaria(desde=date(2025, 2, 24), hasta=date(2025, 3, 6))
    estado = SimpleNamespace(tramo=tramo, proceso=f"prueba-particion-{uuid.uuid4().hex[:8]}")

    def obtener():
        fuente = fuentes.FuenteParquet(cargador=lambda: estado.tramo.copy())
        fuente.proceso = estado.proceso
        return fuente

    monkeypatch.setattr(ejecucion, "obtener_fuente", obtener)
    return estado


def _filas(tramo, ruta: str, hasta: date, desde: date | None = None) -> int:
    m = (tramo["ruta"] == ruta) & (tramo["fecha"] <= hasta)
    if desde is not None:
        m &= tramo["fecha"] >= desde
    return int(m.sum())


def _post(cliente, **cuerpo) -> dict:
    r = cliente.post("/api/v1/frequency/executions", json=cuerpo, headers={"X-Correlation-Id": "prueba-particion"})
    assert r.status_code == 202, r.text
    return r.json()


def _detalle(cliente, execution_id) -> dict:
    r = cliente.get(f"/api/v1/frequency/executions/{execution_id}")
    assert r.status_code == 200, r.text
    return r.json()


def _marcas(sesion, proceso: str) -> dict[str, MarcaAguaRuta]:
    sesion.expire_all()
    return {m.ruta: m for m in sesion.scalars(select(MarcaAguaRuta).where(MarcaAguaRuta.proceso == proceso))}


def _maxima(tramo, ruta: str, hasta: date) -> datetime:
    import pandas as pd

    filas = tramo[(tramo["ruta"] == ruta) & (tramo["fecha"] <= hasta)]
    return pd.Timestamp(filas["ultima_actualizacion"].max()).to_pydatetime()


# ---------------------------------------------------------------- ejecución partida de punta a punta
def test_ejecucion_partida_un_trabajo_por_ruta_cada_uno_desde_su_marca(cliente, fuente_propia, sesion):
    creada = _post(cliente, hasta="2025-03-02", particion="ruta")
    assert creada["particion"] == "ruta" and creada["ruta"] is None and creada["padre_id"] is None
    assert [t["ruta"] for t in creada["trabajos"]] == list(RUTAS)
    madre = _detalle(cliente, creada["execution_id"])
    assert madre["estado"] == "ok", madre["mensaje"]
    assert madre["mensaje"] == "Terminada: 3 de 3 trabajos por ruta ok"
    trabajos = {t["ruta"]: t for t in madre["trabajos"]}
    for ruta in RUTAS:
        t = trabajos[ruta]
        assert t["estado"] == "ok" and t["intentos"] == 1
        assert t["filas_leidas"] == _filas(fuente_propia.tramo, ruta, date(2025, 3, 2))       # solo su ruta
        detalle = _detalle(cliente, t["execution_id"])
        assert detalle["ruta"] == ruta and detalle["padre_id"] == creada["execution_id"]
        assert detalle["predicciones"] == 3 and detalle["metricas"]["particion"]["rutas"] == [ruta]
        assert detalle["metricas"]["monitoreo"]["cierre_del_modelo"] == "ejecución madre"
    # la madre suma lo de sus trabajos y cierra lo del modelo una sola vez
    assert madre["filas_leidas"] == sum(t["filas_leidas"] for t in trabajos.values())
    assert madre["predicciones"] == 9 and madre["recomendaciones"] == 9
    assert sesion.scalar(select(text("count(*)")).select_from(MonitoreoModelo)
                         .where(MonitoreoModelo.execution_id.in_([uuid.UUID(t["execution_id"])
                                                                  for t in trabajos.values()]))) == 0
    # una marca de agua por proceso y ruta, la de los datos de esa ruta, dejada por su trabajo
    marcas = _marcas(sesion, fuente_propia.proceso)
    assert set(marcas) == set(RUTAS)
    for ruta in RUTAS:
        assert marcas[ruta].marca_agua == _maxima(fuente_propia.tramo, ruta, date(2025, 3, 2))
        assert str(marcas[ruta].execution_id) == trabajos[ruta]["execution_id"]
    api = cliente.get("/api/v1/frequency/watermarks", params={"proceso": fuente_propia.proceso}).json()
    assert sorted(m["ruta"] for m in api) == sorted(RUTAS) and {m["origen"] for m in api} == {"ejecucion"}
    listado = cliente.get("/api/v1/frequency/executions", params={"padre_id": creada["execution_id"]}).json()
    assert listado["total"] == 3 and {i["ruta"] for i in listado["items"]} == set(RUTAS)

    repetida = _detalle(cliente, _post(cliente, hasta="2025-03-02", particion="ruta")["execution_id"])
    for t in repetida["trabajos"]:           # repetir no lee nada: cada ruta ya está en su marca
        assert t["estado"] == "ok" and t["filas_leidas"] == 0
        assert t["marca_agua_anterior"] == trabajos[t["ruta"]]["marca_agua_nueva"]
    # la marca sigue siendo la del trabajo que la movió (§9.5: la de la última ejecución exitosa que leyó algo)
    assert {r: str(m.execution_id) for r, m in _marcas(sesion, fuente_propia.proceso).items()} == {
        r: trabajos[r]["execution_id"] for r in RUTAS}
    dia = _detalle(cliente, _post(cliente, hasta="2025-03-03", particion="ruta")["execution_id"])
    for t in dia["trabajos"]:                # llega un día: cada ruta lee exactamente su día
        assert t["filas_leidas"] == _filas(fuente_propia.tramo, t["ruta"], date(2025, 3, 3), date(2025, 3, 3))


def test_partida_y_sin_partir_dan_las_mismas_predicciones_plan_y_alertas_por_ruta(cliente, fuente_propia, sesion):
    """Mismo día, mismos datos: la ejecución sin partir (proceso P1) y la partida por ruta (proceso P2, marcas desde
    cero) dan por ruta las mismas predicciones, el mismo plan del día, detectan las mismas alertas y el mismo
    monitoreo del modelo."""
    def abiertas():
        sesion.expire_all()
        return {a.clave_dedup: a.ocurrencias for a in sesion.scalars(select(Alerta))}

    def fotos(ejecuciones):          # la foto de la respuesta del reto por ruta (sin lo que cambia en cada cálculo)
        filas = sesion.execute(text(f"SELECT ruta, payload FROM {E}.respuesta_reto "
                                    "WHERE execution_id = ANY(CAST(:ids AS uuid[]))"),
                               {"ids": [str(i) for i in ejecuciones]}).all()
        return {f.ruta: f.payload["ruta"] for f in filas}

    antes = abiertas()
    sin_partir = _detalle(cliente, _post(cliente, hasta="2025-03-04")["execution_id"])
    assert sin_partir["estado"] == "ok" and sin_partir["filas_leidas"] > 0
    tras_sin_partir = abiertas()
    fotos_x = fotos([sin_partir["execution_id"]])
    fuente_propia.proceso = f"prueba-particion-{uuid.uuid4().hex[:8]}"        # marcas desde cero para la partida
    partida = _detalle(cliente, _post(cliente, hasta="2025-03-04", particion="ruta")["execution_id"])
    assert partida["estado"] == "ok" and partida["metricas"]["trabajos_ok"] == 3
    assert partida["filas_leidas"] == sin_partir["filas_leidas"]
    tras_partida = abiertas()
    ids = [uuid.UUID(t["execution_id"]) for t in partida["trabajos"]]
    x = uuid.UUID(sin_partir["execution_id"])

    def predicciones(ejecuciones):
        return sorted((p.ruta, p.instante, p.horizonte_min, round(p.pasajeros, 6), round(p.p10 or 0, 6),
                       round(p.p90 or 0, 6), p.model_id)
                      for p in sesion.scalars(select(Prediccion).where(Prediccion.execution_id.in_(ejecuciones))))

    def plan(ejecuciones):
        return sorted((r.ruta, r.fecha, r.hora, r.buses_hora, r.headway_min, r.vehiculos_requeridos, r.viable)
                      for r in sesion.scalars(select(Recomendacion).where(Recomendacion.execution_id.in_(ejecuciones),
                                                                          Recomendacion.origen == "plan_dia")))

    assert predicciones([x]) == predicciones(ids) and len(predicciones(ids)) == 9
    assert plan([x]) == plan(ids)
    assert fotos(ids) == fotos_x                         # la respuesta del reto, ruta por ruta, igual
    # alertas: la partida vuelve a detectar exactamente las mismas (deduplicadas: suman una ocurrencia cada una)
    tocadas_x = {k: n - antes.get(k, 0) for k, n in tras_sin_partir.items() if n != antes.get(k)}
    tocadas_p = {k: n - tras_sin_partir.get(k, 0) for k, n in tras_partida.items() if n != tras_sin_partir.get(k)}
    assert tocadas_x and tocadas_x == tocadas_p          # p. ej. 18 alertas en el día de esta prueba
    # monitoreo del modelo: una fila por ejecución (la de la madre), con las mismas métricas
    horario = MonitoreoModelo.detalle["familia"].astext.is_distinct_from("corto_plazo")    # el del corto plazo, aparte
    m_x = sesion.scalars(select(MonitoreoModelo).where(MonitoreoModelo.execution_id == x,
                                                       MonitoreoModelo.rol == "activo", horario)).all()
    m_p = sesion.scalars(select(MonitoreoModelo).where(
        MonitoreoModelo.execution_id == uuid.UUID(partida["execution_id"]), MonitoreoModelo.rol == "activo",
        horario)).all()
    assert len(m_x) == len(m_p) == 1
    for campo in ("fecha_corte", "wape_movil", "mae_movil", "cobertura_p10_p90", "psi_max", "n_observaciones"):
        assert getattr(m_x[0], campo) == getattr(m_p[0], campo), campo
    assert m_p[0].n_predicciones == 9


def test_sin_partir_despues_de_una_ruta_lee_solo_lo_que_falta(cliente, fuente_propia, sesion):
    tramo = fuente_propia.tramo
    una = _detalle(cliente, _post(cliente, hasta="2025-03-02", particion="ruta", rutas=["SILENCIO"])["execution_id"])
    assert [t["ruta"] for t in una["trabajos"]] == ["SILENCIO"]
    assert una["filas_leidas"] == _filas(tramo, "SILENCIO", date(2025, 3, 2))
    todas = _detalle(cliente, _post(cliente, hasta="2025-03-02")["execution_id"])
    # SILENCIO ya está en su marca: la ejecución de todas las rutas solo lee las otras dos
    assert todas["filas_leidas"] == _filas(tramo, "CRA 54", date(2025, 3, 2)) + _filas(tramo, "CL 72", date(2025, 3, 2))
    assert todas["metricas"]["particion"]["rutas"] == "todas"
    marcas = _marcas(sesion, fuente_propia.proceso)
    assert set(marcas) == {*RUTAS, "*"}                     # todas en la frontera de la lectura completa
    assert {m.marca_agua for m in marcas.values()} == {_maxima(tramo, "SILENCIO", date(2025, 3, 2))}
    dia = _detalle(cliente, _post(cliente, hasta="2025-03-03", particion="ruta")["execution_id"])
    assert sorted(t["filas_leidas"] for t in dia["trabajos"]) == sorted(
        _filas(tramo, r, date(2025, 3, 3), date(2025, 3, 3)) for r in RUTAS)


@pytest.fixture
def postgres_en_memoria(monkeypatch):
    """La fuente PostgreSQL de verdad (FuentePostgresSoloLectura.leer_particion: un SELECT desde la marca más antigua
    y luego la marca, el solape y las huellas de cada ruta) sobre el tramo de la serie empaquetada. consultar() entrega
    lo que filtra el SELECT de la lista blanca (marca, hasta y rutas); lo demás (catálogos, punto de despacho) no está
    y el ciclo sigue sin eso, como con una réplica que no lo expone."""
    import pandas as pd

    from app.servicios import datos, ejecucion, fuentes

    tramo = datos.demanda_horaria(desde=date(2025, 2, 24), hasta=date(2025, 3, 6))
    proceso = f"prueba-particion-pg-{uuid.uuid4().hex[:8]}"

    class EnMemoria(fuentes.FuentePostgresSoloLectura):
        def consultar(self, sql, parametros=None):
            if "cambiados" not in getattr(sql, "text", str(sql)):
                raise RuntimeError("esta prueba solo simula la lectura incremental")
            p = parametros or {}
            marcas = fuentes._marcas_con_zona(tramo["ultima_actualizacion"])
            filtro = marcas > pd.Timestamp(p["marca"])
            if "hasta" in p:
                filtro &= marcas < pd.Timestamp(p["hasta"])
            if "rutas" in p:
                filtro &= tramo["ruta"].isin(p["rutas"])
            return tramo[filtro.to_numpy()].sort_values("ultima_actualizacion").reset_index(drop=True)

    monkeypatch.setattr(ejecucion, "obtener_fuente", lambda: EnMemoria(motor=object(), proceso=proceso))
    return SimpleNamespace(tramo=tramo, proceso=proceso)


def test_todas_las_rutas_con_hasta_anterior_a_una_ruta_adelantada_no_salta_ni_repite(cliente, postgres_en_memoria,
                                                                                      sesion):
    """Fuente PostgreSQL. SILENCIO ya leyó hasta el día 4 (un trabajo de su ruta); un trabajo de todas las rutas hasta
    el día 2 deja a CRA 54, CL 72 y la frontera en el día 2 (no en la marca adelantada de SILENCIO) sin borrar las
    huellas de SILENCIO, y el siguiente, hasta el día 4, les lee exactamente los días 3 y 4 y a SILENCIO nada: ningún
    día se salta y ninguna fila se entrega dos veces."""
    tramo, proceso = postgres_en_memoria.tramo, postgres_en_memoria.proceso
    otras = ("CRA 54", "CL 72")
    una = _detalle(cliente, _post(cliente, hasta="2025-03-04", particion="ruta", rutas=["SILENCIO"])["execution_id"])
    assert una["estado"] == "ok" and una["filas_leidas"] == _filas(tramo, "SILENCIO", date(2025, 3, 4))
    huellas = _marcas(sesion, proceso)["SILENCIO"].estado_fuente["huellas"]
    assert huellas                                              # la ventana de solape de SILENCIO (su día 4)
    antes = _detalle(cliente, _post(cliente, hasta="2025-03-02")["execution_id"])
    assert antes["estado"] == "ok"
    assert antes["filas_leidas"] == sum(_filas(tramo, r, date(2025, 3, 2)) for r in otras)
    marcas = _marcas(sesion, proceso)
    assert marcas["SILENCIO"].marca_agua == _maxima(tramo, "SILENCIO", date(2025, 3, 4))
    assert marcas["SILENCIO"].estado_fuente["huellas"] == huellas          # no leyó nada: sus huellas siguen
    dia_2 = max(_maxima(tramo, r, date(2025, 3, 2)) for r in otras)
    assert {r: marcas[r].marca_agua for r in (*otras, "*")} == {r: dia_2 for r in (*otras, "*")}
    despues = _detalle(cliente, _post(cliente, hasta="2025-03-04")["execution_id"])
    assert despues["filas_leidas"] == sum(_filas(tramo, r, date(2025, 3, 4), date(2025, 3, 3)) for r in otras)
    assert despues["metricas"]["lectura"]["rutas"]["SILENCIO"]["entregadas"] == 0


def test_falla_de_una_ruta_no_mueve_su_marca_y_la_siguiente_la_vuelve_a_leer(cliente, fuente_propia, sesion,
                                                                             monkeypatch):
    from app.servicios import ejecucion

    original = ejecucion._incorporar_historico

    def falla_en_cra54(s, validos, execution_id):
        if validos is not None and len(validos) and set(validos["ruta"]) == {"CRA 54"}:
            raise RuntimeError("histórico no disponible (simulado)")
        return original(s, validos, execution_id)

    monkeypatch.setattr(ejecucion, "_incorporar_historico", falla_en_cra54)
    madre = _detalle(cliente, _post(cliente, hasta="2025-03-02", particion="ruta")["execution_id"])
    estados = {t["ruta"]: t["estado"] for t in madre["trabajos"]}
    assert estados == {"SILENCIO": "ok", "CRA 54": "error", "CL 72": "ok"}
    assert madre["estado"] == "ok" and madre["mensaje"] == "Terminada con 1 de 3 trabajos por ruta en error"
    fallido = next(t for t in madre["trabajos"] if t["ruta"] == "CRA 54")
    assert fallido["filas_leidas"] > 0                     # su avance lo guardó, pero lo leído se revirtió
    assert madre["filas_leidas"] == sum(t["filas_leidas"] for t in madre["trabajos"] if t["estado"] == "ok")
    assert set(_marcas(sesion, fuente_propia.proceso)) == {"SILENCIO", "CL 72"}      # la fallida no se movió
    monkeypatch.setattr(ejecucion, "_incorporar_historico", original)
    otra = _detalle(cliente, _post(cliente, hasta="2025-03-02", particion="ruta")["execution_id"])
    leidas = {t["ruta"]: t["filas_leidas"] for t in otra["trabajos"]}
    assert leidas == {"SILENCIO": 0, "CRA 54": _filas(fuente_propia.tramo, "CRA 54", date(2025, 3, 2)), "CL 72": 0}


def test_borrar_el_trabajo_que_movio_la_marca_devuelve_la_ruta_a_su_carga(cliente, fuente_propia, sesion):
    """La marca de una ruta es la de la ejecución que la movió: si esa ejecución se borra (limpieza de pruebas o de
    una corrida mala), su marca se borra con ella y la ruta vuelve a leer sus datos; las demás no releen nada."""
    madre = _detalle(cliente, _post(cliente, hasta="2025-03-02", particion="ruta")["execution_id"])
    cra = next(t for t in madre["trabajos"] if t["ruta"] == "CRA 54")
    sesion.execute(text(f"DELETE FROM {E}.execution_log WHERE execution_id = :i"), {"i": cra["execution_id"]})
    sesion.commit()
    assert set(_marcas(sesion, fuente_propia.proceso)) == {"SILENCIO", "CL 72"}
    otra = _detalle(cliente, _post(cliente, hasta="2025-03-02", particion="ruta")["execution_id"])
    leidas = {t["ruta"]: t["filas_leidas"] for t in otra["trabajos"]}
    assert leidas == {"SILENCIO": 0, "CRA 54": _filas(fuente_propia.tramo, "CRA 54", date(2025, 3, 2)), "CL 72": 0}


def test_post_partido_valida_las_rutas_y_no_repite(cliente, sesion, monkeypatch):
    from app.servicios import ejecucion

    antes = sesion.scalar(select(text("count(*)")).select_from(Ejecucion))
    r = cliente.post("/api/v1/frequency/executions", json={"particion": "ruta", "rutas": ["NO-EXISTE"]})
    assert r.status_code == 422 and r.json()["error"]["codigo"] == "ruta_desconocida", r.text
    assert r.json()["error"]["detalle"]["desconocidas"] == ["NO-EXISTE"]
    assert sesion.scalar(select(text("count(*)")).select_from(Ejecucion)) == antes      # no creó nada
    monkeypatch.setattr(ejecucion, "ejecutar", lambda *a, **k: None)   # queda en la cola: se mira lo que se creó
    creada = cliente.post("/api/v1/frequency/executions",
                          json={"particion": "ruta", "rutas": ["CRA 54", "CRA 54"], "hasta": "2025-03-02"}).json()
    assert [t["ruta"] for t in creada["trabajos"]] == ["CRA 54"] and creada["parametros"]["rutas"] == ["CRA 54"]
    assert "particion" not in creada["parametros"]          # la partición vive en su columna, no en los parámetros
    sesion.execute(text(f"UPDATE {E}.execution_log SET estado = 'error', mensaje = 'limpieza de prueba' "
                        "WHERE execution_id = :m OR padre_id = :m"), {"m": creada["execution_id"]})
    sesion.commit()


# ---------------------------------------------------------------- cola: candado por ruta
@pytest.fixture
def cola_limpia(migrada):
    from app.db import sesion_contexto

    def limpiar():
        with sesion_contexto() as s:
            s.execute(text(f"UPDATE {E}.execution_log SET estado = 'error', worker_id = NULL, lease_hasta = NULL, "
                           "mensaje = 'limpieza de prueba' WHERE estado IN ('en_cola', 'corriendo')"))

    limpiar()
    yield
    limpiar()


def _grupo(rutas=("A", "B", "C"), dia: int = 1):
    from app.db import sesion_contexto
    from app.servicios import ejecucion

    with sesion_contexto() as s:
        madre, trabajos = ejecucion.crear_ejecucion_partida(s, {"hasta": f"2025-01-{dia:02d}", "prueba": "cola"},
                                                            "prueba-particion", list(rutas))
        return madre.execution_id, {t.ruta: t.execution_id for t in trabajos}


def _cerrar(execution_id, worker_id):
    from app.db import sesion_contexto
    from app.servicios import cola, ejecucion

    token = cola.trabajador_actual.set(worker_id)
    try:
        with sesion_contexto() as s:
            cola.cerrar_ok(s, execution_id, {"estado": "ok", "progreso": 100, "terminado_en": ejecucion.ahora()})
    finally:
        cola.trabajador_actual.reset(token)


def test_reclamo_reparte_rutas_distintas_y_la_misma_ruta_espera(cola_limpia):
    from app.servicios import cola

    madre1, dia1 = _grupo(dia=1)
    madre2, dia2 = _grupo(dia=2)
    w = [f"r{i}:900{i}:aaaaaa:t1" for i in range(4)]
    tomados = [cola.reclamar(w[i], lease_s=30) for i in range(3)]
    assert {r.ruta for r in tomados} == {"A", "B", "C"} and {r.execution_id for r in tomados} == set(dia1.values())
    assert cola.reclamar(w[3], lease_s=30) is None       # día 2: cada ruta ocupada; las madres esperan
    _cerrar(dia1["A"], w[0])
    siguiente = cola.reclamar(w[0], lease_s=30)
    assert (siguiente.execution_id, siguiente.ruta) == (dia2["A"], "A")    # la ruta A sigue con su día 2
    assert cola.reclamar(w[3], lease_s=30) is None       # B y C del día 1 corren; la madre 1 espera
    _cerrar(dia1["B"], w[1])
    _cerrar(dia1["C"], w[2])
    orden = [cola.reclamar(w[1], lease_s=30), cola.reclamar(w[2], lease_s=30)]
    assert orden[0].execution_id == madre1 and orden[0].ruta is None         # la madre 1 ya no tiene trabajos
    assert {orden[1].execution_id} <= {dia2["B"], dia2["C"]}
    sin_partir = _crear_sin_partir()
    _cerrar(madre1, w[1])
    restantes = {dia2["B"], dia2["C"]} - {orden[1].execution_id}
    r = cola.reclamar(w[1], lease_s=30)
    assert r.execution_id in restantes                   # antes que la de todas las rutas (llegó después)
    assert cola.reclamar(w[3], lease_s=30) is None       # la de todas las rutas espera a que no corra ninguna ruta
    for ident, worker in ((dia2["A"], w[0]), (orden[1].execution_id, w[2]), (r.execution_id, w[1])):
        _cerrar(ident, worker)
    todas = cola.reclamar(w[3], lease_s=30)
    assert {todas.execution_id} <= {madre2, sin_partir}


def _crear_sin_partir():
    from app.db import sesion_contexto
    from app.servicios import ejecucion

    with sesion_contexto() as s:
        return ejecucion.crear_ejecucion(s, "frecuencia", {"prueba": "cola"}, "prueba-particion").execution_id


def test_ejecucion_sin_partir_bloquea_todas_las_rutas(cola_limpia):
    from app.servicios import cola

    sin_partir = _crear_sin_partir()
    _, trabajos = _grupo(rutas=("A", "B"), dia=3)
    tomada = cola.reclamar("x:9100:aaaaaa:t1", lease_s=30)
    assert tomada.execution_id == sin_partir and tomada.ruta is None
    assert cola.reclamar("y:9101:bbbbbb:t1", lease_s=30) is None   # ninguna ruta mientras corre la de todas
    _cerrar(sin_partir, "x:9100:aaaaaa:t1")
    assert {cola.reclamar("y:9101:bbbbbb:t1", lease_s=30).ruta,
            cola.reclamar("z:9102:cccccc:t1", lease_s=30).ruta} == {"A", "B"}


def test_la_de_todas_las_rutas_espera_y_una_ruta_libre_que_llega_despues_se_le_adelanta(cola_limpia):
    """Lo que garantiza el reclamo entre una ejecución de todas las rutas y los trabajos de ruta: nunca corren a la vez,
    pero no van en orden de llegada. Mientras corre la ruta C, la de todas las rutas espera; un trabajo de B que llega
    después no se cruza con nada que corra y se reclama antes (la de todas las rutas lee luego cada ruta desde su
    marca: test_todas_las_rutas_con_hasta_anterior_a_una_ruta_adelantada_no_salta_ni_repite)."""
    from app.servicios import cola

    _, c = _grupo(rutas=("C",), dia=1)
    assert cola.reclamar("c:9301:aaaaaa:t1", lease_s=30).execution_id == c["C"]
    todas = _crear_sin_partir()
    _, b = _grupo(rutas=("B",), dia=2)
    adelantado = cola.reclamar("b:9302:bbbbbb:t1", lease_s=30)
    assert adelantado.execution_id == b["B"] and adelantado.ruta == "B"
    _cerrar(c["C"], "c:9301:aaaaaa:t1")
    assert cola.reclamar("t:9303:cccccc:t1", lease_s=30, execution_id=todas) is None     # B sigue corriendo
    _cerrar(b["B"], "b:9302:bbbbbb:t1")
    assert cola.reclamar("t:9303:cccccc:t1", lease_s=30, execution_id=todas).execution_id == todas


@pytest.fixture
def ciclo_con_tiempos(monkeypatch):
    """Ciclo corto que anota quién corrió cada trabajo, de qué ruta y cuándo; la madre comprueba que sus trabajos ya
    terminaron. Cierra con cola.cerrar_ok (la cerca del ciclo real)."""
    from app.db import sesion_contexto
    from app.servicios import cola, ejecucion

    registro: list[dict] = []
    cerrojo = threading.Lock()

    def ciclo(execution_id):
        with sesion_contexto() as s:
            e = s.get(Ejecucion, execution_id)
            ruta, madre = e.ruta, e.particion is not None
            pendientes = s.execute(text(f"SELECT count(*) FROM {E}.execution_log WHERE padre_id = :i "
                                        "AND estado IN ('en_cola', 'corriendo')"), {"i": execution_id}).scalar()
        inicio = time.monotonic()
        time.sleep(0.01 if madre else 0.25)
        with sesion_contexto() as s:
            cola.cerrar_ok(s, execution_id, {"estado": "ok", "progreso": 100, "terminado_en": ejecucion.ahora()})
        with cerrojo:
            registro.append({"id": execution_id, "ruta": ruta, "madre": madre, "pendientes": pendientes,
                             "worker": cola.trabajador_actual.get(), "inicio": inicio, "fin": time.monotonic()})

    monkeypatch.setattr(ejecucion, "_ciclo_frecuencia", ciclo)
    return registro


def test_dos_replicas_procesan_rutas_distintas_a_la_vez_sin_duplicados(cola_limpia, ciclo_con_tiempos):
    from app.servicios import cola

    grupos = [_grupo(dia=d) for d in range(1, 5)]
    ids = [m for m, _ in grupos] + [i for _, t in grupos for i in t.values()]
    parada = threading.Event()
    replicas = [cola.Trabajador(1, parada, worker_id="replica-a:9201:aaaaaa:t1", lease_s=10, sondeo_s=0.02),
                cola.Trabajador(2, parada, worker_id="replica-b:9202:bbbbbb:t1", lease_s=10, sondeo_s=0.02)]
    for r in replicas:
        r.start()
    try:
        fin = time.monotonic() + 90
        while time.monotonic() < fin and len(ciclo_con_tiempos) < len(ids):
            time.sleep(0.05)
    finally:
        parada.set()
        for r in replicas:
            r.join(timeout=10)
    hechos = [x for x in ciclo_con_tiempos if x["id"] in set(ids)]
    assert Counter(x["id"] for x in hechos) == Counter(ids)                  # cada trabajo, exactamente una vez
    trabajos = [x for x in hechos if not x["madre"]]
    assert {x["worker"].split(":")[0] for x in trabajos} == {"replica-a", "replica-b"}
    cruzan = [(a, b) for a in trabajos for b in trabajos
              if a["id"] != b["id"] and a["inicio"] < b["fin"] and b["inicio"] < a["fin"]]
    assert cruzan, "dos rutas distintas debieron correr a la vez"
    assert all(a["ruta"] != b["ruta"] and a["worker"] != b["worker"] for a, b in cruzan)   # nunca la misma ruta
    for ruta in ("A", "B", "C"):            # cada ruta, en el orden de sus días (marca de agua)
        de_la_ruta = sorted((x for x in trabajos if x["ruta"] == ruta), key=lambda x: x["inicio"])
        assert [x["id"] for x in de_la_ruta] == [t[ruta] for _, t in grupos]
    assert all(x["pendientes"] == 0 for x in hechos if x["madre"])           # la madre, cuando terminaron todos


# ---------------------------------------------------------------- candado de asesoría dentro del ciclo
def test_candado_de_ruta_aunque_una_replica_viva_haya_perdido_la_reserva(migrada):
    from app.db import nueva_sesion
    from app.servicios import ejecucion

    viva, otra, todas = nueva_sesion(), nueva_sesion(), nueva_sesion()
    try:
        ejecucion.tomar_candados_particion(viva, "A", espera_s=0)            # la réplica que perdió la reserva
        with pytest.raises(ejecucion.ParticionOcupada):
            ejecucion.tomar_candados_particion(otra, "A", espera_s=0.5)
        otra.rollback()
        ejecucion.tomar_candados_particion(otra, "B", espera_s=0)            # otra ruta, a la vez: sí
        with pytest.raises(ejecucion.ParticionOcupada):
            ejecucion.tomar_candados_particion(todas, None, espera_s=0.5)    # todas las rutas: espera
        todas.rollback()
        viva.rollback()                                                       # la vieja revierte: se libera
        otra.rollback()
        ejecucion.tomar_candados_particion(otra, "A", espera_s=0)
        otra.rollback()
        ejecucion.tomar_candados_particion(todas, None, espera_s=0)
    finally:
        for s in (viva, otra, todas):
            s.rollback()
            s.close()


# ---------------------------------------------------------------- planificador partido
def test_planificador_partido_una_madre_y_sus_trabajos_por_franja(cola_limpia):
    from app.db import sesion_contexto
    from app.servicios import planificador

    franja = datetime(2026, 3, 1, 5, 15, tzinfo=planificador.ZONA) + timedelta(minutes=uuid.uuid4().int % 100000)
    resultados: list = []
    barrera = threading.Barrier(2)

    def replica():
        barrera.wait()
        resultados.append(planificador.encolar_franja("frecuencia", franja, {"origen": "prueba", "rutas": list(RUTAS)},
                                                      "prueba", rutas=list(RUTAS)))

    hilos = [threading.Thread(target=replica) for _ in range(2)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()
    madres = [r for r in resultados if r is not None]
    assert len(madres) == 1
    with sesion_contexto() as s:
        filas = s.execute(text(f"SELECT execution_id, particion, ruta, padre_id FROM {E}.execution_log "
                               "WHERE execution_id = :m OR padre_id = :m"), {"m": madres[0]}).all()
    assert sorted((f.particion, f.ruta) for f in filas if f.padre_id is None) == [("ruta", None)]
    assert sorted(f.ruta for f in filas if f.padre_id == madres[0]) == sorted(RUTAS)


# ---------------------------------------------------------------- migración 0009 (base propia, desechable)
def _alembic(url: str, *args: str) -> None:
    from alembic.config import Config

    from alembic import command

    cfg = Config(str(RAIZ / "alembic.ini"))
    cfg.set_main_option("script_location", str(RAIZ / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    getattr(command, args[0])(cfg, *args[1:])


@pytest.fixture
def base_desechable(migrada):
    """Una base vacía en el mismo servidor local, que se borra al terminar (la migración baja y sube sin tocar la
    base de pruebas compartida)."""
    url = make_url(str(migrada))
    nombre = f"{url.database}_m0009_{uuid.uuid4().hex[:6]}"
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text(f'CREATE DATABASE "{nombre}"'))
    try:
        yield url.set(database=nombre).render_as_string(hide_password=False)
    finally:
        with admin.connect() as c:
            c.execute(text(f'DROP DATABASE IF EXISTS "{nombre}" WITH (FORCE)'))
        admin.dispose()


def test_migracion_0009_siembra_la_marca_global_en_cada_ruta_y_baja(base_desechable):
    spec = importlib.util.spec_from_file_location("m0009", RAIZ / "alembic" / "versions" / "0009_particion_por_ruta.py")
    m0009 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m0009)
    assert (m0009.revision, m0009.down_revision) == ("0009", "0008")
    _alembic(base_desechable, "upgrade", "0008")
    motor = create_engine(base_desechable)
    marca = datetime(2025, 3, 2, 23, 59, 59, tzinfo=ZoneInfo("America/Bogota"))
    estado = {"version": 2, "tabla": "demanda_segmentos", "solape_min": 15, "marca": marca.isoformat(),
              "huellas": {"SILENCIO|2025-03-02|20": "h1", "CRA 54|2025-03-02|20": "h2"}}
    with motor.begin() as c:
        c.execute(text(f"INSERT INTO {E}.execution_log (execution_id, tipo, estado, progreso, intentos, parametros, "
                       "metricas, marca_agua_nueva) VALUES (:i, 'frecuencia', 'ok', 100, 1, '{}'::jsonb, "
                       "CAST(:m AS jsonb), :marca)"),
                  {"i": uuid.uuid4(), "m": json.dumps({"fuente_estado": estado}), "marca": marca})
        c.execute(text(f"INSERT INTO {E}.demanda_observada (ruta, fecha, hora, pasajeros, idproceso) VALUES "
                       "('SILENCIO', '2025-03-02', 20, 10, 'sobusa'), ('CRA 54', '2025-03-02', 20, 12, NULL)"))
    motor.dispose()
    _alembic(base_desechable, "upgrade", "0009")
    motor = create_engine(base_desechable)
    with motor.connect() as c:
        filas = {(f.proceso, f.ruta): f for f in c.execute(text(f"SELECT * FROM {E}.marca_agua_ruta"))}
    motor.dispose()
    assert set(filas) == {("sobusa", "SILENCIO"), ("sobusa", "CRA 54"), ("sobusa", "*"), ("*", "*")}
    assert {f.marca_agua for f in filas.values()} == {marca}
    assert {f.origen for f in filas.values()} == {"migracion_0009"}
    assert filas[("sobusa", "SILENCIO")].estado_fuente["huellas"] == {"SILENCIO|2025-03-02|20": "h1"}
    assert filas[("sobusa", "CRA 54")].estado_fuente["huellas"] == {"CRA 54|2025-03-02|20": "h2"}
    assert filas[("sobusa", "*")].estado_fuente["huellas"] == estado["huellas"]
    _alembic(base_desechable, "downgrade", "0008")
    motor = create_engine(base_desechable)
    with motor.connect() as c:
        assert c.execute(text(f"SELECT to_regclass('{E}.marca_agua_ruta')")).scalar() is None
        columnas = set(c.execute(text("SELECT column_name FROM information_schema.columns WHERE table_schema = :e "
                                      "AND table_name = 'execution_log'"), {"e": E}).scalars())
    motor.dispose()
    assert not {"ruta", "padre_id", "particion"} & columnas
    _alembic(base_desechable, "upgrade", "head")
