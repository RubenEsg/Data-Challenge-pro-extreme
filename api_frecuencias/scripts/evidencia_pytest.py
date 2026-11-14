"""Corre un grupo de pruebas con pytest y deja su resultado como archivo de evidencia (RNF-014, §14.1).

Los archivos «pytest_<área>.txt» de docs/evidencias/ son el resultado de una corrida de las pruebas de un área. Este
guion los escribe siempre igual, para que ninguno se arme a mano: el título, el comando, las variables de entorno que
cambian lo que corre (sin claves), la fecha de la corrida, el resultado con los conteos por estado y por archivo, y una
línea por prueba (las de «pytest -rA»).

Uso (desde api_frecuencias/):
  python scripts/evidencia_pytest.py --salida docs/evidencias/catalogos/pytest_catalogos.txt \
      --titulo "Pruebas de los catálogos operacionales" [--nota "..."] -- tests/unit/test_catalogos.py ...
Lo que va después de «--» son los argumentos de pytest. El código de salida es el de pytest.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ZONA = ZoneInfo("America/Bogota")
ESTADOS = ("PASSED", "FAILED", "ERROR", "SKIPPED", "XFAIL", "XPASS")
# Variables que cambian qué pruebas corren o contra qué base local; ninguna lleva una clave.
VARIABLES = ("GENERAR_EVIDENCIAS", "TEST_DATABASE_NAME", "REPLICA_PRUEBAS_ESCRITURA", "SCHEMATHESIS_EJEMPLOS",
             "PRUEBA_CAIDA", "PRUEBA_REPLICAS", "PRUEBA_PLANIFICADOR")
_RESUMEN = "short test summary info"
_LINEA = re.compile(rf"^({'|'.join(ESTADOS)}) (?:\[\d+\] )?(\S+)")


def lineas_de_estado(salida: str) -> list[tuple[str, str, str]]:
    """(estado, archivo de la prueba, línea completa) de cada línea del resumen «-rA» de pytest.

    Solo cuenta lo que viene después de «short test summary info» y nombra un archivo .py: los registros capturados de
    una prueba también pueden empezar por «ERROR».
    """
    filas = []
    resumen = salida.rpartition(_RESUMEN)[2]
    for linea in resumen.splitlines():
        m = _LINEA.match(linea)
        if m and ".py" in m.group(2):
            archivo = m.group(2).split("::")[0]
            filas.append((m.group(1), re.sub(r":\d+:?$", "", archivo), linea.rstrip()))
    return filas


def armar(titulo: str, argumentos: list[str], entorno: dict[str, str], inicio: datetime, fin: datetime,
          salida: str, codigo: int, notas: list[str]) -> str:
    """El texto del archivo de evidencia de una corrida de pytest."""
    filas = lineas_de_estado(salida)
    estados = Counter(e for e, _, _ in filas)
    por_archivo = Counter(a for _, a, _ in filas)
    variables = " ".join(f"{k}={entorno[k]}" for k in VARIABLES if entorno.get(k))
    conteos = ", ".join(f"{estados.get(e, 0)} {e}" for e in ESTADOS if estados.get(e) or e in ("PASSED", "FAILED"))
    partes = [titulo, "",
              "Comando (desde api_frecuencias/, escrito por scripts/evidencia_pytest.py):",
              f"  {(variables + ' ') if variables else ''}python -m pytest {' '.join(argumentos)} -rA",
              f"Corrida del {inicio:%Y-%m-%d}, de {inicio:%H:%M:%S} a {fin:%H:%M:%S} (America/Bogota); "
              f"{(fin - inicio).total_seconds():.0f} s.",
              f"Resultado: {len(filas)} casos; {conteos} (código de salida de pytest: {codigo}).",
              "Por archivo: " + "; ".join(f"{a}: {n}" for a, n in sorted(por_archivo.items())) + "."]
    partes += [f"Nota: {n}" for n in notas]
    partes += [""] + [linea for _, _, linea in filas]
    return "\n".join(partes) + "\n"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--salida", type=Path, required=True)
    p.add_argument("--titulo", required=True)
    p.add_argument("--nota", action="append", default=[])
    p.add_argument("pytest", nargs="+", help="argumentos de pytest, después de «--»")
    a = p.parse_args(argv)
    inicio = datetime.now(ZONA)
    r = subprocess.run([sys.executable, "-m", "pytest", *a.pytest, "-rA", "-q", "-p", "no:cacheprovider"],  # noqa: S603
                       capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
    fin = datetime.now(ZONA)
    texto = armar(a.titulo, a.pytest, dict(os.environ), inicio, fin, r.stdout, r.returncode, a.nota)
    a.salida.parent.mkdir(parents=True, exist_ok=True)
    a.salida.write_text(texto, encoding="utf-8")
    print("\n".join(texto.splitlines()[4:7]))
    if r.returncode:
        print(r.stdout[-3000:])
    return r.returncode


if __name__ == "__main__":
    raise SystemExit(main())
