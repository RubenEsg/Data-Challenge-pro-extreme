"""Orquestación de una ejecución (RF-013, RNF-001, RNF-004, RNF-011).

Ciclo: lectura incremental por marca de agua -> calidad (errores por lote, fila y causa) -> histórico propio sin
duplicados -> evaluación del error del modelo activo sobre lo recién llegado -> predicciones 30/60/120 por ruta ->
recomendaciones -> alertas deduplicadas -> notificaciones simuladas.

Los resultados de un intento se escriben en UNA transacción: si el intento falla no quedan resultados parciales y el
reintento parte limpio. El progreso se guarda aparte (transacciones cortas) para poder consultarlo mientras corre.
Todo queda ligado a execution_id, model_id, feature_version, versión de umbrales y data_cutoff.
"""
from __future__ import annotations

import logging
import math
import time
import uuid
from datetime import UTC, date, datetime, timedelta
from datetime import time as dtime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import obtener_ajustes
from app.db import sesion_contexto
from app.modelos_db import (
    Alerta,
    DemandaObservada,
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


# ---------------------------------------------------------------- umbrales (§5.1, regla de gobierno)
def umbrales_vigentes(sesion: Session) -> tuple[int, dict[str, Any]]:
    filas = sesion.scalars(select(Umbral).where(Umbral.vigente)).all()
    version = max((f.version for f in filas), default=0)
    return version, {f.nombre: f.valor for f in filas}


def nueva_version_umbrales(sesion: Session, valores: dict[str, Any], creado_por: str, motivo: str | None) -> int:
    """Cada cambio crea una versión nueva del conjunto completo; la anterior queda como histórico."""
    filas = sesion.scalars(select(Umbral).where(Umbral.vigente)).all()
    actuales = {f.nombre: f for f in filas}
    desconocidos = sorted(set(valores) - set(actuales))
    if desconocidos:
        raise ValueError(f"Parámetros desconocidos: {', '.join(desconocidos)}. Válidos: {', '.join(sorted(actuales))}")
    combinados = {n: f.valor for n, f in actuales.items()} | valores
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
        sesion.add(Umbral(nombre=nombre, valor=valor, descripcion=actuales[nombre].descripcion, version=nueva,
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
def crear_ejecucion(sesion: Session, tipo: str, parametros: dict, correlation_id: str | None) -> Ejecucion:
    e = Ejecucion(execution_id=uuid.uuid4(), tipo=tipo, estado="en_cola", progreso=0, intentos=0,
                  parametros=json_seguro(parametros), metricas={}, correlation_id=correlation_id, mensaje="En cola")
    sesion.add(e)
    sesion.commit()
    return e


def _avance(execution_id: uuid.UUID, progreso: float, etapa: str, **campos: Any) -> None:
    with sesion_contexto() as s:
        s.execute(update(Ejecucion).where(Ejecucion.execution_id == execution_id)
                  .values(progreso=progreso, etapa=etapa, actualizado_en=ahora(), **campos))


def ultima_marca_agua(sesion: Session) -> datetime | None:
    return sesion.scalar(select(func.max(Ejecucion.marca_agua_nueva))
                         .where(Ejecucion.tipo == "frecuencia", Ejecucion.estado == "ok"))


def obtener_fuente():
    """Fuente de las tablas operacionales según FUENTE (parquet por defecto; postgres = solo lectura)."""
    from app.servicios import fuentes

    aj = obtener_ajustes()
    if aj.fuente == "postgres":
        if not aj.fuente_database_url:
            raise ErrorNoReintentable("FUENTE=postgres requiere la variable FUENTE_DATABASE_URL")
        return fuentes.FuentePostgresSoloLectura(url=aj.fuente_database_url,
                                                 statement_timeout_ms=aj.fuente_statement_timeout_ms)
    if aj.fuente != "parquet":
        raise ErrorNoReintentable(f"FUENTE desconocida: {aj.fuente!r} (use parquet o postgres)")
    return fuentes.FuenteParquet()


def recuperar_interrumpidas() -> list[uuid.UUID]:
    """RNF-001: al arrancar, las ejecuciones que quedaron «corriendo» vuelven a la cola para reintentarse."""
    with sesion_contexto() as s:
        ids = list(s.scalars(select(Ejecucion.execution_id).where(Ejecucion.estado.in_(("corriendo", "en_cola")))))
        if ids:
            s.execute(update(Ejecucion).where(Ejecucion.execution_id.in_(ids)).values(
                estado="en_cola", mensaje="Reencolada al reiniciar el servicio (RNF-001)", actualizado_en=ahora()))
    return ids


def ejecutar(execution_id: uuid.UUID) -> None:
    """Corre una ejecución con reintentos controlados (backoff exponencial corto)."""
    aj = obtener_ajustes()
    for intento in range(1, max(1, aj.max_reintentos) + 1):
        with sesion_contexto() as s:
            e = s.get(Ejecucion, execution_id)
            if e is None:
                return
            tipo = e.tipo
            s.execute(update(Ejecucion).where(Ejecucion.execution_id == execution_id).values(
                estado="corriendo", intentos=Ejecucion.intentos + 1, iniciado_en=func.coalesce(
                    Ejecucion.iniciado_en, ahora()), mensaje=f"Intento {intento}", actualizado_en=ahora()))
        try:
            if tipo == "entrenamiento":
                _ciclo_entrenamiento(execution_id)
            else:
                _ciclo_frecuencia(execution_id)
            return
        except Exception as exc:  # noqa: BLE001 - se registra y se reintenta
            definitiva = isinstance(exc, ErrorNoReintentable) or intento >= aj.max_reintentos
            log.exception("Fallo en la ejecución %s (intento %s)", execution_id, intento)
            with sesion_contexto() as s:
                s.execute(update(Ejecucion).where(Ejecucion.execution_id == execution_id).values(
                    estado="error" if definitiva else "en_cola",
                    mensaje=f"{type(exc).__name__}: {exc}"[:2000],
                    terminado_en=ahora() if definitiva else None, actualizado_en=ahora()))
            if definitiva:
                return
            time.sleep(min(0.5 * 2 ** (intento - 1), 5))


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
    resumen: dict[str, int] = {}
    for err in errores:
        dim = str(err.get("dimension") or "validez")
        resumen[dim] = resumen.get(dim, 0) + 1
        fila = err.get("fila")
        s.add(ErrorCalidad(execution_id=execution_id, lote=str(err.get("lote") or lote),
                           fila=int(fila) if _num(fila) is not None else None, campo=err.get("campo"),
                           codigo=str(err.get("codigo") or "DQ"), dimension=dim,
                           detalle=None if err.get("detalle") is None else str(err.get("detalle"))))
    return resumen


def _incorporar_historico(s: Session, validos, execution_id: uuid.UUID) -> int:
    """Upsert por la clave natural (ruta, fecha, hora): una carga repetida no duplica."""
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    if validos is None or not len(validos):
        return 0
    filas = []
    for r in validos[["ruta", "fecha", "hora", "pasajeros", "salidas", "ultima_actualizacion"]].itertuples(index=False):
        filas.append(dict(ruta=str(r.ruta), fecha=r.fecha if isinstance(r.fecha, date) else a_instante(r.fecha).date(),
                          hora=int(r.hora), pasajeros=_num(r.pasajeros),
                          salidas=None if _num(r.salidas) is None else int(r.salidas),
                          ultima_actualizacion=a_instante(r.ultima_actualizacion), execution_id=execution_id))
    for i in range(0, len(filas), 5000):
        lote = filas[i:i + 5000]
        stmt = pg_insert(DemandaObservada).values(lote)
        stmt = stmt.on_conflict_do_update(
            constraint="ux_demanda_observada_clave",
            set_={"pasajeros": stmt.excluded.pasajeros, "salidas": stmt.excluded.salidas,
                  "ultima_actualizacion": stmt.excluded.ultima_actualizacion,
                  "execution_id": stmt.excluded.execution_id, "cargado_en": func.now()})
        s.execute(stmt)
    return len(filas)


def guardar_alerta(s: Session, a: dict, execution_id: uuid.UUID | None, umbrales_version: int | None
                   ) -> tuple[Alerta, bool]:
    """Inserta la alerta o, si ya hay una abierta con la misma clave_dedup, suma una ocurrencia."""
    abierta = s.scalar(select(Alerta).where(Alerta.clave_dedup == a["clave_dedup"],
                                            Alerta.estado.not_in(ESTADOS_CERRADOS)))
    if abierta is not None:
        abierta.ocurrencias += 1
        abierta.ultima_deteccion = ahora()
        abierta.actualizado_en = ahora()
        return abierta, False
    try:
        alert_id = uuid.UUID(str(a.get("id")))
    except (ValueError, TypeError):
        alert_id = uuid.uuid4()
    variables = json_seguro(a.get("variables") or {})
    variables["umbrales_version"] = umbrales_version
    nueva = Alerta(
        alert_id=alert_id, codigo=a["codigo"], execution_id=execution_id, empresa=a.get("empresa"),
        ruta=a.get("ruta"), sentido=a.get("sentido"), viaje=a.get("viaje"), conductor=a.get("conductor"),
        vehiculo=a.get("vehiculo"), detectada_en=a_instante(a.get("detectada_en")) or ahora(),
        ventana_inicio=a_instante(a.get("ventana_inicio")), ventana_fin=a_instante(a.get("ventana_fin")),
        horizonte_min=a.get("horizonte_min"), severidad=a["severidad"], estado="nueva",
        observado=_num(a.get("observado")), esperado=_num(a.get("esperado")), umbral=_num(a.get("umbral")),
        puntaje=_num(a.get("puntaje")), explicacion=a.get("explicacion"), variables=variables,
        recomendacion=a.get("recomendacion"), comentarios=[], clave_dedup=a["clave_dedup"], ocurrencias=1,
        ultima_deteccion=ahora())
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


def construir_recomendacion(r: dict, *, ruta: str, fecha: date, hora: int, demanda_hora: float | None,
                            demanda_p90: float | None, execution_id: uuid.UUID | None,
                            prediction_id: uuid.UUID | None, umbrales_version: int | None,
                            entradas: dict) -> Recomendacion:
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
        detalle=json_seguro({"entradas": entradas, "salida": r}))


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
        variables=json_seguro(r.get("variables") or {}))
    s.add(pred)
    s.flush()
    return pred


def _ciclo_frecuencia(execution_id: uuid.UUID) -> None:
    from app.servicios import alertas, calidad, datos, inferencia, optimizacion

    t0 = time.perf_counter()
    with sesion_contexto() as s:
        e = s.get(Ejecucion, execution_id)
        p = dict(e.parametros or {})
        hasta = date.fromisoformat(p["hasta"]) if p.get("hasta") else None
        marca_anterior = ultima_marca_agua(s)
        _avance(execution_id, 10, "lectura_incremental", marca_agua_anterior=marca_anterior)

        df, nueva_marca = obtener_fuente().leer_incremental(marca_anterior, hasta)
        filas_leidas = 0 if df is None else len(df)
        lote = f"{execution_id.hex[:8]}:{p.get('hasta') or 'todo'}"
        _avance(execution_id, 25, "calidad", filas_leidas=filas_leidas)
        if filas_leidas:
            validos, errores = calidad.validar_lote(df, lote)
        else:
            validos, errores = df, []
        resumen_dq = _guardar_errores(s, execution_id, lote, errores)
        filas_validas = 0 if validos is None else len(validos)
        incorporadas = _incorporar_historico(s, validos, execution_id)
        marca_nueva = a_instante(nueva_marca) or marca_anterior
        data_cutoff = marca_nueva

        version_u, umbrales = umbrales_vigentes(s)
        activo = modelo_activo(s)
        model_id = p.get("model_id") or (activo.model_id if activo else None)
        metricas: dict[str, Any] = {"lote": lote, "errores_calidad": resumen_dq, "incorporadas_historico": incorporadas}
        predicciones = recomendaciones = 0
        nuevas_alertas: list[Alerta] = []
        repetidas = 0
        fallos: list[dict] = []
        contextos: list[dict] = []

        if filas_validas == 0 and not p.get("instante"):
            metricas["nota"] = "Sin datos nuevos desde la marca de agua: no se reprocesa el histórico."
        else:
            # 1) evaluación del error del modelo activo sobre los días recién llegados (ciclo 14.2, paso 3)
            wape_por_ruta: dict[str, float] = {}
            if filas_validas and model_id:
                try:
                    ev = inferencia.evaluar(model_id, min(validos["fecha"]), max(validos["fecha"]))
                    metricas["evaluacion_error"] = json_seguro(ev)
                    for nombre_ruta, m in (ev.get("por_ruta") or {}).items():
                        w = _num((m or {}).get("wape"))
                        if w is not None:
                            wape_por_ruta[nombre_ruta] = w / 100.0 if w > 1.5 else w
                except Exception as exc:  # noqa: BLE001
                    fallos.append({"etapa": "evaluacion", "error": str(exc)})
            _avance(execution_id, 45, "prediccion")

            # 2) predicciones y recomendaciones
            instante = _instante_por_defecto(p, validos, data_cutoff)
            catalogo = {r["ruta"]: r for r in datos.catalogo_rutas()}
            rutas = p.get("rutas") or list(catalogo)
            for ruta in rutas:
                info = catalogo.get(ruta, {})
                for h in p.get("horizontes") or HORIZONTES:
                    try:
                        r = inferencia.predecir(ruta, instante, int(h), model_id=model_id)
                    except Exception as exc:  # noqa: BLE001 - se registra por ruta y horizonte
                        fallos.append({"etapa": "prediccion", "ruta": ruta, "horizonte_min": h, "error": str(exc)})
                        continue
                    pred = guardar_prediccion(s, r, ruta=ruta, instante=instante, horizonte_min=int(h),
                                              model_id=model_id, execution_id=execution_id)
                    predicciones += 1
                    entradas = parametros_recomendacion(info, umbrales)
                    try:
                        rec_d = optimizacion.recomendar(ruta, pred.hora, demanda_hora=pred.pasajeros,
                                                        demanda_p90=pred.p90, **entradas)
                    except Exception as exc:  # noqa: BLE001
                        fallos.append({"etapa": "recomendacion", "ruta": ruta, "horizonte_min": h, "error": str(exc)})
                        continue
                    s.add(construir_recomendacion(rec_d, ruta=ruta, fecha=pred.fecha, hora=pred.hora,
                                                  demanda_hora=pred.pasajeros, demanda_p90=pred.p90,
                                                  execution_id=execution_id, prediction_id=pred.prediction_id,
                                                  umbrales_version=version_u, entradas=entradas))
                    recomendaciones += 1
                    inicio = pred.objetivo.astimezone(ZONA).replace(minute=0, second=0, microsecond=0)
                    frec = entradas.get("frecuencia_actual_min")
                    contextos.append({
                        "ruta": ruta, "empresa": "Sobusa", "detectada_en": ahora(), "ventana_inicio": inicio,
                        "ventana_fin": inicio + timedelta(hours=1), "horizonte_min": int(h),
                        "demanda_prevista": pred.pasajeros, "p10": pred.p10, "p90": pred.p90,
                        "capacidad": entradas["capacidad"],
                        "buses_hora_actual": (60.0 / frec) if frec else None,
                        "buses_hora_recomendado": rec_d.get("buses_hora"), "model_id": pred.model_id,
                        # ALT-010 es del modelo: se evalúa una vez por ruta (primer horizonte), no por ventana
                        "wape_movil": wape_por_ruta.get(ruta) if h == (p.get("horizontes") or HORIZONTES)[0]
                        else None,
                        "campos_faltantes": sorted({str(x.get("campo")) for x in errores
                                                    if x.get("dimension") == "completitud"}) or None,
                    })
            _avance(execution_id, 70, "alertas")

            # 3) alertas deduplicadas
            umbrales_alertas = dict(umbrales) | {"version": version_u}
            for ctx in contextos:
                for a in alertas.evaluar_alertas(ctx, umbrales_alertas):
                    registro, es_nueva = guardar_alerta(s, a, execution_id, version_u)
                    if es_nueva:
                        nuevas_alertas.append(registro)
                    else:
                        repetidas += 1
            _avance(execution_id, 85, "notificaciones")

            # 4) notificaciones simuladas de las alertas nuevas críticas
            if p.get("notificar", True) and nuevas_alertas:
                metricas["notificaciones"] = _notificar(s, execution_id, nuevas_alertas, fallos)

        metricas.update({
            "predicciones": predicciones, "recomendaciones": recomendaciones, "alertas_nuevas": len(nuevas_alertas),
            "alertas_repetidas": repetidas, "fallos": fallos, "duracion_s": round(time.perf_counter() - t0, 3)})
        feature_version = None
        if predicciones:
            feature_version = s.scalar(select(Prediccion.feature_version)
                                       .where(Prediccion.execution_id == execution_id).limit(1))
        s.execute(update(Ejecucion).where(Ejecucion.execution_id == execution_id).values(
            estado="ok", etapa="terminada", progreso=100, marca_agua_anterior=marca_anterior,
            marca_agua_nueva=marca_nueva, data_cutoff=data_cutoff, filas_leidas=filas_leidas,
            filas_validas=filas_validas, model_id=model_id, feature_version=feature_version,
            umbrales_version=version_u, metricas=json_seguro(metricas),
            mensaje="Terminada" if not fallos else f"Terminada con {len(fallos)} fallos parciales",
            terminado_en=ahora(), actualizado_en=ahora()))


def _notificar(s: Session, execution_id: uuid.UUID, nuevas: list[Alerta], fallos: list[dict]) -> int:
    try:
        from app.servicios import notificaciones
        canales = notificaciones.notificadores_desde_entorno()
    except Exception as exc:  # noqa: BLE001
        fallos.append({"etapa": "notificacion", "error": str(exc)})
        return 0
    enviadas = 0
    for alerta in nuevas:
        datos_alerta = json_seguro({c.key: getattr(alerta, c.key) for c in Alerta.__table__.columns})
        for canal in canales:
            try:
                registro = canal.enviar(datos_alerta) or {}
            except Exception as exc:  # noqa: BLE001 - un canal caído no detiene la ejecución
                fallos.append({"etapa": "notificacion", "canal": type(canal).__name__, "error": str(exc)})
                continue
            s.add(Notificacion(execution_id=execution_id, alert_id=alerta.alert_id,
                               canal=str(registro.get("canal") or type(canal).__name__),
                               destinatario=registro.get("destinatario") or ", ".join(
                                   map(str, registro.get("destinatarios") or [])) or None,
                               asunto=registro.get("asunto"),
                               mensaje=registro.get("mensaje"), estado=str(registro.get("estado") or "simulado"),
                               simulado=bool(registro.get("simulado", True)), detalle=json_seguro(registro)))
            enviadas += 1
    return enviadas


def _ciclo_entrenamiento(execution_id: uuid.UUID) -> None:
    """RF-018: entrena un candidato con los datos validados hasta la fecha pedida y lo registra como candidato."""
    from app.servicios import inferencia

    with sesion_contexto() as s:
        p = dict(s.get(Ejecucion, execution_id).parametros or {})
    _avance(execution_id, 20, "entrenamiento")
    info = inferencia.entrenar(date.fromisoformat(p["hasta"]), semilla=int(p.get("semilla", 42)))
    _avance(execution_id, 80, "registro")
    with sesion_contexto() as s:
        registro = registrar_modelo(s, info, estado="candidato", execution_id=execution_id)
        s.execute(update(Ejecucion).where(Ejecucion.execution_id == execution_id).values(
            estado="ok", etapa="terminada", progreso=100, model_id=registro.model_id,
            feature_version=registro.feature_version, data_cutoff=registro.data_cutoff,
            metricas=json_seguro({"modelo": info.get("metricas"), "sha256": info.get("sha256"),
                                  "artefacto": info.get("artefacto")}),
            mensaje=f"Candidato {registro.model_id} registrado", terminado_en=ahora(), actualizado_en=ahora()))
