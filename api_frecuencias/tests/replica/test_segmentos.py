"""Capa analítica de segmentos y zonas (§6.1, §6.2, §7.1, §11.2, RNF-002) contra la réplica en solo lectura (lector_ia).

Comprueba la coherencia de lo derivado (mín ≤ promedio ≤ máx, totales iguales a un SQL directo, día ISO y la
estacionalidad elegida con la misma regla que fn_insert_timbradas_anio), que la agregación MATERIALIZADA que sirve la
API (refrescada desde la réplica con lector_ia hacia la base LOCAL de pruebas, nunca hacia la réplica) da exactamente
lo mismo que la agregación directa, y el endpoint con autenticación, paginación, orden y exportación.

Con GENERAR_EVIDENCIAS=1 la comparación queda en docs/evidencias/pruebas/segmentos_equivalencia.json.
"""
from __future__ import annotations

import io
import json
import time
from datetime import date

import pandas as pd
import pytest
from sqlalchemy import text

from scripts import replica_comun as rc
from tests.evidencia import guardar_evidencia

psycopg = pytest.importorskip("psycopg")
DIA = date(2023, 2, 14)          # martes con datos de las tres rutas en la carga
# Combinaciones de filtros, orden y paginación que se comparan entre la agregación directa y la materializada
CASOS = [
    ({}, None, 50, 0),
    ({"idruta": 2}, None, 50, 0),
    ({"idruta": 16, "id_dia_semana": 2}, "-max_subidas", 50, 0),
    ({"hora": 7}, "prom_pasajeros", 50, 0),
    ({"idruta": 21, "id_estacionalidad": 25}, None, 100, 250),
    ({"desde": DIA, "hasta": DIA}, None, 50, 0),
    ({"desde": date(2023, 1, 1), "hasta": date(2023, 1, 31)}, "-nro_viajes", 50, 0),
    ({"desde": date(2023, 1, 10), "idruta": 21}, None, 50, 100),
]


@pytest.fixture(scope="module")
def motor(cargada):
    from sqlalchemy import create_engine

    url = rc.url_rol("lector_ia")
    if not url:
        pytest.skip("falta LECTOR_IA_PASSWORD")
    m = create_engine(url.replace("postgresql://", "postgresql+psycopg://"), pool_size=1, max_overflow=0)
    yield m
    m.dispose()


@pytest.fixture(scope="module")
def propia():
    """Base LOCAL de pruebas (TEST_DATABASE_NAME, migrada a head): ahí se escribe la agregación materializada. La
    réplica solo se lee."""
    from sqlalchemy import create_engine

    from tests.integracion import conftest as base_local

    url = base_local.requerir_base()
    base_local._alembic("upgrade", "head")
    m = create_engine(url, connect_args={"options": "-c timezone=America/Bogota"})
    yield m
    with m.begin() as c:
        for tabla in ("segmento_estadistica_refresco", "segmento_estadistica", "segmento_estadistica_dia"):
            c.execute(text(f"DELETE FROM ai_frecuencias.{tabla}"))
    m.dispose()


@pytest.fixture
def referencia_sin_apuro(monkeypatch):
    """La agregación DIRECTA (la referencia) sin filtros tarda 15 a 19 s en la réplica y más con el equipo cargado:
    para compararla se le da un statement_timeout de 5 minutos. El refresco materializado sigue con el de 30 s."""
    from app.config import obtener_ajustes

    monkeypatch.setattr(obtener_ajustes(), "fuente_statement_timeout_ms", 300_000)


@pytest.fixture(scope="module")
def materializada(propia, motor):
    """Refresco completo desde la réplica (lector_ia, READ ONLY, por tramos) hacia la base propia."""
    from sqlalchemy.orm import Session

    from app.servicios import segmentos, segmentos_refresco

    t0 = time.perf_counter()
    with Session(propia) as s:
        resumen = segmentos_refresco.refrescar(s, segmentos.fuente(motor), None, {"modo": "completo"})
        s.commit()
    return {**resumen, "segundos": round(time.perf_counter() - t0, 2)}


def test_estadisticas_coherentes_con_sql_directo(motor, lector):
    from app.servicios import segmentos

    r = segmentos.estadisticas_directas(motor=motor, idruta=21, desde=DIA, hasta=DIA, limite=500)
    assert r["total"] > 0 and len(r["items"]) == min(500, r["total"])
    todo = segmentos.estadisticas_directas_df(motor=motor, idruta=21, desde=DIA, hasta=DIA)
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

    r = segmentos.estadisticas_directas(motor=motor, idruta=2, desde=DIA, hasta=DIA, orden="-max_subidas", limite=5)
    maximos = [x["max_subidas"] for x in r["items"]]
    assert maximos == sorted(maximos, reverse=True)
    with pytest.raises(ValueError):
        segmentos.estadisticas_directas(motor=motor, orden="subidas; DROP TABLE rutas")
    with pytest.raises(ValueError):
        segmentos.estadisticas_directas(motor=motor, desde=date(2024, 1, 2), hasta=date(2024, 1, 1))


def test_agregacion_materializada_identica_a_la_directa(materializada, propia, motor, referencia_sin_apuro):
    """§6.1 y RNF-002: la agregación que sirve la API, refrescada por tramos desde la réplica, devuelve EXACTAMENTE las
    mismas filas (mismo JSON) y el mismo total que la agregación directa, con y sin filtros, rango de fechas, orden
    y paginación; y la consulta materializada no toca la réplica."""
    from sqlalchemy.orm import Session

    from app.servicios import segmentos

    assert materializada["modo"] == "completo" and materializada["filas"] > 100_000
    assert materializada["fecha_min"] == date(2023, 1, 1) and materializada["fecha_max"] == date(2023, 2, 27)
    comparaciones = []
    for filtros, orden, limite, desplazamiento in CASOS:
        t0 = time.perf_counter()
        directa = segmentos.estadisticas_directas(motor=motor, orden=orden, limite=limite,
                                                  desplazamiento=desplazamiento, **filtros)
        t1 = time.perf_counter()
        with Session(propia) as s:
            servida = segmentos.consultar(s, orden=orden, limite=limite, desplazamiento=desplazamiento, **filtros)
        t2 = time.perf_counter()
        identicas = json.dumps(servida["items"], sort_keys=True) == json.dumps(directa["items"], sort_keys=True)
        comparaciones.append({"filtros": {k: str(v) for k, v in filtros.items()}, "orden": orden, "limite": limite,
                              "desplazamiento": desplazamiento, "total": servida["total"],
                              "total_directa": directa["total"], "items_identicos": identicas,
                              "ms_directa": round((t1 - t0) * 1000), "ms_materializada": round((t2 - t1) * 1000)})
        assert identicas and servida["total"] == directa["total"] > 0, comparaciones[-1]
        assert servida["fuente"] == segmentos.FUENTE_MATERIALIZADA and servida["actualizado_en"].endswith("-05:00")
    guardar_evidencia("pruebas/segmentos_equivalencia.json", {
        "prueba": "tests/replica/test_segmentos.py::test_agregacion_materializada_identica_a_la_directa",
        "fuente": "réplica operacional local (lector_ia, READ ONLY), timbradas_segmentos 2023-01-01 a 2023-02-27",
        "refresco": {k: materializada[k] for k in ("modo", "tramos", "fechas_releidas", "filas_leidas", "filas_dia",
                                                    "filas", "fecha_min", "fecha_max", "segundos")},
        "comparaciones": comparaciones})


def _versiones_fisicas(s) -> dict[str, set[str]]:
    """ctid y xmin de cada fila visible de las dos tablas de la agregación (base propia): una fila insertada,
    actualizada o borrada en la transacción cambia el conjunto."""
    return {t: set(s.execute(text(f"SELECT ctid::text || ':' || xmin::text FROM ai_frecuencias.{t}")).scalars())
            for t in ("segmento_estadistica", "segmento_estadistica_dia")}


def _incremental_medido(propia, motor) -> dict:
    """Un refresco incremental desde la réplica (lector_ia) hacia la base propia, con su duración y las versiones de
    fila que escribió o quitó en cada tabla de la agregación."""
    from sqlalchemy.orm import Session

    from app.servicios import segmentos, segmentos_refresco

    with Session(propia) as s:
        antes = _versiones_fisicas(s)
        t0 = time.perf_counter()
        resumen = segmentos_refresco.refrescar(s, segmentos.fuente(motor), None, {"modo": "incremental"})
        segundos = time.perf_counter() - t0
        despues = _versiones_fisicas(s)
        s.commit()
    return {**{k: resumen[k] for k in ("modo", "tramos", "fechas_releidas", "filas_leidas",
                                       "filas_respuesta_reescritas", "filas_dia", "filas", "ventana")},
            "marca_fuente": resumen["marca_fuente"], "segundos": round(segundos, 2),
            "versiones_de_fila_escritas_o_quitadas": {t: len(antes[t] ^ despues[t]) for t in antes}}


def _diferencia_con_la_reconstruccion(propia) -> int:
    """Filas en que segmento_estadistica (base propia) difiere de rehacerla entera desde el grano diario (EXCEPT en los
    dos sentidos, la misma comparación de tests/integracion/test_segmentos_materializados.py); 0 = el refresco
    parcial dejó exactamente lo que deja uno completo."""
    from sqlalchemy.orm import Session

    from tests.integracion.test_segmentos_materializados import _diferencia_con_la_reconstruccion as diferencia

    with Session(propia) as s:
        return diferencia(s)


def test_refresco_sin_cambios_no_relee_la_ventana_de_solape_y_mide_la_diferencia(materializada, propia, motor,
                                                                                 monkeypatch):
    """(e) Sin filas nuevas en la réplica, la ventana de solape de 15 min (FUENTE_SOLAPE_MIN, hallazgos H7 y H10) igual
    tiene filas: las de la marca máxima (26 fechas en la réplica). Sin huellas comparables (como antes de la
    migración 0012) el incremental relee esas fechas y reagrega su parte de la agregación; con las huellas que dejó el
    refresco anterior termina «sin_cambios» sin escribir una sola fila. Tras ese refresco parcial,
    segmento_estadistica es exactamente la que daría rehacerla entera (todas sus filas) y la agregación directa; sin
    solape tampoco relee nada. Con GENERAR_EVIDENCIAS=1 la medición queda en
    docs/evidencias/pruebas/segmentos_sin_cambios.json."""
    from sqlalchemy.orm import Session

    from app.config import obtener_ajustes
    from app.servicios import segmentos

    con_huellas = _incremental_medido(propia, motor)          # el completo del fixture dejó las huellas
    assert con_huellas["modo"] == "sin_cambios" and con_huellas["fechas_releidas"] == 0, con_huellas
    assert con_huellas["filas_leidas"] == 0 and not any(con_huellas["versiones_de_fila_escritas_o_quitadas"].values())
    assert con_huellas["ventana"]["fechas_en_ventana"] > 0 and con_huellas["ventana"]["fechas_cambiadas"] == 0
    assert con_huellas["marca_fuente"] == materializada["marca_fuente"]
    with Session(propia) as s:                                 # como un refresco anterior a la 0012: sin huellas
        s.execute(text("UPDATE ai_frecuencias.segmento_estadistica_refresco SET huellas_solape = NULL"))
        s.commit()
    sin_huellas = _incremental_medido(propia, motor)
    assert sin_huellas["modo"] == "incremental" and sin_huellas["fechas_releidas"] == \
        con_huellas["ventana"]["fechas_en_ventana"] and sin_huellas["filas_leidas"] > 0
    assert sin_huellas["filas"] == materializada["filas"] and sin_huellas["filas_dia"] == materializada["filas_dia"]
    distintas = _diferencia_con_la_reconstruccion(propia)      # el parcial reagregó ~113 mil claves de 26 fechas
    assert distintas == 0
    otra_vez = _incremental_medido(propia, motor)              # ese incremental dejó las huellas: ya no relee
    assert otra_vez["modo"] == "sin_cambios" and otra_vez["filas_leidas"] == 0
    with Session(propia) as s:
        servida = segmentos.consultar(s, idruta=2, limite=50, desplazamiento=0)
    limite = obtener_ajustes().fuente_statement_timeout_ms
    monkeypatch.setattr(obtener_ajustes(), "fuente_statement_timeout_ms", 300_000)     # solo la referencia directa
    directa = segmentos.estadisticas_directas(motor=motor, idruta=2, limite=50, desplazamiento=0)
    monkeypatch.setattr(obtener_ajustes(), "fuente_statement_timeout_ms", limite)
    assert servida["items"] == directa["items"] and servida["total"] == directa["total"]
    monkeypatch.setattr(obtener_ajustes(), "fuente_solape_min", 0)
    sin_solape = _incremental_medido(propia, motor)
    assert sin_solape["modo"] == "sin_cambios" and sin_solape["fechas_releidas"] == 0
    guardar_evidencia("pruebas/segmentos_sin_cambios.json", {
        "prueba": "tests/replica/test_segmentos.py::"
                  "test_refresco_sin_cambios_no_relee_la_ventana_de_solape_y_mide_la_diferencia",
        "fuente": "réplica operacional local (lector_ia, READ ONLY) sin filas nuevas; agregación en la base propia",
        "solape_min": 15,
        "antes_sin_huellas": sin_huellas, "ahora_con_huellas": con_huellas, "siguiente_con_huellas": otra_vez,
        "sin_solape": sin_solape,
        "tras_el_parcial_filas_distintas_de_rehacerla_entera": distintas,
        "identica_a_la_directa": {"filtros": {"idruta": 2}, "total": servida["total"], "items_identicos": True}})


def test_zonas_tarifarias_explican_por_que_no_hay_filas(motor):
    from app.servicios import segmentos

    for nivel in ("anio", "consolidado"):
        z = segmentos.zonas(nivel=nivel, motor=motor)
        assert z["total"] == 0 and "maneja_zonas" in z["nota"] and len(z["rutas"]) == 3


def test_endpoint_con_autenticacion_paginacion_y_exportacion(materializada, propia, motor, monkeypatch):
    """El endpoint lee la agregación materializada (base propia) con autenticación, paginación, validación y
    exportación; las zonas siguen leyendo la réplica en solo lectura."""
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import Session

    from app import seguridad
    from app.db import obtener_sesion
    from app.main import app
    from app.servicios import segmentos

    def sesion_propia():
        s = Session(propia)
        try:
            yield s
        finally:
            s.close()

    fuente_original = segmentos.fuente
    monkeypatch.setattr(segmentos, "fuente", lambda motor_=None: fuente_original(motor))
    monkeypatch.setitem(app.dependency_overrides, obtener_sesion, sesion_propia)
    clave = "clave-de-prueba-segmentos-0123456789"
    monkeypatch.setenv("API_KEY_OPERADOR", clave)
    monkeypatch.setattr(seguridad.obtener_ajustes(), "auth_habilitada", True)
    cliente = TestClient(app)
    params = {"idruta": 16, "desde": DIA.isoformat(), "hasta": DIA.isoformat(), "limite": 3, "desplazamiento": 2}
    assert cliente.get("/api/v1/segmentos/estadisticas", params=params).status_code == 401
    r = cliente.get("/api/v1/segmentos/estadisticas", params=params, headers={"X-API-Key": clave})
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["limite"] == 3 and cuerpo["desplazamiento"] == 2 and len(cuerpo["items"]) == 3
    assert cuerpo["disponible"] is True and cuerpo["materializacion"]["fecha_max"] == "2023-02-27"
    directa = segmentos.estadisticas_directas(motor=motor, idruta=16, desde=DIA, hasta=DIA, limite=3,
                                              desplazamiento=2)
    assert cuerpo["items"] == directa["items"] and cuerpo["total"] == directa["total"]
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
