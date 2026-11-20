"""Integración: el pronóstico de corto plazo por la API (RF-005, RF-006, RF-016, RF-017, §9.2, §12.3) contra
PostgreSQL: POST lo guarda (ruta, sentidos y segmentos) con su versión, banda, líneas base y recomendación; GET lo
consulta y lo exporta; /calcular y /dia lo calculan sin guardar; /modelo da la versión con su prueba reservada; los
errores son los declarados y el ciclo lo genera con su execution_id. Borra lo que escribe."""
from __future__ import annotations

import pytest
from sqlalchemy import delete, func, select

from app.modelos_db import PrediccionCortoPlazo

pytestmark = pytest.mark.integracion
RUTA = "/api/v1/predictions/corto-plazo"
PEDIDO = {"ruta": "CRA 54", "instante": "2025-07-07T07:10:00-05:00", "horizonte_min": 60}


@pytest.fixture
def limpio(sesion):
    grupos: list = []
    yield grupos
    sesion.rollback()
    if grupos:
        sesion.execute(delete(PrediccionCortoPlazo).where(PrediccionCortoPlazo.grupo_id.in_(grupos)))
        sesion.commit()


def test_post_guarda_la_ruta_sus_sentidos_y_sus_segmentos(cliente, sesion, limpio):
    r = cliente.post(RUTA, json=PEDIDO)
    assert r.status_code == 201, r.text
    d = r.json()
    limpio.append(d["grupo_id"])
    assert d["instante"].startswith("2025-07-07T07:00:00-05:00") and d["horizonte_min"] == 60
    assert d["model_id"] == "cp_lgbm_20250630_s42" and d["feature_version"] and d["data_cutoff"] == "2025-06-30"
    assert d["p10"] <= d["pasajeros"] <= d["p90"] and d["promedio_dia_hora"] is not None and d["real"] is not None
    assert len(d["sentidos"]) == 2 and len(d["segmentos"]) == 123 and len(d["explicacion"]["factores"]) == 5
    # §12.3: las claves del ejemplo de la especificación
    assert d["predictionId"] == d["grupo_id"] and d["routeId"] == "CRA 54" and d["horizonMinutes"] == 60
    assert d["predictedPassengers"] == round(d["pasajeros"]) and d["modelVersion"] == d["model_id"]
    assert d["confidenceInterval"]["lower"] <= d["predictedPassengers"] <= d["confidenceInterval"]["upper"]
    assert d["explanation"] == [f["variable"] for f in d["explicacion"]["factores"]]
    assert d["recomendacion"]["hora"] == 7 and d["recommendation"]["viable"] in (True, False)
    filas = sesion.scalars(select(PrediccionCortoPlazo).where(PrediccionCortoPlazo.grupo_id == d["grupo_id"])).all()
    assert len(filas) == 1 + 2 + 123
    por_nivel = {n: [f for f in filas if f.nivel == n] for n in ("ruta", "sentido", "segmento")}
    ruta = por_nivel["ruta"][0]
    assert ruta.pasajeros == pytest.approx(d["pasajeros"]) and ruta.model_id == d["model_id"]
    assert ruta.latencia_ms is not None and ruta.generated_at is not None and ruta.explicacion["factores"]
    assert ruta.recomendacion is not None and ruta.execution_id is None
    assert {f.sentido for f in por_nivel["sentido"]} == {"ida", "regreso"}
    assert sorted(f.nro_segmento for f in por_nivel["segmento"]) == list(range(1, 124))
    # la recomendación de §10.2 también queda en recommendation, ligada a la fila de la ruta
    from app.modelos_db import Recomendacion

    rec = sesion.scalars(select(Recomendacion)
                         .where(Recomendacion.prediction_corto_plazo_id == ruta.prediction_id)).one()
    assert rec.origen == "corto_plazo" and rec.hora == d["recomendacion"]["hora"]
    sesion.delete(rec)
    sesion.commit()


def test_consulta_filtra_y_exporta(cliente, limpio):
    d = cliente.post(RUTA, json=PEDIDO | {"horizonte_min": 30, "incluir_recomendacion": False}).json()
    limpio.append(d["grupo_id"])
    assert d["recomendacion"] is None and d["recommendation"] is None
    base = {"grupo_id": d["grupo_id"]}
    assert cliente.get(RUTA, params=base).json()["total"] == 126
    sen = cliente.get(RUTA, params=base | {"nivel": "sentido"}).json()
    assert sen["total"] == 2 and {x["sentido"] for x in sen["items"]} == {"ida", "regreso"}
    seg = cliente.get(RUTA, params=base | {"nivel": "segmento", "nro_segmento": 5}).json()
    assert seg["total"] == 1 and seg["items"][0]["nro_segmento"] == 5
    filtros = {"ruta": "CRA 54", "idruta": 16, "horizonte_min": 30, "desde": "2025-07-07", "hasta": "2025-07-07",
               "nivel": "ruta", "model_id": d["model_id"]}
    assert cliente.get(RUTA, params=filtros).json()["total"] >= 1
    csv = cliente.get(f"{RUTA}/export", params=base | {"formato": "csv"})
    assert csv.status_code == 200 and csv.headers["X-Total-Count"] == "126" and "nivel" in csv.text.splitlines()[0]


def test_calcular_dia_y_modelo_no_guardan(cliente, sesion):
    antes = sesion.scalar(select(func.count()).select_from(PrediccionCortoPlazo))
    c = cliente.get(f"{RUTA}/calcular", params=PEDIDO | {"incluir_segmentos": False})
    assert c.status_code == 200, c.text
    assert c.json()["grupo_id"] is None and c.json()["segmentos"] == [] and c.json()["recommendation"] is not None
    dia = cliente.get(f"{RUTA}/dia", params={"ruta": "CRA 54", "fecha": "2025-07-07", "horizonte_min": 60})
    assert dia.status_code == 200 and len(dia.json()["instantes"]) == 35
    m = cliente.get(f"{RUTA}/modelo").json()
    assert m["model_id"] == m["activo"] == "cp_lgbm_20250630_s42" and len(m["sha256"]) == 18
    r60 = m["metricas_prueba"]["ruta"]["60"]
    assert r60["wape_modelo"] < r60["wape_promedio_dia_hora"]
    assert m["cobertura"]["fuera_de_muestra_desde"] == "2025-07-01"
    assert sesion.scalar(select(func.count()).select_from(PrediccionCortoPlazo)) == antes


def test_errores_declarados(cliente, monkeypatch):
    from app.servicios import corto_plazo as cp

    r = cliente.get(f"{RUTA}/calcular", params=PEDIDO | {"horizonte_min": 45})
    assert r.status_code == 422 and r.json()["error"]["codigo"] == "horizonte_invalido"
    r = cliente.post(RUTA, json=PEDIDO | {"horizonte_min": 45})
    assert r.status_code == 422 and r.json()["error"]["codigo"] == "validacion"
    r = cliente.get(f"{RUTA}/calcular", params=PEDIDO | {"instante": "2025-07-07T03:00:00-05:00"})
    assert r.status_code == 422 and r.json()["error"]["codigo"] == "fuera_de_cobertura"
    r = cliente.get(f"{RUTA}/dia", params={"ruta": "CRA 54", "fecha": "2023-01-05", "horizonte_min": 60})
    assert r.status_code == 422 and r.json()["error"]["codigo"] == "fuera_de_cobertura"
    r = cliente.post(RUTA, json=PEDIDO | {"ruta": "RUTA X"})
    assert r.status_code == 404 and r.json()["error"]["codigo"] == "ruta_desconocida"
    r = cliente.get(f"{RUTA}/calcular", params=PEDIDO | {"model_id": "no_existe"})
    assert r.status_code == 404 and r.json()["error"]["codigo"] == "modelo_no_encontrado"

    def alterado(*_a, **_k):
        raise cp.ErrorCortoPlazo("el artefacto no coincide con el SHA-256 (simulado)")

    monkeypatch.setattr(cp, "cargar", alterado)
    for metodo, url in (("get", f"{RUTA}/calcular"), ("get", f"{RUTA}/modelo")):
        r = getattr(cliente, metodo)(url, params=PEDIDO)
        assert r.status_code == 503 and r.json()["error"]["codigo"] == "pronostico_no_disponible"


def test_roles(cliente, claves_prueba, limpio, monkeypatch):
    from app.config import obtener_ajustes

    monkeypatch.setattr(obtener_ajustes(), "auth_habilitada", True)
    operador = {"X-API-Key": claves_prueba["operador"]}
    assert cliente.post(RUTA, json=PEDIDO, headers=operador).status_code == 403
    assert cliente.get(f"{RUTA}/calcular", params=PEDIDO, headers=operador).status_code == 200
    r = cliente.post(RUTA, json=PEDIDO, headers={"X-API-Key": claves_prueba["analista"]})
    assert r.status_code == 201
    limpio.append(r.json()["grupo_id"])


BOGOTA_ZONA = "America/Bogota"


@pytest.fixture
def ejecucion_de_prueba(sesion):
    """Una ejecución real (las tablas del ciclo la citan por llave foránea); lo demás se deshace con rollback."""
    from app.modelos_db import Ejecucion
    from app.servicios import corto_plazo as cp
    from app.servicios import ejecucion

    e = ejecucion.crear_ejecucion(sesion, "frecuencia", {"prueba": "corto_plazo"}, None)
    cp.limpiar_cache()
    yield e.execution_id
    sesion.rollback()
    sesion.execute(delete(Ejecucion).where(Ejecucion.execution_id == e.execution_id))
    sesion.commit()
    cp.limpiar_cache()


def _ciclo(execution_id, validos, marca, fuente=None, instante=None):
    from app.servicios import ejecucion

    p = {"instante": instante.isoformat()} if instante else {}
    return ejecucion._Ciclo(execution_id=execution_id, p=p, fuente=fuente or object(), df=validos, validos=validos,
                            errores=[], marca_anterior=None, marca_nueva=marca, filas_leidas=len(validos),
                            filas_validas=len(validos), version_u=None, umbrales={}, model_id=None, metricas={})


def test_el_ciclo_lee_los_bloques_de_15_minutos_y_pronostica_con_lo_leido(sesion, ejecucion_de_prueba):
    """RF-013 y §7.3 pasos 2 a 7 en modo Parquet: los días que trajo la lectura horaria se leen del panel en bloques
    de 15 minutos y lectura_15min dice hasta dónde se leyó cada uno; sus celdas no se copian a subidas_15min (ya están
    empaquetadas), la celda imposible del 05-07-2025 queda en data_quality_error (VAL-009) y la serie que se sirve no
    la usa, y el pronóstico del día siguiente a las 04:00 usa solo lo leído: se guarda con el execution_id, con su
    recomendación (origen corto_plazo, ligada a la fila de la ruta)."""
    from datetime import date, datetime
    from zoneinfo import ZoneInfo

    import pandas as pd

    from app.modelos_db import ErrorCalidad, Lectura15Min, Recomendacion, Subidas15Min
    from app.servicios import corto_plazo as cp
    from app.servicios import ejecucion

    z = ZoneInfo(BOGOTA_ZONA)
    validos = pd.DataFrame({"ruta": ["SILENCIO", "CRA 54"], "fecha": [date(2025, 7, 4), date(2025, 7, 5)]})
    c = _ciclo(ejecucion_de_prueba, validos, datetime(2025, 7, 5, 23, 59, 59, tzinfo=z))
    ejecucion._leer_corto_plazo(sesion, c)
    leido = c.metricas["lectura_corto_plazo"]
    assert c.fallos == [] and leido["fuente"] == "panel_empaquetado" and leido["dias"] == 2 and leido["excluidas"] == 1
    lecturas = {(x.idruta, x.fecha): x for x in sesion.scalars(select(Lectura15Min)).all()}
    assert lecturas[(16, date(2025, 7, 5))].excluidas == 1 and lecturas[(2, date(2025, 7, 4))].celdas > 100
    # un día del panel no se copia a la base (ya está empaquetado); la serie servida excluye la celda imposible
    assert leido["guardadas"] == 0 and not sesion.scalar(select(func.count()).select_from(Subidas15Min).where(
        Subidas15Min.fecha.in_([date(2025, 7, 4), date(2025, 7, 5)])))
    with cp.con_sesion(sesion):
        servida = cp.serie(16)
    assert servida.y[cp.dia_de_fecha(date(2025, 7, 5))].max() <= 1000
    error = sesion.scalars(select(ErrorCalidad).where(ErrorCalidad.execution_id == ejecucion_de_prueba)).one()
    assert error.codigo == "VAL-009" and error.llave == {"idruta": 16, "fecha": "2025-07-05", "bloque": 31,
                                                         "nro_segmento": 4} and error.bloqueante
    catalogo = ejecucion._info_de_las_rutas()
    recomendador = ejecucion._RecomendacionesDeLaEjecucion({}, None)
    ejecucion._pronostico_corto_plazo(sesion, c, ["SILENCIO", "CRA 54"], datetime(2025, 7, 6, 6, tzinfo=z),
                                      catalogo, recomendador, [])
    cp_m = c.metricas["corto_plazo"]
    assert c.fallos == [] and cp_m["pronosticos"] == 6 and cp_m["recomendaciones"] == 6
    assert cp_m["instante"].startswith("2025-07-06T04:00") and cp_m["datos_hasta"].startswith("2025-07-05T23:59:59")
    sesion.flush()
    filas = sesion.scalars(select(PrediccionCortoPlazo).where(PrediccionCortoPlazo.execution_id
                                                              == ejecucion_de_prueba)).all()
    rutas = [f for f in filas if f.nivel == "ruta"]
    assert len(rutas) == 6 and all(f.variables["datos_hasta"].startswith("2025-07-05T23:59:59") for f in rutas)
    assert all(f.idproceso is not None or f.id_dia_semana is not None for f in rutas)
    assert {f.id_segmento for f in filas if f.nivel == "segmento"} - {None}
    recs = sesion.scalars(select(Recomendacion).where(Recomendacion.execution_id == ejecucion_de_prueba)).all()
    assert len(recs) == 6 and {r.origen for r in recs} == {"corto_plazo"}
    assert {r.prediction_corto_plazo_id for r in recs} == {f.prediction_id for f in rutas}


def test_en_un_ciclo_intradia_el_corto_plazo_alimenta_las_alertas_de_pronostico(sesion, ejecucion_de_prueba):
    """§7.3 paso 7 y §11.2 (alertas de pronóstico con la recomendación de la franja): en un ciclo intradía, cada
    pronóstico de corto plazo deja el contexto de sus alertas (demanda por hora, capacidad de la recomendación y las
    variables influyentes del TreeSHAP del modelo) y alertas.evaluar_pronostico lo convierte en alertas de pronóstico.
    CRA 54 el miércoles 19-11-2025 a las 07:00, con lo leído hasta las 07:04: la demanda de la hora pico supera lo que
    da la flota (la recomendación sale no viable), y eso es una alerta de pronóstico."""
    from datetime import date, datetime
    from zoneinfo import ZoneInfo

    import pandas as pd

    from app.servicios import alertas, ejecucion

    z = ZoneInfo(BOGOTA_ZONA)
    instante = datetime(2025, 11, 19, 7, 0, tzinfo=z)
    validos = pd.DataFrame({"ruta": ["CRA 54"], "fecha": [date(2025, 11, 19)]})
    c = _ciclo(ejecucion_de_prueba, validos, datetime(2025, 11, 19, 7, 4, tzinfo=z), instante=instante)
    c.p["intradia"] = True
    contextos: list[dict] = []
    ejecucion._pronostico_corto_plazo(sesion, c, ["CRA 54"], instante, ejecucion._info_de_las_rutas(),
                                      ejecucion._RecomendacionesDeLaEjecucion({}, None), contextos)
    m = c.metricas["corto_plazo"]
    assert c.fallos == [] and m["pronosticos"] == 3 and m["contextos_alerta"] == 3 and len(contextos) == 3
    assert all(x["variables_influyentes"] and {v["fuente"] for v in x["variables_influyentes"]}
               == {"shap_modelo_corto_plazo"} for x in contextos)
    emitidas = alertas.evaluar_pronostico(contextos, alertas._umbrales({}))
    assert emitidas and {a["codigo"] for a in emitidas} <= {"ALT-001", "ALT-002", "ALT-003", "ALT-004"}
    assert all(a["ruta"] == "CRA 54" for a in emitidas)


def test_un_dia_nuevo_leido_de_la_fuente_se_pronostica_hasta_donde_se_leyo(sesion, ejecucion_de_prueba):
    """En modo integrado los bloques salen de timbradas_segmentos (aquí, una fuente de prueba con lo del miércoles
    17-12-2025 pasado al 1-1-2026): un día posterior al panel se pronostica hasta donde se leyó, no más allá, y el día
    siguiente solo cuando el anterior se leyó completo."""
    from datetime import date, datetime, timedelta
    from zoneinfo import ZoneInfo

    import pandas as pd

    from app.servicios import corto_plazo as cp
    from app.servicios import ejecucion
    from app.servicios import panel_corto_plazo as P

    z = ZoneInfo(BOGOTA_ZONA)
    nuevo = date(2026, 1, 1)

    class FuenteDePrueba:
        def leer_panel_15min(self, idruta, segmentos, fechas, hasta):
            sub, sal = P.del_panel(idruta, [nuevo - timedelta(days=15)])
            seg = P.segmentos(idruta)
            ids = dict(zip(seg["nro_segmento"], seg["id_segmento"], strict=True))
            sub = sub.assign(fecha=nuevo, id_segmento=sub["nro_segmento"].map(ids))
            corte = (hasta.hour * 60 + hasta.minute) // 15
            return sub[sub["bloque"] < corte], sal.assign(fecha=nuevo)[sal["bloque"] < corte]

    validos = pd.DataFrame({"ruta": ["SILENCIO"], "fecha": [nuevo]})
    c = _ciclo(ejecucion_de_prueba, validos, datetime(2026, 1, 1, 9, 4, tzinfo=z), FuenteDePrueba())
    ejecucion._leer_corto_plazo(sesion, c)
    leido = c.metricas["lectura_corto_plazo"]
    # un día posterior al panel sí queda en subidas_15min: es lo que el panel empaquetado no tiene
    assert c.fallos == [] and leido["fuente"] == "timbradas_segmentos" and leido["guardadas"] == leido["celdas"] > 0
    with cp.con_sesion(sesion):
        r = cp.pronosticar("SILENCIO", datetime(2026, 1, 1, 9, 0, tzinfo=z), 30, incluir_segmentos=False)
        assert r["datos_hasta"].startswith("2026-01-01T09:04") and r["real"] is None
        assert r["observado"]["acumulado_hoy"] > 0
        with pytest.raises(cp.FueraDeCobertura):
            cp.pronosticar("SILENCIO", datetime(2026, 1, 1, 9, 30, tzinfo=z), 30)
        with pytest.raises(cp.FueraDeCobertura):
            cp.pronosticar("SILENCIO", datetime(2026, 1, 2, 4, 0, tzinfo=z), 30)
        assert cp.cobertura()["leido_hasta"].startswith("2026-01-01T09:04")
    # el resto del día llega: el día siguiente se puede pronosticar desde su primer instante
    c = _ciclo(ejecucion_de_prueba, validos, datetime(2026, 1, 1, 23, 59, 59, tzinfo=z), FuenteDePrueba())
    ejecucion._leer_corto_plazo(sesion, c)
    with cp.con_sesion(sesion):
        r = cp.pronosticar("SILENCIO", datetime(2026, 1, 2, 4, 0, tzinfo=z), 60, incluir_segmentos=False)
    assert r["p10"] <= r["pasajeros"] <= r["p90"] and r["real"] is None
    # sin la sesión (solo el panel empaquetado), 2026 sigue fuera de la cobertura
    with pytest.raises(cp.FueraDeCobertura):
        cp.pronosticar("SILENCIO", datetime(2026, 1, 1, 9, 0, tzinfo=z), 30)


def test_ciclo_de_vida_del_corto_plazo_registro_compuerta_activacion_y_reversion(cliente, sesion, tmp_path,
                                                                                monkeypatch):
    """RF-018, RF-019 y §9.2: el modelo de corto plazo es la familia corto_plazo de model_registry (un activo por
    familia). Una versión nueva del registro de artefactos entra como candidata; POST /models/{id}/activate aplica la
    compuerta de cuatro criterios en una ventana posterior a su fecha de corte (422 si empieza dentro de la muestra),
    la activa sin tocar el activo horario, y POST /models/rollback con familia=corto_plazo vuelve a la anterior. Usa
    una copia temporal de los modelos (un clon del activo con otro model_id)."""
    import json
    import shutil

    from app.modelos_db import RegistroModelo
    from app.servicios import corto_plazo as cp
    from app.servicios import datos, ejecucion

    copia = tmp_path / "modelos"
    shutil.copytree(datos.carpeta_modelos(), copia)
    clon = "cp_lgbm_20250630_s43"
    shutil.copytree(copia / "corto_plazo" / cp.MODEL_ID_E14, copia / "corto_plazo" / clon)
    monkeypatch.setenv("MODELOS_DIR", str(copia))
    cp.limpiar_cache()
    man = json.loads((copia / "corto_plazo" / clon / cp.ARCHIVO_MANIFIESTO).read_text(encoding="utf-8"))
    man["model_id"] = clon
    (copia / "corto_plazo" / clon / cp.ARCHIVO_MANIFIESTO).write_text(json.dumps(man), encoding="utf-8")
    cp.registrar(man, activar=False, motivo="clon de prueba")
    horario = ejecucion.modelo_activo(sesion, "horario")
    try:
        lista = cliente.get("/api/v1/models", params={"familia": "corto_plazo"}).json()
        por_id = {m["model_id"]: m for m in lista["items"]}
        assert por_id[cp.MODEL_ID_E14]["estado"] == "activo" and por_id[clon]["estado"] == "candidato"
        assert {m["familia"] for m in lista["items"]} == {"corto_plazo"} and len(por_id[clon]["sha256"]) == 64
        imp = cliente.get(f"/api/v1/models/{clon}/importance").json()
        assert imp["por_nivel"]["ruta"]["60"][0]["variable"] == "p15"
        ev = cliente.get(f"/api/v1/models/{clon}/evaluation",
                         params={"desde": "2025-07-01", "hasta": "2025-07-02"}).json()
        assert ev["ventana"]["dias"] == 2 and 0 < ev["ventana"]["wape"] < 20
        r = cliente.post(f"/api/v1/models/{clon}/activate", json={"aprobado_por": "prueba", "motivo": "prueba",
                                                                 "validacion_desde": "2025-06-20",
                                                                 "validacion_hasta": "2025-06-22"})
        assert r.status_code == 422 and r.json()["error"]["codigo"] == "ventana_en_muestra"
        r = cliente.post(f"/api/v1/models/{clon}/activate", json={"aprobado_por": "prueba", "motivo": "prueba",
                                                                 "validacion_desde": "2025-07-01",
                                                                 "validacion_hasta": "2025-07-02"})
        assert r.status_code == 200, r.text
        assert r.json()["estado"] == "activo" and r.json()["anterior_model_id"] == cp.MODEL_ID_E14
        comparacion = r.json()["metricas"]["validacion_activacion"]
        assert comparacion["compuerta"]["aprobado"] and len(comparacion["compuerta"]["criterios"]) == 4
        sesion.expire_all()
        assert ejecucion.modelo_activo(sesion, "corto_plazo").model_id == clon
        assert ejecucion.modelo_activo(sesion, "horario").model_id == (horario.model_id if horario else None)
        # el pronóstico usa el activo de la familia
        c = cliente.get(f"{RUTA}/calcular", params=PEDIDO | {"incluir_segmentos": False}).json()
        assert c["model_id"] == clon
        r = cliente.post("/api/v1/models/rollback", json={"usuario": "prueba", "motivo": "prueba",
                                                          "familia": "corto_plazo"})
        assert r.status_code == 200, r.text
        assert r.json()["model_id"] == cp.MODEL_ID_E14 and r.json()["estado"] == "activo"
        sesion.expire_all()
        assert ejecucion.modelo_activo(sesion, "horario").model_id == (horario.model_id if horario else None)
    finally:
        sesion.rollback()
        sesion.execute(delete(RegistroModelo).where(RegistroModelo.model_id == clon))
        e14 = sesion.scalar(select(RegistroModelo).where(RegistroModelo.model_id == cp.MODEL_ID_E14))
        if e14 is not None:
            e14.estado = "activo"
        sesion.commit()
        monkeypatch.delenv("MODELOS_DIR")
        cp.limpiar_cache()


def test_el_monitoreo_del_corto_plazo_queda_en_model_monitoring(cliente, sesion, ejecucion_de_prueba):
    """§9.4 y §9.5 para el corto plazo: con lo leído hasta la marca del ciclo, el error móvil (WAPE, MAE, sesgo) por
    horizonte y por ruta en los últimos 7 días completos, la cobertura P10-P90, el volumen de pronósticos guardados y
    el PSI de las variables frente a las 4 semanas anteriores al corte del modelo, en model_monitoring con su
    execution_id; ALT-010 se evalúa por ruta con wape_max."""
    from datetime import date, datetime
    from zoneinfo import ZoneInfo

    import pandas as pd

    from app.modelos_db import MonitoreoModelo
    from app.servicios import monitoreo_corto_plazo

    z = ZoneInfo(BOGOTA_ZONA)
    validos = pd.DataFrame({"ruta": ["SILENCIO"], "fecha": [date(2025, 10, 14)]})
    c = _ciclo(ejecucion_de_prueba, validos, datetime(2025, 10, 14, 23, 59, 59, tzinfo=z))
    c.nuevas_alertas, c.repetidas = [], 0
    m = monitoreo_corto_plazo.en_ciclo(sesion, c)
    assert c.fallos == [] and m["hasta"] == date(2025, 10, 14) and m["desde"] == date(2025, 10, 8)
    assert 0 < m["wape_movil"] < 0.2 and 0.6 < m["cobertura_p10_p90"] < 1 and set(m["wape_por_ruta"]) == {
        "SILENCIO", "CRA 54", "CL 72"}
    assert m["estado"] in ("ok", "aviso", "alerta") and m["psi_variable_max"] in monitoreo_corto_plazo.VARIABLES_PSI
    fila = sesion.get(MonitoreoModelo, m["id"])
    assert fila.execution_id == ejecucion_de_prueba and fila.model_id.startswith("cp_")
    assert fila.detalle["familia"] == "corto_plazo" and set(fila.detalle["por_horizonte"]) == {"30", "60", "120"}
    assert set(fila.psi) == set(monitoreo_corto_plazo.VARIABLES_PSI) and fila.ventana_dias == 7
    assert fila.predicciones_ventana >= 0 and m["alt010_nuevas"] == 0     # WAPE de 7-9 %: lejos de wape_max
    sesion.commit()                 # GET /monitoring lo lee con su propia sesión; la ejecución se borra al final
    try:
        cp_api = cliente.get("/api/v1/monitoring", params={"familia": "corto_plazo",
                                                           "execution_id": str(ejecucion_de_prueba)}).json()
        horario = cliente.get("/api/v1/monitoring", params={"familia": "horario",
                                                            "execution_id": str(ejecucion_de_prueba)}).json()
        assert [x["id"] for x in cp_api["items"]] == [m["id"]] and horario["total"] == 0
    finally:
        sesion.delete(sesion.get(MonitoreoModelo, m["id"]))
        sesion.commit()


def test_la_respuesta_del_reto_dice_las_proximas_dos_horas(sesion):
    """§20 «qué situaciones requieren atención inmediata»: GET /respuesta trae, por ruta, el pronóstico de corto plazo
    de 30, 60 y 120 min con su banda, el promedio por día y hora, la recomendación de §10.2 y los 5 segmentos con más
    subidas previstas en la próxima hora."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from app.routers.respuesta import proximas_dos_horas

    d = proximas_dos_horas(sesion, ["CRA 54", "CL 72"], datetime(2025, 10, 15, 7, 10, tzinfo=ZoneInfo(BOGOTA_ZONA)))
    assert d["instante"].startswith("2025-10-15T07:10") and d["origen_instante"] == "pedido"
    assert d["model_id"].startswith("cp_") and [r["ruta"] for r in d["rutas"]] == ["CRA 54", "CL 72"]
    cra = d["rutas"][0]
    assert [h["horizonte_min"] for h in cra["horizontes"]] == [30, 60, 120]
    for h in cra["horizontes"]:
        assert h["p10"] <= h["pasajeros"] <= h["p90"] and h["promedio_dia_hora"] is not None
        assert h["viable"] in (True, False) and len(h["sentidos"]) == 2 and h["explicacion"]
    seg = cra["segmentos_mas_cargados_60_min"]
    assert len(seg) == 5 and seg[0]["pasajeros"] >= seg[-1]["pasajeros"]
    sin_ref = proximas_dos_horas(sesion, ["SILENCIO"], None)
    assert sin_ref["instante"] and sin_ref["origen_instante"].startswith("último día con datos")
