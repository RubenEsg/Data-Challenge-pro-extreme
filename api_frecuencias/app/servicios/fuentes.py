"""Fuentes de datos de entrada con lectura incremental por ultima_actualizacion (especificación v1.5, §8.3, §9.5).

- FuenteParquet (por defecto): los datos del proyecto empaquetados en datos/ (demanda_horaria.parquet, a través de
  app.servicios.datos.demanda_horaria). Sin red y reproducible. `hasta` simula la llegada diaria: solo son visibles las
  filas con fecha <= hasta, de modo que la demo puede mostrar ciclos incrementales día a día.
- FuentePostgresSoloLectura: las tablas existentes de Extreme (§8.2) en PostgreSQL con un usuario SELECT (lector_ia).
  URL en la variable de entorno FUENTE_DATABASE_URL (nunca en el repositorio). Cada lectura abre una transacción
  «SET TRANSACTION READ ONLY» con «SET LOCAL statement_timeout» y «SET LOCAL TimeZone = 'America/Bogota'», ejecuta un
  único SELECT de una lista blanca y termina con ROLLBACK (nunca COMMIT). Cualquier sentencia que no sea SELECT se
  rechaza antes de tocar la base.

Lectura incremental exacta (RF-013, §11.2, hallazgos H7 y H10 de docs/hallazgos_extreme.md):
- las marcas de Extreme son `timestamp without time zone` llenadas con NOW() en la zona del servidor; la sesión fija
  America/Bogota para que la comparación con la marca (con zona) no se corra 5 horas;
- NOW() es la hora de INICIO de la transacción de escritura: una captura larga se confirma con una marca anterior a
  la última leída. Por eso se lee con una ventana de solape (marca − FUENTE_SOLAPE_MIN) y se deduplica por llave;
- cada fila leída lleva una huella de contenido (md5 de sus valores sin la marca). La ejecución guarda las huellas de
  la ventana de solape (y de los resellados) y la siguiente lectura descarta las filas cuya huella ya entregó: una fila
  tardía o modificada se entrega exactamente una vez y un resellado sin cambios (fn_consolidar, H7) no se reprocesa.

Lecturas disponibles (tabla=...): las consolidadas con marca (timbradas_*), los catálogos de contexto sin marca
("Procesos", rutas, estacionalidades, novedades, segmentos) y la lectura compuesta «demanda_segmentos», que convierte
timbradas_segmentos (lo que escribe el trigger tg_timbrada_segmento) en el contrato de demanda horaria del ciclo
(ruta, fecha, hora de salida, pasajeros, salidas, ultima_actualizacion) re-agregando completas las franjas tocadas.
Todas devuelven (DataFrame, nueva_marca); la nueva marca es la mayor marca leída (o la recibida si no llegó nada).
Fuera de la lectura incremental, `viajes(ruta, desde, hasta)` lee los viajes de una ruta en una ventana (progvehiculos,
§5.3 «viaje, conductor y vehículo»: el despacho de ALT-006 y los viajes con datos faltantes de ALT-009), con el mismo
SELECT de la lista blanca, la misma transacción READ ONLY y el conductor seudonimizado antes de salir de aquí (§18).

El ciclo diario (FUENTE_TABLA) solo procesa de punta a punta «demanda_segmentos»: es la única lectura con el
contrato de demanda horaria que validan la calidad, la ingesta y el modelo. Las demás tablas de la lista blanca se
leen con esta misma clase para los catálogos, la capa de segmentos, las pruebas y las evidencias de la réplica.

Ocupación actual por segmento (§10.1, leer_carga_segmentos): para las franjas que acaba de entregar esa lectura, el
ciclo lee viaje por viaje sus subidas y bajadas por segmento con otro SELECT constante de la lista blanca (las franjas
van como arreglos enlazados). Como depende de las franjas entregadas y no de una marca propia, convive con la marca
de agua por ruta (RNF-005) sin estado adicional. El conductor se seudonimiza al leer (§18).

Lectura por partición (RNF-005, leer_particion): el ciclo guarda una marca de agua y unas huellas por proceso y ruta
(ai_frecuencias.marca_agua_ruta). Un trabajo de UNA ruta lee solo esa ruta (en PostgreSQL, el mismo SELECT de la
lista blanca con «r.nombre = ANY(:rutas)») desde la marca de esa ruta; un trabajo de todas las rutas lee desde la
marca más antigua y cada fila se filtra con la marca y las huellas de SU ruta. La regla exacta de siempre (solape,
huellas, tipo de llegada) se aplica ruta por ruta.

Definición de pasajeros en modo integrado (docs/evidencias/datos/definicion_pasajeros.md): igual que el objetivo del
modelo y el histórico empaquetado, pasajeros = Σ numeropasajeros de los viajes válidos de progvehiculos (finalizado
'S', no cancelado, dato <= 300) que salen en esa hora y salidas = número de viajes válidos. Σ subidas de
timbradas_segmentos queda en la columna subidas (5,2 % menos que numeropasajeros en el solape de 2023). La consulta
une rutas, "Procesos" y estacionalidades_anio (§11.2): filtra por FUENTE_PROCESO y entrega proceso, idempresa e
id_estacionalidad (vigente en la fecha, período más corto) de cada franja.

Definición de bajadas (§6.1 «Bajadas: descensos consolidados», docs/evidencias/consolidados/definicion_bajadas.md): la
misma regla aplicada a los descensos, bajadas_viajes = Σ numerobajadas de los viajes válidos (dato <= 300, ceros
incluidos); Σ bajadas de timbradas_segmentos queda en la columna bajadas. En los mismos viajes las dos difieren 0,11 %
(en total, −5,3 %: la diferencia es de cobertura, como la de pasajeros), y bajadas_viajes cubre todo el histórico
(2023-2025), así que la usan ALT-008, su backtest y el contraste con timbradas_consolidado. En modo offline la trae
datos/bajadas_horaria.parquet.
"""
from __future__ import annotations

import hashlib
import logging
import math
import os
import re
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, timezone
from typing import Any, NamedTuple

import pandas as pd

log = logging.getLogger("api_frecuencias.fuentes")
MARCA_INICIAL = datetime(1970, 1, 1, tzinfo=UTC)
ZONA = "America/Bogota"
SOLAPE_MIN_DEFECTO = 15
# 2: la huella de demanda_segmentos cambió (definición de pasajeros y columnas de proceso y estacionalidad); 3: llegó la
# columna bajadas_viajes (migración 0013). Un estado de otra versión no se compara y la primera lectura vuelve a
# entregar la ventana de solape (con las columnas nuevas, que el histórico guarda).
VERSION_ESTADO = 3
# Lectura que el ciclo procesa de punta a punta (FUENTE_TABLA) y proceso (operador) por omisión.
TABLA_CICLO = "demanda_segmentos"
TABLAS_CICLO = (TABLA_CICLO,)
PROCESO_DEFECTO = "sobusa"
DEFINICION_PASAJEROS = "numeropasajeros_viajes_validos_v2"
DEFINICION_BAJADAS = "numerobajadas_viajes_validos_v1"
# Punto de despacho empaquetado (modo offline): inicio del segmento 1 de rutas_segmentos de cada ruta (ST_StartPoint
# de la configuración activa, EPSG:4326), leído de la réplica; tests/replica/test_integrado.py comprueba que
# coincide con ubicacion_despacho de la fuente PostgreSQL.
PUNTO_DESPACHO_EMPAQUETADO = {
    2: (-74.8042050, 10.8881388),
    16: (-74.8047108, 10.8886320),
    21: (-74.8043518, 10.8885557),
}

# Tablas de §8.2 (más los catálogos que usan los scripts de Extreme) que se pueden leer; nunca escribir.
TABLAS_CON_MARCA = (
    "timbradas_consolidado", "timbradas_consolidado_zonas", "timbradas_anio", "timbradas_anio_zonas",
    "timbradas_segmentos", "timbradas_segmentos_anio", "timbradas_segmentos_consolidado",
)
# Catálogos pequeños sin marca: se leen completos. "Procesos" lleva comillas y mayúscula en la base real.
TABLAS_SIN_MARCA = ("rutas", "Procesos", "estacionalidades", "estacionalidades_anio", "dias_semana",
                    "novedades_viales", "novedades_viales_fecha", "novedades_viales_ruta", "rutas_segmentos",
                    "rutas_segmentos_config")
# Lecturas compuestas (varias tablas, un solo SELECT constante con parámetros enlazados).
VISTAS = ("demanda_segmentos",)
TABLAS_PERMITIDAS = TABLAS_CON_MARCA + TABLAS_SIN_MARCA + VISTAS

# La marca se llama ultima_actualizacion salvo en timbradas_segmentos (DDL de Extreme: ultimaactualizacion).
COLUMNA_MARCA = {"timbradas_segmentos": "ultimaactualizacion"}
# Tablas con marca que traen la columna proceso (el operador; en la base de Extreme hay varios, hallazgo H4): su
# lectura incremental filtra el proceso de la fuente EN EL SQL («proceso = :proceso», parámetro enlazado), así que las
# filas de otros operadores no se leen, no entran en las huellas del estado incremental ni mueven la marca nueva.
TABLAS_CON_PROCESO = ("timbradas_consolidado", "timbradas_anio", "timbradas_segmentos_anio",
                      "timbradas_segmentos_consolidado")
# Llave natural de cada lectura (deduplicación y huella). Sin entrada: la primera columna (la llave primaria).
LLAVES = {
    "timbradas_consolidado": ("proceso", "id_ruta", "id_dia_semana", "id_estacionalidad", "hora", "hora_inicio",
                              "hora_fin"),
    "timbradas_consolidado_zonas": ("id_timbrada_consolidado", "id_zona_tarifa"),
    "timbradas_anio": ("proceso", "ano", "id_ruta", "id_dia_semana", "id_estacionalidad_anio", "hora_inicio",
                       "hora_fin"),
    "timbradas_anio_zonas": ("id_timbrada_anio", "id_zona_tarifa"),
    "timbradas_segmentos": ("id_segmento", "id_viaje", "hora_inicio"),
    "timbradas_segmentos_anio": ("id_segmento", "proceso", "ano", "id_ruta", "id_dia_semana", "id_estacionalidad_anio",
                                 "hora", "hora_inicio", "hora_fin"),
    "timbradas_segmentos_consolidado": ("id_segmento", "proceso", "id_dia_semana", "id_estacionalidad", "hora",
                                        "hora_inicio", "hora_fin"),
    "demanda_segmentos": ("ruta", "fecha", "hora"),
}

# Demanda horaria desde la segmentación: los viajes con timbradas nuevas o modificadas marcan sus franjas (ruta, hora
# de salida) y cada franja tocada se vuelve a agregar COMPLETA (todos sus viajes), para no entregar sumas parciales.
# pasajeros = Σ numeropasajeros de los viajes válidos (finalizado 'S', no cancelado, dato <= 300) que salen en esa
# hora, la misma definición del objetivo del modelo; bajadas_viajes = Σ numerobajadas con la misma regla; salidas =
# viajes válidos; subidas y bajadas = Σ de los segmentos.
# La ruta se une con "Procesos" (raíz de las relaciones, filtro :proceso) y la estacionalidad vigente de la fecha sale
# de estacionalidades_anio con el desempate de fn_insert_timbradas_anio (el período más corto).
# El nombre y la empresa de la ruta viajan desde `franjas`, que ya une rutas: la consulta final NO vuelve a unir rutas.
# Con esa segunda unión PostgreSQL estimaba `viajes ⋈ rutas` con el ndistinct por omisión de un CTE (1/200 en vez de
# una de tres rutas): unas 60 filas donde hay 13.304. Con la propuesta de índices entera y las estadísticas al día
# (ANALYZE también mide la expresión del índice sobre date_trunc('hour', fechasalida)), esa estimación elegía un ciclo
# anidado con Materialize para unir segmentos_viaje: 88 millones de filas descartadas y la lectura de un bloque grande
# pasaba de 3,5 a más de 9 s. Sin esa unión la lectura entrega las mismas filas en el mismo orden, con y sin índices, y
# con la propuesta entera baja en vez de subir (docs/evidencias/replica/indices_candidatos.md, «La propuesta entera»;
# tests/replica/test_explain.py).
_SQL_DEMANDA_SEGMENTOS = """
WITH cambiados AS (
    SELECT DISTINCT ts.id_viaje
      FROM timbradas_segmentos ts
     WHERE ts.ultimaactualizacion > :marca{filtro_hasta}
), franjas AS (
    SELECT DISTINCT pv.idruta, r.proceso, r.nombre, r.idempresa, date_trunc('hour', pv.fechasalida) AS franja
      FROM cambiados c
      JOIN progvehiculos pv ON pv.idprogramacion = c.id_viaje
      JOIN rutas r ON r.idruta = pv.idruta
      JOIN "Procesos" p ON p.proceso = r.proceso
     WHERE (CAST(:proceso AS text) IS NULL OR r.proceso = CAST(:proceso AS text)){filtro_rutas}
), viajes AS (
    SELECT pv.idprogramacion, f.idruta, f.proceso, f.nombre, f.idempresa, f.franja, pv.numeropasajeros,
           pv.numerobajadas, (pv.finalizado = 'S' AND pv.cancelada = 'N') AS valido
      FROM franjas f
      JOIN progvehiculos pv ON pv.idruta = f.idruta AND date_trunc('hour', pv.fechasalida) = f.franja
), segmentos_viaje AS (
    SELECT v.idprogramacion, SUM(ts.subidas) AS subidas, SUM(ts.bajadas) AS bajadas, COUNT(*) AS filas,
           MAX(ts.ultimaactualizacion) AS marca
      FROM viajes v
      JOIN timbradas_segmentos ts ON ts.id_viaje = v.idprogramacion
     GROUP BY v.idprogramacion
), estacion AS (
    SELECT d.proceso, d.fecha, ea.id_estacionalidad, ea.id_estacionalidad_anio
      FROM (SELECT DISTINCT proceso, CAST(franja AS date) AS fecha FROM franjas) d
      LEFT JOIN LATERAL (
            SELECT e.id_estacionalidad, e.id_estacionalidad_anio
              FROM estacionalidades_anio e
             WHERE e.proceso = d.proceso AND e.fecha_inicio <= d.fecha AND e.fecha_fin >= d.fecha
             ORDER BY (e.fecha_fin - e.fecha_inicio), e.fecha_inicio DESC, e.id_estacionalidad_anio DESC
             LIMIT 1) ea ON true
)
SELECT v.nombre AS ruta, v.idruta, v.proceso, v.idempresa, CAST(v.franja AS date) AS fecha,
       CAST(EXTRACT(HOUR FROM v.franja) AS integer) AS hora,
       CAST(COALESCE(SUM(v.numeropasajeros) FILTER (WHERE v.valido AND v.numeropasajeros <= 300), 0)
            AS double precision) AS pasajeros,
       CAST(COALESCE(SUM(v.numerobajadas) FILTER (WHERE v.valido AND v.numerobajadas <= 300), 0)
            AS double precision) AS bajadas_viajes,
       COUNT(*) FILTER (WHERE v.valido) AS salidas,
       SUM(s.subidas) AS subidas, SUM(s.bajadas) AS bajadas, SUM(s.filas) AS filas_segmento,
       COUNT(s.idprogramacion) AS viajes_con_timbradas,
       es.id_estacionalidad, es.id_estacionalidad_anio,
       MAX(s.marca) AS ultima_actualizacion
  FROM viajes v
  LEFT JOIN segmentos_viaje s ON s.idprogramacion = v.idprogramacion
  LEFT JOIN estacion es ON es.proceso = v.proceso AND es.fecha = CAST(v.franja AS date)
 GROUP BY v.nombre, v.idruta, v.proceso, v.idempresa, v.franja, es.id_estacionalidad, es.id_estacionalidad_anio
 ORDER BY ultima_actualizacion, ruta, fecha, hora
 LIMIT :limite
"""

# Panel de 15 minutos del pronóstico de corto plazo (RF-005, app/servicios/panel_corto_plazo.py): los viajes de la
# ruta que salieron entre :desde y :fin, sus subidas por segmento y bloque de 15 minutos de timbradas_segmentos (el
# bloque de hora_inicio, como lo escribe tg_timbrada_segmento) en los días pedidos, solo lo actualizado antes de
# :hasta (la marca de agua de la ejecución; sin marca, la fila de la carga inicial cuenta), y los viajes que iniciaron
# en cada bloque (progvehiculos.fechainicio: la oferta ya observada). Valores siempre enlazados.
_SQL_SUBIDAS_15MIN = """
WITH viajes AS (
    SELECT pv.idprogramacion
      FROM progvehiculos pv
     WHERE pv.idruta = :idruta AND pv.fechasalida >= :desde AND pv.fechasalida < :fin
)
SELECT ts.id_segmento, ts.fecha,
       CAST(EXTRACT(HOUR FROM ts.hora_inicio) AS integer) * 4
         + CAST(FLOOR(EXTRACT(MINUTE FROM ts.hora_inicio) / 15) AS integer) AS bloque,
       CAST(SUM(ts.subidas) AS double precision) AS subidas
  FROM viajes v
  JOIN timbradas_segmentos ts ON ts.id_viaje = v.idprogramacion
 WHERE ts.id_segmento = ANY(CAST(:segmentos AS bigint[]))
   AND ts.fecha = ANY(CAST(:fechas AS date[]))
   AND ts.subidas > 0
   AND COALESCE(ts.ultimaactualizacion < CAST(:hasta AS timestamptz), true)
 GROUP BY ts.id_segmento, ts.fecha, bloque
 ORDER BY ts.fecha, bloque, ts.id_segmento
 LIMIT :limite
"""
_SQL_SALIDAS_15MIN = """
SELECT CAST(pv.fechainicio AS date) AS fecha,
       CAST(EXTRACT(HOUR FROM pv.fechainicio) AS integer) * 4
         + CAST(FLOOR(EXTRACT(MINUTE FROM pv.fechainicio) / 15) AS integer) AS bloque,
       CAST(COUNT(*) AS double precision) AS salidas
  FROM progvehiculos pv
 WHERE pv.idruta = :idruta AND pv.fechainicio >= :desde AND pv.fechainicio < :fin
   AND CAST(pv.fechainicio AS date) = ANY(CAST(:fechas AS date[]))
 GROUP BY 1, 2
 ORDER BY 1, 2
 LIMIT :limite
"""

# Variantes fijas del SELECT de la lista blanca (RNF-005): fin de la ventana (`hasta`) y rutas del trabajo. Con rutas,
# solo las franjas de esas rutas se re-agregan (viajes, segmentos y estacionalidad): la misma búsqueda de lo cambiado
# por marca de agua y menos trabajo después (docs/evidencias/cola/lectura_por_ruta_replica.txt, EXPLAIN como
# lector_ia). Los valores van siempre como parámetros enlazados (:hasta, :rutas).
FILTRO_HASTA_SEGMENTOS = " AND ts.ultimaactualizacion < :hasta"
FILTRO_RUTAS_SEGMENTOS = "\n       AND r.nombre = ANY(CAST(:rutas AS text[]))"

# §10.1 «ocupación actual por segmento»: los viajes no cancelados de las franjas (ruta, fecha, hora de salida) que
# entregó la lectura incremental, con sus subidas y bajadas por segmento sumadas en todos sus bloques de 15 minutos
# (lo que escribe tg_timbrada_segmento; un viaje puede cruzar un segmento en dos bloques, errata E2), el vehículo y el
# conductor (que se seudonimiza al leer, §18; nunca sale de esta capa en claro). Las franjas van como tres arreglos
# enlazados; nada del texto viene de la petición. app/servicios/ocupacion.py calcula la carga a bordo por segmento.
_SQL_CARGA_SEGMENTOS = """
WITH franjas AS (
    SELECT DISTINCT f.ruta, f.fecha, f.hora
      FROM unnest(CAST(:rutas AS text[]), CAST(:fechas AS date[]), CAST(:horas AS integer[])) AS f(ruta, fecha, hora)
), viajes AS (
    SELECT pv.idprogramacion, r.nombre AS ruta, pv.idruta, f.fecha, f.hora, pv.idvehiculo, pv.idconductor,
           (pv.finalizado = 'S') AS terminado
      FROM franjas f
      JOIN rutas r ON r.nombre = f.ruta
      JOIN progvehiculos pv ON pv.idruta = r.idruta
                           AND pv.fechasalida >= f.fecha + make_interval(hours => f.hora)
                           AND pv.fechasalida < f.fecha + make_interval(hours => f.hora + 1)
     WHERE pv.cancelada = 'N'
       AND (CAST(:proceso AS text) IS NULL OR r.proceso = CAST(:proceso AS text))
)
SELECT v.ruta, v.idruta, v.fecha, v.hora, v.idprogramacion AS id_viaje, v.idvehiculo AS vehiculo,
       v.idconductor AS conductor, v.terminado, ts.id_segmento, rs.nro_segmento,
       SUM(ts.subidas) AS subidas, SUM(ts.bajadas) AS bajadas
  FROM viajes v
  JOIN timbradas_segmentos ts ON ts.id_viaje = v.idprogramacion
  JOIN rutas_segmentos rs ON rs.id = ts.id_segmento
 GROUP BY v.ruta, v.idruta, v.fecha, v.hora, v.idprogramacion, v.idvehiculo, v.idconductor, v.terminado,
          ts.id_segmento, rs.nro_segmento
 ORDER BY v.idprogramacion, rs.nro_segmento
 LIMIT :limite
"""
COLUMNAS_CARGA_SEGMENTOS = ("ruta", "idruta", "fecha", "hora", "id_viaje", "vehiculo", "conductor", "terminado",
                            "id_segmento", "nro_segmento", "subidas", "bajadas")


def identificador_entero(valor):
    """Un identificador entero que pandas volvió float (la columna traía algún nulo: 700001 -> 700001.0) vuelve a ser
    entero; lo demás queda igual. Así el seudónimo del conductor y el texto del vehículo no dependen de que la lectura
    traiga o no un nulo en otra fila."""
    if isinstance(valor, float) and valor.is_integer():
        return int(valor)
    return valor


def seudonimos(crudos) -> list[str | None]:
    """§18: el seudónimo de cada identificador de conductor (alertas.seudonimo_conductor: «cnd_» + HMAC-SHA256 con
    SEUDONIMO_SECRETO), en el mismo orden; nulo sin valor o sin secreto. Es la ÚNICA seudonimización de la capa de
    lectura: la usan seudonimizar_conductores (ocupación por segmento) y seudonimizar_viajes (alertas de §5.3), así
    que un conductor tiene el mismo seudónimo por los dos caminos. El id se normaliza antes (alertas.id_texto: 77,
    77.0 y «77» son el mismo, aunque un nulo en otra fila vuelva float la columna) y el HMAC se calcula una vez por
    valor distinto (la carga por segmentos repite el conductor de un viaje en cada uno de sus segmentos)."""
    from app.servicios.alertas import id_texto, seudonimo_conductor

    memoria: dict[str | None, str | None] = {}
    salida = []
    for valor in crudos:
        texto = id_texto(valor)
        if texto not in memoria:
            memoria[texto] = seudonimo_conductor(texto)
        salida.append(memoria[texto])
    return salida


def seudonimizar_conductores(d: pd.DataFrame) -> pd.DataFrame:
    """§18: la columna «conductor» de cada fila pasa a su seudónimo (seudonimos); sin secreto queda vacía. El dato en
    claro nunca sale de la capa de lectura."""
    if "conductor" not in d.columns or not len(d):
        return d
    return d.assign(conductor=seudonimos(d["conductor"]))


# §5.3 «viaje, conductor y vehículo, cuando aplique» (ALT-006 y ALT-009): los viajes programados de UNA ruta con salida
# en [desde, hasta) de progvehiculos, con su estado, la salida real (fechainicio), la marca de plazo de salida excedido
# y, en el ciclo integrado, cuántas filas de timbradas_segmentos tiene cada uno (un viaje válido sin ellas no llegó a la
# segmentación). La ventana va sobre date_trunc('hour', fechasalida), la expresión del índice propuesto 3, y el conteo
# por id_viaje usa el índice propuesto 2 (docs/evidencias/replica/propuesta_indices.sql). idconductor se lee solo para
# seudonimizarlo enseguida (seudonimizar_viajes, HMAC de §18): nunca sale de esta capa en claro.
_SQL_VIAJES_RUTA = """
WITH viajes AS (
    SELECT pv.idprogramacion, pv.idvehiculo, pv.idconductor, pv.fechasalida, pv.fechainicio, pv.finalizado,
           pv.cancelada, pv.excedeplazosalida, pv.numeropasajeros
      FROM progvehiculos pv
      JOIN rutas r ON r.idruta = pv.idruta
     WHERE (r.nombre = :ruta OR CAST(r.idruta AS text) = :ruta)
       AND (CAST(:proceso AS text) IS NULL OR r.proceso = CAST(:proceso AS text))
       AND date_trunc('hour', pv.fechasalida) >= CAST(:desde AS timestamp)
       AND date_trunc('hour', pv.fechasalida) < CAST(:hasta AS timestamp)
     ORDER BY pv.fechasalida, pv.idprogramacion
     LIMIT :limite
){cte_segmentos}
SELECT v.idprogramacion AS viaje, v.idvehiculo AS vehiculo, v.idconductor, v.fechasalida AS salida,
       v.fechainicio AS salida_real, v.finalizado, v.cancelada, v.excedeplazosalida, v.numeropasajeros{col_segmentos}
  FROM viajes v{union_segmentos}
 ORDER BY v.fechasalida, v.idprogramacion
"""
# Variantes fijas de la lectura de viajes: con el conteo de segmentos (ciclo integrado, que lee la capa de segmentos) o
# sin él (catálogos: la capa de segmentos no cubre el mismo periodo que la serie empaquetada).
_SEGMENTOS_VIAJE = {
    True: (",\nsegmentos AS (\n    SELECT ts.id_viaje, COUNT(*) AS filas\n      FROM timbradas_segmentos ts\n"
           "      JOIN viajes v ON v.idprogramacion = ts.id_viaje\n     GROUP BY ts.id_viaje\n)",
           ", COALESCE(s.filas, 0) AS filas_segmento", "\n  LEFT JOIN segmentos s ON s.id_viaje = v.idprogramacion"),
    False: ("", ", CAST(NULL AS bigint) AS filas_segmento", ""),
}
LIMITE_VIAJES = 5000      # viajes por lectura (una ruta tiene unos 300 por día)


def sql_viajes_ruta(con_segmentos: bool) -> str:
    """El SELECT constante de la lectura de viajes de una ruta (lista blanca), con o sin el conteo de segmentos."""
    cte, columna, union = _SEGMENTOS_VIAJE[bool(con_segmentos)]
    return _SQL_VIAJES_RUTA.format(cte_segmentos=cte, col_segmentos=columna, union_segmentos=union)


def seudonimizar_viajes(d: pd.DataFrame) -> pd.DataFrame:
    """§18 «Exposición de datos»: reemplaza idconductor por su seudónimo (seudonimos, la misma función de la ocupación
    por segmento; nulo sin secreto) y quita la columna en claro. Lo usan todas las lecturas de viajes."""
    if d is None:
        return d
    salida = d.drop(columns=["idconductor"], errors="ignore").copy()
    salida["conductor"] = seudonimos(d["idconductor"] if "idconductor" in d.columns else [None] * len(d))
    return salida


# Punto de despacho (§8.1, alertas georreferenciadas): inicio del segmento 1 de la ruta, configuración activa primero.
_SQL_UBICACION_DESPACHO = """
SELECT ST_AsGeoJSON(ST_StartPoint(ST_GeometryN(rs.geom_segmento, 1)), 7) AS punto
  FROM rutas_segmentos rs
  JOIN rutas r ON r.idruta = rs.idruta
  LEFT JOIN rutas_segmentos_config c ON c.id = rs.id_config
 WHERE rs.nro_segmento = 1 AND (r.nombre = :ruta OR CAST(r.idruta AS text) = :ruta)
 ORDER BY COALESCE(c.activo, rs.activo, true) DESC, rs.id_config DESC
 LIMIT 1
"""

# Contexto operacional y catálogos (RF-003, §11.2): columnas explícitas, sin datos sensibles (minimización, §18):
# de "Procesos" no se leen las credenciales de interfaces que tiene la tabla real.
CONSULTAS_CONTEXTO = {
    "procesos": ('SELECT proceso, nombre, estado, toleranciatiempo, id_estacionalidad, ultima_estacionalidad '
                 'FROM "Procesos" ORDER BY proceso'),
    "rutas": ("SELECT idruta, nombre, codigo, proceso, idempresa, frecuenciadespachos, primerdespacho, estado_ruta, "
              "idrutageo, tolerancia, tolsalida, maneja_zonas, id_tipo_tarifa, zona_tolerancia_inicio, "
              "zona_tolerancia_fin FROM rutas ORDER BY idruta"),
    "dias_semana": "SELECT id_dia_semana, dia_semana FROM dias_semana ORDER BY id_dia_semana",
    "estacionalidades": ("SELECT id_estacionalidad, proceso, estacionalidad, nombre, descripcion "
                         "FROM estacionalidades ORDER BY id_estacionalidad"),
    "estacionalidades_anio": (
        "SELECT ea.id_estacionalidad_anio, ea.proceso, ea.id_estacionalidad, e.estacionalidad, e.nombre, ea.ano, "
        "ea.fecha_inicio, ea.fecha_fin, (ea.fecha_fin - ea.fecha_inicio) AS dias "
        "FROM estacionalidades_anio ea LEFT JOIN estacionalidades e ON e.id_estacionalidad = ea.id_estacionalidad "
        "ORDER BY ea.fecha_inicio, ea.id_estacionalidad_anio"),
    "novedades_viales": ("SELECT id_novedad_vial, proceso, novedad, nombre, descripcion FROM novedades_viales "
                         "ORDER BY id_novedad_vial"),
    "novedades_viales_fecha": (
        "SELECT nvf.id_novedad_vial_fecha, nvf.proceso, nvf.id_novedad_vial, nv.novedad, nv.nombre, nvf.fecha, "
        "nvf.hora_inicio, nvf.hora_fin, nvf.potencial_efecto, nvf.porcentaje_impacto "
        "FROM novedades_viales_fecha nvf LEFT JOIN novedades_viales nv ON nv.id_novedad_vial = nvf.id_novedad_vial "
        "ORDER BY nvf.fecha, nvf.hora_inicio, nvf.id_novedad_vial_fecha"),
    "novedades_viales_ruta": ("SELECT id_novedad_vial_ruta, id_novedad_vial_fecha, id_ruta FROM novedades_viales_ruta "
                              "ORDER BY id_novedad_vial_ruta"),
    "segmentos": ("SELECT rs.id AS id_segmento, rs.id_config, rs.idruta, rs.idrutageo, rs.nro_segmento, rs.activo, "
                  "rs.longitud_m FROM rutas_segmentos rs ORDER BY rs.idruta, rs.id_config, rs.nro_segmento"),
    "segmentos_config": ("SELECT id, idruta, idrutageo, tipo_agrupacion, numero_segmentos, activo, fecha_creacion "
                         "FROM rutas_segmentos_config ORDER BY id"),
    # §6.1 «frecuenciadespachos» y §6.2 «headway vigente» (frecuencias_despacho): solo las tres columnas que hacen
    # falta, para que una columna ajena que falte en otra versión de la tabla rutas no tumbe esta lectura.
    "frecuencias": "SELECT idruta, nombre, frecuenciadespachos FROM rutas ORDER BY idruta",
}

_PROHIBIDAS = re.compile(
    r"\b(INSERT|UPDATE|DELETE|MERGE|UPSERT|CREATE|ALTER|DROP|TRUNCATE|GRANT|REVOKE|COPY|CALL|DO|EXECUTE|PREPARE|"
    r"VACUUM|ANALYZE|REINDEX|CLUSTER|LOCK|COMMENT|REFRESH|SECURITY|LISTEN|NOTIFY|INTO|SET|RESET|BEGIN|COMMIT|"
    r"ROLLBACK|SAVEPOINT|NEXTVAL|SETVAL|PG_SLEEP|DBLINK|LO_IMPORT|LO_EXPORT)\b|\bFOR\s+(UPDATE|SHARE|NO\s+KEY|KEY)\b",
    re.IGNORECASE)


class OperacionNoPermitida(PermissionError):
    """La fuente operacional es de solo lectura: solo se aceptan SELECT."""


class SentenciaCancelada(RuntimeError):
    """La fuente canceló la sentencia por statement_timeout (SQLSTATE 57014): la base respondió y está arriba; la que
    no cupo es la consulta. Solo la lanza una fuente creada con cancelacion_responde=True (la capa de segmentos, que
    parte la lectura): el circuit breaker no la cuenta como caída. La excepción original queda en __cause__."""


SQLSTATE_CANCELADA = "57014"


def _filas_select(conn, sentencia, parametros, cancelacion_responde: bool):
    """Filas del SELECT en la transacción abierta; con cancelacion_responde, el tiempo agotado sube como
    SentenciaCancelada (el texto es el mensaje de PostgreSQL, sin la sentencia ni sus parámetros)."""
    try:
        return conn.execute(sentencia, parametros or {}).mappings().all()
    except Exception as exc:
        original = getattr(exc, "orig", None)
        if cancelacion_responde and getattr(original, "sqlstate", None) == SQLSTATE_CANCELADA:
            raise SentenciaCancelada(str(original).strip()) from exc
        raise


def _normalizar_marca(marca):
    if marca is None:
        return MARCA_INICIAL
    m = pd.Timestamp(marca)
    if m.tzinfo is None:
        m = m.tz_localize(ZONA)
    return m.to_pydatetime()


def _marcas_con_zona(serie):
    """Marcas leídas (timestamp sin zona en America/Bogota, o con zona) -> datetime con zona."""
    s = pd.to_datetime(serie)
    if getattr(s.dt, "tz", None) is None:
        s = s.dt.tz_localize(ZONA, ambiguous="NaT", nonexistent="NaT")
    return s


def validar_solo_select(sql):
    """Lanza OperacionNoPermitida si `sql` no es una única sentencia SELECT (o WITH ... SELECT) sin escrituras."""
    if not isinstance(sql, str) or not sql.strip():
        raise OperacionNoPermitida("Sentencia vacía.")
    limpio = re.sub(r"--[^\n]*", " ", sql)
    limpio = re.sub(r"/\*.*?\*/", " ", limpio, flags=re.DOTALL)
    sin_literales = re.sub(r"'(?:[^']|'')*'", "''", limpio)
    cuerpo = sin_literales.strip().rstrip(";").strip()
    if ";" in cuerpo:
        raise OperacionNoPermitida("Solo se permite una sentencia por consulta.")
    primera = cuerpo.split(None, 1)[0].upper()
    if primera not in ("SELECT", "WITH"):
        raise OperacionNoPermitida(f"La fuente es de solo lectura: se rechaza una sentencia {primera}.")
    m = _PROHIBIDAS.search(cuerpo)
    if m:
        raise OperacionNoPermitida(f"La fuente es de solo lectura: se rechaza «{m.group(0)}» dentro de la consulta.")
    return True


def huella_fila(valores) -> str:
    """md5 (16 hex) de los valores de una fila en orden fijo; None y NaN cuentan como vacío."""
    partes = []
    for v in valores:
        if v is None or (isinstance(v, float) and math.isnan(v)):
            partes.append("∅")
        elif isinstance(v, float) and v.is_integer():
            partes.append(str(int(v)))
        else:
            partes.append(str(v))
    return hashlib.md5("\x1f".join(partes).encode("utf-8"), usedforsecurity=False).hexdigest()[:16]


def _huellas_previas(estado_previo, tabla):
    """Huellas {llave: huella} del estado incremental anterior, solo si es de esta tabla y de la versión vigente del
    formato (VERSION_ESTADO); si no, ninguna, y entonces ninguna fila cuenta como repetida."""
    if (estado_previo and estado_previo.get("tabla") == tabla
            and int(estado_previo.get("version") or 0) == VERSION_ESTADO):
        return dict(estado_previo.get("huellas") or {})
    return {}


def _tipo_llegada(carga_inicial, conocida, posterior):
    """Tipo de llegada de una fila entregada: en la carga inicial todo es «carga_inicial» (no cuenta como dato
    tardío, OPOR-001); después, «modificada» si la llave ya se conocía y «nueva» o «tardia» según su marca sea
    posterior o no a la marca anterior."""
    if carga_inicial:
        return "carga_inicial"
    if conocida:
        return "modificada"
    return "nueva" if posterior else "tardia"


# ------------------------------------------------------------------ partición por ruta (RNF-005)
def huellas_de_la_ruta(estado: dict | None, ruta: str) -> dict | None:
    """Las huellas de UNA ruta (llaves «ruta|fecha|hora») de un estado incremental; None si no hay estado."""
    if not isinstance(estado, dict):
        return None
    huellas = {k: h for k, h in (estado.get("huellas") or {}).items() if str(k).split("|", 1)[0] == ruta}
    return {**estado, "huellas": huellas}


@dataclass(frozen=True)
class Particion:
    """Lo que lee un trabajo del ciclo (RNF-005): el proceso, sus rutas (None = todas las de la fuente) y la marca de
    agua y las huellas de cada ruta. Las rutas sin marca propia usan la frontera de las lecturas de todas las rutas
    del proceso (marca_resto y estado_resto); sin ninguna, la marca inicial (carga completa)."""

    proceso: str
    rutas: tuple[str, ...] | None = None
    marcas: Mapping[str, datetime] = field(default_factory=dict)
    estados: Mapping[str, dict] = field(default_factory=dict)
    marca_resto: datetime | None = None
    estado_resto: dict | None = None

    def marca_de(self, ruta: str | None) -> datetime:
        """Marca de agua de la ruta (con zona); la frontera si la ruta no tiene marca propia."""
        crudo = self.marcas.get(ruta, self.marca_resto) if ruta is not None else self.marca_resto
        return _normalizar_marca(crudo)

    def estado_de(self, ruta: str | None) -> dict | None:
        """Huellas de la ventana de solape de la ruta (las propias o, sin marca propia, las de la frontera)."""
        if ruta is not None and ruta in self.estados:
            return self.estados[ruta]
        return self.estado_resto if ruta is None else huellas_de_la_ruta(self.estado_resto, ruta)

    def rutas_conocidas(self) -> list[str]:
        """Las rutas del trabajo o, si es de todas, las que ya tienen marca propia."""
        return list(self.rutas) if self.rutas is not None else sorted(self.marcas)

    def marca_lectura(self) -> datetime:
        """Desde dónde se lee la fuente: la marca más antigua de las rutas del trabajo (y la frontera, si el trabajo es
        de todas las rutas: una ruta nueva todavía no tiene marca propia)."""
        marcas = [self.marca_de(r) for r in self.rutas_conocidas()]
        if self.rutas is None or not marcas:
            marcas.append(self.marca_de(None))
        return min(marcas)

    def marca_anterior(self) -> datetime | None:
        """La marca que muestra la ejecución: la de su ruta o, si es de todas, la más avanzada (la marca global de
        antes). None si nunca se leyó nada."""
        marcas = [self.marca_de(r) for r in self.rutas_conocidas()]
        if self.rutas is None:
            marcas.append(self.marca_de(None))
        valida = [m for m in marcas if m > MARCA_INICIAL]
        return max(valida) if valida else None


@dataclass
class LecturaParticion:
    """Resultado de leer una partición: las filas entregadas, la marca nueva y las huellas de cada ruta leída, la marca
    mayor de toda la lectura (None si no llegó nada) y el resumen (totales y detalle por ruta)."""

    df: pd.DataFrame
    marcas: dict[str, datetime]
    estados: dict[str, dict]
    marca_global: datetime | None
    resumen: dict | None = None


def _sumar_resumenes(base: dict, por_ruta: dict[str, dict]) -> dict:
    """Totales de la lectura (los mismos campos de una lectura sin partir) y el detalle compacto por ruta."""
    campos = ("entregadas", "nuevas", "tardias", "modificadas", "repetidas_solape", "duplicadas_llave",
              "huellas_estado", "descartadas_marca_ruta")
    total = dict(base)
    for campo in campos:
        total[campo] = int(sum(int(r.get(campo) or 0) for r in por_ruta.values()))
    total["rutas"] = {r: {k: v for k, v in res.items() if k in (*campos, "leidas", "marca_anterior", "marca_nueva")}
                      for r, res in sorted(por_ruta.items(), key=lambda x: str(x[0]))}
    return total


def _avanzar_a_la_frontera(lectura: LecturaParticion, particion: Particion) -> None:
    """Un trabajo de TODAS las rutas leyó la fuente completa hasta su marca mayor: cada ruta conocida queda en esa
    frontera aunque no le haya llegado nada (como la marca global de antes), y la frontera también."""
    if lectura.marca_global is None:
        return
    for ruta in {*particion.marcas, *lectura.marcas}:
        previa = lectura.marcas.get(ruta, particion.marca_de(ruta))
        lectura.marcas[ruta] = max(previa, lectura.marca_global)


def leer_particion(fuente, particion: Particion, hasta=None) -> LecturaParticion:
    """Lectura incremental de la partición de un trabajo (RNF-005). Las fuentes con lectura por ruta propia
    (FuenteParquet, FuentePostgresSoloLectura) filtran cada ruta con su marca; a cualquier otra (dobles de prueba) se
    le pide la lectura de siempre desde la marca más antigua y luego se filtran las rutas del trabajo."""
    propia = getattr(fuente, "leer_particion", None)
    lectura = propia(particion, hasta) if callable(propia) else _leer_particion_generica(fuente, particion, hasta)
    if particion.rutas is None:
        _avanzar_a_la_frontera(lectura, particion)
    return lectura


def _leer_particion_generica(fuente, particion: Particion, hasta) -> LecturaParticion:
    marca = particion.marca_lectura()
    estado = particion.estado_resto if particion.rutas is None else None
    d, nueva = leer_con_estado(fuente, None if marca <= MARCA_INICIAL else marca, hasta, estado)
    if particion.rutas is not None and d is not None and "ruta" in d.columns:
        d = d[d["ruta"].astype(str).isin(particion.rutas)].reset_index(drop=True)
    marca_global = None if nueva is None else _normalizar_marca(nueva)
    rutas = particion.rutas_conocidas()
    marcas = {r: max(particion.marca_de(r), marca_global) for r in rutas} if marca_global is not None else {}
    return LecturaParticion(df=d, marcas=marcas, estados={}, marca_global=marca_global,
                            resumen=getattr(fuente, "resumen_lectura", None))


def _claves_de_ruta(d: pd.DataFrame) -> pd.Series:
    """La ruta de cada fila como texto (None si falta): la llave de la partición."""
    return d["ruta"].map(lambda r: None if r is None or (isinstance(r, float) and math.isnan(r)) else str(r))


def _claves_o_vacias(d: pd.DataFrame) -> pd.Series:
    """Las claves de ruta de lo leído; sin filas o sin columna de ruta, todas None (un solo grupo, la frontera)."""
    if len(d) and "ruta" in d.columns:
        return _claves_de_ruta(d)
    return pd.Series([None] * len(d), index=d.index, dtype=object)


def _orden_de_ruta(ruta: str | None) -> tuple[bool, str]:
    return ruta is None, str(ruta)


def _filas_de_la_ruta(claves: pd.Series, ruta: str | None):
    """Máscara (numpy) de las filas de UNA ruta (None: las filas sin ruta)."""
    return (claves.isna() if ruta is None else claves == ruta).to_numpy(dtype=bool)


class _LecturaRuta(NamedTuple):
    """Lo que se leyó de UNA ruta: filas entregadas, su marca nueva (la suya o la mayor que se le leyó), el resumen,
    el estado de huellas y la marca mayor de las filas posteriores a su marca (None si no pasó ninguna)."""

    filas: pd.DataFrame
    marca: datetime
    resumen: dict
    estado: dict
    leida: datetime | None


def _marca_mayor(marcas: pd.Series) -> datetime | None:
    """La marca mayor de una serie de marcas con zona; None si no hay ninguna válida."""
    mayor = marcas.max() if len(marcas) else pd.NaT
    return None if pd.isna(mayor) else pd.Timestamp(mayor).to_pydatetime()


def _juntar_lecturas(d: pd.DataFrame, lecturas: dict[str | None, _LecturaRuta]) -> LecturaParticion:
    """Une las lecturas de cada ruta: las filas en el orden de sus marcas, la marca y las huellas de cada ruta y la
    marca mayor de lo que se LEYÓ (filas posteriores a la marca de su ruta), como la marca global de antes. La marca
    propia de una ruta adelantada no cuenta: si todas sus filas se descartaron porque ya se le entregaron, un trabajo
    de todas las rutas con `hasta` anterior a esa marca movería a las demás rutas (y a la frontera) más allá de lo que
    se les leyó, y sus días siguientes no se leerían nunca."""
    partes = [v.filas for v in lecturas.values()]
    df = pd.concat(partes, ignore_index=True) if partes else d
    if len(df) and "ultima_actualizacion" in df.columns:
        df = df.sort_values("ultima_actualizacion", kind="stable").reset_index(drop=True)
    con_ruta = {r: v for r, v in lecturas.items() if r is not None}
    return LecturaParticion(df=df, marcas={r: v.marca for r, v in con_ruta.items()},
                            estados={r: v.estado for r, v in con_ruta.items()},
                            marca_global=max((v.leida for v in lecturas.values() if v.leida is not None),
                                             default=None),
                            resumen={("(sin ruta)" if r is None else r): v.resumen for r, v in lecturas.items()})


def _posteriores_a_su_marca(d: pd.DataFrame, marcas: pd.Series, particion: Particion, solape_min: int = 0):
    """Máscara (numpy) de las filas cuya marca es posterior a la marca de SU ruta (menos el solape, si lo hay): lo
    anterior ya se le entregó a esa ruta. Una fila sin ruta se compara con la frontera."""
    claves = _claves_de_ruta(d) if len(d) else pd.Series([], dtype=object)
    mascara = pd.Series(False, index=d.index)
    for ruta in pd.unique(claves):
        marca = particion.marca_de(ruta)
        desde = marca - timedelta(minutes=solape_min) if marca > MARCA_INICIAL else marca
        de_la_ruta = claves.isna() if ruta is None else claves == ruta
        mascara |= de_la_ruta & (marcas > pd.Timestamp(desde))
    return mascara.to_numpy(dtype=bool)


class FuenteParquet:
    """Fuente offline por defecto: demanda horaria del proyecto (datos/demanda_horaria.parquet)."""

    nombre = "parquet"
    admite_estado = False
    proceso = PROCESO_DEFECTO     # la serie empaquetada es de Sobusa (llave del proceso en la marca por ruta)

    def __init__(self, cargador=None):
        # cargador() -> DataFrame con el contrato de datos.demanda_horaria(); inyectable en pruebas.
        self._cargador = cargador

    def _cargar(self, hasta):
        if self._cargador is not None:
            return self._cargador()
        from . import datos
        # §6.1 Bajadas: la serie empaquetada con bajadas_viajes (datos/bajadas_horaria.parquet), la misma definición
        # de la lectura integrada; sin el archivo, el lote llega sin la columna y el histórico la deja nula
        return datos.con_bajadas(datos.demanda_horaria(hasta=hasta))

    def leer_incremental(self, marca_agua=None, hasta=None):
        """Filas con ultima_actualizacion > marca_agua y fecha <= hasta (si se da). Devuelve (df, nueva_marca)."""
        marca = _normalizar_marca(marca_agua)
        d = self._cargar(hasta)
        if hasta is not None:
            h = hasta.date() if isinstance(hasta, datetime) else hasta
            d = d[pd.to_datetime(d["fecha"]).dt.date <= h]
        ua = pd.to_datetime(d["ultima_actualizacion"])
        if getattr(ua.dt, "tz", None) is None:
            ua = ua.dt.tz_localize(ZONA)
        d = d[(ua > pd.Timestamp(marca)).values].copy()
        if len(d):
            d = d.sort_values(["ultima_actualizacion", "ruta", "fecha", "hora"]).reset_index(drop=True)
            nueva = pd.Timestamp(d["ultima_actualizacion"].max()).to_pydatetime()
        else:
            nueva = marca
        return d, nueva

    def leer_particion(self, particion: Particion, hasta=None) -> LecturaParticion:
        """RNF-005: las filas de las rutas del trabajo (todas si particion.rutas es None) con fecha <= hasta, cada una
        con ultima_actualizacion > la marca de SU ruta. La marca nueva de cada ruta es la mayor que se le leyó."""
        d = self._cargar(hasta)
        if hasta is not None:
            h = hasta.date() if isinstance(hasta, datetime) else hasta
            d = d[pd.to_datetime(d["fecha"]).dt.date <= h]
        if particion.rutas is not None:
            d = d[d["ruta"].astype(str).isin(particion.rutas)]
        d = d[_posteriores_a_su_marca(d, _marcas_con_zona(d["ultima_actualizacion"]), particion)].copy()
        marcas: dict[str, datetime] = {r: particion.marca_de(r) for r in particion.rutas or ()}
        marca_global = None
        if len(d):
            d = d.sort_values(["ultima_actualizacion", "ruta", "fecha", "hora"]).reset_index(drop=True)
            leidas = _marcas_con_zona(d["ultima_actualizacion"])
            maximos = leidas.groupby(_claves_de_ruta(d)).max()
            marcas.update({str(r): pd.Timestamp(m).to_pydatetime() for r, m in maximos.items()})
            marca_global = pd.Timestamp(leidas.max()).to_pydatetime()
        return LecturaParticion(df=d, marcas=marcas, estados={}, marca_global=marca_global)

    def ubicacion_despacho(self, ruta):
        """Punto de despacho de la ruta (GeoJSON Point) del catálogo empaquetado; None si la ruta no lo tiene."""
        return punto_despacho_empaquetado(ruta)


def _idruta(ruta) -> int | None:
    """idruta de una ruta dada por nombre o por id, según el catálogo empaquetado (None si no existe)."""
    try:
        from app.servicios import datos

        return int(datos.ruta_info(str(ruta))["idruta"])
    except (KeyError, ValueError, TypeError, OSError):
        return None


def punto_despacho_empaquetado(ruta) -> dict | None:
    idruta = _idruta(ruta)
    punto = PUNTO_DESPACHO_EMPAQUETADO.get(idruta) if idruta is not None else None
    if punto is None:
        return None
    return {"type": "Point", "coordinates": [punto[0], punto[1]]}


class FuentePostgresSoloLectura:
    """Lectura incremental de las tablas existentes con un usuario SELECT (nunca escribe).

    Después de cada leer_incremental quedan `resumen_lectura` (métricas: leidas, entregadas, nuevas, tardias,
    modificadas, repetidas_solape, duplicadas_llave) y `estado_incremental` (huellas de la ventana de solape) para
    guardarlos con la ejecución; la siguiente lectura recibe ese estado en `estado_previo`. `repetidas_por_llave` trae
    todas las filas leídas cuya llave natural se repite (la lectura entrega solo la más reciente de cada una), para que
    quien valida la unicidad las reporte (§6.3; app/servicios/consolidados.py)."""

    nombre = "postgres"
    admite_estado = True

    def __init__(self, url=None, tabla=TABLA_CICLO, statement_timeout_ms=None, motor=None, limite=500000,
                 solape_min=None, proceso=None, cancelacion_responde=False):
        # cancelacion_responde: un statement_timeout sube como SentenciaCancelada y no abre el circuit breaker
        # (quien lee decide cómo partir la lectura; app/servicios/segmentos_refresco.py). Por omisión, como siempre.
        self.cancelacion_responde = bool(cancelacion_responde)
        self.url = url or os.environ.get("FUENTE_DATABASE_URL", "")
        if not self.url and motor is None:
            raise ValueError("FUENTE_DATABASE_URL no está definida: la fuente PostgreSQL necesita una URL de solo "
                             "lectura.")
        if tabla not in TABLAS_PERMITIDAS:
            raise OperacionNoPermitida(f"Tabla no permitida: {tabla!r}.")
        self.tabla = tabla
        if proceso is None:
            proceso = os.environ.get("FUENTE_PROCESO", PROCESO_DEFECTO)
        # Vacío o «*»: todos los procesos (operadores) de la base; por omisión, el de Sobusa.
        self.proceso = None if str(proceso).strip() in ("", "*") else str(proceso).strip()
        self._ubicaciones: dict[str, dict | None] = {}
        self.statement_timeout_ms = int(statement_timeout_ms or os.environ.get("FUENTE_STATEMENT_TIMEOUT_MS") or 30000)
        if self.statement_timeout_ms <= 0:
            raise ValueError("FUENTE_STATEMENT_TIMEOUT_MS debe ser > 0 (0 desactivaría el límite de tiempo).")
        if solape_min is None:
            solape_min = os.environ.get("FUENTE_SOLAPE_MIN") or SOLAPE_MIN_DEFECTO
        self.solape_min = int(solape_min)
        if self.solape_min < 0:
            raise ValueError("FUENTE_SOLAPE_MIN no puede ser negativo.")
        self.limite = int(limite)
        self._motor = motor
        self.resumen_lectura: dict | None = None
        self.estado_incremental: dict | None = None
        self.repetidas_por_llave: pd.DataFrame | None = None
        self.resumen_carga: dict | None = None

    # ------------------------------------------------------------------ acceso
    def _engine(self):
        if self._motor is None:
            from sqlalchemy import create_engine
            self._motor = create_engine(self.url, pool_pre_ping=True, pool_size=2, max_overflow=0)
        return self._motor

    def consultar(self, sql, parametros=None):
        """Ejecuta un único SELECT (texto, text() o sqlalchemy Select) en una transacción READ ONLY con
        statement_timeout y TimeZone America/Bogota, y devuelve un DataFrame. Lo que no sea SELECT se rechaza antes de
        abrir la conexión."""
        from sqlalchemy import text
        from sqlalchemy.sql import Select
        from sqlalchemy.sql.elements import TextClause

        if isinstance(sql, Select):
            validar_solo_select(str(sql))                 # defensa adicional sobre la sentencia compilada
            sentencia = sql
        elif isinstance(sql, TextClause):
            validar_solo_select(sql.text)
            sentencia = sql
        else:
            validar_solo_select(sql)
            sentencia = text(sql)
        timeout = int(self.statement_timeout_ms)          # entero validado: no hay texto del usuario en el SET

        def _leer():
            with self._engine().connect() as conn:
                try:
                    conn.execute(text("SET TRANSACTION READ ONLY"))
                    conn.execute(text(f"SET LOCAL statement_timeout = {timeout}"))
                    conn.execute(text(f"SET LOCAL TimeZone = '{ZONA}'"))   # constante: marcas sin zona de Extreme
                    return _filas_select(conn, sentencia, parametros, self.cancelacion_responde)
                finally:
                    conn.rollback()                       # solo lectura: nunca se confirma nada

        # RNF-010: solo la conexión pasa por el circuit breaker (fallos de red o timeout lo abren; el SQL rechazado
        # arriba o un error de datos no, ni el statement_timeout con cancelacion_responde, que sube como
        # SentenciaCancelada). Abierto -> CircuitoAbierto sin tocar la base; la ejecución se reintenta.
        from app.servicios import circuito

        filas = circuito.obtener("fuente_postgres").llamar(_leer)
        return pd.DataFrame([dict(f) for f in filas])

    def para_tabla(self, tabla: str) -> FuentePostgresSoloLectura:
        """Otra lectura de la lista blanca con la misma conexión, el mismo statement_timeout, el mismo solape y el mismo
        proceso (la usan los consolidados del ciclo, app/servicios/consolidados.py). Solo lectura, como esta."""
        return FuentePostgresSoloLectura(url=self.url or None, tabla=tabla,
                                         statement_timeout_ms=self.statement_timeout_ms, motor=self._engine(),
                                         limite=self.limite, solape_min=self.solape_min, proceso=self.proceso or "*",
                                         cancelacion_responde=self.cancelacion_responde)

    @property
    def columna_marca(self) -> str:
        return COLUMNA_MARCA.get(self.tabla, "ultima_actualizacion")

    @property
    def filtra_proceso(self) -> bool:
        """La lectura incremental de esta tabla filtra el proceso en el SQL (TABLAS_CON_PROCESO y un proceso dado; con
        «*», todos los operadores)."""
        return self.proceso is not None and self.tabla in TABLAS_CON_PROCESO

    def consulta_incremental(self, con_hasta=False, con_rutas=False):
        """SELECT de la tabla (lista blanca) con marca > :marca (y < :hasta), del proceso de la fuente si la tabla lo
        trae (TABLAS_CON_PROCESO: «proceso = :proceso»), ordenado y limitado.

        Tablas: SQLAlchemy Core (el nombre viene de TABLAS_PERMITIDAS y se cita si hace falta, p. ej. "Procesos").
        Vista demanda_segmentos: SQL constante, con las variantes fijas de `hasta` y de las rutas del trabajo
        (con_rutas, RNF-005: «r.nombre = ANY(:rutas)»). En todos los casos los valores van como parámetros enlazados."""
        import sqlalchemy as sa

        if self.tabla not in TABLAS_PERMITIDAS:
            raise OperacionNoPermitida(f"Tabla no permitida: {self.tabla!r}.")
        if self.tabla == "demanda_segmentos":
            return sa.text(_SQL_DEMANDA_SEGMENTOS.format(
                filtro_hasta=FILTRO_HASTA_SEGMENTOS if con_hasta else "",
                filtro_rutas=FILTRO_RUTAS_SEGMENTOS if con_rutas else ""))
        if con_rutas:
            raise OperacionNoPermitida(f"La lectura por ruta solo existe para {TABLA_CICLO!r}, no para {self.tabla!r}.")
        col = self.columna_marca
        t = sa.table(self.tabla, sa.column(col), sa.column("proceso"))
        q = sa.select(sa.literal_column("*")).select_from(t)
        if self.tabla in TABLAS_SIN_MARCA:
            return q.limit(self.limite)
        q = q.where(t.c[col] > sa.bindparam("marca"))
        if con_hasta:
            q = q.where(t.c[col] < sa.bindparam("hasta"))
        if self.filtra_proceso:
            q = q.where(t.c.proceso == sa.bindparam("proceso"))
        return q.order_by(t.c[col]).limit(self.limite)

    # ------------------------------------------------------------------ lectura incremental
    def _desde(self, marca: datetime) -> datetime:
        """Inicio de la ventana de lectura: la marca menos el solape (la carga inicial lee desde la marca inicial)."""
        return marca - timedelta(minutes=self.solape_min) if marca > MARCA_INICIAL else marca

    def _parametros(self, desde: datetime, hasta) -> dict:
        params = {"marca": desde}
        if hasta is not None:
            h = hasta.date() if isinstance(hasta, datetime) else hasta
            params["hasta"] = datetime.combine(h + timedelta(days=1), datetime.min.time()).replace(
                tzinfo=timezone(timedelta(hours=-5)))   # fin del día en America/Bogota (UTC-5, sin horario de verano)
        if self.tabla == "demanda_segmentos":
            params.update(limite=self.limite, proceso=self.proceso)
        elif self.filtra_proceso:
            params["proceso"] = self.proceso
        return params

    def leer_incremental(self, marca_agua=None, hasta=None, estado_previo=None):
        """(df, nueva_marca). Lee marca > (marca_agua − solape) y entrega solo lo nuevo, tardío o modificado."""
        marca = _normalizar_marca(marca_agua)
        desde = self._desde(marca)
        sql = self.consulta_incremental(con_hasta=hasta is not None)
        self.repetidas_por_llave = None
        if self.tabla in TABLAS_SIN_MARCA:
            d = self.consultar(sql, {})
            self.resumen_lectura = {"tabla": self.tabla, "leidas": len(d), "entregadas": len(d), "sin_marca": True}
            self.estado_incremental = None
            return d, marca
        d = self.consultar(sql, self._parametros(desde, hasta))
        return self._filtrar_por_huella(d, marca, desde, estado_previo)

    def _filtrar_por_huella(self, d, marca, desde, estado_previo):
        self.repetidas_por_llave = filas_de_llaves_repetidas(self, d)
        salida, nueva_marca, resumen, estado = _filtrar_huellas(self, d, marca, desde, estado_previo)
        self.resumen_lectura, self.estado_incremental = resumen, estado
        return salida, nueva_marca

    # ------------------------------------------------------------------ lectura por partición (RNF-005)
    def leer_particion(self, particion: Particion, hasta=None) -> LecturaParticion:
        """Lectura incremental de las rutas del trabajo: un solo SELECT de la lista blanca (con «r.nombre =
        ANY(:rutas)» si el trabajo es de rutas dadas) desde la marca más antigua de esas rutas, en la transacción READ
        ONLY de siempre; después, la regla exacta de leer_incremental (solape, huellas, tipo de llegada) ruta por ruta
        con la marca y las huellas de cada una."""
        if self.tabla in TABLAS_SIN_MARCA:
            raise OperacionNoPermitida(f"{self.tabla!r} no tiene marca de agua: no se lee por partición.")
        desde = self._desde(particion.marca_lectura())
        params = self._parametros(desde, hasta)
        if particion.rutas is not None:
            params["rutas"] = list(particion.rutas)
        sql = self.consulta_incremental(con_hasta=hasta is not None, con_rutas=particion.rutas is not None)
        d = self.consultar(sql, params)
        lectura = self._por_ruta(d, particion)
        marca_previa = particion.marca_anterior() or MARCA_INICIAL
        marca_nueva = max(marca_previa, lectura.marca_global or marca_previa)     # la que muestra: nunca retrocede
        base = {"tabla": self.tabla, "particion": list(particion.rutas or ["*"]), "proceso": particion.proceso,
                "marca_anterior": marca_previa.isoformat(), "desde": desde.isoformat(), "solape_min": self.solape_min,
                "leidas": len(d), "truncada": len(d) >= self.limite, "marca_nueva": marca_nueva.isoformat()}
        lectura.resumen = _sumar_resumenes(base, lectura.resumen or {})
        unido = {k: h for e in lectura.estados.values() for k, h in (e.get("huellas") or {}).items()}
        self.resumen_lectura = lectura.resumen
        self.estado_incremental = _estado(self, marca_nueva, unido)
        return lectura

    def _por_ruta(self, d: pd.DataFrame, particion: Particion) -> LecturaParticion:
        """Cada ruta (las del trabajo, las conocidas y las que llegaron) con su marca, su solape y sus huellas."""
        claves = _claves_o_vacias(d)
        rutas = sorted({*particion.rutas_conocidas(), *pd.unique(claves)}, key=_orden_de_ruta)
        lecturas = {ruta: self._leer_ruta(d[_filas_de_la_ruta(claves, ruta)], particion, ruta) for ruta in rutas}
        return _juntar_lecturas(d, lecturas)

    def _leer_ruta(self, d: pd.DataFrame, particion: Particion, ruta: str | None) -> _LecturaRuta:
        """Las filas de UNA ruta con su marca: lo que quedó antes de su ventana de solape ya se le entregó. `leida` es
        la marca mayor de lo que pasó esa ventana (lo que de verdad se leyó para la ruta). Si no pasó ninguna fila
        (un `hasta` anterior a su marca o una lectura truncada), la ruta conserva sus huellas: con unas vacías, la
        lectura siguiente le volvería a entregar su ventana de solape."""
        marca = particion.marca_de(ruta)
        desde = self._desde(marca)
        antes = len(d)
        col = self.columna_marca
        leida = None
        if antes and col in d.columns:
            marcas = _marcas_con_zona(d[col])
            vigentes = (marcas > pd.Timestamp(desde)).to_numpy(dtype=bool)
            d, leida = d[vigentes], _marca_mayor(marcas[vigentes])
        previo = particion.estado_de(ruta)
        salida, nueva, resumen, estado = _filtrar_huellas(self, d, marca, desde, previo)
        resumen["descartadas_marca_ruta"] = antes - len(d)
        if not len(d) and isinstance(previo, dict):
            estado = previo
        return _LecturaRuta(salida, nueva, resumen, estado, leida)

    # ------------------------------------------------------------------ ocupación actual por segmento (§10.1)
    def leer_carga_segmentos(self, franjas) -> pd.DataFrame:
        """Viaje × segmento de las franjas [(ruta, fecha, hora de salida)] con sus subidas y bajadas, el vehículo y el
        conductor ya seudonimizado (COLUMNAS_CARGA_SEGMENTOS), en la transacción READ ONLY de siempre. Vacío si no hay
        franjas. `truncada` en el atributo resumen_carga dice si se llegó al límite de filas."""
        franjas = list(franjas or ())
        if not franjas:
            return pd.DataFrame(columns=list(COLUMNAS_CARGA_SEGMENTOS))
        params = {"rutas": [str(r) for r, _, _ in franjas], "fechas": [f for _, f, _ in franjas],
                  "horas": [int(h) for _, _, h in franjas], "proceso": self.proceso, "limite": self.limite}
        d = self.consultar(_SQL_CARGA_SEGMENTOS, params)
        self.resumen_carga = {"franjas": len(franjas), "filas": len(d), "truncada": len(d) >= self.limite}
        if not len(d):
            return pd.DataFrame(columns=list(COLUMNAS_CARGA_SEGMENTOS))
        return seudonimizar_conductores(d)

    # ------------------------------------------------------------------ panel de 15 minutos (corto plazo, RF-005)
    def leer_panel_15min(self, idruta: int, segmentos: list[int], fechas: list, hasta=None):
        """(subidas, salidas) de la ruta en esos días, en la transacción READ ONLY de siempre: las subidas por
        id_segmento, día y bloque de 15 minutos de timbradas_segmentos (lo que escribe el trigger de conteo de Extreme,
        con su regla del segmento más cercano; solo lo actualizado antes de `hasta`) y los viajes que iniciaron en cada
        bloque (progvehiculos.fechainicio). app/servicios/panel_corto_plazo.py los valida y los guarda."""
        if not fechas or not segmentos:
            return (pd.DataFrame(columns=["id_segmento", "fecha", "bloque", "subidas"]),
                    pd.DataFrame(columns=["fecha", "bloque", "salidas"]))
        desde = min(fechas) - timedelta(days=1)
        fin = max(fechas) + timedelta(days=1)
        base = {"idruta": int(idruta), "desde": desde, "fin": fin, "fechas": list(fechas), "limite": self.limite}
        sub = self.consultar(_SQL_SUBIDAS_15MIN, dict(base, segmentos=[int(s) for s in segmentos], hasta=hasta))
        sal = self.consultar(_SQL_SALIDAS_15MIN, base)
        if not len(sub):
            sub = pd.DataFrame(columns=["id_segmento", "fecha", "bloque", "subidas"])
        if not len(sal):
            sal = pd.DataFrame(columns=["fecha", "bloque", "salidas"])
        self.resumen_panel = {"idruta": int(idruta), "dias": len(fechas), "celdas": len(sub),
                              "truncada": len(sub) >= self.limite or len(sal) >= self.limite}
        return sub, sal

    # ------------------------------------------------------------------ contexto operacional y catálogos (RF-003)
    def leer_contexto(self, nombre):
        """Catálogo o tabla de contexto completa (CONSULTAS_CONTEXTO), en solo lectura."""
        if nombre not in CONSULTAS_CONTEXTO:
            raise OperacionNoPermitida(f"Consulta de contexto desconocida: {nombre!r}.")
        return self.consultar(CONSULTAS_CONTEXTO[nombre])

    def procesos(self):
        return self.leer_contexto("procesos")

    def rutas(self):
        return self.leer_contexto("rutas")

    def estacionalidades_anio(self):
        return self.leer_contexto("estacionalidades_anio")

    def segmentos(self):
        return self.leer_contexto("segmentos")

    def novedades_viales(self, desde=None, hasta=None):
        """novedades_viales_fecha (con su catálogo) y la lista de rutas afectadas (vacía = todas, como en Sobusa)."""
        nov = self.leer_contexto("novedades_viales_fecha")
        rutas = self.leer_contexto("novedades_viales_ruta")
        if len(nov):
            nov["fecha"] = pd.to_datetime(nov["fecha"]).dt.date
            if desde is not None:
                nov = nov[nov["fecha"] >= desde]
            if hasta is not None:
                nov = nov[nov["fecha"] <= hasta]
            por_novedad = {} if rutas.empty else rutas.groupby("id_novedad_vial_fecha")["id_ruta"].apply(
                lambda s: sorted(int(x) for x in s)).to_dict()
            nov = nov.assign(rutas=[por_novedad.get(i, []) for i in nov["id_novedad_vial_fecha"]])
        return nov.reset_index(drop=True)

    def ubicacion_despacho(self, ruta):
        """Inicio del segmento 1 de la ruta en rutas_segmentos (GeoJSON Point, EPSG:4326), en solo lectura; se guarda
        por ruta durante la vida de la fuente. None si la ruta no tiene segmentos."""
        clave = str(ruta)
        if clave not in self._ubicaciones:
            import json

            d = self.consultar(_SQL_UBICACION_DESPACHO, {"ruta": clave})
            punto = d["punto"].iloc[0] if len(d) and "punto" in d.columns else None
            self._ubicaciones[clave] = json.loads(punto) if isinstance(punto, str) else None
        return self._ubicaciones[clave]

    def viajes(self, ruta, desde, hasta, con_segmentos=None):
        """§5.3 (ALT-006 y ALT-009): los viajes de la ruta (nombre o idruta) con salida programada en [desde, hasta)
        de progvehiculos, en solo lectura y en orden de salida, con el conductor ya seudonimizado (seudonimizar_viajes).
        con_segmentos (por omisión, si esta fuente lee la capa de segmentos del ciclo): cuenta las filas de
        timbradas_segmentos de cada viaje."""
        if con_segmentos is None:
            con_segmentos = self.tabla == TABLA_CICLO
        d = self.consultar(sql_viajes_ruta(con_segmentos), {"ruta": str(ruta), "proceso": self.proceso,
                                                            "desde": desde, "hasta": hasta, "limite": LIMITE_VIAJES})
        return seudonimizar_viajes(d)

    def catalogos_calidad(self):
        """Llaves existentes para la validación relacional del lote (§6.3, §8.3), leídas en solo lectura."""
        rutas = self.rutas()
        cat = {"rutas": set(rutas["nombre"].dropna()), "idrutas": {int(x) for x in rutas["idruta"].dropna()},
               "procesos": set(self.procesos()["proceso"].dropna()),
               "estacionalidades": {int(x) for x in self.leer_contexto("estacionalidades")["id_estacionalidad"]
                                    .dropna()},
               "novedades": {int(x) for x in self.leer_contexto("novedades_viales")["id_novedad_vial"].dropna()}}
        segmentos = self.segmentos()
        if len(segmentos):
            cat["segmentos"] = {int(x) for x in segmentos["id_segmento"].dropna()}
            # REL-006 (§7.3 paso 3): la ruta de cada segmento, para validar que el segmento de una fila es de su ruta
            pares = segmentos.dropna(subset=["id_segmento", "idruta"])
            cat["segmentos_ruta"] = {int(s): int(r) for s, r in zip(pares["id_segmento"], pares["idruta"],
                                                                   strict=True)}
        if "capacidad" in rutas.columns:
            cat["capacidades"] = dict(zip(rutas["nombre"], pd.to_numeric(rutas["capacidad"], errors="coerce"),
                                          strict=True))
        cat.update(self._catalogos_del_dia())
        return cat

    def _catalogos_del_dia(self) -> dict:
        """dias_semana (REL-007) y los días ISO en que cae cada estacionalidad según sus fechas (VAL-007), leídos en
        solo lectura. Si falta una de las dos tablas, el día de la semana no se valida contra ellas (queda en el
        log)."""
        from app.servicios import calidad

        try:
            dias = self.leer_contexto("dias_semana")
            vigencias = self.estacionalidades_anio()
        except Exception as exc:  # noqa: BLE001 - sin estas tablas se valida lo demás
            log.info("dias_semana o estacionalidades_anio no disponibles para la calidad: %s", exc)
            return {}
        salida = calidad.dias_por_estacionalidad(vigencias)
        if len(dias) and "id_dia_semana" in dias.columns:
            salida["dias_semana"] = {int(x) for x in dias["id_dia_semana"].dropna()}
        return salida


# ------------------------------------------------------------------ frecuencia vigente de la ruta (§6.1, §6.2)
# rutas.frecuenciadespachos (su unidad es el supuesto S14, hallazgo H15, que confirma Extreme). En modo integrado
# datos.ruta_info la toma de la tabla rutas de la fuente con CONSULTAS_CONTEXTO["frecuencias"] (solo lectura) y, si
# esta lectura no la trae, de su catálogo empaquetado.
FRECUENCIA_TTL_S = 300.0                 # la tabla rutas cambia poco: se relee a lo sumo cada 5 min por fuente
SQLSTATE_COLUMNA_INEXISTENTE = "42703"
# id(motor) -> (motor, instante, valores, detalle); el motor se guarda para no confundir un id reutilizado
_frecuencias: dict[int, tuple[Any, float, dict[int, Any] | None, str]] = {}
_frecuencias_candado = threading.Lock()


def _leer_frecuencias(fuente) -> tuple[dict[int, Any] | None, str]:
    """({idruta: frecuenciadespachos tal como la trae la fuente}, detalle) o (None, por qué no se pudo)."""
    try:
        d = fuente.leer_contexto("frecuencias")
    except Exception as exc:  # noqa: BLE001 - sin esta lectura rige el catálogo empaquetado
        if getattr(getattr(exc, "orig", None), "sqlstate", None) == SQLSTATE_COLUMNA_INEXISTENTE:
            return None, "la tabla rutas de la fuente no trae la columna frecuenciadespachos"
        log.info("frecuenciadespachos no disponible en la fuente: %s", exc)
        return None, f"la lectura de la fuente falló ({type(exc).__name__})"
    if not len(d) or not {"idruta", "frecuenciadespachos"} <= set(d.columns):
        return None, "la tabla rutas de la fuente no trae filas"
    ids = pd.to_numeric(d["idruta"], errors="coerce")
    valores = {int(i): v for i, v in zip(ids, d["frecuenciadespachos"], strict=True) if pd.notna(i)}
    return valores, "rutas.frecuenciadespachos de la base de Extreme (solo lectura)"


def frecuencias_despacho(fuente) -> tuple[dict[int, Any] | None, str]:
    """§6.1 «frecuenciadespachos» y §6.2 «headway vigente»: {idruta: rutas.frecuenciadespachos} de la fuente, leída con
    el SELECT de la lista blanca en la transacción READ ONLY de siempre, y de dónde salió; (None, motivo) si no
    responde o no trae la columna. Se guarda FRECUENCIA_TTL_S segundos por motor de la fuente, también la falta de
    respuesta: ni se consulta en cada uso de la ruta ni se le suman intentos al circuit breaker de la fuente."""
    motor = fuente._engine()
    ahora = time.monotonic()
    with _frecuencias_candado:
        guardado = _frecuencias.get(id(motor))
    if guardado is not None and guardado[0] is motor and ahora - guardado[1] < FRECUENCIA_TTL_S:
        return guardado[2], guardado[3]
    valores, detalle = _leer_frecuencias(fuente)
    with _frecuencias_candado:
        _frecuencias[id(motor)] = (motor, ahora, valores, detalle)
    return valores, detalle


def limpiar_frecuencias() -> None:
    """Olvida las frecuencias leídas (pruebas, o tras cambiar la fuente configurada)."""
    with _frecuencias_candado:
        _frecuencias.clear()


def validar_tabla_ciclo(tabla: str) -> str:
    """FUENTE_TABLA: el ciclo solo procesa de punta a punta la lectura «demanda_segmentos»."""
    if tabla not in TABLAS_CICLO:
        raise ValueError(f"FUENTE_TABLA={tabla!r} no está soportada por el ciclo: solo «demanda_segmentos» llega de "
                         "punta a punta (calidad, histórico, modelo y alertas). Las tablas timbradas_* se leen para "
                         "catálogos, segmentos y pruebas, no como lote del ciclo.")
    return tabla


def _estado(fuente, marca, huellas):
    return {"version": VERSION_ESTADO, "tabla": fuente.tabla, "solape_min": fuente.solape_min,
            "marca": pd.Timestamp(marca).isoformat(), "huellas": huellas}


def llave_de_la_lectura(tabla: str, d: pd.DataFrame) -> list[str]:
    """Las columnas de la llave natural con que la lectura incremental deduplica lo leído de `tabla` (LLAVES; si no
    trae ninguna, la primera columna)."""
    return [c for c in LLAVES.get(tabla, (d.columns[0],)) if c in d.columns] or [d.columns[0]]


def _como_entregadas(fuente, d: pd.DataFrame) -> pd.DataFrame:
    """Las filas como las entrega la lectura: con ultima_actualizacion (la marca, si la tabla la llama de otro modo) y
    su zona horaria."""
    col = fuente.columna_marca
    if col != "ultima_actualizacion" and "ultima_actualizacion" not in d.columns:
        d["ultima_actualizacion"] = d[col]
    if "ultima_actualizacion" in d.columns:
        d["ultima_actualizacion"] = _marcas_con_zona(d["ultima_actualizacion"])
    return d


def filas_de_llaves_repetidas(fuente, d: pd.DataFrame) -> pd.DataFrame:
    """§6.3 «Unicidad: reportar al responsable del consolidado; no corregir directamente»: TODAS las filas leídas cuya
    llave natural se repite, como las entrega la lectura. _filtrar_huellas deduplica por esa llave y se queda con la
    más reciente para guardar una huella por llave, así que quien valida la unicidad (consolidados.py) las recupera de
    aquí. Con UNIQUE en la fuente solo se repite una llave con columnas nulas. Vacío si la lectura no deduplica (sin
    filas o sin la columna de la marca)."""
    if not len(d) or fuente.columna_marca not in d.columns:
        return d.iloc[0:0].copy()
    repetida = d.duplicated(subset=llave_de_la_lectura(fuente.tabla, d), keep=False)
    return _como_entregadas(fuente, d[repetida].reset_index(drop=True))


def _filtrar_huellas(fuente, d, marca, desde, estado_previo):
    """Regla exacta de la lectura incremental sobre lo leído desde `desde` (marca − solape): deduplica por llave (las
    filas de una llave repetida, en filas_de_llaves_repetidas), descarta lo que ya se entregó con la misma huella y
    marca el tipo de llegada. Devuelve (filas entregadas, marca nueva, resumen, estado de huellas de la ventana de
    solape)."""
    col = fuente.columna_marca
    leidas = len(d)
    resumen = {"tabla": fuente.tabla, "marca_anterior": marca.isoformat(), "desde": desde.isoformat(),
               "solape_min": fuente.solape_min, "leidas": leidas, "truncada": leidas >= fuente.limite}
    if leidas == 0 or col not in d.columns:
        resumen.update(entregadas=leidas, nuevas=leidas, tardias=0, modificadas=0, repetidas_solape=0,
                       marca_nueva=marca.isoformat())
        return d, marca, resumen, _estado(fuente, marca, {})
    marcas = _marcas_con_zona(d[col])
    llave = llave_de_la_lectura(fuente.tabla, d)
    d = d.assign(_marca=marcas).sort_values("_marca", kind="stable")
    d = d.drop_duplicates(subset=llave, keep="last").reset_index(drop=True)     # deduplicar por llave natural
    valores = [c for c in sorted(d.columns) if c not in (col, "_marca")]
    claves = ["|".join(str(v) for v in fila) for fila in d[llave].itertuples(index=False, name=None)]
    huellas = [huella_fila(fila) for fila in d[valores].itertuples(index=False, name=None)]
    previas = _huellas_previas(estado_previo, fuente.tabla)
    repetida = [previas.get(k) == h for k, h in zip(claves, huellas, strict=True)]
    conocida = [k in previas for k in claves]
    posterior = (d["_marca"] > pd.Timestamp(marca)).tolist()
    nueva_marca = max(marca, pd.Timestamp(d["_marca"].max()).to_pydatetime())
    limite_estado = pd.Timestamp(nueva_marca - timedelta(minutes=fuente.solape_min))
    en_ventana = (d["_marca"] > limite_estado).tolist()
    estado = {k: h for k, h, v in zip(claves, huellas, en_ventana, strict=True) if v}
    entregar = [not r for r in repetida]
    resumen.update(
        entregadas=int(sum(entregar)),
        nuevas=int(sum(e and not c and p for e, c, p in zip(entregar, conocida, posterior, strict=True))),
        tardias=int(sum(e and not c and not p for e, c, p in zip(entregar, conocida, posterior, strict=True))),
        modificadas=int(sum(e and c for e, c in zip(entregar, conocida, strict=True))),
        repetidas_solape=int(sum(repetida)), duplicadas_llave=leidas - len(d),
        marca_nueva=nueva_marca.isoformat(), huellas_estado=len(estado))
    # Tipo de llegada de cada fila entregada (calidad: la carga inicial no cuenta como dato tardío, OPOR-001).
    carga_inicial = marca <= MARCA_INICIAL
    tipo = [_tipo_llegada(carga_inicial, c, p) for c, p in zip(conocida, posterior, strict=True)]
    d = d.assign(tipo_llegada=tipo)
    salida = _como_entregadas(fuente, d[entregar].drop(columns=["_marca"]).reset_index(drop=True))
    return salida, nueva_marca, resumen, _estado(fuente, nueva_marca, estado)


def fuente_desde_entorno(env=None):
    """FUENTE=parquet (por defecto) o FUENTE=postgres (requiere FUENTE_DATABASE_URL; FUENTE_TABLA, FUENTE_PROCESO y
    FUENTE_SOLAPE_MIN opcionales; FUENTE_TABLA solo admite demanda_segmentos)."""
    env = os.environ if env is None else env
    tipo = (env.get("FUENTE") or "parquet").strip().lower()
    if tipo == "postgres":
        return FuentePostgresSoloLectura(url=env.get("FUENTE_DATABASE_URL") or None,
                                         tabla=validar_tabla_ciclo(env.get("FUENTE_TABLA") or TABLA_CICLO),
                                         statement_timeout_ms=env.get("FUENTE_STATEMENT_TIMEOUT_MS") or None,
                                         solape_min=env.get("FUENTE_SOLAPE_MIN") or None,
                                         proceso=env.get("FUENTE_PROCESO"))
    if tipo != "parquet":
        raise ValueError(f"FUENTE desconocida: {tipo!r} (use parquet o postgres).")
    return FuenteParquet()


def leer_con_estado(fuente, marca_agua, hasta, estado_previo=None):
    """Llama a leer_incremental pasando el estado de huellas solo a las fuentes que lo admiten."""
    if getattr(fuente, "admite_estado", False):
        return fuente.leer_incremental(marca_agua, hasta, estado_previo=estado_previo)
    return fuente.leer_incremental(marca_agua, hasta)


__all__ = ["FuenteParquet", "FuentePostgresSoloLectura", "OperacionNoPermitida", "validar_solo_select",
           "fuente_desde_entorno", "leer_con_estado", "huella_fila", "validar_tabla_ciclo",
           "punto_despacho_empaquetado", "TABLAS_PERMITIDAS", "TABLAS_SIN_MARCA", "TABLAS_CICLO", "TABLA_CICLO",
           "COLUMNA_MARCA", "CONSULTAS_CONTEXTO", "MARCA_INICIAL", "DEFINICION_PASAJEROS", "Particion",
           "LecturaParticion", "leer_particion", "huellas_de_la_ruta", "PROCESO_DEFECTO", "sql_viajes_ruta",
           "seudonimizar_viajes", "seudonimizar_conductores", "seudonimos", "LIMITE_VIAJES", "TABLAS_CON_PROCESO",
           "frecuencias_despacho", "limpiar_frecuencias", "filas_de_llaves_repetidas", "llave_de_la_lectura"]
