"""Capa analítica de segmentos y zonas tarifarias (especificación v1.5, §6.1, §6.2, §11.1, §11.2).

§6.1 pide promedios, máximos y mínimos de subidas, bajadas y pasajeros por segmento, y aclara que los máximos y
mínimos «no existen en el DDL: se derivan en la capa analítica agregando timbradas_segmentos, sin modificar funciones
ni scripts». Aquí se derivan con un SELECT de solo lectura (lector_ia, FuentePostgresSoloLectura.consultar: READ ONLY,
statement_timeout, TimeZone America/Bogota) sobre lo que escribe el trigger tg_timbrada_segmento:

- unidad de observación: un viaje (id_viaje) en un segmento y una hora; si el viaje cruza el segmento en dos bloques de
  15 minutos de la misma hora (errata E2) se suman sus subidas y bajadas y se toma la mayor ocupación (pasajeros);
- dimensiones: segmento (id, ruta, nro_segmento), estacionalidad (la de estacionalidades_anio vigente en la fecha
  para el proceso de la ruta de cada segmento, con el mismo desempate que fn_insert_timbradas_anio: el período más
  corto), día de la semana ISO (1 = lunes, como
  EXTRACT(ISODOW) en las funciones de Extreme) y hora del bloque (hora_inicio del trigger);
- medidas: nro_viajes, días, promedio, máximo y mínimo de subidas, bajadas y pasajeros, y totales.

§6.2 «demanda por zona tarifaria»: timbradas_anio_zonas y timbradas_consolidado_zonas con su consolidado padre. En
Sobusa ninguna ruta maneja zonas (rutas.maneja_zonas = false, id_tipo_tarifa ≠ 2), así que Extreme no las llena; la
respuesta lo dice con el dato de rutas en vez de devolver una tabla vacía sin explicación (hallazgo H5).

Todo el SQL es constante (lista blanca); los filtros van como parámetros enlazados y el orden sale de una lista de
columnas permitidas. Nada se escribe en la base de Extreme.
"""
from __future__ import annotations

import io
import math
from datetime import date, datetime
from typing import Any

import pandas as pd

from app.config import obtener_ajustes

ORDENES = {"idruta", "nro_segmento", "id_segmento", "id_estacionalidad", "id_dia_semana", "hora", "nro_viajes",
           "prom_subidas", "max_subidas", "prom_bajadas", "max_bajadas", "prom_pasajeros", "max_pasajeros",
           "subidas", "bajadas"}
ORDEN_DEFECTO = "idruta, nro_segmento, id_estacionalidad, id_dia_semana, hora"
LIMITE_EXPORTACION = 50_000

_SQL_ESTADISTICAS = """
WITH filtrado AS (
    SELECT ts.id_segmento, rs.idruta, rs.nro_segmento, ts.id_viaje, ts.fecha,
           CAST(EXTRACT(ISODOW FROM ts.fecha) AS integer) AS id_dia_semana,
           CAST(EXTRACT(HOUR FROM ts.hora_inicio) AS integer) AS hora,
           ts.subidas, ts.bajadas, ts.pasajeros
      FROM timbradas_segmentos ts
      JOIN rutas_segmentos rs ON rs.id = ts.id_segmento
     WHERE (CAST(:idruta AS bigint) IS NULL OR rs.idruta = CAST(:idruta AS bigint))
       AND (CAST(:id_segmento AS bigint) IS NULL OR ts.id_segmento = CAST(:id_segmento AS bigint))
       AND (CAST(:desde AS date) IS NULL OR ts.fecha >= CAST(:desde AS date))
       AND (CAST(:hasta AS date) IS NULL OR ts.fecha <= CAST(:hasta AS date))
), por_viaje AS (
    SELECT id_segmento, idruta, nro_segmento, id_viaje, fecha, id_dia_semana, hora,
           SUM(subidas) AS subidas, SUM(bajadas) AS bajadas, MAX(pasajeros) AS pasajeros
      FROM filtrado
     GROUP BY id_segmento, idruta, nro_segmento, id_viaje, fecha, id_dia_semana, hora
), estacion AS (
    SELECT f.fecha, f.idruta, ea.id_estacionalidad, ea.id_estacionalidad_anio
      FROM (SELECT DISTINCT fecha, idruta FROM por_viaje) f
      LEFT JOIN LATERAL (
            SELECT e.id_estacionalidad, e.id_estacionalidad_anio
              FROM estacionalidades_anio e
              JOIN rutas r ON r.proceso = e.proceso AND r.idruta = f.idruta
             WHERE e.fecha_inicio <= f.fecha AND e.fecha_fin >= f.fecha
             ORDER BY (e.fecha_fin - e.fecha_inicio), e.fecha_inicio DESC, e.id_estacionalidad_anio DESC
             LIMIT 1) ea ON true
), agregado AS (
    SELECT p.id_segmento, p.idruta, p.nro_segmento, es.id_estacionalidad, p.id_dia_semana, p.hora,
           COUNT(*) AS nro_viajes, COUNT(DISTINCT p.fecha) AS dias,
           ROUND(AVG(p.subidas), 3) AS prom_subidas, MAX(p.subidas) AS max_subidas, MIN(p.subidas) AS min_subidas,
           ROUND(AVG(p.bajadas), 3) AS prom_bajadas, MAX(p.bajadas) AS max_bajadas, MIN(p.bajadas) AS min_bajadas,
           ROUND(AVG(p.pasajeros), 3) AS prom_pasajeros, MAX(p.pasajeros) AS max_pasajeros,
           MIN(p.pasajeros) AS min_pasajeros, SUM(p.subidas) AS subidas, SUM(p.bajadas) AS bajadas,
           MIN(p.fecha) AS primera_fecha, MAX(p.fecha) AS ultima_fecha
      FROM por_viaje p
      JOIN estacion es ON es.fecha = p.fecha AND es.idruta = p.idruta
     WHERE (CAST(:id_estacionalidad AS bigint) IS NULL OR es.id_estacionalidad = CAST(:id_estacionalidad AS bigint))
       AND (CAST(:id_dia_semana AS integer) IS NULL OR p.id_dia_semana = CAST(:id_dia_semana AS integer))
       AND (CAST(:hora AS integer) IS NULL OR p.hora = CAST(:hora AS integer))
     GROUP BY p.id_segmento, p.idruta, p.nro_segmento, es.id_estacionalidad, p.id_dia_semana, p.hora
)
SELECT a.*, COUNT(*) OVER () AS total_filas
  FROM agregado a
 ORDER BY {orden}
 LIMIT :limite OFFSET :desplazamiento
"""

_SQL_ZONAS = {
    "anio": """
SELECT 'anio' AS nivel, t.id_ruta, t.proceso, t.ano, t.id_dia_semana, t.id_estacionalidad_anio AS id_estacionalidad,
       t.hora_inicio, t.hora_fin, z.id_zona_tarifa, z.subidas, z.bajadas, z.nro_viajes, z.promedio_subidas,
       z.promedio_bajadas, z.ultima_actualizacion, COUNT(*) OVER () AS total_filas
  FROM timbradas_anio_zonas z
  JOIN timbradas_anio t ON t.id_timbrada_anio = z.id_timbrada_anio
 WHERE (CAST(:idruta AS bigint) IS NULL OR t.id_ruta = CAST(:idruta AS bigint))
   AND (CAST(:id_dia_semana AS integer) IS NULL OR t.id_dia_semana = CAST(:id_dia_semana AS integer))
 ORDER BY t.id_ruta, z.id_zona_tarifa, t.id_dia_semana, t.hora_inicio
 LIMIT :limite OFFSET :desplazamiento""",
    "consolidado": """
SELECT 'consolidado' AS nivel, t.id_ruta, t.proceso, NULL AS ano, t.id_dia_semana, t.id_estacionalidad,
       t.hora_inicio, t.hora_fin, z.id_zona_tarifa, z.subidas, z.bajadas, z.nro_viajes, z.promedio_subidas,
       z.promedio_bajadas, z.ultima_actualizacion, COUNT(*) OVER () AS total_filas
  FROM timbradas_consolidado_zonas z
  JOIN timbradas_consolidado t ON t.id_timbrada_consolidado = z.id_timbrada_consolidado
 WHERE (CAST(:idruta AS bigint) IS NULL OR t.id_ruta = CAST(:idruta AS bigint))
   AND (CAST(:id_dia_semana AS integer) IS NULL OR t.id_dia_semana = CAST(:id_dia_semana AS integer))
 ORDER BY t.id_ruta, z.id_zona_tarifa, t.id_dia_semana, t.hora_inicio
 LIMIT :limite OFFSET :desplazamiento""",
}
_SQL_RUTAS_ZONAS = "SELECT idruta, nombre, maneja_zonas, id_tipo_tarifa FROM rutas ORDER BY idruta"


class FuenteNoConfigurada(RuntimeError):
    """La capa analítica lee la base operacional: hace falta FUENTE_DATABASE_URL (usuario de solo lectura)."""


def fuente(motor=None):
    from app.servicios.fuentes import FuentePostgresSoloLectura

    aj = obtener_ajustes()
    if motor is None and not aj.fuente_database_url:
        raise FuenteNoConfigurada("FUENTE_DATABASE_URL no está definida: la capa de segmentos lee las tablas de "
                                  "Extreme con el usuario de solo lectura (modo integrado, docker-compose."
                                  "integracion.yml).")
    # Sin URL de relleno: con un motor inyectado la fuente no necesita URL (y sin ninguno de los dos ya falló arriba).
    return FuentePostgresSoloLectura(url=aj.fuente_database_url or None,
                                     tabla="timbradas_segmentos", statement_timeout_ms=aj.fuente_statement_timeout_ms,
                                     motor=motor)


def _orden(orden: str | None) -> str:
    if not orden:
        return ORDEN_DEFECTO
    partes = []
    for campo in orden.split(","):
        campo = campo.strip()
        desc = campo.startswith("-")
        nombre = campo.lstrip("+-")
        if nombre not in ORDENES:
            raise ValueError(f"No se puede ordenar por '{nombre}'. Campos: {', '.join(sorted(ORDENES))}")
        partes.append(f"{nombre} {'DESC' if desc else 'ASC'}")
    return ", ".join(partes + [ORDEN_DEFECTO])


def sql_estadisticas(orden: str | None = None) -> str:
    return _SQL_ESTADISTICAS.format(orden=_orden(orden))


def parametros_estadisticas(idruta=None, desde=None, hasta=None, id_segmento=None, id_estacionalidad=None,
                            id_dia_semana=None, hora=None, limite=50, desplazamiento=0) -> dict[str, Any]:
    if desde is not None and hasta is not None and desde > hasta:
        raise ValueError("desde no puede ser posterior a hasta")
    return {"idruta": idruta, "desde": desde, "hasta": hasta,
            "id_segmento": id_segmento, "id_estacionalidad": id_estacionalidad, "id_dia_semana": id_dia_semana,
            "hora": hora, "limite": int(limite), "desplazamiento": int(desplazamiento)}


def _numericos(df: pd.DataFrame) -> pd.DataFrame:
    """NUMERIC de PostgreSQL llega como Decimal: se pasa a float para operar y exportar."""
    from decimal import Decimal

    for c in df.columns:
        if df[c].dtype == object and df[c].map(lambda v: isinstance(v, Decimal)).any():
            df[c] = df[c].astype(float)
    return df


def _pagina(df: pd.DataFrame, limite: int, desplazamiento: int, **extra) -> dict:
    df = _numericos(df)
    total = int(df["total_filas"].iloc[0]) if len(df) else 0
    items = df.drop(columns=["total_filas"], errors="ignore")
    registros = [{k: _json(v) for k, v in fila.items()} for fila in items.to_dict(orient="records")]
    return {"total": total, "limite": limite, "desplazamiento": desplazamiento, "items": registros, **extra}


def _json(v):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if hasattr(v, "item"):
        return v.item()
    if hasattr(v, "isoformat"):
        return v.isoformat()
    if not isinstance(v, (int, float, str, bool)):
        try:
            return float(v)
        except (TypeError, ValueError):
            return str(v)
    return v


def estadisticas(orden: str | None = None, motor=None, **filtros) -> dict:
    """Página de estadísticas por segmento × estacionalidad × día de la semana × hora (§6.1)."""
    params = parametros_estadisticas(**filtros)
    df = fuente(motor).consultar(sql_estadisticas(orden), params)
    return _pagina(df, params["limite"], params["desplazamiento"],
                   definicion="viaje × segmento × hora; estacionalidad vigente en la fecha (período más corto); "
                              "día ISO 1 = lunes; derivado de timbradas_segmentos sin modificar funciones ni scripts")


def estadisticas_df(orden: str | None = None, motor=None, **filtros) -> pd.DataFrame:
    filtros.update(limite=LIMITE_EXPORTACION, desplazamiento=0)
    params = parametros_estadisticas(**filtros)
    df = fuente(motor).consultar(sql_estadisticas(orden), params).drop(columns=["total_filas"], errors="ignore")
    return _numericos(df)


def zonas(nivel: str = "consolidado", idruta=None, id_dia_semana=None, limite=50, desplazamiento=0,
          motor=None) -> dict:
    """Demanda por zona tarifaria (§6.2) desde timbradas_{anio,consolidado}_zonas, con la razón si no hay datos."""
    if nivel not in _SQL_ZONAS:
        raise ValueError("nivel debe ser 'anio' o 'consolidado'")
    f = fuente(motor)
    df = f.consultar(_SQL_ZONAS[nivel], {"idruta": idruta, "id_dia_semana": id_dia_semana, "limite": int(limite),
                                         "desplazamiento": int(desplazamiento)})
    extra: dict[str, Any] = {"nivel": nivel}
    if df.empty:
        rutas = f.consultar(_SQL_RUTAS_ZONAS)
        con_zonas = rutas[(rutas["maneja_zonas"].fillna(False)) | (rutas["id_tipo_tarifa"] == 2)]
        extra["nota"] = ("Sin filas: ninguna ruta maneja zonas tarifarias (rutas.maneja_zonas = false e "
                         "id_tipo_tarifa ≠ 2), por eso fn_insert_timbradas_anio no ejecuta su bloque de zonas "
                         "(docs/hallazgos_extreme.md, H5)." if con_zonas.empty else
                         "Sin filas para el filtro pedido.")
        extra["rutas"] = [{k: _json(v) for k, v in r.items()} for r in rutas.to_dict(orient="records")]
    return _pagina(df, int(limite), int(desplazamiento), **extra)


def exportar(df: pd.DataFrame, formato: str, nombre: str) -> tuple[bytes, str, str]:
    marca = datetime.now().strftime("%Y%m%d_%H%M%S")
    if formato == "xlsx":
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine="openpyxl") as escritor:
            df.to_excel(escritor, index=False, sheet_name=nombre[:31])
        return (buffer.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                f"{nombre}_{marca}.xlsx")
    return df.to_csv(index=False).encode("utf-8-sig"), "text/csv; charset=utf-8", f"{nombre}_{marca}.csv"


def sql_estadisticas_para_explain(motor) -> tuple[str, dict]:
    """SQL compilado (marcadores del driver) y parámetros de una consulta típica: ruta 2, todo el período."""
    import sqlalchemy as sa

    compilado = sa.text(sql_estadisticas()).compile(dialect=motor.dialect)
    return str(compilado), parametros_estadisticas(idruta=2, limite=100)


__all__ = ["estadisticas", "estadisticas_df", "zonas", "exportar", "FuenteNoConfigurada", "sql_estadisticas"]
