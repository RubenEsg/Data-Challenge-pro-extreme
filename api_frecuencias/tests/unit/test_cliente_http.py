"""Cliente HTTP común de los scripts de la demostración §14.2 y del despliegue (scripts/cliente_http.py).

Con httpx.MockTransport, sin red: un GET o un HEAD que encuentra la conexión cerrada por el servidor (al abrirla,
ConnectError; al escribir la petición, WriteError; al leer la respuesta, ReadError o RemoteProtocolError) se reintenta
UNA vez y, si vuelve a fallar, el error sube; un POST, PUT, PATCH o DELETE nunca se reintenta (podría duplicar una
ejecución o una activación), tampoco ante esos errores, y va por un transporte sin keep-alive; un tiempo agotado no se
reintenta; el keep-alive del cliente es menor que los 5 s con los que uvicorn cierra las conexiones ociosas.
"""
from __future__ import annotations

import inspect
from pathlib import Path

import httpx
import pytest
import uvicorn

from scripts import cliente_http

API = Path(__file__).resolve().parents[2]
BASE = "http://api.prueba"
LECTURAS = ("GET", "HEAD")
ESCRITURAS = ("POST", "PUT", "PATCH", "DELETE")
# la carrera del keep-alive: la conexión se cierra al abrirla, al escribir la petición o al leer la respuesta
CARRERA = (httpx.RemoteProtocolError, httpx.ConnectError, httpx.ReadError, httpx.WriteError)


def _transporte(fallos: int, error: type[httpx.TransportError] = httpx.RemoteProtocolError):
    """MockTransport que falla con «error» las primeras «fallos» peticiones y después responde 200; anota los
    métodos."""
    llamadas: list[str] = []

    def manejar(request: httpx.Request) -> httpx.Response:
        llamadas.append(request.method)
        if len(llamadas) <= fallos:
            raise error("Server disconnected without sending a response.", request=request)
        return httpx.Response(200, json={"ok": True})

    return httpx.MockTransport(manejar), llamadas


@pytest.mark.parametrize("error", CARRERA)
@pytest.mark.parametrize("metodo", LECTURAS)
def test_get_y_head_se_reintentan_una_vez_y_luego_propagan_el_error(metodo, error):
    transporte, llamadas = _transporte(fallos=99, error=error)
    with cliente_http.crear_cliente(BASE, timeout=5, transporte=transporte) as c, pytest.raises(error):
        c.request(metodo, "/api/v1/frequency/executions/e1")
    assert llamadas == [metodo, metodo]


@pytest.mark.parametrize("error", CARRERA)
@pytest.mark.parametrize("metodo", LECTURAS)
def test_un_get_o_un_head_que_falla_una_vez_responde_con_el_reintento(metodo, error):
    transporte, llamadas = _transporte(fallos=1, error=error)
    with cliente_http.crear_cliente(BASE, timeout=5, headers={"X-API-Key": "k"}, transporte=transporte) as c:
        r = c.request(metodo, "/health")
    assert r.status_code == 200
    assert llamadas == [metodo, metodo]


def test_los_errores_reintentables_son_los_de_la_carrera_y_ningun_tiempo_agotado():
    assert set(cliente_http.ERRORES_REINTENTABLES) == set(CARRERA)
    assert not any(issubclass(e, httpx.TimeoutException) for e in cliente_http.ERRORES_REINTENTABLES)


@pytest.mark.parametrize("error", CARRERA)
@pytest.mark.parametrize("metodo", ESCRITURAS)
def test_post_put_patch_y_delete_no_se_reintentan(metodo, error):
    transporte, llamadas = _transporte(fallos=1, error=error)
    with cliente_http.crear_cliente(BASE, timeout=5, transporte=transporte) as c, pytest.raises(error):
        c.request(metodo, "/api/v1/frequency/executions", json={"hasta": "2025-08-31"})
    assert llamadas == [metodo]          # una sola vez, aunque la segunda habría respondido 200


@pytest.mark.parametrize("error", [httpx.ReadTimeout, httpx.ConnectTimeout, httpx.WriteTimeout, httpx.PoolTimeout])
def test_otros_errores_de_transporte_no_se_reintentan(error):
    transporte, llamadas = _transporte(fallos=1, error=error)
    with cliente_http.crear_cliente(BASE, timeout=5, transporte=transporte) as c, pytest.raises(error):
        c.get("/api/v1/alerts")
    assert llamadas == ["GET"]


def test_lecturas_y_escrituras_van_por_transportes_distintos():
    lecturas, por_lecturas = _transporte(fallos=0)
    escrituras, por_escrituras = _transporte(fallos=0)
    with httpx.Client(base_url=BASE, transport=cliente_http.TransporteApi(lecturas, escrituras)) as c:
        for metodo in LECTURAS + ESCRITURAS:
            c.request(metodo, "/api/v1/models")
    assert por_lecturas == list(LECTURAS) and por_escrituras == list(ESCRITURAS)


def test_el_keep_alive_del_cliente_es_menor_que_el_del_servidor():
    servidor = inspect.signature(uvicorn.Config).parameters["timeout_keep_alive"].default
    assert servidor == cliente_http.TIMEOUT_KEEP_ALIVE_SERVIDOR_S == 5
    for archivo in ("Dockerfile", "docker-compose.yml", "docker-compose.replicas.yml",
                    "docker-compose.integracion.yml"):   # nadie cambia el plazo del servidor
        assert "timeout-keep-alive" not in (API / archivo).read_text(encoding="utf-8"), archivo
    assert cliente_http.LIMITES.keepalive_expiry == cliente_http.KEEPALIVE_S < 5
    with cliente_http.crear_cliente("http://127.0.0.1:9", timeout=5) as c:
        # los pools de httpcore que arma httpx.HTTPTransport (atributos internos; httpx y httpcore van fijados)
        assert c._transport.lecturas._pool._keepalive_expiry == cliente_http.KEEPALIVE_S
        assert c._transport.escrituras._pool._max_keepalive_connections == 0


def test_la_clave_de_api_sale_solo_del_entorno(monkeypatch):
    monkeypatch.setenv("SOBUSA_API_KEY", "  clave-de-prueba  ")
    assert cliente_http.cabeceras_api() == {"X-API-Key": "clave-de-prueba"}
    monkeypatch.delenv("SOBUSA_API_KEY")
    assert cliente_http.cabeceras_api() == {}


@pytest.mark.parametrize("nombre", ["demo_ciclo.py", "demo_ciclo_api.py", "verificar_despliegue.py"])
def test_los_scripts_de_la_demostracion_usan_el_cliente_comun(nombre):
    texto = (API / "scripts" / nombre).read_text(encoding="utf-8")
    assert "crear_cliente(" in texto and "httpx.Client(" not in texto
    assert "def cabeceras_api" not in texto
    # el cliente común es scripts/cliente_http.py; «cliente_api» es el del tablero (dash_app/cliente_api.py)
    assert "from cliente_http import" in texto and "cliente_api" not in texto
    assert (API / "scripts" / "cliente_http.py").exists() and not (API / "scripts" / "cliente_api.py").exists()
