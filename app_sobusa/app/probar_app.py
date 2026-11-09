# -*- coding: utf-8 -*-
"""Prueba de humo de la app «Sobusa Despacho» (app.html): Microsoft Edge sin interfaz, sin internet.

Abre app.html desde file:// con Playwright (canal msedge, render por software con swiftshader) y bloquea toda
petición a internet, como cuando se abre con doble clic en un equipo sin conexión. En cada ancho (1366 y 400 px
por defecto) recorre las nueve pantallas por su hash (#inicio … #metodo) y en cada una:

  - junta los errores de consola y las excepciones de la página, también las de los iframes embebidos (se ignora
    el «net::ERR_FAILED» de las peticiones a internet, que la prueba bloquea a propósito);
  - mide el desborde horizontal del documento (scrollWidth − clientWidth, debe ser 0) y cuenta los elementos que
    se salen del ancho de la ventana (sin contar los fijos, los que están dentro de un contenedor con
    desplazamiento propio, los invisibles y los módulos dormidos);
  - comprueba que la cabecera tiene un h1 visible con la pregunta de la pantalla (y que es el único h1);
  - si la pantalla tiene módulo embebido (Horario: planificador; Despacho: consola; Ciudad: vista 3D; Resultado:
    simulador de ahorro; Método y datos: tablero), espera a que su iframe cargue («Cargado» o «Listo») y anota si
    la página embebida avisó «listo» a la app;
  - en «Método y datos» comprueba la ficha «Capacidad real de la flota» (con su botón de fuente) y la línea del
    último día de cada mes.

Al final imprime una línea por pantalla y ancho, el resumen, y sale con código 1 si hubo errores de página o de
consola, desbordes, pantallas sin h1, módulos que no cargaron o textos esperados que faltan.

Uso (la carpeta del proyecto se deduce de la ubicación de este archivo; con PYTHONIOENCODING=utf-8 en Windows):
    python app/probar_app.py
    python app/probar_app.py --ancho 1366                  # solo un ancho (se pueden dar varios)
    python app/probar_app.py --pantalla ciudad despacho    # solo algunas pantallas
    python app/probar_app.py --capturas                    # una captura por pantalla y ancho en app/capturas_pruebas/
    python app/probar_app.py --capturas otra/carpeta       # … o en la carpeta que se indique (más resultados.json)
    python app/probar_app.py --proyecto "D:/otra/copia"    # probar otra copia del proyecto
Tarda alrededor de un minuto (56 s el 2-nov-2026 con los dos anchos); lo que más tarda es la vista 3D (WebGL por software).
"""
import argparse
import json
import sys
import time
from pathlib import Path

from playwright.sync_api import TimeoutError as TiempoAgotado
from playwright.sync_api import sync_playwright

AQUI = Path(__file__).resolve().parent
PROYECTO = AQUI.parent
CAPTURAS_POR_DEFECTO = AQUI / "capturas_pruebas"

# Las nueve pantallas, en el orden de la barra lateral (app/app.js, lista PANTALLAS).
PANTALLAS = ["inicio", "demanda", "modelo", "horario", "despacho", "ciudad", "resultado", "piloto", "metodo"]
# Pantallas con módulo embebido y la página que carga cada una. Horario, Despacho, Ciudad y Método usan el módulo
# de app.js (sección .modulo con su estado «Cargando… / Cargado / Listo»); Resultado monta su propio iframe
# (#res-modulo-cuerpo) cuando el bloque del simulador entra en la vista.
MODULOS = {
    "horario": "planificador.html",
    "despacho": "consola_despacho.html",
    "ciudad": "vista_3d.html",
    "resultado": "simulador_ahorro.html",
    "metodo": "EDA_visual.html",
}
# Segundos de espera máxima para que cargue el iframe de cada módulo (la vista 3D y la consola cargan un día entero).
ESPERA_MODULO_S = {"ciudad": 90, "despacho": 60}
ESPERA_MODULO_S_DEFECTO = 40
# Textos que deben verse en «Método y datos» (ficha de capacidad de la flota y línea del último día de cada mes).
TEXTOS_METODO = ("Capacidad real de la flota", "Último día de cada mes de 2025", "Mediana (sentados + de pie)",
                 "Vehículos que corrieron en 2025")
ARGS_EDGE = ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"]

JS_MEDIR = """() => {
  const doc = document.documentElement;
  const fuera = [];
  const excluido = el => {
    if (el.closest('.modulo--dormido, .pantalla--dormida, [hidden]')) return true;
    for (let p = el; p && p !== document.body; p = p.parentElement) {
      const cs = getComputedStyle(p);
      if (cs.position === 'fixed' || /(auto|scroll)/.test(cs.overflowX) || cs.visibility === 'hidden' || cs.opacity === '0' || cs.display === 'none') return true;
    }
    return false;
  };
  document.querySelectorAll('body *').forEach(el => {
    const r = el.getBoundingClientRect();
    if (r.width > 0 && r.right > window.innerWidth + 1 && !excluido(el)) {
      fuera.push(el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') + (typeof el.className === 'string' && el.className ? '.' + el.className.split(' ').slice(0, 2).join('.') : '') + ' → ' + Math.round(r.right) + ' px');
    }
  });
  const h1 = document.getElementById('cab-pregunta');
  const rh = h1 ? h1.getBoundingClientRect() : null;
  return {
    desborde: doc.scrollWidth - doc.clientWidth,
    fuera: fuera.slice(0, 10), n_fuera: fuera.length,
    h1: h1 && rh.height > 0 ? h1.textContent.trim() : '',
    n_h1: document.querySelectorAll('h1').length,
    activa: document.querySelector('.lateral__nav [aria-current]') ? document.querySelector('.lateral__nav [aria-current]').textContent.trim() : '',
    error_pintar: !!document.querySelector('#pantallas .aviso--critico[role="alert"]'),
    fuentes: document.querySelectorAll('#pantallas [popovertarget], #pantallas [data-fuente]').length,
    canvas: document.querySelectorAll('canvas').length,
    texto: (document.getElementById('pantallas') || {innerText: ''}).innerText.length,
  };
}"""

JS_MODULO = """(id) => {
  if (id === 'resultado') {
    const marco = document.querySelector('#res-modulo-cuerpo iframe');
    const cargando = document.getElementById('res-modulo-cargando');
    const estado = document.getElementById('res-modulo-estado');
    if (!marco) return { existe: false, cargado: false, listo: false, estado: '' };
    return { existe: true, cargado: !!(cargando && cargando.hidden), listo: null, estado: estado ? estado.textContent.trim() : '' };
  }
  const m = window.app && window.app.modulo(id);
  if (!m) return { existe: false, cargado: false, listo: false, estado: '' };
  const e = m.elemento.querySelector('[data-estado]');
  const t = e ? e.textContent.trim() : '';
  return { existe: true, cargado: t === 'Cargado' || t === 'Listo', listo: !!m.listo, estado: t };
}"""


def bloquear(ruta):
    """Deja pasar file:// (y data:, blob:) y corta http(s): la prueba es sin internet."""
    if ruta.request.url.startswith(("http://", "https://")):
        ruta.abort()
    else:
        ruta.continue_()


def esperar_modulo(pag, pantalla, segundos):
    """Espera a que el iframe de la pantalla cargue; devuelve el estado final del módulo."""
    if pantalla == "resultado":
        # El simulador se monta cuando su bloque se acerca a la vista: se lleva hasta él.
        pag.evaluate("() => { const m = document.getElementById('res-modulo'); if (m) m.scrollIntoView(); }")
    else:
        # Los módulos van debajo del resumen (3-nov-2026): se lleva la ventana hasta el iframe, porque la vista 3D solo
        # termina de cargar (y avisa «listo») cuando su iframe entra en la ventana, como le pasaría al jurado al bajar.
        pag.evaluate("(id) => { const m = window.app && window.app.modulo(id); if (m && m.elemento) m.elemento.scrollIntoView(); }", pantalla)
    try:
        pag.wait_for_function("(id) => (" + JS_MODULO + ")(id).cargado", arg=pantalla, timeout=segundos * 1000)
    except TiempoAgotado:
        pass
    estado = pag.evaluate(JS_MODULO, pantalla)
    if estado["cargado"] and estado["listo"] is False:
        # Cargó pero aún no avisó «listo»: unos segundos más (no es fallo si no llega; se anota).
        try:
            pag.wait_for_function("(id) => (" + JS_MODULO + ")(id).listo", arg=pantalla, timeout=15000)
        except TiempoAgotado:
            pass
        estado = pag.evaluate(JS_MODULO, pantalla)
    return estado


def probar(proyecto, anchos, pantallas, capturas):
    url = (proyecto / "app.html").as_uri()
    if not (proyecto / "app.html").exists():
        print(f"No existe {proyecto / 'app.html'}")
        return 2
    if capturas:
        capturas.mkdir(parents=True, exist_ok=True)
    errores = []      # (ancho, pantalla, tipo, texto)
    filas = []        # resumen por ancho y pantalla
    bloqueadas = {}   # ancho → hosts de las peticiones a internet que se cortaron
    actual = {"ancho": None, "pantalla": "carga"}
    t0 = time.time()

    def anotar(tipo, texto):
        errores.append((actual["ancho"], actual["pantalla"], tipo, texto))

    with sync_playwright() as pw:
        nav = pw.chromium.launch(channel="msedge", headless=True, args=ARGS_EDGE)
        for ancho in anchos:
            actual["ancho"], actual["pantalla"] = ancho, "carga"
            ctx = nav.new_context(viewport={"width": ancho, "height": 900 if ancho > 600 else 800}, device_scale_factor=1)
            ctx.route("**/*", bloquear)
            pag = ctx.new_page()
            bloqueadas[ancho] = set()
            pag.on("requestfailed", lambda r, a=ancho: bloqueadas[a].add(r.url.split("/")[2] if r.url.startswith(("http://", "https://")) else r.url[:80]))
            pag.on("console", lambda m: anotar("consola", m.text) if m.type == "error" and "net::ERR_FAILED" not in m.text else None)
            pag.on("pageerror", lambda e: anotar("pagina", str(e)))
            pag.goto(url + "#" + pantallas[0], wait_until="load")
            try:
                pag.wait_for_function("window.__appLista === true", timeout=20000)
            except TiempoAgotado:
                anotar("carga", "la app no terminó de arrancar en 20 s (window.__appLista)")
            pag.wait_for_timeout(800)
            for p in pantallas:
                actual["pantalla"] = p
                t1 = time.time()
                pag.evaluate(f"location.hash = '#{p}'")
                pag.wait_for_timeout(1500)
                modulo = None
                if p in MODULOS:
                    modulo = esperar_modulo(pag, p, ESPERA_MODULO_S.get(p, ESPERA_MODULO_S_DEFECTO))
                    if not modulo["existe"]:
                        anotar("modulo", f"no se creó el iframe de {MODULOS[p]}")
                    elif not modulo["cargado"]:
                        anotar("modulo", f"el iframe de {MODULOS[p]} no cargó (estado «{modulo['estado']}»)")
                # Hasta el final y de vuelta arriba: así se montan las partes perezosas antes de medir y capturar.
                pag.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                pag.wait_for_timeout(400)
                pag.evaluate("window.scrollTo(0, 0)")
                pag.wait_for_timeout(300)
                m = pag.evaluate(JS_MEDIR)
                if m["desborde"] > 1:
                    anotar("desborde", f"el documento mide {m['desborde']} px más que la ventana")
                if m["n_fuera"]:
                    anotar("desborde", f"{m['n_fuera']} elemento(s) fuera del ancho: " + "; ".join(m["fuera"]))
                if not m["h1"]:
                    anotar("h1", "la cabecera no tiene un h1 visible")
                if m["n_h1"] != 1:
                    anotar("h1", f"hay {m['n_h1']} h1 en la página (debe haber uno)")
                if m["error_pintar"]:
                    anotar("pagina", "la pantalla muestra el aviso «no se pudo pintar»")
                if p == "metodo":
                    txt = pag.inner_text("body")
                    for esperado in TEXTOS_METODO:
                        if esperado not in txt:
                            anotar("falta", f"no se ve «{esperado}»")
                    if pag.evaluate("document.querySelectorAll('#metodo-ultimo-dia button, #metodo-ultimo-dia [aria-haspopup]').length") < 1:
                        anotar("falta", "la línea del último día de cada mes no tiene botón de fuente")
                if capturas:
                    pag.screenshot(path=str(capturas / f"app_{ancho}_{p}.png"), full_page=True)
                fila = {"ancho": ancho, "pantalla": p, "h1": m["h1"], "desborde_px": m["desborde"], "fuera": m["n_fuera"],
                        "modulo": (MODULOS.get(p) if modulo else None), "modulo_estado": (modulo or {}).get("estado"),
                        "modulo_listo": (modulo or {}).get("listo"), "texto": m["texto"], "canvas": m["canvas"],
                        "errores": sum(1 for e in errores if e[0] == ancho and e[1] == p), "segundos": round(time.time() - t1, 1)}
                filas.append(fila)
                est = "ok " if fila["errores"] == 0 else "MAL"
                mod = ""
                if modulo:
                    mod = f"  módulo {MODULOS[p]}: {modulo['estado'] or 'sin iframe'}" + ("" if modulo["listo"] is None else (" (avisó listo)" if modulo["listo"] else " (sin aviso listo)"))
                print(f"[{ancho}] {est} {p:10s} h1 «{m['h1']}»  desborde {m['desborde']} px, fuera {m['n_fuera']}{mod}  {fila['segundos']} s", flush=True)
            actual["pantalla"] = "cierre"
            print(f"[{ancho}] peticiones a internet bloqueadas: {sorted(bloqueadas[ancho]) or 'ninguna'}", flush=True)
            ctx.close()
        nav.close()

    n_desb = sum(1 for e in errores if e[2] == "desborde")
    n_h1 = sum(1 for e in errores if e[2] == "h1")
    n_mod = sum(1 for e in errores if e[2] == "modulo")
    n_err = sum(1 for e in errores if e[2] in ("pagina", "consola", "carga"))
    n_falta = sum(1 for e in errores if e[2] == "falta")
    veredicto = "OK" if not errores else "FALLA"
    print(f"\nPantallas: {len(pantallas)} × {len(anchos)} ancho(s) en {round(time.time() - t0)} s · errores de página o consola: {n_err} · "
          f"desbordes: {n_desb} · sin h1: {n_h1} · módulos sin cargar: {n_mod} · textos que faltan: {n_falta} · veredicto: {veredicto}")
    for e in errores:
        print(f"  ✗ [{e[0]}] {e[1]}: {e[2]} · {e[3][:300]}")
    if capturas:
        resultado = {"url": url, "anchos": anchos, "pantallas": pantallas, "segundos": round(time.time() - t0, 1), "veredicto": veredicto,
                     "errores": [{"ancho": a, "pantalla": p, "tipo": t, "texto": x} for a, p, t, x in errores],
                     "peticiones_internet_bloqueadas": {str(k): sorted(v) for k, v in bloqueadas.items()}, "filas": filas}
        (capturas / "resultados.json").write_text(json.dumps(resultado, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"Capturas y resultados.json en {capturas}")
    return 0 if not errores else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description="Prueba de humo de app.html (Edge sin interfaz, sin internet).")
    ap.add_argument("--proyecto", default=str(PROYECTO), help="carpeta del proyecto (por defecto, la de este archivo)")
    ap.add_argument("--ancho", type=int, nargs="+", default=[1366, 400], help="ancho(s) de ventana en px (por defecto 1366 y 400)")
    ap.add_argument("--pantalla", nargs="+", choices=PANTALLAS, default=PANTALLAS, metavar="ID", help="pantalla(s) a probar: " + " ".join(PANTALLAS))
    ap.add_argument("--capturas", nargs="?", const=str(CAPTURAS_POR_DEFECTO), default=None, metavar="CARPETA",
                    help=f"guardar una captura por pantalla y ancho (sin valor: {CAPTURAS_POR_DEFECTO.relative_to(PROYECTO)})")
    a = ap.parse_args(argv)
    pantallas = [p for p in PANTALLAS if p in a.pantalla]   # en el orden de la barra
    return probar(Path(a.proyecto).resolve(), a.ancho, pantallas, Path(a.capturas).resolve() if a.capturas else None)


if __name__ == "__main__":
    sys.exit(main())
