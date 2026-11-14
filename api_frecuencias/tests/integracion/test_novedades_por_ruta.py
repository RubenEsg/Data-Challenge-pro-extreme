"""§11.2 «Las novedades viales se cruzan por fecha, rango horario y ruta» leyendo las tablas de Extreme en solo lectura.

Las tablas de novedades de Extreme (novedades_viales, novedades_viales_fecha y novedades_viales_ruta, con las
estacionalidades que dan los festivos) se crean en un esquema aparte de la base LOCAL de pruebas con filas
sintéticas, y se leen con FuentePostgresSoloLectura (READ ONLY, statement_timeout, ROLLBACK), igual que la réplica:
con filas en novedades_viales_ruta, cada novedad afecta solo a sus rutas en el contexto y en las variables del modelo;
sin filas, cada novedad es de todas las rutas (el caso de Sobusa, que tests/replica/test_integrado.py prueba con la
réplica real).
"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest
from sqlalchemy import create_engine, text

from tests.evidencia import guardar_evidencia

ESQUEMA = "fuente_novedades_prueba"
DIA = date(2024, 3, 9)
DDL = f"""
CREATE TABLE {ESQUEMA}.novedades_viales (id_novedad_vial bigint PRIMARY KEY, proceso text, novedad text, nombre text,
                                         descripcion text);
CREATE TABLE {ESQUEMA}.novedades_viales_fecha (id_novedad_vial_fecha bigint PRIMARY KEY, proceso text,
    id_novedad_vial bigint REFERENCES {ESQUEMA}.novedades_viales, fecha date, hora_inicio time, hora_fin time,
    potencial_efecto text, porcentaje_impacto numeric);
CREATE TABLE {ESQUEMA}.novedades_viales_ruta (id_novedad_vial_ruta bigint PRIMARY KEY,
    id_novedad_vial_fecha bigint REFERENCES {ESQUEMA}.novedades_viales_fecha, id_ruta bigint);
CREATE TABLE {ESQUEMA}.estacionalidades (id_estacionalidad bigint PRIMARY KEY, proceso text, estacionalidad text,
                                         nombre text, descripcion text);
CREATE TABLE {ESQUEMA}.estacionalidades_anio (id_estacionalidad_anio bigint PRIMARY KEY, proceso text,
    id_estacionalidad bigint, ano bigint, fecha_inicio date, fecha_fin date);
INSERT INTO {ESQUEMA}.novedades_viales VALUES (1, 'sobusa', 'CARNAVAL', 'Carnaval', ''),
                                              (2, 'sobusa', 'CIERRE', 'Cierre de vía', '');
INSERT INTO {ESQUEMA}.novedades_viales_fecha VALUES
    (11, 'sobusa', 1, '{DIA}', '06:00', '08:30', 'SUBE', 30),
    (12, 'sobusa', 2, '{DIA}', '07:00', '09:00', 'BAJA', 80);
INSERT INTO {ESQUEMA}.estacionalidades VALUES (5, 'sobusa', 'FESTIVO_NACIONAL', 'Festivo', '');
INSERT INTO {ESQUEMA}.estacionalidades_anio VALUES (1, 'sobusa', 5, 2024, '2024-03-25', '2024-03-25');
"""


@pytest.fixture(scope="module")
def fuente(migrada):
    """Las tablas de novedades de Extreme en un esquema aparte de la base de pruebas (se borra al terminar), leídas
    con el lector de solo lectura de la API."""
    from app.servicios.fuentes import FuentePostgresSoloLectura

    admin = create_engine(migrada)
    with admin.begin() as c:
        c.execute(text(f"DROP SCHEMA IF EXISTS {ESQUEMA} CASCADE"))
        c.execute(text(f"CREATE SCHEMA {ESQUEMA}"))
        c.execute(text(DDL))
    motor = create_engine(migrada, connect_args={"options": f"-c search_path={ESQUEMA}"})
    yield admin, FuentePostgresSoloLectura(motor=motor, tabla="novedades_viales_fecha")
    motor.dispose()
    with admin.begin() as c:
        c.execute(text(f"DROP SCHEMA IF EXISTS {ESQUEMA} CASCADE"))
    admin.dispose()


def _leer(f) -> dict[str, pd.DataFrame]:
    """Las cuatro tablas como las lee scripts/replica_contexto.py (FuentePostgresSoloLectura.leer_contexto)."""
    return {nombre: f.leer_contexto(nombre) for nombre in ("novedades_viales_fecha", "novedades_viales_ruta",
                                                            "estacionalidades_anio", "estacionalidades")}


def _contexto(tablas):
    from scripts.preparar_datos_api import contexto_y_novedades_por_ruta

    ea = tablas["estacionalidades_anio"][["id_estacionalidad_anio", "proceso", "id_estacionalidad", "ano",
                                          "fecha_inicio", "fecha_fin"]]
    return contexto_y_novedades_por_ruta(tablas["novedades_viales_fecha"], tablas["novedades_viales_ruta"], ea,
                                         tablas["estacionalidades"], "2024-01-01", "2024-03-31")


def _serie() -> pd.DataFrame:
    inicio = date(2024, 1, 1)
    return pd.DataFrame([{"ruta": ruta, "fecha": inicio + timedelta(days=i), "hora": h, "pasajeros": 50.0 + h,
                          "excluido": 0, "festivo": 0, "tipo_dia": 0}
                         for i in range(80) for ruta in ("SILENCIO", "CRA 54", "CL 72") for h in range(5, 11)])


def _variables(tablas, monkeypatch) -> pd.DataFrame:
    """La tabla de variables del modelo como la arma la API (inferencia.variables_de) con ese contexto."""
    from app.servicios import datos, inferencia

    ctx, por_ruta, _info = _contexto(tablas)
    monkeypatch.setattr(datos, "novedades_por_ruta", lambda: por_ruta)
    return inferencia.variables_de(_serie(), contexto=ctx)


def _nov(tabla, ruta, hora) -> float:
    fila = tabla[(tabla["ruta"] == ruta) & (tabla["fecha"] == DIA) & (tabla["hora"] == hora)]
    return float(fila["nov_impacto"].iloc[0])


def _por_hora(tabla) -> dict:
    """nov_impacto de cada ruta en las horas 6 a 9 del día de las novedades (para la evidencia)."""
    return {ruta: {h: _nov(tabla, ruta, h) for h in range(6, 10)} for ruta in ("SILENCIO", "CRA 54", "CL 72")}


EVIDENCIA: dict = {"prueba": "tests/integracion/test_novedades_por_ruta.py",
                   "fuente": "tablas de novedades de Extreme con filas sintéticas en un esquema de la base local, "
                             "leídas con FuentePostgresSoloLectura (READ ONLY)",
                   "novedades": {"11": "Carnaval, 06:00-08:30, SUBE 30 %",
                                 "12": "Cierre de vía, 07:00-09:00, BAJA 80 %"}}


def test_con_filas_en_novedades_viales_ruta_cada_novedad_afecta_solo_a_sus_rutas(fuente, monkeypatch):
    admin, f = fuente
    with admin.begin() as c:
        c.execute(text(f"INSERT INTO {ESQUEMA}.novedades_viales_ruta VALUES (1, 12, 21)"))     # el cierre: CL 72
    try:
        tablas = _leer(f)
        assert len(tablas["novedades_viales_ruta"]) == 1
        nov = f.novedades_viales()
        assert dict(zip(nov["id_novedad_vial_fecha"], nov["rutas"], strict=True)) == {11: [], 12: [21]}
        ctx, por_ruta, info = _contexto(tablas)
        assert info["novedades_por_ruta"] == 1 and info["novedades_todas_las_rutas"] == 1
        assert set(por_ruta["ruta"]) == {"CL 72"} and sorted(por_ruta["hora"]) == [7, 8, 9]
        t = _variables(tablas, monkeypatch)
        assert _nov(t, "CL 72", 9) == 80 and _nov(t, "CL 72", 7) == 80          # el cierre, en su ruta
        assert _nov(t, "SILENCIO", 9) == 0 and _nov(t, "CRA 54", 9) == 0         # no en las demás
        assert _nov(t, "SILENCIO", 7) == 30 and _nov(t, "CRA 54", 6) == 30       # el Carnaval, en todas
        EVIDENCIA["con_novedades_viales_ruta"] = {"filas": [{"id_novedad_vial_fecha": 12, "id_ruta": 21}],
                                                  "resumen": info, "nov_impacto_por_ruta_y_hora": _por_hora(t)}
    finally:
        with admin.begin() as c:
            c.execute(text(f"DELETE FROM {ESQUEMA}.novedades_viales_ruta"))


def test_sin_filas_en_novedades_viales_ruta_cada_novedad_es_de_todas_las_rutas(fuente, monkeypatch):
    _admin, f = fuente
    tablas = _leer(f)
    assert tablas["novedades_viales_ruta"].empty
    ctx, por_ruta, info = _contexto(tablas)
    assert por_ruta.empty and info["novedades_todas_las_rutas"] == 2 and info["filas_novedades_viales_ruta"] == 0
    t = _variables(tablas, monkeypatch)
    for ruta in ("SILENCIO", "CRA 54", "CL 72"):
        assert _nov(t, ruta, 9) == 80 and _nov(t, ruta, 7) == 80 and _nov(t, ruta, 6) == 30
    EVIDENCIA["sin_filas_en_novedades_viales_ruta"] = {"resumen": info, "nov_impacto_por_ruta_y_hora": _por_hora(t)}
    guardar_evidencia("datos/novedades_por_ruta.json", EVIDENCIA)
