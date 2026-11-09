# Copia de EntregaFinal/dash_app/motor/comun.py. Único cambio: la carpeta de datos (DATOS) sale de la variable de entorno
# DATA_DIR (vacía = api_frecuencias/datos/) en lugar de dash_app/datos/; se quitaron fmt/pct/hhmm (solo formato del tablero).
"""Constantes, rutas de archivos y parámetros del optimizador D5 para la API de frecuencias.

Origen: sistema_tiempo_real/comun.py del proyecto -> dash_app/motor/comun.py -> esta copia.
- Los costos con fuente (26.400,22 COP por bus-hora de conductor, 1.991,24 COP por km evitable y 3.182 COP de tarifa neta,
  precios 2026) se leen ya calculados de datos/costos_fuente.json (copia de costos/resultados/costos_unitarios.json, clave
  "2026").
- No usa el paquete holidays: el tipo de día de cada fecha de 2025 viene en los insumos de D5 (insumos_d5_2025.parquet).
param_d5() devuelve los mismos parámetros que el original.
"""
import json
import os
from functools import lru_cache
from pathlib import Path

import numpy as np

AQUI = Path(__file__).resolve().parent
RAIZ_API = AQUI.parents[2]                       # .../api_frecuencias
DATOS = Path(os.environ.get("DATA_DIR") or (RAIZ_API / "datos"))

RUTAS = {2: "SILENCIO", 16: "CRA 54", 21: "CL 72"}
ID_RUTA = {v: k for k, v in RUTAS.items()}
ORDEN = ["SILENCIO", "CRA 54", "CL 72"]
HORAS = np.arange(4, 21)                     # horas de salida programada que planifica D5 (4..20)
CAPACIDAD = 50

FUENTE_COSTOS = "costos con fuente (2026)"
FUENTE_SUPUESTOS = "supuestos D5"

# Intervalo máximo entre salidas por tipo de día (política de servicio de D1, la que usa D5)
INTERVALO_MAX = {"Laboral": 10.0, "Sábado": 10.0, "Domingo/festivo": 15.0}


@lru_cache(maxsize=1)
def costos_con_fuente():
    """Costos unitarios con fuente (precios 2026): costo_km_evitable, bus_hora_conductor, tarifa_efectiva y sus rangos
    bajo/alto. Archivo datos/costos_fuente.json."""
    return json.loads((DATOS / "costos_fuente.json").read_text(encoding="utf-8"))


def param_d5(fuente=True):
    """Parámetros de D5 (experimentos/D5_optimizacion_milp/run.py, PARAM).

    Con fuente=True: costo por bus-hora, costo por km y tarifa de costos/ (precios 2026), igual que costos/reoptimizar_d5.py:
    es el plan que reasigna salidas (x_corrida_1). Con fuente=False: los supuestos iniciales de D5 (60.000 / 1.500 / 3.000),
    el plan que recorta (x_D5)."""
    P = {
        "COSTO_BUS_HORA": 60000, "COSTO_KM": 1500, "TARIFA": 3000, "VALOR_TIEMPO_ESPERA": 7000,
        "PENALIDAD_SOBRECARGA": 10000, "ELASTICIDAD": 0.5, "CAPACIDAD": 50, "INTERVALO_MIN": 2.0,
        "INTERVALO_MAX": dict(INTERVALO_MAX), "DELTA": 6,
        "HORA_INICIO_SUAVIDAD": 7, "FACTOR_FLOTA": 0.85, "HORIZONTE": 7,
        "Z_CUANTILES": {"0.1": -1.2816, "0.5": 0.0, "0.8": 0.8416, "0.9": 1.2816}, "FUENTE": FUENTE_SUPUESTOS,
    }
    if fuente:
        u = costos_con_fuente()["central"]
        P.update({"COSTO_BUS_HORA": u["bus_hora_conductor"], "COSTO_KM": u["costo_km_evitable"], "TARIFA": u["tarifa_efectiva"],
                  "FUENTE": FUENTE_COSTOS})
    return P


def es_fuente(P):
    """True si P lleva los costos con fuente (y entonces la referencia del plan es x_corrida_1, no x_D5)."""
    return str(P.get("FUENTE", "")) == FUENTE_COSTOS
