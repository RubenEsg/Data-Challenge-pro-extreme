"""Carga /despacho en frío varias veces (contexto nuevo, sin caché) y cuenta errores de consola y buses en el mapa."""
import sys
import time

from playwright.sync_api import sync_playwright

PUERTO = int(sys.argv[1]) if len(sys.argv) > 1 else 8361
VECES = int(sys.argv[2]) if len(sys.argv) > 2 else 6

JS_BUSES = """() => {
  const cont = document.getElementById('desp-mapa');
  const gd = cont && (cont.classList.contains('js-plotly-plot') ? cont : cont.querySelector('.js-plotly-plot'));
  if (!gd || !gd.data) return -1;
  let n = 0;
  for (const t of gd.data) { if ((t.name || '').startsWith('Buses') && t.lat) n += t.lat.length; }
  return n;
}"""

resultados = []
with sync_playwright() as p:
    nav = p.chromium.launch(channel="msedge", headless=True)
    for i in range(VECES):
        ctx = nav.new_context(viewport={"width": 1600, "height": 900})
        pag = ctx.new_page()
        errores = []
        pag.on("console", lambda m, errores=errores: errores.append(m.text) if m.type == "error" else None)
        pag.on("pageerror", lambda e, errores=errores: errores.append(str(e)))
        t0 = time.time()
        pag.goto(f"http://127.0.0.1:{PUERTO}/despacho", wait_until="domcontentloaded")
        pag.wait_for_timeout(9000)
        buses1 = pag.evaluate(JS_BUSES)
        pag.wait_for_timeout(3000)
        buses2 = pag.evaluate(JS_BUSES)
        listo = pag.evaluate("() => { const s = document.getElementById('desp-mapa'); return !!s; }")
        estilo = [e for e in errores if "Style is not done loading" in e]
        resultados.append((i + 1, round(time.time() - t0, 1), buses1, buses2, len(errores), len(estilo)))
        print(f"carga {i + 1}: buses {buses1} -> {buses2}, errores de consola {len(errores)} (estilo {len(estilo)})"
              + (f" | primero: {errores[0][:160]}" if errores else ""), flush=True)
        ctx.close()
    nav.close()
malas = [r for r in resultados if r[4] > 0 or r[3] <= 0]
print(f"RESULTADO: {len(resultados) - len(malas)} de {len(resultados)} cargas en frío sin errores y con buses en "
      "el mapa")
sys.exit(1 if malas else 0)
