"""Datos de demanda y catálogo de rutas empaquetados con la API (carpeta datos/).

Todo sale de archivos del propio proyecto generados por scripts/preparar_datos_api.py (ver datos/origen.json):
- demanda_horaria.parquet: pasajeros y salidas por ruta, fecha y hora de salida (4-20 h), 2023-2025.
- catalogo_rutas.json: capacidad (50), tiempo de ciclo, flota y frecuencia actual por ruta.
- parametros_operativos_hora.parquet: los mismos parámetros por ruta, tipo de día y hora.

La carpeta se puede cambiar con la variable de entorno DATA_DIR (la misma de app/config.py).
No hay conexión a ninguna base de datos aquí: es la fuente offline y reproducible por defecto.
"""

from __future__ import annotations

import json
import os
from datetime import date
from functools import lru_cache
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parents[2]
ZONA = "America/Bogota"
HORAS_SERVICIO = range(4, 21)  # horas de salida con servicio: 4..20
HORAS_PICO = (6, 7, 8, 17, 18, 19)  # franjas 6-8 h y 17-19 h (horas de salida)
CAPACIDAD_BUS = 50
COLUMNAS_CONTRATO = ["ruta", "fecha", "hora", "pasajeros", "salidas", "ultima_actualizacion"]
TIPOS_DIA = {0: "Laboral", 1: "Sábado", 2: "Domingo/festivo"}


def carpeta_datos() -> Path:
    valor = os.environ.get("DATA_DIR", "")
    return Path(valor) if valor else RAIZ / "datos"


def carpeta_modelos() -> Path:
    valor = os.environ.get("MODELOS_DIR", "")
    return Path(valor) if valor else carpeta_datos() / "modelos"


@lru_cache(maxsize=4)
def _cargar_demanda(ruta_archivo: str) -> pd.DataFrame:
    d = pd.read_parquet(ruta_archivo)
    d["fecha"] = pd.to_datetime(d["fecha"]).dt.date
    d["hora"] = d["hora"].astype(int)
    d["pasajeros"] = d["pasajeros"].astype(float)
    if d["ultima_actualizacion"].dt.tz is None:
        d["ultima_actualizacion"] = d["ultima_actualizacion"].dt.tz_localize(ZONA)
    otras = [c for c in d.columns if c not in COLUMNAS_CONTRATO]
    return d[COLUMNAS_CONTRATO + otras].reset_index(drop=True)


def demanda_horaria(
    desde: date | None = None, hasta: date | None = None, rutas: list[str] | None = None
) -> pd.DataFrame:
    """Serie horaria de demanda.

    Columnas del contrato: ruta (str), fecha (date), hora (int 4..20), pasajeros (float), salidas (Int, puede faltar),
    ultima_actualizacion (datetime con zona America/Bogota). Columnas extra: idruta, tipo_dia (0 Laboral, 1 Sábado,
    2 Domingo/festivo), festivo, carnaval, semana_santa, vacaciones, navidad, primero_enero, excluido.
    Devuelve una copia (se puede modificar sin tocar la caché).
    """
    d = _cargar_demanda(str(carpeta_datos() / "demanda_horaria.parquet"))
    m = pd.Series(True, index=d.index)
    if desde is not None:
        m &= d["fecha"] >= desde
    if hasta is not None:
        m &= d["fecha"] <= hasta
    if rutas:
        m &= d["ruta"].isin(rutas)
    return d[m].copy()


def rango_fechas() -> tuple[date, date]:
    d = _cargar_demanda(str(carpeta_datos() / "demanda_horaria.parquet"))
    return d["fecha"].min(), d["fecha"].max()


@lru_cache(maxsize=4)
def _cargar_catalogo(ruta_archivo: str) -> tuple[dict, ...]:
    return tuple(json.loads(Path(ruta_archivo).read_text(encoding="utf-8")))


def catalogo_rutas() -> list[dict]:
    """Rutas con ruta, idruta, capacidad, tiempo_ciclo_min, flota, frecuencia_actual_min (+ codigo, por_tipo_dia...).

    Fuentes: idruta/codigo de la tabla rutas (datos/rutas.parquet del proyecto); ciclo, flota e intervalo programado de
    experimentos/D1_optimizacion/parametros_operativos.parquet (mediana de día laboral, 6-19 h); capacidad 50.
    """
    return [dict(r) for r in _cargar_catalogo(str(carpeta_datos() / "catalogo_rutas.json"))]


def ruta_info(ruta: str) -> dict:
    for r in catalogo_rutas():
        if r["ruta"] == ruta or str(r["idruta"]) == str(ruta):
            return r
    raise KeyError(f"Ruta desconocida: {ruta!r}. Rutas válidas: {[r['ruta'] for r in catalogo_rutas()]}")


def nombres_rutas() -> list[str]:
    return [r["ruta"] for r in catalogo_rutas()]


@lru_cache(maxsize=2)
def _cargar_parametros(ruta_archivo: str) -> pd.DataFrame:
    return pd.read_parquet(ruta_archivo)


def parametros_operativos(ruta: str | None = None, tipo_dia: str | None = None) -> pd.DataFrame:
    """Ciclo, flota, intervalo programado, nmin y nmax por ruta, tipo de día y hora.

    tipo_dia: Laboral, Sábado o Domingo/festivo.
    """
    p = _cargar_parametros(str(carpeta_datos() / "parametros_operativos_hora.parquet")).copy()
    if ruta is not None:
        p = p[p["ruta"] == ruta]
    if tipo_dia is not None:
        p = p[p["tipo_dia"] == tipo_dia]
    return p.reset_index(drop=True)


def tipo_dia_de(fecha: date, festivo: bool = False) -> int:
    """0 Laboral, 1 Sábado, 2 Domingo/festivo."""
    if festivo or fecha.weekday() == 6:
        return 2
    return 1 if fecha.weekday() == 5 else 0


def limpiar_cache() -> None:
    _cargar_demanda.cache_clear()
    _cargar_catalogo.cache_clear()
    _cargar_parametros.cache_clear()
