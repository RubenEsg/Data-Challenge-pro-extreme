"""E2E del tablero completo (las once pantallas) con Edge sin interfaz, contra la API de desarrollo.

Uso: python e2e_tablero_completo.py PUERTO_ANALISTA PUERTO_OPERADOR PUERTO_CLAVE_INVALIDA PUERTO_API CARPETA_EVIDENCIA
(el tablero principal usa la clave de analista, la que pide POST /respuesta/calcular).
- Cada pantalla: carga, h1, 0 errores de consola, sin desborde a 1600 px, contraste, teclado (Tab con foco visible en
  las once), captura 1600×900 (dash_<pantalla>.png) y la página completa (dash_<pantalla>_completa.png).
- Pronóstico: la sección «Modelo activo (API)» frente a GET /api/v1/predictions (ventanas del día, modelo, calibración,
  paginación, la banda P10–P90 frente a lo real, las variables SHAP del pronóstico elegido y la exportación) y el
  laboratorio del informe rotulado aparte.
- El modelo: primero el modelo del producto (sus cifras = evidencias de evaluación y calibración; su importancia =
  GET /models/{id}/importance), después los experimentos del informe en su sección.
- Alertas: la bandeja en orden de prioridad igual a GET /alerts?orden=prioridad, el chip «Escalada» cuando la bitácora
  tiene «escalar», y los campos de §5.3 del detalle frente a GET /api/v1/alerts/{id}.
- Recomendaciones: escenario viable y no viable (función objetivo con la fuente de cada peso, restricciones con holgura,
  tipologías, RF-008, motivo y mejor aproximación) y el plan del día frente a GET /recommendations/plan.
- Monitoreo: WAPE, MAE, sesgo y cobertura frente a GET /monitoring; PSI por variable; política y sombra.
- Inicio: la tarjeta «Respuesta a la pregunta del reto» frente a GET /api/v1/respuesta. Antes se crea una versión nueva
  de los umbrales con los mismos valores (PUT /thresholds): la foto de la respuesta queda vieja, GET /respuesta responde
  404 «sin_calcular» y la tarjeta muestra «Calculando…», pide POST /respuesta/calcular y vuelve a consultar cada 3 s.
- Despacho dice que es la repetición de un día de 2025 y que no despacha; Operación › «Salud del servicio» se captura.
- Autenticación: con clave de operador (403 al calcular) y con una clave inválida (401) las pantallas lo dicen, sin
  trazas ni errores de consola.

Las claves de prueba (operador, analista, admin) se leen de claves.json junto a este archivo; ese archivo se crea solo
para la corrida y nunca se versiona. Requiere Playwright y Microsoft Edge."""
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import TimeoutError as TiempoAgotado
from playwright.sync_api import sync_playwright

ADMIN, OPER, MALA, API = (int(x) for x in sys.argv[1:5])
OUT = Path(sys.argv[5])
OUT.mkdir(parents=True, exist_ok=True)
AQUI = Path(__file__).resolve().parent
CLAVES = json.loads((AQUI / "claves.json").read_text(encoding="utf-8"))
EVAL = json.loads((AQUI.parent / "modelo" / "evaluacion_modelo.json").read_text(encoding="utf-8"))
CALIB = json.loads((AQUI.parent / "modelo" / "calibracion_condicional.json").read_text(encoding="utf-8"))
NIVEL_RANGO = {"Crítica": 0, "Preventiva": 1, "Informativa": 2}
SEV_RANGO = {"critica": 0, "preventiva": 1, "informativa": 2}
res = {"inicio": time.strftime("%Y-%m-%d %H:%M:%S"), "pruebas": [], "teclado": {}, "contraste": {},
       "errores_consola": {}}
fallas = []
LINEAS = []


def ok(nombre, cond, detalle=""):
    res["pruebas"].append({"prueba": nombre, "ok": bool(cond), "detalle": str(detalle)[:400]})
    if not cond:
        fallas.append(nombre)
    linea = ("OK    " if cond else "FALLA ") + f"{nombre} · {str(detalle)[:220]}".replace("\n", " | ")
    LINEAS.append(linea)
    print(linea, flush=True)


def api(ruta, rol="admin", metodo="GET", cuerpo=None):
    datos = None if cuerpo is None else json.dumps(cuerpo).encode("utf-8")
    req = urllib.request.Request(f"http://127.0.0.1:{API}/api/v1/{ruta}", data=datos, method=metodo,
                                 headers={"X-API-Key": CLAVES[rol], "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:  # noqa: S310 - URL fija http://127.0.0.1 de la API local
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"null")


def q(texto):
    return urllib.request.quote(texto)


def es(x, d=1):
    """Número en es-CO como lo escribe el tablero: 14,77 · 1.234."""
    return f"{x:,.{d}f}".replace(",", "#").replace(".", ",").replace("#", ".")


def esperar_respuesta(pg, ruta, limite=90):
    """Espera a que la tarjeta de Inicio muestre la respuesta de esa ruta (puede pasar por «Calculando…»).
    Devuelve (texto, vio_calculando)."""
    vio = False
    fin = time.time() + limite
    t = ""
    while time.time() < fin:
        t = pg.locator("#in-resp-cuerpo").inner_text() if pg.locator("#in-resp-cuerpo").count() else ""
        vio = vio or "Calculando" in t
        if "La pregunta" in t and re.search(rf"Ruta:\s*{re.escape(ruta)}", t):
            return t, vio
        if "Calculando" not in t and ("todavía no está calculada" in t or "tarda más" in t or "no responde" in t):
            return t, vio
        pg.wait_for_timeout(250)
    return t, vio


def esperar(pg, extra=900):
    pg.wait_for_function("() => !document.querySelector('[data-dash-is-loading=\"true\"]')", timeout=90000)
    pg.wait_for_timeout(extra)


def abrir(pg, base, ruta, extra=1500):
    for intento in range(2):   # con la máquina cargada, una primera carga lenta se repite una vez
        pg.goto(base + ruta, wait_until="networkidle")
        try:
            pg.wait_for_selector("#contenido h1", timeout=60000)
            break
        except TiempoAgotado:
            if intento:
                raise
            LINEAS.append(f"AVISO {ruta}: la pantalla tardó más de 60 s en mostrar su título; se repite la carga")
    esperar(pg, extra)


def num_es(t):
    """«1.234,5» → 1234.5"""
    return float(t.replace(".", "").replace(",", ".").replace("−", "-").replace("+", "").replace("%", "").strip())


DESBORDE = "() => [document.documentElement.scrollWidth, document.documentElement.clientWidth]"
FOCO = r"""() => {
  const el = document.activeElement; if (!el || el === document.body) return null;
  const cs = getComputedStyle(el); const r = el.getBoundingClientRect();
  const marca = e => { const c = getComputedStyle(e);
                       return c.outlineStyle !== 'none' && parseFloat(c.outlineWidth) > 0; };
  // El contorno puede ir en el envoltorio (los campos y el selector de fecha lo dibujan con :focus-within)
  let visible = false;
  for (let e = el, i = 0; e && i < 4; e = e.parentElement, i++) { if (marca(e)) { visible = true; break; } }
  let nombre = (el.getAttribute('aria-label') || el.innerText || el.value || el.id || el.tagName).trim().slice(0, 40);
  return {tag: el.tagName.toLowerCase(), nombre, visible, x: Math.round(r.x), y: Math.round(r.y + window.scrollY)};
}"""
CONTRASTE = r"""() => {
  const lum = c => { const v = c.map(x => { x /= 255;
                                            return x <= 0.03928 ? x / 12.92 : Math.pow((x + 0.055) / 1.055, 2.4); });
                     return 0.2126 * v[0] + 0.7152 * v[1] + 0.0722 * v[2]; };
  const rgb = s => { const m = s.match(/rgba?\(([^)]+)\)/); if (!m) return null;
                     const p = m[1].split(/[ ,\/]+/).filter(Boolean).map(Number);
                     return [p[0], p[1], p[2], p.length > 3 ? p[3] : 1]; };
  const fondo = el => { for (let e = el; e; e = e.parentElement) { const c = rgb(getComputedStyle(e).backgroundColor);
                          if (c && c[3] > 0.5) return c; } return [239, 239, 239, 1]; };
  const malos = []; let n = 0, minimo = 99;
  for (const el of document.querySelectorAll('#contenido *')) {
    if (el.closest('svg, .js-plotly-plot, .insight')) continue;
    if (!Array.from(el.childNodes).some(x => x.nodeType === 3 && x.textContent.trim())) continue;
    const cs = getComputedStyle(el);
    if (cs.visibility === 'hidden' || cs.display === 'none' || !el.getClientRects().length) continue;
    if (el.closest('[disabled], .boton[disabled]')) continue;
    const c = rgb(cs.color), f = fondo(el); if (!c) continue;
    const a = lum(c), b = lum(f); const r = (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
    const grande = parseFloat(cs.fontSize) >= 24
                   || (parseFloat(cs.fontSize) >= 18.66 && parseInt(cs.fontWeight) >= 600);
    n++; minimo = Math.min(minimo, r);
    const clase = (el.className || '').toString().split(' ')[0];
    if (r < (grande ? 3 : 4.5))
      malos.push(`${el.tagName.toLowerCase()}.${clase} «${el.textContent.trim().slice(0, 30)}» ${r.toFixed(2)}`);
  }
  return {textos: n, minimo: Math.round(minimo * 100) / 100, malos: malos.slice(0, 8), n_malos: malos.length};
}"""

PANTALLAS = [("inicio", "/"), ("pronostico", "/pronostico"), ("horario", "/horario"), ("despacho", "/despacho"),
             ("alertas", "/alertas"), ("recomendaciones", "/recomendaciones"), ("operacion", "/operacion"),
             ("monitoreo", "/monitoreo"), ("modelo", "/modelo"), ("resultado", "/resultado"), ("anexos", "/anexos")]


def teclado(pg, nombre, pasos=32):
    pg.evaluate("() => { window.scrollTo(0, 0); if (document.activeElement) document.activeElement.blur(); }")
    vistos = []
    for _ in range(pasos):
        pg.keyboard.press("Tab")
        pg.wait_for_timeout(60)
        f = pg.evaluate(FOCO)
        if f:
            vistos.append(f)
    sin_foco = [v for v in vistos if not v["visible"]]
    res["teclado"][nombre] = vistos
    ok(f"{nombre}: Tab recorre {len(vistos)} elementos con foco visible", vistos and not sin_foco,
       "barra (" + str(sum(1 for v in vistos if v["y"] < 80)) + " enlaces) → contenido: " +
       " → ".join(f"{v['tag']}:{v['nombre']}" for v in vistos if v["y"] >= 80)[:900]
       + (f" · SIN FOCO VISIBLE: {sin_foco[:3]}" if sin_foco else ""))


with sync_playwright() as p:
    nav = p.chromium.launch(channel="msedge", headless=True)
    ctx = nav.new_context(viewport={"width": 1600, "height": 900}, device_scale_factor=1, accept_downloads=True)
    pg = ctx.new_page()
    errores = []
    pg.on("console", lambda m: errores.append(f"{m.type}: {m.text[:200]}") if m.type == "error" else None)
    pg.on("pageerror", lambda e: errores.append(f"pageerror: {e}"))
    B = f"http://127.0.0.1:{ADMIN}"

    # --- 1. Las once pantallas: carga, consola, desborde, capturas ------------------------------------------------
    for nombre, ruta in PANTALLAS:
        errores.clear()
        abrir(pg, B, ruta, 2500 if nombre in ("inicio", "despacho", "horario") else 1800)
        if nombre == "operacion":
            pg.wait_for_timeout(500)
        h1 = pg.locator("#contenido h1").first.inner_text()
        w = pg.evaluate(DESBORDE)
        pg.screenshot(path=str(OUT / f"dash_{nombre}.png"))
        pg.screenshot(path=str(OUT / f"dash_{nombre}_completa.png"), full_page=True)
        if nombre == "despacho" and errores and all("Style is not done loading" in e for e in errores):
            # Carrera conocida de MapLibre en la primera carga en frío (el estilo de CARTO aún no llega): se anota y
            # se repite
            LINEAS.append(f"AVISO despacho: en la primera carga en frío MapLibre avisó {errores} (estilo del mapa "
                          "aún sin cargar); se repite la carga")
            res.setdefault("avisos", []).append({"despacho_primera_carga": list(errores)})
            errores.clear()
            abrir(pg, B, ruta, 4000)
            h1 = pg.locator("#contenido h1").first.inner_text()
        ok(f"{nombre}: carga con su título y sin errores de consola", h1 and not errores,
           f"h1 «{h1}» · errores {errores}")
        ok(f"{nombre}: sin desplazamiento horizontal a 1600 px", w[0] <= w[1] + 1, w)
        res["errores_consola"][nombre] = list(errores)
        c = pg.evaluate(CONTRASTE)
        res["contraste"][nombre] = c
        ok(f"{nombre}: contraste del texto visible (WCAG AA)", c["n_malos"] == 0,
           f"{c['textos']} textos · mínimo {c['minimo']}:1 · {c['malos']}")
        if nombre == "despacho":
            sub = pg.locator(".desp-titulos").inner_text()
            ok("despacho: el subtítulo dice que es la repetición de un día de 2025 y que no despacha (§3.2)",
               "Repetición de un día de 2025" in sub and "no despacha" in sub, sub[:160])
        teclado(pg, nombre)   # RNF-012: Tab con foco visible en las once pantallas

    # --- 2. Alertas: los campos nuevos de §5.3 ----------------------------------------------------------------------
    errores.clear()
    abrir(pg, B, "/alertas", 2500)
    _s, lista = api("alerts?estado=nueva&limite=20&orden=prioridad")
    filas_al = pg.locator("#al-lista tbody tr").all_inner_texts()
    niveles = [next((n for n in NIVEL_RANGO if n in f), "?") for f in filas_al]
    ok("alertas: la bandeja va en orden de prioridad (crítica → preventiva → informativa)",
       niveles and [NIVEL_RANGO.get(n, 9) for n in niveles] == sorted(NIVEL_RANGO.get(n, 9) for n in niveles),
       " · ".join(niveles))
    ok("alertas: el orden de la bandeja = GET /alerts?orden=prioridad",
       [SEV_RANGO[a["severidad"]] for a in lista["items"]] == [NIVEL_RANGO.get(n, 9) for n in niveles]
       and all(a["codigo"] in f for a, f in zip(lista["items"], filas_al, strict=False)),
       f"{len(filas_al)} filas · API {[a['codigo'] for a in lista['items'][:5]]}")
    escaladas = 0
    for a in lista["items"]:
        if (a.get("ocurrencias") or 0) > 1:
            _s, hist = api(f"alerts/{a['alert_id']}/history")
            escaladas += any(h.get("accion") == "escalar" for h in hist or [])
    chips_esc = pg.locator("#al-lista .chip", has_text="Escalada").count()
    ok("alertas: el chip «Escalada» marca las alertas con «escalar» en su bitácora", chips_esc == escaladas,
       f"{chips_esc} chips · {escaladas} escaladas en la API")
    primera = lista["items"][0]
    _s, a = api(f"alerts/{primera['alert_id']}")
    txt = pg.locator("#al-campos").inner_text()
    for rotulo in ("Origen", "Tendencia", "Pendiente", "Serie reciente", "Probabilidad", "Método del puntaje",
                   "Variables influyentes", "Ubicación"):
        ok(f"alertas: el detalle muestra «{rotulo}»", rotulo in txt, a["codigo"])
    pend = a.get("tendencia_pendiente")
    ok("alertas: la pendiente coincide con la API", pend is None or f"{abs(pend) * 100:.1f}".replace(".", ",") in txt,
       f"API {pend}")
    shap = [v for v in a.get("variables_influyentes") or []
            if v.get("fuente") != "regla" and v.get("efecto_pasajeros") is not None]
    if shap:
        top = max(shap, key=lambda v: abs(v["efecto_pasajeros"]))
        fila1 = pg.locator("#al-campos table").filter(has_text="Efecto").locator("tbody tr").first.inner_text()
        ok("alertas: la variable más influyente va primero (|efecto SHAP| mayor)",
           (top.get("descripcion") or top["variable"]) in fila1,
           f"API {top['variable']} {top['efecto_pasajeros']} · fila {fila1[:80]}")
    ok("alertas: la serie reciente se dibuja", pg.locator("#al-campos .js-plotly-plot").count() >= 1,
       a.get("serie_reciente", [])[:2])
    # Una alerta observada (ALT-005..ALT-008) si existe, para la serie observado/esperado
    _s, obs = api("alerts?codigo=ALT-007&limite=1")
    if obs and obs.get("items"):
        ok("alertas: hay alertas observadas en la API", True, obs["items"][0]["codigo"])
    pg.locator(".al-fila, .api-fila").nth(1).click()
    esperar(pg, 1500)
    pg.evaluate("() => { const h = Array.from(document.querySelectorAll('#al-campos h4'))"
                ".find(x => x.textContent.trim() === 'Evidencia');"
                " (h || document.querySelector('#al-campos')).scrollIntoView({block: 'start'});"
                " window.scrollBy(0, -96); }")
    pg.wait_for_timeout(400)
    pg.screenshot(path=str(OUT / "dash_alertas_detalle.png"))
    ok("alertas: 0 errores de consola en el detalle", not errores, errores)

    # --- 3. Recomendaciones: escenario viable, no viable y plan D5 --------------------------------------------------
    errores.clear()
    abrir(pg, B, "/recomendaciones", 3500)
    plan_txt = pg.locator("#re-plan-cifras").inner_text()
    fecha = pg.locator("#re-plan-fecha input").input_value() if pg.locator("#re-plan-fecha input").count() else ""
    _s, r_ej = api("frequency/executions?tipo=frecuencia&estado=ok&limite=1&orden=-creado_en")
    _s, recs = api(f"recommendations?execution_id={r_ej['items'][0]['execution_id']}&ruta=SILENCIO&limite=1")
    dia = recs["items"][0]["fecha"]
    _s, plan = api(f"recommendations/plan?ruta=SILENCIO&fecha={dia}&pronostico=activo")
    ok("recomendaciones: salidas del día del plan (modelo activo, persistido por el ciclo) = API",
       f"{plan['salidas_dia']:,}".replace(",", ".") in plan_txt, f"API {plan['salidas_dia']} · {plan_txt[:120]}")
    vh = plan.get("vehiculos_hora_pico")
    ok("recomendaciones: vehículos en la hora pico = API", (str(vh) if vh is not None else "—") in plan_txt, vh)
    filas_plan = pg.locator("#re-plan-tabla tbody tr").count()
    ok("recomendaciones: una fila por hora del plan", filas_plan == len(plan["horas"]),
       f"{filas_plan} filas · API {len(plan['horas'])} horas")
    pg.evaluate("() => { document.querySelector('#re-plan-cifras').scrollIntoView({block: 'start'});"
                " window.scrollBy(0, -160); }")
    pg.wait_for_timeout(500)
    pg.screenshot(path=str(OUT / "dash_recomendaciones_plan.png"))
    # Escenario no viable (el que se prellena: la hora pico vigente)
    pg.locator("#re-calcular").click()
    esperar(pg, 2500)
    t = pg.locator("#re-escenario").inner_text()
    ok("recomendaciones: escenario calculado con la clave de analista o superior", "Función objetivo" in t, t[:120])
    if "no es viable" in t:
        ok("recomendaciones: inviable con su motivo y la mejor aproximación (§18)", "Mejor aproximación" in t, t[:200])
        pg.evaluate("() => { document.querySelector('#re-escenario').scrollIntoView({block: 'start'});"
                    " window.scrollBy(0, -96); }")
        pg.wait_for_timeout(400)
        pg.screenshot(path=str(OUT / "dash_recomendaciones_no_viable.png"))
    # Escenario viable: demanda moderada en una hora del valle, con pesos y nivel de servicio
    pg.locator("#re-e-hora").fill("10")
    pg.locator("#re-e-demanda").fill("300")
    pg.locator("#re-e-p90").fill("360")
    pg.locator("#re-e-servicio").fill("90")
    pg.locator("#re-calcular").click()
    esperar(pg, 3000)
    t = pg.locator("#re-escenario").inner_text()
    for rotulo in ("Función objetivo (§10.2)", "α · Costo operativo", "β · Tiempo de espera", "γ · Sobreocupación",
                   "δ · Desviación de la frecuencia", "peso: ", "Total ponderado",
                   "Restricciones y límites que mandan", "Holgura", "Límites que mandan",
                   "Mezcla de tipologías (§10.1)", "Actual frente a recomendada (RF-008)",
                   "Cumple el nivel de servicio"):
        ok(f"recomendaciones: el escenario muestra «{rotulo}»", rotulo in t, "")
    ok("recomendaciones: el escenario viable no muestra el aviso de inviable",
       "no es viable" not in t.split("Función objetivo")[0], t[:160])
    # Pesos: α = 2 desde la solicitud → la fuente del peso cambia
    pg.locator("#re-escenario").scroll_into_view_if_needed()
    pg.evaluate("() => { const t = Array.from(document.querySelectorAll('#re-escenario h3'))"
                ".find(x => x.textContent.startsWith('Función'));"
                " (t || document.querySelector('#re-escenario')).scrollIntoView({block: 'start'});"
                " window.scrollBy(0, -110); }")
    pg.wait_for_timeout(400)
    pg.screenshot(path=str(OUT / "dash_recomendaciones_escenario.png"))
    pg.locator("summary", has_text="Pesos de la función objetivo").click()
    pg.locator("#re-e-alfa").fill("2")
    pg.locator("#re-calcular").click()
    esperar(pg, 3000)
    t2 = pg.locator("#re-escenario").inner_text()
    ok("recomendaciones: un peso de la solicitud se muestra con su fuente", "2,00" in t2 and "solicitud" in t2.lower(),
       [x for x in t2.split("\n") if "peso:" in x][:4])
    ok("recomendaciones: 0 errores de consola", not errores, errores)

    # --- 4. Monitoreo -----------------------------------------------------------------------------------------------
    errores.clear()
    abrir(pg, B, "/monitoreo", 3500)
    _s, mon = api("monitoring?limite=10&orden=-creado_en")
    m = next(x for x in mon["items"] if x["rol"] == "activo")
    cif = pg.locator("#mo-cifras").inner_text()
    ok("monitoreo: WAPE móvil = API", f"{m['wape_movil'] * 100:.1f}".replace(".", ",") in cif, m["wape_movil"])
    ok("monitoreo: MAE móvil = API", f"{m['mae_movil']:.1f}".replace(".", ",") in cif, m["mae_movil"])
    ok("monitoreo: cobertura P10–P90 = API", f"{m['cobertura_p10_p90'] * 100:.1f}".replace(".", ",") in cif,
       m["cobertura_p10_p90"])
    ok("monitoreo: sesgo = API", f"{abs(m['sesgo_pct']) * 100:.2f}".replace(".", ",") in cif, m["sesgo_pct"])
    psi_filas = pg.locator("#mo-psi tbody tr").count()
    ok("monitoreo: una fila de PSI por variable de la API", psi_filas == len(m["psi"]),
       f"{psi_filas} · API {len(m['psi'])}")
    estados = pg.locator("#mo-psi tbody .chip").all_inner_texts()
    ok("monitoreo: el estado de cada variable va con icono y palabra", all(e.strip() for e in estados) and
       pg.locator("#mo-psi tbody .chip .glifo").count() == len(estados), estados[:3])
    _s, pol = api("monitoring/policy")
    tp = pg.locator("#mo-politica").inner_text()
    ok("monitoreo: decisión de reentrenar = API", ("Reentrenar ahora" in tp) == bool(pol["decision"]["reentrenar"]),
       pol["decision"]["reentrenar"])
    ts = pg.locator("#mo-sombra").inner_text()
    ok("monitoreo: retador en sombra = API", all(c["model_id"] in ts for c in pol["en_sombra"]),
       [c["model_id"] for c in pol["en_sombra"]])
    ok("monitoreo: los cuatro criterios de la compuerta",
       ts.count("WAPE") >= 2 and "sesgo" in ts and "Cobertura" in ts, "")
    pg.locator("#mo-actualizar").click()
    esperar(pg, 1500)
    ok("monitoreo: «Actualizar» recarga sin errores", not errores, errores)
    for boton, ext in (("#mo-csv", ".csv"), ("#mo-xlsx", ".xlsx")):
        with pg.expect_download(timeout=30000) as d:
            pg.locator(boton).click()
        nombre = d.value.suggested_filename
        destino = OUT / f"export_monitoreo_dash{ext}"
        d.value.save_as(str(destino))
        ok(f"monitoreo: exporta {ext[1:].upper()} (GET /monitoring/export)",
           nombre.endswith(ext) and destino.stat().st_size > 0, f"{nombre} · {destino.stat().st_size} bytes")
    pg.evaluate("() => document.querySelector('#mo-politica').scrollIntoView({block: 'center'})")
    pg.wait_for_timeout(300)
    pg.screenshot(path=str(OUT / "dash_monitoreo_politica.png"))

    # --- 4b. Pronóstico: «Modelo activo (API)» frente a GET /predictions y el laboratorio rotulado aparte ---------
    errores.clear()
    abrir(pg, B, "/pronostico", 3500)
    ruta_p = "CRA 54"
    _s, ult = api(f"predictions?ruta={q(ruta_p)}&horizonte_min=60&limite=1&orden=-fecha")
    dia_p = ult["items"][0]["fecha"]
    _s, todo = api(f"predictions?ruta={q(ruta_p)}&desde={dia_p}&hasta={dia_p}&horizonte_min=60&limite=500"
                   "&orden=instante")
    ventanas = sorted({p["instante"] for p in todo["items"]})
    cif = pg.locator("#pr-api-cifras").inner_text()
    calib = sorted({str((p.get("variables") or {}).get("calibracion_version")) for p in todo["items"]})
    ok("pronóstico API: el modelo y la versión de la calibración = GET /predictions",
       all(p["model_id"] in cif for p in todo["items"]) and all(f"Calibración {c}" in cif for c in calib),
       f"{sorted({p['model_id'] for p in todo['items']})} · calibración {calib}")
    filas_banda = pg.locator("#pr-api-banda-tabla tbody tr").count()
    ok("pronóstico API: una ventana por instante del día en la banda = API", filas_banda == len(ventanas),
       f"{filas_banda} ventanas · API {len(ventanas)} instantes el {dia_p}")
    trazas = pg.locator("#pr-api-banda .scatterlayer .trace").count()
    leyenda_b = pg.locator("#pr-api-banda-leyenda .leyenda__item").all_inner_texts()
    ok("pronóstico API: la banda P10–P90, el P50 y lo real se dibujan",
       trazas >= 3 and any("Banda P10–P90" in x for x in leyenda_b) and any("Real" in x for x in leyenda_b),
       f"{trazas} trazas · leyenda {leyenda_b}")
    pag = pg.locator("#pr-api-paginas").inner_text()
    ok("pronóstico API: la paginación cuenta los pronósticos de la API", f"{todo['total']} pronósticos" in pag, pag)
    primera_fila = pg.locator("#pr-api-lista tbody tr").first.inner_text()
    pg.locator("#pr-api-sig").click()
    esperar(pg, 1200)
    pag2 = pg.locator("#pr-api-paginas").inner_text()
    ok("pronóstico API: «Siguiente» trae la página 2 (limite y desplazamiento de la API)",
       pag2.startswith("Página 2") and pg.locator("#pr-api-lista tbody tr").first.inner_text() != primera_fila, pag2)
    pg.locator("#pr-api-ant").click()
    esperar(pg, 1200)
    boton = pg.locator("#pr-api-lista .api-fila").nth(2)
    pid = json.loads(boton.get_attribute("id"))["id"]
    boton.click()
    esperar(pg, 1500)
    _s, pr = api(f"predictions/{pid}")
    det = pg.locator("#pr-api-detalle").inner_text()
    fac = ((pr.get("explicacion_local") or {}).get("factores") or [{}])[0]
    desc = (fac.get("descripcion") or "")
    ok("pronóstico API: el detalle del pronóstico elegido trae su variable SHAP principal y su efecto",
       desc[:1].upper() + desc[1:] in det and es(fac.get("efecto_pasajeros") or 0, 1).lstrip("-") in det,
       f"{fac.get('variable')} {fac.get('efecto_pasajeros')} · banda {pr.get('p10')}–{pr.get('p90')}")
    ok("pronóstico API: la banda del elegido = API", f"{round(pr['p10']):,}".replace(",", ".") in det
       and f"{round(pr['p90']):,}".replace(",", ".") in det, (pr["p10"], pr["p90"]))
    pg.evaluate("() => { document.querySelector('#pr-api').scrollIntoView({block: 'start'});"
                " window.scrollBy(0, -80); }")
    pg.wait_for_timeout(500)
    pg.screenshot(path=str(OUT / "dash_pronostico_api.png"))
    for boton_x, ext in (("#pr-api-csv", ".csv"), ("#pr-api-xlsx", ".xlsx")):
        with pg.expect_download(timeout=30000) as d:
            pg.locator(boton_x).click()
        nombre = d.value.suggested_filename
        destino = OUT / f"export_predicciones_dash{ext}"
        d.value.save_as(str(destino))
        ok(f"pronóstico API: exporta {ext[1:].upper()} (GET /predictions/export)",
           nombre.endswith(ext) and destino.stat().st_size > 0, f"{nombre} · {destino.stat().st_size} bytes")
    lab = pg.locator("#pr-laboratorio").inner_text()
    todo_txt = pg.locator("#contenido").inner_text()
    ok("pronóstico: el laboratorio va rotulado «experimento 11 / experimento 12» y dice que no es el modelo de la API",
       "Laboratorio del informe académico" in lab and "No es el modelo de la API" in lab, lab[:120])
    ok("pronóstico: no se nombra «modelo final» ni «E11/E12» a secas",
       not re.search(r"modelo final|\bE1[12]\b|Híbrido \(E12\)", todo_txt), "")
    ok("pronóstico: 0 errores de consola", not errores, errores)

    # --- 4c. El modelo: primero el del producto, después los experimentos del informe ---------------------------
    errores.clear()
    abrir(pg, B, "/modelo", 3000)
    prod = pg.locator("#mo-producto").inner_text()
    g = EVAL["prueba_reservada"]["global"]
    cob = CALIB["resultados"]["prueba"]["v2"]["global"]["cobertura_pct"]
    activo = EVAL["prueba_reservada"]["modelos"]["activo"]
    ok("modelo: la primera tarjeta es el modelo del producto con sus cifras de evaluación y calibración",
       activo in prod and es(g["cand"]["wape"], 2) in prod and es(g["b1"]["wape"], 2) in prod and es(cob, 2) in prod,
       f"{activo} · {g['cand']['wape']} frente a {g['b1']['wape']} · cobertura {cob}")
    h2 = pg.locator("#contenido h2.seccion__titulo").all_inner_texts()
    ok("modelo: el producto va primero y los experimentos del informe en su sección rotulada",
       h2[:1] == ["El modelo del producto"] and any("Laboratorio del informe académico" in x for x in h2), h2)
    ok("modelo: declara el uso honesto de la prueba de nov–dic 2025", "reporte informativo" in prod, "")
    _s, imp = api(f"models/{activo}/importance")
    shap = sorted((imp.get("shap") or {}).get("media_abs_shap_log") or [], key=lambda x: -x["media_abs"])
    if shap:
        total = sum(x["media_abs"] for x in shap)
        txt_imp = pg.locator("#mo-producto-imp").inner_text()
        ok("modelo: la importancia del modelo activo = GET /models/{id}/importance (media de |SHAP|)",
           es(shap[0]["media_abs"] / total * 100, 1) in txt_imp, f"{shap[0]['variable']} {shap[0]['media_abs']}")
    ok("modelo: 0 errores de consola", not errores, errores)

    # --- 4d. Operación › «Salud del servicio» ------------------------------------------------------------------
    errores.clear()
    abrir(pg, B, "/operacion", 2500)
    pg.locator("#op-vista label", has_text="Salud del servicio").first.click()
    esperar(pg, 2500)
    salud_txt = pg.locator("#op-v-monitoreo").inner_text()
    ok("operación: la vista «Salud del servicio» muestra /health y /metrics", "Salud del servicio" in salud_txt
       and ("/health" in salud_txt or "health" in salud_txt.lower()), salud_txt[:160])
    pg.evaluate("() => { document.querySelector('#op-v-monitoreo').scrollIntoView({block: 'start'});"
                " window.scrollBy(0, -200); }")
    pg.wait_for_timeout(400)
    pg.screenshot(path=str(OUT / "dash_operacion_salud.png"))
    ok("operación: 0 errores de consola en «Salud del servicio»", not errores, errores)

    # --- 5. Inicio: la respuesta a la pregunta del reto (§7.1: «Calculando…», POST y consulta cada 3 s) -------
    errores.clear()
    # Una versión nueva de los umbrales con los mismos valores deja vieja la foto de la respuesta: GET /respuesta
    # responde 404 «sin_calcular» y la tarjeta tiene que pedir el cálculo (C7)
    _s, um = api("thresholds")
    st_put, _r = api("thresholds", "admin", "PUT", {
        "valores": {"ocupacion_objetivo_max": um["valores"]["ocupacion_objetivo_max"]},
        "motivo": "Recorrido del tablero: versión nueva con los mismos valores para probar el cálculo a pedido"})
    st0, r0 = api("respuesta?ruta=SILENCIO", "operador")
    ok("inicio: con umbrales nuevos la foto queda vieja y GET /respuesta responde 404 «sin_calcular»",
       st_put == 200 and st0 == 404 and (r0 or {}).get("error", {}).get("codigo") == "sin_calcular",
       f"PUT {st_put} · GET {st0} {(r0 or {}).get('error', {}).get('codigo')}")
    pg.goto(B + "/", wait_until="domcontentloaded")
    pg.wait_for_selector("#in-resp-cuerpo", timeout=30000)
    vio, inicio_t = False, time.time()
    while time.time() - inicio_t < 30 and not vio:
        vio = "Calculando" in pg.locator("#in-resp-cuerpo").inner_text()
        if vio:
            pg.evaluate("() => { document.querySelector('#inicio-respuesta').scrollIntoView({block: 'start'});"
                        " window.scrollBy(0, -96); }")
            pg.screenshot(path=str(OUT / "dash_inicio_calculando.png"))
        elif "La pregunta" in pg.locator("#in-resp-cuerpo").inner_text():
            break
        pg.wait_for_timeout(150)
    tr, vio2 = esperar_respuesta(pg, "SILENCIO")
    segundos = time.time() - inicio_t
    ok("inicio: la tarjeta muestra «Calculando…», pide el cálculo y consulta cada 3 s hasta tener la respuesta",
       (vio or vio2) and "La pregunta" in tr, f"«Calculando…» visto: {vio or vio2} · respuesta en {segundos:.1f} s")
    _s, ejs = api("frequency/executions?tipo=respuesta&limite=1&orden=-creado_en")
    ok("inicio: el cálculo pedido por el tablero es una ejecución «respuesta» de la cola",
       bool(ejs and ejs.get("items")) and ejs["items"][0]["estado"] == "ok",
       (ejs["items"][0]["execution_id"], ejs["items"][0]["estado"]) if ejs and ejs.get("items") else ejs)
    st, resp = api("respuesta?ruta=SILENCIO", "operador")
    if st == 200:
        r = resp["rutas"][0]
        ok("inicio: la tarjeta trae la pregunta literal de la especificación", resp["pregunta"][:60] in tr,
           resp["pregunta"][:80])
        ok("inicio: pasajeros esperados del día = API",
           f"{round(r['pasajeros_esperados']['dia']):,}".replace(",", ".") in tr, r["pasajeros_esperados"]["dia"])
        ok("inicio: vehículos en la hora pico = API", str(r["vehiculos"]["requeridos_pico"]) in tr, r["vehiculos"])
        traza = resp.get("trazabilidad") or {}
        ok("inicio: la trazabilidad nombra el modelo, la calibración y la fuente del pronóstico",
           traza.get("model_id", "?") in tr and "calibración de la banda" in tr and "plan con" in tr,
           [x for x in tr.split("\n") if x.startswith("Trazabilidad")][:1])
        ok("inicio: «Atención inmediata» dice que son las alertas abiertas ahora", "abiertas ahora" in tr, "")
        for ruta in ("CRA 54", "CL 72"):
            pg.locator("#in-resp-ruta label", has_text=ruta).first.click()
            t3, vio3 = esperar_respuesta(pg, ruta)
            _st, rr = api(f"respuesta?ruta={q(ruta)}", "operador")
            ok(f"inicio: la ruta {ruta} cambia la respuesta" + (" (pasó por «Calculando…»)" if vio3 else ""),
               _st == 200 and f"{round(rr['rutas'][0]['pasajeros_esperados']['dia']):,}".replace(",", ".") in t3,
               rr["rutas"][0]["pasajeros_esperados"]["dia"] if _st == 200 else _st)
        pg.locator("#in-resp-ruta label", has_text="SILENCIO").first.click()
        esperar_respuesta(pg, "SILENCIO")
        esperar(pg, 800)
    else:
        ok("inicio: sin el endpoint, la tarjeta lo dice con un aviso claro", "todavía no" in tr or "no responde" in tr,
           f"{st} · {tr[:160]}")
    pg.evaluate("() => { document.querySelector('#inicio-respuesta').scrollIntoView({block: 'start'});"
                " window.scrollBy(0, -96); }")
    pg.wait_for_timeout(400)
    pg.screenshot(path=str(OUT / "dash_inicio_respuesta.png"))
    mas = pg.locator("#inicio-respuesta .mas summary").first
    mas.click()
    pg.wait_for_timeout(500)
    filas = pg.locator("#in-resp-tabla tbody tr").count()
    ok("inicio: el «…» de la tarjeta trae la tabla hora por hora", filas > 0 or st != 200, f"{filas} filas")
    if st == 200:
        pg.keyboard.press("Escape")
        for boton, ext in (("#in-resp-csv", ".csv"), ("#in-resp-xlsx", ".xlsx")):
            with pg.expect_download(timeout=60000) as d:
                pg.locator(boton).click()
            nombre = d.value.suggested_filename
            destino = OUT / f"export_respuesta_dash{ext}"
            d.value.save_as(str(destino))
            ok(f"inicio: exporta la respuesta en {ext[1:].upper()} (GET /respuesta/export)",
               nombre.endswith(ext) and destino.stat().st_size > 0, f"{nombre} · {destino.stat().st_size} bytes")
    ok("inicio: 0 errores de consola", not errores, errores)
    ctx.close()

    # --- 6. Autenticación: operador (403 al calcular) y clave inválida (401) ------------------------------------------
    for puerto, rol in ((OPER, "operador"), (MALA, "invalida")):
        ctx = nav.new_context(viewport={"width": 1600, "height": 900})
        pg = ctx.new_page()
        errs = []
        pg.on("console", lambda m, errs=errs: errs.append(m.text[:200]) if m.type == "error" else None)
        pg.on("pageerror", lambda e, errs=errs: errs.append(f"pageerror: {e}"))
        B2 = f"http://127.0.0.1:{puerto}"
        if rol == "operador":
            abrir(pg, B2, "/recomendaciones", 3000)
            pg.locator("#re-calcular").click()
            esperar(pg, 2000)
            t = pg.locator("#re-escenario").inner_text()
            ok("auth operador: calcular escenario → 403 con un aviso claro",
               "prohibido" in t and "rol" in t and "Traceback" not in t, t[:200])
            pg.evaluate("() => document.querySelector('#re-escenario').scrollIntoView({block: 'center'})")
            pg.screenshot(path=str(OUT / "dash_auth_operador_403.png"))
            abrir(pg, B2, "/monitoreo", 2500)
            ok("auth operador: Monitoreo se puede leer (GET es de operador)",
               "WAPE móvil" in pg.locator("#mo-cifras").inner_text(), "")
        else:
            for nombre, ruta, sel in (("inicio", "/", "#in-resp-cuerpo"), ("alertas", "/alertas", "#al-aviso-api"),
                                      ("recomendaciones", "/recomendaciones", "#re-aviso-api"),
                                      ("monitoreo", "/monitoreo", "#mo-estado"),
                                      ("operacion", "/operacion", "#op-aviso-api")):
                abrir(pg, B2, ruta, 3000)
                t = pg.locator(sel).inner_text()
                ok(f"auth clave inválida: {nombre} dice que la API pide una clave válida",
                   "clave válida" in t and "Traceback" not in t, t[:180])
                if nombre in ("alertas", "inicio"):
                    pg.screenshot(path=str(OUT / f"dash_auth_401_{nombre}.png"))
        ok(f"auth {rol}: 0 errores de consola", not errs, errs)
        ctx.close()
    nav.close()

res["fin"] = time.strftime("%Y-%m-%d %H:%M:%S")
res["resumen"] = {"pruebas": len(res["pruebas"]), "fallas": len(fallas), "lista_fallas": fallas}
(OUT / "e2e_tablero_completo.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
cab = [f"E2E del tablero (once pantallas) · Edge sin interfaz · 1600×900 · {res['inicio']} → {res['fin']}",
       f"Dash con la clave de analista en {ADMIN}, de operador en {OPER} y una clave inválida en {MALA}; API de "
       f"desarrollo en {API}.",
       f"Resultado: {len(res['pruebas']) - len(fallas)} de {len(res['pruebas'])} comprobaciones bien, "
       f"{len(fallas)} fallas.", ""]
(OUT / "e2e_tablero_completo.txt").write_text("\n".join(cab + LINEAS) + "\n", encoding="utf-8")
print(res["resumen"])
sys.exit(1 if fallas else 0)
