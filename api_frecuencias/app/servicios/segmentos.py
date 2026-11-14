"""Capa analítica de segmentos y zonas tarifarias (especificación v1.5, §6.1, §6.2, §7.1, §11.1, §11.2, RNF-002).

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

Agregación materializada (§7.1 «las peticiones HTTP no se bloquean durante lecturas masivas», RNF-002, RNF-004).
GET /api/v1/segmentos/estadisticas ya no agrega timbradas_segmentos dentro de la petición: lee el resultado que deja
el trabajo «segmentos» de la cola (app/servicios/segmentos_refresco.py) en el esquema propio:
- sin rango de fechas, o con un rango que cubre todo el período agregado: ai_frecuencias.segmento_estadistica, ya en
  el grano de la respuesta e indexada por los filtros y el orden por omisión;
- con un rango de fechas: ai_frecuencias.segmento_estadistica_dia (grano segmento × fecha × hora con medidas
  sumables), que se vuelve a agregar solo en ese rango.
Las dos dan EXACTAMENTE lo mismo que la agregación directa (estadisticas_directas, que se conserva como referencia y
para las pruebas): mismas columnas, mismos tipos y mismo redondeo (el promedio es numeric_div de las mismas sumas y
conteos que usa AVG). La respuesta dice de cuándo es la agregación (actualizado_en) y, si todavía no existe, lo dice
y el router encola el refresco en vez de bloquear la petición.

§6.2 «demanda por zona tarifaria»: timbradas_anio_zonas y timbradas_consolidado_zonas con su consolidado padre. En
Sobusa ninguna ruta maneja zonas (rutas.maneja_zonas = false, id_tipo_tarifa ≠ 2), así que Extreme no las llena; la
respuesta lo dice con el dato de rutas en vez de devolver una tabla vacía sin explicación (hallazgo H5).

Todo el SQL es constante (lista blanca); los filtros van como parámetros enlazados, las condiciones salen de una lista
de fragmentos fijos y el orden de una lista de columnas permitidas. Nada se escribe en la base de Extreme.
"""
from __future__ import annotations

import io
import math
import threading
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import obtener_ajustes

ORDENES = {"idruta", "nro_segmento", "id_segmento", "id_estacionalidad", "id_dia_semana", "hora", "nro_viajes",
           "prom_subidas", "max_subidas", "prom_bajadas", "max_bajadas", "prom_pasajeros", "max_pasajeros",
           "subidas", "bajadas"}
# id_segmento al final: dos segmentos de configuraciones distintas pueden compartir ruta y nro_segmento, y sin él el
# orden de los empates (y por lo tanto el contenido de cada página) quedaría al azar.
ORDEN_DEFECTO = "idruta, nro_segmento, id_estacionalidad, id_dia_semana, hora, id_segmento"
LIMITE_EXPORTACION = 50_000
DEFINICION = ("viaje × segmento × hora; estacionalidad vigente en la fecha (período más corto); día ISO 1 = lunes; "
              "derivado de timbradas_segmentos sin modificar funciones ni scripts")
FUENTE_MATERIALIZADA = "agregacion_materializada"

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

# ---------------------------------------------------------------- lectura de la agregación materializada
LLAVES = "id_segmento, idruta, nro_segmento, id_estacionalidad, id_dia_semana, hora"
COLUMNAS = (LLAVES + ", nro_viajes, dias, prom_subidas, max_subidas, min_subidas, prom_bajadas, max_bajadas, "
            "min_bajadas, prom_pasajeros, max_pasajeros, min_pasajeros, subidas, bajadas, primera_fecha, ultima_fecha")
# Medidas del grano de la respuesta a partir del grano diario. El promedio es numeric_div(Σ, n) redondeado, la misma
# división que hace AVG sobre los viajes; días = filas diarias del grupo (una por fecha, llave primaria del grano).
MEDIDAS_DESDE_DIA = """SUM(nro_viajes) AS nro_viajes, COUNT(*) AS dias,
           ROUND(SUM(suma_subidas) / SUM(nro_viajes), 3) AS prom_subidas, MAX(max_subidas) AS max_subidas,
           MIN(min_subidas) AS min_subidas,
           ROUND(SUM(suma_bajadas) / SUM(nro_viajes), 3) AS prom_bajadas, MAX(max_bajadas) AS max_bajadas,
           MIN(min_bajadas) AS min_bajadas,
           ROUND(SUM(suma_pasajeros) / SUM(nro_viajes), 3) AS prom_pasajeros, MAX(max_pasajeros) AS max_pasajeros,
           MIN(min_pasajeros) AS min_pasajeros, SUM(suma_subidas) AS subidas, SUM(suma_bajadas) AS bajadas,
           MIN(fecha) AS primera_fecha, MAX(fecha) AS ultima_fecha"""
# Condiciones fijas por filtro: solo entran las de los filtros presentes (el plan usa los índices de cada caso).
_CONDICIONES = {
    "idruta": "idruta = CAST(:idruta AS bigint)",
    "id_segmento": "id_segmento = CAST(:id_segmento AS bigint)",
    "id_estacionalidad": "id_estacionalidad = CAST(:id_estacionalidad AS bigint)",
    "id_dia_semana": "id_dia_semana = CAST(:id_dia_semana AS integer)",
    "hora": "hora = CAST(:hora AS integer)",
    "desde": "fecha >= CAST(:desde AS date)",
    "hasta": "fecha <= CAST(:hasta AS date)",
}
_FILTROS_RESPUESTA = ("idruta", "id_segmento", "id_estacionalidad", "id_dia_semana", "hora")
# Plantillas con marcadores que solo se llenan con las constantes de arriba, las condiciones fijas y el orden de la
# lista blanca (nunca con texto de la petición): los valores van siempre como parámetros enlazados.
_SQL_MAT_TOTAL = "SELECT count(*) FROM ai_frecuencias.segmento_estadistica{donde}"
_SQL_MAT_PAGINA = ("SELECT {columnas} FROM ai_frecuencias.segmento_estadistica{donde} ORDER BY {orden} "
                   "LIMIT :limite OFFSET :desplazamiento")
_SQL_DIA_PAGINA = ("WITH agregado AS (SELECT {llaves}, {medidas} FROM ai_frecuencias.segmento_estadistica_dia{donde} "
                   "GROUP BY {llaves}) SELECT a.*, COUNT(*) OVER () AS total_filas FROM agregado a ORDER BY {orden} "
                   "LIMIT :limite OFFSET :desplazamiento")
_SQL_DIA_TOTAL = ("SELECT count(*) FROM (SELECT 1 FROM ai_frecuencias.segmento_estadistica_dia{donde} "
                  "GROUP BY {llaves}) g")
# Con un rango de fechas largo la agregación del grano diario no cabe en el work_mem por omisión (4 MB) y ordena en
# disco: en la transacción de solo lectura de esa consulta se sube a 64 MB (un 30 % menos de tiempo, medido).
_SQL_MEMORIA_RANGO = text("SET LOCAL work_mem = '64MB'")
SQL_ULTIMO_REFRESCO = text("""
SELECT r.id, r.execution_id, r.modo, r.actualizado_en, r.fecha_min, r.fecha_max, r.filas_dia, r.filas,
       r.fechas_releidas, r.marca_fuente, r.huella_catalogos, r.duracion_s, r.huellas_solape,
       (SELECT max(c.actualizado_en) FROM ai_frecuencias.segmento_estadistica_refresco c
         WHERE c.modo = 'completo') AS ultimo_completo
  FROM ai_frecuencias.segmento_estadistica_refresco r
 ORDER BY r.actualizado_en DESC, r.id DESC
 LIMIT 1
""")

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


MENSAJE_SIN_FUENTE = ("FUENTE_DATABASE_URL no está definida: la capa de segmentos lee las tablas de Extreme con el "
                      "usuario de solo lectura (modo integrado, docker-compose.integracion.yml).")
_motores: dict[str, Any] = {}
_candado_motores = threading.Lock()


def _motor_fuente(url: str):
    """Un motor por URL de la fuente para todo el proceso: las lecturas no abren una conexión nueva cada vez."""
    url = url.replace("postgresql://", "postgresql+psycopg://", 1) if url.startswith("postgresql://") else url
    with _candado_motores:
        if url not in _motores:
            from sqlalchemy import create_engine

            _motores[url] = create_engine(url, pool_pre_ping=True, pool_size=2, max_overflow=2,
                                          connect_args={"connect_timeout": 5})
        return _motores[url]


def fuente_configurada() -> bool:
    return bool(obtener_ajustes().fuente_database_url)


def fuente(motor=None):
    from app.servicios.fuentes import FuentePostgresSoloLectura

    aj = obtener_ajustes()
    if motor is None and not aj.fuente_database_url:
        raise FuenteNoConfigurada(MENSAJE_SIN_FUENTE)
    if motor is None:
        motor = _motor_fuente(aj.fuente_database_url)
    # Sin URL de relleno: con un motor inyectado la fuente no necesita URL (y sin ninguno de los dos ya falló arriba).
    # cancelacion_responde: el refresco parte un tramo que agota el statement_timeout (segmentos_refresco.leer_tramo);
    # ese tiempo agotado no debe abrir el circuit breaker que comparten la ingesta y los catálogos.
    return FuentePostgresSoloLectura(url=aj.fuente_database_url or None,
                                     tabla="timbradas_segmentos", statement_timeout_ms=aj.fuente_statement_timeout_ms,
                                     motor=motor, cancelacion_responde=True)


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
    for c in df.columns:
        if df[c].dtype == object and df[c].map(lambda v: isinstance(v, Decimal)).any():
            df[c] = df[c].astype(float)
    return df


def _pagina(df: pd.DataFrame, limite: int, desplazamiento: int, **extra) -> dict:
    df = _numericos(df)
    total = int(df["total_filas"].iloc[0]) if len(df) else 0
    items = df.drop(columns=["total_filas"], errors="ignore")
    filas = [{k: _json(v) for k, v in fila.items()} for fila in items.to_dict(orient="records")]
    return {"total": total, "limite": limite, "desplazamiento": desplazamiento, "items": filas, **extra}


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


# ---------------------------------------------------------------- agregación directa (referencia)
def estadisticas_directas(orden: str | None = None, motor=None, **filtros) -> dict:
    """Agregación DIRECTA sobre timbradas_segmentos (§6.1), dentro de la llamada: es la referencia contra la que se
    prueba la materializada y lo que calcula, por tramos, el trabajo de refresco. La API no la usa en las peticiones."""
    params = parametros_estadisticas(**filtros)
    df = fuente(motor).consultar(sql_estadisticas(orden), params)
    return _pagina(df, params["limite"], params["desplazamiento"], definicion=DEFINICION)


def estadisticas_directas_df(orden: str | None = None, motor=None, **filtros) -> pd.DataFrame:
    filtros.update(limite=LIMITE_EXPORTACION, desplazamiento=0)
    params = parametros_estadisticas(**filtros)
    df = fuente(motor).consultar(sql_estadisticas(orden), params).drop(columns=["total_filas"], errors="ignore")
    return _numericos(df)


# ---------------------------------------------------------------- agregación materializada (lo que sirve la API)
def _donde(params: dict[str, Any], campos) -> str:
    activas = [_CONDICIONES[c] for c in campos if params.get(c) is not None]
    return (" WHERE " + " AND ".join(activas)) if activas else ""


def ultimo_refresco(s: Session) -> dict[str, Any] | None:
    """La marca del último refresco terminado de la agregación (None si nunca se calculó)."""
    fila = s.execute(SQL_ULTIMO_REFRESCO).mappings().first()
    return dict(fila) if fila is not None else None


def _instantanea(s: Session) -> None:
    """La marca y los datos se leen en una sola instantánea de solo lectura: un refresco que termina en medio de la
    consulta no mezcla el total de una versión con la página de otra."""
    if not s.in_transaction():
        s.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))


def _cubre_todo(params: dict[str, Any], refresco: dict[str, Any]) -> bool:
    """¿El rango pedido incluye todo el período agregado? Entonces el filtro de fechas no excluye nada."""
    desde, hasta = params.get("desde"), params.get("hasta")
    if desde is None and hasta is None:
        return True
    minimo, maximo = refresco.get("fecha_min"), refresco.get("fecha_max")
    if minimo is None or maximo is None:
        return True        # agregación vacía: la tabla del grano de la respuesta también lo está
    return (desde is None or desde <= minimo) and (hasta is None or hasta >= maximo)


def sql_materializada(params: dict[str, Any], orden: str | None, refresco: dict[str, Any]) -> tuple[str, str | None]:
    """(SQL de la página, SQL del total o None si la página trae total_filas) según el rango de fechas pedido."""
    criterio = _orden(orden)
    if _cubre_todo(params, refresco):
        donde = _donde(params, _FILTROS_RESPUESTA)
        return (_SQL_MAT_PAGINA.format(columnas=COLUMNAS, donde=donde, orden=criterio),
                _SQL_MAT_TOTAL.format(donde=donde))
    donde = _donde(params, (*_FILTROS_RESPUESTA, "desde", "hasta"))
    return _SQL_DIA_PAGINA.format(llaves=LLAVES, medidas=MEDIDAS_DESDE_DIA, donde=donde, orden=criterio), None


def _total_de_pagina_vacia(s: Session, params: dict[str, Any]) -> int:
    """Una página después del final viene sin filas (y sin total_filas): el total se cuenta aparte."""
    donde = _donde(params, (*_FILTROS_RESPUESTA, "desde", "hasta"))
    return int(s.execute(text(_SQL_DIA_TOTAL.format(donde=donde, llaves=LLAVES)), params).scalar() or 0)


def _leer_pagina(s: Session, params: dict[str, Any], orden: str | None, refresco: dict[str, Any]
                 ) -> tuple[list, int]:
    """(filas de la página, total de filas que cumplen los filtros) en la transacción de solo lectura."""
    sql_pagina, sql_total = sql_materializada(params, orden, refresco)
    if sql_total is None:
        s.execute(_SQL_MEMORIA_RANGO)
    filas = s.execute(text(sql_pagina), params).mappings().all()
    if sql_total is not None:
        return filas, int(s.execute(text(sql_total), params).scalar() or 0)
    if filas:
        return filas, int(filas[0]["total_filas"])
    return filas, (_total_de_pagina_vacia(s, params) if params["desplazamiento"] > 0 else 0)


def _entera_con_nulos(filas, columna: str) -> bool:
    valores = [f[columna] for f in filas]
    return None in valores and any(isinstance(v, int) and not isinstance(v, bool) for v in valores)


def _valor(v: Any, como_float: bool) -> Any:
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if como_float and isinstance(v, int) and not isinstance(v, bool):
        return float(v)
    return v


def registros(filas) -> list[dict[str, Any]]:
    """Filas -> items JSON con la MISMA representación que la agregación directa (que pasa por pandas): NUMERIC como
    float, fechas en ISO y, si en la página una columna entera trae nulos, sus enteros como float (pandas la vuelve
    float64). Sin armar un DataFrame por petición: es la ruta caliente de GET /segmentos/estadisticas."""
    if not filas:
        return []
    columnas = [c for c in filas[0].keys() if c != "total_filas"]
    flotantes = {c for c in columnas if _entera_con_nulos(filas, c)}
    return [{c: _valor(f[c], c in flotantes) for c in columnas} for f in filas]


def describir_refresco(refresco: dict[str, Any]) -> dict[str, Any]:
    """La marca del refresco para la respuesta (instantes en America/Bogota, -05:00)."""
    from app.servicios.ejecucion import ZONA

    def instante(v):
        return v.astimezone(ZONA).isoformat() if isinstance(v, datetime) else None

    return {"execution_id": str(refresco["execution_id"]) if refresco.get("execution_id") else None,
            "modo": refresco.get("modo"), "actualizado_en": instante(refresco.get("actualizado_en")),
            "ultimo_completo": instante(refresco.get("ultimo_completo")),
            "fecha_min": _json(refresco.get("fecha_min")), "fecha_max": _json(refresco.get("fecha_max")),
            "filas": int(refresco.get("filas") or 0), "filas_dia": int(refresco.get("filas_dia") or 0),
            "marca_fuente": instante(refresco.get("marca_fuente"))}


def _leer_materializada(s: Session, orden: str | None, filtros: dict[str, Any]) -> tuple | None:
    """(filas, total, marca del refresco, parámetros) en una instantánea de solo lectura; None sin agregación."""
    params = parametros_estadisticas(**filtros)
    _orden(orden)                                    # un orden inválido es 422 antes de tocar la base
    _instantanea(s)
    refresco = ultimo_refresco(s)
    if refresco is None:
        s.rollback()
        return None
    filas, total = _leer_pagina(s, params, orden, refresco)
    s.rollback()                                     # fin de la transacción de solo lectura
    return filas, total, refresco, params


def consultar(s: Session, orden: str | None = None, **filtros) -> dict | None:
    """Página de estadísticas por segmento × estacionalidad × día × hora (§6.1) desde la agregación materializada.

    None si la agregación todavía no existe (el router lo dice y encola el refresco). Nunca lee la base de Extreme."""
    leido = _leer_materializada(s, orden, filtros)
    if leido is None:
        return None
    filas, total, refresco, params = leido
    marca = describir_refresco(refresco)
    return {"total": total, "limite": params["limite"], "desplazamiento": params["desplazamiento"],
            "items": registros(filas), "definicion": DEFINICION, "disponible": True, "fuente": FUENTE_MATERIALIZADA,
            "actualizado_en": marca["actualizado_en"], "materializacion": marca}


def consultar_df(s: Session, orden: str | None = None, **filtros) -> pd.DataFrame | None:
    """Las mismas filas, hasta LIMITE_EXPORTACION, para la exportación CSV/XLSX (None si no hay agregación)."""
    filtros.update(limite=LIMITE_EXPORTACION, desplazamiento=0)
    leido = _leer_materializada(s, orden, filtros)
    if leido is None:
        return None
    columnas = [c.strip() for c in COLUMNAS.split(",")]
    return _numericos(pd.DataFrame([[f[c] for c in columnas] for f in leido[0]], columns=columnas))


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


__all__ = ["consultar", "consultar_df", "estadisticas_directas", "estadisticas_directas_df", "zonas", "exportar",
           "FuenteNoConfigurada", "sql_estadisticas", "ultimo_refresco", "describir_refresco", "fuente_configurada"]
