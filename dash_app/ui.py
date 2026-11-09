"""Piezas de interfaz del laboratorio con el estilo de la referencia que eligió el usuario (DISENO.md): la navegación arriba,
títulos enormes, tarjetas casi blancas con el botón redondo «…», cifras grandes, chips en píldora y barras rayadas.

Todo color sale de tokens.py (que lee assets/estilos.css): ROL para Plotly y var(--…) para los estilos en línea. Aquí no se
escribe ningún color ni tamaño de letra. Contenido:
  · números y fechas en es-CO (con el menos tipográfico «−»);
  · la plantilla «sobusa» de Plotly y las ayudas de los gráficos (traza con las formas rayada, foco y escalon_rayado,
    barras_foco, banda_foco, etiquetas_columnas, hover, marcas, unidad_eje, linea_cero, referencia, franja, fuente_svg);
  · los componentes del catálogo (DISENO.md §5): encabezado, arriba, rejilla, seccion, tarjeta (con «…»), bloque, mas,
    cifra, heroe, saldo, antes_despues, chip, chip_cambio, chip_valor, barra_rayas, puntos, tarjeta_insight, aviso, grafico,
    leyenda, tabla, segmentado, control, desplegable, fuentes, destino, boton, boton_redondo, casilla, deslizador, delta,
    hora_chip, pie;
  · al final, el bloque «compatibilidad» con los nombres antiguos que las páginas sin migrar todavía usan.
"""
import math

import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio
from dash import dcc, html

import tokens as T
from motor.comun import fmt, pct  # noqa: F401  (se reexportan para las páginas)
from tokens import LAVADO, ROL, TOKENS, VAR, alfa, px  # noqa: F401  (se reexportan)

TOK = TOKENS                                  # el nombre que usa DISENO.md
FUENTE = T.FUENTE_TEXTO

MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
MESES_CORTOS = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]

# Modelos en el orden fijo (selectores, fichas, gráfica de errores y tablas); el híbrido es el recomendado
ORDEN_MODELOS = ["B1", "E1", "E11", "E12"]
NOMBRE_MODELO = {"B1": "Regla manual", "E1": "Primer modelo (E1)", "E11": "Modelo final (E11)", "E12": "Híbrido (E12)"}

# Especificaciones fijas de las marcas (dataviz: marks-and-anatomy.md; DISENO.md §7)
ANCHO_LINEA = 2          # px: toda línea
ANCHO_REAL = 2.5         # px: lo que de verdad pasó
MARCADOR = 8             # px: marcadores, siempre con anillo
ANILLO = 2               # px: anillo de --superficie alrededor de un marcador
PUNTA_BARRA = 6          # px: punta redondeada de las barras (base cuadrada)
BARRA_MAX = 24           # px: grosor máximo de una barra (se fija con width en unidades de categoría)
RAYA = 9                 # px: paso del rayado diagonal de las barras (marker.pattern)
RAYA_SOLIDEZ = 0.34      # parte del paso que ocupa la raya
RAYA_LLENADO = 7         # px: paso del rayado vertical bajo un escalón (fillpattern)
MARGEN_ETIQUETAS = 56    # px: margen derecho cuando hay valores en la punta de barras horizontales

GRAF_CONFIG = {"displayModeBar": False, "responsive": True, "scrollZoom": False}


# --- Números y fechas -------------------------------------------------------------------------------------------------
def _finito(x):
    try:
        return x is not None and math.isfinite(float(x))
    except (TypeError, ValueError):
        return False


def num(x, d=0):
    """Número en es-CO con el menos tipográfico: 1.234,5 · −0,32 (los niveles van sin «+»)."""
    if not _finito(x):
        return "—"
    s = fmt(x, d)
    return "−" + s[1:] if s.startswith("-") else s


def con_signo(x, d=0):
    """Número con signo y el menos tipográfico: +1.234 / −0,32 (cambios, pasos de la cascada y saldos)."""
    if not _finito(x):
        return "—"
    return ("+" if x > 0 else "−" if x < 0 else "") + fmt(abs(x), d)


def cop(x, d=0):
    return f"{num(x, d)} COP"


def millones(x, d=1):
    return f"{num(x / 1e6, d)} M COP"


def fecha_larga(f, con_dia=True):
    f = pd.Timestamp(f)
    s = f"{f.day} de {MESES[f.month - 1]} de {f.year}"
    return f"{DIAS[f.dayofweek]} {s}" if con_dia else s


def fecha_corta(f):
    f = pd.Timestamp(f)
    return f"{f.day} {MESES_CORTOS[f.month - 1]}"


# --- Plantilla de Plotly «sobusa» (DISENO.md §7; el equivalente de app/tema_echarts.js) -------------------------------
TRANSPARENTE = alfa(ROL["superficie"], 0)


def fuente_svg(rol="tinta_2", paso="--t-xs"):
    """Fuente del texto de un gráfico (ejes, anotaciones, valor en la punta): familia de la app, un paso de la escala y un
    rol de texto («tinta», «tinta_2», «tinta_3»). Nunca el color de la serie."""
    return dict(family=FUENTE, size=px(paso), color=ROL[rol])


# Estilo de la referencia: rótulos grises (oscurecidos lo justo para 4,5:1), rejilla muy clara, sin títulos de eje, la
# etiqueta flotante en píldora blanca con borde fino y texto oscuro.
_EJE_X = dict(showgrid=False, zeroline=False, showline=True, linecolor=ROL["rejilla"], linewidth=1, ticks="", tickangle=0,
              tickfont=fuente_svg("tinta_3"), automargin=True, fixedrange=True)
_EJE_Y = dict(showgrid=True, gridcolor=ROL["rejilla"], gridwidth=1, griddash="solid", zeroline=False, showline=False, ticks="",
              tickfont=fuente_svg("tinta_3"), tickformat=",.0f", automargin=True, fixedrange=True)

pio.templates["sobusa"] = go.layout.Template(
    layout=go.Layout(
        font=fuente_svg("tinta_2"),
        paper_bgcolor=TRANSPARENTE, plot_bgcolor=TRANSPARENTE,   # la tarjeta pone --superficie
        separators=",.",                                          # coma decimal y punto de miles
        colorway=[ROL["modelo"], ROL["hoy"], ROL["real"]],        # solo por si una traza no declara su rol
        margin=dict(l=px("--e-1"), r=px("--e-4"), t=px("--e-3"), b=px("--e-1")),
        showlegend=False,                                         # la leyenda es HTML (ui.leyenda)
        hovermode="x unified",
        hoverlabel=dict(bgcolor=ROL["blanco"], bordercolor=ROL["linea"], font=fuente_svg("tinta", "--t-s"), align="left", namelength=-1),
        xaxis=_EJE_X, yaxis=_EJE_Y,
        barcornerradius=PUNTA_BARRA, bargap=0.22, bargroupgap=0.08,
        annotationdefaults=dict(font=fuente_svg("tinta_2"), showarrow=False, arrowcolor=ROL["tinta_3"], arrowwidth=1),
        shapedefaults=dict(line=dict(color=ROL["tinta_3"], width=1)),
        dragmode=False,
    ),
    data=dict(
        bar=[go.Bar(marker=dict(line=dict(width=0)), textposition="outside", cliponaxis=False, textfont=fuente_svg("tinta"))],
        scatter=[go.Scatter(line=dict(width=ANCHO_LINEA, shape="linear"),
                            marker=dict(size=MARCADOR, line=dict(width=ANILLO, color=ROL["superficie"])))],
    ),
)
pio.templates.default = "sobusa"


# --- Ayudas de los gráficos -------------------------------------------------------------------------------------------
# Forma por defecto de cada rol (DISENO.md §2.2): la intensidad del gris la decide la forma (§2.10)
_FORMA = {"real": "gruesa", "hoy": "escalon", "contexto": "linea", "modelo": "linea", "modelo_final": "trazos",
          "previsto_modelo": "punteada", "previsto_hoy": "punteada", "recorta": "linea", "oraculo": "trazos"}
FORMAS = ("barra", "foco", "rayada", "linea", "gruesa", "trazos", "punteada", "escalon", "escalon_rayado", "area", "punto")
# Tinte de cada familia: el fondo del rayado y de la banda de foco
TINTE = {"modelo": "modelo_tinte", "modelo_final": "modelo_tinte", "previsto_modelo": "modelo_tinte", "hoy": "hoy_tinte",
         "previsto_hoy": "hoy_tinte", "contexto": "hoy_tinte", "real": "hoy_tinte", "oraculo": "hoy_tinte", "recorta": "recorta_tinte"}


def tinte(rol):
    """Color del tinte de la familia de un rol (fondo del rayado): ROL["modelo_tinte"] para «modelo», etc."""
    return ROL[TINTE.get(T.RUTA_ROL.get(rol, rol), "hoy_tinte")]


def _rayado(rol, forma="/"):
    """marker.pattern del rayado de un rol: rayas del color del rol sobre su tinte. forma "" = barra sólida (la de foco)."""
    return {"shape": forma, "fgcolor": _color(rol), "bgcolor": tinte(rol), "size": RAYA, "solidity": RAYA_SOLIDEZ, "fillmode": "replace"}


def _color(rol):
    """Color de un rol (o de una ruta con su nombre de los datos)."""
    rol = T.RUTA_ROL.get(rol, rol)
    if rol not in ROL:
        raise KeyError(f"rol sin color: {rol!r} (roles: {', '.join(ROL)})")
    return ROL[rol]


def _marcador(c):
    return dict(size=MARCADOR, color=c, line=dict(width=ANILLO, color=ROL["superficie"]))


def traza(rol, forma=None, *, escalon=False, marcadores=None, ancho=None):
    """Estilo de una traza según su rol y su forma, para mezclar en go.Bar / go.Scatter con **:
    go.Bar(x=…, y=…, **ui.traza("modelo", "barra", ancho=0.34)) · go.Scatter(x=…, y=…, **ui.traza("real")).
    Formas: barra o foco (sólida: la serie en foco), rayada (rayas diagonales del color sobre su tinte: las demás de la
    familia, hoy y las referencias), linea, gruesa (2,5 px), trazos, punteada, escalon, escalon_rayado (escalón «hv» con
    relleno de rayas verticales claras, como «Retention» de la referencia), area, punto.
    El oráculo lleva marcadores de 8 px con anillo; los demás, solo si se piden."""
    c = _color(rol)
    forma = forma or _FORMA.get(rol, "linea")
    if forma not in FORMAS:
        raise ValueError(f"forma desconocida: {forma!r}")
    if forma in ("barra", "foco", "rayada"):
        d = {"marker": {"color": c, "line": {"width": 0}}}
        if forma == "rayada":
            d["marker"]["pattern"] = _rayado(rol)
        if ancho is not None:
            d["width"] = ancho
        return d
    if forma == "escalon_rayado":
        return {"mode": "lines", "line": {"color": c, "width": ANCHO_REAL, "shape": "hv"}, "fill": "tozeroy",
                "fillcolor": alfa(c, LAVADO / 2),
                "fillpattern": {"shape": "|", "fgcolor": alfa(c, 0.3), "size": RAYA_LLENADO, "solidity": 0.22, "fillmode": "overlay"}}
    if forma == "punto":
        return {"mode": "markers", "marker": _marcador(c)}
    if marcadores is None:
        marcadores = rol == "oraculo"
    linea = {"color": c, "width": ANCHO_REAL if forma == "gruesa" else ANCHO_LINEA,
             "shape": "hvh" if (escalon or forma == "escalon") else "linear"}
    if forma == "trazos":
        linea["dash"] = "dash"
    elif forma == "punteada":
        linea["dash"] = "dot"
    d = {"mode": "lines+markers" if marcadores else "lines", "line": linea}
    if marcadores:
        d["marker"] = _marcador(c)
    if forma == "area":
        d.update(fill="tozeroy", fillcolor=alfa(c, LAVADO))
    return d


def hover(nombre, valores, unidad="", d=0, signo=False, categorias=None):
    """customdata ya formateado (es-CO, «−») y su hovertemplate: «Nombre: <b>valor</b> unidad». El valor manda (dataviz).
    Con `categorias` (barras horizontales), «categoría: <b>valor</b> unidad». Uso: go.Bar(…, **ui.hover("Se ponen", u, "salidas", 1))."""
    f = con_signo if signo else num
    textos = [f(v, d) for v in valores]
    u = f" {unidad}" if unidad else ""
    if categorias is not None:
        cd = [[str(c), t] for c, t in zip(categorias, textos)]
        plantilla = ("" if not nombre else f"{nombre} · ") + "%{customdata[0]}: <b>%{customdata[1]}</b>" + u
    else:
        cd = [[t] for t in textos]
        plantilla = f"{nombre}: <b>%{{customdata[0]}}</b>{u}"
    return {"customdata": cd, "hovertemplate": plantilla + "<extra></extra>"}


def hover_texto(textos):
    """Texto al pasar el puntero ya armado por la página (una cadena por punto, con sus cifras ya formateadas)."""
    return {"customdata": [[t] for t in textos], "hovertemplate": "%{customdata[0]}<extra></extra>"}


def paso_redondo(tope, maximo_marcas=3):
    """Paso «redondo» para que un eje llegue a `tope` con pocas marcas a cada lado del cero."""
    tope = abs(tope) or 1
    for p in (1, 2, 2.5, 4, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000, 2000, 2500, 5000, 10000, 20000, 25000, 50000):
        if math.ceil(tope / p) <= maximo_marcas:
            return p
    return 10 ** math.ceil(math.log10(tope))


def ancho_barra(n_categorias, largo_eje_px=None):
    """Ancho de barra (en unidades de categoría, el `width` de go.Bar) para que no pase de 24 px ni en el lienzo más ancho:
    el contenido llega como mucho a --ancho-contenido menos el relleno del gráfico. Con 17 horas da ≈ 0,35. Para barras
    horizontales, `largo_eje_px` es el alto del lienzo (240 en «bajo»)."""
    largo = largo_eje_px or (px("--ancho-contenido") - 2 * px("--e-5"))
    return round(min(0.8, BARRA_MAX / (largo / max(n_categorias, 1))), 3)


def marcas(lo, hi, paso, d=None, signo=False):
    """(tickvals, ticktext) de lo a hi cada `paso`, en es-CO; con signo=True los positivos llevan «+» (ejes de cambios)."""
    v = math.floor(lo / paso) * paso
    vals = []
    while v <= hi + 1e-9:
        vals.append(round(v, 6))
        v += paso
    def texto(t):
        dd = d if d is not None else (0 if float(t).is_integer() else 1)
        return "0" if t == 0 else (con_signo(t, dd) if signo else num(t, dd))
    return vals, [texto(t) for t in vals]


def unidad_eje(fig, texto):
    """La unidad del eje de valores en horizontal, arriba a la izquierda (no hay títulos de eje girados)."""
    fig.add_annotation(text=texto, xref="paper", yref="paper", x=0, y=1, xanchor="left", yanchor="bottom", yshift=px("--e-1"),
                       showarrow=False, font=fuente_svg("tinta_3"))
    fig.update_layout(margin_t=px("--e-6"))
    return fig


def linea_cero(fig, eje="y"):
    """Línea de cero en --tinta-3, 1 px: solo donde importa el signo."""
    linea = dict(color=ROL["cero"], width=1)
    (fig.add_hline(y=0, line=linea) if eje == "y" else fig.add_vline(x=0, line=linea))
    return fig


def referencia(fig, x=None, y=None, texto=None):
    """Línea de referencia sólida de 1 px en --tinta-3 con su rótulo en --tinta-2 (p. ej. el β central). Nunca a trazos."""
    linea = dict(color=ROL["referencia"], width=1)
    if x is not None:
        fig.add_vline(x=x, line=linea)
        if texto:
            fig.add_annotation(x=x, y=1, yref="paper", text=texto, yanchor="bottom", showarrow=False, font=fuente_svg("tinta_2"))
    if y is not None:
        fig.add_hline(y=y, line=linea)
        if texto:
            fig.add_annotation(x=1, xref="paper", y=y, text=texto, xanchor="right", yanchor="bottom", showarrow=False, font=fuente_svg("tinta_2"))
    return fig


def franja(fig, x0, x1):
    """Franja de rango o de selección (--franja: el acento al 8 %), detrás de las marcas."""
    fig.add_vrect(x0=x0, x1=x1, fillcolor=ROL["franja"], line_width=0, layer="below")
    return fig


def barras_foco(rol, categorias, foco=None, ancho=None):
    """Barras de una serie con una columna en foco (sólida) y las demás rayadas, como «Payments» de la referencia:
    go.Bar(x=cats, y=vals, **ui.barras_foco("modelo", cats, foco="Hora pico")). Sin foco, todas rayadas."""
    formas = ["" if (foco is not None and c == foco) else "/" for c in categorias]
    d = {"marker": {"color": _color(rol), "line": {"width": 0}, "pattern": dict(_rayado(rol), shape=formas)}}
    if ancho is not None:
        d["width"] = ancho
    return d


def banda_foco(fig, x, categorias=None, medio_ancho=0.5):
    """Banda vertical azul clara detrás de la columna en foco (la de «Successful Payments»). `x` es la categoría (con
    `categorias`, la lista del eje) o la posición numérica."""
    i = categorias.index(x) if categorias is not None else x
    fig.add_vrect(x0=i - medio_ancho, x1=i + medio_ancho, fillcolor=ROL["franja"], line_width=0, layer="below")
    return fig


def etiquetas_columnas(fig, categorias, textos, foco=None, rotulos=None):
    """Rótulo y valor encima de cada columna, arriba del lienzo (gris; el de foco en tinta), como en «Payments».
    `textos` ya formateados (ui.num); `rotulos`, una línea opcional encima del valor."""
    for i, (c, t) in enumerate(zip(categorias, textos)):
        rol = "tinta" if c == foco else "tinta_3"
        texto = t if not rotulos else f"{rotulos[i]}<br>{t}"
        fig.add_annotation(x=c, y=1, yref="paper", yanchor="bottom", yshift=px("--e-1"), text=texto, showarrow=False,
                           align="center", font=fuente_svg(rol, "--t-s"))
    fig.update_layout(margin_t=px("--e-8") if rotulos else px("--e-6"))
    return fig


def figura_vacia(texto="Sin datos"):
    fig = go.Figure()
    fig.add_annotation(text=texto, showarrow=False, x=0.5, y=0.5, xref="paper", yref="paper", font=fuente_svg("tinta_3", "--t-s"))
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)
    return fig


# --- Piezas básicas ---------------------------------------------------------------------------------------------------
def _lista(x):
    if x is None:
        return []
    return [h for h in x if h is not None] if isinstance(x, (list, tuple)) else [x]


def _kw(**pares):
    """Solo las propiedades con valor (Dash no siempre acepta None)."""
    return {k: v for k, v in pares.items() if v is not None}


def _clases(*cs):
    return " ".join(c for c in cs if c)


def icono(nombre, clase=""):
    """Icono de la familia de la app (assets/iconos), del color del texto."""
    return html.Span(className=_clases("glifo", f"i-{nombre}", clase), **{"aria-hidden": "true"})


_glifo = icono   # para las funciones con un parámetro llamado «icono»

# Pantalla → icono de su cuadro. El color sale de --pantalla-<id> (DISENO.md §2.7)
PANTALLA_ICONO = {"inicio": "inicio", "pronostico": "demanda", "horario": "horario", "modelo": "modelo", "resultado": "resultado",
                  "enlaces": "externo", "demanda": "demanda", "despacho": "despacho", "ciudad": "ciudad", "piloto": "piloto",
                  "metodo": "metodo"}
_COLORES = {"turquesa", "azul", "indigo", "naranja", "coral", "cian", "verde", "morado", "gris"}


def cuadro(pantalla, icono=None, clase=""):
    """Cuadro de color de una pantalla (28 px; 32 px con clase «cuadro-color--cabecera»). `pantalla` es su id (inicio,
    pronostico, horario, modelo, resultado, enlaces, o despacho, ciudad… para las páginas sueltas de Enlaces)."""
    if pantalla in _COLORES:   # compatibilidad: cuadro(color, icono, clase)
        estilo = {"--cuadro": f"var(--color-{pantalla})"}
    else:
        estilo = {"--cuadro": f"var(--pantalla-{pantalla})"}
        icono = icono or PANTALLA_ICONO.get(pantalla, "inicio")
    return html.Span(_glifo(icono), className=_clases("cuadro-color", clase), style=estilo, **{"aria-hidden": "true"})


# --- Estructura de la pantalla ----------------------------------------------------------------------------------------
def pantalla(hijos, clase=""):
    """El contenedor de una pantalla: cabecera (o el grupo de arriba) y sus secciones, con 64 px entre ellas."""
    return html.Div(_lista(hijos), className=_clases("pantalla", clase))


def arriba(cabecera_, controles=None, respuesta=None):
    """Grupo de arriba: en una fila, la cabecera (título enorme + subtítulo) a la izquierda y los controles de la pantalla a
    la derecha en un grupo de píldoras (debajo si no caben) → la respuesta (24 px). Los 48 px empiezan después."""
    fila = [cabecera_] + ([fila_controles(controles)] if controles is not None else [])
    return html.Div([html.Div(fila, className="encabezado")] + _lista(respuesta), className="pantalla__arriba")


def encabezado(titulo, subtitulo=None, controles=None, respuesta=None, pantalla=None):
    """Encabezado de pantalla de la referencia («Overview» + controles a la derecha): h1 enorme en peso normal → subtítulo
    gris que responde con la cifra; `controles` (lista de segmentados, selector de fecha…) van en la píldora de la derecha;
    `respuesta` (fichas, avisos) debajo. ui.encabezado("¿Qué gana Sobusa?", "El plan…", [sel_plan])."""
    return arriba(cabecera(pantalla or "inicio", titulo, subtitulo), controles, respuesta)


def rejilla(hijos, columnas="2-1", clase="", id=None):
    """Rejilla de tarjetas del tablero: «2-1» (ancha + angosta, como Payments + Gross Volume), «1-2», «1-1» o «3». En el
    teléfono, una columna."""
    return html.Div(_lista(hijos), className=_clases("rejilla", f"rejilla--{columnas}", clase), **_kw(id=id))


def cabecera(pantalla, pregunta, subtitulo=None, *resto, **_):
    """Cabecera de pantalla: cuadro de 32 px con el color de la pantalla → la pregunta (h1) → el subtítulo que la responde
    con la cifra. Una por pantalla y sin controles."""
    if pantalla in _COLORES:   # compatibilidad: cabecera(color, icono, titulo, subtitulo)
        caja = cuadro(pantalla, pregunta, "cuadro-color--cabecera")
        pregunta, subtitulo = subtitulo, (resto[0] if resto else None)
    else:
        caja = cuadro(pantalla, None, "cuadro-color--cabecera")
    texto = [caja, html.H1(pregunta, className="cabecera__pregunta")]
    if subtitulo is not None:
        texto.append(html.P(subtitulo, className="cabecera__subtitulo"))
    return html.Header(html.Div(texto, className="cabecera__texto"), className="cabecera")


def fila_controles(hijos):
    """Fila de controles sin tarjeta, alineada a la izquierda, encima de lo que cambia (en el teléfono, uno por línea)."""
    return html.Div(_lista(hijos), className="controles")


def seccion(titulo, hijos, subtitulo=None, fuentes=None, controles=None, id=None, intro=None):
    """Sección: h2 con el mensaje → subtítulo debajo → intro → fila de controles (lo que cambia esa parte) → cuerpo (24 px)
    → un pie de fuentes. `fuentes` es una lista de rutas o un componente."""
    cab = [html.H2(titulo, className="seccion__titulo")]
    if subtitulo is not None:
        cab.append(html.P(subtitulo, className="seccion__sub"))
    partes = [html.Div(cab, className="seccion__cab")]
    if intro is not None:
        partes.append(html.P(intro, className="seccion__intro"))
    if controles is not None:
        partes.append(fila_controles(controles))
    partes += _lista(hijos)
    if fuentes:
        partes.append(globals()["fuentes"](fuentes) if isinstance(fuentes, (list, tuple, str)) else fuentes)
    return html.Section(partes, className="seccion", **_kw(id=id))


def mas(detalles=None, fuentes_=None, titulo="Ver los datos", id=None, clase=""):
    """Botón redondo «…» de la esquina de una tarjeta: abre (details/summary, sin callbacks) un panel flotante con
    `detalles` (la tabla gemela, una nota) y el pie de `fuentes_`. El texto «Ver los datos» queda para lectores de pantalla.
    ui.grafico ya lo trae (con su tabla y `fuentes=[…]`); ui.tarjeta lo pone si recibe detalles= o fuentes=."""
    cuerpo = [html.P(titulo, className="mas__titulo")] + _lista(detalles)
    if fuentes_:
        cuerpo.append(globals()["fuentes"](fuentes_) if isinstance(fuentes_, (list, tuple, str)) else fuentes_)
    return html.Details([html.Summary([_glifo("puntos"), html.Span(titulo, className="oculto")], title=f"{titulo} y las fuentes"),
                         html.Div(cuerpo, className="mas__panel")], className=_clases("mas", clase), **_kw(id=id))


def tarjeta(hijos=None, titulo=None, subtitulo=None, clase="", id=None, detalles=None, fuentes=None, cuerpo=None, **compat):
    """Tarjeta de la referencia (casi blanca, radio 26, borde fino, sombra difusa): cabecera con el título (24 px, peso
    normal) y, si hay `detalles` o `fuentes`, el botón redondo «…» a la derecha que los abre → el cuerpo. Lo anidado va en
    blanco con borde fino. Uso: ui.tarjeta(cuerpo, titulo="Por ruta", detalles=ui.tabla(…), fuentes=["datos/x.json"]).
    (También ui.bloque(titulo, cuerpo, detalles=…).) Un gráfico va en ui.grafico."""
    partes = []
    hay_mas = detalles is not None or bool(fuentes)
    if titulo is not None or hay_mas:
        t = [html.H3(titulo, className="tarjeta__titulo")] if titulo is not None else []
        if subtitulo is not None:
            t.append(html.P(subtitulo, className="tarjeta__sub"))
        cab = [html.Div(t, className="tarjeta__textos")] + ([mas(detalles, fuentes)] if hay_mas else [])
        partes.append(html.Div(cab, className="tarjeta__cab"))
    if compat.get("derecha") is not None:   # compatibilidad: el control va debajo del título, a la izquierda
        partes.append(fila_controles(compat["derecha"]))
    partes += _lista(cuerpo if hijos is None else hijos)
    return html.Div(partes, className=_clases("tarjeta", clase), **_kw(id=id))


def bloque(titulo, cuerpo, detalles=None, subtitulo=None, fuentes=None, clase="", id=None):
    """La tarjeta con el orden de la referencia: título → cuerpo, y el «…» con `detalles` y `fuentes`."""
    return tarjeta(cuerpo, titulo=titulo, subtitulo=subtitulo, clase=clase, id=id, detalles=detalles, fuentes=fuentes)


def parrafo(texto, clase=""):
    return html.P(texto, className=_clases("parrafo", clase))


def nota(texto, clase=""):
    """Nota de una línea (--t-s, --tinta-3)."""
    return html.P(texto, className=_clases("nota", clase))


def pie(hijos):
    """Pie de pantalla (solo en Inicio): de dónde salen los datos y el equipo."""
    return html.Footer(_lista(hijos), className="pie")


# --- Cifras -----------------------------------------------------------------------------------------------------------
def icono_cambio(v):
    """Flecha abajo, flecha arriba o igual según el signo (la dirección nunca va solo en el color)."""
    return "flecha-abajo" if v < 0 else "flecha-arriba" if v > 0 else "igual"


def cifras(fichas, clase="", id=None):
    """Fila de fichas (auto-fit, minmax(210px, 1fr); como mucho 4 por fila)."""
    return html.Div(_lista(fichas), className=_clases("cifras", clase), **_kw(id=id))


def cifra(etiqueta, valor, unidad=None, variacion=None, tono=None, nota=None, *, flecha=None, chip=None, hoy=False, mini=False,
          clase="", id=None, **compat):
    """Ficha de cifra: etiqueta → valor con unidad → variación de una línea (flecha + texto; color de estado solo si el
    sentido es inequívoco: tono «bien» o «mal») → nota. `flecha` es el número cuyo signo elige la flecha. `chip` va junto a
    la etiqueta («Recomendado para producción»). `hoy=True` pone el valor en --tinta-2. Sin punto de color ni ruta de archivo."""
    cab = [html.Span(etiqueta, className="cifra__etiqueta")]
    if chip is not None:
        cab.append(chip)
    valor_ = [html.Span(valor, className="cifra__numero")] + ([html.Span(unidad, className="cifra__unidad")] if unidad else [])
    hijos = [html.Div(cab, className="cifra__cab"), html.P(valor_, className="cifra__valor")]
    if variacion is not None:
        tono = "mal" if tono == "critico" else tono
        ic = icono_cambio(flecha) if flecha is not None else ({"bien": "bien", "mal": "alerta"}.get(tono) if tono else None)
        hijos.append(html.P(([_glifo(ic, "glifo--s")] if ic else []) + [html.Span(variacion)],
                            className=_clases("cifra__variacion", tono and f"cifra__variacion--{tono}")))
    if nota is not None:
        hijos.append(html.P(nota, className="cifra__nota"))
    if compat.get("fuente"):   # compatibilidad: la ruta pasa al pie de fuentes de la sección al migrar
        hijos.append(html.P(compat["fuente"], className="cifra__fuente", title=compat["fuente"]))
    return html.Div(hijos, className=_clases("cifra", hoy and "cifra--hoy", mini and "cifra--mini", clase), **_kw(id=id))


def saldo(titulo, valor, definicion=None, unidad="M COP al año", d=0, palabras=("saldo positivo", "saldo negativo")):
    """Un saldo: cifra con su signo (--t-xl) + chip de estado con icono y palabra + definición de una línea."""
    estado = chip(palabras[0], "bien") if valor > 0 else chip(palabras[1], "critico") if valor < 0 else chip("saldo nulo")
    hijos = [html.P(titulo, className="saldo__titulo"),
             html.P([html.Span(con_signo(valor, d)), html.Span(unidad, className="saldo__unidad")], className="saldo__valor"),
             estado]
    if definicion:
        hijos.append(html.P(definicion, className="saldo__texto"))
    return html.Div(hijos, className="saldo")


def heroe(etiqueta, valor, unidad, texto, saldos, lado=None, pie=None, id=None):
    """Cifra protagonista (una por pantalla): etiqueta → valor a --t-hero (el signo del mismo tamaño) con su unidad → una
    línea → los dos saldos → la columna de la segunda respuesta (a la derecha del valor en escritorio, debajo de los saldos
    en el teléfono) → el pie (β y el enlace). Ese es también el orden del DOM: el ahorro nunca va sin sus saldos."""
    principal = [html.P(etiqueta, className="heroe__etiqueta"),
                 html.P([html.Span(valor, className="heroe__numero"), html.Span(unidad, className="heroe__unidad")], className="heroe__valor")]
    for t in _lista(texto):
        principal.append(html.P(t, className="heroe__texto") if isinstance(t, str) else t)
    partes = [html.Div(principal, className="heroe__principal"), html.Div(_lista(saldos), className="saldos")]
    if lado is not None:
        partes.append(html.Div(_lista(lado), className="heroe__lado"))
    if pie is not None:
        partes.append(html.Div(_lista(pie), className="heroe__pie"))
    return html.Div(partes, className="heroe cifra--hero", **_kw(id=id))


def antes_despues(etiqueta, hoy, plan, cambio=None, nota=None, plan_rotulo="Con el plan", hoy_rotulo="Hoy", clase=""):
    """Ficha antes → después: etiqueta (qué, unidad, periodo) → «Hoy» en --tinta-2 → «Con el plan» → chip de cambio → nota.
    Para niveles comparados; nunca para flujos de dinero (esos van en el héroe o en los saldos)."""
    filas = html.Dl([
        html.Div([html.Dt(hoy_rotulo), html.Dd(hoy, className="cambio__hoy")], className="cambio__fila"),
        html.Div([html.Dt(plan_rotulo), html.Dd(plan, className="cambio__plan")], className="cambio__fila"),
    ], className="cambio__pares")
    hijos = [html.P(etiqueta, className="cambio__etiqueta"), filas]
    if cambio is not None:
        hijos.append(html.Div(cambio, className="cambio__chip"))
    if nota is not None:
        hijos.append(html.P(nota, className="cambio__nota"))
    return html.Div(hijos, className=_clases("cambio", clase))


def cambios(fichas, clase=""):
    """Rejilla de fichas antes → después (auto-fit, minmax(min(100%, 280px), 1fr))."""
    return html.Div(_lista(fichas), className=_clases("cambios", clase))


# --- Chips y avisos ---------------------------------------------------------------------------------------------------
_ICONO_ESTADO = {"bien": "bien", "atencion": "alerta", "critico": "alerta"}


def chip(texto, tipo=None, icono=None, **_compat):
    """Chip de 26 px: neutro (borde --linea) o de estado (bien, atencion, critico: siempre con icono y palabra) o «acento»
    («Recomendado para producción»). Nunca para marcar «mejor» (eso es .tabla__mejor)."""
    tipo = None if tipo == "neutro" else tipo   # compatibilidad: «neutro» es el chip sin variante
    if icono is None and isinstance(texto, str):
        icono = _ICONO_ESTADO.get(tipo)
    partes = ([_glifo(icono, "glifo--s")] if icono else []) + list(_lista(texto))
    return html.Span(partes, className=_clases("chip", tipo and f"chip--{tipo}"))


def triangulo(valor, tono=None):
    """▲ / ▼ / = según el signo de `valor` (un triángulo dibujado, sin texto): verde o rojo solo con `tono` «bien» o
    «critico» (cuando el sentido es inequívoco); si no, gris."""
    direccion = "arriba" if valor > 0 else "abajo" if valor < 0 else "igual"
    tono = {"mal": "critico"}.get(tono, tono)
    return html.Span(className=_clases("triangulo", f"triangulo--{direccion}", tono in ("bien", "critico") and f"triangulo--{tono}"),
                     **{"aria-hidden": "true"})


def chip_cambio(valor, texto, tono=None):
    """Chip de una diferencia (el «▲ 15%» de la referencia): triángulo según el signo de `valor` + el texto con su signo.
    `tono` («bien» | «critico») solo cuando el sentido es inequívoco; salidas, horas de bus, km y costo van sin tono."""
    tono = None if tono in (None, "neutro") else tono
    return html.Span([triangulo(valor, tono), html.Span(texto)], className="chip")


def chip_valor(rotulo, valor, id=None):
    """Chip de la referencia «Peak: Wed»: rótulo en gris y valor en tinta. Uso: ui.chip_valor("Pico:", "7:00")."""
    return html.Span([html.Span(rotulo, className="chip__rotulo"), html.Span(valor)], className="chip", **_kw(id=id))


def barra_rayas(etiqueta, valor, fraccion, rol="modelo", id=None):
    """Barra de progreso rayada de la referencia («Online Payments  $26,800» + barra): rótulo gris a la izquierda, valor a
    la derecha (ya formateado) y la barra con rayas del color del rol hasta `fraccion` (0 a 1). Para partes de un total o
    avance frente a una meta; nunca para un saldo con signo."""
    p = max(0.0, min(1.0, float(fraccion or 0)))
    return html.Div([html.Div([html.Span(etiqueta, className="rayas__etiqueta"), html.Span(valor, className="rayas__valor")], className="rayas__cab"),
                     html.Div(html.Div(className="rayas__relleno", style={"--p": f"{p * 100:.1f}%", "--c": VAR[_rol(rol)]}),
                              className="rayas__pista", role="img", **{"aria-label": f"{etiqueta}: {valor}"})],
                    className="rayas", **_kw(id=id))


def puntos(cuentas, foco=None, rol="modelo", etiqueta=None, id=None):
    """Matriz de puntos de la referencia («Transactions»): una columna por categoría con `cuentas[i]` puntos (enteros
    pequeños, p. ej. ya escalados de 0 a 5); la columna `foco` (índice) va sólida y las demás en el tinte. `etiqueta`
    (aria-label) dice qué representa con sus cifras."""
    cols = [html.Span([html.Span(className="puntos__p") for _ in range(int(n))],
                      className=_clases("puntos__col", i == foco and "puntos__col--foco")) for i, n in enumerate(cuentas)]
    estilo = {"--c": VAR[_rol(rol)], "--c-tinte": VAR[TINTE.get(_rol(rol), "hoy_tinte")]}
    return html.Div(cols, className="puntos", style=estilo, role="img", **{"aria-label": etiqueta or ""}, **_kw(id=id))


def tarjeta_insight(valor, titulo, texto=None, chip_="Lectura", id=None):
    """Tarjeta «Insights» de la referencia: degradado naranja → azul con grano, chip arriba, número grande blanco, una
    frase blanca y un texto. Una por pantalla como mucho; el número sale de datos/ (ya formateado)."""
    cuerpo = [html.P(valor, className="insight__valor"), html.P(titulo, className="insight__titulo")]
    if texto is not None:
        cuerpo.append(html.P(texto, className="insight__texto"))
    return html.Div([html.Span([_glifo("info", "glifo--s"), chip_], className="insight__chip"), html.Div(cuerpo, className="insight__cuerpo")],
                    className="insight", **_kw(id=id))


_AVISO_ICONO = {None: "info", "canje": "canje", "atencion": "alerta", "critico": "alerta", "bien": "bien"}


def aviso(texto, tipo=None, titulo=None, rol=None, id=None):
    """Aviso: icono de 22 px + título y texto a --t-m, sobre --superficie (o --superficie-2 anidado); el color solo en el
    icono y el título. Tipos: None (nota), «canje», «atencion», «critico» (el único con fondo teñido y role=alert), «bien».
    `texto` es una cadena, una lista de párrafos (cadenas) o un componente."""
    if tipo in ("info", "nota"):   # compatibilidad: la variante teñida «info» se retiró; es una nota
        tipo = None
    cuerpo = [html.P(titulo, className="aviso__titulo")] if titulo is not None else []
    if isinstance(texto, str):
        cuerpo.append(html.P(texto))
    elif isinstance(texto, (list, tuple)) and all(isinstance(t, str) for t in texto):
        cuerpo += [html.P(t) for t in texto]
    else:
        cuerpo.append(html.Div(_lista(texto)))
    return html.Div([_glifo(_AVISO_ICONO.get(tipo, "info"), "aviso__icono"), html.Div(cuerpo, className="aviso__cuerpo")],
                    className=_clases("aviso", tipo and f"aviso--{tipo}"), role=rol or ("alert" if tipo == "critico" else "note"),
                    **_kw(id=id))


# --- Leyenda, tabla y gráfico -----------------------------------------------------------------------------------------
# Orden fijo de la leyenda: Real, Hoy, Con el modelo, Modelo final, Plan que recorta, Oráculo, Contexto; rutas en su orden
_ORDEN_LEYENDA = {r: i for i, r in enumerate(["real", "hoy", "previsto_hoy", "modelo", "previsto_modelo", "modelo_final",
                                              "recorta", "oraculo", "contexto", "silencio", "cra54", "cl72"])}
_ROL_DE_COLOR = {}
for _r, _c in ROL.items():
    _ROL_DE_COLOR.setdefault(_c, _r)


def _rol(rol_o_color):
    """Rol de una entrada: el rol mismo, el nombre de una ruta de los datos o (compatibilidad) el color de un rol."""
    rol = T.RUTA_ROL.get(rol_o_color, rol_o_color)
    if rol in ROL:
        return rol
    if isinstance(rol_o_color, str) and rol_o_color.startswith("#") and rol_o_color.lower() in _ROL_DE_COLOR:
        return _ROL_DE_COLOR[rol_o_color.lower()]
    raise KeyError(f"rol desconocido: {rol_o_color!r}")


def leyenda(items, ordenar=True, id=None):
    """Leyenda HTML: [(texto, rol, forma)], una muestra por cada par rol-forma que se ve en el gráfico (también cuando una
    sola traza usa dos colores). Formas: barra, linea, gruesa, trazos, punteada, escalon, area, punto. La muestra lleva
    --c: var(--serie-…), nunca un color escrito. Un gráfico de un solo rol no lleva leyenda: lo nombra el título."""
    filas = []
    for i, (texto, rol, forma) in enumerate(items):
        rol = _rol(rol)
        forma = {"puntos": "punteada", "barra-borde": "barra", "foco": "barra", "escalon_rayado": "escalon"}.get(forma, forma)
        filas.append((_ORDEN_LEYENDA.get(rol, 99) if ordenar else 0, i, texto, rol, forma))
    filas.sort(key=lambda f: (f[0], f[1]))
    return html.Ul([html.Li([html.Span(className=f"leyenda__muestra leyenda__muestra--{forma}", style={"--c": VAR[rol]}), html.Span(texto)],
                            className="leyenda__item") for _o, _i, texto, rol, forma in filas],
                   className="leyenda", **_kw(id=id))


def muestra(rol_o_ruta):
    """Muestra cuadrada de 10 px del color de una ruta o de una serie (va siempre al lado de su nombre)."""
    return html.Span(className="tabla__muestra", style={"--c": VAR[_rol(rol_o_ruta)]}, **{"aria-hidden": "true"})


def clave(texto, rol_o_ruta):
    """Nombre con su muestra de color (rutas en las tablas)."""
    return html.Span([muestra(rol_o_ruta), html.Span(texto)], className="tabla__clave")


def tabla(encabezados, filas, total=None, mejor=None, compacta=False, muestras=None, ocultar_movil=(), num=None, alta=False, id=None):
    """Tabla en su marco blanco (radio 18, desplazamiento propio). La primera columna es el rótulo de la fila; las demás son
    números (.num, a la derecha y tabulares) salvo que `num` diga otra cosa. `total`: fila de total en 600. `mejor`: celdas
    (fila, columna) con el mejor valor, en --acento. `muestras`: ruta o rol de cada fila. `ocultar_movil`: columnas que se
    ocultan en ≤ 600 px."""
    n = len(encabezados)
    es_num = list(num) if num is not None else [j > 0 for j in range(n)]
    mejor = set(mejor or ())
    ocultar = set(ocultar_movil or ())

    def cls(j, *extra):
        return _clases("num" if es_num[j] else "", "solo-ancho" if j in ocultar else "", *extra) or None

    cab = html.Thead(html.Tr([html.Th(h, scope="col", **_kw(className=cls(j))) for j, h in enumerate(encabezados)]))
    cuerpo = []
    for i, f in enumerate(filas):
        rotulo = f[0]
        if muestras and muestras[i]:
            rotulo = clave(f[0], muestras[i])
        celdas = [html.Td(v, **_kw(className=cls(j, "tabla__mejor" if (i, j) in mejor else ""))) for j, v in enumerate(f[1:], 1)]
        cuerpo.append(html.Tr([html.Th(rotulo, scope="row", **_kw(className=cls(0)))] + celdas))
    if total is not None:
        cuerpo.append(html.Tr([html.Th(total[0], scope="row")] + [html.Td(v, **_kw(className=cls(j))) for j, v in enumerate(total[1:], 1)],
                              className="tabla__fila-total"))
    t = html.Table([cab, html.Tbody(cuerpo)], className=_clases("tabla", compacta and "tabla--compacta"))
    return html.Div(t, className=_clases("tabla-marco", alta and "tabla-marco--alta"), **_kw(id=id))


def desplegable(resumen, cuerpo, llano=False, pequeno=False, abierto=False, clase="", id=None):
    """Desplegable con chevron que gira: «Cómo se calcula», «Qué mide cada cifra». La variante pequeña es «Ver los datos»
    (icono de tabla, --t-s). Nunca para esconder un canje o un límite: esos van en un aviso a la vista."""
    titulo = [_glifo("chevron-derecha", "desplegable__chevron glifo--s")] + ([_glifo("tabla", "glifo--s")] if pequeno else []) + [html.Span(resumen)]
    return html.Details([html.Summary(titulo, className="desplegable__resumen"), html.Div(_lista(cuerpo), className="desplegable__cuerpo")],
                        open=abierto, className=_clases("desplegable", llano and "desplegable--llano", pequeno and "desplegable--pequeno", clase),
                        **_kw(id=id))


def grafico(id_o_fig, titulo=None, subtitulo=None, etiqueta=None, tabla=None, leyenda=None, nota=None, alto="normal", id=None,
            resumen_tabla="Ver los datos", **compat):
    """Contenedor de gráfico (figure.grafico): título-mensaje (h3) → subtítulo (qué es cada color, unidad, periodo) → leyenda
    HTML → lienzo (role=img con aria-label: el mensaje y las cifras clave) → «Ver los datos» (tabla gemela) → nota. Sin
    controles dentro: los de una sola figura van en la fila de su sección. `alto`: «normal» (320), «bajo» (240), «alto» (420).
    Con un id, los callbacks pueden escribir en «<id>-titulo», «<id>-sub», «<id>-leyenda», «<id>-tabla», «<id>-nota» (children)
    y en «<id>-lienzo» (aria-label). `tabla` es un componente o (encabezados, filas); `leyenda`, un componente o [(texto, rol, forma)]."""
    if isinstance(titulo, (int, float)) and not isinstance(titulo, bool):   # compatibilidad: grafico(id_o_fig, alto_px, clase)
        return _grafico_suelto(id_o_fig, titulo, subtitulo or compat.get("clase", ""))
    gid = id_o_fig if isinstance(id_o_fig, str) else id
    sub = (lambda s: f"{gid}-{s}" if gid else None)
    props = dict(config=GRAF_CONFIG, responsive=True, className="grafico__plotly", style={"height": "100%"})
    graf = dcc.Graph(id=gid, **props) if isinstance(id_o_fig, str) else dcc.Graph(figure=id_o_fig, **props, **_kw(id=gid))
    lienzo = html.Div(graf, className=_clases("grafico__lienzo", alto in ("bajo", "alto") and f"grafico__lienzo--{alto}"),
                      role="img", **{"aria-label": etiqueta or ""}, **_kw(id=sub("lienzo")))
    if isinstance(leyenda, (list, tuple)):
        leyenda = globals()["leyenda"](leyenda)
    if isinstance(tabla, tuple) and len(tabla) == 2:
        tabla = globals()["tabla"](tabla[0], tabla[1], compacta=True)
    textos = html.Div([html.H3(titulo, className="grafico__titulo", **_kw(id=sub("titulo"))),
                       html.P(subtitulo, className="grafico__sub", **_kw(id=sub("sub")))], className="grafico__textos")
    boton_mas = mas(html.Div(tabla, **_kw(id=sub("tabla"))), compat.get("fuentes"), resumen_tabla, clase="grafico__tabla")
    partes = [html.Div([textos, boton_mas], className="grafico__cab")]
    if leyenda is not None or gid:
        partes.append(html.Div(leyenda, **_kw(id=sub("leyenda"))))
    partes.append(lienzo)
    if nota is not None or gid:
        partes.append(html.P(nota, className="grafico__pie", **_kw(id=sub("nota"))))
    return html.Figure(partes, className="grafico", **_kw(id=sub("figura")))


# --- Pie de fuentes, destinos, botones y controles --------------------------------------------------------------------
def fuentes(rutas, rotulo="Fuentes:"):
    """Pie de fuentes de una sección: en escritorio, una línea (máx. 2) con icono, «Fuentes:» y las rutas relativas, con el
    texto completo en title; en el teléfono, «Fuentes (n)» plegado."""
    rutas = [r for r in _lista(rutas) if r]
    texto = " · ".join(rutas)
    escritorio = html.P([_glifo("fuente", "glifo--s"), html.Span(rotulo, className="fuentes__rotulo"), html.Span(texto)],
                        className="fuentes fuentes--escritorio", title=texto)
    movil = html.Details([html.Summary([_glifo("fuente", "glifo--s"), f"Fuentes ({len(rutas)})"]),
                          html.Ul([html.Li(r) for r in rutas], className="fuentes__lista")], className="fuentes fuentes--movil")
    return html.Div([escritorio, movil], className="fuentes-pie")


def destino(href, pantalla, titulo, texto, externo=False, icono=None):
    """Enlace a otra pantalla o a una página suelta: cuadro de 28 px + h3 → texto → «Abrir ›». Sin elevación."""
    hijos = [html.Div([cuadro(pantalla, icono), html.H3(titulo, className="destino__titulo")], className="destino__cab"),
             html.P(texto, className="destino__texto"),
             html.Span(["Abrir", _glifo("externo" if externo else "chevron-derecha", "glifo--s")], className="destino__ir")]
    if externo:
        return html.A(hijos, href=href, target="_blank", rel="noopener", className="destino")
    return dcc.Link(hijos, href=href, className="destino")


def destinos(hijos):
    return html.Div(_lista(hijos), className="destinos")


def boton(texto, href=None, tipo="secundario", icono=None, id=None, pequeno=False, externo=False, titulo=None):
    """Botón en píldora (36 px; 28 el pequeño): «primario» (uno por bloque), «secundario» o «fantasma». Con href es un enlace."""
    partes = ([_glifo(icono, "glifo--m")] if icono else []) + [texto]
    cls = _clases("boton", f"boton--{tipo}", pequeno and "boton--pequeno")
    if href:
        extra = {"target": "_blank", "rel": "noopener"} if externo else {}
        return html.A(partes, href=href, className=cls, **extra, **_kw(id=id, title=titulo))
    return html.Button(partes, className=cls, type="button", **_kw(id=id, title=titulo))


def boton_redondo(icono, href=None, titulo="", id=None, externo=False):
    """Botón redondo de borde fino (44 px) con un glifo, como los de la barra de la referencia. Con href es un enlace;
    `titulo` es su nombre (title y aria-label)."""
    hijos = [_glifo(icono)]
    kw = {"aria-label": titulo, "title": titulo}
    if href:
        extra = {"target": "_blank", "rel": "noopener"} if externo else {}
        return html.A(hijos, href=href, className="boton-redondo", **kw, **extra, **_kw(id=id))
    return html.Button(hijos, type="button", className="boton-redondo", **kw, **_kw(id=id))


def segmentado(id, opciones, valor, pequeno=False, clase="", persistir=True):
    """Segmentado (radios de verdad) para 2 a 6 opciones cortas y excluyentes; la elegida sobre --superficie en 600. Sin
    puntos de color. `opciones`: cadenas o {"label", "value"}."""
    if isinstance(pequeno, str):   # compatibilidad: segmentado(id, opciones, valor, clase)
        clase, pequeno = pequeno, "segmentado--pequeno" in pequeno
    ops = []
    for o in opciones:
        o = dict(o) if isinstance(o, dict) else {"label": o, "value": o}
        if isinstance(o["label"], str):
            o["label"] = html.Span(o["label"], className="segmentado__etiqueta")
        ops.append(o)
    kw = {"persistence": True, "persistence_type": "session"} if persistir else {}
    cls = _clases("segmentado", pequeno and "segmentado--pequeno", clase.replace("segmentado--pequeno", "").strip())
    return dcc.RadioItems(id=id, options=ops, value=valor, inline=True, className=cls, labelClassName="segmentado__opcion",
                          inputClassName="segmentado__input", **kw)


def control(rotulo, componente, ayuda=None, clase=""):
    """Control con su rótulo delante, en línea («Ruta:», «Tipo de día:»); la ayuda, si hay, debajo."""
    hijos = [html.Label(rotulo, className="control-rotulado__rotulo"), componente]
    if ayuda is not None:
        hijos.append(html.P(ayuda, className="control-rotulado__ayuda"))
    return html.Div(hijos, className=_clases("control-rotulado", clase))


def casilla(id, opciones, valor=None, lista=False, persistir=True):
    """Casillas nativas de 16 px en el acento (dcc.Checklist). `lista=True` las pone una debajo de otra."""
    kw = {"persistence": True, "persistence_type": "session"} if persistir else {}
    return dcc.Checklist(id=id, options=opciones, value=list(valor or []), className=_clases("casilla", lista and "casilla--lista"), **kw)


def deslizador(id, rotulo, minimo, maximo, paso, valor, marcas=None, ayuda=None, persistir=True):
    """Deslizador del panel de Horario: rótulo y valor (en «<id>-valor», lo escribe un callback) en una línea → pista →
    marcas a --t-xs → ayuda. Las marcas y ayudas que son datos se arman con fmt desde los datos."""
    kw = {"persistence": True, "persistence_type": "session"} if persistir else {}
    hijos = [html.Div([html.Label(rotulo, htmlFor=id, className="deslizador__rotulo"), html.Span(id=f"{id}-valor", className="deslizador__valor")],
                      className="deslizador__cab"),
             dcc.Slider(id=id, min=minimo, max=maximo, step=paso, value=valor, marks=marcas, updatemode="mouseup",
                        tooltip={"placement": "bottom", "always_visible": False}, allow_direct_input=False, className="deslizador", **kw)]
    if ayuda is not None:
        hijos.append(html.P(ayuda, className="deslizador__ayuda"))
    return html.Div(hijos, className="deslizador-bloque")


def delta(dif, d=0):
    """Celda de cambio del horario minuto a minuto: «+n» en --acento-suave, «−n» en --superficie-2 o «=»."""
    if dif > 0:
        return html.Span(con_signo(dif, d), className="delta delta--mas")
    if dif < 0:
        return html.Span(con_signo(dif, d), className="delta delta--menos")
    return html.Span("=", className="delta")


def hora_chip(texto):
    """Hora de una salida (mono, --t-s, sobre --superficie-2)."""
    return html.Span(texto, className="hora-chip")


# --- compatibilidad (inicio) -------------------------------------------------------------------------------------------
# Nombres antiguos que las páginas sin migrar todavía usan. Ya apuntan a los roles nuevos (el índigo dejó de ser dato, E1 y
# lo que se quita pasan a contexto, los supuestos iniciales a --serie-recorta). verificar_estilo.py los permite solo
# dentro de este bloque y lista quién los usa; se borra cuando las páginas migren.
COL = {
    "hoy": ROL["contexto"], "modelo": ROL["modelo"], "hibrido": ROL["modelo"], "e1": ROL["contexto"], "real": ROL["real"],
    "oraculo": ROL["oraculo"], "supuestos": ROL["recorta"], "quitadas": ROL["contexto"],
    "SILENCIO": ROL["silencio"], "CRA 54": ROL["cra54"], "CL 72": ROL["cl72"],
    "tinta": ROL["tinta"], "tinta2": ROL["tinta_2"], "tinta3": ROL["tinta_3"], "rejilla": ROL["rejilla"], "eje": ROL["eje"],
    "acento": ROL["acento"], "bien": ROL["bien"], "critico": ROL["critico"], "atencion": ROL["atencion"],
}
COLOR_MODELO = {"B1": ROL["contexto"], "E1": ROL["contexto"], "E11": ROL["modelo"], "E12": ROL["modelo"]}


def opcion_punto(texto, color=None, trazos=False):
    """Compatibilidad: la opción del segmentado ya no lleva punto de color."""
    return html.Span(texto, className="segmentado__etiqueta")


def _grafico_suelto(id_o_fig, alto=320, clase=""):
    """Compatibilidad: un dcc.Graph sin su contenedor (las páginas nuevas usan ui.grafico)."""
    kw = {"id": id_o_fig} if isinstance(id_o_fig, str) else {"figure": id_o_fig}
    return dcc.Graph(**kw, config=GRAF_CONFIG, style={"height": f"{alto}px"}, className=_clases("grafico-suelto", clase))


def figura(id_o_fig, alto, etiqueta, clase=""):
    """Compatibilidad: gráfico suelto con su aria-label."""
    return html.Div(_grafico_suelto(id_o_fig, alto, clase), role="img", **{"aria-label": etiqueta})


def ver_datos(encabezados, filas, resumen="Ver los datos"):
    """Compatibilidad: tabla gemela plegada (ui.grafico ya la trae)."""
    return desplegable(resumen, tabla(encabezados, filas, compacta=True), pequeno=True)


def pie_fuente(texto):
    """Compatibilidad: una línea de fuente suelta (las secciones nuevas llevan ui.fuentes)."""
    return html.P([_glifo("fuente", "glifo--s"), html.Span(texto)], className="pie-fuente")


def fichas_anuales(A, plan="reasigna", con_costo=True, clase=""):
    """Compatibilidad: fichas antes → después del año de un plan frente a hoy (salidas, horas de bus, km y, si se pide, el
    costo de km y conductor) con datos/ahorro_anual.json. Las diferencias y los % son campos del archivo. El costo lleva el
    signo del costo y va sin color (DISENO.md §6, regla 16)."""
    h, p = A["planes"]["hoy"], A["planes"][plan]
    s, bh, km = p["menos_salidas_anio"], p["delta_buses_hora_anio"], p["delta_km_anio"]
    fichas = [
        antes_despues("Salidas al año", num(h["salidas_anio"]), num(p["salidas_anio"]),
                      chip_cambio(-s, f"{con_signo(-s)} al año · {con_signo(p['var_salidas_pct'], 1)} %")),
        antes_despues("Horas de bus al año", num(h["buses_hora_anio"], 1), num(p["buses_hora_anio"], 1),
                      chip_cambio(-bh, f"{con_signo(-bh, 1)} al año · {con_signo(p['var_buses_hora_pct'], 1)} %")),
        antes_despues("Kilómetros al año", num(h["km_anio"]), num(p["km_anio"]),
                      chip_cambio(-km, f"{con_signo(-km)} al año · {con_signo(p['var_km_pct'], 1)} %")),
    ]
    if con_costo:
        ah = p["ahorro_operacion_Mcop"]
        fichas.insert(0, antes_despues("Costo de km y horas de conductor, M COP al año", num(h["costo_km_conductor_Mcop"]),
                                       num(p["costo_km_conductor_Mcop"]),
                                       chip_cambio(-ah, f"{con_signo(-ah)} M COP al año · {con_signo(-p['ahorro_pct_costo'], 1)} %"),
                                       nota="Esa diferencia es el ahorro en operación; no es ganancia (abajo, lo que se juega en pasajes)."))
    return html.Div(fichas, className=_clases("cambios", clase))
# --- compatibilidad (fin) ----------------------------------------------------------------------------------------------
