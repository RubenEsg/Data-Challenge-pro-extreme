"""Motor de inferencia ONNX Runtime (§9.1 «candidato tabular exportado a ONNX», §9.2 «ONNX Runtime»).

MOTOR_INFERENCIA=sklearn (por omisión) carga modelo.joblib; MOTOR_INFERENCIA=onnx usa los modelo_{punto,p10,p90}.onnx
que deja scripts/exportar_onnx.py junto al artefacto, con su SHA-256 en manifest['onnx'] (se verifica al cargar,
una sola vez por modelo, igual que el joblib). Solo los modelos fv2 (ruta ordinal) son exportables: el fv1 usa
variables categóricas nativas que skl2onnx no traduce bien (WAPE 99 % sin Exp y P10 que no cuadra).
El grafo del punto ya trae el nodo Exp (enlace de la pérdida Poisson), así que su salida está en pasajeros.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

import numpy as np

MOTORES = ("sklearn", "onnx")
PARTES = ("punto", "p10", "p90")


class MotorNoDisponible(RuntimeError):
    """El modelo no tiene exportación ONNX verificable o falta onnxruntime."""


def _desde_ajustes() -> str:
    try:  # MOTOR_INFERENCIA también puede venir del .env (app/config.py)
        from app.config import obtener_ajustes

        return obtener_ajustes().motor_inferencia
    except Exception:  # noqa: BLE001
        return ""


def motor_configurado() -> str:
    """MOTOR_INFERENCIA del entorno (o del .env); por omisión sklearn."""
    motor = (os.environ.get("MOTOR_INFERENCIA") or _desde_ajustes() or "sklearn").strip().lower()
    if motor not in MOTORES:
        raise MotorNoDisponible(f"MOTOR_INFERENCIA={motor!r} no es válido (use {' o '.join(MOTORES)})")
    return motor


def sha256(ruta: Path) -> str:
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for bloque in iter(lambda: f.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()


class ModeloOnnx:
    """Envoltura con la interfaz .predict(X) de scikit-learn sobre una sesión de ONNX Runtime (CPU)."""

    def __init__(self, ruta: Path, sha_esperado: str | None):
        try:
            import onnxruntime as ort
        except ImportError as exc:  # pragma: no cover - onnxruntime está en requirements
            raise MotorNoDisponible("onnxruntime no está instalado") from exc
        calculado = sha256(ruta)
        if sha_esperado and calculado != sha_esperado:
            raise MotorNoDisponible(f"El SHA-256 de {ruta.name} no coincide con el manifiesto "
                                    f"(esperado {sha_esperado[:12]}..., calculado {calculado[:12]}...)")
        opciones = ort.SessionOptions()
        opciones.intra_op_num_threads = 1
        self.sesion = ort.InferenceSession(str(ruta), sess_options=opciones, providers=["CPUExecutionProvider"])
        self.entrada = self.sesion.get_inputs()[0].name
        self.sha256 = calculado
        self.ruta = ruta

    def predict(self, x) -> np.ndarray:
        arr = np.asarray(x, dtype=np.float32)
        return self.sesion.run(None, {self.entrada: arr})[0].ravel().astype(float)


def cargar_sesiones(carpeta: Path, manifiesto: dict) -> dict[str, ModeloOnnx]:
    """{'punto': ModeloOnnx, 'p10': ..., 'p90': ...} verificados contra manifest['onnx']['archivos']."""
    info = manifiesto.get("onnx") or {}
    archivos = info.get("archivos") or {}
    if not archivos:
        raise MotorNoDisponible(f"{manifiesto.get('model_id')} no tiene exportación ONNX "
                                "(ejecute scripts/exportar_onnx.py --model-id ...)")
    salida = {}
    for parte in PARTES:
        a = archivos.get(parte)
        if not a:
            raise MotorNoDisponible(f"Falta la parte {parte} de la exportación ONNX de {manifiesto.get('model_id')}")
        ruta = Path(carpeta) / a["archivo"]
        if not ruta.exists():
            raise MotorNoDisponible(f"No existe {ruta}")
        salida[parte] = ModeloOnnx(ruta, a.get("sha256"))
    return salida
