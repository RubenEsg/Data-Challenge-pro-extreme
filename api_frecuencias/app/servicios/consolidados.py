"""Consolidados de Extreme en el ciclo diario: lectura incremental, calidad y contraste con la agregación propia
(especificación v1.5, §6.1, §6.3, §7.3 paso 3, §11.2; RF-004).

Tablas (lista blanca de fuentes.TABLAS_CON_MARCA, siempre en solo lectura):
- timbradas_consolidado: subidas, bajadas, nro_viajes, promedio_subidas, promedio_bajadas y ultima_actualizacion por
  proceso, ruta, día ISO, estacionalidad y bloque de 15 minutos. La escribe fn_consolidar_timbradas_historicas con los
  años cerrados de timbradas_anio (hasta el año anterior al de su ultima_actualizacion);
- timbradas_segmentos_anio y timbradas_segmentos_consolidado: lo mismo por segmento (y año), con pasajeros y
  promedio_pasajeros (§6.1 «prom_…_x_segmento», «nro_viajes» y «ultima_actualizacion» de esas dos tablas).

Cada ejecución del ciclo la hace UNA vez: la de todas las rutas o, partida por ruta (RNF-005), la madre al cerrar; con
la versión de umbrales de la ejecución (ejecucion.umbrales_de_la_ejecucion). Por cada tabla:
1. Lee desde SU marca de agua (ai_frecuencias.marca_agua_tabla, por proceso y tabla) con la regla exacta de siempre
   (fuentes.FuentePostgresSoloLectura: READ ONLY, statement_timeout, ventana de solape y huellas de contenido, que
   descartan el resellado sin cambios del cierre nocturno, hallazgo H7). Lee la base operacional configurada para la
   capa analítica (FUENTE_DATABASE_URL, la misma de app/servicios/segmentos.py); sin ella, lo dice y no lee.
2. Valida lo leído con calidad.validar_lote (esquemas consolidado, segmentos_anio y segmentos_consolidado): las seis
   dimensiones de §6.3, con CONS-001 (promedios coherentes con subidas, bajadas, pasajeros y nro_viajes), el segmento
   (REL-004 y REL-006) y el día de la semana (REL-007 y VAL-007, contra las fechas de su estacionalidad).
3. Contrasta las llaves que tocó lo leído con la agregación propia, con las tolerancias gobernadas de threshold_config
   (TOLERANCIAS_POR_DEFECTO, migración 0013):
   - timbradas_consolidado frente al histórico propio (demanda_observada: pasajeros, bajadas_viajes y salidas) por
     ruta × día ISO × estacionalidad, en el período del consolidado. No por hora: el consolidado asigna cada viaje al
     bloque de SU FIN (hallazgo H10) y el histórico a la hora de salida (en la réplica, el promedio por viaje por hora
     difiere 20,6 % en la mediana frente a la hora de salida y 1,3 % frente a la de fin; por día ISO y estacionalidad,
     1,4 %: docs/evidencias/consolidados/contraste_consolidados.md);
   - los dos de segmentos frente a la agregación materializada (segmento_estadistica_dia, la que deja el trabajo
     «segmentos») por segmento × (año) × día ISO × estacionalidad: promedios por viaje y viajes por día (CONTR-002).
     Tampoco por hora: fn_insert_timbradas_anio pone TODOS los segmentos de un viaje en el bloque de 15 minutos de su
     fin (H10 también en estas tablas) y la agregación propia, en la hora en que el bus pasó por cada segmento. Con
     filas reales de la liquidación, por hora la mayoría de las llaves no encuentra la agregación propia y salen
     diferencias groseras falsas; sin la hora, ninguna (docs/evidencias/consolidados/segmentos_filas_reales.json).
     Por hora solo queda el rango (CONTR-003: el promedio por viaje del bloque de Extreme dentro del [mínimo, máximo]
     propio de esa hora), que nunca bloquea porque el bloque de Extreme puede ser otro.
   Las medidas comparadas no dependen de cuántos días cubre cada lado: promedio de subidas, de bajadas y de pasajeros
   por viaje y viajes por día de operación. En timbradas_consolidado, los días de Extreme son los del calendario del
   período con ese día ISO y esa estacionalidad (la vigente de período más corto, como en fn_insert_timbradas_anio)
   frente a las fechas propias: los años cerrados de timbradas_anio están completos y el histórico propio puede ser
   más corto. En las de segmentos, los días de los dos lados son los de la agregación propia de la misma llave: las
   tablas de Extreme y segmento_estadistica_dia salen de timbradas_segmentos y cubren las mismas fechas, así que el
   calendario contaría días sin viajes de ningún lado (un año abierto o un histórico de segmentos que empieza a mitad
   de año) y daría diferencias groseras falsas; el año abierto de la anual (el de la marca más reciente de Extreme) no
   compara los viajes por día, porque el refresco propio puede ir un ciclo atrás.
4. Registra cada diferencia en data_quality_error (lote «id8:tabla», llave, campo, valor, detalle y bloqueante: no
   bloqueante sobre contraste_tolerancia; bloqueante, la llave queda fuera del análisis, sobre
   contraste_tolerancia_grosera) y deja la marca nueva en la MISMA transacción del ciclo: un intento revertido no la
   mueve. Si no hay filas para contrastar (hoy las dos tablas de segmentos de la réplica, hallazgo H4) el resumen lo
   dice explícitamente.
El resumen queda en las métricas de la ejecución (metricas.calidad.consolidados). Los consolidados no alimentan el
modelo (su objetivo es el histórico propio): «bloqueante» los marca como no aptos para el análisis, no los corrige.
"""
from __future__ import annotations

import logging
import math
import uuid
from collections import Counter
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.modelos_db import MarcaAguaTabla

log = logging.getLogger("api_frecuencias.consolidados")

TABLA_RUTA = "timbradas_consolidado"
TABLA_SEGMENTOS_ANIO = "timbradas_segmentos_anio"
TABLA_SEGMENTOS = "timbradas_segmentos_consolidado"
TABLAS = (TABLA_RUTA, TABLA_SEGMENTOS_ANIO, TABLA_SEGMENTOS)
PROCESO_TODOS = "*"
CLAVE_CONSOLIDADOS = 7_441_011    # pg_advisory_xact_lock: los consolidados de una ejecución a la vez en el clúster
# Valores de la migración 0013 (threshold_config); rigen si la versión de umbrales de la ejecución no los trae
TOLERANCIAS_POR_DEFECTO = {"contraste_tolerancia": 0.15, "contraste_tolerancia_grosera": 0.50,
                           "contraste_viajes_minimos": 30}
# Incidencias que se guardan por tabla y ejecución (primero las bloqueantes); el resumen cuenta todas
MAX_INCIDENCIAS_POR_TABLA = 2000
FECHA_MINIMA = date(1900, 1, 1)
CONSISTENCIA = "consistencia"
H4 = ("hallazgo H4: los scripts 5 y 6 de Extreme filtran el proceso «cootransoriente» y no llenan las tablas por "
      "segmento de Sobusa")
NOTA_H10 = ("por ruta × día ISO × estacionalidad y no por hora: el consolidado asigna cada viaje al bloque de su fin "
            "(hallazgo H10) y el histórico propio a la hora de salida")
NOTA_H10_SEGMENTOS = ("por segmento × día ISO × estacionalidad (y año en la anual) y no por hora: "
                      "fn_insert_timbradas_anio pone todos los segmentos de un viaje en el bloque de 15 minutos de su "
                      "fin (hallazgo H10) y la agregación propia, en la hora en que el bus pasó por cada segmento")
NOTA_RANGO = ("CONTR-003 por hora, no bloqueante: el bloque de 15 minutos de Extreme puede ser otro que la hora de "
              "paso de la agregación propia (hallazgo H10)")

# ---------------------------------------------------------------- SQL de la fuente (constantes; solo SELECT)
# Las dos de segmentos salen con la hora del bloque de Extreme: el contraste que puede bloquear la vuelve a sumar (H10)
# y el rango por hora (CONTR-003) la usa.
_SQL_FUENTE = {
    TABLA_RUTA: """
SELECT id_ruta, id_dia_semana, id_estacionalidad, SUM(subidas) AS subidas, SUM(bajadas) AS bajadas,
       SUM(nro_viajes) AS n, MAX(ultima_actualizacion) AS marca
  FROM timbradas_consolidado
 WHERE id_ruta = ANY(CAST(:ids AS bigint[]))
   AND (CAST(:proceso AS text) IS NULL OR proceso = CAST(:proceso AS text))
 GROUP BY id_ruta, id_dia_semana, id_estacionalidad
""",
    TABLA_SEGMENTOS_ANIO: """
SELECT t.id_segmento, t.ano, t.id_dia_semana, ea.id_estacionalidad,
       CAST(EXTRACT(HOUR FROM t.hora_inicio) AS integer) AS hora, SUM(t.subidas) AS subidas,
       SUM(t.bajadas) AS bajadas, SUM(t.pasajeros) AS pasajeros, SUM(t.nro_viajes) AS n,
       MAX(t.ultima_actualizacion) AS marca
  FROM timbradas_segmentos_anio t
  LEFT JOIN estacionalidades_anio ea ON ea.id_estacionalidad_anio = t.id_estacionalidad_anio
 WHERE t.id_segmento = ANY(CAST(:ids AS bigint[]))
   AND (CAST(:proceso AS text) IS NULL OR t.proceso = CAST(:proceso AS text))
 GROUP BY t.id_segmento, t.ano, t.id_dia_semana, ea.id_estacionalidad, CAST(EXTRACT(HOUR FROM t.hora_inicio) AS integer)
""",
    TABLA_SEGMENTOS: """
SELECT id_segmento, id_dia_semana, id_estacionalidad, CAST(EXTRACT(HOUR FROM hora_inicio) AS integer) AS hora,
       SUM(subidas) AS subidas, SUM(bajadas) AS bajadas, SUM(pasajeros) AS pasajeros, SUM(nro_viajes) AS n,
       MAX(ultima_actualizacion) AS marca
  FROM timbradas_segmentos_consolidado
 WHERE id_segmento = ANY(CAST(:ids AS bigint[]))
   AND (CAST(:proceso AS text) IS NULL OR proceso = CAST(:proceso AS text))
 GROUP BY id_segmento, id_dia_semana, id_estacionalidad, CAST(EXTRACT(HOUR FROM hora_inicio) AS integer)
""",
}
# Primer año que pueden cubrir los consolidados de años cerrados (el último es el anterior al de su marca)
_SQL_PRIMER_ANO = {
    TABLA_RUTA: ("SELECT min(ano) AS primer_ano FROM timbradas_anio "
                 "WHERE (CAST(:proceso AS text) IS NULL OR proceso = CAST(:proceso AS text))"),
    TABLA_SEGMENTOS: ("SELECT min(ano) AS primer_ano FROM timbradas_segmentos_anio "
                      "WHERE (CAST(:proceso AS text) IS NULL OR proceso = CAST(:proceso AS text))"),
}

# ---------------------------------------------------------------- agregación propia (esquema ai_frecuencias)
_SQL_PROPIA_RUTA = text("""
SELECT idruta AS id_ruta, id_dia_semana, id_estacionalidad, SUM(pasajeros) AS subidas, SUM(bajadas_viajes) AS bajadas,
       SUM(salidas) AS n, SUM(salidas) FILTER (WHERE bajadas_viajes IS NOT NULL) AS n_bajadas,
       COUNT(DISTINCT fecha) AS dias
  FROM ai_frecuencias.demanda_observada
 WHERE idruta = ANY(CAST(:ids AS integer[])) AND fecha >= :desde AND fecha <= :hasta
 GROUP BY idruta, id_dia_semana, id_estacionalidad
""")
# La misma agregación materializada de segmentos (grano diario segmento × fecha × hora, medidas sumables) en los dos
# granos del contraste: sin la hora (el que puede bloquear) y con ella (el rango, CONTR-003). Los días propios de la
# llave son sus fechas distintas: sin la hora, una fecha trae una fila por cada hora de paso. La anual agrupa además
# por año.
_PLANTILLA_PROPIA_SEGMENTOS = """
SELECT id_segmento{ano_columna}, id_dia_semana, id_estacionalidad{hora}, SUM(nro_viajes) AS n,
       SUM(suma_subidas) AS subidas, SUM(suma_bajadas) AS bajadas, SUM(suma_pasajeros) AS pasajeros,
       COUNT(DISTINCT fecha) AS dias,
       MIN(min_subidas) AS min_subidas, MAX(max_subidas) AS max_subidas, MIN(min_bajadas) AS min_bajadas,
       MAX(max_bajadas) AS max_bajadas, MIN(min_pasajeros) AS min_pasajeros, MAX(max_pasajeros) AS max_pasajeros
  FROM ai_frecuencias.segmento_estadistica_dia
 WHERE id_segmento = ANY(CAST(:ids AS bigint[])) AND fecha >= :desde AND fecha <= :hasta
 GROUP BY id_segmento{ano_grupo}, id_dia_semana, id_estacionalidad{hora}
"""
_ANO = "CAST(EXTRACT(YEAR FROM fecha) AS integer)"
_HORA = ", hora"


def _propia_de_segmentos(por_ano: bool, hora: str = ""):
    """La agregación propia de una tabla por segmento (constantes del módulo; `hora` es "" o _HORA)."""
    return text(_PLANTILLA_PROPIA_SEGMENTOS.format(ano_columna=f", {_ANO} AS ano" if por_ano else "",
                                                   ano_grupo=f", {_ANO}" if por_ano else "", hora=hora))


_SQL_PROPIA = {
    TABLA_RUTA: _SQL_PROPIA_RUTA,
    TABLA_SEGMENTOS_ANIO: _propia_de_segmentos(por_ano=True),
    TABLA_SEGMENTOS: _propia_de_segmentos(por_ano=False),
}
_SQL_PROPIA_POR_HORA = {
    TABLA_SEGMENTOS_ANIO: _propia_de_segmentos(por_ano=True, hora=_HORA),
    TABLA_SEGMENTOS: _propia_de_segmentos(por_ano=False, hora=_HORA),
}
# Columnas normalizadas de los dos lados del contraste (las que falten, NaN): sumas, y en la propia el rango por viaje
SUMAS = ("n", "n_bajadas", "subidas", "bajadas", "pasajeros", "dias")
RANGO = ("min_subidas", "max_subidas", "min_bajadas", "max_bajadas", "min_pasajeros", "max_pasajeros")


@dataclass(frozen=True)
class Medida:
    """Una medida del contraste: numerador / denominador en cada lado (mismas columnas normalizadas) y el piso del
    denominador de la diferencia relativa."""

    campo: str
    numerador: str
    denominador: str
    piso: float = 1.0


MEDIDAS_RUTA = (Medida("promedio_subidas", "subidas", "n"), Medida("promedio_bajadas", "bajadas", "n_bajadas"),
                Medida("viajes_por_dia", "n", "dias"))
MEDIDAS_SEGMENTO = (Medida("promedio_subidas", "subidas", "n"), Medida("promedio_bajadas", "bajadas", "n"),
                    Medida("promedio_pasajeros", "pasajeros", "n"), Medida("viajes_por_dia", "n", "dias"))


@dataclass(frozen=True)
class Tabla:
    """Cómo se lee, se valida y se contrasta una tabla consolidada de Extreme."""

    nombre: str
    esquema: str                     # calidad.ESQUEMAS
    codigo: str                      # código del contraste en data_quality_error
    tocadas: str                     # columna de lo leído que define las llaves a contrastar
    grano: tuple[str, ...]           # llave de la comparación que puede bloquear: sin la hora del bloque (H10)
    medidas: tuple[Medida, ...]
    propia: str                      # de dónde sale la agregación propia (texto del resumen)
    nota: str                        # por qué ese grano (texto del resumen)
    grano_rango: tuple[str, ...] = ()    # CONTR-003, no bloqueante: el grano y la hora; vacío, no se mira el rango
    por_ano: bool = False            # el período es el año de cada fila (timbradas_segmentos_anio)
    dias_propios: bool = False       # viajes por día con los días de la agregación propia (misma fuente en los dos)


PROPIA_SEGMENTOS = "segmento_estadistica_dia (agregación materializada del trabajo «segmentos»)"
GRANO_SEGMENTOS = ("id_segmento", "id_dia_semana", "id_estacionalidad")
GRANO_SEGMENTOS_ANIO = ("id_segmento", "ano", "id_dia_semana", "id_estacionalidad")
CONFIG = {
    TABLA_RUTA: Tabla(TABLA_RUTA, "consolidado", "CONTR-001", "id_ruta",
                      ("id_ruta", "id_dia_semana", "id_estacionalidad"), MEDIDAS_RUTA,
                      "demanda_observada (pasajeros, bajadas_viajes y salidas)", NOTA_H10),
    TABLA_SEGMENTOS_ANIO: Tabla(TABLA_SEGMENTOS_ANIO, "segmentos_anio", "CONTR-002", "id_segmento",
                                GRANO_SEGMENTOS_ANIO, MEDIDAS_SEGMENTO, PROPIA_SEGMENTOS, NOTA_H10_SEGMENTOS,
                                grano_rango=(*GRANO_SEGMENTOS_ANIO, "hora"), por_ano=True, dias_propios=True),
    TABLA_SEGMENTOS: Tabla(TABLA_SEGMENTOS, "segmentos_consolidado", "CONTR-002", "id_segmento",
                           GRANO_SEGMENTOS, MEDIDAS_SEGMENTO, PROPIA_SEGMENTOS, NOTA_H10_SEGMENTOS,
                           grano_rango=(*GRANO_SEGMENTOS, "hora"), dias_propios=True),
}
DIAS_CALENDARIO = "calendario del período (día ISO y estacionalidad vigente)"
DIAS_PROPIOS = ("los de la agregación propia de la misma llave (los dos lados salen de timbradas_segmentos); el año "
                "abierto de la anual no se compara")


# ---------------------------------------------------------------- tolerancias gobernadas (§5.1, threshold_config)
def tolerancias_de(umbrales: dict | None) -> dict[str, float]:
    """Las tolerancias del contraste de la versión de umbrales de la ejecución; las que falten o no sean números
    positivos, las de TOLERANCIAS_POR_DEFECTO."""
    salida = dict(TOLERANCIAS_POR_DEFECTO)
    for nombre in salida:
        try:
            valor = float((umbrales or {})[nombre])
        except (KeyError, TypeError, ValueError):
            continue
        if math.isfinite(valor) and valor > 0:
            salida[nombre] = valor
    return salida


def _numero(nombre: str, valor: Any) -> float:
    """El valor de una tolerancia como número finito; si no lo es, ValueError con el nombre (la API responde 422)."""
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        raise ValueError(f"{nombre} debe ser un número; se recibió {valor!r}") from None
    if not math.isfinite(numero):
        raise ValueError(f"{nombre} debe ser un número finito; se recibió {valor!r}")
    return numero


def validar_tolerancias(valores: dict[str, Any]) -> None:
    """PUT /thresholds: 0 < contraste_tolerancia <= contraste_tolerancia_grosera <= 10 y contraste_viajes_minimos un
    entero >= 1. Lanza ValueError con el motivo (la API responde 422)."""
    if not set(TOLERANCIAS_POR_DEFECTO) & set(valores):
        return
    t = {n: _numero(n, valores.get(n, v)) for n, v in TOLERANCIAS_POR_DEFECTO.items()}
    if not 0 < t["contraste_tolerancia"] <= t["contraste_tolerancia_grosera"] <= 10:
        raise ValueError("Las tolerancias del contraste deben cumplir 0 < contraste_tolerancia <= "
                         "contraste_tolerancia_grosera <= 10")
    if t["contraste_viajes_minimos"] < 1 or not float(t["contraste_viajes_minimos"]).is_integer():
        raise ValueError("contraste_viajes_minimos debe ser un entero >= 1")


# ---------------------------------------------------------------- calendario del período (viajes por día)
def vigencias_del_proceso(tabla: pd.DataFrame | None, proceso: str | None) -> list[tuple]:
    """(id_estacionalidad, desde, hasta) de estacionalidades_anio del proceso (todas si es None), en el orden con que
    fn_insert_timbradas_anio elige la vigente de una fecha: período más corto, inicio más reciente, id mayor."""
    if tabla is None or not len(tabla):
        return []
    filas = []
    for f in tabla.to_dict("records"):
        if proceso is not None and f.get("proceso") not in (None, proceso):
            continue
        desde, hasta = pd.Timestamp(f["fecha_inicio"]).date(), pd.Timestamp(f["fecha_fin"]).date()
        if pd.notna(f.get("id_estacionalidad")) and desde <= hasta:
            filas.append(((hasta - desde).days, -desde.toordinal(), -int(f.get("id_estacionalidad_anio") or 0),
                          int(f["id_estacionalidad"]), desde, hasta))
    return [(e, d, h) for *_orden, e, d, h in sorted(filas)]


def dias_calendario(desde: date, hasta: date, vigencias: list[tuple]) -> Counter:
    """{(año, día ISO, id_estacionalidad): días} de [desde, hasta]; cada fecha con la estacionalidad vigente (la
    primera de `vigencias` que la contiene) o None si ninguna."""
    conteo: Counter = Counter()
    dia = desde
    while dia <= hasta:
        est = next((e for e, d, h in vigencias if d <= dia <= h), None)
        conteo[(dia.year, dia.isoweekday(), est)] += 1
        dia += timedelta(days=1)
    return conteo


def _con_dias(ext: pd.DataFrame, cfg: Tabla, periodo: tuple[date, date] | None, vigencias: list[tuple]) -> None:
    """Días del calendario de cada llave de Extreme (columna «dias»): los del período (o del año de la fila en la tabla
    anual) con ese día ISO y esa estacionalidad. Sin período ni vigencias, NaN: los viajes por día no se comparan."""
    if not len(ext) or (periodo is None and not cfg.por_ano) or not vigencias:
        ext["dias"] = math.nan
        return
    if cfg.por_ano:
        anos = [int(a) for a in ext["ano"].dropna().unique()]
        conteo = sum((dias_calendario(date(a, 1, 1), date(a, 12, 31), vigencias) for a in anos), Counter())
        claves = zip(ext["ano"], ext["id_dia_semana"], ext["id_estacionalidad"], strict=True)
        ext["dias"] = [conteo.get((_entero(a), _entero(d), _entero(e)), 0) for a, d, e in claves]
        return
    conteo = Counter()
    for (_ano, d, e), n in dias_calendario(periodo[0], periodo[1], vigencias).items():
        conteo[(d, e)] += n
    claves = zip(ext["id_dia_semana"], ext["id_estacionalidad"], strict=True)
    ext["dias"] = [conteo.get((_entero(d), _entero(e)), 0) for d, e in claves]


def _entero(valor) -> int | None:
    if valor is None or (isinstance(valor, float) and math.isnan(valor)) or valor is pd.NA:
        return None
    return int(valor)


def ano_abierto(ext: pd.DataFrame) -> int | None:
    """El año de la marca más reciente de las filas de Extreme: en timbradas_segmentos_anio, el año en curso."""
    if not len(ext) or "marca" not in ext.columns:
        return None
    marca = pd.to_datetime(ext["marca"], errors="coerce").max()
    return None if pd.isna(marca) else int(marca.year)


def _dias_propios(ext: pd.DataFrame, cfg: Tabla, propia: pd.DataFrame, abierto: int | None = None) -> None:
    """Tablas por segmento (cfg.dias_propios): los días de cada llave de Extreme (columna «dias») son los de la misma
    llave en la agregación propia (en el grano efectivo, después de sin_estacionalidad): sus fechas distintas, sin la
    hora, porque el bloque de Extreme es el del fin del viaje y no la hora de paso (H10). timbradas_segmentos_anio y
    _consolidado (script 6 y fn_insert_timbradas_anio) y segmento_estadistica_dia salen de timbradas_segmentos y cubren
    las mismas fechas: el calendario contaría días sin viajes de ningún lado (el año en curso o un histórico de
    segmentos que empieza a mitad de año) y daría diferencias groseras falsas. En la anual, el año abierto (`abierto`,
    el de la marca más reciente de Extreme) queda en NaN: el refresco propio puede ir un ciclo atrás y los viajes por
    día de ese año no se comparan (sus promedios por viaje, sí)."""
    if not len(ext) or not len(propia):
        ext["dias"] = math.nan
        return
    grano = list(cfg.grano)
    dias_propia = normalizar_lado(propia, cfg.grano, True)[[*grano, "dias"]]
    ext["dias"] = normalizar_lado(ext, cfg.grano, False)[grano].merge(dias_propia, on=grano, how="left")[
        "dias"].to_numpy()
    if cfg.por_ano and abierto is not None:
        ext.loc[(pd.to_numeric(ext["ano"], errors="coerce") >= abierto).to_numpy(), "dias"] = math.nan


# ---------------------------------------------------------------- contraste (puro, sin base)
@dataclass
class Contraste:
    """Resultado del contraste de una tabla: incidencias (filas de data_quality_error) y conteos del resumen."""

    incidencias: list[dict]
    resumen: dict


def _relativa(ext: pd.Series, propia: pd.Series, piso: float) -> pd.Series:
    return (ext - propia).abs() / propia.abs().clip(lower=piso)


def _llave(fila: dict, grano: tuple[str, ...], proceso: str | None) -> dict:
    llave = {c: _entero(fila.get(c)) for c in grano}
    if proceso is not None:
        llave["proceso"] = proceso
    return llave


def _incidencias_de_medida(m: pd.DataFrame, med: Medida, cfg: Tabla, tol: dict, lote: str,
                           proceso: str | None) -> list[dict]:
    """Las llaves cuya medida difiere más que contraste_tolerancia (bloqueante si supera la grosera)."""
    ext = m[f"{med.numerador}_ext"] / m[f"{med.denominador}_ext"].where(m[f"{med.denominador}_ext"] > 0)
    propia = m[f"{med.numerador}_propia"] / m[f"{med.denominador}_propia"].where(m[f"{med.denominador}_propia"] > 0)
    rel = _relativa(ext, propia, med.piso)
    sobre = rel > tol["contraste_tolerancia"]
    salida = []
    for i in m.index[sobre.fillna(False).to_numpy()]:
        grosera = bool(rel[i] > tol["contraste_tolerancia_grosera"])
        salida.append({
            "lote": lote, "fila": None, "llave": _llave(m.loc[i].to_dict(), cfg.grano, proceso), "campo": med.campo,
            "valor": f"{ext[i]:.4f}", "codigo": cfg.codigo, "dimension": CONSISTENCIA, "bloqueante": grosera,
            "detalle": (f"{med.campo} = {ext[i]:.2f} en {cfg.nombre} frente a {propia[i]:.2f} de la agregación propia "
                        f"({cfg.propia}): diferencia {rel[i]:.1%} (tolerancia {tol['contraste_tolerancia']:.0%}"
                        + (f"; grosera desde {tol['contraste_tolerancia_grosera']:.0%}: la llave queda fuera del "
                           "análisis)" if grosera else ")"))})
    return salida


def _incidencias_de_rango(m: pd.DataFrame, cfg: Tabla, lote: str, proceso: str | None) -> list[dict]:
    """CONTR-003 (§11.2 «máximos y mínimos … y rango horario»): el promedio por viaje de Extreme fuera del rango
    [mínimo, máximo] que la agregación propia vio en la llave y la hora (no bloqueante: el bloque de Extreme puede ser
    otro, hallazgo H10)."""
    salida = []
    for medida in ("subidas", "bajadas", "pasajeros"):
        prom = m[f"{medida}_ext"] / m["n_ext"].where(m["n_ext"] > 0)
        fuera = (prom < m[f"min_{medida}"] - 0.005) | (prom > m[f"max_{medida}"] + 0.005)
        for i in m.index[fuera.fillna(False).to_numpy()]:
            salida.append({
                "lote": lote, "fila": None, "llave": _llave(m.loc[i].to_dict(), cfg.grano_rango, proceso),
                "campo": f"promedio_{medida}", "valor": f"{prom[i]:.4f}", "codigo": "CONTR-003",
                "dimension": CONSISTENCIA, "bloqueante": False,
                "detalle": (f"promedio_{medida} = {prom[i]:.2f} en {cfg.nombre} está fuera del rango por viaje de la "
                            f"agregación propia [{m.at[i, f'min_{medida}']:g}, {m.at[i, f'max_{medida}']:g}] de esa "
                            "hora (no bloquea: el bloque de Extreme puede ser otro, hallazgo H10)")})
    return salida


def _filtrar_pocos(m: pd.DataFrame, minimos: float) -> tuple[pd.DataFrame, int]:
    """Las llaves con al menos `minimos` viajes en los dos lados (las demás no se comparan: su promedio es ruido)."""
    suficientes = (m["n_ext"] >= minimos) & (m["n_propia"] >= minimos)
    return m[suficientes], int((~suficientes).sum())


def normalizar_lado(df: pd.DataFrame, grano: tuple[str, ...], propia: bool) -> pd.DataFrame:
    """Un lado del contraste con todas sus columnas (las que falten, NaN), en float. En Extreme n_bajadas = n (sus
    viajes cuentan para las dos medidas); en la propia, sin n_bajadas, también (los segmentos)."""
    columnas = [*grano, *SUMAS, *(RANGO if propia else ())]
    d = df.reindex(columns=columnas).copy()
    for c in columnas:
        d[c] = pd.to_numeric(d[c], errors="coerce")
    if not propia or d["n_bajadas"].isna().all():
        d["n_bajadas"] = d["n"]
    return d


def _cruce(ext: pd.DataFrame, propia: pd.DataFrame, grano: tuple[str, ...], tol: dict) -> tuple[pd.DataFrame, dict]:
    """Los dos lados unidos por `grano`: las llaves comparables (con agregación propia y contraste_viajes_minimos
    viajes en cada lado) y los conteos del resumen (llaves de Extreme, comparadas, sin agregación propia y con pocos
    viajes)."""
    m = normalizar_lado(ext, grano, False).merge(normalizar_lado(propia, grano, True), on=list(grano), how="left",
                                                 suffixes=("_ext", "_propia"))
    con_propia = m["n_propia"].notna()
    comparables, pocos = _filtrar_pocos(m[con_propia], tol["contraste_viajes_minimos"])
    return comparables, {"grano": list(grano), "llaves": int(len(m)), "comparadas": int(len(comparables)),
                         "sin_agregacion_propia": int((~con_propia).sum()), "pocos_viajes": pocos}


def contrastar(ext: pd.DataFrame, propia: pd.DataFrame, cfg: Tabla, tolerancias: dict, lote: str,
               proceso: str | None = None) -> Contraste:
    """Contraste puro de las llaves de Extreme (`ext`, ya sumados sus bloques) con la agregación propia (`propia`) en
    cfg.grano: el grano y las columnas de SUMAS (n = viajes, subidas, bajadas, pasajeros, dias, n_bajadas). Es la
    comparación que puede bloquear. Devuelve las incidencias y el resumen (llaves, comparadas, sin agregación propia,
    con pocos viajes, diferencias, groseras y llaves bloqueadas)."""
    tol = tolerancias_de(tolerancias)
    comparables, conteos = _cruce(ext, propia, cfg.grano, tol)
    incidencias = [i for med in cfg.medidas for i in _incidencias_de_medida(comparables, med, cfg, tol, lote,
                                                                              proceso)]
    resumen = conteos | {
        "diferencias": len(incidencias), "groseras": sum(1 for i in incidencias if i["bloqueante"]),
        "llaves_bloqueadas": len({tuple(sorted(i["llave"].items())) for i in incidencias if i["bloqueante"]}),
        "por_campo": dict(Counter(i["campo"] for i in incidencias)), "tolerancias": tol}
    return Contraste(incidencias, resumen)


def contrastar_rango(ext: pd.DataFrame, propia: pd.DataFrame, cfg: Tabla, tolerancias: dict, lote: str,
                     proceso: str | None = None) -> Contraste:
    """CONTR-003 puro, en cfg.grano_rango (el grano y la hora): el promedio por viaje de cada bloque de Extreme (`ext`,
    sus bloques de 15 minutos sumados por hora) frente al rango [mínimo, máximo] por viaje de la agregación propia de
    esa hora (`propia`, con RANGO). Nunca bloquea: con filas de fn_insert_timbradas_anio el bloque es el del fin del
    viaje y no la hora de paso (H10), así que una llave sin agregación propia en esa hora solo se cuenta."""
    tol = tolerancias_de(tolerancias)
    comparables, conteos = _cruce(ext, propia, cfg.grano_rango, tol)
    incidencias = _incidencias_de_rango(comparables, cfg, lote, proceso)
    return Contraste(incidencias, conteos | {"fuera_de_rango": len(incidencias),
                                            "por_campo": dict(Counter(i["campo"] for i in incidencias)),
                                            "nota": NOTA_RANGO})


def _reagrupar(df: pd.DataFrame, grano: tuple[str, ...]) -> pd.DataFrame:
    """Suma un lado sin una de sus columnas de grano: sumas con suma, mínimos con mínimo y máximos con máximo. Una suma
    sin ningún valor sigue nula, como SUM en SQL: una medida que Extreme trae nula en todos los bloques de una llave no
    se compara (sumada como 0 daría una diferencia grosera falsa; la falta del dato la reporta la calidad de §6.3)."""
    sumas = [c for c in SUMAS if c in df.columns]
    rangos = {c: ("min" if c.startswith("min_") else "max") for c in RANGO if c in df.columns}
    if not len(df):
        return df.reindex(columns=[*grano, *sumas, *rangos])
    grupos = df.groupby(list(grano), dropna=False)
    partes = [grupos[sumas].sum(min_count=1)]
    if rangos:
        partes.append(grupos[list(rangos)].agg(rangos))
    return pd.concat(partes, axis=1).reset_index()


def _sin_estacionalidad_en(grano: tuple[str, ...], ext: pd.DataFrame,
                           propia: pd.DataFrame) -> tuple[tuple[str, ...], pd.DataFrame, pd.DataFrame]:
    """El grano y los dos lados sin id_estacionalidad si la agregación propia no trae ninguna (H1); si no, iguales."""
    if not len(propia) or "id_estacionalidad" not in propia.columns or propia["id_estacionalidad"].notna().any():
        return grano, ext, propia
    sin = tuple(c for c in grano if c != "id_estacionalidad")
    return sin, _reagrupar(ext, sin), _reagrupar(propia, sin)


def sin_estacionalidad(cfg: Tabla, ext: pd.DataFrame, propia: pd.DataFrame) -> tuple[Tabla, pd.DataFrame,
                                                                                       pd.DataFrame]:
    """Si la agregación propia no trae ninguna estacionalidad (histórico sin estacionalidades de Sobusa, hallazgo H1),
    el contraste se hace sin ella: los dos lados se vuelven a sumar sin esa columna (los días también, porque cada
    fecha tiene una sola estacionalidad)."""
    grano, ext, propia = _sin_estacionalidad_en(cfg.grano, ext, propia)
    return (cfg if grano == cfg.grano else replace(cfg, grano=grano)), ext, propia


def sin_estacionalidad_del_rango(cfg: Tabla, ext: pd.DataFrame, propia: pd.DataFrame) -> tuple[Tabla, pd.DataFrame,
                                                                                                 pd.DataFrame]:
    """Lo mismo para el rango por hora (CONTR-003): la tabla con su grano_rango sin la estacionalidad, y los dos lados
    vueltos a sumar sin ella, si la agregación propia no trae ninguna (H1)."""
    grano, ext, propia = _sin_estacionalidad_en(cfg.grano_rango, ext, propia)
    return (cfg if grano == cfg.grano_rango else replace(cfg, grano_rango=grano)), ext, propia


# ---------------------------------------------------------------- lectura de la fuente y del esquema propio
def fuente_de_la_tabla(tabla: str):
    """La lectura de solo lectura de `tabla` con la base operacional de la capa analítica (FUENTE_DATABASE_URL, la de
    app/servicios/segmentos.py); None si no está configurada."""
    from app.servicios import segmentos

    if not segmentos.fuente_configurada():
        return None
    return segmentos.fuente().para_tabla(tabla)


def _proceso(fuente) -> str:
    return getattr(fuente, "proceso", None) or PROCESO_TODOS


def _uno(df: pd.DataFrame, columna: str):
    return df[columna].iloc[0] if len(df) and columna in df.columns else None


def _numerico(df: pd.DataFrame) -> pd.DataFrame:
    """Las columnas de conteos como float (la fuente devuelve Decimal en las sumas)."""
    for c in df.columns:
        if c != "marca":
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def _periodo(fuente, cfg: Tabla, ext: pd.DataFrame) -> tuple[date, date] | None:
    """[1 de enero del primer año de la fuente anual, 31 de diciembre del año anterior a la marca más reciente]: los
    años cerrados que suma el consolidado (fn_consolidar_timbradas_historicas). None si no se puede saber."""
    if cfg.por_ano or cfg.nombre not in _SQL_PRIMER_ANO or not len(ext):
        return None
    marca = pd.to_datetime(ext["marca"], errors="coerce").max()
    primer = _uno(fuente.consultar(_SQL_PRIMER_ANO[cfg.nombre], {"proceso": fuente.proceso}), "primer_ano")
    if pd.isna(marca) or primer is None or pd.isna(primer):
        return None
    fin = date(int(marca.year) - 1, 12, 31)
    inicio = date(int(primer), 1, 1)
    return (inicio, fin) if inicio <= fin else None


def _agregado_fuente(fuente, cfg: Tabla, ids: list[int]) -> pd.DataFrame:
    """Las llaves tocadas sumadas en la fuente, en el grano de su SELECT (con la hora en las tablas por segmento)."""
    d = fuente.consultar(_SQL_FUENTE[cfg.nombre], {"ids": ids, "proceso": fuente.proceso})
    return _numerico(d) if len(d) else pd.DataFrame(columns=[*(cfg.grano_rango or cfg.grano), "subidas", "bajadas",
                                                             "pasajeros", "n", "marca"])


def _agregado_propio(s: Session, sql, grano: tuple[str, ...], ids: list[int],
                     periodo: tuple[date, date] | None) -> pd.DataFrame:
    """La agregación propia de las llaves tocadas con `sql` (_SQL_PROPIA o _SQL_PROPIA_POR_HORA), en `grano`."""
    desde, hasta = periodo or (FECHA_MINIMA, date.max)
    filas = s.execute(sql, {"ids": ids, "desde": desde, "hasta": hasta}).mappings().all()
    return _numerico(pd.DataFrame([dict(f) for f in filas], columns=None if filas else [*grano, "n"]))


# ---------------------------------------------------------------- marca de agua por tabla
def marca_de_la_tabla(s: Session, proceso: str, tabla: str) -> MarcaAguaTabla | None:
    return s.get(MarcaAguaTabla, (proceso, tabla))


def guardar_marca(s: Session, proceso: str, tabla: str, marca: datetime, estado: dict | None,
                  execution_id: uuid.UUID | None, filas: int) -> None:
    """Upsert de la marca de la tabla en la transacción del ciclo: nunca retrocede y, como marca_agua_ruta, su
    ejecución cambia solo si la movió (§9.5: la de la última ejecución exitosa que leyó algo nuevo)."""
    from sqlalchemy import case
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from app.servicios.ejecucion import json_seguro

    stmt = pg_insert(MarcaAguaTabla).values(proceso=proceso, tabla=tabla, marca_agua=marca, execution_id=execution_id,
                                            estado_fuente=json_seguro(estado) if estado else None, filas_leidas=filas)
    movida = stmt.excluded.marca_agua > MarcaAguaTabla.marca_agua
    stmt = stmt.on_conflict_do_update(
        index_elements=[MarcaAguaTabla.proceso, MarcaAguaTabla.tabla],
        set_={"marca_agua": stmt.excluded.marca_agua, "estado_fuente": stmt.excluded.estado_fuente,
              "execution_id": case((movida, stmt.excluded.execution_id), else_=MarcaAguaTabla.execution_id),
              "filas_leidas": stmt.excluded.filas_leidas, "actualizado_en": text("now()")},
        where=MarcaAguaTabla.marca_agua <= stmt.excluded.marca_agua)
    s.execute(stmt)


# ---------------------------------------------------------------- una tabla en el ciclo
@dataclass
class Paso:
    """Lo que el ciclo procesa de una tabla: su configuración, la fuente, la sesión y la ejecución."""

    cfg: Tabla
    fuente: Any
    s: Session
    execution_id: uuid.UUID
    tolerancias: dict
    catalogos: dict
    vigencias: list
    ahora: datetime

    @property
    def lote(self) -> str:
        return f"{self.execution_id.hex[:8]}:{self.cfg.nombre}"


def _iso(valor) -> str | None:
    if valor is None:
        return None
    return pd.Timestamp(valor).isoformat()


def _textos_de_llave(d: pd.DataFrame, llave: list[str]) -> pd.Series:
    """La llave de cada fila como texto (dos nulos se comparan iguales, como en drop_duplicates)."""
    return d[llave].astype(str).agg("|".join, axis=1)


def _con_las_llaves_repetidas(tabla: str, df: pd.DataFrame, repetidas: pd.DataFrame | None) -> pd.DataFrame:
    """§6.3 «Unicidad: reportar al responsable del consolidado; no corregir directamente» (6.3-06) también en la
    lectura incremental, que deduplica por la llave natural y entrega solo la fila más reciente de cada llave
    (fuentes._filtrar_huellas; resumen_lectura.duplicadas_llave). Aquí una llave repetida que la lectura ENTREGÓ (nueva
    o modificada) vuelve con todas las filas que trajo la fuente (fuentes.filas_de_llaves_repetidas): la calidad las
    marca UNI-001 sin elegir una y reportar_unicidad las informa al responsable, como las demás. Una llave repetida que
    la lectura no entregó (ya se entregó con la misma huella y la ventana de solape la vuelve a traer, como toda la
    tabla con un solo sello, H7) no vuelve: ya se reportó, y la tabla sigue «sin_cambios» en vez de reportarla en cada
    ciclo. Con UNIQUE en la fuente solo pasa con columnas nulas en la llave."""
    from app.servicios import fuentes

    if repetidas is None or not len(repetidas) or not len(df):
        return df
    llave = fuentes.llave_de_la_lectura(tabla, repetidas)
    entregadas = _textos_de_llave(df, llave)
    repetidas = repetidas[_textos_de_llave(repetidas, llave).isin(set(entregadas))]
    if not len(repetidas):
        return df
    otras = df[~entregadas.isin(set(_textos_de_llave(repetidas, llave)))]
    return pd.concat([x for x in (otras, repetidas) if len(x)], ignore_index=True)


def _leer(paso: Paso) -> tuple[pd.DataFrame, datetime, MarcaAguaTabla | None]:
    """Lo nuevo o modificado de la tabla desde su marca (solape y huellas de fuentes.py), solo del proceso: la lectura
    lo filtra en el SQL (fuentes.TABLAS_CON_PROCESO), así que las filas de otros operadores no se leen, no entran en las
    huellas que se guardan en marca_agua_tabla.estado_fuente ni mueven la marca. El filtro de aquí solo cubre una fuente
    que no filtre en el SQL (un doble de prueba). Una llave que la lectura deduplicó vuelve con todas sus filas
    (_con_las_llaves_repetidas)."""
    from app.servicios import fuentes

    previa = marca_de_la_tabla(paso.s, _proceso(paso.fuente), paso.cfg.nombre)
    estado = previa.estado_fuente if previa is not None else None
    df, nueva = fuentes.leer_con_estado(paso.fuente, previa.marca_agua if previa else None, None, estado)
    df = _con_las_llaves_repetidas(paso.cfg.nombre, df, getattr(paso.fuente, "repetidas_por_llave", None))
    if paso.fuente.proceso and len(df) and "proceso" in df.columns:
        df = df[df["proceso"].astype(str) == paso.fuente.proceso].reset_index(drop=True)
    return df, nueva, previa


def _sin_filas(paso: Paso, previa: MarcaAguaTabla | None, lectura: dict) -> dict:
    """Nada que contrastar, decidido con lo que ya hizo la lectura y sin otra consulta a la fuente (en la base de
    Extreme no hay índice sobre proceso ni sobre ultima_actualizacion, hallazgo H12: un count(*) por tabla y proceso en
    cada ejecución sería un barrido completo de las tablas grandes por segmento):
    - sin marca previa y sin filas leídas: la lectura empezó en la marca inicial (toda la tabla, solo el proceso) y no
      trajo nada, así que la tabla no tiene filas del proceso con ultima_actualizacion (H4 en las de segmentos);
    - si no: la tabla ya entregó filas del proceso (o la ventana de solape solo trajo repetidas) y no cambió."""
    if previa is None and not lectura.get("leidas"):
        detalle = (f"{paso.cfg.nombre} no tiene filas del proceso {_proceso(paso.fuente)!r} para contrastar (la "
                   "lectura desde la marca inicial no trajo ninguna)" + (f" ({H4})." if paso.cfg.nombre != TABLA_RUTA
                                                                         else "."))
        return {"resultado": "sin_filas_fuente", "detalle": detalle}
    return {"resultado": "sin_cambios",
            "detalle": f"Sin filas nuevas ni modificadas desde la marca {_iso(previa.marca_agua if previa else None)}."}


def _rango_de(paso: Paso, leido: pd.DataFrame, ids: list[int], periodo: tuple[date, date] | None) -> Contraste:
    """CONTR-003 de una tabla por segmento: lo leído de Extreme, con la hora de su bloque, frente al rango por viaje de
    la agregación propia de esa hora (sin estacionalidad propia, H1, los dos lados se suman sin ella)."""
    cfg = paso.cfg
    propia = _agregado_propio(paso.s, _SQL_PROPIA_POR_HORA[cfg.nombre], cfg.grano_rango, ids, periodo)
    cfg_rango, ext, propia = sin_estacionalidad_del_rango(cfg, leido, propia)
    return contrastar_rango(ext, propia, cfg_rango, paso.tolerancias, paso.lote, paso.fuente.proceso)


def _contraste_de(paso: Paso, df: pd.DataFrame) -> Contraste:
    """Las llaves que tocó lo leído, sumadas en la fuente, frente a la agregación propia del mismo período. En las
    tablas por segmento, la comparación que puede bloquear suma los bloques de Extreme sin la hora (H10) y por hora solo
    queda el rango (CONTR-003, en resumen.por_hora), que no bloquea."""
    cfg = paso.cfg
    ids = sorted({int(x) for x in pd.to_numeric(df[cfg.tocadas], errors="coerce").dropna()})
    leido = _agregado_fuente(paso.fuente, cfg, ids)
    periodo = _periodo(paso.fuente, cfg, leido)
    abierto = ano_abierto(leido) if cfg.por_ano else None
    ext = _reagrupar(leido, cfg.grano) if cfg.grano_rango else leido
    propia = _agregado_propio(paso.s, _SQL_PROPIA[cfg.nombre], cfg.grano, ids, periodo)
    if not cfg.dias_propios:
        _con_dias(ext, cfg, periodo, paso.vigencias)
    cfg_efectiva, ext, propia = sin_estacionalidad(cfg, ext, propia)
    if cfg.dias_propios:           # en el grano efectivo: sin estacionalidad propia (H1) los días también se suman
        _dias_propios(ext, cfg_efectiva, propia, abierto)
    r = contrastar(ext, propia, cfg_efectiva, paso.tolerancias, paso.lote, paso.fuente.proceso)
    r.resumen.update(agregacion_propia=cfg.propia, periodo=[_iso(p) for p in periodo] if periodo else None,
                     ids=len(ids), dias_viajes_por_dia=DIAS_PROPIOS if cfg.dias_propios else DIAS_CALENDARIO,
                     nota=cfg.nota)
    if cfg_efectiva.grano != cfg.grano:
        r.resumen["nota_estacionalidad"] = ("el histórico propio no trae id_estacionalidad (hallazgo H1): se contrasta "
                                            "por día ISO, sumando las estacionalidades de los dos lados")
    if cfg.grano_rango:
        rango = _rango_de(paso, leido, ids, periodo)
        r.incidencias += rango.incidencias
        r.resumen["por_hora"] = rango.resumen
    return r


def _ordenar_incidencias(errores: list[dict]) -> list[dict]:
    """Primero las bloqueantes; a lo sumo MAX_INCIDENCIAS_POR_TABLA."""
    return sorted(errores, key=lambda e: not e.get("bloqueante"))[:MAX_INCIDENCIAS_POR_TABLA]


def _procesar_filas(paso: Paso, df: pd.DataFrame) -> dict:
    """Calidad (§6.3) y contraste de lo leído; guarda las incidencias en data_quality_error y, si hay llaves
    duplicadas (UNI-001), las reporta al responsable del consolidado (§6.3, ejecucion.reportar_unicidad: el mismo
    canal, el mismo formato y la misma transacción que el reporte del lote del ciclo; lote «id8:tabla»)."""
    from app.servicios import calidad
    from app.servicios.ejecucion import _guardar_errores, reportar_unicidad

    columnas = [c for c in df.columns if c not in ("tipo_llegada",) and not c.startswith("id_timbrada")]
    validos, errores = calidad.validar_lote(df[columnas], paso.lote, esquema=paso.cfg.esquema,
                                            catalogos=paso.catalogos, ahora=paso.ahora)
    contraste = _contraste_de(paso, df)
    todas = errores + contraste.incidencias
    guardadas = _ordenar_incidencias(todas)
    _guardar_errores(paso.s, paso.execution_id, paso.lote, guardadas)
    return {"resultado": "contrastado", "filas_validas": int(len(validos)),
            "errores_por_codigo": dict(Counter(e["codigo"] for e in todas)),
            "bloqueantes": sum(1 for e in todas if e.get("bloqueante")), "incidencias": len(todas),
            "registradas": len(guardadas), "contraste": contraste.resumen,
            **reportar_unicidad(paso.s, paso.execution_id, paso.lote, errores)}


def procesar_tabla(paso: Paso) -> dict:
    """Lee, valida y contrasta una tabla y deja su marca nueva (todo en la transacción del ciclo)."""
    df, nueva, previa = _leer(paso)
    lectura = {k: v for k, v in (getattr(paso.fuente, "resumen_lectura", None) or {}).items()
               if k in ("leidas", "entregadas", "nuevas", "tardias", "modificadas", "repetidas_solape",
                        "duplicadas_llave", "truncada")}
    base = {"marca_anterior": _iso(previa.marca_agua) if previa else None, "lectura": lectura,
            "filas": int(len(df))}
    resultado = _procesar_filas(paso, df) if len(df) else _sin_filas(paso, previa, lectura)
    if lectura.get("leidas"):
        guardar_marca(paso.s, _proceso(paso.fuente), paso.cfg.nombre, nueva, paso.fuente.estado_incremental,
                      paso.execution_id, int(lectura["leidas"]))
        base["marca_nueva"] = _iso(nueva)
    return base | resultado


# ---------------------------------------------------------------- el paso del ciclo
def _catalogos(fuente) -> tuple[dict, list]:
    """Catálogos de la calidad (rutas, procesos, estacionalidades, segmentos con su ruta, días) y las vigencias de
    estacionalidades_anio del proceso, leídos una vez para las tres tablas (solo lectura)."""
    from app.servicios import calidad

    catalogos = calidad.catalogos_desde_fuente(fuente)
    try:
        vigencias = vigencias_del_proceso(fuente.estacionalidades_anio(), fuente.proceso)
    except Exception as exc:  # noqa: BLE001 - sin vigencias no se comparan los viajes por día
        log.info("estacionalidades_anio no disponible para el contraste: %s", exc)
        vigencias = []
    return catalogos, vigencias


def _una_tabla(s: Session, tabla: str, execution_id: uuid.UUID, tolerancias: dict, comun: dict,
               fallos: list[dict]) -> dict:
    """Una tabla en su punto de guardado: si la fuente o la base fallan, se revierte solo lo de esa tabla, su marca no
    se mueve (la ejecución siguiente la vuelve a leer) y queda como fallo parcial de la ejecución."""
    fuente = fuente_de_la_tabla(tabla)
    if fuente is None:
        return {"resultado": "sin_fuente", "detalle": "FUENTE_DATABASE_URL no está definida: los consolidados de "
                                                      "Extreme no se leen (modo offline)."}
    try:
        if "catalogos" not in comun:
            comun["catalogos"], comun["vigencias"] = _catalogos(fuente)
        paso = Paso(CONFIG[tabla], fuente, s, execution_id, tolerancias, comun["catalogos"], comun["vigencias"],
                    comun["ahora"])
        with s.begin_nested():
            return procesar_tabla(paso)
    except Exception as exc:  # noqa: BLE001 - una tabla con problemas no detiene el ciclo
        log.warning("consolidado %s no procesado: %s", tabla, exc)
        fallos.append({"etapa": "consolidados", "tabla": tabla, "error": str(exc)[:500]})
        return {"resultado": "error", "detalle": f"{type(exc).__name__}: {str(exc)[:300]}"}


def en_ciclo(s: Session, execution_id: uuid.UUID, umbrales: dict | None, fallos: list[dict],
             ahora: datetime | None = None) -> dict:
    """§6.1, §6.3, §11.2: las tres tablas consolidadas de Extreme, una vez por ejecución, con las tolerancias de la
    versión de umbrales de la ejecución. Devuelve el resumen por tabla para metricas.calidad.consolidados.

    Con la base operacional configurada, toma primero un candado de asesoría de la transacción (CLAVE_CONSOLIDADOS):
    si dos ejecuciones cierran a la vez (la madre de un día y un ciclo sin partir), la segunda espera a que la primera
    confirme y lee desde la marca que esta dejó. El ciclo lo pide después del candado del modelo, como la madre: el
    orden de los candados es el mismo y no hay interbloqueo."""
    from app.servicios.ejecucion import ahora as reloj

    tolerancias = tolerancias_de(umbrales)
    comun: dict[str, Any] = {"ahora": ahora or reloj()}
    if fuente_de_la_tabla(TABLA_RUTA) is not None:
        s.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": CLAVE_CONSOLIDADOS})
    tablas = {t: _una_tabla(s, t, execution_id, tolerancias, comun, fallos) for t in TABLAS}
    return {"tablas": tablas, "tolerancias": tolerancias,
            "resultados": dict(Counter(r["resultado"] for r in tablas.values()))}


def marcas(s: Session) -> list[MarcaAguaTabla]:
    """Las marcas de agua de las tablas consolidadas (para consultas y pruebas)."""
    return list(s.scalars(select(MarcaAguaTabla).order_by(MarcaAguaTabla.proceso, MarcaAguaTabla.tabla)).all())


__all__ = ["CONFIG", "TABLAS", "TOLERANCIAS_POR_DEFECTO", "Contraste", "Medida", "Paso", "Tabla", "ano_abierto",
           "contrastar", "contrastar_rango", "dias_calendario", "en_ciclo", "fuente_de_la_tabla", "guardar_marca",
           "marca_de_la_tabla", "marcas", "procesar_tabla", "sin_estacionalidad", "tolerancias_de",
           "validar_tolerancias", "vigencias_del_proceso"]
