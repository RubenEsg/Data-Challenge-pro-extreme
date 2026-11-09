"""Mediciones rápidas de rendimiento para la matriz de cumplimiento.

RNF-002: p50/p95/máximo de 50 GET paginados (limite=50) contra la API en marcha.
RNF-003: ingesta de un lote de 111.792 filas (la serie horaria de 55.896 filas replicada con las fechas
corridas tres años atrás): lectura incremental + validación de calidad (seis dimensiones) + inserción con
upsert por (ruta, fecha, hora) en la base LOCAL de pruebas, dentro de una transacción que se revierte al final
(no queda nada guardado). Memoria pico medida con tracemalloc (asignaciones de Python y NumPy).

Uso:  python scripts/medir_rendimiento.py --base http://127.0.0.1:8000 --salida docs/evidencias/rendimiento.txt
"""
from __future__ import annotations

import argparse
import os
import statistics
import sys
import time
import tracemalloc
from pathlib import Path

import httpx
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_LINEAS: list[str] = []
HOSTS_LOCALES = {"localhost", "127.0.0.1", "db", "::1"}


def log(*partes) -> None:
    texto = " ".join(str(p) for p in partes)
    _LINEAS.append(texto)
    print(texto)


def p95(valores: list[float]) -> float:
    orden = sorted(valores)
    return orden[min(len(orden) - 1, int(round(0.95 * (len(orden) - 1))))]


def medir_api(base: str, n: int) -> None:
    log(f"RNF-002: {n} GET paginados por recurso (limite=50), secuenciales, tras 3 de calentamiento; API {base}")
    clave = os.environ.get("SOBUSA_API_KEY", "").strip()      # §7.2: la clave solo llega por el entorno
    with httpx.Client(base_url=base, timeout=30, headers={"X-API-Key": clave} if clave else {}) as c:
        for ruta in ("/api/v1/predictions", "/api/v1/recommendations", "/api/v1/alerts",
                     "/api/v1/frequency/executions"):
            for _ in range(3):
                c.get(ruta, params={"limite": 50})
            tiempos, total = [], None
            for i in range(n):
                t0 = time.perf_counter()
                r = c.get(ruta, params={"limite": 50, "desplazamiento": (i % 3) * 10})
                tiempos.append((time.perf_counter() - t0) * 1000)
                r.raise_for_status()
                total = r.json()["total"]
            log(f"   GET {ruta:<30} filas en la tabla={total:>5}  p50={statistics.median(tiempos):7.1f} ms  "
                f"p95={p95(tiempos):7.1f} ms  máx={max(tiempos):7.1f} ms  -> "
                f"{'cumple' if p95(tiempos) < 2000 else 'NO cumple'} p95 < 2 s")


def medir_ingesta() -> None:
    from sqlalchemy import create_engine
    from sqlalchemy.engine import make_url
    from sqlalchemy.orm import Session

    from app.config import Ajustes
    from app.servicios import calidad, ejecucion
    from app.servicios.fuentes import FuenteParquet

    url = make_url(Ajustes().database_url)
    if url.host not in HOSTS_LOCALES:
        log("   Se omite la inserción: la URL no es local")
        return
    url = url.set(database="ai_frecuencias_pruebas")

    tracemalloc.start()
    t0 = time.perf_counter()
    df, marca = FuenteParquet().leer_incremental(None, None)
    t_lectura = time.perf_counter() - t0
    copia = df.copy()
    copia["fecha"] = pd.to_datetime(copia["fecha"]) - pd.DateOffset(years=3)
    copia["fecha"] = copia["fecha"].dt.date
    copia["ultima_actualizacion"] = pd.to_datetime(copia["ultima_actualizacion"]) - pd.DateOffset(years=3)
    lote = pd.concat([df, copia], ignore_index=True)
    log(f"RNF-003: lote de {len(lote):,} filas (serie de {len(df):,} filas + réplica con fechas -3 años)")
    t1 = time.perf_counter()
    validos, errores = calidad.validar_lote(lote, "rendimiento-111k")
    t_calidad = time.perf_counter() - t1
    t2 = time.perf_counter()
    motor = create_engine(url, pool_pre_ping=True)
    with Session(motor) as s:
        insertadas = ejecucion._incorporar_historico(s, validos, None)
        s.flush()
        t_insercion = time.perf_counter() - t2
        s.rollback()
    motor.dispose()
    _, pico = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    total = t_lectura + t_calidad + t_insercion
    log(f"   lectura incremental (Parquet, {len(df):,} filas): {t_lectura:6.2f} s")
    log(f"   validación de calidad (6 dimensiones, {len(lote):,} filas): {t_calidad:6.2f} s; válidas={len(validos):,} "
        f"errores={len(errores)}")
    log(f"   inserción con upsert en PostgreSQL local (lotes de 5.000, transacción revertida): {insertadas:,} filas "
        f"en {t_insercion:6.2f} s")
    log(f"   total {total:6.2f} s ({len(lote) / total:,.0f} filas/s); "
        f"memoria pico (tracemalloc) {pico / 2**20:,.0f} MiB")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--base", default="http://127.0.0.1:8000")
    p.add_argument("--n", type=int, default=50)
    p.add_argument("--salida", type=Path, default=None)
    p.add_argument("--sin-ingesta", action="store_true")
    p.add_argument("--sin-api", action="store_true")
    a = p.parse_args()
    log(f"Mediciones de rendimiento {time.strftime('%Y-%m-%d %H:%M:%S')} (portátil Windows 11, Docker Desktop)")
    if not a.sin_api:
        medir_api(a.base, a.n)
    if not a.sin_ingesta:
        medir_ingesta()
    if a.salida:
        a.salida.parent.mkdir(parents=True, exist_ok=True)
        a.salida.write_text("\n".join(_LINEAS) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
