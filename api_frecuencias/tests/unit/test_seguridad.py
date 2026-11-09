"""Unitarias de app/seguridad.py: carga de claves (solo hashes), resolución, matriz de permisos y auditoría."""
import hashlib
import json
import secrets

import pytest

from app import seguridad as S
from app.config import Ajustes


def _h(clave: str) -> str:
    return hashlib.sha256(clave.encode()).hexdigest()


def test_carga_api_keys_json_de_hashes_y_por_rol():
    k1, k2 = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    env = {"API_KEYS": json.dumps({_h(k1): {"usuario": "ana", "rol": "analista"}}), "API_KEY_ADMIN": k2}
    claves = S.cargar_claves(env)
    assert claves[_h(k1)] == S.Principal("ana", "analista")
    assert claves[_h(k2)] == S.Principal("admin", "admin")
    assert k1 not in json.dumps({h: p.__dict__ for h, p in claves.items()})      # solo hashes en memoria
    assert S.resolver(k1, claves).usuario == "ana"
    assert S.resolver(k2, claves).rol == "admin"
    assert S.resolver("otra-clave-cualquiera", claves) is None
    assert S.resolver(None, claves) is None and S.resolver("", claves) is None


@pytest.mark.parametrize("crudo", ["no es json", "[1, 2]",
                                   json.dumps({"abc": {"usuario": "x", "rol": "admin"}}),
                                   json.dumps({"a" * 64: {"usuario": "x", "rol": "superusuario"}}),
                                   json.dumps({"b" * 64: {"usuario": "", "rol": "admin"}})])
def test_entradas_invalidas_se_ignoran_sin_filtrar_secretos(crudo, caplog):
    assert S.cargar_claves({"API_KEYS": crudo}) == {}


def test_clave_por_rol_demasiado_corta_se_ignora():
    assert S.cargar_claves({"API_KEY_OPERADOR": "corta"}) == {}


@pytest.mark.parametrize("metodo,ruta,rol", [
    ("GET", "/api/v1/alerts", "operador"),
    ("GET", "/api/v1/models/{model_id}", "operador"),
    ("PATCH", "/api/v1/alerts/{alert_id}/status", "operador"),
    ("POST", "/api/v1/frequency/executions", "analista"),
    ("POST", "/api/v1/predictions/run", "analista"),
    ("POST", "/api/v1/recommendations/calculate", "analista"),
    ("POST", "/api/v1/models/train", "analista"),
    ("POST", "/api/v1/models/{model_id}/activate", "admin"),
    ("POST", "/api/v1/models/rollback", "admin"),
    ("PUT", "/api/v1/thresholds", "admin"),
    ("DELETE", "/api/v1/alerts/{alert_id}", "admin"),          # escritura no listada: denegación por omisión
    ("POST", "/api/v1/nueva_escritura", "admin"),
])
def test_matriz_de_permisos(metodo, ruta, rol):
    assert S.rol_requerido(metodo, ruta) == rol
    assert S.rol_requerido(metodo, ruta.removeprefix("/api/v1")) == rol


def test_usuario_de_auditoria_es_el_principal():
    assert S.usuario_auditoria(S.Principal("ana", "operador"), "suplantador") == "ana"
    assert S.usuario_auditoria(S.ANONIMO, "pedro") == "pedro"          # auth apagada: se respeta lo declarado
    assert S.usuario_auditoria(S.ANONIMO, None) == "anonimo"
    assert S.usuario_auditoria(None, None) == "anonimo"


@pytest.mark.parametrize("entorno,explicito,esperado", [
    ("produccion", None, False), ("local", None, True), ("pruebas", None, True), ("demo", None, True),
    ("produccion", True, True), ("local", False, False)])
def test_swagger_por_ambiente(entorno, explicito, esperado):
    aj = Ajustes(_env_file=None, entorno=entorno, docs_habilitados=explicito)
    rutas = S.rutas_documentacion(aj)
    assert (rutas["docs_url"] == "/docs") is esperado and (rutas["openapi_url"] == "/openapi.json") is esperado
    assert rutas["redoc_url"] is None


def test_autenticacion_por_omision_encendida(monkeypatch):
    for variable in ("AUTH_HABILITADA", "METRICAS_PUBLICAS"):
        monkeypatch.delenv(variable, raising=False)
    aj = Ajustes(_env_file=None)
    assert aj.auth_habilitada is True and aj.metricas_publicas is True
    assert "@" not in repr(aj) and "database_url" not in repr(aj)     # la URL (con su clave) no sale en logs


def test_crear_api_key_entrega_clave_y_solo_el_hash():
    import subprocess
    import sys
    from pathlib import Path

    raiz = Path(__file__).resolve().parents[2]
    salida = subprocess.run([sys.executable, str(raiz / "scripts" / "crear_api_key.py"), "--rol", "analista",
                             "--usuario", "ana"], capture_output=True, text=True, check=True, timeout=60,
                            env={"PYTHONIOENCODING": "utf-8", "SYSTEMROOT": __import__("os").environ.get(
                                "SYSTEMROOT", "")}, encoding="utf-8").stdout.splitlines()
    clave = salida[1].strip()
    entrada = salida[-1].strip()
    assert len(clave) >= 43 and clave not in entrada
    claves = S.cargar_claves({"API_KEYS": entrada})
    assert S.resolver(clave, claves) == S.Principal("ana", "analista")


def test_dependencia_401_403_y_principal(monkeypatch):
    """La dependencia sin servidor: request falso con la plantilla de la ruta, como la deja FastAPI."""
    import asyncio
    from types import SimpleNamespace

    from app.routers.comun import ErrorApi

    clave_op, clave_admin = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    monkeypatch.setenv("API_KEYS", json.dumps({_h(clave_op): {"usuario": "olga", "rol": "operador"},
                                               _h(clave_admin): {"usuario": "root", "rol": "admin"}}))
    aj = Ajustes(_env_file=None, auth_habilitada=True)
    monkeypatch.setattr(S, "obtener_ajustes", lambda: aj)

    def pedir(metodo, plantilla, clave):
        req = SimpleNamespace(method=metodo, scope={"route": SimpleNamespace(path=plantilla)},
                              url=SimpleNamespace(path=plantilla), state=SimpleNamespace())
        return asyncio.run(S.autenticar(req, clave)), req

    with pytest.raises(ErrorApi) as e:
        pedir("GET", "/api/v1/alerts", None)
    assert e.value.status == 401 and e.value.codigo == "no_autenticado"
    with pytest.raises(ErrorApi) as e:
        pedir("PUT", "/api/v1/thresholds", clave_op)
    assert e.value.status == 403 and e.value.detalle == {"rol": "operador", "rol_requerido": "admin"}
    principal, req = pedir("PUT", "/api/v1/thresholds", clave_admin)
    assert principal == S.Principal("root", "admin") and req.state.principal is principal
    principal, _ = pedir("PATCH", "/api/v1/alerts/{alert_id}/status", clave_op)
    assert principal.usuario == "olga"
    monkeypatch.setattr(aj, "auth_habilitada", False)
    principal, _ = pedir("PUT", "/api/v1/thresholds", None)
    assert principal is S.ANONIMO
