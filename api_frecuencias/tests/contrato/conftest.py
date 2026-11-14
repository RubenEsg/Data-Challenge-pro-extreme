"""Pruebas de contrato (spec v1.5 §14.1 «Contrato | OpenAPI, pytest y HTTPX | Esquemas, códigos y compatibilidad»).

Corren contra la misma base local de pruebas que la suite de integración (TEST_DATABASE_NAME en el servidor de la
5433, o TEST_DATABASE_URL en CI) y con el MISMO juego de claves de prueba: se importan de tests/integracion/conftest.py
para que haya un solo API_KEYS por proceso. La autenticación queda ENCENDIDA en este paquete (AUTH_HABILITADA=true).

Higiene: la API lee y escribe en una COPIA temporal de datos/ (DATA_DIR y MODELOS_DIR), nunca en el repositorio.
"""
from __future__ import annotations

import shutil
import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from tests.integracion.conftest import CLAVES_PRUEBA, MOTIVO_OMISION, URL_PRUEBAS, _alembic

RAIZ = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="package")
def entorno_contrato(tmp_path_factory):
    from app.config import obtener_ajustes
    from app.servicios import datos, inferencia

    if not URL_PRUEBAS:
        pytest.skip(f"pruebas de contrato omitidas: {MOTIVO_OMISION}")
    copia = tmp_path_factory.mktemp("datos_contrato") / "datos"
    shutil.copytree(RAIZ / "datos", copia)
    mp = pytest.MonkeyPatch()
    # FUENTE_DATABASE_URL vacía: la capa de segmentos queda en modo offline (sin agregación ni refrescos), igual en
    # cualquier equipo y en el CI; tests/integracion/test_segmentos_materializados.py prueba el modo integrado.
    for nombre, valor in {"DATA_DIR": str(copia), "MODELOS_DIR": str(copia / "modelos"),
                          "AUTH_HABILITADA": "true", "METRICAS_PUBLICAS": "true",
                          "PLANIFICADOR_HABILITADO": "false", "REANUDAR_EJECUCIONES": "false",
                          "FUENTE_DATABASE_URL": ""}.items():
        mp.setenv(nombre, valor)
    obtener_ajustes.cache_clear()
    datos.limpiar_cache()
    inferencia.limpiar_cache()
    try:
        yield copia
    finally:
        mp.undo()
        obtener_ajustes.cache_clear()
        datos.limpiar_cache()
        inferencia.limpiar_cache()


@pytest.fixture(scope="package")
def app_contrato(entorno_contrato):
    _alembic("downgrade", "base")
    _alembic("upgrade", "head")
    from app.main import app

    return app


@pytest.fixture(scope="package")
def cliente_contrato(app_contrato):
    from fastapi.testclient import TestClient

    with TestClient(app_contrato, headers={"X-API-Key": CLAVES_PRUEBA["admin"]}) as c:
        yield c


@pytest.fixture(scope="package")
def claves() -> dict[str, str]:
    return dict(CLAVES_PRUEBA)


@pytest.fixture(scope="package")
def sembrado(cliente_contrato) -> dict:
    """Datos reales mínimos para que cada ruta devuelva contenido: una ejecución completa con un tramo pequeño de la
    serie real (predicciones y recomendaciones) y una alerta abierta."""
    from app.db import sesion_contexto
    from app.servicios import datos, ejecucion, fuentes

    tramo = datos.demanda_horaria(desde=date(2025, 2, 24), hasta=date(2025, 3, 4))
    mp = pytest.MonkeyPatch()
    mp.setattr(ejecucion, "obtener_fuente", lambda: fuentes.FuenteParquet(cargador=lambda: tramo.copy()))
    try:
        r = cliente_contrato.post("/api/v1/frequency/executions", json={"hasta": "2025-03-02"})
    finally:
        mp.undo()
    assert r.status_code == 202, r.text
    eid = r.json()["execution_id"]
    detalle = cliente_contrato.get(f"/api/v1/frequency/executions/{eid}").json()
    assert detalle["estado"] == "ok", detalle.get("mensaje")
    pred = cliente_contrato.get("/api/v1/predictions", params={"execution_id": eid, "limite": 1}).json()["items"]
    assert pred, "la ejecución de siembra no dejó predicciones"
    ahora = datetime.now(UTC)
    with sesion_contexto() as s:
        alerta, _ = ejecucion.guardar_alerta(s, {
            "codigo": "ALT-002", "ruta": "SILENCIO", "severidad": "critica", "detectada_en": ahora,
            "ventana_inicio": ahora, "ventana_fin": ahora + timedelta(hours=1), "horizonte_min": 60,
            "observado": 0.95, "esperado": 0.85, "umbral": 0.9, "puntaje": 0.7, "explicacion": "contrato",
            "variables": {"origen": "contrato"}, "recomendacion": "Despacho adicional",
            "clave_dedup": f"ALT-002|SILENCIO|contrato-{uuid.uuid4()}"}, None, 1)
        alert_id = str(alerta.alert_id)
    modelos = cliente_contrato.get("/api/v1/models", params={"limite": 100}).json()["items"]
    return {"execution_id": eid, "prediction_id": pred[0]["prediction_id"], "alert_id": alert_id,
            "model_id": next(m["model_id"] for m in modelos if m["estado"] == "activo"),
            "modelos": {m["model_id"]: m["estado"] for m in modelos}}


@pytest.fixture
def sin_trabajos(monkeypatch):
    """Los POST que crean jobs (ejecución, entrenamiento) quedan en cola sin procesarse: el contrato es la respuesta
    202, y así una prueba de contrato no entrena modelos ni relee la serie."""
    from app.servicios import ejecucion

    monkeypatch.setattr(ejecucion, "ejecutar", lambda *a, **k: None)
