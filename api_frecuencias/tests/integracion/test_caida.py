"""RNF-001 · prueba de caída de punta a punta (procesos uvicorn reales y SIGKILL), sobre la base LOCAL de pruebas.

Corre scripts/prueba_caida.py en puertos libres: SIGKILL durante la lectura y durante la predicción (la réplica
reinicia y retoma) y una segunda réplica que retoma al vencer la reserva. Tarda unos dos minutos, así que solo
corre con PRUEBA_CAIDA=1 (la evidencia firmada está en docs/evidencias/cola/caida_rnf001.txt).
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

pytestmark = pytest.mark.skipif(os.environ.get("PRUEBA_CAIDA") != "1",
                                reason="prueba de caída con procesos reales: active con PRUEBA_CAIDA=1 (~2 min)")


def _puerto_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_sigkill_en_lectura_y_prediccion_y_reserva_vencida(migrada, tmp_path):
    base = make_url(migrada).database
    salida = tmp_path / "caida.json"
    informe = tmp_path / "caida.txt"
    r = subprocess.run(  # noqa: S603
        [sys.executable, str(RAIZ / "scripts" / "prueba_caida.py"), "--base-datos", base,
         "--puerto-a", str(_puerto_libre()), "--puerto-b", str(_puerto_libre()), "--json", str(salida),
         "--salida", str(informe), "--logs", str(tmp_path / "logs")],
        cwd=RAIZ, env=os.environ | {"PYTHONIOENCODING": "utf-8"}, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=900)
    assert r.returncode == 0, r.stdout[-4000:] + r.stderr[-2000:]
    resultado = json.loads(salida.read_text(encoding="utf-8"))
    # con GENERAR_EVIDENCIAS=1 regenera la evidencia firmada de docs/evidencias/cola/; si no, queda en un temporal
    guardar_evidencia("cola/caida_rnf001.json", salida.read_text(encoding="utf-8"))
    if informe.exists():
        guardar_evidencia("cola/caida_rnf001.txt", informe.read_text(encoding="utf-8"))
    assert resultado["ok"] and not resultado["fallas"]
    escenarios = {e["escenario"]: e for e in resultado["escenarios"]}
    assert set(escenarios) == {"sigkill_lectura_incremental", "sigkill_prediccion", "reserva_vencida_otra_replica"}
    for e in escenarios.values():
        assert e["intentos"] == 2 and [t[2] for t in e["traza"]] == ["abandonado", "ok"]
