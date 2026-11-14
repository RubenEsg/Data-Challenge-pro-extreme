"""Anexos: ¿Qué más hay, aparte de este tablero? El tablero es la entrada única: lo importante está en sus pestañas. Aquí va
el material de apoyo, que no hace falta abrir para entender la propuesta: arriba la entrega final (el informe técnico y el
cuaderno) y qué es cada cosa; debajo, la misma propuesta sin conexión (app.html, con la consola de despacho y la vista 3D)
y sus páginas sueltas; al final, los documentos del proyecto. Solo se lista lo que se encuentra junto a esta carpeta, y los
conteos salen de lo que se encuentra (DISENO.md §6.12). La ruta antigua, /enlaces, lleva aquí."""
import os
from pathlib import Path

import dash
from dash import html

import datos_app as D
import ui

dash.register_page(__name__, path="/anexos", redirect_from=["/enlaces"], name="Anexos", order=10,
                   title="Anexos · Sobusa Despacho")

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
    ("simulador_ahorro.html", "Simulador de ahorro", "resultado", "Costos, conductores y el saldo del plan en sus dos casos, por mes y por día."),
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
    """Lo importante está en las pestañas de este tablero; aquí, qué material de apoyo se encontró junto a la carpeta."""
    partes = []
    if entrega:
        partes += ["el informe técnico", "el cuaderno"]
    if raiz:
        partes.append("la app sin conexión" + (f" con {_letras(n_paginas)} página{'s' if n_paginas != 1 else ''} "
                                                 f"suelta{'s' if n_paginas != 1 else ''}" if n_paginas else ""))
    base = "Todo lo importante está en las pestañas de este tablero."
    if not partes:
        return f"{base} El material de apoyo no está junto a esta carpeta."
    texto = partes[0] if len(partes) == 1 else ", ".join(partes[:-1]) + " y " + partes[-1]
    return f"{base} Aquí está el material de apoyo ({texto}); no hace falta abrirlo para entender la propuesta."


def _app_completa(raiz):
    """Tarjeta: la app sin conexión, con el botón para abrirla y la ruta del archivo. Es apoyo: el botón va en blanco."""
    rel = os.path.relpath(raiz / "app.html", AQUI).replace(os.sep, "/")
    n_pantallas = len(D.cifras_app().get("pantallas", {}))
    return ui.tarjeta([
        ui.parrafo(f"Las {_letras(n_pantallas)} pantallas del proyecto con todas las cifras y su fuente, la consola de despacho y "
                   "la vista 3D, con resultados ya calculados. Funciona sin internet y sin instalar nada: se abre con doble clic "
                   "sobre app.html. Sirve para revisar el proyecto sin correr el tablero."),
        html.Div([ui.boton("Abrir la app sin conexión", href="/proyecto/app.html", tipo="secundario", icono="externo", externo=True),
                  ui.nota(["Archivo: ", html.Code(rel)])], className="botonera"),
    ], titulo="La app sin conexión", subtitulo="Sobusa Despacho (app.html): la misma propuesta, con la fuente de cada cifra.",
        id="enlaces-app")


def _entrega(entrega):
    """Tarjeta angosta: el informe técnico y el cuaderno ejecutado, uno por línea (la primera, píldora negra)."""
    return ui.tarjeta(html.Div(
        [ui.boton(n, href=f"/entrega/{a}", tipo="primario" if i == 0 else "secundario", icono="externo", externo=True)
         for i, (a, n) in enumerate(entrega)], className="botonera"),
        titulo="La entrega final", subtitulo="El informe técnico y el cuaderno ejecutado, junto a esta carpeta.", id="enlaces-entrega")


def _que_hace():
    return ui.tarjeta([
        ui.parrafo([html.Strong("Este tablero: "), "es la entrada. Calcula en vivo (el optimizador se resuelve con CBC cada vez "
                    "que cambia un parámetro) y lee la API del reto. En Inicio están la propuesta, lo que se ahorra, lo que se "
                    "juega en pasajes y el piloto que lo mide."]),
        ui.parrafo([html.Strong("El informe técnico y el cuaderno: "), "la versión académica, con el método y cada cifra comprobada."]),
        ui.parrafo([html.Strong("La app sin conexión (app.html): "), "lo mismo con resultados ya calculados, para abrir con doble "
                    "clic. No trae nada que cambie la propuesta."]),
    ], titulo="Qué es cada cosa", id="enlaces-que-hace")


def layout(**_):
    raiz = _proyecto()
    entrega = [(a, n) for a, n in ENTREGA if (AQUI.parent / a).is_file()]
    pags = [p for p in PAGINAS if raiz and (raiz / p[0]).is_file()]
    docs = [(r, n) for r, n in INFORMES if raiz and (raiz / r).is_file()]

    # Fila 1: la entrega final (el informe técnico y el cuaderno) y qué es cada cosa
    fila1 = ([_entrega(entrega)] if entrega else []) + [_que_hace()]
    # h2 solo para lectores de pantalla: las tarjetas llevan h3 y así no se salta de h1 a h3
    bloques = [html.H2("La entrega final y qué es cada cosa", className="oculto"),
               ui.rejilla(fila1, "1-1", id="enlaces-tablero")]

    # La misma propuesta sin conexión: la app y sus páginas sueltas (o el aviso de que no está al lado)
    sin_conexion = [_app_completa(raiz)] if raiz else [ui.aviso(
        ["No encontré app.html junto a esta carpeta. Si tienes el proyecto completo, ábrelo con doble clic en ",
         html.Code("app.html"), " o indica su carpeta con la variable ", html.Code("SOBUSA_PROYECTO"), " antes de correr el tablero."],
        "atencion", "La app sin conexión no está al lado")]
    if pags:
        # Dos por fila (una en el teléfono): con cuatro por fila, «Consola de despacho» y «Simulador de ahorro» se partían
        sin_conexion.append(ui.rejilla([
            ui.destino(f"/proyecto/{arch}", pantalla, nombre, texto, externo=True)
            for arch, nombre, pantalla, texto in pags], "1-1", id="enlaces-paginas"))
    bloques.append(ui.seccion("La misma propuesta, sin conexión", sin_conexion,
                              "Partes de la app sin conexión; se abren aparte, en otra pestaña y con su propio estilo."))

    # Al final, los documentos del proyecto que se encontraron
    if docs:
        # Cada documento en píldora blanca (el mismo estilo de enlace que la entrega final) con su ruta al lado
        bloques.append(ui.tarjeta(
            [html.Div([ui.boton(n, href=f"/proyecto/{r}", tipo="secundario", icono="externo", externo=True),
                       ui.nota(html.Code(r, className="ruta"))], className="botonera") for r, n in docs],
            titulo="Documentos del proyecto", subtitulo="Los que se encontraron junto a esta carpeta.", id="enlaces-informe"))

    return ui.pantalla([
        ui.encabezado("¿Qué más hay, aparte de este tablero?", _subtitulo(raiz, len(pags), entrega), pantalla="enlaces"),
        *bloques,
    ])
