"""Catálogos operacionales de solo lectura y ajuste local de capacidad (§3.1 «Gestión operacional», §3.2, §6.1,
§8.1-§8.3, RF-014, RF-016, RF-017).

Fuentes, en este orden:
1. Réplica o base operacional con un usuario SELECT (CATALOGOS_DATABASE_URL o, si falta, FUENTE_DATABASE_URL). Cada
   consulta pasa por ``app.servicios.fuentes.FuentePostgresSoloLectura.consultar``: ``validar_solo_select`` antes de
   conectar, ``SET TRANSACTION READ ONLY``, ``SET LOCAL statement_timeout``, ROLLBACK y circuit breaker. Este módulo
   no escribe nunca en las tablas de Extreme ni crea objetos en su esquema.
2. Archivos offline, si no hay réplica configurada: las exportaciones Parquet del reto (CATALOGOS_DATOS_DIR, o
   REPLICA_DATOS_DIR, o la carpeta datos/ del proyecto), el catálogo empaquetado de la API (datos/catalogo_rutas.json y
   parametros_operativos_hora.parquet) y el reporte de flota sin datos personales (insumos_sobusa/flota_sobusa.csv).
CATALOGOS_FUENTE=auto (por omisión), replica o archivos fuerza una de las dos.

Datos personales (§18, minimización): no salen nunca la placa, el conductor, el propietario, los contactos, el módem,
la póliza ni la posición GPS. La placa solo se usa en memoria para cruzar la clase del vehículo con el reporte de flota.
La única excepción es el seudónimo del conductor (HMAC, nunca el identificador) de los viajes de una alerta
(viajes_para_alertas, §5.3).

Fechas (§8.1, §12.1): los ``timestamp`` sin zona de las tablas operacionales son hora local de Barranquilla; todo
instante que sale de aquí lleva la zona America/Bogota (-05:00).

Ajuste local (§3.2, §8.3): la capacidad operativa por ruta y tipología vive SOLO en ai_frecuencias, como parámetros
gobernados del conjunto versionado ``threshold_config`` (prefijo ``capacidad_override.``). Cada cambio crea una versión
nueva del conjunto con creado_por, motivo y creado_en; la versión queda en ``umbrales_version`` de cada recomendación.
``capacidad_vigente(ruta)`` es el contrato que puede llamar el optimizador. La flota disponible y el tiempo de ciclo
se ajustan igual (app/servicios/flota_ciclo.py): ``versionar_ajustes`` y ``eventos_ajustes`` son comunes a los dos.
"""
from __future__ import annotations

import json
import logging
import math
import os
import re
import threading
import time
from collections.abc import Callable
from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

ZONA = ZoneInfo("America/Bogota")
RAIZ = Path(__file__).resolve().parents[2]
log = logging.getLogger("api_frecuencias.catalogos")

PREFIJO_CAPACIDAD = "capacidad_override"
TIPOLOGIA_TODAS = "TODAS"
CAPACIDAD_MIN, CAPACIDAD_MAX = 1, 200
TOLERANCIA_SIMPLIFICACION = 1e-5      # grados (unos 1,1 m): geometría liviana para el tablero
_RE_TIPOLOGIA = re.compile(r"^[A-Z0-9_-]{1,32}$")
LIMITE_EXPORTACION = 100_000

# Columnas que nunca salen de este módulo (personas, secretos, posición en vivo).
COLUMNAS_PROHIBIDAS = frozenset({
    "placa", "idconductor", "idconductor_actual", "idpropietario", "idcontacto", "tel_emergencia", "poliza",
    "aseguradora", "modem_user", "modem_passwd", "modem_puk", "modem_imei", "modem_min", "modem_user_2",
    "modem_passwd_2", "modem_puk_2", "latitud", "longitud", "xpos", "ypos", "usuario", "iddespachador",
    "url_interfaz_despacho", "usuario_interfaz_despacho", "clave_interfaz_despacho", "observacion",
})

COLUMNAS = {
    "procesos": ["proceso", "nombre", "estado", "toleranciatiempo", "multaatraso", "multaadelanto", "penaliza",
                 "maneja_capac_veh", "maneja_hora_pico", "id_estacionalidad", "ultima_estacionalidad", "rutas"],
    "empresas": ["idempresa", "proceso", "proceso_nombre", "rutas", "idrutas"],
    "rutas": ["idruta", "ruta", "codigo", "nombre", "proceso", "idempresa", "estado_ruta", "frecuenciadespachos",
              "frecuenciadespachos_min", "primerdespacho", "tolsalida", "tolerancia", "tiempoplazosalida",
              "distancia_global", "tiempo_global", "flotadisp_prog", "capacidad", "cap_min_autorizada",
              "cap_max_autorizada", "capacidad_vigente", "capacidad_fuente", "tiempo_ciclo_min", "flota",
              "frecuencia_actual_min", "por_tipo_dia"],
    "segmentos": ["id", "id_config", "idruta", "ruta", "idrutageo", "nro_segmento", "activo", "longitud_m",
                  "vertices_original", "vertices", "geometria"],
    "vehiculos": ["idvehiculo", "idruta", "ruta", "tipologia", "tipovehiculo", "carroceria", "marca", "modelo",
                  "n_sentados", "n_depie", "capacidad_total", "activo", "despacho_habilitado"],
    "viajes": ["idprogramacion", "idruta", "ruta", "idvehiculo", "fecha", "hora_programada", "registrado_en",
               "estado", "cancelada", "finalizado"],
    "despachos": ["idprogramacion", "idruta", "ruta", "idvehiculo", "fecha", "hora_programada", "salida_real",
                  "llegada", "retraso_min", "duracion_min", "pasajeros", "finalizado"],
}
ORDEN_POR_DEFECTO = {"procesos": "proceso", "empresas": "idempresa", "rutas": "idruta", "segmentos": "id",
                     "vehiculos": "idvehiculo", "viajes": "hora_programada", "despachos": "salida_real"}
ORDENABLES = {
    "procesos": ("proceso", "nombre"),
    "empresas": ("idempresa", "proceso", "rutas"),
    "rutas": ("idruta", "ruta", "codigo", "frecuenciadespachos_min", "tiempo_ciclo_min", "flota"),
    "segmentos": ("id", "idruta", "id_config", "nro_segmento", "longitud_m"),
    "vehiculos": ("idvehiculo", "idruta", "tipologia", "capacidad_total", "n_sentados", "n_depie", "modelo"),
    "viajes": ("hora_programada", "idprogramacion", "idruta", "idvehiculo", "registrado_en"),
    "despachos": ("salida_real", "hora_programada", "idprogramacion", "idruta", "idvehiculo", "retraso_min"),
}


class CatalogoNoDisponible(RuntimeError):
    """La fuente configurada no tiene este catálogo (por ejemplo, sin réplica ni exportaciones en la imagen)."""


class FiltroInvalido(ValueError):
    """Filtro u orden fuera de la lista blanca del catálogo."""


# ---------------------------------------------------------------- fechas (§8.1)
def a_bogota(valor: Any) -> datetime | None:
    """Instante con zona America/Bogota. Sin zona se interpreta como hora local (las tablas operacionales guardan
    ``timestamp`` local); con zona se convierte. None, NaT o vacío -> None."""
    if valor is None or valor is pd.NaT or (isinstance(valor, float) and math.isnan(valor)):
        return None
    if isinstance(valor, str):
        if not valor.strip():
            return None
        valor = pd.Timestamp(valor)
    if isinstance(valor, pd.Timestamp):
        if pd.isna(valor):
            return None
        valor = valor.to_pydatetime()
    if not isinstance(valor, datetime):
        if isinstance(valor, date):
            return datetime(valor.year, valor.month, valor.day, tzinfo=ZONA)
        return None
    return valor.replace(tzinfo=ZONA) if valor.tzinfo is None else valor.astimezone(ZONA)


def _limpio(v: Any) -> Any:
    """Valor de pandas/numpy -> tipo de Python serializable (NaN -> None)."""
    if v is None:
        return None
    if isinstance(v, (pd.Timestamp, datetime)):
        return a_bogota(v)
    if isinstance(v, np.generic):
        v = v.item()
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    if v is pd.NaT or (not isinstance(v, (str, list, dict, tuple)) and pd.isna(v) is True):
        return None
    return v


def registros(df: pd.DataFrame, columnas: list[str]) -> list[dict]:
    """Filas del catálogo como dicts con el contrato de columnas (faltantes -> None, nunca columnas prohibidas)."""
    salida = []
    cols = [c for c in columnas if c not in COLUMNAS_PROHIBIDAS]
    for fila in df.to_dict("records"):
        salida.append({c: _limpio(fila.get(c)) for c in cols})
    return salida


# ---------------------------------------------------------------- configuración de la fuente
def _env(nombre: str, defecto: str = "") -> str:
    """Variable de entorno o, si falta, el mismo ajuste de app.config (que también lee el .env)."""
    valor = os.environ.get(nombre)
    if not valor and nombre.startswith("CATALOGOS_"):
        from app.config import obtener_ajustes

        valor = getattr(obtener_ajustes(), nombre.lower(), "")
    return (str(valor) if valor not in (None, "") else defecto).strip()


def url_replica() -> str:
    """URL de solo lectura de la réplica/base operacional (vacía si no hay). Nunca se escribe en logs."""
    url = _env("CATALOGOS_DATABASE_URL")
    if not url:
        from app.config import obtener_ajustes

        url = (obtener_ajustes().fuente_database_url or "").strip()
    return url


def modo() -> str:
    """replica | archivos según CATALOGOS_FUENTE (auto: réplica si hay URL configurada)."""
    pedido = _env("CATALOGOS_FUENTE", "auto").lower()
    if pedido not in ("auto", "replica", "archivos"):
        raise ValueError(f"CATALOGOS_FUENTE desconocida: {pedido!r} (use auto, replica o archivos)")
    if pedido == "auto":
        return "replica" if url_replica() else "archivos"
    return pedido


def carpeta_exportaciones() -> Path:
    valor = _env("CATALOGOS_DATOS_DIR") or _env("REPLICA_DATOS_DIR")
    return Path(valor) if valor else RAIZ.parents[1] / "datos"


def archivo_flota() -> Path:
    valor = _env("CATALOGOS_FLOTA_CSV")
    return Path(valor) if valor else RAIZ.parents[1] / "insumos_sobusa" / "flota_sobusa.csv"


# ---------------------------------------------------------------- catálogo empaquetado de la API (siempre está)
def rutas_api() -> list[dict]:
    from app.servicios import datos

    return datos.catalogo_rutas()


def _nombre_ruta(idruta: Any) -> str | None:
    for r in rutas_api():
        if str(r.get("idruta")) == str(idruta):
            return r["ruta"]
    return None


def ruta_info(ruta: Any) -> dict:
    """Ruta del catálogo por nombre (SILENCIO) o por idruta (2). KeyError si no existe."""
    for r in rutas_api():
        if r["ruta"] == str(ruta) or str(r["idruta"]) == str(ruta):
            return r
    raise KeyError(f"Ruta desconocida: {ruta!r}. Rutas válidas: {[r['ruta'] for r in rutas_api()]}")


def _minutos(valor: Any) -> float | None:
    try:
        f = float(str(valor).strip().replace(",", "."))
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None


def _texto(valor: Any) -> str | None:
    """Columna de texto de la tabla rutas (varchar en Extreme). El catálogo empaquetado la trae como número:
    41 -> "41" (y 41.0 -> "41"), para que la respuesta cumpla el mismo contrato con cualquier fuente."""
    v = _limpio(valor)
    if v is None:
        return None
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v)


# ---------------------------------------------------------------- fuente: réplica (solo lectura)
_motores: dict[str, Any] = {}
_bloqueo = threading.Lock()
_cache: dict[tuple, tuple[float, pd.DataFrame]] = {}


def _ttl() -> float:
    try:
        return float(_env("CATALOGOS_CACHE_S", "300"))
    except ValueError:
        return 300.0


def _url_psycopg(url: str) -> str:
    return url.replace("postgresql://", "postgresql+psycopg://", 1) if url.startswith("postgresql://") else url


class FuenteReplica:
    """SELECT de solo lectura sobre la réplica con la guarda de app.servicios.fuentes (READ ONLY, timeout, breaker)."""

    nombre = "replica"

    def __init__(self, url: str | None = None, motor=None):
        from app.servicios.fuentes import FuentePostgresSoloLectura

        url = url or url_replica()
        if motor is None:
            if not url:
                raise CatalogoNoDisponible("No hay réplica configurada (CATALOGOS_DATABASE_URL o FUENTE_DATABASE_URL)")
            motor = self._motor(url)
        self._id_motor = id(motor)                       # la caché distingue réplicas distintas
        self._lector = FuentePostgresSoloLectura(url=url or "inyectado", motor=motor)

    @staticmethod
    def _motor(url: str):
        with _bloqueo:
            if url not in _motores:
                from sqlalchemy import create_engine

                _motores[url] = create_engine(_url_psycopg(url), pool_pre_ping=True, pool_size=2, max_overflow=2,
                                              connect_args={"options": "-c timezone=America/Bogota",
                                                            "connect_timeout": 5})
            return _motores[url]

    def consultar(self, sql: str, parametros: dict | None = None) -> pd.DataFrame:
        return self._lector.consultar(sql, parametros or {})

    def consultar_cacheado(self, clave: tuple, sql: str, parametros: dict | None = None) -> pd.DataFrame:
        clave = (self._id_motor, *clave)
        ahora = time.monotonic()
        guardado = _cache.get(clave)
        if guardado and ahora - guardado[0] < _ttl():
            return guardado[1].copy()
        d = self.consultar(sql, parametros)
        _cache[clave] = (ahora, d)
        return d.copy()

    def viajes(self, ruta: Any, desde: datetime, hasta: datetime) -> pd.DataFrame:
        """Los viajes de una ruta y una ventana con el SELECT de la lista blanca de fuentes.py (sin conteo de segmentos)
        y el conductor seudonimizado (§5.3, §18)."""
        return self._lector.viajes(ruta, desde, hasta, con_segmentos=False)

    def columnas(self, tabla: str) -> set[str]:
        d = self.consultar_cacheado(
            ("columnas", tabla),
            "SELECT column_name FROM information_schema.columns WHERE table_schema = 'public' AND table_name = :t",
            {"t": tabla})
        return set(d["column_name"]) if len(d) else set()


def limpiar_cache() -> None:
    _cache.clear()
    _geometrias.clear()
    _leer_parquet.cache_clear()
    _progvehiculos_archivo.cache_clear()
    _segmentos_archivo.cache_clear()
    _flota_csv.cache_clear()


# ---------------------------------------------------------------- fuente: archivos offline
def _archivo(nombre: str) -> Path:
    return carpeta_exportaciones() / nombre


def _mtime(p: Path) -> float:
    return p.stat().st_mtime if p.exists() else -1.0


@lru_cache(maxsize=16)
def _leer_parquet(ruta: str, columnas: tuple[str, ...], mtime: float) -> pd.DataFrame:
    import pyarrow.parquet as pq

    disponibles = set(pq.ParquetFile(ruta).schema_arrow.names)
    return pq.read_table(ruta, columns=[c for c in columnas if c in disponibles]).to_pandas()


def _parquet(nombre: str, columnas: tuple[str, ...]) -> pd.DataFrame:
    p = _archivo(nombre)
    if not p.exists():
        raise CatalogoNoDisponible(f"Sin réplica y sin la exportación {nombre} en {carpeta_exportaciones().name}/ "
                                   "(defina CATALOGOS_DATABASE_URL o CATALOGOS_DATOS_DIR)")
    return _leer_parquet(str(p), columnas, _mtime(p)).copy()


@lru_cache(maxsize=1)
def _flota_csv(ruta: str, mtime: float) -> pd.DataFrame | None:
    if mtime < 0:
        return None
    f = pd.read_csv(ruta, dtype=str)
    return f


def _clase_por_placa() -> dict[str, tuple[str | None, str | None]]:
    """placa -> (clase, carrocería) del reporte de flota (la placa no sale de esta función)."""
    p = archivo_flota()
    f = _flota_csv(str(p), _mtime(p))
    if f is None or "Placa" not in f.columns:
        return {}
    f = f.dropna(subset=["Placa"]).drop_duplicates("Placa")
    return {str(r["Placa"]).strip().upper(): (r.get("Clase") or None, r.get("Carrocería") or None)
            for _, r in f.iterrows()}


# ---------------------------------------------------------------- geometría (GeoJSON, sin dependencias externas)
def _douglas_peucker(puntos: np.ndarray, tolerancia: float) -> np.ndarray:
    """Simplificación de Douglas-Peucker iterativa (conserva extremos)."""
    n = len(puntos)
    if n <= 2 or tolerancia <= 0:
        return puntos
    conservar = np.zeros(n, dtype=bool)
    conservar[0] = conservar[-1] = True
    pila = [(0, n - 1)]
    while pila:
        i, j = pila.pop()
        if j <= i + 1:
            continue
        a, b = puntos[i], puntos[j]
        tramo = puntos[i + 1:j]
        ab = b - a
        largo = float(np.hypot(*ab))
        if largo == 0:
            dist = np.hypot(*(tramo - a).T)
        else:
            dist = np.abs(ab[0] * (tramo[:, 1] - a[1]) - ab[1] * (tramo[:, 0] - a[0])) / largo
        k = int(np.argmax(dist))
        if dist[k] > tolerancia:
            m = i + 1 + k
            conservar[m] = True
            pila.extend(((i, m), (m, j)))
    return puntos[conservar]


def wkt_a_geojson(wkt: str | None, tolerancia: float | None = TOLERANCIA_SIMPLIFICACION) -> tuple[dict | None, int]:
    """LINESTRING WKT -> (GeoJSON LineString, vértices originales). Otra geometría o vacío -> (None, 0)."""
    if not wkt or not isinstance(wkt, str):
        return None, 0
    texto = wkt.strip()
    if not texto.upper().startswith("LINESTRING") or "(" not in texto:
        return None, 0
    interior = texto[texto.index("(") + 1:texto.rindex(")")]
    valores = np.array(interior.replace(",", " ").split(), dtype=float)
    if valores.size < 4 or valores.size % 2:
        return None, 0
    puntos = valores.reshape(-1, 2)
    original = len(puntos)
    if tolerancia:
        puntos = _douglas_peucker(puntos, tolerancia)
    return {"type": "LineString", "coordinates": np.round(puntos, 7).tolist()}, original


def _vertices_wkt(wkt: str | None) -> int:
    """Vértices de una LINESTRING WKT sin convertirla (cuenta las comas): 0 si no es una línea."""
    if not wkt or not isinstance(wkt, str) or not wkt.lstrip().upper().startswith("LINESTRING") or "(" not in wkt:
        return 0
    return wkt.count(",", wkt.index("(")) + 1


@lru_cache(maxsize=2)
def _segmentos_archivo(ruta: str, mtime: float, tolerancia: float | None) -> pd.DataFrame:
    """Segmentos del Parquet exportado con la geometría ya simplificada (la WKT completa pesa unos 95 kB por
    segmento: se lee por lotes y no se guarda). tolerancia=None: sin geometría, solo el número de vértices (lo que
    piden geometria=ninguna y geometria=completa, que después trae la completa solo de los segmentos de la página)."""
    import pyarrow.parquet as pq

    filas = []
    archivo = pq.ParquetFile(ruta)
    cols = [c for c in ("id", "id_config", "idruta", "idrutageo", "nro_segmento", "activo", "longitud_m",
                        "geom_segmento") if c in archivo.schema_arrow.names]
    for lote in archivo.iter_batches(batch_size=256, columns=cols):
        d = lote.to_pandas()
        for r in d.to_dict("records"):
            wkt = r.pop("geom_segmento", None)
            if tolerancia is None:
                geo, n = None, _vertices_wkt(wkt)
            else:
                geo, n = wkt_a_geojson(wkt, tolerancia)
            r["geometria"], r["vertices_original"] = geo, n
            r["vertices"] = len(geo["coordinates"]) if geo else 0
            filas.append(r)
    return pd.DataFrame(filas)


# ---------------------------------------------------------------- lectores por catálogo
def _fuente(fuente=None):
    if fuente is not None:
        return fuente
    return FuenteReplica() if modo() == "replica" else None


def procesos(fuente=None) -> tuple[pd.DataFrame, str]:
    f = _fuente(fuente)
    cols = ("proceso", "nombre", "estado", "toleranciatiempo", "multaatraso", "multaadelanto", "penaliza",
            "maneja_capac_veh", "maneja_hora_pico", "id_estacionalidad", "ultima_estacionalidad")
    if f is not None:
        d = f.consultar_cacheado(("procesos",), 'SELECT proceso, nombre, estado, toleranciatiempo, multaatraso, '
                                 'multaadelanto, penaliza, maneja_capac_veh, maneja_hora_pico, id_estacionalidad, '
                                 'ultima_estacionalidad FROM "Procesos"')
        r, _ = rutas_tabla(f)
        nombre = f.nombre
    else:
        d = _parquet("Procesos.parquet", cols)
        r, _ = rutas_tabla(None)
        nombre = "archivos"
    conteo = r.groupby("proceso").size() if len(r) and "proceso" in r.columns else pd.Series(dtype=int)
    d["rutas"] = d["proceso"].map(conteo).fillna(0).astype(int)
    return d, nombre


SQL_RUTAS = ("SELECT r.idruta, r.codigo, r.nombre, r.proceso, r.idempresa, r.estado_ruta, r.frecuenciadespachos, "
             "r.primerdespacho, r.tolsalida, r.tolerancia, r.tiempoplazosalida, r.distancia_global, r.tiempo_global, "
             "r.flotadisp_prog, to_jsonb(r) ->> 'capacidad' AS capacidad, "
             "to_jsonb(r) ->> 'cap_min_autorizada' AS cap_min_autorizada, "
             "to_jsonb(r) ->> 'cap_max_autorizada' AS cap_max_autorizada FROM rutas r ORDER BY r.idruta")


def rutas_tabla(fuente=None) -> tuple[pd.DataFrame, str]:
    """Tabla rutas (sin geometría): columnas de despacho y, si existen, capacidad, cap_min/cap_max autorizadas."""
    deseadas = ("idruta", "codigo", "nombre", "proceso", "idempresa", "estado_ruta", "frecuenciadespachos",
                "primerdespacho", "tolsalida", "tolerancia", "tiempoplazosalida", "distancia_global", "tiempo_global",
                "flotadisp_prog", "capacidad", "cap_min_autorizada", "cap_max_autorizada")
    f = _fuente(fuente)
    if f is not None:
        # SQL fijo: las columnas opcionales de §6.1 (capacidad, cap_min/cap_max_autorizada) se leen con to_jsonb y
        # valen NULL si la tabla no las tiene, sin construir texto SQL con nombres de columna.
        d = f.consultar_cacheado(("rutas",), SQL_RUTAS)
        for c in ("capacidad", "cap_min_autorizada", "cap_max_autorizada"):
            if c in d.columns:
                d[c] = pd.to_numeric(d[c], errors="coerce")
        return d, f.nombre
    try:
        return _parquet("rutas.parquet", deseadas), "archivos"
    except CatalogoNoDisponible:
        # imagen sin exportaciones: lo mínimo del catálogo empaquetado de la API
        d = pd.DataFrame([{"idruta": r["idruta"], "codigo": r.get("codigo"),
                           "frecuenciadespachos": r.get("frecuenciadespachos_tabla_rutas"),
                           "primerdespacho": r.get("primer_despacho"),
                           "flotadisp_prog": r.get("flota_programada_tabla_rutas")} for r in rutas_api()])
        return d, "archivos_api"


def rutas(fuente=None, umbrales: dict | None = None) -> tuple[pd.DataFrame, str]:
    """Rutas del reto: tabla rutas + parámetros operativos (ciclo, flota, intervalo) + capacidad vigente."""
    tabla, nombre = rutas_tabla(fuente)
    api = {int(r["idruta"]): r for r in rutas_api()}
    tabla = tabla[pd.to_numeric(tabla["idruta"], errors="coerce").isin(list(api))].copy()
    tabla["idruta"] = tabla["idruta"].astype(int)
    filas = []
    for t in tabla.to_dict("records"):
        r = api[t["idruta"]]
        cv = capacidad_vigente(t["idruta"], umbrales=umbrales or {})    # sin umbrales: solo el catálogo
        filas.append({**t, "ruta": r["ruta"],
                      "codigo": _texto(t.get("codigo")) or r.get("codigo"),
                      "primerdespacho": _texto(t.get("primerdespacho")),
                      "frecuenciadespachos": _texto(t.get("frecuenciadespachos")),
                      "flotadisp_prog": _texto(t.get("flotadisp_prog")),
                      "frecuenciadespachos_min": _minutos(t.get("frecuenciadespachos")),
                      "capacidad": _limpio(t.get("capacidad")) or r.get("capacidad"),
                      "cap_min_autorizada": _limpio(t.get("cap_min_autorizada")),
                      "cap_max_autorizada": _limpio(t.get("cap_max_autorizada")),
                      "capacidad_vigente": cv["capacidad"], "capacidad_fuente": cv["fuente"],
                      "tiempo_ciclo_min": r.get("tiempo_ciclo_min"), "flota": r.get("flota"),
                      "frecuencia_actual_min": r.get("frecuencia_actual_min"),
                      "por_tipo_dia": r.get("por_tipo_dia") or {}})
    return pd.DataFrame(filas, columns=COLUMNAS["rutas"]), nombre


def parametros_por_hora(idruta: int) -> list[dict]:
    """Ciclo, flota, intervalo programado y nmin/nmax por tipo de día y hora (datos/parametros_operativos_hora)."""
    from app.servicios import datos

    nombre = _nombre_ruta(idruta)
    if nombre is None:
        return []
    p = datos.parametros_operativos(ruta=nombre)
    return registros(p, ["tipo_dia", "hora", "tiempo_ciclo_min", "flota", "intervalo_programado_min", "capacidad",
                         "nmin", "nmax"])


def empresas(fuente=None) -> tuple[pd.DataFrame, str]:
    """Empresa = idempresa de la tabla rutas dentro de su proceso ("Procesos" es la raíz de las relaciones)."""
    r, nombre = rutas_tabla(fuente)
    if "idempresa" not in r.columns or "proceso" not in r.columns:
        raise CatalogoNoDisponible("Sin réplica y sin la exportación rutas.parquet con idempresa y proceso: el "
                                   "catálogo empaquetado de la API no los trae (defina CATALOGOS_DATABASE_URL o "
                                   "CATALOGOS_DATOS_DIR)")
    p, _ = procesos(fuente)
    nombres = dict(zip(p["proceso"], p["nombre"], strict=False))
    filas = []
    for (idempresa, proceso), g in r.groupby(["idempresa", "proceso"], dropna=False):
        filas.append({"idempresa": _limpio(idempresa), "proceso": _limpio(proceso),
                      "proceso_nombre": nombres.get(proceso), "rutas": len(g),
                      "idrutas": sorted(int(x) for x in g["idruta"].dropna())})
    return pd.DataFrame(filas, columns=COLUMNAS["empresas"]), nombre


_SEGMENTOS_BASE = ("SELECT id, id_config, idruta, idrutageo, nro_segmento, activo, longitud_m, "
                   "ST_NPoints(geom_segmento) AS vertices_original")
_SEGMENTOS_FILTRO = " FROM rutas_segmentos WHERE (CAST(:idruta AS bigint) IS NULL OR idruta = CAST(:idruta AS bigint))"
SQL_SEGMENTOS_SIN_GEOMETRIA = _SEGMENTOS_BASE + _SEGMENTOS_FILTRO
SQL_SEGMENTOS_SIMPLIFICADOS = (_SEGMENTOS_BASE + ", ST_AsGeoJSON(ST_SimplifyPreserveTopology(geom_segmento, "
                               "CAST(:tol AS double precision)), 7) AS geojson" + _SEGMENTOS_FILTRO)


def segmentos(fuente=None, geometria: str = "simplificada", idruta: int | None = None) -> tuple[pd.DataFrame, str]:
    """rutas_segmentos con su longitud y la geometría como GeoJSON (simplificada, completa o ninguna). En la réplica
    el filtro por idruta va en el SQL (la simplificación con PostGIS se hace solo sobre esa ruta)."""
    tol = {"simplificada": TOLERANCIA_SIMPLIFICACION, "completa": 0.0, "ninguna": None}
    if geometria not in tol:
        raise FiltroInvalido("geometria debe ser simplificada, completa o ninguna")
    if geometria == "completa":                 # la completa se pide por página con geometria_completa(ids)
        geometria = "ninguna"
    f = _fuente(fuente)
    if f is not None:
        d, nombre = _segmentos_replica(f, geometria, idruta), f.nombre
    else:
        d, nombre = _segmentos_exportacion(geometria), "archivos"
    if geometria == "ninguna":
        d["geometria"], d["vertices"] = None, 0
    d["longitud_m"] = pd.to_numeric(d["longitud_m"], errors="coerce").astype(float)
    d["ruta"] = d["idruta"].map(_nombre_ruta)
    return d, nombre


def _segmentos_replica(f, geometria: str, idruta: int | None) -> pd.DataFrame:
    """SQL fijo; sin idruta, :idruta va NULL (CAST explícito para que PostgreSQL conozca el tipo). La simplificación
    la hace PostGIS (ST_SimplifyPreserveTopology) solo si se pide geometría."""
    params = {"idruta": None if idruta is None else int(idruta)}
    if geometria == "ninguna":
        return f.consultar_cacheado(("segmentos", geometria, idruta), SQL_SEGMENTOS_SIN_GEOMETRIA, params)
    params["tol"] = TOLERANCIA_SIMPLIFICACION
    d = f.consultar_cacheado(("segmentos", geometria, idruta), SQL_SEGMENTOS_SIMPLIFICADOS, params)
    d["geometria"] = [json.loads(g) if isinstance(g, str) else g for g in d.pop("geojson")] if len(d) else []
    d["vertices"] = [len(g["coordinates"]) if isinstance(g, dict) else 0 for g in d["geometria"]]
    return d


def _archivo_segmentos() -> Path:
    """rutas_segmentos.parquet de las exportaciones; sin él (ni réplica), el catálogo no está disponible."""
    p = _archivo("rutas_segmentos.parquet")
    if not p.exists():
        raise CatalogoNoDisponible("Sin réplica y sin la exportación rutas_segmentos.parquet "
                                   "(defina CATALOGOS_DATABASE_URL o CATALOGOS_DATOS_DIR)")
    return p


def _segmentos_exportacion(geometria: str) -> pd.DataFrame:
    """rutas_segmentos.parquet; sin geometría no se convierte ni se simplifica la WKT de los 2.695 segmentos (unos
    250 MB de texto): solo se cuentan sus vértices."""
    p = _archivo_segmentos()
    tolerancia = None if geometria == "ninguna" else TOLERANCIA_SIMPLIFICACION
    return _segmentos_archivo(str(p), _mtime(p), tolerancia).copy()


def _wkt_de(ids: list[int]) -> list[dict]:
    """[{id, geom_segmento}] de los segmentos pedidos, leídos del Parquet exportado (solo esas filas)."""
    import pyarrow.parquet as pq

    tabla = pq.read_table(str(_archivo_segmentos()), columns=["id", "geom_segmento"], filters=[("id", "in", ids)])
    return tabla.to_pandas().to_dict("records")


def geometria_completa(ids: list[int], fuente=None) -> dict[int, dict]:
    """GeoJSON sin simplificar SOLO de los segmentos pedidos (unos 95 kB cada uno): nunca de toda la tabla."""
    ids = [int(i) for i in ids][:500]
    if not ids:
        return {}
    f = _fuente(fuente)
    if f is not None:
        d = f.consultar("SELECT id, ST_AsGeoJSON(geom_segmento, 7) AS geojson FROM rutas_segmentos "
                        "WHERE id = ANY(:ids)", {"ids": ids})
        return {int(r["id"]): json.loads(r["geojson"]) for r in d.to_dict("records") if r.get("geojson")}
    return {int(r["id"]): g for r in _wkt_de(ids) if (g := wkt_a_geojson(r["geom_segmento"], 0)[0])}


# Listado paginado (RNF-002): el catálogo se filtra, ordena y pagina SIN geometría y la geometría (y los vértices de la
# original) se arma después solo para los segmentos de la página. Antes, la primera petición simplificaba las 2.695
# geometrías (unos 100 MB en la réplica) para devolver 50: 5,0 s en frío (docs/evidencias/pruebas/k6_volumen.txt).
COLUMNAS_LISTADO_SEGMENTOS = ("id", "id_config", "idruta", "idrutageo", "nro_segmento", "activo", "longitud_m")
SQL_SEGMENTOS_LISTADO = "SELECT " + ", ".join(COLUMNAS_LISTADO_SEGMENTOS) + _SEGMENTOS_FILTRO
SQL_GEOMETRIA_PAGINA = ("SELECT id, ST_NPoints(geom_segmento) AS vertices_original, "
                        "ST_AsGeoJSON(ST_SimplifyPreserveTopology(geom_segmento, CAST(:tol AS double precision)), 7) "
                        "AS geojson FROM rutas_segmentos WHERE id = ANY(:ids)")
SQL_VERTICES_PAGINA = ("SELECT id, ST_NPoints(geom_segmento) AS vertices_original FROM rutas_segmentos "
                       "WHERE id = ANY(:ids)")


def segmentos_listado(fuente=None, idruta: int | None = None) -> tuple[pd.DataFrame, str]:
    """rutas_segmentos sin geometría (id, configuración, ruta, número, activo y longitud) para filtrar y paginar."""
    f = _fuente(fuente)
    if f is not None:
        params = {"idruta": None if idruta is None else int(idruta)}
        d, nombre = f.consultar_cacheado(("segmentos_listado", idruta), SQL_SEGMENTOS_LISTADO, params), f.nombre
    else:
        _archivo_segmentos()
        d, nombre = _parquet("rutas_segmentos.parquet", COLUMNAS_LISTADO_SEGMENTOS), "archivos"
    d["longitud_m"] = pd.to_numeric(d["longitud_m"], errors="coerce").astype(float)
    d["ruta"] = d["idruta"].map(_nombre_ruta)
    return d, nombre


def _datos_geometria(geo: dict | None, vertices_original: Any) -> dict[str, Any]:
    return {"geometria": geo, "vertices": len(geo["coordinates"]) if geo else 0,
            "vertices_original": _limpio(vertices_original)}


def _pagina_replica(f, ids: list[int], geometria: str) -> dict[int, dict]:
    """Geometría de los segmentos pedidos, leída de la réplica (sin caché por página: la guarda _memorizadas)."""
    if geometria == "ninguna":
        d = f.consultar(SQL_VERTICES_PAGINA, {"ids": ids})
        return {int(r["id"]): _datos_geometria(None, r["vertices_original"]) for r in d.to_dict("records")}
    d = f.consultar(SQL_GEOMETRIA_PAGINA, {"ids": ids, "tol": TOLERANCIA_SIMPLIFICACION})
    return {int(r["id"]): _datos_geometria(json.loads(r["geojson"]) if isinstance(r.get("geojson"), str) else None,
                                           r["vertices_original"]) for r in d.to_dict("records")}


# Geometría ya armada, POR SEGMENTO (RNF-002): cada página pide a la fuente solo los segmentos que no tiene guardados.
# La memoria queda acotada por el número de segmentos (2.695 en Sobusa) por modo, no por las combinaciones de página,
# orden y filtros: una caché por página crecía sin límite (cada desplazamiento distinto era una entrada nueva que nunca
# se borraba). De la réplica, cada segmento vale CATALOGOS_CACHE_S segundos; del Parquet, mientras el archivo no
# cambie (su fecha de modificación va en la llave). limpiar_cache() la vacía.
_geometrias: dict[tuple, tuple[float, dict]] = {}


def _memorizadas(origen: tuple, geometria: str, ids: list[int], leer, ttl: float | None) -> dict[int, dict]:
    """{id: datos} de los ids pedidos: los vigentes de la memoria y los demás con leer(faltantes)."""
    ahora = time.monotonic()
    salida: dict[int, dict] = {}
    for i in ids:
        guardada = _geometrias.get((origen, geometria, i))
        if guardada is not None and (ttl is None or ahora - guardada[0] < ttl):
            salida[i] = guardada[1]
    faltantes = [i for i in ids if i not in salida]
    if faltantes:
        for i, datos in leer(faltantes).items():
            _geometrias[(origen, geometria, i)] = (ahora, datos)
            salida[i] = datos
    return {i: dict(salida[i]) for i in ids if i in salida}


def _pagina_archivo(ids: list[int], geometria: str) -> dict[int, dict]:
    salida = {}
    for r in _wkt_de(ids):
        if geometria == "ninguna":
            salida[int(r["id"])] = _datos_geometria(None, _vertices_wkt(r["geom_segmento"]))
        else:
            geo, original = wkt_a_geojson(r["geom_segmento"], TOLERANCIA_SIMPLIFICACION)
            salida[int(r["id"])] = _datos_geometria(geo, original)
    return salida


def geometria_de_pagina(ids: list[int], geometria: str, fuente=None) -> dict[int, dict]:
    """{id: {geometria, vertices, vertices_original}} SOLO de los segmentos de una página: GeoJSON simplificado
    (~1 m), completo o ninguno, y los vértices de la geometría original."""
    if geometria not in ("simplificada", "completa", "ninguna"):
        raise FiltroInvalido("geometria debe ser simplificada, completa o ninguna")
    ids = [int(i) for i in ids][:500]
    if not ids:
        return {}
    if geometria == "completa":
        return {i: {**_datos_geometria(g, None), "vertices_original": len(g["coordinates"])}
                for i, g in geometria_completa(ids, fuente).items()}
    f = _fuente(fuente)
    if f is not None:
        origen = ("replica", getattr(f, "_id_motor", id(f)))
        return _memorizadas(origen, geometria, ids, lambda faltantes: _pagina_replica(f, faltantes, geometria), _ttl())
    p = _archivo_segmentos()
    return _memorizadas(("archivo", str(p), _mtime(p)), geometria, ids,
                        lambda faltantes: _pagina_archivo(faltantes, geometria), None)


def _tipologia(clase: Any) -> str:
    if clase is None or (isinstance(clase, float) and math.isnan(clase)) or not str(clase).strip():
        return "SIN_CLASE"
    return re.sub(r"[^A-Z0-9_-]", "_", str(clase).strip().upper())[:32]


def _leer_vehiculos(f, cols) -> tuple[pd.DataFrame, str]:
    """Vehículos del origen disponible: réplica de solo lectura, archivos exportados o el reporte de flota."""
    if f is not None:
        d = f.consultar_cacheado(("vehiculos",), "SELECT idvehiculo, placa, idruta, tipovehiculo, marca, modelo, "
                                 "n_sentados, n_depie, capacidad, estado, despacho_habilitado FROM vehiculos")
        return d, f.nombre
    try:
        return _parquet("vehiculos.parquet", cols), "archivos"
    except CatalogoNoDisponible:
        return _vehiculos_desde_flota(), "flota_csv"


def _agregar_clase(d: pd.DataFrame) -> None:
    """Quita la placa (dato que no se publica) y, si falta, agrega clase y carrocería cruzando por placa."""
    clases = _clase_por_placa()
    placas = d.pop("placa") if "placa" in d.columns else pd.Series([None] * len(d), index=d.index)
    cruce = [clases.get(str(p).strip().upper()) if isinstance(p, str) else None for p in placas]
    if "clase" not in d.columns:
        d["clase"] = [c[0] if c else None for c in cruce]
        d["carroceria"] = [c[1] if c else None for c in cruce]


def vehiculos(fuente=None) -> tuple[pd.DataFrame, str]:
    """Vehículos con capacidad sentados + de pie y tipología (clase del reporte de flota), sin datos personales."""
    cols = ("idvehiculo", "placa", "idruta", "tipovehiculo", "marca", "modelo", "n_sentados", "n_depie",
            "capacidad", "estado", "despacho_habilitado")
    d, nombre = _leer_vehiculos(_fuente(fuente), cols)
    _agregar_clase(d)
    d["tipologia"] = [_tipologia(c) for c in d["clase"]]
    sentados = pd.to_numeric(d.get("n_sentados"), errors="coerce")
    depie = pd.to_numeric(d.get("n_depie"), errors="coerce")
    total = sentados.fillna(0) + depie.fillna(0)
    nominal = pd.to_numeric(d.get("capacidad"), errors="coerce") if "capacidad" in d.columns else total * 0
    d["capacidad_total"] = np.where(total > 0, total, np.where(nominal.fillna(0) > 0, nominal, np.nan))
    d["n_sentados"], d["n_depie"] = sentados, depie
    if "estado" in d.columns:
        d["activo"] = d["estado"].map(lambda e: None if e is None else str(e).strip().upper() in ("Y", "S", "A"))
    d["idruta"] = pd.to_numeric(d["idruta"], errors="coerce").astype("Int64")
    d["ruta"] = d["idruta"].map(lambda x: None if pd.isna(x) else _nombre_ruta(int(x)))
    for c in COLUMNAS["vehiculos"]:
        if c not in d.columns:
            d[c] = None
    return d[COLUMNAS["vehiculos"]], nombre


_RUTAS_FLOTA = {"SILENCIO": 2, "KRA. 54 UNINORTE": 16, "72": 21}


def _vehiculos_desde_flota() -> pd.DataFrame:
    """Respaldo sin réplica ni vehiculos.parquet: el reporte de flota, sin placa (idvehiculo queda vacío)."""
    p = archivo_flota()
    f = _flota_csv(str(p), _mtime(p))
    if f is None:
        raise CatalogoNoDisponible("Sin réplica, sin la exportación vehiculos.parquet y sin el reporte de flota "
                                   "insumos_sobusa/flota_sobusa.csv (defina CATALOGOS_DATABASE_URL, "
                                   "CATALOGOS_DATOS_DIR o CATALOGOS_FLOTA_CSV)")
    f = f.drop_duplicates("Placa")
    return pd.DataFrame({
        "idvehiculo": None, "idruta": f["Ruta"].map(_RUTAS_FLOTA), "tipovehiculo": None, "marca": f["Marca"],
        "modelo": f["Modelo"], "n_sentados": pd.to_numeric(f["Sentados"], errors="coerce"),
        "n_depie": pd.to_numeric(f["Pie"], errors="coerce"), "capacidad": None, "estado": None,
        "despacho_habilitado": None, "clase": f["Clase"], "carroceria": f["Carrocería"]}).reset_index(drop=True)


def tipologias(fuente=None) -> tuple[pd.DataFrame, str]:
    """Resumen por ruta y tipología: vehículos, capacidad mediana, mínima y máxima (§10.1 tipologías distintas)."""
    d, nombre = vehiculos(fuente)
    d = d[d["capacidad_total"].notna()].copy()
    filas = []
    for (idruta, tip), g in d.groupby([d["idruta"].astype("float"), "tipologia"], dropna=False):
        filas.append({"idruta": None if pd.isna(idruta) else int(idruta),
                      "ruta": None if pd.isna(idruta) else _nombre_ruta(int(idruta)), "tipologia": tip,
                      "vehiculos": len(g), "capacidad_mediana": float(g["capacidad_total"].median()),
                      "capacidad_min": float(g["capacidad_total"].min()),
                      "capacidad_max": float(g["capacidad_total"].max()),
                      "sentados_mediana": float(g["n_sentados"].median()),
                      "depie_mediana": float(g["n_depie"].median())})
    return pd.DataFrame(filas), nombre


# ---------------------------------------------------------------- viajes y despachos (progvehiculos)
@lru_cache(maxsize=1)
def _progvehiculos_archivo(ruta: str, mtime: float) -> pd.DataFrame:
    import pyarrow.parquet as pq

    cols = ["idprogramacion", "idruta", "idvehiculo", "fechasalida", "fecharegistro", "fechainicio", "fechafin",
            "cancelada", "finalizado", "numeropasajeros"]
    return pq.read_table(ruta, columns=cols).to_pandas()


def _rango(desde: date | None, hasta: date | None) -> tuple[datetime | None, datetime | None]:
    """Fechas locales -> [desde 00:00, hasta+1 00:00) como timestamp local sin zona (así se guarda en la tabla)."""
    ini = datetime(desde.year, desde.month, desde.day) if desde else None
    try:
        fin = datetime(hasta.year, hasta.month, hasta.day) + timedelta(days=1) if hasta else None
    except OverflowError:                               # hasta = 9999-12-31: sin límite superior
        fin = None
    if ini and fin and fin <= ini:
        raise FiltroInvalido("hasta debe ser igual o posterior a desde")
    return ini, fin


_COLUMNAS_PROG = ("idprogramacion", "idruta", "idvehiculo", "fechasalida", "fecharegistro", "fechainicio", "fechafin",
                  "cancelada", "finalizado", "numeropasajeros")
_COLUMNAS_VIAJES = ("idprogramacion", "idruta", "idvehiculo", "fechasalida", "fecharegistro", "cancelada", "finalizado")
_COLUMNAS_DESPACHOS = ("idprogramacion", "idruta", "idvehiculo", "fechasalida", "fechainicio", "fechafin",
                       "numeropasajeros", "finalizado")
_ORDEN_SQL = {
    "viajes": {"hora_programada": "fechasalida", "idprogramacion": "idprogramacion", "idruta": "idruta",
               "idvehiculo": "idvehiculo", "registrado_en": "fecharegistro"},
    "despachos": {"salida_real": "fechainicio", "hora_programada": "fechasalida", "idprogramacion": "idprogramacion",
                  "idruta": "idruta", "idvehiculo": "idvehiculo", "retraso_min": "(fechainicio - fechasalida)"},
}


def _orden(catalogo: str, orden: str | None) -> tuple[str, bool]:
    campo = (orden or ORDEN_POR_DEFECTO[catalogo]).strip()
    desc = campo.startswith("-")
    nombre = campo.lstrip("-+")
    if nombre not in ORDENABLES[catalogo]:
        campos = ", ".join(ORDENABLES[catalogo])
        raise FiltroInvalido(f"No se puede ordenar {catalogo} por '{nombre}'. Campos: {campos}")
    return nombre, desc


def programacion(catalogo: str, *, idruta: int | None = None, desde: date | None = None, hasta: date | None = None,
                 idvehiculo: str | None = None, estado: str | None = None, retraso_minimo: float | None = None,
                 orden: str | None = None, limite: int = 50, desplazamiento: int = 0,
                 fuente=None) -> tuple[pd.DataFrame, int, str]:
    """Viajes programados (catalogo='viajes') o despachos reales (catalogo='despachos') de progvehiculos, filtrados,
    ordenados y paginados. Devuelve (página, total, fuente)."""
    if catalogo not in ("viajes", "despachos"):
        raise FiltroInvalido(catalogo)
    if estado is not None and estado not in ("programado", "cancelado", "finalizado"):
        raise FiltroInvalido("estado debe ser programado, cancelado o finalizado")
    campo, desc = _orden(catalogo, orden)
    ini, fin = _rango(desde, hasta)
    pedido = {"catalogo": catalogo, "idruta": None if idruta is None else int(idruta),
              "idvehiculo": str(idvehiculo) if idvehiculo else None, "estado": estado,
              "retraso_minimo": None if retraso_minimo is None else float(retraso_minimo), "desde": ini, "hasta": fin,
              "columna_fecha": "fechasalida" if catalogo == "viajes" else "fechainicio", "campo": campo, "desc": desc,
              "limite": max(0, min(int(limite), LIMITE_EXPORTACION)),
              "desplazamiento": max(0, min(int(desplazamiento), 10**12))}
    f = _fuente(fuente)
    if f is not None:
        pagina, n = _programacion_replica(f, pedido)
        nombre = f.nombre
    else:
        pagina, n = _programacion_archivo(pedido)
        nombre = "archivos"
    return _forma_programacion(catalogo, pagina), n, nombre


def _condiciones_replica(c, pedido: dict) -> tuple[list, dict]:
    """Condiciones WHERE de progvehiculos y sus parámetros enlazados (ningún valor entra en el texto SQL)."""
    import sqlalchemy as sa

    condiciones, params = [], {}
    if pedido["catalogo"] == "despachos":
        condiciones += [c.fechainicio.is_not(None), c.cancelada == sa.bindparam("no_cancelada")]
        params["no_cancelada"] = "N"
    for nombre_param, columna in (("idruta", c.idruta), ("idvehiculo", c.idvehiculo)):
        if pedido[nombre_param] is not None:
            condiciones.append(columna == sa.bindparam(nombre_param))
            params[nombre_param] = pedido[nombre_param]
    columna_fecha = c[pedido["columna_fecha"]]
    if pedido["desde"] is not None:
        condiciones.append(columna_fecha >= sa.bindparam("desde"))
        params["desde"] = pedido["desde"]
    if pedido["hasta"] is not None:
        condiciones.append(columna_fecha < sa.bindparam("hasta"))
        params["hasta"] = pedido["hasta"]
    if pedido["estado"] is not None:
        params.update(si="S", no="N")
        condiciones.append({"cancelado": c.cancelada == sa.bindparam("si"),
                            "finalizado": sa.and_(c.cancelada == sa.bindparam("no"),
                                                  c.finalizado == sa.bindparam("si")),
                            "programado": sa.and_(c.cancelada == sa.bindparam("no"),
                                                  c.finalizado.is_distinct_from(sa.bindparam("si")))}[pedido["estado"]])
    if pedido["retraso_minimo"] is not None:
        retraso = sa.extract("epoch", c.fechainicio - c.fechasalida) / 60.0
        condiciones.append(retraso >= sa.bindparam("retraso"))
        params["retraso"] = pedido["retraso_minimo"]
    return condiciones, params


def _programacion_replica(f, pedido: dict) -> tuple[pd.DataFrame, int]:
    """Página y total desde la réplica con SQLAlchemy Core: identificadores como objetos de una lista fija y valores
    siempre como parámetros enlazados."""
    import sqlalchemy as sa

    t = sa.table("progvehiculos", *(sa.column(x) for x in _COLUMNAS_PROG))
    c = t.c
    condiciones, params = _condiciones_replica(c, pedido)
    columnas = _COLUMNAS_VIAJES if pedido["catalogo"] == "viajes" else _COLUMNAS_DESPACHOS
    clave_orden = {"hora_programada": c.fechasalida, "salida_real": c.fechainicio, "registrado_en": c.fecharegistro,
                   "idprogramacion": c.idprogramacion, "idruta": c.idruta, "idvehiculo": c.idvehiculo,
                   "retraso_min": c.fechainicio - c.fechasalida}[pedido["campo"]]
    orden_sql = (clave_orden.desc() if pedido["desc"] else clave_orden.asc()).nulls_last()
    conteo = sa.select(sa.func.count().label("total")).select_from(t).where(sa.true(), *condiciones)
    consulta = (sa.select(*(c[x] for x in columnas)).where(sa.true(), *condiciones)
                .order_by(orden_sql, c.idprogramacion)
                .limit(sa.bindparam("limite", type_=sa.Integer))
                .offset(sa.bindparam("desplazamiento", type_=sa.BigInteger)))
    total = f.consultar(conteo, params)
    pagina = f.consultar(consulta, {**params, "limite": pedido["limite"], "desplazamiento": pedido["desplazamiento"]})
    return pagina, (int(total["total"].iloc[0]) if len(total) else 0)


def _mascara_archivo(d: pd.DataFrame, pedido: dict) -> np.ndarray:
    """Los mismos filtros que _condiciones_replica, sobre la exportación progvehiculos.parquet."""
    m = np.ones(len(d), dtype=bool)
    if pedido["catalogo"] == "despachos":
        m &= d["fechainicio"].notna().to_numpy() & (d["cancelada"] == "N").to_numpy()
    if pedido["idruta"] is not None:
        m &= (d["idruta"] == pedido["idruta"]).to_numpy()
    if pedido["desde"] is not None:
        m &= (d[pedido["columna_fecha"]] >= pedido["desde"]).to_numpy()
    if pedido["hasta"] is not None:
        m &= (d[pedido["columna_fecha"]] < pedido["hasta"]).to_numpy()
    if pedido["idvehiculo"]:
        m &= (d["idvehiculo"] == pedido["idvehiculo"]).to_numpy()
    if pedido["estado"] == "cancelado":
        m &= (d["cancelada"] == "S").to_numpy()
    elif pedido["estado"] == "finalizado":
        m &= ((d["cancelada"] == "N") & (d["finalizado"] == "S")).to_numpy()
    elif pedido["estado"] == "programado":
        m &= ((d["cancelada"] == "N") & (d["finalizado"] != "S")).to_numpy()
    if pedido["retraso_minimo"] is not None:
        retraso = (d["fechainicio"] - d["fechasalida"]).dt.total_seconds() / 60
        m &= (retraso >= pedido["retraso_minimo"]).to_numpy()
    return m


def _programacion_archivo(pedido: dict) -> tuple[pd.DataFrame, int]:
    """Página y total desde la exportación Parquet, con el mismo orden estable que la réplica."""
    p = _archivo("progvehiculos.parquet")
    if not p.exists():
        raise CatalogoNoDisponible("Sin réplica y sin la exportación progvehiculos.parquet "
                                   "(defina CATALOGOS_DATABASE_URL o CATALOGOS_DATOS_DIR)")
    d = _progvehiculos_archivo(str(p), _mtime(p))
    sub = d[_mascara_archivo(d, pedido)]
    n = len(sub)
    clave = _ORDEN_SQL[pedido["catalogo"]][pedido["campo"]].strip("()").split(" - ")
    ascendente = [not pedido["desc"], True]
    if len(clave) == 2:
        llave = (sub[clave[0]] - sub[clave[1]]).dt.total_seconds()
        sub = sub.assign(_k=llave).sort_values(["_k", "idprogramacion"], ascending=ascendente, na_position="last",
                                               kind="mergesort")
    else:
        sub = sub.sort_values([clave[0], "idprogramacion"], ascending=ascendente, na_position="last",
                              kind="mergesort")
    inicio = pedido["desplazamiento"]
    return sub.iloc[inicio:inicio + pedido["limite"]].copy(), n


# ---------------------------------------------------------------- viajes de una alerta (§5.3, ALT-006 y ALT-009)
_COLUMNAS_VIAJES_ALERTA = ("idprogramacion", "idruta", "idvehiculo", "idconductor", "fechasalida", "fechainicio",
                           "cancelada", "finalizado", "excedeplazosalida", "numeropasajeros")
_NOMBRES_VIAJE_ALERTA = {"idprogramacion": "viaje", "idvehiculo": "vehiculo", "fechasalida": "salida",
                         "fechainicio": "salida_real"}


def _local_sin_zona(t: datetime) -> datetime:
    """Instante -> timestamp local sin zona (así guarda las fechas progvehiculos)."""
    return t.astimezone(ZONA).replace(tzinfo=None) if t.tzinfo is not None else t


def viajes_para_alertas(ruta: Any, desde: datetime, hasta: datetime, fuente=None) -> pd.DataFrame:
    """Los viajes de la ruta con salida programada en [desde, hasta) para identificar el viaje, el vehículo y el
    conductor de ALT-006 y ALT-009 (§5.3): de la réplica en solo lectura (FuentePostgresSoloLectura.viajes) o, sin ella,
    de la exportación progvehiculos.parquet (solo las filas de la ruta y la ventana, sin cargar la tabla entera). El
    conductor sale solo seudonimizado (fuentes.seudonimizar_viajes, §18). Sin conteo de segmentos: fuera del ciclo
    integrado la capa de segmentos no cubre el periodo de la serie empaquetada. CatalogoNoDisponible si no hay ni
    réplica ni exportación."""
    import pyarrow.parquet as pq

    from app.servicios.fuentes import seudonimizar_viajes

    f = _fuente(fuente)
    if f is not None:
        return f.viajes(ruta, desde, hasta)
    p = _archivo("progvehiculos.parquet")
    if not p.exists():
        raise CatalogoNoDisponible("Sin réplica y sin la exportación progvehiculos.parquet: los viajes de la alerta "
                                   "no se identifican (defina CATALOGOS_DATABASE_URL o CATALOGOS_DATOS_DIR)")
    disponibles = set(pq.ParquetFile(str(p)).schema_arrow.names)
    filtros = [("idruta", "=", int(ruta_info(ruta)["idruta"])), ("fechasalida", ">=", _local_sin_zona(desde)),
               ("fechasalida", "<", _local_sin_zona(hasta))]
    d = pq.read_table(str(p), columns=[c for c in _COLUMNAS_VIAJES_ALERTA if c in disponibles],
                      filters=filtros).to_pandas()
    d = d.sort_values(["fechasalida", "idprogramacion"], kind="mergesort").rename(columns=_NOMBRES_VIAJE_ALERTA)
    return seudonimizar_viajes(d.assign(filas_segmento=None).drop(columns=["idruta"]))


def _forma_programacion(catalogo: str, d: pd.DataFrame) -> pd.DataFrame:
    if not len(d):
        return pd.DataFrame(columns=COLUMNAS[catalogo])
    d = d.copy()
    salida = pd.to_datetime(d["fechasalida"])
    d["hora_programada"] = salida
    d["ruta"] = d["idruta"].map(_nombre_ruta)
    if catalogo == "viajes":
        d["fecha"] = salida.dt.date
        d["registrado_en"] = pd.to_datetime(d["fecharegistro"])
        d["cancelada"] = d["cancelada"].map(lambda v: None if v is None else v == "S")
        d["finalizado"] = d["finalizado"].map(lambda v: None if v is None else v == "S")
        d["estado"] = [("cancelado" if c else "finalizado" if fz else "programado")
                       for c, fz in zip(d["cancelada"], d["finalizado"], strict=False)]
    else:
        inicio, fin = pd.to_datetime(d["fechainicio"]), pd.to_datetime(d["fechafin"])
        d["fecha"] = inicio.dt.date
        d["salida_real"], d["llegada"] = inicio, fin
        d["retraso_min"] = ((inicio - salida).dt.total_seconds() / 60).round(1)
        d["duracion_min"] = ((fin - inicio).dt.total_seconds() / 60).round(1)
        d["pasajeros"] = pd.to_numeric(d["numeropasajeros"], errors="coerce").astype("Int64")
        d["finalizado"] = d["finalizado"].map(lambda v: None if v is None else v == "S")
    return d[COLUMNAS[catalogo]]


# ---------------------------------------------------------------- filtros, orden y paginación en memoria
def filtrar(df: pd.DataFrame, **filtros: Any) -> pd.DataFrame:
    """Igualdad por columna (None = sin filtro). Columnas fuera del DataFrame -> FiltroInvalido."""
    m = pd.Series(True, index=df.index)
    for col, valor in filtros.items():
        if valor is None:
            continue
        if col not in df.columns:
            raise FiltroInvalido(f"Filtro desconocido: {col}")
        serie = df[col]
        if isinstance(valor, bool):
            m &= serie.map(lambda v, b=valor: v is not None and not pd.isna(v) and bool(v) == b)
        elif isinstance(valor, (int, float)) and not isinstance(valor, bool):
            m &= pd.to_numeric(serie, errors="coerce") == valor
        else:
            m &= serie.astype(str).str.upper() == str(valor).upper()
    return df[m]


def paginar(df: pd.DataFrame, catalogo: str, orden: str | None, limite: int, desplazamiento: int
            ) -> tuple[pd.DataFrame, int]:
    campo, desc = _orden(catalogo, orden)
    total = len(df)
    if total:
        df = df.sort_values(campo, ascending=not desc, na_position="last", kind="mergesort")
    return df.iloc[int(desplazamiento):int(desplazamiento) + int(limite)], total


def exportar(df: pd.DataFrame, columnas: list[str], formato: str, nombre: str) -> tuple[bytes, str, str]:
    """(contenido, media_type, nombre de archivo) en CSV o XLSX; instantes en America/Bogota (-05:00)."""
    filas = registros(df.head(LIMITE_EXPORTACION), columnas)
    for f in filas:
        for k, v in list(f.items()):
            if isinstance(v, datetime):
                f[k] = v.isoformat()
            elif isinstance(v, (dict, list)):
                f[k] = json.dumps(v, ensure_ascii=False)
    tabla = pd.DataFrame(filas, columns=[c for c in columnas if c not in COLUMNAS_PROHIBIDAS])
    marca = datetime.now(ZONA).strftime("%Y%m%d_%H%M%S")
    if formato == "xlsx":
        import io

        from openpyxl import Workbook

        # modo write_only de openpyxl: escribe fila por fila sin armar la hoja en memoria (100.000 filas de despachos
        # en unos 13 s en lugar de 21 s con pandas.to_excel, medido en el mismo equipo)
        libro = Workbook(write_only=True)
        hoja = libro.create_sheet(nombre[:31])
        hoja.append(list(tabla.columns))
        for fila in tabla.astype(object).where(tabla.notna(), None).itertuples(index=False, name=None):
            hoja.append(list(fila))
        buffer = io.BytesIO()
        libro.save(buffer)
        return (buffer.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                f"{nombre}_{marca}.xlsx")
    return tabla.to_csv(index=False).encode("utf-8-sig"), "text/csv; charset=utf-8", f"{nombre}_{marca}.csv"


# ---------------------------------------------------------------- ajuste local de capacidad (§3.2, §8.3)
def normalizar_tipologia(tipologia: str | None) -> str:
    t = (tipologia or TIPOLOGIA_TODAS).strip().upper()
    if not _RE_TIPOLOGIA.match(t):
        raise ValueError("tipologia: 1 a 32 caracteres A-Z, 0-9, _ o - (TODAS = toda la ruta)")
    return t


def clave_capacidad(idruta: int, tipologia: str | None = None) -> str:
    return f"{PREFIJO_CAPACIDAD}.{int(idruta)}.{normalizar_tipologia(tipologia)}"


def ajustes_capacidad(umbrales: dict[str, Any]) -> dict[tuple[int, str], int]:
    """{(idruta, tipología): capacidad} de los parámetros vigentes con prefijo capacidad_override (los inválidos se
    ignoran y quedan en el log)."""
    salida: dict[tuple[int, str], int] = {}
    for nombre, valor in (umbrales or {}).items():
        if not str(nombre).startswith(PREFIJO_CAPACIDAD + "."):
            continue
        partes = str(nombre).split(".")
        try:
            idruta, tip, cap = int(partes[1]), partes[2], float(valor)
        except (IndexError, TypeError, ValueError):
            log.warning("Ajuste de capacidad inválido ignorado: %s", nombre)
            continue
        if not CAPACIDAD_MIN <= cap <= CAPACIDAD_MAX:
            log.warning("Ajuste de capacidad fuera de rango ignorado: %s=%s", nombre, valor)
            continue
        salida[(idruta, tip)] = int(round(cap))
    return salida


def _umbrales_de_la_base(sesion=None) -> tuple[int | None, dict[str, Any]]:
    from app.servicios.ejecucion import umbrales_vigentes

    if sesion is not None:
        return umbrales_vigentes(sesion)
    try:
        from app.db import sesion_contexto

        with sesion_contexto() as s:
            return umbrales_vigentes(s)
    except Exception:  # noqa: BLE001 - sin base de resultados se usa la capacidad del catálogo (queda en el log)
        log.warning("Sin base de resultados: capacidad del catálogo sin ajustes locales")
        return None, {}


def capacidad_vigente(ruta: Any, tipologia: str | None = None, *, umbrales: dict[str, Any] | None = None,
                      umbrales_version: int | None = None, sesion=None) -> dict:
    """Contrato para el optimizador: capacidad operativa vigente de una ruta (nombre o idruta).

    Prioridad: ajuste local de la tipología pedida > ajuste local de toda la ruta (TODAS) > capacidad del catálogo.
    ``umbrales``: el dict de parámetros vigentes que ya leyó el ciclo (misma versión que queda en la recomendación);
    si no se da, se lee de la base (``sesion`` o una sesión propia). Devuelve capacidad, fuente, clave, versión y los
    ajustes por tipología de la ruta. KeyError si la ruta no existe."""
    info = ruta_info(ruta)
    idruta = int(info["idruta"])
    base = int(info.get("capacidad") or 50)
    if umbrales is None:
        umbrales_version, umbrales = _umbrales_de_la_base(sesion)
    ajustes = ajustes_capacidad(umbrales or {})
    tip = normalizar_tipologia(tipologia) if tipologia else None
    elegido = None
    for t in ([tip] if tip and tip != TIPOLOGIA_TODAS else []) + [TIPOLOGIA_TODAS]:
        if (idruta, t) in ajustes:
            elegido = t
            break
    return {"ruta": info["ruta"], "idruta": idruta, "tipologia": tip or TIPOLOGIA_TODAS,
            "capacidad": ajustes[(idruta, elegido)] if elegido else base, "capacidad_catalogo": base,
            "fuente": "ajuste_local" if elegido else "catalogo",
            "clave": clave_capacidad(idruta, elegido) if elegido else None, "umbrales_version": umbrales_version,
            "por_tipologia": {t: c for (r, t), c in sorted(ajustes.items()) if r == idruta}}


def versionar_ajustes(sesion, cambios: dict[str, Any], creado_por: str, motivo: str,
                      describir: Callable[[str], str]) -> int:
    """Versión nueva del conjunto gobernado (threshold_config) con `cambios` ({nombre: valor}; None retira el ajuste).
    Copia el resto del conjunto vigente, firma creado_por y motivo y deja la anterior como histórico. Un cambio a la
    vez: el candado de la transacción (ejecucion.bloquear_umbrales, el mismo de PUT /thresholds) se toma antes de leer
    la versión vigente, así que dos cambios simultáneos no parten de la misma versión. LookupError si se retira un
    ajuste que no está vigente. `describir(nombre)` da la descripción de un parámetro nuevo. Devuelve la versión
    nueva. La usan el ajuste de capacidad y el de flota y ciclo (app/servicios/flota_ciclo.py)."""
    from sqlalchemy import func, select, update

    from app.modelos_db import Umbral
    from app.servicios.ejecucion import bloquear_umbrales

    bloquear_umbrales(sesion)
    filas = sesion.scalars(select(Umbral).where(Umbral.vigente).with_for_update()).all()
    actuales = {f.nombre: f for f in filas}
    combinados = {n: f.valor for n, f in actuales.items()}
    for nombre, valor in cambios.items():
        if valor is not None:
            combinados[nombre] = valor
        elif combinados.pop(nombre, None) is None:
            raise LookupError(f"No hay un ajuste vigente {nombre}")
    nueva = (sesion.scalar(select(func.max(Umbral.version))) or 0) + 1
    sesion.execute(update(Umbral).where(Umbral.vigente).values(vigente=False))
    sesion.flush()
    for nombre, valor in combinados.items():
        descripcion = actuales[nombre].descripcion if nombre in actuales else describir(nombre)
        sesion.add(Umbral(nombre=nombre, valor=valor, descripcion=descripcion, version=nueva, vigente=True,
                          creado_por=creado_por, motivo=motivo.strip()))
    sesion.commit()
    return nueva


def fijar_capacidad(sesion, idruta: int, tipologia: str | None, capacidad: int | None, creado_por: str,
                    motivo: str) -> int:
    """Crea una versión nueva del conjunto gobernado con el ajuste (capacidad=None lo retira). Un cambio a la vez
    (versionar_ajustes toma el candado de threshold_config). Devuelve la versión nueva."""
    ruta_info(idruta)                                     # integridad referencial hacia una ruta autorizada
    if not motivo or not motivo.strip():
        raise ValueError("motivo es obligatorio para un ajuste de capacidad")
    clave = clave_capacidad(idruta, tipologia)
    if capacidad is not None and not CAPACIDAD_MIN <= int(capacidad) <= CAPACIDAD_MAX:
        raise ValueError(f"capacidad debe estar entre {CAPACIDAD_MIN} y {CAPACIDAD_MAX} pasajeros")
    _, _, tip = clave.split(".")
    descripcion = (f"§3.2 Ajuste local: capacidad operativa autorizada de la ruta {idruta}, tipología {tip} "
                   "(pasajeros por bus; solo en ai_frecuencias)")
    return versionar_ajustes(sesion, {clave: None if capacidad is None else int(capacidad)}, creado_por, motivo,
                             lambda _nombre: descripcion)


def _cambios_de_version(version: int, v: dict, anterior: dict) -> list[dict]:
    """Ajustes creados, cambiados o retirados en una versión frente a la anterior."""
    eventos = []
    actual = v["ajustes"]
    for nombre in sorted(set(anterior) | set(actual)):
        antes, despues = anterior.get(nombre), actual.get(nombre)
        if antes == despues:
            continue
        accion = "creado" if antes is None else "retirado" if despues is None else "cambiado"
        eventos.append({"version": version, "nombre": nombre, "accion": accion, "antes": antes, "despues": despues,
                        "creado_por": v["creado_por"], "motivo": v["motivo"], "creado_en": a_bogota(v["creado_en"])})
    return eventos


def eventos_ajustes(sesion, prefijos: tuple[str, ...]) -> list[dict]:
    """Cambios de los ajustes locales cuyos nombres empiezan por `prefijos`, versión por versión y del más antiguo al
    más reciente: {version, nombre, accion (creado, cambiado o retirado), antes, despues, creado_por, motivo,
    creado_en (America/Bogota)}. Los usan el historial de la capacidad y el de la flota y el ciclo."""
    from sqlalchemy import select

    from app.modelos_db import Umbral

    filas = sesion.execute(select(Umbral.version, Umbral.nombre, Umbral.valor, Umbral.creado_por, Umbral.motivo,
                                  Umbral.creado_en).order_by(Umbral.version)).all()
    por_version: dict[int, dict] = {}
    for f in filas:
        v = por_version.setdefault(f.version, {"ajustes": {}, "creado_por": f.creado_por, "motivo": f.motivo,
                                               "creado_en": f.creado_en})
        if str(f.nombre).startswith(prefijos):
            v["ajustes"][f.nombre] = f.valor
    eventos, anterior = [], {}
    for version in sorted(por_version):
        v = por_version[version]
        eventos += _cambios_de_version(version, v, anterior)
        anterior = v["ajustes"]
    return eventos


def historial_capacidad(sesion, idruta: int | None = None) -> list[dict]:
    """Cambios de los ajustes de capacidad, versión por versión (creado, cambiado o retirado), con quién y por qué."""
    eventos = []
    for e in eventos_ajustes(sesion, (PREFIJO_CAPACIDAD + ".",)):
        _, r, tip = e["nombre"].split(".")
        if idruta is not None and int(r) != int(idruta):
            continue
        eventos.append({"version": e["version"], "idruta": int(r), "ruta": _nombre_ruta(int(r)), "tipologia": tip,
                        "accion": e["accion"], "capacidad_anterior": e["antes"], "capacidad_nueva": e["despues"],
                        "creado_por": e["creado_por"], "motivo": e["motivo"], "creado_en": e["creado_en"]})
    return list(reversed(eventos))


__all__ = ["capacidad_vigente", "fijar_capacidad", "historial_capacidad", "ajustes_capacidad", "clave_capacidad",
           "versionar_ajustes", "eventos_ajustes",
           "procesos", "empresas", "rutas", "segmentos", "vehiculos", "tipologias", "programacion", "a_bogota",
           "CatalogoNoDisponible", "FiltroInvalido", "FuenteReplica", "COLUMNAS", "COLUMNAS_PROHIBIDAS", "modo"]
