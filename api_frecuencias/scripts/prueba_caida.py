"""RNF-001 · prueba de caída: SIGKILL a la API a mitad de una ejecución y retoma sin perder ni duplicar nada.

Tres escenarios, cada uno con un día nuevo de datos (lectura incremental por marca de agua):
  1. SIGKILL durante la LECTURA incremental; la réplica reinicia con la misma identidad y retoma al instante.
  2. SIGKILL durante la PREDICCIÓN (con predicciones ya escritas en la transacción abierta); reinicia y retoma.
  3. Dos réplicas: se mata la que tenía el trabajo y NO se reinicia; la otra lo retoma al vencer la reserva.
Antes se corre una ejecución limpia de referencia. Para cada ejecución se comprueba: estado ok, intentos = 2,
traza de intentos [abandonado, ok], el mismo número de predicciones y recomendaciones que la referencia, sin
duplicados, alertas = alertas nuevas de las métricas y una sola entrada «crear» por alerta, notificaciones =
las de las métricas, errores de calidad = los de validar el mismo lote una vez, filas leídas = las del día y
marca de agua contigua (marca anterior = marca nueva de la ejecución previa).

Uso:  python scripts/prueba_caida.py --base-datos ai_frecuencias_pruebas_cola \
          --salida docs/evidencias/cola/caida_rnf001.txt --json docs/evidencias/cola/caida_rnf001.json
      Con SIGKILL real de Linux (réplicas en contenedores de la imagen de la API y docker kill):
      docker build -t sobusa_cola_caida:prueba .
      python scripts/prueba_caida.py --docker sobusa_cola_caida:prueba --base-datos ai_frecuencias_pruebas_cola_docker \
          --salida docs/evidencias/cola/caida_rnf001_docker.txt --json docs/evidencias/cola/caida_rnf001_docker.json
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cola_servidor import (  # noqa: E402
    RAIZ,
    Cliente,
    Replica,
    ReplicaDocker,
    lineas_de_log,
    motor,
    preparar_base,
    url_local,
)
from sqlalchemy import text  # noqa: E402

E = "ai_frecuencias"
_LINEAS: list[str] = []


def log(*partes) -> None:
    linea = " ".join(str(p) for p in partes)
    _LINEAS.append(linea)
    print(linea, flush=True)


def esperar(cli: Cliente, ident: str, condicion, limite_s: float = 600, paso: float = 0.1) -> dict:
    fin = time.time() + limite_s
    ultimo: dict = {}
    while time.time() < fin:
        try:
            ultimo = cli.pedir("GET", f"/api/v1/frequency/executions/{ident}")
            if condicion(ultimo):
                return ultimo
        except OSError:
            pass  # la réplica está caída o reiniciando
        time.sleep(paso)
    raise TimeoutError(f"{ident}: condición no alcanzada; último estado {ultimo.get('estado')} {ultimo.get('etapa')}")


def esperar_db(m, ident: str, condicion_sql: str, limite_s: float = 300) -> float:
    t0 = time.time()
    while time.time() - t0 < limite_s:
        with m.connect() as c:
            if c.execute(text(f"SELECT 1 FROM {E}.execution_log WHERE execution_id = :i AND {condicion_sql}"),  # nosec B608  # identificadores de constantes del script; valores por parámetro
                         {"i": ident}).first():
                return time.time() - t0
        time.sleep(0.1)
    raise TimeoutError(condicion_sql)


def limpiar_cola(m) -> int:
    with m.begin() as c:
        return c.execute(text(f"UPDATE {E}.execution_log SET estado = 'error', worker_id = NULL, lease_hasta = NULL, "  # nosec B608  # identificadores de constantes del script; valores por parámetro
                              "mensaje = 'limpieza previa a la prueba de caída' "
                              "WHERE estado IN ('en_cola', 'corriendo')")).rowcount


def fecha_inicial(m):
    from app.servicios import datos

    primera, ultima = datos.rango_fechas()
    with m.connect() as c:
        marca = c.execute(text(f"SELECT max(marca_agua_nueva) FROM {E}.execution_log "  # nosec B608  # identificadores de constantes del script; valores por parámetro
                               "WHERE tipo = 'frecuencia' AND estado = 'ok'")).scalar()
    d0 = (marca.date() + timedelta(days=1)) if marca else primera + timedelta(days=6)
    if d0 + timedelta(days=4) > ultima:
        raise SystemExit(f"No quedan días nuevos tras la marca de agua {marca} (datos hasta {ultima}); "
                         "use una base de pruebas nueva con --base-datos")
    return d0


def medir(m, ident: str) -> dict:
    with m.connect() as c:
        f = c.execute(text(f"""
            SELECT e.estado, e.intentos, e.filas_leidas, e.filas_validas, e.marca_agua_anterior, e.marca_agua_nueva,
                   e.metricas, e.parametros,
                   (SELECT count(*) FROM {E}.prediction p WHERE p.execution_id = e.execution_id) AS predicciones,
                   (SELECT count(DISTINCT (p.ruta, p.instante, p.horizonte_min)) FROM {E}.prediction p
                     WHERE p.execution_id = e.execution_id) AS predicciones_distintas,
                   (SELECT count(*) FROM {E}.recommendation r WHERE r.execution_id = e.execution_id) AS recomendaciones,
                   (SELECT count(*) FROM {E}.alert a WHERE a.execution_id = e.execution_id) AS alertas,
                   (SELECT count(*) FROM {E}.alert_history h JOIN {E}.alert a ON a.alert_id = h.alert_id
                     WHERE a.execution_id = e.execution_id AND h.accion = 'crear') AS alertas_crear,
                   (SELECT count(*) FROM {E}.notification_log n
                     WHERE n.execution_id = e.execution_id) AS notificaciones,
                   (SELECT count(*) FROM {E}.data_quality_error q
                     WHERE q.execution_id = e.execution_id) AS errores_dq,
                   (SELECT count(*) FROM {E}.feature_snapshot f
                     WHERE f.execution_id = e.execution_id AND f.segmento IS NULL) AS foto_ruta,
                   (SELECT count(DISTINCT (f.prediction_id, f.fecha, f.hora)) FROM {E}.feature_snapshot f
                     WHERE f.execution_id = e.execution_id AND f.segmento IS NULL) AS foto_ruta_distintas,
                   (SELECT count(*) FROM {E}.feature_snapshot f
                     WHERE f.execution_id = e.execution_id AND f.segmento IS NOT NULL) AS foto_segmento,
                   (SELECT count(DISTINCT (f.prediction_id, f.sentido, f.segmento, f.fecha, f.hora))
                      FROM {E}.feature_snapshot f
                     WHERE f.execution_id = e.execution_id AND f.segmento IS NOT NULL) AS foto_segmento_distintas
              FROM {E}.execution_log e WHERE e.execution_id = :i"""), {"i": ident}).one()._asdict()  # nosec B608  # {E} es la constante ESQUEMA
        f["intentos_traza"] = [tuple(x) for x in c.execute(text(
            f"SELECT intento, worker_id, resultado FROM {E}.execution_attempt WHERE execution_id = :i "  # nosec B608  # identificadores de constantes del script; valores por parámetro
            "ORDER BY intento"), {"i": ident}).all()]
    return f


def esperado_del_lote(marca_anterior, hasta) -> tuple[int, int]:
    """Filas que trae la lectura incremental y errores de calidad de validarlas UNA vez."""
    from datetime import date

    from app.servicios import calidad
    from app.servicios.fuentes import FuenteParquet

    df, _ = FuenteParquet().leer_incremental(marca_anterior, date.fromisoformat(hasta))
    errores = calidad.validar_lote(df, "referencia")[1] if len(df) else []
    return len(df), len(errores)


def comprobar(nombre: str, d: dict, ref: dict, anterior: dict, caida: bool) -> list[str]:
    fallas = []
    met = d["metricas"] or {}
    filas_esp, dq_esp = esperado_del_lote(d["marca_agua_anterior"], d["parametros"]["hasta"])
    reglas = [
        ("estado ok", d["estado"] == "ok"),
        ("intentos = 2" if caida else "intentos = 1", d["intentos"] == (2 if caida else 1)),
        ("traza [abandonado, ok]" if caida else "traza [ok]",
         [r for _, _, r in d["intentos_traza"]] == (["abandonado", "ok"] if caida else ["ok"])),
        ("predicciones = referencia y sin duplicados",
         d["predicciones"] == d["predicciones_distintas"] == ref["predicciones"] > 0),
        ("recomendaciones = referencia", d["recomendaciones"] == ref["recomendaciones"] > 0),
        ("alertas = alertas_nuevas de la ejecución", d["alertas"] == met.get("alertas_nuevas")),
        ("una sola entrada «crear» por alerta", d["alertas_crear"] == d["alertas"]),
        ("notificaciones = las de las métricas", d["notificaciones"] == (met.get("notificaciones") or 0)),
        (f"errores de calidad = {dq_esp} (validar el lote una vez)", d["errores_dq"] == dq_esp),
        (f"filas leídas = {filas_esp} (las del día nuevo)", d["filas_leidas"] == filas_esp),
        ("marca de agua contigua", anterior is None or d["marca_agua_anterior"] == anterior["marca_agua_nueva"]),
        # §11.2 y §7.3 paso 4: la foto de variables (de la ruta y por segmento y sentido) queda una sola vez; el
        # intento abandonado no deja filas (van en la transacción que confirma el intento «ok»)
        ("foto de variables = referencia y sin filas repetidas (de la ruta y por segmento)",
         d["foto_ruta"] == d["foto_ruta_distintas"] == ref["foto_ruta"] > 0
         and d["foto_segmento"] == d["foto_segmento_distintas"] == ref["foto_segmento"]),
    ]
    for regla, ok in reglas:
        log(f"   [{'OK' if ok else 'FALLA'}] {regla}")
        if not ok:
            fallas.append(f"{nombre}: {regla}")
    return fallas


def resumen(nombre: str, d: dict) -> None:
    log(f"   {nombre}: estado={d['estado']} intentos={d['intentos']} filas_leidas={d['filas_leidas']} "
        f"predicciones={d['predicciones']} recomendaciones={d['recomendaciones']} alertas={d['alertas']} "
        f"notificaciones={d['notificaciones']} errores_dq={d['errores_dq']} foto_ruta={d['foto_ruta']} "
        f"foto_segmento={d['foto_segmento']}")
    log(f"   traza de intentos: {d['intentos_traza']}")
    log(f"   marca de agua: {d['marca_agua_anterior']} -> {d['marca_agua_nueva']}")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--base-datos", default="ai_frecuencias_pruebas_cola")
    p.add_argument("--puerto-a", type=int, default=8103)
    p.add_argument("--puerto-b", type=int, default=8104)
    p.add_argument("--lease", type=float, default=6.0)
    p.add_argument("--salida", type=Path)
    p.add_argument("--json", type=Path)
    p.add_argument("--logs", type=Path, default=RAIZ / "reportes" / "tmp" / "caida")
    p.add_argument("--docker", metavar="IMAGEN", help="réplicas en contenedores Linux de esa imagen (docker kill)")
    a = p.parse_args()
    url = url_local(a.base_datos)
    preparar_base(url)
    m = motor(url)
    log(f"RNF-001 · prueba de caída {time.strftime('%Y-%m-%d %H:%M:%S')} (Windows 11; base local {a.base_datos})")
    if a.docker:
        log(f"Réplicas en contenedores Linux de la imagen {a.docker}: SIGKILL = docker kill (señal 9 al proceso de la "
            "API); reinicio = docker start del mismo contenedor.")
    else:
        log("SIGKILL = Popen.kill() = TerminateProcess: el proceso muere sin apagado ordenado (equivale a kill -9).")
    log(f"Filas pendientes limpiadas antes de empezar: {limpiar_cola(m)}")
    entorno = {"LEASE_SEGUNDOS": str(a.lease), "SONDEO_COLA_SEGUNDOS": "0.5"}
    if a.docker:
        A = ReplicaDocker("caida-a", a.puerto_a, url, a.logs, a.docker, **entorno)
        B = ReplicaDocker("caida-b", a.puerto_b, url, a.logs, a.docker, **entorno)
    else:
        A = Replica("caida-a", a.puerto_a, url, a.logs, **entorno)
        B = Replica("caida-b", a.puerto_b, url, a.logs, **entorno)
    pausas = {"pausa_lectura": 3.0, "pausa_prediccion": 0.8}
    fallas: list[str] = []
    salida_json: dict = {"escenarios": []}
    try:
        log(f"Réplica A arrancó en {A.arrancar(**pausas):.1f} s (pausa inyectada: 3 s en la lectura, 0,8 s por "
            "predicción, para que el SIGKILL caiga dentro de la etapa)")
        ca, cb = Cliente(a.puerto_a), Cliente(a.puerto_b)
        d0 = fecha_inicial(m)

        def post(cli: Cliente, dias: int, etiqueta: str) -> str:
            cuerpo = {"hasta": (d0 + timedelta(days=dias)).isoformat()}
            return cli.pedir("POST", "/api/v1/frequency/executions", cuerpo, cid=f"caida-{etiqueta}")["execution_id"]

        # 0) referencia limpia
        ref_id = post(ca, 0, "referencia")
        esperar(ca, ref_id, lambda d: d["estado"] in ("ok", "error"))
        ref = medir(m, ref_id)
        log(f"\n0) Ejecución de referencia SIN caída ({ref_id}, hasta {d0}):")
        resumen("referencia", ref)
        fallas += comprobar("referencia", ref, ref, None, caida=False)
        salida_json["referencia"] = {"execution_id": ref_id, **{k: ref[k] for k in ("predicciones", "recomendaciones",
                                                                                  "alertas", "intentos", "foto_ruta",
                                                                                  "foto_segmento")}}
        anterior = ref

        # 1) y 2) SIGKILL en una etapa; la misma réplica reinicia
        for n, (etapa, espera) in enumerate((("lectura_incremental", 1.0), ("prediccion", 2.5)), start=1):
            ident = post(ca, n, etapa)
            esperar(ca, ident, lambda d, e=etapa: d["estado"] == "corriendo" and d.get("etapa") == e, paso=0.05)
            time.sleep(espera)
            with m.connect() as c:
                visibles = c.execute(text(f"SELECT count(*) FROM {E}.prediction WHERE execution_id = :i"),  # nosec B608  # identificadores de constantes del script; valores por parámetro
                                     {"i": ident}).scalar()
            t_kill = time.time()
            A.matar()
            log(f"\n{n}) SIGKILL a la réplica A durante «{etapa}» ({ident}, hasta {d0 + timedelta(days=n)}); "
                f"predicciones visibles desde fuera antes del kill: {visibles} (transacción sin confirmar)")
            vuelta = A.arrancar(**pausas)
            esperar(ca, ident, lambda d: d["estado"] in ("ok", "error"))
            total = time.time() - t_kill
            d = medir(m, ident)
            log(f"   API de vuelta en {vuelta:.1f} s; ejecución terminada {total:.1f} s después del kill")
            resumen(etapa, d)
            fallas += comprobar(etapa, d, ref, anterior, caida=True)
            salida_json["escenarios"].append({"escenario": f"sigkill_{etapa}", "execution_id": ident,
                                              "api_de_vuelta_s": round(vuelta, 1), "ok_tras_kill_s": round(total, 1),
                                              "predicciones_visibles_antes_del_kill": visibles,
                                              "intentos": d["intentos"], "traza": d["intentos_traza"]})
            anterior = d

        # 3) dos réplicas: muere la que tiene el trabajo y no vuelve; la otra lo retoma al vencer la reserva
        log(f"\nRéplica B arrancó en {B.arrancar(**pausas):.1f} s")
        ident = post(cb, 3, "reserva")
        esperar(cb, ident, lambda d: d["estado"] == "corriendo" and d.get("etapa") == "prediccion", paso=0.05)
        time.sleep(1.5)
        with m.connect() as c:
            dueno = c.execute(text(f"SELECT worker_id FROM {E}.execution_log WHERE execution_id = :i"),  # nosec B608  # identificadores de constantes del script; valores por parámetro
                              {"i": ident}).scalar()
        victima, sobreviviente = (A, B) if dueno.startswith("caida-a:") else (B, A)
        t_kill = time.time()
        victima.matar()
        log(f"\n3) SIGKILL a la réplica {victima.nombre} (dueña de {ident}) sin reiniciarla; "
            f"la réplica {sobreviviente.nombre} sigue viva (reserva de {a.lease:.0f} s)")
        retoma = esperar_db(m, ident, f"intentos = 2 AND worker_id LIKE '{sobreviviente.nombre}:%'")
        esperar(Cliente(sobreviviente.puerto), ident, lambda d: d["estado"] in ("ok", "error"))
        total = time.time() - t_kill
        d = medir(m, ident)
        log(f"   {sobreviviente.nombre} la retomó {retoma:.1f} s después del kill (reserva vencida); "
            f"terminada {total:.1f} s después")
        resumen("reserva_vencida", d)
        fallas += comprobar("reserva_vencida", d, ref, anterior, caida=True)
        otro = [w for _, w, _ in d["intentos_traza"]]
        regla = len(otro) == 2 and otro[0].startswith(victima.nombre) and otro[1].startswith(sobreviviente.nombre)
        log(f"   [{'OK' if regla else 'FALLA'}] intento 1 de {victima.nombre}, intento 2 de {sobreviviente.nombre}")
        if not regla:
            fallas.append("reserva_vencida: réplicas de la traza")
        salida_json["escenarios"].append({"escenario": "reserva_vencida_otra_replica", "execution_id": ident,
                                          "retomada_tras_kill_s": round(retoma, 1), "ok_tras_kill_s": round(total, 1),
                                          "intentos": d["intentos"], "traza": d["intentos_traza"]})

        with m.connect() as c:
            n, distintas = c.execute(text(f"SELECT count(*), count(DISTINCT (ruta, fecha, hora)) "  # nosec B608  # identificadores de constantes del script; valores por parámetro
                                          f"FROM {E}.demanda_observada")).one()
        log(f"\nHistórico propio demanda_observada: {n} filas, {distintas} claves distintas "
            f"-> {'sin duplicados' if n == distintas else 'CON DUPLICADOS'}")
        if n != distintas:
            fallas.append("demanda_observada con claves duplicadas")
        for r in (A, B):
            r.volcar_log()
            for x in lineas_de_log(r.log_path, ("reencolad", "devuelta por"))[-6:]:
                log(f"   log {r.nombre}: {x}")
    finally:
        A.parar()
        B.parar()
        m.dispose()
    log(f"\nRESULTADO: {'TODO OK' if not fallas else 'FALLAS: ' + '; '.join(fallas)}")
    salida_json["ok"] = not fallas
    salida_json["fallas"] = fallas
    if a.salida:
        a.salida.parent.mkdir(parents=True, exist_ok=True)
        a.salida.write_text("\n".join(_LINEAS) + "\n", encoding="utf-8")
    if a.json:
        a.json.parent.mkdir(parents=True, exist_ok=True)
        a.json.write_text(json.dumps(salida_json, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return 0 if not fallas else 1


if __name__ == "__main__":
    raise SystemExit(main())
