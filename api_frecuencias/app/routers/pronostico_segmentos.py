"""Pronóstico por segmento y sentido (§9.1 «ruta, sentido, segmento») por DESAGREGACIÓN documentada.

No hay un modelo por segmento: timbradas_segmentos solo trae 2023-01-01 a 2023-02-27, así que el pronóstico de la
ruta (el del modelo activo, con su banda calibrada) se reparte con la fracción histórica de subidas de cada segmento
por ruta, tipo de día y hora de salida (datos/reparto_segmentos.parquet, scripts/preparar_segmentos.py). La suma de
los segmentos es exactamente el pronóstico de la ruta. El sentido es una aproximación geométrica (mitad del ciclo por
longitud acumulada): las exportaciones no traen columna de sentido. P10/P90 por segmento se escalan con la misma
fracción (los cuantiles no se suman: es una banda aproximada). Evaluación del reparto en
docs/evidencias/monitoreo/desagregacion_segmentos.json.

GET /api/v1/predictions/segmentos?prediction_id=...            reparte una predicción guardada
GET /api/v1/predictions/segmentos?ruta=...&instante=...&horizonte_min=60   pronóstico al vuelo (no se guarda)
"""
from __future__ import annotations

import uuid
from datetime import datetime
from functools import lru_cache
from typing import Any, Literal

import pandas as pd
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import obtener_sesion
from app.modelos_db import Prediccion
from app.routers.comun import ErrorApi, no_encontrado

router = APIRouter(tags=["predicciones y recomendaciones"])
ARCHIVO = "reparto_segmentos.parquet"
NOTA = ("Desagregación del pronóstico de la ruta con el reparto histórico de subidas por segmento "
        "(timbradas_segmentos, ene-feb 2023); sentido aproximado por la mitad del ciclo; no es un modelo por segmento")


@lru_cache(maxsize=2)
def _reparto(ruta_archivo: str, mtime: float) -> pd.DataFrame:
    return pd.read_parquet(ruta_archivo)


def reparto() -> pd.DataFrame:
    from app.servicios import datos

    archivo = datos.carpeta_datos() / ARCHIVO
    if not archivo.exists():
        raise ErrorApi(503, "reparto_no_disponible", f"Falta datos/{ARCHIVO}: ejecute scripts/preparar_segmentos.py")
    return _reparto(str(archivo), archivo.stat().st_mtime)


def tramos_de_prediccion(variables: dict, pasajeros: float) -> list[tuple[str, int, float]]:
    """[(fecha, hora, pasajeros de la ventana en esa hora)] desde variables['por_hora'] (normalizado al total)."""
    k = float(variables.get("factor_nowcast") or 1.0)
    por_hora = variables.get("por_hora") or []
    t = [(str(h["fecha"]), int(h["hora"]), float(h["fraccion"]) * float(h["pasajeros_hora"]) * k) for h in por_hora]
    suma = sum(x for _, _, x in t)
    if suma > 0 and pasajeros is not None:
        t = [(f, h, x * float(pasajeros) / suma) for f, h, x in t]
    return t


def desagregar(ruta: str, tramos: list[tuple[str, int, float]], pasajeros: float, p10: float | None,
               p90: float | None, tipo_dia_de) -> dict[str, Any]:
    """Reparte la demanda de la ventana entre segmentos; devuelve segmentos, sentidos y el control de la suma."""
    r = reparto()
    r = r[r["ruta"] == ruta]
    if r.empty:
        raise ErrorApi(404, "ruta_sin_segmentos", f"No hay reparto por segmento para la ruta {ruta}")
    acumulado: dict[int, float] = {}
    niveles: dict[int, str] = {}
    for fecha, hora, demanda in tramos:
        td = tipo_dia_de(fecha, hora)
        celda = r[(r["tipo_dia"] == td) & (r["hora"] == hora)]
        if celda.empty:
            celda = r[r["tipo_dia"] == td].groupby("id_segmento", as_index=False).agg(
                fraccion=("fraccion", "mean"), nivel=("nivel", "first"))
            celda["fraccion"] = celda["fraccion"] / celda["fraccion"].sum()
            celda["nivel"] = "ruta_tipo_dia (hora sin datos)"
        for s, f, n in zip(celda["id_segmento"], celda["fraccion"], celda["nivel"], strict=False):
            acumulado[int(s)] = acumulado.get(int(s), 0.0) + demanda * float(f)
            niveles.setdefault(int(s), str(n))
    meta = r.drop_duplicates("id_segmento").set_index("id_segmento")
    total = sum(acumulado.values()) or 1.0
    segmentos = []
    for s, v in sorted(acumulado.items(), key=lambda kv: int(meta.at[kv[0], "nro_segmento"])):
        frac = v / total
        segmentos.append({
            "id_segmento": s, "nro_segmento": int(meta.at[s, "nro_segmento"]), "sentido": meta.at[s, "sentido"],
            "km_inicio": round(float(meta.at[s, "km_inicio"]), 3),
            "longitud_m": round(float(meta.at[s, "longitud_m"]), 1),
            "fraccion": round(frac, 6), "pasajeros": round(v, 3),
            "p10": None if p10 is None else round(float(p10) * frac, 3),
            "p90": None if p90 is None else round(float(p90) * frac, 3), "nivel_reparto": niveles[s]})
    sentidos = {}
    for seg in segmentos:
        d = sentidos.setdefault(seg["sentido"], {"sentido": seg["sentido"], "pasajeros": 0.0, "fraccion": 0.0,
                                                 "segmentos": 0})
        d["pasajeros"] += seg["pasajeros"]
        d["fraccion"] += seg["fraccion"]
        d["segmentos"] += 1
    for d in sentidos.values():
        d["pasajeros"], d["fraccion"] = round(d["pasajeros"], 3), round(d["fraccion"], 6)
    return {"segmentos": segmentos, "sentidos": list(sentidos.values()),
            "suma_segmentos": round(sum(acumulado.values()), 3),   # sin redondear cada segmento
            "periodo_reparto": str(r["periodo"].iloc[0]) if "periodo" in r.columns else None}


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


@router.get("/predictions/segmentos", summary="Pronóstico por segmento y sentido (desagregación documentada del "
                                              "pronóstico de la ruta)")
def por_segmento(prediction_id: uuid.UUID | None = None, ruta: str | None = None, instante: datetime | None = None,
                 horizonte_min: int = Query(60, ge=30, le=120, json_schema_extra={"enum": [30, 60, 120]},
                                            description="30, 60 o 120"), model_id: str | None = None,
                 sentido: Literal["ida", "regreso"] | None = None, nivel: Literal["segmento", "sentido"] = "segmento",
                 sesion: Session = Depends(obtener_sesion)):
    from app.servicios import ejecucion as servicio
    from app.servicios import inferencia

    if int(horizonte_min) not in (30, 60, 120):
        raise ErrorApi(422, "horizonte_invalido", "horizonte_min debe ser 30, 60 o 120")
    if prediction_id is not None:
        base, variables = _base_guardada(sesion, prediction_id)
    else:
        base, variables = _base_al_vuelo(sesion, ruta, instante, int(horizonte_min), model_id)
    tabla = inferencia.tabla_variables(sesion)

    def tipo_dia_de(fecha: str, hora: int) -> int:
        f = pd.Timestamp(fecha).date()
        return inferencia._tipo_dia_tabla(tabla, base["ruta"], f, hora)

    tramos = tramos_de_prediccion(variables, base["pasajeros_ruta"])
    d = desagregar(base["ruta"], tramos, base["pasajeros_ruta"], base["p10"], base["p90"], tipo_dia_de)
    if sentido:
        d["segmentos"] = [x for x in d["segmentos"] if x["sentido"] == sentido]
        d["sentidos"] = [x for x in d["sentidos"] if x["sentido"] == sentido]
    salida = dict(base, nivel=nivel, nota=NOTA, metodo="fracción histórica de subidas por segmento × pronóstico "
                  "de la ruta, hora por hora de la ventana", periodo_reparto=d["periodo_reparto"],
                  suma_segmentos=d["suma_segmentos"], sentidos=d["sentidos"],
                  segmentos=d["segmentos"] if nivel == "segmento" else [],
                  evaluacion="docs/evidencias/monitoreo/desagregacion_segmentos.json")
    return servicio.json_seguro(salida)
