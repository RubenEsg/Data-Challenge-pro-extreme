"""Linaje de los datos empaquetados: reconstrucción desde la réplica operacional (§16 «Calidad de datos»:
trazabilidad y reproducibilidad; §6.1, §11.2).

Lee en solo lectura las tablas de Extreme de la réplica LOCAL (puerto 5434, usuario lector_ia; cada consulta pasa por
FuentePostgresSoloLectura.consultar: SELECT de una sola sentencia, transacción READ ONLY, statement_timeout y ROLLBACK)
y escribe sus resultados en docs/evidencias/datos/ (nunca en datos/):

  --linaje                 reconstruye la serie de datos/demanda_horaria.parquet (pasajeros y salidas por ruta, fecha y
                           hora de salida 4-20 h, 2023-01-01 a 2025-12-31) con las reglas del objetivo del modelo y
                           datos/contexto_operacional.parquet (novedades viales y festivos oficiales) con
                           preparar_datos_api.contexto_desde_tablas; compara fila a fila y por SHA-256 del contenido
                           normalizado con lo empaquetado -> linaje.json y linaje.md.
  --definicion-pasajeros   mide en el solape de timbradas_segmentos (2023-01-01 a 2023-02-27) la diferencia entre
                           Σ subidas de los segmentos y Σ numeropasajeros de los viajes válidos, por ruta y hora
                           -> definicion_pasajeros.json.
  --muestra-consolidado    escribe tests/fixtures/consolidado_muestra.csv: filas de timbradas_consolidado (conteos
                           agregados por bloque de 15 minutos, sin datos personales) para las pruebas de calidad.

Reglas del objetivo (las mismas de la tabla de modelado del proyecto): viaje válido = finalizado 'S' y cancelada 'N';
pasajeros = Σ numeropasajeros de los viajes válidos con dato y <= 300 (ceros incluidos); salidas = viajes válidos; la
hora es la de fechasalida; las franjas sin viajes valen 0. El calendario (tipo de día, festivos, Carnaval, Semana
Santa, vacaciones, Navidad, 1 de enero) y la marca «excluido» (102 horas de 2024 que la limpieza del proyecto marcó
como no confiables) son reglas propias del proyecto, no datos de Extreme, y no se reconstruyen aquí.

Nunca se conecta a la base compartida del reto: replica_comun solo acepta servidores locales.
Uso:  python -m scripts.reconstruir_desde_replica [--linaje] [--definicion-pasajeros] [--muestra-consolidado]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from scripts import replica_comun as rc  # noqa: E402

EVIDENCIAS = RAIZ / "docs" / "evidencias" / "datos"
FIXTURE = RAIZ / "tests" / "fixtures" / "consolidado_muestra.csv"
DATOS = RAIZ / "datos"
DESDE, HASTA = date(2023, 1, 1), date(2025, 12, 31)
HORAS = range(4, 21)
SOLAPE = (date(2023, 1, 1), date(2023, 2, 27))
ZONA = ZoneInfo("America/Bogota")

SQL_DEMANDA = """
SELECT pv.idruta, CAST(pv.fechasalida AS date) AS fecha, CAST(EXTRACT(HOUR FROM pv.fechasalida) AS integer) AS hora,
       COUNT(*) AS salidas,
       COALESCE(SUM(pv.numeropasajeros) FILTER (WHERE pv.numeropasajeros IS NOT NULL AND pv.numeropasajeros <= 300), 0)
           AS pasajeros
  FROM progvehiculos pv
 WHERE pv.finalizado = 'S' AND pv.cancelada = 'N'
   AND pv.fechasalida >= :desde AND pv.fechasalida < :hasta
   AND EXTRACT(HOUR FROM pv.fechasalida) BETWEEN 4 AND 20
 GROUP BY 1, 2, 3
"""
# Huella de la entrada: las columnas de progvehiculos que usa la regla (sin conductor ni otros datos personales).
SQL_HUELLA_PROGVEHICULOS = """
SELECT count(*) AS filas,
       encode(sha256(convert_to(string_agg(
           concat_ws('|', idprogramacion, idruta, fechasalida, finalizado, cancelada, numeropasajeros),
           chr(10) ORDER BY idprogramacion), 'UTF8')), 'hex') AS sha256
  FROM progvehiculos
 WHERE fechasalida >= :desde AND fechasalida < :hasta
"""
SQL_DEFINICION = """
WITH seg AS (
    SELECT ts.id_viaje, SUM(ts.subidas) AS subidas FROM timbradas_segmentos ts GROUP BY ts.id_viaje
), viajes AS (
    SELECT pv.idruta, CAST(pv.fechasalida AS date) AS fecha, CAST(EXTRACT(HOUR FROM pv.fechasalida) AS integer) AS hora,
           (pv.finalizado = 'S' AND pv.cancelada = 'N') AS valido,
           CASE WHEN pv.numeropasajeros IS NOT NULL AND pv.numeropasajeros <= 300 THEN pv.numeropasajeros END AS pax,
           s.id_viaje IS NOT NULL AS con_timbradas, COALESCE(s.subidas, 0) AS subidas
      FROM progvehiculos pv
      LEFT JOIN seg s ON s.id_viaje = pv.idprogramacion
     WHERE pv.fechasalida >= :desde AND pv.fechasalida < :hasta
), franjas AS (
    SELECT idruta, fecha, hora, bool_or(con_timbradas) AS leida
      FROM viajes WHERE valido GROUP BY idruta, fecha, hora
)
SELECT v.idruta, v.hora,
       SUM(v.subidas) AS subidas_segmentos,
       COALESCE(SUM(v.pax) FILTER (WHERE v.valido), 0) AS pasajeros_viajes_validos,
       COALESCE(SUM(v.pax) FILTER (WHERE v.valido AND v.con_timbradas), 0) AS pasajeros_viajes_con_timbradas,
       COALESCE(SUM(v.pax) FILTER (WHERE v.valido AND NOT v.con_timbradas), 0) AS pasajeros_viajes_sin_timbradas,
       COALESCE(SUM(v.pax) FILTER (WHERE v.valido AND NOT f.leida), 0) AS pasajeros_franjas_sin_timbradas,
       COUNT(*) FILTER (WHERE v.valido) AS viajes_validos,
       COUNT(*) FILTER (WHERE v.con_timbradas) AS viajes_con_timbradas,
       COUNT(*) FILTER (WHERE v.valido AND NOT v.con_timbradas) AS viajes_validos_sin_timbradas,
       COUNT(DISTINCT (v.fecha, v.hora)) FILTER (WHERE v.valido AND NOT f.leida) AS franjas_sin_timbradas
  FROM viajes v
  LEFT JOIN franjas f ON f.idruta = v.idruta AND f.fecha = v.fecha AND f.hora = v.hora
 GROUP BY 1, 2
"""
SQL_MUESTRA = """
SELECT proceso, id_ruta, id_dia_semana, id_estacionalidad, hora, hora_inicio, hora_fin, subidas, bajadas, nro_viajes,
       promedio_subidas, promedio_bajadas, ultima_actualizacion
  FROM timbradas_consolidado
 WHERE (id_estacionalidad = 25 AND id_dia_semana IN (1, 7)) OR hora_fin < hora_inicio
 ORDER BY id_ruta, id_dia_semana, id_estacionalidad, hora_inicio
"""
CONTEXTO = {
    "novedades_viales_fecha": "SELECT id_novedad_vial_fecha, proceso, id_novedad_vial, fecha, hora_inicio, hora_fin, "
                              "potencial_efecto, porcentaje_impacto FROM novedades_viales_fecha "
                              "ORDER BY id_novedad_vial_fecha",
    "novedades_viales_ruta": "SELECT id_novedad_vial_ruta, id_novedad_vial_fecha, id_ruta FROM novedades_viales_ruta "
                             "ORDER BY id_novedad_vial_ruta",
    "estacionalidades_anio": "SELECT id_estacionalidad_anio, proceso, id_estacionalidad, ano, fecha_inicio, fecha_fin "
                             "FROM estacionalidades_anio ORDER BY id_estacionalidad_anio",
    "estacionalidades": "SELECT id_estacionalidad, proceso, estacionalidad, nombre FROM estacionalidades "
                        "ORDER BY id_estacionalidad",
}
EXPORTACION_ORIGINAL = (
    "Exportación del 2026-10-03 21:51:37 (scripts/exportar_tablas.py del repositorio del equipo, no se vuelve a "
    "ejecutar): una sesión de solo lectura (set_session(readonly=True)) sobre la base compartida del reto y, por cada "
    "una de las 15 tablas (Procesos, rutas, vehiculos, dias_semana, estacionalidades, estacionalidades_anio, "
    "novedades_viales, novedades_viales_fecha, novedades_viales_ruta, rutas_segmentos_config, rutas_segmentos, "
    "timbradas_consolidado, timbradas_anio, timbradas_segmentos y progvehiculos), un único SELECT de columnas "
    "explícitas FROM public.\"tabla\" leído con un cursor de servidor en bloques de 100.000 filas, más un SELECT "
    "count(*) para comprobar que las filas exportadas coinciden con las del servidor (15 de 15 coinciden; "
    "progvehiculos 564.837 filas). Las credenciales viven fuera del repositorio. Desde entonces el proyecto solo usa "
    "esas exportaciones: la réplica local se cargó con ellas (scripts/replica_cargar.py)."
)


def _fuente():
    from app.servicios.fuentes import FuentePostgresSoloLectura

    url = rc.url_rol("lector_ia")
    if not url:
        raise SystemExit("Falta LECTOR_IA_PASSWORD (entorno o .env local): la reconstrucción lee la réplica local.")
    return FuentePostgresSoloLectura(url=url.replace("postgresql://", "postgresql+psycopg://", 1), tabla="rutas",
                                     statement_timeout_ms=180_000)


def sha256_archivo(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def sha256_texto(texto: str) -> str:
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def _rutas() -> dict[int, str]:
    from app.servicios import datos

    return {int(r["idruta"]): r["ruta"] for r in datos.catalogo_rutas()}


def demanda_reconstruida(f) -> pd.DataFrame:
    """Serie ruta × fecha × hora (4-20 h) con pasajeros y salidas de los viajes válidos; las franjas vacías valen 0."""
    rutas = _rutas()
    d = f.consultar(SQL_DEMANDA, {"desde": datetime.combine(DESDE, datetime.min.time()),
                                  "hasta": datetime.combine(HASTA + timedelta(days=1), datetime.min.time())})
    d = d[d["idruta"].isin(list(rutas))].copy()
    d["fecha"] = pd.to_datetime(d["fecha"]).dt.date
    rejilla = pd.MultiIndex.from_product([sorted(rutas), pd.date_range(DESDE, HASTA).date, list(HORAS)],
                                         names=["idruta", "fecha", "hora"]).to_frame(index=False)
    t = rejilla.merge(d, on=["idruta", "fecha", "hora"], how="left")
    t["pasajeros"] = pd.to_numeric(t["pasajeros"]).fillna(0)
    t["salidas"] = pd.to_numeric(t["salidas"]).fillna(0)
    t["ruta"] = t["idruta"].map(rutas)
    return t[["ruta", "idruta", "fecha", "hora", "pasajeros", "salidas"]]


def normalizada(df: pd.DataFrame, columnas: list[str]) -> str:
    """Texto CSV ordenado y con tipos fijos (enteros sin decimales, fechas ISO): base del SHA-256 del contenido."""
    t = df[columnas].copy()
    for c in columnas:
        if c == "fecha":
            t[c] = pd.to_datetime(t[c]).dt.strftime("%Y-%m-%d")
        elif c == "ruta":
            t[c] = t[c].astype(str)
        else:
            t[c] = pd.to_numeric(t[c]).fillna(-1).round(4)
            if (t[c] % 1 == 0).all():
                t[c] = t[c].astype("int64")
    return t.sort_values(columnas[:3]).to_csv(index=False, lineterminator="\n")


def comparar(empaquetada: pd.DataFrame, reconstruida: pd.DataFrame, llave: list[str], medidas: list[str]) -> dict:
    a = empaquetada[llave + medidas].copy()
    b = reconstruida[llave + medidas].copy()
    for t in (a, b):
        t["fecha"] = pd.to_datetime(t["fecha"]).dt.date
    m = a.merge(b, on=llave, how="outer", suffixes=("_empaquetado", "_replica"), indicator=True)
    salida = {"filas_empaquetadas": int(len(a)), "filas_reconstruidas": int(len(b)),
              "solo_empaquetado": int((m["_merge"] == "left_only").sum()),
              "solo_replica": int((m["_merge"] == "right_only").sum())}
    ambos = m[m["_merge"] == "both"]
    for c in medidas:
        x = pd.to_numeric(ambos[f"{c}_empaquetado"]).astype(float)
        y = pd.to_numeric(ambos[f"{c}_replica"]).astype(float)
        iguales = (x - y).abs() < 1e-6
        salida[c] = {"iguales": int(iguales.sum()), "distintas": int((~iguales).sum()),
                     "suma_empaquetado": float(x.sum()), "suma_replica": float(y.sum()),
                     "max_diferencia_abs": float((x - y).abs().max()) if len(x) else 0.0}
        if (~iguales).any():
            salida[c]["ejemplos"] = [{k: (str(v) if isinstance(v, date) else v) for k, v in r.items()}
                                     for r in ambos.loc[~iguales.values, llave + [f"{c}_empaquetado", f"{c}_replica"]]
                                     .head(10).to_dict("records")]
    return salida


def linaje(f) -> dict:
    """Serie y contexto reconstruidos desde la réplica frente a los archivos empaquetados."""
    from scripts.preparar_datos_api import contexto_desde_tablas

    resultado: dict = {"generado_en": datetime.now(ZONA).isoformat(timespec="seconds"),
                       "script": "scripts/reconstruir_desde_replica.py --linaje",
                       "lee": "réplica local (lector_ia, transacciones READ ONLY)",
                       "exportacion_original": EXPORTACION_ORIGINAL}
    huella = f.consultar(SQL_HUELLA_PROGVEHICULOS, {"desde": datetime.combine(DESDE, datetime.min.time()),
                                                     "hasta": datetime.combine(HASTA + timedelta(days=1),
                                                                               datetime.min.time())})
    entradas = {"progvehiculos": {"filas_2023_2025": int(huella["filas"].iloc[0]),
                                  "columnas": "idprogramacion, idruta, fechasalida, finalizado, cancelada, "
                                              "numeropasajeros",
                                  "sha256_contenido": huella["sha256"].iloc[0]}}
    tablas = {}
    for nombre, sql in CONTEXTO.items():
        tablas[nombre] = f.consultar(sql)
        entradas[nombre] = {"filas": int(len(tablas[nombre])),
                            "sha256_contenido": sha256_texto(tablas[nombre].to_csv(index=False, lineterminator="\n"))}
    resultado["entradas"] = entradas

    reconstruida = demanda_reconstruida(f)
    empaquetada = pd.read_parquet(DATOS / "demanda_horaria.parquet")
    cols = ["ruta", "idruta", "fecha", "hora", "pasajeros", "salidas"]
    texto_a, texto_b = normalizada(empaquetada, cols), normalizada(reconstruida, cols)
    resultado["demanda_horaria"] = {
        "archivo": "datos/demanda_horaria.parquet", "sha256_archivo": sha256_archivo(DATOS / "demanda_horaria.parquet"),
        "columnas_comparadas": cols, "sha256_contenido_empaquetado": sha256_texto(texto_a),
        "sha256_contenido_reconstruido": sha256_texto(texto_b), "contenido_identico": texto_a == texto_b,
        "comparacion": comparar(empaquetada, reconstruida, ["idruta", "fecha", "hora"], ["pasajeros", "salidas"]),
        "no_reconstruido": "calendario (tipo_dia, festivo, carnaval, semana_santa, vacaciones, navidad, "
                           "primero_enero) y excluido: reglas propias del proyecto, no datos de Extreme"}

    ctx, info = contexto_desde_tablas(tablas["novedades_viales_fecha"], tablas["novedades_viales_ruta"],
                                      tablas["estacionalidades_anio"], tablas["estacionalidades"])
    ctx_emp = pd.read_parquet(DATOS / "contexto_operacional.parquet")
    cols_ctx = ["fecha", "hora", "nov_impacto", "nov_sube", "festivo_oficial"]
    ta, tb = normalizada(ctx_emp, cols_ctx), normalizada(ctx, cols_ctx)
    comp = comparar(ctx_emp.assign(idruta=0), ctx.assign(idruta=0), ["idruta", "fecha", "hora"],
                    ["nov_impacto", "nov_sube", "festivo_oficial"])
    resultado["contexto_operacional"] = {
        "archivo": "datos/contexto_operacional.parquet",
        "sha256_archivo": sha256_archivo(DATOS / "contexto_operacional.parquet"),
        "sha256_contenido_empaquetado": sha256_texto(ta), "sha256_contenido_reconstruido": sha256_texto(tb),
        "contenido_identico": ta == tb, "comparacion": comp, "resumen_reconstruido": info}
    return resultado


def definicion_pasajeros(f) -> dict:
    """Σ subidas de timbradas_segmentos frente a Σ numeropasajeros de los viajes válidos (solape 2023)."""
    rutas = _rutas()
    d = f.consultar(SQL_DEFINICION, {"desde": datetime.combine(SOLAPE[0], datetime.min.time()),
                                     "hasta": datetime.combine(SOLAPE[1] + timedelta(days=1), datetime.min.time())})
    d = d[d["idruta"].isin(list(rutas)) & d["hora"].between(4, 20)].copy()
    for c in d.columns[2:]:
        d[c] = pd.to_numeric(d[c])

    def bloque(g: pd.DataFrame) -> dict:
        s, p = float(g["subidas_segmentos"].sum()), float(g["pasajeros_viajes_validos"].sum())
        pc = float(g["pasajeros_viajes_con_timbradas"].sum())
        return {"subidas_segmentos": s, "pasajeros_viajes_validos": p,
                "diferencia_pct": round(100 * (s - p) / p, 2) if p else None,
                "pasajeros_mismos_viajes_con_timbradas": pc,
                "diferencia_mismos_viajes_pct": round(100 * (s - pc) / pc, 2) if pc else None,
                "pasajeros_viajes_sin_timbradas": float(g["pasajeros_viajes_sin_timbradas"].sum()),
                "pasajeros_franjas_sin_timbradas": float(g["pasajeros_franjas_sin_timbradas"].sum()),
                "viajes_validos": int(g["viajes_validos"].sum()),
                "viajes_validos_sin_timbradas": int(g["viajes_validos_sin_timbradas"].sum()),
                "franjas_sin_timbradas": int(g["franjas_sin_timbradas"].sum())}

    por_ruta = {rutas[int(r)]: bloque(g) for r, g in d.groupby("idruta")}
    por_hora = {int(h): bloque(g) for h, g in d.groupby("hora")}
    por_ruta_hora = [{"ruta": rutas[int(r)], "hora": int(h), **bloque(g)}
                     for (r, h), g in d.groupby(["idruta", "hora"])]
    total = bloque(d)
    material = [x for x in por_ruta_hora if x["diferencia_pct"] is not None and abs(x["diferencia_pct"]) > 5]
    return {"generado_en": datetime.now(ZONA).isoformat(timespec="seconds"),
            "script": "scripts/reconstruir_desde_replica.py --definicion-pasajeros",
            "periodo": f"{SOLAPE[0]} a {SOLAPE[1]} (todo timbradas_segmentos de la réplica)", "horas": "4-20",
            "total": total, "por_ruta": por_ruta, "por_hora": por_hora, "por_ruta_hora": por_ruta_hora,
            "celdas_ruta_hora_con_diferencia_mayor_5pct": len(material), "celdas_ruta_hora": len(por_ruta_hora),
            "umbral_material_pct": 5.0, "material": abs(total["diferencia_pct"] or 0) > 5 or len(material) > 0,
            "decision": "La lectura integrada (demanda_segmentos) usa la definición del modelo: pasajeros = Σ "
                        "numeropasajeros de los viajes válidos; Σ subidas queda en la columna subidas "
                        "(app/servicios/fuentes.py, DEFINICION_PASAJEROS = numeropasajeros_viajes_validos_v2)."}


def muestra_consolidado(f) -> int:
    d = f.consultar(SQL_MUESTRA)
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    for c in ("hora", "hora_inicio", "hora_fin"):
        d[c] = [v.isoformat() if hasattr(v, "isoformat") else str(v) for v in d[c]]
    d["ultima_actualizacion"] = pd.to_datetime(d["ultima_actualizacion"]).dt.strftime("%Y-%m-%dT%H:%M:%S.%f")
    d.to_csv(FIXTURE, index=False, lineterminator="\n")
    return len(d)


def _n(x) -> str:
    """Entero con punto de miles (convención en español)."""
    return f"{x:,.0f}".replace(",", ".")


def _md_linaje(r: dict) -> str:
    dh, cx = r["demanda_horaria"], r["contexto_operacional"]
    cp, cs = dh["comparacion"]["pasajeros"], dh["comparacion"]["salidas"]
    e = r["entradas"]
    filas = [
        "# Linaje de los datos empaquetados", "",
        f"Generado el {r['generado_en']} con `python -m scripts.reconstruir_desde_replica --linaje`. Datos "
        "completos en `linaje.json`.", "",
        "## De dónde salen", "",
        r["exportacion_original"], "",
        "## Reconstrucción desde la réplica (solo lectura, lector_ia)", "",
        "| Archivo empaquetado | Filas | SHA-256 del contenido empaquetado | SHA-256 reconstruido | ¿Idéntico? |",
        "|---|---:|---|---|---|",
        f"| `datos/demanda_horaria.parquet` (ruta, idruta, fecha, hora, pasajeros, salidas) | "
        f"{_n(dh['comparacion']['filas_empaquetadas'])} | `{dh['sha256_contenido_empaquetado'][:16]}…` | "
        f"`{dh['sha256_contenido_reconstruido'][:16]}…` | {'sí' if dh['contenido_identico'] else 'no'} |",
        f"| `datos/contexto_operacional.parquet` (fecha, hora, nov_impacto, nov_sube, festivo_oficial) | "
        f"{_n(cx['comparacion']['filas_empaquetadas'])} | `{cx['sha256_contenido_empaquetado'][:16]}…` | "
        f"`{cx['sha256_contenido_reconstruido'][:16]}…` | {'sí' if cx['contenido_identico'] else 'no'} |", "",
        f"- Pasajeros: {_n(cp['iguales'])} franjas iguales y {_n(cp['distintas'])} distintas; suma empaquetada "
        f"{_n(cp['suma_empaquetado'])} frente a {_n(cp['suma_replica'])} reconstruida.",
        f"- Salidas: {_n(cs['iguales'])} iguales y {_n(cs['distintas'])} distintas.",
        f"- Filas solo en lo empaquetado: {dh['comparacion']['solo_empaquetado']}; solo en la reconstrucción: "
        f"{dh['comparacion']['solo_replica']}.",
        f"- No se reconstruye: {dh['no_reconstruido']}.", "",
        "## Huellas de las entradas (réplica)", "",
        "| Tabla | Filas | SHA-256 del contenido |", "|---|---:|---|",
        f"| progvehiculos (2023-2025; {e['progvehiculos']['columnas']}) | "
        f"{_n(e['progvehiculos']['filas_2023_2025'])} | "
        f"`{e['progvehiculos']['sha256_contenido']}` |",
    ]
    for nombre in CONTEXTO:
        filas.append(f"| {nombre} | {_n(e[nombre]['filas'])} | `{e[nombre]['sha256_contenido']}` |")
    filas += ["", "## Huellas de los archivos empaquetados", "",
              f"- `datos/demanda_horaria.parquet`: `{dh['sha256_archivo']}`",
              f"- `datos/contexto_operacional.parquet`: `{cx['sha256_archivo']}`", "",
              "## Reglas", "",
              "- Viaje válido: `finalizado = 'S'` y `cancelada = 'N'` en progvehiculos; la hora es la de `fechasalida` "
              "(4 a 20 h: no hay salidas válidas a las 21 h en 2023-2025).",
              "- `pasajeros` = Σ `numeropasajeros` de los viajes válidos con dato y ≤ 300 (ceros incluidos); "
              "`salidas` = número de viajes válidos; una franja sin viajes vale 0.",
              "- Contexto: `preparar_datos_api.contexto_desde_tablas` (novedades viales por fecha y rango horario; "
              f"novedades_viales_ruta tiene {e['novedades_viales_ruta']['filas']} filas, así que cada novedad aplica "
              "a las tres rutas; festivos oficiales = FESTIVO_NACIONAL de estacionalidades_anio).", ""]
    return "\n".join(filas)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--linaje", action="store_true")
    ap.add_argument("--definicion-pasajeros", action="store_true")
    ap.add_argument("--muestra-consolidado", action="store_true")
    a = ap.parse_args(argv)
    if not (a.linaje or a.definicion_pasajeros or a.muestra_consolidado):
        a.linaje = a.definicion_pasajeros = True
    f = _fuente()
    EVIDENCIAS.mkdir(parents=True, exist_ok=True)
    if a.muestra_consolidado:
        print(f"muestra de timbradas_consolidado: {muestra_consolidado(f)} filas -> {FIXTURE.relative_to(RAIZ)}")
    if a.definicion_pasajeros:
        r = definicion_pasajeros(f)
        (EVIDENCIAS / "definicion_pasajeros.json").write_text(json.dumps(r, ensure_ascii=False, indent=1),
                                                              encoding="utf-8")
        print("definición de pasajeros:", json.dumps(r["total"], ensure_ascii=False), "material:", r["material"])
    if a.linaje:
        r = linaje(f)
        (EVIDENCIAS / "linaje.json").write_text(json.dumps(r, ensure_ascii=False, indent=1, default=str),
                                                encoding="utf-8")
        (EVIDENCIAS / "linaje.md").write_text(_md_linaje(r), encoding="utf-8")
        print("demanda_horaria idéntica:", r["demanda_horaria"]["contenido_identico"],
              "· contexto idéntico:", r["contexto_operacional"]["contenido_identico"])
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")      # consola de Windows (cp1252)
    raise SystemExit(main())
