"""Prueba de app/muestra.html en el navegador (Playwright + Microsoft Edge, canal 'msedge', render por software con swiftshader).

Abre la muestra desde file:// con todas las peticiones a internet bloqueadas, con el sistema en claro y en oscuro (la app es
solo clara desde el 19-oct-2026: en los dos casos el fondo debe ser el claro), a 1366 y 400 px de ancho y con la barra plegada; prueba el interruptor, el popover de
fuente (y que quede bajo su botón), la tabla gemela y las pestañas; guarda capturas en app/capturas_muestra/ y junta los
errores de consola, las excepciones y las peticiones fallidas. Falla si hay algún error, alguna petición a internet o
desplazamiento horizontal (se ignoran los descendientes de elementos fijos y de contenedores con desplazamiento propio).

Uso, desde la carpeta del proyecto:  PYTHONIOENCODING=utf-8 python app/probar_muestra.py
"""
import json
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

AQUI = Path(__file__).resolve().parent
URL = (AQUI / "muestra.html").as_uri()
CAPT = AQUI / "capturas_muestra"
ARGS = ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"]


def main():
    CAPT.mkdir(exist_ok=True)
    errores, avisos, red, medidas, capturas = [], [], [], {}, []
    t0 = time.time()
    with sync_playwright() as pw:
        nav = pw.chromium.launch(channel="msedge", headless=True, args=ARGS)

        def abrir(ancho, alto, esquema):
            ctx = nav.new_context(viewport={"width": ancho, "height": alto}, color_scheme=esquema, device_scale_factor=1)
            ctx.route("**/*", lambda ruta: ruta.abort() if ruta.request.url.startswith(("http://", "https://")) else ruta.continue_())
            pg = ctx.new_page()
            etiqueta = f"{ancho}-{esquema}"
            pg.on("console", lambda m: (errores if m.type == "error" else avisos if m.type == "warning" else []).append({"vista": etiqueta, "tipo": m.type, "texto": m.text}))
            pg.on("pageerror", lambda e: errores.append({"vista": etiqueta, "tipo": "pageerror", "texto": str(e)}))
            pg.on("requestfailed", lambda r: red.append({"vista": etiqueta, "url": r.url, "error": r.failure}))
            pg.goto(URL, wait_until="load")
            pg.wait_for_function("window.__muestraLista === true", timeout=20000)
            pg.wait_for_timeout(700)
            return ctx, pg, etiqueta

        def medir(pg, etiqueta):
            m = pg.evaluate("""() => {
                const doc = document.documentElement;
                const fuera = [];
                const enFijoODesplazable = el => { for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) { const cs = getComputedStyle(p); if (cs.position === 'fixed' || /(auto|scroll)/.test(cs.overflowX)) return true; } return getComputedStyle(el).position === 'fixed'; };
                document.querySelectorAll('body *').forEach(el => {
                    const r = el.getBoundingClientRect();
                    if (r.width > 0 && r.right > window.innerWidth + 1 && !enFijoODesplazable(el) && !el.closest('.modulo--dormido')) {
                        fuera.push((el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') + (el.className && typeof el.className === 'string' ? '.' + el.className.split(' ').slice(0, 2).join('.') : '')) + ' → ' + Math.round(r.right));
                    }
                });
                const nav = document.querySelector('.lateral__nav');
                return {
                    scrollWidth: doc.scrollWidth, innerWidth: window.innerWidth, desborde: doc.scrollWidth > window.innerWidth, fuera: fuera.slice(0, 20), nFuera: fuera.length,
                    navMovil: nav ? { clientWidth: nav.clientWidth, scrollWidth: nav.scrollWidth, desplazable: nav.scrollWidth > nav.clientWidth } : null,
                    canvases: document.querySelectorAll('canvas').length, fondo: getComputedStyle(document.body).backgroundColor,
                    tema: document.documentElement.getAttribute('data-theme'), tokensOk: !!getComputedStyle(document.documentElement).getPropertyValue('--acento').trim(),
                    iconos: document.querySelectorAll('svg use').length, altura: doc.scrollHeight,
                };
            }""")
            medidas[etiqueta] = m
            return m

        def foto(pg, nombre, completa=True):
            pg.screenshot(path=str(CAPT / f"{nombre}.png"), full_page=completa)
            capturas.append(f"{nombre}.png")

        for esquema in ("light", "dark"):
            tema_txt = "sistema_claro" if esquema == "light" else "sistema_oscuro"
            for ancho, alto in ((1366, 900), (400, 800)):
                ctx, pg, etiqueta = abrir(ancho, alto, esquema)
                medir(pg, etiqueta)
                foto(pg, f"muestra_{ancho}_{tema_txt}")
                if ancho == 400:
                    foto(pg, f"muestra_400_{tema_txt}_ventana_arriba", completa=False)
                    pg.evaluate("document.getElementById('s-graficos').scrollIntoView()")
                    pg.wait_for_timeout(400)
                    foto(pg, f"muestra_400_{tema_txt}_ventana_graficos", completa=False)
                    pg.evaluate("document.querySelector('.lateral__nav').scrollTo({left: 400})")
                    pg.wait_for_timeout(300)
                    foto(pg, f"muestra_400_{tema_txt}_ventana_pestanas", completa=False)
                if ancho == 1366:
                    pg.click("#esc-modelo")
                    pg.wait_for_timeout(800)
                    pg.click("#fuente-btn-1")
                    pg.wait_for_timeout(400)
                    geo = pg.evaluate("""() => { const pe = document.querySelector('.fuente-pop:popover-open'); if (!pe) return { abierto: null, bien: false };
                        const p = pe.getBoundingClientRect(); const b = document.getElementById('fuente-btn-1').getBoundingClientRect();
                        return { abierto: pe.id, popTop: Math.round(p.top), popLeft: Math.round(p.left), btnBottom: Math.round(b.bottom), btnLeft: Math.round(b.left),
                                 bien: p.top >= b.bottom && p.left >= 0 && p.right <= window.innerWidth && p.bottom <= window.innerHeight }; }""")
                    medidas[etiqueta]["popover"] = geo
                    foto(pg, f"muestra_1366_{tema_txt}_popover", completa=False)
                    pg.keyboard.press("Escape")
                    pg.click("#ver-tabla-1")
                    pg.wait_for_timeout(300)
                    medidas[etiqueta]["tabla_visible"] = pg.evaluate("() => !document.querySelector('#grafico-1 .grafico__tabla').hidden")
                    pg.click("#ver-tabla-1")
                    pg.click("#pestana-2")
                    medidas[etiqueta]["pestana_cambia"] = pg.evaluate("() => document.getElementById('pestana-2').getAttribute('aria-selected') === 'true' && !document.getElementById('panel-2').hidden")
                    pg.click("[data-plegar]")
                    pg.wait_for_timeout(500)
                    medir(pg, etiqueta + "-plegada")
                    foto(pg, f"muestra_1366_{tema_txt}_plegada")
                    pg.click("[data-plegar]")
                ctx.close()
        nav.close()

    internet = [r for r in red if r["url"].startswith(("http://", "https://"))]
    desbordes = {k: v for k, v in medidas.items() if v["desborde"] or v["nFuera"]}
    popover_mal = [k for k, v in medidas.items() if "popover" in v and not v["popover"]["bien"]]
    no_claro = [k for k, v in medidas.items() if v["tema"] != "light" or v["fondo"] not in ("rgb(245, 245, 247)", "rgba(0, 0, 0, 0)")]
    resultado = {
        "url": URL, "segundos": round(time.time() - t0, 1), "capturas": capturas, "errores": errores, "avisos": avisos,
        "peticiones_internet": internet, "medidas": medidas, "desbordes": desbordes, "popover_mal_colocado": popover_mal, "no_claro": no_claro,
        "veredicto": "OK" if not errores and not internet and not desbordes and not popover_mal and not no_claro else "FALLA",
    }
    (CAPT / "resultados.json").write_text(json.dumps(resultado, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: resultado[k] for k in ("segundos", "veredicto", "errores", "avisos", "peticiones_internet", "desbordes", "popover_mal_colocado", "no_claro")}, ensure_ascii=False, indent=1))
    for k, v in medidas.items():
        print(f"{k:28s} scroll {v['scrollWidth']:5d} / ventana {v['innerWidth']:5d}  canvas {v['canvases']}  iconos {v['iconos']:3d}  fondo {v['fondo']}  alto {v['altura']}"
              + (f"  popover {v['popover']['abierto']} bien={v['popover']['bien']} tabla {v.get('tabla_visible')} pestaña {v.get('pestana_cambia')}" if 'popover' in v else ""))
    return 0 if resultado["veredicto"] == "OK" else 1


if __name__ == "__main__":
    sys.exit(main())
