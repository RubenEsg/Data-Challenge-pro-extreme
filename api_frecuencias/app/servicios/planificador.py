"""Planificador interno (§7.2 «APScheduler o proceso programado», §14.2, RNF-004).

Reemplaza el cron externo. Dos trabajos con cron configurable (zona America/Bogota):
- ejecución diaria (PLAN_EJECUCION_CRON, por omisión «15 5 * * *»): encola una ejecución de frecuencia que lee lo
  nuevo desde la marca de agua y actualiza predicciones, recomendaciones y alertas;
- revisión de reentrenamiento (PLAN_REENTRENAMIENTO_CRON, por omisión «0 4 * * 1»): decide
  app/servicios/politica.decidir_reentreno con los umbrales versionados de threshold_config (periodicidad de
  `reentreno_periodicidad_dias` días de datos nuevos, degradación del WAPE móvil, deriva PSI o cobertura baja) y, si
  corresponde, encola un entrenamiento con corte = datos - 61 días.
El entrenamiento registra un CANDIDATO que pasa `sombra_dias` días en sombra. Por omisión (activacion_automatica = 1,
migración 0004) se ACTIVA SOLO si supera la compuerta de sombra de cuatro criterios (WAPE ≤ activo y ≤ wape_max,
cobertura P10-P90 en [cobertura_aviso, cobertura_max] y |sesgo| ≤ sesgo_max), auditado y reversible; con
activacion_automatica = 0 queda «aprobado» y lo activa un admin con POST /models/{id}/activate, que aplica la misma
compuerta en una ventana posterior a lo que vio el candidato.

Idempotente con N réplicas: cada réplica dispara su planificador, pero el trabajo solo hace
INSERT … ON CONFLICT DO NOTHING sobre el índice único (tipo, programada_para); la primera gana y las demás no
encolan nada. La ejecución en sí la toma una sola réplica desde la cola (app/servicios/cola.py).
"""
from __future__ import annotations

import json
import logging
import threading
import uuid
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import text

from app.config import obtener_ajustes
from app.db import sesion_contexto

log = logging.getLogger("api_frecuencias.planificador")
ZONA = ZoneInfo("America/Bogota")
_planificador = None
_cerrojo = threading.Lock()
_ultimas: dict[str, dict[str, Any]] = {}

_ENCOLAR = text("""
INSERT INTO ai_frecuencias.execution_log (execution_id, tipo, estado, progreso, intentos, parametros, metricas,
                               correlation_id, mensaje, programada_para)
VALUES (:id, :tipo, 'en_cola', 0, 0, CAST(:parametros AS jsonb), '{}'::jsonb, :cid, :mensaje, :franja)
ON CONFLICT (tipo, programada_para) WHERE programada_para IS NOT NULL DO NOTHING
RETURNING execution_id
""")


_DIAS = ("sun", "mon", "tue", "wed", "thu", "fri", "sat", "sun")


def disparador(expresion: str):
    """Expresión crontab estándar de 5 campos -> CronTrigger de APScheduler en America/Bogota.

    APScheduler 3.x numera el día de la semana desde el lunes (0 = lunes) incluso en from_crontab; aquí se traduce
    la numeración estándar de cron (0 o 7 = domingo, 1 = lunes) a nombres para que «0 4 * * 1» sea el lunes.
    """
    import re

    from apscheduler.triggers.cron import CronTrigger

    campos = expresion.split()
    if len(campos) == 5:
        campos[4] = re.sub(r"(?<![/\d])[0-7](?!\d)", lambda m: _DIAS[int(m.group())], campos[4])
    return CronTrigger.from_crontab(" ".join(campos), timezone=ZONA)


def franja_actual(trigger, ahora: datetime, ventana: timedelta = timedelta(hours=1)) -> datetime | None:
    """Última hora de disparo del cron que no es posterior a `ahora` (dentro de `ventana`); None si no hay.

    Dos réplicas que disparan el mismo cron calculan la misma franja aunque una llegue unos segundos tarde.
    """
    ahora = ahora if ahora.tzinfo else ahora.replace(tzinfo=ZONA)
    t = trigger.get_next_fire_time(None, ahora - ventana)
    ultima = None
    while t is not None and t <= ahora:
        ultima = t
        t = trigger.get_next_fire_time(t, t + timedelta(seconds=1))
    return ultima


def encolar_franja(tipo: str, franja: datetime, parametros: dict[str, Any], motivo: str) -> uuid.UUID | None:
    """Encola una fila por (tipo, franja). Devuelve el execution_id nuevo o None si la franja ya estaba."""
    with sesion_contexto() as s:
        nuevo = s.execute(_ENCOLAR, {
            "id": uuid.uuid4(), "tipo": tipo, "parametros": json.dumps(parametros, ensure_ascii=False),
            "cid": f"planificador-{tipo}-{franja.astimezone(ZONA):%Y%m%dT%H%M}", "mensaje": motivo,
            "franja": franja}).scalar()
    return nuevo


def tarea_ejecucion_diaria(ahora: datetime | None = None) -> uuid.UUID | None:
    aj = obtener_ajustes()
    ahora = ahora or datetime.now(ZONA)
    franja = franja_actual(disparador(aj.plan_ejecucion_cron), ahora)
    if franja is None:
        return None
    nuevo = encolar_franja("frecuencia", franja, {"notificar": True, "origen": "planificador"},
                           f"En cola por el planificador (franja {franja.astimezone(ZONA):%Y-%m-%d %H:%M})")
    _ultimas["frecuencia"] = {"franja": franja.isoformat(), "execution_id": str(nuevo) if nuevo else None,
                              "encolada_por_esta_replica": nuevo is not None, "en": ahora.isoformat()}
    log.info("Planificador: franja %s de frecuencia %s", franja.isoformat(),
             f"encolada {nuevo}" if nuevo else "ya encolada por otra réplica")
    return nuevo


def evaluar_reentrenamiento() -> dict[str, Any]:
    """¿Hace falta un candidato nuevo? Decide app/servicios/politica.py (periodicidad, degradación, deriva o
    cobertura, con umbrales versionados); corte = datos - 61 días, así que la validación usa solo datos reales."""
    from app.servicios import ejecucion, politica

    with sesion_contexto() as s:
        _, umbrales = ejecucion.umbrales_vigentes(s)
        decision = politica.decidir_reentreno(s, umbrales)
    decision.setdefault("hasta", None)
    return decision


def tarea_reentrenamiento(ahora: datetime | None = None) -> uuid.UUID | None:
    aj = obtener_ajustes()
    ahora = ahora or datetime.now(ZONA)
    franja = franja_actual(disparador(aj.plan_reentrenamiento_cron), ahora)
    if franja is None:
        return None
    decision = evaluar_reentrenamiento()
    nuevo = None
    if decision["reentrenar"]:
        nuevo = encolar_franja("entrenamiento", franja, {
            "hasta": decision["hasta"], "datos_hasta": decision.get("datos_hasta"), "semilla": 42,
            "solicitado_por": "planificador",
            "motivo": "; ".join(decision["motivos"])}, "Reentrenamiento programado: " + "; ".join(decision["motivos"]))
    _ultimas["entrenamiento"] = {"franja": franja.isoformat(), "execution_id": str(nuevo) if nuevo else None,
                                 "decision": decision, "en": ahora.isoformat()}
    log.info("Planificador: revisión de reentrenamiento %s -> %s", franja.isoformat(), decision)
    return nuevo


def iniciar() -> bool:
    """Arranca el BackgroundScheduler si PLANIFICADOR_HABILITADO=true. Idempotente."""
    global _planificador
    aj = obtener_ajustes()
    if not aj.planificador_habilitado:
        return False
    with _cerrojo:
        if _planificador is not None:
            return True
        from apscheduler.schedulers.background import BackgroundScheduler

        p = BackgroundScheduler(timezone=ZONA, job_defaults={"coalesce": True, "misfire_grace_time": 3600,
                                                             "max_instances": 1})
        p.add_job(tarea_ejecucion_diaria, disparador(aj.plan_ejecucion_cron), id="ejecucion_diaria",
                  name="Ejecución de frecuencia programada")
        p.add_job(tarea_reentrenamiento, disparador(aj.plan_reentrenamiento_cron), id="reentrenamiento",
                  name="Revisión de reentrenamiento")
        p.start()
        _planificador = p
    log.info("Planificador activo: ejecución «%s», reentrenamiento «%s» (America/Bogota)",
             aj.plan_ejecucion_cron, aj.plan_reentrenamiento_cron)
    return True


def detener() -> None:
    global _planificador
    with _cerrojo:
        if _planificador is not None:
            _planificador.shutdown(wait=False)
            _planificador = None


def _proxima_ejecucion(ident: str, cron: str):
    """Próximo disparo de un trabajo: el del planificador vivo si lo tiene; si no, el que daría su cron."""
    if _planificador is not None and _planificador.get_job(ident) is not None:
        return _planificador.get_job(ident).next_run_time
    try:
        return disparador(cron).get_next_fire_time(None, datetime.now(ZONA))
    except ValueError:
        return None


def _texto_franja(f: dict) -> dict:
    """Fila de execution_log lista para JSON: instantes en ISO 8601 y UUID como texto."""
    return {k: v.isoformat() if isinstance(v, datetime) else (str(v) if isinstance(v, uuid.UUID) else v)
            for k, v in f.items()}


def estado() -> dict[str, Any]:
    """Para GET /api/v1/scheduler: configuración, próximos disparos y últimas franjas encoladas (de la base)."""
    aj = obtener_ajustes()
    trabajos = []
    for ident, cron in (("ejecucion_diaria", aj.plan_ejecucion_cron),
                        ("reentrenamiento", aj.plan_reentrenamiento_cron)):
        proxima = _proxima_ejecucion(ident, cron)
        trabajos.append({"id": ident, "cron": cron, "proxima": proxima.isoformat() if proxima else None})
    with sesion_contexto() as s:
        franjas = [_texto_franja(dict(f._mapping)) for f in s.execute(text("""
            SELECT tipo, programada_para, execution_id, estado, worker_id, intentos, terminado_en
              FROM ai_frecuencias.execution_log WHERE programada_para IS NOT NULL
             ORDER BY programada_para DESC LIMIT 10"""))]
    return {"habilitado": aj.planificador_habilitado, "activo_en_esta_replica": _planificador is not None,
            "zona": "America/Bogota", "trabajos": trabajos, "franjas_recientes": franjas,
            "ultimas_en_esta_replica": _ultimas}
