"""Integración: una ejecución con datos OBSERVADOS produce ALT-005..ALT-009 con la estructura completa de §5.3,
deduplicadas por episodio, con su bitácora, la ubicación como geography (GiST, §8.1) y el conductor solo seudónimo.

Lote: 8 semanas reales (referencia del consolidado) + el 15/10/2025 alterado a propósito:
- CRA 54: caída del 60 % a las 8 y 9 h (ALT-005), salto sobre el P90 a las 15 y 16 h (ALT-007) y 0 salidas a las 12 h
  (ALT-006, con el punto de despacho);
- SILENCIO: número de viajes del día triplicado (ALT-008);
- CL 72: falta la hora 14 (ALT-009).
La fuente expone además los viajes del día de progvehiculos (§5.3), con el conductor seudonimizado como en las fuentes
reales: ALT-006 y ALT-009 llevan el viaje, el vehículo y el seudónimo del conductor; las demás, el motivo por el que no
aplican (variables.identificacion_5_3).
La fuente es de prueba (FuenteFija) y no escribe nada fuera de la base local de pruebas. Con GENERAR_EVIDENCIAS=1 la
prueba reescribe docs/evidencias/alertas/alertas_observadas_ejemplo.json (cinco alertas guardadas con su bitácora).
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from tests.evidencia import guardar_evidencia

Z = ZoneInfo("America/Bogota")
DIA = date(2025, 10, 15)
PUNTO = {"type": "Point", "coordinates": [-74.8, 10.98]}
SECRETO = "secreto-integracion-alertas-observadas"   # seudónimos de prueba, solo de conductores sintéticos
EJECUCIONES: list = []   # ejecuciones que crea este módulo; al final se borra lo que guardaron


def _limpiar(sesion, ids: list) -> None:
    """Deja la base como estaba: la demanda incorporada (8 semanas reales), las alertas con su bitácora, las
    recomendaciones, las predicciones y las ejecuciones de la prueba."""
    from sqlalchemy import delete

    from app.modelos_db import Alerta, DemandaObservada, Ejecucion, Prediccion, Recomendacion

    sesion.rollback()
    if not ids:
        return
    for modelo in (DemandaObservada, Alerta, Recomendacion, Prediccion, Ejecucion):
        sesion.execute(delete(modelo).where(modelo.execution_id.in_(ids)))
    sesion.commit()
    ids.clear()


def _viajes_del_dia() -> pd.DataFrame:
    """Viajes de progvehiculos de DIA como los devuelve el SELECT de la fuente (idconductor en claro, antes de
    seudonimizar): CRA 54 con dos despachos cancelados a las 12 h (la hora sin salidas); CL 72 con un viaje sin
    numeropasajeros y sin timbradas de segmento a las 14 h (la hora que no llegó)."""
    def v(viaje, ruta, hora, minuto, vehiculo, conductor, cancelada="N", pasajeros=30, segmentos=40):
        salida = datetime.combine(DIA, time(hora, minuto))
        return {"ruta": ruta, "viaje": viaje, "vehiculo": vehiculo, "idconductor": conductor, "salida": salida,
                "salida_real": salida + timedelta(minutes=1), "finalizado": "N" if cancelada == "S" else "S",
                "cancelada": cancelada, "excedeplazosalida": None, "numeropasajeros": pasajeros,
                "filas_segmento": segmentos}
    return pd.DataFrame([v(8001, "CRA 54", 11, 52, "SOBUSA21", 5101), v(8002, "CRA 54", 12, 15, "SOBUSA52", 5252, "S"),
                         v(8003, "CRA 54", 12, 45, "SOBUSA53", 5353, "S"), v(8004, "CRA 54", 13, 5, "SOBUSA54", 5454),
                         v(8100, "CL 72", 13, 40, "SOBUSA16", 6161),
                         v(8101, "CL 72", 14, 20, "SOBUSA17", 7171, pasajeros=None, segmentos=0)])


class FuenteFija:
    """Fuente operacional de prueba: entrega siempre el mismo lote (como una relectura de datos tardíos) y NO mueve
    la marca de agua (devuelve la anterior), para no alterar a las demás pruebas de la sesión. Los viajes del día
    salen de _viajes_del_dia, seudonimizados con la misma función que las fuentes reales."""

    def __init__(self, df):
        self.df = df

    def leer_incremental(self, marca_agua=None, hasta=None):
        return self.df.copy(), marca_agua

    def procesos(self):
        return pd.DataFrame({"proceso": ["sobusa"], "toleranciatiempo": [0]})

    def ubicacion_despacho(self, ruta):
        return PUNTO if ruta == "CRA 54" else None

    def viajes(self, ruta, desde, hasta):
        from app.servicios import fuentes

        d = _viajes_del_dia()
        salida = pd.to_datetime(d["salida"])
        ini, fin = desde.astimezone(Z).replace(tzinfo=None), hasta.astimezone(Z).replace(tzinfo=None)
        return fuentes.seudonimizar_viajes(d[(d["ruta"] == ruta) & (salida >= ini) & (salida < fin)]
                                           .drop(columns=["ruta"]))


@pytest.fixture
def lote_observado(monkeypatch, sesion):
    from app.servicios import datos, ejecucion, inferencia

    monkeypatch.setenv("SEUDONIMO_SECRETO", SECRETO)
    modelo = inferencia.modelo_activo()
    d = datos.demanda_horaria(desde=DIA - timedelta(weeks=8), hasta=DIA).copy()   # ultima_actualizacion: fin del día

    def banda(ruta, h):
        r = inferencia.predecir(ruta, datetime.combine(DIA, time(h), tzinfo=Z), 60, model_id=modelo,
                                usar_nowcast=False)
        return r["pasajeros"], r["p10"], r["p90"]

    hoy = d["fecha"] == DIA
    for h in (8, 9):
        e, p10, _ = banda("CRA 54", h)
        d.loc[hoy & (d["ruta"] == "CRA 54") & (d["hora"] == h), "pasajeros"] = round(min(0.4 * e, 0.8 * p10), 1)
    for h in (15, 16):
        e, _, p90 = banda("CRA 54", h)
        d.loc[hoy & (d["ruta"] == "CRA 54") & (d["hora"] == h), "pasajeros"] = round(max(1.6 * e, 1.3 * p90), 1)
    # sin despacho no hay pasajeros (CONS-002 de calidad rechaza «pasajeros en una hora sin salidas»)
    d.loc[hoy & (d["ruta"] == "CRA 54") & (d["hora"] == 12), ["salidas", "pasajeros"]] = 0
    d.loc[hoy & (d["ruta"] == "SILENCIO"), "salidas"] = d.loc[hoy & (d["ruta"] == "SILENCIO"), "salidas"] * 3
    # CL 72: sobreocupación OBSERVADA a las 17 y 18 h (ALT-002 observada): 120 % con el factor de carga de la franja y
    # los puestos por bus del catálogo de la ruta (los mismos que usa el ciclo)
    from app.servicios import optimizacion

    puestos = float({r["ruta"]: r for r in datos.catalogo_rutas()}["CL 72"].get("capacidad") or 50)
    for h in (17, 18):
        fila = hoy & (d["ruta"] == "CL 72") & (d["hora"] == h)
        factor = optimizacion.factor_carga_franja("CL 72", DIA, h)["factor_carga"]
        d.loc[fila, "pasajeros"] = round(1.2 * float(d.loc[fila, "salidas"].iloc[0]) * puestos / factor, 1)
    d = d[~(hoy & (d["ruta"] == "CL 72") & (d["hora"] == 14))].reset_index(drop=True)
    sesion.execute(text("DELETE FROM ai_frecuencias.demanda_observada WHERE ruta = 'CL 72' AND fecha = :f "
                        "AND hora = 14"), {"f": DIA})
    sesion.commit()
    monkeypatch.setattr(ejecucion, "obtener_fuente", lambda: FuenteFija(d))
    try:
        yield modelo
    finally:
        _limpiar(sesion, EJECUCIONES)


def _correr(cliente, modelo):
    r = cliente.post("/api/v1/frequency/executions", json={"hasta": str(DIA), "model_id": modelo, "notificar": False})
    assert r.status_code == 202, r.text
    EJECUCIONES.append(uuid.UUID(r.json()["execution_id"]))
    e = cliente.get(f"/api/v1/frequency/executions/{r.json()['execution_id']}").json()
    assert e["estado"] == "ok", e.get("mensaje")
    return e


def _local(v):
    return datetime.fromisoformat(str(v).replace("Z", "+00:00")).astimezone(Z)


def _alertas(cliente, codigo, ruta):
    r = cliente.get("/api/v1/alerts", params={"codigo": codigo, "ruta": ruta, "limite": 500})
    assert r.status_code == 200, r.text
    out = []
    for a in r.json()["items"]:
        if a["horizonte_min"] != 0:
            continue
        if codigo == "ALT-009":
            if str(DIA) in a["clave_dedup"] and a["clave_dedup"].endswith("|faltantes"):
                out.append(a)
        elif a["ventana_inicio"] and _local(a["ventana_inicio"]).date() == DIA:
            out.append(a)
    return out


def test_ejecucion_con_datos_observados_produce_alt005_a_alt009(cliente, lote_observado, sesion):
    e = _correr(cliente, lote_observado)
    obs = e["metricas"]["alertas_observadas"]
    assert {"ALT-005", "ALT-006", "ALT-007", "ALT-008", "ALT-009"} <= set(obs["por_codigo"]), obs
    assert obs["horas_evaluadas"] >= 3 * 16

    esperadas = {("ALT-005", "CRA 54"), ("ALT-006", "CRA 54"), ("ALT-007", "CRA 54"), ("ALT-008", "SILENCIO"),
                 ("ALT-009", "CL 72"), ("ALT-002", "CL 72")}
    vistas = {}
    for codigo, ruta in esperadas:
        al = _alertas(cliente, codigo, ruta)
        assert al, f"{codigo} {ruta} no aparece en GET /alerts"
        a = al[0]
        vistas[codigo] = a
        # §5.3 completa y §9.4 (real, esperado, umbral, tendencia, recomendación) en la respuesta de la API
        for campo in ("alert_id", "codigo", "empresa", "ruta", "detectada_en", "ventana_inicio", "ventana_fin",
                      "severidad", "estado", "observado", "esperado", "umbral", "puntaje", "explicacion",
                      "recomendacion", "clave_dedup", "tendencia", "metodo_puntaje", "origen"):
            assert a[campo] is not None, (codigo, campo)
        for campo in ("sentido", "viaje", "conductor", "vehiculo", "probabilidad", "asignado_a", "ubicacion",
                      "variables_influyentes", "serie_reciente", "comentarios"):
            assert campo in a, (codigo, campo)
        assert a["estado"] == "nueva" and a["horizonte_min"] == 0
        assert a["tendencia"] in ("al_alza", "a_la_baja", "estable", "sin_datos")
        assert a["variables"]["umbrales_version"] == e["umbrales_version"]
        historia = cliente.get(f"/api/v1/alerts/{a['alert_id']}/history").json()
        assert [h["accion"] for h in historia][:1] == ["crear"]

    a5 = vistas["ALT-005"]
    assert a5["origen"] == "observado" and a5["severidad"] == "preventiva"
    assert _local(a5["ventana_inicio"]).hour == 8 and _local(a5["ventana_fin"]).hour == 10
    assert a5["variables_influyentes"] and a5["serie_reciente"] and a5["clave_dedup"].endswith("|obs")
    assert vistas["ALT-007"]["variables"]["sentido_desviacion"] == "+"
    a6 = vistas["ALT-006"]
    assert a6["severidad"] == "critica" and a6["ubicacion"] == PUNTO
    assert a6["variables"]["fuente_tolerancia"] == "threshold_config.tolerancia_despacho_min"   # toleranciatiempo 0
    assert vistas["ALT-008"]["variables"]["z_por_campo"]["nro_viajes"] >= 3.5
    assert any("14:00" in h for h in vistas["ALT-009"]["variables"]["horas_faltantes"])
    # §5.2 ALT-002 «ocupación observada» evaluada en producción: factor de carga × pasajeros / (salidas × puestos)
    # (el día real puede traer otros episodios de sobreocupación; el inyectado cubre las 17 y 18 h)
    a2 = next(x for x in _alertas(cliente, "ALT-002", "CL 72")
              if _local(x["ventana_inicio"]).hour <= 17 and _local(x["ventana_fin"]).hour >= 19)
    assert a2["origen"] == "observado" and a2["severidad"] == "critica"
    assert a2["variables"]["tipo_ocupacion"] == "observada" and a2["observado"] >= 1.15
    assert {"17:00", "18:00"} <= set(a2["variables"]["ocupacion_por_hora"])

    # alertas de pronóstico del mismo ciclo: en la hora recomendada (demanda y capacidad por hora) y una sola por
    # código, ruta y franja aunque la miren los tres horizontes
    filas_rec = sesion.execute(text(
        "SELECT ruta, fecha, hora, detalle FROM ai_frecuencias.recommendation WHERE execution_id = :e"),
        {"e": e["execution_id"]}).all()
    recomendadas = {(r, f, int(h)) for r, f, h, _ in filas_rec}
    assert recomendadas
    pronostico = sesion.execute(text(
        "SELECT codigo, ruta, ventana_inicio, ventana_fin, variables, esperado FROM ai_frecuencias.alert "
        "WHERE execution_id = :e AND origen = 'pronostico'"), {"e": e["execution_id"]}).all()
    claves = [(c, r, vi) for c, r, vi, *_ in pronostico]
    assert len(claves) == len(set(claves))
    for codigo, ruta, vi, vf, variables, _ in pronostico:
        ini = vi.astimezone(Z)
        assert (ruta, ini.date(), ini.hour) in recomendadas, (codigo, ruta, ini)
        assert vf - vi == timedelta(hours=1)
        assert variables["horizontes_min"], codigo
    # la alerta y la recomendación de la misma franja dicen la MISMA ocupación (factor de carga del optimizador):
    # ALT-002 de pronóstico sale si y solo si la ocupación de la frecuencia actual que calcula el optimizador ≥ 90 %
    alt002 = {(r, vi.astimezone(Z).hour): esp for c, r, vi, _, _, esp in pronostico if c == "ALT-002"}
    for ruta, _, hora, detalle in filas_rec:
        actual = ((detalle or {}).get("salida", {}).get("comparacion_actual") or {}).get("actual") or {}
        ocupacion = actual.get("ocupacion_esperada")
        if ocupacion is None:
            continue
        assert ((ruta, int(hora)) in alt002) is (ocupacion >= 0.9), (ruta, hora, ocupacion)
        if (ruta, int(hora)) in alt002:
            assert alt002[(ruta, int(hora))] == pytest.approx(ocupacion, abs=1e-4)

    # §8.1: la ubicación es geography(Point,4326) con índice GiST y responde a consultas espaciales
    tipo = sesion.execute(text("SELECT format_type(atttypid, atttypmod) FROM pg_attribute WHERE attrelid = "
                               "'ai_frecuencias.alert'::regclass AND attname = 'ubicacion'")).scalar()
    if tipo.startswith("geography"):
        assert sesion.execute(text("SELECT indexdef FROM pg_indexes WHERE schemaname = 'ai_frecuencias' "
                                   "AND indexname = 'ix_alert_ubicacion'")).scalar().lower().find("gist") > 0
        cerca = sesion.execute(text(
            "SELECT count(*) FROM ai_frecuencias.alert WHERE alert_id = :i AND ST_DWithin(ubicacion, "
            "ST_SetSRID(ST_MakePoint(-74.801, 10.981), 4326)::geography, 500)"), {"i": a6["alert_id"]}).scalar()
        assert cerca == 1

    # §18: deduplicación por episodio; la segunda ejecución con el mismo lote no duplica
    e2 = _correr(cliente, lote_observado)
    assert e2["metricas"]["alertas_observadas"]["por_codigo"] == obs["por_codigo"]
    for codigo, ruta in esperadas:
        al = _alertas(cliente, codigo, ruta)
        claves = [a["clave_dedup"] for a in al]
        assert len(claves) == len(set(claves))
        a = next(x for x in al if x["clave_dedup"] == vistas[codigo]["clave_dedup"])
        assert a["ocurrencias"] >= 2 and a["alert_id"] == vistas[codigo]["alert_id"]

    # §5.3 «viaje, conductor y vehículo, cuando aplique»: ALT-006 y ALT-009 llevan el viaje, el vehículo y el
    # seudónimo del conductor (nunca el id en claro); ALT-005, ALT-007 y ALT-008 dicen por qué no aplican
    a9 = vistas["ALT-009"]
    assert (a6["viaje"], a6["vehiculo"]) == ("8002", "SOBUSA52") and a6["conductor"].startswith("cnd_")
    assert (a9["viaje"], a9["vehiculo"]) == ("8101", "SOBUSA17") and a9["conductor"].startswith("cnd_")
    for a in (a6, a9):
        assert a["variables"]["identificacion_5_3"]["resultado"] == "identificado"
    for codigo in ("ALT-005", "ALT-007", "ALT-008"):
        ident = vistas[codigo]["variables"]["identificacion_5_3"]
        assert ident["aplica"] == [] and ident["motivo"] and vistas[codigo]["viaje"] is None, codigo
    _guardar_ejemplo(cliente, sesion, vistas, tipo)


def _valor_umbral(valor):
    numero = float(valor)
    return int(numero) if numero.is_integer() else numero


def _guardar_ejemplo(cliente, sesion, vistas: dict, columna: str) -> None:
    """alertas/alertas_observadas_ejemplo.json (en docs/evidencias solo con GENERAR_EVIDENCIAS=1): cinco alertas
    observadas como las guarda PostgreSQL y las devuelve GET /alerts/{id}, con la identificación de §5.3 (el viaje,
    el vehículo y el seudónimo del conductor, o en variables.identificacion_5_3 el motivo por el que no aplica) y su
    bitácora; además la columna de la ubicación, su índice GiST, el CHECK del seudónimo y los umbrales de las alertas
    que agregó la migración 0003 (UMBRALES_0003; su versión copia también los anteriores)."""
    import importlib.util

    from tests.integracion.conftest import RAIZ

    spec = importlib.util.spec_from_file_location("m0003", RAIZ / "alembic" / "versions" / "0003_alertas_estructura.py")
    m0003 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m0003)
    indice = sesion.execute(text("SELECT indexdef FROM pg_indexes WHERE schemaname = 'ai_frecuencias' "
                                 "AND indexname = 'ix_alert_ubicacion'")).scalar()
    check = sesion.execute(text("SELECT pg_get_constraintdef(c.oid) FROM pg_constraint c WHERE c.conrelid = "
                                "'ai_frecuencias.alert'::regclass AND c.contype = 'c' AND "
                                "pg_get_constraintdef(c.oid) LIKE '%conductor%'")).scalar()
    umbrales = sesion.execute(text("SELECT version, nombre, valor, creado_por FROM ai_frecuencias.threshold_config "
                                   "WHERE creado_por = 'migracion_0003' AND nombre = ANY(:n) ORDER BY nombre"),
                              {"n": [n for n, _v, _d in m0003.UMBRALES_0003]}).all()
    sesion.rollback()
    alertas = []
    for codigo in ("ALT-005", "ALT-006", "ALT-007", "ALT-008", "ALT-009"):
        a = cliente.get(f"/api/v1/alerts/{vistas[codigo]['alert_id']}").json()
        historia = cliente.get(f"/api/v1/alerts/{a['alert_id']}/history").json()
        a["bitacora"] = [{k: h.get(k) for k in ("accion", "estado_nuevo", "usuario", "comentario", "creado_en")}
                         for h in historia]
        alertas.append(a)
    base = os.environ.get("TEST_DATABASE_NAME", "ai_frecuencias_pruebas")
    contenido = {"origen": f"tests/integracion/test_alertas_observadas.py en la base local {base}",
                 "columna_ubicacion": columna, "indice_ubicacion": indice, "check_conductor": check,
                 "umbrales_migracion_0003": [{"version": f.version, "nombre": f.nombre, "valor": _valor_umbral(f.valor),
                                              "creado_por": f.creado_por} for f in umbrales],
                 "alertas": alertas}
    guardar_evidencia("alertas/alertas_observadas_ejemplo.json",
                      json.dumps(contenido, ensure_ascii=False, indent=2, default=str))


def test_la_base_rechaza_un_conductor_en_claro(sesion, migrada):
    from app.modelos_db import Alerta

    a = Alerta(alert_id=uuid.uuid4(), codigo="ALT-006", ruta="PRUEBA_SEUDONIMO", detectada_en=datetime.now(UTC),
               severidad="critica", estado="nueva", clave_dedup=f"ALT-006|PRUEBA_SEUDONIMO|{uuid.uuid4()}",
               conductor="Juan Pérez")
    sesion.add(a)
    with pytest.raises(IntegrityError):
        sesion.commit()
    sesion.rollback()
