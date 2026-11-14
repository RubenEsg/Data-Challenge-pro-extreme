"""Unidad del contraste de los consolidados de Extreme con la agregación propia (app/servicios/consolidados.py; §6.1,
§6.3, §7.3 paso 3, §11.2): tolerancias gobernadas, calendario del período, medidas que no dependen de cuántos días
cubre cada lado, incidencias con llave, valor y bloqueante, rango propio de los segmentos y el resumen sin fuente."""
from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime

import pandas as pd
import pytest

from app.servicios import consolidados as C

TOL = dict(C.TOLERANCIAS_POR_DEFECTO)
RUTA = C.CONFIG[C.TABLA_RUTA]
SEG = C.CONFIG[C.TABLA_SEGMENTOS]


# ---------------------------------------------------------------- tolerancias gobernadas
def test_tolerancias_de_la_version_y_por_omision():
    assert C.tolerancias_de(None) == TOL
    assert C.tolerancias_de({"contraste_tolerancia": 0.2, "contraste_viajes_minimos": "10"}) == dict(
        TOL, contraste_tolerancia=0.2, contraste_viajes_minimos=10.0)
    # lo que no es un número positivo no reemplaza el valor por omisión
    assert C.tolerancias_de({"contraste_tolerancia": "x", "contraste_tolerancia_grosera": -1,
                             "contraste_viajes_minimos": float("nan")}) == TOL


@pytest.mark.parametrize("valores", [{"contraste_tolerancia": 0.6}, {"contraste_tolerancia_grosera": 0.1},
                                     {"contraste_tolerancia": 0}, {"contraste_tolerancia_grosera": 11},
                                     {"contraste_viajes_minimos": 0}, {"contraste_viajes_minimos": 2.5},
                                     {"contraste_tolerancia": None}, {"contraste_tolerancia_grosera": "mucho"},
                                     {"contraste_viajes_minimos": [30]}, {"contraste_tolerancia": float("inf")}])
def test_validar_tolerancias_rechaza_las_incoherentes(valores):
    with pytest.raises(ValueError):
        C.validar_tolerancias(dict(TOL, **valores))


def test_validar_tolerancias_acepta_las_coherentes_y_lo_ajeno():
    C.validar_tolerancias(dict(TOL))
    C.validar_tolerancias(dict(TOL, contraste_tolerancia=0.5, contraste_tolerancia_grosera=0.5))
    C.validar_tolerancias({"ocupacion_critica": 0.9})          # sin parámetros del contraste: nada que validar


# ---------------------------------------------------------------- calendario del período
def _vigencias():
    return pd.DataFrame({
        "id_estacionalidad_anio": [1, 2, 3, 4], "proceso": ["sobusa", "sobusa", "sobusa", "otro"],
        "id_estacionalidad": [25, 3, 7, 9],
        "fecha_inicio": [date(2025, 1, 1), date(2025, 12, 8), date(2025, 2, 28), date(2025, 1, 1)],
        "fecha_fin": [date(2025, 12, 31), date(2025, 12, 8), date(2025, 3, 4), date(2025, 12, 31)]})


def test_vigencias_en_el_orden_de_fn_insert_timbradas_anio():
    v = C.vigencias_del_proceso(_vigencias(), "sobusa")
    assert [e for e, _d, _h in v] == [3, 7, 25]          # la de período más corto primero; la de otro proceso no
    assert len(C.vigencias_del_proceso(_vigencias(), None)) == 4


def test_dias_calendario_con_la_estacionalidad_vigente_de_cada_fecha():
    v = C.vigencias_del_proceso(_vigencias(), "sobusa")
    conteo = C.dias_calendario(date(2025, 1, 1), date(2025, 12, 31), v)
    assert sum(conteo.values()) == 365
    assert conteo[(2025, 1, 3)] == 1                      # el 8 de diciembre de 2025 es lunes y es festivo (3)
    assert conteo[(2025, 1, 25)] == 52 - 1 - 1            # los lunes corrientes: 52 menos el festivo y el de Carnaval
    assert sum(n for (a, d, e), n in conteo.items() if e == 7) == 5
    assert C.dias_calendario(date(2025, 1, 2), date(2025, 1, 1), v) == {}


def test_con_dias_por_periodo_y_por_ano():
    v = C.vigencias_del_proceso(_vigencias(), "sobusa")
    ext = pd.DataFrame({"id_ruta": [2, 2], "id_dia_semana": [1, 1], "id_estacionalidad": [25, 3], "n": [5000, 200]})
    C._con_dias(ext, RUTA, (date(2025, 1, 1), date(2025, 12, 31)), v)
    assert ext["dias"].tolist() == [50, 1]
    anual = pd.DataFrame({"id_segmento": [1], "ano": [2025], "id_dia_semana": [1], "id_estacionalidad": [3],
                          "n": [9]})
    C._con_dias(anual, C.CONFIG[C.TABLA_SEGMENTOS_ANIO], None, v)
    assert anual["dias"].tolist() == [1]
    sin = ext.drop(columns=["dias"])
    C._con_dias(sin, RUTA, None, v)                        # sin período no se cuentan días: NaN
    assert sin["dias"].isna().all()


# ---------------------------------------------------------------- contraste de ruta
def _lados():
    """Cinco llaves de la ruta 2 (día ISO × estacionalidad): igual, bajadas +30 % (incidencia), bajadas +80 %
    (grosera), pocos viajes y sin agregación propia; y una de la ruta 16 con viajes por día +25 %."""
    ext = pd.DataFrame({"id_ruta": [2, 2, 2, 2, 2, 16], "id_dia_semana": [1, 2, 3, 4, 5, 1],
                        "id_estacionalidad": [25] * 6,
                        "n": [5000, 5000, 5000, 10, 4000, 2500], "subidas": [400000, 400000, 400000, 800, 1, 200000],
                        "bajadas": [390000, 507000, 702000, 780, 1, 195000], "dias": [50, 50, 50, 50, 50, 50]})
    propia = pd.DataFrame({"id_ruta": [2, 2, 2, 2, 16], "id_dia_semana": [1, 2, 3, 4, 1],
                           "id_estacionalidad": [25] * 5, "n": [300, 300, 300, 3, 120],
                           "subidas": [24000, 24000, 24000, 240, 9600], "bajadas": [23400, 23400, 23400, 234, 9360],
                           "n_bajadas": [300, 300, 300, 3, 120], "dias": [3, 3, 3, 3, 3]})
    return ext, propia


def test_contraste_de_ruta_con_llave_valor_y_bloqueante():
    ext, propia = _lados()
    r = C.contrastar(ext, propia, RUTA, TOL, "abcd1234:timbradas_consolidado", "sobusa")
    res = r.resumen
    assert (res["llaves"], res["comparadas"], res["sin_agregacion_propia"], res["pocos_viajes"]) == (6, 4, 1, 1)
    por = {(i["llave"]["id_ruta"], i["llave"]["id_dia_semana"], i["campo"]): i for i in r.incidencias}
    assert set(por) == {(2, 2, "promedio_bajadas"), (2, 3, "promedio_bajadas"), (16, 1, "viajes_por_dia")}
    moderada, grosera, viajes = por[(2, 2, "promedio_bajadas")], por[(2, 3, "promedio_bajadas")], por[
        (16, 1, "viajes_por_dia")]
    assert moderada["bloqueante"] is False and grosera["bloqueante"] is True and viajes["bloqueante"] is False
    assert grosera["llave"] == {"id_ruta": 2, "id_dia_semana": 3, "id_estacionalidad": 25, "proceso": "sobusa"}
    assert grosera["valor"] == "140.4000" and grosera["fila"] is None and grosera["codigo"] == "CONTR-001"
    assert grosera["dimension"] == "consistencia" and grosera["lote"] == "abcd1234:timbradas_consolidado"
    assert "80.0%" in grosera["detalle"] and "fuera del análisis" in grosera["detalle"]
    assert "30.0%" in moderada["detalle"] and "fuera del análisis" not in moderada["detalle"]
    assert res["diferencias"] == 3 and res["groseras"] == 1 and res["llaves_bloqueadas"] == 1
    assert res["por_campo"] == {"promedio_bajadas": 2, "viajes_por_dia": 1}


def test_contraste_con_las_tolerancias_de_la_version():
    ext, propia = _lados()
    laxa = C.contrastar(ext, propia, RUTA, dict(TOL, contraste_tolerancia=0.85, contraste_tolerancia_grosera=0.9),
                        "L", None)
    assert laxa.incidencias == [] and laxa.resumen["tolerancias"]["contraste_tolerancia"] == 0.85
    estricta = C.contrastar(ext, propia, RUTA, dict(TOL, contraste_viajes_minimos=1), "L", None)
    assert estricta.resumen["pocos_viajes"] == 0 and "proceso" not in estricta.incidencias[0]["llave"]


def test_contraste_sin_bajadas_propias_no_las_compara():
    ext, propia = _lados()
    propia = propia.drop(columns=["bajadas", "n_bajadas"])
    r = C.contrastar(ext, propia, RUTA, TOL, "L")
    assert {i["campo"] for i in r.incidencias} == {"viajes_por_dia"}


def test_contraste_sin_agregacion_propia_cuenta_las_llaves():
    ext, _ = _lados()
    r = C.contrastar(ext, pd.DataFrame(columns=["id_ruta", "id_dia_semana", "id_estacionalidad", "n"]), RUTA, TOL, "L")
    assert r.incidencias == [] and r.resumen["sin_agregacion_propia"] == 6 and r.resumen["comparadas"] == 0


def test_sin_estacionalidad_vuelve_a_sumar_los_dos_lados():
    """H1: el histórico propio sin id_estacionalidad se contrasta por día ISO, sumando las estacionalidades (y los
    días, porque cada fecha tiene una sola estacionalidad)."""
    ext = pd.DataFrame({"id_ruta": [2, 2], "id_dia_semana": [1, 1], "id_estacionalidad": [25, 3], "n": [5000, 100],
                        "subidas": [400000, 8000], "bajadas": [390000, 7800], "dias": [50, 1]})
    propia = pd.DataFrame({"id_ruta": [2], "id_dia_semana": [1], "id_estacionalidad": [None], "n": [5100.0],
                           "subidas": [408000.0], "bajadas": [397800.0], "n_bajadas": [5100.0], "dias": [51]})
    cfg, e, p = C.sin_estacionalidad(RUTA, ext, propia)
    assert cfg.grano == ("id_ruta", "id_dia_semana") and len(e) == 1 and int(e["dias"].iloc[0]) == 51
    assert C.contrastar(e, p, cfg, TOL, "L").incidencias == []
    # con estacionalidad en la propia no cambia nada
    assert C.sin_estacionalidad(RUTA, ext, propia.assign(id_estacionalidad=25))[0] is RUTA


# ---------------------------------------------------------------- contraste de segmentos (sin la hora; rango por hora)
ANUAL = C.CONFIG[C.TABLA_SEGMENTOS_ANIO]


def _segmentos(**cambios) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Los segmentos 11 y 12 un lunes corriente: 100 viajes en Extreme y 50 propios, con 5 subidas, 4 bajadas y 30
    pasajeros por viaje; el 12 trae 3 subidas propias por viaje (máximo 4). `cambios` agrega columnas a los dos lados
    (la hora del bloque, para el rango)."""
    llave = {"id_segmento": [11, 12], "id_dia_semana": [1, 1], "id_estacionalidad": [25, 25], **cambios}
    ext = pd.DataFrame({**llave, "n": [100, 100], "subidas": [500, 500], "bajadas": [400, 400],
                        "pasajeros": [3000, 3000], "dias": [10, 10]})
    propia = pd.DataFrame({**llave, "n": [50, 50], "subidas": [250, 150], "bajadas": [200, 200],
                           "pasajeros": [1500, 1500], "dias": [5, 5], "min_subidas": [0, 0], "max_subidas": [9, 4],
                           "min_bajadas": [0, 0], "max_bajadas": [9, 9], "min_pasajeros": [-30, -30],
                           "max_pasajeros": [90, 90]})
    return ext, propia


def test_sin_estacionalidad_del_rango_quita_la_estacionalidad_del_grano_por_hora():
    """H1 en el rango por hora (CONTR-003): si la agregación propia no trae estacionalidad, la tabla queda con su
    grano_rango sin ella (el grano que puede bloquear no cambia) y los dos lados se vuelven a sumar; si la trae, la
    configuración es la misma. El contraste del rango recibe siempre una Tabla."""
    ext, propia = _segmentos(hora=[7, 7])
    cfg, e, p = C.sin_estacionalidad_del_rango(SEG, ext, propia.assign(id_estacionalidad=None))
    assert isinstance(cfg, C.Tabla) and cfg.grano == SEG.grano
    assert cfg.grano_rango == tuple(c for c in SEG.grano_rango if c != "id_estacionalidad")
    assert "id_estacionalidad" not in e.columns and "id_estacionalidad" not in p.columns
    r = C.contrastar_rango(e, p, cfg, TOL, "L", "sobusa")
    assert r.resumen["grano"] == list(cfg.grano_rango) and r.resumen["fuera_de_rango"] == 1
    assert "id_estacionalidad" not in r.incidencias[0]["llave"]
    # con estacionalidad propia no cambia nada: la misma configuración y los mismos lados
    igual, e2, p2 = C.sin_estacionalidad_del_rango(SEG, ext, propia)
    assert igual is SEG and e2 is ext and p2 is propia


def test_el_grano_que_bloquea_de_los_segmentos_no_lleva_la_hora():
    """H10 también en las tablas por segmento: la comparación que puede bloquear va por segmento × (año) × día ISO ×
    estacionalidad; la hora solo queda en el grano del rango (CONTR-003). La de ruta no mira el rango."""
    assert SEG.grano == ("id_segmento", "id_dia_semana", "id_estacionalidad")
    assert ANUAL.grano == ("id_segmento", "ano", "id_dia_semana", "id_estacionalidad")
    assert SEG.grano_rango == (*SEG.grano, "hora") and ANUAL.grano_rango == (*ANUAL.grano, "hora")
    assert RUTA.grano_rango == () and "hora" not in RUTA.grano
    assert "H10" in SEG.nota and "H10" in ANUAL.nota and "H10" in RUTA.nota
    for tabla in (C.TABLA_SEGMENTOS, C.TABLA_SEGMENTOS_ANIO):
        sin_hora, por_hora = C._SQL_PROPIA[tabla].text, C._SQL_PROPIA_POR_HORA[tabla].text
        assert "hora" not in sin_hora and por_hora.count(", hora") == 2          # SELECT y GROUP BY
        # los días de la llave son sus fechas distintas: sin la hora, una fecha trae una fila por hora de paso
        assert "COUNT(DISTINCT fecha) AS dias" in sin_hora and "COUNT(DISTINCT fecha) AS dias" in por_hora
    assert C.TABLA_RUTA not in C._SQL_PROPIA_POR_HORA


def test_contraste_de_segmentos_promedios_sin_la_hora():
    ext, propia = _segmentos()
    r = C.contrastar(ext, propia, SEG, TOL, "L", "sobusa")
    # el segmento 12: 5 subidas por viaje en Extreme frente a 3 propias (+67 %, grosera); el rango no se mira aquí
    (subidas,) = r.incidencias
    assert (subidas["codigo"], subidas["campo"], subidas["bloqueante"]) == ("CONTR-002", "promedio_subidas", True)
    assert subidas["llave"] == {"id_segmento": 12, "id_dia_semana": 1, "id_estacionalidad": 25, "proceso": "sobusa"}
    assert r.resumen["grano"] == list(SEG.grano) and r.resumen["groseras"] == 1


def test_rango_por_hora_de_los_segmentos_no_bloquea():
    """CONTR-003 (§11.2 «máximos y mínimos … y rango horario»): el promedio por viaje del bloque de Extreme fuera del
    [mínimo, máximo] propio de esa hora. No bloquea (el bloque de Extreme puede ser otro, H10) y su llave lleva la
    hora; una hora de Extreme sin agregación propia solo se cuenta."""
    ext, propia = _segmentos(hora=[7, 7])
    otra_hora = ext.assign(hora=8)                                # un bloque de Extreme que lo propio no tiene
    r = C.contrastar_rango(pd.concat([ext, otra_hora]), propia, SEG, TOL, "L", "sobusa")
    (rango,) = r.incidencias                                       # el 12: 5 subidas por viaje fuera de [0, 4]
    assert (rango["codigo"], rango["campo"], rango["bloqueante"]) == ("CONTR-003", "promedio_subidas", False)
    assert rango["llave"] == {"id_segmento": 12, "id_dia_semana": 1, "id_estacionalidad": 25, "hora": 7,
                              "proceso": "sobusa"}
    assert "[0, 4]" in rango["detalle"] and "H10" in rango["detalle"] and rango["valor"] == "5.0000"
    res = r.resumen
    assert res["grano"] == list(SEG.grano_rango) and "H10" in res["nota"]
    assert (res["llaves"], res["comparadas"], res["sin_agregacion_propia"], res["fuera_de_rango"]) == (4, 2, 2, 1)
    assert "groseras" not in res and "llaves_bloqueadas" not in res


# ---------------------------------------------------------------- el bloque del fin del viaje (H10) por segmento
LUNES_H10 = {"id_dia_semana": 1, "id_estacionalidad": 25}


def _h10(subidas_12: int = 360, viajes_11: int = 120) -> dict[str, pd.DataFrame]:
    """Los segmentos 11 y 12 en tres lunes, 40 viajes por día. Extreme (fn_insert_timbradas_anio) pone los 120 viajes
    de cada segmento en el bloque del FIN del viaje (hora 7). La agregación propia los tiene en la hora de paso: el 11
    a las 5 y a las 6, y el 12 a las 6 y a las 7. Mismos viajes y mismas sumas: 5 subidas por viaje en el 11 y 3 en el
    12. `subidas_12` y `viajes_11` siembran una diferencia real en Extreme."""
    def lado(filas):
        return pd.DataFrame([{**LUNES_H10, "id_segmento": seg, **({"hora": hora} if hora is not None else {}),
                              "n": n, "subidas": s, "bajadas": 4 * n, "pasajeros": 30 * n, **mas}
                             for seg, hora, n, s, mas in filas])

    rango = {"dias": 3, "min_subidas": 0, "max_subidas": 9, "min_bajadas": 0, "max_bajadas": 8, "min_pasajeros": 0,
             "max_pasajeros": 60}
    marca = {"marca": datetime(2026, 1, 10, 8)}
    return {"leido": lado([(11, 7, viajes_11, 5 * viajes_11, marca), (12, 7, 120, subidas_12, marca)]),
            "propia": lado([(11, None, 120, 600, rango), (12, None, 120, 360, rango)]),
            "propia_hora": lado([(11, 5, 60, 330, rango), (11, 6, 60, 270, rango), (12, 6, 60, 200, rango),
                                 (12, 7, 60, 160, rango)])}


def _contraste_del_ciclo(monkeypatch, lados: dict[str, pd.DataFrame]) -> C.Contraste:
    """consolidados._contraste_de de timbradas_segmentos_consolidado con los dos lados ya leídos (sin base)."""
    monkeypatch.setattr(C, "_agregado_fuente", lambda fuente, cfg, ids: lados["leido"].copy())
    monkeypatch.setattr(C, "_periodo", lambda fuente, cfg, ext: None)
    monkeypatch.setattr(C, "_agregado_propio", lambda s, sql, grano, ids, periodo: lados[
        "propia_hora" if "hora" in grano else "propia"].copy())
    return C._contraste_de(_paso(C.TABLA_SEGMENTOS), pd.DataFrame({"id_segmento": [11, 12]}))


def test_segmentos_en_el_bloque_del_fin_del_viaje_no_dan_groseras_falsas_h10(monkeypatch):
    """El defecto: con filas de la liquidación, que pone todos los segmentos del viaje en el bloque de su fin, el
    contraste por hora daba diferencias groseras falsas y dejaba llaves fuera del análisis. Ahora la comparación que
    bloquea suma los bloques sin la hora: mismos viajes y mismas sumas, ninguna diferencia. Por hora solo queda el
    rango, que no bloquea, y el resumen dice cuántos bloques de Extreme no tienen agregación propia en esa hora."""
    lados = _h10()
    r = _contraste_del_ciclo(monkeypatch, lados)
    res = r.resumen
    assert res["grano"] == list(SEG.grano) and (res["llaves"], res["comparadas"]) == (2, 2)
    assert (res["diferencias"], res["groseras"], res["llaves_bloqueadas"]) == (0, 0, 0) and r.incidencias == []
    assert res["sin_agregacion_propia"] == 0 and "H10" in res["nota"] and res["dias_viajes_por_dia"] == C.DIAS_PROPIOS
    hora = res["por_hora"]
    assert hora["grano"] == list(SEG.grano_rango) and (hora["llaves"], hora["sin_agregacion_propia"]) == (2, 1)
    assert (hora["comparadas"], hora["fuera_de_rango"]) == (1, 0) and "no bloqueante" in hora["nota"]
    # con la hora en el grano (lo de antes) esos mismos datos dan groseras falsas: el doble de viajes por día en la
    # única hora que coincide, y la otra llave sin agregación propia
    con_hora = replace(SEG, grano=SEG.grano_rango)
    ext = lados["leido"].drop(columns="marca")
    C._dias_propios(ext, con_hora, lados["propia_hora"])
    antes = C.contrastar(ext, lados["propia_hora"], con_hora, TOL, "L").resumen
    assert antes["groseras"] >= 1 and antes["sin_agregacion_propia"] == 1 and antes["llaves_bloqueadas"] == 1


def test_segmentos_una_diferencia_real_se_sigue_detectando_sin_la_hora(monkeypatch):
    """Lo que no se puede perder: con los bloques en la hora del fin del viaje, una diferencia real de Extreme (el
    segmento 12 con 80 % más subidas por viaje y el 11 con el doble de viajes) sale como CONTR-002 grosera y
    bloqueante en su llave, que ya no lleva la hora."""
    r = _contraste_del_ciclo(monkeypatch, _h10(subidas_12=648, viajes_11=240))
    por = {(i["llave"]["id_segmento"], i["campo"]): i for i in r.incidencias}
    assert set(por) == {(12, "promedio_subidas"), (11, "viajes_por_dia")}
    subidas, viajes = por[(12, "promedio_subidas")], por[(11, "viajes_por_dia")]
    assert subidas["codigo"] == viajes["codigo"] == "CONTR-002" and subidas["bloqueante"] and viajes["bloqueante"]
    assert subidas["llave"] == {"id_segmento": 12, "id_dia_semana": 1, "id_estacionalidad": 25, "proceso": "sobusa"}
    assert subidas["valor"] == "5.4000" and "80.0%" in subidas["detalle"] and "fuera del análisis" in subidas["detalle"]
    assert viajes["valor"] == "80.0000"                    # 240 viajes en los 3 lunes propios de la llave, no en 6
    assert (r.resumen["groseras"], r.resumen["llaves_bloqueadas"]) == (2, 2)


def test_segmentos_sin_estacionalidad_propia_el_rango_tambien_se_suma_sin_ella(monkeypatch):
    """H1 en los dos granos: si la agregación propia no trae estacionalidad, el contraste que bloquea y el rango por
    hora suman los dos lados sin ella."""
    lados = _h10()
    for nombre in ("propia", "propia_hora"):
        lados[nombre] = lados[nombre].assign(id_estacionalidad=None)
    res = _contraste_del_ciclo(monkeypatch, lados).resumen
    assert res["grano"] == ["id_segmento", "id_dia_semana"] and res["comparadas"] == 2 and res["diferencias"] == 0
    assert "H1" in res["nota_estacionalidad"]
    assert res["por_hora"]["grano"] == ["id_segmento", "id_dia_semana", "hora"] and res["por_hora"]["comparadas"] == 1


# ---------------------------------------------------------------- viajes por día de los segmentos (días propios)
def _anual(ano: int, n_ext: int, marca: datetime) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Una llave de timbradas_segmentos_anio con n_ext viajes (5 subidas, 4 bajadas y 30 pasajeros por viaje) y la
    misma llave en la agregación propia: 100 viajes en 10 lunes con los mismos promedios."""
    llave = {"id_segmento": 11, "ano": ano, "id_dia_semana": 1, "id_estacionalidad": 25}
    ext = pd.DataFrame([dict(llave, n=n_ext, subidas=5 * n_ext, bajadas=4 * n_ext, pasajeros=30 * n_ext, marca=marca)])
    propia = pd.DataFrame([dict(llave, n=100, subidas=500, bajadas=400, pasajeros=3000, dias=10, min_subidas=0,
                                max_subidas=9, min_bajadas=0, max_bajadas=8, min_pasajeros=0, max_pasajeros=60)])
    return ext, propia


def test_segmentos_viajes_por_dia_con_los_dias_propios_sin_falsas_groseras():
    """Las tablas por segmento de Extreme y segmento_estadistica_dia salen de timbradas_segmentos y cubren las mismas
    fechas: con los mismos viajes en 10 de los 52 lunes del año no hay diferencia (el calendario del año entero daba una
    grosera falsa); con el doble de viajes, sí."""
    ext, propia = _anual(2025, 100, datetime(2026, 1, 10, 8))
    calendario = ext.copy()
    C._con_dias(calendario, ANUAL, None, [(25, date(2025, 1, 1), date(2025, 12, 31))])
    assert calendario["dias"].tolist() == [52]             # 100 / 52 frente a 100 / 10: lo que daba la grosera falsa
    C._dias_propios(ext, ANUAL, propia, C.ano_abierto(ext))
    assert ext["dias"].tolist() == [10]
    assert C.contrastar(ext, propia, ANUAL, TOL, "L").incidencias == []
    ext, propia = _anual(2025, 200, datetime(2026, 1, 10, 8))
    C._dias_propios(ext, ANUAL, propia, C.ano_abierto(ext))
    (viajes,) = C.contrastar(ext, propia, ANUAL, TOL, "L").incidencias
    assert viajes["campo"] == "viajes_por_dia" and viajes["valor"] == "20.0000" and viajes["bloqueante"] is True


def test_segmentos_el_ano_abierto_no_compara_viajes_por_dia_y_sin_propia_tampoco():
    """El año de la marca más reciente de Extreme está abierto: sus viajes por día no se comparan (el refresco propio
    puede ir un ciclo atrás); sus promedios por viaje, sí. Sin agregación propia no hay días."""
    ext, propia = _anual(2026, 200, datetime(2026, 3, 10, 8))
    assert C.ano_abierto(ext) == 2026 and C.ano_abierto(ext.drop(columns="marca")) is None
    C._dias_propios(ext, ANUAL, propia, C.ano_abierto(ext))
    assert ext["dias"].isna().all()
    r = C.contrastar(ext, propia, ANUAL, TOL, "L")
    assert r.incidencias == [] and r.resumen["comparadas"] == 1
    ext, _ = _anual(2025, 100, datetime(2026, 1, 10, 8))
    C._dias_propios(ext, ANUAL, pd.DataFrame(columns=[*ANUAL.grano, "n"]))
    assert ext["dias"].isna().all()


def test_segmentos_sin_estacionalidad_propia_cuentan_los_dias_en_el_grano_efectivo():
    """H1: si la agregación propia no trae estacionalidad, los dos lados se suman sin ella y los días propios se toman
    en ese grano (antes de sumar, las llaves de Extreme con estacionalidad no encontrarían las propias)."""
    seg = C.CONFIG[C.TABLA_SEGMENTOS]
    llave = {"id_segmento": 11, "id_dia_semana": 1}
    ext = pd.DataFrame([dict(llave, id_estacionalidad=25, n=90, subidas=450, bajadas=360, pasajeros=2700),
                        dict(llave, id_estacionalidad=3, n=10, subidas=50, bajadas=40, pasajeros=300)])
    propia = pd.DataFrame([dict(llave, id_estacionalidad=None, n=50, subidas=250, bajadas=200, pasajeros=1500,
                                dias=10, min_subidas=0, max_subidas=9, min_bajadas=0, max_bajadas=8, min_pasajeros=0,
                                max_pasajeros=60)])
    cfg, e, p = C.sin_estacionalidad(seg, ext, propia)
    C._dias_propios(e, cfg, p)
    assert cfg.grano == ("id_segmento", "id_dia_semana") and e["dias"].tolist() == [10]
    (viajes,) = C.contrastar(e, p, cfg, TOL, "L").incidencias      # 100 viajes en 10 días frente a 50: el doble
    assert viajes["campo"] == "viajes_por_dia" and viajes["valor"] == "10.0000"


def test_una_medida_nula_en_todos_los_bloques_de_extreme_sigue_nula_al_sumarlos_sin_la_hora():
    """Al sumar los bloques de Extreme sin la hora (H10), una medida que viene nula en todos los bloques de la llave
    debe seguir nula, como SUM en SQL, y no compararse. Sumada como 0 daba una diferencia grosera falsa (0,00 frente
    al promedio propio) y bloqueaba la llave; la falta del dato es de la calidad de §6.3, no del contraste. Con algún
    bloque con dato se suman los que lo tienen."""
    seg = C.CONFIG[C.TABLA_SEGMENTOS]
    llave = {"id_segmento": 11, "id_dia_semana": 2, "id_estacionalidad": 25}
    leido = pd.DataFrame([dict(llave, hora=6, n=20.0, subidas=100.0, bajadas=None, pasajeros=400.0),
                          dict(llave, hora=7, n=20.0, subidas=100.0, bajadas=None, pasajeros=400.0),
                          dict(llave, id_segmento=12, hora=6, n=20.0, subidas=100.0, bajadas=None, pasajeros=400.0),
                          dict(llave, id_segmento=12, hora=7, n=20.0, subidas=100.0, bajadas=90.0, pasajeros=400.0)])
    leido["bajadas"] = pd.to_numeric(leido["bajadas"])
    ext = C._reagrupar(leido, seg.grano).set_index("id_segmento")
    assert pd.isna(ext.at[11, "bajadas"]) and ext.at[12, "bajadas"] == 90
    assert ext.loc[11, ["n", "subidas", "pasajeros"]].tolist() == [40, 200, 800]
    propia = pd.DataFrame([dict(llave, n=40, subidas=200, bajadas=180, pasajeros=800, dias=4)])
    ext = ext.reset_index()
    C._dias_propios(ext, seg, propia)
    r = C.contrastar(ext[ext["id_segmento"] == 11], propia, seg, TOL, "L")
    assert r.resumen["comparadas"] == 1 and r.incidencias == [] and r.resumen["llaves_bloqueadas"] == 0
    # vacío, como antes: las columnas del grano y las sumas
    assert list(C._reagrupar(leido.iloc[:0], seg.grano).columns) == [*seg.grano, "n", "subidas", "bajadas", "pasajeros"]


def test_las_tablas_de_segmentos_usan_los_dias_propios_y_la_de_ruta_el_calendario():
    assert C.CONFIG[C.TABLA_SEGMENTOS].dias_propios and ANUAL.dias_propios
    assert not RUTA.dias_propios
    propia = pd.DataFrame([{**{c: 1 for c in ANUAL.grano}, "id_estacionalidad": None, "n": 40, "dias": 4}])
    cfg, _, p = C.sin_estacionalidad(ANUAL, pd.DataFrame(columns=[*ANUAL.grano, "n"]), propia)
    # sin estacionalidad en la propia (H1) la tabla conserva el resto de su configuración
    assert cfg.dias_propios and cfg.por_ano and cfg.grano_rango and "id_estacionalidad" not in cfg.grano
    assert p["dias"].tolist() == [4]


def test_normalizar_lado_completa_las_columnas():
    d = C.normalizar_lado(pd.DataFrame({"id_ruta": [2], "n": ["10"]}), ("id_ruta",), propia=True)
    assert set(C.SUMAS) | set(C.RANGO) <= set(d.columns) and d["n_bajadas"].iloc[0] == 10.0


# ---------------------------------------------------------------- el paso del ciclo sin fuente
def test_en_ciclo_sin_fuente_lo_dice_en_las_tres_tablas(monkeypatch):
    import uuid

    monkeypatch.setattr(C, "fuente_de_la_tabla", lambda tabla: None)
    fallos: list = []
    r = C.en_ciclo(None, uuid.uuid4(), {}, fallos)
    assert set(r["tablas"]) == set(C.TABLAS) and r["resultados"] == {"sin_fuente": 3} and fallos == []
    assert all("FUENTE_DATABASE_URL" in t["detalle"] for t in r["tablas"].values())
    assert r["tolerancias"] == TOL


def test_fuente_de_la_tabla_usa_la_de_la_capa_de_segmentos(monkeypatch):
    from app.servicios import segmentos

    class Base:
        def para_tabla(self, tabla):
            return ("lectura", tabla)

    monkeypatch.setattr(segmentos, "fuente_configurada", lambda: True)
    monkeypatch.setattr(segmentos, "fuente", lambda motor=None: Base())
    assert C.fuente_de_la_tabla(C.TABLA_RUTA) == ("lectura", C.TABLA_RUTA)
    monkeypatch.setattr(segmentos, "fuente_configurada", lambda: False)
    assert C.fuente_de_la_tabla(C.TABLA_RUTA) is None


def test_las_sql_de_la_fuente_son_select_de_la_lista_blanca():
    from app.servicios import fuentes

    for sql in [*C._SQL_FUENTE.values(), *C._SQL_PRIMER_ANO.values()]:
        assert fuentes.validar_solo_select(sql)
    assert set(C.TABLAS) <= set(fuentes.TABLAS_CON_MARCA)
    # la lectura incremental de las tres filtra el proceso en el SQL (las filas de otros operadores no se leen)
    assert set(C.TABLAS) <= set(fuentes.TABLAS_CON_PROCESO)
    assert not hasattr(C, "_SQL_CONTEO")                      # sin count(*) por tabla y proceso en cada ejecución


class _FuenteSinConsultas:
    """Una fuente que no admite ninguna consulta: _sin_filas decide con lo que ya hizo la lectura."""

    proceso = "sobusa"

    def consultar(self, *_a, **_k):
        raise AssertionError("_sin_filas no debe consultar la fuente (count(*) sin índice, H12)")


def _paso(tabla: str, fuente=None):
    import uuid
    from datetime import datetime

    return C.Paso(C.CONFIG[tabla], fuente or _FuenteSinConsultas(), None, uuid.uuid4(), {}, {}, [], datetime.now())


def test_sin_filas_se_decide_sin_contar_las_filas_de_la_fuente():
    """Sin marca previa ni filas leídas, la lectura desde la marca inicial (toda la tabla, solo el proceso) no trajo
    nada: sin_filas_fuente (con H4 en las de segmentos). Con marca previa, o si la ventana solo trajo repetidas, la
    tabla ya entregó filas del proceso: sin_cambios. Ninguna de las dos consulta la fuente."""
    from datetime import datetime
    from types import SimpleNamespace

    vacia = C._sin_filas(_paso(C.TABLA_SEGMENTOS), None, {"leidas": 0})
    assert vacia["resultado"] == "sin_filas_fuente" and "H4" in vacia["detalle"] and "filas_fuente" not in vacia
    ruta = C._sin_filas(_paso(C.TABLA_RUTA), None, {})
    assert ruta["resultado"] == "sin_filas_fuente" and "H4" not in ruta["detalle"]
    previa = SimpleNamespace(marca_agua=datetime(2026, 1, 10, 8))
    assert C._sin_filas(_paso(C.TABLA_RUTA), previa, {"leidas": 0})["resultado"] == "sin_cambios"
    assert C._sin_filas(_paso(C.TABLA_RUTA), None, {"leidas": 7})["resultado"] == "sin_cambios"


def test_los_duplicados_de_un_consolidado_se_reportan_al_responsable(monkeypatch):
    """§6.3 «Unicidad: reportar al responsable del consolidado»: los UNI-001 de una tabla consolidada van por
    ejecucion.reportar_unicidad (el mismo canal y el mismo formato que los del lote del ciclo), con el lote «id8:tabla»,
    y el resumen del reporte queda en el resultado de la tabla."""
    import pandas as pd

    from app.servicios import ejecucion

    reportados: list = []

    def reportar(s, execution_id, lote, errores):
        reportados.append((execution_id, lote, sorted({e["codigo"] for e in errores})))
        return {"reporte_unicidad": {"lote": lote, "llaves_duplicadas": 1}}

    monkeypatch.setattr(ejecucion, "reportar_unicidad", reportar)
    monkeypatch.setattr(ejecucion, "_guardar_errores", lambda *a, **k: None)
    monkeypatch.setattr(C, "_contraste_de", lambda paso, df: C.Contraste([], {"llaves": 0}))
    fila = {"proceso": "sobusa", "id_ruta": 2, "id_dia_semana": 1, "id_estacionalidad": 25, "hora": "07:00:00",
            "hora_inicio": "07:00:00", "hora_fin": "07:15:00", "subidas": 100, "bajadas": 90, "nro_viajes": 10,
            "promedio_subidas": 10.0, "promedio_bajadas": 9.0, "ultima_actualizacion": "2026-01-10 08:00:00"}
    paso = _paso(C.TABLA_RUTA)
    r = C._procesar_filas(paso, pd.DataFrame([fila, fila]))
    assert reportados == [(paso.execution_id, paso.lote, ["UNI-001"])]
    assert paso.lote.endswith(":timbradas_consolidado") and r["errores_por_codigo"]["UNI-001"] == 2
    assert r["reporte_unicidad"] == {"lote": paso.lote, "llaves_duplicadas": 1} and r["filas_validas"] == 0


def _fuente_que_lee(filas: list[dict]):
    """FuentePostgresSoloLectura de timbradas_consolidado (proceso sobusa) con un motor falso: cada SELECT devuelve
    `filas`, así que la lectura incremental real (huellas y deduplicación por llave) corre sobre ellas."""
    from unittest import mock

    from app.servicios import fuentes

    motor = mock.MagicMock(name="engine")
    conn = motor.connect.return_value.__enter__.return_value
    resultado = mock.MagicMock()
    resultado.mappings.return_value.all.return_value = filas
    conn.execute.side_effect = lambda stmt, params=None: (resultado if str(stmt).lstrip().upper().startswith("SELECT")
                                                          else mock.MagicMock())
    return fuentes.FuentePostgresSoloLectura(url="postgresql+psycopg://x@y/z", motor=motor, tabla=C.TABLA_RUTA,
                                             proceso="sobusa")


def test_una_llave_que_la_lectura_deduplico_vuelve_a_la_calidad_y_se_reporta(monkeypatch):
    """6.3-06 «no se corrige; el duplicado se reporta» también en la lectura incremental: con columnas nulas en la
    llave (UNIQUE lo permite) la fuente trae dos filas de la misma llave y fuentes._filtrar_huellas entrega solo la más
    reciente (duplicadas_llave = 1). El resumen de la tabla lo dice, y las dos filas vuelven a la calidad: las dos son
    UNI-001 y van al responsable por ejecucion.reportar_unicidad, como las demás. Sin duplicados no cambia nada."""
    from datetime import time

    from app.servicios import ejecucion

    reportados: list = []

    def reportar(s, execution_id, lote, errores):
        uni = [e for e in errores if e["codigo"] == "UNI-001"]
        reportados.append((lote, len(uni)))
        return {"reporte_unicidad": {"lote": lote, "filas_duplicadas": len(uni)}} if uni else {}

    monkeypatch.setattr(ejecucion, "reportar_unicidad", reportar)
    monkeypatch.setattr(ejecucion, "_guardar_errores", lambda *a, **k: None)
    monkeypatch.setattr(C, "_contraste_de", lambda paso, df: C.Contraste([], {"llaves": 0}))
    monkeypatch.setattr(C, "marca_de_la_tabla", lambda *a: None)
    monkeypatch.setattr(C, "guardar_marca", lambda *a, **k: None)

    def fila(id_ruta, est, subidas, hora_marca):
        return {"id_timbrada_consolidado": hora_marca, "proceso": "sobusa", "id_ruta": id_ruta, "id_dia_semana": 1,
                "id_estacionalidad": est, "hora": time(7), "hora_inicio": time(7), "hora_fin": time(7, 15),
                "subidas": subidas, "bajadas": 90, "nro_viajes": 10, "promedio_subidas": subidas / 10,
                "promedio_bajadas": 9.0, "ultima_actualizacion": datetime(2026, 1, 10, hora_marca)}

    fuente = _fuente_que_lee([fila(2, None, 100, 8), fila(2, None, 120, 9), fila(16, 25, 100, 8)])
    paso = _paso(C.TABLA_RUTA, fuente)
    r = C.procesar_tabla(paso)
    assert fuente.resumen_lectura["duplicadas_llave"] == 1 and len(fuente.repetidas_por_llave) == 2
    assert r["lectura"]["duplicadas_llave"] == 1 and r["lectura"]["entregadas"] == 2 and r["filas"] == 3
    assert r["errores_por_codigo"]["UNI-001"] == 2 and r["reporte_unicidad"]["filas_duplicadas"] == 2
    assert reportados == [(paso.lote, 2)]
    otra = _paso(C.TABLA_RUTA, _fuente_que_lee([fila(2, 25, 100, 8), fila(16, 25, 100, 8)]))
    sin_duplicados = C.procesar_tabla(otra)
    assert sin_duplicados["lectura"]["duplicadas_llave"] == 0 and sin_duplicados["filas"] == 2
    assert "UNI-001" not in sin_duplicados["errores_por_codigo"] and "reporte_unicidad" not in sin_duplicados
    assert reportados[1:] == [(otra.lote, 0)] and len(otra.fuente.repetidas_por_llave) == 0


def test_una_llave_repetida_ya_reportada_no_se_reporta_en_cada_ciclo(monkeypatch):
    """6.3-06 sin reportar dos veces lo mismo: el ciclo siguiente vuelve a leer las filas de la llave repetida (la
    ventana de solape, o toda la tabla con un solo sello, H7), pero con la misma huella la lectura no las entrega, así
    que no vuelven a la calidad ni al responsable y la tabla sale «sin_cambios» (antes se reportaban y se contrastaban
    en cada ciclo). Si la llave cambia (su fila más reciente es otra), la lectura la entrega y se reporta otra vez."""
    from datetime import time
    from types import SimpleNamespace

    from app.servicios import ejecucion

    reportados: list = []

    def reportar(s, execution_id, lote, errores):
        reportados.append(sum(1 for e in errores if e["codigo"] == "UNI-001"))
        return {"reporte_unicidad": {"lote": lote}} if reportados[-1] else {}

    marcas: dict = {}
    monkeypatch.setattr(ejecucion, "reportar_unicidad", reportar)
    monkeypatch.setattr(ejecucion, "_guardar_errores", lambda *a, **k: None)
    monkeypatch.setattr(C, "_contraste_de", lambda paso, df: C.Contraste([], {"llaves": 0}))
    monkeypatch.setattr(C, "marca_de_la_tabla", lambda *a: marcas.get("previa"))
    monkeypatch.setattr(C, "guardar_marca", lambda s, proceso, tabla, marca, estado, *a: marcas.update(
        previa=SimpleNamespace(marca_agua=marca, estado_fuente=estado)))

    def fila(id_ruta, est, subidas, minuto):
        return {"id_timbrada_consolidado": minuto, "proceso": "sobusa", "id_ruta": id_ruta, "id_dia_semana": 1,
                "id_estacionalidad": est, "hora": time(7), "hora_inicio": time(7), "hora_fin": time(7, 15),
                "subidas": subidas, "bajadas": 90, "nro_viajes": 10, "promedio_subidas": subidas / 10,
                "promedio_bajadas": 9.0, "ultima_actualizacion": datetime(2026, 1, 10, 9, minuto)}

    def ciclo(filas):
        return C.procesar_tabla(_paso(C.TABLA_RUTA, _fuente_que_lee(filas)))

    leidas = [fila(2, None, 100, 5), fila(2, None, 120, 10), fila(16, 25, 100, 8)]
    primera = ciclo(leidas)
    assert primera["resultado"] == "contrastado" and primera["errores_por_codigo"]["UNI-001"] == 2
    segunda = ciclo(leidas)                                  # las mismas filas, dentro de la ventana de solape
    assert segunda["resultado"] == "sin_cambios" and "reporte_unicidad" not in segunda and segunda["filas"] == 0
    assert (segunda["lectura"]["entregadas"], segunda["lectura"]["duplicadas_llave"]) == (0, 1)
    cambio = ciclo([fila(2, None, 100, 5), fila(2, None, 130, 12), fila(16, 25, 100, 8)])
    assert cambio["lectura"]["modificadas"] == 1 and cambio["errores_por_codigo"]["UNI-001"] == 2
    assert reportados == [2, 2] and "reporte_unicidad" in cambio


def test_ordenar_incidencias_primero_las_bloqueantes(monkeypatch):
    monkeypatch.setattr(C, "MAX_INCIDENCIAS_POR_TABLA", 2)
    errores = [{"codigo": "A", "bloqueante": False}, {"codigo": "B", "bloqueante": True},
               {"codigo": "C", "bloqueante": None}, {"codigo": "D", "bloqueante": True}]
    assert [e["codigo"] for e in C._ordenar_incidencias(errores)] == ["B", "D"]
