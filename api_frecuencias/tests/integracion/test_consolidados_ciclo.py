"""Consolidados de Extreme en el ciclo diario contra la base LOCAL de pruebas (§5.2 ALT-008, §6.1, §6.3, §7.3 paso 3,
§9.5, §11.2; migración 0013).

Las tablas de Extreme (timbradas_consolidado, timbradas_anio, timbradas_segmentos_anio,
timbradas_segmentos_consolidado y los catálogos rutas, "Procesos", estacionalidades, estacionalidades_anio,
novedades_viales, rutas_segmentos y dias_semana) se crean en un esquema aparte de la base de pruebas con datos
sintéticos y se leen con FuentePostgresSoloLectura (READ ONLY, statement_timeout, ROLLBACK), como la réplica. Nunca se
escribe en la réplica.

Se prueba: la lectura incremental con su marca por tabla (sin cambios, resellado sin cambios descartado por huella,
fila modificada), CONS-001, VAL-007, REL-004 y REL-006 sobre las filas leídas, el contraste con el histórico propio y
con la agregación materializada de segmentos (incidencias con llave, valor y bloqueante en data_quality_error), el
resultado explícito sin filas (H4), una tabla que falla sin detener el ciclo, el ciclo completo (sin partir y partido
por ruta, con la versión de umbrales fijada), la validación de las tolerancias en PUT /thresholds, las bajadas en el
histórico (COPY y upsert que no borra) con ALT-008 y la migración 0013 de subida y bajada.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
from sqlalchemy import create_engine, delete, select, text

from app.modelos_db import DemandaObservada, Ejecucion, ErrorCalidad, MarcaAguaTabla
from tests.integracion.conftest import restituir_umbrales

ZONA = ZoneInfo("America/Bogota")
E = "ai_frecuencias"
ESQUEMA = "fuente_consolidados_prueba"
MARCA = datetime(2026, 1, 10, 8, 0)
LUNES = [date(2025, 3, 3), date(2025, 3, 10), date(2025, 3, 17)]
MARTES = [date(2025, 3, 4), date(2025, 3, 11), date(2025, 3, 18)]

DDL = f"""
CREATE TABLE {ESQUEMA}.rutas (idruta bigint PRIMARY KEY, nombre text, codigo text, proceso text, idempresa bigint,
    frecuenciadespachos double precision, primerdespacho time, estado_ruta text, idrutageo bigint, tolerancia bigint,
    tolsalida bigint, maneja_zonas boolean, id_tipo_tarifa bigint, zona_tolerancia_inicio bigint,
    zona_tolerancia_fin bigint);
CREATE TABLE {ESQUEMA}."Procesos" (proceso text PRIMARY KEY, nombre text, estado text, toleranciatiempo bigint,
    id_estacionalidad bigint, ultima_estacionalidad date);
CREATE TABLE {ESQUEMA}.estacionalidades (id_estacionalidad bigint PRIMARY KEY, proceso text, estacionalidad text,
    nombre text, descripcion text);
CREATE TABLE {ESQUEMA}.estacionalidades_anio (id_estacionalidad_anio bigint PRIMARY KEY, proceso text,
    id_estacionalidad bigint, ano bigint, fecha_inicio date, fecha_fin date);
CREATE TABLE {ESQUEMA}.novedades_viales (id_novedad_vial bigint PRIMARY KEY, proceso text, novedad text, nombre text,
    descripcion text);
CREATE TABLE {ESQUEMA}.rutas_segmentos (id bigint PRIMARY KEY, id_config bigint, idruta integer, idrutageo bigint,
    nro_segmento integer, activo boolean, longitud_m double precision);
CREATE TABLE {ESQUEMA}.dias_semana (id_dia_semana bigint PRIMARY KEY, dia_semana text);
CREATE TABLE {ESQUEMA}.timbradas_anio (id_timbrada_anio bigint PRIMARY KEY, proceso text, ano bigint);
CREATE TABLE {ESQUEMA}.timbradas_consolidado (
    id_timbrada_consolidado BIGSERIAL PRIMARY KEY, proceso TEXT, id_ruta BIGINT, id_dia_semana BIGINT,
    id_estacionalidad BIGINT, hora TIME, hora_inicio TIME, hora_fin TIME, subidas BIGINT, bajadas BIGINT,
    nro_viajes BIGINT, promedio_subidas DOUBLE PRECISION, promedio_bajadas DOUBLE PRECISION,
    ultima_actualizacion TIMESTAMP,
    UNIQUE (proceso, id_ruta, id_dia_semana, id_estacionalidad, hora, hora_inicio, hora_fin));
CREATE TABLE {ESQUEMA}.timbradas_segmentos_anio (
    id_timbrada_segmento_anio BIGSERIAL PRIMARY KEY, id_segmento BIGINT, proceso VARCHAR(50), ano INT4, id_ruta INT8,
    id_dia_semana INT4, id_estacionalidad_anio INT8, hora TIME, hora_inicio TIME, hora_fin TIME, subidas INT4,
    bajadas INT4, pasajeros INT4, nro_viajes INT4, promedio_subidas NUMERIC(10, 2), promedio_bajadas NUMERIC(10, 2),
    promedio_pasajeros NUMERIC(10, 2), ultima_actualizacion TIMESTAMP);
CREATE TABLE {ESQUEMA}.timbradas_segmentos_consolidado (
    id_timbrada_segmentos_consolidado BIGSERIAL PRIMARY KEY, id_segmento BIGINT, proceso VARCHAR(50), id_ruta INT8,
    id_dia_semana INT4, id_estacionalidad INT8, hora TIME, hora_inicio TIME, hora_fin TIME, subidas INT4,
    bajadas INT4, pasajeros INT4, nro_viajes INT4, promedio_subidas NUMERIC(10, 2), promedio_bajadas NUMERIC(10, 2),
    promedio_pasajeros NUMERIC(10, 2), ultima_actualizacion TIMESTAMP);
"""


def _filas_consolidado() -> list[dict]:
    """Ruta 2: lunes corrientes iguales al histórico (100 viajes por día en 51 lunes, en dos bloques) y martes con
    bajadas +30 % (incidencia no bloqueante; uno de sus bloques trae además un promedio incoherente, CONS-001);
    ruta 16: lunes con bajadas +80 % (grosera) y martes sin histórico propio; un festivo (estacionalidad 3, solo lunes)
    con id_dia_semana = 3 (VAL-007)."""
    def fila(ruta, dia, est, ini, n, s, b, prom_s=None):
        hora = time(ini.hour)
        fin = (datetime.combine(date(2025, 1, 1), ini) + timedelta(minutes=15)).time()
        return {"proceso": "sobusa", "id_ruta": ruta, "id_dia_semana": dia, "id_estacionalidad": est, "hora": hora,
                "hora_inicio": ini, "hora_fin": fin, "subidas": s, "bajadas": b, "nro_viajes": n,
                "promedio_subidas": prom_s if prom_s is not None else round(s / n, 2),
                "promedio_bajadas": round(b / n, 2), "ultima_actualizacion": MARCA}

    return [fila(2, 1, 25, time(7), 2550, 204000, 198900), fila(2, 1, 25, time(7, 15), 2550, 204000, 198900),
            fila(2, 2, 25, time(7), 2600, 208000, 263640), fila(2, 2, 25, time(7, 15), 2600, 208000, 263640, 99.0),
            fila(16, 1, 25, time(7), 10200, 816000, 1432080), fila(16, 2, 25, time(7), 10400, 832000, 811200),
            fila(2, 3, 3, time(8), 100, 8000, 7800)]


def _sembrar(c) -> None:
    c.execute(text(f"INSERT INTO {ESQUEMA}.rutas (idruta, nombre, proceso) VALUES (2, 'SILENCIO', 'sobusa'), "
                   "(16, 'CRA 54', 'sobusa')"))
    c.execute(text(f"INSERT INTO {ESQUEMA}.\"Procesos\" (proceso, nombre, toleranciatiempo) VALUES "
                   "('sobusa', 'SOBUSA', 0)"))
    c.execute(text(f"INSERT INTO {ESQUEMA}.estacionalidades VALUES (25, 'sobusa', 'DIAS_CORRIENTES', 'x', 'x'), "
                   "(3, 'sobusa', 'FESTIVO_NACIONAL', 'x', 'x')"))
    c.execute(text(f"INSERT INTO {ESQUEMA}.estacionalidades_anio VALUES (1, 'sobusa', 25, 2025, '2025-01-01', "
                   "'2025-12-31'), (2, 'sobusa', 3, 2025, '2025-12-08', '2025-12-08')"))
    c.execute(text(f"INSERT INTO {ESQUEMA}.novedades_viales VALUES (1, 'sobusa', 'CIERRE', 'x', 'x')"))
    c.execute(text(f"INSERT INTO {ESQUEMA}.rutas_segmentos VALUES (11, 1, 16, 1, 1, true, 500), "
                   "(12, 1, 16, 1, 2, true, 500), (21, 2, 2, 2, 1, true, 500)"))
    c.execute(text(f"INSERT INTO {ESQUEMA}.dias_semana SELECT d, 'd' || d FROM generate_series(1, 7) d"))
    c.execute(text(f"INSERT INTO {ESQUEMA}.timbradas_anio VALUES (1, 'sobusa', 2025)"))
    c.execute(text(f"INSERT INTO {ESQUEMA}.timbradas_consolidado (proceso, id_ruta, id_dia_semana, id_estacionalidad, "
                   "hora, hora_inicio, hora_fin, subidas, bajadas, nro_viajes, promedio_subidas, promedio_bajadas, "
                   "ultima_actualizacion) VALUES (:proceso, :id_ruta, :id_dia_semana, :id_estacionalidad, :hora, "
                   ":hora_inicio, :hora_fin, :subidas, :bajadas, :nro_viajes, :promedio_subidas, :promedio_bajadas, "
                   ":ultima_actualizacion)"), _filas_consolidado())


@pytest.fixture(scope="module")
def motor_fuente(migrada):
    admin = create_engine(migrada)
    with admin.begin() as c:
        c.execute(text(f"DROP SCHEMA IF EXISTS {ESQUEMA} CASCADE"))
        c.execute(text(f"CREATE SCHEMA {ESQUEMA}"))
        c.execute(text(DDL))
        _sembrar(c)
    motor = create_engine(migrada, connect_args={"options": f"-c search_path={ESQUEMA}"})
    yield motor
    motor.dispose()
    with admin.begin() as c:
        c.execute(text(f"DROP SCHEMA IF EXISTS {ESQUEMA} CASCADE"))
    admin.dispose()


def _limpiar(s, ids) -> None:
    s.rollback()
    s.execute(delete(MarcaAguaTabla))
    if ids:
        todos = set(ids) | set(s.scalars(select(Ejecucion.execution_id).where(Ejecucion.padre_id.in_(ids))))
        s.execute(delete(DemandaObservada).where(DemandaObservada.execution_id.in_(todos)))
        s.execute(text(f"DELETE FROM {E}.demanda_observada WHERE ruta LIKE 'PRUEBA-CONS%'"))
        s.execute(delete(Ejecucion).where(Ejecucion.execution_id.in_(todos)))
    s.execute(text(f"DELETE FROM {E}.segmento_estadistica_dia WHERE id_segmento IN (11, 12, 21)"))
    s.commit()


@pytest.fixture
def entorno(motor_fuente, sesion, monkeypatch):
    """La capa analítica lee el esquema sintético (como con FUENTE_DATABASE_URL), proceso «sobusa»; sin marcas por
    tabla antes y después; deja la base como la encontró (ejecuciones, histórico propio y segmentos sembrados)."""
    from app.servicios import segmentos

    original = segmentos.fuente
    monkeypatch.setattr(segmentos, "fuente", lambda motor=None: original(motor or motor_fuente))
    monkeypatch.setattr(segmentos, "fuente_configurada", lambda: True)
    monkeypatch.setenv("FUENTE_PROCESO", "sobusa")
    ids: list[uuid.UUID] = []
    _limpiar(sesion, ids)
    yield ids
    _limpiar(sesion, ids)


def _ejecucion(s, ids) -> uuid.UUID:
    from app.servicios import ejecucion

    e = ejecucion.crear_ejecucion(s, "frecuencia", {"prueba": "consolidados"}, "consolidados")
    ids.append(e.execution_id)
    return e.execution_id


def _historico_propio(s, eid) -> None:
    """El histórico propio de las rutas 2 y 16 (con nombres de prueba, para no chocar con el histórico de otras
    pruebas; el contraste agrupa por idruta) en tres lunes y tres martes de 2025 con la estacionalidad 25: 100 y 200
    viajes por día, 80 subidas y 78 bajadas por viaje."""
    filas = []
    for ruta, idruta, dias, viajes in (("PRUEBA-CONS-SILENCIO", 2, LUNES + MARTES, 100),
                                       ("PRUEBA-CONS-CRA54", 16, LUNES, 200)):
        for dia in dias:
            for hora in (6, 7):
                n = viajes // 2
                filas.append(DemandaObservada(
                    ruta=ruta, fecha=dia, hora=hora, pasajeros=80.0 * n, salidas=n, bajadas_viajes=78.0 * n,
                    ultima_actualizacion=datetime(2025, 3, 20, tzinfo=ZONA), execution_id=eid, idruta=idruta,
                    idproceso="sobusa", id_dia_semana=dia.isoweekday(), id_estacionalidad=25))
    s.add_all(filas)
    s.commit()


def _en_ciclo(s, eid, umbrales=None) -> tuple[dict, list]:
    from app.servicios import consolidados

    fallos: list = []
    r = consolidados.en_ciclo(s, eid, umbrales or {}, fallos)
    s.commit()
    return r, fallos


def _errores(s, eid) -> list[ErrorCalidad]:
    s.expire_all()
    return list(s.scalars(select(ErrorCalidad).where(ErrorCalidad.execution_id == eid)).all())


# ---------------------------------------------------------------- timbradas_consolidado en el paso del ciclo
def test_consolidado_se_lee_valida_y_contrasta_y_deja_su_marca(entorno, sesion):
    s = sesion
    eid = _ejecucion(s, entorno)
    _historico_propio(s, eid)
    r, fallos = _en_ciclo(s, eid)
    assert fallos == []
    t = r["tablas"]["timbradas_consolidado"]
    assert t["resultado"] == "contrastado" and t["filas"] == 7 and t["lectura"]["leidas"] == 7
    assert t["marca_anterior"] is None and t["marca_nueva"].startswith("2026-01-10T08:00:00")
    # calidad de las filas leídas: el promedio incoherente (CONS-001) y el festivo de un lunes en miércoles (VAL-007)
    assert t["errores_por_codigo"]["CONS-001"] == 1 and t["errores_por_codigo"]["VAL-007"] == 1
    assert t["filas_validas"] == 5
    c = t["contraste"]
    assert c["grano"] == ["id_ruta", "id_dia_semana", "id_estacionalidad"] and c["periodo"][0].startswith("2025-01-01")
    assert (c["llaves"], c["comparadas"], c["sin_agregacion_propia"]) == (5, 3, 2)
    assert (c["diferencias"], c["groseras"], c["llaves_bloqueadas"]) == (2, 1, 1) and "H10" in c["nota"]
    # data_quality_error: cada incidencia con su lote, llave, valor y si bloquea
    errores = _errores(s, eid)
    contr = sorted((e.llave["id_ruta"], e.llave["id_dia_semana"], e.campo, e.bloqueante) for e in errores
                   if e.codigo == "CONTR-001")
    assert contr == [(2, 2, "promedio_bajadas", False), (16, 1, "promedio_bajadas", True)]
    grosera = next(e for e in errores if e.codigo == "CONTR-001" and e.bloqueante)
    assert grosera.lote == f"{eid.hex[:8]}:timbradas_consolidado" and grosera.valor == "140.4000"
    assert grosera.llave == {"id_ruta": 16, "id_dia_semana": 1, "id_estacionalidad": 25, "proceso": "sobusa"}
    assert grosera.dimension == "consistencia" and "80.0%" in grosera.detalle
    cons = next(e for e in errores if e.codigo == "CONS-001")
    assert cons.llave["id_ruta"] == 2 and cons.valor == "99" and cons.bloqueante is True
    # marca de agua de la tabla, en la transacción del ciclo
    marca = s.get(MarcaAguaTabla, ("sobusa", "timbradas_consolidado"))
    assert marca.execution_id == eid and marca.filas_leidas == 7 and marca.estado_fuente["version"] >= 3
    # las dos de segmentos no tienen filas: el resumen lo dice (H4) y su marca no se mueve
    for tabla in ("timbradas_segmentos_anio", "timbradas_segmentos_consolidado"):
        assert r["tablas"][tabla]["resultado"] == "sin_filas_fuente" and "H4" in r["tablas"][tabla]["detalle"]
        assert s.get(MarcaAguaTabla, ("sobusa", tabla)) is None


def test_relectura_sin_cambios_resellado_y_fila_modificada(entorno, sesion, motor_fuente):
    """§6.1 ultima_actualizacion: la segunda lectura no trae nada; el resellado del cierre nocturno (H7: misma fila,
    marca nueva) se descarta por huella pero mueve la marca; una fila modificada se entrega sola y solo se contrasta su
    ruta."""
    s = sesion
    eid = _ejecucion(s, entorno)
    _historico_propio(s, eid)
    _en_ciclo(s, eid)
    segunda = _ejecucion(s, entorno)
    r, _ = _en_ciclo(s, segunda)
    t = r["tablas"]["timbradas_consolidado"]
    assert t["resultado"] == "sin_cambios" and t["filas"] == 0 and _errores(s, segunda) == []
    with motor_fuente.begin() as c:     # el esquema sintético de esta prueba, nunca la réplica
        c.execute(text("UPDATE timbradas_consolidado SET ultima_actualizacion = ultima_actualizacion + "
                       "interval '1 day'"))
    tercera = _ejecucion(s, entorno)
    r, _ = _en_ciclo(s, tercera)
    t = r["tablas"]["timbradas_consolidado"]
    assert t["resultado"] == "sin_cambios" and t["lectura"]["repetidas_solape"] == 7
    assert s.get(MarcaAguaTabla, ("sobusa", "timbradas_consolidado")).marca_agua.astimezone(ZONA).day == 11
    try:
        with motor_fuente.begin() as c:
            c.execute(text("UPDATE timbradas_consolidado SET bajadas = 795600, promedio_bajadas = 78, "
                           "ultima_actualizacion = ultima_actualizacion + interval '1 hour' WHERE id_ruta = 16 "
                           "AND id_dia_semana = 1"))
        cuarta = _ejecucion(s, entorno)
        r, _ = _en_ciclo(s, cuarta)
        t = r["tablas"]["timbradas_consolidado"]
        assert t["resultado"] == "contrastado" and t["filas"] == 1 and t["lectura"]["modificadas"] == 1
        assert t["contraste"]["ids"] == 1 and t["contraste"]["diferencias"] == 0      # la ruta 16 ya cuadra
    finally:
        with motor_fuente.begin() as c:
            c.execute(text("TRUNCATE timbradas_consolidado"))
            _restaurar_consolidado(c)


def test_la_lectura_solo_lee_huellea_y_marca_las_filas_del_proceso(entorno, sesion, motor_fuente):
    """En la base de Extreme hay filas de otros operadores (H4). La lectura filtra el proceso en el SQL: no las lee,
    no entran en las huellas que guarda marca_agua_tabla.estado_fuente y su marca más reciente no mueve la del proceso;
    el resultado para Sobusa es el mismo que sin ellas. Con la tabla sin cambios, el ciclo no cuenta filas."""
    s = sesion
    ajenas = [dict(f, proceso="cootransoriente", ultima_actualizacion=MARCA + timedelta(days=30))
              for f in _filas_consolidado()]
    with motor_fuente.begin() as c:     # el esquema sintético de esta prueba, nunca la réplica
        c.execute(text(f"INSERT INTO {ESQUEMA}.timbradas_consolidado (proceso, id_ruta, id_dia_semana, "
                       "id_estacionalidad, hora, hora_inicio, hora_fin, subidas, bajadas, nro_viajes, "
                       "promedio_subidas, promedio_bajadas, ultima_actualizacion) VALUES (:proceso, :id_ruta, "
                       ":id_dia_semana, :id_estacionalidad, :hora, :hora_inicio, :hora_fin, :subidas, :bajadas, "
                       ":nro_viajes, :promedio_subidas, :promedio_bajadas, :ultima_actualizacion)"), ajenas)
    try:
        eid = _ejecucion(s, entorno)
        _historico_propio(s, eid)
        r, fallos = _en_ciclo(s, eid)
        t = r["tablas"]["timbradas_consolidado"]
        assert fallos == [] and t["resultado"] == "contrastado"
        assert t["lectura"]["leidas"] == 7 and t["filas"] == 7            # solo las de Sobusa, como sin las ajenas
        assert (t["contraste"]["llaves"], t["contraste"]["diferencias"]) == (5, 2)
        marca = s.get(MarcaAguaTabla, ("sobusa", "timbradas_consolidado"))
        assert marca.filas_leidas == 7 and marca.marca_agua == MARCA.replace(tzinfo=ZONA)
        assert len(marca.estado_fuente["huellas"]) == 7
        assert all(k.startswith("sobusa|") for k in marca.estado_fuente["huellas"])
        segunda, _ = _en_ciclo(s, _ejecucion(s, entorno))
        assert segunda["tablas"]["timbradas_consolidado"]["resultado"] == "sin_cambios"
        assert "filas_fuente" not in segunda["tablas"]["timbradas_consolidado"]
    finally:
        with motor_fuente.begin() as c:
            c.execute(text("DELETE FROM timbradas_consolidado WHERE proceso = 'cootransoriente'"))


def test_los_duplicados_de_un_consolidado_se_reportan_al_responsable(entorno, sesion, monkeypatch):
    """§6.3 «Unicidad: reportar al responsable del consolidado; no corregir directamente» (6.3-06): las llaves
    duplicadas (UNI-001) de las filas leídas de una tabla consolidada se reportan como las del lote del ciclo
    (ejecucion.reportar_unicidad): el mismo canal de correo, el mismo formato, la fila en notification_log con el lote
    «id8:tabla» en la transacción del ciclo y el resumen en el resultado de la tabla."""
    from app.modelos_db import Notificacion
    from app.servicios import consolidados

    monkeypatch.setenv("NOTIF_UNICIDAD_DESTINATARIOS", "consolidado@extreme.example")
    s = sesion
    eid = _ejecucion(s, entorno)
    paso = consolidados.Paso(consolidados.CONFIG[consolidados.TABLA_RUTA],
                             consolidados.fuente_de_la_tabla(consolidados.TABLA_RUTA), s, eid,
                             consolidados.tolerancias_de({}), {}, [], datetime.now(ZONA))
    try:
        r = consolidados._procesar_filas(paso, pd.DataFrame(_filas_consolidado()[:1] * 2 + _filas_consolidado()[1:3]))
        s.commit()
        assert r["errores_por_codigo"]["UNI-001"] == 2 and r["filas_validas"] == 2
        reporte = r["reporte_unicidad"]
        assert (reporte["lote"], reporte["llaves_duplicadas"], reporte["filas_duplicadas"]) == (paso.lote, 1, 2)
        assert reporte["consulta"] == f"/api/v1/frequency/executions/{eid}/errors?codigo=UNI-001"
        s.expire_all()
        fila = s.get(Notificacion, reporte["notification_id"])
        assert fila.execution_id == eid and fila.canal == "correo" and fila.estado == "simulada"
        assert fila.asunto == f"[CALIDAD §6.3] 1 llave duplicada en el lote {paso.lote}"
        assert fila.detalle["tipo"] == "reporte_unicidad" and fila.detalle["reporte"]["corregido"] is False
        assert "id_ruta=2" in fila.mensaje and "No se corrigió nada" in fila.mensaje
        uni = [e for e in _errores(s, eid) if e.codigo == "UNI-001"]
        assert len(uni) == 2 and all(e.lote == paso.lote for e in uni)
    finally:
        s.rollback()
        s.execute(text(f"DELETE FROM {E}.notification_log WHERE execution_id = :e"), {"e": eid})
        s.commit()


def test_una_llave_repetida_que_la_lectura_deduplico_se_reporta_al_responsable(entorno, sesion, motor_fuente,
                                                                               monkeypatch):
    """6.3-06 también en la lectura incremental: el UNIQUE de timbradas_consolidado deja pasar dos filas con
    id_estacionalidad nulo y el resto de la llave igual. La lectura entrega solo la más reciente y el resumen de la
    tabla lo dice (lectura.duplicadas_llave = 1); las dos filas vuelven a la calidad, las dos quedan UNI-001 en
    data_quality_error y el reporte va al responsable del consolidado por ejecucion.reportar_unicidad, en la
    transacción del ciclo. No se corrige nada en la fuente. El ciclo siguiente vuelve a leer esas filas (están en la
    ventana de solape de la marca), pero ya se entregaron con la misma huella: la tabla sale «sin_cambios», sin otro
    UNI-001 ni otro reporte al responsable."""
    from app.modelos_db import Notificacion

    monkeypatch.setenv("NOTIF_UNICIDAD_DESTINATARIOS", "consolidado@extreme.example")
    s = sesion
    base = _filas_consolidado()[0]
    repetidas = [dict(base, id_estacionalidad=None, subidas=base["subidas"] + extra,
                      ultima_actualizacion=MARCA + timedelta(minutes=minutos))
                 for extra, minutos in ((0, 5), (100, 10))]
    with motor_fuente.begin() as c:     # el esquema sintético de esta prueba, nunca la réplica
        c.execute(text(f"INSERT INTO {ESQUEMA}.timbradas_consolidado (proceso, id_ruta, id_dia_semana, "
                       "id_estacionalidad, hora, hora_inicio, hora_fin, subidas, bajadas, nro_viajes, "
                       "promedio_subidas, promedio_bajadas, ultima_actualizacion) VALUES (:proceso, :id_ruta, "
                       ":id_dia_semana, :id_estacionalidad, :hora, :hora_inicio, :hora_fin, :subidas, :bajadas, "
                       ":nro_viajes, :promedio_subidas, :promedio_bajadas, :ultima_actualizacion)"), repetidas)
    eid = _ejecucion(s, entorno)
    siguiente = None
    try:
        r, fallos = _en_ciclo(s, eid)
        t = r["tablas"]["timbradas_consolidado"]
        assert fallos == [] and t["resultado"] == "contrastado"
        assert (t["lectura"]["leidas"], t["lectura"]["entregadas"], t["lectura"]["duplicadas_llave"]) == (9, 8, 1)
        assert t["filas"] == 9 and t["errores_por_codigo"]["UNI-001"] == 2
        reporte = t["reporte_unicidad"]
        assert (reporte["lote"], reporte["llaves_duplicadas"], reporte["filas_duplicadas"]) == (
            f"{eid.hex[:8]}:timbradas_consolidado", 1, 2)
        s.expire_all()
        aviso = s.get(Notificacion, reporte["notification_id"])
        assert aviso.execution_id == eid and aviso.canal == "correo" and "No se corrigió nada" in aviso.mensaje
        uni = [e for e in _errores(s, eid) if e.codigo == "UNI-001"]
        assert len(uni) == 2 and {e.llave["id_estacionalidad"] for e in uni} == {None}
        assert all(e.lote == reporte["lote"] and e.bloqueante for e in uni)
        with motor_fuente.connect() as c:       # la fuente sigue con sus dos filas: no se corrigió nada
            assert c.execute(text("SELECT count(*) FROM timbradas_consolidado WHERE id_estacionalidad IS NULL")
                             ).scalar() == 2
        siguiente = _ejecucion(s, entorno)       # el ciclo siguiente, sin nada nuevo en la fuente
        r2, fallos2 = _en_ciclo(s, siguiente)
        t2 = r2["tablas"]["timbradas_consolidado"]
        assert fallos2 == [] and t2["resultado"] == "sin_cambios" and "reporte_unicidad" not in t2
        assert (t2["lectura"]["leidas"], t2["lectura"]["entregadas"], t2["lectura"]["duplicadas_llave"]) == (9, 0, 1)
        assert not [e for e in _errores(s, siguiente) if e.codigo == "UNI-001"]
        avisos = s.execute(text(f"SELECT count(*) FROM {E}.notification_log WHERE execution_id = :e"),
                           {"e": siguiente}).scalar()
        assert avisos == 0
    finally:
        with motor_fuente.begin() as c:
            c.execute(text("DELETE FROM timbradas_consolidado WHERE id_estacionalidad IS NULL"))
        s.rollback()
        s.execute(text(f"DELETE FROM {E}.notification_log WHERE execution_id IN (:e, :f)"),
                  {"e": eid, "f": siguiente or eid})
        s.commit()


def _restaurar_consolidado(c) -> None:
    c.execute(text(f"INSERT INTO {ESQUEMA}.timbradas_consolidado (proceso, id_ruta, id_dia_semana, id_estacionalidad, "
                   "hora, hora_inicio, hora_fin, subidas, bajadas, nro_viajes, promedio_subidas, promedio_bajadas, "
                   "ultima_actualizacion) VALUES (:proceso, :id_ruta, :id_dia_semana, :id_estacionalidad, :hora, "
                   ":hora_inicio, :hora_fin, :subidas, :bajadas, :nro_viajes, :promedio_subidas, :promedio_bajadas, "
                   ":ultima_actualizacion)"), _filas_consolidado())


def test_tolerancias_de_la_version_de_la_ejecucion(entorno, sesion):
    s = sesion
    eid = _ejecucion(s, entorno)
    _historico_propio(s, eid)
    r, _ = _en_ciclo(s, eid, {"contraste_tolerancia": 0.85, "contraste_tolerancia_grosera": 0.9})
    t = r["tablas"]["timbradas_consolidado"]
    assert t["contraste"]["diferencias"] == 0 and r["tolerancias"]["contraste_tolerancia"] == 0.85
    assert not [e for e in _errores(s, eid) if e.codigo.startswith("CONTR")]


def test_una_tabla_que_falla_no_detiene_las_demas_ni_mueve_su_marca(entorno, sesion, monkeypatch):
    from app.servicios import consolidados

    original = consolidados.fuente_de_la_tabla

    def con_falla(tabla):
        f = original(tabla)
        if tabla == "timbradas_segmentos_anio":
            def rota(*a, **k):
                raise ConnectionError("la fuente se cayó a mitad de la lectura")
            f.leer_incremental = rota
        return f

    monkeypatch.setattr(consolidados, "fuente_de_la_tabla", con_falla)
    s = sesion
    eid = _ejecucion(s, entorno)
    r, fallos = _en_ciclo(s, eid)
    assert r["tablas"]["timbradas_segmentos_anio"]["resultado"] == "error"
    assert fallos == [{"etapa": "consolidados", "tabla": "timbradas_segmentos_anio",
                       "error": "la fuente se cayó a mitad de la lectura"}]
    assert r["tablas"]["timbradas_consolidado"]["resultado"] == "contrastado"
    assert s.get(MarcaAguaTabla, ("sobusa", "timbradas_segmentos_anio")) is None


# ---------------------------------------------------------------- segmentos: agregación materializada
def _segmentos_propios(s) -> None:
    """segmento_estadistica_dia (lo que deja el trabajo «segmentos»): segmentos 11 y 12 de la ruta 16 en tres lunes,
    20 viajes por día en la hora en que el bus PASA por el segmento (8 a las 6 y 12 a las 7); 5 subidas por viaje en el
    11 y 3 en el 12 (máximo 4), 4 bajadas y 30 pasajeros por viaje."""
    filas = [{"s": seg, "f": dia, "h": hora, "n": n, "ss": por_viaje * n, "mx": max_s, "sb": 4 * n, "sp": 30 * n}
             for seg, por_viaje, max_s in ((11, 5, 9), (12, 3, 4)) for dia in LUNES for hora, n in ((6, 8), (7, 12))]
    s.execute(text(f"INSERT INTO {E}.segmento_estadistica_dia (id_segmento, idruta, nro_segmento, fecha, "
                   "id_estacionalidad, id_dia_semana, hora, nro_viajes, suma_subidas, max_subidas, min_subidas, "
                   "suma_bajadas, max_bajadas, min_bajadas, suma_pasajeros, max_pasajeros, min_pasajeros) "
                   "VALUES (:s, 16, 1, :f, 25, 1, :h, :n, :ss, :mx, 0, :sb, 8, 0, :sp, 60, -10)"), filas)
    s.commit()


SQL_SEGMENTOS_ANIO = (
    f"INSERT INTO {ESQUEMA}.timbradas_segmentos_anio (id_segmento, proceso, ano, id_ruta, id_dia_semana, "
    "id_estacionalidad_anio, hora, hora_inicio, hora_fin, subidas, bajadas, pasajeros, nro_viajes, promedio_subidas, "
    "promedio_bajadas, promedio_pasajeros, ultima_actualizacion) VALUES (:seg, :proceso, 2025, :ruta, :dia, :ea, :hi, "
    ":hi, :hf, :su, :ba, :pa, :n, :ps, :pb, :pp, :u)")


def _fila_segmento(seg: int, bloque: time, n: int, subidas_por_viaje: int = 5, **mas) -> dict:
    """Una fila de Extreme de un segmento de la ruta 16 un lunes corriente, en el bloque de 15 minutos `bloque`: n
    viajes con 4 bajadas y 30 pasajeros por viaje; los promedios, con el CEIL que escribe Extreme (H7)."""
    fin = (datetime.combine(date(2025, 1, 1), bloque) + timedelta(minutes=15)).time()
    f = {"proceso": "sobusa", "seg": seg, "ruta": 16, "dia": 1, "hi": bloque, "hf": fin, "u": MARCA, "n": n,
         "su": subidas_por_viaje * n, "ba": 4 * n, "pa": 30 * n, **mas}
    return f | {"ps": -(-f["su"] // n), "pb": -(-f["ba"] // n), "pp": -(-f["pa"] // n)}


def _sembrar_segmentos(c) -> None:
    """Las tablas por segmento de Extreme salen de timbradas_segmentos, como segmento_estadistica_dia, y cubren los
    mismos tres lunes: 60 viajes por segmento. La liquidación (fn_insert_timbradas_anio) pone los segmentos de cada
    viaje en el bloque de 15 minutos del FIN del viaje (H10): aquí, la mitad en el de las 07:45 y la mitad en el de las
    08:00, que no son las horas de paso de la agregación propia (6 y 7). El 11 cuadra; el 12 trae 5 subidas por viaje
    frente a 3 propias (la diferencia real sembrada)."""
    filas = [_fila_segmento(seg, bloque, 30) for seg in (11, 12) for bloque in (time(7, 45), time(8))]
    filas += [_fila_segmento(21, time(8), 40),        # el 21 es de la ruta 2
              _fila_segmento(77, time(8), 40)]        # no existe
    c.execute(text(f"INSERT INTO {ESQUEMA}.timbradas_segmentos_consolidado (id_segmento, proceso, id_ruta, "
                   "id_dia_semana, id_estacionalidad, hora, hora_inicio, hora_fin, subidas, bajadas, pasajeros, "
                   "nro_viajes, promedio_subidas, promedio_bajadas, promedio_pasajeros, ultima_actualizacion) VALUES "
                   "(:seg, :proceso, :ruta, :dia, 25, :hi, :hi, :hf, :su, :ba, :pa, :n, :ps, :pb, :pp, :u)"), filas)
    # la anual: el 11 cuadra en sus dos bloques; el 12 trae el DOBLE de viajes con los promedios propios (3 subidas por
    # viaje); y una fila del 11 con el festivo de un lunes (estacionalidad anual 2) en martes (VAL-007)
    anual = [dict(f, ea=1) for f in filas[:2]]
    anual += [_fila_segmento(12, bloque, 60, subidas_por_viaje=3, ea=1) for bloque in (time(7, 45), time(8))]
    anual.append(dict(filas[0], ea=2, dia=2))
    c.execute(text(SQL_SEGMENTOS_ANIO), anual)


def test_segmentos_contrastados_con_la_agregacion_materializada(entorno, sesion, motor_fuente):
    """§11.2: promedios por viaje y viajes por día por segmento × (año) × día ISO × estacionalidad, sin la hora: los
    bloques de Extreme son los del fin del viaje (H10) y la agregación propia está en la hora de paso. Con los mismos
    viajes no hay diferencia; la diferencia real sembrada sí sale, grosera y bloqueante. Por hora solo queda el rango
    [mínimo, máximo] propio (CONTR-003), que no bloquea. REL-004 y REL-006 (§7.3 paso 3) sobre las filas por segmento;
    VAL-007 en la anual."""
    from app.servicios import consolidados

    s = sesion
    _segmentos_propios(s)
    with motor_fuente.begin() as c:
        _sembrar_segmentos(c)
    try:
        eid = _ejecucion(s, entorno)
        r, fallos = _en_ciclo(s, eid)
    finally:
        with motor_fuente.begin() as c:
            c.execute(text("TRUNCATE timbradas_segmentos_consolidado, timbradas_segmentos_anio"))
    assert fallos == []
    t = r["tablas"]["timbradas_segmentos_consolidado"]
    assert t["resultado"] == "contrastado" and t["filas"] == 6
    assert t["errores_por_codigo"]["REL-006"] == 1 and t["errores_por_codigo"]["REL-004"] == 1
    c = t["contraste"]
    assert c["grano"] == ["id_segmento", "id_dia_semana", "id_estacionalidad"] and "H10" in c["nota"]
    assert "segmento_estadistica_dia" in c["agregacion_propia"]
    # los bloques de Extreme (07:45 y 08:00) no son las horas de paso propias (6 y 7): sin la hora, las llaves de los
    # segmentos 11 y 12 se comparan; solo el 12 difiere (5 subidas por viaje frente a 3: grosera, queda bloqueada)
    assert (c["llaves"], c["comparadas"], c["sin_agregacion_propia"]) == (4, 2, 2)
    assert (c["diferencias"], c["groseras"], c["llaves_bloqueadas"]) == (1, 1, 1)
    # viajes por día con los días de la agregación propia (las dos salen de timbradas_segmentos): los tres lunes que
    # cubren las dos, no los 51 lunes del calendario de 2025 (que darían una diferencia grosera falsa)
    assert c["dias_viajes_por_dia"] == consolidados.DIAS_PROPIOS
    # por hora, solo el rango: de los seis bloques-hora de Extreme, los cuatro de las 8 no tienen agregación propia en
    # esa hora y los dos de las 7 se comparan; el promedio del 12 (5) está fuera de su [0, 4]
    hora = c["por_hora"]
    assert hora["grano"] == [*c["grano"], "hora"] and "no bloqueante" in hora["nota"]
    assert (hora["llaves"], hora["comparadas"], hora["sin_agregacion_propia"], hora["fuera_de_rango"]) == (6, 2, 4, 1)
    errores = [e for e in _errores(s, eid) if e.lote.endswith("timbradas_segmentos_consolidado")]
    contr = sorted((e.codigo, e.llave["id_segmento"], str(e.llave.get("hora", "sin hora")), e.campo, e.bloqueante)
                   for e in errores if e.codigo.startswith("CONTR"))
    assert contr == [("CONTR-002", 12, "sin hora", "promedio_subidas", True),
                     ("CONTR-003", 12, "7", "promedio_subidas", False)]
    grosera = next(e for e in errores if e.codigo == "CONTR-002")
    assert grosera.llave == {"id_segmento": 12, "id_dia_semana": 1, "id_estacionalidad": 25, "proceso": "sobusa"}
    assert grosera.valor == "5.0000" and "66.7%" in grosera.detalle and "fuera del análisis" in grosera.detalle
    rango = next(e for e in errores if e.codigo == "CONTR-003")
    assert "[0, 4]" in rango.detalle and "H10" in rango.detalle
    anual = r["tablas"]["timbradas_segmentos_anio"]
    assert anual["resultado"] == "contrastado" and anual["errores_por_codigo"].get("VAL-007") == 1
    assert anual["contraste"]["grano"] == ["id_segmento", "ano", "id_dia_semana", "id_estacionalidad"]
    # la anual: el 11 cuadra; el 12 trae el doble de viajes con los mismos promedios, y sus 120 viajes se reparten en
    # los TRES lunes propios de la llave (40 por día), no en las seis filas de fecha y hora de la agregación propia
    viajes = [e for e in _errores(s, eid) if e.lote.endswith("timbradas_segmentos_anio") and e.codigo == "CONTR-002"]
    assert [(e.llave, e.campo, e.valor, e.bloqueante) for e in viajes] == [
        ({"id_segmento": 12, "ano": 2025, "id_dia_semana": 1, "id_estacionalidad": 25, "proceso": "sobusa"},
         "viajes_por_dia", "40.0000", True)]
    assert "frente a 20.00" in viajes[0].detalle and anual["contraste"]["diferencias"] == 1
    # §6.1 ultima_actualizacion de las dos tablas por segmento: cada una con su marca de agua, de esta ejecución
    for tabla, filas in (("timbradas_segmentos_consolidado", 6), ("timbradas_segmentos_anio", 5)):
        marca = s.get(MarcaAguaTabla, ("sobusa", tabla))
        assert marca.execution_id == eid and marca.filas_leidas == filas
        assert marca.marca_agua == MARCA.replace(tzinfo=ZONA) and r["tablas"][tabla]["marca_nueva"].startswith(
            "2026-01-10T08:00:00")


def test_una_incidencia_vieja_con_la_hora_en_la_llave_se_sigue_listando(cliente, entorno, sesion):
    """Antes el contraste por segmento era por hora y sus CONTR-002 guardaban la hora en data_quality_error.llave. Las
    filas viejas siguen ahí hasta que la retención las borre: la llave es un JSON libre, y la API de errores las lista
    junto a las nuevas (sin la hora) y las filtra igual por lote, código y bloqueante."""
    eid = _ejecucion(sesion, entorno)
    lote = f"{eid.hex[:8]}:timbradas_segmentos_consolidado"
    base = {"id_segmento": 12, "id_dia_semana": 1, "id_estacionalidad": 25, "proceso": "sobusa"}
    sesion.add_all([ErrorCalidad(execution_id=eid, lote=lote, fila=None, campo="promedio_subidas", codigo="CONTR-002",
                                 dimension="consistencia", detalle=detalle, llave=llave, valor="5.0000",
                                 bloqueante=True)
                    for detalle, llave in (("incidencia de antes, por hora", base | {"hora": 7}),
                                           ("incidencia de ahora, sin la hora", base))])
    sesion.commit()
    r = cliente.get(f"/api/v1/frequency/executions/{eid}/errors",
                    params={"codigo": "CONTR-002", "lote": lote, "bloqueante": "true"})
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert r.json()["total"] == 2 and {e["llave"].get("hora") for e in items} == {7, None}
    assert {e["llave"]["id_segmento"] for e in items} == {12} and all(e["bloqueante"] for e in items)
    detalle = cliente.get(f"/api/v1/frequency/executions/{eid}").json()
    assert detalle["errores_por_dimension"].get("consistencia") == 2


# ---------------------------------------------------------------- el ciclo completo
@pytest.fixture
def ciclo(entorno, sesion, monkeypatch):
    """El ciclo lee un tramo empaquetado con bajadas (con un proceso propio en las marcas por ruta), no pide el
    refresco de segmentos y encuentra el histórico propio de las rutas 2 y 16 con la estacionalidad 25 (el contraste
    de esas llaves no depende de lo que otras pruebas dejaron en el histórico, que queda sin estacionalidad)."""
    from app.servicios import datos, ejecucion, fuentes, segmentos_refresco

    proceso = f"prueba-consolidados-{uuid.uuid4().hex[:8]}"
    tramo = datos.con_bajadas(datos.demanda_horaria(desde=date(2025, 3, 3), hasta=date(2025, 3, 5)))
    tramo["ultima_actualizacion"] = pd.Timestamp.now(tz="America/Bogota") + pd.Timedelta(days=1)

    def obtener():
        f = fuentes.FuenteParquet(cargador=lambda: tramo.copy())
        f.proceso = proceso
        return f

    monkeypatch.setattr(ejecucion, "obtener_fuente", obtener)
    monkeypatch.setattr(segmentos_refresco, "encolar_tras_ciclo", lambda eid: None)
    _historico_propio(sesion, _ejecucion(sesion, entorno))
    return entorno


def test_ciclo_sin_partir_guarda_bajadas_y_contrasta_los_consolidados(cliente, ciclo, sesion):
    r = cliente.post("/api/v1/frequency/executions", json={"hasta": "2025-03-05", "plan_dia": False,
                                                            "notificar": False})
    assert r.status_code == 202, r.text
    eid = uuid.UUID(r.json()["execution_id"])
    ciclo.append(eid)
    d = cliente.get(f"/api/v1/frequency/executions/{eid}").json()
    assert d["estado"] == "ok", d["mensaje"]
    cons = d["metricas"]["calidad"]["consolidados"]
    assert cons["tablas"]["timbradas_consolidado"]["resultado"] == "contrastado"
    assert cons["resultados"] == {"contrastado": 1, "sin_filas_fuente": 2}
    # §6.1 y §9.5: el histórico guarda las bajadas de los viajes del lote
    sesion.expire_all()
    filas = sesion.execute(select(DemandaObservada.bajadas_viajes).where(DemandaObservada.execution_id == eid)).all()
    assert filas and all(b is not None for (b,) in filas)
    # las incidencias se consultan por la API de errores de la ejecución
    errores = cliente.get(f"/api/v1/frequency/executions/{eid}/errors", params={"codigo": "CONTR-001"}).json()
    assert errores["total"] >= 1 and all(e["lote"].endswith("timbradas_consolidado") for e in errores["items"])
    bloq = cliente.get(f"/api/v1/frequency/executions/{eid}/errors",
                       params={"codigo": "CONTR-001", "bloqueante": "true", "idruta": 16}).json()
    assert bloq["total"] >= 1


def test_ciclo_partido_la_madre_contrasta_una_vez_con_la_version_fijada(cliente, ciclo, sesion, monkeypatch):
    """RNF-005: los trabajos de ruta no leen los consolidados; la madre los lee al cerrar, una vez, con la versión de
    umbrales fijada al crear la ejecución aunque un PUT /thresholds cambie las tolerancias mientras tanto."""
    from app.servicios import ejecucion

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(ejecucion, "ejecutar", lambda *a, **k: None)
        r = cliente.post("/api/v1/frequency/executions", json={"hasta": "2025-03-05", "particion": "ruta",
                                                                "plan_dia": False, "notificar": False})
    assert r.status_code == 202, r.text
    madre = uuid.UUID(r.json()["execution_id"])
    ciclo.append(madre)
    antes = cliente.get("/api/v1/thresholds").json()
    cambio = cliente.put("/api/v1/thresholds", json={"valores": {"contraste_tolerancia": 0.95,
                                                                 "contraste_tolerancia_grosera": 0.99},
                                                     "motivo": "prueba de la versión fijada"})
    assert cambio.status_code == 200, cambio.text
    try:
        ejecucion.ejecutar(madre, [uuid.UUID(t["execution_id"]) for t in r.json()["trabajos"]])
        d = cliente.get(f"/api/v1/frequency/executions/{madre}").json()
        assert d["estado"] == "ok", d["mensaje"]
        cons = d["metricas"]["calidad"]["consolidados"]
        assert cons["tolerancias"]["contraste_tolerancia"] == antes["valores"]["contraste_tolerancia"]
        assert cons["tablas"]["timbradas_consolidado"]["resultado"] == "contrastado"
        for t in d["trabajos"]:
            trabajo = cliente.get(f"/api/v1/frequency/executions/{t['execution_id']}").json()
            assert "consolidados" not in (trabajo["metricas"].get("calidad") or {})
        sesion.expire_all()
        marca = sesion.get(MarcaAguaTabla, ("sobusa", "timbradas_consolidado"))
        assert marca is not None and marca.execution_id == madre
    finally:
        restituir_umbrales(sesion, antes["version"])


def test_put_thresholds_valida_las_tolerancias_del_contraste(cliente):
    for valores in ({"contraste_tolerancia": 0.8, "contraste_tolerancia_grosera": 0.5},
                    {"contraste_viajes_minimos": 0}, {"contraste_viajes_minimos": 2.5},
                    {"contraste_tolerancia": None}, {"contraste_tolerancia_grosera": "mucho"}):
        r = cliente.put("/api/v1/thresholds", json={"valores": valores, "motivo": "inválido"})
        assert r.status_code == 422 and r.json()["error"]["codigo"] == "umbral_invalido", valores


# ---------------------------------------------------------------- bajadas en el histórico y ALT-008
def test_bajadas_en_el_historico_sin_borrar_lo_que_el_lote_no_trae_y_alt008(entorno, sesion):
    from app.servicios import alertas, ejecucion, ingesta

    s = sesion
    eid = _ejecucion(s, entorno)
    dias = [date(2025, 3, 3) + timedelta(weeks=k) for k in range(6)]          # seis lunes
    lote = pd.DataFrame([{"ruta": "PRUEBA-CONS", "fecha": d, "hora": h, "pasajeros": 100.0, "salidas": 2,
                          "bajadas_viajes": 90.0 if d != dias[-1] else 20.0, "subidas": 95.0, "bajadas": 88.0,
                          "viajes_con_timbradas": 2, "ultima_actualizacion": pd.Timestamp("2025-04-20", tz="UTC")}
                         for d in dias for h in range(4, 21)])
    r = ingesta.incorporar(s, lote, eid)
    s.commit()
    assert r["insertadas"] == len(lote)
    fila = s.scalar(select(DemandaObservada).where(DemandaObservada.ruta == "PRUEBA-CONS",
                                                   DemandaObservada.fecha == dias[0], DemandaObservada.hora == 7))
    assert (fila.bajadas_viajes, fila.subidas, fila.bajadas, fila.viajes_con_timbradas) == (90.0, 95.0, 88.0, 2)
    # un lote sin las medidas (modo offline sin el archivo) no borra las que ya estaban
    r = ingesta.incorporar(s, lote.drop(columns=list(ingesta.MEDIDAS)).assign(pasajeros=101.0), eid)
    s.commit()
    s.expire_all()
    fila = s.get(DemandaObservada, fila.id)
    assert r["actualizadas"] == len(lote) and fila.pasajeros == 101.0 and fila.bajadas_viajes == 90.0
    cons = ejecucion._consolidado_del_dia(s, "PRUEBA-CONS", dias[-1], 0, {"semanas_referencia": 8}, set())
    assert cons["bajadas"] == 20.0 * 17 and cons["referencia_valores"]["bajadas"] == [90.0 * 17] * 5
    ctx = {"ruta": "PRUEBA-CONS", "consolidado": cons, "detectada_en": datetime(2025, 4, 8, tzinfo=ZONA)}
    a = next(x for x in alertas.evaluar_observadas(ctx) if x["codigo"] == "ALT-008")
    assert a["variables"]["campo"] == "bajadas" and "bajadas =" in a["explicacion"]


# ---------------------------------------------------------------- migración 0013
def _migracion_0013():
    import importlib.util

    from tests.integracion.conftest import RAIZ

    spec = importlib.util.spec_from_file_location("m0013", RAIZ / "alembic" / "versions" / "0013_consolidados_ciclo.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def test_migracion_0013_sube_y_baja(migrada, sesion):
    """La 0013 copia las tolerancias del código, crea UNA versión nueva vigente, agrega las cuatro columnas del
    histórico y marca_agua_tabla; bajarla borra solo lo suyo. Sube y baja su propia revisión sin suponer que es la
    cabeza: lo que venga después se baja antes y vuelve a subir al final (upgrade head)."""
    from sqlalchemy import func, inspect

    from app.modelos_db import Umbral
    from app.servicios import consolidados
    from app.servicios.ejecucion import SQL_CANDADO_UMBRALES
    from tests.integracion.conftest import _alembic

    m = _migracion_0013()
    assert m.revision == "0013" and m.down_revision == "0012"
    assert {n: v for n, v, _d in m.UMBRALES_0013} == consolidados.TOLERANCIAS_POR_DEFECTO
    assert m.CANDADO_UMBRALES == SQL_CANDADO_UMBRALES.text      # el mismo candado que PUT /thresholds

    def estado():
        sesion.expire_all()
        insp = inspect(sesion.get_bind())
        columnas = {c["name"] for c in insp.get_columns("demanda_observada", schema=E)}
        tablas = set(insp.get_table_names(schema=E))
        vigentes = {f.nombre: f.creado_por for f in sesion.scalars(select(Umbral).where(Umbral.vigente))}
        propias = sesion.scalar(select(func.count()).select_from(Umbral).where(Umbral.creado_por == m.CREADO_POR))
        return columnas, tablas, vigentes, propias

    columnas, tablas, vigentes, _ = estado()
    assert set(m.COLUMNAS_0013) <= columnas and "marca_agua_tabla" in tablas
    assert set(consolidados.TOLERANCIAS_POR_DEFECTO) <= set(vigentes)
    sesion.commit()
    try:
        _alembic("downgrade", m.revision)          # lo que venga después de la 0013 queda fuera
        _alembic("downgrade", m.down_revision)
        columnas, tablas, vigentes, propias = estado()
        assert not set(m.COLUMNAS_0013) & columnas and "marca_agua_tabla" not in tablas and propias == 0
        assert vigentes
        if all(c.startswith("migracion_") for c in vigentes.values()):   # sin PUT posterior que las arrastre
            assert not set(consolidados.TOLERANCIAS_POR_DEFECTO) & set(vigentes)
        _alembic("upgrade", m.revision)
        columnas, tablas, vigentes, propias = estado()
        assert set(m.COLUMNAS_0013) <= columnas and "marca_agua_tabla" in tablas
        assert set(consolidados.TOLERANCIAS_POR_DEFECTO) <= set(vigentes) and propias == len(vigentes)
        assert set(vigentes.values()) == {m.CREADO_POR}           # la versión vigente es la que dejó la 0013
    finally:
        sesion.rollback()
        _alembic("upgrade", "head")
    columnas, tablas, vigentes, _ = estado()
    assert set(m.COLUMNAS_0013) <= columnas and "marca_agua_tabla" in tablas
    assert set(consolidados.TOLERANCIAS_POR_DEFECTO) <= set(vigentes)
