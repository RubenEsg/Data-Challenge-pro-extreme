"""Tiempos de los dos catálogos más pesados con las exportaciones Parquet locales (modo archivos, sin réplica).

Uso (desde EntregaFinal/api_frecuencias, con el venv y las exportaciones del reto en la carpeta datos/ de la raíz):
    .venv\\Scripts\\python docs\\evidencias\\catalogos\\medir_exportaciones.py
Mide en proceso (sin HTTP) las mismas funciones que llaman los routers y no escribe nada:
- GET /catalogos/segmentos?geometria=completa&limite=50: segmentos(geometria="completa") + geometria_completa(ids)
- GET /catalogos/despachos/export?formato=xlsx (sin filtros): programacion("despachos", limite=100000) + exportar(xlsx)
Resultado de referencia: rendimiento_exportaciones.txt (en esta carpeta).
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(RAIZ))
os.environ["CATALOGOS_FUENTE"] = "archivos"

from app.servicios import catalogos as C  # noqa: E402


def medir(nombre, funcion, veces=3):
    tiempos, resultado = [], None
    for _ in range(veces):
        t0 = time.perf_counter()
        resultado = funcion()
        tiempos.append(time.perf_counter() - t0)
    print(f"{nombre}: primera {tiempos[0]:.2f} s, luego {min(tiempos[1:]):.2f} s", flush=True)
    return resultado


def segmentos_completa(limite=50):
    d, _ = C.segmentos(geometria="completa")
    pagina, _ = C.paginar(d, "segmentos", None, limite, 0)
    geos = C.geometria_completa([int(i) for i in pagina["id"]])
    return len(pagina), sum(len(g["coordinates"]) for g in geos.values())


def despachos_xlsx():
    d, total, _ = C.programacion("despachos", limite=C.LIMITE_EXPORTACION, desplazamiento=0)
    t0 = time.perf_counter()
    contenido, _, _ = C.exportar(d, C.COLUMNAS["despachos"], "xlsx", "despachos")
    return total, len(d), len(contenido), time.perf_counter() - t0


if __name__ == "__main__":
    print("exportaciones en", C.carpeta_exportaciones().name + "/", flush=True)
    n, vertices = medir("segmentos geometria=completa limite=50", segmentos_completa)
    print(f"  {n} segmentos, {vertices} vértices")
    total, filas, peso, t_xlsx = medir("despachos/export xlsx sin filtros", despachos_xlsx, veces=2)
    print(f"  total {total}, filas exportadas {filas}, {peso / 1e6:.1f} MB; escribir el xlsx: {t_xlsx:.2f} s")
