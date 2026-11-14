"""Integración de §5.3 «viaje, conductor y vehículo, cuando aplique».

Una ejecución real de la API con una fuente que, como FuentePostgresSoloLectura, expone los viajes del día
(progvehiculos, con el conductor seudonimizado en la fuente): ALT-006 lleva el viaje, el vehículo y el seudónimo del
conductor del despacho cancelado de la hora sin salidas, ALT-009 los del viaje con datos faltantes de la hora que no
llegó, la base solo guarda seudónimos y toda alerta de la ejecución dice qué campos de identificación le aplican.

La fuente es de prueba y no escribe nada fuera de la base local de pruebas. La prueba borra lo que creó.
"""
from __future__ import annotations

import hashlib
import hmac
import uuid
from datetime import date, datetime, time, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
from sqlalchemy import delete, select, text

Z = ZoneInfo("America/Bogota")
DIA = date(2025, 10, 22)            # miércoles laboral (no lo usa ninguna otra prueba de alertas observadas)
SECRETO = "secreto-integracion-identificacion"
E = "ai_frecuencias"


def _seudonimo(valor) -> str:
    return "cnd_" + hmac.new(SECRETO.encode(), str(valor).encode(), hashlib.sha256).hexdigest()[:24]


def _limpiar(sesion, ids: list) -> None:
    """Lo que dejaron las ejecuciones de la prueba (y sus trabajos por ruta)."""
    from app.modelos_db import Alerta, DemandaObservada, Ejecucion, Prediccion, Recomendacion, RespuestaReto

    sesion.rollback()
    if not ids:
        return
    todos = set(ids) | set(sesion.scalars(select(Ejecucion.execution_id).where(Ejecucion.padre_id.in_(ids))))
    for modelo in (DemandaObservada, Alerta, Recomendacion, Prediccion, RespuestaReto):
        sesion.execute(delete(modelo).where(modelo.execution_id.in_(todos)))
    sesion.execute(delete(Ejecucion).where(Ejecucion.execution_id.in_(todos)))
    sesion.commit()
    ids.clear()


def _viajes_del_dia() -> pd.DataFrame:
    """Viajes de progvehiculos de DIA como los devuelve el SELECT de la fuente (idconductor en claro, antes de
    seudonimizar): CRA 54 con dos despachos cancelados a las 12 h; CL 72 con un viaje sin numeropasajeros y sin
    timbradas de segmento a las 14 h (la hora que no llegó)."""
    def v(viaje, ruta, hora, minuto, vehiculo, conductor, cancelada="N", pasajeros=30, segmentos=40):
        salida = datetime.combine(DIA, time(hora, minuto))
        return {"ruta": ruta, "viaje": viaje, "vehiculo": vehiculo, "idconductor": conductor, "salida": salida,
                "salida_real": salida + timedelta(minutes=1), "finalizado": "N" if cancelada == "S" else "S",
                "cancelada": cancelada, "excedeplazosalida": None, "numeropasajeros": pasajeros,
                "filas_segmento": segmentos}
    return pd.DataFrame([v(9001, "CRA 54", 11, 52, "SOBUSA11", 5001), v(9002, "CRA 54", 12, 15, "SOBUSA42", 4242, "S"),
                         v(9003, "CRA 54", 12, 45, "SOBUSA43", 4343, "S"), v(9004, "CRA 54", 13, 5, "SOBUSA44", 4444),
                         v(9100, "CL 72", 13, 40, "SOBUSA6", 6060),
                         v(9101, "CL 72", 14, 20, "SOBUSA7", 7070, pasajeros=None, segmentos=0)])


class FuenteConViajes:
    """Fuente operacional de prueba: el mismo lote siempre (no mueve la marca) y los viajes del día, seudonimizados
    con la misma función que las fuentes reales (fuentes.seudonimizar_viajes)."""

    def __init__(self, df):
        self.df = df
        self.pedidos: list = []

    def leer_incremental(self, marca_agua=None, hasta=None):
        return self.df.copy(), marca_agua

    def procesos(self):
        return pd.DataFrame({"proceso": ["sobusa"], "toleranciatiempo": [0]})

    def viajes(self, ruta, desde, hasta):
        from app.servicios import fuentes

        self.pedidos.append((ruta, desde, hasta))
        d = _viajes_del_dia()
        salida = pd.to_datetime(d["salida"])
        ini, fin = desde.astimezone(Z).replace(tzinfo=None), hasta.astimezone(Z).replace(tzinfo=None)
        d = d[(d["ruta"] == ruta) & (salida >= ini) & (salida < fin)].drop(columns=["ruta"])
        return fuentes.seudonimizar_viajes(d)


@pytest.fixture
def lote_con_viajes(monkeypatch, sesion):
    from app.servicios import datos, ejecucion, inferencia

    monkeypatch.setenv("SEUDONIMO_SECRETO", SECRETO)
    modelo = inferencia.modelo_activo()
    d = datos.demanda_horaria(desde=DIA - timedelta(weeks=8), hasta=DIA).copy()
    hoy = d["fecha"] == DIA
    # CRA 54 sin salidas a las 12 h (ALT-006 por tiempo; sin despacho tampoco hay pasajeros, CONS-002)
    d.loc[hoy & (d["ruta"] == "CRA 54") & (d["hora"] == 12), ["salidas", "pasajeros"]] = 0
    # CL 72 sin la hora 14 (ALT-009 por horas faltantes)
    d = d[~(hoy & (d["ruta"] == "CL 72") & (d["hora"] == 14))].reset_index(drop=True)
    sesion.execute(text(f"DELETE FROM {E}.demanda_observada WHERE ruta = 'CL 72' AND fecha = :f AND hora = 14"),
                   {"f": DIA})
    sesion.commit()
    fuente = FuenteConViajes(d)
    monkeypatch.setattr(ejecucion, "obtener_fuente", lambda: fuente)
    ids: list = []
    try:
        yield SimpleNamespace(modelo=modelo, fuente=fuente, ids=ids)
    finally:
        _limpiar(sesion, ids)


def _alertas(cliente, codigo, ruta):
    r = cliente.get("/api/v1/alerts", params={"codigo": codigo, "ruta": ruta, "limite": 500})
    assert r.status_code == 200, r.text
    return r.json()["items"]


def _local(v):
    return datetime.fromisoformat(str(v).replace("Z", "+00:00")).astimezone(Z)


def test_alt006_y_alt009_llevan_el_viaje_el_vehiculo_y_el_seudonimo_del_conductor(cliente, lote_con_viajes, sesion):
    r = cliente.post("/api/v1/frequency/executions", json={"hasta": str(DIA), "model_id": lote_con_viajes.modelo,
                                                           "notificar": False})
    assert r.status_code == 202, r.text
    eid = r.json()["execution_id"]
    lote_con_viajes.ids.append(uuid.UUID(eid))
    e = cliente.get(f"/api/v1/frequency/executions/{eid}").json()
    assert e["estado"] == "ok", e.get("mensaje")
    assert not [f for f in e["metricas"].get("fallos") or [] if f.get("etapa") == "viajes"]
    assert {ruta for ruta, _d, _h in lote_con_viajes.fuente.pedidos} == {"SILENCIO", "CRA 54", "CL 72"}

    a6 = next(a for a in _alertas(cliente, "ALT-006", "CRA 54")
              if a["ventana_inicio"] and _local(a["ventana_inicio"]).date() == DIA
              and _local(a["ventana_inicio"]).hour <= 12 < _local(a["ventana_fin"]).hour)
    assert (a6["viaje"], a6["vehiculo"], a6["conductor"]) == ("9002", "SOBUSA42", _seudonimo(4242))
    ident = a6["variables"]["identificacion_5_3"]
    assert ident["resultado"] == "identificado" and ident["rol_viaje"] == "cancelado"
    assert ident["aplica"] == ["viaje", "vehiculo", "conductor"] and a6["sentido"] is None
    assert a6["variables"]["viajes_ventana"]["cancelado"] >= 2
    assert a6["variables"]["ultimo_despacho_previo"]["viaje"] == "9001"
    assert "Viaje 9002 (vehículo SOBUSA42), salida programada 12:15" in a6["explicacion"]

    a9 = next(a for a in _alertas(cliente, "ALT-009", "CL 72")
              if str(DIA) in a["clave_dedup"] and a["clave_dedup"].endswith("|faltantes"))
    assert (a9["viaje"], a9["vehiculo"], a9["conductor"]) == ("9101", "SOBUSA7", _seudonimo(7070))
    faltan = a9["variables"]["viajes_con_datos_faltantes"]
    assert faltan["en_horas_faltantes"] == 1 and faltan["lista"][0]["faltantes"] == ["sin_numeropasajeros",
                                                                                     "sin_timbradas_segmento"]
    # §18: en la base solo hay seudónimos (el CHECK los exige) y nunca el identificador en claro
    guardados = dict(sesion.execute(text(f"SELECT viaje, conductor FROM {E}.alert WHERE alert_id IN (:a, :b)"),
                                    {"a": a6["alert_id"], "b": a9["alert_id"]}).all())
    sesion.rollback()
    assert guardados == {"9002": _seudonimo(4242), "9101": _seudonimo(7070)}
    # toda alerta de la ejecución dice qué campos de §5.3 le aplican (las de pronóstico: ninguno de viaje)
    filas = sesion.execute(text(f"SELECT codigo, origen, viaje, variables -> 'identificacion_5_3' AS ident "
                                f"FROM {E}.alert WHERE execution_id = :e"), {"e": eid}).all()
    sesion.rollback()
    assert filas and all(f.ident is not None and f.ident["sentido"].startswith("no aplica") for f in filas)
    assert all(f.ident["aplica"] == [] and f.viaje is None for f in filas if f.origen == "pronostico")
