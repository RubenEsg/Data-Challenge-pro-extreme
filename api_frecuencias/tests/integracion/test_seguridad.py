"""§7.2 y RNF-011: matriz 401/403/2xx de TODAS las rutas de /api/v1 por rol, auditoría con el principal y Swagger
restringido por ambiente. La matriz esperada se escribe aquí a mano (desde la especificación), no se copia de
app/seguridad.POLITICA: si alguien cambia un permiso o agrega una escritura sin decidir su rol, esta prueba falla."""
from __future__ import annotations

import os
import re
import subprocess
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from app.modelos_db import HistorialAlerta, Umbral
from tests.evidencia import guardar_evidencia

RAIZ = Path(__file__).resolve().parents[2]
NIVEL = {"operador": 0, "analista": 1, "admin": 2}
# Escrituras y su rol mínimo (§7.2 y contrato de roles). Toda lectura (GET) es de operador en adelante.
ESPERADO_ESCRITURAS = {
    ("PATCH", "/api/v1/alerts/{alert_id}/status"): "operador",
    ("POST", "/api/v1/frequency/executions"): "analista",
    ("POST", "/api/v1/predictions/run"): "analista",
    ("POST", "/api/v1/recommendations/calculate"): "analista",
    ("POST", "/api/v1/respuesta/calcular"): "analista",                  # §7.1: encola el cálculo de la respuesta
    ("POST", "/api/v1/models/train"): "analista",
    ("POST", "/api/v1/models/{model_id}/activate"): "admin",
    ("POST", "/api/v1/models/rollback"): "admin",
    ("PUT", "/api/v1/thresholds"): "admin",
    ("POST", "/api/v1/thresholds/{version}/aprobar"): "admin",           # §5.1: aprobación de una versión de umbrales
    ("PUT", "/api/v1/catalogos/capacidad"): "admin",
}


@pytest.fixture
def auth_activa(cliente, monkeypatch):
    from app.config import obtener_ajustes

    monkeypatch.setattr(obtener_ajustes(), "auth_habilitada", True)
    return cliente


def _rutas_api():
    from app.main import app

    salida = []
    for r in app.routes:
        if getattr(r, "path", "").startswith("/api/v1") and getattr(r, "methods", None):
            for m in sorted(r.methods - {"HEAD", "OPTIONS"}):
                salida.append((m, r.path))
    return sorted(set(salida))


def _concreta(plantilla: str) -> str:
    return re.sub(r"\{([^}]+)\}", lambda m: "M-NO-EXISTE" if m.group(1) == "model_id" else str(uuid.uuid4()),
                  plantilla)


def _pedir(cliente, metodo: str, plantilla: str, clave: str | None):
    cabeceras = {"X-API-Key": clave} if clave is not None else {"X-API-Key": ""}
    url = _concreta(plantilla)
    if metodo == "GET":
        return cliente.request("GET", url, headers=cabeceras)
    # cuerpo inválido a propósito ([] en lugar de objeto): si la autenticación deja pasar, responde 422 sin
    # efectos (no crea ejecuciones ni toca modelos); si no, 401/403 antes de validar.
    return cliente.request(metodo, url, headers=cabeceras, json=[])


def test_toda_escritura_tiene_rol_explicito():
    escrituras = {(m, p) for m, p in _rutas_api() if m != "GET"}
    assert escrituras == set(ESPERADO_ESCRITURAS), "escritura sin rol decidido en la matriz de permisos"


# Degradación prevista (RNF-010): la dependencia de datos no existe en esta máquina (sin réplica ni exportaciones,
# como en GitHub Actions) o no responde. Solo vale si el 503 lleva el error uniforme con uno de estos códigos y la
# operación lo declara en el OpenAPI; cualquier otro 5xx rompe la matriz.
CODIGOS_DEGRADACION = {"catalogo_no_disponible", "fuente_no_disponible", "reparto_no_disponible"}


def _degradacion_declarada(metodo: str, plantilla: str, r) -> bool:
    from app.main import app

    if r.status_code != 503:
        return False
    try:
        codigo = r.json()["error"]["codigo"]
    except (ValueError, KeyError, TypeError):
        return False
    declarados = app.openapi()["paths"][plantilla][metodo.lower()]["responses"]
    return codigo in CODIGOS_DEGRADACION and "503" in declarados


def test_matriz_401_403_2xx_de_cada_ruta_y_rol(auth_activa, claves_prueba):
    rutas = _rutas_api()
    assert len(rutas) >= 20
    filas = []
    for metodo, plantilla in rutas:
        requerido = ESPERADO_ESCRITURAS.get((metodo, plantilla), "operador")
        for etiqueta, clave in (("sin_clave", None), ("clave_invalida", "x" * 43)):
            r = _pedir(auth_activa, metodo, plantilla, clave)
            assert r.status_code == 401, (metodo, plantilla, etiqueta, r.status_code)
            assert r.headers["WWW-Authenticate"] == 'ApiKey header="X-API-Key"'
            cuerpo = r.json()["error"]
            assert cuerpo["codigo"] == "no_autenticado" and cuerpo["correlation_id"]
            filas.append((metodo, plantilla, etiqueta, r.status_code))
        for rol, clave in claves_prueba.items():
            r = _pedir(auth_activa, metodo, plantilla, clave)
            if NIVEL[rol] < NIVEL[requerido]:
                assert r.status_code == 403, (metodo, plantilla, rol, r.status_code, r.text[:200])
                assert r.json()["error"]["codigo"] == "prohibido"
                assert r.json()["error"]["detalle"] == {"rol": rol, "rol_requerido": requerido}
            else:
                assert r.status_code not in (401, 403), (metodo, plantilla, rol, r.status_code, r.text[:200])
                assert r.status_code < 500 or _degradacion_declarada(metodo, plantilla, r), (
                    metodo, plantilla, rol, r.status_code, r.text[:200])
            filas.append((metodo, plantilla, rol, r.status_code))
    lineas = [f"{m:<6} {p:<48} {quien:<15} {estado}" for m, p, quien, estado in filas]
    guardar_evidencia("seguridad/matriz_roles.txt",
                      "método ruta quién → estado HTTP (cuerpo inválido a propósito en escrituras: 422 = pasó "
                      "la autenticación)\n" + "\n".join(lineas) + "\n")


def test_lecturas_200_por_rol_y_metrics_health_publicos(auth_activa, claves_prueba):
    for clave in claves_prueba.values():
        for url in ("/api/v1/alerts", "/api/v1/predictions", "/api/v1/models", "/api/v1/thresholds",
                    "/api/v1/frequency/executions", "/api/v1/recommendations"):
            assert auth_activa.get(url, headers={"X-API-Key": clave}).status_code == 200, url
    assert auth_activa.get("/health", headers={"X-API-Key": ""}).status_code == 200
    assert auth_activa.get("/metrics", headers={"X-API-Key": ""}).status_code == 200


def test_metrics_privado_si_se_configura(auth_activa, claves_prueba, monkeypatch):
    from app.config import obtener_ajustes

    monkeypatch.setattr(obtener_ajustes(), "metricas_publicas", False)
    assert auth_activa.get("/metrics", headers={"X-API-Key": ""}).status_code == 401
    assert auth_activa.get("/metrics", headers={"X-API-Key": claves_prueba["operador"]}).status_code == 200


def test_auditoria_usa_el_principal_y_no_el_cuerpo(auth_activa, claves_prueba, sesion):
    from app.servicios import ejecucion

    ahora = datetime.now(UTC)
    alerta = {"codigo": "ALT-002", "ruta": "SEGURIDAD", "severidad": "critica", "detectada_en": ahora,
              "ventana_inicio": ahora, "ventana_fin": ahora + timedelta(hours=1), "horizonte_min": 60,
              "observado": 0.95, "esperado": 0.85, "umbral": 0.9, "puntaje": 0.7, "explicacion": "prueba",
              "variables": {}, "recomendacion": "Despacho adicional",
              "clave_dedup": f"ALT-002|SEGURIDAD|{uuid.uuid4()}"}
    a, _ = ejecucion.guardar_alerta(sesion, alerta, None, 1)
    sesion.commit()
    r = auth_activa.patch(f"/api/v1/alerts/{a.alert_id}/status", headers={"X-API-Key": claves_prueba["operador"]},
                          json={"accion": "reconocer", "usuario": "suplantador"})
    assert r.status_code == 200 and r.json()["estado"] == "reconocida"
    sesion.expire_all()
    historial = sesion.scalars(select(HistorialAlerta).where(HistorialAlerta.alert_id == a.alert_id)
                               .order_by(HistorialAlerta.creado_en, HistorialAlerta.id)).all()
    assert historial[-1].accion == "reconocer" and historial[-1].usuario == "prueba_operador"
    assert "suplantador" not in [h.usuario for h in historial]

    vigentes = auth_activa.get("/api/v1/thresholds", headers={"X-API-Key": claves_prueba["admin"]}).json()
    nombre, valor = next(iter(vigentes["valores"].items()))
    cuerpo = {"valores": {nombre: valor}, "creado_por": "otro", "motivo": "prueba de auditoría"}
    assert auth_activa.put("/api/v1/thresholds", headers={"X-API-Key": claves_prueba["analista"]},
                           json=cuerpo).status_code == 403
    r = auth_activa.put("/api/v1/thresholds", headers={"X-API-Key": claves_prueba["admin"]}, json=cuerpo)
    assert r.status_code == 200
    sesion.expire_all()
    ultima = sesion.scalar(select(Umbral).where(Umbral.version == r.json()["version"]).limit(1))
    assert ultima.creado_por == "prueba_admin"


def test_la_url_de_la_base_de_pruebas_no_muestra_su_clave(migrada):
    """§7.1 «ningún secreto»: lo que pytest imprime del fixture (repr, en tracebacks y con --showlocals) oculta la
    clave; el valor sigue sirviendo para conectarse."""
    from sqlalchemy.engine import make_url

    url = make_url(str(migrada))
    if url.password:
        assert url.password not in repr(migrada) and "***" in repr(migrada)
    assert url.host in {"localhost", "127.0.0.1", "db", "::1"} and url.database


def test_ninguna_clave_en_claro_en_el_entorno_ni_en_el_log(claves_prueba, caplog):
    assert all(clave not in os.environ["API_KEYS"] for clave in claves_prueba.values())
    from app import seguridad

    assert seguridad.resolver(claves_prueba["analista"]).rol == "analista"
    assert all(clave not in caplog.text for clave in claves_prueba.values())


def _docs_en(entorno: str) -> tuple[int, int]:
    # proceso aparte (la app fija /docs al construirse) y sin el .env local: solo cuenta ENTORNO
    codigo = ("from app import config\n_aj = config.Ajustes(_env_file=None)\nconfig.obtener_ajustes = lambda: _aj\n"
              "from fastapi.testclient import TestClient\nfrom app.main import app\n"
              "c = TestClient(app)\nprint(c.get('/docs').status_code, c.get('/openapi.json').status_code)\n")
    env = {k: v for k, v in os.environ.items() if k != "DOCS_HABILITADOS"}
    env.update(ENTORNO=entorno, PYTHONIOENCODING="utf-8", OTEL_EXPORTADOR="ninguno")
    salida = subprocess.run([sys.executable, "-c", codigo], cwd=RAIZ, env=env, capture_output=True, text=True,
                            timeout=120, check=True)
    docs, openapi = salida.stdout.strip().splitlines()[-1].split()
    return int(docs), int(openapi)


def test_swagger_restringido_por_ambiente():
    assert _docs_en("produccion") == (404, 404)
    assert _docs_en("local") == (200, 200)


def test_openapi_declara_el_esquema_de_seguridad(cliente):
    import json

    spec = cliente.get("/openapi.json").json()
    esquema = spec["components"]["securitySchemes"]["ApiKey"]
    assert {k: esquema[k] for k in ("type", "in", "name")} == {"type": "apiKey", "in": "header", "name": "X-API-Key"}
    assert {"ApiKey": []} in spec["paths"]["/api/v1/alerts"]["get"]["security"]
    assert "security" not in spec["paths"]["/health"]["get"]
    operaciones = []
    for ruta, metodos in sorted(spec["paths"].items()):
        for metodo, op in sorted(metodos.items()):
            if ruta.startswith("/api/v1"):
                assert {"ApiKey": []} in op.get("security", []), (metodo, ruta)   # botón Authorize en todas
                operaciones.append({"metodo": metodo.upper(), "ruta": ruta, "seguridad": op["security"],
                                    "rol_minimo": ESPERADO_ESCRITURAS.get((metodo.upper(), ruta), "operador")})
    guardar_evidencia("seguridad/openapi_seguridad.json", json.dumps(
        {"securitySchemes": spec["components"]["securitySchemes"], "operaciones": operaciones}, ensure_ascii=False,
        indent=1))
