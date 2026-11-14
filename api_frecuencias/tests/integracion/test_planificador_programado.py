"""§14.2 «la ejecución programada procesa lo nuevo o modificado desde la última marca y actualiza predicciones,
recomendaciones y alertas», de punta a punta y sin POST manual, y §10.1 «ocupación actual» en la operación programada
(el ciclo intradía).

Corre docs/evidencias/cola/planificador_programado.py en un proceso aparte: el planificador interno (APScheduler,
cron cada minuto) encola las franjas y la cola las procesa; a mitad de la prueba llega un día nuevo y se modifican
tres filas. Después corre scripts/evidencia_planificador_intradia.py: el trabajo intradía encola sus franjas con
instante = la franja en un día comprimido (cada minuto real, la hora siguiente) y la restricción reactiva actúa en el
plan del día en curso. Cada una tarda unos cuatro o cinco minutos (espera los cambios de minuto), así que solo corren
con PRUEBA_PLANIFICADOR=1. Usan bases locales desechables (<TEST_DATABASE_NAME>_plan y _intradia) y una copia temporal
de datos/; la evidencia queda en un directorio temporal salvo con GENERAR_EVIDENCIAS=1 (tests/evidencia.py).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.evidencia import guardar_evidencia

RAIZ = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.skipif(os.environ.get("PRUEBA_PLANIFICADOR") != "1",
                                reason="ejecución programada real (cron cada minuto): active con PRUEBA_PLANIFICADOR=1 "
                                       "(~4 min)")


def test_franja_programada_procesa_solo_lo_nuevo_y_actualiza_resultados(migrada, tmp_path):
    base = os.environ.get("TEST_DATABASE_NAME", "ai_frecuencias_pruebas") + "_plan"
    salida, resumen = tmp_path / "planificador_programado.txt", tmp_path / "planificador_programado.json"
    r = subprocess.run(  # noqa: S603
        [sys.executable, str(RAIZ / "docs" / "evidencias" / "cola" / "planificador_programado.py"),
         "--raiz", str(RAIZ), "--base-datos", base, "--salida", str(salida), "--json", str(resumen)],
        cwd=RAIZ, env=os.environ | {"PYTHONIOENCODING": "utf-8", "TEST_DATABASE_URL": str(migrada)},
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=1500)
    assert r.returncode == 0, r.stdout[-4000:] + r.stderr[-2000:]
    datos = json.loads(resumen.read_text(encoding="utf-8"))
    guardar_evidencia("cola/planificador_programado.txt", salida.read_text(encoding="utf-8"))
    guardar_evidencia("cola/planificador_programado.json", resumen.read_text(encoding="utf-8"))
    assert all(datos["comprobaciones"].values()), datos["comprobaciones"]
    assert datos["manuales"] == 0
    leidas = [f["filas_leidas"] for f in datos["franjas"]]
    assert leidas[0] > 0 and any(0 < x <= datos["llegada"]["filas_nuevas"] + 3 for x in leidas[1:])


def test_el_ciclo_intradia_programado_aplica_la_ocupacion_actual(migrada, tmp_path):
    """§10.1 10.1-d en la operación PROGRAMADA: scripts/evidencia_planificador_intradia.py arranca la API con el
    planificador real y la cola real; las franjas intradía (8:05, 9:05, 10:05 y 11:05 de un día comprimido, calculadas
    con el PLAN_INTRADIA_CRON por omisión) se encolan solas, una vez cada una aunque otra réplica dispare la misma, con
    instante = la franja; cada ciclo lee solo la hora que llegó y la restricción reactiva por ocupación actual actúa en
    el plan del día en curso y en las recomendaciones de 30 y 60 min de esa hora, y deja de actuar cuando la ocupación
    baja del umbral. Unos cinco minutos (espera cuatro cambios de minuto)."""
    base = os.environ.get("TEST_DATABASE_NAME", "ai_frecuencias_pruebas") + "_intradia"
    salida, resumen = tmp_path / "planificador_intradia.txt", tmp_path / "planificador_intradia.json"
    r = subprocess.run(  # noqa: S603
        [sys.executable, str(RAIZ / "scripts" / "evidencia_planificador_intradia.py"),
         "--base-datos", base, "--salida", str(salida), "--json", str(resumen)],
        cwd=RAIZ, env=os.environ | {"PYTHONIOENCODING": "utf-8", "TEST_DATABASE_URL": str(migrada)},
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=1500)
    assert r.returncode == 0, r.stdout[-4000:] + r.stderr[-2000:]
    datos = json.loads(resumen.read_text(encoding="utf-8"))
    guardar_evidencia("ocupacion/planificador_intradia.txt", salida.read_text(encoding="utf-8"))
    guardar_evidencia("ocupacion/planificador_intradia.json", resumen.read_text(encoding="utf-8"))
    assert all(datos["comprobaciones"].values()), datos["comprobaciones"]
    assert len(datos["franjas"]) == 4 and datos["refrescos_pedidos"] == 0
    assert [f["restriccion_plan"]["aplica"] for f in datos["franjas"]] == [True, True, False, None]
    assert datos["latencia_consulta_paginada"]["con_ciclo_en_curso"]["p95_s"] < 2
