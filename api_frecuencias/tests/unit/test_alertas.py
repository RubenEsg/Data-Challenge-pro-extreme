"""Pruebas del motor de alertas ALT-001..ALT-010 (§5.2, §5.3), la deduplicación y la máquina de estados."""
from datetime import UTC, datetime

import pytest

from app.servicios import alertas as A

T0 = datetime(2025, 3, 10, 7, 0, tzinfo=UTC)
T1 = datetime(2025, 3, 10, 8, 0, tzinfo=UTC)
CAMPOS_53 = {"id", "codigo", "ruta", "vehiculo", "detectada_en", "ventana_inicio", "ventana_fin", "horizonte_min",
             "severidad", "estado", "observado", "esperado", "umbral", "puntaje", "explicacion", "variables",
             "recomendacion", "asignado_a", "comentarios", "historial", "clave_dedup", "empresa", "sentido", "viaje",
             "conductor"}


def base(**kw):
    """Contexto tranquilo: ninguna regla debe dispararse."""
    c = dict(ruta="CRA 54", detectada_en=T0, ventana_inicio=T0, ventana_fin=T1, horizonte_min=60,
             demanda_prevista=300.0, p10=250.0, p90=350.0, pasajeros_observados=310.0, demanda_patron=300.0,
             capacidad=50, buses_hora_actual=9, buses_hora_recomendado=9, salidas_esperadas=9, salidas_observadas=9,
             minutos_desde_ultimo_despacho=4, headway_programado_min=6.7, minutos_sin_datos=10, campos_faltantes=[],
             wape_movil=0.14,
             consolidado={"subidas": 300, "bajadas": 280, "nro_viajes": 9,
                          "referencia": {"subidas": (290, 30), "bajadas": (270, 30), "nro_viajes": (9, 1)}})
    c.update(kw)
    return c


def codigos(ctx, umbrales=None):
    return {a["codigo"] for a in A.evaluar_alertas(ctx, umbrales)}


def una(ctx, codigo, umbrales=None):
    al = [a for a in A.evaluar_alertas(ctx, umbrales) if a["codigo"] == codigo]
    assert len(al) == 1, f"{codigo} no se disparó"
    return al[0]


def test_contexto_normal_no_dispara_nada():
    assert codigos(base()) == set()


@pytest.mark.parametrize("codigo,cambios,severidad", [
    ("ALT-001", dict(demanda_prevista=420, p90=520, p10=380, pasajeros_observados=None), "preventiva"),
    ("ALT-001", dict(demanda_prevista=480, p90=560, p10=420, pasajeros_observados=None), "critica"),
    ("ALT-002", dict(ocupacion_observada=0.95), "critica"),
    # 350 × 0,85 = 297,5 < P90 350 y P(carga crítica > 297,5) = 53 % ≥ alt003_probabilidad_minima (30 %)
    ("ALT-003", dict(buses_hora_actual=7, buses_hora_recomendado=9), "preventiva"),
    ("ALT-004", dict(demanda_prevista=100, p10=80, p90=120, pasajeros_observados=None, demanda_patron=None,
                     buses_hora_recomendado=6), "informativa"),
    ("ALT-005", dict(pasajeros_observados=150, p10=200), "preventiva"),       # bajo 0,7 × patrón y bajo el P10
    ("ALT-006", dict(minutos_desde_ultimo_despacho=15), "critica"),
    ("ALT-006", dict(salidas_observadas=4), "critica"),                       # déficit 55,6 % > 50 %
    ("ALT-007", dict(pasajeros_observados=420), "preventiva"),
    ("ALT-008", dict(consolidado={"subidas": 900, "bajadas": 280, "nro_viajes": 9,
                                  "referencia": {"subidas": (290, 30)}}), "preventiva"),
    ("ALT-008", dict(consolidado={"subidas": 50, "bajadas": 10, "nro_viajes": 0}), "preventiva"),
    ("ALT-009", dict(minutos_sin_datos=2_880), "critica"),   # 2 períodos × 1.440 min (valor de threshold_config)
    ("ALT-009", dict(campos_faltantes=["subidas"]), "critica"),
    ("ALT-010", dict(wape_movil=0.26, model_id="E11-v1"), "critica"),
])
def test_cada_codigo_se_dispara_con_su_condicion(codigo, cambios, severidad):
    a = una(base(**cambios), codigo)
    assert a["severidad"] == severidad
    assert a["estado"] == "nueva"
    assert CAMPOS_53 <= set(a)
    assert a["explicacion"] and a["recomendacion"]
    if codigo in ("ALT-001", "ALT-004"):
        # alertas de pronóstico: no hay valor observado; la proyección va en esperado (§5.3)
        assert a["observado"] is None and a["esperado"] is not None
    else:
        assert a["observado"] is not None
    assert a["umbral"] is not None
    assert 0.5 <= a["puntaje"] <= 1.0
    if codigo == "ALT-010":
        assert a["clave_dedup"] == "ALT-010|E11-v1|CRA 54|episodio"      # un episodio por modelo y ruta
    else:
        assert a["clave_dedup"] == f"{codigo}|CRA 54|{T0.isoformat()}|{T1.isoformat()}"
    assert a["version_umbrales"] == A.UMBRALES_POR_DEFECTO["version"]


@pytest.mark.parametrize("codigo,cambios", [
    ("ALT-001", dict(p90=449)),                                 # 9 x 50 = 450 de capacidad
    ("ALT-002", dict(ocupacion_observada=0.89)),
    ("ALT-003", dict(buses_hora_actual=9, buses_hora_recomendado=9)),
    ("ALT-004", dict(demanda_prevista=140)),                    # ocupación 31,1 % >= 30 %
    ("ALT-004", dict(demanda_prevista=100, buses_hora_recomendado=9)),   # baja, pero ya está en la oferta recomendada
    ("ALT-005", dict(pasajeros_observados=211, p10=200)),       # caída del 29,7 % < 30 %
    ("ALT-005", dict(pasajeros_observados=1, demanda_patron=5, demanda_prevista=5, p10=0, p90=10)),  # patrón muy bajo
    ("ALT-006", dict(minutos_desde_ultimo_despacho=11, salidas_observadas=8)),
    ("ALT-006", dict(salidas_observadas=4.5)),                  # déficit 50 % = tolerancia: no la supera
    ("ALT-005", dict(pasajeros_observados=150, p10=140)),       # cae 50 % pero queda sobre el P10 calibrado
    ("ALT-007", dict(pasajeros_observados=345)),                # error 15 % pero dentro del intervalo
    ("ALT-008", dict(consolidado={"subidas": 370, "bajadas": 280, "nro_viajes": 9,
                                  "referencia": {"subidas": (290, 30)}})),
    ("ALT-009", dict(minutos_sin_datos=2_879)),               # bajo 2 × 1.440 min
    ("ALT-010", dict(wape_movil=0.20)),
])
def test_cada_codigo_no_se_dispara_bajo_el_umbral(codigo, cambios):
    assert codigo not in codigos(base(**cambios))


def test_alt002_calcula_la_ocupacion_esperada_si_falta():
    a = una(base(demanda_prevista=420, p90=430, p10=400, pasajeros_observados=None, buses_hora_actual=9), "ALT-002")
    assert a["esperado"] == pytest.approx(420 / 450, abs=1e-4)
    assert a["observado"] is None                    # la ocupación esperada no es una observación
    assert a["variables"]["tipo_ocupacion"] == "esperada"


def test_periodo_de_ingesta_por_omision_es_el_de_la_base():
    """El valor por omisión del código es el de threshold_config (migración 0001: 1.440 min, ciclo diario): ALT-009
    por frescura salta a los 2 × 1.440 = 2.880 min, no a los 120."""
    assert A.UMBRALES_POR_DEFECTO["periodo_ingesta_min"] == 1440.0
    assert "ALT-009" not in codigos(base(minutos_sin_datos=130))
    a = una(base(minutos_sin_datos=3_000), "ALT-009")
    assert a["umbral"] == 2_880 and "2.880 min" in a["explicacion"]
    # con el valor de la base pasado explícitamente (como lo hace el ciclo) el resultado es el mismo
    assert una(base(minutos_sin_datos=3_000), "ALT-009", {"periodo_ingesta_min": 1440})["umbral"] == 2_880
    assert "ALT-009" in codigos(base(minutos_sin_datos=130), {"periodo_ingesta_min": 60})


def test_alt010_un_episodio_por_modelo_y_ruta_aunque_cambie_la_ventana():
    a = una(base(wape_movil=0.26, model_id="hgb_x"), "ALT-010")
    b = una(base(wape_movil=0.30, model_id="hgb_x", ventana_inicio=T1, ventana_fin=T1), "ALT-010")
    assert a["clave_dedup"] == b["clave_dedup"] == A.clave_modelo("hgb_x", "CRA 54")
    assert una(base(wape_movil=0.26, model_id="otro"), "ALT-010")["clave_dedup"] != a["clave_dedup"]


def test_alt007_por_debajo_del_intervalo():
    a = una(base(pasajeros_observados=200, demanda_patron=None), "ALT-007")
    assert "por debajo" in a["explicacion"]


def test_umbrales_configurables():
    ctx = base(ocupacion_observada=0.85)
    assert "ALT-002" not in codigos(ctx)
    assert "ALT-002" in codigos(ctx, {"ocupacion_critica": 0.80, "version": "v2"})
    assert una(ctx, "ALT-002", {"ocupacion_critica": 0.80, "version": "v2"})["version_umbrales"] == "v2"


def test_explicacion_incluye_observado_esperado_y_umbral():
    a = una(base(wape_movil=0.26), "ALT-010")
    assert "26,0 %" in a["explicacion"] and "20,0 %" in a["explicacion"]


def test_contexto_vacio_no_falla():
    assert A.evaluar_alertas({}, None) == []


def test_deduplicacion():
    ctx = base(wape_movil=0.3, minutos_sin_datos=500)
    primera = A.evaluar_alertas(ctx)
    segunda = A.evaluar_alertas(ctx)
    assert {a["clave_dedup"] for a in primera} == {a["clave_dedup"] for a in segunda}
    assert A.deduplicar(primera + segunda) == primera
    existentes = {primera[0]["clave_dedup"]}
    assert [a["codigo"] for a in A.deduplicar(segunda, existentes)] == [a["codigo"] for a in segunda[1:]]
    otra_ventana = A.evaluar_alertas(base(wape_movil=0.3, minutos_sin_datos=500, ventana_inicio=T1))
    # otra ventana es otra alerta, salvo ALT-010: la degradación es un episodio del modelo en la ruta
    comunes = {a["clave_dedup"] for a in otra_ventana} & {a["clave_dedup"] for a in primera}
    assert comunes == {A.clave_modelo(None, "CRA 54")}


def test_flujo_completo_de_estados_con_historial():
    alerta = {"id": "a1", "estado": "nueva"}
    estado, h = A.cambiar_estado(alerta, "reconocer", "operador1")
    assert (estado, h["estado_anterior"], h["estado_nuevo"], h["usuario"], h["alerta_id"]) == \
        ("reconocida", "nueva", "reconocida", "operador1", "a1")
    assert alerta["estado"] == "nueva"           # función pura: no modifica la alerta
    estado, h = A.cambiar_estado({"estado": estado}, "comentar", "operador1", comentario="Revisando")
    assert estado == "reconocida" and h["comentario"] == "Revisando"
    estado, h = A.cambiar_estado({"estado": estado}, "asignar", "jefe", asignado_a="despachador2")
    assert estado == "asignada" and h["asignado_a"] == "despachador2"
    estado, _ = A.cambiar_estado({"estado": estado}, "asignar", "jefe", asignado_a="despachador3")
    assert estado == "asignada"
    estado, h = A.cambiar_estado({"estado": estado}, "cerrar", "despachador3", comentario="Bus adicional despachado")
    assert estado == "cerrada" and h["fecha"].tzinfo is not None


@pytest.mark.parametrize("estado", ["nueva", "reconocida", "asignada"])
def test_descartar_desde_cualquier_estado_abierto(estado):
    assert A.cambiar_estado(estado, "descartar", "u", comentario="Falsa alarma")[0] == "descartada"


@pytest.mark.parametrize("estado,accion", [
    ("nueva", "asignar"), ("nueva", "cerrar"), ("reconocida", "reconocer"), ("reconocida", "cerrar"),
    ("asignada", "reconocer"), ("cerrada", "reconocer"), ("cerrada", "comentar"), ("descartada", "asignar"),
    ("descartada", "comentar"), ("nueva", "volar"),
])
def test_transiciones_invalidas_lanzan_error(estado, accion):
    with pytest.raises(A.TransicionInvalida):
        A.cambiar_estado({"estado": estado}, accion, "u", comentario="x", asignado_a="y")


def test_validaciones_de_datos_de_la_accion():
    with pytest.raises(ValueError):
        A.cambiar_estado({"estado": "reconocida"}, "asignar", "u")          # falta asignado_a
    with pytest.raises(ValueError):
        A.cambiar_estado({"estado": "nueva"}, "comentar", "u", comentario=" ")
    with pytest.raises(ValueError):
        A.cambiar_estado({"estado": "nueva"}, "reconocer", "")
    with pytest.raises(A.TransicionInvalida):
        A.cambiar_estado({"estado": "inexistente"}, "reconocer", "u")
