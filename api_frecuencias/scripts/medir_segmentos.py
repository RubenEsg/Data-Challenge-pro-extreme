"""RNF-002, §7.1 y §14.1 «Carga»: mide con k6 la capa de segmentos y la carga con el volumen acordado contra una API
PROPIA en modo integrado, y deja la evidencia en docs/evidencias/pruebas/.

La API es uvicorn de ESTE checkout en 127.0.0.1:<puerto> (Docker Desktop la alcanza como host.docker.internal), con:
- DATABASE_URL: la base LOCAL --base-datos del servidor de .env (5433), con el volumen de un año sembrado
  (scripts/sembrar_volumen.py); se migra a head antes de empezar;
- FUENTE=postgres y FUENTE_DATABASE_URL: la réplica operacional local (5434) con el usuario de solo lectura lector_ia;
- autenticación encendida con una clave de rol analista NUEVA en cada corrida (solo por entorno, nunca se imprime);
- un trabajador de la cola (TRABAJADORES=1) y el planificador apagado;
- DATA_DIR y MODELOS_DIR en una copia temporal de datos/ (cola_servidor.datos_de_la_base): si el ciclo de la ingesta
  hace que la política de aprendizaje entrene un candidato, queda en la copia y no en datos/ del repositorio.

Pasos (--pasos, en este orden):
  refresco   POST /api/v1/segmentos/estadisticas/refrescar {modo: completo} y espera el trabajo (tramos, duración)
  en_frio    reinicia la API y corre k6/en_frio.js: primera petición a cada ruta (frío) y segunda (caliente)
  segmentos  k6/segmentos.js: 50 usuarios sobre /segmentos/estadisticas y /catalogos/segmentos durante un refresco
  consultas  k6/consultas.js con el volumen acordado (MIN_PREDICCIONES=3300, MIN_ALERTAS=8000)
  ingesta    k6/consultas_durante_ingesta.js: ingesta incremental desde la réplica mientras 30 usuarios consultan
Evidencia: <salida>/k6_segmentos.txt (lectura) y k6_segmentos_<paso>.json (resúmenes de k6). La API se detiene al
final, también si un paso falla. Nunca escribe en la réplica: solo la lee con lector_ia.

Uso (desde EntregaFinal/api_frecuencias, con la réplica y el PostgreSQL local arriba):
  python scripts/sembrar_volumen.py --base-datos ai_frecuencias_seg_rapido --plantilla <base de un año> \
      --ejecuciones 365 --recrear
  python scripts/medir_segmentos.py --base-datos ai_frecuencias_seg_rapido --puerto 8310
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "scripts"))
sys.path.insert(0, str(RAIZ))
from cola_servidor import datos_de_la_base, motor, preparar_base, url_local  # noqa: E402

ZONA = ZoneInfo("America/Bogota")
IMAGEN_K6 = "grafana/k6:1.4.2"
PASOS = ("refresco", "en_frio", "segmentos", "consultas", "ingesta")
RUTA_REFRESCO = "/api/v1/segmentos/estadisticas/refrescar"
TABLAS_VOLUMEN = ("execution_log", "prediction", "recommendation", "alert", "alert_history", "segmento_estadistica_dia",
                  "segmento_estadistica")
_LINEAS: list[str] = []


def log(*partes) -> None:
    linea = " ".join(str(p) for p in partes)
    _LINEAS.append(linea)
    print(linea, flush=True)


def url_lector() -> str:
    from replica_comun import url_rol

    url = url_rol("lector_ia")
    if not url:
        raise SystemExit("Falta LECTOR_IA_PASSWORD (la réplica se lee con el usuario de solo lectura)")
    return url.replace("postgresql://", "postgresql+psycopg://", 1)


# ---------------------------------------------------------------- la API propia
class ApiPropia:
    """uvicorn de este checkout en 127.0.0.1:<puerto>, en modo integrado (réplica con lector_ia)."""

    def __init__(self, puerto: int, url_propia: str, clave: str, carpeta: Path):
        self.puerto, self.url_propia, self.clave = puerto, url_propia, clave
        self.log_path = carpeta / f"api_{puerto}.log"
        self.proc: subprocess.Popen | None = None

    def entorno(self) -> dict[str, str]:
        hash_clave = hashlib.sha256(self.clave.encode()).hexdigest()
        return os.environ | datos_de_la_base(self.url_propia) | {
            "DATABASE_URL": self.url_propia, "FUENTE": "postgres", "FUENTE_DATABASE_URL": url_lector(),
            "CATALOGOS_FUENTE": "replica", "AUTH_HABILITADA": "true",
            "API_KEYS": json.dumps({hash_clave: {"usuario": "k6_segmentos", "rol": "analista"}}),
            "API_KEY_OPERADOR": "", "API_KEY_ANALISTA": "", "API_KEY_ADMIN": "", "TRABAJADORES": "1",
            "REANUDAR_EJECUCIONES": "true", "PLANIFICADOR_HABILITADO": "false", "ENTORNO": "pruebas",
            "LOG_NIVEL": "WARNING", "TRABAJADOR_ID": f"medicion-segmentos-{self.puerto}", "PYTHONIOENCODING": "utf-8"}

    def arrancar(self) -> float:
        salida = open(self.log_path, "a", encoding="utf-8")  # noqa: SIM115 - vive mientras viva el proceso
        t0 = time.perf_counter()
        self.proc = subprocess.Popen(  # noqa: S603 - comando fijo con el intérprete actual
            [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(self.puerto),
             "--log-level", "warning"], cwd=RAIZ, env=self.entorno(), stdout=salida, stderr=subprocess.STDOUT)
        fin = time.time() + 120
        while time.time() < fin:
            if self.proc.poll() is not None:
                raise RuntimeError(f"La API terminó al arrancar (ver {self.log_path})")
            if self._sana():
                return time.perf_counter() - t0
            time.sleep(0.3)
        raise TimeoutError("La API propia no respondió /health")

    def _sana(self) -> bool:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{self.puerto}/health", timeout=3) as r:  # nosec B310  # URL fija a 127.0.0.1  # noqa: S310
                return r.status == 200
        except (urllib.error.URLError, OSError):
            return False

    def parar(self) -> None:
        if self.proc is not None and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=30)
        self.proc = None

    def pedir(self, metodo: str, ruta: str, cuerpo: dict | None = None) -> dict:
        datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
        req = urllib.request.Request(f"http://127.0.0.1:{self.puerto}{ruta}", data=datos, method=metodo,  # noqa: S310
                                     headers={"X-API-Key": self.clave, "Content-Type": "application/json",
                                              "X-Correlation-Id": "medir-segmentos"})
        with urllib.request.urlopen(req, timeout=60) as r:  # nosec B310  # URL fija a 127.0.0.1  # noqa: S310
            return json.loads(r.read().decode())


# ---------------------------------------------------------------- k6 en Docker
def correr_k6(api: ApiPropia, script: str, nombre: str, salida: Path, **entorno: str) -> tuple[int, str, dict]:
    """(código de salida, texto de k6, resumen exportado). La clave llega a k6 solo por el entorno del proceso."""
    variables = [x for k, v in entorno.items() for x in ("-e", f"{k}={v}")]
    cmd = ["docker", "run", "--rm", "-e", f"BASE=http://host.docker.internal:{api.puerto}", "-e", "SOBUSA_API_KEY",
           *variables, "-v", f"{RAIZ / 'k6'}:/scripts:ro", "-v", f"{salida}:/salida", IMAGEN_K6, "run",
           "--summary-export", f"/salida/{nombre}.json", f"/scripts/{script}"]
    r = subprocess.run(cmd, env=os.environ | {"SOBUSA_API_KEY": api.clave}, capture_output=True, text=True,  # noqa: S603
                       encoding="utf-8", errors="replace", timeout=1200)
    texto = r.stdout + r.stderr
    resumen_path = salida / f"{nombre}.json"
    resumen = json.loads(resumen_path.read_text(encoding="utf-8")) if resumen_path.exists() else {}
    return r.returncode, texto, resumen


def _p95(resumen: dict, metrica: str) -> float | None:
    valor = resumen.get("metrics", {}).get(metrica, {}).get("p(95)")
    return None if valor is None else round(float(valor), 1)


def _valor_del_umbral(datos: dict, umbral: str):
    """El valor que compara el umbral: p(95), count, rate o value según la expresión («p(95)<2000», «count>100»)."""
    for clave in ("p(95)", "count", "rate"):
        if umbral.startswith(clave) and clave in datos:
            return datos[clave]
    return datos.get("value", datos.get("rate"))


def _umbrales(resumen: dict) -> list[str]:
    """«métrica umbral: cumple/NO cumple» de cada umbral (en el resumen de k6, true = se cruzó el umbral)."""
    lineas = []
    for metrica, datos in sorted(resumen.get("metrics", {}).items()):
        for umbral, cruzado in (datos.get("thresholds") or {}).items():
            valor = _valor_del_umbral(datos, umbral)
            lineas.append(f"{metrica:<58} {umbral:<12} {'NO cumple' if cruzado else 'cumple':<10} "
                          f"(valor {round(float(valor), 2) if valor is not None else '-'})")
    return lineas


def _consola(texto: str) -> list[str]:
    """Mensajes console.log de k6 (msg="…")."""
    return [m.replace("\\t", "\t") for m in re.findall(r'msg="(.*?)" source=console', texto)]


# ---------------------------------------------------------------- pasos
def paso_refresco(api: ApiPropia, contexto: dict) -> None:
    t0 = time.perf_counter()
    en_cola = api.pedir("POST", RUTA_REFRESCO, {"modo": "completo"})
    detalle = _esperar(api, en_cola["execution_id"], 600)
    m = detalle.get("metricas") or {}
    contexto["refresco"] = {"execution_id": en_cola["execution_id"], "estado": detalle.get("estado"),
                            "segundos": round(time.perf_counter() - t0, 1), **{k: m.get(k) for k in (
                                "modo", "tramos", "fechas_releidas", "filas_leidas", "filas_dia", "filas",
                                "fecha_min", "fecha_max", "duracion_s")}}
    log(f"1) Refresco completo de la agregación (trabajo de la cola {en_cola['execution_id']}): "
        f"{detalle.get('estado')} en {contexto['refresco']['segundos']} s; {m.get('tramos')} tramos de hasta 31 días "
        f"leídos de la réplica con lector_ia ({m.get('filas_leidas')} filas del grano diario), "
        f"{m.get('filas')} filas en el grano de la respuesta, período {m.get('fecha_min')} a {m.get('fecha_max')}")


def _esperar(api: ApiPropia, execution_id: str, limite_s: float) -> dict:
    fin, detalle = time.time() + limite_s, {}
    while time.time() < fin:
        detalle = api.pedir("GET", f"/api/v1/frequency/executions/{execution_id}")
        if detalle.get("estado") in ("ok", "error"):
            return detalle
        time.sleep(1)
    return detalle


def paso_en_frio(api: ApiPropia, contexto: dict, salida: Path) -> None:
    api.parar()
    arranque = api.arrancar()
    codigo, texto, resumen = correr_k6(api, "en_frio.js", "k6_segmentos_en_frio", salida)
    filas: dict[str, dict] = {}
    for linea in _consola(texto):
        partes = linea.split("\t")
        if len(partes) == 4 and partes[0] in ("frio", "caliente"):
            filas.setdefault(partes[1], {})[partes[0]] = (partes[2], float(partes[3].split()[0]))
    contexto["en_frio"] = {"codigo_k6": codigo, "arranque_s": round(arranque, 1), "rutas": filas,
                           "p95_frio": _p95(resumen, "http_req_duration{pasada:frio,clase:consulta}"),
                           "p95_caliente": _p95(resumen, "http_req_duration{pasada:caliente,clase:consulta}")}
    log(f"\n2) Peticiones EN FRÍO (k6/en_frio.js): API recién arrancada ({arranque:.1f} s hasta /health), primera "
        "petición a cada ruta sin calentamiento («frío») y segunda pasada inmediata («caliente»); 1 usuario, en serie")
    log(f"   {'ruta':<32} {'estado':>6} {'frío ms':>9} {'caliente ms':>12}  p95 < 2 s")
    for nombre, pasadas in filas.items():
        estado, frio = pasadas.get("frio", ("-", float("nan")))
        _, caliente = pasadas.get("caliente", ("-", float("nan")))
        veredicto = "descarga, fuera de RNF-002" if nombre.endswith("_export") else (
            "cumple" if max(frio, caliente) < 2000 else "NO cumple")
        log(f"   {nombre:<32} {estado:>6} {frio:9.1f} {caliente:12.1f}  {veredicto}")
    log(f"   p95 de las consultas paginadas: en frío {contexto['en_frio']['p95_frio']} ms, en caliente "
        f"{contexto['en_frio']['p95_caliente']} ms (código de salida de k6: {codigo}; 0 = los umbrales cumplen)")


def paso_segmentos(api: ApiPropia, contexto: dict, salida: Path) -> None:
    codigo, texto, resumen = correr_k6(api, "segmentos.js", "k6_segmentos_carga", salida)
    contexto["segmentos"] = {"codigo_k6": codigo, "consola": _consola(texto),
                             "p95": {m: _p95(resumen, m) for m in resumen.get("metrics", {})
                                     if m.startswith("http_req_duration{")}}
    log("\n3) Carga sobre la capa de segmentos MIENTRAS corre un refresco completo (k6/segmentos.js): rampa "
        "0 -> 25 -> 50 usuarios en 60 s, consultas al azar con desplazamiento dentro del total de cada una")
    for linea in contexto["segmentos"]["consola"] + _umbrales(resumen):
        log(f"   {linea.strip()}")
    log(f"   (código de salida de k6: {codigo}; 0 = todos los umbrales cumplen)")


def paso_consultas(api: ApiPropia, contexto: dict, salida: Path) -> None:
    codigo, texto, resumen = correr_k6(api, "consultas.js", "k6_segmentos_consultas", salida,
                                       MIN_PREDICCIONES="3300", MIN_ALERTAS="8000")
    contexto["consultas"] = {"codigo_k6": codigo, "p95": _p95(resumen, "http_req_duration")}
    log("\n4) Consultas paginadas con el volumen acordado (k6/consultas.js, mínimos 3.300 predicciones y 8.000 "
        "alertas): rampa 0 -> 25 -> 50 usuarios en 60 s")
    for linea in _umbrales(resumen):
        log(f"   {linea.strip()}")
    log(f"   (código de salida de k6: {codigo})")


def paso_ingesta(api: ApiPropia, contexto: dict, salida: Path) -> None:
    codigo, texto, resumen = correr_k6(api, "consultas_durante_ingesta.js", "k6_segmentos_ingesta", salida,
                                       HASTA="2027-01-01", INCLUIR_SEGMENTOS="1", DURACION_S="240",
                                       LIMITE_INGESTA_S="230")
    contexto["ingesta"] = {"codigo_k6": codigo, "consola": _consola(texto),
                           "p95_durante": _p95(resumen, "http_req_duration{fase:durante_ingesta}")}
    log("\n5) Consultas DURANTE una ingesta incremental en modo integrado (k6/consultas_durante_ingesta.js, "
        "INCLUIR_SEGMENTOS=1, 240 s): POST /api/v1/frequency/executions lee lo nuevo de la réplica "
        "(demanda_segmentos con lector_ia) sobre la base con el volumen de un año, mientras 30 usuarios consultan")
    for linea in contexto["ingesta"]["consola"] + _umbrales(resumen):
        log(f"   {linea.strip()}")
    log(f"   (código de salida de k6: {codigo})")


def volumen(url_propia: str) -> dict[str, int]:
    from sqlalchemy import text

    m = motor(url_propia)
    with m.connect() as c:
        filas = {t: int(c.execute(text(f"SELECT count(*) FROM ai_frecuencias.{t}")).scalar())  # noqa: S608  # nosec B608  # nombres fijos de TABLAS_VOLUMEN
                 for t in TABLAS_VOLUMEN}
    m.dispose()
    return filas


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--base-datos", default="ai_frecuencias_seg_rapido")
    p.add_argument("--puerto", type=int, default=8310)
    p.add_argument("--salida", type=Path, default=RAIZ / "docs" / "evidencias" / "pruebas")
    p.add_argument("--pasos", nargs="+", choices=PASOS, default=list(PASOS))
    a = p.parse_args()
    if a.base_datos in ("ai_frecuencias", "postgres"):
        raise SystemExit("Use una base local propia para medir (nunca la principal)")
    url_propia = url_local(a.base_datos)
    preparar_base(url_propia)
    # ruta absoluta: «docker run -v <salida>:/salida» toma una ruta relativa como nombre de volumen y k6 ni arranca
    # (código 125, sin resumen)
    a.salida = a.salida.resolve()
    a.salida.mkdir(parents=True, exist_ok=True)
    contexto: dict = {"fecha": datetime.now(ZONA).isoformat(timespec="seconds"), "base": a.base_datos,
                      "volumen_antes": volumen(url_propia), "pasos": a.pasos}
    log(f"Capa de segmentos y carga con el volumen acordado · {contexto['fecha']} (portátil Windows 11, Docker "
        f"Desktop, k6 {IMAGEN_K6}); API propia de este checkout en 127.0.0.1:{a.puerto}, modo integrado (réplica "
        "5434 con lector_ia), base propia en 5433, autenticación encendida con una clave analista nueva")
    log(f"   volumen de la base al empezar: {json.dumps(contexto['volumen_antes'])}")
    api = ApiPropia(a.puerto, url_propia, secrets.token_urlsafe(32), Path(tempfile.mkdtemp(prefix="medir_seg_")))
    try:
        api.arrancar()
        for paso in a.pasos:
            _correr_paso(paso, api, contexto, a.salida)
    finally:
        api.parar()
    contexto["volumen_despues"] = volumen(url_propia)
    log(f"\n   volumen de la base al terminar: {json.dumps(contexto['volumen_despues'])}")
    (a.salida / "k6_segmentos.txt").write_text("\n".join(_LINEAS) + "\n", encoding="utf-8")
    (a.salida / "k6_segmentos_resumen.json").write_text(json.dumps(contexto, ensure_ascii=False, indent=1,
                                                                   default=str), encoding="utf-8")
    return 0


def _correr_paso(paso: str, api: ApiPropia, contexto: dict, salida: Path) -> None:
    if paso == "refresco":
        paso_refresco(api, contexto)
    elif paso == "en_frio":
        paso_en_frio(api, contexto, salida)
    elif paso == "segmentos":
        paso_segmentos(api, contexto, salida)
    elif paso == "consultas":
        paso_consultas(api, contexto, salida)
    else:
        paso_ingesta(api, contexto, salida)


if __name__ == "__main__":
    raise SystemExit(main())
