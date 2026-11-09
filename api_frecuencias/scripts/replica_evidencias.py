"""Genera la evidencia de la réplica operacional en docs/evidencias/replica/ (scripts sin modificar y roles).

- replica_init.log: registro de la inicialización ($PGDATA/replica_init.log del contenedor).
- replica_objetos.txt: funciones, trigger, tablas de Extreme (\\d+), índices, esquemas, roles y privilegios por defecto.
- replica_errata.txt: cada corrección (E1, E2, H1) con el fallo SIN ella y el resultado CON ella, en bases desechables
  o en transacciones que se deshacen.
- replica_roles.txt: cada escritura de lector_ia (con y sin modo solo lectura) con su error exacto, y escritor_ia.

Uso: .venv\\Scripts\\python -m scripts.replica_evidencias   (con la réplica arriba y cargada)
"""
from __future__ import annotations

import sys
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

import psycopg

from scripts import replica_comun as rc

SALIDA = rc.RAIZ / "docs" / "evidencias" / "replica"
TABLAS_EXTREME = ["rutas_segmentos_config", "rutas_segmentos_porcion", "rutas_segmentos", "timbradas_segmentos",
                  "timbradas_segmentos_anio", "timbradas_segmentos_anio_trazabilidad",
                  "timbradas_segmentos_consolidado", "conteo_pasajeros"]


def _ahora() -> str:
    return datetime.now(ZoneInfo("America/Bogota")).isoformat(timespec="seconds")


def _url(rol: str, base: str = "operacional") -> str:
    url = rc.url_rol(rol)
    if url is None:
        raise SystemExit(f"falta la clave de {rol} en el entorno o en el .env")
    return url.rsplit("/", 1)[0] + f"/{base}"


def init_log() -> None:
    r = rc.psql("operacional", "-At", "-c", "SELECT pg_read_file('replica_init.log')")
    texto = r.stdout if r.returncode == 0 else ""
    if not texto:
        import subprocess

        texto = subprocess.run(["docker", "exec", rc.contenedor(), "sh", "-c",  # noqa: S603, S607
                                "cat \"$PGDATA/replica_init.log\""], capture_output=True, text=True,
                               encoding="utf-8", check=True).stdout
    (SALIDA / "replica_init.log").write_text(texto, encoding="utf-8")


def objetos() -> None:
    comandos = ["\\df public.fn_*",
                "SELECT t.tgname, t.tgrelid::regclass AS tabla, p.proname AS funcion, t.tgenabled, "
                "pg_get_triggerdef(t.oid) AS definicion FROM pg_trigger t JOIN pg_proc p ON p.oid = t.tgfoid "
                "WHERE NOT t.tgisinternal",
                "\\dt+ public.*", "\\dn+",
                "SELECT indexrelid::regclass AS indice, indrelid::regclass AS tabla, pg_get_indexdef(indexrelid) "
                "FROM pg_index WHERE indrelid::regclass::text IN ('timbradas_segmentos', 'timbradas_consolidado', "
                "'timbradas_anio', 'conteo_pasajeros', 'rutas_segmentos', 'rutas_segmentos_config') ORDER BY 2, 1",
                "SELECT rolname, rolsuper, rolcanlogin, rolconnlimit, rolconfig FROM pg_roles "
                "WHERE rolname IN ('extreme_dba', 'lector_ia', 'escritor_ia') ORDER BY 1",
                "\\ddp", "\\l operacional",
                "SELECT n.nspname AS esquema, c.relname AS tabla, "
                "has_table_privilege('lector_ia', c.oid, 'SELECT') AS lector_select, "
                "has_table_privilege('lector_ia', c.oid, 'INSERT,UPDATE,DELETE,TRUNCATE') AS lector_escribe, "
                "has_table_privilege('escritor_ia', c.oid, 'SELECT,INSERT,UPDATE,DELETE') AS escritor_algo "
                "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = 'public' AND c.relkind = 'r' ORDER BY 2"]
    comandos += [f"\\d+ public.{t}" for t in TABLAS_EXTREME]
    args = []
    for c in comandos:
        args += ["-c", c]
    r = rc.psql("operacional", "-P", "pager=off", *args)
    texto = f"Objetos de la réplica operacional ({_ahora()})\n\n" + r.stdout + r.stderr
    (SALIDA / "replica_objetos.txt").write_text(texto, encoding="utf-8")


def _nueva_base(admin) -> str:
    nombre = f"validacion_{uuid.uuid4().hex[:10]}"
    with admin.cursor() as cur:
        cur.execute(f'CREATE DATABASE "{nombre}"')
    for archivo in ("00_extensiones.sql", "10_base_operacional.sql"):
        rc.psql(nombre, "-q", "-v", "ON_ERROR_STOP=1", "-f", f"/docker-entrypoint-initdb.d/{archivo}")
    return nombre


def errata(admin) -> None:
    lineas = [f"Correcciones de la réplica y la prueba del fallo sin cada una ({_ahora()})",
              "Los scripts de Extreme se ejecutan SIN cambios (replica/extreme, SHA256SUMS). Las correcciones son",
              "archivos aparte en replica/errata. Pruebas automáticas: tests/replica/test_scripts_extreme.py", ""]
    bases = []
    try:
        # E1
        b = _nueva_base(admin)
        bases.append(b)
        r = rc.psql(b, "-v", "ON_ERROR_STOP=0", "-f", "/extreme/1. tablas.sql")
        errores = [x for x in (r.stdout + r.stderr).splitlines() if "ERROR:" in x]
        lineas += ["== E1 — «1. tablas.sql» SIN la corrección E1 (base vacía desechable):",
                   f"   {len(errores)} errores:"] + [f"   | {e}" for e in errores]
        b = _nueva_base(admin)
        bases.append(b)
        rc.psql(b, "-q", "-v", "ON_ERROR_STOP=1", "-f", "/errata/E1_rutas_segmentos_config.sql")
        r = rc.psql(b, "-v", "ON_ERROR_STOP=0", "-f", "/extreme/1. tablas.sql")
        salida = r.stdout + r.stderr
        lineas += ["== E1 — el mismo script CON E1 antes:",
                   f"   {salida.count('ERROR:')} error (el de sintaxis, esperado) y {salida.count('CREATE TABLE')} "
                   "CREATE TABLE"] + [f"   | {x}" for x in salida.splitlines()] + [""]
        # E2
        for con_e2 in (False, True):
            b = _nueva_base(admin)
            bases.append(b)
            pasos = ["/errata/E1_rutas_segmentos_config.sql", "/extreme/1. tablas.sql"]
            pasos += ["/errata/E2_unique_timbradas_segmentos.sql"] if con_e2 else []
            pasos += ["/extreme/7. trigger de conteo.sql"]
            for p in pasos:
                rc.psql(b, "-q", "-v", f"ON_ERROR_STOP={0 if p.endswith('tablas.sql') else 1}", "-f", p)
            with psycopg.connect(_url("extreme_dba", b), autocommit=True) as cx, cx.cursor() as cur:
                cur.execute("INSERT INTO rutas (idruta, proceso, idrutageo) VALUES (2, 'sobusa', 3)")
                cur.execute("INSERT INTO progvehiculos (idprogramacion, idruta, proceso) VALUES (1, 2, 'sobusa')")
                cur.execute("""INSERT INTO rutas_segmentos_config (idruta, idrutageo, tipo_agrupacion,
                               "tamaño_segmento_m") VALUES (2, 3, 'distancia', 500) RETURNING id""")
                idc = cur.fetchone()[0]
                cur.execute("""INSERT INTO rutas_segmentos (id_config, idruta, idrutageo, nro_segmento, activo,
                               porciones_ids, longitud_m, geom_segmento) VALUES (%s, 2, 3, 1, true, '[]', 1096.0,
                               'SRID=4326;LINESTRING(-74.80 10.98, -74.79 10.98)')""", (idc,))
                res = []
                for i, (hora, sub, acum) in enumerate([("06:05", 3, 3), ("06:20", 2, 5)], start=1):
                    try:
                        cur.execute("""INSERT INTO conteo_pasajeros (id, fecha, idprogramacion, latitud, longitud,
                                       cantidad_subida, cantidad_bajada, acumulada_subida, acumulada_bajada)
                                       VALUES (%s, %s, 1, 10.98, -74.795, %s, 0, %s, 0)""",
                                    (i, f"2023-02-07 {hora}:00", sub, acum))
                        res.append(f"fila cruda {i} ({hora}): insertada")
                    except psycopg.Error as exc:
                        res.append(f"fila cruda {i} ({hora}): RECHAZADA — {str(exc).splitlines()[0]}")
                cur.execute("SELECT (SELECT count(*) FROM conteo_pasajeros), count(*), "
                            "coalesce(sum(subidas), 0) FROM timbradas_segmentos")
                n_crudas, n_ts, subidas = cur.fetchone()
            titulo = "CON E2" if con_e2 else "SIN E2 (llave del script 1)"
            lineas += [f"== E2 — {titulo}: un viaje pasa por el mismo segmento en dos bloques de 15 minutos"]
            lineas += [f"   {x}" for x in res]
            lineas += [f"   conteo_pasajeros: {n_crudas} filas; timbradas_segmentos: {n_ts} filas; "
                       f"Σ subidas {subidas} (Σ crudas enviadas = 5)"]
        lineas.append("")
        # H1
        with psycopg.connect(_url("extreme_dba")) as cx, cx.cursor() as cur:
            cur.execute("SET client_min_messages = warning")
            cur.execute("""SELECT r.idprogramacion FROM replica_meta.viajes_reservados r
                           JOIN public.progvehiculos p USING (idprogramacion)
                           WHERE p.apto_estadisticas_historicas ORDER BY 1 LIMIT 10""")
            viajes = [v[0] for v in cur.fetchall()]
            cx.rollback()
            con, sin = [], []
            for v in viajes:
                cur.execute("SELECT public.fn_insert_timbradas_anio(%s)", (v,))
                con.append(cur.fetchone()[0])
                cx.rollback()
                cur.execute("UPDATE public.estacionalidades_anio SET proceso = 'cootransoriente'")
                cur.execute("SELECT public.fn_insert_timbradas_anio(%s)", (v,))
                sin.append(cur.fetchone()[0])
                cx.rollback()
        lineas += ["== H1 — fn_insert_timbradas_anio sobre viajes reservados aptos (transacciones que se deshacen):",
                   f"   viajes: {viajes}",
                   f"   SIN H1 (estacionalidades_anio.proceso = 'cootransoriente'): {sin}  -> TRUE en {sum(sin)} de "
                   f"{len(sin)}",
                   f"   CON H1 (proceso = 'sobusa'): {con}  -> TRUE en {sum(con)} de {len(con)}",
                   "   Los FALSE con H1 no traen diagnóstico de la función: docs/hallazgos_extreme.md (H6) documenta "
                   "los viajes «aptos» sin fecha de fin, que devuelven FALSE sin aviso."]
    finally:
        with admin.cursor() as cur:
            for b in bases:
                cur.execute(f'DROP DATABASE IF EXISTS "{b}" WITH (FORCE)')
    (SALIDA / "replica_errata.txt").write_text("\n".join(lineas) + "\n", encoding="utf-8")


def roles() -> None:
    lineas = [f"Roles de la IA en la réplica (§11.3) ({_ahora()})", ""]
    with psycopg.connect(_url("lector_ia"), autocommit=True) as cx, cx.cursor() as cur:
        lineas.append("== lector_ia: configuración de la sesión (ALTER ROLE ... SET)")
        for p in ("default_transaction_read_only", "statement_timeout", "idle_in_transaction_session_timeout",
                  "lock_timeout", "TimeZone"):
            cur.execute(f"SHOW {p}")
            lineas.append(f"   {p} = {cur.fetchone()[0]}")
        cur.execute("SELECT count(*) FROM public.timbradas_consolidado")
        lineas.append(f"== lector_ia: SELECT count(*) FROM timbradas_consolidado -> {cur.fetchone()[0]} (correcto)")  # nosec B608  # identificadores de constantes del script; valores por parámetro
        cur.execute("SELECT count(*) FROM public.timbradas_segmentos")
        lineas.append(f"== lector_ia: SELECT count(*) FROM timbradas_segmentos -> {cur.fetchone()[0]} (correcto)")  # nosec B608  # identificadores de constantes del script; valores por parámetro
    fallos = 0
    for modo in ("sesión por defecto (solo lectura)", "después de SET default_transaction_read_only = off"):
        lineas += ["", f"== lector_ia: escrituras con {modo} — TODAS deben fallar"]
        with psycopg.connect(_url("lector_ia"), autocommit=True) as cx:
            if "off" in modo:
                cx.execute("SET default_transaction_read_only = off")
            for nombre, sql in rc.ESCRITURAS_LECTOR:
                try:
                    with cx.transaction(), cx.cursor() as cur:
                        if sql.startswith("COPY"):
                            with cur.copy(sql) as cp:
                                cp.write_row(("x",))
                        else:
                            cur.execute(sql)
                    lineas.append(f"   {nombre:<36} PERMITIDO  <-- FALLO DE SEGURIDAD")
                    fallos += 1
                except psycopg.Error as exc:
                    lineas.append(f"   {nombre:<36} rechazado [{exc.sqlstate}] {str(exc).splitlines()[0]}")
    lineas += ["", "== escritor_ia: en ai_frecuencias (debe funcionar)"]
    with psycopg.connect(_url("escritor_ia"), autocommit=True) as cx, cx.cursor() as cur:
        tabla = f"ai_frecuencias.prueba_{uuid.uuid4().hex[:8]}"
        cur.execute(f"CREATE TABLE {tabla} (x int)")
        cur.execute(f"INSERT INTO {tabla} VALUES (1), (2)")  # nosec B608  # identificadores de constantes del script; valores por parámetro
        cur.execute(f"SELECT sum(x) FROM {tabla}")  # nosec B608  # identificadores de constantes del script; valores por parámetro
        lineas.append(f"   CREATE TABLE, INSERT y SELECT en {tabla}: suma = {cur.fetchone()[0]} (correcto)")
        cur.execute(f"DROP TABLE {tabla}")
        cur.execute("CREATE TEMP TABLE paso_ingesta (x int)")
        lineas.append("   CREATE TEMP TABLE (staging de la ingesta): correcto")
    lineas.append("== escritor_ia: tablas de Extreme (debe fallar)")
    with psycopg.connect(_url("escritor_ia"), autocommit=True) as cx:
        for sql in ["SELECT count(*) FROM public.timbradas_consolidado",
                    "INSERT INTO public.timbradas_consolidado (proceso) VALUES ('x')",
                    "CREATE TABLE public.intruso (x int)", "SELECT public.fn_consolidar_timbradas_historicas()"]:
            try:
                with cx.transaction():
                    cx.execute(sql)
                lineas.append(f"   {sql:<70} PERMITIDO  <-- FALLO DE SEGURIDAD")
                fallos += 1
            except psycopg.Error as exc:
                lineas.append(f"   {sql:<70} rechazado [{exc.sqlstate}] {str(exc).splitlines()[0]}")
    lineas += ["", f"Resultado: {fallos} escrituras indebidas permitidas "
               f"({2 * len(rc.ESCRITURAS_LECTOR)} intentos de lector_ia y 4 de escritor_ia)."]
    (SALIDA / "replica_roles.txt").write_text("\n".join(lineas) + "\n", encoding="utf-8")
    if fallos:
        raise SystemExit(f"{fallos} escrituras indebidas permitidas")


def main() -> int:
    SALIDA.mkdir(parents=True, exist_ok=True)
    if not rc.docker_disponible():
        raise SystemExit(f"contenedor {rc.contenedor()} no disponible")
    init_log()
    objetos()
    with psycopg.connect(_url("extreme_dba"), autocommit=True) as admin:
        errata(admin)
    roles()
    for f in ("replica_init.log", "replica_objetos.txt", "replica_errata.txt", "replica_roles.txt"):
        print(f"escrito docs/evidencias/replica/{f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
