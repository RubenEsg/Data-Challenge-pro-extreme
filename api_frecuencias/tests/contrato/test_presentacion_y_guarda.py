"""Unidad (sin base de datos): presentación §8.1 de los instantes anidados y guarda contra el byte NUL (§12.1).

- app.esquemas.bogota_profundo y el serializador de Salida: todo instante de una respuesta, también dentro de un
  JSONB (comentarios[].en, variables, métricas, detalle), sale en America/Bogota (-05:00);
- app.openapi_doc.GuardaNul: 0x00 en ruta, consulta, cabecera o cuerpo JSON -> 422 uniforme, y el cuerpo de una
  petición normal llega intacto a la aplicación.
"""
from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

pytestmark = pytest.mark.contrato


def test_bogota_profundo_convierte_solo_instantes():
    from app.esquemas import bogota_profundo

    entrada = {
        "comentarios": [{"en": "2025-01-02T11:00:00+00:00", "comentario": "Faltan las horas 2025-01-02 06:00"}],
        "variables": {"horas_faltantes": ["2025-10-15 14:00", "2025-10-15T15:00:00-05:00"], "fecha": "2025-10-15",
                      "ultima_llegada": "2025-10-15T19:30:00Z", "hora": "04:40:00", "n": 3},
        "instante": datetime(2025, 1, 2, 11, 0, tzinfo=UTC), "dia": date(2025, 1, 2), "texto": "SILENCIO",
    }
    salida = bogota_profundo(entrada)
    assert salida["comentarios"][0] == {"en": "2025-01-02T06:00:00-05:00",
                                        "comentario": "Faltan las horas 2025-01-02 06:00"}
    assert salida["variables"]["horas_faltantes"] == ["2025-10-15T14:00:00-05:00", "2025-10-15T15:00:00-05:00"]
    assert salida["variables"]["ultima_llegada"] == "2025-10-15T14:30:00-05:00"
    assert (salida["variables"]["fecha"], salida["variables"]["hora"], salida["variables"]["n"]) == \
        ("2025-10-15", "04:40:00", 3)
    assert salida["instante"].utcoffset().total_seconds() == -5 * 3600
    assert salida["dia"] == date(2025, 1, 2) and salida["texto"] == "SILENCIO"


def test_salida_presenta_columnas_y_jsonb_en_bogota():
    from app.esquemas import HistorialSalida

    h = HistorialSalida(id=1, alert_id="00000000-0000-0000-0000-000000000001", accion="comentar",
                        estado_nuevo="reconocida", usuario="u",
                        detalle={"antes": {"ventana_fin": "2025-03-03T13:00:00+00:00"}},
                        creado_en=datetime(2025, 3, 3, 12, 0, tzinfo=UTC))
    json = h.model_dump(mode="json")
    assert json["creado_en"] == "2025-03-03T07:00:00-05:00"
    assert json["detalle"]["antes"]["ventana_fin"] == "2025-03-03T08:00:00-05:00"
    # el esquema OpenAPI no cambia con el serializador
    assert HistorialSalida.model_json_schema(mode="serialization")["properties"]["creado_en"]["format"] == "date-time"


@pytest.mark.parametrize(("scope", "campo"), [
    ({"path": "/api/v1/alerts", "query_string": b"ruta=%00"}, "query.ruta"),
    ({"path": "/api/v1/alerts", "query_string": b"codigo=a&ruta=SIL%00ENCIO"}, "query.ruta"),
    ({"path": "/api/v1/models/\x00", "raw_path": b"/api/v1/models/%00", "query_string": b""}, "path"),
    ({"path": "/health", "query_string": b"", "headers": [(b"x-otra", b"a\x00b")]}, "header.x-otra"),
    ({"path": "/api/v1/alerts", "query_string": b"ruta=SILENCIO&radio_m=100", "headers": [(b"x", b"y")]}, None),
])
def test_campo_con_nul(scope, campo):
    from app.openapi_doc import _campo_con_nul

    assert _campo_con_nul(scope) == campo


def test_guarda_nul_rechaza_cuerpo_y_deja_pasar_el_resto():
    from app.openapi_doc import GuardaNul

    app = FastAPI()
    app.add_middleware(GuardaNul)

    @app.post("/eco")
    async def eco(request: Request):
        return await request.json()

    c = TestClient(app)
    assert c.post("/eco", json={"a": "ñandú", "b": [1, 2]}).json() == {"a": "ñandú", "b": [1, 2]}
    r = c.post("/eco", json={"a": "x\u0000y"}, headers={"X-Correlation-Id": "cid-nul"})
    assert r.status_code == 422 and r.headers["X-Correlation-Id"] == "cid-nul"
    assert r.json()["error"]["codigo"] == "validacion" and r.json()["error"]["detalle"][0]["campo"] == "body"
    r = c.get("/eco", params={"q": "\x00"})
    assert r.status_code == 422 and r.json()["error"]["correlation_id"]
