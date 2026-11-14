"""Lo que el ciclo le consulta a la base de Extreme por cada tabla consolidada en una ejecución sin novedades, antes y
después de filtrar el proceso en el SQL (§6.1, §8.3 «no interferencia», §18 «Consulta pesada»; hallazgos H4, H7 y H12
de docs/hallazgos_extreme.md), medido en la réplica LOCAL con EXPLAIN (ANALYZE, BUFFERS).

- Antes: la lectura incremental sin filtrar el proceso (fuentes.consulta_incremental con proceso «*»: el filtro se
  hacía después, en Python, así que las filas de otros operadores se leían, entraban en las huellas que se guardan en
  marca_agua_tabla.estado_fuente y movían la marca) y, si no llegaba nada del proceso, el count(*) por tabla y proceso
  de consolidados._sin_filas (SQL_CONTEO_RETIRADO).
- Ahora: la lectura incremental con «proceso = :proceso» en el SQL (fuentes.TABLAS_CON_PROCESO) y ninguna otra
  consulta: consolidados._sin_filas decide con lo que ya hizo la lectura.

Escenarios:
1. Las tres tablas del ciclo (consolidados.TABLAS) tal como están en la réplica: timbradas_consolidado con las filas de
   Sobusa, sin novedades (la lectura desde su marca menos el solape: lo que relee cada ciclo entre dos cierres), y las
   dos por segmento, vacías en la réplica (H4: sin marca guardada, cada ciclo lee desde la marca inicial).
2. Volumen de otro operador. En la base de Extreme las tablas por segmento traen filas de cootransoriente (H4) y en la
   réplica están vacías. Dentro de UNA transacción que se revierte se crea una tabla TEMPORAL con el nombre y las
   columnas de timbradas_segmentos_consolidado (CREATE TEMP TABLE ... (LIKE public...) ON COMMIT DROP), que en esa
   sesión tapa a la real (PostgreSQL busca primero en pg_temp), con filas del proceso «cootransoriente»: tantas como
   las de timbradas_consolidado de Sobusa por los segmentos promedio de una ruta (el mismo grano más el segmento), y
   todas con la misma ultima_actualizacion (el cierre nocturno resella toda la tabla, H7). Se miden las mismas
   consultas del ciclo, sin esquema, como las compila fuentes.py, y además lo que hacía después la API con la lectura
   de antes: traer las filas y calcular sus huellas con fuentes._filtrar_huellas (la regla exacta de la lectura
   incremental), con el tamaño del estado que se guardaba. La tabla real no se toca y nada queda: la temporal solo
   existe en esa transacción y el ROLLBACK la borra (al terminar se comprueba que ya no existe).

Corre como extreme_dba (lector_ia, el usuario de la API, no tiene el privilegio TEMP en la réplica), con el candado de
las simulaciones de la réplica (scripts/replica_simular_llegada.candado), lock_timeout y statement_timeout; cada
consulta se mide REPETICIONES veces y se informa la más rápida (scripts/replica_indices_candidatos.py, la misma forma de
medir). Escribe docs/evidencias/consolidados/lectura_por_proceso.json y .md.

Uso (desde EntregaFinal/api_frecuencias, con la réplica levantada y OPERACIONAL_PASSWORD en el .env):
  python -m scripts.replica_lectura_consolidados
"""
from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass, field
from datetime import datetime

from scripts import replica_comun as rc
from scripts import replica_indices_candidatos as ric

SALIDA = rc.RAIZ / "docs" / "evidencias" / "consolidados"
PROCESO = "sobusa"
OTRO_PROCESO = "cootransoriente"
TABLA_SINTETICA = "timbradas_segmentos_consolidado"
# El count(*) por tabla y proceso que hacía consolidados._sin_filas en cada ejecución sin filas nuevas (retirado: aquí
# solo se mide; la misma definición de scripts/replica_indices_candidatos.py).
SQL_CONTEO_RETIRADO = ric.SQL_CONTEO_RETIRADO
SQL_TEMPORAL = (f"CREATE TEMP TABLE {TABLA_SINTETICA} (LIKE public.{TABLA_SINTETICA} INCLUDING DEFAULTS) "
                "ON COMMIT DROP")
# Una fila por segmento × día × hora × estacionalidad, todas del otro operador y con el mismo sello (H7). Texto fijo
# (sin formato): la tabla es la temporal de TABLA_SINTETICA y los valores van por parámetro.
SQL_FILAS_SINTETICAS = """
INSERT INTO pg_temp.timbradas_segmentos_consolidado
    (id_timbrada_segmentos_consolidado, id_segmento, proceso, id_ruta, id_dia_semana, id_estacionalidad, hora,
     hora_inicio, hora_fin, subidas, bajadas, pasajeros, nro_viajes, promedio_subidas, promedio_bajadas,
     promedio_pasajeros, ultima_actualizacion)
SELECT g, 1 + mod(g, %(segmentos)s), %(proceso)s, 9001, 1 + mod(g / %(segmentos)s, 7),
       1 + g / (%(segmentos)s * 7 * 17), make_time(4 + mod(g / (%(segmentos)s * 7), 17), 0, 0),
       make_time(4 + mod(g / (%(segmentos)s * 7), 17), 0, 0), make_time(5 + mod(g / (%(segmentos)s * 7), 17), 0, 0),
       10 + mod(g, 50), 9 + mod(g, 50), mod(g, 30), 4, 2.5, 2.25, 7.5, CAST(%(sello)s AS timestamp)
  FROM generate_series(0, %(filas)s - 1) AS g
"""
SQL_EXISTE_TEMPORAL = f"SELECT to_regclass('pg_temp.{TABLA_SINTETICA}') IS NOT NULL"
# La marca y las filas del proceso de cada tabla del ciclo (consolidados.TABLAS), texto fijo por tabla
SQL_MARCA_Y_FILAS = {
    "timbradas_consolidado": ("SELECT max(ultima_actualizacion), count(*) FROM public.timbradas_consolidado "
                              "WHERE proceso = %s"),
    "timbradas_segmentos_anio": ("SELECT max(ultima_actualizacion), count(*) FROM public.timbradas_segmentos_anio "
                                 "WHERE proceso = %s"),
    "timbradas_segmentos_consolidado": ("SELECT max(ultima_actualizacion), count(*) FROM "
                                        "public.timbradas_segmentos_consolidado WHERE proceso = %s"),
}
SELLO_POR_OMISION = datetime(2026, 8, 13, 22, 0, tzinfo=ric.ZONA)      # si la réplica no trae consolidado de Sobusa
# Índices candidatos para las tablas por segmento, medidos sobre la TEMPORAL (nunca sobre la tabla real): el de la marca
# sola (el de la propuesta de la ola A) y el de proceso y marca (el que sirve a «proceso = :proceso» desde la marca)
INDICES_SINTETICOS = (("ix_ia_tmp_marca", "ultima_actualizacion"),
                      ("ix_ia_tmp_proceso_marca", "proceso, ultima_actualizacion"))
# Segmentos promedio de las rutas del proceso en su configuración activa (rutas_segmentos_config.numero_segmentos
# viene vacío en la réplica: se cuentan los de rutas_segmentos)
SQL_SEGMENTOS_POR_RUTA = """
SELECT round(avg(n)) FROM (
    SELECT rs.idruta, count(*) AS n FROM public.rutas_segmentos rs
      JOIN public.rutas_segmentos_config c ON c.id = rs.id_config AND c.activo
     WHERE rs.idruta IN (SELECT DISTINCT t.id_ruta FROM public.timbradas_consolidado t WHERE t.proceso = %s)
     GROUP BY rs.idruta) x
"""


@dataclass
class Escenario:
    """Las consultas de una tabla en una ejecución sin novedades: las de antes y las de ahora."""

    clave: str
    descripcion: str
    antes: list = field(default_factory=list)
    ahora: list = field(default_factory=list)


def consultas_de_la_tabla(motor, tabla: str, desde: datetime) -> tuple[list, list]:
    """(antes, ahora) del ciclo para `tabla` desde `desde`: la lectura sin filtrar el proceso y el count(*) retirado;
    la lectura del proceso en el SQL. Los SELECT son los de fuentes.consulta_incremental, compilados para el driver."""
    sql_todos, params_todos = ric._incremental(motor, tabla, None)
    sql_proceso, params_proceso = ric._incremental(motor, tabla, PROCESO)
    conteo = ric._compilar(motor, SQL_CONTEO_RETIRADO.format(tabla=tabla))
    antes = [ric.Consulta(f"{tabla}_lectura_sin_filtro", "lectura incremental sin filtrar el proceso",
                          "fuentes.consulta_incremental (proceso «*»)", sql_todos, dict(params_todos, marca=desde)),
             ric.Consulta(f"{tabla}_conteo_del_proceso", "count(*) del proceso (consolidados._sin_filas, retirado)",
                          "SQL_CONTEO_RETIRADO", conteo, {"proceso": PROCESO})]
    ahora = [ric.Consulta(f"{tabla}_lectura_del_proceso", "lectura incremental del proceso en el SQL",
                          "fuentes.consulta_incremental (TABLAS_CON_PROCESO)", sql_proceso,
                          dict(params_proceso, marca=desde, proceso=PROCESO))]
    return antes, ahora


def escenarios_reales(motor, ctx: dict) -> list[Escenario]:
    """Las tres tablas del ciclo como están en la réplica (sin novedades)."""
    from app.servicios import consolidados, fuentes

    salida = []
    for tabla in consolidados.TABLAS:
        marca = ctx["marcas"].get(tabla)
        desde = marca - ric.SOLAPE if marca is not None else fuentes.MARCA_INICIAL
        texto = (f"sin novedades: desde la marca {marca.isoformat()} menos el solape" if marca is not None else
                 "sin filas del proceso en la réplica (H4): sin marca guardada, desde la marca inicial")
        antes, ahora = consultas_de_la_tabla(motor, tabla, desde)
        salida.append(Escenario(tabla, f"{tabla}, {texto}", antes, ahora))
    return salida


def filas_sinteticas(ctx: dict) -> int:
    """Las filas de un operador del tamaño de Sobusa en timbradas_segmentos_consolidado: las de su
    timbradas_consolidado (ruta × día × estacionalidad × hora) por los segmentos promedio de una ruta."""
    return int(ctx["filas_consolidado"]) * int(ctx["segmentos_por_ruta"])


def contexto(cx) -> dict:
    """Las marcas y los tamaños reales de la réplica (solo lectura de catálogos y de las tablas)."""
    from app.servicios import consolidados

    marcas = {}
    with cx.cursor() as cur:
        for tabla in consolidados.TABLAS:
            cur.execute(SQL_MARCA_Y_FILAS[tabla], (PROCESO,))
            marca, filas = cur.fetchone()
            marcas[tabla] = {"marca": marca, "filas": int(filas)}
        cur.execute(SQL_SEGMENTOS_POR_RUTA, (PROCESO,))
        segmentos = int(cur.fetchone()[0] or 0)
    return {"marcas": {t: (v["marca"].replace(tzinfo=ric.ZONA) if v["marca"] else None) for t, v in marcas.items()},
            "filas_del_proceso": {t: v["filas"] for t, v in marcas.items()},
            "filas_consolidado": marcas[consolidados.TABLA_RUTA]["filas"], "segmentos_por_ruta": segmentos}


# ---------------------------------------------------------------- medición
def _medir(conn, consultas: list) -> dict:
    """Cada consulta con ric._mejor (EXPLAIN ANALYZE BUFFERS, la más rápida de las repeticiones) y el total."""
    medidas = {c.clave: dict(ric._mejor(conn, c), descripcion=c.descripcion, origen=c.origen) for c in consultas}
    return {"consultas": len(consultas), "ms_total": round(sum(m["ms_ejecucion"] for m in medidas.values()), 2),
            "filas_leidas": sum(int(m["filas"] or 0) for m in medidas.values() if "lectura" in m["descripcion"]),
            "detalle": medidas}


def medir_escenario(conn, e: Escenario) -> dict:
    return {"escenario": e.clave, "descripcion": e.descripcion, "antes": _medir(conn, e.antes),
            "ahora": _medir(conn, e.ahora)}


def huellas_de_la_lectura(conn, consulta, tabla: str, proceso: str | None) -> dict:
    """Lo que hacía la API con una lectura: traer las filas y pasarlas por fuentes._filtrar_huellas (la regla exacta de
    la lectura incremental) desde la marca inicial; cuántas huellas quedaban en el estado y cuánto pesaba en JSON."""
    import pandas as pd

    from app.servicios import fuentes

    t0 = time.perf_counter()
    resultado = conn.exec_driver_sql(consulta.sql, consulta.params)
    d = pd.DataFrame(resultado.fetchall(), columns=list(resultado.keys()))
    traer = time.perf_counter() - t0
    f = fuentes.FuentePostgresSoloLectura(url="postgresql+psycopg://lector_ia@localhost/x", tabla=tabla,
                                          motor=object(), proceso=proceso or "*")
    t1 = time.perf_counter()
    _salida, _marca, resumen, estado = fuentes._filtrar_huellas(f, d, fuentes.MARCA_INICIAL, fuentes.MARCA_INICIAL,
                                                                None)
    return {"filas_traidas": int(len(d)), "segundos_traer": round(traer, 2),
            "segundos_huellas": round(time.perf_counter() - t1, 2), "huellas_en_el_estado": len(estado["huellas"]),
            "mb_estado_fuente": round(len(json.dumps(estado, default=str)) / 2**20, 2),
            "truncada": bool(resumen.get("truncada"))}


def medir_sintetico(conn, motor, ctx: dict) -> dict:
    """La tabla por segmento con filas de otro operador, en la transacción de `conn` (que el llamador revierte). El
    sello de todas sus filas es la marca de timbradas_consolidado de la réplica (el último cierre)."""
    from app.servicios import consolidados, fuentes

    filas = filas_sinteticas(ctx)
    sello = ctx["marcas"][consolidados.TABLA_RUTA] or SELLO_POR_OMISION
    t0 = time.perf_counter()
    conn.exec_driver_sql(SQL_TEMPORAL)
    conn.exec_driver_sql(SQL_FILAS_SINTETICAS, {"segmentos": ctx["segmentos_por_ruta"], "proceso": OTRO_PROCESO,
                                                "sello": sello.replace(tzinfo=None), "filas": filas})
    conn.exec_driver_sql(f"ANALYZE pg_temp.{TABLA_SINTETICA}")     # temporal: sus estadísticas mueren con ella
    carga = time.perf_counter() - t0
    antes, ahora = consultas_de_la_tabla(motor, TABLA_SINTETICA, fuentes.MARCA_INICIAL)
    e = Escenario(f"{TABLA_SINTETICA}_con_otro_operador",
                  f"{TABLA_SINTETICA} con {_n(filas)} filas de {OTRO_PROCESO} y ninguna de {PROCESO} (H4), todas con "
                  "el sello del último cierre (H7): cada ejecución, desde la marca inicial", antes, ahora)
    r = medir_escenario(conn, e)
    r.update(filas_sinteticas=filas, segmentos_por_ruta=ctx["segmentos_por_ruta"], sello=sello.isoformat(),
             segundos_carga=round(carga, 1))
    r["antes"]["api"] = huellas_de_la_lectura(conn, antes[0], TABLA_SINTETICA, None)
    r["ahora"]["api"] = huellas_de_la_lectura(conn, ahora[0], TABLA_SINTETICA, PROCESO)
    r["indices"] = medir_indices(conn, ahora[0])
    return r


def medir_indices(conn, consulta) -> list[dict]:
    """La lectura de ahora sobre la tabla temporal con cada índice candidato de INDICES_SINTETICOS (creado sobre la
    TEMPORAL, en la misma transacción que se revierte, y borrado antes del siguiente): cuál sirve a la lectura del
    proceso cuando la tabla es de otro operador. La propuesta para el DBA (propuesta_indices.sql) sale de aquí para las
    tablas por segmento."""
    salida = []
    for nombre, columnas in INDICES_SINTETICOS:
        conn.exec_driver_sql(f"CREATE INDEX {nombre} ON pg_temp.{TABLA_SINTETICA} ({columnas})")   # constantes
        conn.exec_driver_sql(f"ANALYZE pg_temp.{TABLA_SINTETICA}")
        m = ric._mejor(conn, consulta)
        salida.append({"indice": nombre, "columnas": columnas, "ms_ejecucion": m["ms_ejecucion"],
                       "filas": m["filas"], "escaneos": m["escaneos"], "usa_el_indice": ric._usa(m, nombre)})
        conn.exec_driver_sql(f"DROP INDEX pg_temp.{nombre}")
    return salida


def medir(con_sintetico: bool = True) -> dict:
    from scripts.replica_simular_llegada import candado, conectar

    motor = ric._motor_dba()
    admin = conectar("extreme_dba", autocommit=True)
    informe: dict = {"generado": datetime.now(ric.ZONA).isoformat(timespec="seconds"), "rol": "extreme_dba",
                     "metodo": ("una transacción que se revierte; EXPLAIN (ANALYZE, BUFFERS), la más rápida de "
                                f"{ric.REPETICIONES} corridas por consulta; lock_timeout {ric.ESPERA_CANDADO}"),
                     "proceso": PROCESO, "otro_proceso": OTRO_PROCESO}
    try:
        with candado(admin):
            ctx = contexto(admin)
            informe["contexto"] = {"marcas": {t: (m.isoformat() if m else None) for t, m in ctx["marcas"].items()},
                                   "filas_del_proceso": ctx["filas_del_proceso"],
                                   "segmentos_por_ruta": ctx["segmentos_por_ruta"]}
            with motor.connect() as conn:
                try:
                    ric._preparar(conn)
                    informe["reales"] = [medir_escenario(conn, e) for e in escenarios_reales(motor, ctx)]
                    if con_sintetico:
                        informe["sintetico"] = medir_sintetico(conn, motor, ctx)
                finally:
                    conn.rollback()
                informe["temporal_al_terminar"] = bool(conn.exec_driver_sql(SQL_EXISTE_TEMPORAL).scalar())
                conn.rollback()
    finally:
        admin.close()
        motor.dispose()
    return informe


# ---------------------------------------------------------------- informe
def _n(x) -> str:
    """Entero con punto de miles; decimal con coma."""
    if isinstance(x, float):
        return f"{x:,.2f}".replace(",", "§").replace(".", ",").replace("§", ".")
    return f"{int(x):,}".replace(",", ".")


def _fila(nombre: str, lado: dict) -> str:
    api = lado.get("api") or {}
    extra = (f" | {_n(api['filas_traidas'])} | {_n(api['huellas_en_el_estado'])} | {_n(api['mb_estado_fuente'])} MB"
             if api else " | — | — | —")
    return f"| {nombre} | {lado['consultas']} | {ric._ms(lado['ms_total'])} | {_n(lado['filas_leidas'])}{extra} |"


def _informe_indices(s: dict) -> list[str]:
    """La lectura del proceso sobre la tabla temporal sin índice y con cada índice candidato (sobre la temporal)."""
    if not s.get("indices"):
        return []
    sin = next(iter(s["ahora"]["detalle"].values()))
    lin = ["", "Índices candidatos para las tablas por segmento, creados sobre la TEMPORAL dentro de la misma "
               "transacción (nunca sobre la tabla real) y medidos con la lectura de ahora (la del proceso desde la "
               "marca inicial):", "", "| Índice | Columnas | ms | Filas | Escaneos |", "|---|---|---|---|---|",
           f"| (ninguno) | — | {ric._ms(sin['ms_ejecucion'])} | {_n(sin['filas'] or 0)} | "
           f"{', '.join(sin['escaneos'])} |"]
    lin += [f"| `{i['indice']}` | {i['columnas']} | {ric._ms(i['ms_ejecucion'])} | {_n(i['filas'] or 0)} | "
            f"{', '.join(i['escaneos'])} |" for i in s["indices"]]
    lin += ["", conclusion_indices(sin["ms_ejecucion"], s["indices"])]
    return lin


def conclusion_indices(ms_sin: float, indices: list[dict]) -> str:
    """Qué índice sirve a la lectura del proceso en la tabla de otro operador, con el criterio de
    scripts/replica_indices_candidatos.py (lo usa y baja al menos MEJORA_MINIMA y AHORRO_MINIMO_MS)."""
    sirven = [i for i in indices if i["usa_el_indice"] and ms_sin - i["ms_ejecucion"] >= ric.AHORRO_MINIMO_MS
              and ms_sin > 0 and 1 - i["ms_ejecucion"] / ms_sin >= ric.MEJORA_MINIMA]
    if not sirven:
        return "Ningún índice candidato cumple el criterio con este volumen."
    mejor = min(sirven, key=lambda i: i["ms_ejecucion"])
    otros = "; ".join(f"`{i['indice']}` ({i['columnas']}): {ric._ms(i['ms_ejecucion'])} ms"
                      + ("" if i in sirven else " (no cumple el criterio)") for i in indices if i is not mejor)
    texto = (f"Cumple el criterio y es el más rápido `{mejor['indice']}` ({mejor['columnas']}): la lectura del proceso "
             f"baja de {ric._ms(ms_sin)} a {ric._ms(mejor['ms_ejecucion'])} ms" + (f"; {otros}" if otros else "") + ".")
    sola = next((i for i in indices if i["columnas"] == "ultima_actualizacion"), None)
    if sola is not None and sola not in sirven:
        texto += (" La marca sola no sirve aquí: todas las filas de los otros operadores son posteriores a la marca "
                  "inicial (sin filas del proceso no hay marca guardada), así que el índice no evita recorrerlas.")
    return texto


def informe_md(r: dict) -> str:
    ctx = r["contexto"]
    lin = ["# Lectura de los consolidados por proceso y sin count(*), medida en la réplica", "",
           f"Generado {r['generado']} con `python -m scripts.replica_lectura_consolidados` como {r['rol']}. Método: "
           f"{r['metodo']}. Filas de {r['proceso']} en la réplica: "
           + ", ".join(f"{t} {_n(n)}" for t, n in ctx["filas_del_proceso"].items()) + ".", "",
           "Antes: la lectura incremental sin filtrar el proceso (el filtro se hacía en Python) y, sin filas del "
           "proceso, el `count(*)` por tabla y proceso de `consolidados._sin_filas`. Ahora: la lectura con "
           "`proceso = :proceso` en el SQL (`fuentes.TABLAS_CON_PROCESO`) y ninguna otra consulta.", "",
           "| Escenario | Lado | Consultas a la fuente | ms en el servidor | Filas leídas | Filas a la API | Huellas "
           "guardadas | estado_fuente |", "|---|---|---|---|---|---|---|---|"]
    filas = [*r.get("reales", []), *([r["sintetico"]] if r.get("sintetico") else [])]
    for e in filas:
        for lado in ("antes", "ahora"):
            lin.append(f"| {e['escenario']} " + _fila(lado, e[lado]))
    lin += ["", "Escenarios:", ""]
    lin += [f"- `{e['escenario']}`: {e['descripcion']}." for e in filas]
    s = r.get("sintetico")
    if s:
        api = s["antes"]["api"]
        lin += ["", f"La tabla temporal se cargó con {_n(s['filas_sinteticas'])} filas ({s['segmentos_por_ruta']} "
                    f"segmentos por ruta × las filas de timbradas_consolidado de {r['proceso']}) en "
                    f"{_n(float(s['segundos_carga']))} s y existió solo en la transacción revertida: al terminar, "
                    f"`to_regclass('pg_temp.{TABLA_SINTETICA}')` es "
                    f"{'NO NULO (revisar)' if r.get('temporal_al_terminar') else 'nulo'}. Antes, la API traía "
                    f"{_n(api['filas_traidas'])} filas ajenas"
                    + (" (la lectura llegaba al límite de filas)" if api["truncada"] else "")
                    + f" en {_n(float(api['segundos_traer']))} s, calculaba sus huellas en "
                    f"{_n(float(api['segundos_huellas']))} s y guardaba {_n(api['huellas_en_el_estado'])} en "
                    f"`marca_agua_tabla.estado_fuente` ({_n(float(api['mb_estado_fuente']))} MB de JSON), en cada "
                    "ejecución: con el sello del cierre (H7) toda la tabla cae en la ventana de solape. Ahora no trae "
                    "ninguna."]
        lin += _informe_indices(s)
    lin += ["", "Las cifras absolutas dependen de la carga del equipo (la réplica corre en el mismo equipo que las "
                "pruebas). Sin índice sobre `proceso` ni sobre `ultima_actualizacion` (H12) la lectura sigue "
                "recorriendo la tabla; lo que se quita es el segundo recorrido (`count(*)`) y las filas de otros "
                "operadores que viajaban a la API. Crear índices es decisión de Extreme "
                "(`docs/evidencias/replica/propuesta_indices.sql`).", ""]
    return "\n".join(lin)


def escribir(r: dict) -> None:
    SALIDA.mkdir(parents=True, exist_ok=True)
    (SALIDA / "lectura_por_proceso.json").write_text(json.dumps(r, ensure_ascii=False, indent=1, default=str),
                                                     encoding="utf-8")
    (SALIDA / "lectura_por_proceso.md").write_text(informe_md(r), encoding="utf-8")


def main(argv: list[str] | None = None) -> dict:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--sin-sintetico", action="store_true", help="solo las tablas reales de la réplica")
    a = p.parse_args(argv)
    r = medir(con_sintetico=not a.sin_sintetico)
    escribir(r)
    print(informe_md(r))
    return r


if __name__ == "__main__":
    main()
