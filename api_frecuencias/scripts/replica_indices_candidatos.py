"""Índices candidatos para la base de Extreme medidos en la réplica LOCAL con EXPLAIN (ANALYZE, BUFFERS), cada uno
creado DENTRO de una transacción que se revierte (§8.3 «índices que apruebe el responsable de la base», §11.3, §14.1
«Rendimiento: SQL EXPLAIN», §18 «Consulta pesada»; hallazgo H12 de docs/hallazgos_extreme.md).

Mide las consultas reales de la API que filtran por fecha o por la marca de agua: las del refresco de la agregación de
segmentos (app/servicios/segmentos_refresco.py: ventana de solape por ultimaactualizacion, grano diario de un tramo
por fecha y rango de la fuente), la lectura incremental demanda_segmentos de todas las rutas y de una ruta
(app/servicios/fuentes.py), la ocupación actual por segmento (§10.1, leer_carga_segmentos), los viajes de una ruta de
§5.3 y las lecturas de los consolidados de la ola B (app/servicios/consolidados.py: lectura incremental por proceso,
el agregado de las rutas tocadas y el count(*) que hacía _sin_filas). Cada escenario es una transacción:

    BEGIN; SET LOCAL lock_timeout; consultas sin el índice; CREATE INDEX ...; las mismas consultas; ROLLBACK

El DDL de PostgreSQL es transaccional: el índice solo existe dentro de esa transacción (ninguna otra sesión lo ve) y el
ROLLBACK lo deshace con todo; al terminar se comprueba en pg_indexes que la réplica no conserva ninguno. Se crea como
extreme_dba (el dueño de las tablas; CREATE INDEX CONCURRENTLY no cabe en una transacción), sin ANALYZE (que en
PostgreSQL actualiza relpages y reltuples fuera de la transacción) y con el candado de las simulaciones de la réplica
(scripts/replica_simular_llegada.candado). Mientras dura la transacción la tabla del índice no admite escrituras
(CREATE INDEX toma ShareLock): con lock_timeout de 2 s el script no espera a un escritor. Cada consulta se mide
REPETICIONES veces y se compara la más rápida de cada lado, en la misma transacción y con la misma carga del equipo.

Además mide LA PROPUESTA ENTERA (medir_propuesta_entera): un índice que solo no cambia un plan puede cambiarlo junto con
los demás y con las estadísticas al día. Es otra transacción que se revierte, con TODAS las lecturas de la API y con
ANALYZE en los dos lados:

    BEGIN; ANALYZE; todas las consultas; CREATE INDEX de toda la propuesta; ANALYZE; las mismas consultas; ROLLBACK

Ahí ANALYZE hace falta: es lo que hará el DBA (o autovacuum) después de crear los índices, y mide también la expresión
de un índice sobre una expresión. Sus estadísticas (pg_statistic) se revierten con la transacción; relpages y
reltuples de las tablas quedan al día, que es lo que deja cualquier ANALYZE, sin cambiar datos ni esquema. El criterio
de «ningún empeoramiento» se evalúa también en esa medición, para cada lectura (empeoran).

Escribe docs/evidencias/replica/indices_candidatos.json y .md. La propuesta (docs/evidencias/replica/
propuesta_indices.sql, la escribe scripts/replica_explain.py con propuesta_sql()) son los candidatos con
propuesto=True, decididos con esta medición; el informe dice si la medición los respalda, uno por uno y la propuesta
entera. Crear los índices sigue siendo decisión de Extreme.

Uso (desde EntregaFinal/api_frecuencias, con la réplica levantada y OPERACIONAL_PASSWORD en el .env):
  python -m scripts.replica_indices_candidatos
"""
from __future__ import annotations

import argparse
import json
import textwrap
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from scripts import replica_comun as rc

ZONA = ZoneInfo("America/Bogota")
SALIDA = rc.RAIZ / "docs" / "evidencias" / "replica"
ESPERA_CANDADO = "2s"          # CREATE INDEX no espera a un escritor de la réplica más que esto
TIEMPO_MAXIMO_MS = 180000
REPETICIONES = 2               # cada consulta, dos veces por lado: se compara la más rápida (caché caliente)
MEJORA_MINIMA = 0.30           # el índice baja al menos 30 % alguna de sus consultas, y la usa...
AHORRO_MINIMO_MS = 10.0        # ... con al menos 10 ms menos ...
EMPEORA_MAXIMO = 0.15          # ... y no empeora más de 15 % ninguna de las demás que mide
RUIDO_MS = 1.0                 # una diferencia menor no cuenta como empeoramiento (consultas de centésimas de ms)
PROCESO = "sobusa"
RUTAS = ("CL 72", "CRA 54", "SILENCIO")
ENTERA = "propuesta_entera"    # el escenario de toda la propuesta, con ANALYZE en los dos lados
SIN_EL_3 = "propuesta_sin_el_indice_3"     # la misma medición sin el índice sobre la expresión de la hora de salida
INDICE_3 = "ix_ia_progvehiculos_ruta_hora_salida"
# Las tablas de los índices de la propuesta: las que se analizan al medirla entera (y en scripts/replica_explain.py)
TABLAS_DE_LA_PROPUESTA = ("timbradas_segmentos", "progvehiculos", "timbradas_consolidado", "timbradas_anio",
                          "timbradas_segmentos_anio", "timbradas_segmentos_consolidado")


@dataclass(frozen=True)
class Candidato:
    """Un índice candidato: su DDL, las consultas que lo justificarían y si va en la propuesta."""

    nombre: str
    tabla: str
    columnas: str
    para: tuple[str, ...]
    motivo: str
    propuesto: bool
    antes: bool = False            # ya estaba en la propuesta de la ola A
    nota: str = ""                 # la decisión con la medición de indices_candidatos.json (2026-11-13)

    @property
    def ddl(self) -> str:
        return f"CREATE INDEX {self.nombre} ON public.{self.tabla} ({self.columnas})"

    def ddl_produccion(self) -> str:
        return f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {self.nombre}\n    ON public.{self.tabla} ({self.columnas});"


LECTURA = ("demanda_segmentos_sin_novedades", "demanda_segmentos_una_ruta_sin_novedades", "demanda_segmentos_bloque",
           "demanda_segmentos_una_ruta_bloque")
VENTANA = ("segmentos_ventana_sin_novedades", "segmentos_ventana_bloque")
GRANO = ("segmentos_grano_diario_1_fecha", "segmentos_grano_diario_7_fechas")
CANDIDATOS: tuple[Candidato, ...] = (
    Candidato("ix_ia_timbradas_segmentos_ultimaactualizacion", "timbradas_segmentos", "ultimaactualizacion",
              (*LECTURA, *VENTANA, "segmentos_rango"),
              "Lectura incremental de timbradas_segmentos (lo que escribe tg_timbrada_segmento) por marca de agua y "
              "ventana de solape del refresco de la agregación de segmentos.", True, True,
              "Se propone: sin novedades, la lectura incremental baja de unos 170 a 50 ms y la ventana de solape del "
              "refresco, de unos 120 a 0,02 ms (el costo fijo de cada ciclo y de cada refresco, que sin el índice "
              "recorre toda la tabla y crece con el histórico)."),
    Candidato("ix_ia_timbradas_segmentos_id_viaje", "timbradas_segmentos", "id_viaje",
              (*LECTURA, "ocupacion_actual", "viajes_de_una_ruta"),
              "Segmentos de un viaje: re-agregación de las franjas tocadas, ocupación actual por segmento y conteo "
              "de segmentos de los viajes de §5.3 (la llave foránea id_viaje no tiene índice).", True, True,
              "Se propone: los viajes de una ruta y un día con su conteo de segmentos (§5.3) bajan de unos 800 a "
              "90 ms y, con el índice 3, a 9 ms."),
    Candidato("ix_ia_progvehiculos_ruta_hora_salida", "progvehiculos", "idruta, (date_trunc('hour', fechasalida))",
              (*LECTURA, "viajes_de_una_ruta"),
              "Viajes de una ruta en una hora de salida (las franjas de la demanda horaria y la ventana de los viajes "
              "de §5.3).", True, True,
              "Se propone junto con el índice 2: los viajes de una ruta y un día bajan de unos 820 a 9 ms (solo, a "
              "unos 730 ms). Con las estadísticas al día, las de su expresión hacen que la lectura compuesta sin "
              "novedades baje a 0,1 ms y que la del bloque grande use los índices 1 y 2 (ver «La propuesta entera»)."),
    Candidato("ix_ia_timbradas_segmentos_fecha", "timbradas_segmentos", "fecha",
              (*GRANO, "segmentos_rango"),
              "Refresco de la agregación de segmentos: relee el grano diario de las fechas cambiadas por fecha "
              "(SQL_FUENTE_DIA) y el rango de la fuente (min/max de fecha).", False, False,
              "No se propone con esta medición: el grano diario de una fecha baja solo de unos 260 a 220 ms y el de 7 "
              "fechas (12,5 % de la réplica) empeora de unos 1.400 a 1.620 ms; con el de la marca, el rango de la "
              "fuente baja de unos 175 a 0,03 ms. Con el histórico completo (unos 58 millones de filas proyectadas, 7 "
              "fechas serían el 0,6 % de la tabla) conviene volver a medirlo con el volumen de producción (H12)."),
    Candidato("ix_ia_progvehiculos_ruta_fechasalida", "progvehiculos", "idruta, fechasalida",
              ("ocupacion_actual",),
              "Ocupación actual por segmento: los viajes de una ruta con salida en el rango de una franja.", False,
              False,
              "No se propone: la ocupación actual de un día empeora de unos 710 a 870 ms (880 ms con el índice 2): "
              "el plan sigue recorriendo timbradas_segmentos con un hash join; esa lectura no se arregla con un "
              "índice."),
    Candidato("ix_ia_timbradas_consolidado_ultima_actualizacion", "timbradas_consolidado", "ultima_actualizacion",
              ("consolidado_sin_novedades", "consolidado_resellado", "consolidado_todos_los_procesos"),
              "Marca de agua de los consolidados (§8.3: «consultar los incrementos por ultima_actualizacion»).", True,
              True,
              "Se mantiene por §8.3, con prioridad baja: a 10.731 filas la lectura sin novedades baja de 1,3 ms a "
              "0,01 ms y tras el resellado de 4,5 a 2,7 ms (no cumple el ahorro mínimo de 10 ms a este volumen)."),
    Candidato("ix_ia_timbradas_consolidado_proceso_ultima_actualizacion", "timbradas_consolidado",
              "proceso, ultima_actualizacion",
              ("consolidado_sin_novedades", "consolidado_resellado", "consolidado_conteo_del_proceso",
               "consolidado_existe_el_proceso"),
              "Lectura incremental de los consolidados de UN proceso (el filtro por proceso del SQL; en la base de "
              "Extreme hay varios operadores, H4).", False, False,
              "No se propone: a este volumen da lo mismo que el de la marca sola (1,3 a 0,01 ms y 4,4 a 2,2 ms); con "
              "varios operadores en la tabla, sería la alternativa al índice 4."),
)
# Los de los otros consolidados con marca (nombre, tabla, columnas, motivo). timbradas_anio tiene filas de Sobusa en la
# réplica: sigue por §8.3 con el argumento del de timbradas_consolidado. Las dos por segmento no tienen filas de Sobusa
# (H4) y en la base de Extreme son de otros operadores: sin filas del proceso no hay marca guardada y su lectura
# («proceso = :proceso» desde la marca inicial) solo la sirve un índice por (proceso, ultima_actualizacion); con la
# marca sola la lectura sigue recorriendo la tabla. Medido con ese volumen en una tabla temporal, dentro de una
# transacción que se revierte (scripts/replica_lectura_consolidados.py, docs/evidencias/consolidados/
# lectura_por_proceso.md).
# Sin punto y coma en los motivos: van como comentario de la propuesta.
OTROS_CONSOLIDADOS = (
    ("ix_ia_timbradas_anio_ultima_actualizacion", "timbradas_anio", "ultima_actualizacion",
     "Marca de agua de timbradas_anio (§8.3), con el mismo argumento que el de timbradas_consolidado."),
    ("ix_ia_timbradas_segmentos_anio_proceso_marca", "timbradas_segmentos_anio", "proceso, ultima_actualizacion",
     "Lectura incremental de las tablas por segmento de UN proceso (proceso = :proceso desde su marca). En la base "
     "de Extreme son de otros operadores (hallazgo H4) y, sin filas del proceso, la lectura empieza en la marca "
     "inicial: la marca sola no evita recorrerlas. Medido con ese volumen en una tabla temporal "
     "(docs/evidencias/consolidados/lectura_por_proceso.md)."),
    ("ix_ia_timbradas_segmentos_consolidado_proceso_marca", "timbradas_segmentos_consolidado",
     "proceso, ultima_actualizacion", ""),
)
# Escenarios combinados: cada lectura con los índices que usa a la vez (la lectura incremental, los tres de la ola A;
# el refresco, la marca y la fecha; la ocupación actual, el viaje y la salida de la ruta).
COMBINADOS = {"lectura_incremental_1_2_3": ("ix_ia_timbradas_segmentos_ultimaactualizacion",
                                            "ix_ia_timbradas_segmentos_id_viaje",
                                            "ix_ia_progvehiculos_ruta_hora_salida"),
              "refresco_segmentos_1_4": ("ix_ia_timbradas_segmentos_ultimaactualizacion",
                                         "ix_ia_timbradas_segmentos_fecha"),
              "ocupacion_actual_2_5": ("ix_ia_timbradas_segmentos_id_viaje", "ix_ia_progvehiculos_ruta_fechasalida")}

# Sin punto y coma en los comentarios: replica_explain separa las sentencias por «;».
ENCABEZADO = """-- Propuesta de índices para el DBA de Extreme Technologies (§8.3: se piden después de revisar
-- EXPLAIN (ANALYZE, BUFFERS) y los aplica el responsable de la base). Medidos SOLO en la réplica local, cada uno dentro
-- de una transacción que se revierte, y la propuesta ENTERA con las estadísticas al día (ANALYZE) frente a todas las
-- lecturas del módulo de IA (scripts/replica_indices_candidatos.py, docs/evidencias/replica/indices_candidatos.md).
-- En producción, CONCURRENTLY no bloquea las escrituras de la captura ni de los triggers. Después de crearlos conviene
-- ANALYZE de esas tablas. Ninguno cambia tablas, triggers, funciones ni scripts: solo acelera las lecturas.
"""


def _comentario(numero: int, motivo: str) -> str:
    """El motivo como comentario numerado de la propuesta, partido en líneas de hasta 116 caracteres."""
    return "\n".join(f"-- {x}" for x in textwrap.wrap(f"{numero}) {motivo}", 116))


def propuesta_sql() -> str:
    """docs/evidencias/replica/propuesta_indices.sql: los candidatos propuestos y los de los otros consolidados
    (OTROS_CONSOLIDADOS; un motivo vacío comparte el comentario del anterior)."""
    partes = [ENCABEZADO]
    propuestos = [(c.motivo, c.ddl_produccion()) for c in CANDIDATOS if c.propuesto]
    propuestos += [(m, f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {n}\n    ON public.{t} ({col});")
                   for n, t, col, m in OTROS_CONSOLIDADOS]
    numero = 0
    for motivo, ddl in propuestos:
        if motivo:
            numero += 1
            partes.append(f"{_comentario(numero, motivo)}\n{ddl}")
        else:
            partes.append(ddl)
    return "\n".join(partes) + "\n"


def indices_de_la_propuesta(sin: tuple[str, ...] = ()) -> list[tuple[str, str]]:
    """(nombre, CREATE INDEX) de TODA la propuesta para una transacción que se revierte: los mismos índices de
    propuesta_sql(), sin CONCURRENTLY (no cabe en una transacción) ni IF NOT EXISTS. `sin` quita índices por nombre
    (para medir cuál cambia un plan)."""
    propuestos = [(c.nombre, c.ddl) for c in CANDIDATOS if c.propuesto]
    propuestos += [(n, f"CREATE INDEX {n} ON public.{t} ({col})") for n, t, col, _m in OTROS_CONSOLIDADOS]
    return [(n, ddl) for n, ddl in propuestos if n not in sin]


# ---------------------------------------------------------------- consultas reales de la API
@dataclass
class Consulta:
    clave: str
    descripcion: str
    origen: str
    sql: str
    params: dict
    referencia: bool = False       # no es una lectura de la API: se mide para comparar y no entra en el criterio


# La formulación anterior de la lectura compuesta (hasta el 13-11-2026): la consulta final volvía a unir rutas. Con la
# propuesta entera y ANALYZE, esa unión hacía elegir un ciclo anidado que compara todos los viajes con todos (la
# estimación de `viajes ⋈ rutas` usa el ndistinct por omisión de un CTE). Se mide solo en la propuesta entera, como
# referencia, para dejar con cifras por qué fuentes._SQL_DEMANDA_SEGMENTOS ya no la tiene. Pares: (texto de hoy, texto
# de antes).
UNION_FINAL_DE_RUTAS = (
    ("SELECT DISTINCT pv.idruta, r.proceso, r.nombre, r.idempresa, date_trunc(",
     "SELECT DISTINCT pv.idruta, r.proceso, date_trunc("),
    ("f.idruta, f.proceso, f.nombre, f.idempresa, f.franja,", "f.idruta, f.proceso, f.franja,"),
    ("SELECT v.nombre AS ruta, v.idruta, v.proceso, v.idempresa,",
     "SELECT r.nombre AS ruta, v.idruta, v.proceso, r.idempresa,"),
    ("  LEFT JOIN estacion es ON", "  JOIN rutas r ON r.idruta = v.idruta\n  LEFT JOIN estacion es ON"),
    ("GROUP BY v.nombre, v.idruta, v.proceso, v.idempresa,", "GROUP BY r.nombre, v.idruta, v.proceso, r.idempresa,"),
)
CON_UNION_FINAL = "_con_union_final_de_rutas"


def con_union_final_de_rutas(sql: str) -> str:
    """El SQL de la lectura compuesta con la unión final de rutas que tenía antes (solo para medirla de referencia)."""
    for hoy, antes in UNION_FINAL_DE_RUTAS:
        if sql.count(hoy) != 1:
            raise ValueError(f"la lectura compuesta ya no tiene «{hoy}»: revise UNION_FINAL_DE_RUTAS")
        sql = sql.replace(hoy, antes)
    return sql


def _compilar(motor, sql: str) -> str:
    import sqlalchemy as sa

    return str(sa.text(sql).compile(dialect=motor.dialect))


def _incremental(motor, tabla: str, proceso: str | None, con_rutas: bool = False) -> tuple[str, dict]:
    """El SELECT exacto de FuentePostgresSoloLectura.consulta_incremental, compilado para el driver."""
    from app.servicios.fuentes import FuentePostgresSoloLectura

    f = FuentePostgresSoloLectura(url="postgresql+psycopg://lector_ia@localhost/x", tabla=tabla, motor=motor,
                                  proceso=proceso or "*")
    sentencia = f.consulta_incremental(con_rutas=con_rutas)
    if hasattr(sentencia, "compile") and not isinstance(sentencia, str):
        compilado = sentencia.compile(dialect=motor.dialect)
        return str(compilado), dict(compilado.params)
    return _compilar(motor, sentencia), {}


def contexto(cx) -> dict:
    """Las marcas y fechas reales de la réplica con que se arma cada consulta (como replica_explain: la lectura de un
    día es el bloque de marcas que cubre el volumen de un día)."""
    from scripts import replica_explain as rx

    with cx.cursor() as cur:
        vol = rx.volumen(cur)
        marca_dia = rx.marca_de_lectura(cur, "timbradas_segmentos", vol["filas_por_dia"])
        cur.execute("SELECT max(ultimaactualizacion), max(fecha) FROM public.timbradas_segmentos")
        marca_max, ultima_fecha = cur.fetchone()
        cur.execute("SELECT max(ultima_actualizacion) FROM public.timbradas_consolidado")
        marca_consolidado = cur.fetchone()[0]
        cur.execute("SELECT indexname FROM pg_indexes WHERE schemaname = 'public' AND indexname LIKE 'ix\\_ia\\_%'")
        previos = [r[0] for r in cur.fetchall()]
    return {"volumen": vol, "marca_dia": marca_dia, "marca_max": marca_max.replace(tzinfo=ZONA),
            "ultima_fecha": ultima_fecha, "marca_consolidado": marca_consolidado.replace(tzinfo=ZONA),
            "indices_previos": previos}


SOLAPE = timedelta(minutes=15)


def _lecturas(motor, ctx: dict) -> list[Consulta]:
    """La lectura incremental de todas las rutas y de una ruta en dos regímenes: «sin novedades» (marca = la mayor:
    nada posterior, el costo fijo de cada ciclo programado o intradía sin datos nuevos; en producción la ventana de
    solape vuelve a traer los últimos 15 min de llegadas, unas 500 filas a 49 mil por día, pero en la réplica la
    carga se selló en solo 2 marcas y esos 15 min traen 1,26 millones de filas) y «bloque» (la marca anterior al
    último bloque de marcas que cubre el volumen de un día: en la réplica, casi toda la tabla; una cota superior de
    una llegada diaria)."""
    sql, params = _incremental(motor, "demanda_segmentos", PROCESO)
    sql_ruta, params_ruta = _incremental(motor, "demanda_segmentos", PROCESO, con_rutas=True)
    salida = []
    for regimen, marca, texto in (("sin_novedades", ctx["marca_max"], "sin novedades (marca = la mayor)"),
                                  ("bloque", ctx["marca_dia"], "bloque de llegada de la réplica")):
        salida += [
            Consulta(f"demanda_segmentos_{regimen}", f"Lectura incremental de la demanda horaria, todas las rutas, "
                     f"{texto}", "fuentes._SQL_DEMANDA_SEGMENTOS", sql,
                     dict(params, marca=marca, limite=500000, proceso=PROCESO)),
            Consulta(f"demanda_segmentos_una_ruta_{regimen}", f"La misma lectura de UNA ruta (RNF-005, partición por "
                     f"ruta), {texto}", "fuentes._SQL_DEMANDA_SEGMENTOS + FILTRO_RUTAS_SEGMENTOS", sql_ruta,
                     dict(params_ruta, marca=marca, limite=500000, proceso=PROCESO, rutas=["CRA 54"]))]
    try:
        anterior = con_union_final_de_rutas(sql)
    except ValueError:             # la lectura cambió de forma: se mide sin la referencia (la prueba unitaria avisa)
        return salida
    salida.append(Consulta(
        "demanda_segmentos_bloque" + CON_UNION_FINAL, "Referencia, no es una lectura de la API: la del bloque de "
        "llegada con la unión final de rutas que la consulta tenía antes", "formulación anterior de "
        "fuentes._SQL_DEMANDA_SEGMENTOS", anterior,
        dict(params, marca=ctx["marca_dia"], limite=500000, proceso=PROCESO), referencia=True))
    return salida


def _refresco(motor, ctx: dict) -> list[Consulta]:
    from app.servicios import segmentos_refresco as R

    fin = ctx["ultima_fecha"]
    ventana, dia = _compilar(motor, R.SQL_FUENTE_VENTANA), _compilar(motor, R.SQL_FUENTE_DIA)
    return [
        Consulta("segmentos_ventana_sin_novedades", "Refresco de segmentos: ventana de solape sin novedades (marca = "
                 "la mayor), el costo fijo de cada refresco", "segmentos_refresco.SQL_FUENTE_VENTANA", ventana,
                 {"marca": ctx["marca_max"]}),
        Consulta("segmentos_ventana_bloque", "Refresco de segmentos: ventana de solape desde el bloque de llegada de "
                 "la réplica − 15 min", "segmentos_refresco.SQL_FUENTE_VENTANA", ventana,
                 {"marca": ctx["marca_dia"] - SOLAPE}),
        Consulta("segmentos_grano_diario_1_fecha", "Refresco de segmentos: grano diario de la última fecha (lo que "
                 "relee un incremental con una fecha cambiada)", "segmentos_refresco.SQL_FUENTE_DIA", dia,
                 {"desde": fin, "hasta": fin, "idruta": None}),
        Consulta("segmentos_grano_diario_7_fechas", "Refresco de segmentos: grano diario de un tramo de 7 fechas "
                 "(12,5 % de la réplica; con el histórico completo serían unas 7 de 1.095 fechas)",
                 "segmentos_refresco.SQL_FUENTE_DIA", dia, {"desde": fin - timedelta(days=6), "hasta": fin,
                                                            "idruta": None}),
        Consulta("segmentos_rango", "Refresco de segmentos: rango de la fuente (min/max de fecha y marca)",
                 "segmentos_refresco.SQL_FUENTE_RANGO", _compilar(motor, R.SQL_FUENTE_RANGO), {})]


def _viajes(motor, ctx: dict) -> list[Consulta]:
    from app.servicios import fuentes

    dia = ctx["ultima_fecha"]
    inicio = datetime.combine(dia, datetime.min.time(), tzinfo=ZONA)
    franjas = [(r, dia, h) for r in RUTAS for h in range(4, 21)]
    return [
        Consulta("ocupacion_actual", "Ocupación actual por segmento: viaje × segmento de las 51 franjas de un día "
                 "(§10.1)", "fuentes._SQL_CARGA_SEGMENTOS", _compilar(motor, fuentes._SQL_CARGA_SEGMENTOS),
                 {"rutas": [r for r, _, _ in franjas], "fechas": [f for _, f, _ in franjas],
                  "horas": [h for _, _, h in franjas], "proceso": PROCESO, "limite": 500000}),
        Consulta("viajes_de_una_ruta", "Viajes de una ruta y un día con su conteo de segmentos (§5.3, ALT-006 y "
                 "ALT-009)", "fuentes.sql_viajes_ruta(con_segmentos=True)",
                 _compilar(motor, fuentes.sql_viajes_ruta(True)),
                 {"ruta": "CRA 54", "proceso": PROCESO, "desde": inicio, "hasta": inicio + timedelta(days=1),
                  "limite": fuentes.LIMITE_VIAJES})]


# el count(*) por tabla y proceso que hacía consolidados._sin_filas con la tabla sin cambios (hasta esta revisión;
# {tabla} es una de consolidados.TABLAS; también lo mide scripts/replica_lectura_consolidados.py) y su alternativa
SQL_CONTEO_RETIRADO = ("SELECT count(*) AS filas FROM {tabla} "
                       "WHERE (CAST(:proceso AS text) IS NULL OR proceso = CAST(:proceso AS text))")
SQL_CONTEO_ANTERIOR = SQL_CONTEO_RETIRADO.format(tabla="timbradas_consolidado")
SQL_EXISTE = "SELECT EXISTS (SELECT 1 FROM timbradas_consolidado WHERE proceso = :proceso) AS hay"


def _consolidados(motor, ctx: dict) -> list[Consulta]:
    from app.servicios import consolidados

    sql_p, params_p = _incremental(motor, "timbradas_consolidado", PROCESO)
    sql_t, params_t = _incremental(motor, "timbradas_consolidado", None)
    resellado = ctx["marca_consolidado"] - SOLAPE
    return [
        Consulta("consolidado_sin_novedades", "Consolidado: lectura incremental del proceso sin novedades (marca = la "
                 "mayor), lo de cada ciclo entre dos cierres", "fuentes.consulta_incremental (TABLAS_CON_PROCESO)",
                 sql_p, dict(params_p, marca=ctx["marca_consolidado"], proceso=PROCESO)),
        Consulta("consolidado_resellado", "Consolidado: la lectura del proceso tras el resellado nocturno (marca = la "
                 "mayor − solape: fn_consolidar vuelve a sellar toda la tabla, H7; las huellas descartan lo repetido)",
                 "fuentes.consulta_incremental (TABLAS_CON_PROCESO)", sql_p,
                 dict(params_p, marca=resellado, proceso=PROCESO)),
        Consulta("consolidado_todos_los_procesos", "Consolidado: la lectura tras el resellado sin filtrar el proceso "
                 "(como antes de esta revisión)", "fuentes.consulta_incremental (proceso «*»)", sql_t,
                 dict(params_t, marca=resellado)),
        Consulta("consolidado_carga_inicial", "Consolidado: carga inicial del proceso (marca inicial, toda la tabla)",
                 "fuentes.consulta_incremental (TABLAS_CON_PROCESO)", sql_p,
                 dict(params_p, marca=datetime(1970, 1, 1, tzinfo=UTC), proceso=PROCESO)),
        Consulta("consolidado_agregado_rutas", "Consolidado: agregado de las rutas tocadas para el contraste",
                 "consolidados._SQL_FUENTE[timbradas_consolidado]",
                 _compilar(motor, consolidados._SQL_FUENTE[consolidados.TABLA_RUTA]),
                 {"ids": [2, 16, 21], "proceso": PROCESO}),
        Consulta("consolidado_conteo_del_proceso", "Consolidado: el count(*) del proceso que hacía _sin_filas en cada "
                 "ciclo sin cambios (ya no se hace)", "consolidados._SQL_CONTEO (retirado)",
                 _compilar(motor, SQL_CONTEO_ANTERIOR), {"proceso": PROCESO}),
        Consulta("consolidado_existe_el_proceso", "Consolidado: EXISTS del proceso (alternativa al count(*))",
                 "alternativa medida", _compilar(motor, SQL_EXISTE), {"proceso": PROCESO})]


def consultas(motor, ctx: dict) -> dict[str, Consulta]:
    todas = [*_lecturas(motor, ctx), *_refresco(motor, ctx), *_viajes(motor, ctx), *_consolidados(motor, ctx)]
    return {c.clave: c for c in todas}


# ---------------------------------------------------------------- medición en una transacción que se revierte
def _explicar(conn, c: Consulta) -> dict:
    from scripts import replica_explain as rx

    plan = conn.exec_driver_sql("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + c.sql, c.params).scalar()
    return rx.resumir_plan(plan)


def _mejor(conn, c: Consulta) -> dict:
    corridas = [_explicar(conn, c) for _ in range(REPETICIONES)]
    mejor = min(corridas, key=lambda r: r["ms_ejecucion"])
    return dict(mejor, ms_corridas=[r["ms_ejecucion"] for r in corridas])


def _preparar(conn) -> None:
    conn.exec_driver_sql(f"SET LOCAL lock_timeout = '{ESPERA_CANDADO}'")         # constantes del script
    conn.exec_driver_sql(f"SET LOCAL statement_timeout = {int(TIEMPO_MAXIMO_MS)}")
    conn.exec_driver_sql("SET LOCAL TimeZone = 'America/Bogota'")


def _estado(conn, nombre: str) -> dict:
    fila = conn.exec_driver_sql(
        "SELECT i.indisvalid, i.indcheckxmin, pg_relation_size(i.indexrelid) FROM pg_index i "
        "WHERE i.indexrelid = CAST(%(n)s AS regclass)", {"n": f"public.{nombre}"}).one()
    return {"valido": bool(fila[0]), "indcheckxmin": bool(fila[1]), "mb": round(fila[2] / 2**20, 1)}


def medir_escenario(motor, nombre: str, indices: list[Candidato], objetivo: list[Consulta]) -> dict:
    """Las consultas sin los índices y con ellos, en UNA transacción que se revierte."""
    r: dict = {"escenario": nombre, "indices": [c.nombre for c in indices]}
    with motor.connect() as conn:
        try:
            _preparar(conn)
            r["sin"] = {c.clave: _mejor(conn, c) for c in objetivo}
            r["creados"] = {}
            for cand in indices:
                t0 = time.perf_counter()
                conn.exec_driver_sql(cand.ddl)
                r["creados"][cand.nombre] = {"segundos": round(time.perf_counter() - t0, 2),
                                             **_estado(conn, cand.nombre)}
            r["con"] = {c.clave: _mejor(conn, c) for c in objetivo}
        except Exception as exc:  # noqa: BLE001 - se registra (p. ej. un escritor con el candado) y sigue
            r["error"] = str(exc).splitlines()[0][:300]
        finally:
            conn.rollback()
    print(f"[{nombre}] " + ", ".join(f"{k}: {r.get('sin', {}).get(k, {}).get('ms_ejecucion')} -> "
                                     f"{r.get('con', {}).get(k, {}).get('ms_ejecucion')} ms" for k in
                                     (c.clave for c in objetivo)) + (f" ERROR {r['error']}" if "error" in r else ""))
    return r


def medir_propuesta_entera(motor, objetivo: list[Consulta], sin: tuple[str, ...] = ()) -> dict:
    """Las consultas sin índices y con TODA la propuesta (menos los índices de `sin`), con ANALYZE en los dos lados (las
    estadísticas al día antes y después, también las de la expresión de un índice), en UNA transacción que se
    revierte."""
    indices = indices_de_la_propuesta(sin)
    escenario = SIN_EL_3 if sin else ENTERA
    r: dict = {"escenario": escenario, "indices": [n for n, _ddl in indices], "omitidos": list(sin),
               "analyze": list(TABLAS_DE_LA_PROPUESTA), "referencias": [c.clave for c in objetivo if c.referencia]}
    with motor.connect() as conn:
        try:
            _preparar(conn)
            _analizar(conn)
            r["sin"] = {c.clave: _mejor(conn, c) for c in objetivo}
            r["creados"] = {}
            for nombre, ddl in indices:
                t0 = time.perf_counter()
                conn.exec_driver_sql(ddl)
                r["creados"][nombre] = {"segundos": round(time.perf_counter() - t0, 2), **_estado(conn, nombre)}
            _analizar(conn)
            r["con"] = {c.clave: _mejor(conn, c) for c in objetivo}
        except Exception as exc:  # noqa: BLE001 - se registra (p. ej. un escritor con el candado) y sigue
            r["error"] = str(exc).splitlines()[0][:300]
        finally:
            conn.rollback()
    print(f"[{escenario}] " + ", ".join(f"{c.clave}: {r.get('sin', {}).get(c.clave, {}).get('ms_ejecucion')} -> "
                                        f"{r.get('con', {}).get(c.clave, {}).get('ms_ejecucion')} ms"
                                        for c in objetivo) + (f" ERROR {r['error']}" if "error" in r else ""),
          flush=True)
    return r


# Lo que importa del índice 3 (el de la expresión): la lectura del bloque grande (hoy y con la formulación anterior), el
# régimen sin novedades y los viajes de una ruta de §5.3, la consulta a la que sirve
CONSULTAS_DEL_INDICE_3 = ("demanda_segmentos_bloque", "demanda_segmentos_bloque" + CON_UNION_FINAL,
                          "demanda_segmentos_sin_novedades", "viajes_de_una_ruta")


def _analizar(conn) -> None:
    """ANALYZE de las tablas de la propuesta dentro de la transacción: sus estadísticas se revierten con ella."""
    for tabla in TABLAS_DE_LA_PROPUESTA:
        conn.exec_driver_sql(f"ANALYZE public.{tabla}")       # constantes del script


def _usa(medida: dict, nombre: str) -> bool:
    return any(nombre in e for e in medida.get("escaneos") or [])


def comparar(escenario: dict) -> dict:
    """Por consulta: ms sin y con, mejora relativa, ahorro, si el plan usa alguno de los índices del escenario y las
    filas que descarta el filtro de una unión (un ciclo anidado que compara todas las parejas)."""
    salida = {}
    for clave, sin in (escenario.get("sin") or {}).items():
        con = escenario["con"][clave]
        ms_sin, ms_con = sin["ms_ejecucion"], con["ms_ejecucion"]
        salida[clave] = {"ms_sin": ms_sin, "ms_con": ms_con, "ahorro_ms": round(ms_sin - ms_con, 2),
                         "mejora": round(1 - ms_con / ms_sin, 3) if ms_sin > 0 else None,
                         "usa_indice": any(_usa(con, n) for n in escenario["indices"]),
                         "escaneos_sin": sin["escaneos"], "escaneos_con": con["escaneos"], "filas": con["filas"],
                         "descartadas_por_union_sin": sin.get("filas_descartadas_por_union", 0),
                         "descartadas_por_union_con": con.get("filas_descartadas_por_union", 0)}
    return salida


def empeora(v: dict) -> bool:
    """La consulta tarda con los índices más de EMPEORA_MAXIMO que sin ellos (y más de RUIDO_MS)."""
    return v["mejora"] is not None and v["mejora"] < -EMPEORA_MAXIMO and -v["ahorro_ms"] > RUIDO_MS


def empeoran(comparacion: dict, referencias: tuple[str, ...] | list[str] = ()) -> list[str]:
    """Las lecturas de la API que empeoran con los índices del escenario (las de referencia no cuentan)."""
    return [clave for clave, v in comparacion.items() if clave not in referencias and empeora(v)]


def respalda(comparacion: dict) -> bool:
    """La medición justifica el índice: alguna consulta mejora al menos MEJORA_MINIMA y AHORRO_MINIMO_MS usando el
    índice, y ninguna de las que mide empeora más de EMPEORA_MAXIMO."""
    if not comparacion:
        return False
    alguna = any(v["usa_indice"] and (v["mejora"] or 0) >= MEJORA_MINIMA and v["ahorro_ms"] >= AHORRO_MINIMO_MS
                 for v in comparacion.values())
    return alguna and not empeoran(comparacion)


def veredicto_de_la_propuesta(entera: dict | None) -> dict:
    """El criterio de «ningún empeoramiento» con la propuesta ENTERA y las estadísticas al día: qué lecturas de la API
    empeoran, cuáles mejoran al menos MEJORA_MINIMA y AHORRO_MINIMO_MS, y en cuáles la propuesta trae un filtro de
    unión que antes no descartaba filas (un ciclo anidado elegido con una mala estimación). None en
    `sin_empeoramiento` si no se pudo medir."""
    comparacion = (entera or {}).get("comparacion") or {}
    if not comparacion:
        return {"medida": False, "sin_empeoramiento": None, "empeoran": [], "mejoran": [], "con_filtro_de_union": []}
    referencias = (entera or {}).get("referencias") or []
    propias = {k: v for k, v in comparacion.items() if k not in referencias}
    peores = empeoran(comparacion, referencias)
    return {"medida": True, "sin_empeoramiento": not peores, "empeoran": peores,
            "mejoran": [k for k, v in propias.items()
                        if (v["mejora"] or 0) >= MEJORA_MINIMA and v["ahorro_ms"] >= AHORRO_MINIMO_MS],
            "con_filtro_de_union": [k for k, v in propias.items()
                                    if v["descartadas_por_union_con"] > v["descartadas_por_union_sin"]]}


def _indices_al_terminar(cx) -> list[str]:
    with cx.cursor() as cur:
        cur.execute("SELECT indexname FROM pg_indexes WHERE schemaname = 'public' AND indexname LIKE 'ix\\_ia\\_%'")
        return [r[0] for r in cur.fetchall()]


def _motor_dba():
    from sqlalchemy import create_engine

    url = rc.url_rol("extreme_dba")
    if not url:
        raise SystemExit("Falta OPERACIONAL_PASSWORD (o REPLICA_URL) en el entorno o en el .env local.")
    return create_engine(url.replace("postgresql://", "postgresql+psycopg://", 1), pool_size=1, max_overflow=0)


def _escenarios(todas: dict[str, Consulta]) -> list[tuple[str, list[Candidato], list[Consulta]]]:
    por_nombre = {c.nombre: c for c in CANDIDATOS}
    lista = [(c.nombre, [c], [todas[k] for k in c.para]) for c in CANDIDATOS]
    for nombre, indices in COMBINADOS.items():
        cands = [por_nombre[n] for n in indices]
        objetivo = sorted({k for c in cands for k in c.para}, key=list(todas).index)
        lista.append((nombre, cands, [todas[k] for k in objetivo]))
    return lista


def medir(solo: list[str] | None = None) -> dict:
    from scripts.replica_simular_llegada import candado, conectar

    motor = _motor_dba()
    admin = conectar("extreme_dba", autocommit=True)
    informe: dict = {"generado": datetime.now(ZONA).isoformat(timespec="seconds"), "rol": "extreme_dba",
                     "metodo": ("cada escenario en una transacción que se revierte: consultas sin el índice, CREATE "
                                "INDEX, las mismas consultas, ROLLBACK; sin ANALYZE; lock_timeout "
                                f"{ESPERA_CANDADO}; la más rápida de {REPETICIONES} corridas por lado. La propuesta "
                                "entera, en otra transacción que se revierte, con todas las consultas y ANALYZE en los "
                                "dos lados"),
                     "criterio": {"mejora_minima": MEJORA_MINIMA, "ahorro_minimo_ms": AHORRO_MINIMO_MS,
                                  "empeora_maximo": EMPEORA_MAXIMO, "ruido_ms": RUIDO_MS}}
    try:
        with candado(admin):
            ctx = contexto(admin)
            todas = consultas(motor, ctx)
            informe["contexto"] = {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in ctx.items()}
            informe["consultas"] = {k: {"descripcion": c.descripcion, "origen": c.origen, "referencia": c.referencia}
                                    for k, c in todas.items()}
            escenarios = [e for e in _escenarios(todas) if not solo or e[0] in solo]
            informe["escenarios"] = []
            for nombre, indices, objetivo in escenarios:
                medido = medir_escenario(motor, nombre, indices, objetivo)
                medido["comparacion"] = comparar(medido) if "con" in medido else {}
                medido["respaldado"] = respalda(medido["comparacion"])
                informe["escenarios"].append(medido)
            if not solo or ENTERA in solo:
                entera = medir_propuesta_entera(motor, list(todas.values()))
                informe[ENTERA] = dict(entera, comparacion=comparar(entera) if "con" in entera else {})
                sin_3 = medir_propuesta_entera(motor, [todas[k] for k in CONSULTAS_DEL_INDICE_3 if k in todas],
                                               sin=(INDICE_3,))
                informe[SIN_EL_3] = dict(sin_3, comparacion=comparar(sin_3) if "con" in sin_3 else {})
            informe["indices_en_la_replica_al_terminar"] = _indices_al_terminar(admin)
    finally:
        admin.close()
        motor.dispose()
    informe["decision"] = decision(informe)
    informe["veredicto"] = veredicto_de_la_propuesta(informe.get(ENTERA))
    return informe


def _respaldo(c: Candidato, escenarios: list[dict]) -> tuple[bool | None, list[str]]:
    """(respaldado, escenarios que lo respaldan): su escenario solo, o uno combinado en el que alguna consulta que
    cumple el criterio usa ESTE índice. None si ningún escenario con él se pudo medir."""
    medidos = [e for e in escenarios if c.nombre in e["indices"] and "comparacion" in e and "error" not in e]
    if not medidos:
        return None, []
    que = [e["escenario"] for e in medidos if e["respaldado"] and any(
        any(c.nombre in x for x in v["escaneos_con"]) and (v["mejora"] or 0) >= MEJORA_MINIMA
        and v["ahorro_ms"] >= AHORRO_MINIMO_MS for v in e["comparacion"].values())]
    return bool(que), que


def decision(informe: dict) -> list[dict]:
    """Cada candidato: si va en la propuesta y si la medición lo respalda (solo o con los índices que se usan junto)."""
    escenarios = informe.get("escenarios", [])
    salida = []
    for c in CANDIDATOS:
        respaldado, por = _respaldo(c, escenarios)
        salida.append({"indice": c.nombre, "tabla": c.tabla, "columnas": c.columnas, "propuesto": c.propuesto,
                       "ya_propuesto_en_la_ola_a": c.antes, "respaldado_por_la_medicion": respaldado,
                       "escenarios_que_lo_respaldan": por, "nota": c.nota})
    return salida


# ---------------------------------------------------------------- informe
def _ms(x) -> str:
    return "—" if x is None else f"{x:,.1f}".replace(",", "§").replace(".", ",").replace("§", ".")


def _pct(x) -> str:
    return "—" if x is None else f"{100 * x:.0f} %".replace("-", "−")


def _miles(x) -> str:
    return f"{int(x):,}".replace(",", ".")


def _informe_entera(r: dict) -> list[str]:
    """Sección del informe: la propuesta ENTERA con las estadísticas al día y el criterio de ningún empeoramiento."""
    entera = r.get(ENTERA)
    if not entera:
        return []
    titulo = ["", "## La propuesta entera, con las estadísticas al día (ANALYZE)", ""]
    if "error" in entera or not entera.get("comparacion"):
        return [*titulo, f"No se pudo medir: {entera.get('error', 'sin comparación')}."]
    veredicto = r.get("veredicto") or veredicto_de_la_propuesta(entera)
    referencias = entera.get("referencias") or []
    lin = [*titulo,
           f"Una transacción que se revierte: ANALYZE de {', '.join(entera['analyze'])}; todas las consultas; CREATE "
           f"INDEX de los {len(entera['indices'])} índices de la propuesta; ANALYZE otra vez; las mismas consultas; "
           "ROLLBACK. Las estadísticas están al día en los dos lados, también las de la expresión del índice sobre "
           "`date_trunc('hour', fechasalida)`, que es lo que tendrá la base después de que el DBA cree los índices.",
           "", *_tabla_entera(entera, "ms con la propuesta")]
    if veredicto["sin_empeoramiento"]:
        lin += ["", f"**Ninguna lectura de la API empeora** más de {_pct(EMPEORA_MAXIMO)} con la propuesta entera: el "
                    f"criterio se cumple también así. Mejoran al menos {_pct(MEJORA_MINIMA)} y "
                    f"{AHORRO_MINIMO_MS:.0f} ms: {_lista(veredicto['mejoran'])}."]
    else:
        lin += ["", f"**Con la propuesta entera empeoran más de {_pct(EMPEORA_MAXIMO)}: "
                    f"{_lista(veredicto['empeoran'])}.** El criterio de ningún empeoramiento NO se cumple con la "
                    "propuesta entera."]
    if veredicto["con_filtro_de_union"]:
        lin += ["", f"Con la propuesta, el filtro de una unión descarta filas que sin ella no descartaba, en: "
                    f"{_lista(veredicto['con_filtro_de_union'])}."]
    return lin + _nota_de_las_referencias(entera, referencias) + _informe_sin_el_3(r)


def _tabla_entera(medida: dict, columna_con: str) -> list[str]:
    """La tabla de una medición con ANALYZE en los dos lados: cada consulta sin índices y con ellos."""
    referencias = medida.get("referencias") or []
    lin = [f"| Consulta | ms sin índices | {columna_con} | Mejora | Filas descartadas en uniones, sin → con | "
           "Empeora |", "|---|---|---|---|---|---|"]
    for clave, v in medida["comparacion"].items():
        nombre = f"{clave} (referencia)" if clave in referencias else clave
        lin.append(f"| {nombre} | {_ms(v['ms_sin'])} | {_ms(v['ms_con'])} | {_pct(v['mejora'])} | "
                   f"{_miles(v['descartadas_por_union_sin'])} → {_miles(v['descartadas_por_union_con'])} | "
                   f"{'sí' if empeora(v) else 'no'} |")
    return lin


def _nota_de_las_referencias(entera: dict, referencias: list[str]) -> list[str]:
    """Qué es cada consulta de referencia de la propuesta entera y qué le pasa con ella."""
    lin = []
    for clave in referencias:
        v = entera["comparacion"].get(clave)
        if v:
            lin += ["", f"`{clave}` no es una lectura de la API: es la del bloque de llegada con la unión final de "
                        "`rutas` que `fuentes._SQL_DEMANDA_SEGMENTOS` tenía hasta el 13-11-2026. Con la propuesta "
                        f"entera pasa de {_ms(v['ms_sin'])} a {_ms(v['ms_con'])} ms y descarta "
                        f"{_miles(v['descartadas_por_union_con'])} filas en el filtro de una unión: PostgreSQL estima "
                        "`viajes ⋈ rutas` con el ndistinct por omisión de un CTE y, con las estadísticas de la "
                        "expresión del índice 3, elige un ciclo anidado con Materialize. Por eso la lectura ya no "
                        "vuelve a unir `rutas` (el nombre y la empresa viajan desde el CTE `franjas`): entrega las "
                        "mismas filas en el mismo orden."]
    return lin


def _informe_sin_el_3(r: dict) -> list[str]:
    """Subsección: la misma medición sin el índice 3, para dejar medido que es el que cambia el plan de la formulación
    anterior y lo que se perdería sin él (por eso se conserva y se corrigió la lectura)."""
    sin_3, entera = r.get(SIN_EL_3), r.get(ENTERA) or {}
    if not sin_3 or not sin_3.get("comparacion"):
        return []
    lin = ["", "### La misma medición sin el índice 3 (cuál cambia el plan y qué se perdería sin él)", "",
           f"Otra transacción que se revierte, con ANALYZE en los dos lados y los {len(sin_3['indices'])} índices de "
           f"la propuesta menos `{INDICE_3}`:", "", *_tabla_entera(sin_3, "ms sin el índice 3")]
    con_todos = entera.get("comparacion") or {}
    frases = []
    for clave, texto in (("demanda_segmentos_bloque" + CON_UNION_FINAL, "la formulación anterior del bloque"),
                         ("viajes_de_una_ruta", "los viajes de una ruta y un día (§5.3)"),
                         ("demanda_segmentos_sin_novedades", "la lectura sin novedades de cada ciclo")):
        if clave in sin_3["comparacion"] and clave in con_todos:
            frases.append(f"{texto}, {_ms(sin_3['comparacion'][clave]['ms_con'])} ms sin el índice 3 frente a "
                          f"{_ms(con_todos[clave]['ms_con'])} ms con la propuesta entera")
    if frases:
        lin += ["", "Con las estadísticas al día: " + "; ".join(frases) + ". El cambio de plan de la formulación "
                    "anterior viene de las estadísticas de la expresión de ese índice; quitarlo lo evitaría, pero "
                    "se perdería lo que aporta a los viajes de una ruta y al régimen sin novedades. Por eso el "
                    "índice sigue en la propuesta y lo que se corrigió fue la lectura."]
    return lin


def _lista(claves: list[str]) -> str:
    return ", ".join(f"`{c}`" for c in claves) or "ninguna"


def informe_md(r: dict) -> str:
    ctx = r["contexto"]
    lin = ["# Índices candidatos medidos en la réplica, dentro de transacciones que se revierten", "",
           f"Generado {r['generado']} con `python -m scripts.replica_indices_candidatos` como {r['rol']} (el dueño de "
           f"las tablas). Método: {r['metodo']}. Volumen: {ctx['volumen']['timbradas_segmentos_filas']:,} filas de "
           f"timbradas_segmentos ({ctx['volumen']['tamano_mb']} MB) y {ctx['volumen']['progvehiculos_viajes']:,} "
           f"viajes de progvehiculos; marca de un día {ctx['marca_dia']}, última fecha {ctx['ultima_fecha']}.", "",
           f"Índices `ix_ia_*` en la réplica antes de medir: {ctx['indices_previos'] or 'ninguno'}; al terminar: "
           f"{r['indices_en_la_replica_al_terminar'] or 'ninguno'} (la réplica sigue fiel a Extreme).", "",
           f"Criterio: el índice se usa y baja al menos {_pct(MEJORA_MINIMA)} y {AHORRO_MINIMO_MS:.0f} ms alguna de "
           f"las consultas que lo justificarían, y ninguna empeora más de {_pct(EMPEORA_MAXIMO)} (una diferencia "
           f"menor de {RUIDO_MS:.0f} ms no cuenta). Ese «ningún empeoramiento» se evalúa además con la propuesta "
           "entera, más abajo.", "",
           "| Escenario | Consulta | ms sin | ms con | Mejora | Usa el índice | Escaneos con el índice |",
           "|---|---|---|---|---|---|---|"]
    for e in r["escenarios"]:
        if "error" in e:
            lin.append(f"| {e['escenario']} | — | — | — | — | — | no se pudo medir: {e['error']} |")
            continue
        for clave, v in e["comparacion"].items():
            lin.append(f"| {e['escenario']} | {clave} | {_ms(v['ms_sin'])} | {_ms(v['ms_con'])} | {_pct(v['mejora'])} "
                       f"| {'sí' if v['usa_indice'] else 'no'} | {', '.join(v['escaneos_con'])} |")
    lin += _informe_entera(r)
    lin += ["", "## Decisión (`docs/evidencias/replica/propuesta_indices.sql`)", "",
            "| Índice | Tabla (columnas) | Respaldado por la medición | En la propuesta | Por qué |",
            "|---|---|---|---|---|"]
    for d in r["decision"]:
        resp = {True: "sí", False: "no", None: "—"}[d["respaldado_por_la_medicion"]]
        ola_a = " (desde la ola A)" if d["ya_propuesto_en_la_ola_a"] else ""
        lin.append(f"| `{d['indice']}` | {d['tabla']} ({d['columnas']}) | {resp} | "
                   f"{'sí' if d['propuesto'] else 'no'}{ola_a} | {d.get('nota', '')} |")
    lin += ["", "El de `timbradas_anio` por `ultima_actualizacion` sigue en la propuesta por §8.3 con el argumento del "
                "de `timbradas_consolidado`. Para `timbradas_segmentos_anio` y `timbradas_segmentos_consolidado`, que "
                "en la réplica no tienen filas de Sobusa (H4) y en la base de Extreme son de otros operadores, la "
                "propuesta trae el índice por (`proceso`, `ultima_actualizacion`): sin filas del proceso no hay marca "
                "guardada y la lectura del proceso empieza en la marca inicial, así que la marca sola no evita "
                "recorrer las filas ajenas. Se midió con ese volumen en una tabla temporal, dentro de una transacción "
                "que se revierte (`scripts/replica_lectura_consolidados.py`, "
                "`docs/evidencias/consolidados/lectura_por_proceso.md`). `explain_incremental.txt` "
                "(`scripts/replica_explain.py`) aplica esta propuesta entera como extreme_dba, con esos dos índices "
                "por (`proceso`, `ultima_actualizacion`), mide con las estadísticas al día (ANALYZE) y la borra al "
                "terminar; como en la réplica las dos tablas están vacías, su lectura es un Seq Scan con ellos y sin "
                "ellos."]
    lin += ["", "Consultas medidas:", ""]
    lin += [f"- `{k}`: {v['descripcion']} (`{v['origen']}`)." for k, v in r["consultas"].items()]
    lin += ["", "Las cifras absolutas dependen de la carga del equipo (la réplica corre en el mismo equipo que las "
                "pruebas); la comparación es la de cada transacción, con la misma carga. Crear los índices sigue "
                "siendo decisión de Extreme (§8.3).", ""]
    return "\n".join(lin)


def escribir(r: dict) -> None:
    """La evidencia (JSON y Markdown) y la propuesta para el DBA, desde la misma decisión."""
    SALIDA.mkdir(parents=True, exist_ok=True)
    (SALIDA / "indices_candidatos.json").write_text(json.dumps(r, ensure_ascii=False, indent=1, default=str),
                                                    encoding="utf-8")
    (SALIDA / "indices_candidatos.md").write_text(informe_md(r), encoding="utf-8")
    (SALIDA / "propuesta_indices.sql").write_text(propuesta_sql(), encoding="utf-8")


def main(argv: list[str] | None = None) -> dict:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--solo", nargs="*", help="escenarios a medir (por omisión, todos)")
    p.add_argument("--informe", action="store_true",
                   help="no mide: rehace el informe y la propuesta desde indices_candidatos.json")
    a = p.parse_args(argv)
    if a.informe:
        r = json.loads((SALIDA / "indices_candidatos.json").read_text(encoding="utf-8"))
        r["decision"] = decision(r)
        r["veredicto"] = veredicto_de_la_propuesta(r.get(ENTERA))
    else:
        r = medir(a.solo)
    escribir(r)
    print(json.dumps(r["decision"], ensure_ascii=False, indent=1))
    return r


if __name__ == "__main__":
    main()
