"""Respuesta del reto (§20) contra el PostgreSQL local, con la autenticación encendida y el cálculo en la cola (§7.1).

- POST /api/v1/respuesta/calcular: sin clave 401, operador 403, analista 202 con el execution_id de una ejecución de
  tipo «respuesta»; el trabajador calcula con el modelo activo y guarda la foto en ai_frecuencias.respuesta_reto.
- GET /api/v1/respuesta: 200 leído de la foto (sin MILP ni pronóstico en el GET), con la trazabilidad completa; 404
  «sin_calcular» con la pista del POST cuando la foto no existe; sin fecha, el día siguiente al último dato.
- Atención inmediata: las alertas abiertas ahora (críticas primero) y, aparte, las de la fecha consultada.
- §8.1: todo instante en -05:00.
"""
from __future__ import annotations

import re
import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import text

FECHA = "2025-10-15"
INSTANTE = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?")


@pytest.fixture
def auth_activa(cliente, monkeypatch):
    from app.config import obtener_ajustes

    monkeypatch.setattr(obtener_ajustes(), "auth_habilitada", True)
    return cliente


def _clave(claves: dict, rol: str) -> dict:
    return {"X-API-Key": claves[rol]}


def _instantes(valor, camino="$"):
    if isinstance(valor, dict):
        for k, v in valor.items():
            yield from _instantes(v, f"{camino}.{k}")
    elif isinstance(valor, list):
        for v in valor:
            yield from _instantes(v, f"{camino}[]")
    elif isinstance(valor, str):
        m = INSTANTE.fullmatch(valor.strip())
        if m:
            yield camino, valor, m.group(1)


def _calcular(cliente, claves: dict, cuerpo: dict | None) -> dict:
    r = cliente.post("/api/v1/respuesta/calcular", json=cuerpo, headers=_clave(claves, "analista"))
    assert r.status_code == 202, r.text[:500]
    return r.json()


def _alerta(sesion, codigo: str, severidad: str, estado: str, detectada_en: datetime, ruta: str = "CL 72"):
    from app.servicios import ejecucion

    a = {"codigo": codigo, "ruta": ruta, "severidad": severidad, "detectada_en": detectada_en,
         "ventana_inicio": detectada_en, "ventana_fin": detectada_en + timedelta(hours=1), "horizonte_min": 60,
         "observado": 1.0, "esperado": 0.8, "umbral": 0.9, "puntaje": 0.5, "explicacion": f"prueba {codigo}",
         "variables": {}, "recomendacion": "Revisar", "clave_dedup": f"{codigo}|RESPUESTA|{uuid.uuid4()}"}
    fila, _ = ejecucion.guardar_alerta(sesion, a, None, 1)
    fila.estado = estado
    sesion.commit()
    return fila


def test_401_sin_clave_y_403_operador_en_el_calculo(auth_activa, claves_prueba):
    for cabeceras in ({"X-API-Key": ""}, {"X-API-Key": "x" * 43}):
        r = auth_activa.get("/api/v1/respuesta", headers=cabeceras)
        assert r.status_code == 401 and r.json()["error"]["codigo"] == "no_autenticado"
        r = auth_activa.post("/api/v1/respuesta/calcular", json={"fecha": FECHA}, headers=cabeceras)
        assert r.status_code == 401 and r.json()["error"]["codigo"] == "no_autenticado"
    r = auth_activa.post("/api/v1/respuesta/calcular", json={"fecha": FECHA}, headers=_clave(claves_prueba,
                                                                                            "operador"))
    assert r.status_code == 403 and r.json()["error"]["codigo"] == "prohibido"


def test_post_202_en_la_cola_y_get_200_desde_la_foto(auth_activa, claves_prueba, sesion, monkeypatch):
    from app.servicios import respuesta

    cuerpo = _calcular(auth_activa, claves_prueba, {"fecha": FECHA, "rutas": ["SILENCIO"]})
    assert cuerpo["tipo"] == "respuesta" and cuerpo["fecha"] == FECHA and cuerpo["rutas"] == ["SILENCIO"]
    assert cuerpo["consultar_estado"].endswith(cuerpo["execution_id"]) and cuerpo["creado_en"].endswith("-05:00")
    eid = cuerpo["execution_id"]
    e = auth_activa.get(f"/api/v1/frequency/executions/{eid}", headers=_clave(claves_prueba, "analista")).json()
    assert e["tipo"] == "respuesta" and e["estado"] == "ok", e        # TestClient corre la tarea antes de volver

    def _prohibido(*_a, **_k):
        raise AssertionError("GET /respuesta no debe pronosticar ni resolver el MILP")

    monkeypatch.setattr(respuesta, "_bloque_ruta", _prohibido)
    monkeypatch.setattr(respuesta, "componer", _prohibido)
    for rol in ("operador", "analista", "admin"):
        r = auth_activa.get("/api/v1/respuesta", params={"ruta": "SILENCIO", "fecha": FECHA},
                            headers=_clave(claves_prueba, rol))
        assert r.status_code == 200, (rol, r.text[:300])
    datos = r.json()
    assert datos["pregunta"].startswith("con los datos históricos y recientes, ¿cada cuánto despachar buses")
    assert datos["fecha"] == FECHA and datos["tipo_dia"] == "Laboral" and r.headers["X-Correlation-Id"]
    traz = datos["trazabilidad"]
    assert traz["execution_id"] == eid and traz["model_id"] and traz["feature_version"] and traz["data_cutoff"]
    assert traz["calibracion_version"] and traz["fuente_pronostico"] in ("modelo_activo", "E12")
    assert isinstance(traz["umbrales_version"], int)            # threshold_config sembrado por la migración
    assert any("respuesta_reto" in f for f in traz["fuentes"])
    (ruta,) = datos["rutas"]
    assert ruta["ruta"] == "SILENCIO" and len(ruta["cada_cuanto_despachar"]) == 17
    assert all(z in ("-05:00", "-0500") for _c, _v, z in _instantes(datos)), list(_instantes(datos))
    assert datos["generado_en"].endswith("-05:00") and datos["consultado_en"].endswith("-05:00")
    fila = sesion.execute(text("SELECT model_id, umbrales_version, execution_id, fuente_pronostico, "
                               "calibracion_version, idruta FROM ai_frecuencias.respuesta_reto "
                               "WHERE fecha = :f AND ruta = 'SILENCIO'"), {"f": date.fromisoformat(FECHA)}).one()
    assert (fila.model_id, fila.umbrales_version, str(fila.execution_id)) == (traz["model_id"],
                                                                               traz["umbrales_version"], eid)
    assert fila.fuente_pronostico == traz["fuente_pronostico"] and fila.idruta == 2


def test_404_sin_calcular_con_la_pista(auth_activa, claves_prueba, sesion):
    """Sin foto guardada del día, 404 «sin_calcular» con la pista del POST. La precondición se fija aquí: otras pruebas
    (los ciclos de test_particion_ruta.py hasta el 2025-03-03) dejan la foto del 2025-03-04 con la versión de umbrales
    vigente, y como ninguna prueba deja vigente una versión creada por PUT (restituir_umbrales), al consultar es la
    misma versión."""
    sesion.execute(text("DELETE FROM ai_frecuencias.respuesta_reto WHERE fecha = :f"), {"f": date(2025, 3, 4)})
    sesion.commit()
    clave = _clave(claves_prueba, "operador")
    r = auth_activa.get("/api/v1/respuesta", params={"ruta": "CRA 54", "fecha": "2025-03-04"}, headers=clave)
    assert r.status_code == 404
    error = r.json()["error"]
    assert error["codigo"] == "sin_calcular" and error["correlation_id"]
    assert error["detalle"]["pista"] == "POST /api/v1/respuesta/calcular"
    assert error["detalle"]["rol_requerido"] == "analista"
    assert error["detalle"]["cuerpo_sugerido"] == {"fecha": "2025-03-04", "rutas": ["CRA 54"]}
    assert error["detalle"]["rutas_sin_calcular"] == ["CRA 54"] and isinstance(error["detalle"]["umbrales_version"],
                                                                                int)
    assert auth_activa.get("/api/v1/respuesta/export", params={"fecha": "2025-03-04"},
                           headers=clave).json()["error"]["codigo"] == "sin_calcular"
    r = auth_activa.get("/api/v1/respuesta", params={"ruta": "KRA 99"}, headers=clave)
    assert r.status_code == 422 and any(d["campo"] == "query.ruta" for d in r.json()["error"]["detalle"])


def test_post_fuera_de_los_dias_calculables_404_sin_encolar(auth_activa, claves_prueba, sesion):
    from sqlalchemy import func, select

    from app.modelos_db import Ejecucion
    from app.servicios import respuesta

    antes = sesion.scalar(select(func.count()).select_from(Ejecucion).where(Ejecucion.tipo == "respuesta"))
    primera, ultima = respuesta.rango_calculable(sesion)
    for fecha in ((ultima + timedelta(days=1)).isoformat(), "2030-01-01", (primera - timedelta(days=1)).isoformat()):
        r = auth_activa.post("/api/v1/respuesta/calcular", json={"fecha": fecha}, headers=_clave(claves_prueba,
                                                                                                "analista"))
        assert r.status_code == 404, r.text[:300]
        error = r.json()["error"]
        assert error["codigo"] == "sin_datos" and error["detalle"]["ultima_fecha"] == ultima.isoformat()
    sesion.expire_all()
    assert sesion.scalar(select(func.count()).select_from(Ejecucion).where(Ejecucion.tipo == "respuesta")) == antes


def test_sin_fecha_calcula_y_lee_el_dia_siguiente_al_ultimo_dato(auth_activa, claves_prueba, sesion):
    from app.servicios import respuesta

    esperado = respuesta.fecha_por_omision(sesion)
    cuerpo = _calcular(auth_activa, claves_prueba, {})
    assert cuerpo["fecha"] == esperado.isoformat() and cuerpo["rutas"] == ["SILENCIO", "CRA 54", "CL 72"]
    e = auth_activa.get(f"/api/v1/frequency/executions/{cuerpo['execution_id']}",
                        headers=_clave(claves_prueba, "analista")).json()
    assert e["estado"] == "ok", e
    r = auth_activa.get("/api/v1/respuesta", headers=_clave(claves_prueba, "operador"))
    assert r.status_code == 200, r.text[:300]
    datos = r.json()
    assert datos["fecha"] == esperado.isoformat()
    assert datos["trazabilidad"]["datos_hasta"] == (esperado - timedelta(days=1)).isoformat()
    assert datos["trazabilidad"]["fuente_pronostico"] == "modelo_activo"
    assert [x["ruta"] for x in datos["rutas"]] == ["SILENCIO", "CRA 54", "CL 72"]
    assert [x["idruta"] for x in datos["rutas"]] == [2, 16, 21]


def test_atencion_abiertas_ahora_y_de_la_fecha(auth_activa, claves_prueba, sesion):
    from app.servicios import respuesta

    respuesta.precalcular(sesion, date.fromisoformat(FECHA), ["CL 72"], confirmar=True)   # modo síncrono de prueba
    futuro = datetime.now(UTC) + timedelta(days=1)          # más reciente que cualquier alerta de otras pruebas
    del_dia = datetime(2025, 10, 15, 17, 0, tzinfo=UTC)     # 12:00 en Bogotá del día consultado
    creadas = [_alerta(sesion, "ALT-004", "informativa", "nueva", futuro),
               _alerta(sesion, "ALT-003", "preventiva", "reconocida", futuro),
               _alerta(sesion, "ALT-002", "critica", "asignada", futuro - timedelta(minutes=5)),
               _alerta(sesion, "ALT-001", "critica", "cerrada", futuro),
               _alerta(sesion, "ALT-007", "preventiva", "descartada", futuro),
               _alerta(sesion, "ALT-005", "critica", "cerrada", del_dia)]
    try:
        r = auth_activa.get("/api/v1/respuesta", params={"ruta": "CL 72", "fecha": FECHA},
                            headers=_clave(claves_prueba, "operador"))
        assert r.status_code == 200, r.text[:300]
        ruta = r.json()["rutas"][0]
        lista = ruta["atencion_inmediata"]
        ids = [x["alert_id"] for x in lista]
        cerradas = {str(a.alert_id) for a in creadas[3:]}
        assert str(creadas[2].alert_id) in ids and not cerradas & set(ids)
        rango = [respuesta.ORDEN_SEVERIDAD.get(x["severidad"], 9) for x in lista]
        assert rango == sorted(rango), "las críticas van primero"
        assert all(x["estado"] not in ("cerrada", "descartada") and x["alcance"] == "abierta ahora" for x in lista)
        assert all(x["detectada_en"].endswith("-05:00") for x in lista)
        assert all(x["alcance"] == "detectada en la fecha consultada" for x in ruta["alertas_de_la_fecha"])
        rango_dia = [respuesta.ORDEN_SEVERIDAD.get(x["severidad"], 9) for x in ruta["alertas_de_la_fecha"]]
        assert rango_dia == sorted(rango_dia)
        del_dia = respuesta.alertas_de_la_fecha(sesion, "CL 72", date.fromisoformat(FECHA), limite=500)
        assert str(creadas[2].alert_id) not in {x["alert_id"] for x in del_dia}
        fila = next(x for x in del_dia if x["alert_id"] == str(creadas[5].alert_id))
        assert fila["estado"] == "cerrada" and fila["detectada_en"] == "2025-10-15T12:00:00-05:00"
        resumen = ruta["atencion_resumen"]
        assert resumen["abiertas_ahora"] >= 3 and resumen["de_la_fecha"] >= 1
        assert resumen["consultado_en"].endswith("-05:00") and "Abiertas ahora" in resumen["nota"]
        completas = respuesta.atencion_inmediata(sesion, "CL 72", limite=500)
        mias = [x for x in completas if x["alert_id"] in {str(a.alert_id) for a in creadas[:3]}]
        assert [x["codigo"] for x in mias] == ["ALT-002", "ALT-003", "ALT-004"]
    finally:
        for a in creadas:
            sesion.delete(a)
        sesion.commit()


def test_exportacion_csv_desde_la_foto(auth_activa, claves_prueba, sesion):
    from app.servicios import respuesta

    respuesta.precalcular(sesion, date.fromisoformat(FECHA), ["SILENCIO"], confirmar=True)
    r = auth_activa.get("/api/v1/respuesta/export", params={"formato": "csv", "fecha": FECHA, "ruta": "SILENCIO"},
                        headers=_clave(claves_prueba, "operador"))
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    lineas = r.content.decode("utf-8-sig").strip().splitlines()
    assert len(lineas) == 1 + 17 and "-05:00" in lineas[1] and "SILENCIO" in lineas[1]
    assert "fuente_pronostico" in lineas[0] and "calibracion_version" in lineas[0]


def test_precalcular_reemplaza_la_foto_y_el_post_no_duplica(sesion):
    from app.servicios import ejecucion, respuesta

    f = date.fromisoformat(FECHA)
    respuesta.precalcular(sesion, f, ["CRA 54"], confirmar=True)
    respuesta.precalcular(sesion, f, ["CRA 54"], confirmar=True)
    n = sesion.execute(text("SELECT count(*) FROM ai_frecuencias.respuesta_reto WHERE fecha = :f AND ruta = 'CRA 54' "
                            "GROUP BY model_id, umbrales_version"), {"f": f}).scalars().all()
    assert n and all(x == 1 for x in n)
    pendiente = ejecucion.crear_ejecucion(sesion, "respuesta", {"fecha": "2025-06-02", "rutas": ["CL 72"]}, None)
    try:
        mismo, nueva = respuesta.solicitar_calculo(sesion, date(2025, 6, 2), ["CL 72"], None)
        assert nueva is False and mismo.execution_id == pendiente.execution_id
    finally:
        sesion.delete(pendiente)
        sesion.commit()
