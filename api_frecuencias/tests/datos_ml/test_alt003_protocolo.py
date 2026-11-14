"""ALT-003 de pronóstico: la evidencia publicada del protocolo sin fuga (scripts/variantes_alt003.py) respalda el
mínimo de probabilidad vigente en el código y en la migración 0014, y la robustez por hora se reproduce.

- la elección se hizo en una ventana de validación estrictamente anterior a la de evaluación;
- el mínimo elegido es el de alertas.UMBRALES_POR_DEFECTO (y el que siembra la 0014);
- en evaluación supera la tasa base de las franjas donde ALT-003 puede emitirse con un IC del 95 % por encima de 1, y
  supera a la regla anterior (solo el nivel de servicio);
- con el ciclo desde cada hora de servicio, la variante adoptada también supera la tasa base.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

pytestmark = pytest.mark.datos_ml

RAIZ = Path(__file__).resolve().parents[2]
EVIDENCIA = RAIZ / "docs" / "evidencias" / "alertas" / "backtest_alertas_pronostico.json"
ROBUSTEZ = RAIZ / "docs" / "evidencias" / "alertas" / "alt003_variantes_todas_las_horas.json"


@pytest.mark.skipif(not EVIDENCIA.exists(), reason="sin la evidencia del backtest de pronóstico")
def test_la_evidencia_publicada_respalda_el_minimo_vigente_de_alt003():
    from app.servicios.alertas import UMBRALES_POR_DEFECTO

    r = json.loads(EVIDENCIA.read_text(encoding="utf-8"))
    a = r["alt003"]
    assert a["ventanas"]["validacion"][1] < a["ventanas"]["evaluacion"][0]           # sin fuga: validación antes
    assert a["decision"] == "adoptar" and a["elegida"] == UMBRALES_POR_DEFECTO["alt003_probabilidad_minima"]
    assert r["alt003_probabilidad_minima"] == a["elegida"] == a["adoptada"]
    elegida = a["variantes"][f"{a['elegida']:.2f}"]
    assert elegida["validacion"]["alertas"] >= a["n_min_validacion"] and elegida["validacion"]["lift_elegible"] > 1
    assert a["intervalos_elegida"]["lift_elegible"][0] > 1                        # evaluación: IC por encima de 1
    anterior = a["variantes"][f"{a['anterior']:.2f}"]["evaluacion"]
    assert elegida["evaluacion"]["precision"] > anterior["precision"]
    assert elegida["evaluacion"]["lift"] > anterior["lift"]
    # la tabla del ciclo ya usa el mínimo adoptado: es la misma variante que mide el protocolo en todo el periodo
    ahora = r["variantes"]["franja"]["por_codigo"]["ALT-003"]
    assert ahora["alertas"] == elegida["validacion"]["alertas"] + elegida["evaluacion"]["alertas"]
    assert ahora["lift_elegible"] > 1 and r["antes_alt003"]["lift"] < 1


@pytest.mark.skipif(not ROBUSTEZ.exists(), reason="sin la evidencia de robustez por hora")
def test_en_todas_las_horas_la_variante_adoptada_supera_la_tasa_base():
    from app.servicios.alertas import UMBRALES_POR_DEFECTO

    a = json.loads(ROBUSTEZ.read_text(encoding="utf-8"))["alt003"]
    p = UMBRALES_POR_DEFECTO["alt003_probabilidad_minima"]
    assert a["adoptada"] == p
    adoptada = a["variantes"][f"{p:.2f}"]
    for ventana in ("validacion", "evaluacion"):
        assert adoptada[ventana]["lift"] > 1 and adoptada[ventana]["lift_elegible"] > 1, ventana
    assert a["intervalos_adoptada"]["lift"][0] > 1


def test_la_robustez_por_hora_se_reproduce_en_dos_dias(datos_copia, tmp_path):
    from scripts import backtest_alertas

    r = backtest_alertas.alt003_todas_las_horas(date(2025, 10, 14), date(2025, 10, 15), tmp_path, horas=(6, 7))
    a = r["alt003"]
    assert a["diagnostico"]["franjas"] <= 2 * 2 * 3
    assert a["ventanas"]["validacion"] == ["2025-10-14", "2025-10-14"]           # la mitad del periodo
    assert set(a["candidatos"]) >= {0.1, a["adoptada"]}
    assert (tmp_path / "alt003_variantes_todas_las_horas.md").exists()
