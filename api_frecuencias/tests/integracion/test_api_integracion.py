"""Integración: migraciones, ejecución incremental, deduplicación, alertas, modelos, umbrales y exportaciones."""
from __future__ import annotations

import io
import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import func, inspect, select, text

from app.modelos_db import Alerta, DemandaObservada, Ejecucion, RegistroModelo, Umbral

TABLAS = {"model_registry", "prediction", "recommendation", "alert", "alert_history", "execution_log",
          "data_quality_error", "threshold_config", "notification_log", "demanda_observada", "marca_agua_ruta",
          "segmento_estadistica_dia", "segmento_estadistica", "segmento_estadistica_refresco", "ocupacion_segmento",
          "retencion_registro", "marca_agua_tabla"}


# ---------------------------------------------------------------- migraciones
def test_migracion_crea_esquema_y_siembra_umbrales(migrada, sesion):
    """Independiente del orden: los valores sembrados se leen en el HISTÓRICO (versión 1 de la 0001 y la versión de
    la 0005), no en la versión vigente, que otras pruebas cambian con PUT /thresholds."""
    tablas = set(inspect(sesion.get_bind()).get_table_names(schema="ai_frecuencias"))
    assert TABLAS | {"respuesta_reto"} <= tablas
    filas = sesion.scalars(select(Umbral).where(Umbral.vigente)).all()
    # cada migración que agrega umbrales (0003 alertas, 0004 monitoreo, 0005 pesos de §10.2) crea una versión nueva
    # del conjunto completo: lo que se exige es UNA sola versión vigente, la última
    assert {f.version for f in filas} == {sesion.scalar(select(func.max(Umbral.version)))}
    v1 = {f.nombre: f.valor for f in sesion.scalars(select(Umbral).where(Umbral.version == 1,
                                                                        Umbral.creado_por == "migracion_0001"))}
    assert v1["ocupacion_critica"] == 0.9 and v1["baja_utilizacion"] == 0.3
    assert v1["error_pronostico"] == 0.15 and v1["periodos_atraso"] == 2
    # 0005: α, β, γ, δ, el nivel de servicio y los costos de §10.2 están en threshold_config desde la instalación
    from app.servicios.optimizacion import PARAMETROS_OBJETIVO

    v5 = {f.nombre for f in sesion.scalars(select(Umbral).where(Umbral.creado_por == "migracion_0005"))}
    assert set(PARAMETROS_OBJETIVO) <= v5 and set(PARAMETROS_OBJETIVO) <= {f.nombre for f in filas}
    indices = {i["name"] for i in inspect(sesion.get_bind()).get_indexes("alert", schema="ai_frecuencias")}
    esperados = {"ux_alert_dedup_abiertas", "ix_alert_estado", "ix_alert_viaje_fecha", "ix_alert_idruta_detectada"}
    assert esperados <= indices


def test_migracion_0006_dimensiones_sube_baja_y_rellena(migrada, sesion):
    """0006 (§8.3, §8.1, §6.3, §5.1, §20): al bajar desaparecen sus columnas, restricciones y la tabla respuesta_reto;
    al subir vuelven y las filas que ya existían quedan con idruta, proceso y día ISO del catálogo."""
    import importlib.util

    from tests.integracion.conftest import RAIZ, _alembic

    spec = importlib.util.spec_from_file_location(
        "m0006", RAIZ / "alembic" / "versions" / "0006_dimensiones_calidad_respuesta.py")
    m0006 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m0006)

    def columnas(tabla: str) -> set[str]:
        with sesion.get_bind().connect() as c:
            return set(c.execute(text("SELECT column_name FROM information_schema.columns "
                                      "WHERE table_schema = 'ai_frecuencias' AND table_name = :t"), {"t": tabla})
                       .scalars())

    for tabla, nuevas in m0006.COLUMNAS_0006.items():
        assert set(nuevas) <= columnas(tabla), tabla
    fecha = date(2031, 3, 9)     # domingo fuera de cualquier dato de las demás pruebas
    sesion.commit()
    try:
        _alembic("downgrade", "0005")
        for tabla, nuevas in m0006.COLUMNAS_0006.items():
            assert not set(nuevas) & columnas(tabla), tabla
        assert "respuesta_reto" not in set(inspect(sesion.get_bind()).get_table_names(schema="ai_frecuencias"))
        sesion.execute(text("INSERT INTO ai_frecuencias.demanda_observada (ruta, fecha, hora, pasajeros, salidas) "
                            "VALUES ('CL 72', :f, 6, 100, 5)"), {"f": fecha})
        sesion.commit()
    finally:
        sesion.rollback()
        _alembic("upgrade", "head")
    try:
        fila = sesion.execute(text("SELECT idruta, idproceso, idempresa, id_dia_semana, id_estacionalidad "
                                   "FROM ai_frecuencias.demanda_observada WHERE ruta = 'CL 72' AND fecha = :f"),
                              {"f": fecha}).one()
        assert tuple(fila) == (21, "sobusa", None, 7, None)
        for tabla, nuevas in m0006.COLUMNAS_0006.items():
            assert set(nuevas) <= columnas(tabla), tabla
        tipos = sesion.scalar(text("SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                                   "WHERE conname = 'ck_execution_log_tipo'"))
        assert "respuesta" in tipos
        # §8.1 claves naturales: una recomendación por predicción y una hora del plan por ruta en cada ejecución
        unicos = dict(sesion.execute(text(
            "SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = 'ai_frecuencias' "
            "AND indexname IN ('ux_recommendation_prediccion', 'ux_recommendation_plan_dia', "
            "'ux_respuesta_reto_clave')")).all())
        assert set(unicos) == {"ux_recommendation_prediccion", "ux_recommendation_plan_dia", "ux_respuesta_reto_clave"}
        assert all("UNIQUE" in d for d in unicos.values()) and "plan_dia" in unicos["ux_recommendation_plan_dia"]
        estados = sesion.scalar(text("SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                                     "WHERE conname = 'ck_alert_estado'"))
        assert all(e in estados for e in ("nueva", "reconocida", "asignada", "cerrada", "descartada"))
    finally:
        sesion.rollback()
        sesion.execute(text("DELETE FROM ai_frecuencias.demanda_observada WHERE fecha = :f"), {"f": fecha})
        sesion.commit()


def test_migracion_0005_pesos_objetivo_sube_y_baja(migrada, sesion):
    """La 0005 copia los valores del código; bajarla borra solo sus filas y deja vigente la versión anterior."""
    import importlib.util

    from app.servicios.optimizacion import PARAMETROS_OBJETIVO
    from tests.integracion.conftest import RAIZ, _alembic

    spec = importlib.util.spec_from_file_location("m0005", RAIZ / "alembic" / "versions" / "0005_pesos_objetivo.py")
    m0005 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m0005)
    assert {n: (v, d) for n, v, d in m0005.PESOS_0005} == dict(PARAMETROS_OBJETIVO)   # sin deriva frente al código

    def vigentes():
        # columnas explícitas: al bajar a 0004 la tabla no tiene las columnas que agregan migraciones posteriores
        sesion.expire_all()
        filas = sesion.execute(select(Umbral.nombre, Umbral.version, Umbral.creado_por).where(Umbral.vigente)).all()
        return {f.nombre: f for f in filas}

    def por_migracion():
        return sesion.scalar(select(func.count()).select_from(Umbral).where(Umbral.creado_por == "migracion_0005"))

    sesion.commit()
    try:
        _alembic("downgrade", "0004")
        assert por_migracion() == 0
        antes = vigentes()
        assert antes and len({f.version for f in antes.values()}) == 1
        # sin PUT previo los pesos no quedan vigentes: rige el código, como antes de la 0005
        if all(f.creado_por in ("migracion_0003", "migracion_0004", "migracion_0001") for f in antes.values()):
            assert not set(PARAMETROS_OBJETIVO) & set(antes)
    finally:
        sesion.rollback()     # suelta los bloqueos de lectura: la 0006 altera threshold_config al subir
        _alembic("upgrade", "head")
    despues = vigentes()
    assert set(PARAMETROS_OBJETIVO) <= set(despues) and len({f.version for f in despues.values()}) == 1
    # al volver a head, la última versión del conjunto completo es la de la última migración que versiona umbrales
    # (la 0007, umbrales de las reglas nuevas, o una posterior como la 0010, parámetros del plan)
    creadores = {f.creado_por for f in despues.values()}
    assert len(creadores) == 1 and min(creadores).startswith("migracion_") and min(creadores) >= "migracion_0007"
    assert max(f.version for f in despues.values()) == sesion.scalar(select(func.max(Umbral.version)))
    assert sesion.scalar(select(func.count()).select_from(Umbral).where(Umbral.creado_por == "migracion_0005"))


def test_migracion_0007_umbrales_de_las_reglas_nuevas_sube_y_baja(migrada, sesion):
    """La 0007 versiona los umbrales que el código leía con valor por omisión (ALT-002 observada y ruptura de RF-009):
    copia los valores del código, crea UNA versión nueva vigente y bajarla borra solo sus filas."""
    import importlib.util

    from app.servicios.alertas import UMBRALES_POR_DEFECTO
    from tests.integracion.conftest import RAIZ, _alembic

    spec = importlib.util.spec_from_file_location(
        "m0007", RAIZ / "alembic" / "versions" / "0007_umbrales_reglas_nuevas.py")
    m0007 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m0007)
    nuevos = {n: v for n, v, _d in m0007.UMBRALES_0007}
    assert m0007.down_revision == "0006"
    assert nuevos == {n: UMBRALES_POR_DEFECTO[n] for n in nuevos}        # sin deriva frente al código
    assert {"salidas_minimas_ocupacion", "persistencia_ocupacion_horas", "ruptura_k", "ruptura_h",
            "ruptura_dias_referencia", "ruptura_cambio_minimo", "ruptura_dias_reinicio"} <= set(nuevos)

    def vigentes():
        sesion.expire_all()
        filas = sesion.execute(select(Umbral.nombre, Umbral.valor, Umbral.version, Umbral.creado_por)
                               .where(Umbral.vigente)).all()
        return {f.nombre: f for f in filas}

    def de_la_0007():
        return sesion.scalar(select(func.count()).select_from(Umbral).where(Umbral.creado_por == "migracion_0007"))

    sesion.commit()
    try:
        _alembic("downgrade", "0006")
        assert de_la_0007() == 0
        antes = vigentes()
        assert antes and len({f.version for f in antes.values()}) == 1
        assert not set(nuevos) & set(antes) or any(f.creado_por != "migracion_0005" for f in antes.values())
    finally:
        sesion.rollback()
        _alembic("upgrade", "head")
    despues = vigentes()
    assert len({f.version for f in despues.values()}) == 1 and set(antes) | set(nuevos) <= set(despues)
    assert {n: despues[n].valor for n in nuevos} == nuevos
    assert max(f.version for f in despues.values()) == sesion.scalar(select(func.max(Umbral.version)))
    # la 0007 crea UNA versión del conjunto completo: lo que había más sus umbrales (las migraciones posteriores, como
    # la 0010, agregan después sus propios parámetros en otra versión)
    assert de_la_0007() == len(set(antes) | set(nuevos))


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


IDRUTAS = {"SILENCIO": 2, "CRA 54": 16, "CL 72": 21}


def _resultados_con_dimensiones_y_plan(cliente, sesion, ejecucion_ok: dict) -> None:
    """Sobre una ejecución real del ciclo: dimensiones de §8.3 en cada fila, plan del día siguiente (D4), foto de la
    respuesta (C3), resumen de calidad (C4) y métricas Prometheus de la cola y las etapas."""
    from app.modelos_db import Prediccion, Recomendacion

    eid = uuid.UUID(ejecucion_ok["execution_id"])
    preds = sesion.scalars(select(Prediccion).where(Prediccion.execution_id == eid)).all()
    assert preds and all(p.idruta == IDRUTAS[p.ruta] and p.id_dia_semana == p.fecha.isoweekday() for p in preds)
    recs = sesion.scalars(select(Recomendacion).where(Recomendacion.execution_id == eid)).all()
    franja = [r for r in recs if r.origen == "franja"]
    plan = [r for r in recs if r.origen == "plan_dia"]
    assert len(franja) == 9 and all(r.prediction_id is not None and r.idruta == IDRUTAS[r.ruta] for r in franja)
    metricas = ejecucion_ok["metricas"]
    assert {"plan_dia", "respuesta", "calidad"} <= set(metricas)
    assert len(plan) == ejecucion_ok["recomendaciones_plan_dia"] == metricas["recomendaciones_plan_dia"]
    if plan:     # una fila por (ruta, hora) del día siguiente, sin predicción, con sus dimensiones
        assert all(r.prediction_id is None and r.idruta == IDRUTAS[r.ruta] for r in plan)
        # headway en toda hora con salidas; una hora sin operación (p. ej. CL 72 a las 4 h en domingo: 0 minutos
        # operados) queda con 0 salidas y headway nulo, no con un intervalo inventado
        assert all(r.headway_min for r in plan if (r.buses_hora or 0) > 0)
        assert all(r.headway_min is None for r in plan if not r.buses_hora)
        assert len({(r.ruta, r.fecha, r.hora) for r in plan}) == len(plan)
        assert {r.fecha for r in plan} == {date.fromisoformat(metricas["plan_dia"]["fecha"])}
    else:        # sin plan, la ejecución igual termina «ok» y la advertencia dice por qué
        assert metricas["plan_dia"]["advertencias"]
    obs = sesion.execute(select(DemandaObservada.ruta, DemandaObservada.idruta, DemandaObservada.id_dia_semana,
                                DemandaObservada.fecha).where(DemandaObservada.execution_id == eid)).all()
    assert obs and all(i == IDRUTAS[r] and d == f.isoweekday() for r, i, d, f in obs)
    alertas = sesion.scalars(select(Alerta).where(Alerta.execution_id == eid)).all()
    assert all(a.idruta == IDRUTAS[a.ruta] and a.id_dia_semana for a in alertas if a.ruta in IDRUTAS)
    assert all(a.empresa != "Sobusa" for a in alertas)          # la empresa sale del catálogo, no de un literal
    lineas = cliente.get("/metrics").text.splitlines()
    assert any(x.startswith("api_ejecuciones_total{") and 'tipo="frecuencia"' in x and 'resultado="ok"' in x
               for x in lineas)
    assert any(x.startswith("api_ejecucion_etapa_segundos_count{") and 'etapa="prediccion"' in x for x in lineas)
    assert any(x.startswith("api_ejecucion_duracion_segundos_count{") and 'tipo="frecuencia"' in x for x in lineas)
    assert any(x.startswith("api_cola_trabajos{") and 'estado="en_cola"' in x for x in lineas)


@pytest.fixture
def marca_de_agua_propia(monkeypatch, sesion):
    """La marca de agua (y las huellas de la fuente) son solo las que dejan las ejecuciones de esta prueba: otras
    pruebas de la misma base pudieron dejar marcas posteriores (la prueba no depende del orden). Desde la migración
    0009 la marca es por proceso y ruta (marca_agua_ruta): la fuente de esta prueba lee un proceso propio, así que sus
    marcas no se mezclan con las de las demás y la prueba ejercita el mecanismo real, sin reemplazarlo."""
    from app.servicios import ejecucion

    desde = sesion.scalar(text("SELECT clock_timestamp()"))
    sesion.commit()
    proceso = f"prueba-marca-{uuid.uuid4().hex[:8]}"
    obtener = ejecucion.obtener_fuente

    def obtener_fuente():
        fuente = obtener()
        fuente.proceso = proceso
        return fuente

    monkeypatch.setattr(ejecucion, "obtener_fuente", obtener_fuente)
    return desde


def test_ejecucion_incremental_respeta_marca_de_agua(cliente, fuente_pequena, sesion, marca_de_agua_propia):
    primera = _correr(cliente, hasta="2025-03-02")
    assert primera["estado"] == "ok", primera["mensaje"]
    assert primera["filas_leidas"] > 0 and primera["predicciones"] == 9 and primera["recomendaciones"] == 9
    assert primera["correlation_id"] == "prueba-ejec" and primera["umbrales_version"] >= 1
    assert primera["model_id"] and primera["marca_agua_nueva"]
    _resultados_con_dimensiones_y_plan(cliente, sesion, primera)

    segunda = _correr(cliente, hasta="2025-03-02")
    assert segunda["estado"] == "ok" and segunda["filas_leidas"] == 0 and segunda["predicciones"] == 0
    assert segunda["marca_agua_anterior"] == primera["marca_agua_nueva"]

    tercera = _correr(cliente, hasta="2025-03-03", plan_dia=False)      # el plan del día se puede omitir
    assert tercera["estado"] == "ok" and 0 < tercera["filas_leidas"] < primera["filas_leidas"]
    assert tercera["recomendaciones_plan_dia"] == 0 and "plan_dia" not in tercera["metricas"]

    claves = sesion.execute(select(func.count(), func.count(func.distinct(
        func.concat(DemandaObservada.ruta, DemandaObservada.fecha, DemandaObservada.hora))))).one()
    assert claves[0] == claves[1]


def test_catalogos_de_la_calidad_salen_de_la_fuente():
    """§7.3 paso 3 y §8.3: la validación relacional recibe rutas e idruta del catálogo y, si la fuente operacional los
    expone, procesos, estacionalidades y novedades; un catálogo que falla no detiene la validación."""
    import pandas as pd

    from app.servicios import ejecucion

    class Fuente:
        def leer_contexto(self, nombre):
            if nombre == "novedades_viales":
                raise ConnectionError("réplica caída")
            return {"procesos": pd.DataFrame({"proceso": ["sobusa"]}),
                    "estacionalidades": pd.DataFrame({"id_estacionalidad": [1, 2, None]})}[nombre]

    cat = ejecucion.catalogos_calidad(Fuente())
    assert cat["rutas"] == set(IDRUTAS) and cat["idrutas"] == set(IDRUTAS.values())
    assert cat["procesos"] == {"sobusa"} and cat["estacionalidades"] == {1, 2} and "novedades" not in cat
    assert set(ejecucion.catalogos_calidad(object())) == {"rutas", "idrutas"}     # Parquet: solo el catálogo


def test_dias_observados_son_los_del_lote_en_la_ventana_que_ya_empezaron():
    """§5.2, RF-009: las alertas observadas evalúan cada día del lote con horas nuevas de los últimos
    VENTANA_OBSERVADA_DIAS días del lote (no la carga inicial día por día) que ya empezó frente a la referencia; con la
    captura en vivo, el ciclo de la madrugada evalúa el día anterior y el día en curso."""
    from app.servicios import ejecucion

    zona = ejecucion.ZONA
    dias = [date(2025, 8, 1) + timedelta(days=d) for d in range(30)]        # el último, el 30 de agosto
    carga_inicial = {(f, h) for f in dias for h in range(24)}
    referencia = datetime(2025, 8, 30, 5, 15, tzinfo=zona)                  # el ciclo de la madrugada del día 30
    assert ejecucion.dias_observados(carga_inicial, referencia) == dias[-ejecucion.VENTANA_OBSERVADA_DIAS:]
    madrugada = {(dias[-2], h) for h in range(4, 21)} | {(dias[-1], 4)}
    assert ejecucion.dias_observados(madrugada, referencia) == dias[-2:]
    # el día en curso entra cuando termina su primera hora de servicio (4 h): a las 4:30 todavía no
    assert ejecucion.dias_observados(madrugada, datetime(2025, 8, 30, 4, 30, tzinfo=zona)) == [dias[-2]]
    assert ejecucion.dias_observados(set(), referencia) == []


def test_una_recomendacion_por_ruta_y_franja_en_la_ejecucion(monkeypatch):
    """Rendimiento del ciclo: los horizontes que caen en la misma franja reciben copias de una sola recomendación;
    una franja distinta se resuelve aparte y un error no se guarda (se repite en cada horizonte)."""
    from app.servicios import ejecucion, optimizacion

    llamadas = []

    def falsa(info, umbrales, version, **kw):
        llamadas.append((info["ruta"], kw["hora"]))
        if kw["hora"] == 99:
            raise ValueError("franja sin parámetros")
        return {"buses_hora": 7, "explicacion": ["x"]}, {"capacidad": 80, "tipologias": [{"codigo": "B"}]}

    monkeypatch.setattr(optimizacion, "recomendacion_franja", falsa)
    rec = ejecucion._RecomendacionesDeLaEjecucion({"ocupacion_objetivo_max": 0.85}, 3)
    franja = {"fecha": date(2025, 8, 31), "hora": 6, "demanda_hora": 768.4, "p90_hora": 923.5, "p10_hora": 600.0}
    r1, e1 = rec.de_la_franja({}, "SILENCIO", dict(franja, fraccion_ventana=0.5))
    r2, e2 = rec.de_la_franja({}, "SILENCIO", dict(franja, fraccion_ventana=1.0))
    assert llamadas == [("SILENCIO", 6)] and r1 == r2 and e1 == e2
    r1["franja_prediccion"] = "primera"
    r1["explicacion"].append("y")
    e1["tipologias"][0]["codigo"] = "C"
    assert "franja_prediccion" not in r2 and r2["explicacion"] == ["x"] and e2["tipologias"][0]["codigo"] == "B"
    rec.de_la_franja({}, "CRA 54", franja)
    rec.de_la_franja({}, "SILENCIO", dict(franja, hora=7))
    assert len(llamadas) == 3
    for _ in range(2):
        with pytest.raises(ValueError):
            rec.de_la_franja({}, "SILENCIO", dict(franja, hora=99))
    assert len(llamadas) == 5


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
        # la compuerta de activación mira también la cobertura calibrada y el sesgo (cuatro criterios)
        return {"wape": wapes[model_id], "mae": 1.0, "rmse": 1.0, "por_ruta": {}, "sesgo_pct": 1.0,
                "cobertura_p10_p90_conformal": 80.0}

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
def test_umbrales_versionados(cliente, umbrales_restituidos):
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


# ---------------------------------------------------------------- escalamiento (§7.2), calidad, cola y API
def test_redeteccion_mas_grave_escala_y_notifica(sesion, monkeypatch):
    """D7: subir de preventiva a crítica actualiza la alerta, deja «escalar» en la bitácora (sin cambiar el estado) y
    la notifica; una redetección más leve solo suma la ocurrencia (la severidad nunca baja sola)."""
    from types import SimpleNamespace

    from app.modelos_db import HistorialAlerta
    from app.servicios import ejecucion, notificaciones

    clave = f"ALT-002|CL 72|{uuid.uuid4()}"
    a1, nueva = ejecucion.guardar_alerta(sesion, dict(_alerta_base(clave), ruta="CL 72", severidad="preventiva"),
                                         None, 1)
    assert nueva and a1.severidad == "preventiva" and a1.idruta == 21 and a1.idproceso in ("sobusa", None)
    a2, nueva2 = ejecucion.guardar_alerta(sesion, dict(_alerta_base(clave), ruta="CL 72", severidad="critica"),
                                          None, 1)
    assert not nueva2 and a2.alert_id == a1.alert_id and a2.severidad == "critica" and a2.estado == "nueva"
    a3, _ = ejecucion.guardar_alerta(sesion, dict(_alerta_base(clave), ruta="CL 72", severidad="informativa"), None, 1)
    assert a3.severidad == "critica" and a3.ocurrencias == 3
    sesion.flush()
    acciones = [(h.accion, h.estado_anterior, h.estado_nuevo, h.detalle.get("severidad_nueva")) for h in sesion.scalars(
        select(HistorialAlerta).where(HistorialAlerta.alert_id == a1.alert_id).order_by(HistorialAlerta.id))]
    assert acciones == [("crear", None, "nueva", None), ("escalar", "nueva", "nueva", "critica")]

    enviadas = []

    class Canal:
        def enviar(self, alerta):
            enviadas.append(alerta)
            return {"canal": "prueba", "estado": "simulado", "simulado": True}

    monkeypatch.setattr(notificaciones, "notificadores_desde_entorno", lambda: [Canal()])
    ciclo = SimpleNamespace(p={}, nuevas_alertas=[], metricas={}, execution_id=None, fallos=[])
    ejecucion._notificar_nuevas(sesion, ciclo)
    assert ciclo.metricas == {"alertas_escaladas": 1, "notificaciones": 1, "notificaciones_por_estado": {"simulado": 1}}
    assert enviadas[0]["alert_id"] == str(a1.alert_id) and enviadas[0]["motivo_notificacion"] == "escalamiento"
    sesion.rollback()


def test_errores_de_calidad_con_llave_valor_y_filtro_por_idruta(cliente, sesion):
    """C4: cada error queda con la llave del registro, el valor y si bloquea; la API los filtra por idruta."""
    import pandas as pd

    from app.servicios import calidad, ejecucion

    e = ejecucion.crear_ejecucion(sesion, "frecuencia", {"prueba": "calidad"}, None)
    lote = pd.DataFrame({"ruta": ["CL 72", "CRA 54", "RUTA X"], "fecha": [date(2025, 3, 1)] * 3, "hora": [6, 7, 8],
                         "pasajeros": [-5.0, 120.0, 30.0], "salidas": [4, 5, 3],
                         "ultima_actualizacion": [datetime(2025, 3, 2, 1, 0, tzinfo=UTC)] * 3})
    _, errores = calidad.validar_lote(lote, "prueba", catalogos=ejecucion.catalogos_calidad(None),
                                      ahora=ejecucion.ahora())
    assert errores
    ejecucion._guardar_errores(sesion, e.execution_id, "prueba", errores)
    sesion.commit()
    todos = cliente.get(f"/api/v1/frequency/executions/{e.execution_id}/errors").json()
    assert todos["total"] == len(errores)
    assert all(x["llave"] and "bloqueante" in x for x in todos["items"])
    de_cl72 = cliente.get(f"/api/v1/frequency/executions/{e.execution_id}/errors", params={"idruta": 21}).json()
    assert de_cl72["total"] >= 1 and all(x["llave"].get("ruta") == "CL 72" for x in de_cl72["items"])
    negativo = next(x for x in de_cl72["items"] if x["campo"] == "pasajeros")
    assert negativo["valor"] in ("-5.0", "-5") and negativo["bloqueante"] is True
    sesion.execute(text("UPDATE ai_frecuencias.execution_log SET estado = 'error' WHERE execution_id = :i"),
                   {"i": e.execution_id})
    sesion.commit()


def test_trabajo_respuesta_en_la_cola(sesion, monkeypatch):
    """C3: una ejecución tipo «respuesta» la toma la cola, llama a respuesta.precalcular con {fecha, rutas} y cierra
    «ok» en la misma transacción. D4 también desde la cola: persiste las filas origen='plan_dia' de los mismos planes
    que usó la foto, así que GET /recommendations/plan responde después de POST /respuesta/calcular."""
    from app.modelos_db import Recomendacion
    from app.servicios import cola, ejecucion, respuesta

    llamadas = []
    horas = [{"hora": 4, "salidas": 0, "headway_min": None, "minutos_operados": 0.0, "pasajeros_previstos": 0.0,
              "viable": True, "motivo": "Sin operación programada en la hora"},
             {"hora": 5, "salidas": 6, "headway_min": 10.0, "vehiculos_requeridos": 20, "minutos_operados": 60.0,
              "pasajeros_previstos": 120.5, "pasajeros_p90": 150.0, "viable": True}]

    def precalcular(s, fecha, rutas=None, *, execution_id=None, confirmar=False, planes=None):
        llamadas.append((fecha, rutas, execution_id))
        for r in rutas:
            planes[r] = {"horas": horas, "model_id": "hgb_prueba", "fuente_pronostico": "modelo_activo",
                         "calibracion_version": "v2", "umbrales_version": 1, "salidas_dia": 6}
        return {"fecha": fecha.isoformat(), "guardadas": len(rutas), "rutas": [{"ruta": r} for r in rutas],
                "trazabilidad": {"model_id": "hgb_prueba", "umbrales_version": 1, "fuente_pronostico": "modelo_activo",
                                 "calibracion_version": "v2"}}

    monkeypatch.setattr(respuesta, "precalcular", precalcular)
    e = ejecucion.crear_ejecucion(sesion, "respuesta", {"fecha": "2025-09-01", "rutas": ["CL 72"]}, None)
    assert cola.procesar(e.execution_id) == "ok"
    sesion.expire_all()
    final = sesion.get(Ejecucion, e.execution_id)
    assert llamadas == [(date(2025, 9, 1), ["CL 72"], e.execution_id)]
    assert final.estado == "ok" and final.model_id == "hgb_prueba" and final.metricas["guardadas"] == 1
    assert final.metricas["recomendaciones_plan_dia"] == 2 and final.metricas["plan_dia"]["rutas"] == {"CL 72": 2}
    filas = sesion.scalars(select(Recomendacion).where(Recomendacion.execution_id == e.execution_id)
                           .order_by(Recomendacion.hora)).all()
    assert [(f.origen, f.ruta, f.fecha, f.hora) for f in filas] == [("plan_dia", "CL 72", date(2025, 9, 1), 4),
                                                                    ("plan_dia", "CL 72", date(2025, 9, 1), 5)]
    assert filas[0].buses_hora == 0 and filas[0].headway_min is None        # hora sin operación: sin intervalo
    assert filas[1].headway_min == 10.0 and filas[1].idruta == 21 and filas[1].prediction_id is None


def test_trabajo_respuesta_de_un_dia_sin_datos_no_se_reintenta(sesion):
    """Un día fuera de los calculables (respuesta.SinDatos) falla de forma definitiva al primer intento."""
    from app.servicios import cola, ejecucion

    e = ejecucion.crear_ejecucion(sesion, "respuesta", {"fecha": "2031-01-01", "rutas": ["CL 72"]}, None)
    assert cola.procesar(e.execution_id) == "error"
    sesion.expire_all()
    final = sesion.get(Ejecucion, e.execution_id)
    assert final.estado == "error" and final.intentos == 1


def test_umbrales_se_aprueban_por_version(cliente, umbrales_restituidos):
    """§5.1: una versión nace «propuesta»; el área operativa la aprueba (rol admin) y la firma queda en cada fila."""
    vigente = cliente.get("/api/v1/thresholds").json()
    nueva = cliente.put("/api/v1/thresholds", json={"valores": {"baja_utilizacion": vigente["valores"]
                                                                ["baja_utilizacion"]}, "motivo": "prueba"}).json()
    assert nueva["estado"] == "propuesta" and nueva["aprobado_por"] is None
    r = cliente.post(f"/api/v1/thresholds/{nueva['version']}/aprobar",
                     json={"aprobado_por": "jefe_operacion", "comentario": "acta 12"})
    assert r.status_code == 200, r.text
    assert r.json()["estado"] == "aprobada" and r.json()["aprobado_por"] and r.json()["aprobado_en"]
    assert all(d["aprobado_por"] == r.json()["aprobado_por"] for d in r.json()["detalle"])
    otra = cliente.post(f"/api/v1/thresholds/{nueva['version']}/aprobar", json={"aprobado_por": "otro"})
    assert otra.json()["aprobado_por"] == r.json()["aprobado_por"]          # idempotente: conserva la primera
    assert cliente.get("/api/v1/thresholds").json()["estado"] == "aprobada"
    assert cliente.post("/api/v1/thresholds/999999/aprobar").status_code == 404


def test_exportacion_avisa_el_tope_de_filas(cliente, sesion, monkeypatch):
    """Con el tope alcanzado la exportación lo dice: X-Truncado=true y X-Total-Count con todo lo filtrado."""
    from app.routers import comun
    from app.servicios import ejecucion

    clave = f"ALT-002|SILENCIO|{uuid.uuid4()}"
    for i in range(3):
        ejecucion.guardar_alerta(sesion, dict(_alerta_base(f"{clave}|{i}"), ruta="SILENCIO"), None, 1)
    sesion.commit()
    completo = cliente.get("/api/v1/alerts/export", params={"formato": "csv", "ruta": "SILENCIO"})
    total = int(completo.headers["X-Total-Count"])
    assert completo.headers["X-Truncado"] == "false" and total >= 3
    monkeypatch.setattr(comun, "LIMITE_EXPORTACION", 2)
    cortado = cliente.get("/api/v1/alerts/export", params={"formato": "csv", "ruta": "SILENCIO"})
    assert cortado.headers["X-Truncado"] == "true" and int(cortado.headers["X-Total-Count"]) == total
    assert len(cortado.content.decode("utf-8-sig").splitlines()) == 3        # cabecera + 2 filas
    cabeceras = cliente.get("/openapi.json").json()["paths"]["/api/v1/alerts/export"]["get"]["responses"]["200"]
    assert {"X-Total-Count", "X-Truncado"} <= set(cabeceras["headers"])


def test_listado_de_ejecuciones_por_fecha_y_modelo(cliente, sesion):
    from app.servicios import ejecucion

    e = ejecucion.crear_ejecucion(sesion, "frecuencia", {"prueba": "filtros"}, None)
    sesion.execute(text("UPDATE ai_frecuencias.execution_log SET estado = 'error', model_id = 'modelo_filtro', "
                        "creado_en = '2024-02-10 12:00-05' WHERE execution_id = :i"), {"i": e.execution_id})
    sesion.commit()
    base = "/api/v1/frequency/executions"
    r = cliente.get(base, params={"desde": "2024-02-10", "hasta": "2024-02-10", "model_id": "modelo_filtro"}).json()
    assert [x["execution_id"] for x in r["items"]] == [str(e.execution_id)]
    assert cliente.get(base, params={"desde": "2024-02-11", "model_id": "modelo_filtro"}).json()["total"] == 0
    assert cliente.get(base, params={"hasta": "2024-02-09", "model_id": "modelo_filtro"}).json()["total"] == 0
    malo = cliente.get(base, params={"desde": "2024-02-11", "hasta": "2024-02-10"})
    assert malo.status_code == 422 and malo.json()["error"]["codigo"] == "rango_invalido"
