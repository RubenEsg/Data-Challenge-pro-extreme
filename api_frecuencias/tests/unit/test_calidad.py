"""Pruebas de calidad.validar_lote: las seis dimensiones de §6.3, rechazo sin corrección, llave del registro y
resumen. La muestra real (tests/fixtures/consolidado_muestra.csv) son 531 filas de timbradas_consolidado de la réplica
(bloques de 15 minutos, conteos agregados, sin datos personales), extraídas con
«python -m scripts.reconstruir_desde_replica --muestra-consolidado»."""
from datetime import UTC, date, datetime, time
from pathlib import Path

import pandas as pd
import pytest

from app.servicios import calidad as Q
from app.servicios import fuentes as F

MUESTRA = Path(__file__).resolve().parents[1] / "fixtures" / "consolidado_muestra.csv"


def lote_demanda(n=3):
    ua = pd.Timestamp("2025-03-10 23:59:59", tz="America/Bogota")
    return pd.DataFrame({
        "ruta": ["CRA 54"] * n,
        "fecha": [date(2025, 3, 10)] * n,
        "hora": list(range(6, 6 + n)),
        "pasajeros": [100.0 + i for i in range(n)],
        "salidas": pd.array([5] * n, dtype="Int16"),
        "ultima_actualizacion": [ua] * n,
    })


def lote_consolidado():
    return pd.DataFrame({
        "proceso": [1, 1], "id_ruta": [16, 21], "id_dia_semana": [1, 1], "id_estacionalidad": [3, 3], "hora": [7, 7],
        "hora_inicio": ["07:00:00", "07:00:00"], "hora_fin": ["07:59:59", "07:59:59"],
        "subidas": [300, 200], "bajadas": [280, 190], "nro_viajes": [10, 8],
        "promedio_subidas": [30.0, 25.0], "promedio_bajadas": [28.0, 23.75],
        "ultima_actualizacion": [datetime(2025, 3, 10, 12, tzinfo=UTC)] * 2,
    })


def cods(errores):
    return {e["codigo"] for e in errores}


def test_lote_limpio_pasa_completo():
    df = lote_demanda()
    validos, errores = Q.validar_lote(df, "L1")
    assert errores == [] and len(validos) == 3
    v2, e2 = Q.validar_lote(lote_consolidado(), "L2")
    assert e2 == [] and len(v2) == 2


def test_completitud_campo_nulo_y_columna_faltante():
    df = lote_demanda()
    df.loc[1, "pasajeros"] = None
    validos, errores = Q.validar_lote(df, "L1")
    e = [x for x in errores if x["codigo"] == "COMP-001"]
    assert len(e) == 1 and e[0]["fila"] == 1 and e[0]["campo"] == "pasajeros" and e[0]["dimension"] == "completitud"
    assert e[0]["lote"] == "L1" and e[0]["bloqueante"] is True
    assert list(validos.index) == [0, 2]
    validos, errores = Q.validar_lote(lote_demanda().drop(columns=["hora"]), "L1")
    assert "COMP-002" in cods(errores) and len(validos) == 0


def test_validez_conteos_hora_fecha_y_capacidad():
    df = lote_demanda(4)
    df.loc[0, "pasajeros"] = -3
    df.loc[1, "hora"] = 25
    df.loc[2, "ultima_actualizacion"] = pd.Timestamp("2025-03-09 10:00", tz="America/Bogota")
    df["capacidad"] = [50, 50, 50, 0]
    validos, errores = Q.validar_lote(df, "L1")
    assert {"VAL-001", "VAL-002", "VAL-003", "VAL-005"} <= cods(errores)
    assert all(e["dimension"] == "validez" for e in errores if e["codigo"].startswith("VAL"))
    assert len(validos) == 0


def test_validez_franja_incoherente_en_consolidado():
    df = lote_consolidado()
    df.loc[0, "hora_inicio"] = "08:30:00"
    _, errores = Q.validar_lote(df, "L1")
    assert "VAL-004" in cods(errores)


def test_unicidad_reporta_todas_las_filas_duplicadas_sin_corregir():
    df = pd.concat([lote_demanda(2), lote_demanda(1)], ignore_index=True)
    validos, errores = Q.validar_lote(df, "L1")
    dup = [e for e in errores if e["codigo"] == "UNI-001"]
    assert sorted(e["fila"] for e in dup) == [0, 2]
    assert list(validos.index) == [1]
    assert df.shape == (3, 6)            # el lote original no se modifica


def test_consistencia_promedios_y_viajes():
    df = lote_consolidado()
    df.loc[0, "promedio_subidas"] = 45.0          # 300 / 10 = 30
    df.loc[1, "nro_viajes"] = 0
    df.loc[1, "promedio_subidas"] = None
    df.loc[1, "promedio_bajadas"] = None
    validos, errores = Q.validar_lote(df, "L1")
    assert {"CONS-001", "CONS-002"} <= cods(errores)
    assert len(validos) == 0
    d = lote_demanda()
    d.loc[0, "salidas"] = 0
    _, errores = Q.validar_lote(d, "L1")
    assert "CONS-002" in cods(errores)


def test_oportunidad_no_bloquea_pero_se_registra():
    df = lote_demanda()
    df.loc[0, "ultima_actualizacion"] = pd.Timestamp("2025-03-15 08:00", tz="America/Bogota")
    validos, errores = Q.validar_lote(df, "L1")
    e = [x for x in errores if x["codigo"] == "OPOR-001"]
    assert len(e) == 1 and e[0]["bloqueante"] is False and e[0]["dimension"] == "oportunidad"
    assert len(validos) == 3
    _, errores = Q.validar_lote(lote_demanda(), "L1", ahora=datetime(2025, 3, 10, 12, tzinfo=UTC))
    assert "OPOR-002" in cods(errores)


def test_relacional_ruta_y_estacionalidad():
    df = lote_demanda()
    df.loc[2, "ruta"] = "RUTA FANTASMA"
    validos, errores = Q.validar_lote(df, "L1")
    assert [e["fila"] for e in errores if e["codigo"] == "REL-001"] == [2]
    assert len(validos) == 2
    c = lote_consolidado()
    c.loc[1, "id_ruta"] = 99
    _, errores = Q.validar_lote(c, "L1", catalogos={"estacionalidades": {1, 2}})
    assert {"REL-001", "REL-002"} <= cods(errores)


def test_resumen_y_lote_vacio():
    df = lote_demanda()
    df.loc[0, "pasajeros"] = None
    _, errores = Q.validar_lote(df, "L1")
    r = Q.resumen(df, errores)
    assert r["filas"] == 3 and r["filas_cuarentena"] == 1 and r["errores_por_dimension"] == {"completitud": 1}
    assert r["latencia_media_h"] == pytest.approx(0, abs=0.01)
    v, e = Q.validar_lote(pd.DataFrame(), "L0")
    assert len(v) == 0 and e == []


def test_esquema_desconocido():
    with pytest.raises(ValueError):
        Q.validar_lote(pd.DataFrame({"x": [1]}), "L1")


# ------------------------------------------------------------------ esquema consolidado real (bloques de 15 minutos)
def muestra_consolidado():
    return pd.read_csv(MUESTRA)


def test_muestra_real_sin_falsos_duplicados_ni_falsa_franja_a_medianoche():
    m = muestra_consolidado()
    assert len(m) >= 300
    # varios bloques de 15 min comparten (proceso, ruta, día, estacionalidad, hora): la llave de 5 columnas fallaba
    assert m.duplicated(["proceso", "id_ruta", "id_dia_semana", "id_estacionalidad", "hora"]).sum() > 100
    medianoche = m[(m["hora_fin"] == "00:00:00") & (m["hora_inicio"] > "00:00:00")]
    assert len(medianoche) == 27 and set(medianoche["hora_inicio"]) == {"23:45:00"}
    validos, errores = Q.validar_lote(m, "muestra-real")
    assert [e for e in errores if e["codigo"] in ("UNI-001", "VAL-004")] == []
    assert errores == [] and len(validos) == len(m)
    assert Q.ESQUEMAS["consolidado"]["llave"] == list(F.LLAVES["timbradas_consolidado"])


def test_columnas_time_de_postgresql_y_franja_incoherente():
    m = muestra_consolidado().head(60).copy()
    for c in ("hora", "hora_inicio", "hora_fin"):
        m[c] = [time.fromisoformat(x) for x in m[c]]          # psycopg entrega datetime.time
    assert Q.validar_lote(m, "t")[1] == []
    m.loc[0, "hora_inicio"], m.loc[0, "hora_fin"] = time(8, 30), time(8, 15)
    m.loc[1, "hora"] = "25:00:00"
    m.loc[2, "hora_fin"] = "24:99"
    codigos = sorted((e["fila"], e["codigo"]) for e in Q.validar_lote(m, "t")[1])
    assert codigos == [(0, "VAL-004"), (1, "VAL-002"), (2, "VAL-006")]


def test_duplicado_real_con_la_llave_de_7_columnas():
    m = muestra_consolidado().head(20)
    d = pd.concat([m, m.iloc[[3]]], ignore_index=True)
    dup = [e for e in Q.validar_lote(d, "t")[1] if e["codigo"] == "UNI-001"]
    assert sorted(e["fila"] for e in dup) == [3, 20]
    assert set(dup[0]["llave"]) == set(F.LLAVES["timbradas_consolidado"])


def test_cada_error_trae_llave_valor_y_bloqueante():
    df = lote_demanda()
    df.loc[1, "pasajeros"] = -4
    e = [x for x in Q.validar_lote(df, "L1")[1] if x["codigo"] == "VAL-001"][0]
    assert e["llave"] == {"ruta": "CRA 54", "fecha": "2025-03-10", "hora": 7}
    assert e["valor"] == "-4" and e["bloqueante"] is True and e["campo"] == "pasajeros"
    c = muestra_consolidado().head(5).copy()
    c.loc[2, "subidas"] = None
    e2 = [x for x in Q.validar_lote(c, "L2")[1] if x["codigo"] == "COMP-001"][0]
    assert e2["valor"] is None and e2["llave"]["hora_inicio"] == c.loc[2, "hora_inicio"]
    assert len(e2["llave"]) == 7


def test_relacional_con_los_catalogos_de_la_fuente():
    df = lote_demanda()
    df["id_estacionalidad"] = [25, 25, 99]
    df.loc[0, "ruta"] = "RUTA NUEVA"
    cat = {"rutas": {"CRA 54", "RUTA NUEVA"}, "idrutas": {16, 99}, "estacionalidades": {25}}
    validos, errores = Q.validar_lote(df, "L1", catalogos=cat)
    assert [(e["fila"], e["codigo"]) for e in errores] == [(2, "REL-002")]   # la ruta nueva del catálogo es válida
    assert len(validos) == 2
    c = muestra_consolidado().head(3).copy()
    c.loc[0, "proceso"] = "otro_operador"
    errores = Q.validar_lote(c, "L2", catalogos={"procesos": {"sobusa"}, "estacionalidades": {25}})[1]
    assert [(e["fila"], e["codigo"]) for e in errores] == [(0, "REL-005")]


def test_sin_catalogos_usa_el_catalogo_empaquetado_y_no_una_lista_fija():
    from app.servicios import datos

    assert not hasattr(Q, "RUTAS_VALIDAS") and not hasattr(Q, "IDRUTAS_VALIDAS")
    cat = Q.catalogo_empaquetado()
    assert cat["rutas"] == {r["ruta"] for r in datos.catalogo_rutas()}
    assert cat["idrutas"] == {int(r["idruta"]) for r in datos.catalogo_rutas()}
    assert Q.catalogos_desde_fuente(F.FuenteParquet())["rutas"] == cat["rutas"]


def test_capacidad_del_catalogo_menor_o_igual_a_cero_es_val_005():
    validos, errores = Q.validar_lote(lote_demanda(), "L1", catalogos={"capacidades": {"CRA 54": 0, "CL 72": 50}})
    e = [x for x in errores if x["codigo"] == "VAL-005"]
    assert len(e) == 1 and e[0]["fila"] is None and e[0]["llave"] == {"ruta": "CRA 54"} and e[0]["valor"] == "0"
    assert len(validos) == 3                       # el error es del catálogo: las filas del lote siguen siendo válidas
    assert Q.resumen(lote_demanda(), errores)["errores_de_catalogo"] == 1


def test_oportunidad_usa_ahora_y_no_cuenta_la_carga_inicial_ni_los_resellados():
    df = lote_demanda()
    df["ultima_actualizacion"] = pd.Timestamp("2026-08-14 00:52", tz="America/Bogota")   # recarga, años después
    errores = Q.validar_lote(df, "L1", ahora=datetime(2026, 8, 15, tzinfo=UTC))[1]
    assert [e["codigo"] for e in errores] == ["OPOR-001"] * 3
    df["tipo_llegada"] = ["carga_inicial", "nueva", "tardia"]
    errores = Q.validar_lote(df, "L1", ahora=datetime(2026, 8, 15, tzinfo=UTC))[1]
    assert [e["fila"] for e in errores if e["codigo"] == "OPOR-001"] == [1, 2]
    futuro = Q.validar_lote(df, "L1", ahora=datetime(2026, 8, 13, tzinfo=UTC))[1]
    assert [e["fila"] for e in futuro if e["codigo"] == "OPOR-002"] == [0, 1, 2]
    assert all(not e["bloqueante"] for e in futuro)
    assert not [e for e in Q.validar_lote(df, "L1")[1] if e["codigo"] == "OPOR-002"]     # ahora = reloj de la API


def test_lote_por_segmento_no_se_confunde_con_la_demanda():
    with pytest.raises(ValueError, match="demanda_segmentos"):
        Q.validar_lote(pd.DataFrame({"id_segmento": [1], "pasajeros": [3]}), "L1")
