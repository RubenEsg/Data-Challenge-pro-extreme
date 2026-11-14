"""RNF-005 · dos réplicas de la API (procesos uvicorn reales) procesan RUTAS DISTINTAS A LA VEZ, sin duplicados, y la
MISMA ruta nunca en paralelo (partición por ruta y fecha, migración 0009).

1. Arranca dos réplicas sobre la MISMA base local (cada una con su identidad y un trabajador).
2. Envía N ejecuciones partidas por ruta (particion = «ruta», un día nuevo cada una), alternando la réplica que recibe
   el POST: N madres y N × rutas trabajos de ruta, uno por (ruta, fecha).
3. Espera a que terminen y comprueba en la base con execution_attempt (réplica, reclamado_en y terminado_en de cada
   intento, en el reloj de la base):
   - todo ok, un solo intento por trabajo y exactamente un intento «ok» (0 duplicados);
   - las dos réplicas procesaron trabajos de ruta y hubo trabajos de rutas distintas corriendo a la vez en réplicas
     distintas (intervalos que se cruzan);
   - ningún par de trabajos de la MISMA ruta se cruzó en el tiempo (candado por ruta) y cada ruta procesó sus días en
     orden, con su marca de agua contigua (marca anterior = marca nueva del día anterior de esa ruta);
   - cada madre empezó después de que terminaron sus trabajos;
   - predicciones sin duplicados, demanda_observada sin claves repetidas y una marca de agua por ruta en
     marca_agua_ruta, la del último día;
   - la foto de variables (§11.2, con las filas por segmento y sentido de §7.3 paso 4): cada fila en el trabajo de su
     ruta y en la partición mensual de su ventana, ninguna en la madre y ninguna repetida.
4. Con --comparar-sin-partir corre los MISMOS días sin partir (una ejecución de todas las rutas por día) en otra base
   nueva, también con dos réplicas, y compara lo que dejan las dos: predicciones, recomendaciones, plan del día, alertas
   (con sus ocurrencias), foto de la respuesta del reto, histórico propio, monitoreo del modelo y foto de variables (de
   la ruta y por segmento, con sus variables) deben ser iguales.

Uso:  python scripts/prueba_replicas_por_ruta.py --base-datos ai_frecuencias_pruebas_particion_ruta_replicas --n 6 \
          --puerto-a 8322 --puerto-b 8323 --comparar-sin-partir --salida docs/evidencias/cola/replicas_por_ruta.txt \
          [--json docs/evidencias/cola/replicas_por_ruta.json] [--pausa-prediccion 0.3]
Solo contra un PostgreSQL LOCAL (la URL sale de .env o DATABASE_URL y nunca se imprime). --base-nueva y
--comparar-sin-partir borran y vuelven a crear las bases de ESTA prueba (sus nombres los da --base-datos).
Las réplicas de cada lote corren con DATA_DIR y MODELOS_DIR en su propia copia temporal de datos/
(cola_servidor.datos_de_la_base): los dos lotes parten de los mismos modelos y el repositorio queda igual.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter, defaultdict
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cola_servidor import (  # noqa: E402
    RAIZ,
    Cliente,
    Replica,
    motor,
    politica_del_lote,
    preparar_base,
    regla_de_la_politica,
    url_local,
)
from sqlalchemy import text  # noqa: E402

E = "ai_frecuencias"
_LINEAS: list[str] = []


def log(*partes) -> None:
    linea = " ".join(str(p) for p in partes)
    _LINEAS.append(linea)
    print(linea, flush=True)


def fecha_inicial(m, n: int):
    """El primer día sin leer: el siguiente a la marca más avanzada (por ruta o la de antes) o el 7.º de la serie."""
    from app.servicios import datos

    primera, ultima = datos.rango_fechas()
    with m.connect() as c:
        marca = c.execute(text(f"SELECT greatest((SELECT max(marca_agua) FROM {E}.marca_agua_ruta), "  # nosec B608  # E es la constante del esquema
                               f"(SELECT max(marca_agua_nueva) FROM {E}.execution_log "
                               "WHERE tipo = 'frecuencia' AND estado = 'ok'))")).scalar()
    d0 = (marca.astimezone(_zona()).date() + timedelta(days=1)) if marca else primera + timedelta(days=6)
    if d0 + timedelta(days=n) > ultima:
        raise SystemExit(f"No quedan {n} días nuevos tras la marca {marca} (datos hasta {ultima}); use otra base")
    return d0


def _zona():
    from zoneinfo import ZoneInfo

    return ZoneInfo("America/Bogota")


def enviar(a, A: Replica, B: Replica, d0, particion: bool = True) -> tuple[list[str], float]:
    clientes = [Cliente(A.puerto), Cliente(B.puerto)]
    madres = []
    t0 = time.time()
    for i in range(a.n):
        cuerpo = {"hasta": (d0 + timedelta(days=i)).isoformat()} | ({"particion": "ruta"} if particion else {})
        r = clientes[i % 2].pedir("POST", "/api/v1/frequency/executions", cuerpo, cid=f"replicas-ruta-{i:02d}")
        madres.append(r["execution_id"])
    log(f"{a.n} ejecuciones {'partidas por ruta' if particion else 'sin partir'} enviadas en {time.time() - t0:.1f} s "
        f"(POST alternado entre :{A.puerto} y :{B.puerto}); días {d0} … {d0 + timedelta(days=a.n - 1)}")
    return madres, t0


def esperar(m, madres: list[str], limite: float) -> None:
    fin = time.time() + limite
    while time.time() < fin:
        with m.connect() as c:
            pendientes = c.execute(text(f"SELECT count(*) FROM {E}.execution_log WHERE (execution_id = "  # nosec B608  # E es la constante del esquema
                                        "ANY(CAST(:ids AS uuid[])) OR padre_id = ANY(CAST(:ids AS uuid[]))) "
                                        "AND estado NOT IN ('ok', 'error')"), {"ids": madres}).scalar()
        if not pendientes:
            return
        time.sleep(0.5)


def leer_trabajos(m, madres: list[str]) -> list[dict]:
    with m.connect() as c:
        filas = c.execute(text(f"""
            SELECT e.execution_id, e.padre_id, e.ruta, e.particion, e.estado, e.intentos, e.filas_leidas,
                   e.marca_agua_anterior, e.marca_agua_nueva, e.parametros ->> 'hasta' AS hasta,
                   (SELECT count(*) FROM {E}.prediction p WHERE p.execution_id = e.execution_id) AS pred,
                   (SELECT count(DISTINCT (p.ruta, p.instante, p.horizonte_min)) FROM {E}.prediction p
                     WHERE p.execution_id = e.execution_id) AS pred_distintas,
                   (SELECT count(*) FROM {E}.execution_attempt t WHERE t.execution_id = e.execution_id) AS intentos_t,
                   (SELECT count(*) FROM {E}.execution_attempt t WHERE t.execution_id = e.execution_id
                       AND t.resultado = 'ok') AS ok_t,
                   t.worker_id, t.reclamado_en, t.terminado_en
              FROM {E}.execution_log e
              LEFT JOIN {E}.execution_attempt t ON t.execution_id = e.execution_id AND t.resultado = 'ok'
             WHERE e.execution_id = ANY(CAST(:ids AS uuid[])) OR e.padre_id = ANY(CAST(:ids AS uuid[]))
             ORDER BY t.reclamado_en"""), {"ids": madres}).mappings().all()  # nosec B608  # {E} es la constante del esquema
    return [dict(f, replica=(f["worker_id"] or "-").split(":")[0]) for f in filas]


def _hora(x) -> str:
    return "-" if x is None else x.astimezone(_zona()).strftime("%H:%M:%S.%f")[:-3]


def _marca(x) -> str:
    return "(sin marca)      " if x is None else x.astimezone(_zona()).strftime("%Y-%m-%d %H:%M")


def cruces(trabajos: list[dict]) -> list[tuple[dict, dict, float]]:
    """Pares de trabajos cuyos intervalos [reclamado_en, terminado_en] se cruzan, con los segundos de cruce."""
    salida = []
    for i, a in enumerate(trabajos):
        for b in trabajos[i + 1:]:
            inicio, fin = max(a["reclamado_en"], b["reclamado_en"]), min(a["terminado_en"], b["terminado_en"])
            if inicio < fin:
                salida.append((a, b, (fin - inicio).total_seconds()))
    return salida


def concurrencia_maxima(trabajos: list[dict]) -> int:
    eventos = sorted([(t["reclamado_en"], 1) for t in trabajos] + [(t["terminado_en"], -1) for t in trabajos])
    actual = maximo = 0
    for _, paso in eventos:
        actual += paso
        maximo = max(maximo, actual)
    return maximo


def tabla(trabajos: list[dict]) -> None:
    log("\n trabajo   madre     hasta       ruta       réplica          estado int filas pred  reclamado      "
        "terminado      s     marca anterior -> marca nueva")
    for t in trabajos:
        dur = (t["terminado_en"] - t["reclamado_en"]).total_seconds() if t["terminado_en"] else 0.0
        madre = str(t["padre_id"])[:8] if t["padre_id"] else "-"
        log(f" {str(t['execution_id'])[:8]}  {madre:<8}  {t['hasta']}  {(t['ruta'] or '(madre)'):<10} "
            f"{t['replica']:<16} {t['estado']:<6} {t['intentos']:>3} {t['filas_leidas'] or 0:>5} {t['pred']:>4}  "
            f"{_hora(t['reclamado_en'])}  {_hora(t['terminado_en'])} {dur:5.2f}  "
            f"{_marca(t['marca_agua_anterior'])} -> {_marca(t['marca_agua_nueva'])}")


def _por_ruta_en_orden(trabajos: list[dict]) -> dict[str, list[dict]]:
    por_ruta: dict[str, list[dict]] = defaultdict(list)
    for t in sorted(trabajos, key=lambda x: x["reclamado_en"]):
        por_ruta[t["ruta"]].append(t)
    return por_ruta


def reglas_de_ruta(trabajos: list[dict], madres: list[dict], pares) -> list[tuple[str, bool]]:
    misma_ruta = [(a, b) for a, b, _ in pares if a["ruta"] == b["ruta"]]
    distintas = [(a, b, s) for a, b, s in pares if a["ruta"] != b["ruta"] and a["replica"] != b["replica"]]
    por_ruta = _por_ruta_en_orden(trabajos)
    en_orden = all([t["hasta"] for t in v] == sorted(t["hasta"] for t in v) for v in por_ruta.values())
    contiguas = all(v[i]["marca_agua_anterior"] == v[i - 1]["marca_agua_nueva"]
                    for v in por_ruta.values() for i in range(1, len(v)))
    hijos = defaultdict(list)
    for t in trabajos:
        hijos[str(t["padre_id"])].append(t)
    madre_al_final = all(m["reclamado_en"] >= max(h["terminado_en"] for h in hijos[str(m["execution_id"])])
                         for m in madres)
    return [
        ("las dos réplicas procesaron trabajos de ruta", len({t["replica"] for t in trabajos}) == 2),
        (f"rutas distintas a la vez en réplicas distintas: {len(distintas)} pares de intervalos cruzados "
         f"(máximo {max((s for *_, s in distintas), default=0):.2f} s)", bool(distintas)),
        ("la misma ruta nunca se procesó en paralelo (0 cruces)", not misma_ruta),
        ("cada ruta procesó sus días en orden", en_orden),
        ("marca de agua de cada ruta contigua: ningún lote perdido ni leído dos veces", contiguas),
        ("cada madre empezó cuando ya habían terminado sus trabajos", madre_al_final),
    ]


def foto_de_la_particion(m, madres: list[str]) -> dict[str, int]:
    """La foto de variables de la ejecución partida (§11.2 y §7.3 paso 4 con RNF-005): filas por segmento, filas en
    una madre, en el trabajo de otra ruta, fuera de la partición mensual (UTC) de su ventana y repetidas."""
    with m.connect() as c:
        conteos = dict(c.execute(text(f"""
            SELECT count(*) AS filas, count(*) FILTER (WHERE f.segmento IS NOT NULL) AS por_segmento,
                   count(*) FILTER (WHERE e.particion IS NOT NULL) AS en_la_madre,
                   count(*) FILTER (WHERE e.particion IS NULL AND e.ruta IS DISTINCT FROM f.ruta) AS de_otra_ruta,
                   count(*) FILTER (WHERE k.relname <> 'feature_snapshot_' ||
                                    to_char(f.ventana_inicio AT TIME ZONE 'UTC', 'YYYYMM')) AS fuera_de_su_particion
              FROM {E}.feature_snapshot f
              JOIN {E}.execution_log e ON e.execution_id = f.execution_id
              JOIN pg_class k ON k.oid = f.tableoid
             WHERE e.execution_id = ANY(CAST(:ids AS uuid[])) OR e.padre_id = ANY(CAST(:ids AS uuid[]))"""),  # nosec B608  # E es la constante del esquema
            {"ids": madres}).one()._mapping)
        conteos["repetidas"] = c.execute(text(f"""
            SELECT count(*) FROM (SELECT f.execution_id, f.prediction_id, f.sentido, f.segmento, f.fecha, f.hora
              FROM {E}.feature_snapshot f JOIN {E}.execution_log e ON e.execution_id = f.execution_id
             WHERE e.execution_id = ANY(CAST(:ids AS uuid[])) OR e.padre_id = ANY(CAST(:ids AS uuid[]))
             GROUP BY 1, 2, 3, 4, 5, 6 HAVING count(*) > 1) x"""), {"ids": madres}).scalar()  # nosec B608  # E es la constante del esquema
    return conteos


def reglas_de_la_foto(foto: dict[str, int]) -> list[tuple[str, bool]]:
    from app.config import obtener_ajustes

    con_segmentos = foto["por_segmento"] > 0 or not obtener_ajustes().foto_segmentos   # FOTO_SEGMENTOS=false: no hay
    return [
        (f"foto de variables: {foto['filas']} filas ({foto['por_segmento']} por segmento y sentido), cada una en el "
         "trabajo de su ruta y en la partición mensual de su ventana",
         foto["filas"] > 0 and con_segmentos and foto["de_otra_ruta"] == 0 and foto["fuera_de_su_particion"] == 0),
        ("la madre no guarda foto y ninguna fila de la foto se repite", foto["en_la_madre"] == foto["repetidas"] == 0),
    ]


def informe(m, filas: list[dict], n: int, rutas: list[str]) -> tuple[list[str], dict]:
    trabajos = [f for f in filas if f["ruta"] is not None]
    madres = [f for f in filas if f["particion"] is not None]
    tabla(sorted(filas, key=lambda x: x["reclamado_en"] or x["terminado_en"]))
    pares = cruces(trabajos)
    with m.connect() as c:
        n_dem, n_dist = c.execute(text(f"SELECT count(*), count(DISTINCT (ruta, fecha, hora)) "  # nosec B608  # E es la constante del esquema
                                       f"FROM {E}.demanda_observada")).one()
        marcas = {r: mk for r, mk in c.execute(text(f"SELECT ruta, marca_agua FROM {E}.marca_agua_ruta "  # nosec B608  # E es la constante del esquema
                                                     "WHERE proceso = 'sobusa' AND ruta <> '*'")).all()}
    ultimas = {r: v[-1]["marca_agua_nueva"] for r, v in _por_ruta_en_orden(trabajos).items()}
    foto = foto_de_la_particion(m, [str(x["execution_id"]) for x in madres])
    politica = politica_del_lote(m)
    reglas = [
        (f"{len(filas)} de {len(filas)} terminados ok ({len(madres)} madres y {len(trabajos)} trabajos de ruta)",
         Counter(f["estado"] for f in filas) == Counter({"ok": len(filas)}) and len(trabajos) == n * len(rutas)),
        ("exactamente un intento 'ok' por trabajo (0 duplicados)", all(f["ok_t"] == 1 for f in filas)),
        ("un solo intento por trabajo (nadie lo tomó dos veces)", all(f["intentos_t"] == 1 == f["intentos"]
                                                                       for f in filas)),
        *reglas_de_ruta(trabajos, madres, pares),
        ("predicciones sin duplicados en cada trabajo", all(f["pred"] == f["pred_distintas"] for f in filas)),
        (f"demanda_observada: {n_dem} filas = {n_dist} claves distintas", n_dem == n_dist),
        ("marca_agua_ruta: una fila por ruta, en la marca del último día de esa ruta", marcas == ultimas),
        *reglas_de_la_foto(foto),
        regla_de_la_politica(politica),
    ]
    inicio = min(t["reclamado_en"] for t in trabajos)
    fin = max(t["terminado_en"] for t in trabajos)
    suma = sum((t["terminado_en"] - t["reclamado_en"]).total_seconds() for t in trabajos)
    pared = (fin - inicio).total_seconds()
    log(f"\nReparto de los trabajos de ruta por réplica: {dict(Counter(t['replica'] for t in trabajos))}")
    log(f"Trabajos de ruta: {len(trabajos)}; suma de sus duraciones {suma:.1f} s en {pared:.1f} s de reloj "
        f"(paralelismo medio {suma / pared if pared else 0:.2f}); concurrencia máxima {concurrencia_maxima(trabajos)}; "
        f"pares cruzados {len(pares)}")
    for a, b, s in sorted(pares, key=lambda x: -x[2])[:5]:
        log(f"   a la vez {s:.2f} s: {a['ruta']} {a['hasta']} en {a['replica']} y {b['ruta']} {b['hasta']} en "
            f"{b['replica']}")
    fallas = []
    for regla, ok in reglas:
        log(f"   [{'OK' if ok else 'FALLA'}] {regla}")
        if not ok:
            fallas.append(regla)
    resumen = {"trabajos": len(trabajos), "madres": len(madres), "pares_cruzados": len(pares),
               "pares_misma_ruta": sum(1 for a, b, _ in pares if a["ruta"] == b["ruta"]),
               "concurrencia_maxima": concurrencia_maxima(trabajos), "suma_duraciones_s": round(suma, 2),
               "reloj_s": round(pared, 2), "por_replica": dict(Counter(t["replica"] for t in trabajos)),
               "foto_de_variables": foto, "politica_de_aprendizaje": politica, "fallas": fallas,
               "intervalos": [{"execution_id": str(t["execution_id"]), "padre_id": str(t["padre_id"]),
                               "ruta": t["ruta"], "hasta": t["hasta"], "replica": t["replica"],
                               "worker_id": t["worker_id"], "reclamado_en": t["reclamado_en"].isoformat(),
                               "terminado_en": t["terminado_en"].isoformat()} for t in trabajos]}
    return fallas, resumen


# Lo que deja cada ejecución, comparable entre dos bases (lo que no depende de identificadores ni de la hora). Son
# sentencias constantes del script, sin entradas: {E} es la constante del esquema (de ahí cada «nosec B608»).
CONSULTAS_COMPARADAS = {
    "predicciones (ruta, instante, horizonte, P50, P10, P90, modelo)":
        f"SELECT ruta, instante, horizonte_min, round(pasajeros::numeric, 6), round(p10::numeric, 6), "  # nosec B608
        f"round(p90::numeric, 6), model_id FROM {E}.prediction",
    "recomendaciones de franja":
        f"SELECT ruta, fecha, hora, buses_hora, headway_min, vehiculos_requeridos, viable "  # nosec B608
        f"FROM {E}.recommendation WHERE origen = 'franja'",
    "plan del día por ruta y hora":
        f"SELECT ruta, fecha, hora, buses_hora, headway_min, vehiculos_requeridos, viable "  # nosec B608
        f"FROM {E}.recommendation WHERE origen = 'plan_dia'",
    "alertas (clave, código, ruta, severidad, ocurrencias)":
        f"SELECT clave_dedup, codigo, ruta, severidad, ocurrencias FROM {E}.alert",  # nosec B608
    "foto de la respuesta del reto por ruta":
        f"SELECT fecha, ruta, CAST(payload -> 'ruta' AS text) FROM {E}.respuesta_reto",  # nosec B608
    "histórico propio (demanda_observada)":
        f"SELECT ruta, fecha, hora, pasajeros, salidas FROM {E}.demanda_observada",  # nosec B608
    "monitoreo del modelo (una fila por ejecución)":
        f"SELECT fecha_corte, round(wape_movil::numeric, 6), round(cobertura_p10_p90::numeric, 6) "  # nosec B608
        f"FROM {E}.model_monitoring WHERE rol = 'activo'",
    # §11.2 y §7.3 paso 4: la foto de variables (sus variables, con un hash) de la ruta y por segmento y sentido
    "foto de variables de la ruta":
        f"SELECT ruta, horizonte_min, fecha, hora, model_id, ventana_inicio, md5(CAST(features AS text)) "  # nosec B608
        f"FROM {E}.feature_snapshot WHERE segmento IS NULL",
    "foto de variables por segmento y sentido":
        f"SELECT ruta, horizonte_min, sentido, segmento, fecha, hora, model_id, ventana_inicio, "  # nosec B608
        f"md5(CAST(features AS text)) FROM {E}.feature_snapshot WHERE segmento IS NOT NULL",
}


def _resultados(m) -> dict[str, Counter]:
    with m.connect() as c:
        return {nombre: Counter(tuple(f) for f in c.execute(text(sql)).all())  # nosec B608  # SQL constante del script
                for nombre, sql in CONSULTAS_COMPARADAS.items()}


def comparar(m_ruta, m_sin) -> list[str]:
    """Las mismas salidas por ruta con la ejecución partida y sin partir (bases nuevas, mismos días)."""
    log("\nPartida por ruta frente a sin partir (dos bases nuevas, los mismos días, dos réplicas cada una):")
    con, sin = _resultados(m_ruta), _resultados(m_sin)
    fallas = []
    for nombre in CONSULTAS_COMPARADAS:
        iguales = con[nombre] == sin[nombre]
        detalle = f"{sum(con[nombre].values())} filas iguales" if iguales else (
            f"{sum((con[nombre] - sin[nombre]).values())} solo partida, {sum((sin[nombre] - con[nombre]).values())} "
            "solo sin partir")
        log(f"   [{'OK' if iguales and con[nombre] else 'FALLA'}] {nombre}: {detalle}")
        if not (iguales and con[nombre]):
            fallas.append(f"comparación: {nombre}")
    return fallas


def recrear(url: str) -> None:
    """Base local NUEVA para la prueba (borra la anterior del mismo nombre: es de esta prueba) y la migra."""
    from sqlalchemy import create_engine
    from sqlalchemy.engine import make_url

    u = make_url(url)
    admin = create_engine(u.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text(f'DROP DATABASE IF EXISTS "{u.database}" WITH (FORCE)'))
    admin.dispose()
    preparar_base(url)


def correr_lote(url: str, a, particion: bool, etiqueta: str) -> tuple[list[str], float, object]:
    """Dos réplicas sobre `url`, N ejecuciones (partidas por ruta o no) y la espera hasta que terminan todas."""
    m = motor(url)
    sufijo = "" if particion else "-sin"
    A = Replica(f"replica-a{sufijo}", a.puerto_a, url, a.logs, SONDEO_COLA_SEGUNDOS="0.5")
    B = Replica(f"replica-b{sufijo}", a.puerto_b, url, a.logs, SONDEO_COLA_SEGUNDOS="0.5")
    pausa = (f", pausa inyectada de {a.pausa_prediccion} s por predicción" if a.pausa_prediccion
             else ", sin pausas inyectadas (tiempos reales)")
    try:
        t_a = A.arrancar(pausa_prediccion=a.pausa_prediccion)
        t_b = B.arrancar(pausa_prediccion=a.pausa_prediccion)
        log(f"\n[{etiqueta}] réplica A (:{a.puerto_a}) arrancó en {t_a:.1f} s; réplica B (:{a.puerto_b}) en "
            f"{t_b:.1f} s; 1 trabajador por réplica, reserva 30 s, sondeo 0,5 s{pausa}")
        d0 = fecha_inicial(m, a.n)
        ids, t0 = enviar(a, A, B, d0, particion)
        esperar(m, ids, a.limite)
        segundos = time.time() - t0
        log(f"[{etiqueta}] lote terminado en {segundos:.1f} s")
    finally:
        A.parar()
        B.parar()
    return ids, segundos, m


def _guardar(a, fallas: list[str], resumen: dict) -> None:
    if a.salida:
        a.salida.parent.mkdir(parents=True, exist_ok=True)
        a.salida.write_text("\n".join(_LINEAS) + "\n", encoding="utf-8")
    if a.json:
        a.json.parent.mkdir(parents=True, exist_ok=True)
        a.json.write_text(json.dumps({"ok": not fallas, **resumen}, ensure_ascii=False, indent=1), encoding="utf-8")


def main() -> int:
    from app.servicios import datos

    p = argparse.ArgumentParser()
    p.add_argument("--base-datos", default="ai_frecuencias_pruebas_particion_ruta_replicas")
    p.add_argument("--puerto-a", type=int, default=8322)
    p.add_argument("--puerto-b", type=int, default=8323)
    p.add_argument("--n", type=int, default=6)
    p.add_argument("--limite", type=float, default=1200)
    p.add_argument("--pausa-prediccion", type=float, default=0.0)
    p.add_argument("--base-nueva", action="store_true", help="borra y vuelve a crear la base de la prueba")
    p.add_argument("--comparar-sin-partir", action="store_true",
                   help="corre los mismos días sin partir en <base>_sin_partir (nueva) y compara las salidas")
    p.add_argument("--salida", type=Path)
    p.add_argument("--json", type=Path)
    p.add_argument("--logs", type=Path, default=RAIZ / "reportes" / "tmp" / "replicas_por_ruta")
    a = p.parse_args()
    url = url_local(a.base_datos)
    if a.base_nueva or a.comparar_sin_partir:
        recrear(url)
    else:
        preparar_base(url)
    rutas = datos.nombres_rutas()
    log(f"RNF-005 · partición por ruta con dos réplicas {time.strftime('%Y-%m-%d %H:%M:%S')} (base local "
        f"{a.base_datos}; rutas {', '.join(rutas)})")
    madres, segundos, m = correr_lote(url, a, True, "partida por ruta")
    fallas, resumen = informe(m, leer_trabajos(m, madres), a.n, rutas)
    resumen["reloj_lote_s"] = round(segundos, 1)
    if a.comparar_sin_partir:
        url_sin = url_local(f"{a.base_datos}_sin_partir")
        recrear(url_sin)
        _, segundos_sin, m_sin = correr_lote(url_sin, a, False, "sin partir")
        fallas += comparar(m, m_sin)
        resumen.update(reloj_lote_sin_partir_s=round(segundos_sin, 1))
        log(f"   reloj del lote: partida por ruta {segundos:.1f} s; sin partir {segundos_sin:.1f} s")
        m_sin.dispose()
    m.dispose()
    log(f"\nRESULTADO: {'TODO OK' if not fallas else 'FALLAS: ' + '; '.join(fallas)}")
    _guardar(a, fallas, resumen)
    return 0 if not fallas else 1


if __name__ == "__main__":
    raise SystemExit(main())
