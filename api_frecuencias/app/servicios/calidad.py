"""Calidad del dato de cada lote leído (especificación v1.5, §6.3; RF-004).

validar_lote(df, lote_id) revisa las seis dimensiones y devuelve (df_validos, errores). Cada error lleva lote, fila,
campo, codigo, dimension, detalle, valor y bloqueante. Las filas con un error bloqueante van a cuarentena (no pasan a la
inferencia) y nunca se corrigen; los errores de oportunidad no son bloqueantes: se registran como alerta de retraso y
métrica de latencia (tratamiento de §6.3).

Se reconocen dos esquemas de lote:
- "demanda": la salida de FuenteParquet / datos.demanda_horaria() [ruta, fecha, hora, pasajeros, salidas,
  ultima_actualizacion];
- "consolidado": timbradas_consolidado de la fuente PostgreSQL [proceso, id_ruta, id_dia_semana, id_estacionalidad, hora,
  hora_inicio, hora_fin, subidas, bajadas, nro_viajes, promedio_subidas, promedio_bajadas, ultima_actualizacion].
"""
from __future__ import annotations

from datetime import timedelta

import numpy as np
import pandas as pd

ESQUEMAS = {
    "demanda": {
        "obligatorios": ["ruta", "fecha", "hora", "pasajeros", "ultima_actualizacion"],
        "conteos": ["pasajeros", "salidas"],
        "llave": ["ruta", "fecha", "hora"],
    },
    "consolidado": {
        "obligatorios": ["proceso", "id_ruta", "id_dia_semana", "id_estacionalidad", "hora", "subidas", "bajadas",
                         "nro_viajes", "ultima_actualizacion"],
        "conteos": ["subidas", "bajadas", "nro_viajes", "promedio_subidas", "promedio_bajadas"],
        "llave": ["proceso", "id_ruta", "id_dia_semana", "id_estacionalidad", "hora"],
    },
}

# Catálogo relacional por defecto: las tres rutas del reto (nombre e idruta del proyecto).
RUTAS_VALIDAS = {"SILENCIO", "CRA 54", "CL 72"}
IDRUTAS_VALIDAS = {2, 16, 21}
RETRASO_MAXIMO = timedelta(days=2)          # §5.1: datos atrasados = 2 períodos de ingesta (ciclo diario)
TOLERANCIA_PROMEDIO = 0.01                  # 1 % (y al menos 0,01) entre el promedio y subidas / nro_viajes


def detectar_esquema(df):
    cols = set(df.columns)
    if "pasajeros" in cols or "ruta" in cols:
        return "demanda"
    if "subidas" in cols or "id_ruta" in cols:
        return "consolidado"
    raise ValueError("No se reconoce el esquema del lote (se esperaba demanda horaria o timbradas_consolidado).")


def _a_utc(serie):
    s = pd.to_datetime(serie, errors="coerce", utc=False)
    if getattr(s.dt, "tz", None) is None:
        s = s.dt.tz_localize("America/Bogota", ambiguous="NaT", nonexistent="NaT")
    return s.dt.tz_convert("UTC")


def validar_lote(df, lote_id, esquema=None, catalogos=None, ahora=None, retraso_maximo=RETRASO_MAXIMO):
    """Valida un lote y devuelve (df_validos, errores).

    catalogos: {"rutas": set de nombres, "idrutas": set de ids, "estacionalidades": set, "novedades": set} para la
    validación relacional (por defecto las tres rutas del reto). ahora: instante de la ejecución (para marcas en el
    futuro). retraso_maximo: tolerancia de oportunidad entre el fin del día del registro y su ultima_actualizacion.
    """
    if df is None or len(df) == 0:
        return (df.copy() if df is not None else pd.DataFrame()), []
    esquema = esquema or detectar_esquema(df)
    conf = ESQUEMAS[esquema]
    cat = {"rutas": RUTAS_VALIDAS, "idrutas": IDRUTAS_VALIDAS}
    cat.update(catalogos or {})
    d = df.reset_index(drop=True)
    filas = df.index.tolist()
    errores = []
    bloqueadas = np.zeros(len(d), dtype=bool)

    def registrar(mascara, campo, codigo, dimension, detalle, bloqueante=True):
        mascara = np.asarray(mascara, dtype=bool)
        for i in np.flatnonzero(mascara):
            valor = d.at[i, campo] if campo in d.columns else None
            if isinstance(valor, (np.generic,)):
                valor = valor.item()
            if valor is not None and not isinstance(valor, (int, float, str, bool)):
                valor = str(valor)
            if isinstance(valor, float) and np.isnan(valor):
                valor = None
            errores.append({"lote": lote_id, "fila": filas[i], "campo": campo, "codigo": codigo,
                            "dimension": dimension, "detalle": detalle(i) if callable(detalle) else detalle,
                            "valor": valor, "bloqueante": bloqueante})
        if bloqueante:
            bloqueadas[mascara] = True

    # 1. Completitud: columnas y valores obligatorios
    for campo in conf["obligatorios"]:
        if campo not in d.columns:
            registrar(np.ones(len(d), bool), campo, "COMP-002", "completitud",
                      f"Falta la columna obligatoria '{campo}' en el lote.")
        else:
            registrar(d[campo].isna().values, campo, "COMP-001", "completitud", f"'{campo}' es obligatorio y llegó vacío.")

    # 2. Validez: tipos, conteos >= 0, hora, fechas coherentes, capacidad > 0
    for campo in conf["conteos"]:
        if campo in d.columns:
            num = pd.to_numeric(d[campo], errors="coerce")
            registrar((num.isna() & d[campo].notna()).values, campo, "VAL-006", "validez", f"'{campo}' no es numérico.")
            registrar((num < 0).fillna(False).values, campo, "VAL-001", "validez", f"'{campo}' es negativo.")
    if "hora" in d.columns:
        h = pd.to_numeric(d["hora"], errors="coerce")
        registrar((h.notna() & ((h < 0) | (h > 23) | (h % 1 != 0))).values, "hora", "VAL-002", "validez",
                  "La hora debe ser un entero entre 0 y 23.")
    if "capacidad" in d.columns:
        c = pd.to_numeric(d["capacidad"], errors="coerce")
        registrar((c <= 0).fillna(False).values, "capacidad", "VAL-005", "validez", "La capacidad debe ser > 0.")
    if {"hora_inicio", "hora_fin"} <= set(d.columns):
        ini = pd.to_timedelta(d["hora_inicio"].astype(str), errors="coerce")
        fin = pd.to_timedelta(d["hora_fin"].astype(str), errors="coerce")
        registrar((ini > fin).fillna(False).values, "hora_inicio", "VAL-004", "validez",
                  "La franja es incoherente: hora_inicio es posterior a hora_fin.")
    marca = None
    if "ultima_actualizacion" in d.columns:
        marca = _a_utc(d["ultima_actualizacion"])
        registrar((marca.isna() & d["ultima_actualizacion"].notna()).values, "ultima_actualizacion", "VAL-006", "validez",
                  "ultima_actualizacion no es una fecha válida.")
    fin_dia = None
    if "fecha" in d.columns:
        f = pd.to_datetime(d["fecha"], errors="coerce")
        registrar((f.isna() & d["fecha"].notna()).values, "fecha", "VAL-006", "validez", "La fecha no es válida.")
        if f.dt.tz is None:
            f = f.dt.tz_localize("America/Bogota")
        inicio_dia = f.dt.normalize().dt.tz_convert("UTC")
        fin_dia = inicio_dia + np.timedelta64(1, "D")
        if marca is not None:
            registrar((marca < inicio_dia).fillna(False).values, "fecha", "VAL-003", "validez",
                      lambda i: f"ultima_actualizacion ({marca.iloc[i]}) es anterior al día del registro ({d.at[i, 'fecha']}).")

    # 3. Unicidad: la llave natural no se repite (todas las filas del grupo a cuarentena; no se elige una)
    llave = [c for c in conf["llave"] if c in d.columns]
    if len(llave) == len(conf["llave"]):
        dup = d.duplicated(subset=llave, keep=False).values
        registrar(dup, llave[0], "UNI-001", "unicidad",
                  lambda i: "Llave duplicada (" + ", ".join(f"{c}={d.at[i, c]}" for c in llave) + "); se reporta al "
                  "responsable del consolidado, no se corrige.")

    # 4. Consistencia: promedios coherentes con subidas, bajadas y nro_viajes; demanda sin salidas
    if {"nro_viajes"} <= set(d.columns):
        nv = pd.to_numeric(d["nro_viajes"], errors="coerce")
        for total, prom in (("subidas", "promedio_subidas"), ("bajadas", "promedio_bajadas")):
            if {total, prom} <= set(d.columns):
                t = pd.to_numeric(d[total], errors="coerce")
                p = pd.to_numeric(d[prom], errors="coerce")
                esperado = t / nv.where(nv > 0)
                incoh = ((p - esperado).abs() > np.maximum(TOLERANCIA_PROMEDIO * esperado.abs(), 0.01)).fillna(False)
                registrar(incoh.values, prom, "CONS-001", "consistencia",
                          lambda i, t=t, nv=nv, prom=prom, total=total:
                          f"{prom} = {d.at[i, prom]} no coincide con {total} / nro_viajes = {t.iloc[i]} / {nv.iloc[i]}.")
        if "subidas" in d.columns:
            s = pd.to_numeric(d["subidas"], errors="coerce")
            registrar(((nv == 0) & (s > 0)).fillna(False).values, "nro_viajes", "CONS-002", "consistencia",
                      "Hay subidas con nro_viajes = 0.")
    if {"pasajeros", "salidas"} <= set(d.columns):
        pas = pd.to_numeric(d["pasajeros"], errors="coerce")
        sal = pd.to_numeric(d["salidas"], errors="coerce")
        registrar(((sal == 0) & (pas > 0)).fillna(False).values, "salidas", "CONS-002", "consistencia",
                  "Hay pasajeros en una hora sin salidas.")

    # 5. Oportunidad (no bloqueante): retraso frente al día del registro y marcas en el futuro
    if marca is not None and fin_dia is not None:
        retraso = marca - fin_dia
        registrar((retraso > pd.Timedelta(retraso_maximo)).fillna(False).values, "ultima_actualizacion", "OPOR-001",
                  "oportunidad", lambda i: f"Dato tardío: llegó {retraso.iloc[i]} después del cierre del día "
                  f"(tolerancia {retraso_maximo}).", bloqueante=False)
    if marca is not None and ahora is not None:
        ahora_ts = pd.Timestamp(ahora)
        ahora_ts = ahora_ts.tz_localize("UTC") if ahora_ts.tzinfo is None else ahora_ts.tz_convert("UTC")
        registrar((marca > ahora_ts + np.timedelta64(5, "m")).fillna(False).values, "ultima_actualizacion", "OPOR-002",
                  "oportunidad", "ultima_actualizacion está en el futuro frente al instante de la ejecución.",
                  bloqueante=False)

    # 6. Relacional: llaves de ruta, estacionalidad y novedad existentes
    if "ruta" in d.columns and cat.get("rutas"):
        registrar((~d["ruta"].isin(cat["rutas"]) & d["ruta"].notna()).values, "ruta", "REL-001", "relacional",
                  lambda i: f"La ruta {d.at[i, 'ruta']!r} no existe en el catálogo.")
    if "id_ruta" in d.columns and cat.get("idrutas"):
        ir = pd.to_numeric(d["id_ruta"], errors="coerce")
        registrar((~ir.isin(cat["idrutas"]) & d["id_ruta"].notna()).values, "id_ruta", "REL-001", "relacional",
                  lambda i: f"id_ruta {d.at[i, 'id_ruta']} no existe en rutas.")
    if "id_estacionalidad" in d.columns and cat.get("estacionalidades"):
        registrar((~d["id_estacionalidad"].isin(cat["estacionalidades"]) & d["id_estacionalidad"].notna()).values,
                  "id_estacionalidad", "REL-002", "relacional",
                  lambda i: f"id_estacionalidad {d.at[i, 'id_estacionalidad']} no existe en estacionalidades.")
    if "id_novedad_vial" in d.columns and cat.get("novedades"):
        registrar((~d["id_novedad_vial"].isin(cat["novedades"]) & d["id_novedad_vial"].notna()).values,
                  "id_novedad_vial", "REL-003", "relacional",
                  lambda i: f"id_novedad_vial {d.at[i, 'id_novedad_vial']} no existe en novedades_viales.")

    validos = df.loc[~bloqueadas].copy() if len(df) == len(bloqueadas) else df.copy()
    return validos, errores


def resumen(df, errores):
    """Conteos por dimensión y código, filas en cuarentena y latencia media (horas) entre el cierre del día y la marca."""
    por_dim, por_cod, cuarentena = {}, {}, set()
    for e in errores:
        por_dim[e["dimension"]] = por_dim.get(e["dimension"], 0) + 1
        por_cod[e["codigo"]] = por_cod.get(e["codigo"], 0) + 1
        if e["bloqueante"]:
            cuarentena.add(e["fila"])
    latencia = None
    if df is not None and len(df) and {"fecha", "ultima_actualizacion"} <= set(df.columns):
        f = pd.to_datetime(df["fecha"], errors="coerce")
        if f.dt.tz is None:
            f = f.dt.tz_localize("America/Bogota")
        lag = _a_utc(df["ultima_actualizacion"]) - (f.dt.normalize().dt.tz_convert("UTC") + np.timedelta64(1, "D"))
        latencia = float(lag.dt.total_seconds().mean() / 3600) if lag.notna().any() else None
    return {"filas": 0 if df is None else int(len(df)), "filas_cuarentena": len(cuarentena),
            "errores_por_dimension": por_dim, "errores_por_codigo": por_cod, "latencia_media_h": latencia}
