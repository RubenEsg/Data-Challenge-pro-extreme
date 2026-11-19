"""E2E de Pronóstico › «Lo que pide el enunciado: 30, 60 y 120 minutos» con Edge sin interfaz, contra la API de
desarrollo (spec v1.5 §2.2, RF-005, §3.1 M3, RNF-012).

Uso: python e2e_corto_plazo.py PUERTO_TABLERO PUERTO_API CARPETA_EVIDENCIA
- Carga Pronóstico a 1600 px y a 400 px: título, 0 errores de consola y sin desplazamiento horizontal.
- Con los controles por omisión (CRA 54, el día de ejemplo del informe, 17:00, 60 min) y después con SILENCIO a 30 min:
  las cifras del instante (pronóstico, banda, promedio por día y hora, lo real y la recomendación) son las de
  GET /api/v1/predictions/corto-plazo/calcular; la curva del día trae los 35 instantes de GET …/dia; el perfil por
  segmento trae un segmento por fila (123 en CRA 54, 135 en SILENCIO); los dos sentidos y la primera variable de la
  explicación son los de la API.
- La tabla de la prueba reservada es la de datos/corto_plazo.json (sin API) y está el aviso «Lo que no funcionó».
- Capturas: dash_pronostico.png (1600×900), dash_pronostico_completa.png y dash_pronostico_corto_plazo.png.
Escribe e2e_corto_plazo.txt y .json. Requiere Playwright y Microsoft Edge."""
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

TABLERO, API = (int(x) for x in sys.argv[1:3])
OUT = Path(sys.argv[3])
OUT.mkdir(parents=True, exist_ok=True)
AQUI = Path(__file__).resolve().parent
CP = json.loads((AQUI.parents[3] / "dash_app" / "datos" / "corto_plazo.json").read_text(encoding="utf-8"))
res = {"inicio": time.strftime("%Y-%m-%d %H:%M:%S"), "pruebas": []}
LINEAS = []


def ok(nombre, cond, detalle=""):
    res["pruebas"].append({"prueba": nombre, "ok": bool(cond), "detalle": str(detalle)[:400]})
    linea = ("OK    " if cond else "FALLA ") + f"{nombre} · {str(detalle)[:220]}".replace("\n", " | ")
    LINEAS.append(linea)
    print(linea, flush=True)


def api(recurso, **params):
    url = f"http://127.0.0.1:{API}/api/v1/{recurso}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=60) as r:   # noqa: S310 - API local de desarrollo
        return json.loads(r.read().decode("utf-8"))


def es(x, d=0):
    """Formato es-CO del tablero (miles «.», decimales «,»)."""
    s = f"{x:,.{d}f}"
    return s.replace(",", "§").replace(".", ",").replace("§", ".")


def esperar_seccion(pg):
    pg.wait_for_selector("#cp-dia-titulo:not(:empty)", timeout=60000)
    pg.wait_for_load_state("networkidle")
    pg.wait_for_timeout(1500)


def comprobar(pg, ruta, fecha, hora, h, segmentos):
    r = api("predictions/corto-plazo/calcular", ruta=ruta, instante=f"{fecha}T{hora}:00-05:00", horizonte_min=h)
    d = api("predictions/corto-plazo/dia", ruta=ruta, fecha=fecha, horizonte_min=h)
    cif = pg.locator("#cp-cifras").inner_text()
    ok(f"{ruta} {hora} {h} min: pronóstico y banda = GET /calcular",
       es(r["pasajeros"]) in cif and es(r["p10"]) in cif and es(r["p90"]) in cif,
       f"{r['pasajeros']} [{r['p10']}; {r['p90']}]")
    ok(f"{ruta} {hora} {h} min: promedio por día y hora y lo real = API",
       es(r["promedio_dia_hora"]) in cif and (r["real"] is None or es(r["real"]) in cif),
       f"promedio {r['promedio_dia_hora']} · real {r['real']}")
    rec = r.get("recomendacion") or {}
    ok(f"{ruta} {hora} {h} min: la recomendación de §10.2 = API",
       (es(rec["buses_hora"]) in cif and es(rec["headway_min"], 1) in cif) if rec.get("viable") else "No viable" in cif,
       f"viable {rec.get('viable')} · {rec.get('buses_hora')} buses/h cada {rec.get('headway_min')} min")
    filas_dia = pg.locator("#cp-dia-tabla tbody tr").count()
    ok(f"{ruta} {h} min: la curva del día tiene los instantes de GET /dia", filas_dia == len(d["instantes"]) == 35,
       f"{filas_dia} filas · API {len(d['instantes'])}")
    filas_seg = pg.locator("#cp-seg-tabla tbody tr").count()
    ok(f"{ruta}: un segmento por fila en el perfil", filas_seg == segmentos == len(r["segmentos"]),
       f"{filas_seg} filas · API {len(r['segmentos'])}")
    sen = pg.locator("#cp-sentidos").inner_text()
    ok(f"{ruta}: ida y regreso = API", all(es(s["pasajeros"]) in sen for s in r["sentidos"]),
       [(s["sentido"], s["pasajeros"]) for s in r["sentidos"]])
    porque = pg.locator("#cp-porque").inner_text()
    f1 = r["explicacion"]["factores"][0]
    ok(f"{ruta}: la variable que más mueve el pronóstico y su factor = API (TreeSHAP)",
       f1["variable"] in porque and es(f1["factor"], 3) in porque, f"{f1['variable']} × {f1['factor']}")
    trazas = pg.locator("#cp-dia .scatterlayer .trace").count()
    ok(f"{ruta}: la curva dibuja banda, pronóstico, promedio y real", trazas >= 4, f"{trazas} trazas")


with sync_playwright() as p:
    nav = p.chromium.launch(channel="msedge", headless=True)
    for ancho in (1600, 400):
        errores = []
        pg = nav.new_page(viewport={"width": ancho, "height": 900})
        pg.on("console", lambda m, e=errores: e.append(m.text) if m.type == "error" else None)
        pg.on("pageerror", lambda x, e=errores: e.append(str(x)))
        pg.goto(f"http://127.0.0.1:{TABLERO}/pronostico", wait_until="networkidle")
        esperar_seccion(pg)
        doc = pg.evaluate("document.documentElement.scrollWidth")
        ok(f"{ancho} px: carga sin errores de consola y sin desplazamiento horizontal", not errores and doc <= ancho,
           f"errores {errores} · ancho del contenido {doc}")
        if ancho == 1600:
            ok("la sección está arriba de la pantalla y rotulada",
               pg.locator("#cp h2").first.inner_text().startswith("Lo que pide el enunciado"),
               pg.locator("#cp h2").first.inner_text())
            fecha = CP["dia_de_ejemplo"]["fecha"]
            comprobar(pg, "CRA 54", fecha, "17:00", 60, 123)
            tabla = pg.locator("#cp").inner_text()
            r60 = CP["niveles"]["ruta"]["60"]
            ok("la prueba reservada = datos/corto_plazo.json (sin API)",
               f"{es(r60['modelo'], 2)} %" in tabla and f"{es(r60['promedio_dia_hora'], 2)} %" in tabla
               and f"{es(CP['niveles']['segmento']['60']['modelo'], 2)} %" in tabla,
               f"ruta 60 min {r60['modelo']} frente a {r60['promedio_dia_hora']}")
            ok("está el aviso «Lo que no funcionó» con los domingos corrientes",
               "Lo que no funcionó" in tabla and "domingos corrientes" in tabla, "")
            pg.screenshot(path=str(OUT / "dash_pronostico.png"))
            pg.locator("#cp").screenshot(path=str(OUT / "dash_pronostico_corto_plazo.png"))
            pg.screenshot(path=str(OUT / "dash_pronostico_completa.png"), full_page=True)
            pg.locator("#cp-ruta label").filter(has_text="SILENCIO").click()
            pg.locator("#cp-h label").filter(has_text="30 min").click()
            esperar_seccion(pg)
            pg.wait_for_timeout(2500)
            comprobar(pg, "SILENCIO", fecha, "17:00", 30, 135)
        pg.close()
    nav.close()
res["fin"] = time.strftime("%Y-%m-%d %H:%M:%S")
res["resumen"] = f"{sum(x['ok'] for x in res['pruebas'])} de {len(res['pruebas'])} comprobaciones bien"
(OUT / "e2e_corto_plazo.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
(OUT / "e2e_corto_plazo.txt").write_text("\n".join(LINEAS + ["", res["resumen"]]) + "\n", encoding="utf-8")
print(res["resumen"])
sys.exit(0 if all(x["ok"] for x in res["pruebas"]) else 1)
