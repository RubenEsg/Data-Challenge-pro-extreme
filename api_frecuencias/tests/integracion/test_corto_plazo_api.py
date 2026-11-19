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


def test_el_ciclo_genera_el_pronostico_de_corto_plazo(sesion):
    """§7.3 paso 5: el paso del ciclo guarda el pronóstico de cada ruta y horizonte con el execution_id de la
    ejecución, y omite sin fallar un instante fuera de la cobertura del modelo."""
    import uuid
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from app.servicios import ejecucion

    bogota = ZoneInfo("America/Bogota")
    c = type("Ciclo", (), {})()
    c.horizontes, c.fallos, c.metricas, c.execution_id = [30, 60], [], {}, uuid.uuid4()
    ejecucion._pronostico_corto_plazo(sesion, c, ["SILENCIO"], datetime(2025, 9, 16, 6, tzinfo=bogota))
    nuevos = [f for f in sesion.new if isinstance(f, PrediccionCortoPlazo)]
    assert c.fallos == [] and c.metricas["corto_plazo"]["pronosticos"] == 2
    assert len(nuevos) == 2 * (1 + 2 + 135) and {f.execution_id for f in nuevos} == {c.execution_id}
    assert {f.horizonte_min for f in nuevos} == {30, 60} and len({f.grupo_id for f in nuevos}) == 2
    sesion.rollback()
    c.fallos, c.metricas = [], {}
    ejecucion._pronostico_corto_plazo(sesion, c, ["SILENCIO"], datetime(2026, 3, 2, 6, tzinfo=bogota))
    assert c.fallos == [] and c.metricas["corto_plazo"]["pronosticos"] == 0
    assert len(c.metricas["corto_plazo"]["omitidos"]) == 2
    sesion.rollback()
