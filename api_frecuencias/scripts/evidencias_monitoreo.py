"""Evidencias del monitoreo (§9.4) y de la política (RF-018/RF-019) en docs/evidencias/monitoreo/ (sin base de datos).

- psi_dia_lag7.json: por qué dia_lag7 no dispara el reentrenamiento (PSI frente al año de referencia, frente a la
  misma ventana del año anterior, ruido de 28 días al azar y de ventanas contiguas dentro de la propia referencia).
- monitoreo_2025.json: el monitoreo del modelo activo cada 7 días de sep a dic de 2025 (posterior a su corte), con la
  calibración de la banda que midió cada fila (calibracion_version) y la hora de generación.
- compuerta_ejemplo.json: la compuerta de cuatro criterios aplicada a fv1 (retador) frente a fv2 (activo) en 14 días
  de septiembre de 2025, FUERA de la prueba reservada (nov-dic 2025).

Uso:  python scripts/evidencias_monitoreo.py
"""
from __future__ import annotations

import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))
SALIDA = RAIZ / "docs" / "evidencias" / "monitoreo"


def psi_dia_lag7() -> dict:
    from app.servicios import inferencia, monitoreo

    t = inferencia._filas_utiles(inferencia.tabla_variables())
    corte = date(2025, 8, 31)
    ref = t[(t["fecha"] > corte - timedelta(days=365)) & (t["fecha"] <= corte)]
    r = {v: monitoreo.referencia(ref[v]) for v in ("dia_lag7", "lag7", "nivel_7_34")}
    rng = np.random.default_rng(0)
    dias = sorted(ref["fecha"].unique())
    azar = [monitoreo.psi(r["dia_lag7"], ref[ref["fecha"].isin(set(rng.choice(dias, 28, replace=False)))]["dia_lag7"])
            for _ in range(50)]
    contiguas = []
    a = corte - timedelta(days=364)
    while a + timedelta(days=28) <= corte + timedelta(days=1):
        m = (ref["fecha"] >= a) & (ref["fecha"] < a + timedelta(days=28))
        contiguas.append({"desde": str(a), "psi": round(monitoreo.psi(r["dia_lag7"], ref[m]["dia_lag7"]), 3)})
        a += timedelta(days=28)
    ventanas = []
    for ini in (date(2025, 9, 1), date(2025, 10, 1), date(2025, 11, 1), date(2025, 12, 1)):
        cur = t[(t["fecha"] >= ini) & (t["fecha"] < ini + timedelta(days=28))]
        r0 = ini - timedelta(days=364)
        est = t[(t["fecha"] >= r0) & (t["fecha"] < r0 + timedelta(days=28))]
        ventanas.append({
            "ventana": f"{ini} + 28 días",
            "psi_vs_anio_referencia": {v: round(monitoreo.psi(r[v], cur[v]), 3) for v in r},
            "psi_dia_lag7_vs_misma_ventana_anio_anterior": round(
                monitoreo.psi(monitoreo.referencia(est["dia_lag7"]), cur["dia_lag7"]), 3),
            "psi_dia_lag7_una_fila_por_ruta_y_dia": round(monitoreo.psi(
                monitoreo.referencia(ref.drop_duplicates(["ruta", "fecha"])["dia_lag7"]),
                cur.drop_duplicates(["ruta", "fecha"])["dia_lag7"]), 3)})
    return {
        "referencia": f"{ref['fecha'].min()} a {ref['fecha'].max()} (365 días de entrenamiento del modelo activo)",
        "ventanas_2025": ventanas,
        "ruido_28_dias_al_azar_de_la_referencia": {"p50": round(float(np.median(azar)), 3),
                                                   "p95": round(float(np.quantile(azar, 0.95)), 3)},
        "ventanas_contiguas_dentro_de_la_referencia": {
            "p50": round(float(np.median([c["psi"] for c in contiguas])), 3),
            "max": max(c["psi"] for c in contiguas), "detalle": contiguas},
        "conclusion": ("dia_lag7 es diaria (una por ruta y día, repetida en 17 horas), "
                       "autocorrelacionada y estacional: "
                       "28 días contiguos solo ven una estación, y dentro del MISMO año de entrenamiento ya dan PSI de "
                       "hasta 1,6, mientras 28 días al azar dan ~0,08. No es un error de datos ni de granularidad "
                       "horaria (una fila por día da lo mismo) y tampoco se corrige con la misma ventana del año "
                       "anterior. Se reporta con su umbral calibrado (p95 del ruido contiguo) y NO dispara el "
                       "reentrenamiento; las variables horarias (lag7, b8, m4, nivel_7_34) sí, con el umbral fijo."),
    }


def monitoreo_2025() -> dict:
    from app.servicios import inferencia, monitoreo

    mid = inferencia.modelo_activo()
    filas = []
    d = date(2025, 9, 28)
    while d <= date(2025, 12, 31):
        m = monitoreo.calcular(mid, d, {"wape_max": 0.20})
        estado, motivos = monitoreo.estado_de(m, {"wape_max": 0.20})
        filas.append({"hasta": str(d), "wape_movil": m["wape_movil"], "mae_movil": m["mae_movil"],
                      "sesgo_pct": m["sesgo_pct"], "cobertura_p10_p90": m["cobertura_p10_p90"],
                      "calibracion_version": m.get("calibracion_version"),
                      "psi_max": m["psi_max"], "psi_variable_max": m["psi_variable_max"],
                      "psi_dia_lag7": m["psi"]["dia_lag7"]["psi"],
                      "umbral_dia_lag7": m["psi"]["dia_lag7"]["umbral_alerta"],
                      "wape_por_ruta": m["wape_por_ruta"], "estado": estado, "motivos": motivos})
        d += timedelta(days=7)
    versiones = sorted({str(f["calibracion_version"]) for f in filas})
    coberturas = [f["cobertura_p10_p90"] for f in filas if f["cobertura_p10_p90"] is not None]
    return {"model_id": mid, "ventana_dias": 28, "generado_en": _ahora(), "script": "scripts/evidencias_monitoreo.py",
            "calibracion_version": versiones[0] if len(versiones) == 1 else versiones,
            "origen_datos": "serie empaquetada (datos/demanda_horaria.parquet), sin base de datos",
            "cobertura_p10_p90_rango": [min(coberturas), max(coberturas)] if coberturas else None,
            "nota": ("monitoreo semanal posterior al corte del modelo (2025-08-31); de noviembre en adelante cae en la "
                     "prueba reservada, que aquí solo se reporta (no decide nada)"),
            "filas": filas,
            "estados": {e: sum(f["estado"] == e for f in filas) for e in ("ok", "aviso", "alerta")}}


def _ahora() -> str:
    return datetime.now(ZoneInfo("America/Bogota")).isoformat(timespec="seconds")


VENTANA_COMPUERTA = (date(2025, 9, 1), date(2025, 9, 14))


def compuerta() -> dict:
    """La compuerta en 14 días de septiembre de 2025: fuera de la prueba reservada (nov-dic), pero dentro de la
    validación de los dos modelos (corte 2025-08-31 + 61 días), con la que se ajustó su banda. Por eso es un ejemplo
    del cálculo de los cuatro criterios, no una decisión fuera de muestra: en producción la sombra usa los días
    posteriores a lo que vio el candidato y POST /models/{id}/activate rechaza esta ventana (422)."""
    from app.servicios import politica

    c = politica.compuerta("hgb_fv1_20250831_s42", "hgb_fv2_20250831_s42", *VENTANA_COMPUERTA, {"wape_max": 0.20})
    return {**c, "generado_en": _ahora(), "script": "scripts/evidencias_monitoreo.py (compuerta)",
            "nota": ("ventana 2025-09-01 a 2025-09-14: no toca la prueba reservada (2025-11-01 a 2025-12-31); cae en "
                     "la validación de ambos modelos (2025-09-01 a 2025-10-31), así que ilustra el cálculo de los "
                     "cuatro criterios y no es una evaluación fuera de muestra. La compuerta real se aplica en la "
                     "ventana de sombra, posterior a todo lo que vio el candidato.")}


def main() -> None:
    from app.servicios.ejecucion import json_seguro

    SALIDA.mkdir(parents=True, exist_ok=True)
    for nombre, f in (("psi_dia_lag7.json", psi_dia_lag7), ("monitoreo_2025.json", monitoreo_2025),
                      ("compuerta_ejemplo.json", compuerta)):
        (SALIDA / nombre).write_text(json.dumps(json_seguro(f()), ensure_ascii=False, indent=2), encoding="utf-8")
        print("escrito", SALIDA / nombre)


if __name__ == "__main__":
    main()
