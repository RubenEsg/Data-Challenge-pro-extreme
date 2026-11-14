"""Modo integrado de scripts/verificar_despliegue.py: el puerto de --puerto-integrado es el que publica la API.

docker-compose.integracion.yml publica la API en ${API_INTEGRADA_PUERTO_HOST:-8302}. La verificación consulta
http://127.0.0.1:<--puerto-integrado>; si no le pasa esa variable a compose, con un puerto distinto del de omisión la
API queda en el 8302 y /health nunca responde en el puerto pedido.
"""
from __future__ import annotations

from pathlib import Path

from scripts import verificar_despliegue

API = Path(__file__).resolve().parents[2]
VARIABLE = "API_INTEGRADA_PUERTO_HOST"


def test_el_puerto_integrado_llega_a_compose():
    assert verificar_despliegue.entorno_integrado(8360) == {VARIABLE: "8360"}


def test_compose_publica_la_api_integrada_en_esa_variable():
    texto = (API / "docker-compose.integracion.yml").read_text(encoding="utf-8")
    assert f'- "${{{VARIABLE}:-8302}}:8000"' in texto
