"""§14.2 «la ejecución programada procesa lo nuevo o modificado desde la última marca y actualiza predicciones,
recomendaciones y alertas», de punta a punta y sin POST manual.

Corre docs/evidencias/cola/planificador_programado.py en un proceso aparte: el planificador interno (APScheduler,
cron cada minuto) encola las franjas y la cola las procesa; a mitad de la prueba llega un día nuevo y se modifican
tres filas. Tarda unos cuatro minutos (espera los cambios de minuto), así que solo corre con PRUEBA_PLANIFICADOR=1.
Usa una base local desechable (<TEST_DATABASE_NAME>_plan) y una copia temporal de datos/; la evidencia queda en un
directorio temporal salvo con GENERAR_EVIDENCIAS=1 (tests/evidencia.py).
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
