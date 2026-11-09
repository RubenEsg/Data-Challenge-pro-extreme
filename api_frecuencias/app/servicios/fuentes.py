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

El ciclo diario (FUENTE_TABLA) solo procesa de punta a punta «demanda_segmentos»: es la única lectura con el
contrato de demanda horaria que validan la calidad, la ingesta y el modelo. Las demás tablas de la lista blanca se
leen con esta misma clase para los catálogos, la capa de segmentos, las pruebas y las evidencias de la réplica.

Definición de pasajeros en modo integrado (docs/evidencias/datos/definicion_pasajeros.md): igual que el objetivo del
modelo y el histórico empaquetado, pasajeros = Σ numeropasajeros de los viajes válidos de progvehiculos (finalizado
'S', no cancelado, dato <= 300) que salen en esa hora y salidas = número de viajes válidos. Σ subidas de
timbradas_segmentos queda en la columna subidas (5,2 % menos que numeropasajeros en el solape de 2023). La consulta
une rutas, "Procesos" y estacionalidades_anio (§11.2): filtra por FUENTE_PROCESO y entrega proceso, idempresa e
id_estacionalidad (vigente en la fecha, período más corto) de cada franja.
"""
from __future__ import annotations

import hashlib
import math
import os
import re
from datetime import UTC, datetime, timedelta, timezone

import pandas as pd

MARCA_INICIAL = datetime(1970, 1, 1, tzinfo=UTC)
ZONA = "America/Bogota"
SOLAPE_MIN_DEFECTO = 15
# 2: la huella de demanda_segmentos cambió (definición de pasajeros y columnas de proceso y estacionalidad); un estado
# de otra versión no se compara y la primera lectura vuelve a entregar la ventana de solape.
VERSION_ESTADO = 2
# Lectura que el ciclo procesa de punta a punta (FUENTE_TABLA) y proceso (operador) por omisión.
TABLA_CICLO = "demanda_segmentos"
TABLAS_CICLO = (TABLA_CICLO,)
PROCESO_DEFECTO = "sobusa"
DEFINICION_PASAJEROS = "numeropasajeros_viajes_validos_v2"
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
# hora, la misma definición del objetivo del modelo; salidas = viajes válidos; subidas y bajadas = Σ de los segmentos.
# La ruta se une con "Procesos" (raíz de las relaciones, filtro :proceso) y la estacionalidad vigente de la fecha sale
# de estacionalidades_anio con el desempate de fn_insert_timbradas_anio (el período más corto).
_SQL_DEMANDA_SEGMENTOS = """
WITH cambiados AS (
    SELECT DISTINCT ts.id_viaje
      FROM timbradas_segmentos ts
     WHERE ts.ultimaactualizacion > :marca{filtro_hasta}
), franjas AS (
    SELECT DISTINCT pv.idruta, r.proceso, date_trunc('hour', pv.fechasalida) AS franja
      FROM cambiados c
      JOIN progvehiculos pv ON pv.idprogramacion = c.id_viaje
      JOIN rutas r ON r.idruta = pv.idruta
      JOIN "Procesos" p ON p.proceso = r.proceso
     WHERE (CAST(:proceso AS text) IS NULL OR r.proceso = CAST(:proceso AS text))
), viajes AS (
    SELECT pv.idprogramacion, f.idruta, f.proceso, f.franja, pv.numeropasajeros,
           (pv.finalizado = 'S' AND pv.cancelada = 'N') AS valido
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
SELECT r.nombre AS ruta, v.idruta, v.proceso, r.idempresa, CAST(v.franja AS date) AS fecha,
       CAST(EXTRACT(HOUR FROM v.franja) AS integer) AS hora,
       CAST(COALESCE(SUM(v.numeropasajeros) FILTER (WHERE v.valido AND v.numeropasajeros <= 300), 0)
            AS double precision) AS pasajeros,
       COUNT(*) FILTER (WHERE v.valido) AS salidas,
       SUM(s.subidas) AS subidas, SUM(s.bajadas) AS bajadas, SUM(s.filas) AS filas_segmento,
       COUNT(s.idprogramacion) AS viajes_con_timbradas,
       es.id_estacionalidad, es.id_estacionalidad_anio,
       MAX(s.marca) AS ultima_actualizacion
  FROM viajes v
  LEFT JOIN segmentos_viaje s ON s.idprogramacion = v.idprogramacion
  JOIN rutas r ON r.idruta = v.idruta
  LEFT JOIN estacion es ON es.proceso = v.proceso AND es.fecha = CAST(v.franja AS date)
 GROUP BY r.nombre, v.idruta, v.proceso, r.idempresa, v.franja, es.id_estacionalidad, es.id_estacionalidad_anio
 ORDER BY ultima_actualizacion, ruta, fecha, hora
 LIMIT :limite
"""

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
}

_PROHIBIDAS = re.compile(
    r"\b(INSERT|UPDATE|DELETE|MERGE|UPSERT|CREATE|ALTER|DROP|TRUNCATE|GRANT|REVOKE|COPY|CALL|DO|EXECUTE|PREPARE|"
    r"VACUUM|ANALYZE|REINDEX|CLUSTER|LOCK|COMMENT|REFRESH|SECURITY|LISTEN|NOTIFY|INTO|SET|RESET|BEGIN|COMMIT|"
    r"ROLLBACK|SAVEPOINT|NEXTVAL|SETVAL|PG_SLEEP|DBLINK|LO_IMPORT|LO_EXPORT)\b|\bFOR\s+(UPDATE|SHARE|NO\s+KEY|KEY)\b",
    re.IGNORECASE)


class OperacionNoPermitida(PermissionError):
    """La fuente operacional es de solo lectura: solo se aceptan SELECT."""


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


class FuenteParquet:
    """Fuente offline por defecto: demanda horaria del proyecto (datos/demanda_horaria.parquet)."""

    nombre = "parquet"
    admite_estado = False

    def __init__(self, cargador=None):
        # cargador() -> DataFrame con el contrato de datos.demanda_horaria(); inyectable en pruebas.
        self._cargador = cargador

    def _cargar(self, hasta):
        if self._cargador is not None:
            return self._cargador()
        from . import datos
        return datos.demanda_horaria(hasta=hasta)

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
    modificadas, repetidas_solape) y `estado_incremental` (huellas de la ventana de solape) para guardarlos con la
    ejecución; la siguiente lectura recibe ese estado en `estado_previo`."""

    nombre = "postgres"
    admite_estado = True

    def __init__(self, url=None, tabla=TABLA_CICLO, statement_timeout_ms=None, motor=None, limite=500000,
                 solape_min=None, proceso=None):
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
                    return conn.execute(sentencia, parametros or {}).mappings().all()
                finally:
                    conn.rollback()                       # solo lectura: nunca se confirma nada

        # RNF-010: solo la conexión pasa por el circuit breaker (fallos de red o timeout lo abren; el SQL rechazado
        # arriba o un error de datos no). Abierto -> CircuitoAbierto sin tocar la base; la ejecución se reintenta.
        from app.servicios import circuito

        filas = circuito.obtener("fuente_postgres").llamar(_leer)
        return pd.DataFrame([dict(f) for f in filas])

    @property
    def columna_marca(self) -> str:
        return COLUMNA_MARCA.get(self.tabla, "ultima_actualizacion")

    def consulta_incremental(self, con_hasta=False):
        """SELECT de la tabla (lista blanca) con marca > :marca (y < :hasta), ordenado y limitado.

        Tablas: SQLAlchemy Core (el nombre viene de TABLAS_PERMITIDAS y se cita si hace falta, p. ej. "Procesos").
        Vista demanda_segmentos: SQL constante. En ambos casos los valores van como parámetros enlazados."""
        import sqlalchemy as sa

        if self.tabla not in TABLAS_PERMITIDAS:
            raise OperacionNoPermitida(f"Tabla no permitida: {self.tabla!r}.")
        if self.tabla == "demanda_segmentos":
            filtro = " AND ts.ultimaactualizacion < :hasta" if con_hasta else ""
            return sa.text(_SQL_DEMANDA_SEGMENTOS.format(filtro_hasta=filtro))
        col = self.columna_marca
        t = sa.table(self.tabla, sa.column(col))
        q = sa.select(sa.literal_column("*")).select_from(t)
        if self.tabla in TABLAS_SIN_MARCA:
            return q.limit(self.limite)
        q = q.where(t.c[col] > sa.bindparam("marca"))
        if con_hasta:
            q = q.where(t.c[col] < sa.bindparam("hasta"))
        return q.order_by(t.c[col]).limit(self.limite)

    # ------------------------------------------------------------------ lectura incremental
    def leer_incremental(self, marca_agua=None, hasta=None, estado_previo=None):
        """(df, nueva_marca). Lee marca > (marca_agua − solape) y entrega solo lo nuevo, tardío o modificado."""
        marca = _normalizar_marca(marca_agua)
        desde = marca - timedelta(minutes=self.solape_min) if marca > MARCA_INICIAL else marca
        params = {"marca": desde}
        if hasta is not None:
            h = hasta.date() if isinstance(hasta, datetime) else hasta
            params["hasta"] = datetime.combine(h + timedelta(days=1), datetime.min.time()).replace(
                tzinfo=timezone(timedelta(hours=-5)))   # fin del día en America/Bogota (UTC-5, sin horario de verano)
        sql = self.consulta_incremental(con_hasta=hasta is not None)
        if self.tabla in TABLAS_SIN_MARCA:
            d = self.consultar(sql, {})
            self.resumen_lectura = {"tabla": self.tabla, "leidas": len(d), "entregadas": len(d), "sin_marca": True}
            self.estado_incremental = None
            return d, marca
        if self.tabla == "demanda_segmentos":
            params.update(limite=self.limite, proceso=self.proceso)
        d = self.consultar(sql, params)
        return self._filtrar_por_huella(d, marca, desde, estado_previo)

    def _filtrar_por_huella(self, d, marca, desde, estado_previo):
        col = self.columna_marca
        leidas = len(d)
        resumen = {"tabla": self.tabla, "marca_anterior": marca.isoformat(), "desde": desde.isoformat(),
                   "solape_min": self.solape_min, "leidas": leidas, "truncada": leidas >= self.limite}
        if leidas == 0 or col not in d.columns:
            resumen.update(entregadas=leidas, nuevas=leidas, tardias=0, modificadas=0, repetidas_solape=0,
                           marca_nueva=marca.isoformat())
            self.resumen_lectura, self.estado_incremental = resumen, _estado(self, marca, {})
            return d, marca
        marcas = _marcas_con_zona(d[col])
        llave = [c for c in LLAVES.get(self.tabla, (d.columns[0],)) if c in d.columns] or [d.columns[0]]
        d = d.assign(_marca=marcas).sort_values("_marca", kind="stable")
        d = d.drop_duplicates(subset=llave, keep="last").reset_index(drop=True)     # deduplicar por llave natural
        valores = [c for c in sorted(d.columns) if c not in (col, "_marca")]
        claves = ["|".join(str(v) for v in fila) for fila in d[llave].itertuples(index=False, name=None)]
        huellas = [huella_fila(fila) for fila in d[valores].itertuples(index=False, name=None)]
        previas = _huellas_previas(estado_previo, self.tabla)
        repetida =[previas.get(k) == h for k, h in zip(claves, huellas, strict=True)]
        conocida = [k in previas for k in claves]
        posterior = (d["_marca"] > pd.Timestamp(marca)).tolist()
        nueva_marca = max(marca, pd.Timestamp(d["_marca"].max()).to_pydatetime())
        limite_estado = pd.Timestamp(nueva_marca - timedelta(minutes=self.solape_min))
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
        salida = d[entregar].drop(columns=["_marca"]).reset_index(drop=True)
        if col != "ultima_actualizacion" and "ultima_actualizacion" not in salida.columns:
            salida["ultima_actualizacion"] = salida[col]
        if "ultima_actualizacion" in salida.columns:
            salida["ultima_actualizacion"] = _marcas_con_zona(salida["ultima_actualizacion"])
        self.resumen_lectura, self.estado_incremental = resumen, _estado(self, nueva_marca, estado)
        return salida, nueva_marca

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
        if "capacidad" in rutas.columns:
            cat["capacidades"] = dict(zip(rutas["nombre"], pd.to_numeric(rutas["capacidad"], errors="coerce"),
                                          strict=True))
        return cat


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
           "COLUMNA_MARCA", "CONSULTAS_CONTEXTO", "MARCA_INICIAL", "DEFINICION_PASAJEROS"]
