"""Datos de demanda y catálogo de rutas empaquetados con la API (carpeta datos/).

Todo sale de archivos del propio proyecto generados por scripts/preparar_datos_api.py (ver datos/origen.json):
- demanda_horaria.parquet: pasajeros y salidas por ruta, fecha y hora de salida (4-20 h), 2023-2025.
- catalogo_rutas.json: capacidad (50), tiempo de ciclo, flota y frecuencia actual por ruta.
- parametros_operativos_hora.parquet: los mismos parámetros por ruta, tipo de día y hora.
- contexto_operacional.parquet: novedades viales por hora y festivos oficiales (variables fv2, se conocen antes).
- perfil_intrahorario.parquet: reparto de las subidas entre la primera y la segunda media hora (ventanas 30/60/120).
- clima_diario.parquet: lluvia diaria observada, solo para evaluar por condición.
Los tres últimos son opcionales: si faltan, las variables de contexto valen 0 y el reparto intrahorario es 0,5.

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


COLUMNAS_CONTEXTO = ["fecha", "hora", "nov_impacto", "nov_sube", "festivo_oficial"]


@lru_cache(maxsize=2)
def _cargar_parquet_opcional(ruta_archivo: str, mtime: float) -> pd.DataFrame | None:
    if mtime < 0:
        return None
    d = pd.read_parquet(ruta_archivo)
    if "fecha" in d.columns:
        d["fecha"] = pd.to_datetime(d["fecha"]).dt.date
    return d


def _opcional(nombre: str) -> pd.DataFrame | None:
    archivo = carpeta_datos() / nombre
    mtime = archivo.stat().st_mtime if archivo.exists() else -1.0
    d = _cargar_parquet_opcional(str(archivo), mtime)
    return None if d is None else d.copy()


def huella_archivo(nombre: str) -> float:
    """mtime del archivo de datos (-1 si no existe): sirve de llave de caché para lo que se calcula con él."""
    archivo = carpeta_datos() / nombre
    return archivo.stat().st_mtime if archivo.exists() else -1.0


def contexto_operacional() -> pd.DataFrame:
    """Contexto conocido por adelantado por fecha y hora (variables fv2): nov_impacto (porcentaje_impacto de la novedad
    vial que cruza la hora, 0 si no hay), nov_sube (etiqueta SUBE) y festivo_oficial (FESTIVO_NACIONAL de
    estacionalidades_anio). Tabla vacía con esas columnas si falta datos/contexto_operacional.parquet."""
    d = _opcional("contexto_operacional.parquet")
    if d is None:
        return pd.DataFrame({c: pd.Series(dtype="float64" if c.startswith("nov_i") else "int64") for c in
                             COLUMNAS_CONTEXTO}).astype({"fecha": "object"})
    d["hora"] = d["hora"].astype(int)
    return d[COLUMNAS_CONTEXTO]


def perfil_intrahorario() -> pd.DataFrame:
    """Fracción de las subidas de la hora que viaja en los buses que salen entre h:00 y h:29, por ruta, tipo_dia (0, 1,
    2) y hora (viajes de 2024). Vacía si falta datos/perfil_intrahorario.parquet (se usa entonces el reparto 0,5)."""
    d = _opcional("perfil_intrahorario.parquet")
    if d is None:
        return pd.DataFrame(columns=["ruta", "tipo_dia", "hora", "fraccion_primera_media", "dias"])
    return d


def clima_diario() -> pd.DataFrame | None:
    """Lluvia diaria observada (solo para evaluar por condición; nunca es variable del pronóstico)."""
    return _opcional("clima_diario.parquet")


def limpiar_cache() -> None:
    _cargar_demanda.cache_clear()
    _cargar_catalogo.cache_clear()
    _cargar_parametros.cache_clear()
    _cargar_parquet_opcional.cache_clear()
