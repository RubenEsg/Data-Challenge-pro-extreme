"""Pruebas unitarias de app/servicios/catalogos.py (§3.1 Gestión operacional, §3.2, §8.1, §8.3, RF-014, RF-017).

Sin base de datos ni réplica: las fuentes se inyectan (una falsa que registra el SQL) o se leen de archivos temporales.
"""
from __future__ import annotations

from datetime import UTC, date, datetime

import numpy as np
import pandas as pd
import pytest

from app.servicios import catalogos as C
from app.servicios.fuentes import OperacionNoPermitida


@pytest.fixture(autouse=True)
def _aislado(monkeypatch, tmp_path):
    """Cada prueba con su carpeta de exportaciones y su CSV de flota (nunca los datos reales)."""
    monkeypatch.setenv("CATALOGOS_DATOS_DIR", str(tmp_path / "exportaciones"))
    monkeypatch.setenv("CATALOGOS_FLOTA_CSV", str(tmp_path / "flota.csv"))
    monkeypatch.delenv("CATALOGOS_DATABASE_URL", raising=False)
    monkeypatch.setenv("CATALOGOS_FUENTE", "archivos")       # aunque el .env local defina una réplica
    (tmp_path / "exportaciones").mkdir()
    C.limpiar_cache()
    yield
    C.limpiar_cache()


class FuenteFalsa:
    """Fuente inyectada: guarda cada SQL y sus parámetros y responde con DataFrames fijos."""

    nombre = "replica"

    def __init__(self, respuestas: dict[str, pd.DataFrame] | None = None):
        self.respuestas = respuestas or {}
        self.sql: list[tuple[str, dict]] = []

    def consultar(self, sql, parametros=None):
        from app.servicios.fuentes import validar_solo_select

        texto = str(sql)                              # texto o sentencia de SQLAlchemy Core ya compilada
        validar_solo_select(texto)                    # la misma guarda que aplica la fuente real
        self.sql.append((texto, dict(parametros or {})))
        for clave, df in self.respuestas.items():
            if clave in texto:
                return df.copy()
        return pd.DataFrame()

    def consultar_cacheado(self, clave, sql, parametros=None):
        return self.consultar(sql, parametros)

    def columnas(self, tabla):
        return {"idruta", "codigo", "nombre", "proceso", "idempresa", "frecuenciadespachos", "primerdespacho",
                "cap_min_autorizada", "cap_max_autorizada"}


# ---------------------------------------------------------------- §8.1 fechas
def test_a_bogota_sin_zona_es_hora_local_y_con_zona_se_convierte():
    assert C.a_bogota(datetime(2025, 3, 1, 5, 0)).isoformat() == "2025-03-01T05:00:00-05:00"
    assert C.a_bogota(datetime(2025, 3, 1, 10, 0, tzinfo=UTC)).isoformat() == "2025-03-01T05:00:00-05:00"
    assert C.a_bogota(pd.Timestamp("2025-03-01 10:00:00+00:00")).isoformat() == "2025-03-01T05:00:00-05:00"
    assert C.a_bogota(date(2025, 3, 1)).isoformat() == "2025-03-01T00:00:00-05:00"
    for vacio in (None, pd.NaT, float("nan"), ""):
        assert C.a_bogota(vacio) is None


def test_registros_saca_instantes_con_zona_y_nunca_columnas_prohibidas():
    df = pd.DataFrame({"idvehiculo": ["SOBUSA1"], "placa": ["ABC123"], "idconductor": [77],
                       "hora": [pd.Timestamp("2025-01-02 06:30")], "n": [np.int64(3)], "x": [np.nan]})
    fila = C.registros(df, ["idvehiculo", "placa", "idconductor", "hora", "n", "x"])[0]
    assert "placa" not in fila and "idconductor" not in fila
    assert fila["hora"].isoformat() == "2025-01-02T06:30:00-05:00"
    assert fila["n"] == 3 and isinstance(fila["n"], int) and fila["x"] is None


# ---------------------------------------------------------------- geometría
def test_wkt_a_geojson_simplifica_y_conserva_extremos():
    puntos = ", ".join(f"{-74.8 + i * 1e-6:.7f} 10.9" for i in range(101))      # 101 puntos colineales
    geo, original = C.wkt_a_geojson(f"LINESTRING({puntos})")
    assert original == 101
    assert geo["type"] == "LineString" and len(geo["coordinates"]) == 2
    assert geo["coordinates"][0] == [-74.8, 10.9]
    completo, _ = C.wkt_a_geojson(f"LINESTRING({puntos})", tolerancia=0)
    assert len(completo["coordinates"]) == 101
    quiebre, _ = C.wkt_a_geojson("LINESTRING(0 0, 1 1, 2 0)", tolerancia=1e-5)
    assert len(quiebre["coordinates"]) == 3                                         # el vértice real se conserva
    assert C.wkt_a_geojson("POINT(1 2)") == (None, 0) and C.wkt_a_geojson(None) == (None, 0)


# ---------------------------------------------------------------- ajuste local de capacidad (§3.2, contrato)
def test_capacidad_vigente_prioridad_tipologia_ruta_catalogo():
    umbrales = {"capacidad_override.2.TODAS": 45, "capacidad_override.2.BUSETA": 30, "ocupacion_critica": 0.9,
                "capacidad_override.16.TODAS": 0, "capacidad_override.x.TODAS": 40}       # 0 y x se ignoran
    busetas = C.capacidad_vigente("SILENCIO", "buseta", umbrales=umbrales, umbrales_version=9)
    assert (busetas["capacidad"], busetas["fuente"], busetas["clave"]) == (30, "ajuste_local",
                                                                           "capacidad_override.2.BUSETA")
    assert busetas["umbrales_version"] == 9 and busetas["por_tipologia"] == {"BUSETA": 30, "TODAS": 45}
    bus = C.capacidad_vigente(2, "BUS", umbrales=umbrales)
    assert (bus["capacidad"], bus["clave"]) == (45, "capacidad_override.2.TODAS")       # cae a TODAS
    cra54 = C.capacidad_vigente(16, umbrales=umbrales)
    assert (cra54["capacidad"], cra54["fuente"]) == (50, "catalogo")                    # 0 fuera de rango
    with pytest.raises(KeyError):
        C.capacidad_vigente("RUTA-INEXISTENTE", umbrales={})


def test_capacidad_vigente_sin_base_de_resultados_usa_el_catalogo(monkeypatch):
    def _sin_base(_sesion=None):
        raise ConnectionError("sin base")

    monkeypatch.setattr("app.servicios.ejecucion.umbrales_vigentes", _sin_base)
    monkeypatch.setattr("app.db.sesion_contexto", _sin_base)
    r = C.capacidad_vigente("CL 72")
    assert (r["capacidad"], r["fuente"], r["umbrales_version"]) == (50, "catalogo", None)


@pytest.mark.parametrize("malo", ["BUS;DROP", "bus buseta", "", "x" * 33, "ñandú"])
def test_tipologia_se_valida(malo):
    with pytest.raises(ValueError):
        C.clave_capacidad(2, malo if malo else " ")


def test_clave_capacidad_normaliza():
    assert C.clave_capacidad(2) == "capacidad_override.2.TODAS"
    assert C.clave_capacidad("21", " buseta ") == "capacidad_override.21.BUSETA"


# ---------------------------------------------------------------- réplica: guarda de solo lectura
def test_fuente_replica_reusa_la_guarda_de_fuentes_antes_de_conectar():
    class MotorQueFalla:
        def connect(self):  # pragma: no cover - no debe llegar aquí
            raise AssertionError("no debía conectarse")

    f = C.FuenteReplica(url="postgresql://lector@localhost:5434/operacional", motor=MotorQueFalla())
    for sql in ("DELETE FROM rutas", "SELECT 1; DROP TABLE rutas", "UPDATE vehiculos SET placa = 'x'",
                "SELECT * FROM progvehiculos FOR UPDATE", "CREATE TABLE ai_frecuencias.x (a int)"):
        with pytest.raises(OperacionNoPermitida):
            f.consultar(sql)


def test_sin_url_la_replica_no_esta_disponible(monkeypatch):
    monkeypatch.setattr("app.config.obtener_ajustes", lambda: type("A", (), {"fuente_database_url": ""})())
    monkeypatch.delenv("CATALOGOS_FUENTE")
    assert C.modo() == "archivos"
    with pytest.raises(C.CatalogoNoDisponible):
        C.FuenteReplica()
    monkeypatch.setenv("CATALOGOS_DATABASE_URL", "postgresql://lector@localhost:5434/operacional")
    assert C.modo() == "replica"
    monkeypatch.setenv("CATALOGOS_FUENTE", "archivos")
    assert C.modo() == "archivos"
    monkeypatch.setenv("CATALOGOS_FUENTE", "otra")
    with pytest.raises(ValueError):
        C.modo()


def test_programacion_en_replica_solo_select_con_parametros_y_orden_de_lista_blanca():
    filas = pd.DataFrame({"idprogramacion": [10], "idruta": [2], "idvehiculo": ["SOBUSA1"],
                          "fechasalida": [datetime(2025, 3, 3, 6, 0)], "fechainicio": [datetime(2025, 3, 3, 6, 4)],
                          "fechafin": [datetime(2025, 3, 3, 10, 0)], "numeropasajeros": [55], "finalizado": ["S"]})
    f = FuenteFalsa({"count(*)": pd.DataFrame({"total": [1]}), "LIMIT :limite": filas})
    pagina, total, fuente = C.programacion("despachos", idruta=2, desde=date(2025, 3, 3), hasta=date(2025, 3, 3),
                                           idvehiculo="SOBUSA1", retraso_minimo=2, orden="-retraso_min", limite=5,
                                           desplazamiento=0, fuente=f)
    assert (total, fuente) == (1, "replica")
    sql, params = f.sql[-1]
    assert sql.startswith("SELECT ") and "fechainicio IS NOT NULL" in sql and "cancelada = :no_cancelada" in sql
    assert "ORDER BY progvehiculos.fechainicio - progvehiculos.fechasalida DESC NULLS LAST" in sql
    assert "SOBUSA1" not in sql and "2025" not in sql and params["no_cancelada"] == "N"
    conteo, _ = f.sql[-2]
    assert conteo.startswith("SELECT count(*) AS total") and "LIMIT" not in conteo
    assert params["idruta"] == 2 and params["idvehiculo"] == "SOBUSA1" and params["limite"] == 5
    assert params["desde"] == datetime(2025, 3, 3) and params["hasta"] == datetime(2025, 3, 4)
    fila = C.registros(pagina, C.COLUMNAS["despachos"])[0]
    assert fila["retraso_min"] == 4.0 and fila["duracion_min"] == 236.0 and fila["pasajeros"] == 55
    assert fila["salida_real"].isoformat() == "2025-03-03T06:04:00-05:00"
    for malo in ("placa", "-1;DROP TABLE x", "fechasalida"):
        with pytest.raises(C.FiltroInvalido):
            C.programacion("viajes", orden=malo, fuente=f)
    with pytest.raises(C.FiltroInvalido):
        C.programacion("viajes", desde=date(2025, 3, 5), hasta=date(2025, 3, 1), fuente=f)


def _progvehiculos(carpeta):
    filas = []
    for i, (ruta, salida, inicio, cancelada, finalizado) in enumerate([
        (2, "2025-03-03 05:00", "2025-03-03 05:02", "N", "S"),
        (2, "2025-03-03 05:10", None, "S", "N"),
        (2, "2025-03-03 05:20", "2025-03-03 05:31", "N", "S"),
        (16, "2025-03-03 05:00", "2025-03-03 05:00", "N", "N"),
        (2, "2025-03-04 05:00", "2025-03-04 05:05", "N", "S"),
    ]):
        filas.append({"idprogramacion": 100 + i, "idvehiculo": f"SOBUSA{i}", "idconductor": 999, "idruta": ruta,
                      "fechasalida": pd.Timestamp(salida), "fecharegistro": pd.Timestamp(salida) - pd.Timedelta("1h"),
                      "fechainicio": pd.Timestamp(inicio) if inicio else pd.NaT,
                      "fechafin": pd.Timestamp(inicio) + pd.Timedelta("4h") if inicio else pd.NaT,
                      "cancelada": cancelada, "finalizado": finalizado, "numeropasajeros": 40 + i})
    pd.DataFrame(filas).to_parquet(carpeta / "progvehiculos.parquet")


def test_programacion_offline_filtra_ordena_pagina_y_deriva_estado(tmp_path):
    _progvehiculos(tmp_path / "exportaciones")
    viajes, total, fuente = C.programacion("viajes", idruta=2, desde=date(2025, 3, 3), hasta=date(2025, 3, 3))
    assert (total, fuente) == (3, "archivos")
    filas = C.registros(viajes, C.COLUMNAS["viajes"])
    assert [f["estado"] for f in filas] == ["finalizado", "cancelado", "finalizado"]
    assert "idconductor" not in filas[0]
    assert filas[0]["hora_programada"].isoformat() == "2025-03-03T05:00:00-05:00"
    cancelados, n, _ = C.programacion("viajes", estado="cancelado")
    assert n == 1 and int(cancelados["idprogramacion"].iloc[0]) == 101
    despachos, n, _ = C.programacion("despachos", idruta=2, orden="-retraso_min", limite=1)
    assert n == 3 and float(despachos["retraso_min"].iloc[0]) == 11.0                 # 05:20 -> 05:31
    pagina2, n, _ = C.programacion("despachos", idruta=2, orden="salida_real", limite=1, desplazamiento=1)
    assert n == 3 and int(pagina2["idprogramacion"].iloc[0]) == 102
    tardios, n, _ = C.programacion("despachos", retraso_minimo=5)
    assert n == 2 and set(tardios["idprogramacion"]) == {102, 104}


def test_vehiculos_sin_datos_personales_y_con_tipologia_del_reporte_de_flota(tmp_path):
    (tmp_path / "flota.csv").write_text("Placa,Ruta,Modelo,Marca,Clase,Carrocería,Tipo GPS,Sentados,Pie\n"
                                        "AAA111,SILENCIO,2019,CHEVROLET,BUSETA,CERRADO,SONAR,20,10\n",
                                        encoding="utf-8")
    replica = pd.DataFrame({"idvehiculo": ["SOBUSA1", "SOBUSA2"], "placa": ["AAA111", "BBB222"], "idruta": [2, None],
                            "tipovehiculo": [1, 2], "marca": ["CHEVROLET", "AGRALE"], "modelo": ["2019", "2010"],
                            "n_sentados": [20, 30], "n_depie": [10, 0], "capacidad": [0.0, 0.0], "estado": ["Y", "N"],
                            "despacho_habilitado": [True, False]})
    d, fuente = C.vehiculos(FuenteFalsa({"FROM vehiculos": replica}))
    assert fuente == "replica" and not (set(d.columns) & C.COLUMNAS_PROHIBIDAS)
    filas = C.registros(d, C.COLUMNAS["vehiculos"])
    assert filas[0]["tipologia"] == "BUSETA" and filas[0]["carroceria"] == "CERRADO"
    assert filas[0]["capacidad_total"] == 30 and filas[0]["activo"] is True and filas[0]["ruta"] == "SILENCIO"
    assert filas[1]["tipologia"] == "SIN_CLASE" and filas[1]["idruta"] is None and filas[1]["activo"] is False
    assert all("AAA111" not in str(v) for f in filas for v in f.values())


def test_vehiculos_respaldo_flota_csv_sin_placa(tmp_path):
    (tmp_path / "flota.csv").write_text("Placa,Ruta,Modelo,Marca,Clase,Carrocería,Tipo GPS,Sentados,Pie\n"
                                        "AAA111,SILENCIO,2019,CHEVROLET,BUS,CERRADO,SONAR,30,20\n"
                                        "AAA111,SILENCIO,2019,CHEVROLET,BUS,CERRADO,SONAR,30,20\n"
                                        "CCC333,KR50,2015,AGRALE,BUSETA,CERRADO,SONAR,19,8\n", encoding="utf-8")
    d, fuente = C.vehiculos()
    assert fuente == "flota_csv" and len(d) == 2                                       # placa repetida = un bus
    t, _ = C.tipologias()
    assert set(t["tipologia"]) == {"BUS", "BUSETA"}
    assert float(t.loc[t["tipologia"] == "BUS", "capacidad_mediana"].iloc[0]) == 50.0


def test_rutas_con_cap_min_max_si_existen_y_capacidad_vigente():
    tabla = pd.DataFrame({"idruta": [2, 99], "codigo": ["2", "x"], "nombre": ["SILENCIO", "OTRA"],
                          "proceso": ["sobusa", "otro"], "idempresa": [None, 1], "frecuenciadespachos": ["5", "7"],
                          "primerdespacho": ["04:40:00", None], "cap_min_autorizada": [40, None],
                          "cap_max_autorizada": [80, None]})
    d, _ = C.rutas(FuenteFalsa({"FROM rutas": tabla}), umbrales={"capacidad_override.2.TODAS": 42})
    assert list(d["idruta"]) == [2]                                                    # solo rutas del catálogo
    fila = C.registros(d, C.COLUMNAS["rutas"])[0]
    assert (fila["cap_min_autorizada"], fila["cap_max_autorizada"]) == (40, 80)
    assert (fila["capacidad_vigente"], fila["capacidad_fuente"]) == (42, "ajuste_local")
    assert fila["frecuenciadespachos_min"] == 5.0 and fila["tiempo_ciclo_min"] > 0 and fila["flota"] > 0


def test_sin_exportaciones_los_catalogos_grandes_avisan_y_rutas_usa_el_catalogo_de_la_api():
    with pytest.raises(C.CatalogoNoDisponible):
        C.programacion("viajes")
    with pytest.raises(C.CatalogoNoDisponible):
        C.segmentos()
    d, fuente = C.rutas()
    assert fuente == "archivos_api" and len(d) == 3 and d["capacidad_vigente"].eq(50).all()
    # el catálogo empaquetado trae flotadisp_prog como número: sale como texto y cumple el modelo de respuesta
    from app.routers.catalogos import RutaSalida

    filas = [RutaSalida.model_validate(f) for f in C.registros(d, C.COLUMNAS["rutas"])]
    assert {f.idruta: f.flotadisp_prog for f in filas} == {2: "41", 16: "62", 21: "44"}
    assert all(f.frecuenciadespachos == "5" and f.primerdespacho for f in filas)


@pytest.mark.parametrize(("wkt", "n"), [("LINESTRING(1 2, 3 4, 5 6)", 3), ("linestring (1 2,3 4)", 2),
                                        ("POINT(1 2)", 0), ("", 0), (None, 0)])
def test_vertices_wkt_sin_convertir_la_geometria(wkt, n):
    assert C._vertices_wkt(wkt) == n
    if n:
        assert C.wkt_a_geojson(wkt, 0)[1] == n          # mismo conteo que la conversión completa


def test_xlsx_en_modo_write_only_se_lee_igual():
    import io

    df = pd.DataFrame({"idprogramacion": [1, 2], "hora_programada": [pd.Timestamp("2025-01-02 06:00"), None],
                       "retraso_min": [1.5, float("nan")], "finalizado": [True, None]})
    contenido, _, nombre = C.exportar(df, ["idprogramacion", "hora_programada", "retraso_min", "finalizado"], "xlsx",
                                      "despachos")
    hoja = pd.read_excel(io.BytesIO(contenido), sheet_name="despachos")
    assert nombre.endswith(".xlsx") and list(hoja.columns) == ["idprogramacion", "hora_programada", "retraso_min",
                                                               "finalizado"]
    assert hoja["hora_programada"].iloc[0] == "2025-01-02T06:00:00-05:00" and pd.isna(hoja["retraso_min"].iloc[1])


@pytest.mark.parametrize(("valor", "texto"), [(41, "41"), (41.0, "41"), ("62", "62"), (np.int64(44), "44"),
                                              (None, None), (float("nan"), None), (5.5, "5.5")])
def test_texto_de_la_tabla_rutas(valor, texto):
    assert C._texto(valor) == texto


def test_filtrar_paginar_y_exportar():
    df = pd.DataFrame({"idruta": [2, 16, 21], "tipologia": ["BUS", "BUSETA", "BUS"], "activo": [True, False, None],
                       "capacidad_total": [50.0, 30.0, 55.0], "idvehiculo": ["a", "b", "c"]})
    assert list(C.filtrar(df, tipologia="bus")["idruta"]) == [2, 21]
    assert list(C.filtrar(df, activo=True)["idruta"]) == [2]
    with pytest.raises(C.FiltroInvalido):
        C.filtrar(df, placa="x")
    pagina, total = C.paginar(df, "vehiculos", "-capacidad_total", 2, 0)
    assert total == 3 and list(pagina["idruta"]) == [21, 2]
    with pytest.raises(C.FiltroInvalido):
        C.paginar(df, "vehiculos", "placa", 2, 0)
    con_hora = pd.DataFrame({"idprogramacion": [1], "hora_programada": [pd.Timestamp("2025-01-02 06:00")]})
    csv, media, nombre = C.exportar(con_hora, ["idprogramacion", "hora_programada"], "csv", "viajes")
    assert media.startswith("text/csv") and nombre.endswith(".csv")
    assert "2025-01-02T06:00:00-05:00" in csv.decode("utf-8-sig")
    xlsx, media, _ = C.exportar(con_hora, ["idprogramacion", "hora_programada"], "xlsx", "viajes")
    assert xlsx[:2] == b"PK" and "spreadsheetml" in media


# ---------------------------------------------------------------- segmentos: geometría solo de la página (RNF-002)
def _segmentos_parquet(carpeta):
    """Tres segmentos con WKT: el 1 y el 2 de la ruta 2 (un zigzag que se simplifica) y el 3 de la ruta 16 sin
    geometría."""
    zigzag = "LINESTRING(" + ", ".join(f"{-74.8 + i * 1e-4} {10.9 + (i % 2) * 1e-7}" for i in range(40)) + ")"
    pd.DataFrame({"id": [1, 2, 3], "id_config": [1, 1, 2], "idruta": [2, 2, 16], "idrutageo": [1, 1, 2],
                  "nro_segmento": [1, 2, 1], "activo": [True, True, False], "longitud_m": [120.5, 99.0, 300.0],
                  "geom_segmento": [zigzag, "LINESTRING(-74.8 10.9, -74.7 10.9)", None]}).to_parquet(
        carpeta / "rutas_segmentos.parquet")


def test_listado_de_segmentos_sin_geometria_y_geometria_de_la_pagina_offline(tmp_path):
    _segmentos_parquet(tmp_path / "exportaciones")
    d, fuente = C.segmentos_listado()
    assert fuente == "archivos" and "geom_segmento" not in d.columns
    assert list(d["ruta"]) == ["SILENCIO", "SILENCIO", "CRA 54"]
    simplificada = C.geometria_de_pagina([1, 2, 3], "simplificada")
    assert simplificada[1]["vertices_original"] == 40 and 2 <= simplificada[1]["vertices"] < 40
    assert simplificada[2] == {"geometria": {"type": "LineString", "coordinates": [[-74.8, 10.9], [-74.7, 10.9]]},
                               "vertices": 2, "vertices_original": 2}
    assert simplificada[3] == {"geometria": None, "vertices": 0, "vertices_original": 0}
    assert C.geometria_de_pagina([1], "ninguna") == {1: {"geometria": None, "vertices": 0, "vertices_original": 40}}
    completa = C.geometria_de_pagina([1, 2], "completa")
    assert completa[1]["vertices"] == completa[1]["vertices_original"] == 40 and 3 not in completa
    assert C.geometria_de_pagina([], "simplificada") == {}
    with pytest.raises(C.FiltroInvalido):
        C.geometria_de_pagina([1], "otra")


class _ReplicaDeSegmentos(C.FuenteReplica):
    """FuenteReplica con su caché real sobre una réplica falsa de n segmentos: consultar responde solo los ids
    pedidos (como el WHERE id = ANY) y guarda cada SQL validado como SELECT."""

    def __init__(self, n: int):
        super().__init__(motor=object())                  # nunca se conecta: consultar está sustituida
        self.n, self.sql = n, []

    def consultar(self, sql, parametros=None):
        from app.servicios.fuentes import validar_solo_select

        validar_solo_select(sql)
        self.sql.append((sql, dict(parametros or {})))
        ids = [i for i in (parametros or {}).get("ids", []) if 1 <= i <= self.n]
        geo = '{"type": "LineString", "coordinates": [[-74.8, 10.9], [-74.7, 10.9]]}'
        return pd.DataFrame({"id": ids, "vertices_original": [2500] * len(ids), "geojson": [geo] * len(ids)})


def test_la_geometria_de_las_paginas_se_guarda_por_segmento_con_memoria_acotada(monkeypatch):
    """Mil páginas distintas (desplazamientos y tamaños al azar) de 40 segmentos: la memoria guarda a lo sumo un
    registro por segmento y modo, nunca uno por página (antes cada página nueva era una entrada que no se borraba), y
    a la réplica solo se le piden los segmentos que faltan."""
    import random

    f, rng = _ReplicaDeSegmentos(40), random.Random(7)
    for _ in range(1000):
        inicio = rng.randint(1, 40)
        ids = list(range(inicio, min(41, inicio + rng.randint(1, 15))))
        pagina = C.geometria_de_pagina(ids, rng.choice(["simplificada", "ninguna"]), f)
        assert sorted(pagina) == ids and all(pagina[i]["vertices_original"] == 2500 for i in ids)
    assert len(C._geometrias) <= 2 * 40 and len(C._cache) == 0
    pedidos = len(f.sql)
    assert C.geometria_de_pagina([3, 4, 5], "simplificada", f)[4]["vertices"] == 2 and len(f.sql) == pedidos
    monkeypatch.setenv("CATALOGOS_CACHE_S", "0")                # vencida: se vuelve a leer, y solo esos ids
    C.geometria_de_pagina([3, 4, 5], "simplificada", f)
    assert len(f.sql) == pedidos + 1 and f.sql[-1][1]["ids"] == [3, 4, 5]


def test_la_geometria_del_parquet_no_se_relee_para_los_segmentos_ya_vistos(tmp_path, monkeypatch):
    _segmentos_parquet(tmp_path / "exportaciones")
    lecturas = []
    original = C._wkt_de
    monkeypatch.setattr(C, "_wkt_de", lambda ids: lecturas.append(list(ids)) or original(ids))
    primera = C.geometria_de_pagina([1, 2], "simplificada")
    assert C.geometria_de_pagina([2, 1], "simplificada") == primera and lecturas == [[1, 2]]
    C.geometria_de_pagina([2, 3], "simplificada")
    assert lecturas == [[1, 2], [3]]                            # del archivo, solo el segmento que faltaba


def test_geometria_de_la_pagina_desde_la_replica_solo_pide_esos_ids():
    geo = '{"type": "LineString", "coordinates": [[-74.8, 10.9], [-74.7, 10.9]]}'
    f = FuenteFalsa({"ST_AsGeoJSON(ST_Simplify": pd.DataFrame({"id": [7], "vertices_original": [2503],
                                                                "geojson": [geo]}),
                     "AS vertices_original FROM": pd.DataFrame({"id": [7], "vertices_original": [2503]}),
                     "SELECT id, id_config": pd.DataFrame({"id": [7], "id_config": [1], "idruta": [2],
                                                           "idrutageo": [1], "nro_segmento": [1], "activo": [True],
                                                           "longitud_m": ["10.5"]})})
    d, fuente = C.segmentos_listado(f, idruta=2)
    assert fuente == "replica" and d["longitud_m"].tolist() == [10.5] and "ST_" not in f.sql[-1][0]
    assert f.sql[-1][1] == {"idruta": 2}
    pagina = C.geometria_de_pagina([7], "simplificada", f)
    assert pagina == {7: {"geometria": {"type": "LineString", "coordinates": [[-74.8, 10.9], [-74.7, 10.9]]},
                          "vertices": 2, "vertices_original": 2503}}
    assert f.sql[-1][1] == {"ids": [7], "tol": C.TOLERANCIA_SIMPLIFICACION}
    assert C.geometria_de_pagina([7], "ninguna", f) == {7: {"geometria": None, "vertices": 0,
                                                            "vertices_original": 2503}}
