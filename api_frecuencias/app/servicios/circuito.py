"""Circuit breaker para las integraciones externas (RNF-010): base fuente de solo lectura y notificadores.

Estados: cerrado -> (fallos_max fallos de conexión seguidos) -> abierto -> (reinicio_s) -> semiabierto -> un solo
ensayo: si sale bien vuelve a cerrado; si falla, vuelve a abierto. Mientras está abierto se falla rápido con
CircuitoAbierto, sin tocar la integración.
Solo cuentan los fallos de infraestructura (conexión, red, tiempo de espera). Un error de datos o de validación
(SQL rechazado, ValueError, IntegrityError...) demuestra que la integración respondió: no abre el circuito, se
propaga igual y cuenta como éxito para el circuito.
El estado se ve en /health y en Prometheus (api_circuito_estado: 0 cerrado, 1 semiabierto, 2 abierto). Es estado en
memoria por réplica, a propósito: cada réplica protege sus propias conexiones.
"""
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Any, TypeVar

from prometheus_client import Counter, Gauge

log = logging.getLogger("api_frecuencias.circuito")
T = TypeVar("T")

CERRADO, SEMIABIERTO, ABIERTO = "cerrado", "semiabierto", "abierto"
VALOR_ESTADO = {CERRADO: 0, SEMIABIERTO: 1, ABIERTO: 2}

ESTADO = Gauge("api_circuito_estado", "Estado del circuit breaker (0 cerrado, 1 semiabierto, 2 abierto)",
               ["integracion"])
RECHAZOS = Counter("api_circuito_rechazos_total", "Llamadas rechazadas por circuito abierto", ["integracion"])
FALLOS = Counter("api_circuito_fallos_total", "Fallos de infraestructura contados por el circuito", ["integracion"])
TRANSICIONES = Counter("api_circuito_transiciones_total", "Cambios de estado del circuito", ["integracion", "hacia"])


class CircuitoAbierto(RuntimeError):
    """La integración está en circuito abierto: se falla rápido. `reintentar_en_s` dice cuándo habrá un ensayo."""

    def __init__(self, nombre: str, reintentar_en_s: float):
        super().__init__(f"Circuito {nombre} abierto: se reintenta en {reintentar_en_s:.0f} s")
        self.nombre, self.reintentar_en_s = nombre, reintentar_en_s


def es_falla_de_infraestructura(exc: BaseException) -> bool:
    """True para conexión, red o tiempo de espera; False para errores de datos, SQL o validación."""
    if isinstance(exc, CircuitoAbierto):
        return False
    if isinstance(exc, (TimeoutError, ConnectionError)):
        return True
    try:
        import socket

        if isinstance(exc, socket.gaierror):
            return True
    except ImportError:  # pragma: no cover
        pass
    try:
        from sqlalchemy import exc as sa_exc

        if isinstance(exc, (sa_exc.OperationalError, sa_exc.InterfaceError, sa_exc.DisconnectionError,
                            sa_exc.TimeoutError)):
            return True
        if isinstance(exc, sa_exc.DBAPIError) and getattr(exc, "connection_invalidated", False):
            return True
    except ImportError:  # pragma: no cover
        pass
    try:
        import psycopg

        if isinstance(exc, (psycopg.OperationalError, psycopg.InterfaceError)):
            return True
    except ImportError:  # pragma: no cover
        pass
    return False


class Circuito:
    def __init__(self, nombre: str, fallos_max: int = 3, reinicio_s: float = 60.0,
                 reloj: Callable[[], float] = time.monotonic,
                 es_falla: Callable[[BaseException], bool] = es_falla_de_infraestructura):
        if fallos_max < 1 or reinicio_s <= 0:
            raise ValueError("fallos_max debe ser >= 1 y reinicio_s > 0")
        self.nombre, self.fallos_max, self.reinicio_s = nombre, int(fallos_max), float(reinicio_s)
        self._reloj, self._es_falla = reloj, es_falla
        self._candado = threading.Lock()
        self._estado = CERRADO
        self._fallos = 0
        self._abierto_desde: float | None = None
        self._ensayo_en_curso = False
        self.ultimo_error: str | None = None
        ESTADO.labels(nombre).set(VALOR_ESTADO[CERRADO])

    # ------------------------------------------------------------ estado
    def _cambiar(self, nuevo: str) -> None:
        if nuevo == self._estado:
            return
        anterior, self._estado = self._estado, nuevo
        ESTADO.labels(self.nombre).set(VALOR_ESTADO[nuevo])
        TRANSICIONES.labels(self.nombre, nuevo).inc()
        nivel = logging.WARNING if nuevo == ABIERTO else logging.INFO
        log.log(nivel, "Circuito %s: %s -> %s", self.nombre, anterior, nuevo,
                extra={"integracion": self.nombre, "estado_circuito": nuevo, "fallos": self._fallos})

    def _restante(self) -> float:
        if self._abierto_desde is None:
            return 0.0
        return max(0.0, self.reinicio_s - (self._reloj() - self._abierto_desde))

    @property
    def estado(self) -> str:
        with self._candado:
            if self._estado == ABIERTO and self._restante() <= 0:
                return SEMIABIERTO          # el próximo llamado será el ensayo
            return self._estado

    def resumen(self) -> dict[str, Any]:
        with self._candado:
            estado = SEMIABIERTO if self._estado == ABIERTO and self._restante() <= 0 else self._estado
            return {"estado": estado, "fallos_seguidos": self._fallos, "fallos_max": self.fallos_max,
                    "reinicio_s": self.reinicio_s,
                    "reintento_en_s": round(self._restante(), 1) if self._estado == ABIERTO else None,
                    "ultimo_error": self.ultimo_error}

    def reiniciar(self) -> None:
        with self._candado:
            self._fallos, self._abierto_desde, self._ensayo_en_curso, self.ultimo_error = 0, None, False, None
            self._cambiar(CERRADO)

    # ------------------------------------------------------------ llamada protegida
    def _admitir(self) -> bool:
        """Devuelve True si la llamada es el ensayo semiabierto. Lanza CircuitoAbierto si no se admite."""
        with self._candado:
            if self._estado == ABIERTO:
                restante = self._restante()
                if restante > 0:
                    RECHAZOS.labels(self.nombre).inc()
                    raise CircuitoAbierto(self.nombre, restante)
                self._cambiar(SEMIABIERTO)
            if self._estado == SEMIABIERTO:
                if self._ensayo_en_curso:
                    RECHAZOS.labels(self.nombre).inc()
                    raise CircuitoAbierto(self.nombre, self.reinicio_s)
                self._ensayo_en_curso = True
                return True
            return False

    def _exito(self) -> None:
        with self._candado:
            self._fallos, self._ensayo_en_curso, self._abierto_desde = 0, False, None
            self._cambiar(CERRADO)

    def _fallo(self, exc: BaseException, ensayo: bool) -> None:
        with self._candado:
            self._fallos += 1
            self._ensayo_en_curso = False
            # /health es público: solo el tipo de error (el mensaje puede nombrar equipos o usuarios); el detalle
            # completo queda en el log.
            self.ultimo_error = type(exc).__name__
            log.warning("Circuito %s: fallo %s de %s (%s)", self.nombre, self._fallos, self.fallos_max,
                        f"{type(exc).__name__}: {exc}"[:300], extra={"integracion": self.nombre})
            FALLOS.labels(self.nombre).inc()
            if ensayo or self._fallos >= self.fallos_max:
                self._abierto_desde = self._reloj()
                self._cambiar(ABIERTO)

    def llamar(self, funcion: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        ensayo = self._admitir()
        try:
            resultado = funcion(*args, **kwargs)
        except BaseException as exc:
            if self._es_falla(exc):
                self._fallo(exc, ensayo)
            else:
                self._exito()       # la integración respondió: un error de datos no abre el circuito
            raise
        self._exito()
        return resultado


_registro: dict[str, Circuito] = {}
_candado_registro = threading.Lock()


def _parametros(nombre: str) -> tuple[int, float]:
    from app.config import obtener_ajustes

    aj = obtener_ajustes()
    if nombre.startswith("notif_"):
        return aj.circuito_notif_fallos_max, aj.circuito_notif_reinicio_s
    return aj.circuito_fuente_fallos_max, aj.circuito_fuente_reinicio_s


def obtener(nombre: str) -> Circuito:
    """Circuito compartido de la integración `nombre` (fuente_postgres, notif_correo, notif_whatsapp...)."""
    with _candado_registro:
        c = _registro.get(nombre)
        if c is None:
            fallos_max, reinicio_s = _parametros(nombre)
            c = _registro[nombre] = Circuito(nombre, fallos_max, reinicio_s)
        return c


def estados() -> dict[str, dict[str, Any]]:
    with _candado_registro:
        circuitos = dict(_registro)
    return {n: c.resumen() for n, c in sorted(circuitos.items())}


def reiniciar_todos() -> None:
    """Solo para pruebas: deja el registro vacío (los circuitos se recrean con la configuración vigente)."""
    with _candado_registro:
        _registro.clear()


INTEGRACIONES = ("fuente_postgres", "notif_correo", "notif_whatsapp")


def registrar_integraciones() -> None:
    """Crea los circuitos conocidos para que /health y /metrics los muestren desde el arranque."""
    for nombre in INTEGRACIONES:
        obtener(nombre)
