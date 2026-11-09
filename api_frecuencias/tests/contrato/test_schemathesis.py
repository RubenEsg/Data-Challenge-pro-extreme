"""Contrato por propiedades con Schemathesis (spec v1.5 §14.1 «Contrato»): ninguna entrada da un error 5xx y toda
respuesta cumple lo que declara el OpenAPI.

Schemathesis genera peticiones a partir del OpenAPI de la API (valores válidos y casos límite de cada parámetro y
cuerpo) y las envía por ASGI, con la clave admin, sobre la base local de pruebas ya sembrada. Número de ejemplos
acotado (SCHEMATHESIS_EJEMPLOS, 10 por omisión) para que la suite siga siendo rápida. Chequeos, en TODAS las
operaciones (también las que se agreguen, como GET /api/v1/respuesta):
- not_a_server_error: ninguna respuesta 5xx (un 503 con el error uniforme es degradación prevista, RNF-010, y se
  acepta solo si la operación lo declara);
- status_code_conformance: el código está documentado en la operación;
- content_type_conformance: el tipo de contenido es uno de los declarados (JSON, text/csv, xlsx o text/plain);
- response_schema_conformance: el cuerpo JSON cumple el esquema documentado de ese código;
- response_headers_conformance: llegan las cabeceras declaradas como obligatorias (X-Correlation-Id en toda
  respuesta, WWW-Authenticate en el 401).
Los POST que crean jobs quedan en cola sin procesarse (no entrenan ni releen la serie).

Los defectos que esta prueba encontró el 09-11-2026 (enteros sin cota que llegaban a SQL y el byte NUL en filtros de
texto, ambos con 500) están corregidos: cota «le» en la paginación y los filtros, guarda NUL con 422 en
app/openapi_doc.py. Ya no hay lista de defectos conocidos: cualquier falla rompe la prueba con la petición exacta.
"""
from __future__ import annotations

import os

import pytest
import schemathesis
from hypothesis import HealthCheck, settings
from schemathesis.checks import (
    content_type_conformance,
    not_a_server_error,
    response_headers_conformance,
    response_schema_conformance,
    status_code_conformance,
)

pytestmark = [pytest.mark.contrato, pytest.mark.integracion]

EJEMPLOS = int(os.environ.get("SCHEMATHESIS_EJEMPLOS", "10"))
CHEQUEOS = [not_a_server_error, status_code_conformance, content_type_conformance, response_schema_conformance,
            response_headers_conformance]


@pytest.fixture(scope="module")
def esquema_api(app_contrato, sembrado):
    from app.servicios import ejecucion

    mp = pytest.MonkeyPatch()
    mp.setattr(ejecucion, "ejecutar", lambda *a, **k: None)
    try:
        yield schemathesis.openapi.from_asgi("/openapi.json", app_contrato)
    finally:
        mp.undo()


esquema = schemathesis.pytest.from_fixture("esquema_api")


def _error_uniforme_503(case, respuesta) -> bool:
    """503 con el error uniforme y declarado en la operación = dependencia no configurada o circuito abierto."""
    try:
        uniforme = respuesta.status_code == 503 and {"codigo", "mensaje"} <= set(respuesta.json()["error"])
    except (ValueError, KeyError, TypeError):
        return False
    return uniforme and "503" in (case.operation.definition.raw.get("responses") or {})


@esquema.parametrize()
@settings(max_examples=EJEMPLOS, deadline=None, derandomize=True, database=None,
          suppress_health_check=list(HealthCheck))
def test_ninguna_entrada_produce_error_5xx_y_todo_cumple_el_contrato(case, claves):
    respuesta = case.call(headers={"X-API-Key": claves["admin"]}, timeout=60)
    if _error_uniforme_503(case, respuesta):
        case.validate_response(respuesta, checks=CHEQUEOS[1:])
        return
    case.validate_response(respuesta, checks=CHEQUEOS)
