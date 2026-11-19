"""Retención automática de datos (§18 «Exposición de datos → minimización, control de acceso, retención y
anonimización»): un trabajo de la cola de tipo «retencion» (migración 0012) que aplica la política documentada.

La política es la de EntregaFinal/PLAN_EVOLUCION.md (§2, «Particionamiento»: 13 meses en caliente; las particiones
viejas se separan con DETACH PARTITION) y la de la especificación técnica E02 («Retención: particiones mensuales con
DETACH/DROP en la tabla de mayor volumen»), extendida a las demás tablas que crecen. Sus parámetros son gobernados:
viven en threshold_config (PARAMETROS; los siembra la migración 0012), GET /thresholds los muestra con su historial y
PUT /thresholds los cambia (rol admin, auditado y aprobable), con la validación de validar_parametros.

Grupos (cada uno con sus meses en caliente; lo anterior al corte):
- foto (retencion_meses_foto): feature_snapshot, la tabla de mayor volumen (≈ 0,47 MB por ejecución con las filas
  por segmento y sentido, ≈ 14 MB por mes con una ejecución diaria). Cada partición mensual cuyo rango termina antes
  del corte, cuyas filas se crearon todas antes del corte y en la que ninguna foto es de una predicción que la regla
  de resultados de la misma corrida conserva (una foto vive lo que vive su predicción: la predicción vieja que sostiene
  una recomendación posterior al corte conserva su partición; con retencion_meses_resultados = 0 se conservan todas
  las predicciones y con ellas sus fotos) se separa (DETACH PARTITION) y se borra (DROP); con
  retencion_archivar_particiones = 1 queda como <partición>_archivo (si ese nombre ya existe porque el mismo mes se
  archivó antes, <partición>_archivo_2, _3…) para archivarla con pg_dump, SIN las llaves foráneas que clonó de
  feature_snapshot (a prediction y a execution_log, ON DELETE CASCADE): con ellas, borrar después su predicción o su
  ejecución vieja (las reglas de resultados y de ejecuciones, en la misma corrida) vaciaría el archivo en cascada.
- resultados (retencion_meses_resultados): recommendation, prediction (con su foto por llave foránea),
  prediction_corto_plazo, respuesta_reto y segmento_estadistica_refresco (menos la última marca y la del último
  completo), por su fecha de creación.
- alertas (retencion_meses_alertas): notification_log por fecha y las alertas cerradas o descartadas por su última
  actualización, con su historial; una alerta abierta nunca se borra.
- ejecuciones (retencion_meses_ejecuciones): execution_log «ok» o «error» con sus intentos, errores de calidad y filas
  de monitoreo, solo las que ya no sostienen nada (ni una marca de agua, ni un modelo, ni el histórico validado, ni un
  resultado o una alerta que se conserva, ni un trabajo por ruta que se conserva) y nunca la última de cada tipo.
- derivada: segmento_estadistica_dia y segmento_estadistica se conservan. Son derivadas de timbradas_segmentos: el
  refresco las iguala a la fuente y el completo periódico las recalcula, así que su retención es la de Extreme; la
  bitácora deja sus filas, su período y su tamaño en cada corrida.

Se conservan siempre: demanda_observada (histórico validado del reentrenamiento, RF-018), ocupacion_segmento (la
ocupación observada por segmento de §10.1, sin datos personales), model_registry y threshold_config (auditoría de
modelos y de parámetros), marca_agua_ruta y marca_agua_tabla (estado de la lectura incremental por ruta y de los
consolidados de Extreme por tabla; la ejecución que movió una marca tampoco se borra, porque su llave foránea ON DELETE
CASCADE se llevaría la marca) y retencion_registro (esta bitácora).
0 meses en un grupo = ese grupo no se recorta.

Corte: el instante de la corrida menos N meses del calendario de Bogotá (corte()). Cada acción va en su propia
transacción corta, con su fila en retencion_registro: una partición, o un lote de LOTE_FILAS filas de una tabla (la fila
de bitácora de la tabla se actualiza en la transacción de cada lote, así que siempre dice lo que de verdad se borró).
Separar una partición pide candados sobre feature_snapshot y sobre las tablas a las que apunta su llave foránea (el
DETACH, ShareRowExclusive sobre prediction y execution_log; el DROP o quitar las llaves del archivo, AccessExclusive);
con lock_timeout = ESPERA_CANDADO, menor que deadlock_timeout, si un ciclo los tiene la acción queda «pospuesta» para la
corrida siguiente, nadie espera de más y PostgreSQL nunca aborta al ciclo por un interbloqueo. Todo es idempotente
(borrar lo anterior al corte dos veces no borra más): si la réplica pierde la reserva (se verifica antes de cada
acción), la que retoma el trabajo sigue donde quedó.

Simulación (simular = true, la opción por omisión de POST /api/v1/retencion/aplicar y la de la corrida programada si
retencion_aplicar_programada = 0): las particiones se planifican sin tocarlas y las filas se cuentan con los mismos
DELETE, en el mismo orden, dentro de UNA transacción que se revierte (cuenta exactamente lo que se borraría, también lo
que solo queda libre al borrar lo de la regla anterior). Nada se borra; la bitácora queda con simulado = true.

Solo toca el esquema ai_frecuencias: todo el SQL es constante (lista blanca), y los nombres de las particiones salen del
catálogo (pg_inherits de ai_frecuencias.feature_snapshot), se validan con NOMBRE_PARTICION y van entre comillas (los de
las llaves foráneas del archivo, de pg_constraint, con NOMBRE_RESTRICCION).
"""
from __future__ import annotations

import calendar
import logging
import re
import time
import uuid
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.db import sesion_contexto
from app.modelos_db import Ejecucion, RegistroRetencion

log = logging.getLogger("api_frecuencias.retencion")
ZONA = ZoneInfo("America/Bogota")
TIPO = "retencion"
CLAVE_RETENCION = 7_441_014          # pg_advisory_xact_lock: una acción de retención a la vez en todo el clúster
LOTE_FILAS = 5_000
# lock_timeout al separar una partición (constante: no hay texto externo en el SET). Menor que deadlock_timeout (1 s
# por omisión): si un ciclo que ya leyó execution_log espera a la retención entre el DETACH y el DROP, quien primero
# cumple deadlock_timeout es abortado; así cede siempre la retención y no el ciclo (en PostgreSQL 14, con 2 s el ciclo
# caía por «deadlock detected»), como monitoreo.ESPERA_LOCK_PARTICION.
ESPERA_CANDADO = "500ms"
NOMBRE_PARTICION = re.compile(r"^feature_snapshot_[0-9]{6}$")    # las que crea asegurar_particion_feature_snapshot
# <partición>_archivo y, si el mismo mes se vuelve a archivar, <partición>_archivo_2, _3… (nombre_de_archivo)
NOMBRE_ARCHIVO = re.compile(r"^feature_snapshot_[0-9]{6}_archivo(_[0-9]{1,4})?$")
NOMBRE_RESTRICCION = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")      # llaves foráneas del archivo (de pg_constraint)
MESES_MINIMO, MESES_MAXIMO = 3, 120  # menos de 3 meses rompería la ventana del monitoreo, la sombra y el conformal

# nombre: (valor por omisión, descripción). La migración 0012 los copia (una prueba verifica que coinciden).
PARAMETROS: dict[str, tuple[int, str]] = {
    "retencion_meses_foto": (13, "§18 retención: meses en caliente de feature_snapshot. Las particiones mensuales "
                                 "enteras anteriores al corte se separan (DETACH PARTITION) y se borran (DROP) o se "
                                 "archivan; 0 = no se recorta"),
    "retencion_meses_resultados": (13, "§18 retención: meses de prediction, recommendation, respuesta_reto y "
                                       "segmento_estadistica_refresco (por su fecha de creación); lo que cuelga de "
                                       "ellas por llave foránea se borra con ellas; 0 = no se recorta"),
    "retencion_meses_alertas": (13, "§18 retención: meses de las alertas cerradas o descartadas (con su historial) y "
                                    "de notification_log; una alerta abierta nunca se borra; 0 = no se recorta"),
    "retencion_meses_ejecuciones": (13, "§18 retención: meses de execution_log terminado (con sus intentos, errores "
                                        "de calidad y filas de monitoreo); nunca la que sostiene una marca de agua, un "
                                        "modelo, el histórico validado o un resultado que se conserva, ni la última de "
                                        "cada tipo; 0 = no se recorta"),
    "retencion_archivar_particiones": (0, "§18 retención: 1 = la partición vieja de feature_snapshot solo se separa y "
                                          "queda como tabla <partición>_archivo para archivarla (pg_dump); 0 = se "
                                          "separa y se borra"),
    "retencion_aplicar_programada": (1, "§18 retención: 1 = la corrida del planificador aplica la política; 0 = solo "
                                        "la simula y deja el informe en retencion_registro"),
}
MESES = ("retencion_meses_foto", "retencion_meses_resultados", "retencion_meses_alertas", "retencion_meses_ejecuciones")
BANDERAS = ("retencion_archivar_particiones", "retencion_aplicar_programada")
CONSERVADAS = {
    "demanda_observada": "histórico validado: lo usa el reentrenamiento (RF-018)",
    "ocupacion_segmento": "ocupación observada por segmento (§10.1), sin datos personales: la serie para recalibrar "
                          "la restricción reactiva y el perfil histórico",
    "model_registry": "auditoría de los modelos y de su activación (RF-019)",
    "threshold_config": "auditoría de los umbrales y parámetros versionados (§5.1)",
    "marca_agua_ruta": "estado de la lectura incremental por ruta (RNF-005)",
    "marca_agua_tabla": "estado de la lectura incremental de los consolidados de Extreme por tabla (§6.1), sin datos "
                        "personales",
    "alert (abiertas)": "trabajo pendiente de la operación",
    "retencion_registro": "bitácora de esta tarea",
}
DERIVADA = ("derivada de timbradas_segmentos: el refresco la iguala a la fuente y el refresco completo periódico la "
            "recalcula (SEGMENTOS_COMPLETO_DIAS), así que se conserva y su retención es la de Extreme")
# Tablas que se borran con la fila a la que pertenecen (llave foránea ON DELETE CASCADE): tabla -> (grupo, parámetro,
# de quién dependen)
DEPENDIENTES = {
    "alert_history": ("alertas", "retencion_meses_alertas", "su alerta"),
    "execution_attempt": ("ejecuciones", "retencion_meses_ejecuciones", "su ejecución"),
    "data_quality_error": ("ejecuciones", "retencion_meses_ejecuciones", "su ejecución (el lote ya no se consulta)"),
    "model_monitoring": ("ejecuciones", "retencion_meses_ejecuciones", "su ejecución"),
}


# ---------------------------------------------------------------- parámetros gobernados
def _entero(nombre: str, valor: Any) -> int:
    try:
        numero = float(valor)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{nombre} debe ser un número entero; se recibió {valor!r}") from exc
    if not numero.is_integer():
        raise ValueError(f"{nombre} debe ser un número entero; se recibió {valor!r}")
    return int(numero)


def validar_parametros(valores: dict[str, Any]) -> None:
    """PUT /thresholds: meses enteros, 0 (no se recorta) o entre MESES_MINIMO y MESES_MAXIMO; banderas 0 o 1."""
    for nombre in MESES:
        if nombre in valores:
            meses = _entero(nombre, valores[nombre])
            if meses != 0 and not MESES_MINIMO <= meses <= MESES_MAXIMO:
                raise ValueError(f"{nombre} debe ser 0 (no se recorta) o estar entre {MESES_MINIMO} y {MESES_MAXIMO} "
                                 f"meses; se recibió {valores[nombre]}")
    for nombre in BANDERAS:
        if nombre in valores and _entero(nombre, valores[nombre]) not in (0, 1):
            raise ValueError(f"{nombre} es 0 o 1; se recibió {valores[nombre]}")


def politica_de(umbrales: dict | None) -> dict[str, int]:
    """Los parámetros de la política: los de la versión de threshold_config o, si faltan, los valores por omisión."""
    umbrales = umbrales or {}
    salida = {}
    for nombre, (defecto, _descripcion) in PARAMETROS.items():
        try:
            salida[nombre] = _entero(nombre, umbrales.get(nombre, defecto))
        except ValueError:
            salida[nombre] = defecto
    return salida


def corte(ahora: datetime, meses: int) -> datetime | None:
    """El instante `meses` meses antes de `ahora` en el calendario de Bogotá (el día se acota al último del mes);
    None con 0 meses (ese grupo no se recorta)."""
    if meses <= 0:
        return None
    local = ahora.astimezone(ZONA)
    anio, mes = divmod(local.year * 12 + local.month - 1 - meses, 12)
    dia = min(local.day, calendar.monthrange(anio, mes + 1)[1])
    return local.replace(year=anio, month=mes + 1, day=dia)


# ---------------------------------------------------------------- reglas por filas (SQL constante)
@dataclass(frozen=True)
class Regla:
    """Filas de una tabla que se borran: `candidatas` es un SELECT constante de la llave de las filas anteriores al
    corte (:corte) que se pueden borrar sin dejar huérfano nada de lo que se conserva."""

    grupo: str
    tabla: str
    llave: str
    parametro: str
    candidatas: str
    descripcion: str


_PLANTILLA_SIN_REFERENCIA = ("NOT EXISTS (SELECT 1 FROM ai_frecuencias.{tabla} r WHERE r.execution_id = "
                             "t.execution_id)")
_REFERENCIAS_EJECUCION = ("marca_agua_ruta", "marca_agua_tabla", "model_registry", "demanda_observada", "prediction",
                          "prediction_corto_plazo", "recommendation", "alert", "notification_log", "respuesta_reto",
                          "segmento_estadistica_refresco")
_PLANTILLA_EJECUCIONES = """WITH base AS (
    SELECT t.execution_id FROM ai_frecuencias.execution_log t
     WHERE t.creado_en < :corte AND t.estado IN ('ok', 'error') AND {sin_referencias}
       AND t.execution_id NOT IN (SELECT DISTINCT ON (u.tipo) u.execution_id FROM ai_frecuencias.execution_log u
                                   ORDER BY u.tipo, u.creado_en DESC, u.execution_id DESC)
)
SELECT b.execution_id FROM base b
 WHERE NOT EXISTS (SELECT 1 FROM ai_frecuencias.execution_log h WHERE h.padre_id = b.execution_id)"""
_REFRESCOS_VIEJOS = (
    "SELECT t.id FROM ai_frecuencias.segmento_estadistica_refresco t WHERE t.actualizado_en < :corte AND t.id NOT IN ("
    "COALESCE((SELECT u.id FROM ai_frecuencias.segmento_estadistica_refresco u ORDER BY u.actualizado_en DESC, "
    "u.id DESC LIMIT 1), -1), COALESCE((SELECT u.id FROM ai_frecuencias.segmento_estadistica_refresco u WHERE "
    "u.modo = 'completo' ORDER BY u.actualizado_en DESC, u.id DESC LIMIT 1), -1))")

# El orden importa: primero lo que apunta a otras tablas (las recomendaciones antes que sus predicciones, las
# notificaciones antes que sus alertas) y al final las ejecuciones, cuando ya no les queda nada que las sostenga.
REGLAS: tuple[Regla, ...] = (
    Regla("resultados", "recommendation", "recommendation_id", "retencion_meses_resultados",
          "SELECT t.recommendation_id FROM ai_frecuencias.recommendation t WHERE t.creado_en < :corte",
          "recomendaciones por fecha de creación"),
    Regla("resultados", "prediction", "prediction_id", "retencion_meses_resultados",
          "SELECT t.prediction_id FROM ai_frecuencias.prediction t WHERE t.creado_en < :corte AND NOT EXISTS "
          "(SELECT 1 FROM ai_frecuencias.recommendation r WHERE r.prediction_id = t.prediction_id)",
          "predicciones por fecha de creación (su foto de variables se borra con ellas; nunca una que sostiene una "
          "recomendación que se conserva)"),
    Regla("resultados", "prediction_corto_plazo", "prediction_id", "retencion_meses_resultados",
          "SELECT t.prediction_id FROM ai_frecuencias.prediction_corto_plazo t WHERE t.creado_en < :corte",
          "pronósticos de corto plazo por fecha de creación (la fila de la ruta, las de sus sentidos y las de sus "
          "segmentos)"),
    Regla("resultados", "respuesta_reto", "id", "retencion_meses_resultados",
          "SELECT t.id FROM ai_frecuencias.respuesta_reto t WHERE t.generado_en < :corte",
          "fotos de la respuesta del reto por fecha de cálculo"),
    Regla("resultados", "segmento_estadistica_refresco", "id", "retencion_meses_resultados", _REFRESCOS_VIEJOS,
          "marcas de los refrescos de segmentos (nunca la última ni la del último completo)"),
    Regla("alertas", "notification_log", "id", "retencion_meses_alertas",
          "SELECT t.id FROM ai_frecuencias.notification_log t WHERE t.creado_en < :corte",
          "notificaciones y reportes enviados, por fecha"),
    Regla("alertas", "alert", "alert_id", "retencion_meses_alertas",
          "SELECT t.alert_id FROM ai_frecuencias.alert t WHERE t.actualizado_en < :corte AND t.estado IN "
          "('cerrada', 'descartada') AND NOT EXISTS (SELECT 1 FROM ai_frecuencias.notification_log n "
          "WHERE n.alert_id = t.alert_id)",
          "alertas cerradas o descartadas, por su última actualización (con su historial)"),
    Regla("ejecuciones", "execution_log", "execution_id", "retencion_meses_ejecuciones",
          _PLANTILLA_EJECUCIONES.format(sin_referencias=" AND ".join(
              _PLANTILLA_SIN_REFERENCIA.format(tabla=t) for t in _REFERENCIAS_EJECUCION)),
          "ejecuciones terminadas que ya no sostienen nada (con sus intentos, errores de calidad y monitoreo); "
          "nunca la última de cada tipo"),
)
_PLANTILLA_BORRAR = ("DELETE FROM ai_frecuencias.{tabla} WHERE {llave} IN (SELECT c.{llave} FROM ({candidatas}) c "
                     "LIMIT :lote)")


def sql_borrar(regla: Regla):
    return text(_PLANTILLA_BORRAR.format(tabla=regla.tabla, llave=regla.llave, candidatas=regla.candidatas))


# ---------------------------------------------------------------- particiones de feature_snapshot
SQL_PARTICIONES = text(r"""
SELECT c.relname AS particion,
       CAST((regexp_match(pg_get_expr(c.relpartbound, c.oid), 'FROM \(''([^'']+)''\)'))[1] AS timestamptz) AS desde,
       CAST((regexp_match(pg_get_expr(c.relpartbound, c.oid), 'TO \(''([^'']+)''\)'))[1] AS timestamptz) AS hasta,
       pg_total_relation_size(c.oid) AS bytes
  FROM pg_inherits i
  JOIN pg_class c ON c.oid = i.inhrelid
  JOIN pg_class p ON p.oid = i.inhparent
  JOIN pg_namespace n ON n.oid = p.relnamespace
 WHERE n.nspname = 'ai_frecuencias' AND p.relname = 'feature_snapshot'
 ORDER BY hasta NULLS LAST, c.relname
""")
# Por el padre con el rango de la partición: PostgreSQL solo recorre esa partición (poda de particiones). «recientes»:
# filas creadas después del corte de la foto; «conservadas»: fotos de una predicción que la regla de resultados de la
# MISMA corrida conserva (creada desde su corte, o sostiene una recomendación que se conserva; con
# retencion_meses_resultados = 0, :corte_resultados nulo, toda predicción se conserva). Una foto vive lo que vive su
# predicción: una partición con alguna de las dos se conserva entera.
SQL_FILAS_PARTICION = text("""
SELECT count(*) AS filas, count(*) FILTER (WHERE f.creado_en >= :corte) AS recientes,
       count(*) FILTER (WHERE c.prediction_id IS NOT NULL) AS conservadas
  FROM ai_frecuencias.feature_snapshot f
  LEFT JOIN (SELECT p.prediction_id FROM ai_frecuencias.prediction p
              WHERE CAST(:corte_resultados AS timestamptz) IS NULL OR p.creado_en >= :corte_resultados
             UNION
             SELECT r.prediction_id FROM ai_frecuencias.recommendation r
              WHERE r.prediction_id IS NOT NULL AND r.creado_en >= :corte_resultados) c
         ON c.prediction_id = f.prediction_id
 WHERE f.ventana_inicio >= :desde AND f.ventana_inicio < :hasta
""")
SQL_DERIVADA = {
    "segmento_estadistica_dia": text("SELECT count(*) AS filas, min(fecha) AS fecha_min, max(fecha) AS fecha_max, "
                                     "pg_total_relation_size('ai_frecuencias.segmento_estadistica_dia') AS bytes "
                                     "FROM ai_frecuencias.segmento_estadistica_dia"),
    "segmento_estadistica": text("SELECT count(*) AS filas, min(primera_fecha) AS fecha_min, max(ultima_fecha) AS "
                                 "fecha_max, pg_total_relation_size('ai_frecuencias.segmento_estadistica') AS bytes "
                                 "FROM ai_frecuencias.segmento_estadistica"),
}
SQL_CANDADO = text("SELECT pg_advisory_xact_lock(:k)")
SQL_RESERVA = text("SELECT 1 FROM ai_frecuencias.execution_log WHERE execution_id = :id AND worker_id = :w "
                   "AND estado = 'corriendo'")
# las llaves foráneas que una partición separada conserva de feature_snapshot (:tabla, ya validada con NOMBRE_ARCHIVO)
SQL_LLAVES_FORANEAS = text("SELECT c.conname FROM pg_constraint c WHERE c.conrelid = CAST(:tabla AS regclass) "
                           "AND c.contype = 'f' ORDER BY c.conname")
# los archivos que ya existen de una partición (:base = <partición>_archivo)
SQL_ARCHIVOS = text("SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "WHERE n.nspname = 'ai_frecuencias' AND starts_with(c.relname, :base)")


def nombre_de_archivo(s: Session, particion: str) -> str:
    """El nombre libre del archivo de una partición: <partición>_archivo o, si ya existe (el mismo mes se archivó antes
    y la partición se volvió a crear al reprocesar datos viejos), <partición>_archivo_2, _3… el primero libre. Así el
    RENAME no choca con el archivo anterior y la acción no queda pospuesta en cada corrida."""
    if not NOMBRE_PARTICION.fullmatch(particion):
        raise ValueError(f"Nombre de partición inesperado: {particion!r}")
    base = f"{particion}_archivo"
    existentes = set(s.execute(SQL_ARCHIVOS, {"base": base}).scalars())
    nombre, n = base, 1
    while nombre in existentes:
        n += 1
        nombre = f"{base}_{n}"
    return nombre


def ddl_particion(nombre: str, archivar: bool, archivo: str | None = None) -> list[str]:
    """DETACH y luego DROP (o RENAME al archivo, por omisión <nombre>_archivo) de una partición de feature_snapshot. Los
    nombres vienen del catálogo y deben cumplir NOMBRE_PARTICION y NOMBRE_ARCHIVO; van entre comillas."""
    if not NOMBRE_PARTICION.fullmatch(nombre):
        raise ValueError(f"Nombre de partición inesperado: {nombre!r}")
    archivo = archivo or f"{nombre}_archivo"
    if not NOMBRE_ARCHIVO.fullmatch(archivo) or not archivo.startswith(f"{nombre}_archivo"):
        raise ValueError(f"Nombre de archivo inesperado: {archivo!r}")
    separar = f'ALTER TABLE ai_frecuencias.feature_snapshot DETACH PARTITION ai_frecuencias."{nombre}"'
    final = (f'ALTER TABLE ai_frecuencias."{nombre}" RENAME TO "{archivo}"' if archivar
             else f'DROP TABLE ai_frecuencias."{nombre}"')
    return [separar, final]


# ---------------------------------------------------------------- la corrida
@dataclass
class Corrida:
    """Una corrida de la política: si simula, el instante, los parámetros y la bitácora de lo que hizo."""

    simular: bool
    politica: dict[str, int]
    ahora: datetime
    execution_id: uuid.UUID | None = None
    umbrales_version: int | None = None
    trabajador: str | None = None
    sesiones: Callable[[], AbstractContextManager[Session]] = sesion_contexto
    acciones: list[dict[str, Any]] = field(default_factory=list)

    def corte_de(self, parametro: str) -> datetime | None:
        return corte(self.ahora, self.politica.get(parametro, 0))


class ReservaPerdida(Exception):
    """Otra réplica retomó el trabajo de retención: esta deja de actuar (lo que ya hizo queda en la bitácora)."""


def _abrir(c: Corrida, s: Session) -> None:
    """Cada acción: el candado de la retención y la verificación de que el trabajo sigue siendo de esta réplica."""
    s.execute(SQL_CANDADO, {"k": CLAVE_RETENCION})
    if c.trabajador and c.execution_id and not s.execute(SQL_RESERVA, {"id": c.execution_id,
                                                                       "w": c.trabajador}).scalar():
        raise ReservaPerdida(f"La retención {c.execution_id} ya no está reservada por {c.trabajador}")


def _anotar(c: Corrida, s: Session, accion: dict[str, Any], registro: RegistroRetencion | None = None
            ) -> RegistroRetencion:
    """La fila de bitácora de una acción (o su actualización, en los lotes siguientes de la misma tabla)."""
    from app.servicios.ejecucion import json_seguro

    if registro is None:
        registro = RegistroRetencion(execution_id=c.execution_id, simulado=c.simular, grupo=accion["grupo"],
                                     objeto=accion["objeto"], accion=accion["accion"], corte=accion.get("corte"),
                                     umbrales_version=c.umbrales_version)
        s.add(registro)
    registro.filas = int(accion.get("filas") or 0)
    registro.bytes = accion.get("bytes")
    registro.detalle = json_seguro(accion.get("detalle") or {})
    s.flush()
    return registro


def _accion(grupo: str, objeto: str, accion: str, corte_: datetime | None, filas: int = 0, bytes_: int | None = None,
            **detalle: Any) -> dict[str, Any]:
    return {"grupo": grupo, "objeto": objeto, "accion": accion, "corte": corte_, "filas": int(filas),
            "bytes": None if bytes_ is None else int(bytes_), "detalle": detalle}


# ---------------------------------------------------------------- foto de variables (particiones)
def _particiones(s: Session) -> list[dict[str, Any]]:
    return [dict(f) for f in s.execute(SQL_PARTICIONES).mappings().all()]


def _motivo_para_conservar(nombre: str, conteo) -> dict[str, Any] | None:
    """Por qué una partición vieja se conserva entera (None si se puede separar): un nombre no estándar (la separa el
    DBA), filas creadas después del corte o fotos de predicciones que la regla de resultados conserva (una foto vive
    lo que vive su predicción)."""
    if not NOMBRE_PARTICION.fullmatch(nombre):
        return {"motivo": "nombre no estándar: la separa el DBA"}
    if conteo.recientes:
        return {"recientes": int(conteo.recientes),
                "motivo": "tiene filas creadas después del corte: su predicción se conserva"}
    if conteo.conservadas:
        return {"fotos_de_predicciones_conservadas": int(conteo.conservadas),
                "motivo": "tiene fotos de predicciones que la regla de resultados conserva (creadas desde su corte, o "
                          "viejas pero con una recomendación que se conserva; con retencion_meses_resultados = 0, "
                          "todas): una foto vive lo que vive su predicción"}
    return None


def _plan_particion(s: Session, p: dict[str, Any], corte_: datetime, archivar: bool,
                    corte_resultados: datetime | None) -> dict[str, Any] | None:
    """Qué hacer con una partición: None si su rango llega al corte (se conserva entera); si no, separarla y borrarla
    (o archivarla), o conservarla con el motivo (_motivo_para_conservar)."""
    if p["hasta"] is None or p["hasta"] > corte_:
        return None
    conteo = s.execute(SQL_FILAS_PARTICION, {"desde": p["desde"], "hasta": p["hasta"], "corte": corte_,
                                             "corte_resultados": corte_resultados}).one()
    rango = {"desde": p["desde"], "hasta": p["hasta"]}
    conservar = _motivo_para_conservar(p["particion"], conteo)
    if conservar is not None:
        return _accion("foto", p["particion"], "conservar", corte_, conteo.filas, p["bytes"], **rango, **conservar)
    return _accion("foto", p["particion"], "separar_y_archivar" if archivar else "separar_y_borrar", corte_,
                   conteo.filas, p["bytes"], **rango)


def soltar_llaves_foraneas(s: Session, archivo: str) -> list[str]:
    """Quita de una partición archivada las llaves foráneas que clonó de feature_snapshot (a prediction y a
    execution_log, ON DELETE CASCADE): el archivo es una copia independiente para pg_dump y, con ellas, borrar su
    predicción o su ejecución vieja vaciaría el archivo en cascada. Los nombres salen de pg_constraint y se validan.
    Devuelve los nombres quitados."""
    if not NOMBRE_ARCHIVO.fullmatch(archivo):
        raise ValueError(f"Nombre de archivo inesperado: {archivo!r}")
    tabla = f'ai_frecuencias."{archivo}"'
    nombres = list(s.execute(SQL_LLAVES_FORANEAS, {"tabla": tabla}).scalars())
    if not all(NOMBRE_RESTRICCION.fullmatch(n) for n in nombres):
        raise ValueError(f"Nombre de restricción inesperado en {archivo}: {nombres!r}")
    for nombre in nombres:
        s.execute(text(f'ALTER TABLE {tabla} DROP CONSTRAINT "{nombre}"'))
    return nombres


def _ejecutar_separacion(s: Session, accion: dict[str, Any]) -> dict[str, Any]:
    """DETACH y DROP (o RENAME al archivo libre y sin llaves foráneas) de la partición en la transacción de `s`, con
    lock_timeout = ESPERA_CANDADO. Devuelve la acción hecha (la de archivar, con su archivo y las llaves quitadas en el
    detalle)."""
    archivar = accion["accion"] == "separar_y_archivar"
    s.execute(text(f"SET LOCAL lock_timeout = '{ESPERA_CANDADO}'"))     # constante del módulo
    archivo = nombre_de_archivo(s, accion["objeto"]) if archivar else None
    for sentencia in ddl_particion(accion["objeto"], archivar, archivo):
        s.execute(text(sentencia))
    if archivo is None:
        return accion
    quitadas = soltar_llaves_foraneas(s, archivo)
    return {**accion, "detalle": {**accion["detalle"], "archivo": archivo, "llaves_foraneas_quitadas": quitadas}}


def _separar(c: Corrida, accion: dict[str, Any]) -> dict[str, Any]:
    """La separación en una transacción corta (_ejecutar_separacion); si un ciclo tiene los candados, la acción queda
    pospuesta para la corrida siguiente."""
    try:
        with c.sesiones() as s:
            _abrir(c, s)
            hecha = _ejecutar_separacion(s, accion)
            _anotar(c, s, hecha)
        return hecha
    except DBAPIError as exc:
        motivo = str(getattr(exc, "orig", exc)).splitlines()[0][:300]
        log.warning("Partición %s pospuesta: %s", accion["objeto"], motivo)
        pospuesta = {**accion, "accion": "pospuesta", "detalle": {**accion["detalle"], "motivo": motivo,
                                                                  "accion_pedida": accion["accion"]}}
        with c.sesiones() as s:
            _abrir(c, s)
            _anotar(c, s, pospuesta)
        return pospuesta


def _foto(c: Corrida) -> None:
    corte_ = c.corte_de("retencion_meses_foto")
    if corte_ is None:
        return
    archivar = bool(c.politica.get("retencion_archivar_particiones"))
    corte_resultados = c.corte_de("retencion_meses_resultados")
    with c.sesiones() as s:
        planes = [a for a in (_plan_particion(s, p, corte_, archivar, corte_resultados) for p in _particiones(s))
                  if a is not None]
    for accion in planes:
        if c.simular or accion["accion"] == "conservar":
            with c.sesiones() as s:
                _abrir(c, s)
                _anotar(c, s, accion)
            c.acciones.append(accion)
        else:
            c.acciones.append(_separar(c, accion))


# ---------------------------------------------------------------- resultados, alertas y ejecuciones (filas)
def _lote(s: Session, regla: Regla, corte_: datetime, accion: dict[str, Any]) -> int:
    """Un lote de a lo sumo LOTE_FILAS filas de la regla; suma lo borrado a la acción."""
    borradas = int(s.execute(sql_borrar(regla), {"corte": corte_, "lote": LOTE_FILAS}).rowcount or 0)
    accion["filas"] += borradas
    accion["detalle"]["lotes"] += 1 if borradas else 0
    return borradas


def _accion_de_filas(regla: Regla, corte_: datetime) -> dict[str, Any]:
    return _accion(regla.grupo, regla.tabla, "borrar_filas", corte_, 0, descripcion=regla.descripcion, lotes=0)


def _borrar(c: Corrida, regla: Regla, corte_: datetime) -> dict[str, Any]:
    """Lotes de LOTE_FILAS filas, cada uno en su transacción con la fila de bitácora al día, hasta que no quede ninguna.
    Una madre de una ejecución partida solo es candidata cuando ya no le queda ningún trabajo: se borra en un lote
    posterior al de sus trabajos (si uno se conserva, ella también), y cada fila borrada se cuenta."""
    accion = _accion_de_filas(regla, corte_)
    registro_id, borradas = None, 1
    while borradas:
        with c.sesiones() as s:
            _abrir(c, s)
            borradas = _lote(s, regla, corte_, accion)
            previo = s.get(RegistroRetencion, registro_id) if registro_id is not None else None
            registro_id = _anotar(c, s, accion, previo).id
    return accion


def _simular_filas(c: Corrida, reglas: list[tuple[Regla, datetime]]) -> None:
    """Simulación exacta: los mismos DELETE por lotes, en el mismo orden y en UNA transacción que se revierte. Así
    cuenta lo que de verdad se borraría, también lo que solo queda libre cuando se borra lo de la regla anterior (una
    ejecución que sostenía una predicción vieja), sin borrar nada; la bitácora se escribe después de revertir."""
    acciones = []
    with c.sesiones() as s:
        _abrir(c, s)
        for regla, corte_ in reglas:
            accion = _accion_de_filas(regla, corte_)
            while _lote(s, regla, corte_, accion):
                pass
            acciones.append(accion)
        s.rollback()
    with c.sesiones() as s:
        _abrir(c, s)
        for accion in acciones:
            _anotar(c, s, accion)
    c.acciones.extend(acciones)


def _filas(c: Corrida, avance: Callable[[float, str], None]) -> None:
    reglas = [(r, c.corte_de(r.parametro)) for r in REGLAS if c.corte_de(r.parametro) is not None]
    if c.simular:
        avance(50, "simulacion de las filas")
        _simular_filas(c, reglas)
        return
    for i, (regla, corte_) in enumerate(reglas, start=1):
        avance(20 + 60 * i / len(reglas), f"{regla.grupo}: {regla.tabla}")
        c.acciones.append(_borrar(c, regla, corte_))


def _derivada(c: Corrida) -> None:
    """La agregación de segmentos se conserva: deja en la bitácora sus filas, su período y su tamaño."""
    with c.sesiones() as s:
        _abrir(c, s)
        for tabla, sql in SQL_DERIVADA.items():
            fila = s.execute(sql).mappings().one()
            accion = _accion("derivada", tabla, "conservar", None, fila["filas"], fila["bytes"],
                             fecha_min=fila["fecha_min"], fecha_max=fila["fecha_max"], motivo=DERIVADA)
            _anotar(c, s, accion)
            c.acciones.append(accion)


def _sin_avance(_progreso: float, _etapa: str) -> None:
    """Avance nulo para llamadas fuera de la cola (pruebas y guiones)."""


def aplicar(politica: dict[str, int], *, simular: bool, ahora: datetime | None = None,
            execution_id: uuid.UUID | None = None, umbrales_version: int | None = None,
            trabajador: str | None = None, sesiones: Callable[[], AbstractContextManager[Session]] | None = None,
            avance: Callable[[float, str], None] = _sin_avance) -> dict[str, Any]:
    """Aplica (o simula) la política: particiones de la foto, filas de resultados, alertas y ejecuciones, y el informe
    de la agregación derivada. Devuelve el resumen que queda en las métricas del trabajo."""
    t0 = time.perf_counter()
    c = Corrida(simular=simular, politica=dict(politica), ahora=ahora or datetime.now(UTC),
                execution_id=execution_id, umbrales_version=umbrales_version, trabajador=trabajador,
                sesiones=sesiones or sesion_contexto)
    avance(10, "foto_de_variables")
    _foto(c)
    _filas(c, avance)
    avance(85, "derivada")
    _derivada(c)
    return resumen(c, time.perf_counter() - t0)


def resumen(c: Corrida, segundos: float) -> dict[str, Any]:
    """Lo que hizo (o haría) la corrida: cortes por grupo, acciones y totales."""
    cortes = {n: c.corte_de(n) for n in MESES}
    borradas = [a for a in c.acciones if a["accion"] in ("separar_y_borrar", "separar_y_archivar", "borrar_filas")]
    return {"simulado": c.simular, "ahora": c.ahora, "umbrales_version": c.umbrales_version,
            "politica": dict(c.politica), "cortes": cortes, "acciones": c.acciones,
            "filas": int(sum(a["filas"] for a in borradas if a["accion"] == "borrar_filas")),
            "particiones": sum(1 for a in borradas if a["accion"] != "borrar_filas"),
            "filas_particiones": int(sum(a["filas"] for a in borradas if a["accion"] != "borrar_filas")),
            "bytes_particiones": int(sum(a["bytes"] or 0 for a in borradas if a["accion"] != "borrar_filas")),
            "pospuestas": sum(1 for a in c.acciones if a["accion"] == "pospuesta"),
            "duracion_s": round(segundos, 3)}


# ---------------------------------------------------------------- el trabajo de la cola
def simula(parametros: dict[str, Any], politica: dict[str, int]) -> bool:
    """¿Simula la corrida? La pedida por la API dice «simular»; la programada simula si la política no la deja
    aplicar (retencion_aplicar_programada = 0)."""
    if parametros.get("simular") is not None:
        return bool(parametros["simular"])
    return not bool(politica.get("retencion_aplicar_programada", 1))


def mensaje(r: dict[str, Any]) -> str:
    verbo = "simulada (no se borró nada)" if r["simulado"] else "aplicada"
    texto = (f"Retención {verbo}: {r['filas']} filas y {r['particiones']} particiones de la foto de variables "
             f"({r['filas_particiones']} filas) anteriores al corte")
    return texto + (f"; {r['pospuestas']} acciones pospuestas" if r["pospuestas"] else "")


def _retencion_en_cola(execution_id: uuid.UUID) -> None:
    from app.servicios import cola, ejecucion

    with sesion_contexto() as s:
        parametros = dict(s.get(Ejecucion, execution_id).parametros or {})
        version_u, umbrales = ejecucion.umbrales_vigentes(s)
    politica = politica_de(umbrales)
    ejecucion._avance(execution_id, 5, "planificacion")
    try:
        r = aplicar(politica, simular=simula(parametros, politica), execution_id=execution_id,
                    umbrales_version=version_u, trabajador=cola.trabajador_actual.get(),
                    avance=lambda p, etapa: ejecucion._avance(execution_id, round(p, 2), etapa))
    except ReservaPerdida as exc:
        raise cola.ReservaPerdida(str(exc)) from exc
    with sesion_contexto() as s:
        cola.cerrar_ok(s, execution_id, dict(
            estado="ok", etapa="terminada", progreso=100, umbrales_version=version_u,
            filas_leidas=r["filas"] + r["filas_particiones"], metricas=ejecucion.json_seguro(r),
            mensaje=mensaje(r), terminado_en=ejecucion.ahora(), actualizado_en=ejecucion.ahora()))


def ciclo_retencion(execution_id: uuid.UUID) -> None:
    """Trabajo «retencion» de la cola. RNF-006: corre en el span «ejecucion.ciclo_retencion», que continúa la traza
    de quien lo encoló."""
    from app.observabilidad import ejecucion_en_curso

    with ejecucion_en_curso(execution_id, TIPO):
        _retencion_en_cola(execution_id)


# ---------------------------------------------------------------- encolar sin duplicar y consultar
def solicitar(s: Session, parametros: dict[str, Any], correlation_id: str | None = None) -> tuple[Ejecucion, bool]:
    """Encola una corrida {simular, motivo, origen, solicitado_por} y devuelve (ejecución, nueva). Si ya hay una en
    cola o corriendo, devuelve esa (no se duplica: dos corridas a la vez solo se estorbarían)."""
    from app.servicios import ejecucion

    s.execute(SQL_CANDADO, {"k": CLAVE_RETENCION + 1})
    existente = s.scalars(select(Ejecucion).where(Ejecucion.tipo == TIPO, Ejecucion.estado.in_(("en_cola",
                                                                                                 "corriendo")))
                          .order_by(Ejecucion.creado_en)).first()
    if existente is not None:
        s.commit()           # sin escrituras: solo suelta el candado
        return existente, False
    return ejecucion.crear_ejecucion(s, TIPO, parametros, correlation_id), True


def _accion_de_regla(regla: Regla, politica: dict[str, int], ahora: datetime) -> dict[str, Any]:
    return {"grupo": regla.grupo, "tabla": regla.tabla, "accion": "borrar_filas", "parametro": regla.parametro,
            "meses": politica[regla.parametro], "corte": corte(ahora, politica[regla.parametro]),
            "descripcion": regla.descripcion}


def reglas_vigentes(politica: dict[str, int], ahora: datetime) -> list[dict[str, Any]]:
    """La política en vigor, tabla por tabla, con su corte de hoy (GET /api/v1/retencion)."""
    meses_foto = politica["retencion_meses_foto"]
    foto = {"grupo": "foto", "tabla": "feature_snapshot",
            "accion": "separar_y_archivar" if politica["retencion_archivar_particiones"] else "separar_y_borrar",
            "parametro": "retencion_meses_foto", "meses": meses_foto, "corte": corte(ahora, meses_foto),
            "descripcion": "particiones mensuales enteras anteriores al corte, con todas sus filas creadas antes del "
                           "corte y sin fotos de predicciones que se conservan (DETACH PARTITION y DROP, o archivo)"}
    dependientes = [{"grupo": g, "tabla": t, "accion": "borrar_filas", "parametro": p, "meses": politica[p],
                     "corte": corte(ahora, politica[p]), "descripcion": f"se borran con {quien} (llave foránea ON "
                                                                        "DELETE CASCADE)"}
                    for t, (g, p, quien) in DEPENDIENTES.items()]
    derivadas = [{"grupo": "derivada", "tabla": t, "accion": "conservar", "parametro": None, "meses": None,
                  "corte": None, "descripcion": DERIVADA} for t in SQL_DERIVADA]
    conservadas = [{"grupo": "conservada", "tabla": t, "accion": "conservar", "parametro": None, "meses": None,
                    "corte": None, "descripcion": d} for t, d in CONSERVADAS.items()]
    return [foto, *(_accion_de_regla(r, politica, ahora) for r in REGLAS), *dependientes, *derivadas, *conservadas]


def ultima_corrida(s: Session) -> list[RegistroRetencion]:
    """Las filas de bitácora de la corrida más reciente (vacía si nunca corrió)."""
    ultima = s.scalars(select(RegistroRetencion).order_by(RegistroRetencion.creado_en.desc(),
                                                          RegistroRetencion.id.desc()).limit(1)).first()
    if ultima is None:
        return []
    filtro = (RegistroRetencion.execution_id == ultima.execution_id if ultima.execution_id is not None
              else RegistroRetencion.id == ultima.id)
    return list(s.scalars(select(RegistroRetencion).where(filtro).order_by(RegistroRetencion.id)).all())


def describir(s: Session, ahora: datetime | None = None) -> dict[str, Any]:
    """La política vigente (parámetros gobernados, versión y corte de cada tabla) y la bitácora de la última corrida."""
    from app.servicios import ejecucion

    version_u, umbrales = ejecucion.umbrales_vigentes(s)
    politica = politica_de(umbrales)
    momento = ahora or datetime.now(UTC)
    return {"umbrales_version": version_u, "ahora": momento, "parametros": politica,
            "aplicar_programada": bool(politica["retencion_aplicar_programada"]),
            "reglas": reglas_vigentes(politica, momento), "ultima_corrida": ultima_corrida(s)}


__all__ = ["TIPO", "PARAMETROS", "REGLAS", "Regla", "Corrida", "aplicar", "ciclo_retencion", "corte",
           "ddl_particion", "describir", "nombre_de_archivo", "politica_de", "reglas_vigentes", "simula",
           "soltar_llaves_foraneas", "solicitar", "sql_borrar", "validar_parametros", "SQL_PARTICIONES",
           "SQL_FILAS_PARTICION", "SQL_DERIVADA", "SQL_LLAVES_FORANEAS", "SQL_ARCHIVOS"]
