"""Capa analítica de segmentos y zonas (§6.1, §6.2, §11.2) contra la réplica, en solo lectura (lector_ia).

Comprueba la coherencia de lo derivado (mín ≤ promedio ≤ máx, totales iguales a un SQL directo, día ISO y la
estacionalidad elegida con la misma regla que fn_insert_timbradas_anio) y el endpoint con autenticación, paginación,
orden y exportación.
"""
from __future__ import annotations

import io
from datetime import date

import pandas as pd
import pytest

from scripts import replica_comun as rc

psycopg = pytest.importorskip("psycopg")
DIA = date(2023, 2, 14)          # martes con datos de las tres rutas en la carga


@pytest.fixture
def motor(cargada):
    from sqlalchemy import create_engine

    url = rc.url_rol("lector_ia")
    if not url:
        pytest.skip("falta LECTOR_IA_PASSWORD")
    m = create_engine(url.replace("postgresql://", "postgresql+psycopg://"), pool_size=1, max_overflow=0)
    yield m
    m.dispose()


def test_estadisticas_coherentes_con_sql_directo(motor, lector):
    from app.servicios import segmentos

    r = segmentos.estadisticas(motor=motor, idruta=21, desde=DIA, hasta=DIA, limite=500)
    assert r["total"] > 0 and len(r["items"]) == min(500, r["total"])
    todo = segmentos.estadisticas_df(motor=motor, idruta=21, desde=DIA, hasta=DIA)
    assert len(todo) == r["total"]
    for medida in ("subidas", "bajadas", "pasajeros"):
        assert (todo[f"min_{medida}"] <= todo[f"prom_{medida}"] + 1e-9).all()
        assert (todo[f"prom_{medida}"] <= todo[f"max_{medida}"] + 1e-9).all()
    assert set(todo["id_dia_semana"]) == {DIA.isoweekday()}
    with lector.cursor() as cur:
        cur.execute("""SELECT coalesce(sum(ts.subidas), 0), coalesce(sum(ts.bajadas), 0)
                         FROM public.timbradas_segmentos ts JOIN public.rutas_segmentos rs ON rs.id = ts.id_segmento
                        WHERE rs.idruta = 21 AND ts.fecha = %s""", (DIA,))
        subidas, bajadas = cur.fetchone()
        cur.execute("""SELECT e.id_estacionalidad FROM public.estacionalidades_anio e
                        WHERE e.proceso = 'sobusa' AND e.fecha_inicio <= %s AND e.fecha_fin >= %s
                        ORDER BY (e.fecha_fin - e.fecha_inicio), e.fecha_inicio DESC, e.id_estacionalidad_anio DESC
                        LIMIT 1""", (DIA, DIA))
        estacionalidad = cur.fetchone()[0]
    assert int(todo["subidas"].sum()) == subidas and int(todo["bajadas"].sum()) == bajadas
    assert set(todo["id_estacionalidad"].dropna().astype(int)) == {estacionalidad}


def test_orden_y_filtros_validados(motor):
    from app.servicios import segmentos

    r = segmentos.estadisticas(motor=motor, idruta=2, desde=DIA, hasta=DIA, orden="-max_subidas", limite=5)
    maximos = [x["max_subidas"] for x in r["items"]]
    assert maximos == sorted(maximos, reverse=True)
    with pytest.raises(ValueError):
        segmentos.estadisticas(motor=motor, orden="subidas; DROP TABLE rutas")
    with pytest.raises(ValueError):
        segmentos.estadisticas(motor=motor, desde=date(2024, 1, 2), hasta=date(2024, 1, 1))


def test_zonas_tarifarias_explican_por_que_no_hay_filas(motor):
    from app.servicios import segmentos

    for nivel in ("anio", "consolidado"):
        z = segmentos.zonas(nivel=nivel, motor=motor)
        assert z["total"] == 0 and "maneja_zonas" in z["nota"] and len(z["rutas"]) == 3


def test_endpoint_con_autenticacion_paginacion_y_exportacion(motor, monkeypatch):
    from fastapi.testclient import TestClient

    from app import seguridad
    from app.main import app
    from app.servicios import segmentos

    fuente_original = segmentos.fuente
    monkeypatch.setattr(segmentos, "fuente", lambda motor_=None: fuente_original(motor))
    clave = "clave-de-prueba-segmentos-0123456789"
    monkeypatch.setenv("API_KEY_OPERADOR", clave)
    ajustes = seguridad.obtener_ajustes()
    monkeypatch.setattr(ajustes, "auth_habilitada", True)
    cliente = TestClient(app)
    params = {"idruta": 16, "desde": DIA.isoformat(), "hasta": DIA.isoformat(), "limite": 3, "desplazamiento": 2}
    assert cliente.get("/api/v1/segmentos/estadisticas", params=params).status_code == 401
    r = cliente.get("/api/v1/segmentos/estadisticas", params=params, headers={"X-API-Key": clave})
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["limite"] == 3 and cuerpo["desplazamiento"] == 2 and len(cuerpo["items"]) == 3
    assert cliente.get("/api/v1/segmentos/estadisticas", params={**params, "id_dia_semana": 9},
                       headers={"X-API-Key": clave}).status_code == 422
    csv = cliente.get("/api/v1/segmentos/estadisticas/export", params={"idruta": 16, "desde": DIA.isoformat(),
                                                                       "hasta": DIA.isoformat(), "formato": "csv"},
                      headers={"X-API-Key": clave})
    assert csv.status_code == 200 and "attachment" in csv.headers["content-disposition"]
    df = pd.read_csv(io.BytesIO(csv.content), encoding="utf-8-sig")
    assert len(df) == cuerpo["total"] and {"prom_subidas", "max_subidas", "min_subidas"} <= set(df.columns)
    z = cliente.get("/api/v1/segmentos/zonas", headers={"X-API-Key": clave})
    assert z.status_code == 200 and z.json()["total"] == 0
