# -*- coding: utf-8 -*-
"""Prueba de humo de las cinco páginas sueltas del proyecto: Microsoft Edge sin interfaz, sin internet.

Abre cada página desde file:// con Playwright (canal msedge, render por software con swiftshader), con toda
petición a internet bloqueada, y espera a que cumpla su condición (hasta un tiempo máximo por página):

  - EDA_visual.html: cargan dashboard_datos.js, dashboard_salidas.js y dashboard_correlaciones.js; hay al menos dos
    gráficos de ECharts dibujados y los KPI tienen texto;
  - planificador.html: carga planificador_datos.js y hay al menos un gráfico;
  - simulador_ahorro.html: carga simulacion_ahorro/simulacion_datos.js y hay al menos un gráfico;
  - consola_despacho.html, abierta en #dia=2025-06-03&hora=07:12: el reloj marca las 07:12 (o el minuto siguiente),
    el mapa de Leaflet existe y la página tiene contenido;
  - vista_3d.html, abierta en #dia=2025-06-03&hora=07:12&local=1&pausa=1: el reloj marca las 07:1x, hay un lienzo
    WebGL y se usa el mapa local de mapa_local/ (insignia «Mapa sin internet (copia local)»).

En todas se juntan los errores de consola y las excepciones de la página (se ignora el «net::ERR_FAILED» de las
peticiones a internet, cortadas a propósito) y se mide el desborde horizontal del documento. Al final imprime una
línea por página y ancho, el resumen, y sale con código 1 si alguna página tuvo errores, no cumplió su condición
o desborda la ventana.

Uso (la carpeta del proyecto se deduce de la ubicación de este archivo; con PYTHONIOENCODING=utf-8 en Windows):
    python app/probar_paginas.py
    python app/probar_paginas.py --ancho 1366 400                     # varios anchos (por defecto solo 1366)
    python app/probar_paginas.py --pagina consola_despacho vista_3d   # solo algunas páginas
    python app/probar_paginas.py --capturas                           # una captura por página y ancho en app/capturas_pruebas/
    python app/probar_paginas.py --capturas otra/carpeta              # … o en la carpeta que se indique (más resultados.json)
    python app/probar_paginas.py --proyecto "D:/otra/copia"           # probar otra copia del proyecto
Tarda unos 15 segundos (12 s el 2-nov-2026 a 1366 px); lo que más tarda es la vista 3D (WebGL por software).
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
ARGS_EDGE = ["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"]


def _texto(id_):
    return f"((document.getElementById('{id_}') || {{innerText: ''}}).innerText || '').trim()"


# Página → (hash con el que se abre, espera máxima en s, JS que mide, condición de «bien» sobre la medida).
PAGINAS = {
    "EDA_visual.html": ("", 40, """() => ({
        datos: !!(window.DATOS && window.DATOS.meta), salidas: !!(window.SALIDAS && window.SALIDAS.dias && window.SALIDAS.dias.length),
        correlaciones: !!(window.CORRELACIONES && window.CORRELACIONES.diaria_niveles),
        echarts: document.querySelectorAll('[_echarts_instance_]').length, canvas: document.querySelectorAll('canvas').length,
        kpis: %s.length })""" % _texto("kpis"),
        lambda r: r["datos"] and r["salidas"] and r["correlaciones"] and r["echarts"] >= 2 and r["kpis"] > 20),
    "planificador.html": ("", 30, """() => ({ plan: !!(window.PLAN && window.PLAN.meta), echarts: document.querySelectorAll('[_echarts_instance_]').length,
        canvas: document.querySelectorAll('canvas').length, texto: document.body.innerText.length })""",
        lambda r: r["plan"] and r["echarts"] >= 1 and r["texto"] > 500),
    "simulador_ahorro.html": ("", 30, """() => ({ sim: !!(window.SIM && window.SIM.generado), echarts: document.querySelectorAll('[_echarts_instance_]').length,
        canvas: document.querySelectorAll('canvas').length, texto: document.body.innerText.length })""",
        lambda r: r["sim"] and r["echarts"] >= 1 and r["texto"] > 500),
    "consola_despacho.html": ("#dia=2025-06-03&hora=07:12", 60, """() => ({ reloj: %s, fecha: %s,
        leaflet: document.querySelectorAll('.leaflet-container').length, canvas: document.querySelectorAll('canvas').length,
        echarts: document.querySelectorAll('[_echarts_instance_]').length, texto: document.body.innerText.length })""" % (_texto("reloj-hm"), _texto("reloj-fecha")),
        lambda r: r["reloj"].startswith("07:1") and r["leaflet"] >= 1 and r["texto"] > 500),
    "vista_3d.html": ("#dia=2025-06-03&hora=07:12&local=1&pausa=1", 90, """() => ({ reloj: %s,
        canvas: document.querySelectorAll('canvas').length, buses: %s,
        mapa_local: !!(document.getElementById('insignia-mapa') && !document.getElementById('insignia-mapa').hidden),
        texto: document.body.innerText.length })""" % (_texto("reloj"), _texto("n-buses")),
        lambda r: "07:1" in r["reloj"] and r["canvas"] >= 1 and r["mapa_local"] and r["texto"] > 200),
}
NOMBRES = [p[:-5] for p in PAGINAS]   # sin «.html», para --pagina


def bloquear(ruta):
    """Deja pasar file:// (y data:, blob:) y corta http(s): la prueba es sin internet."""
    if ruta.request.url.startswith(("http://", "https://")):
        ruta.abort()
    else:
        ruta.continue_()


def probar(proyecto, anchos, paginas, capturas):
    if capturas:
        capturas.mkdir(parents=True, exist_ok=True)
    errores = []   # (ancho, página, tipo, texto)
    filas = []
    t0 = time.time()
    with sync_playwright() as pw:
        nav = pw.chromium.launch(channel="msedge", headless=True, args=ARGS_EDGE)
        for ancho in anchos:
            for pagina in paginas:
                hash_, espera, js, bien = PAGINAS[pagina]
                archivo = proyecto / pagina
                if not archivo.exists():
                    errores.append((ancho, pagina, "falta", f"no existe {archivo}"))
                    print(f"[{ancho}] MAL {pagina}: no existe", flush=True)
                    continue
                t1 = time.time()
                ctx = nav.new_context(viewport={"width": ancho, "height": 900 if ancho > 600 else 800}, device_scale_factor=1)
                ctx.route("**/*", bloquear)
                pag = ctx.new_page()
                err = []
                bloqueadas = set()
                pag.on("requestfailed", lambda r, b=bloqueadas: b.add(r.url.split("/")[2]) if r.url.startswith(("http://", "https://")) else None)
                pag.on("console", lambda m, e=err: e.append(("consola", m.text)) if m.type == "error" and "net::ERR_FAILED" not in m.text else None)
                pag.on("pageerror", lambda x, e=err: e.append(("pagina", str(x))))
                pag.goto(archivo.as_uri() + hash_, wait_until="load")
                # Espera a que la página cumpla su condición, hasta el tiempo máximo (el JS se evalúa en la página).
                try:
                    pag.wait_for_function(f"() => {{ const r = ({js})(); return {bien_js(pagina)}; }}", timeout=espera * 1000)
                except TiempoAgotado:
                    pass
                pag.wait_for_timeout(1000)
                r = pag.evaluate(js)
                cumple = bool(bien(r))
                desborde = pag.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
                if not cumple:
                    errores.append((ancho, pagina, "contenido", f"datos o gráficos no cargados: {r}"))
                if desborde > 1:
                    errores.append((ancho, pagina, "desborde", f"el documento mide {desborde} px más que la ventana"))
                errores.extend((ancho, pagina, t, m) for t, m in err)
                if capturas:
                    pag.screenshot(path=str(capturas / f"pagina_{ancho}_{pagina[:-5]}.png"), full_page=False)
                fila = {"ancho": ancho, "pagina": pagina, "hash": hash_, "cumple": cumple, "desborde_px": desborde, "medida": r,
                        "errores": len(err) + (0 if cumple else 1) + (1 if desborde > 1 else 0), "internet_bloqueado": sorted(bloqueadas),
                        "segundos": round(time.time() - t1, 1)}
                filas.append(fila)
                est = "ok " if fila["errores"] == 0 else "MAL"
                print(f"[{ancho}] {est} {pagina}{hash_}: {r}  desborde {desborde} px  errores {len(err)}  {fila['segundos']} s"
                      + (f"  internet bloqueado: {sorted(bloqueadas)}" if bloqueadas else ""), flush=True)
                ctx.close()
        nav.close()

    veredicto = "OK" if not errores else "FALLA"
    print(f"\nPáginas: {len(paginas)} × {len(anchos)} ancho(s) en {round(time.time() - t0)} s · errores: {len(errores)} · veredicto: {veredicto}")
    for e in errores:
        print(f"  ✗ [{e[0]}] {e[1]}: {e[2]} · {str(e[3])[:300]}")
    if capturas:
        resultado = {"anchos": anchos, "paginas": paginas, "segundos": round(time.time() - t0, 1), "veredicto": veredicto,
                     "errores": [{"ancho": a, "pagina": p, "tipo": t, "texto": str(x)} for a, p, t, x in errores], "filas": filas}
        (capturas / "resultados_paginas.json").write_text(json.dumps(resultado, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"Capturas y resultados_paginas.json en {capturas}")
    return 0 if not errores else 1


def bien_js(pagina):
    """La misma condición de «bien» que la lambda de PAGINAS, escrita en JS para esperar con wait_for_function."""
    return {
        "EDA_visual.html": "r.datos && r.salidas && r.correlaciones && r.echarts >= 2 && r.kpis > 20",
        "planificador.html": "r.plan && r.echarts >= 1 && r.texto > 500",
        "simulador_ahorro.html": "r.sim && r.echarts >= 1 && r.texto > 500",
        "consola_despacho.html": "r.reloj.startsWith('07:1') && r.leaflet >= 1 && r.texto > 500",
        "vista_3d.html": "r.reloj.includes('07:1') && r.canvas >= 1 && r.mapa_local && r.texto > 200",
    }[pagina]


def main(argv=None):
    ap = argparse.ArgumentParser(description="Prueba de humo de las cinco páginas sueltas (Edge sin interfaz, sin internet).")
    ap.add_argument("--proyecto", default=str(PROYECTO), help="carpeta del proyecto (por defecto, la de este archivo)")
    ap.add_argument("--ancho", type=int, nargs="+", default=[1366], help="ancho(s) de ventana en px (por defecto 1366)")
    ap.add_argument("--pagina", nargs="+", choices=NOMBRES, default=NOMBRES, metavar="NOMBRE", help="página(s) a probar: " + " ".join(NOMBRES))
    ap.add_argument("--capturas", nargs="?", const=str(CAPTURAS_POR_DEFECTO), default=None, metavar="CARPETA",
                    help=f"guardar una captura por página y ancho (sin valor: {CAPTURAS_POR_DEFECTO.relative_to(PROYECTO)})")
    a = ap.parse_args(argv)
    paginas = [p for p in PAGINAS if p[:-5] in a.pagina]   # en el orden de la tabla
    return probar(Path(a.proyecto).resolve(), a.ancho, paginas, Path(a.capturas).resolve() if a.capturas else None)


if __name__ == "__main__":
    sys.exit(main())
