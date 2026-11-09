"""Pruebas de las fuentes incrementales. La fuente PostgreSQL se prueba SOLO con unittest.mock: nunca se conecta a una
base real (y menos a la base compartida del reto)."""
from datetime import UTC, date, datetime
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
    f = F.FuentePostgresSoloLectura(url="postgresql+psycopg://lector@host-falso/db", motor=motor, statement_timeout_ms=1500)
    marca = datetime(2025, 3, 10, tzinfo=UTC)
    d, nueva = f.leer_incremental(marca)
    s = sentencias(conn)
    assert s[0] == "SET TRANSACTION READ ONLY"
    assert s[1] == "SET LOCAL statement_timeout = 1500"
    assert s[2].startswith("SELECT * FROM timbradas_consolidado WHERE")
    assert "ultima_actualizacion > :marca" in s[2] and "ORDER BY" in s[2] and "LIMIT" in s[2]
    assert conn.execute.call_args_list[2].args[1]["marca"] == marca
    conn.rollback.assert_called_once()
    conn.commit.assert_not_called()
    assert len(d) == 2 and pd.Timestamp(nueva) == pd.Timestamp("2025-03-10 13:00", tz="UTC")


def test_postgres_con_hasta_y_sin_resultados_conserva_la_marca():
    motor, conn = motor_falso([])
    f = F.FuentePostgresSoloLectura(url="postgresql+psycopg://x@y/z", motor=motor)
    marca = datetime(2025, 3, 10, tzinfo=UTC)
    d, nueva = f.leer_incremental(marca, hasta=date(2025, 3, 11))
    assert len(d) == 0 and nueva == marca
    assert "ultima_actualizacion < :hasta" in sentencias(conn)[2]
    assert conn.execute.call_args_list[2].args[1]["hasta"].isoformat().startswith("2025-03-12T00:00:00-05:00")


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
