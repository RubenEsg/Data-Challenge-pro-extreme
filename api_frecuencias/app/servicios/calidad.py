"""Calidad del dato de cada lote leído (especificación v1.5, §6.3; RF-004).

validar_lote(df, lote_id, catalogos=None, ahora=None) revisa las seis dimensiones y devuelve (df_validos, errores).
Cada error lleva lote, fila (posición en el lote), llave (dict con las columnas llave del registro, para encontrarlo
sin depender del orden del lote), campo, valor (texto de la celda), codigo, dimension, detalle y bloqueante. Las filas
con un error bloqueante se rechazan (no pasan a la inferencia ni al histórico) y nunca se corrigen; el registro y su
causa quedan en data_quality_error. Los errores de oportunidad no son bloqueantes: son informativos y la alerta de
retraso es ALT-009 (frescura de la fuente). La tolerancia de un dato tardío (OPOR-001) es el mismo umbral de §5.1
«datos atrasados» de la versión vigente de threshold_config (retraso_maximo_de), no una cifra del código.

Se reconocen cuatro esquemas de lote:
- "demanda": la salida de FuenteParquet / datos.demanda_horaria() y de la lectura integrada demanda_segmentos
  [ruta, fecha, hora, pasajeros, salidas, ultima_actualizacion (+ idruta, subidas, bajadas, bajadas_viajes,
  viajes_con_timbradas, id_estacionalidad)];
- "consolidado": timbradas_consolidado de Extreme [proceso, id_ruta, id_dia_semana, id_estacionalidad, hora,
  hora_inicio, hora_fin, subidas, bajadas, nro_viajes, promedio_subidas, promedio_bajadas, ultima_actualizacion]. Su
  llave es la de 7 columnas del DDL (fuentes.LLAVES): bloques de 15 minutos con hora, hora_inicio y hora_fin de tipo
  time; hora_fin = 00:00 cierra el día (cuenta como 24:00);
- "segmentos_anio" y "segmentos_consolidado": timbradas_segmentos_anio y timbradas_segmentos_consolidado (la misma
  forma por segmento, con pasajeros y promedio_pasajeros, y ano e id_estacionalidad_anio en la anual). pasajeros puede
  ser negativo (hallazgo H9: diferencia de contadores acumulados): se valida como número, no como conteo >= 0. Se pide
  el esquema por su nombre: detectar_esquema no acepta filas por segmento.

CONS-001 acepta el promedio exacto (tolerancia del 1 %) y el que escribe fn_consolidar_timbradas_historicas,
CEIL(Σ / nro_viajes) (hallazgo H7): los dos son coherentes con subidas, bajadas y nro_viajes.

Validación relacional (§6.3, §8.3): contra los catálogos que recibe (rutas, idrutas, procesos, estacionalidades,
novedades, segmentos, segmentos_ruta, dias_semana, capacidades), leídos en solo lectura de la fuente con
catalogos_desde_fuente(fuente). Sin catálogos se usa el catálogo de rutas empaquetado (datos/catalogo_rutas.json), nunca
una lista fija en el código. §7.3 paso 3 (segmento y día de la semana): REL-004 (el segmento existe), REL-006 (es de la
ruta de la fila), REL-007 (el día existe en dias_semana) y VAL-007 (id_dia_semana es el día ISO de la fecha o, sin
fecha, uno de los días en que cae su estacionalidad según las fechas de estacionalidades_anio:
dias_por_estacionalidad). VAL-008: la hora es la del bloque que empieza en hora_inicio.
"""
from __future__ import annotations

import logging
import math
from datetime import UTC, datetime, time, timedelta

import numpy as np
import pandas as pd

from app.servicios.fuentes import LLAVES

log = logging.getLogger("api_frecuencias.calidad")

ZONA_OPERACION = "America/Bogota"
COLUMNAS_HORA = ("hora", "hora_inicio", "hora_fin")

_CONTEOS_CONSOLIDADO = ["subidas", "bajadas", "nro_viajes", "promedio_subidas", "promedio_bajadas"]
_OBLIGATORIOS_SEGMENTO = ["id_segmento", "proceso", "id_ruta", "id_dia_semana", "hora", "hora_inicio", "hora_fin",
                          "subidas", "bajadas", "pasajeros", "nro_viajes", "ultima_actualizacion"]
ESQUEMAS = {
    "demanda": {
        "obligatorios": ["ruta", "fecha", "hora", "pasajeros", "ultima_actualizacion"],
        "conteos": ["pasajeros", "salidas", "subidas", "bajadas", "bajadas_viajes", "viajes_con_timbradas"],
        "llave": ["ruta", "fecha", "hora"],
        "hora": "entera",
    },
    "consolidado": {
        "obligatorios": ["proceso", "id_ruta", "id_dia_semana", "id_estacionalidad", "hora", "hora_inicio",
                         "hora_fin", "subidas", "bajadas", "nro_viajes", "ultima_actualizacion"],
        "conteos": _CONTEOS_CONSOLIDADO,
        "llave": list(LLAVES["timbradas_consolidado"]),
        "hora": "tiempo",
    },
    "segmentos_anio": {
        "obligatorios": [*_OBLIGATORIOS_SEGMENTO, "ano", "id_estacionalidad_anio"],
        "conteos": _CONTEOS_CONSOLIDADO,
        "numericos": ["pasajeros", "promedio_pasajeros"],
        "llave": list(LLAVES["timbradas_segmentos_anio"]),
        "hora": "tiempo",
    },
    "segmentos_consolidado": {
        "obligatorios": [*_OBLIGATORIOS_SEGMENTO, "id_estacionalidad"],
        "conteos": _CONTEOS_CONSOLIDADO,
        "numericos": ["pasajeros", "promedio_pasajeros"],
        "llave": list(LLAVES["timbradas_segmentos_consolidado"]),
        "hora": "tiempo",
    },
}

RETRASO_MAXIMO = timedelta(days=2)          # por omisión: §5.1 datos atrasados, 2 × 1.440 min (retraso_maximo_de)
TOLERANCIA_PROMEDIO = 0.01                  # 1 % (y al menos 0,01) entre el promedio y subidas / nro_viajes
MARGEN_FUTURO = timedelta(minutes=5)        # reloj del servidor de Extreme frente al de la API
# Tipos de llegada (columna tipo_llegada de FuentePostgresSoloLectura) que no cuentan para OPOR-001: la marca dice
# cuándo se volvió a sellar el registro (recarga, fn_consolidar, hallazgo H7), no cuándo llegó el dato.
LLEGADAS_RESELLADAS = ("carga_inicial", "resellada")

COLUMNA_MARCA = "ultima_actualizacion"
VALIDEZ, CONSISTENCIA, OPORTUNIDAD, RELACIONAL = "validez", "consistencia", "oportunidad", "relacional"
VAL_TIPO = "VAL-006"                        # valor que no es del tipo esperado (número, fecha u hora)


def detectar_esquema(df):
    cols = set(df.columns)
    if "id_segmento" in cols:
        raise ValueError("Lote de timbradas_segmentos*: el ciclo procesa el esquema de demanda (FUENTE_TABLA="
                         "demanda_segmentos) o timbradas_consolidado, no filas por segmento.")
    if "pasajeros" in cols or "ruta" in cols:
        return "demanda"
    if "subidas" in cols or "id_ruta" in cols:
        return "consolidado"
    raise ValueError("No se reconoce el esquema del lote (se esperaba demanda horaria o timbradas_consolidado).")


def _a_utc(serie):
    s = pd.to_datetime(serie, errors="coerce", utc=False)
    if getattr(s.dt, "tz", None) is None:
        s = s.dt.tz_localize(ZONA_OPERACION, ambiguous="NaT", nonexistent="NaT")
    return s.dt.tz_convert("UTC")


def _hora_de(v) -> float:
    """Hora del día en horas decimales: número, datetime.time, timedelta o texto «HH:MM[:SS]»; NaN si no se puede."""
    if v is None or v is pd.NaT or (isinstance(v, float) and math.isnan(v)):
        return np.nan
    if isinstance(v, time):
        return v.hour + v.minute / 60 + (v.second + v.microsecond / 1e6) / 3600
    if isinstance(v, (pd.Timedelta, timedelta)):
        return v.total_seconds() / 3600
    if isinstance(v, (int, float, np.integer, np.floating)) and not isinstance(v, bool):
        return float(v)
    texto = str(v).strip()
    if ":" not in texto:
        try:
            return float(texto)
        except ValueError:
            return np.nan
    partes = texto.split(":")
    try:
        h, m = int(partes[0]), int(partes[1])
        s = float(partes[2]) if len(partes) > 2 else 0.0
    except (ValueError, IndexError):
        return np.nan
    if h < 0 or not (0 <= m < 60 and 0 <= s < 60):
        return np.nan
    return h + m / 60 + s / 3600


def horas(serie: pd.Series) -> pd.Series:
    """Serie de horas decimales (acepta columnas time de PostgreSQL, texto y números)."""
    if pd.api.types.is_numeric_dtype(serie) and not pd.api.types.is_bool_dtype(serie):
        return pd.to_numeric(serie, errors="coerce").astype(float)
    return pd.Series([_hora_de(v) for v in serie], index=serie.index, dtype=float)


def _texto(valor) -> str | None:
    """Valor de una celda como texto (None si falta): se guarda tal cual en data_quality_error.valor."""
    if isinstance(valor, np.generic):
        valor = valor.item()
    if valor is None or valor is pd.NaT or valor is pd.NA:
        return None
    if isinstance(valor, float):
        if math.isnan(valor):
            return None
        return str(int(valor)) if valor.is_integer() else repr(valor)
    if isinstance(valor, (datetime, pd.Timestamp, time)) or hasattr(valor, "isoformat"):
        return valor.isoformat()
    return str(valor)


def _simple(valor):
    """Valor JSON de una columna llave (número, texto o fecha/hora ISO)."""
    if isinstance(valor, np.generic):
        valor = valor.item()
    if valor is None or valor is pd.NaT or valor is pd.NA or (isinstance(valor, float) and math.isnan(valor)):
        return None
    if isinstance(valor, float) and valor.is_integer():
        return int(valor)
    if isinstance(valor, (int, float, str, bool)):
        return valor
    if hasattr(valor, "isoformat"):
        return valor.isoformat()
    return str(valor)


def catalogo_empaquetado() -> dict:
    """Rutas, idrutas y capacidades del catálogo empaquetado (datos/catalogo_rutas.json); vacío si no se puede leer."""
    try:
        from app.servicios import datos

        rutas = datos.catalogo_rutas()
    except Exception as exc:  # noqa: BLE001 - sin catálogo, la validación relacional de rutas no se puede hacer
        log.warning("Catálogo de rutas no disponible para la validación relacional: %s", exc)
        return {}
    return {"rutas": {r["ruta"] for r in rutas}, "idrutas": {int(r["idruta"]) for r in rutas},
            "capacidades": {r["ruta"]: r.get("capacidad") for r in rutas}}


def catalogos_desde_fuente(fuente=None) -> dict:
    """Catálogos de la validación relacional: el empaquetado y, encima, lo que la fuente lea en solo lectura
    (FuentePostgresSoloLectura.catalogos_calidad: rutas, procesos, estacionalidades, novedades y segmentos)."""
    cat = catalogo_empaquetado()
    leer = getattr(fuente, "catalogos_calidad", None)
    if leer is not None:
        try:
            cat.update({k: v for k, v in (leer() or {}).items() if v})
        except Exception as exc:  # noqa: BLE001 - se valida con el catálogo empaquetado y queda en el log
            log.warning("Catálogos de la fuente no disponibles; se usa el catálogo empaquetado: %s", exc)
    return cat


def _fecha_o_nada(valor):
    """date de una celda (date, datetime, Timestamp o texto ISO); None si falta o no es una fecha."""
    if valor is None or valor is pd.NaT or (isinstance(valor, float) and math.isnan(valor)):
        return None
    try:
        return pd.Timestamp(valor).date()
    except (TypeError, ValueError):
        return None


def _dias_iso(desde, hasta) -> frozenset:
    """Días ISO (1 = lunes … 7 = domingo) en que cae [desde, hasta]; los siete si el período dura una semana o más."""
    if desde is None or hasta is None or hasta < desde:
        return frozenset()
    largo = (hasta - desde).days
    if largo >= 6:
        return frozenset(range(1, 8))
    return frozenset((desde + timedelta(days=k)).isoweekday() for k in range(largo + 1))


def dias_por_estacionalidad(vigencias: pd.DataFrame | None) -> dict:
    """Catálogos de VAL-007 desde estacionalidades_anio (id_estacionalidad_anio, id_estacionalidad, fecha_inicio,
    fecha_fin): {"dias_estacionalidad": {id_estacionalidad: días ISO de todas sus fechas}, "dias_estacionalidad_anio":
    {id_estacionalidad_anio: días ISO de sus fechas}}. Un festivo de un día solo admite el día ISO de cada año; una
    temporada de una semana o más, los siete. Vacío sin filas."""
    if vigencias is None or not len(vigencias):
        return {}
    por_estacionalidad: dict[int, set] = {}
    por_anio: dict[int, frozenset] = {}
    for fila in vigencias.to_dict("records"):
        dias = _dias_iso(_fecha_o_nada(fila.get("fecha_inicio")), _fecha_o_nada(fila.get("fecha_fin")))
        if pd.notna(fila.get("id_estacionalidad_anio")):
            por_anio[int(fila["id_estacionalidad_anio"])] = dias
        if pd.notna(fila.get("id_estacionalidad")):
            por_estacionalidad.setdefault(int(fila["id_estacionalidad"]), set()).update(dias)
    return {"dias_estacionalidad": {k: frozenset(v) for k, v in por_estacionalidad.items()},
            "dias_estacionalidad_anio": por_anio}


def retraso_maximo_de(umbrales: dict | None) -> timedelta:
    """Tolerancia de oportunidad (OPOR-001) gobernada: el umbral de §5.1 «datos atrasados» de la versión vigente de
    threshold_config, periodos_atraso × periodo_ingesta_min (el mismo de ALT-009). Sin esos valores, o si no son
    números positivos, rige RETRASO_MAXIMO (2 × 1.440 min, los valores sembrados por la migración 0001)."""
    try:
        minutos = float(umbrales["periodos_atraso"]) * float(umbrales["periodo_ingesta_min"])
        return timedelta(minutes=minutos) if minutos > 0 else RETRASO_MAXIMO
    except (KeyError, TypeError, ValueError, OverflowError):
        return RETRASO_MAXIMO


def validar_lote(df, lote_id, esquema=None, catalogos=None, ahora=None, retraso_maximo=RETRASO_MAXIMO):
    """Valida un lote y devuelve (df_validos, errores).

    catalogos: {"rutas", "idrutas", "procesos", "estacionalidades", "novedades", "segmentos": conjuntos de llaves
    existentes; "capacidades": {ruta: capacidad}} para la validación relacional y la capacidad > 0. Las claves que
    falten se toman del catálogo empaquetado. ahora: instante de la ejecución (marcas en el futuro; por omisión, el
    reloj de la API). retraso_maximo: tolerancia de oportunidad entre el cierre del día del registro y su marca (el
    ciclo pasa la de threshold_config, retraso_maximo_de).
    """
    if df is None or len(df) == 0:
        return (df.copy() if df is not None else pd.DataFrame()), []
    esquema = esquema or detectar_esquema(df)
    conf = ESQUEMAS[esquema]
    cat = catalogo_empaquetado()
    cat.update({k: v for k, v in (catalogos or {}).items() if v is not None})
    reg = _Registro(df, lote_id, conf["llave"])
    _completitud(reg, conf)                                          # 1
    marca, fin_dia = _validez(reg, conf, cat)                        # 2
    _unicidad(reg, conf)                                             # 3
    _consistencia(reg)                                               # 4
    _oportunidad(reg, marca, fin_dia, ahora, retraso_maximo)         # 5
    _relacional(reg, cat)                                            # 6
    validos = df.loc[~reg.bloqueadas].copy() if len(df) == len(reg.bloqueadas) else df.copy()
    return validos, reg.errores


class _Registro:
    """Errores de un lote y filas rechazadas a medida que se revisa cada dimensión de §6.3."""

    def __init__(self, df, lote_id, llave):
        self.d = df.reset_index(drop=True)
        self.filas = df.index.tolist()
        self.lote_id = lote_id
        self.llave = [c for c in llave if c in self.d.columns]
        self.errores = []
        self.bloqueadas = np.zeros(len(self.d), dtype=bool)

    def llave_de(self, i) -> dict:
        return {c: _simple(self.d.at[i, c]) for c in self.llave}

    def registrar(self, mascara, campo, codigo, dimension, detalle, bloqueante=True):
        mascara = np.asarray(mascara, dtype=bool)
        d = self.d
        for i in np.flatnonzero(mascara):
            valor = _texto(d.at[i, campo]) if campo in d.columns else None
            self.errores.append({"lote": self.lote_id, "fila": self.filas[i], "llave": self.llave_de(i),
                                 "campo": campo, "valor": valor, "codigo": codigo, "dimension": dimension,
                                 "detalle": detalle(i) if callable(detalle) else detalle, "bloqueante": bloqueante})
        if bloqueante:
            self.bloqueadas[mascara] = True

    def registrar_catalogo(self, llave, campo, valor, codigo, dimension, detalle):
        """Error de un catálogo (no de una fila del lote): fila vacía y la llave del registro del catálogo."""
        self.errores.append({"lote": self.lote_id, "fila": None, "llave": llave, "campo": campo,
                             "valor": _texto(valor), "codigo": codigo, "dimension": dimension, "detalle": detalle,
                             "bloqueante": True})


def _completitud(reg: _Registro, conf: dict) -> None:
    """1. Completitud: columnas y valores obligatorios."""
    d = reg.d
    for campo in conf["obligatorios"]:
        if campo not in d.columns:
            reg.registrar(np.ones(len(d), bool), campo, "COMP-002", "completitud",
                          f"Falta la columna obligatoria '{campo}' en el lote.")
        else:
            reg.registrar(d[campo].isna().values, campo, "COMP-001", "completitud",
                          f"'{campo}' es obligatorio y llegó vacío.")


def _validez_conteos(reg: _Registro, conf: dict) -> None:
    """Conteos numéricos y >= 0; las columnas «numericos» (pasajeros por segmento, H9) solo numéricas."""
    d = reg.d
    for campo in (*conf["conteos"], *conf.get("numericos", ())):
        if campo in d.columns:
            num = pd.to_numeric(d[campo], errors="coerce")
            reg.registrar((num.isna() & d[campo].notna()).values, campo, VAL_TIPO, VALIDEZ,
                          f"'{campo}' no es numérico.")
            if campo in conf["conteos"]:
                reg.registrar((num < 0).fillna(False).values, campo, "VAL-001", VALIDEZ, f"'{campo}' es negativo.")


def _validez_horas(reg: _Registro, conf: dict) -> None:
    """Hora entera 0-23 (demanda) u hora del día de tipo time (consolidado) y franja coherente; hora_fin = 00:00
    cierra el día y cuenta como 24:00 (bloque 23:45-00:00)."""
    d = reg.d
    if "hora" in d.columns:
        h = horas(d["hora"])
        reg.registrar((h.isna() & d["hora"].notna()).values, "hora", VAL_TIPO, VALIDEZ,
                      "La hora no es un número ni una hora del día (HH:MM:SS).")
        if conf.get("hora") == "entera":
            malo, texto = (h < 0) | (h > 23) | (h % 1 != 0), "La hora debe ser un entero entre 0 y 23."
        else:
            malo, texto = (h < 0) | (h >= 24), "La hora debe estar entre 00:00 y 23:59:59."
        reg.registrar((h.notna() & malo).values, "hora", "VAL-002", VALIDEZ, texto)
    if {"hora_inicio", "hora_fin"} <= set(d.columns):
        ini, fin = horas(d["hora_inicio"]), horas(d["hora_fin"])
        for campo, serie in (("hora_inicio", ini), ("hora_fin", fin)):
            reg.registrar((serie.isna() & d[campo].notna()).values, campo, VAL_TIPO, VALIDEZ,
                          f"'{campo}' no es una hora del día (HH:MM:SS).")
        fin_dia = fin.where(~((fin == 0) & (ini > 0)), 24.0)
        reg.registrar((ini > fin_dia).fillna(False).values, "hora_inicio", "VAL-004", VALIDEZ,
                      lambda i: f"La franja es incoherente: hora_inicio ({d.at[i, 'hora_inicio']}) es posterior a "
                                f"hora_fin ({d.at[i, 'hora_fin']}).")


def _validez_capacidad(reg: _Registro, cat: dict) -> None:
    """Capacidad > 0: la del lote (si la trae) y la del catálogo de las rutas del lote (registro del catálogo)."""
    d = reg.d
    if "capacidad" in d.columns:
        c = pd.to_numeric(d["capacidad"], errors="coerce")
        reg.registrar((c <= 0).fillna(False).values, "capacidad", "VAL-005", VALIDEZ, "La capacidad debe ser > 0.")
    capacidades = cat.get("capacidades") or {}
    if "ruta" not in d.columns or not capacidades:
        return
    for ruta in sorted({r for r in d["ruta"].dropna().unique() if r in capacidades}, key=str):
        valor = pd.to_numeric(pd.Series([capacidades[ruta]]), errors="coerce").iloc[0]
        if pd.notna(valor) and valor <= 0:
            reg.registrar_catalogo({"ruta": _simple(ruta)}, "capacidad", capacidades[ruta], "VAL-005", VALIDEZ,
                                   f"La capacidad del catálogo para la ruta {ruta!r} es {capacidades[ruta]}: debe ser "
                                   "> 0; el optimizador no la usa hasta que se corrija en la fuente.")


def _validez_fechas(reg: _Registro):
    """Marca y fecha válidas, y la marca no anterior al día del registro.
    Devuelve (marca en UTC, fin del día del registro en UTC); cada una None si falta su columna."""
    d = reg.d
    marca = None
    if COLUMNA_MARCA in d.columns:
        marca = _a_utc(d[COLUMNA_MARCA])
        reg.registrar((marca.isna() & d[COLUMNA_MARCA].notna()).values, COLUMNA_MARCA,
                      VAL_TIPO, VALIDEZ, "ultima_actualizacion no es una fecha válida.")
    if "fecha" not in d.columns:
        return marca, None
    f = pd.to_datetime(d["fecha"], errors="coerce")
    reg.registrar((f.isna() & d["fecha"].notna()).values, "fecha", VAL_TIPO, VALIDEZ, "La fecha no es válida.")
    if f.dt.tz is None:
        f = f.dt.tz_localize(ZONA_OPERACION)
    inicio_dia = f.dt.normalize().dt.tz_convert("UTC")
    if marca is not None:
        reg.registrar((marca < inicio_dia).fillna(False).values, "fecha", "VAL-003", VALIDEZ,
                      lambda i: f"ultima_actualizacion ({marca.iloc[i]}) es anterior al día del registro "
                                f"({d.at[i, 'fecha']}).")
    return marca, inicio_dia + np.timedelta64(1, "D")


def _validez_hora_del_bloque(reg: _Registro) -> None:
    """VAL-008 (rango horario, §7.3 paso 3): la hora de la fila es la del bloque que empieza en hora_inicio (la hora
    entera, como en timbradas_consolidado, o el mismo inicio del bloque, como en timbradas_segmentos_anio). Solo en
    las filas cuya hora y cuya franja ya son válidas (VAL-002, VAL-004 y VAL-006 reportan las demás)."""
    d = reg.d
    if not {"hora", "hora_inicio"} <= set(d.columns):
        return
    h, ini = horas(d["hora"]), horas(d["hora_inicio"])
    validas = (h >= 0) & (h < 24) & (ini >= 0) & (ini < 24)
    if "hora_fin" in d.columns:
        fin = horas(d["hora_fin"])
        validas &= ini <= fin.where(~((fin == 0) & (ini > 0)), 24.0)
    reg.registrar((validas & (np.floor(h) != np.floor(ini))).fillna(False).values, "hora", "VAL-008", VALIDEZ,
                  lambda i: f"La hora ({d.at[i, 'hora']}) no es la del bloque que empieza a las "
                            f"{d.at[i, 'hora_inicio']}.")


def _dia_iso_de_la_fecha(reg: _Registro, dia: pd.Series) -> None:
    d = reg.d
    iso = pd.to_datetime(d["fecha"], errors="coerce").dt.dayofweek + 1
    malo = (iso.notna() & dia.notna() & (iso != dia)).values
    reg.registrar(malo, "id_dia_semana", "VAL-007", VALIDEZ,
                  lambda i: f"id_dia_semana = {d.at[i, 'id_dia_semana']} no es el día ISO de la fecha "
                            f"{d.at[i, 'fecha']} ({int(iso.iloc[i])}).")


def _dia_fuera_de_su_estacionalidad(reg: _Registro, dia: pd.Series, columna: str, dias: dict) -> None:
    d = reg.d
    posibles = pd.to_numeric(d[columna], errors="coerce").map(dias)
    malo = np.array([isinstance(p, frozenset) and pd.notna(x) and int(x) not in p
                     for p, x in zip(posibles, dia, strict=True)], dtype=bool)
    reg.registrar(malo, "id_dia_semana", "VAL-007", VALIDEZ,
                  lambda i: f"id_dia_semana = {d.at[i, 'id_dia_semana']} no cae en ninguna fecha de {columna} "
                            f"{d.at[i, columna]} (días ISO posibles: {sorted(posibles.iloc[i])}).")


def _validez_dia_semana(reg: _Registro, cat: dict) -> None:
    """VAL-007 (día de la semana, §7.3 paso 3): id_dia_semana de Extreme frente a la fecha donde la fuente la trae: el
    día ISO de `fecha` o, sin fecha, los días en que caen las fechas de su estacionalidad (estacionalidades_anio; un
    festivo de un día solo admite el día ISO de sus fechas). Sin catálogo de fechas no se evalúa."""
    d = reg.d
    if "id_dia_semana" not in d.columns:
        return
    dia = pd.to_numeric(d["id_dia_semana"], errors="coerce")
    if "fecha" in d.columns:
        _dia_iso_de_la_fecha(reg, dia)
        return
    for columna, nombre in (("id_estacionalidad_anio", "dias_estacionalidad_anio"),
                            ("id_estacionalidad", "dias_estacionalidad")):
        if columna in d.columns and cat.get(nombre):
            _dia_fuera_de_su_estacionalidad(reg, dia, columna, cat[nombre])
            return


def _validez(reg: _Registro, conf: dict, cat: dict):
    """2. Validez: tipos, conteos >= 0, horas y franjas (y la hora del bloque), día de la semana coherente con su
    fecha, fechas coherentes, capacidad > 0."""
    _validez_conteos(reg, conf)
    _validez_horas(reg, conf)
    _validez_hora_del_bloque(reg)
    _validez_dia_semana(reg, cat)
    _validez_capacidad(reg, cat)
    return _validez_fechas(reg)


def _normalizada(d: pd.DataFrame, columna: str) -> pd.Series:
    """Columna llave comparable: horas como número (time, texto y 00:00 de cierre iguales) y fechas como date."""
    if columna in COLUMNAS_HORA:
        return horas(d[columna])
    if columna == "fecha":
        return pd.to_datetime(d[columna], errors="coerce").dt.date
    return d[columna]


def _unicidad(reg: _Registro, conf: dict) -> None:
    """3. Unicidad: la llave natural no se repite (todas las filas del grupo se rechazan; no se elige una)."""
    d = reg.d
    llave = [c for c in conf["llave"] if c in d.columns]
    if len(llave) != len(conf["llave"]):
        return                                   # la columna que falta ya es COMP-002
    norm = pd.DataFrame({c: _normalizada(d, c) for c in llave})
    dup = norm.duplicated(keep=False).values
    reg.registrar(dup, llave[0], "UNI-001", "unicidad",
                  lambda i: "Llave duplicada (" + ", ".join(f"{c}={d.at[i, c]}" for c in llave) + "); se reporta "
                  "al responsable del consolidado, no se corrige.")


TOLERANCIA_TECHO = 0.005                    # promedio = CEIL(Σ / nro_viajes) de fn_consolidar (H7), con 2 decimales


def _consistencia_promedios(reg: _Registro, nv) -> None:
    """4a. Los promedios de subidas, bajadas y pasajeros coinciden con el total / nro_viajes: el exacto (tolerancia del
    1 %) o el entero hacia arriba que escribe fn_consolidar_timbradas_historicas (CEIL, hallazgo H7)."""
    d = reg.d
    for total, prom in (("subidas", "promedio_subidas"), ("bajadas", "promedio_bajadas"),
                        ("pasajeros", "promedio_pasajeros")):
        if {total, prom} <= set(d.columns):
            t = pd.to_numeric(d[total], errors="coerce")
            p = pd.to_numeric(d[prom], errors="coerce")
            esperado = t / nv.where(nv > 0)
            lejos_exacto = (p - esperado).abs() > np.maximum(TOLERANCIA_PROMEDIO * esperado.abs(), 0.01)
            lejos_techo = (p - np.ceil(esperado)).abs() > TOLERANCIA_TECHO
            incoh = (lejos_exacto & lejos_techo).fillna(False)
            reg.registrar(incoh.values, prom, "CONS-001", CONSISTENCIA,
                          lambda i, t=t, nv=nv, prom=prom, total=total:
                          f"{prom} = {d.at[i, prom]} no coincide con {total} / nro_viajes = "
                          f"{t.iloc[i]} / {nv.iloc[i]} (ni con su valor exacto ni con el entero hacia arriba).")


def _consistencia(reg: _Registro) -> None:
    """4. Consistencia: promedios coherentes con subidas, bajadas y nro_viajes; demanda sin salidas."""
    d = reg.d
    if {"nro_viajes"} <= set(d.columns):
        nv = pd.to_numeric(d["nro_viajes"], errors="coerce")
        _consistencia_promedios(reg, nv)
        if "subidas" in d.columns:
            s = pd.to_numeric(d["subidas"], errors="coerce")
            reg.registrar(((nv == 0) & (s > 0)).fillna(False).values, "nro_viajes", "CONS-002", CONSISTENCIA,
                          "Hay subidas con nro_viajes = 0.")
    if {"pasajeros", "salidas"} <= set(d.columns):
        pas = pd.to_numeric(d["pasajeros"], errors="coerce")
        sal = pd.to_numeric(d["salidas"], errors="coerce")
        reg.registrar(((sal == 0) & (pas > 0)).fillna(False).values, "salidas", "CONS-002", CONSISTENCIA,
                      "Hay pasajeros en una hora sin salidas.")


def _resellada(d: pd.DataFrame) -> np.ndarray:
    """Filas cuya marca es un re-sellado (carga inicial, recarga o fn_consolidar sobre una llave ya entregada)."""
    if "tipo_llegada" not in d.columns:
        return np.zeros(len(d), dtype=bool)
    return d["tipo_llegada"].isin(LLEGADAS_RESELLADAS).values


def _instante_utc(ahora) -> pd.Timestamp:
    ts = pd.Timestamp(ahora if ahora is not None else datetime.now(UTC))
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def _oportunidad(reg: _Registro, marca, fin_dia, ahora, retraso_maximo) -> None:
    """5. Oportunidad (no bloqueante): retraso frente al cierre del día del registro (sin contar las filas
    reselladas) y marcas en el futuro frente al instante de la ejecución."""
    if marca is None:
        return
    futuro = (marca > _instante_utc(ahora) + pd.Timedelta(MARGEN_FUTURO)).fillna(False).values
    if fin_dia is not None:
        retraso = marca - fin_dia
        tarde = (retraso > pd.Timedelta(retraso_maximo)).fillna(False).values & ~_resellada(reg.d) & ~futuro
        reg.registrar(tarde, COLUMNA_MARCA, "OPOR-001", OPORTUNIDAD,
                      lambda i: f"Dato tardío: llegó {retraso.iloc[i]} después del cierre del día "
                                f"(tolerancia {retraso_maximo}).", bloqueante=False)
    reg.registrar(futuro, COLUMNA_MARCA, "OPOR-002", OPORTUNIDAD,
                  "ultima_actualizacion está en el futuro frente al instante de la ejecución.", bloqueante=False)


def _no_esta_en(d, columna, validos, numerico=False):
    """Filas con valor en `columna` que no está en el catálogo `validos`."""
    serie = pd.to_numeric(d[columna], errors="coerce") if numerico else d[columna]
    conjunto = {int(v) for v in validos if pd.notna(pd.to_numeric(v, errors="coerce"))} if numerico else set(validos)
    return (~serie.isin(conjunto) & d[columna].notna()).values


# (columna del lote, catálogo, código, numérica, texto del catálogo)
_RELACIONES = (
    ("ruta", "rutas", "REL-001", False, "rutas"),
    ("idruta", "idrutas", "REL-001", True, "rutas"),
    ("id_ruta", "idrutas", "REL-001", True, "rutas"),
    ("id_estacionalidad", "estacionalidades", "REL-002", True, "estacionalidades"),
    ("id_novedad_vial", "novedades", "REL-003", True, "novedades_viales"),
    ("id_segmento", "segmentos", "REL-004", True, "rutas_segmentos"),
    ("proceso", "procesos", "REL-005", False, "Procesos"),
    ("id_dia_semana", "dias_semana", "REL-007", True, "dias_semana"),
)


def _segmento_de_su_ruta(reg: _Registro, cat: dict) -> None:
    """REL-006 (segmento, §7.3 paso 3): el segmento de la fila es de su ruta (rutas_segmentos.idruta = id_ruta)."""
    d = reg.d
    mapa = cat.get("segmentos_ruta") or {}
    if not mapa or not {"id_segmento", "id_ruta"} <= set(d.columns):
        return
    de_su_ruta = pd.to_numeric(d["id_segmento"], errors="coerce").map(mapa)
    ruta = pd.to_numeric(d["id_ruta"], errors="coerce")
    malo = (de_su_ruta.notna() & ruta.notna() & (de_su_ruta != ruta)).values
    reg.registrar(malo, "id_segmento", "REL-006", RELACIONAL,
                  lambda i: f"El segmento {d.at[i, 'id_segmento']} es de la ruta {int(de_su_ruta.iloc[i])} en "
                            f"rutas_segmentos, no de id_ruta {d.at[i, 'id_ruta']}.")


def _relacional(reg: _Registro, cat: dict) -> None:
    """6. Relacional: llaves de ruta, estacionalidad, novedad, segmento, proceso y día existentes en los catálogos, y
    el segmento de la ruta de la fila."""
    d = reg.d
    for columna, nombre, codigo, numerico, tabla in _RELACIONES:
        if columna in d.columns and cat.get(nombre):
            reg.registrar(_no_esta_en(d, columna, cat[nombre], numerico), columna, codigo, RELACIONAL,
                          lambda i, c=columna, t=tabla: f"{c} {d.at[i, c]!r} no existe en {t}.")
    _segmento_de_su_ruta(reg, cat)


def resumen(df, errores):
    """Conteos por dimensión y código, filas rechazadas, errores de catálogo y latencia media (horas) entre el cierre
    del día y la marca (sin las filas reselladas)."""
    por_dim, por_cod, cuarentena, catalogo = {}, {}, set(), 0
    for e in errores:
        por_dim[e["dimension"]] = por_dim.get(e["dimension"], 0) + 1
        por_cod[e["codigo"]] = por_cod.get(e["codigo"], 0) + 1
        if e.get("fila") is None:
            catalogo += 1
        elif e["bloqueante"]:
            cuarentena.add(e["fila"])
    latencia = None
    if df is not None and len(df) and {"fecha", "ultima_actualizacion"} <= set(df.columns):
        d = df.loc[~_resellada(df)]
        f = pd.to_datetime(d["fecha"], errors="coerce")
        if f.dt.tz is None:
            f = f.dt.tz_localize(ZONA_OPERACION)
        lag = _a_utc(d["ultima_actualizacion"]) - (f.dt.normalize().dt.tz_convert("UTC") + np.timedelta64(1, "D"))
        latencia = float(lag.dt.total_seconds().mean() / 3600) if lag.notna().any() else None
    return {"filas": 0 if df is None else int(len(df)), "filas_cuarentena": len(cuarentena),
            "errores_de_catalogo": catalogo, "errores_por_dimension": por_dim, "errores_por_codigo": por_cod,
            "latencia_media_h": latencia}
