"""Fuentes de datos de entrada con lectura incremental por ultima_actualizacion (especificación v1.5, §8.3 y §9.5).

- FuenteParquet (por defecto): los datos del proyecto empaquetados en datos/ (demanda_horaria.parquet, a través de
  app.servicios.datos.demanda_horaria). Sin red y reproducible. `hasta` simula la llegada diaria: solo son visibles las
  filas con fecha <= hasta, de modo que la demo puede mostrar ciclos incrementales día a día.
- FuentePostgresSoloLectura: las tablas consolidadas existentes (§8.2) en una base PostgreSQL con un usuario SELECT.
  URL en la variable de entorno FUENTE_DATABASE_URL (nunca en el repositorio). Cada lectura abre una transacción
  «SET TRANSACTION READ ONLY» con «SET LOCAL statement_timeout», ejecuta solo SELECT sobre tablas de una lista blanca y
  termina con ROLLBACK (nunca COMMIT). Cualquier sentencia que no sea SELECT se rechaza antes de tocar la base.
Ambas devuelven (DataFrame, nueva_marca); nueva_marca es la mayor ultima_actualizacion leída (o la marca recibida si no
llegó nada), y el orquestador la guarda por ejecución.
"""
from __future__ import annotations

import os
import re
from datetime import UTC, datetime, timedelta, timezone

import pandas as pd

MARCA_INICIAL = datetime(1970, 1, 1, tzinfo=UTC)

# Tablas consolidadas y de contexto de §8.2 que se pueden leer (nunca escribir).
TABLAS_PERMITIDAS = (
    "timbradas_consolidado", "timbradas_consolidado_zonas", "timbradas_anio", "timbradas_anio_zonas",
    "timbradas_segmentos_consolidado", "timbradas_segmentos_anio", "rutas", "procesos", "estacionalidades",
    "estacionalidades_anio", "novedades_viales", "novedades_viales_fecha", "novedades_viales_ruta",
)
# Tablas sin ultima_actualizacion: se leen completas (catálogos pequeños).
TABLAS_SIN_MARCA = ("rutas", "procesos", "estacionalidades", "estacionalidades_anio", "novedades_viales",
                    "novedades_viales_fecha", "novedades_viales_ruta")

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
        m = m.tz_localize("America/Bogota")
    return m.to_pydatetime()


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


class FuenteParquet:
    """Fuente offline por defecto: demanda horaria del proyecto (datos/demanda_horaria.parquet)."""

    nombre = "parquet"

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
            ua = ua.dt.tz_localize("America/Bogota")
        d = d[(ua > pd.Timestamp(marca)).values].copy()
        if len(d):
            d = d.sort_values(["ultima_actualizacion", "ruta", "fecha", "hora"]).reset_index(drop=True)
            nueva = pd.Timestamp(d["ultima_actualizacion"].max()).to_pydatetime()
        else:
            nueva = marca
        return d, nueva


class FuentePostgresSoloLectura:
    """Lectura incremental de las tablas consolidadas existentes con un usuario SELECT (nunca escribe)."""

    nombre = "postgres"

    def __init__(self, url=None, tabla="timbradas_consolidado", statement_timeout_ms=None, motor=None, limite=500000):
        self.url = url or os.environ.get("FUENTE_DATABASE_URL", "")
        if not self.url and motor is None:
            raise ValueError("FUENTE_DATABASE_URL no está definida: la fuente PostgreSQL necesita una URL de solo lectura.")
        if tabla not in TABLAS_PERMITIDAS:
            raise OperacionNoPermitida(f"Tabla no permitida: {tabla!r}.")
        self.tabla = tabla
        self.statement_timeout_ms = int(statement_timeout_ms or os.environ.get("FUENTE_STATEMENT_TIMEOUT_MS") or 30000)
        if self.statement_timeout_ms <= 0:
            raise ValueError("FUENTE_STATEMENT_TIMEOUT_MS debe ser > 0 (0 desactivaría el límite de tiempo).")
        self.limite = int(limite)
        self._motor = motor

    def _engine(self):
        if self._motor is None:
            from sqlalchemy import create_engine
            self._motor = create_engine(self.url, pool_pre_ping=True, pool_size=2, max_overflow=0)
        return self._motor

    def consultar(self, sql, parametros=None):
        """Ejecuta un único SELECT (texto o sqlalchemy Select) en una transacción READ ONLY con statement_timeout y
        devuelve un DataFrame. Todo lo que no sea SELECT se rechaza antes de abrir la conexión."""
        from sqlalchemy import text
        from sqlalchemy.sql import Select

        if isinstance(sql, Select):
            validar_solo_select(str(sql))                 # defensa adicional sobre la sentencia compilada
            sentencia = sql
        else:
            validar_solo_select(sql)
            sentencia = text(sql)
        timeout = int(self.statement_timeout_ms)          # entero validado: no hay texto del usuario en el SET
        with self._engine().connect() as conn:
            try:
                conn.execute(text("SET TRANSACTION READ ONLY"))
                conn.execute(text(f"SET LOCAL statement_timeout = {timeout}"))
                filas = conn.execute(sentencia, parametros or {}).mappings().all()
            finally:
                conn.rollback()                           # solo lectura: nunca se confirma nada
        return pd.DataFrame([dict(f) for f in filas])

    def consulta_incremental(self, con_hasta=False):
        """SELECT * de la tabla (lista blanca) con ultima_actualizacion > :marca (y < :hasta), ordenado y limitado.
        Se construye con SQLAlchemy Core: el nombre de la tabla viene de TABLAS_PERMITIDAS y los valores van siempre
        como parámetros enlazados (sin concatenar texto)."""
        import sqlalchemy as sa

        if self.tabla not in TABLAS_PERMITIDAS:
            raise OperacionNoPermitida(f"Tabla no permitida: {self.tabla!r}.")
        t = sa.table(self.tabla, sa.column("ultima_actualizacion"))
        q = sa.select(sa.literal_column("*")).select_from(t)
        if self.tabla in TABLAS_SIN_MARCA:
            return q.limit(self.limite)
        q = q.where(t.c.ultima_actualizacion > sa.bindparam("marca"))
        if con_hasta:
            q = q.where(t.c.ultima_actualizacion < sa.bindparam("hasta"))
        return q.order_by(t.c.ultima_actualizacion).limit(self.limite)

    def leer_incremental(self, marca_agua=None, hasta=None):
        marca = _normalizar_marca(marca_agua)
        params = {"marca": marca}
        if hasta is not None:
            h = hasta.date() if isinstance(hasta, datetime) else hasta
            params["hasta"] = datetime.combine(h + timedelta(days=1), datetime.min.time()).replace(
                tzinfo=timezone(timedelta(hours=-5)))   # fin del día en America/Bogota (UTC-5, sin horario de verano)
        sql = self.consulta_incremental(con_hasta=hasta is not None)
        if self.tabla in TABLAS_SIN_MARCA:
            params = {}
        d = self.consultar(sql, params)
        if len(d) and "ultima_actualizacion" in d.columns:
            nueva = pd.Timestamp(pd.to_datetime(d["ultima_actualizacion"]).max()).to_pydatetime()
        else:
            nueva = marca
        return d, nueva


def fuente_desde_entorno(env=None):
    """FUENTE=parquet (por defecto) o FUENTE=postgres (requiere FUENTE_DATABASE_URL)."""
    env = os.environ if env is None else env
    tipo = (env.get("FUENTE") or "parquet").strip().lower()
    if tipo == "postgres":
        return FuentePostgresSoloLectura(url=env.get("FUENTE_DATABASE_URL") or None,
                                         statement_timeout_ms=env.get("FUENTE_STATEMENT_TIMEOUT_MS") or None)
    if tipo != "parquet":
        raise ValueError(f"FUENTE desconocida: {tipo!r} (use parquet o postgres).")
    return FuenteParquet()


__all__ = ["FuenteParquet", "FuentePostgresSoloLectura", "OperacionNoPermitida", "validar_solo_select",
           "fuente_desde_entorno", "TABLAS_PERMITIDAS", "MARCA_INICIAL"]
