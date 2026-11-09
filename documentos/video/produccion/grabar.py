"""Graba el recorrido del video E11 con Playwright (Edge), escena por escena, contra la API (8371) y el tablero (8372)
aislados. Cada escena se prepara fuera de cámara (carga de la página), luego corre su narración (duración medida del
WAV) con las acciones a sus tiempos, y se anota su tramo [inicio, fin] del video crudo; la mezcla corta solo esos
tramos. La clave de API nunca aparece en pantalla: se agrega como cabecera a las peticiones del navegador hacia la API.
Uso: python grabar.py [id_escena ...]   (sin argumentos, todas)"""
import json
import sys
import time
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright

AQUI = Path(__file__).resolve().parent
API, DASH = "http://127.0.0.1:8371", "http://127.0.0.1:8372"
CLAVES = json.loads((AQUI / "claves.json").read_text(encoding="utf-8"))
VOZ = json.loads((AQUI / "voz/resumen.json").read_text(encoding="utf-8"))
F = 16000 / 22050  # las marcas de System.Speech vienen en la escala de 16 kHz; el WAV es de 22,05 kHz
RESPIRO = 0.6
DIA_NUEVO = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1].startswith("2025-") else "2025-09-04"
SOLO = [a for a in sys.argv[1:] if not a.startswith("2025-")]
VIS = (AQUI / "visores").as_uri()
cli = httpx.Client(base_url=API, headers={"X-API-Key": CLAVES["analista"]}, timeout=60)
estado = {}


def marca(eid, i):
    return VOZ[eid]["inicios_s"][i] * F


class Reloj:
    def __init__(self, pg):
        self.pg, self.ini = pg, time.perf_counter()

    def hasta(self, t):
        falta = self.ini + t - time.perf_counter()
        if falta > 0:
            self.pg.wait_for_timeout(falta * 1000)


def sin_carga(pg, extra=800):
    pg.wait_for_function("() => !document.querySelector('[data-dash-is-loading=\"true\"]')", timeout=90000)
    pg.wait_for_timeout(extra)


def ir_dash(pg, ruta, extra=1500):
    pg.goto(DASH + ruta, wait_until="networkidle")
    pg.wait_for_selector("#contenido h1", timeout=30000)
    sin_carga(pg, extra)


def desplazar(pg, selector, ajuste=-96, suave=True):
    pg.evaluate("([s, a, suave]) => { const e = document.querySelector(s); if (!e) return;"
                " const y = e.getBoundingClientRect().top + window.scrollY + a;"
                " window.scrollTo({top: Math.max(0, y), behavior: suave ? 'smooth' : 'auto'}); }", [selector, ajuste, suave])


# --- Escenas -----------------------------------------------------------------------------------------------------
def p_s01(pg):
    ir_dash(pg, "/", 3000)


def a_s01(pg, r):
    r.hasta(marca("s01_problema", 2) - 0.3)
    desplazar(pg, "#inicio-respuesta", -96)


def a_s02(pg, r):
    r.hasta(1.0)
    desplazar(pg, "#in-resp-cuerpo", -150)
    r.hasta(8.0)
    pg.locator("#in-resp-ruta label", has_text="CRA 54").first.click()
    sin_carga(pg, 300)


def p_s03(pg):
    pg.goto(API + "/docs", wait_until="networkidle")
    pg.wait_for_selector(".opblock", timeout=30000)
    pg.wait_for_timeout(800)
    desplazar(pg, ".opblock-post .opblock-summary-path[data-path='/api/v1/frequency/executions']", -120, False)
    pg.wait_for_timeout(600)


def a_s03(pg, r):
    r.hasta(0.8)
    pg.locator(".opblock-post .opblock-summary-path[data-path='/api/v1/frequency/executions']").first.click()
    bloque = pg.locator(".opblock.opblock-post.is-open").first
    r.hasta(2.6)
    bloque.locator(".try-out__btn").click()
    r.hasta(4.2)
    bloque.locator("textarea.body-param__text").fill('{\n  "hasta": "' + DIA_NUEVO + '"\n}')
    r.hasta(6.8)
    bloque.locator(".execute").click()
    bloque.locator(".live-responses-table").first.wait_for(timeout=30000)
    texto = bloque.locator(".live-responses-table .highlight-code pre, .live-responses-table pre.microlight").first.inner_text()
    estado["respuesta_post"] = json.loads(texto)
    r.hasta(8.6)
    pg.evaluate("() => { const b = document.querySelector('.opblock.opblock-post.is-open .live-responses-table');"
                " b && b.scrollIntoView({block: 'center', behavior: 'smooth'}); }")


def p_s04(pg):
    eid = estado["respuesta_post"]["execution_id"]
    fin = time.time() + 600
    while time.time() < fin:
        d = cli.get(f"/api/v1/frequency/executions/{eid}").json()
        if d["estado"] in ("ok", "error"):
            break
        time.sleep(2)
    estado["ejecucion"] = d
    pg.locator(".opblock-post .opblock-summary-path[data-path='/api/v1/frequency/executions']").first.click()
    pg.wait_for_timeout(500)
    desplazar(pg, ".opblock-get .opblock-summary-path[data-path='/api/v1/frequency/executions/{execution_id}']", -120, False)
    pg.wait_for_timeout(600)


def a_s04(pg, r):
    r.hasta(0.5)
    pg.locator(".opblock-get .opblock-summary-path[data-path='/api/v1/frequency/executions/{execution_id}']").first.click()
    bloque = pg.locator(".opblock.opblock-get.is-open").first
    r.hasta(1.8)
    bloque.locator(".try-out__btn").click()
    r.hasta(3.0)
    bloque.locator("tr[data-param-name='execution_id'] input").fill(estado["respuesta_post"]["execution_id"])
    r.hasta(4.6)
    bloque.locator(".execute").click()
    bloque.locator(".live-responses-table").first.wait_for(timeout=30000)
    r.hasta(6.0)
    pg.evaluate("() => { const b = document.querySelector('.opblock.opblock-get.is-open .live-responses-table .response-col_description');"
                " if (!b) return; const y = b.getBoundingClientRect().top + window.scrollY - 70;"
                " window.scrollTo({top: y, behavior: 'smooth'}); }")


def p_s05(pg):
    pg.goto(f"{VIS}/modelo.html", wait_until="load")
    pg.wait_for_timeout(400)


def a_s05(pg, r):
    r.hasta(marca("s05_modelo", 3) - 0.2)
    desplazar(pg, ".tarjeta:nth-of-type(2)", -40)


def p_s06(pg):
    ir_dash(pg, "/pronostico", 2500)


def a_s06(pg, r):
    r.hasta(marca("s06_pronostico", 1) - 0.4)
    pg.locator("header a, nav a", has_text="Horario").first.click()
    pg.wait_for_url("**/horario", timeout=15000)
    sin_carga(pg, 200)


def p_s07(pg):
    ir_dash(pg, "/despacho", 5000)


def a_s07(pg, r):
    r.hasta(1.0)


def p_s08(pg):
    ir_dash(pg, "/alertas", 2500)


def campo(pg, ident):
    return pg.locator(f"input#{ident}, #{ident} input, textarea#{ident}, #{ident} textarea").first


def a_s08(pg, r):
    r.hasta(0.6)
    pg.locator(".al-fila, .api-fila").first.click()
    sin_carga(pg, 200)
    r.hasta(2.0)
    desplazar(pg, "#al-tarjeta-detalle", -90)
    r.hasta(marca("s08_alertas", 1) + 0.4)
    desplazar(pg, "#al-campos", -90)
    r.hasta(marca("s08_alertas", 2) - 0.2)
    desplazar(pg, ".api-acciones", -260)
    r.hasta(marca("s08_alertas", 2) + 0.8)
    pg.locator("#al-reconocer").click()
    sin_carga(pg, 200)
    campo(pg, "al-asignado").fill("supervisor.turno")
    pg.locator("#al-asignar").click()
    sin_carga(pg, 200)
    campo(pg, "al-comentario").fill("Se ajustó la salida de la hora pico")
    pg.locator("#al-cerrar").click()
    sin_carga(pg, 300)
    r.hasta(marca("s08_alertas", 3) + 0.2)
    desplazar(pg, "#al-historial", -120)


def p_s09(pg):
    ir_dash(pg, "/recomendaciones", 3500)


def a_s09(pg, r):
    r.hasta(1.2)
    desplazar(pg, "#re-plan-cifras", -160)
    r.hasta(marca("s09_recomendaciones", 2) - 4.0)
    pg.locator("#re-calcular").click()
    sin_carga(pg, 300)
    r.hasta(marca("s09_recomendaciones", 2) - 0.3)
    desplazar(pg, "#re-escenario", -96)


def p_s10(pg):
    ir_dash(pg, "/monitoreo", 3000)


def a_s10(pg, r):
    r.hasta(3.0)
    desplazar(pg, "#mo-tarjeta-psi", -96)
    r.hasta(marca("s10_monitoreo", 1) - 0.2)
    desplazar(pg, "#mo-sombra", -120)


def p_s11(pg):
    pg.goto(f"{VIS}/ciclo.html", wait_until="load")
    pg.wait_for_timeout(400)


def a_s11(pg, r):
    # frase i de la narración -> paso del registro que se muestra (la frase 3 cubre los pasos 3 y 4)
    for i, paso in ((1, "#paso1"), (2, "#paso2"), (3, "#paso3"), (4, "#paso5"), (5, "#paso6")):
        r.hasta(marca("s11_ciclo", i) - 0.2)
        desplazar(pg, paso, -24)


def p_vis(nombre):
    def _p(pg):
        pg.goto(f"{VIS}/{nombre}", wait_until="load")
        pg.wait_for_timeout(400)
    return _p


def nada(pg, r):
    r.hasta(0.5)


def sin_preparar(pg):
    pass


ESCENAS = [("s01_problema", p_s01, a_s01), ("s02_respuesta", sin_preparar, a_s02), ("s03_dia_nuevo", p_s03, a_s03),
           ("s04_lectura", p_s04, a_s04), ("s05_modelo", p_s05, a_s05), ("s06_pronostico", p_s06, a_s06),
           ("s07_despacho", p_s07, a_s07), ("s08_alertas", p_s08, a_s08), ("s09_recomendaciones", p_s09, a_s09),
           ("s10_monitoreo", p_s10, a_s10), ("s11_ciclo", p_s11, a_s11), ("s12_ingenieria", p_vis("ingenieria.html"), nada),
           ("s13_cierre", p_vis("cierre.html"), nada)]
SOLO_VISORES = {"s05_modelo", "s11_ciclo", "s12_ingenieria", "s13_cierre"}
if SOLO:
    ESCENAS = [e for e in ESCENAS if e[0] in SOLO]

linea, t_reloj = [], time.perf_counter()
with sync_playwright() as p:
    nav = p.chromium.launch(channel="msedge")
    ctx = nav.new_context(viewport={"width": 1600, "height": 900}, device_scale_factor=1, locale="es-CO",
                          record_video_dir=str(AQUI / "crudo"), record_video_size={"width": 1600, "height": 900})

    def con_clave(route):
        h = dict(route.request.headers)
        h["x-api-key"] = CLAVES["analista"]
        route.continue_(headers=h)

    ctx.route("http://127.0.0.1:8371/api/**", con_clave)
    pg = ctx.new_page()
    t0 = time.perf_counter()
    errores = []
    pg.on("console", lambda m: errores.append(f"{m.type}: {m.text[:160]}") if m.type == "error" else None)
    pg.on("pageerror", lambda e: errores.append(f"pageerror: {str(e)[:160]}"))
    for eid, prep, acc in ESCENAS:
        errores.clear()
        prep(pg)
        r = Reloj(pg)
        fallo = None
        try:
            acc(pg, r)
        except Exception as ex:  # se anota y la escena sigue con lo que alcanzó a mostrar
            fallo = f"{type(ex).__name__}: {str(ex)[:300]}"
        r.hasta(VOZ[eid]["audio_s"] + RESPIRO)
        fin = time.perf_counter()
        linea.append({"id": eid, "inicio_s": round(r.ini - t0, 3), "fin_s": round(fin - t0, 3),
                      "audio_s": VOZ[eid]["audio_s"], "tramo_s": round(fin - r.ini, 3), "fallo": fallo,
                      "errores_consola": list(errores)})
        print(json.dumps(linea[-1], ensure_ascii=False), flush=True)
    video = pg.video.path()
    ctx.close()
    nav.close()

extra = {}
if "respuesta_post" in estado:
    extra["respuesta_post"] = estado["respuesta_post"]
    d = cli.get(f"/api/v1/frequency/executions/{estado['respuesta_post']['execution_id']}").json()
    extra["ejecucion"] = {k: d.get(k) for k in ("execution_id", "estado", "mensaje", "marca_agua_anterior", "marca_agua_nueva",
                                                 "filas_leidas", "filas_validas")}
    extra["ejecucion"]["metricas"] = {k: (d.get("metricas") or {}).get(k) for k in ("predicciones", "recomendaciones", "alertas_nuevas")}
# Las escenas 5, 11, 12 y 13 son páginas locales de evidencia: si solo se grabaron esas, no se consulta la API
if any(e["id"] not in SOLO_VISORES for e in linea):
    cerradas = cli.get("/api/v1/alerts", params={"estado": "cerrada", "limite": 5}).json()
    extra["alertas_cerradas"] = [{k: a.get(k) for k in ("alert_id", "codigo", "estado", "asignado_a")} for a in cerradas.get("items", [])]
for e in linea:
    e["video"] = str(video)
(AQUI / f"linea_tiempo_{int(time.time())}.json").write_text(json.dumps({"video": str(video), "escenas": linea, "api": extra,
                                                    "segundos_reloj": round(time.perf_counter() - t_reloj, 1)},
                                                   ensure_ascii=False, indent=1), encoding="utf-8")
print("video:", video, "· reloj", round(time.perf_counter() - t_reloj, 1), "s · tramos", round(sum(e["tramo_s"] for e in linea), 1), "s")
