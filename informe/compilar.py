"""Compila el informe técnico final con Tectonic (LaTeX + BibTeX, las pasadas que haga falta) y lo revisa.

    python EntregaFinal/informe/compilar.py         -> EntregaFinal/informe/main.pdf y EntregaFinal/Informe_tecnico_Sobusa.pdf

Antes, si cambió algo de los experimentos: python EntregaFinal/informe/figuras_extra.py

Tectonic se busca en el PATH, en la variable TECTONIC o en machine_learning/entrega 3/articulo/herramientas/tectonic.exe;
descarga los paquetes de LaTeX la primera vez. Después de compilar, el guion:
  - busca en main.log referencias o citas sin resolver y cajas desbordadas de más de 10 pt (sale con código 1 si hay);
  - cuenta las páginas y copia el PDF a EntregaFinal/Informe_tecnico_Sobusa.pdf.
Con la variable PAGINAS_PNG=<carpeta> guarda además cada página en PNG (necesita PyMuPDF) para revisarla.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent
ENTREGA = AQUI.parent                                                                    # EntregaFinal/
TECTONIC_LOCAL = AQUI.parents[2] / "entrega 3" / "articulo" / "herramientas" / "tectonic.exe"   # machine_learning/
DESTINO = ENTREGA / "Informe_tecnico_Sobusa.pdf"
UMBRAL_PT = 10.0


def tectonic() -> str:
    for candidato in (os.environ.get("TECTONIC"), shutil.which("tectonic"), str(TECTONIC_LOCAL)):
        if candidato and Path(candidato).exists():
            return candidato
    sys.exit("No se encontró Tectonic: https://tectonic-typesetting.github.io/ (o fija la variable TECTONIC)")


def revisar_log(log: str) -> list[str]:
    problemas = []
    for patron, que in ((r"LaTeX Warning: Reference `([^']+)' on page", "referencia sin resolver"),
                        (r"LaTeX Warning: Citation `([^']+)' on page", "cita sin resolver"),
                        (r"LaTeX Warning: There were undefined references", "referencias sin definir")):
        for m in re.finditer(patron, log):
            problemas.append(f"{que}: {m.group(1) if m.groups() else ''}")
    for m in re.finditer(r"Overfull \\hbox \(([\d.]+)pt too wide\)[^\n]*lines? (\d+)(?:--(\d+))?", log):
        if float(m.group(1)) > UMBRAL_PT:
            problemas.append(f"caja desbordada {m.group(1)} pt, líneas {m.group(2)}-{m.group(3) or m.group(2)}")
    for m in re.finditer(r"Overfull \\vbox \(([\d.]+)pt too high\)", log):
        if float(m.group(1)) > UMBRAL_PT:
            problemas.append(f"caja vertical desbordada {m.group(1)} pt")
    return problemas


def main() -> None:
    exe = tectonic()
    comando = [exe, "--keep-logs", "--chatter", "minimal", "main.tex"]
    print("$", " ".join(comando))
    r = subprocess.run(comando, cwd=AQUI, capture_output=True, text=True, encoding="utf-8", errors="replace")
    salida = (r.stdout + r.stderr).strip()
    if r.returncode != 0:
        print(salida[-4000:])
        sys.exit(f"Tectonic terminó con código {r.returncode}")

    pdf = AQUI / "main.pdf"
    try:
        from pypdf import PdfReader
        paginas = len(PdfReader(str(pdf)).pages)
    except ImportError:
        paginas = None
    print(f"{pdf.name}: {paginas} páginas, {pdf.stat().st_size / 1e6:.2f} MB")

    problemas = revisar_log((AQUI / "main.log").read_text(encoding="utf-8", errors="replace"))
    if problemas:
        print("Problemas en main.log:")
        print("\n".join(f"  - {p}" for p in problemas))
    else:
        print(f"main.log: sin referencias ni citas rotas y sin cajas desbordadas de más de {UMBRAL_PT:.0f} pt")

    if os.environ.get("PAGINAS_PNG"):
        import pymupdf
        carpeta = Path(os.environ["PAGINAS_PNG"])
        carpeta.mkdir(parents=True, exist_ok=True)
        with pymupdf.open(pdf) as doc:
            for i, pagina in enumerate(doc, start=1):
                pagina.get_pixmap(dpi=80).save(carpeta / f"pagina_{i:02d}.png")
        print(f"páginas en PNG: {carpeta}")

    shutil.copy2(pdf, DESTINO)
    print(f"copiado a {DESTINO.relative_to(ENTREGA.parent)}")
    if problemas:
        sys.exit(1)


if __name__ == "__main__":
    main()
