"""§5.3 «Empresa, ruta, sentido, viaje, conductor y vehículo, cuando aplique»: qué campos aplican a cada regla, el viaje
del despacho de ALT-006 (cancelado o tardío), los viajes con datos faltantes de ALT-009 y el conductor solo como
seudónimo (§18). La fuente PostgreSQL se prueba con unittest.mock: nunca se conecta a una base."""
import hashlib
import hmac
from datetime import date, datetime, timedelta
from unittest import mock
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from app.servicios import alertas as A
from app.servicios import catalogos, ejecucion
from app.servicios import fuentes as F

Z = ZoneInfo("America/Bogota")
DIA = datetime(2025, 10, 15, 0, 0, tzinfo=Z)
SECRETO = "secreto-de-prueba-identificacion"


@pytest.fixture(autouse=True)
def _secreto(monkeypatch):
    monkeypatch.setenv("SEUDONIMO_SECRETO", SECRETO)


def seudonimo(valor):
    return "cnd_" + hmac.new(SECRETO.encode(), str(valor).encode(), hashlib.sha256).hexdigest()[:24]


def fila(viaje, hora, minuto=0, *, vehiculo=None, conductor=77, cancelada="N", finalizado="S", retraso=1.0,
         excede=None, pasajeros=30, segmentos=None):
    """Una fila como la entregan las fuentes de viajes (conductor YA seudonimizado, timestamps locales sin zona)."""
    salida = datetime(2025, 10, 15, hora, minuto)
    return {"viaje": viaje, "vehiculo": vehiculo or f"SOBUSA{viaje % 100}", "conductor": seudonimo(conductor),
            "salida": salida, "salida_real": None if retraso is None else salida + timedelta(minutes=retraso),
            "finalizado": finalizado, "cancelada": cancelada, "excedeplazosalida": excede,
            "numeropasajeros": pasajeros, "filas_segmento": segmentos}


def viajes(*filas):
    return [A.viaje_de_fila(f) for f in filas]


def dia(cambios=None, **extra):
    """Un día tranquilo de CRA 54 (4-20 h): real = esperado, 10 salidas por hora; cambios: {hora: {campo: valor}}."""
    horas = []
    for h in range(4, 21):
        d = A.contexto_hora(DIA + timedelta(hours=h), 100.0, 100.0, 80.0, 120.0, 10.0, 10.0, 6.0)
        d.update((cambios or {}).get(h, {}))
        horas.append(d)
    return {"ruta": "CRA 54", "empresa": "Sobusa", "detectada_en": DIA + timedelta(days=1, hours=6), "horas": horas,
            **extra}


def solo(ctx, codigo):
    al = [a for a in A.evaluar_observadas(ctx) if a["codigo"] == codigo]
    assert len(al) == 1, f"{codigo}: {len(al)} alertas"
    return al[0]


# ---------------------------------------------------------------- qué aplica a cada regla
def test_tabla_de_identificacion_cubre_las_diez_reglas():
    assert set(A.IDENTIFICACION_5_3) == set(A.CATALOGO)
    for codigo, (aplica, motivo) in A.IDENTIFICACION_5_3.items():
        esperado = ("viaje", "vehiculo", "conductor") if codigo in ("ALT-006", "ALT-009") else ()
        assert tuple(aplica) == esperado, codigo
        assert motivo and len(motivo) > 20, codigo
    ident = A.identificacion_5_3("ALT-001")
    assert ident["aplica"] == [] and ident["sentido"].startswith("no aplica") and "resultado" not in ident
    # la única variante con otra identificación: la ALT-002 observada medida en el segmento crítico (§10.1)
    assert set(A.VARIANTES_5_3) == {("ALT-002", A.METODO_OCUPACION_SEGMENTO)}
    campos, motivo, sentido = A.VARIANTES_5_3[("ALT-002", A.METODO_OCUPACION_SEGMENTO)]
    assert campos == ("sentido", "viaje", "vehiculo", "conductor") and len(motivo) > 20
    assert sentido == A.SENTIDO_SEGMENTO_CRITICO and not sentido.startswith("no aplica")
    variante = A.identificacion_5_3("ALT-002", "identificado", variante=A.METODO_OCUPACION_SEGMENTO)
    assert variante["aplica"] == list(campos) and variante["sentido"] == sentido
    assert variante["variante"] == "segmento_critico" and variante["resultado"] == "identificado"
    assert A.identificacion_5_3("ALT-002")["sentido"] == A.SENTIDO_NO_APLICA      # sin el segmento, la de la ruta


def test_toda_alerta_dice_que_campos_de_identificacion_le_aplican():
    from tests.unit.test_alertas_ocupacion_segmentos import CONDUCTOR, alt002, hora, segmento

    ctx = {"ruta": "CRA 54", "buses_hora_actual": 7, "capacidad": 50, "demanda_prevista": 300.0, "p90": 350.0,
           "p10": 250.0, "minutos_sin_datos": 3_000, "wape_movil": 0.3, "model_id": "m"}
    alertas = A.evaluar_alertas(ctx)
    assert {"ALT-003", "ALT-009", "ALT-010"} <= {a["codigo"] for a in alertas}
    for a in alertas:
        ident = a["variables"]["identificacion_5_3"]
        assert ident["aplica"] == list(A.IDENTIFICACION_5_3[a["codigo"]][0]), a["codigo"]
        assert a["sentido"] is None and ident["sentido"] == A.SENTIDO_NO_APLICA
        if not ident["aplica"]:
            assert a["viaje"] is None and a["vehiculo"] is None and a["conductor"] is None
    # la ALT-002 observada medida en el segmento crítico sí lleva el sentido aproximado y el viaje más cargado
    (por_segmento,) = alt002([hora(7, 600, 10, segmento(0.96)), hora(8, 600, 10, segmento(1.04, nro=35))])
    ident = por_segmento["variables"]["identificacion_5_3"]
    campos, _motivo, sentido = A.VARIANTES_5_3[("ALT-002", A.METODO_OCUPACION_SEGMENTO)]
    assert ident["aplica"] == list(campos) and ident["sentido"] == sentido and ident["resultado"] == "identificado"
    assert (por_segmento["sentido"], por_segmento["viaje"], por_segmento["vehiculo"],
            por_segmento["conductor"]) == ("ida", "5141001", "1234", CONDUCTOR)
    # con el factor de carga (sin segmento medido) la ALT-002 observada sigue siendo de la ruta
    (por_factor,) = alt002([hora(7, 1_200, 10), hora(8, 1_200, 10)])
    ident = por_factor["variables"]["identificacion_5_3"]
    assert ident["aplica"] == [] and ident["sentido"] == A.SENTIDO_NO_APLICA and por_factor["sentido"] is None


# ---------------------------------------------------------------- un viaje de progvehiculos en formato de alerta
def test_viaje_de_fila_estado_retraso_y_zona():
    v = A.viaje_de_fila(fila(4512345.0, 12, 20, vehiculo="SOBUSA45", retraso=23.5, excede="S"))
    assert v["viaje"] == "4512345" and v["vehiculo"] == "SOBUSA45" and v["estado"] == "valido"
    assert v["salida"] == datetime(2025, 10, 15, 12, 20, tzinfo=Z) and v["retraso_min"] == 23.5
    assert v["excede_plazo"] is True and v["pasajeros"] == 30.0 and v["filas_segmento"] is None
    assert A.viaje_de_fila(fila(1, 6, cancelada="S", finalizado="N"))["estado"] == "cancelado"
    assert A.viaje_de_fila(fila(2, 6, finalizado="N"))["estado"] == "sin_finalizar"
    vacio = A.viaje_de_fila({"viaje": 3, "salida": pd.Timestamp("2025-10-15 06:00"), "salida_real": pd.NaT,
                             "numeropasajeros": float("nan"), "filas_segmento": pd.NA, "conductor": None})
    assert vacio["retraso_min"] is None and vacio["pasajeros"] is None and vacio["filas_segmento"] is None
    assert vacio["conductor"] is None and vacio["salida"].tzinfo is not None


def test_el_conductor_solo_sale_como_seudonimo():
    d = pd.DataFrame({"viaje": [10, 11], "idconductor": [77.0, None], "salida": [datetime(2025, 10, 15, 6)] * 2})
    s = F.seudonimizar_viajes(d)
    assert "idconductor" not in s.columns
    assert s["conductor"].tolist() == [seudonimo(77), None]           # 77.0 y 77 dan el mismo seudónimo
    assert A.seudonimo_conductor(77) == A.seudonimo_conductor(77.0) == A.seudonimo_conductor("77")
    assert A.PATRON_SEUDONIMO.match(s["conductor"].iloc[0])
    v = A.viaje_de_fila({"viaje": 10, "conductor": "77"})               # aunque llegue en claro, sale seudónimo
    assert v["conductor"] == seudonimo(77)


def test_sin_secreto_no_hay_conductor(monkeypatch):
    monkeypatch.delenv("SEUDONIMO_SECRETO", raising=False)
    s = F.seudonimizar_viajes(pd.DataFrame({"viaje": [1], "idconductor": [77]}))
    assert s["conductor"].tolist() == [None]


# ---------------------------------------------------------------- ALT-006: el despacho que no salió o salió tarde
def test_alt006_identifica_el_despacho_cancelado_de_la_hora_vacia():
    vs = viajes(fila(100, 11, 50), fila(101, 12, 10, cancelada="S", finalizado="N", conductor=88),
                fila(102, 12, 40, cancelada="S", finalizado="N"), fila(103, 13, 5))
    a = solo(dia({12: {"salidas_observadas": 0}}, viajes=vs), "ALT-006")
    assert (a["viaje"], a["vehiculo"], a["conductor"]) == ("101", "SOBUSA1", seudonimo(88))
    ident = a["variables"]["identificacion_5_3"]
    assert ident["resultado"] == "identificado" and ident["rol_viaje"] == "cancelado"
    assert ident["aplica"] == ["viaje", "vehiculo", "conductor"]
    ventana = a["variables"]["viajes_ventana"]
    assert ventana["total"] == 2 and ventana["cancelado"] == 2 and ventana["valido"] == 0
    assert [x["viaje"] for x in ventana["lista"]] == ["101", "102"]
    assert a["variables"]["ultimo_despacho_previo"]["viaje"] == "100"
    assert "Viaje 101 (vehículo SOBUSA1), salida programada 12:10" in a["explicacion"]
    # nunca el identificador en claro: solo seudónimos válidos en la alerta
    assert all(A.PATRON_SEUDONIMO.match(x["conductor"]) for x in ventana["lista"])


def test_alt006_sin_cancelados_toma_el_despacho_mas_tardio():
    vs = viajes(fila(200, 12, 0, retraso=2), fila(201, 12, 20, retraso=9), fila(202, 12, 40, excede="S", retraso=4),
                fila(203, 12, 50, retraso=30))
    a = solo(dia({12: {"salidas_observadas": 4}, 13: {"salidas_observadas": 4}}, viajes=vs), "ALT-006")
    assert a["viaje"] == "203" and a["variables"]["identificacion_5_3"]["rol_viaje"] == "tardio"
    assert a["variables"]["viajes_ventana"]["tardios"] == 3        # 9 > 5 min de tolerancia, el marcado y el de 30
    assert "despacho tardío" in a["explicacion"]


def test_alt006_tolerancia_de_procesos_decide_quien_es_tardio():
    vs = viajes(fila(300, 12, 0, retraso=9), fila(301, 12, 30, retraso=7))
    ctx = dia({12: {"salidas_observadas": 2}, 13: {"salidas_observadas": 2}}, viajes=vs, tolerancia_tiempo_min=10)
    a = solo(ctx, "ALT-006")
    assert a["viaje"] is None and a["variables"]["identificacion_5_3"]["tolerancia_retraso_min"] == 10.0


def test_alt006_deficit_de_programacion_no_inventa_un_viaje():
    vs = viajes(fila(400, 11, 55), fila(401, 12, 15), fila(402, 13, 20))
    a = solo(dia({12: {"salidas_observadas": 3}, 13: {"salidas_observadas": 3}}, viajes=vs), "ALT-006")
    assert a["viaje"] is None and a["vehiculo"] is None and a["conductor"] is None
    ident = a["variables"]["identificacion_5_3"]
    assert ident["resultado"] == "sin_viaje_cancelado_ni_tardio" and "rol_viaje" not in ident
    assert a["variables"]["ultimo_despacho_previo"]["viaje"] == "400"
    assert "el déficit es de programación" in a["explicacion"]


def test_alt006_sin_viajes_en_la_fuente_lo_dice():
    a = solo(dia({12: {"salidas_observadas": 0}}), "ALT-006")
    assert a["viaje"] is None and a["variables"]["identificacion_5_3"]["resultado"] == "fuente_sin_viajes"
    # una fuente que expone viajes pero no trae ninguno del día no cubre ese día: no es un déficit de programación
    a = solo(dia({12: {"salidas_observadas": 0}}, viajes=[]), "ALT-006")
    assert a["viaje"] is None and a["variables"]["identificacion_5_3"]["resultado"] == "fuente_sin_viajes_del_dia"
    assert "no trae ningún viaje de la ruta en ese día" in a["explicacion"]


def test_alt006_sin_despacho_antes_de_la_ventana_no_dice_que_el_dia_no_tiene_viajes():
    """Episodio de las 5 h y el primer viaje del día a las 6:10: el día sí tiene viajes, pero ninguno en la ventana
    ni antes de ella (déficit de programación)."""
    a = solo(dia({5: {"salidas_observadas": 0}}, viajes=viajes(fila(800, 6, 10))), "ALT-006")
    assert a["viaje"] is None and a["variables"]["identificacion_5_3"]["resultado"] == "sin_viaje_cancelado_ni_tardio"
    assert a["variables"]["ultimo_despacho_previo"] is None
    assert "ni un despacho antes de ella" in a["explicacion"] and "ningún viaje de la ruta" not in a["explicacion"]


# ---------------------------------------------------------------- ALT-009: los viajes con datos faltantes
def _ctx_009(viajes_dia, horas_faltantes=("2025-10-15T14:00:00-05:00",), campos=()):
    datos = {"minutos_sin_datos": 30, "campos_faltantes": list(campos), "horas_faltantes": list(horas_faltantes),
             "fecha": date(2025, 10, 15)}
    return {"ruta": "CL 72", "empresa": "Sobusa", "detectada_en": DIA + timedelta(days=1), "viajes": viajes_dia,
            "datos": datos}


def test_alt009_primero_los_viajes_de_las_horas_faltantes():
    vs = viajes(fila(500, 9, pasajeros=None), fila(501, 14, 10, segmentos=0), fila(502, 14, 40, segmentos=12),
                fila(503, 16, pasajeros=480), fila(504, 17, finalizado="N"),
                fila(505, 18, cancelada="S", pasajeros=None))
    a = solo(_ctx_009(vs), "ALT-009")
    assert (a["viaje"], a["vehiculo"]) == ("501", "SOBUSA1") and a["conductor"] == seudonimo(77)
    faltan = a["variables"]["viajes_con_datos_faltantes"]
    assert faltan["total"] == 4 and faltan["en_horas_faltantes"] == 1 and faltan["programados_en_horas_faltantes"] == 2
    assert [(x["viaje"], x["faltantes"]) for x in faltan["lista"]] == [
        ("501", ["sin_timbradas_segmento"]), ("500", ["sin_numeropasajeros"]), ("503", ["pasajeros_fuera_de_rango"]),
        ("504", ["sin_finalizar"])]                     # el cancelado no cuenta como dato faltante
    assert a["variables"]["identificacion_5_3"]["resultado"] == "identificado"
    assert "sin timbradas de segmento" in a["explicacion"]


def test_alt009_una_hora_sin_viajes_programados_no_es_un_dato_que_falte():
    """Sin servicio programado en la hora (ningún viaje, o solo cancelados) no hay nada que capturar: no alerta."""
    assert not [a for a in A.evaluar_observadas(_ctx_009(viajes(fila(600, 9), fila(601, 15)))) if a["codigo"] ==
                "ALT-009"]
    solo_cancelado = viajes(fila(602, 14, 30, cancelada="S", finalizado="N"))
    assert not [a for a in A.evaluar_observadas(_ctx_009(solo_cancelado)) if a["codigo"] == "ALT-009"]
    # sin los viajes del día (fuente horaria) la hora sigue contando como faltante, como antes
    assert solo(_ctx_009(None), "ALT-009")["variables"]["horas_faltantes"] == ["2025-10-15T14:00:00-05:00"]


def test_alt009_una_fuente_de_viajes_vacia_no_calla_las_horas_faltantes():
    """El día evaluado tiene demanda: si la fuente de viajes no trae ninguno de ese día no lo cubre (réplica o
    exportación desfasada) y eso no prueba que no hubo servicio; ALT-009 (crítica) sale igual, sin viaje."""
    horas = ("2025-10-15T14:00:00-05:00", "2025-10-15T15:00:00-05:00")
    a = solo(_ctx_009([], horas_faltantes=horas), "ALT-009")
    assert a["variables"]["horas_faltantes"] == list(horas) and a["variables"]["horas_sin_viajes_programados"] == []
    assert a["viaje"] is None and a["variables"]["identificacion_5_3"]["resultado"] == "fuente_sin_viajes_del_dia"
    assert "no trae ningún viaje de la ruta en ese día" in a["explicacion"]
    assert solo(_ctx_009(None, horas_faltantes=horas), "ALT-009")["observado"] == a["observado"] == 2


def test_alt009_conserva_solo_las_horas_con_servicio_y_explica_las_demas():
    vs = viajes(fila(603, 14, 5), fila(604, 14, 35), fila(605, 9))
    a = solo(_ctx_009(vs, horas_faltantes=("2025-10-15T14:00:00-05:00", "2025-10-15T16:00:00-05:00")), "ALT-009")
    assert a["variables"]["horas_faltantes"] == ["2025-10-15T14:00:00-05:00"]
    assert a["variables"]["horas_sin_viajes_programados"] == ["2025-10-15T16:00:00-05:00"]
    assert a["viaje"] is None and "están completos en progvehiculos" in a["explicacion"]
    a = solo(_ctx_009(viajes(fila(606, 9)), horas_faltantes=(), campos=("subidas",)), "ALT-009")
    assert "Ningún viaje del día tiene datos faltantes" in a["explicacion"]


def test_alt009_solo_por_frescura_no_tiene_viaje():
    ctx = _ctx_009(viajes(fila(700, 9, pasajeros=None)), horas_faltantes=())
    ctx["datos"]["minutos_sin_datos"] = 3_000
    a = solo(ctx, "ALT-009")
    assert a["viaje"] is None and a["variables"]["identificacion_5_3"]["resultado"] == "solo_frescura"
    ctx["viajes"] = None
    ctx["datos"]["horas_faltantes"] = ["2025-10-15T14:00:00-05:00"]
    assert solo(ctx, "ALT-009")["variables"]["identificacion_5_3"]["resultado"] == "fuente_sin_viajes"


# ---------------------------------------------------------------- las fuentes de viajes (solo lectura)
def motor_falso(filas):
    """Motor que devuelve `filas` a cualquier sentencia que no sea un SET (el SELECT de viajes empieza por WITH)."""
    motor = mock.MagicMock(name="engine")
    conn = motor.connect.return_value.__enter__.return_value
    resultado = mock.MagicMock()
    resultado.mappings.return_value.all.return_value = filas

    def ejecutar(stmt, params=None):
        return mock.MagicMock() if str(stmt).lstrip().upper().startswith("SET") else resultado

    conn.execute.side_effect = ejecutar
    return motor, conn


@pytest.mark.parametrize("con_segmentos", [True, False])
def test_sql_de_viajes_es_un_select_de_lista_blanca_con_parametros(con_segmentos):
    sql = F.sql_viajes_ruta(con_segmentos)
    assert F.validar_solo_select(sql)
    for p in (":ruta", ":proceso", ":desde", ":hasta", ":limite"):
        assert p in sql
    assert ("timbradas_segmentos" in sql) is con_segmentos
    assert "date_trunc('hour', pv.fechasalida) >= CAST(:desde AS timestamp)" in sql    # el índice propuesto 3


def test_fuente_postgres_lee_viajes_en_solo_lectura_y_seudonimiza():
    filas = [{"viaje": 9, "vehiculo": "SOBUSA9", "idconductor": 77, "salida": datetime(2025, 10, 15, 6, 10),
              "salida_real": datetime(2025, 10, 15, 6, 12), "finalizado": "S", "cancelada": "N",
              "excedeplazosalida": None, "numeropasajeros": 25, "filas_segmento": 40}]
    motor, conn = motor_falso(filas)
    f = F.FuentePostgresSoloLectura(url="postgresql+psycopg://lector@host-falso/db", motor=motor)
    d = f.viajes("CRA 54", DIA, DIA + timedelta(days=1))
    assert "idconductor" not in d.columns and d["conductor"].tolist() == [seudonimo(77)]
    sentencias = [" ".join(str(c.args[0]).split()) for c in conn.execute.call_args_list]
    assert sentencias[0] == "SET TRANSACTION READ ONLY" and sentencias[3].startswith("WITH viajes AS")
    assert "timbradas_segmentos" in sentencias[3]                      # la fuente del ciclo cuenta los segmentos
    params = conn.execute.call_args_list[3].args[1]
    assert params["ruta"] == "CRA 54" and params["desde"] == DIA and params["limite"] == F.LIMITE_VIAJES
    conn.rollback.assert_called_once()
    conn.commit.assert_not_called()
    motor2, conn2 = motor_falso([])
    F.FuentePostgresSoloLectura(url="postgresql+psycopg://x@y/z", motor=motor2, tabla="timbradas_consolidado").viajes(
        "CRA 54", DIA, DIA + timedelta(days=1))
    assert "timbradas_segmentos" not in " ".join(str(c.args[0]) for c in conn2.execute.call_args_list)


def _exportacion(carpeta):
    carpeta.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({
        "idprogramacion": [1, 2, 3, 4], "idruta": [16, 16, 16, 2], "idvehiculo": ["SOBUSA1", "SOBUSA2", "SOBUSA3", "X"],
        "idconductor": [77, 88, 99, 11],
        "fechasalida": pd.to_datetime(["2025-10-15 05:50", "2025-10-15 12:10", "2025-10-16 00:00", "2025-10-15 07:00"]),
        "fechainicio": pd.to_datetime(["2025-10-15 05:51", None, "2025-10-16 00:02", "2025-10-15 07:01"]),
        "cancelada": ["N", "S", "N", "N"], "finalizado": ["S", "N", "S", "S"],
        "excedeplazosalida": [None, None, "S", None], "numeropasajeros": [30, None, 20, 15]}).to_parquet(
        carpeta / "progvehiculos.parquet")


def test_catalogos_viajes_de_la_exportacion_sin_conductor_en_claro(tmp_path, monkeypatch):
    _exportacion(tmp_path)
    monkeypatch.setenv("CATALOGOS_DATOS_DIR", str(tmp_path))
    monkeypatch.setenv("CATALOGOS_FUENTE", "archivos")
    catalogos.limpiar_cache()
    d = catalogos.viajes_para_alertas("CRA 54", DIA, DIA + timedelta(days=1))
    assert d["viaje"].tolist() == [1, 2]                                 # la ruta 16 y el 15/10, en orden de salida
    assert "idconductor" not in d.columns and d["conductor"].tolist() == [seudonimo(77), seudonimo(88)]
    assert d["filas_segmento"].isna().all()                              # sin conteo de segmentos fuera del ciclo
    vs = [A.viaje_de_fila(x) for x in d.to_dict("records")]
    assert [v["estado"] for v in vs] == ["valido", "cancelado"] and vs[0]["retraso_min"] == 1.0
    monkeypatch.setenv("CATALOGOS_DATOS_DIR", str(tmp_path / "vacia"))
    with pytest.raises(catalogos.CatalogoNoDisponible):
        catalogos.viajes_para_alertas("CRA 54", DIA, DIA + timedelta(days=1))


def test_la_redeteccion_del_episodio_toma_el_viaje_identificado():
    import uuid

    from app.modelos_db import Alerta

    abierta = Alerta(alert_id=uuid.uuid4(), codigo="ALT-006", origen="observado", estado="nueva",
                     ventana_fin=DIA + timedelta(hours=13), observado=60.0)
    a = {"ventana_fin": DIA + timedelta(hours=14), "observado": 120.0, "viaje": "101", "vehiculo": "SOBUSA1",
         "conductor": seudonimo(88), "variables": {}, "explicacion": "continúa"}
    sesion = mock.MagicMock()
    ejecucion._actualizar_episodio(sesion, abierta, a, None, 1)
    assert (abierta.viaje, abierta.vehiculo, abierta.conductor) == ("101", "SOBUSA1", seudonimo(88))
    sin_viaje = dict(a, ventana_fin=DIA + timedelta(hours=15), viaje=None, vehiculo=None, conductor=None)
    ejecucion._actualizar_episodio(sesion, abierta, sin_viaje, None, 1)
    assert abierta.viaje == "101" and abierta.conductor == seudonimo(88)      # conserva el identificado
    assert sesion.add.call_count == 2                                         # dos entradas «redeteccion»
    # la ALT-002 medida en el segmento crítico trae además el sentido aproximado de su segmento
    abierta_002 = Alerta(alert_id=uuid.uuid4(), codigo="ALT-002", origen="observado", estado="nueva",
                         ventana_fin=DIA + timedelta(hours=8), observado=0.96, sentido="ida")
    regreso = dict(a, ventana_fin=DIA + timedelta(hours=9), sentido="regreso")
    ejecucion._actualizar_episodio(sesion, abierta_002, regreso, None, 1)
    assert (abierta_002.viaje, abierta_002.sentido) == ("101", "regreso")
    ejecucion._actualizar_episodio(sesion, abierta_002, dict(a, ventana_fin=DIA + timedelta(hours=10)), None, 1)
    assert abierta_002.sentido == "regreso"                                   # sin sentido nuevo, conserva el que tenía


def test_viajes_del_dia_prefiere_la_fuente_del_ciclo_y_no_falla_sin_viajes(monkeypatch):
    fallos = []

    class FuenteConViajes:
        def viajes(self, ruta, desde, hasta):
            assert (ruta, desde, hasta) == ("CRA 54", DIA, DIA + timedelta(days=1))
            return pd.DataFrame([fila(9, 6)])

    vs = ejecucion.viajes_del_dia(FuenteConViajes(), "CRA 54", date(2025, 10, 15), fallos)
    assert [v["viaje"] for v in vs] == ["9"] and not fallos

    def sin_catalogo(*_a):
        raise catalogos.CatalogoNoDisponible("sin exportación")

    monkeypatch.setattr(catalogos, "viajes_para_alertas", sin_catalogo)
    assert ejecucion.viajes_del_dia(object(), "CRA 54", date(2025, 10, 15), fallos) is None and not fallos

    class FuenteRota:
        def viajes(self, *_a):
            raise RuntimeError("timeout")

    assert ejecucion.viajes_del_dia(FuenteRota(), "CRA 54", date(2025, 10, 15), fallos) is None
    assert fallos == [{"etapa": "viajes", "ruta": "CRA 54", "error": "timeout"}]
