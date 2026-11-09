"""Sobusa Despacho · Laboratorio del modelo (Dash).

El modelo funcionando en vivo: pronósticos fuera de muestra de 2025 y el optimizador de salidas (MILP de D5 con CBC) que se
resuelve en el momento con la ruta, el día, el modelo de pronóstico y los costos que se elijan.

Uso:
    python -m venv .venv
    .venv\\Scripts\\activate            (Windows)   ·   source .venv/bin/activate   (macOS / Linux)
    pip install -r requirements.txt
    python app.py                      ->  http://127.0.0.1:8050

Si falta la carpeta datos/, se genera desde el proyecto completo con `python preparar_datos.py`.
El sistema de diseño (colores por rol, escala, componentes) está en DISENO.md; lo comprueba verificar_estilo.py.
"""
import json
import os
import sys
from pathlib import Path

sys.dont_write_bytecode = True               # no dejar __pycache__ dentro de la carpeta de la entrega

import dash  # noqa: E402
import flask  # noqa: E402
from dash import Dash, Input, Output, dcc, html  # noqa: E402

AQUI = Path(__file__).resolve().parent
if str(AQUI) not in sys.path:
    sys.path.insert(0, str(AQUI))

import datos_app as D  # noqa: E402
import ui  # noqa: E402

MARCA = "Sobusa Despacho"
TITULO = f"{MARCA} · Laboratorio del modelo"

app = Dash(__name__, use_pages=True, pages_folder=str(AQUI / "paginas"), assets_folder=str(AQUI / "assets"),
           title=TITULO, update_title=None, suppress_callback_exceptions=True,
           meta_tags=[{"name": "viewport", "content": "width=device-width, initial-scale=1, viewport-fit=cover"},
                      {"name": "description", "content": "El modelo de pronóstico y el optimizador de despacho de Sobusa, funcionando en vivo."},
                      {"name": "color-scheme", "content": "light"},
                      {"name": "theme-color", "content": ui.ROL["fondo"]}])
server = app.server

# Cada pantalla tiene un solo nombre en la barra, en las pestañas del teléfono y en el título del navegador; la pregunta
# (su h1) va en el title del enlace. El color del cuadro sale de --pantalla-<id> (DISENO.md §2.7).
NAV = [
    ("/", "inicio", "Inicio", "¿Qué proponemos?"),
    ("/pronostico", "pronostico", "Pronóstico", "¿Cuántos pasajeros habrá?"),
    ("/horario", "horario", "Horario", "¿Cuántos buses y cada cuánto?"),
    ("/despacho", "despacho", "Despacho", "¿Qué sale ahora y en qué bus?"),
    ("/modelo", "modelo", "Modelo", "¿Qué modelo es y por qué?"),
    ("/resultado", "resultado", "Resultado", "¿Qué gana Sobusa?"),
    ("/enlaces", "enlaces", "Enlaces", "¿Dónde está el resto del proyecto?"),
]

# El nombre y el título del navegador de cada página salen de NAV, aunque la página registre otros.
for _pagina in dash.page_registry.values():
    for _ruta, _id, _nombre, _pregunta in NAV:
        if _pagina.get("path") == _ruta:
            _pagina["name"] = _nombre
            _pagina["title"] = f"{_nombre} · {MARCA}"


CLASE_ENLACE = "barra__enlace"


def barra_superior():
    """Navegación arriba (la de la referencia): logo + «Sobusa Despacho» a la izquierda, las siete pantallas como pestañas de
    texto (la activa en píldora negra) y el chip «Cálculo en vivo» a la derecha. En el teléfono las pestañas se desplazan."""
    enlaces = []
    for i, (ruta, pantalla, nombre, pregunta) in enumerate(NAV):
        enlaces.append(html.Li(dcc.Link(nombre, href=ruta, id=f"nav-{i}", title=pregunta, className=CLASE_ENLACE)))
    return html.Header(html.Div([
        dcc.Link([html.Span(ui.icono("bus"), className="barra__logo"), html.Span(MARCA, className="barra__nombre")],
                 href="/", className="barra__marca", title="Inicio · Laboratorio del modelo"),
        html.Nav(html.Ul(enlaces, className="barra__lista"), className="barra__nav", **{"aria-label": "Pantallas"}),
        html.Div(html.Span([ui.icono("bien", "glifo--s"), html.Span("Cálculo en vivo", className="barra__estado-texto")],
                           className="barra__estado", title="El optimizador se resuelve en el momento · Data Challenge 2026 · Uninorte",
                           **{"aria-label": "Cálculo en vivo"}),
                 className="barra__derecha"),
    ], className="barra__dentro"), className="barra")


barra_lateral = barra_superior   # el nombre anterior


def aviso_datos():
    faltan = D.faltan_datos()
    if not faltan:
        return None
    return html.Div(ui.aviso([html.Span("Faltan archivos en datos/: " + ", ".join(faltan) + ". "),
                              html.Span("Genéralos desde el proyecto completo con "), html.Code("python preparar_datos.py"), html.Span(".")],
                             "critico", "La app no encuentra sus datos"), className="aviso-global")


app.layout = html.Div([
    dcc.Location(id="url"),
    barra_superior(),
    html.Main([aviso_datos(), dash.page_container], className="contenido", id="contenido"),
], className="app")

# La pantalla activa lleva aria-current="page" (dcc.Link no lo admite como propiedad: se pone en el navegador) y la clase
# --activo de respaldo (la píldora negra).
app.clientside_callback(
    r"""function (ruta) {
        var rutas = %s, clase = %s;
        var actual = (ruta || '/').replace(/\/+$/, '') || '/';
        return rutas.map(function (r, i) {
            var a = document.getElementById('nav-' + i);
            if (a) {
                if (r === actual) {
                    a.setAttribute('aria-current', 'page');
                    var lista = a.closest('ul');   /* en el teléfono, la pestaña activa queda a la vista */
                    if (lista) { lista.scrollLeft = a.parentNode.offsetLeft - (lista.clientWidth - a.offsetWidth) / 2; }
                } else { a.removeAttribute('aria-current'); }
            }
            return r === actual ? clase + ' ' + clase + '--activo' : clase;
        });
    }""" % (json.dumps([r for r, *_ in NAV]), json.dumps(CLASE_ENLACE)),
    [Output(f"nav-{i}", "className") for i in range(len(NAV))], Input("url", "pathname"))


# --- La app HTML del proyecto y el informe, servidos desde la carpeta del proyecto (si está al lado) -------------------
WEB = {".html", ".js", ".css", ".json", ".png", ".jpg", ".jpeg", ".svg", ".webp", ".gif", ".ico", ".woff", ".woff2", ".ttf",
       ".otf", ".pdf", ".pbf", ".mvt", ".glb", ".gltf", ".bin", ".map", ".md"}


def carpeta_proyecto():
    """Carpeta que tiene app.html: la variable SOBUSA_PROYECTO, la carpeta de la entrega (..), su subcarpeta app_sobusa
    (así viene en el ZIP de la entrega) o la raíz del proyecto (../..)."""
    cands = [os.environ.get("SOBUSA_PROYECTO"), AQUI.parent, AQUI.parent / "app_sobusa", AQUI.parent.parent]
    for c in cands:
        if c and (Path(c) / "app.html").is_file():
            return Path(c).resolve()
    return None


# Documentos de la entrega final que están junto a dash_app (solo estos nombres se sirven)
DOCS_ENTREGA = {"Informe_tecnico_Sobusa.pdf", "entrega_final.html"}


@server.route("/entrega/<nombre>")
def servir_entrega(nombre):
    if nombre not in DOCS_ENTREGA or not (AQUI.parent / nombre).is_file():
        flask.abort(404)
    return flask.send_from_directory(AQUI.parent, nombre)


@server.route("/proyecto/<path:ruta>")
def servir_proyecto(ruta):
    raiz = carpeta_proyecto()
    p = Path(ruta)
    if raiz is None or p.suffix.lower() not in WEB or any(parte.startswith(".") for parte in p.parts):
        flask.abort(404)
    if p.parts and p.parts[0].lower() in {"datos", "credenciales.py", "info.txt"}:
        flask.abort(404)
    if p.suffix.lower() == ".md":
        return flask.send_from_directory(raiz, ruta, mimetype="text/plain; charset=utf-8")
    return flask.send_from_directory(raiz, ruta)


if __name__ == "__main__":
    puerto = int(os.environ.get("PORT", "8050"))
    print(f"{TITULO}: abre http://127.0.0.1:{puerto} en el navegador (Ctrl+C para detener).")
    app.run(host="127.0.0.1", port=puerto, debug=False)
