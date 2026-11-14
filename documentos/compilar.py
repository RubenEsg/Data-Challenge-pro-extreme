"""Compila los documentos de entrega con Tectonic y los revisa.

    python EntregaFinal/documentos/compilar.py            -> E01, E02, presentación (PDF) y presentación (PPTX)
    python EntregaFinal/documentos/compilar.py E01        -> solo uno (E01, E02 o presentacion)
    python EntregaFinal/documentos/compilar.py --sin-datos   (no regenera cifras, figuras ni la tabla de la API)

El Python que lo ejecuta necesita requisitos_documentos.txt (matplotlib, pypdf, pymupdf, python-pptx). La tabla de
endpoints se genera con el Python del venv de la API (variable API_PYTHON; por omisión api_frecuencias/.venv); si no
está, tabla_api.py usa docs/openapi.json.

Pasos:
  1. datos_documentos.py: cifras (generado/cifras.tex), colores por rol (generado/colores.tex) y figuras;
     tabla_api.py: generado/tabla_api.tex.
  2. Tectonic sobre cada .tex (Tectonic se busca en la variable TECTONIC, en el PATH o en
     machine_learning/entrega 3/articulo/herramientas/tectonic.exe, como en informe/compilar.py).
  3. Revisa cada .log: referencias o citas sin resolver y cajas desbordadas de más de 10 pt.
  4. Cuenta las páginas y falla si se rompe un presupuesto: E01 = 2; E02 entre 12 y 16; presentación entre 12 y 15.
  5. Busca en el texto de cada PDF cadenas que nunca deben salir (cadenas de conexión, claves) y cifras «s. d.».
  6. Arma presentacion_final.pptx editable: de fondo, la parte gráfica de cada página (sin texto) con su texto
     alternativo; encima, el título de la diapositiva y cada línea de texto como cuadros de texto nativos en su misma
     posición; y las notas del orador de notas_orador.txt con las cifras de generado/ ({{Macro}}). El PDF sigue siendo
     la versión principal.
Sale con código 1 si algo falla.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent
ENTREGA = AQUI.parent
TECTONIC_LOCAL = AQUI.parents[2] / "entrega 3" / "articulo" / "herramientas" / "tectonic.exe"
UMBRAL_PT = 10.0
DOCUMENTOS = {
    "E01": ("E01_documento_ejecutivo.tex", 2, 2),
    "E02": ("E02_especificacion_tecnica.tex", 12, 16),
    "presentacion": ("presentacion_final.tex", 12, 15),
}
PROHIBIDAS = [r"postgres(?:ql)?(?:\+\w+)?://", r"(?i)password\s*=", r"(?i)contraseña\s*[:=]", r"(?i)api_key\s*=\s*\S{8,}"]


def tectonic() -> str:
    for candidato in (os.environ.get("TECTONIC"), shutil.which("tectonic"), str(TECTONIC_LOCAL)):
        if candidato and Path(candidato).exists():
            return candidato
    sys.exit("No se encontró Tectonic: https://tectonic-typesetting.github.io/ (o fija la variable TECTONIC)")


def python_api() -> str:
    if os.environ.get("API_PYTHON"):
        return os.environ["API_PYTHON"]
    for rel in (".venv/Scripts/python.exe", ".venv/bin/python"):
        p = ENTREGA / "api_frecuencias" / rel
        if p.exists():
            return str(p)
    return sys.executable


def revisar_log(log: str) -> list[str]:
    problemas = []
    for patron, que in ((r"LaTeX Warning: Reference `([^']+)' on page", "referencia sin resolver"),
                        (r"LaTeX Warning: Citation `([^']+)' on page", "cita sin resolver"),
                        (r"LaTeX Warning: There were undefined references", "referencias sin definir")):
        for m in re.finditer(patron, log):
            problemas.append(f"{que}: {m.group(1) if m.groups() else ''}")
    for m in re.finditer(r"Overfull \\hbox \(([\d.]+)pt too wide\)[^\n]*?(?:lines? (\d+)(?:--(\d+))?)?\n", log):
        if float(m.group(1)) > UMBRAL_PT:
            problemas.append(f"caja desbordada {m.group(1)} pt, líneas {m.group(2)}-{m.group(3) or m.group(2)}")
    for m in re.finditer(r"Overfull \\vbox \(([\d.]+)pt too high\)", log):
        if float(m.group(1)) > UMBRAL_PT:
            problemas.append(f"caja vertical desbordada {m.group(1)} pt")
    for m in re.finditer(r"Missing character: There is no (\S+)", log):
        problemas.append(f"carácter sin glifo: {m.group(1)}")
    return problemas


def generar_datos() -> list[str]:
    problemas = []
    r = subprocess.run([sys.executable, str(AQUI / "datos_documentos.py")], cwd=AQUI, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", check=False)
    print(r.stdout.strip())
    if r.returncode != 0:
        problemas.append(f"datos_documentos.py terminó con {r.returncode}: {r.stderr[-1500:]}")
    r = subprocess.run([python_api(), str(AQUI / "tabla_api.py")], cwd=AQUI, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", check=False)
    print(r.stdout.strip())
    if r.returncode != 0:
        problemas.append(f"tabla_api.py terminó con {r.returncode}: {r.stderr[-1500:]}")
    return problemas


def compilar(nombre: str, exe: str) -> tuple[Path | None, list[str]]:
    tex, minimo, maximo = DOCUMENTOS[nombre]
    comando = [exe, "--keep-logs", "--chatter", "minimal", tex]
    print("$", " ".join(comando))
    r = subprocess.run(comando, cwd=AQUI, capture_output=True, text=True, encoding="utf-8", errors="replace",
                       check=False)
    if r.returncode != 0:
        print((r.stdout + r.stderr)[-4000:])
        return None, [f"{tex}: Tectonic terminó con código {r.returncode}"]
    pdf = AQUI / tex.replace(".tex", ".pdf")
    problemas = [f"{tex}: {p}" for p in revisar_log((AQUI / tex.replace(".tex", ".log")).read_text(
        encoding="utf-8", errors="replace"))]
    from pypdf import PdfReader
    lector = PdfReader(str(pdf))
    paginas = len(lector.pages)
    print(f"{pdf.name}: {paginas} páginas (presupuesto {minimo}–{maximo}), {pdf.stat().st_size / 1e6:.2f} MB")
    if not minimo <= paginas <= maximo:
        problemas.append(f"{pdf.name}: {paginas} páginas fuera del presupuesto {minimo}–{maximo}")
    texto = "\n".join(p.extract_text() or "" for p in lector.pages)
    for patron in PROHIBIDAS:
        if re.search(patron, texto):
            problemas.append(f"{pdf.name}: aparece una cadena prohibida ({patron})")
    if "s. d." in texto or "s. d." in texto:
        problemas.append(f"{pdf.name}: hay cifras sin dato («s. d.»): falta alguna evidencia")
    return pdf, problemas


def valores_macros() -> dict[str, str]:
    """Valor en texto plano de cada macro de una línea de generado/cifras.tex y generado/respuesta_tabla.tex (para
    reemplazar los {{Nombre}} de las notas del orador con las mismas cifras de la diapositiva)."""
    valores = {}
    for archivo in ("cifras.tex", "respuesta_tabla.tex"):
        p = AQUI / "generado" / archivo
        if not p.exists():
            continue
        for m in re.finditer(r"^\\newcommand\{\\(\w+)\}\{(.*)\}(?:%.*)?$", p.read_text(encoding="utf-8"),
                             flags=re.MULTILINE):
            v = m.group(2)
            for patron, reemplazo in ((r"\\(?:path|emph|textbf|texttt)\{([^{}]*)\}", r"\1"),
                                      (r"\\ensuremath\{\\le\}", "≤"), (r"\\ensuremath\{\\ge\}", "≥")):
                v = re.sub(patron, reemplazo, v)
            for a, b in (("--", "–"), ("~", " "), ("\\,", " "), ("\\%", "%"), ("\\_", "_"), ("\\&", "&")):
                v = v.replace(a, b)
            valores[m.group(1)] = v
    return valores


def notas() -> list[str]:
    bloques, actual = [], None
    for linea in (AQUI / "notas_orador.txt").read_text(encoding="utf-8").splitlines():
        if linea.startswith("=== "):
            if actual is not None:
                bloques.append("\n".join(actual).strip())
            actual = []
        elif actual is not None:
            actual.append(linea)
    if actual is not None:
        bloques.append("\n".join(actual).strip())
    valores = valores_macros()
    # Las notas se escriben en párrafos con saltos de línea de 120 columnas: se unen en párrafos y se resuelven
    # los {{Nombre}} con la cifra de la macro.
    return [re.sub(r"\{\{(\w+)\}\}", lambda m: valores.get(m.group(1), m.group(0)), " ".join(b.split()))
            for b in bloques]


# Texto alternativo de la parte gráfica de cada diapositiva (el texto va aparte, en cuadros de texto editables).
ALT_GRAFICOS = {
    "¿Cada cuánto": "Portada sobre fondo gris claro, con una tarjeta blanca que destaca tres cifras.",
    "El problema y lo que entregamos": "Tres tarjetas en columnas: la situación de hoy, la pregunta del reto (en azul) y "
                                       "lo que entregamos.",
    "Datos validados": "Tarjetas con las seis dimensiones de calidad de §6.3, la lectura y el contraste de los "
                       "consolidados de Extreme, la lectura incremental, la carga idempotente y la prueba de no "
                       "fuga.",
    "El modelo le gana": "Gráfico de puntos con el WAPE y su intervalo del 95 % del modelo activo, el modelo anterior y "
                         "las líneas base B1 y B2, y una tabla de robustez por ruta, año y horizonte.",
    "Incertidumbre y ciclo de vida": "Tarjetas de cobertura, explicabilidad y ciclo de vida del modelo, y la captura de "
                                     "la pantalla Monitoreo del tablero con el error, el sesgo y la cobertura del "
                                     "modelo activo.",
    "Recomendaciones viables": "Tarjeta con la función objetivo, dos cifras del optimizador y la captura de la pantalla "
                               "Recomendaciones del tablero.",
    "Alertas que se pueden creer": "Gráfico de barras de alertas por ruta y día por código, antes y después de la "
                                   "persistencia, y la captura de la bandeja de alertas del tablero.",
    "Se conecta sin interferir": "Lista de controles de no interferencia en la réplica y gráfico de barras horizontales "
                                 "del p95 por recurso frente al límite de 2 segundos.",
    "Ingeniería que se puede auditar": "Gráfico de barras de pruebas por nivel, dos cifras (cobertura y operaciones) y "
                                       "una lista de integración continua, SonarQube, Docker y observabilidad.",
    "Demostración del ciclo": "Diagrama de seis pasos numerados: llegada de datos, lectura incremental, evaluación del "
                              "error, candidato, comparación con el activo y decisión.",
    "La respuesta a la pregunta": "Tabla de la respuesta por ruta (salidas, cada cuánto despachar por franja, horas no "
                                  "viables, pasajeros, buses en ruta y recaudo) y una tarjeta de atención inmediata.",
    "Qué gana Sobusa": "Seis gráficos de escalones con las salidas por hora de hoy (gris) y del plan que reasigna (azul), "
                       "por ruta y tipo de día, y tarjetas con las cifras del valor.",
    "Plan de implementación": "Tres fases en tarjetas (conexión, modo sombra y piloto, esta en azul) y dos tarjetas de "
                              "costos y riesgos.",
    "La decisión que pedimos": "Tres tarjetas numeradas con las decisiones que se piden a Extreme.",
}


def _lineas(pagina) -> list[dict]:
    """Líneas horizontales de texto de una página del PDF con sus tramos (texto, tamaño, color, letra) y su caja. Los
    tramos de una misma «línea» del PDF con otra línea base se separan (una cifra grande y su leyenda debajo), y el
    texto girado (ejes de los gráficos) se deja en la imagen."""
    lineas = []
    for b in pagina.get_text("dict")["blocks"]:
        if b.get("type") != 0:
            continue
        for linea in b["lines"]:
            if abs(linea.get("dir", (1, 0))[1]) > 0.01:
                continue                                              # girada: queda en el fondo gráfico
            grupos: list[list[dict]] = []
            for t in linea["spans"]:
                if not t["text"].strip():
                    continue
                if grupos and abs(grupos[-1][0]["origin"][1] - t["origin"][1]) <= 2:
                    grupos[-1].append(t)
                else:
                    grupos.append([t])
            for tramos in grupos:
                caja = (min(t["bbox"][0] for t in tramos), min(t["bbox"][1] for t in tramos),
                        max(t["bbox"][2] for t in tramos), max(t["bbox"][3] for t in tramos))
                lineas.append({"bbox": caja, "tramos": tramos, "texto": "".join(t["text"] for t in tramos).strip()})
    return lineas


def _formato(run, tramo, escala_pt: float) -> None:
    from pptx.dml.color import RGBColor
    from pptx.util import Pt
    letra = tramo["font"]
    run.font.size = Pt(round(tramo["size"] * escala_pt, 1))
    run.font.name = "Inter Medium" if "Medium" in letra else "Inter"
    run.font.bold = "SemiBold" in letra or "Bold" in letra
    c = tramo["color"]
    run.font.color.rgb = RGBColor((c >> 16) & 255, (c >> 8) & 255, c & 255)


def armar_pptx(pdf: Path) -> list[str]:
    """PPTX editable: cada diapositiva lleva de fondo la parte gráfica de la página del PDF (tarjetas, gráficos y
    capturas, sin el texto) con su texto alternativo, el título como título de la diapositiva y cada línea de texto como
    cuadro de texto nativo en su misma posición, y las notas del orador. El PDF sigue siendo la versión principal."""
    import tempfile

    import pymupdf
    from pptx import Presentation
    from pptx.enum.text import MSO_ANCHOR, MSO_AUTO_SIZE, PP_ALIGN
    from pptx.util import Emu
    textos = notas()
    prs = Presentation()
    prs.slide_width, prs.slide_height = Emu(12192000), Emu(6858000)          # 16:9 (13,333 × 7,5 pulgadas)
    prs.core_properties.title = "¿Cada cuánto despachar? Presentación final"
    prs.core_properties.author = "Abrahan Basto Martínez, Rubén Esguerra Fernández, Paula Gómez"
    prs.core_properties.language = "es-CO"
    solo_titulo = prs.slide_layouts[5]
    problemas = []
    with tempfile.TemporaryDirectory() as tmp, pymupdf.open(pdf) as doc:
        n = len(doc)
        for i, pagina in enumerate(doc):
            escala = prs.slide_width / pagina.rect.width                       # EMU por punto del PDF
            escala_pt = escala / 12700                                         # punto del PPTX por punto del PDF
            lineas = _lineas(pagina)
            # Copia de la página sin texto: el fondo gráfico.
            sola = pymupdf.open()
            sola.insert_pdf(doc, from_page=i, to_page=i)
            fondo_pag = sola[0]
            for linea in lineas:
                fondo_pag.add_redact_annot(pymupdf.Rect(linea["bbox"]), fill=False)
            fondo_pag.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE,
                                       graphics=pymupdf.PDF_REDACT_LINE_ART_NONE)
            quedan = {(round(t["bbox"][0]), round(t["bbox"][1]), t["text"]) for x in _lineas(fondo_pag)
                      for t in x["tramos"]}
            png = Path(tmp) / f"diapositiva_{i + 1:02d}.png"
            zoom = 1920 / pagina.rect.width                                  # 1920 px de ancho (16:9)
            fondo_pag.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom)).save(png)
            sola.close()
            s = prs.slides.add_slide(solo_titulo)
            imagen = s.shapes.add_picture(str(png), 0, 0, width=prs.slide_width, height=prs.slide_height)
            arbol = s.shapes._spTree
            arbol.remove(imagen._element)
            arbol.insert(2, imagen._element)                                  # al fondo, detrás del texto
            # Título: las líneas de letra grande (≥ 15 pt) pegadas al margen izquierdo; las cifras grandes van dentro
            # de tarjetas, más a la derecha. Si no hay, la(s) línea(s) de letra más grande.
            margen = min((x["bbox"][0] for x in lineas), default=0)
            de_titulo = [x for x in lineas if x["bbox"][0] <= margen + 3 and all(t["size"] >= 15 for t in x["tramos"])]
            if not de_titulo:
                mayor = max((t["size"] for x in lineas for t in x["tramos"]), default=0)
                de_titulo = [x for x in lineas if all(abs(t["size"] - mayor) < 0.6 for t in x["tramos"])]
            titulo_txt = " ".join(x["texto"] for x in de_titulo)
            alt = next((v for k, v in ALT_GRAFICOS.items() if titulo_txt.startswith(k)),
                       f"Parte gráfica de la diapositiva {i + 1}.")
            imagen._element.nvPicPr.cNvPr.set("descr", f"Diapositiva {i + 1}, «{titulo_txt}»: {alt}")
            titulo = s.shapes.title
            if de_titulo:
                x0 = min(x["bbox"][0] for x in de_titulo)
                y0 = min(x["bbox"][1] for x in de_titulo)
                x1 = max(x["bbox"][2] for x in de_titulo)
                y1 = max(x["bbox"][3] for x in de_titulo)
                titulo.left, titulo.top = Emu(int(x0 * escala)), Emu(int(y0 * escala))
                titulo.width, titulo.height = Emu(int((x1 - x0) * escala * 1.06)), Emu(int((y1 - y0) * escala))
                tf = titulo.text_frame
                tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
                tf.vertical_anchor = MSO_ANCHOR.TOP
                tf.auto_size = MSO_AUTO_SIZE.NONE
                for k, x in enumerate(de_titulo):
                    p = tf.paragraphs[0] if k == 0 else tf.add_paragraph()
                    p.alignment = PP_ALIGN.LEFT
                    for t in x["tramos"]:
                        r = p.add_run()
                        r.text = t["text"]
                        _formato(r, t, escala_pt)
            else:
                titulo._element.getparent().remove(titulo._element)
            # El resto del texto: un cuadro por línea, en su posición.
            for x in lineas:
                if x in de_titulo or all((round(t["bbox"][0]), round(t["bbox"][1]), t["text"]) in quedan
                                         for t in x["tramos"]):
                    continue
                x0, y0, x1, y1 = x["bbox"]
                caja = s.shapes.add_textbox(Emu(int(x0 * escala)), Emu(int(y0 * escala)),
                                            Emu(int((x1 - x0) * escala * 1.06) + 12700), Emu(int((y1 - y0) * escala)))
                tf = caja.text_frame
                tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
                tf.word_wrap = False
                tf.auto_size = MSO_AUTO_SIZE.NONE
                tf.vertical_anchor = MSO_ANCHOR.TOP
                p = tf.paragraphs[0]
                for t in x["tramos"]:
                    r = p.add_run()
                    r.text = t["text"]
                    _formato(r, t, escala_pt)
            s.notes_slide.notes_text_frame.text = textos[i] if i < len(textos) else ""
        destino = AQUI / "presentacion_final.pptx"
        prs.save(destino)
    if len(textos) != n:
        problemas.append(f"notas_orador.txt tiene {len(textos)} bloques y la presentación {n} diapositivas")
    for k, t in enumerate(textos):
        for m in re.finditer(r"\{\{(\w+)\}\}", t):
            problemas.append(f"notas de la diapositiva {k + 1}: {{{{{m.group(1)}}}}} no es una macro de generado/")
    reabierta = Presentation(str(destino))
    con_notas = sum(1 for s in reabierta.slides if s.has_notes_slide and s.notes_slide.notes_text_frame.text.strip())
    con_titulo = sum(1 for s in reabierta.slides if s.shapes.title is not None and s.shapes.title.text.strip())
    cajas = sum(1 for s in reabierta.slides for sh in s.shapes if sh.has_text_frame and sh.text_frame.text.strip())
    sin_alt = sum(1 for s in reabierta.slides for sh in s.shapes
                  if sh.shape_type == 13 and not sh._element.nvPicPr.cNvPr.get("descr"))
    print(f"{destino.name}: {len(reabierta.slides)} diapositivas, {con_titulo} con título, {cajas} cuadros de texto "
          f"editables, {con_notas} con notas del orador, {sin_alt} imágenes sin texto alternativo")
    if con_notas != len(reabierta.slides):
        problemas.append("hay diapositivas sin notas del orador")
    if con_titulo != len(reabierta.slides):
        problemas.append("hay diapositivas sin título editable")
    if sin_alt:
        problemas.append(f"{sin_alt} imágenes sin texto alternativo en el .pptx")
    return problemas


def main() -> None:
    for flujo in (sys.stdout, sys.stderr):
        if hasattr(flujo, "reconfigure"):
            flujo.reconfigure(encoding="utf-8", errors="replace")
    os.environ["PYTHONIOENCODING"] = "utf-8"
    pedidos =[a for a in sys.argv[1:] if not a.startswith("--")] or list(DOCUMENTOS)
    problemas = [] if "--sin-datos" in sys.argv else generar_datos()
    exe = tectonic()
    for nombre in pedidos:
        pdf, p = compilar(nombre, exe)
        problemas += p
        if nombre == "presentacion" and pdf is not None:
            problemas += armar_pptx(pdf)
    if problemas:
        print("Problemas:")
        print("\n".join(f"  - {p}" for p in problemas))
        sys.exit(1)
    print(f"Sin problemas: referencias resueltas, sin cajas desbordadas de más de {UMBRAL_PT:.0f} pt y páginas dentro"
          " del presupuesto.")


if __name__ == "__main__":
    main()
