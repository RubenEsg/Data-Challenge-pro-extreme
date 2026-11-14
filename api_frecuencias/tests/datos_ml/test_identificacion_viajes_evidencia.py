"""§5.3 «Empresa, ruta, sentido, viaje, conductor y vehículo, cuando aplique»: la evidencia publicada con la réplica
(docs/evidencias/alertas/identificacion_viajes.json, scripts/evidencia_identificacion_alertas.py) respalda la tabla
alertas.IDENTIFICACION_5_3.

- la tabla de la evidencia es la del código, con sus motivos: viaje, vehículo y conductor solo aplican a ALT-006 y
  ALT-009, y la variante «segmento_critico» de ALT-002 observada (alertas.VARIANTES_5_3) trae además el sentido;
- casi todas las ALT-006 con datos reales traen su viaje y el seudónimo de su conductor, y los viajes válidos de su
  ventana son las salidas de la serie horaria;
- el sentido no aplica a las reglas por ruta: cada viaje toca más de la mitad de los segmentos de su ruta (los dos
  sentidos del supuesto S9); en el segmento crítico medido sí hay un sentido aproximado y un viaje más cargado;
- §18: la evidencia no copia ningún seudónimo ni identificador de conductor.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.datos_ml

RAIZ = Path(__file__).resolve().parents[2]
EVIDENCIA = RAIZ / "docs" / "evidencias" / "alertas" / "identificacion_viajes.json"


@pytest.mark.skipif(not EVIDENCIA.exists(), reason="sin la evidencia de identificación de viajes")
def test_la_evidencia_de_identificacion_respalda_la_tabla_de_5_3():
    from app.servicios import alertas

    texto = EVIDENCIA.read_text(encoding="utf-8")
    r = json.loads(texto)
    assert [x["codigo"] for x in r["reglas"]] == list(alertas.IDENTIFICACION_5_3)
    assert [(x["aplica"], x["motivo"]) for x in r["reglas"]] == [(list(a), m) for a, m in
                                                                 alertas.IDENTIFICACION_5_3.values()]
    assert all(x["sentido"] == alertas.SENTIDO_NO_APLICA for x in r["reglas"])
    assert {x["codigo"] for x in r["reglas"] if x["aplica"]} == {"ALT-006", "ALT-009"}
    # la variante de ALT-002 medida en el segmento crítico: la misma de VARIANTES_5_3, con el sentido
    assert [(x["codigo"], x["variante"], x["aplica"], x["motivo"], x["sentido"]) for x in r["variantes"]] == [
        (c, v, list(a), m, s) for (c, v), (a, m, s) in alertas.VARIANTES_5_3.items()]
    assert ("ALT-002", "segmento_critico") in alertas.VARIANTES_5_3
    seg = r["alt002_segmento"]
    assert seg["horas_con_segmento_critico"] > 0 and seg["con_sentido"] >= 0.9 * seg["horas_con_segmento_critico"]
    assert seg["con_viaje_mas_cargado"] == seg["horas_con_segmento_critico"]
    assert seg["alt002_con_sentido"] == seg["alt002_con_viaje"] == seg["alt002_segmento_critico"]
    assert "no aplica a ninguna regla" not in EVIDENCIA.with_suffix(".md").read_text(encoding="utf-8")
    a6, a9 = r["alt006"], r["alt009"]
    assert a6["alertas"] > 0 and a6["con_viaje"] >= 0.9 * a6["alertas"]
    assert a6["con_conductor"] == a6["con_viaje"] and a6["salidas_iguales"] == a6["alertas"]
    assert a9["alertas"] > 0 and a9["con_viaje"] == a9["alertas"]
    circuito = r["circuito"]["por_ruta"]
    assert {x["ruta"] for x in circuito} == {"SILENCIO", "CRA 54", "CL 72"}
    assert all(x["mas_de_medio_circuito"] > 0.9 and x["mediana"] > 0.5 for x in circuito)
    assert not re.search(r"cnd_[0-9a-f]{24}", texto) and "idconductor" not in texto
