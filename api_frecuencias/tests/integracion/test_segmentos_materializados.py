"""Agregación materializada de segmentos (§6.1, §7.1, RNF-002, RNF-004) contra la base LOCAL de pruebas.

Las tablas de Extreme que lee la capa de segmentos (rutas, rutas_segmentos, estacionalidades_anio y
timbradas_segmentos, con el DDL de «1. tablas.sql» y la errata E2) se crean en un esquema aparte de la base de pruebas
con datos sintéticos que ejercitan los casos borde: un viaje que cruza el mismo segmento en dos bloques de 15 minutos
de la misma hora (E2), pasajeros negativos (H9), fechas sin estacionalidad, vigencias superpuestas (gana la más corta)
y empatadas (gana la de id mayor), una ruta de otro proceso y dos configuraciones de una ruta con el mismo
nro_segmento. La fuente se lee con FuentePostgresSoloLectura (READ ONLY, statement_timeout, ROLLBACK), como la réplica.

Prueba que la agregación materializada es idéntica a la directa, que el refresco es un trabajo de la cola con
progreso, reintento y cerca, que la consulta nunca bloquea (encola si no hay agregación), el modo incremental, el
cambio de catálogos, la exportación, el planificador y el encolado tras un ciclo con datos nuevos.
"""
from __future__ import annotations

import io
import json
import random
import uuid
from datetime import date, datetime, time, timedelta

import pandas as pd
import pytest
from sqlalchemy import create_engine, text

E = "ai_frecuencias"
ESQUEMA = "fuente_segmentos_prueba"
DDL_FUENTE = f"""
CREATE TABLE {ESQUEMA}.rutas (idruta bigint PRIMARY KEY, nombre text, proceso text, maneja_zonas boolean,
                              id_tipo_tarifa bigint);
CREATE TABLE {ESQUEMA}.rutas_segmentos (id bigint PRIMARY KEY, id_config bigint NOT NULL, idruta integer NOT NULL,
                                        nro_segmento integer NOT NULL, UNIQUE (id_config, nro_segmento));
CREATE TABLE {ESQUEMA}.estacionalidades_anio (id_estacionalidad_anio bigint PRIMARY KEY, proceso text,
                                              id_estacionalidad bigint, ano bigint, fecha_inicio date, fecha_fin date);
CREATE TABLE {ESQUEMA}.timbradas_segmentos (
    id_timbrada_segmento BIGSERIAL PRIMARY KEY, id_segmento BIGINT NOT NULL, id_viaje BIGINT NOT NULL,
    fecha DATE NOT NULL, hora_inicio TIME NOT NULL, hora_fin TIME NOT NULL, subidas INTEGER NOT NULL DEFAULT 0,
    bajadas INTEGER NOT NULL DEFAULT 0, pasajeros INTEGER NOT NULL DEFAULT 0, ultimaactualizacion TIMESTAMP,
    UNIQUE (id_segmento, id_viaje, hora_inicio));
-- los consolidados que el ciclo lee una vez por ejecución (app/servicios/consolidados.py), vacíos como en la réplica
-- las dos de segmentos (hallazgo H4): el ciclo de estas pruebas los lee y dice que no hay filas que contrastar
CREATE TABLE {ESQUEMA}.timbradas_consolidado (
    id_timbrada_consolidado BIGSERIAL PRIMARY KEY, proceso TEXT, id_ruta BIGINT, id_dia_semana BIGINT,
    id_estacionalidad BIGINT, hora TIME, hora_inicio TIME, hora_fin TIME, subidas BIGINT, bajadas BIGINT,
    nro_viajes BIGINT, promedio_subidas DOUBLE PRECISION, promedio_bajadas DOUBLE PRECISION,
    ultima_actualizacion TIMESTAMP);
CREATE TABLE {ESQUEMA}.timbradas_segmentos_anio (
    id_timbrada_segmento_anio BIGSERIAL PRIMARY KEY, id_segmento BIGINT NOT NULL, proceso VARCHAR(50) NOT NULL,
    ano INT4 NOT NULL, id_ruta INT8 NOT NULL, id_dia_semana INT4 NOT NULL, id_estacionalidad_anio INT8 NOT NULL,
    hora TIME NOT NULL, hora_inicio TIME NOT NULL, hora_fin TIME NOT NULL, subidas INT4 NOT NULL, bajadas INT4 NOT NULL,
    pasajeros INT4 NOT NULL, nro_viajes INT4 NOT NULL, promedio_subidas NUMERIC(10, 2),
    promedio_bajadas NUMERIC(10, 2), promedio_pasajeros NUMERIC(10, 2), ultima_actualizacion TIMESTAMP);
CREATE TABLE {ESQUEMA}.timbradas_segmentos_consolidado (
    id_timbrada_segmentos_consolidado BIGSERIAL PRIMARY KEY, id_segmento BIGINT NOT NULL, proceso VARCHAR(50) NOT NULL,
    id_ruta INT8 NOT NULL, id_dia_semana INT4 NOT NULL, id_estacionalidad INT8 NOT NULL, hora TIME NOT NULL,
    hora_inicio TIME NOT NULL, hora_fin TIME NOT NULL, subidas INT4 NOT NULL, bajadas INT4 NOT NULL,
    pasajeros INT4 NOT NULL, nro_viajes INT4 NOT NULL, promedio_subidas NUMERIC(10, 2),
    promedio_bajadas NUMERIC(10, 2), promedio_pasajeros NUMERIC(10, 2), ultima_actualizacion TIMESTAMP);
"""
RUTAS = [(2, "SILENCIO", "sobusa"), (16, "CRA 54", "sobusa"), (99, "OTRA", "otro")]
# ruta 2 con dos configuraciones: los segmentos 1 y 4 (y 2 y 5) comparten ruta y nro_segmento
SEGMENTOS = [(1, 1, 2, 1), (2, 1, 2, 2), (3, 1, 2, 3), (4, 2, 2, 1), (5, 2, 2, 2),
             (11, 3, 16, 1), (12, 3, 16, 2), (13, 3, 16, 3), (21, 4, 99, 1), (22, 4, 99, 2)]
ESTACIONALIDADES = [
    (1, "sobusa", 25, 2024, date(2024, 1, 1), date(2024, 12, 31)),
    (2, "sobusa", 7, 2024, date(2024, 3, 4), date(2024, 3, 10)),
    (3, "sobusa", 8, 2024, date(2024, 3, 8), date(2024, 3, 12)),      # más corta: gana del 8 al 10
    (4, "sobusa", 9, 2024, date(2024, 3, 15), date(2024, 3, 16)),
    (5, "sobusa", 10, 2024, date(2024, 3, 15), date(2024, 3, 16)),    # empate de duración e inicio: gana la de id mayor
]
FECHAS = [date(2023, 12, 30), date(2023, 12, 31)] + [date(2024, 3, 1) + timedelta(days=i) for i in range(18)]
MARCA_BASE = datetime(2024, 4, 1, 8, 0)
CASOS = [
    ({}, None, 50, 0), ({"idruta": 2}, None, 50, 0), ({"idruta": 99}, None, 50, 0), ({"id_segmento": 12}, None, 50, 0),
    ({"id_estacionalidad": 8}, None, 50, 0), ({"id_dia_semana": 6}, "-max_pasajeros", 50, 0),
    ({"hora": 7}, "subidas", 50, 0), ({"idruta": 2, "hora": 8}, "-prom_subidas", 50, 0),
    ({"desde": date(2024, 3, 8), "hasta": date(2024, 3, 10)}, None, 50, 0),
    ({"desde": date(2024, 3, 5)}, "-nro_viajes", 20, 5), ({"hasta": date(2024, 3, 2)}, None, 50, 0),
    ({"desde": date(2023, 1, 1), "hasta": date(2025, 1, 1)}, None, 50, 0),
    ({"desde": date(2024, 3, 15), "hasta": date(2024, 3, 16), "idruta": 16}, "-max_bajadas", 50, 0),
    ({}, "prom_pasajeros", 7, 13), ({"idruta": 2}, "nro_segmento", 10, 30),
]


def _viajes(rng: random.Random, fecha: date, ruta: int, segmentos: list[int]) -> list[tuple]:
    """Timbradas de 3 viajes de una ruta en un día: un bloque de 15 min por segmento y, a veces, un segundo bloque en
    el mismo segmento (errata E2), que puede caer en la misma hora o en la siguiente."""
    filas = []
    for k in range(3):
        viaje = int(f"{fecha:%Y%m%d}{ruta:03d}{k}")
        inicio = datetime.combine(fecha, time(rng.randint(5, 20), rng.choice((0, 15, 30, 45))))
        for j, seg in enumerate(segmentos):
            bloques = [inicio + timedelta(minutes=15 * j)]
            if rng.random() < 0.3:
                bloques.append(bloques[0] + timedelta(minutes=15))
            for b in bloques:
                if b.date() != fecha:
                    continue
                fin = (b + timedelta(minutes=15)).time() if b.time() < time(23, 45) else time(23, 59, 59)
                filas.append((seg, viaje, fecha, b.time(), fin, rng.randint(0, 8), rng.randint(0, 8),
                              rng.randint(-30, 120), _marca(fecha)))
    return filas


def _marca(fecha: date) -> datetime:
    """ultimaactualizacion sembrada: una hora distinta por fecha (la ventana de solape de 15 min toca una sola)."""
    return MARCA_BASE + timedelta(hours=FECHAS.index(fecha))


def _sembrar(c) -> None:
    rng = random.Random(2026)
    c.execute(text(f"INSERT INTO {ESQUEMA}.rutas VALUES (:i, :n, :p, false, 1)"),
              [{"i": i, "n": n, "p": p} for i, n, p in RUTAS])
    c.execute(text(f"INSERT INTO {ESQUEMA}.rutas_segmentos VALUES (:i, :c, :r, :n)"),
              [{"i": i, "c": cf, "r": r, "n": n} for i, cf, r, n in SEGMENTOS])
    c.execute(text(f"INSERT INTO {ESQUEMA}.estacionalidades_anio VALUES (:i, :p, :e, :a, :d, :h)"),
              [{"i": i, "p": p, "e": e, "a": a, "d": d, "h": h} for i, p, e, a, d, h in ESTACIONALIDADES])
    filas = []
    for fecha in FECHAS:
        for ruta, _n, _p in RUTAS:
            filas += _viajes(rng, fecha, ruta, [s[0] for s in SEGMENTOS if s[2] == ruta])
    c.execute(text(f"INSERT INTO {ESQUEMA}.timbradas_segmentos (id_segmento, id_viaje, fecha, hora_inicio, hora_fin, "
                   "subidas, bajadas, pasajeros, ultimaactualizacion) "
                   "VALUES (:s, :v, :f, :hi, :hf, :su, :ba, :pa, :u)"),
              [dict(zip(("s", "v", "f", "hi", "hf", "su", "ba", "pa", "u"), f, strict=True)) for f in filas])


@pytest.fixture(scope="module")
def motor_fuente(migrada):
    """Las tablas de Extreme en un esquema aparte de la base LOCAL de pruebas (se borra al terminar)."""
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


def _limpiar() -> None:
    from app.db import sesion_contexto

    with sesion_contexto() as s:
        for tabla in ("segmento_estadistica_refresco", "segmento_estadistica", "segmento_estadistica_dia"):
            s.execute(text(f"DELETE FROM {E}.{tabla}"))
        s.execute(text(f"DELETE FROM {E}.execution_log WHERE tipo = 'segmentos'"))


@pytest.fixture
def con_fuente(motor_fuente, monkeypatch):
    """La capa de segmentos lee la fuente sintética, como con FUENTE_DATABASE_URL configurada; sin agregación ni
    trabajos «segmentos» antes y después (no interfiere con las demás pruebas de la cola)."""
    from app.servicios import segmentos

    original = segmentos.fuente
    monkeypatch.setattr(segmentos, "fuente", lambda motor=None: original(motor or motor_fuente))
    monkeypatch.setattr(segmentos, "fuente_configurada", lambda: True)
    _limpiar()
    yield motor_fuente
    _limpiar()


@pytest.fixture
def sin_fuente(migrada, monkeypatch):
    from app.servicios import segmentos

    monkeypatch.setattr(segmentos, "fuente_configurada", lambda: False)
    monkeypatch.setattr(segmentos.obtener_ajustes(), "fuente_database_url", "")
    _limpiar()
    yield
    _limpiar()


def _refrescar(modo: str = "completo") -> dict:
    from app.db import sesion_contexto
    from app.servicios import segmentos, segmentos_refresco

    with sesion_contexto() as s:
        return segmentos_refresco.refrescar(s, segmentos.fuente(), None, {"modo": modo})


def _iguales(motor_fuente, casos=CASOS) -> list[str]:
    """Casos en que la agregación materializada difiere de la directa (JSON de los items o total)."""
    from app.db import sesion_contexto
    from app.servicios import segmentos

    distintos = []
    for filtros, orden, limite, desplazamiento in casos:
        directa = segmentos.estadisticas_directas(motor=motor_fuente, orden=orden, limite=limite,
                                                  desplazamiento=desplazamiento, **filtros)
        with sesion_contexto() as s:
            servida = segmentos.consultar(s, orden=orden, limite=limite, desplazamiento=desplazamiento, **filtros)
        if (json.dumps(servida["items"], sort_keys=True) != json.dumps(directa["items"], sort_keys=True)
                or servida["total"] != directa["total"]):
            distintos.append(f"{filtros} {orden} {limite}/{desplazamiento}: {servida['total']} vs {directa['total']}")
    return distintos


# ---------------------------------------------------------------- equivalencia exacta
def test_materializada_identica_a_la_directa_en_todos_los_casos_borde(con_fuente):
    resumen = _refrescar("completo")
    assert resumen["modo"] == "completo" and resumen["fechas_releidas"] == (FECHAS[-1] - FECHAS[0]).days + 1
    assert resumen["fecha_min"] == FECHAS[0] and resumen["fecha_max"] == FECHAS[-1] and resumen["filas"] > 100
    assert not _iguales(con_fuente)
    from app.db import sesion_contexto
    from app.servicios import segmentos

    with sesion_contexto() as s:   # casos borde que la muestra debe contener para que la prueba diga algo
        todo = segmentos.consultar(s, limite=500, desplazamiento=0)["items"]
        todo += segmentos.consultar(s, limite=500, desplazamiento=500)["items"]
    assert {x["id_estacionalidad"] for x in todo} >= {None, 25, 7, 8, 10} and 9 not in {x["id_estacionalidad"]
                                                                                       for x in todo}
    assert min(x["min_pasajeros"] for x in todo) < 0 and any(x["nro_viajes"] > x["dias"] for x in todo)


def test_pagina_despues_del_final_trae_el_total_real(con_fuente):
    from app.db import sesion_contexto
    from app.servicios import segmentos

    _refrescar("completo")
    with sesion_contexto() as s:
        total = segmentos.consultar(s, limite=1, desplazamiento=0)["total"]
        vacia = segmentos.consultar(s, limite=10, desplazamiento=total + 5)
        rango = segmentos.consultar(s, desde=date(2024, 3, 2), hasta=date(2024, 3, 3), limite=1, desplazamiento=0)
        rango_vacia = segmentos.consultar(s, desde=date(2024, 3, 2), hasta=date(2024, 3, 3), limite=5,
                                          desplazamiento=10_000)
    assert vacia["items"] == [] and vacia["total"] == total > 0
    assert rango_vacia["items"] == [] and rango_vacia["total"] == rango["total"] > 0


# ---------------------------------------------------------------- incremental y catálogos
def test_incremental_relee_solo_las_fechas_cambiadas(con_fuente, monkeypatch):
    from app.servicios import segmentos

    monkeypatch.setattr(segmentos.obtener_ajustes(), "fuente_solape_min", 0)   # el solape se prueba aparte
    _refrescar("completo")
    marca = MARCA_BASE + timedelta(days=2)
    with con_fuente.begin() as c:
        c.execute(text(f"UPDATE {ESQUEMA}.timbradas_segmentos SET subidas = subidas + 5, ultimaactualizacion = :m "
                       "WHERE fecha = :f AND id_segmento = 11"), {"m": marca, "f": date(2024, 3, 6)})
        c.execute(text(f"INSERT INTO {ESQUEMA}.timbradas_segmentos (id_segmento, id_viaje, fecha, hora_inicio, "
                       "hora_fin, subidas, bajadas, pasajeros, ultimaactualizacion) VALUES "
                       "(12, 77001, :f, '07:00', '07:15', 9, 1, 40, :m), "
                       "(13, 77001, :f, '07:15', '07:30', 0, 9, 31, :m)"),
                  {"f": date(2024, 3, 19), "m": marca})
    try:
        resumen = _refrescar("auto")
        assert resumen["modo"] == "incremental" and resumen["tramos"] == 2 and resumen["fechas_releidas"] == 2
        assert resumen["marca_fuente"].replace(tzinfo=None) == marca and resumen["fecha_max"] == date(2024, 3, 19)
        assert not _iguales(con_fuente)
        assert _refrescar("auto")["modo"] == "sin_cambios"
    finally:
        with con_fuente.begin() as c:
            c.execute(text(f"DELETE FROM {ESQUEMA}.timbradas_segmentos WHERE id_viaje = 77001"))
            c.execute(text(f"UPDATE {ESQUEMA}.timbradas_segmentos SET subidas = subidas - 5, ultimaactualizacion = "
                           ":m WHERE fecha = :f AND id_segmento = 11"),
                      {"m": _marca(date(2024, 3, 6)), "f": date(2024, 3, 6)})


def _versiones_fisicas(s) -> dict[str, set[str]]:
    """ctid y xmin de cada fila visible de las dos tablas de la agregación: una fila insertada, actualizada o borrada
    en la transacción cambia el conjunto (un UPDATE deja otra versión física)."""
    return {t: set(s.execute(text(f"SELECT ctid::text || ':' || xmin::text FROM {E}.{t}")).scalars())
            for t in ("segmento_estadistica", "segmento_estadistica_dia")}


def _refrescar_contando(modo: str = "auto") -> tuple[dict, dict[str, int]]:
    """El refresco y cuántas versiones de fila escribió o quitó en cada tabla de la agregación (diferencia simétrica de
    las versiones físicas antes y después, en la misma transacción)."""
    from app.db import sesion_contexto
    from app.servicios import segmentos, segmentos_refresco

    with sesion_contexto() as s:
        antes = _versiones_fisicas(s)
        resumen = segmentos_refresco.refrescar(s, segmentos.fuente(), None, {"modo": modo})
        despues = _versiones_fisicas(s)
        return resumen, {t: len(antes[t] ^ despues[t]) for t in antes}


def test_incremental_sin_cambios_en_la_ventana_de_solape_no_reescribe_nada(con_fuente):
    """(e) La marca de Extreme es la hora de INICIO de su transacción (H7, H10): el incremental mira la ventana de
    FUENTE_SOLAPE_MIN antes de la marca, que con 15 min nunca queda vacía mientras haya filas con la marca máxima. Si
    sus huellas son las que dejó el refresco anterior, termina «sin_cambios»: no relee ninguna fecha ni escribe una
    sola fila de la agregación. Sin huellas comparables (un refresco anterior a la migración 0012) relee la ventana
    entera, como antes, y deja las huellas para el siguiente."""
    from app.db import sesion_contexto

    _refrescar("completo")
    resumen, escrituras = _refrescar_contando("incremental")
    assert resumen["modo"] == "sin_cambios" and resumen["fechas_releidas"] == 0 and resumen["filas_leidas"] == 0
    assert resumen["ventana"] == {"fechas_en_ventana": 1, "comparada_con_el_refresco_anterior": True,
                                  "fechas_cambiadas": 0}
    assert sum(escrituras.values()) == 0, escrituras
    with sesion_contexto() as s:   # como un refresco anterior a la 0012: sin huellas de la ventana
        s.execute(text(f"UPDATE {E}.segmento_estadistica_refresco SET huellas_solape = NULL"))
    resumen, escrituras = _refrescar_contando("incremental")
    assert resumen["modo"] == "incremental" and resumen["fechas_releidas"] == 1 and resumen["tramos"] == 1
    assert 0 < escrituras["segmento_estadistica"] and resumen["filas_respuesta_reescritas"] < resumen["filas"]
    assert not _iguales(con_fuente, CASOS[:2])
    assert _refrescar_contando("auto")[0]["modo"] == "sin_cambios"


def test_una_fila_tardia_en_el_solape_relee_solo_su_fecha_y_reagrega_solo_sus_claves(con_fuente):
    """Una transacción larga de Extreme confirma DESPUÉS del refresco filas con una marca anterior a la máxima pero
    dentro del solape: cambia la huella de su fecha y el refresco siguiente relee solo esa fecha; segmento_estadistica
    solo reescribe las claves de esa fecha y queda idéntica a la agregación directa."""
    _refrescar("completo")
    marca = _marca(FECHAS[-1]) - timedelta(minutes=5)
    fecha = date(2024, 3, 9)
    with con_fuente.begin() as c:
        c.execute(text(f"INSERT INTO {ESQUEMA}.timbradas_segmentos (id_segmento, id_viaje, fecha, hora_inicio, "
                       "hora_fin, subidas, bajadas, pasajeros, ultimaactualizacion) VALUES "
                       "(1, 88001, :f, '09:00', '09:15', 4, 0, 4, :m), (2, 88001, :f, '09:15', '09:30', 2, 3, 3, :m)"),
                  {"f": fecha, "m": marca})
    try:
        resumen, escrituras = _refrescar_contando("auto")
        assert resumen["modo"] == "incremental" and resumen["tramos"] == 1 and resumen["fechas_releidas"] == 1
        assert resumen["ventana"]["fechas_cambiadas"] == 1 and resumen["ventana"]["fechas_en_ventana"] == 2
        assert resumen["filas_respuesta_reescritas"] < resumen["filas"]          # solo las claves de esa fecha
        assert escrituras["segmento_estadistica"] < 2 * resumen["filas"]
        assert not _iguales(con_fuente)
        assert _refrescar_contando("auto")[0]["modo"] == "sin_cambios"
    finally:
        with con_fuente.begin() as c:
            c.execute(text(f"DELETE FROM {ESQUEMA}.timbradas_segmentos WHERE id_viaje = 88001"))


def _diferencia_con_la_reconstruccion(s) -> int:
    """Filas en que segmento_estadistica difiere de rehacerla entera desde el grano diario (EXCEPT en los dos
    sentidos); 0 = la agregación parcial es exactamente la completa."""
    from app.servicios import segmentos

    completa = (f"SELECT {segmentos.LLAVES}, {segmentos.MEDIDAS_DESDE_DIA} FROM {E}.segmento_estadistica_dia "
                f"GROUP BY {segmentos.LLAVES}")
    servida = f"SELECT {segmentos.COLUMNAS} FROM {E}.segmento_estadistica"
    return int(s.execute(text(f"SELECT (SELECT count(*) FROM (({completa}) EXCEPT ({servida})) a) + "
                              f"(SELECT count(*) FROM (({servida}) EXCEPT ({completa})) b)")).scalar())


def test_refrescos_parciales_seguidos_dan_lo_mismo_que_rehacer_todo(con_fuente, monkeypatch):
    """Equivalencia del refresco parcial: tras una serie al azar de cambios en la fuente (filas nuevas, cambiadas y
    borradas en fechas sueltas, con marcas nuevas o tardías dentro del solape) y un refresco incremental después de
    cada una, segmento_estadistica es exactamente la que daría rehacerla entera y la agregación directa."""
    from app.db import sesion_contexto
    from app.servicios import segmentos

    monkeypatch.setattr(segmentos.obtener_ajustes(), "segmentos_dias_por_lote", 3)
    rng = random.Random(14)
    _refrescar("completo")
    maxima = _marca(FECHAS[-1])
    try:
        for paso in range(6):
            marca = maxima + timedelta(minutes=rng.choice((-6, 20, 45)))   # a veces tardía (dentro del solape)
            maxima = max(maxima, marca)
            fechas = rng.sample(FECHAS, 2)
            with con_fuente.begin() as c:
                c.execute(text(f"UPDATE {ESQUEMA}.timbradas_segmentos SET subidas = subidas + 1, "
                               "ultimaactualizacion = :m WHERE fecha = :f AND id_segmento IN (1, 11)"),
                          {"m": marca, "f": fechas[0]})
                c.execute(text(f"DELETE FROM {ESQUEMA}.timbradas_segmentos WHERE id_timbrada_segmento = (SELECT "
                               f"min(id_timbrada_segmento) FROM {ESQUEMA}.timbradas_segmentos WHERE fecha = :f)"),
                          {"f": fechas[1]})
                c.execute(text(f"INSERT INTO {ESQUEMA}.timbradas_segmentos (id_segmento, id_viaje, fecha, hora_inicio, "
                               "hora_fin, subidas, bajadas, pasajeros, ultimaactualizacion) VALUES "
                               "(13, :v, :f, '10:00', '10:15', 3, 1, 9, :m)"),
                          {"v": 99000 + paso, "f": fechas[1], "m": marca})
            resumen = _refrescar("auto")
            assert resumen["modo"] in ("incremental", "sin_cambios"), resumen
            with sesion_contexto() as s:
                assert _diferencia_con_la_reconstruccion(s) == 0, (paso, resumen)
        assert not _iguales(con_fuente)
    finally:
        with con_fuente.begin() as c:   # la fuente sintética se vuelve a sembrar igual que al principio
            c.execute(text(f"TRUNCATE {ESQUEMA}.timbradas_segmentos, {ESQUEMA}.rutas, {ESQUEMA}.rutas_segmentos, "
                           f"{ESQUEMA}.estacionalidades_anio"))
            _sembrar(c)


def test_cambio_de_estacionalidades_fuerza_refresco_completo(con_fuente):
    _refrescar("completo")
    with con_fuente.begin() as c:
        c.execute(text(f"INSERT INTO {ESQUEMA}.estacionalidades_anio VALUES (6, 'sobusa', 11, 2024, :d, :d)"),
                  {"d": date(2024, 3, 3)})
    try:
        resumen = _refrescar("auto")
        assert resumen["modo"] == "completo"     # cambió la huella: la asignación de estacionalidad ya no valía
        assert not _iguales(con_fuente, [({"id_estacionalidad": 11}, None, 50, 0), ({}, None, 50, 0)])
    finally:
        with con_fuente.begin() as c:
            c.execute(text(f"DELETE FROM {ESQUEMA}.estacionalidades_anio WHERE id_estacionalidad_anio = 6"))


def test_modo_rango_relee_solo_esas_fechas_acotadas_a_la_fuente(con_fuente):
    from app.db import sesion_contexto
    from app.servicios import segmentos, segmentos_refresco

    _refrescar("completo")
    with sesion_contexto() as s:
        resumen = segmentos_refresco.refrescar(s, segmentos.fuente(), None,
                                               {"modo": "rango", "desde": "2024-03-17", "hasta": "2030-01-01"})
    assert resumen["modo"] == "rango" and resumen["fechas_releidas"] == 2 and not _iguales(con_fuente, CASOS[:3])


# ---------------------------------------------------------------- el trabajo de la cola
def _detalle(cliente, execution_id) -> dict:
    return cliente.get(f"/api/v1/frequency/executions/{execution_id}").json()


def test_post_refrescar_es_un_trabajo_con_progreso_y_cerca(cliente, con_fuente):
    """POST /segmentos/estadisticas/refrescar responde 202 con el execution_id; el trabajo corre en la cola (aquí, sin
    hilos, en la misma petición con el mismo protocolo de reserva), termina «ok» al 100 % y deja la agregación."""
    r = cliente.post("/api/v1/segmentos/estadisticas/refrescar", json={"modo": "completo"})
    assert r.status_code == 202, r.text
    cuerpo = r.json()
    assert cuerpo["tipo"] == "segmentos" and cuerpo["nueva"] is True and cuerpo["modo"] == "completo"
    assert cuerpo["consultar_estado"] == f"/api/v1/frequency/executions/{cuerpo['execution_id']}"
    detalle = _detalle(cliente, cuerpo["execution_id"])
    assert detalle["estado"] == "ok" and float(detalle["progreso"]) == 100 and detalle["etapa"] == "terminada"
    assert detalle["metricas"]["modo"] == "completo" and detalle["metricas"]["filas"] > 100
    assert detalle["metricas"]["tramos"] >= 1 and detalle["filas_leidas"] > 0
    from app.db import sesion_contexto

    with sesion_contexto() as s:
        intentos = s.execute(text(f"SELECT resultado FROM {E}.execution_attempt WHERE execution_id = :i"),
                             {"i": cuerpo["execution_id"]}).scalars().all()
    assert intentos == ["ok"]
    est = cliente.get("/api/v1/segmentos/estadisticas", params={"idruta": 16, "limite": 5}).json()
    assert est["disponible"] is True and est["fuente"] == "agregacion_materializada"
    assert est["actualizado_en"].endswith("-05:00") and est["materializacion"]["execution_id"] == cuerpo["execution_id"]
    assert not _iguales(con_fuente, [({"idruta": 16}, None, 5, 0)])


def test_la_metrica_de_etapas_queda_acotada_y_el_detalle_de_los_tramos_en_el_trabajo(cliente, con_fuente,
                                                                                     monkeypatch, caplog):
    """RNF-006: dos refrescos con fechas distintas (y tramos de un día) no crean series nuevas en
    api_ejecucion_etapa_segundos: la etiqueta es «lectura_fuente»; el tramo y las fechas quedan en
    metricas.tramos_leidos del trabajo y en el log."""
    import logging

    from prometheus_client import REGISTRY

    from app.servicios import ejecucion, segmentos

    def etiquetas() -> set[str]:
        return {m.labels["etapa"] for f in REGISTRY.collect() if f.name == "api_ejecucion_etapa_segundos"
                for m in f.samples if "etapa" in m.labels}

    monkeypatch.setattr(segmentos.obtener_ajustes(), "segmentos_dias_por_lote", 1)    # un tramo por fecha
    caplog.set_level(logging.INFO, logger="api_frecuencias.segmentos")
    _refrescar("completo")
    detalles = []
    for desde, hasta in (("2024-03-02", "2024-03-03"), ("2024-03-10", "2024-03-12")):
        r = cliente.post("/api/v1/segmentos/estadisticas/refrescar",
                         json={"modo": "rango", "desde": desde, "hasta": hasta})
        assert r.status_code == 202, r.text
        detalles.append(_detalle(cliente, r.json()["execution_id"]))
    assert all(d["estado"] == "ok" for d in detalles), [d["mensaje"] for d in detalles]
    tramos = [t for d in detalles for t in d["metricas"]["tramos_leidos"]]
    assert [(t["desde"], t["hasta"]) for t in tramos] == [
        ("2024-03-02", "2024-03-02"), ("2024-03-03", "2024-03-03"), ("2024-03-10", "2024-03-10"),
        ("2024-03-11", "2024-03-11"), ("2024-03-12", "2024-03-12")]
    assert [t["tramo"] for t in tramos] == ["1/2", "2/2", "1/3", "2/3", "3/3"] and all(t["filas"] > 0 for t in tramos)
    assert "tramo 3/3 (2024-03-12 a 2024-03-12)" in caplog.text
    vistas = etiquetas()
    assert "lectura_fuente" in vistas and vistas <= ejecucion.ETAPAS_METRICA | {ejecucion.ETAPA_OTRA}, vistas
    assert not any(c.isdigit() for e in vistas for c in e)


def test_post_refrescar_valida_y_no_duplica(cliente, con_fuente, monkeypatch):
    from app.servicios import ejecucion

    monkeypatch.setattr(ejecucion, "ejecutar", lambda *a, **k: None)      # queda en cola sin procesarse
    for cuerpo in ({"modo": "rango"}, {"modo": "otro"}, {"modo": "auto", "desde": "2024-03-01"},
                   {"modo": "rango", "desde": "2024-03-05", "hasta": "2024-03-01"}):
        r = cliente.post("/api/v1/segmentos/estadisticas/refrescar", json=cuerpo)
        assert r.status_code == 422 and r.json()["error"]["codigo"] == "validacion", (cuerpo, r.text)
    primero = cliente.post("/api/v1/segmentos/estadisticas/refrescar", json={"modo": "rango", "desde": "2024-03-01",
                                                                             "hasta": "2024-03-02"}).json()
    segundo = cliente.post("/api/v1/segmentos/estadisticas/refrescar", json={"modo": "rango", "desde": "2024-03-01",
                                                                             "hasta": "2024-03-02"}).json()
    otro = cliente.post("/api/v1/segmentos/estadisticas/refrescar").json()
    assert primero["nueva"] and not segundo["nueva"] and segundo["execution_id"] == primero["execution_id"]
    assert otro["nueva"] and otro["modo"] == "auto" and otro["execution_id"] != primero["execution_id"]
    assert primero["desde"] == "2024-03-01" and primero["hasta"] == "2024-03-02"


def test_peticiones_simultaneas_no_duplican_el_refresco(con_fuente):
    """Varias peticiones A LA VEZ que encuentran la agregación vacía dejan UN solo refresco en la cola: buscar y crear
    van bajo un candado de asesoría de transacción. Sin él, 10 peticiones simultáneas dejaban de 5 a 8 trabajos
    repetidos, y cada uno volvía a leer timbradas_segmentos en la base de Extreme."""
    import threading

    from app.db import nueva_sesion, sesion_contexto
    from app.servicios import segmentos_refresco

    n = 8
    barrera, nuevas, errores = threading.Barrier(n), [], []

    def pedir():
        s = nueva_sesion()
        try:
            barrera.wait(timeout=30)
            _e, nueva = segmentos_refresco.solicitar(s, {"modo": "auto", "origen": "consulta"},
                                                     cualquiera_en_curso=True)
            nuevas.append(nueva)
        except Exception as exc:  # noqa: BLE001 - se informa en la aserción
            errores.append(exc)
        finally:
            s.close()

    hilos = [threading.Thread(target=pedir) for _ in range(n)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join(timeout=60)
    with sesion_contexto() as s:
        trabajos = s.execute(text(f"SELECT count(*) FROM {E}.execution_log WHERE tipo = 'segmentos'")).scalar()
    assert not errores, errores
    assert sorted(nuevas) == [False] * (n - 1) + [True] and trabajos == 1


def test_reintento_tras_una_caida_de_la_fuente_sin_resultados_a_medias(con_fuente, monkeypatch):
    """RNF-004: si la fuente falla a mitad del refresco, el intento se revierte entero (la agregación anterior sigue
    sirviendo) y el trabajo se reintenta con espera hasta terminar «ok»."""
    from sqlalchemy.exc import OperationalError

    from app.db import sesion_contexto
    from app.servicios import cola, ejecucion, fuentes, segmentos

    _refrescar("completo")
    with sesion_contexto() as s:
        antes = segmentos.ultimo_refresco(s)
        e = ejecucion.crear_ejecucion(s, "segmentos", {"modo": "completo"}, "prueba-reintento")
    original = fuentes.FuentePostgresSoloLectura.consultar
    estado = {"llamadas": 0}

    def consultar_que_falla(self, sql, parametros=None):
        estado["llamadas"] += 1
        if estado["llamadas"] == 4:            # huella, rango, primer tramo, ... el cuarto se cae
            raise OperationalError("SELECT", {}, ConnectionError("la base operacional se cayó"))
        return original(self, sql, parametros)

    monkeypatch.setattr(fuentes.FuentePostgresSoloLectura, "consultar", consultar_que_falla)
    monkeypatch.setattr(segmentos.obtener_ajustes(), "segmentos_dias_por_lote", 5)
    r = cola.reclamar("replica-seg:5001:aaaaaa:t1", lease_s=10, execution_id=e.execution_id)
    assert cola.correr_reclamo(r, lease_s=10, max_reintentos=3, base_espera=0.2) == "reintento"
    with sesion_contexto() as s:
        assert segmentos.ultimo_refresco(s)["id"] == antes["id"]       # nada a medias: sigue la versión anterior
        s.execute(text(f"UPDATE {E}.execution_log SET disponible_desde = now() WHERE execution_id = :i"),
                  {"i": e.execution_id})
    r2 = cola.reclamar("replica-seg:5002:bbbbbb:t1", lease_s=10, execution_id=e.execution_id)
    assert r2.intentos == 2 and cola.correr_reclamo(r2, lease_s=10, max_reintentos=3) == "ok"
    with sesion_contexto() as s:
        intentos = s.execute(text(f"SELECT resultado FROM {E}.execution_attempt WHERE execution_id = :i "
                                  "ORDER BY intento"), {"i": e.execution_id}).scalars().all()
        assert intentos == ["reintento", "ok"] and segmentos.ultimo_refresco(s)["execution_id"] == e.execution_id
    assert not _iguales(con_fuente, CASOS[:2])


# ---------------------------------------------------------------- la consulta nunca bloquea
def test_consulta_sin_agregacion_encola_el_refresco_y_no_bloquea(cliente, con_fuente, monkeypatch):
    from app.servicios import ejecucion

    llamadas = []
    original = ejecucion.ejecutar
    monkeypatch.setattr(ejecucion, "ejecutar", lambda eid: llamadas.append(eid))   # queda en cola
    r = cliente.get("/api/v1/segmentos/estadisticas", params={"limite": 5})
    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["disponible"] is False and cuerpo["total"] == 0 and cuerpo["items"] == []
    assert cuerpo["actualizado_en"] is None and cuerpo["refresco"]["nueva"] is True
    assert "cola" in cuerpo["nota"] and llamadas == [uuid.UUID(cuerpo["refresco"]["execution_id"])]
    otra = cliente.get("/api/v1/segmentos/estadisticas", params={"idruta": 2}).json()
    assert otra["refresco"]["execution_id"] == cuerpo["refresco"]["execution_id"] and not otra["refresco"]["nueva"]
    exportacion = cliente.get("/api/v1/segmentos/estadisticas/export")
    assert exportacion.status_code == 503 and exportacion.json()["error"]["codigo"] == "agregacion_pendiente"
    assert exportacion.json()["error"]["detalle"]["execution_id"] == cuerpo["refresco"]["execution_id"]
    monkeypatch.setattr(ejecucion, "ejecutar", original)
    from app.servicios import cola

    assert cola.procesar(uuid.UUID(cuerpo["refresco"]["execution_id"])) == "ok"
    lista = cliente.get("/api/v1/segmentos/estadisticas", params={"limite": 5}).json()
    assert lista["disponible"] is True and lista["total"] > 0 and len(lista["items"]) == 5


def test_sin_base_operacional_lo_dice_sin_error(cliente, sin_fuente):
    r = cliente.get("/api/v1/segmentos/estadisticas")
    assert r.status_code == 200 and r.json()["disponible"] is False and "FUENTE_DATABASE_URL" in r.json()["nota"]
    assert "refresco" not in r.json()
    p = cliente.post("/api/v1/segmentos/estadisticas/refrescar", json={"modo": "auto"})
    assert p.status_code == 503 and p.json()["error"]["codigo"] == "fuente_no_configurada"
    csv = cliente.get("/api/v1/segmentos/estadisticas/export", params={"formato": "csv"})
    assert csv.status_code == 200
    columnas = pd.read_csv(io.BytesIO(csv.content), encoding="utf-8-sig").columns
    assert {"id_segmento", "prom_subidas", "primera_fecha"} <= set(columnas)


def test_exportacion_lee_la_agregacion(cliente, con_fuente):
    from app.servicios import segmentos

    _refrescar("completo")
    csv = cliente.get("/api/v1/segmentos/estadisticas/export", params={"idruta": 2, "formato": "csv"})
    assert csv.status_code == 200
    df = pd.read_csv(io.BytesIO(csv.content), encoding="utf-8-sig")
    directa = segmentos.estadisticas_directas_df(motor=con_fuente, idruta=2)
    assert len(df) == len(directa) and list(df.columns) == list(directa.columns)
    assert df["subidas"].sum() == pytest.approx(directa["subidas"].sum())
    xlsx = cliente.get("/api/v1/segmentos/estadisticas/export", params={"desde": "2024-03-08", "formato": "xlsx"})
    assert xlsx.status_code == 200 and xlsx.content[:2] == b"PK"


# ---------------------------------------------------------------- quién encola: planificador y ciclo
def test_planificador_encola_una_franja_por_cron_en_todo_el_cluster(con_fuente, monkeypatch):
    from app.servicios import planificador

    aj = planificador.obtener_ajustes()
    monkeypatch.setattr(aj, "fuente_database_url", "postgresql+psycopg://lector_ia@127.0.0.1:1/operacional")
    monkeypatch.setattr(aj, "plan_segmentos_cron", "45 5 * * *")
    ahora = datetime(2031, 5, 6, 5, 50, tzinfo=planificador.ZONA)
    primero = planificador.tarea_refresco_segmentos(ahora)
    assert primero is not None and planificador.tarea_refresco_segmentos(ahora + timedelta(seconds=20)) is None
    assert "refresco_segmentos" in {t[0] for t in planificador.trabajos_programados(aj)}
    from app.db import sesion_contexto
    from app.modelos_db import Ejecucion

    with sesion_contexto() as s:
        e = s.get(Ejecucion, primero)
        assert e.tipo == "segmentos" and e.parametros["modo"] == "auto" and e.programada_para is not None
    monkeypatch.setattr(aj, "fuente_database_url", "")
    assert planificador.tarea_refresco_segmentos(ahora + timedelta(days=1)) is None


def test_ciclo_con_datos_nuevos_encola_el_refresco_sin_duplicar(con_fuente):
    from types import SimpleNamespace

    from app.db import sesion_contexto
    from app.servicios import ejecucion

    ciclo = SimpleNamespace(filas_validas=51, execution_id=uuid.uuid4())
    ejecucion._encolar_refresco_segmentos(ciclo)
    ejecucion._encolar_refresco_segmentos(ciclo)                       # otro ciclo antes de que corra: no duplica
    ejecucion._encolar_refresco_segmentos(SimpleNamespace(filas_validas=0, execution_id=uuid.uuid4()))
    with sesion_contexto() as s:
        filas = s.execute(text(f"SELECT parametros FROM {E}.execution_log WHERE tipo = 'segmentos'")).scalars().all()
    assert len(filas) == 1 and filas[0]["origen"] == "ciclo" and filas[0]["ciclo"] == str(ciclo.execution_id)
