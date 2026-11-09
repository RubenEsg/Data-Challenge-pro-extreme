"""Cola de trabajos en PostgreSQL para N réplicas (RNF-001, RNF-004, RNF-005, §7.1 procesos largos asíncronos).

La tabla execution_log es también la cola; no hace falta otro servicio (Redis, RabbitMQ).

Protocolo
- Encolar: una fila con estado 'en_cola' (POST /frequency/executions, POST /models/train o el planificador).
- Reclamar: SELECT … FOR UPDATE SKIP LOCKED LIMIT 1 y UPDATE a 'corriendo' con worker_id, intentos + 1 y una reserva
  lease_hasta = now() + LEASE_SEGUNDOS, en una transacción corta. Dos réplicas nunca toman la misma fila.
- Orden: las ejecuciones de tipo 'frecuencia' corren de una en una en todo el clúster, porque la lectura
  incremental parte de la marca de agua de la anterior. Un bloqueo de asesoría de transacción serializa los
  reclamos (milisegundos), así que dos réplicas no pueden arrancar dos 'frecuencia' a la vez. Los entrenamientos
  sí corren en paralelo.
- Latido: mientras corre, un hilo renueva la reserva cada LEASE/3. Si la réplica muere (SIGKILL, corte de luz), la
  reserva vence y cualquier réplica devuelve la fila a la cola (liberar_vencidas) y la retoma. Una réplica que
  reinicia con la misma identidad recupera al instante lo que dejó su proceso anterior.
- Cerca (fencing): el cierre 'ok' se escribe en la MISMA transacción que los resultados y solo si la fila sigue
  reservada por el mismo worker_id. Si otra réplica la retomó, el intento viejo se revierte entero: nunca quedan
  resultados duplicados, aunque dos procesos lleguen a correr el mismo trabajo.
- Reintento: un fallo reintentable deja la fila 'en_cola' con disponible_desde = now() + espera exponencial; al
  agotar MAX_REINTENTOS queda 'error'. La marca de agua solo avanza con una ejecución que termina 'ok'.
- execution_attempt guarda cada intento (réplica, inicio, fin, resultado): evidencia de «exactamente una vez».
- Tipos de trabajo: 'frecuencia' (ciclo diario), 'entrenamiento' (candidato en sombra) y 'respuesta' (foto de la
  respuesta del reto con respuesta.precalcular).
- Métricas Prometheus (/metrics): intentos terminados por tipo y resultado, su duración (los entrenamientos incluidos),
  reintentos por motivo y la profundidad de la cola por tipo y estado (ColectorCola, registrado en app/main.py).
"""
from __future__ import annotations

import contextvars
import logging
import os
import re
import socket
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any

from prometheus_client import Counter, Histogram
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import obtener_ajustes
from app.db import sesion_contexto

log = logging.getLogger("api_frecuencias.cola")
TIPOS = ("frecuencia", "entrenamiento", "respuesta")
EJECUCIONES = Counter("api_ejecuciones_total", "Intentos de ejecución terminados, por tipo de trabajo y resultado "
                      "(ok, reintento, error, reserva_perdida)", ["tipo", "resultado"])
DURACION = Histogram("api_ejecucion_duracion_segundos", "Duración de cada intento por tipo de trabajo y resultado "
                     "(tipo=entrenamiento: duración de los entrenamientos)", ["tipo", "resultado"],
                     buckets=(1, 5, 15, 30, 60, 120, 300, 600, 1200, 1800, 3600))
REINTENTOS = Counter("api_cola_reintentos_total", "Trabajos devueltos a la cola para otro intento, por tipo y motivo "
                     "(fallo, reserva_vencida, reinicio)", ["tipo", "motivo"])
CLAVE_RECLAMO = 7_441_001  # pg_advisory_xact_lock: serializa los reclamos (no las ejecuciones de entrenamiento)
_ARRANQUE = uuid.uuid4().hex[:6]
trabajador_actual: contextvars.ContextVar[str | None] = contextvars.ContextVar("trabajador_actual", default=None)


class ReservaPerdida(Exception):
    """Otra réplica retomó el trabajo (la reserva venció): este intento no debe escribir resultados."""


@dataclass(frozen=True)
class Reclamo:
    execution_id: uuid.UUID
    tipo: str
    intentos: int
    worker_id: str


# ---------------------------------------------------------------- identidad y espera
def identidad_replica() -> str:
    """Identidad estable de la réplica: TRABAJADOR_ID, o el nombre del contenedor/equipo (sin «:»)."""
    crudo = obtener_ajustes().trabajador_id or os.environ.get("HOSTNAME") or socket.gethostname() or "replica"
    return re.sub(r"[^A-Za-z0-9_.-]", "-", crudo.strip()) or "replica"


def identidad_proceso() -> str:
    """réplica:pid:arranque — distingue un proceso reiniciado del anterior aunque la réplica sea la misma."""
    return f"{identidad_replica()}:{os.getpid()}:{_ARRANQUE}"


def espera_reintento(intento: int, base: float = 2.0, tope: float = 60.0) -> float:
    """Espera exponencial antes del reintento n (2, 4, 8 … s, con tope)."""
    return float(min(tope, base * 2 ** max(0, intento - 1)))


# ---------------------------------------------------------------- SQL de la cola
_RECLAMAR = text("""
WITH c AS (
    SELECT e.execution_id
      FROM ai_frecuencias.execution_log e
     WHERE e.estado = 'en_cola'
       AND coalesce(e.disponible_desde, now()) <= now()
       AND (CAST(:id AS uuid) IS NULL OR e.execution_id = CAST(:id AS uuid))
       AND (e.tipo <> 'frecuencia' OR NOT EXISTS (
             SELECT 1 FROM ai_frecuencias.execution_log x WHERE x.tipo = 'frecuencia' AND x.estado = 'corriendo'))
       AND (e.tipo <> 'frecuencia' OR NOT EXISTS (
             SELECT 1 FROM ai_frecuencias.execution_log y
              WHERE y.tipo = 'frecuencia' AND y.estado = 'en_cola' AND y.creado_en < e.creado_en
                AND y.disponible_desde > now()))
     ORDER BY e.creado_en, e.execution_id
     FOR UPDATE SKIP LOCKED
     LIMIT 1
)
UPDATE ai_frecuencias.execution_log t
   SET estado = 'corriendo', worker_id = :w, intentos = t.intentos + 1,
       lease_hasta = now() + make_interval(secs => :lease), disponible_desde = NULL,
       iniciado_en = coalesce(t.iniciado_en, now()), actualizado_en = now(),
       mensaje = 'Intento ' || (t.intentos + 1) || ' en ' || :w
  FROM c
 WHERE t.execution_id = c.execution_id
RETURNING t.execution_id, t.tipo, t.intentos
""")

_RENOVAR = text("""
UPDATE ai_frecuencias.execution_log SET lease_hasta = now() + make_interval(secs => :lease)
 WHERE execution_id = :id AND worker_id = :w AND estado = 'corriendo'
""")

_VENCIDAS = text("""
UPDATE ai_frecuencias.execution_log t
   SET estado = CASE WHEN t.intentos >= :max THEN 'error' ELSE 'en_cola' END,
       terminado_en = CASE WHEN t.intentos >= :max THEN now() END,
       mensaje = CASE WHEN t.intentos >= :max
                      THEN 'Se agotaron los intentos: ' || coalesce(t.worker_id, 'la réplica') ||
                           ' dejó de renovar la reserva'
                      ELSE 'Reencolada (RNF-001): ' || coalesce(t.worker_id, 'la réplica') ||
                           ' dejó de renovar la reserva' END,
       worker_id = NULL, lease_hasta = NULL, actualizado_en = now()
 WHERE t.estado = 'corriendo' AND (t.lease_hasta IS NULL OR t.lease_hasta < now())
RETURNING t.execution_id, t.estado, t.tipo
""")

_PROPIAS = text("""
UPDATE ai_frecuencias.execution_log t
   SET estado = CASE WHEN t.intentos >= :max THEN 'error' ELSE 'en_cola' END,
       terminado_en = CASE WHEN t.intentos >= :max THEN now() END,
       mensaje = 'Reencolada al reiniciar la réplica ' || :replica || ' (el proceso ' ||
                 split_part(t.worker_id, ':', 2) || ' terminó sin cerrarla; RNF-001)',
       worker_id = NULL, lease_hasta = NULL, actualizado_en = now()
 WHERE t.estado = 'corriendo'
   AND split_part(t.worker_id, ':', 1) = :replica
   AND split_part(t.worker_id, ':', 2) || ':' || split_part(t.worker_id, ':', 3) <> :proceso
RETURNING t.execution_id, t.estado, t.tipo
""")

_ABANDONAR_INTENTOS = text("""
UPDATE ai_frecuencias.execution_attempt SET resultado = 'abandonado', terminado_en = now(), detalle = :detalle
 WHERE execution_id = ANY(CAST(:ids AS uuid[])) AND resultado = 'corriendo'
""")


# ---------------------------------------------------------------- operaciones
def reclamar(worker_id: str, lease_s: float | None = None, execution_id: uuid.UUID | None = None,
             sesion: Session | None = None) -> Reclamo | None:
    """Reserva el siguiente trabajo disponible (o uno en particular) para worker_id. None si no hay."""
    lease = float(lease_s if lease_s is not None else obtener_ajustes().lease_segundos)

    def _hacer(s: Session) -> Reclamo | None:
        s.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": CLAVE_RECLAMO})
        fila = s.execute(_RECLAMAR, {"id": str(execution_id) if execution_id else None, "w": worker_id,
                                     "lease": lease}).first()
        if fila is None:
            return None
        s.execute(text("INSERT INTO ai_frecuencias.execution_attempt (execution_id, intento, worker_id) "
                       "VALUES (:id, :n, :w)"), {"id": fila.execution_id, "n": fila.intentos, "w": worker_id})
        return Reclamo(execution_id=fila.execution_id, tipo=fila.tipo, intentos=int(fila.intentos),
                       worker_id=worker_id)

    if sesion is not None:
        r = _hacer(sesion)
        sesion.commit()
        return r
    with sesion_contexto() as s:
        return _hacer(s)


def renovar(execution_id: uuid.UUID, worker_id: str, lease_s: float | None = None) -> bool:
    """Latido: alarga la reserva. False si ya no es de este trabajador (otra réplica la retomó)."""
    lease = float(lease_s if lease_s is not None else obtener_ajustes().lease_segundos)
    with sesion_contexto() as s:
        return s.execute(_RENOVAR, {"id": execution_id, "w": worker_id, "lease": lease}).rowcount == 1


def _devolver(sql, parametros: dict, detalle: str, motivo: str = "reserva_vencida") -> list[uuid.UUID]:
    with sesion_contexto() as s:
        filas = s.execute(sql, parametros).all()
        ids = [f.execution_id for f in filas]
        if ids:
            s.execute(_ABANDONAR_INTENTOS, {"ids": [str(i) for i in ids], "detalle": detalle})
    for f in filas:
        log.warning("Ejecución %s devuelta por %s: queda %s", f.execution_id, detalle, f.estado)
        if f.estado == "en_cola":
            REINTENTOS.labels(str(f.tipo), motivo).inc()
    return ids


def liberar_vencidas(max_reintentos: int | None = None) -> list[uuid.UUID]:
    """Devuelve a la cola las filas 'corriendo' cuya reserva venció (su réplica murió o dejó de responder)."""
    maximo = max(1, max_reintentos if max_reintentos is not None else obtener_ajustes().max_reintentos)
    return _devolver(_VENCIDAS, {"max": maximo}, "reserva vencida")


def liberar_propias(replica: str | None = None, proceso: str | None = None,
                    max_reintentos: int | None = None) -> list[uuid.UUID]:
    """Al reiniciar una réplica: devuelve lo que tenía reservado su proceso ANTERIOR (que ya no existe)."""
    replica = replica or identidad_replica()
    proceso = proceso or identidad_proceso().split(":", 1)[1]
    maximo = max(1, max_reintentos if max_reintentos is not None else obtener_ajustes().max_reintentos)
    return _devolver(_PROPIAS, {"replica": replica, "proceso": proceso, "max": maximo},
                     f"reinicio de la réplica {replica}", motivo="reinicio")


def recuperar_al_arrancar() -> list[uuid.UUID]:
    """RNF-001 al arrancar: lo del proceso anterior de esta réplica y lo de reservas vencidas vuelve a la cola."""
    return list(dict.fromkeys([*liberar_propias(), *liberar_vencidas()]))


def cerrar_ok(s: Session, execution_id: uuid.UUID, valores: dict[str, Any]) -> None:
    """Cierre 'ok' con cerca, en la transacción de los resultados: si la reserva ya no es de este trabajador,
    lanza ReservaPerdida y el llamador revierte todo (no quedan resultados duplicados)."""
    from sqlalchemy import update

    from app.modelos_db import Ejecucion

    worker = trabajador_actual.get()
    consulta = update(Ejecucion).where(Ejecucion.execution_id == execution_id)
    if worker is not None:
        consulta = consulta.where(Ejecucion.worker_id == worker, Ejecucion.estado == "corriendo")
    resultado = s.execute(consulta.values(lease_hasta=None, **valores))
    if worker is not None and resultado.rowcount != 1:
        raise ReservaPerdida(f"La ejecución {execution_id} ya no está reservada por {worker}")
    if worker is not None:
        s.execute(text("UPDATE ai_frecuencias.execution_attempt SET resultado = 'ok', terminado_en = now() "
                       "WHERE execution_id = :id AND worker_id = :w AND resultado = 'corriendo'"),
                  {"id": execution_id, "w": worker})


def _cerrar_intento(r: Reclamo, resultado: str, detalle: str | None) -> None:
    with sesion_contexto() as s:
        s.execute(text("UPDATE ai_frecuencias.execution_attempt SET resultado = :r, terminado_en = now(), detalle = :d "
                       "WHERE execution_id = :id AND intento = :n AND resultado = 'corriendo'"),
                  {"r": resultado, "d": (detalle or "")[:2000] or None, "id": r.execution_id, "n": r.intentos})


def _registrar_fallo(r: Reclamo, exc: Exception, definitiva: bool, espera_s: float) -> str:
    """Fallo con cerca: solo lo registra quien aún tiene la reserva."""
    mensaje = f"{type(exc).__name__}: {exc}"[:2000]
    with sesion_contexto() as s:
        n = s.execute(text("""
            UPDATE ai_frecuencias.execution_log
               SET estado = :estado, mensaje = :m, worker_id = NULL, lease_hasta = NULL, actualizado_en = now(),
                   terminado_en = CASE WHEN :definitiva THEN now() END,
                   disponible_desde = CASE WHEN :definitiva THEN NULL
                                           ELSE now() + make_interval(secs => :espera) END
             WHERE execution_id = :id AND worker_id = :w AND estado = 'corriendo'"""),
            {"estado": "error" if definitiva else "en_cola", "m": mensaje, "definitiva": definitiva,
             "espera": espera_s, "id": r.execution_id, "w": r.worker_id}).rowcount
    resultado = ("error" if definitiva else "reintento") if n == 1 else "reserva_perdida"
    _cerrar_intento(r, resultado, mensaje)
    return resultado


class _Latido(threading.Thread):
    def __init__(self, r: Reclamo, lease_s: float):
        super().__init__(name=f"latido-{r.execution_id.hex[:8]}", daemon=True)
        self.r, self.lease_s = r, lease_s
        self.parar = threading.Event()
        self.perdida = threading.Event()

    def run(self) -> None:
        while not self.parar.wait(max(0.2, self.lease_s / 3)):
            try:
                if not renovar(self.r.execution_id, self.r.worker_id, self.lease_s):
                    self.perdida.set()
                    log.warning("Reserva perdida de %s (%s)", self.r.execution_id, self.r.worker_id)
                    return
            except Exception:  # noqa: BLE001 - un corte breve de la base no detiene el trabajo; se reintenta
                log.warning("No se pudo renovar la reserva de %s", self.r.execution_id, exc_info=True)


def correr_reclamo(r: Reclamo, *, lease_s: float | None = None, max_reintentos: int | None = None,
                   base_espera: float = 2.0) -> str:
    """Corre UN intento ya reclamado. Devuelve 'ok', 'reintento', 'error' o 'reserva_perdida'."""
    from app.servicios import ejecucion

    aj = obtener_ajustes()
    lease = float(lease_s if lease_s is not None else aj.lease_segundos)
    maximo = max(1, max_reintentos if max_reintentos is not None else aj.max_reintentos)
    latido = _Latido(r, lease)
    latido.start()
    token = trabajador_actual.set(r.worker_id)
    t0 = time.perf_counter()
    resultado = "error"
    try:
        _correr_segun_tipo(r)
        log.info("Ejecución %s (%s) ok en %.1f s, intento %s, %s", r.execution_id, r.tipo,
                 time.perf_counter() - t0, r.intentos, r.worker_id)
        resultado = "ok"
    except ReservaPerdida as exc:
        log.warning("%s: el intento se revirtió completo", exc)
        _cerrar_intento(r, "reserva_perdida", str(exc))
        resultado = "reserva_perdida"
    except Exception as exc:  # noqa: BLE001 - se registra y se reintenta con espera
        definitiva = isinstance(exc, ejecucion.ErrorNoReintentable) or r.intentos >= maximo
        log.exception("Fallo en la ejecución %s (intento %s de %s, %s)", r.execution_id, r.intentos, maximo,
                      r.worker_id)
        resultado = _registrar_fallo(r, exc, definitiva, espera_reintento(r.intentos, base_espera))
        if resultado == "reintento":
            REINTENTOS.labels(r.tipo, "fallo").inc()
    finally:
        trabajador_actual.reset(token)
        latido.parar.set()
        EJECUCIONES.labels(r.tipo, resultado).inc()
        DURACION.labels(r.tipo, resultado).observe(time.perf_counter() - t0)
        ejecucion.cerrar_etapa(r.execution_id)
    return resultado


def _correr_segun_tipo(r: Reclamo) -> None:
    from app.servicios import ejecucion

    if r.tipo == "entrenamiento":
        ejecucion._ciclo_entrenamiento(r.execution_id)
    elif r.tipo == "respuesta":
        ejecucion._ciclo_respuesta(r.execution_id)
    else:
        ejecucion._ciclo_frecuencia(r.execution_id)


def _estado(execution_id: uuid.UUID) -> str | None:
    with sesion_contexto() as s:
        return s.execute(text("SELECT estado FROM ai_frecuencias.execution_log WHERE execution_id = :id"),
                         {"id": execution_id}).scalar()


def procesar(execution_id: uuid.UUID, *, limite_espera_s: float = 600.0) -> str | None:
    """Sin trabajadores en segundo plano (TRABAJADORES=0, pruebas): procesa aquí esta ejecución con el MISMO
    protocolo de reserva. Si otra réplica ya la tomó, no hace nada. Devuelve el estado final que vio."""
    aj = obtener_ajustes()
    worker = f"{identidad_proceso()}:api"
    espera_hasta = time.monotonic() + limite_espera_s
    while True:
        r = reclamar(worker, execution_id=execution_id)
        if r is not None:
            resultado = correr_reclamo(r)
            if resultado != "reintento":
                return _estado(execution_id)
            espera_hasta = time.monotonic() + limite_espera_s
            continue
        estado = _estado(execution_id)
        if estado != "en_cola" or time.monotonic() > espera_hasta:
            return estado
        liberar_vencidas()
        time.sleep(max(0.05, min(aj.sondeo_cola_segundos, 1.0)))


# ---------------------------------------------------------------- trabajadores en segundo plano
class Trabajador(threading.Thread):
    """Hilo que consume la cola: barre reservas vencidas, reclama, corre y vuelve a sondear."""

    def __init__(self, indice: int, parada: threading.Event, *, worker_id: str | None = None,
                 lease_s: float | None = None, sondeo_s: float | None = None, max_reintentos: int | None = None,
                 base_espera: float = 2.0):
        super().__init__(name=f"cola-{indice}", daemon=True)
        aj = obtener_ajustes()
        self.worker_id = worker_id or f"{identidad_proceso()}:t{indice}"
        self.parada = parada
        self.lease_s = float(lease_s if lease_s is not None else aj.lease_segundos)
        self.sondeo_s = float(sondeo_s if sondeo_s is not None else aj.sondeo_cola_segundos)
        self.max_reintentos = max_reintentos
        self.base_espera = base_espera
        self.hechos: list[tuple[uuid.UUID, str]] = []
        self.ocupado = threading.Event()

    def run(self) -> None:
        ultimo_barrido = 0.0
        while not self.parada.is_set():
            try:
                if time.monotonic() - ultimo_barrido >= max(0.5, self.lease_s / 3):
                    liberar_vencidas(self.max_reintentos)
                    ultimo_barrido = time.monotonic()
                r = reclamar(self.worker_id, self.lease_s)
            except Exception:  # noqa: BLE001 - base caída: espera y reintenta sin morir
                log.warning("No se pudo consultar la cola", exc_info=True)
                self.parada.wait(min(5.0, self.sondeo_s * 5))
                continue
            if r is None:
                self.parada.wait(self.sondeo_s)
                continue
            self.ocupado.set()
            try:
                self.hechos.append((r.execution_id, correr_reclamo(
                    r, lease_s=self.lease_s, max_reintentos=self.max_reintentos, base_espera=self.base_espera)))
            finally:
                self.ocupado.clear()
            # cede el turno un sondeo: como las de frecuencia van de una en una, sin esta pausa la réplica que
            # termina reclamaría siempre la siguiente antes de que las demás despierten (reparto de carga)
            self.parada.wait(self.sondeo_s)


_parada = threading.Event()
_trabajadores: list[Trabajador] = []


def iniciar(n: int | None = None) -> list[Trabajador]:
    """Arranca n hilos consumidores (TRABAJADORES por omisión). Idempotente."""
    n = obtener_ajustes().trabajadores_efectivos if n is None else n
    if _trabajadores or n <= 0:
        return list(_trabajadores)
    _parada.clear()
    for i in range(1, n + 1):
        t = Trabajador(i, _parada)
        t.start()
        _trabajadores.append(t)
    log.info("Cola: %s trabajadores en %s (reserva %.0f s)", n, identidad_proceso(),
             obtener_ajustes().lease_segundos)
    return list(_trabajadores)


def detener(espera_s: float = 10.0) -> list[uuid.UUID]:
    """Parada ordenada (SIGTERM): no toma trabajos nuevos, espera el que corre y devuelve lo que no terminó."""
    if not _trabajadores:
        return []
    _parada.set()
    limite = time.monotonic() + espera_s
    for t in _trabajadores:
        t.join(timeout=max(0.0, limite - time.monotonic()))
    _trabajadores.clear()
    proceso = identidad_proceso()
    try:
        with sesion_contexto() as s:
            ids = [f.execution_id for f in s.execute(text("""
                UPDATE ai_frecuencias.execution_log SET estado = 'en_cola', worker_id = NULL, lease_hasta = NULL,
                       mensaje = 'Devuelta a la cola por apagado ordenado de ' || :p, actualizado_en = now()
                 WHERE estado = 'corriendo' AND worker_id LIKE :prefijo
                RETURNING execution_id"""), {"p": proceso, "prefijo": proceso.replace("_", r"\_") + ":%"}).all()]
            if ids:
                s.execute(_ABANDONAR_INTENTOS, {"ids": [str(i) for i in ids], "detalle": "apagado ordenado"})
    except Exception:  # noqa: BLE001 - si la base no responde, la reserva vence sola
        log.warning("No se pudieron devolver los trabajos al apagar", exc_info=True)
        ids = []
    return ids


def estado_trabajadores() -> dict[str, Any]:
    return {"replica": identidad_replica(), "proceso": identidad_proceso(),
            "trabajadores": [{"worker_id": t.worker_id, "vivo": t.is_alive(), "ocupado": t.ocupado.is_set(),
                              "hechos": len(t.hechos)} for t in _trabajadores]}


class ColectorCola:
    """Profundidad de la cola para Prometheus: trabajos por tipo y estado (en_cola, corriendo), leídos de
    execution_log al raspar /metrics con una consulta agregada; el resultado se guarda unos segundos para que los
    raspados seguidos no carguen la base. Sin base, la métrica sale sin muestras (nunca rompe /metrics)."""

    ESTADOS = ("en_cola", "corriendo")

    def __init__(self, ttl_s: float = 5.0):
        self.ttl_s = ttl_s
        self._guardado: tuple[float, dict] | None = None
        self._candado = threading.Lock()

    def _conteos(self) -> dict | None:
        with self._candado:
            if self._guardado is not None and time.monotonic() - self._guardado[0] < self.ttl_s:
                return self._guardado[1]
        try:
            with sesion_contexto() as s:
                filas = s.execute(text("SELECT tipo, estado, count(*) FROM ai_frecuencias.execution_log "
                                       "WHERE estado IN ('en_cola', 'corriendo') GROUP BY tipo, estado")).all()
        except Exception:  # noqa: BLE001 - sin base no hay profundidad que informar
            log.debug("No se pudo leer la profundidad de la cola", exc_info=True)
            return None
        conteos = {(str(tipo), str(estado)): int(n) for tipo, estado, n in filas}
        with self._candado:
            self._guardado = (time.monotonic(), conteos)
        return conteos

    def collect(self):
        from prometheus_client.core import GaugeMetricFamily

        g = GaugeMetricFamily("api_cola_trabajos", "Trabajos en la cola de PostgreSQL por tipo y estado "
                              "(en_cola incluye los que esperan un reintento)", labels=["tipo", "estado"])
        conteos = self._conteos()
        if conteos is not None:
            for tipo in sorted(set(TIPOS) | {k[0] for k in conteos}):
                for estado in self.ESTADOS:
                    g.add_metric([tipo, estado], conteos.get((tipo, estado), 0))
        yield g
