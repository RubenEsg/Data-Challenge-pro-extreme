"""Simulador de llegada de datos a la réplica operacional (RF-013, §7.3 pasos 1-2, §9.5, §11.2, §14.2 «llegada de
información nueva»).

Inserta en public.conteo_pasajeros, COMO EXTREME_DBA (el papel de la captura de Extreme; nunca lector_ia ni
escritor_ia), las filas crudas reales de los viajes reservados (muestra_conteo_pasajeros_20230207_r2_r21.parquet,
rutas 2 y 21 del 2023-02-07, fuera de la carga de timbradas_segmentos). Cada INSERT dispara el trigger de Extreme
tg_timbrada_segmento, que llena timbradas_segmentos con su ultimaactualizacion. Después, como la liquidación y el cierre
nocturno de Extreme (que no se entregaron: hallazgo H6), llama fn_insert_timbradas_anio(viaje) por viaje y
fn_consolidar_timbradas_historicas(). Las funciones y el trigger NO se modifican.

Luego (opcional, --ciclo-api) corre la API en modo integrado EN ESTE PROCESO: lee con lector_ia, escribe en
ai_frecuencias con escritor_ia, POST /api/v1/frequency/executions dos veces y muestra que la marca de agua entrega
exactamente las franjas nuevas y luego 0. La carpeta de datos/modelos se copia a un temporal (no toca datos/).

Al terminar RESTAURA la réplica (salvo --conservar): las tablas que tocan las funciones vuelven a su respaldo en
replica_meta y se borran las filas crudas y segmentadas de los viajes simulados, para que la réplica siga igual a la
exportación (tests/replica/test_carga.py).

Uso:
  .venv\\Scripts\\python -m scripts.replica_simular_llegada --viajes 3 --liquidar --consolidar --ciclo-api
  .venv\\Scripts\\python -m scripts.replica_simular_llegada --viajes 1 --filas-max 40 --sin-evidencia --conservar
Solo se conecta a la réplica LOCAL (scripts/replica_comun.py); las claves salen del .env y no se imprimen.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import sys
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import pandas as pd

from scripts import replica_comun as rc

RAIZ = rc.RAIZ
DATOS = Path(os.environ.get("REPLICA_DATOS_DIR") or RAIZ.parents[1] / "datos")
MUESTRA = DATOS / "muestra_conteo_pasajeros_20230207_r2_r21.parquet"
EXPORT_TS = DATOS / "timbradas_segmentos.parquet"
SALIDA = RAIZ / "docs" / "evidencias" / "replica"
CANDADO = 727_001          # pg_advisory_lock compartido con tests/replica: una sola simulación a la vez
VIAJES_SIN_FIN = (5141354, 5141358)   # apto_estadisticas_historicas = TRUE sin fechafin ni fecha_fin_liquidacion

# Tablas que modifican fn_insert_timbradas_anio y fn_consolidar_timbradas_historicas (respaldo y restauración).
TABLAS_FUNCIONES = ("timbradas_anio", "timbradas_anio_trazabilidad", "timbradas_anio_zonas",
                    "timbradas_anio_zonas_trazabilidad", "timbradas_consolidado", "timbradas_consolidado_zonas",
                    "timbradas_segmentos_anio", "timbradas_segmentos_anio_trazabilidad",
                    "timbradas_segmentos_consolidado")
MARCAS = {"timbradas_segmentos": "ultimaactualizacion", "timbradas_anio": "ultima_actualizacion",
          "timbradas_anio_zonas": "ultima_actualizacion", "timbradas_consolidado": "ultima_actualizacion",
          "timbradas_consolidado_zonas": "ultima_actualizacion", "timbradas_segmentos_anio": "ultima_actualizacion",
          "timbradas_segmentos_consolidado": "ultima_actualizacion"}
COLUMNAS_CONSOLIDADO = ("proceso", "id_ruta", "id_dia_semana", "id_estacionalidad", "hora", "hora_inicio", "hora_fin",
                        "subidas", "bajadas", "nro_viajes", "promedio_subidas", "promedio_bajadas")


def _psycopg():
    import psycopg
    return psycopg


def conectar(rol: str = "extreme_dba", **kw):
    url = rc.url_rol(rol)
    if not url:
        raise SystemExit(f"Falta la clave de {rol} en el entorno o en el .env local (ver .env.example).")
    return _psycopg().connect(url, **kw)


@contextmanager
def candado(cx, espera_s: float = 600.0):
    """Serializa simulaciones y pruebas que escriben en la réplica (varias suites pueden correr a la vez)."""
    limite = time.monotonic() + espera_s
    with cx.cursor() as cur:
        while True:
            cur.execute("SELECT pg_try_advisory_lock(%s)", (CANDADO,))
            if cur.fetchone()[0]:
                break
            if time.monotonic() > limite:
                raise TimeoutError("otra simulación tiene el candado de la réplica")
            time.sleep(1.0)
    try:
        yield
    finally:
        with cx.cursor() as cur:
            cur.execute("SELECT pg_advisory_unlock(%s)", (CANDADO,))


# ---------------------------------------------------------------- selección y lectura de la muestra
def elegir_viajes(cur, n: int, ids: list[int] | None = None, incluir_sin_fin: bool = False) -> list[int]:
    if ids:
        return [int(v) for v in ids]
    cur.execute("""SELECT r.idprogramacion FROM replica_meta.viajes_reservados r
                   JOIN public.progvehiculos p USING (idprogramacion)
                   WHERE p.apto_estadisticas_historicas AND (%s OR p.fechafin IS NOT NULL
                         OR p.fecha_fin_liquidacion IS NOT NULL)
                   ORDER BY r.idprogramacion LIMIT %s""", (incluir_sin_fin, n))
    return [int(v[0]) for v in cur.fetchall()]


def filas_muestra(viajes: list[int], filas_max: int | None = None) -> pd.DataFrame:
    import pyarrow.parquet as pq

    tabla = pq.read_table(MUESTRA, filters=[("idprogramacion", "in", list(viajes))])
    d = tabla.to_pandas().sort_values(["idprogramacion", "fecha", "id"]).reset_index(drop=True)
    if filas_max:
        d = d.groupby("idprogramacion", group_keys=False).head(int(filas_max)).reset_index(drop=True)
    return d


def columnas_conteo(cur) -> list[str]:
    cur.execute("""SELECT column_name FROM information_schema.columns
                   WHERE table_schema = 'public' AND table_name = 'conteo_pasajeros' ORDER BY ordinal_position""")
    return [r[0] for r in cur.fetchall()]


# ---------------------------------------------------------------- marcas y conteos
def marcas(cur) -> dict[str, dict]:
    salida = {}
    for tabla, col in MARCAS.items():
        cur.execute(f"SELECT count(*), max({col}) FROM public.{tabla}")  # nosec B608  # identificadores de constantes del script; valores por parámetro  # noqa: S608 - nombres constantes
        n, m = cur.fetchone()
        salida[tabla] = {"filas": int(n), "max_marca": None if m is None else m.isoformat()}
    return salida


def filas_posteriores(cur, t0: datetime) -> dict[str, int]:
    salida = {}
    for tabla, col in MARCAS.items():
        cur.execute(f"SELECT count(*) FROM public.{tabla} WHERE {col} > %s", (t0,))  # nosec B608  # identificadores de constantes del script; valores por parámetro  # noqa: S608
        salida[tabla] = int(cur.fetchone()[0])
    return salida


def huellas_consolidado(cur) -> dict[int, tuple[str, str]]:
    cols = ", ".join(COLUMNAS_CONSOLIDADO)
    cur.execute(f"SELECT id_timbrada_consolidado, md5(ROW({cols})::text), ultima_actualizacion::text "  # nosec B608  # identificadores de constantes del script; valores por parámetro  # noqa: S608
                "FROM public.timbradas_consolidado")
    return {int(i): (h, m) for i, h, m in cur.fetchall()}


# ---------------------------------------------------------------- respaldo y restauración
def respaldar(cx) -> None:
    with cx.cursor() as cur:
        for t in TABLAS_FUNCIONES:
            cur.execute(f"DROP TABLE IF EXISTS replica_meta.respaldo_{t}")
            cur.execute(f"CREATE TABLE replica_meta.respaldo_{t} AS TABLE public.{t}")
        cur.execute("DROP TABLE IF EXISTS replica_meta.respaldo_procesos")
        cur.execute('CREATE TABLE replica_meta.respaldo_procesos AS TABLE public."Procesos"')
    cx.commit()


def restaurar(cx, viajes: list[int], con_respaldo: bool) -> dict:
    """Deja la réplica como estaba: borra lo simulado y devuelve las tablas de las funciones a su respaldo."""
    with cx.cursor() as cur:
        cur.execute("DELETE FROM public.timbradas_segmentos WHERE id_viaje = ANY(%s)", (viajes,))
        borradas_ts = cur.rowcount
        cur.execute("DELETE FROM public.conteo_pasajeros WHERE idprogramacion = ANY(%s)", (viajes,))
        borradas_cp = cur.rowcount
        if con_respaldo:
            cur.execute("TRUNCATE " + ", ".join(f"public.{t}" for t in TABLAS_FUNCIONES))
            for t in TABLAS_FUNCIONES:
                cur.execute(f"INSERT INTO public.{t} SELECT * FROM replica_meta.respaldo_{t}")  # nosec B608  # identificadores de constantes del script; valores por parámetro  # noqa: S608
            cur.execute("""UPDATE public."Procesos" p SET id_estacionalidad = r.id_estacionalidad,
                                  ultima_estacionalidad = r.ultima_estacionalidad, id_diasemana = r.id_diasemana
                             FROM replica_meta.respaldo_procesos r WHERE r.proceso = p.proceso""")
            for t in (*TABLAS_FUNCIONES, "procesos"):
                cur.execute(f"DROP TABLE IF EXISTS replica_meta.respaldo_{t}")
    cx.commit()
    with cx.cursor() as cur:
        cur.execute("ANALYZE public.timbradas_segmentos")
        cur.execute("ANALYZE public.conteo_pasajeros")
    cx.commit()
    return {"timbradas_segmentos_borradas": borradas_ts, "conteo_pasajeros_borradas": borradas_cp,
            "tablas_restauradas": list(TABLAS_FUNCIONES) if con_respaldo else []}


# ---------------------------------------------------------------- llegada, liquidación y cierre
def insertar(cx, filas: pd.DataFrame, columnas: list[str]) -> dict:
    """Un INSERT por fila cruda, en orden de fecha (como la captura); una transacción por viaje."""
    cols = [c for c in columnas if c in filas.columns]
    sql = f"INSERT INTO public.conteo_pasajeros ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))})"  # nosec B608  # identificadores de constantes del script; valores por parámetro
    t0 = time.perf_counter()
    por_viaje = {}
    for viaje, grupo in filas.groupby("idprogramacion", sort=True):
        tv = time.perf_counter()
        valores = [tuple(None if pd.isna(v) else (v.item() if hasattr(v, "item") else v) for v in fila)
                   for fila in grupo[cols].itertuples(index=False, name=None)]
        with cx.cursor() as cur:
            cur.executemany(sql, valores)
        cx.commit()
        por_viaje[int(viaje)] = {"filas": len(grupo), "segundos": round(time.perf_counter() - tv, 2)}
    total = time.perf_counter() - t0
    return {"filas": len(filas), "segundos": round(total, 2),
            "ms_por_fila": round(1000 * total / max(1, len(filas)), 1), "por_viaje": por_viaje}


def liquidar(cx, viajes: list[int]) -> list[dict]:
    avisos: list[str] = []
    cx.add_notice_handler(lambda d: avisos.append(d.message_primary))
    salida = []
    with cx.cursor() as cur:
        cur.execute("SET client_min_messages = notice")
        for v in viajes:
            avisos.clear()
            t0 = time.perf_counter()
            cur.execute("SELECT public.fn_insert_timbradas_anio(%s)", (v,))
            ok = bool(cur.fetchone()[0])
            cx.commit()
            fila = {"viaje": v, "resultado": ok, "segundos": round(time.perf_counter() - t0, 3)}
            if not ok:
                fila["avisos"] = list(avisos[:8])
            salida.append(fila)
        cur.execute("SET client_min_messages = warning")
    cx.commit()
    return salida


def consolidar(cx) -> dict:
    with cx.cursor() as cur:
        antes = huellas_consolidado(cur)
        t0 = time.perf_counter()
        cur.execute("SELECT public.fn_consolidar_timbradas_historicas()")
        ok = bool(cur.fetchone()[0])
        segundos = time.perf_counter() - t0
        cx.commit()
        despues = huellas_consolidado(cur)
    resellladas = sum(1 for i, (_, m) in despues.items() if i in antes and antes[i][1] != m)
    cambiadas = sum(1 for i, (h, _) in despues.items() if i in antes and antes[i][0] != h)
    return {"resultado": ok, "segundos": round(segundos, 3), "filas": len(despues),
            "reselladas_misma_huella": resellladas - cambiadas, "cambiadas_contenido": cambiadas,
            "nuevas": sum(1 for i in despues if i not in antes)}


def equivalencia(cur, viajes: list[int]) -> dict:
    """Σ subidas/bajadas por (id_segmento, id_viaje) del trigger frente a la exportación de timbradas_segmentos."""
    if not EXPORT_TS.exists():
        return {"nota": f"no está {EXPORT_TS.name}"}
    import pyarrow.parquet as pq

    ex = pq.read_table(EXPORT_TS, columns=["id_segmento", "id_viaje", "subidas", "bajadas"],
                       filters=[("id_viaje", "in", list(viajes))]).to_pandas()
    ex = ex.groupby(["id_segmento", "id_viaje"], as_index=False)[["subidas", "bajadas"]].sum()
    cur.execute("""SELECT id_segmento, id_viaje, sum(subidas) AS subidas, sum(bajadas) AS bajadas
                   FROM public.timbradas_segmentos WHERE id_viaje = ANY(%s) GROUP BY 1, 2""", (viajes,))
    tr = pd.DataFrame(cur.fetchall(), columns=["id_segmento", "id_viaje", "subidas", "bajadas"])
    m = ex.merge(tr, on=["id_segmento", "id_viaje"], how="outer", suffixes=("_export", "_trigger"), indicator=True)
    ambos = m[m["_merge"] == "both"]
    iguales = ((ambos["subidas_export"] == ambos["subidas_trigger"])
               & (ambos["bajadas_export"] == ambos["bajadas_trigger"])).sum()
    return {"pares_exportacion": len(ex), "pares_trigger": len(tr), "pares_comunes": len(ambos),
            "pares_iguales": int(iguales), "porcentaje_iguales": round(100 * iguales / max(1, len(ambos)), 2),
            "subidas_export": int(ex["subidas"].sum()), "subidas_trigger": int(tr["subidas"].sum() if len(tr) else 0),
            "bajadas_export": int(ex["bajadas"].sum()), "bajadas_trigger": int(tr["bajadas"].sum() if len(tr) else 0)}


# ---------------------------------------------------------------- lecturas como lector_ia (lo que hace la API)
def lecturas_fuente(t0: datetime, tablas=("demanda_segmentos", "timbradas_segmentos", "timbradas_anio",
                                          "timbradas_consolidado", "timbradas_segmentos_anio",
                                          "timbradas_segmentos_consolidado")) -> dict:
    from app.servicios.fuentes import FuentePostgresSoloLectura

    url = rc.url_rol("lector_ia").replace("postgresql://", "postgresql+psycopg://")
    salida = {}
    for tabla in tablas:
        f = FuentePostgresSoloLectura(url=url, tabla=tabla, solape_min=15)
        d1, m1 = f.leer_incremental(t0)
        r1, estado = dict(f.resumen_lectura), f.estado_incremental
        d2, _ = f.leer_incremental(m1, estado_previo=estado)
        r2 = dict(f.resumen_lectura)
        salida[tabla] = {"primera": {k: r1.get(k) for k in ("leidas", "entregadas", "nuevas", "tardias", "modificadas",
                                                          "repetidas_solape", "marca_nueva")},
                         "segunda": {k: r2.get(k) for k in ("leidas", "entregadas", "repetidas_solape")}}
        f._engine().dispose()
    return salida


def reiniciar_esquema_integrado() -> dict:
    """Vacía ai_frecuencias en la réplica COMO ESCRITOR_IA (su dueño) sin borrar el esquema: escritor_ia no podría
    volver a crearlo (no tiene CREATE en la base). Deja la demostración reproducible desde la marca inicial."""
    with conectar("escritor_ia", autocommit=True) as cx, cx.cursor() as cur:
        cur.execute("""SELECT format('DROP TABLE IF EXISTS %I.%I CASCADE', schemaname, tablename)
                       FROM pg_tables WHERE schemaname = 'ai_frecuencias'""")
        sentencias = [r[0] for r in cur.fetchall()]
        cur.execute("""SELECT format('DROP FUNCTION IF EXISTS %s CASCADE', p.oid::regprocedure)
                       FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
                       WHERE n.nspname = 'ai_frecuencias'""")
        sentencias += [r[0] for r in cur.fetchall()]
        for s in sentencias:
            cur.execute(s)
        return {"objetos_borrados": len(sentencias)}


def migraciones_aplicadas(salida: str | None) -> list[str]:
    """Todas las líneas «Running upgrade» (y los errores) de alembic upgrade head: el informe dice cuántas migraciones
    aplicó y cuáles (antes se guardaban solo las últimas seis y el informe decía «6 migraciones» con más)."""
    return [x for x in (salida or "").strip().splitlines() if "Running upgrade" in x or "Error" in x]


class ApiIntegrada:
    """La API en modo integrado dentro de este proceso: DATABASE_URL = escritor_ia y FUENTE_DATABASE_URL = lector_ia
    en la MISMA base de la réplica; datos y modelos en una copia temporal (no se toca datos/ del repositorio)."""

    def __init__(self):
        self.temporal = Path(tempfile.mkdtemp(prefix="sobusa_integrado_"))
        shutil.copytree(RAIZ / "datos", self.temporal / "datos")
        self.clave = secrets.token_urlsafe(24)
        escritor = rc.url_rol("escritor_ia").replace("postgresql://", "postgresql+psycopg://")
        lector = rc.url_rol("lector_ia").replace("postgresql://", "postgresql+psycopg://")
        os.environ.update({
            "DATABASE_URL": escritor, "FUENTE": "postgres", "FUENTE_DATABASE_URL": lector,
            "FUENTE_TABLA": "demanda_segmentos", "FUENTE_PROCESO": "sobusa", "FUENTE_SOLAPE_MIN": "15",
            "FUENTE_STATEMENT_TIMEOUT_MS": "30000",
            "DATA_DIR": str(self.temporal / "datos"), "MODELOS_DIR": str(self.temporal / "datos" / "modelos"),
            "REANUDAR_EJECUCIONES": "false", "PLANIFICADOR_HABILITADO": "false", "AUTH_HABILITADA": "true",
            "API_KEY_ADMIN": self.clave, "API_KEYS": "", "ENTORNO": "pruebas", "NOTIFICACIONES_CANALES": "",
            "MAX_REINTENTOS": "1"})
        self.preparacion = {"reinicio": reiniciar_esquema_integrado()}
        import subprocess

        t0 = time.perf_counter()
        mig = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=RAIZ,  # noqa: S603
                             capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300,
                             check=False, env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        self.preparacion.update(alembic_upgrade_head_como_escritor_ia=mig.returncode == 0,
                                alembic_segundos=round(time.perf_counter() - t0, 2),
                                alembic_salida=migraciones_aplicadas(mig.stderr or mig.stdout))
        if mig.returncode != 0:
            raise RuntimeError("alembic upgrade head falló como escritor_ia: " + (mig.stderr or "")[-800:])
        from fastapi.testclient import TestClient

        from app.main import app

        self._cm = TestClient(app)
        self.cliente = self._cm.__enter__()

    def ejecutar(self, etiqueta: str, cuerpo: dict | None = None) -> dict:
        cab = {"X-API-Key": self.clave}
        t0 = time.perf_counter()
        r = self.cliente.post("/api/v1/frequency/executions", json=cuerpo or {}, headers=cab)
        datos = r.json()
        eid = datos.get("execution_id") or datos.get("id")
        e = self.cliente.get(f"/api/v1/frequency/executions/{eid}", headers=cab).json() if eid else datos
        met = e.get("metricas") or {}
        lectura = dict(met.get("lectura") or {})
        return {"corrida": etiqueta, "http": r.status_code, "segundos": round(time.perf_counter() - t0, 2),
                "estado": e.get("estado"), "filas_leidas": e.get("filas_leidas"),
                "filas_validas": e.get("filas_validas"), "marca_agua_anterior": e.get("marca_agua_anterior"),
                "marca_agua_nueva": e.get("marca_agua_nueva"), "lectura": lectura,
                "incorporadas_historico": met.get("incorporadas_historico"), "predicciones": met.get("predicciones"),
                "recomendaciones": met.get("recomendaciones"), "alertas_nuevas": met.get("alertas_nuevas"),
                "nota": met.get("nota"), "errores_calidad": met.get("errores_calidad"),
                "fallos": (met.get("fallos") or [])[:3], "mensaje": e.get("mensaje")}

    def cerrar(self) -> None:
        try:
            self._cm.__exit__(None, None, None)
        finally:
            shutil.rmtree(self.temporal, ignore_errors=True)


def escritura_ai_frecuencias(cx) -> dict:
    """Prueba de §8.1/§11.3 tras el ciclo: resultados en ai_frecuencias y nada nuevo fuera de ese esquema."""
    with cx.cursor() as cur:
        cur.execute("""SELECT n.nspname, count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                       WHERE c.relkind IN ('r', 'p') AND pg_get_userbyid(c.relowner) = 'escritor_ia'
                       GROUP BY 1 ORDER BY 1""")
        return {esquema: int(n) for esquema, n in cur.fetchall()}


def main(argv: list[str] | None = None) -> dict:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--viajes", type=int, default=3)
    p.add_argument("--ids", type=int, nargs="*")
    p.add_argument("--filas-max", type=int, default=None, help="filas crudas por viaje (por omisión, todas)")
    p.add_argument("--incluir-sin-fin", action="store_true", help="incluir viajes aptos sin fechafin (H11)")
    p.add_argument("--liquidar", action="store_true", help="fn_insert_timbradas_anio por viaje")
    p.add_argument("--consolidar", action="store_true", help="fn_consolidar_timbradas_historicas()")
    p.add_argument("--ciclo-api", action="store_true", help="POST /frequency/executions dos veces (modo integrado)")
    p.add_argument("--conservar", action="store_true", help="no restaurar la réplica al terminar")
    p.add_argument("--sin-evidencia", action="store_true")
    p.add_argument("--salida", type=Path, default=None, help="además, guarda el informe JSON en esta ruta")
    a = p.parse_args(argv)
    if not MUESTRA.exists():
        raise SystemExit(f"No está la muestra {MUESTRA}")
    informe: dict = {"inicio": datetime.now().astimezone().isoformat(), "rol_escritura": "extreme_dba"}
    cx = conectar()
    viajes: list[int] = []
    respaldo = False
    api = None
    try:
        with candado(cx):
            if a.ciclo_api:
                # 1.ª ejecución ANTES de la llegada: carga inicial desde la marca de 1970 (todo el histórico segmentado)
                api = ApiIntegrada()
                informe["ciclo_api"] = {"preparacion": api.preparacion,
                                        "corridas": [api.ejecutar("1_carga_inicial_antes_de_la_llegada")]}
            with cx.cursor() as cur:
                cur.execute("SET TimeZone = 'America/Bogota'")
                viajes = elegir_viajes(cur, a.viajes, a.ids, a.incluir_sin_fin)
                cur.execute("SELECT count(*) FROM public.conteo_pasajeros WHERE idprogramacion = ANY(%s)", (viajes,))
                if cur.fetchone()[0]:
                    raise SystemExit("Esos viajes ya tienen filas crudas: restaure la réplica antes (sin --conservar).")
                cols = columnas_conteo(cur)
                cur.execute("SELECT now()")
                t0 = cur.fetchone()[0]
                informe.update(viajes=viajes, t0=t0.isoformat(), antes=marcas(cur))
            cx.commit()
            if a.liquidar or a.consolidar:
                respaldar(cx)
                respaldo = True
            filas = filas_muestra(viajes, a.filas_max)
            informe["llegada"] = insertar(cx, filas, cols)
            if a.liquidar:
                informe["liquidacion"] = liquidar(cx, viajes)
            if a.consolidar:
                # H7 visto por el lector: huellas de timbradas_consolidado ANTES del cierre y lectura DESPUÉS con ellas
                from app.servicios.fuentes import FuentePostgresSoloLectura

                url_l = rc.url_rol("lector_ia").replace("postgresql://", "postgresql+psycopg://")
                previa = FuentePostgresSoloLectura(url=url_l, tabla="timbradas_consolidado", solape_min=15)
                _, marca_previa = previa.leer_incremental(None)
                estado_previo = previa.estado_incremental
                informe["consolidacion"] = consolidar(cx)
                _, _ = previa.leer_incremental(marca_previa, estado_previo=estado_previo)
                informe["h7_resellado_visto_por_lector_ia"] = {
                    k: previa.resumen_lectura.get(k) for k in ("leidas", "entregadas", "modificadas", "nuevas",
                                                               "repetidas_solape", "marca_anterior", "marca_nueva")}
                previa._engine().dispose()
            with cx.cursor() as cur:
                informe["despues"] = marcas(cur)
                informe["filas_con_marca_posterior_a_t0"] = filas_posteriores(cur, t0)
                informe["equivalencia_trigger_vs_exportacion"] = equivalencia(cur, viajes)
            cx.commit()
            informe["lecturas_lector_ia"] = lecturas_fuente(t0)
            if api is not None:
                # 2.ª: solo las franjas de los viajes que llegaron; 3.ª: nada nuevo (0 filas, sin reprocesar)
                informe["ciclo_api"]["corridas"].append(api.ejecutar("2_despues_de_la_llegada"))
                informe["ciclo_api"]["corridas"].append(api.ejecutar("3_sin_datos_nuevos"))
                informe["tablas_de_escritor_ia_por_esquema"] = escritura_ai_frecuencias(cx)
            if not a.conservar:
                informe["restauracion"] = restaurar(cx, viajes, respaldo)
                with cx.cursor() as cur:
                    informe["tras_restaurar"] = marcas(cur)
                cx.commit()
    except BaseException:
        cx.rollback()
        if viajes and not a.conservar:
            restaurar(cx, viajes, respaldo)
        raise
    finally:
        if api is not None:
            api.cerrar()
        cx.close()
    if a.salida is not None:
        a.salida.write_text(json.dumps(informe, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    if not a.sin_evidencia:
        SALIDA.mkdir(parents=True, exist_ok=True)
        (SALIDA / "replica_llegada.json").write_text(json.dumps(informe, ensure_ascii=False, indent=1, default=str),
                                                     encoding="utf-8")
        (SALIDA / "replica_llegada.txt").write_text(texto_informe(informe), encoding="utf-8")
    return informe


def _corrida(c: dict) -> str:
    lec = c.get("lectura") or {}
    texto = (f"   {c.get('corrida')}: HTTP {c.get('http')}, estado {c.get('estado')}, "
             f"filas_leidas={c.get('filas_leidas')} "
             f"(leidas en la ventana {lec.get('leidas')}, repetidas {lec.get('repetidas_solape')}, nuevas "
             f"{lec.get('nuevas')}), predicciones={c.get('predicciones')}, recomendaciones={c.get('recomendaciones')}, "
             f"errores de calidad {c.get('errores_calidad') or {}}, marca {c.get('marca_agua_anterior')} -> "
             f"{c.get('marca_agua_nueva')}, {c.get('segundos')} s")
    return texto + (f" · nota: {c['nota']}" if c.get("nota") else "")


def texto_informe(r: dict) -> str:
    """Versión legible del informe (docs/evidencias/replica/replica_llegada.txt)."""
    ll = r.get("llegada") or {}
    eq = r.get("equivalencia_trigger_vs_exportacion") or {}
    filas = ["Llegada de datos por el trigger de Extreme y lectura incremental (scripts/replica_simular_llegada.py)",
             f"Inicio: {r.get('inicio')} · escribe: {r.get('rol_escritura')} (la captura) · lee: lector_ia · "
             "resultados: escritor_ia",
             f"Viajes reservados simulados: {r.get('viajes')}", "",
             "== 1. Llegada (un INSERT por fila cruda, una transacción por viaje)",
             f"   {ll.get('filas')} filas crudas en {ll.get('segundos')} s ({ll.get('ms_por_fila')} ms por fila): "
             f"{ll.get('por_viaje')}",
             f"   filas con marca posterior a t0: {r.get('filas_con_marca_posterior_a_t0')}",
             f"   equivalencia trigger vs exportación: {eq.get('pares_iguales')}/{eq.get('pares_comunes')} pares "
             f"(segmento, viaje) iguales ({eq.get('porcentaje_iguales')} %); Σ subidas {eq.get('subidas_trigger')} = "
             f"{eq.get('subidas_export')}; Σ bajadas {eq.get('bajadas_trigger')} = {eq.get('bajadas_export')}", ""]
    if r.get("liquidacion"):
        filas.append("== 2. Liquidación fn_insert_timbradas_anio (por viaje)")
        filas += [f"   viaje {x.get('viaje')}: {x.get('resultado')} en {x.get('segundos')} s {x.get('error') or ''}"
                  for x in r["liquidacion"]]
        filas.append("")
    if r.get("consolidacion"):
        c = r["consolidacion"]
        filas += ["== 3. Cierre fn_consolidar_timbradas_historicas()",
                  f"   resultado {c.get('resultado')} en {c.get('segundos')} s; filas {c.get('filas')}; cambiadas de "
                  f"contenido {c.get('cambiadas_contenido')}; reselladas con la misma huella "
                  f"{c.get('reselladas_misma_huella')}; nuevas {c.get('nuevas')}",
                  f"   visto por lector_ia con huella: {r.get('h7_resellado_visto_por_lector_ia')}", ""]
    filas.append("== 4. Lecturas incrementales como lector_ia desde t0 (primera) y con el estado de huellas (segunda)")
    for tabla, v in (r.get("lecturas_lector_ia") or {}).items():
        p1, p2 = v.get("primera") or {}, v.get("segunda") or {}
        filas.append(f"   {tabla:<34} primera: leidas={p1.get('leidas')} entregadas={p1.get('entregadas')} · "
                     f"segunda: leidas={p2.get('leidas')} entregadas={p2.get('entregadas')} "
                     f"repetidas={p2.get('repetidas_solape')}")
    filas.append("")
    api = r.get("ciclo_api") or {}
    if api:
        prep = api.get("preparacion") or {}
        aplicadas = sum("Running upgrade" in x for x in prep.get("alembic_salida") or [])
        filas += ["== 5. La API en modo integrado (DATABASE_URL = escritor_ia, FUENTE_DATABASE_URL = lector_ia, misma "
                  "base)",
                  f"   alembic upgrade head como escritor_ia: {prep.get('alembic_upgrade_head_como_escritor_ia')} en "
                  f"{prep.get('alembic_segundos')} s ({aplicadas} migraciones)"]
        filas += [f"      {x.split('Running upgrade', 1)[-1].strip()}" for x in prep.get("alembic_salida") or []]
        filas += [_corrida(c) for c in api.get("corridas") or []]
        filas += [f"   tablas de escritor_ia por esquema: {r.get('tablas_de_escritor_ia_por_esquema')}", ""]
    filas += ["== 6. Restauración (la réplica vuelve al estado cargado)", f"   {r.get('restauracion')}",
              f"   antes == después de restaurar: {r.get('tras_restaurar') == r.get('antes')}", ""]
    return chr(10).join(filas)


if __name__ == "__main__":
    # la consola de Windows (cp1252) no codifica todo el texto del informe: la salida va en UTF-8
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    resultado = main()
    print(json.dumps({k: resultado.get(k) for k in ("viajes", "llegada", "liquidacion", "consolidacion",
                                                     "filas_con_marca_posterior_a_t0", "lecturas_lector_ia",
                                                     "ciclo_api", "restauracion")},
                     ensure_ascii=False, indent=1, default=str)[:20000])
