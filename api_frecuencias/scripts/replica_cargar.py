"""Carga la réplica operacional (servicio «operacional», puerto 5434) desde las exportaciones Parquet del reto.

- Ids originales: cada tabla conserva su llave primaria exportada; después se ajustan todas las secuencias (setval).
- Orden de llaves foráneas: "Procesos", rutas, catálogos, vehiculos, novedades, progvehiculos, rutas_segmentos_config,
  rutas_segmentos, timbradas_segmentos, timbradas_anio y timbradas_consolidado. rutasgeograficas (no exportada) se
  reconstruye uniendo en orden los segmentos activos exportados.
- timbradas_segmentos se carga SIN los viajes reservados para la simulación (los de la muestra real de conteo,
  rutas 2 y 21 del 2023-02-07): esos llegan después por el trigger de Extreme (replica_meta.viajes_reservados).
- Columnas sensibles («clave_interfaz_despacho», claves de módem...) se cargan en NULL: la réplica no guarda secretos.
- Armonización H1 (replica/errata/H1_armonizar_estacionalidades.sql) salvo REPLICA_ARMONIZAR_ESTACIONALIDADES=0.
- Vuelve a ejecutar tal cual los scripts 99, 5 y 6 de Extreme sobre la réplica cargada y registra que no procesan
  nada (filtran proceso = 'cootransoriente').
- ANALYZE, conteos contra datos/_exportacion.json, integridad de todas las llaves foráneas, longitudes de
  rutasgeograficas, tiempo y memoria (tracemalloc, pool de Arrow y pico del proceso).

Uso (desde EntregaFinal/api_frecuencias, con la réplica arriba):
    .venv\\Scripts\\python -m scripts.replica_cargar
Lee OPERACIONAL_PASSWORD y OPERACIONAL_PUERTO_HOST del entorno o del .env local (o REPLICA_ADMIN_URL completa).
Solo se conecta a un servidor LOCAL: nunca a la base compartida del reto.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import platform
import sys
import time
import tracemalloc
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, urlsplit
from zoneinfo import ZoneInfo

import psycopg
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.csv as pacsv
import pyarrow.parquet as pq

RAIZ = Path(__file__).resolve().parents[1]
DATOS = Path(os.environ.get("REPLICA_DATOS_DIR") or RAIZ.parents[1] / "datos")
EXTREME = RAIZ / "replica" / "extreme"
ERRATA = RAIZ / "replica" / "errata"
EVIDENCIAS = RAIZ / "docs" / "evidencias" / "replica"
MUESTRA = "muestra_conteo_pasajeros_20230207_r2_r21.parquet"
HOSTS_LOCALES = {"localhost", "127.0.0.1", "::1", "operacional"}
LOTE = 200_000
BOGOTA = ZoneInfo("America/Bogota")

# (tabla, archivo Parquet). El orden respeta las llaves foráneas.
TABLAS = [
    ('"Procesos"', "Procesos.parquet"),
    ("rutas", "rutas.parquet"),
    ("dias_semana", "dias_semana.parquet"),
    ("estacionalidades", "estacionalidades.parquet"),
    ("estacionalidades_anio", "estacionalidades_anio.parquet"),
    ("vehiculos", "vehiculos.parquet"),
    ("novedades_viales", "novedades_viales.parquet"),
    ("novedades_viales_fecha", "novedades_viales_fecha.parquet"),
    ("novedades_viales_ruta", "novedades_viales_ruta.parquet"),
    ("progvehiculos", "progvehiculos.parquet"),
    ("rutas_segmentos_config", "rutas_segmentos_config.parquet"),
    ("rutas_segmentos", "rutas_segmentos.parquet"),
    ("timbradas_segmentos", "timbradas_segmentos.parquet"),
    ("timbradas_anio", "timbradas_anio.parquet"),
    ("timbradas_consolidado", "timbradas_consolidado.parquet"),
]

# secretos operativos que vinieron en la exportación: la columna se conserva (fidelidad del esquema) pero vacía
SENSIBLES = {
    "Procesos": ["url_interfaz_despacho", "usuario_interfaz_despacho", "clave_interfaz_despacho"],
    "vehiculos": ["modem_user", "modem_passwd", "modem_puk", "modem_user_2", "modem_passwd_2", "modem_puk_2"],
}


def _cargar_env() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover
        return
    load_dotenv(RAIZ / ".env", override=False)


def url_admin() -> str:
    """URL de extreme_dba en la réplica LOCAL (nunca la base del reto).

    REPLICA_URL (o REPLICA_ADMIN_URL) completa, o se arma con OPERACIONAL_PASSWORD, REPLICA_HOST (localhost) y
    OPERACIONAL_PUERTO_HOST (5434)."""
    _cargar_env()
    url = os.environ.get("REPLICA_URL") or os.environ.get("REPLICA_ADMIN_URL")
    if not url:
        clave = os.environ.get("OPERACIONAL_PASSWORD")
        if not clave:
            raise SystemExit("Defina OPERACIONAL_PASSWORD (o REPLICA_URL) en el entorno o en el .env local")
        host = os.environ.get("REPLICA_HOST", "localhost")
        puerto = os.environ.get("OPERACIONAL_PUERTO_HOST", "5434")
        url = f"postgresql://extreme_dba:{quote(clave, safe='')}@{host}:{puerto}/operacional"
    host = urlsplit(url.replace("postgresql+psycopg://", "postgresql://")).hostname
    if host not in HOSTS_LOCALES:
        raise SystemExit(f"La réplica solo se carga en un servidor local (host={host!r})")
    return url.replace("postgresql+psycopg://", "postgresql://")


def _pico_proceso_mb() -> float | None:
    """Pico de memoria del proceso (working set en Windows, ru_maxrss en Linux)."""
    try:
        if platform.system() == "Windows":
            import ctypes
            from ctypes import wintypes

            class PMC(ctypes.Structure):
                _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                            ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                            ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]

            pmc = PMC()
            pmc.cb = ctypes.sizeof(PMC)
            k32 = ctypes.WinDLL("kernel32")
            k32.GetCurrentProcess.restype = wintypes.HANDLE
            ps = ctypes.WinDLL("psapi")
            ps.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(PMC), wintypes.DWORD]
            if ps.GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb):
                return pmc.PeakWorkingSetSize / 2**20
            return None
        import resource

        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    except Exception:  # noqa: BLE001
        return None


def _nombre(tabla: str) -> str:
    return tabla.strip('"')


def _preparar_lote(nombre: str, lote: pa.Table, reservados: pa.Array | None, enmascaradas: dict) -> pa.Table:
    if nombre == "timbradas_segmentos" and reservados is not None:
        lote = lote.filter(pc.invert(pc.is_in(lote["id_viaje"], value_set=reservados)))
    for col in SENSIBLES.get(nombre, []):
        if col in lote.column_names:
            i = lote.column_names.index(col)
            enmascaradas[col] = enmascaradas.get(col, 0) + (len(lote) - lote[col].null_count)
            lote = lote.set_column(i, col, pa.nulls(len(lote), lote.schema.field(col).type))
    if nombre == "rutas_segmentos":
        i = lote.column_names.index("geom_segmento")
        lote = lote.set_column(i, "geom_segmento",
                               pc.binary_join_element_wise(pa.scalar("SRID=4326;"), lote["geom_segmento"], ""))
    return lote


def copiar_tabla(cur: psycopg.Cursor, tabla: str, archivo: str, reservados: pa.Array | None) -> dict:
    nombre = _nombre(tabla)
    pf = pq.ParquetFile(DATOS / archivo)
    columnas = pf.schema_arrow.names
    lista = ", ".join(f'"{c}"' for c in columnas)
    t0 = time.perf_counter()
    filas = leidas = 0
    enmascaradas: dict[str, int] = {}
    opciones = pacsv.WriteOptions(include_header=False, quoting_style="needed")
    with cur.copy(f"COPY public.{tabla} ({lista}) FROM STDIN WITH (FORMAT csv)") as cp:
        for lote in pf.iter_batches(batch_size=LOTE):
            t = _preparar_lote(nombre, pa.Table.from_batches([lote]), reservados, enmascaradas)
            leidas += lote.num_rows
            filas += t.num_rows
            buf = io.BytesIO()
            pacsv.write_csv(t, buf, opciones)
            cp.write(buf.getbuffer())
    return {"tabla": nombre, "filas": filas, "leidas": leidas, "excluidas": leidas - filas,
            "segundos": round(time.perf_counter() - t0, 2), "enmascaradas": enmascaradas}


def _ejecutar_archivo(cur: psycopg.Cursor, ruta: Path) -> None:
    cur.execute(ruta.read_bytes().decode("utf-8"))


def _registrar_paso(cur, paso: str, archivo: str, errores: int, nota: str, inicio: datetime, salida: str) -> None:
    import hashlib

    sha = hashlib.sha256((RAIZ / archivo).read_bytes()).hexdigest() if (RAIZ / archivo).exists() else None
    cur.execute("""INSERT INTO replica_meta.paso
                       (paso, archivo, sha256, errores, errores_esperados, nota, inicio, salida)
                   VALUES (%s, %s, %s, %s, 0, %s, %s, %s)""", (paso, archivo, sha, errores, nota, inicio, salida))


def reiniciar(cur: psycopg.Cursor) -> None:
    cur.execute("""SELECT format('%I.%I', schemaname, tablename) FROM pg_tables
                   WHERE schemaname = 'public' AND tablename <> 'spatial_ref_sys'""")
    tablas = [r[0] for r in cur.fetchall()]
    cur.execute(f"TRUNCATE {', '.join(tablas)} RESTART IDENTITY CASCADE")
    cur.execute("TRUNCATE replica_meta.carga, replica_meta.viajes_reservados")
    cur.execute("DELETE FROM replica_meta.paso WHERE paso LIKE 'carga%' OR paso LIKE 'post-carga%'")


def reservar_viajes(cur: psycopg.Cursor) -> pa.Array:
    muestra = pq.read_table(DATOS / MUESTRA, columns=["idprogramacion"])
    conteo = muestra.group_by("idprogramacion").aggregate([("idprogramacion", "count")])
    ids = conteo["idprogramacion"]
    ts = pq.read_table(DATOS / "timbradas_segmentos.parquet", columns=["id_viaje"],
                       filters=[("id_viaje", "in", ids.to_pylist())])
    excl = ts.group_by("id_viaje").aggregate([("id_viaje", "count")])
    excl_map = dict(zip(excl["id_viaje"].to_pylist(), excl["id_viaje_count"].to_pylist(), strict=True))
    filas = [(int(i), int(n), int(excl_map.get(i, 0)))
             for i, n in zip(ids.to_pylist(), conteo["idprogramacion_count"].to_pylist(), strict=True)]
    with cur.copy("COPY replica_meta.viajes_reservados (idprogramacion, filas_crudas, "
                  "filas_timbradas_segmentos_excluidas) FROM STDIN") as cp:
        for fila in filas:
            cp.write_row(fila)
    return ids


def reconstruir_rutasgeograficas(cur: psycopg.Cursor) -> list[tuple]:
    # rutasgeograficas no se exportó y rutas.geom viene vacía: cada línea se reconstruye uniendo en orden los
    # segmentos activos exportados (los segmentos de Extreme salen de ST_LineSubstring sobre esa misma línea)
    # varias configuraciones comparten idrutageo (p. ej. las rutas 2, 8 y 9 usan la 3): se toma la de la ruta que está
    # en public.rutas y, si ninguna lo está, la de menor id
    cur.execute("""INSERT INTO public.rutasgeograficas (idruta, geom)
                   WITH cfg AS (
                       SELECT DISTINCT ON (c.idrutageo) c.id, c.idrutageo
                       FROM public.rutas_segmentos_config c
                       ORDER BY c.idrutageo, (c.idruta IN (SELECT idruta FROM public.rutas)) DESC, c.id)
                   SELECT cfg.idrutageo, ST_LineMerge(ST_Collect(s.geom_segmento ORDER BY s.nro_segmento))
                   FROM public.rutas_segmentos s JOIN cfg ON cfg.id = s.id_config
                   WHERE s.activo GROUP BY cfg.idrutageo""")
    cur.execute("""SELECT g.idruta, ST_GeometryType(g.geom), round(ST_Length(g.geom::geography)::numeric, 1),
                          round(s.suma, 1), s.n
                   FROM public.rutasgeograficas g
                   JOIN (SELECT s.idrutageo, sum(s.longitud_m) suma, count(*) n FROM public.rutas_segmentos s
                         JOIN public.rutas r ON r.idruta = s.idruta AND r.idrutageo = s.idrutageo
                         WHERE s.activo GROUP BY s.idrutageo) s ON s.idrutageo = g.idruta
                   ORDER BY 1""")
    return cur.fetchall()


def ajustar_secuencias(cur: psycopg.Cursor) -> list[tuple]:
    cur.execute("""SELECT format('%I.%I', ns.nspname, s.relname), format('%I.%I', tn.nspname, t.relname), a.attname
                   FROM pg_class s JOIN pg_namespace ns ON ns.oid = s.relnamespace
                   JOIN pg_depend d ON d.objid = s.oid AND d.deptype IN ('a', 'i')
                   JOIN pg_class t ON t.oid = d.refobjid JOIN pg_namespace tn ON tn.oid = t.relnamespace
                   JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = d.refobjsubid
                   WHERE s.relkind = 'S' AND tn.nspname = 'public' ORDER BY 1""")
    salida = []
    for seq, tabla, col in cur.fetchall():
        cur.execute(f'SELECT max("{col}") FROM {tabla}')  # nosec B608  # identificadores de constantes del script; valores por parámetro
        maximo = cur.fetchone()[0]
        if maximo is None:
            cur.execute("SELECT setval(%s, 1, false)", (seq,))
        else:
            cur.execute("SELECT setval(%s, %s, true)", (seq, maximo))
        salida.append((seq, maximo))
    return salida


def verificar_llaves_foraneas(cur: psycopg.Cursor) -> list[tuple]:
    cur.execute("""SELECT c.conname, c.conrelid::regclass::text, c.confrelid::regclass::text,
                          array_agg(a.attname ORDER BY k.ord), array_agg(af.attname ORDER BY k.ord)
                   FROM pg_constraint c
                   CROSS JOIN LATERAL unnest(c.conkey, c.confkey) WITH ORDINALITY AS k(col, fcol, ord)
                   JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = k.col
                   JOIN pg_attribute af ON af.attrelid = c.confrelid AND af.attnum = k.fcol
                   WHERE c.contype = 'f' AND c.connamespace = 'public'::regnamespace
                   GROUP BY 1, 2, 3 ORDER BY 2, 1""")
    salida = []
    for nombre, hija, madre, cols, fcols in cur.fetchall():
        union = " AND ".join(f'm."{f}" = h."{c}"' for c, f in zip(cols, fcols, strict=True))
        no_nulas = " AND ".join(f'h."{c}" IS NOT NULL' for c in cols)
        cur.execute(f"SELECT count(*) FROM {hija} h WHERE {no_nulas} AND NOT EXISTS "  # nosec B608  # identificadores de constantes del script; valores por parámetro
                    f"(SELECT 1 FROM {madre} m WHERE {union})")
        huerfanas = cur.fetchone()[0]
        cur.execute(f"SELECT count(*) FROM {hija}")  # nosec B608  # identificadores de constantes del script; valores por parámetro
        salida.append((nombre, hija, madre, cur.fetchone()[0], huerfanas))
    return salida


def scripts_post_carga(cur: psycopg.Cursor) -> list[dict]:
    """Ejecuta tal cual los scripts 99, 5 y 6 sobre la réplica cargada: no procesan nada con datos de 'sobusa'."""
    conteos_sql = ("SELECT (SELECT count(*) FROM public.timbradas_segmentos), "
                   "(SELECT count(*) FROM public.timbradas_segmentos_anio), "
                   "(SELECT count(*) FROM public.rutas_segmentos_config), "
                   "(SELECT count(*) FROM public.rutas_segmentos)")
    salida = []
    for archivo in ["99. prueba de segmentacion.sql", "5. cargue inicial timbradas_segmentos.sql",
                    "6. cargue inicial timbradas_segmentos_anio.sql"]:
        cur.execute(conteos_sql)
        antes = cur.fetchone()
        inicio = datetime.now(BOGOTA)
        t0 = time.perf_counter()
        _ejecutar_archivo(cur, EXTREME / archivo)
        dur = round(time.perf_counter() - t0, 2)
        cur.execute(conteos_sql)
        despues = cur.fetchone()
        nota = (f"Post-carga, tal cual, sobre la réplica cargada: {dur} s; filas (timbradas_segmentos, "
                f"timbradas_segmentos_anio, rutas_segmentos_config, rutas_segmentos) antes={antes} después={despues}"
                " (filtra proceso = 'cootransoriente'; los datos son de 'sobusa')")
        _registrar_paso(cur, f"post-carga {archivo.split('.')[0]}", f"replica/extreme/{archivo}", 0, nota, inicio, "")
        salida.append({"script": archivo, "segundos": dur, "antes": list(antes), "despues": list(despues)})
    return salida


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--sin-post-carga", action="store_true", help="no volver a ejecutar los scripts 99, 5 y 6")
    args = ap.parse_args(argv)

    tracemalloc.start()
    pa.default_memory_pool()  # inicializa el pool para medir su máximo
    armonizar = os.environ.get("REPLICA_ARMONIZAR_ESTACIONALIDADES", "1") != "0"
    t_total = time.perf_counter()
    exportacion = json.loads((DATOS / "_exportacion.json").read_text(encoding="utf-8"))
    resultados: list[dict] = []
    with psycopg.connect(url_admin(), autocommit=False) as cx, cx.cursor() as cur:
        cur.execute("SET TimeZone = 'America/Bogota'")
        cur.execute("SET maintenance_work_mem = '256MB'")
        t0 = time.perf_counter()
        reiniciar(cur)
        reservados = reservar_viajes(cur)
        t_prep = round(time.perf_counter() - t0, 2)
        # Paso de RESTAURACIÓN del DBA (extreme_dba, como un pg_restore), no del entrenamiento ni de las pruebas
        # (§11.3): la carga masiva de las exportaciones no dispara triggers ni revisa llaves foráneas fila por fila
        # (session_replication_role = replica, solo en esta sesión y solo durante el COPY); la integridad se comprueba
        # completa al final con verificar_llaves_foraneas() y tg_timbrada_segmento queda habilitado. lector_ia y
        # escritor_ia no pueden cambiar este parámetro (42501): test_integrado.py::test_la_ia_no_puede_apagar_triggers_*
        cur.execute("SET session_replication_role = replica")
        for tabla, archivo in TABLAS:
            r = copiar_tabla(cur, tabla, archivo, reservados)
            r["filas_exportadas"] = exportacion.get(r["tabla"], {}).get("filas_exportadas")
            resultados.append(r)
            print(f"  {r['tabla']:<24} {r['filas']:>10,} filas  {r['segundos']:>6.2f} s"
                  + (f"  (excluidas {r['excluidas']:,})" if r["excluidas"] else ""), flush=True)
        cur.execute("SET session_replication_role = origin")
        geo = reconstruir_rutasgeograficas(cur)
        secuencias = ajustar_secuencias(cur)
        # conteo_pasajeros empieza vacía: su secuencia arranca por encima del mayor id de la muestra real, para que las
        # filas nuevas del simulador nunca choquen con los ids originales de los viajes reservados (modo reproducción)
        max_id_muestra = pq.read_table(DATOS / MUESTRA, columns=["id"])["id"]
        tope = int(pc.max(max_id_muestra).as_py())
        cur.execute("SELECT setval('public.conteo_pasajeros_id_seq', greatest(%s, "
                    "(SELECT coalesce(max(id), 0) FROM public.conteo_pasajeros)), true)", (tope,))
        secuencias = [(s, tope if s == "public.conteo_pasajeros_id_seq" else m) for s, m in secuencias]
        if armonizar:
            inicio = datetime.now(BOGOTA)
            _ejecutar_archivo(cur, ERRATA / "H1_armonizar_estacionalidades.sql")
            h1_filas = cur.rowcount
            _registrar_paso(cur, "carga H1", "replica/errata/H1_armonizar_estacionalidades.sql", 0,
                            f"Armonización H1: {h1_filas} filas de estacionalidades_anio pasan a proceso='sobusa'",
                            inicio, "")
        else:
            h1_filas = 0
        for r in resultados:
            cur.execute("""INSERT INTO replica_meta.carga (tabla, filas, filas_exportadas, excluidas, segundos, nota)
                           VALUES (%s, %s, %s, %s, %s, %s)""",
                        (r["tabla"], r["filas"], r["filas_exportadas"], r["excluidas"], r["segundos"],
                         json.dumps({"enmascaradas": r["enmascaradas"]}) if r["enmascaradas"] else None))
        cx.commit()
        post = [] if args.sin_post_carga else scripts_post_carga(cur)
        cx.commit()
        t0 = time.perf_counter()
        cx.autocommit = True
        cur.execute("ANALYZE")
        t_analyze = round(time.perf_counter() - t0, 2)
        fks = verificar_llaves_foraneas(cur)
        cur.execute("SELECT pg_size_pretty(pg_database_size(current_database())), version()")
        tam, version = cur.fetchone()
        cur.execute("SELECT proceso, count(*) FROM public.estacionalidades_anio GROUP BY 1")
        estacionalidades = cur.fetchall()
    total = round(time.perf_counter() - t_total, 2)
    _, pico_py = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    filas_total = sum(r["filas"] for r in resultados)
    resumen = {
        "fecha": datetime.now(BOGOTA).isoformat(timespec="seconds"),
        "servidor": version.split(",")[0],
        "tamano_base": tam,
        "segundos_total": total,
        "segundos_preparacion": t_prep,
        "segundos_analyze": t_analyze,
        "filas_total": filas_total,
        "filas_por_segundo": round(filas_total / total) if total else None,
        "memoria_pico_python_mb": round(pico_py / 2**20, 1),
        "memoria_pico_arrow_mb": round(pa.default_memory_pool().max_memory() / 2**20, 1),
        "memoria_pico_proceso_mb": round(_pico_proceso_mb() or 0, 1),
        "lote_filas": LOTE,
        "viajes_reservados": len(reservados),
        "armonizacion_H1_filas": h1_filas,
        "estacionalidades_anio_por_proceso": dict(estacionalidades),
        "tablas": resultados,
        "rutasgeograficas": [{"idruta": g[0], "tipo": g[1], "longitud_m": float(g[2]),
                              "suma_longitud_segmentos_m": float(g[3]), "segmentos": g[4]} for g in geo],
        "secuencias": [{"secuencia": s, "max_id": m} for s, m in secuencias],
        "llaves_foraneas": [{"constraint": f[0], "tabla": f[1], "referencia": f[2], "filas": f[3], "huerfanas": f[4]}
                            for f in fks],
        "scripts_post_carga": post,
    }
    escribir_evidencia(resumen)
    print(f"listo: {filas_total:,} filas en {total} s ({resumen['filas_por_segundo']:,} filas/s); "
          f"pico proceso {resumen['memoria_pico_proceso_mb']} MB; FK huérfanas: {sum(f[4] for f in fks)}")
    return 0 if all(f[4] == 0 for f in fks) else 1


def escribir_evidencia(r: dict) -> None:
    EVIDENCIAS.mkdir(parents=True, exist_ok=True)
    (EVIDENCIAS / "replica_carga.json").write_text(json.dumps(r, ensure_ascii=False, indent=1, default=str),
                                                   encoding="utf-8")
    lineas = [
        "Carga de la réplica operacional desde las exportaciones Parquet (scripts/replica_cargar.py)",
        f"Fecha: {r['fecha']}   Servidor: {r['servidor']}   Tamaño de la base: {r['tamano_base']}",
        f"Total: {r['filas_total']:,} filas en {r['segundos_total']} s ({r['filas_por_segundo']:,} filas/s); "
        f"preparación {r['segundos_preparacion']} s; ANALYZE {r['segundos_analyze']} s; lotes de {r['lote_filas']:,}",
        f"Memoria pico: proceso {r['memoria_pico_proceso_mb']} MB; Python (tracemalloc) "
        f"{r['memoria_pico_python_mb']} MB; Arrow {r['memoria_pico_arrow_mb']} MB",
        f"Viajes reservados para la simulación (no cargados en timbradas_segmentos): {r['viajes_reservados']}",
        f"Armonización H1: {r['armonizacion_H1_filas']} filas de estacionalidades_anio -> proceso='sobusa' "
        f"(ahora {r['estacionalidades_anio_por_proceso']})",
        "",
        f"{'tabla':<26}{'filas':>12}{'exportadas':>12}{'excluidas':>11}{'s':>8}{'filas/s':>11}  nota",
    ]
    for t in r["tablas"]:
        fps = round(t["filas"] / t["segundos"]) if t["segundos"] else 0
        nota = ""
        if t["excluidas"]:
            nota = "sin los viajes reservados"
        if t["enmascaradas"]:
            nota = "columnas sensibles en NULL: " + ", ".join(f"{k} ({v})" for k, v in t["enmascaradas"].items())
        coincide = t["filas"] + t["excluidas"] == (t["filas_exportadas"] or 0)
        lineas.append(f"{t['tabla']:<26}{t['filas']:>12,}{t['filas_exportadas'] or 0:>12,}{t['excluidas']:>11,}"
                      f"{t['segundos']:>8.2f}{fps:>11,}  {'OK' if coincide else 'DIFIERE'} {nota}")
    lineas += ["", "rutasgeograficas reconstruida (ST_LineMerge de los segmentos activos, en orden):"]
    for g in r["rutasgeograficas"]:
        lineas.append(f"  idrutageo {g['idruta']}: {g['tipo']} {g['longitud_m']:,} m; suma de longitud_m de "
                      f"{g['segmentos']} segmentos = {g['suma_longitud_segmentos_m']:,} m")
    lineas += ["", "Secuencias ajustadas (setval al máximo id cargado):"]
    lineas += [f"  {s['secuencia']}: {s['max_id']}" for s in r["secuencias"]]
    lineas += ["", "Integridad de las llaves foráneas (filas hijas sin madre):"]
    lineas += [f"  {f['constraint']}: {f['tabla']} -> {f['referencia']}  {f['filas']:,} filas, "
               f"{f['huerfanas']} huérfanas" for f in r["llaves_foraneas"]]
    if r["scripts_post_carga"]:
        lineas += ["", "Scripts 99, 5 y 6 de Extreme ejecutados tal cual sobre la réplica cargada:"]
        lineas += [f"  {p['script']}: {p['segundos']} s; filas antes {p['antes']} después {p['despues']}"
                   for p in r["scripts_post_carga"]]
    (EVIDENCIAS / "replica_carga.txt").write_text("\n".join(lineas) + "\n", encoding="utf-8")
    # una línea por corrida: el tiempo depende de la carga del equipo, así que se conservan todas las mediciones
    historial = EVIDENCIAS / "replica_carga_historial.txt"
    if not historial.exists():
        historial.write_text("fecha | filas | segundos | filas/s | pico proceso MB | pico Arrow MB | FK huérfanas\n",
                             encoding="utf-8")
    with historial.open("a", encoding="utf-8") as h:
        h.write(f"{r['fecha']} | {r['filas_total']} | {r['segundos_total']} | {r['filas_por_segundo']} | "
                f"{r['memoria_pico_proceso_mb']} | {r['memoria_pico_arrow_mb']} | "
                f"{sum(f['huerfanas'] for f in r['llaves_foraneas'])}\n")


if __name__ == "__main__":
    sys.exit(main())
