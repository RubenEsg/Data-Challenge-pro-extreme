"""Pronóstico en lote frente a hora por hora (inferencia.predecir_horas frente a predecir), sin base de datos.

Para cada ruta, las 17 horas de servicio (4 a 20 h) de un día: compara los diccionarios (deben ser idénticos salvo
generated_at y latencia_ms) y mide el tiempo con el modelo ya cargado (mediana de varias repeticiones). Escribe
docs/evidencias/modelo/predecir_horas_lote.json.

Uso: python scripts/evaluar_lote_inferencia.py [--fecha 2025-12-18] [--repeticiones 5]
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from app.servicios import datos, inferencia  # noqa: E402

SALIDA = RAIZ / "docs" / "evidencias" / "modelo" / "predecir_horas_lote.json"
ZONA = ZoneInfo("America/Bogota")
IGNORADAS = ("generated_at", "latencia_ms")


def _sin_tiempos(r: dict) -> dict:
    return {k: v for k, v in r.items() if k not in IGNORADAS}


def medir(ruta: str, fecha: date, repeticiones: int) -> dict:
    inicios = [datetime(fecha.year, fecha.month, fecha.day, h, tzinfo=ZONA) for h in datos.HORAS_SERVICIO]
    lote = inferencia.predecir_horas(ruta, inicios)
    uno = [inferencia.predecir(ruta, i, 60, usar_nowcast=False) for i in inicios]
    iguales = all(_sin_tiempos(a) == _sin_tiempos(b) for a, b in zip(lote, uno, strict=True))
    t_lote, t_uno = [], []
    for _ in range(repeticiones):
        t0 = time.perf_counter()
        inferencia.predecir_horas(ruta, inicios)
        t_lote.append(time.perf_counter() - t0)
        t0 = time.perf_counter()
        for i in inicios:
            inferencia.predecir(ruta, i, 60, usar_nowcast=False)
        t_uno.append(time.perf_counter() - t0)
    return {"ruta": ruta, "horas": len(inicios), "identicos_hora_por_hora": iguales,
            "segundos_lote_mediana": round(statistics.median(t_lote), 4),
            "segundos_hora_por_hora_mediana": round(statistics.median(t_uno), 4),
            "aceleracion": round(statistics.median(t_uno) / max(statistics.median(t_lote), 1e-9), 2)}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--fecha", type=date.fromisoformat, default=date(2025, 12, 18))
    ap.add_argument("--repeticiones", type=int, default=5)
    a = ap.parse_args()
    inferencia.precalentar()
    filas = [medir(r, a.fecha, a.repeticiones) for r in datos.nombres_rutas()]
    salida = {"modelo": inferencia.modelo_activo(), "fecha": str(a.fecha), "repeticiones": a.repeticiones,
              "generado_en": datetime.now(ZONA).isoformat(timespec="seconds"),
              "script": "scripts/evaluar_lote_inferencia.py",
              "nota": ("ventana de 60 min al inicio de cada hora, sin factor intradía (como el contexto de las alertas "
                       "observadas y el plan del día); el lote llama una vez a los tres modelos y a SHAP"),
              "rutas": filas}
    SALIDA.write_text(json.dumps(salida, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(salida, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
