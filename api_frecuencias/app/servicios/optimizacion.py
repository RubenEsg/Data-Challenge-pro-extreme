"""Optimización de la frecuencia (especificación v1.5, §10; RF-007 y RF-008).

Dos niveles:
1. recomendar(): las fórmulas mínimas de §10.3 para una ruta y una hora, con la incertidumbre de la demanda (se dimensiona
   con el P90 cuando se entrega), los límites de headway y la flota. Si la recomendación no es viable se marca viable=False
   con el motivo, en lugar de forzar una cifra (§10.3, último párrafo).
2. plan_dia_d5(): el MILP de D5 del proyecto (app/servicios/motor_d5, copia de EntregaFinal/dash_app/motor) para una ruta
   y una fecha de 2025: elige las salidas de cada hora (4..20) minimizando costo operativo + espera + sobrecarga esperada
   + ingreso perdido, sujeto a la flota disponible, la suavidad y los intervalos mínimo y máximo (§10.2).
"""
from __future__ import annotations

import math
from datetime import date, datetime

EPS = 1e-9

# Fracción de los abordajes de una hora que viajan a la vez en el punto de carga máxima (carga crítica / abordajes).
# Mediana 2025 de L_real / real en datos/insumos_d5_2025.parquet (horas con > 20 abordajes); coincide con la mediana de
# exp(mu) / pronóstico E1 de la lognormal de D5 (0,415 / 0,463 / 0,415). Con factor 1,0 se usa la fórmula literal de
# §10.3 sobre los abordajes, que ignora la renovación de pasajeros a lo largo de la ruta y sobredimensiona la oferta.
FACTOR_CARGA_CRITICA = {"SILENCIO": 0.410, "CRA 54": 0.453, "CL 72": 0.408}


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
    demanda = _num("demanda_hora", demanda_hora, 0)
    p90 = _num("demanda_p90", demanda_p90, 0, permitir_none=True)
    cap = _num("capacidad", capacidad, 0, estricto=True)
    occ = _num("ocupacion_objetivo", ocupacion_objetivo, 0, estricto=True)
    if occ > 1:
        raise ValueError(f"ocupacion_objetivo debe estar en (0, 1] (recibido: {occ}).")
    hmin = _num("headway_min", headway_min, 0, estricto=True)
    hmax = _num("headway_max", headway_max, 0, estricto=True)
    if hmax < hmin:
        raise ValueError(f"headway_max ({hmax}) no puede ser menor que headway_min ({hmin}).")
    if hmin > 60:
        raise ValueError(f"headway_min debe ser <= 60 min para planear buses por hora (recibido: {hmin}).")
    ciclo = _num("tiempo_ciclo_min", tiempo_ciclo_min, 0, estricto=True, permitir_none=True)
    flota = _num("flota_disponible", flota_disponible, 0, permitir_none=True)
    actual = _num("frecuencia_actual_min", frecuencia_actual_min, 0, estricto=True, permitir_none=True)
    if factor_carga is None:
        factor = FACTOR_CARGA_CRITICA.get(ruta, 1.0)
        fuente_factor = "ruta (insumos D5 2025)" if ruta in FACTOR_CARGA_CRITICA else "fórmula literal (1,0)"
    else:
        factor = _num("factor_carga", factor_carga, 0, estricto=True)
        if factor > 1:
            raise ValueError(f"factor_carga debe estar en (0, 1] (recibido: {factor}).")
        fuente_factor = "parámetro"

    cap_ef = cap * occ
    usa_p90 = p90 is not None
    demanda_diseno = factor * (max(demanda, p90) if usa_p90 else demanda)
    buses_demanda = int(math.ceil(demanda_diseno / cap_ef - EPS)) if demanda_diseno > 0 else 0
    buses_servicio = int(math.ceil(60.0 / hmax - EPS))          # mínimo para no pasar la espera máxima
    buses_max_headway = int(math.floor(60.0 / hmin + EPS))      # máximo que permite el headway mínimo
    headway_demanda = 60.0 / buses_demanda if buses_demanda > 0 else None

    motivos = []
    buses = max(buses_demanda, buses_servicio)
    if buses > buses_max_headway:
        motivos.append(
            f"La demanda de diseño ({_f(demanda_diseno)} pas/h) exige {buses_demanda} buses/h, un intervalo de "
            f"{_f(headway_demanda, 2)} min, menor que el headway mínimo permitido ({_f(hmin, 2)} min, máximo "
            f"{buses_max_headway} buses/h = {_f(buses_max_headway * cap_ef)} pas/h de capacidad efectiva).")
        buses = buses_max_headway
    headway = min(max(60.0 / buses, hmin), hmax)

    vehiculos = int(math.ceil(ciclo / headway - EPS)) if ciclo is not None else None
    buses_factible = buses
    if flota is not None and vehiculos is not None and vehiculos > flota:
        buses_flota = int(math.floor(flota * 60.0 / ciclo + EPS))
        buses_factible = min(buses, buses_flota)
        motivos.append(
            f"La flota disponible ({_f(flota, 0)} vehículos) no alcanza: con un ciclo de {_f(ciclo)} min y un headway de "
            f"{_f(headway, 2)} min se requieren {vehiculos} vehículos; la flota solo sostiene {buses_flota} buses/h.")
    headway_factible = (60.0 / buses_factible) if buses_factible > 0 else None
    if flota is not None and (headway_factible is None or headway_factible > hmax + EPS):
        motivos.append(f"Con la flota disponible ni siquiera se cumple el headway máximo ({_f(hmax, 2)} min).")
    viable = not motivos

    capacidad_ofrecida = buses * cap
    # ocupación en el punto de carga máxima con la demanda puntual (no con el P90)
    ocupacion = factor * demanda / capacidad_ofrecida if capacidad_ofrecida > 0 else None

    buses_actual = 60.0 / actual if actual is not None else None
    diferencia = round(headway - actual, 2) if actual is not None else None
    if actual is None:
        cambio = None
    elif diferencia < -0.05:
        cambio = "reducir_intervalo"
    elif diferencia > 0.05:
        cambio = "ampliar_intervalo"
    else:
        cambio = "mantener"
    ocupacion_actual = (factor * demanda / (buses_actual * cap)) if buses_actual else None

    etiqueta = "P90" if usa_p90 else "demanda"
    base_dem = max(demanda, p90) if usa_p90 else demanda
    formula = (f"capacidad_efectiva = {_f(cap, 0)} × {_f(occ, 2)} = {_f(cap_ef)}; "
               f"carga_critica = {_f(factor, 3)} × {etiqueta} {_f(base_dem)} = {_f(demanda_diseno)}; "
               f"buses_hora = max(ceil({_f(demanda_diseno)} / {_f(cap_ef)}) = {buses_demanda}, "
               f"ceil(60 / {_f(hmax, 2)}) = {buses_servicio}) = {max(buses_demanda, buses_servicio)}"
               + (f" → acotado por headway_min a {buses}" if buses != max(buses_demanda, buses_servicio) else "")
               + f"; headway = 60 / {buses} = {_f(60.0 / buses, 2)} → [{_f(hmin, 2)}, {_f(hmax, 2)}] = {_f(headway, 2)} min")
    if vehiculos is not None:
        formula += f"; vehiculos_requeridos = ceil({_f(ciclo)} / {_f(headway, 2)}) = {vehiculos}"

    return {
        "ruta": ruta,
        "hora": hora,
        "buses_hora": buses,
        "headway_min": round(headway, 2),
        "vehiculos_requeridos": vehiculos,
        "capacidad_efectiva": round(cap_ef, 2),
        "ocupacion_esperada": round(ocupacion, 4) if ocupacion is not None else None,
        "viable": viable,
        "motivo": " ".join(motivos) if motivos else None,
        "frecuencia_actual_min": actual,
        "diferencia_min": diferencia,
        "formula": formula,
        # detalle adicional (trazabilidad y escenarios, RF-008)
        "demanda_hora": demanda,
        "demanda_p90": p90,
        "demanda_diseno": demanda_diseno,
        "criterio_demanda": "p90" if usa_p90 else "puntual",
        "factor_carga": factor,
        "fuente_factor_carga": fuente_factor,
        "buses_hora_demanda": buses_demanda,
        "headway_demanda_min": round(headway_demanda, 2) if headway_demanda is not None else None,
        "buses_hora_minimo_servicio": buses_servicio,
        "buses_hora_factible": buses_factible,
        "headway_factible_min": round(headway_factible, 2) if headway_factible is not None else None,
        "capacidad_ofrecida": capacidad_ofrecida,
        "flota_disponible": flota,
        "tiempo_ciclo_min": ciclo,
        "buses_hora_actual": round(buses_actual, 2) if buses_actual is not None else None,
        "ocupacion_actual": round(ocupacion_actual, 4) if ocupacion_actual is not None else None,
        "cambio": cambio,
        "parametros": {"capacidad": cap, "ocupacion_objetivo": occ, "headway_min": hmin, "headway_max": hmax},
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


def plan_dia_d5(ruta, fecha, modelo="E12", fuente_costos=True):
    """Plan de un día con el MILP de D5 (copia en motor_d5) para `ruta` y `fecha` (2025).

    Devuelve una lista de 17 dicts (horas 4..20): hora, salidas (x_plan del MILP), headway_min (minutos operados de la
    hora / salidas; None si la hora no se opera o no tiene salidas), programar (salidas a programar descontando la tasa de
    viajes no válidos), pasajeros_previstos (pronóstico de `modelo`), minutos_operados, estado del solver y tipo de día.
    Lanza ValueError si la ruta o la fecha no tienen insumos de D5.
    """
    from .motor_d5 import comun as C
    from .motor_d5 import plan_base

    if ruta not in C.ORDEN:
        raise ValueError(f"Ruta desconocida: {ruta!r}. Rutas válidas: {', '.join(C.ORDEN)}.")
    if modelo not in plan_base.MODELOS:
        raise ValueError(f"Modelo desconocido: {modelo!r}. Válidos: {', '.join(plan_base.MODELOS)}.")
    if isinstance(fecha, str):
        fecha = date.fromisoformat(fecha[:10])
    elif isinstance(fecha, datetime):
        fecha = fecha.date()
    P = C.param_d5(fuente=fuente_costos)
    r = plan_base.plan_ruta(fecha, ruta, P, modelo=modelo)
    tb = r["tabla"]
    por_hora = {}
    for m in r["horario"]:              # salidas equiespaciadas de D5, en minutos desde medianoche
        por_hora.setdefault(int(m) // 60, []).append(f"{int(m) // 60:02d}:{int(m) % 60:02d}")
    salida = []
    for fila in tb.itertuples(index=False):
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
        })
    return salida
