"""Utilidades comunes de los routers: errores uniformes, paginación, orden y exportación CSV/XLSX."""
from __future__ import annotations

import io
from datetime import datetime
from typing import Annotated, Any

import pandas as pd
from fastapi import Query
from fastapi.responses import Response
from pydantic import AfterValidator
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.esquemas import bogota_profundo
from app.servicios.ejecucion import ZONA, json_seguro

LIMITE_EXPORTACION = 100_000
HORIZONTES_VALIDOS = (30, 60, 120)
DESPLAZAMIENTO_MAX = 1_000_000_000          # cabe en el BIGINT de PostgreSQL: fuera de rango es 422, no 500


def _horizonte_valido(valor: int | None) -> int | None:
    if valor is not None and valor not in HORIZONTES_VALIDOS:
        raise ValueError("horizonte_min debe ser 30, 60 o 120")
    return valor


# Filtro opcional de horizonte en la consulta: Literal[30, 60, 120] no acepta el texto «60» de una URL, así que se
# declara entero acotado con su enumeración (OpenAPI) y un validador que rechaza los demás valores con 422.
HorizonteConsulta = Annotated[int | None, Query(ge=30, le=120, json_schema_extra={"enum": list(HORIZONTES_VALIDOS)},
                                                description="Horizonte del pronóstico en minutos: 30, 60 o 120"),
                              AfterValidator(_horizonte_valido)]


class ErrorApi(Exception):
    def __init__(self, status: int, codigo: str, mensaje: str, detalle: Any = None):
        super().__init__(mensaje)
        self.status, self.codigo, self.mensaje, self.detalle = status, codigo, mensaje, detalle


def no_encontrado(recurso: str, ident: Any) -> ErrorApi:
    return ErrorApi(404, "no_encontrado", f"{recurso} {ident} no existe")


class ParametrosPagina:
    def __init__(self, limite: int = Query(50, ge=1, le=500, description="Tamaño de página"),
                 desplazamiento: int = Query(0, ge=0, le=DESPLAZAMIENTO_MAX, description="Registros a saltar"),
                 orden: str | None = Query(None, description="Campo de orden; prefijo '-' para descendente")):
        self.limite, self.desplazamiento, self.orden = limite, desplazamiento, orden


def ordenar(consulta: Select, modelo, orden: str | None, por_defecto: str) -> Select:
    """Orden pedido (o el de por omisión) con la llave primaria como desempate: con LIMIT/OFFSET, un orden con empates
    repite o salta filas entre páginas (las ~1.170 filas de la foto de una ejecución comparten ventana_inicio)."""
    campo = orden or por_defecto
    desc = campo.startswith("-")
    nombre = campo.lstrip("-+")
    columna = modelo.__table__.columns.get(nombre)
    if columna is None:
        raise ErrorApi(422, "orden_invalido", f"No se puede ordenar por '{nombre}'",
                       {"campos": sorted(modelo.__table__.columns.keys())})
    desempate = [c for c in modelo.__table__.primary_key.columns if c is not columna]
    return consulta.order_by(columna.desc() if desc else columna.asc(), *desempate)


def paginar(sesion: Session, consulta: Select, modelo, pagina: ParametrosPagina, por_defecto: str) -> dict:
    total = sesion.scalar(select(func.count()).select_from(consulta.order_by(None).subquery()))
    filas = sesion.scalars(ordenar(consulta, modelo, pagina.orden, por_defecto)
                           .limit(pagina.limite).offset(pagina.desplazamiento)).all()
    return {"total": total or 0, "limite": pagina.limite, "desplazamiento": pagina.desplazamiento, "items": filas}


def _fila(obj) -> dict:
    return {c.key: getattr(obj, c.key) for c in obj.__table__.columns}


CABECERAS_EXPORTACION = {
    "X-Total-Count": {"description": "Registros que cumplen el filtro (aunque el archivo traiga menos)",
                      "required": True, "schema": {"type": "integer", "minimum": 0}},
    "X-Truncado": {"description": f"true si el archivo se cortó en el tope de {LIMITE_EXPORTACION:,} filas "
                                  "(LIMITE_EXPORTACION); afine los filtros para exportar el resto",
                   "required": True, "schema": {"type": "string", "enum": ["true", "false"]}},
}


def documentar_exportaciones(esquema: dict, prefijos_excluidos: tuple[str, ...] = ()) -> dict:
    """Agrega X-Total-Count y X-Truncado a la respuesta 200 de cada /export que arma exportar() (idempotente)."""
    for ruta, operaciones in esquema.get("paths", {}).items():
        if not ruta.endswith("/export") or ruta.startswith(prefijos_excluidos):
            continue
        respuesta = (operaciones.get("get") or {}).get("responses", {}).get("200")
        if respuesta is not None:
            respuesta["headers"] = {**(respuesta.get("headers") or {}), **CABECERAS_EXPORTACION}
    return esquema


def exportar(sesion: Session, consulta: Select, modelo, formato: str, nombre: str, orden: str | None,
             por_defecto: str) -> Response:
    """CSV (UTF-8 con BOM) o XLSX con los registros filtrados, hasta LIMITE_EXPORTACION filas. Siempre responde
    X-Total-Count (registros que cumplen el filtro) y X-Truncado (true si el archivo se cortó en el tope)."""
    filas = sesion.scalars(ordenar(consulta, modelo, orden, por_defecto).limit(LIMITE_EXPORTACION + 1)).all()
    truncado = len(filas) > LIMITE_EXPORTACION
    if truncado:
        filas = filas[:LIMITE_EXPORTACION]
        total = sesion.scalar(select(func.count()).select_from(consulta.order_by(None).subquery())) or 0
    else:
        total = len(filas)
    cabeceras = {"X-Total-Count": str(total), "X-Truncado": "true" if truncado else "false"}
    registros = []
    for f in filas:
        d = _fila(f)
        for k, v in list(d.items()):
            if isinstance(v, datetime):
                d[k] = v.astimezone(ZONA).isoformat()
            elif isinstance(v, (dict, list)):
                import json

                # §8.1 también dentro del JSON de la celda (comentarios[].en, variables, métricas, detalle)
                d[k] = json.dumps(bogota_profundo(json_seguro(v)), ensure_ascii=False)
            elif v is not None and not isinstance(v, (int, float, str, bool)):
                d[k] = str(v)
        registros.append(d)
    df = pd.DataFrame(registros, columns=[c.key for c in modelo.__table__.columns])
    marca = datetime.now(ZONA).strftime("%Y%m%d_%H%M%S")
    if formato == "xlsx":
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine="openpyxl") as escritor:
            df.to_excel(escritor, index=False, sheet_name=nombre[:31])
        return Response(buffer.getvalue(),
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": f'attachment; filename="{nombre}_{marca}.xlsx"',
                                 **cabeceras})
    contenido = df.to_csv(index=False).encode("utf-8-sig")
    return Response(contenido, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{nombre}_{marca}.csv"', **cabeceras})
