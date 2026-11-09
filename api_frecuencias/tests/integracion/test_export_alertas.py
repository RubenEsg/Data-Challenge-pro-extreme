"""Integración: exportación de alertas (RF-016/RF-017) con los mismos filtros de GET /api/v1/alerts."""
from __future__ import annotations

import csv
import io
import json
import uuid
from datetime import UTC, datetime, timedelta

# Los campos de §5.3 que la exportación debe traer como columnas (además de las de auditoría).
CAMPOS_5_3 = ["alert_id", "codigo", "execution_id", "empresa", "ruta", "sentido", "viaje", "conductor", "vehiculo",
              "detectada_en", "ventana_inicio", "ventana_fin", "horizonte_min", "severidad", "estado", "observado",
              "esperado", "umbral", "puntaje", "explicacion", "variables", "recomendacion", "asignado_a",
              "comentarios", "clave_dedup", "ocurrencias"]


def _alerta(clave: str, severidad: str, ruta: str, cuando: datetime) -> dict:
    return {"codigo": "ALT-002", "ruta": ruta, "severidad": severidad, "detectada_en": cuando,
            "ventana_inicio": cuando, "ventana_fin": cuando + timedelta(hours=1), "horizonte_min": 60,
            "observado": 0.95, "esperado": 0.85, "umbral": 0.9, "puntaje": 0.7, "explicacion": "exportación",
            "variables": {"ocupacion": 0.95, "nota": "señal"}, "recomendacion": "Despacho adicional",
            "clave_dedup": clave}


def _sembrar(sesion) -> tuple[str, str]:
    from app.servicios import ejecucion

    marca = uuid.uuid4().hex[:8]
    ahora = datetime.now(UTC)
    critica, _ = ejecucion.guardar_alerta(sesion, _alerta(f"EXP|{marca}|c", "critica", "SILENCIO", ahora), None, 1)
    ejecucion.guardar_alerta(sesion, _alerta(f"EXP|{marca}|p", "preventiva", "CL 72", ahora), None, 1)
    sesion.commit()
    return marca, str(critica.alert_id)


def test_exportar_alertas_csv_respeta_filtros(cliente, sesion):
    marca, id_critica = _sembrar(sesion)
    url = f"/api/v1/alerts/{id_critica}/status"
    r = cliente.patch(url, json={"accion": "reconocer", "usuario": "ana", "comentario": "visto en el tablero"})
    assert r.status_code == 200, r.text

    r = cliente.get("/api/v1/alerts/export", params={"formato": "csv", "severidad": "critica", "ruta": "SILENCIO"})
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/csv")
    assert 'filename="alertas_' in r.headers["content-disposition"]
    filas = list(csv.DictReader(io.StringIO(r.content.decode("utf-8-sig"))))
    assert filas, "la exportación filtrada debe traer la alerta crítica sembrada"
    assert all(set(CAMPOS_5_3) <= set(f) for f in filas)
    assert {f["severidad"] for f in filas} == {"critica"} and {f["ruta"] for f in filas} == {"SILENCIO"}
    mia = next(f for f in filas if f["alert_id"] == id_critica)
    assert mia["estado"] == "reconocida"
    # las columnas JSON viajan como JSON válido y sin escapar los acentos
    assert json.loads(mia["variables"])["nota"] == "señal"
    assert json.loads(mia["comentarios"])[0]["comentario"] == "visto en el tablero"

    # el mismo filtro que GET /alerts: los totales coinciden
    filtro = {"severidad": "critica", "ruta": "SILENCIO", "limite": 1}
    total = cliente.get("/api/v1/alerts", params=filtro).json()["total"]
    assert len(filas) == total

    # estado y fechas también filtran; una fecha futura no trae nada
    manana = (datetime.now(UTC) + timedelta(days=2)).date().isoformat()
    vacia = cliente.get("/api/v1/alerts/export", params={"formato": "csv", "desde": manana})
    assert vacia.status_code == 200 and len(vacia.content.decode("utf-8-sig").strip().splitlines()) == 1
    reconocidas = cliente.get("/api/v1/alerts/export", params={"estado": "reconocida", "codigo": "ALT-002"})
    assert reconocidas.status_code == 200
    assert id_critica in reconocidas.content.decode("utf-8-sig")


def test_exportar_alertas_xlsx_y_errores(cliente, sesion):
    import openpyxl

    _sembrar(sesion)
    r = cliente.get("/api/v1/alerts/export", params={"formato": "xlsx", "severidad": "preventiva"})
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("application/vnd.openxmlformats-officedocument.spreadsheetml")
    hoja = openpyxl.load_workbook(io.BytesIO(r.content)).active
    encabezados = [c.value for c in hoja[1]]
    assert set(CAMPOS_5_3) <= set(encabezados) and hoja.max_row >= 2
    col = encabezados.index("severidad")
    assert {fila[col] for fila in hoja.iter_rows(min_row=2, values_only=True)} == {"preventiva"}

    # «export» no se confunde con un alert_id, el formato se valida y el orden también
    assert cliente.get("/api/v1/alerts/export", params={"formato": "pdf"}).status_code == 422
    malo = cliente.get("/api/v1/alerts/export", params={"orden": "no_existe"})
    assert malo.status_code == 422 and malo.json()["error"]["codigo"] == "orden_invalido"
    assert "/api/v1/alerts/export" in cliente.get("/openapi.json").json()["paths"]


def _sembrar_bandeja(sesion, marca: str) -> dict:
    """Tres alertas de una ruta de prueba: una informativa reciente, una crítica vieja y una preventiva intermedia."""
    from app.servicios import ejecucion

    t = datetime.now(UTC)
    ids = {}
    for sev, horas in (("informativa", 0), ("critica", 5), ("preventiva", 2)):
        a, _ = ejecucion.guardar_alerta(sesion, dict(_alerta(f"PRI|{marca}|{sev}", sev, f"PRUEBA_{marca}",
                                                            t - timedelta(hours=horas)), codigo="ALT-004"), None, 1)
        ids[sev] = str(a.alert_id)
    sesion.commit()
    return ids


def test_bandeja_por_prioridad_por_omision(cliente, sesion):
    """§3.1 «priorizar»: GET /alerts ordena por omisión crítica > preventiva > informativa y, dentro de cada una, la
    más reciente primero; orden=-detectada_en sigue disponible."""
    marca = uuid.uuid4().hex[:8]
    ids = _sembrar_bandeja(sesion, marca)
    ruta = f"PRUEBA_{marca}"
    por_omision = cliente.get("/api/v1/alerts", params={"ruta": ruta}).json()
    assert [a["alert_id"] for a in por_omision["items"]] == [ids["critica"], ids["preventiva"], ids["informativa"]]
    explicita = cliente.get("/api/v1/alerts", params={"ruta": ruta, "orden": "prioridad", "limite": 2,
                                                      "desplazamiento": 1}).json()
    assert explicita["total"] == 3 and [a["alert_id"] for a in explicita["items"]] == [ids["preventiva"],
                                                                                      ids["informativa"]]
    por_fecha = cliente.get("/api/v1/alerts", params={"ruta": ruta, "orden": "-detectada_en"}).json()
    assert [a["alert_id"] for a in por_fecha["items"]] == [ids["informativa"], ids["preventiva"], ids["critica"]]
    exportadas = cliente.get("/api/v1/alerts/export", params={"ruta": ruta, "orden": "prioridad"})
    filas = list(csv.DictReader(io.StringIO(exportadas.content.decode("utf-8-sig"))))
    assert [f["alert_id"] for f in filas] == [ids["critica"], ids["preventiva"], ids["informativa"]]


def test_filtro_por_idruta(cliente, sesion):
    """§8.3: idruta filtra por rutas.idruta (columna alert.idruta o, si falta, el nombre que da el catálogo)."""
    from app.servicios import dimensiones

    marca, _ = _sembrar(sesion)
    mapa = dimensiones.mapa_rutas()
    idruta = mapa["SILENCIO"]["idruta"]
    assert idruta is not None
    r = cliente.get("/api/v1/alerts", params={"idruta": idruta, "limite": 500, "orden": "-detectada_en"})
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert items and {a["ruta"] for a in items} == {"SILENCIO"}
    assert any(a["clave_dedup"] == f"EXP|{marca}|c" for a in items)
    otra = [f["idruta"] for n, f in mapa.items() if n != "SILENCIO" and f.get("idruta") is not None][0]
    assert all(a["ruta"] != "SILENCIO" for a in cliente.get("/api/v1/alerts", params={"idruta": otra}).json()["items"])
    assert cliente.get("/api/v1/alerts", params={"idruta": 999_999}).json()["total"] == 0
    assert cliente.get("/api/v1/alerts", params={"idruta": "uno"}).status_code == 422


def test_historial_paginado_y_comentarios_en_bogota(cliente, sesion):
    """§12.1: la bitácora se pagina (limite, desplazamiento, orden, acción; total en X-Total-Count) y los comentarios
    se guardan y se presentan en -05:00 (§8.1)."""
    _, id_critica = _sembrar(sesion)
    url = f"/api/v1/alerts/{id_critica}"
    for texto in ("uno", "dos", "tres"):
        r = cliente.patch(f"{url}/status", json={"accion": "comentar", "comentario": texto, "usuario": "ana"})
        assert r.status_code == 200, r.text
    assert all(c["en"].endswith("-05:00") for c in r.json()["comentarios"])
    from app.modelos_db import Alerta

    sesion.expire_all()
    guardada = sesion.get(Alerta, uuid.UUID(id_critica))
    assert all(c["en"].endswith("-05:00") for c in guardada.comentarios)        # también en el JSON guardado

    completo = cliente.get(f"{url}/history")
    assert completo.headers["X-Total-Count"] == "4"                              # crear + 3 comentarios
    assert [h["accion"] for h in completo.json()] == ["crear", "comentar", "comentar", "comentar"]
    pagina = cliente.get(f"{url}/history", params={"limite": 2, "desplazamiento": 1})
    assert [h["comentario"] for h in pagina.json()] == ["uno", "dos"] and pagina.headers["X-Total-Count"] == "4"
    inversa = cliente.get(f"{url}/history", params={"orden": "-creado_en", "limite": 1}).json()
    assert inversa[0]["comentario"] == "tres"
    solo = cliente.get(f"{url}/history", params={"accion": "comentar"})
    assert solo.headers["X-Total-Count"] == "3" and len(solo.json()) == 3
    assert all(h["creado_en"].endswith("-05:00") for h in completo.json())
    assert cliente.get(f"{url}/history", params={"limite": 0}).status_code == 422
    assert cliente.get(f"{url}/history", params={"orden": "accion"}).status_code == 422
