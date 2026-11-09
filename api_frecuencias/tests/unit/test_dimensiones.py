"""Dimensiones de §8.3 (app/servicios/dimensiones.py): idruta, idempresa, idproceso, día ISO y estacionalidad."""
from __future__ import annotations

from datetime import UTC, date, datetime

import pandas as pd
import pytest

from app.servicios import dimensiones as dim


@pytest.fixture(autouse=True)
def _sin_cache(monkeypatch):
    dim.limpiar_cache()
    yield
    dim.limpiar_cache()


@pytest.fixture
def catalogos_falsos(monkeypatch):
    """Tabla rutas y Procesos como los exporta Extreme para Sobusa (proceso de texto, idempresa nulo)."""
    from app.servicios import catalogos

    rutas = pd.DataFrame({"idruta": [2, 16, 21], "proceso": ["sobusa"] * 3, "idempresa": [None, None, None]})
    procesos = pd.DataFrame({"proceso": ["sobusa"], "nombre": ["SOBUSA"]})
    vigencias = pd.DataFrame({"proceso": ["cootransoriente", "sobusa", "sobusa"], "id_estacionalidad": [1, 7, 8],
                              "fecha_inicio": [date(2025, 11, 3), date(2026, 2, 1), date(2026, 2, 14)],
                              "fecha_fin": [date(2025, 11, 3), date(2026, 2, 28), date(2026, 2, 17)]})
    monkeypatch.setattr(catalogos, "rutas_tabla", lambda fuente=None: (rutas, "prueba"))
    monkeypatch.setattr(catalogos, "procesos", lambda fuente=None: (procesos, "prueba"))
    monkeypatch.setattr(catalogos, "_fuente", lambda fuente=None: None)
    monkeypatch.setattr(catalogos, "_parquet", lambda nombre, columnas: vigencias)
    return rutas


def test_idruta_del_catalogo_empaquetado_y_dia_iso(catalogos_falsos):
    d = dim.dimensiones("CRA 54", date(2025, 11, 9))          # domingo
    assert d == {"idruta": 16, "idempresa": None, "idproceso": "sobusa", "id_dia_semana": 7,
                 "id_estacionalidad": None}
    assert set(d) == set(dim.CAMPOS)
    assert dim.dimensiones("SILENCIO", date(2025, 11, 10))["id_dia_semana"] == 1     # lunes
    assert dim.idruta("CL 72") == 21 and dim.idruta("2") == 2 and dim.idruta("cra 54") == 16


def test_el_instante_se_lleva_a_bogota_antes_del_dia(catalogos_falsos):
    # 2025-11-10 03:00 UTC es todavía el domingo 9 en Bogotá (UTC-5)
    assert dim.dimensiones("SILENCIO", datetime(2025, 11, 10, 3, 0, tzinfo=UTC))["id_dia_semana"] == 7
    assert dim.dimensiones("SILENCIO", "2025-11-10T06:00:00-05:00")["id_dia_semana"] == 1
    assert dim.dimensiones("SILENCIO", None)["id_dia_semana"] is None


def test_el_proceso_se_guarda_como_texto_sin_cambiar_su_semantica(catalogos_falsos):
    """En Extreme la llave de "Procesos" es texto («sobusa»): convertirla a número la perdería."""
    assert dim.dimensiones("CL 72", date(2025, 8, 31))["idproceso"] == "sobusa"
    assert dim.empresa("CL 72") == "SOBUSA"


def test_estacionalidad_vigente_del_proceso_de_la_ruta(catalogos_falsos):
    # la vigencia de otro proceso no cuenta; si se solapan gana la más corta (los días centrales del carnaval)
    assert dim.dimensiones("CRA 54", date(2025, 11, 3))["id_estacionalidad"] is None
    assert dim.dimensiones("CRA 54", date(2026, 2, 10))["id_estacionalidad"] == 7
    assert dim.dimensiones("CRA 54", date(2026, 2, 15))["id_estacionalidad"] == 8
    assert dim.dimensiones("CRA 54", date(2026, 2, 15), id_estacionalidad=3)["id_estacionalidad"] == 3


def test_sin_fuentes_los_valores_quedan_nulos_y_no_se_inventan(monkeypatch):
    from app.servicios import catalogos

    def falla(*a, **k):
        raise catalogos.CatalogoNoDisponible("sin réplica ni exportaciones")

    monkeypatch.setattr(catalogos, "rutas_tabla", falla)
    monkeypatch.setattr(catalogos, "procesos", falla)
    monkeypatch.setattr(catalogos, "_fuente", lambda fuente=None: None)
    monkeypatch.setattr(catalogos, "_parquet", falla)
    d = dim.dimensiones("SILENCIO", date(2025, 11, 9))
    # sin réplica ni exportaciones solo vale el catálogo empaquetado (datos/catalogo_rutas.json): trae idruta, el
    # proceso «sobusa» y la empresa «SOBUSA», pero no idempresa (Extreme no lo trae para Sobusa) ni estacionalidad
    assert d["idruta"] == 2 and d["idproceso"] == "sobusa" and d["id_estacionalidad"] is None
    assert d["idempresa"] is None
    assert dim.empresa("SILENCIO") == "SOBUSA"
    desconocida = dim.dimensiones("RUTA X", date(2025, 11, 9))
    assert desconocida["idruta"] is None and desconocida["id_dia_semana"] == 7
    assert desconocida["idproceso"] is None and desconocida["idempresa"] is None


def test_idempresa_nunca_es_un_texto(monkeypatch):
    """idempresa es entero o nulo: un catálogo que trajera el proceso o el nombre en ese campo no lo llena."""
    from app.servicios import catalogos, datos

    def falla(*a, **k):
        raise catalogos.CatalogoNoDisponible("sin réplica ni exportaciones")

    catalogo = [{"ruta": "SILENCIO", "idruta": 2, "proceso": "sobusa", "empresa": "SOBUSA", "idempresa": "sobusa"},
                {"ruta": "CL 72", "idruta": 21, "proceso": "sobusa", "idempresa": "7"}]
    monkeypatch.setattr(datos, "catalogo_rutas", lambda: catalogo)
    monkeypatch.setattr(catalogos, "rutas_tabla", falla)
    monkeypatch.setattr(catalogos, "procesos", falla)
    monkeypatch.setattr(catalogos, "_fuente", lambda fuente=None: None)
    monkeypatch.setattr(catalogos, "_parquet", falla)
    assert dim.dimensiones("SILENCIO", date(2025, 11, 9))["idempresa"] is None
    assert dim.dimensiones("CL 72", date(2025, 11, 9))["idempresa"] == 7
    lote = pd.DataFrame({"ruta": ["SILENCIO"], "fecha": [date(2025, 11, 9)], "idempresa": ["SOBUSA"]})
    assert dim.columnas_lote(lote)["idempresa"].tolist() == [None]


def test_el_lote_integrado_trae_proceso_empresa_y_estacionalidad(catalogos_falsos):
    """En modo integrado demanda_segmentos ya trae proceso, idempresa e id_estacionalidad por franja: mandan sobre
    el catálogo; lo que el lote no trae (filas con nulos) se completa como siempre."""
    lote = pd.DataFrame({"ruta": ["CRA 54", "CRA 54", "CL 72"],
                         "fecha": [date(2026, 2, 10), date(2026, 2, 10), date(2026, 2, 15)],
                         "proceso": ["sobusa", "sobusa", None], "idempresa": [3, None, None],
                         "id_estacionalidad": [None, 9, None]})
    cols = dim.columnas_lote(lote)
    assert cols["idproceso"].tolist() == ["sobusa"] * 3
    assert cols["idempresa"].tolist() == [3, None, None]
    # fila 1: sin estacionalidad en el lote, la vigente del proceso (7); fila 2: la del lote (9); fila 3: la más corta
    assert cols["id_estacionalidad"].tolist() == [7, 9, 8]
    assert cols["idruta"].tolist() == [16, 16, 21] and cols["id_dia_semana"].tolist() == [2, 2, 7]


def test_columnas_de_un_lote(catalogos_falsos):
    lote = pd.DataFrame({"ruta": ["CRA 54", "CRA 54", "CL 72"], "fecha": [date(2025, 8, 30)] * 2 + [date(2025, 8, 31)],
                         "hora": [5, 6, 5]})
    cols = dim.columnas_lote(lote)
    assert list(cols.columns) == list(dim.CAMPOS) and list(cols.index) == list(lote.index)
    assert cols["idruta"].tolist() == [16, 16, 21] and cols["id_dia_semana"].tolist() == [6, 6, 7]
    assert cols["idproceso"].tolist() == ["sobusa"] * 3


def test_la_migracion_0006_usa_los_idruta_del_catalogo():
    """Los valores que rellena la 0006 en las filas existentes coinciden con el catálogo empaquetado."""
    import importlib.util
    from pathlib import Path

    from app.servicios import datos

    archivo = Path(__file__).resolve().parents[2] / "alembic" / "versions" / "0006_dimensiones_calidad_respuesta.py"
    spec = importlib.util.spec_from_file_location("m0006", archivo)
    m0006 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m0006)
    assert {r: v[0] for r, v in m0006.RUTAS_0006.items()} == {r["ruta"]: r["idruta"] for r in datos.catalogo_rutas()}
