"""scripts/replica_lectura_consolidados.py (§6.1, §8.3, §18 «Consulta pesada»; H4, H7, H12): lo que el ciclo consulta
por tabla consolidada antes (lectura sin filtrar el proceso + count(*)) y ahora (lectura del proceso en el SQL, nada
más), y el volumen de otro operador en una tabla TEMPORAL dentro de la transacción que se revierte. Sin base: la
conexión es un doble que registra las sentencias."""
from __future__ import annotations

import re
from datetime import datetime

import pytest
from sqlalchemy import create_engine

from scripts import replica_indices_candidatos as ric
from scripts import replica_lectura_consolidados as L

MARCA = datetime(2026, 8, 13, 22, 0, tzinfo=ric.ZONA)
COLUMNAS = ["id_timbrada_segmentos_consolidado", "id_segmento", "proceso", "id_ruta", "id_dia_semana",
            "id_estacionalidad", "hora", "hora_inicio", "hora_fin", "subidas", "bajadas", "pasajeros", "nro_viajes",
            "promedio_subidas", "promedio_bajadas", "promedio_pasajeros", "ultima_actualizacion"]


@pytest.fixture(scope="module")
def motor():
    return create_engine("postgresql+psycopg://lector_ia@localhost/x")       # solo el dialecto: no conecta


def _plan(filas: int) -> list[dict]:
    return [{"Plan": {"Node Type": "Limit", "Actual Rows": filas, "Plans": [
        {"Node Type": "Seq Scan", "Relation Name": L.TABLA_SINTETICA, "Shared Hit Blocks": 3, "Shared Read Blocks": 0,
         "Rows Removed by Filter": 0}]}, "Execution Time": 2.5, "Planning Time": 0.1}]


class _Resultado:
    def __init__(self, filas=None, valor=None):
        self.filas, self.valor = filas or [], valor

    def scalar(self):
        return self.valor

    def fetchall(self):
        return self.filas

    def keys(self):
        return COLUMNAS


class _Conexion:
    """Registra las sentencias; la lectura sin filtrar el proceso trae 3 filas de otro operador con el mismo sello."""

    def __init__(self):
        self.sentencias: list[str] = []

    def exec_driver_sql(self, sql, params=None):
        self.sentencias.append(sql)
        ajena = "proceso = %(proceso)s" not in sql
        if sql.startswith("EXPLAIN"):
            return _Resultado(valor=_plan(3 if ajena and "count(*)" not in sql else 0))
        if sql.startswith("SELECT *"):
            filas = [(i, i, L.OTRO_PROCESO, 9001, 1, 1, "07:00:00", "07:00:00", "08:00:00", 10, 9, 1, 4, 2.5, 2.25,
                      7.5, MARCA.replace(tzinfo=None)) for i in range(3)] if ajena else []
            return _Resultado(filas)
        return _Resultado()


def test_antes_lee_sin_filtrar_y_cuenta_ahora_solo_lee_el_proceso(motor):
    antes, ahora = L.consultas_de_la_tabla(motor, "timbradas_segmentos_consolidado", MARCA)
    lectura, conteo = antes
    assert "proceso" not in lectura.sql and lectura.params["marca"] == MARCA
    assert conteo.sql.startswith("SELECT count(*) AS filas FROM timbradas_segmentos_consolidado")
    assert conteo.sql == ric._compilar(motor, ric.SQL_CONTEO_RETIRADO.format(tabla="timbradas_segmentos_consolidado"))
    assert len(ahora) == 1 and "timbradas_segmentos_consolidado.proceso = %(proceso)s" in ahora[0].sql
    assert ahora[0].params["proceso"] == L.PROCESO and ahora[0].params["marca"] == MARCA
    # las lecturas son las de la lista blanca de la API (sin esquema: la temporal las tapa en su sesión)
    from app.servicios.fuentes import validar_solo_select

    assert all(validar_solo_select(c.sql) and "public." not in c.sql for c in [*antes, *ahora])


def test_los_escenarios_reales_usan_la_marca_o_la_marca_inicial(motor):
    from app.servicios import consolidados, fuentes

    ctx = {"marcas": {consolidados.TABLA_RUTA: MARCA, consolidados.TABLA_SEGMENTOS_ANIO: None,
                      consolidados.TABLA_SEGMENTOS: None}}
    escenarios = {e.clave: e for e in L.escenarios_reales(motor, ctx)}
    assert list(escenarios) == list(consolidados.TABLAS) == list(L.SQL_MARCA_Y_FILAS)
    assert all(f"FROM public.{t} WHERE proceso = %s" in sql for t, sql in L.SQL_MARCA_Y_FILAS.items())
    assert escenarios[consolidados.TABLA_RUTA].ahora[0].params["marca"] == MARCA - ric.SOLAPE
    assert escenarios[consolidados.TABLA_SEGMENTOS].ahora[0].params["marca"] == fuentes.MARCA_INICIAL
    assert "H4" in escenarios[consolidados.TABLA_SEGMENTOS].descripcion


def test_el_volumen_sintetico_vive_en_una_temporal_y_mide_las_huellas_de_antes(motor):
    ctx = {"marcas": {"timbradas_consolidado": MARCA}, "filas_consolidado": 10, "segmentos_por_ruta": 4}
    cx = _Conexion()
    r = L.medir_sintetico(cx, motor, ctx)
    assert L.filas_sinteticas(ctx) == r["filas_sinteticas"] == 40 and r["sello"] == MARCA.isoformat()
    assert cx.sentencias[0] == L.SQL_TEMPORAL and "ON COMMIT DROP" in L.SQL_TEMPORAL
    assert cx.sentencias[1].strip().startswith(f"INSERT INTO pg_temp.{L.TABLA_SINTETICA}")
    assert cx.sentencias[2] == f"ANALYZE pg_temp.{L.TABLA_SINTETICA}"
    # nada escribe, crea ni borra en el esquema de Extreme
    escritura = re.compile(r"\b(INSERT\s+INTO|UPDATE|DELETE|DROP|ALTER|CREATE\s+INDEX|TRUNCATE)\b\s+public\.", re.I)
    assert not any(escritura.search(s) for s in cx.sentencias)
    assert r["antes"]["consultas"] == 2 and r["ahora"]["consultas"] == 1
    assert r["antes"]["filas_leidas"] == 3 and r["ahora"]["filas_leidas"] == 0
    assert r["antes"]["api"]["filas_traidas"] == 3 and r["antes"]["api"]["huellas_en_el_estado"] == 3
    assert r["ahora"]["api"] == dict(r["ahora"]["api"], filas_traidas=0, huellas_en_el_estado=0)
    # cada índice candidato se crea sobre la TEMPORAL, se mide con la lectura de ahora y se borra antes del siguiente
    assert [i["indice"] for i in r["indices"]] == [n for n, _c in L.INDICES_SINTETICOS]
    creados = [s for s in cx.sentencias if s.startswith(("CREATE INDEX", "DROP INDEX"))]
    assert creados == [x for n, c in L.INDICES_SINTETICOS
                       for x in (f"CREATE INDEX {n} ON pg_temp.{L.TABLA_SINTETICA} ({c})", f"DROP INDEX pg_temp.{n}")]


def test_la_conclusion_de_los_indices_sigue_el_criterio_de_la_medicion():
    marca = {"indice": "ix_ia_tmp_marca", "columnas": "ultima_actualizacion", "ms_ejecucion": 290.0,
             "usa_el_indice": True}
    compuesto = {"indice": "ix_ia_tmp_proceso_marca", "columnas": "proceso, ultima_actualizacion",
                 "ms_ejecucion": 0.02, "usa_el_indice": True}
    texto = L.conclusion_indices(266.0, [marca, compuesto])
    assert "es el más rápido `ix_ia_tmp_proceso_marca`" in texto and "(no cumple el criterio)" in texto
    assert "La marca sola no sirve aquí" in texto
    assert L.conclusion_indices(266.0, [dict(marca, ms_ejecucion=0.01), compuesto]).count("no sirve") == 0
    assert L.conclusion_indices(266.0, [dict(compuesto, usa_el_indice=False)]) == (
        "Ningún índice candidato cumple el criterio con este volumen.")


def test_el_informe_compara_antes_y_ahora():
    def lado(consultas, filas, api=None):
        return {"consultas": consultas, "ms_total": 12.5, "filas_leidas": filas, "detalle": {},
                **({"api": api} if api else {})}

    api = {"filas_traidas": 500000, "segundos_traer": 4.2, "segundos_huellas": 6.1, "huellas_en_el_estado": 500000,
           "mb_estado_fuente": 38.5, "truncada": True}
    r = {"generado": "2026-11-10T20:30:00-05:00", "rol": "extreme_dba", "metodo": "una transacción que se revierte",
         "proceso": "sobusa", "otro_proceso": "cootransoriente",
         "contexto": {"filas_del_proceso": {"timbradas_consolidado": 10731}},
         "reales": [{"escenario": "timbradas_consolidado", "descripcion": "sin novedades", "antes": lado(2, 4),
                     "ahora": lado(1, 4)}],
         "sintetico": {"escenario": "timbradas_segmentos_consolidado_con_otro_operador", "descripcion": "sintético",
                       "antes": lado(2, 500000, api), "ahora": lado(1, 0, dict(api, filas_traidas=0,
                                                                              huellas_en_el_estado=0)),
                       "filas_sinteticas": 1384299, "segmentos_por_ruta": 129, "segundos_carga": 8.3},
         "temporal_al_terminar": False}
    md = L.informe_md(r)
    assert "| timbradas_consolidado | antes | 2 |" in md and "| timbradas_consolidado | ahora | 1 |" in md
    assert "1.384.299 filas" in md and "500.000 filas ajenas (la lectura llegaba al límite de filas)" in md
    assert "es nulo" in md and "38,50 MB" in md
