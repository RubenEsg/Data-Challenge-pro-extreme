"""Pruebas de calidad.validar_lote: las seis dimensiones de §6.3, cuarentena sin corrección y resumen."""
from datetime import UTC, date, datetime

import pandas as pd
import pytest

from app.servicios import calidad as Q


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
