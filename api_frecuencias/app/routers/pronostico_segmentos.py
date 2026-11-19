"""Pronóstico por segmento y sentido (§3.1 «Predicción de demanda: por ruta, sentido, segmento y franja horaria →
pronóstico e intervalo de confianza», §9.1, §9.2).

El pronóstico de la ruta (el del modelo activo, con su banda calibrada) se reparte entre segmentos con el MODELO DE
SEGMENTOS activo (app/servicios/modelo_segmentos.py; registro datos/modelos/segmentos/registro.json, artefacto con
SHA-256 verificado al cargar): la fracción de cada segmento, hora por hora de la ventana, condicionada a ruta, sentido,
hora y calendario; la de cada sentido es la suma de sus segmentos y la suma de los segmentos es exactamente el
pronóstico de la ruta. La banda P10-P90 de cada segmento y sentido es conformal (ajustada en la validación de
feb-2023) compuesta con la banda de la ruta. El sentido es una aproximación geométrica (supuesto S9: mitad del ciclo
por longitud acumulada); las exportaciones no traen sentido. ?modelo_segmentos= elige otra versión registrada, por
ejemplo el reparto fijo B0 (la línea base). Evaluación: docs/evidencias/modelo/segmentos_modelo.md.

GET /api/v1/predictions/segmentos?prediction_id=...            reparte una predicción guardada
GET /api/v1/predictions/segmentos?ruta=...&instante=...&horizonte_min=60   pronóstico al vuelo (no se guarda)

Al vuelo, por omisión (fuente=auto) responde el pronóstico de corto plazo por segmento (RF-005; el modelo de segmentos
de E14, ajustado con las subidas por segmento de 2023-2025 y medido una vez en la prueba reservada de julio a
diciembre de 2025): cada segmento con su propio modelo, la banda conformal y la línea base. El reparto del modelo de
segmentos de ene-feb de 2023 sobre el pronóstico horario queda para repartir una predicción horaria guardada
(prediction_id) o si se pide (fuente=reparto o modelo_segmentos); fuera de la cobertura del corto plazo, auto reparte.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import obtener_sesion
from app.modelos_db import Prediccion
from app.routers.comun import ErrorApi, no_encontrado
from app.servicios import modelo_segmentos as ms

router = APIRouter(tags=["predicciones y recomendaciones"])
tramos_de_prediccion = ms.tramos_de_prediccion   # compatibilidad: la función vive en el servicio
SUPUESTO_SENTIDO = "sentido aproximado por la mitad del ciclo (supuesto S9; las exportaciones no traen sentido)"


def modelo_de_segmentos(model_id: str | None) -> dict:
    """Modelo de segmentos registrado (el activo por omisión), con su SHA-256 verificado.

    404 solo si el cliente pidió un model_id que no está; si al activo le falta el manifiesto, o el registro o el
    manifiesto no son JSON válido (ValueError), es una degradación del servidor: 503 «reparto_no_disponible»."""
    try:
        return ms.cargar(model_id)
    except ms.ModeloSegmentosNoEncontrado as exc:
        if model_id is None:
            raise _no_disponible(exc) from exc
        raise ErrorApi(404, "modelo_no_encontrado", str(exc).strip("'\""), {"modelo_segmentos": model_id}) from exc
    except (ms.ErrorModeloSegmentos, OSError, ValueError) as exc:
        raise _no_disponible(exc) from exc


def _no_disponible(exc: Exception) -> ErrorApi:
    return ErrorApi(503, "reparto_no_disponible", f"Modelo de segmentos no disponible: {exc}")


def _base_guardada(sesion: Session, prediction_id: uuid.UUID) -> tuple[dict, dict]:
    """Pronóstico de la ruta desde una predicción guardada: (datos de la predicción, variables usadas)."""
    pred = sesion.get(Prediccion, prediction_id)
    if pred is None:
        raise no_encontrado("La predicción", prediction_id)
    base = {"prediction_id": pred.prediction_id, "ruta": pred.ruta, "instante": pred.instante,
            "horizonte_min": pred.horizonte_min, "model_id": pred.model_id, "pasajeros_ruta": pred.pasajeros,
            "p10": pred.p10, "p90": pred.p90, "feature_version": pred.feature_version,
            "data_cutoff": pred.data_cutoff, "origen": "predicción guardada"}
    return base, pred.variables or {}


def _base_al_vuelo(sesion: Session, ruta: str | None, instante: datetime | None, horizonte_min: int,
                   model_id: str | None) -> tuple[dict, dict]:
    """Pronóstico de la ruta calculado al vuelo (no se guarda): (datos del pronóstico, variables usadas)."""
    from app.servicios import datos, inferencia
    from app.servicios import ejecucion as servicio

    if not ruta or instante is None:
        raise ErrorApi(422, "parametros_requeridos", "Indique prediction_id, o ruta e instante")
    try:
        ruta = datos.ruta_info(ruta)["ruta"]
    except KeyError as exc:
        raise ErrorApi(404, "ruta_desconocida", str(exc).strip("'\"")) from exc
    activo = servicio.modelo_activo(sesion)
    mid = model_id or (activo.model_id if activo else None)
    try:   # con la serie validada de la base: también los días que llegaron después del Parquet empaquetado
        with inferencia.con_sesion(sesion):
            r = inferencia.predecir(ruta, servicio.a_instante(instante), horizonte_min, model_id=mid)
    except LookupError as exc:
        raise ErrorApi(404, "modelo_no_encontrado", str(exc).strip("'\""), {"model_id": mid}) from exc
    except ValueError as exc:
        raise ErrorApi(422, "prediccion_invalida", str(exc)) from exc
    base = {"prediction_id": None, "ruta": ruta, "instante": r["instante"], "horizonte_min": r["horizonte_min"],
            "model_id": r["model_id"], "pasajeros_ruta": r["pasajeros"], "p10": r["p10"], "p90": r["p90"],
            "feature_version": r["feature_version"], "data_cutoff": r["data_cutoff"],
            "origen": "pronóstico al vuelo (no se guarda)"}
    return base, r["variables"]


def _desagregar(modelo: dict, base: dict, variables: dict, tabla) -> dict:
    def calendario_de(f: date, h: int) -> dict:
        return ms.calendario_de_tabla(tabla, base["ruta"], f, h)

    tramos = ms.tramos_de_prediccion(variables, base["pasajeros_ruta"])
    try:
        return ms.desagregar_ventana(modelo, base["ruta"], tramos, base["pasajeros_ruta"], base["p10"], base["p90"],
                                     calendario_de)
    except ms.RutaSinSegmentos as exc:
        raise ErrorApi(404, "ruta_sin_segmentos", str(exc)) from exc


@router.get("/predictions/segmentos", summary="Pronóstico por segmento y sentido (modelo de segmentos versionado "
                                              "sobre el pronóstico de la ruta, con banda P10-P90)")
def por_segmento(prediction_id: uuid.UUID | None = None, ruta: str | None = None, instante: datetime | None = None,
                 horizonte_min: int = Query(60, ge=30, le=120, json_schema_extra={"enum": [30, 60, 120]},
                                            description="30, 60 o 120"), model_id: str | None = None,
                 sentido: Literal["ida", "regreso"] | None = None, nivel: Literal["segmento", "sentido"] = "segmento",
                 modelo_segmentos: str | None = Query(None, max_length=120, description=(
                     "model_id del registro de segmentos (datos/modelos/segmentos/registro.json); por omisión el "
                     "activo. seg_reparto_fijo_20230227 es el reparto fijo B0, la línea base")),
                 fuente: Literal["auto", "corto_plazo", "reparto"] = Query("auto", description=(
                     "auto (por omisión): al vuelo, el pronóstico de corto plazo por segmento (el de E14, 2023-2025) "
                     "si cubre el instante; si no, o con prediction_id, model_id o modelo_segmentos, el reparto. "
                     "corto_plazo o "
                     "reparto lo fijan")),
                 sesion: Session = Depends(obtener_sesion)):
    from app.servicios import ejecucion as servicio
    from app.servicios import inferencia

    if int(horizonte_min) not in (30, 60, 120):
        raise ErrorApi(422, "horizonte_invalido", "horizonte_min debe ser 30, 60 o 120")
    al_vuelo = prediction_id is None and modelo_segmentos is None and model_id is None
    if fuente == "corto_plazo" or (fuente == "auto" and al_vuelo):
        d = _corto_plazo(sesion, ruta, instante, int(horizonte_min), fijado=fuente == "corto_plazo")
        if d is not None:
            d = _del_sentido(d, sentido)
            if nivel != "segmento":
                d["segmentos"] = []
            return servicio.json_seguro(dict(d, nivel=nivel))
    modelo = modelo_de_segmentos(modelo_segmentos)
    if prediction_id is not None:
        base, variables = _base_guardada(sesion, prediction_id)
    else:
        base, variables = _base_al_vuelo(sesion, ruta, instante, int(horizonte_min), model_id)
    d = _del_sentido(_desagregar(modelo, base, variables, inferencia.tabla_variables(sesion)), sentido)
    salida = dict(base, nivel=nivel, fuente="reparto",
                  nota=f"{ms.DESCRIPCIONES[modelo['tipo']]}, ajustado con las subidas por "
                                         f"segmento de {modelo.get('periodo_datos')}; {SUPUESTO_SENTIDO}",
                  metodo="fracción prevista por el modelo de segmentos × pronóstico de la ruta, hora por hora de la "
                         "ventana", periodo_reparto=d["periodo_reparto"], suma_segmentos=d["suma_segmentos"],
                  sentidos=d["sentidos"], segmentos=d["segmentos"] if nivel == "segmento" else [],
                  modelo_segmentos=ms.ficha(modelo), banda_segmentos=ms.METODO_BANDA,
                  evaluacion="docs/evidencias/modelo/segmentos_modelo.md")
    return servicio.json_seguro(salida)


def _del_sentido(d: dict, sentido: str | None) -> dict:
    """Los segmentos y sentidos de d, solo los del sentido pedido (todos si no se pidió uno)."""
    if sentido:
        d["segmentos"] = [x for x in d["segmentos"] if x["sentido"] == sentido]
        d["sentidos"] = [x for x in d["sentidos"] if x["sentido"] == sentido]
    return d


def _corto_plazo(sesion: Session, ruta: str | None, instante: datetime | None, horizonte_min: int,
                 fijado: bool) -> dict | None:
    """El pronóstico de corto plazo por segmento y sentido al vuelo, en la forma de esta respuesta. None si no cubre
    el pedido y no se fijó (entonces reparte); fijado y sin cobertura, 422."""
    from app.routers.pronostico_corto_plazo import modelo_de_la_familia
    from app.servicios import corto_plazo as cp
    from app.servicios import datos

    if not ruta or instante is None:
        if fijado:
            raise ErrorApi(422, "parametros_requeridos", "Indique ruta e instante")
        return None
    try:
        ruta = datos.ruta_info(ruta)["ruta"]
    except KeyError as exc:
        raise ErrorApi(404, "ruta_desconocida", str(exc).strip("'\"")) from exc
    try:
        with cp.con_sesion(sesion):
            r = cp.pronosticar(ruta, instante, horizonte_min, model_id=modelo_de_la_familia(sesion, None))
    except cp.FueraDeCobertura as exc:
        if fijado:
            raise ErrorApi(422, "fuera_de_cobertura", str(exc)) from exc
        return None
    except (cp.ErrorCortoPlazo, cp.ModeloCortoPlazoNoEncontrado, OSError) as exc:
        if fijado:
            raise ErrorApi(503, "pronostico_no_disponible", f"Modelo de corto plazo no disponible: {exc}") from exc
        return None
    total = round(sum(float(s["pasajeros"] or 0) for s in r["segmentos"]), 3)
    return {"prediction_id": None, "ruta": r["ruta"], "instante": r["instante"], "horizonte_min": r["horizonte_min"],
            "model_id": r["model_id"], "pasajeros_ruta": r["pasajeros"], "p10": r["p10"], "p90": r["p90"],
            "feature_version": r["feature_version"], "data_cutoff": r["data_cutoff"],
            "origen": "pronóstico de corto plazo al vuelo (no se guarda; POST /predictions/run o "
                      "/predictions/corto-plazo lo guardan)",
            "fuente": "corto_plazo", "ventana": r["ventana"], "datos_hasta": r.get("datos_hasta"),
            "nota": ("modelo de segmentos de E14 (LightGBM de Poisson por segmento, ajustado con las subidas por "
                     "segmento de 2023-2025 y medido una vez en la prueba reservada de julio a diciembre de 2025); el "
                     f"sentido es la suma de sus segmentos; {SUPUESTO_SENTIDO}"),
            "metodo": "un modelo por segmento con lo observado hasta el instante (no un reparto del total)",
            "periodo_reparto": None, "suma_segmentos": total, "sentidos": r["sentidos"], "segmentos": r["segmentos"],
            "pasajeros_ruta_modelo_ruta": r["pasajeros"], "modelo_segmentos": None, "calidad": r.get("calidad"),
            "banda_segmentos": "conformal por tramo del pronóstico, ajustada en la validación (enero-junio de 2025)",
            "evaluacion": "pronostico_corto_plazo/README.md (experimento E14)"}
