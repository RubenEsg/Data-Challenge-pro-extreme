"""Cliente HTTP común de los scripts que hablan con la API en corridas largas (demostración §14.2 y despliegue).

La API corre con uvicorn, que cierra una conexión keep-alive ociosa a los 5 s (timeout_keep_alive por omisión: ni el
Dockerfile ni docker-compose.yml lo cambian), y httpx, por omisión, reutiliza una conexión ociosa hasta 5 s
(keepalive_expiry). Con los dos plazos iguales hay una carrera: el cliente manda la petición por una conexión que el
servidor está cerrando en ese momento y recibe httpx.RemoteProtocolError («Server disconnected without sending a
response»). Por eso el cliente de crear_cliente():

- descarta las conexiones ociosas a los KEEPALIVE_S = 2 s, mucho antes de que el servidor las cierre;
- reintenta UNA vez solo las peticiones idempotentes (GET y HEAD) ante los errores de esa carrera: la misma conexión
  que el servidor cierra puede fallar al escribir la petición (httpx.WriteError), al leer la respuesta
  (httpx.ReadError o RemoteProtocolError) o al abrirse (ConnectError). Si el reintento también falla, el error sube.
  Un tiempo agotado (ReadTimeout, ConnectTimeout) no es esa carrera y nunca se reintenta;
- nunca reintenta un POST, PUT, PATCH ni DELETE (podría duplicar una ejecución, un entrenamiento o una activación),
  tampoco ante esos errores, y los manda por una conexión nueva, sin keep-alive, para que no caigan en esa carrera.

Con un transporte propio httpx no aplica los proxies del entorno (HTTP_PROXY, ALL_PROXY): estos scripts hablan con una
API local. La clave de API llega solo por el entorno (cabeceras_api, §7.2).

Se llama cliente_http, no cliente_api, para no confundirse con EntregaFinal/dash_app/cliente_api.py, el cliente
del tablero, que sus páginas importan como «import cliente_api».
"""
from __future__ import annotations

import logging
import os

import httpx

TIMEOUT_KEEP_ALIVE_SERVIDOR_S = 5.0   # uvicorn --timeout-keep-alive por omisión (Dockerfile y docker-compose.yml)
KEEPALIVE_S = 2.0                     # claramente menor: el cliente no reutiliza una conexión que el servidor cierra
LIMITES = httpx.Limits(max_connections=100, max_keepalive_connections=20, keepalive_expiry=KEEPALIVE_S)
SIN_KEEPALIVE = httpx.Limits(max_connections=100, max_keepalive_connections=0)   # cada escritura, conexión nueva
METODOS_REINTENTABLES = frozenset({"GET", "HEAD"})
# la carrera del keep-alive: la conexión se cerró al abrirla, al escribir la petición o al leer la respuesta
ERRORES_REINTENTABLES = (httpx.RemoteProtocolError, httpx.ConnectError, httpx.ReadError, httpx.WriteError)
_LOG = logging.getLogger("cliente_http")


def cabeceras_api() -> dict[str, str]:
    """§7.2: la clave de API llega SOLO por el entorno (SOBUSA_API_KEY; la demostración completa exige el rol admin)."""
    clave = os.environ.get("SOBUSA_API_KEY", "").strip()
    return {"X-API-Key": clave} if clave else {}


class TransporteApi(httpx.BaseTransport):
    """Lecturas (GET y HEAD) por conexiones reutilizables, con un reintento; el resto por «escrituras», sin
    reintento."""

    def __init__(self, lecturas: httpx.BaseTransport, escrituras: httpx.BaseTransport | None = None) -> None:
        self.lecturas = lecturas
        self.escrituras = lecturas if escrituras is None else escrituras

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        if request.method not in METODOS_REINTENTABLES:
            return self.escrituras.handle_request(request)
        try:
            return self.lecturas.handle_request(request)
        except ERRORES_REINTENTABLES as exc:
            _LOG.warning("%s %s: %s; se reintenta una vez (petición idempotente)", request.method, request.url.path,
                         type(exc).__name__)
        return self.lecturas.handle_request(request)

    def close(self) -> None:
        self.lecturas.close()
        if self.escrituras is not self.lecturas:
            self.escrituras.close()


def crear_cliente(base_url: str, *, timeout: float, headers: dict[str, str] | None = None,
                  transporte: httpx.BaseTransport | None = None) -> httpx.Client:
    """httpx.Client contra la API con TransporteApi. «transporte» reemplaza a los dos transportes de httpx (para las
    pruebas, un httpx.MockTransport)."""
    if transporte is None:
        api = TransporteApi(httpx.HTTPTransport(limits=LIMITES), httpx.HTTPTransport(limits=SIN_KEEPALIVE))
    else:
        api = TransporteApi(transporte)
    return httpx.Client(base_url=base_url, timeout=timeout, headers=headers, transport=api)
