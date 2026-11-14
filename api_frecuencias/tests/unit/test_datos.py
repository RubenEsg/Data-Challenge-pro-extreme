"""Pruebas de app/servicios/datos.py: contrato de la serie horaria y del catálogo de rutas."""

from datetime import date, datetime, time

import pandas as pd
import pytest

from app.servicios import datos

pytestmark = pytest.mark.skipif(
    not (datos.carpeta_datos() / "demanda_horaria.parquet").exists(),
    reason="faltan los datos empaquetados (scripts/preparar_datos_api.py)",
)


def test_demanda_horaria_cumple_contrato():
    d = datos.demanda_horaria()
    assert list(d.columns[:6]) == datos.COLUMNAS_CONTRATO
    assert set(d["ruta"].unique()) == {"SILENCIO", "CRA 54", "CL 72"}
    assert d["hora"].between(4, 20).all()
    assert isinstance(d["fecha"].iloc[0], date)
    assert not d.duplicated(["ruta", "fecha", "hora"]).any()
    assert (d["pasajeros"].dropna() >= 0).all()
    assert str(d["ultima_actualizacion"].dt.tz) == "America/Bogota"


def test_ultima_actualizacion_es_fin_del_dia():
    d = datos.demanda_horaria(desde=date(2025, 3, 3), hasta=date(2025, 3, 3))
    esperado = pd.Timestamp(datetime.combine(date(2025, 3, 3), time(23, 59, 59))).tz_localize("America/Bogota")
    assert (d["ultima_actualizacion"] == esperado).all()


def test_filtros_por_fecha_y_ruta():
    d = datos.demanda_horaria(desde=date(2025, 1, 6), hasta=date(2025, 1, 12), rutas=["CL 72"])
    assert set(d["ruta"]) == {"CL 72"}
    assert d["fecha"].min() >= date(2025, 1, 6) and d["fecha"].max() <= date(2025, 1, 12)
    assert len(d) == 7 * 17


def test_demanda_devuelve_copia():
    d = datos.demanda_horaria(desde=date(2025, 1, 6), hasta=date(2025, 1, 6))
    d["pasajeros"] = -1
    assert (datos.demanda_horaria(desde=date(2025, 1, 6), hasta=date(2025, 1, 6))["pasajeros"] >= 0).all()


def test_catalogo_rutas():
    cat = datos.catalogo_rutas()
    assert {c["ruta"] for c in cat} == {"SILENCIO", "CRA 54", "CL 72"}
    for c in cat:
        for campo in ("ruta", "idruta", "capacidad", "tiempo_ciclo_min", "flota", "frecuencia_actual_min"):
            assert campo in c
        assert c["capacidad"] == 50
        assert c["tiempo_ciclo_min"] > 0 and c["flota"] > 0 and c["frecuencia_actual_min"] > 0
    assert datos.ruta_info("16")["ruta"] == "CRA 54"
    with pytest.raises(KeyError):
        datos.ruta_info("NO EXISTE")


def test_parametros_operativos_por_hora():
    p = datos.parametros_operativos("SILENCIO", "Laboral")
    assert len(p) > 0
    assert {"tiempo_ciclo_min", "flota", "intervalo_programado_min", "nmin", "nmax"} <= set(p.columns)


def test_contexto_operacional_y_perfil_intrahorario():
    c = datos.contexto_operacional()
    assert list(c.columns) == datos.COLUMNAS_CONTEXTO
    if len(c):
        assert (c["nov_impacto"] >= 0).all() and c["hora"].between(4, 20).all()
        assert c["festivo_oficial"].isin([0, 1]).all()
        assert not c.duplicated(["fecha", "hora"]).any()
    p = datos.perfil_intrahorario()
    if len(p):
        assert p["fraccion_primera_media"].between(0.05, 0.95).all()
        assert set(p["tipo_dia"].unique()) <= {0, 1, 2}


def test_archivos_opcionales_faltantes_dan_tablas_vacias(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    assert len(datos.contexto_operacional()) == 0
    assert list(datos.contexto_operacional().columns) == datos.COLUMNAS_CONTEXTO
    assert len(datos.perfil_intrahorario()) == 0
    assert datos.clima_diario() is None


def test_bajadas_empaquetadas_con_la_grilla_de_la_serie():
    """§6.1 Bajadas: datos/bajadas_horaria.parquet tiene una fila por (ruta, fecha, hora) de la serie y con_bajadas
    la agrega sin cambiar las demás columnas; una serie que ya la trae no se toca."""
    b = datos.bajadas_horaria()
    if b is None:
        pytest.skip("sin datos/bajadas_horaria.parquet")
    serie = datos.demanda_horaria()
    assert len(b) == len(serie) and not b.duplicated(["ruta", "fecha", "hora"]).any()
    assert (b["bajadas_viajes"] >= 0).all() and b["bajadas_viajes"].sum() > 0
    tramo = datos.demanda_horaria(desde=date(2025, 3, 3), hasta=date(2025, 3, 3))
    con = datos.con_bajadas(tramo)
    assert len(con) == len(tramo) and con["bajadas_viajes"].notna().all()
    assert con.drop(columns=["bajadas_viajes"]).reset_index(drop=True).equals(tramo.reset_index(drop=True))
    assert datos.con_bajadas(con) is con and datos.con_bajadas(tramo.iloc[:0]).empty


def test_sin_el_archivo_de_bajadas_la_serie_queda_igual(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    assert datos.bajadas_horaria() is None
    serie = pd.DataFrame({"ruta": ["CL 72"], "fecha": [date(2025, 1, 1)], "hora": [6], "pasajeros": [1.0]})
    assert datos.con_bajadas(serie) is serie
