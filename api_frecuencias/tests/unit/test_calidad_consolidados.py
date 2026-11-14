"""Calidad de los consolidados de Extreme que lee el ciclo (§6.3, §7.3 paso 3): CONS-001 con el promedio exacto o el
CEIL de fn_consolidar (H7), esquemas por segmento (pasajeros puede ser negativo, H9), el segmento (REL-004 y REL-006),
el día de la semana (REL-007 y VAL-007 contra la fecha o las fechas de su estacionalidad) y la hora del bloque
(VAL-008)."""
from __future__ import annotations

from datetime import UTC, date, datetime, time

import pandas as pd

from app.servicios import calidad as Q
from app.servicios import fuentes as F

MARCA = datetime(2026, 1, 10, 12, tzinfo=UTC)


def cods(errores, fila=None):
    return sorted(e["codigo"] for e in errores if fila is None or e["fila"] == fila)


def consolidado(**cambios) -> pd.DataFrame:
    d = pd.DataFrame({
        "proceso": ["sobusa"] * 3, "id_ruta": [2, 2, 16], "id_dia_semana": [1, 2, 1], "id_estacionalidad": [25, 25, 3],
        "hora": [time(7), time(7), time(8)], "hora_inicio": [time(7), time(7, 15), time(8, 30)],
        "hora_fin": [time(7, 15), time(7, 30), time(8, 45)], "subidas": [100, 10, 7], "bajadas": [90, 11, 7],
        "nro_viajes": [3, 3, 2], "promedio_subidas": [33.33, 3.33, 3.5], "promedio_bajadas": [30.0, 3.67, 3.5],
        "ultima_actualizacion": [MARCA] * 3})
    for c, v in cambios.items():
        d[c] = v
    return d


def segmentos_consolidado(**cambios) -> pd.DataFrame:
    d = pd.DataFrame({
        "id_segmento": [11, 12], "proceso": ["sobusa"] * 2, "id_ruta": [16, 16], "id_dia_semana": [1, 1],
        "id_estacionalidad": [25, 25], "hora": [time(7), time(7, 15)], "hora_inicio": [time(7), time(7, 15)],
        "hora_fin": [time(7, 15), time(7, 30)], "subidas": [10, 3], "bajadas": [4, 2], "pasajeros": [-50, 30],
        "nro_viajes": [4, 2], "promedio_subidas": [3.0, 1.5], "promedio_bajadas": [1.0, 1.0],
        "promedio_pasajeros": [-12.0, 15.0], "ultima_actualizacion": [MARCA] * 2})
    for c, v in cambios.items():
        d[c] = v
    return d


# ---------------------------------------------------------------- CONS-001 (§6.3 consistencia)
def test_cons001_acepta_el_exacto_y_el_ceil_de_fn_consolidar():
    """H7: fn_consolidar_timbradas_historicas escribe CEIL(Σ / nro_viajes); 100 / 3 = 33,33 y CEIL = 34 son
    coherentes; 35 no lo es."""
    assert Q.validar_lote(consolidado(), "L", esquema="consolidado")[1] == []
    techo = consolidado(promedio_subidas=[34.0, 4.0, 4.0], promedio_bajadas=[30.0, 4.0, 4.0])
    assert Q.validar_lote(techo, "L", esquema="consolidado")[1] == []
    malo = consolidado(promedio_subidas=[35.0, 3.33, 3.5])
    validos, errores = Q.validar_lote(malo, "L", esquema="consolidado")
    assert cods(errores) == ["CONS-001"] and len(validos) == 2
    assert "entero hacia arriba" in errores[0]["detalle"] and errores[0]["campo"] == "promedio_subidas"


def test_esquemas_por_segmento_con_pasajeros_negativos_y_cons001_de_pasajeros():
    ok = segmentos_consolidado()
    assert Q.validar_lote(ok, "L", esquema="segmentos_consolidado")[1] == []          # pasajeros < 0 (H9) no es error
    malo = segmentos_consolidado(promedio_pasajeros=[-12.0, 40.0], pasajeros=[-50, "x"])
    errores = Q.validar_lote(malo, "L", esquema="segmentos_consolidado")[1]
    assert cods(errores, fila=1) == ["VAL-006"]          # sin número no hay promedio que contrastar
    malo = segmentos_consolidado(promedio_pasajeros=[-12.0, 40.0])
    assert cods(Q.validar_lote(malo, "L", esquema="segmentos_consolidado")[1]) == ["CONS-001"]
    negativo = segmentos_consolidado(subidas=[-1, 3])
    assert "VAL-001" in cods(Q.validar_lote(negativo, "L", esquema="segmentos_consolidado")[1])
    assert Q.ESQUEMAS["segmentos_anio"]["llave"] == list(F.LLAVES["timbradas_segmentos_anio"])
    assert Q.ESQUEMAS["segmentos_consolidado"]["llave"] == list(F.LLAVES["timbradas_segmentos_consolidado"])


def test_esquema_anual_exige_ano_y_estacionalidad_anual():
    d = segmentos_consolidado().drop(columns=["id_estacionalidad"])
    errores = Q.validar_lote(d, "L", esquema="segmentos_anio")[1]
    faltan = {e["campo"] for e in errores if e["codigo"] == "COMP-002"}
    assert faltan == {"ano", "id_estacionalidad_anio"}


# ---------------------------------------------------------------- segmento (§7.3 paso 3)
def test_segmento_existe_y_es_de_su_ruta():
    cat = {"segmentos": {11, 12, 21}, "segmentos_ruta": {11: 16, 12: 16, 21: 99}, "idrutas": {16, 99}}
    assert Q.validar_lote(segmentos_consolidado(), "L", esquema="segmentos_consolidado", catalogos=cat)[1] == []
    d = segmentos_consolidado(id_segmento=[21, 77])
    errores = Q.validar_lote(d, "L", esquema="segmentos_consolidado", catalogos=cat)[1]
    assert cods(errores, fila=0) == ["REL-006"] and cods(errores, fila=1) == ["REL-004"]
    rel6 = next(e for e in errores if e["codigo"] == "REL-006")
    assert "ruta 99" in rel6["detalle"] and rel6["llave"]["id_segmento"] == 21 and rel6["bloqueante"] is True


# ---------------------------------------------------------------- día de la semana (§7.3 paso 3)
def _dias():
    vigencias = pd.DataFrame({"id_estacionalidad_anio": [1, 2, 3], "id_estacionalidad": [25, 3, 3],
                              "fecha_inicio": [date(2025, 1, 1), date(2024, 12, 8), date(2025, 12, 8)],
                              "fecha_fin": [date(2025, 12, 31), date(2024, 12, 8), date(2025, 12, 8)]})
    return Q.dias_por_estacionalidad(vigencias)


def test_dias_por_estacionalidad_desde_sus_fechas():
    dias = _dias()
    # el 8 de diciembre de 2024 es domingo (7) y el de 2025 es lunes (1); los días corrientes caen en los siete
    assert dias["dias_estacionalidad"] == {25: frozenset(range(1, 8)), 3: frozenset({1, 7})}
    assert dias["dias_estacionalidad_anio"] == {1: frozenset(range(1, 8)), 2: frozenset({7}), 3: frozenset({1})}
    assert Q.dias_por_estacionalidad(None) == {} and Q.dias_por_estacionalidad(pd.DataFrame()) == {}


def test_val007_dia_de_la_semana_frente_a_las_fechas_de_su_estacionalidad():
    cat = dict(_dias(), dias_semana=set(range(1, 8)))
    assert Q.validar_lote(consolidado(), "L", esquema="consolidado", catalogos=cat)[1] == []
    d = consolidado(id_dia_semana=[1, 2, 3])        # la fila 2 es del festivo 3, que solo cae lunes o domingo
    errores = Q.validar_lote(d, "L", esquema="consolidado", catalogos=cat)[1]
    assert cods(errores) == ["VAL-007"] and errores[0]["fila"] == 2 and errores[0]["bloqueante"] is True
    assert "[1, 7]" in errores[0]["detalle"]
    fuera = consolidado(id_dia_semana=[1, 2, 8])
    assert "REL-007" in cods(Q.validar_lote(fuera, "L", esquema="consolidado", catalogos=cat)[1], fila=2)


def test_val007_con_la_estacionalidad_anual_y_con_la_fecha():
    cat = _dias()
    anual = segmentos_consolidado(id_estacionalidad_anio=[2, 3], ano=[2024, 2025]).drop(columns="id_estacionalidad")
    errores = Q.validar_lote(anual, "L", esquema="segmentos_anio", catalogos=cat)[1]
    assert [(e["fila"], e["codigo"]) for e in errores] == [(0, "VAL-007")]   # el 8-dic-2024 fue domingo, no lunes
    demanda = pd.DataFrame({"ruta": ["CRA 54"] * 2, "fecha": [date(2025, 3, 10)] * 2, "hora": [6, 7],
                            "pasajeros": [10.0, 12.0], "id_dia_semana": [1, 2],
                            "ultima_actualizacion": [pd.Timestamp("2025-03-10 23:00", tz="America/Bogota")] * 2})
    errores = Q.validar_lote(demanda, "L")[1]
    assert [(e["fila"], e["codigo"]) for e in errores] == [(1, "VAL-007")] and "día ISO" in errores[0]["detalle"]


# ---------------------------------------------------------------- hora del bloque (rango horario)
def test_val008_la_hora_es_la_del_bloque():
    assert Q.validar_lote(segmentos_consolidado(), "L", esquema="segmentos_consolidado")[1] == []
    d = consolidado(hora=[time(7), time(6), time(8)])
    errores = Q.validar_lote(d, "L", esquema="consolidado")[1]
    assert [(e["fila"], e["codigo"]) for e in errores] == [(1, "VAL-008")]
    # una franja ya incoherente (VAL-004) no se reporta dos veces
    d = consolidado(hora_inicio=[time(7), time(7, 45), time(8, 30)], hora_fin=[time(7, 15), time(7, 30), time(8, 45)],
                    hora=[time(7), time(5), time(8)])
    assert cods(Q.validar_lote(d, "L", esquema="consolidado")[1]) == ["VAL-004"]


def test_muestra_real_con_los_catalogos_del_dia_sin_falsos_errores():
    """Las 531 filas reales de la muestra (estacionalidad 25, días corrientes, lunes y domingo) pasan VAL-007, VAL-008
    y REL-007 con los catálogos del día."""
    from pathlib import Path

    muestra = pd.read_csv(Path(__file__).resolve().parents[1] / "fixtures" / "consolidado_muestra.csv")
    cat = dict(_dias(), dias_semana=set(range(1, 8)))
    validos, errores = Q.validar_lote(muestra, "muestra", catalogos=cat)
    assert errores == [] and len(validos) == len(muestra)
