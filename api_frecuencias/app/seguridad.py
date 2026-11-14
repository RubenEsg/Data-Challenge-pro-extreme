"""Autenticación por API key con roles (§7.2 API Gateway, §7.1 ningún secreto en el repositorio, RNF-011).

Cabecera ``X-API-Key``. Las claves nunca están en el repositorio ni en la base: se leen del entorno del despliegue.
- ``API_KEYS``: JSON ``{"<sha256 hex de la clave>": {"usuario": "ana", "rol": "analista"}, ...}``. Solo viaja el hash.
- O una variable por rol, ``API_KEY_OPERADOR``, ``API_KEY_ANALISTA`` y ``API_KEY_ADMIN`` (la clave en claro, solo en
  el entorno o en un gestor de secretos). Se convierte en hash al cargar y el usuario auditado es el nombre del rol.
Las claves son tokens aleatorios de alta entropía (``secrets.token_urlsafe(32)``, ver scripts/crear_api_key.py):
para eso basta SHA-256, como en los tokens de GitHub; no son contraseñas elegidas por personas.

Roles acumulativos: operador (lectura y cambio de estado de alertas) < analista (+ ejecuciones, predicciones,
recomendaciones y entrenamiento) < admin (+ activar o revertir modelos, cambiar umbrales, los ajustes locales de
capacidad, flota y tiempo de ciclo y correr la retención de datos). La matriz de permisos
vive aquí, en un solo lugar auditable (POLITICA); toda ruta de /api/v1 pasa por ``autenticar`` desde main.py.
Una escritura sin entrada explícita en la matriz exige admin (denegación por omisión).
Con ``AUTH_HABILITADA=false`` (solo para desarrollo local) todo se permite y el usuario auditado es el declarado.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from collections.abc import Mapping
from contextvars import ContextVar
from dataclasses import dataclass

from fastapi import Request, Security
from fastapi.security import APIKeyHeader
from prometheus_client import Counter

from app.config import obtener_ajustes
from app.routers.comun import ErrorApi

log = logging.getLogger("api_frecuencias.seguridad")
AUTENTICACIONES = Counter("api_autenticacion_total", "Decisiones de autenticación en /api/v1 (ok, 401, 403)",
                          ["resultado", "rol"])

CABECERA = "X-API-Key"
ROLES = ("operador", "analista", "admin")
NIVEL = {rol: i for i, rol in enumerate(ROLES)}
PREFIJO = "/api/v1"

# (método, plantilla de ruta sin el prefijo /api/v1) -> rol mínimo. Los GET no listados exigen operador.
POLITICA: dict[tuple[str, str], str] = {
    ("PATCH", "/alerts/{alert_id}/status"): "operador",
    ("POST", "/frequency/executions"): "analista",
    ("GET", "/frequency/watermarks"): "operador",            # RNF-005: marcas de agua por proceso y ruta
    ("POST", "/predictions/run"): "analista",
    ("POST", "/recommendations/calculate"): "analista",
    ("POST", "/respuesta/calcular"): "analista",
    ("POST", "/segmentos/estadisticas/refrescar"): "analista",
    ("POST", "/models/train"): "analista",
    ("POST", "/models/{model_id}/activate"): "admin",
    ("POST", "/models/rollback"): "admin",
    ("PUT", "/thresholds"): "admin",
    ("POST", "/thresholds/{version}/aprobar"): "admin",
    ("PUT", "/catalogos/capacidad"): "admin",
    ("PUT", "/catalogos/flota"): "admin",          # §3.1: flota disponible y tiempo de ciclo (ajuste local)
    ("POST", "/retencion/aplicar"): "admin",       # §18: la tarea de retención bajo demanda (borra datos viejos)
}
METODOS_LECTURA = ("GET", "HEAD", "OPTIONS")

ESQUEMA_API_KEY = APIKeyHeader(name=CABECERA, auto_error=False, scheme_name="ApiKey",
                               description="Clave de API del rol (operador, analista o admin).")


@dataclass(frozen=True)
class Principal:
    usuario: str
    rol: str
    autenticado: bool = True


ANONIMO = Principal(usuario="anonimo", rol="admin", autenticado=False)
principal_actual: ContextVar[Principal | None] = ContextVar("principal_actual", default=None)


def hash_clave(clave: str) -> str:
    return hashlib.sha256(clave.encode("utf-8")).hexdigest()


def rol_requerido(metodo: str, ruta: str) -> str:
    """Rol mínimo para (método, ruta). `ruta` es la plantilla, con o sin el prefijo /api/v1."""
    relativa = ruta[len(PREFIJO):] if ruta.startswith(PREFIJO) else ruta
    metodo = metodo.upper()
    explicito = POLITICA.get((metodo, relativa))
    if explicito:
        return explicito
    return "operador" if metodo in METODOS_LECTURA else "admin"


def _objeto_api_keys(crudo: str) -> dict:
    """El JSON de API_KEYS como diccionario; si no es un objeto JSON válido, lo registra y devuelve {}."""
    try:
        datos = json.loads(crudo)
        if not isinstance(datos, dict):
            raise ValueError("API_KEYS debe ser un objeto JSON")
    except ValueError:
        log.error("API_KEYS no es un JSON válido {hash: {usuario, rol}}; se ignora")
        return {}
    return datos


def _entrada_api_keys(h: object, info: object) -> tuple[str, Principal] | None:
    """(hash, Principal) de una entrada de API_KEYS, o None si el hash, el rol o el usuario no son válidos."""
    hash_ = str(h).strip().lower()
    datos = info if isinstance(info, dict) else {}
    rol = str(datos.get("rol", "")).strip().lower()
    usuario = str(datos.get("usuario", "")).strip()
    hash_valido = len(hash_) == 64 and all(c in "0123456789abcdef" for c in hash_)
    if not hash_valido or rol not in NIVEL or not usuario:
        log.error("Entrada inválida en API_KEYS (hash %s…): se ignora", hash_[:6])
        return None
    return hash_, Principal(usuario=usuario, rol=rol)


def _claves_por_rol(env: Mapping[str, str]) -> dict[str, Principal]:
    """hash -> Principal de las variables API_KEY_<ROL> (clave en claro, mínimo 16 caracteres)."""
    claves: dict[str, Principal] = {}
    for rol in ROLES:
        clave = (env.get(f"API_KEY_{rol.upper()}") or "").strip()
        if not clave:
            continue
        if len(clave) < 16:
            log.error("API_KEY_%s es demasiado corta (mínimo 16 caracteres): se ignora", rol.upper())
            continue
        claves[hash_clave(clave)] = Principal(usuario=rol, rol=rol)
    return claves


def cargar_claves(env: Mapping[str, str] | None = None) -> dict[str, Principal]:
    """hash -> Principal desde API_KEYS (JSON de hashes) y API_KEY_<ROL> (clave en claro). Ignora entradas inválidas
    y lo deja en el log, sin escribir nunca una clave ni un hash completo."""
    env = os.environ if env is None else env
    claves: dict[str, Principal] = {}
    crudo = (env.get("API_KEYS") or "").strip()
    if crudo:
        for h, info in _objeto_api_keys(crudo).items():
            entrada = _entrada_api_keys(h, info)
            if entrada is not None:
                claves[entrada[0]] = entrada[1]
    claves.update(_claves_por_rol(env))
    return claves


_cache: tuple[tuple[str, ...], dict[str, Principal]] | None = None


def _claves_vigentes() -> dict[str, Principal]:
    """Relee el entorno solo si cambió (rotar una clave no exige reiniciar el proceso)."""
    global _cache
    firma = tuple(os.environ.get(n, "") for n in ("API_KEYS", *(f"API_KEY_{r.upper()}" for r in ROLES)))
    if _cache is None or _cache[0] != firma:
        _cache = (firma, cargar_claves())
    return _cache[1]


def resolver(clave: str | None, claves: Mapping[str, Principal] | None = None) -> Principal | None:
    if not clave:
        return None
    claves = _claves_vigentes() if claves is None else claves
    buscado = hash_clave(clave.strip())
    encontrado = None
    for h, principal in claves.items():          # comparación de tiempo constante sobre todas las entradas
        if hmac.compare_digest(h, buscado):
            encontrado = principal
    return encontrado


def _no_autenticado(mensaje: str) -> ErrorApi:
    return ErrorApi(401, "no_autenticado", mensaje, {"cabecera": CABECERA})


async def autenticar(request: Request, clave: str | None = Security(ESQUEMA_API_KEY)) -> Principal:
    """Dependencia de todas las rutas de /api/v1: identifica la clave y aplica la matriz de permisos."""
    ruta = request.scope.get("route")
    plantilla = getattr(ruta, "path", request.url.path)
    requerido = rol_requerido(request.method, plantilla)
    if not obtener_ajustes().auth_habilitada:
        principal = ANONIMO
    else:
        principal = resolver(clave)
        if principal is None:
            AUTENTICACIONES.labels("401", "-").inc()
            raise _no_autenticado("Falta la cabecera X-API-Key o la clave no es válida" if clave is not None
                                  else "Falta la cabecera X-API-Key")
        if NIVEL[principal.rol] < NIVEL[requerido]:
            AUTENTICACIONES.labels("403", principal.rol).inc()
            request.state.principal = principal          # el log de la petición registra quién fue rechazado
            raise ErrorApi(403, "prohibido", f"El rol {principal.rol} no puede {request.method} {plantilla}",
                           {"rol": principal.rol, "rol_requerido": requerido})
    AUTENTICACIONES.labels("ok" if principal.autenticado else "sin_autenticacion", principal.rol).inc()
    request.state.principal = principal
    principal_actual.set(principal)
    return principal


async def proteger_metricas(request: Request, clave: str | None = Security(ESQUEMA_API_KEY)) -> None:
    """/metrics: público si METRICAS_PUBLICAS=true (scrape de Prometheus en la red interna); si no, cualquier rol."""
    aj = obtener_ajustes()
    if aj.metricas_publicas or not aj.auth_habilitada:
        return
    if resolver(clave) is None:
        raise _no_autenticado("/metrics exige X-API-Key (METRICAS_PUBLICAS=false)")


def usuario_auditoria(principal: Principal | None, declarado: str | None = None) -> str:
    """Usuario que queda en la auditoría: con autenticación es SIEMPRE el principal (el cuerpo no puede suplantarlo);
    sin autenticación (desarrollo local) se respeta el declarado en la petición."""
    if principal is not None and principal.autenticado:
        return principal.usuario
    return declarado or (principal.usuario if principal else ANONIMO.usuario)


def rutas_documentacion(ajustes=None) -> dict[str, str | None]:
    """Swagger UI y openapi.json solo en los ambientes donde están habilitados (§12.1); en producción, 404."""
    ajustes = ajustes or obtener_ajustes()
    activos = ajustes.docs_efectivos
    return {"docs_url": "/docs" if activos else None, "openapi_url": "/openapi.json" if activos else None,
            "redoc_url": None}


def advertir_configuracion() -> None:
    aj = obtener_ajustes()
    if not aj.auth_habilitada:
        log.warning("AUTH_HABILITADA=false: la API no exige X-API-Key (use solo en desarrollo local)")
    elif not _claves_vigentes():
        log.error("AUTH_HABILITADA=true y no hay claves (API_KEYS o API_KEY_<ROL>): toda ruta de /api/v1 dará 401")


__all__ = ["CABECERA", "ROLES", "POLITICA", "Principal", "autenticar", "proteger_metricas", "rol_requerido",
           "cargar_claves", "resolver", "hash_clave", "usuario_auditoria", "rutas_documentacion",
           "principal_actual", "advertir_configuracion"]
