"""ALT-005..ALT-009 con datos observados (§5.2, §5.3, §9.4, §18): cada regla se dispara y NO se dispara en su
frontera, con persistencia, episodios, supresión entre reglas, seudónimo del conductor y estructura completa."""
import struct
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.modelos_db import punto_geojson
from app.servicios import alertas as A

Z = ZoneInfo("America/Bogota")
DIA = datetime(2025, 10, 15, 0, 0, tzinfo=Z)
U = A.UMBRALES_POR_DEFECTO
CAMPOS_53 = {"id", "codigo", "empresa", "ruta", "sentido", "viaje", "conductor", "vehiculo", "detectada_en",
             "ventana_inicio", "ventana_fin", "horizonte_min", "severidad", "estado", "observado", "esperado", "umbral",
             "puntaje", "probabilidad", "metodo_puntaje", "explicacion", "variables", "variables_influyentes",
             "recomendacion", "asignado_a", "comentarios", "historial", "clave_dedup", "origen", "tendencia",
             "tendencia_pendiente", "serie_reciente", "ubicacion"}


def dia(cambios=None, esperado=100.0, p10=80.0, p90=120.0, salidas_esp=10.0, headway=6.0, nuevas=True):
    """Un día tranquilo (4-20 h): real = esperado, salidas = esperadas. cambios: {hora: {campo: valor}}."""
    horas = []
    for h in range(4, 21):
        inicio = DIA + timedelta(hours=h)
        d = A.contexto_hora(inicio, esperado, esperado, p10, p90, salidas_esp, salidas_esp, headway, nueva=nuevas,
                            variables_influyentes=[{"variable": "lag7", "valor": 98.0, "efecto_pasajeros": 3.0}])
        d.update((cambios or {}).get(h, {}))
        horas.append(d)
    return {"ruta": "CRA 54", "empresa": "Sobusa", "detectada_en": DIA + timedelta(days=1, hours=6), "horas": horas}


def obs(ctx, umbrales=None):
    return A.evaluar_observadas(ctx, umbrales)


def codigos(ctx, umbrales=None):
    return sorted(a["codigo"] for a in obs(ctx, umbrales))


def solo(ctx, codigo, umbrales=None):
    al = [a for a in obs(ctx, umbrales) if a["codigo"] == codigo]
    assert len(al) == 1, f"{codigo}: {len(al)} alertas"
    return al[0]


def test_dia_tranquilo_no_alerta():
    assert obs(dia()) == []


# ---------------------------------------------------------------- ALT-005
def test_alt005_caida_sostenida_dos_horas_un_solo_episodio():
    a = solo(dia({8: {"observado": 60.0}, 9: {"observado": 55.0}}), "ALT-005")
    assert a["ventana_inicio"] == DIA + timedelta(hours=8) and a["ventana_fin"] == DIA + timedelta(hours=10)
    assert a["observado"] == 115 and a["esperado"] == 200 and a["umbral"] == pytest.approx(140)
    assert a["variables"]["horas_seguidas"] == 2 and a["horizonte_min"] == 0 and a["origen"] == "observado"
    assert a["clave_dedup"] == f"ALT-005|CRA 54|{(DIA + timedelta(hours=8)).isoformat()}|obs"
    assert "ALT-007" not in codigos(dia({8: {"observado": 60.0}, 9: {"observado": 55.0}}))   # suprimida


def test_alt005_una_sola_hora_no_alerta_por_persistencia():
    assert "ALT-005" not in codigos(dia({8: {"observado": 60.0}}))
    assert "ALT-005" in codigos(dia({8: {"observado": 60.0}}), {"persistencia_horas": 1})


@pytest.mark.parametrize("valor,dispara", [(70.0, False), (69.9, True)])
def test_alt005_frontera_de_caida(valor, dispara):
    ctx = dia({8: {"observado": valor, "p10": 75.0}, 9: {"observado": valor, "p10": 75.0}})
    assert ("ALT-005" in codigos(ctx)) is dispara


def test_alt005_exige_estar_bajo_el_p10_calibrado():
    ctx = dia({8: {"observado": 65.0, "p10": 60.0}, 9: {"observado": 65.0, "p10": 60.0}})
    assert "ALT-005" not in codigos(ctx)
    assert "ALT-005" in codigos(ctx, {"alt005_exigir_p10": 0})


def test_alt005_patron_bajo_no_se_evalua():
    ctx = dia({8: {"observado": 1.0, "esperado": 9.0, "p10": 5.0}, 9: {"observado": 1.0, "esperado": 9.0, "p10": 5.0}})
    assert "ALT-005" not in codigos(ctx)


def test_horas_ya_evaluadas_no_vuelven_a_alertar():
    assert obs(dia({8: {"observado": 60.0}, 9: {"observado": 55.0}}, nuevas=False)) == []


def test_episodio_que_continua_conserva_la_clave_y_crece():
    a1 = solo(dia({8: {"observado": 60.0}, 9: {"observado": 55.0}}), "ALT-005")
    a2 = solo(dia({8: {"observado": 60.0}, 9: {"observado": 55.0}, 10: {"observado": 50.0}}), "ALT-005")
    assert a1["clave_dedup"] == a2["clave_dedup"]
    assert a2["ventana_fin"] == DIA + timedelta(hours=11) and a2["variables"]["horas_seguidas"] == 3


# ---------------------------------------------------------------- ALT-007
def test_alt007_sobre_p90_dos_horas():
    a = solo(dia({15: {"observado": 140.0}, 16: {"observado": 150.0}}), "ALT-007")
    assert a["variables"]["sentido_desviacion"] == "+" and a["umbral"] == 240 and a["observado"] == 290
    assert "P90" in a["explicacion"] and a["severidad"] == "preventiva"


@pytest.mark.parametrize("valor,dispara", [(120.0, False), (120.5, True)])
def test_alt007_frontera_p90(valor, dispara):
    assert ("ALT-007" in codigos(dia({15: {"observado": valor}, 16: {"observado": valor}}))) is dispara


def test_alt007_exige_error_minimo_aunque_salga_de_la_banda():
    ctx = dia({15: {"observado": 112.0, "p90": 110.0}, 16: {"observado": 112.0, "p90": 110.0}})   # error 12 %
    assert "ALT-007" not in codigos(ctx)


def test_alt007_sentidos_alternos_no_persisten():
    assert "ALT-007" not in codigos(dia({15: {"observado": 150.0}, 16: {"observado": 75.0}}))


def test_alt007_por_debajo_si_alt005_no_lo_cubre():
    a = solo(dia({8: {"observado": 75.0}, 9: {"observado": 76.0}}), "ALT-007")   # bajo P10 pero > 0,7 × esperado
    assert a["variables"]["sentido_desviacion"] == "-" and "ALT-005" not in codigos(dia({8: {"observado": 75.0},
                                                                                        9: {"observado": 76.0}}))


# ---------------------------------------------------------------- ALT-006
def test_alt006_hora_sin_salidas_dispara_por_tiempo():
    a = solo(dia({12: {"salidas_observadas": 0}}), "ALT-006")
    assert a["severidad"] == "critica" and a["observado"] == 60 and a["umbral"] == 6 + U["tolerancia_despacho_min"]
    assert "al menos 60 min" in a["explicacion"] and a["variables"]["por_tiempo"] is True
    assert a["variables"]["fuente_tolerancia"] == "threshold_config.tolerancia_despacho_min"


def test_alt006_usa_toleranciatiempo_de_procesos():
    ctx = dict(dia({12: {"salidas_observadas": 0}}), tolerancia_tiempo_min=55)   # 60 > 6 + 55 es falso
    assert "ALT-006" not in codigos(ctx)
    ctx["tolerancia_tiempo_min"] = 53                                            # 60 > 6 + 53
    a = solo(ctx, "ALT-006")
    assert a["variables"]["fuente_tolerancia"] == "Procesos.toleranciatiempo" and a["umbral"] == 59


def test_alt006_toleranciatiempo_cero_usa_el_umbral():
    a = solo(dict(dia({12: {"salidas_observadas": 0}}), tolerancia_tiempo_min=0), "ALT-006")
    assert a["variables"]["fuente_tolerancia"] == "threshold_config.tolerancia_despacho_min"


def test_alt006_deficit_por_conteo_con_persistencia_y_frontera():
    limite = 10 * (1 - U["tolerancia_salidas"])            # 5 salidas: déficit exactamente igual a la tolerancia
    assert "ALT-006" not in codigos(dia({12: {"salidas_observadas": limite}, 13: {"salidas_observadas": limite}}))
    assert "ALT-006" not in codigos(dia({12: {"salidas_observadas": 4}}))          # una sola hora
    a = solo(dia({12: {"salidas_observadas": 4}, 13: {"salidas_observadas": 3}}), "ALT-006")
    assert a["observado"] == 7 and a["esperado"] == 20 and a["variables"]["por_tiempo"] is False


@pytest.mark.parametrize("hora", [4, 20])
def test_alt006_no_se_evalua_en_las_horas_de_borde(hora):
    assert "ALT-006" not in codigos(dia({hora: {"salidas_observadas": 0}}))


def test_alt006_lleva_la_ubicacion_del_despacho():
    punto = {"type": "Point", "coordinates": [-74.8, 10.98]}
    a = solo(dict(dia({12: {"salidas_observadas": 0}}), ubicacion=punto), "ALT-006")
    assert a["ubicacion"] == punto


# ---------------------------------------------------------------- ALT-008
def _consolidado(subidas, referencia, nro_viajes=170, ref_viajes=None):
    return {"fecha": DIA.date(), "inicio": DIA, "fin": DIA + timedelta(days=1), "subidas": subidas,
            "nro_viajes": nro_viajes, "serie": referencia[-6:] + [subidas],
            "referencia_valores": {"subidas": referencia, "nro_viajes": ref_viajes or [170] * len(referencia)}}


def test_alt008_z_robusto_en_la_frontera():
    ref = [1000.0, 1010.0, 990.0, 1005.0, 995.0, 1020.0, 980.0, 1000.0]   # mediana 1000, MAD 10 -> escala 50 (5 %)
    umbral = U["z_anomalia"]
    ctx = dict(dia(), consolidado=_consolidado(1000 + 50 * umbral - 1, ref))
    assert "ALT-008" not in codigos(ctx)
    ctx = dict(dia(), consolidado=_consolidado(1000 + 50 * umbral + 1, ref))
    a = solo(ctx, "ALT-008")
    assert a["variables"]["z_por_campo"]["subidas"] == pytest.approx((50 * umbral + 1) / 50, abs=1e-3)
    assert "z robusto" in a["metodo_puntaje"] and a["clave_dedup"].endswith("|dia")
    assert a["tendencia"] in ("al_alza", "estable", "a_la_baja")


def test_alt008_necesita_referencia_minima():
    ctx = dict(dia(), consolidado=_consolidado(5000.0, [1000.0, 1000.0, 1000.0]))
    assert "ALT-008" not in codigos(ctx)


def test_alt008_subidas_sin_viajes():
    ctx = dict(dia(), consolidado=_consolidado(500.0, [1000.0] * 8, nro_viajes=0))
    assert "ALT-008" in codigos(ctx)


def _con_bajadas(bajadas, referencia):
    cons = _consolidado(1000.0, [1000.0, 1010.0, 990.0, 1005.0, 995.0, 1020.0, 980.0, 1000.0])
    cons["bajadas"] = bajadas
    cons["referencia_valores"]["bajadas"] = referencia
    return cons


def test_alt008_evalua_las_bajadas_con_el_mismo_z_robusto_en_su_frontera():
    """§5.2 «subidas, bajadas o número de viajes atípicos»: con subidas y viajes normales, unas bajadas fuera de
    mediana ± z_anomalia × escala del mismo tipo de día dan ALT-008 con campo «bajadas»; justo dentro, no."""
    ref = [950.0, 960.0, 940.0, 955.0, 945.0, 970.0, 930.0, 950.0]       # mediana 950, MAD 10 -> escala 47,5 (5 %)
    umbral = U["z_anomalia"]
    assert "ALT-008" not in codigos(dict(dia(), consolidado=_con_bajadas(950 - 47.5 * umbral + 1, ref)))
    a = solo(dict(dia(), consolidado=_con_bajadas(950 - 47.5 * umbral - 1, ref)), "ALT-008")
    assert a["variables"]["campo"] == "bajadas" and a["variables"]["bajadas"] == pytest.approx(950 - 47.5 * umbral - 1)
    assert a["variables"]["z_por_campo"]["bajadas"] < -umbral and "bajadas =" in a["explicacion"]
    assert a["umbral"] == pytest.approx(950 - umbral * 47.5, abs=1e-3) and "Límite para bajadas" in a["explicacion"]
    # con los umbrales gobernados de la versión: un z_anomalia mayor ya no la dispara
    assert "ALT-008" not in codigos(dict(dia(), consolidado=_con_bajadas(950 - 47.5 * umbral - 1, ref)),
                                    {"z_anomalia": umbral + 1})


def test_alt008_no_evalua_bajadas_sin_dato_ni_referencia_minima():
    assert "ALT-008" not in codigos(dict(dia(), consolidado=_con_bajadas(None, [950.0] * 8)))
    assert "ALT-008" not in codigos(dict(dia(), consolidado=_con_bajadas(10.0, [950.0] * 3)))


# ---------------------------------------------------------------- ALT-009
@pytest.mark.parametrize("minutos,dispara", [(2 * 1440 - 1, False), (2 * 1440, True)])
def test_alt009_frescura_dos_periodos_de_ingesta(minutos, dispara):
    ctx = dict(dia(), datos={"minutos_sin_datos": minutos, "ultima_llegada": DIA, "referencia": DIA,
                             "campos_faltantes": [], "horas_faltantes": []})
    al = [a for a in obs(ctx, {"periodo_ingesta_min": 1440}) if a["codigo"] == "ALT-009"]
    assert bool(al) is dispara
    if al:
        assert al[0]["clave_dedup"].endswith("|frescura") and al[0]["origen"] == "calidad_datos"


def test_alt009_horas_faltantes_y_campos():
    ctx = dict(dia(), datos={"minutos_sin_datos": 10, "horas_faltantes": ["2025-10-15T14:00:00-05:00"],
                             "campos_faltantes": ["salidas"], "fecha": DIA.date()})
    a = solo(ctx, "ALT-009")
    assert "15/10/2025 14:00" in a["explicacion"] and "salidas" in a["explicacion"]
    assert a["clave_dedup"].endswith("|faltantes")
    assert a["variables"]["horas_faltantes"] == ["2025-10-15T14:00:00-05:00"]


# ---------------------------------------------------------------- estructura §5.3 / §9.4 en todas
def test_todas_las_observadas_traen_la_estructura_completa():
    ctx = dia({8: {"observado": 60.0}, 9: {"observado": 55.0}, 12: {"salidas_observadas": 0},
               15: {"observado": 150.0}, 16: {"observado": 160.0}})
    ctx["consolidado"] = _consolidado(3000.0, [1000.0] * 8)
    ctx["datos"] = {"minutos_sin_datos": 10, "horas_faltantes": ["2025-10-15T14:00:00-05:00"],
                    "fecha": DIA.date()}
    al = obs(ctx)
    assert sorted(a["codigo"] for a in al) == ["ALT-005", "ALT-006", "ALT-007", "ALT-008", "ALT-009"]
    for a in al:
        assert CAMPOS_53 <= set(a), CAMPOS_53 - set(a)
        assert a["observado"] is not None and a["esperado"] is not None and a["umbral"] is not None
        assert a["tendencia"] in ("al_alza", "a_la_baja", "estable", "sin_datos")
        assert a["recomendacion"] and a["explicacion"] and a["metodo_puntaje"]
        assert 0.5 <= a["puntaje"] <= 1.0 and a["horizonte_min"] == 0
        assert a["version_umbrales"] == U["version"]
    a5 = next(a for a in al if a["codigo"] == "ALT-005")
    assert a5["variables_influyentes"][0]["variable"] == "lag7" and a5["serie_reciente"]
    assert a5["tendencia"] == "a_la_baja"


# ---------------------------------------------------------------- utilidades
def test_seudonimo_del_conductor(monkeypatch):
    monkeypatch.setenv("SEUDONIMO_SECRETO", "secreto-de-prueba")
    s1 = A.seudonimo_conductor("CC 12345678")
    assert A.PATRON_SEUDONIMO.match(s1) and "12345678" not in s1
    assert s1 == A.seudonimo_conductor("CC 12345678") and s1 != A.seudonimo_conductor("CC 87654321")
    assert A.seudonimo_conductor(s1) == s1
    monkeypatch.delenv("SEUDONIMO_SECRETO")
    assert A.seudonimo_conductor("Juan Pérez") is None
    a = A.evaluar_alertas({"ruta": "X", "wape_movil": 0.5, "conductor": "Juan Pérez"})[0]
    assert a["conductor"] is None


@pytest.mark.parametrize("serie,etiqueta", [([1, 2, 3, 4], "al_alza"), ([4, 3, 2, 1], "a_la_baja"),
                                            ([2, 2, 2], "estable"), ([5], "sin_datos"), ([], "sin_datos")])
def test_tendencia(serie, etiqueta):
    assert A.tendencia(serie)[0] == etiqueta


def test_probabilidad_con_la_banda():
    assert A.probabilidad_supera(100, 80, 120, 100) == pytest.approx(0.5)
    assert A.probabilidad_supera(100, 80, 120, 120) == pytest.approx(0.1, abs=1e-3)
    a = [x for x in A.evaluar_alertas({"ruta": "X", "demanda_prevista": 480, "p10": 420, "p90": 560, "capacidad": 50,
                                       "buses_hora_actual": 9}) if x["codigo"] == "ALT-001"][0]
    assert 0.5 < a["probabilidad"] < 1 and "Probabilidad" in a["explicacion"]


def test_z_robusto_con_mad_nula_usa_la_escala_minima():
    z, med, esc = A.z_robusto(1100, [1000.0] * 8, 0.05)
    assert med == 1000 and esc == 50 and z == pytest.approx(2.0)


def test_punto_geojson_lee_hexewkb_y_ewkt():
    hexewkb = struct.pack("<BIIdd", 1, 0x20000001, 4326, -1.2, 10.3).hex().upper()   # SRID=4326;POINT(-1.2 10.3)
    assert punto_geojson(hexewkb) == {"type": "Point", "coordinates": [pytest.approx(-1.2), pytest.approx(10.3)]}
    assert punto_geojson("SRID=4326;POINT(-74.8 10.98)") == {"type": "Point", "coordinates": [-74.8, 10.98]}
    assert punto_geojson(None) is None
