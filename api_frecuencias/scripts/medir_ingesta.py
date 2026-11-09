"""RNF-003 · medición de la ingesta con COPY (tiempo por etapa y memoria pico) con ≥ 100.000 filas.

Lote de 111.792 filas: la serie horaria del proyecto (55.896 filas) más una réplica con las fechas corridas tres
años atrás (mismo lote que scripts/medir_rendimiento.py). Etapas: lectura incremental (Parquet) -> validación de
calidad (6 dimensiones) -> COPY a la tabla de paso + INSERT … ON CONFLICT. Luego, en la MISMA transacción:
recarga idéntica (debe modificar 0 filas) y recarga con 1 % de filas cambiadas (debe actualizar solo esas). Al
final la transacción se REVIERTE: no queda nada en la base local de pruebas.

Memoria: pico de tracemalloc (asignaciones de Python, NumPy y pandas) y pico del conjunto de trabajo del proceso.

Uso:  python scripts/medir_ingesta.py --base-datos ai_frecuencias_pruebas_cola --salida docs/evidencias/cola/ingesta.txt
"""
from __future__ import annotations

import argparse
import ctypes
import sys
import time
import tracemalloc
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cola_servidor import motor, preparar_base, url_local  # noqa: E402

_LINEAS: list[str] = []


def log(*partes) -> None:
    linea = " ".join(str(p) for p in partes)
    _LINEAS.append(linea)
    print(linea, flush=True)


def pico_proceso_mib() -> float | None:
    """Pico del conjunto de trabajo (Windows) o ru_maxrss (Linux)."""
    if sys.platform == "win32":
        class Contadores(ctypes.Structure):
            _fields_ = [("cb", ctypes.c_ulong), ("PageFaultCount", ctypes.c_ulong),
                        ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]

        c = Contadores()
        c.cb = ctypes.sizeof(c)
        kernel32, psapi = ctypes.windll.kernel32, ctypes.windll.psapi
        kernel32.GetCurrentProcess.restype = ctypes.c_void_p
        psapi.GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.POINTER(Contadores), ctypes.c_ulong]
        if psapi.GetProcessMemoryInfo(kernel32.GetCurrentProcess(), ctypes.byref(c), c.cb):
            return c.PeakWorkingSetSize / 2**20
        return None
    import resource

    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


def main() -> int:
    import pandas as pd
    from sqlalchemy.orm import Session

    p = argparse.ArgumentParser()
    p.add_argument("--base-datos", default="ai_frecuencias_pruebas_cola")
    p.add_argument("--comparar-anterior", type=int, default=10000,
                   help="filas para medir el método anterior (insert().values por lotes de 5.000); 0 = no")
    p.add_argument("--salida", type=Path)
    a = p.parse_args()
    url = url_local(a.base_datos)
    preparar_base(url)
    from app.servicios import calidad, ingesta
    from app.servicios.fuentes import FuenteParquet

    log(f"RNF-003 · ingesta con COPY {time.strftime('%Y-%m-%d %H:%M:%S')} (portátil Windows 11, PostgreSQL 14 local "
        f"en Docker, base {a.base_datos}; transacción revertida al final)")
    rss_antes = pico_proceso_mib()

    def leer_y_validar():
        t0 = time.perf_counter()
        df, _ = FuenteParquet().leer_incremental(None, None)
        t_lectura = time.perf_counter() - t0
        copia = df.copy()
        copia["fecha"] = (pd.to_datetime(copia["fecha"]) - pd.DateOffset(years=3)).dt.date
        copia["ultima_actualizacion"] = pd.to_datetime(copia["ultima_actualizacion"]) - pd.DateOffset(years=3)
        lote = pd.concat([df, copia], ignore_index=True)
        t1 = time.perf_counter()
        validos, errores = calidad.validar_lote(lote, "rendimiento-111k")
        return df, lote, validos, errores, t_lectura, time.perf_counter() - t1

    m = motor(url)
    # pasada de MEMORIA (tracemalloc encendido: frena las asignaciones, así que no se usa para los tiempos)
    tracemalloc.start()
    *_, validos_m, _, _, _ = leer_y_validar()
    with Session(m) as s:
        ingesta.incorporar(s, validos_m, None)
        s.rollback()
    _, pico_py = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    del validos_m
    # pasada de TIEMPOS (sin tracemalloc)
    df, lote, validos, errores, t_lectura, t_calidad = leer_y_validar()
    with Session(m) as s:
        r1 = ingesta.incorporar(s, validos, None)
        r2 = ingesta.incorporar(s, validos, None)
        cambiado = validos.copy()
        n_cambio = max(1, len(cambiado) // 100)
        cambiado.loc[cambiado.index[:n_cambio], "pasajeros"] = cambiado.loc[cambiado.index[:n_cambio],
                                                                            "pasajeros"].fillna(0) + 1
        r3 = ingesta.incorporar(s, cambiado, None)
        s.rollback()
        anterior = None
        if a.comparar_anterior:
            muestra = validos.iloc[:a.comparar_anterior]
            t = time.perf_counter()
            ingesta._incorporar_por_lotes(s, muestra, None)
            s.flush()
            anterior = (len(muestra), time.perf_counter() - t)
            s.rollback()
    m.dispose()
    rss = pico_proceso_mib()
    ingesta_s = r1["copy_s"] + r1["upsert_s"]
    total = t_lectura + t_calidad + ingesta_s
    log(f"Lote: {len(lote):,} filas (serie de {len(df):,} + réplica con fechas -3 años); válidas {len(validos):,}; "
        f"errores de calidad {len(errores):,}")
    log(f"   lectura incremental (Parquet)            {t_lectura:7.2f} s")
    log(f"   validación de calidad (6 dimensiones)    {t_calidad:7.2f} s")
    log(f"   COPY a la tabla de paso                  {r1['copy_s']:7.2f} s")
    log(f"   INSERT … ON CONFLICT (upsert)            {r1['upsert_s']:7.2f} s   insertadas {r1['insertadas']:,}, "
        f"actualizadas {r1['actualizadas']:,}")
    log(f"   ingesta (COPY + upsert)                  {ingesta_s:7.2f} s   -> {r1['filas'] / ingesta_s:,.0f} filas/s")
    log(f"   total del pipeline                       {total:7.2f} s")
    log(f"Recarga idéntica (misma clave, mismos valores): {r2['copy_s'] + r2['upsert_s']:.2f} s; insertadas "
        f"{r2['insertadas']}, actualizadas {r2['actualizadas']}, sin cambio {r2['sin_cambio']:,} -> idempotente")
    log(f"Recarga con {n_cambio:,} filas cambiadas (1 %): {r3['copy_s'] + r3['upsert_s']:.2f} s; insertadas "
        f"{r3['insertadas']}, actualizadas {r3['actualizadas']:,}, sin cambio {r3['sin_cambio']:,}")
    log(f"Memoria pico: tracemalloc {pico_py / 2**20:,.0f} MiB (lectura + validación + COPY); conjunto de trabajo del "
        f"proceso {rss:,.0f} MiB (antes de empezar {rss_antes:,.0f} MiB)" if rss and rss_antes else
        f"Memoria pico: tracemalloc {pico_py / 2**20:,.0f} MiB")
    if anterior:
        n, seg = anterior
        log(f"Método anterior (insert().values por lotes de 5.000), muestra de {n:,} filas: {seg:.2f} s -> "
            f"{n / seg:,.0f} filas/s; proyectado a {r1['filas']:,} filas: {r1['filas'] / (n / seg):,.0f} s "
            f"(medido antes: 152,6 s en docs/evidencias/rendimiento.txt)")
        log(f"Aceleración de la ingesta: {(r1['filas'] / (n / seg)) / ingesta_s:,.1f} veces (ambos medidos aquí, sin "
            "tracemalloc). Nota: los 152,6 s de rendimiento.txt se midieron con tracemalloc encendido, que frena "
            "las asignaciones de Python; por eso aquí la memoria se mide en una pasada aparte.")
    cumple = r1["filas"] >= 100_000 and ingesta_s < 10 and r2["insertadas"] == 0 and r2["actualizadas"] == 0 \
        and r3["actualizadas"] == n_cambio
    log(f"RESULTADO: {'CUMPLE' if cumple else 'NO CUMPLE'} (≥ 100.000 filas en < 10 s, recarga sin duplicar ni "
        "reescribir, recarga con cambios solo actualiza lo cambiado)")
    if a.salida:
        a.salida.parent.mkdir(parents=True, exist_ok=True)
        a.salida.write_text("\n".join(_LINEAS) + "\n", encoding="utf-8")
    return 0 if cumple else 1


if __name__ == "__main__":
    raise SystemExit(main())
