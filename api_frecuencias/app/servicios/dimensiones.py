"""Dimensiones de §8.3 en las tablas de resultados: idruta, idempresa, idproceso, id_dia_semana e id_estacionalidad.

§8.3 pide «mantener id_ruta, proceso, id_dia_semana e id_estacionalidad como dimensiones, sin cambiar su semántica».
Cada predicción, recomendación, alerta, fila del histórico (demanda_observada) y foto de variables guarda estas
columnas junto al nombre de la ruta, con los valores de las tablas de Extreme:

- idruta: rutas.idruta (entero). Sale del catálogo empaquetado de la API (datos/catalogo_rutas.json), que es la
  correspondencia nombre -> idruta de las tres rutas del reto.
- idempresa: rutas.idempresa (entero, nulo si la tabla no lo trae; en la exportación de Sobusa viene nulo).
- idproceso: la llave de "Procesos", que en Extreme es la columna de TEXTO rutas.proceso (p. ej. «sobusa»). Se
  guarda tal cual, sin convertirla a número, para no cambiar su semántica.
- id_dia_semana: día ISO 1 = lunes … 7 = domingo de la fecha local (America/Bogota), el de dias_semana.
- id_estacionalidad: estacionalidades_anio vigente en la fecha para el proceso de la ruta; nulo si no hay ninguna
  (las estacionalidades exportadas son de otro proceso y Sobusa no tiene filas propias: hallazgo H1 de
  docs/hallazgos_extreme.md).
- En modo integrado el lote de demanda_segmentos ya trae proceso, idempresa e id_estacionalidad por franja
  (app/servicios/fuentes.py): columnas_lote() los respeta cuando vienen y solo completa lo que falte.

Orden de las fuentes: primero el catálogo empaquetado (si trae idempresa, proceso o empresa); lo que falte se toma
de la tabla rutas y de "Procesos" (réplica de solo lectura en modo integrado o exportaciones Parquet), por medio de
app/servicios/catalogos.py. Si ninguna fuente responde, el valor queda nulo: nunca se inventa.

El mapa se guarda en memoria con vencimiento (DIMENSIONES_CACHE_S, 300 s por omisión); limpiar_cache() lo borra.
"""
from __future__ import annotations

import logging
import math
import os
import threading
import time
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

ZONA = ZoneInfo("America/Bogota")
CAMPOS = ("idruta", "idempresa", "idproceso", "id_dia_semana", "id_estacionalidad")
log = logging.getLogger("api_frecuencias.dimensiones")

_bloqueo = threading.Lock()
_cache: dict[str, tuple[float, Any]] = {}


# ---------------------------------------------------------------- utilidades
def _entero(valor: Any) -> int | None:
    if valor is None or isinstance(valor, bool):
        return None
    try:
        f = float(str(valor).strip())
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f) or not f.is_integer():
        return None
    return int(f)


def _texto(valor: Any) -> str | None:
    if valor is None:
        return None
    if isinstance(valor, float):
        if math.isnan(valor):
            return None
        if valor.is_integer():
            valor = int(valor)
    texto = str(valor).strip()
    return texto or None


def _ttl() -> float:
    try:
        return max(0.0, float(os.environ.get("DIMENSIONES_CACHE_S", "300")))
    except ValueError:
        return 300.0


def _cacheado(clave: str, calcular):
    ahora = time.monotonic()
    with _bloqueo:
        guardado = _cache.get(clave)
        if guardado is not None and ahora - guardado[0] < _ttl():
            return guardado[1]
    valor = calcular()
    with _bloqueo:
        _cache[clave] = (ahora, valor)
    return valor


def limpiar_cache() -> None:
    with _bloqueo:
        _cache.clear()


def fecha_local(valor: Any) -> date | None:
    """date | datetime (con o sin zona) | texto ISO -> fecha local en America/Bogota (None si no se puede)."""
    if valor is None:
        return None
    if hasattr(valor, "to_pydatetime"):
        valor = valor.to_pydatetime()
    if isinstance(valor, str):
        try:
            valor = datetime.fromisoformat(valor) if ("T" in valor or " " in valor) else date.fromisoformat(valor)
        except ValueError:
            return None
    if isinstance(valor, datetime):
        return valor.astimezone(ZONA).date() if valor.tzinfo else valor.date()
    if isinstance(valor, date):
        return valor
    return None


def dia_semana_iso(valor: Any) -> int | None:
    """1 = lunes … 7 = domingo (ISO 8601, como dias_semana de Extreme)."""
    dia = fecha_local(valor)
    return dia.isoweekday() if dia else None


# ---------------------------------------------------------------- mapa de rutas
def _desde_catalogo_empaquetado() -> dict[str, dict]:
    from app.servicios import datos

    mapa: dict[str, dict] = {}
    for r in datos.catalogo_rutas():
        mapa[str(r["ruta"])] = {
            "ruta": str(r["ruta"]), "idruta": _entero(r.get("idruta")),
            "idempresa": _entero(r.get("idempresa")),
            "idproceso": _texto(r.get("idproceso", r.get("proceso"))),
            "empresa": _texto(r.get("empresa")),
        }
    return mapa


def _completar_con_tabla_rutas(mapa: dict[str, dict]) -> None:
    """idempresa y proceso de la tabla rutas (réplica de solo lectura o exportación rutas.parquet)."""
    if all(f["idempresa"] is not None and f["idproceso"] is not None for f in mapa.values()):
        return
    try:
        from app.servicios import catalogos

        tabla, _origen = catalogos.rutas_tabla()
    except Exception as exc:  # noqa: BLE001 - sin la tabla rutas los valores quedan nulos
        log.info("tabla rutas no disponible para las dimensiones: %s", exc)
        return
    if tabla is None or not len(tabla) or "idruta" not in tabla.columns:
        return
    por_id = {}
    for fila in tabla.to_dict("records"):
        ident = _entero(fila.get("idruta"))
        if ident is not None:
            por_id[ident] = fila
    for f in mapa.values():
        t = por_id.get(f["idruta"])
        if not t:
            continue
        if f["idempresa"] is None:
            f["idempresa"] = _entero(t.get("idempresa"))
        if f["idproceso"] is None:
            f["idproceso"] = _texto(t.get("proceso"))


def _nombres_de_proceso() -> dict[str, str]:
    """proceso -> nombre de "Procesos" (la empresa operadora, p. ej. «SOBUSA»)."""
    try:
        from app.servicios import catalogos

        tabla, _origen = catalogos.procesos()
    except Exception as exc:  # noqa: BLE001
        log.info("Procesos no disponible para el nombre de la empresa: %s", exc)
        return {}
    if tabla is None or not len(tabla) or "proceso" not in tabla.columns:
        return {}
    return {str(p): _texto(n) for p, n in zip(tabla["proceso"], tabla.get("nombre", [None] * len(tabla)),
                                              strict=False) if _texto(p) and _texto(n)}


def _construir_mapa() -> dict[str, dict]:
    mapa = _desde_catalogo_empaquetado()
    _completar_con_tabla_rutas(mapa)
    if any(f["empresa"] is None for f in mapa.values()):
        nombres = _nombres_de_proceso()
        for f in mapa.values():
            if f["empresa"] is None and f["idproceso"] is not None:
                f["empresa"] = nombres.get(f["idproceso"])
    return mapa


def mapa_rutas() -> dict[str, dict]:
    """{nombre de ruta: {ruta, idruta, idempresa, idproceso, empresa}} (copia; con caché)."""
    return {k: dict(v) for k, v in _cacheado("rutas", _construir_mapa).items()}


def _ruta(ruta: Any) -> dict | None:
    if ruta is None:
        return None
    mapa = _cacheado("rutas", _construir_mapa)
    texto = str(ruta).strip()
    if texto in mapa:
        return mapa[texto]
    for f in mapa.values():           # también por idruta («2») o sin distinguir mayúsculas
        if str(f["idruta"]) == texto or f["ruta"].upper() == texto.upper():
            return f
    return None


def idruta(ruta: Any) -> int | None:
    f = _ruta(ruta)
    return None if f is None else f["idruta"]


def empresa(ruta: Any) -> str | None:
    """Empresa de la ruta según el catálogo: la del catálogo empaquetado o el nombre de su proceso en "Procesos"
    (Extreme no trae rutas.idempresa para Sobusa). Nulo si ninguna fuente lo dice."""
    f = _ruta(ruta)
    return None if f is None else f["empresa"]


# ---------------------------------------------------------------- estacionalidad
def _leer_vigencias() -> list[tuple[str | None, int, date, date]]:
    """(proceso, id_estacionalidad, desde, hasta) de estacionalidades_anio (réplica o exportación)."""
    try:
        from app.servicios import catalogos

        fuente = catalogos._fuente(None)
        if fuente is not None:
            tabla = fuente.consultar_cacheado(("estacionalidades_anio_dimensiones",),
                                              "SELECT proceso, id_estacionalidad, fecha_inicio, fecha_fin "
                                              "FROM estacionalidades_anio")
        else:
            tabla = catalogos._parquet("estacionalidades_anio.parquet",
                                       ("proceso", "id_estacionalidad", "fecha_inicio", "fecha_fin"))
    except Exception as exc:  # noqa: BLE001 - sin el catálogo la estacionalidad queda nula
        log.info("estacionalidades_anio no disponible: %s", exc)
        return []
    vigencias = []
    for fila in tabla.to_dict("records"):
        ident, desde, hasta = (_entero(fila.get("id_estacionalidad")), fecha_local(fila.get("fecha_inicio")),
                               fecha_local(fila.get("fecha_fin")))
        if ident is not None and desde is not None and hasta is not None:
            vigencias.append((_texto(fila.get("proceso")), ident, desde, hasta))
    return vigencias


def estacionalidad(dia: Any, proceso: str | None) -> int | None:
    """id_estacionalidad vigente en la fecha para el proceso (la de vigencia más corta si se solapan)."""
    fecha = fecha_local(dia)
    if fecha is None or proceso is None:
        return None
    candidatas = [(hasta - desde, ident) for p, ident, desde, hasta in _cacheado("vigencias", _leer_vigencias)
                  if p == proceso and desde <= fecha <= hasta]
    return min(candidatas)[1] if candidatas else None


# ---------------------------------------------------------------- API del módulo
def dimensiones(ruta: Any, instante_o_fecha: Any = None, *, id_estacionalidad: int | None = None) -> dict:
    """{idruta, idempresa, idproceso, id_dia_semana, id_estacionalidad} de una ruta en una fecha o instante.

    ruta: nombre (SILENCIO) o idruta. instante_o_fecha: date, datetime (se lleva a America/Bogota) o texto ISO.
    id_estacionalidad: si el contexto operacional ya la trae, se respeta. Las rutas desconocidas dan todo nulo
    salvo el día de la semana."""
    f = _ruta(ruta) or {}
    proceso = f.get("idproceso")
    dia = fecha_local(instante_o_fecha)
    return {
        "idruta": f.get("idruta"),
        "idempresa": f.get("idempresa"),
        "idproceso": proceso,
        "id_dia_semana": dia.isoweekday() if dia else None,
        "id_estacionalidad": id_estacionalidad if id_estacionalidad is not None else estacionalidad(dia, proceso),
    }


# columnas del lote integrado (demanda_segmentos) -> dimensión y conversión (idempresa e id_estacionalidad enteros;
# proceso es texto en Extreme y se guarda tal cual en idproceso)
COLUMNAS_DEL_LOTE = (("proceso", "idproceso", "texto"), ("idproceso", "idproceso", "texto"),
                     ("idempresa", "idempresa", "entero"), ("id_estacionalidad", "id_estacionalidad", "entero"))


def _del_lote(fila: dict) -> dict:
    """Lo que el lote ya trae de las dimensiones (nunca un texto en idempresa ni en id_estacionalidad)."""
    salida: dict[str, Any] = {}
    for columna, campo, tipo in COLUMNAS_DEL_LOTE:
        if columna in fila and campo not in salida:
            valor = _texto(fila[columna]) if tipo == "texto" else _entero(fila[columna])
            if valor is not None:
                salida[campo] = valor
    return salida


def columnas_lote(df, columna_ruta: str = "ruta", columna_fecha: str = "fecha"):
    """Las cinco columnas para un DataFrame (histórico): una consulta del mapa por ruta y fecha distintas. Si el lote
    trae proceso, idempresa o id_estacionalidad (lectura integrada de demanda_segmentos), esos valores mandan."""
    import pandas as pd

    salida = pd.DataFrame(index=df.index, columns=list(CAMPOS), dtype=object)
    if df is None or not len(df):
        return salida
    propias = [c for c, _campo, _tipo in COLUMNAS_DEL_LOTE if c in df.columns]
    memoria: dict[tuple, dict] = {}
    for posicion, (i, ruta, fecha) in enumerate(zip(df.index, df[columna_ruta], df[columna_fecha], strict=False)):
        del_lote = _del_lote({c: df[c].iat[posicion] for c in propias}) if propias else {}
        dia = fecha_local(fecha)
        clave = (ruta, dia, del_lote.get("idproceso"), del_lote.get("id_estacionalidad"))
        if clave not in memoria:
            base = dimensiones(ruta, dia, id_estacionalidad=del_lote.get("id_estacionalidad"))
            if del_lote.get("idproceso") is not None and del_lote.get("id_estacionalidad") is None:
                base["idproceso"] = del_lote["idproceso"]
                base["id_estacionalidad"] = estacionalidad(dia, del_lote["idproceso"])
            memoria[clave] = base
        valores = dict(memoria[clave]) | {k: v for k, v in del_lote.items() if v is not None}
        for campo in CAMPOS:
            salida.at[i, campo] = valores.get(campo)
    return salida


__all__ = ["CAMPOS", "columnas_lote", "dia_semana_iso", "dimensiones", "empresa", "estacionalidad", "fecha_local",
           "idruta", "limpiar_cache", "mapa_rutas"]
