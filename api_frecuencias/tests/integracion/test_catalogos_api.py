"""Integración de /api/v1/catalogos (§3.1 Gestión operacional, §3.2, §8.3, RF-014, RF-016, RF-017) y prueba de §8.1
sobre TODA la API: ningún instante sale sin zona ni en UTC; todos salen en America/Bogota (-05:00).

Base local de pruebas (TEST_DATABASE_NAME); la réplica solo se usa si está arriba, con el rol lector_ia (la URL sale
de scripts.replica_comun.url_rol y nunca se imprime). Nada se escribe en datos/ ni en las tablas de Extreme.
"""
from __future__ import annotations

import io
import json
import re
import warnings
from datetime import date

import pytest
from sqlalchemy import text

from app.servicios import catalogos as C

DIA = {"idruta": 2, "desde": "2025-03-03", "hasta": "2025-03-03"}
HAY_EXPORTACIONES = (C.carpeta_exportaciones() / "progvehiculos.parquet").exists()
requiere_exportaciones = pytest.mark.skipif(not HAY_EXPORTACIONES, reason="sin las exportaciones Parquet del reto")


@pytest.fixture
def archivos(monkeypatch):
    monkeypatch.setenv("CATALOGOS_FUENTE", "archivos")
    monkeypatch.delenv("CATALOGOS_DATABASE_URL", raising=False)
    C.limpiar_cache()
    yield
    C.limpiar_cache()


@pytest.fixture
def replica(monkeypatch):
    try:
        from scripts.replica_comun import url_rol

        url = url_rol("lector_ia")
    except Exception:  # noqa: BLE001
        url = None
    if not url:
        pytest.skip("réplica sin configurar (LECTOR_IA_PASSWORD)")
    try:
        C.FuenteReplica(url).consultar("SELECT 1 AS uno")
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"réplica no disponible: {type(exc).__name__}")
    monkeypatch.setenv("CATALOGOS_DATABASE_URL", url)
    monkeypatch.setenv("CATALOGOS_FUENTE", "replica")
    C.limpiar_cache()
    yield url
    C.limpiar_cache()


@pytest.fixture
def auth_activa(cliente, monkeypatch):
    from app.config import obtener_ajustes

    monkeypatch.setattr(obtener_ajustes(), "auth_habilitada", True)
    return cliente


def _clave(claves, rol):
    return {"X-API-Key": claves[rol]}


# ---------------------------------------------------------------- catálogos offline
@requiere_exportaciones
def test_catalogos_offline_paginados_con_su_fuente(cliente, archivos):
    for ruta, minimo in (("procesos", 1), ("empresas", 1), ("rutas", 3), ("vehiculos", 100),
                         ("segmentos?geometria=ninguna", 100)):
        r = cliente.get(f"/api/v1/catalogos/{ruta}")
        assert r.status_code == 200, (ruta, r.text)
        cuerpo = r.json()
        assert cuerpo["fuente"] == "archivos" and cuerpo["total"] >= minimo and cuerpo["consultado_en"].endswith(
            "-05:00")
        assert set(cuerpo) == {"total", "limite", "desplazamiento", "fuente", "consultado_en", "items"}
    rutas = cliente.get("/api/v1/catalogos/rutas").json()["items"]
    assert {x["idruta"] for x in rutas} == {2, 16, 21}
    assert all(x["capacidad_vigente"] > 0 and x["tiempo_ciclo_min"] > 0 and x["flota"] > 0 for x in rutas)
    assert all("cap_min_autorizada" in x and "frecuenciadespachos" in x for x in rutas)
    detalle = cliente.get("/api/v1/catalogos/rutas/2").json()
    assert detalle["ruta"] == "SILENCIO" and len(detalle["parametros_por_hora"]) > 10
    assert cliente.get("/api/v1/catalogos/rutas/999").status_code == 404
    seg = cliente.get("/api/v1/catalogos/segmentos", params={"idruta": 2, "limite": 3, "orden": "nro_segmento"}).json()
    assert seg["items"][0]["geometria"]["type"] == "LineString" and seg["items"][0]["longitud_m"] > 0
    assert seg["items"][0]["vertices"] < seg["items"][0]["vertices_original"]
    completa = cliente.get("/api/v1/catalogos/segmentos", params={"idruta": 2, "limite": 1, "geometria": "completa",
                                                                  "orden": "nro_segmento"}).json()["items"][0]
    assert completa["id"] == seg["items"][0]["id"] and completa["vertices"] == completa["vertices_original"] > 100
    for malo in ({"idruta": 10**30}, {"nro_desde": -1}, {"idvehiculo": "x' OR 1=1"}, {"geometria": "otra"}):
        assert cliente.get("/api/v1/catalogos/segmentos" if "idvehiculo" not in malo else
                           "/api/v1/catalogos/viajes", params=malo).status_code == 422, malo
    veh = cliente.get("/api/v1/catalogos/vehiculos", params={"idruta": 2, "limite": 500}).json()
    assert veh["total"] > 10 and not any(set(v) & C.COLUMNAS_PROHIBIDAS for v in veh["items"])
    tip = cliente.get("/api/v1/catalogos/vehiculos/tipologias", params={"idruta": 2}).json()
    assert tip and all(t["capacidad_mediana"] > 0 for t in tip)


@requiere_exportaciones
def test_viajes_y_despachos_filtros_orden_paginacion_y_exportacion(cliente, archivos):
    r = cliente.get("/api/v1/catalogos/viajes", params={**DIA, "limite": 5})
    assert r.status_code == 200
    viajes = r.json()
    assert viajes["total"] > 20 and len(viajes["items"]) == 5
    horas = [v["hora_programada"] for v in viajes["items"]]
    assert horas == sorted(horas) and all(h.startswith("2025-03-03T") and h.endswith("-05:00") for h in horas)
    desc = cliente.get("/api/v1/catalogos/viajes", params={**DIA, "limite": 1, "orden": "-hora_programada"}).json()
    assert desc["items"][0]["hora_programada"] >= horas[-1]
    despachos = cliente.get("/api/v1/catalogos/despachos", params={**DIA, "limite": 500}).json()
    assert 0 < despachos["total"] <= viajes["total"]
    assert all(d["salida_real"].endswith("-05:00") for d in despachos["items"])
    csv = cliente.get("/api/v1/catalogos/viajes/export", params={**DIA, "formato": "csv"})
    assert csv.status_code == 200 and csv.headers["content-type"].startswith("text/csv")
    lineas = csv.content.decode("utf-8-sig").strip().splitlines()
    assert len(lineas) == viajes["total"] + 1 and "-05:00" in lineas[1]
    xlsx = cliente.get("/api/v1/catalogos/despachos/export", params={**DIA, "formato": "xlsx"})
    assert xlsx.status_code == 200 and xlsx.content[:2] == b"PK"
    import pandas as pd

    hoja = pd.read_excel(io.BytesIO(xlsx.content))
    assert len(hoja) == despachos["total"] and "placa" not in hoja.columns
    for params, codigo in (({"orden": "placa"}, "filtro_invalido"), ({"desde": "2025-03-05", "hasta": "2025-03-01"},
                                                                      "filtro_invalido")):
        malo = cliente.get("/api/v1/catalogos/viajes", params=params)
        assert malo.status_code == 422 and malo.json()["error"]["codigo"] == codigo


# ---------------------------------------------------------------- máquina limpia (CI, jurado): degradación declarada
@pytest.fixture
def sin_fuentes(monkeypatch, tmp_path):
    """Como en GitHub Actions o en la máquina de un jurado: sin réplica, sin las exportaciones Parquet de la raíz y sin
    el reporte de flota. Solo queda el catálogo empaquetado de la API (datos/catalogo_rutas.json)."""
    vacia = tmp_path / "exportaciones_vacias"
    vacia.mkdir()
    monkeypatch.setenv("CATALOGOS_FUENTE", "archivos")
    monkeypatch.setenv("CATALOGOS_DATOS_DIR", str(vacia))
    monkeypatch.setenv("CATALOGOS_FLOTA_CSV", str(tmp_path / "sin_flota.csv"))
    monkeypatch.delenv("CATALOGOS_DATABASE_URL", raising=False)
    C.limpiar_cache()
    yield
    C.limpiar_cache()


def _rutas_get_de_catalogos() -> list[str]:
    from fastapi.routing import APIRoute

    from app.main import app

    return sorted(r.path for r in app.routes if isinstance(r, APIRoute) and "GET" in r.methods
                  and r.path.startswith("/api/v1/catalogos"))


def test_sin_replica_ni_exportaciones_cada_catalogo_responde_200_o_503_declarado(cliente, sin_fuentes):
    """Ningún catálogo da 500 ni rompe su modelo de respuesta con solo los datos empaquetados: responde 200 con el
    catálogo de la API (rutas, capacidad) o 503 «catalogo_no_disponible» con la razón, declarado en el OpenAPI."""
    from app.main import app

    doc, estados = app.openapi(), {}
    for plantilla in _rutas_get_de_catalogos():
        params = {"formato": "csv"} if plantilla.endswith("/export") else {}
        r = cliente.get(plantilla.replace("{idruta}", "2"), params=params)
        estados[plantilla] = r.status_code
        assert r.status_code in (200, 503), (plantilla, r.status_code, r.text[:300])
        if r.status_code == 503:
            error = r.json()["error"]
            assert error["codigo"] == "catalogo_no_disponible" and "CATALOGOS_" in error["mensaje"], error
            assert "503" in doc["paths"][plantilla]["get"]["responses"], plantilla
    con_paquete = ("/api/v1/catalogos", "/api/v1/catalogos/rutas", "/api/v1/catalogos/rutas/{idruta}",
                   "/api/v1/catalogos/rutas/export", "/api/v1/catalogos/capacidad",
                   "/api/v1/catalogos/capacidad/historial", "/api/v1/catalogos/flota",
                   "/api/v1/catalogos/flota/historial")
    assert {p: estados[p] for p in con_paquete} == dict.fromkeys(con_paquete, 200)
    sin_exportacion = ("/api/v1/catalogos/despachos", "/api/v1/catalogos/viajes", "/api/v1/catalogos/segmentos",
                       "/api/v1/catalogos/vehiculos", "/api/v1/catalogos/procesos", "/api/v1/catalogos/empresas")
    assert {p: estados[p] for p in sin_exportacion} == dict.fromkeys(sin_exportacion, 503)
    rutas = cliente.get("/api/v1/catalogos/rutas").json()
    assert rutas["fuente"] == "archivos_api" and {x["idruta"] for x in rutas["items"]} == {2, 16, 21}
    assert all(isinstance(x["flotadisp_prog"], str) and x["capacidad_vigente"] > 0 for x in rutas["items"])


def test_replica_configurada_pero_caida_responde_503_y_no_500(cliente, monkeypatch):
    """RNF-010: con la réplica configurada e inalcanzable (puerto cerrado), el catálogo responde 503
    «fuente_no_disponible» desde la primera petición, antes de que el circuito se abra."""
    from app.servicios import circuito

    monkeypatch.setattr(circuito, "_registro", {})        # circuito propio: no altera el de las otras pruebas
    monkeypatch.setenv("CATALOGOS_FUENTE", "replica")
    monkeypatch.setenv("CATALOGOS_DATABASE_URL", "postgresql+psycopg://lector_ia@127.0.0.1:1/operacional")
    C.limpiar_cache()
    try:
        for ruta in ("/api/v1/catalogos/rutas", "/api/v1/catalogos/despachos"):
            r = cliente.get(ruta)
            assert r.status_code == 503, (ruta, r.status_code, r.text[:300])
            assert r.json()["error"]["codigo"] == "fuente_no_disponible"
            assert r.json()["error"]["detalle"]["integracion"] == "fuente_postgres"
    finally:
        C.limpiar_cache()


# ---------------------------------------------------------------- roles (§7.2)
def test_roles_en_catalogos(auth_activa, claves_prueba, umbrales_restituidos):
    c = auth_activa
    assert c.get("/api/v1/catalogos/rutas", headers={"X-API-Key": ""}).status_code == 401
    for rol in ("operador", "analista", "admin"):
        assert c.get("/api/v1/catalogos/rutas", headers=_clave(claves_prueba, rol)).status_code == 200
        assert c.get("/api/v1/catalogos/capacidad", headers=_clave(claves_prueba, rol)).status_code == 200
    cuerpo = {"idruta": 21, "tipologia": "TODAS", "capacidad": 48, "motivo": "prueba de roles"}
    for rol in ("operador", "analista"):
        r = c.put("/api/v1/catalogos/capacidad", json=cuerpo, headers=_clave(claves_prueba, rol))
        assert r.status_code == 403 and r.json()["error"]["detalle"]["rol_requerido"] == "admin"
    ok = c.put("/api/v1/catalogos/capacidad", json=cuerpo, headers=_clave(claves_prueba, "admin"))
    assert ok.status_code == 200 and ok.json()["capacidad"] == 48
    retiro = c.put("/api/v1/catalogos/capacidad", json={**cuerpo, "capacidad": None, "motivo": "fin de la prueba"},
                   headers=_clave(claves_prueba, "admin"))
    assert retiro.status_code == 200 and retiro.json()["fuente"] == "catalogo"


# ---------------------------------------------------------------- ajuste local versionado (§3.2, §8.3)
def test_ajuste_de_capacidad_versionado_auditado_y_leido_por_el_optimizador(auth_activa, claves_prueba, sesion,
                                                                            umbrales_restituidos):
    """El retiro del final es parte de lo que se prueba (la capacidad vuelve a la del catálogo); umbrales_restituidos
    borra después todas las versiones que creó la prueba."""
    from app.servicios import optimizacion

    c, admin = auth_activa, _clave(claves_prueba, "admin")
    antes = c.get("/api/v1/thresholds", headers=admin).json()
    try:
        r1 = c.put("/api/v1/catalogos/capacidad", headers=admin,
                   json={"idruta": 2, "capacidad": 40, "motivo": "Flota mixta en SILENCIO",
                         "creado_por": "suplantador"})
        assert r1.status_code == 200, r1.text
        assert (r1.json()["capacidad"], r1.json()["fuente"]) == (40, "ajuste_local")
        assert r1.json()["umbrales_version"] == antes["version"] + 1
        r2 = c.put("/api/v1/catalogos/capacidad", headers=admin,
                   json={"idruta": 2, "tipologia": "buseta", "capacidad": 30, "motivo": "Busetas de 30 puestos"})
        assert r2.status_code == 200 and r2.json()["por_tipologia"] == {"BUSETA": 30, "TODAS": 40}
        assert c.get("/api/v1/catalogos/capacidad", params={"idruta": 2, "tipologia": "BUSETA"},
                     headers=admin).json()[0]["capacidad"] == 30
        assert c.get("/api/v1/catalogos/rutas/2", headers=admin).json()["capacidad_vigente"] == 40
        # el conjunto gobernado sigue íntegro: los demás umbrales no cambian y un PUT /thresholds conserva el ajuste
        despues = c.get("/api/v1/thresholds", headers=admin).json()
        assert {k: v for k, v in despues["valores"].items() if not k.startswith("capacidad_override.")} == \
            antes["valores"]
        mismo = {"ocupacion_objetivo_max": antes["valores"]["ocupacion_objetivo_max"]}
        assert c.put("/api/v1/thresholds", headers=admin, json={"valores": mismo, "creado_por": "x",
                                                               "motivo": "sin cambio"}).status_code == 200
        # contrato del optimizador: lee la capacidad vigente y recomienda con ella
        sesion.expire_all()
        cv = C.capacidad_vigente("SILENCIO", sesion=sesion)
        assert (cv["capacidad"], cv["fuente"], cv["umbrales_version"]) == (40, "ajuste_local", antes["version"] + 3)
        con_ajuste = optimizacion.recomendar("SILENCIO", 7, demanda_hora=900, capacidad=cv["capacidad"])
        sin_ajuste = optimizacion.recomendar("SILENCIO", 7, demanda_hora=900, capacidad=cv["capacidad_catalogo"])
        assert con_ajuste["buses_hora"] > sin_ajuste["buses_hora"]
        # validaciones e integridad referencial hacia rutas autorizadas
        for cuerpo, estado in (({"idruta": 999, "capacidad": 40, "motivo": "ruta inexistente"}, 422),
                               ({"idruta": 2, "capacidad": 0, "motivo": "cero"}, 422),
                               ({"idruta": 2, "capacidad": 40, "motivo": ""}, 422),
                               ({"idruta": 2, "tipologia": "BUS;DROP", "capacidad": 40, "motivo": "inyección"}, 422),
                               ({"idruta": 2, "tipologia": "BUS", "capacidad": None, "motivo": "no existe"}, 404)):
            assert c.put("/api/v1/catalogos/capacidad", headers=admin, json=cuerpo).status_code == estado, cuerpo
        retiro = c.put("/api/v1/catalogos/capacidad", headers=admin,
                       json={"idruta": 2, "tipologia": "BUSETA", "capacidad": None, "motivo": "Busetas retiradas"})
        assert retiro.status_code == 200 and retiro.json()["por_tipologia"] == {"TODAS": 40}
        historial = c.get("/api/v1/catalogos/capacidad/historial", params={"idruta": 2}, headers=admin).json()
        acciones = [(e["tipologia"], e["accion"], e["capacidad_anterior"], e["capacidad_nueva"]) for e in historial]
        assert acciones[:3] == [("BUSETA", "retirado", 30, None), ("BUSETA", "creado", None, 30),
                                ("TODAS", "creado", None, 40)]
        assert {e["creado_por"] for e in historial[:3]} == {"prueba_admin"}        # el cuerpo no suplanta
        assert historial[2]["motivo"] == "Flota mixta en SILENCIO" and historial[0]["creado_en"].endswith("-05:00")
        pagina = c.get("/api/v1/catalogos/capacidad/historial", params={"idruta": 2, "limite": 1, "desplazamiento": 1},
                       headers=admin)
        assert pagina.status_code == 200 and pagina.json() == historial[1:2]          # paginado, mismo orden
        assert int(pagina.headers["X-Total-Count"]) == len(historial)
        assert c.get("/api/v1/catalogos/capacidad/historial", params={"limite": 0}, headers=admin).status_code == 422
        # vive solo en ai_frecuencias
        n = sesion.execute(text("SELECT count(*) FROM ai_frecuencias.threshold_config "
                                "WHERE vigente AND nombre LIKE 'capacidad_override.%'")).scalar()
        assert n == 1
    finally:
        c.put("/api/v1/catalogos/capacidad", headers=admin,
              json={"idruta": 2, "capacidad": None, "motivo": "limpieza de la prueba"})
    assert C.capacidad_vigente("SILENCIO", sesion=sesion)["fuente"] == "catalogo"


# ---------------------------------------------------------------- réplica (lector_ia, READ ONLY)
def test_catalogos_desde_la_replica_con_lector_ia_en_solo_lectura(cliente, replica, monkeypatch):
    sesion_replica = C.FuenteReplica(replica).consultar(
        "SELECT current_user AS usuario, current_setting('transaction_read_only') AS solo_lectura, "
        "current_setting('TimeZone') AS zona")
    assert sesion_replica.to_dict("records") == [{"usuario": "lector_ia", "solo_lectura": "on",
                                                  "zona": "America/Bogota"}]
    for ruta in ("procesos", "empresas", "rutas", "vehiculos", "segmentos?idruta=2&limite=2", "viajes", "despachos"):
        r = cliente.get(f"/api/v1/catalogos/{ruta}")
        assert r.status_code == 200 and r.json()["fuente"] == "replica", (ruta, r.text[:200])
    seg = cliente.get("/api/v1/catalogos/segmentos", params={"idruta": 2, "limite": 2}).json()["items"][0]
    assert seg["geometria"]["type"] == "LineString" and seg["vertices"] < seg["vertices_original"]
    viajes = cliente.get("/api/v1/catalogos/viajes", params={**DIA, "limite": 500}).json()
    assert viajes["total"] > 20
    assert not any(set(v) & C.COLUMNAS_PROHIBIDAS for v in
                   cliente.get("/api/v1/catalogos/vehiculos", params={"limite": 500}).json()["items"])
    if HAY_EXPORTACIONES:                       # misma respuesta que las exportaciones: la réplica es fiel
        monkeypatch.setenv("CATALOGOS_FUENTE", "archivos")
        offline, n, fuente = C.programacion("viajes", idruta=2, desde=date(2025, 3, 3), hasta=date(2025, 3, 3),
                                            limite=500)
        assert fuente == "archivos" and n == viajes["total"]
        assert [int(x) for x in offline["idprogramacion"]] == [v["idprogramacion"] for v in viajes["items"]]



# ---------------------------------------------------------------- §8.1 en TODA la API
INSTANTE = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?")
BOGOTA = ("-05:00", "-0500")
# Campos con hallazgos conocidos, por (ruta, campo). Vacío: la prueba es estricta y cualquier campo o ruta que devuelva
# un instante sin zona o en otra zona la rompe (los JSONB se presentan en Bogotá con app.esquemas.bogota_profundo).
PENDIENTES_AJENOS: dict[tuple[str, str], str] = {}
# Valores para los parámetros obligatorios de consulta que piden algunas rutas (si responden 422 sin ellos).
PARAMETROS_TIPICOS = {"ruta": "SILENCIO", "idruta": 2, "fecha": "2025-01-15", "desde": "2025-01-01",
                      "hasta": "2025-01-31", "hora": 7, "horizonte_min": 60, "instante": "2025-01-15T07:00:00-05:00",
                      "formato": "csv"}


def _faltantes(respuesta) -> list[str]:
    try:
        detalle = respuesta.json()["error"]["detalle"] or []
    except (ValueError, KeyError, TypeError):
        return []
    return [d["campo"].split(".", 1)[1] for d in detalle
            if isinstance(d, dict) and str(d.get("campo", "")).startswith("query.") and d.get("tipo") == "missing"]


def _instantes_malos(valor, camino="$"):
    """(campo, valor) de cada valor que ES un instante (no prosa que lo mencione) sin zona o fuera de Bogotá."""
    if isinstance(valor, dict):
        for k, v in valor.items():
            yield from _instantes_malos(v, f"{camino}.{k}")
    elif isinstance(valor, list):
        for v in valor[:200]:
            yield from _instantes_malos(v, f"{camino}[]")
    elif isinstance(valor, str):
        texto = valor.strip()
        m = INSTANTE.fullmatch(texto)
        if m and m.group(1) not in BOGOTA:
            yield camino, texto
        elif texto[:1] in "[{":                         # JSON dentro de una celda de CSV
            try:
                yield from _instantes_malos(json.loads(texto), camino)
            except ValueError:
                pass


def _instantes_malos_csv(contenido: bytes):
    import csv

    for fila in csv.DictReader(io.StringIO(contenido.decode("utf-8-sig", "replace"))):
        for columna, celda in fila.items():
            yield from _instantes_malos(celda or "", f"csv:{columna}")


def test_unidad_del_detector_de_instantes():
    assert list(_instantes_malos({"a": "2025-01-02T06:00:00-05:00", "b": "2025-01-02", "c": "04:40:00"})) == []
    malos = dict(_instantes_malos({"a": "2025-01-02T11:00:00+00:00", "b": ["2025-01-02 06:00"], "c": "2025-01-02Z",
                                   "d": "Faltan las horas 2025-01-02 06:00 y 07:00", "e": "2025-01-02T11:00:00Z"}))
    assert malos == {"$.a": "2025-01-02T11:00:00+00:00", "$.b[]": "2025-01-02 06:00", "$.e": "2025-01-02T11:00:00Z"}
    assert list(_instantes_malos_csv(b'x,y\n2025-01-02T06:00:00-05:00,"[{""en"": ""2025-01-02T11:00:00+00:00""}]"\n'))\
        == [("csv:y[].en", "2025-01-02T11:00:00+00:00")]


def _primero(cliente, ruta, campo):
    r = cliente.get(ruta)
    if r.status_code != 200:
        return None
    cuerpo = r.json()
    items = cuerpo.get("items", []) if isinstance(cuerpo, dict) else cuerpo
    return items[0].get(campo) if items and isinstance(items[0], dict) else None


def test_toda_la_api_presenta_los_instantes_en_bogota(cliente, archivos):
    """§8.1 y §12.1: recorre todas las rutas GET de /api/v1 (las de otros equipos incluidas) y falla si alguna
    devuelve un instante sin zona o con otra zona (UTC, Z, +00:00), salvo los pendientes ajenos ya informados."""
    from fastapi.routing import APIRoute

    from app.main import app

    if not cliente.get("/api/v1/frequency/executions").json().get("total"):
        r = cliente.post("/api/v1/frequency/executions", json={"hasta": "2025-01-15", "rutas": ["SILENCIO"],
                                                               "horizontes": [60], "notificar": False})
        assert r.status_code in (200, 201, 202), r.text
    ids = {"execution_id": _primero(cliente, "/api/v1/frequency/executions", "execution_id"),
           "model_id": _primero(cliente, "/api/v1/models", "model_id"),
           "alert_id": _primero(cliente, "/api/v1/alerts", "alert_id"),
           "prediction_id": _primero(cliente, "/api/v1/predictions", "prediction_id"),
           "recommendation_id": _primero(cliente, "/api/v1/recommendations", "recommendation_id"),
           "idruta": 2}
    verificadas, omitidas, hallazgos = [], [], {}
    for ruta in app.routes:
        if not isinstance(ruta, APIRoute) or "GET" not in ruta.methods or not ruta.path.startswith("/api/v1"):
            continue
        nombres = re.findall(r"{(\w+)}", ruta.path)
        if any(ids.get(n) is None for n in nombres):
            omitidas.append((ruta.path, "sin id"))
            continue
        url = ruta.path.format(**{n: ids[n] for n in nombres})
        params = {"formato": "csv"} if ruta.path.endswith("/export") else {}
        if "/catalogos/segmentos" in ruta.path:
            params["geometria"] = "ninguna"
        r = cliente.get(url, params=params)
        faltan = _faltantes(r) if r.status_code == 422 else []
        if faltan and all(n in PARAMETROS_TIPICOS for n in faltan):
            r = cliente.get(url, params={**params, **{n: PARAMETROS_TIPICOS[n] for n in faltan}})
        if r.status_code != 200:
            omitidas.append((ruta.path, r.status_code))
            continue
        tipo = r.headers.get("content-type", "")
        if "json" in tipo:
            encontrados = list(_instantes_malos(r.json()))
        elif "csv" in tipo:
            encontrados = list(_instantes_malos_csv(r.content))
        else:
            omitidas.append((ruta.path, tipo))
            continue
        verificadas.append(ruta.path)
        for campo, valor in encontrados:
            hallazgos.setdefault((ruta.path, campo), valor)
    nuevos = {f"{r} {c}": v for (r, c), v in hallazgos.items() if (r, c) not in PENDIENTES_AJENOS}
    resueltos = [k for k in PENDIENTES_AJENOS if k[0] in verificadas and k not in hallazgos]
    if resueltos:
        warnings.warn(f"Sin hallazgo en esta corrida (si ya se corrigió, quítelo de PENDIENTES_AJENOS): {resueltos}",
                      stacklevel=1)
    print(json.dumps({"verificadas": len(verificadas), "rutas_verificadas": verificadas, "omitidas": omitidas,
                      "hallazgos": {f"{r} {c}": v for (r, c), v in hallazgos.items()},
                      "pendientes_ajenos": {f"{r} {c}": d for (r, c), d in PENDIENTES_AJENOS.items()}},
                     ensure_ascii=False, default=str))
    assert len(verificadas) >= 15, (verificadas, omitidas)
    assert not [r for r in verificadas if "/catalogos" in r and any(k.startswith(r + " ") for k in nuevos)]
    assert not nuevos, f"Instantes sin zona o fuera de America/Bogota (§8.1): {nuevos}"
