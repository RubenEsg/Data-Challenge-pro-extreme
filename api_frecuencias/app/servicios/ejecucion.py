"""Orquestación de una ejecución (RF-013, RNF-001, RNF-004, RNF-011).

Ciclo: lectura incremental por marca de agua -> calidad con los catálogos de la fuente (errores por lote, llave,
valor y causa) -> histórico propio sin duplicados -> evaluación del error del modelo activo sobre lo recién llegado ->
predicciones 30/60/120 por ruta -> recomendaciones -> alertas deduplicadas y escaladas -> notificaciones simuladas ->
plan del día siguiente por ruta y hora (recomendaciones origen='plan_dia') y foto de la respuesta del reto -> al cerrar,
una vez por ejecución, los consolidados de Extreme (timbradas_consolidado y las dos tablas por segmento: lectura con su
marca por tabla, calidad y contraste con la agregación propia; app/servicios/consolidados.py).
Cada fila de resultados guarda las dimensiones de §8.3 (app/servicios/dimensiones.py).

Los resultados de un intento se escriben en UNA transacción: si el intento falla no quedan resultados parciales y el
reintento parte limpio. El progreso se guarda aparte (transacciones cortas) para poder consultarlo mientras corre.
Todo queda ligado a execution_id, model_id, feature_version, versión de umbrales y data_cutoff.

Partición por ruta y fecha (RNF-005, migración 0009): la marca de agua es por proceso y ruta
(ai_frecuencias.marca_agua_ruta). Una ejecución se puede partir (particion = «ruta») en un trabajo por ruta de la
fecha pedida (`hasta`); sin `rutas`, uno por cada ruta del catálogo. Cada trabajo lee solo su ruta desde la marca de
esa ruta, con el candado de su ruta (dos trabajos de la misma ruta nunca corren a la vez; los de rutas distintas, sí,
en réplicas distintas) y hace todo lo que es de la ruta: calidad, histórico, predicciones, recomendaciones, alertas,
notificaciones, plan del día y foto de la respuesta. La ejecución madre corre cuando terminan sus trabajos y cierra,
una vez por ejecución, lo que es del modelo: la fila de monitoreo (§9.4), el retador en sombra y la política
(RF-018/RF-019). Una ejecución sin partir es un trabajo de todas las rutas: lee cada ruta desde su marca y deja
todas en la misma frontera, igual que la marca global de antes.
"""
from __future__ import annotations

import copy
import logging
import math
import re
import threading
import time
import uuid
from collections import Counter
from contextlib import nullcontext
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from datetime import time as dtime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from prometheus_client import Histogram
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import obtener_ajustes
from app.db import sesion_contexto
from app.modelos_db import (
    Alerta,
    Ejecucion,
    ErrorCalidad,
    HistorialAlerta,
    MarcaAguaRuta,
    Notificacion,
    Prediccion,
    Recomendacion,
    RegistroModelo,
    Umbral,
)

ZONA = ZoneInfo("America/Bogota")
ESTADOS_CERRADOS = ("cerrada", "descartada")
HORIZONTES = (30, 60, 120)
log = logging.getLogger("api_frecuencias.ejecucion")
# RNF-005: llave de la frontera de las lecturas de todas las rutas en marca_agua_ruta y candados de asesoría de la
# partición (dos enteros: clave, subclave) y de la política del modelo
RUTA_FRONTERA = "*"
PARTICION_RUTA = "ruta"
CLAVE_PARTICION_TODAS = 7442     # (clave, 0): exclusiva para un trabajo de todas las rutas, compartida para uno de ruta
CLAVE_PARTICION_RUTA = 7443      # (clave, hashtext(ruta)): un solo trabajo de esa ruta a la vez
CLAVE_MODELO = 7444              # (clave, 0): la política del modelo (reversión, compuerta, reentreno), una a la vez


class ErrorNoReintentable(Exception):
    """Falla de configuración o de datos que no se arregla reintentando."""


class ParticionOcupada(Exception):
    """Otro proceso tiene el candado de la ruta (o de todas las rutas): el intento se reintenta con espera."""


# ---------------------------------------------------------------- utilidades
def ahora() -> datetime:
    return datetime.now(UTC)


def a_instante(valor: Any) -> datetime | None:
    """date | datetime | str ISO -> datetime con zona (sin zona se asume America/Bogota)."""
    if valor is None:
        return None
    if isinstance(valor, str):
        valor = datetime.fromisoformat(valor) if "T" in valor or " " in valor else date.fromisoformat(valor)
    if isinstance(valor, datetime):
        if hasattr(valor, "to_pydatetime"):
            valor = valor.to_pydatetime()
        return valor if valor.tzinfo else valor.replace(tzinfo=ZONA)
    if isinstance(valor, date):
        return datetime.combine(valor, dtime(0), tzinfo=ZONA)
    raise TypeError(f"No se puede convertir {valor!r} a instante")


def json_seguro(obj: Any) -> Any:
    """Convierte numpy/pandas/fechas/Decimal a tipos JSON."""
    if obj is None or isinstance(obj, (bool, str, int)):
        return obj
    if isinstance(obj, float):
        return None if math.isnan(obj) or math.isinf(obj) else obj
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, uuid.UUID):
        return str(obj)
    if isinstance(obj, dict):
        return {str(k): json_seguro(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [json_seguro(v) for v in obj]
    if hasattr(obj, "item"):
        try:
            return json_seguro(obj.item())
        except (ValueError, TypeError):
            pass
    if hasattr(obj, "tolist"):
        return json_seguro(obj.tolist())
    return str(obj)


def _num(valor: Any) -> float | None:
    if valor is None:
        return None
    try:
        f = float(valor)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) or math.isinf(f) else f


def dimensiones_fila(ruta: Any, cuando: Any) -> dict[str, Any]:
    """§8.3: idruta, idempresa, idproceso, id_dia_semana e id_estacionalidad de una fila de resultados. Si el catálogo
    no responde quedan nulas: una dimensión que falta nunca detiene el ciclo."""
    from app.servicios import dimensiones

    try:
        return dimensiones.dimensiones(ruta, cuando)
    except Exception as exc:  # noqa: BLE001
        log.warning("dimensiones de %s no disponibles: %s", ruta, exc)
        return dict.fromkeys(dimensiones.CAMPOS)


def empresa_de(ruta: Any) -> str | None:
    """Empresa de la ruta según el catálogo (catálogo empaquetado o nombre del proceso en "Procesos")."""
    from app.servicios import dimensiones

    try:
        return dimensiones.empresa(ruta)
    except Exception as exc:  # noqa: BLE001
        log.info("empresa de %s no disponible: %s", ruta, exc)
        return None


def serie_de_la_sesion(s: Session):
    """RF-013: dentro del bloque, la inferencia arma las variables con la serie validada de la sesión (lo que llegó en
    esta ejecución incluido), si el módulo de inferencia lo permite; si no, con la serie empaquetada."""
    from app.servicios import inferencia

    con_sesion = getattr(inferencia, "con_sesion", None)
    return con_sesion(s) if con_sesion is not None else nullcontext()


# ---------------------------------------------------------------- umbrales (§5.1, regla de gobierno)
def umbrales_vigentes(sesion: Session) -> tuple[int, dict[str, Any]]:
    filas = sesion.scalars(select(Umbral).where(Umbral.vigente)).all()
    version = max((f.version for f in filas), default=0)
    return version, {f.nombre: f.valor for f in filas}


def umbrales_de_la_ejecucion(sesion: Session, parametros: dict) -> tuple[int, dict[str, Any]]:
    """La versión de umbrales con que corre un ciclo: la vigente o, en una ejecución partida por ruta (RNF-005), la que
    estaba vigente al crearla (`umbrales_version` de sus parámetros, crear_trabajos_por_ruta). Así la madre y todos
    sus trabajos usan la misma versión de umbrales y de parámetros del plan (§5.1) aunque llegue un PUT /thresholds
    mientras corren; la ejecución siguiente ya usa la nueva. Si esa versión ya no existe, rige la vigente."""
    version = parametros.get("umbrales_version")
    if version is not None:
        filas = sesion.scalars(select(Umbral).where(Umbral.version == int(version))).all()
        if filas:
            return int(version), {f.nombre: f.valor for f in filas}
    return umbrales_vigentes(sesion)


SQL_CANDADO_UMBRALES = text("SELECT pg_advisory_xact_lock(hashtext('ai_frecuencias.threshold_config'))")


def bloquear_umbrales(sesion: Session) -> None:
    """§5.1 «se versionan»: un solo cambio del conjunto gobernado a la vez. Toma un candado de PostgreSQL de la
    transacción (pg_advisory_xact_lock; se suelta con el commit o el rollback) antes de leer la versión vigente. Lo
    usan PUT /thresholds (nueva_version_umbrales) y los ajustes locales de capacidad, flota y ciclo
    (catalogos.versionar_ajustes). Sin él, dos cambios simultáneos partían de la misma versión: el segundo, al
    despertar del FOR UPDATE, ya no veía filas vigentes y dejaba una versión con solo su parámetro (el resto del
    conjunto dejaba de regir), o chocaba con la unicidad de (nombre, version) y respondía 500. Con el candado, el
    segundo espera y parte de la versión que dejó el primero."""
    sesion.execute(SQL_CANDADO_UMBRALES)


def nueva_version_umbrales(sesion: Session, valores: dict[str, Any], creado_por: str, motivo: str | None) -> int:
    """Cada cambio crea una versión nueva del conjunto completo; la anterior queda como histórico. Un cambio a la vez
    (bloquear_umbrales)."""
    from app.servicios import consolidados, flota_ciclo, retencion
    from app.servicios.optimizacion import (
        PARAMETROS_OBJETIVO,
        PARAMETROS_PLAN,
        descripcion_parametro,
        validar_parametros_objetivo,
        validar_parametros_plan,
    )

    bloquear_umbrales(sesion)
    filas = sesion.scalars(select(Umbral).where(Umbral.vigente)).all()
    actuales = {f.nombre: f for f in filas}
    # §10.2 y §5.1: los pesos y costos de la función objetivo y los parámetros del plan del día (tarifa, elasticidad y
    # suavidad) también se versionan aquí (si no están, rige el código)
    validos = set(actuales) | set(PARAMETROS_OBJETIVO) | set(PARAMETROS_PLAN)
    desconocidos = sorted(set(valores) - validos)
    if desconocidos:
        raise ValueError(f"Parámetros desconocidos: {', '.join(desconocidos)}. Válidos: {', '.join(sorted(validos))}")
    combinados = {n: f.valor for n, f in actuales.items()} | valores
    validar_parametros_objetivo(combinados)
    validar_parametros_plan(combinados)
    retencion.validar_parametros(combinados)          # §18: meses en caliente y banderas de la política de retención
    flota_ciclo.validar_ajustes(valores)
    consolidados.validar_tolerancias(combinados)   # §6.3, §11.2: tolerancias del contraste de los consolidados
    for nombre, valor in valores.items():
        if _num(valor) is None or float(valor) < 0:
            raise ValueError(f"El parámetro {nombre} debe ser un número no negativo")
    for nombre in ("ocupacion_objetivo_min", "ocupacion_objetivo_max", "ocupacion_critica", "baja_utilizacion",
                   "error_pronostico", "caida_demanda", "tolerancia_salidas", "wape_max", "alt003_probabilidad_minima"):
        if nombre in combinados and not 0 < float(combinados[nombre]) <= 1.5:
            raise ValueError(f"{nombre} es una fracción (0, 1.5]; se recibió {combinados[nombre]}")
    if float(combinados.get("ocupacion_objetivo_min", 0)) > float(combinados.get("ocupacion_objetivo_max", 1)):
        raise ValueError("ocupacion_objetivo_min no puede superar ocupacion_objetivo_max")
    if float(combinados.get("headway_minimo_min", 0)) > float(combinados.get("headway_maximo_min", 1e9)):
        raise ValueError("headway_minimo_min no puede superar headway_maximo_min")
    nueva = (sesion.scalar(select(func.max(Umbral.version))) or 0) + 1
    sesion.execute(update(Umbral).where(Umbral.vigente).values(vigente=False))
    sesion.flush()
    for nombre, valor in combinados.items():
        descripcion = actuales[nombre].descripcion if nombre in actuales else descripcion_parametro(nombre)
        sesion.add(Umbral(nombre=nombre, valor=valor, descripcion=descripcion, version=nueva,
                          vigente=True, creado_por=creado_por, motivo=motivo))
    sesion.commit()
    return nueva


# ---------------------------------------------------------------- registro de modelos
def modelo_activo(sesion: Session) -> RegistroModelo | None:
    return sesion.scalar(select(RegistroModelo).where(RegistroModelo.estado == "activo"))


def registrar_modelo(sesion: Session, info: dict, estado: str = "candidato",
                     execution_id: uuid.UUID | None = None) -> RegistroModelo:
    """Guarda (o actualiza) la ficha de un modelo devuelto por inferencia.entrenar()."""
    existente = sesion.scalar(select(RegistroModelo).where(RegistroModelo.model_id == info["model_id"]))
    tipo = info.get("tipo") if info.get("tipo") in ("linea_base", "candidato") else "candidato"
    campos = dict(
        version=str(info.get("version") or info["model_id"]),
        tipo=tipo,
        artefacto=str(info.get("artefacto") or ""),
        sha256=str(info.get("sha256") or ""),
        feature_version=str(info.get("feature_version") or ""),
        data_cutoff=a_instante(info.get("data_cutoff")),
        metricas=json_seguro(info.get("metricas") or {}),
    )
    if existente is not None:
        if existente.estado == "activo":  # nunca se sobrescribe la ficha (ni el sha256) del modelo activo
            existente.auditoria = [*(existente.auditoria or []), json_seguro({
                "evento": "registro_omitido", "en": ahora().isoformat(), "execution_id": execution_id,
                "motivo": "el modelo activo no se sobrescribe; un reentrenamiento con el mismo id debe usar otro id",
                "sha256_recibido": campos["sha256"]})]
            return existente
        for k, v in campos.items():
            setattr(existente, k, v)
        return existente
    registro = RegistroModelo(model_id=info["model_id"], estado=estado, execution_id=execution_id,
                              auditoria=[{"evento": "registro", "estado": estado, "en": ahora().isoformat()}],
                              **campos)
    sesion.add(registro)
    sesion.flush()
    return registro


def sembrar_registro(sesion: Session) -> int:
    """Si el registro está vacío, registra los modelos ya entrenados que publique inferencia (si los expone)."""
    if sesion.scalar(select(func.count()).select_from(RegistroModelo)):
        return 0
    try:
        from app.servicios import inferencia
    except Exception:  # noqa: BLE001 - el módulo de modelo puede no estar listo todavía
        return 0
    listar = getattr(inferencia, "modelos_disponibles", None) or getattr(inferencia, "listar_modelos", None)
    if listar is None:
        return 0
    fichas = [f for f in listar() if f.get("model_id") and f.get("ejecutable_en_api", True)
              and f.get("tipo") in ("linea_base", "candidato", None)]
    if not fichas:
        return 0
    base = next((f for f in fichas if f.get("activo") or f.get("estado") == "activo"), None) or \
        next((f for f in fichas if f.get("tipo") == "linea_base"), fichas[0])
    for ficha in fichas:
        r = registrar_modelo(sesion, ficha, estado="candidato")
        if ficha is base:
            r.estado = "activo"
            r.aprobado_por = "sistema (arranque)"
            r.activado_en = ahora()
            r.auditoria = [*r.auditoria, {"evento": "activacion_inicial", "en": ahora().isoformat()}]
    sesion.commit()
    return len(fichas)


# ---------------------------------------------------------------- ejecuciones
def _traceparent_actual() -> str | None:
    """W3C traceparent del span en curso (None sin traza activa), para guardarlo en execution_log."""
    try:
        from opentelemetry.propagate import inject

        portador: dict[str, str] = {}
        inject(portador)
        return portador.get("traceparent")
    except Exception:  # noqa: BLE001 - sin OpenTelemetry la ejecución se crea igual
        return None


def crear_ejecucion(sesion: Session, tipo: str, parametros: dict, correlation_id: str | None) -> Ejecucion:
    e = Ejecucion(execution_id=uuid.uuid4(), tipo=tipo, estado="en_cola", progreso=0, intentos=0,
                  parametros=json_seguro(parametros), metricas={}, correlation_id=correlation_id, mensaje="En cola",
                  traceparent=_traceparent_actual())
    sesion.add(e)
    sesion.commit()
    return e


def crear_trabajos_por_ruta(sesion: Session, madre: Ejecucion, rutas: list[str]) -> list[Ejecucion]:
    """RNF-005: un trabajo de frecuencia por ruta, hijo de la ejecución madre, con los mismos parámetros (fecha
    `hasta`, instante, horizontes, modelo, notificar, plan del día) y rutas = [su ruta]. Cada uno se inserta con
    clock_timestamp() para que la cola los reparta en el orden de las rutas. La versión de umbrales vigente queda
    fijada en los parámetros de la madre y de sus trabajos (umbrales_de_la_ejecucion): toda la ejecución usa la misma.
    No confirma: va en la transacción de quien crea la madre (todo o nada)."""
    version_u, _ = umbrales_vigentes(sesion)
    madre.parametros = json_seguro(dict(madre.parametros or {}, umbrales_version=version_u))
    base = dict(madre.parametros)
    trabajos = []
    for ruta in rutas:
        t = Ejecucion(execution_id=uuid.uuid4(), tipo="frecuencia", estado="en_cola", progreso=0, intentos=0,
                      parametros=json_seguro(base | {"rutas": [ruta]}), metricas={},
                      correlation_id=madre.correlation_id, mensaje=f"En cola: ruta {ruta}",
                      traceparent=madre.traceparent, ruta=ruta, padre_id=madre.execution_id,
                      creado_en=func.clock_timestamp())
        sesion.add(t)
        sesion.flush()
        trabajos.append(t)
    return trabajos


def crear_ejecucion_partida(sesion: Session, parametros: dict, correlation_id: str | None,
                            rutas: list[str]) -> tuple[Ejecucion, list[Ejecucion]]:
    """RNF-005: la ejecución madre (particion = «ruta») y un trabajo por ruta, en una sola transacción. La madre no
    lee: la cola la entrega cuando terminan sus trabajos y entonces cierra lo que es del modelo."""
    madre = Ejecucion(execution_id=uuid.uuid4(), tipo="frecuencia", estado="en_cola", progreso=0, intentos=0,
                      parametros=json_seguro(dict(parametros, rutas=list(rutas))), metricas={},
                      correlation_id=correlation_id, mensaje=f"En cola: espera a sus {len(rutas)} trabajos por ruta",
                      traceparent=_traceparent_actual(), particion=PARTICION_RUTA, creado_en=func.clock_timestamp())
    sesion.add(madre)
    sesion.flush()
    trabajos = crear_trabajos_por_ruta(sesion, madre, rutas)
    sesion.commit()
    return madre, trabajos


ETAPAS = Histogram("api_ejecucion_etapa_segundos", "Duración de cada etapa de una ejecución (lectura_incremental, "
                   "calidad, prediccion, alertas, notificaciones, plan_dia, entrenamiento, registro, respuesta)",
                   ["etapa"], buckets=(0.1, 0.5, 1, 2.5, 5, 10, 30, 60, 120, 300, 600, 1800))
# RNF-006: la etiqueta «etapa» de ETAPAS es el NOMBRE de la etapa, de este conjunto cerrado (las de cada tipo de
# trabajo de la cola); el detalle (el tramo y las fechas del refresco de segmentos, la tabla de la retención) queda en
# la columna etapa de execution_log, en las métricas del trabajo y en el log. Así una ejecución con otras fechas no crea
# una serie nueva en Prometheus: lo que no es un nombre conocido cuenta en ETAPA_OTRA.
ETAPAS_METRICA = frozenset({
    "lectura_incremental", "calidad", "prediccion", "alertas", "notificaciones", "plan_dia", "cierre_modelo",
    "entrenamiento", "registro", "respuesta", "planificacion", "lectura_fuente", "agregacion", "foto_de_variables",
    "simulacion", "derivada"})
ETAPA_OTRA = "otra"
_NOMBRE_DE_ETAPA = re.compile(r"([a-z_]+)(?:\s.*|\(.*)?", re.DOTALL)
_etapas_en_curso: dict[uuid.UUID, tuple[str, float]] = {}
_etapas_candado = threading.Lock()


def etiqueta_etapa(etapa: str | None) -> str:
    """La etiqueta de la etapa en ETAPAS: su nombre sin el detalle que lo sigue tras un espacio o un paréntesis
    («lectura_fuente 1/2 (2023-01-01 a 2023-01-31)» -> lectura_fuente) si es uno de ETAPAS_METRICA; si no (otra forma,
    como «grupo: tabla»), ETAPA_OTRA. El conjunto de etiquetas queda acotado por construcción."""
    coincide = _NOMBRE_DE_ETAPA.fullmatch(str(etapa or "").strip())
    return coincide.group(1) if coincide and coincide.group(1) in ETAPAS_METRICA else ETAPA_OTRA


def _medir_etapa(execution_id: uuid.UUID, etapa: str | None) -> None:
    """Cierra la etapa anterior de la ejecución en la métrica ETAPAS y abre la nueva (None = la ejecución terminó)."""
    instante = time.perf_counter()
    with _etapas_candado:
        previa = _etapas_en_curso.pop(execution_id, None)
        if etapa is not None:
            _etapas_en_curso[execution_id] = (etapa, instante)
    if previa is not None:
        ETAPAS.labels(etiqueta_etapa(previa[0])).observe(instante - previa[1])


def cerrar_etapa(execution_id: uuid.UUID) -> None:
    """La cola lo llama al terminar cada intento: la última etapa queda medida."""
    _medir_etapa(execution_id, None)


def _avance(execution_id: uuid.UUID, progreso: float, etapa: str, *, detalle: str | None = None,
            **campos: Any) -> None:
    """Progreso del trabajo. `etapa` es el nombre de la etapa (la etiqueta de ETAPAS y el span «ejecucion.<etapa>»);
    `detalle` (por ejemplo, el tramo y las fechas que lee el refresco de segmentos) solo se agrega a la columna etapa
    de execution_log, que GET /frequency/executions/{id} muestra mientras corre."""
    _medir_etapa(execution_id, etapa)
    with sesion_contexto() as s:
        s.execute(update(Ejecucion).where(Ejecucion.execution_id == execution_id)
                  .values(progreso=progreso, etapa=f"{etapa} {detalle}" if detalle else etapa,
                          actualizado_en=ahora(), **campos))


def ultima_marca_agua(sesion: Session) -> datetime | None:
    return sesion.scalar(select(func.max(Ejecucion.marca_agua_nueva))
                         .where(Ejecucion.tipo == "frecuencia", Ejecucion.estado == "ok"))


def estado_fuente_anterior(sesion: Session) -> dict | None:
    """Huellas de la ventana de solape que guardó la última ejecución ok (fuentes.py): con ellas la
    lectura siguiente entrega una fila tardía o modificada exactamente una vez. Se confirman con los resultados."""
    metricas = sesion.scalar(select(Ejecucion.metricas)
                             .where(Ejecucion.tipo == "frecuencia", Ejecucion.estado == "ok",
                                    Ejecucion.marca_agua_nueva.is_not(None))
                             .order_by(Ejecucion.marca_agua_nueva.desc(), Ejecucion.terminado_en.desc()).limit(1))
    estado = (metricas or {}).get("fuente_estado")
    return estado if isinstance(estado, dict) else None


# ---------------------------------------------------------------- partición por ruta (RNF-005)
def proceso_de_la_fuente(fuente: Any) -> str:
    """Llave del proceso en la marca por ruta: el proceso que lee la fuente (FUENTE_PROCESO; «*» = todos)."""
    return str(getattr(fuente, "proceso", None) or RUTA_FRONTERA)


def marcas_de_agua(s: Session, proceso: str) -> dict[str, MarcaAguaRuta]:
    """Marcas de agua por ruta del proceso, con la frontera '*' (ai_frecuencias.marca_agua_ruta)."""
    filas = s.scalars(select(MarcaAguaRuta).where(MarcaAguaRuta.proceso == proceso)).all()
    return {f.ruta: f for f in filas}


def particion_del_trabajo(s: Session, e: Ejecucion, fuente: Any):
    """La partición que lee el trabajo: su ruta (o todas si e.ruta es NULL) con la marca de agua y las huellas de
    cada ruta; las rutas sin marca propia parten de la frontera del proceso (la marca global de antes de la 0009)."""
    from app.servicios import fuentes

    proceso = proceso_de_la_fuente(fuente)
    filas = marcas_de_agua(s, proceso)
    frontera = filas.pop(RUTA_FRONTERA, None)
    return fuentes.Particion(
        proceso=proceso, rutas=(e.ruta,) if e.ruta else None,
        marcas={r: f.marca_agua for r, f in filas.items()},
        estados={r: f.estado_fuente for r, f in filas.items() if isinstance(f.estado_fuente, dict)},
        marca_resto=frontera.marca_agua if frontera is not None else None,
        estado_resto=frontera.estado_fuente if frontera is not None else None)


def tomar_candados_particion(s: Session, ruta: str | None, espera_s: float | None = None) -> None:
    """Candado de la partición en la transacción de los resultados (se suelta al confirmar o revertir): un trabajo de
    UNA ruta toma el de su ruta (exclusivo) y el de «todas las rutas» compartido; uno de todas las rutas, el de
    «todas» exclusivo. La cola ya no entrega dos trabajos que se crucen; el candado lo garantiza también si una réplica
    que perdió la reserva sigue viva: el segundo espera hasta `espera_s` (por omisión dos reservas) y, si no se libera,
    el intento se reintenta con espera (ParticionOcupada)."""
    if ruta:
        pedidos = [("SELECT pg_try_advisory_xact_lock_shared(:k, 0)", {"k": CLAVE_PARTICION_TODAS}),
                   ("SELECT pg_try_advisory_xact_lock(:k, hashtext(:r))", {"k": CLAVE_PARTICION_RUTA, "r": ruta})]
    else:
        pedidos = [("SELECT pg_try_advisory_xact_lock(:k, 0)", {"k": CLAVE_PARTICION_TODAS})]
    limite = time.monotonic() + (espera_s if espera_s is not None else 2 * obtener_ajustes().lease_segundos)
    for sql, params in pedidos:
        while not s.execute(text(sql), params).scalar():
            if time.monotonic() >= limite:
                raise ParticionOcupada(f"La partición {ruta or 'de todas las rutas'} la tiene otro trabajo")
            time.sleep(0.2)


def tomar_candado_modelo(s: Session) -> None:
    """La política del modelo (reversión, compuerta de sombra, reentreno) de un ciclo a la vez en el clúster: con la
    ejecución partida, la madre de un día y un ciclo sin partir pueden cerrar a la vez. Se suelta al confirmar."""
    s.execute(text("SELECT pg_advisory_xact_lock(:k, 0)"), {"k": CLAVE_MODELO})


def _instante_o_nada(marca: datetime | None) -> datetime | None:
    from app.servicios import fuentes

    return None if marca is None or marca <= fuentes.MARCA_INICIAL else marca


def filas_de_marcas(c: _Ciclo) -> list[dict[str, Any]]:
    """Las marcas nuevas que deja el trabajo: las de las rutas que leyó (con sus huellas) y, si fue de todas las
    rutas, la frontera del proceso (la marca mayor de la lectura, con las huellas de todas las rutas)."""
    if c.particion is None or c.lectura is None:
        return []
    proceso = c.particion.proceso
    filas = [{"proceso": proceso, "ruta": ruta, "marca_agua": marca, "execution_id": c.execution_id,
              "estado_fuente": json_seguro(c.lectura.estados.get(ruta)) if c.lectura.estados.get(ruta) else None}
             for ruta, marca in sorted(c.lectura.marcas.items()) if _instante_o_nada(marca) is not None]
    if c.particion.rutas is None and c.lectura.marca_global is not None:
        frontera = max(c.particion.marca_de(None), c.lectura.marca_global)
        estado = c.metricas.get("fuente_estado")
        filas.append({"proceso": proceso, "ruta": RUTA_FRONTERA, "marca_agua": frontera,
                      "execution_id": c.execution_id, "estado_fuente": estado if isinstance(estado, dict) else None})
    return filas


def guardar_marcas(s: Session, c: _Ciclo) -> int:
    """Upsert de las marcas por ruta en la transacción de los resultados: solo quedan si el intento cierra «ok» con la
    cerca de cola.cerrar_ok (un intento revertido no mueve ninguna marca). Una marca nunca retrocede, y execution_id
    cambia solo si el trabajo la movió (§9.5: la marca es la de la última ejecución exitosa que leyó algo nuevo)."""
    from sqlalchemy import case
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    filas = filas_de_marcas(c)
    if not filas:
        return 0
    stmt = pg_insert(MarcaAguaRuta).values([dict(f, origen="ejecucion") for f in filas])
    movida = stmt.excluded.marca_agua > MarcaAguaRuta.marca_agua
    stmt = stmt.on_conflict_do_update(
        index_elements=[MarcaAguaRuta.proceso, MarcaAguaRuta.ruta],
        set_={"marca_agua": stmt.excluded.marca_agua, "estado_fuente": stmt.excluded.estado_fuente,
              "execution_id": case((movida, stmt.excluded.execution_id), else_=MarcaAguaRuta.execution_id),
              "origen": case((movida, stmt.excluded.origen), else_=MarcaAguaRuta.origen),
              "actualizado_en": func.now()},
        where=MarcaAguaRuta.marca_agua <= stmt.excluded.marca_agua)
    s.execute(stmt)
    return len(filas)


def resumen_particion(c: _Ciclo) -> dict[str, Any]:
    """La partición del trabajo para sus métricas: proceso, rutas y la marca de cada ruta antes y después."""
    if c.particion is None or c.lectura is None:
        return {}
    rutas = c.particion.rutas_conocidas() if c.particion.rutas is not None else sorted(c.lectura.marcas)
    return {"proceso": c.particion.proceso, "rutas": list(c.particion.rutas) if c.particion.rutas else "todas",
            "marcas": {r: {"anterior": _instante_o_nada(c.particion.marca_de(r)),
                           "nueva": _instante_o_nada(c.lectura.marcas.get(r))} for r in rutas},
            "frontera_anterior": _instante_o_nada(c.particion.marca_de(None))}


def obtener_fuente():
    """Fuente de las tablas operacionales según FUENTE (parquet por defecto; postgres = solo lectura)."""
    from app.servicios import fuentes

    aj = obtener_ajustes()
    if aj.fuente == "postgres":
        if not aj.fuente_database_url:
            raise ErrorNoReintentable("FUENTE=postgres requiere la variable FUENTE_DATABASE_URL")
        return fuentes.FuentePostgresSoloLectura(url=aj.fuente_database_url,
                                                 statement_timeout_ms=aj.fuente_statement_timeout_ms,
                                                 tabla=aj.fuente_tabla, solape_min=aj.fuente_solape_min,
                                                 proceso=getattr(aj, "fuente_proceso", None))
    if aj.fuente != "parquet":
        raise ErrorNoReintentable(f"FUENTE desconocida: {aj.fuente!r} (use parquet o postgres)")
    return fuentes.FuenteParquet()


def recuperar_interrumpidas() -> list[uuid.UUID]:
    """RNF-001: vuelven a la cola las ejecuciones «corriendo» cuya reserva venció o que dejó el proceso anterior
    de esta misma réplica. Con N réplicas no toca el trabajo vivo de otra (su reserva sigue vigente)."""
    from app.servicios import cola

    return cola.recuperar_al_arrancar()


def ejecutar(execution_id: uuid.UUID, trabajos: list[uuid.UUID] | None = None) -> None:
    """Despacha una ejecución ya encolada (cola en PostgreSQL, app/servicios/cola.py).

    Con trabajadores en este proceso (TRABAJADORES ≥ 1), la toma cualquiera de las réplicas desde la cola. Sin
    trabajadores (TRABAJADORES=0 o REANUDAR_EJECUCIONES=false, como en las pruebas), se procesa aquí mismo con el
    mismo protocolo de reserva, reintentos con espera y cierre con cerca. En una ejecución partida, `trabajos` son
    sus trabajos por ruta: se procesan primero y la madre al final (la cola no la entrega antes).
    """
    from app.servicios import cola

    if obtener_ajustes().trabajadores_efectivos > 0:
        return
    for trabajo in trabajos or ():
        cola.procesar(trabajo)
    cola.procesar(execution_id)


def _instante_por_defecto(parametros: dict, validos, data_cutoff: datetime | None) -> datetime:
    if parametros.get("instante"):
        return a_instante(parametros["instante"])
    base: date | None = None
    if validos is not None and len(validos):
        base = max(validos["fecha"])
    elif parametros.get("hasta"):
        base = date.fromisoformat(parametros["hasta"])
    elif data_cutoff is not None:
        base = data_cutoff.astimezone(ZONA).date()
    base = base or ahora().astimezone(ZONA).date()
    return datetime.combine(base + timedelta(days=1), dtime(6, 0), tzinfo=ZONA)


def _guardar_errores(s: Session, execution_id: uuid.UUID, lote: str, errores: list[dict]) -> dict[str, int]:
    """Cada error con su lote, fila, campo, causa y, desde la migración 0006, la llave del registro (columnas llave),
    el valor observado y si bloquea la fila (§6.3, §14.2: el error lleva al registro exacto)."""
    resumen: dict[str, int] = {}
    for err in errores:
        dim = str(err.get("dimension") or "validez")
        resumen[dim] = resumen.get(dim, 0) + 1
        fila = err.get("fila")
        llave = err.get("llave")
        bloqueante = err.get("bloqueante")
        s.add(ErrorCalidad(execution_id=execution_id, lote=str(err.get("lote") or lote),
                           fila=int(fila) if _num(fila) is not None else None, campo=err.get("campo"),
                           codigo=str(err.get("codigo") or "DQ"), dimension=dim,
                           detalle=None if err.get("detalle") is None else str(err.get("detalle")),
                           llave=json_seguro(llave) if isinstance(llave, dict) else None,
                           valor=None if err.get("valor") is None else str(err.get("valor")),
                           bloqueante=None if bloqueante is None else bool(bloqueante)))
    return resumen


def reportar_unicidad(s: Session, execution_id: uuid.UUID, lote: str, errores: list[dict]) -> dict[str, Any]:
    """§6.3 «Unicidad: reportar al responsable del consolidado; no corregir directamente». Si el lote trae llaves
    duplicadas (UNI-001), el reporte (cada llave con sus filas del lote y la ruta de la API que lista los errores) va al
    responsable del consolidado por el canal de correo existente (simulado, NOTIF_UNICIDAD_DESTINATARIOS) y queda en
    notification_log, en la transacción del ciclo. Sin destinatario (lo define Extreme) queda «pendiente_destinatario».
    No corrige nada: las filas duplicadas ya se rechazaron. Devuelve {} sin duplicados, o el resumen para las métricas
    de la ejecución en «reporte_unicidad»."""
    from app.servicios import notificaciones

    consulta = f"/api/v1/frequency/executions/{execution_id}/errors?codigo={notificaciones.CODIGO_UNICIDAD}"
    reporte = notificaciones.reporte_unicidad(errores, lote, consulta)
    if reporte is None:
        return {}
    try:
        registro = notificaciones.enviar_reporte_unicidad(reporte)
    except Exception as exc:  # noqa: BLE001 - el reporte queda registrado como fallido; el ciclo sigue
        log.warning("reporte de unicidad del lote %s no enviado: %s", lote, exc)
        registro = {"canal": "correo", "estado": "fallida", "simulado": True, "error": str(exc)[:300]}
    fila = Notificacion(execution_id=execution_id, alert_id=None, canal=str(registro.get("canal") or "correo"),
                        destinatario=registro.get("destinatario"), asunto=reporte["asunto"], mensaje=reporte["cuerpo"],
                        estado=_estado_envio(registro), simulado=bool(registro.get("simulado", True)),
                        detalle=json_seguro({**registro, "reporte": reporte}))
    s.add(fila)
    s.flush()
    return {"reporte_unicidad": {"notification_id": fila.id, "estado": fila.estado, "lote": lote,
                                 "responsable": reporte["responsable"], "destinatario": fila.destinatario,
                                 "llaves_duplicadas": reporte["llaves_duplicadas"],
                                 "filas_duplicadas": reporte["filas_duplicadas"], "consulta": consulta}}


def catalogos_calidad(fuente: Any) -> dict[str, set]:
    """Catálogos de la validación relacional (§6.3, §7.3 paso 3): rutas e idruta del catálogo de la API y, si la
    fuente operacional los expone (réplica o producción, solo lectura), procesos, estacionalidades y novedades."""
    from app.servicios import datos

    rutas = datos.catalogo_rutas()
    cat: dict[str, set] = {"rutas": {str(r["ruta"]) for r in rutas},
                           "idrutas": {int(r["idruta"]) for r in rutas if _num(r.get("idruta")) is not None}}
    leer = getattr(fuente, "leer_contexto", None)
    if leer is None:
        return cat
    for clave, tabla, columna in (("procesos", "procesos", "proceso"),
                                  ("estacionalidades", "estacionalidades", "id_estacionalidad"),
                                  ("novedades", "novedades_viales", "id_novedad_vial")):
        try:
            d = leer(tabla)
            if d is not None and len(d) and columna in d.columns:
                valores = d[columna].dropna().tolist()
                cat[clave] = {str(v) for v in valores} if clave == "procesos" else {int(v) for v in valores}
        except Exception as exc:  # noqa: BLE001 - sin ese catálogo rige el empaquetado de calidad.py
            log.info("catálogo %s no disponible para la calidad: %s", tabla, exc)
    return cat


def _incorporar_historico(s: Session, validos, execution_id: uuid.UUID) -> int:
    """Upsert por la clave natural (ruta, fecha, hora) con COPY + INSERT … ON CONFLICT en la transacción de `s`
    (app/servicios/ingesta.py): una carga repetida no duplica ni reescribe filas iguales."""
    from app.servicios import ingesta

    return int(ingesta.incorporar(s, validos, execution_id)["filas"])


def guardar_alerta(s: Session, a: dict, execution_id: uuid.UUID | None, umbrales_version: int | None
                   ) -> tuple[Alerta, bool]:
    """Inserta la alerta o, si ya hay una abierta con la misma clave_dedup, suma una ocurrencia (§18).

    Las alertas observadas usan una clave por episodio (código + ruta + inicio + «obs»): si el episodio sigue en una
    ejecución posterior, se actualizan la ventana, los valores, la serie y la tendencia de la MISMA alerta y la
    bitácora (alert_history) guarda una entrada «redeteccion» con los valores anteriores y los nuevos."""
    from app.servicios import alertas as reglas

    abierta = s.scalar(select(Alerta).where(Alerta.clave_dedup == a["clave_dedup"],
                                            Alerta.estado.not_in(ESTADOS_CERRADOS)))
    if abierta is not None:
        abierta.ocurrencias += 1
        abierta.ultima_deteccion = ahora()
        abierta.actualizado_en = ahora()
        _actualizar_episodio(s, abierta, a, execution_id, umbrales_version)
        escalar_alerta(s, abierta, a, execution_id, umbrales_version)
        return abierta, False
    try:
        alert_id = uuid.UUID(str(a.get("id")))
    except (ValueError, TypeError):
        alert_id = uuid.uuid4()
    variables = json_seguro(a.get("variables") or {})
    variables["umbrales_version"] = umbrales_version
    detectada = a_instante(a.get("detectada_en")) or ahora()
    nueva = Alerta(
        alert_id=alert_id, codigo=a["codigo"], execution_id=execution_id,
        empresa=a.get("empresa") or empresa_de(a.get("ruta")),
        ruta=a.get("ruta"), sentido=a.get("sentido"), viaje=a.get("viaje"),
        conductor=reglas.seudonimo_conductor(a.get("conductor")),   # §18: nunca el dato en claro
        vehiculo=a.get("vehiculo"), detectada_en=detectada,
        ventana_inicio=a_instante(a.get("ventana_inicio")), ventana_fin=a_instante(a.get("ventana_fin")),
        horizonte_min=a.get("horizonte_min"), severidad=a["severidad"], estado="nueva",
        observado=_num(a.get("observado")), esperado=_num(a.get("esperado")), umbral=_num(a.get("umbral")),
        puntaje=_num(a.get("puntaje")), explicacion=a.get("explicacion"), variables=variables,
        recomendacion=a.get("recomendacion"), comentarios=[], clave_dedup=a["clave_dedup"], ocurrencias=1,
        ultima_deteccion=ahora(), origen=a.get("origen") or reglas.ORIGEN_POR_CODIGO.get(a["codigo"], "pronostico"),
        tendencia=a.get("tendencia"), tendencia_pendiente=_num(a.get("tendencia_pendiente")),
        serie_reciente=json_seguro(a.get("serie_reciente") or []), probabilidad=_num(a.get("probabilidad")),
        metodo_puntaje=a.get("metodo_puntaje"), variables_influyentes=json_seguro(a.get("variables_influyentes") or []),
        ubicacion=a.get("ubicacion"),
        **dimensiones_fila(a.get("ruta"), a_instante(a.get("ventana_inicio")) or detectada))
    try:
        with s.begin_nested():
            s.add(nueva)
            s.flush()
    except IntegrityError:  # otra ejecución la creó al tiempo: se trata como repetida
        abierta = s.scalar(select(Alerta).where(Alerta.clave_dedup == a["clave_dedup"],
                                                Alerta.estado.not_in(ESTADOS_CERRADOS)))
        if abierta is None:
            raise
        abierta.ocurrencias += 1
        return abierta, False
    s.add(HistorialAlerta(alert_id=nueva.alert_id, accion="crear", estado_anterior=None, estado_nuevo="nueva",
                          usuario="sistema", comentario=f"Detectada por la ejecución {execution_id}",
                          detalle={"execution_id": json_seguro(execution_id), "umbrales_version": umbrales_version}))
    return nueva, True


def _inicio_anterior(abierta: Alerta, a: dict) -> datetime | None:
    """El inicio de la detección `a` si es anterior al de la alerta abierta: el episodio creció hacia atrás (una hora
    anterior que el lote vuelve a traer y ahora supera el umbral; clave_del_episodio la junta con la abierta). None si
    no."""
    inicio = a_instante(a.get("ventana_inicio"))
    if inicio is None or (abierta.ventana_inicio is not None and inicio >= abierta.ventana_inicio):
        return None
    return inicio


def _actualizar_episodio(s: Session, abierta: Alerta, a: dict, execution_id: uuid.UUID | None,
                         umbrales_version: int | None) -> None:
    """Un episodio observado que continúa: la alerta abierta toma la ventana y los valores nuevos y la
    bitácora guarda lo anterior (historial completo, sin duplicar la alerta). Si el episodio creció hacia atrás, la
    ventana empieza en el menor de los dos inicios (_inicio_anterior), así cubre todas las horas del episodio."""
    fin_nuevo, inicio_anterior = a_instante(a.get("ventana_fin")), _inicio_anterior(abierta, a)
    if abierta.origen not in ("observado", "calidad_datos") or fin_nuevo is None or (
            abierta.ventana_fin and fin_nuevo <= abierta.ventana_fin and _num(a.get("observado")) == abierta.observado
            and inicio_anterior is None):
        return
    antes = {"ventana_inicio": json_seguro(abierta.ventana_inicio and abierta.ventana_inicio.astimezone(ZONA)),
             "ventana_fin": json_seguro(abierta.ventana_fin and abierta.ventana_fin.astimezone(ZONA)),
             "observado": abierta.observado,
             "esperado": abierta.esperado, "umbral": abierta.umbral, "tendencia": abierta.tendencia}
    abierta.ventana_inicio = inicio_anterior or abierta.ventana_inicio
    abierta.ventana_fin = max(fin_nuevo, abierta.ventana_fin or fin_nuevo)
    for campo in ("observado", "esperado", "umbral", "puntaje", "probabilidad", "tendencia_pendiente"):
        setattr(abierta, campo, _num(a.get(campo)))
    _identificacion_del_episodio(abierta, a)
    abierta.tendencia = a.get("tendencia")
    abierta.explicacion = a.get("explicacion")
    abierta.serie_reciente = json_seguro(a.get("serie_reciente") or [])
    abierta.variables_influyentes = json_seguro(a.get("variables_influyentes") or [])
    abierta.variables = json_seguro(a.get("variables") or {}) | {"umbrales_version": umbrales_version}
    despues = {"ventana_inicio": json_seguro(abierta.ventana_inicio and abierta.ventana_inicio.astimezone(ZONA)),
               "ventana_fin": json_seguro(abierta.ventana_fin.astimezone(ZONA)), "observado": abierta.observado,
               "esperado": abierta.esperado, "umbral": abierta.umbral, "tendencia": abierta.tendencia}
    s.add(HistorialAlerta(alert_id=abierta.alert_id, accion="redeteccion", estado_anterior=abierta.estado,
                          estado_nuevo=abierta.estado, usuario="sistema",
                          comentario=f"El episodio continúa (ejecución {execution_id})",
                          detalle={"execution_id": json_seguro(execution_id), "antes": antes, "despues": despues}))


def _identificacion_del_episodio(abierta: Alerta, a: dict) -> None:
    """§5.3: si la redetección del episodio identifica el viaje (ALT-006, ALT-009 y la ALT-002 medida en el segmento
    crítico), la alerta abierta toma su viaje, su vehículo y el seudónimo de su conductor (§18: nunca el dato en claro)
    y, si la redetección lo trae, el sentido aproximado de su segmento; si no lo identifica, conserva lo que tenía."""
    from app.servicios import alertas as reglas

    if not a.get("viaje"):
        return
    abierta.viaje, abierta.vehiculo = str(a["viaje"]), a.get("vehiculo")
    abierta.conductor = reglas.seudonimo_conductor(a.get("conductor"))
    abierta.sentido = a.get("sentido") or abierta.sentido


ORDEN_SEVERIDAD = {"informativa": 0, "preventiva": 1, "critica": 2}
CLAVE_ESCALADAS = "alertas_escaladas_a_critica"


def escalar_alerta(s: Session, abierta: Alerta, a: dict, execution_id: uuid.UUID | None,
                   umbrales_version: int | None) -> bool:
    """§7.2 escalamiento: si la redetección trae una severidad MAYOR, la alerta abierta sube a esa severidad, la
    bitácora guarda una entrada «escalar» (el estado no cambia) y, si queda crítica, se notifica al cerrar el ciclo.
    La severidad nunca baja sola: una redetección más leve solo suma la ocurrencia."""
    nueva = str(a.get("severidad") or "")
    if ORDEN_SEVERIDAD.get(nueva, -1) <= ORDEN_SEVERIDAD.get(abierta.severidad, -1):
        return False
    anterior = abierta.severidad
    abierta.severidad = nueva
    abierta.actualizado_en = ahora()
    s.add(HistorialAlerta(
        alert_id=abierta.alert_id, accion="escalar", estado_anterior=abierta.estado, estado_nuevo=abierta.estado,
        usuario="sistema", comentario=f"Severidad {anterior} -> {nueva} al redetectar el episodio "
                                      f"(ejecución {execution_id})",
        detalle=json_seguro({"execution_id": execution_id, "umbrales_version": umbrales_version,
                             "severidad_anterior": anterior, "severidad_nueva": nueva,
                             "observado": _num(a.get("observado")), "umbral": _num(a.get("umbral")),
                             "ocurrencias": abierta.ocurrencias})))
    if nueva == "critica":
        s.info.setdefault(CLAVE_ESCALADAS, []).append(abierta)
    return True


# ---------------------------------------------------------------- contexto observado (ALT-005..ALT-009)
def _a_fecha(valor: Any) -> date:
    if isinstance(valor, datetime):
        return valor.astimezone(ZONA).date() if valor.tzinfo else valor.date()
    if isinstance(valor, date):
        return valor
    if hasattr(valor, "to_pydatetime"):
        return valor.to_pydatetime().date()
    return date.fromisoformat(str(valor)[:10])


def referencia_temporal(p: dict, instante: datetime | None) -> datetime:
    """El «ahora» de la ejecución para medir la frescura (ALT-009): el instante simulado si la ejecución trae
    `instante` o `hasta` (repetición del histórico); si no, el reloj."""
    if (p.get("instante") or p.get("hasta")) and instante is not None:
        return instante
    return ahora()


def tolerancia_proceso(fuente: Any) -> float | None:
    """Procesos.toleranciatiempo (minutos) de la fuente operacional si la expone (réplica o producción); None si no."""
    leer = getattr(fuente, "procesos", None)
    if leer is None:
        return None
    try:
        tabla = leer()
        if tabla is None or not len(tabla) or "toleranciatiempo" not in tabla:
            return None
        return _num(tabla["toleranciatiempo"].iloc[0])
    except Exception as exc:  # noqa: BLE001 - sin el dato, ALT-006 usa el umbral configurado
        log.info("toleranciatiempo no disponible: %s", exc)
        return None


def ubicacion_despacho(fuente: Any, ruta: str) -> dict | None:
    """Punto de despacho de la ruta (GeoJSON) si la fuente lo expone (p. ej. inicio de rutasgeograficas)."""
    leer = getattr(fuente, "ubicacion_despacho", None)
    if leer is None:
        return None
    try:
        return leer(ruta)
    except Exception as exc:  # noqa: BLE001
        log.info("ubicación de despacho no disponible para %s: %s", ruta, exc)
        return None


def viajes_del_dia(fuente: Any, ruta: str, fecha: date, fallos: list) -> list[dict] | None:
    """§5.3 «viaje, conductor y vehículo, cuando aplique»: los viajes de la ruta en el día, de progvehiculos en solo
    lectura: los de la fuente operacional del ciclo (FuentePostgresSoloLectura.viajes, con el conductor ya
    seudonimizado) o, si la fuente no los expone (la serie empaquetada es horaria), los de los catálogos (réplica o
    exportación, catalogos.viajes_para_alertas). None si ninguna los tiene: las alertas salen igual y dicen en
    variables.identificacion_5_3 que la fuente no trae viajes. Un error de la fuente queda en los fallos de la
    ejecución; que no haya ninguna fuente de viajes no es un fallo."""
    from app.servicios import alertas as reglas
    from app.servicios import catalogos

    inicio = datetime.combine(fecha, dtime(0), tzinfo=ZONA)
    leer = getattr(fuente, "viajes", None) or catalogos.viajes_para_alertas
    try:
        tabla = leer(ruta, inicio, inicio + timedelta(days=1))
    except catalogos.CatalogoNoDisponible as exc:
        log.info("viajes de %s no disponibles: %s", ruta, exc)
        return None
    except Exception as exc:  # noqa: BLE001 - sin viajes las alertas se emiten igual, sin identificar el viaje
        fallos.append({"etapa": "viajes", "ruta": ruta, "error": str(exc)})
        return None
    if tabla is None:
        return None
    return [reglas.viaje_de_fila(f) for f in tabla.to_dict("records")]


def _festivos() -> set[date]:
    from app.servicios import datos

    try:
        c = datos.contexto_operacional()
        return {_a_fecha(f) for f in c.loc[c["festivo_oficial"] == 1, "fecha"].unique()}
    except Exception:  # noqa: BLE001
        return set()


# §5.2, RF-009: días del lote que evalúan las alertas observadas (contados desde su último día) y duración máxima de un
# viaje válido (regla R3 de la definición de pasajeros: de 30 a 360 min).
VENTANA_OBSERVADA_DIAS = 7
DURACION_MAXIMA_VIAJE = timedelta(minutes=360)


def fin_de_la_hora(fecha: date, hora: int) -> datetime:
    """El fin de la hora de salida (fecha, hora) en Bogotá: desde entonces ya salieron todos sus viajes."""
    return datetime.combine(fecha, dtime(int(hora)), tzinfo=ZONA) + timedelta(hours=1)


def dias_observados(nuevas: set[tuple[date, int]], referencia: datetime) -> list[date]:
    """§5.2, RF-009: los días del lote que evalúan las alertas observadas, en orden: cada día con horas nuevas de los
    últimos VENTANA_OBSERVADA_DIAS días del lote (contados desde su último día) en el que ya terminó su primera hora de
    servicio frente a la referencia. Con la captura en vivo, el ciclo de las 5:15 trae el día anterior (completo) y la
    franja de las 4 h del día en curso: se evalúan los dos, cada uno con sus horas cerradas. La carga inicial (meses de
    histórico) no se evalúa día por día: sus alertas serían de días ya pasados (las mide el backtest de alertas)."""
    from app.servicios import datos

    fechas = sorted({f for f, _ in nuevas})
    if not fechas:
        return []
    desde = fechas[-1] - timedelta(days=VENTANA_OBSERVADA_DIAS - 1)
    primera = min(datos.HORAS_SERVICIO)
    return [f for f in fechas if f >= desde and fin_de_la_hora(f, primera) <= referencia]


def _viajes_de_la_hora_terminados(viajes: list[dict] | None, fecha: date, hora: int) -> bool:
    """True si se conocen los viajes del día y ninguno de los que salen en esa hora sigue sin finalizar (un viaje
    cancelado no tiene nada que esperar)."""
    if not viajes:
        return False
    return not any(v.get("estado") == "sin_finalizar" and v.get("salida") is not None
                   and v["salida"].date() == fecha and v["salida"].hour == int(hora) for v in viajes)


def hora_completa(fecha: date, hora: int, referencia: datetime, viajes: list[dict] | None = None) -> bool:
    """Una hora cerrada cuyos conteos ya son definitivos. Pasajeros y salidas son Σ de los viajes VÁLIDOS (finalizados,
    fuentes.py): un viaje en curso todavía no cuenta, y un viaje dura unas 3,5 h. Lo son si ninguno de sus viajes sigue
    en curso (con los viajes del día) o si desde el fin de la hora pasó la duración máxima de un viaje válido
    (DURACION_MAXIMA_VIAJE)."""
    fin = fin_de_la_hora(fecha, hora)
    if fin + DURACION_MAXIMA_VIAJE <= referencia:
        return True
    return fin <= referencia and _viajes_de_la_hora_terminados(viajes, fecha, hora)


def contextos_observados(s: Session, ruta: str, validos, campos_faltantes: list[str] | None, model_id: str | None,
                         referencia: datetime, umbrales: dict, *, fuente: Any = None, festivos: set | None = None,
                         fallos: list | None = None) -> list[dict]:
    """Los contextos de evaluar_observadas() de una ruta con lo que trajo la ejecución: uno por día del lote que se
    evalúa (dias_observados), en orden; sin días que evaluar, uno solo con la frescura (ALT-009).

    Cada día (contexto_del_dia) trae sus horas de servicio cerradas frente a la referencia (las que todavía no
    terminaron no se evalúan: ni son un dato que falte ni tienen demanda que comparar), su consolidado si el día ya
    terminó (ALT-008) y sus horas faltantes (ALT-009). Lo que es de la ruta va una sola vez: la frescura y los campos
    obligatorios faltantes del lote en el último día, y la serie diaria de la ruptura (RF-009) en el último día
    terminado. Los días se vuelven a evaluar cuando su lote los trae otra vez (ciclos intradía, el de la madrugada):
    las claves de episodio de alertas.py actualizan la misma alerta abierta en lugar de duplicarla."""
    fallos = fallos if fallos is not None else []
    festivos = festivos if festivos is not None else _festivos()
    base: dict[str, Any] = {"ruta": ruta, "empresa": empresa_de(ruta), "detectada_en": ahora(),
                            "tolerancia_tiempo_min": tolerancia_proceso(fuente),
                            "ubicacion": ubicacion_despacho(fuente, ruta)}
    nuevas = _horas_nuevas(validos, ruta)
    dias = dias_observados(nuevas, referencia)
    llegada = _datos_de_llegada(s, ruta, referencia, campos_faltantes, dias[-1] if dias else None)
    if not dias:
        return [dict(base, datos=llegada)]
    contextos = [contexto_del_dia(s, base, dia, nuevas, model_id, referencia, umbrales, festivos=festivos,
                                  fuente=fuente, fallos=fallos) for dia in dias]
    for ctx in contextos:
        propio = {"horas_faltantes": ctx.pop("horas_faltantes"), "fecha": ctx["fecha"]}
        if ctx is not contextos[-1]:     # la frescura y los campos faltantes son de la ruta: una vez, en el último día
            propio.update(minutos_sin_datos=None, campos_faltantes=[])
        ctx["datos"] = dict(llegada, **propio)
    terminados = [ctx for ctx in contextos if ctx.get("dia_terminado")]
    if terminados:     # RF-009 «rupturas de comportamiento»: serie diaria real frente al pronóstico (CUSUM)
        terminados[-1]["serie_diaria"] = serie_diaria_memorizada(s, ruta, terminados[-1]["fecha"], model_id,
                                                                 {f for f, _ in nuevas}, fallos)
    return contextos


def contexto_observado(s: Session, ruta: str, validos, campos_faltantes: list[str] | None, model_id: str | None,
                       referencia: datetime, umbrales: dict, *, fuente: Any = None, festivos: set | None = None,
                       fallos: list | None = None) -> dict:
    """El contexto del último día que se evalúa de la ruta (contextos_observados), con la frescura de la ruta."""
    return contextos_observados(s, ruta, validos, campos_faltantes, model_id, referencia, umbrales, fuente=fuente,
                                festivos=festivos, fallos=fallos)[-1]


def contexto_del_dia(s: Session, base: dict, fecha: date, nuevas: set, model_id: str | None, referencia: datetime,
                     umbrales: dict, *, festivos: set, fuente: Any = None, fallos: list | None = None) -> dict:
    """El contexto observado de UN día de la ruta (`base`: ruta, empresa, detección, tolerancia y ubicación):

    - horas: las horas de servicio del día ya cerradas frente a la referencia (histórico propio, ya con el lote), cada
      una con el pronóstico del modelo para esa hora y su banda P10-P90 calibrada (inferencia.predecir sin factor
      intradía: el patrón del modelo, no la regla b8), salidas observadas frente a 60 / intervalo programado y nueva =
      llegó en esta ejecución. Una hora cerrada con viajes todavía en curso (hora_completa) lleva pasajeros y salidas
      en None, porque sus conteos aún no son definitivos: ALT-005, ALT-006, ALT-007 y la ALT-002 estimada no la leen
      como una caída o un despacho que faltó; sí conserva la ocupación medida por segmento (ALT-002), que es la de los
      viajes que ya pasaron;
    - horas_faltantes: las horas de servicio cerradas sin registro antes de la última cerrada con registro (ALT-009);
    - consolidado: si el día ya terminó (su última hora está completa) y tiene todas sus horas de servicio, subidas,
      bajadas (bajadas_viajes, si todas las horas la traen) y número de viajes frente al mismo tipo de día de las
      semanas_referencia previas (z robusto, ALT-008);
    - viajes: los viajes del día de progvehiculos con el conductor seudonimizado (viajes_del_dia, §5.3), para el viaje,
      el vehículo y el conductor de ALT-006 y ALT-009 y para saber si una hora ya terminó; None si ninguna fuente los
      tiene."""
    from app.modelos_db import DemandaObservada
    from app.servicios import datos

    fallos = fallos if fallos is not None else []
    ruta = base["ruta"]
    ctx: dict[str, Any] = dict(base, fecha=fecha, viajes=viajes_del_dia(fuente, ruta, fecha, fallos))
    filas = [(int(h), pas, sal) for h, pas, sal in s.execute(
        select(DemandaObservada.hora, DemandaObservada.pasajeros, DemandaObservada.salidas)
        .where(DemandaObservada.ruta == ruta, DemandaObservada.fecha == fecha).order_by(DemandaObservada.hora)).all()
        if fin_de_la_hora(fecha, int(h)) <= referencia]
    presentes = {h for h, _, _ in filas}
    ultima_hora = max(presentes, default=-1)
    ctx["horas_faltantes"] = [datetime.combine(fecha, dtime(h), tzinfo=ZONA).isoformat()
                              for h in datos.HORAS_SERVICIO if h <= ultima_hora and h not in presentes]
    td = datos.tipo_dia_de(fecha, fecha in festivos)
    servicio = [f for f in filas if f[0] in datos.HORAS_SERVICIO]
    dia = {"ruta": ruta, "fecha": fecha, "nuevas": nuevas, "model_id": model_id, "fallos": fallos,
           "intervalos": _intervalos_del_tipo_de_dia(ruta, td, fallos), "viajes": ctx["viajes"],
           "referencia": referencia,
           "pronosticos": _pronosticos_de_las_horas(ruta, fecha, [h for h, _, _ in servicio], model_id, fallos)}
    ctx["horas"] = [_hora_del_dia(dia, fila) for fila in servicio]
    ctx["dia_terminado"] = hora_completa(fecha, max(datos.HORAS_SERVICIO), referencia, ctx["viajes"])
    if ctx["dia_terminado"] and set(datos.HORAS_SERVICIO) <= presentes:
        consolidado = _consolidado_del_dia(s, ruta, fecha, td, umbrales, festivos)
        if consolidado is not None:
            ctx["consolidado"] = consolidado
    return ctx


def _hora_del_dia(dia: dict, fila: tuple) -> dict:
    """Una hora cerrada del día con su pronóstico. Si sus viajes siguen en curso, sin pasajeros ni salidas
    (viajes_en_curso = True): sus conteos todavía no son definitivos."""
    hora, pasajeros, salidas = fila
    completa = hora_completa(dia["fecha"], hora, dia["referencia"], dia["viajes"])
    h = _contexto_hora_observada(dia["ruta"], dia["fecha"], hora, pasajeros if completa else None,
                                 salidas if completa else None, dia["nuevas"], dia["intervalos"], dia["model_id"],
                                 dia["fallos"], pronostico=dia["pronosticos"].get(hora))
    h["viajes_en_curso"] = not completa
    return h


_SERIES_DIARIAS: dict[tuple, tuple[float, list[dict]]] = {}
_SERIES_CANDADO = threading.Lock()
_SERIES_MAX = 32
SERIE_DIARIA_DIAS = 56
SERIE_DIARIA_S = Histogram("api_serie_diaria_segundos",
                           "Duración de la serie diaria de la ruptura (RF-009) por ruta, con o sin la memoria",
                           ["memoria"], buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30))


def _huella_serie(s: Session, ruta: str, hasta: date, dias: int) -> tuple:
    """Huella barata de lo observado en la ventana de la serie (filas, suma de pasajeros y última actualización):
    si llega o se corrige un dato de esos días, la huella cambia y la serie se recalcula."""
    from app.modelos_db import DemandaObservada

    desde = hasta - timedelta(days=int(dias))
    columnas = [func.count(), func.coalesce(func.sum(DemandaObservada.pasajeros), 0)]
    if hasattr(DemandaObservada, "actualizado_en"):
        columnas.append(func.max(DemandaObservada.actualizado_en))
    fila = s.execute(select(*columnas).where(DemandaObservada.ruta == ruta, DemandaObservada.fecha <= hasta,
                                             DemandaObservada.fecha > desde)).one()
    return tuple(str(v) for v in fila)


def serie_diaria_memorizada(s: Session, ruta: str, fecha: date, model_id: str | None, nuevas: set,
                            fallos: list | None = None) -> list[dict]:
    """alertas.serie_diaria_ruta con memoria por (ruta, día, modelo, días nuevos y huella de lo observado). El
    pronóstico de 56 días × 17 h es la parte costosa; una repetición sin datos nuevos de esos días lo reutiliza.
    La duración queda en el histograma api_serie_diaria_segundos. Lista vacía si falla: la regla no se evalúa."""
    from app.servicios import alertas as reglas

    calcular = getattr(reglas, "serie_diaria_ruta", None)
    if calcular is None or fecha is None:
        return []
    t0 = time.perf_counter()
    try:
        with s.begin_nested():     # una falla de la huella revierte solo esta lectura
            huella = _huella_serie(s, ruta, fecha, SERIE_DIARIA_DIAS)
    except Exception as exc:  # noqa: BLE001 - sin huella se calcula sin memoria
        log.info("huella de la serie diaria de %s: %s", ruta, exc)
        huella = None
    clave = (ruta, fecha.isoformat(), model_id, tuple(sorted(str(f) for f in nuevas)), huella)
    with _SERIES_CANDADO:
        guardada = _SERIES_DIARIAS.get(clave) if huella is not None else None
    if guardada is not None:
        SERIE_DIARIA_S.labels(memoria="si").observe(time.perf_counter() - t0)
        return copy.deepcopy(guardada[1])
    try:
        with s.begin_nested():     # lee demanda_observada en la sesión del ciclo: un error no la deja inservible
            serie = calcular(s, ruta, fecha, model_id, dias=SERIE_DIARIA_DIAS, nuevas=nuevas) or []
    except Exception as exc:  # noqa: BLE001 - la ruptura no detiene el ciclo
        if fallos is not None:
            fallos.append({"etapa": "serie_diaria", "ruta": ruta, "error": str(exc)})
        return []
    if huella is not None:
        with _SERIES_CANDADO:
            _SERIES_DIARIAS[clave] = (time.monotonic(), copy.deepcopy(serie))
            while len(_SERIES_DIARIAS) > _SERIES_MAX:
                _SERIES_DIARIAS.pop(next(iter(_SERIES_DIARIAS)))
    SERIE_DIARIA_S.labels(memoria="no").observe(time.perf_counter() - t0)
    log.info("serie diaria de %s hasta %s: %s días en %.2f s", ruta, fecha, len(serie), time.perf_counter() - t0)
    return serie


def limpiar_series_diarias() -> None:
    with _SERIES_CANDADO:
        _SERIES_DIARIAS.clear()


def _horas_nuevas(validos, ruta: str) -> set[tuple[date, int]]:
    """(fecha, hora) de las filas de la ruta que llegaron en esta ejecución."""
    if validos is None or not len(validos) or "ruta" not in validos:
        return set()
    lote = validos[validos["ruta"] == ruta]
    return {(_a_fecha(f), int(h)) for f, h in zip(lote["fecha"], lote["hora"], strict=False)}


def _datos_de_llegada(s: Session, ruta: str, referencia: datetime, campos_faltantes: list[str] | None,
                      fecha: date | None) -> dict:
    """Frescura (minutos desde la última llegada frente a la referencia) y campos obligatorios faltantes."""
    from app.modelos_db import DemandaObservada

    ultima = s.scalar(select(func.max(DemandaObservada.ultima_actualizacion)).where(DemandaObservada.ruta == ruta))
    ultima = ultima.astimezone(ZONA) if ultima is not None else None   # §8.1: instantes presentados en Bogotá
    referencia = referencia.astimezone(ZONA)
    campos = sorted({str(c) for c in campos_faltantes or []})
    minutos = None if ultima is None else round((referencia - ultima).total_seconds() / 60, 1)
    return {"minutos_sin_datos": minutos, "ultima_llegada": ultima, "referencia": referencia,
            "campos_faltantes": campos, "horas_faltantes": [], "fecha": fecha}


def _intervalos_del_tipo_de_dia(ruta: str, td: int, fallos: list) -> dict:
    """Intervalo programado (min) por hora de la ruta para el tipo de día; vacío (y un fallo) si no hay parámetros."""
    from app.servicios import datos

    try:
        par = datos.parametros_operativos(ruta, datos.TIPOS_DIA[td])
        return {int(h): _num(v) for h, v in zip(par["hora"], par["intervalo_programado_min"], strict=False)}
    except Exception as exc:  # noqa: BLE001
        fallos.append({"etapa": "alertas_observadas", "ruta": ruta, "error": f"parámetros operativos: {exc}"})
        return {}


def _pronosticos_de_las_horas(ruta: str, fecha: date, horas: list[int], model_id: str | None,
                              fallos: list) -> dict[int, dict]:
    """Pronóstico de 60 min sin factor intradía de cada hora cerrada, en UN lote (inferencia.predecir_horas). Si el
    lote no está disponible o falla, cada hora se pide por separado en _contexto_hora_observada."""
    from app.servicios import inferencia

    en_lote = getattr(inferencia, "predecir_horas", None)
    if en_lote is None or not horas:
        return {}
    inicios = [datetime.combine(fecha, dtime(h), tzinfo=ZONA) for h in horas]
    try:
        resultados = en_lote(ruta, inicios, model_id, horizonte_min=60, usar_nowcast=False)
    except Exception as exc:  # noqa: BLE001 - se vuelve al pronóstico hora por hora
        fallos.append({"etapa": "alertas_observadas", "ruta": ruta, "error": f"pronóstico en lote: {exc}"})
        return {}
    return dict(zip(horas, resultados, strict=False)) if len(resultados) == len(horas) else {}


def _contexto_hora_observada(ruta: str, fecha: date, hora: int, pasajeros, salidas, nuevas: set, intervalos: dict,
                             model_id: str | None, fallos: list, pronostico: dict | None = None) -> dict:
    """Una hora cerrada del día con su pronóstico y su banda calibrada (sin factor intradía) y la oferta programada."""
    from app.servicios import alertas as reglas
    from app.servicios import inferencia

    inicio = datetime.combine(fecha, dtime(hora), tzinfo=ZONA)
    esp = p10 = p90 = None
    infl: list = []
    try:
        r = pronostico if pronostico is not None else inferencia.predecir(ruta, inicio, 60, model_id=model_id,
                                                                           usar_nowcast=False)
        esp, p10, p90 = _num(r.get("pasajeros")), _num(r.get("p10")), _num(r.get("p90"))
        infl = reglas.variables_desde_shap(r.get("explicacion_local"))
    except Exception as exc:  # noqa: BLE001 - sin pronóstico la hora no evalúa ALT-005/ALT-007
        fallos.append({"etapa": "alertas_observadas", "ruta": ruta, "hora": hora, "error": str(exc)})
    intervalo = intervalos.get(hora)
    return reglas.contexto_hora(inicio, _num(pasajeros), esp, p10, p90, salidas,
                                (60.0 / intervalo) if intervalo else None, intervalo,
                                nueva=(fecha, hora) in nuevas, variables_influyentes=infl)


def _bajadas_del_dia(fila) -> float | None:
    """Σ bajadas_viajes del día si todas sus horas la traen (con horas sin dato la suma subestimaría el día)."""
    return _num(fila[4]) if fila[5] == fila[3] else None


def _consolidado_del_dia(s: Session, ruta: str, dia: date, td: int, umbrales: dict, festivos: set) -> dict | None:
    """Subidas (Σ pasajeros), bajadas (Σ bajadas_viajes, la misma definición) y número de viajes del día frente al
    mismo tipo de día de las semanas_referencia previas (ALT-008, §5.2). Las bajadas solo cuentan en los días con el
    dato en todas sus horas."""
    from app.modelos_db import DemandaObservada
    from app.servicios import datos

    semanas = int(float(umbrales.get("semanas_referencia", 8)))
    diarios = s.execute(select(DemandaObservada.fecha, func.sum(DemandaObservada.pasajeros),
                               func.sum(DemandaObservada.salidas), func.count(),
                               func.sum(DemandaObservada.bajadas_viajes), func.count(DemandaObservada.bajadas_viajes))
                        .where(DemandaObservada.ruta == ruta,
                               DemandaObservada.fecha >= dia - timedelta(weeks=semanas),
                               DemandaObservada.fecha <= dia, DemandaObservada.hora.in_(list(datos.HORAS_SERVICIO)))
                        .group_by(DemandaObservada.fecha).order_by(DemandaObservada.fecha)).all()
    del_dia = [x for x in diarios if x[0] == dia]
    ref = [x for x in diarios if x[0] < dia and x[3] >= len(datos.HORAS_SERVICIO)
           and datos.tipo_dia_de(x[0], x[0] in festivos) == td]
    if not del_dia:
        return None
    inicio_dia = datetime.combine(dia, dtime(0), tzinfo=ZONA)
    return {
        "fecha": dia, "inicio": inicio_dia, "fin": inicio_dia + timedelta(days=1),
        "subidas": _num(del_dia[0][1]), "bajadas": _bajadas_del_dia(del_dia[0]), "nro_viajes": _num(del_dia[0][2]),
        "referencia_valores": {"subidas": [_num(x[1]) for x in ref], "nro_viajes": [_num(x[2]) for x in ref],
                               "bajadas": [b for b in map(_bajadas_del_dia, ref) if b is not None]},
        "serie": [_num(x[1]) for x in ref[-6:]] + [_num(del_dia[0][1])],
        "serie_detalle": [{"fecha": str(x[0]), "subidas": _num(x[1]), "bajadas": _bajadas_del_dia(x),
                           "nro_viajes": _num(x[2])} for x in ref[-6:] + del_dia],
        "descripcion_referencia": f"{len(ref)} días {datos.TIPOS_DIA[td].lower()} de las {semanas} semanas "
                                  f"previas (mediana y 1,4826·MAD)"}


def _faltantes_por_ruta(df, errores: list[dict]) -> dict:
    """{ruta: campos obligatorios faltantes} de los errores de completitud (None = fila sin ruta legible)."""
    out: dict = {}
    for e in errores or []:
        if e.get("dimension") != "completitud":
            continue
        ruta = None
        try:
            if df is not None and e.get("fila") in df.index:
                ruta = df.loc[e["fila"], "ruta"]
        except Exception:  # noqa: BLE001
            ruta = None
        out.setdefault(None if ruta is None or (isinstance(ruta, float) and math.isnan(ruta)) else str(ruta),
                       set()).add(str(e.get("campo")))
    return out


def _tasa_horaria_ventana(c: dict) -> float | None:
    """Pasajeros por hora previstos en la ventana del horizonte: la demanda de la ventana × 60 / horizonte. Sin la
    demanda de la ventana, demanda_prevista, que ya es por hora (alertas.contexto_pronostico)."""
    if c.get("demanda_ventana") is not None:
        return float(c["demanda_ventana"]) * 60.0 / int(c["horizonte_min"])
    return None if c.get("demanda_prevista") is None else float(c["demanda_prevista"])


def tendencia_por_horizonte(contextos: list[dict]) -> None:
    """§9.4: serie de los pasajeros por hora previstos en las ventanas de cada ruta (30 -> 60 -> 120 min), para la
    tendencia de las alertas de pronóstico. Cada valor es una tasa horaria, en las unidades de la alerta."""
    por_ruta: dict[str, list] = {}
    for c in contextos:
        tasa = _tasa_horaria_ventana(c) if c.get("horizonte_min") else None
        if tasa is not None:
            por_ruta.setdefault(c["ruta"], []).append((int(c["horizonte_min"]), tasa))
    for c in contextos:
        serie = sorted(por_ruta.get(c["ruta"], []))
        c.setdefault("serie_tendencia", [v for _, v in serie])
        c.setdefault("serie_reciente", [{"horizonte_min": h, "pasajeros_por_hora": round(v, 1)} for h, v in serie])


def con_ocupacion_por_segmento(ctx: dict, ocupacion: dict | None) -> int:
    """§10.1 ocupación actual en el contexto observado: cada hora cerrada con ocupación medida por segmento lleva el
    resumen de su segmento crítico (segmento_critico: segmento, sentido, viajes, ocupación y el viaje más cargado con
    su vehículo y su conductor seudónimo); ALT-002 observada la usa en lugar de la estimación con el factor de carga.
    Devuelve cuántas horas la recibieron."""
    marcadas = 0
    for h in ctx.get("horas") or []:
        inicio = h.get("inicio")
        if ocupacion and hasattr(inicio, "hour"):
            local = inicio.astimezone(ZONA) if inicio.tzinfo else inicio
            resumen = ocupacion.get((local.date(), local.hour))
            if resumen is not None:
                h["segmento_critico"] = resumen
                marcadas += 1
    return marcadas


def ocupacion_del_dia(s: Session, ruta: str, fecha: date | None, del_ciclo: dict | None) -> dict | None:
    """§10.1 la ocupación por segmento con que se evalúan las horas de un día del lote (ALT-002 en el segmento
    crítico): la que ya guardaron los ciclos para la ruta y el día (ai_frecuencias.ocupacion_segmento, la medición más
    reciente de cada franja: ocupacion.observada_guardada, sin el viaje más cargado) y, encima, la que acaba de medir
    este ciclo, que sí lo trae. Un ciclo intradía mide las horas que trae su lote: si la captura entrega cada hora una
    vez, la hora anterior del episodio quedaba sin medir y ALT-002 nunca juntaba sus horas de persistencia. Si la
    lectura falla, solo la del ciclo (queda en el log)."""
    from app.servicios import ocupacion

    if fecha is None:
        return del_ciclo
    try:
        with s.begin_nested():     # una falla revierte solo esta lectura, no la transacción del ciclo
            guardada = ocupacion.observada_guardada(s, ruta, fecha, ahora())
    except Exception as exc:  # noqa: BLE001 - sin la guardada rige la ocupación medida en este ciclo
        log.info("ocupación guardada de %s del %s no disponible: %s", ruta, fecha, exc)
        guardada = {}
    return {**guardada, **(del_ciclo or {})} or None


def _faltantes_de(variables: dict | None) -> tuple:
    """Las horas y los campos que faltan según una ALT-009 (su ventana termina en la referencia del ciclo, que cambia
    en cada ejecución: lo que dice qué se alertó son estas listas)."""
    v = variables or {}
    return (tuple(sorted(map(str, v.get("horas_faltantes") or []))),
            tuple(sorted(map(str, v.get("campos_faltantes") or []))))


def _ya_cubierta(cerrada: Alerta, a: dict) -> bool:
    """La alerta cerrada ya dice lo que dice la detección `a`: en ALT-009 las mismas horas y campos que faltan; en las
    demás, una ventana que llega por lo menos hasta el fin de la nueva."""
    if a.get("origen") == "calidad_datos":
        return _faltantes_de(cerrada.variables) == _faltantes_de(a.get("variables"))
    fin = a_instante(a.get("ventana_fin"))
    return fin is not None and cerrada.ventana_fin is not None and fin <= cerrada.ventana_fin


def episodio_ya_cerrado(s: Session, a: dict) -> bool:
    """§18 «sin duplicar»: el episodio observado de `a` ya se alertó, el área operativa lo cerró o lo descartó y la
    nueva detección no le agrega nada (_ya_cubierta). Pasa cuando el ciclo vuelve a leer un día ya evaluado (los
    ciclos intradía releen las horas cuyos viajes siguen llegando; el de la madrugada, el día anterior): sin esto, la
    detección repetida abriría una alerta nueva con la clave de la cerrada. Si hay una abierta con la clave, la
    actualiza guardar_alerta; si el episodio sigue (su ventana pasa la de la cerrada), se alerta de nuevo; una ALT-009
    solo por atraso (sin horas ni campos que falten) es siempre un episodio nuevo."""
    if a.get("origen") not in ("observado", "calidad_datos"):
        return False
    if a.get("origen") == "calidad_datos" and not any(_faltantes_de(a.get("variables"))):
        return False
    alertas_clave = s.scalars(select(Alerta).where(Alerta.clave_dedup == a["clave_dedup"])).all()
    if any(x.estado not in ESTADOS_CERRADOS for x in alertas_clave):
        return False
    return any(_ya_cubierta(x, a) for x in alertas_clave)


def clave_del_episodio(s: Session, a: dict) -> str:
    """§18 «sin duplicar»: la clave con que se guarda la alerta observada `a`. La de un episodio es su inicio
    (alertas.clave_episodio), y con los ciclos intradía el mismo día se evalúa varias veces: el inicio de la racha
    puede moverse entre un ciclo y el siguiente (una hora anterior que el lote vuelve a traer y ahora supera el umbral,
    o una hora que se completa después que la siguiente) y el mismo episodio saldría con otra clave como una alerta
    nueva por las mismas horas. Si no hay una alerta abierta con la clave de `a`, se usa la de la alerta del mismo
    código y ruta cuya ventana se cruza o se toca con la de `a`: la abierta, que la redetección actualiza
    (guardar_alerta), o si no la cerrada más reciente, que decide episodio_ya_cerrado. Sin ninguna, la de `a`."""
    clave = a["clave_dedup"]
    inicio, fin = a_instante(a.get("ventana_inicio")), a_instante(a.get("ventana_fin"))
    if a.get("origen") != "observado" or inicio is None or fin is None:
        return clave
    abierta = Alerta.estado.not_in(ESTADOS_CERRADOS)
    if s.scalar(select(Alerta.alert_id).where(Alerta.clave_dedup == clave, abierta).limit(1)) is not None:
        return clave
    del_episodio = s.scalar(select(Alerta.clave_dedup).where(
        Alerta.codigo == a["codigo"], Alerta.ruta == a.get("ruta"), Alerta.origen == "observado",
        Alerta.ventana_inicio <= fin, Alerta.ventana_fin >= inicio)
        .order_by(abierta.desc(), Alerta.ventana_fin.desc(), Alerta.alert_id).limit(1))
    return del_episodio or clave


def _guardar_observadas(s: Session, alertas_ctx: list[dict], execution_id: uuid.UUID, version_u: int | None,
                        resumen: dict) -> tuple[list[Alerta], int]:
    """Guarda las alertas observadas de un contexto (deduplicadas por episodio, con la clave de su episodio:
    clave_del_episodio) y las cuenta en el resumen; las de un episodio ya cerrado sin nada nuevo (episodio_ya_cerrado)
    no se vuelven a abrir."""
    nuevas: list[Alerta] = []
    repetidas = 0
    for a in alertas_ctx:
        resumen["por_codigo"][a["codigo"]] = resumen["por_codigo"].get(a["codigo"], 0) + 1
        clave = clave_del_episodio(s, a)
        if clave != a["clave_dedup"]:
            resumen["episodios_con_otro_inicio"] += 1
            a["clave_dedup"] = clave
        if episodio_ya_cerrado(s, a):
            resumen["episodios_cerrados_sin_cambio"] += 1
            repetidas += 1
            continue
        registro, es_nueva = guardar_alerta(s, a, execution_id, version_u)
        if es_nueva:
            nuevas.append(registro)
        else:
            repetidas += 1
    return nuevas, repetidas


def _resumen_del_dia(resumen: dict, ctx: dict, ocupacion: dict | None) -> None:
    """Cuenta las horas del contexto de un día en el resumen de las alertas observadas."""
    horas = ctx.get("horas") or []
    resumen["horas_con_ocupacion_por_segmento"] += con_ocupacion_por_segmento(ctx, ocupacion)
    resumen["horas_evaluadas"] += sum(1 for h in horas if h.get("nueva"))
    resumen["horas_con_viajes_en_curso"] += sum(1 for h in horas if h.get("viajes_en_curso"))
    if ctx.get("fecha") is not None:
        resumen["dias_evaluados"].setdefault(ctx["ruta"], []).append(ctx["fecha"].isoformat())


def alertas_observadas(s: Session, rutas: list[str], df, validos, errores: list[dict], model_id: str | None,
                       umbrales_alertas: dict, referencia: datetime, fuente: Any, execution_id: uuid.UUID,
                       version_u: int | None, fallos: list[dict], ocupacion: dict | None = None
                       ) -> tuple[list[Alerta], int, dict]:
    """Evalúa ALT-005..ALT-009 con lo observado de cada ruta, día por día del lote (contextos_observados: cada día que
    quedó cerrado y, del día en curso, solo sus horas cerradas), y las guarda deduplicadas (episodios). `ocupacion`:
    {ruta: {(fecha, hora): resumen del segmento crítico}} de la ocupación actual por segmento que midió el ciclo
    (ALT-002); si la fuente la mide (leer_carga_segmentos), cada día se evalúa además con la que guardaron los ciclos
    anteriores (ocupacion_del_dia)."""
    from app.servicios import alertas as reglas

    por_segmento = ocupacion is not None and getattr(fuente, "leer_carga_segmentos", None) is not None
    nuevas: list[Alerta] = []
    repetidas = 0
    resumen: dict[str, Any] = {"por_codigo": {}, "horas_evaluadas": 0, "horas_con_ocupacion_por_segmento": 0,
                               "horas_con_viajes_en_curso": 0, "dias_evaluados": {},
                               "episodios_cerrados_sin_cambio": 0, "episodios_con_otro_inicio": 0,
                               "referencia": referencia.astimezone(ZONA).isoformat()}
    faltantes = _faltantes_por_ruta(df, errores)
    festivos = _festivos()
    for ruta in rutas:
        try:
            for ctx in contextos_observados(s, ruta, validos,
                                            sorted(faltantes.get(ruta, set()) | faltantes.get(None, set())),
                                            model_id, referencia, umbrales_alertas, fuente=fuente,
                                            festivos=festivos, fallos=fallos):
                medida = (ocupacion or {}).get(ruta)
                _resumen_del_dia(resumen, ctx, ocupacion_del_dia(s, ruta, ctx.get("fecha"), medida)
                                 if por_segmento else medida)
                n, r = _guardar_observadas(s, reglas.evaluar_observadas(ctx, umbrales_alertas), execution_id,
                                           version_u, resumen)
                nuevas.extend(n)
                repetidas += r
        except Exception as exc:  # noqa: BLE001 - una ruta con problemas no detiene el ciclo
            log.warning("alertas observadas de %s: %s", ruta, exc)
            fallos.append({"etapa": "alertas_observadas", "ruta": ruta, "error": str(exc)})
    return nuevas, repetidas, resumen


def construir_recomendacion(r: dict, *, ruta: str, fecha: date, hora: int, demanda_hora: float | None,
                            demanda_p90: float | None, execution_id: uuid.UUID | None,
                            prediction_id: uuid.UUID | None, umbrales_version: int | None,
                            entradas: dict, origen: str = "franja") -> Recomendacion:
    """Fila de recommendation: la de una franja (§10.2, ligada a su predicción) o una hora del plan del día
    (origen='plan_dia', sin predicción), con las dimensiones de §8.3."""
    return Recomendacion(
        recommendation_id=uuid.uuid4(), execution_id=execution_id, prediction_id=prediction_id, ruta=ruta,
        fecha=fecha, hora=hora, demanda_hora=demanda_hora, demanda_p90=demanda_p90,
        buses_hora=None if r.get("buses_hora") is None else int(r["buses_hora"]),
        headway_min=_num(r.get("headway_min")),
        vehiculos_requeridos=None if r.get("vehiculos_requeridos") is None else int(r["vehiculos_requeridos"]),
        capacidad_efectiva=_num(r.get("capacidad_efectiva")), ocupacion_esperada=_num(r.get("ocupacion_esperada")),
        viable=bool(r.get("viable", True)), motivo=r.get("motivo"),
        frecuencia_actual_min=_num(r.get("frecuencia_actual_min")), diferencia_min=_num(r.get("diferencia_min")),
        # §6.2: headway vigente de rutas.frecuenciadespachos y su diferencia con el recomendado (migración 0010)
        frecuenciadespachos_min=_num(r.get("frecuenciadespachos_min")),
        diferencia_frecuenciadespachos_min=_num(r.get("diferencia_frecuenciadespachos_min")),
        formula=r.get("formula"), umbrales_version=umbrales_version,
        detalle=json_seguro({"entradas": entradas, "salida": r}), origen=origen,
        **dimensiones_fila(ruta, fecha))


def parametros_recomendacion(info: dict, umbrales: dict) -> dict:
    return dict(
        capacidad=int(info.get("capacidad") or 50),
        ocupacion_objetivo=float(umbrales.get("ocupacion_objetivo_max", 0.85)),
        tiempo_ciclo_min=_num(info.get("tiempo_ciclo_min")),
        flota_disponible=None if info.get("flota") is None else int(info["flota"]),
        headway_min=float(umbrales.get("headway_minimo_min", 2.0)),
        headway_max=float(umbrales.get("headway_maximo_min", 10.0)),
        frecuencia_actual_min=_num(info.get("frecuencia_actual_min")),
    )


def guardar_prediccion(s: Session, r: dict, *, ruta: str, instante: datetime, horizonte_min: int,
                       model_id: str | None, execution_id: uuid.UUID | None) -> Prediccion:
    objetivo = instante + timedelta(minutes=horizonte_min)
    local = objetivo.astimezone(ZONA)
    pred = Prediccion(
        prediction_id=uuid.uuid4(), execution_id=execution_id, ruta=ruta, instante=instante,
        horizonte_min=horizonte_min, objetivo=objetivo, fecha=local.date(), hora=local.hour,
        pasajeros=float(r["pasajeros"]), p10=_num(r.get("p10")), p90=_num(r.get("p90")),
        model_id=str(r.get("model_id") or model_id or "desconocido"), feature_version=r.get("feature_version"),
        data_cutoff=a_instante(r.get("data_cutoff")), generated_at=a_instante(r.get("generated_at")) or ahora(),
        latencia_ms=_num(r.get("latencia_ms")), explicacion=json_seguro(r.get("explicacion") or []),
        variables=json_seguro(r.get("variables") or {}),
        # columnas de la migración 0004 (antes solo en variables)
        p10_modelo=_num(r.get("p10_modelo")), p90_modelo=_num(r.get("p90_modelo")),
        ajuste_conformal=_num(r.get("ajuste_conformal")),
        explicacion_local=json_seguro(r.get("explicacion_local")) if r.get("explicacion_local") else None,
        **dimensiones_fila(ruta, local.date()))
    s.add(pred)
    s.flush()
    return pred


@dataclass
class _Ciclo:
    """Estado de una ejecución del ciclo de frecuencia mientras corre (todo va en la misma sesión y transacción)."""

    execution_id: uuid.UUID
    p: dict
    fuente: Any
    df: Any
    validos: Any
    errores: list[dict]
    marca_anterior: datetime | None
    marca_nueva: datetime | None      # también es el data_cutoff de la ejecución
    filas_leidas: int
    filas_validas: int
    version_u: int
    umbrales: dict
    model_id: str | None
    metricas: dict[str, Any]
    predicciones: int = 0
    recomendaciones: int = 0
    recomendaciones_plan: int = 0
    repetidas: int = 0
    nuevas_alertas: list[Alerta] = field(default_factory=list)
    fallos: list[dict] = field(default_factory=list)
    monitoreo: dict[str, Any] = field(default_factory=dict)   # monitoreo §9.4 de esta ejecución
    ocupacion: dict[str, Any] = field(default_factory=dict)   # §10.1 ocupación actual por segmento (ocupacion.py)
    reactivas: dict[str, Any] = field(default_factory=dict)   # §10.1 restricción reactiva por ruta (plan y franjas)
    # RNF-005: ruta del trabajo (None = todas las rutas), partición leída (marcas de antes) y lectura (marcas nuevas)
    ruta: str | None = None
    particion: Any = None
    lectura: Any = None

    @property
    def horizontes(self):
        return self.p.get("horizontes") or HORIZONTES


class _RecomendacionesDeLaEjecucion:
    """Una recomendación de §10.2 por ruta y franja dentro de una ejecución.

    Los horizontes 30/60/120 de una ruta suelen caer en la misma hora principal, con la misma demanda por hora y la
    misma banda: optimizacion.recomendacion_franja da entonces el mismo resultado y se resuelve una sola vez. Cada
    horizonte recibe su propia copia (y su propia franja_prediccion). Un error no se guarda: se repite en cada
    horizonte, igual que sin esta memoria. `reactivas` ({ruta: restricción reactiva}): la ocupación actual por
    segmento de la ejecución (§10.1), la misma que recibe el plan del día (recomendacion_con_ocupacion)."""

    def __init__(self, umbrales: dict, version_u: int | None, reactivas: dict[str, dict] | None = None):
        self.umbrales = umbrales
        self.version_u = version_u
        self.reactivas = reactivas or {}
        self._resueltas: dict[tuple, tuple[dict, dict]] = {}

    def de_la_franja(self, info: dict, ruta: str, franja: dict) -> tuple[dict, dict]:
        clave = (ruta, franja["fecha"], franja["hora"], franja["demanda_hora"], franja["p90_hora"], franja["p10_hora"])
        if clave not in self._resueltas:
            self._resueltas[clave] = recomendacion_con_ocupacion(dict(info, ruta=ruta), franja, self.umbrales,
                                                                 self.version_u, self.reactivas.get(ruta))
        rec_d, entradas = self._resueltas[clave]
        return copy.deepcopy(rec_d), copy.deepcopy(entradas)


def recomendacion_con_ocupacion(info: dict, franja: dict, umbrales: dict, version_u: int | None,
                                reactiva: dict | None) -> tuple[dict, dict]:
    """§10.2 de la franja (optimizacion.recomendacion_franja) con la ocupación actual por segmento (§10.1): si la
    restricción reactiva de la ruta aplica en la hora de la franja (ocupacion.piso_de_la_franja), la franja no baja
    de los buses/h que exige la carga observada. Es la misma restricción (la misma carga y las mismas salidas pedidas)
    que pone el piso del plan del día en esa hora, pero en la franja el piso tampoco pasa de lo que la flota sostiene
    con el ciclo, así que puede quedar por debajo del piso del plan y lo dice (limitada_por_flota). Si la
    recomendación ya cumple el piso queda igual; si con el piso la franja no es ejecutable (flota, ciclo), queda la de
    siempre y lo dice. El resultado lleva «restriccion_reactiva» (aplicada o no, y por qué) siempre que la restricción
    toque esta franja."""
    from app.servicios import ocupacion, optimizacion

    pedido = dict(hora=franja["hora"], fecha=franja["fecha"], demanda_hora=franja["demanda_hora"],
                  demanda_p90=franja["p90_hora"], demanda_p10=franja["p10_hora"])
    rec_d, entradas = optimizacion.recomendacion_franja(info, umbrales, version_u, **pedido)
    piso = ocupacion.piso_de_la_franja(reactiva, franja["fecha"], franja["hora"], entradas)
    if piso is None:
        return rec_d, entradas
    sin_piso = rec_d.get("buses_hora")
    if not rec_d.get("viable") or int(sin_piso or 0) >= piso["salidas_minimas"]:
        rec_d["restriccion_reactiva"] = dict(piso, aplicada=False, motivo=_motivo_sin_piso(rec_d, piso))
        return rec_d, entradas
    ejecutable = _con_el_mayor_piso_ejecutable(info, umbrales, version_u, pedido, piso, int(sin_piso))
    if ejecutable is None:
        rec_d["restriccion_reactiva"] = dict(piso, aplicada=False, motivo=(
            "ni un bus/h más es ejecutable con la flota, el ciclo y las tipologías: se deja la recomendación sin piso"))
        return rec_d, entradas
    con_piso, entradas_piso, piso = ejecutable
    texto = (f"Restricción reactiva de ocupación observada (§10.1): en la última hora cerrada "
             f"({piso['hora_cerrada']}:00) el segmento crítico {piso['segmento']} llegó a "
             f"{round(100 * float(piso['ocupacion_observada'] or 0))} %; a las {piso['hora_aplica']}:00 no menos de "
             f"{piso['salidas_minimas']} buses/h ({piso['formula']}); sin el piso serían {sin_piso}.")
    con_piso["restriccion_reactiva"] = dict(piso, aplicada=True, buses_hora_sin_piso=sin_piso, motivo=texto)
    con_piso["explicacion"] = [*(con_piso.get("explicacion") or []), texto]
    return con_piso, dict(entradas_piso, restriccion_reactiva=con_piso["restriccion_reactiva"])


def _con_el_mayor_piso_ejecutable(info: dict, umbrales: dict, version_u: int | None, pedido: dict, piso: dict,
                                  sin_piso: int) -> tuple[dict, dict, dict] | None:
    """El MILP de la franja con el piso más alto que puede ejecutar: el de la restricción y, si con él la franja no es
    viable (la flota de cada tipología, el ciclo), uno menos cada vez, hasta uno más que la recomendación sin piso.
    Devuelve (recomendación, entradas, piso con las salidas exigidas y la fórmula) o None si ninguno es ejecutable.
    Son pocos MILP (memorizados) y solo en la hora en que actúa la restricción."""
    from app.servicios import ocupacion, optimizacion

    for k in range(int(piso["salidas_minimas"]), sin_piso, -1):
        rec, entradas = optimizacion.recomendacion_franja(info, umbrales, version_u, buses_minimos=k, **pedido)
        if rec.get("viable"):
            return rec, entradas, ocupacion.piso_acotado(piso, k)
    return None


def _motivo_sin_piso(rec_d: dict, piso: dict) -> str:
    """Por qué la restricción reactiva no cambió la recomendación de la franja."""
    if not rec_d.get("viable"):
        return "la franja no es viable ni sin el piso: se informa como está"
    if piso.get("limitada_por_flota"):
        return (f"la flota disponible no deja subir más: la recomendación ya está en {rec_d.get('buses_hora')} "
                f"buses/h y la carga observada pediría {piso['salidas_pedidas']}")
    return "la recomendación ya cumple el piso"


def _marca_nueva(ruta: str | None, lectura, marca_anterior: datetime | None) -> datetime | None:
    """La marca nueva del trabajo (y su data_cutoff): la de su ruta o, si es de todas, la mayor de la lectura."""
    nueva = lectura.marcas.get(ruta) if ruta else lectura.marca_global
    candidatas = [m for m in (marca_anterior, _instante_o_nada(a_instante(nueva))) if m is not None]
    return max(candidatas) if candidatas else None


def validar_calidad(df, lote: str, fuente: Any, umbrales: dict | None) -> tuple:
    """§6.3 del lote con los catálogos de la fuente, el reloj del ciclo y la tolerancia de oportunidad gobernada
    (§5.1 «datos atrasados» de la versión vigente de threshold_config, calidad.retraso_maximo_de)."""
    from app.servicios import calidad

    if df is None or not len(df):
        return df, []
    return calidad.validar_lote(df, lote, catalogos=catalogos_calidad(fuente), ahora=ahora(),
                                retraso_maximo=calidad.retraso_maximo_de(umbrales))


def _leer_lote(s: Session, execution_id: uuid.UUID) -> _Ciclo:
    """Lectura incremental de la partición del trabajo (su ruta, o todas, cada una desde su marca de agua; con el
    candado de la partición), umbrales vigentes, calidad (errores por lote, fila y causa, con la tolerancia de
    oportunidad gobernada) e histórico propio sin duplicados; luego el modelo con el que se pronostica."""
    from app.servicios import calidad
    from app.servicios import fuentes as _fuentes

    e = s.get(Ejecucion, execution_id)
    p = dict(e.parametros or {})
    hasta = date.fromisoformat(p["hasta"]) if p.get("hasta") else None
    fuente = obtener_fuente()
    tomar_candados_particion(s, e.ruta)
    particion = particion_del_trabajo(s, e, fuente)
    marca_anterior = particion.marca_anterior()
    _avance(execution_id, 10, "lectura_incremental", marca_agua_anterior=marca_anterior)
    lectura = _fuentes.leer_particion(fuente, particion, hasta)
    df = lectura.df
    filas_leidas = 0 if df is None else len(df)
    lote = _nombre_del_lote(execution_id, e.ruta, p)
    _avance(execution_id, 25, "calidad", filas_leidas=filas_leidas)
    version_u, umbrales = umbrales_de_la_ejecucion(s, p)     # la fijada por su ejecución partida, o la vigente
    validos, errores = validar_calidad(df, lote, fuente, umbrales)
    resumen_dq = _guardar_errores(s, execution_id, lote, errores)
    filas_validas = 0 if validos is None else len(validos)
    incorporadas = _incorporar_historico(s, validos, execution_id)
    activo = modelo_activo(s)
    metricas: dict[str, Any] = {"lote": lote, "errores_calidad": resumen_dq, "incorporadas_historico": incorporadas,
                                **reportar_unicidad(s, execution_id, lote, errores)}   # §6.3 al responsable
    if filas_leidas and getattr(calidad, "resumen", None) is not None:
        try:   # §6.3: conteos por dimensión y código, filas en cuarentena y latencia media del lote
            metricas["calidad"] = json_seguro(calidad.resumen(df, errores))
        except Exception as exc:  # noqa: BLE001 - el resumen es informativo
            metricas["calidad"] = {"error": str(exc)}
    if getattr(fuente, "resumen_lectura", None) is not None:   # leídas, tardías, modificadas y repetidas
        metricas["lectura"] = fuente.resumen_lectura
        metricas["fuente_estado"] = fuente.estado_incremental
    if filas_validas:   # último día de datos del trabajo: la madre de una ejecución partida monitorea hasta ahí
        metricas["datos_hasta"] = _a_fecha(max(validos["fecha"])).isoformat()
    c = _Ciclo(execution_id=execution_id, p=p, fuente=fuente, df=df, validos=validos, errores=errores,
               marca_anterior=marca_anterior, marca_nueva=_marca_nueva(e.ruta, lectura, marca_anterior),
               filas_leidas=filas_leidas, filas_validas=filas_validas, version_u=version_u, umbrales=umbrales,
               model_id=p.get("model_id") or (activo.model_id if activo else None), metricas=metricas,
               ruta=e.ruta, particion=particion, lectura=lectura)
    metricas["particion"] = resumen_particion(c)
    return c


def _nombre_del_lote(execution_id: uuid.UUID, ruta: str | None, p: dict) -> str:
    """Lote de los errores de calidad: «id8:hasta», o «id8:ruta:hasta» en el trabajo de una ruta."""
    return f"{execution_id.hex[:8]}:{ruta + ':' if ruta else ''}{p.get('hasta') or 'todo'}"


def _notificar_nuevas(s: Session, c: _Ciclo) -> None:
    """Notificaciones simuladas de las alertas nuevas críticas y de las abiertas que escalaron a crítica (§7.2)."""
    escaladas = list(dict.fromkeys(s.info.pop(CLAVE_ESCALADAS, [])))
    escaladas = [a for a in escaladas if a not in c.nuevas_alertas]
    if escaladas:
        c.metricas["alertas_escaladas"] = len(escaladas)
    if c.p.get("notificar", True) and (c.nuevas_alertas or escaladas):
        por_estado: dict[str, int] = {}
        c.metricas["notificaciones"] = _notificar(s, c.execution_id, c.nuevas_alertas + escaladas, c.fallos,
                                                  escaladas={a.alert_id for a in escaladas}, por_estado=por_estado)
        c.metricas["notificaciones_por_estado"] = por_estado      # simulado, omitida (bajo la severidad mínima)…


def _sin_datos_nuevos(s: Session, c: _Ciclo) -> None:
    """Sin filas nuevas no se reprocesa el histórico; ALT-009 igual mide la frescura frente a 2 períodos de ingesta."""
    from app.servicios import datos

    c.metricas["nota"] = "Sin datos nuevos desde la marca de agua: no se reprocesa el histórico."
    if es_intradia(c.p):
        c.metricas["intradia"] = {"nota": NOTA_INTRADIA, "instante": c.p.get("instante")}
    rutas_frescura = c.p.get("rutas") or [r["ruta"] for r in datos.catalogo_rutas()]
    obs_nuevas, c.repetidas, c.metricas["alertas_observadas"] = alertas_observadas(
        s, rutas_frescura, c.df, c.validos, c.errores, c.model_id, dict(c.umbrales) | {"version": c.version_u},
        referencia_temporal(c.p, _instante_por_defecto(c.p, None, c.marca_nueva)), c.fuente, c.execution_id,
        c.version_u, c.fallos)
    c.nuevas_alertas.extend(obs_nuevas)
    _notificar_nuevas(s, c)


def _evaluar_error(c: _Ciclo) -> dict[str, float]:
    """Paso 3 del ciclo de §14.2: error del modelo activo sobre los días recién llegados (WAPE por ruta, en 0-1)."""
    from app.servicios import inferencia

    wape_por_ruta: dict[str, float] = {}
    if not (c.filas_validas and c.model_id):
        return wape_por_ruta
    try:   # el trabajo de UNA ruta (RNF-005) evalúa solo su ruta
        ev = inferencia.evaluar(c.model_id, min(c.validos["fecha"]), max(c.validos["fecha"]),
                                **({"rutas": [c.ruta]} if c.ruta else {}))
        c.metricas["evaluacion_error"] = json_seguro(ev)
        for nombre_ruta, m in (ev.get("por_ruta") or {}).items():
            w = _num((m or {}).get("wape"))
            if w is not None:
                wape_por_ruta[nombre_ruta] = w / 100.0 if w > 1.5 else w
    except Exception as exc:  # noqa: BLE001
        c.fallos.append({"etapa": "evaluacion", "error": str(exc)})
    return wape_por_ruta


def _monitorear(s: Session, c: _Ciclo, wape_por_ruta: dict[str, float]) -> None:
    """Monitoreo de §9.4: ALT-010 usa el WAPE MÓVIL por ruta; también monitorea al retador. El trabajo de UNA ruta
    calcula las mismas métricas sin guardar la fila: la guarda la ejecución madre, una vez por ejecución."""
    from app.servicios import monitoreo as _monitoreo

    if c.ruta is not None:
        c.monitoreo = _monitoreo.en_ciclo_de_ruta(s, c.model_id, c.validos, c.umbrales, c.fallos, c.ruta)
    else:
        c.monitoreo = _monitoreo.en_ciclo(s, c.execution_id, c.model_id, c.validos, c.umbrales, c.version_u,
                                          c.fallos)
    wape_por_ruta.update({r: w for r, w in (c.monitoreo.get("wape_por_ruta") or {}).items() if w is not None})


def _pronostico_corto_plazo(s: Session, c: _Ciclo, rutas: list[str], instante: datetime) -> None:
    """RF-005 y §7.3 paso 5: el pronóstico de corto plazo (30, 60 y 120 min por ruta, sentido y segmento, con lo
    observado hasta el instante) de cada ruta y horizonte del ciclo, guardado con su execution_id en
    prediction_corto_plazo. Un instante o una fecha fuera de la cobertura del modelo se anota como omitido; un error
    del modelo queda en los fallos de la ejecución."""
    from app.servicios import corto_plazo as cp

    resumen: dict[str, Any] = {"pronosticos": 0, "omitidos": [], "model_id": None}
    if s is None:                       # ciclo sin base (pruebas de una parte del ciclo): no hay dónde guardarlo
        c.metricas["corto_plazo"] = dict(resumen, omitido="sin sesión de base de datos")
        return
    for ruta in rutas:
        for h in c.horizontes:
            try:
                r = cp.pronosticar(ruta, instante, int(h))
            except cp.FueraDeCobertura as exc:
                resumen["omitidos"].append({"ruta": ruta, "horizonte_min": int(h), "motivo": str(exc)})
                continue
            except Exception as exc:  # noqa: BLE001 - se registra por ruta y horizonte
                c.fallos.append({"etapa": "corto_plazo", "ruta": ruta, "horizonte_min": h, "error": str(exc)})
                continue
            r["generated_at"] = ahora().astimezone(ZONA).isoformat(timespec="seconds")
            cp.guardar(s, r, execution_id=c.execution_id)
            resumen["pronosticos"] += 1
            resumen["model_id"] = r["model_id"]
    c.metricas["corto_plazo"] = resumen


def _pronostico_y_recomendacion(s: Session, c: _Ciclo, ruta: str, info: dict, h: Any, instante: datetime,
                                wape_por_ruta: dict[str, float], recomendador: _RecomendacionesDeLaEjecucion,
                                contextos: list) -> None:
    """Un horizonte de una ruta: guarda la predicción y la recomendación de su franja y agrega el contexto de la
    alerta de pronóstico. Si algo falla, queda en los fallos de la ejecución por ruta y horizonte."""
    from app.routers.predicciones import _franja_de_la_prediccion as franja_de_prediccion
    from app.servicios import alertas, inferencia

    try:
        r = inferencia.predecir(ruta, instante, int(h), model_id=c.model_id)
    except Exception as exc:  # noqa: BLE001 - se registra por ruta y horizonte
        c.fallos.append({"etapa": "prediccion", "ruta": ruta, "horizonte_min": h, "error": str(exc)})
        return
    pred = guardar_prediccion(s, r, ruta=ruta, instante=instante, horizonte_min=int(h), model_id=c.model_id,
                              execution_id=c.execution_id)
    c.predicciones += 1
    # §10.2 igual que POST /predictions/run: la hora principal de la ventana con su demanda POR HORA y su banda
    # calibrada (la demanda de la ventana de 30/60/120 min no es una tasa horaria)
    franja = franja_de_prediccion(pred)
    try:
        rec_d, entradas = recomendador.de_la_franja(info, ruta, franja)
    except Exception as exc:  # noqa: BLE001
        c.fallos.append({"etapa": "recomendacion", "ruta": ruta, "horizonte_min": h, "error": str(exc)})
        return
    rec_d["franja_prediccion"] = franja
    s.add(construir_recomendacion(rec_d, ruta=ruta, fecha=franja["fecha"], hora=franja["hora"],
                                  demanda_hora=franja["demanda_hora"], demanda_p90=franja["p90_hora"],
                                  execution_id=c.execution_id, prediction_id=pred.prediction_id,
                                  umbrales_version=c.version_u, entradas=entradas))
    c.recomendaciones += 1
    # alertas de pronóstico en unidades por hora: la demanda de la franja recomendada frente a la
    # capacidad por hora; la ventana de la alerta es esa misma hora
    contextos.append(alertas.contexto_pronostico(
        ruta, int(h), franja,
        {"pasajeros": pred.pasajeros, "p10": pred.p10, "p90": pred.p90, "model_id": pred.model_id},
        entradas, rec_d, empresa=empresa_de(ruta), detectada_en=ahora(),
        # ALT-010 es del modelo: se evalúa una vez por ruta (primer horizonte), no por ventana
        wape_movil=wape_por_ruta.get(ruta) if h == c.horizontes[0] else None,
        # §5.3 variables influyentes (SHAP del pronóstico); los campos faltantes pasan a ALT-009
        # observada (una por ruta y día, no una por horizonte)
        variables_influyentes=alertas.variables_desde_shap(r.get("explicacion_local"))))


def _alertas_de_pronostico(s: Session, c: _Ciclo, contextos: list[dict], umbrales_alertas: dict) -> None:
    """Alertas de pronóstico deduplicadas."""
    from app.servicios import alertas

    tendencia_por_horizonte(contextos)
    # los horizontes que caen en la misma franja dan una sola alerta (alertas.evaluar_pronostico)
    for a in alertas.evaluar_pronostico(contextos, umbrales_alertas):
        registro, es_nueva = guardar_alerta(s, a, c.execution_id, c.version_u)
        if es_nueva:
            c.nuevas_alertas.append(registro)
        else:
            c.repetidas += 1


def _particion_de_la_foto(instante: datetime) -> None:
    """La partición mensual de la foto de variables, creada antes de escribir predicciones y fuera de la transacción
    del ciclo (monitoreo.asegurar_particion_previa): dos trabajos de rutas distintas a la vez no se interbloquean."""
    from app.servicios import monitoreo as _monitoreo

    try:
        _monitoreo.asegurar_particion_previa(instante)
    except Exception as exc:  # noqa: BLE001 - sin base para la DDL corta, guardar_snapshot lo intenta como antes
        log.info("partición de la foto no asegurada antes del ciclo: %s", exc)


def _ocupacion_actual(s: Session, c: _Ciclo, instante: datetime) -> None:
    """§10.1 ocupación actual por segmento de las franjas que trajo el lote, solo de las horas ya cerradas a la
    referencia del ciclo (app/servicios/ocupacion.py), en un punto de guardado de la transacción del ciclo: si la
    lectura o el cálculo fallan, el ciclo sigue sin ella (queda en los fallos) y el plan y ALT-002 usan solo el
    pronóstico y el factor de carga. Después arma, una vez por ejecución, la restricción reactiva de cada ruta para el
    día del instante (c.reactivas): la reciben el plan del día y las recomendaciones de 30, 60 y 120 min."""
    from app.servicios import ocupacion

    try:
        with s.begin_nested():
            c.ocupacion = ocupacion.del_ciclo(s, c.fuente, c.validos, c.execution_id, c.umbrales, c.version_u,
                                              cerradas_hasta=referencia_temporal(c.p, instante))
    except Exception as exc:  # noqa: BLE001 - la ocupación por segmento no detiene el ciclo
        log.warning("ocupación por segmento: %s", exc)
        c.fallos.append({"etapa": "ocupacion_segmentos", "error": str(exc)})
        c.ocupacion = {"por_ruta": {}, "resumen": {"error": str(exc)}}
    c.metricas["ocupacion_segmentos"] = json_seguro(c.ocupacion.get("resumen"))
    fecha = instante.astimezone(ZONA).date()
    c.reactivas = {ruta: ocupacion.restriccion_reactiva(observada, fecha, instante, c.umbrales)
                   for ruta, observada in (c.ocupacion.get("por_ruta") or {}).items() if observada}


# Un ciclo intradía del planificador (§10.1 ocupación actual en la operación programada; planificador.py) no hace lo
# que es del modelo ni lo que se lee una vez al día: lo hace el ciclo diario con días completos.
NOTA_INTRADIA = ("Ciclo intradía: no evalúa el error del modelo ni guarda el monitoreo, la sombra o la política (el "
                 "día en curso está incompleto: lo hace el ciclo diario con días completos), no lee los consolidados "
                 "de Extreme ni pide el refresco de la agregación de segmentos (se hacen una vez al día).")


def es_intradia(p: dict | None) -> bool:
    """¿Es un ciclo intradía del planificador (parametros.intradia, planificador.tarea_ciclo_intradia)?"""
    return bool((p or {}).get("intradia"))


# La franja planificada más reciente que espera en la cola después de una dada (de cualquier ciclo de frecuencia del
# planificador: intradía o diario; las ejecuciones pedidas con POST no tienen franja).
_SQL_FRANJA_POSTERIOR = text("""
SELECT max(x.programada_para) FROM ai_frecuencias.execution_log x
 WHERE x.tipo = 'frecuencia' AND x.estado = 'en_cola' AND x.programada_para > :franja
""")


def franja_posterior_en_cola(s: Session, e: Ejecucion) -> datetime | None:
    """§10.1, RNF-001: la franja planificada posterior que ya espera en la cola detrás del ciclo intradía `e` (la de su
    madre, si `e` es el trabajo de una ruta), o None si `e` no es intradía o no hay ninguna. Pasa cuando la cola se
    detuvo o un trabajo largo la retrasó: la franja vieja ya no sirve para programar la hora en curso, y leer con su
    instante consumiría la marca de agua de lo que llegó después (también los datos de la noche que necesita el ciclo
    diario para cerrar el día completo)."""
    if not es_intradia(e.parametros):
        return None
    franja = e.programada_para
    if franja is None and e.padre_id is not None:
        franja = s.scalar(select(Ejecucion.programada_para).where(Ejecucion.execution_id == e.padre_id))
    return None if franja is None else s.scalar(_SQL_FRANJA_POSTERIOR, {"franja": franja})


def _omitida_por_franja_posterior(execution_id: uuid.UUID) -> bool:
    """Cierra «ok», sin leer la fuente ni mover la marca de agua, el ciclo intradía que tiene una franja posterior
    esperando en la cola (franja_posterior_en_cola): esa franja lee lo mismo desde la misma marca con un instante más
    reciente. Devuelve True si la omitió."""
    from app.servicios import cola

    with sesion_contexto() as s:
        e = s.get(Ejecucion, execution_id)
        posterior = franja_posterior_en_cola(s, e)
        if posterior is None:
            return False
        nota = (f"Franja intradía omitida: la franja {posterior.astimezone(ZONA):%Y-%m-%d %H:%M} ya espera en la cola "
                "y lee lo mismo desde la misma marca de agua, con un instante más reciente.")
        cola.cerrar_ok(s, execution_id, dict(
            estado="ok", etapa="terminada", progreso=100, filas_leidas=0, filas_validas=0, mensaje=nota,
            metricas=json_seguro({"intradia": {"nota": NOTA_INTRADIA, "instante": (e.parametros or {}).get("instante"),
                                               "omitida": nota, "franja_posterior": posterior}}),
            terminado_en=ahora(), actualizado_en=ahora()))
    log.info("Ciclo intradía %s omitido: la franja %s ya espera en la cola", execution_id, posterior.isoformat())
    return True


def _error_y_monitoreo(s: Session, c: _Ciclo) -> dict[str, float]:
    """Paso 3 de §14.2 (el error del modelo sobre lo recién llegado) y el monitoreo de §9.4, que da el WAPE móvil de
    ALT-010. Un ciclo intradía no los hace (NOTA_INTRADIA): con el día en curso incompleto el error saldría inflado y la
    política del modelo (reversión, compuerta, reentreno) decidiría con él."""
    if es_intradia(c.p):
        c.metricas["intradia"] = {"nota": NOTA_INTRADIA, "instante": c.p.get("instante")}
        return {}
    wape_por_ruta = _evaluar_error(c)
    _monitorear(s, c, wape_por_ruta)
    return wape_por_ruta


def _info_de_las_rutas() -> dict[str, dict]:
    """{ruta: su información del catálogo} para las franjas del ciclo, con el headway vigente de §6.1 y §6.2 que da
    datos.frecuencia_vigente, el mismo que lee el plan del día (optimizacion.plan_dia, con datos.ruta_info): en modo
    integrado, rutas.frecuenciadespachos de la tabla rutas de la base de Extreme (frecuencia_fuente = «fuente»); si no,
    o si la fuente no responde o no trae valor, el del catálogo empaquetado. Así la franja, su fila de recommendation y
    el plan de un mismo ciclo comparan con el mismo valor y dicen la misma fuente (fuente_frecuenciadespachos). La
    lectura de la fuente se guarda unos minutos (fuentes.frecuencias_despacho): no es una consulta por ruta."""
    from app.servicios import datos

    return {r["ruta"]: datos.frecuencia_vigente(r) for r in datos.catalogo_rutas()}


def _con_datos_nuevos(s: Session, c: _Ciclo) -> None:
    """Con datos nuevos: error del modelo, monitoreo, ocupación actual por segmento (§10.1), predicciones 30/60/120
    por ruta con su recomendación (con la restricción reactiva de la ocupación actual en la hora en que actúa y el
    headway vigente del plan, _info_de_las_rutas), alertas deduplicadas (de pronóstico y observadas) y
    notificaciones."""
    instante = _instante_por_defecto(c.p, c.validos, c.marca_nueva)
    wape_por_ruta = _error_y_monitoreo(s, c)
    _ocupacion_actual(s, c, instante)
    _avance(c.execution_id, 45, "prediccion")

    _particion_de_la_foto(instante)
    catalogo = _info_de_las_rutas()
    rutas = c.p.get("rutas") or list(catalogo)
    recomendador = _RecomendacionesDeLaEjecucion(c.umbrales, c.version_u, c.reactivas)
    contextos: list[dict] = []
    for ruta in rutas:
        for h in c.horizontes:
            _pronostico_y_recomendacion(s, c, ruta, catalogo.get(ruta, {}), h, instante, wape_por_ruta, recomendador,
                                        contextos)
    _pronostico_corto_plazo(s, c, rutas, instante)
    _avance(c.execution_id, 70, "alertas")

    umbrales_alertas = dict(c.umbrales) | {"version": c.version_u}
    _alertas_de_pronostico(s, c, contextos, umbrales_alertas)
    # ALT-005..ALT-009 con los datos OBSERVADOS de la ejecución (RF-009); ALT-002 con la ocupación por segmento
    obs_nuevas, obs_repetidas, c.metricas["alertas_observadas"] = alertas_observadas(
        s, rutas, c.df, c.validos, c.errores, c.model_id, umbrales_alertas, referencia_temporal(c.p, instante),
        c.fuente, c.execution_id, c.version_u, c.fallos, ocupacion=c.ocupacion.get("por_ruta"))
    c.nuevas_alertas.extend(obs_nuevas)
    c.repetidas += obs_repetidas
    _avance(c.execution_id, 85, "notificaciones")
    _notificar_nuevas(s, c)
    _avance(c.execution_id, 92, "plan_dia")
    plan_y_respuesta(s, c, instante)


FORMULA_PLAN = ("Plan del día (MILP de D5) con el pronóstico horario P10/P50/P90 del modelo activo y los umbrales "
                "vigentes: salidas por hora, headway = minutos / salidas y vehículos = ceil(ciclo / headway)")


def _fila_plan(h: dict) -> dict:
    """Una hora del plan del día en los campos de recommendation (y el detalle completo de la hora)."""
    headway, actual = _num(h.get("headway_min")), _num(h.get("frecuencia_actual_min"))
    return {"buses_hora": h.get("salidas"), "headway_min": headway,
            "vehiculos_requeridos": h.get("vehiculos_requeridos"), "capacidad_efectiva": h.get("capacidad_efectiva"),
            "ocupacion_esperada": h.get("ocupacion_esperada"), "viable": bool(h.get("viable", True)),
            "motivo": h.get("motivo"), "frecuencia_actual_min": actual,
            "diferencia_min": None if headway is None or actual is None else round(headway - actual, 2),
            "frecuenciadespachos_min": h.get("frecuenciadespachos_min"),
            "diferencia_frecuenciadespachos_min": h.get("diferencia_frecuenciadespachos_min"),
            "formula": FORMULA_PLAN, "hora_plan": h}


def _parametros_del_plan(plan: dict) -> dict | None:
    """Los parámetros gobernados con que se resolvió el plan (valor y fuente de cada uno, §5.1), para que el plan
    persistido diga con qué tarifa, elasticidad, suavidad, costos y límites se calculó."""
    parametros = plan.get("parametros")
    if not isinstance(parametros, dict):
        return None
    return {n: {"valor": e.get("valor"), "fuente": e.get("fuente")} for n, e in parametros.items()
            if isinstance(e, dict)}


def guardar_plan_dia(s: Session, c: _Ciclo, ruta: str, fecha: date, plan: dict) -> int:
    """D4: una fila de recommendation por (ruta, hora) del plan del día, con origen='plan_dia' y sin predicción."""
    return persistir_plan_dia(s, c.execution_id, c.version_u, ruta, fecha, plan)


def persistir_plan_dia(s: Session, execution_id: uuid.UUID, version_u: int | None, ruta: str, fecha: date,
                       plan: dict) -> int:
    """Las filas origen='plan_dia' de un plan (todas las horas de 4 a 20 h; una hora sin operación queda con 0
    salidas, headway nulo y su motivo). Las usan el ciclo diario y el trabajo «respuesta» de la cola."""
    horas = plan.get("horas") or []
    entradas = {"fuente_pronostico": plan.get("fuente_pronostico"), "model_id": plan.get("model_id"),
                "calibracion_version": plan.get("calibracion_version"), "umbrales_version": version_u,
                "estado_solver": plan.get("estado_solver"), "tipo_dia": plan.get("tipo_dia"),
                "salidas_dia": plan.get("salidas_dia"), "vehiculos_hora_pico": plan.get("vehiculos_hora_pico"),
                "parametros": _parametros_del_plan(plan), "flota_y_ciclo": plan.get("flota_y_ciclo"),
                "holgura_flota": plan.get("holgura_flota"),
                "frecuenciadespachos_min": plan.get("frecuenciadespachos_min"),
                "fuente_frecuenciadespachos": plan.get("fuente_frecuenciadespachos"),
                "ocupacion_actual": plan.get("ocupacion_actual")}
    for h in horas:
        fila = _fila_plan(h)
        s.add(construir_recomendacion(
            fila, ruta=ruta, fecha=fecha, hora=int(h["hora"]), demanda_hora=_num(h.get("pasajeros_previstos")),
            demanda_p90=_num(h.get("pasajeros_p90")), execution_id=execution_id, prediction_id=None,
            umbrales_version=version_u, entradas=entradas, origen="plan_dia"))
    s.flush()
    return len(horas)


def plan_y_respuesta(s: Session, c: _Ciclo, instante: datetime) -> None:
    """D4 y C3: al cerrar el ciclo, el plan del día siguiente por ruta con el modelo activo (optimizacion.plan_dia) y la
    foto de la respuesta del reto (respuesta.precalcular), en la misma transacción. Cada paso va en un punto de
    guardado: si falla, se revierte solo ese paso y la ejecución termina «ok» con la advertencia en métricas."""
    if c.p.get("plan_dia") is False:
        return
    from app.servicios import datos

    fecha = instante.astimezone(ZONA).date()
    rutas = c.p.get("rutas") or [r["ruta"] for r in datos.catalogo_rutas()]
    resumen: dict[str, Any] = {"fecha": fecha.isoformat(), "rutas": {}, "advertencias": []}
    c.metricas["plan_dia"] = resumen
    t0 = time.perf_counter()
    try:
        from app.servicios import optimizacion

        calcular = optimizacion.plan_dia
    except (ImportError, AttributeError) as exc:
        resumen["advertencias"].append({"etapa": "plan_dia", "error": f"plan del día no disponible: {exc}"})
        calcular = None
    planes: dict[str, dict] = {}
    for ruta in rutas if calcular is not None else []:
        try:
            with s.begin_nested():
                plan = calcular(fecha, ruta, umbrales=c.umbrales, umbrales_version=c.version_u, model_id=c.model_id,
                                **_ocupacion_del_plan(c, ruta))
                n = guardar_plan_dia(s, c, ruta, fecha, plan)
            planes[ruta] = plan
            c.recomendaciones_plan += n
            resumen["rutas"][ruta] = {"horas": n, "model_id": plan.get("model_id"),
                                      "calibracion_version": plan.get("calibracion_version"),
                                      "fuente_pronostico": plan.get("fuente_pronostico"),
                                      "salidas_dia": plan.get("salidas_dia"),
                                      "restriccion_reactiva": _resumen_reactiva(plan.get("ocupacion_actual"))}
        except Exception as exc:  # noqa: BLE001 - una ruta sin plan no detiene el cierre
            log.warning("plan del día de %s: %s", ruta, exc)
            resumen["advertencias"].append({"etapa": "plan_dia", "ruta": ruta, "error": str(exc)})
    resumen["duracion_s"] = round(time.perf_counter() - t0, 3)
    _foto_respuesta(s, c, fecha, rutas, planes)


def _ocupacion_del_plan(c: _Ciclo, ruta: str) -> dict[str, Any]:
    """§10.1 ocupación actual como entrada del plan: la restricción reactiva de la ruta (ocupacion.restriccion_reactiva,
    armada en _ocupacion_actual con la ocupación observada del ciclo, el día y el instante del plan y su versión de
    umbrales; la misma que reciben las recomendaciones de la franja). Sin ocupación observada de la ruta, nada: el plan
    se llama como siempre (y queda idéntico)."""
    reactiva = (c.reactivas or {}).get(ruta)
    return {"ocupacion_actual": reactiva} if reactiva else {}


def _resumen_reactiva(reactiva: dict | None) -> dict | None:
    """Lo que dicen las métricas del ciclo de la restricción reactiva de una ruta."""
    if not reactiva:
        return None
    return {k: reactiva.get(k) for k in ("aplica", "hora_cerrada", "hora_aplica", "ocupacion_observada",
                                         "salidas_minimas", "motivo")}


def _foto_respuesta(s: Session, c: _Ciclo, fecha: date, rutas: list[str],
                    planes: dict[str, dict] | None = None) -> None:
    """C2: respuesta.precalcular en un punto de guardado; un fallo queda como advertencia en métricas. Recibe los
    planes que el ciclo acaba de calcular y persistir y la versión de umbrales del ciclo (§5.1; en una ejecución
    partida por ruta, la fijada al crearla): la foto queda con esa versión y usa los planes tal cual (no vuelve a
    resolver el MILP), así que la foto y GET /recommendations/plan dicen lo mismo hora por hora, también si un
    PUT /thresholds llega mientras corre la ejecución (GET /respuesta lee la foto de la versión vigente: tras ese PUT
    responde 404 «sin_calcular» hasta el cálculo siguiente). Si un plan no sirve tal cual (el modelo activo cambió a
    mitad de la ejecución), precalcular lo vuelve a resolver: las métricas dicen qué planes reutilizó la foto, cuáles
    volvió a resolver y por qué, y cuáles calculó porque el ciclo no los traía."""
    t0 = time.perf_counter()
    planes = dict(planes or {})
    try:
        from app.servicios import respuesta

        with s.begin_nested():
            r = respuesta.precalcular(s, fecha, list(rutas), execution_id=c.execution_id, planes=planes,
                                      umbrales=(c.version_u, dict(c.umbrales or {})))
        traz = r.get("trazabilidad") or {}
        uso = r.get("planes") or {}
        c.metricas["respuesta"] = {"fecha": r.get("fecha"), "guardadas": r.get("guardadas"),
                                   "model_id": traz.get("model_id"), "umbrales_version": traz.get("umbrales_version"),
                                   "fuente_pronostico": traz.get("fuente_pronostico"),
                                   "planes_reutilizados": uso.get("reutilizados", []),
                                   "planes_recalculados": uso.get("recalculados", []),
                                   "planes_calculados": uso.get("calculados", []),
                                   "motivos_recalculo": uso.get("motivos") or {},
                                   "duracion_s": round(time.perf_counter() - t0, 3)}
    except Exception as exc:  # noqa: BLE001 - sin la foto, GET /respuesta responde 404 «sin_calcular»
        log.warning("foto de la respuesta del %s: %s", fecha, exc)
        c.metricas["respuesta"] = {"fecha": fecha.isoformat(), "advertencia": str(exc),
                                   "duracion_s": round(time.perf_counter() - t0, 3)}


def _cierre_del_trabajo_de_ruta(s: Session, c: _Ciclo) -> dict[str, Any]:
    """El trabajo de UNA ruta guarda la foto de variables de sus predicciones (§11.2); el monitoreo, la sombra y la
    política son del modelo y los cierra la ejecución madre (una vez por ejecución)."""
    from app.servicios import monitoreo as _mon

    out = {k: v for k, v in (c.monitoreo or {}).items() if k != "wape_por_ruta"}
    out.update(_mon.foto_del_ciclo(s, c.execution_id, c.marca_nueva, c.predicciones, c.fallos))
    out["cierre_del_modelo"] = "ejecución madre"
    return out


def consolidados_de_la_ejecucion(s: Session, execution_id: uuid.UUID, umbrales: dict | None, fallos: list[dict],
                                 metricas: dict[str, Any]) -> None:
    """§6.1, §6.3, §7.3 paso 3, §11.2: los consolidados de Extreme (timbradas_consolidado, timbradas_segmentos_anio y
    timbradas_segmentos_consolidado) una vez por ejecución: la de todas las rutas o, partida por ruta, la madre al
    cerrar. Lectura incremental con su marca por tabla, calidad y contraste con la agregación propia, con las
    tolerancias de la versión de umbrales de la ejecución, en la transacción del cierre (app/servicios/consolidados.py).
    El resumen queda en metricas.calidad.consolidados."""
    from app.servicios import consolidados

    resumen = metricas.setdefault("calidad", {})
    resumen["consolidados"] = consolidados.en_ciclo(s, execution_id, umbrales, fallos)


def _cerrar_ciclo(s: Session, c: _Ciclo, t0: float) -> None:
    """Foto de variables (§11.2), sombra y política (RF-018/RF-019), consolidados de Extreme (una vez por ejecución,
    después del candado del modelo), métricas, marcas de agua por ruta (RNF-005) y cierre con cerca: el «ok» final pasa
    por cola.cerrar_ok en la MISMA transacción que los resultados y las marcas, y solo si la reserva sigue siendo de
    este trabajador."""
    from app.servicios import cola

    if c.ruta is not None:
        c.metricas["monitoreo"] = _cierre_del_trabajo_de_ruta(s, c)
    elif c.predicciones or c.monitoreo:
        from app.servicios import monitoreo as _mon

        tomar_candado_modelo(s)       # la política, de un ciclo a la vez (también frente a la madre de un día)
        c.metricas["monitoreo"] = _mon.cerrar_ciclo(s, c.execution_id, c.marca_nueva, c.predicciones, c.monitoreo,
                                                    c.umbrales, c.version_u, c.fallos)
    # después del candado del modelo, como la madre; el trabajo de una ruta y el ciclo intradía no los leen
    if c.ruta is None and not es_intradia(c.p):
        consolidados_de_la_ejecucion(s, c.execution_id, c.umbrales, c.fallos, c.metricas)
    c.metricas.update({
        "predicciones": c.predicciones, "recomendaciones": c.recomendaciones,
        "recomendaciones_plan_dia": c.recomendaciones_plan, "alertas_nuevas": len(c.nuevas_alertas),
        "alertas_repetidas": c.repetidas, "fallos": c.fallos, "duracion_s": round(time.perf_counter() - t0, 3)})
    feature_version = None
    if c.predicciones:
        feature_version = s.scalar(select(Prediccion.feature_version)
                                   .where(Prediccion.execution_id == c.execution_id).limit(1))
    if c.particion is not None:
        c.metricas["particion"]["marcas_guardadas"] = guardar_marcas(s, c)
    cola.cerrar_ok(s, c.execution_id, dict(
        estado="ok", etapa="terminada", progreso=100, marca_agua_anterior=c.marca_anterior,
        marca_agua_nueva=c.marca_nueva, data_cutoff=c.marca_nueva, filas_leidas=c.filas_leidas,
        filas_validas=c.filas_validas, model_id=c.model_id, feature_version=feature_version,
        umbrales_version=c.version_u, metricas=json_seguro(c.metricas),
        mensaje="Terminada" if not c.fallos else f"Terminada con {len(c.fallos)} fallos parciales",
        terminado_en=ahora(), actualizado_en=ahora()))


def _es_madre(execution_id: uuid.UUID) -> bool:
    with sesion_contexto() as s:
        return s.scalar(select(Ejecucion.particion).where(Ejecucion.execution_id == execution_id)) is not None


def _ciclo_frecuencia(execution_id: uuid.UUID) -> None:
    """Ciclo diario de §14.2. Los resultados del intento se escriben en una sola sesión y transacción, que el cierre
    confirma con cola.cerrar_ok (si el intento falla, no quedan resultados parciales). La ejecución madre de una
    ejecución partida por ruta no lee: cierra lo del modelo cuando terminaron sus trabajos (_ciclo_de_la_madre) y es
    ella, no cada trabajo de ruta, la que pide el refresco de la agregación de segmentos, una vez por ejecución. Un
    ciclo intradía del planificador (es_intradia) no lo pide: la agregación es una estadística histórica por día de la
    semana y hora, que el ciclo diario y PLAN_SEGMENTOS_CRON refrescan una vez al día. Un ciclo intradía con una franja
    posterior ya en la cola se cierra sin leer (_omitida_por_franja_posterior)."""
    if _es_madre(execution_id):
        _pedir_refresco_segmentos(execution_id, _ciclo_de_la_madre(execution_id))
        return
    if _omitida_por_franja_posterior(execution_id):
        return
    t0 = time.perf_counter()
    with sesion_contexto() as s:
        c = _leer_lote(s, execution_id)
        with serie_de_la_sesion(s):    # RF-013: lo que llegó en esta ejecución ya alimenta las variables
            # sin datos nuevos no se reprocesa: tampoco un ciclo intradía (sin ocupación nueva, su plan sería el mismo)
            if c.filas_validas == 0 and (not c.p.get("instante") or es_intradia(c.p)):
                _sin_datos_nuevos(s, c)
            else:
                _con_datos_nuevos(s, c)
            _cerrar_ciclo(s, c, t0)
    # RNF-005: el trabajo de una ruta no lo pide (lo pide su madre al cerrar la ejecución), ni el ciclo intradía
    if c.ruta is None and not es_intradia(c.p):
        _encolar_refresco_segmentos(c)


def _encolar_refresco_segmentos(c: _Ciclo) -> None:
    """§6.1, RNF-004: un ciclo que trajo datos nuevos deja en la cola el refresco de la agregación de segmentos (con la
    base operacional configurada y sin duplicar uno en cola). Va después de confirmar el ciclo: si falla, el ciclo
    sigue «ok» y el refresco programado lo recoge después."""
    _pedir_refresco_segmentos(c.execution_id, c.filas_validas)


def _pedir_refresco_segmentos(execution_id: uuid.UUID, filas_validas: int) -> None:
    """El pedido del refresco tras un ciclo confirmado: el de una ejecución sin partir o el de la madre de una partida
    por ruta (RNF-005), con las filas válidas de sus trabajos. Así se pide una sola vez por ejecución: cada refresco
    lee timbradas_segmentos en la base de Extreme, y la cola solo junta los pedidos que siguen en cola."""
    if not filas_validas:
        return
    try:
        from app.servicios import segmentos_refresco

        segmentos_refresco.encolar_tras_ciclo(execution_id)
    except Exception as exc:  # noqa: BLE001 - el refresco no es parte del resultado del ciclo
        log.warning("No se pudo encolar el refresco de segmentos tras %s: %s", execution_id, exc)


# ---------------------------------------------------------------- ejecución madre de una ejecución partida (RNF-005)
def _resumen_trabajo(t: Ejecucion) -> dict[str, Any]:
    """Una línea por trabajo de ruta en las métricas de la madre."""
    m = t.metricas or {}
    return {"execution_id": t.execution_id, "ruta": t.ruta, "estado": t.estado, "intentos": t.intentos,
            "filas_leidas": t.filas_leidas, "filas_validas": t.filas_validas, "predicciones": m.get("predicciones"),
            "recomendaciones": m.get("recomendaciones"),
            "recomendaciones_plan_dia": m.get("recomendaciones_plan_dia"), "alertas_nuevas": m.get("alertas_nuevas"),
            "marca_agua_anterior": t.marca_agua_anterior, "marca_agua_nueva": t.marca_agua_nueva,
            "iniciado_en": t.iniciado_en, "terminado_en": t.terminado_en, "worker_id": t.worker_id,
            "mensaje": t.mensaje}


def _datos_hasta_de(trabajos: list[Ejecucion]) -> date | None:
    """El último día de datos validados de los trabajos ok (el `hasta` del monitoreo de la ejecución)."""
    fechas = [date.fromisoformat(str((t.metricas or {})["datos_hasta"])[:10]) for t in trabajos
              if t.estado == "ok" and (t.metricas or {}).get("datos_hasta")]
    return max(fechas) if fechas else None


def _modelo_de_los_trabajos(s: Session, trabajos: list[Ejecucion], p: dict) -> str | None:
    """El modelo de la ejecución: el pedido, el que usaron sus trabajos (el más frecuente) o el activo."""
    usados = Counter(t.model_id for t in trabajos if t.estado == "ok" and t.model_id)
    if p.get("model_id"):
        return p["model_id"]
    if usados:
        return usados.most_common(1)[0][0]
    activo = modelo_activo(s)
    return activo.model_id if activo else None


def _cierre_del_modelo(s: Session, execution_id: uuid.UUID, trabajos: list[Ejecucion], model_id: str | None,
                       umbrales: dict, version_u: int | None, fallos: list[dict], *,
                       intradia: bool = False) -> dict[str, Any]:
    """Lo que en una ejecución sin partir hace su cierre y no es de una ruta, una vez para toda la ejecución: la fila
    de monitoreo (§9.4) hasta el último día de datos de sus trabajos, las predicciones del retador en sombra sobre las
    predicciones de los trabajos y la política (reversión, compuerta de sombra y reentreno; RF-018/RF-019). La madre
    de un ciclo intradía no monitorea ni aplica la política (NOTA_INTRADIA): solo cuenta las predicciones."""
    from app.servicios import monitoreo as _mon

    ids = [t.execution_id for t in trabajos]
    predicciones = (s.scalar(select(func.count()).select_from(Prediccion).where(Prediccion.execution_id.in_(ids)))
                    or 0) if ids else 0
    hasta = _datos_hasta_de(trabajos)
    tomar_candado_modelo(s)
    monitoreo = (_mon.en_ciclo(s, execution_id, model_id, None, umbrales, version_u, fallos, hasta=hasta)
                 if hasta is not None and model_id and not intradia else {})
    out: dict[str, Any] = {"predicciones": int(predicciones), "datos_hasta": hasta}
    if predicciones or monitoreo:
        out["monitoreo"] = _mon.cerrar_ciclo(s, execution_id, None, int(predicciones), monitoreo, umbrales,
                                             version_u, fallos, ejecuciones=ids, foto=False)
    return out


def _sumas_de_los_trabajos(trabajos: list[Ejecucion]) -> dict[str, int]:
    claves = ("recomendaciones", "recomendaciones_plan_dia", "alertas_nuevas", "alertas_repetidas")
    return {k: int(sum(int((t.metricas or {}).get(k) or 0) for t in trabajos)) for k in claves}


def _ciclo_de_la_madre(execution_id: uuid.UUID) -> int:
    """RNF-005: la madre de una ejecución partida corre cuando terminaron sus trabajos por ruta (la cola no la
    entrega antes) y cierra, una vez por ejecución y con el candado del modelo, lo que es del modelo. En sus métricas
    queda el resumen de cada trabajo (ruta, estado, réplica, filas, marcas de agua); su marca anterior y su marca nueva
    son la menor y la mayor de sus trabajos. Un trabajo en error no la detiene: queda contado en el mensaje. Devuelve
    las filas válidas de sus trabajos «ok» con las que _ciclo_frecuencia pide el refresco de segmentos (0 en un ciclo
    intradía, que no lo pide ni lee los consolidados: NOTA_INTRADIA)."""
    from app.servicios import cola

    t0 = time.perf_counter()
    with sesion_contexto() as s, serie_de_la_sesion(s):
        p = dict(s.get(Ejecucion, execution_id).parametros or {})
        intradia = es_intradia(p)
        trabajos = list(s.scalars(select(Ejecucion).where(Ejecucion.padre_id == execution_id)
                                  .order_by(Ejecucion.creado_en, Ejecucion.execution_id)).all())
        _avance(execution_id, 50, "cierre_modelo")
        version_u, umbrales = umbrales_de_la_ejecucion(s, p)    # la misma versión que usaron sus trabajos
        model_id = _modelo_de_los_trabajos(s, trabajos, p)
        fallos: list[dict] = []
        ok = [t for t in trabajos if t.estado == "ok"]
        metricas: dict[str, Any] = {"particion": PARTICION_RUTA, "trabajos": [_resumen_trabajo(t) for t in trabajos],
                                    "trabajos_ok": len(ok), "trabajos_error": len(trabajos) - len(ok),
                                    **_sumas_de_los_trabajos(ok),
                                    **_cierre_del_modelo(s, execution_id, trabajos, model_id, umbrales, version_u,
                                                         fallos, intradia=intradia)}
        if intradia:
            metricas["intradia"] = {"nota": NOTA_INTRADIA, "instante": p.get("instante")}
        else:    # los consolidados de Extreme, una vez por ejecución y con la versión de umbrales fijada al crearla
            consolidados_de_la_ejecucion(s, execution_id, umbrales, fallos, metricas)
        metricas.update(fallos=fallos, duracion_s=round(time.perf_counter() - t0, 3))
        cierre = _cierre_de_la_madre(trabajos, ok)
        cola.cerrar_ok(s, execution_id, dict(
            cierre, estado="ok", etapa="terminada", progreso=100, model_id=model_id,
            umbrales_version=version_u, metricas=json_seguro(metricas), terminado_en=ahora(),
            actualizado_en=ahora()))
    return 0 if intradia else int(cierre["filas_validas"])


def _cierre_de_la_madre(trabajos: list[Ejecucion], ok: list[Ejecucion]) -> dict[str, Any]:
    """Lo que la madre muestra de sus trabajos: la menor marca anterior y la mayor marca nueva (su corte), las filas
    de los trabajos «ok» (lo de un trabajo en error se revirtió y la ejecución siguiente lo vuelve a leer; su avance
    guardó filas_leidas, que no se suman), la versión de variables y cuántos trabajos terminaron en error."""
    anteriores = [t.marca_agua_anterior for t in ok if t.marca_agua_anterior is not None]
    nuevas = [t.marca_agua_nueva for t in ok if t.marca_agua_nueva is not None]
    en_error = len(trabajos) - len(ok)
    mensaje = (f"Terminada con {en_error} de {len(trabajos)} trabajos por ruta en error" if en_error
               else f"Terminada: {len(ok)} de {len(trabajos)} trabajos por ruta ok")
    return {"marca_agua_anterior": min(anteriores, default=None), "marca_agua_nueva": max(nuevas, default=None),
            "data_cutoff": max(nuevas, default=None), "filas_leidas": sum(t.filas_leidas or 0 for t in ok),
            "filas_validas": sum(t.filas_validas or 0 for t in ok), "mensaje": mensaje,
            "feature_version": next((t.feature_version for t in ok if t.feature_version), None)}


def _datos_para_canales(alerta: Alerta, escaladas: set | None) -> dict:
    """Los datos de la alerta que reciben los canales; si la alerta se escaló, lo dice el motivo de la notificación."""
    datos_alerta = json_seguro({c.key: getattr(alerta, c.key) for c in Alerta.__table__.columns})
    if escaladas and alerta.alert_id in escaladas:
        datos_alerta["motivo_notificacion"] = "escalamiento"
    return datos_alerta


def _estado_envio(registro: dict) -> str:
    """Estado del envío que informa el canal («simulado» si no lo informa)."""
    return str(registro.get("estado") or "simulado")


def _fila_notificacion(execution_id: uuid.UUID, alerta: Alerta, canal: Any, registro: dict) -> Notificacion:
    """La fila de Notificacion de un envío (o simulación) de la alerta por un canal, con lo que el canal informó."""
    return Notificacion(execution_id=execution_id, alert_id=alerta.alert_id,
                        canal=str(registro.get("canal") or type(canal).__name__),
                        destinatario=registro.get("destinatario") or ", ".join(
                            map(str, registro.get("destinatarios") or [])) or None,
                        asunto=registro.get("asunto"),
                        mensaje=registro.get("mensaje"), estado=_estado_envio(registro),
                        simulado=bool(registro.get("simulado", True)), detalle=json_seguro(registro))


def _notificar(s: Session, execution_id: uuid.UUID, nuevas: list[Alerta], fallos: list[dict],
               escaladas: set | None = None, por_estado: dict[str, int] | None = None) -> int:
    """Registros de notificación (uno por alerta y canal). `por_estado` cuenta simuladas, omitidas, etc."""
    try:
        from app.servicios import notificaciones
        canales = notificaciones.notificadores_desde_entorno()
    except Exception as exc:  # noqa: BLE001
        fallos.append({"etapa": "notificacion", "error": str(exc)})
        return 0
    enviadas = 0
    for alerta in nuevas:
        datos_alerta = _datos_para_canales(alerta, escaladas)
        for canal in canales:
            try:
                registro = canal.enviar(datos_alerta) or {}
            except Exception as exc:  # noqa: BLE001 - un canal caído no detiene la ejecución
                fallos.append({"etapa": "notificacion", "canal": type(canal).__name__, "error": str(exc)})
                continue
            s.add(_fila_notificacion(execution_id, alerta, canal, registro))
            enviadas += 1
            if por_estado is not None:
                estado = _estado_envio(registro)
                por_estado[estado] = por_estado.get(estado, 0) + 1
    return enviadas


def _ciclo_entrenamiento(execution_id: uuid.UUID) -> None:
    """RF-018: entrena un candidato con los datos validados hasta la fecha pedida y lo registra como candidato.

    La serie es el histórico VALIDADO (demanda_observada sobre la serie empaquetada, truncada en
    datos_hasta si viene); el id nunca pisa al activo y el candidato queda en sombra (app/servicios/politica.py).
    """
    from app.servicios import politica

    with sesion_contexto() as s:
        p = dict(s.get(Ejecucion, execution_id).parametros or {})
    _avance(execution_id, 20, "entrenamiento")
    info = politica.entrenar_candidato(p)
    _avance(execution_id, 80, "registro")
    with sesion_contexto() as s:
        from app.servicios import cola

        registro = registrar_modelo(s, info, estado="candidato", execution_id=execution_id)
        _, umbrales = umbrales_vigentes(s)
        politica.iniciar_sombra(registro, info, umbrales)
        cola.cerrar_ok(s, execution_id, dict(
            estado="ok", etapa="terminada", progreso=100, model_id=registro.model_id,
            feature_version=registro.feature_version, data_cutoff=registro.data_cutoff,
            metricas=json_seguro({"modelo": info.get("metricas"), "sha256": info.get("sha256"),
                                  "artefacto": info.get("artefacto"), "serie": info.get("serie"),
                                  "sombra": (registro.metricas or {}).get("sombra")}),
            mensaje=f"Candidato {registro.model_id} registrado", terminado_en=ahora(), actualizado_en=ahora()))


def _ciclo_respuesta(execution_id: uuid.UUID) -> None:
    """C3: la foto de la respuesta del reto como trabajo de la cola (§7.1 procesos largos asíncronos). Parámetros
    {fecha, rutas}; respuesta.precalcular la guarda en respuesta_reto y el cierre «ok» va en la misma transacción.
    RNF-006: corre dentro del span «ejecucion.ciclo_respuesta», que continúa la traza de quien la encoló."""
    try:
        from app.observabilidad import ejecucion_en_curso
    except ImportError:  # pragma: no cover - sin observabilidad corre igual
        ejecucion_en_curso = None
    from app.servicios import respuesta

    with ejecucion_en_curso(execution_id, "respuesta") if ejecucion_en_curso else nullcontext():
        try:
            _foto_de_la_respuesta_en_cola(execution_id)
        except (respuesta.SinDatos, ValueError) as exc:
            # un día sin variables o una ruta inválida no mejoran con un reintento: falla definitiva con su motivo
            raise ErrorNoReintentable(str(exc)) from exc


def _plan_de_la_respuesta(s: Session, execution_id: uuid.UUID, fecha: date, version_u: int | None,
                          planes: dict[str, dict]) -> dict:
    """D4 también desde la cola: las filas origen='plan_dia' de los mismos planes que usó la foto, cada ruta en su
    punto de guardado, para que GET /recommendations/plan responda después de POST /respuesta/calcular."""
    resumen: dict[str, Any] = {"fecha": fecha.isoformat(), "rutas": {}, "advertencias": []}
    for ruta, plan in planes.items():
        try:
            with s.begin_nested():
                resumen["rutas"][ruta] = persistir_plan_dia(s, execution_id, version_u, ruta, fecha, plan)
        except Exception as exc:  # noqa: BLE001 - sin las filas del plan la foto de la respuesta sigue valiendo
            log.warning("plan del día de %s (trabajo respuesta): %s", ruta, exc)
            resumen["advertencias"].append({"etapa": "plan_dia", "ruta": ruta, "error": str(exc)})
    return resumen


def _foto_de_la_respuesta_en_cola(execution_id: uuid.UUID) -> None:
    from app.servicios import cola, respuesta

    t0 = time.perf_counter()
    with sesion_contexto() as s:
        p = dict(s.get(Ejecucion, execution_id).parametros or {})
    _avance(execution_id, 20, "respuesta")
    fecha = date.fromisoformat(str(p["fecha"])[:10]) if p.get("fecha") else None
    with sesion_contexto() as s, serie_de_la_sesion(s):
        planes: dict[str, dict] = {}
        with s.begin_nested():
            r = respuesta.precalcular(s, fecha, p.get("rutas") or None, execution_id=execution_id, planes=planes)
        traz = r.get("trazabilidad") or {}
        plan = _plan_de_la_respuesta(s, execution_id, date.fromisoformat(str(r["fecha"])),
                                     traz.get("umbrales_version"), planes)
        cola.cerrar_ok(s, execution_id, dict(
            estado="ok", etapa="terminada", progreso=100, model_id=traz.get("model_id"),
            umbrales_version=traz.get("umbrales_version"),
            metricas=json_seguro({"fecha": r.get("fecha"), "guardadas": r.get("guardadas"),
                                  "rutas": [b.get("ruta") for b in r.get("rutas") or []],
                                  "fuente_pronostico": traz.get("fuente_pronostico"),
                                  "calibracion_version": traz.get("calibracion_version"),
                                  "plan_dia": plan, "recomendaciones_plan_dia": sum(plan["rutas"].values()),
                                  "duracion_s": round(time.perf_counter() - t0, 3)}),
            mensaje=f"Respuesta del {r.get('fecha')} calculada ({r.get('guardadas')} rutas)",
            terminado_en=ahora(), actualizado_en=ahora()))
