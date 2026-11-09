"""Orquestación de una ejecución (RF-013, RNF-001, RNF-004, RNF-011).

Ciclo: lectura incremental por marca de agua -> calidad con los catálogos de la fuente (errores por lote, llave,
valor y causa) -> histórico propio sin duplicados -> evaluación del error del modelo activo sobre lo recién llegado ->
predicciones 30/60/120 por ruta -> recomendaciones -> alertas deduplicadas y escaladas -> notificaciones simuladas ->
plan del día siguiente por ruta y hora (recomendaciones origen='plan_dia') y foto de la respuesta del reto.
Cada fila de resultados guarda las dimensiones de §8.3 (app/servicios/dimensiones.py).

Los resultados de un intento se escriben en UNA transacción: si el intento falla no quedan resultados parciales y el
reintento parte limpio. El progreso se guarda aparte (transacciones cortas) para poder consultarlo mientras corre.
Todo queda ligado a execution_id, model_id, feature_version, versión de umbrales y data_cutoff.
"""
from __future__ import annotations

import copy
import logging
import math
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
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import obtener_ajustes
from app.db import sesion_contexto
from app.modelos_db import (
    Alerta,
    Ejecucion,
    ErrorCalidad,
    HistorialAlerta,
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


class ErrorNoReintentable(Exception):
    """Falla de configuración o de datos que no se arregla reintentando."""


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


def nueva_version_umbrales(sesion: Session, valores: dict[str, Any], creado_por: str, motivo: str | None) -> int:
    """Cada cambio crea una versión nueva del conjunto completo; la anterior queda como histórico."""
    from app.servicios.optimizacion import PARAMETROS_OBJETIVO, validar_parametros_objetivo

    filas = sesion.scalars(select(Umbral).where(Umbral.vigente)).all()
    actuales = {f.nombre: f for f in filas}
    # §10.2: los pesos y costos de la función objetivo también se versionan aquí (si no están, rige el código)
    validos = set(actuales) | set(PARAMETROS_OBJETIVO)
    desconocidos = sorted(set(valores) - validos)
    if desconocidos:
        raise ValueError(f"Parámetros desconocidos: {', '.join(desconocidos)}. Válidos: {', '.join(sorted(validos))}")
    combinados = {n: f.valor for n, f in actuales.items()} | valores
    validar_parametros_objetivo(combinados)
    for nombre, valor in valores.items():
        if _num(valor) is None or float(valor) < 0:
            raise ValueError(f"El parámetro {nombre} debe ser un número no negativo")
    for nombre in ("ocupacion_objetivo_min", "ocupacion_objetivo_max", "ocupacion_critica", "baja_utilizacion",
                   "error_pronostico", "caida_demanda", "tolerancia_salidas", "wape_max"):
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
        descripcion = actuales[nombre].descripcion if nombre in actuales else PARAMETROS_OBJETIVO[nombre][1]
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


ETAPAS = Histogram("api_ejecucion_etapa_segundos", "Duración de cada etapa de una ejecución (lectura_incremental, "
                   "calidad, prediccion, alertas, notificaciones, plan_dia, entrenamiento, registro, respuesta)",
                   ["etapa"], buckets=(0.1, 0.5, 1, 2.5, 5, 10, 30, 60, 120, 300, 600, 1800))
_etapas_en_curso: dict[uuid.UUID, tuple[str, float]] = {}
_etapas_candado = threading.Lock()


def _medir_etapa(execution_id: uuid.UUID, etapa: str | None) -> None:
    """Cierra la etapa anterior de la ejecución en la métrica ETAPAS y abre la nueva (None = la ejecución terminó)."""
    instante = time.perf_counter()
    with _etapas_candado:
        previa = _etapas_en_curso.pop(execution_id, None)
        if etapa is not None:
            _etapas_en_curso[execution_id] = (etapa, instante)
    if previa is not None:
        ETAPAS.labels(previa[0]).observe(instante - previa[1])


def cerrar_etapa(execution_id: uuid.UUID) -> None:
    """La cola lo llama al terminar cada intento: la última etapa queda medida."""
    _medir_etapa(execution_id, None)


def _avance(execution_id: uuid.UUID, progreso: float, etapa: str, **campos: Any) -> None:
    _medir_etapa(execution_id, etapa)
    with sesion_contexto() as s:
        s.execute(update(Ejecucion).where(Ejecucion.execution_id == execution_id)
                  .values(progreso=progreso, etapa=etapa, actualizado_en=ahora(), **campos))


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


def ejecutar(execution_id: uuid.UUID) -> None:
    """Despacha una ejecución ya encolada (cola en PostgreSQL, app/servicios/cola.py).

    Con trabajadores en este proceso (TRABAJADORES ≥ 1), la toma cualquiera de las réplicas desde la cola. Sin
    trabajadores (TRABAJADORES=0 o REANUDAR_EJECUCIONES=false, como en las pruebas), se procesa aquí mismo con el
    mismo protocolo de reserva, reintentos con espera y cierre con cerca.
    """
    from app.servicios import cola

    if obtener_ajustes().trabajadores_efectivos > 0:
        return
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


def _actualizar_episodio(s: Session, abierta: Alerta, a: dict, execution_id: uuid.UUID | None,
                         umbrales_version: int | None) -> None:
    """Un episodio observado que continúa: la alerta abierta toma la ventana y los valores nuevos y la
    bitácora guarda lo anterior (historial completo, sin duplicar la alerta)."""
    fin_nuevo = a_instante(a.get("ventana_fin"))
    if abierta.origen not in ("observado", "calidad_datos") or fin_nuevo is None or (
            abierta.ventana_fin and fin_nuevo <= abierta.ventana_fin and _num(a.get("observado")) == abierta.observado):
        return
    antes = {"ventana_fin": json_seguro(abierta.ventana_fin and abierta.ventana_fin.astimezone(ZONA)),
             "observado": abierta.observado,
             "esperado": abierta.esperado, "umbral": abierta.umbral, "tendencia": abierta.tendencia}
    abierta.ventana_fin = max(fin_nuevo, abierta.ventana_fin or fin_nuevo)
    for campo in ("observado", "esperado", "umbral", "puntaje", "probabilidad", "tendencia_pendiente"):
        setattr(abierta, campo, _num(a.get(campo)))
    abierta.tendencia = a.get("tendencia")
    abierta.explicacion = a.get("explicacion")
    abierta.serie_reciente = json_seguro(a.get("serie_reciente") or [])
    abierta.variables_influyentes = json_seguro(a.get("variables_influyentes") or [])
    abierta.variables = json_seguro(a.get("variables") or {}) | {"umbrales_version": umbrales_version}
    despues = {"ventana_fin": json_seguro(abierta.ventana_fin.astimezone(ZONA)), "observado": abierta.observado,
               "esperado": abierta.esperado, "umbral": abierta.umbral, "tendencia": abierta.tendencia}
    s.add(HistorialAlerta(alert_id=abierta.alert_id, accion="redeteccion", estado_anterior=abierta.estado,
                          estado_nuevo=abierta.estado, usuario="sistema",
                          comentario=f"El episodio continúa (ejecución {execution_id})",
                          detalle={"execution_id": json_seguro(execution_id), "antes": antes, "despues": despues}))


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


def _festivos() -> set[date]:
    from app.servicios import datos

    try:
        c = datos.contexto_operacional()
        return {_a_fecha(f) for f in c.loc[c["festivo_oficial"] == 1, "fecha"].unique()}
    except Exception:  # noqa: BLE001
        return set()


def contexto_observado(s: Session, ruta: str, validos, campos_faltantes: list[str] | None, model_id: str | None,
                       referencia: datetime, umbrales: dict, *, fuente: Any = None, festivos: set | None = None,
                       fallos: list | None = None) -> dict:
    """Contexto de evaluar_observadas() para una ruta con lo que trajo la ejecución:

    - horas: las horas cerradas del último día recibido de la ruta (histórico propio, ya con el lote), cada una con
      el pronóstico del modelo para esa hora y su banda P10-P90 calibrada (inferencia.predecir sin factor intradía:
      el patrón del modelo, no la regla b8), salidas observadas frente a 60 / intervalo programado y nueva = llegó
      en esta ejecución;
    - consolidado: subidas y número de viajes del último día completo frente al mismo tipo de día de las
      semanas_referencia previas (z robusto);
    - datos: minutos desde la última llegada frente a la referencia temporal, campos obligatorios faltantes (calidad)
      y horas de servicio sin registro;
    - tolerancia_tiempo_min (Procesos.toleranciatiempo) y ubicacion del despacho cuando la fuente los expone.
    """
    from app.modelos_db import DemandaObservada
    from app.servicios import datos

    fallos = fallos if fallos is not None else []
    festivos = festivos if festivos is not None else _festivos()
    ctx: dict[str, Any] = {"ruta": ruta, "empresa": empresa_de(ruta), "detectada_en": ahora(),
                           "tolerancia_tiempo_min": tolerancia_proceso(fuente),
                           "ubicacion": ubicacion_despacho(fuente, ruta)}
    nuevas = _horas_nuevas(validos, ruta)
    fecha = max((f for f, _ in nuevas), default=None)
    ctx["datos"] = _datos_de_llegada(s, ruta, referencia, campos_faltantes, fecha)
    if fecha is None:
        return ctx

    filas = s.execute(select(DemandaObservada.hora, DemandaObservada.pasajeros, DemandaObservada.salidas)
                      .where(DemandaObservada.ruta == ruta, DemandaObservada.fecha == fecha)
                      .order_by(DemandaObservada.hora)).all()
    presentes = {int(h) for h, _, _ in filas}
    ultima_hora = max(presentes, default=-1)
    ctx["datos"]["horas_faltantes"] = [datetime.combine(fecha, dtime(h), tzinfo=ZONA).isoformat()
                                       for h in datos.HORAS_SERVICIO if h <= ultima_hora and h not in presentes]
    td = datos.tipo_dia_de(fecha, fecha in festivos)
    intervalos = _intervalos_del_tipo_de_dia(ruta, td, fallos)
    servicio = [(int(h), pas, sal) for h, pas, sal in filas if int(h) in datos.HORAS_SERVICIO]
    pronosticos = _pronosticos_de_las_horas(ruta, fecha, [h for h, _, _ in servicio], model_id, fallos)
    ctx["horas"] = [_contexto_hora_observada(ruta, fecha, hora, pasajeros, salidas, nuevas, intervalos,
                                             model_id, fallos, pronostico=pronosticos.get(hora))
                    for hora, pasajeros, salidas in servicio]
    # RF-009 «rupturas de comportamiento»: serie diaria real frente al pronóstico del modelo (CUSUM de alertas.py)
    ctx["serie_diaria"] = serie_diaria_memorizada(s, ruta, fecha, model_id, {f for f, _ in nuevas}, fallos)

    # consolidado del último día completo de la ruta frente al mismo tipo de día de las semanas previas
    completos = _dias_completos(nuevas)
    consolidado = _consolidado_del_dia(s, ruta, completos[-1], td, umbrales, festivos) if completos else None
    if consolidado is not None:
        ctx["consolidado"] = consolidado
    return ctx


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


def _dias_completos(nuevas: set[tuple[date, int]]) -> list[date]:
    """Días del lote con todas las horas de servicio, en orden. Cuenta las horas por día en una pasada (lineal en el
    tamaño del lote: la carga inicial trae decenas de miles de horas)."""
    from app.servicios import datos

    por_dia = Counter(f for f, h in nuevas if h in datos.HORAS_SERVICIO)
    return sorted(f for f, n in por_dia.items() if n >= len(datos.HORAS_SERVICIO))


def _consolidado_del_dia(s: Session, ruta: str, dia: date, td: int, umbrales: dict, festivos: set) -> dict | None:
    """Subidas y número de viajes del día frente al mismo tipo de día de las semanas_referencia previas."""
    from app.modelos_db import DemandaObservada
    from app.servicios import datos

    semanas = int(float(umbrales.get("semanas_referencia", 8)))
    diarios = s.execute(select(DemandaObservada.fecha, func.sum(DemandaObservada.pasajeros),
                               func.sum(DemandaObservada.salidas), func.count())
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
        "subidas": _num(del_dia[0][1]), "nro_viajes": _num(del_dia[0][2]),
        "referencia_valores": {"subidas": [_num(x[1]) for x in ref], "nro_viajes": [_num(x[2]) for x in ref]},
        "serie": [_num(x[1]) for x in ref[-6:]] + [_num(del_dia[0][1])],
        "serie_detalle": [{"fecha": str(x[0]), "subidas": _num(x[1]), "nro_viajes": _num(x[2])}
                          for x in ref[-6:] + del_dia],
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


def alertas_observadas(s: Session, rutas: list[str], df, validos, errores: list[dict], model_id: str | None,
                       umbrales_alertas: dict, referencia: datetime, fuente: Any, execution_id: uuid.UUID,
                       version_u: int | None, fallos: list[dict]) -> tuple[list[Alerta], int, dict]:
    """Evalúa ALT-005..ALT-009 con lo observado de cada ruta y las guarda deduplicadas (episodios)."""
    from app.servicios import alertas as reglas

    nuevas: list[Alerta] = []
    repetidas = 0
    resumen: dict[str, Any] = {"por_codigo": {}, "horas_evaluadas": 0,
                               "referencia": referencia.astimezone(ZONA).isoformat()}
    faltantes = _faltantes_por_ruta(df, errores)
    festivos = _festivos()
    for ruta in rutas:
        try:
            ctx = contexto_observado(s, ruta, validos, sorted(faltantes.get(ruta, set()) | faltantes.get(None, set())),
                                     model_id, referencia, umbrales_alertas, fuente=fuente, festivos=festivos,
                                     fallos=fallos)
            resumen["horas_evaluadas"] += sum(1 for h in ctx.get("horas") or [] if h.get("nueva"))
            for a in reglas.evaluar_observadas(ctx, umbrales_alertas):
                registro, es_nueva = guardar_alerta(s, a, execution_id, version_u)
                resumen["por_codigo"][a["codigo"]] = resumen["por_codigo"].get(a["codigo"], 0) + 1
                if es_nueva:
                    nuevas.append(registro)
                else:
                    repetidas += 1
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

    @property
    def horizontes(self):
        return self.p.get("horizontes") or HORIZONTES


class _RecomendacionesDeLaEjecucion:
    """Una recomendación de §10.2 por ruta y franja dentro de una ejecución.

    Los horizontes 30/60/120 de una ruta suelen caer en la misma hora principal, con la misma demanda por hora y la
    misma banda: optimizacion.recomendacion_franja da entonces el mismo resultado y se resuelve una sola vez. Cada
    horizonte recibe su propia copia (y su propia franja_prediccion). Un error no se guarda: se repite en cada
    horizonte, igual que sin esta memoria."""

    def __init__(self, umbrales: dict, version_u: int | None):
        self.umbrales = umbrales
        self.version_u = version_u
        self._resueltas: dict[tuple, tuple[dict, dict]] = {}

    def de_la_franja(self, info: dict, ruta: str, franja: dict) -> tuple[dict, dict]:
        from app.servicios import optimizacion

        clave = (ruta, franja["fecha"], franja["hora"], franja["demanda_hora"], franja["p90_hora"], franja["p10_hora"])
        if clave not in self._resueltas:
            self._resueltas[clave] = optimizacion.recomendacion_franja(
                dict(info, ruta=ruta), self.umbrales, self.version_u, hora=franja["hora"], fecha=franja["fecha"],
                demanda_hora=franja["demanda_hora"], demanda_p90=franja["p90_hora"], demanda_p10=franja["p10_hora"])
        rec_d, entradas = self._resueltas[clave]
        return copy.deepcopy(rec_d), copy.deepcopy(entradas)


def _leer_lote(s: Session, execution_id: uuid.UUID) -> _Ciclo:
    """Lectura incremental desde la marca de agua, calidad (errores por lote, fila y causa) e histórico propio sin
    duplicados; luego los umbrales vigentes y el modelo con el que se pronostica."""
    from app.servicios import calidad
    from app.servicios import fuentes as _fuentes

    e = s.get(Ejecucion, execution_id)
    p = dict(e.parametros or {})
    hasta = date.fromisoformat(p["hasta"]) if p.get("hasta") else None
    marca_anterior = ultima_marca_agua(s)
    _avance(execution_id, 10, "lectura_incremental", marca_agua_anterior=marca_anterior)
    fuente = obtener_fuente()
    df, nueva_marca = _fuentes.leer_con_estado(fuente, marca_anterior, hasta, estado_fuente_anterior(s))
    filas_leidas = 0 if df is None else len(df)
    lote = f"{execution_id.hex[:8]}:{p.get('hasta') or 'todo'}"
    _avance(execution_id, 25, "calidad", filas_leidas=filas_leidas)
    validos, errores = (calidad.validar_lote(df, lote, catalogos=catalogos_calidad(fuente), ahora=ahora())
                        if filas_leidas else (df, []))
    resumen_dq = _guardar_errores(s, execution_id, lote, errores)
    filas_validas = 0 if validos is None else len(validos)
    incorporadas = _incorporar_historico(s, validos, execution_id)
    version_u, umbrales = umbrales_vigentes(s)
    activo = modelo_activo(s)
    metricas: dict[str, Any] = {"lote": lote, "errores_calidad": resumen_dq, "incorporadas_historico": incorporadas}
    if filas_leidas and getattr(calidad, "resumen", None) is not None:
        try:   # §6.3: conteos por dimensión y código, filas en cuarentena y latencia media del lote
            metricas["calidad"] = json_seguro(calidad.resumen(df, errores))
        except Exception as exc:  # noqa: BLE001 - el resumen es informativo
            metricas["calidad"] = {"error": str(exc)}
    if getattr(fuente, "resumen_lectura", None) is not None:   # leídas, tardías, modificadas y repetidas
        metricas["lectura"] = fuente.resumen_lectura
        metricas["fuente_estado"] = fuente.estado_incremental
    return _Ciclo(execution_id=execution_id, p=p, fuente=fuente, df=df, validos=validos, errores=errores,
                  marca_anterior=marca_anterior, marca_nueva=a_instante(nueva_marca) or marca_anterior,
                  filas_leidas=filas_leidas, filas_validas=filas_validas, version_u=version_u, umbrales=umbrales,
                  model_id=p.get("model_id") or (activo.model_id if activo else None), metricas=metricas)


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
    try:
        ev = inferencia.evaluar(c.model_id, min(c.validos["fecha"]), max(c.validos["fecha"]))
        c.metricas["evaluacion_error"] = json_seguro(ev)
        for nombre_ruta, m in (ev.get("por_ruta") or {}).items():
            w = _num((m or {}).get("wape"))
            if w is not None:
                wape_por_ruta[nombre_ruta] = w / 100.0 if w > 1.5 else w
    except Exception as exc:  # noqa: BLE001
        c.fallos.append({"etapa": "evaluacion", "error": str(exc)})
    return wape_por_ruta


def _monitorear(s: Session, c: _Ciclo, wape_por_ruta: dict[str, float]) -> None:
    """Monitoreo de §9.4: ALT-010 usa el WAPE MÓVIL por ruta; también monitorea al retador."""
    from app.servicios import monitoreo as _monitoreo

    c.monitoreo = _monitoreo.en_ciclo(s, c.execution_id, c.model_id, c.validos, c.umbrales, c.version_u, c.fallos)
    wape_por_ruta.update({r: w for r, w in (c.monitoreo.get("wape_por_ruta") or {}).items() if w is not None})


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


def _con_datos_nuevos(s: Session, c: _Ciclo) -> None:
    """Con datos nuevos: error del modelo, monitoreo, predicciones 30/60/120 por ruta con su recomendación, alertas
    deduplicadas (de pronóstico y observadas) y notificaciones."""
    from app.servicios import datos

    wape_por_ruta = _evaluar_error(c)
    _monitorear(s, c, wape_por_ruta)
    _avance(c.execution_id, 45, "prediccion")

    instante = _instante_por_defecto(c.p, c.validos, c.marca_nueva)
    catalogo = {r["ruta"]: r for r in datos.catalogo_rutas()}
    rutas = c.p.get("rutas") or list(catalogo)
    recomendador = _RecomendacionesDeLaEjecucion(c.umbrales, c.version_u)
    contextos: list[dict] = []
    for ruta in rutas:
        for h in c.horizontes:
            _pronostico_y_recomendacion(s, c, ruta, catalogo.get(ruta, {}), h, instante, wape_por_ruta, recomendador,
                                        contextos)
    _avance(c.execution_id, 70, "alertas")

    umbrales_alertas = dict(c.umbrales) | {"version": c.version_u}
    _alertas_de_pronostico(s, c, contextos, umbrales_alertas)
    # ALT-005..ALT-009 con los datos OBSERVADOS de la ejecución (RF-009)
    obs_nuevas, obs_repetidas, c.metricas["alertas_observadas"] = alertas_observadas(
        s, rutas, c.df, c.validos, c.errores, c.model_id, umbrales_alertas, referencia_temporal(c.p, instante),
        c.fuente, c.execution_id, c.version_u, c.fallos)
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
            "formula": FORMULA_PLAN, "hora_plan": h}


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
                "salidas_dia": plan.get("salidas_dia"), "vehiculos_hora_pico": plan.get("vehiculos_hora_pico")}
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
                plan = calcular(fecha, ruta, umbrales=c.umbrales, umbrales_version=c.version_u, model_id=c.model_id)
                n = guardar_plan_dia(s, c, ruta, fecha, plan)
            planes[ruta] = plan
            c.recomendaciones_plan += n
            resumen["rutas"][ruta] = {"horas": n, "model_id": plan.get("model_id"),
                                      "calibracion_version": plan.get("calibracion_version"),
                                      "fuente_pronostico": plan.get("fuente_pronostico"),
                                      "salidas_dia": plan.get("salidas_dia")}
        except Exception as exc:  # noqa: BLE001 - una ruta sin plan no detiene el cierre
            log.warning("plan del día de %s: %s", ruta, exc)
            resumen["advertencias"].append({"etapa": "plan_dia", "ruta": ruta, "error": str(exc)})
    resumen["duracion_s"] = round(time.perf_counter() - t0, 3)
    _foto_respuesta(s, c, fecha, rutas, planes)


def _foto_respuesta(s: Session, c: _Ciclo, fecha: date, rutas: list[str],
                    planes: dict[str, dict] | None = None) -> None:
    """C2: respuesta.precalcular en un punto de guardado; un fallo queda como advertencia en métricas. Recibe los
    planes que el ciclo acaba de calcular y persistir: la foto los usa tal cual (no vuelve a resolver el MILP), así
    que GET /respuesta y GET /recommendations/plan dicen lo mismo hora por hora."""
    t0 = time.perf_counter()
    planes = dict(planes or {})
    reutilizados = sorted(planes)
    try:
        from app.servicios import respuesta

        with s.begin_nested():
            r = respuesta.precalcular(s, fecha, list(rutas), execution_id=c.execution_id, planes=planes)
        traz = r.get("trazabilidad") or {}
        c.metricas["respuesta"] = {"fecha": r.get("fecha"), "guardadas": r.get("guardadas"),
                                   "model_id": traz.get("model_id"), "umbrales_version": traz.get("umbrales_version"),
                                   "fuente_pronostico": traz.get("fuente_pronostico"),
                                   "planes_reutilizados": reutilizados,
                                   "duracion_s": round(time.perf_counter() - t0, 3)}
    except Exception as exc:  # noqa: BLE001 - sin la foto, GET /respuesta responde 404 «sin_calcular»
        log.warning("foto de la respuesta del %s: %s", fecha, exc)
        c.metricas["respuesta"] = {"fecha": fecha.isoformat(), "advertencia": str(exc),
                                   "duracion_s": round(time.perf_counter() - t0, 3)}


def _cerrar_ciclo(s: Session, c: _Ciclo, t0: float) -> None:
    """Foto de variables (§11.2), sombra y política (RF-018/RF-019), métricas y cierre con cerca: el «ok» final pasa por
    cola.cerrar_ok en la MISMA transacción que los resultados, y solo si la reserva sigue siendo de este trabajador."""
    from app.servicios import cola

    if c.predicciones or c.monitoreo:
        from app.servicios import monitoreo as _mon

        c.metricas["monitoreo"] = _mon.cerrar_ciclo(s, c.execution_id, c.marca_nueva, c.predicciones, c.monitoreo,
                                                    c.umbrales, c.version_u, c.fallos)
    c.metricas.update({
        "predicciones": c.predicciones, "recomendaciones": c.recomendaciones,
        "recomendaciones_plan_dia": c.recomendaciones_plan, "alertas_nuevas": len(c.nuevas_alertas),
        "alertas_repetidas": c.repetidas, "fallos": c.fallos, "duracion_s": round(time.perf_counter() - t0, 3)})
    feature_version = None
    if c.predicciones:
        feature_version = s.scalar(select(Prediccion.feature_version)
                                   .where(Prediccion.execution_id == c.execution_id).limit(1))
    cola.cerrar_ok(s, c.execution_id, dict(
        estado="ok", etapa="terminada", progreso=100, marca_agua_anterior=c.marca_anterior,
        marca_agua_nueva=c.marca_nueva, data_cutoff=c.marca_nueva, filas_leidas=c.filas_leidas,
        filas_validas=c.filas_validas, model_id=c.model_id, feature_version=feature_version,
        umbrales_version=c.version_u, metricas=json_seguro(c.metricas),
        mensaje="Terminada" if not c.fallos else f"Terminada con {len(c.fallos)} fallos parciales",
        terminado_en=ahora(), actualizado_en=ahora()))


def _ciclo_frecuencia(execution_id: uuid.UUID) -> None:
    """Ciclo diario de §14.2. Los resultados del intento se escriben en una sola sesión y transacción, que el cierre
    confirma con cola.cerrar_ok (si el intento falla, no quedan resultados parciales)."""
    t0 = time.perf_counter()
    with sesion_contexto() as s:
        c = _leer_lote(s, execution_id)
        with serie_de_la_sesion(s):    # RF-013: lo que llegó en esta ejecución ya alimenta las variables
            if c.filas_validas == 0 and not c.p.get("instante"):
                _sin_datos_nuevos(s, c)
            else:
                _con_datos_nuevos(s, c)
            _cerrar_ciclo(s, c, t0)


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
