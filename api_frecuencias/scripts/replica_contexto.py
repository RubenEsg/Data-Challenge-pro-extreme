"""Reconstruye el contexto operacional del modelo (variables fv2) DESDE LA BASE, en solo lectura (RF-003, §6.2, §11.2
«las novedades viales se cruzan por fecha, rango horario y ruta para generar variables de impacto»).

Hoy datos/contexto_operacional.parquet sale de las exportaciones (scripts/preparar_datos_api.py). Este script lee las
mismas tablas de la base operacional con lector_ia (FuentePostgresSoloLectura: READ ONLY, statement_timeout, TimeZone)
— novedades_viales_fecha, novedades_viales_ruta, estacionalidades_anio y estacionalidades — y aplica EXACTAMENTE la
misma función de preparar_datos_api.py (contexto_y_novedades_por_ruta: las novedades de todas las rutas por fecha y
hora y, si novedades_viales_ruta trae filas, las de rutas dadas por ruta, fecha y hora), para que las variables del
modelo puedan venir de la base en vez de los archivos. Compara el resultado con el parquet empaquetado (igualdad fila
a fila) y, con --salida, escribe el parquet en otra carpeta (nunca sobre datos/ del repositorio), con
novedades_por_ruta.parquet al lado si hay novedades por ruta.

Uso: .venv\\Scripts\\python -m scripts.replica_contexto [--salida C:/tmp/contexto_operacional.parquet]
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

import pandas as pd

from scripts import replica_comun as rc

RAIZ = rc.RAIZ
EVIDENCIA = RAIZ / "docs" / "evidencias" / "replica" / "replica_contexto.json"
COLUMNAS = ["fecha", "hora", "nov_impacto", "nov_sube", "festivo_oficial"]


def leer_tablas(url: str | None = None) -> dict[str, pd.DataFrame]:
    from app.servicios.fuentes import FuentePostgresSoloLectura

    url = url or (rc.url_rol("lector_ia") or "").replace("postgresql://", "postgresql+psycopg://")
    if not url:
        raise SystemExit("Falta LECTOR_IA_PASSWORD (o pase --url de un usuario de solo lectura).")
    f = FuentePostgresSoloLectura(url=url, tabla="novedades_viales_fecha")
    try:
        return {"novedades_viales_fecha": f.leer_contexto("novedades_viales_fecha"),
                "novedades_viales_ruta": f.leer_contexto("novedades_viales_ruta"),
                "estacionalidades_anio": f.leer_contexto("estacionalidades_anio"),
                "estacionalidades": f.leer_contexto("estacionalidades")}
    finally:
        f._engine().dispose()


def construir(tablas: dict[str, pd.DataFrame], desde: str = "2023-01-01", hasta: str = "2026-12-31"):
    """Misma lógica que preparar_datos_api (contexto de todas las rutas, novedades de rutas dadas y resumen),
    alimentada con lo leído de la base."""
    from scripts.preparar_datos_api import contexto_y_novedades_por_ruta

    # columnas de la tabla, sin las del catálogo unido
    ea = tablas["estacionalidades_anio"][["id_estacionalidad_anio", "proceso", "id_estacionalidad", "ano",
                                          "fecha_inicio", "fecha_fin"]]
    return contexto_y_novedades_por_ruta(tablas["novedades_viales_fecha"], tablas["novedades_viales_ruta"], ea,
                                         tablas["estacionalidades"], desde, hasta)


def comparar(ctx: pd.DataFrame, referencia: Path) -> dict:
    if not referencia.exists():
        return {"referencia": str(referencia), "existe": False}
    ref = pd.read_parquet(referencia)
    ref["fecha"] = pd.to_datetime(ref["fecha"]).dt.date
    a = ctx[COLUMNAS].sort_values(["fecha", "hora"]).reset_index(drop=True)
    b = ref[COLUMNAS].sort_values(["fecha", "hora"]).reset_index(drop=True)
    m = a.merge(b, on=["fecha", "hora"], how="outer", suffixes=("_bd", "_archivo"), indicator=True)
    ambos = m[m["_merge"] == "both"]
    iguales = ((ambos["nov_impacto_bd"].astype(float).round(6) == ambos["nov_impacto_archivo"].astype(float).round(6))
               & (ambos["nov_sube_bd"] == ambos["nov_sube_archivo"])
               & (ambos["festivo_oficial_bd"] == ambos["festivo_oficial_archivo"]))
    return {"filas_bd": len(a), "filas_archivo": len(b), "filas_comunes": len(ambos),
            "filas_iguales": int(iguales.sum()), "identico": bool(len(a) == len(b) == len(ambos) == int(iguales.sum())),
            "horas_con_novedad_bd": int((a["nov_impacto"] > 0).sum()),
            "horas_con_novedad_archivo": int((b["nov_impacto"] > 0).sum())}


def main(argv: list[str] | None = None) -> dict:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--salida", type=Path, default=None)
    p.add_argument("--url", default=None, help="URL de solo lectura (por omisión, lector_ia de la réplica local)")
    p.add_argument("--sin-evidencia", action="store_true")
    a = p.parse_args(argv)
    tablas = leer_tablas(a.url)
    ctx, por_ruta, info = construir(tablas)
    from app.servicios import datos

    informe = {"generado_en": datetime.now().astimezone().isoformat(), "rol": "lector_ia (solo lectura)",
               "tablas_leidas": {k: len(v) for k, v in tablas.items()}, "info": info,
               "comparacion_con_datos_contexto_operacional": comparar(ctx, datos.carpeta_datos() /
                                                                        "contexto_operacional.parquet")}
    if a.salida is not None:
        destino = a.salida.resolve()
        if (RAIZ / "datos").resolve() in destino.parents:
            raise SystemExit("No se escribe en datos/ del repositorio: elija otra carpeta.")
        ctx.to_parquet(destino, index=False)
        informe["salida"] = str(destino)
        from scripts.preparar_datos_api import escribir_novedades_por_ruta

        if escribir_novedades_por_ruta(destino.parent, por_ruta):
            informe["salida_novedades_por_ruta"] = str(destino.parent / "novedades_por_ruta.parquet")
    if not a.sin_evidencia:
        EVIDENCIA.write_text(json.dumps(informe, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return informe


if __name__ == "__main__":
    print(json.dumps(main(), ensure_ascii=False, indent=1, default=str))
