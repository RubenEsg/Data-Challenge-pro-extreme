"""Planificador interno (§7.2 «APScheduler o proceso programado», §14.2, RNF-004).

Reemplaza el cron externo. Trabajos con cron configurable (zona America/Bogota):
- ejecución diaria (PLAN_EJECUCION_CRON, por omisión «15 5 * * *»): encola una ejecución de frecuencia que lee lo
  nuevo desde la marca de agua y actualiza predicciones, recomendaciones y alertas;
- ciclos intradía (PLAN_INTRADIA_CRON, por omisión «5 6-20 * * *»; vacío los apaga; solo con la captura en vivo,
  FUENTE=postgres), §10.1 «ocupación actual»: encola una ejecución de frecuencia con instante = la franja
  (parametros.intradia), así que la restricción reactiva por ocupación actual actúa en la operación programada: el
  plan del día EN CURSO y las recomendaciones de 30, 60 y 120 min desde la franja usan la ocupación de la última hora
  cerrada. No evalúa el error del modelo ni aplica su política, no lee los consolidados ni pide el refresco de
  segmentos (ejecucion.NOTA_INTRADIA). Una franja que coincide con la del ciclo diario no se encola: el índice único
  (tipo, programada_para) la daría al primero que llegue;
- revisión de reentrenamiento (PLAN_REENTRENAMIENTO_CRON, por omisión «0 4 * * 1»): decide
  app/servicios/politica.decidir_reentreno con los umbrales versionados de threshold_config (periodicidad de
  `reentreno_periodicidad_dias` días de datos nuevos, degradación del WAPE móvil, deriva PSI o cobertura baja) y, si
  corresponde, encola un entrenamiento con corte = datos - 61 días.
- refresco de la agregación de segmentos (PLAN_SEGMENTOS_CRON, por omisión «45 5 * * *», después del ciclo diario;
  solo con la base operacional configurada, FUENTE_DATABASE_URL): encola un trabajo «segmentos» en modo «auto»
  (incremental, o completo cada SEGMENTOS_COMPLETO_DIAS días; app/servicios/segmentos_refresco.py), §6.1, RNF-004.
- retención de datos (PLAN_RETENCION_CRON, por omisión «30 3 * * 0», los domingos antes del ciclo; vacío la apaga):
  encola un trabajo «retencion» que aplica la política de §18 con los parámetros gobernados de threshold_config, o
  solo la simula si retencion_aplicar_programada = 0 (app/servicios/retencion.py, migración 0012).
El entrenamiento registra un CANDIDATO que pasa `sombra_dias` días en sombra. Por omisión (activacion_automatica = 1,
migración 0004) se ACTIVA SOLO si supera la compuerta de sombra de cuatro criterios (WAPE ≤ activo y ≤ wape_max,
cobertura P10-P90 en [cobertura_aviso, cobertura_max] y |sesgo| ≤ sesgo_max), auditado y reversible; con
activacion_automatica = 0 queda «aprobado» y lo activa un admin con POST /models/{id}/activate, que aplica la misma
compuerta en una ventana posterior a lo que vio el candidato.

Idempotente con N réplicas: cada réplica dispara su planificador, pero el trabajo solo hace
INSERT … ON CONFLICT DO NOTHING sobre el índice único (tipo, programada_para); la primera gana y las demás no
encolan nada. La ejecución en sí la toma una sola réplica desde la cola (app/servicios/cola.py).

Con PLAN_PARTICION=ruta (RNF-005) la fila de la franja es la ejecución madre y, en la MISMA transacción y solo si la
franja era nueva, se encola un trabajo por ruta del catálogo: las réplicas procesan rutas distintas a la vez.
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
                               correlation_id, mensaje, programada_para, particion)
VALUES (:id, :tipo, 'en_cola', 0, 0, CAST(:parametros AS jsonb), '{}'::jsonb, :cid, :mensaje, :franja, :particion)
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


def encolar_franja(tipo: str, franja: datetime, parametros: dict[str, Any], motivo: str, *,
                   rutas: list[str] | None = None) -> uuid.UUID | None:
    """Encola una fila por (tipo, franja). Devuelve el execution_id nuevo o None si la franja ya estaba. Con `rutas`
    (RNF-005) la fila es la ejecución madre y sus trabajos por ruta se encolan en la misma transacción."""
    from app.modelos_db import Ejecucion

    with sesion_contexto() as s:
        nuevo = s.execute(_ENCOLAR, {
            "id": uuid.uuid4(), "tipo": tipo, "parametros": json.dumps(parametros, ensure_ascii=False),
            "cid": f"planificador-{tipo}-{franja.astimezone(ZONA):%Y%m%dT%H%M}", "mensaje": motivo,
            "franja": franja, "particion": "ruta" if rutas else None}).scalar()
        if nuevo is not None and rutas:
            from app.servicios import ejecucion

            ejecucion.crear_trabajos_por_ruta(s, s.get(Ejecucion, nuevo), list(rutas))
    return nuevo


YA_ENCOLADA = "ya encolada por otra réplica"


def como_quedo(nuevo: uuid.UUID | None) -> str:
    """Lo que dice el log de una franja del planificador: la ejecución que encoló esta réplica o, si la franja ya
    estaba (INSERT … ON CONFLICT DO NOTHING), que la encoló otra réplica."""
    return f"encolada {nuevo}" if nuevo else YA_ENCOLADA


def rutas_de_la_particion() -> list[str] | None:
    """Rutas del catálogo si PLAN_PARTICION=ruta (un trabajo por ruta); None si la ejecución no se parte."""
    if getattr(obtener_ajustes(), "plan_particion", "ninguna") != "ruta":
        return None
    from app.servicios import datos

    return datos.nombres_rutas()


def tarea_ejecucion_diaria(ahora: datetime | None = None) -> uuid.UUID | None:
    aj = obtener_ajustes()
    ahora = ahora or datetime.now(ZONA)
    franja = franja_actual(disparador(aj.plan_ejecucion_cron), ahora)
    if franja is None:
        return None
    rutas = rutas_de_la_particion()
    particion: dict[str, Any] = {"rutas": rutas} if rutas else {}      # sin partir: la llamada de siempre
    nuevo = encolar_franja("frecuencia", franja, {"notificar": True, "origen": "planificador"} | particion,
                           f"En cola por el planificador (franja {franja.astimezone(ZONA):%Y-%m-%d %H:%M})",
                           **particion)
    _ultimas["frecuencia"] = {"franja": franja.isoformat(), "execution_id": str(nuevo) if nuevo else None,
                              "encolada_por_esta_replica": nuevo is not None, "en": ahora.isoformat()}
    log.info("Planificador: franja %s de frecuencia %s", franja.isoformat(), como_quedo(nuevo))
    return nuevo


ORIGEN_INTRADIA = "planificador_intradia"


def intradia_disponible(aj=None) -> bool:
    """Los ciclos intradía existen con PLAN_INTRADIA_CRON y la fuente de la captura en vivo (FUENTE=postgres: la base
    de Extreme en solo lectura, réplica o producción). En modo offline (FUENTE=parquet, la demostración) los datos no
    llegan dentro del día y un ciclo intradía solo repetiría el plan (y competiría con los ciclos de la demostración por
    la marca de agua), como el refresco de segmentos sin FUENTE_DATABASE_URL."""
    aj = aj or obtener_ajustes()
    return bool(getattr(aj, "plan_intradia_cron", "")) and getattr(aj, "fuente", "parquet") == "postgres"


def tarea_ciclo_intradia(ahora: datetime | None = None) -> uuid.UUID | None:
    """§10.1 ocupación actual en la operación programada: encola la franja del cron intradía (PLAN_INTRADIA_CRON) como
    una ejecución de frecuencia con instante = la franja y parametros.intradia, por el mismo INSERT … ON CONFLICT de la
    ejecución diaria (una sola fila por franja con N réplicas) y, con PLAN_PARTICION=ruta, como madre con un trabajo por
    ruta y la versión de umbrales fijada al crearla. La franja que coincide con la del ciclo diario (los dos crons a la
    misma hora) no se encola: es la del ciclo diario. Una franja que llega con otro ciclo de frecuencia corriendo espera
    en la cola (cola._RECLAMAR no entrega dos trabajos de frecuencia cuyas particiones se cruzan) y lee desde la marca
    que deje el anterior. None si no hay franja, si coincide con la del ciclo diario o si otra réplica ya la encoló.
    Solo con la captura en vivo (FUENTE=postgres, intradia_disponible): con la serie empaquetada no llega nada dentro
    del día y no hay ocupación actual que leer."""
    aj = obtener_ajustes()
    cron = getattr(aj, "plan_intradia_cron", "")
    ahora = ahora or datetime.now(ZONA)
    franja = franja_actual(disparador(cron), ahora) if cron and intradia_disponible(aj) else None
    if franja is None:
        return None
    local = franja.astimezone(ZONA)
    if franja == franja_actual(disparador(aj.plan_ejecucion_cron), ahora):
        _ultimas["frecuencia_intradia"] = {"franja": franja.isoformat(), "execution_id": None, "en": ahora.isoformat(),
                                           "omitida": "coincide con la franja del ciclo diario"}
        log.info("Planificador: franja intradía %s omitida (es la del ciclo diario)", franja.isoformat())
        return None
    rutas = rutas_de_la_particion()
    particion: dict[str, Any] = {"rutas": rutas} if rutas else {}
    parametros = {"notificar": True, "origen": ORIGEN_INTRADIA, "intradia": True, "instante": local.isoformat()}
    nuevo = encolar_franja("frecuencia", franja, parametros | particion,
                           f"Ciclo intradía en cola por el planificador (franja {local:%Y-%m-%d %H:%M})", **particion)
    _ultimas["frecuencia_intradia"] = {"franja": franja.isoformat(), "execution_id": str(nuevo) if nuevo else None,
                                       "encolada_por_esta_replica": nuevo is not None, "en": ahora.isoformat()}
    log.info("Planificador: franja intradía %s %s", franja.isoformat(), como_quedo(nuevo))
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


def _encolar_programada(tipo: str, cron: str, parametros: dict[str, Any], nombre: str,
                        ahora: datetime | None) -> uuid.UUID | None:
    """Encola la franja del cron de un trabajo programado (una sola fila por franja en todo el clúster) y la deja en
    las últimas de esta réplica. None si no hay franja o si otra réplica ya la encoló."""
    ahora = ahora or datetime.now(ZONA)
    franja = franja_actual(disparador(cron), ahora)
    if franja is None:
        return None
    nuevo = encolar_franja(tipo, franja, parametros, f"{nombre} (franja {franja.astimezone(ZONA):%Y-%m-%d %H:%M})")
    _ultimas[tipo] = {"franja": franja.isoformat(), "execution_id": str(nuevo) if nuevo else None,
                      "encolada_por_esta_replica": nuevo is not None, "en": ahora.isoformat()}
    log.info("Planificador: franja %s de %s %s", franja.isoformat(), tipo, como_quedo(nuevo))
    return nuevo


def tarea_refresco_segmentos(ahora: datetime | None = None) -> uuid.UUID | None:
    """Encola la franja del refresco de la agregación de segmentos (modo «auto»), una por franja en todo el clúster."""
    aj = obtener_ajustes()
    if not getattr(aj, "fuente_database_url", ""):
        return None
    return _encolar_programada("segmentos", aj.plan_segmentos_cron, {"modo": "auto", "origen": "planificador"},
                               "Refresco de la agregación de segmentos", ahora)


def tarea_retencion(ahora: datetime | None = None) -> uuid.UUID | None:
    """§18 retención: encola la franja de la corrida programada de la política (PLAN_RETENCION_CRON). Si aplica o solo
    simula lo decide al correr el parámetro gobernado retencion_aplicar_programada (app/servicios/retencion.py)."""
    aj = obtener_ajustes()
    cron = getattr(aj, "plan_retencion_cron", "")
    if not cron:
        return None
    return _encolar_programada("retencion", cron, {"origen": "planificador"}, "Retención de datos (§18)", ahora)


def trabajos_programados(aj=None) -> list[tuple[str, str, Any, str]]:
    """(id, cron, tarea, nombre) de cada trabajo del planificador. Los ciclos intradía existen con PLAN_INTRADIA_CRON
    y la captura en vivo (intradia_disponible: FUENTE=postgres), el refresco de segmentos solo con la base operacional
    configurada (sin ella la capa de segmentos no tiene de dónde leer) y la retención con PLAN_RETENCION_CRON (por
    omisión, los domingos a las 03:30; vacío la apaga)."""
    aj = aj or obtener_ajustes()
    trabajos = [("ejecucion_diaria", aj.plan_ejecucion_cron, tarea_ejecucion_diaria,
                 "Ejecución de frecuencia programada"),
                ("reentrenamiento", aj.plan_reentrenamiento_cron, tarea_reentrenamiento, "Revisión de reentrenamiento")]
    if intradia_disponible(aj):
        trabajos.append(("ciclo_intradia", aj.plan_intradia_cron, tarea_ciclo_intradia,
                         "Ciclo intradía de frecuencia (§10.1 ocupación actual)"))
    if getattr(aj, "fuente_database_url", ""):
        trabajos.append(("refresco_segmentos", getattr(aj, "plan_segmentos_cron", "45 5 * * *"),
                         tarea_refresco_segmentos, "Refresco de la agregación de segmentos"))
    if getattr(aj, "plan_retencion_cron", ""):
        trabajos.append(("retencion", aj.plan_retencion_cron, tarea_retencion, "Retención de datos (§18)"))
    return trabajos


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
        for ident, cron, tarea, nombre in trabajos_programados(aj):
            p.add_job(tarea, disparador(cron), id=ident, name=nombre)
        p.start()
        _planificador = p
    log.info("Planificador activo: %s (America/Bogota)",
             ", ".join(f"{ident} «{cron}»" for ident, cron, _t, _n in trabajos_programados(aj)))
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
    for ident, cron, _tarea, _nombre in trabajos_programados(aj):
        proxima = _proxima_ejecucion(ident, cron)
        trabajos.append({"id": ident, "cron": cron, "proxima": proxima.isoformat() if proxima else None})
    with sesion_contexto() as s:   # origen: «planificador» (ciclo diario) o «planificador_intradia» (ciclo intradía)
        franjas = [_texto_franja(dict(f._mapping)) for f in s.execute(text("""
            SELECT tipo, programada_para, execution_id, estado, worker_id, intentos, terminado_en, particion,
                   parametros->>'origen' AS origen
              FROM ai_frecuencias.execution_log WHERE programada_para IS NOT NULL
             ORDER BY programada_para DESC LIMIT 10"""))]
    return {"habilitado": aj.planificador_habilitado, "activo_en_esta_replica": _planificador is not None,
            "zona": "America/Bogota", "particion": getattr(aj, "plan_particion", "ninguna"), "trabajos": trabajos,
            "franjas_recientes": franjas, "ultimas_en_esta_replica": _ultimas}
