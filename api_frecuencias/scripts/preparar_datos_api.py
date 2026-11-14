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
5. datos/novedades_viales_fecha.parquet, novedades_viales_ruta.parquet, estacionalidades_anio.parquet y
   estacionalidades.parquet (exportaciones de las tablas del mismo nombre) -> datos/contexto_operacional.parquet
   (variables de contexto de la versión fv2: impacto por hora de las novedades viales de todas las rutas y festivos
   oficiales) y, solo si novedades_viales_ruta trae filas, datos/novedades_por_ruta.parquet (§11.2: el impacto de cada
   novedad de rutas dadas, solo en sus rutas; app/servicios/novedades.py).
6. datos/progvehiculos.parquet + datos/conteo_viajes.parquet (solo 2024) -> datos/perfil_intrahorario.parquet
   (fracción de las subidas de la hora que viaja en los buses que salen entre h:00 y h:29).
7. datos/clima_diario.parquet -> datos/clima_diario.parquet de la API (solo para evaluar por condición: la lluvia es
   observada y diaria, usarla como variable del pronóstico sería fuga).
8. datos/progvehiculos.parquet -> datos/bajadas_horaria.parquet: bajadas_viajes por ruta, fecha y hora de salida
   (4-20 h) = Σ numerobajadas de los viajes válidos (finalizado 'S', cancelada 'N', dato no nulo y <= 300, ceros
   incluidos), la definición de pasajeros aplicada a los descensos (§6.1 Bajadas), con la grilla de la serie (una hora
   sin viajes válidos vale 0, como pasajeros). Es la misma regla de la lectura integrada demanda_segmentos
   (app/servicios/fuentes.py); tests/replica/test_consolidados.py (test_las_bajadas_empaquetadas_son_las_de_la_replica)
   comprueba que coincide con la réplica.

Uso:  python scripts/preparar_datos_api.py [--raiz-proyecto RUTA] [--solo-contexto] [--solo-bajadas]
      --solo-contexto regenera solo los puntos 5-7 (no toca la serie ni el catálogo).
      --solo-bajadas regenera solo el punto 8 (no toca la serie ni el catálogo).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

RAIZ_API = Path(__file__).resolve().parents[1]
RAIZ_PROYECTO = Path(__file__).resolve().parents[3]
if str(RAIZ_API) not in sys.path:
    sys.path.insert(0, str(RAIZ_API))

from app.servicios import novedades  # noqa: E402  (§11.2: novedades por fecha, rango horario y ruta)

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


def _hora(x) -> int:
    return int(str(x).split(":")[0])


def _nombres_de_rutas(raiz: Path | None = None) -> dict[int, str]:
    """idruta -> nombre de la ruta: de datos/rutas.parquet del proyecto si existe; si no, del catálogo de la API."""
    archivo = raiz / "datos" / "rutas.parquet" if raiz is not None else None
    if archivo is not None and archivo.exists():
        rutas = pd.read_parquet(archivo, columns=["idruta", "nombre"])
        return {int(i): str(n) for i, n in zip(rutas["idruta"], rutas["nombre"], strict=True)}
    catalogo = json.loads((RAIZ_API / "datos" / "catalogo_rutas.json").read_text(encoding="utf-8"))
    return {int(r["idruta"]): str(r["ruta"]) for r in catalogo}


def _leer_contexto(raiz: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    d = raiz / "datos"
    return (pd.read_parquet(d / "novedades_viales_fecha.parquet"), pd.read_parquet(d / "novedades_viales_ruta.parquet"),
            pd.read_parquet(d / "estacionalidades_anio.parquet"), pd.read_parquet(d / "estacionalidades.parquet"))


def contexto_operacional(raiz: Path, desde: str = "2023-01-01", hasta: str = "2026-12-31") -> tuple[pd.DataFrame, dict]:
    """Contexto conocido por adelantado, por fecha y hora de salida (4-20 h), de las novedades de TODAS las rutas.

    - nov_impacto: porcentaje_impacto de novedades_viales_fecha si la hora [h:00, h+1:00) cruza [hora_inicio, hora_fin]
      (el máximo si hay varias); 0 si no. Solo las novedades sin filas en novedades_viales_ruta (las de todas las
      rutas; en Sobusa, todas): las de rutas dadas van en novedades_por_ruta (contexto_y_novedades_por_ruta).
    - nov_sube: 1 si la novedad está marcada potencial_efecto = 'SUBE'.
    - festivo_oficial: días FESTIVO_NACIONAL de estacionalidades_anio (respaldo del calendario de la serie, cubre 2026).
    """
    nov, por_ruta, ea, est = _leer_contexto(raiz)
    return contexto_desde_tablas(nov, por_ruta, ea, est, desde, hasta, _nombres_de_rutas(raiz))


def contexto_y_novedades_por_ruta(nov: pd.DataFrame, por_ruta: pd.DataFrame, ea: pd.DataFrame, est: pd.DataFrame,
                                  desde: str = "2023-01-01", hasta: str = "2026-12-31",
                                  nombres: dict[int, str] | None = None) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """§11.2 «las novedades viales se cruzan por fecha, rango horario y ruta»: (contexto de todas las rutas por fecha y
    hora, novedades de rutas dadas por ruta, fecha y hora, resumen). Una novedad con filas en novedades_viales_ruta
    afecta solo a esas rutas del catálogo (`nombres`: idruta -> ruta); una sin filas, a todas (app/servicios/
    novedades.py). Con novedades_viales_ruta vacía (Sobusa) el contexto es el de siempre y la segunda tabla, vacía."""
    nombres = nombres if nombres is not None else _nombres_de_rutas()
    rutas_de = novedades.rutas_por_novedad(por_ruta)
    ctx, info = _contexto_general(novedades.de_todas_las_rutas(nov, rutas_de), ea, est, desde, hasta)
    por_ruta_ctx = novedades.impacto_por_ruta(nov, rutas_de, nombres)
    info.update(novedades=int(len(nov)), dias_con_novedad=int(nov["fecha"].nunique()) if len(nov) else 0,
                **novedades.resumen(nov, por_ruta, nombres), filas_novedades_por_ruta=int(len(por_ruta_ctx)))
    return ctx, por_ruta_ctx, info


def contexto_desde_tablas(nov: pd.DataFrame, por_ruta: pd.DataFrame, ea: pd.DataFrame, est: pd.DataFrame,
                          desde: str = "2023-01-01", hasta: str = "2026-12-31",
                          nombres: dict[int, str] | None = None) -> tuple[pd.DataFrame, dict]:
    """El contexto de todas las rutas a partir de las tablas ya leídas (exportaciones Parquet o la réplica con
    lector_ia, como hace scripts/reconstruir_desde_replica.py). Las novedades de rutas dadas ya no detienen la
    preparación: se aplican solo a sus rutas (contexto_y_novedades_por_ruta) y el resumen las cuenta."""
    ctx, _por_ruta, info = contexto_y_novedades_por_ruta(nov, por_ruta, ea, est, desde, hasta, nombres)
    return ctx, info


def _contexto_general(nov: pd.DataFrame, ea: pd.DataFrame, est: pd.DataFrame, desde: str, hasta: str
                      ) -> tuple[pd.DataFrame, dict]:
    """El contexto por fecha y hora de las novedades de todas las rutas y los festivos oficiales (la regla de
    siempre: con novedades_viales_ruta vacía da el mismo datos/contexto_operacional.parquet)."""
    filas = []
    for r in nov.itertuples():
        for h in range(max(4, _hora(r.hora_inicio)), min(20, _hora(r.hora_fin)) + 1):
            filas.append(
                {
                    "fecha": pd.Timestamp(r.fecha).date(),
                    "hora": h,
                    "nov_impacto": float(r.porcentaje_impacto or 0),
                    "nov_sube": int(str(r.potencial_efecto).upper() == "SUBE"),
                }
            )
    nv = pd.DataFrame(filas, columns=["fecha", "hora", "nov_impacto", "nov_sube"])
    nv = nv.groupby(["fecha", "hora"], as_index=False).max()
    ea = ea.drop(columns=["estacionalidad"], errors="ignore").merge(
        est[["id_estacionalidad", "estacionalidad"]], on="id_estacionalidad")
    festivos: set = set()
    for r in ea[ea["estacionalidad"] == "FESTIVO_NACIONAL"].itertuples():
        festivos |= {x.date() for x in pd.date_range(pd.Timestamp(r.fecha_inicio), pd.Timestamp(r.fecha_fin), freq="D")}
    fechas = [x.date() for x in pd.date_range(desde, hasta, freq="D")]
    base = pd.MultiIndex.from_product([fechas, range(4, 21)], names=["fecha", "hora"]).to_frame(index=False)
    ctx = base.merge(nv, on=["fecha", "hora"], how="left")
    ctx["nov_impacto"] = ctx["nov_impacto"].fillna(0).astype("float32")
    ctx["nov_sube"] = ctx["nov_sube"].fillna(0).astype("int8")
    ctx["festivo_oficial"] = ctx["fecha"].isin(festivos).astype("int8")
    ctx["hora"] = ctx["hora"].astype("int8")
    info = {
        "novedades": int(len(nov)),
        "dias_con_novedad": int(nov["fecha"].nunique()) if len(nov) else 0,
        "horas_con_novedad": int((ctx["nov_impacto"] > 0).sum()),
        "festivos_oficiales_en_rango": int(ctx.loc[ctx["festivo_oficial"] == 1, "fecha"].nunique()),
        "procesos_estacionalidades": sorted(map(str, ea["proceso"].unique())),
    }
    return ctx, info


def perfil_intrahorario(raiz: Path, serie: pd.DataFrame, anio: int = 2024) -> pd.DataFrame:
    """Fracción de las subidas de la hora h que viaja en los buses que salen entre h:00 y h:29 (por ruta, tipo de día y
    hora), con los viajes de `anio` (conteo_viajes.subidas + progvehiculos.fechasalida). Es la media de las fracciones
    diarias; sustituye el reparto uniforme (0,5) de la primera media hora en las ventanas de 30/60/120 min."""
    d = raiz / "datos"
    ids = {int(i): r for r, i in serie.groupby("ruta")["idruta"].first().items()}
    pv = pd.read_parquet(d / "progvehiculos.parquet", columns=["idprogramacion", "idruta", "fechasalida", "cancelada"])
    pv = pv[pv["idruta"].isin(ids)]
    pv["fechasalida"] = pd.to_datetime(pv["fechasalida"])
    pv = pv[(pv["fechasalida"] >= f"{anio}-01-01") & (pv["fechasalida"] < f"{anio + 1}-01-01")]
    pv = pv[pv["cancelada"].astype(str).str.upper().ne("S")]  # cancelada: 'S' / 'N'
    cv = pd.read_parquet(d / "conteo_viajes.parquet", columns=["idprogramacion", "subidas"])
    v = pv.merge(cv, on="idprogramacion")
    v["ruta"] = v["idruta"].map(ids)
    v["fecha"] = v["fechasalida"].dt.date
    v["hora"] = v["fechasalida"].dt.hour
    v["s1"] = np.where(v["fechasalida"].dt.minute < 30, v["subidas"], 0.0)
    hh = v.groupby(["ruta", "fecha", "hora"], as_index=False).agg(s1=("s1", "sum"), s=("subidas", "sum"))
    hh = hh[(hh["s"] > 0) & hh["hora"].between(4, 20)]
    tipos = serie[["ruta", "fecha", "tipo_dia"]].drop_duplicates(["ruta", "fecha"])
    hh = hh.merge(tipos, on=["ruta", "fecha"], how="left")
    dsem = pd.to_datetime(hh["fecha"]).dt.dayofweek
    hh["tipo_dia"] = hh["tipo_dia"].fillna(pd.Series(np.where(dsem == 6, 2, np.where(dsem == 5, 1, 0)))).astype(int)
    hh["fraccion"] = hh["s1"] / hh["s"]
    p = hh.groupby(["ruta", "tipo_dia", "hora"], as_index=False).agg(
        fraccion_primera_media=("fraccion", "mean"), dias=("fraccion", "size")
    )
    p["fraccion_primera_media"] = p["fraccion_primera_media"].clip(0.05, 0.95).astype("float32")
    p["tipo_dia"] = p["tipo_dia"].astype("int8")
    p["hora"] = p["hora"].astype("int8")
    return p


def escribir_novedades_por_ruta(destino: Path, por_ruta: pd.DataFrame) -> bool:
    """datos/novedades_por_ruta.parquet solo si hay novedades de rutas dadas; si no, se quita uno viejo (la API lo lee
    como «sin novedades por ruta»). Devuelve si quedó escrito."""
    archivo = destino / "novedades_por_ruta.parquet"
    if por_ruta.empty:
        archivo.unlink(missing_ok=True)
        return False
    por_ruta.assign(hora=por_ruta["hora"].astype("int8"), nov_impacto=por_ruta["nov_impacto"].astype("float32"),
                    nov_sube=por_ruta["nov_sube"].astype("int8")).to_parquet(archivo, index=False)
    return True


def preparar_contexto(raiz: Path, destino: Path, serie: pd.DataFrame) -> dict:
    """Escribe contexto_operacional (novedades de todas las rutas y festivos), novedades_por_ruta (si hay novedades de
    rutas dadas), perfil_intrahorario y clima_diario (para evaluar por condición)."""
    nov, por_ruta_tabla, ea, est = _leer_contexto(raiz)
    ctx, por_ruta, info = contexto_y_novedades_por_ruta(nov, por_ruta_tabla, ea, est, nombres=_nombres_de_rutas(raiz))
    ctx.to_parquet(destino / "contexto_operacional.parquet", index=False)
    info["novedades_por_ruta.parquet"] = escribir_novedades_por_ruta(destino, por_ruta)
    perfil = perfil_intrahorario(raiz, serie)
    perfil.to_parquet(destino / "perfil_intrahorario.parquet", index=False)
    clima = pd.read_parquet(raiz / "datos" / "clima_diario.parquet", columns=["fecha", "precipitacion_4_21h_mm"])
    clima["fecha"] = pd.to_datetime(clima["fecha"]).dt.date
    clima.to_parquet(destino / "clima_diario.parquet", index=False)
    return {
        "contexto_operacional.parquet": {
            "fuente": "datos/novedades_viales_fecha.parquet, novedades_viales_ruta.parquet, estacionalidades_anio.parquet, estacionalidades.parquet",
            "filas": len(ctx),
            "columnas": {
                "nov_impacto": "porcentaje_impacto de la novedad vial si la hora de salida cruza [hora_inicio, hora_fin]; 0 si no (máximo si hay varias). Solo las novedades sin filas en novedades_viales_ruta (todas las rutas; en Sobusa, todas): las de rutas dadas van en novedades_por_ruta.parquet y la API las aplica solo a sus rutas (app/servicios/novedades.py)",
                "nov_sube": "1 si potencial_efecto = SUBE (la etiqueta no siempre coincide con los datos: el modelo aprende el signo)",
                "festivo_oficial": "FESTIVO_NACIONAL de estacionalidades_anio (respaldo del calendario; cubre 2026 para la semana siguiente)",
            },
            **info,
        },
        "perfil_intrahorario.parquet": {
            "fuente": "datos/progvehiculos.parquet (fechasalida, idruta, cancelada) + datos/conteo_viajes.parquet (subidas), viajes de 2024",
            "filas": len(perfil),
            "fraccion_media": round(float(perfil["fraccion_primera_media"].mean()), 4),
            "definicion": "media diaria de subidas de los viajes que salen entre h:00 y h:29 / subidas de los viajes que salen en la hora h, por ruta, tipo de día y hora; si falta se usa 0,5",
        },
        "clima_diario.parquet": {
            "fuente": "datos/clima_diario.parquet (precipitacion_4_21h_mm)",
            "uso": "solo como condición en la evaluación (lluvia >= 5 y >= 20 mm, seco); nunca como variable del pronóstico",
        },
    }


COLUMNAS_VIAJES_BAJADAS = ["idruta", "fechasalida", "finalizado", "cancelada", "numerobajadas"]


def bajadas_desde_viajes(viajes: pd.DataFrame, serie: pd.DataFrame) -> pd.DataFrame:
    """bajadas_viajes por (ruta, fecha, hora de salida) en la grilla de la serie: Σ numerobajadas de los viajes válidos
    (finalizado 'S', cancelada 'N', dato no nulo y <= 300; ceros incluidos). Una hora de la grilla sin viajes válidos
    vale 0, igual que pasajeros en la serie."""
    validos = viajes[(viajes["finalizado"] == "S") & (viajes["cancelada"] == "N")]
    salida = pd.to_datetime(validos["fechasalida"])
    bajadas = pd.to_numeric(validos["numerobajadas"], errors="coerce")
    v = pd.DataFrame({"idruta": validos["idruta"].astype(int).to_numpy(), "fecha": salida.dt.date.to_numpy(),
                      "hora": salida.dt.hour.astype(int).to_numpy(),
                      "bajadas_viajes": bajadas.where(bajadas <= 300).to_numpy()})
    por_franja = v.groupby(["idruta", "fecha", "hora"], as_index=False)["bajadas_viajes"].sum()
    grilla = pd.DataFrame({"ruta": serie["ruta"].astype(str), "idruta": serie["idruta"].astype(int),
                           "fecha": pd.to_datetime(serie["fecha"]).dt.date, "hora": serie["hora"].astype(int)})
    out = grilla.merge(por_franja, on=["idruta", "fecha", "hora"], how="left")
    out["bajadas_viajes"] = out["bajadas_viajes"].fillna(0.0).astype("float32")
    out["hora"] = out["hora"].astype("int8")
    return out[["ruta", "fecha", "hora", "bajadas_viajes"]].sort_values(["fecha", "ruta", "hora"]).reset_index(
        drop=True)


def preparar_bajadas(raiz: Path, destino: Path) -> dict:
    """Punto 8: datos/bajadas_horaria.parquet desde la exportación de progvehiculos y la grilla de la serie."""
    import hashlib

    serie = pd.read_parquet(destino / "demanda_horaria.parquet", columns=["ruta", "idruta", "fecha", "hora"])
    viajes = pd.read_parquet(raiz / "datos" / "progvehiculos.parquet", columns=COLUMNAS_VIAJES_BAJADAS)
    b = bajadas_desde_viajes(viajes, serie)
    archivo = destino / "bajadas_horaria.parquet"
    b.to_parquet(archivo, index=False)
    return {"bajadas_horaria.parquet": {
        "fuente": "datos/progvehiculos.parquet (exportación de la tabla progvehiculos) y la grilla de "
                  "demanda_horaria.parquet",
        "filas": len(b), "desde": str(b["fecha"].min()), "hasta": str(b["fecha"].max()),
        "total_bajadas_viajes": float(b["bajadas_viajes"].sum()),
        "sha256": hashlib.sha256(archivo.read_bytes()).hexdigest(),
        "columnas": {
            "bajadas_viajes": "suma de numerobajadas de los viajes válidos que salen en esa hora (finalizado S, "
                              "cancelada N, dato no nulo y <= 300, ceros incluidos): la definición de pasajeros "
                              "aplicada a los descensos (§6.1 Bajadas)"}}}


def _actualizar_origen(destino: Path, origen: dict) -> None:
    ruta_origen = destino / "origen.json"
    previo = {}
    if ruta_origen.exists():  # el archivo es compartido con otros scripts: se actualizan solo estas llaves
        try:
            previo = json.loads(ruta_origen.read_text(encoding="utf-8"))
        except ValueError:
            previo = {}
    previo.update(origen)
    ruta_origen.write_text(json.dumps(previo, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--raiz-proyecto", type=Path, default=RAIZ_PROYECTO)
    ap.add_argument("--solo-contexto", action="store_true", help="solo contexto, perfil intrahorario y clima")
    ap.add_argument("--solo-bajadas", action="store_true", help="solo datos/bajadas_horaria.parquet (punto 8)")
    args = ap.parse_args()
    raiz = args.raiz_proyecto
    destino = RAIZ_API / "datos"
    destino.mkdir(parents=True, exist_ok=True)
    if args.solo_bajadas:
        info = preparar_bajadas(raiz, destino)
        _actualizar_origen(destino, info)
        print(json.dumps(info, ensure_ascii=False, indent=1, default=str))
        return
    if args.solo_contexto:
        serie = pd.read_parquet(destino / "demanda_horaria.parquet", columns=["ruta", "idruta", "fecha", "tipo_dia"])
        serie["fecha"] = pd.to_datetime(serie["fecha"]).dt.date
        info = preparar_contexto(raiz, destino, serie)
        _actualizar_origen(destino, info)
        print(json.dumps(info, ensure_ascii=False, indent=1, default=str))
        return

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
    origen.update(preparar_contexto(raiz, destino, s))
    _actualizar_origen(destino, origen)
    print(f"demanda_horaria: {len(s)} filas, {s['fecha'].min()} a {s['fecha'].max()}")
    print(json.dumps([{k: v for k, v in c.items() if k != "por_tipo_dia"} for c in cat], ensure_ascii=False))


if __name__ == "__main__":
    main()
