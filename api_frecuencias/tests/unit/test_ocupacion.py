"""Ocupación por segmento histórica y actual (§10.1; hallazgo H9; app/servicios/ocupacion.py).

- el método: carga al salir del segmento k acotada en 0 en cada segmento, en el orden de nro_segmento, con un viaje que
  cruza un segmento en dos bloques sumado (E2) y los segmentos sin eventos con la carga del anterior;
- el perfil histórico empaquetado (datos/ocupacion_segmentos_hora.parquet) y el segmento crítico por día de operación y
  hora, con el tipo de día como respaldo y la estacionalidad nula para Sobusa (H1);
- la ocupación observada de las franjas del ciclo, su segmento crítico y el viaje más cargado (conductor seudónimo);
- la restricción reactiva: cuándo aplica, en qué hora y por qué no aplica.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from app.servicios import datos, fuentes, ocupacion

Z = ZoneInfo("America/Bogota")
DIA = date(2025, 10, 15)          # miércoles


def filas(viaje: int, cambios: list[tuple[int, int, int]], *, ruta="CL 72", idruta=21, hora=7, fecha=DIA,
          vehiculo="V-1", conductor=None) -> list[dict]:
    """Filas viaje × segmento [(nro_segmento, subidas, bajadas)] como las entrega leer_carga_segmentos."""
    return [{"ruta": ruta, "idruta": idruta, "fecha": fecha, "hora": hora, "id_viaje": viaje, "vehiculo": vehiculo,
             "conductor": conductor, "terminado": True, "id_segmento": 10_000 + nro, "nro_segmento": nro,
             "subidas": s, "bajadas": b} for nro, s, b in cambios]


# ---------------------------------------------------------------- método
def test_la_carga_se_acota_en_0_en_cada_segmento_y_no_arrastra_la_bajada_de_mas():
    d = pd.DataFrame(filas(1, [(1, 3, 0), (2, 0, 5), (3, 4, 0)]))
    c = ocupacion.cargas_por_segmento(d)
    assert c["carga"].tolist() == [3.0, 0.0, 4.0]          # la literal max(0, Σ) daría [3, 0, 2]
    r = ocupacion.resumen_viajes(c)
    assert int(r.loc[0, "carga_max"]) == 4 and int(r.loc[0, "nro_segmento_critico"]) == 3


def test_un_viaje_que_cruza_un_segmento_en_dos_bloques_se_suma_y_se_ordena_por_nro_segmento():
    d = pd.DataFrame(filas(1, [(2, 1, 0), (1, 5, 0), (2, 2, 1), (3, 0, 4)]))   # el 2 en dos bloques de 15 min (E2)
    c = ocupacion.cargas_por_segmento(d)
    assert c["nro_segmento"].tolist() == [1, 2, 3]
    assert c["subidas"].tolist() == [5, 3, 0] and c["bajadas"].tolist() == [0, 1, 4]
    assert c["carga"].tolist() == [5.0, 7.0, 3.0]


def test_el_tramo_completa_los_segmentos_sin_eventos_con_la_carga_anterior():
    c = ocupacion.cargas_por_segmento(pd.DataFrame(filas(1, [(2, 4, 0), (5, 0, 1)]) + filas(2, [(1, 2, 0)])))
    malla = ocupacion.cargas_en_el_tramo(c)
    uno = malla[malla["id_viaje"] == 1]
    assert uno["nro_segmento"].tolist() == [2, 3, 4, 5]          # solo entre el primero y el último registrado
    assert uno["carga"].tolist() == [4.0, 4.0, 4.0, 3.0]
    assert malla[malla["id_viaje"] == 2]["carga"].tolist() == [2.0]
    assert ocupacion.cargas_en_el_tramo(ocupacion.cargas_por_segmento(pd.DataFrame())).empty


def test_el_segmento_critico_es_el_primero_que_alcanza_la_carga_maxima():
    c = ocupacion.cargas_por_segmento(pd.DataFrame(filas(1, [(1, 4, 0), (2, 0, 0), (3, 1, 1), (4, 0, 4)])))
    r = ocupacion.resumen_viajes(c).iloc[0]
    assert r["carga_max"] == 4 and r["nro_segmento_critico"] == 1 and r["segmentos"] == 4
    assert ocupacion.resumen_viajes(ocupacion.cargas_por_segmento(None)).empty


def test_el_sentido_es_el_mismo_del_reparto_por_segmento_empaquetado():
    """Misma regla que scripts/preparar_segmentos.py (mitad de la longitud acumulada del ciclo)."""
    rep = pd.read_parquet(datos.carpeta_datos() / "reparto_segmentos.parquet",
                          columns=["idruta", "id_segmento", "nro_segmento", "longitud_m", "sentido", "km_inicio"])
    rep = rep.drop_duplicates("id_segmento")
    propios = ocupacion.sentidos(rep.drop(columns=["sentido", "km_inicio"]))
    m = propios.merge(rep[["id_segmento", "sentido", "km_inicio"]], on="id_segmento", suffixes=("", "_reparto"))
    assert len(m) == len(rep) and (m["sentido"] == m["sentido_reparto"]).all()
    assert (m["km_inicio"] - m["km_inicio_reparto"]).abs().max() < 1e-9
    assert set(propios["sentido"]) == {"ida", "regreso"}


# ---------------------------------------------------------------- histórico empaquetado
def test_el_perfil_historico_empaquetado_trae_las_tres_rutas_los_dos_niveles_y_estacionalidad_nula():
    p = ocupacion.perfil_historico()
    assert p is not None and not p.empty
    assert set(p["ruta"]) == {"SILENCIO", "CRA 54", "CL 72"} and set(p["nivel"]) == {"dia_semana", "tipo_dia"}
    dias = p[p["nivel"] == "dia_semana"]
    assert set(dias["id_dia_semana"].astype(int)) == set(range(1, 8)) and dias["hora"].between(4, 20).all()
    assert p.loc[p["nivel"] == "tipo_dia", "id_dia_semana"].isna().all()
    assert p["id_estacionalidad"].isna().all()                 # hallazgo H1: estacionalidades_anio es de otro proceso
    assert (p["carga_p50"] <= p["carga_p90"] + 1e-6).all() and (p["carga_p90"] <= p["carga_max"] + 1e-6).all()
    assert (p["viajes_criticos"] <= p["nro_viajes"]).all() and (p["carga_media"] >= 0).all()
    assert set(p["sentido"]) == {"ida", "regreso"}
    assert ocupacion.catalogo_segmentos().groupby("ruta").size().to_dict() == {"CL 72": 128, "CRA 54": 123,
                                                                               "SILENCIO": 135}


def test_segmento_critico_historico_por_dia_de_operacion_con_su_ocupacion():
    c = ocupacion.segmento_critico_historico("CRA 54", DIA, 6, 50)
    assert c["nivel"] == "dia_semana" and c["id_dia_semana"] == 3 and c["hora"] == 6
    p = ocupacion.perfil_historico()
    celda = p[(p["ruta"] == "CRA 54") & (p["nivel"] == "dia_semana") & (p["id_dia_semana"] == 3) & (p["hora"] == 6)]
    assert c["nro_segmento"] == int(celda.loc[celda["carga_media"].idxmax(), "nro_segmento"])
    assert c["ocupacion_media"] == pytest.approx(c["carga_media"] / 50, abs=1e-3)
    assert c["sentido"] in ("ida", "regreso") and c["periodo"] == ocupacion.PERIODO_HISTORICO
    assert "Segmento crítico histórico" in c["texto"] and f"el {c['nro_segmento']} " in c["texto"]
    # otra capacidad (la gobernada) cambia la ocupación, no el segmento
    c80 = ocupacion.segmento_critico_historico("CRA 54", DIA, 6, 80)
    assert c80["nro_segmento"] == c["nro_segmento"] and c80["ocupacion_media"] < c["ocupacion_media"]


def test_un_festivo_usa_el_dia_7_y_una_celda_con_pocos_dias_el_tipo_de_dia(monkeypatch):
    festivo, domingo = date(2025, 11, 17), date(2025, 11, 16)
    assert ocupacion.segmento_critico_historico("SILENCIO", festivo, 9) == \
        ocupacion.segmento_critico_historico("SILENCIO", domingo, 9)
    assert ocupacion.segmento_critico_historico("SILENCIO", festivo, 9)["id_dia_semana"] == 7
    monkeypatch.setattr(ocupacion, "MIN_DIAS_CELDA", 10_000)
    respaldo = ocupacion.segmento_critico_historico("SILENCIO", DIA, 9)
    assert respaldo["nivel"] == "tipo_dia" and respaldo["tipo_dia"] == 0 and respaldo["id_dia_semana"] is None
    assert "tipo laboral" in respaldo["texto"]
    assert ocupacion.segmento_critico_historico("RUTA X", DIA, 9) is None


def test_sin_perfil_empaquetado_no_hay_segmento_critico(monkeypatch):
    monkeypatch.setattr(datos, "ocupacion_segmentos_historica", lambda: None)
    monkeypatch.setattr(datos, "huella_archivo", lambda nombre: -1.0)
    ocupacion.limpiar_cache()
    try:
        assert ocupacion.segmento_critico_historico("CRA 54", DIA, 7) is None
        assert ocupacion.catalogo_segmentos().empty
    finally:
        ocupacion.limpiar_cache()


# ---------------------------------------------------------------- actual: franjas del ciclo
def lote_hora(hora: int, cargas: list[int], *, primer_viaje: int, ruta="CL 72", idruta=21) -> list[dict]:
    """Viajes de una franja que suben `carga` pasajeros en el segmento 1, bajan la mitad en el 3 y el resto en el 5."""
    salida = []
    for i, carga in enumerate(cargas):
        salida += filas(primer_viaje + i, [(1, carga, 0), (3, 0, carga // 2), (5, 0, carga - carga // 2)],
                        ruta=ruta, idruta=idruta, hora=hora, vehiculo=f"V-{primer_viaje + i}",
                        conductor=f"cnd_{(primer_viaje + i):024x}")
    return salida


def test_ocupacion_observada_por_segmento_marca_el_critico_y_el_viaje_mas_cargado():
    d = pd.DataFrame(lote_hora(7, [40, 50, 45], primer_viaje=1))
    tabla = ocupacion.calcular_observada(d, {"CL 72": 50.0})
    assert sorted(tabla["nro_segmento"].unique()) == [1, 2, 3, 4, 5]
    criticos = tabla[tabla["critico"]]
    assert len(criticos) == 1 and int(criticos["nro_segmento"].iloc[0]) == 1      # el primero con la carga máxima
    uno = tabla[tabla["nro_segmento"] == 2].iloc[0]                                # sin eventos: la carga del 1
    assert uno["carga_media"] == pytest.approx(45.0) and uno["nro_viajes"] == 3
    assert uno["ocupacion_media"] == pytest.approx(0.9) and uno["carga_max"] == 50
    resumen = ocupacion.resumen_por_hora(tabla, d)["CL 72"][(DIA, 7)]
    assert resumen["nro_segmento"] == 1 and resumen["carga_total"] == pytest.approx(135.0)
    assert resumen["ocupacion_media"] == pytest.approx(0.9) and resumen["viajes_terminados"] == 3
    assert resumen["viaje"] == {"id_viaje": 2, "vehiculo": "V-2", "conductor": f"cnd_{2:024x}", "carga": 50.0}
    assert resumen["sentido"] in (None, "ida", "regreso")


def test_franjas_del_lote_son_las_del_ultimo_dia_de_cada_ruta():
    lote = pd.DataFrame({"ruta": ["CL 72", "CL 72", "CL 72", "CRA 54"], "hora": [7, 8, 9, 7],
                         "fecha": [date(2025, 10, 14), DIA, DIA, date(2025, 10, 14)]})
    assert ocupacion.franjas_del_lote(lote) == [("CL 72", DIA, 8), ("CL 72", DIA, 9),
                                                ("CRA 54", date(2025, 10, 14), 7)]
    assert ocupacion.franjas_del_lote(None) == [] and ocupacion.franjas_del_lote(pd.DataFrame()) == []


def test_el_ciclo_de_la_madrugada_mide_tambien_el_dia_que_acaba_de_terminar():
    """Con la captura en vivo, el ciclo programado de las 5:15 ya trae la franja de las 4 h del día en curso (sus
    viajes, de unas 3,5 h, van por la mitad). Con solo el último día del lote nunca se mediría ni guardaría el día
    anterior completo: la ventana es de 24 h hacia atrás desde la franja más reciente de cada ruta."""
    ayer = date(2025, 10, 14)
    lote = pd.DataFrame({"ruta": ["CL 72"] * 17 + ["CL 72", "CRA 54", "CRA 54"],
                         "fecha": [ayer] * 17 + [DIA, date(2025, 10, 12), ayer],
                         "hora": list(range(4, 21)) + [4, 20, 6]})
    franjas = ocupacion.franjas_del_lote(lote)
    cl72 = [(f, h) for r, f, h in franjas if r == "CL 72"]
    assert cl72 == [(ayer, h) for h in range(5, 21)] + [(DIA, 4)]       # 24 h: de ayer a las 5 h a hoy a las 4 h
    assert [(f, h) for r, f, h in franjas if r == "CRA 54"] == [(ayer, 6)]  # lo de antes de la ventana no se relee


def test_una_fecha_datetime64_da_las_mismas_llaves_que_una_date():
    """Las llaves (fecha, hora) de la ocupación observada son date aunque la fuente entregue la fecha como datetime64:
    un Timestamp nunca es igual a un date y la restricción reactiva y ALT-002 no encontrarían la hora."""
    d = pd.DataFrame(lote_hora(8, [48, 50], primer_viaje=1))
    d["fecha"] = pd.to_datetime(d["fecha"])
    resumen = ocupacion.resumen_por_hora(ocupacion.calcular_observada(d, {"CL 72": 50.0}), d)["CL 72"]
    assert list(resumen) == [(DIA, 8)] and type(next(iter(resumen))[0]) is date
    r = ocupacion.restriccion_reactiva(resumen, DIA, datetime(2025, 10, 15, 9, 30, tzinfo=Z), {})
    assert r["aplica"] is True and r["hora_cerrada"] == 8 and r["viajes_terminados"] == 2


def test_el_seudonimo_y_el_vehiculo_no_cambian_con_un_nulo_en_otra_fila(monkeypatch):
    """Un nulo en otra fila vuelve float la columna (700001 -> 700001.0): el mismo conductor conserva su seudónimo y
    el vehículo no se escribe «1234.0»."""
    monkeypatch.setenv("SEUDONIMO_SECRETO", "secreto-de-prueba")
    sin_nulos = fuentes.seudonimizar_conductores(pd.DataFrame({"conductor": [700001, 700002]}))
    con_nulo = fuentes.seudonimizar_conductores(pd.DataFrame({"conductor": [700001, None]}))
    assert con_nulo["conductor"].iloc[0] == sin_nulos["conductor"].iloc[0] and pd.isna(con_nulo["conductor"].iloc[1])
    assert fuentes.identificador_entero(1234.0) == 1234 and fuentes.identificador_entero("SOBUSA491") == "SOBUSA491"
    d = pd.DataFrame(lote_hora(7, [48, 40], primer_viaje=1))
    d["vehiculo"] = [1234] * 3 + [None] * 3
    resumen = ocupacion.resumen_por_hora(ocupacion.calcular_observada(d, {"CL 72": 50.0}), d)["CL 72"][(DIA, 7)]
    assert resumen["viaje"]["id_viaje"] == 1 and resumen["viaje"]["vehiculo"] == "1234"


def test_del_ciclo_sin_viajes_por_segmento_no_escribe_y_dice_por_que():
    lote = pd.DataFrame({"ruta": ["CL 72"], "fecha": [DIA], "hora": [7]})
    r = ocupacion.del_ciclo(None, fuentes.FuenteParquet(), lote, None, {}, None)
    assert r["por_ruta"] == {} and "modo offline" in r["resumen"]["nota"]

    class SinFilas:
        def leer_carga_segmentos(self, franjas):
            return pd.DataFrame(columns=list(fuentes.COLUMNAS_CARGA_SEGMENTOS))

    r = ocupacion.del_ciclo(None, SinFilas(), lote, None, {}, None)
    assert r["por_ruta"] == {} and r["resumen"]["filas"] == 0


def test_la_estacionalidad_actual_sale_del_lote_de_la_lectura_integrada():
    lote = pd.DataFrame({"ruta": ["CL 72", "CL 72", "CRA 54"], "fecha": [DIA, DIA, DIA], "hora": [7, 8, 7],
                         "id_estacionalidad": [12, 12, None]})
    assert ocupacion.estacionalidades_del_lote(lote) == {("CL 72", DIA): 12}
    assert ocupacion.estacionalidades_del_lote(lote.drop(columns=["id_estacionalidad"])) == {}
    assert ocupacion.estacionalidades_del_lote(None) == {}


def test_capacidades_de_las_rutas_son_las_del_plan():
    assert ocupacion.capacidades_de(["CL 72"], {}, None) == {"CL 72": 50.0}
    gobernada = ocupacion.capacidades_de(["CRA 54"], {"capacidad_override.16.TODAS": 60}, 3)
    assert gobernada == {"CRA 54": 60.0}
    assert ocupacion.capacidades_de(["RUTA X"], {}, None) == {"RUTA X": ocupacion.CAPACIDAD_POR_OMISION}


# ---------------------------------------------------------------- restricción reactiva
def observada(ocupacion_media: float, horas=(7, 8), nro_viajes=6, carga_total=330.0) -> dict:
    return {(DIA, h): {"nro_segmento": 34, "id_segmento": 99, "sentido": "ida", "nro_viajes": nro_viajes,
                       "ocupacion_media": ocupacion_media, "carga_total": carga_total, "capacidad": 50.0,
                       "viaje": {"id_viaje": 1, "vehiculo": "V-1", "conductor": None, "carga": 55.0}}
            for h in horas}


def test_la_restriccion_reactiva_aplica_en_la_hora_siguiente_a_la_ultima_cerrada():
    r = ocupacion.restriccion_reactiva(observada(0.95), DIA, datetime(2025, 10, 15, 9, 30, tzinfo=Z), {})
    assert r["aplica"] is True and r["hora_cerrada"] == 8 and r["hora_aplica"] == 9
    assert r["segmento"] == 34 and r["carga_critica_pax_h"] == 330.0 and r["umbral_critico"] == 0.9
    assert "no es un re-pronóstico" in r["naturaleza"] and "95 %" in r["motivo"]
    # si la siguiente ya pasó, la del instante (a lo sumo 2 h después de la cerrada)
    r = ocupacion.restriccion_reactiva(observada(0.95, horas=(7,)), DIA, datetime(2025, 10, 15, 9, 5, tzinfo=Z), {})
    assert r["aplica"] is True and (r["hora_cerrada"], r["hora_aplica"]) == (7, 9)


@pytest.mark.parametrize(("ocup", "instante", "umbrales", "texto"), [
    (0.85, datetime(2025, 10, 15, 9, 30, tzinfo=Z), {}, "por debajo del umbral crítico"),
    (0.95, datetime(2025, 10, 15, 9, 30, tzinfo=Z), {"ocupacion_critica": 0.97}, "por debajo del umbral crítico"),
    (0.95, datetime(2025, 10, 16, 6, 0, tzinfo=Z), {}, "no está en el día del plan"),
    (0.95, datetime(2025, 10, 15, 7, 0, tzinfo=Z), {}, "no hay una hora cerrada"),
    (0.95, datetime(2025, 10, 15, 12, 0, tzinfo=Z), {}, "no sirve para programar"),
    (0.95, None, {}, "no está en el día del plan"),
])
def test_la_restriccion_reactiva_no_aplica_y_dice_por_que(ocup, instante, umbrales, texto):
    r = ocupacion.restriccion_reactiva(observada(ocup), DIA, instante, umbrales)
    assert r["aplica"] is False and texto in r["motivo"]


def test_la_restriccion_reactiva_exige_viajes_medidos_y_no_pasa_de_las_20():
    pocos = ocupacion.restriccion_reactiva(observada(0.95, nro_viajes=1), DIA,
                                           datetime(2025, 10, 15, 9, 30, tzinfo=Z), {})
    assert pocos["aplica"] is False and "al menos 2 viajes" in pocos["motivo"]
    tarde = ocupacion.restriccion_reactiva(observada(0.95, horas=(20,)), DIA,
                                           datetime(2025, 10, 15, 21, 0, tzinfo=Z), {})
    assert tarde["aplica"] is False and "21:00" in tarde["motivo"]
    assert ocupacion.restriccion_reactiva(None, DIA, datetime(2025, 10, 15, 9, tzinfo=Z), {}) is None


# ---------------------------------------------------------------- lectura en solo lectura (fuentes.py)
def test_la_lectura_de_carga_es_un_select_de_la_lista_blanca_con_franjas_enlazadas():
    assert fuentes.validar_solo_select(fuentes._SQL_CARGA_SEGMENTOS)
    for marcador in (":rutas", ":fechas", ":horas", ":proceso", ":limite"):
        assert marcador in fuentes._SQL_CARGA_SEGMENTOS
    assert "cancelada = 'N'" in fuentes._SQL_CARGA_SEGMENTOS


def test_leer_carga_segmentos_pasa_las_franjas_como_arreglos_y_seudonimiza_al_leer(monkeypatch):
    monkeypatch.setenv("SEUDONIMO_SECRETO", "secreto-de-prueba")
    f = fuentes.FuentePostgresSoloLectura(url="postgresql+psycopg://x@localhost:1/x")
    pedidos = []

    def consultar(sql, params):
        pedidos.append((sql, params))
        return pd.DataFrame(lote_hora(7, [10], primer_viaje=5)).assign(conductor=987654)

    monkeypatch.setattr(f, "consultar", consultar)
    d = f.leer_carga_segmentos([("CL 72", DIA, 7), ("CL 72", DIA, 8)])
    sql, params = pedidos[0]
    assert sql is fuentes._SQL_CARGA_SEGMENTOS
    assert params["rutas"] == ["CL 72", "CL 72"] and params["horas"] == [7, 8] and params["fechas"] == [DIA, DIA]
    assert params["proceso"] == "sobusa" and f.resumen_carga == {"franjas": 2, "filas": 3, "truncada": False}
    assert d["conductor"].map(lambda v: bool(re.fullmatch(r"cnd_[0-9a-f]{24}", v))).all()
    assert "987654" not in d.to_csv()                     # el dato en claro no sale de la capa de lectura
    assert f.leer_carga_segmentos([]).empty and len(pedidos) == 1
    monkeypatch.delenv("SEUDONIMO_SECRETO")
    sin_secreto = f.leer_carga_segmentos([("CL 72", DIA, 7)])
    assert sin_secreto["conductor"].isna().all()           # sin secreto no hay seudónimo, nunca el dato en claro
