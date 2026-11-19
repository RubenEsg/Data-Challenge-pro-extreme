"""Convivencia del ciclo de frecuencia con la capa de segmentos y con la partición por ruta (§6.1, §7.3 paso 4, §5.1,
RNF-001, RNF-004, RNF-005), contra la base LOCAL de pruebas.

La base operacional está configurada (la fuente sintética de test_segmentos_materializados) y el modelo de segmentos
está activo, así que cada ciclo guarda la foto por segmento y sentido en feature_snapshot y, si trajo datos nuevos,
pide el refresco de la agregación de segmentos. Se comprueba:

1. Sin partir: un intento que pierde la reserva en el cierre con cerca (otra réplica la tomó) y otro que falla en el
   cierre (error reintentable) se revierten completos. No dejan predicciones ni filas de la foto (de la ruta o por
   segmento) y no piden el refresco. La réplica que la retoma termina «ok»: la foto queda una sola vez y queda UN
   refresco «segmentos» con origen «ciclo», pedido después del cierre, que corre con la cola y deja la agregación.
2. Partida por ruta (particion = «ruta»): cada trabajo de ruta guarda la foto de SUS predicciones, en su ejecución y
   en la partición mensual de su ventana, sin filas repetidas; la madre no guarda foto. Las filas son las mismas que
   deja la ejecución sin partir del mismo día. El refresco lo pide la madre, una sola vez por ejecución y después de
   cerrar; ningún trabajo de ruta lo pide (cada pedido que la cola no junta es una lectura más en la base de Extreme).
   Los consolidados de Extreme (app/servicios/consolidados.py) también los lee solo la madre, al cerrar.
3. Partida por ruta con caída: un trabajo de ruta que pierde la reserva en el cierre no deja foto ni pide el refresco;
   al retomarlo, su foto queda una sola vez y la madre pide un solo refresco.
4. La madre y todos sus trabajos usan la misma versión de umbrales y de parámetros del plan (la vigente al crear la
   ejecución), aunque llegue un PUT /thresholds mientras corren, también en la foto de la respuesta del reto, que
   reutiliza el plan guardado; la ejecución siguiente ya usa la versión nueva.
5. Con PLAN_PARTICION=ruta, la franja del planificador encola la madre y sus trabajos con la versión fijada, y al
   procesarlos se cumple lo mismo: la foto una vez por trabajo y un solo refresco, pedido por la madre.

Cada prueba lee con un proceso propio (sus marcas por ruta no se mezclan con las de otras pruebas) un tramo real de
sep-2025 que «llega ahora». Deja la base como la encontró: borra sus ejecuciones y sus trabajos por ruta (y con ellos
predicciones, recomendaciones, alertas, histórico, foto de la respuesta, foto de variables, monitoreo, intentos y
marcas por ruta), la agregación de segmentos y los trabajos «segmentos», y restaura el registro de modelos.
"""
from __future__ import annotations

import uuid
from collections import Counter
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pandas as pd
import pytest
from sqlalchemy import create_engine, delete, func, select, text

from app.modelos_db import (
    Alerta,
    DemandaObservada,
    Ejecucion,
    FotoVariables,
    Prediccion,
    Recomendacion,
    RegistroModelo,
    RespuestaReto,
)
from tests.integracion.conftest import restituir_umbrales
from tests.integracion.test_segmentos_materializados import DDL_FUENTE, ESQUEMA, _sembrar

E = "ai_frecuencias"
ACTIVO = "hgb_fv2_20250831_s42"
RUTAS = ("SILENCIO", "CRA 54", "CL 72")
TABLAS_AGREGACION = ("segmento_estadistica_refresco", "segmento_estadistica", "segmento_estadistica_dia")


# ---------------------------------------------------------------- entorno y limpieza
def _limpiar_segmentos(s) -> None:
    """Sin agregación de segmentos ni trabajos «segmentos» (como test_segmentos_materializados._limpiar)."""
    s.rollback()
    for tabla in TABLAS_AGREGACION:
        s.execute(text(f"DELETE FROM {E}.{tabla}"))
    s.execute(text(f"DELETE FROM {E}.execution_log WHERE tipo = 'segmentos'"))
    s.commit()


def _limpiar_ejecuciones(s, ids: list[uuid.UUID]) -> None:
    """Lo que dejaron las ejecuciones de este módulo y sus trabajos por ruta. Con las ejecuciones se van, en cascada,
    la foto de variables, el monitoreo, los errores de calidad, los intentos y las marcas por ruta que movieron."""
    s.rollback()
    if not ids:
        return
    todos = set(ids) | set(s.scalars(select(Ejecucion.execution_id).where(Ejecucion.padre_id.in_(ids))))
    for modelo in (DemandaObservada, Alerta, Recomendacion, Prediccion, RespuestaReto):
        s.execute(delete(modelo).where(modelo.execution_id.in_(todos)))
    s.execute(delete(Ejecucion).where(Ejecucion.execution_id.in_(todos)))
    s.commit()


def _restaurar_registro(s, previos: dict) -> None:
    for m in s.scalars(select(RegistroModelo).where(RegistroModelo.estado == "activo")).all():
        m.estado = "candidato"
    s.flush()
    for activo in (False, True):          # primero los no activos: un solo activo a la vez
        for mid, (estado, anterior, metricas, auditoria) in previos.items():
            m = s.scalar(select(RegistroModelo).where(RegistroModelo.model_id == mid))
            if m is not None and (estado == "activo") == activo:
                m.estado, m.anterior_model_id, m.metricas, m.auditoria = estado, anterior, metricas, auditoria
        s.flush()
    s.commit()


@pytest.fixture(scope="module")
def motor_fuente(migrada):
    """Las tablas de Extreme que lee la capa de segmentos, en un esquema aparte de la base LOCAL de pruebas."""
    admin = create_engine(migrada)
    with admin.begin() as c:
        c.execute(text(f"DROP SCHEMA IF EXISTS {ESQUEMA} CASCADE"))
        c.execute(text(f"CREATE SCHEMA {ESQUEMA}"))
        c.execute(text(DDL_FUENTE))
        _sembrar(c)
    motor = create_engine(migrada, connect_args={"options": f"-c search_path={ESQUEMA}"})
    yield motor
    motor.dispose()
    with admin.begin() as c:
        c.execute(text(f"DROP SCHEMA IF EXISTS {ESQUEMA} CASCADE"))
    admin.dispose()


@pytest.fixture(scope="module")
def entorno(cliente, motor_fuente):
    """Registro conocido (fv2 activo), capa de segmentos con la fuente sintética, fuente de frecuencia con sep-2025
    «llegando ahora» y un proceso propio por prueba; al final, la limpieza."""
    from app.db import nueva_sesion
    from app.servicios import datos, ejecucion, fuentes, segmentos

    s = nueva_sesion()
    ejecucion.sembrar_registro(s)
    previos = {m.model_id: (m.estado, m.anterior_model_id, dict(m.metricas or {}), list(m.auditoria or []))
               for m in s.scalars(select(RegistroModelo)).all()}
    if ACTIVO not in previos:
        s.close()
        pytest.skip("el registro empaquetado no trae el modelo activo fv2")
    for m in s.scalars(select(RegistroModelo).where(RegistroModelo.estado == "activo")).all():
        m.estado = "candidato"
    s.flush()
    s.scalar(select(RegistroModelo).where(RegistroModelo.model_id == ACTIVO)).estado = "activo"
    s.commit()
    _limpiar_segmentos(s)
    tramo = datos.demanda_horaria(desde=date(2025, 9, 1), hasta=date(2025, 9, 25))
    base = pd.Timestamp.now(tz="America/Bogota") + pd.Timedelta(days=1)
    tramo["ultima_actualizacion"] = base + pd.to_timedelta(
        [(f - date(2025, 9, 1)).days for f in tramo["fecha"]], unit="D")
    estado = SimpleNamespace(sesion=s, ids=[], proceso="")

    def nuevo_proceso() -> None:          # marcas por ruta desde cero: la ejecución lee el tramo desde la carga
        estado.proceso = f"prueba-convivencia-{uuid.uuid4().hex[:8]}"

    def obtener():
        fuente = fuentes.FuenteParquet(cargador=lambda: tramo.copy())
        fuente.proceso = estado.proceso
        return fuente

    estado.nuevo_proceso = nuevo_proceso
    nuevo_proceso()
    mp = pytest.MonkeyPatch()
    original = segmentos.fuente
    mp.setattr(segmentos, "fuente", lambda motor=None: original(motor or motor_fuente))
    mp.setattr(segmentos, "fuente_configurada", lambda: True)
    mp.setattr(ejecucion, "obtener_fuente", obtener)
    try:
        yield estado
    finally:
        mp.undo()
        _limpiar_ejecuciones(s, estado.ids)
        _limpiar_segmentos(s)
        _restaurar_registro(s, previos)
        s.close()


@pytest.fixture(autouse=True)
def sin_refrescos_en_cola(entorno):
    """Cada prueba empieza sin refrescos «segmentos» en cola: uno que dejara otra prueba juntaría los pedidos (la cola
    no duplica un refresco igual en cola) y la prueba no vería el suyo."""
    s = entorno.sesion
    s.rollback()
    s.execute(text(f"DELETE FROM {E}.execution_log WHERE tipo = 'segmentos' AND estado = 'en_cola'"))
    s.commit()


@pytest.fixture
def pedidos_de_refresco(monkeypatch):
    """Cada pedido del refresco de segmentos tras un ciclo (segmentos_refresco.encolar_tras_ciclo), en orden."""
    from app.servicios import segmentos_refresco

    original = segmentos_refresco.encolar_tras_ciclo
    pedidos: list[str] = []

    def espia(execution_id_ciclo):
        pedidos.append(str(execution_id_ciclo))
        return original(execution_id_ciclo)

    monkeypatch.setattr(segmentos_refresco, "encolar_tras_ciclo", espia)
    return pedidos


# ---------------------------------------------------------------- utilidades
def _post(cliente, entorno, *, encolar_solo: bool = False, **cuerpo) -> dict:
    """POST /frequency/executions. Con encolar_solo, la API crea la ejecución (y sus trabajos por ruta) sin procesarla:
    la prueba la procesa paso a paso con la cola."""
    from app.servicios import ejecucion

    with pytest.MonkeyPatch.context() as mp:
        if encolar_solo:
            mp.setattr(ejecucion, "ejecutar", lambda *a, **k: None)
        r = cliente.post("/api/v1/frequency/executions", json=cuerpo, headers={"X-Correlation-Id": "convivencia"})
    assert r.status_code == 202, r.text
    creada = r.json()
    entorno.ids.append(uuid.UUID(creada["execution_id"]))
    return creada


def _detalle(cliente, execution_id) -> dict:
    r = cliente.get(f"/api/v1/frequency/executions/{execution_id}")
    assert r.status_code == 200, r.text
    return r.json()


def _ids(*ejecuciones) -> list[str]:
    return [str(e) for e in ejecuciones]


def _conteos(s, ids: list[str]) -> dict:
    """Predicciones y filas de la foto (de la ruta y por segmento) de esas ejecuciones. Termina la transacción de
    lectura: abierta, su AccessShareLock sobre feature_snapshot frenaría la partición del mes del ciclo siguiente."""
    s.expire_all()
    uuids = [uuid.UUID(i) for i in ids]
    de_ellas = FotoVariables.execution_id.in_(uuids)
    out = {"predicciones": s.scalar(select(func.count()).select_from(Prediccion)
                                    .where(Prediccion.execution_id.in_(uuids))),
           "foto_ruta": s.scalar(select(func.count()).select_from(FotoVariables)
                                 .where(de_ellas, FotoVariables.segmento.is_(None))),
           "foto_segmento": s.scalar(select(func.count()).select_from(FotoVariables)
                                     .where(de_ellas, FotoVariables.segmento.is_not(None)))}
    s.rollback()
    return out


def _refrescos(s, ciclo=None) -> list[dict]:
    """Los trabajos «segmentos» en orden de creación; con `ciclo`, solo los pedidos tras ese ciclo."""
    filas = s.execute(text(f"SELECT execution_id, estado, parametros, creado_en FROM {E}.execution_log "
                           "WHERE tipo = 'segmentos' ORDER BY creado_en")).mappings().all()
    s.rollback()
    todos = [dict(f) for f in filas]
    return todos if ciclo is None else [r for r in todos if (r["parametros"] or {}).get("ciclo") == str(ciclo)]


def _pendientes(s) -> list[dict]:
    return [r for r in _refrescos(s) if r["estado"] == "en_cola"]


def _repetidas(s, ids: list[str]) -> tuple[int, int]:
    """Filas repetidas de la foto por segmento y de la foto de la ruta (por predicción, segmento, sentido y hora)."""
    params = {"ids": ids}
    seg = s.execute(text(
        f"SELECT count(*) FROM (SELECT prediction_id, segmento, sentido, fecha, hora FROM {E}.feature_snapshot "
        "WHERE execution_id = ANY(CAST(:ids AS uuid[])) AND segmento IS NOT NULL GROUP BY 1, 2, 3, 4, 5 "
        "HAVING count(*) > 1) x"), params).scalar()
    ruta = s.execute(text(
        f"SELECT count(*) FROM (SELECT prediction_id, fecha, hora FROM {E}.feature_snapshot "
        "WHERE execution_id = ANY(CAST(:ids AS uuid[])) AND segmento IS NULL GROUP BY 1, 2, 3 "
        "HAVING count(*) > 1) x"), params).scalar()
    s.rollback()
    return seg, ruta


def _fuera_de_su_particion(s, ids: list[str]) -> int:
    """Filas de la foto que no están en la partición mensual (UTC) de su ventana_inicio."""
    n = s.execute(text(
        f"SELECT count(*) FROM {E}.feature_snapshot f JOIN pg_class c ON c.oid = f.tableoid "
        "WHERE f.execution_id = ANY(CAST(:ids AS uuid[])) "
        "AND c.relname <> 'feature_snapshot_' || to_char(f.ventana_inicio AT TIME ZONE 'UTC', 'YYYYMM')"),
        {"ids": ids}).scalar()
    s.rollback()
    return n


def _filas_foto(s, ids: list[str], *, segmento: bool) -> Counter:
    """Lo que dejó la foto, sin lo que cambia entre ejecuciones (identificadores, corte): ruta, horizonte, sentido,
    segmento, fecha, hora, modelo, ventana y un hash de las variables."""
    filas = s.execute(text(
        "SELECT ruta, horizonte_min, sentido, segmento, fecha, hora, model_id, ventana_inicio, "
        f"md5(CAST(features AS text)) FROM {E}.feature_snapshot WHERE execution_id = ANY(CAST(:ids AS uuid[])) "
        f"AND segmento IS {'NOT ' if segmento else ''}NULL"), {"ids": ids}).all()
    s.rollback()
    return Counter(tuple(f) for f in filas)


def _correr_refresco(cliente, s, refresco_id) -> dict:
    from app.servicios import ejecucion

    ejecucion.ejecutar(refresco_id)        # sin trabajadores en las pruebas: la cola lo procesa aquí
    d = _detalle(cliente, refresco_id)
    assert d["estado"] == "ok" and float(d["progreso"]) == 100, d
    s.rollback()
    return d


def _robar_la_reserva(original):
    """cola.cerrar_ok de una réplica que perdió la reserva: otra réplica tomó la fila justo antes del cierre (la cerca
    ve otro worker_id en la misma transacción) y el intento se revierte completo."""
    def cerrar(sesion, execution_id, valores):
        sesion.execute(text(f"UPDATE {E}.execution_log SET worker_id = 'otra-replica' WHERE execution_id = :i"),
                       {"i": execution_id})
        return original(sesion, execution_id, valores)

    return cerrar


def _vencer_reserva(s, execution_id) -> None:
    from app.servicios import cola

    s.execute(text(f"UPDATE {E}.execution_log SET lease_hasta = now() - interval '1 minute' WHERE execution_id = :i"),
              {"i": execution_id})
    s.commit()
    assert uuid.UUID(str(execution_id)) in cola.liberar_vencidas(max_reintentos=3)


def _intentos(s, execution_id) -> list[str]:
    filas = s.execute(text(f"SELECT resultado FROM {E}.execution_attempt WHERE execution_id = :i ORDER BY intento"),
                      {"i": execution_id}).scalars().all()
    s.rollback()
    return list(filas)


# ---------------------------------------------------------------- 1. sin partir: caída en el cierre y retoma
def test_sin_partir_la_reserva_perdida_y_el_fallo_en_el_cierre_no_dejan_foto_ni_refresco_y_la_retoma_deja_uno(
        cliente, entorno, pedidos_de_refresco):
    from app.servicios import cola, ejecucion

    s = entorno.sesion
    entorno.nuevo_proceso()
    eid = ejecucion.crear_ejecucion(s, "frecuencia", {"hasta": "2025-09-15"}, "convivencia-sin-partir").execution_id
    entorno.ids.append(eid)
    s.rollback()
    original = cola.cerrar_ok

    # 1) la reserva se pierde en el cierre con cerca: se revierte todo y no se pide el refresco
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(cola, "cerrar_ok", _robar_la_reserva(original))
        r1 = cola.reclamar("convivencia:w1", execution_id=eid)
        assert r1 is not None
        assert cola.correr_reclamo(r1, max_reintentos=3, base_espera=0.0) == "reserva_perdida"
    assert _conteos(s, _ids(eid)) == {"predicciones": 0, "foto_ruta": 0, "foto_segmento": 0}
    assert not pedidos_de_refresco and not _refrescos(s, eid) and not _pendientes(s)
    _vencer_reserva(s, eid)                # la reserva de w1 vence y vuelve a la cola, como la retoma de otra réplica

    # 2) un fallo reintentable en el cierre: tampoco deja nada ni pide el refresco
    def fallar(sesion, execution_id, valores):
        raise RuntimeError("fallo simulado en el cierre")

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(cola, "cerrar_ok", fallar)
        r2 = cola.reclamar("convivencia:w2", execution_id=eid)
        assert r2 is not None
        assert cola.correr_reclamo(r2, max_reintentos=5, base_espera=0.0) == "reintento"
    assert _conteos(s, _ids(eid)) == {"predicciones": 0, "foto_ruta": 0, "foto_segmento": 0}
    assert not pedidos_de_refresco and not _refrescos(s, eid) and not _pendientes(s)

    # 3) otra réplica la retoma y termina «ok»: la foto queda una vez y se pide UN refresco, después del cierre
    r3 = cola.reclamar("convivencia:w3", execution_id=eid)
    assert r3 is not None
    assert cola.correr_reclamo(r3, max_reintentos=5, base_espera=0.0) == "ok"
    fin = _detalle(cliente, eid)
    assert fin["estado"] == "ok" and fin["filas_validas"] > 0, fin["mensaje"]
    seg = fin["metricas"]["monitoreo"]["feature_snapshot_segmentos"]
    assert seg["estado"] == "ok" and seg["filas"] > 0, seg
    conteos = _conteos(s, _ids(eid))
    assert conteos["predicciones"] > 0 and conteos["foto_ruta"] > 0 and conteos["foto_segmento"] == seg["filas"]
    assert _repetidas(s, _ids(eid)) == (0, 0) and _fuera_de_su_particion(s, _ids(eid)) == 0
    assert _intentos(s, eid) == ["reserva_perdida", "reintento", "ok"]
    # los consolidados de Extreme (app/servicios/consolidados.py) se leen al cerrar; en la fuente sintética no tienen
    # filas y el resumen de calidad lo dice
    assert fin["metricas"]["calidad"]["consolidados"]["resultados"] == {"sin_filas_fuente": 3}
    assert pedidos_de_refresco == [str(eid)]
    (refresco,) = _refrescos(s, eid)
    assert refresco["estado"] == "en_cola" and refresco["parametros"]["origen"] == "ciclo"
    assert [r["execution_id"] for r in _pendientes(s)] == [refresco["execution_id"]]
    assert refresco["creado_en"] >= pd.Timestamp(fin["terminado_en"]).to_pydatetime()   # pedido tras confirmar
    hecho = _correr_refresco(cliente, s, refresco["execution_id"])
    est = cliente.get("/api/v1/segmentos/estadisticas", params={"idruta": 16, "limite": 5}).json()
    assert est["disponible"] is True and est["materializacion"]["execution_id"] == hecho["execution_id"]


# ---------------------------------------------------------------- 2. partida por ruta: foto y un solo refresco
def test_partida_por_ruta_guarda_la_foto_una_vez_por_trabajo_igual_que_sin_partir_y_la_madre_pide_un_refresco(
        cliente, entorno, pedidos_de_refresco):
    s = entorno.sesion
    dia = "2025-09-17"
    entorno.nuevo_proceso()
    sin_partir = _detalle(cliente, _post(cliente, entorno, hasta=dia)["execution_id"])
    assert sin_partir["estado"] == "ok" and sin_partir["filas_validas"] > 0, sin_partir["mensaje"]
    x = sin_partir["execution_id"]
    assert pedidos_de_refresco == [x]
    (primero,) = _refrescos(s, x)
    _correr_refresco(cliente, s, primero["execution_id"])
    pedidos_de_refresco.clear()

    entorno.nuevo_proceso()                 # la partida lee el mismo día desde cero, con sus marcas por ruta
    creada = _post(cliente, entorno, hasta=dia, particion="ruta")
    madre = _detalle(cliente, creada["execution_id"])
    assert madre["estado"] == "ok" and madre["metricas"]["trabajos_ok"] == len(RUTAS), madre["mensaje"]
    trabajos = {t["ruta"]: t for t in madre["trabajos"]}
    assert set(trabajos) == set(RUTAS) and madre["filas_validas"] == sin_partir["filas_validas"]
    ids_trabajos = _ids(*(t["execution_id"] for t in trabajos.values()))

    # cada trabajo guarda la foto de SUS predicciones: en su ejecución, de su ruta y en la partición de su ventana
    for ruta, t in trabajos.items():
        d = _detalle(cliente, t["execution_id"])
        seg = d["metricas"]["monitoreo"]["feature_snapshot_segmentos"]
        assert seg["estado"] == "ok" and seg["filas"] > 0, (ruta, seg)
        conteos = _conteos(s, _ids(t["execution_id"]))
        assert conteos["foto_segmento"] == seg["filas"]
        assert conteos["foto_ruta"] + conteos["foto_segmento"] == d["metricas"]["monitoreo"]["feature_snapshot_filas"]
        rutas_de_la_foto = s.execute(text(f"SELECT DISTINCT ruta FROM {E}.feature_snapshot WHERE execution_id = :i"),
                                     {"i": t["execution_id"]}).scalars().all()
        s.rollback()
        assert rutas_de_la_foto == [ruta]
    # los consolidados de Extreme los lee la madre al cerrar, una vez por ejecución; ningún trabajo de ruta
    assert madre["metricas"]["calidad"]["consolidados"]["resultados"] == {"sin_filas_fuente": 3}
    assert not [r for r, t in trabajos.items()
                if "consolidados" in (_detalle(cliente, t["execution_id"])["metricas"].get("calidad") or {})]
    # la madre no guarda foto (sus trabajos ya la guardaron): ninguna fila queda dos veces
    assert _conteos(s, _ids(madre["execution_id"])) == {"predicciones": 0, "foto_ruta": 0, "foto_segmento": 0}
    assert "feature_snapshot_segmentos" not in (madre["metricas"].get("monitoreo") or {})
    assert _repetidas(s, ids_trabajos) == (0, 0) and _fuera_de_su_particion(s, ids_trabajos) == 0
    # las mismas filas (y las mismas variables) que la ejecución sin partir del mismo día
    for segmento in (True, False):
        partida, entera = _filas_foto(s, ids_trabajos, segmento=segmento), _filas_foto(s, [x], segmento=segmento)
        assert partida and partida == entera, (segmento, sum(partida.values()), sum(entera.values()))

    # el refresco: lo pide la madre, una sola vez y después de cerrar; ningún trabajo de ruta lo pide
    assert pedidos_de_refresco == [madre["execution_id"]]
    (pendiente,) = _pendientes(s)
    assert _refrescos(s, madre["execution_id"]) == [pendiente]
    assert pendiente["creado_en"] >= pd.Timestamp(madre["terminado_en"]).to_pydatetime()
    assert not any(_refrescos(s, t) for t in ids_trabajos)
    _correr_refresco(cliente, s, pendiente["execution_id"])


# ---------------------------------------------------------------- 3. partida por ruta con caída de un trabajo
def test_partida_por_ruta_un_trabajo_que_pierde_la_reserva_no_deja_foto_ni_refresco_y_al_retomarlo_queda_uno(
        cliente, entorno, pedidos_de_refresco):
    from app.servicios import cola

    s = entorno.sesion
    entorno.nuevo_proceso()
    creada = _post(cliente, entorno, encolar_solo=True, hasta="2025-09-19", particion="ruta")
    madre = creada["execution_id"]
    trabajos = [t["execution_id"] for t in creada["trabajos"]]
    caido = trabajos[0]

    with pytest.MonkeyPatch.context() as mp:     # el trabajo de la primera ruta pierde la reserva en el cierre
        mp.setattr(cola, "cerrar_ok", _robar_la_reserva(cola.cerrar_ok))
        r1 = cola.reclamar("convivencia:ruta-w1", execution_id=uuid.UUID(caido))
        assert r1 is not None and r1.ruta == creada["trabajos"][0]["ruta"]
        assert cola.correr_reclamo(r1, max_reintentos=3, base_espera=0.0) == "reserva_perdida"
    assert _conteos(s, [caido]) == {"predicciones": 0, "foto_ruta": 0, "foto_segmento": 0}
    assert not pedidos_de_refresco
    _vencer_reserva(s, caido)
    r2 = cola.reclamar("convivencia:ruta-w2", execution_id=uuid.UUID(caido))      # otra réplica lo retoma
    assert r2 is not None and cola.correr_reclamo(r2, max_reintentos=3, base_espera=0.0) == "ok"
    assert not pedidos_de_refresco               # un trabajo de ruta no pide el refresco
    for t in trabajos[1:]:
        assert cola.procesar(uuid.UUID(t)) == "ok"
    assert not pedidos_de_refresco
    assert cola.procesar(uuid.UUID(madre)) == "ok"

    d_madre = _detalle(cliente, madre)
    assert d_madre["metricas"]["trabajos_ok"] == len(RUTAS), d_madre["mensaje"]
    assert _intentos(s, caido) == ["reserva_perdida", "ok"]
    d_caido = _detalle(cliente, caido)
    assert _conteos(s, [caido])["foto_segmento"] == d_caido["metricas"]["monitoreo"]["feature_snapshot_segmentos"][
        "filas"] > 0
    assert _repetidas(s, trabajos) == (0, 0) and _fuera_de_su_particion(s, trabajos) == 0
    assert pedidos_de_refresco == [madre]
    (pendiente,) = _pendientes(s)
    assert _refrescos(s, madre) == [pendiente] and not any(_refrescos(s, t) for t in trabajos)
    _correr_refresco(cliente, s, pendiente["execution_id"])


# ---------------------------------------------------------------- 4. la misma versión de umbrales en toda la ejecución
def test_la_madre_y_sus_trabajos_usan_la_misma_version_de_umbrales_y_de_parametros_del_plan(cliente, entorno):
    """§5.1 con RNF-005: un PUT /thresholds que llega mientras corren los trabajos de una ejecución partida no la
    parte en dos versiones. La madre y todos sus trabajos (recomendaciones de franja, plan del día con su tarifa,
    elasticidad y suavidad, y foto de la respuesta del reto con las mismas salidas que ese plan) usan la versión
    vigente al crear la ejecución; la ejecución siguiente usa la nueva."""
    from app.servicios import cola

    s = entorno.sesion
    entorno.nuevo_proceso()
    antes = cliente.get("/api/v1/thresholds").json()
    version, elasticidad = antes["version"], antes["valores"]["elasticidad"]
    creada = _post(cliente, entorno, encolar_solo=True, hasta="2025-09-21", particion="ruta")
    madre, trabajos = creada["execution_id"], [t["execution_id"] for t in creada["trabajos"]]
    assert cola.procesar(uuid.UUID(trabajos[0])) == "ok"
    r = cliente.put("/api/v1/thresholds", json={"valores": {"elasticidad": 0.35},
                                                "motivo": "convivencia: cambio a mitad de una ejecución partida"})
    assert r.status_code == 200, r.text
    nueva = r.json()["version"]
    try:
        assert nueva > version
        for t in trabajos[1:]:
            assert cola.procesar(uuid.UUID(t)) == "ok"
        assert cola.procesar(uuid.UUID(madre)) == "ok"
        assert {_detalle(cliente, e)["umbrales_version"] for e in [madre, *trabajos]} == {version}
        filas = s.execute(text(
            f"SELECT origen, umbrales_version, detalle -> 'entradas' -> 'parametros' -> 'elasticidad' AS elasticidad "
            f"FROM {E}.recommendation WHERE execution_id = ANY(CAST(:ids AS uuid[]))"), {"ids": trabajos}).all()
        s.rollback()
        # franja y plan del modelo horario; corto_plazo, la recomendación de cada pronóstico de 30, 60 y 120 min
        assert {f.origen for f in filas} == {"franja", "plan_dia", "corto_plazo"}
        assert {f.umbrales_version for f in filas} == {version}
        plan = [f.elasticidad for f in filas if f.origen == "plan_dia"]
        assert plan and all(e == {"valor": float(elasticidad), "fuente": f"threshold_config v{version}"} for e in plan)
        # la foto de la respuesta de cada trabajo, también con esa versión y con las mismas salidas que su plan
        # guardado (reutiliza el plan: no vuelve a resolver el MILP con los umbrales nuevos)
        fotos = s.execute(text(
            "SELECT r.ruta, r.umbrales_version, (SELECT sum(CAST(x ->> 'buses_hora' AS numeric)) FROM "
            "jsonb_array_elements(r.payload -> 'ruta' -> 'cada_cuanto_despachar') x) AS salidas_foto, "
            f"(SELECT sum(p.buses_hora) FROM {E}.recommendation p WHERE p.execution_id = r.execution_id "
            f"AND p.origen = 'plan_dia') AS salidas_plan FROM {E}.respuesta_reto r "
            "WHERE r.execution_id = ANY(CAST(:ids AS uuid[]))"), {"ids": trabajos}).all()
        s.rollback()
        assert sorted(f.ruta for f in fotos) == sorted(RUTAS) and {f.umbrales_version for f in fotos} == {version}
        assert all(f.salidas_foto is not None and f.salidas_foto == f.salidas_plan for f in fotos), fotos
        # la ejecución siguiente ya usa la versión nueva (el siguiente cálculo, sin reiniciar)
        siguiente = _detalle(cliente, _post(cliente, entorno, hasta="2025-09-22", particion="ruta")["execution_id"])
        assert siguiente["estado"] == "ok" and siguiente["metricas"]["trabajos_ok"] == len(RUTAS)
        assert {siguiente["umbrales_version"]} | {t["umbrales_version"] for t in
                                                   (_detalle(cliente, x["execution_id"])
                                                    for x in siguiente["trabajos"])} == {nueva}
    finally:
        restituir_umbrales(s, version)        # sin la versión creada por PUT y con la de antes vigente


# ---------------------------------------------------------------- 5. la franja programada con PLAN_PARTICION=ruta
def test_con_plan_particion_ruta_la_franja_programada_fija_su_version_y_la_madre_pide_un_solo_refresco(
        cliente, entorno, pedidos_de_refresco, monkeypatch):
    """PLAN_PARTICION=ruta: la franja del planificador encola la madre y un trabajo por ruta con la versión de umbrales
    fijada; al procesarlos, la foto queda una vez por trabajo y el refresco de segmentos lo pide la madre, una vez."""
    from app.servicios import cola, planificador

    s = entorno.sesion
    entorno.nuevo_proceso()
    monkeypatch.setattr(planificador, "obtener_ajustes",
                        lambda: SimpleNamespace(plan_ejecucion_cron="15 5 * * *", plan_particion="ruta"))
    ahora = datetime(2027, 1, 1, 5, 16, tzinfo=planificador.ZONA) + timedelta(days=uuid.uuid4().int % 3000)
    madre = planificador.tarea_ejecucion_diaria(ahora)          # una franja propia: nadie más la encoló
    assert madre is not None
    entorno.ids.append(madre)
    version = cliente.get("/api/v1/thresholds").json()["version"]
    trabajos = [str(t) for t in s.scalars(select(Ejecucion.execution_id).where(Ejecucion.padre_id == madre)
                                          .order_by(Ejecucion.creado_en))]
    s.rollback()
    assert len(trabajos) == len(RUTAS)
    for t in trabajos:
        assert cola.procesar(uuid.UUID(t)) == "ok"
    assert not pedidos_de_refresco               # ningún trabajo de ruta pide el refresco
    assert cola.procesar(madre) == "ok"
    d = _detalle(cliente, madre)
    assert d["metricas"]["trabajos_ok"] == len(RUTAS) and d["parametros"]["umbrales_version"] == version
    assert {d["umbrales_version"]} | {_detalle(cliente, t)["umbrales_version"] for t in trabajos} == {version}
    # la madre de la franja programada también cierra los consolidados de Extreme, una vez (sin filas en esta fuente)
    assert d["metricas"]["calidad"]["consolidados"]["resultados"] == {"sin_filas_fuente": 3}
    assert _conteos(s, trabajos)["foto_segmento"] > 0
    assert _conteos(s, [str(madre)]) == {"predicciones": 0, "foto_ruta": 0, "foto_segmento": 0}
    assert _repetidas(s, trabajos) == (0, 0) and _fuera_de_su_particion(s, trabajos) == 0
    assert pedidos_de_refresco == [str(madre)]
    (pendiente,) = _pendientes(s)
    assert _refrescos(s, madre) == [pendiente] and not any(_refrescos(s, t) for t in trabajos)
    _correr_refresco(cliente, s, pendiente["execution_id"])
