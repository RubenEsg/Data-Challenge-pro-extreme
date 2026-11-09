"""Evidencia P8+P10: API real (uvicorn :8102) con AUTH_HABILITADA=true y OTEL_EXPORTADOR=otlp hacia Jaeger (:4318),
una ejecución por la cola (hilo trabajador) y la traza leída de la API de Jaeger. Base: la de pruebas LOCAL
ai_frecuencias_pruebas_seguridad (nunca la del reto). Las claves se generan aquí y no se guardan."""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import subprocess
import sys
import time
from pathlib import Path

import httpx

API = Path(r"D:\Ruben\universidad\machine_learning\DATA CHALLENGE\EntregaFinal\api_frecuencias")
EVID = API / "docs" / "evidencias" / "seguridad"
PY = API / ".venv" / "Scripts" / "python.exe"
BASE = "http://127.0.0.1:8102"
JAEGER = "http://127.0.0.1:16686"


def url_pruebas() -> str:
    sys.path.insert(0, str(API))
    from sqlalchemy.engine import make_url

    from app.config import Ajustes

    return make_url(Ajustes().database_url).set(database="ai_frecuencias_pruebas_seguridad").render_as_string(
        hide_password=False)


def main() -> None:
    claves = {rol: secrets.token_urlsafe(32) for rol in ("operador", "analista", "admin")}
    env = dict(os.environ)
    env.update(DATABASE_URL=url_pruebas(), AUTH_HABILITADA="true", ENTORNO="demo", OTEL_EXPORTADOR="otlp",
               OTEL_EXPORTER_OTLP_ENDPOINT="http://127.0.0.1:4318", OTEL_SERVICE_NAME="api-frecuencias",
               REANUDAR_EJECUCIONES="true", TRABAJADORES="1", TRABAJADOR_ID="replica-evidencia",
               PLANIFICADOR_HABILITADO="false", PYTHONIOENCODING="utf-8", MAX_REINTENTOS="1",
               API_KEYS=json.dumps({hashlib.sha256(c.encode()).hexdigest(): {"usuario": f"evid_{r}", "rol": r}
                                    for r, c in claves.items()}))
    for k in ("SOBUSA_API_KEY", "API_KEY_OPERADOR", "API_KEY_ANALISTA", "API_KEY_ADMIN"):
        env.pop(k, None)
    salida = open(EVID / "log_api_evidencia_jaeger.txt", "w", encoding="utf-8")
    proc = subprocess.Popen([str(PY), "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8102"],  # noqa: S603
                            cwd=API, env=env, stdout=salida, stderr=subprocess.STDOUT)
    try:
        for _ in range(120):
            try:
                if httpx.get(f"{BASE}/health", timeout=2).status_code in (200, 503):
                    break
            except httpx.HTTPError:
                time.sleep(0.5)
        informe = []
        sin = httpx.get(f"{BASE}/api/v1/alerts", timeout=10)
        op = httpx.post(f"{BASE}/api/v1/frequency/executions", json={}, timeout=10,
                        headers={"X-API-Key": claves["operador"]})
        informe.append(f"GET /api/v1/alerts sin clave -> {sin.status_code} {sin.json()['error']['codigo']}")
        informe.append(f"POST /api/v1/frequency/executions con operador -> {op.status_code} "
                       f"{op.json()['error']['codigo']} {op.json()['error']['detalle']}")
        c = httpx.Client(base_url=BASE, timeout=60, headers={"X-API-Key": claves["analista"]})
        r = c.post("/api/v1/frequency/executions", headers={"X-Correlation-Id": "evid-jaeger-1"},
                   json={"hasta": "2025-03-05", "instante": "2025-03-05T07:00:00-05:00",
                         "rutas": ["CRA 54"], "horizontes": [60]})
        informe.append(f"POST /api/v1/frequency/executions con analista -> {r.status_code}")
        eid = r.json()["execution_id"]
        estado = {}
        for _ in range(240):
            estado = c.get(f"/api/v1/frequency/executions/{eid}").json()
            if estado["estado"] in ("ok", "error"):
                break
            time.sleep(1)
        informe.append(f"ejecución {eid}: estado={estado.get('estado')} etapa={estado.get('etapa')} "
                       f"worker_id={estado.get('worker_id')} mensaje={estado.get('mensaje')}")
        time.sleep(8)                                   # el BatchSpanProcessor exporta cada 5 s
        trace_id = None
        salida.flush()
        for x in Path(salida.name).read_text(encoding="utf-8").splitlines():
            if x.startswith("{") and json.loads(x).get("execution_id") == eid and json.loads(x).get("trace_id"):
                trace_id = json.loads(x)["trace_id"]
                break
        traza = {}
        for _ in range(10):                             # Jaeger 2.x: API v3 (OTLP JSON)
            resp = httpx.get(f"{JAEGER}/api/v3/traces/{trace_id}", timeout=10)
            if resp.status_code == 200:
                traza = resp.json()
                break
            time.sleep(2)
        (EVID / "jaeger_traza_ejecucion.json").write_text(json.dumps(traza, ensure_ascii=False, indent=1),
                                                          encoding="utf-8")
        spans = [s for r in traza.get("result", {}).get("resourceSpans", []) for ss in r["scopeSpans"]
                 for s in ss["spans"]]
        informe.append(f"traza {trace_id} en Jaeger: {len(spans)} spans")
        informe.append("raíz: " + ", ".join(s["name"] for s in spans if not s.get("parentSpanId")))
        informe.append("etapas: " + ", ".join(sorted(s["name"] for s in spans if s["name"].startswith("ejecucion."))))
        (EVID / "jaeger_resumen.txt").write_text("\n".join(informe) + "\n", encoding="utf-8")
        print("\n".join(informe))
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            proc.kill()
        salida.close()


if __name__ == "__main__":
    main()
