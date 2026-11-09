"""Utilidades comunes de los routers: errores uniformes, paginación, orden y exportación CSV/XLSX."""
from __future__ import annotations

import io
from datetime import datetime
from typing import Any

import pandas as pd
from fastapi import Query
from fastapi.responses import Response
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.servicios.ejecucion import ZONA, json_seguro

LIMITE_EXPORTACION = 100_000


class ErrorApi(Exception):
    def __init__(self, status: int, codigo: str, mensaje: str, detalle: Any = None):
        super().__init__(mensaje)
        self.status, self.codigo, self.mensaje, self.detalle = status, codigo, mensaje, detalle


def no_encontrado(recurso: str, ident: Any) -> ErrorApi:
    return ErrorApi(404, "no_encontrado", f"{recurso} {ident} no existe")


class ParametrosPagina:
    def __init__(self, limite: int = Query(50, ge=1, le=500, description="Tamaño de página"),
                 desplazamiento: int = Query(0, ge=0, description="Registros a saltar"),
                 orden: str | None = Query(None, description="Campo de orden; prefijo '-' para descendente")):
        self.limite, self.desplazamiento, self.orden = limite, desplazamiento, orden


def ordenar(consulta: Select, modelo, orden: str | None, por_defecto: str) -> Select:
    campo = orden or por_defecto
    desc = campo.startswith("-")
    nombre = campo.lstrip("-+")
    columna = modelo.__table__.columns.get(nombre)
    if columna is None:
        raise ErrorApi(422, "orden_invalido", f"No se puede ordenar por '{nombre}'",
                       {"campos": sorted(modelo.__table__.columns.keys())})
    return consulta.order_by(columna.desc() if desc else columna.asc())


def paginar(sesion: Session, consulta: Select, modelo, pagina: ParametrosPagina, por_defecto: str) -> dict:
    total = sesion.scalar(select(func.count()).select_from(consulta.order_by(None).subquery()))
    filas = sesion.scalars(ordenar(consulta, modelo, pagina.orden, por_defecto)
                           .limit(pagina.limite).offset(pagina.desplazamiento)).all()
    return {"total": total or 0, "limite": pagina.limite, "desplazamiento": pagina.desplazamiento, "items": filas}


def _fila(obj) -> dict:
    return {c.key: getattr(obj, c.key) for c in obj.__table__.columns}


def exportar(sesion: Session, consulta: Select, modelo, formato: str, nombre: str, orden: str | None,
             por_defecto: str) -> Response:
    filas = sesion.scalars(ordenar(consulta, modelo, orden, por_defecto).limit(LIMITE_EXPORTACION)).all()
    registros = []
    for f in filas:
        d = _fila(f)
        for k, v in list(d.items()):
            if isinstance(v, datetime):
                d[k] = v.astimezone(ZONA).isoformat()
            elif isinstance(v, (dict, list)):
                import json

                d[k] = json.dumps(json_seguro(v), ensure_ascii=False)
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
                        headers={"Content-Disposition": f'attachment; filename="{nombre}_{marca}.xlsx"'})
    contenido = df.to_csv(index=False).encode("utf-8-sig")
    return Response(contenido, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{nombre}_{marca}.csv"'})
