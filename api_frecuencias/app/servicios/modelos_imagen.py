"""Modelos que trae la imagen y le faltan al volumen de modelos (RNF-008, §9.2).

En Docker Compose, /app/datos/modelos es el volumen «modelos»: guarda lo que entrena la API y sobrevive a los
reinicios. Docker lo llena con lo que trae la imagen solo la primera vez, cuando el volumen está vacío. Al actualizar
una instalación que ya existía, la imagen nueva trae modelos que el volumen no tiene (por ejemplo, el de corto plazo),
y el volumen los tapa. Por eso la imagen guarda una segunda copia en /app/modelos_imagen (MODELOS_IMAGEN_DIR), y al
arrancar la API copia al volumen lo que le falta:

- las carpetas de los modelos que el volumen no tiene;
- en cada registro (el de los modelos horarios, segmentos/ y corto_plazo/), las fichas de esos modelos, como
  candidatos. El modelo activo no cambia: activar sigue siendo una decisión con su compuerta (POST
  /models/{model_id}/activate). Si el volumen no tiene el registro, se copia el de la imagen tal cual, con su activo.

Nada se sobrescribe ni se borra: lo que ya está en el volumen se queda como está.
"""
from __future__ import annotations

import json
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path

from . import datos

ORIGEN_POR_OMISION = "/app/modelos_imagen"
ARCHIVO_REGISTRO = "registro.json"
SUBREGISTROS = ("segmentos", "corto_plazo")


def carpeta_imagen() -> Path:
    return Path(os.environ.get("MODELOS_IMAGEN_DIR") or ORIGEN_POR_OMISION)


def _leer(ruta: Path) -> dict | None:
    if not ruta.exists():
        return None
    return json.loads(ruta.read_text(encoding="utf-8"))


def _sembrar_registro(origen: Path, destino: Path) -> list[str]:
    """Copia las carpetas y las fichas que le faltan al registro de destino. Devuelve los model_id agregados."""
    reg_o = _leer(origen / ARCHIVO_REGISTRO)
    if reg_o is None:
        return []
    destino.mkdir(parents=True, exist_ok=True)
    for mid in reg_o.get("modelos", {}):
        if (origen / mid).is_dir() and not (destino / mid).exists():
            shutil.copytree(origen / mid, destino / mid)
    ruta_d = destino / ARCHIVO_REGISTRO
    reg_d = _leer(ruta_d)
    if reg_d is None:
        shutil.copy2(origen / ARCHIVO_REGISTRO, ruta_d)
        return list(reg_o.get("modelos", {}))
    nuevos = [mid for mid in reg_o.get("modelos", {}) if mid not in reg_d.get("modelos", {})]
    if not nuevos:
        return []
    for mid in nuevos:
        reg_d.setdefault("modelos", {})[mid] = dict(reg_o["modelos"][mid], estado="candidato")
    reg_d.setdefault("historial_siembra", []).append(
        {"en": datetime.now(UTC).isoformat(timespec="seconds"), "modelos": nuevos,
         "motivo": "modelos de la imagen que el volumen no tenía (entran como candidatos; el activo no cambia)"})
    ruta_d.write_text(json.dumps(reg_d, ensure_ascii=False, indent=1), encoding="utf-8")
    return nuevos


def sembrar(origen: Path | None = None, destino: Path | None = None) -> dict[str, list[str]]:
    """Copia al volumen lo que trae la imagen y le falta. {registro: [model_id agregados]}; vacío si no hay nada que
    copiar o si la carpeta de la imagen no existe (fuera de Docker)."""
    origen = Path(origen) if origen else carpeta_imagen()
    destino = Path(destino) if destino else datos.carpeta_modelos()
    if not origen.is_dir() or (destino.exists() and origen.resolve() == destino.resolve()):
        return {}
    hechos: dict[str, list[str]] = {}
    nuevos = _sembrar_registro(origen, destino)
    if nuevos:
        hechos["horarios"] = nuevos
    for sub in SUBREGISTROS:
        if (origen / sub).is_dir():
            nuevos = _sembrar_registro(origen / sub, destino / sub)
            if nuevos:
                hechos[sub] = nuevos
    return hechos
