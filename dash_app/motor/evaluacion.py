"""Contabilidad ex post de un día (con la demanda realizada), igual para el plan, la oferta real y el oráculo.

Copia de evaluar() de experimentos/D5_optimizacion_milp/run.py (sección 2, «Contabilidad ex post»), aplicada a un solo
día y a una o varias rutas: mismas fórmulas, sin anualizar.
- espera media (min) = minutos operados / salidas / 2 × (1 + CV²), ponderada por los pasajeros reales de cada hora;
- pasajeros sobre la capacidad = max(carga crítica real − 50 × salidas, 0), sumado en las horas con carga medida;
- pasajeros ganados o perdidos = pasajeros reales × elasticidad × (salidas − salidas reales) / salidas reales.
"""
import numpy as np


def evaluar(base, n, P):
    """`base`: filas ruta x hora de un día (insumos de D5); `n`: salidas por fila. Devuelve un dict con las cifras del día."""
    n = np.asarray(n, float)
    M = base["minutos"].values
    pax = base["real"].values
    cv = base["cv_d4"].values
    cap = base["capacidad"].values
    with np.errstate(divide="ignore", invalid="ignore"):
        esp = np.where(n > 0, M / np.where(n > 0, n, 1) / 2 * (1 + cv ** 2), np.nan)
    ok = (n > 0) & (pax > 0) & np.isfinite(esp)
    bh = n * base["ciclo"].values / 60
    km = n * base["dist"].values
    L = base["L_real"].values
    conL = np.isfinite(L)
    sobre = np.where(conL, np.maximum(L - cap * n, 0), 0.0)
    with np.errstate(divide="ignore", invalid="ignore"):
        fc = np.where(conL & (n > 0), L / (cap * np.where(n > 0, n, 1)), np.where(conL & (L > 0), np.inf, np.nan))
    n0 = base["n_S0"].values
    with np.errstate(divide="ignore", invalid="ignore"):
        dP = np.where(n0 > 0, pax * P["ELASTICIDAD"] * (n - n0) / np.where(n0 > 0, n0, 1), 0.0)
    costo_op = (bh * P["COSTO_BUS_HORA"] + km * P["COSTO_KM"]).sum()
    costo_espera = np.nansum(np.where(ok, pax * esp / 60 * P["VALOR_TIEMPO_ESPERA"], 0))
    fc_val = fc[np.isfinite(fc) | np.isinf(fc)]
    return {
        "salidas": float(n.sum()),
        "programadas": float(np.ceil(n / (1 - base["tasa_no_valido"].fillna(0).values)).sum()),
        "buses_hora": float(bh.sum()),
        "km": float(km.sum()),
        "costo_operativo": float(costo_op),
        "espera_media_min": float((esp[ok] * pax[ok]).sum() / pax[ok].sum()) if ok.any() else float("nan"),
        "costo_espera": float(costo_espera),
        "pax_sobre_capacidad": float(sobre.sum()),
        "pct_horas_fc_mayor_1": float((fc_val > 1).mean() * 100) if len(fc_val) else float("nan"),
        "pax_ganados": float(dP.sum()),
        "pax_perdidos": float(-np.minimum(dP, 0).sum()),
        "pax_ganados_bruto": float(np.maximum(dP, 0).sum()),
        "ingreso_neto_elasticidad": float(dP.sum() * P["TARIFA"]),
        "pasajeros_reales": float(np.nansum(pax)),
    }
