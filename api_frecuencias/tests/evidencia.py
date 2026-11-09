"""Evidencia escrita por las pruebas, sin ensuciar el repositorio.

Las pruebas que dejan un archivo de evidencia (matriz de roles, traza, resiliencia, backtests...) lo escriben con
``guardar_evidencia``:

- con ``GENERAR_EVIDENCIAS=1`` el archivo va a ``docs/evidencias/<ruta_relativa>``: así se regenera la evidencia
  versionada, a propósito y con un comando explícito;
- sin esa variable (lo normal: la suite, el CI o un jurado que corre las pruebas) va a un directorio temporal, y el
  checkout queda igual que antes de correrlas. ``EVIDENCIAS_DIR`` permite elegir ese directorio.

La función devuelve la ruta escrita, para que la prueba la pueda releer o mostrar.

    GENERAR_EVIDENCIAS=1 pytest tests/integracion/test_seguridad.py     # regenera docs/evidencias/seguridad/
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path, PurePosixPath

RAIZ = Path(__file__).resolve().parents[1]
DOCS_EVIDENCIAS = RAIZ / "docs" / "evidencias"
_temporal: Path | None = None


def generando_evidencias() -> bool:
    """True solo si se pidió regenerar la evidencia versionada (GENERAR_EVIDENCIAS=1)."""
    return os.environ.get("GENERAR_EVIDENCIAS", "").strip() == "1"


def directorio_evidencias() -> Path:
    """docs/evidencias con GENERAR_EVIDENCIAS=1; si no, EVIDENCIAS_DIR o un directorio temporal del proceso."""
    global _temporal
    if generando_evidencias():
        return DOCS_EVIDENCIAS
    elegido = os.environ.get("EVIDENCIAS_DIR", "").strip()
    if elegido:
        return Path(elegido)
    if _temporal is None:
        _temporal = Path(tempfile.mkdtemp(prefix="evidencias_pruebas_"))
    return _temporal


def _relativa_segura(ruta_relativa: str | Path) -> PurePosixPath:
    relativa = PurePosixPath(str(ruta_relativa).replace("\\", "/"))
    if relativa.is_absolute() or not relativa.parts or ".." in relativa.parts or ":" in relativa.parts[0]:
        raise ValueError(f"la evidencia debe ir dentro de docs/evidencias: {ruta_relativa!r}")
    return relativa


def guardar_evidencia(ruta_relativa: str | Path, contenido: str | bytes | dict | list) -> Path:
    """Escribe una evidencia y devuelve su ruta.

    ``ruta_relativa`` es relativa a docs/evidencias (por ejemplo «seguridad/matriz_roles.txt»). ``contenido`` puede
    ser texto, bytes o un dict/list, que se guarda como JSON legible (UTF-8, sin escapar acentos)."""
    destino = directorio_evidencias().joinpath(*_relativa_segura(ruta_relativa).parts)
    destino.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(contenido, bytes):
        destino.write_bytes(contenido)
    else:
        texto = contenido if isinstance(contenido, str) else json.dumps(contenido, ensure_ascii=False, indent=1,
                                                                        default=str)
        destino.write_text(texto, encoding="utf-8")
    return destino


__all__ = ["DOCS_EVIDENCIAS", "directorio_evidencias", "generando_evidencias", "guardar_evidencia"]
