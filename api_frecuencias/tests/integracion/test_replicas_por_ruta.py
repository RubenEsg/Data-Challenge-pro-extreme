"""RNF-005 · dos réplicas reales (procesos uvicorn) con la ejecución partida por ruta, de punta a punta.

Corre scripts/prueba_replicas_por_ruta.py: dos réplicas sobre una base local NUEVA (derivada de la base de pruebas,
nunca la compartida) procesan N días partidos por ruta y el script comprueba con execution_attempt que hubo rutas
distintas a la vez en réplicas distintas, que la misma ruta nunca corrió en paralelo, que no hubo duplicados y que la
marca de agua de cada ruta quedó contigua; después corre los mismos días SIN partir en otra base nueva y compara que
las predicciones, el plan del día, las alertas, la foto de la respuesta, el monitoreo y la foto de variables (de la
ruta y por segmento y sentido: cada fila una vez, en el trabajo de su ruta y en la partición de su ventana) sean
iguales. Tarda unos dos o tres minutos, así que solo corre con PRUEBA_REPLICAS=1 (la evidencia firmada está en
docs/evidencias/cola/replicas_por_ruta.txt). Puertos: PRUEBA_REPLICAS_PUERTOS="a,b" o dos libres.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy.engine import make_url

from tests.evidencia import guardar_evidencia

RAIZ = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.skipif(os.environ.get("PRUEBA_REPLICAS") != "1",
                                reason="dos réplicas reales partidas por ruta: active con PRUEBA_REPLICAS=1 (~3 min)")


def _puertos() -> list[int]:
    elegidos = [p for p in os.environ.get("PRUEBA_REPLICAS_PUERTOS", "").split(",") if p.strip()]
    if len(elegidos) == 2:
        return [int(p) for p in elegidos]
    puertos = []
    for _ in range(2):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            puertos.append(s.getsockname()[1])
    return puertos


def test_dos_replicas_reales_rutas_distintas_a_la_vez_y_mismas_salidas_que_sin_partir(migrada, tmp_path):
    base = f"{make_url(migrada).database}_replicas_ruta"
    puerto_a, puerto_b = _puertos()
    salida, informe = tmp_path / "replicas_por_ruta.json", tmp_path / "replicas_por_ruta.txt"
    r = subprocess.run(  # noqa: S603
        [sys.executable, str(RAIZ / "scripts" / "prueba_replicas_por_ruta.py"), "--base-datos", base, "--n", "4",
         "--puerto-a", str(puerto_a), "--puerto-b", str(puerto_b), "--comparar-sin-partir", "--json", str(salida),
         "--salida", str(informe), "--logs", str(tmp_path / "logs")],
        cwd=RAIZ, env=os.environ | {"PYTHONIOENCODING": "utf-8"}, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=1500)
    assert r.returncode == 0, r.stdout[-4000:] + r.stderr[-2000:]
    resultado = json.loads(salida.read_text(encoding="utf-8"))
    # con GENERAR_EVIDENCIAS=1 regenera la evidencia firmada de docs/evidencias/cola/; si no, queda en un temporal
    guardar_evidencia("cola/replicas_por_ruta.json", salida.read_text(encoding="utf-8"))
    guardar_evidencia("cola/replicas_por_ruta.txt", informe.read_text(encoding="utf-8"))
    assert resultado["ok"] and not resultado["fallas"]
    assert resultado["pares_cruzados"] > 0 and resultado["pares_misma_ruta"] == 0
    assert set(resultado["por_replica"]) == {"replica-a", "replica-b"} and resultado["concurrencia_maxima"] == 2
    foto = resultado["foto_de_variables"]          # §7.3 paso 4 con RNF-005: la foto por segmento, una vez por fila
    assert foto["filas"] > 0 and foto["en_la_madre"] == foto["repetidas"] == foto["de_otra_ruta"] == 0
    assert foto["fuera_de_su_particion"] == 0
