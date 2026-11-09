"""Cliente de la API del reto (/api/v1) para las pantallas Alertas, Recomendaciones y Operación y para la tarjeta
«Respuesta a la pregunta del reto» de Inicio (GET /api/v1/respuesta).

- URL base: variable SOBUSA_API_URL (por omisión http://127.0.0.1:8000).
- Clave: si SOBUSA_API_KEY está definida, cada petición lleva la cabecera X-API-Key (la API asigna el rol y el usuario de
  la auditoría a partir de la clave). SOBUSA_USUARIO es el nombre que el tablero muestra y envía en el cuerpo de las
  acciones (por omisión operador.dash); con la autenticación activa, la API registra el usuario de la clave.
- Tiempos cortos (conexión y lectura): el tablero nunca se queda colgado esperando a la API.
- Nunca lanza: cada función devuelve (datos, error). `error` es una frase lista para el aviso de la pantalla, por
  ejemplo «La API no responde en http://127.0.0.1:8000 …». Sin API no se inventa ningún dato: la pantalla lo dice.
- Cada petición lleva X-Correlation-Id «dash-…» para seguirla en el log de la API.
"""
from __future__ import annotations

import os
import re
import threading
import uuid

import requests

BASE = os.environ.get("SOBUSA_API_URL", "http://127.0.0.1:8000").rstrip("/")
CLAVE = os.environ.get("SOBUSA_API_KEY", "").strip()
USUARIO = os.environ.get("SOBUSA_USUARIO", "operador.dash").strip() or "operador.dash"
PREFIJO = "/api/v1"
TIEMPO = (1.5, 8.0)            # segundos: conexión, lectura
TIEMPO_SALUD = (1.0, 2.0)      # /health y /metrics responden al instante
TIEMPO_DESCARGA = (1.5, 30.0)  # una exportación grande tarda más
VACIOS = (None, "", "todas", "todos")

TIEMPO_LARGO = (1.5, 600.0)   # solo en un hilo aparte (Operación): nunca dentro de un callback
_local = threading.local()


class _PorHilo:
    """Una requests.Session por hilo (Flask atiende cada callback en su hilo): reutiliza conexiones sin compartir estado."""

    def __getattr__(self, nombre):
        s = getattr(_local, "s", None)
        if s is None:
            s = _local.s = requests.Session()
        return getattr(s, nombre)


_sesion = _PorHilo()


def con_clave() -> bool:
    return bool(CLAVE)


def _cabeceras(etiqueta: str) -> dict:
    h = {"X-Correlation-Id": f"dash-{etiqueta}-{uuid.uuid4().hex[:8]}", "Accept": "application/json"}
    if CLAVE:
        h["X-API-Key"] = CLAVE
    return h


def _url(recurso: str) -> str:
    return f"{BASE}{PREFIJO}/{recurso.lstrip('/')}"


def _etiqueta(recurso: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", recurso.split("?")[0].lower()).strip("-")[:40] or "api"


def limpio(params: dict | None) -> dict:
    """Los filtros que viajan: sin vacíos ni «todas»; los booleanos como true/false."""
    out = {}
    for k, v in (params or {}).items():
        if v in VACIOS:
            continue
        out[k] = ("true" if v else "false") if isinstance(v, bool) else v
    return out


def frase_conexion(exc: Exception) -> str:
    # ConnectTimeout también es ConnectionError: en Windows, un puerto cerrado de 127.0.0.1 no rechaza al instante y
    # vence el tiempo de conexión. Ambos casos son «la API no responde»; solo la lectura lenta es otra cosa.
    if isinstance(exc, requests.ConnectionError):
        return (f"La API no responde en {BASE}. Levántela (docker compose -p sobusa_api up -d o uvicorn) o ajuste "
                "SOBUSA_API_URL, y vuelva a cargar la pantalla.")
    if isinstance(exc, requests.Timeout):
        return f"La API en {BASE} tardó demasiado en responder. Vuelva a intentarlo en un momento."
    return f"No fue posible consultar la API en {BASE}: {exc.__class__.__name__}."


def frase_error(r: requests.Response) -> str:
    """El error uniforme de la API ({"error": {codigo, mensaje, detalle, correlation_id}}) en una frase."""
    try:
        err = (r.json() or {}).get("error") or {}
    except ValueError:
        err = {}
    codigo = err.get("codigo") or str(r.status_code)
    mensaje = err.get("mensaje") or r.text[:200] or r.reason
    if r.status_code == 401:
        return f"{codigo}: la API pide una clave válida (defina SOBUSA_API_KEY). {mensaje}"
    if r.status_code == 403:
        return f"{codigo}: la clave configurada no tiene el rol para esta acción. {mensaje}"
    return f"{codigo}: {mensaje}"


def titulo_error(err: str | None) -> str:
    """Título del aviso según el error: la clave falta o no vale (401), la clave no tiene el rol (403), la API no
    responde o la API contestó con otro error. Las pantallas lo ponen encima de la frase de `frase_error`."""
    e = (err or "").strip()
    if e.startswith(("no_autenticado", "401")):
        return "La API pide una clave válida"
    if e.startswith(("prohibido", "403")):
        return "La clave no tiene el rol para esta consulta"
    if e.startswith(("La API no responde", "La API en", "No fue posible")):
        return "La API no responde"
    return "La API respondió con un error"


def ayuda_error(err: str | None) -> str:
    """Qué hacer con ese error, en una frase para el aviso de la pantalla."""
    t = titulo_error(err)
    if t == "La API pide una clave válida":
        return ("Defina SOBUSA_API_KEY con una clave del rol operador o superior (scripts/crear_api_key.py de la API) y "
                "vuelva a abrir el tablero. Mientras tanto la pantalla no muestra datos: nada se calcula en el Dash.")
    if t == "La clave no tiene el rol para esta consulta":
        return "Pida una clave con el rol que indica la API. Lo demás de la pantalla sigue disponible."
    return "La pantalla no muestra datos sin la API: nada de lo que ve aquí se calcula en el Dash."


TIEMPO_RESPUESTA = (1.5, 45.0)   # GET /respuesta: la primera consulta del día arma el plan y el pronóstico de cada hora


def obtener_con_codigo(recurso: str, tiempo_espera=TIEMPO, **params):
    """GET /api/v1/<recurso> → (json, error, codigo). `codigo` es el código uniforme de la API («sin_datos»,
    «sin_calcular», «no_encontrado», «no_autenticado»…), o None si respondió bien o no respondió."""
    datos, err, codigo, _detalle = obtener_con_detalle(recurso, tiempo_espera, **params)
    return datos, err, codigo


def obtener_con_detalle(recurso: str, tiempo_espera=TIEMPO, **params):
    """Como obtener_con_codigo, y además el `detalle` del error uniforme (dict o None): p. ej. la fecha y la pista de
    POST /respuesta/calcular cuando GET /respuesta responde 404 «sin_calcular»."""
    r, err = _pedir("GET", recurso, params=params, tiempo=tiempo_espera)
    if err:
        codigo, detalle = None, None
        if r is not None:
            try:
                e = (r.json() or {}).get("error") or {}
            except (ValueError, AttributeError):
                e = {}
            codigo, detalle = e.get("codigo"), e.get("detalle")
            codigo = codigo or str(r.status_code)
        return None, err, codigo, detalle if isinstance(detalle, dict) else None
    try:
        return r.json(), None, None, None
    except ValueError:
        return None, f"La API respondió algo que no es JSON en {recurso}.", None, None


def _pedir(metodo: str, recurso: str, *, params=None, cuerpo=None, tiempo=TIEMPO, absoluta=False):
    url = recurso if absoluta else _url(recurso)
    try:
        r = _sesion.request(metodo, url, params=limpio(params), json=cuerpo, timeout=tiempo,
                            headers=_cabeceras(_etiqueta(recurso)))
    except requests.RequestException as exc:
        return None, frase_conexion(exc)
    if r.status_code >= 400:
        return r, frase_error(r)
    return r, None


def obtener(recurso: str, **params):
    """GET /api/v1/<recurso> con filtros → (json, error)."""
    r, err = _pedir("GET", recurso, params=params)
    if err:
        return None, err
    try:
        return r.json(), None
    except ValueError:
        return None, f"La API respondió algo que no es JSON en {recurso}."


def enviar(metodo: str, recurso: str, cuerpo: dict | None = None, tiempo=TIEMPO):
    """POST/PUT/PATCH con cuerpo JSON → (json, error). El error trae el código de la API (409 transicion_invalida,
    activacion_rechazada, 422 datos_incompletos…). `tiempo` más largo solo para lo que se corre en un hilo aparte
    (la activación de un modelo valida cuatro semanas antes de responder)."""
    r, err = _pedir(metodo, recurso, cuerpo=cuerpo or {}, tiempo=tiempo)
    if err:
        return None, err
    try:
        return r.json(), None
    except ValueError:
        return {}, None


def cambiar_estado(alert_id: str, accion: str, comentario: str | None = None, asignado_a: str | None = None):
    cuerpo = {"accion": accion, "usuario": USUARIO, "comentario": (comentario or "").strip() or None,
              "asignado_a": (asignado_a or "").strip() or None}
    return enviar("PATCH", f"alerts/{alert_id}/status", cuerpo)


def salud():
    """GET /health → (json, error). Un 503 con cuerpo («degradado») no es un error de conexión: se devuelve el cuerpo."""
    try:
        r = _sesion.get(f"{BASE}/health", timeout=TIEMPO_SALUD, headers=_cabeceras("salud"))
    except requests.RequestException as exc:
        return None, frase_conexion(exc)
    try:
        cuerpo = r.json()
    except ValueError:
        return None, f"/health respondió {r.status_code} sin JSON."
    return cuerpo, None


def metricas_texto():
    """GET /metrics (texto Prometheus) → (texto, error)."""
    r, err = _pedir("GET", f"{BASE}/metrics", tiempo=TIEMPO_SALUD, absoluta=True)
    if err:
        return None, err
    return r.text, None


def descargar(recurso: str, formato: str = "csv", **filtros):
    """GET /api/v1/<recurso>/export → ((bytes, nombre_de_archivo), error). Pasa por el servidor del Dash para que la clave
    nunca llegue al navegador."""
    r, err = _pedir("GET", f"{recurso}/export", params=dict(filtros, formato=formato), tiempo=TIEMPO_DESCARGA)
    if err:
        return None, err
    m = re.search(r'filename="?([^";]+)"?', r.headers.get("content-disposition", ""))
    nombre = m.group(1) if m else f"{recurso.replace('/', '_')}.{formato}"
    return (r.content, nombre), None


def parsear_metricas(texto: str) -> list[tuple[str, dict, float]]:
    """Líneas de la exposición Prometheus → [(nombre, etiquetas, valor)] (sin comentarios)."""
    out = []
    for linea in (texto or "").splitlines():
        if not linea or linea.startswith("#"):
            continue
        m = re.match(r"^([a-zA-Z_:][\w:]*)(\{(.*)\})?\s+(\S+)", linea)
        if not m:
            continue
        etiquetas = dict(re.findall(r'(\w+)="((?:[^"\\]|\\.)*)"', m.group(3) or ""))
        try:
            out.append((m.group(1), etiquetas, float(m.group(4))))
        except ValueError:
            continue
    return out
