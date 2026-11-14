"""ALT-002 observada con la ocupación ACTUAL por segmento (§5.2 «ocupación observada», §10.1, §5.3 «sentido, viaje,
conductor y vehículo cuando aplique»): la hora que trae su segmento crítico se mide ahí, y la alerta dice el segmento,
el sentido aproximado y el viaje, el vehículo y el conductor (solo seudónimo, §18) del viaje más cargado."""
from datetime import date, datetime

import pytest

from app.servicios import alertas as A
from app.servicios import ejecucion

DIA = date(2025, 10, 16)
CONDUCTOR = "cnd_" + "ab" * 12


def segmento(ocupacion, viajes=8, nro=34, sentido="ida"):
    return {"nro_segmento": nro, "id_segmento": 9_000 + nro, "sentido": sentido, "nro_viajes": viajes,
            "carga_media": 50 * ocupacion, "capacidad": 50.0, "ocupacion_media": ocupacion,
            "carga_total": 50 * ocupacion * viajes,
            "viaje": {"id_viaje": 5_141_001, "vehiculo": "1234", "conductor": CONDUCTOR, "carga": 58.0}}


def hora(h, pasajeros, salidas, seg=None):
    inicio = datetime.combine(DIA, datetime.min.time().replace(hour=h), tzinfo=A.ZONA)
    x = A.contexto_hora(inicio, pasajeros, None, None, None, salidas, None, None)
    if seg is not None:
        x["segmento_critico"] = seg
    return x


def ctx(horas):
    return {"ruta": "CL 72", "empresa": "SOBUSA", "detectada_en": datetime(2025, 10, 16, 21, tzinfo=A.ZONA),
            "capacidad": 50, "factor_carga_por_hora": {h: 0.45 for h in range(4, 21)}, "horas": horas}


def alt002(horas):
    return [a for a in A.evaluar_observadas(ctx(horas)) if a["codigo"] == "ALT-002"]


def test_la_hora_con_segmento_critico_se_mide_ahi_y_la_alerta_dice_el_viaje():
    # con el factor la ocupación sería 0,45 × 600 / (10 × 50) = 54 %: la medida en el segmento crítico manda
    horas = [hora(7, 600, 10, segmento(0.96)), hora(8, 600, 10, segmento(1.04, nro=35)), hora(9, 600, 10)]
    al = alt002(horas)
    assert len(al) == 1
    a = al[0]
    assert a["observado"] == pytest.approx(1.04) and a["variables"]["metodo_ocupacion"] == "segmento_critico"
    assert a["sentido"] == "ida" and a["viaje"] == "5141001" and a["vehiculo"] == "1234"
    assert a["conductor"] == CONDUCTOR and A.PATRON_SEUDONIMO.match(a["conductor"])
    assert a["variables"]["segmento_critico"] == 35 and a["variables"]["viajes_medidos"] == 8
    assert "segmento crítico 35 (ida)" in a["explicacion"] and "subidas y bajadas por segmento" in a["explicacion"]
    assert a["variables"]["ocupacion_por_hora"] == {"07:00": 0.96, "08:00": 1.04}


def test_la_medida_por_segmento_bajo_el_umbral_no_alerta_aunque_el_factor_diera_mas():
    # con el factor: 0,45 × 1.200 / (10 × 50) = 108 %; medido en el segmento crítico: 70 %
    assert alt002([hora(7, 1_200, 10, segmento(0.70)), hora(8, 1_200, 10, segmento(0.70))]) == []


def test_sin_segmento_o_con_pocos_viajes_medidos_rige_el_factor_de_carga():
    al = alt002([hora(7, 1_200, 10, segmento(0.70, viajes=1)), hora(8, 1_200, 10)])
    assert len(al) == 1 and al[0]["variables"]["metodo_ocupacion"] == "factor_carga"
    assert al[0]["observado"] == pytest.approx(1.08) and al[0]["viaje"] is None and al[0]["sentido"] is None
    assert "factor de carga 0,450" in al[0]["explicacion"]


def test_la_hora_de_borde_no_se_evalua_ni_con_el_segmento():
    assert A.segmento_medido(hora(4, 600, 4, segmento(1.2)), A.UMBRALES_POR_DEFECTO) is None
    assert A.segmento_medido(hora(7, 600, 4, segmento(1.2)), A.UMBRALES_POR_DEFECTO) is not None
    assert A.segmento_medido(hora(7, 600, 4, {"ocupacion_media": None}), A.UMBRALES_POR_DEFECTO) is None


def test_el_ciclo_pone_el_segmento_critico_en_las_horas_cerradas_del_contexto():
    c = ctx([hora(7, 600, 10), hora(8, 600, 10)])
    marcadas = ejecucion.con_ocupacion_por_segmento(c, {(DIA, 8): segmento(0.95)})
    assert marcadas == 1 and "segmento_critico" not in c["horas"][0]
    assert c["horas"][1]["segmento_critico"]["ocupacion_media"] == 0.95
    assert ejecucion.con_ocupacion_por_segmento(c, None) == 0
