"""Unidad de la agregación materializada de segmentos (§6.1, §7.1, RNF-002, RNF-004, RNF-005), sin base de datos.

La fuente se inyecta (una falsa que valida que cada SQL sea un SELECT de la lista blanca y responde DataFrames fijos):
planificación del refresco (completo, incremental, rango, sin cambios), tramos, partición automática cuando un tramo
agota el statement_timeout, CSV para COPY, SQL de la consulta según el rango pedido, parámetros, planificador, cola y
el encolado al cerrar un ciclo.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pandas as pd
import pytest

from app.servicios import segmentos as S
from app.servicios import segmentos_refresco as R

Z = R.ZONA
MARCA = datetime(2024, 4, 1, 8, 0, tzinfo=Z)


class FuenteFalsa:
    """Responde por fragmento de SQL; registra cada consulta (validada como SELECT de solo lectura)."""

    def __init__(self, respuestas: dict[str, pd.DataFrame] | None = None, falla=None):
        self.respuestas = respuestas or {}
        self.falla = falla
        self.consultas: list[tuple[str, dict]] = []

    def consultar(self, sql, parametros=None):
        from app.servicios.fuentes import validar_solo_select

        validar_solo_select(sql)
        parametros = dict(parametros or {})
        self.consultas.append((sql, parametros))
        if self.falla is not None:
            self.falla(sql, parametros)
        for clave, df in self.respuestas.items():
            if clave in sql:
                return df.copy()
        return pd.DataFrame()


class TiempoAgotado(Exception):
    sqlstate = "57014"


def _fuente(huella="h1", fecha_min=date(2024, 3, 1), fecha_max=date(2024, 3, 20), cambios=None, falla=None):
    respuestas = {"md5(": pd.DataFrame({"huella": [huella]}),
                  "min(fecha)": pd.DataFrame({"fecha_min": [fecha_min], "fecha_max": [fecha_max],
                                              "marca": [datetime(2024, 4, 1, 9, 0)]}),
                  "WHERE ultimaactualizacion >": cambios if cambios is not None else pd.DataFrame(),
                  "DISTINCT idruta": pd.DataFrame({"idruta": [2, 16]})}
    return FuenteFalsa(respuestas, falla)


def _previo(**cambios):
    base = {"huella_catalogos": "h1", "marca_fuente": MARCA, "ultimo_completo": datetime.now(Z) - timedelta(days=1),
            "fecha_min": date(2024, 3, 1), "fecha_max": date(2024, 3, 20)}
    return {**base, **cambios}


def _planificar(fuente, previo, parametros, **kw):
    opciones = {"dias_por_lote": 7, "completo_dias": 7, "solape_min": 15, **kw}
    return R.planificar(fuente, previo, parametros, **opciones)


# ---------------------------------------------------------------- tramos y parámetros
def test_partir_en_tramos_consecutivos_sin_huecos_ni_solapes():
    assert R.partir(date(2024, 3, 1), date(2024, 3, 15), 7) == [
        (date(2024, 3, 1), date(2024, 3, 7)), (date(2024, 3, 8), date(2024, 3, 14)),
        (date(2024, 3, 15), date(2024, 3, 15))]
    assert R.partir(date(2024, 3, 2), date(2024, 3, 1), 7) == []
    assert R.partir(date(2024, 3, 1), date(2024, 3, 1), 0) == [(date(2024, 3, 1), date(2024, 3, 1))]


def test_tramos_contiguos_no_incluyen_los_huecos():
    fechas = ["2024-03-06", date(2024, 3, 5), date(2024, 3, 9), date(2024, 3, 10), date(2024, 3, 11), None]
    assert R.tramos_contiguos(fechas, 2) == [
        (date(2024, 3, 5), date(2024, 3, 6)), (date(2024, 3, 9), date(2024, 3, 10)),
        (date(2024, 3, 11), date(2024, 3, 11))]
    assert R.tramos_contiguos([], 7) == []


@pytest.mark.parametrize("parametros", [{"modo": "otro"}, {"modo": "rango"}, {"modo": "rango", "desde": "2024-03-02"},
                                        {"modo": "rango", "desde": "2024-03-05", "hasta": "2024-03-01"},
                                        {"modo": "auto", "desde": "2024-03-01"}, {"modo": "completo",
                                                                                 "hasta": "2024-03-01"},
                                        {"modo": "rango", "desde": "ayer", "hasta": "2024-03-01"}])
def test_parametros_invalidos(parametros):
    with pytest.raises(R.ParametrosInvalidos):
        R.validar_parametros(parametros)


def test_parametros_validos_se_normalizan():
    assert R.validar_parametros(None) == {"modo": "auto", "desde": None, "hasta": None}
    assert R.validar_parametros({"modo": "rango", "desde": "2024-03-01T00:00:00", "hasta": date(2024, 3, 2),
                                 "origen": "api"}) == {"modo": "rango", "desde": date(2024, 3, 1),
                                                       "hasta": date(2024, 3, 2)}


# ---------------------------------------------------------------- plan del refresco
@pytest.mark.parametrize(("modo", "previo", "motivo"), [
    ("completo", _previo(), "pedido"),
    ("auto", None, "sin_refresco_anterior"),
    ("incremental", _previo(huella_catalogos="otra"), "cambiaron_los_catalogos"),
    ("auto", _previo(marca_fuente=None), "sin_marca_anterior"),
    ("auto", _previo(ultimo_completo=datetime.now(Z) - timedelta(days=8)), "periodico"),
    ("auto", _previo(ultimo_completo=None), "periodico"),
    ("incremental", _previo(ultimo_completo=datetime.now(Z) - timedelta(days=30)), None),
    ("auto", _previo(), None),
    ("rango", _previo(), None),
])
def test_cuando_hace_falta_un_refresco_completo(modo, previo, motivo):
    assert R._requiere_completo(modo, previo, "h1", 7, datetime.now(Z)) == motivo


def test_plan_completo_cubre_todas_las_fechas_de_la_fuente_y_toma_su_marca():
    plan = _planificar(_fuente(), None, {"modo": "auto"})
    assert plan.modo == "completo" and plan.borrar_todo and plan.huella == "h1"
    assert plan.tramos[0] == (date(2024, 3, 1), date(2024, 3, 7)) and plan.tramos[-1][1] == date(2024, 3, 20)
    assert plan.fechas == 20 and plan.marca == datetime(2024, 4, 1, 9, 0, tzinfo=Z)


def test_plan_completo_con_la_fuente_vacia_no_tiene_tramos():
    fuente = _fuente(fecha_min=None, fecha_max=None)
    plan = _planificar(fuente, None, {})
    assert plan.modo == "completo" and plan.tramos == [] and plan.fechas == 0


def test_plan_incremental_relee_solo_lo_cambiado_con_la_ventana_de_solape():
    cambios = pd.DataFrame({"fecha": [date(2024, 3, 6), date(2024, 3, 7), date(2024, 3, 19)],
                            "marca": [datetime(2024, 4, 2, 7, 0), datetime(2024, 4, 2, 7, 5), datetime(2024, 4, 3)]})
    fuente = _fuente(cambios=cambios)
    plan = _planificar(fuente, _previo(), {"modo": "auto"})
    assert plan.modo == "incremental" and not plan.borrar_todo
    assert plan.tramos == [(date(2024, 3, 6), date(2024, 3, 7)), (date(2024, 3, 19), date(2024, 3, 19))]
    assert plan.marca == datetime(2024, 4, 3, tzinfo=Z)
    sql, parametros = next(c for c in fuente.consultas if "ultimaactualizacion >" in c[0])
    assert parametros["marca"] == MARCA - timedelta(minutes=15)       # H7/H10: solape antes de la marca


def test_plan_incremental_sin_cambios_no_relee_nada():
    plan = _planificar(_fuente(), _previo(), {"modo": "incremental"})
    assert plan.modo == "sin_cambios" and plan.tramos == [] and plan.marca == MARCA


def test_plan_rango_acotado_a_las_fechas_de_la_fuente():
    plan = _planificar(_fuente(), _previo(), {"modo": "rango", "desde": "2023-01-01", "hasta": "2024-03-03"})
    assert plan.modo == "rango" and plan.tramos == [(date(2024, 3, 1), date(2024, 3, 3))]
    assert plan.marca == MARCA and not plan.borrar_todo
    fuera = _planificar(_fuente(), _previo(), {"modo": "rango", "desde": "2030-01-01", "hasta": "2030-01-02"})
    assert fuera.tramos == []


# ---------------------------------------------------------------- huellas de la ventana de solape (migración 0012)
def _ventana(*grupos) -> pd.DataFrame:
    """Grupos fecha × marca de la ventana como los devuelve SQL_FUENTE_VENTANA (marca sin zona, hora de Bogotá)."""
    columnas = ["fecha", "marca", "filas", "subidas", "bajadas", "pasajeros", "contenido"]
    return pd.DataFrame([dict(zip(columnas, g, strict=True)) for g in grupos], columns=columnas)


VENTANA = _ventana((date(2024, 3, 19), datetime(2024, 4, 1, 7, 50), 40, 120, 118, 900, 123456),
                   (date(2024, 3, 19), datetime(2024, 4, 1, 8, 0), 3, 5, 4, 30, -77),
                   (date(2024, 3, 20), datetime(2024, 4, 1, 8, 0), 10, 30, 29, 200, 999))


def _previo_con_huellas(ventana=VENTANA, solape=15, **cambios):
    return _previo(huellas_solape=R.referencia_ventana(ventana, MARCA, solape), **cambios)


def test_huellas_por_fecha_cambian_con_filas_sumas_contenido_o_marca():
    base = R.huellas_ventana(VENTANA)
    assert set(base) == {"2024-03-19", "2024-03-20"} and all(len(h) == 16 for h in base.values())
    assert R.huellas_ventana(VENTANA.iloc[::-1]) == base                      # no depende del orden de los grupos
    for columna, valor in (("filas", 41), ("subidas", 121), ("contenido", 123457),
                           ("marca", datetime(2024, 4, 1, 7, 51))):
        otra = VENTANA.copy()
        otra.loc[0, columna] = valor
        cambio = R.huellas_ventana(otra)
        assert cambio["2024-03-19"] != base["2024-03-19"] and cambio["2024-03-20"] == base["2024-03-20"], columna
    # la misma marca con zona explícita (otra representación del mismo instante) da la misma huella
    con_zona = VENTANA.assign(marca=[m.replace(tzinfo=Z).astimezone(R.UTC) for m in VENTANA["marca"]])
    assert R.huellas_ventana(con_zona) == base
    assert R.huellas_ventana(pd.DataFrame()) == {} and R.huellas_ventana(None) == {}


def test_la_referencia_guarda_solo_la_ventana_de_la_marca_nueva():
    ref = R.referencia_ventana(VENTANA, MARCA, 5)        # ventana (07:55, …): el grupo de las 07:50 queda fuera
    assert ref["solape_min"] == 5 and ref["version"] == R.VERSION_VENTANA
    assert datetime.fromisoformat(ref["desde"]) == MARCA - timedelta(minutes=5)
    assert set(ref["fechas"]) == {"2024-03-19", "2024-03-20"}
    assert ref["fechas"]["2024-03-19"] == R.huellas_ventana(VENTANA.iloc[1:])["2024-03-19"]
    assert R.referencia_ventana(VENTANA, None, 15) is None


@pytest.mark.parametrize(("cambio", "comparable"), [
    ({}, True), ({"solape_min": 30}, False), ({"version": 99}, False), ({"desde": "2020-01-01T00:00:00+00:00"}, False),
    ({"desde": "no es fecha"}, False), ({"fechas": None}, False)])
def test_la_referencia_previa_solo_sirve_con_el_mismo_solape_y_la_misma_ventana(cambio, comparable):
    previo = _previo_con_huellas()
    previo["huellas_solape"] = {**previo["huellas_solape"], **cambio}
    previas = R._referencia_previa(previo, 15)
    assert (previas == R.huellas_ventana(VENTANA)) if comparable else previas is None
    assert R._referencia_previa(_previo(), 15) is None                         # refresco anterior a la 0012


def test_fechas_cambiadas_entran_cambian_o_salen_de_la_ventana():
    previas = {"2024-03-18": "a", "2024-03-19": "b", "2024-03-20": "c"}
    assert R.fechas_cambiadas({"2024-03-19": "b", "2024-03-20": "x", "2024-03-21": "d"}, previas) == [
        date(2024, 3, 18), date(2024, 3, 20), date(2024, 3, 21)]
    assert R.fechas_cambiadas(dict(previas), previas) == []
    assert R.fechas_cambiadas({"2024-03-20": "c", "2024-03-19": "b"}, None) == [date(2024, 3, 19), date(2024, 3, 20)]


def test_incremental_con_la_misma_ventana_termina_sin_cambios_y_no_relee_nada():
    """(e) Con FUENTE_SOLAPE_MIN = 15 la ventana nunca está vacía mientras haya filas con la marca máxima: antes se
    releían todas sus fechas en cada ciclo. Con las huellas del refresco anterior iguales, no se relee nada."""
    fuente = _fuente(cambios=VENTANA)
    plan = _planificar(fuente, _previo_con_huellas(), {"modo": "auto"})
    assert plan.modo == "sin_cambios" and plan.tramos == [] and plan.fechas == 0 and plan.marca == MARCA
    assert plan.ventana == _previo_con_huellas()["huellas_solape"]              # la referencia sigue siendo la misma
    assert plan.detalle == {"fechas_en_ventana": 2, "comparada_con_el_refresco_anterior": True, "fechas_cambiadas": 0}
    sin_referencia = _planificar(_fuente(cambios=VENTANA), _previo(), {"modo": "auto"})   # como antes de la 0012
    assert sin_referencia.modo == "incremental" and sin_referencia.tramos == [(date(2024, 3, 19), date(2024, 3, 20))]
    assert sin_referencia.ventana == R.referencia_ventana(VENTANA, MARCA, 15)


def test_incremental_relee_solo_las_fechas_cuyas_huellas_cambiaron():
    tardia = VENTANA.copy()
    tardia.loc[0, ["filas", "contenido"]] = [41, 555]           # una transacción larga confirmó tarde en el solape
    nueva = _ventana((date(2024, 3, 25), datetime(2024, 4, 1, 9, 30), 7, 8, 9, 10, 11))
    fuente = _fuente(cambios=pd.concat([tardia, nueva], ignore_index=True))
    plan = _planificar(fuente, _previo_con_huellas(), {"modo": "auto"})
    assert plan.modo == "incremental" and plan.tramos == [(date(2024, 3, 19), date(2024, 3, 19)),
                                                          (date(2024, 3, 25), date(2024, 3, 25))]
    assert plan.marca == datetime(2024, 4, 1, 9, 30, tzinfo=Z) and plan.detalle["fechas_cambiadas"] == 2
    assert set(plan.ventana["fechas"]) == {"2024-03-25"}        # la ventana nueva empieza en 09:15


def test_completo_deja_las_huellas_de_su_ventana_y_el_rango_conserva_las_previas():
    fuente = _fuente(cambios=VENTANA)
    completo = _planificar(fuente, None, {"modo": "auto"})
    marca = datetime(2024, 4, 1, 9, 0, tzinfo=Z)                 # la marca más reciente de la fuente (SQL_FUENTE_RANGO)
    assert completo.ventana == R.referencia_ventana(VENTANA, marca, 15)
    _sql, parametros = next(c for c in fuente.consultas if "ultimaactualizacion >" in c[0])
    assert parametros["marca"] == marca - timedelta(minutes=15) and completo.detalle["motivo_completo"]
    rango = _planificar(_fuente(), _previo_con_huellas(), {"modo": "rango", "desde": "2024-03-02",
                                                            "hasta": "2024-03-02"})
    assert rango.ventana == _previo_con_huellas()["huellas_solape"]


class _SesionRegistro:
    """Registra las sentencias que ejecutaría el refresco (sin base)."""

    def __init__(self):
        self.sql: list[str] = []

    def execute(self, sentencia, parametros=None):
        self.sql.append(str(sentencia))
        return SimpleNamespace(rowcount=7, scalar=lambda: None)


BORRAR_RESPUESTA = "DELETE FROM ai_frecuencias.segmento_estadistica"
UN_DIA = [(date(2024, 3, 1), date(2024, 3, 1))]


@pytest.mark.parametrize(("plan", "espera"), [
    (R.Plan("completo", UN_DIA, borrar_todo=True), BORRAR_RESPUESTA),
    (R.Plan("completo", [], borrar_todo=True), BORRAR_RESPUESTA),
    (R.Plan("incremental", UN_DIA), "NOT EXISTS"), (R.Plan("rango", UN_DIA), "NOT EXISTS"),
    (R.Plan("sin_cambios"), None), (R.Plan("rango"), None)])
def test_el_grano_de_la_respuesta_se_rehace_entero_solo_en_un_completo(plan, espera):
    s = _SesionRegistro()
    reescritas = R._agregar(s, plan, lambda *_a: None)
    if espera is None:
        assert s.sql == [] and reescritas == 0
    else:
        assert espera in s.sql[0] and reescritas == 7
        assert ("NOT EXISTS" in s.sql[-1]) == (not plan.borrar_todo)


def test_un_tramo_parcial_saca_las_claves_antes_y_despues_de_reemplazar_sus_fechas(monkeypatch):
    s = _SesionRegistro()
    monkeypatch.setattr(R, "copiar_dia", lambda _s, df, _e: len(df))
    filas = R._reemplazar_tramo(s, R.Plan("incremental"), date(2024, 3, 1), date(2024, 3, 2),
                                [pd.DataFrame({"linea": ["a", "b"]})], None)
    assert filas == 2 and len(s.sql) == 3
    assert "EXISTS" in s.sql[0] and s.sql[0] == s.sql[2] and "segmento_estadistica_dia" in s.sql[1]
    completo = _SesionRegistro()
    assert R._reemplazar_tramo(completo, R.Plan("completo", borrar_todo=True), date(2024, 3, 1), date(2024, 3, 2),
                               [pd.DataFrame({"linea": ["a"]})], None) == 1 and completo.sql == []
    from app.servicios.fuentes import validar_solo_select

    validar_solo_select(R.SQL_FUENTE_VENTANA)                     # la ventana sigue siendo un SELECT de solo lectura


# ---------------------------------------------------------------- lectura por tramos con partición automática
def test_un_tramo_que_agota_el_timeout_se_parte_por_fechas_y_luego_por_ruta():
    """RNF-005: un tramo que no cabe en el statement_timeout se lee por mitades de fecha y, en un solo día, por ruta.
    Aquí agota el tiempo todo tramo de más de dos días y todo tramo con el 3 de marzo sin ruta."""
    dificil = date(2024, 3, 3)
    fallidas = []

    def falla(sql, p):
        if "timbradas_segmentos ts" not in sql:
            return
        if (p["hasta"] - p["desde"]).days >= 2 or (p["desde"] <= dificil <= p["hasta"] and p["idruta"] is None):
            fallidas.append((p["desde"], p["hasta"], p["idruta"]))
            raise RuntimeError("cancelada") from TiempoAgotado("canceling statement due to statement timeout")

    fuente = _fuente(falla=falla)
    fuente.respuestas["timbradas_segmentos ts"] = pd.DataFrame({"id_segmento": [1]})
    marcos = R.leer_tramo(fuente, date(2024, 3, 1), date(2024, 3, 4))
    leidas = [(p["desde"], p["hasta"], p["idruta"]) for s, p in fuente.consultas if "timbradas_segmentos ts" in s]
    exitosas = [x for x in leidas if x not in fallidas]
    assert fallidas == [(date(2024, 3, 1), date(2024, 3, 4), None), (date(2024, 3, 3), date(2024, 3, 4), None),
                        (dificil, dificil, None)]
    assert exitosas == [(date(2024, 3, 1), date(2024, 3, 2), None), (dificil, dificil, 2), (dificil, dificil, 16),
                        (date(2024, 3, 4), date(2024, 3, 4), None)]
    assert len(marcos) == 4


def _motor_con_tiempo_agotado(lento):
    """Motor simulado de la fuente PostgreSQL real: la lectura del grano diario agota el statement_timeout (psycopg
    QueryCanceled, SQLSTATE 57014, como lo entrega SQLAlchemy) cuando lento(desde, hasta, idruta) es verdadero."""
    from unittest import mock

    import psycopg.errors
    from sqlalchemy.exc import OperationalError

    leidas = []

    def ejecutar(_sentencia, parametros=None):
        parametros = parametros or {}
        if "desde" in parametros:
            pedido = (parametros["desde"], parametros["hasta"], parametros["idruta"])
            leidas.append(pedido)
            if lento(*pedido):
                raise OperationalError("SELECT", parametros, psycopg.errors.QueryCanceled(
                    "canceling statement due to statement timeout"))
        resultado = mock.MagicMock()
        resultado.mappings.return_value.all.return_value = (
            [{"idruta": 2}, {"idruta": 16}] if "DISTINCT idruta" in str(_sentencia) else [{"linea": "x"}])
        return resultado

    motor = mock.MagicMock()
    motor.connect.return_value.__enter__.return_value.execute.side_effect = ejecutar
    return motor, leidas


def test_el_tiempo_agotado_no_abre_el_circuito_compartido_y_la_particion_llega_al_fondo():
    """Con la fuente real de la capa de segmentos, un statement_timeout sube como SentenciaCancelada: el circuit
    breaker «fuente_postgres» (el mismo de la ingesta y los catálogos) sigue cerrado aunque haya más de tres tiempos
    agotados seguidos, y la partición llega hasta un día y, ese día, por ruta. Antes, el tercer tiempo agotado seguido
    abría el circuito, cortaba la partición con CircuitoAbierto y dejaba la fuente bloqueada 60 s para todos."""
    from app.servicios import circuito

    circuito.reiniciar_todos()
    dificil = date(2024, 3, 3)
    motor, leidas = _motor_con_tiempo_agotado(lambda d, h, r: (h - d).days >= 1 or (d == dificil and r is None))
    try:
        marcos = R.leer_tramo(S.fuente(motor=motor), date(2024, 3, 1), date(2024, 3, 8))
        assert circuito.estados()["fuente_postgres"]["estado"] == circuito.CERRADO
    finally:
        circuito.reiniciar_todos()
    dias_sueltos = [x for x in leidas if x[0] == x[1] and x[2] is None]
    assert len(marcos) == 9 and (dificil, dificil, 2) in leidas and (dificil, dificil, 16) in leidas
    assert len(dias_sueltos) == 8 and len(leidas) - len(marcos) == 8   # 7 tramos de varios días y el día difícil


def test_la_particion_tiene_un_tope_de_tiempos_agotados_por_refresco():
    """Si casi todo agota el tiempo, la fuente está sobrecargada: después de MAX_TIEMPOS_AGOTADOS particiones el
    tramo sube el error (el trabajo vuelve a la cola con su espera) en vez de seguir partiendo con lecturas de 30 s."""
    from app.servicios import circuito
    from app.servicios.fuentes import SentenciaCancelada

    circuito.reiniciar_todos()
    motor, leidas = _motor_con_tiempo_agotado(lambda d, h, r: (h - d).days >= 1)
    try:
        with pytest.raises(SentenciaCancelada) as error:
            R.leer_tramo(S.fuente(motor=motor), date(2024, 1, 1), date(2024, 1, 31), particion=R.Particion(3))
        assert R.es_tiempo_agotado(error.value) and circuito.estados()["fuente_postgres"]["estado"] == "cerrado"
    finally:
        circuito.reiniciar_todos()
    assert [(h - d).days + 1 for d, h, _r in leidas] == [31, 16, 8, 4]        # 3 particiones y la cuarta sube
    assert R.Particion().restantes == R.MAX_TIEMPOS_AGOTADOS


def test_otro_error_o_un_tramo_que_ya_no_se_puede_partir_sube():
    def otro(sql, parametros):
        if "timbradas_segmentos ts" in sql:
            raise RuntimeError("se cayó la conexión")

    with pytest.raises(RuntimeError, match="se cayó"):
        R.leer_tramo(_fuente(falla=otro), date(2024, 3, 1), date(2024, 3, 9))

    def siempre(sql, parametros):
        if "timbradas_segmentos ts" in sql:
            raise TiempoAgotado("timeout")

    with pytest.raises(TiempoAgotado):
        R.leer_tramo(_fuente(falla=siempre), date(2024, 3, 1), date(2024, 3, 1), idruta=2)


def test_tiempo_agotado_se_reconoce_dentro_de_la_cadena_de_errores():
    envuelto = RuntimeError("sqlalchemy")
    envuelto.orig = TiempoAgotado("57014")
    assert R.es_tiempo_agotado(envuelto) and R.es_tiempo_agotado(TiempoAgotado())
    assert not R.es_tiempo_agotado(RuntimeError("otra cosa"))
    ciclo = RuntimeError("a")
    ciclo.__cause__ = ciclo                                              # una cadena circular no cuelga
    assert not R.es_tiempo_agotado(ciclo)


def test_csv_para_copy_con_la_ejecucion_al_final():
    lineas = ["1,2,1,2024-03-01,25,5,7,2,11,6,5,4,4,0,-20,-5,-15", "2,2,2,2024-03-02,,6,8,1,3,3,3,0,0,0,7,7,7"]
    eid = uuid.uuid4()
    assert R.csv_dia(lineas, eid).splitlines() == [f"{lineas[0]},{eid}", f"{lineas[1]},{eid}"]
    assert R.csv_dia(lineas, None) == f"{lineas[0]},\n{lineas[1]},\n"           # sin ejecución: NULL en COPY
    assert R.csv_dia([], eid) == ""


def test_la_fuente_arma_cada_linea_en_el_orden_de_las_columnas_del_grano_diario():
    """La línea CSV la arma PostgreSQL en el orden de COLUMNAS_DIA (el mismo del COPY), con la estacionalidad nula
    como campo vacío (concat_ws omite los NULL) y la fecha con formato fijo (sin depender de DateStyle)."""
    from app.servicios.fuentes import validar_solo_select

    validar_solo_select(R.SQL_FUENTE_DIA)
    lista = R.SQL_FUENTE_DIA.split("concat_ws(',',")[1].split(") AS linea")[0]
    campos = [c.strip() for c in lista.replace("\n", " ").split(",")]
    assert campos[3] == "to_char(fecha" and campos[5] == "COALESCE(CAST(id_estacionalidad AS text)"
    nombres = [c.split("(")[-1].split(" ")[0] for c in campos if c not in ("'YYYY-MM-DD')", "'')")]
    assert nombres == list(R.COLUMNAS_DIA)
    assert R._COPY_DIA.startswith("COPY ai_frecuencias.segmento_estadistica_dia (" + ", ".join(R.COLUMNAS_DIA))


def test_avance_del_plan_y_mensajes():
    plan = R.Plan("incremental", [(date(2024, 3, 1), date(2024, 3, 2)), (date(2024, 3, 9), date(2024, 3, 9))])
    assert plan.fechas == 3
    assert "al día" in R._mensaje({"modo": "sin_cambios"})
    assert "3 fechas releídas en 2 tramos" in R._mensaje({"modo": "incremental", "fechas_releidas": 3, "tramos": 2,
                                                           "filas": 10})


# ---------------------------------------------------------------- consulta de la agregación materializada
def test_condiciones_solo_de_los_filtros_presentes():
    params = S.parametros_estadisticas(idruta=2, hora=7)
    assert S._donde(params, ("idruta", "id_segmento", "hora")) == (
        " WHERE idruta = CAST(:idruta AS bigint) AND hora = CAST(:hora AS integer)")
    assert S._donde(S.parametros_estadisticas(), ("idruta", "desde")) == ""


@pytest.mark.parametrize(("filtros", "tabla"), [
    ({}, "segmento_estadistica "), ({"idruta": 2, "hora": 6}, "segmento_estadistica "),
    ({"desde": date(2024, 1, 1)}, "segmento_estadistica "), ({"hasta": date(2024, 3, 20)}, "segmento_estadistica "),
    ({"desde": date(2024, 3, 2)}, "segmento_estadistica_dia"),
    ({"hasta": date(2024, 3, 19)}, "segmento_estadistica_dia"),
    ({"desde": date(2024, 3, 5), "hasta": date(2024, 3, 5)}, "segmento_estadistica_dia"),
])
def test_rango_que_cubre_todo_usa_el_grano_de_la_respuesta(filtros, tabla):
    refresco = {"fecha_min": date(2024, 3, 1), "fecha_max": date(2024, 3, 20)}
    pagina, total = S.sql_materializada(S.parametros_estadisticas(**filtros), None, refresco)
    assert f"FROM ai_frecuencias.{tabla}" in pagina
    assert (total is None) == (tabla == "segmento_estadistica_dia")
    assert pagina.rstrip().endswith("LIMIT :limite OFFSET :desplazamiento")
    assert "id_segmento" in pagina.split("ORDER BY")[1]                # desempate estable de la paginación


def test_items_con_la_misma_representacion_que_la_agregacion_directa():
    """registros() reproduce lo que hacía pandas en la agregación directa: NUMERIC como float, fechas en ISO y, si la
    página trae nulos en una columna entera, sus enteros como float (pandas la vuelve float64); sin total_filas."""
    filas = [{"id_segmento": 1, "id_estacionalidad": 25, "prom_subidas": Decimal("1.500"),
              "primera_fecha": date(2024, 3, 1), "subidas": Decimal("12"), "total_filas": 2},
             {"id_segmento": 2, "id_estacionalidad": None, "prom_subidas": Decimal("0.333"),
              "primera_fecha": date(2024, 3, 2), "subidas": Decimal("1"), "total_filas": 2}]
    assert S.registros(filas) == [
        {"id_segmento": 1, "id_estacionalidad": 25.0, "prom_subidas": 1.5, "primera_fecha": "2024-03-01",
         "subidas": 12.0},
        {"id_segmento": 2, "id_estacionalidad": None, "prom_subidas": 0.333, "primera_fecha": "2024-03-02",
         "subidas": 1.0}]
    assert isinstance(S.registros(filas)[0]["id_estacionalidad"], float)
    sin_nulos = S.registros(filas[:1])[0]
    assert isinstance(sin_nulos["id_estacionalidad"], int) and isinstance(sin_nulos["id_segmento"], int)
    assert S.registros([]) == []
    directa = S._pagina(pd.DataFrame(filas), 50, 0)["items"]          # el camino con pandas da lo mismo
    assert directa == S.registros(filas) and [type(v) for v in directa[0].values()] == [
        type(v) for v in S.registros(filas)[0].values()]


def test_agregacion_vacia_tambien_usa_el_grano_de_la_respuesta():
    assert S._cubre_todo({"desde": date(2024, 3, 5), "hasta": None}, {"fecha_min": None, "fecha_max": None})


def test_orden_con_lista_blanca_y_desempate():
    assert S._orden("-max_subidas,hora").startswith("max_subidas DESC, hora ASC, idruta, nro_segmento")
    assert S._orden(None) == S.ORDEN_DEFECTO and S.ORDEN_DEFECTO.endswith("id_segmento")
    with pytest.raises(ValueError):
        S._orden("subidas; DROP TABLE rutas")


def test_consultar_valida_el_orden_y_el_rango_antes_de_tocar_la_base():
    class SesionQueNoSeUsa:
        def __getattr__(self, nombre):
            raise AssertionError(f"no debía tocar la base ({nombre})")

    with pytest.raises(ValueError):
        S.consultar(SesionQueNoSeUsa(), orden="hora; DELETE")
    with pytest.raises(ValueError):
        S.consultar(SesionQueNoSeUsa(), desde=date(2024, 3, 2), hasta=date(2024, 3, 1))


def test_describir_refresco_en_bogota():
    from zoneinfo import ZoneInfo

    eid = uuid.uuid4()
    marca = S.describir_refresco({"execution_id": eid, "modo": "completo",
                                  "actualizado_en": datetime(2024, 4, 1, 13, 0, tzinfo=ZoneInfo("UTC")),
                                  "ultimo_completo": None, "fecha_min": date(2024, 3, 1), "fecha_max": None,
                                  "filas": 10, "filas_dia": None, "marca_fuente": MARCA})
    assert marca["execution_id"] == str(eid) and marca["actualizado_en"] == "2024-04-01T08:00:00-05:00"
    assert marca["fecha_min"] == "2024-03-01" and marca["fecha_max"] is None and marca["filas_dia"] == 0
    assert marca["ultimo_completo"] is None and marca["marca_fuente"].endswith("-05:00")


def test_sin_fuente_configurada_no_se_encola_nada(monkeypatch):
    monkeypatch.setattr(S, "obtener_ajustes", lambda: SimpleNamespace(fuente_database_url="",
                                                                      fuente_statement_timeout_ms=30000))
    assert not S.fuente_configurada()
    with pytest.raises(S.FuenteNoConfigurada, match="FUENTE_DATABASE_URL"):
        R.solicitar(None, {"modo": "auto"})                       # falla antes de tocar la sesión
    with pytest.raises(S.FuenteNoConfigurada):
        S.fuente()
    assert R.encolar_tras_ciclo(uuid.uuid4()) is None


def test_motor_de_la_fuente_se_reutiliza_y_usa_psycopg():
    a = S._motor_fuente("postgresql://lector_ia@127.0.0.1:1/operacional")
    b = S._motor_fuente("postgresql+psycopg://lector_ia@127.0.0.1:1/operacional")
    assert a is b and a.dialect.driver == "psycopg"


# ---------------------------------------------------------------- planificador, cola y ciclo
def test_planificador_solo_programa_el_refresco_con_base_operacional():
    from app.servicios import planificador as p

    base = SimpleNamespace(plan_ejecucion_cron="15 5 * * *", plan_reentrenamiento_cron="0 4 * * 1")
    assert [t[0] for t in p.trabajos_programados(base)] == ["ejecucion_diaria", "reentrenamiento"]
    con = SimpleNamespace(**vars(base), fuente_database_url="postgresql+psycopg://x@127.0.0.1:1/x",
                          plan_segmentos_cron="45 5 * * *")
    trabajos = {t[0]: t for t in p.trabajos_programados(con)}
    assert trabajos["refresco_segmentos"][1] == "45 5 * * *" and trabajos["refresco_segmentos"][2] is \
        p.tarea_refresco_segmentos


def test_tarea_de_segmentos_encola_su_franja(monkeypatch):
    from app.servicios import planificador as p

    encoladas = []
    aj = SimpleNamespace(plan_segmentos_cron="45 5 * * *", fuente_database_url="postgresql+psycopg://x@h/x")
    monkeypatch.setattr(p, "obtener_ajustes", lambda: aj)
    monkeypatch.setattr(p, "encolar_franja", lambda tipo, franja, parametros, motivo: encoladas.append(
        (tipo, franja, parametros)) or uuid.uuid4())
    ahora = datetime(2026, 11, 9, 5, 46, tzinfo=p.ZONA)
    assert p.tarea_refresco_segmentos(ahora) is not None
    assert encoladas == [("segmentos", datetime(2026, 11, 9, 5, 45, tzinfo=p.ZONA),
                          {"modo": "auto", "origen": "planificador"})]
    assert p.tarea_refresco_segmentos(datetime(2026, 11, 9, 4, 0, tzinfo=p.ZONA)) is None    # fuera de la ventana
    aj.fuente_database_url = ""
    assert p.tarea_refresco_segmentos(ahora) is None and len(encoladas) == 1


def test_la_cola_despacha_el_tipo_segmentos(monkeypatch):
    from app.servicios import cola

    llamadas = []
    monkeypatch.setattr(R, "ciclo_refresco", lambda eid: llamadas.append(eid))
    eid = uuid.uuid4()
    assert cola.correr_reclamo(cola.Reclamo(eid, "segmentos", 1, "w:1:a"), lease_s=3600) == "ok"
    assert llamadas == [eid] and "segmentos" in cola.TIPOS


def test_parametros_o_configuracion_invalidos_no_se_reintentan(monkeypatch):
    from app.servicios import ejecucion

    class SesionFalsa:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, _modelo, _eid):
            return SimpleNamespace(parametros={"modo": "rango"})

    monkeypatch.setattr(R, "sesion_contexto", SesionFalsa)
    with pytest.raises(ejecucion.ErrorNoReintentable, match="rango"):
        R._refrescar_en_cola(uuid.uuid4())


def test_el_ciclo_con_datos_nuevos_pide_el_refresco_y_un_fallo_no_lo_tumba(monkeypatch):
    from app.servicios import ejecucion

    pedidos = []
    monkeypatch.setattr(R, "encolar_tras_ciclo", lambda eid: pedidos.append(eid))
    eid = uuid.uuid4()
    ejecucion._encolar_refresco_segmentos(SimpleNamespace(filas_validas=0, execution_id=uuid.uuid4()))
    ejecucion._encolar_refresco_segmentos(SimpleNamespace(filas_validas=3, execution_id=eid))
    assert pedidos == [eid]

    def falla(_eid):
        raise RuntimeError("base de resultados caída")

    monkeypatch.setattr(R, "encolar_tras_ciclo", falla)
    ejecucion._encolar_refresco_segmentos(SimpleNamespace(filas_validas=3, execution_id=eid))   # no lanza


def test_el_ciclo_de_frecuencia_encola_el_refresco_despues_de_confirmar(monkeypatch):
    from contextlib import nullcontext

    from app.servicios import ejecucion

    orden = []

    class Sesion:
        def __enter__(self):
            orden.append("abre")
            return self

        def __exit__(self, *a):
            orden.append("confirma")
            return False

    ciclo = SimpleNamespace(filas_validas=4, p={}, execution_id=uuid.uuid4(), ruta=None)
    monkeypatch.setattr(ejecucion, "_es_madre", lambda eid: False)       # ejecución sin partir (RNF-005)
    monkeypatch.setattr(ejecucion, "_omitida_por_franja_posterior", lambda eid: False)   # no es una franja vieja
    monkeypatch.setattr(ejecucion, "sesion_contexto", Sesion)
    monkeypatch.setattr(ejecucion, "_leer_lote", lambda s, eid: ciclo)
    monkeypatch.setattr(ejecucion, "serie_de_la_sesion", lambda s: nullcontext())
    monkeypatch.setattr(ejecucion, "_con_datos_nuevos", lambda s, c: orden.append("resultados"))
    monkeypatch.setattr(ejecucion, "_cerrar_ciclo", lambda s, c, t0: orden.append("cierre"))
    monkeypatch.setattr(ejecucion, "_encolar_refresco_segmentos", lambda c: orden.append(("segmentos", c)))
    # sin la envoltura de trazas (app/observabilidad.py la agrega si la app ya se importó)
    ciclo_frecuencia = getattr(ejecucion._ciclo_frecuencia, "_otel_original", ejecucion._ciclo_frecuencia)
    ciclo_frecuencia(ciclo.execution_id)
    assert orden == ["abre", "resultados", "cierre", "confirma", ("segmentos", ciclo)]


def test_en_una_ejecucion_partida_solo_la_madre_pide_el_refresco_una_vez(monkeypatch):
    """RNF-005 con la capa de segmentos: el trabajo de una ruta no pide el refresco (cada pedido que la cola no junta
    es una lectura más en la base de Extreme); lo pide la madre al cerrar la ejecución, con las filas válidas de sus
    trabajos, y sin filas válidas no lo pide."""
    from contextlib import nullcontext

    from app.servicios import ejecucion

    pedidos = []
    monkeypatch.setattr(R, "encolar_tras_ciclo", lambda eid: pedidos.append(eid))

    class Sesion:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    trabajo = SimpleNamespace(filas_validas=7, p={}, execution_id=uuid.uuid4(), ruta="CL 72")
    monkeypatch.setattr(ejecucion, "_omitida_por_franja_posterior", lambda eid: False)   # no es una franja vieja
    monkeypatch.setattr(ejecucion, "sesion_contexto", Sesion)
    monkeypatch.setattr(ejecucion, "_leer_lote", lambda s, eid: trabajo)
    monkeypatch.setattr(ejecucion, "serie_de_la_sesion", lambda s: nullcontext())
    monkeypatch.setattr(ejecucion, "_con_datos_nuevos", lambda s, c: None)
    monkeypatch.setattr(ejecucion, "_cerrar_ciclo", lambda s, c, t0: None)
    ciclo_frecuencia = getattr(ejecucion._ciclo_frecuencia, "_otel_original", ejecucion._ciclo_frecuencia)

    monkeypatch.setattr(ejecucion, "_es_madre", lambda eid: False)
    ciclo_frecuencia(trabajo.execution_id)                  # trabajo de ruta con datos nuevos: no pide
    assert pedidos == []

    madre = uuid.uuid4()
    filas_de_la_madre = iter([21, 0])
    monkeypatch.setattr(ejecucion, "_es_madre", lambda eid: True)
    monkeypatch.setattr(ejecucion, "_ciclo_de_la_madre", lambda eid: next(filas_de_la_madre))
    ciclo_frecuencia(madre)                                 # la madre con 21 filas válidas en sus trabajos: pide
    ciclo_frecuencia(uuid.uuid4())                          # una madre sin filas válidas: no pide
    assert pedidos == [madre]
