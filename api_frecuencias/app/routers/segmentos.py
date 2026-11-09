"""/api/v1/segmentos: capa analítica de segmentos y zonas tarifarias (§6.1, §6.2, §11.2), en solo lectura.

Autenticación y rol: los GET exigen al menos «operador» (app/seguridad.py, registro en main.py). Paginación con
limite/desplazamiento, orden con lista blanca y exportación CSV o XLSX (RF-017).

Sin base operacional configurada (modo offline, FUENTE_DATABASE_URL vacía) responde 200 con «disponible: false» y la
razón, en vez de un 5xx: la capa analítica solo existe en modo integrado (docker-compose.integracion.yml). Los errores
de la base (caída, timeout, circuito abierto) sí responden 503.
"""
from __future__ import annotations

from datetime import date
from typing import Literal

import pandas as pd
from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response

from app.routers.comun import ErrorApi, ParametrosPagina
from app.servicios import segmentos as servicio

router = APIRouter(prefix="/segmentos", tags=["segmentos"])
ENTERO_MAX = 2_147_483_647          # INTEGER de PostgreSQL
BIGINT_MAX = 9_223_372_036_854_775_807


def _filtros(idruta: int | None = Query(None, ge=0, le=ENTERO_MAX, description="idruta (2, 16 o 21)"),
             desde: date | None = Query(None, description="Fecha inicial (timbradas_segmentos.fecha)"),
             hasta: date | None = Query(None, description="Fecha final"),
             id_segmento: int | None = Query(None, ge=0, le=BIGINT_MAX, description="rutas_segmentos.id"),
             id_estacionalidad: int | None = Query(None, ge=0, le=BIGINT_MAX,
                                                   description="estacionalidades.id_estacionalidad"),
             id_dia_semana: int | None = Query(None, ge=1, le=7, description="Día ISO: 1 lunes … 7 domingo"),
             hora: int | None = Query(None, ge=0, le=23, description="Hora del bloque (hora_inicio)")) -> dict:
    return {"idruta": idruta, "desde": desde, "hasta": hasta, "id_segmento": id_segmento,
            "id_estacionalidad": id_estacionalidad, "id_dia_semana": id_dia_semana, "hora": hora}


def _no_disponible(exc: Exception, pagina: ParametrosPagina) -> dict:
    return {"total": 0, "limite": pagina.limite, "desplazamiento": pagina.desplazamiento, "items": [],
            "disponible": False, "nota": str(exc)}


def _llamar(funcion, *args, **kwargs):
    try:
        return funcion(*args, **kwargs)
    except ValueError as exc:
        raise ErrorApi(422, "parametro_invalido", str(exc)) from exc
    except servicio.FuenteNoConfigurada:
        raise
    except Exception as exc:  # noqa: BLE001 - base caída, timeout o circuito abierto: dependencia no disponible
        raise ErrorApi(503, "fuente_no_disponible", "La base operacional no respondió; reintente más tarde",
                       {"error": type(exc).__name__}) from exc


@router.get("/estadisticas",
            summary="Promedio, máximo y mínimo de subidas, bajadas y pasajeros por segmento, estacionalidad, día, hora")
def estadisticas(filtros: dict = Depends(_filtros), pagina: ParametrosPagina = Depends()) -> dict:
    try:
        return _llamar(servicio.estadisticas, orden=pagina.orden, limite=pagina.limite,
                       desplazamiento=pagina.desplazamiento, **filtros)
    except servicio.FuenteNoConfigurada as exc:
        return _no_disponible(exc, pagina)


@router.get("/estadisticas/export", summary="Exportar las estadísticas por segmento (CSV o XLSX)",
            response_class=Response)
def exportar_estadisticas(filtros: dict = Depends(_filtros), formato: Literal["csv", "xlsx"] = "csv",
                          orden: str | None = None) -> Response:
    try:
        df = _llamar(servicio.estadisticas_df, orden=orden, **filtros)
    except servicio.FuenteNoConfigurada:
        df = pd.DataFrame(columns=["id_segmento", "idruta", "nro_segmento", "id_estacionalidad", "id_dia_semana",
                                   "hora", "nro_viajes", "prom_subidas", "max_subidas", "min_subidas"])
    contenido, tipo, nombre = servicio.exportar(df, formato, "estadisticas_segmentos")
    return Response(contenido, media_type=tipo, headers={"Content-Disposition": f'attachment; filename="{nombre}"'})


@router.get("/zonas", summary="Demanda por zona tarifaria (timbradas_anio_zonas / timbradas_consolidado_zonas)")
def zonas(nivel: Literal["anio", "consolidado"] = "consolidado",
          idruta: int | None = Query(None, ge=0, le=ENTERO_MAX), id_dia_semana: int | None = Query(None, ge=1, le=7),
          pagina: ParametrosPagina = Depends()) -> dict:
    try:
        return _llamar(servicio.zonas, nivel=nivel, idruta=idruta, id_dia_semana=id_dia_semana, limite=pagina.limite,
                       desplazamiento=pagina.desplazamiento)
    except servicio.FuenteNoConfigurada as exc:
        return _no_disponible(exc, pagina)
