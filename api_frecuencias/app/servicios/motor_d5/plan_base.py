"""Plan de un día (ruta x hora de salida) con el MILP de D5, para el laboratorio.

Versión reducida de sistema_tiempo_real/plan_base.py del proyecto. Lo que se conserva tal cual: entradas_d5 (formato de
milp.costos_por_nivel), oraculo_ruta (oráculo de D5 con la demanda y la carga realizadas), horario (salidas equiespaciadas
dentro de cada hora) y referencia. Lo que cambia:
- los insumos de 2025 se leen de datos/insumos_d5_2025.parquet, que preparar_datos.py arma con las mismas uniones que
  plan_base._decisiones(): decisiones_2025.parquet de D5 + pred_viajes_validos de E1 (h = 7) como oferta de referencia
  k0_plan + capacidad y distancia de D1 (parametros_operativos.parquet) + x_corrida_1 de
  costos/resultados/d5_reoptimizado_decisiones.parquet (columna x_D5_fuente);
- se puede elegir el pronóstico de demanda (regla manual, E1, modelo final E11 o híbrido E12) y el intervalo máximo;
- se resuelve una ruta a la vez (plan_ruta) y se guarda en caché el resultado de cada combinación de parámetros.

Pronóstico de otro modelo (como sistema_tiempo_real/motor.py, Motor.reoptimizar): D5 se calibró con el pronóstico de E1
(columna prediccion, pasajeros por hora, h = 7) y la carga crítica de cada hora es una lognormal (mu, s). Para planear con el
pronóstico de otro modelo se usa su predicción como pasajeros previstos y se corre la mediana de la carga en la misma
proporción, hora por hora: c = max(pred_modelo, 1) / max(pred_E1, 1); pax = pred_modelo; mu' = mu + log(c); s no cambia.
Con E1, c = 1 y el plan es exactamente el de plan_base.plan_dia.
"""
import time
from functools import lru_cache

import numpy as np
import pandas as pd

from . import comun as C
from . import milp

S_ORACULO = 0.02           # dispersión casi nula de la carga crítica en el oráculo (igual que D5, run.py: s_or)

MODELOS = {
    "B1": "Regla manual",
    "E1": "Primer modelo (E1)",
    "E11": "Modelo final (E11)",
    "E12": "Híbrido (E12)",
}


@lru_cache(maxsize=1)
def _insumos():
    d = pd.read_parquet(C.DATOS / "insumos_d5_2025.parquet")
    d["dia"] = pd.to_datetime(d["dia"])
    return d


@lru_cache(maxsize=1)
def _pronosticos():
    p = pd.read_parquet(C.DATOS / "pronosticos_2025.parquet")
    p["dia"] = pd.to_datetime(p["dia"])
    return p


def fechas_disponibles():
    """Días de 2025 que tienen insumos de D5 y pronósticos de los cuatro modelos."""
    a = set(_insumos()["dia"].unique())
    b = set(_pronosticos()["dia"].unique())
    return sorted(pd.Timestamp(x) for x in a & b)


def insumos(fecha, ruta, modelo="E12", imax=None):
    """Insumos de D5 de una ruta (17 horas, 4..20) para `fecha`, con el pronóstico de `modelo` y, si se da, el intervalo
    máximo `imax` (minutos) en lugar de la política por tipo de día (10 min laboral y sábado, 15 domingo y festivo)."""
    f = pd.Timestamp(fecha).normalize()
    d = _insumos()
    sub = d[(d["dia"] == f) & (d["ruta"] == ruta)].sort_values("hora").reset_index(drop=True)
    if len(sub) != len(C.HORAS):
        raise ValueError(f"No hay insumos de D5 para {ruta} el {f.date()}.")
    sub["pax_E1"] = sub["prediccion"].clip(lower=0)
    if modelo == "E1":
        sub["pax_pred"] = sub["pax_E1"]
        sub["c_modelo"] = 1.0
    else:
        p = _pronosticos()
        pm = p[(p["dia"] == f) & (p["ruta"] == ruta)].set_index("hora")[modelo].reindex(sub["hora"]).values
        if np.isnan(pm).any():
            raise ValueError(f"Falta el pronóstico de {MODELOS.get(modelo, modelo)} para {ruta} el {f.date()}.")
        c = np.clip(pm, 1, None) / np.clip(sub["pax_E1"].values, 1, None)
        sub["pax_pred"] = np.clip(pm, 0, None)
        sub["c_modelo"] = c
        sub["mu"] = sub["mu"].values + np.log(c)
    if imax is not None:
        imax = float(imax)
        M = sub["minutos"].values
        nmin = np.where(M > 0, np.ceil(M / imax - 1e-9), 0).astype(int)
        sub["nmin"] = nmin
        sub["nmax"] = np.maximum(sub["nmax"].values, nmin)
    return sub


def entradas_d5(sub, pax=None, mu=None, s=None, k0=None):
    """Convierte las filas de una ruta (17 horas) al formato de milp.costos_por_nivel (igual que entradas_de de D5)."""
    pax = sub["pax_pred"].values if pax is None else np.asarray(pax, float)
    mu = sub["mu"].values if mu is None else np.asarray(mu, float)
    s = sub["s"].values if s is None else np.asarray(s, float)
    k0 = sub["k0_plan"].values if k0 is None else np.asarray(k0, float)
    ent = []
    for i, r in enumerate(sub.itertuples(index=False)):
        ent.append({"minutos": float(r.minutos), "nmin": int(r.nmin), "nmax": int(r.nmax), "ciclo": float(r.ciclo), "km": float(r.dist),
                    "cv": float(r.cv_d4), "pax": max(float(pax[i]), 0.0), "mu": float(mu[i]), "s": float(s[i]),
                    "p50": float(np.exp(mu[i])), "k0": float(k0[i]), "cap": float(r.capacidad)})
    return ent


def oraculo_ruta(sub, P):
    """Oráculo de D5 con los parámetros P: el MILP resuelto con la demanda y la carga crítica realizadas (pasajeros = real;
    mediana de la carga = L_real donde se conoce, si no la prevista; s = 0,02; oferta de referencia k0 = salidas reales n_S0;
    método rápido: programación dinámica y MILP solo si viola la flota). Devuelve 17 enteros."""
    L = sub["L_real"].values.astype(float)
    mu_or = np.where(L > 0, np.log(np.clip(L, 1, None)), sub["mu"].values)
    k0_or = np.clip(sub["n_S0"].fillna(1).values, 1, None)
    ent = entradas_d5(sub, pax=sub["real"].fillna(0).clip(lower=0).values, mu=mu_or, s=np.full(len(sub), S_ORACULO), k0=k0_or)
    x, _, _ = milp.resolver_rapido(ent, sub["ciclo"].values, float(sub["flota_disp"].iloc[0]), P)
    return np.asarray(x).astype(int)


def horario(x, minutos, horas=C.HORAS):
    """Horario minuto a minuto de D5: salidas equiespaciadas dentro de cada hora y centradas en su subintervalo.
    Devuelve minutos desde medianoche (una salida de la hora h nunca pasa del minuto h:59)."""
    x = np.asarray(x).astype(int)
    out = []
    op = [h for h, xx in zip(horas, x) if xx > 0]
    if not op:
        return out
    primera = min(op)
    for h, xx, M in zip(horas, x, minutos):
        if xx <= 0:
            continue
        ini = (h + 1) * 60 - M if (h == primera and M < 60) else h * 60
        H = M / xx
        out += [min(int(np.floor(ini + (i + 0.5) * H + 0.5)), int(h) * 60 + 59) for i in range(xx)]
    return out


def referencia(P):
    """Columna con la que se compara el plan: x_D5_fuente (x_corrida_1) con los costos con fuente, x_D5 con los supuestos."""
    return "x_D5_fuente" if C.es_fuente(P) else "x_D5"


def _clave_P(P):
    return tuple(sorted((k, float(v)) for k, v in P.items() if isinstance(v, (int, float))))


@lru_cache(maxsize=512)
def _plan_cache(fecha, ruta, modelo, imax, claveP, fuente):
    P = C.param_d5(fuente=fuente)
    P.update(dict(claveP))
    t0 = time.perf_counter()
    sub = insumos(fecha, ruta, modelo, imax)
    ent = entradas_d5(sub)
    flota = float(sub["flota_disp"].iloc[0])
    x, estado, holg, comp = milp.resolver_dia_detalle(ent, sub["ciclo"].values, flota, P, solver="cbc")
    seg = time.perf_counter() - t0
    sub["x_plan"] = x
    sub["programar"] = np.ceil(sub["x_plan"] / (1 - sub["tasa_no_valido"].fillna(0)))
    return {"tabla": sub, "horario": horario(x, sub["minutos"].values), "flota": flota, "estado": estado, "holgura": holg,
            "componentes": comp, "segundos": seg, "tipo_dia": str(sub["tipo_dia"].iloc[0])}


@lru_cache(maxsize=512)
def _oraculo_cache(fecha, ruta, imax, claveP, fuente):
    P = C.param_d5(fuente=fuente)
    P.update(dict(claveP))
    sub = insumos(fecha, ruta, "E1", imax)
    return oraculo_ruta(sub, P)


def plan_ruta(fecha, ruta, P, modelo="E12", imax=None, oraculo=False):
    """Plan de una ruta para `fecha` con los parámetros P y el pronóstico de `modelo`. Devuelve dict con la tabla por hora
    (x_plan, programar y los insumos), el horario minuto a minuto, el estado del solver, los componentes del costo del
    objetivo y los segundos de cálculo (0 si vino de la caché). Con `oraculo`, la tabla trae x_oraculo."""
    f = pd.Timestamp(fecha).normalize().strftime("%Y-%m-%d")
    fuente = C.es_fuente(P)
    claveP = _clave_P(P)
    hit = _plan_cache.cache_info().hits
    t0 = time.perf_counter()
    r = _plan_cache(f, ruta, modelo, None if imax is None else float(imax), claveP, fuente)
    r = dict(r)
    r["tabla"] = r["tabla"].copy()
    r["de_cache"] = _plan_cache.cache_info().hits > hit
    r["segundos_llamada"] = time.perf_counter() - t0
    ref = referencia(P)
    tb = r["tabla"]
    r["referencia"] = ref
    if tb[ref].notna().all():
        tb["coincide_ref"] = tb["x_plan"] == tb[ref]
    if oraculo:
        tb["x_oraculo"] = _oraculo_cache(f, ruta, None if imax is None else float(imax), claveP, fuente)
    return r
