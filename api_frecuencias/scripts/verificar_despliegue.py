"""RNF-008 · prueba de despliegue reproducible con Docker Compose (E09; §14.2 «Instalación» y «Demostración»; RNF-001).

Todo ocurre en un proyecto compose AISLADO (por omisión «sobusa_limpio»: API en el puerto 8010, PostgreSQL en el
5440 y volúmenes propios), desde cero:
  1. construye la imagen y levanta la pila con «up -d --build» sobre volúmenes nuevos (tiempos de cada fase);
  2. el servicio «migrar» aplica las migraciones 0001…head (log de Alembic, versión, tablas, PostGIS);
  3. comprueba GET /health y el HEALTHCHECK de la imagen;
  4. crea claves de API con scripts/crear_api_key.py DENTRO del contenedor; las claves solo viven en la memoria de
     este proceso (nunca se imprimen ni se guardan) y la API se recrea con sus hashes en API_KEYS;
  5. corre la demostración de §14.2 (scripts/demo_ciclo_api.py, pasos (1) a (6), con reversión);
  6. RNF-001: SIGKILL (docker kill + docker start) y reinicio ordenado (docker compose restart) de la API a mitad de
     una ejecución; comprueba que no se pierden ni duplican lotes, predicciones ni alertas;
  7. describe la imagen (tamaño, usuario, capas) y regenera requisitos_congelados.txt con su pip freeze;
  8. «down -v» y comprueba que no quedan contenedores ni volúmenes del proyecto.
Evidencia en docs/evidencias/despliegue/: arranque_limpio.txt, migraciones.txt, demo_ciclo_api.txt, reinicio.txt e
imagen.txt (y docs/evidencias/demo_ciclo.txt con la misma demostración).

Uso:  .venv\\Scripts\\python scripts\\verificar_despliegue.py [--proyecto sobusa_limpio] [--puerto-api 8010]
          [--puerto-db 5440] [--sin-cache] [--conservar] [--sin-caida]
Nunca toca los proyectos en uso (sobusa_api, sobusa_rep). Las claves de la base de la prueba se generan al azar en
un archivo temporal que se borra al terminar.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo

import httpx

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "scripts"))
ZONA = ZoneInfo("America/Bogota")
PROTEGIDOS = {"sobusa_api", "sobusa_rep"}
E = "ai_frecuencias"
SECRETOS: list[str] = []


def ocultar(texto: str) -> str:
    for s in SECRETOS:
        if s:
            texto = texto.replace(s, "<oculto>")
    return texto


class Bitacora:
    """Líneas de un archivo de evidencia; también salen por consola (sin secretos)."""

    def __init__(self, nombre: str):
        self.nombre, self.lineas = nombre, []

    def __call__(self, *partes) -> None:
        linea = ocultar(" ".join(str(p) for p in partes))
        self.lineas.append(linea)
        print(linea, flush=True)

    def guardar(self, carpeta: Path) -> Path:
        carpeta.mkdir(parents=True, exist_ok=True)
        ruta = carpeta / self.nombre
        ruta.write_text("\n".join(self.lineas) + "\n", encoding="utf-8")
        return ruta


def ahora() -> str:
    return datetime.now(ZONA).strftime("%Y-%m-%d %H:%M:%S %z")


class Pila:
    def __init__(self, proyecto: str, archivo_env: Path, entorno: dict[str, str]):
        self.proyecto, self.archivo_env, self.entorno = proyecto, archivo_env, entorno

    def env(self) -> dict[str, str]:
        base = {k: v for k, v in os.environ.items() if k not in self.entorno}
        return base | self.entorno | {"API_ENV_FILE": str(self.archivo_env)}

    def compose(self, *args: str, timeout: float = 1800, check: bool = True) -> subprocess.CompletedProcess:
        cmd = ["docker", "compose", "-p", self.proyecto, "--env-file", str(self.archivo_env),
               "-f", "docker-compose.yml", *args]
        r = subprocess.run(cmd, cwd=RAIZ, env=self.env(), capture_output=True, text=True, encoding="utf-8",  # noqa: S603
                           errors="replace", timeout=timeout)
        if check and r.returncode != 0:
            raise RuntimeError(f"docker compose {' '.join(args)} -> {r.returncode}\n{ocultar(r.stderr[-3000:])}")
        return r

    def contenedor(self, servicio: str) -> str:
        return f"{self.proyecto}-{servicio}-1"


def docker(*args: str, timeout: float = 600, check: bool = True) -> subprocess.CompletedProcess:
    r = subprocess.run(["docker", *args], capture_output=True, text=True, encoding="utf-8", errors="replace",  # noqa: S603, S607
                       timeout=timeout)
    if check and r.returncode != 0:
        raise RuntimeError(f"docker {' '.join(args)} -> {r.returncode}\n{ocultar(r.stderr[-2000:])}")
    return r


def esperar_salud(base: str, limite_s: float = 300) -> float:
    t0 = time.time()
    while time.time() - t0 < limite_s:
        try:
            r = httpx.get(f"{base}/health", timeout=3)
            if r.status_code == 200 and r.json().get("estado") == "ok":
                return time.time() - t0
        except (httpx.HTTPError, ValueError):
            pass
        time.sleep(0.5)
    raise TimeoutError(f"{base}/health no respondió ok en {limite_s} s")


def esperar_estado_docker(nombre: str, estado: str, limite_s: float = 300) -> float:
    t0 = time.time()
    while time.time() - t0 < limite_s:
        r = docker("inspect", "-f", "{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}",
                   nombre, check=False)
        if r.stdout.strip() == estado:
            return time.time() - t0
        time.sleep(0.5)
    raise TimeoutError(f"{nombre} no llegó a {estado}")


def esperar_salida(nombre: str, limite_s: float = 600) -> tuple[float, int]:
    t0 = time.time()
    while time.time() - t0 < limite_s:
        r = docker("inspect", "-f", "{{.State.Status}} {{.State.ExitCode}}", nombre, check=False)
        partes = r.stdout.split()
        if partes and partes[0] == "exited":
            return time.time() - t0, int(partes[1])
        time.sleep(0.5)
    raise TimeoutError(f"{nombre} no terminó")


def crear_clave(pila: Pila, rol: str, usuario: str) -> tuple[str, dict]:
    """scripts/crear_api_key.py dentro del contenedor de la API; la salida se lee aquí y no se muestra."""
    r = pila.compose("exec", "-T", "api", "python", "scripts/crear_api_key.py", "--rol", rol, "--usuario", usuario)
    lineas = [x.strip() for x in r.stdout.splitlines() if x.strip()]
    clave = lineas[lineas.index(next(x for x in lineas if x.startswith("Clave para"))) + 1]
    entrada = json.loads(lineas[-1])
    SECRETOS.append(clave)
    return clave, entrada


# ------------------------------------------------------------------------------------------------ fases
def fase_arranque(pila: Pila, a, log: Bitacora) -> dict:
    t = {}
    log(f"RNF-008 · arranque limpio con Docker Compose · {ahora()} (America/Bogota)")
    log(f"Proyecto compose aislado «{a.proyecto}»: API en 127.0.0.1:{a.puerto_api}, PostgreSQL en 127.0.0.1:"
        f"{a.puerto_db}, volúmenes {a.proyecto}_datos_pg y {a.proyecto}_modelos (nuevos).")
    v = docker("version", "--format", "{{.Server.Version}}").stdout.strip()
    cv = docker("compose", "version", "--short").stdout.strip()
    log(f"Docker Engine {v}; Docker Compose {cv}; equipo Windows 11 (Docker Desktop, contenedores Linux).")
    log("Configuración: un archivo de entorno temporal generado al azar (POSTGRES_PASSWORD, SEUDONIMO_SECRETO) a "
        "partir de .env.example; no se usa el .env del equipo. PLANIFICADOR_HABILITADO=false para que la "
        "demostración sea determinista (el planificador se prueba aparte en docs/evidencias/cola/).")
    t0 = time.time()
    pila.compose("down", "-v", "--remove-orphans", check=False)
    log(f"\n0) Limpieza previa del proyecto aislado (down -v): {time.time() - t0:.1f} s")

    t0 = time.time()
    args = ["build"] + (["--no-cache"] if a.sin_cache else [])
    pila.compose(*args, timeout=3600)
    t["construccion_s"] = time.time() - t0
    log(f"1) docker compose -p {a.proyecto} build{' --no-cache' if a.sin_cache else ''}: {t['construccion_s']:.1f} s "
        "(reutiliza las capas en caché de BuildKit si ya existen; con --sin-cache se reconstruye todo)")

    t0 = time.time()
    pila.compose("up", "-d", "--build")
    t["up_retorna_s"] = time.time() - t0
    log(f"2) docker compose -p {a.proyecto} up -d --build: retorna en {t['up_retorna_s']:.1f} s "
        "(db sano -> migrar termina con 0 -> api)")
    t_db = esperar_estado_docker(pila.contenedor("db"), "healthy")
    dur, codigo = esperar_salida(pila.contenedor("migrar"))
    t["migrar_codigo"] = codigo
    log(f"   db healthy; migrar terminó con código {codigo}")
    # los dos tiempos se cuentan desde el inicio del «up»
    esperar_salud(f"http://127.0.0.1:{a.puerto_api}")
    t["health_s"] = time.time() - t0
    esperar_estado_docker(pila.contenedor("api"), "healthy")
    t["healthcheck_s"] = time.time() - t0
    log(f"3) GET /health = ok a los {t['health_s']:.1f} s del «up»; HEALTHCHECK de la imagen = healthy a los "
        f"{t['healthcheck_s']:.1f} s")
    salud = httpx.get(f"http://127.0.0.1:{a.puerto_api}/health", timeout=5).json()
    log(f"   /health -> {salud}")
    t["salud"] = salud
    t["db_healthy_tras_up_s"] = t_db
    return t


def fase_migraciones(pila: Pila, a, log: Bitacora) -> bool:
    log(f"Migraciones Alembic aplicadas por el servicio «migrar» en la base nueva · {ahora()}")
    r = pila.compose("logs", "--no-color", "--no-log-prefix", "migrar")
    log("\n$ docker compose logs migrar   (alembic upgrade head sobre volumen nuevo)")
    for linea in (r.stdout + r.stderr).splitlines():
        log("  " + linea)
    r = pila.compose("run", "--rm", "--no-deps", "-T", "migrar", "alembic", "history")
    log("\n$ alembic history")
    for linea in r.stdout.splitlines():
        log("  " + linea)
    r = pila.compose("run", "--rm", "--no-deps", "-T", "migrar", "alembic", "current")
    log("\n$ alembic current")
    actual = [x for x in r.stdout.splitlines() if x.strip()]
    for linea in actual:
        log("  " + linea)
    consultas = [
        "SELECT version()",
        "SELECT postgis_full_version()",
        f"SELECT version_num FROM {E}.alembic_version",  # nosec B608  # E es la constante del esquema
        f"SELECT count(*) AS tablas FROM pg_tables WHERE schemaname = '{E}'",  # nosec B608  # E es constante
        f"SELECT tablename FROM pg_tables WHERE schemaname = '{E}' ORDER BY 1",  # nosec B608  # E es constante
        f"SELECT inhrelid::regclass AS particion FROM pg_inherits WHERE inhparent = '{E}.feature_snapshot'::regclass "  # nosec B608  # E es constante
        "ORDER BY 1",
        f"SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = '{E}' AND indexdef ILIKE '%USING gist%'",  # nosec B608  # E es constante
        # pg_stat_statements en la base de resultados (command del servicio db + initdb_resultados/)
        "SHOW shared_preload_libraries",
        "SELECT extname, extversion FROM pg_extension ORDER BY 1",
    ]
    args = ["exec", "-T", "db", "psql", "-U", "sobusa", "-d", "ai_frecuencias", "-P", "pager=off"]
    for q in consultas:
        args += ["-c", q]
    r = pila.compose(*args, check=False)
    log("\n$ psql: versión del servidor, PostGIS, versión de Alembic, tablas, particiones, el índice GiST y "
        "pg_stat_statements")
    for linea in (r.stdout + r.stderr).splitlines():
        log("  " + linea)
    # idempotencia: volver a migrar no cambia nada
    r = pila.compose("run", "--rm", "--no-deps", "-T", "migrar", "alembic", "upgrade", "head")
    log("\n$ alembic upgrade head (segunda vez): no hay nada pendiente")
    for linea in (r.stdout + r.stderr).splitlines():
        log("  " + linea)
    head = pila.compose("run", "--rm", "--no-deps", "-T", "migrar", "alembic", "heads").stdout.split()
    ok = bool(actual) and bool(head) and actual[0].split()[0] == head[0]
    log(f"\nResultado: versión actual {actual[0] if actual else '?'} = head {head[0] if head else '?'} -> "
        f"{'OK' if ok else 'FALLA'}")
    return ok


def fase_claves(pila: Pila, a, log: Bitacora) -> dict[str, str]:
    claves, entradas = {}, {}
    for rol, usuario in (("admin", "verificacion_admin"), ("operador", "verificacion_operador")):
        clave, entrada = crear_clave(pila, rol, usuario)
        claves[rol] = clave
        entradas.update(entrada)
    pila.entorno["API_KEYS"] = json.dumps(entradas, ensure_ascii=False)
    SECRETOS.append(pila.entorno["API_KEYS"])
    t0 = time.time()
    pila.compose("up", "-d", "--no-deps", "api")
    t_salud = esperar_salud(f"http://127.0.0.1:{a.puerto_api}")
    log(f"4) Claves de API: 2 creadas con scripts/crear_api_key.py dentro del contenedor (roles admin y operador); "
        f"la API se recreó con sus hashes en API_KEYS y respondió /health en {time.time() - t0:.1f} s "
        f"(salud {t_salud:.1f} s). Las claves no se imprimen ni se guardan.")
    base = f"http://127.0.0.1:{a.puerto_api}"
    sin = httpx.get(f"{base}/api/v1/alerts", timeout=10).status_code
    con = httpx.get(f"{base}/api/v1/alerts", headers={"X-API-Key": claves["operador"]}, timeout=30).status_code
    rol = httpx.post(f"{base}/api/v1/models/rollback", json={}, headers={"X-API-Key": claves["operador"]},
                     timeout=30).status_code
    met = httpx.get(f"{base}/metrics", timeout=10).status_code
    seud = pila.compose("exec", "-T", "api", "python", "-c",
                        "import os; print(len(os.environ.get('SEUDONIMO_SECRETO', '')))").stdout.strip()
    log(f"   GET /api/v1/alerts sin clave -> {sin} (esperado 401); con la clave operador -> {con} (esperado 200); "
        f"POST /api/v1/models/rollback con la clave operador -> {rol} (esperado 403, exige admin); "
        f"GET /metrics -> {met}; SEUDONIMO_SECRETO llega al contenedor con {seud} caracteres (no se muestra)")
    claves["_ok"] = str(sin == 401 and con == 200 and rol == 403 and met == 200 and seud == "64")
    return claves


def fase_demo(a, clave_admin: str, log: Bitacora, salida: Path) -> bool:
    destino = salida / "demo_ciclo_api.txt"
    env = os.environ | {"SOBUSA_API_URL": f"http://127.0.0.1:{a.puerto_api}", "SOBUSA_API_KEY": clave_admin,
                        "PYTHONIOENCODING": "utf-8"}
    t0 = time.time()
    r = subprocess.run([sys.executable, str(RAIZ / "scripts" / "demo_ciclo_api.py"), "--hasta", a.hasta.isoformat(),  # noqa: S603
                        "--corte", a.corte.isoformat(), "--revertir", "--salida", str(destino)],
                       cwd=RAIZ, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=3600)
    log(f"5) Demostración §14.2 (scripts/demo_ciclo_api.py --revertir) -> código {r.returncode} en "
        f"{time.time() - t0:.1f} s; salida en {destino.relative_to(RAIZ).as_posix()}")
    if r.returncode != 0:
        log("   stderr:", ocultar(r.stderr[-2000:]))
    if destino.exists():
        texto = ocultar(destino.read_text(encoding="utf-8"))
        destino.write_text(texto, encoding="utf-8")
        pasos = [n for n in range(1, 7) if f"\n({n}) " in "\n" + texto]
        log(f"   pasos impresos: {pasos} (se esperan 1 a 6)")
        # docs/evidencias/demo_ciclo.txt se refresca con esta corrida; la de 8-nov queda como demo_ciclo_8nov.txt
        ev = RAIZ / "docs" / "evidencias"
        antiguo = ev / "demo_ciclo_8nov.txt"
        if (ev / "demo_ciclo.txt").exists() and not antiguo.exists():
            shutil.copyfile(ev / "demo_ciclo.txt", antiguo)
        cabecera = (f"Ciclo de demostración (§14.2) sobre la pila Docker Compose aislada «{a.proyecto}», creada desde "
                    "cero por scripts/verificar_despliegue.py. Copia de docs/evidencias/despliegue/demo_ciclo_api.txt; "
                    "la corrida anterior (8-nov, scripts/demo_ciclo.py) está en demo_ciclo_8nov.txt.\n\n")
        (ev / "demo_ciclo.txt").write_text(cabecera + texto, encoding="utf-8")
        return r.returncode == 0 and pasos == [1, 2, 3, 4, 5, 6]
    return False


def fase_sin_demo(a, clave: str, log: Bitacora) -> bool:
    """Sin la demostración: carga inicial y un día nuevo, que sirve de referencia a la prueba RNF-001."""
    cli = httpx.Client(base_url=f"http://127.0.0.1:{a.puerto_api}", headers={"X-API-Key": clave}, timeout=30)
    ok = True
    for etiqueta, d in (("carga inicial", a.hasta), ("día nuevo (referencia)", a.hasta + timedelta(days=1))):
        t0 = time.time()
        r = cli.post("/api/v1/frequency/executions", json={"hasta": d.isoformat()})
        r.raise_for_status()
        ident = r.json()["execution_id"]
        e: dict = {}
        while time.time() - t0 < 2400:
            e = cli.get(f"/api/v1/frequency/executions/{ident}").json()
            if e["estado"] in ("ok", "error"):
                break
            time.sleep(1)
        log(f"5) {etiqueta} hasta {d}: {e.get('estado')} en {time.time() - t0:.1f} s; filas leídas "
            f"{e.get('filas_leidas')}, predicciones {e.get('predicciones')}, alertas {e.get('alertas')}")
        ok = ok and e.get("estado") == "ok"
    log("   (la demostración completa de §14.2 se corre sin --sin-demo; ver demo_ciclo_api.txt)")
    return ok


def fase_caida(pila: Pila, a, clave: str, log: Bitacora) -> bool:
    """RNF-001 con la pila compose: SIGKILL real y reinicio ordenado a mitad de una ejecución."""
    import prueba_caida as pc
    from sqlalchemy import create_engine, text

    url = (f"postgresql+psycopg://sobusa:{quote(pila.entorno['POSTGRES_PASSWORD'], safe='')}@127.0.0.1:"
           f"{a.puerto_db}/ai_frecuencias")
    m = create_engine(url, pool_pre_ping=True)
    base = f"http://127.0.0.1:{a.puerto_api}"
    cli = httpx.Client(base_url=base, headers={"X-API-Key": clave}, timeout=10)
    log(f"RNF-001 · recuperación ante reinicios de la API en la pila Docker Compose «{a.proyecto}» · {ahora()}")
    log("La API corre como en producción (uvicorn en el contenedor, cola en PostgreSQL con reserva que vence, "
        "REANUDAR_EJECUCIONES=true). Escenarios, cada uno con un día nuevo de datos:")
    log("  A) SIGKILL: docker kill (señal 9 al proceso de la API, sin apagado ordenado) y docker start del mismo "
        "contenedor (misma identidad de réplica);")
    log("  B) reinicio ordenado: docker compose restart api (SIGTERM y arranque).")
    log("Referencia: una ejecución del día sin interrupción. Las comprobaciones son las de scripts/prueba_caida.py.")
    with m.connect() as c:
        marca = c.execute(text(f"SELECT max(marca_agua_nueva) FROM {E}.execution_log WHERE tipo = 'frecuencia' "  # nosec B608  # E es la constante del esquema
                               "AND estado = 'ok'")).scalar()
    d0 = marca.astimezone(ZONA).date() + timedelta(days=1)

    def post(d: date, etiqueta: str) -> str:
        r = cli.post("/api/v1/frequency/executions", json={"hasta": d.isoformat()},
                     headers={"X-Correlation-Id": f"rnf001-{etiqueta}"})
        r.raise_for_status()
        return r.json()["execution_id"]

    def leer(ident: str) -> dict | None:
        try:
            return cli.get(f"/api/v1/frequency/executions/{ident}").json()
        except (httpx.HTTPError, ValueError):
            return None

    def esperar_fin(ident: str, limite_s: float = 2400) -> dict:
        fin = time.time() + limite_s
        while time.time() < fin:
            d = leer(ident)
            if d and d["estado"] in ("ok", "error"):
                return d
            time.sleep(0.3)
        raise TimeoutError(ident)

    fallas: list[str] = []
    # referencia: la última ejecución normal con datos nuevos (la del día nuevo de la demostración, sin interrupción)
    with m.connect() as c:
        ref_id = c.execute(text(f"SELECT execution_id FROM {E}.execution_log WHERE tipo = 'frecuencia' "  # nosec B608  # E es la constante del esquema
                                "AND estado = 'ok' AND filas_leidas > 0 ORDER BY creado_en DESC LIMIT 1")).scalar()
    if ref_id is None:
        ref_id = post(d0, "referencia")
        esperar_fin(ref_id)
        d0 += timedelta(days=1)
    ref_id = str(ref_id)
    ref = pc.medir(m, ref_id)
    log(f"\n0) Referencia sin interrupción ({ref_id}, hasta {ref['parametros'].get('hasta')}):")
    pc._LINEAS.clear()
    pc.resumen("referencia", ref)
    fallas += pc.comprobar("referencia", ref, ref, None, caida=False)
    for linea in pc._LINEAS:
        log(linea)
    anterior = ref
    escenarios = (("A", "SIGKILL (docker kill + docker start)"), ("B", "reinicio ordenado (docker compose restart)"))
    for n, (letra, nombre) in enumerate(escenarios, start=1):
        dia = d0 + timedelta(days=n - 1)   # un día nuevo por escenario, contiguo a la marca de agua
        ident = post(dia, f"escenario-{letra}")
        t_ini = time.time()
        etapa_kill = None
        while time.time() - t_ini < 120:
            d = leer(ident)
            if d and d["estado"] == "corriendo" and d.get("etapa") not in (None, "", "en_cola"):
                etapa_kill = d.get("etapa")
                if etapa_kill not in ("lectura_incremental",) or time.time() - t_ini > 1.5:
                    break
            if d and d["estado"] in ("ok", "error"):
                break
            time.sleep(0.05)
        with m.connect() as c:
            visibles = c.execute(text(f"SELECT count(*) FROM {E}.prediction WHERE execution_id = :i"),  # nosec B608  # E es constante; :i va enlazado
                                 {"i": ident}).scalar()
        t_corte = time.time()
        if letra == "A":
            docker("kill", pila.contenedor("api"))
            docker("start", pila.contenedor("api"))
        else:
            pila.compose("restart", "api")
        vuelta = esperar_salud(base)
        d = esperar_fin(ident)
        total = time.time() - t_corte
        medido = pc.medir(m, ident)
        intentos = [r for _, _, r in medido["intentos_traza"]]
        hubo_corte = "abandonado" in intentos or medido["intentos"] > 1
        log(f"\n{n}) Escenario {letra}: {nombre} durante «{etapa_kill}» ({ident}, hasta {dia}); predicciones visibles "
            f"desde fuera antes del corte: {visibles}")
        log(f"   API de vuelta en {vuelta:.1f} s; ejecución {d['estado']} {total:.1f} s después del corte; "
            f"traza de intentos {intentos}")
        if not hubo_corte:
            log("   La ejecución terminó antes de que el proceso se detuviera (apagado ordenado): igual se comprueba "
                "que no se perdió ni duplicó nada.")
        pc._LINEAS.clear()
        pc.resumen(f"escenario {letra}", medido)
        fallas += pc.comprobar(f"escenario {letra}", medido, ref, anterior, caida=hubo_corte)
        for linea in pc._LINEAS:
            log(linea)
        if letra == "A" and not hubo_corte:
            fallas.append("escenario A: el SIGKILL no cayó dentro de la ejecución")
        anterior = medido
    with m.connect() as c:
        dup = c.execute(text(f"SELECT count(*) - count(DISTINCT (execution_id, ruta, instante, horizonte_min)) "  # nosec B608  # E es la constante del esquema
                             f"FROM {E}.prediction")).scalar()
        pend = c.execute(text(f"SELECT count(*) FROM {E}.execution_log "  # nosec B608  # E es la constante del esquema
                              "WHERE estado IN ('en_cola', 'corriendo')")).scalar()
    log(f"\nGlobal: predicciones duplicadas en toda la base = {dup}; ejecuciones pendientes o colgadas = {pend}")
    if dup or pend:
        fallas.append("duplicados o ejecuciones colgadas")
    log(f"Resultado RNF-001: {'OK' if not fallas else 'FALLA: ' + '; '.join(fallas)}")
    m.dispose()
    return not fallas


def fase_imagen(pila: Pila, a, log: Bitacora) -> None:
    imagen = f"{a.proyecto}-api"
    info = json.loads(docker("image", "inspect", imagen).stdout)[0]
    log(f"Imagen de la API ({imagen}) · {ahora()}")
    log(f"  id {info['Id'][:19]}…, creada {info.get('Created')}")
    log(f"  tamaño (contenido de las capas, docker image inspect .Size): {info['Size'] / 1e6:.1f} MB")
    r = docker("images", imagen, "--format", "{{.Size}}")
    log(f"  tamaño en disco (docker images): {r.stdout.strip()}")
    cfg = info.get("Config", {})
    log(f"  usuario: {cfg.get('User')}; puerto: {list((cfg.get('ExposedPorts') or {}).keys())}; "
        f"comando: {cfg.get('Cmd')}")
    log(f"  HEALTHCHECK: {(cfg.get('Healthcheck') or {}).get('Test')}")
    publicas = [e for e in cfg.get("Env", []) if not e.startswith(("PATH=", "GPG_KEY=", "PYTHON_SHA256="))]
    log(f"  variables de la imagen (ninguna secreta; se omiten PATH y las de verificación de la imagen base): "
        f"{publicas}")
    r = docker("run", "--rm", imagen, "sh", "-c",
               "python --version; id; du -sh /usr/local/lib/python3.11/site-packages /app/app /app/datos "
               "/app/scripts /app/alembic 2>/dev/null; du -s /usr/local/lib/python3.11/site-packages/* 2>/dev/null "
               "| sort -n | tail -12 | awk '{printf \"%.0f MB %s\\n\", $1/1024, $2}'")
    log("\n$ dentro de la imagen: python, usuario y tamaños")
    for linea in r.stdout.splitlines():
        log("  " + linea)
    r = docker("history", "--format", "{{.Size}}\t{{.CreatedBy}}", imagen)
    log("\n$ docker history (capas)")
    for linea in r.stdout.splitlines():
        log("  " + linea[:160])
    pruebas = docker("run", "--rm", imagen, "python", "-c",
                     "import importlib.util as u; print([m for m in ('pytest','ruff','bandit','coverage','httpx',"
                     "'skl2onnx','onnx','schemathesis') if u.find_spec(m)])").stdout.strip()
    log(f"\nHerramientas de desarrollo dentro de la imagen (debe ser []): {pruebas}")
    freeze = docker("run", "--rm", imagen, "pip", "freeze").stdout
    paquetes = [x for x in freeze.splitlines() if x.strip()]
    cabecera = [
        "# Versiones EXACTAS instaladas en la imagen Docker de la API (pip freeze dentro de la imagen).",
        f"# Generado por scripts/verificar_despliegue.py el {ahora()} a partir de la imagen {imagen} "
        f"(python:3.11-slim, {len(paquetes)} paquetes).",
        "# Es el registro de lo que corre; para instalar use requirements.txt (ejecución) o requirements-dev.txt "
        "(desarrollo y CI).",
    ]
    (RAIZ / "requisitos_congelados.txt").write_text("\n".join(cabecera + paquetes) + "\n", encoding="utf-8")
    log(f"requisitos_congelados.txt regenerado con el pip freeze de la imagen: {len(paquetes)} paquetes")
    # lo instalado en la imagen debe ser exactamente requirements.txt (con los marcadores de Linux y Python 3.11)
    from packaging.requirements import Requirement
    from packaging.utils import canonicalize_name

    entorno = {"python_version": "3.11", "python_full_version": "3.11.18", "sys_platform": "linux",
               "platform_system": "Linux", "os_name": "posix", "platform_machine": "x86_64",
               "implementation_name": "cpython", "platform_python_implementation": "CPython", "extra": ""}
    fijados = {}
    for linea in (RAIZ / "requirements.txt").read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if linea and not linea.startswith("#"):
            req = Requirement(linea)
            if req.marker is None or req.marker.evaluate(entorno):
                fijados[canonicalize_name(req.name)] = str(req.specifier).lstrip("=")
    instalados = {canonicalize_name(x.split("==")[0]): x.split("==", 1)[1] for x in paquetes if "==" in x}
    distintos = sorted(k for k in set(fijados) | set(instalados) if fijados.get(k) != instalados.get(k))
    log(f"pip freeze de la imagen frente a requirements.txt: {len(instalados)} instalados, {len(fijados)} fijados, "
        f"diferencias {distintos} ({'idénticos' if not distintos else 'NO coinciden'})")


def fase_bajar(pila: Pila, a, log: Bitacora) -> bool:
    t0 = time.time()
    pila.compose("down", "-v", "--remove-orphans")
    filtro = f"label=com.docker.compose.project={a.proyecto}"
    cont = docker("ps", "-a", "--filter", filtro, "--format", "{{.Names}}").stdout.split()
    vols = docker("volume", "ls", "--filter", filtro, "--format", "{{.Name}}").stdout.split()
    log(f"8) docker compose -p {a.proyecto} down -v: {time.time() - t0:.1f} s; contenedores restantes {cont}, "
        f"volúmenes restantes {vols}")
    return not cont and not vols


ESCRITURAS = ("INSERT", "UPDATE", "DELETE", "MERGE", "CREATE", "ALTER", "DROP", "TRUNCATE", "GRANT", "REVOKE", "COPY")


def verificar_integrado(a) -> int:
    """Modo integrado (docker-compose.integracion.yml) contra la réplica que YA está corriendo en «sobusa_rep».

    Construye la imagen, migra con escritor_ia (run --rm --no-deps), levanta SOLO la API (up --no-deps; la réplica y su
    volumen no se recrean ni se reinician), corre una ejecución y comprueba con pg_stat_statements qué sentencias
    corrió cada usuario técnico. Al final retira solo api y migrar. Evidencia: modo_integrado.txt.
    """
    import replica_comun as rc
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url

    log = Bitacora("modo_integrado.txt")
    proyecto, op = "sobusa_rep", "sobusa_rep-operacional-1"
    base = f"http://127.0.0.1:{a.puerto_integrado}"
    archivos = ["-f", "docker-compose.yml", "-f", "docker-compose.integracion.yml", "--profile", "integracion"]
    entorno: dict[str, str] = {}

    def compose(*args: str, check: bool = True, timeout: float = 1800) -> subprocess.CompletedProcess:
        r = subprocess.run(["docker", "compose", "-p", proyecto, *archivos, *args], cwd=RAIZ,  # noqa: S603, S607
                           env=os.environ | entorno, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout)
        if check and r.returncode != 0:
            raise RuntimeError(f"docker compose {' '.join(args)} -> {r.returncode}\n{ocultar(r.stderr[-3000:])}")
        return r

    def huella() -> str:
        formato = ("{{.Id}} inicio={{.State.StartedAt}} estado={{.State.Status}} "
                   "volumenes={{range .Mounts}}{{if eq .Type \"volume\"}}{{.Name}} {{end}}{{end}}")
        return docker("inspect", "-f", formato, op).stdout.strip()

    urls = {}
    for rol in ("extreme_dba", "lector_ia", "escritor_ia"):
        u = rc.url_rol(rol)
        if not u:
            raise SystemExit(f"Falta la clave de {rol} en el .env local")
        u = u.replace("postgresql://", "postgresql+psycopg://")
        SECRETOS.append(make_url(u).password or "")
        urls[rol] = u
    dba = create_engine(urls["extreme_dba"])

    def sentencias() -> dict[tuple[str, int], tuple[int, str]]:
        with dba.connect() as c:
            filas = c.execute(text("SELECT r.rolname, s.queryid, s.calls, s.query FROM pg_stat_statements s "
                                   "JOIN pg_roles r ON r.oid = s.userid "
                                   "WHERE r.rolname IN ('lector_ia', 'escritor_ia')")).all()
        return {(f[0], int(f[1])): (int(f[2]), f[3]) for f in filas}

    vol_antes = docker("volume", "ls", "--format", "{{.Name}}").stdout.split()
    antes = huella()
    log(f"Modo integrado con la réplica de la base operacional · {ahora()} (America/Bogota)")
    log(f"Proyecto compose «{proyecto}» (el de la réplica, para compartir su red); API en {base}.")
    log(f"Contenedor de la réplica ANTES: {antes}")
    t0 = time.time()
    compose("build", "api", "migrar", timeout=3600)
    log(f"\n1) build api migrar: {time.time() - t0:.1f} s")
    r = compose("run", "--rm", "--no-deps", "-T", "migrar")
    log("2) run --rm --no-deps migrar (alembic upgrade head como escritor_ia en la base operacional, esquema "
        "ai_frecuencias):")
    for linea in (r.stdout + r.stderr).splitlines():
        if "alembic" in linea or "Running" in linea:
            log("   " + linea.strip())
    r = compose("run", "--rm", "--no-deps", "-T", "api", "python", "scripts/crear_api_key.py", "--rol", "analista",
                "--usuario", "verificacion_integrado")
    lineas = [x.strip() for x in r.stdout.splitlines() if x.strip()]
    clave = lineas[lineas.index(next(x for x in lineas if x.startswith("Clave para"))) + 1]
    SECRETOS.append(clave)
    entorno["API_KEYS"] = lineas[-1]
    SECRETOS.append(entorno["API_KEYS"])
    previas = sentencias()
    t0 = time.time()
    compose("up", "-d", "--no-deps", "api")
    t_salud = esperar_salud(base)
    salud = httpx.get(f"{base}/health", timeout=5).json()
    log(f"3) Clave de rol analista creada dentro del contenedor (no se muestra); up -d --no-deps api: /health ok en "
        f"{time.time() - t0:.1f} s (salud {t_salud:.1f} s) -> {salud}")
    cli = httpx.Client(base_url=base, headers={"X-API-Key": clave}, timeout=30)
    t0 = time.time()
    r = cli.post("/api/v1/frequency/executions", json={}, headers={"X-Correlation-Id": "modo-integrado"})
    r.raise_for_status()
    ident = r.json()["execution_id"]
    d: dict = {}
    while time.time() - t0 < 900:
        d = cli.get(f"/api/v1/frequency/executions/{ident}").json()
        if d["estado"] in ("ok", "error"):
            break
        time.sleep(1)
    lectura = (d.get("metricas") or {}).get("lectura") or {}
    log(f"4) POST /api/v1/frequency/executions -> {ident}: {d.get('estado')} en {time.time() - t0:.1f} s; filas "
        f"leídas {d.get('filas_leidas')}, marca de agua {d.get('marca_agua_anterior')} -> {d.get('marca_agua_nueva')}; "
        f"predicciones {d.get('predicciones')}, recomendaciones {d.get('recomendaciones')}, alertas {d.get('alertas')}")
    log(f"   lectura incremental: tabla {lectura.get('tabla')}, desde {lectura.get('desde')}, leídas "
        f"{lectura.get('leidas')}, nuevas {lectura.get('nuevas')}, repetidas por el solape "
        f"{lectura.get('repetidas_solape')}")
    time.sleep(1)
    nuevas = sentencias()
    fallas = []
    log("\n5) Sentencias que corrió cada usuario técnico durante la ejecución (pg_stat_statements, diferencia de "
        "llamadas antes/después):")
    for rol in ("lector_ia", "escritor_ia"):
        tipos: dict[str, int] = {}
        ejemplos: list[str] = []
        for (r_, qid), (calls, q) in nuevas.items():
            dif = calls - previas.get((r_, qid), (0, ""))[0]
            if r_ != rol or dif <= 0:
                continue
            tipo = (q.strip().split(None, 1) or ["?"])[0].upper()
            tipos[tipo] = tipos.get(tipo, 0) + dif
            if tipo in ESCRITURAS or tipo in ("SELECT", "WITH"):
                ejemplos.append(f"{dif:>4} x {' '.join(q.split())[:150]}")
        log(f"   {rol}: {dict(sorted(tipos.items()))}")
        for e in sorted(ejemplos, key=lambda x: ("demanda" not in x, x))[:10]:
            log(f"      {e}")
        escritas = {t for t in tipos if t in ESCRITURAS}
        if rol == "lector_ia" and escritas:
            fallas.append(f"lector_ia ejecutó {escritas}")
        if rol == "lector_ia" and not tipos.get("SELECT"):
            fallas.append("lector_ia no leyó nada")
        if rol == "escritor_ia" and not escritas:
            fallas.append("escritor_ia no escribió nada")
        if rol == "escritor_ia":
            fuera = [q for (r_, _), (c_, q) in nuevas.items() if r_ == rol and (q.strip().split(None, 1) or [""])[0]
                     .upper() in ("INSERT", "UPDATE", "DELETE") and "ai_frecuencias." not in q]
            if fuera:
                fallas.append("escritor_ia escribió fuera de ai_frecuencias")
            log(f"      escrituras de escritor_ia fuera del esquema ai_frecuencias: {len(fuera)}")
    with dba.connect() as c:
        roles = c.execute(text("SELECT rolname, rolconfig FROM pg_roles WHERE rolname IN ('lector_ia', 'escritor_ia') "
                               "ORDER BY 1")).all()
        fila = c.execute(text("SELECT estado, filas_leidas, marca_agua_nueva FROM ai_frecuencias.execution_log "
                              "WHERE execution_id = :i"), {"i": ident}).first()
    log("\n6) Configuración de los roles en la réplica:")
    for rol, cfg in roles:
        log(f"   {rol}: {cfg}")
    log(f"   fila de la ejecución en operacional.ai_frecuencias.execution_log: {tuple(fila) if fila else None}")
    import psycopg

    with psycopg.connect(urls["lector_ia"].replace("postgresql+psycopg://", "postgresql://")) as conn:
        try:
            conn.execute("CREATE TABLE ai_frecuencias.prueba_escritura_lector (x int)")
            resultado = "PERMITIDO (falla)"
            fallas.append("lector_ia pudo crear una tabla")
        except psycopg.Error as exc:
            resultado = f"rechazado: {type(exc).__name__}: {str(exc).splitlines()[0]}"
        conn.rollback()
    log(f"   intento de escritura como lector_ia (dentro de una transacción que se revierte): {resultado}")
    compose("rm", "-s", "-f", "api", "migrar")
    if f"{proyecto}_modelos" not in vol_antes:
        docker("volume", "rm", f"{proyecto}_modelos", check=False)
    for imagen in (f"{proyecto}-api", f"{proyecto}-migrar"):
        docker("rmi", imagen, check=False)
    despues = huella()
    restos = docker("ps", "-a", "--filter", f"label=com.docker.compose.project={proyecto}", "--format",
                    "{{.Names}}").stdout.split()
    log(f"\n7) Retiro: rm -s -f api migrar. Contenedores que quedan en el proyecto: {restos}")
    log(f"Contenedor de la réplica DESPUÉS: {despues}")
    if despues != antes:
        fallas.append("el contenedor de la réplica cambió")
    log(f"   réplica intacta (mismo contenedor, mismo inicio, mismo volumen): {despues == antes}")
    if d.get("estado") != "ok":
        fallas.append(f"la ejecución terminó en {d.get('estado')}")
    if salud.get("fuente") != "postgres":
        fallas.append("la API no reporta fuente postgres")
    log(f"\nResultado del modo integrado: {'OK' if not fallas else 'FALLA: ' + '; '.join(fallas)}")
    dba.dispose()
    log.guardar(a.salida)
    return 0 if not fallas else 1


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--proyecto", default="sobusa_limpio")
    p.add_argument("--puerto-api", type=int, default=8010)
    p.add_argument("--puerto-db", type=int, default=5440)
    p.add_argument("--hasta", type=date.fromisoformat, default=date(2025, 8, 30))
    p.add_argument("--corte", type=date.fromisoformat, default=date(2025, 9, 30))
    p.add_argument("--salida", type=Path, default=RAIZ / "docs" / "evidencias" / "despliegue")
    p.add_argument("--sin-cache", action="store_true", help="construir la imagen con --no-cache")
    p.add_argument("--conservar", action="store_true", help="no hacer down -v al final (para inspeccionar)")
    p.add_argument("--sin-caida", action="store_true", help="omitir la prueba RNF-001")
    p.add_argument("--sin-demo", action="store_true",
                   help="omitir la demostración (carga inicial y un día de referencia para RNF-001)")
    p.add_argument("--modo-integrado", action="store_true",
                   help="en lugar de la pila aislada, verificar docker-compose.integracion.yml contra la réplica "
                        "que ya corre en sobusa_rep (no la recrea; retira solo api y migrar al final)")
    p.add_argument("--puerto-integrado", type=int, default=8302)
    a = p.parse_args()
    if a.modo_integrado:
        return verificar_integrado(a)
    if a.proyecto in PROTEGIDOS:
        raise SystemExit(f"El proyecto {a.proyecto} está en uso: use un proyecto aislado (p. ej. sobusa_limpio)")
    carpeta = Path(tempfile.mkdtemp(prefix="sobusa_despliegue_"))
    entorno = {
        "POSTGRES_DB": "ai_frecuencias", "POSTGRES_USER": "sobusa", "POSTGRES_PASSWORD": secrets.token_hex(16),
        "SEUDONIMO_SECRETO": secrets.token_hex(32), "API_PUERTO_HOST": str(a.puerto_api),
        "DB_PUERTO_HOST": str(a.puerto_db), "ENTORNO": "demo", "AUTH_HABILITADA": "true",
        "PLANIFICADOR_HABILITADO": "false", "REANUDAR_EJECUCIONES": "true", "FUENTE": "parquet", "LOG_NIVEL": "INFO",
        "API_KEYS": "",
    }
    SECRETOS.extend([entorno["POSTGRES_PASSWORD"], entorno["SEUDONIMO_SECRETO"]])
    plantilla = (RAIZ / ".env.example").read_text(encoding="utf-8").splitlines()
    claves_plantilla = {k for k in entorno}
    lineas = [x for x in plantilla if not (x.split("=", 1)[0].strip() in claves_plantilla and "=" in x)]
    lineas += [f"{k}={v}" for k, v in entorno.items() if k != "API_KEYS"]
    archivo_env = carpeta / "despliegue.env"
    archivo_env.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    pila = Pila(a.proyecto, archivo_env, entorno)
    arranque, migra = Bitacora("arranque_limpio.txt"), Bitacora("migraciones.txt")
    reinicio, imagen = Bitacora("reinicio.txt"), Bitacora("imagen.txt")
    resultados: dict[str, bool] = {}
    t_total = time.time()
    try:
        t = fase_arranque(pila, a, arranque)
        resultados["arranque desde cero y /health"] = t["migrar_codigo"] == 0 and t["salud"].get("estado") == "ok"
        resultados["migraciones 0001…head"] = fase_migraciones(pila, a, migra)
        arranque(f"   migraciones: ver migraciones.txt ({'OK' if resultados['migraciones 0001…head'] else 'FALLA'})")
        claves = fase_claves(pila, a, arranque)
        resultados["claves de API por rol y autenticación"] = claves.pop("_ok") == "True"
        if a.sin_demo:
            resultados["carga inicial y día de referencia"] = fase_sin_demo(a, claves["admin"], arranque)
        else:
            resultados["demostración §14.2 (pasos 1 a 6)"] = fase_demo(a, claves["admin"], arranque, a.salida)
        if not a.sin_caida:
            # POST /frequency/executions exige el rol analista: se usa la clave admin de la verificación
            resultados["RNF-001 reinicios sin pérdidas"] = fase_caida(pila, a, claves["admin"], reinicio)
            ok = resultados["RNF-001 reinicios sin pérdidas"]
            arranque(f"6) RNF-001: ver reinicio.txt ({'OK' if ok else 'FALLA'})")
        fase_imagen(pila, a, imagen)
        arranque("7) Imagen: ver imagen.txt (tamaño, usuario sin privilegios, capas, pip freeze)")
    except Exception as exc:  # noqa: BLE001 - se deja constancia y se baja la pila igual
        arranque(f"ERROR: {ocultar(str(exc))}")
        resultados["sin errores inesperados"] = False
        try:
            logs = pila.compose("logs", "--no-color", "--tail", "80", "api", check=False).stdout
            arranque("Últimas líneas del log de la API:\n" + ocultar(logs))
        except Exception as exc2:  # noqa: BLE001
            arranque(f"(sin log de la API: {exc2})")
    finally:
        if not a.conservar:
            try:
                resultados["down -v sin restos"] = fase_bajar(pila, a, arranque)
            except Exception as exc:  # noqa: BLE001
                arranque(f"ERROR al bajar la pila: {ocultar(str(exc))}")
                resultados["down -v sin restos"] = False
        shutil.rmtree(carpeta, ignore_errors=True)
    arranque(f"\nResumen ({(time.time() - t_total) / 60:.1f} min en total):")
    for nombre, ok in resultados.items():
        arranque(f"  [{'OK' if ok else 'FALLA'}] {nombre}")
    todo = all(resultados.values()) and bool(resultados)
    arranque(f"Resultado global: {'OK' if todo else 'FALLA'}")
    for b in (arranque, migra, reinicio, imagen):
        if b.lineas:
            b.guardar(a.salida)
    return 0 if todo else 1


if __name__ == "__main__":
    sys.exit(main())
