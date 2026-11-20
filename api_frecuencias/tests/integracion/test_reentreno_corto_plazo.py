"""Reentrenamiento controlado del corto plazo (spec v1.5 RF-018c, §9.5-e, §9.5-j, §14.2 «Incremental 3»).

La política decide con la periodicidad, la degradación, la deriva y la cobertura, no encola con un entrenamiento
pendiente o un retador en sombra ni con un corte que no agrega días; el trabajo «entrenamiento» con familia=corto_plazo
entrena con el histórico validado, publica los 18 artefactos con su SHA-256, registra la candidata sin pisar la activa
y la deja en sombra; la compuerta de cuatro criterios decide al completarse la ventana. Para que la prueba dure
segundos, el entrenamiento usa árboles mínimos y una sola ruta (la mecánica es la misma; el modelo no se usa para nada
más)."""
from __future__ import annotations

import uuid
from datetime import date
from types import SimpleNamespace

import pytest
from sqlalchemy import delete, select

pytestmark = pytest.mark.integracion


def _ciclo_falso(umbrales: dict | None = None) -> SimpleNamespace:
    return SimpleNamespace(umbrales=umbrales or {}, version_u=None, execution_id=uuid.uuid4(), fallos=[])


def _borrar_entrenamientos(sesion) -> None:
    from app.modelos_db import Ejecucion

    sesion.rollback()
    sesion.execute(delete(Ejecucion).where(Ejecucion.tipo == "entrenamiento",
                                           Ejecucion.parametros["familia"].astext == "corto_plazo"))
    sesion.commit()


def test_la_politica_del_corto_plazo_decide_bloquea_y_encola(cliente, sesion, monkeypatch):
    """Periodicidad: el activo de E14 vio hasta el 30-06-2025. Al 31-08 ya hay 62 días nuevos, pero el corte (01-07)
    no agrega 28 días de entrenamiento: no se encola. Al 30-11, el corte 30-09 sí: se encola un trabajo
    «entrenamiento» con familia=corto_plazo (hasta = corte, datos_hasta = la fecha leída), que bloquea un segundo
    pedido y no bloquea al modelo horario. Con REENTRENO_CORTO_PLAZO_EN_CICLO=false o reentreno_en_ciclo = 0 no se
    encola. GET /monitoring/policy muestra la misma decisión."""
    from app.servicios import politica
    from app.servicios import reentreno_corto_plazo as R

    _borrar_entrenamientos(sesion)
    try:
        dec = R.decidir(sesion, {}, date(2025, 8, 31))
        assert dec["modelo_activo"] == "cp_lgbm_20250630_s42" and str(dec["ultimo_dato_visto"]) == "2025-06-30"
        assert any(m.startswith("periodicidad: 62 días") for m in dec["motivos"])
        assert not dec["reentrenar"] and any("no agrega 28 días" in b for b in dec["bloqueos"])
        dec = R.decidir(sesion, {}, date(2025, 11, 30))
        assert dec["reentrenar"] and dec["hasta"] == "2025-09-30" and dec["datos_hasta"] == "2025-11-30"
        c = _ciclo_falso()
        monkeypatch.setenv(R.ENV_EN_CICLO, "false")
        out = R.despues_del_ciclo(sesion, c, {"hasta": "2025-11-30"})
        assert "entrenamiento_encolado" not in out and "false" in out["reentreno"]["nota"]
        out = R.despues_del_ciclo(sesion, _ciclo_falso({"reentreno_en_ciclo": 0}), {"hasta": "2025-11-30"})
        assert "entrenamiento_encolado" not in out and "reentreno_en_ciclo = 0" in out["reentreno"]["nota"]
        monkeypatch.setenv(R.ENV_EN_CICLO, "true")
        out = R.despues_del_ciclo(sesion, c, {"hasta": "2025-11-30"})
        assert out["entrenamiento_encolado"] is not None and c.fallos == []
        sesion.commit()
        from app.modelos_db import Ejecucion

        e = sesion.get(Ejecucion, out["entrenamiento_encolado"])
        assert e.tipo == "entrenamiento" and e.estado == "en_cola"
        assert e.parametros["familia"] == "corto_plazo" and e.parametros["hasta"] == "2025-09-30"
        assert e.parametros["solicitado_por"] == politica.USUARIO_POLITICA
        # un segundo pedido queda bloqueado; el horario no cuenta este trabajo como suyo
        dec = R.decidir(sesion, {}, date(2025, 11, 30))
        assert not dec["reentrenar"] and any("de corto plazo en cola" in b for b in dec["bloqueos"])
        assert not [b for b in politica._bloqueos_reentreno(sesion) if "entrenamiento" in b]
        pol = cliente.get("/api/v1/monitoring/policy").json()
        assert pol["corto_plazo"]["decision"]["familia"] == "corto_plazo" and pol["corto_plazo"]["en_ciclo"]
    finally:
        _borrar_entrenamientos(sesion)


def test_post_models_train_con_familia_corto_plazo_encola_su_trabajo(cliente, sesion, monkeypatch):
    """RF-018c también a mano: POST /models/train con familia=corto_plazo crea el trabajo de la cola (202)."""
    from app.modelos_db import Ejecucion
    from app.servicios import ejecucion

    monkeypatch.setattr(ejecucion, "ejecutar", lambda *a, **k: None)
    try:
        r = cliente.post("/api/v1/models/train", json={"hasta": "2025-09-30", "familia": "corto_plazo"})
        assert r.status_code == 202, r.text
        sesion.expire_all()
        e = sesion.get(Ejecucion, uuid.UUID(r.json()["execution_id"]))
        assert e.tipo == "entrenamiento" and e.parametros["familia"] == "corto_plazo"
        assert cliente.post("/api/v1/models/train", json={"hasta": "2025-09-30", "familia": "otra"}).status_code == 422
    finally:
        _borrar_entrenamientos(sesion)


@pytest.fixture
def modelos_temporales(tmp_path, monkeypatch):
    """Copia temporal de los modelos y una sola ruta, con árboles mínimos (segundos en vez de 15 minutos)."""
    import shutil

    from app.servicios import corto_plazo as cp
    from app.servicios import datos
    from app.servicios import reentreno_corto_plazo as R
    from app.servicios import variables_corto_plazo as V

    copia = tmp_path / "modelos"
    shutil.copytree(datos.carpeta_modelos(), copia, ignore=shutil.ignore_patterns("onnx"))
    monkeypatch.setenv("MODELOS_DIR", str(copia))
    monkeypatch.setattr(V, "RUTAS", {2: "SILENCIO"})

    def rapido(x, y, hiper, semilla):
        import lightgbm as lgb

        return lgb.LGBMRegressor(objective="poisson", n_estimators=4, num_leaves=7, learning_rate=0.3,
                                 random_state=int(semilla), n_jobs=2, verbose=-1, deterministic=True,
                                 force_row_wise=True).fit(x, y)

    monkeypatch.setattr(R, "_ajustar", rapido)
    cp.limpiar_cache()
    yield copia
    monkeypatch.delenv("MODELOS_DIR")
    cp.limpiar_cache()


def test_el_trabajo_entrena_registra_la_candidata_en_sombra_y_la_compuerta_decide(cliente, sesion,
                                                                                modelos_temporales):
    """El trabajo de la cola entrena con el histórico validado hasta datos_hasta (corte 30-09-2025, validación
    01-10..30-11): los artefactos con su SHA-256, la banda ajustada en la validación (ruta, sentido y segmento) y el
    manifiesto con su origen; la candidata entra a model_registry (familia corto_plazo) en sombra del 01-12 al 14-12,
    la activa no cambia y un reintento no vuelve a entrenar. Al leer el 14-12, la compuerta compara a los dos en esa
    ventana con los cuatro criterios: con árboles mínimos la candidata pierde y queda rechazada."""
    from app.modelos_db import Ejecucion, RegistroModelo
    from app.servicios import cola, ejecucion
    from app.servicios import corto_plazo as cp
    from app.servicios import reentreno_corto_plazo as R

    mid = "cp_lgbm_20250930_s42"
    e = ejecucion.crear_ejecucion(sesion, "entrenamiento", {"familia": "corto_plazo", "hasta": "2025-09-30",
                                                             "datos_hasta": "2025-11-30", "solicitado_por": "prueba",
                                                             "motivo": "prueba del reentrenamiento"}, None)
    sesion.commit()
    try:
        assert cola.procesar(e.execution_id) == "ok"
        sesion.expire_all()
        fila = sesion.get(Ejecucion, e.execution_id)
        assert fila.estado == "ok" and fila.model_id == mid and fila.metricas["familia"] == "corto_plazo"
        man = cp.cargar(mid)["manifiesto"]           # SHA-256 de cada artefacto verificado al cargar
        assert man["data_cutoff"] == "2025-09-30" and man["datos_hasta"] == "2025-11-30"
        assert man["periodos"]["validacion"] == ["2025-10-01", "2025-11-30"] and man["metricas_prueba"] is None
        assert len(man["artefactos"]) == 6 and man["origen"]["reentrenamiento"]["base"] == cp.MODEL_ID_E14
        for nivel in ("ruta", "sentido", "segmento"):
            cal = man["banda"]["calibracion"][nivel]["60"]["SILENCIO"]
            assert cal["cortes"] and cal["q"]
        assert cp.registro()["activo"] == cp.MODEL_ID_E14 and cp.registro()["modelos"][mid]["estado"] == "candidato"
        reg = sesion.scalar(select(RegistroModelo).where(RegistroModelo.model_id == mid))
        assert reg.familia == "corto_plazo" and reg.estado == "candidato"
        sombra = reg.metricas["sombra"]
        assert sombra["estado"] == "en_sombra" and sombra["inicio"] == "2025-12-01" and sombra["fin"] == "2025-12-14"
        assert ejecucion.modelo_activo(sesion, "corto_plazo").model_id == cp.MODEL_ID_E14
        # la versión nueva pronostica (con sus artefactos y su banda)
        with cp.con_sesion(sesion):
            r = cp.pronosticar(2, __import__("datetime").datetime.fromisoformat("2025-12-05T07:00:00-05:00"), 60,
                               model_id=mid, incluir_segmentos=False)
        assert r["model_id"] == mid and r["p10"] <= r["pasajeros"] <= r["p90"]
        # un reintento no vuelve a entrenar
        assert R.preparar(sesion, date(2025, 9, 30), date(2025, 11, 30)).get("previo") is not None
        # antes del fin de la ventana sigue en sombra; al leer el 14-12 la compuerta decide
        assert R.revisar_sombra(sesion, date(2025, 12, 10), {}, None)[0]["estado"] == "en_sombra"
        decision = R.revisar_sombra(sesion, date(2025, 12, 14), {}, None)[0]
        assert decision["estado"] == "rechazado" and len(decision["criterios"]) == 4
        assert decision["activo"] == cp.MODEL_ID_E14
        sesion.flush()
        assert reg.estado == "rechazado" and "compuerta de sombra no aprobada" in reg.motivo
        assert ejecucion.modelo_activo(sesion, "corto_plazo").model_id == cp.MODEL_ID_E14
    finally:
        sesion.rollback()
        sesion.execute(delete(RegistroModelo).where(RegistroModelo.model_id == mid))
        sesion.execute(delete(Ejecucion).where(Ejecucion.execution_id == e.execution_id))
        sesion.commit()


def test_un_corte_sin_historia_suficiente_falla_sin_reintentar(cliente, sesion, modelos_temporales):
    """ErrorReentreno (no reintentable): un corte con menos de 180 días de historia después del arranque."""
    from app.modelos_db import Ejecucion
    from app.servicios import cola, ejecucion

    e = ejecucion.crear_ejecucion(sesion, "entrenamiento", {"familia": "corto_plazo", "hasta": "2023-05-01"}, None)
    sesion.commit()
    try:
        assert cola.procesar(e.execution_id) == "error"
        sesion.expire_all()
        fila = sesion.get(Ejecucion, e.execution_id)
        assert "180 días de historia" in (fila.mensaje or "") and fila.intentos == 1
    finally:
        sesion.rollback()
        sesion.execute(delete(Ejecucion).where(Ejecucion.execution_id == e.execution_id))
        sesion.commit()


def test_el_reentrenamiento_es_reproducible(modelos_temporales, tmp_path):
    """§14.2 «Incremental 3»: con la misma serie validada, el mismo corte y la misma semilla, dos entrenamientos dan
    los mismos artefactos (el mismo SHA-256) y la misma banda."""
    from app.servicios import corto_plazo as cp
    from app.servicios import reentreno_corto_plazo as R

    base = cp.cargar(cp.MODEL_ID_E14)["manifiesto"]
    r = cp.serie(2)
    huellas, bandas = [], []
    for k in (1, 2):
        carpeta = tmp_path / f"corrida{k}"
        carpeta.mkdir()
        ent = R._Entrenamiento(base, date(2025, 9, 30), date(2025, 11, 30), 42, carpeta, None)
        ent.ruta(r)
        huellas.append({c: a["sha256"] for c, a in ent.artefactos.items()})
        bandas.append(ent.banda)
    assert len(huellas[0]) == 6 and huellas[0] == huellas[1] and bandas[0] == bandas[1]


def test_la_banda_conformal_cubre_lo_que_promete():
    """La banda P10-P90 conformal por tramo (la de E14) cubre ~80 % en datos de Poisson."""
    import numpy as np

    from app.servicios import reentreno_corto_plazo as R
    from app.servicios import variables_corto_plazo as V

    rng = np.random.default_rng(0)
    p = rng.uniform(1, 400, 40_000)
    y = rng.poisson(p)
    cal = R.conformal_ajustar(y[:20_000], p[:20_000])
    lo, hi = V.conformal_aplicar(p[20_000:], cal)
    cobertura = float(((lo <= y[20_000:]) & (y[20_000:] <= hi)).mean())
    assert len(cal["cortes"]) == 3 and 0.77 <= cobertura <= 0.83
    assert R.model_id_de(date(2025, 9, 30)) == "cp_lgbm_20250930_s42"
