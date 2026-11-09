"""Llegada de datos por el trigger de Extreme y lectura incremental exacta (RF-013, §7.3, §9.5, §11.2).

Escriben en la réplica COMO EXTREME_DBA (el papel de la captura): solo corren con REPLICA_PRUEBAS_ESCRITURA=1, toman el
candado de la réplica (varias suites a la vez) y borran al final lo que insertaron. La API lee siempre con lector_ia.
"""
from __future__ import annotations

import os

import pytest

from scripts import replica_comun as rc
from scripts import replica_simular_llegada as sim

psycopg = pytest.importorskip("psycopg")

pytestmark = pytest.mark.skipif(os.environ.get("REPLICA_PRUEBAS_ESCRITURA") != "1",
                                reason="escribe en la réplica como extreme_dba: REPLICA_PRUEBAS_ESCRITURA=1")
VIAJE_A, VIAJE_B = 5141359, 5141360          # viajes reservados (fuera de la carga), con fechafin


def _fuente(**kw):
    from app.servicios.fuentes import FuentePostgresSoloLectura

    url = rc.url_rol("lector_ia").replace("postgresql://", "postgresql+psycopg://")
    return FuentePostgresSoloLectura(url=url, tabla=kw.pop("tabla", "timbradas_segmentos"), **kw)


@pytest.fixture
def captura(cargada):
    """Conexión de extreme_dba con el candado tomado; al final borra lo insertado de los viajes de prueba."""
    cx = sim.conectar()
    with sim.candado(cx, espera_s=600):
        try:
            yield cx
        finally:
            cx.rollback()
            sim.restaurar(cx, [VIAJE_A, VIAJE_B], con_respaldo=False)
    cx.close()


def _insertar(cx, viaje, n, confirmar=True):
    with cx.cursor() as cur:
        cols = sim.columnas_conteo(cur)
    filas = sim.filas_muestra([viaje], n)
    c = [x for x in cols if x in filas.columns]
    with cx.cursor() as cur:
        cur.executemany(f"INSERT INTO public.conteo_pasajeros ({', '.join(c)}) VALUES ({', '.join(['%s'] * len(c))})",
                        [tuple(None if v != v else (v.item() if hasattr(v, "item") else v) for v in fila)
                         for fila in filas[c].itertuples(index=False, name=None)])
    if confirmar:
        cx.commit()
    return len(filas)


def _ahora(cx):
    with cx.cursor() as cur:
        cur.execute("SELECT clock_timestamp()")
        t = cur.fetchone()[0]
    cx.commit()
    return t


def test_trigger_llena_timbradas_segmentos_y_la_lectura_es_exacta(captura):
    t0 = _ahora(captura)
    crudas = _insertar(captura, VIAJE_A, 40)
    with captura.cursor() as cur:
        cur.execute("SELECT count(*), sum(subidas) FROM public.timbradas_segmentos WHERE id_viaje = %s "
                    "AND ultimaactualizacion > %s", (VIAJE_A, t0))
        n_seg, subidas = cur.fetchone()
        cur.execute("SELECT coalesce(sum(cantidad_subida), 0) FROM public.conteo_pasajeros WHERE idprogramacion = %s",
                    (VIAJE_A,))
        subidas_crudas = cur.fetchone()[0]
    captura.commit()
    assert crudas == 40 and n_seg > 0 and subidas == subidas_crudas      # Σ segmentado = Σ crudo (con la E2)
    f = _fuente()
    d1, m1 = f.leer_incremental(t0)
    assert f.resumen_lectura["leidas"] == n_seg and set(d1["id_viaje"]) == {VIAJE_A}
    d2, m2 = f.leer_incremental(m1, estado_previo=f.estado_incremental)
    assert len(d2) == 0 and f.resumen_lectura["repetidas_solape"] == n_seg and m2 == m1
    dem = _fuente(tabla="demanda_segmentos")
    d3, _ = dem.leer_incremental(t0)
    assert len(d3) == 1 and int(d3["salidas"].iloc[0]) >= 1                 # una franja (ruta, fecha, hora)
    f._engine().dispose()
    dem._engine().dispose()


def test_solape_recupera_la_captura_que_confirma_tarde_exactamente_una_vez(captura):
    """NOW() es el inicio de la transacción: una captura que empieza antes de la lectura y confirma después queda con
    una marca ANTERIOR a la marca leída. Sin solape se pierde; con solape se entrega una vez."""
    t0 = _ahora(captura)
    tardia = sim.conectar()
    try:
        _insertar(tardia, VIAJE_A, 25, confirmar=False)          # transacción abierta: marca = su inicio
        _insertar(captura, VIAJE_B, 25)                            # otra captura confirma antes, con marca mayor
        f = _fuente()
        d1, m1 = f.leer_incremental(t0)
        assert set(d1["id_viaje"]) == {VIAJE_B}
        estado = f.estado_incremental
        tardia.commit()                                            # ahora sí llegan las filas del viaje A
        sin_solape = _fuente(solape_min=0)
        d0, _ = sin_solape.leer_incremental(m1)
        assert len(d0) == 0                                        # sin solape: perdidas
        d2, m2 = f.leer_incremental(m1, estado_previo=estado)
        r = f.resumen_lectura
        assert set(d2["id_viaje"]) == {VIAJE_A} and r["tardias"] == len(d2) > 0
        assert r["repetidas_solape"] == len(d1)
        d3, _ = f.leer_incremental(m2, estado_previo=f.estado_incremental)
        assert len(d3) == 0                                        # exactamente una vez
        f._engine().dispose()
        sin_solape._engine().dispose()
    finally:
        tardia.rollback()
        tardia.close()
