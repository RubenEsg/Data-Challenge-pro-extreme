"""EntregaFinal/historial_desarrollo.py (E03 «historial», fila E03.3): el formato del historial sobre una salida de git
sintética. No usa el historial real ni git: solo parsear_log, depurar y formatear."""
from __future__ import annotations

import importlib.util
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

RUTA = Path(__file__).resolve().parents[3] / "historial_desarrollo.py"
if not RUTA.is_file():
    pytest.skip("historial_desarrollo.py no está en esta copia (la CI solo descarga api_frecuencias/)",
                allow_module_level=True)

_spec = importlib.util.spec_from_file_location("historial_desarrollo", RUTA)
historial = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = historial            # dataclass necesita el módulo registrado
_spec.loader.exec_module(historial)

BOGOTA = timezone(timedelta(hours=-5))
GENERADO = datetime(2026, 11, 9, 20, 30, tzinfo=BOGOTA)


def _commit(letra: str, padres: str, fecha: str, asunto: str, numstat: list[str]) -> str:
    """Un commit con el formato que pide el script: %x1e%H%x1f%h%x1f%P%x1f%aI%x1f%s y después --numstat."""
    h = letra * 40
    cabeza = "\x1e" + "\x1f".join([h, h[:7], padres, fecha, asunto])
    return cabeza + "\n\n" + "".join(f"{x}\n" for x in numstat)


SALIDA_GIT = "".join([
    _commit("a", "", "2026-10-07T10:13:12-05:00", "Respaldo inicial", [
        "10\t0\tnotas_privadas/plan.md",
        "-\t-\tdatos_privados/figura.png",
    ]),
    _commit("b", "a" * 40, "2026-10-07T18:00:00-05:00", "Entrega: avisar a ana.perez@example.com | revisar", [
        "5\t2\tEntregaFinal/README.md",
        "3\t1\t{scripts_privados => EntregaFinal/scripts}/x.py",
        "1\t0\tnotas_privadas/otro.md",
    ]),
    # fuera de orden a propósito: el historial sale ordenado por fecha
    _commit("d", "c" * 40 + " " + "e" * 40, "2026-10-09T09:00:00-05:00", "Fusión de la rama de pruebas", []),
    _commit("c", "b" * 40, "2026-10-09T08:00:00-05:00", "Conectar la base con contraseña=valor-secreto", [
        "1\t1\tconfiguracion_privada.py",
    ]),
])


def _historial() -> tuple[list, list, str]:
    commits = historial.parsear_log(SALIDA_GIT)
    omitidos = historial.depurar(commits)
    texto = historial.formatear(commits, omitidos, GENERADO, "main", punta="d" * 40)
    return commits, omitidos, texto


def test_parsea_conteos_binarios_renombres_y_marca_de_entregafinal():
    commits, _, _ = _historial()
    assert [c.corto for c in commits] == ["aaaaaaa", "bbbbbbb", "ccccccc", "ddddddd"]
    a, b, c, d = commits
    assert (a.archivos, a.binarios, a.agregadas, a.quitadas, a.en_entrega) == (2, 1, 10, 0, 0)
    assert (b.archivos, b.agregadas, b.quitadas, b.en_entrega) == (3, 9, 3, 2)
    assert (c.archivos, c.en_entrega, c.padres) == (1, 0, 1)
    assert d.padres == 2 and d.archivos == 0


def test_rutas_de_numstat_con_renombres():
    assert historial.rutas_numstat("a/b.py") == ["a/b.py"]
    assert historial.rutas_numstat("viejo.py => EntregaFinal/nuevo.py") == ["viejo.py", "EntregaFinal/nuevo.py"]
    assert historial.rutas_numstat("{x => EntregaFinal/x}/y.py") == ["x/y.py", "EntregaFinal/x/y.py"]
    assert historial.rutas_numstat("EntregaFinal/{ => sub}/z.md") == ["EntregaFinal/z.md", "EntregaFinal/sub/z.md"]


def test_sin_correos_ni_secretos_ni_rutas_fuera_de_entregafinal():
    _, omitidos, texto = _historial()
    assert "@" not in texto and "ana.perez" not in texto and "[correo omitido]" in texto
    assert "valor-secreto" not in texto and "contraseña=" not in texto
    assert omitidos == [("ccccccc", "una credencial asignada")]
    assert historial.OMITIDO in texto
    for ruta in ("notas_privadas", "datos_privados", "scripts_privados", "configuracion_privada", "plan.md"):
        assert ruta not in texto


def test_omite_secretos_sin_falsos_positivos_comunes():
    fecha = datetime(2026, 11, 9, 10, 0, tzinfo=BOGOTA)
    asuntos = {
        "Cifras clave: kappa 0,94 y SHA-256 del modelo": False,
        "Referencia al commit 6f885e83cae939c90cfc2796c13cc433dfce643a": False,
        "Subir la clave=abc123 del servidor": True,
        "Cadena aB3dE5fG7hJ9kL1mN3pQ5rS7tU9vW1xY3zA5bC7 pegada por error": True,
    }
    commits = [historial.Commit(f"{k:040d}", f"{k:07d}", 1, fecha, a) for k, a in enumerate(asuntos)]
    omitidos = {corto for corto, _ in historial.depurar(commits)}
    assert [c.corto in omitidos for c in commits] == list(asuntos.values())


def test_formato_agrupado_por_dia_con_tabla_y_encabezado():
    _, _, texto = _historial()
    assert texto.startswith("# Historial de desarrollo\n")
    assert "repositorio de desarrollo del equipo" in texto and "Cómo verificarlo" in texto
    assert "RubenEsg/" not in texto and "privado" not in texto          # la entrega no nombra otro repositorio
    assert "Generado** el 9 de noviembre de 2026 a las 20:30 (−05:00), desde `main` (`ddddddd`)" in texto
    assert f"`{'d' * 40}`" in texto and f"`{'a' * 40}`" in texto          # hashes completos de la punta y el primero
    dias = re.findall(r"^## (\d{4}-\d{2}-\d{2}) · (\w+) · (\d+) commits?$", texto, flags=re.M)
    assert dias == [("2026-10-07", "miércoles", "2"), ("2026-10-09", "viernes", "2")]
    filas = [x for x in texto.splitlines() if x.startswith("| ") and "`" in x.split("|")[2]]
    assert filas == [
        "| 10:13 | `aaaaaaa` | Respaldo inicial | 2 (1 binario) | +10 / −0 | — |",
        "| 18:00 | `bbbbbbb` | Entrega: avisar a [correo omitido] \\| revisar | 3 | +9 / −3 | sí (2) |",
        f"| 08:00 | `ccccccc` | {historial.OMITIDO} | 1 | +1 / −1 | — |",
        "| 09:00 | `ddddddd` | Fusión de la rama de pruebas | fusión | — | — |",
    ]
    assert "| 4 | 2 | 2026-10-07 | 2026-10-09 | 1 | 6 | +20 / −4 |" in texto


def test_es_determinista_y_sin_commits_falla():
    primera, segunda = _historial()[2], _historial()[2]          # dos corridas con la misma entrada
    assert primera == segunda
    with pytest.raises(ValueError):
        historial.formatear([], [], GENERADO, "main")
