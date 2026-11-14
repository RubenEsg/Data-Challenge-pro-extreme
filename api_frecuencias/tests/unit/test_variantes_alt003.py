"""Protocolo sin fuga de ALT-003 (scripts/variantes_alt003.py) y su cableado en el backtest de pronóstico: la tasa base
de las franjas donde puede emitirse, la elección en validación con soporte mínimo, la decisión «informativa» si nada
supera la tasa base y el intervalo bootstrap reproducible."""
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from scripts import backtest_alertas as B
from scripts import variantes_alt003 as V

Z = ZoneInfo("America/Bogota")


def fila(fecha, prob_mediana, positiva, *, alt001=False, cumple=False, ruta="CL 72"):
    """Una franja con capacidad efectiva 100: la mediana de la carga fija la probabilidad (σ_log 0,1)."""
    return {"ruta": ruta, "fecha": fecha, "hora": 6, "carga_mediana": prob_mediana, "sigma_log": 0.1,
            "capacidad_efectiva": 100.0, "factor_carga": 1.0, "real": 120.0 if positiva else 80.0,
            "cumple_nivel_servicio": cumple, "alt001": alt001}


def dias(desde, n):
    return [str(desde + timedelta(days=i)) for i in range(n)]


def test_corte_de_validacion():
    assert V.corte_de(date(2025, 9, 15), date(2025, 12, 31)) == date(2025, 10, 31)
    assert V.corte_de(date(2025, 10, 14), date(2025, 10, 15)) == date(2025, 10, 14)   # fuera: la mitad


def test_dispara_es_la_regla_de_la_alerta():
    f = V.preparar([fila("2025-10-01", 100.0, True)])[0]
    assert f["prob"] == pytest.approx(0.5) and V.dispara(f, 0.3) and not V.dispara(f, 0.6)
    assert not V.dispara(dict(f, cumple_nivel_servicio=True), 0.1)      # cumple el nivel de servicio: nunca
    assert V.dispara(dict(f, prob=None), 0.9)                            # sin probabilidad: basta no cumplir


def test_la_tasa_base_elegible_excluye_las_franjas_de_alt001():
    filas = V.preparar([fila("2025-10-01", 100.0, True), fila("2025-10-01", 90.0, False),
                        fila("2025-10-02", 130.0, True, alt001=True), fila("2025-10-02", 140.0, True, alt001=True)])
    m = V._metricas(filas, 0.10)
    assert m["alertas"] == 2 and m["confirmadas"] == 1                  # las de ALT-001 no son de ALT-003 (§18)
    assert m["tasa_base"] == 0.75 and m["tasa_base_elegible"] == 0.5
    assert m["lift"] == pytest.approx(0.5 / 0.75, abs=1e-3) and m["lift_elegible"] == 1.0


def test_elige_el_mayor_lift_con_soporte_minimo_o_ninguno():
    val = {0.1: {"alertas": 40, "lift_elegible": 1.3}, 0.3: {"alertas": 25, "lift_elegible": 2.0},
           0.4: {"alertas": 5, "lift_elegible": 4.0}}
    assert V.elegir(val) == 0.3                       # 0,40 tiene más lift pero menos de 20 alertas
    assert V.elegir({0.1: {"alertas": 40, "lift_elegible": 0.9}, 0.3: {"alertas": 25, "lift_elegible": 0.95}}) is None
    assert V.elegir({0.2: {"alertas": 30, "lift_elegible": 1.5}, 0.3: {"alertas": 30, "lift_elegible": 1.5}}) == 0.2


def _escenario(informativa=False):
    """Validación en septiembre-octubre y evaluación en noviembre: las franjas de mayor probabilidad son positivas o,
    en el escenario sin señal, lo es solo la de menor probabilidad (la que ninguna variante alerta)."""
    filas = []
    for f in dias(date(2025, 9, 15), 47) + dias(date(2025, 11, 1), 30):
        for j, mediana in enumerate((80.0, 95.0, 105.0)):
            positiva = j == 0 if informativa else mediana > 100
            filas.append(fila(f, mediana, positiva, ruta=("CL 72", "SILENCIO", "CRA 54")[j]))
    return filas


def test_protocolo_adopta_si_supera_la_tasa_base_en_validacion():
    r = V.evaluar(_escenario(), date(2025, 10, 31))
    assert r["ventanas"] == {"validacion": ["2025-09-15", "2025-10-31"], "evaluacion": ["2025-11-01", "2025-11-30"]}
    assert r["decision"] == "adoptar" and r["elegida"] is not None
    e = r["variantes"][f"{r['elegida']:.2f}"]["evaluacion"]
    assert e["precision"] == 1.0 and e["lift_elegible"] > 1
    ic = r["intervalos_elegida"]["lift_elegible"]
    assert ic[0] <= e["lift_elegible"] <= ic[1]
    assert V.evaluar(_escenario(), date(2025, 10, 31))["intervalos_elegida"] == r["intervalos_elegida"]   # semilla
    assert "(elegida)" in "\n".join(V.informe(r, "prueba"))


def test_protocolo_sin_senal_baja_a_informativa():
    r = V.evaluar(_escenario(informativa=True), date(2025, 10, 31))
    assert r["elegida"] is None and r["decision"] == "informativa"
    assert "baja a informativa" in "\n".join(V.informe(r, "prueba"))


def test_diagnostico_separa_las_franjas_de_alt001():
    filas = [fila("2025-10-01", 130.0, True, alt001=True), fila("2025-10-01", 105.0, False),
             fila("2025-10-02", 60.0, False)]
    d = V.diagnostico(V.preparar(filas))
    assert d["con_alt001"] == {"franjas": 1, "positivas": 1.0}
    assert d["alt003_anterior"] == {"franjas": 1, "positivas": 0.0} and d["sin_alerta"]["franjas"] == 1
    assert d["senal_frecuencia_insuficiente"]["franjas"] == 2


# ---------------------------------------------------------------- cableado en scripts/backtest_alertas.py
def _ctx(hora, ruta="CL 72", h=30):
    ini = datetime(2025, 10, 16, hora, tzinfo=Z)
    return {"ruta": ruta, "ventana_inicio": ini, "horizonte_min": h, "buses_hora_actual": 4.0, "capacidad": 50,
            "factor_carga": 0.5, "demanda_prevista": 300.0, "p90": 360.0, "p10": 250.0, "ocupacion_objetivo_max": 0.85,
            "carga_critica_mediana": 150.0, "sigma_log": 0.14, "cumple_nivel_servicio": False}


def test_la_tasa_base_elegible_del_backtest_excluye_las_franjas_con_alt001():
    from collections import defaultdict

    acum = {k: defaultdict(int) for k in ("base_n", "base_si", "base_n_elegible", "base_si_elegible")}
    ctxs = [_ctx(6), _ctx(7)]
    observado = {("CL 72", date(2025, 10, 16), 6): 400.0, ("CL 72", date(2025, 10, 16), 7): 400.0}
    lista = [{"codigo": "ALT-001", "ruta": "CL 72", "ventana_inicio": ctxs[0]["ventana_inicio"]}]
    B._contar_base(lista, ctxs, observado, {"ocupacion_objetivo_max": 0.85, "ocupacion_critica": 0.9,
                                            "baja_utilizacion": 0.3}, acum)
    assert acum["base_n"]["ALT-003"] == 2 and acum["base_n_elegible"]["ALT-003"] == 1
    assert acum["base_n_elegible"]["ALT-001"] == 2                  # los demás códigos no se suprimen
    fila_b = B._fila_alt003(ctxs, lista, observado)
    assert fila_b["alt001"] is True and fila_b["capacidad_efectiva"] == pytest.approx(4 * 50 * 0.85)
    assert (fila_b["carga_mediana"], fila_b["sigma_log"], fila_b["real"]) == (150.0, 0.14, 400.0)
