# ruff: noqa: E501  (textos de documentación de las fuentes en origen.json)
"""Prepara los datos compactos que usa la API de frecuencias (carpeta datos/ de este proyecto).

Se ejecuta una sola vez, en la máquina de desarrollo, a partir de archivos del propio proyecto
(nunca se conecta a la base de datos del reto). Produce:

- datos/demanda_horaria.parquet: serie ruta x fecha x hora de salida (4-20 h), 2023-01-01 a 2025-12-31,
  con pasajeros, salidas, calendario y ultima_actualizacion (fin del día, America/Bogota).
- datos/catalogo_rutas.json: capacidad, tiempo de ciclo, flota y frecuencia actual por ruta.
- datos/parametros_operativos_hora.parquet: ciclo, flota, intervalo programado y límites por ruta, tipo de día y hora.
- datos/origen.json: de dónde sale cada columna.

Fuentes (rutas relativas a la raíz del proyecto «DATA CHALLENGE»):
1. experimentos/E1_lgbm_salida/datos_modelado_salida.parquet: tabla de modelado del proyecto (ruta x día x hora de
   salida). pasajeros_total = suma de numeropasajeros de los viajes válidos (dato <= 300, ceros incluidos);
   viajes_validos = salidas válidas; calendario (festivos, Carnaval, Semana Santa, vacaciones, Navidad, 1 de enero).
   Respaldo si no existe: EntregaFinal/dash_app/datos/pronosticos_2025.parquet (columna real, solo 2025).
2. datos/rutas.parquet: exportación de la tabla rutas (idruta, nombre, codigo, flotadisp_prog, frecuenciadespachos).
3. experimentos/D1_optimizacion/parametros_operativos.parquet: ciclo (min), flota_disp, intervalo_prog_med por
   ruta, tipo de día y hora (los mismos parámetros del optimizador D1/D5).
4. EntregaFinal/dash_app/datos/insumos_d5_2025.parquet: nmin y nmax de salidas por hora (límites del MILP D5).

Uso:  python scripts/preparar_datos_api.py [--raiz-proyecto RUTA]
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

RAIZ_API = Path(__file__).resolve().parents[1]
RAIZ_PROYECTO = Path(__file__).resolve().parents[3]
ZONA = "America/Bogota"
CAPACIDAD = 50
RUTAS = ["SILENCIO", "CRA 54", "CL 72"]
TIPOS_DIA = {0: "Laboral", 1: "Sábado", 2: "Domingo/festivo"}


def _normalizar_tipo(t: str) -> str:
    t = str(t)
    if t.startswith("Lab"):
        return "Laboral"
    if t.startswith("S"):
        return "Sábado"
    return "Domingo/festivo"


def serie_desde_e1(ruta_e1: Path) -> pd.DataFrame:
    cols = [
        "idruta",
        "ruta",
        "dia",
        "hora",
        "pasajeros_total",
        "viajes_validos",
        "tipo_dia",
        "festivo",
        "carnaval",
        "semana_santa",
        "vacaciones",
        "navidad",
        "primero_enero",
        "excluido",
    ]
    d = pd.read_parquet(ruta_e1, columns=cols)
    s = pd.DataFrame(
        {
            "ruta": d["ruta"].astype(str),
            "idruta": d["idruta"].astype("int16"),
            "fecha": pd.to_datetime(d["dia"]).dt.date,
            "hora": d["hora"].astype("int8"),
            "pasajeros": d["pasajeros_total"].astype("float32"),
            "salidas": d["viajes_validos"].round().astype("Int16"),
            "tipo_dia": d["tipo_dia"].astype("int8"),
        }
    )
    for c in ["festivo", "carnaval", "semana_santa", "vacaciones", "navidad", "primero_enero", "excluido"]:
        s[c] = d[c].fillna(0).astype("int8")
    return s


def serie_desde_pronosticos(ruta_p: Path) -> pd.DataFrame:
    d = pd.read_parquet(ruta_p)
    tipo = d["tipo_dia"].map(lambda t: {"Laboral": 0, "Sábado": 1}.get(_normalizar_tipo(t), 2))
    s = pd.DataFrame(
        {
            "ruta": d["ruta"].astype(str),
            "idruta": d["idruta"].astype("int16"),
            "fecha": pd.to_datetime(d["dia"]).dt.date,
            "hora": d["hora"].astype("int8"),
            "pasajeros": d["real"].astype("float32"),
            "salidas": pd.array([pd.NA] * len(d), dtype="Int16"),
            "tipo_dia": tipo.astype("int8"),
        }
    )
    for c in ["carnaval", "semana_santa", "vacaciones", "navidad", "primero_enero", "excluido"]:
        s[c] = np.int8(0)
    s["festivo"] = ((s["tipo_dia"] == 2) & (pd.to_datetime(s["fecha"]).dt.dayofweek != 6)).astype("int8")
    return s


def catalogo(raiz: Path) -> tuple[list[dict], pd.DataFrame]:
    rutas = pd.read_parquet(
        raiz / "datos" / "rutas.parquet",
        columns=["idruta", "nombre", "codigo", "flotadisp_prog", "frecuenciadespachos", "primerdespacho"],
    )
    po = pd.read_parquet(raiz / "experimentos" / "D1_optimizacion" / "parametros_operativos.parquet")
    po["tipo_dia"] = po["tipo_dia"].map(_normalizar_tipo)
    ins = pd.read_parquet(
        raiz / "EntregaFinal" / "dash_app" / "datos" / "insumos_d5_2025.parquet",
        columns=["ruta", "tipo_dia", "hora", "nmin", "nmax"],
    )
    ins["tipo_dia"] = ins["tipo_dia"].map(_normalizar_tipo)
    lim = ins.groupby(["ruta", "tipo_dia", "hora"], as_index=False).agg(nmin=("nmin", "median"), nmax=("nmax", "max"))
    tabla = po[["ruta", "tipo_dia", "hora", "ciclo", "flota_disp", "intervalo_prog_med", "capacidad"]].merge(
        lim, on=["ruta", "tipo_dia", "hora"], how="left"
    )
    tabla = tabla.rename(
        columns={"ciclo": "tiempo_ciclo_min", "flota_disp": "flota", "intervalo_prog_med": "intervalo_programado_min"}
    )
    tabla["hora"] = tabla["hora"].astype("int8")
    salida = []
    for nombre in RUTAS:
        r = rutas[rutas["nombre"] == nombre].iloc[0]
        lab = tabla[(tabla["ruta"] == nombre) & (tabla["tipo_dia"] == "Laboral")]
        lab_dia = lab[lab["hora"].between(6, 19)]
        por_tipo = {}
        for t, g in tabla[tabla["ruta"] == nombre].groupby("tipo_dia"):
            g2 = g[g["hora"].between(6, 19)]
            por_tipo[t] = {
                "tiempo_ciclo_min": round(float(g2["tiempo_ciclo_min"].median()), 1),
                "flota": int(g2["flota"].median()),
                "frecuencia_actual_min": round(float(g2["intervalo_programado_min"].median()), 1),
            }
        salida.append(
            {
                "ruta": nombre,
                "idruta": int(r["idruta"]),
                "codigo": str(r["codigo"]),
                "capacidad": CAPACIDAD,
                "tiempo_ciclo_min": round(float(lab_dia["tiempo_ciclo_min"].median()), 1),
                "flota": int(lab_dia["flota"].median()),
                "frecuencia_actual_min": round(float(lab_dia["intervalo_programado_min"].median()), 1),
                "flota_programada_tabla_rutas": int(r["flotadisp_prog"]),
                "frecuenciadespachos_tabla_rutas": int(r["frecuenciadespachos"]),
                "primer_despacho": str(r["primerdespacho"]),
                "por_tipo_dia": por_tipo,
            }
        )
    return salida, tabla


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--raiz-proyecto", type=Path, default=RAIZ_PROYECTO)
    args = ap.parse_args()
    raiz = args.raiz_proyecto
    destino = RAIZ_API / "datos"
    destino.mkdir(parents=True, exist_ok=True)

    ruta_e1 = raiz / "experimentos" / "E1_lgbm_salida" / "datos_modelado_salida.parquet"
    if ruta_e1.exists():
        s = serie_desde_e1(ruta_e1)
        fuente_serie = "experimentos/E1_lgbm_salida/datos_modelado_salida.parquet"
    else:
        s = serie_desde_pronosticos(raiz / "EntregaFinal" / "dash_app" / "datos" / "pronosticos_2025.parquet")
        fuente_serie = "EntregaFinal/dash_app/datos/pronosticos_2025.parquet (solo 2025)"
    s = s[s["hora"].between(4, 20) & s["ruta"].isin(RUTAS)].copy()
    s = s.sort_values(["fecha", "ruta", "hora"]).reset_index(drop=True)
    fin_dia = pd.to_datetime(pd.Series(s["fecha"]).astype(str)) + pd.to_timedelta(86399, unit="s")
    s["ultima_actualizacion"] = fin_dia.dt.tz_localize(ZONA)
    s.to_parquet(destino / "demanda_horaria.parquet", index=False)

    cat, tabla = catalogo(raiz)
    (destino / "catalogo_rutas.json").write_text(json.dumps(cat, ensure_ascii=False, indent=2), encoding="utf-8")
    tabla.to_parquet(destino / "parametros_operativos_hora.parquet", index=False)

    origen = {
        "generado_en": datetime.now(UTC).isoformat(timespec="seconds"),
        "script": "scripts/preparar_datos_api.py",
        "demanda_horaria.parquet": {
            "fuente": fuente_serie,
            "filas": len(s),
            "desde": str(s["fecha"].min()),
            "hasta": str(s["fecha"].max()),
            "columnas": {
                "pasajeros": "pasajeros_total: suma de numeropasajeros de los viajes válidos que salen en esa hora (dato <= 300, ceros incluidos)",
                "salidas": "viajes_validos: salidas válidas en esa hora",
                "tipo_dia": "0 Laboral, 1 Sábado, 2 Domingo/festivo",
                "festivo, carnaval, semana_santa, vacaciones, navidad, primero_enero": "calendario del proyecto (se conoce por adelantado)",
                "excluido": "1 = hora marcada como dato no confiable en la tabla de modelado (102 horas de 2024); no se usa para entrenar ni evaluar",
                "ultima_actualizacion": "fin del día (23:59:59 America/Bogota): marca para la lectura incremental (RF-013)",
            },
        },
        "catalogo_rutas.json": {
            "idruta, codigo, flota_programada_tabla_rutas, frecuenciadespachos_tabla_rutas, primer_despacho": "datos/rutas.parquet (exportación de la tabla rutas)",
            "capacidad": "50 puestos por bus (parametros_operativos.capacidad; regla del reto)",
            "tiempo_ciclo_min": "mediana de ciclo (min) en día laboral, horas 6-19, experimentos/D1_optimizacion/parametros_operativos.parquet",
            "flota": "mediana de flota_disp en día laboral, horas 6-19 (misma fuente; es la flota que usa el MILP D5)",
            "frecuencia_actual_min": "mediana de intervalo_prog_med (intervalo programado) en día laboral, horas 6-19 (misma fuente)",
            "por_tipo_dia": "los mismos tres valores por tipo de día",
        },
        "parametros_operativos_hora.parquet": {
            "fuente": "experimentos/D1_optimizacion/parametros_operativos.parquet + nmin/nmax de EntregaFinal/dash_app/datos/insumos_d5_2025.parquet",
        },
    }
    ruta_origen = destino / "origen.json"
    previo = {}
    if ruta_origen.exists():  # el archivo es compartido con otros scripts: se actualizan solo estas llaves
        try:
            previo = json.loads(ruta_origen.read_text(encoding="utf-8"))
        except ValueError:
            previo = {}
    previo.update(origen)
    ruta_origen.write_text(json.dumps(previo, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"demanda_horaria: {len(s)} filas, {s['fecha'].min()} a {s['fecha'].max()}")
    print(json.dumps([{k: v for k, v in c.items() if k != "por_tipo_dia"} for c in cat], ensure_ascii=False))


if __name__ == "__main__":
    main()
