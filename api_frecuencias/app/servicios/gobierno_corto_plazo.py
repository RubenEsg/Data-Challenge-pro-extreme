"""Ciclo de vida del modelo de corto plazo (spec v1.5 RF-018, RF-019, §9.2 «se administra su ciclo de vida», §9.5).

El modelo de 30, 60 y 120 minutos es la familia «corto_plazo» de ai_frecuencias.model_registry (migración 0016: un
activo por familia). Su ciclo de vida es el mismo del modelo horario:

- registro: cada versión del registro de artefactos (datos/modelos/corto_plazo/registro.json, el que escribe
  scripts/entrenar_corto_plazo.py) entra a model_registry como candidato, con su SHA-256 (el del manifiesto, que trae
  el de cada uno de sus 18 artefactos), su versión de variables, su fecha de corte y las cifras de su prueba reservada
  (sembrar). Si la familia no tiene activo, el activo del registro de artefactos lo es (arranque).
- evaluación: el pronóstico de la ruta en cada media hora de 04:00 a 21:00 de cada día de una ventana, con los datos
  que ya leyó la API (el panel empaquetado y lo que trajo la lectura incremental): WAPE, MAE, cobertura de la banda
  P10-P90 y sesgo, por horizonte y en conjunto (evaluar).
- compuerta: los mismos cuatro criterios que la del modelo horario (politica.compuerta) y los mismos umbrales
  versionados de threshold_config: WAPE del candidato ≤ el del activo y ≤ wape_max, cobertura P10-P90 en
  [cobertura_aviso, cobertura_max] y |sesgo| ≤ sesgo_max, los dos modelos en la MISMA ventana, que empieza después de la
  fecha de corte del candidato (compuerta). La activación y la reversión son POST /models/{model_id}/activate y POST
  /models/rollback con familia=corto_plazo (app/routers/modelos.py), auditadas en model_registry.

La fuente de verdad del modelo activo es model_registry: la API y el ciclo pasan su model_id a corto_plazo.pronosticar.
"""
from __future__ import annotations

import hashlib
from datetime import date, datetime, timedelta

import numpy as np

from . import corto_plazo as cp
from . import variables_corto_plazo as V

FAMILIA = "corto_plazo"
USUARIO_ARRANQUE = "sistema (arranque)"


def _sha256(ruta) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def ficha(model_id: str) -> dict:
    """La ficha de model_registry de una versión del registro de artefactos de corto plazo."""
    import json

    carpeta = cp.carpeta_modelos() / model_id
    manifiesto = carpeta / cp.ARCHIVO_MANIFIESTO
    man = json.loads(manifiesto.read_text(encoding="utf-8"))
    corte = date.fromisoformat(man["data_cutoff"])
    return {"model_id": model_id, "version": model_id, "tipo": "candidato",
            "artefacto": f"corto_plazo/{model_id}/{cp.ARCHIVO_MANIFIESTO}", "sha256": _sha256(manifiesto),
            "feature_version": man.get("feature_version"),
            "data_cutoff": datetime(corte.year, corte.month, corte.day, tzinfo=cp.ZONA),
            "metricas": {"prueba": man.get("metricas_prueba") or {}, "entrenado_con": man.get("entrenado_con"),
                         "artefactos": len(man.get("artefactos") or {}), "periodos": man.get("periodos")}}


def sembrar(sesion) -> int:
    """Las versiones del registro de artefactos que model_registry no tiene entran como candidatas de la familia
    corto_plazo; si la familia no tiene activo, el activo del registro de artefactos lo es. Devuelve cuántas
    entraron."""
    from sqlalchemy import select

    from app.modelos_db import RegistroModelo
    from app.servicios import ejecucion

    try:
        reg = cp.registro()
    except (OSError, ValueError):
        return 0
    modelos = list(reg.get("modelos") or {})
    if not modelos:
        return 0
    conocidos = set(sesion.scalars(select(RegistroModelo.model_id).where(RegistroModelo.model_id.in_(modelos))).all())
    nuevos = []
    for mid in modelos:
        if mid in conocidos or not (cp.carpeta_modelos() / mid / cp.ARCHIVO_MANIFIESTO).exists():
            continue
        r = ejecucion.registrar_modelo(sesion, ficha(mid), estado="candidato")
        r.familia = FAMILIA
        nuevos.append(mid)
    n = len(nuevos)
    if not n:
        return 0
    sesion.flush()
    # la activación inicial solo al registrar por primera vez el activo del registro de artefactos: si un admin lo
    # retiró después, sembrar no lo vuelve a activar
    if reg.get("activo") in nuevos and ejecucion.modelo_activo(sesion, FAMILIA) is None:
        activo = sesion.scalar(select(RegistroModelo).where(RegistroModelo.model_id == reg["activo"]))
        if activo is not None and activo.familia == FAMILIA:
            activo.estado = "activo"
            activo.aprobado_por = USUARIO_ARRANQUE
            activo.activado_en = ejecucion.ahora()
            activo.motivo = "activo del registro de artefactos de corto plazo al arrancar"
            activo.auditoria = [*(activo.auditoria or []), {"evento": "activacion_inicial",
                                                            "en": ejecucion.ahora().isoformat()}]
    sesion.commit()
    return n


def es_de_la_familia(model_id: str) -> bool:
    try:
        return model_id in (cp.registro().get("modelos") or {})
    except (OSError, ValueError):
        return False


# ----------------------------------------------------------------------------------------------- evaluación
def _ultimo_dia_con_datos() -> date:
    """El último día completo: el del panel empaquetado o el último leído entero."""
    from datetime import time as dtime

    sc = cp.serie_completa(next(iter(V.RUTAS)))
    completos = [f for f, h in sc.hasta.items() if h.astimezone(cp.ZONA).time() >= dtime(23, 59, 59)]
    return max([cp.fecha_de_dia(sc.fin_panel), *completos])


def evaluar(model_id: str, desde: date, hasta: date, horizontes: tuple = (30, 60, 120)) -> dict:
    """El modelo en una ventana de días con datos (dentro de corto_plazo.con_sesion, también lo leído): el pronóstico
    de la ruta en cada media hora de 04:00 a 21:00, frente a lo que subió en la ventana. Solo cuentan los días con
    datos y las ventanas que ya se leyeron enteras. WAPE, MAE y sesgo en %, cobertura P10-P90 en %."""
    modelo = cp.cargar(model_id)
    tot = {h: _vacio() for h in horizontes}
    ruta_tot = {V.RUTAS[i]: _vacio() for i in V.RUTAS}
    dias = 0
    d = desde
    while d <= hasta:
        dias += int(_acumular_dia(modelo["model_id"], d, horizontes, tot, ruta_tot))
        d += timedelta(days=1)
    por_h, todos = {}, _vacio()
    for h, x in tot.items():
        if not x["y"]:
            continue
        a = _unir(x)
        por_h[str(h)] = _metricas(a)
        for c in todos:
            todos[c].append(a[c])
    if not por_h:
        return {"model_id": model_id, "desde": desde, "hasta": hasta, "dias": 0, "n": 0}
    conjunto = _metricas(_unir(todos))
    por_ruta = {r: _metricas(_unir(x)) for r, x in ruta_tot.items() if x["y"]}
    return {"model_id": model_id, "desde": desde, "hasta": hasta, "dias": dias, **conjunto, "por_horizonte": por_h,
            "por_ruta": por_ruta, "nivel": "ruta",
            "nota": "pronóstico de la ruta en cada media hora de 04:00 a 21:00 de los días con datos"}


def _vacio() -> dict:
    return {"y": [], "p": [], "lo": [], "hi": []}


def _unir(x: dict) -> dict:
    return {c: np.concatenate(v) for c, v in x.items()}


def _ventanas_leidas(d: date, h: int, limite: datetime | None) -> np.ndarray:
    """Las ventanas del día que terminan antes de lo leído (todas si el día ya se leyó entero)."""
    if limite is None:
        return np.ones(len(V.INSTANTES), bool)
    fin = [datetime(d.year, d.month, d.day, b // 4, (b % 4) * 15, tzinfo=cp.ZONA) + timedelta(minutes=h)
           for b in V.INSTANTES.tolist()]
    return np.array([f <= limite for f in fin])


def _acumular_dia(model_id: str, d: date, horizontes: tuple, tot: dict, ruta_tot: dict) -> bool:
    """Suma a tot (por horizonte) y a ruta_tot (por ruta) el pronóstico y lo observado del día d de cada ruta con
    datos; True si alguna ruta lo tuvo."""
    k = cp.dia_de_fecha(d)
    usado = False
    for idruta in V.RUTAS:
        sc = cp.serie_completa(idruta)
        if not (V.ARRANQUE <= k < len(sc.ruta.cal)) or not bool(sc.ruta.ok[k]):
            continue
        limite = cp.limite_lectura(sc, d)
        for h in horizontes:
            n = cp._dia(model_id, idruta, k, h, niveles=("ruta",))["ruta"]
            vale = _ventanas_leidas(d, h, limite)
            for clave, fuente in (("y", n["y"]), ("p", n["p"]), ("lo", n["p10"]), ("hi", n["p90"])):
                tot[h][clave].append(np.asarray(fuente)[vale, 0])
                ruta_tot[V.RUTAS[idruta]][clave].append(np.asarray(fuente)[vale, 0])
            usado = True
    return usado


def _metricas(a: dict) -> dict:
    y, p = a["y"].astype(float), a["p"].astype(float)
    total = float(y.sum())
    err = np.abs(y - p)
    return {"n": int(len(y)), "wape": round(100 * float(err.sum()) / total, 3) if total else None,
            "mae": round(float(err.mean()), 3) if len(y) else None,
            "sesgo_pct": round(100 * (float(p.sum()) - total) / total, 3) if total else None,
            "cobertura_p10_p90": round(100 * float(((a["lo"] <= y) & (y <= a["hi"])).mean()), 2) if len(y) else None}


def compuerta(cand_id: str, activo_id: str | None, desde: date, hasta: date, umbrales: dict | None) -> dict:
    """Los cuatro criterios de politica.compuerta, con los mismos umbrales, para la familia corto_plazo."""
    from app.servicios import politica

    u = politica.umbrales_politica(umbrales)
    m_c = evaluar(cand_id, desde, hasta)
    m_a = evaluar(activo_id, desde, hasta) if activo_id else None
    w_c = None if m_c.get("wape") is None else float(m_c["wape"]) / 100.0
    w_a = None if not m_a or m_a.get("wape") is None else float(m_a["wape"]) / 100.0
    cob = None if m_c.get("cobertura_p10_p90") is None else float(m_c["cobertura_p10_p90"]) / 100.0
    sesgo = None if m_c.get("sesgo_pct") is None else float(m_c["sesgo_pct"]) / 100.0
    criterios = [
        {"criterio": "WAPE del candidato ≤ WAPE del activo",
         "ok": w_a is None or (w_c is not None and w_c <= w_a + 1e-12), "candidato": w_c, "referencia": w_a},
        {"criterio": f"WAPE ≤ wape_max ({u['wape_max']:.0%})", "ok": w_c is not None and w_c <= u["wape_max"],
         "candidato": w_c, "referencia": u["wape_max"]},
        {"criterio": f"cobertura P10-P90 en [{u['cobertura_aviso']:.0%}, {u['cobertura_max']:.0%}]",
         "ok": cob is not None and u["cobertura_aviso"] <= cob <= u["cobertura_max"], "candidato": cob,
         "referencia": [u["cobertura_aviso"], u["cobertura_max"]]},
        {"criterio": f"|sesgo| ≤ sesgo_max ({u['sesgo_max']:.0%})",
         "ok": sesgo is not None and abs(sesgo) <= u["sesgo_max"], "candidato": sesgo, "referencia": u["sesgo_max"]},
    ]
    return {"ventana": {"desde": desde, "hasta": hasta}, "candidato": cand_id, "activo": activo_id,
            "familia": FAMILIA, "aprobado": m_c.get("n", 0) > 0 and all(c["ok"] for c in criterios),
            "criterios": criterios, "calibracion": {"candidato": "conformal por tramo", "activo": "conformal por tramo",
                                                    "misma_version": True},
            "metricas_candidato": m_c, "metricas_activo": m_a}


def ventana(cand, desde: date | None, hasta: date | None) -> tuple[date, date, date]:
    """La ventana de la compuerta: por omisión, los 28 días que siguen a la fecha de corte del candidato, recortados al
    último día con datos. ValueError si empieza dentro de la muestra (en o antes del corte)."""
    corte = cand.data_cutoff.astimezone(cp.ZONA).date() if cand.data_cutoff else None
    d = desde or ((corte + timedelta(days=1)) if corte else None)
    if d is None:
        raise ValueError("Indique validacion_desde y validacion_hasta")
    if corte is not None and d <= corte:
        raise ValueError(f"La validación debe empezar después del {corte}: el candidato se entrenó con los datos "
                         f"hasta esa fecha")
    h = min(hasta or (d + timedelta(days=27)), _ultimo_dia_con_datos())
    return d, h, corte
