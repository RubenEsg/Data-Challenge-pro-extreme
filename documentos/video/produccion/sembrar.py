"""Siembra la API aislada (8371) con un ciclo corto de demostración: tres ejecuciones diarias (carga inicial y días
nuevos), un candidato entrenado con datos_hasta (queda en sombra) y deja un resumen en sembrar.json.
Uso: python sembrar.py [--sin-entrenar]"""
import json
import sys
import time
from pathlib import Path

import httpx

AQUI = Path(__file__).resolve().parent
CLAVES = json.loads((AQUI / "claves.json").read_text(encoding="utf-8"))
c = httpx.Client(base_url="http://127.0.0.1:8371", timeout=600, headers={"X-API-Key": CLAVES["admin"]})
resumen = {"ejecuciones": []}


def esperar(eid, limite=1500):
    fin = time.time() + limite
    while time.time() < fin:
        d = c.get(f"/api/v1/frequency/executions/{eid}").json()
        if d["estado"] in ("ok", "error"):
            return d
        time.sleep(3)
    raise TimeoutError(eid)


def ejecutar(hasta):
    t = time.time()
    r = c.post("/api/v1/frequency/executions", json={"hasta": hasta})
    r.raise_for_status()
    d = esperar(r.json()["execution_id"])
    m = d.get("metricas") or {}
    fila = {"hasta": hasta, "execution_id": d["execution_id"], "estado": d["estado"], "mensaje": d.get("mensaje"),
            "filas_leidas": d.get("filas_leidas"), "filas_validas": d.get("filas_validas"),
            "marca_agua_anterior": d.get("marca_agua_anterior"), "marca_agua_nueva": d.get("marca_agua_nueva"),
            "predicciones": m.get("predicciones"), "recomendaciones": m.get("recomendaciones"),
            "alertas": m.get("alertas_nuevas"), "segundos": round(time.time() - t, 1)}
    resumen["ejecuciones"].append(fila)
    print(json.dumps(fila, ensure_ascii=False), flush=True)
    return d


print(c.get("/health").json(), flush=True)
for dia in ("2025-09-01", "2025-09-02", "2025-09-03"):
    ejecutar(dia)
if "--sin-entrenar" not in sys.argv:
    t = time.time()
    r = c.post("/api/v1/models/train", json={"hasta": "2025-07-03", "datos_hasta": "2025-09-03",
                                             "solicitado_por": "analista.planeacion"})
    print("entrenar", r.status_code, r.text[:300], flush=True)
    if r.status_code < 300:
        d = esperar(r.json()["execution_id"], 1500)
        resumen["entrenamiento"] = {"estado": d["estado"], "mensaje": d.get("mensaje"), "model_id": d.get("model_id"),
                                    "segundos": round(time.time() - t, 1)}
        print("entrenamiento", json.dumps(resumen["entrenamiento"], ensure_ascii=False), flush=True)
pol = c.get("/api/v1/monitoring/policy").json()
resumen["politica"] = pol
print("politica", json.dumps(pol, ensure_ascii=False)[:800], flush=True)
(AQUI / "sembrar.json").write_text(json.dumps(resumen, ensure_ascii=False, indent=1), encoding="utf-8")
