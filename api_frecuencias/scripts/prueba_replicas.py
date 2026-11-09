"""RNF-005 · dos réplicas de la API comparten un lote de ejecuciones sin duplicarlas (y planificador con 2 réplicas).

1. Arranca dos réplicas (por omisión :8103 y :8104) sobre la MISMA base local, cada una con su identidad.
2. Envía N ejecuciones (un día nuevo cada una), alternando la réplica que recibe el POST.
3. Espera a que todas terminen y cuenta en la base: quién procesó cada una (execution_attempt), intentos 'ok' por
   ejecución (= 1), predicciones por ejecución sin duplicados, marca de agua contigua (ningún lote perdido ni
   leído dos veces) y claves únicas en demanda_observada.
4. Opcional (--planificador-minutos M): reinicia las dos réplicas con PLANIFICADOR_HABILITADO=true y
   PLAN_EJECUCION_CRON='*/1 * * * *' durante M minutos y comprueba que hay UNA ejecución por franja.

Uso:  python scripts/prueba_replicas.py --base-datos ai_frecuencias_pruebas_cola --n 20 \
          --salida docs/evidencias/cola/replicas.txt [--planificador-minutos 3]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cola_servidor import RAIZ, Cliente, Replica, lineas_de_log, motor, preparar_base, url_local  # noqa: E402
from sqlalchemy import text  # noqa: E402

E = "ai_frecuencias"
_LINEAS: list[str] = []


def log(*partes) -> None:
    linea = " ".join(str(p) for p in partes)
    _LINEAS.append(linea)
    print(linea, flush=True)


def fecha_inicial(m, n: int):
    from app.servicios import datos

    primera, ultima = datos.rango_fechas()
    with m.connect() as c:
        marca = c.execute(text(f"SELECT max(marca_agua_nueva) FROM {E}.execution_log "  # nosec B608  # identificadores de constantes del script; valores por parámetro
                               "WHERE tipo = 'frecuencia' AND estado = 'ok'")).scalar()
    d0 = (marca.date() + timedelta(days=1)) if marca else primera + timedelta(days=6)
    if d0 + timedelta(days=n) > ultima:
        raise SystemExit(f"No quedan {n} días nuevos tras la marca {marca} (datos hasta {ultima})")
    return d0


def lote(m, a, A: Replica, B: Replica) -> list[str]:
    clientes = [Cliente(A.puerto), Cliente(B.puerto)]
    d0 = fecha_inicial(m, a.n)
    ids, t0 = [], time.time()
    for i in range(a.n):
        r = clientes[i % 2].pedir("POST", "/api/v1/frequency/executions",
                                  {"hasta": (d0 + timedelta(days=i)).isoformat()}, cid=f"replicas-{i:02d}")
        ids.append(r["execution_id"])
    log(f"{a.n} ejecuciones enviadas en {time.time() - t0:.1f} s (POST alternado: {a.n // 2 + a.n % 2} a "
        f":{A.puerto}, {a.n // 2} a :{B.puerto}); días {d0} … {d0 + timedelta(days=a.n - 1)}")
    fin = time.time() + a.limite
    while time.time() < fin:
        with m.connect() as c:
            pendientes = c.execute(text(f"SELECT count(*) FROM {E}.execution_log WHERE execution_id = "  # nosec B608  # identificadores de constantes del script; valores por parámetro
                                        "ANY(CAST(:ids AS uuid[])) AND estado NOT IN ('ok', 'error')"),
                                   {"ids": ids}).scalar()
        if not pendientes:
            break
        time.sleep(0.5)
    log(f"Lote terminado en {time.time() - t0:.1f} s")
    return ids


def _hora(x) -> str:
    return "(sin marca)      " if x is None else f"{x:%Y-%m-%d %H:%M}"


def informe_lote(m, ids: list[str]) -> list[str]:
    fallas = []
    with m.connect() as c:
        filas = c.execute(text(f"""
            SELECT e.execution_id, e.estado, e.intentos, e.filas_leidas, e.marca_agua_anterior, e.marca_agua_nueva,
                   e.terminado_en, e.parametros ->> 'hasta' AS hasta,
                   (SELECT count(*) FROM {E}.prediction p WHERE p.execution_id = e.execution_id) AS pred,
                   (SELECT count(DISTINCT (p.ruta, p.instante, p.horizonte_min)) FROM {E}.prediction p
                     WHERE p.execution_id = e.execution_id) AS pred_distintas,
                   (SELECT count(*) FROM {E}.execution_attempt t WHERE t.execution_id = e.execution_id) AS intentos_t,
                   (SELECT count(*) FROM {E}.execution_attempt t WHERE t.execution_id = e.execution_id
                       AND t.resultado = 'ok') AS ok_t,
                   (SELECT split_part(t.worker_id, ':', 1) FROM {E}.execution_attempt t
                     WHERE t.execution_id = e.execution_id AND t.resultado = 'ok') AS replica
              FROM {E}.execution_log e WHERE e.execution_id = ANY(CAST(:ids AS uuid[]))
             ORDER BY e.terminado_en"""), {"ids": ids}).all()  # nosec B608  # {E} es la constante ESQUEMA
        n_dem, n_dist = c.execute(text(f"SELECT count(*), count(DISTINCT (ruta, fecha, hora)) "  # nosec B608  # identificadores de constantes del script; valores por parámetro
                                       f"FROM {E}.demanda_observada")).one()
    log("\n hasta       réplica        estado intentos filas_leídas predicciones  marca anterior -> marca nueva")
    for f in filas:
        log(f" {f.hasta}  {f.replica or '-':<14} {f.estado:<6} {f.intentos:>8} {f.filas_leidas or 0:>12} "
            f"{f.pred:>12}  {_hora(f.marca_agua_anterior)} -> {_hora(f.marca_agua_nueva)}")
    por_replica = Counter(f.replica for f in filas)
    contiguas = all(filas[i].marca_agua_anterior == filas[i - 1].marca_agua_nueva for i in range(1, len(filas)))
    orden_hasta = [f.hasta for f in filas] == sorted(f.hasta for f in filas)
    reglas = [
        (f"{len(ids)} de {len(ids)} terminadas ok", Counter(f.estado for f in filas) == Counter({"ok": len(ids)})),
        ("exactamente un intento 'ok' por ejecución (0 duplicados)", all(f.ok_t == 1 for f in filas)),
        ("un solo intento por ejecución (nadie la tomó dos veces)",
         all(f.intentos_t == 1 == f.intentos for f in filas)),
        ("las dos réplicas procesaron trabajo",
         len([r for r in por_replica if r]) == 2),
        ("predicciones sin duplicados en cada ejecución", all(f.pred == f.pred_distintas > 0 for f in filas)),
        ("marca de agua contigua: ningún lote perdido ni leído dos veces", contiguas),
        ("se procesaron en el orden de llegada de los datos", orden_hasta),
        (f"demanda_observada: {n_dem} filas = {n_dist} claves distintas", n_dem == n_dist),
    ]
    log(f"\nReparto por réplica (intento 'ok'): {dict(por_replica)}")
    log(f"Total de intentos: {sum(f.intentos_t for f in filas)}; ejecuciones: {len(filas)}; "
        f"duplicados: {sum(max(0, f.ok_t - 1) for f in filas)}")
    for regla, ok in reglas:
        log(f"   [{'OK' if ok else 'FALLA'}] {regla}")
        if not ok:
            fallas.append(regla)
    return fallas


def planificador(m, a, url) -> list[str]:
    log(f"\nPlanificador con 2 réplicas: PLAN_EJECUCION_CRON='*/1 * * * *' durante {a.planificador_minutos} min")
    entorno = {"PLANIFICADOR_HABILITADO": "true", "PLAN_EJECUCION_CRON": "*/1 * * * *",
               "PLAN_REENTRENAMIENTO_CRON": "0 4 * * 1", "SONDEO_COLA_SEGUNDOS": "0.5"}
    A = Replica("replica-8103", a.puerto_a, url, a.logs, **entorno)
    B = Replica("replica-8104", a.puerto_b, url, a.logs, **entorno)
    inicio = datetime.now().astimezone()
    try:
        A.arrancar()
        B.arrancar()
        time.sleep(a.planificador_minutos * 60 + 5)
        estado = Cliente(A.puerto).pedir("GET", "/api/v1/scheduler")
        fin = time.time() + 300
        while time.time() < fin:  # deja terminar lo que el planificador encoló
            with m.connect() as c:
                if not c.execute(text(f"SELECT count(*) FROM {E}.execution_log WHERE programada_para >= :i "  # nosec B608  # identificadores de constantes del script; valores por parámetro
                                      "AND estado IN ('en_cola', 'corriendo')"), {"i": inicio}).scalar():
                    break
            time.sleep(1)
    finally:
        A.parar()
        B.parar()
    with m.connect() as c:
        filas = c.execute(text(f"""
            SELECT e.programada_para, e.estado, e.filas_leidas, e.worker_id,
                   (SELECT split_part(t.worker_id, ':', 1) FROM {E}.execution_attempt t
                     WHERE t.execution_id = e.execution_id ORDER BY t.intento DESC LIMIT 1) AS replica,
                   e.metricas ->> 'predicciones' AS pred, e.metricas ->> 'nota' AS nota
              FROM {E}.execution_log e WHERE e.programada_para >= :i ORDER BY e.programada_para"""),  # nosec B608  # {E} es la constante ESQUEMA
                          {"i": inicio}).all()
        por_franja = c.execute(text(f"SELECT programada_para, count(*) FROM {E}.execution_log "  # nosec B608  # identificadores de constantes del script; valores por parámetro
                                    "WHERE programada_para >= :i GROUP BY 1 HAVING count(*) > 1"),
                               {"i": inicio}).all()
    for f in filas:
        log(f"   franja {f.programada_para:%H:%M}  réplica={f.replica}  estado={f.estado}  filas_leidas="
            f"{f.filas_leidas}  predicciones={f.pred}  {f.nota or ''}")
    log(f"   GET /api/v1/scheduler (réplica A): trabajos={json.dumps(estado['trabajos'], ensure_ascii=False)}")
    lineas = []
    for r in (A, B):
        lineas += [f"{r.nombre}: {x}" for x in lineas_de_log(r.log_path, ("planificador: franja",))]
    for x in lineas[-8:]:
        log(f"   log {x}")
    reglas = [(f"{len(filas)} franjas encoladas (una por minuto)", len(filas) >= a.planificador_minutos),
              ("ninguna franja encolada dos veces", not por_franja),
              ("todas terminadas ok", all(f.estado == "ok" for f in filas))]
    fallas = []
    for regla, ok in reglas:
        log(f"   [{'OK' if ok else 'FALLA'}] {regla}")
        if not ok:
            fallas.append(regla)
    return fallas


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--base-datos", default="ai_frecuencias_pruebas_cola")
    p.add_argument("--puerto-a", type=int, default=8103)
    p.add_argument("--puerto-b", type=int, default=8104)
    p.add_argument("--n", type=int, default=20)
    p.add_argument("--limite", type=float, default=1200)
    p.add_argument("--planificador-minutos", type=int, default=0)
    p.add_argument("--salida", type=Path)
    p.add_argument("--logs", type=Path, default=RAIZ / "reportes" / "tmp" / "replicas")
    a = p.parse_args()
    url = url_local(a.base_datos)
    preparar_base(url)
    m = motor(url)
    log(f"RNF-005 · dos réplicas comparten la cola {time.strftime('%Y-%m-%d %H:%M:%S')} (base local {a.base_datos})")
    with m.begin() as c:
        log("Filas pendientes limpiadas antes de empezar: " + str(c.execute(text(
            f"UPDATE {E}.execution_log SET estado = 'error', worker_id = NULL, lease_hasta = NULL, mensaje = "  # nosec B608  # identificadores de constantes del script; valores por parámetro
            "'limpieza previa a la prueba de réplicas' WHERE estado IN ('en_cola', 'corriendo')")).rowcount))
    fallas: list[str] = []
    if a.n:
        A = Replica("replica-8103", a.puerto_a, url, a.logs, SONDEO_COLA_SEGUNDOS="0.5")
        B = Replica("replica-8104", a.puerto_b, url, a.logs, SONDEO_COLA_SEGUNDOS="0.5")
        try:
            log(f"Réplica A (:{a.puerto_a}) arrancó en {A.arrancar():.1f} s; réplica B (:{a.puerto_b}) en "
                f"{B.arrancar():.1f} s; 1 trabajador por réplica, reserva 30 s, sondeo 0,5 s")
            ids = lote(m, a, A, B)
        finally:
            A.parar()
            B.parar()
        fallas += informe_lote(m, ids)
    if a.planificador_minutos:
        fallas += planificador(m, a, url)
    m.dispose()
    log(f"\nRESULTADO: {'TODO OK' if not fallas else 'FALLAS: ' + '; '.join(fallas)}")
    if a.salida:
        a.salida.parent.mkdir(parents=True, exist_ok=True)
        a.salida.write_text("\n".join(_LINEAS) + "\n", encoding="utf-8")
    return 0 if not fallas else 1


if __name__ == "__main__":
    raise SystemExit(main())
