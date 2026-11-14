"""Prueba del sistema de diseño del laboratorio Dash (DISENO.md §9), junto a verificar_ahorro.py.

Uso (con el Python del entorno del Dash o con cualquier Python 3.10+; solo biblioteca estándar):
    python verificar_estilo.py                    # en el código, sin servidor: CSS, Python, roles y paleta
    python verificar_estilo.py --solo-base        # lo mismo sin paginas/*.py (la base: estilos.css, tokens.py, ui.py…)
    python verificar_estilo.py --vivo 8082        # además, en Edge sin interfaz con el Dash corriendo en ese puerto
    python verificar_estilo.py --vivo 8082 --capturas CARPETA --informe informe.json

La parte en vivo necesita Playwright; si este Python no lo tiene, dice con qué comando correrla. Nunca usa el puerto 8050.
Termina con código 1 si algo falla.
"""
import argparse
import ast
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tokenize
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))
import tokens as T  # noqa: E402

CSS = AQUI / "assets" / "estilos.css"
BASE_PY = [AQUI / "ui.py", AQUI / "tokens.py", AQUI / "app.py", AQUI / "controles.py", AQUI / "cliente_api.py"]
PAGINAS_PY = sorted((AQUI / "paginas").glob("*.py"))
# El Dash ya no copia app/tokens.css: sigue la referencia que eligió el usuario (DISENO.md §1). Tokens que deben existir:
NUEVOS = ["--serie-modelo", "--serie-modelo-tinte", "--serie-hoy", "--serie-hoy-tinte", "--serie-real", "--serie-recorta",
          "--serie-recorta-tinte", "--serie-contexto", "--franja", "--lavado", "--blanco", "--tinta-tenue", "--tinta-inversa",
          "--radio-l", "--radio-xl", "--sombra-2", "--sombra-4", "--insight-1", "--insight-5", "--grano", "--icono-puntos",
          "--alto-barra", "--peso-titulo", "--peso-cifra", "--ls-cifra", "--lh-uno"]
PROPIOS = ["--ancho-panel", "--boton-redondo"]
RETIRADOS = ["--serie-hibrido", "--info-suave", "--lateral-hover", "--ancho-lateral"]
# Contraste de texto (WCAG): (texto, fondo, mínimo). 4,5:1 para texto pequeño; 3:1 para texto de 24 px o más y marcas.
CONTRASTES = [(t, f, 4.5) for t in ("--tinta", "--tinta-2", "--tinta-3") for f in ("--superficie", "--superficie-2", "--fondo", "--blanco")] + [
    ("--acento", "--superficie", 4.5), ("--acento", "--blanco", 4.5), ("--acento-sobre-suave", "--acento-suave", 4.5),
    ("--bien", "--blanco", 4.5), ("--bien", "--superficie", 4.5), ("--critico", "--blanco", 4.5), ("--atencion-texto", "--blanco", 4.5),
    ("--critico", "--critico-suave", 4.5), ("--tinta-inversa", "--tinta", 4.5),
    ("--tinta-tenue", "--superficie", 3.0), ("--tinta-tenue", "--blanco", 3.0),                       # solo texto de 24 px o más
    ("--tinta-inversa", "--insight-4", 4.5), ("--tinta-inversa", "--insight-5", 4.5), ("--tinta-inversa", "--insight-3", 3.0),
    ("--serie-modelo", "--superficie", 3.0), ("--serie-hoy", "--superficie", 3.0), ("--serie-recorta", "--superficie", 3.0),
    ("--serie-real", "--superficie", 3.0), ("--ruta-silencio", "--superficie", 3.0), ("--ruta-cra54", "--superficie", 3.0),
    ("--ruta-cl72", "--superficie", 3.0)]


class Informe:
    def __init__(self):
        self.fallas, self.avisos, self.notas, self.bien = [], [], [], []

    def falla(self, grupo, texto):
        self.fallas.append((grupo, texto))

    def aviso(self, grupo, texto):
        self.avisos.append((grupo, texto))

    def nota(self, grupo, texto):
        self.notas.append((grupo, texto))

    def ok(self, grupo, texto):
        self.bien.append((grupo, texto))


# --- CSS --------------------------------------------------------------------------------------------------------------
def reglas(texto, base=0, medios=()):
    """Reglas de un CSS sin comentarios: (medios, selector, [(propiedad, valor)], línea). Entra en @media y @supports."""
    out = []
    for pre, cuerpo, linea, inicio in T.estatutos(texto):
        linea_abs = base + linea
        if pre.startswith("@media") or pre.startswith("@supports"):
            out += reglas(cuerpo, base + texto.count("\n", 0, inicio), medios + (pre,))
        elif pre.startswith("@"):
            continue                                      # @keyframes y otras: no son componentes
        else:
            out.append((medios, pre, T.declaraciones(cuerpo), linea_abs))
    return out


def sin_funciones(valor, nombres=("var", "env", "url")):
    """El valor sin las llamadas var(…), env(…) y url(…) (con sus paréntesis anidados)."""
    out, i = [], 0
    while i < len(valor):
        m = re.match(r"(%s)\(" % "|".join(nombres), valor[i:])
        if m and (i == 0 or not (valor[i - 1].isalnum() or valor[i - 1] == "-")):
            prof, j = 1, i + len(m.group(0))
            while j < len(valor) and prof:
                prof += {"(": 1, ")": -1}.get(valor[j], 0)
                j += 1
            out.append(" ")
            i = j
            continue
        out.append(valor[i])
        i += 1
    return "".join(out)


# Literales permitidos fuera de :root (selector · propiedad · valor). Con la base de la referencia ya no hace falta ninguno:
# todo pasa por tokens. Se deja la estructura por si un componente de Dash lo exige.
LISTA_BLANCA = []
ESPACIADO = re.compile(r"^(padding|margin|gap|row-gap|column-gap)(-[a-z-]+)?$")


def permitido(selector, prop, valor):
    return any(re.search(s, selector) and re.search(p, prop) and re.search(v, valor) for s, p, v in LISTA_BLANCA)


def comprobar_css(inf):
    g = "CSS"
    texto = CSS.read_text(encoding="utf-8")
    limpio = T.quitar_comentarios(texto)
    todas = reglas(limpio)
    problemas = 0
    locales = set()
    for medios, sel, decls, linea in todas:
        if sel.startswith(":root"):
            continue
        for prop, valor in decls:
            if prop.startswith("--"):
                locales.add(prop)
            donde = f"estilos.css:{linea} «{sel[:60]}» {prop}: {valor}"
            limpio_v = sin_funciones(valor)
            if re.search(r"#[0-9a-fA-F]{3,8}\b|\b(rgba?|hsla?)\(|\b(white|black)\b", limpio_v):
                inf.falla(g, f"color literal fuera de :root · {donde}")
                problemas += 1
            if prop == "font-weight" and re.search(r"\b(700|800|900|bold)\b", valor) or prop == "font" and re.search(r"\b(700|bold)\b", valor):
                inf.falla(g, f"peso 700 o bold · {donde}")
                problemas += 1
            reglas_valor = {
                "font-size": r"^(var\(--t-[\w-]+\)|0|inherit)$",
                "font-weight": r"^(var\(--peso-\w+\)|inherit)$",
                "line-height": r"^(var\(--lh-[\w-]+\)|inherit|normal)$",
                "letter-spacing": r"^(var\(--ls-[\w-]+\)|0|normal)$",
                "box-shadow": r"^(var\(--sombra-[\w-]+\)|none)$",
            }
            ok = True
            if prop in reglas_valor:
                ok = bool(re.match(reglas_valor[prop], valor))
            elif prop == "border-radius":
                ok = all(re.match(r"^(var\(--radio-[\w-]+\)|0)$", parte) for parte in re.findall(r"var\([^)]*\)|\S+", valor))
            elif prop == "font":
                ok = not re.search(r"\d", sin_funciones(valor))
            elif ESPACIADO.match(prop):
                ok = all(abs(float(x)) <= 3 for x in re.findall(r"(-?\d+(?:\.\d+)?)px", sin_funciones(valor, ("var", "env"))))
            if not ok and not permitido(sel, prop, valor):
                inf.falla(g, f"literal fuera de la escala · {donde}")
                problemas += 1
    # cada var(--x) usada está definida (en :root, en una regla o en los estilos en línea de ui.py: --c y --cuadro)
    definidas = set(T.TOKENS) | set(T.TOKENS_TELEFONO) | locales | {"--c", "--c-tinte", "--p", "--cuadro"}
    usadas = set(re.findall(r"var\(\s*(--[\w-]+)", limpio))
    for py in BASE_PY + PAGINAS_PY:
        usadas |= {u for u in re.findall(r"var\((--[\w-]+)\)", py.read_text(encoding="utf-8")) if not u.endswith("-")}
    for nombre in sorted(usadas - definidas):
        inf.falla(g, f"var({nombre}) se usa y no está definida")
        problemas += 1
    for nombre in RETIRADOS:
        if nombre in T.TOKENS or re.search(re.escape(nombre) + r"\b", limpio):
            inf.falla(g, f"{nombre} se retiró y sigue en estilos.css")
            problemas += 1
    for nombre in NUEVOS + PROPIOS:
        if nombre not in T.TOKENS:
            inf.falla(g, f"falta el token {nombre} en :root")
            problemas += 1
    if not problemas:
        inf.ok(g, f"{len(todas)} reglas sin colores, tamaños, pesos, interlineados, radios, sombras ni espaciados literales "
                  f"(salvo la lista blanca de la app); {len(usadas)} var() definidas; {len(RETIRADOS)} tokens retirados ausentes")
    # avisar de las clases del bloque de compatibilidad que ya nadie usa
    compat = texto.split("compatibilidad (inicio)", 1)[1].split("compatibilidad (fin)", 1)[0] if "compatibilidad (inicio)" in texto else ""
    clases = sorted(set(re.findall(r"\.([a-z][\w-]*)", T.quitar_comentarios(compat))))
    codigo = "\n".join(p.read_text(encoding="utf-8") for p in BASE_PY + PAGINAS_PY)
    sin_uso = [c for c in clases if not re.search(r"(?<![\w-])" + re.escape(c) + r"(?![\w-])", codigo)]
    if sin_uso:
        inf.aviso(g, "clases de compatibilidad que ya nadie usa (se pueden borrar): " + ", ".join(sin_uso))


def _luminancia(c):
    r, g, b, _a = T.rgba(c)
    lin = [(x / 255) / 12.92 if x / 255 <= 0.04045 else ((x / 255 + 0.055) / 1.055) ** 2.4 for x in (r, g, b)]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contraste(a, b):
    la, lb = sorted((_luminancia(a), _luminancia(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def comprobar_contraste(inf):
    """Contraste WCAG de cada par texto/fondo y marca/superficie de CONTRASTES (antes: paridad con app/tokens.css, que se
    retiró: el Dash ahora sigue la referencia que eligió el usuario)."""
    g = "Contraste"
    mal = 0
    for texto, fondo, minimo in CONTRASTES:
        r = contraste(texto, fondo)
        if r + 1e-9 < minimo:
            inf.falla(g, f"{texto} sobre {fondo}: {r:.2f}:1 (mínimo {minimo:g}:1)")
            mal += 1
    if not mal:
        peor = min(CONTRASTES, key=lambda x: contraste(x[0], x[1]) / x[2])
        inf.ok(g, f"{len(CONTRASTES)} pares con su mínimo (4,5:1 texto, 3:1 texto de 24 px o más y marcas); el más justo: "
                  f"{peor[0]} sobre {peor[1]} {contraste(peor[0], peor[1]):.2f}:1")


def comprobar_roles(inf):
    g = "Roles"
    mal = 0
    paleta = T.colores_de_la_paleta()
    for rol, tok in T.ROL_TOKEN.items():
        if tok not in T.TOKENS:
            inf.falla(g, f"ROL[{rol!r}] apunta a {tok}, que no está en :root")
            mal += 1
        elif T.rgba(tok) != paleta.get(tok):
            inf.falla(g, f"ROL[{rol!r}] no es el color de {tok}")
            mal += 1
    if not mal:
        inf.ok(g, f"los {len(T.ROL)} roles de ROL son tokens de :root ({len(set(T.ROL_TOKEN.values()))} tokens distintos)")


# --- Python -----------------------------------------------------------------------------------------------------------
HEX = re.compile(r"(?<![\w&/])#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3})(?![0-9A-Za-z_-])")
RGB = re.compile(r"\b(?:rgba?|hsla?)\(\s*\d")
TAM = re.compile(r"font-size|fontSize|\bfont_size\s*=|(?:font|textfont|tickfont|insidetextfont|outsidetextfont|titlefont)\s*=\s*dict\("
                 r"(?:[^()]|\([^()]*\))*?\bsize\s*=\s*\d", re.S)
PROHIBIDOS = [
    (r"\bCOL\[", "COL[…]: colores sueltos (usa ui.traza o ui.ROL)"),
    (r"\bCOLOR_MODELO\b", "COLOR_MODELO (el color sale del rol)"),
    (r"\bopcion_punto\b", "opcion_punto (el segmentado no lleva puntos)"),
    (r"\bpunto\s*=", "punto= (sin puntos de color)"),
    (r"segmentado__punto", "segmentado__punto"),
    (r"className\s*=\s*[\"']punto\b", "className=\"punto\""),
    (r"aviso\((?:[^()]|\([^()]*\))*?,\s*[\"']info[\"']", "aviso(…, \"info\") (la variante teñida se retiró)"),
    (r"go\.Waterfall", "go.Waterfall (la cascada es go.Bar con base)"),
    (r"shape\s*=\s*[\"']spline[\"']", "shape=\"spline\""),
    (r"showlegend\s*=\s*True", "showlegend=True (la leyenda es HTML)"),
    (r"\bderecha\s*=", "derecha= (un control nunca va a la derecha de un título)"),
    (r"\b[xy]axis_title\b|\btitle_text\b", "título de eje (la unidad va con ui.unidad_eje)"),
    (r"add_[vh]line\((?:[^()]|\([^()]*\))*?\bdash\b", "add_vline/add_hline con dash (las referencias son sólidas)"),
    (r"hovertemplate\s*=\s*f?[\"'][^\"'\n]*%\{[xyz]", "hovertemplate con %{x}/%{y}/%{z} (el texto va ya formateado en customdata)"),
]
# Solo en paginas/*.py: el rayado y las bandas salen de ui.py (una sola especificación)
PROHIBIDOS_PAGINAS = [
    (r"\bpattern\s*=|[\"']pattern[\"']\s*:|\bfillpattern\b", "rayado escrito a mano (usa ui.traza(rol, \"rayada\"), ui.barras_foco o ui.traza(rol, \"escalon_rayado\"))"),
    (r"\b(?:px|font_size)\s*=\s*\d|\bborder-?[Rr]adius\b", "medida escrita a mano (usa las clases de estilos.css)"),
]
# 11 y 12 nombran los experimentos del informe («experimento 11 / experimento 12»), no son cifras
SUELTOS_PERMITIDOS = re.compile(r"^(2024|2025|2026|1|0|7|11|12|95|E1|E11|E12|54|72|2)$")


def _textos(fuente):
    """(línea, texto) de las cadenas del código (también las partes de los f-strings) y el código sin comentarios."""
    cadenas, lineas = [], fuente.splitlines(keepends=True)
    tipos = {tokenize.STRING} | {getattr(tokenize, n) for n in ("FSTRING_MIDDLE",) if hasattr(tokenize, n)}
    comentarios = []
    for tok in tokenize.generate_tokens(io.StringIO(fuente).readline):
        if tok.type in tipos:
            cadenas.append((tok.start[0], tok.string))
        elif tok.type == tokenize.COMMENT:
            comentarios.append(tok.start)
    for fila, col in reversed(comentarios):          # el código sin comentarios, con las mismas líneas
        lineas[fila - 1] = lineas[fila - 1][:col] + ("\n" if lineas[fila - 1].endswith("\n") else "")
    return cadenas, "".join(lineas)


def _rango_compat(fuente):
    lineas = fuente.splitlines()
    ini = next((i for i, l in enumerate(lineas, 1) if "compatibilidad (inicio)" in l), None)
    fin = next((i for i, l in enumerate(lineas, 1) if "compatibilidad (fin)" in l), None)
    return (ini, fin) if ini and fin else None


def _cifras_a_mano(arbol):
    """Cadenas visibles con miles o decimales escritos a mano (fuera de {…}); y otros números sueltos (aviso)."""
    malas, sueltas = [], []
    docs = set()
    for nodo in ast.walk(arbol):
        if isinstance(nodo, (ast.Module, ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef)) and nodo.body and \
                isinstance(nodo.body[0], ast.Expr) and isinstance(getattr(nodo.body[0], "value", None), ast.Constant):
            docs.add(id(nodo.body[0].value))
    for nodo in ast.walk(arbol):
        partes = []
        if isinstance(nodo, ast.JoinedStr):
            partes = [(v.value, nodo.lineno) for v in nodo.values if isinstance(v, ast.Constant) and isinstance(v.value, str)]
            for v in nodo.values:
                if isinstance(v, ast.Constant):
                    docs.add(id(v))
        elif isinstance(nodo, ast.Constant) and isinstance(nodo.value, str) and id(nodo) not in docs:
            partes = [(nodo.value, nodo.lineno)]
        for texto, linea in partes:
            if re.search(r"(?<![\d.,])\d{1,3}(?:\.\d{3})+(?![\d,])|(?<![\d.])\d+,\d+(?!\d)", texto):
                malas.append((linea, texto[:70]))
            elif re.search(r"[a-záéíóúñ]", texto, re.I):
                for x in re.findall(r"(?<![\w.,-])(\d+)(?![\w.,])", texto):
                    if not SUELTOS_PERMITIDOS.match(x):
                        sueltas.append((linea, x, texto[:50]))
    return malas, sueltas


def comprobar_python(inf, con_paginas=True):
    archivos = BASE_PY + (PAGINAS_PY if con_paginas else [])
    for py in archivos:
        rel = py.relative_to(AQUI).as_posix()
        g = f"Python · {rel}"
        fuente = py.read_text(encoding="utf-8")
        cadenas, codigo = _textos(fuente)
        mal = 0
        for linea, s in cadenas:
            for patron, que in ((HEX, "color hex escrito a mano"), (RGB, "rgb()/rgba() escrito a mano")):
                m = patron.search(s)
                if m:
                    inf.falla(g, f"{que} en la línea {linea}: {m.group(0)}")
                    mal += 1
        for m in TAM.finditer(codigo):
            inf.falla(g, f"tamaño de letra escrito a mano en la línea {codigo.count(chr(10), 0, m.start()) + 1} (usa las clases o ui.fuente_svg)")
            mal += 1
        compat = _rango_compat(fuente) if py.name == "ui.py" else None
        for patron, que in (PROHIBIDOS + PROHIBIDOS_PAGINAS if py.parent.name == "paginas" else PROHIBIDOS):
            for m in re.finditer(patron, codigo, re.S):
                linea = codigo.count("\n", 0, m.start()) + 1
                if compat and compat[0] <= linea <= compat[1]:
                    continue
                inf.falla(g, f"{que} · línea {linea}")
                mal += 1
        if py.parent.name == "paginas":
            malas, sueltas = _cifras_a_mano(ast.parse(fuente))
            for linea, texto in malas:
                inf.falla(g, f"cifra escrita a mano en la línea {linea}: «{texto}»")
                mal += 1
            if sueltas:
                inf.aviso(g, f"{len(sueltas)} números sueltos en cadenas (revisar que salgan de datos/): "
                             + "; ".join(f"l. {l} «{x}»" for l, x, _t in sueltas[:8]) + (" …" if len(sueltas) > 8 else ""))
        if compat:
            usos = sorted({n for p in PAGINAS_PY for n in ("COL[", "COLOR_MODELO", "opcion_punto", "pie_fuente", "ver_datos", "figura(",
                                                          "fichas_anuales", "derecha=", "punto=") if n in p.read_text(encoding="utf-8")})
            inf.nota(g, f"bloque de compatibilidad en las líneas {compat[0]}–{compat[1]}; lo usan las páginas sin migrar: "
                        + (", ".join(usos) if usos else "nadie (ya se puede borrar)"))
        if not mal:
            inf.ok(g, "sin colores ni tamaños escritos a mano y sin las piezas retiradas")


# --- Paleta: validate_palette.js del método dataviz ------------------------------------------------------------------
# (gráfico, tokens que se ven juntos, todos los pares, lo que se espera: «todo» = código 0; si no, estado de cada control)
CONJUNTOS = [
    ("Lo que proponemos solo (azul)", ["--serie-modelo"], False, "todo"),
    ("Proponemos (azul) frente al plan que recorta (rosa)", ["--serie-modelo", "--serie-recorta"], True, "todo"),
    ("Proponemos (azul) frente a hoy (gris)", ["--serie-modelo", "--serie-hoy"], True, {"cvd": "PASS", "normal": "PASS", "contraste": "PASS"}),
    ("Hoy (gris) frente al plan que recorta (rosa)", ["--serie-hoy", "--serie-recorta"], True, {"cvd": "PASS", "normal": "PASS", "contraste": "PASS"}),
    ("Azul, rosa y gris juntos (Qué gana: hoy, reasignar, recortar)", ["--serie-modelo", "--serie-recorta", "--serie-hoy"], True,
     {"cvd": "PASS", "normal": "PASS", "contraste": "PASS"}),
    ("Pronóstico · real, proponemos y contexto", ["--serie-real", "--serie-modelo", "--serie-contexto"], True, {"cvd": "PASS", "normal": "PASS"}),
    ("Horario · proponemos, hoy, real/oráculo y recorta", ["--serie-modelo", "--serie-hoy", "--serie-real", "--serie-recorta"], True,
     {"cvd": "PASS", "normal": "PASS"}),
    ("Rutas en su orden (solo muestras)", ["--ruta-silencio", "--ruta-cra54", "--ruta-cl72"], True, "todo"),
]
CONTROLES = {"banda": "Lightness band", "croma": "Chroma floor", "cvd": "CVD separation", "normal": "Normal-vision floor", "contraste": "Contrast vs surface"}


def _validador():
    """El validador de paletas es externo y no viaja en el repositorio: su ruta va en VALIDADOR_PALETA."""
    ruta = os.environ.get("VALIDADOR_PALETA", "").strip()
    return Path(ruta) if ruta and Path(ruta).is_file() else None


def comprobar_paleta(inf):
    g = "Paleta"
    node, script = shutil.which("node"), _validador()
    if not node or not script:
        inf.nota(g, "no están node o el validador de paletas (VALIDADOR_PALETA con la ruta de validate_palette.js): se omite la validación de la paleta")
        return
    superficie = T.color("--superficie")
    mal = 0
    for nombre, toks, todos, espera in CONJUNTOS:
        colores = ",".join(T.color(t) for t in toks)
        cmd = [node, str(script), colores, "--mode", "light", "--surface", superficie] + (["--pairs", "all"] if todos else [])
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
        estados = {k: (re.search(r"\[(PASS|FAIL|WARN)\]\s+" + re.escape(v), r.stdout) or [None, "?"])[1] for k, v in CONTROLES.items()}
        if espera == "todo":
            bien = r.returncode == 0
        else:
            bien = all(estados.get(k) == v for k, v in espera.items())
        if bien:
            inf.ok(g, f"{nombre}: " + " · ".join(f"{k} {estados[k]}" for k in ("cvd", "normal", "contraste")))
        else:
            inf.falla(g, f"{nombre} ({colores}): se esperaba {espera} y el validador dio {estados} (código {r.returncode})")
            mal += 1


# --- En el navegador ------------------------------------------------------------------------------------------------------
# (pantalla, ruta, máximo de tamaños de letra, ¿lleva cifra protagonista?). La escala de la referencia tiene más pasos
# (título enorme, cifra, protagonista): hasta 8 por pantalla.
PANTALLAS = [("inicio", "/", 8, True), ("pronostico", "/pronostico", 8, False), ("horario", "/horario", 8, False),
             ("despacho", "/despacho", 8, False), ("alertas", "/alertas", 8, False),
             ("recomendaciones", "/recomendaciones", 8, False), ("operacion", "/operacion", 8, False), ("monitoreo", "/monitoreo", 8, False),
             ("modelo", "/modelo", 8, False), ("resultado", "/resultado", 8, True), ("enlaces", "/enlaces", 7, False)]

JS = r"""() => {
  const raiz = document.querySelector('#contenido') || document.body;
  const visible = el => { if (!el.getClientRects().length) return false; const cs = getComputedStyle(el);
    return cs.visibility !== 'hidden' && cs.display !== 'none' && parseFloat(cs.opacity) > 0; };
  const fuera = el => el.closest('svg, .barra, .dash-slider-mark, .dash-datepicker-content, .js-plotly-plot');
  const desc = el => el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') +
    (typeof el.className === 'string' && el.className.trim() ? '.' + el.className.trim().split(/\s+/).slice(0, 2).join('.') : '');
  const tamanos = {}, pesos = {}, colores = {}, pantalla = [], cabeceras = [];
  const COLORES_PANTALLA = new Set(%COLORES%);
  for (const el of raiz.querySelectorAll('*')) {
    if (fuera(el) || !visible(el)) continue;
    const cs = getComputedStyle(el);
    const conTexto = Array.from(el.childNodes).some(n => n.nodeType === 3 && n.textContent.trim()) || el.tagName === 'INPUT';
    if (conTexto) {
      tamanos[cs.fontSize] = tamanos[cs.fontSize] || desc(el);
      pesos[cs.fontWeight] = pesos[cs.fontWeight] || desc(el);
      colores['texto|' + cs.color] = colores['texto|' + cs.color] || desc(el);
    }
    colores['fondo|' + cs.backgroundColor] = colores['fondo|' + cs.backgroundColor] || desc(el);
    for (const l of ['Top', 'Right', 'Bottom', 'Left']) {
      if (parseFloat(cs['border' + l + 'Width']) > 0 && cs['border' + l + 'Style'] !== 'none') {
        const k = 'borde|' + cs['border' + l + 'Color']; colores[k] = colores[k] || desc(el); }
    }
    if (COLORES_PANTALLA.has(cs.backgroundColor) && !el.closest('.cuadro-color')) pantalla.push(desc(el));
    if (/^H[1-6]$/.test(el.tagName)) cabeceras.push(+el.tagName[1]);
  }
  const escala = {};
  for (const t of ['--t-xs', '--t-s', '--t-m', '--t-l', '--t-xl', '--t-2xl', '--t-3xl', '--t-cifra', '--t-hero']) {
    const p = document.createElement('span'); p.style.fontSize = 'var(' + t + ')'; document.body.appendChild(p);
    escala[getComputedStyle(p).fontSize] = t; p.remove(); }
  const vista = document.documentElement.clientWidth, ancho = document.documentElement.scrollWidth, anchos = [];
  if (ancho > vista + 1) for (const el of document.querySelectorAll('body *')) {
    const r = el.getBoundingClientRect(); if (r.width > 0 && r.right > vista + 1) anchos.push(desc(el) + ' → ' + Math.round(r.right));
    if (anchos.length >= 6) break; }
  return {tamanos, pesos, colores, pantalla, cabeceras, escala, vista, ancho, anchos,
          heroes: document.querySelectorAll('.cifra--hero').length,
          saldos_en_heroe: document.querySelectorAll('.cifra--hero .saldo').length};
}"""


def _rgb(texto):
    texto = texto.strip()
    m = re.match(r"rgba?\(\s*([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)(?:[,\s/]+([\d.]+))?\s*\)", texto)
    if m:
        return tuple(round(float(m.group(i))) for i in (1, 2, 3)) + (float(m.group(4)) if m.group(4) else 1.0,)
    m = re.match(r"color\(srgb\s+([\d.e-]+)\s+([\d.e-]+)\s+([\d.e-]+)(?:\s*/\s*([\d.]+))?\)", texto)
    if m:
        return tuple(round(float(m.group(i)) * 255) for i in (1, 2, 3)) + (float(m.group(4)) if m.group(4) else 1.0,)
    return None


def vivo(inf, puerto, capturas=None):
    if puerto == 8050:
        inf.falla("En vivo", "el 8050 es la ventana del usuario: usa otro puerto")
        return
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        inf.nota("En vivo", f"este Python no tiene Playwright: corre la parte en vivo con «python {Path(__file__).name} --vivo {puerto}» "
                            "desde un Python que lo tenga (el global del equipo, con Edge instalado)")
        return
    paleta = {c[:3] for c in T.colores_de_la_paleta().values()}
    fuertes = []   # el color de pantalla se retiró con la barra lateral
    js = JS.replace("%COLORES%", json.dumps([f"rgb({r}, {g}, {b})" for r, g, b, _a in fuertes]))
    base = f"http://127.0.0.1:{puerto}"
    if capturas:
        Path(capturas).mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        nav = p.chromium.launch(channel="msedge", headless=True)
        for ancho, alto in ((1366, 900), (400, 860)):
            pg = nav.new_context(viewport={"width": ancho, "height": alto}, device_scale_factor=1).new_page()
            errores, avisos = [], []
            pg.on("console", lambda m: (errores if m.type == "error" else avisos).append(m.text) if m.type in ("error", "warning") else None)
            pg.on("pageerror", lambda e: errores.append(f"pageerror: {e}"))
            for nombre, ruta, limite, protagonista in PANTALLAS:
                g = f"En vivo · {nombre} · {ancho} px"
                errores.clear()
                avisos.clear()
                pg.goto(base + ruta, wait_until="networkidle")
                pg.wait_for_selector("#contenido h1", timeout=30000)
                pg.wait_for_function("() => !document.querySelector('[data-dash-is-loading=\"true\"]')", timeout=60000)
                pg.wait_for_timeout(1200)
                d = pg.evaluate(js)
                if capturas:
                    pg.screenshot(path=str(Path(capturas) / f"{nombre}_{ancho}.png"), full_page=True)
                mal = 0
                for e in errores:
                    inf.falla(g, f"error de consola: {e[:160]}")
                    mal += 1
                for a in avisos[:3]:
                    inf.aviso(g, f"aviso de consola: {a[:160]}")
                tams = sorted(d["tamanos"], key=lambda s: float(s[:-2]))
                fuera_escala = [t for t in tams if t not in d["escala"]]
                if len(tams) > limite:
                    inf.falla(g, f"{len(tams)} tamaños de letra (máx. {limite}): " + ", ".join(f"{t} ({d['tamanos'][t]})" for t in tams))
                    mal += 1
                for t in fuera_escala:
                    inf.falla(g, f"tamaño fuera de la escala: {t} en {d['tamanos'][t]}")
                    mal += 1
                for peso, el in d["pesos"].items():
                    if peso not in ("400", "500", "600"):
                        inf.falla(g, f"peso {peso} en {el}")
                        mal += 1
                for clave, el in d["colores"].items():
                    tipo, valor = clave.split("|", 1)
                    c = _rgb(valor)
                    if c is None or c[3] == 0:
                        continue
                    if not any(all(abs(a - b) <= 1 for a, b in zip(c[:3], q)) for q in paleta):
                        inf.falla(g, f"color de {tipo} fuera de la paleta: {valor} en {el}")
                        mal += 1
                for el in d["pantalla"][:5]:
                    inf.falla(g, f"color de pantalla fuera de .cuadro-color: {el}")
                    mal += 1
                cab = d["cabeceras"]
                saltos = [f"h{a}→h{b}" for a, b in zip(cab, cab[1:]) if b > a + 1]
                if cab and cab[0] != 1 or saltos:
                    inf.falla(g, "encabezados con saltos: " + (", ".join(saltos) or f"empieza en h{cab[0]}"))
                    mal += 1
                if d["heroes"] > 1 or (protagonista and (d["heroes"] != 1 or d["saldos_en_heroe"] < 2)):
                    inf.falla(g, f"cifra protagonista: {d['heroes']} (con {d['saldos_en_heroe']} saldos dentro); "
                                 + ("se espera exactamente una con al menos dos fichas de saldo" if protagonista else "como mucho una"))
                    mal += 1
                if ancho == 400 and d["ancho"] > d["vista"] + 1:
                    inf.falla(g, f"desplazamiento horizontal: {d['ancho']} px de contenido en {d['vista']} px · " + "; ".join(d["anchos"]))
                    mal += 1
                resumen = (f"{len(tams)} tamaños ({', '.join(tams)}) · {len(d['colores'])} colores calculados · "
                           f"{len(errores)} errores de consola · contenido de {d['ancho']} px en {d['vista']} px")
                (inf.ok if not mal else inf.nota)(g, resumen)
            pg.context.close()
        nav.close()


# --- Principal --------------------------------------------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Prueba del sistema de diseño del laboratorio Dash (DISENO.md §9).")
    ap.add_argument("--vivo", type=int, metavar="PUERTO", help="revisa también las once pantallas en el navegador (nunca 8050)")
    ap.add_argument("--solo-vivo", action="store_true", help="solo la parte en el navegador")
    ap.add_argument("--solo-base", action="store_true", help="en el código, solo la base (sin paginas/*.py)")
    ap.add_argument("--capturas", metavar="CARPETA", help="guarda una captura de cada pantalla a 1366 y a 400 px")
    ap.add_argument("--informe", metavar="ARCHIVO.json", help="escribe el informe en JSON")
    a = ap.parse_args()
    inf = Informe()
    if not a.solo_vivo:
        comprobar_contraste(inf)
        comprobar_roles(inf)
        comprobar_css(inf)
        comprobar_python(inf, con_paginas=not a.solo_base)
        comprobar_paleta(inf)
    if a.vivo:
        vivo(inf, a.vivo, a.capturas)
    salida = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace") if hasattr(sys.stdout, "buffer") else sys.stdout
    for titulo, lista in (("Bien", inf.bien), ("Notas", inf.notas), ("Avisos", inf.avisos), ("Fallas", inf.fallas)):
        if lista:
            print(f"\n== {titulo} ({len(lista)}) ==", file=salida)
            for grupo, texto in lista:
                print(f"  [{grupo}] {texto}", file=salida)
    print(f"\nResultado: {'FALLA' if inf.fallas else 'PASA'} · {len(inf.bien)} bien · {len(inf.avisos)} avisos · {len(inf.fallas)} fallas",
          file=salida)
    salida.flush()
    if a.informe:
        Path(a.informe).parent.mkdir(parents=True, exist_ok=True)
        Path(a.informe).write_text(json.dumps({k: [list(x) for x in getattr(inf, k)] for k in ("bien", "notas", "avisos", "fallas")},
                                              ensure_ascii=False, indent=1), encoding="utf-8")
    sys.exit(1 if inf.fallas else 0)


if __name__ == "__main__":
    main()
