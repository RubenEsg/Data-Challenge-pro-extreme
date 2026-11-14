"""Refresco de la agregación materializada de segmentos como trabajo de la cola (§6.1, §7.1, RNF-002, RNF-004).

§7.1 pide que las peticiones HTTP no se bloqueen durante lecturas masivas y RNF-004 que las lecturas largas vayan como
jobs con progreso y reintento. La agregación de timbradas_segmentos (2,77 millones de filas en la réplica) sale de la
petición y pasa a un trabajo de tipo «segmentos» de la cola en PostgreSQL (app/servicios/cola.py): reserva con
latido, reintento con espera exponencial, intentos auditados y cierre con cerca en la MISMA transacción que escribe
los resultados (si el intento falla o pierde la reserva, no queda nada a medias y la API sigue sirviendo la versión
anterior, que nunca se borra antes de tener la nueva).

Quién lo encola (siempre con la base operacional configurada, FUENTE_DATABASE_URL):
- el planificador interno (PLAN_SEGMENTOS_CRON, por omisión 05:45, después del ciclo diario de las 05:15);
- el ciclo diario de frecuencia, al terminar, si leyó datos nuevos (ejecucion._ciclo_frecuencia);
- POST /api/v1/segmentos/estadisticas/refrescar (rol analista, 202 con el execution_id);
- GET /api/v1/segmentos/estadisticas cuando la agregación todavía no existe (lo dice y no bloquea).
No se duplica: si ya hay uno igual en cola, se devuelve ese.

Qué hace (refrescar):
1. Toma un candado de asesoría de transacción: dos réplicas nunca refrescan a la vez.
2. Decide qué fechas releer (planificar):
   - «completo»: todas las fechas de timbradas_segmentos; también si no hay refresco anterior, si cambió la huella
     de los catálogos que fijan las dimensiones (rutas_segmentos, rutas, estacionalidades_anio) o, en modo «auto», si
     el último completo tiene más de SEGMENTOS_COMPLETO_DIAS días (así se recogen también las filas borradas);
   - «incremental» (lo normal en modo «auto»): la ventana de solape son las filas cuya marca ultimaactualizacion es
     posterior a la del refresco anterior menos FUENTE_SOLAPE_MIN (la marca de Extreme es la hora de inicio de su
     transacción, hallazgos H7 y H10). Desde la migración 0012 cada refresco deja las huellas por fecha de esa
     ventana (filas, sumas y una huella del contenido de cada grupo fecha × marca; huellas_ventana) y el siguiente
     solo relee las fechas cuyas huellas cambiaron, aparecieron o salieron de la ventana. Si la fuente no trae nada
     nuevo ni cambiado, termina «sin_cambios» sin reescribir nada (antes releía en cada ciclo todas las fechas de la
     ventana: en la réplica, 26 fechas y 164.206 filas). Sin huellas comparables (un refresco anterior a la 0012 u
     otro FUENTE_SOLAPE_MIN) relee todas las fechas de la ventana, como antes;
   - «rango»: las fechas pedidas (acotadas a las que existen en la fuente).
3. Lee de la fuente con el usuario de solo lectura (FuentePostgresSoloLectura: READ ONLY, statement_timeout de
   FUENTE_STATEMENT_TIMEOUT_MS, ROLLBACK) el grano diario segmento × fecha × hora por tramos de a lo sumo
   SEGMENTOS_DIAS_POR_LOTE días. Si un tramo agota el statement_timeout se parte solo: por mitades de fecha y, en un
   solo día, por ruta (RNF-005), hasta MAX_TIEMPOS_AGOTADOS veces por refresco; el tiempo agotado no cuenta como
   caída para el circuit breaker de la fuente. Cada tramo reemplaza sus fechas en segmento_estadistica_dia con COPY.
4. segmento_estadistica (grano de la respuesta) desde el grano diario, dentro de la base propia: un refresco completo
   la rehace entera; uno incremental o de rango solo vuelve a agregar las claves (segmento × estacionalidad × día ×
   hora) que tenían o traen las fechas releídas (reagregar_faltantes); el resto de la tabla no se toca.
5. Deja la marca del refresco (con las huellas de la ventana) en segmento_estadistica_refresco y cierra la ejecución
   con cola.cerrar_ok.
El progreso (etapa y porcentaje por tramo) se ve en GET /api/v1/frequency/executions/{execution_id}.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.config import obtener_ajustes
from app.db import sesion_contexto
from app.modelos_db import Ejecucion
from app.servicios import segmentos

log = logging.getLogger("api_frecuencias.segmentos")
ZONA = ZoneInfo("America/Bogota")
TIPO = "segmentos"
MODOS = ("auto", "completo", "incremental", "rango")
CLAVE_REFRESCO = 7_441_008       # pg_advisory_xact_lock: un refresco a la vez en todo el clúster
CLAVE_SOLICITUD = 7_441_009      # pg_advisory_xact_lock: «buscar uno en cola y si no, crear» es atómico
SQLSTATE_TIEMPO_AGOTADO = "57014"
# Tiempos agotados que tolera un refresco antes de rendirse (cada uno costó un statement_timeout en la fuente): más que
# esto ya no es un tramo grande sino una fuente sobrecargada, y el trabajo vuelve a la cola con su espera.
MAX_TIEMPOS_AGOTADOS = 12
# Nombre de la etapa de lectura (RNF-006): la etiqueta de api_ejecucion_etapa_segundos no lleva el tramo ni las fechas
# (cada refresco con otras fechas crearía una serie nueva); ese detalle va aparte (Avance) y queda en tramos_leidos.
ETAPA_LECTURA = "lectura_fuente"
Avance = Callable[..., None]      # avance(progreso, etapa, detalle=None)
COLUMNAS_DIA = ("id_segmento", "idruta", "nro_segmento", "fecha", "id_estacionalidad", "id_dia_semana", "hora",
                "nro_viajes", "suma_subidas", "max_subidas", "min_subidas", "suma_bajadas", "max_bajadas",
                "min_bajadas", "suma_pasajeros", "max_pasajeros", "min_pasajeros")

# ---------------------------------------------------------------- lecturas de la fuente (lista blanca, solo SELECT)
# Grano diario: la misma unidad (viaje × segmento × hora), la misma estacionalidad y el mismo día ISO que
# segmentos._SQL_ESTADISTICAS, sumados por fecha con medidas que se pueden volver a agregar sin perder exactitud.
# Cada fila sale como una línea CSV en el orden de COLUMNAS_DIA (la estacionalidad nula, campo vacío; la fecha en
# ISO con to_char, sin depender de DateStyle): PostgreSQL ya da el texto exacto de cada número, y el trabajo solo la
# pasa a COPY. Así no convierte cientos de miles de valores en objetos de Python (medido en un tramo de 31 días:
# 194 mil filas, unos 20 s de CPU de Python y 317 MiB con un DataFrame), que además le quitarían el GIL a las
# peticiones que atiende el mismo proceso mientras corre el refresco.
SQL_FUENTE_DIA = """
WITH por_viaje AS (
    SELECT ts.id_segmento, rs.idruta, rs.nro_segmento, ts.id_viaje, ts.fecha,
           CAST(EXTRACT(HOUR FROM ts.hora_inicio) AS integer) AS hora,
           SUM(ts.subidas) AS subidas, SUM(ts.bajadas) AS bajadas, MAX(ts.pasajeros) AS pasajeros
      FROM timbradas_segmentos ts
      JOIN rutas_segmentos rs ON rs.id = ts.id_segmento
     WHERE ts.fecha >= CAST(:desde AS date) AND ts.fecha <= CAST(:hasta AS date)
       AND (CAST(:idruta AS bigint) IS NULL OR rs.idruta = CAST(:idruta AS bigint))
     GROUP BY ts.id_segmento, rs.idruta, rs.nro_segmento, ts.id_viaje, ts.fecha,
              CAST(EXTRACT(HOUR FROM ts.hora_inicio) AS integer)
), estacion AS (
    SELECT f.fecha, f.idruta, ea.id_estacionalidad
      FROM (SELECT DISTINCT fecha, idruta FROM por_viaje) f
      LEFT JOIN LATERAL (
            SELECT e.id_estacionalidad
              FROM estacionalidades_anio e
              JOIN rutas r ON r.proceso = e.proceso AND r.idruta = f.idruta
             WHERE e.fecha_inicio <= f.fecha AND e.fecha_fin >= f.fecha
             ORDER BY (e.fecha_fin - e.fecha_inicio), e.fecha_inicio DESC, e.id_estacionalidad_anio DESC
             LIMIT 1) ea ON true
), dia AS (
    SELECT p.id_segmento, p.idruta, p.nro_segmento, p.fecha, es.id_estacionalidad,
           CAST(EXTRACT(ISODOW FROM p.fecha) AS integer) AS id_dia_semana, p.hora,
           COUNT(*) AS nro_viajes,
           SUM(p.subidas) AS suma_subidas, MAX(p.subidas) AS max_subidas, MIN(p.subidas) AS min_subidas,
           SUM(p.bajadas) AS suma_bajadas, MAX(p.bajadas) AS max_bajadas, MIN(p.bajadas) AS min_bajadas,
           SUM(p.pasajeros) AS suma_pasajeros, MAX(p.pasajeros) AS max_pasajeros, MIN(p.pasajeros) AS min_pasajeros
      FROM por_viaje p
      JOIN estacion es ON es.fecha = p.fecha AND es.idruta = p.idruta
     GROUP BY p.id_segmento, p.idruta, p.nro_segmento, p.fecha, es.id_estacionalidad, p.hora
)
SELECT concat_ws(',', id_segmento, idruta, nro_segmento, to_char(fecha, 'YYYY-MM-DD'),
                 COALESCE(CAST(id_estacionalidad AS text), ''), id_dia_semana, hora, nro_viajes,
                 suma_subidas, max_subidas, min_subidas, suma_bajadas, max_bajadas, min_bajadas,
                 suma_pasajeros, max_pasajeros, min_pasajeros) AS linea
  FROM dia
"""
SQL_FUENTE_RANGO = ("SELECT min(fecha) AS fecha_min, max(fecha) AS fecha_max, max(ultimaactualizacion) AS marca "
                    "FROM timbradas_segmentos")
# Ventana de solape (H7, H10): las filas con marca posterior a :marca (la del refresco anterior menos
# FUENTE_SOLAPE_MIN), en un grupo por fecha y marca con lo que permite decir si algo cambió desde ese refresco: filas,
# sumas de subidas, bajadas y pasajeros y una huella del contenido (suma de hashtext de cada fila, que no depende del
# orden ni obliga a ordenar). Es un solo recorrido de la tabla, como el SELECT de las fechas cambiadas de antes; en la
# réplica, unos 0,2 s para 1,26 millones de filas en la ventana.
SQL_FUENTE_VENTANA = """
SELECT fecha, ultimaactualizacion AS marca, count(*) AS filas, sum(subidas) AS subidas, sum(bajadas) AS bajadas,
       sum(pasajeros) AS pasajeros,
       sum(hashtext(concat_ws(':', id_segmento, id_viaje, hora_inicio, hora_fin, subidas, bajadas, pasajeros)))
           AS contenido
  FROM timbradas_segmentos
 WHERE ultimaactualizacion > :marca
 GROUP BY fecha, ultimaactualizacion
 ORDER BY fecha, ultimaactualizacion
"""
COLUMNAS_VENTANA = ("marca", "filas", "subidas", "bajadas", "pasajeros", "contenido")
VERSION_VENTANA = 1      # formato de huellas_solape; otra versión no se compara (se relee la ventana entera)
SQL_FUENTE_RUTAS = "SELECT DISTINCT idruta FROM rutas_segmentos ORDER BY idruta"
# Huella de lo que fija las dimensiones: si Extreme cambia un segmento, el proceso de una ruta o una vigencia de
# estacionalidad, la asignación ya materializada deja de valer y el refresco siguiente es completo.
SQL_FUENTE_HUELLA = """
SELECT md5(string_agg(t, '|' ORDER BY t)) AS huella FROM (
    SELECT 'S' || rs.id || ':' || rs.idruta || ':' || rs.nro_segmento AS t FROM rutas_segmentos rs
    UNION ALL
    SELECT 'R' || r.idruta || ':' || COALESCE(r.proceso, '') FROM rutas r
    UNION ALL
    SELECT 'E' || e.id_estacionalidad_anio || ':' || COALESCE(e.proceso, '') || ':' ||
           COALESCE(CAST(e.id_estacionalidad AS text), '') || ':' || COALESCE(CAST(e.fecha_inicio AS text), '') ||
           ':' || COALESCE(CAST(e.fecha_fin AS text), '')
      FROM estacionalidades_anio e
) x
"""

# ---------------------------------------------------------------- escrituras en el esquema propio
_COPY_DIA = ("COPY ai_frecuencias.segmento_estadistica_dia (" + ", ".join(COLUMNAS_DIA) +
             ", execution_id) FROM STDIN WITH (FORMAT csv)")
_SQL_BORRAR_DIA = text("DELETE FROM ai_frecuencias.segmento_estadistica_dia")
_SQL_BORRAR_DIA_TRAMO = text("DELETE FROM ai_frecuencias.segmento_estadistica_dia "
                             "WHERE fecha >= :desde AND fecha <= :hasta")
_SQL_BORRAR_RESPUESTA = text("DELETE FROM ai_frecuencias.segmento_estadistica")
# Las mismas medidas que la consulta por rango de fechas (segmentos.MEDIDAS_DESDE_DIA), sobre todo el grano diario
_PLANTILLA_RECONSTRUIR = ("INSERT INTO ai_frecuencias.segmento_estadistica ({columnas}) SELECT {llaves}, {medidas} "
                          "FROM ai_frecuencias.segmento_estadistica_dia GROUP BY {llaves}")
_SQL_RECONSTRUIR = text(_PLANTILLA_RECONSTRUIR.format(columnas=segmentos.COLUMNAS, llaves=segmentos.LLAVES,
                                                      medidas=segmentos.MEDIDAS_DESDE_DIA))
# Refresco parcial (incremental o rango): la clave del grano de la respuesta (la del índice único
# ux_segmento_estadistica_clave). Cada tramo saca de segmento_estadistica las claves que tenían sus fechas ANTES de
# reemplazarlas y las que traen DESPUÉS; al final se vuelven a agregar, desde todo el grano diario, las claves que
# quedaron sin fila (reagregar_faltantes). Como segmento_estadistica era la agregación exacta del grano diario, las
# demás claves no cambian: el resultado es el mismo que rehacer la tabla entera, sin reescribirla.
_MISMA_CLAVE = ("e.id_segmento = d.id_segmento AND COALESCE(e.id_estacionalidad, -1) = COALESCE(d.id_estacionalidad, "
                "-1) AND e.id_dia_semana = d.id_dia_semana AND e.hora = d.hora")
_PLANTILLA_SACAR = ("DELETE FROM ai_frecuencias.segmento_estadistica e WHERE EXISTS (SELECT 1 FROM "
                    "ai_frecuencias.segmento_estadistica_dia d WHERE d.fecha >= :desde AND d.fecha <= :hasta "
                    "AND {clave})")
_SQL_SACAR_CLAVES_DEL_TRAMO = text(_PLANTILLA_SACAR.format(clave=_MISMA_CLAVE))
_PLANTILLA_REAGREGAR =("INSERT INTO ai_frecuencias.segmento_estadistica ({columnas}) SELECT {llaves}, {medidas} "
                        "FROM ai_frecuencias.segmento_estadistica_dia d WHERE NOT EXISTS (SELECT 1 FROM "
                        "ai_frecuencias.segmento_estadistica e WHERE {clave}) GROUP BY {llaves}")
_SQL_REAGREGAR = text(_PLANTILLA_REAGREGAR.format(columnas=segmentos.COLUMNAS, llaves=segmentos.LLAVES,
                                                  medidas=segmentos.MEDIDAS_DESDE_DIA, clave=_MISMA_CLAVE))
_SQL_RESUMEN_DIA = text("SELECT count(*) AS filas_dia, min(fecha) AS fecha_min, max(fecha) AS fecha_max "
                        "FROM ai_frecuencias.segmento_estadistica_dia")
_SQL_FILAS_RESPUESTA = text("SELECT count(*) FROM ai_frecuencias.segmento_estadistica")
_SQL_REGISTRAR = text("""
INSERT INTO ai_frecuencias.segmento_estadistica_refresco
       (execution_id, modo, fecha_min, fecha_max, filas_dia, filas, fechas_releidas, marca_fuente, huella_catalogos,
        duracion_s, huellas_solape)
VALUES (:execution_id, :modo, :fecha_min, :fecha_max, :filas_dia, :filas, :fechas_releidas, :marca_fuente, :huella,
        :duracion_s, CAST(:huellas_solape AS jsonb))
RETURNING actualizado_en
""")


class ParametrosInvalidos(ValueError):
    """Parámetros del refresco que no tienen sentido (modo desconocido o rango mal formado)."""


@dataclass
class Plan:
    """Qué fechas se releen de la fuente, con qué marca queda el refresco y qué huellas de la ventana de solape deja
    para que el siguiente compare (`ventana`, la columna huellas_solape)."""

    modo: str                                   # completo | incremental | rango | sin_cambios
    tramos: list[tuple[date, date]] = field(default_factory=list)
    borrar_todo: bool = False
    marca: datetime | None = None
    huella: str | None = None
    ventana: dict | None = None
    detalle: dict = field(default_factory=dict)

    @property
    def fechas(self) -> int:
        return sum((h - d).days + 1 for d, h in self.tramos)


# ---------------------------------------------------------------- parámetros y tramos
def _fecha(valor: Any) -> date | None:
    if valor is None or valor == "":
        return None
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    return date.fromisoformat(str(valor)[:10])


def validar_parametros(parametros: dict[str, Any] | None) -> dict[str, Any]:
    """{modo, desde, hasta} normalizados. «rango» exige desde ≤ hasta; los demás modos no llevan fechas."""
    p = dict(parametros or {})
    modo = p.get("modo") or "auto"
    if modo not in MODOS:
        raise ParametrosInvalidos(f"modo debe ser uno de {', '.join(MODOS)}")
    try:
        desde, hasta = _fecha(p.get("desde")), _fecha(p.get("hasta"))
    except ValueError as exc:
        raise ParametrosInvalidos(f"fecha inválida: {exc}") from exc
    if modo == "rango" and (desde is None or hasta is None or desde > hasta):
        raise ParametrosInvalidos("el modo rango exige desde y hasta, con desde no posterior a hasta")
    if modo != "rango" and (desde is not None or hasta is not None):
        raise ParametrosInvalidos("desde y hasta solo se usan con modo rango")
    return {"modo": modo, "desde": desde, "hasta": hasta}


def partir(desde: date, hasta: date, dias: int) -> list[tuple[date, date]]:
    """[desde, hasta] en tramos consecutivos de a lo sumo `dias` días."""
    tramos, inicio, paso = [], desde, max(1, int(dias))
    while inicio <= hasta:
        fin = min(hasta, inicio + timedelta(days=paso - 1))
        tramos.append((inicio, fin))
        inicio = fin + timedelta(days=1)
    return tramos


def tramos_contiguos(fechas, dias: int) -> list[tuple[date, date]]:
    """Fechas sueltas -> tramos de días seguidos (sin incluir los huecos), cada uno de a lo sumo `dias` días."""
    ordenadas = sorted({_fecha(f) for f in fechas if f is not None})
    corridas: list[list[date]] = []
    for f in ordenadas:
        if corridas and f == corridas[-1][-1] + timedelta(days=1):
            corridas[-1].append(f)
        else:
            corridas.append([f])
    return [t for c in corridas for t in partir(c[0], c[-1], dias)]


def _con_zona(valor: Any) -> datetime | None:
    """Marca de la fuente (timestamp sin zona, hora de Bogotá) -> instante con zona."""
    if valor is None or (isinstance(valor, float) and pd.isna(valor)) or valor is pd.NaT:
        return None
    if isinstance(valor, pd.Timestamp):
        valor = valor.to_pydatetime()
    return valor if valor.tzinfo else valor.replace(tzinfo=ZONA)


def _uno(df: pd.DataFrame, columna: str) -> Any:
    return df[columna].iloc[0] if len(df) and columna in df.columns else None


# ---------------------------------------------------------------- huellas de la ventana de solape
def _valor_huella(valor: Any) -> str:
    """Texto canónico de un valor de la ventana: la marca como instante UTC y los números enteros sin decimales."""
    if isinstance(valor, (datetime, pd.Timestamp)):
        return _con_zona(valor).astimezone(UTC).isoformat()
    if valor is None or (isinstance(valor, float) and math.isnan(valor)):
        return "∅"
    if isinstance(valor, (int, float, Decimal)) and float(valor).is_integer():
        return str(int(valor))
    return str(valor)


def _marcas(ventana: pd.DataFrame | None) -> list[datetime]:
    """Las marcas (con zona) de los grupos de la ventana."""
    if ventana is None or "marca" not in ventana.columns:
        return []
    return [m for m in (_con_zona(x) for x in ventana["marca"]) if m is not None]


def huellas_ventana(ventana: pd.DataFrame | None, desde: datetime | None = None) -> dict[str, str]:
    """{fecha ISO: huella} de la ventana de solape: md5 (16 hex) de los grupos fecha × marca de cada fecha (marca,
    filas, sumas y contenido, en orden), solo con los grupos de marca posterior a `desde` (todos si es None). Una fila
    nueva, cambiada (Extreme le vuelve a poner la marca) o borrada dentro de la ventana cambia la huella de su fecha."""
    if ventana is None or ventana.empty or "fecha" not in ventana.columns:
        return {}
    columnas = [c for c in COLUMNAS_VENTANA if c in ventana.columns]
    grupos: dict[str, list[str]] = {}
    for fila in ventana.to_dict(orient="records"):
        marca = _con_zona(fila.get("marca"))
        if desde is not None and (marca is None or marca <= desde):
            continue
        grupos.setdefault(_fecha(fila["fecha"]).isoformat(), []).append(
            "|".join(_valor_huella(fila.get(c)) for c in columnas))
    return {f: hashlib.md5("\n".join(sorted(g)).encode("utf-8"), usedforsecurity=False).hexdigest()[:16]
            for f, g in sorted(grupos.items())}


def referencia_ventana(ventana: pd.DataFrame | None, marca: datetime | None, solape_min: int) -> dict | None:
    """Lo que el refresco deja para que el siguiente compare (columna huellas_solape): la ventana que empieza en su
    marca menos el solape y sus huellas por fecha. None sin marca (fuente vacía)."""
    if marca is None:
        return None
    solape = max(0, int(solape_min))
    desde = marca - timedelta(minutes=solape)
    return {"version": VERSION_VENTANA, "solape_min": solape, "desde": desde.isoformat(),
            "fechas": huellas_ventana(ventana, desde)}


def _referencia_previa(previo: dict, solape_min: int) -> dict[str, str] | None:
    """Las huellas que dejó el refresco anterior, si sirven para comparar con las de ahora: la misma versión, el mismo
    solape y la ventana que empieza en su marca menos ese solape. None si no sirven (se relee la ventana entera)."""
    ref, marca = previo.get("huellas_solape"), previo.get("marca_fuente")
    if not isinstance(ref, dict) or marca is None or not isinstance(ref.get("fechas"), dict):
        return None
    solape = max(0, int(solape_min))
    try:
        desde = datetime.fromisoformat(str(ref.get("desde")))
    except ValueError:
        return None
    comparable = (ref.get("version") == VERSION_VENTANA and ref.get("solape_min") == solape
                  and desde == marca - timedelta(minutes=solape))
    return dict(ref["fechas"]) if comparable else None


def fechas_cambiadas(actuales: dict[str, str], previas: dict[str, str] | None) -> list[date]:
    """Fechas a releer: sin huellas previas comparables, todas las de la ventana; con ellas, las que entran, cambian o
    salen de la ventana (una que sale perdió filas: también se relee)."""
    if previas is None:
        return sorted(date.fromisoformat(f) for f in actuales)
    return sorted(date.fromisoformat(f) for f in set(actuales) | set(previas) if actuales.get(f) != previas.get(f))


def _json_ventana(ventana: dict | None) -> str | None:
    return None if ventana is None else json.dumps(ventana, ensure_ascii=False, sort_keys=True)


# ---------------------------------------------------------------- plan del refresco
def _requiere_completo(modo: str, previo: dict | None, huella: str | None, completo_dias: int,
                       ahora: datetime) -> str | None:
    """Motivo para un refresco completo, o None si alcanza con el incremental (o el rango pedido)."""
    if modo == "completo":
        return "pedido"
    if previo is None:
        return "sin_refresco_anterior"
    if previo.get("huella_catalogos") != huella:
        return "cambiaron_los_catalogos"
    if previo.get("marca_fuente") is None:
        return "sin_marca_anterior"
    ultimo = previo.get("ultimo_completo")
    if modo == "auto" and (ultimo is None or ahora - ultimo > timedelta(days=completo_dias)):
        return "periodico"
    return None


def _rango_fuente(fuente) -> tuple[date | None, date | None, datetime | None]:
    """(primera fecha, última fecha, marca más reciente) de timbradas_segmentos."""
    rango = fuente.consultar(SQL_FUENTE_RANGO)
    return _fecha(_uno(rango, "fecha_min")), _fecha(_uno(rango, "fecha_max")), _con_zona(_uno(rango, "marca"))


def _leer_ventana(fuente, marca: datetime | None, solape_min: int) -> pd.DataFrame | None:
    """Los grupos fecha × marca de la ventana que empieza en `marca` menos el solape (None sin marca)."""
    if marca is None:
        return None
    return fuente.consultar(SQL_FUENTE_VENTANA, {"marca": marca - timedelta(minutes=max(0, solape_min))})


def _plan_completo(fuente, huella: str | None, dias: int, solape_min: int) -> Plan:
    """Todas las fechas de la fuente; deja las huellas de la ventana de su marca para que el incremental siguiente
    compare (sin ellas, el primero después de cada completo volvería a leer la ventana entera)."""
    inicio, fin, marca = _rango_fuente(fuente)
    tramos = partir(inicio, fin, dias) if inicio and fin else []
    ventana = _leer_ventana(fuente, marca, solape_min)
    return Plan("completo", tramos, borrar_todo=True, marca=marca, huella=huella,
                ventana=referencia_ventana(ventana, marca, solape_min))


def _plan_rango(fuente, previo: dict, p: dict, huella: str | None, dias: int) -> Plan:
    """Las fechas pedidas; la marca y las huellas de la ventana siguen siendo las del refresco anterior."""
    inicio, fin, _marca = _rango_fuente(fuente)
    desde, hasta = max(p["desde"], inicio or p["desde"]), min(p["hasta"], fin or p["hasta"])
    tramos = partir(desde, hasta, dias) if desde <= hasta else []
    return Plan("rango", tramos, marca=previo.get("marca_fuente"), huella=huella, ventana=previo.get("huellas_solape"))


def _plan_incremental(fuente, previo: dict, huella: str | None, dias: int, solape_min: int) -> Plan:
    """Solo las fechas de la ventana de solape cuyas huellas cambiaron desde el refresco anterior; sin ninguna,
    «sin_cambios» (no se relee ni se reescribe nada). La marca nueva es la mayor de la ventana."""
    marca = previo["marca_fuente"]
    ventana = _leer_ventana(fuente, marca, solape_min)
    nueva = max([marca, *_marcas(ventana)])
    previas = _referencia_previa(previo, solape_min)
    actuales = huellas_ventana(ventana)
    fechas = fechas_cambiadas(actuales, previas)
    detalle = {"fechas_en_ventana": len(actuales), "comparada_con_el_refresco_anterior": previas is not None,
               "fechas_cambiadas": len(fechas)}
    referencia = referencia_ventana(ventana, nueva, solape_min)
    if not fechas:
        return Plan("sin_cambios", marca=nueva, huella=huella, ventana=referencia, detalle=detalle)
    return Plan("incremental", tramos_contiguos(fechas, dias), marca=nueva, huella=huella, ventana=referencia,
                detalle=detalle)


def planificar(fuente, previo: dict | None, parametros: dict[str, Any], *, dias_por_lote: int, completo_dias: int,
               solape_min: int, ahora: datetime | None = None) -> Plan:
    """Decide el modo efectivo y los tramos de fechas a releer (ver el docstring del módulo)."""
    p = validar_parametros(parametros)
    huella = _uno(fuente.consultar(SQL_FUENTE_HUELLA), "huella")
    motivo = _requiere_completo(p["modo"], previo, huella, completo_dias, ahora or datetime.now(ZONA))
    if motivo is not None:
        plan = _plan_completo(fuente, huella, dias_por_lote, solape_min)
        plan.detalle = {"motivo_completo": motivo}
        log.info("Refresco de segmentos completo (%s): %s tramos", motivo, len(plan.tramos))
        return plan
    if p["modo"] == "rango":
        return _plan_rango(fuente, previo, p, huella, dias_por_lote)
    return _plan_incremental(fuente, previo, huella, dias_por_lote, solape_min)


# ---------------------------------------------------------------- lectura por tramos con partición automática
def es_tiempo_agotado(exc: BaseException) -> bool:
    """¿La fuente canceló la sentencia por statement_timeout (SQLSTATE 57014)?"""
    vistos = set()
    actual: BaseException | None = exc
    while actual is not None and id(actual) not in vistos:
        vistos.add(id(actual))
        if getattr(actual, "sqlstate", None) == SQLSTATE_TIEMPO_AGOTADO:
            return True
        actual = getattr(actual, "orig", None) or actual.__cause__
    return False


def _mitades(fuente, desde: date, hasta: date, idruta: int | None) -> list[tuple[date, date, int | None]]:
    """Cómo partir un tramo que no cupo en el statement_timeout: dos mitades de fechas o, en un día, por ruta."""
    if desde < hasta:
        medio = desde + timedelta(days=(hasta - desde).days // 2)
        return [(desde, medio, idruta), (medio + timedelta(days=1), hasta, idruta)]
    if idruta is None:
        rutas = fuente.consultar(SQL_FUENTE_RUTAS)
        return [(desde, hasta, int(r)) for r in rutas.get("idruta", [])]
    return []


@dataclass
class Particion:
    """Tiempos agotados que el refresco todavía tolera; lo comparten todos los tramos de un mismo refresco."""

    restantes: int = MAX_TIEMPOS_AGOTADOS


def leer_tramo(fuente, desde: date, hasta: date, idruta: int | None = None,
               particion: Particion | None = None) -> list[pd.DataFrame]:
    """El grano diario de [desde, hasta] (y de una ruta, si se pide). Si la sentencia agota el statement_timeout de
    la fuente, el tramo se parte y se lee por partes, a lo sumo MAX_TIEMPOS_AGOTADOS veces por refresco; cualquier
    otro error, o un tiempo agotado pasado ese tope, sube (el trabajo vuelve a la cola con su espera).

    La fuente de la capa de segmentos (segmentos.fuente) informa el tiempo agotado como SentenciaCancelada, que el
    circuit breaker no cuenta como caída: así partir un tramo no abre el circuito compartido de la fuente (que
    también usan la ingesta y los catálogos) ni corta la partición al tercer tiempo agotado seguido."""
    particion = particion if particion is not None else Particion()
    try:
        return [fuente.consultar(SQL_FUENTE_DIA, {"desde": desde, "hasta": hasta, "idruta": idruta})]
    except Exception as exc:  # noqa: BLE001 - solo el tiempo agotado se maneja aquí; lo demás se vuelve a lanzar
        se_parte = es_tiempo_agotado(exc) and particion.restantes > 0
        partes = _mitades(fuente, desde, hasta, idruta) if se_parte else []
        if not partes:
            raise
    particion.restantes -= 1
    log.warning("Tramo %s a %s (ruta %s) superó el statement_timeout de la fuente: se lee en %s partes", desde, hasta,
                idruta if idruta is not None else "todas", len(partes))
    return [df for d, h, r in partes for df in leer_tramo(fuente, d, h, r, particion)]


# ---------------------------------------------------------------- escritura en el esquema propio
def csv_dia(lineas, execution_id: uuid.UUID | None) -> str:
    """Las líneas del grano diario que arma la fuente, más la ejecución que las escribe, como CSV para COPY."""
    sufijo = f",{execution_id}\n" if execution_id else ",\n"
    return "".join(f"{linea}{sufijo}" for linea in lineas)


def copiar_dia(s: Session, df: pd.DataFrame, execution_id: uuid.UUID | None) -> int:
    """COPY de las filas del grano diario en la transacción de la sesión (si el intento falla, no queda nada)."""
    if df is None or df.empty:
        return 0
    s.flush()
    cruda = s.connection().connection.driver_connection
    if type(cruda).__module__.split(".")[0] != "psycopg":   # pragma: no cover - el proyecto usa psycopg 3
        raise RuntimeError("El refresco de segmentos necesita el driver psycopg 3 (COPY)")
    with cruda.cursor() as cur, cur.copy(_COPY_DIA) as copia:
        copia.write(csv_dia(df["linea"], execution_id))
    return len(df)


def _reemplazar_tramo(s: Session, plan: Plan, desde: date, hasta: date, marcos: list[pd.DataFrame],
                      execution_id: uuid.UUID | None) -> int:
    """Las fechas del tramo en el grano diario. En un refresco parcial (incremental o rango) también saca de
    segmento_estadistica las claves que tenían esas fechas y las que traen: reagregar_faltantes las vuelve a agregar."""
    rango = {"desde": desde, "hasta": hasta}
    if not plan.borrar_todo:
        s.execute(_SQL_SACAR_CLAVES_DEL_TRAMO, rango)
        s.execute(_SQL_BORRAR_DIA_TRAMO, rango)
    filas = sum(copiar_dia(s, df, execution_id) for df in marcos)
    if not plan.borrar_todo:
        s.execute(_SQL_SACAR_CLAVES_DEL_TRAMO, rango)
    return filas


def _releer(s: Session, fuente, plan: Plan, execution_id: uuid.UUID | None, avance: Avance
            ) -> tuple[int, list[dict[str, Any]]]:
    """Relee los tramos del plan. Devuelve las filas leídas y el detalle de cada tramo (fechas, filas, partes en que se
    partió por el statement_timeout y segundos), que queda en las métricas del trabajo y en el log; la etapa del
    avance es siempre «lectura_fuente» (su detalle, el tramo y las fechas, solo va a la columna etapa del trabajo)."""
    if plan.borrar_todo:
        s.execute(_SQL_BORRAR_DIA)
    filas, particion, tramos = 0, Particion(), []
    for i, (desde, hasta) in enumerate(plan.tramos, start=1):
        t0 = time.perf_counter()
        marcos = leer_tramo(fuente, desde, hasta, particion=particion)
        leidas = _reemplazar_tramo(s, plan, desde, hasta, marcos, execution_id)
        filas += leidas
        tramos.append({"tramo": f"{i}/{len(plan.tramos)}", "desde": desde, "hasta": hasta, "filas": leidas,
                       "partes": len(marcos), "segundos": round(time.perf_counter() - t0, 3)})
        log.info("Refresco de segmentos %s: tramo %s/%s (%s a %s), %s filas en %s parte(s), %.1f s", execution_id,
                 i, len(plan.tramos), desde, hasta, leidas, len(marcos), tramos[-1]["segundos"])
        avance(10 + 75 * i / len(plan.tramos), ETAPA_LECTURA, f"{i}/{len(plan.tramos)} ({desde} a {hasta})")
    return filas, tramos


def reconstruir(s: Session) -> int:
    """segmento_estadistica (grano de la respuesta) desde el grano diario, sin leer la base de Extreme."""
    s.execute(_SQL_BORRAR_RESPUESTA)
    return int(s.execute(_SQL_RECONSTRUIR).rowcount or 0)


def reagregar_faltantes(s: Session) -> int:
    """Refresco parcial: vuelve a agregar desde el grano diario solo las claves de segmento_estadistica que quedaron
    sin fila (las de las fechas releídas, _reemplazar_tramo). Devuelve las filas escritas."""
    return int(s.execute(_SQL_REAGREGAR).rowcount or 0)


def _agregar(s: Session, plan: Plan, avance: Avance) -> int:
    """El grano de la respuesta tras releer: entero en un completo, solo lo de las fechas releídas en un parcial y
    nada si no se releyó ninguna fecha («sin_cambios» o un rango fuera de la fuente). Devuelve las filas escritas."""
    if not (plan.borrar_todo or plan.tramos):
        return 0
    avance(88, "agregacion")
    return reconstruir(s) if plan.borrar_todo else reagregar_faltantes(s)


def _registrar(s: Session, execution_id: uuid.UUID | None, plan: Plan, lectura: tuple[int, list[dict[str, Any]]],
               t0: float, reescritas: int = 0) -> dict:
    filas_leidas, tramos_leidos = lectura
    resumen = dict(s.execute(_SQL_RESUMEN_DIA).mappings().one())
    filas = int(s.execute(_SQL_FILAS_RESPUESTA).scalar() or 0)
    datos = {"execution_id": execution_id, "modo": plan.modo, "fecha_min": resumen["fecha_min"],
             "fecha_max": resumen["fecha_max"], "filas_dia": int(resumen["filas_dia"]), "filas": filas,
             "fechas_releidas": plan.fechas, "marca_fuente": plan.marca, "huella": plan.huella,
             "duracion_s": round(time.perf_counter() - t0, 3)}
    actualizado_en = s.execute(_SQL_REGISTRAR, {**datos, "huellas_solape": _json_ventana(plan.ventana)}).scalar()
    return {**datos, "actualizado_en": actualizado_en, "tramos": len(plan.tramos), "filas_leidas": filas_leidas,
            "tramos_leidos": tramos_leidos, "filas_respuesta_reescritas": reescritas, "ventana": plan.detalle}


def _sin_avance(_progreso: float, _etapa: str, _detalle: str | None = None) -> None:
    """Avance nulo para llamadas fuera de la cola (pruebas y guiones)."""


def refrescar(s: Session, fuente, execution_id: uuid.UUID | None = None, parametros: dict[str, Any] | None = None,
              avance: Avance = _sin_avance) -> dict[str, Any]:
    """Refresca la agregación en la transacción de `s` (no la confirma: lo hace quien llama, con la cerca de la cola).

    Devuelve el resumen que queda en las métricas de la ejecución: modo efectivo, tramos (con el detalle de cada uno
    en tramos_leidos), fechas releídas, filas leídas, filas de los dos granos, período cubierto, marca de la fuente y
    duración. `avance(progreso, etapa, detalle)` recibe siempre el nombre de la etapa (planificacion, lectura_fuente,
    agregacion, registro: la etiqueta acotada de la métrica api_ejecucion_etapa_segundos) y aparte su detalle."""
    aj = obtener_ajustes()
    t0 = time.perf_counter()
    s.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": CLAVE_REFRESCO})
    previo = segmentos.ultimo_refresco(s)
    plan = planificar(fuente, previo, parametros or {}, dias_por_lote=aj.segmentos_dias_por_lote,
                      completo_dias=aj.segmentos_completo_dias, solape_min=aj.fuente_solape_min)
    avance(10, ETAPA_LECTURA, f"({plan.modo}, {len(plan.tramos)} tramos)")
    lectura = _releer(s, fuente, plan, execution_id, avance)
    reescritas = _agregar(s, plan, avance)
    avance(95, "registro")
    return _registrar(s, execution_id, plan, lectura, t0, reescritas)


# ---------------------------------------------------------------- el trabajo de la cola
def _avance_de(execution_id: uuid.UUID) -> Avance:
    from app.servicios import ejecucion

    def avanzar(progreso: float, etapa: str, detalle: str | None = None) -> None:
        ejecucion._avance(execution_id, round(progreso, 2), etapa, detalle=detalle)

    return avanzar


def _mensaje(resumen: dict[str, Any]) -> str:
    if resumen["modo"] == "sin_cambios":
        return "Agregación de segmentos al día: la fuente no trae cambios desde el refresco anterior"
    return (f"Agregación de segmentos {resumen['modo']}: {resumen['fechas_releidas']} fechas releídas en "
            f"{resumen['tramos']} tramos, {resumen['filas']} filas")


def _refrescar_en_cola(execution_id: uuid.UUID) -> None:
    from app.servicios import cola, ejecucion

    with sesion_contexto() as s:
        parametros = dict(s.get(Ejecucion, execution_id).parametros or {})
    try:
        validar_parametros(parametros)
        lectura = segmentos.fuente()
    except (ParametrosInvalidos, segmentos.FuenteNoConfigurada) as exc:
        raise ejecucion.ErrorNoReintentable(str(exc)) from exc   # ni la configuración ni el pedido mejoran solos
    ejecucion._avance(execution_id, 5, "planificacion")
    with sesion_contexto() as s:
        resumen = refrescar(s, lectura, execution_id, parametros, _avance_de(execution_id))
        cola.cerrar_ok(s, execution_id, dict(
            estado="ok", etapa="terminada", progreso=100, filas_leidas=resumen["filas_leidas"],
            filas_validas=resumen["filas_leidas"], metricas=ejecucion.json_seguro(resumen),
            mensaje=_mensaje(resumen), terminado_en=ejecucion.ahora(), actualizado_en=ejecucion.ahora()))


def ciclo_refresco(execution_id: uuid.UUID) -> None:
    """Trabajo «segmentos» de la cola. RNF-006: corre en el span «ejecucion.ciclo_segmentos», que continúa la traza
    de quien lo encoló."""
    from app.observabilidad import ejecucion_en_curso

    with ejecucion_en_curso(execution_id, TIPO):
        _refrescar_en_cola(execution_id)


# ---------------------------------------------------------------- encolar sin duplicar
def _misma_solicitud(e: Ejecucion, parametros: dict[str, Any]) -> bool:
    previos = e.parametros or {}
    return all(str(previos.get(k) or "") == str(parametros.get(k) or "") for k in ("modo", "desde", "hasta"))


def solicitar(s: Session, parametros: dict[str, Any], correlation_id: str | None = None, *,
              cualquiera_en_curso: bool = False) -> tuple[Ejecucion, bool]:
    """Encola un refresco {modo, desde, hasta, origen} y devuelve (ejecución, nueva).

    Si ya hay uno igual en cola, devuelve ese. Con cualquiera_en_curso (la consulta que encontró la agregación vacía)
    sirve cualquier refresco en cola o corriendo. Lanza FuenteNoConfigurada sin la base operacional.

    Buscar y crear van bajo un candado de asesoría de transacción (CLAVE_SOLICITUD): sin él, varias peticiones
    simultáneas (p. ej. muchas consultas que encuentran la agregación vacía justo después de desplegar) veían la cola
    vacía a la vez y encolaban un refresco cada una. El candado se suelta al confirmar (crear_ejecucion confirma)."""
    from app.servicios import ejecucion

    if not segmentos.fuente_configurada():
        raise segmentos.FuenteNoConfigurada(segmentos.MENSAJE_SIN_FUENTE)
    p = validar_parametros(parametros)
    solicitud = {**parametros, "modo": p["modo"], "desde": p["desde"] and p["desde"].isoformat(),
                 "hasta": p["hasta"] and p["hasta"].isoformat()}
    s.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": CLAVE_SOLICITUD})
    estados = ("en_cola", "corriendo") if cualquiera_en_curso else ("en_cola",)
    existentes = s.scalars(select(Ejecucion).where(Ejecucion.tipo == TIPO, Ejecucion.estado.in_(estados))
                           .order_by(Ejecucion.creado_en)).all()
    for e in existentes:
        if cualquiera_en_curso or _misma_solicitud(e, solicitud):
            s.commit()           # sin escrituras: solo suelta el candado (los objetos siguen cargados)
            return e, False
    return ejecucion.crear_ejecucion(s, TIPO, solicitud, correlation_id), True


def encolar_tras_ciclo(execution_id_ciclo: uuid.UUID) -> uuid.UUID | None:
    """El ciclo de frecuencia trajo datos nuevos: refresco «auto» en cola (si hay base operacional y no hay otro)."""
    if not segmentos.fuente_configurada():
        return None
    from app.observabilidad import span

    # RNF-006: span propio. crear_ejecucion anota el execution_id del refresco en el span actual, que aquí sería la
    # última etapa del ciclo de frecuencia: esa etapa quedaba en las trazas con el id de OTRA ejecución.
    with span("ejecucion.encolar_refresco_segmentos", ciclo=str(execution_id_ciclo)), sesion_contexto() as s:
        e, nueva = solicitar(s, {"modo": "auto", "origen": "ciclo", "ciclo": str(execution_id_ciclo)})
        log.info("Refresco de segmentos tras el ciclo %s: %s", execution_id_ciclo,
                 f"encolado {e.execution_id}" if nueva else f"ya estaba en cola ({e.execution_id})")
        return e.execution_id


__all__ = ["TIPO", "MODOS", "refrescar", "planificar", "leer_tramo", "partir", "tramos_contiguos", "solicitar",
           "ciclo_refresco", "encolar_tras_ciclo", "validar_parametros", "ParametrosInvalidos", "Plan", "Particion",
           "es_tiempo_agotado", "reconstruir", "reagregar_faltantes", "copiar_dia", "huellas_ventana",
           "referencia_ventana", "fechas_cambiadas", "SQL_FUENTE_VENTANA"]
