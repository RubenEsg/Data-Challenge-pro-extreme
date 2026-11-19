"""Unidad de la retención automática (§18 «Exposición de datos → retención»), sin base de datos.

Parámetros gobernados (los mismos de la migración 0012) y su validación, el corte por meses del calendario de Bogotá,
que todo el SQL solo nombra tablas del esquema ai_frecuencias, la DDL de las particiones con el nombre validado, que la
política cubre cada tabla del esquema, cuándo simula y el planificador.
"""
from __future__ import annotations

import importlib.util
import re
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from app.servicios import retencion as R

Z = ZoneInfo("America/Bogota")
RAIZ = Path(__file__).resolve().parents[2]


def _migracion_0012():
    spec = importlib.util.spec_from_file_location(
        "m0012", RAIZ / "alembic" / "versions" / "0012_retencion_y_ventana_segmentos.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def test_los_parametros_son_los_que_siembra_la_migracion_0012():
    m = _migracion_0012()
    assert {n: (v, d) for n, v, d in m.PARAMETROS_0012} == R.PARAMETROS          # sin deriva frente al código
    assert (m.revision, m.down_revision, m.TIPO) == ("0012", "0011", R.TIPO)
    assert {n for n in R.PARAMETROS if n.startswith("retencion_meses_")} == set(R.MESES)
    assert all(R.PARAMETROS[n][0] == 13 for n in R.MESES)                          # 13 meses en caliente (§18)


@pytest.mark.parametrize("valores", [
    {"retencion_meses_foto": 2}, {"retencion_meses_resultados": 121}, {"retencion_meses_alertas": 13.5},
    {"retencion_meses_ejecuciones": "trece"}, {"retencion_archivar_particiones": 2},
    {"retencion_aplicar_programada": -1}, {"retencion_meses_foto": None}])
def test_parametros_invalidos_se_rechazan(valores):
    with pytest.raises(ValueError):
        R.validar_parametros(valores)


def test_parametros_validos_y_otros_umbrales_no_se_tocan():
    R.validar_parametros({"retencion_meses_foto": 0, "retencion_meses_resultados": 3, "retencion_meses_alertas": 120,
                          "retencion_meses_ejecuciones": 13.0, "retencion_archivar_particiones": 1,
                          "retencion_aplicar_programada": False, "ocupacion_critica": 0.9})


def test_politica_de_los_umbrales_vigentes_o_los_valores_por_omision():
    assert R.politica_de(None) == {n: v for n, (v, _d) in R.PARAMETROS.items()}
    p = R.politica_de({"retencion_meses_foto": 6.0, "retencion_aplicar_programada": 0, "retencion_meses_alertas": "x"})
    assert p["retencion_meses_foto"] == 6 and p["retencion_aplicar_programada"] == 0
    assert p["retencion_meses_alertas"] == 13                                       # un valor ilegible: el de omisión


@pytest.mark.parametrize(("ahora", "meses", "esperado"), [
    (datetime(2026, 11, 10, 3, 30, tzinfo=Z), 13, datetime(2025, 10, 10, 3, 30, tzinfo=Z)),
    (datetime(2026, 3, 31, 12, 0, tzinfo=Z), 1, datetime(2026, 2, 28, 12, 0, tzinfo=Z)),     # día acotado al mes
    (datetime(2024, 2, 29, 0, 0, tzinfo=Z), 12, datetime(2023, 2, 28, 0, 0, tzinfo=Z)),
    (datetime(2026, 1, 15, 8, 0, tzinfo=ZoneInfo("UTC")), 13, datetime(2024, 12, 15, 3, 0, tzinfo=Z)),  # en Bogotá
])
def test_corte_resta_meses_del_calendario_de_bogota(ahora, meses, esperado):
    assert R.corte(ahora, meses) == esperado


def test_cero_meses_no_recorta():
    assert R.corte(datetime(2026, 11, 10, tzinfo=Z), 0) is None


# ---------------------------------------------------------------- solo el esquema ai_frecuencias
CATALOGO = {"pg_inherits", "pg_class", "pg_namespace", "pg_constraint"}
ALIAS = {"base"}                     # el CTE de las ejecuciones
LLAVES_DEL_ARCHIVO = ["feature_snapshot_execution_id_fkey", "feature_snapshot_prediction_id_fkey"]


class _SesionFalsa:
    """Registra las sentencias; el SELECT de pg_constraint devuelve `nombres`."""

    def __init__(self, nombres):
        self.nombres, self.sentencias = list(nombres), []

    def execute(self, sentencia, parametros=None):
        self.sentencias.append((str(sentencia), parametros))
        return SimpleNamespace(scalars=lambda: iter(self.nombres))


def _sql_del_modulo() -> list[str]:
    textos = [r.candidatas for r in R.REGLAS]
    textos += [str(R.sql_borrar(r)) for r in R.REGLAS]
    textos += [str(R.SQL_PARTICIONES), str(R.SQL_FILAS_PARTICION), str(R.SQL_RESERVA), str(R.SQL_LLAVES_FORANEAS),
               str(R.SQL_ARCHIVOS)]
    textos += [str(s) for s in R.SQL_DERIVADA.values()]
    textos += R.ddl_particion("feature_snapshot_201901", False) + R.ddl_particion("feature_snapshot_201901", True)
    textos += R.ddl_particion("feature_snapshot_201901", True, "feature_snapshot_201901_archivo_2")
    archivo = _SesionFalsa(LLAVES_DEL_ARCHIVO)
    R.soltar_llaves_foraneas(archivo, "feature_snapshot_201901_archivo")
    textos += [t for t, _p in archivo.sentencias]
    return textos


def test_todo_el_sql_solo_nombra_tablas_del_esquema_ai_frecuencias():
    """Cada tabla que nombra el SQL de la retención (FROM, JOIN, DELETE, ALTER, DROP, PARTITION) es del esquema
    ai_frecuencias o del catálogo de PostgreSQL (solo para listar las particiones). Nada fuera del esquema propio."""
    patron = re.compile(r"\b(?:FROM|JOIN|TABLE|PARTITION|INTO|UPDATE)\s+(?!\()([A-Za-z_\".]+)", re.IGNORECASE)
    nombradas = {m.group(1) for texto in _sql_del_modulo() for m in patron.finditer(texto)}
    fuera = {n for n in nombradas if not n.startswith("ai_frecuencias.") and n not in CATALOGO | ALIAS}
    assert not fuera, fuera
    assert {"ai_frecuencias.execution_log", "ai_frecuencias.prediction", "ai_frecuencias.feature_snapshot"} <= nombradas
    assert all(":corte" in r.candidatas for r in R.REGLAS)              # toda regla borra solo lo anterior al corte
    assert "n.nspname = 'ai_frecuencias'" in str(R.SQL_PARTICIONES)


def test_la_ddl_de_las_particiones_valida_el_nombre_del_catalogo():
    assert R.ddl_particion("feature_snapshot_202509", False) == [
        'ALTER TABLE ai_frecuencias.feature_snapshot DETACH PARTITION ai_frecuencias."feature_snapshot_202509"',
        'DROP TABLE ai_frecuencias."feature_snapshot_202509"']
    assert R.ddl_particion("feature_snapshot_202509", True)[1] == (
        'ALTER TABLE ai_frecuencias."feature_snapshot_202509" RENAME TO "feature_snapshot_202509_archivo"')
    for nombre in ("feature_snapshot_2025", 'feature_snapshot_202509"; DROP TABLE x; --', "prediction",
                   "feature_snapshot_202509_archivo"):
        with pytest.raises(ValueError):
            R.ddl_particion(nombre, False)
    # el archivo nuevo de un mes que ya se archivó (nombre_de_archivo); nunca el de otro mes ni un nombre inesperado
    assert R.ddl_particion("feature_snapshot_202509", True, "feature_snapshot_202509_archivo_2")[1] == (
        'ALTER TABLE ai_frecuencias."feature_snapshot_202509" RENAME TO "feature_snapshot_202509_archivo_2"')
    for archivo in ("feature_snapshot_202510_archivo", "feature_snapshot_202509_archivo_x", "prediction",
                    'feature_snapshot_202509_archivo_2"; DROP TABLE x; --'):
        with pytest.raises(ValueError):
            R.ddl_particion("feature_snapshot_202509", True, archivo)


class _SesionArchivos:
    """El SELECT de los archivos existentes de una partición devuelve `existentes`."""

    def __init__(self, existentes):
        self.existentes, self.parametros = list(existentes), []

    def execute(self, sentencia, parametros=None):
        self.parametros.append(parametros)
        return SimpleNamespace(scalars=lambda: iter(self.existentes))


@pytest.mark.parametrize(("existentes", "esperado"), [
    ([], "feature_snapshot_201907_archivo"),
    (["feature_snapshot_201907_archivo"], "feature_snapshot_201907_archivo_2"),
    (["feature_snapshot_201907_archivo", "feature_snapshot_201907_archivo_2"], "feature_snapshot_201907_archivo_3"),
    (["feature_snapshot_201907_archivo_2"], "feature_snapshot_201907_archivo"),
])
def test_el_archivo_de_un_mes_ya_archivado_toma_el_primer_nombre_libre(existentes, esperado):
    """El mismo mes archivado dos veces (se reprocesaron datos viejos): el RENAME no choca con el archivo anterior."""
    s = _SesionArchivos(existentes)
    assert R.nombre_de_archivo(s, "feature_snapshot_201907") == esperado
    assert s.parametros == [{"base": "feature_snapshot_201907_archivo"}]
    assert R.NOMBRE_ARCHIVO.fullmatch(esperado)
    with pytest.raises(ValueError):
        R.nombre_de_archivo(s, 'feature_snapshot_201907"; DROP TABLE x; --')


def test_una_particion_con_fotos_de_predicciones_conservadas_se_conserva():
    """Una foto vive lo que vive su predicción: el motivo para conservar una partición vieja, en orden (nombre no
    estándar, filas recientes, fotos de predicciones que la regla de resultados conserva); sin ninguno, se separa."""
    def conteo(recientes=0, conservadas=0):
        return SimpleNamespace(recientes=recientes, conservadas=conservadas)

    assert R._motivo_para_conservar("feature_snapshot_201908", conteo()) is None
    assert "nombre no estándar" in R._motivo_para_conservar("fs_dba_201801", conteo(conservadas=3))["motivo"]
    assert R._motivo_para_conservar("feature_snapshot_201908", conteo(recientes=2, conservadas=1))["recientes"] == 2
    motivo = R._motivo_para_conservar("feature_snapshot_201908", conteo(conservadas=1))
    assert motivo["fotos_de_predicciones_conservadas"] == 1 and "vive lo que vive su predicción" in motivo["motivo"]
    # el motivo nombra los tres casos que cuenta «conservadas» (SQL_FILAS_PARTICION), no solo el de la recomendación
    assert all(caso in motivo["motivo"] for caso in ("creadas desde su corte", "con una recomendación que se conserva",
                                                     "retencion_meses_resultados = 0"))
    sql = " ".join(str(R.SQL_FILAS_PARTICION).split())
    assert "ai_frecuencias.recommendation r" in sql and "CAST(:corte_resultados AS timestamptz) IS NULL" in sql


def test_el_archivo_suelta_sus_llaves_foraneas_con_nombres_validados():
    """La partición archivada pierde las llaves foráneas que clonó de feature_snapshot (si no, borrar su predicción
    vieja vaciaba el archivo en cascada). El nombre del archivo y los de las restricciones se validan antes de armar la
    DDL; con un nombre inesperado no se ejecuta ningún ALTER."""
    s = _SesionFalsa(LLAVES_DEL_ARCHIVO)
    assert R.soltar_llaves_foraneas(s, "feature_snapshot_201903_archivo") == LLAVES_DEL_ARCHIVO
    assert s.sentencias[0][1] == {"tabla": 'ai_frecuencias."feature_snapshot_201903_archivo"'}
    assert [t for t, _p in s.sentencias[1:]] == [f'ALTER TABLE ai_frecuencias."feature_snapshot_201903_archivo" '
                                                 f'DROP CONSTRAINT "{n}"' for n in LLAVES_DEL_ARCHIVO]
    for archivo in ("feature_snapshot_201903", "prediction", 'feature_snapshot_201903_archivo"; DROP TABLE x; --'):
        with pytest.raises(ValueError):
            R.soltar_llaves_foraneas(_SesionFalsa([]), archivo)
    assert R.soltar_llaves_foraneas(_SesionFalsa([]), "feature_snapshot_201903_archivo_2") == []
    malo = _SesionFalsa(["feature_snapshot_prediction_id_fkey", 'x"; DROP TABLE ai_frecuencias.prediction; --'])
    with pytest.raises(ValueError):
        R.soltar_llaves_foraneas(malo, "feature_snapshot_201903_archivo")
    assert len(malo.sentencias) == 1                                    # solo el SELECT: ningún ALTER


def test_la_espera_del_candado_es_menor_que_deadlock_timeout():
    """ESPERA_CANDADO por debajo del deadlock_timeout por omisión de PostgreSQL (1 s): en un interbloqueo con un ciclo
    cede la retención (la prueba de integración lo comprueba contra el servidor)."""
    assert R.ESPERA_CANDADO.endswith("ms") and int(R.ESPERA_CANDADO[:-2]) < 1000


def test_la_politica_cubre_cada_tabla_del_esquema():
    """Toda tabla de ai_frecuencias tiene una regla de retención (borrar, separar o conservar), para que una tabla
    nueva no quede sin decidir (si se agrega una, esta prueba lo recuerda)."""
    from app.modelos_db import Base

    tablas = {t.name for t in Base.metadata.tables.values()}
    tablas |= {"segmento_estadistica_dia", "segmento_estadistica", "segmento_estadistica_refresco"}   # sin ORM
    reglas = R.reglas_vigentes(R.politica_de(None), datetime(2026, 11, 10, tzinfo=Z))
    cubiertas = {r["tabla"].split(" ")[0] for r in reglas}
    assert tablas <= cubiertas, tablas - cubiertas
    por_tabla = {r["tabla"]: r for r in reglas}
    assert por_tabla["feature_snapshot"]["accion"] == "separar_y_borrar"
    assert por_tabla["feature_snapshot"]["corte"] == datetime(2025, 10, 10, tzinfo=Z)
    assert por_tabla["demanda_observada"]["accion"] == "conservar"
    assert por_tabla["segmento_estadistica_dia"]["grupo"] == "derivada"
    assert por_tabla["alert_history"]["parametro"] == "retencion_meses_alertas"
    archivar = R.reglas_vigentes({**R.politica_de(None), "retencion_archivar_particiones": 1},
                                 datetime(2026, 11, 10, tzinfo=Z))
    assert archivar[0]["accion"] == "separar_y_archivar"


def test_las_ejecuciones_nunca_se_borran_si_algo_las_sostiene():
    candidatas = next(r for r in R.REGLAS if r.tabla == "execution_log").candidatas
    for tabla in ("marca_agua_ruta", "marca_agua_tabla", "model_registry", "demanda_observada", "prediction",
                  "prediction_corto_plazo", "recommendation", "alert", "notification_log", "respuesta_reto",
                  "segmento_estadistica_refresco"):
        assert f"FROM ai_frecuencias.{tabla} r WHERE r.execution_id = t.execution_id" in candidatas, tabla
    assert "estado IN ('ok', 'error')" in candidatas and "DISTINCT ON (u.tipo)" in candidatas
    assert "h.padre_id = b.execution_id" in candidatas                  # una madre solo sin trabajos que se conservan
    assert [r.tabla for r in R.REGLAS][-1] == "execution_log"           # las ejecuciones, al final


# ---------------------------------------------------------------- simulación, mensajes y planificador
def test_simula_lo_pedido_o_lo_que_diga_la_politica():
    assert R.simula({"simular": True}, {"retencion_aplicar_programada": 1})
    assert not R.simula({"simular": False}, {"retencion_aplicar_programada": 0})
    assert not R.simula({"origen": "planificador"}, {"retencion_aplicar_programada": 1})
    assert R.simula({"origen": "planificador"}, {"retencion_aplicar_programada": 0})


def test_mensaje_de_la_corrida():
    r = {"simulado": True, "filas": 12, "particiones": 1, "filas_particiones": 300, "pospuestas": 0}
    assert R.mensaje(r).startswith("Retención simulada (no se borró nada): 12 filas y 1 particiones")
    assert "2 acciones pospuestas" in R.mensaje({**r, "simulado": False, "pospuestas": 2})


def test_el_planificador_programa_la_retencion_con_su_cron(monkeypatch):
    from app.servicios import planificador as p

    base = SimpleNamespace(plan_ejecucion_cron="15 5 * * *", plan_reentrenamiento_cron="0 4 * * 1")
    assert "retencion" not in [t[0] for t in p.trabajos_programados(base)]              # sin cron, no se programa
    con = SimpleNamespace(**vars(base), plan_retencion_cron="30 3 * * 0")
    trabajos = {t[0]: t for t in p.trabajos_programados(con)}
    assert trabajos["retencion"][1] == "30 3 * * 0" and trabajos["retencion"][2] is p.tarea_retencion
    encoladas = []
    monkeypatch.setattr(p, "obtener_ajustes", lambda: con)
    monkeypatch.setattr(p, "encolar_franja", lambda tipo, franja, parametros, motivo: encoladas.append(
        (tipo, franja, parametros, motivo)) or "id-retencion")
    domingo = datetime(2026, 11, 8, 3, 31, tzinfo=p.ZONA)
    assert p.tarea_retencion(domingo) == "id-retencion"
    assert encoladas[0][:3] == ("retencion", datetime(2026, 11, 8, 3, 30, tzinfo=p.ZONA), {"origen": "planificador"})
    assert p.tarea_retencion(datetime(2026, 11, 9, 3, 31, tzinfo=p.ZONA)) is None          # lunes: no es su franja
    monkeypatch.setattr(p, "obtener_ajustes", lambda: base)
    assert p.tarea_retencion(domingo) is None and len(encoladas) == 1


def test_la_cola_despacha_el_tipo_retencion(monkeypatch):
    from app.servicios import cola

    llamadas = []
    monkeypatch.setattr(R, "ciclo_retencion", lambda eid: llamadas.append(eid))
    assert "retencion" in cola.TIPOS
    cola._correr_segun_tipo(cola.Reclamo(execution_id="e1", tipo="retencion", intentos=1, worker_id="w"))
    assert llamadas == ["e1"]


def test_la_matriz_de_permisos_exige_admin_para_aplicar():
    from app.seguridad import rol_requerido

    assert rol_requerido("POST", "/api/v1/retencion/aplicar") == "admin"
    assert rol_requerido("GET", "/api/v1/retencion") == "operador"
