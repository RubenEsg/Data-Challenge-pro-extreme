"""Testcontainers (§14.1 «Integración»): migraciones, repositorios y API contra un PostGIS 14-3.4 efímero.

Cubre la fila «Integración | pytest, Testcontainers PostgreSQL/PostGIS | Repositorios, migraciones y API» y los
criterios de §14.2 «crea el esquema mediante migraciones» y «una carga repetida con la misma clave no duplica».
"""
from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import create_engine, func, inspect, select, text

from tests.testcontainers.conftest import alembic, revision_head

pytestmark = [pytest.mark.testcontainers, pytest.mark.integracion]

TABLAS = {"model_registry", "prediction", "recommendation", "alert", "alert_history", "execution_log",
          "data_quality_error", "threshold_config", "notification_log", "demanda_observada", "execution_attempt"}


def _inspeccion(url: str):
    motor = create_engine(url)
    return motor, inspect(motor)


# ---------------------------------------------------------------- migraciones desde cero
def test_contenedor_es_postgis_14_3_4_y_esta_vacio(entorno_contenedor):
    motor = create_engine(entorno_contenedor["url"])
    with motor.connect() as c:
        version = c.execute(text("SHOW server_version")).scalar()
        postgis = c.execute(text("SELECT postgis_lib_version()")).scalar()
        esquemas = set(c.execute(text("SELECT nspname FROM pg_namespace")).scalars())
    motor.dispose()
    assert version.startswith("14."), version
    assert postgis.startswith("3.4"), postgis
    assert "ai_frecuencias" not in esquemas, "el contenedor debe empezar sin el esquema (lo crea Alembic)"


def test_alembic_upgrade_downgrade_upgrade_desde_cero(entorno_contenedor):
    url = entorno_contenedor["url"]
    alembic(url, "upgrade", "head")
    motor, insp = _inspeccion(url)
    assert TABLAS <= set(insp.get_table_names(schema="ai_frecuencias"))
    with motor.connect() as c:
        assert c.execute(text("SELECT version_num FROM ai_frecuencias.alembic_version")).scalar() == revision_head()
    motor.dispose()

    alembic(url, "downgrade", "base")
    motor, insp = _inspeccion(url)
    quedan = set(insp.get_table_names(schema="ai_frecuencias")) - {"alembic_version"}
    motor.dispose()
    assert not quedan & TABLAS, f"downgrade base dejó tablas: {sorted(quedan & TABLAS)}"

    alembic(url, "upgrade", "head")
    motor, insp = _inspeccion(url)
    assert TABLAS <= set(insp.get_table_names(schema="ai_frecuencias"))
    motor.dispose()


def test_indices_restricciones_y_semillas(migrado):
    motor, insp = _inspeccion(migrado["url"])
    indices_alerta = {i["name"] for i in insp.get_indexes("alert", schema="ai_frecuencias")}
    assert {"ux_alert_dedup_abiertas", "ix_alert_estado"} <= indices_alerta
    indices_modelo = {i["name"] for i in insp.get_indexes("model_registry", schema="ai_frecuencias")}
    assert "ux_model_registry_un_activo" in indices_modelo
    unicas = {u["name"] for u in insp.get_unique_constraints("demanda_observada", schema="ai_frecuencias")}
    assert "ux_demanda_observada_clave" in unicas
    with motor.connect() as c:
        # semillas de la 0001 (versión 1, §5.1); migraciones posteriores pueden crear versiones nuevas del conjunto
        semillas = dict(c.execute(text(
            "SELECT nombre, valor FROM ai_frecuencias.threshold_config WHERE version = 1")).all())
        vigentes = c.execute(text("SELECT DISTINCT version FROM ai_frecuencias.threshold_config WHERE vigente")
                             ).scalars().all()
        maxima = c.execute(text("SELECT MAX(version) FROM ai_frecuencias.threshold_config")).scalar()
    motor.dispose()
    assert semillas["ocupacion_critica"] == 0.9 and semillas["baja_utilizacion"] == 0.3
    assert semillas["error_pronostico"] == 0.15 and semillas["periodos_atraso"] == 2
    assert vigentes == [maxima], "debe haber un solo conjunto vigente: la versión más reciente"


# ---------------------------------------------------------------- repositorios
@pytest.fixture
def sesion_tc(migrado):
    from app.db import nueva_sesion

    s = nueva_sesion()
    yield s
    s.rollback()
    s.close()


def test_repositorio_ejecucion_y_carga_repetida_sin_duplicar(sesion_tc):
    from app.modelos_db import DemandaObservada, Ejecucion
    from app.servicios import datos, ejecucion

    e = ejecucion.crear_ejecucion(sesion_tc, "frecuencia", {"origen": "testcontainers"}, "tc-repo")
    sesion_tc.commit()
    leida = sesion_tc.get(Ejecucion, e.execution_id)
    assert leida.estado == "en_cola" and leida.correlation_id == "tc-repo"

    lote = datos.demanda_horaria(desde=date(2025, 3, 3), hasta=date(2025, 3, 4))
    antes = sesion_tc.scalar(select(func.count()).select_from(DemandaObservada))
    ejecucion._incorporar_historico(sesion_tc, lote, e.execution_id)
    sesion_tc.commit()
    medio = sesion_tc.scalar(select(func.count()).select_from(DemandaObservada))
    ejecucion._incorporar_historico(sesion_tc, lote, e.execution_id)   # misma clave (ruta, fecha, hora)
    sesion_tc.commit()
    despues = sesion_tc.scalar(select(func.count()).select_from(DemandaObservada))
    assert medio - antes == len(lote) > 0 and despues == medio


def test_repositorio_alertas_deduplica_e_historial(sesion_tc):
    from app.modelos_db import Alerta
    from app.servicios import ejecucion

    ahora = datetime.now(UTC)
    clave = f"ALT-002|SILENCIO|tc-{uuid.uuid4()}"
    base = {"codigo": "ALT-002", "ruta": "SILENCIO", "severidad": "critica", "detectada_en": ahora,
            "ventana_inicio": ahora, "ventana_fin": ahora + timedelta(hours=1), "horizonte_min": 60,
            "observado": 0.95, "esperado": 0.85, "umbral": 0.9, "puntaje": 0.7, "explicacion": "testcontainers",
            "variables": {"x": 1}, "recomendacion": "Despacho adicional", "clave_dedup": clave}
    a1, nueva1 = ejecucion.guardar_alerta(sesion_tc, dict(base), None, 1)
    a2, nueva2 = ejecucion.guardar_alerta(sesion_tc, dict(base), None, 1)
    sesion_tc.commit()
    assert nueva1 and not nueva2 and a1.alert_id == a2.alert_id and a2.ocurrencias == 2
    assert sesion_tc.scalar(select(func.count()).select_from(Alerta).where(Alerta.clave_dedup == clave)) == 1


def test_repositorio_umbrales_vigentes(sesion_tc):
    from app.servicios import ejecucion

    version, valores = ejecucion.umbrales_vigentes(sesion_tc)
    assert version >= 1 and 0 < float(valores["ocupacion_critica"]) <= 1


# ---------------------------------------------------------------- API contra el contenedor
def test_api_health_y_autenticacion(cliente_tc, claves_tc):
    salud = cliente_tc.get("/health")
    assert salud.status_code == 200 and salud.json()["base_datos"] == "ok"
    sin_clave = cliente_tc.get("/api/v1/models", headers={"X-API-Key": ""})
    assert sin_clave.status_code == 401 and sin_clave.headers["WWW-Authenticate"].startswith("ApiKey")
    operador = cliente_tc.put("/api/v1/thresholds", json={"valores": {"ocupacion_critica": 0.9},
                                                           "creado_por": "tc"},
                              headers={"X-API-Key": claves_tc["operador"]})
    assert operador.status_code == 403


def test_api_ciclo_incremental_completo_en_contenedor(cliente_tc, monkeypatch):
    """POST /frequency/executions con un tramo real pequeño: lectura, calidad, predicción, recomendación y alertas."""
    from app.servicios import datos, ejecucion, fuentes

    tramo = datos.demanda_horaria(desde=date(2025, 2, 24), hasta=date(2025, 3, 4))
    monkeypatch.setattr(ejecucion, "obtener_fuente", lambda: fuentes.FuenteParquet(cargador=lambda: tramo.copy()))
    r = cliente_tc.post("/api/v1/frequency/executions", json={"hasta": "2025-03-02"},
                        headers={"X-Correlation-Id": "tc-ciclo"})
    assert r.status_code == 202, r.text
    detalle = cliente_tc.get(f"/api/v1/frequency/executions/{r.json()['execution_id']}").json()
    assert detalle["estado"] == "ok", detalle.get("mensaje")
    assert detalle["filas_leidas"] > 0 and detalle["predicciones"] > 0 and detalle["recomendaciones"] > 0
    assert detalle["correlation_id"] == "tc-ciclo"

    predicciones = cliente_tc.get("/api/v1/predictions", params={"execution_id": detalle["execution_id"]}).json()
    assert predicciones["total"] == detalle["predicciones"]
    p = predicciones["items"][0]
    assert p["horizonte_min"] in (30, 60, 120) and p["model_id"] and p["p10"] <= p["pasajeros"] <= p["p90"]

    repetida = cliente_tc.post("/api/v1/frequency/executions", json={"hasta": "2025-03-02"})
    segunda = cliente_tc.get(f"/api/v1/frequency/executions/{repetida.json()['execution_id']}").json()
    assert segunda["estado"] == "ok" and segunda["filas_leidas"] == 0, "la marca de agua debe evitar releer"
    modelos = cliente_tc.get("/api/v1/models").json()
    assert modelos["total"] >= 1 and any(m["estado"] == "activo" for m in modelos["items"])
