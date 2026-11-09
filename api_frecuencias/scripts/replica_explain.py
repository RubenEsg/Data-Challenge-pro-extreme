"""EXPLAIN (ANALYZE, BUFFERS) de cada consulta incremental de la API sobre la réplica, COMO LECTOR_IA (E07, §8.3,
§11.3, §14.1 «Rendimiento: SQL EXPLAIN y prueba de volumen»).

1. Compila el SQL EXACTO que genera FuentePostgresSoloLectura.consulta_incremental (y la capa analítica de segmentos)
   y lo explica en la misma sesión que usa la API: READ ONLY, statement_timeout y TimeZone America/Bogota, con una
   marca real (la de una lectura diaria: la marca máxima de la tabla menos 24 h, o la de la carga).
2. Aplica la PROPUESTA de índices (docs/evidencias/replica/propuesta_indices.sql) SOLO EN LA RÉPLICA y como
   extreme_dba, el dueño de la base: §8.3 dice que los índices los aplica el responsable de la base de datos.
3. Vuelve a medir con los índices.
4. Los borra (la réplica vuelve a ser fiel a Extreme), salvo --conservar-indices.
Guarda docs/evidencias/replica/explain_incremental.txt y .json con planes, tiempos, buffers y el argumento de volumen.

Uso: .venv\\Scripts\\python -m scripts.replica_explain
"""
from __future__ import annotations

import argparse
import json
import re
import time
from datetime import datetime

from scripts import replica_comun as rc

RAIZ = rc.RAIZ
SALIDA = RAIZ / "docs" / "evidencias" / "replica"
PROPUESTA = SALIDA / "propuesta_indices.sql"
TABLAS = ("demanda_segmentos", "timbradas_segmentos", "timbradas_consolidado", "timbradas_anio",
          "timbradas_segmentos_anio", "timbradas_segmentos_consolidado")
MARCA_DE = {"demanda_segmentos": ("timbradas_segmentos", "ultimaactualizacion"),
            "timbradas_segmentos": ("timbradas_segmentos", "ultimaactualizacion")}

PROPUESTA_SQL = """-- Propuesta de índices para el DBA de Extreme Technologies (§8.3: se piden después de revisar
-- EXPLAIN (ANALYZE, BUFFERS) y los aplica el responsable de la base). Generada por scripts/replica_explain.py y medida
-- SOLO en la réplica local. En producción, CONCURRENTLY no bloquea las escrituras de la captura ni de los triggers.
-- Ninguno cambia tablas, triggers, funciones ni scripts: solo acelera las lecturas incrementales del módulo de IA.

-- 1) Lectura incremental de timbradas_segmentos (lo que escribe tg_timbrada_segmento) por marca de agua.
CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_ia_timbradas_segmentos_ultimaactualizacion
    ON public.timbradas_segmentos (ultimaactualizacion);
-- 2) Re-agregación de las franjas tocadas: segmentos de un viaje (la llave foránea id_viaje no tiene índice).
CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_ia_timbradas_segmentos_id_viaje
    ON public.timbradas_segmentos (id_viaje);
-- 3) Viajes de una ruta en una hora de salida (franja de la demanda horaria).
CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_ia_progvehiculos_ruta_hora_salida
    ON public.progvehiculos (idruta, (date_trunc('hour', fechasalida)));
-- 4) Marca de agua de los consolidados (§8.3: «consultar los incrementos por ultima_actualizacion»).
CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_ia_timbradas_consolidado_ultima_actualizacion
    ON public.timbradas_consolidado (ultima_actualizacion);
CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_ia_timbradas_anio_ultima_actualizacion
    ON public.timbradas_anio (ultima_actualizacion);
CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_ia_timbradas_segmentos_anio_ultima_actualizacion
    ON public.timbradas_segmentos_anio (ultima_actualizacion);
CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_ia_timbradas_segmentos_consolidado_ultima_actualizacion
    ON public.timbradas_segmentos_consolidado (ultima_actualizacion);
"""


def _indices_propuestos() -> list[str]:
    return re.findall(r"IF NOT EXISTS (\w+)", PROPUESTA_SQL)


def _url_lector() -> str:
    url = rc.url_rol("lector_ia")
    if not url:
        raise SystemExit("Falta LECTOR_IA_PASSWORD en el entorno o en el .env local.")
    return url.replace("postgresql://", "postgresql+psycopg://")


def marca_de_lectura(cur, tabla: str, filas_dia: int) -> datetime:
    """Marca de una lectura DIARIA típica: la que deja por delante el volumen de un día. Las marcas de la carga se
    sellaron en pocas horas, así que «máximo − 24 h» leería toda la tabla; se usa el volumen diario medido
    (timbradas_segmentos: filas/día de la réplica; timbradas_anio: ~200 filas/día que toca la liquidación) y, en
    timbradas_consolidado, la tabla completa porque fn_consolidar la vuelve a sellar entera cada noche (H7)."""
    origen, col = MARCA_DE.get(tabla, (tabla, "ultima_actualizacion"))
    desfase = {"demanda_segmentos": filas_dia, "timbradas_segmentos": filas_dia, "timbradas_anio": 200}.get(tabla)
    if desfase is None:
        cur.execute(f"SELECT min({col}) - INTERVAL '1 second' FROM public.{origen}")  # nosec B608  # identificadores de constantes del script; valores por parámetro  # noqa: S608 - constantes
    else:
        # muchas filas comparten la misma marca (una transacción): se toma la marca distinta anterior al bloque
        # que completa el volumen del día, para que «marca > M» devuelva al menos ese volumen
        cur.execute(f"""SELECT m FROM (SELECT {col} AS m, sum(count(*)) OVER (ORDER BY {col} DESC) AS acumulado
                                         FROM public.{origen} GROUP BY {col}) x
                        WHERE acumulado >= %s ORDER BY m DESC OFFSET 1 LIMIT 1""",  # nosec B608  # noqa: S608
                    (int(desfase),))
    fila = cur.fetchone()
    m = fila[0] if fila else None
    if m is None:
        from datetime import UTC

        return datetime(1970, 1, 2, tzinfo=UTC)     # tabla vacía en la réplica: se lee desde la marca inicial
    from zoneinfo import ZoneInfo

    return m.replace(tzinfo=ZoneInfo("America/Bogota"))


def _con_zona(m: datetime) -> datetime:
    from zoneinfo import ZoneInfo

    return m.replace(tzinfo=ZoneInfo("America/Bogota"))


def sql_compilado(fuente, motor):
    """(sql con marcadores del driver, parámetros) de la consulta incremental de la fuente."""
    sentencia = fuente.consulta_incremental()
    compilado = sentencia.compile(dialect=motor.dialect)
    return str(compilado), dict(compilado.params)


def explicar(motor, sql: str, params: dict) -> dict:
    """EXPLAIN (ANALYZE, BUFFERS) en TEXT y JSON, en la sesión de la API (READ ONLY, timeout, TimeZone)."""
    salida = {}
    with motor.connect() as conn:
        try:
            conn.exec_driver_sql("SET TRANSACTION READ ONLY")
            conn.exec_driver_sql("SET LOCAL statement_timeout = 60000")
            conn.exec_driver_sql("SET LOCAL TimeZone = 'America/Bogota'")
            t0 = time.perf_counter()
            texto = conn.exec_driver_sql("EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT) " + sql, params).scalars().all()
            salida["ms_cliente"] = round(1000 * (time.perf_counter() - t0), 1)
            plan = conn.exec_driver_sql("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + sql, params).scalar()
        finally:
            conn.rollback()
    raiz = plan[0]
    nodo = raiz["Plan"]
    nodos = []

    def recorrer(n):
        nodos.append(n)
        for h in n.get("Plans", []):
            recorrer(h)

    recorrer(nodo)
    escaneos = [f"{n['Node Type']} {n.get('Relation Name', '')} {n.get('Index Name', '')}".strip()
                for n in nodos if "Scan" in n["Node Type"]]
    salida.update(
        texto="\n".join(texto), ms_ejecucion=round(raiz.get("Execution Time", 0.0), 2),
        ms_planificacion=round(raiz.get("Planning Time", 0.0), 2), filas=nodo.get("Actual Rows"),
        buffers_hit=sum(n.get("Shared Hit Blocks", 0) for n in nodos if "Plans" not in n),
        buffers_read=sum(n.get("Shared Read Blocks", 0) for n in nodos if "Plans" not in n),
        escaneos=escaneos, filas_descartadas_por_filtro=sum(n.get("Rows Removed by Filter", 0) for n in nodos))
    return salida


def medir(motor, etiqueta: str, marcas: dict) -> dict:
    from app.servicios.fuentes import FuentePostgresSoloLectura

    salida = {}
    for tabla in TABLAS:
        f = FuentePostgresSoloLectura(url="postgresql+psycopg://lector_ia@localhost/x", tabla=tabla, motor=motor,
                                      solape_min=15)
        sql, params = sql_compilado(f, motor)
        params.update(marca=marcas[tabla], limite=f.limite)   # «desde» ya incluye el solape del día
        if "proceso" in params:                                # demanda_segmentos filtra por FUENTE_PROCESO
            params["proceso"] = f.proceso
        try:
            salida[tabla] = {"marca": marcas[tabla].isoformat(), **explicar(motor, sql, params)}
        except Exception as exc:  # noqa: BLE001 - se registra y sigue con las demás
            salida[tabla] = {"error": str(exc).splitlines()[0]}
        print(f"[{etiqueta}] {tabla}: {salida[tabla].get('ms_ejecucion')} ms, filas={salida[tabla].get('filas')}, "
              f"escaneos={salida[tabla].get('escaneos')}")
    try:
        from app.servicios import segmentos

        sql, params = segmentos.sql_estadisticas_para_explain(motor)
        salida["segmentos_estadisticas"] = explicar(motor, sql, params)
    except Exception as exc:  # noqa: BLE001
        salida["segmentos_estadisticas"] = {"error": str(exc).splitlines()[0]}
    return salida


def aplicar_indices(cx) -> dict:
    tiempos = {}
    for sentencia in [s.strip() for s in PROPUESTA_SQL.split(";") if "CREATE INDEX" in s]:
        nombre = re.search(r"IF NOT EXISTS (\w+)", sentencia).group(1)
        cuerpo = "\n".join(x for x in sentencia.splitlines() if not x.strip().startswith("--"))
        t0 = time.perf_counter()
        cx.execute(cuerpo)
        tiempos[nombre] = round(time.perf_counter() - t0, 2)
    for t in ("timbradas_segmentos", "progvehiculos", "timbradas_consolidado", "timbradas_anio",
              "timbradas_segmentos_anio", "timbradas_segmentos_consolidado"):
        cx.execute(f"ANALYZE public.{t}")
    return tiempos


def borrar_indices(cx) -> list[str]:
    nombres = _indices_propuestos()
    for n in nombres:
        cx.execute(f"DROP INDEX CONCURRENTLY IF EXISTS public.{n}")
    return nombres


def volumen(cur) -> dict:
    """Argumento de volumen: filas por día que entran y tamaño que tendrá la tabla con el histórico completo."""
    cur.execute("""SELECT count(*), count(DISTINCT fecha), count(DISTINCT id_viaje),
                          pg_total_relation_size('public.timbradas_segmentos') FROM public.timbradas_segmentos""")
    filas, dias, viajes, bytes_ = cur.fetchone()
    cur.execute("SELECT count(*), min(fechasalida)::date, max(fechasalida)::date FROM public.progvehiculos")
    viajes_total, desde, hasta = cur.fetchone()
    por_viaje = filas / max(1, viajes)
    por_dia = filas / max(1, dias)
    proyectada = por_viaje * viajes_total
    return {"timbradas_segmentos_filas": int(filas), "dias_con_datos": int(dias), "viajes_con_segmentos": int(viajes),
            "filas_por_viaje": round(por_viaje, 1), "filas_por_dia": round(por_dia),
            "tamano_mb": round(bytes_ / 2**20, 1), "progvehiculos_viajes": int(viajes_total),
            "progvehiculos_periodo": f"{desde} a {hasta}",
            "filas_proyectadas_historico_completo": round(proyectada),
            "fraccion_leida_por_ejecucion_diaria": round(por_dia / max(1.0, proyectada), 6)}


def main(argv: list[str] | None = None) -> dict:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--conservar-indices", action="store_true")
    a = p.parse_args(argv)
    from sqlalchemy import create_engine

    from scripts.replica_simular_llegada import candado, conectar

    SALIDA.mkdir(parents=True, exist_ok=True)
    PROPUESTA.write_text(PROPUESTA_SQL, encoding="utf-8")
    motor = create_engine(_url_lector(), pool_size=1, max_overflow=0)
    informe: dict = {"generado_en": datetime.now().astimezone().isoformat(), "rol_medicion": "lector_ia",
                     "rol_indices": "extreme_dba (dueño de la base, §8.3)"}
    dba = conectar("extreme_dba", autocommit=True)
    try:
        with candado(dba):
            with dba.cursor() as cur:
                informe["volumen"] = volumen(cur)
                marcas = {t: marca_de_lectura(cur, t, informe["volumen"]["filas_por_dia"]) for t in TABLAS}
                # escenario de régimen: la ejecución siguiente a una lectura completa (marca = la mayor; nada nuevo)
                marcas_max = {}
                for t in TABLAS:
                    origen, col = MARCA_DE.get(t, (t, "ultima_actualizacion"))
                    cur.execute(f"SELECT max({col}) FROM public.{origen}")  # nosec B608  # identificadores de constantes del script; valores por parámetro  # noqa: S608 - constantes
                    m = cur.fetchone()[0]
                    marcas_max[t] = marcas[t] if m is None else _con_zona(m)
                existentes = _indices_propuestos()
                cur.execute("SELECT indexname FROM pg_indexes WHERE indexname = ANY(%s)", (existentes,))
                informe["indices_previos"] = [r[0] for r in cur.fetchall()]
            informe["antes"] = medir(motor, "antes", marcas)
            informe["antes_sin_novedades"] = medir(motor, "antes sin novedades", marcas_max)
            informe["indices_aplicados_s"] = aplicar_indices(dba)
            informe["despues"] = medir(motor, "después", marcas)
            informe["despues_sin_novedades"] = medir(motor, "después sin novedades", marcas_max)
            if not a.conservar_indices:
                informe["indices_borrados"] = borrar_indices(dba)
                for t in ("timbradas_segmentos", "progvehiculos"):
                    dba.execute(f"ANALYZE public.{t}")
    finally:
        dba.close()
        motor.dispose()
    (SALIDA / "explain_incremental.json").write_text(json.dumps(informe, ensure_ascii=False, indent=1, default=str),
                                                     encoding="utf-8")
    (SALIDA / "explain_incremental.txt").write_text(_texto(informe), encoding="utf-8")
    return informe


def _texto(inf: dict) -> str:
    v = inf["volumen"]
    lineas = [
        "EXPLAIN (ANALYZE, BUFFERS) de las consultas incrementales de la API, como lector_ia (READ ONLY, "
        "statement_timeout, TimeZone America/Bogota)",
        f"Generado: {inf['generado_en']} · índices aplicados por {inf['rol_indices']} y borrados al terminar",
        "", "== Argumento de volumen",
        f"timbradas_segmentos en la réplica: {v['timbradas_segmentos_filas']:,} filas ({v['tamano_mb']} MB), "
        f"{v['viajes_con_segmentos']:,} viajes, {v['filas_por_viaje']} filas por viaje, {v['dias_con_datos']} días.",
        f"progvehiculos: {v['progvehiculos_viajes']:,} viajes ({v['progvehiculos_periodo']}). Con todos los viajes "
        f"segmentados, timbradas_segmentos tendría unos {v['filas_proyectadas_historico_completo']:,} filas.",
        f"Una ejecución diaria lee unas {v['filas_por_dia']:,} filas: fracción "
        f"{v['fraccion_leida_por_ejecucion_diaria']} de la tabla. Sin índice en la marca, cada ejecución recorre "
        "la tabla completa (crece con el histórico); con índice, el costo depende solo de lo que llegó ese día.", "",
        "Escenario A «bloque de llegada»: marca anterior al último bloque de marcas que cubre el volumen de un día",
        "(la carga se selló en pocas transacciones, así que el bloque es mayor que un día). Escenario B «sin "
        "novedades»: la ejecución siguiente (marca = la mayor); es el costo fijo de cada ejecución programada."]
    for titulo, a_, d_ in (("A · bloque de llegada", "antes", "despues"),
                           ("B · sin novedades", "antes_sin_novedades", "despues_sin_novedades")):
        lineas += ["", f"== Resumen {titulo} (ms de ejecución en el servidor · filas · escaneos)",
                   f"{'consulta':34} {'filas':>8} {'antes':>10} {'después':>10}  escaneos antes -> después"]
        for t, antes in inf.get(a_, {}).items():
            despues = inf.get(d_, {}).get(t, {})
            ms_a = str(antes.get("ms_ejecucion", antes.get("error")))
            lineas.append(f"{t:34} {str(antes.get('filas')):>8} {ms_a:>10} "
                          f"{str(despues.get('ms_ejecucion', despues.get('error'))):>10}  "
                          f"{antes.get('escaneos')} -> {despues.get('escaneos')}")
    for fase in ("antes", "despues"):
        lineas += ["", f"== Planes completos ({fase})"]
        for t, r in inf[fase].items():
            lineas += [f"-- {t} (marca {r.get('marca', '-')}): {r.get('ms_ejecucion')} ms, filas={r.get('filas')}, "
                       f"buffers hit={r.get('buffers_hit')} read={r.get('buffers_read')}, "
                       f"descartadas por filtro={r.get('filas_descartadas_por_filtro')}", r.get("texto") or
                       r.get("error", ""), ""]
    return "\n".join(lineas) + "\n"


if __name__ == "__main__":
    r = main()
    print(json.dumps({"volumen": r["volumen"], "indices": r.get("indices_aplicados_s")}, ensure_ascii=False, indent=1))
