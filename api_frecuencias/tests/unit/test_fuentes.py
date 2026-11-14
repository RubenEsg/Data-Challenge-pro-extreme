"""Pruebas de las fuentes incrementales. La fuente PostgreSQL se prueba SOLO con unittest.mock: nunca se conecta a una
base real (y menos a la base compartida del reto)."""
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from unittest import mock

import pandas as pd
import pytest

from app.servicios import fuentes as F


def demanda_falsa():
    filas = []
    for dia in (1, 2, 3):
        for hora in (6, 7):
            filas.append({"ruta": "CL 72", "fecha": date(2025, 1, dia), "hora": hora, "pasajeros": 10.0 * hora,
                          "salidas": 3,
                          "ultima_actualizacion": pd.Timestamp(f"2025-01-0{dia} 23:59:59", tz="America/Bogota")})
    return pd.DataFrame(filas)


# ------------------------------------------------------------------ FuenteParquet
def test_parquet_ciclo_incremental_simula_la_llegada_diaria():
    f = F.FuenteParquet(cargador=demanda_falsa)
    d1, m1 = f.leer_incremental(None, hasta=date(2025, 1, 1))
    assert len(d1) == 2 and set(d1["fecha"]) == {date(2025, 1, 1)}
    d2, m2 = f.leer_incremental(m1, hasta=date(2025, 1, 2))
    assert len(d2) == 2 and set(d2["fecha"]) == {date(2025, 1, 2)}
    assert m2 > m1
    d3, m3 = f.leer_incremental(m2, hasta=date(2025, 1, 2))   # no llegó nada nuevo
    assert len(d3) == 0 and m3 == m2
    d4, m4 = f.leer_incremental(m2)                             # sin «hasta»: todo lo pendiente
    assert len(d4) == 2 and pd.Timestamp(m4) == pd.Timestamp("2025-01-03 23:59:59", tz="America/Bogota")


def test_parquet_marca_sin_zona_se_interpreta_en_bogota():
    f = F.FuenteParquet(cargador=demanda_falsa)
    d, _ = f.leer_incremental(datetime(2025, 1, 2, 23, 59, 59))
    assert set(d["fecha"]) == {date(2025, 1, 3)}


def test_parquet_lee_los_datos_del_proyecto():
    d, marca = F.FuenteParquet().leer_incremental(None, hasta=date(2023, 1, 1))
    assert len(d) > 0 and {"ruta", "fecha", "hora", "pasajeros", "salidas", "ultima_actualizacion"} <= set(d.columns)
    assert marca is not None


# ------------------------------------------------------------------ guardia de solo lectura
@pytest.mark.parametrize("sql", [
    "SELECT * FROM timbradas_consolidado WHERE ultima_actualizacion > :marca",
    "with t as (select 1 as x) select x from t",
    "SELECT nombre FROM rutas WHERE nombre = 'DELETE'",          # palabra prohibida solo dentro de un literal
    "SELECT 1; ",
])
def test_guardia_acepta_select(sql):
    assert F.validar_solo_select(sql) is True


@pytest.mark.parametrize("sql", [
    "DELETE FROM timbradas_consolidado",
    "UPDATE rutas SET capacidad = 0",
    "INSERT INTO rutas VALUES (1)",
    "DROP TABLE rutas",
    "TRUNCATE timbradas_anio",
    "SELECT * INTO copia FROM rutas",
    "SELECT * FROM rutas FOR UPDATE",
    "SELECT 1; DELETE FROM rutas",
    "WITH x AS (DELETE FROM rutas RETURNING *) SELECT * FROM x",
    "  ",
    "SET statement_timeout = 0",
    "select pg_sleep(100)",
])
def test_guardia_rechaza_lo_que_no_es_select(sql):
    with pytest.raises(F.OperacionNoPermitida):
        F.validar_solo_select(sql)


# ------------------------------------------------------------------ FuentePostgresSoloLectura (solo mocks)
def motor_falso(filas):
    motor = mock.MagicMock(name="engine")
    conn = motor.connect.return_value.__enter__.return_value
    resultado_select = mock.MagicMock()
    resultado_select.mappings.return_value.all.return_value = filas

    def ejecutar(stmt, params=None):
        return resultado_select if str(stmt).lstrip().upper().startswith("SELECT") else mock.MagicMock()

    conn.execute.side_effect = ejecutar
    return motor, conn


def sentencias(conn):
    return [" ".join(str(c.args[0]).split()) for c in conn.execute.call_args_list]


def test_postgres_abre_transaccion_read_only_con_timeout_y_hace_rollback():
    filas = [{"id_ruta": 16, "hora": 7, "subidas": 300, "ultima_actualizacion": datetime(2025, 3, 10, 12, tzinfo=UTC)},
             {"id_ruta": 21, "hora": 7, "subidas": 200, "ultima_actualizacion": datetime(2025, 3, 10, 13, tzinfo=UTC)}]
    motor, conn = motor_falso(filas)
    f = F.FuentePostgresSoloLectura(url="postgresql+psycopg://lector@host-falso/db", motor=motor,
                                    statement_timeout_ms=1500, tabla="timbradas_consolidado")
    marca = datetime(2025, 3, 10, tzinfo=UTC)
    d, nueva = f.leer_incremental(marca)
    s = sentencias(conn)
    assert s[0] == "SET TRANSACTION READ ONLY"
    assert s[1] == "SET LOCAL statement_timeout = 1500"
    assert s[2] == "SET LOCAL TimeZone = 'America/Bogota'"       # marcas sin zona de Extreme (H10)
    assert s[3].startswith("SELECT * FROM timbradas_consolidado WHERE")
    assert "ultima_actualizacion > :marca" in s[3] and "ORDER BY" in s[3] and "LIMIT" in s[3]
    # ventana de solape: se lee desde marca − FUENTE_SOLAPE_MIN (15 min por omisión)
    assert conn.execute.call_args_list[3].args[1]["marca"] == marca - timedelta(minutes=15)
    conn.rollback.assert_called_once()
    conn.commit.assert_not_called()
    assert len(d) == 2 and pd.Timestamp(nueva) == pd.Timestamp("2025-03-10 13:00", tz="UTC")


def test_postgres_con_hasta_y_sin_resultados_conserva_la_marca():
    motor, conn = motor_falso([])
    f = F.FuentePostgresSoloLectura(url="postgresql+psycopg://x@y/z", motor=motor, tabla="timbradas_consolidado")
    marca = datetime(2025, 3, 10, tzinfo=UTC)
    d, nueva = f.leer_incremental(marca, hasta=date(2025, 3, 11))
    assert len(d) == 0 and nueva == marca
    assert "ultima_actualizacion < :hasta" in sentencias(conn)[3]
    assert conn.execute.call_args_list[3].args[1]["hasta"].isoformat().startswith("2025-03-12T00:00:00-05:00")


def test_postgres_rechaza_escrituras_sin_tocar_la_base():
    motor, _ = motor_falso([])
    f = F.FuentePostgresSoloLectura(url="postgresql+psycopg://x@y/z", motor=motor)
    with pytest.raises(F.OperacionNoPermitida):
        f.consultar("DELETE FROM timbradas_consolidado")
    motor.connect.assert_not_called()


def test_postgres_solo_tablas_de_lista_blanca():
    with pytest.raises(F.OperacionNoPermitida):
        F.FuentePostgresSoloLectura(url="postgresql+psycopg://x@y/z", tabla="usuarios", motor=mock.MagicMock())


def test_postgres_lee_la_url_del_entorno(monkeypatch):
    monkeypatch.setenv("FUENTE_DATABASE_URL", "postgresql+psycopg://lector@host-falso:5432/db")
    with mock.patch("sqlalchemy.create_engine") as crear:
        f = F.FuentePostgresSoloLectura()
        f._engine()
        crear.assert_called_once()
        assert crear.call_args.args[0] == "postgresql+psycopg://lector@host-falso:5432/db"


def test_postgres_sin_url_falla(monkeypatch):
    monkeypatch.delenv("FUENTE_DATABASE_URL", raising=False)
    with pytest.raises(ValueError):
        F.FuentePostgresSoloLectura()


def test_fuente_desde_entorno(monkeypatch):
    assert isinstance(F.fuente_desde_entorno({}), F.FuenteParquet)
    f = F.fuente_desde_entorno({"FUENTE": "postgres", "FUENTE_DATABASE_URL": "postgresql+psycopg://x@y/z",
                                "FUENTE_STATEMENT_TIMEOUT_MS": "2000"})
    assert isinstance(f, F.FuentePostgresSoloLectura) and f.statement_timeout_ms == 2000
    with pytest.raises(ValueError):
        F.fuente_desde_entorno({"FUENTE": "excel"})


# ------------------------------------------------------------------ esquema real, solape y huella
def test_procesos_con_mayuscula_y_comillas_y_marca_de_timbradas_segmentos():
    assert "Procesos" in F.TABLAS_PERMITIDAS and "procesos" not in F.TABLAS_PERMITIDAS
    p = F.FuentePostgresSoloLectura(url="postgresql+psycopg://x@y/z", tabla="Procesos", motor=mock.MagicMock())
    assert " ".join(str(p.consulta_incremental()).split()).startswith('SELECT * FROM "Procesos"')
    ts = F.FuentePostgresSoloLectura(url="postgresql+psycopg://x@y/z", tabla="timbradas_segmentos",
                                     motor=mock.MagicMock())
    sql = " ".join(str(ts.consulta_incremental(con_hasta=True)).split())
    assert "ultimaactualizacion > :marca" in sql and "ultimaactualizacion < :hasta" in sql
    assert "ORDER BY timbradas_segmentos.ultimaactualizacion" in sql


def test_vista_demanda_segmentos_es_un_select_con_parametros():
    f = F.FuentePostgresSoloLectura(url="postgresql+psycopg://x@y/z", tabla="demanda_segmentos",
                                    motor=mock.MagicMock())
    for con_hasta in (False, True):
        texto = f.consulta_incremental(con_hasta=con_hasta).text
        assert F.validar_solo_select(texto)
        assert ":marca" in texto and ":limite" in texto and (":hasta" in texto) == con_hasta
    for nombre, sql in F.CONSULTAS_CONTEXTO.items():
        assert F.validar_solo_select(sql), nombre
    assert "clave_interfaz_despacho" not in F.CONSULTAS_CONTEXTO["procesos"]     # minimización (§18)


def _fila(viaje, ts, subidas):
    return {"id_segmento": 7, "id_viaje": viaje, "hora_inicio": "06:00:00", "subidas": subidas, "bajadas": 1,
            "pasajeros": 3, "ultimaactualizacion": ts}


def test_solape_entrega_la_fila_tardia_una_sola_vez_y_descarta_repetidas():
    t = datetime(2026, 11, 9, 1, 0)                     # marcas sin zona (hora de Bogotá), como las de Extreme
    lote1 = [_fila(1, t, 5), _fila(2, t + timedelta(minutes=5), 4)]
    motor, _ = motor_falso(lote1)
    f = F.FuentePostgresSoloLectura(url="postgresql+psycopg://x@y/z", tabla="timbradas_segmentos", motor=motor)
    d1, m1 = f.leer_incremental(None)
    assert len(d1) == 2 and f.resumen_lectura["nuevas"] == 2
    estado = f.estado_incremental
    assert pd.Timestamp(m1) == pd.Timestamp(t + timedelta(minutes=5), tz="America/Bogota")
    # segunda lectura: la ventana de solape vuelve a traer las 2 filas ya entregadas y una tardía (marca anterior a m1
    # porque su transacción empezó antes y se confirmó después) más una modificada
    tardia = _fila(3, t + timedelta(minutes=2), 9)
    modificada = _fila(1, t + timedelta(minutes=6), 6)
    motor2, conn2 = motor_falso([lote1[1], tardia, modificada])
    f2 = F.FuentePostgresSoloLectura(url="postgresql+psycopg://x@y/z", tabla="timbradas_segmentos", motor=motor2)
    d2, m2 = f2.leer_incremental(m1, estado_previo=estado)
    r = f2.resumen_lectura
    assert conn2.execute.call_args_list[3].args[1]["marca"] == m1 - timedelta(minutes=15)
    assert sorted(d2["id_viaje"]) == [1, 3]
    assert (r["tardias"], r["modificadas"], r["repetidas_solape"], r["nuevas"]) == (1, 1, 1, 0)
    # tercera lectura con lo mismo: nada nuevo (exactamente una vez)
    motor3, _ = motor_falso([lote1[1], tardia, modificada])
    f3 = F.FuentePostgresSoloLectura(url="postgresql+psycopg://x@y/z", tabla="timbradas_segmentos", motor=motor3)
    d3, m3 = f3.leer_incremental(m2, estado_previo=f2.estado_incremental)
    assert len(d3) == 0 and m3 == m2 and f3.resumen_lectura["repetidas_solape"] == 3


def test_resellado_sin_cambios_no_se_reprocesa():
    # fn_consolidar_timbradas_historicas vuelve a sellar todas las filas con la misma marca (hallazgo H7)
    t = datetime(2026, 8, 14, 11, 29)
    filas = [{"proceso": "sobusa", "id_ruta": 2, "id_dia_semana": d, "id_estacionalidad": 25, "hora": "06:00:00",
              "hora_inicio": "06:00:00", "hora_fin": "06:15:00", "subidas": 10 * d, "bajadas": d, "nro_viajes": 3,
              "ultima_actualizacion": t} for d in range(1, 8)]
    motor, _ = motor_falso(filas)
    f = F.FuentePostgresSoloLectura(url="postgresql+psycopg://x@y/z", motor=motor, tabla="timbradas_consolidado")
    d1, m1 = f.leer_incremental(None)
    assert len(d1) == 7 and set(d1["tipo_llegada"]) == {"carga_inicial"}
    resellado = [dict(x, ultima_actualizacion=t + timedelta(days=1)) for x in filas]
    resellado[3]["subidas"] += 1                         # solo una fila cambió de verdad
    motor2, _ = motor_falso(resellado)
    f2 = F.FuentePostgresSoloLectura(url="postgresql+psycopg://x@y/z", motor=motor2, tabla="timbradas_consolidado")
    d2, m2 = f2.leer_incremental(m1, estado_previo=f.estado_incremental)
    assert len(d2) == 1 and int(d2["id_dia_semana"].iloc[0]) == 4
    assert f2.resumen_lectura["repetidas_solape"] == 6 and m2 > m1


def test_leer_con_estado_no_cambia_la_firma_de_la_fuente_parquet():
    f = F.FuenteParquet(cargador=demanda_falsa)
    d, _ = F.leer_con_estado(f, None, date(2025, 1, 1), estado_previo={"huellas": {}})
    assert len(d) == 2


# ------------------------------------------------------------------ tabla del ciclo, proceso, estacionalidad y despacho
URL = "postgresql+psycopg://x@y/z"


def test_fuente_tabla_solo_admite_demanda_segmentos():
    from pydantic import ValidationError

    from app.config import Ajustes

    with pytest.raises(ValueError, match="demanda_segmentos"):
        F.fuente_desde_entorno({"FUENTE": "postgres", "FUENTE_DATABASE_URL": URL,
                                "FUENTE_TABLA": "timbradas_consolidado"})
    assert F.fuente_desde_entorno({"FUENTE": "postgres", "FUENTE_DATABASE_URL": URL}).tabla == "demanda_segmentos"
    assert F.FuentePostgresSoloLectura(url=URL, motor=mock.MagicMock()).tabla == "demanda_segmentos"
    with pytest.raises(ValidationError, match="demanda_segmentos"):
        Ajustes(_env_file=None, fuente_tabla="timbradas_segmentos_anio")
    assert Ajustes(_env_file=None).fuente_tabla == "demanda_segmentos"


def test_demanda_segmentos_une_procesos_y_estacionalidades_y_filtra_por_proceso():
    motor, conn = motor_falso([])
    f = F.FuentePostgresSoloLectura(url=URL, motor=motor, proceso="sobusa")
    f.leer_incremental(None)
    sql = sentencias(conn)[3]
    assert 'JOIN "Procesos" p ON p.proceso = r.proceso' in sql and "estacionalidades_anio" in sql
    assert "r.proceso = CAST(:proceso AS text)" in sql and "id_estacionalidad" in sql
    assert "SUM(v.numeropasajeros) FILTER (WHERE v.valido AND v.numeropasajeros <= 300)" in sql
    assert conn.execute.call_args_list[3].args[1]["proceso"] == "sobusa"
    todos, conn2 = motor_falso([])
    F.FuentePostgresSoloLectura(url=URL, motor=todos, proceso="*").leer_incremental(None)
    assert conn2.execute.call_args_list[3].args[1]["proceso"] is None


def test_demanda_segmentos_lleva_el_nombre_y_la_empresa_de_la_ruta_desde_las_franjas():
    """La consulta final no vuelve a unir rutas: con esa unión PostgreSQL estimaba unas 60 filas donde hay miles y, con
    la propuesta de índices entera y las estadísticas al día, unía los segmentos con un ciclo anidado que comparaba
    todos los viajes con todos (docs/evidencias/replica/indices_candidatos.md, «La propuesta entera»). El nombre y la
    empresa viajan desde el CTE franjas, que ya une rutas; el filtro por rutas del trabajo sigue ahí."""
    sql = F._SQL_DEMANDA_SEGMENTOS.format(filtro_hasta="", filtro_rutas="")
    assert sql.count("JOIN rutas r ON") == 1
    franjas = sql.split("franjas AS (")[1].split("), viajes AS (")[0]
    assert "JOIN rutas r ON r.idruta = pv.idruta" in franjas
    assert "SELECT DISTINCT pv.idruta, r.proceso, r.nombre, r.idempresa, date_trunc('hour', pv.fechasalida)" in franjas
    assert "f.idruta, f.proceso, f.nombre, f.idempresa, f.franja" in sql.split("), viajes AS (")[1]
    final = sql.split("\n)\nSELECT ")[1]
    assert final.startswith("v.nombre AS ruta, v.idruta, v.proceso, v.idempresa, CAST(v.franja AS date) AS fecha,")
    assert "GROUP BY v.nombre, v.idruta, v.proceso, v.idempresa, v.franja, es.id_estacionalidad" in final
    assert " r." not in final and "rutas" not in final
    por_ruta = F._SQL_DEMANDA_SEGMENTOS.format(filtro_hasta="", filtro_rutas=F.FILTRO_RUTAS_SEGMENTOS)
    assert "r.nombre = ANY(CAST(:rutas AS text[]))" in por_ruta.split("), viajes AS (")[0]
    assert F.validar_solo_select(sql) and F.validar_solo_select(por_ruta)


def test_estado_de_otra_version_no_se_compara():
    t = datetime(2026, 11, 9, 1, 0)
    filas = [_fila(1, t, 5)]
    f = F.FuentePostgresSoloLectura(url=URL, tabla="timbradas_segmentos", motor=motor_falso(filas)[0])
    f.leer_incremental(None)
    viejo = dict(f.estado_incremental, version=1)
    f2 = F.FuentePostgresSoloLectura(url=URL, tabla="timbradas_segmentos", motor=motor_falso(filas)[0])
    d, _ = f2.leer_incremental(t, estado_previo=viejo)
    assert len(d) == 1 and d["tipo_llegada"].tolist() == ["tardia"]


def test_ubicacion_despacho_en_las_dos_fuentes():
    p = F.FuenteParquet(cargador=demanda_falsa)
    punto = p.ubicacion_despacho("CL 72")
    assert punto == {"type": "Point", "coordinates": [-74.8043518, 10.8885557]}
    assert p.ubicacion_despacho("21") == punto and p.ubicacion_despacho("RUTA FANTASMA") is None
    motor, conn = motor_falso([{"punto": '{"type":"Point","coordinates":[-74.8043518,10.8885557]}'}])
    f = F.FuentePostgresSoloLectura(url=URL, motor=motor)
    assert f.ubicacion_despacho("CL 72") == punto
    assert f.ubicacion_despacho("CL 72") == punto                  # se guarda por ruta: una sola consulta
    sql = [s for s in sentencias(conn) if "ST_StartPoint" in s]
    assert len(sql) == 1 and "rs.nro_segmento = 1" in sql[0]
    assert F.validar_solo_select(F._SQL_UBICACION_DESPACHO)


# ------------------------------------------------------------------ consolidados y bajadas (migración 0013)
def test_demanda_segmentos_trae_bajadas_de_los_viajes_validos_con_la_regla_de_pasajeros():
    """§6.1 Bajadas: la lectura integrada entrega bajadas_viajes = Σ numerobajadas de los viajes válidos (dato <= 300),
    la definición de pasajeros; la huella cambió de forma (VERSION_ESTADO 3): un estado de la versión 2 no se
    compara."""
    motor, conn = motor_falso([])
    F.FuentePostgresSoloLectura(url=URL, motor=motor).leer_incremental(None)
    sql = sentencias(conn)[3]
    assert "SUM(v.numerobajadas) FILTER (WHERE v.valido AND v.numerobajadas <= 300)" in sql
    assert "AS bajadas_viajes" in sql and "pv.numerobajadas" in sql
    assert F.VERSION_ESTADO == 3 and F.DEFINICION_BAJADAS.startswith("numerobajadas")


def test_para_tabla_comparte_la_conexion_y_los_limites():
    motor, conn = motor_falso([])
    base = F.FuentePostgresSoloLectura(url=URL, motor=motor, statement_timeout_ms=1234, solape_min=7, proceso="sobusa",
                                       cancelacion_responde=True)
    otra = base.para_tabla("timbradas_segmentos_anio")
    assert otra.tabla == "timbradas_segmentos_anio" and otra._engine() is motor
    assert (otra.statement_timeout_ms, otra.solape_min, otra.proceso, otra.cancelacion_responde) == (
        1234, 7, "sobusa", True)
    assert F.FuentePostgresSoloLectura(url=URL, motor=motor, proceso="*").para_tabla("rutas").proceso is None
    with pytest.raises(F.OperacionNoPermitida):
        base.para_tabla("progvehiculos_borrar")
    otra.leer_incremental(None)
    assert sentencias(conn)[3].startswith("SELECT * FROM timbradas_segmentos_anio WHERE")


def test_catalogos_de_calidad_traen_la_ruta_de_cada_segmento_y_los_dias(monkeypatch):
    f = F.FuentePostgresSoloLectura(url=URL, motor=mock.MagicMock())
    tablas = {
        "rutas": pd.DataFrame({"idruta": [2, 16], "nombre": ["SILENCIO", "CRA 54"]}),
        "procesos": pd.DataFrame({"proceso": ["sobusa"]}),
        "estacionalidades": pd.DataFrame({"id_estacionalidad": [25, 3]}),
        "novedades_viales": pd.DataFrame({"id_novedad_vial": [1]}),
        "segmentos": pd.DataFrame({"id_segmento": [11, 12], "idruta": [16, 2]}),
        "dias_semana": pd.DataFrame({"id_dia_semana": list(range(1, 8))}),
        "estacionalidades_anio": pd.DataFrame({"id_estacionalidad_anio": [9], "id_estacionalidad": [3],
                                               "fecha_inicio": [date(2025, 12, 8)], "fecha_fin": [date(2025, 12, 8)]}),
    }
    monkeypatch.setattr(f, "leer_contexto", lambda nombre: tablas[nombre])
    cat = f.catalogos_calidad()
    assert cat["segmentos_ruta"] == {11: 16, 12: 2} and cat["dias_semana"] == set(range(1, 8))
    assert cat["dias_estacionalidad"] == {3: frozenset({1})} and cat["dias_estacionalidad_anio"] == {9: frozenset({1})}

    def sin_dias(nombre):
        if nombre == "dias_semana":
            raise RuntimeError("no existe")
        return tablas[nombre]

    monkeypatch.setattr(f, "leer_contexto", sin_dias)
    cat = f.catalogos_calidad()                       # sin dias_semana: lo demás sigue
    assert "dias_semana" not in cat and cat["segmentos"] == {11, 12}


def test_parquet_por_defecto_trae_las_bajadas_empaquetadas():
    from app.servicios import datos

    if datos.bajadas_horaria() is None:
        pytest.skip("sin datos/bajadas_horaria.parquet")
    d, _ = F.FuenteParquet().leer_incremental(None, hasta=date(2023, 1, 2))
    assert "bajadas_viajes" in d.columns and d["bajadas_viajes"].notna().all() and (d["bajadas_viajes"] >= 0).all()
    assert "bajadas_viajes" not in F.FuenteParquet(cargador=demanda_falsa).leer_incremental(None)[0].columns


# ------------------------------------------------------------------ una sola seudonimización (§18)
def test_el_mismo_conductor_tiene_el_mismo_seudonimo_por_los_dos_caminos(monkeypatch):
    """seudonimizar_conductores (ocupación por segmento) y seudonimizar_viajes (alertas de §5.3) delegan en la misma
    función (seudonimos): el mismo conductor da el mismo seudónimo por los dos caminos, aunque llegue como 77, 77.0 o
    «77» y aunque un nulo en otra fila vuelva float la columna; un nulo queda nulo y nunca sale el dato en claro."""
    from app.servicios import alertas

    monkeypatch.setenv("SEUDONIMO_SECRETO", "secreto-de-prueba")
    ocupacion = F.seudonimizar_conductores(pd.DataFrame({"conductor": [77, None, 700001.0, 77.0]}))["conductor"]
    viajes = F.seudonimizar_viajes(pd.DataFrame({"viaje": [1, 2, 3, 4], "idconductor": ["77", None, 700001, 77]}))
    assert ocupacion.tolist() == viajes["conductor"].tolist()
    assert ocupacion.iloc[0] == ocupacion.iloc[3] == alertas.seudonimo_conductor(77) and pd.isna(ocupacion.iloc[1])
    assert ocupacion.iloc[2] == alertas.seudonimo_conductor(700001)
    assert alertas.PATRON_SEUDONIMO.match(ocupacion.iloc[2])
    assert F.seudonimos([77, 77.0, "77", None, float("nan")]) == [alertas.seudonimo_conductor(77)] * 3 + [None, None]
    assert "idconductor" not in viajes.columns
    # sin columna, sin filas o sin lectura no hay nada que seudonimizar (los viajes sin idconductor quedan en nulo)
    sin_conductor = pd.DataFrame({"viaje": [1]})
    assert F.seudonimizar_conductores(sin_conductor) is sin_conductor
    assert F.seudonimizar_conductores(pd.DataFrame({"conductor": []})).empty
    assert F.seudonimizar_viajes(None) is None and F.seudonimizar_viajes(sin_conductor)["conductor"].tolist() == [None]
    monkeypatch.delenv("SEUDONIMO_SECRETO")
    assert F.seudonimos([77, None]) == [None, None]                    # sin secreto: nulo, nunca en claro


# ------------------------------------------------------------------ lectura de los consolidados por proceso
def test_la_lectura_incremental_de_los_consolidados_filtra_el_proceso_en_el_sql():
    """Las tablas con proceso (TABLAS_CON_PROCESO) filtran el de la fuente en el SQL con un parámetro enlazado: las
    filas de otros operadores no se leen. timbradas_segmentos no tiene proceso; con «*» se leen todos."""
    for tabla in F.TABLAS_CON_PROCESO:
        motor, conn = motor_falso([])
        F.FuentePostgresSoloLectura(url=URL, motor=motor, tabla=tabla, proceso="sobusa").leer_incremental(None)
        sql = sentencias(conn)[3]
        assert f"{tabla}.proceso = :proceso" in sql and sql.index(":proceso") < sql.index("ORDER BY"), sql
        assert conn.execute.call_args_list[3].args[1]["proceso"] == "sobusa"
    for tabla, proceso in (("timbradas_segmentos", "sobusa"), ("timbradas_consolidado", "*")):
        motor, conn = motor_falso([])
        f = F.FuentePostgresSoloLectura(url=URL, motor=motor, tabla=tabla, proceso=proceso)
        f.leer_incremental(None)
        assert ":proceso" not in sentencias(conn)[3] and "proceso" not in conn.execute.call_args_list[3].args[1]
        assert not f.filtra_proceso


# ------------------------------------------------------------------ frecuencia vigente (§6.1, §6.2)
class _FuenteRutas:
    """Una fuente cuya tabla rutas trae `filas` (o lanza `error`); cuenta las lecturas."""

    def __init__(self, filas=None, error=None):
        self.filas, self.error, self.lecturas = filas, error, 0
        self._motor = object()

    def _engine(self):
        return self._motor

    def leer_contexto(self, nombre):
        assert nombre == "frecuencias"
        self.lecturas += 1
        if self.error is not None:
            raise self.error
        return pd.DataFrame(self.filas)


def test_frecuencias_de_la_fuente_con_respaldo_y_memoria():
    F.limpiar_frecuencias()
    f = _FuenteRutas([{"idruta": 2, "nombre": "SILENCIO", "frecuenciadespachos": "7"},
                      {"idruta": 16.0, "nombre": "CRA 54", "frecuenciadespachos": None}])
    valores, detalle = F.frecuencias_despacho(f)
    assert valores == {2: "7", 16: None} and "solo lectura" in detalle
    assert F.frecuencias_despacho(f)[0] == valores and f.lecturas == 1             # memoria por motor (TTL)

    class SinColumna(Exception):
        orig = SimpleNamespace(sqlstate=F.SQLSTATE_COLUMNA_INEXISTENTE)       # UndefinedColumn de psycopg

    assert F.frecuencias_despacho(_FuenteRutas(error=SinColumna())) == (
        None, "la tabla rutas de la fuente no trae la columna frecuenciadespachos")
    caida = _FuenteRutas(error=ConnectionError("sin red"))
    assert F.frecuencias_despacho(caida) == (None, "la lectura de la fuente falló (ConnectionError)")
    assert F.frecuencias_despacho(caida)[0] is None and caida.lecturas == 1       # no se reintenta en cada uso
    assert F.frecuencias_despacho(_FuenteRutas([]))[0] is None
    sql = F.CONSULTAS_CONTEXTO["frecuencias"]
    assert F.validar_solo_select(sql) and "frecuenciadespachos" in sql
    F.limpiar_frecuencias()


def test_ruta_info_toma_la_frecuencia_de_la_fuente_en_modo_integrado(monkeypatch):
    """datos.ruta_info: en modo integrado la frecuencia vigente sale de la tabla rutas de la fuente y lo dice
    (frecuencia_fuente); si la fuente no responde, no trae la columna o no trae valor para la ruta, rige la del
    catálogo empaquetado. En modo offline, siempre el catálogo empaquetado."""
    from app.servicios import datos, segmentos

    F.limpiar_frecuencias()
    empaquetada = datos.catalogo_rutas()[0]
    offline = datos.ruta_info(empaquetada["ruta"])
    assert offline["frecuencia_fuente"] == datos.FRECUENCIA_EMPAQUETADA and "modo offline" in offline[
        "frecuencia_fuente_detalle"]
    assert offline["frecuenciadespachos_tabla_rutas"] == empaquetada["frecuenciadespachos_tabla_rutas"]
    fuente = _FuenteRutas([{"idruta": int(empaquetada["idruta"]), "nombre": empaquetada["ruta"],
                            "frecuenciadespachos": "12"}])
    monkeypatch.setattr(segmentos, "fuente_configurada", lambda: True)
    monkeypatch.setattr(segmentos, "fuente", lambda motor=None: fuente)
    integrada = datos.ruta_info(str(empaquetada["idruta"]))
    assert integrada["frecuenciadespachos_tabla_rutas"] == "12"
    assert integrada["frecuencia_fuente"] == datos.FRECUENCIA_DE_LA_FUENTE and integrada["ruta"] == empaquetada["ruta"]
    otra = datos.catalogo_rutas()[1]                                 # la fuente no trae esa ruta: respaldo
    respaldo = datos.ruta_info(otra["ruta"])
    assert respaldo["frecuencia_fuente"] == datos.FRECUENCIA_EMPAQUETADA and "sin valor para la ruta" in respaldo[
        "frecuencia_fuente_detalle"]
    assert respaldo["frecuenciadespachos_tabla_rutas"] == otra["frecuenciadespachos_tabla_rutas"]
    # una ruta sin idruta numérico no tiene con qué buscarse en la fuente: rige su valor empaquetado
    sin_id = datos.frecuencia_vigente({"ruta": "SIN ID", "idruta": "x", "frecuenciadespachos_tabla_rutas": "9"})
    assert sin_id["frecuencia_fuente"] == datos.FRECUENCIA_EMPAQUETADA
    assert sin_id["frecuenciadespachos_tabla_rutas"] == "9" and "sin valor" in sin_id["frecuencia_fuente_detalle"]
    F.limpiar_frecuencias()
    monkeypatch.setattr(segmentos, "fuente", lambda motor=None: _FuenteRutas(error=TimeoutError("lenta")))
    caida = datos.ruta_info(empaquetada["ruta"])
    assert caida["frecuencia_fuente"] == datos.FRECUENCIA_EMPAQUETADA and "falló" in caida["frecuencia_fuente_detalle"]

    def sin_fuente(motor=None):
        raise RuntimeError("no se pudo abrir")

    monkeypatch.setattr(segmentos, "fuente", sin_fuente)
    assert "no se pudo abrir" in datos.ruta_info(empaquetada["ruta"])["frecuencia_fuente_detalle"]
    assert datos.catalogo_rutas()[0] == empaquetada                  # el catálogo empaquetado no cambia
    F.limpiar_frecuencias()
