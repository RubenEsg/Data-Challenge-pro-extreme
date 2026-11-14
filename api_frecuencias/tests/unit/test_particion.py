"""Unidad de la partición por ruta (RNF-005): marca de agua por proceso y ruta, lectura filtrada por ruta (lista
blanca y solo lectura) y marcas que deja cada trabajo. La fuente PostgreSQL se prueba SOLO con unittest.mock: nunca
se conecta a una base."""
from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from unittest import mock

import pandas as pd
import pytest

from app.servicios import fuentes as F

BOGOTA = "America/Bogota"
URL = "postgresql+psycopg://x@y/z"


def _ts(texto: str) -> datetime:
    return pd.Timestamp(texto, tz=BOGOTA).to_pydatetime()


def demanda(rutas=("A", "B"), dias=(1, 2, 3)) -> pd.DataFrame:
    """Dos rutas, dos horas por día; cada día llega a las 23:59 de ese día (como la serie empaquetada)."""
    filas = [{"ruta": r, "fecha": date(2025, 1, d), "hora": h, "pasajeros": 10.0 * h + d, "salidas": 3,
              "ultima_actualizacion": pd.Timestamp(f"2025-01-0{d} 23:59:59", tz=BOGOTA)}
             for r in rutas for d in dias for h in (6, 7)]
    return pd.DataFrame(filas)


# ------------------------------------------------------------------ Particion
def test_particion_marca_de_cada_ruta_y_frontera():
    p = F.Particion(proceso="sobusa", marcas={"A": _ts("2025-01-02 23:59:59")}, marca_resto=_ts("2025-01-01 23:59:59"))
    assert p.marca_de("A") == _ts("2025-01-02 23:59:59")
    assert p.marca_de("B") == _ts("2025-01-01 23:59:59")          # sin marca propia: la frontera
    assert p.marca_de(None) == _ts("2025-01-01 23:59:59")
    assert p.marca_lectura() == _ts("2025-01-01 23:59:59")        # todas las rutas: la más antigua, con la frontera
    assert p.marca_anterior() == _ts("2025-01-02 23:59:59")       # la que muestra: la más avanzada (la global)
    solo_a = F.Particion(proceso="sobusa", rutas=("A",), marcas=p.marcas, marca_resto=p.marca_resto)
    assert solo_a.marca_lectura() == solo_a.marca_anterior() == _ts("2025-01-02 23:59:59")
    vacia = F.Particion(proceso="sobusa")
    assert vacia.marca_lectura() == F.MARCA_INICIAL and vacia.marca_anterior() is None


def test_huellas_de_cada_ruta_salen_de_la_frontera_si_no_tiene_propias():
    resto = {"version": F.VERSION_ESTADO, "tabla": "demanda_segmentos", "huellas": {"A|2025-01-01|6": "h1",
                                                                                    "B|2025-01-01|6": "h2"}}
    p = F.Particion(proceso="sobusa", estados={"A": {"huellas": {"A|x|1": "propia"}}}, estado_resto=resto)
    assert p.estado_de("A") == {"huellas": {"A|x|1": "propia"}}
    assert p.estado_de("B")["huellas"] == {"B|2025-01-01|6": "h2"}
    assert p.estado_de(None) is resto
    assert F.huellas_de_la_ruta(None, "A") is None


# ------------------------------------------------------------------ FuenteParquet
def test_parquet_cada_ruta_desde_su_marca_y_la_ruta_del_trabajo_sola():
    f = F.FuenteParquet(cargador=demanda)
    p = F.Particion(proceso="sobusa", marcas={"A": _ts("2025-01-02 23:59:59"), "B": _ts("2025-01-01 23:59:59")})
    lectura = F.leer_particion(f, p, hasta=date(2025, 1, 3))
    assert sorted(lectura.df.groupby("ruta")["fecha"].apply(lambda s: sorted(set(s))).items()) == [
        ("A", [date(2025, 1, 3)]), ("B", [date(2025, 1, 2), date(2025, 1, 3)])]
    assert lectura.marca_global == _ts("2025-01-03 23:59:59")
    assert lectura.marcas == {"A": _ts("2025-01-03 23:59:59"), "B": _ts("2025-01-03 23:59:59")}
    solo_b = F.Particion(proceso="sobusa", rutas=("B",), marcas=p.marcas)
    lectura_b = F.leer_particion(f, solo_b, hasta=date(2025, 1, 2))
    assert set(lectura_b.df["ruta"]) == {"B"} and set(lectura_b.df["fecha"]) == {date(2025, 1, 2)}
    assert lectura_b.marcas == {"B": _ts("2025-01-02 23:59:59")} and "A" not in lectura_b.marcas


def test_parquet_sin_rutas_es_la_lectura_de_siempre():
    """Con todas las marcas en la misma frontera, la lectura por partición entrega lo mismo que leer_incremental."""
    f = F.FuenteParquet(cargador=demanda)
    marca = _ts("2025-01-01 23:59:59")
    legado, nueva = f.leer_incremental(marca, hasta=date(2025, 1, 3))
    lectura = F.leer_particion(f, F.Particion(proceso="sobusa", marcas={"A": marca, "B": marca}), date(2025, 1, 3))
    pd.testing.assert_frame_equal(lectura.df.reset_index(drop=True), legado.reset_index(drop=True))
    assert lectura.marca_global == pd.Timestamp(nueva).to_pydatetime()


def test_parquet_ruta_sin_datos_nuevos_conserva_su_marca_y_todas_avanzan_a_la_frontera():
    f = F.FuenteParquet(cargador=lambda: demanda(rutas=("A",)))
    marcas = {"A": _ts("2025-01-01 23:59:59"), "B": _ts("2025-01-01 23:59:59")}
    trabajo_b = F.leer_particion(f, F.Particion(proceso="sobusa", rutas=("B",), marcas=marcas), date(2025, 1, 3))
    assert len(trabajo_b.df) == 0 and trabajo_b.marca_global is None
    assert trabajo_b.marcas == {"B": marcas["B"]}                  # sin filas, la marca de B no se mueve
    todas = F.leer_particion(f, F.Particion(proceso="sobusa", marcas=marcas), date(2025, 1, 3))
    # un trabajo de todas las rutas leyó la fuente completa hasta su marca mayor: B queda en esa frontera
    assert todas.marcas == {"A": _ts("2025-01-03 23:59:59"), "B": _ts("2025-01-03 23:59:59")}


def test_fuente_sin_lectura_por_ruta_usa_la_de_siempre_y_filtra_la_ruta():
    class Doble:
        def leer_incremental(self, marca_agua=None, hasta=None):
            return demanda(), marca_agua

    trabajo = F.leer_particion(Doble(), F.Particion(proceso="*", rutas=("A",)), None)
    assert set(trabajo.df["ruta"]) == {"A"} and trabajo.marca_global is None and trabajo.marcas == {}
    marca = _ts("2025-01-02 23:59:59")
    todas = F.leer_particion(Doble(), F.Particion(proceso="*", marcas={"A": marca}, marca_resto=marca), None)
    assert len(todas.df) == len(demanda()) and todas.marcas == {"A": marca}     # el doble no mueve las marcas
    # sin frontera, una ruta sin marca propia no se leyó nunca: el trabajo de todas las rutas parte de la marca inicial
    sin_frontera = F.leer_particion(Doble(), F.Particion(proceso="*", marcas={"A": marca}), None)
    assert sin_frontera.marca_global is None and sin_frontera.marcas == {}


# ------------------------------------------------------------------ FuentePostgresSoloLectura (solo mocks)
def motor_falso(filas):
    motor = mock.MagicMock(name="engine")
    conn = motor.connect.return_value.__enter__.return_value
    resultado = mock.MagicMock()
    resultado.mappings.return_value.all.return_value = filas

    def ejecutar(stmt, params=None):
        return resultado if str(stmt).lstrip().upper().startswith(("SELECT", "WITH")) else mock.MagicMock()

    conn.execute.side_effect = ejecutar
    return motor, conn


def _fila(ruta, hora, ts, pasajeros):
    return {"ruta": ruta, "idruta": 1, "proceso": "sobusa", "idempresa": None, "fecha": date(2026, 11, 8),
            "hora": hora, "pasajeros": pasajeros, "salidas": 2, "subidas": 1.0, "bajadas": 1.0, "filas_segmento": 2,
            "viajes_con_timbradas": 2, "id_estacionalidad": 25, "id_estacionalidad_anio": 9,
            "ultima_actualizacion": ts}


def test_sql_por_ruta_es_de_la_lista_blanca_y_lleva_las_rutas_como_parametro():
    f = F.FuentePostgresSoloLectura(url=URL, motor=mock.MagicMock())
    for con_hasta in (False, True):
        sql = f.consulta_incremental(con_hasta=con_hasta, con_rutas=True).text
        assert F.validar_solo_select(sql)
        assert "r.nombre = ANY(CAST(:rutas AS text[]))" in sql and (":hasta" in sql) == con_hasta
    assert "ANY(CAST(:rutas" not in f.consulta_incremental().text        # sin rutas, el SELECT de siempre
    otra = F.FuentePostgresSoloLectura(url=URL, tabla="timbradas_consolidado", motor=mock.MagicMock())
    with pytest.raises(F.OperacionNoPermitida, match="demanda_segmentos"):
        otra.consulta_incremental(con_rutas=True)
    catalogo = F.FuentePostgresSoloLectura(url=URL, tabla="rutas", motor=mock.MagicMock())
    with pytest.raises(F.OperacionNoPermitida):
        catalogo.leer_particion(F.Particion(proceso="sobusa"))


def test_postgres_trabajo_de_una_ruta_lee_solo_esa_ruta_en_solo_lectura():
    t = datetime(2026, 11, 8, 23, 0)                    # marca sin zona de Extreme (hora de Bogotá)
    motor, conn = motor_falso([_fila("A", 6, t, 30.0)])
    f = F.FuentePostgresSoloLectura(url=URL, motor=motor, statement_timeout_ms=1500)
    marca_a = _ts("2026-11-08 20:00")
    p = F.Particion(proceso="sobusa", rutas=("A",), marcas={"A": marca_a, "B": _ts("2026-11-01 00:00")})
    lectura = f.leer_particion(p, hasta=date(2026, 11, 8))
    s = [" ".join(str(c.args[0]).split()) for c in conn.execute.call_args_list]
    assert s[0] == "SET TRANSACTION READ ONLY" and s[1] == "SET LOCAL statement_timeout = 1500"
    assert "r.nombre = ANY(CAST(:rutas AS text[]))" in s[3]
    params = conn.execute.call_args_list[3].args[1]
    assert params["rutas"] == ["A"] and params["proceso"] == "sobusa"
    assert params["marca"] == marca_a - timedelta(minutes=15)             # la marca de SU ruta, menos el solape
    conn.rollback.assert_called_once()
    conn.commit.assert_not_called()
    assert len(lectura.df) == 1 and lectura.marcas == {"A": _ts("2026-11-08 23:00")}
    assert f.resumen_lectura["particion"] == ["A"] and f.resumen_lectura["nuevas"] == 1


def test_postgres_todas_las_rutas_cada_una_con_su_marca_y_sus_huellas():
    """Lectura desde la marca más antigua: lo de A anterior a la ventana de A se descarta (ya se le entregó), una fila
    de A en su ventana con la misma huella es repetida y la misma fila de B (con otra marca) es nueva."""
    marca_a, marca_b = _ts("2026-11-08 22:00"), _ts("2026-11-08 18:00")
    vieja_a = _fila("A", 5, datetime(2026, 11, 8, 19, 0), 10.0)       # antes de la ventana de A (21:45)
    repetida_a = _fila("A", 6, datetime(2026, 11, 8, 21, 50), 30.0)   # en la ventana de A, ya entregada
    nueva_a = _fila("A", 7, datetime(2026, 11, 8, 22, 30), 40.0)
    nueva_b = _fila("B", 6, datetime(2026, 11, 8, 21, 50), 30.0)
    f0 = F.FuentePostgresSoloLectura(url=URL, motor=motor_falso([repetida_a])[0])
    f0.leer_incremental(_ts("2026-11-08 21:00"))
    estado_a = F.huellas_de_la_ruta(f0.estado_incremental, "A")
    motor, conn = motor_falso([vieja_a, repetida_a, nueva_b, nueva_a])
    f = F.FuentePostgresSoloLectura(url=URL, motor=motor)
    p = F.Particion(proceso="sobusa", marcas={"A": marca_a, "B": marca_b}, estados={"A": estado_a},
                    marca_resto=marca_b)
    lectura = F.leer_particion(f, p)
    assert conn.execute.call_args_list[3].args[1]["marca"] == marca_b - timedelta(minutes=15)
    assert "rutas" not in conn.execute.call_args_list[3].args[1]           # todas: sin filtro de rutas
    assert sorted(zip(lectura.df["ruta"], lectura.df["hora"], strict=True)) == [("A", 7), ("B", 6)]
    r = f.resumen_lectura
    assert r["rutas"]["A"]["descartadas_marca_ruta"] == 1 and r["rutas"]["A"]["repetidas_solape"] == 1
    assert (r["entregadas"], r["repetidas_solape"], r["leidas"]) == (2, 1, 4)
    assert lectura.marcas == {"A": _ts("2026-11-08 22:30"), "B": _ts("2026-11-08 22:30")}   # todas a la frontera
    assert lectura.marca_global == _ts("2026-11-08 22:30")
    assert set(lectura.estados) == {"A", "B"} and "B|2026-11-08|6" in lectura.estados["B"]["huellas"]


def test_postgres_marcas_alineadas_entrega_lo_mismo_que_leer_incremental():
    t = datetime(2026, 11, 8, 22, 0)
    filas = [_fila("A", 6, t, 30.0), _fila("B", 6, t + timedelta(minutes=1), 31.0), _fila("A", 7, t, 32.0)]
    marca = _ts("2026-11-08 21:00")
    legado = F.FuentePostgresSoloLectura(url=URL, motor=motor_falso(filas)[0])
    d_legado, m_legado = legado.leer_incremental(marca)
    f = F.FuentePostgresSoloLectura(url=URL, motor=motor_falso(filas)[0])
    lectura = f.leer_particion(F.Particion(proceso="sobusa", marcas={"A": marca, "B": marca}))
    pd.testing.assert_frame_equal(lectura.df, d_legado)
    assert lectura.marca_global == m_legado
    for campo in ("entregadas", "nuevas", "tardias", "modificadas", "repetidas_solape"):
        assert f.resumen_lectura[campo] == legado.resumen_lectura[campo], campo


def test_postgres_ruta_adelantada_no_mueve_la_frontera_ni_pierde_sus_huellas():
    """B ya leyó hasta el día 10 (trabajo de su ruta) y un trabajo de todas las rutas lee hasta el día 8: la frontera y
    la marca de A son las de lo que se LEYÓ (día 8), no la marca de B, cuyas filas se descartaron todas; si no, A no
    leería nunca sus días 9 y 10. B no leyó nada: conserva su marca y sus huellas."""
    marca_b = _ts("2026-11-10 23:00")
    estado_b = {"version": F.VERSION_ESTADO, "tabla": "demanda_segmentos", "huellas": {"B|2026-11-10|22": "hb"}}
    ya_entregada_b = _fila("B", 6, datetime(2026, 11, 8, 22, 0), 30.0)
    nueva_a = _fila("A", 6, datetime(2026, 11, 8, 22, 0), 31.0)
    f = F.FuentePostgresSoloLectura(url=URL, motor=motor_falso([ya_entregada_b, nueva_a])[0])
    p = F.Particion(proceso="sobusa", marcas={"B": marca_b}, estados={"B": estado_b})
    lectura = F.leer_particion(f, p, hasta=date(2026, 11, 8))
    assert list(lectura.df["ruta"]) == ["A"]
    assert lectura.marca_global == _ts("2026-11-08 22:00")
    assert lectura.marcas == {"A": _ts("2026-11-08 22:00"), "B": marca_b}
    assert lectura.estados["B"] == estado_b
    assert f.resumen_lectura["rutas"]["B"]["descartadas_marca_ruta"] == 1
    assert f.resumen_lectura["marca_nueva"] == marca_b.isoformat()       # la que muestra nunca retrocede


# ------------------------------------------------------------------ marcas que deja un trabajo (ejecucion.py)
def _ciclo(particion, lectura, **k):
    from app.servicios import ejecucion

    base = dict(execution_id=uuid.uuid4(), p={}, fuente=None, df=None, validos=None, errores=[], marca_anterior=None,
                marca_nueva=None, filas_leidas=0, filas_validas=0, version_u=1, umbrales={}, model_id=None,
                metricas={})
    return ejecucion._Ciclo(**(base | k), particion=particion, lectura=lectura)


def test_filas_de_marcas_de_un_trabajo_de_ruta_y_de_uno_de_todas():
    from app.servicios import ejecucion

    marca = _ts("2025-01-02 23:59:59")
    p_ruta = F.Particion(proceso="sobusa", rutas=("A",), marcas={"A": marca})
    lectura = F.LecturaParticion(df=pd.DataFrame(), marcas={"A": _ts("2025-01-03 23:59:59")},
                                 estados={"A": {"huellas": {"A|x|6": "h"}}}, marca_global=_ts("2025-01-03 23:59:59"))
    c = _ciclo(p_ruta, lectura, ruta="A")
    filas = ejecucion.filas_de_marcas(c)
    assert [(f["proceso"], f["ruta"], f["marca_agua"]) for f in filas] == [("sobusa", "A", _ts("2025-01-03 23:59:59"))]
    assert filas[0]["estado_fuente"] == {"huellas": {"A|x|6": "h"}} and filas[0]["execution_id"] == c.execution_id
    todas = _ciclo(F.Particion(proceso="sobusa", marca_resto=marca), lectura,
                   metricas={"fuente_estado": {"huellas": {}}})
    assert [f["ruta"] for f in ejecucion.filas_de_marcas(todas)] == ["A", ejecucion.RUTA_FRONTERA]
    sin_datos = F.LecturaParticion(df=pd.DataFrame(), marcas={"A": F.MARCA_INICIAL}, estados={}, marca_global=None)
    assert ejecucion.filas_de_marcas(_ciclo(F.Particion(proceso="sobusa", rutas=("A",)), sin_datos)) == []
    assert ejecucion.filas_de_marcas(_ciclo(None, None)) == []


def test_marca_nueva_del_trabajo_y_resumen_de_la_particion():
    from app.servicios import ejecucion

    anterior = _ts("2025-01-02 23:59:59")
    lectura = F.LecturaParticion(df=pd.DataFrame(), marcas={"A": _ts("2025-01-03 23:59:59"), "B": anterior},
                                 estados={}, marca_global=_ts("2025-01-03 23:59:59"))
    assert ejecucion._marca_nueva("B", lectura, anterior) == anterior
    assert ejecucion._marca_nueva(None, lectura, anterior) == _ts("2025-01-03 23:59:59")
    vacia = F.LecturaParticion(df=pd.DataFrame(), marcas={"A": F.MARCA_INICIAL}, estados={}, marca_global=None)
    assert ejecucion._marca_nueva("A", vacia, None) is None          # sin datos ni marca previa: sin marca
    c = _ciclo(F.Particion(proceso="sobusa", rutas=("A",), marcas={"A": anterior}), lectura, ruta="A")
    r = ejecucion.resumen_particion(c)
    assert r["proceso"] == "sobusa" and r["rutas"] == ["A"]
    assert r["marcas"] == {"A": {"anterior": anterior, "nueva": _ts("2025-01-03 23:59:59")}}
    assert ejecucion.resumen_particion(_ciclo(None, None)) == {}


def test_proceso_de_la_fuente_y_nombre_del_lote():
    from app.servicios import ejecucion

    assert ejecucion.proceso_de_la_fuente(F.FuenteParquet()) == "sobusa"
    assert ejecucion.proceso_de_la_fuente(F.FuentePostgresSoloLectura(url=URL, motor=mock.MagicMock(),
                                                                      proceso="*")) == "*"
    assert ejecucion.proceso_de_la_fuente(object()) == "*"
    eid = uuid.UUID(int=0xABCDEF0123456789)
    assert ejecucion._nombre_del_lote(eid, None, {"hasta": "2025-01-03"}) == f"{eid.hex[:8]}:2025-01-03"
    assert ejecucion._nombre_del_lote(eid, "CRA 54", {}) == f"{eid.hex[:8]}:CRA 54:todo"


def test_candado_ocupado_se_reintenta_y_lo_libre_se_toma(monkeypatch):
    from app.servicios import ejecucion

    class Sesion:
        def __init__(self, respuestas):
            self.respuestas, self.sql = list(respuestas), []

        def execute(self, sql, params):
            self.sql.append((str(sql), dict(params)))
            return SimpleNamespace(scalar=lambda: self.respuestas.pop(0))

    libre = Sesion([True, True])
    ejecucion.tomar_candados_particion(libre, "A", espera_s=0)
    assert "lock_shared" in libre.sql[0][0] and "hashtext(:r)" in libre.sql[1][0] and libre.sql[1][1]["r"] == "A"
    todas = Sesion([True])
    ejecucion.tomar_candados_particion(todas, None, espera_s=0)
    assert len(todas.sql) == 1 and "lock_shared" not in todas.sql[0][0]
    monkeypatch.setattr(ejecucion.time, "sleep", lambda s: None)
    with pytest.raises(ejecucion.ParticionOcupada, match="A"):
        ejecucion.tomar_candados_particion(Sesion([True, False, False]), "A", espera_s=0)


# ------------------------------------------------------------------ API y planificador
def test_solicitud_admite_solo_particion_ninguna_o_ruta():
    from pydantic import ValidationError

    from app.esquemas import SolicitudEjecucion

    assert SolicitudEjecucion().particion == "ninguna"
    assert SolicitudEjecucion(particion="ruta", rutas=["CRA 54"]).particion == "ruta"
    with pytest.raises(ValidationError):
        SolicitudEjecucion(particion="fecha")


def test_planificador_parte_por_ruta_solo_si_se_configura(monkeypatch):
    from app.config import Ajustes
    from app.servicios import datos, planificador

    monkeypatch.setattr(planificador, "obtener_ajustes", lambda: SimpleNamespace(plan_particion="ruta"))
    assert planificador.rutas_de_la_particion() == datos.nombres_rutas()
    monkeypatch.setattr(planificador, "obtener_ajustes", lambda: SimpleNamespace(plan_particion="ninguna"))
    assert planificador.rutas_de_la_particion() is None
    monkeypatch.setattr(planificador, "obtener_ajustes", lambda: SimpleNamespace())     # ajustes sin el campo
    assert planificador.rutas_de_la_particion() is None
    assert Ajustes(_env_file=None, plan_particion=" Ruta ").plan_particion == "ruta"
    with pytest.raises(ValueError, match="PLAN_PARTICION"):
        Ajustes(_env_file=None, plan_particion="fecha")


def test_tarea_diaria_partida_encola_la_madre_con_sus_rutas(monkeypatch):
    from app.servicios import datos
    from app.servicios import planificador as p

    monkeypatch.setattr(p, "obtener_ajustes",
                        lambda: SimpleNamespace(plan_ejecucion_cron="15 5 * * *", plan_particion="ruta"))
    llamadas = []
    monkeypatch.setattr(p, "encolar_franja", lambda tipo, franja, parametros, motivo, **k: llamadas.append(
        (tipo, parametros, k)) or "id-madre")
    assert p.tarea_ejecucion_diaria(datetime(2026, 3, 2, 5, 15, 3, tzinfo=p.ZONA)) == "id-madre"
    rutas = datos.nombres_rutas()
    assert llamadas == [("frecuencia", {"notificar": True, "origen": "planificador", "rutas": rutas},
                         {"rutas": rutas})]


def test_particion_de_la_foto_se_crea_aparte_y_reintenta_si_el_candado_esta_ocupado(monkeypatch):
    """La partición mensual de feature_snapshot se crea en una transacción corta y propia, con lock_timeout: si un
    trabajo vecino tiene el candado, cede y reintenta; si ya existe, no hace DDL."""
    from sqlalchemy.exc import OperationalError

    from app import db
    from app.servicios import monitoreo

    sentencias, intentos = [], {"n": 0}

    class Conexion:
        def __init__(self, existe):
            self.existe = existe

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, sql, params=None):
            sentencias.append(str(sql))
            if "to_regclass" in str(sql):
                return SimpleNamespace(scalar=lambda: "feature_snapshot_202503" if self.existe else None)
            if "asegurar_particion" in str(sql):
                intentos["n"] += 1
                if intentos["n"] == 1:
                    raise OperationalError("SELECT ...", {}, Exception("lock timeout"))
            return SimpleNamespace(scalar=lambda: None)

        def commit(self):
            sentencias.append("COMMIT")

    monkeypatch.setattr(monitoreo.time, "sleep", lambda s: None)
    monkeypatch.setattr(db, "motor", lambda: SimpleNamespace(connect=lambda: Conexion(existe=False)))
    assert monitoreo.asegurar_particion_previa(datetime(2025, 3, 5, 11, tzinfo=UTC)) is True
    assert intentos["n"] == 2 and sentencias[-1] == "COMMIT"
    assert any("lock_timeout = '500ms'" in x for x in sentencias)
    sentencias.clear()
    monkeypatch.setattr(db, "motor", lambda: SimpleNamespace(connect=lambda: Conexion(existe=True)))
    assert monitoreo.asegurar_particion_previa(datetime(2025, 3, 5, 11, tzinfo=UTC)) is True
    assert not any("asegurar_particion" in x for x in sentencias)              # ya existe: sin DDL

    class Ocupada(Conexion):                                                    # siempre ocupado: se rinde
        def execute(self, sql, params=None):
            if "asegurar_particion" in str(sql):
                raise OperationalError("SELECT ...", {}, Exception("lock timeout"))
            return super().execute(sql, params)

    monkeypatch.setattr(db, "motor", lambda: SimpleNamespace(connect=lambda: Ocupada(existe=False)))
    assert monitoreo.asegurar_particion_previa(datetime(2025, 3, 5, 11, tzinfo=UTC), espera_s=0) is False


def test_instante_cero_de_la_marca_es_utc():
    assert F.MARCA_INICIAL == datetime(1970, 1, 1, tzinfo=UTC)


def test_la_ejecucion_partida_fija_su_version_de_umbrales_y_sus_trabajos_la_leen(monkeypatch):
    """§5.1 con RNF-005: la madre y sus trabajos llevan en sus parámetros la versión vigente al crearlos y el ciclo lee
    esa versión (no la que esté vigente cuando corre cada trabajo); sin versión fijada, o si ya no existe, la
    vigente."""
    from app.servicios import ejecucion as X

    versiones = {6: [SimpleNamespace(nombre="elasticidad", valor=0.5)], 7: [SimpleNamespace(nombre="elasticidad",
                                                                                            valor=0.35)]}

    class Sesion:
        def __init__(self):
            self.nuevos = []

        def scalars(self, consulta):           # SELECT … WHERE version = :version (el único parámetro)
            (pedida,) = consulta.compile().params.values()
            return SimpleNamespace(all=lambda: versiones.get(int(pedida), []))

        def add(self, fila):
            self.nuevos.append(fila)

        def flush(self):
            return None

    monkeypatch.setattr(X, "umbrales_vigentes", lambda s: (7, {"elasticidad": 0.35}))
    s = Sesion()
    madre = SimpleNamespace(parametros={"hasta": "2025-09-21"}, correlation_id="c", traceparent=None,
                            execution_id=uuid.uuid4())
    trabajos = X.crear_trabajos_por_ruta(s, madre, ["A", "B"])
    assert madre.parametros["umbrales_version"] == 7
    assert [t.parametros["umbrales_version"] for t in trabajos] == [7, 7]
    assert X.umbrales_de_la_ejecucion(s, {"umbrales_version": 6}) == (6, {"elasticidad": 0.5})   # la fijada
    assert X.umbrales_de_la_ejecucion(s, {}) == (7, {"elasticidad": 0.35})                       # sin partir
    assert X.umbrales_de_la_ejecucion(s, {"umbrales_version": 99}) == (7, {"elasticidad": 0.35})  # ya no existe
