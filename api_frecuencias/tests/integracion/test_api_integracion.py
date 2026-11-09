"""Integración: migraciones, ejecución incremental, deduplicación, alertas, modelos, umbrales y exportaciones."""
from __future__ import annotations

import io
import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import func, inspect, select, text

from app.modelos_db import Alerta, DemandaObservada, Ejecucion, RegistroModelo, Umbral

TABLAS = {"model_registry", "prediction", "recommendation", "alert", "alert_history", "execution_log",
          "data_quality_error", "threshold_config", "notification_log", "demanda_observada"}


# ---------------------------------------------------------------- migraciones
def test_migracion_crea_esquema_y_siembra_umbrales(migrada, sesion):
    tablas = set(inspect(sesion.get_bind()).get_table_names(schema="ai_frecuencias"))
    assert TABLAS <= tablas
    filas = sesion.scalars(select(Umbral).where(Umbral.vigente)).all()
    valores = {f.nombre: f.valor for f in filas}
    assert {f.version for f in filas} == {1}
    assert valores["ocupacion_critica"] == 0.9 and valores["baja_utilizacion"] == 0.3
    assert valores["error_pronostico"] == 0.15 and valores["periodos_atraso"] == 2
    indices = {i["name"] for i in inspect(sesion.get_bind()).get_indexes("alert", schema="ai_frecuencias")}
    assert "ux_alert_dedup_abiertas" in indices and "ix_alert_estado" in indices


# ---------------------------------------------------------------- ejecución incremental
@pytest.fixture
def fuente_pequena(monkeypatch):
    """Fuente Parquet real con un tramo pequeño de datos reales (rápida y determinista)."""
    from app.servicios import datos, ejecucion, fuentes

    tramo = datos.demanda_horaria(desde=date(2025, 2, 24), hasta=date(2025, 3, 4))
    monkeypatch.setattr(ejecucion, "obtener_fuente", lambda: fuentes.FuenteParquet(cargador=lambda: tramo.copy()))
    return tramo


def _correr(cliente, **cuerpo):
    r = cliente.post("/api/v1/frequency/executions", json=cuerpo, headers={"X-Correlation-Id": "prueba-ejec"})
    assert r.status_code == 202, r.text
    assert r.headers["X-Correlation-Id"] == "prueba-ejec"
    detalle = cliente.get(f"/api/v1/frequency/executions/{r.json()['execution_id']}")
    assert detalle.status_code == 200
    return detalle.json()


def test_ejecucion_incremental_respeta_marca_de_agua(cliente, fuente_pequena, sesion):
    primera = _correr(cliente, hasta="2025-03-02")
    assert primera["estado"] == "ok", primera["mensaje"]
    assert primera["filas_leidas"] > 0 and primera["predicciones"] == 9 and primera["recomendaciones"] == 9
    assert primera["correlation_id"] == "prueba-ejec" and primera["umbrales_version"] >= 1
    assert primera["model_id"] and primera["marca_agua_nueva"]

    segunda = _correr(cliente, hasta="2025-03-02")
    assert segunda["estado"] == "ok" and segunda["filas_leidas"] == 0 and segunda["predicciones"] == 0
    assert segunda["marca_agua_anterior"] == primera["marca_agua_nueva"]

    tercera = _correr(cliente, hasta="2025-03-03")
    assert tercera["estado"] == "ok" and 0 < tercera["filas_leidas"] < primera["filas_leidas"]

    claves = sesion.execute(select(func.count(), func.count(func.distinct(
        func.concat(DemandaObservada.ruta, DemandaObservada.fecha, DemandaObservada.hora))))).one()
    assert claves[0] == claves[1]


def test_carga_repetida_no_duplica(migrada, fuente_pequena, sesion):
    from app.servicios import ejecucion

    e = ejecucion.crear_ejecucion(sesion, "frecuencia", {}, None)
    lote = fuente_pequena[fuente_pequena["fecha"] == date(2025, 3, 4)]
    antes = sesion.scalar(select(func.count()).select_from(DemandaObservada))
    ejecucion._incorporar_historico(sesion, lote, e.execution_id)
    sesion.commit()
    medio = sesion.scalar(select(func.count()).select_from(DemandaObservada))
    ejecucion._incorporar_historico(sesion, lote, e.execution_id)
    sesion.commit()
    despues = sesion.scalar(select(func.count()).select_from(DemandaObservada))
    assert medio - antes == len(lote) and despues == medio


def test_reinicio_reencola_ejecuciones_corriendo(migrada, sesion):
    from app.servicios import ejecucion

    e = ejecucion.crear_ejecucion(sesion, "frecuencia", {}, None)
    sesion.execute(text("UPDATE ai_frecuencias.execution_log SET estado='corriendo' WHERE execution_id=:i"),
                   {"i": e.execution_id})
    sesion.commit()
    assert e.execution_id in ejecucion.recuperar_interrumpidas()
    sesion.expire_all()
    assert sesion.get(Ejecucion, e.execution_id).estado == "en_cola"
    sesion.execute(text("UPDATE ai_frecuencias.execution_log SET estado='error' WHERE execution_id=:i"),
                   {"i": e.execution_id})
    sesion.commit()


# ---------------------------------------------------------------- alertas
def _alerta_base(clave: str) -> dict:
    ahora = datetime.now(UTC)
    return {"codigo": "ALT-002", "ruta": "SILENCIO", "severidad": "critica", "detectada_en": ahora,
            "ventana_inicio": ahora, "ventana_fin": ahora + timedelta(hours=1), "horizonte_min": 60,
            "observado": 0.95, "esperado": 0.85, "umbral": 0.9, "puntaje": 0.7, "explicacion": "prueba",
            "variables": {"x": 1}, "recomendacion": "Despacho adicional", "clave_dedup": clave}


def test_alertas_deduplicadas_y_bitacora(cliente, sesion):
    from app.servicios import ejecucion

    clave = f"ALT-002|SILENCIO|{uuid.uuid4()}"
    a1, nueva1 = ejecucion.guardar_alerta(sesion, _alerta_base(clave), None, 1)
    a2, nueva2 = ejecucion.guardar_alerta(sesion, _alerta_base(clave), None, 1)
    sesion.commit()
    assert nueva1 and not nueva2 and a1.alert_id == a2.alert_id and a2.ocurrencias == 2
    assert sesion.scalar(select(func.count()).select_from(Alerta).where(Alerta.clave_dedup == clave)) == 1

    url = f"/api/v1/alerts/{a1.alert_id}/status"
    assert cliente.patch(url, json={"accion": "cerrar", "usuario": "ana"}).status_code == 409
    assert cliente.patch(url, json={"accion": "reconocer", "usuario": "ana"}).json()["estado"] == "reconocida"
    assert cliente.patch(url, json={"accion": "asignar", "usuario": "ana"}).status_code == 422
    r = cliente.patch(url, json={"accion": "asignar", "usuario": "ana", "asignado_a": "despacho"})
    assert r.json()["estado"] == "asignada" and r.json()["asignado_a"] == "despacho"
    r = cliente.patch(url, json={"accion": "comentar", "usuario": "ana", "comentario": "bus extra enviado"})
    assert r.json()["estado"] == "asignada" and len(r.json()["comentarios"]) == 1
    assert cliente.patch(url, json={"accion": "cerrar", "usuario": "ana"}).json()["estado"] == "cerrada"
    historia = cliente.get(f"/api/v1/alerts/{a1.alert_id}/history").json()
    assert [h["accion"] for h in historia] == ["crear", "reconocer", "asignar", "comentar", "cerrar"]
    assert historia[-1]["estado_anterior"] == "asignada" and historia[-1]["estado_nuevo"] == "cerrada"

    # cerrada la anterior, la misma clave puede abrir una alerta nueva
    a3, nueva3 = ejecucion.guardar_alerta(sesion, _alerta_base(clave), None, 1)
    sesion.commit()
    assert nueva3 and a3.alert_id != a1.alert_id
    listado = cliente.get("/api/v1/alerts", params={"estado": "nueva", "severidad": "critica", "ruta": "SILENCIO"})
    assert listado.status_code == 200 and listado.json()["total"] >= 1


# ---------------------------------------------------------------- modelos
def _modelo(sesion, model_id: str, estado: str) -> RegistroModelo:
    m = RegistroModelo(model_id=model_id, version="1", tipo="candidato", artefacto=f"{model_id}.joblib",
                       sha256="0" * 64, feature_version="fv-prueba",
                       data_cutoff=datetime(2025, 6, 30, tzinfo=UTC), metricas={}, estado=estado,
                       auditoria=[])
    sesion.add(m)
    sesion.commit()
    return m


def test_activacion_controlada_y_reversion(cliente, sesion, monkeypatch):
    from app.servicios import inferencia

    previo_real = sesion.scalar(select(RegistroModelo.model_id).where(RegistroModelo.estado == "activo"))
    sesion.execute(text("UPDATE ai_frecuencias.model_registry SET estado='retirado' WHERE estado='activo'"))
    sesion.commit()
    sufijo = uuid.uuid4().hex[:6]
    base, malo, bueno = f"base-{sufijo}", f"malo-{sufijo}", f"bueno-{sufijo}"
    _modelo(sesion, base, "activo")
    _modelo(sesion, malo, "candidato")
    _modelo(sesion, bueno, "candidato")
    wapes = {base: 15.0, malo: 18.5, bueno: 13.9}
    ventanas = []

    def evaluar(model_id, desde, hasta, *a, **k):
        ventanas.append((model_id, desde, hasta))
        return {"wape": wapes[model_id], "mae": 1.0, "rmse": 1.0, "por_ruta": {}}

    monkeypatch.setattr(inferencia, "evaluar", evaluar)
    r = cliente.post(f"/api/v1/models/{malo}/activate", json={"aprobado_por": "comite"})
    assert r.status_code == 409 and r.json()["error"]["codigo"] == "activacion_rechazada"
    assert cliente.get(f"/api/v1/models/{malo}").json()["estado"] == "rechazado"
    assert ventanas[0][1:] == ventanas[1][1:]  # misma validación temporal para ambos

    r = cliente.post(f"/api/v1/models/{bueno}/activate", json={"aprobado_por": "comite", "motivo": "mejor WAPE"})
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["estado"] == "activo" and cuerpo["anterior_model_id"] == base and cuerpo["aprobado_por"] == "comite"
    assert cuerpo["metricas"]["validacion_activacion"]["candidato"]["wape"] == 13.9
    assert cliente.get(f"/api/v1/models/{base}").json()["estado"] == "retirado"

    r = cliente.post("/api/v1/models/rollback", json={"usuario": "comite", "motivo": "prueba de reversión"})
    assert r.status_code == 200 and r.json()["model_id"] == base and r.json()["estado"] == "activo"
    activos = cliente.get("/api/v1/models", params={"estado": "activo"}).json()
    assert activos["total"] == 1 and activos["items"][0]["model_id"] == base

    # deja activo de nuevo el modelo real que había antes de la prueba
    sesion.execute(text("UPDATE ai_frecuencias.model_registry SET estado='retirado' WHERE estado='activo'"))
    if previo_real:
        sesion.execute(text("UPDATE ai_frecuencias.model_registry SET estado='activo' WHERE model_id=:m"),
                       {"m": previo_real})
    sesion.commit()


# ---------------------------------------------------------------- umbrales, exportación, contrato
def test_umbrales_versionados(cliente):
    antes = cliente.get("/api/v1/thresholds").json()
    r = cliente.put("/api/v1/thresholds", json={"valores": {"ocupacion_critica": 0.92}, "creado_por": "operacion"})
    assert r.status_code == 200 and r.json()["version"] == antes["version"] + 1
    assert r.json()["valores"]["ocupacion_critica"] == 0.92
    assert r.json()["valores"]["baja_utilizacion"] == antes["valores"]["baja_utilizacion"]
    historia = cliente.get("/api/v1/thresholds/history", params={"nombre": "ocupacion_critica"}).json()
    assert [h["version"] for h in historia][:2] == [antes["version"] + 1, antes["version"]]
    malo = cliente.put("/api/v1/thresholds", json={"valores": {"ocupacion_critica": 7}, "creado_por": "x"})
    assert malo.status_code == 422 and malo.json()["error"]["codigo"] == "umbral_invalido"


def test_exportaciones_csv_y_xlsx(cliente, fuente_pequena):
    import openpyxl

    r = cliente.post("/api/v1/predictions/run", json={"ruta": "CRA 54", "instante": "2025-03-04T06:30:00-05:00",
                                                      "horizonte_min": 30})
    assert r.status_code == 201, r.text
    p = r.json()
    assert p["p10"] <= p["pasajeros"] <= p["p90"] and p["explicacion"] and p["recomendacion"]["buses_hora"] >= 1
    csv = cliente.get("/api/v1/predictions/export", params={"formato": "csv", "ruta": "CRA 54"})
    assert csv.status_code == 200 and csv.headers["content-type"].startswith("text/csv")
    assert "prediction_id" in csv.content.decode("utf-8-sig").splitlines()[0]
    xlsx = cliente.get("/api/v1/recommendations/export", params={"formato": "xlsx"})
    assert xlsx.status_code == 200
    hoja = openpyxl.load_workbook(io.BytesIO(xlsx.content)).active
    assert hoja.max_row >= 2 and "recommendation_id" in [c.value for c in hoja[1]]
    assert cliente.get("/api/v1/predictions/export", params={"formato": "pdf"}).status_code == 422


def test_contrato_errores_paginacion_y_observabilidad(cliente):
    r = cliente.get(f"/api/v1/frequency/executions/{uuid.uuid4()}")
    assert r.status_code == 404 and set(r.json()["error"]) == {"codigo", "mensaje", "detalle", "correlation_id"}
    r = cliente.get("/api/v1/predictions", params={"orden": "no_existe"})
    assert r.status_code == 422 and r.json()["error"]["codigo"] == "orden_invalido"
    r = cliente.get("/api/v1/frequency/executions", params={"limite": 1, "desplazamiento": 0, "orden": "-creado_en"})
    assert r.status_code == 200 and r.json()["limite"] == 1 and len(r.json()["items"]) <= 1
    assert "X-Correlation-Id" in r.headers
    assert cliente.get("/health").json()["base_datos"] == "ok"
    assert "api_peticiones_total" in cliente.get("/metrics").text
    rutas = cliente.get("/openapi.json").json()["paths"]
    for ruta in ("/api/v1/frequency/executions", "/api/v1/frequency/executions/{execution_id}",
                 "/api/v1/predictions/run", "/api/v1/predictions", "/api/v1/recommendations/calculate",
                 "/api/v1/recommendations", "/api/v1/alerts", "/api/v1/alerts/{alert_id}/status",
                 "/api/v1/models", "/api/v1/models/{model_id}/activate"):
        assert ruta in rutas
