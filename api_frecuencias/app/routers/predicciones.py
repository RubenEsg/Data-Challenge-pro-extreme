"""Predicciones (RF-005, RF-006, RF-015) y recomendaciones (RF-007, RF-008) con consulta y exportación (RF-016/017)."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import obtener_sesion
from app.esquemas import (
    IntervaloConfianza,
    Pagina,
    PlanDia,
    PrediccionRespuesta,
    PrediccionSalida,
    RecomendacionCalculada,
    RecomendacionResumen,
    RecomendacionSalida,
    SolicitudPrediccion,
    SolicitudRecomendacion,
)
from app.modelos_db import Prediccion, Recomendacion
from app.routers.comun import (
    ErrorApi,
    HorizonteConsulta,
    ParametrosPagina,
    exportar,
    no_encontrado,
    ordenar,
    paginar,
)
from app.servicios import ejecucion as servicio

IdRutaConsulta = Annotated[int | None, Query(ge=1, le=2_147_483_647, description="Filtro por rutas.idruta de Extreme")]
router = APIRouter(tags=["predicciones y recomendaciones"])
Formato = Literal["csv", "xlsx"]


def _info_ruta(ruta: str) -> dict:
    from app.servicios import datos

    try:
        return datos.ruta_info(ruta)
    except KeyError as exc:
        raise ErrorApi(404, "ruta_desconocida", str(exc).strip("'\"")) from exc


def _elegir_modelo(solicitud: SolicitudPrediccion) -> tuple[str, str, bool]:
    """(modelo, motivo, fijado): qué modelo responde la solicitud. Un model_id del registro de corto plazo o del horario
    manda; si no, el campo «modelo». fijado=False solo en «auto»: entonces, si el corto plazo no cubre la solicitud,
    responde el horario."""
    from app.servicios import corto_plazo as cp

    if solicitud.model_id:
        try:
            de_corto_plazo = solicitud.model_id in (cp.registro().get("modelos") or {})
        except (OSError, ValueError):
            de_corto_plazo = False
        if de_corto_plazo:
            return "corto_plazo", f"model_id {solicitud.model_id} del registro de corto plazo", True
        return "horario", f"model_id {solicitud.model_id} del registro de modelos horarios", True
    if solicitud.modelo != "auto":
        return solicitud.modelo, f"modelo={solicitud.modelo} pedido en la solicitud", True
    return "corto_plazo", ("por omisión: el pronóstico de corto plazo de RF-005 (las subidas de la ventana con lo "
                           "observado hasta el instante)"), False


@router.post("/predictions/run", response_model=PrediccionRespuesta, status_code=201,
             summary="Inferencia para una ruta y un horizonte de 30, 60 o 120 min (incluye la recomendación derivada)")
def correr_prediccion(solicitud: SolicitudPrediccion, sesion: Session = Depends(obtener_sesion)):
    from app.servicios import corto_plazo as cp

    info = _info_ruta(solicitud.ruta)
    modelo, motivo, fijado = _elegir_modelo(solicitud)
    if modelo == "corto_plazo":
        try:
            return _correr_corto_plazo(solicitud, info, sesion, motivo)
        except cp.FueraDeCobertura as exc:
            if fijado:
                raise ErrorApi(422, "fuera_de_cobertura", str(exc)) from exc
            motivo = f"el pronóstico de corto plazo no cubre la solicitud ({exc}); responde el modelo horario"
        except (cp.ErrorCortoPlazo, cp.ModeloCortoPlazoNoEncontrado, OSError) as exc:
            if fijado:
                raise ErrorApi(503, "pronostico_no_disponible", f"Modelo de corto plazo no disponible: {exc}") from exc
            motivo = f"el modelo de corto plazo no está disponible ({exc}); responde el modelo horario"
    return _correr_horario(solicitud, info, sesion, motivo)


def _correr_corto_plazo(solicitud: SolicitudPrediccion, info: dict, sesion: Session,
                        motivo: str) -> PrediccionRespuesta:
    """RF-005 con el modelo de corto plazo: la ruta, sus sentidos y sus segmentos quedan en prediction_corto_plazo; la
    recomendación de la franja (§10.2, la hora del punto medio de la ventana a ritmo por hora) en recommendation."""
    from datetime import time as dtime

    from app.routers.pronostico_corto_plazo import modelo_de_la_familia
    from app.servicios import corto_plazo as cp

    mid = modelo_de_la_familia(sesion, solicitud.model_id)      # el activo de la familia en model_registry
    with cp.con_sesion(sesion):          # lo leído por la lectura incremental, además del panel empaquetado
        r = cp.pronosticar(info["ruta"], solicitud.instante, solicitud.horizonte_min, model_id=mid,
                           incluir_segmentos=solicitud.incluir_segmentos)
    r["generated_at"] = servicio.ahora().astimezone(cp.ZONA).isoformat(timespec="seconds")
    rec = franja = rec_d = None
    if solicitud.incluir_recomendacion:
        try:
            franja, rec_d, entradas, version_u = cp.recomendacion_completa(sesion, r, info)
        except ValueError as exc:
            raise ErrorApi(422, "parametros_invalidos", str(exc)) from exc
        rec_d["franja_prediccion"] = franja
        r["recomendacion"] = cp.resumen_recomendacion(franja, rec_d, version_u)
    grupo = cp.guardar(sesion, r)
    if rec_d is not None:
        entradas = dict(entradas, prediccion_corto_plazo={"grupo_id": str(grupo),
                                                          "prediction_id": str(r["prediction_id"])})
        rec = servicio.construir_recomendacion(rec_d, ruta=info["ruta"], fecha=franja["fecha"], hora=franja["hora"],
                                               demanda_hora=franja["demanda_hora"], demanda_p90=franja["p90_hora"],
                                               execution_id=None, prediction_id=None, umbrales_version=version_u,
                                               entradas=entradas, origen="corto_plazo",
                                               prediction_corto_plazo_id=r["prediction_id"])
        sesion.flush()      # la fila de la ruta de prediction_corto_plazo existe antes que la recomendación que la cita
        sesion.add(rec)
    sesion.commit()
    instante = datetime.fromisoformat(r["instante"])
    corte = date.fromisoformat(r["data_cutoff"])
    salida = PrediccionRespuesta(
        prediction_id=r["prediction_id"], execution_id=None, ruta=r["ruta"], instante=instante,
        horizonte_min=r["horizonte_min"], objetivo=datetime.fromisoformat(r["ventana"]["hasta"]),
        fecha=instante.date(), hora=instante.hour, pasajeros=r["pasajeros"], p10=r["p10"], p90=r["p90"],
        model_id=r["model_id"], feature_version=r["feature_version"],
        data_cutoff=datetime.combine(corte, dtime(0), tzinfo=cp.ZONA),
        generated_at=datetime.fromisoformat(r["generated_at"]), latencia_ms=r.get("latencia_ms"),
        explicacion=list(r["explicacion"]["factores"]), explicacion_local=r["explicacion"], idruta=r["idruta"],
        variables={"observado": r["observado"], "promedio_dia_hora": r.get("promedio_dia_hora"),
                   "ultima_semana": r.get("ultima_semana"), "real": r.get("real"),
                   "instante_solicitado": r["instante_solicitado"], "en_muestra": r["en_muestra"],
                   "dia_con_datos": r["dia_con_datos"], "calidad": r.get("calidad")},
        creado_en=servicio.ahora(), modelo="corto_plazo", motivo_modelo=motivo, grupo_id=grupo, ventana=r["ventana"],
        franja=r.get("franja"), sentidos=r["sentidos"], segmentos=r.get("segmentos"),
        recomendacion=RecomendacionSalida.model_validate(rec) if rec is not None else None)
    _claves_12_3(salida, rec)
    return salida


def _correr_horario(solicitud: SolicitudPrediccion, info: dict, sesion: Session, motivo: str) -> PrediccionRespuesta:
    """El modelo horario (el del plan del día siguiente): pronostica con siete días de antelación."""
    from app.servicios import inferencia, ocupacion

    ruta = info["ruta"]
    activo = servicio.modelo_activo(sesion)
    model_id = solicitud.model_id or (activo.model_id if activo else None)
    instante = servicio.a_instante(solicitud.instante)
    try:   # RF-013: con la serie validada de la sesión (Parquet ∪ demanda_observada) pronostica después del Parquet
        with inferencia.con_sesion(sesion):
            r = inferencia.predecir(ruta, instante, solicitud.horizonte_min, model_id=model_id)
    except LookupError as exc:
        raise ErrorApi(404, "modelo_no_encontrado", str(exc).strip("'\""), {"model_id": model_id}) from exc
    except ValueError as exc:
        raise ErrorApi(422, "prediccion_invalida", str(exc)) from exc
    pred = servicio.guardar_prediccion(sesion, r, ruta=ruta, instante=instante,
                                       horizonte_min=solicitud.horizonte_min, model_id=model_id, execution_id=None)
    rec = None
    if solicitud.incluir_recomendacion:
        version_u, umbrales = servicio.umbrales_vigentes(sesion)
        franja = _franja_de_la_prediccion(pred)
        # §10.1: la ocupación actual que ya midieron los ciclos antes del instante, la misma restricción reactiva que
        # reciben el plan del día y las recomendaciones del ciclo intradía (ninguna medición posterior al instante)
        reactiva = ocupacion.reactiva_guardada(sesion, ruta, franja["fecha"], instante, umbrales)
        try:   # §10.2 con la banda calibrada de la franja (P90 = nivel de servicio por omisión)
            rec_d, entradas = servicio.recomendacion_con_ocupacion(info, franja, umbrales, version_u, reactiva)
        except ValueError as exc:
            raise ErrorApi(422, "parametros_invalidos", str(exc)) from exc
        rec_d["franja_prediccion"] = franja
        rec = servicio.construir_recomendacion(rec_d, ruta=ruta, fecha=franja["fecha"], hora=franja["hora"],
                                               demanda_hora=franja["demanda_hora"], demanda_p90=franja["p90_hora"],
                                               execution_id=None, prediction_id=pred.prediction_id,
                                               umbrales_version=version_u, entradas=entradas)
        sesion.add(rec)
    sesion.commit()
    salida = PrediccionRespuesta.model_validate(pred)
    salida.recomendacion = RecomendacionSalida.model_validate(rec) if rec is not None else None
    salida.modelo, salida.motivo_modelo = "horario", motivo
    _claves_12_3(salida, rec)
    return salida


def _franja_de_la_prediccion(pred: Prediccion) -> dict:
    """La franja horaria que se recomienda: la hora con más peso en la ventana pronosticada, con su demanda POR HORA
    y su banda (variables.por_hora de inferencia.predecir). La ventana de 30/60/120 min no es una hora: sin el desglose
    se pasa a tasa horaria (× 60 / horizonte)."""
    from datetime import date as _date

    por_hora = [h for h in (pred.variables or {}).get("por_hora") or [] if isinstance(h, dict)
                and h.get("pasajeros_hora") is not None]
    if por_hora:
        h = max(por_hora, key=lambda x: float(x.get("fraccion") or 0))
        fecha = h.get("fecha")
        return {"fecha": _date.fromisoformat(str(fecha)[:10]) if fecha else pred.fecha, "hora": int(h["hora"]),
                "demanda_hora": float(h["pasajeros_hora"]),
                "p10_hora": None if h.get("p10_hora") is None else float(h["p10_hora"]),
                "p90_hora": None if h.get("p90_hora") is None else float(h["p90_hora"]),
                "fraccion_ventana": h.get("fraccion"), "fuente": "variables.por_hora (hora principal de la ventana)"}
    escala = 60.0 / float(pred.horizonte_min or 60)
    return {"fecha": pred.fecha, "hora": int(pred.hora), "demanda_hora": float(pred.pasajeros) * escala,
            "p10_hora": None if pred.p10 is None else float(pred.p10) * escala,
            "p90_hora": None if pred.p90 is None else float(pred.p90) * escala, "fraccion_ventana": None,
            "fuente": "ventana × 60 / horizonte (sin desglose por hora)"}


def _variables_principales(pred) -> list[str]:
    """§12.3 explanation: nombres de las variables que más mueven el pronóstico (SHAP local; si no, la importancia
    global del modelo; si no, las variables principales de la hora)."""
    variables = pred.variables or {}
    local = variables.get("explicacion_local") or getattr(pred, "explicacion_local", None) or {}
    nombres = [f.get("variable") for f in local.get("factores") or [] if isinstance(f, dict)]
    if not any(nombres):
        nombres = [x.get("variable") if isinstance(x, dict) else str(x) for x in local.get("importancia_global") or []]
    if not any(nombres):
        nombres = [k for k in ("lag7", "b8_regla_manual", "nivel_7_34", "tipo_dia", "hora") if variables.get(k)
                   is not None]
    return [str(n) for n in nombres if n][:5]


def _claves_12_3(salida: PrediccionRespuesta, rec) -> None:
    """Las claves del ejemplo de §12.3 (camelCase), además de los campos de siempre."""
    import math

    generada = servicio.a_instante(salida.generated_at)
    salida.predictionId = salida.prediction_id
    salida.routeId = salida.ruta
    salida.generatedAt = generada.astimezone(servicio.ZONA).isoformat(timespec="seconds") if generada else None
    salida.horizonMinutes = int(salida.horizonte_min)
    salida.predictedPassengers = int(round(float(salida.pasajeros)))
    salida.confidenceInterval = IntervaloConfianza(
        lower=None if salida.p10 is None else int(math.floor(float(salida.p10) + 1e-9)),
        upper=None if salida.p90 is None else int(math.ceil(float(salida.p90) - 1e-9)))
    salida.modelVersion = salida.model_id
    salida.recommendation = None if rec is None else _recomendacion_12_3(rec)
    salida.explanation = _variables_principales(salida)


def _recomendacion_12_3(rec) -> RecomendacionResumen:
    """§12.3 recommendation con su viabilidad: una franja inviable no presenta la mejor aproximación como
    recomendación (cifras en None, viable=false y el motivo); la aproximación sigue en recomendacion.detalle."""
    if not rec.viable:
        return RecomendacionResumen(viable=False, reason=rec.motivo)
    return RecomendacionResumen(headwayMinutes=rec.headway_min, busesPerHour=rec.buses_hora,
                                vehiclesRequired=rec.vehiculos_requeridos, viable=True)


def _por_idruta(consulta, modelo, idruta: int | None):
    """§8.3: filtro por idruta (la dimensión de Extreme); sin la columna, por el nombre de la ruta del catálogo."""
    if idruta is None:
        return consulta
    if hasattr(modelo, "idruta"):
        return consulta.where(modelo.idruta == idruta)
    from app.servicios.motor_d5 import comun

    return consulta.where(modelo.ruta == comun.RUTAS.get(int(idruta), f"idruta {idruta}"))


def _filtrar_predicciones(ruta, desde, hasta, horizonte_min, execution_id, model_id, idruta=None):
    consulta = _por_idruta(select(Prediccion), Prediccion, idruta)
    if ruta:
        consulta = consulta.where(Prediccion.ruta == ruta)
    if desde:
        consulta = consulta.where(Prediccion.fecha >= desde)
    if hasta:
        consulta = consulta.where(Prediccion.fecha <= hasta)
    if horizonte_min:
        consulta = consulta.where(Prediccion.horizonte_min == horizonte_min)
    if execution_id:
        consulta = consulta.where(Prediccion.execution_id == execution_id)
    if model_id:
        consulta = consulta.where(Prediccion.model_id == model_id)
    return consulta


DESCRIPCION_MODELO = (
    "Qué pronósticos: «corto_plazo» (las subidas de la ventana de 30, 60 o 120 min con lo observado hasta el instante, "
    "RF-005; la fila de la ruta: el detalle por sentido y segmento está en /predictions/corto-plazo), «horario» (el "
    "modelo del plan del día siguiente). Sin el filtro, los dos.")
ModeloConsulta = Annotated[Literal["horario", "corto_plazo"] | None, Query(description=DESCRIPCION_MODELO)]


def _filtrar_corto_plazo(ruta, desde, hasta, horizonte_min, execution_id, model_id, idruta):
    """Las filas de la ruta de prediction_corto_plazo con los filtros de /predictions."""
    from app.modelos_db import PrediccionCortoPlazo as P

    consulta = select(P).where(P.nivel == "ruta")
    for columna, valor in ((P.ruta, ruta), (P.horizonte_min, horizonte_min), (P.execution_id, execution_id),
                           (P.model_id, model_id), (P.idruta, idruta)):
        if valor:
            consulta = consulta.where(columna == valor)
    if desde:
        consulta = consulta.where(P.fecha >= desde)
    if hasta:
        consulta = consulta.where(P.fecha <= hasta)
    return consulta


def como_prediccion(p) -> dict:
    """Una fila de prediction_corto_plazo con los campos de /predictions (la hora es la del instante)."""
    from datetime import time as dtime

    zona = servicio.ZONA
    return {"prediction_id": p.prediction_id, "execution_id": p.execution_id, "ruta": p.ruta, "instante": p.instante,
            "horizonte_min": p.horizonte_min, "objetivo": p.objetivo, "fecha": p.fecha,
            "hora": p.instante.astimezone(zona).hour, "pasajeros": p.pasajeros, "p10": p.p10, "p90": p.p90,
            "model_id": p.model_id, "feature_version": p.feature_version,
            "data_cutoff": datetime.combine(p.data_cutoff, dtime(0), tzinfo=zona) if p.data_cutoff else None,
            "generated_at": p.generated_at, "latencia_ms": p.latencia_ms,
            "explicacion": list((p.explicacion or {}).get("factores") or []),
            "variables": dict(p.variables or {}, franja=p.franja, promedio_dia_hora=p.promedio_dia_hora,
                              ultima_semana=p.ultima_semana, nivel=p.nivel, sentido=p.sentido,
                              nro_segmento=p.nro_segmento),
            "creado_en": p.creado_en, "explicacion_local": p.explicacion or None, "idruta": p.idruta,
            "idempresa": p.idempresa, "idproceso": p.idproceso, "id_dia_semana": p.id_dia_semana,
            "id_estacionalidad": p.id_estacionalidad, "modelo": "corto_plazo", "grupo_id": p.grupo_id}


def _clave_orden(orden: str | None):
    """(atributo, descendente) de ParametrosPagina.orden para mezclar las dos tablas (por omisión, -generated_at)."""
    texto = (orden or "-generated_at").split(",")[0].strip()
    campo = texto.lstrip("-+")
    comunes = {"generated_at", "instante", "fecha", "ruta", "horizonte_min", "pasajeros", "model_id", "creado_en",
               "objetivo", "idruta"}
    return (campo if campo in comunes else "generated_at"), texto.startswith("-") or campo not in comunes


@router.get("/predictions", response_model=Pagina[PrediccionSalida], summary="Consultar pronósticos por filtros")
def listar_predicciones(ruta: str | None = None, desde: date | None = None, hasta: date | None = None,
                        horizonte_min: HorizonteConsulta = None, execution_id: uuid.UUID | None = None,
                        model_id: str | None = None, idruta: IdRutaConsulta = None, modelo: ModeloConsulta = None,
                        pagina: ParametrosPagina = Depends(),
                        sesion: Session = Depends(obtener_sesion)):
    from app.modelos_db import PrediccionCortoPlazo

    filtros = (ruta, desde, hasta, horizonte_min, execution_id, model_id, idruta)
    if modelo == "horario":
        return paginar(sesion, _filtrar_predicciones(*filtros), Prediccion, pagina, "-generated_at")
    if modelo == "corto_plazo":
        x = paginar(sesion, _filtrar_corto_plazo(*filtros), PrediccionCortoPlazo, pagina, "-generated_at")
        return dict(x, items=[como_prediccion(p) for p in x["items"]])
    # las dos tablas: cada una ordenada hasta desplazamiento + límite, mezcladas por la misma llave
    ordenar(_filtrar_predicciones(*filtros), Prediccion, pagina.orden, "-generated_at")   # 422 si no se puede
    campo, desc = _clave_orden(pagina.orden)
    n = pagina.desplazamiento + pagina.limite
    total = 0
    filas: list[dict] = []
    for consulta, modelo_db, convertir in ((_filtrar_predicciones(*filtros), Prediccion, None),
                                           (_filtrar_corto_plazo(*filtros), PrediccionCortoPlazo, como_prediccion)):
        total += sesion.scalar(select(func.count()).select_from(consulta.order_by(None).subquery())) or 0
        columna = getattr(modelo_db, campo)
        for f in sesion.scalars(consulta.order_by(columna.desc() if desc else columna.asc(),
                                                  modelo_db.prediction_id).limit(n)).all():
            filas.append(convertir(f) if convertir else PrediccionSalida.model_validate(f).model_dump())
    filas.sort(key=lambda f: (f[campo] is None, f[campo]), reverse=desc)
    return {"total": total, "limite": pagina.limite, "desplazamiento": pagina.desplazamiento,
            "items": filas[pagina.desplazamiento:n]}


@router.get("/predictions/export", summary="Exportar pronósticos filtrados (CSV o XLSX)",
            response_class=__import__("fastapi").responses.Response)
def exportar_predicciones(formato: Formato = "csv", ruta: str | None = None, desde: date | None = None,
                          hasta: date | None = None, horizonte_min: HorizonteConsulta = None,
                          execution_id: uuid.UUID | None = None, model_id: str | None = None,
                          idruta: IdRutaConsulta = None, orden: str | None = None,
                          modelo: Annotated[Literal["horario", "corto_plazo"], Query(
                              description="«horario» (por omisión) o «corto_plazo» (la fila de la ruta; el detalle "
                                          "por sentido y segmento sale de /predictions/corto-plazo/export)")] =
                          "horario",
                          sesion: Session = Depends(obtener_sesion)):
    from app.modelos_db import PrediccionCortoPlazo

    filtros = (ruta, desde, hasta, horizonte_min, execution_id, model_id, idruta)
    if modelo == "corto_plazo":
        return exportar(sesion, _filtrar_corto_plazo(*filtros), PrediccionCortoPlazo, formato,
                        "predicciones_corto_plazo", orden, "-generated_at")
    return exportar(sesion, _filtrar_predicciones(*filtros), Prediccion, formato, "predicciones", orden,
                    "-generated_at")


@router.get("/predictions/{prediction_id}", response_model=PrediccionSalida, summary="Una predicción")
def una_prediccion(prediction_id: uuid.UUID, sesion: Session = Depends(obtener_sesion)):
    from app.modelos_db import PrediccionCortoPlazo

    pred = sesion.get(Prediccion, prediction_id)
    if pred is not None:
        return pred
    cp = sesion.get(PrediccionCortoPlazo, prediction_id)
    if cp is None:
        raise no_encontrado("La predicción", prediction_id)
    return como_prediccion(cp)


@router.post("/recommendations/calculate", response_model=RecomendacionCalculada, status_code=201,
             summary="Calcular frecuencia y flota con la función objetivo de §10.2, tipologías, escenarios y "
                     "sensibilidad",
             description=(
                 "min α·costo_operativo + β·tiempo_espera + γ·penalización_sobreocupación + δ·desviación_frecuencia "
                 "sujeto a capacidad (nivel de servicio sobre el P90 calibrado), flota disponible, headway mínimo y "
                 "máximo y duración del ciclo (MILP de la franja con PuLP/CBC). Los pesos y costos son los vigentes "
                 "de threshold_config (PUT /thresholds crea una versión nueva) o los del código. Devuelve las "
                 "restricciones activas, los límites que mandan, la asignación por tipología (§10.1), las dos líneas "
                 "base de §10.3 (literal: factor 1 y demanda puntual; ajustada: factor de carga × P90), la "
                 "comparación con la frecuencia actual programada (RF-008), la marca de sobreoferta (ocupación "
                 "esperada bajo ocupacion_objetivo_min), el escenario «qué pasa si» y, si se pide, el análisis de "
                 "sensibilidad. El headway máximo es min(headway_maximo_min, 2 × espera_max_min). Una franja inviable "
                 "sale viable=false con su motivo; sus cifras son la mejor aproximación ejecutable (nunca violan "
                 "headway, flota ni ciclo), también en mejor_aproximacion."))
def calcular(solicitud: SolicitudRecomendacion, sesion: Session = Depends(obtener_sesion)):
    from app.servicios import optimizacion

    info = _info_ruta(solicitud.ruta)
    version_u, umbrales = servicio.umbrales_vigentes(sesion)
    if solicitud.prediction_id is not None and sesion.get(Prediccion, solicitud.prediction_id) is None:
        raise no_encontrado("La predicción", solicitud.prediction_id)
    fecha = solicitud.fecha or servicio.ahora().astimezone(servicio.ZONA).date()
    pedido = {c: getattr(solicitud, c) for c in optimizacion.CAMPOS_SOLICITUD}
    try:
        r, entradas = optimizacion.recomendacion_franja(
            info, umbrales, version_u, hora=solicitud.hora, fecha=fecha, demanda_hora=solicitud.demanda_hora,
            demanda_p90=solicitud.demanda_p90, demanda_p10=solicitud.demanda_p10, solicitud=pedido,
            pesos=solicitud.pesos, nivel_servicio=solicitud.nivel_servicio, usar_tipologias=solicitud.tipologias,
            escenario=solicitud.escenario.model_dump(exclude_none=True) if solicitud.escenario else None,
            incluir_sensibilidad=solicitud.sensibilidad)
    except ValueError as exc:
        raise ErrorApi(422, "parametros_invalidos", str(exc)) from exc
    rec = servicio.construir_recomendacion(
        optimizacion.para_guardar(r), ruta=info["ruta"], fecha=fecha, hora=solicitud.hora,
        demanda_hora=solicitud.demanda_hora,
        demanda_p90=solicitud.demanda_p90, execution_id=None, prediction_id=solicitud.prediction_id,
        umbrales_version=version_u, entradas=entradas)
    sesion.add(rec)
    sesion.commit()
    salida = RecomendacionCalculada.model_validate(rec)
    for campo in ("metodo", "objetivo", "demanda", "solver", "tipologias", "margen", "linea_base_10_3",
                  "linea_base_10_3_literal", "sobreoferta", "motivo_sobreoferta", "mejor_aproximacion",
                  "comparacion_actual", "escenario", "sensibilidad", "contexto_franja", "capacidad_gobernada",
                  "cambio_frecuenciadespachos", "fuente_frecuenciadespachos", "ocupacion_historica"):
        setattr(salida, campo, servicio.json_seguro(r.get(campo)))
    salida.restricciones = servicio.json_seguro(r.get("restricciones") or [])
    salida.limites_activos = list(r.get("limites_activos") or [])
    salida.explicacion = list(r.get("explicacion") or [])
    return salida


# Solo para pruebas (las pruebas lo cambian con monkeypatch): calcula el plan dentro del GET si no está persistido.
# Nunca se activa por HTTP (§7.1: los procesos largos van a la cola).
CALCULO_SINCRONO_PRUEBAS = False
PISTA_CALCULO = "POST /api/v1/respuesta/calcular"


def _filas_plan_persistido(sesion: Session, ruta: str, fecha: date) -> list:
    """Filas origen = 'plan_dia' de la ejecución más reciente que calculó el plan de esa ruta y fecha."""
    if hasattr(Recomendacion, "origen"):
        condicion = Recomendacion.origen == "plan_dia"
    else:   # esquema sin la columna: la marca va en detalle
        condicion = Recomendacion.detalle["origen"].astext == "plan_dia"
    filas = sesion.scalars(select(Recomendacion).where(Recomendacion.ruta == ruta, Recomendacion.fecha == fecha,
                                                       condicion).order_by(Recomendacion.creado_en.desc())).all()
    if not filas:
        return []
    ultima = filas[0].execution_id
    return [f for f in filas if f.execution_id == ultima]


@router.get("/recommendations/plan", response_model=PlanDia,
            summary="Plan del día por hora con el modelo activo (salidas, headway, vehículos, viabilidad y costo)",
            description=("Lee el plan del día persistido por el ciclo diario (ai_frecuencias.recommendation, origen "
                         "'plan_dia'): para cada hora de 4 a 20 h, salidas, despachos minuto a minuto, headway, "
                         "vehículos requeridos ceil(ciclo / headway) con headway = 60 / salidas por hora, costo y "
                         "flota, pasajeros previstos P10/P50/P90 del modelo "
                         "activo, límites activos, demanda de diseño, margen, viabilidad con su motivo, sobreoferta "
                         "y comparación con el intervalo programado. El resumen trae salidas programadas, flota, "
                         "costo del día, vehiculos_hora_pico y buses_en_ruta_pico; definicion_vehiculos dice qué mide "
                         "cada uno. Una hora con una sola salida no tiene intervalo que verificar (sin_intervalo). "
                         "MILP de D5 (PuLP/CBC) con flota en ruta, "
                         "suavidad, headway máximo efectivo y headway mínimo gobernados por threshold_config. El GET "
                         "no resuelve el MILP (§7.1): si el plan no está calculado responde 404 «sin_calcular» con la "
                         "pista de POST /api/v1/respuesta/calcular."))
def plan_dia(ruta: str, fecha: date, pronostico: Literal["activo", "E12"] = "activo",
             sesion: Session = Depends(obtener_sesion)):
    from app.servicios import optimizacion

    info = _info_ruta(ruta)
    filas = _filas_plan_persistido(sesion, info["ruta"], fecha) if pronostico == "activo" else []
    if filas:
        return optimizacion.plan_desde_filas(filas)
    if CALCULO_SINCRONO_PRUEBAS:
        version_u, umbrales = servicio.umbrales_vigentes(sesion)
        try:
            return optimizacion.plan_dia(fecha, info["ruta"], umbrales=umbrales, umbrales_version=version_u,
                                         pronostico=pronostico)
        except ValueError as exc:
            raise ErrorApi(404, "plan_no_disponible", str(exc), {"ruta": info["ruta"],
                                                                  "fecha": fecha.isoformat()}) from exc
    raise ErrorApi(404, "sin_calcular",
                   f"El plan del {fecha.isoformat()} para {info['ruta']} aún no está calculado: lo calcula el ciclo "
                   f"diario para el día siguiente o, a pedido, {PISTA_CALCULO} (rol analista, responde 202 con el "
                   f"execution_id).",
                   {"ruta": info["ruta"], "fecha": fecha.isoformat(), "pista": PISTA_CALCULO,
                    "pronostico": pronostico})


def _filtrar_recomendaciones(ruta, desde, hasta, viable, execution_id, idruta=None, origen=None):
    consulta = _por_idruta(select(Recomendacion), Recomendacion, idruta)
    if origen and hasattr(Recomendacion, "origen"):
        consulta = consulta.where(Recomendacion.origen == origen)
    if ruta:
        consulta = consulta.where(Recomendacion.ruta == ruta)
    if desde:
        consulta = consulta.where(Recomendacion.fecha >= desde)
    if hasta:
        consulta = consulta.where(Recomendacion.fecha <= hasta)
    if viable is not None:
        consulta = consulta.where(Recomendacion.viable == viable)
    if execution_id:
        consulta = consulta.where(Recomendacion.execution_id == execution_id)
    return consulta


DESCRIPCION_ORIGEN = (
    "Origen de la recomendación. «corto_plazo»: la de §10.2 con el pronóstico de corto plazo de la ventana (30, 60 o "
    "120 min; POST /predictions/run por omisión, POST /predictions/corto-plazo y el ciclo), ligada a la fila de la "
    "ruta de prediction_corto_plazo. «franja»: la de una franja con el modelo horario, ligada a su predicción (POST "
    "/predictions/run con modelo=horario, POST /recommendations/calculate o el ciclo diario). «plan_dia»: una hora del "
    "plan del día siguiente que persiste el ciclo diario (MILP de D5 con el modelo horario activo; sin prediction_id); "
    "GET /recommendations/plan las arma por ruta y fecha. Sin el filtro se listan todos los orígenes.")
OrigenConsulta = Annotated[Literal["franja", "plan_dia", "corto_plazo"] | None,
                           Query(description=DESCRIPCION_ORIGEN)]


@router.get("/recommendations", response_model=Pagina[RecomendacionSalida], summary="Consultar recomendaciones",
            description=(
                "Lista paginada de recomendaciones con dos orígenes, que se distinguen por el campo y el filtro "
                "«origen»: «franja» (franjas con la función objetivo de §10.2, ligadas a una predicción) y «plan_dia» "
                "(las horas del plan del día siguiente que persiste el ciclo diario). Sin «origen» se listan ambos; "
                "para la bandeja de recomendaciones de franja use origen=franja, y para el plan completo de una ruta "
                "y una fecha, GET /recommendations/plan. Filtros por ruta, idruta (§8.3), fechas, viabilidad y "
                "ejecución."))
def listar_recomendaciones(ruta: str | None = None, desde: date | None = None, hasta: date | None = None,
                           viable: bool | None = None, execution_id: uuid.UUID | None = None,
                           idruta: IdRutaConsulta = None, origen: OrigenConsulta = None,
                           pagina: ParametrosPagina = Depends(), sesion: Session = Depends(obtener_sesion)):
    consulta = _filtrar_recomendaciones(ruta, desde, hasta, viable, execution_id, idruta, origen)
    return paginar(sesion, consulta, Recomendacion, pagina, "-creado_en")


@router.get("/recommendations/export", summary="Exportar recomendaciones filtradas (CSV o XLSX)",
            response_class=__import__("fastapi").responses.Response)
def exportar_recomendaciones(formato: Formato = "csv", ruta: str | None = None, desde: date | None = None,
                             hasta: date | None = None, viable: bool | None = None,
                             execution_id: uuid.UUID | None = None, idruta: IdRutaConsulta = None,
                             origen: OrigenConsulta = None, orden: str | None = None,
                             sesion: Session = Depends(obtener_sesion)):
    consulta = _filtrar_recomendaciones(ruta, desde, hasta, viable, execution_id, idruta, origen)
    return exportar(sesion, consulta, Recomendacion, formato, "recomendaciones", orden, "-creado_en")
