"""Ciclo de demostración completo (§14.2 de la especificación) contra la API en marcha, solo con httpx.

Pasos: registro de modelos (línea base y candidato) → ejecución incremental hasta una fecha → predicciones
30/60/120 con P10/P90, versión y explicación → recomendaciones (headway, buses/h, vehículos, viabilidad) →
alertas (estructura §5.3 y deduplicación) → ciclo de vida de una alerta con su historial → llegada de datos
nuevos (solo se leen las filas nuevas, marca de agua) con evaluación del error → reentrenamiento, comparación
y activación o rechazo con motivo → reversión → exportación CSV/XLSX.

Uso (con la API en http://127.0.0.1:8000 y la base ai_frecuencias recién migrada):
    python scripts/demo_ciclo.py --base http://127.0.0.1:8000 --salida docs/evidencias/demo_ciclo.txt
"""
from __future__ import annotations

import argparse
import collections
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import httpx

_LINEAS: list[str] = []


def log(*partes) -> None:
    texto = " ".join(str(p) for p in partes)
    _LINEAS.append(texto)
    print(texto.encode(sys.stdout.encoding or "utf-8", errors="replace").decode(sys.stdout.encoding or "utf-8"))


def esperar(c: httpx.Client, execution_id: str, limite_s: int = 900) -> dict:
    fin = time.time() + limite_s
    ultimo = None
    while time.time() < fin:
        d = c.get(f"/api/v1/frequency/executions/{execution_id}").json()
        if d["estado"] in ("ok", "error"):
            return d
        etapa = f"{d.get('etapa') or d['estado']} {float(d['progreso']):.0f} %"
        if etapa != ultimo:
            log(f"     … {etapa}")
            ultimo = etapa
        time.sleep(1)
    raise TimeoutError(execution_id)


def ejecutar(c: httpx.Client, hasta: date, etiqueta: str, instante: str | None = None) -> dict:
    t0 = time.perf_counter()
    cuerpo = {"hasta": hasta.isoformat()}
    if instante:
        cuerpo["instante"] = instante
    r = c.post("/api/v1/frequency/executions", json=cuerpo, headers={"X-Correlation-Id": f"demo-{etiqueta}"})
    r.raise_for_status()
    log(f"   POST /frequency/executions {cuerpo} -> {r.status_code} (job en segundo plano)")
    d = esperar(c, r.json()["execution_id"])
    ev = (d.get("metricas") or {}).get("evaluacion_error") or {}
    log(f"   ejecución {d['execution_id']} estado={d['estado']} en {time.perf_counter() - t0:.1f} s, intentos={d['intentos']}")
    log(f"   filas leídas={d['filas_leidas']} válidas={d['filas_validas']} errores por dimensión={d.get('errores_por_dimension')}")
    log(f"   marca de agua {d['marca_agua_anterior']} -> {d['marca_agua_nueva']}; data_cutoff={d['data_cutoff']}")
    log(f"   model_id={d['model_id']} feature_version={d['feature_version']} umbrales_version={d['umbrales_version']} "
        f"correlation_id={d['correlation_id']}")
    met = d.get("metricas") or {}
    log(f"   predicciones={d['predicciones']} recomendaciones={d['recomendaciones']} alertas={d['alertas']} "
        f"(nuevas={met.get('alertas_nuevas')}, repetidas={met.get('alertas_repetidas')}, "
        f"notificaciones simuladas={met.get('notificaciones')}, incorporadas al histórico={met.get('incorporadas_historico')})")
    if ev:
        log(f"   evaluación del modelo activo sobre lo recién llegado: {ev}")
    if d["estado"] != "ok":
        log("   MENSAJE:", d.get("mensaje"))
    return d


def _activar(c: httpx.Client, model_id: str, usuario: str, motivo: str, ventana: tuple[str, str] | None = None
             ) -> httpx.Response:
    cuerpo = {"aprobado_por": usuario, "motivo": motivo}
    if ventana:
        cuerpo |= {"validacion_desde": ventana[0], "validacion_hasta": ventana[1]}
    r = c.post(f"/api/v1/models/{model_id}/activate", json=cuerpo)
    if r.status_code == 200:
        m = r.json()
        comp = (m["metricas"] or {}).get("validacion_activacion", {})
        wc = (comp.get("candidato") or {}).get("wape")
        wa = (comp.get("activo") or {}).get("wape")
        log(f"   ACTIVADO {model_id} (anterior {m['anterior_model_id']}, aprobado_por={m['aprobado_por']}): "
            f"WAPE candidato={wc} activo={wa} en {comp.get('ventana')}")
    else:
        err = r.json().get("error", {})
        log(f"   RECHAZADO {model_id} ({r.status_code} {err.get('codigo')}): {err.get('mensaje')}")
    return r


def gobierno(c: httpx.Client, usuario: str, fallos: list[str]) -> None:
    """Activa el candidato de la entrega si mejora al activo e intenta activar una línea base peor (debe rechazarse)."""
    log("   Gobierno del modelo: activar el candidato que viaja en la entrega e intentar volver a una línea base peor")
    modelos = c.get("/api/v1/models", params={"limite": 50}).json()["items"]
    entrega = next((m for m in modelos if m["model_id"] == "hgb_fv1_20250831_s42" and m["estado"] != "activo"), None)
    if entrega:
        _activar(c, entrega["model_id"], usuario, "activación del modelo de la entrega")
    modelos = c.get("/api/v1/models", params={"limite": 50}).json()["items"]
    base = next((m for m in modelos if m["tipo"] == "linea_base" and m["estado"] != "activo"), None)
    if base:  # la línea base no tiene corte propio: se compara en la misma ventana de noviembre de 2025
        r = _activar(c, base["model_id"], usuario, "intento de volver a la regla manual",
                     ventana=("2025-11-01", "2025-11-28"))
        if r.status_code == 200:
            fallos.append("la línea base peor no se rechazó")
    for m in c.get("/api/v1/models", params={"orden": "model_id", "limite": 50}).json()["items"]:
        log(f"   registro: {m['model_id']:<28} {m['tipo']:<11} {m['estado']:<10} aprobado_por={m['aprobado_por']} "
            f"anterior={m['anterior_model_id']} motivo={m['motivo']}")
        for ev in (m.get("auditoria") or [])[-3:]:
            log(f"      auditoría: {ev}")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--base", default="http://127.0.0.1:8000")
    p.add_argument("--hasta", type=date.fromisoformat, default=date(2025, 11, 3),
                   help="corte de la primera ejecución (carga inicial)")
    p.add_argument("--corte", type=date.fromisoformat, default=date(2025, 10, 31),
                   help="corte de datos del candidato que se reentrena")
    p.add_argument("--usuario", default="comite_operacion")
    p.add_argument("--salida", type=Path, default=None)
    a = p.parse_args()
    c = httpx.Client(base_url=a.base, timeout=300)
    fallos: list[str] = []
    api = "/api/v1"

    log("=== Ciclo de demostración API de frecuencias Sobusa (§14.2) ===")
    log("0. GET /health ->", c.get("/health").json())

    log("\n1. Registro de modelos (línea base y candidato sembrados desde el manifiesto)")
    for m in c.get(f"{api}/models", params={"orden": "model_id"}).json()["items"]:
        met = m["metricas"] or {}
        log(f"   {m['model_id']:<28} tipo={m['tipo']:<11} estado={m['estado']:<9} sha256={m['sha256'][:12]}… "
            f"feature_version={m['feature_version']} corte={m['data_cutoff']} "
            f"WAPE prueba={(met.get('prueba') or {}).get('wape', met.get('wape'))}")

    log(f"\n2. Ejecución 1: llegan los datos hasta {a.hasta} (carga inicial incremental desde cero)")
    e1 = ejecutar(c, a.hasta, "carga-inicial")
    if e1["estado"] != "ok":
        fallos.append("ejecucion 1")
    errores = c.get(f"{api}/frequency/executions/{e1['execution_id']}/errors", params={"limite": 3}).json()
    log(f"   errores de calidad guardados por lote, fila y causa: total={errores['total']} muestra={errores['items'][:3]}")

    log("\n3. Predicciones de la ejecución 1 (30/60/120 min con P10/P90, versión y explicación)")
    preds = c.get(f"{api}/predictions", params={"execution_id": e1["execution_id"], "limite": 200,
                                                  "orden": "ruta"}).json()
    por_h = collections.Counter(x["horizonte_min"] for x in preds["items"])
    log(f"   total={preds['total']} por horizonte={dict(sorted(por_h.items()))} "
        f"rutas={sorted({x['ruta'] for x in preds['items']})}")
    if set(por_h) != {30, 60, 120}:
        fallos.append("horizontes de prediccion")
    for x in preds["items"][:3]:
        log(f"   {x['ruta']:<9} instante={x['instante']} h={x['horizonte_min']:>3} min objetivo={x['objetivo']} "
            f"pasajeros={x['pasajeros']:.1f} P10={x['p10']:.1f} P90={x['p90']:.1f} model_id={x['model_id']} "
            f"feature_version={x['feature_version']} data_cutoff={x['data_cutoff']}")
        log(f"      explicación: {x['explicacion'][:3]}")
    ruta0 = preds["items"][0]["ruta"] if preds["items"] else "CRA 54"
    r = c.post(f"{api}/predictions/run", json={"ruta": ruta0, "instante": f"{a.hasta + timedelta(days=1)}T07:00:00-05:00",
                                                 "horizonte_min": 60})
    if r.status_code == 201:
        x = r.json()
        rec = x.get("recomendacion") or {}
        log(f"   POST /predictions/run (en línea) {ruta0} 07:00 +60 min -> {x['pasajeros']:.1f} pasajeros "
            f"[P10 {x['p10']:.1f}, P90 {x['p90']:.1f}] en {x['latencia_ms']} ms; recomendación: "
            f"{rec.get('buses_hora')} buses/h, headway {rec.get('headway_min')} min, viable={rec.get('viable')}")
    else:
        fallos.append("predictions/run")
        log("   POST /predictions/run FALLÓ", r.status_code, r.text[:300])

    log("\n4. Recomendaciones de la ejecución 1 (§10.3)")
    recs = c.get(f"{api}/recommendations", params={"execution_id": e1["execution_id"], "limite": 200}).json()
    viables = sum(1 for x in recs["items"] if x["viable"])
    log(f"   total={recs['total']} viables={viables} no viables={recs['total'] - viables}")
    for x in recs["items"][:4]:
        log(f"   {x['ruta']:<9} {x['fecha']} {x['hora']:>2} h demanda={x['demanda_hora']} buses/h={x['buses_hora']} "
            f"headway={x['headway_min']} min vehículos={x['vehiculos_requeridos']} capacidad efectiva={x['capacidad_efectiva']} "
            f"ocupación={x['ocupacion_esperada']} viable={x['viable']} motivo={x['motivo']} "
            f"actual={x['frecuencia_actual_min']} diferencia={x['diferencia_min']}")
    r = c.post(f"{api}/recommendations/calculate", json={"ruta": "CRA 54", "hora": 7, "demanda_hora": 1200})
    if r.status_code == 201:
        x = r.json()
        log(f"   POST /recommendations/calculate CRA 54 7 h 1200 pas -> buses/h={x['buses_hora']} headway={x['headway_min']} "
            f"vehículos={x['vehiculos_requeridos']} viable={x['viable']}")
        log(f"      fórmula: {x['formula']}")
    else:
        fallos.append("recommendations/calculate")
        log("   POST /recommendations/calculate FALLÓ", r.status_code, r.text[:300])

    log("\n5. Alertas (estructura §5.3) y deduplicación")
    alertas = c.get(f"{api}/alerts", params={"limite": 200}).json()
    log(f"   abiertas tras la ejecución 1: total={alertas['total']} por código="
        f"{dict(collections.Counter(x['codigo'] for x in alertas['items']))} por severidad="
        f"{dict(collections.Counter(x['severidad'] for x in alertas['items']))}")
    alerta = alertas["items"][0] if alertas["items"] else None
    if alerta:
        campos = ["alert_id", "codigo", "ruta", "vehiculo", "detectada_en", "ventana_inicio", "ventana_fin",
                  "horizonte_min", "severidad", "estado", "observado", "esperado", "umbral", "puntaje",
                  "explicacion", "recomendacion", "clave_dedup", "ocurrencias"]
        for k in campos:
            log(f"      {k}: {alerta.get(k)}")
        log(f"      variables: {alerta.get('variables')}")
    log("   Ejecución 1-bis: mismo corte y mismo instante (sin datos nuevos, se fuerza el recálculo): las alertas "
        "repetidas no se duplican, suman ocurrencias")
    e1b = ejecutar(c, a.hasta, "repeticion", instante=f"{a.hasta + timedelta(days=1)}T06:00:00-05:00")
    alertas_b = c.get(f"{api}/alerts", params={"limite": 200}).json()
    max_oc = max((x["ocurrencias"] for x in alertas_b["items"]), default=0)
    log(f"   alertas abiertas antes={alertas['total']} después={alertas_b['total']} ocurrencias máximas={max_oc} "
        f"(filas leídas en la repetición={e1b['filas_leidas']}, filas en demanda_observada sin duplicar)")
    if alertas_b["total"] != alertas["total"] or (alertas["total"] and max_oc < 2):
        fallos.append("deduplicacion")

    if alerta:
        log("\n6. Ciclo de vida de la alerta", alerta["alert_id"], f"({alerta['codigo']} {alerta['ruta']})")
        pasos = [{"accion": "reconocer", "usuario": "despachador_1"},
                 {"accion": "asignar", "usuario": "despachador_1", "asignado_a": "supervisor_ruta",
                  "comentario": "Revisar refuerzo de la hora pico"},
                 {"accion": "cerrar", "usuario": "supervisor_ruta", "comentario": "Se programó el refuerzo"}]
        for cuerpo in pasos:
            r = c.patch(f"{api}/alerts/{alerta['alert_id']}/status", json=cuerpo)
            log(f"   PATCH {cuerpo['accion']:<9} -> {r.status_code} estado={r.json().get('estado')} "
                f"asignado_a={r.json().get('asignado_a')}")
            if r.status_code != 200:
                fallos.append(f"PATCH {cuerpo['accion']}")
        r = c.patch(f"{api}/alerts/{alerta['alert_id']}/status", json={"accion": "reconocer", "usuario": "x"})
        log(f"   transición inválida (reconocer una alerta cerrada) -> {r.status_code} {r.json().get('error', {}).get('codigo')}")
        for h in c.get(f"{api}/alerts/{alerta['alert_id']}/history").json():
            log(f"   historial: {h['creado_en']} {h['accion']:<9} {h['estado_anterior']} -> {h['estado_nuevo']} "
                f"por {h['usuario']} {h['comentario'] or ''}")

    siguiente = a.hasta + timedelta(days=1)
    log(f"\n7. Llegan datos nuevos ({siguiente}): la ejecución 2 solo lee las filas nuevas y evalúa el error")
    e2 = ejecutar(c, siguiente, "dia-siguiente")
    if e2["estado"] != "ok" or (e2["filas_leidas"] or 0) >= (e1["filas_leidas"] or 0):
        fallos.append("lectura incremental")

    log(f"\n8. Reentrenamiento: candidato con corte {a.corte}, comparación con el activo y decisión")
    r = c.post(f"{api}/models/train", json={"hasta": a.corte.isoformat(), "solicitado_por": a.usuario})
    log(f"   POST /models/train -> {r.status_code}")
    t0 = time.perf_counter()
    et = esperar(c, r.json()["execution_id"])
    log(f"   entrenamiento {et['estado']} en {time.perf_counter() - t0:.1f} s: {et['mensaje']} model_id={et['model_id']}")
    activo_antes = next((m for m in c.get(f"{api}/models").json()["items"] if m["estado"] == "activo"), None)
    if et["estado"] == "ok" and et["model_id"]:
        cand = et["model_id"]
        r = c.post(f"{api}/models/{cand}/activate", json={"aprobado_por": a.usuario,
                                                            "motivo": "ciclo de demostración §14.2"})
        if r.status_code == 200:
            m = r.json()
            comp = (m["metricas"] or {}).get("validacion_activacion", {})
            log(f"   ACTIVADO {cand} (anterior {m['anterior_model_id']}) aprobado_por={m['aprobado_por']}")
            log(f"   comparación en la misma ventana: {comp}")
            r = c.post(f"{api}/models/rollback", json={"usuario": a.usuario, "motivo": "prueba de reversión"})
            log(f"   POST /models/rollback -> {r.status_code}; activo ahora: {r.json().get('model_id')}")
            if r.status_code != 200:
                fallos.append("rollback")
        else:
            err = r.json().get("error", {})
            log(f"   RECHAZADO ({r.status_code} {err.get('codigo')}): {err.get('mensaje')} detalle={err.get('detalle')}")
    else:
        fallos.append("entrenamiento")
    gobierno(c, a.usuario, fallos)
    log(f"   (activo antes de la decisión: {activo_antes and activo_antes['model_id']})")

    log("\n9. Exportación (RF-017)")
    for ruta_exp, fmt in (("predictions", "csv"), ("recommendations", "xlsx")):
        r = c.get(f"{api}/{ruta_exp}/export", params={"formato": fmt, "execution_id": e1["execution_id"]})
        log(f"   GET /{ruta_exp}/export?formato={fmt} -> {r.status_code} {r.headers.get('content-type')} "
            f"{len(r.content)} bytes")
        if r.status_code != 200:
            fallos.append(f"export {fmt}")
        elif fmt == "csv":
            log("      " + "\n      ".join(r.text.splitlines()[:3]))
        if a.salida and r.status_code == 200:
            (a.salida.parent / f"export_{ruta_exp}.{fmt}").write_bytes(r.content)

    log("\n10. Umbrales vigentes:", {k: v for k, v in list(c.get(f"{api}/thresholds").json()["valores"].items())[:6]}, "…")
    paso_notificaciones(c, a.hasta + timedelta(days=2), fallos)
    log("\nRESULTADO:", "OK, todos los pasos cumplidos" if not fallos else f"con fallos: {fallos}")
    if a.salida:
        a.salida.parent.mkdir(parents=True, exist_ok=True)
        a.salida.write_text("\n".join(_LINEAS) + "\n", encoding="utf-8")
    return 0 if not fallos else 1


def paso_notificaciones(c: httpx.Client, hasta: date, fallos: list[str]) -> None:
    log(f"\n11. Otro día de datos ({hasta}) con los canales simulados de correo y WhatsApp activos "
        "(NOTIFICACIONES_CANALES=correo,whatsapp en docker-compose.yml)")
    d = ejecutar(c, hasta, "notificaciones")
    if d["estado"] != "ok":
        fallos.append("ejecucion con notificaciones")


def anexar_notificaciones() -> int:
    """Corre solo el paso 11 y lo agrega al final del archivo de salida (sin repetir el resto del ciclo)."""
    p = argparse.ArgumentParser()
    p.add_argument("--anexar-notificaciones", action="store_true")
    p.add_argument("--base", default="http://127.0.0.1:8000")
    p.add_argument("--hasta", type=date.fromisoformat, default=date(2025, 11, 5))
    p.add_argument("--salida", type=Path, default=None)
    a = p.parse_args()
    fallos: list[str] = []
    paso_notificaciones(httpx.Client(base_url=a.base, timeout=300), a.hasta, fallos)
    log("RESULTADO del paso 11:", "OK" if not fallos else f"con fallos: {fallos}")
    if a.salida:
        with a.salida.open("a", encoding="utf-8") as f:
            f.write("\n".join(_LINEAS) + "\n")
    return 0 if not fallos else 1


if __name__ == "__main__":
    raise SystemExit(anexar_notificaciones() if "--anexar-notificaciones" in sys.argv else main())
