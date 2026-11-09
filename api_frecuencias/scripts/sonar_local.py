"""Análisis real con SonarQube en Docker (spec v1.5: §7.1, RNF-007, RNF-013, §14.2 y el «reporte de SonarQube» de E03).

Uso (desde EntregaFinal/api_frecuencias, con el venv de la API):
    python scripts/sonar_local.py --archivo-clave <fuera del repositorio>/sonar_admin.txt
    python scripts/sonar_local.py --sin-pruebas      # reutiliza la última cobertura (más rápido)
    python scripts/sonar_local.py --solo-exportar    # vuelve a leer la puerta y las medidas y rehace la evidencia
    python scripts/sonar_local.py --detener          # además apaga el contenedor al final (SonarQube usa unos 2,5 GB)

Qué hace, en orden:
 1. Arranca o reutiliza el contenedor «sobusa_sonar» (sonarqube:community) en 127.0.0.1:9000, solo si el puerto está
    libre o ya es suyo; nunca toca otros contenedores. Espera a que /api/system/status diga UP.
 2. En el primer arranque cambia la clave de fábrica de admin por una aleatoria que se guarda SOLO en --archivo-clave
    (o en la variable SONAR_CLAVE_ARCHIVO), que debe quedar fuera del repositorio. La clave nunca se imprime.
 3. Crea (o actualiza) el proyecto «sobusa-api-frecuencias», el perfil de calidad «Reto Sobusa v1.5» (hereda de
    «Sonar way» —en SonarQube 26 para Python, «Sonar way comprehensive»— y activa además todas las reglas de
    seguridad de Python) y la puerta de calidad «Reto Sobusa v1.5»
    sobre TODO el código: 0 vulnerabilidades, 0 bugs, 0 hallazgos bloqueantes o críticos, 100 % de security hotspots
    revisados, cobertura ≥ 85 % y duplicación ≤ 3 %.
 4. Corre pytest con cobertura de todo app/ (incluido motor_d5), ruff y bandit; los reportes de ruff y bandit quedan
    también como evidencia en docs/evidencias/calidad/.
 5. Crea un token de análisis del proyecto (solo en memoria), ejecuta sonar-scanner-cli en Docker sobre una copia del
    código y espera el resultado. El token se revoca al terminar.
 6. Aplica las decisiones revisadas a mano de scripts/sonar_decisiones.json: deuda de mantenibilidad aceptada y
    security hotspots seguros, cada una con su justificación (nunca se acepta un bug ni una vulnerabilidad).
 7. Exporta a docs/evidencias/sonarqube/: quality_gate.json, measures.json, issues.json, hotspots.json,
    perfil_calidad.json, resumen.md, scanner.log y tablero_sonarqube.png (Playwright con Edge).
Sale con 0 si la puerta queda en OK y con 1 si no.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import secrets
import shutil
import socket
import string
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

RAIZ = Path(__file__).resolve().parents[1]
EVIDENCIA = RAIZ / "docs" / "evidencias" / "sonarqube"
EVIDENCIA_CALIDAD = RAIZ / "docs" / "evidencias" / "calidad"
HOST = "http://127.0.0.1:9000"
PUERTO = 9000
CONTENEDOR = "sobusa_sonar"
IMAGEN_SERVIDOR = "sonarqube:community"
IMAGEN_SCANNER = "sonarsource/sonar-scanner-cli:latest"
PROYECTO = "sobusa-api-frecuencias"
NOMBRE_PROYECTO = "API de frecuencias · Data Challenge Sobusa 2026"
NOMBRE_PERFIL = "Reto Sobusa v1.5"
NOMBRE_PUERTA = "Reto Sobusa v1.5"
PADRES_PERFIL = ("Sonar way comprehensive", "Sonar way")
USUARIO_ADMIN = "admin"
CLAVE_FABRICA = "admin"  # noqa: S105 - clave pública de fábrica de SonarQube; este script la reemplaza al arrancar
TZ = ZoneInfo("America/Bogota")
PRUEBAS_POR_OMISION = ["tests/unit", "tests/integracion", "tests/replica", "tests/contrato", "tests/datos_ml"]

# Puerta de calidad «Reto Sobusa v1.5» (todo el código, no solo el nuevo): métrica, operador, umbral y lectura.
CONDICIONES = [
    ("vulnerabilities", "GT", "0", "Vulnerabilidades"),
    ("bugs", "GT", "0", "Bugs"),
    ("blocker_violations", "GT", "0", "Hallazgos bloqueantes"),
    ("critical_violations", "GT", "0", "Hallazgos críticos"),
    # software_quality_blocker_issues y software_quality_high_issues (modo MQR) son, para SonarQube, las mismas
    # métricas que blocker_violations y critical_violations: la puerta no admite las dos a la vez.
    ("security_hotspots_reviewed", "LT", "100", "Security hotspots revisados (%)"),
    ("coverage", "LT", "85", "Cobertura de pruebas (%)"),
    ("duplicated_lines_density", "GT", "3", "Líneas duplicadas (%)"),
]
METRICAS = ("ncloc,files,functions,classes,statements,complexity,cognitive_complexity,coverage,line_coverage,"
            "lines_to_cover,uncovered_lines,tests,test_failures,test_errors,skipped_tests,test_success_density,"
            "bugs,vulnerabilities,code_smells,security_hotspots,security_hotspots_reviewed,"
            "duplicated_lines_density,duplicated_lines,duplicated_blocks,sqale_index,sqale_debt_ratio,"
            "sqale_rating,reliability_rating,security_rating,security_review_rating,blocker_violations,"
            "critical_violations,major_violations,minor_violations,info_violations,violations,"
            "software_quality_blocker_issues,software_quality_high_issues,software_quality_medium_issues,"
            "software_quality_low_issues,software_quality_info_issues,software_quality_security_issues,"
            "software_quality_reliability_issues,software_quality_maintainability_issues,"
            "software_quality_security_rating,software_quality_reliability_rating,"
            "software_quality_maintainability_rating,accepted_issues,alert_status")

# Decisiones revisadas a mano (deuda de mantenibilidad aceptada y security hotspots seguros), cada una con su
# justificación: regla, archivo y un texto de la línea marcada. Nunca se acepta un bug ni una vulnerabilidad.
DECISIONES = RAIZ / "scripts" / "sonar_decisiones.json"
TIPOS_ACEPTABLES = {"CODE_SMELL"}


def _escribir(texto: str) -> None:
    print(texto, flush=True)


def _enmascarar(texto: str) -> str:
    """Oculta cualquier clave dentro de una URL (usuario:clave@host) antes de guardar un registro como evidencia."""
    return re.sub(r"(\w[\w+.-]*://[^:/@\s]+:)[^@\s]+@", r"\g<1>***@", texto)


# ------------------------------------------------------------------------------------------------ cliente Web API
class Sonar:
    """Cliente mínimo de la Web API (autenticación básica con admin; la clave solo vive en memoria)."""

    def __init__(self, clave: str | None = None) -> None:
        self.clave = clave

    def _pedir(self, metodo: str, ruta: str, datos: dict | None = None, clave: str | None = None) -> tuple[int, str]:
        clave = clave if clave is not None else self.clave
        cuerpo = None
        url = HOST + ruta
        if metodo == "POST":
            cuerpo = urllib.parse.urlencode(datos or {}).encode()
        elif datos:
            url += "?" + urllib.parse.urlencode(datos)
        req = urllib.request.Request(url, data=cuerpo, method=metodo)  # noqa: S310 - siempre http://127.0.0.1:9000
        if clave is not None:
            par = base64.b64encode(f"{USUARIO_ADMIN}:{clave}".encode()).decode()
            req.add_header("Authorization", "Basic " + par)
        try:
            # B310 no aplica: la URL es siempre HOST (http://127.0.0.1:9000) más una ruta fija de la Web API
            with urllib.request.urlopen(req, timeout=60) as r:  # nosec B310  # noqa: S310
                return r.status, r.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", "replace")

    def get(self, ruta: str, **params) -> dict:
        codigo, txt = self._pedir("GET", ruta, params)
        if codigo != 200:
            raise RuntimeError(f"GET {ruta} respondió {codigo}: {txt[:300]}")
        return json.loads(txt)

    def post(self, ruta: str, **datos) -> tuple[int, str]:
        return self._pedir("POST", ruta, datos)

    def get_paginado(self, ruta: str, clave_lista: str, **params) -> tuple[list[dict], dict]:
        elementos: list[dict] = []
        pagina = 1
        while True:
            datos = self.get(ruta, p=pagina, ps=500, **params)
            elementos += datos.get(clave_lista, [])
            total = datos.get("paging", {}).get("total", datos.get("total", 0))
            if len(elementos) >= total or not datos.get(clave_lista):
                return elementos, datos
            pagina += 1


# ------------------------------------------------------------------------------------------------ contenedor
def _docker(*args: str, capturar: bool = True, entorno: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", *args], capture_output=capturar, text=True, encoding="utf-8",  # noqa: S603,S607
                          errors="replace", env=entorno, check=False)


def _puerto_ocupado(puerto: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        return s.connect_ex(("127.0.0.1", puerto)) == 0


def asegurar_contenedor() -> None:
    estado = _docker("inspect", "-f", "{{.State.Running}}", CONTENEDOR)
    if estado.returncode == 0 and estado.stdout.strip() == "true":
        _escribir(f"SonarQube: reutilizo el contenedor {CONTENEDOR}, que ya está corriendo.")
        return
    if _puerto_ocupado(PUERTO):
        raise SystemExit(f"El puerto {PUERTO} está ocupado por otro proceso y {CONTENEDOR} no está corriendo: "
                         "libérelo (este script no toca otros contenedores).")
    if estado.returncode == 0:
        _escribir(f"SonarQube: arranco el contenedor existente {CONTENEDOR}.")
        r = _docker("start", CONTENEDOR)
    else:
        _escribir(f"SonarQube: creo el contenedor {CONTENEDOR} ({IMAGEN_SERVIDOR}) en 127.0.0.1:{PUERTO}.")
        r = _docker("run", "-d", "--name", CONTENEDOR, "-p", f"127.0.0.1:{PUERTO}:9000",
                    "-e", "SONAR_ES_BOOTSTRAP_CHECKS_DISABLE=true",
                    "-v", "sobusa_sonar_data:/opt/sonarqube/data", "-v", "sobusa_sonar_ext:/opt/sonarqube/extensions",
                    "-v", "sobusa_sonar_logs:/opt/sonarqube/logs", "--label", f"proyecto={PROYECTO}", IMAGEN_SERVIDOR)
    if r.returncode != 0:
        raise SystemExit(f"No se pudo arrancar {CONTENEDOR}: {r.stderr.strip()[:300]}")


def esperar_up(limite_s: float = 300) -> str:
    inicio = time.monotonic()
    sonar = Sonar()
    while time.monotonic() - inicio < limite_s:
        try:
            codigo, txt = sonar._pedir("GET", "/api/system/status")
            if codigo == 200 and json.loads(txt).get("status") == "UP":
                version = json.loads(txt).get("version", "?")
                _escribir(f"SonarQube {version} en estado UP ({time.monotonic() - inicio:.0f} s).")
                return version
        except (urllib.error.URLError, ConnectionError, TimeoutError, json.JSONDecodeError):
            pass
        time.sleep(3)
    raise SystemExit(f"SonarQube no llegó a UP en {limite_s:.0f} s (vea: docker logs {CONTENEDOR}).")


# ------------------------------------------------------------------------------------------------ clave y token
def _clave_aleatoria() -> str:
    alfabeto = string.ascii_letters + string.digits
    cuerpo = "".join(secrets.choice(alfabeto) for _ in range(24))
    return f"Sq{cuerpo}#{secrets.randbelow(10)}a"


def _clave_valida(clave: str) -> bool:
    codigo, txt = Sonar(clave)._pedir("GET", "/api/authentication/validate")
    return codigo == 200 and json.loads(txt).get("valid") is True


def asegurar_clave(archivo: Path) -> str:
    archivo = archivo.resolve()
    if archivo.is_relative_to(RAIZ.parent.parent) or archivo.is_relative_to(RAIZ):
        raise SystemExit("El archivo de la clave de admin debe quedar FUERA del repositorio.")
    if archivo.exists():
        clave = archivo.read_text(encoding="utf-8").strip()
        if _clave_valida(clave):
            _escribir("SonarQube: la clave de admin del archivo indicado es válida (no se imprime).")
            return clave
        raise SystemExit("La clave del archivo indicado no es válida para admin en este servidor.")
    if not _clave_valida(CLAVE_FABRICA):
        raise SystemExit("admin ya no usa la clave de fábrica y el archivo indicado no existe: pase el --archivo-clave "
                         "que se usó en el primer arranque (o la variable SONAR_CLAVE_ARCHIVO).")
    clave = _clave_aleatoria()
    codigo, txt = Sonar(CLAVE_FABRICA).post("/api/users/change_password", login=USUARIO_ADMIN,
                                            previousPassword=CLAVE_FABRICA, password=clave)
    if codigo != 204:
        raise SystemExit(f"No se pudo cambiar la clave de admin ({codigo}): {txt[:200]}")
    archivo.parent.mkdir(parents=True, exist_ok=True)
    archivo.write_text(clave, encoding="utf-8")
    _escribir("SonarQube: primer arranque, la clave de fábrica de admin se cambió por una aleatoria "
              "(guardada solo en el archivo indicado, fuera del repositorio).")
    return clave


def crear_token(sonar: Sonar) -> tuple[str, str]:
    nombre = f"analisis-{datetime.now(TZ):%Y%m%d-%H%M%S}"
    codigo, txt = sonar.post("/api/user_tokens/generate", name=nombre, type="PROJECT_ANALYSIS_TOKEN",
                             projectKey=PROYECTO)
    if codigo != 200:
        raise SystemExit(f"No se pudo crear el token de análisis ({codigo}): {txt[:200]}")
    return nombre, json.loads(txt)["token"]


def revocar_token(sonar: Sonar, nombre: str) -> None:
    codigo, _ = sonar.post("/api/user_tokens/revoke", name=nombre)
    _escribir(f"Token de análisis «{nombre}» revocado ({codigo}).")


# ------------------------------------------------------------------------------------------------ configuración
def asegurar_proyecto(sonar: Sonar) -> None:
    if sonar.get("/api/projects/search", projects=PROYECTO).get("components"):
        return
    codigo, txt = sonar.post("/api/projects/create", project=PROYECTO, name=NOMBRE_PROYECTO, visibility="private")
    if codigo != 200:
        raise SystemExit(f"No se pudo crear el proyecto ({codigo}): {txt[:200]}")
    _escribir(f"Proyecto {PROYECTO} creado (privado).")


def asegurar_perfil(sonar: Sonar) -> dict:
    perfiles = sonar.get("/api/qualityprofiles/search", language="py")["profiles"]
    nombres = {p["name"] for p in perfiles if p.get("isBuiltIn")}
    # «Sonar way» para Python se llama «Sonar way comprehensive» desde SonarQube 2025.x (el integrado más completo)
    padre = next((n for n in PADRES_PERFIL if n in nombres), None)
    if padre is None:
        raise SystemExit(f"No hay un perfil integrado de la familia «Sonar way» para Python: {sorted(nombres)}")
    perfil = next((p for p in perfiles if p["name"] == NOMBRE_PERFIL), None)
    if perfil is None:
        codigo, txt = sonar.post("/api/qualityprofiles/create", language="py", name=NOMBRE_PERFIL)
        if codigo != 200:
            raise SystemExit(f"No se pudo crear el perfil ({codigo}): {txt[:200]}")
        perfil = json.loads(txt)["profile"]
    sonar.post("/api/qualityprofiles/change_parent", language="py", qualityProfile=NOMBRE_PERFIL,
               parentQualityProfile=padre)
    # Además del perfil padre: todas las reglas de seguridad de Python (vulnerabilidades y security hotspots).
    codigo, txt = sonar.post("/api/qualityprofiles/activate_rules", targetKey=perfil["key"], languages="py",
                             repositories="python", types="VULNERABILITY,SECURITY_HOTSPOT", qprofile=perfil["key"],
                             activation="false")
    if codigo != 200:
        raise SystemExit(f"No se pudieron activar las reglas de seguridad ({codigo}): {txt[:200]}")
    activadas = json.loads(txt)
    sonar.post("/api/qualityprofiles/add_project", language="py", qualityProfile=NOMBRE_PERFIL, project=PROYECTO)
    perfil = next(p for p in sonar.get("/api/qualityprofiles/search", language="py")["profiles"]
                  if p["name"] == NOMBRE_PERFIL)
    seguridad = sonar.get("/api/rules/search", languages="py", repositories="python",
                          types="VULNERABILITY,SECURITY_HOTSPOT", qprofile=perfil["key"], activation="true", ps=1)
    # Reglas de seguridad que el perfil agrega sobre su padre (lo que distingue al perfil del reto)
    base = next(p for p in sonar.get("/api/qualityprofiles/search", language="py")["profiles"]
                if p["name"] == padre)
    reglas_perfil, _ = sonar.get_paginado("/api/rules/search", "rules", languages="py", repositories="python",
                                          types="VULNERABILITY,SECURITY_HOTSPOT", qprofile=perfil["key"],
                                          activation="true")
    reglas_base, _ = sonar.get_paginado("/api/rules/search", "rules", languages="py", repositories="python",
                                        types="VULNERABILITY,SECURITY_HOTSPOT", qprofile=base["key"],
                                        activation="true")
    en_base = {r["key"] for r in reglas_base}
    agregadas = [{"regla": r["key"], "nombre": r.get("name"), "tipo": r.get("type")}
                 for r in reglas_perfil if r["key"] not in en_base]
    _escribir(f"Perfil «{NOMBRE_PERFIL}»: {perfil.get('activeRuleCount')} reglas activas "
              f"({seguridad.get('total')} de seguridad, {len(agregadas)} agregadas sobre «{padre}»).")
    return {"perfil": perfil, "reglas_seguridad_activas": seguridad.get("total"),
            "perfil_padre": padre, "reglas_seguridad_padre": len(en_base), "reglas_seguridad_agregadas": agregadas,
            "activadas_en_esta_corrida": activadas}


def asegurar_puerta(sonar: Sonar) -> list[tuple[str, str, str, str]]:
    disponibles = {m["key"] for m in sonar.get_paginado("/api/metrics/search", "metrics")[0]}
    condiciones = [c for c in CONDICIONES if c[0] in disponibles]
    for metrica, *_ in CONDICIONES:
        if metrica not in disponibles:
            _escribir(f"  aviso: la métrica {metrica} no existe en esta versión; se omite de la puerta.")
    codigo, txt = sonar._pedir("GET", "/api/qualitygates/show", {"name": NOMBRE_PUERTA})
    if codigo == 404 or codigo == 400:
        codigo, txt = sonar.post("/api/qualitygates/create", name=NOMBRE_PUERTA)
        if codigo != 200:
            raise SystemExit(f"No se pudo crear la puerta ({codigo}): {txt[:200]}")
        actuales = []
    else:
        actuales = json.loads(txt).get("conditions", [])
    por_metrica = {c["metric"]: c for c in actuales}
    # SonarQube agrega solo, al crear una puerta, condiciones sobre el código nuevo (new_coverage, new_violations,
    # new_duplicated_lines_density). La puerta del reto es sobre TODO el código: quedan solo las de CONDICIONES.
    deseadas = {c[0] for c in condiciones}
    for metrica, c in list(por_metrica.items()):
        if metrica not in deseadas:
            sonar.post("/api/qualitygates/delete_condition", id=c["id"])
            del por_metrica[metrica]
            _escribir(f"  condición {metrica} retirada (no forma parte de la puerta del reto).")
    for metrica, op, umbral, _ in condiciones:
        actual = por_metrica.get(metrica)
        if actual is None:
            codigo, txt = sonar.post("/api/qualitygates/create_condition", gateName=NOMBRE_PUERTA, metric=metrica,
                                     op=op, error=umbral)
        elif actual.get("op") != op or str(actual.get("error")) != umbral:
            codigo, txt = sonar.post("/api/qualitygates/update_condition", id=actual["id"], metric=metrica, op=op,
                                     error=umbral)
        else:
            continue
        if codigo not in (200, 204):
            raise SystemExit(f"Condición {metrica} {op} {umbral} rechazada ({codigo}): {txt[:200]}")
    sonar.post("/api/qualitygates/select", gateName=NOMBRE_PUERTA, projectKey=PROYECTO)
    _escribir(f"Puerta «{NOMBRE_PUERTA}»: {len(condiciones)} condiciones sobre todo el código, asociada a {PROYECTO}.")
    return condiciones


# ------------------------------------------------------------------------------------------------ reportes
def _correr(cmd: list[str]) -> subprocess.CompletedProcess:
    """Herramienta del venv (ruff, bandit) sobre la raíz de la API; los argumentos son fijos de este script."""
    return subprocess.run(cmd, cwd=RAIZ, capture_output=True, text=True, encoding="utf-8",  # noqa: S603
                          errors="replace", check=False)


def _relativa(ruta: str) -> str:
    """Ruta de un reporte (absoluta de Windows o relativa con «\\») -> relativa POSIX a la raíz de la API."""
    p = ruta.replace("\\", "/")
    raiz = str(RAIZ).replace("\\", "/")
    if p.lower().startswith(raiz.lower() + "/"):
        p = p[len(raiz) + 1:]
    return p


def correr_pruebas(area: Path, pruebas: list[str], log: Path) -> dict:
    rc = area / "coveragerc"
    rc.write_text("[run]\nsource = app\nrelative_files = True\n\n[report]\nskip_empty = True\n", encoding="utf-8")
    copia = area / "datos"
    shutil.copytree(RAIZ / "datos", copia)  # las pruebas nunca escriben en datos/ del repositorio
    entorno = os.environ | {"DATA_DIR": str(copia), "MODELOS_DIR": str(copia / "modelos"),
                            "PYTHONIOENCODING": "utf-8"}
    entorno.setdefault("TEST_DATABASE_NAME", "ai_frecuencias_pruebas_sonar")
    entorno.setdefault("SCHEMATHESIS_EJEMPLOS", "3")
    cmd = [sys.executable, "-m", "pytest", *pruebas, f"--cov-config={rc}", "--cov=app",
           f"--cov-report=xml:{area / 'reportes' / 'coverage.xml'}", "--cov-report=term",
           f"--junitxml={area / 'reportes' / 'pytest.xml'}", "-q"]
    _escribir(f"pytest con cobertura de todo app/: {' '.join(pruebas)} (base {entorno['TEST_DATABASE_NAME']}) …")
    inicio = time.monotonic()
    with log.open("w", encoding="utf-8") as salida:
        r = subprocess.run(cmd, cwd=RAIZ, env=entorno, stdout=salida, stderr=subprocess.STDOUT,  # noqa: S603
                           check=False)
    junit = (area / "reportes" / "pytest.xml").read_text(encoding="utf-8")
    atributos = dict(re.findall(r'(\w+)="([^"]*)"', re.search(r"<testsuite [^>]*>", junit).group(0)))
    resultado = {"codigo_salida": r.returncode, "duracion_s": round(time.monotonic() - inicio, 1),
                 **{k: int(atributos.get(k, 0)) for k in ("tests", "failures", "errors", "skipped")}}
    _escribir(f"pytest: {resultado}")
    return resultado


def correr_lint(area: Path) -> dict:
    """ruff (todo el repositorio de la API) y bandit (app/ y scripts/): evidencia en docs/evidencias/calidad/."""
    EVIDENCIA_CALIDAD.mkdir(parents=True, exist_ok=True)
    py = sys.executable
    sello = f"{datetime.now(TZ):%Y-%m-%d %H:%M %z}"
    ruff_json = _correr([py, "-m", "ruff", "check", ".", "--output-format", "json"])
    hallazgos_ruff = json.loads(ruff_json.stdout or "[]")
    for h in hallazgos_ruff:
        h["filename"] = _relativa(h["filename"])
    ruff_txt = _correr([py, "-m", "ruff", "check", ".", "--output-format", "concise"])
    version_ruff = _correr([py, "-m", "ruff", "--version"]).stdout.strip()
    texto_ruff = (f"{version_ruff} · ruff check . (todo el repositorio de la API; reglas E, F, W, I, B, UP, S de "
                  f"pyproject.toml) · {sello}\n{ruff_txt.stdout.strip()}\ncódigo de salida: {ruff_txt.returncode}\n")
    (EVIDENCIA_CALIDAD / "ruff.json").write_text(json.dumps(hallazgos_ruff, ensure_ascii=False, indent=1) + "\n",
                                                 encoding="utf-8")
    (EVIDENCIA_CALIDAD / "ruff.txt").write_text(texto_ruff, encoding="utf-8")
    resultados = {"ruff": {"hallazgos": len(hallazgos_ruff), "codigo_salida": ruff_txt.returncode}}
    textos_bandit = []
    jsons_bandit = {}
    for alcance, extra in (("app", []), ("scripts", ["-ll"])):
        b = _correr([py, "-m", "bandit", "-c", "pyproject.toml", "-r", alcance, *extra, "-f", "json", "-q"])
        datos = json.loads(b.stdout or "{}")
        for h in datos.get("results", []):
            h["filename"] = _relativa(h["filename"])
        datos["metrics"] = {_relativa(k): v for k, v in datos.get("metrics", {}).items()}
        jsons_bandit[alcance] = datos
        t = _correr([py, "-m", "bandit", "-c", "pyproject.toml", "-r", alcance, *extra, "-f", "txt", "-q"])
        textos_bandit.append(f"== bandit -r {alcance} {' '.join(extra) or '(todas las severidades)'} · {sello}\n"
                             f"{t.stdout.strip()}\ncódigo de salida: {t.returncode}\n")
        resultados[f"bandit_{alcance}"] = {"hallazgos": len(datos.get("results", [])), "codigo_salida": b.returncode}
    version_bandit = _correr([py, "-m", "bandit", "--version"]).stdout.splitlines()[0].replace("__main__.py", "bandit")
    (EVIDENCIA_CALIDAD / "bandit.txt").write_text(f"{version_bandit}\n\n" + "\n".join(textos_bandit), encoding="utf-8")
    # bandit.json (formato nativo de bandit, el que importa SonarQube) es el de app/; el de scripts/ va aparte.
    for nombre, alcance in (("bandit.json", "app"), ("bandit_scripts.json", "scripts")):
        (EVIDENCIA_CALIDAD / nombre).write_text(json.dumps(jsons_bandit[alcance], ensure_ascii=False, indent=1) + "\n",
                                                encoding="utf-8")
    # Los reportes de la raíz de docs/evidencias/ (los que leía sonar-project.properties) quedan iguales a los nuevos.
    for nombre in ("ruff.txt", "bandit.txt", "ruff.json", "bandit.json"):
        shutil.copyfile(EVIDENCIA_CALIDAD / nombre, RAIZ / "docs" / "evidencias" / nombre)
    # Para SonarQube: solo lo que está dentro de sonar.sources (app/).
    reportes = area / "reportes"
    (reportes / "ruff.json").write_text(json.dumps([h for h in hallazgos_ruff if h["filename"].startswith("app/")]),
                                        encoding="utf-8")
    (reportes / "bandit.json").write_text(json.dumps(jsons_bandit["app"]), encoding="utf-8")
    _escribir(f"ruff y bandit: {resultados}")
    return resultados


def preparar_area(area: Path, cobertura_previa: Path | None) -> None:
    """Copia el código que se analiza (app/, tests/ y sonar-project.properties) al área temporal del scanner."""
    ignorar = shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache")
    destino = area / "src"
    shutil.copytree(RAIZ / "app", destino / "app", ignore=ignorar)
    shutil.copytree(RAIZ / "tests", destino / "tests", ignore=ignorar)
    shutil.copyfile(RAIZ / "sonar-project.properties", destino / "sonar-project.properties")
    (destino / "reportes").mkdir()
    for nombre in ("coverage.xml", "pytest.xml", "ruff.json", "bandit.json"):
        origen = area / "reportes" / nombre
        if not origen.exists() and nombre in ("coverage.xml", "pytest.xml") and cobertura_previa:
            origen = cobertura_previa / nombre
        if not origen.exists():
            continue
        texto = origen.read_text(encoding="utf-8")
        if nombre == "coverage.xml":  # <source> absoluto de Windows o relativo -> /usr/src/app
            texto = re.sub(r"<source>[^<]*</source>", "<source>/usr/src/app</source>", texto)
        (destino / "reportes" / nombre).write_text(texto, encoding="utf-8")


def correr_scanner(area: Path, token: str, log: Path) -> int:
    nombre = f"sobusa_sonar_scanner_{secrets.token_hex(4)}"
    argumentos = ["-Dsonar.working.directory=/tmp/sw", "-Dsonar.scm.disabled=true",
                  "-Dsonar.python.coverage.reportPaths=reportes/coverage.xml",
                  "-Dsonar.python.xunit.reportPath=reportes/pytest.xml",
                  "-Dsonar.python.ruff.reportPaths=reportes/ruff.json",
                  "-Dsonar.python.bandit.reportPaths=reportes/bandit.json",
                  "-Dsonar.qualitygate.wait=true", "-Dsonar.qualitygate.timeout=900"]
    entorno = os.environ | {"SONAR_TOKEN": token}
    r = _docker("create", "--name", nombre, "--network", f"container:{CONTENEDOR}",
                "-e", "SONAR_HOST_URL=http://localhost:9000", "-e", "SONAR_TOKEN",
                "-v", "sobusa_sonar_scanner_cache:/opt/sonar-scanner/.sonar/cache", IMAGEN_SCANNER, *argumentos,
                entorno=entorno)
    if r.returncode != 0:
        raise SystemExit(f"No se pudo crear el contenedor del scanner: {r.stderr.strip()[:300]}")
    try:
        cp = _docker("cp", f"{area / 'src'}{os.sep}.", f"{nombre}:/usr/src")
        if cp.returncode != 0:
            raise SystemExit(f"docker cp falló: {cp.stderr.strip()[:300]}")
        _escribir("sonar-scanner-cli en Docker (copia del código, sin volúmenes de Windows) …")
        inicio = time.monotonic()
        corrida = _docker("start", "-a", nombre, entorno=entorno)
        texto = (corrida.stdout or "") + (corrida.stderr or "")
        texto = _enmascarar(texto.replace(token, "***"))
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(texto, encoding="utf-8")
        _escribir(f"scanner terminó con código {_docker('inspect', '-f', '{{.State.ExitCode}}', nombre).stdout.strip()}"
                  f" en {time.monotonic() - inicio:.0f} s.")
        return int(_docker("inspect", "-f", "{{.State.ExitCode}}", nombre).stdout.strip() or 1)
    finally:
        _docker("rm", "-f", nombre)


def esperar_tarea(sonar: Sonar, limite_s: float = 900) -> dict:
    inicio = time.monotonic()
    while time.monotonic() - inicio < limite_s:
        actividad = sonar.get("/api/ce/component", component=PROYECTO)
        if not actividad.get("queue") and actividad.get("current"):
            return actividad["current"]
        time.sleep(3)
    raise SystemExit("La tarea de análisis no terminó a tiempo.")


# ------------------------------------------------------------------------------------------------ decisiones
class _Fuentes:
    """Líneas del código TAL COMO SE ANALIZÓ (api/sources/raw), para que las decisiones casen con lo que vio Sonar."""

    def __init__(self, sonar: Sonar) -> None:
        self.sonar = sonar
        self._cache: dict[str, list[str]] = {}

    def linea(self, componente: str, numero: int | None) -> str:
        if not numero:
            return ""
        if componente not in self._cache:
            codigo, txt = self.sonar._pedir("GET", "/api/sources/raw", {"key": componente})
            self._cache[componente] = txt.splitlines() if codigo == 200 else []
        lineas = self._cache[componente]
        return lineas[numero - 1] if numero <= len(lineas) else ""


def _decision(decisiones: list[dict], regla: str, archivo: str, linea: str) -> dict | None:
    return next((d for d in decisiones if d["regla"] == regla and d["archivo"] == archivo and d["contiene"] in linea),
                None)


def aplicar_decisiones(sonar: Sonar) -> dict:
    datos = json.loads(DECISIONES.read_text(encoding="utf-8"))
    fuentes = _Fuentes(sonar)
    aceptadas, seguros = [], []
    abiertos, _ = sonar.get_paginado("/api/issues/search", "issues", componentKeys=PROYECTO, resolved="false")
    for i in abiertos:
        if i.get("type") not in TIPOS_ACEPTABLES:
            continue
        archivo = i["component"].split(":", 1)[-1]
        d = _decision(datos.get("deuda_aceptada", []), i["rule"], archivo, fuentes.linea(i["component"], i.get("line")))
        if d is None:
            continue
        sonar.post("/api/issues/add_comment", issue=i["key"], text="Deuda aceptada: " + d["justificacion"])
        codigo, _ = sonar.post("/api/issues/do_transition", issue=i["key"], transition="accept")
        if codigo != 200:
            codigo, _ = sonar.post("/api/issues/do_transition", issue=i["key"], transition="wontfix")
        aceptadas.append({"issue": i["key"], "regla": i["rule"], "archivo": archivo, "linea": i.get("line"),
                          "codigo": codigo})
    pendientes, _ = sonar.get_paginado("/api/hotspots/search", "hotspots", project=PROYECTO, status="TO_REVIEW")
    for h in pendientes:
        archivo = h["component"].split(":", 1)[-1]
        d = _decision(datos.get("hotspots_seguros", []), h["ruleKey"], archivo,
                      fuentes.linea(h["component"], h.get("line")))
        if d is None:
            continue
        codigo, _ = sonar.post("/api/hotspots/change_status", hotspot=h["key"], status="REVIEWED", resolution="SAFE",
                               comment=d["justificacion"])
        seguros.append({"hotspot": h["key"], "regla": h["ruleKey"], "archivo": archivo, "linea": h.get("line"),
                        "codigo": codigo})
    _escribir(f"Decisiones aplicadas: {len(aceptadas)} hallazgos de mantenibilidad aceptados con justificación; "
              f"{len(seguros)} de {len(pendientes)} security hotspots marcados seguros.")
    return {"deuda_aceptada": aceptadas, "hotspots_seguros": seguros}


# ------------------------------------------------------------------------------------------------ evidencia
def exportar(sonar: Sonar, version: str, condiciones: list, perfil: dict | None, pruebas: dict | None,
             lint: dict | None, codigo_scanner: int | None) -> str:
    EVIDENCIA.mkdir(parents=True, exist_ok=True)
    estado = sonar.get("/api/qualitygates/project_status", projectKey=PROYECTO)
    definicion = sonar.get("/api/qualitygates/show", name=NOMBRE_PUERTA)
    medidas = sonar.get("/api/measures/component", component=PROYECTO, metricKeys=METRICAS)
    issues, primera = sonar.get_paginado("/api/issues/search", "issues", componentKeys=PROYECTO, resolved="false",
                                         facets="severities,types,impactSeverities,impactSoftwareQualities,rules")
    aceptados, _ = sonar.get_paginado("/api/issues/search", "issues", componentKeys=PROYECTO,
                                      issueStatuses="ACCEPTED", additionalFields="comments")
    hotspots, _ = sonar.get_paginado("/api/hotspots/search", "hotspots", project=PROYECTO)
    analisis = sonar.get("/api/project_analyses/search", project=PROYECTO, ps=1).get("analyses", [])
    if perfil is None:
        perfiles = sonar.get("/api/qualityprofiles/search", project=PROYECTO)["profiles"]
        perfil = {"perfil": next((p for p in perfiles if p["language"] == "py"), None)}
    generado = datetime.now(TZ).isoformat(timespec="seconds")
    base = {"servidor": f"SonarQube {version} (Community Build, Docker)", "proyecto": PROYECTO,
            "generado_en": generado, "ultimo_analisis": analisis[0] if analisis else None}

    def guardar(nombre: str, datos: dict) -> None:
        (EVIDENCIA / nombre).write_text(json.dumps(base | datos, ensure_ascii=False, indent=1) + "\n",
                                        encoding="utf-8")

    guardar("quality_gate.json", {"puerta": NOMBRE_PUERTA, "estado": estado["projectStatus"],
                                  "definicion": definicion})
    guardar("measures.json", {"medidas": {m["metric"]: m.get("value") for m in medidas["component"]["measures"]},
                              "respuesta": medidas})
    campos = ("key", "rule", "severity", "type", "impacts", "component", "line", "message", "status",
              "issueStatus", "resolution", "cleanCodeAttribute", "tags", "effort")
    guardar("issues.json", {"total_abiertos": len(issues), "total_aceptados": len(aceptados),
                            "facetas": primera.get("facets", []),
                            "issues": [{k: i.get(k) for k in campos} for i in issues],
                            "aceptados_con_justificacion": [
                                {**{k: i.get(k) for k in campos},
                                 "justificacion": next((c.get("markdown") or c.get("htmlText") for c in
                                                        i.get("comments", [])), None)} for i in aceptados]})
    guardar("hotspots.json", {"total": len(hotspots), "hotspots": hotspots})
    guardar("perfil_calidad.json", perfil)

    valores = {m["metric"]: m.get("value") for m in medidas["component"]["measures"]}
    estado_puerta = estado["projectStatus"]["status"]
    texto = _resumen_md(version, generado, estado, valores, issues, hotspots, perfil, pruebas, lint, codigo_scanner,
                        condiciones, analisis[0] if analisis else None, aceptados)
    (EVIDENCIA / "resumen.md").write_text(texto, encoding="utf-8")
    _escribir(f"Puerta de calidad «{NOMBRE_PUERTA}»: {estado_puerta}. Evidencia en {EVIDENCIA.relative_to(RAIZ)}.")
    return estado_puerta


def _nota(valor: str | None) -> str:
    return {"1.0": "A", "2.0": "B", "3.0": "C", "4.0": "D", "5.0": "E"}.get(valor or "", valor or "—")


def _resumen_md(version, generado, estado, valores, issues, hotspots, perfil, pruebas, lint, codigo_scanner,
                condiciones, analisis, aceptados) -> str:
    st = estado["projectStatus"]
    lectura = {m: t for m, _, _, t in condiciones}
    lineas = [
        "# SonarQube: análisis del backend de frecuencias",
        "",
        f"- Servidor: SonarQube {version} (Community Build) en Docker, contenedor `{CONTENEDOR}`, 127.0.0.1:{PUERTO}.",
        f"- Proyecto: `{PROYECTO}` (código analizado: `app/`; pruebas: `tests/`).",
        f"- Análisis: {analisis.get('date') if analisis else '—'} · evidencia generada {generado}.",
        f"- Perfil de calidad: «{NOMBRE_PERFIL}» (hereda de «{perfil.get('perfil_padre', 'Sonar way')}», el perfil "
        "integrado más completo de SonarQube para Python, y activa además todas las reglas de seguridad de Python): "
        f"{perfil.get('perfil', {}).get('activeRuleCount', '—')} reglas activas, "
        f"{perfil.get('reglas_seguridad_activas', '—')} de seguridad ({perfil.get('reglas_seguridad_padre', '—')} del "
        f"perfil padre más {', '.join(r['regla'] for r in perfil.get('reglas_seguridad_agregadas', [])) or '—'}).",
        "",
        f"## Puerta de calidad «{NOMBRE_PUERTA}»: **{'APROBADA' if st['status'] == 'OK' else st['status']}**",
        "",
        "Se evalúa sobre todo el código (no solo el código nuevo). Cada condición falla si se cumple la comparación.",
        "",
        "| Condición | Falla si | Valor medido | Resultado |",
        "|---|---|---|---|",
    ]
    for c in st.get("conditions", []):
        op = {"GT": ">", "LT": "<"}.get(c.get("comparator"), c.get("comparator"))
        lineas.append(f"| {lectura.get(c['metricKey'], c['metricKey'])} (`{c['metricKey']}`) | {op} "
                      f"{c.get('errorThreshold')} | {c.get('actualValue', 'sin valor')} | "
                      f"{'cumple' if c['status'] == 'OK' else c['status']} |")
    sin_valor = [m for m, *_ in condiciones if m not in {c["metricKey"] for c in st.get("conditions", [])}]
    if sin_valor:
        lineas.append("")
        lineas.append(f"Condiciones sin valor en este análisis (no aplican): {', '.join(sin_valor)}. "
                      "`security_hotspots_reviewed` no tiene valor cuando no hay security hotspots.")
    abiertos = {}
    for i in issues:
        abiertos[i.get("severity")] = abiertos.get(i.get("severity"), 0) + 1
    lineas += [
        "",
        "## Medidas (todo el código)",
        "",
        "| Medida | Valor |",
        "|---|---|",
        f"| Líneas de código (ncloc) | {valores.get('ncloc')} |",
        f"| Bugs | {valores.get('bugs')} |",
        f"| Vulnerabilidades | {valores.get('vulnerabilities')} |",
        f"| Security hotspots (revisados) | {valores.get('security_hotspots')} "
        f"({valores.get('security_hotspots_reviewed', '—')} %) |",
        f"| Code smells | {valores.get('code_smells')} |",
        f"| Cobertura de pruebas | {valores.get('coverage')} % (líneas por cubrir: {valores.get('lines_to_cover')}, "
        f"sin cubrir: {valores.get('uncovered_lines')}) |",
        f"| Duplicación | {valores.get('duplicated_lines_density')} % |",
        f"| Confiabilidad / Seguridad / Mantenibilidad | {_nota(valores.get('reliability_rating'))} / "
        f"{_nota(valores.get('security_rating'))} / {_nota(valores.get('sqale_rating'))} |",
        f"| Confiabilidad / Seguridad / Mantenibilidad, vista por impacto (la del tablero) | "
        f"{_nota(valores.get('software_quality_reliability_rating'))} "
        f"({valores.get('software_quality_reliability_issues')} hallazgos) / "
        f"{_nota(valores.get('software_quality_security_rating'))} "
        f"({valores.get('software_quality_security_issues')}) / "
        f"{_nota(valores.get('software_quality_maintainability_rating'))} "
        f"({valores.get('software_quality_maintainability_issues')}) |",
        f"| Revisión de seguridad | {_nota(valores.get('security_review_rating'))} |",
        f"| Hallazgos aceptados con justificación | {valores.get('accepted_issues')} |",
        f"| Deuda técnica | {valores.get('sqale_index')} min ({valores.get('sqale_debt_ratio')} %) |",
        f"| Pruebas importadas (junit) | {valores.get('tests')} (fallas {valores.get('test_failures')}, errores "
        f"{valores.get('test_errors')}, omitidas {valores.get('skipped_tests')}) |",
        "",
        f"Hallazgos abiertos: {len(issues)} "
        f"({', '.join(f'{k}: {v}' for k, v in sorted(abiertos.items(), key=lambda x: str(x[0]))) or 'ninguno'}). "
        "El detalle de cada uno está en `issues.json`; los security hotspots y su revisión, en `hotspots.json`.",
    ]
    criticos_abiertos = [i for i in issues if i.get("severity") in ("BLOCKER", "CRITICAL")]
    if criticos_abiertos:
        lineas += ["", "### Hallazgos bloqueantes o críticos abiertos", "", "| Regla | Severidad | Archivo:línea |",
                   "|---|---|---|"]
        lineas += [f"| `{i['rule']}` | {i['severity']} | `{i['component'].split(':', 1)[-1]}:{i.get('line')}` |"
                   for i in criticos_abiertos]
    if aceptados:
        lineas += ["", "### Deuda de mantenibilidad aceptada con justificación", "",
                   f"{len(aceptados)} hallazgos de mantenibilidad (code smells) se aceptaron uno por uno con su "
                   "justificación, que queda como comentario en SonarQube y en `issues.json` "
                   "(`aceptados_con_justificacion`). Las decisiones están versionadas en "
                   "`scripts/sonar_decisiones.json`;"
                   " ningún bug, vulnerabilidad ni hallazgo de seguridad se acepta por esta vía.", "",
                   "| Regla | Severidad | Archivo:línea |", "|---|---|---|"]
        lineas += [f"| `{i['rule']}` | {i.get('severity')} | `{i['component'].split(':', 1)[-1]}:{i.get('line')}` |"
                   for i in aceptados]
    revisados = [h for h in hotspots if h.get("status") == "REVIEWED"]
    if hotspots:
        lineas += ["", f"Security hotspots: {len(hotspots)}, revisados {len(revisados)}.", ""]
        for h in hotspots:
            lineas.append(f"- `{h['ruleKey']}` en `{h['component'].split(':', 1)[-1]}:{h.get('line')}` · "
                          f"{h.get('status')} {h.get('resolution') or ''}".rstrip())
    if pruebas:
        lineas += ["", "## Pruebas y análisis estático que alimentan el análisis", "",
                   f"- pytest (todas las suites salvo Testcontainers): {pruebas['tests']} pruebas, "
                   f"{pruebas['failures']} fallas, {pruebas['errors']} errores, {pruebas['skipped']} omitidas, "
                   f"código de salida {pruebas['codigo_salida']}, {pruebas['duracion_s']} s. La cobertura que lee "
                   "SonarQube incluye todo `app/` (también `app/servicios/motor_d5/`)."]
    if lint:
        lineas += [f"- ruff (todo el repositorio de la API): {lint['ruff']['hallazgos']} hallazgos "
                   f"(`docs/evidencias/calidad/ruff.txt`).",
                   f"- bandit `-r app` (todas las severidades): {lint['bandit_app']['hallazgos']} hallazgos; "
                   f"bandit `-r scripts -ll`: {lint['bandit_scripts']['hallazgos']} "
                   "(`docs/evidencias/calidad/bandit.txt`)."]
    if codigo_scanner is not None:
        lineas.append(f"- sonar-scanner-cli terminó con código {codigo_scanner} (0 = puerta aprobada; el registro "
                      "está en `scanner.log`).")
    lineas += [
        "",
        "## Alcance y límites",
        "",
        "- La edición Community de SonarQube no incluye el análisis de flujo de datos (taint analysis) que detecta "
        "inyecciones; el tablero lo advierte. Ese frente lo cubren bandit (`-r app`, todas las severidades), la regla "
        "de solo lectura de la fuente (`app/servicios/fuentes.py`: solo SELECT, transacción READ ONLY y "
        "statement_timeout) y las pruebas de seguridad de `tests/unit` y `tests/integracion`.",
        "- La base embebida de SonarQube (H2) sirve para evaluación, como advierte el tablero; el análisis es completo "
        "y se reproduce con el script de abajo.",
        "",
        "## Cómo reproducirlo",
        "",
        "```",
        "cd EntregaFinal/api_frecuencias",
        ".venv/Scripts/python.exe scripts/sonar_local.py --archivo-clave <ruta fuera del repositorio>/sonar_admin.txt",
        "```",
        "",
        "El script arranca SonarQube en Docker, crea el perfil y la puerta, corre las pruebas con cobertura, ruff y "
        "bandit, ejecuta sonar-scanner-cli y reescribe esta carpeta. La clave de admin se guarda solo en el archivo "
        "indicado (fuera del repositorio) y el token de análisis vive en memoria y se revoca al terminar.",
        "",
        "Archivos: `quality_gate.json` (estado y definición de la puerta), `measures.json`, `issues.json`, "
        "`hotspots.json`, `perfil_calidad.json`, `scanner.log` y `tablero_sonarqube.png` (tablero del proyecto, "
        "código completo).",
        "",
    ]
    return "\n".join(lineas)


def capturar_tablero(clave: str) -> None:
    """PNG del tablero del proyecto (pestaña de todo el código). La sesión se abre por la API: la clave no se teclea
    en ninguna página y no aparece en la captura."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        navegador = p.chromium.launch(channel="msedge", headless=True)
        contexto = navegador.new_context(viewport={"width": 1440, "height": 1100}, locale="es-CO")
        r = contexto.request.post(f"{HOST}/api/authentication/login", form={"login": USUARIO_ADMIN, "password": clave})
        if not r.ok:
            raise RuntimeError(f"no se pudo abrir sesión en la interfaz ({r.status})")
        pagina = contexto.new_page()
        pagina.goto(f"{HOST}/dashboard?id={PROYECTO}&codeScope=overall", wait_until="networkidle")
        pagina.wait_for_timeout(4000)
        # Avisos promocionales de la edición Community (no son parte del análisis): se cierran antes de la captura.
        try:
            pagina.get_by_text("Get the most out of", exact=False).first.wait_for(timeout=6000)
        except Exception:  # noqa: BLE001, S110  # nosec B110  # el aviso no siempre aparece
            pass
        for nombre in ("Dismiss", "Descartar"):
            boton = pagina.locator(f"button:has-text('{nombre}'), a:has-text('{nombre}')")
            for k in range(boton.count()):
                try:
                    boton.nth(k).click(timeout=2000)
                    pagina.wait_for_timeout(1500)
                except Exception:  # noqa: BLE001, S112  # nosec B112  # un aviso que no se cierra no afecta la captura
                    continue
        cerrar = pagina.locator("[role=alert] button, .it__banner button, button[aria-label*='Dismiss']")
        for k in range(cerrar.count()):
            try:
                cerrar.nth(k).click(timeout=1000)
            except Exception:  # noqa: BLE001, S112  # nosec B112  # un aviso que no se cierra no afecta la captura
                continue
        pagina.keyboard.press("Escape")
        pagina.wait_for_timeout(1000)
        pagina.screenshot(path=str(EVIDENCIA / "tablero_sonarqube.png"), full_page=True)
        pagina.goto(f"{HOST}/project/issues?id={PROYECTO}&issueStatuses=OPEN%2CCONFIRMED", wait_until="networkidle")
        pagina.wait_for_timeout(3000)
        pagina.screenshot(path=str(EVIDENCIA / "hallazgos_sonarqube.png"), full_page=False)
        navegador.close()
    _escribir("Capturas del tablero en docs/evidencias/sonarqube/.")


# ------------------------------------------------------------------------------------------------ principal
def main() -> int:
    for flujo in (sys.stdout, sys.stderr):
        if hasattr(flujo, "reconfigure"):
            flujo.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--archivo-clave", type=Path,
                    default=Path(os.environ.get("SONAR_CLAVE_ARCHIVO", Path.home() / ".sobusa_sonar" /
                                                "sonar_admin.txt")),
                    help="archivo FUERA del repositorio donde vive la clave de admin")
    ap.add_argument("--sin-pruebas", action="store_true", help="no corre pytest (usa --cobertura-previa)")
    ap.add_argument("--cobertura-previa", type=Path, default=EVIDENCIA,
                    help="carpeta con coverage.xml y pytest.xml de una corrida anterior (con --sin-pruebas)")
    ap.add_argument("--pruebas", nargs="+", default=PRUEBAS_POR_OMISION, help="carpetas de pruebas para pytest")
    ap.add_argument("--solo-exportar", action="store_true", help="solo relee la puerta y rehace la evidencia")
    ap.add_argument("--sin-captura", action="store_true", help="no toma la captura del tablero")
    ap.add_argument("--detener", action="store_true", help="apaga el contenedor al final")
    args = ap.parse_args()

    asegurar_contenedor()
    version = esperar_up()
    clave = asegurar_clave(args.archivo_clave)
    sonar = Sonar(clave)
    asegurar_proyecto(sonar)
    perfil = asegurar_perfil(sonar)
    condiciones = asegurar_puerta(sonar)
    pruebas = lint = codigo_scanner = None
    if not args.solo_exportar:
        area = Path(tempfile.mkdtemp(prefix="sonar_area_"))
        try:
            (area / "reportes").mkdir()
            if not args.sin_pruebas:
                pruebas = correr_pruebas(area, args.pruebas, area / "pytest.log")
            lint = correr_lint(area)
            preparar_area(area, None if pruebas else args.cobertura_previa)
            nombre_token, token = crear_token(sonar)
            try:
                codigo_scanner = correr_scanner(area, token, EVIDENCIA / "scanner.log")
            finally:
                revocar_token(sonar, nombre_token)
                del token
            tarea = esperar_tarea(sonar)
            _escribir(f"Tarea de análisis {tarea.get('id')}: {tarea.get('status')}.")
            if pruebas:  # la cobertura y el junit de esta corrida quedan junto a la evidencia
                EVIDENCIA.mkdir(parents=True, exist_ok=True)
                for nombre in ("coverage.xml", "pytest.xml"):
                    texto = (area / "src" / "reportes" / nombre).read_text(encoding="utf-8")
                    (EVIDENCIA / nombre).write_text(_enmascarar(texto), encoding="utf-8")
                texto = (area / "pytest.log").read_text(encoding="utf-8", errors="replace")
                (EVIDENCIA / "pytest.log").write_text(_enmascarar(texto), encoding="utf-8")
        finally:
            shutil.rmtree(area, ignore_errors=True)
    decisiones = aplicar_decisiones(sonar)
    if decisiones["deuda_aceptada"] or decisiones["hotspots_seguros"]:
        time.sleep(8)  # SonarQube recalcula las medidas y la puerta tras cada cambio de estado
    # La corrida completa deja sus cifras (pytest, ruff, bandit y scanner) en corrida.json; --solo-exportar las reusa
    corrida = EVIDENCIA / "corrida.json"
    if not args.solo_exportar:
        EVIDENCIA.mkdir(parents=True, exist_ok=True)
        corrida.write_text(json.dumps({"pruebas": pruebas, "lint": lint, "codigo_scanner": codigo_scanner,
                                       "generado_en": datetime.now(TZ).isoformat(timespec="seconds")},
                                      ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    elif corrida.exists():
        previa = json.loads(corrida.read_text(encoding="utf-8"))
        pruebas, lint, codigo_scanner = previa.get("pruebas"), previa.get("lint"), previa.get("codigo_scanner")
    estado = exportar(sonar, version, condiciones, perfil, pruebas, lint, codigo_scanner)
    if not args.sin_captura:
        try:
            capturar_tablero(clave)
        except Exception as exc:  # noqa: BLE001 - la captura es evidencia adicional; no cambia la puerta
            _escribir(f"aviso: no se pudo tomar la captura del tablero: {exc}")
    if args.detener:
        _docker("stop", CONTENEDOR)
        _escribir(f"Contenedor {CONTENEDOR} detenido (sus volúmenes se conservan).")
    return 0 if estado == "OK" else 1


if __name__ == "__main__":
    sys.exit(main())
