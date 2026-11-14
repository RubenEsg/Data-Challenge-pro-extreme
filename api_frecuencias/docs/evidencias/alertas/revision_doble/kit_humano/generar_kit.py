"""Genera revisar.html: la página para la revisión doble HUMANA, a ciegas, de las 96 alertas de la muestra.

Fila 18-R2 de la matriz: §18 de la especificación v1.5, riesgo «Etiquetas incorrectas → métricas engañosas», mitigación
«muestra manual revisada dos veces y conciliación». La página funciona abierta con doble clic (file://), sin internet
y sin librerías externas: las tarjetas, el protocolo, los estilos, la fuente y el código van dentro del archivo.

Lee:
  ../muestra.json                     las alertas de la muestra (id, código, ruta, fecha, ventana, tarjeta)
  ../muestra/<id>.md                  la tarjeta de contexto de cada alerta (sin etiqueta)
  ../protocolo.md                     §2 (independencia y orden de decisión) y §3 (definiciones por código)
  plantilla/pagina.html, estilos.css y app.js    esqueleto, estilos y lógica de la página
  dash_app/tokens.py y dash_app/assets/          tokens de color y tipografía del tablero, fuente Inter e iconos

Es ciega: no lee etiquetas_A.json, etiquetas_B.json, conciliacion.json ni resumen.md. De cada tarjeta quita el aviso
inicial (habla de los revisores automatizados) y la sección «Para el revisor» (la reemplaza el panel de decisión).
La salida es determinista: con las mismas fuentes sale el mismo archivo, byte a byte (no lleva la hora de generación).

Uso (desde cualquier carpeta; solo la biblioteca estándar de Python 3.11 o superior):
    python -I generar_kit.py [--salida RUTA] [--dash RUTA_DE_DASH_APP]
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import html
import importlib.util
import json
import re
import sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent
REVISION = AQUI.parent
ENTREGA = AQUI.parents[5]          # EntregaFinal/ en el repositorio del proyecto; la raíz en el de entrega
PLANTILLA = AQUI / "plantilla"
SALIDA = AQUI / "revisar.html"

# Propiedades propias de la página (se fijan en línea o desde app.js): no son tokens del sistema de diseño.
LOCALES = {"--p", "--c", "--alto-cabecera"}
# Iconos del tablero (dash_app/assets/iconos) que usa la página, en línea y con el color del texto.
ICONOS = ("bus", "bien", "alerta", "info", "chevron-izquierda", "chevron-derecha", "descargar")
FAMILIAS = {"pronostico": "de pronóstico", "observada": "observada"}
# Regla del sistema de diseño (DISENO.md) fuera de :root: ni colores, ni tamaños de letra, pesos, interlineados,
# radios o sombras literales. Las propiedades de medida solo llevan var(--…); las de color, además, ningún color con
# nombre (los hexadecimales y rgb()/hsl() se buscan en toda la hoja). Los números de un degradado sí valen.
SOLO_TOKENS = {"font", "font-size", "font-weight", "line-height", "border-radius", "box-shadow"}
DE_COLOR = {"color", "background", "background-color", "border", "border-top", "border-bottom", "border-color",
            "outline", "outline-color", "fill", "stroke"}
COLORES_CON_NOMBRE = re.compile(
    r"\b(white|black|red|green|blue|gr[ae]y|silver|orange|purple|pink|yellow|navy|teal)\b", re.I)

ITEM = re.compile(r"^(\s*)([-*]|\d+\.)\s+(.*)$")
NUMERO = re.compile(r"^[−-]?\d{1,3}(?:\.\d{3})*(?:,\d+)?(?:\s?%)?$")
SECCION_REVISOR = re.compile(r"^\d+\.\s+Para el revisor\b")
TITULO_CODIGO = re.compile(r"^(ALT-\d{3}) (.+?)(?: \((.+)\))?$")


class ErrorKit(Exception):
    """Una fuente no tiene la forma esperada: mejor no generar la página que generarla incompleta."""


# --- Markdown de las tarjetas y del protocolo (el subconjunto que usan) -------------------------------------------
def en_linea(texto: str) -> str:
    """`código` y **negrita**; todo lo demás se escapa. «\\|» es una barra dentro de una celda."""
    out = []
    for parte in re.split(r"(`[^`]+`)", texto):
        if len(parte) >= 2 and parte.startswith("`") and parte.endswith("`"):
            out.append(f"<code>{html.escape(parte[1:-1], quote=False)}</code>")
        else:
            t = html.escape(parte.replace("\\|", "|"), quote=False)
            out.append(re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t))
    return "".join(out)


def bloques(texto: str) -> list[dict]:
    """Divide el Markdown en bloques: título, cita, tabla, lista y párrafo."""
    lineas = texto.splitlines()
    out: list[dict] = []
    i = 0
    while i < len(lineas):
        linea = lineas[i]
        if not linea.strip():
            i += 1
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", linea)
        if m:
            out.append({"tipo": "titulo", "nivel": len(m.group(1)), "texto": m.group(2).strip()})
            i += 1
            continue
        j = i
        if linea.startswith(">"):
            while j < len(lineas) and lineas[j].startswith(">"):
                j += 1
            out.append({"tipo": "cita", "texto": " ".join(x[1:].strip() for x in lineas[i:j])})
        elif linea.lstrip().startswith("|"):
            while j < len(lineas) and lineas[j].lstrip().startswith("|"):
                j += 1
            out.append({"tipo": "tabla", "lineas": lineas[i:j]})
        elif ITEM.match(linea):
            j += 1
            while j < len(lineas) and lineas[j].strip() and (ITEM.match(lineas[j]) or lineas[j][:1] in (" ", "\t")):
                j += 1
            out.append({"tipo": "lista", "lineas": lineas[i:j]})
        else:
            while (j < len(lineas) and lineas[j].strip() and not ITEM.match(lineas[j])
                   and not re.match(r"^(#{1,6}\s|>|\s*\|)", lineas[j])):
                j += 1
            out.append({"tipo": "parrafo", "texto": " ".join(x.strip() for x in lineas[i:j])})
        i = j
    return out


def arbol_lista(lineas: list[str]) -> list[dict]:
    """Lista con sangrías → árbol de ítems (las líneas sangradas que no son ítems continúan el ítem anterior)."""
    raiz: dict = {"hijos": [], "sangria": -1}
    pila = [raiz]
    for linea in lineas:
        m = ITEM.match(linea)
        if m:
            sangria = len(m.group(1).expandtabs(4))
            while pila[-1] is not raiz and pila[-1]["sangria"] >= sangria:
                pila.pop()
            marca = m.group(2)
            nodo = {"texto": m.group(3).strip(), "sangria": sangria, "ordenada": marca[0].isdigit(),
                    "numero": int(marca[:-1]) if marca[0].isdigit() else None, "hijos": []}
            pila[-1]["hijos"].append(nodo)
            pila.append(nodo)
        elif pila[-1] is not raiz:
            pila[-1]["texto"] += " " + linea.strip()
    return raiz["hijos"]


def nodos_html(nodos: list[dict], padre: int | None = None) -> str:
    """Árbol de ítems → HTML. Una lista numerada dentro de un ítem numerado lleva los pasos «2.1», «2.2»…"""
    grupos: list[tuple[bool, list[dict]]] = []
    for n in nodos:
        if grupos and grupos[-1][0] == n["ordenada"]:
            grupos[-1][1].append(n)
        else:
            grupos.append((n["ordenada"], [n]))
    out = []
    for ordenada, grupo in grupos:
        pasos = ordenada and padre is not None
        items = []
        for n in grupo:
            hijos = nodos_html(n["hijos"], n["numero"]) if n["hijos"] else ""
            texto = en_linea(n["texto"])
            if pasos:
                items.append(f'<li><span class="num-paso">{padre}.{n["numero"]}</span><div>{texto}{hijos}</div></li>')
            elif ordenada:
                items.append(f'<li value="{n["numero"]}">{texto}{hijos}</li>')
            else:
                items.append(f"<li>{texto}{hijos}</li>")
        etiqueta = "ol" if ordenada else "ul"
        clase = ' class="pasos"' if pasos else ""
        out.append(f"<{etiqueta}{clase}>{''.join(items)}</{etiqueta}>")
    return "".join(out)


def celdas(linea: str) -> list[str]:
    s = linea.strip()
    s = s[1:] if s.startswith("|") else s
    s = s[:-1] if s.endswith("|") and not s.endswith("\\|") else s
    return [c.strip() for c in re.split(r"(?<!\\)\|", s)]


def tabla_html(lineas: list[str]) -> str:
    """Tabla Markdown → tabla del tablero: columnas de cifras a la derecha; las horas de la ventana («►») resaltadas."""
    filas = [celdas(x) for x in lineas]
    if len(filas) < 2 or not all(re.fullmatch(r":?-{3,}:?", c) for c in filas[1]):
        raise ErrorKit(f"tabla sin fila separadora: {lineas[0][:80]}")
    cab = filas[0]
    n = len(cab)
    cuerpo = [(f + [""] * n)[:n] for f in filas[2:]]
    clase_num = []
    for k in range(n):
        valores = [f[k].replace("**", "").strip() for f in cuerpo]
        valores = [v for v in valores if v and v != "—"]
        clase_num.append(' class="num"' if valores and all(NUMERO.match(v) for v in valores) else "")
    ventana = cab[0] == "" and any(f[0] == "►" for f in cuerpo)
    ths = []
    for k, c in enumerate(cab):
        if k == 0 and ventana:
            ths.append('<th scope="col" class="marca-ventana"><span class="oculto">Hora de la ventana</span></th>')
        else:
            ths.append(f'<th scope="col"{clase_num[k]}>{en_linea(c)}</th>')
    trs = []
    for f in cuerpo:
        tds = []
        for k, c in enumerate(f):
            if k == 0 and ventana:
                marca = ('<span aria-hidden="true">►</span><span class="oculto">hora de la ventana</span>'
                         if c == "►" else "")
                tds.append(f'<td class="marca-ventana">{marca}</td>')
            else:
                tds.append(f"<td{clase_num[k]}>{en_linea(c)}</td>")
        clase = ' class="en-ventana"' if ventana and f[0] == "►" else ""
        trs.append(f"<tr{clase}>{''.join(tds)}</tr>")
    return (f'<div class="tabla-marco"><table class="tabla"><thead><tr>{"".join(ths)}</tr></thead>'
            f'<tbody>{"".join(trs)}</tbody></table></div>')


def bloques_html(bs: list[dict], desplazar: int = 1) -> str:
    out = []
    for b in bs:
        if b["tipo"] == "titulo":
            nivel = min(6, b["nivel"] + desplazar)
            out.append(f"<h{nivel}>{en_linea(b['texto'])}</h{nivel}>")
        elif b["tipo"] == "parrafo":
            out.append(f"<p>{en_linea(b['texto'])}</p>")
        elif b["tipo"] == "tabla":
            out.append(tabla_html(b["lineas"]))
        elif b["tipo"] == "lista":
            out.append(nodos_html(arbol_lista(b["lineas"])))
        else:
            out.append(f"<blockquote><p>{en_linea(b['texto'])}</p></blockquote>")
    return "\n".join(out)


def partir(texto: str, nivel: int) -> list[tuple[str | None, str]]:
    """Secciones de un nivel de título: [(título o None para el preámbulo, cuerpo)]."""
    marca = "#" * nivel + " "
    out: list[tuple[str | None, str]] = []
    titulo: str | None = None
    actual: list[str] = []
    for linea in texto.splitlines():
        if linea.startswith(marca):
            out.append((titulo, "\n".join(actual)))
            titulo, actual = linea[len(marca):].strip(), []
        else:
            actual.append(linea)
    out.append((titulo, "\n".join(actual)))
    return out


# --- Fuentes -------------------------------------------------------------------------------------------------------
def leer_muestra(revision: Path) -> list[dict]:
    muestra = json.loads((revision / "muestra.json").read_text(encoding="utf-8"))["muestra"]
    ids = [x["id"] for x in muestra]
    if len(ids) != len(set(ids)) or not ids:
        raise ErrorKit("muestra.json: ids vacíos o repetidos")
    return muestra


def id_kit(muestra: list[dict]) -> str:
    """Identificador estable de la muestra (ids y claves de episodio): separa el avance guardado de otra muestra."""
    base = "\n".join(f"{x['id']}|{x['clave_dedup']}" for x in muestra)
    return hashlib.sha256(base.encode("utf-8")).hexdigest()[:12]


def protocolo(texto: str, codigos: list[str]) -> dict:
    """Las partes del protocolo que ve el revisor: §2 (independencia y orden de decisión) y §3 (definiciones)."""
    secciones = dict(partir(texto, 2))
    como = next((c for t, c in secciones.items() if t and t.startswith("2.")), None)
    defin = next((c for t, c in secciones.items() if t and t.startswith("3.")), None)
    if como is None or defin is None:
        raise ErrorKit("protocolo.md: faltan las secciones «2. Cómo se revisa» o «3. Definiciones por código»")
    lista = next((b for b in bloques(como) if b["tipo"] == "lista"), None)
    nodos = arbol_lista(lista["lineas"]) if lista else []
    elegidos = [n for n in nodos if n["texto"].startswith(("**Independencia", "**Orden de decisión"))]
    orden = next((n for n in elegidos if n["texto"].startswith("**Orden de decisión")), None)
    if len(elegidos) != 2 or orden is None or len(orden["hijos"]) < 5:
        raise ErrorKit("protocolo.md §2: no encuentro «Independencia» y «Orden de decisión» con sus 5 pasos")
    definiciones = {}
    preambulo = ""
    for titulo, cuerpo in partir(defin, 3):
        if titulo is None:
            preambulo = bloques_html(bloques(cuerpo))
            continue
        m = TITULO_CODIGO.match(titulo)
        if not m:
            raise ErrorKit(f"protocolo.md §3: título de código inesperado: {titulo}")
        definiciones[m.group(1)] = {"nombre": m.group(2), "detalle": m.group(3) or "",
                                    "html": bloques_html(bloques(cuerpo))}
    faltan = [c for c in codigos if c not in definiciones]
    if faltan:
        raise ErrorKit(f"protocolo.md §3: sin definición para {faltan}")
    return {"como": nodos_html(elegidos), "orden": nodos_html(orden["hijos"], orden["numero"]),
            "convenciones": preambulo, "definiciones": definiciones}


def chip(rotulo: str, valor: str) -> str:
    return f'<span class="chip"><span class="chip__rotulo">{rotulo}</span> {html.escape(valor)}</span>'


def tarjeta(item: dict, texto: str, nombre_codigo: str, token_ruta: str) -> str:
    """Tarjeta Markdown → <article>, sin el aviso de la revisión automatizada ni la sección «Para el revisor»."""
    bs = bloques(texto)
    if not bs or bs[0]["tipo"] != "titulo" or bs[0]["nivel"] != 1 or item["id"] not in bs[0]["texto"]:
        raise ErrorKit(f"{item['tarjeta']}: no empieza con el título de la tarjeta {item['id']}")
    resto = bs[1:]
    if resto and resto[0]["tipo"] == "cita":
        resto = resto[1:]
    quedan, saltar, quitadas = [], False, 0
    for b in resto:
        if b["tipo"] == "titulo" and b["nivel"] == 2:
            saltar = bool(SECCION_REVISOR.match(b["texto"]))
            quitadas += saltar
        if not saltar:
            quedan.append(b)
    if quitadas != 1 or any(b["tipo"] == "cita" for b in quedan):
        raise ErrorKit(f"{item['tarjeta']}: estructura inesperada (aviso o sección «Para el revisor»)")
    i = html.escape(item["id"])
    ruta = (f'<span class="chip"><span class="muestra-ruta" style="--c: var({token_ruta})" aria-hidden="true">'
            f"</span>{html.escape(item['ruta'])}</span>")
    chips = ruta + chip("Fecha", item["fecha"]) + chip("Ventana", item["ventana"])
    chips += chip("Familia", FAMILIAS.get(item["familia"], item["familia"]))
    titulo = f"{html.escape(item['codigo'])} {html.escape(nombre_codigo)}"
    return (
        f'<article class="tarjeta tarjeta-alerta" data-id="{i}" data-codigo="{html.escape(item["codigo"])}" '
        f'aria-labelledby="titulo-{i}" hidden>\n'
        f'<header class="alerta__cab"><p class="alerta__id">{i} · tarjeta de contexto</p>'
        f'<h2 class="alerta__titulo" id="titulo-{i}" tabindex="-1">{titulo}</h2><div class="chips">{chips}</div>'
        '<button type="button" class="boton boton--secundario boton--pequeno ir-decision">Ir a la decisión</button>'
        f'</header>\n<div class="md">\n{bloques_html(quedan)}\n</div>\n</article>'
    )


# --- Sistema de diseño ---------------------------------------------------------------------------------------------
def cargar_tokens(dash: Path):
    ruta = dash / "tokens.py"
    if not ruta.is_file():
        raise ErrorKit(f"no encuentro {ruta}: los colores y la tipografía salen del sistema de diseño del tablero")
    spec = importlib.util.spec_from_file_location("tokens_tablero", ruta)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def revisar_css(css: str) -> None:
    """La regla del sistema de diseño: fuera de :root, colores, letra, radios y sombras solo con var(--…)."""
    limpio = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    problemas = []
    if re.search(r"#[0-9a-fA-F]{3,8}\b", limpio) or re.search(r"\b(?:rgba?|hsla?|hwb|lab|lch|oklch|oklab)\(", limpio):
        problemas.append("color literal (hexadecimal o rgb/hsl)")
    for prop, valor in re.findall(r"(?<![\w-])([a-z-]+)\s*:\s*([^;{}]+)", limpio):
        resto = re.sub(r"var\([^()]*\)", "", valor)
        if (prop in SOLO_TOKENS and re.search(r"\d", resto)) or (prop in DE_COLOR and COLORES_CON_NOMBRE.search(resto)):
            problemas.append(f"{prop}: {valor.strip()}")
    if problemas:
        raise ErrorKit("estilos fuera del sistema de diseño: " + "; ".join(problemas))


def bloque_tokens(tok, texto_que_usa: str) -> str:
    """:root con los tokens de estilos.css que la página usa (y los que estos citan), en el orden del tablero."""
    usados = set(re.findall(r"var\(\s*(--[\w-]+)", texto_que_usa)) - LOCALES
    todos = dict(tok.TOKENS)
    necesarios: set[str] = set()
    pendientes = sorted(usados)
    while pendientes:
        nombre = pendientes.pop()
        if nombre in necesarios:
            continue
        if nombre not in todos:
            raise ErrorKit(f"{nombre} no es un token de dash_app/assets/estilos.css")
        necesarios.add(nombre)
        pendientes.extend(re.findall(r"var\(\s*(--[\w-]+)", todos[nombre]))
    lineas = ["  color-scheme: light;"] + [f"  {k}: {v};" for k, v in todos.items() if k in necesarios]
    css = ":root {\n" + "\n".join(lineas) + "\n}\n"
    for consulta, extra in (("(max-width: 600px)", tok.TOKENS_TELEFONO),
                            ("(prefers-reduced-motion: reduce)", tok.TOKENS_MOVIMIENTO_REDUCIDO)):
        pares = "".join(f"    {k}: {v};\n" for k, v in extra.items() if k in necesarios)
        if pares:
            css += f"@media {consulta} {{\n  :root {{\n{pares}  }}\n}}\n"
    return css


def icono(dash: Path, nombre: str, clase: str = "glifo") -> str:
    """Icono del tablero en línea: sin xmlns (no hace falta dentro de HTML) y con el color del texto."""
    svg = (dash / "assets" / "iconos" / f"{nombre}.svg").read_text(encoding="utf-8").strip()
    svg = svg.replace(' xmlns="http://www.w3.org/2000/svg"', "").replace('stroke="#000"', 'stroke="currentColor"')
    if "http" in svg or "#" in svg:
        raise ErrorKit(f"icono {nombre}: trae referencias o colores que no se esperaban")
    return svg.replace("<svg ", f'<svg class="{clase}" aria-hidden="true" focusable="false" ', 1)


def fuente(dash: Path) -> str:
    datos = base64.b64encode((dash / "assets" / "fuentes" / "InterVariable.woff2").read_bytes()).decode("ascii")
    return ('@font-face { font-family: "Inter"; src: url(data:font/woff2;base64,' + datos + ') format("woff2"); '
            "font-weight: 100 900; font-style: normal; font-display: swap; }")


def sha(texto: str) -> str:
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def json_en_script(obj) -> str:
    """JSON dentro de <script>: sin «<», «>» ni «&» literales (no puede cerrar la etiqueta)."""
    texto = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    return texto.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")


# --- Página --------------------------------------------------------------------------------------------------------
def opciones(campo: str, valores: list[tuple[str, str]], marca: str) -> str:
    return "".join(
        f'<button type="button" class="opcion" data-campo="{campo}" data-valor="{v}" aria-pressed="false">'
        f"{marca}{texto}</button>"
        for v, texto in valores
    )


def lista_y(codigos: list[str]) -> str:
    return codigos[0] if len(codigos) == 1 else ", ".join(codigos[:-1]) + " y " + codigos[-1]


def leer_plantilla(nombre: str) -> str:
    texto = (PLANTILLA / nombre).read_text(encoding="utf-8")
    if nombre != "pagina.html" and ("</style" in texto.lower() or "</script" in texto.lower() or "http" in texto):
        raise ErrorKit(f"plantilla/{nombre}: no puede cerrar su etiqueta ni citar recursos externos")
    return texto


def construir(revision: Path, dash: Path) -> str:
    muestra = leer_muestra(revision)
    codigos = sorted({x["codigo"] for x in muestra})
    texto_protocolo = (revision / "protocolo.md").read_text(encoding="utf-8")
    proto = protocolo(texto_protocolo, codigos)
    definiciones = proto["definiciones"]
    tok = cargar_tokens(dash)
    textos, articulos = [], []
    for item in muestra:
        texto = (revision / item["tarjeta"]).read_text(encoding="utf-8")
        textos.append(texto)
        rol = tok.RUTA_ROL.get(item["ruta"])
        if rol is None:
            raise ErrorKit(f"{item['id']}: la ruta {item['ruta']} no tiene color en el sistema de diseño")
        articulos.append(tarjeta(item, texto, definiciones[item["codigo"]]["nombre"], tok.ROL_TOKEN[rol]))

    ic = {n: icono(dash, n) for n in ICONOS}
    elegida = icono(dash, "bien", "glifo glifo-elegida")
    tarjetas_codigo = "\n".join(
        f'<section class="tarjeta" aria-labelledby="def-{c}"><h2 class="tarjeta__titulo" id="def-{c}">{c} '
        f'{html.escape(definiciones[c]["nombre"])}</h2>'
        f'<p class="tarjeta__sub">{en_linea(definiciones[c]["detalle"])}</p>'
        f'<div class="md def">{definiciones[c]["html"]}</div></section>'
        for c in codigos
    )
    sin_casos = [c for c in definiciones if c not in codigos]
    nota = (f"{lista_y(sin_casos)} no tienen casos en esta muestra; sus definiciones están en "
            "<code>protocolo.md</code> §3." if sin_casos else "Todos los códigos del protocolo tienen casos aquí.")
    defs_panel = "\n".join(
        f'<div class="def md" data-codigo="{c}" hidden><p class="def__sub">{c} '
        f'{html.escape(definiciones[c]["nombre"])} · {en_linea(definiciones[c]["detalle"])}</p>'
        f'{definiciones[c]["html"]}</div>'
        for c in codigos
    )
    datos = {
        "kit": id_kit(muestra),
        "alertas": [{"id": x["id"], "codigo": x["codigo"], "nombre": definiciones[x["codigo"]]["nombre"],
                     "ruta": x["ruta"], "fecha": x["fecha"], "ventana": x["ventana"], "familia": x["familia"]}
                    for x in muestra],
    }
    css, js, pagina = leer_plantilla("estilos.css"), leer_plantilla("app.js"), leer_plantilla("pagina.html")
    revisar_css(css)
    reemplazos = {
        "@@TOTAL@@": str(len(muestra)),
        "@@KIT@@": datos["kit"],
        "@@SHA_MUESTRA@@": sha((revision / "muestra.json").read_text(encoding="utf-8")),
        "@@SHA_TARJETAS@@": sha("".join(textos)),
        "@@SHA_PROTOCOLO@@": sha(texto_protocolo),
        "@@PROTOCOLO_COMO@@": proto["como"],
        "@@PROTOCOLO_CONVENCIONES@@": proto["convenciones"],
        "@@PROTOCOLO_CODIGOS@@": tarjetas_codigo,
        "@@NOTA_SIN_CASOS@@": nota,
        "@@ORDEN_DECISION@@": proto["orden"],
        "@@DEFINICIONES_PANEL@@": defs_panel,
        "@@TARJETAS@@": "\n".join(articulos),
        "@@OPCIONES_ETIQUETA@@": opciones(
            "etiqueta", [("verdadera", "Verdadera"), ("falsa", "Falsa"), ("indeterminada", "Indeterminada")], elegida),
        "@@OPCIONES_CONFIANZA@@": opciones("confianza", [("alta", "Alta"), ("media", "Media"), ("baja", "Baja")],
                                           elegida),
        "@@ICONO_BUS@@": ic["bus"],
        "@@ICONO_ALERTA@@": ic["alerta"],
        "@@ICONO_BIEN@@": ic["bien"],
        "@@ICONO_INFO@@": ic["info"],
        "@@ICONO_DESCARGAR@@": ic["descargar"],
        "@@CHEVRON_IZQ@@": ic["chevron-izquierda"],
        "@@CHEVRON_DER@@": ic["chevron-derecha"],
    }
    for marca, valor in reemplazos.items():
        pagina = pagina.replace(marca, valor)
    tokens_css = bloque_tokens(tok, css + pagina)
    finales = {"@@FUENTE@@": fuente(dash), "@@TOKENS@@": tokens_css.strip(), "@@CSS@@": css.strip(),
               "@@JS@@": js.strip(), "@@DATOS@@": json_en_script(datos)}
    for marca, valor in finales.items():
        pagina = pagina.replace(marca, valor)
    if "@@" in pagina:
        raise ErrorKit("quedó un marcador sin reemplazar en la página")
    return pagina


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--salida", type=Path, default=SALIDA, help="HTML que se escribe (por defecto revisar.html)")
    ap.add_argument("--dash", type=Path, default=ENTREGA / "dash_app", help="carpeta dash_app/ del tablero")
    args = ap.parse_args(argv)
    try:
        pagina = construir(REVISION, args.dash)
    except ErrorKit as e:
        print(f"No se generó la página: {e}", file=sys.stderr)
        return 2
    args.salida.parent.mkdir(parents=True, exist_ok=True)
    args.salida.write_text(pagina, encoding="utf-8", newline="\n")
    n = pagina.count('class="tarjeta tarjeta-alerta"')
    print(f"{args.salida}: {n} alertas, {len(pagina.encode('utf-8')) / 1e6:.2f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
