"""Datos de demanda y catálogo de rutas empaquetados con la API (carpeta datos/).

Todo sale de archivos del propio proyecto generados por scripts/preparar_datos_api.py (ver datos/origen.json):
- demanda_horaria.parquet: pasajeros y salidas por ruta, fecha y hora de salida (4-20 h), 2023-2025.
- catalogo_rutas.json: capacidad (50), tiempo de ciclo, flota y frecuencia actual por ruta.
- parametros_operativos_hora.parquet: los mismos parámetros por ruta, tipo de día y hora.
- contexto_operacional.parquet: novedades viales de todas las rutas por hora y festivos oficiales (variables fv2, se
  conocen antes).
- novedades_por_ruta.parquet: novedades viales de rutas dadas por ruta, fecha y hora (§11.2); solo existe si
  novedades_viales_ruta trae filas (en Sobusa no: cada novedad es de todas las rutas).
- perfil_intrahorario.parquet: reparto de las subidas entre la primera y la segunda media hora (ventanas 30/60/120).
- calendario_academico.csv: recesos de los colegios oficiales de Barranquilla y periodos de clases universitarias
  (variables fv3, se conocen antes; cada fila con su fuente).
- clima_diario.parquet: lluvia diaria observada, solo para evaluar por condición.
- ocupacion_segmentos_hora.parquet: ocupación histórica por segmento, día de operación y hora (§10.1), la que arma
  scripts/preparar_ocupacion_segmentos.py con las subidas y bajadas por segmento de cada viaje (2023-01-01 a
  2023-02-27).
- bajadas_horaria.parquet: bajadas_viajes (Σ numerobajadas de los viajes válidos) por ruta, fecha y hora de salida,
  2023-2025 (§6.1 Bajadas; la fuente offline la entrega con la serie y ALT-008 la usa).
Los siete últimos son opcionales: si faltan, las variables de contexto valen 0, las del calendario académico quedan
como dato faltante, el reparto intrahorario es 0,5, la recomendación no nombra el segmento crítico histórico y el lote
offline llega sin bajadas.

La carpeta se puede cambiar con la variable de entorno DATA_DIR (la misma de app/config.py).
No hay conexión a ninguna base de datos aquí: es la fuente offline y reproducible por defecto. La única excepción es
la frecuencia vigente de la ruta (ruta_info, frecuencia_vigente): en modo integrado la lee la capa de fuentes de la
tabla rutas de Extreme en solo lectura, con el catálogo empaquetado como respaldo.
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
    """La ruta del catálogo empaquetado (por nombre o por idruta) con su frecuencia vigente de rutas.frecuenciadespachos
    (frecuenciadespachos_tabla_rutas) y de dónde salió (frecuencia_vigente). KeyError si no existe."""
    for r in catalogo_rutas():
        if r["ruta"] == ruta or str(r["idruta"]) == str(ruta):
            return frecuencia_vigente(r)
    raise KeyError(f"Ruta desconocida: {ruta!r}. Rutas válidas: {[r['ruta'] for r in catalogo_rutas()]}")


FRECUENCIA_EMPAQUETADA = "catalogo_empaquetado"
FRECUENCIA_DE_LA_FUENTE = "fuente"


def _sin_valor(valor) -> bool:
    """Nulo, NaN, pd.NA o texto vacío (lo que trae una celda sin dato)."""
    return not valor.strip() if isinstance(valor, str) else bool(pd.isna(valor))


def _frecuencias_integradas() -> tuple[dict | None, str]:
    """({idruta: frecuenciadespachos}, detalle) de la fuente en modo integrado (FUENTE_DATABASE_URL, la de la capa
    analítica: app.servicios.fuentes.frecuencias_despacho, solo lectura); (None, motivo) en modo offline o si falla."""
    try:
        from app.servicios import fuentes, segmentos

        if not segmentos.fuente_configurada():
            return None, "modo offline (sin FUENTE_DATABASE_URL)"
        return fuentes.frecuencias_despacho(segmentos.fuente())
    except Exception as exc:  # noqa: BLE001 - sin la fuente rige el catálogo empaquetado
        return None, f"la fuente no se pudo abrir ({type(exc).__name__})"


def frecuencia_vigente(info: dict) -> dict:
    """§6.1 «frecuenciadespachos» y §6.2 «headway vigente» (su unidad es el supuesto S14, hallazgo H15). En modo
    integrado la frecuencia de la ruta es la de la tabla rutas de la base de Extreme, leída en solo lectura con la
    lista blanca de app/servicios/fuentes.py; si la fuente no responde, no trae la columna o no trae un valor para la
    ruta, rige la del catálogo empaquetado (datos/catalogo_rutas.json). Devuelve una copia de la ruta que dice de
    dónde salió: frecuencia_fuente («fuente» o «catalogo_empaquetado») y frecuencia_fuente_detalle (el motivo)."""
    valores, detalle = _frecuencias_integradas()
    salida = dict(info, frecuencia_fuente=FRECUENCIA_EMPAQUETADA)
    if valores is None:
        return dict(salida, frecuencia_fuente_detalle=f"{detalle}: rige el catálogo empaquetado")
    try:
        valor = valores.get(int(info["idruta"]))
    except (KeyError, TypeError, ValueError):
        valor = None
    if _sin_valor(valor):
        return dict(salida, frecuencia_fuente_detalle=f"{detalle}: sin valor para la ruta, rige el catálogo "
                                                      "empaquetado")
    return dict(salida, frecuenciadespachos_tabla_rutas=valor, frecuencia_fuente=FRECUENCIA_DE_LA_FUENTE,
                frecuencia_fuente_detalle=detalle)


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


@lru_cache(maxsize=8)
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


COLUMNAS_CALENDARIO_ACADEMICO = ["tipo", "inicio", "fin", "periodo", "fuente", "fuente_url", "confianza"]
TIPOS_CALENDARIO_ACADEMICO = ("escolar_receso", "universitario_clases")


@lru_cache(maxsize=4)
def _cargar_calendario_academico(ruta_archivo: str, mtime: float) -> pd.DataFrame | None:
    if mtime < 0:
        return None
    d = pd.read_csv(ruta_archivo, encoding="utf-8")
    d["inicio"] = pd.to_datetime(d["inicio"]).dt.date
    d["fin"] = pd.to_datetime(d["fin"]).dt.date
    return d


def calendario_academico() -> pd.DataFrame:
    """Calendario académico conocido por adelantado (variables fv3): una fila por periodo, con tipo `escolar_receso`
    (recesos de los colegios oficiales de Barranquilla) o `universitario_clases` (clases universitarias: mediana de
    inicio y fin entre las universidades de E10), sus fechas (inclusive) y su fuente. Tabla vacía con esas columnas si
    falta datos/calendario_academico.csv."""
    archivo = carpeta_datos() / "calendario_academico.csv"
    d = _cargar_calendario_academico(str(archivo), archivo.stat().st_mtime if archivo.exists() else -1.0)
    if d is None:
        return pd.DataFrame({c: pd.Series(dtype="object") for c in COLUMNAS_CALENDARIO_ACADEMICO})
    return d[COLUMNAS_CALENDARIO_ACADEMICO].copy()


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


COLUMNAS_NOVEDADES_RUTA = ["ruta", "fecha", "hora", "nov_impacto", "nov_sube"]


def novedades_por_ruta() -> pd.DataFrame:
    """§11.2 novedades viales de rutas dadas (novedades_viales_ruta con filas) por ruta, fecha y hora: nov_impacto y
    nov_sube solo en sus rutas (app/servicios/novedades.py). Vacía si falta datos/novedades_por_ruta.parquet, como en
    Sobusa, donde la tabla no trae filas y cada novedad es de todas las rutas (contexto_operacional)."""
    d = _opcional("novedades_por_ruta.parquet")
    if d is None:
        return pd.DataFrame({"ruta": pd.Series(dtype="object"), "fecha": pd.Series(dtype="object"),
                             "hora": pd.Series(dtype="int64"), "nov_impacto": pd.Series(dtype="float64"),
                             "nov_sube": pd.Series(dtype="int64")})
    d["hora"] = d["hora"].astype(int)
    return d[COLUMNAS_NOVEDADES_RUTA]


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


def ocupacion_segmentos_historica() -> pd.DataFrame | None:
    """§10.1 ocupación histórica por segmento (datos/ocupacion_segmentos_hora.parquet, app/servicios/ocupacion.py):
    carga a bordo media, P50, P90 y máxima por ruta, segmento, nivel (día de operación ISO o tipo de día), hora de
    salida y estacionalidad. None si el archivo no está."""
    return _opcional("ocupacion_segmentos_hora.parquet")


ARCHIVO_BAJADAS = "bajadas_horaria.parquet"
LLAVE_HORARIA = ["ruta", "fecha", "hora"]


def bajadas_horaria() -> pd.DataFrame | None:
    """§6.1 Bajadas: bajadas_viajes por ruta, fecha y hora de salida (4-20 h), 2023-2025 = Σ numerobajadas de los viajes
    válidos (finalizado 'S', no cancelado, dato <= 300, ceros incluidos), la definición de pasajeros aplicada a los
    descensos (scripts/preparar_datos_api.py --solo-bajadas). None si falta datos/bajadas_horaria.parquet."""
    d = _opcional(ARCHIVO_BAJADAS)
    if d is None:
        return None
    d["hora"] = d["hora"].astype(int)
    d["bajadas_viajes"] = d["bajadas_viajes"].astype(float)
    return d[[*LLAVE_HORARIA, "bajadas_viajes"]]


def con_bajadas(serie: pd.DataFrame) -> pd.DataFrame:
    """La serie horaria con bajadas_viajes (bajadas_horaria) por (ruta, fecha, hora); sin el archivo, o si la serie ya
    la trae, tal cual. Una hora sin dato queda nula (nunca se inventa un cero)."""
    bajadas = bajadas_horaria()
    if bajadas is None or "bajadas_viajes" in serie.columns or not len(serie):
        return serie
    return serie.merge(bajadas, on=LLAVE_HORARIA, how="left")


def limpiar_cache() -> None:
    from app.servicios import fuentes

    _cargar_demanda.cache_clear()
    _cargar_catalogo.cache_clear()
    _cargar_parametros.cache_clear()
    _cargar_parquet_opcional.cache_clear()
    fuentes.limpiar_frecuencias()
