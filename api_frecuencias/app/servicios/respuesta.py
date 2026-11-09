"""Respuesta explícita a la pregunta final de la especificación v1.5 (§20), con los datos históricos y recientes.

«con los datos históricos y recientes, ¿cada cuánto despachar buses para optimizar la flota y el recaudo? ¿Cuántos
pasajeros y vehículos se esperan, y qué situaciones requieren atención inmediata?»

Cómo se calcula (§7.1, procesos largos asíncronos): el pronóstico hora por hora y el MILP corren fuera de la petición
HTTP. precalcular() los ejecuta en el trabajador de la cola (ejecución de tipo «respuesta» que encola
POST /api/v1/respuesta/calcular) o al cierre del ciclo diario para el día siguiente, y guarda una foto por ruta en
ai_frecuencias.respuesta_reto. GET /api/v1/respuesta solo lee esa foto; las alertas se leen en el momento de la
consulta, porque «atención inmediata» es lo que está abierto ahora.

No hay modelado nuevo: cada cifra sale de una pieza que ya existe y que la respuesta cita en `trazabilidad.fuentes`.
- Pasajeros esperados: el modelo ACTIVO (inferencia.predecir, ventana de 60 min al inicio de cada hora, sin factor
  intradía) con su banda P10-P90 calibrada. Ese mismo pronóstico alimenta el plan, así que plan y pasajeros coinciden
  hora a hora.
- Cada cuánto despachar: el plan del día (optimizacion.plan_dia, MILP de D5 con los umbrales vigentes) frente al
  intervalo programado por ruta, tipo de día y hora (D1, parametros_operativos_hora.parquet). Viable = el solver
  terminó en óptimo, los buses en ruta no pasan la flota disponible (conteo de D5 cada 15 min), el intervalo queda
  entre el mínimo gobernado y el máximo efectivo, y la demanda no pide más salidas de las que permite el headway
  mínimo (§10.2, §18).
- Vehículos: máximo de buses en ruta a la vez con el plan (milp.fracciones_en_ruta) frente a la flota; la fórmula de
  §10.3, ceil(ciclo / headway), se informa al lado.
- Flota y recaudo: costo operativo del plan (componente «op» del MILP), vehículos-hora frente a lo programado, espera
  media y sobreocupación esperada (las fórmulas de milp.costos_por_nivel evaluadas en las dos ofertas) y recaudo =
  pasajeros esperados × tarifa neta de param_d5(fuente=True) (datos/costos_fuente.json).
- Atención inmediata: alertas «abiertas ahora» en ai_frecuencias.alert (ni cerradas ni descartadas al consultar), las
  críticas primero, y aparte las alertas detectadas en la fecha consultada.
Todos los instantes salen en America/Bogota (§8.1).
"""
from __future__ import annotations

import json
import logging
import math
import os
import statistics
from datetime import date, datetime, time, timedelta
from functools import lru_cache
from typing import Any

from sqlalchemy import case, func, or_, select, text
from sqlalchemy.orm import Session

from app.config import ESQUEMA
from app.modelos_db import Alerta, DemandaObservada, Ejecucion
from app.servicios import ejecucion as servicio

log = logging.getLogger("api_frecuencias.respuesta")
PREGUNTA = ("con los datos históricos y recientes, ¿cada cuánto despachar buses para optimizar la flota y el recaudo? "
            "¿Cuántos pasajeros y vehículos se esperan, y qué situaciones requieren atención inmediata?")
RUTAS = ("SILENCIO", "CRA 54", "CL 72")
HORAS = tuple(range(4, 21))                      # horas de salida que planifica D5 (4..20)
TIPO_TRABAJO = "respuesta"                       # tipo de la ejecución en la cola (execution_log.tipo)
ESTADOS_FINALES = ("cerrada", "descartada")
ORDEN_SEVERIDAD = {"critica": 0, "preventiva": 1, "informativa": 2}
MAX_ALERTAS = 10
ALCANCE_ABIERTAS = "abierta ahora"
ALCANCE_FECHA = "detectada en la fecha consultada"
# Franjas de las métricas del modelo (inferencia.FRANJAS) con un nombre operativo.
FRANJAS = (("madrugada (4-5 h)", 4, 5), ("pico mañana (6-8 h)", 6, 8), ("valle (9-16 h)", 9, 16),
           ("pico tarde (17-19 h)", 17, 19), ("cierre (20 h)", 20, 20))
HORAS_VALLE = range(9, 17)
NOTA_TARIFA_SIN_DATO = "tarifa no suministrada por Extreme (§19)"
TEXTO_ELASTICIDAD = ("β estimada ≈ 0,70 por observación, sin validar en campo; el plan usa 0,5 por prudencia; la "
                     "sensibilidad está en docs/evidencias/optimizacion/sensibilidad.md; el piloto la mide")
TABLA = f"{ESQUEMA}.respuesta_reto"
PISTA = "POST /api/v1/respuesta/calcular"        # la misma pista del 404 «sin_calcular» de /recommendations/plan


class SinDatos(LookupError):
    """No hay pronóstico o plan para la fecha (o no hay modelo cargable): el cálculo no se puede hacer."""


class SinCalcular(LookupError):
    """No hay foto guardada de la respuesta para la fecha con el modelo y los umbrales vigentes (404 «sin_calcular»)."""

    def __init__(self, mensaje: str, detalle: dict):
        super().__init__(mensaje)
        self.detalle = detalle


# ---------------------------------------------------------------------------------------------------- utilidades
def _f(x: float, d: int = 1) -> str:
    """Número con coma decimal y punto de miles (es-CO) para los textos."""
    return f"{x:,.{d}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def franja_de(hora: int) -> str:
    for nombre, ini, fin in FRANJAS:
        if ini <= int(hora) <= fin:
            return nombre
    return "fuera de servicio"


def instante_bogota(valor: Any) -> str | None:
    """Instante ISO-8601 con la zona de Bogotá (-05:00), §8.1."""
    inst = servicio.a_instante(valor)
    return inst.astimezone(servicio.ZONA).isoformat(timespec="seconds") if inst else None


def _ahora_bogota() -> str:
    return datetime.now(servicio.ZONA).isoformat(timespec="seconds")


def _clave_datos() -> str:
    """La caché se separa por carpeta de datos y de modelos (las pruebas usan copias temporales)."""
    return f"{os.environ.get('DATA_DIR', '')}|{os.environ.get('MODELOS_DIR', '')}"


def pronostico_plan() -> str:
    """«activo» (por omisión: el modelo activo) o «E12» (MODELO_PLAN=E12, el pronóstico precalculado de 2025, como
    opción)."""
    return "E12" if os.environ.get("MODELO_PLAN", "").strip().upper() == "E12" else "activo"


def _plan_dia_disponible():
    from app.servicios import optimizacion

    return getattr(optimizacion, "plan_dia", None)


# ---------------------------------------------------------------------------------------------------- fechas
@lru_cache(maxsize=4)
def _serie_fechas(_clave: str) -> tuple[date, date]:
    from app.servicios import datos

    fechas = datos.demanda_horaria()["fecha"]
    return min(fechas), max(fechas)


def ultima_fecha_datos(sesion: Session | None = None) -> date:
    """Último día con datos que tiene la API: la serie empaquetada y lo que el ciclo diario incorporó en
    ai_frecuencias.demanda_observada (datos recientes)."""
    ultima = _serie_fechas(_clave_datos())[1]
    if sesion is not None:
        try:
            # punto de guardado: si la consulta falla se revierte solo ella, nunca la transacción del ciclo que llama
            with sesion.begin_nested():
                en_base = sesion.scalar(select(func.max(DemandaObservada.fecha)))
        except Exception as exc:  # noqa: BLE001 - sin la tabla (base vieja) vale la serie empaquetada
            log.warning("No se pudo leer la última fecha de demanda_observada: %s", exc)
            en_base = None
        if en_base is not None and en_base > ultima:
            ultima = en_base
    return ultima


def fecha_por_omision(sesion: Session | None = None) -> date:
    """El día siguiente al último dato que tiene la API («datos recientes»): el día que hay que planear."""
    return ultima_fecha_datos(sesion) + timedelta(days=1)


def rango_calculable(sesion: Session | None = None) -> tuple[date, date]:
    """Primer y último día que se pueden pedir: desde el inicio de la serie hasta los días después del último dato
    para los que la inferencia arma variables (variables.DIAS_EXTRA). Es un filtro barato para el POST; el cálculo
    revisa después las variables de cada ruta."""
    from app.servicios import variables

    primera = _serie_fechas(_clave_datos())[0]
    return primera, ultima_fecha_datos(sesion) + timedelta(days=int(getattr(variables, "DIAS_EXTRA", 7)))


@lru_cache(maxsize=4)
def _fechas_disponibles(_clave: str, con_plan_dia: bool) -> tuple[date, ...]:
    from app.servicios import inferencia

    indice = inferencia.tabla_variables().index
    if con_plan_dia:       # el plan con el modelo activo sale para cualquier día con variables
        candidatas = sorted({f for _r, f, _h in indice})
    else:                  # respaldo: solo los días de 2025 con insumos y pronóstico E12 de D5
        from app.servicios.motor_d5 import plan_base

        candidatas = [ts.date() for ts in plan_base.fechas_disponibles()]
    return tuple(f for f in candidatas if all((r, f, h) in indice for r in RUTAS for h in (HORAS[0], HORAS[-1])))


def fechas_disponibles() -> tuple[date, ...]:
    """Días que se pueden calcular: con variables del modelo para las tres rutas (y, sin plan_dia, con insumos D5)."""
    con_plan = _plan_dia_disponible() is not None and pronostico_plan() == "activo"
    return _fechas_disponibles(_clave_datos(), con_plan)


# ---------------------------------------------------------------------------------------------------- modelo
def _candidatos_modelo(sesion: Session | None) -> list[str]:
    from app.servicios import inferencia

    candidatos = []
    if sesion is not None:
        activo = servicio.modelo_activo(sesion)
        if activo is not None:
            candidatos.append(activo.model_id)
    try:
        candidatos.append(inferencia.modelo_activo())
    except Exception as exc:  # noqa: BLE001 - sin registro en disco se intenta solo con el de la base
        log.warning("Sin registro de modelos en disco: %s", exc)
    return list(dict.fromkeys(candidatos))


def modelo_vigente(sesion: Session | None) -> dict:
    """Modelo activo (registro en PostgreSQL; si no se puede cargar, el del registro en disco) con su versión de
    variables y su fecha de corte."""
    from app.servicios import inferencia

    for mid in _candidatos_modelo(sesion):
        try:
            m = inferencia.cargar(mid)
        except Exception as exc:  # noqa: BLE001 - un modelo que no carga no responde; se prueba el siguiente
            log.warning("El modelo %s no se pudo cargar para la respuesta del reto: %s", mid, exc)
            continue
        corte = m.get("data_cutoff")
        return {"model_id": m["model_id"], "feature_version": m.get("feature_version"),
                "data_cutoff": corte.isoformat() if hasattr(corte, "isoformat") else corte}
    raise SinDatos("No hay un modelo activo que se pueda cargar para pronosticar los pasajeros")


# ---------------------------------------------------------------------------------------------------- por ruta
def _pronostico_dia(ruta: str, fecha: date, model_id: str) -> list[dict]:
    """Pasajeros esperados por hora de salida (4..20) con P10/P90 calibrados: inferencia.predecir con ventana de 60 min
    que empieza en la hora (la misma llamada del contexto observado del ciclo diario), sin factor intradía. Usa el lote
    inferencia.predecir_horas (los mismos valores en una sola llamada al modelo) si existe."""
    from app.servicios import inferencia

    inicios = [datetime(fecha.year, fecha.month, fecha.day, h, 0, tzinfo=servicio.ZONA) for h in HORAS]
    lote = getattr(inferencia, "predecir_horas", None)
    try:
        if lote is not None:
            resultados = lote(ruta, inicios, model_id, horizonte_min=60, usar_nowcast=False)
        else:
            resultados = [inferencia.predecir(ruta, i, 60, model_id=model_id, usar_nowcast=False) for i in inicios]
    except (ValueError, LookupError) as exc:
        raise SinDatos(f"Sin pronóstico para {ruta} el {fecha.isoformat()}: {exc}") from exc
    return [{"hora": h, "esperado": round(float(r["pasajeros"]), 1), "p10": round(float(r["p10"]), 1),
             "p90": round(float(r["p90"]), 1), "_calibracion": r.get("calibracion_version")}
            for h, r in zip(HORAS, resultados, strict=True)]


def _buses_en_ruta(salidas: list[float], ciclos: list[float]) -> tuple[float, float]:
    """Máximo de buses en ruta a la vez (conteo de D5 cada 15 min, milp.fracciones_en_ruta) y el instante (horas)."""
    import numpy as np

    from app.servicios.motor_d5 import milp

    fr = milp.fracciones_en_ruta(np.asarray(ciclos, float))
    en_ruta = np.asarray(salidas, float) @ fr
    j = int(np.argmax(en_ruta))
    return float(en_ruta[j]), float(milp.T_FLOTA[j])


def _espera_min(minutos: float, k: float, cv: float) -> float | None:
    """Espera media de un pasajero (min) con k salidas en `minutos` e intervalos irregulares (milp.costos_por_nivel)."""
    if k <= 0 or minutos <= 0:
        return None
    return minutos / k / 2.0 * (1.0 + cv ** 2)


def _sobreocupacion(fila, k: float, minutos: float, sin_dato: bool) -> float | None:
    """Pasajeros esperados por encima de la capacidad (lognormal de la carga crítica de D5); None sin esa carga."""
    import numpy as np

    from app.servicios.motor_d5 import milp

    mu, s, capacidad = (getattr(fila, c, None) for c in ("mu", "s", "capacidad"))
    if mu is None or s is None or capacidad is None or any(isinstance(v, float) and math.isnan(v)
                                                           for v in (mu, s, capacidad)):
        return None
    cap = k * float(capacidad)
    if cap > 0:
        return float(milp.sobrecarga_lognormal(float(mu), float(s), np.array([cap]))[0])
    if minutos > 0 and not sin_dato:
        return float(math.exp(float(mu) + float(s) ** 2 / 2))
    return 0.0


def _comparacion_oferta(tb, salidas: dict[int, float], params: dict,
                        sin_dato: frozenset[int] = frozenset()) -> dict:
    """Vehículos-hora, costo operativo, espera media y sobreocupación esperada de una oferta (salidas por hora),
    con las fórmulas del MILP de D5 (milp.costos_por_nivel) y su demanda (pax_pred, lognormal de la carga crítica).
    `sin_dato`: horas sin intervalo programado; ahí no se cuenta la carga como sobreocupación de la oferta actual."""
    vh = costo = espera_pax = pax_total = 0.0
    sobre: float | None = 0.0
    for fila in tb.itertuples(index=False):
        h = int(fila.hora)
        k = float(salidas.get(h) or 0.0)
        ciclo, km, minutos = float(fila.ciclo), float(fila.dist), float(fila.minutos)
        vh += k * ciclo / 60.0
        costo += k * ciclo / 60.0 * params["COSTO_BUS_HORA"] + k * km * params["COSTO_KM"]
        pax = max(float(fila.pax_pred), 0.0)
        e = _espera_min(minutos, k, float(fila.cv_d4))
        if e is not None and pax > 0:
            espera_pax += pax * e
            pax_total += pax
        so = _sobreocupacion(fila, k, minutos, h in sin_dato)
        sobre = None if so is None or sobre is None else sobre + so
    return {"vehiculos_hora": vh, "costo_operativo_cop": costo,
            "espera_media_min": espera_pax / pax_total if pax_total > 0 else None, "sobreocupacion_pasajeros": sobre}


COLUMNAS_OFERTA = ("hora", "ciclo", "dist", "minutos", "pax_pred", "cv_d4", "capacidad", "mu", "s")


def _insumos_del_plan(plan: dict, ruta: str, fecha: date, umbrales: dict, version_u: int | None, fuente: str):
    """Los insumos por hora con los que se resolvió el plan (mismos ciclo, km, capacidad y carga crítica lognormal),
    para evaluar con las mismas fórmulas la oferta recomendada y la programada. None si no se pueden reconstruir."""
    import pandas as pd

    from app.servicios import optimizacion

    tabla = plan.get("tabla")
    if isinstance(tabla, pd.DataFrame) and set(COLUMNAS_OFERTA) <= set(tabla.columns):
        return tabla.sort_values("hora")
    if all(set(COLUMNAS_OFERTA[1:]) - {"ciclo", "minutos", "pax_pred"} <= set(h) for h in plan["horas"]):
        return pd.DataFrame([{"hora": int(h["hora"]), "ciclo": float(h["tiempo_ciclo_min"]), "dist": float(h["dist"]),
                              "minutos": float(h.get("minutos_operados") or 0.0), "cv_d4": float(h["cv_d4"]),
                              "pax_pred": max(float(h.get("pasajeros_previstos") or 0.0), 0.0),
                              "capacidad": float(h["capacidad"]), "mu": float(h["mu"]), "s": float(h["s"])}
                             for h in plan["horas"]])
    try:
        if fuente == "E12":
            from app.servicios.motor_d5 import comun as motor_comun
            from app.servicios.motor_d5 import plan_base

            return plan_base.plan_ruta(fecha, ruta, motor_comun.param_d5(fuente=True), modelo="E12")["tabla"]
        insumos = getattr(optimizacion, "_insumos_activo", None)
        gobernados = getattr(optimizacion, "parametros_plan", None)
        if insumos is not None and gobernados is not None:
            pron = {int(h["hora"]): {"p10": float(h.get("pasajeros_p10") or 0.0),
                                     "p50": float(h.get("pasajeros_previstos") or 0.0),
                                     "p90": float(h.get("pasajeros_p90") or 0.0)} for h in plan["horas"]}
            return insumos(fecha, ruta, pron, gobernados(umbrales, version_u, True)).sort_values("hora")
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        log.info("No se reconstruyeron los insumos del plan de %s el %s: %s", ruta, fecha, exc)
    return None


def _tabla_comparacion(plan: dict, ruta: str, fecha: date, umbrales: dict | None = None,
                       version_u: int | None = None, fuente: str = "modelo_activo"):
    """Insumos por hora para comparar ofertas: los del plan (_insumos_del_plan) con su ciclo y sus minutos; si no se
    pueden reconstruir, una tabla mínima con el ciclo, los minutos y la demanda del plan (sin la carga crítica, la
    sobreocupación queda en null)."""
    import pandas as pd

    from app.servicios import optimizacion

    horas = pd.DataFrame([{"hora": int(h["hora"]), "ciclo": float(h["tiempo_ciclo_min"]),
                           "minutos": float(h.get("minutos_operados") or 0.0),
                           "pax_pred": max(float(h.get("pasajeros_previstos") or 0.0), 0.0)} for h in plan["horas"]])
    base = _insumos_del_plan(plan, ruta, fecha, umbrales or {}, version_u, fuente)
    if base is not None and set(COLUMNAS_OFERTA) <= set(base.columns) and len(base) == len(horas):
        tb = base.sort_values("hora").reset_index(drop=True)[list(COLUMNAS_OFERTA)].copy()
        if tb["hora"].tolist() == horas["hora"].tolist():
            tb["ciclo"], tb["minutos"] = horas["ciclo"].to_numpy(float), horas["minutos"].to_numpy(float)
            return tb
    horas["dist"] = optimizacion.KM_CICLO.get(ruta, optimizacion.KM_CICLO_POR_OMISION)
    horas["cv_d4"] = optimizacion.CV_INTERVALOS.get(ruta, optimizacion.CV_POR_OMISION)
    return horas


def _costos_del_plan(plan: dict, params: dict) -> dict:
    """param_d5(fuente=True) con el costo de bus-hora y de km con que se resolvió el plan (threshold_config)."""
    salida = dict(params)
    gob = plan.get("parametros") or {}
    for clave, nombre in (("COSTO_BUS_HORA", "costo_bus_hora_cop"), ("COSTO_KM", "costo_km_cop")):
        valor = servicio._num((gob.get(nombre) or {}).get("valor") if isinstance(gob.get(nombre), dict) else None)
        if valor is not None and valor > 0:
            salida[clave] = valor
    return salida


def _problemas_intervalo(h: dict, intervalo_min: float, intervalo_max: float) -> list[str]:
    """Intervalo de la hora fuera de [mínimo, máximo]. Con una sola salida no hay intervalo entre salidas dentro de la
    hora (horas de apertura o cierre parciales), así que el mínimo no aplica."""
    hw = h.get("headway_min")
    if h["salidas"] <= 0 or hw is None:
        return []
    problemas = []
    if h["salidas"] >= 2 and hw < intervalo_min - 1e-6:
        problemas.append(f"intervalo de {_f(hw, 2)} min, menor que el mínimo de {_f(intervalo_min)} min")
    if hw > intervalo_max + 0.05:
        problemas.append(f"intervalo de {_f(hw, 2)} min, mayor que el máximo de {_f(intervalo_max)} min")
    return problemas


def _problema_headway_minimo(h: dict) -> list[str]:
    """La demanda pide más salidas de las que permite el headway mínimo gobernado (§10.2): el plan programa el tope,
    que es la mejor aproximación ejecutable, y la hora se marca no viable en lugar de forzar una cifra."""
    if not h.get("limitada_por_headway_minimo"):
        return []
    minutos = float(h.get("minutos_operados") or 0.0)
    pedidas = int(h["salidas_sin_tope"])
    return [f"la demanda prevista pide {pedidas} salidas (una cada {_f(minutos / pedidas, 2)} min) y el headway "
            f"mínimo gobernado de {_f(float(h['headway_minimo_min']), 2)} min permite como máximo "
            f"{int(h['maximo_salidas_headway'])}; el plan programa {int(h['salidas'])} salidas, la mejor "
            f"aproximación ejecutable"]


def _viabilidad(h: dict, en_ruta_hora: float, flota: float, estado: str, intervalo_min: float,
                intervalo_max: float) -> tuple[bool, str]:
    """Viabilidad de la hora del plan (§10.3 último párrafo y §18 «recomendación inviable»), con el motivo."""
    problemas = []
    if str(estado) != "Optimal":
        problemas.append(f"el solver terminó en «{estado}», no en óptimo")
    if en_ruta_hora > flota + 1e-6:
        problemas.append(f"pide {_f(en_ruta_hora)} buses en ruta y la flota disponible es {_f(flota, 0)}")
    problemas += _problema_headway_minimo(h)
    problemas += _problemas_intervalo(h, intervalo_min, intervalo_max)
    if problemas:
        return False, "No viable: " + "; ".join(problemas) + "."
    if h["salidas"] <= 0:
        return True, "Hora sin salidas en el plan (sin minutos operados o sin demanda que las justifique)."
    flota_txt = f"como máximo {_f(en_ruta_hora)} buses en ruta de {_f(flota, 0)} disponibles."
    if h["salidas"] == 1:
        minutos = float(h.get("minutos_operados") or 0.0)
        return True, (f"Viable: una sola salida en {_f(minutos)} min operados (no hay intervalo entre salidas dentro "
                      f"de la hora) y {flota_txt}")
    return True, f"Viable: intervalo dentro de {_f(intervalo_min)}-{_f(intervalo_max)} min y {flota_txt}"


def resumen_por_franja(filas: list[dict]) -> list[dict]:
    """Cada cuánto despachar por franja: headway de la franja = minutos operados / salidas de la franja, recomendado y
    programado, con las horas no viables."""
    salida = []
    for nombre, ini, fin in FRANJAS:
        horas = [f for f in filas if ini <= f["hora"] <= fin]
        salidas = sum(f["buses_hora"] for f in horas)
        programadas = sum(f["buses_hora_actual"] or 0.0 for f in horas)
        minutos = sum((f["headway_min"] or 0.0) * f["buses_hora"] for f in horas)
        minutos_prog = sum((f["headway_actual_min"] or 0.0) * (f["buses_hora_actual"] or 0.0) for f in horas)
        salida.append({"franja": nombre, "salidas": salidas, "salidas_programadas": round(programadas, 1),
                       "headway_min": round(minutos / salidas, 2) if salidas else None,
                       "headway_actual_min": round(minutos_prog / programadas, 2) if programadas else None,
                       "horas_no_viables": [f["hora"] for f in horas if not f["viable"]]})
    return salida


def _resumen_despacho(filas: list[dict], plan: dict, pron: dict[int, dict]) -> dict:
    """Salidas del día, headway de la hora con más salidas (empate: más pasajeros), mediana del valle (9-16 h) y el
    resumen por franja."""
    operadas = [f for f in filas if f["buses_hora"] and f["headway_min"]]
    hora_pico = hw_pico = hw_valle = None
    if operadas:
        pico = max(operadas, key=lambda f: (f["buses_hora"], pron.get(f["hora"], {}).get("esperado") or 0.0))
        valle = [f["headway_min"] for f in operadas if f["hora"] in HORAS_VALLE]
        hw_valle = round(statistics.median(valle), 2) if valle else None
        hora_pico, hw_pico = pico["hora"], pico["headway_min"]
    return {"salidas_dia_recomendadas": int(plan["salidas_dia"]),
            "salidas_dia_programadas": plan.get("salidas_programadas_dia"),
            "headway_pico_min": hw_pico, "headway_valle_min": hw_valle, "hora_pico": hora_pico,
            "por_franja": resumen_por_franja(filas)}


def _umbral(umbrales: dict, nombre: str) -> float | None:
    valor = servicio._num((umbrales or {}).get(nombre))
    return None if valor is None or valor <= 0 else valor


def _limites_headway(params: dict, tipo_dia: str, umbrales: dict) -> tuple[float, float]:
    """Mínimo gobernado (threshold_config headway_minimo_min) o el de D5, y el máximo efectivo: el de la política por
    tipo de día de D5, acotado por headway_maximo_min y por 2 × espera_max_min (espera media = headway / 2, supuesto
    S12 de documentos/mapeo_especificacion.md)."""
    minimo = _umbral(umbrales, "headway_minimo_min") or float(params["INTERVALO_MIN"])
    maximos = params["INTERVALO_MAX"]
    maximo = float(maximos.get(tipo_dia, max(maximos.values())))
    tope_hw = _umbral(umbrales, "headway_maximo_min")
    espera = _umbral(umbrales, "espera_max_min")
    if tope_hw is not None:
        maximo = min(maximo, tope_hw)
    if espera is not None:
        maximo = min(maximo, 2.0 * espera)
    return minimo, max(minimo, maximo)


def _filas_despacho(plan: dict, limites: tuple[float, float]) -> list[dict]:
    """Una fila por hora: headway y salidas recomendadas frente a las programadas, con su viabilidad, el motivo y, si
    el plan los trae, los límites activos, la demanda de diseño y el margen."""
    import numpy as np

    from app.servicios.motor_d5 import milp

    horas = plan["horas"]
    flota = float(plan["flota_disponible"])
    fr = milp.fracciones_en_ruta(np.asarray([float(h["tiempo_ciclo_min"]) for h in horas], float))
    en_ruta = np.asarray([float(h["salidas"]) for h in horas]) @ fr     # buses en ruta en cada instante de T_FLOTA
    filas = []
    for h in horas:
        en_hora = [float(en_ruta[j]) for j, t in enumerate(milp.T_FLOTA) if h["hora"] < t <= h["hora"] + 1]
        viable, motivo = _viabilidad(h, max(en_hora, default=0.0), flota, plan["estado_solver"], *limites)
        if h.get("viable") is False and viable:          # el plan del día ya la marcó no viable con su motivo
            viable, motivo = False, h.get("motivo") or "No viable según el plan del día."
        fila = {"hora": int(h["hora"]), "franja": franja_de(h["hora"]), "headway_min": h["headway_min"],
                "buses_hora": int(h["salidas"]), "headway_actual_min": h.get("frecuencia_actual_min"),
                "buses_hora_actual": h.get("salidas_programadas"), "viable": viable, "motivo": motivo}
        for clave in ("limites_activos", "demanda_diseno", "margen"):
            if h.get(clave) is not None:
                fila[clave] = servicio.json_seguro(h[clave])
        filas.append(fila)
    return filas


def _pasajeros(pron: dict[int, dict]) -> dict:
    por_hora = [pron[h] for h in HORAS if h in pron]
    return {"dia": round(sum(p["esperado"] for p in por_hora), 1), "p10": round(sum(p["p10"] for p in por_hora), 1),
            "p90": round(sum(p["p90"] for p in por_hora), 1), "por_hora": por_hora}


NOTA_VEHICULOS = (
    "requeridos_pico = máximo de buses en ruta a la vez con el plan (conteo de D5 cada 15 min con el ciclo de cada "
    "hora); requeridos_pico_10_3 = máximo de ceil(ciclo / headway) de §10.3 en las horas completas (60 min operados), "
    "que supone que la frecuencia de la hora se mantiene un ciclo completo y por eso difiere del conteo cuando la "
    "frecuencia cambia de una hora a otra; requeridos_programados = el mismo conteo de buses en ruta con las salidas "
    "programadas hoy (D1).")


def _vehiculos(plan: dict) -> dict:
    """Vehículos requeridos en el pico (buses en ruta a la vez) frente a la flota, la cifra de §10.3 y lo programado."""
    horas = plan["horas"]
    ciclos = [float(h["tiempo_ciclo_min"]) for h in horas]
    max_rec, t_rec = _buses_en_ruta([float(h["salidas"]) for h in horas], ciclos)
    max_prog, _t = _buses_en_ruta([float(h.get("salidas_programadas") or 0.0) for h in horas], ciclos)
    completas = [int(h["vehiculos_requeridos"]) for h in horas
                 if h["salidas"] > 0 and float(h.get("minutos_operados") or 0) >= 60 - 1e-6]
    return {"requeridos_pico": int(math.ceil(max_rec - 1e-6)), "flota_disponible": int(round(float(
            plan["flota_disponible"]))), "hora_pico": max(HORAS[0], int(math.floor(t_rec - 1e-9))),
            "requeridos_pico_10_3": max(completas, default=None),
            "requeridos_programados": int(math.ceil(max_prog - 1e-6)), "nota": NOTA_VEHICULOS}


def _nota_recaudo(tarifa: float | None, params: dict, costo_actual: float) -> str:
    if not tarifa:
        return NOTA_TARIFA_SIN_DATO
    return (f"Recaudo = pasajeros esperados × tarifa neta de {_f(float(tarifa), 0)} COP por pasajero: tarifa pública "
            f"del Área Metropolitana 2026 (3.700 COP) × 0,86 que retiene el operador (datos/costos_fuente.json, la "
            f"misma de param_d5(fuente=True)); Extreme no suministró la tarifa (§19), así que es una cifra de "
            f"referencia. Costo operativo = bus-hora ({_f(params['COSTO_BUS_HORA'], 0)} COP) + km "
            f"({_f(params['COSTO_KM'], 0)} COP) del plan; con lo programado hoy sería {_f(costo_actual, 0)} COP. "
            f"vehiculos_hora_ahorrados > 0: el plan usa menos vehículos-hora que lo programado; < 0: usa más.")


def _redondeo(valor: float | None, decimales: int | None = None) -> float | None:
    if valor is None:
        return None
    return round(float(valor), decimales) if decimales is not None else round(float(valor))


def _flota_y_recaudo(plan: dict, tabla, params: dict, pasajeros_dia: float) -> dict:
    """Plan frente a lo programado (vehículos-hora, costo, espera y sobreocupación) y recaudo con la tarifa neta."""
    from app.servicios.motor_d5 import comun as motor_comun

    horas = plan["horas"]
    sin_programado = frozenset(int(h["hora"]) for h in horas if h.get("frecuencia_actual_min") is None)
    rec = _comparacion_oferta(tabla, {int(h["hora"]): float(h["salidas"]) for h in horas}, params)
    act = _comparacion_oferta(tabla, {int(h["hora"]): float(h.get("salidas_programadas") or 0.0) for h in horas},
                              params, sin_programado)
    comp = plan.get("componentes_costo_cop") or {}
    tarifa = params.get("TARIFA") if motor_comun.es_fuente(params) else None
    return {
        "recaudo_esperado_cop": _redondeo(pasajeros_dia * float(tarifa)) if tarifa else None,
        "costo_operativo_cop": _redondeo(comp.get("op", rec["costo_operativo_cop"])),
        "vehiculos_hora_ahorrados": round(act["vehiculos_hora"] - rec["vehiculos_hora"], 1),
        "nota": _nota_recaudo(tarifa, params, act["costo_operativo_cop"]),
        "tarifa_neta_cop": _redondeo(tarifa, 1),
        "costo_operativo_actual_cop": _redondeo(act["costo_operativo_cop"]),
        "vehiculos_hora_recomendados": round(rec["vehiculos_hora"], 1),
        "vehiculos_hora_actuales": round(act["vehiculos_hora"], 1),
        "espera_media_min": _redondeo(rec["espera_media_min"], 2),
        "espera_media_actual_min": _redondeo(act["espera_media_min"], 2),
        "sobreocupacion_pasajeros": _redondeo(rec["sobreocupacion_pasajeros"], 1),
        "sobreocupacion_pasajeros_actual": _redondeo(act["sobreocupacion_pasajeros"], 1),
        "ingreso_perdido_cop": _redondeo(comp.get("ingreso")),
    }


def _plan_reutilizable(plan: dict | None, model_id: str | None, version_u: int | None, pronostico: str) -> bool:
    """El plan que trae quien llama (el ciclo diario acaba de calcularlo y persistirlo) sirve tal cual si es del mismo
    modelo activo, de la misma versión de umbrales y con el pronóstico del modelo activo."""
    return (isinstance(plan, dict) and bool(plan.get("horas")) and pronostico == "activo"
            and plan.get("fuente_pronostico") == "modelo_activo"
            and (model_id is None or plan.get("model_id") == model_id)
            and plan.get("umbrales_version") == version_u)


def _llamar_plan_dia(plan_dia, ruta: str, fecha: date, umbrales: dict, version_u: int | None, pronostico: str,
                     pron: list[dict], model_id: str | None, calibracion: str | None) -> tuple[dict, str]:
    """Plan del día con optimizacion.plan_dia y la fuente de su pronóstico. Con el pronóstico del modelo activo y un
    plan_dia que acepta model_id es la misma llamada del ciclo diario; si no, plan_dia recibe el pronóstico hora por
    hora de la respuesta (solo cuando el pronóstico es el del modelo activo)."""
    import inspect

    parametros = inspect.signature(plan_dia).parameters
    if pronostico == "activo" and model_id and "model_id" in parametros:
        # la misma llamada del ciclo diario (ejecucion.plan_y_respuesta): su memoria evita repetir el MILP
        plan = plan_dia(fecha, ruta, umbrales=dict(umbrales or {}), umbrales_version=version_u, model_id=model_id)
    else:
        horario = [{"hora": p["hora"], "p10": p["p10"], "p50": p["esperado"], "p90": p["p90"],
                    "calibracion_version": calibracion} for p in pron]
        plan = plan_dia(fecha, ruta, umbrales=dict(umbrales or {}), umbrales_version=version_u,
                        pronostico=pronostico, pronostico_horario=horario if pronostico == "activo" else None)
    fuente = plan.get("fuente_pronostico") or ("modelo_activo" if pronostico == "activo" else "E12")
    return plan, str(fuente)


def _plan(ruta: str, fecha: date, umbrales: dict, version_u: int | None, pronostico: str,
          pron: list[dict], model_id: str | None = None, calibracion: str | None = None,
          plan_previo: dict | None = None) -> tuple[dict, str]:
    """Plan del día de la ruta y la fuente de su pronóstico.

    Con optimizacion.plan_dia (MILP de D5 con los umbrales vigentes) y el pronóstico del modelo activo: el mismo
    plan que el ciclo diario persiste como filas origen = 'plan_dia' (misma llamada, con model_id; si quien llama ya
    lo calculó, `plan_previo` se usa tal cual y no se vuelve a resolver el MILP). Así GET /respuesta y
    GET /recommendations/plan dicen las mismas salidas hora por hora. Sin plan_dia, el respaldo es el plan D5 con el
    pronóstico E12 precalculado, que solo existe para 2025."""
    from app.servicios import optimizacion

    plan_dia = _plan_dia_disponible()
    try:
        if plan_dia is not None and _plan_reutilizable(plan_previo, model_id, version_u, pronostico):
            return plan_previo, str(plan_previo.get("fuente_pronostico"))
        if plan_dia is not None:
            return _llamar_plan_dia(plan_dia, ruta, fecha, umbrales, version_u, pronostico, pron, model_id,
                                    calibracion)
        plan = optimizacion.resumen_plan_d5(ruta, fecha, modelo="E12", fuente_costos=True,
                                            headway_min=_umbral(umbrales, "headway_minimo_min"))
    except (ValueError, LookupError) as exc:
        raise SinDatos(str(exc)) from exc
    return plan, "E12"


def _bloque_ruta(ruta: str, fecha: date, model_id: str, umbrales: dict, version_u: int | None,
                 planes: dict[str, dict] | None = None) -> dict:
    """Todo lo de una ruta y un día que no depende de las alertas: pronóstico, plan, vehículos, flota y recaudo.
    `planes` ({ruta: plan}): el plan que ya calculó quien llama se reutiliza; el que se calcule aquí se agrega."""
    from app.servicios import datos
    from app.servicios.motor_d5 import comun as motor_comun

    pron_lista = _pronostico_dia(ruta, fecha, model_id)
    calibraciones = sorted({str(p.pop("_calibracion")) for p in pron_lista if p.get("_calibracion")})
    plan, fuente = _plan(ruta, fecha, umbrales, version_u, pronostico_plan(), pron_lista, model_id,
                         ", ".join(calibraciones) or None, plan_previo=(planes or {}).get(ruta))
    if planes is not None:
        planes[ruta] = plan
    pron = {p["hora"]: p for p in pron_lista}
    params = _costos_del_plan(plan, motor_comun.param_d5(fuente=True))
    tipo_dia = str(plan["tipo_dia"])
    limites = _limites_headway(params, tipo_dia, umbrales)
    if plan.get("headway_minimo_min") and plan.get("headway_maximo_min"):     # los mismos límites que usó el plan
        limites = (float(plan["headway_minimo_min"]), float(plan["headway_maximo_min"]))
    filas = _filas_despacho(plan, limites)
    pasajeros = _pasajeros(pron)
    tabla = _tabla_comparacion(plan, ruta, fecha, umbrales, version_u, fuente)
    idruta = datos.ruta_info(ruta).get("idruta")
    return {"ruta": ruta, "idruta": None if idruta is None else int(idruta), "tipo_dia": tipo_dia,
            "cada_cuanto_despachar": filas, "resumen_despacho": _resumen_despacho(filas, plan, pron),
            "pasajeros_esperados": pasajeros, "vehiculos": _vehiculos(plan),
            "flota_y_recaudo": _flota_y_recaudo(plan, tabla, params, pasajeros["dia"]),
            "_fuente_pronostico": fuente, "_calibracion": calibraciones,
            "_plan": {"estado_solver": plan.get("estado_solver"), "headway_minimo_min": plan.get("headway_minimo_min"),
                      "plan_model_id": plan.get("model_id"), "plan_calibracion": plan.get("calibracion_version")}}


# ---------------------------------------------------------------------------------------------------- alertas
def _alerta_salida(a: Alerta, alcance: str) -> dict:
    return {"alert_id": str(a.alert_id), "codigo": a.codigo, "severidad": a.severidad, "estado": a.estado,
            "ruta": a.ruta, "origen": getattr(a, "origen", None), "alcance": alcance,
            "detectada_en": instante_bogota(a.detectada_en), "ventana_inicio": instante_bogota(a.ventana_inicio),
            "explicacion": a.explicacion, "recomendacion": a.recomendacion}


def _rango_severidad():
    return case(*[(Alerta.severidad == s, n) for s, n in ORDEN_SEVERIDAD.items()], else_=len(ORDEN_SEVERIDAD))


def atencion_inmediata(sesion: Session | None, ruta: str, limite: int = MAX_ALERTAS) -> list[dict]:
    """Alertas ABIERTAS AHORA (ni cerradas ni descartadas en el momento de la consulta) de la ruta y las generales
    (sin ruta), críticas primero y luego las más recientes."""
    if sesion is None:
        return []
    consulta = (select(Alerta).where(Alerta.estado.notin_(ESTADOS_FINALES))
                .where(or_(Alerta.ruta == ruta, Alerta.ruta.is_(None)))
                .order_by(_rango_severidad(), Alerta.detectada_en.desc(), Alerta.alert_id).limit(limite))
    return [_alerta_salida(a, ALCANCE_ABIERTAS) for a in sesion.scalars(consulta).all()]


def _limites_dia(fecha: date) -> tuple[datetime, datetime]:
    inicio = datetime.combine(fecha, time(0, 0), tzinfo=servicio.ZONA)
    return inicio, inicio + timedelta(days=1)


def alertas_de_la_fecha(sesion: Session | None, ruta: str, fecha: date, limite: int = MAX_ALERTAS) -> list[dict]:
    """Alertas de la ruta (o generales) detectadas en la fecha consultada o cuya ventana empieza ese día (día de
    Bogotá), en cualquier estado, críticas primero."""
    if sesion is None:
        return []
    ini, fin = _limites_dia(fecha)
    consulta = (select(Alerta).where(or_(Alerta.ruta == ruta, Alerta.ruta.is_(None)))
                .where(or_(Alerta.detectada_en.between(ini, fin - timedelta(microseconds=1)),
                           Alerta.ventana_inicio.between(ini, fin - timedelta(microseconds=1))))
                .order_by(_rango_severidad(), Alerta.detectada_en.desc(), Alerta.alert_id).limit(limite))
    return [_alerta_salida(a, ALCANCE_FECHA) for a in sesion.scalars(consulta).all()]


def _resumen_atencion(sesion: Session | None, ruta: str, fecha: date, consultado_en: str) -> dict:
    """Conteos completos (sin el límite de la lista) de las abiertas ahora y de las de la fecha, por severidad."""
    abiertas: dict[str, int] = {}
    de_la_fecha: dict[str, int] = {}
    if sesion is not None:
        ini, fin = _limites_dia(fecha)
        de_ruta = or_(Alerta.ruta == ruta, Alerta.ruta.is_(None))
        for destino, condicion in ((abiertas, Alerta.estado.notin_(ESTADOS_FINALES)),
                                   (de_la_fecha, or_(Alerta.detectada_en.between(ini, fin - timedelta(microseconds=1)),
                                                     Alerta.ventana_inicio.between(ini,
                                                                                   fin - timedelta(microseconds=1))))):
            for sev, n in sesion.execute(select(Alerta.severidad, func.count()).where(de_ruta, condicion)
                                         .group_by(Alerta.severidad)).all():
                destino[str(sev)] = int(n)
    return {"consultado_en": consultado_en, "abiertas_ahora": sum(abiertas.values()),
            "abiertas_ahora_por_severidad": abiertas, "de_la_fecha": sum(de_la_fecha.values()),
            "de_la_fecha_por_severidad": de_la_fecha,
            "nota": (f"«Abiertas ahora»: alertas sin cerrar ni descartar en ai_frecuencias.alert en el momento de la "
                     f"consulta ({consultado_en}), de cualquier fecha; es lo que pide atención inmediata. «De la "
                     f"fecha»: alertas detectadas el {fecha.isoformat()} (día de Bogotá), en cualquier estado.")}


def _agregar_atencion(sesion: Session | None, bloque: dict, fecha: date, consultado_en: str) -> dict:
    r = bloque["ruta"]
    bloque["atencion_inmediata"] = atencion_inmediata(sesion, r)
    bloque["alertas_de_la_fecha"] = alertas_de_la_fecha(sesion, r, fecha)
    bloque["atencion_resumen"] = _resumen_atencion(sesion, r, fecha, consultado_en)
    return bloque


def _ultima_ejecucion(sesion: Session | None) -> str | None:
    """La última ejecución del ciclo de frecuencia que terminó bien (la que actualizó datos, predicciones y alertas)."""
    if sesion is None:
        return None
    e = sesion.scalars(select(Ejecucion).where(Ejecucion.tipo == "frecuencia", Ejecucion.estado == "ok")
                       .order_by(Ejecucion.terminado_en.desc().nulls_last(), Ejecucion.creado_en.desc())
                       .limit(1)).first()
    return str(e.execution_id) if e is not None else None


# ---------------------------------------------------------------------------------------------------- respuesta
def limitaciones(modelo: dict, fuente_pronostico: str) -> list[str]:
    from app.servicios import optimizacion

    elasticidad = str(getattr(optimizacion, "TEXTO_ELASTICIDAD", TEXTO_ELASTICIDAD)).rstrip(".")
    if fuente_pronostico == "E12":
        plan_txt = ("El plan de despacho es el MILP de D5 resuelto con el pronóstico híbrido E12 precalculado para "
                    "2025 (datos/pronosticos_2025.parquet); los pasajeros esperados son del modelo activo "
                    f"{modelo['model_id']} con su banda P10-P90 calibrada. Los dos pronósticos no coinciden hora a "
                    "hora, y solo hay plan para los días de 2025 con insumos de D5.")
    else:
        plan_txt = (f"El plan de despacho y los pasajeros esperados salen del mismo pronóstico horario del modelo "
                    f"activo {modelo['model_id']} (P10, P50 y P90 calibrados de cada hora): se puede calcular para "
                    "cualquier día con variables, incluido el día siguiente al último dato.")
    return [
        plan_txt,
        "El headway mínimo gobernado en threshold_config (headway_minimo_min; 2 min por omisión) es una restricción "
        "explícita del plan (§10.2): ninguna hora programa más de floor(minutos / headway mínimo) salidas. Donde la "
        "demanda pediría más, la hora sale «no viable» con su motivo y el plan muestra la mejor aproximación "
        "ejecutable, sin forzar una cifra (§10.3 y §18).",
        "«Espera máxima» de §5.1 se interpreta como la espera media del pasajero (headway / 2 con llegadas "
        "aleatorias): el headway máximo efectivo es min(headway_maximo_min, 2 × espera_max_min) (supuesto S12, "
        "pregunta a Extreme en docs/hallazgos_extreme.md).",
        "La banda P10-P90 del día suma las bandas de cada hora: es más ancha que la banda del total del día.",
        "La tarifa no la suministró Extreme (§19): el recaudo usa la tarifa pública 2026 del Área Metropolitana × 0,86 "
        "(datos/costos_fuente.json) y es una cifra de referencia.",
        "Ciclo, flota disponible e intervalo programado son medianas de 2025 por ruta, tipo de día y hora (D1) y no "
        "siempre cuadran entre sí: con la programación de hoy, los buses en ruta pueden superar la flota "
        "(vehiculos.requeridos_programados). Extreme debe confirmar el ciclo y la flota por franja (§19).",
        "El valor del tiempo de espera (7.000 COP/h) y la penalidad por pasajero sobre la capacidad (10.000 COP) son "
        f"supuestos de D5 que debe validar el área operativa (§5.1). Elasticidad: {elasticidad}.",
        "Atención inmediata: la lista «abiertas ahora» son las alertas sin cerrar ni descartar en el momento de la "
        "consulta, de cualquier fecha; las de la fecha consultada van aparte en alertas_de_la_fecha.",
    ]


def _umbrales(sesion: Session | None) -> tuple[int | None, dict]:
    """Versión vigente de threshold_config y sus valores (None y {} sin base)."""
    if sesion is None:
        return None, {}
    version, umbrales = servicio.umbrales_vigentes(sesion)
    return version, dict(umbrales or {})


def _avisos(modelo: dict, fuente: str, tipo_dia: str | None, fecha: date) -> list[str]:
    avisos = limitaciones(modelo, fuente)
    if tipo_dia == "Domingo/festivo" and fecha.weekday() != 6:
        avisos.append(f"El {fecha.isoformat()} es festivo: el plan y la frecuencia programada de comparación usan "
                      "los parámetros de domingo o festivo (parametros_operativos_hora no tiene una programación "
                      "propia para los festivos entre semana).")
    return avisos


def _validar_rutas(rutas: list[str] | tuple[str, ...] | None) -> tuple[str, ...]:
    if not rutas:
        return RUTAS
    desconocidas = [r for r in rutas if r not in RUTAS]
    if desconocidas:
        raise ValueError(f"Ruta desconocida: {desconocidas[0]!r}. Válidas: {', '.join(RUTAS)}")
    return tuple(dict.fromkeys(rutas))


def _fecha_calculable(fecha: date) -> bool:
    """La fecha tiene variables del modelo para las tres rutas en la serie vigente (la validada, con los datos
    recientes de la base, dentro de inferencia.con_sesion) y, sin plan_dia, insumos D5 de 2025."""
    from app.servicios import inferencia

    indice = inferencia.tabla_variables().index
    if not all((r, fecha, h) in indice for r in RUTAS for h in (HORAS[0], HORAS[-1])):
        return False
    if _plan_dia_disponible() is not None and pronostico_plan() == "activo":
        return True
    return fecha in set(fechas_disponibles())


def _validar_fecha(fecha: date) -> None:
    if not _fecha_calculable(fecha):
        fechas = fechas_disponibles()
        rango = f"del {fechas[0].isoformat()} al {fechas[-1].isoformat()}" if fechas else "ninguno"
        raise SinDatos(f"No hay variables del modelo (o insumos del plan) para el {fecha.isoformat()}: días "
                       f"calculables con la serie empaquetada {rango}, más los que agreguen los datos recientes")


def _serie_vigente(sesion: Session | None):
    """Con sesión, la inferencia usa la serie validada (Parquet empaquetado más demanda_observada, RF-013)."""
    from contextlib import nullcontext

    entrar = getattr(servicio, "serie_de_la_sesion", None)
    return entrar(sesion) if sesion is not None and entrar is not None else nullcontext()


def _fuentes(modelo: dict, fuente: str) -> list[str]:
    plan = ("Plan de despacho: app/servicios/optimizacion.plan_dia (MILP de D5 con PuLP/CBC y los umbrales vigentes "
            "de threshold_config), con el pronóstico horario del modelo activo" if fuente != "E12" else
            "Plan de despacho: app/servicios/optimizacion.resumen_plan_d5 (MILP de D5 con PuLP/CBC), pronóstico E12 "
            "precalculado (datos/pronosticos_2025.parquet)")
    return [
        plan,
        f"Pasajeros esperados: app/servicios/inferencia.predecir (modelo {modelo['model_id']}, ventana de 60 min por "
        "hora de salida, banda P10-P90 calibrada, sin factor intradía)",
        "Datos históricos: datos/demanda_horaria.parquet (serie empaquetada); datos recientes: "
        "ai_frecuencias.demanda_observada (lo que incorpora el ciclo diario)",
        "Frecuencia programada, ciclo y flota: datos/parametros_operativos_hora.parquet (D1, mediana 2025 por ruta, "
        "tipo de día y hora)",
        "Costos y tarifa: datos/costos_fuente.json (param_d5(fuente=True))",
        "Foto de la respuesta: tabla ai_frecuencias.respuesta_reto (una fila por fecha, ruta, modelo y versión de "
        "umbrales)",
        "Atención inmediata: tabla ai_frecuencias.alert (abiertas ahora: estados nueva, reconocida y asignada)",
    ]


def componer(sesion: Session | None, ruta: str | None = None, fecha: date | None = None, *,
             rutas: list[str] | tuple[str, ...] | None = None, execution_id: Any = None,
             con_alertas: bool = True, planes: dict[str, dict] | None = None) -> dict:
    """Calcula la respuesta completa (pronóstico y plan de cada ruta) sin guardarla. Lanza SinDatos si la fecha no se
    puede calcular y ValueError si una ruta no es válida. Es el cálculo de precalcular(); no corre en un GET.
    `planes`: ver precalcular()."""
    elegidas = _validar_rutas([ruta] if ruta else rutas)
    with _serie_vigente(sesion):
        return _componer(sesion, elegidas, fecha or fecha_por_omision(sesion), execution_id, con_alertas, planes)


def _componer(sesion: Session | None, elegidas: tuple[str, ...], fecha: date, execution_id: Any,
              con_alertas: bool, planes: dict[str, dict] | None = None) -> dict:
    _validar_fecha(fecha)
    modelo = modelo_vigente(sesion)
    version_u, umbrales = _umbrales(sesion)
    consultado_en = _ahora_bogota()
    bloques, calibraciones, fuentes = [], set(), set()
    for r in elegidas:
        completo = _bloque_ruta(r, fecha, modelo["model_id"], umbrales, version_u, planes)
        calibraciones.update(completo.get("_calibracion") or [])
        fuentes.add(completo["_fuente_pronostico"])
        bloque = {k: v for k, v in completo.items() if not k.startswith("_")}
        bloque["tipo_dia"] = completo["tipo_dia"]
        if con_alertas:
            _agregar_atencion(sesion, bloque, fecha, consultado_en)
        bloques.append(bloque)
    tipo_dia = bloques[0]["tipo_dia"] if bloques else None
    fuente = ", ".join(sorted(fuentes)) or None
    for b in bloques:
        b.pop("tipo_dia", None)
    return {
        "pregunta": PREGUNTA,
        "fecha": fecha.isoformat(),
        "tipo_dia": tipo_dia,
        "generado_en": consultado_en,
        "consultado_en": consultado_en,
        "trazabilidad": {
            "model_id": modelo["model_id"], "feature_version": modelo["feature_version"],
            "data_cutoff": modelo["data_cutoff"], "calibracion_version": ", ".join(sorted(calibraciones)) or None,
            "calibracion_banda": ", ".join(sorted(calibraciones)) or None,
            "fuente_pronostico": fuente, "umbrales_version": version_u,
            "execution_id": None if execution_id is None else str(execution_id),
            "ultima_ejecucion_ciclo": _ultima_ejecucion(sesion),
            "datos_hasta": ultima_fecha_datos(sesion).isoformat(),
            "fuentes": _fuentes(modelo, fuente or ""),
        },
        "rutas": bloques,
        "limitaciones": _avisos(modelo, fuente or "", tipo_dia, fecha),
    }


# ---------------------------------------------------------------------------------------------------- foto guardada
def _payload_ruta(respuesta: dict, bloque: dict) -> dict:
    """Lo que se guarda por ruta: el bloque sin las alertas (se leen al consultar) y lo común de la respuesta."""
    plano = {k: v for k, v in bloque.items() if k not in ("atencion_inmediata", "alertas_de_la_fecha",
                                                           "atencion_resumen")}
    return servicio.json_seguro({"fecha": respuesta["fecha"], "tipo_dia": respuesta["tipo_dia"],
                                 "generado_en": respuesta["generado_en"], "trazabilidad": respuesta["trazabilidad"],
                                 "limitaciones": respuesta["limitaciones"], "ruta": plano})


def precalcular(sesion: Session, fecha: date | None, rutas: list[str] | None = None, *, execution_id: Any = None,
                confirmar: bool = False, planes: dict[str, dict] | None = None) -> dict:
    """Calcula la respuesta del reto (modelo activo, umbrales vigentes) y guarda una foto por ruta en
    ai_frecuencias.respuesta_reto. Devuelve la respuesta calculada, con «guardadas» = filas escritas.

    Reemplaza la foto anterior de la misma (fecha, ruta, modelo, versión de umbrales). No hace commit salvo con
    `confirmar`: el trabajador de la cola lo hace en la misma transacción del cierre «ok» de la ejecución.

    `planes` ({ruta: plan de optimizacion.plan_dia}) es de entrada y salida: el ciclo diario pasa los planes que
    acaba de calcular y persistir, y la respuesta los usa tal cual (mismo modelo y versión de umbrales; no vuelve a
    resolver el MILP). Las rutas que falten se calculan y se agregan al diccionario, para que quien llama persista
    las mismas horas (trabajo «respuesta» de la cola)."""
    respuesta = componer(sesion, fecha=fecha, rutas=rutas, execution_id=execution_id, con_alertas=False,
                         planes=planes)
    traz = respuesta["trazabilidad"]
    ejecucion_id = None if execution_id is None else str(execution_id)
    # TABLA es la constante del módulo (ai_frecuencias.respuesta_reto), no una entrada: todo valor va como parámetro
    borrar = text(f"DELETE FROM {TABLA} WHERE fecha = :fecha AND ruta = :ruta AND model_id = :model_id "  # nosec B608
                  "AND umbrales_version IS NOT DISTINCT FROM :umbrales")
    insertar = text(f"INSERT INTO {TABLA} (fecha, ruta, idruta, payload, model_id, calibracion_version, "  # nosec B608
                    "umbrales_version, execution_id, fuente_pronostico) VALUES (:fecha, :ruta, :idruta, "
                    "CAST(:payload AS jsonb), :model_id, :calibracion, :umbrales, CAST(:execution_id AS uuid), "
                    ":fuente)")
    for bloque in respuesta["rutas"]:
        valores = {"fecha": date.fromisoformat(respuesta["fecha"]), "ruta": bloque["ruta"], "idruta": bloque["idruta"],
                   "payload": json.dumps(_payload_ruta(respuesta, bloque), ensure_ascii=False),
                   "model_id": traz["model_id"], "calibracion": traz["calibracion_version"],
                   "umbrales": traz["umbrales_version"], "execution_id": ejecucion_id,
                   "fuente": traz["fuente_pronostico"]}
        sesion.execute(borrar, valores)
        sesion.execute(insertar, valores)
    sesion.flush()
    if confirmar:
        sesion.commit()
    respuesta["guardadas"] = len(respuesta["rutas"])
    return respuesta


def _ultimo_calculo(sesion: Session, fecha: date) -> dict | None:
    """La última ejecución de tipo «respuesta» pedida para esa fecha (para explicar un 404 «sin_calcular»)."""
    try:
        with sesion.begin_nested():    # un fallo revierte solo esta lectura, no la sesión de quien llama
            e = sesion.scalars(select(Ejecucion).where(Ejecucion.tipo == TIPO_TRABAJO,
                                                       Ejecucion.parametros["fecha"].astext == fecha.isoformat())
                               .order_by(Ejecucion.creado_en.desc()).limit(1)).first()
    except Exception:  # noqa: BLE001 - el detalle es informativo
        return None
    if e is None:
        return None
    return {"execution_id": str(e.execution_id), "estado": e.estado, "mensaje": e.mensaje,
            "creado_en": instante_bogota(e.creado_en)}


def _fotos(sesion: Session, fecha: date, model_id: str, version_u: int | None) -> dict[str, Any]:
    # TABLA es la constante del módulo, no una entrada: la fecha, el modelo y la versión van como parámetros
    filas = sesion.execute(text(
        f"SELECT DISTINCT ON (ruta) ruta, payload, execution_id, generado_en FROM {TABLA} "  # nosec B608
        "WHERE fecha = :fecha AND model_id = :model_id AND umbrales_version IS NOT DISTINCT FROM :umbrales "
        "ORDER BY ruta, generado_en DESC"), {"fecha": fecha, "model_id": model_id, "umbrales": version_u}).all()
    return {f.ruta: f for f in filas}


def leer(sesion: Session | None, ruta: str | None = None, fecha: date | None = None) -> dict:
    """GET /api/v1/respuesta: la foto guardada más reciente para (fecha, ruta) con el modelo activo y la versión de
    umbrales vigente, sin cálculo pesado; las alertas se leen en el momento de la consulta. Lanza SinCalcular si
    falta la foto de alguna ruta pedida."""
    elegidas = _validar_rutas([ruta] if ruta else None)
    fecha = fecha or fecha_por_omision(sesion)
    pista = {"pista": PISTA, "cuerpo_sugerido": {"fecha": fecha.isoformat(), "rutas": list(elegidas)},
             "rol_requerido": "analista"}
    if sesion is None:
        raise SinCalcular(f"No hay respuesta calculada para el {fecha.isoformat()}: sin base de datos no hay fotos",
                          {"fecha": fecha.isoformat(), **pista})
    version_u, _u = _umbrales(sesion)
    candidatos = _candidatos_modelo(sesion)
    fotos: dict[str, Any] = {}
    model_id = candidatos[0] if candidatos else None
    for mid in candidatos:
        fotos = _fotos(sesion, fecha, mid, version_u)
        if fotos:
            model_id = mid
            break
    faltan = [r for r in elegidas if r not in fotos]
    if faltan:
        raise SinCalcular(
            f"La respuesta del {fecha.isoformat()} no está calculada para {', '.join(faltan)} con el modelo "
            f"{model_id} y la versión de umbrales {version_u}: pídala con POST /api/v1/respuesta/calcular "
            "(rol analista) y vuelva a consultar",
            {"fecha": fecha.isoformat(), "rutas_sin_calcular": faltan, "model_id": model_id,
             "umbrales_version": version_u, **pista, "ultimo_calculo": _ultimo_calculo(sesion, fecha)})
    return _desde_fotos(sesion, fecha, [fotos[r] for r in elegidas])


def _desde_fotos(sesion: Session, fecha: date, filas: list) -> dict:
    consultado_en = _ahora_bogota()
    payloads = [f.payload if isinstance(f.payload, dict) else json.loads(f.payload) for f in filas]
    mas_reciente = max(range(len(filas)), key=lambda i: filas[i].generado_en)
    base = payloads[mas_reciente]
    traz = dict(base["trazabilidad"])
    ejecuciones = sorted({str(f.execution_id) for f in filas if f.execution_id is not None})
    traz["execution_id"] = str(filas[mas_reciente].execution_id) if filas[mas_reciente].execution_id else None
    traz["ejecuciones_por_ruta"] = {p["ruta"]["ruta"]: (str(f.execution_id) if f.execution_id else None)
                                    for p, f in zip(payloads, filas, strict=True)}
    if len(ejecuciones) > 1:
        log.info("La respuesta del %s combina fotos de %s ejecuciones", fecha, len(ejecuciones))
    rutas = [_agregar_atencion(sesion, dict(p["ruta"]), fecha, consultado_en) for p in payloads]
    return {"pregunta": PREGUNTA, "fecha": fecha.isoformat(), "tipo_dia": base.get("tipo_dia"),
            "generado_en": instante_bogota(filas[mas_reciente].generado_en) or base.get("generado_en"),
            "consultado_en": consultado_en, "trazabilidad": traz, "rutas": rutas,
            "limitaciones": base.get("limitaciones") or []}


# ---------------------------------------------------------------------------------------------------- cola de trabajos
def solicitar_calculo(sesion: Session, fecha: date | None, rutas: list[str] | None,
                      correlation_id: str | None) -> tuple[Ejecucion, bool]:
    """Encola una ejecución de tipo «respuesta» con {fecha, rutas} (POST /api/v1/respuesta/calcular). Si ya hay una
    igual en cola o corriendo, devuelve esa (nueva = False) en lugar de duplicar el cálculo. Una fecha fuera de los
    días calculables lanza SinDatos sin encolar nada (la API responde 404 «sin_datos»)."""
    elegidas = list(_validar_rutas(rutas))
    fecha = fecha or fecha_por_omision(sesion)
    primera, ultima = rango_calculable(sesion)
    if not primera <= fecha <= ultima:
        raise SinDatos(f"El {fecha.isoformat()} está fuera de los días que se pueden calcular: del "
                       f"{primera.isoformat()} al {ultima.isoformat()} (las variables del modelo llegan hasta "
                       f"{(ultima - ultima_fecha_datos(sesion)).days} días después del último dato)")
    parametros = {"fecha": fecha.isoformat(), "rutas": elegidas}
    existente = sesion.scalars(select(Ejecucion).where(Ejecucion.tipo == TIPO_TRABAJO,
                                                       Ejecucion.estado.in_(("en_cola", "corriendo")),
                                                       Ejecucion.parametros["fecha"].astext == parametros["fecha"])
                               .order_by(Ejecucion.creado_en.desc())).all()
    for e in existente:
        if sorted((e.parametros or {}).get("rutas") or RUTAS) == sorted(elegidas):
            return e, False
    return servicio.crear_ejecucion(sesion, TIPO_TRABAJO, parametros, correlation_id), True


# ---------------------------------------------------------------------------------------------------- exportación
def tabla_plana(respuesta: dict) -> list[dict]:
    """Una fila por ruta y hora (para la exportación CSV/XLSX de RF-017)."""
    filas = []
    traz = respuesta["trazabilidad"]
    for r in respuesta["rutas"]:
        pron = {p["hora"]: p for p in r["pasajeros_esperados"]["por_hora"]}
        for h in r["cada_cuanto_despachar"]:
            p = pron.get(h["hora"], {})
            filas.append({"fecha": respuesta["fecha"], "tipo_dia": respuesta["tipo_dia"], "ruta": r["ruta"],
                          "idruta": r["idruta"], "hora": h["hora"], "franja": h["franja"],
                          "headway_min": h["headway_min"], "buses_hora": h["buses_hora"],
                          "headway_actual_min": h["headway_actual_min"], "buses_hora_actual": h["buses_hora_actual"],
                          "viable": h["viable"], "motivo": h["motivo"], "pasajeros_esperados": p.get("esperado"),
                          "pasajeros_p10": p.get("p10"), "pasajeros_p90": p.get("p90"),
                          "model_id": traz["model_id"], "calibracion_version": traz.get("calibracion_version"),
                          "fuente_pronostico": traz.get("fuente_pronostico"),
                          "umbrales_version": traz["umbrales_version"], "execution_id": traz.get("execution_id"),
                          "generado_en": respuesta["generado_en"]})
    return filas


def limpiar_cache() -> None:
    _fechas_disponibles.cache_clear()
    _serie_fechas.cache_clear()
