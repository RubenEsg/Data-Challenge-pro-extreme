"""Optimización de la frecuencia (especificación v1.5, §10; RF-007, RF-008 y RF-015).

Tres niveles:
1. recomendar(): la LÍNEA BASE, las fórmulas mínimas de §10.3 para una ruta y una hora, con los límites de headway y la
   flota. Hay dos, cada una con su nombre: la literal (factor_carga=1, demanda puntual: ceil(demanda / capacidad
   efectiva)) y la ajustada (carga crítica = factor de carga × P90, la que se compara con §10.2). Si la recomendación
   no es viable se marca viable=False con el motivo (§10.3, último párrafo).
2. optimizar(): la función objetivo de §10.2, explícita y configurable,
       min α·costo_operativo + β·tiempo_espera + γ·penalización_sobreocupación + δ·desviación_frecuencia
   sujeta a capacidad (nivel de servicio sobre el cuantil calibrado de la demanda), flota disponible, headway mínimo y
   máximo y duración del ciclo, resuelta como un MILP de una franja con PuLP/CBC (la misma técnica de D5: binarias por
   nivel de salidas y cortes tangentes de la sobrecarga esperada lognormal, que es convexa). Los pesos y los costos se
   leen de threshold_config (versionados; PUT /thresholds crea una versión nueva) con valores por omisión en el código.
   Asigna la capacidad por tipología (§10.1) con la flota real de cada ruta (tipologias_flota.json). El headway máximo
   es el efectivo de §5.1, min(headway_maximo_min, 2 × espera_max_min) (supuesto S12), y la ocupación objetivo mínima
   marca la sobreoferta. Una franja inviable sale «no viable» con su explicación; sus cifras son la mejor aproximación
   ejecutable (nunca violan headway, flota ni ciclo), rotulada en «mejor_aproximacion».
   comparar_actual(), que_pasa_si() y sensibilidad() dan los escenarios de RF-008 y el análisis de sensibilidad.
3. plan_dia(): el plan del día por hora (4..20) con el MILP de D5 (app/servicios/motor_d5, sin cambios) y el pronóstico
   horario P10/P50/P90 del modelo ACTIVO, para cualquier fecha con variables: minimiza costo operativo + espera +
   sobrecarga esperada + ingreso perdido, sujeto a la flota disponible, la suavidad, el headway máximo efectivo y el
   headway mínimo gobernado como cotas explícitas de cada hora (§10.2), con los parámetros de threshold_config. Cada
   hora dice qué límites mandan, la demanda de diseño, el margen, si es viable y por qué (§10.3 y §18), y si hay
   sobreoferta. Una hora con una sola salida no tiene intervalo que verificar (sin_intervalo) y no es no viable por
   eso. Los vehículos de cada hora son ceil(ciclo / headway) con headway = 60 / salidas por hora, y el plan dice qué
   mide cada cifra de vehículos (definicion_vehiculos). insumos_plan() expone los insumos por hora del MILP (mu, s,
   capacidad, km y CV) para comparar ofertas con las mismas fórmulas. plan_dia_d5() y resumen_plan_d5() conservan el
   plan del laboratorio con los pronósticos de 2025.
Un festivo entre semana usa, en la programación de comparación, el contexto de la franja y el factor de carga, el
tipo de día «Domingo/festivo», el mismo de D5 (tipo_dia_operacion).
"""
from __future__ import annotations

import itertools
import json
import logging
import math
import threading
import time
from collections import OrderedDict
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from statistics import NormalDist

EPS = 1e-9
log = logging.getLogger("api_frecuencias.optimizacion")

# Fracción de los abordajes de una hora que viajan a la vez en el punto de carga máxima (carga crítica / abordajes).
# Mediana 2025 de L_real / real en datos/insumos_d5_2025.parquet (horas con > 20 abordajes); coincide con la mediana de
# exp(mu) / pronóstico E1 de la lognormal de D5 (0,415 / 0,463 / 0,415). Con factor 1,0 se usa la fórmula literal de
# §10.3 sobre los abordajes, que ignora la renovación de pasajeros a lo largo de la ruta y sobredimensiona la oferta.
RUTA_SILENCIO, RUTA_CRA_54, RUTA_CL_72 = "SILENCIO", "CRA 54", "CL 72"
FACTOR_CARGA_CRITICA = {RUTA_SILENCIO: 0.410, RUTA_CRA_54: 0.453, RUTA_CL_72: 0.408}


def _num(nombre, valor, minimo=None, estricto=False, permitir_none=False):
    """Valida que `valor` sea un número finito (y >= / > `minimo`)."""
    if valor is None:
        if permitir_none:
            return None
        raise ValueError(f"{nombre} es obligatorio.")
    try:
        v = float(valor)
    except (TypeError, ValueError):
        raise ValueError(f"{nombre} debe ser numérico (recibido: {valor!r}).") from None
    if not math.isfinite(v):
        raise ValueError(f"{nombre} debe ser un número finito.")
    if minimo is not None and (v <= minimo if estricto else v < minimo):
        signo = ">" if estricto else ">="
        raise ValueError(f"{nombre} debe ser {signo} {minimo} (recibido: {v}).")
    return v


def _f(x, d=1):
    """Número con coma decimal (es-CO) para las explicaciones."""
    return f"{x:,.{d}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _redondear(x, d):
    """round(x, d), o None si no hay valor."""
    return None if x is None else round(x, d)


def _ocupacion_objetivo(valor):
    occ = _num("ocupacion_objetivo", valor, 0, estricto=True)
    if occ > 1:
        raise ValueError(f"ocupacion_objetivo debe estar en (0, 1] (recibido: {occ}).")
    return occ


def _limites_de_headway(headway_min, headway_max):
    """Headway mínimo y máximo validados (el máximo no puede ser menor que el mínimo; el mínimo, a lo sumo 60 min)."""
    hmin = _num("headway_min", headway_min, 0, estricto=True)
    hmax = _num("headway_max", headway_max, 0, estricto=True)
    if hmax < hmin:
        raise ValueError(f"headway_max ({hmax}) no puede ser menor que headway_min ({hmin}).")
    if hmin > 60:
        raise ValueError(f"headway_min debe ser <= 60 min para planear buses por hora (recibido: {hmin}).")
    return hmin, hmax


def _entradas_10_3(demanda_hora, demanda_p90, capacidad, ocupacion_objetivo, headway_min, headway_max,
                   tiempo_ciclo_min, flota_disponible, frecuencia_actual_min) -> dict:
    """Entradas de recomendar() validadas, siempre en el mismo orden (el primer error es el que se informa)."""
    v = {"demanda": _num("demanda_hora", demanda_hora, 0),
         "p90": _num("demanda_p90", demanda_p90, 0, permitir_none=True),
         "cap": _num("capacidad", capacidad, 0, estricto=True),
         "occ": _ocupacion_objetivo(ocupacion_objetivo)}
    v["hmin"], v["hmax"] = _limites_de_headway(headway_min, headway_max)
    v["ciclo"] = _num("tiempo_ciclo_min", tiempo_ciclo_min, 0, estricto=True, permitir_none=True)
    v["flota"] = _num("flota_disponible", flota_disponible, 0, permitir_none=True)
    v["actual"] = _num("frecuencia_actual_min", frecuencia_actual_min, 0, estricto=True, permitir_none=True)
    return v


def _factor_de_carga(ruta, factor_carga):
    """Factor de carga crítica y su fuente: el de la ruta (insumos D5 2025), 1,0 (fórmula literal) o el parámetro."""
    if factor_carga is None:
        if ruta in FACTOR_CARGA_CRITICA:
            return FACTOR_CARGA_CRITICA[ruta], "ruta (insumos D5 2025)"
        return 1.0, "fórmula literal (1,0)"
    factor = _num("factor_carga", factor_carga, 0, estricto=True)
    if factor > 1:
        raise ValueError(f"factor_carga debe estar en (0, 1] (recibido: {factor}).")
    return factor, "parámetro"


def _cambio_frecuencia(headway, actual):
    """RF-008: diferencia (min) del headway recomendado frente a la frecuencia actual y el sentido del cambio."""
    if actual is None:
        return None, None
    diferencia = round(headway - actual, 2)
    if diferencia < -0.05:
        return diferencia, "reducir_intervalo"
    if diferencia > 0.05:
        return diferencia, "ampliar_intervalo"
    return diferencia, "mantener"


def _oferta_10_3(v: dict, factor: float) -> dict:
    """Buses/h de §10.3 con la demanda de diseño, acotados por el headway mínimo (con su motivo si no alcanza)."""
    cap_ef = v["cap"] * v["occ"]
    usa_p90 = v["p90"] is not None
    base_dem = max(v["demanda"], v["p90"]) if usa_p90 else v["demanda"]
    demanda_diseno = factor * base_dem
    buses_demanda = int(math.ceil(demanda_diseno / cap_ef - EPS)) if demanda_diseno > 0 else 0
    o = {"cap_ef": cap_ef, "usa_p90": usa_p90, "base_dem": base_dem, "demanda_diseno": demanda_diseno,
         "buses_demanda": buses_demanda,
         "buses_servicio": int(math.ceil(60.0 / v["hmax"] - EPS)),         # mínimo para no pasar la espera máxima
         "buses_max_headway": int(math.floor(60.0 / v["hmin"] + EPS)),     # máximo que permite el headway mínimo
         "headway_demanda": 60.0 / buses_demanda if buses_demanda > 0 else None, "motivos": []}
    buses = max(buses_demanda, o["buses_servicio"])
    if buses > o["buses_max_headway"]:
        o["motivos"].append(
            f"La demanda de diseño ({_f(demanda_diseno)} pas/h) exige {buses_demanda} buses/h, un intervalo de "
            f"{_f(o['headway_demanda'], 2)} min, menor que el headway mínimo permitido ({_f(v['hmin'], 2)} min, máximo "
            f"{o['buses_max_headway']} buses/h = {_f(o['buses_max_headway'] * cap_ef)} pas/h de capacidad efectiva).")
        buses = o["buses_max_headway"]
    o["buses"] = buses
    o["headway"] = min(max(60.0 / buses, v["hmin"]), v["hmax"])
    o["vehiculos"] = int(math.ceil(v["ciclo"] / o["headway"] - EPS)) if v["ciclo"] is not None else None
    return o


def _ajuste_por_flota(v: dict, o: dict) -> None:
    """Buses/h que sostiene la flota disponible y los motivos de no viabilidad por flota (§10.3); completa `o`."""
    flota, ciclo, vehiculos = v["flota"], v["ciclo"], o["vehiculos"]
    buses_factible = o["buses"]
    if flota is not None and vehiculos is not None and vehiculos > flota:
        buses_flota = int(math.floor(flota * 60.0 / ciclo + EPS))
        buses_factible = min(o["buses"], buses_flota)
        o["motivos"].append(
            f"La flota disponible ({_f(flota, 0)} vehículos) no alcanza: con un ciclo de {_f(ciclo)} min y un "
            f"headway de {_f(o['headway'], 2)} min se requieren {vehiculos} vehículos; la flota solo sostiene "
            f"{buses_flota} buses/h.")
    headway_factible = (60.0 / buses_factible) if buses_factible > 0 else None
    if flota is not None and (headway_factible is None or headway_factible > v["hmax"] + EPS):
        o["motivos"].append(
            f"Con la flota disponible ni siquiera se cumple el headway máximo ({_f(v['hmax'], 2)} min).")
    o["buses_factible"], o["headway_factible"] = buses_factible, headway_factible


def _formula_10_3(v: dict, o: dict, factor: float) -> str:
    """Cálculo de §10.3 escrito con las cifras de la franja (trazabilidad de la recomendación)."""
    etiqueta = "P90" if o["usa_p90"] else "demanda"
    sin_tope = max(o["buses_demanda"], o["buses_servicio"])
    buses, headway = o["buses"], o["headway"]
    formula = (f"capacidad_efectiva = {_f(v['cap'], 0)} × {_f(v['occ'], 2)} = {_f(o['cap_ef'])}; "
               f"carga_critica = {_f(factor, 3)} × {etiqueta} {_f(o['base_dem'])} = {_f(o['demanda_diseno'])}; "
               f"buses_hora = max(ceil({_f(o['demanda_diseno'])} / {_f(o['cap_ef'])}) = {o['buses_demanda']}, "
               f"ceil(60 / {_f(v['hmax'], 2)}) = {o['buses_servicio']}) = {sin_tope}"
               + (f" → acotado por headway_min a {buses}" if buses != sin_tope else "")
               + f"; headway = 60 / {buses} = {_f(60.0 / buses, 2)} → [{_f(v['hmin'], 2)}, {_f(v['hmax'], 2)}] = "
                 f"{_f(headway, 2)} min")
    if o["vehiculos"] is not None:
        formula += f"; vehiculos_requeridos = ceil({_f(v['ciclo'])} / {_f(headway, 2)}) = {o['vehiculos']}"
    return formula


def recomendar(ruta, hora, demanda_hora, demanda_p90=None, capacidad=50, ocupacion_objetivo=0.85, tiempo_ciclo_min=None,
               flota_disponible=None, headway_min=2.0, headway_max=10.0, frecuencia_actual_min=None, factor_carga=None):
    """Recomendación de frecuencia para una ruta y una hora (§10.3).

    - capacidad_efectiva = capacidad × ocupación objetivo.
    - demanda de diseño = factor_carga × (P90 si se entrega, que absorbe la incertidumbre del pronóstico; si no, la
      demanda puntual). factor_carga pasa de abordajes por hora a carga crítica (pasajeros a bordo en el punto de carga
      máxima); None = el de la ruta en FACTOR_CARGA_CRITICA (1,0 si la ruta no está), 1,0 = fórmula literal.
    - buses_hora = ceil(demanda_diseño / capacidad_efectiva), y al menos ceil(60 / headway_max) para respetar la espera
      máxima de la política de servicio.
    - headway = 60 / buses_hora, acotado a [headway_min, headway_max].
    - vehiculos_requeridos = ceil(tiempo_ciclo / headway).
    No viable (viable=False, con motivo) cuando la demanda exige un intervalo menor que headway_min o cuando la flota
    disponible no alcanza los vehículos requeridos. Las cifras devueltas nunca violan los límites de headway; la brecha
    queda en buses_hora_demanda / headway_demanda_min y en el motivo. RF-008: compara con la frecuencia actual.
    """
    v = _entradas_10_3(demanda_hora, demanda_p90, capacidad, ocupacion_objetivo, headway_min, headway_max,
                       tiempo_ciclo_min, flota_disponible, frecuencia_actual_min)
    factor, fuente_factor = _factor_de_carga(ruta, factor_carga)
    o = _oferta_10_3(v, factor)
    _ajuste_por_flota(v, o)
    demanda, cap, actual, buses = v["demanda"], v["cap"], v["actual"], o["buses"]

    capacidad_ofrecida = buses * cap
    # ocupación en el punto de carga máxima con la demanda puntual (no con el P90)
    ocupacion = factor * demanda / capacidad_ofrecida if capacidad_ofrecida > 0 else None
    buses_actual = 60.0 / actual if actual is not None else None
    diferencia, cambio = _cambio_frecuencia(o["headway"], actual)
    ocupacion_actual = (factor * demanda / (buses_actual * cap)) if buses_actual else None

    return {
        "ruta": ruta,
        "hora": hora,
        "metodo": "formulas_10_3",
        "buses_hora": buses,
        "headway_min": round(o["headway"], 2),
        "vehiculos_requeridos": o["vehiculos"],
        "capacidad_efectiva": round(o["cap_ef"], 2),
        "ocupacion_esperada": _redondear(ocupacion, 4),
        "viable": not o["motivos"],
        "motivo": " ".join(o["motivos"]) or None,
        "frecuencia_actual_min": actual,
        "diferencia_min": diferencia,
        "formula": _formula_10_3(v, o, factor),
        # detalle adicional (trazabilidad y escenarios, RF-008)
        "demanda_hora": demanda,
        "demanda_p90": v["p90"],
        "demanda_diseno": o["demanda_diseno"],
        "criterio_demanda": "p90" if o["usa_p90"] else "puntual",
        "factor_carga": factor,
        "fuente_factor_carga": fuente_factor,
        "buses_hora_demanda": o["buses_demanda"],
        "headway_demanda_min": _redondear(o["headway_demanda"], 2),
        "buses_hora_minimo_servicio": o["buses_servicio"],
        "buses_hora_factible": o["buses_factible"],
        "headway_factible_min": _redondear(o["headway_factible"], 2),
        "capacidad_ofrecida": capacidad_ofrecida,
        "flota_disponible": v["flota"],
        "tiempo_ciclo_min": v["ciclo"],
        "buses_hora_actual": _redondear(buses_actual, 2),
        "ocupacion_actual": _redondear(ocupacion_actual, 4),
        "cambio": cambio,
        "parametros": {"capacidad": cap, "ocupacion_objetivo": v["occ"], "headway_min": v["hmin"],
                       "headway_max": v["hmax"]},
    }


def escenarios(parametros, ocupaciones=(0.65, 0.75, 0.85), factores_demanda=(0.8, 1.0, 1.2)):
    """Análisis de sensibilidad (§10.3) y escenarios (RF-008): recomendar() para cada combinación de ocupación objetivo
    y factor de demanda (aplicado a la demanda puntual y al P90). `parametros` son los argumentos de recomendar()."""
    salida = []
    for occ in ocupaciones:
        for fd in factores_demanda:
            kw = dict(parametros)
            kw["ocupacion_objetivo"] = occ
            kw["demanda_hora"] = float(parametros["demanda_hora"]) * fd
            if parametros.get("demanda_p90") is not None:
                kw["demanda_p90"] = float(parametros["demanda_p90"]) * fd
            r = recomendar(**kw)
            salida.append({"ocupacion_objetivo": occ, "factor_demanda": fd, "buses_hora": r["buses_hora"],
                           "headway_min": r["headway_min"], "vehiculos_requeridos": r["vehiculos_requeridos"],
                           "ocupacion_esperada": r["ocupacion_esperada"], "viable": r["viable"], "motivo": r["motivo"],
                           "diferencia_min": r["diferencia_min"]})
    return salida


def _fecha_de(fecha) -> date:
    """date de una fecha dada como date, datetime o texto ISO."""
    if isinstance(fecha, datetime):
        return fecha.date()
    if isinstance(fecha, date):
        return fecha
    return date.fromisoformat(str(fecha)[:10])


def _tope_por_headway(tb, headway_min: float):
    """Salidas máximas de cada hora con el headway mínimo gobernado: floor(minutos operados / headway mínimo), y al
    menos las salidas mínimas de la política de servicio (nmin)."""
    import numpy as np

    minutos = tb["minutos"].to_numpy(float)
    tope = np.where(minutos > 0, np.floor(minutos / float(headway_min) + 1e-9), 0).astype(int)
    return np.maximum(tope, tb["nmin"].to_numpy(int))


@lru_cache(maxsize=256)
def _resolver_d5_acotado(fecha_iso: str, ruta: str, modelo: str, fuente_costos: bool, headway_min: float) -> dict:
    """El MILP de D5 con el headway mínimo gobernado como restricción explícita (§10.2): mismos insumos, costos,
    flota y suavidad que plan_base.plan_ruta; solo baja la cota nmax de las horas donde D5 admitía más salidas que
    floor(minutos / headway mínimo) (las que la operación ya tuvo, hasta 35 por hora)."""
    import numpy as np

    from .motor_d5 import comun as C
    from .motor_d5 import milp, plan_base

    params = C.param_d5(fuente=fuente_costos)
    sub = plan_base.insumos(fecha_iso, ruta, modelo)
    sub["nmax"] = np.minimum(sub["nmax"].to_numpy(int), _tope_por_headway(sub, headway_min))
    flota = float(sub["flota_disp"].iloc[0])
    x, estado, holgura, comp = milp.resolver_dia_detalle(plan_base.entradas_d5(sub), sub["ciclo"].values, flota,
                                                         params, solver="cbc")
    sub["x_plan"] = x
    sub["programar"] = np.ceil(sub["x_plan"] / (1 - sub["tasa_no_valido"].fillna(0)))
    return {"tabla": sub, "horario": plan_base.horario(x, sub["minutos"].values), "flota": flota, "estado": estado,
            "holgura": holgura, "componentes": comp, "tipo_dia": str(sub["tipo_dia"].iloc[0])}


def _plan_d5(ruta: str, fecha: date, modelo: str, fuente_costos: bool, headway_min: float | None) -> dict:
    """Plan D5 del día que respeta el headway mínimo gobernado (por omisión, INTERVALO_MIN de D5: 2 min).

    Si ninguna hora del plan de D5 pasa el tope, es el mismo plan de plan_base.plan_ruta; si no, se resuelve de nuevo
    con el tope como cota. La tabla trae además x_sin_tope (las salidas del plan de D5 sin el tope) y tope_headway."""
    from .motor_d5 import comun as C
    from .motor_d5 import plan_base

    params = C.param_d5(fuente=fuente_costos)
    libre = plan_base.plan_ruta(fecha, ruta, params, modelo=modelo)
    minimo = float(params["INTERVALO_MIN"] if headway_min is None else headway_min)
    tb = libre["tabla"]
    tope = _tope_por_headway(tb, minimo)
    r = dict(libre)
    if (tb["x_plan"].to_numpy(int) > tope).any():
        r.update(_resolver_d5_acotado(fecha.isoformat(), ruta, modelo, bool(fuente_costos), minimo))
        r["tabla"] = r["tabla"].copy()
    r["tabla"]["x_sin_tope"] = tb["x_plan"].to_numpy(int)
    r["tabla"]["tope_headway"] = tope
    r["headway_minimo_min"] = minimo
    return r


def _horas_plan(r: dict, modelo: str) -> list[dict]:
    """Las 17 horas (4..20) del plan con sus despachos minuto a minuto y si el headway mínimo las limita."""
    por_hora = {}
    for m in r["horario"]:              # salidas equiespaciadas de D5, en minutos desde medianoche
        por_hora.setdefault(int(m) // 60, []).append(f"{int(m) // 60:02d}:{int(m) % 60:02d}")
    salida = []
    for fila in r["tabla"].itertuples(index=False):
        x = int(fila.x_plan)
        minutos = float(fila.minutos)
        salida.append({
            "hora": int(fila.hora),
            "salidas": x,
            "despachos": por_hora.get(int(fila.hora), []),
            "headway_min": round(minutos / x, 2) if x > 0 and minutos > 0 else None,
            "programar": int(fila.programar),
            "pasajeros_previstos": round(float(fila.pax_pred), 2),
            "minutos_operados": minutos,
            "estado_solver": r["estado"],
            "tipo_dia": r["tipo_dia"],
            "modelo": modelo,
            "headway_minimo_min": r["headway_minimo_min"],
            "maximo_salidas_headway": int(fila.tope_headway),
            "salidas_sin_tope": int(fila.x_sin_tope),
            "limitada_por_headway_minimo": int(fila.x_sin_tope) > int(fila.tope_headway),
        })
    return salida


def _validar_plan(ruta, modelo) -> None:
    from .motor_d5 import comun as C
    from .motor_d5 import plan_base

    if ruta not in C.ORDEN:
        raise ValueError(f"Ruta desconocida: {ruta!r}. Rutas válidas: {', '.join(C.ORDEN)}.")
    if modelo not in plan_base.MODELOS:
        raise ValueError(f"Modelo desconocido: {modelo!r}. Válidos: {', '.join(plan_base.MODELOS)}.")


def plan_dia_d5(ruta, fecha, modelo="E12", fuente_costos=True, headway_min=None):
    """Plan de un día con el MILP de D5 (copia en motor_d5) para `ruta` y `fecha` (2025).

    Devuelve una lista de 17 dicts (horas 4..20): hora, salidas (x_plan del MILP), headway_min (minutos operados de
    la hora / salidas; None si la hora no se opera o no tiene salidas), programar (salidas a programar descontando la
    tasa de viajes no válidos), pasajeros_previstos (pronóstico de `modelo`), minutos_operados, estado del solver y
    tipo de día.
    `headway_min`: headway mínimo gobernado (threshold_config headway_minimo_min); None = INTERVALO_MIN de D5 (2 min).
    Es una restricción explícita: ninguna hora pasa de floor(minutos / headway_min) salidas. Cada hora dice además
    cuántas salidas daría D5 sin ese tope (salidas_sin_tope) y si el tope la limita (limitada_por_headway_minimo: la
    demanda pide más salidas de las que permite el headway mínimo).
    Lanza ValueError si la ruta o la fecha no tienen insumos de D5.
    """
    _validar_plan(ruta, modelo)
    return _horas_plan(_plan_d5(ruta, _fecha_de(fecha), modelo, fuente_costos, headway_min), modelo)


DEFINICION_VEHICULOS_10_3 = (
    "vehiculos_hora_pico = máximo por hora de los vehículos requeridos de §10.3, ceil(tiempo_ciclo / headway) con el "
    "headway de la hora = 60 / salidas por hora: la flota que sostendría ese ritmo un ciclo completo. En las horas de "
    "apertura o cierre, operadas solo en parte, el intervalo entre salidas es más corto pero no dura un ciclo, así que "
    "no pide más vehículos que el ritmo de la hora.")
DEFINICION_VEHICULOS = (
    f"{DEFINICION_VEHICULOS_10_3} buses_en_ruta_pico es otra medida: el máximo de buses en ruta a la vez con el plan "
    "(conteo de D5 cada 15 min). Es la que limita la flota del MILP y la que usa la respuesta del reto.")


def vehiculos_requeridos_hora(ciclo_min: float, salidas: int) -> int:
    """§10.3: vehículos requeridos = ceil(tiempo_ciclo / headway), con headway = 60 / salidas por hora. En una hora
    operada en parte (apertura o cierre) las salidas van más juntas, pero ese intervalo no se sostiene un ciclo
    completo: la hora pide los vehículos de su ritmo horario, no los de su intervalo, que darían cientos de vehículos
    para una sola salida a las 4:59 (ver DEFINICION_VEHICULOS)."""
    if not salidas or salidas <= 0:
        return 0
    return int(math.ceil(float(ciclo_min) * int(salidas) / 60.0 - EPS))


def _completar_hora_d5(h: dict, tb, programado: dict) -> float:
    """Agrega a una hora del plan D5 el ciclo, los vehículos requeridos y la comparación con el intervalo programado;
    devuelve las salidas programadas de esa hora (0 si no hay intervalo programado)."""
    ciclo = float(tb.loc[h["hora"], "ciclo"])
    h["tiempo_ciclo_min"] = round(ciclo, 2)
    h["vehiculos_requeridos"] = vehiculos_requeridos_hora(ciclo, h["salidas"]) if h["headway_min"] else 0
    frec = programado.get(h["hora"])
    h["frecuencia_actual_min"] = round(frec, 2) if frec else None
    h["salidas_programadas"] = round(h["minutos_operados"] / frec, 2) if frec and h["minutos_operados"] else None
    h["diferencia_salidas"] = (round(h["salidas"] - h["salidas_programadas"], 2)
                               if h["salidas_programadas"] is not None else None)
    return h["salidas_programadas"] or 0.0


def resumen_plan_d5(ruta, fecha, modelo="E12", fuente_costos=True, headway_min=None):
    """Plan D5 de un día (plan_dia_d5) con su resumen: salidas del día, vehículos en la hora pico
    (ceil(ciclo / headway)), componentes del costo del MILP, estado del solver y comparación con el intervalo
    programado de cada hora (RF-008). `headway_min` como en plan_dia_d5."""
    from .motor_d5 import comun as C

    _validar_plan(ruta, modelo)
    f = _fecha_de(fecha)
    r = _plan_d5(ruta, f, modelo, fuente_costos, headway_min)
    horas = _horas_plan(r, modelo)
    tb = r["tabla"].set_index("hora")
    programado = _intervalos_programados(ruta, f)
    total_prog = sum((_completar_hora_d5(h, tb, programado) for h in horas), 0.0)
    comp = {k: round(v, 2) for k, v in (r.get("componentes") or {}).items()}
    limitadas = [h["hora"] for h in horas if h["limitada_por_headway_minimo"]]
    return {
        "ruta": ruta, "fecha": f.isoformat(), "modelo": modelo, "tipo_dia": r["tipo_dia"], "estado_solver": r["estado"],
        "flota_disponible": float(r["flota"]), "holgura_flota": round(float(r.get("holgura") or 0.0), 4),
        "salidas_dia": int(sum(h["salidas"] for h in horas)),
        "salidas_programadas_dia": round(total_prog, 1) if total_prog else None,
        "vehiculos_hora_pico": max((h["vehiculos_requeridos"] for h in horas), default=0),
        "definicion_vehiculos": DEFINICION_VEHICULOS_10_3,
        "componentes_costo_cop": comp, "costo_total_cop": round(sum(comp.values()), 2) if comp else None,
        "fuente_costos": C.param_d5(fuente=fuente_costos)["FUENTE"],
        "headway_minimo_min": r["headway_minimo_min"], "horas_limitadas_por_headway_minimo": limitadas,
        "formulacion": ("MILP D5 (PuLP/CBC): para cada hora h (4-20) una binaria por nivel de salidas; min Σ "
                        "costo operativo + espera + sobrecarga esperada (lognormal) + ingreso perdido, sujeto a "
                        "flota en ruta cada 15 min, suavidad |x_h - x_{h-1}| <= DELTA, intervalo máximo del tipo de "
                        f"día e intervalo mínimo gobernado de {_f(r['headway_minimo_min'], 2)} min (x_h <= "
                        "floor(minutos_h / headway_min))."),
        "horas": horas,
    }


# ======================================================================================================================
# Plan del día con el pronóstico horario del modelo ACTIVO (§10.1-§10.3, RF-007, RF-008): el mismo MILP de D5
# (motor_d5.milp, sin cambios) alimentado con P10/P50/P90 por hora del modelo activo, los parámetros operativos de la
# ruta, el tipo de día y la hora (mediana 2025, D1) y los parámetros gobernados de threshold_config. Sirve para
# cualquier fecha con variables; el pronóstico E12 precalculado de 2025 queda solo como opción (pronostico="E12").
# ======================================================================================================================
FUENTE_MODELO_ACTIVO = "modelo_activo"
FUENTE_E12 = "E12"
PRONOSTICOS_PLAN = {"activo": FUENTE_MODELO_ACTIVO, "E12": FUENTE_E12}
REGLA_ESPERA = ("headway máximo efectivo = min(headway_maximo_min, 2 × espera_max_min): la espera máxima de §5.1 se "
                "lee como espera media del pasajero, headway / 2 con llegadas aleatorias (supuesto S12)")
TEXTO_ELASTICIDAD = ("β estimada ≈ 0,70 por observación, sin validar en campo; el plan usa 0,5 por prudencia; la "
                     "sensibilidad está en docs/evidencias/optimizacion/sensibilidad.md; el piloto la mide")
FUENTE_D5 = "código de D5 (motor_d5.comun.param_d5)"
FUENTE_POR_OMISION = "código (valor por omisión)"     # parámetro que no traen threshold_config ni la solicitud
FUENTE_OPERATIVA = ("datos/parametros_operativos_hora.parquet y datos/insumos_d5_2025.parquet (mediana 2025 por ruta, "
                    "tipo de día y hora)")
_PLANES: OrderedDict = OrderedDict()
_PRONOSTICOS: OrderedDict = OrderedDict()
_PLANES_MAX = 256
_PRONOSTICO_VIGENCIA_S = 120.0       # el ciclo y la foto de la respuesta del mismo cierre comparten el pronóstico
_PLANES_CANDADO = threading.Lock()


def _umbral(nombre: str, umbrales: dict | None, version: int | None, defecto: float) -> dict:
    """Valor de un umbral con su fuente: threshold_config (con la versión) o el valor por omisión del código."""
    if umbrales and umbrales.get(nombre) is not None:
        return {"valor": float(umbrales[nombre]),
                "fuente": f"threshold_config v{version}" if version is not None else "threshold_config"}
    return {"valor": float(defecto), "fuente": FUENTE_POR_OMISION}


def headway_maximo_efectivo(umbrales: dict | None, version: int | None = None) -> dict:
    """§5.1 «espera máxima» con efecto (supuesto S12): headway máximo efectivo = min(headway_maximo_min,
    2 × espera_max_min). Rige en la recomendación de franja y en el plan del día. Nunca queda por debajo del headway
    mínimo: si la espera pedida lo exige, manda el mínimo y la nota lo dice."""
    hmax = _umbral("headway_maximo_min", umbrales, version, 10.0)
    espera = _umbral("espera_max_min", umbrales, version, 5.0)
    hmin = _umbral("headway_minimo_min", umbrales, version, 2.0)
    _num("espera_max_min", espera["valor"], 0, estricto=True)
    dos = 2.0 * espera["valor"]
    valor = min(hmax["valor"], dos)
    manda = "espera_max_min" if dos < hmax["valor"] - EPS else "headway_maximo_min"
    nota = None
    if valor < hmin["valor"] - EPS:
        nota = (f"La espera máxima de {_f(espera['valor'], 2)} min pide un headway de {_f(dos, 2)} min, menor que el "
                f"headway mínimo de {_f(hmin['valor'], 2)} min: manda el headway mínimo.")
        valor, manda = hmin["valor"], "headway_minimo_min"
    return {"valor": round(valor, 4), "manda": manda, "regla": REGLA_ESPERA, "headway_maximo_min": hmax,
            "espera_max_min": espera, "dos_por_espera_min": round(dos, 4), "nota": nota}


def parametros_plan(umbrales: dict | None, umbrales_version: int | None, fuente_costos: bool = True) -> dict:
    """Parámetros del MILP del plan del día con la fuente de cada uno (§5.1 «regla de gobierno»).

    De threshold_config (o del código si la tabla no los trae): headway mínimo y máximo efectivo (nmin y nmax de cada
    hora), ocupación objetivo, nivel de servicio, costos de §10.2 (bus-hora, km, valor del tiempo de espera, penalidad
    por sobreocupación) y los pesos α, β, γ, que escalan el costo operativo, la espera y la sobrecarga del MILP. De D5:
    tarifa, elasticidad, suavidad (DELTA) y hora de inicio de la suavidad. El peso δ no aplica al plan: su papel lo
    cumplen la suavidad entre horas y el ingreso perdido frente a la oferta programada."""
    from .motor_d5 import comun as C

    u = umbrales or {}
    objetivo = parametros_objetivo(u, umbrales_version)
    d5 = C.param_d5(fuente=fuente_costos)
    hmax = headway_maximo_efectivo(u, umbrales_version)
    hmin = _umbral("headway_minimo_min", u, umbrales_version, 2.0)
    if not fuente_costos:
        objetivo = dict(objetivo, costo_bus_hora_cop={"valor": float(d5["COSTO_BUS_HORA"]), "fuente": d5["FUENTE"]},
                        costo_km_cop={"valor": float(d5["COSTO_KM"]), "fuente": d5["FUENTE"]})
    return {
        "headway_minimo_min": hmin,
        "headway_maximo_efectivo_min": {"valor": hmax["valor"], "fuente": REGLA_ESPERA, "detalle": hmax},
        "ocupacion_objetivo_min": _umbral("ocupacion_objetivo_min", u, umbrales_version, 0.65),
        "ocupacion_objetivo_max": _umbral("ocupacion_objetivo_max", u, umbrales_version, 0.85),
        **{n: objetivo[n] for n in ("nivel_servicio", "costo_bus_hora_cop", "costo_km_cop",
                                    "valor_tiempo_espera_cop_h", "penalidad_sobreocupacion_cop",
                                    "peso_costo_operativo", "peso_tiempo_espera", "peso_sobreocupacion")},
        "tarifa_cop": {"valor": float(d5["TARIFA"]), "fuente": f"{FUENTE_D5}: {d5['FUENTE']}"},
        "elasticidad": {"valor": float(d5["ELASTICIDAD"]), "fuente": f"{FUENTE_D5}; {TEXTO_ELASTICIDAD}"},
        "delta_suavidad": {"valor": float(d5["DELTA"]), "fuente": FUENTE_D5},
        "hora_inicio_suavidad": {"valor": float(d5["HORA_INICIO_SUAVIDAD"]), "fuente": FUENTE_D5},
    }


def _p_milp(gob: dict, fuente_costos: bool, ponderar: bool = True) -> dict:
    """Parámetros de motor_d5.milp con los valores gobernados (con ponderar, los pesos α, β, γ ya aplicados)."""
    from .motor_d5 import comun as C

    p = C.param_d5(fuente=fuente_costos)
    v = {n: float(e["valor"]) for n, e in gob.items()}
    a, b, g = ((v["peso_costo_operativo"], v["peso_tiempo_espera"], v["peso_sobreocupacion"]) if ponderar
               else (1.0, 1.0, 1.0))
    bus_hora, km = ((v["costo_bus_hora_cop"], v["costo_km_cop"]) if fuente_costos
                    else (float(p["COSTO_BUS_HORA"]), float(p["COSTO_KM"])))
    p.update({"COSTO_BUS_HORA": bus_hora * a, "COSTO_KM": km * a,
              "VALOR_TIEMPO_ESPERA": v["valor_tiempo_espera_cop_h"] * b,
              "PENALIDAD_SOBRECARGA": v["penalidad_sobreocupacion_cop"] * g,
              "INTERVALO_MIN": v["headway_minimo_min"]})
    return p


@lru_cache(maxsize=4)
def _medianas_d5(carpeta: str, huella: float) -> dict:
    """Mediana 2025 de los insumos de D5 por (ruta, tipo de día, hora): minutos operados, CV de los intervalos, km del
    ciclo y tasa de viajes no válidos. Sirven para cualquier fecha (el plan no usa lo observado del propio día)."""
    import pandas as pd

    if huella < 0:
        return {}
    d = pd.read_parquet(Path(carpeta) / ARCHIVO_INSUMOS_D5,
                        columns=["ruta", "tipo_dia", "hora", "minutos", "cv_d4", "dist", "tasa_no_valido"])
    d["t"] = d["tipo_dia"].astype(str).str[:1]
    g = d.groupby(["ruta", "t", "hora"])[["minutos", "cv_d4", "dist", "tasa_no_valido"]].median()
    return {(str(r), str(t), int(h)): {k: float(x) for k, x in fila.items()} for (r, t, h), fila in g.iterrows()}


def _pronostico_activo(fecha: date, ruta: str, model_id: str | None) -> tuple[list[dict], str, str | None]:
    """P10/P50/P90 de cada hora de servicio (4-20 h) con el modelo activo: inferencia con h = 60 al inicio de cada hora
    y sin factor intradía (el plan se calcula antes del día). En lote si inferencia.predecir_horas existe."""
    from zoneinfo import ZoneInfo

    from app.servicios import datos, inferencia

    zona = ZoneInfo("America/Bogota")
    inicios = [datetime(fecha.year, fecha.month, fecha.day, h, tzinfo=zona) for h in datos.HORAS_SERVICIO]
    if hasattr(inferencia, "predecir_horas"):
        salidas = inferencia.predecir_horas(ruta, inicios, model_id, horizonte_min=60, usar_nowcast=False)
    else:
        salidas = [inferencia.predecir(ruta, i, 60, model_id=model_id, usar_nowcast=False) for i in inicios]
    horas = [{"hora": i.hour, "p10": float(r["p10"]), "p50": float(r["pasajeros"]), "p90": float(r["p90"])}
             for i, r in zip(inicios, salidas, strict=True)]
    modelo = str(salidas[0].get("model_id") or model_id) if salidas else str(model_id)
    return horas, modelo, (salidas[0].get("calibracion_version") if salidas else None)


def _pronostico_memorizado(fecha: date, ruta: str, model_id: str | None) -> tuple[list[dict], str, str | None]:
    """_pronostico_activo con memoria de 2 min por (fecha, ruta, modelo, preferencia de calibración)."""
    from app.servicios import inferencia

    modelo = model_id or inferencia.modelo_activo()
    try:
        preferencia = inferencia.preferencia_calibracion()
    except Exception:  # noqa: BLE001 - la preferencia solo afina la clave
        preferencia = None
    clave = (fecha.isoformat(), ruta, modelo, preferencia)
    with _PLANES_CANDADO:
        guardado = _PRONOSTICOS.get(clave)
    if guardado is not None and time.monotonic() - guardado[0] < _PRONOSTICO_VIGENCIA_S:
        return guardado[1]
    valor = _pronostico_activo(fecha, ruta, modelo)
    with _PLANES_CANDADO:
        _PRONOSTICOS[clave] = (time.monotonic(), valor)
        while len(_PRONOSTICOS) > _PLANES_MAX:
            _PRONOSTICOS.popitem(last=False)
    return valor


def _normalizar_pronostico(pronostico_horario: list[dict]) -> dict[int, dict]:
    """{hora: {p10, p50, p90}} de una lista {hora, p10, p50, p90} (p50 o pasajeros); valida que sean números >= 0."""
    salida = {}
    for h in pronostico_horario or []:
        hora = int(h["hora"])
        p50 = _num("p50", h.get("p50", h.get("pasajeros")), 0)
        p10 = _num("p10", h.get("p10"), 0, permitir_none=True)
        p90 = _num("p90", h.get("p90"), 0, permitir_none=True)
        salida[hora] = {"p10": p10, "p50": p50, "p90": p90}
    return salida


def _dispersion(p10, p50, p90) -> float:
    """s de la lognormal de la carga crítica con la banda calibrada: ln(P90 / P50) / z_0,90 (o con el P10), en [0,02;
    1,5] (0,02 es la dispersión mínima del oráculo de D5)."""
    base = max(float(p50), 1.0)
    if p90 is not None and p90 > base:
        s = math.log(p90 / base) / Z90
    elif p10 is not None and 0 < p10 < base:
        s = math.log(base / p10) / Z90
    else:
        s = 0.02
    return min(max(s, 0.02), 1.5)


def _cotas_hora(minutos: float, hmin: float, hmax: float) -> tuple[int, int]:
    """(nmin, tope): salidas mínimas para no pasar el headway máximo y máximas con el headway mínimo.

    Una sola salida no deja intervalo entre salidas dentro de la hora, así que el headway mínimo no la restringe: en
    una hora operada menos minutos que el headway mínimo (apertura o cierre, p. ej. 0,2 min a las 4 h de un domingo)
    el tope es 1 y la hora no queda no viable por eso. Es la misma regla de respuesta._problemas_intervalo."""
    if minutos <= 0:
        return 0, 0
    return int(math.ceil(minutos / hmax - 1e-9)), max(int(math.floor(minutos / hmin + 1e-9)), 1)


def insumos_plan(fecha, ruta: str, pronostico_horario, parametros: dict | None = None, *,
                 pronostico: str = "activo"):
    """Insumos por hora (4-20 h) con los que plan_dia resuelve el MILP de D5. Es la API pública para quien compare
    ofertas con las mismas fórmulas del plan (la respuesta del reto).

    - `fecha`: date, datetime o texto ISO; `ruta`: nombre de D5 (SILENCIO, CRA 54, CL 72).
    - `pronostico_horario`: {hora: {p10, p50, p90}} o lista [{hora, p10, p50, p90}] (p50 o pasajeros); None = el
      pronóstico del modelo activo, el mismo que usa plan_dia. Con pronostico="E12" se ignora y se usan los insumos
      de D5 del día con el pronóstico E12 de 2025.
    - `parametros` (opcional, la salida de parametros_plan): si llega, agrega las cotas gobernadas de cada hora (nmin,
      tope_headway, sin_nivel_entero, nmax).

    Devuelve un DataFrame, una fila por hora: hora, minutos, ciclo, dist (km del ciclo), cv_d4 (CV de los
    intervalos), pax_pred, p10, p50, p90, factor_carga, mu y s (lognormal de la carga crítica), k0_plan, capacidad,
    flota_disp, tasa_no_valido, nmax_operacion y tipo_dia. Lanza ValueError si faltan parámetros o pronóstico."""
    f = _fecha_de(fecha)
    if pronostico == "E12":
        tb = _insumos_e12(f, ruta)
    else:
        if pronostico_horario is None:
            pronostico_horario = _pronostico_memorizado(f, ruta, None)[0]
        pron = (pronostico_horario if isinstance(pronostico_horario, dict)
                else _normalizar_pronostico(pronostico_horario))
        tb = _insumos_modelo_activo(f, ruta, pron)
    return _con_cotas(tb.reset_index(drop=True), parametros) if parametros else tb


def _insumos_modelo_activo(fecha: date, ruta: str, pron: dict[int, dict]):
    """Insumos del MILP (17 horas) con el pronóstico del modelo activo y los parámetros operativos medianos."""
    import pandas as pd

    from app.servicios import datos

    from .motor_d5 import comun as C

    tipo = tipo_dia_operacion(fecha)
    letra = "LSD"[tipo]
    p = datos.parametros_operativos(ruta)
    p = p[p["tipo_dia"].astype(str).str[:1] == letra].set_index("hora")
    insumos = C.DATOS / ARCHIVO_INSUMOS_D5
    med = _medianas_d5(str(C.DATOS), insumos.stat().st_mtime if insumos.exists() else -1.0)
    filas = []
    for h in C.HORAS:
        h = int(h)
        if h not in p.index or h not in pron:
            raise ValueError(f"Faltan parámetros operativos o pronóstico para {ruta} a las {h}:00 del {fecha}.")
        op, m = p.loc[h], med.get((ruta, letra, h), {})
        minutos = float(m.get("minutos", 60.0))
        f = pron[h]
        carga = factor_carga_franja(ruta, fecha, h)
        factor = carga["factor_carga"] if carga else FACTOR_CARGA_CRITICA.get(ruta, 1.0)
        prog = op["intervalo_programado_min"]
        intervalo = float(prog) if prog is not None and not pd.isna(prog) and float(prog) > 0 else None
        filas.append({"hora": h, "minutos": minutos, "ciclo": float(op["tiempo_ciclo_min"]),
                      "dist": float(m.get("dist", KM_CICLO.get(ruta, KM_CICLO_POR_OMISION))),
                      "cv_d4": float(m.get("cv_d4", CV_INTERVALOS.get(ruta, CV_POR_OMISION))),
                      "pax_pred": f["p50"], "p10": f["p10"], "p50": f["p50"], "p90": f["p90"], "factor_carga": factor,
                      "mu": math.log(max(factor * f["p50"], 1.0)), "s": _dispersion(f["p10"], f["p50"], f["p90"]),
                      "k0_plan": (minutos / intervalo) if intervalo else 1.0, "capacidad": float(op["capacidad"]),
                      "flota_disp": float(p["flota"].max()), "tasa_no_valido": float(m.get("tasa_no_valido", 0.0)),
                      "nmax_operacion": int(op["nmax"]), "tipo_dia": TIPOS_DIA[tipo]})
    return pd.DataFrame(filas)


_insumos_activo = insumos_plan      # nombre anterior, solo por compatibilidad: usar insumos_plan


def _insumos_e12(fecha: date, ruta: str):
    """Insumos del MILP con el pronóstico E12 precalculado de 2025 (opción de laboratorio): los de D5 del día."""
    import numpy as np

    from .motor_d5 import plan_base

    sub = plan_base.insumos(fecha.isoformat(), ruta, "E12").copy()
    sub["p50"], sub["p10"], sub["p90"] = sub["pax_pred"], None, None
    sub["factor_carga"] = np.exp(sub["mu"]) / np.clip(sub["pax_pred"], 1, None)
    sub["nmax_operacion"] = sub["nmax"].astype(int)
    return sub


def _con_cotas(tb, gob: dict):
    """nmin (headway máximo efectivo), tope (headway mínimo) y la cota libre (lo que la operación ya tuvo) por hora."""
    import numpy as np

    hmin, hmax = float(gob["headway_minimo_min"]["valor"]), float(gob["headway_maximo_efectivo_min"]["valor"])
    cotas = [_cotas_hora(float(m), hmin, hmax) for m in tb["minutos"]]
    tb["nmin"] = [c[0] for c in cotas]
    tb["tope_headway"] = [max(c[1], c[0]) for c in cotas]
    tb["sin_nivel_entero"] = [c[0] > c[1] for c in cotas]
    libre = np.maximum(tb["nmax_operacion"].to_numpy(int), tb["tope_headway"].to_numpy(int))
    tb["nmax"] = np.where(tb["minutos"].to_numpy(float) > 0, libre, 0)
    return tb


def _resolver_plan(tb, p_milp: dict) -> dict:
    """MILP de D5 sin el tope y, si alguna hora lo pasa, otra vez con nmax = tope (headway mínimo gobernado)."""
    import numpy as np

    from .motor_d5 import milp, plan_base

    flota = float(tb["flota_disp"].iloc[0])
    x, estado, holgura, _ = milp.resolver_dia_detalle(plan_base.entradas_d5(tb), tb["ciclo"].values, flota, p_milp,
                                                      solver="cbc")
    tb["x_sin_tope"] = np.asarray(x, int)
    if (tb["x_sin_tope"] > tb["tope_headway"]).any():
        acotada = tb.copy()
        acotada["nmax"] = acotada["tope_headway"]
        x, estado, holgura, _ = milp.resolver_dia_detalle(plan_base.entradas_d5(acotada), tb["ciclo"].values, flota,
                                                          p_milp, solver="cbc")
    tb["x_plan"] = np.asarray(x, int)
    tb["programar"] = np.ceil(tb["x_plan"] / (1 - tb["tasa_no_valido"].fillna(0))).astype(int)
    return {"tabla": tb, "estado": estado, "holgura": float(holgura or 0.0), "flota": flota,
            "horario": plan_base.horario(tb["x_plan"].to_numpy(int), tb["minutos"].values)}


def _componentes_por_hora(tb, p_milp: dict) -> list[dict]:
    """Componentes (COP) de cada hora del plan resuelto, sin redondear: operación, espera, sobrecarga e ingreso."""
    from .motor_d5 import milp, plan_base

    salida = []
    for e, x in zip(plan_base.entradas_d5(tb), tb["x_plan"], strict=True):
        k, op, wait, over, rev = milp.costos_por_nivel(e, p_milp)
        i = list(k).index(int(x))
        salida.append({nombre: float(serie[i]) for nombre, serie in
                       (("op", op), ("espera", wait), ("sobrecarga", over), ("ingreso", rev))})
    return salida


def _componentes(tb, p_milp: dict, por_hora: list[dict] | None = None) -> dict:
    """Componentes (COP) del plan resuelto con los costos sin ponderar: operación, espera, sobrecarga e ingreso."""
    comp = {"op": 0.0, "espera": 0.0, "sobrecarga": 0.0, "ingreso": 0.0}
    for fila in por_hora if por_hora is not None else _componentes_por_hora(tb, p_milp):
        for nombre, valor in fila.items():
            comp[nombre] += valor
    return {k: round(v, 2) for k, v in comp.items()}


def _flota_por_hora(tb, flota: float) -> tuple[dict, dict]:
    """Buses en ruta máximos en los instantes de cada hora (cada 15 min) y si la flota no alcanza o manda."""
    import numpy as np

    from .motor_d5 import milp

    fr = milp.fracciones_en_ruta(tb["ciclo"].values)
    en_ruta = tb["x_plan"].to_numpy(float) @ fr
    maximo, estado = {}, {}
    for h in milp.HORAS:
        cols = np.nonzero((milp.T_FLOTA > h) & (milp.T_FLOTA <= h + 1))[0]    # instantes de la hora (cada 15 min)
        pico = float(en_ruta[cols].max()) if len(cols) else 0.0
        maximo[int(h)] = round(pico, 2)
        estado[int(h)] = "insuficiente" if pico > flota + 1e-6 else ("activa" if pico > flota - 0.5 else "holgada")
    return maximo, estado


def _margen_hora(e: dict, x: int, p_milp: dict) -> dict:
    """Por qué x salidas y no x ± 1 en la hora (costo de D5 de cada nivel, sin la suavidad ni la flota)."""
    from .motor_d5 import milp

    k, op, wait, over, rev = milp.costos_por_nivel(e, p_milp)
    tot = [float(a + b + c + d) for a, b, c, d in zip(op, wait, over, rev, strict=True)]
    niveles = [int(v) for v in k]
    base = tot[niveles.index(x)] if x in niveles else None
    salida = {}
    for nombre, paso in (("una_salida_menos", -1), ("una_salida_mas", 1)):
        y = x + paso
        if base is None or y not in niveles:
            salida[nombre] = {"factible": False, "salidas": y}
        else:
            salida[nombre] = {"factible": True, "salidas": y, "delta_costo_cop": round(tot[niveles.index(y)] - base, 2)}
    salida["nota"] = "Costo de D5 de la hora (operación + espera + sobrecarga + ingreso perdido), sin suavidad ni flota"
    return salida


def _limites_hora(i: int, tb, flota_estado: dict, delta: float, hora_suavidad: float) -> list[str]:
    """Restricciones que mandan en la hora i del plan."""
    fila = tb.iloc[i]
    x, h = int(fila["x_plan"]), int(fila["hora"])
    if fila["minutos"] <= 0:
        return []                                       # hora sin operación programada
    activos = []
    if x >= int(fila["tope_headway"]):
        activos.append("headway_minimo")
    if x <= int(fila["nmin"]):
        activos.append("headway_maximo")
    if flota_estado.get(h) in ("activa", "insuficiente"):
        activos.append("flota_disponible")
    for j in (i - 1, i + 1):
        if 0 <= j < len(tb) and max(h, int(tb.iloc[j]["hora"])) >= hora_suavidad:
            a, b = tb.iloc[min(i, j)], tb.iloc[max(i, j)]
            if a["minutos"] > 0 and b["minutos"] > 0 and abs(
                    b["x_plan"] / (b["minutos"] / 60) - a["x_plan"] / (a["minutos"] / 60)) >= delta - 1e-6:
                activos.append("suavidad")
                break
    return activos


def _viabilidad_hora(fila, flota_estado: str, hmin: float, hmax: float, flota: float) -> list[str]:
    """Motivos por los que la hora del plan no es viable (§10.3, §18); vacío si lo es."""
    motivos = []
    x, minutos = int(fila["x_plan"]), float(fila["minutos"])
    if bool(fila["sin_nivel_entero"]):
        motivos.append(f"Con {_f(minutos, 1)} minutos operados no hay un número entero de salidas con headway entre "
                       f"{_f(hmin, 2)} y {_f(hmax, 2)} min.")
    if int(fila["x_sin_tope"]) > int(fila["tope_headway"]):
        motivos.append(
            f"La demanda prevista pide {int(fila['x_sin_tope'])} salidas (una cada "
            f"{_f(minutos / max(int(fila['x_sin_tope']), 1), 2)} min) y el headway mínimo gobernado de {_f(hmin, 2)} "
            f"min permite como máximo {int(fila['tope_headway'])}; el plan programa {x} salidas, la mejor "
            f"aproximación ejecutable.")
    if flota_estado == "insuficiente":
        motivos.append(f"La flota disponible ({_f(flota, 0)} vehículos) no alcanza para sostener las salidas mínimas "
                       f"de la política de servicio en esta hora.")
    return motivos


def _sobreoferta_hora(occ, minimo: float, activos: list[str], hmax: float, nmin: int) -> str | None:
    """Motivo de la marca de sobreoferta (ocupación esperada < ocupación objetivo mínima de §5.1) o None."""
    if occ is None or occ >= minimo - 1e-9:
        return None
    causa = (f"la impone la espera máxima: el headway máximo efectivo de {_f(hmax, 2)} min exige al menos {nmin} "
             f"salidas" if "headway_maximo" in activos else
             "el costo de la espera y de la sobrecarga esperada del MILP justifica esa oferta")
    return (f"Sobreoferta: ocupación esperada en el punto de carga máxima {_f(100 * occ, 1)} %, menor que la ocupación "
            f"objetivo mínima de {_f(100 * minimo, 0)} % (§5.1); {causa}.")


def _hora_del_plan(i: int, contexto: dict) -> dict:
    """Una hora del plan con su explicación: límites activos, demanda de diseño, margen, viabilidad y sobreoferta."""
    from .motor_d5 import plan_base

    tb, gob, r = contexto["tb"], contexto["gob"], contexto["r"]
    fila = tb.iloc[i]
    h, x, minutos = int(fila["hora"]), int(fila["x_plan"]), float(fila["minutos"])
    v = {n: float(e["valor"]) for n, e in gob.items()}
    cap = float(fila["capacidad"])
    z = NormalDist().inv_cdf(v["nivel_servicio"])
    demanda_diseno = math.exp(float(fila["mu"]) + z * float(fila["s"]))
    cap_ef = x * cap * v["ocupacion_objetivo_max"]
    carga_p50 = float(fila["factor_carga"]) * float(fila["p50"])
    occ = carga_p50 / (x * cap) if x > 0 else None
    activos = _limites_hora(i, tb, contexto["flota_estado"], v["delta_suavidad"], v["hora_inicio_suavidad"])
    motivos = _viabilidad_hora(fila, contexto["flota_estado"].get(h), v["headway_minimo_min"],
                               v["headway_maximo_efectivo_min"], r["flota"])
    sobre = _sobreoferta_hora(occ, v["ocupacion_objetivo_min"], activos, v["headway_maximo_efectivo_min"],
                              int(fila["nmin"]))
    entrada = plan_base.entradas_d5(tb.iloc[[i]])[0]
    entrada["nmax"] = max(int(fila["tope_headway"]), int(fila["nmin"]))       # el tope gobernado es una cota dura
    margen = _margen_hora(entrada, x, contexto["p_milp"])
    margen.update({"capacidad_efectiva_pax_h": round(cap_ef, 1), "demanda_diseno_pax_h": round(demanda_diseno, 1),
                   "holgura_pax_h": round(cap_ef - demanda_diseno, 1),
                   "cobertura_demanda_diseno": round(cap_ef / demanda_diseno, 4) if demanda_diseno > 0 else None})
    return {
        "hora": h, "salidas": x, "despachos": contexto["por_hora"].get(h, []),
        "headway_min": round(minutos / x, 2) if x > 0 and minutos > 0 else None,
        "programar": int(fila["programar"]), "pasajeros_previstos": round(float(fila["p50"]), 2),
        "pasajeros_p10": _redondear(None if fila["p10"] is None else float(fila["p10"]), 2),
        "pasajeros_p90": _redondear(None if fila["p90"] is None else float(fila["p90"]), 2),
        "minutos_operados": minutos, "estado_solver": r["estado"], "tipo_dia": str(fila["tipo_dia"]),
        "modelo": contexto["model_id"], "fuente_pronostico": contexto["fuente"], "model_id": contexto["model_id"],
        "calibracion_version": contexto["calibracion"],
        "headway_minimo_min": v["headway_minimo_min"], "headway_maximo_min": v["headway_maximo_efectivo_min"],
        "minimo_salidas_headway": int(fila["nmin"]), "maximo_salidas_headway": int(fila["tope_headway"]),
        "salidas_sin_tope": int(fila["x_sin_tope"]),
        "limitada_por_headway_minimo": int(fila["x_sin_tope"]) > int(fila["tope_headway"]),
        "factor_carga": round(float(fila["factor_carga"]), 4), "demanda_diseno": round(demanda_diseno, 1),
        "capacidad_efectiva": round(cap_ef, 1), "ocupacion_esperada": _redondear(occ, 4),
        "buses_en_ruta_max": contexto["flota_max"].get(h), "limites_activos": activos, "margen": margen,
        "sin_intervalo": x == 1,          # una sola salida: no hay intervalo entre salidas que verificar en la hora
        "viable": not motivos, "motivo": " ".join(motivos) or None,
        "sobreoferta": sobre is not None, "motivo_sobreoferta": sobre,
    }


def _clave_plan(*partes) -> str:
    return json.dumps(partes, sort_keys=True, default=str, ensure_ascii=False)


def limpiar_cache_plan() -> None:
    """Vacía la memoria del plan del día y de su pronóstico (pruebas y mediciones en frío)."""
    with _PLANES_CANDADO:
        _PLANES.clear()
        _PRONOSTICOS.clear()


def plan_dia(fecha, ruta: str, *, umbrales: dict, umbrales_version: int | None, pronostico: str = "activo",
             pronostico_horario: list[dict] | None = None, model_id: str | None = None,
             fuente_costos: bool = True) -> dict:
    """Plan del día por hora (4-20 h) con el MILP de D5 y el pronóstico horario del modelo ACTIVO (contrato C1).

    - pronostico="activo" (por omisión): P10/P50/P90 de cada hora con inferencia (h = 60 al inicio de la hora, sin
      factor intradía), o los de `pronostico_horario` ({hora, p10, p50, p90}) si se pasan. Sirve para cualquier fecha
      con variables. pronostico="E12": el pronóstico precalculado de 2025 (opción de laboratorio).
    - Parámetros gobernados (parametros_plan, con la fuente de cada uno): nmin de cada hora = ceil(minutos / headway
      máximo efectivo) y tope = floor(minutos / headway mínimo) como cotas explícitas del MILP; costos y pesos de
      threshold_config.
    - Cada hora trae limites_activos, demanda_diseno, margen, viable y motivo, más la marca de sobreoferta (§5.1).
    La salida tiene las claves de resumen_plan_d5 más fuente_pronostico, model_id, calibracion_version, umbrales_version
    y parametros. Memoria por (fecha, ruta, model_id, calibracion_version, umbrales_version, pronostico). Lanza
    ValueError si la ruta, el pronóstico o la fecha no sirven.
    """
    from .motor_d5 import comun as C

    f = _fecha_de(fecha)
    if ruta not in C.ORDEN:
        raise ValueError(f"Ruta desconocida: {ruta!r}. Rutas válidas: {', '.join(C.ORDEN)}.")
    if pronostico not in PRONOSTICOS_PLAN:
        raise ValueError(f"pronostico debe ser uno de {', '.join(PRONOSTICOS_PLAN)} (recibido: {pronostico!r}).")
    gob = parametros_plan(umbrales, umbrales_version, fuente_costos)
    fuente, calibracion, pron = PRONOSTICOS_PLAN[pronostico], None, None
    if pronostico == "E12":
        modelo = FUENTE_E12
    elif pronostico_horario is not None:
        from app.servicios import inferencia

        pron = _normalizar_pronostico(pronostico_horario)
        modelo = model_id or inferencia.modelo_activo()
        calibracion = next((h.get("calibracion_version") for h in pronostico_horario if h.get("calibracion_version")),
                           None)
    else:
        lista, modelo, calibracion = _pronostico_memorizado(f, ruta, model_id)
        pron = _normalizar_pronostico(lista)
    clave = _clave_plan(f.isoformat(), ruta, modelo, calibracion, umbrales_version, pronostico,
                        {n: e["valor"] for n, e in gob.items()}, pron, bool(fuente_costos))
    with _PLANES_CANDADO:
        guardado = _PLANES.get(clave)
    if guardado is not None:
        return json.loads(guardado)
    texto = json.dumps(_calcular_plan(f, ruta, gob, pron, fuente, modelo, calibracion, umbrales_version,
                                      fuente_costos), default=str, ensure_ascii=False)
    with _PLANES_CANDADO:
        _PLANES[clave] = texto
        while len(_PLANES) > _PLANES_MAX:
            _PLANES.popitem(last=False)
    return json.loads(texto)


def _calcular_plan(f: date, ruta: str, gob: dict, pron, fuente: str, modelo: str, calibracion, umbrales_version,
                   fuente_costos: bool) -> dict:
    tb = _insumos_e12(f, ruta) if fuente == FUENTE_E12 else _insumos_modelo_activo(f, ruta, pron)
    tb = _con_cotas(tb.reset_index(drop=True), gob)
    p_milp = _p_milp(gob, fuente_costos)
    r = _resolver_plan(tb, p_milp)
    flota_max, flota_estado = _flota_por_hora(tb, r["flota"])
    por_hora = {}
    for m in r["horario"]:
        por_hora.setdefault(int(m) // 60, []).append(f"{int(m) // 60:02d}:{int(m) % 60:02d}")
    contexto = {"tb": tb, "gob": gob, "r": r, "p_milp": p_milp, "flota_max": flota_max, "flota_estado": flota_estado,
                "por_hora": por_hora, "fuente": fuente, "model_id": modelo, "calibracion": calibracion}
    horas = [_hora_del_plan(i, contexto) for i in range(len(tb))]
    programado = _intervalos_programados(ruta, f)
    total_prog = sum((_completar_hora_d5(h, tb.set_index("hora"), programado) for h in horas), 0.0)
    costos_hora = _componentes_por_hora(tb, _p_milp(gob, fuente_costos, ponderar=False))
    comp = _componentes(tb, {}, costos_hora)
    for h, c in zip(horas, costos_hora, strict=True):   # cada fila persistida lleva su costo y la flota del día
        h["componentes_costo_cop"] = {k: round(v, 2) for k, v in c.items()}
        h["costo_hora_cop"] = round(sum(c.values()), 2)
        h["flota_disponible"] = r["flota"]
    hmin, hmax = gob["headway_minimo_min"]["valor"], gob["headway_maximo_efectivo_min"]["valor"]
    return {
        "ruta": ruta, "fecha": f.isoformat(), "modelo": modelo, "tipo_dia": str(tb["tipo_dia"].iloc[0]),
        "estado_solver": r["estado"], "flota_disponible": r["flota"], "holgura_flota": round(r["holgura"], 4),
        "salidas_dia": int(sum(h["salidas"] for h in horas)),
        "salidas_programadas_dia": round(total_prog, 1) if total_prog else None,
        "vehiculos_hora_pico": max((h["vehiculos_requeridos"] for h in horas), default=0),
        "buses_en_ruta_pico": max((h["buses_en_ruta_max"] or 0.0 for h in horas), default=0.0),
        "definicion_vehiculos": DEFINICION_VEHICULOS,
        "componentes_costo_cop": comp, "costo_total_cop": round(sum(comp.values()), 2),
        "fuente_costos": gob["costo_bus_hora_cop"]["fuente"], "fuente_pronostico": fuente, "model_id": modelo,
        "calibracion_version": calibracion, "umbrales_version": umbrales_version,
        "headway_minimo_min": hmin, "headway_maximo_min": hmax,
        "horas_limitadas_por_headway_minimo": [h["hora"] for h in horas if h["limitada_por_headway_minimo"]],
        "horas_no_viables": [h["hora"] for h in horas if not h["viable"]],
        "horas_sobreoferta": [h["hora"] for h in horas if h["sobreoferta"]],
        "viable": all(h["viable"] for h in horas),
        "parametros": gob, "insumos_operativos": FUENTE_OPERATIVA if fuente != FUENTE_E12 else
        "datos/insumos_d5_2025.parquet (insumos de D5 del día) y datos/pronosticos_2025.parquet (E12)",
        "formulacion": (
            f"MILP D5 (PuLP/CBC) con el pronóstico {'del modelo activo ' + modelo if fuente != FUENTE_E12 else 'E12'}"
            f": para cada hora h (4-20) una binaria por nivel de salidas; min Σ α·costo operativo + β·espera + γ·"
            f"sobrecarga esperada (lognormal con la banda calibrada) + ingreso perdido, sujeto a flota en ruta cada "
            f"15 min, suavidad |x_h - x_(h-1)| <= DELTA, headway máximo efectivo de {_f(hmax, 2)} min (x_h >= "
            f"ceil(minutos_h / headway_max)) y headway mínimo gobernado de {_f(hmin, 2)} min (x_h <= "
            f"floor(minutos_h / headway_min))."),
        "horas": horas,
    }


def fila_plan(plan: dict, hora: dict) -> dict:
    """Columnas de ai_frecuencias.recommendation para una hora del plan (origen = 'plan_dia', sin prediction_id): el
    ciclo diario las persiste y GET /recommendations/plan las lee (plan_desde_filas)."""
    from .motor_d5 import comun as C

    resumen = {k: v for k, v in plan.items() if k != "horas"}
    try:   # §8.3: idruta del catálogo empaquetado (app/servicios/dimensiones); si no, el de D5
        from app.servicios import dimensiones

        idruta = dimensiones.idruta(plan["ruta"])
    except Exception:  # noqa: BLE001 - la dimensión nunca impide persistir el plan
        idruta = None
    diferencia = None
    if hora.get("headway_min") is not None and hora.get("frecuencia_actual_min") is not None:
        diferencia = round(hora["headway_min"] - hora["frecuencia_actual_min"], 2)
    return {"ruta": plan["ruta"], "fecha": _fecha_de(plan["fecha"]), "hora": int(hora["hora"]),
            "demanda_hora": hora.get("pasajeros_previstos"), "demanda_p90": hora.get("pasajeros_p90"),
            "buses_hora": int(hora["salidas"]), "headway_min": hora.get("headway_min"),
            "vehiculos_requeridos": hora.get("vehiculos_requeridos"),
            "capacidad_efectiva": hora.get("capacidad_efectiva"),
            "ocupacion_esperada": hora.get("ocupacion_esperada"), "viable": bool(hora.get("viable", True)),
            "motivo": hora.get("motivo"), "frecuencia_actual_min": hora.get("frecuencia_actual_min"),
            "diferencia_min": diferencia, "formula": plan.get("formulacion"),
            "umbrales_version": plan.get("umbrales_version"), "origen": "plan_dia",
            "idruta": idruta if idruta is not None else C.ID_RUTA.get(plan["ruta"]),
            "detalle": {"origen": "plan_dia", "hora_plan": hora, "plan": resumen}}


def _attr(fila, nombre, defecto=None):
    if isinstance(fila, dict):
        return fila.get(nombre, defecto)
    return getattr(fila, nombre, defecto)


def _hora_desde_fila(fila) -> dict:
    """Una hora del plan desde la fila persistida (detalle.hora_plan o, si no está, las columnas)."""
    det = _attr(fila, "detalle") or {}
    salida = det.get("salida") if isinstance(det.get("salida"), dict) else {}
    for candidato in (det.get("hora_plan"), salida.get("hora_plan"), salida):
        if isinstance(candidato, dict) and "salidas" in candidato:
            return dict(candidato)
    return {"hora": int(_attr(fila, "hora")), "salidas": int(_attr(fila, "buses_hora") or 0),
            "headway_min": _attr(fila, "headway_min"), "vehiculos_requeridos": _attr(fila, "vehiculos_requeridos"),
            "pasajeros_previstos": _attr(fila, "demanda_hora"), "pasajeros_p90": _attr(fila, "demanda_p90"),
            "frecuencia_actual_min": _attr(fila, "frecuencia_actual_min"), "viable": bool(_attr(fila, "viable", True)),
            "motivo": _attr(fila, "motivo"), "ocupacion_esperada": _attr(fila, "ocupacion_esperada"),
            "capacidad_efectiva": _attr(fila, "capacidad_efectiva")}


def _primero(horas: list[dict], clave: str):
    return next((h[clave] for h in horas if h.get(clave) is not None), None)


def _resumen_desde_horas(horas: list[dict]) -> dict:
    """El resumen del día que se puede rehacer con las horas persistidas (cada hora del plan lleva su costo, la flota
    del día y su comparación con lo programado): salidas programadas, flota, costo y vehículos con su definición."""
    programadas = sum(float(h.get("salidas_programadas") or 0.0) for h in horas)
    costos = [h["componentes_costo_cop"] for h in horas if isinstance(h.get("componentes_costo_cop"), dict)]
    comp = {}
    for c in costos:
        for nombre, valor in c.items():
            comp[nombre] = comp.get(nombre, 0.0) + float(valor or 0.0)
    comp = {k: round(v, 2) for k, v in comp.items()}
    en_ruta = [float(h["buses_en_ruta_max"]) for h in horas if h.get("buses_en_ruta_max") is not None]
    con_viabilidad = [h for h in horas if h.get("viable") is not None]
    return {
        "salidas_programadas_dia": round(programadas, 1) if programadas else None,
        "flota_disponible": _primero(horas, "flota_disponible"),
        "componentes_costo_cop": comp,
        "costo_total_cop": round(sum(float(h["costo_hora_cop"]) for h in horas if h.get("costo_hora_cop") is not None),
                                 2) if any(h.get("costo_hora_cop") is not None for h in horas) else None,
        "vehiculos_hora_pico": max((int(h.get("vehiculos_requeridos") or 0) for h in horas), default=0),
        "buses_en_ruta_pico": max(en_ruta) if en_ruta else None,
        "definicion_vehiculos": DEFINICION_VEHICULOS,
        "tipo_dia": _primero(horas, "tipo_dia"), "estado_solver": _primero(horas, "estado_solver"),
        "fuente_pronostico": _primero(horas, "fuente_pronostico"), "model_id": _primero(horas, "model_id"),
        "calibracion_version": _primero(horas, "calibracion_version"),
        "headway_minimo_min": _primero(horas, "headway_minimo_min"),
        "headway_maximo_min": _primero(horas, "headway_maximo_min"),
        "horas_limitadas_por_headway_minimo": [h["hora"] for h in horas if h.get("limitada_por_headway_minimo")],
        "horas_sobreoferta": [h["hora"] for h in horas if h.get("sobreoferta")],
        "viable": all(h["viable"] for h in con_viabilidad) if con_viabilidad else None,
    }


def _resumen_de_fila(fila) -> dict | None:
    """Resumen del día guardado en una fila persistida: detalle.plan, detalle.entradas.plan o detalle.entradas (el
    formato del ciclo diario, cuando trae model_id); None si la fila no trae ninguno."""
    det = _attr(fila, "detalle") or {}
    entradas = det.get("entradas") if isinstance(det.get("entradas"), dict) else {}
    return det.get("plan") or entradas.get("plan") or (entradas if entradas.get("model_id") else None)


def _resumen_persistido(filas) -> dict | None:
    """El primer resumen del día guardado en las filas (en el orden recibido), o None si ninguna lo trae."""
    for fila in filas:
        resumen = _resumen_de_fila(fila)
        if resumen:
            return resumen
    return None


def _completar_con_horas(plan: dict, horas: list[dict]) -> None:
    """Completa en `plan` lo que el resumen persistido no trae (claves ausentes o en None, y los componentes del costo
    vacíos) con lo que se rehace con las horas (_resumen_desde_horas)."""
    for clave, valor in _resumen_desde_horas(horas).items():
        if plan.get(clave) is None or (clave == "componentes_costo_cop" and not plan.get(clave)):
            plan[clave] = valor


def _instante_bogota(instante):
    """§8.1: un datetime con zona horaria pasa a la hora de Bogotá (ISO 8601, a segundos); cualquier otro valor (sin
    zona, texto o None) queda igual."""
    if isinstance(instante, datetime) and instante.tzinfo is not None:
        from zoneinfo import ZoneInfo

        return instante.astimezone(ZoneInfo("America/Bogota")).isoformat(timespec="seconds")
    return instante


def plan_desde_filas(filas) -> dict:
    """Plan del día (claves de plan_dia) desde las filas persistidas con origen = 'plan_dia' de una ejecución. Lo que
    el resumen guardado no trae (el ciclo diario guarda solo una parte) se rehace con las horas: salidas programadas,
    flota disponible, costo del día y vehículos en la hora pico con su definición."""
    filas = sorted(filas, key=lambda x: int(_attr(x, "hora")))
    horas = [_hora_desde_fila(x) for x in filas]
    resumen = _resumen_persistido(filas)
    primera = filas[0]
    plan = {"formulacion": _attr(primera, "formula"), "umbrales_version": _attr(primera, "umbrales_version")}
    plan.update(resumen or {})
    _completar_con_horas(plan, horas)
    plan["modelo"] = plan.get("modelo") or plan.get("model_id") or "modelo_activo"
    creado = _instante_bogota(_attr(primera, "creado_en"))
    plan.update(ruta=_attr(primera, "ruta"), fecha=str(_attr(primera, "fecha"))[:10], horas=horas,
                salidas_dia=int(sum(int(h.get("salidas") or 0) for h in horas)),
                horas_no_viables=[h["hora"] for h in horas if h.get("viable") is False],
                execution_id=None if _attr(primera, "execution_id") is None else str(_attr(primera, "execution_id")),
                calculado_en=creado,
                origen="plan_dia persistido por el ciclo diario (ai_frecuencias.recommendation)")
    return plan


# ======================================================================================================================
# §10.2 Función objetivo explícita y configurable, MILP de una franja (PuLP/CBC), tipologías (§10.1), escenarios
# (RF-008) y sensibilidad (§10.3). Todos los montos en COP por hora de la franja.
# ======================================================================================================================
Z90 = NormalDist().inv_cdf(0.90)
EPS_CAPACIDAD = 1e-3            # desempate: a igual costo se prefiere la menor capacidad (reserva los buses grandes)

# nombre -> (valor por omisión, descripción). Se versionan en threshold_config (PUT /thresholds crea una versión nueva);
# si un nombre no está en la tabla rige el valor del código, y la respuesta dice de dónde salió cada uno.
PARAMETROS_OBJETIVO: dict[str, tuple[float, str]] = {
    "peso_costo_operativo": (1.0, "§10.2 α: peso del costo operativo (COP/h) en la función objetivo"),
    "peso_tiempo_espera": (1.0, "§10.2 β: peso del costo del tiempo de espera de los pasajeros (COP/h)"),
    "peso_sobreocupacion": (1.0, "§10.2 γ: peso de la penalización por sobreocupación esperada (COP/h)"),
    "peso_desviacion_frecuencia": (1.0, "§10.2 δ: peso de la desviación frente a la frecuencia programada (COP/h)"),
    "nivel_servicio": (0.90, "§10.2 nivel de servicio: probabilidad de que la carga crítica quepa en la capacidad "
                             "efectiva; 0,90 = P90 calibrado del modelo"),
    "costo_bus_hora_cop": (26400.22, "Costo de un bus-hora de conductor (COP 2026, costos/ con fuente; datos/"
                                     "costos_fuente.json)"),
    "costo_km_cop": (1991.24, "Costo evitable por km recorrido (COP 2026, costos/ con fuente)"),
    "valor_tiempo_espera_cop_h": (7000.0, "Valor del tiempo de espera de un pasajero (COP por hora; supuesto de D5)"),
    "penalidad_sobreocupacion_cop": (10000.0, "Penalidad por pasajero esperado por encima de la ocupación crítica "
                                              "(COP; supuesto de D5)"),
    "costo_cambio_frecuencia_cop": (26400.22, "Costo de apartarse 1 bus/h de la frecuencia programada (COP; supuesto "
                                              "del equipo: 1 bus-hora de conductor por reprogramación)"),
}
PESOS = {"alfa": "peso_costo_operativo", "beta": "peso_tiempo_espera", "gamma": "peso_sobreocupacion",
         "delta": "peso_desviacion_frecuencia"}
SIMBOLO = {"alfa": "α", "beta": "β", "gamma": "γ", "delta": "δ"}

# Datos de ruta (medianas de 2025 en datos/insumos_d5_2025.parquet): km de un ciclo y CV de los intervalos reales (D4).
KM_CICLO = {RUTA_SILENCIO: 62.9, RUTA_CRA_54: 56.4, RUTA_CL_72: 57.0}
CV_INTERVALOS = {RUTA_SILENCIO: 0.647, RUTA_CRA_54: 0.698, RUTA_CL_72: 0.533}
KM_CICLO_POR_OMISION = 59.0
CV_POR_OMISION = 0.6
ARCHIVO_TIPOLOGIAS = Path(__file__).resolve().parent / "tipologias_flota.json"


def validar_parametros_objetivo(valores: dict) -> None:
    """Valida los parámetros de la función objetivo presentes en `valores` (ValueError con el motivo)."""
    for nombre in set(valores) & set(PARAMETROS_OBJETIVO):
        v = _num(nombre, valores[nombre], 0)
        if nombre == "nivel_servicio" and not 0.5 <= v < 1:
            raise ValueError(f"nivel_servicio es una probabilidad en [0,5; 1) (recibido: {v}).")
    pesos = [float(valores[n]) for n in PESOS.values() if n in valores]
    if len(pesos) == len(PESOS) and sum(pesos) <= 0:
        raise ValueError("Al menos uno de los pesos α, β, γ, δ debe ser positivo.")


def _pedido_objetivo(sobrescribir: dict | None) -> dict:
    """Valores pedidos en la solicitud, con los nombres largos (alfa/beta/gamma/delta se traducen); None se ignora."""
    pedido = {}
    for k, v in (sobrescribir or {}).items():
        if v is None:
            continue
        nombre = PESOS.get(k, k)
        if nombre not in PARAMETROS_OBJETIVO:
            raise ValueError(f"Parámetro de la función objetivo desconocido: {k!r}. Válidos: "
                             f"{', '.join(list(PESOS) + list(PARAMETROS_OBJETIVO))}.")
        pedido[nombre] = v
    return pedido


def parametros_objetivo(umbrales: dict | None = None, version: int | None = None,
                        sobrescribir: dict | None = None) -> dict:
    """Valores efectivos de la función objetivo: código <- threshold_config vigente <- solicitud.

    Devuelve {nombre: {"valor": float, "fuente": str}}. `sobrescribir` acepta los nombres largos o
    alfa/beta/gamma/delta.
    """
    umbrales = umbrales or {}
    pedido = _pedido_objetivo(sobrescribir)
    efectivos = {}
    for nombre, (defecto, _desc) in PARAMETROS_OBJETIVO.items():
        if nombre in pedido:
            efectivos[nombre] = {"valor": _num(nombre, pedido[nombre], 0), "fuente": "solicitud"}
        elif nombre in umbrales and umbrales[nombre] is not None:
            fuente = f"threshold_config v{version}" if version is not None else "threshold_config"
            efectivos[nombre] = {"valor": _num(nombre, umbrales[nombre], 0), "fuente": fuente}
        else:
            efectivos[nombre] = {"valor": float(defecto), "fuente": FUENTE_POR_OMISION}
    validar_parametros_objetivo({n: e["valor"] for n, e in efectivos.items()})
    return efectivos


@lru_cache(maxsize=1)
def _tipologias_archivo() -> dict:
    return json.loads(ARCHIVO_TIPOLOGIAS.read_text(encoding="utf-8"))


def tipologias_ruta(ruta: str, flota_disponible: float | None = None) -> list[dict]:
    """Tipologías de capacidad de la ruta (§10.1) desde tipologias_flota.json (flota_sobusa.csv agregada, sin placas).

    Con `flota_disponible`, reparte esa flota entre tipologías en la proporción de la flota registrada de la ruta
    (método del mayor residuo): `disponibles` es el número de vehículos de cada tipología para la franja.
    """
    filas = _tipologias_archivo().get("rutas", {}).get(ruta) or []
    salida = [{"codigo": f["codigo"], "nombre": f["nombre"], "capacidad": int(f["capacidad"]),
               "vehiculos_registrados": int(f["vehiculos"]), "participacion": float(f["participacion"]),
               "sentados": f.get("sentados"), "de_pie": f.get("de_pie"), "disponibles": None} for f in filas]
    if flota_disponible is not None and salida:
        total = int(math.floor(float(flota_disponible) + EPS))
        cuotas = [t["participacion"] * total for t in salida]
        base = [int(math.floor(c)) for c in cuotas]
        resto = total - sum(base)
        orden = sorted(range(len(salida)), key=lambda i: (-(cuotas[i] - base[i]), i))
        for i in orden[:max(resto, 0)]:
            base[i] += 1
        for t, b in zip(salida, base, strict=True):
            t["disponibles"] = b
    return salida


TIPO_DIA_FESTIVO = "Domingo/festivo"
ARCHIVO_INSUMOS_D5 = "insumos_d5_2025.parquet"     # insumos de D5 de 2025 (motor_d5.comun.DATOS)
TIPOS_DIA = ("Laboral", "Sábado", TIPO_DIA_FESTIVO)


@lru_cache(maxsize=4)
def _festivos(carpeta_insumos: str, huella_insumos: float, huella_contexto: float) -> frozenset:
    """Días que se operan como «Domingo/festivo»: los que D5 trata así (tipo_dia de insumos_d5_2025.parquet) y los
    festivos oficiales del calendario (festivo_oficial de contexto_operacional.parquet, FESTIVO_NACIONAL). Las huellas
    (mtime de cada archivo) renuevan la caché si los datos cambian."""
    import pandas as pd

    from app.servicios import datos

    dias = set()
    if huella_insumos >= 0:
        d = pd.read_parquet(Path(carpeta_insumos) / ARCHIVO_INSUMOS_D5, columns=["dia", "tipo_dia"])
        d = d[d["tipo_dia"].astype(str) == TIPO_DIA_FESTIVO]
        dias |= {pd.Timestamp(x).date() for x in d["dia"].unique()}
    if huella_contexto >= 0:
        c = datos.contexto_operacional()
        dias |= {pd.Timestamp(x).date() for x in c.loc[c["festivo_oficial"] > 0, "fecha"].unique()}
    return frozenset(dias)


def es_festivo(fecha) -> bool:
    """True si `fecha` es festivo para la operación (D5 o calendario oficial); un domingo cuenta aunque no figure."""
    from app.servicios import datos

    from .motor_d5 import comun as C

    if fecha is None:
        return False
    f = _fecha_de(fecha)
    insumos = C.DATOS / ARCHIVO_INSUMOS_D5
    huella = insumos.stat().st_mtime if insumos.exists() else -1.0
    return f in _festivos(str(C.DATOS), huella, datos.huella_archivo("contexto_operacional.parquet"))


def tipo_dia_operacion(fecha) -> int:
    """Tipo de día de la operación (0 Laboral, 1 Sábado, 2 Domingo/festivo) con los festivos entre semana, el mismo
    criterio de D5; sin fecha, laboral. Lo usan la programación de comparación, el contexto y el factor de carga."""
    from app.servicios import datos

    if fecha is None:
        return 0
    f = _fecha_de(fecha)
    return datos.tipo_dia_de(f, festivo=es_festivo(f))


def _intervalos_programados(ruta: str, fecha: date | None) -> dict[int, float]:
    """Intervalo programado (min) por hora para el tipo de día de `fecha` (parametros_operativos_hora.parquet, D1). Un
    festivo entre semana usa la programación de domingo o festivo, como el plan D5."""
    from app.servicios import datos

    try:
        p = datos.parametros_operativos(ruta)
    except Exception:  # noqa: BLE001 - sin el archivo se usa la frecuencia del catálogo
        return {}
    if p is None or p.empty:
        return {}
    letra = "LSD"[tipo_dia_operacion(fecha)]
    p = p[p["tipo_dia"].astype(str).str[:1] == letra]
    return {int(h): float(v) for h, v in zip(p["hora"], p["intervalo_programado_min"], strict=True) if v and v > 0}


def contexto_franja(ruta: str, fecha: date | None, hora: int) -> dict:
    """Ciclo, flota e intervalo programado de la franja (ruta, tipo de día, hora) desde parametros_operativos_hora
    (mediana 2025 de D1). Un festivo entre semana usa los parámetros de domingo o festivo. Vacío si la hora no tiene
    parámetros (fuera de 4-20 h)."""
    from app.servicios import datos

    try:
        p = datos.parametros_operativos(ruta)
    except Exception:  # noqa: BLE001
        return {}
    if p is None or p.empty:
        return {}
    tipo = tipo_dia_operacion(fecha)
    letra = "LSD"[tipo]
    f = p[(p["tipo_dia"].astype(str).str[:1] == letra) & (p["hora"] == int(hora))]
    if f.empty:
        return {}
    fila = f.iloc[0]

    def _positivo(v):                  # una hora sin servicio programado trae NaN: no hay frecuencia que comparar
        v = None if v is None else float(v)
        return v if v is not None and math.isfinite(v) and v > 0 else None

    ciclo, flota, intervalo = (_positivo(fila["tiempo_ciclo_min"]), _positivo(fila["flota"]),
                               _positivo(fila["intervalo_programado_min"]))
    return {"tipo_dia": TIPOS_DIA[tipo],
            "tiempo_ciclo_min": None if ciclo is None else round(ciclo, 2),
            "flota_disponible": None if flota is None else int(flota),
            "frecuencia_actual_min": None if intervalo is None else round(intervalo, 2),
            "fuente": "datos/parametros_operativos_hora.parquet (mediana 2025 por ruta, tipo de día y hora; D1)"}


@lru_cache(maxsize=1)
def _factores_carga_hora() -> dict:
    """§10.1 «ocupación histórica por día de la semana y rango de horas»: mediana 2025 de carga crítica / abordajes
    (L_real / real de datos/insumos_d5_2025.parquet, horas con > 20 abordajes) por ruta, tipo de día y hora."""
    from .motor_d5 import comun as C

    archivo = C.DATOS / ARCHIVO_INSUMOS_D5
    if not archivo.exists():
        return {}
    import pandas as pd

    d = pd.read_parquet(archivo, columns=["ruta", "tipo_dia", "hora", "real", "L_real"])
    d = d[(d["real"] > 20) & (d["L_real"] > 0)].copy()
    d["f"] = d["L_real"] / d["real"]
    d["t"] = d["tipo_dia"].astype(str).str[:1]
    g = d.groupby(["ruta", "t", "hora"])["f"].agg(["median", "count"])
    return {(str(r), str(t), int(h)): (float(m), int(n)) for (r, t, h), (m, n) in g.iterrows() if n >= 10}


def factor_carga_franja(ruta: str, fecha: date | None, hora: int) -> dict | None:
    """Factor de carga crítica de la franja (ruta, tipo de día, hora); None si no hay al menos 10 días con datos. Un
    festivo entre semana usa el factor de domingo o festivo."""
    letra = "LSD"[tipo_dia_operacion(fecha)]
    v = _factores_carga_hora().get((ruta, letra, int(hora)))
    if v is None:
        return None
    return {"factor_carga": round(min(max(v[0], 0.05), 1.0), 4), "dias": v[1],
            "fuente": "mediana 2025 de carga crítica / abordajes por ruta, tipo de día y hora (insumos D5)"}


def _distribucion_carga(demanda, p90, p10, factor, nivel):
    """Carga crítica L = factor × demanda ~ lognormal con mediana factor × demanda puntual y dispersión del P90
    calibrado (s = ln(P90 / P50) / z_0,90; si solo hay P10, s = ln(P50 / P10) / z_0,90; sin banda, s = 0).
    Devuelve (mu, s, carga de diseño = cuantil `nivel` de L, criterio)."""
    if demanda <= 0:
        base = max(p90 or 0.0, 0.0)
        return (None, 0.0, factor * base, "sin demanda puntual: P90" if base > 0 else "demanda nula")
    if p90 is not None and p90 > demanda:
        s = math.log(p90 / demanda) / Z90
        criterio = "banda P90 calibrada"
    elif p10 is not None and 0 < p10 < demanda:
        s = math.log(demanda / p10) / Z90
        criterio = "banda P10 calibrada (simétrica en log)"
    else:
        s = 0.0
        criterio = "demanda puntual (sin banda)"
    mu = math.log(factor * demanda)
    z = NormalDist().inv_cdf(nivel)
    return mu, s, math.exp(mu + z * s), criterio


def _sobrecarga(mu, s, capacidad_critica):
    """E[(L - c)^+] en pasajeros para L ~ lognormal(mu, s); determinista si s = 0 (la fórmula de D5, motor_d5.milp)."""
    if mu is None:
        return 0.0
    c = max(float(capacidad_critica), 1e-9)
    if s <= 1e-9:
        return max(math.exp(mu) - c, 0.0)
    nd = NormalDist()
    d1 = (mu + s * s - math.log(c)) / s
    return math.exp(mu + s * s / 2) * nd.cdf(d1) - c * nd.cdf(d1 - s)


def _derivada_sobrecarga(mu, s, capacidad_critica):
    """d E[(L - c)^+] / dc = -P(L > c)."""
    if mu is None:
        return 0.0
    c = max(float(capacidad_critica), 1e-9)
    if s <= 1e-9:
        return -1.0 if math.exp(mu) > c else 0.0
    return -(1.0 - NormalDist().cdf((math.log(c) - mu) / s))


class _Franja:
    """Datos de una franja ya validados y los costos de §10.2 de cualquier solución (k buses/h, mezcla n_t)."""

    def __init__(self, *, demanda, pax, mu, s, carga_diseno, occ, occ_crit, ciclo, km, cv, k_act, flota, tipos, p,
                 k_lo, k_hi):
        self.demanda, self.pax, self.mu, self.s, self.carga_diseno = demanda, pax, mu, s, carga_diseno
        self.occ, self.occ_crit, self.ciclo, self.km, self.cv, self.k_act = occ, occ_crit, ciclo, km, cv, k_act
        self.flota, self.tipos, self.p, self.k_lo, self.k_hi = flota, tipos, p, k_lo, k_hi
        self.caps = [float(t["capacidad"]) for t in tipos]
        ciclo_h = (ciclo if ciclo is not None else 60.0) / 60.0
        self.costo_salida = ciclo_h * p["costo_bus_hora_cop"] + km * p["costo_km_cop"]
        self.cotas = []
        for t in tipos:
            cota = k_hi
            if t.get("disponibles") is not None and ciclo:
                cota = min(cota, int(math.floor(t["disponibles"] * 60.0 / ciclo + EPS)))
            self.cotas.append(max(cota, 0))

    def pesos(self):
        return (self.p["peso_costo_operativo"], self.p["peso_tiempo_espera"], self.p["peso_sobreocupacion"],
                self.p["peso_desviacion_frecuencia"])

    def espera_min(self, k):
        return (60.0 / k) / 2.0 * (1.0 + self.cv ** 2) if k > 0 else None

    def vehiculos(self, n):
        if self.ciclo is None:
            return None
        return int(sum(math.ceil(self.ciclo * x / 60.0 - EPS) for x in n))

    def evaluar(self, n):
        """Componentes (COP/h, sin ponderar), total ponderado y cifras operativas de la mezcla n (buses/h por tipo)."""
        k = int(sum(n))
        cap = float(sum(c * x for c, x in zip(self.caps, n, strict=True)))
        op = k * self.costo_salida
        esp = self.espera_min(k)
        espera = self.pax * esp / 60.0 * self.p["valor_tiempo_espera_cop_h"] if esp is not None else 0.0
        sobre_pax = _sobrecarga(self.mu, self.s, cap * self.occ_crit)
        sobre = self.p["penalidad_sobreocupacion_cop"] * sobre_pax
        desv_bus = abs(k - self.k_act) if self.k_act is not None else 0.0
        desv = self.p["costo_cambio_frecuencia_cop"] * desv_bus
        a, b, g, d = self.pesos()
        total = a * op + b * espera + g * sobre + d * desv
        return {"buses_hora": k, "capacidad_ofrecida": cap, "vehiculos": self.vehiculos(n),
                "espera_media_min": round(esp, 3) if esp is not None else None,
                "sobrecarga_esperada_pax": round(sobre_pax, 3), "desviacion_buses_hora": round(desv_bus, 3),
                "componentes_cop": {"costo_operativo": round(op, 2), "tiempo_espera": round(espera, 2),
                                    "sobreocupacion": round(sobre, 2), "desviacion_frecuencia": round(desv, 2)},
                "total_ponderado_cop": round(total, 2), "_total": total + EPS_CAPACIDAD * cap}

    def factible(self, n, exigir_servicio=True):
        k = sum(n)
        if not self.k_lo <= k <= self.k_hi:
            return False
        if any(x > c for x, c in zip(n, self.cotas, strict=True)):
            return False
        if self.flota is not None and self.ciclo is not None and self.vehiculos(n) > self.flota + EPS:
            return False
        cap = sum(c * x for c, x in zip(self.caps, n, strict=True))
        return not (exigir_servicio and cap * self.occ < self.carga_diseno - 1e-7)


def _enumerar(fr: _Franja, exigir_servicio=True, limite=2_000_000, maximizar_cobertura=False):
    """Búsqueda exhaustiva exacta (verificación del MILP y respaldo si el solver falla). None si no hay solución.

    Con maximizar_cobertura (y sin exigir el nivel de servicio): la mezcla factible con más capacidad efectiva hasta la
    carga de diseño y, entre esas, la de menor costo; es la «mejor aproximación» de una franja inviable."""
    tamano = 1
    for c in fr.cotas:
        tamano *= (c + 1)
    if tamano > limite:
        raise RuntimeError(f"Espacio de búsqueda demasiado grande para enumerar ({tamano} mezclas)")
    mejor = None
    for n in itertools.product(*[range(c + 1) for c in fr.cotas]):
        if not fr.factible(n, exigir_servicio):
            continue
        e = fr.evaluar(n)
        cobertura = min(e["capacidad_ofrecida"] * fr.occ, fr.carga_diseno) if maximizar_cobertura else 0.0
        clave = (-round(cobertura, 6), e["_total"])
        if mejor is None or clave < mejor[2]:
            mejor = (list(n), e, clave)
    return None if mejor is None else (mejor[0], mejor[1])


def _capacidades_alcanzables(fr: _Franja, maximo=4000):
    sumas = {0.0}
    for c, cota in zip(fr.caps, fr.cotas, strict=True):
        sumas = {s + j * c for s in sumas for j in range(cota + 1)}
        if len(sumas) > maximo:
            break
    return sorted(sumas)


_SOLUCIONES_MILP: OrderedDict = OrderedDict()
_SOLUCIONES_MAX = 4096
_SOLUCIONES_CANDADO = threading.Lock()
_ESTADOS_DETERMINISTAS = ("Optimal", "Infeasible")


def _clave_franja(fr: _Franja, exigir_servicio: bool) -> tuple:
    """Todo lo que entra al MILP de la franja: dos franjas con la misma clave tienen el mismo problema."""
    return (bool(exigir_servicio), fr.k_lo, fr.k_hi, tuple(fr.caps), tuple(fr.cotas), fr.ciclo, fr.flota, fr.occ,
            fr.occ_crit, fr.carga_diseno, fr.mu, fr.s, fr.pax, fr.cv, fr.costo_salida, fr.k_act,
            tuple(sorted(fr.p.items())))


def _resolver_milp(fr: _Franja, exigir_servicio=True):
    """MILP de la franja (_resolver_milp_cbc) con memoria en el proceso: una franja idéntica (mismos datos, límites,
    tipologías, pesos y costos) reutiliza la solución ya calculada en lugar de volver a llamar a CBC, que es lo que
    más tarda (unos 50 ms por solución en Windows, casi todo en arrancar el proceso del solver). El resultado es el
    mismo; `segundos` es el tiempo del solver cuando se resolvió. Solo se guardan los estados que no dependen del
    tiempo (óptimo o infactible), nunca un corte por tiempo ni un error."""
    clave = _clave_franja(fr, exigir_servicio)
    with _SOLUCIONES_CANDADO:
        guardada = _SOLUCIONES_MILP.get(clave)
        if guardada is not None:
            _SOLUCIONES_MILP.move_to_end(clave)
    if guardada is None:
        guardada = _resolver_milp_cbc(fr, exigir_servicio)
        if guardada[1] in _ESTADOS_DETERMINISTAS:
            with _SOLUCIONES_CANDADO:
                _SOLUCIONES_MILP[clave] = guardada
                while len(_SOLUCIONES_MILP) > _SOLUCIONES_MAX:
                    _SOLUCIONES_MILP.popitem(last=False)
    mezcla, estado, seg = guardada
    return (None if mezcla is None else list(mezcla)), estado, seg


def limpiar_memoria_milp() -> None:
    """Vacía la memoria de soluciones de la franja (pruebas y mediciones en frío)."""
    with _SOLUCIONES_CANDADO:
        _SOLUCIONES_MILP.clear()


def _resolver_milp_cbc(fr: _Franja, exigir_servicio=True):
    """MILP de la franja con PuLP/CBC. Devuelve (mezcla, estado, segundos) o (None, estado, segundos).

    Variables: y_k binaria por nivel k de buses/h (la espera, convexa en 1/k, se precalcula por nivel como en D5);
    n_t entera (buses/h de la tipología t, n_t <= vehículos disponibles × 60 / ciclo); m_t entera (vehículos de la
    tipología t, m_t >= ciclo × n_t / 60, Σ m_t <= flota); z >= 0 la sobrecarga esperada, con cortes tangentes en
    todas las capacidades alcanzables (exactos porque E[(L - c)^+] es convexa); d >= |K - k_actual|.
    """
    import pulp

    t0 = time.perf_counter()
    prob = pulp.LpProblem("franja_10_2", pulp.LpMinimize)
    niveles = list(range(fr.k_lo, fr.k_hi + 1))
    y = {k: pulp.LpVariable(f"y_{k}", cat="Binary") for k in niveles}
    n = [pulp.LpVariable(f"n_{i}", lowBound=0, upBound=fr.cotas[i], cat="Integer") for i in range(len(fr.caps))]
    prob += pulp.lpSum(y.values()) == 1, "un_nivel"
    K = pulp.lpSum(k * y[k] for k in niveles)
    prob += pulp.lpSum(n) == K, "mezcla_igual_nivel"
    C = pulp.lpSum(c * x for c, x in zip(fr.caps, n, strict=True))
    if fr.ciclo is not None and fr.flota is not None:
        m = [pulp.LpVariable(f"m_{i}", lowBound=0, cat="Integer") for i in range(len(fr.caps))]
        for i in range(len(fr.caps)):
            prob += m[i] >= fr.ciclo / 60.0 * n[i], f"ciclo_{i}"
        prob += pulp.lpSum(m) <= fr.flota, "flota"
    deficit = None
    if exigir_servicio:
        prob += fr.occ * C >= fr.carga_diseno - 1e-7, "nivel_servicio"
    else:
        deficit = pulp.LpVariable("deficit", lowBound=0)
        prob += fr.occ * C + deficit >= fr.carga_diseno, "nivel_servicio_relajado"
    z = pulp.LpVariable("sobrecarga", lowBound=0)
    if fr.mu is not None:
        for j, cap in enumerate(_capacidades_alcanzables(fr)):
            g = _sobrecarga(fr.mu, fr.s, cap * fr.occ_crit)
            dg = _derivada_sobrecarga(fr.mu, fr.s, cap * fr.occ_crit) * fr.occ_crit
            prob += z >= g + dg * (C - cap), f"tangente_{j}"
    a, b, g_, d_ = fr.pesos()
    obj = (a * fr.costo_salida * K
           + b * pulp.lpSum(y[k] * (fr.pax * fr.espera_min(k) / 60.0 * fr.p["valor_tiempo_espera_cop_h"])
                            for k in niveles)
           + g_ * fr.p["penalidad_sobreocupacion_cop"] * z + EPS_CAPACIDAD * C)
    if fr.k_act is not None:
        dv = pulp.LpVariable("desviacion", lowBound=0)
        prob += dv >= K - fr.k_act, "desv_sube"
        prob += dv >= fr.k_act - K, "desv_baja"
        obj += d_ * fr.p["costo_cambio_frecuencia_cop"] * dv
    if deficit is not None:
        obj += 1e9 * deficit
    prob += obj
    prob.solve(pulp.PULP_CBC_CMD(msg=0, timeLimit=20))
    estado = pulp.LpStatus[prob.status]
    seg = time.perf_counter() - t0
    if estado != "Optimal":
        return None, estado, seg
    mezcla = [int(round(x.value() or 0)) for x in n]
    return mezcla, estado, seg


def _restricciones(fr: _Franja, n, e) -> list[dict]:
    """Estado de cada restricción de §10.2 en la solución: valor, límite, holgura y si está activa (manda)."""
    k = e["buses_hora"]
    cap = e["capacidad_ofrecida"]
    menor = min((c for c, x in zip(fr.caps, n, strict=True) if x > 0), default=min(fr.caps))
    filas = [
        {"nombre": "headway_minimo", "descripcion": "Headway mínimo (separación mínima entre despachos)",
         "valor": round(60.0 / k, 2), "limite": round(60.0 / fr.k_hi, 2) if fr.k_hi else None,
         "unidad": "min", "activa": k >= fr.k_hi},
        {"nombre": "headway_maximo", "descripcion": "Headway máximo (espera máxima de la política de servicio)",
         "valor": round(60.0 / k, 2), "limite": round(60.0 / fr.k_lo, 2) if fr.k_lo else None,
         "unidad": "min", "activa": k <= fr.k_lo},
        {"nombre": "nivel_servicio",
         "descripcion": "Capacidad: capacidad efectiva >= carga crítica del nivel de servicio",
         "valor": round(cap * fr.occ, 2), "limite": round(fr.carga_diseno, 2), "unidad": "pasajeros/h",
         "activa": cap * fr.occ - fr.carga_diseno < menor * fr.occ - 1e-9},
    ]
    if fr.ciclo is not None:
        filas += _filas_flota_y_ciclo(fr, n, e)
    filas += _filas_tipologias(fr, n)
    for f in filas:
        f["holgura"] = _holgura(f)
    return filas


def _filas_flota_y_ciclo(fr: _Franja, n, e) -> list[dict]:
    """Restricciones de flota disponible y duración del ciclo (solo si se conoce el ciclo)."""
    veh = e["vehiculos"]
    # la flota manda si ningún bus/h adicional (de cualquier tipología) cabe en ella
    con_uno_mas = min((fr.vehiculos([x + (1 if j == i else 0) for j, x in enumerate(n)]) for i in range(len(n))),
                      default=veh)
    return [{"nombre": "flota_disponible", "descripcion": "Vehículos requeridos (Σ ceil(ciclo × n_t / 60)) "
             "<= flota disponible", "valor": veh, "limite": fr.flota, "unidad": "vehículos",
             "activa": fr.flota is not None and con_uno_mas > fr.flota + EPS},
            {"nombre": "duracion_ciclo",
             "descripcion": "Duración del ciclo: cada salida ocupa un bus un ciclo completo",
             "valor": round(fr.ciclo, 2), "limite": None, "unidad": "min", "activa": True}]


def _filas_tipologias(fr: _Franja, n) -> list[dict]:
    """Restricción de flota de cada tipología con vehículos disponibles conocidos."""
    return [{"nombre": f"flota_{t['codigo']}", "descripcion": f"Buses/h de {t['nombre']} <= vehículos "
             f"disponibles × 60 / ciclo", "valor": x, "limite": cota, "unidad": "buses/h",
             "activa": 0 < cota <= x and cota < fr.k_hi}
            for t, x, cota in zip(fr.tipos, n, fr.cotas, strict=True) if t.get("disponibles") is not None]


def _holgura(f: dict):
    """Holgura de una restricción: cuánto falta para el límite (None si no hay valor o límite numérico)."""
    if not (isinstance(f["valor"], (int, float)) and isinstance(f["limite"], (int, float))):
        return None
    if f["nombre"] in ("headway_minimo", "nivel_servicio"):
        return round(f["valor"] - f["limite"], 2)
    return round(f["limite"] - f["valor"], 2)


def _mejor_aproximacion(fr: _Franja):
    """Mezcla ejecutable (flota, ciclo y headway) con la mayor cobertura del nivel de servicio y, entre esas, el menor
    costo: MILP relajado (déficit muy penalizado); respaldo, la enumeración exacta. None si nada es ejecutable."""
    if fr.k_lo > fr.k_hi:
        return None
    try:
        n, _estado, _seg = _resolver_milp(fr, exigir_servicio=False)
        if n is not None and fr.factible(n, exigir_servicio=False):
            return n
    except Exception:  # noqa: BLE001 - sin solver se intenta la enumeración
        log.warning("El MILP relajado falló; se usa la enumeración exacta", exc_info=True)
    try:
        r = _enumerar(fr, exigir_servicio=False, maximizar_cobertura=True, limite=200_000)
    except RuntimeError:
        return None
    return r[0] if r else None


def _motivo_flota(fr: _Franja, aprox=None) -> str | None:
    """Parte de _diagnostico sobre la flota: no alcanza ni para el headway máximo, o la mejor aproximación no cubre la
    carga del nivel de servicio. None si la flota no es la causa."""
    minimo_veh = int(math.ceil(fr.ciclo * fr.k_lo / 60.0 - EPS))
    if minimo_veh > fr.flota + EPS:
        return (f"La flota disponible ({_f(fr.flota, 0)} vehículos) no alcanza ni para el headway máximo: "
                f"{fr.k_lo} buses/h con un ciclo de {_f(fr.ciclo)} min requieren {minimo_veh} vehículos.")
    if aprox is None:
        return None
    cap = fr.evaluar(aprox)["capacidad_ofrecida"]
    if cap * fr.occ < fr.carga_diseno - 1e-7:
        return (f"La flota disponible ({_f(fr.flota, 0)} vehículos, ciclo de {_f(fr.ciclo)} min) solo sostiene "
                f"{_f(cap * fr.occ, 0)} pasajeros/h de capacidad efectiva y la carga del nivel de servicio es "
                f"{_f(fr.carga_diseno, 0)} ({_f(100 * cap * fr.occ / fr.carga_diseno, 1)} % de cobertura).")
    return None


def _diagnostico(fr: _Franja, aprox=None) -> list[str]:
    """Por qué no hay solución: qué restricciones chocan, con cifras (§18 «Recomendación inviable»)."""
    motivos = []
    if fr.k_lo > fr.k_hi:
        desde = _f(60.0 / fr.k_hi if fr.k_hi else 0, 2)
        motivos.append(f"No hay un número entero de buses por hora con headway entre {desde} y "
                       f"{_f(60.0 / fr.k_lo, 2)} min: los límites de headway no admiten ninguna frecuencia.")
        return motivos
    cap_max_headway = fr.k_hi * max(fr.caps)
    requerida = fr.carga_diseno / fr.occ
    if cap_max_headway * fr.occ < fr.carga_diseno - 1e-7:
        motivos.append(
            f"Ni con el headway mínimo ({fr.k_hi} buses/h) y la tipología más grande ({_f(max(fr.caps), 0)} "
            f"puestos) se cubre la carga del nivel de servicio: se requieren {_f(requerida, 0)} puestos/h y el "
            f"máximo es {_f(cap_max_headway, 0)}.")
    if fr.ciclo is not None and fr.flota is not None:
        motivo = _motivo_flota(fr, aprox)
        if motivo:
            motivos.append(motivo)
    if not motivos:
        motivos.append("Las restricciones de headway, capacidad y flota no tienen solución común con estos datos.")
    return motivos


def optimizar(ruta, hora, demanda_hora, demanda_p90=None, demanda_p10=None, *, capacidad=50,
              ocupacion_objetivo=0.85, ocupacion_critica=0.90, tiempo_ciclo_min=None, flota_disponible=None,
              headway_min=2.0, headway_max=10.0, frecuencia_actual_min=None, factor_carga=None, km_ciclo=None,
              cv_intervalos=None, parametros=None, tipologias=None, verificar=False):
    """Recomendación con la función objetivo de §10.2 (MILP de la franja), la línea base de §10.3 al lado y la
    explicación (restricciones activas, límites que mandan, por qué k y no k ± 1).

    parametros: salida de parametros_objetivo() o un dict {nombre: valor}; None = valores del código.
    tipologias: lista de tipologias_ruta() (con `disponibles`) para la asignación de capacidad de §10.1; None o [] =
      una sola tipología de `capacidad` puestos.
    Las claves de recomendar() se conservan (buses_hora, headway_min, vehiculos_requeridos, viable, motivo, ...). Si la
    franja es inviable sale viable=False con el motivo; buses_hora, headway_min y vehiculos_requeridos llevan la mejor
    aproximación EJECUTABLE (respeta flota, ciclo y headway, no el nivel de servicio), repetida y rotulada en
    «mejor_aproximacion», o None si ni eso existe. El bloque §12.3 de POST /predictions/run no la presenta como
    recomendación (cifras en None y viable=false).
    Al lado van dos líneas base de §10.3, cada una con su nombre: la literal (factor 1, demanda puntual) y la ajustada
    (carga crítica = factor de carga × P90).
    """
    comunes = dict(capacidad=capacidad, ocupacion_objetivo=ocupacion_objetivo, tiempo_ciclo_min=tiempo_ciclo_min,
                   flota_disponible=flota_disponible, headway_min=headway_min, headway_max=headway_max,
                   frecuencia_actual_min=frecuencia_actual_min)
    base = recomendar(ruta, hora, demanda_hora, demanda_p90=demanda_p90, factor_carga=factor_carga, **comunes)
    literal = recomendar(ruta, hora, demanda_hora, demanda_p90=None, factor_carga=1.0, **comunes)
    extra = _entradas_10_2(ruta, base, demanda_p10, ocupacion_critica, km_ciclo, cv_intervalos)
    efectivos = _efectivos_objetivo(parametros)
    fr, usa_tipologias, criterio = _franja_de(base, extra, efectivos, tipologias, capacidad)
    mezcla, solver = _resolver_franja(fr, verificar)
    objetivo = _objetivo_explicito(efectivos, extra, base)
    salida = {"ruta": ruta, "hora": hora, "metodo": "funcion_objetivo_10_2", "solver": solver, "objetivo": objetivo,
              "demanda": _demanda_info(fr, base, extra, criterio),
              "linea_base_10_3": dict({k: base[k] for k in CAMPOS_LINEA_BASE}, nombre=NOMBRE_BASE_AJUSTADA,
                                      factor_carga=base["factor_carga"], criterio_demanda=base["criterio_demanda"]),
              "linea_base_10_3_literal": dict({k: literal[k] for k in CAMPOS_LINEA_BASE}, nombre=NOMBRE_BASE_LITERAL,
                                              factor_carga=1.0, criterio_demanda="puntual"),
              "frecuencia_actual_min": base["frecuencia_actual_min"],
              "parametros": dict(base["parametros"], ocupacion_critica=extra["occ_crit"]),
              "demanda_hora": base["demanda_hora"], "demanda_p90": base["demanda_p90"],
              "factor_carga": base["factor_carga"], "flota_disponible": base["flota_disponible"],
              "tiempo_ciclo_min": base["tiempo_ciclo_min"]}
    contexto = {"fr": fr, "base": base, "objetivo": objetivo, "usa_tipologias": usa_tipologias, "criterio": criterio,
                "capacidad": capacidad, "literal": literal}
    if mezcla is None:
        salida.update(_salida_inviable(contexto))
    else:
        salida.update(_salida_viable(contexto, mezcla))
    return salida


CAMPOS_LINEA_BASE = ("buses_hora", "headway_min", "vehiculos_requeridos", "capacidad_efectiva", "ocupacion_esperada",
                     "viable", "motivo", "formula")
NOMBRE_BASE_LITERAL = "§10.3 literal: ceil(demanda puntual / capacidad efectiva), factor 1"
NOMBRE_BASE_AJUSTADA = ("§10.3 ajustada: ceil(carga crítica de diseño / capacidad efectiva), carga crítica = factor de "
                        "carga × P90")


def _texto_lineas_base(base: dict, literal: dict | None) -> str:
    """Las dos líneas base de §10.3, cada una con su nombre (para la explicación)."""
    def una(nombre, r):
        estado = "viable" if r["viable"] else "no viable"
        return f"{nombre}: {r['buses_hora']} buses/h, headway {_f(r['headway_min'], 2)} min ({estado})"
    partes = [una("Línea base §10.3 literal (factor 1, demanda puntual)", literal)] if literal else []
    partes.append(una(f"ajustada (factor de carga {_f(base['factor_carga'], 3)}, "
                      f"{'P90' if base['criterio_demanda'] == 'p90' else 'demanda puntual'})", base))
    return "; ".join(partes) + "."
EXPRESION_OBJETIVO = ("min α·costo_operativo + β·tiempo_espera + γ·penalización_sobreocupación + "
                      "δ·desviación_frecuencia")


def _entradas_10_2(ruta, base: dict, demanda_p10, ocupacion_critica, km_ciclo, cv_intervalos) -> dict:
    """Entradas propias de §10.2 (P10, ocupación crítica, km y CV del ciclo) validadas, con los datos de la ruta."""
    p10 = _num("demanda_p10", demanda_p10, 0, permitir_none=True)
    occ = base["parametros"]["ocupacion_objetivo"]
    occ_crit = _num("ocupacion_critica", ocupacion_critica, 0, estricto=True)
    if occ_crit < occ:
        raise ValueError(f"ocupacion_critica ({occ_crit}) no puede ser menor que ocupacion_objetivo ({occ}).")
    km = _num("km_ciclo", km_ciclo, 0, permitir_none=True)
    cv = _num("cv_intervalos", cv_intervalos, 0, permitir_none=True)
    return {"p10": p10, "occ": occ, "occ_crit": occ_crit,
            "km": km if km is not None else KM_CICLO.get(ruta, KM_CICLO_POR_OMISION),
            "cv": cv if cv is not None else CV_INTERVALOS.get(ruta, CV_POR_OMISION)}


def _efectivos_objetivo(parametros) -> dict:
    """Parámetros efectivos de la función objetivo: los del código, una salida de parametros_objetivo() (completada
    con los valores por omisión) o un dict {nombre: valor} que sobrescribe."""
    if parametros is None:
        return parametros_objetivo()
    if all(isinstance(v, dict) and "valor" in v for v in parametros.values()):
        efectivos = {n: dict(v) for n, v in parametros.items()}
        for n, (defecto, _d) in PARAMETROS_OBJETIVO.items():
            efectivos.setdefault(n, {"valor": float(defecto), "fuente": FUENTE_POR_OMISION})
        return efectivos
    return parametros_objetivo(sobrescribir=parametros)


def _tipos_franja(tipologias, capacidad) -> tuple[list[dict], bool]:
    """Tipologías con capacidad > 0; sin ellas, una sola tipología de `capacidad` puestos."""
    tipos = [dict(t) for t in (tipologias or []) if float(t.get("capacidad") or 0) > 0]
    if tipos:
        return tipos, True
    return [{"codigo": "U", "nombre": f"Bus de {_f(capacidad, 0)} puestos", "capacidad": float(capacidad),
             "disponibles": None}], False


def _franja_de(base: dict, extra: dict, efectivos: dict, tipologias, capacidad) -> tuple[_Franja, bool, str]:
    """La franja de §10.2 (demanda lognormal calibrada, límites de headway, flota y tipologías) y su criterio."""
    p = {n: float(e["valor"]) for n, e in efectivos.items()}
    demanda, factor = base["demanda_hora"], base["factor_carga"]
    mu, s, carga_diseno, criterio = _distribucion_carga(demanda, base["demanda_p90"], extra["p10"], factor,
                                                        p["nivel_servicio"])
    tipos, usa_tipologias = _tipos_franja(tipologias, capacidad)
    hmin, hmax = base["parametros"]["headway_min"], base["parametros"]["headway_max"]
    actual = base["frecuencia_actual_min"]
    fr = _Franja(demanda=demanda, pax=demanda, mu=mu, s=s, carga_diseno=carga_diseno, occ=extra["occ"],
                 occ_crit=extra["occ_crit"], ciclo=base["tiempo_ciclo_min"], km=extra["km"], cv=extra["cv"],
                 k_act=(60.0 / actual) if actual else None, flota=base["flota_disponible"], tipos=tipos, p=p,
                 k_lo=int(math.ceil(60.0 / hmax - EPS)), k_hi=int(math.floor(60.0 / hmin + EPS)))
    return fr, usa_tipologias, criterio


def _resolver_con_respaldo(fr: _Franja, solver: dict):
    """MILP de la franja; si el solver falla, la enumeración exacta. Anota el estado en `solver`."""
    try:
        mezcla, estado, seg = _resolver_milp(fr)
        solver.update(estado=estado, segundos=round(seg, 4))
        return mezcla
    except Exception as exc:  # noqa: BLE001 - sin solver se usa la enumeración exacta
        solver.update(estado=f"error del solver: {exc}", formulacion="enumeración exacta (respaldo)")
    try:
        r = _enumerar(fr)
    except RuntimeError:
        return None
    return r[0] if r else None


def _coinciden(fr: _Franja, r, mezcla) -> bool:
    """El óptimo del MILP y el de la enumeración exacta coinciden (o ninguno de los dos existe)."""
    if r is None or mezcla is None:
        return r is None and mezcla is None
    return abs(r[1]["_total"] - fr.evaluar(mezcla)["_total"]) <= 1e-6 * max(1.0, r[1]["_total"])


def _verificar_con_enumeracion(fr: _Franja, mezcla, solver: dict):
    """Compara el MILP con la enumeración exacta; si la mezcla del MILP no es factible, se usa la de la enumeración."""
    try:
        r = _enumerar(fr)
    except RuntimeError as exc:
        solver["verificacion_enumeracion"] = {"omitida": str(exc)}
        return mezcla
    solver["verificacion_enumeracion"] = {
        "optimo_enumeracion_cop": None if r is None else round(r[1]["_total"], 4),
        "optimo_milp_cop": None if mezcla is None else round(fr.evaluar(mezcla)["_total"], 4),
        "coinciden": _coinciden(fr, r, mezcla)}
    if mezcla is not None and not fr.factible(mezcla):
        return r[0] if r else None
    return mezcla


def _resolver_franja(fr: _Franja, verificar: bool):
    """(mezcla óptima o None, datos del solver). Sin un número entero de buses/h entre los límites, no se resuelve."""
    solver = {"formulacion": "MILP de la franja (PuLP/CBC)", "estado": None, "segundos": None,
              "verificacion_enumeracion": None}
    if fr.k_lo > fr.k_hi:
        return None, solver
    mezcla = _resolver_con_respaldo(fr, solver)
    if verificar or (mezcla is not None and not fr.factible(mezcla)):
        mezcla = _verificar_con_enumeracion(fr, mezcla, solver)
    return mezcla, solver


def _objetivo_explicito(efectivos: dict, extra: dict, base: dict) -> dict:
    """La función objetivo de §10.2 tal como se resolvió: expresión, pesos y parámetros con su fuente."""
    return {
        "expresion": EXPRESION_OBJETIVO,
        "pesos": {k: {"simbolo": SIMBOLO[k], "nombre": v, **efectivos[v]} for k, v in PESOS.items()},
        "parametros": {n: efectivos[n] for n in PARAMETROS_OBJETIVO if n not in PESOS.values()},
        "definiciones": {
            "costo_operativo": "buses/h × (ciclo/60 × costo_bus_hora + km_ciclo × costo_km)",
            "tiempo_espera": "pasajeros/h × (headway/2 × (1 + cv²)) / 60 × valor_tiempo_espera",
            "penalizacion_sobreocupacion": "penalidad × E[(L - capacidad × ocupación_crítica)+], L lognormal calibrada",
            "desviacion_frecuencia": "costo_cambio × |buses/h - buses/h programados|",
        },
        "datos_ruta": {"km_ciclo": extra["km"], "cv_intervalos": extra["cv"],
                       "tiempo_ciclo_min": base["tiempo_ciclo_min"], "flota_disponible": base["flota_disponible"]},
    }


def _demanda_info(fr: _Franja, base: dict, extra: dict, criterio: str) -> dict:
    demanda, factor = base["demanda_hora"], base["factor_carga"]
    return {"puntual": demanda, "p10": extra["p10"], "p90": base["demanda_p90"],
            "nivel_servicio": fr.p["nivel_servicio"], "criterio": criterio, "factor_carga": factor,
            "sigma_log": round(fr.s, 4),
            "carga_critica_mediana": round(factor * demanda, 2),
            "carga_critica_diseno": round(fr.carga_diseno, 2),
            "capacidad_requerida_puestos": round(fr.carga_diseno / fr.occ, 2)}


def _pesos_txt(fr: _Franja) -> str:
    return ", ".join(f"{SIMBOLO[k]} = {_f(fr.p[v], 2)}" for k, v in PESOS.items())


def _aproximacion_ejecutable(contexto: dict, n) -> tuple[dict, dict, float | None]:
    """Mejor aproximación ejecutable de una franja inviable: (detalle, cifras que se devuelven, cobertura)."""
    fr, occ = contexto["fr"], contexto["fr"].occ
    e = fr.evaluar(n)
    k, cap = e["buses_hora"], e["capacidad_ofrecida"]
    cobertura = (cap * occ / fr.carga_diseno) if fr.carga_diseno > 0 else None
    aprox = {"aviso": "Mejor aproximación ejecutable: respeta la flota, el ciclo y el headway, pero NO cumple "
                      "el nivel de servicio.", "buses_hora": k,
             "headway_min": round(60.0 / k, 2), "vehiculos_requeridos": e["vehiculos"],
             "capacidad_efectiva_pasajeros_h": round(cap * occ, 1),
             "cobertura_nivel_servicio": _redondear(cobertura, 4),
             "componentes_cop": e["componentes_cop"], "total_ponderado_cop": e["total_ponderado_cop"],
             "asignacion": _asignacion(fr.tipos, n, fr) if contexto["usa_tipologias"] else None}
    ocupacion = contexto["base"]["factor_carga"] * fr.demanda / cap if cap > 0 else None
    cifras = {"buses_hora": k, "headway_min": round(60.0 / k, 2), "vehiculos_requeridos": e["vehiculos"],
              "capacidad_efectiva": round(cap * occ / k, 2), "ocupacion_esperada": _redondear(ocupacion, 4)}
    return aprox, cifras, cobertura


def _tipologias_inviable(usa_tipologias: bool, aprox: dict | None) -> dict | None:
    if not usa_tipologias:
        return None
    return {"usadas": True, "asignacion": aprox["asignacion"] if aprox else None}


def _salida_inviable(contexto: dict) -> dict:
    """§18 «Recomendación inviable»: se marca no viable con su motivo. Las cifras que se devuelven son la mejor
    aproximación EJECUTABLE (respeta flota, ciclo y headway; no alcanza el nivel de servicio), nunca una cifra forzada
    que viole una restricción dura. Si ni eso existe, van en None."""
    fr, base = contexto["fr"], contexto["base"]
    n = _mejor_aproximacion(fr)
    motivos = _diagnostico(fr, n)
    aprox = None
    cifras = {"buses_hora": None, "headway_min": None, "vehiculos_requeridos": None,
              "capacidad_efectiva": round(contexto["capacidad"] * fr.occ, 2), "ocupacion_esperada": None}
    if n is not None:
        aprox, cifras, cobertura = _aproximacion_ejecutable(contexto, n)
        if cobertura is not None:
            motivos.append(f"Se informa la mejor aproximación ejecutable: {aprox['buses_hora']} buses/h cada "
                           f"{_f(60.0 / aprox['buses_hora'], 2)} min, que cubre el {_f(100 * cobertura, 1)} % de la "
                           f"carga del nivel de servicio.")
    return cifras | {
        "viable": False, "motivo": " ".join(motivos), "diferencia_min": None, "cambio": None,
        "restricciones": [], "limites_activos": [], "mejor_aproximacion": aprox,
        "tipologias": _tipologias_inviable(contexto["usa_tipologias"], aprox),
        "formula": (f"§10.2 {contexto['objetivo']['expresion']} ({_pesos_txt(fr)}): sin solución que cumpla todas las "
                    f"restricciones. " + " ".join(motivos)),
        "explicacion": ["No viable: " + m for m in motivos] + [_texto_lineas_base(base, contexto.get("literal"))],
    }


def _formula_10_2(contexto: dict, mezcla, e: dict) -> str:
    """Cálculo de §10.2 escrito con las cifras de la solución, seguido de la línea base de §10.3."""
    fr, base = contexto["fr"], contexto["base"]
    k = e["buses_hora"]
    comp = e["componentes_cop"]
    mezcla_txt = ""
    if contexto["usa_tipologias"]:
        mezcla_txt = " (" + " + ".join(f"{x} × {t['codigo']} {_f(t['capacidad'], 0)} puestos"
                                       for t, x in zip(fr.tipos, mezcla, strict=True) if x) + ")"
    vehiculos_txt = f", vehículos {e['vehiculos']}" if e["vehiculos"] is not None else ""
    return (f"§10.2 {contexto['objetivo']['expresion']} con {_pesos_txt(fr)}; nivel de servicio "
            f"{_f(fr.p['nivel_servicio'], 2)} -> carga de diseño {_f(fr.carga_diseno)} pas/h ({contexto['criterio']}); "
            f"óptimo: {k} buses/h{mezcla_txt}, headway 60 / {k} = {_f(60.0 / k, 2)} min{vehiculos_txt}; costo "
            f"operativo {_f(comp['costo_operativo'], 0)} + espera {_f(comp['tiempo_espera'], 0)} + sobreocupación "
            f"{_f(comp['sobreocupacion'], 0)} + desviación {_f(comp['desviacion_frecuencia'], 0)} COP/h. Línea base "
            f"§10.3 ajustada: {base['formula']}")


def _salida_viable(contexto: dict, mezcla) -> dict:
    """La recomendación óptima de §10.2 con sus restricciones activas, el margen (k ± 1) y la explicación."""
    fr, base = contexto["fr"], contexto["base"]
    e = fr.evaluar(mezcla)
    k = e["buses_hora"]
    headway = 60.0 / k
    restr = _restricciones(fr, mezcla, e)
    activos = [r["nombre"] for r in restr if r["activa"] and r["nombre"] != "duracion_ciclo"]
    actual = base["frecuencia_actual_min"]
    diferencia, cambio = _cambio_frecuencia(headway, actual)
    margen = _margen(fr, mezcla, e)
    asign = _asignacion(fr.tipos, mezcla, fr) if contexto["usa_tipologias"] else None
    cap = e["capacidad_ofrecida"]
    ocupacion = base["factor_carga"] * fr.demanda / cap if cap > 0 else None
    tipologias = None
    if contexto["usa_tipologias"]:
        tipologias = {"usadas": True, "fuente": "app/servicios/tipologias_flota.json (flota_sobusa.csv, sin placas)",
                      "asignacion": asign}
    return {
        "buses_hora": k, "headway_min": round(headway, 2), "vehiculos_requeridos": e["vehiculos"],
        "capacidad_efectiva": round(cap * fr.occ / k, 2), "ocupacion_esperada": _redondear(ocupacion, 4),
        "viable": True, "motivo": None, "diferencia_min": diferencia, "cambio": cambio,
        "buses_hora_actual": round(fr.k_act, 2) if fr.k_act else None,
        "capacidad_ofrecida": cap, "espera_media_min": e["espera_media_min"],
        "sobrecarga_esperada_pax": e["sobrecarga_esperada_pax"], "componentes_cop": e["componentes_cop"],
        "costo_total_ponderado_cop": e["total_ponderado_cop"], "restricciones": restr, "limites_activos": activos,
        "margen": margen, "mejor_aproximacion": None, "tipologias": tipologias,
        "formula": _formula_10_2(contexto, mezcla, e),
        "explicacion": _explicar(fr, e, activos, margen, base, asign, actual, contexto["criterio"])
        + [_texto_lineas_base(base, contexto.get("literal"))],
    }


def _asignacion(tipos, n, fr):
    filas = []
    for t, x, cota in zip(tipos, n, fr.cotas, strict=True):
        filas.append({"codigo": t["codigo"], "nombre": t["nombre"], "capacidad": int(t["capacidad"]),
                      "buses_hora": int(x),
                      "vehiculos": int(math.ceil(fr.ciclo * x / 60.0 - EPS)) if fr.ciclo is not None else None,
                      "disponibles": t.get("disponibles"), "maximo_buses_hora": cota})
    return filas


def _margen(fr: _Franja, n, e):
    """Por qué k y no k ± 1: cambio del objetivo al quitar o añadir un bus (el de menor o mayor capacidad posible)."""
    salida = {}
    for nombre, paso in (("un_bus_menos", -1), ("un_bus_mas", 1)):
        mejor = None
        for i in range(len(n)):
            m = list(n)
            m[i] += paso
            if m[i] < 0 or not fr.factible(m):
                continue
            em = fr.evaluar(m)
            if mejor is None or em["_total"] < mejor["_total"]:
                mejor = em
        if mejor is None:
            salida[nombre] = {"factible": False}
            continue
        delta = {c: round(mejor["componentes_cop"][c] - e["componentes_cop"][c], 2) for c in e["componentes_cop"]}
        salida[nombre] = {"factible": True, "buses_hora": mejor["buses_hora"],
                          "delta_componentes_cop": delta,
                          "delta_total_ponderado_cop": round(mejor["total_ponderado_cop"]
                                                             - e["total_ponderado_cop"], 2)}
    return salida


NOMBRES_LIMITES = {"headway_minimo": "el headway mínimo", "headway_maximo": "la espera máxima (headway máximo)",
                   "nivel_servicio": "la capacidad del nivel de servicio", "flota_disponible": "la flota disponible"}


def _texto_limites(fr: _Franja, activos) -> str:
    """Qué restricciones mandan en la solución, en palabras."""
    if not activos:
        return "Ninguna restricción está activa: la frecuencia la fija el equilibrio de costos de §10.2."
    nombres = dict(NOMBRES_LIMITES)
    nombres.update({f"flota_{t['codigo']}": f"la flota de {t['nombre']} ({t['codigo']})" for t in fr.tipos})
    return "Límites que mandan: " + ", ".join(nombres.get(a, a.replace("_", " ")) for a in activos) + "."


def _textos_margen(margen: dict, activos) -> list[str]:
    """Por qué k y no k ± 1, en palabras."""
    textos = []
    menos, mas = margen.get("un_bus_menos", {}), margen.get("un_bus_mas", {})
    if mas.get("factible"):
        d = mas["delta_componentes_cop"]
        textos.append(f"Un bus más por hora costaría {_f(d['costo_operativo'], 0)} COP/h de operación y cambiaría "
                      f"la espera en {_f(d['tiempo_espera'], 0)} y la sobreocupación en "
                      f"{_f(d['sobreocupacion'], 0)} COP/h: el objetivo sube "
                      f"{_f(mas['delta_total_ponderado_cop'], 0)} COP/h.")
    if menos.get("factible"):
        textos.append(f"Un bus menos cambiaría el objetivo en {_f(menos['delta_total_ponderado_cop'], 0)} COP/h.")
    elif "nivel_servicio" in activos:
        textos.append("Un bus menos no es factible: violaría el nivel de servicio.")
    elif "headway_maximo" in activos:
        textos.append("Un bus menos no es factible: violaría la espera máxima.")
    return textos


def _razon_frente_a_linea_base(e: dict, base: dict, asign) -> str:
    """Por qué la recomendación de §10.2 difiere de la línea base de §10.3."""
    k = e["buses_hora"]
    promedio = e["capacidad_ofrecida"] / k
    nominal = base["parametros"]["capacidad"] if "parametros" in base else None
    if asign and nominal and k < base["buses_hora"] and promedio > nominal + EPS:
        return (f"la mezcla de tipologías ofrece {_f(promedio, 1)} puestos por bus en promedio frente a los "
                f"{_f(nominal, 0)} de la línea base")
    if k > base["buses_hora"]:
        return ("el equilibrio de costos de §10.2 (espera y sobreocupación frente al costo operativo) justifica "
                "más buses que el mínimo de capacidad")
    return "el nivel de servicio y los costos de §10.2 se cumplen con menos buses"


def _explicar(fr, e, activos, margen, base, asign, actual, criterio):
    """Explicación en lenguaje claro: la recomendación, la demanda de diseño, los límites que mandan, el margen,
    la asignación de capacidad y la comparación con lo programado y con la línea base."""
    k = e["buses_hora"]
    vehiculos_txt = "."
    if e["vehiculos"] is not None:
        vehiculos_txt = f" con {e['vehiculos']} vehículos en el ciclo de {_f(fr.ciclo)} min."
    textos = [f"Se recomiendan {k} buses/h (un despacho cada {_f(60.0 / k, 2)} min)" + vehiculos_txt]
    textos.append(f"Demanda de diseño: {_f(fr.carga_diseno)} pasajeros en el punto de carga máxima ({criterio}, nivel "
                  f"de servicio {_f(fr.p['nivel_servicio'] * 100, 0)} %); capacidad efectiva ofrecida "
                  f"{_f(e['capacidad_ofrecida'] * fr.occ)}.")
    textos.append(_texto_limites(fr, activos))
    textos += _textos_margen(margen, activos)
    if asign:
        partes = [f"{a['buses_hora']} × {a['nombre']} ({a['capacidad']} puestos)" for a in asign if a["buses_hora"]]
        textos.append("Asignación de capacidad sugerida: " + " + ".join(partes) + ".")
    if actual is not None:
        textos.append(f"Frecuencia actual (programada): cada {_f(actual, 2)} min ({_f(60.0 / actual, 1)} buses/h); "
                      f"la recomendada es cada {_f(60.0 / k, 2)} min.")
    if base["buses_hora"] != k:
        estado_base = "viable" if base["viable"] else "no viable"
        textos.append(f"La línea base §10.3 ajustada daría {base['buses_hora']} buses/h ({estado_base}); la "
                      f"diferencia: {_razon_frente_a_linea_base(e, base, asign)}.")
    return textos


def comparar_actual(r: dict, frecuencia_actual_min: float | None, capacidad: float) -> dict | None:
    """RF-008: frecuencia actual (programada) frente a la recomendada, con costos, espera y sobreocupación esperadas.

    `r` es la salida de optimizar(). La actual se evalúa con la capacidad nominal (`capacidad`) y los mismos datos de la
    franja (demanda, banda, ciclo, flota, pesos).
    """
    if not frecuencia_actual_min:
        return None
    pesos = {v["nombre"]: float(v["valor"]) for v in r["objetivo"]["pesos"].values()}
    p = {**{n: float(e["valor"]) for n, e in r["objetivo"]["parametros"].items()}, **pesos}
    dem = r["demanda"]
    mu = None if dem["carga_critica_mediana"] <= 0 else math.log(dem["carga_critica_mediana"])
    occ, occ_crit = r["parametros"]["ocupacion_objetivo"], r["parametros"]["ocupacion_critica"]
    datos = r["objetivo"]["datos_ruta"]
    k_act = 60.0 / float(frecuencia_actual_min)
    fr = _Franja(demanda=dem["puntual"], pax=dem["puntual"], mu=mu, s=dem["sigma_log"],
                 carga_diseno=dem["carga_critica_diseno"], occ=occ, occ_crit=occ_crit, ciclo=datos["tiempo_ciclo_min"],
                 km=datos["km_ciclo"], cv=datos["cv_intervalos"], k_act=k_act, flota=datos["flota_disponible"],
                 tipos=[{"codigo": "U", "capacidad": float(capacidad), "disponibles": None}], p=p, k_lo=0, k_hi=10**6)
    cap = k_act * float(capacidad)
    op = k_act * fr.costo_salida
    esp = fr.espera_min(k_act)
    espera = fr.pax * esp / 60.0 * p["valor_tiempo_espera_cop_h"]
    sobre_pax = _sobrecarga(mu, dem["sigma_log"], cap * occ_crit)
    a, b, g, _ = fr.pesos()                  # la desviación no se cuenta en la frecuencia actual
    total = a * op + b * espera + g * p["penalidad_sobreocupacion_cop"] * sobre_pax
    vehiculos = int(math.ceil(datos["tiempo_ciclo_min"] * k_act / 60.0 - EPS)) if datos["tiempo_ciclo_min"] else None
    actual = {
        "rotulo": "frecuencia actual (programada)", "frecuencia_min": round(float(frecuencia_actual_min), 2),
        "buses_hora": round(k_act, 2), "vehiculos_requeridos": vehiculos, "capacidad_ofrecida": round(cap, 1),
        "ocupacion_esperada": round(r["factor_carga"] * dem["puntual"] / cap, 4) if cap > 0 else None,
        "cumple_nivel_servicio": cap * occ >= dem["carga_critica_diseno"] - 1e-7,
        "cabe_en_la_flota": (vehiculos <= datos["flota_disponible"]) if vehiculos is not None
        and datos["flota_disponible"] is not None else None,
        "espera_media_min": round(esp, 3), "sobrecarga_esperada_pax": round(sobre_pax, 3),
        "componentes_cop": {"costo_operativo": round(op, 2), "tiempo_espera": round(espera, 2),
                            "sobreocupacion": round(p["penalidad_sobreocupacion_cop"] * sobre_pax, 2),
                            "desviacion_frecuencia": 0.0},
        "total_ponderado_cop": round(total, 2),
    }
    if not r.get("viable"):
        return {"actual": actual, "recomendada": None,
                "conclusion": "La recomendada no es viable; la actual se muestra como referencia."}
    rec = {"frecuencia_min": r["headway_min"], "buses_hora": r["buses_hora"],
           "vehiculos_requeridos": r["vehiculos_requeridos"], "capacidad_ofrecida": r["capacidad_ofrecida"],
           "ocupacion_esperada": r["ocupacion_esperada"], "cumple_nivel_servicio": True, "cabe_en_la_flota": True,
           "espera_media_min": r["espera_media_min"], "sobrecarga_esperada_pax": r["sobrecarga_esperada_pax"],
           "componentes_cop": r["componentes_cop"], "total_ponderado_cop": r["costo_total_ponderado_cop"]}
    delta = {"buses_hora": round(rec["buses_hora"] - actual["buses_hora"], 2),
             "espera_media_min": round(rec["espera_media_min"] - actual["espera_media_min"], 3),
             "sobrecarga_esperada_pax": round(rec["sobrecarga_esperada_pax"] - actual["sobrecarga_esperada_pax"], 3),
             "costo_operativo_cop": round(rec["componentes_cop"]["costo_operativo"]
                                          - actual["componentes_cop"]["costo_operativo"], 2),
             "total_ponderado_cop": round(rec["total_ponderado_cop"] - actual["total_ponderado_cop"], 2)}
    if vehiculos is not None and rec["vehiculos_requeridos"] is not None:
        delta["vehiculos_requeridos"] = rec["vehiculos_requeridos"] - vehiculos
    partes = []
    if not actual["cumple_nivel_servicio"]:
        partes.append("la actual no cubre la carga del nivel de servicio")
    if actual["cabe_en_la_flota"] is False:
        partes.append("la actual no cabe en la flota disponible")
    partes.append(f"cambio de {_f(delta['buses_hora'], 1)} buses/h, espera {_f(delta['espera_media_min'], 2)} min, "
                  f"costo ponderado {_f(delta['total_ponderado_cop'], 0)} COP/h (la desviación no se cuenta en la "
                  f"actual)")
    return {"actual": actual, "recomendada": rec, "diferencia": delta, "conclusion": "; ".join(partes) + "."}


ESCENARIO_CAMPOS = ("factor_demanda", "pesos", "nivel_servicio", "ocupacion_objetivo", "flota_disponible", "capacidad",
                    "tiempo_ciclo_min", "headway_min", "headway_max")


def que_pasa_si(kwargs: dict, escenario: dict, base: dict | None = None) -> dict:
    """RF-008: el mismo cálculo con la demanda, los pesos u otras restricciones cambiadas; diferencias frente a la
    base. `kwargs` son los argumentos de optimizar() de la base."""
    kw = dict(kwargs)
    _escalar_demanda(kw, escenario.get("factor_demanda"))
    sobrescribir = _pesos_del_escenario(escenario)
    if sobrescribir:
        actuales = _valores_parametros(kw.get("parametros"))
        actuales.update({PESOS.get(k, k): v for k, v in sobrescribir.items()})
        kw["parametros"] = parametros_objetivo(sobrescribir=actuales)
    for campo in CAMPOS_RESTRICCION_ESCENARIO:
        if escenario.get(campo) is not None:
            kw[campo] = escenario[campo]
    if escenario.get("capacidad") is not None and kw.get("tipologias"):
        kw["tipologias"] = None             # una capacidad explícita reemplaza las tipologías
    r = optimizar(**kw)
    base = base or optimizar(**kwargs)
    dif = _diferencia_frente_a_base(r, base) if r.get("viable") and base.get("viable") else None
    return {"escenario": {k: escenario[k] for k in ESCENARIO_CAMPOS if escenario.get(k) is not None},
            "resultado": _resumen(r), "diferencia_frente_a_base": dif,
            "explicacion": r.get("explicacion"), "limites_activos": r.get("limites_activos")}


CAMPOS_RESTRICCION_ESCENARIO = ("ocupacion_objetivo", "flota_disponible", "capacidad", "tiempo_ciclo_min",
                                "headway_min", "headway_max")


def _escalar_demanda(kw: dict, factor_demanda) -> None:
    """Multiplica la demanda puntual y la banda (P10, P90) por el factor de demanda del escenario."""
    if factor_demanda is None:
        return
    fd = _num("factor_demanda", factor_demanda, 0)
    for campo in ("demanda_hora", "demanda_p90", "demanda_p10"):
        if kw.get(campo) is not None:
            kw[campo] = float(kw[campo]) * fd


def _pesos_del_escenario(escenario: dict) -> dict:
    """Pesos y nivel de servicio que el escenario cambia."""
    sobrescribir = {}
    if escenario.get("pesos"):
        sobrescribir.update(escenario["pesos"])
    if escenario.get("nivel_servicio") is not None:
        sobrescribir["nivel_servicio"] = escenario["nivel_servicio"]
    return sobrescribir


def _valores_parametros(params) -> dict:
    """{nombre: valor} de los parámetros de la base, vengan como salida de parametros_objetivo() o como valores."""
    if params and all(isinstance(v, dict) for v in params.values()):
        return {n: e["valor"] for n, e in params.items()}
    return dict(params or {})


def _diferencia_frente_a_base(r: dict, base: dict) -> dict:
    """Diferencias del escenario frente a la base (las dos viables)."""
    vehiculos = None
    if r["vehiculos_requeridos"] is not None and base["vehiculos_requeridos"] is not None:
        vehiculos = r["vehiculos_requeridos"] - base["vehiculos_requeridos"]
    return {"buses_hora": r["buses_hora"] - base["buses_hora"],
            "headway_min": round(r["headway_min"] - base["headway_min"], 2),
            "vehiculos_requeridos": vehiculos,
            "total_ponderado_cop": round(r["costo_total_ponderado_cop"] - base["costo_total_ponderado_cop"], 2)}


def _resumen(r: dict) -> dict:
    return {k: r.get(k) for k in ("buses_hora", "headway_min", "vehiculos_requeridos", "ocupacion_esperada", "viable",
                                  "motivo", "costo_total_ponderado_cop", "limites_activos")} | {
        "asignacion": (r.get("tipologias") or {}).get("asignacion")}


VARIACIONES_SENSIBILIDAD = (
    [("peso_" + n, v) for n in ("costo_operativo", "tiempo_espera", "sobreocupacion", "desviacion_frecuencia")
     for v in (0.0, 0.5, 2.0, 5.0)]
    + [("nivel_servicio", v) for v in (0.80, 0.95, 0.99)]
    + [("factor_demanda", v) for v in (0.8, 1.2, 1.5)]
    + [("ocupacion_objetivo", v) for v in (0.75,)]
)


def sensibilidad(kwargs: dict, variaciones=VARIACIONES_SENSIBILIDAD) -> dict:
    """Análisis de sensibilidad (§10.3): cada variación cambia UN parámetro (los pesos se multiplican por el valor;
    nivel de servicio, factor de demanda y ocupación objetivo toman el valor) y se resuelve de nuevo."""
    base = optimizar(**kwargs)
    params = kwargs.get("parametros")
    vigentes = (parametros_objetivo(sobrescribir={n: e["valor"] for n, e in params.items()})
                if params and all(isinstance(v, dict) for v in params.values())
                else parametros_objetivo(sobrescribir=params))
    filas = []
    for nombre, valor in variaciones:
        if nombre.startswith("peso_"):
            esc = {"pesos": {nombre: vigentes[nombre]["valor"] * valor}}
            etiqueta = f"{nombre} × {_f(valor, 1)}"
        elif nombre == "factor_demanda":
            esc = {"factor_demanda": valor}
            etiqueta = f"demanda × {_f(valor, 2)}"
        else:
            esc = {nombre: valor}
            etiqueta = f"{nombre} = {_f(valor, 2)}"
        try:
            r = que_pasa_si(kwargs, esc, base)
            fila = {"variacion": etiqueta, "parametro": nombre, "valor": valor, **r["resultado"],
                    "cambia_la_recomendacion": (r["resultado"]["buses_hora"] != base.get("buses_hora")
                                                or r["resultado"]["viable"] != base.get("viable"))}
        except ValueError as exc:
            fila = {"variacion": etiqueta, "parametro": nombre, "valor": valor, "error": str(exc)}
        filas.append(fila)
    cambian = sum(1 for f in filas if f.get("cambia_la_recomendacion"))
    return {"base": _resumen(base), "variaciones": filas,
            "resumen": f"{cambian} de {len(filas)} variaciones cambian los buses/h o la viabilidad de la base."}


CAMPOS_SOLICITUD = ("capacidad", "ocupacion_objetivo", "tiempo_ciclo_min", "flota_disponible", "headway_min",
                    "headway_max", "frecuencia_actual_min", "ocupacion_critica")


def para_guardar(r: dict) -> dict:
    """Copia de la salida para recommendation.detalle: la sensibilidad se guarda resumida (la exportación XLSX pone el
    JSON en una celda y Excel admite 32.767 caracteres por celda); la respuesta HTTP la lleva completa."""
    g = dict(r)
    s = g.get("sensibilidad")
    if s:
        g["sensibilidad"] = {"resumen": s.get("resumen"), "base": s.get("base"), "variaciones": [
            {k: v.get(k) for k in ("variacion", "buses_hora", "headway_min", "viable", "cambia_la_recomendacion")}
            for v in s.get("variaciones") or []]}
    return g


AJUSTE_LOCAL = "ajuste_local"


def marcar_sobreoferta(r: dict, umbrales: dict | None) -> None:
    """§5.1 «ocupación objetivo 65 % a 85 %»: el 85 % dimensiona la capacidad efectiva y el 65 %
    (ocupacion_objetivo_min) marca la sobreoferta. Si la recomendación viable deja la ocupación esperada (punto de carga
    máxima, demanda puntual) por debajo del mínimo, r lleva sobreoferta=True con su motivo, una fila informativa en
    restricciones (no es una restricción dura del MILP) y una frase en la explicación."""
    minimo = float((umbrales or {}).get("ocupacion_objetivo_min", 0.65))
    occ = r.get("ocupacion_esperada") if r.get("viable") else None
    r["ocupacion_objetivo_min"] = minimo
    if occ is None:
        r["sobreoferta"], r["motivo_sobreoferta"] = (False if r.get("viable") is False else None), None
        return
    sobre = occ < minimo - 1e-9
    motivo = None
    if sobre:
        hmax = (r.get("parametros") or {}).get("headway_max")
        causa = (f"la impone la espera máxima: el headway máximo efectivo de {_f(hmax, 2)} min exige al menos "
                 f"{int(math.ceil(60.0 / hmax - EPS))} buses/h" if "headway_maximo" in (r.get("limites_activos") or [])
                 and hmax else "la causa es el dimensionamiento sobre el P90 calibrado y la mezcla de tipologías (la "
                               "ocupación se mide con la demanda puntual)")
        motivo = (f"Sobreoferta: la ocupación esperada en el punto de carga máxima es {_f(100 * occ, 1)} %, menor que "
                  f"la ocupación objetivo mínima de {_f(100 * minimo, 0)} % (§5.1); {causa}.")
        r.setdefault("explicacion", []).append(motivo)
    r["sobreoferta"], r["motivo_sobreoferta"] = sobre, motivo
    r.setdefault("restricciones", []).append({
        "nombre": "ocupacion_objetivo_minima",
        "descripcion": "Ocupación objetivo mínima (§5.1): por debajo hay sobreoferta (marca informativa, no "
                       "restricción dura)", "valor": round(occ, 4), "limite": minimo, "unidad": "fracción",
        "activa": sobre, "holgura": round(occ - minimo, 4)})


def _entradas_franja(info: dict, umbrales: dict, fecha: date | None, hora: int, solicitud: dict,
                     version: int | None = None) -> tuple[dict, dict]:
    """Entradas de optimizar() para la franja: catálogo de la ruta -> parámetros de la hora y el tipo de día (D1) ->
    factor de carga histórico -> lo que traiga la solicitud. El headway máximo es el efectivo de §5.1:
    min(headway_maximo_min, 2 × espera_max_min). Devuelve (entradas, contexto de la franja)."""
    from app.servicios.ejecucion import parametros_recomendacion

    ruta = info["ruta"]
    entradas = parametros_recomendacion(info, umbrales)
    entradas["ocupacion_critica"] = float(umbrales.get("ocupacion_critica", 0.90))
    hmax = headway_maximo_efectivo(umbrales, version)
    entradas["headway_max"] = hmax["valor"]
    ctx = contexto_franja(ruta, fecha, hora)
    ctx = dict(ctx, headway_maximo=hmax) if ctx else {"headway_maximo": hmax}
    for campo in ("tiempo_ciclo_min", "flota_disponible", "frecuencia_actual_min"):
        if ctx.get(campo) is not None:
            entradas[campo] = ctx[campo]
    carga = factor_carga_franja(ruta, fecha, hora)
    if carga is not None:
        entradas["factor_carga"] = carga["factor_carga"]
        ctx = dict(ctx, factor_carga=carga)
    for campo in CAMPOS_SOLICITUD:
        if campo in solicitud:
            entradas[campo] = solicitud[campo]
    return entradas, ctx


def _tipologias_gobernadas(ruta: str, umbrales: dict, version: int | None, flota_disponible) -> list[dict] | None:
    """Tipologías de la ruta con la flota de la franja y, si hay, la capacidad gobernada de cada una."""
    tipologias = tipologias_ruta(ruta, flota_disponible) or None
    for t in tipologias or []:
        ajuste = _capacidad_gobernada(ruta, umbrales, version, t["codigo"])
        if ajuste.get("fuente") == AJUSTE_LOCAL:
            t["capacidad"], t["capacidad_fuente"] = int(ajuste["capacidad"]), ajuste.get("clave") or AJUSTE_LOCAL
    return tipologias


def _capacidad_gobernada(ruta: str, umbrales: dict, version: int | None, tipologia: str | None = None) -> dict:
    """Capacidad gobernada del catálogo (catalogos.capacidad_vigente): ajuste local de capacidad versionado en
    threshold_config (prefijo capacidad_override). Vacío si el módulo o la ruta no están; nunca impide recomendar."""
    try:
        from app.servicios import catalogos

        cv = catalogos.capacidad_vigente(ruta, tipologia, umbrales=umbrales or {}, umbrales_version=version)
    except Exception:  # noqa: BLE001 - sin catálogo gobernado rige la capacidad del catálogo o de la flota
        return {}
    return {k: cv.get(k) for k in ("capacidad", "fuente", "clave", "tipologia", "umbrales_version")}


def recomendacion_franja(info: dict, umbrales: dict, version_umbrales: int | None, *, hora: int, fecha: date | None,
                         demanda_hora: float, demanda_p90: float | None = None, demanda_p10: float | None = None,
                         solicitud: dict | None = None, pesos: dict | None = None, nivel_servicio: float | None = None,
                         usar_tipologias: bool = True, escenario: dict | None = None,
                         incluir_sensibilidad: bool = False) -> tuple[dict, dict]:
    """Recomendación de §10.2 de una franja con todas sus fuentes, en orden de prioridad:
    catálogo de la ruta -> parámetros de la hora y el tipo de día (D1) -> umbrales vigentes (threshold_config, con los
    pesos versionados) -> lo que traiga la solicitud. Devuelve (resultado de optimizar() con la comparación con la
    frecuencia actual, el escenario y la sensibilidad si se piden; entradas efectivas para la trazabilidad)."""
    ruta = info["ruta"]
    solicitud = {k: v for k, v in (solicitud or {}).items() if v is not None}
    entradas, ctx = _entradas_franja(info, umbrales, fecha, hora, solicitud, version_umbrales)
    sobrescribir = dict(pesos or {})
    if nivel_servicio is not None:
        sobrescribir["nivel_servicio"] = nivel_servicio
    parametros = parametros_objetivo(umbrales, version_umbrales, sobrescribir=sobrescribir)
    # capacidad gobernada (ajuste local versionado del catálogo): ruta completa y, si hay, por tipología
    gobernada = _capacidad_gobernada(ruta, umbrales, version_umbrales)
    if gobernada.get("fuente") == AJUSTE_LOCAL and "capacidad" not in solicitud:
        entradas["capacidad"] = int(gobernada["capacidad"])
    tipologias = None
    if usar_tipologias and "capacidad" not in solicitud:
        tipologias = _tipologias_gobernadas(ruta, umbrales, version_umbrales, entradas.get("flota_disponible"))
    kwargs = dict(ruta=ruta, hora=hora, demanda_hora=demanda_hora, demanda_p90=demanda_p90, demanda_p10=demanda_p10,
                  parametros=parametros, tipologias=tipologias, **entradas)
    r = optimizar(**kwargs)
    marcar_sobreoferta(r, umbrales)
    r["contexto_franja"] = ctx or None
    r["capacidad_gobernada"] = gobernada or None
    r["comparacion_actual"] = comparar_actual(r, entradas.get("frecuencia_actual_min"), entradas["capacidad"])
    if escenario:
        r["escenario"] = que_pasa_si(kwargs, escenario, r)
    if incluir_sensibilidad:
        r["sensibilidad"] = sensibilidad(kwargs)
    trazas = dict(entradas, tipologias=[{k: t.get(k) for k in ("codigo", "capacidad", "disponibles")}
                                        for t in (tipologias or [])] or None,
                  parametros_objetivo=parametros, contexto_franja=ctx or None)
    return r, trazas
