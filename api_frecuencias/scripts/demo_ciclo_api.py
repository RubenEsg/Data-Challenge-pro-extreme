"""Demostración del ciclo completo de la especificación (§14.2) contra la API en marcha.

  1. llegada de información nueva (se simula por fecha: --hasta y luego el día siguiente)
  2. lectura incremental por marca de agua
  3. evaluación del error del modelo activo sobre lo recién llegado
  4. entrenamiento de un modelo candidato (job)
  5. comparación con el modelo activo en la misma validación temporal
  6. decisión de activarlo o rechazarlo (queda auditada; se puede revertir con POST /models/rollback)

Uso:  python scripts/demo_ciclo_api.py --base http://127.0.0.1:8000 --hasta 2025-08-30 --corte 2025-08-31
"""
from __future__ import annotations

import argparse
import time
from datetime import date, timedelta

import httpx


def esperar(c: httpx.Client, execution_id: str, limite_s: int = 900) -> dict:
    fin = time.time() + limite_s
    while time.time() < fin:
        d = c.get(f"/api/v1/frequency/executions/{execution_id}").json()
        if d["estado"] in ("ok", "error"):
            return d
        print(f"   ... {d['etapa'] or d['estado']} {float(d['progreso']):.0f} %")
        time.sleep(2)
    raise TimeoutError(execution_id)


def ejecutar(c: httpx.Client, hasta: date) -> dict:
    r = c.post("/api/v1/frequency/executions", json={"hasta": hasta.isoformat()},
               headers={"X-Correlation-Id": f"demo-{hasta.isoformat()}"})
    r.raise_for_status()
    d = esperar(c, r.json()["execution_id"])
    ev = (d["metricas"] or {}).get("evaluacion_error") or {}
    print(f"   ejecución {d['execution_id']} {d['estado']}: filas leídas {d['filas_leidas']}, válidas "
          f"{d['filas_validas']}, marca {d['marca_agua_anterior']} -> {d['marca_agua_nueva']}")
    print(f"   predicciones {d['predicciones']}, recomendaciones {d['recomendaciones']}, alertas {d['alertas']}, "
          f"WAPE del activo sobre lo nuevo: {ev.get('wape')}")
    return d


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--base", default="http://127.0.0.1:8000")
    p.add_argument("--hasta", type=date.fromisoformat, default=date(2025, 8, 30))
    p.add_argument("--corte", type=date.fromisoformat, default=date(2025, 8, 31))
    p.add_argument("--aprobado-por", default="comite_operacion")
    a = p.parse_args()
    c = httpx.Client(base_url=a.base, timeout=120)
    print("0. estado:", c.get("/health").json())
    print("1-3. carga inicial, llegada del día siguiente y repetición sin datos nuevos")
    ejecutar(c, a.hasta)
    ejecutar(c, a.hasta + timedelta(days=1))
    ejecutar(c, a.hasta + timedelta(days=1))
    print("4. entrenamiento de un candidato con corte", a.corte)
    r = c.post("/api/v1/models/train", json={"hasta": a.corte.isoformat(), "solicitado_por": a.aprobado_por})
    r.raise_for_status()
    e = esperar(c, r.json()["execution_id"])
    print("   ", e["estado"], e["mensaje"])
    if e["estado"] != "ok":
        return
    candidato = e["model_id"]
    print("5-6. comparación con el activo y decisión")
    r = c.post(f"/api/v1/models/{candidato}/activate", json={"aprobado_por": a.aprobado_por,
                                                              "motivo": "ciclo de demostración §14.2"})
    if r.status_code == 200:
        m = r.json()
        comp = m["metricas"].get("validacion_activacion", {})
        wape_activo = (comp.get("activo") or {}).get("wape")
        print(f"   ACTIVADO {candidato} (anterior {m['anterior_model_id']}); WAPE candidato "
              f"{comp.get('candidato', {}).get('wape')} vs activo {wape_activo} en {comp.get('ventana')}")
    else:
        err = r.json()["error"]
        print(f"   RECHAZADO ({r.status_code} {err['codigo']}): {err['mensaje']}")
    print("   registro:", [(m["model_id"], m["estado"]) for m in c.get("/api/v1/models").json()["items"]])


if __name__ == "__main__":
    main()
