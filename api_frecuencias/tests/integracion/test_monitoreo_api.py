"""Integración: monitoreo por ejecución (§9.4), foto de variables particionada (§11.2), columnas nuevas de
prediction, retador en sombra con compuerta y reversión (RF-018, RF-019), evaluación e importancia, y segmentos.

Usa un tramo real de sep-2025 (fuera de muestra del modelo activo) y deja la base como la encontró: borra sus
ejecuciones (y con ellas monitoreo, fotos, predicciones, alertas y demanda observada) y restaura el registro.
"""
from __future__ import annotations

import re
import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy import delete, select, text

from app.modelos_db import (
    Alerta,
    DemandaObservada,
    Ejecucion,
    FotoVariables,
    MonitoreoModelo,
    Prediccion,
    Recomendacion,
    RegistroModelo,
)

ACTIVO = "hgb_fv2_20250831_s42"
RETADOR = "hgb_fv1_20250831_s42"


def _correr(cliente, hasta: str, cid: str) -> dict:
    r = cliente.post("/api/v1/frequency/executions", json={"hasta": hasta}, headers={"X-Correlation-Id": cid})
    assert r.status_code == 202, r.text
    d = cliente.get(f"/api/v1/frequency/executions/{r.json()['execution_id']}").json()
    assert d["estado"] == "ok", d["mensaje"]
    return d


def _limpiar(s, ids: list) -> None:
    if not ids:
        return
    s.execute(delete(DemandaObservada).where(DemandaObservada.execution_id.in_(ids)))
    s.execute(delete(Alerta).where(Alerta.execution_id.in_(ids)))
    s.execute(delete(Recomendacion).where(Recomendacion.execution_id.in_(ids)))
    s.execute(delete(Prediccion).where(Prediccion.execution_id.in_(ids)))
    s.execute(delete(Ejecucion).where(Ejecucion.execution_id.in_(ids)))
    s.commit()


@pytest.fixture(scope="module")
def entorno(cliente):
    """Registro conocido (fv2 activo, fv1 candidato), fuente con sep-2025 y limpieza al final."""
    from app.db import nueva_sesion
    from app.servicios import datos, ejecucion, fuentes

    s = nueva_sesion()
    ejecucion.sembrar_registro(s)
    previos = {m.model_id: (m.estado, m.anterior_model_id, dict(m.metricas or {}), list(m.auditoria or []))
               for m in s.scalars(select(RegistroModelo)).all()}
    if ACTIVO not in previos or RETADOR not in previos:
        s.close()
        pytest.skip("el registro empaquetado no trae fv1 y fv2")
    for m in s.scalars(select(RegistroModelo).where(RegistroModelo.estado == "activo")).all():
        m.estado = "candidato"
    s.flush()
    s.scalar(select(RegistroModelo).where(RegistroModelo.model_id == ACTIVO)).estado = "activo"
    s.commit()
    tramo = datos.demanda_horaria(desde=date(2025, 9, 1), hasta=date(2025, 9, 25))
    # independiente de la marca de agua que dejen otros módulos: los días llegan «ahora» (uno por día de datos);
    # al final se borran estas ejecuciones y la marca vuelve a la anterior
    import pandas as pd

    base = pd.Timestamp.now(tz="America/Bogota") + pd.Timedelta(days=1)
    tramo["ultima_actualizacion"] = base + pd.to_timedelta(
        [(f - date(2025, 9, 1)).days for f in tramo["fecha"]], unit="D")
    mp = pytest.MonkeyPatch()
    mp.setattr(ejecucion, "obtener_fuente", lambda: fuentes.FuenteParquet(cargador=lambda: tramo.copy()))
    ids: list = []
    try:
        yield {"sesion": s, "ids": ids}
    finally:
        mp.undo()
        s.rollback()
        _limpiar(s, ids)
        s.execute(delete(RegistroModelo).where(RegistroModelo.model_id.like("hgb_prueba_analitica%")))
        for m in s.scalars(select(RegistroModelo).where(RegistroModelo.estado == "activo")).all():
            m.estado = "candidato"
        s.flush()
        for mid, (estado, anterior, metricas, auditoria) in previos.items():
            m = s.scalar(select(RegistroModelo).where(RegistroModelo.model_id == mid))
            if m is not None and estado != "activo":
                m.estado, m.anterior_model_id, m.metricas, m.auditoria = estado, anterior, metricas, auditoria
        s.flush()
        for mid, (estado, anterior, metricas, auditoria) in previos.items():
            m = s.scalar(select(RegistroModelo).where(RegistroModelo.model_id == mid))
            if m is not None and estado == "activo":
                m.estado, m.anterior_model_id, m.metricas, m.auditoria = estado, anterior, metricas, auditoria
        s.commit()
        s.close()


@pytest.fixture(scope="module")
def primera(cliente, entorno):
    d = _correr(cliente, "2025-09-15", "analitica-mon-1")
    entorno["ids"].append(uuid.UUID(d["execution_id"]))
    return d


def test_ciclo_guarda_monitoreo_foto_y_columnas_nuevas(primera, entorno):
    s = entorno["sesion"]
    eid = uuid.UUID(primera["execution_id"])
    mon = primera["metricas"]["monitoreo"]
    assert primera["predicciones"] == 9 and mon["estado"] in ("ok", "aviso", "alerta")
    fila = s.scalar(select(MonitoreoModelo).where(MonitoreoModelo.execution_id == eid, MonitoreoModelo.rol == "activo"))
    assert fila.model_id == ACTIVO and fila.ventana_dias == 28 and fila.n_predicciones == 9
    assert fila.hasta == date(2025, 9, 15) and 0 < fila.wape_movil < 0.5 and 0 < fila.cobertura_p10_p90 <= 1
    assert {"lag7", "dia_lag7", "objetivo", "prediccion"} <= set(fila.psi) and fila.estado == mon["estado"]
    assert fila.alertas_total is not None and fila.predicciones_ventana >= 9
    fotos = s.scalars(select(FotoVariables).where(FotoVariables.execution_id == eid)).all()
    assert len(fotos) == mon["feature_snapshot_filas"] > 9
    from app.servicios import variables

    assert set(fotos[0].features) == set(variables.columnas(variables.FV2)) | {"_fraccion_ventana"}
    assert fotos[0].feature_version == variables.FV2 and fotos[0].data_cutoff is not None
    # dimensiones de §8.3 en la foto: idruta del catálogo y día ISO de la fecha de la fila
    if hasattr(FotoVariables, "idruta"):
        from app.servicios import dimensiones

        assert all(f.idruta == dimensiones.idruta(f.ruta) and f.id_dia_semana == f.fecha.isoweekday() for f in fotos)
    particiones = s.execute(text(
        "SELECT c.relname FROM pg_inherits i JOIN pg_class c ON c.oid = i.inhrelid "
        "JOIN pg_class p ON p.oid = i.inhparent WHERE p.relname = 'feature_snapshot'")).scalars().all()
    assert "feature_snapshot_202509" in particiones
    preds = s.scalars(select(Prediccion).where(Prediccion.execution_id == eid)).all()
    assert all(p.p10_modelo is not None and p.p90_modelo is not None for p in preds)
    assert all(p.explicacion_local and p.explicacion_local["metodo"] == "shap_tree_exacto" for p in preds)
    assert any(p.ajuste_conformal is not None for p in preds)
    e = s.get(Ejecucion, eid)
    assert e.traceparent is None or re.fullmatch(r"00-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}", e.traceparent)


def test_endpoints_de_monitoreo(cliente, primera):
    eid = primera["execution_id"]
    r = cliente.get("/api/v1/monitoring", params={"execution_id": eid})
    assert r.status_code == 200 and r.json()["total"] == 1
    item = r.json()["items"][0]
    assert item["model_id"] == ACTIVO and item["estado"] in ("ok", "aviso", "alerta")
    assert cliente.get("/api/v1/monitoring", params={"estado": "otro"}).status_code == 422
    csv = cliente.get("/api/v1/monitoring/export", params={"formato": "csv", "execution_id": eid})
    assert csv.status_code == 200 and csv.headers["content-type"].startswith("text/csv")
    assert "wape_movil" in csv.content.decode("utf-8-sig").splitlines()[0]
    fotos = cliente.get("/api/v1/monitoring/feature-snapshots", params={"execution_id": eid, "limite": 500})
    assert fotos.status_code == 200
    assert fotos.json()["total"] == primera["metricas"]["monitoreo"]["feature_snapshot_filas"]
    assert cliente.get("/api/v1/monitoring/feature-snapshots").status_code == 422
    pol = cliente.get("/api/v1/monitoring/policy").json()
    assert {"reentrenar", "motivos", "bloqueos", "datos_hasta"} <= set(pol["decision"])
    assert pol["umbrales"]["sombra_dias"] == 14
    # el activo (corte 2025-08-31) ya vio la validación hasta 2025-10-31: con datos hasta 2025-09-15 no hay días nuevos
    assert pol["decision"]["dias_desde_ultimo_entrenamiento"] >= 0


def test_politica_presenta_los_instantes_de_la_sombra_en_bogota(cliente, primera, entorno):
    """§8.1: creado_en de un retador en sombra sale en -05:00 aunque se haya guardado en UTC."""
    s = entorno["sesion"]
    ret = s.scalar(select(RegistroModelo).where(RegistroModelo.model_id == RETADOR))
    estado, metricas = ret.estado, dict(ret.metricas or {})
    ret.estado = "candidato"
    ret.metricas = {**metricas, "sombra": {"estado": "en_sombra", "inicio": "2025-09-16", "dias": 14,
                                           "datos_hasta": "2025-09-15", "creado_en": "2026-11-09T09:30:00+00:00"}}
    s.commit()
    try:
        pol = cliente.get("/api/v1/monitoring/policy").json()
    finally:
        ret.estado, ret.metricas = estado, metricas
        s.commit()
    sombra = next(x for x in pol["en_sombra"] if x["model_id"] == RETADOR)
    assert sombra["sombra"]["creado_en"] == "2026-11-09T04:30:00-05:00"
    assert sombra["creado_en"].endswith("-05:00")
    assert pol["decision"]["dias_desde_ultimo_entrenamiento"] >= 0
    assert any("retador en sombra" in b for b in pol["decision"]["bloqueos"])


def test_umbrales_de_la_politica_estan_versionados(cliente, primera):
    vig = cliente.get("/api/v1/thresholds").json()
    for k in ("psi_alerta", "cobertura_min", "sombra_dias", "reentreno_periodicidad_dias", "activacion_automatica"):
        assert k in vig["valores"]


def test_evaluacion_e_importancia(cliente, primera):
    r = cliente.get(f"/api/v1/models/{ACTIVO}/evaluation", params={"desde": "2025-09-01", "hasta": "2025-09-15"})
    assert r.status_code == 200, r.text
    assert r.json()["metricas_entrenamiento"] and r.json()["ventana"]["wape"] > 0
    assert cliente.get(f"/api/v1/models/{ACTIVO}/evaluation", params={"desde": "2025-09-15"}).status_code == 422
    imp = cliente.get(f"/api/v1/models/{ACTIVO}/importance").json()
    assert imp["permutacion"] and imp["shap"]["shap_local"] is True
    assert cliente.get("/api/v1/models/no_existe/importance").status_code == 404


def test_pronostico_por_segmento_suma_la_ruta(cliente, primera, entorno):
    s = entorno["sesion"]
    pred = s.scalars(select(Prediccion).where(Prediccion.execution_id == uuid.UUID(primera["execution_id"]))).first()
    r = cliente.get("/api/v1/predictions/segmentos", params={"prediction_id": str(pred.prediction_id)})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["suma_segmentos"] == pytest.approx(pred.pasajeros, abs=2e-3)
    assert len(d["segmentos"]) > 100 and {x["sentido"] for x in d["sentidos"]} == {"ida", "regreso"}
    assert "2023" in d["periodo_reparto"] and "no es un modelo por segmento" in d["nota"]
    v = cliente.get("/api/v1/predictions/segmentos", params={"ruta": "CRA 54", "instante": "2025-09-16T07:00:00-05:00",
                                                             "horizonte_min": 120, "nivel": "sentido"}).json()
    assert v["segmentos"] == [] and sum(x["pasajeros"] for x in v["sentidos"]) == pytest.approx(v["pasajeros_ruta"],
                                                                                               abs=0.05)
    assert cliente.get("/api/v1/predictions/segmentos", params={"ruta": "NO", "instante": "2025-09-16T07:00:00"}
                       ).status_code == 404
    assert cliente.get("/api/v1/predictions/segmentos").status_code == 422


def test_retador_en_sombra_compuerta_y_reversion(cliente, primera, entorno, monkeypatch):
    from app.servicios import inferencia, politica

    s = entorno["sesion"]
    ret = s.scalar(select(RegistroModelo).where(RegistroModelo.model_id == RETADOR))
    ret.estado = "candidato"
    ret.metricas = {**(ret.metricas or {}), "sombra": {"estado": "en_sombra", "inicio": "2025-09-16", "dias": 3,
                                                        "datos_hasta": "2025-09-15"}}
    s.commit()
    d = _correr(cliente, "2025-09-18", "analitica-mon-2")
    entorno["ids"].append(uuid.UUID(d["execution_id"]))
    s.expire_all()
    sombra = s.scalar(select(MonitoreoModelo).where(MonitoreoModelo.execution_id == uuid.UUID(d["execution_id"]),
                                                    MonitoreoModelo.rol == "sombra"))
    assert sombra.model_id == RETADOR and len(sombra.detalle["predicciones_sombra"]) == 9
    decision = d["metricas"]["monitoreo"]["politica"]["sombra"][0]
    assert decision["model_id"] == RETADOR and decision["estado"] in ("activado", "rechazado")
    assert decision["compuerta"]["ventana"] == {"desde": "2025-09-16", "hasta": "2025-09-18"}
    ret = s.scalar(select(RegistroModelo).where(RegistroModelo.model_id == RETADOR))
    assert ret.metricas["decision_sombra"]["criterios"]
    assert ret.auditoria[-1]["evento"] in ("activado", "activacion_rechazada")
    # reversión automática: el nuevo activo se degrada en los días posteriores a su activación
    act = s.scalar(select(RegistroModelo).where(RegistroModelo.model_id == ACTIVO))
    if ret.estado != "activo":
        act.estado = "retirado"
        s.flush()
        ret.estado, ret.anterior_model_id = "activo", ACTIVO
        ret.metricas = {**ret.metricas, "activacion": {"datos_hasta": "2025-09-18"}}
        s.flush()
    monkeypatch.setattr(inferencia, "evaluar", lambda mid, *a, **k: {"wape": 30.0 if mid == RETADOR else 15.0})
    out = politica.revisar_reversion(s, {"hasta": "2025-09-22"}, {"wape_max": 0.20})
    assert out["revertido"] is True and out["activo"] == ACTIVO
    s.commit()
    assert s.scalar(select(RegistroModelo).where(RegistroModelo.model_id == ACTIVO)).estado == "activo"
    assert s.scalar(select(RegistroModelo).where(RegistroModelo.model_id == RETADOR)).auditoria[-1]["evento"] == \
        "revertido"


def _sembrar_demanda_validada(s, ids: list, fecha: date) -> int:
    """Horas validadas propias en demanda_observada (≤ datos_hasta), con los valores reales de la serie: la prueba no
    depende de lo que dejen otros módulos. Solo siembra las horas de ese día que aún no están (la clave ruta-fecha-hora
    es única), cuelgan de una ejecución propia (estado «error»: no mueve la marca de agua ni bloquea la cola) y se
    borran con las ejecuciones del módulo. Devuelve cuántas horas validadas hay hasta esa fecha."""
    from sqlalchemy import func

    from app.servicios import datos

    existentes = {(str(r), int(h)) for r, h in s.execute(
        select(DemandaObservada.ruta, DemandaObservada.hora).where(DemandaObservada.fecha == fecha)).all()}
    muestra = datos.demanda_horaria(desde=fecha, hasta=fecha).dropna(subset=["pasajeros"])
    nuevas = [r for r in muestra.itertuples() if (str(r.ruta), int(r.hora)) not in existentes][:3]
    if nuevas:
        lote = uuid.uuid4()
        try:
            s.add(Ejecucion(execution_id=lote, tipo="frecuencia", estado="error", progreso=0, intentos=0,
                            parametros={}, metricas={},
                            mensaje="siembra de demanda validada de la prueba de reentrenamiento"))
            s.flush()
            s.add_all([DemandaObservada(ruta=str(r.ruta), fecha=fecha, hora=int(r.hora), pasajeros=float(r.pasajeros),
                                        execution_id=lote) for r in nuevas])
            s.commit()
        except Exception:
            s.rollback()      # la sesión del módulo queda usable para las pruebas siguientes
            raise
        ids.append(lote)
    return int(s.scalar(select(func.count()).select_from(DemandaObservada).where(DemandaObservada.fecha <= fecha)))


def test_entrenamiento_usa_historial_validado_y_no_pisa_el_activo(cliente, primera, entorno, monkeypatch, tmp_path):
    from app.servicios import inferencia

    monkeypatch.setenv("MODELOS_DIR", str(tmp_path))      # higiene: nada se escribe en datos/modelos
    assert _sembrar_demanda_validada(entorno["sesion"], entorno["ids"], date(2025, 8, 29)) >= 3
    vistos = {}

    def entrenar_falso(hasta, semilla=42, *, serie=None, ids_protegidos=None, **k):
        vistos.update(hasta=hasta, filas=len(serie), max_fecha=max(serie["fecha"]), protegidos=set(ids_protegidos),
                      calibracion_grupos=k.get("calibracion_grupos"))
        mid = vistos.get("forzar_id") or "hgb_prueba_analitica_20250701_s42"
        return {"model_id": mid, "tipo": "candidato", "sha256": "f" * 64, "feature_version": "fv2-2026-11-09",
                "data_cutoff": hasta, "metricas": {"validacion": {}}, "artefacto": str(tmp_path / "x.joblib")}

    monkeypatch.setattr(inferencia, "entrenar", entrenar_falso)
    r = cliente.post("/api/v1/models/train", json={"hasta": "2025-07-01", "datos_hasta": "2025-08-31"})
    assert r.status_code == 202, r.text
    entorno["ids"].append(uuid.UUID(r.json()["execution_id"]))
    det = cliente.get(f"/api/v1/frequency/executions/{r.json()['execution_id']}").json()
    assert det["estado"] == "ok", det["mensaje"]
    assert vistos["hasta"] == date(2025, 7, 1) and ACTIVO in vistos["protegidos"]
    assert vistos["max_fecha"] == date(2025, 8, 31)                 # nada posterior a datos_hasta
    assert det["metricas"]["serie"]["filas_demanda_observada"] >= 3
    assert vistos["calibracion_grupos"] == ("bloque",)              # el candidato se calibra como el activo
    cand = cliente.get("/api/v1/models/hgb_prueba_analitica_20250701_s42").json()
    assert cand["estado"] == "candidato" and cand["metricas"]["sombra"]["estado"] == "en_sombra"
    assert cand["metricas"]["sombra"]["inicio"] == "2025-09-01" and cand["metricas"]["sombra"]["dias"] == 14
    # un reentrenamiento que devolviera el id del activo no reescribe su ficha
    s = entorno["sesion"]
    s.expire_all()
    sha_antes = s.scalar(select(RegistroModelo.sha256).where(RegistroModelo.model_id == ACTIVO))
    vistos["forzar_id"] = ACTIVO
    r2 = cliente.post("/api/v1/models/train", json={"hasta": "2025-07-02"})
    entorno["ids"].append(uuid.UUID(r2.json()["execution_id"]))
    s.expire_all()
    activo = s.scalar(select(RegistroModelo).where(RegistroModelo.model_id == ACTIVO))
    assert activo.sha256 == sha_antes and activo.estado == "activo"
    assert activo.auditoria[-1]["evento"] == "registro_omitido"


def test_decision_del_planificador_usa_la_politica(primera):
    from app.servicios import planificador

    d = planificador.evaluar_reentrenamiento()
    assert {"reentrenar", "motivos", "hasta", "datos_hasta", "modelo_activo"} <= set(d)
    if d["hasta"]:
        assert date.fromisoformat(d["hasta"]) == date.fromisoformat(d["datos_hasta"]) - timedelta(days=61)


def test_politica_decide_por_degradacion_y_periodicidad(primera, entorno):
    from app.servicios import ejecucion, politica

    s = entorno["sesion"]
    s.expire_all()
    s.add_all([MonitoreoModelo(model_id=ACTIVO, rol="activo", ventana_dias=28, wape_movil=0.25, estado="alerta",
                               psi={}, motivos=[], detalle={}) for _ in range(3)])
    s.flush()
    _, umbrales = ejecucion.umbrales_vigentes(s)
    d = politica.decidir_reentreno(s, umbrales, date(2025, 9, 20))
    assert any(m.startswith("degradación") for m in d["motivos"]), d
    d2 = politica.decidir_reentreno(s, umbrales, date(2026, 1, 31))
    assert any(m.startswith("periodicidad") for m in d2["motivos"]), d2
    assert d2["hasta"] == "2025-12-01" and d2["datos_hasta"] == "2026-01-31"
    nuevo = politica.encolar_entrenamiento(s, dict(d2, reentrenar=True), "prueba")
    e = s.get(Ejecucion, nuevo)
    assert e.tipo == "entrenamiento" and e.estado == "en_cola" and e.parametros["datos_hasta"] == "2026-01-31"
    assert politica.encolar_entrenamiento(s, dict(d2, reentrenar=False), "prueba") is None
    s.rollback()


# ---------------------------------------------------------------- datos recientes en la inferencia (RF-013, §9.5)
DIA_NUEVO = date(2026, 1, 8)          # posterior al Parquet empaquetado (termina el 2025-12-31) más sus 7 días
DIA_MOLDE = date(2025, 12, 18)        # mismo día de la semana: sus valores reales hacen de «llegada» del día nuevo


def _sembrar_dia_nuevo(s, ids: list) -> dict:
    """Las 17 horas de servicio de las 3 rutas del día nuevo en demanda_observada (las que aún no estén), colgadas de
    una ejecución propia en estado «error» (no mueve la marca de agua) que se borra al final del módulo."""
    from app.servicios import datos

    existentes = {(str(r), int(h)) for r, h in s.execute(
        select(DemandaObservada.ruta, DemandaObservada.hora).where(DemandaObservada.fecha == DIA_NUEVO)).all()}
    molde = datos.demanda_horaria(desde=DIA_MOLDE, hasta=DIA_MOLDE).dropna(subset=["pasajeros"])
    nuevas = [r for r in molde.itertuples() if (str(r.ruta), int(r.hora)) not in existentes]
    lote = uuid.uuid4()
    s.add(Ejecucion(execution_id=lote, tipo="frecuencia", estado="error", progreso=0, intentos=0, parametros={},
                    metricas={}, mensaje="siembra de un día validado posterior al Parquet (prueba de datos recientes)"))
    s.flush()
    s.add_all([DemandaObservada(ruta=str(r.ruta), fecha=DIA_NUEVO, hora=int(r.hora), pasajeros=float(r.pasajeros),
                                salidas=None if pd_isna(r.salidas) else int(r.salidas), execution_id=lote)
               for r in nuevas])
    s.commit()
    ids.append(lote)
    return {(str(r.ruta), int(r.hora)): float(r.pasajeros) for r in molde.itertuples()}


def pd_isna(v) -> bool:
    import pandas as pd

    return bool(pd.isna(v))


def test_un_dia_validado_despues_del_parquet_actualiza_variables_y_se_pronostica(cliente, entorno):
    """C8 / RF-013: un día que llega y pasa la calidad (demanda_observada) actualiza las variables; con él se pronostica
    el día siguiente, se mide el error contra lo real, se monitorea y se evalúa por la API. Solo con el Parquet
    empaquetado, ese pronóstico no es posible."""
    from datetime import datetime

    from app.servicios import inferencia, monitoreo

    s = entorno["sesion"]
    instante = datetime(2026, 1, 9, 6, tzinfo=inferencia.ZONA)         # el día siguiente al día nuevo
    with pytest.raises(ValueError, match="Sin variables"):
        inferencia.predecir("CRA 54", instante, 60, model_id=ACTIVO)    # sin la serie validada
    with pytest.raises(ValueError, match="No hay datos reales"):
        inferencia.evaluar(ACTIVO, DIA_NUEVO, DIA_NUEVO)
    valores = _sembrar_dia_nuevo(s, entorno["ids"])
    with inferencia.con_sesion(s):
        r = inferencia.predecir("CRA 54", instante, 60, model_id=ACTIVO)
        tabla = inferencia.tabla_variables()
    assert r["pasajeros"] > 0 and r["p10"] <= r["pasajeros"] <= r["p90"] and r["calibracion_version"] == "v2"
    assert r["model_id"] == ACTIVO and r["explicacion_local"]["metodo"] == "shap_tree_exacto"
    assert "demanda_observada" in tabla.attrs["origen"] and inferencia.ultimo_dato_real(tabla) == DIA_NUEVO
    # el rezago de 7 días del 15 de enero ES el valor validado del 8 de enero
    assert tabla.loc[("CRA 54", DIA_NUEVO + timedelta(days=7), 6), "lag7"] == valores[("CRA 54", 6)]
    lote = inferencia.predecir_horas("CRA 54", [instante, instante + timedelta(hours=1)], ACTIVO, sesion=s)
    assert lote[0]["pasajeros"] == r["pasajeros"] and lote[0]["explicacion_local"] == r["explicacion_local"]
    ev = inferencia.evaluar(ACTIVO, DIA_NUEVO, DIA_NUEVO, sesion=s)     # error contra lo que llegó
    assert ev["n"] == len(valores) and ev["wape"] > 0 and "demanda_observada" in ev["origen_datos"]
    mon = monitoreo.calcular(ACTIVO, DIA_NUEVO, sesion=s)
    assert mon["hasta"] == DIA_NUEVO and mon["n_observaciones"] > len(valores) and mon["wape_movil"] > 0
    api = cliente.get(f"/api/v1/models/{ACTIVO}/evaluation", params={"desde": str(DIA_NUEVO), "hasta": str(DIA_NUEVO)})
    assert api.status_code == 200, api.text
    assert api.json()["ventana"]["n"] == len(valores)


# ---------------------------------------------------------------- activación gobernada (RF-019, §9.5)
def _candidato_sintetico(s, sufijo: str, **campos) -> RegistroModelo:
    from datetime import UTC, datetime

    m = RegistroModelo(model_id=f"hgb_prueba_analitica_act_{sufijo}_{uuid.uuid4().hex[:6]}", version="1",
                       tipo="candidato", artefacto="x.joblib", sha256="0" * 64, feature_version="fv2-2026-11-09",
                       data_cutoff=datetime(2025, 6, 30, 5, tzinfo=UTC), metricas={}, estado="candidato",
                       auditoria=[])
    for k, v in campos.items():
        setattr(m, k, v)
    s.add(m)
    s.commit()
    return m


def test_activacion_manual_rechaza_una_ventana_dentro_de_la_muestra(cliente, entorno):
    """El fv1 se entrenó hasta el 2025-08-31 y calibró su banda con la validación hasta el 2025-10-31: compararlo ahí
    sería medirlo dentro de la muestra (422), y su corte también."""
    for desde in ("2025-10-01", "2025-08-31"):
        r = cliente.post(f"/api/v1/models/{RETADOR}/activate", json={"aprobado_por": "comite",
                                                                     "validacion_desde": desde,
                                                                     "validacion_hasta": "2025-11-20"})
        assert r.status_code == 422, r.text
        err = r.json()["error"]
        assert err["codigo"] == "ventana_en_muestra" and err["detalle"]["limite_en_muestra"] == "2025-10-31"


def test_activacion_manual_aplica_los_cuatro_criterios_y_forzar_queda_auditado(cliente, entorno, monkeypatch):
    """La vía manual usa la compuerta de la sombra (WAPE, wape_max, cobertura y sesgo) en la ventana posterior a lo que
    vio el candidato; un rechazado solo vuelve con forzar=true y motivo, y eso queda en la auditoría."""
    from app.servicios import inferencia

    s = entorno["sesion"]
    cand = _candidato_sintetico(s, "cob")
    metricas = {ACTIVO: {"wape": 15.0, "sesgo_pct": 1.0, "cobertura_p10_p90_conformal": 80.0, "n": 100},
                cand.model_id: {"wape": 13.0, "sesgo_pct": 1.0, "cobertura_p10_p90_conformal": 95.0, "n": 100}}
    ventanas = []

    def evaluar(model_id, desde, hasta, *a, **k):
        ventanas.append((model_id, desde, hasta))
        return dict(metricas[model_id])

    monkeypatch.setattr(inferencia, "evaluar", evaluar)
    url = f"/api/v1/models/{cand.model_id}/activate"
    r = cliente.post(url, json={"aprobado_por": "comite"})
    assert r.status_code == 409 and r.json()["error"]["codigo"] == "activacion_rechazada", r.text
    assert "cobertura" in r.json()["error"]["mensaje"] and "WAPE" not in r.json()["error"]["mensaje"].split(":")[1]
    # ventana por omisión: después del corte (2025-06-30) + 61 días de validación, igual para los dos modelos
    assert ventanas[0][1:] == ventanas[1][1:] and ventanas[0][1] == date(2025, 8, 31)
    assert cliente.get(f"/api/v1/models/{cand.model_id}").json()["estado"] == "rechazado"
    r = cliente.post(url, json={"aprobado_por": "comite", "validacion_desde": "2025-10-01",
                                "validacion_hasta": "2025-10-28"})
    assert r.status_code == 409 and r.json()["error"]["codigo"] == "requiere_forzar"       # no se prueban ventanas
    r = cliente.post(url, params={"forzar": "true"}, json={"aprobado_por": "comite"})
    assert r.status_code == 422 and r.json()["error"]["codigo"] == "motivo_requerido"
    r = cliente.post(url, params={"forzar": "true"}, json={"aprobado_por": "comite", "motivo": "emergencia operativa"})
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["estado"] == "activo" and cuerpo["anterior_model_id"] == ACTIVO
    assert cuerpo["metricas"]["validacion_activacion"]["forzada"] is True
    eventos = [e["evento"] for e in cuerpo["auditoria"]]
    assert "activacion_forzada" in eventos and eventos[-1] == "activado"
    forzada = next(e for e in cuerpo["auditoria"] if e["evento"] == "activacion_forzada")
    assert forzada["motivo"] == "emergencia operativa"
    assert any("cobertura" in c for c in forzada["criterios_no_cumplidos"])
    # vuelve el activo real (y la reversión queda auditada)
    r = cliente.post("/api/v1/models/rollback", json={"usuario": "comite", "motivo": "fin de la prueba"})
    assert r.status_code == 200 and r.json()["model_id"] == ACTIVO


def test_foto_que_falla_no_tumba_el_ciclo_y_queda_en_las_metricas(primera, entorno, monkeypatch):
    """§11.2: si la foto de variables falla, se deshace solo su punto de guardado, la sesión sigue usable y las métricas
    de la ejecución lo dicen (advertencias y feature_snapshot_estado = «fallo»)."""
    from app.servicios import monitoreo

    s = entorno["sesion"]
    eid = uuid.UUID(primera["execution_id"])
    antes = s.scalar(select(text("count(*)")).select_from(FotoVariables).where(FotoVariables.execution_id == eid))

    def falla(_p):
        raise RuntimeError("disco lleno (simulado)")

    monkeypatch.setattr(monitoreo, "filas_snapshot", falla)
    fallos: list = []
    out = monitoreo.cerrar_ciclo(s, eid, None, 1, {}, {}, None, fallos)
    assert out["feature_snapshot_filas"] == 0 and out["feature_snapshot_estado"] == "fallo"
    assert "disco lleno" in out["advertencias"][0] and fallos[0]["etapa"] == "feature_snapshot"
    despues = s.scalar(select(text("count(*)")).select_from(FotoVariables).where(FotoVariables.execution_id == eid))
    assert despues == antes      # la sesión sigue usable y la foto anterior no se tocó
    s.rollback()


def test_activacion_manual_no_salta_la_sombra(cliente, entorno, monkeypatch):
    from app.servicios import inferencia

    s = entorno["sesion"]
    cand = _candidato_sintetico(s, "sombra", metricas={"sombra": {"estado": "en_sombra", "inicio": "2025-09-01",
                                                                  "dias": 14, "datos_hasta": "2025-08-31"}})
    monkeypatch.setattr(inferencia, "evaluar", lambda *a, **k: pytest.fail("no debe evaluar: la sombra no terminó"))
    r = cliente.post(f"/api/v1/models/{cand.model_id}/activate", json={"aprobado_por": "comite"})
    assert r.status_code == 409 and r.json()["error"]["codigo"] == "requiere_forzar"
    assert cliente.get(f"/api/v1/models/{cand.model_id}").json()["estado"] == "candidato"
