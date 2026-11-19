"""Variables, líneas base y banda del pronóstico de corto plazo (spec v1.5 §2.2 «horizontes configurables de 30, 60 y
120 minutos», RF-005, §3.1 M3, §9.1, §9.2 «el preprocesamiento del entrenamiento se reproduce exactamente en Python y
está versionado», §9.3).

Es el código del experimento E14 (pronostico_corto_plazo/comun.py de la entrega), con el que se eligió el modelo en
la validación (enero a junio de 2025) y se midió una sola vez en la prueba reservada (julio a diciembre de 2025). Las
variables, su orden y sus reglas son las mismas; solo cambian la carpeta de los datos (datos/corto_plazo de la API),
que el número de días sale del calendario, que variables() se partió en tres funciones y que Ruta.recorte() permite
calcular un solo día. scripts/verificar_corto_plazo.py comprueba que, con este código y los artefactos de la API, se
reproducen las predicciones guardadas de esa prueba.

El problema: en cada instante t (cada media hora, de 04:00 a 21:00) se pronostican las subidas de los siguientes 30, 60
y 120 minutos con lo observado hasta t. La unidad es el bloque de 15 minutos del instante en que ocurre la subida.
Ninguna variable usa lo que pasa después de t (pronostico_corto_plazo/comprobar_fuga.py lo comprueba alterando el
futuro: 486 comprobaciones sin diferencias).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

VERSION_VARIABLES = "cp1-2026-11-17"
RUTAS = {2: "SILENCIO", 16: "CRA 54", 21: "CL 72"}
BLOQUES = 96                                  # bloques de 15 minutos por día
INSTANTES = np.arange(16, 85, 2)              # 04:00, 04:30, ..., 21:00
HORIZONTES = {30: 2, 60: 4, 120: 8}           # minutos -> bloques
DIA0 = pd.Timestamp("2023-01-01")
PERIODOS = {"entrenamiento": ("2023-01-01", "2024-12-31"), "validacion": ("2025-01-01", "2025-06-30"),
            "prueba": ("2025-07-01", "2025-12-31")}
# días iniciales sin evaluar ni entrenar: la regla de 8 semanas necesita historia
ARRANQUE = 56
UMBRAL_SIN_DATOS = 0.05                       # un día-ruta con menos del 5 % de lo habitual se trata como «sin datos»
SEMILLA = 42
HILOS = 5
FRANJAS = [("04-05", 16, 24), ("06-08 pico", 24, 36), ("09-16 valle", 36, 68), ("17-19 pico", 68, 80),
           ("20-21", 80, 88)]
NIVELES = ("ruta", "sentido", "segmento")
CALENDARIO = ["dia_semana", "tipo_dia", "festivo", "carnaval", "semana_santa", "vacaciones", "navidad", "primero_enero",
              "vac_escolar", "vac_univ", "mes", "dia_mes"]
HIPER = {"objective": "poisson", "learning_rate": 0.05, "n_estimators": 400, "num_leaves": 63, "min_child_samples": 100,
         "subsample": 0.8, "subsample_freq": 1, "colsample_bytree": 0.8, "reg_lambda": 1.0}
ARCHIVOS_PANEL = ("subidas_segmento_15min.parquet", "salidas_15min.parquet", "segmentos.csv", "calendario.csv")


def rango_dias(periodo: str) -> tuple[int, int]:
    """Índices de día [a, b] (inclusive) del periodo, contados desde el 2023-01-01."""
    a, b = (pd.Timestamp(x) for x in PERIODOS[periodo])
    return (a - DIA0).days, (b - DIA0).days


@dataclass
class Ruta:
    idruta: int
    nombre: str
    y: np.ndarray            # (D, 96, S) subidas por día, bloque y segmento
    sal: np.ndarray          # (D, 96) viajes que iniciaron en el bloque
    seg: pd.DataFrame        # segmentos en orden de recorrido
    cal: pd.DataFrame        # calendario por día
    ok: np.ndarray           # (D,) el día tiene datos

    def recorte(self, desde: int, hasta: int) -> Ruta:
        """Los días [desde, hasta] (inclusive). Las variables de un día solo miran los ARRANQUE días anteriores, así que
        con desde = hasta - ARRANQUE las del último día son las mismas que con la serie entera."""
        sl = slice(desde, hasta + 1)
        return Ruta(self.idruta, self.nombre, self.y[sl], self.sal[sl], self.seg,
                    self.cal.iloc[sl].reset_index(drop=True), self.ok[sl])


def dias_con_datos(total: np.ndarray) -> np.ndarray:
    """Un día-ruta «sin datos» tiene menos del 5 % de la mediana del mismo día de la semana de las 8 semanas anteriores
    (los últimos días de mes de 2025 no traen eventos de conteo). Sin semanas anteriores: basta con que tenga
    subidas."""
    d = len(total)
    ref = np.full((8, d), np.nan)
    for k in range(1, 9):
        ref[k - 1, 7 * k:] = total[:-7 * k]
    hay = ~np.isnan(ref).all(axis=0)
    med = np.full(d, np.nan)
    med[hay] = np.nanmedian(ref[:, hay], axis=0)
    return np.where(np.isnan(med), total > 0, total >= UMBRAL_SIN_DATOS * np.nan_to_num(med, nan=0.0)) & (total > 0)


def cargar_ruta(idruta: int, carpeta: Path) -> Ruta:
    """La serie de la ruta desde el panel de 15 minutos (subidas por segmento y salidas por bloque) y su calendario."""
    seg = pd.read_csv(carpeta / "segmentos.csv")
    seg = seg[seg["idruta"] == idruta].sort_values("nro_segmento").reset_index(drop=True)
    s = len(seg)
    if not (seg["nro_segmento"].to_numpy() == np.arange(1, s + 1)).all():
        raise ValueError("los segmentos no están numerados de 1 a S")
    cal = pd.read_csv(carpeta / "calendario.csv", parse_dates=["fecha"])
    n_dias = len(cal)
    if cal["fecha"].iloc[0] != DIA0 or not (cal["fecha"].diff().dropna() == pd.Timedelta(days=1)).all():
        raise ValueError("el calendario no es diario y continuo desde el 2023-01-01")
    p = pd.read_parquet(carpeta / "subidas_segmento_15min.parquet", filters=[("idruta", "==", idruta)])
    d = (pd.to_datetime(p["dia"]) - DIA0).dt.days.to_numpy()
    y = np.zeros((n_dias, BLOQUES, s), np.float32)
    m = p["nro_segmento"].to_numpy() > 0
    np.add.at(y, (d[m], p["bloque"].to_numpy()[m], p["nro_segmento"].to_numpy()[m] - 1), p["subidas"].to_numpy()[m])
    q = pd.read_parquet(carpeta / "salidas_15min.parquet", filters=[("idruta", "==", idruta)])
    sal = np.zeros((n_dias, BLOQUES), np.float32)
    np.add.at(sal, ((pd.to_datetime(q["dia"]) - DIA0).dt.days.to_numpy(), q["bloque"].to_numpy()),
              q["salidas"].to_numpy())
    cal["dia_semana"] = cal["fecha"].dt.dayofweek
    cal["mes"] = cal["fecha"].dt.month
    cal["dia_mes"] = cal["fecha"].dt.day
    return Ruta(idruta, RUTAS[idruta], y, sal, seg, cal, dias_con_datos(y.sum(axis=(1, 2))))


def agrupar(r: Ruta, nivel: str) -> np.ndarray:
    """(D, 96, G): la demanda de la ruta entera (G = 1), por sentido (G = 2: ida, regreso) o por segmento (G = S)."""
    if nivel == "ruta":
        return r.y.sum(axis=2, keepdims=True)
    if nivel == "sentido":
        ida = (r.seg["sentido"] == "ida").to_numpy()
        return np.stack([r.y[:, :, ida].sum(axis=2), r.y[:, :, ~ida].sum(axis=2)], axis=2)
    return r.y


class Ventanas:
    """Sumas de ventana sobre los instantes de pronóstico, a partir de la suma acumulada de los bloques de 15
    minutos."""

    def __init__(self, yg: np.ndarray):
        d, b, g = yg.shape
        self.cs = np.zeros((d * b + 1, g))
        np.cumsum(yg.reshape(d * b, g), axis=0, out=self.cs[1:])
        self.t = np.arange(d)[:, None] * b + INSTANTES[None, :]
        self.t0 = (np.arange(d) * b)[:, None]

    def futuro(self, k: int) -> np.ndarray:     # lo que se quiere pronosticar: los k bloques que empiezan en t
        return (self.cs[self.t + k] - self.cs[self.t]).astype(np.float32)

    def pasado(self, k: int) -> np.ndarray:     # los k bloques anteriores a t (ya observados)
        return (self.cs[self.t] - self.cs[np.maximum(self.t - k, 0)]).astype(np.float32)

    def hoy(self) -> np.ndarray:                # lo acumulado del día hasta t
        return (self.cs[self.t] - self.cs[self.t0]).astype(np.float32)


def atras(a: np.ndarray, k: int, ok: np.ndarray) -> np.ndarray:
    """El mismo instante k días antes; NaN si ese día no existe o no tiene datos."""
    out = np.full(a.shape, np.nan, np.float32)
    if 0 < k < a.shape[0]:
        out[k:] = a[:-k]
        out[k:][~ok[:-k]] = np.nan
    return out


def media_atras(a: np.ndarray, ks, ok: np.ndarray, con_desv: bool = False):
    """Media (y desviación) del mismo instante en los días d-k, sin contar los días sin datos."""
    s = np.zeros(a.shape, np.float32)
    s2 = np.zeros(a.shape, np.float32)
    n = np.zeros(a.shape, np.float32)
    for k in ks:
        x = atras(a, k, ok)
        m = ~np.isnan(x)
        s[m] += x[m]
        if con_desv:
            s2[m] += x[m] ** 2
        n += m
    with np.errstate(invalid="ignore", divide="ignore"):
        media = np.where(n > 0, s / n, np.nan).astype(np.float32)
        if not con_desv:
            return media
        var = np.where(n > 1, (s2 - n * media ** 2) / (n - 1), np.nan)
        return media, np.sqrt(np.clip(var, 0, None)).astype(np.float32)


SEMANAS4, SEMANAS8 = (7, 14, 21, 28), (7, 14, 21, 28, 35, 42, 49, 56)
CONJUNTOS = ("semanal", "con_hoy", "completo")


def _vecinos(a: np.ndarray, desde: int, hasta: int) -> np.ndarray:
    """Suma de los segmentos s+desde .. s+hasta (sin el propio segmento)."""
    out = np.zeros(a.shape, np.float32)
    for dj in range(desde, hasta + 1):
        if dj < 0:
            out[:, :, -dj:] += a[:, :, :dj]
        elif dj > 0:
            out[:, :, :-dj] += a[:, :, dj:]
    return out


def _variables_de_la_ruta(r: Ruta, v: Ventanas, k: int, latencia: int, d: int, i: int, g: int) -> dict[str, np.ndarray]:
    """En sentido y segmento: el estado de la ruta entera (lo esperado y lo observado hoy en toda la ruta)."""
    vr = Ventanas(agrupar(r, "ruta"))
    yr = vr.futuro(k)

    def obs_r(kk: int) -> np.ndarray:
        return (vr.cs[np.maximum(vr.t - latencia, 0)] - vr.cs[np.maximum(vr.t - latencia - kk, 0)]).astype(np.float32)

    hoy_r = (vr.cs[np.maximum(vr.t - latencia, vr.t0)] - vr.cs[vr.t0]).astype(np.float32)
    ruta_cols = {"R_m4": media_atras(yr, SEMANAS4, r.ok), "R_p30": obs_r(2), "R_p60": obs_r(4), "R_p120": obs_r(8),
                 "R_hoy": hoy_r, "R_ehoy": media_atras(hoy_r, SEMANAS4, r.ok)}
    ruta_cols["R_rhoy"] = (ruta_cols["R_hoy"] + 1) / (ruta_cols["R_ehoy"] + 1)
    return {nombre: np.broadcast_to(a, (d, i, g)) for nombre, a in ruta_cols.items()}


def _variables_de_la_oferta(r: Ruta, v: Ventanas, cols: dict, nivel: str, k: int, latencia: int, d: int, i: int,
                            g: int) -> None:
    """Conjunto «completo»: las salidas ya despachadas y, por segmento, las que pasarán por él y sus vecinos."""
    cs_s = np.concatenate([[0.0], np.cumsum(r.sal.reshape(-1))])
    t = v.t - latencia

    def salidas(desde: np.ndarray, hasta: np.ndarray) -> np.ndarray:
        # salidas en [desde, hasta) ya ocurridas antes de t
        a, b = np.clip(desde, 0, None), np.clip(np.minimum(hasta, t), 0, None)
        return np.where(b > a, cs_s[b] - cs_s[a], 0.0).astype(np.float32)

    for nombre, kk in (("sal60", 4), ("sal120", 8), ("sal240", 16)):
        cols[nombre] = np.broadcast_to(salidas(t - kk, t)[:, :, None], (d, i, g))
    if nivel != "segmento":
        return
    ret = np.round(r.seg["minutos_desde_inicio"].to_numpy() / 15).astype(int)      # bloques hasta el segmento
    llegan = np.empty((d, i, g), np.float32)
    pasaron = np.empty((d, i, g), np.float32)
    for j, lj in enumerate(ret):
        llegan[:, :, j] = salidas(v.t - lj, v.t - lj + k)       # salidas que pasarán por el segmento en la ventana
        pasaron[:, :, j] = salidas(v.t - lj - 2, v.t - lj)      # las que pasaron en la última media hora
    cols["sal_llegan"], cols["sal_pasaron"] = llegan, pasaron
    conocida = np.clip((ret - latencia) / k, 0, 1).astype(np.float32)
    cols["sal_conocida"] = np.broadcast_to(conocida[None, None, :], (d, i, g))
    p30, p60, m4 = cols["p30"], cols["p60"], cols["m4"]
    cols["arriba30"], cols["arriba60"] = _vecinos(p30, -3, -1), _vecinos(p60, -6, -1)   # los segmentos anteriores
    cols["abajo30"] = _vecinos(p30, 1, 3)
    cols["vec_m4"] = _vecinos(np.nan_to_num(m4), -2, 2) + np.nan_to_num(m4)


def variables(r: Ruta, nivel: str, h: int, conjunto: str, latencia: int = 0) -> dict:
    """Variables del nivel (ruta, sentido o segmento) para el horizonte h (minutos) y el conjunto de información:

    - «semanal»: calendario y el mismo instante de las semanas anteriores (lo que se sabe con 7 días de antelación).
    - «con_hoy»: además, ayer, la última semana día a día y lo observado HOY hasta t (últimos 15 a 120 minutos, lo
      acumulado del día y su comparación con lo habitual); en sentido y segmento, también lo observado en la ruta.
    - «completo»: además, la oferta ya despachada (salidas de las últimas horas y, por segmento, las que llegarán en la
      ventana) y, por segmento, lo observado en los segmentos vecinos.
    `latencia` (bloques de 15 min): lo observado solo se conoce hasta t - latencia (sensibilidad al retraso de la
    captura).
    Devuelve X (float32), nombres, y (objetivo), las líneas base y los índices de día, instante y grupo de cada fila.
    """
    if conjunto not in CONJUNTOS:
        raise ValueError(conjunto)
    k = HORIZONTES[h]
    yg = agrupar(r, nivel)
    d, _, g = yg.shape
    i = len(INSTANTES)
    v = Ventanas(yg)
    y = v.futuro(k)                                             # (D, I, G)
    cols: dict[str, np.ndarray] = {}

    # --- lo que se sabe con una semana de antelación
    cols["l7"], cols["l14"] = atras(y, 7, r.ok), atras(y, 14, r.ok)
    cols["m4"] = media_atras(y, SEMANAS4, r.ok)
    m8, sd8 = media_atras(y, SEMANAS8, r.ok, con_desv=True)
    cols["m8"], cols["sd8"] = m8, sd8
    base = {"promedio_dia_hora": m8, "ultima_semana": np.where(np.isnan(cols["l7"]), m8, cols["l7"])}

    def obs(kk: int) -> np.ndarray:     # ventana observada de kk bloques que termina en t - latencia
        if latencia == 0:
            return v.pasado(kk)
        return (v.cs[np.maximum(v.t - latencia, 0)] - v.cs[np.maximum(v.t - latencia - kk, 0)]).astype(np.float32)

    base["persistencia"] = obs(k)                               # lo que subió en los h minutos anteriores
    if conjunto != "semanal":
        cols["ayer"] = atras(y, 1, r.ok)
        cols["m7d"] = media_atras(y, range(1, 8), r.ok)
        for nombre, kk in (("p15", 1), ("p30", 2), ("p60", 4), ("p120", 8)):
            cols[nombre] = obs(kk)
        hoy = (v.cs[np.maximum(v.t - latencia, v.t0)] - v.cs[v.t0]).astype(np.float32)
        cols["hoy"] = hoy
        cols["e120"] = media_atras(cols["p120"], SEMANAS4, r.ok)     # lo habitual en esa misma ventana
        cols["ehoy"] = media_atras(hoy, SEMANAS4, r.ok)
        # hoy frente a lo habitual (un árbol no divide solo)
        cols["r120"] = (cols["p120"] + 1) / (cols["e120"] + 1)
        cols["rhoy"] = (hoy + 1) / (cols["ehoy"] + 1)
        if nivel != "ruta":                                          # el estado de la ruta entera
            cols.update(_variables_de_la_ruta(r, v, k, latencia, d, i, g))
    if conjunto == "completo":
        _variables_de_la_oferta(r, v, cols, nivel, k, latencia, d, i, g)
    # --- calendario, instante y descripción del grupo
    for c in CALENDARIO:
        cols[c] = np.broadcast_to(r.cal[c].to_numpy(np.float32)[:, None, None], (d, i, g))
    cols["instante"] = np.broadcast_to(INSTANTES.astype(np.float32)[None, :, None], (d, i, g))
    if nivel == "sentido":
        cols["sentido"] = np.broadcast_to(np.arange(g, dtype=np.float32)[None, None, :], (d, i, g))
    if nivel == "segmento":
        cols["nro_segmento"] = np.broadcast_to(r.seg["nro_segmento"].to_numpy(np.float32)[None, None, :], (d, i, g))
        regreso = (r.seg["sentido"] == "regreso").to_numpy(np.float32)
        cols["sentido"] = np.broadcast_to(regreso[None, None, :], (d, i, g))
        minutos = r.seg["minutos_desde_inicio"].to_numpy(np.float32)
        cols["minutos_desde_inicio"] = np.broadcast_to(minutos[None, None, :], (d, i, g))
    nombres = list(cols)
    x = np.empty((d * i * g, len(nombres)), np.float32)
    for j, c in enumerate(nombres):
        x[:, j] = cols[c].reshape(-1)
    dia = np.repeat(np.arange(d, dtype=np.int32), i * g)
    inst = np.tile(np.repeat(INSTANTES.astype(np.int16), g), d)
    grupo = np.tile(np.arange(g, dtype=np.int16), d * i)
    return {"x": x, "nombres": nombres, "y": y.reshape(-1), "dia": dia, "instante": inst, "grupo": grupo,
            "base": {n: a.reshape(-1) for n, a in base.items()}, "ok": r.ok[dia], "forma": (d, i, g)}


def filas(v: dict, periodo: str) -> np.ndarray:
    """Filas del periodo que se pueden entrenar y evaluar: día con datos, pasado el arranque y con la línea base del
    promedio por día y hora disponible (las mismas filas para todos los modelos)."""
    a, b = rango_dias(periodo)
    a = max(a, ARRANQUE)
    return (v["dia"] >= a) & (v["dia"] <= b) & v["ok"] & ~np.isnan(v["base"]["promedio_dia_hora"])


# ---------------------------------------------------------------------------------------------------- banda P10-P90
def conformal_aplicar(p: np.ndarray, cal: dict) -> tuple[np.ndarray, np.ndarray]:
    """Banda P10-P90 conformal por tramo del pronóstico (Mondrian), con los cuantiles del puntaje
    (y - p) / raíz(p + 1) ajustados en la validación (pronostico_corto_plazo/validar.py)."""
    p = np.asarray(p, float)
    tramo = np.searchsorted(np.asarray(cal["cortes"]), p)
    q = cal["q"]
    usar = np.array([q[int(t)] if int(t) in q else q[str(int(t))] for t in range(len(cal["cortes"]) + 1)])
    esc = np.sqrt(p + 1)
    return np.clip(p + usar[tramo, 0] * esc, 0, None), p + usar[tramo, 1] * esc


# ---------------------------------------------------------------------------------------------------- métricas
def metricas(y: np.ndarray, p: np.ndarray) -> dict:
    y, p = np.asarray(y, float), np.asarray(p, float)
    if len(y) == 0 or y.sum() == 0:
        return {"n": int(len(y))}
    e = p - y
    den = np.abs(p) + np.abs(y)
    smape = np.where(den > 0, 2 * np.abs(e) / np.where(den > 0, den, 1), 0.0).mean() * 100
    return {"n": int(len(y)), "mae": round(float(np.abs(e).mean()), 3),
            "rmse": round(float(np.sqrt((e ** 2).mean())), 3),
            "wape": round(float(np.abs(e).sum() / y.sum() * 100), 3), "smape": round(float(smape), 3),
            "sesgo_pct": round(float((p.sum() / y.sum() - 1) * 100), 3), "media_real": round(float(y.mean()), 3)}


def franja_de(instante: int) -> str | None:
    """La franja de un instante (bloque de 15 minutos del día)."""
    for nombre, a, b in FRANJAS:
        if a <= instante < b:
            return nombre
    return None
