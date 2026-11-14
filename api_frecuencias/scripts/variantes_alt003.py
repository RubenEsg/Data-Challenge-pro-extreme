"""ALT-003 de pronóstico (frecuencia insuficiente, §5.2): diagnóstico y elección SIN FUGA del umbral (§9.3, §18).

Cada fila es una franja del backtest de pronóstico (scripts/backtest_alertas.py --pronostico): la carga crítica
lognormal del optimizador (mediana = factor de carga × demanda por hora, σ_log de la banda P10-P90 calibrada), la
capacidad efectiva de la frecuencia ACTUAL (buses/h × puestos × ocupación objetivo máxima), si la frecuencia actual
cumple el nivel de servicio, si en esa franja salió ALT-001 y lo REAL de esa hora. Una franja es «positiva» si la carga
crítica real (factor × pasajeros reales) superó la capacidad efectiva: la condición que ALT-003 anuncia.

Diagnóstico: ALT-003 nunca se emite en una franja donde sale ALT-001 (§18, una alerta por fenómeno: ALT-001 la
incluye). Su tasa base correcta es la de las franjas donde SÍ puede emitirse (sin ALT-001): compararla con la tasa base
de todas las franjas mezcla las de ALT-001, que son las de más riesgo, y castiga a ALT-003 por construcción.

Protocolo (declarado antes de evaluar):
- variantes: alertar si la frecuencia actual no cumple el nivel de servicio y P(carga crítica > capacidad efectiva) ≥ p,
  con p en CANDIDATOS (ANTERIOR = 0,10 es la regla sin mínimo: basta no cumplir el nivel de servicio 0,90);
- ventana de VALIDACIÓN estrictamente anterior a la de EVALUACIÓN (corte por fecha);
- se elige, en validación, la variante de mayor lift (precisión / tasa base de las franjas donde puede emitirse) entre
  las que tienen al menos N_MIN_VALIDACION alertas; se adopta solo si ese lift supera 1;
- en evaluación se reportan la precisión, las dos tasas base y los dos lifts con un intervalo bootstrap del 95 %
  (remuestreo de días completos, las rutas del día juntas).
Si ninguna variante supera la tasa base en validación, ALT-003 de pronóstico baja a informativa.
"""
from __future__ import annotations

import math
from datetime import date

import numpy as np

CANDIDATOS = (0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.50)
ANTERIOR = 0.10                 # la regla anterior: solo el nivel de servicio 0,90 del optimizador
N_MIN_VALIDACION = 20
REMUESTREOS = 2000
SEMILLA = 20251101
# validación 15/09-31/10/2025 (47 días) y evaluación 01/11-31/12/2025 (61 días), ambas después del corte del modelo
CORTE_VALIDACION = date(2025, 10, 31)


def corte_de(desde: date, hasta: date) -> date:
    """Último día de la validación: CORTE_VALIDACION si cae dentro del periodo; si no, la mitad del periodo."""
    if desde <= CORTE_VALIDACION < hasta:
        return CORTE_VALIDACION
    return desde + (hasta - desde) // 2


def probabilidad(fila: dict) -> float | None:
    """P(carga crítica > capacidad efectiva) de una fila (la misma cuenta de alertas.probabilidad_sobre_capacidad)."""
    from app.servicios import alertas

    return alertas.probabilidad_sobre_capacidad(fila.get("carga_mediana"), fila.get("sigma_log"),
                                                fila.get("capacidad_efectiva"))


def dispara(fila: dict, umbral: float) -> bool:
    """La regla de alertas._alt003 con mínimo `umbral`: la frecuencia actual no cumple el nivel de servicio y la
    probabilidad de superar la capacidad efectiva llega al mínimo (sin probabilidad, basta el nivel de servicio)."""
    if fila.get("cumple_nivel_servicio") is True:
        return False
    return fila["prob"] is None or fila["prob"] >= umbral


def _r(x, d=4):
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else round(float(x), d)


def _tasa(filas: list[dict]) -> float | None:
    return float(np.mean([f["positiva"] for f in filas])) if filas else None


def _metricas(filas: list[dict], umbral: float) -> dict:
    """Alertas, confirmadas, precisión y lifts de la variante `umbral` sobre unas filas (con la supresión de §18)."""
    elegibles = [f for f in filas if not f["alt001"]]
    alertas = [f for f in elegibles if dispara(f, umbral)]
    n, conf = len(alertas), sum(f["positiva"] for f in alertas)
    base, base_e = _tasa(filas), _tasa(elegibles)
    prec = conf / n if n else None
    return {"alertas": n, "confirmadas": int(conf), "precision": _r(prec), "tasa_base": _r(base),
            "lift": _r(prec / base if prec is not None and base else None, 3),
            "tasa_base_elegible": _r(base_e),
            "lift_elegible": _r(prec / base_e if prec is not None and base_e else None, 3),
            "franjas": len(filas), "franjas_elegibles": len(elegibles)}


def _por_dia(filas: list[dict]) -> dict:
    dias: dict = {}
    for f in filas:
        dias.setdefault(f["fecha"], []).append(f)
    return dias


def intervalo(filas: list[dict], umbral: float, clave: str, remuestreos: int = REMUESTREOS,
              semilla: int = SEMILLA) -> list[float] | None:
    """IC bootstrap del 95 % de `clave` (lift o lift_elegible): días completos remuestreados con reemplazo (las rutas
    del mismo día van juntas). None si en la mitad de los remuestreos no hay alertas con qué medirlo."""
    dias = list(_por_dia(filas).values())
    if not dias:
        return None
    rng = np.random.default_rng(semilla)
    valores = []
    for _ in range(remuestreos):
        muestra = [f for i in rng.integers(0, len(dias), len(dias)) for f in dias[i]]
        v = _metricas(muestra, umbral)[clave]
        if v is not None:
            valores.append(v)
    if len(valores) < remuestreos // 2:
        return None
    return [round(float(np.percentile(valores, 2.5)), 3), round(float(np.percentile(valores, 97.5)), 3)]


def elegir(validacion: dict) -> float | None:
    """La variante de mayor lift elegible en validación con al menos N_MIN_VALIDACION alertas (a igual lift, la de
    menor p); None si ese lift no supera 1 (entonces ALT-003 de pronóstico baja a informativa)."""
    aptas = [(m["lift_elegible"], -p, p) for p, m in validacion.items()
             if m["alertas"] >= N_MIN_VALIDACION and m["lift_elegible"] is not None]
    if not aptas:
        return None
    lift, _, p = max(aptas)
    return p if lift > 1 else None


def preparar(filas: list[dict]) -> list[dict]:
    """Agrega a cada fila su probabilidad y si fue positiva (carga crítica real > capacidad efectiva); descarta las
    franjas sin dato real o sin capacidad efectiva."""
    salida = []
    for f in filas:
        if f.get("real") is None or not f.get("capacidad_efectiva"):
            continue
        g = dict(f)
        g["prob"] = probabilidad(f)
        g["positiva"] = float(f["factor_carga"]) * float(f["real"]) > float(f["capacidad_efectiva"])
        salida.append(g)
    return salida


def evaluar(filas: list[dict], corte: date, candidatos=CANDIDATOS, adoptada: float | None = None) -> dict:
    """El protocolo completo: métricas de cada variante en validación (fecha <= corte) y en evaluación (fecha >
    corte), la elegida y sus intervalos en evaluación (y los de la regla anterior y, si se da, los de la adoptada en
    threshold_config, para comparar)."""
    filas = preparar(filas)
    val = [f for f in filas if f["fecha"] <= str(corte)]
    ev = [f for f in filas if f["fecha"] > str(corte)]
    candidatos = tuple(sorted(set(candidatos) | ({adoptada} if adoptada is not None else set())))
    tabla = {p: {"validacion": _metricas(val, p), "evaluacion": _metricas(ev, p)} for p in candidatos}
    elegida = elegir({p: t["validacion"] for p, t in tabla.items()})
    salida = {"corte_validacion": str(corte), "candidatos": list(candidatos), "anterior": ANTERIOR,
              "adoptada": adoptada, "n_min_validacion": N_MIN_VALIDACION, "remuestreos": REMUESTREOS,
              "semilla": SEMILLA, "ventanas": {"validacion": _rango(val), "evaluacion": _rango(ev)},
              "variantes": {f"{p:.2f}": t for p, t in tabla.items()}, "elegida": elegida,
              "decision": "adoptar" if elegida is not None else "informativa"}
    for nombre, p in (("elegida", elegida), ("anterior", ANTERIOR), ("adoptada", adoptada)):
        if p is not None:
            salida[f"intervalos_{nombre}"] = {k: intervalo(ev, p, k) for k in ("lift", "lift_elegible")}
    salida["diagnostico"] = diagnostico(filas)
    return salida


def _rango(filas: list[dict]) -> list[str] | None:
    fechas = sorted({f["fecha"] for f in filas})
    return [fechas[0], fechas[-1]] if fechas else None


def diagnostico(filas: list[dict]) -> dict:
    """Por qué la regla anterior quedaba bajo la tasa base de todas las franjas: dónde caen las positivas."""
    def anterior(f):
        return not f["alt001"] and dispara(f, ANTERIOR)

    con_001 = [f for f in filas if f["alt001"]]
    alt003 = [f for f in filas if anterior(f)]
    sin = [f for f in filas if not f["alt001"] and not anterior(f)]
    por_ruta = {}
    for ruta in sorted({f["ruta"] for f in filas}):
        g = [f for f in filas if f["ruta"] == ruta]
        por_ruta[ruta] = {"franjas": len(g), "tasa_base": _r(_tasa(g)), "con_alt001": sum(f["alt001"] for f in g),
                          "alt003_anterior": sum(1 for f in g if anterior(f)),
                          "positivas_alt003_anterior": _r(_tasa([f for f in g if anterior(f)]))}
    return {"franjas": len(filas), "tasa_base": _r(_tasa(filas)),
            "con_alt001": {"franjas": len(con_001), "positivas": _r(_tasa(con_001))},
            "alt003_anterior": {"franjas": len(alt003), "positivas": _r(_tasa(alt003))},
            "sin_alerta": {"franjas": len(sin), "positivas": _r(_tasa(sin))},
            "senal_frecuencia_insuficiente": {
                "franjas": len(con_001) + len(alt003), "positivas": _r(_tasa(con_001 + alt003)),
                "nota": "ALT-003 sola o incluida en ALT-001 (variables.incluye_alt003): lo que ve el operador"},
            "por_ruta": por_ruta}


def _c(x, d=3):
    return "—" if x is None else f"{x:.{d}f}".replace(".", ",")


def _ventana(r: dict, nombre: str) -> str:
    v = r["ventanas"].get(nombre)
    return "sin días" if not v else f"{v[0]} a {v[1]}"


def _ic(par):
    return "—" if not par else f"[{_c(par[0], 2)}; {_c(par[1], 2)}]"


def _marca(p: str, r: dict) -> str:
    """« (elegida y adoptada)», « (anterior)»…: qué es cada variante de la tabla."""
    etiquetas = [nombre for nombre in ("elegida", "adoptada", "anterior") if float(p) == r.get(nombre)]
    return f" ({' y '.join(etiquetas)})" if etiquetas else ""


def informe(r: dict, titulo: str) -> list[str]:
    """Líneas Markdown del diagnóstico y de la elección (backtest_alertas_pronostico.md y la robustez por hora)."""
    d = r["diagnostico"]
    lin = [f"## {titulo}", "",
           f"{d['franjas']} franjas; tasa base (carga crítica real > capacidad efectiva): {_c(d['tasa_base'])}. Con "
           f"ALT-001 en la misma franja: {d['con_alt001']['franjas']} franjas, {_c(d['con_alt001']['positivas'])} "
           "positivas (ahí ALT-003 no se emite: ALT-001 la incluye, §18). La regla anterior de ALT-003 (solo el nivel "
           f"de servicio) en las demás: {d['alt003_anterior']['franjas']} franjas, "
           f"{_c(d['alt003_anterior']['positivas'])} positivas. Sin alerta: {d['sin_alerta']['franjas']} franjas, "
           f"{_c(d['sin_alerta']['positivas'])} positivas. La señal de frecuencia insuficiente que ve el operador "
           f"(ALT-003 sola o dentro de ALT-001): {_c(d['senal_frecuencia_insuficiente']['positivas'])} positivas en "
           f"{d['senal_frecuencia_insuficiente']['franjas']} franjas.", "",
           f"Validación {_ventana(r, 'validacion')}; evaluación {_ventana(r, 'evaluacion')}. Variante: alertar si la "
           "frecuencia actual no cumple el nivel de servicio y P(carga crítica > capacidad efectiva) ≥ p. «Elegible» = "
           "franjas donde ALT-003 puede emitirse (sin ALT-001).",
           "", "| p | Validación: alertas | precisión | lift | lift elegible | Evaluación: alertas | precisión | "
               "lift | lift elegible |", "|---|---|---|---|---|---|---|---|---|"]
    for p, t in r["variantes"].items():
        v, e = t["validacion"], t["evaluacion"]
        lin.append(f"| {p.replace('.', ',')}{_marca(p, r)} | {v['alertas']} | {_c(v['precision'])} | "
                   f"{_c(v['lift'], 2)} | {_c(v['lift_elegible'], 2)} | {e['alertas']} | {_c(e['precision'])} | "
                   f"{_c(e['lift'], 2)} | {_c(e['lift_elegible'], 2)} |")
    return lin + ["", _decision(r), _adoptada(r), ""]


def _medida(r: dict, p: float, nombre: str) -> str:
    """«N alertas, precisión x, lift elegible y [IC] y lift z [IC]» de la variante p en la ventana de evaluación."""
    e = r["variantes"][f"{p:.2f}"]["evaluacion"]
    ic = r.get(f"intervalos_{nombre}") or {}
    return (f"{e['alertas']} alertas, precisión {_c(e['precision'])}, lift elegible {_c(e['lift_elegible'], 2)} "
            f"{_ic(ic.get('lift_elegible'))} y lift sobre todas las franjas {_c(e['lift'], 2)} {_ic(ic.get('lift'))}")


def _decision(r: dict) -> str:
    if r["elegida"] is None:
        return ("Ninguna variante supera la tasa base elegible en validación con al menos "
                f"{r['n_min_validacion']} alertas: ALT-003 de pronóstico baja a informativa.")
    return (f"Elegida en validación: p = {_c(r['elegida'], 2)} (mayor lift elegible con al menos "
            f"{r['n_min_validacion']} alertas). En evaluación: {_medida(r, r['elegida'], 'elegida')} (IC bootstrap "
            f"del 95 %, {r['remuestreos']} remuestreos de días). La regla anterior (p = 0,10) en la misma ventana: "
            f"{_medida(r, r['anterior'], 'anterior')}.")


def _adoptada(r: dict) -> str:
    """La frase de la variante vigente en threshold_config cuando no es la elegida en estos datos."""
    p = r.get("adoptada")
    if p is None or p == r.get("elegida"):
        return ""
    return (f"La adoptada en threshold_config (p = {_c(p, 2)}, la elegida con el ciclo de las 6:00), en la misma "
            f"ventana de evaluación: {_medida(r, p, 'adoptada')}.")
