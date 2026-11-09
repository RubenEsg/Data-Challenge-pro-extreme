"""Genera las páginas de evidencia que se muestran en el video: copian literalmente las líneas de los archivos de
evidencia (con su ruta visible) para que cada cifra narrada se vea con su fuente. Uso: python visores.py"""
import html
import json
import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path

AQUI = Path(__file__).resolve().parent
# Raíz del repositorio (la carpeta que contiene EntregaFinal/ y .github/); se puede cambiar con VIDEO_RAIZ_REPO
RAIZ = Path(os.environ.get("VIDEO_RAIZ_REPO") or Path(__file__).resolve().parents[4])
EF = RAIZ / "EntregaFinal"
EV = EF / "api_frecuencias/docs/evidencias"
OUT = AQUI / "visores"
OUT.mkdir(exist_ok=True)

CSS = """
:root { --fondo: #efefef; --tarjeta: #ffffff; --texto: #1d1d1f; --suave: #5b5b62; --acento: #1f4fd1; --resalte: #fff1b8; --borde: #dcdce0; }
* { box-sizing: border-box; }
body { margin: 0; background: var(--fondo); color: var(--texto); font-family: "Segoe UI", system-ui, sans-serif; }
main { max-width: 1480px; margin: 0 auto; padding: 36px 40px 60px; }
.eti { font-size: 15px; letter-spacing: .08em; text-transform: uppercase; color: var(--suave); margin: 0 0 6px; }
h1 { font-size: 46px; font-weight: 600; margin: 0 0 22px; letter-spacing: -.01em; }
.tarjeta { background: var(--tarjeta); border: 1px solid var(--borde); border-radius: 22px; padding: 22px 28px; margin-bottom: 20px; }
.ruta { font-family: Consolas, monospace; font-size: 15px; color: var(--suave); margin: 0 0 12px; }
.ruta b { color: var(--acento); font-weight: 600; }
table { border-collapse: collapse; width: 100%; font-size: 21px; }
th, td { text-align: right; padding: 10px 12px; border-bottom: 1px solid var(--borde); }
th:first-child, td:first-child { text-align: left; }
th { font-size: 16px; color: var(--suave); font-weight: 600; }
mark { background: var(--resalte); color: inherit; padding: 0 4px; border-radius: 6px; font-weight: 600; }
pre { font-family: Consolas, monospace; font-size: 18px; line-height: 1.5; white-space: pre-wrap; margin: 0; }
.paso { color: var(--acento); font-weight: 700; }
.rejilla { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
.rejilla .tarjeta { margin: 0; }
.cifra { font-size: 54px; font-weight: 600; margin: 4px 0 2px; }
.nota { font-size: 18px; color: var(--suave); margin: 0; }
.cita { font-size: 20px; line-height: 1.5; margin: 0; }
.fases { display: grid; grid-template-columns: repeat(3, 1fr); gap: 20px; margin-top: 12px; }
.fase h2 { font-size: 30px; margin: 4px 0 8px; font-weight: 600; }
.fase p { font-size: 20px; line-height: 1.45; margin: 0; color: var(--suave); }
.num { font-size: 18px; color: var(--acento); font-weight: 700; letter-spacing: .06em; }
"""


def pagina(nombre, titulo, cuerpo):
    (OUT / nombre).write_text(
        f"<!doctype html><html lang='es'><head><meta charset='utf-8'><title>{html.escape(titulo)}</title>"
        f"<style>{CSS}</style></head><body><main>{cuerpo}</main></body></html>", encoding="utf-8")


def resaltar(texto, cifras):
    t = html.escape(texto)
    for c in cifras:
        t = t.replace(html.escape(c), f"<mark>{html.escape(c)}</mark>")
    return t


# --- Modelo: tabla de la prueba reservada + calibración + algoritmo ------------------------------------------------
ev = (EV / "modelo/evaluacion_modelo.md").read_text(encoding="utf-8").splitlines()
i_cab = next(i for i, l in enumerate(ev) if l.startswith("| Modelo"))
cab = ev[i_cab]
tabla = []
for l in ev[i_cab + 2:]:
    if not l.startswith("|"):
        break
    tabla.append(l)
filas = [l for l in tabla if l.startswith("| activo") or l.startswith("| B1") or l.startswith("| B2")]
celdas = lambda l: [c.strip() for c in l.strip().strip("|").split("|")]
th = "".join(f"<th>{html.escape(c)}</th>" for c in celdas(cab))
tr = ""
for f in filas:
    cs = celdas(f)
    tr += "<tr>" + "".join(f"<td>{resaltar(c, ['14,77', '21,18', '13,10–16,87', '16,61–26,79'])}</td>" for c in cs) + "</tr>"
cal = next(l for l in (EV / "modelo/calibracion_condicional.md").read_text(encoding="utf-8").splitlines() if "77,82" in l)
cal = cal.lstrip("- ").split(" La peor")[0]
res = next(l for l in (EV / "modelo/resumen_modelo.md").read_text(encoding="utf-8").splitlines() if "Poisson" in l)
res = re.sub(r"[`*]", "", res).strip()
pagina("modelo.html", "Evidencia del modelo", f"""
<p class="eti">Evidencia · modelo de demanda</p><h1>El modelo frente a la regla manual</h1>
<div class="tarjeta"><p class="ruta"><b>api_frecuencias/docs/evidencias/modelo/evaluacion_modelo.md</b> · Prueba reservada 2025-11-01 a 2025-12-31</p>
<table><thead><tr>{th}</tr></thead><tbody>{tr}</tbody></table></div>
<div class="tarjeta"><p class="ruta"><b>api_frecuencias/docs/evidencias/modelo/calibracion_condicional.md</b> · banda P10–P90</p>
<p class="cita">{resaltar(cal, ['77,82 %'])}</p></div>
<div class="tarjeta"><p class="ruta"><b>api_frecuencias/docs/evidencias/modelo/resumen_modelo.md</b></p>
<p class="cita">{resaltar(res, ['pérdida Poisson'])}</p></div>""")

# --- Ciclo de §14.2 desde el registro de la demostración ------------------------------------------------------------
log = (EV / "despliegue/demo_ciclo_api.txt").read_text(encoding="utf-8").splitlines()
# Las cifras que narra la escena 11; si el registro ya no las trae, la página no se genera
CIFRAS_CICLO = ("filas leídas 49623, válidas 49623", "filas leídas 51, válidas 51", "filas leídas 4641, válidas 4641",
                "filas leídas 0, válidas 0", "reentrenar True", "Candidato hgb_fv2_20250930_s42 registrado",
                "Misma ventana para los dos: 2025-12-01 .. 2025-12-14", "WAPE 14.108 %", "WAPE 13.982 %", "[NO cumple]",
                "RECHAZADO hgb_fv2_20250930_s42", "El activo hgb_fv2_20250831_s42 sigue.")
faltan = [c for c in CIFRAS_CICLO if not any(c in l for l in log)]
assert not faltan, f"demo_ciclo_api.txt no trae: {faltan}"
lineas = []
for l in log:
    if l.startswith("Estado: GET /health"):
        assert all(x in l for x in ("'estado': 'ok'", "'base_datos': 'ok'", "'version': '1.0.0'")), l[:120]
        l = "Estado: GET /health -> estado ok, base de datos ok, versión 1.0.0"
    e = html.escape(l)
    m = re.match(r"^\((\d)\) ", l)
    if m:
        e = f"<span class='paso' id='paso{m.group(1)}'>{e}</span>"
    for c in CIFRAS_CICLO:
        e = e.replace(html.escape(c), f"<mark>{html.escape(c)}</mark>")
    lineas.append(e)
pagina("ciclo.html", "Ciclo de la sección 14.2", f"""
<p class="eti">Evidencia · demostración de §14.2</p><h1>El ciclo completo, pasos 1 a 6</h1>
<div class="tarjeta"><p class="ruta"><b>api_frecuencias/docs/evidencias/despliegue/demo_ciclo_api.txt</b> · registro literal de la demostración en la pila creada desde cero (la línea de /health va resumida)</p>
<pre>{chr(10).join(lineas)}</pre></div>""")

# --- Ingeniería ------------------------------------------------------------------------------------------------------
# Suite completa (JUnit), puerta de SonarQube, k6 (consultas y un año de resultados), CI de GitHub y arranque limpio
ts = ET.parse(EV / "pruebas/suite_final.xml").getroot().find("testsuite")
qg = json.loads((EV / "sonarqube/quality_gate.json").read_text(encoding="utf-8"))
cond = {c["metricKey"]: c for c in qg["estado"]["conditions"]}
orden = ["coverage", "bugs", "vulnerabilities", "critical_violations", "blocker_violations", "duplicated_lines_density"]
sq = "\n".join(f"{html.escape(k):<26}{html.escape(cond[k]['actualValue']):>6}  <mark>{html.escape(cond[k]['status'])}</mark>"
               for k in orden if k in cond).replace("  94.3", "  <mark>94.3</mark>", 1)
k6c = json.loads((EV / "pruebas/k6_consultas.json").read_text(encoding="utf-8"))["metrics"]
k6v_todo = json.loads((EV / "pruebas/k6_volumen.json").read_text(encoding="utf-8"))
k6v, tot = k6v_todo["carga"]["metrics"], k6v_todo["carga"]["setup_data"]["totales"]


def k6_lineas(m):
    return (f"  http_req_duration <mark>p(95) = {m['http_req_duration']['p(95)']:.1f} ms</mark>\n"
            f"  http_req_failed <mark>{m['http_req_failed']['value'] * 100:.2f} %</mark> · vus_max {m['vus_max']['value']}")


k6 = (f"<b>k6_consultas.json</b> · consultas paginadas\n{k6_lineas(k6c)}\n"
      f"<b>k6_volumen.json</b> · un año de resultados ({tot['executions']} ejecuciones, {tot['alerts']:,} alertas)\n"
      f"{k6_lineas(k6v)}").replace(f"{tot['alerts']:,}", f"{tot['alerts']:,}".replace(",", "."))
ci = (EV / "pruebas/ci_github.txt").read_text(encoding="utf-8").splitlines()
ci_l = [ci[0].strip()] + [m.group(1) for m in (re.match(r"^- (.+?: success)\b", l) for l in ci) if m]
arr = (EV / "despliegue/arranque_limpio.txt").read_text(encoding="utf-8").splitlines()
vol = re.search(r"volúmenes [^.]*\(nuevos\)", "\n".join(arr[:3])).group(0)
arr_l = [l.strip() for l in arr if l.strip().startswith("[OK]")] + [next(l.strip() for l in arr if l.startswith("Resultado global"))]
ci_html = resaltar("\n".join(ci_l[:1] + ["· " + x for x in ci_l[1:]]), ["en verde en GitHub Actions", "success"])
arr_html = resaltar("\n".join(arr_l), ["Resultado global: OK", "[OK]"])
pagina("ingenieria.html", "Evidencia de ingeniería", f"""
<style>main {{ padding-top: 22px; }} h1 {{ margin-bottom: 16px; }} pre.chico {{ font-size: 16px; }} .rejilla .tarjeta .cifra {{ font-size: 50px; }}</style>
<p class="eti">Evidencia · ingeniería de software</p><h1>Pruebas, calidad, rendimiento y despliegue</h1>
<div class="rejilla">
<div class="tarjeta"><p class="ruta"><b>docs/evidencias/pruebas/suite_final.xml</b> · suite completa</p>
<p class="cifra">{int(ts.get('tests')):,} casos</p><p class="nota">fallas <mark>{ts.get('failures')}</mark> · errores {ts.get('errors')} · omitidos {ts.get('skipped')}</p>
<pre class="chico">tests="{ts.get('tests')}" failures="{ts.get('failures')}" errors="{ts.get('errors')}" skipped="{ts.get('skipped')}"</pre></div>
<div class="tarjeta"><p class="ruta"><b>docs/evidencias/sonarqube/quality_gate.json</b> · {html.escape(qg['servidor'].split(' (')[0])}</p>
<p class="cifra">Puerta {html.escape(qg['estado']['status'])}</p><p class="nota">«{html.escape(qg['puerta'])}» · último análisis {html.escape(qg['ultimo_analisis']['date'][:10])}</p>
<pre class="chico">{sq}</pre></div>
<div class="tarjeta"><p class="ruta"><b>docs/evidencias/pruebas/</b> · k6</p>
<pre class="chico">{k6}</pre></div>
<div class="tarjeta"><p class="ruta"><b>docs/evidencias/pruebas/ci_github.txt</b> y <b>docs/evidencias/despliegue/arranque_limpio.txt</b></p>
<pre class="chico">{ci_html}

{html.escape(vol)}
{arr_html}</pre></div>
</div>""".replace("1,060 casos", "1.060 casos"))

# --- Cierre ----------------------------------------------------------------------------------------------------------
pagina("cierre.html", "Plan de implementación", """
<p class="eti">Sobusa Despacho · Data Challenge 2026 · Universidad del Norte</p><h1>El siguiente paso: un plan en tres fases</h1>
<div class="fases">
<div class="tarjeta fase"><span class="num">FASE 1 · 4 SEMANAS</span><h2>Conexión</h2><p>Réplica de lectura de la base de Extreme, con el usuario de solo lectura y el de escritura en el esquema propio.</p></div>
<div class="tarjeta fase"><span class="num">FASE 2 · 4 SEMANAS</span><h2>Modo sombra</h2><p>Nadie despacha con el sistema: se miden el error y las alertas con criterios claros para seguir.</p></div>
<div class="tarjeta fase"><span class="num">FASE 3 · 8 SEMANAS</span><h2>Piloto</h2><p>CRA 54 y CL 72, con días sorteados y el despachador al mando.</p></div>
</div>
<div class="tarjeta" style="margin-top:20px"><p class="cita">Pregunta del reto (§20): con los datos históricos y recientes, ¿cada cuánto despachar buses para optimizar la flota y el recaudo? ¿Cuántos pasajeros y vehículos se esperan, y qué situaciones requieren atención inmediata?</p></div>
""")
print("visores:", ", ".join(p.name for p in OUT.iterdir()))
