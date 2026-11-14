"""ALT-003 de pronóstico (frecuencia insuficiente, §5.2) con probabilidad (§5.3) y mínimo gobernado
(alt003_probabilidad_minima, migración 0014): la frecuencia actual no cumple el nivel de servicio Y la probabilidad de
que la carga crítica supere la capacidad efectiva llega al mínimo elegido sin fuga (scripts/variantes_alt003.py)."""
import importlib.util
import math
from datetime import date
from pathlib import Path

import pytest

from app.servicios import alertas as A

RAIZ = Path(__file__).resolve().parents[2]
Z90 = A.Z_P90


def ctx(buses, demanda=300.0, p90=350.0, p10=250.0, **extra):
    """Contexto plano de una franja: 50 puestos por bus, factor de carga 1 (sin optimizador)."""
    return {"ruta": "X", "buses_hora_actual": buses, "capacidad": 50, "demanda_prevista": demanda, "p90": p90,
            "p10": p10, **extra}


def alt003(c, umbrales=None):
    al = [a for a in A.evaluar_alertas(c, umbrales) if a["codigo"] == "ALT-003"]
    return al[0] if al else None


@pytest.mark.parametrize("mediana,sigma,capacidad,esperada", [
    (300.0, 0.12, 300.0, 0.5),            # en la mediana: 50 %
    (300.0, 0.0, 299.0, 1.0),             # sin banda: determinista
    (300.0, 0.0, 301.0, 0.0),
    (0.0, 0.2, 100.0, 0.0),               # sin demanda no hay riesgo
    (None, 0.1, 100.0, None), (300.0, 0.1, None, None), (300.0, 0.1, 0.0, None),
])
def test_probabilidad_sobre_capacidad(mediana, sigma, capacidad, esperada):
    assert A.probabilidad_sobre_capacidad(mediana, sigma, capacidad) == esperada


def test_probabilidad_con_la_lognormal_de_la_banda():
    s = math.log(350 / 300) / Z90
    p = A.probabilidad_sobre_capacidad(300.0, s, 297.5)
    assert p == pytest.approx(0.5 * math.erfc(math.log(297.5 / 300) / (s * math.sqrt(2))), abs=1e-4)
    assert A.probabilidad_sobre_capacidad(300.0, s, 350.0) == pytest.approx(0.10, abs=1e-4)   # P90 = el nivel 0,90


def test_alt003_no_se_emite_si_el_riesgo_no_llega_al_minimo():
    # 8 buses/h: 340 de capacidad efectiva < P90 350 -> no cumple el nivel de servicio, pero P(carga > 340) = 14,9 %
    c = ctx(8)
    assert A.UMBRALES_POR_DEFECTO["alt003_probabilidad_minima"] == 0.30
    assert alt003(c) is None
    a = alt003(c, {"alt003_probabilidad_minima": 0.10})       # la regla anterior: basta el nivel de servicio
    assert a is not None and a["probabilidad"] == pytest.approx(0.149, abs=1e-3)
    assert a["variables"]["alt003_probabilidad_minima"] == 0.10


def test_alt003_lleva_la_probabilidad_y_el_minimo_en_la_alerta():
    a = alt003(ctx(7))                                       # 297,5 < 350 y P(carga > 297,5) = 52,8 %
    assert a["severidad"] == "preventiva"
    assert a["probabilidad"] == pytest.approx(0.528, abs=1e-3)
    v = a["variables"]
    assert v["probabilidad_sobre_capacidad_efectiva"] == a["probabilidad"] and v["alt003_probabilidad_minima"] == 0.30
    assert "Probabilidad estimada de que la carga crítica supere la capacidad efectiva: 52,8 %" in a["explicacion"]
    assert "se alerta desde 30,0 %" in a["explicacion"]
    assert "probabilidad = P(carga crítica > capacidad efectiva" in a["metodo_puntaje"]


def test_alt003_sigue_exigiendo_que_no_se_cumpla_el_nivel_de_servicio():
    """Aunque la probabilidad sea alta, si el optimizador dice que la frecuencia actual cumple, no hay ALT-003."""
    c = ctx(7, cumple_nivel_servicio=True, carga_critica_diseno=290.0)
    assert alt003(c) is None


def test_alt003_usa_la_distribucion_del_optimizador_si_viene():
    # el optimizador entrega la mediana y el σ_log de la carga crítica (recommendation.detalle.demanda)
    c = ctx(7, carga_critica_mediana=200.0, sigma_log=0.05)
    assert alt003(c) is None                                 # mediana 200 << 297,5: P ≈ 0 aunque el P90 no cumpla
    c = ctx(7, carga_critica_mediana=297.5, sigma_log=0.05)
    assert alt003(c)["probabilidad"] == pytest.approx(0.5, abs=1e-4)


def test_alt003_la_probabilidad_coincide_con_el_optimizador_real():
    """La lognormal del contexto plano (P50 y P90 por hora) y la que guarda el optimizador real dan la misma
    probabilidad: la alerta y la recomendación miden el mismo riesgo."""
    from app.servicios import datos, optimizacion

    info = {r["ruta"]: r for r in datos.catalogo_rutas()}["CRA 54"]
    umbrales = {k: v for k, v in A.UMBRALES_POR_DEFECTO.items() if k != "version"}
    rec, ent = optimizacion.recomendacion_franja(dict(info, ruta="CRA 54"), umbrales, None, hora=7,
                                                 fecha=date(2025, 10, 16), demanda_hora=1_900.0, demanda_p90=2_100.0,
                                                 demanda_p10=1_700.0)
    franja = {"fecha": date(2025, 10, 16), "hora": 7, "demanda_hora": 1_900.0, "p90_hora": 2_100.0,
              "p10_hora": 1_700.0}
    c = A.contexto_pronostico("CRA 54", 60, franja, {"pasajeros": 1_900.0, "p10": 1_700.0, "p90": 2_100.0}, ent, rec)
    assert c["sigma_log"] == rec["demanda"]["sigma_log"] and c["carga_critica_mediana"] is not None
    plano = {k: v for k, v in c.items() if k not in ("sigma_log", "carga_critica_mediana")}
    cap_ef = A._capacidad_actual(c) * float(c["ocupacion_objetivo_max"])
    assert A._riesgo_003(c, umbrales, cap_ef)[0] == pytest.approx(A._riesgo_003(plano, umbrales, cap_ef)[0], abs=2e-3)


def test_la_migracion_0014_siembra_el_valor_del_codigo():
    spec = importlib.util.spec_from_file_location("m0014", RAIZ / "alembic" / "versions"
                                                  / "0014_alt003_probabilidad_minima.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    # al integrar, la 0014 se encadena detrás de las migraciones de otros paquetes: basta que baje a una que exista
    versiones = RAIZ / "alembic" / "versions"
    previas = {p.name.split("_", 1)[0] for p in versiones.glob("[0-9][0-9][0-9][0-9]_*.py")} - {m.revision}
    assert m.revision == "0014" and m.down_revision in previas and m.CREADO_POR == "migracion_0014"
    from app.servicios.ejecucion import SQL_CANDADO_UMBRALES

    assert m.CANDADO_UMBRALES == SQL_CANDADO_UMBRALES.text      # el mismo candado que PUT /thresholds
    assert {n: v for n, v, _d in m.UMBRALES_0014} == {"alt003_probabilidad_minima":
                                                       A.UMBRALES_POR_DEFECTO["alt003_probabilidad_minima"]}
    assert all(d for _n, _v, d in m.UMBRALES_0014)
