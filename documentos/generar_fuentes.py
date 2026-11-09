"""Genera documentos/fuentes/Inter-{Regular,Medium,SemiBold,Bold}.ttf desde la letra variable del tablero.

    python EntregaFinal/documentos/generar_fuentes.py

XeTeX (Tectonic) no lee WOFF2 ni elige pesos de una fuente variable, así que se crean instancias estáticas de
dash_app/assets/fuentes/InterVariable.woff2 (Inter, SIL OFL 1.1; la licencia se copia al lado). Solo hace falta
correrlo si cambia la letra del tablero. Necesita fonttools y brotli (requisitos_documentos.txt).
"""
from __future__ import annotations

import shutil
from pathlib import Path

from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

AQUI = Path(__file__).resolve().parent
ORIGEN = AQUI.parent / "dash_app" / "assets" / "fuentes"
DESTINO = AQUI / "fuentes"
PESOS = {"Regular": 400, "Medium": 500, "SemiBold": 600, "Bold": 700}


def main() -> None:
    DESTINO.mkdir(exist_ok=True)
    for nombre, peso in PESOS.items():
        fuente = TTFont(ORIGEN / "InterVariable.woff2")
        ejes = {"wght": peso}
        if any(e.axisTag == "opsz" for e in fuente["fvar"].axes):
            ejes["opsz"] = 14
        estatica = instancer.instantiateVariableFont(fuente, ejes, updateFontNames=False)
        estatica.flavor = None
        nombres = estatica["name"]
        for registro in list(nombres.names):
            if registro.nameID in (1, 2, 4, 6, 16, 17):
                nombres.removeNames(nameID=registro.nameID)
        nombres.setName("Inter Sobusa", 1, 3, 1, 0x409)
        nombres.setName(nombre, 2, 3, 1, 0x409)
        nombres.setName(f"Inter Sobusa {nombre}", 4, 3, 1, 0x409)
        nombres.setName(f"InterSobusa-{nombre}", 6, 3, 1, 0x409)
        estatica.save(DESTINO / f"Inter-{nombre}.ttf")
        print(f"fuentes/Inter-{nombre}.ttf")
    shutil.copy2(ORIGEN / "OFL.txt", DESTINO / "OFL.txt")


if __name__ == "__main__":
    main()
