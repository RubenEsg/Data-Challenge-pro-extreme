"""Monitoreo del modelo de corto plazo (spec v1.5 §9.4 «se monitorean la deriva de datos, el error móvil, la cobertura
de los intervalos, el volumen de predicciones», §9.5 «comparación contra los valores reales», ALT-010).

En cada ciclo diario, con los días que ya leyó la API (el panel empaquetado y lo que trajo la lectura incremental):

- error móvil: el pronóstico de la ruta del modelo activo de la familia corto_plazo en cada media hora de 04:00 a 21:00
  de los últimos VENTANA_DIAS días completos, frente a lo que subió en cada ventana (gobierno_corto_plazo.evaluar):
  WAPE, MAE y sesgo, por horizonte, por ruta y en conjunto;
- cobertura de la banda P10-P90 en esas mismas ventanas;
- volumen: los pronósticos de corto plazo guardados en la ventana (prediction_corto_plazo, fila de la ruta);
- deriva (PSI) de las variables de lo observado (p15, p30, p60, hoy, sal60) y del histórico (m8) del pronóstico de la
  ruta a 60 minutos, frente a las 4 semanas anteriores a la fecha de corte del modelo (lo último que vio al entrenar);
- estado ok / aviso / alerta con los mismos umbrales de monitoreo del modelo horario (monitoreo.estado_de); un WAPE
  móvil de una ruta sobre wape_max abre ALT-010 (un episodio por modelo y ruta).

Queda en model_monitoring (model_id del corto plazo, detalle.familia = corto_plazo), con el execution_id del ciclo.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from datetime import time as dtime
from functools import lru_cache

import numpy as np

LOG = logging.getLogger("api_frecuencias.monitoreo")
VENTANA_DIAS = 7
REFERENCIA_DIAS = 28
HORIZONTE_PSI = 60
VARIABLES_PSI = ("p15", "p30", "p60", "hoy", "sal60", "m8")


def _ultimo_dia_completo(sc, marca) -> date | None:
    """El último día leído entero hasta la marca de agua de la ejecución."""
    from app.servicios import corto_plazo as cp

    if marca is None:
        return None
    m = marca.astimezone(cp.ZONA)
    ultimo = m.date() if (m.hour, m.minute, m.second) == (23, 59, 59) else m.date() - timedelta(days=1)
    return min(ultimo, cp.fecha_de_dia(len(sc.ruta.cal) - 1))


def _variables(model_id: str, desde: date, hasta: date) -> dict[str, np.ndarray]:
    """Las variables de PSI del pronóstico de la ruta a 60 minutos en los días con datos de [desde, hasta]."""
    from app.servicios import corto_plazo as cp
    from app.servicios import variables_corto_plazo as V

    cols: dict[str, list] = {v: [] for v in VARIABLES_PSI}
    d = desde
    while d <= hasta:
        k = cp.dia_de_fecha(d)
        for idruta in V.RUTAS:
            sc = cp.serie_completa(idruta)
            if not (V.ARRANQUE <= k < len(sc.ruta.cal)) or not bool(sc.ruta.ok[k]):
                continue
            n = cp._dia(model_id, idruta, k, HORIZONTE_PSI, niveles=("ruta",))["ruta"]
            for v in VARIABLES_PSI:
                if v in n["nombres"]:
                    cols[v].append(n["x"][:, 0, n["nombres"].index(v)])
        d += timedelta(days=1)
    return {v: np.concatenate(x) if x else np.array([]) for v, x in cols.items()}


@lru_cache(maxsize=4)
def _referencia(model_id: str, corte: date, version: str) -> dict:
    """Los cuantiles de referencia de cada variable: las 4 semanas anteriores a la fecha de corte del modelo."""
    from app.servicios import monitoreo

    x = _variables(model_id, corte - timedelta(days=REFERENCIA_DIAS - 1), corte)
    return {v: monitoreo.referencia(valores) for v, valores in x.items()}


def _psi(model_id: str, corte: date, desde: date, hasta: date, version: str, umbrales: dict) -> dict:
    from app.servicios import monitoreo

    u = monitoreo.umbrales_monitoreo(umbrales)
    ref = _referencia(model_id, corte, version)
    act = _variables(model_id, desde, hasta)
    salida = {}
    for v in VARIABLES_PSI:
        valor = monitoreo.psi(ref[v], act[v]) if len(act[v]) else None
        nivel = ("sin_datos" if valor is None else "alerta" if valor > u["psi_alerta"] else
                 "aviso" if valor > u["psi_aviso"] else "ok")
        salida[v] = {"psi": None if valor is None else round(valor, 4), "nivel": nivel,
                     "umbral_aviso": u["psi_aviso"], "umbral_alerta": u["psi_alerta"],
                     "dispara_reentreno": True, "n": int(len(act[v]))}
    return salida


def _frac(x) -> float | None:
    return None if x is None else float(x) / 100.0


def _alertas_alt010(s, c, mid: str, wape_por_ruta: dict, desde: date, hasta: date) -> int:
    """ALT-010 por ruta con el WAPE móvil de la ventana; devuelve cuántas son nuevas (las repetidas se cuentan en el
    ciclo)."""
    from app.servicios import alertas, ejecucion
    from app.servicios import corto_plazo as cp

    nuevas = 0
    u = alertas._umbrales(dict(c.umbrales) | {"version": c.version_u})
    inicio = datetime.combine(desde, dtime(0), tzinfo=cp.ZONA)
    fin = datetime.combine(hasta + timedelta(days=1), dtime(0), tzinfo=cp.ZONA)
    for ruta, w in wape_por_ruta.items():
        a = alertas._alt010({"ruta": ruta, "model_id": mid, "wape_movil": w, "empresa": ejecucion.empresa_de(ruta),
                             "detectada_en": ejecucion.ahora(), "origen": "modelo", "ventana_inicio": inicio,
                             "ventana_fin": fin}, u)
        if a is None:
            continue
        registro, es_nueva = ejecucion.guardar_alerta(s, a, c.execution_id, c.version_u)
        if es_nueva:
            c.nuevas_alertas.append(registro)
            nuevas += 1
        else:
            c.repetidas += 1
    return nuevas


def en_ciclo(s, c) -> dict:
    """El monitoreo del corto plazo del ciclo diario (un ciclo intradía no lo hace: con el día a medias el error
    saldría inflado). Guarda la fila en model_monitoring y abre ALT-010 por ruta. Nunca detiene el ciclo."""
    from sqlalchemy import func, select

    from app.modelos_db import MonitoreoModelo, PrediccionCortoPlazo
    from app.servicios import corto_plazo as cp
    from app.servicios import ejecucion, gobierno_corto_plazo, monitoreo

    if s is None:
        return {}
    activo = ejecucion.modelo_activo(s, "corto_plazo")
    try:
        mid = activo.model_id if activo else cp.modelo_activo()
        if not mid:
            return {}
        with s.begin_nested(), cp.con_sesion(s):
            sc = cp.serie_completa(next(iter(cp.V.RUTAS)))
            hasta = _ultimo_dia_completo(sc, c.marca_nueva)
            if hasta is None:
                return {}
            desde = hasta - timedelta(days=VENTANA_DIAS - 1)
            ev = gobierno_corto_plazo.evaluar(mid, desde, hasta)
            if not ev.get("n"):
                return {"model_id": mid, "estado": "sin_datos", "desde": desde, "hasta": hasta}
            corte = date.fromisoformat(cp.cargar(mid)["manifiesto"]["data_cutoff"])
            psi_vars = _psi(mid, corte, desde, hasta, sc.version, c.umbrales)
            volumen = s.scalar(select(func.count()).select_from(PrediccionCortoPlazo).where(
                PrediccionCortoPlazo.model_id == mid, PrediccionCortoPlazo.nivel == "ruta",
                PrediccionCortoPlazo.fecha >= desde, PrediccionCortoPlazo.fecha <= hasta)) or 0
            m = {"model_id": mid, "wape_movil": _frac(ev.get("wape")), "mae_movil": ev.get("mae"),
                 "sesgo_pct": _frac(ev.get("sesgo_pct")), "cobertura_p10_p90": _frac(ev.get("cobertura_p10_p90")),
                 "psi": psi_vars}
            disp = {k: v for k, v in psi_vars.items() if v["psi"] is not None}
            k_max = max(disp, key=lambda k: disp[k]["psi"]) if disp else None
            estado, motivos = monitoreo.estado_de(m, c.umbrales)
            wape_por_ruta = {r: _frac(x.get("wape")) for r, x in (ev.get("por_ruta") or {}).items()}
            fila = MonitoreoModelo(
                execution_id=c.execution_id, model_id=mid, rol="activo", fecha_corte=hasta, desde=desde, hasta=hasta,
                ventana_dias=VENTANA_DIAS, n_observaciones=ev["n"], n_predicciones=None,
                predicciones_ventana=int(volumen), wape_movil=m["wape_movil"], mae_movil=m["mae_movil"],
                sesgo_pct=m["sesgo_pct"], cobertura_p10_p90=m["cobertura_p10_p90"],
                psi=ejecucion.json_seguro(psi_vars), psi_max=disp[k_max]["psi"] if k_max else None,
                psi_variable_max=k_max, estado=estado, motivos=ejecucion.json_seguro(motivos),
                umbrales_version=c.version_u,
                detalle=ejecucion.json_seguro({
                    "familia": "corto_plazo", "por_horizonte": ev.get("por_horizonte"), "wape_por_ruta": wape_por_ruta,
                    "por_ruta": ev.get("por_ruta"), "dias_con_datos": ev.get("dias"),
                    "referencia_psi": {"desde": corte - timedelta(days=REFERENCIA_DIAS - 1), "hasta": corte,
                                       "variables": list(VARIABLES_PSI), "horizonte_min": HORIZONTE_PSI},
                    "metodo": "pronóstico de la ruta cada media hora de 04:00 a 21:00 frente a lo que subió"}))
            s.add(fila)
            s.flush()
            nuevas = _alertas_alt010(s, c, mid, wape_por_ruta, desde, hasta)
        return {"id": fila.id, "model_id": mid, "estado": estado, "motivos": motivos, "desde": desde, "hasta": hasta,
                "wape_movil": m["wape_movil"], "cobertura_p10_p90": m["cobertura_p10_p90"],
                "sesgo_pct": m["sesgo_pct"], "psi_max": fila.psi_max, "psi_variable_max": k_max,
                "predicciones_ventana": int(volumen), "wape_por_ruta": wape_por_ruta, "alt010_nuevas": nuevas}
    except Exception as exc:  # noqa: BLE001 - el monitoreo no detiene el ciclo
        LOG.warning("monitoreo del corto plazo no disponible: %s", exc, exc_info=True)
        c.fallos.append({"etapa": "monitoreo_corto_plazo", "error": str(exc)})
        return {}
