"""Enlaces: ¿Dónde está el resto del proyecto? Un tablero de tarjetas como la referencia (DISENO.md): la app completa
(app.html, con la consola de despacho y la vista 3D) y la entrega final arriba; las páginas sueltas; el informe y qué hace
cada una abajo. Solo se lista lo que se encuentra junto a esta carpeta, y los conteos salen de lo que se encuentra
(DISENO.md §6.12)."""
import os
from pathlib import Path

import dash
from dash import html

import datos_app as D
import ui

dash.register_page(__name__, path="/enlaces", name="Enlaces", order=5, title="Enlaces · Sobusa Despacho")

AQUI = Path(__file__).resolve().parent.parent

# Documentos de la entrega final, junto a dash_app (los sirve /entrega/ en app.py)
ENTREGA = [
    ("Informe_tecnico_Sobusa.pdf", "Informe técnico final (PDF)"),
    ("entrega_final.html", "Cuaderno final ejecutado (HTML)"),
]
# Documentos que se buscan en la carpeta del proyecto, en este orden
INFORMES = [
    ("documentos/metodologia/main.pdf", "Metodología del Entregable 2 (PDF)"),
    ("documentos/informe_resultados.md", "Informe de resultados (texto)"),
]
# Páginas sueltas: archivo, nombre, pantalla de la app cuyo icono lleva la tarjeta (DISENO.md §2.7) y qué muestra
PAGINAS = [
    ("consola_despacho.html", "Consola de despacho", "despacho", "Qué hace el despachador en cada momento del día, con el plan y la reoptimización."),
    ("vista_3d.html", "Vista 3D", "ciudad", "Los buses en las calles de Barranquilla, hora a hora, con el plan y con lo que pasó."),
    ("planificador.html", "Planificador", "horario", "El horario recomendado por ruta y tipo de día, precalculado."),
    ("simulador_ahorro.html", "Simulador de ahorro", "resultado", "Costos, conductores y saldo del plan, por mes y por día."),
]
_LETRAS = ["ninguna", "una", "dos", "tres", "cuatro", "cinco", "seis", "siete", "ocho", "nueve", "diez"]


def _letras(n):
    """Un conteo en palabras (femenino: «cuatro páginas»), o en cifras si pasa de diez."""
    return _LETRAS[n] if 0 <= n < len(_LETRAS) else ui.num(n)


def _proyecto():
    for c in [os.environ.get("SOBUSA_PROYECTO"), AQUI.parent, AQUI.parent / "app_sobusa", AQUI.parent.parent]:
        if c and (Path(c) / "app.html").is_file():
            return Path(c).resolve()
    return None


def _subtitulo(raiz, n_paginas, entrega):
    partes = []
    if raiz:
        partes.append("la app completa")
        if n_paginas:
            partes.append(f"{_letras(n_paginas)} página{'s' if n_paginas != 1 else ''} suelta{'s' if n_paginas != 1 else ''}")
    if entrega:
        partes.append("el informe técnico")
    if not partes:
        return "Este laboratorio muestra el modelo funcionando; el resto del proyecto no está junto a esta carpeta."
    texto = partes[0] if len(partes) == 1 else ", ".join(partes[:-1]) + " y " + partes[-1]
    return f"En {texto}. Este laboratorio muestra el modelo funcionando; ahí está el proyecto entero."


def _app_completa(raiz):
    """Tarjeta ancha: la app completa, con la píldora negra para abrirla y la ruta del archivo en el «…»."""
    rel = os.path.relpath(raiz / "app.html", AQUI).replace(os.sep, "/")
    n_pantallas = len(D.cifras_app().get("pantallas", {}))
    return ui.tarjeta([
        ui.parrafo(f"Las {_letras(n_pantallas)} pantallas del proyecto con todas las cifras y su fuente, la consola de despacho y "
                   "la vista 3D. Muestra resultados precalculados y funciona sin internet: ábrela con doble clic sobre app.html."),
        html.Div([ui.boton("Abrir la app completa", href="/proyecto/app.html", tipo="primario", icono="externo", externo=True),
                  ui.nota(["Archivo: ", html.Code(rel)])], className="botonera"),
    ], titulo="La app completa", subtitulo="Sobusa Despacho (app.html): el proyecto entero, con su fuente en cada cifra.",
        id="enlaces-app")


def _entrega(entrega):
    """Tarjeta angosta: el informe técnico y el cuaderno ejecutado, uno por línea (la primera, píldora negra)."""
    return ui.tarjeta(html.Div(
        [ui.boton(n, href=f"/entrega/{a}", tipo="primario" if i == 0 else "secundario", icono="externo", externo=True)
         for i, (a, n) in enumerate(entrega)], className="botonera"),
        titulo="La entrega final", subtitulo="El informe técnico y el cuaderno ejecutado, junto a esta carpeta.", id="enlaces-entrega")


def _que_hace():
    return ui.tarjeta([
        ui.parrafo([html.Strong("Este laboratorio (Dash): "), "calcula en vivo. El optimizador se resuelve con CBC cada vez que "
                    "cambia un parámetro, y el pronóstico se puede cambiar de modelo."]),
        ui.parrafo([html.Strong("La app completa (app.html): "), "muestra los resultados ya calculados de todo el proyecto, con su "
                    "fuente, y se abre sin instalar nada."]),
    ], titulo="Qué hace cada una", id="enlaces-que-hace")


def layout(**_):
    raiz = _proyecto()
    entrega = [(a, n) for a, n in ENTREGA if (AQUI.parent / a).is_file()]
    pags = [p for p in PAGINAS if raiz and (raiz / p[0]).is_file()]
    docs = [(r, n) for r, n in INFORMES if raiz and (raiz / r).is_file()]

    # Fila 1: la app completa (o el aviso de que no está) y la entrega final
    fila1 = [_app_completa(raiz)] if raiz else [ui.aviso(
        ["No encontré app.html junto a esta carpeta. Si tienes el proyecto completo, ábrelo con doble clic en ",
         html.Code("app.html"), " o indica su carpeta con la variable ", html.Code("SOBUSA_PROYECTO"), " antes de correr la app."],
        "atencion", "La app completa no está al lado")]
    if entrega:
        fila1.append(_entrega(entrega))
    # h2 solo para lectores de pantalla: las tarjetas llevan h3 y así no se salta de h1 a h3
    bloques = [html.H2("La app completa y la entrega final", className="oculto"),
               ui.rejilla(fila1, "2-1" if len(fila1) == 2 else "1-1", id="enlaces-tablero")]

    if pags:
        # Dos por fila (una en el teléfono): con cuatro por fila, «Consola de despacho» y «Simulador de ahorro» se partían
        bloques.append(ui.seccion("Las páginas sueltas", [ui.rejilla([
            ui.destino(f"/proyecto/{arch}", pantalla, nombre, texto, externo=True)
            for arch, nombre, pantalla, texto in pags], "1-1", id="enlaces-paginas")],
            "Se abren aparte, en otra pestaña y con su propio estilo."))

    # Fila de abajo: el informe (si se encontró) y qué hace cada una
    abajo = []
    if docs:
        # Cada documento en píldora blanca (el mismo estilo de enlace que la entrega final) con su ruta al lado
        abajo.append(ui.tarjeta(
            [html.Div([ui.boton(n, href=f"/proyecto/{r}", tipo="secundario", icono="externo", externo=True),
                       ui.nota(html.Code(r, className="ruta"))], className="botonera") for r, n in docs],
            titulo="El informe", subtitulo="Documentos del proyecto que se encontraron junto a esta carpeta.", id="enlaces-informe"))
    abajo.append(_que_hace())
    bloques.append(ui.rejilla(abajo, "1-1") if len(abajo) == 2 else abajo[0])

    return ui.pantalla([
        ui.encabezado("¿Dónde está el resto del proyecto?", _subtitulo(raiz, len(pags), entrega), pantalla="enlaces"),
        *bloques,
    ])
