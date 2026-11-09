# Copia de experimentos/D5_optimizacion_milp/milp.py del proyecto. Único cambio deliberado: resolver_dia(...,
# devolver_detalle=True) pasó a ser resolver_dia_detalle(...) para que cada función devuelva tuplas del mismo largo
# (SonarQube python:S8495). La formulación del MILP no cambia; detalle y huellas SHA-256 en PROCEDENCIA.md.
"""D5 · núcleo del modelo de optimización (MILP) de salidas por hora.

Un problema por ruta × día: para cada hora h (4-20) se elige exactamente un nivel k de salidas válidas (binaria y[h,k]).
Todo el costo no lineal (espera, sobrecarga esperada) se precalcula por (h, k), así que el modelo es lineal.
"""
import numpy as np
import pulp
from scipy.stats import norm

HORAS = np.arange(4, 21)
T_FLOTA = np.round(np.arange(4.25, 24.01, 0.25), 2)  # instantes donde se cuentan los buses en ruta (cada 15 min)


def sobrecarga_lognormal(mu, s, cap_total):
    """E[(L - c)^+] con L ~ lognormal(mu, s). Vectorizado en c (c > 0)."""
    c = np.maximum(np.asarray(cap_total, float), 1e-9)
    s = max(float(s), 1e-6)
    d1 = (mu + s ** 2 - np.log(c)) / s
    d2 = d1 - s
    return np.exp(mu + s ** 2 / 2) * norm.cdf(d1) - c * norm.cdf(d2)


def fracciones_en_ruta(ciclo_min):
    """fr[h, t]: fracción de las salidas de la hora h (uniformes dentro de la hora) que siguen en ruta en el instante t,
    con el ciclo de esa hora (método de la simulación de D1/D2)."""
    h = HORAS[:, None].astype(float)
    c = np.asarray(ciclo_min, float)[:, None] / 60
    t = T_FLOTA[None, :]
    return np.clip(np.minimum(h + 1, t) - np.maximum(h, t - c), 0, 1)


def costos_por_nivel(entr, P, modo="estocastico"):
    """Para una hora (dict `entr`) devuelve niveles k y los cuatro componentes de costo (COP) de cada nivel.
    entr: minutos (operados), nmin, nmax, ciclo, km, cv, pax (previstos), mu, s (lognormal de la carga crítica),
          k0 (oferta de referencia), cap (capacidad por bus)."""
    k = np.arange(entr["nmin"], entr["nmax"] + 1)
    kf = k.astype(float)
    op = kf * entr["ciclo"] / 60 * P["COSTO_BUS_HORA"] + kf * entr["km"] * P["COSTO_KM"]
    with np.errstate(divide="ignore", invalid="ignore"):
        espera_min = np.where(kf > 0, entr["minutos"] / np.maximum(kf, 1) / 2 * (1 + entr["cv"] ** 2), 0.0)
    wait = entr["pax"] * espera_min / 60 * P["VALOR_TIEMPO_ESPERA"]
    capk = kf * entr["cap"]
    if modo == "deterministico":
        over_pax = np.maximum(entr["p50"] - capk, 0)
    elif modo == "estocastico":
        over_pax = np.where(capk > 0, sobrecarga_lognormal(entr["mu"], entr["s"], np.maximum(capk, 1e-9)),
                            np.exp(entr["mu"] + entr["s"] ** 2 / 2))
    else:  # "estocastico_irregular"
        # La carga no se reparte igual entre los buses: cada bus lleva (L / k) x R, con R lognormal de media 1 y CV = cv de los
        # intervalos (la carga de un bus es proporcional al intervalo que lo precede). Sobrecarga total = k x E[(L R / k - cap)^+].
        s2r = np.log(1 + entr["cv"] ** 2)
        s_tot = np.sqrt(entr["s"] ** 2 + s2r)
        over_pax = np.array([kk * sobrecarga_lognormal(entr["mu"] - np.log(kk) - s2r / 2, s_tot, entr["cap"]) if kk > 0
                             else np.exp(entr["mu"] + entr["s"] ** 2 / 2) for kk in kf])
    over = P["PENALIDAD_SOBRECARGA"] * over_pax
    k0 = max(entr["k0"], 1.0)
    rev = entr["pax"] * P["ELASTICIDAD"] * (k0 - kf) / k0 * P["TARIFA"]
    return k, op, wait, over, rev


def resolver_dia(entradas, ciclo_horas, flota, P, modo="estocastico", solver="cbc"):
    """Resuelve el MILP de un día. `entradas` = lista de 17 dicts (horas 4..20). Devuelve (x, estado, holgura)."""
    x, estado, holg, _ = _resolver_milp(entradas, ciclo_horas, flota, P, modo, solver)
    return x, estado, holg


def resolver_dia_detalle(entradas, ciclo_horas, flota, P, modo="estocastico", solver="cbc"):
    """Igual que resolver_dia, más los cuatro componentes de costo (COP) del plan: (x, estado, holgura, componentes).

    Antes era resolver_dia(..., devolver_detalle=True); se separó para que cada función devuelva siempre una tupla del
    mismo largo (SonarQube python:S8495). El MILP y sus resultados no cambian (ver PROCEDENCIA.md)."""
    x, estado, holg, niveles = _resolver_milp(entradas, ciclo_horas, flota, P, modo, solver)
    comp = {}
    for nombre, idx in [("op", 1), ("espera", 2), ("sobrecarga", 3), ("ingreso", 4)]:
        comp[nombre] = float(sum(niveles[i][idx][list(niveles[i][0]).index(x[i])] for i in range(len(entradas))))
    return x, estado, holg, comp


def _resolver_milp(entradas, ciclo_horas, flota, P, modo, solver):
    """Núcleo común: arma y resuelve el MILP; devuelve (x, estado, holgura, niveles de costo por hora)."""
    prob = pulp.LpProblem("D5", pulp.LpMinimize)
    y = {}
    obj = []
    xexpr = []
    niveles = []
    for i, e in enumerate(entradas):
        k, op, wait, over, rev = costos_por_nivel(e, P, modo)
        tot = op + wait + over + rev
        niveles.append((k, op, wait, over, rev))
        vs = [pulp.LpVariable(f"y_{i}_{int(kk)}", cat="Binary") for kk in k]
        y[i] = vs
        prob += pulp.lpSum(vs) == 1, f"uno_{i}"
        obj.append(pulp.LpAffineExpression([(v, float(c)) for v, c in zip(vs, tot)]))
        xexpr.append(pulp.LpAffineExpression([(v, float(kk)) for v, kk in zip(vs, k)]))
    # suavidad: |x_h/frac_h - x_{h-1}/frac_{h-1}| <= DELTA, desde la transición (HORA_SUAVIDAD-1 -> HORA_SUAVIDAD)
    for i in range(1, len(entradas)):
        h = HORAS[i]
        a, b = entradas[i - 1], entradas[i]
        if h < P["HORA_INICIO_SUAVIDAD"] or a["minutos"] <= 0 or b["minutos"] <= 0:
            continue
        fa, fb = a["minutos"] / 60, b["minutos"] / 60
        prob += (1 / fb) * xexpr[i] - (1 / fa) * xexpr[i - 1] <= P["DELTA"], f"suave_sube_{i}"
        prob += (1 / fa) * xexpr[i - 1] - (1 / fb) * xexpr[i] <= P["DELTA"], f"suave_baja_{i}"
    # flota: buses en ruta en cada instante <= flota disponible (+ holgura muy penalizada para garantizar factibilidad)
    fr = fracciones_en_ruta(ciclo_horas)
    holguras = []
    for j, t in enumerate(T_FLOTA):
        col = fr[:, j]
        if col.max() <= 0:
            continue
        sl = pulp.LpVariable(f"holgura_{j}", lowBound=0)
        holguras.append(sl)
        prob += pulp.lpSum(float(col[i]) * xexpr[i] for i in range(len(entradas)) if col[i] > 0) - sl <= float(flota), f"flota_{j}"
    prob += pulp.lpSum(obj) + 1e8 * pulp.lpSum(holguras)
    if solver == "highs":
        sv = pulp.HiGHS(msg=False)
    else:
        sv = pulp.PULP_CBC_CMD(msg=0)
    prob.solve(sv)
    estado = pulp.LpStatus[prob.status]
    x = np.array([sum(int(kk) * (v.value() or 0) for kk, v in zip(niveles[i][0], y[i])) for i in range(len(entradas))])
    x = np.rint(x).astype(int)
    holg = float(sum((s.value() or 0) for s in holguras))
    return x, estado, holg, niveles


def resolver_rapido(entradas, ciclo_horas, flota, P, modo="estocastico"):
    """Solución exacta más rápida para los barridos de sensibilidad: programación dinámica sin flota; si su solución
    respeta la flota es también óptima del MILP; si no, se resuelve el MILP completo con CBC."""
    x, _ = resolver_dia_dp(entradas, P, modo)
    if (x @ fracciones_en_ruta(ciclo_horas)).max() <= flota + 1e-9:
        return x, "Optimal (DP)", 0.0
    return resolver_dia(entradas, ciclo_horas, flota, P, modo, "cbc")


def resolver_dia_dp(entradas, P, modo="estocastico"):
    """Verificación: programación dinámica exacta SIN la restricción de flota (solo suavidad y cotas)."""
    prev = None
    for i, e in enumerate(entradas):
        k, op, wait, over, rev = costos_por_nivel(e, P, modo)
        tot = op + wait + over + rev
        if prev is None:
            cur = {int(kk): (c, [int(kk)]) for kk, c in zip(k, tot)}
        else:
            h = HORAS[i]
            a = entradas[i - 1]
            cur = {}
            for kk, c in zip(k, tot):
                best = None
                for kp, (cp, path) in prev.items():
                    if h >= P["HORA_INICIO_SUAVIDAD"] and a["minutos"] > 0 and e["minutos"] > 0:
                        if abs(kk / (e["minutos"] / 60) - kp / (a["minutos"] / 60)) > P["DELTA"] + 1e-9:
                            continue
                    if best is None or cp < best[0]:
                        best = (cp, path)
                if best is not None:
                    cur[int(kk)] = (best[0] + c, best[1] + [int(kk)])
        prev = cur
    c, path = min(prev.values(), key=lambda v: v[0])
    return np.array(path), c
