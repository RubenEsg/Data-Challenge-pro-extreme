"""Pronóstico de corto plazo (30, 60 y 120 minutos) por ruta, sentido y segmento: datos, variables, líneas base,
modelo, métricas e intervalos. Lo usan validar.py (elegir) y probar.py (reportar una sola vez). Ver PROTOCOLO.md.

El problema: en cada instante t (cada media hora, de 04:00 a 21:00) se pronostican las subidas de los siguientes 30, 60
y 120 minutos con lo observado hasta t. La unidad es el bloque de 15 minutos del instante en que ocurre la subida.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

AQUI = Path(__file__).resolve().parent
PANEL = AQUI / "panel"
RES = AQUI / "resultados"
RUTAS = {2: "SILENCIO", 16: "CRA 54", 21: "CL 72"}
BLOQUES = 96                                  # bloques de 15 minutos por día
INSTANTES = np.arange(16, 85, 2)              # 04:00, 04:30, ..., 21:00
HORIZONTES = {30: 2, 60: 4, 120: 8}           # minutos -> bloques
DIA0 = pd.Timestamp("2023-01-01")
N_DIAS = 1096                                 # 2023-01-01 a 2025-12-31
PERIODOS = {"entrenamiento": ("2023-01-01", "2024-12-31"), "validacion": ("2025-01-01", "2025-06-30"),
            "prueba": ("2025-07-01", "2025-12-31")}
ARRANQUE = 56                                 # días iniciales sin evaluar ni entrenar: la regla de 8 semanas necesita historia
UMBRAL_SIN_DATOS = 0.05                       # un día-ruta con menos del 5 % de lo habitual se trata como «sin datos»
SEMILLA = 42
HILOS = 5
FRANJAS = [("04-05", 16, 24), ("06-08 pico", 24, 36), ("09-16 valle", 36, 68), ("17-19 pico", 68, 80), ("20-21", 80, 88)]
NIVELES = ("ruta", "sentido", "segmento")
CALENDARIO = ["dia_semana", "tipo_dia", "festivo", "carnaval", "semana_santa", "vacaciones", "navidad", "primero_enero",
              "vac_escolar", "vac_univ", "mes", "dia_mes"]
HIPER = {"objective": "poisson", "learning_rate": 0.05, "n_estimators": 400, "num_leaves": 63, "min_child_samples": 100,
         "subsample": 0.8, "subsample_freq": 1, "colsample_bytree": 0.8, "reg_lambda": 1.0}


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


def dias_con_datos(total: np.ndarray) -> np.ndarray:
    """Un día-ruta «sin datos» tiene menos del 5 % de la mediana del mismo día de la semana de las 8 semanas anteriores
    (los últimos días de mes de 2025 no traen eventos de conteo). Sin semanas anteriores: basta con que tenga subidas."""
    d = len(total)
    ref = np.full((8, d), np.nan)
    for k in range(1, 9):
        ref[k - 1, 7 * k:] = total[:-7 * k]
    hay = ~np.isnan(ref).all(axis=0)
    med = np.full(d, np.nan)
    med[hay] = np.nanmedian(ref[:, hay], axis=0)
    return np.where(np.isnan(med), total > 0, total >= UMBRAL_SIN_DATOS * np.nan_to_num(med, nan=0.0)) & (total > 0)


def cargar_ruta(idruta: int) -> Ruta:
    seg = pd.read_csv(PANEL / "segmentos.csv")
    seg = seg[seg["idruta"] == idruta].sort_values("nro_segmento").reset_index(drop=True)
    s = len(seg)
    if not (seg["nro_segmento"].to_numpy() == np.arange(1, s + 1)).all():
        raise ValueError("los segmentos no están numerados de 1 a S")
    p = pd.read_parquet(PANEL / "subidas_segmento_15min.parquet", filters=[("idruta", "==", idruta)])
    d = (pd.to_datetime(p["dia"]) - DIA0).dt.days.to_numpy()
    y = np.zeros((N_DIAS, BLOQUES, s), np.float32)
    m = p["nro_segmento"].to_numpy() > 0
    np.add.at(y, (d[m], p["bloque"].to_numpy()[m], p["nro_segmento"].to_numpy()[m] - 1), p["subidas"].to_numpy()[m])
    q = pd.read_parquet(PANEL / "salidas_15min.parquet", filters=[("idruta", "==", idruta)])
    sal = np.zeros((N_DIAS, BLOQUES), np.float32)
    np.add.at(sal, ((pd.to_datetime(q["dia"]) - DIA0).dt.days.to_numpy(), q["bloque"].to_numpy()), q["salidas"].to_numpy())
    cal = pd.read_csv(PANEL / "calendario.csv", parse_dates=["fecha"])
    cal["dia_semana"] = cal["fecha"].dt.dayofweek
    cal["mes"] = cal["fecha"].dt.month
    cal["dia_mes"] = cal["fecha"].dt.day
    if len(cal) != N_DIAS:
        raise ValueError("el calendario no cubre los 1.096 días")
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
    """Sumas de ventana sobre los instantes de pronóstico, a partir de la suma acumulada de los bloques de 15 minutos."""

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


def variables(r: Ruta, nivel: str, h: int, conjunto: str, latencia: int = 0) -> dict:
    """Variables del nivel (ruta, sentido o segmento) para el horizonte h (minutos) y el conjunto de información:

    - «semanal»: calendario y el mismo instante de las semanas anteriores (lo que se sabe con 7 días de antelación).
    - «con_hoy»: además, ayer, la última semana día a día y lo observado HOY hasta t (últimos 15 a 120 minutos, lo
      acumulado del día y su comparación con lo habitual); en sentido y segmento, también lo observado en la ruta.
    - «completo»: además, la oferta ya despachada (salidas de las últimas horas y, por segmento, las que llegarán en la
      ventana) y, por segmento, lo observado en los segmentos vecinos.
    `latencia` (bloques de 15 min): lo observado solo se conoce hasta t - latencia (sensibilidad al retraso de la captura).
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
        cols["r120"] = (cols["p120"] + 1) / (cols["e120"] + 1)        # hoy frente a lo habitual (un árbol no divide solo)
        cols["rhoy"] = (hoy + 1) / (cols["ehoy"] + 1)
        if nivel != "ruta":                                          # el estado de la ruta entera
            vr = Ventanas(agrupar(r, "ruta"))
            yr = vr.futuro(k)

            def obs_r(kk: int) -> np.ndarray:
                return (vr.cs[np.maximum(vr.t - latencia, 0)] - vr.cs[np.maximum(vr.t - latencia - kk, 0)]).astype(np.float32)

            hoy_r = (vr.cs[np.maximum(vr.t - latencia, vr.t0)] - vr.cs[vr.t0]).astype(np.float32)
            ruta_cols = {"R_m4": media_atras(yr, SEMANAS4, r.ok), "R_p30": obs_r(2), "R_p60": obs_r(4), "R_p120": obs_r(8),
                         "R_hoy": hoy_r, "R_ehoy": media_atras(hoy_r, SEMANAS4, r.ok)}
            ruta_cols["R_rhoy"] = (ruta_cols["R_hoy"] + 1) / (ruta_cols["R_ehoy"] + 1)
            for nombre, a in ruta_cols.items():
                cols[nombre] = np.broadcast_to(a, (d, i, g))
    if conjunto == "completo":
        cs_s = np.concatenate([[0.0], np.cumsum(r.sal.reshape(-1))])
        t = v.t - latencia

        def salidas(desde: np.ndarray, hasta: np.ndarray) -> np.ndarray:    # salidas en [desde, hasta) ya ocurridas antes de t
            a, b = np.clip(desde, 0, None), np.clip(np.minimum(hasta, t), 0, None)
            return np.where(b > a, cs_s[b] - cs_s[a], 0.0).astype(np.float32)

        for nombre, kk in (("sal60", 4), ("sal120", 8), ("sal240", 16)):
            cols[nombre] = np.broadcast_to(salidas(t - kk, t)[:, :, None], (d, i, g))
        if nivel == "segmento":
            ret = np.round(r.seg["minutos_desde_inicio"].to_numpy() / 15).astype(int)      # bloques hasta el segmento
            llegan = np.empty((d, i, g), np.float32)
            pasaron = np.empty((d, i, g), np.float32)
            for j, lj in enumerate(ret):
                llegan[:, :, j] = salidas(v.t - lj, v.t - lj + k)       # salidas que pasarán por el segmento en la ventana
                pasaron[:, :, j] = salidas(v.t - lj - 2, v.t - lj)      # las que pasaron en la última media hora
            cols["sal_llegan"], cols["sal_pasaron"] = llegan, pasaron
            cols["sal_conocida"] = np.broadcast_to(np.clip((ret - latencia) / k, 0, 1).astype(np.float32)[None, None, :], (d, i, g))
            p30, p60, m4 = cols["p30"], cols["p60"], cols["m4"]

            def vecinos(a: np.ndarray, desde: int, hasta: int) -> np.ndarray:   # suma de los segmentos s+desde .. s+hasta
                out = np.zeros(a.shape, np.float32)
                for dj in range(desde, hasta + 1):
                    if dj < 0:
                        out[:, :, -dj:] += a[:, :, :dj]
                    elif dj > 0:
                        out[:, :, :-dj] += a[:, :, dj:]
                return out

            cols["arriba30"], cols["arriba60"] = vecinos(p30, -3, -1), vecinos(p60, -6, -1)   # los segmentos anteriores
            cols["abajo30"] = vecinos(p30, 1, 3)
            cols["vec_m4"] = vecinos(np.nan_to_num(m4), -2, 2) + np.nan_to_num(m4)
    # --- calendario, instante y descripción del grupo
    for c in CALENDARIO:
        cols[c] = np.broadcast_to(r.cal[c].to_numpy(np.float32)[:, None, None], (d, i, g))
    cols["instante"] = np.broadcast_to(INSTANTES.astype(np.float32)[None, :, None], (d, i, g))
    if nivel == "sentido":
        cols["sentido"] = np.broadcast_to(np.arange(g, dtype=np.float32)[None, None, :], (d, i, g))
    if nivel == "segmento":
        cols["nro_segmento"] = np.broadcast_to(r.seg["nro_segmento"].to_numpy(np.float32)[None, None, :], (d, i, g))
        cols["sentido"] = np.broadcast_to((r.seg["sentido"] == "regreso").to_numpy(np.float32)[None, None, :], (d, i, g))
        cols["minutos_desde_inicio"] = np.broadcast_to(r.seg["minutos_desde_inicio"].to_numpy(np.float32)[None, None, :], (d, i, g))
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


def ajustar(x: np.ndarray, y: np.ndarray, hiper: dict | None = None, semilla: int = SEMILLA):
    import lightgbm as lgb

    hp = dict(HIPER, **(hiper or {}))
    modelo = lgb.LGBMRegressor(**hp, random_state=semilla, n_jobs=HILOS, verbose=-1, deterministic=True, force_row_wise=True)
    return modelo.fit(x, y)


def pronosticar(r: Ruta, nivel: str, h: int, conjunto: str, entrenar=("entrenamiento",), predecir: str = "validacion",
                hiper: dict | None = None, submuestra: float = 1.0, latencia: int = 0, con_modelo: bool = False) -> dict:
    """Entrena con los periodos de `entrenar` y pronostica el periodo `predecir`. Devuelve arreglos (días del periodo,
    instantes, grupos) con lo real, el pronóstico y las líneas base; NaN donde la fila no se evalúa (día sin datos)."""
    t0 = reloj()
    v = variables(r, nivel, h, conjunto, latencia)
    tr = np.zeros(len(v["y"]), bool)
    for per in entrenar:
        tr |= filas(v, per)
    idx = np.flatnonzero(tr)
    if submuestra < 1:
        idx = np.sort(np.random.default_rng(SEMILLA).choice(idx, int(len(idx) * submuestra), replace=False))
    modelo = ajustar(v["x"][idx], v["y"][idx], hiper)
    a, b = rango_dias(predecir)
    d, i, g = v["forma"]
    tramo = slice(a * i * g, (b + 1) * i * g)
    vale = filas(v, predecir)[tramo]
    p = np.clip(modelo.predict(v["x"][tramo][vale]), 0, None)

    def denso(valores: np.ndarray) -> np.ndarray:
        out = np.full(vale.shape, np.nan, np.float32)
        out[vale] = valores
        return out.reshape(b - a + 1, i, g)

    out = {"y": denso(v["y"][tramo][vale]), "p": denso(p), "base": {n: denso(z[tramo][vale]) for n, z in v["base"].items()},
           "n_entrenamiento": int(len(idx)), "n_variables": len(v["nombres"]), "nombres": v["nombres"],
           "segundos": round(reloj() - t0, 1)}
    if con_modelo:
        out["modelo"] = modelo
    return out


def aplanar(*arreglos: np.ndarray) -> list[np.ndarray]:
    """Aplana arreglos (días, instantes, grupos) y deja solo las celdas en que ninguno es NaN; agrega el instante y el
    día de cada celda al final."""
    vale = ~np.isnan(arreglos[0])
    for a in arreglos[1:]:
        vale &= ~np.isnan(a)
    d, i, g = arreglos[0].shape
    inst = np.broadcast_to(INSTANTES[None, :, None], (d, i, g))[vale]
    dia = np.broadcast_to(np.arange(d)[:, None, None], (d, i, g))[vale]
    return [a[vale].astype(float) for a in arreglos] + [inst, dia]


# ---------------------------------------------------------------------------------------------------- métricas
def metricas(y: np.ndarray, p: np.ndarray) -> dict:
    y, p = np.asarray(y, float), np.asarray(p, float)
    if len(y) == 0 or y.sum() == 0:
        return {"n": int(len(y))}
    e = p - y
    den = np.abs(p) + np.abs(y)
    smape = np.where(den > 0, 2 * np.abs(e) / np.where(den > 0, den, 1), 0.0).mean() * 100
    return {"n": int(len(y)), "mae": round(float(np.abs(e).mean()), 3), "rmse": round(float(np.sqrt((e ** 2).mean())), 3),
            "wape": round(float(np.abs(e).sum() / y.sum() * 100), 3), "smape": round(float(smape), 3),
            "sesgo_pct": round(float((p.sum() / y.sum() - 1) * 100), 3), "media_real": round(float(y.mean()), 3)}


def franja_de(instante: np.ndarray) -> np.ndarray:
    out = np.empty(len(instante), dtype=object)
    for nombre, a, b in FRANJAS:
        out[(instante >= a) & (instante < b)] = nombre
    return out


def por_franja(y, p, instante) -> dict:
    fr = franja_de(instante)
    out = {n: metricas(y[fr == n], p[fr == n]) for n, _, _ in FRANJAS}
    pico = np.isin(fr, ["06-08 pico", "17-19 pico"])
    out["pico"], out["valle"] = metricas(y[pico], p[pico]), metricas(y[~pico], p[~pico])
    return out


def bootstrap_wape(dia: np.ndarray, y: np.ndarray, preds: dict, ref: str, b: int = 2000, bloque: int = 7,
                   semilla: int = SEMILLA) -> dict:
    """IC95 del WAPE de cada pronóstico y de su diferencia con `ref`, por bootstrap de bloques móviles de 7 días.
    Trabaja con las sumas por día de |error| y de lo real, así que sirve igual con millones de filas."""
    dias = np.unique(dia)
    pos = np.searchsorted(dias, dia)
    den = np.bincount(pos, weights=y, minlength=len(dias))
    num = {k: np.bincount(pos, weights=np.abs(p - y), minlength=len(dias)) for k, p in preds.items()}
    rng = np.random.default_rng(semilla)
    n_bloques = int(np.ceil(len(dias) / bloque))
    ini = rng.integers(0, max(len(dias) - bloque + 1, 1), size=(b, n_bloques))
    idx = (ini[:, :, None] + np.arange(bloque)[None, None, :]).reshape(b, -1)
    idx = np.minimum(idx, len(dias) - 1)
    d = den[idx].sum(axis=1)
    w = {k: v[idx].sum(axis=1) / d * 100 for k, v in num.items()}
    out = {k: {"ic95": [round(float(np.quantile(x, 0.025)), 2), round(float(np.quantile(x, 0.975)), 2)]} for k, x in w.items()}
    for k, x in w.items():
        if k != ref:
            dif = x - w[ref]
            out[f"{k}_menos_{ref}"] = {"ic95": [round(float(np.quantile(dif, 0.025)), 2), round(float(np.quantile(dif, 0.975)), 2)],
                                      "p_mejora": round(float((dif < 0).mean()), 4)}
    out["dias"], out["B"], out["bloque_dias"] = int(len(dias)), b, bloque
    return out


# ---------------------------------------------------------------------------------------------------- intervalos
def conformal_ajustar(y: np.ndarray, p: np.ndarray, n_tramos: int = 4) -> dict:
    """Banda P10-P90 conformal por tramo del pronóstico (Mondrian): cuantiles 10 % y 90 % del puntaje (y - p) / raíz(p + 1)."""
    cortes = np.unique(np.quantile(p, np.linspace(0, 1, n_tramos + 1)[1:-1]))
    tramo = np.searchsorted(cortes, p)
    s = (y - p) / np.sqrt(p + 1)
    q = {int(t): [float(np.quantile(s[tramo == t], 0.10)), float(np.quantile(s[tramo == t], 0.90))] for t in np.unique(tramo)}
    return {"cortes": [float(c) for c in cortes], "q": q}


def conformal_aplicar(p: np.ndarray, cal: dict) -> tuple[np.ndarray, np.ndarray]:
    tramo = np.searchsorted(np.asarray(cal["cortes"]), p)
    q = cal["q"]
    usar = np.array([q[int(t)] if int(t) in q else q[str(int(t))] for t in range(len(cal["cortes"]) + 1)])
    esc = np.sqrt(p + 1)
    return np.clip(p + usar[tramo, 0] * esc, 0, None), p + usar[tramo, 1] * esc


def cobertura(y, lo, hi) -> dict:
    return {"cobertura_pct": round(float(((y >= lo) & (y <= hi)).mean() * 100), 2),
            "bajo_p10_pct": round(float((y < lo).mean() * 100), 2), "sobre_p90_pct": round(float((y > hi).mean() * 100), 2),
            "ancho_medio": round(float((hi - lo).mean()), 2)}


def reloj() -> float:
    return time.perf_counter()
