"""RNF-001 · prueba de caída de punta a punta (procesos uvicorn reales y SIGKILL), sobre una base LOCAL nueva.

Corre scripts/prueba_caida.py en puertos libres (o en los de PRUEBA_CAIDA_PUERTOS="a,b"): SIGKILL durante la
lectura y durante la predicción (la réplica reinicia y retoma) y una segunda réplica que retoma al vencer la reserva.
En cada caso la foto de variables (de la ruta y por segmento y sentido) queda igual a la de la referencia y sin filas
repetidas. Tarda unos dos minutos, así que solo corre con PRUEBA_CAIDA=1 (la evidencia firmada está en
docs/evidencias/cola/caida_rnf001.txt).

La base es «<base de pruebas>_caida», nueva en cada corrida y borrada al terminar, como las de test_replicas_por_ruta
y test_planificador_programado: prueba_caida.py corre ciclos reales con días nuevos tras la marca de agua y deja su
histórico, sus predicciones y sus alertas. En la base de la sesión, sus días dependían de lo que corrió antes y su
ejecución de referencia leía el histórico entero hasta su primer día (con test_api_integracion antes, desde el
2023-01-01 hasta el 2025-03-04), que quedaba en demanda_observada para las pruebas siguientes
(test_errores_lote espera que el 2024-06-12 no esté en el histórico).
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from tests.evidencia import guardar_evidencia

RAIZ = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.skipif(os.environ.get("PRUEBA_CAIDA") != "1",
                                reason="prueba de caída con procesos reales: active con PRUEBA_CAIDA=1 (~2 min)")


def _puerto_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _puertos() -> list[int]:
    """PRUEBA_CAIDA_PUERTOS="a,b" (en un equipo compartido, los puertos asignados a quien corre la prueba) o dos
    libres."""
    elegidos = [p for p in os.environ.get("PRUEBA_CAIDA_PUERTOS", "").split(",") if p.strip()]
    return [int(p) for p in elegidos] if len(elegidos) == 2 else [_puerto_libre(), _puerto_libre()]


def _borrar_base(migrada, nombre: str) -> None:
    """Borra la base `nombre` del mismo servidor local, si existe (prueba_caida.py la crea y la migra)."""
    admin = create_engine(make_url(migrada).set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as c:
            c.execute(text(f'DROP DATABASE IF EXISTS "{nombre}" WITH (FORCE)'))
    finally:
        admin.dispose()


def _correr_prueba_caida(base: str, tmp_path: Path) -> subprocess.CompletedProcess:
    puerto_a, puerto_b = _puertos()
    return subprocess.run(  # noqa: S603
        [sys.executable, str(RAIZ / "scripts" / "prueba_caida.py"), "--base-datos", base,
         "--puerto-a", str(puerto_a), "--puerto-b", str(puerto_b), "--json", str(tmp_path / "caida.json"),
         "--salida", str(tmp_path / "caida.txt"), "--logs", str(tmp_path / "logs")],
        cwd=RAIZ, env=os.environ | {"PYTHONIOENCODING": "utf-8"}, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=900)


def test_sigkill_en_lectura_y_prediccion_y_reserva_vencida(migrada, tmp_path):
    base = f"{make_url(migrada).database}_caida"       # nueva: nada de lo que deja llega a la base de la sesión
    salida = tmp_path / "caida.json"
    informe = tmp_path / "caida.txt"
    _borrar_base(migrada, base)
    try:
        r = _correr_prueba_caida(base, tmp_path)
    finally:
        _borrar_base(migrada, base)
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
    assert resultado["referencia"]["foto_ruta"] > 0       # §11.2: la foto que comparan los casos con caída
