"""Los 8 scripts de Extreme corren SIN MODIFICAR en la réplica; las correcciones (E1, E2, H1) van aparte y cada
una tiene una prueba que muestra el fallo sin ella."""
from __future__ import annotations

import hashlib
import re

import psycopg
import pytest

from scripts import replica_comun as rc
from tests.replica.conftest import url_base

EXTREME = rc.RAIZ / "replica" / "extreme"
ORIGINALES = rc.RAIZ.parents[1] / "insumos_sobusa" / "scripts_extreme"
SCRIPTS = ["1. tablas.sql", "2. funcion para segmentar ruta.sql", "3. fn_insert_timbradas_anio.sql",
           "4. fn_consolidar_timbradas_historicas.sql", "5. cargue inicial timbradas_segmentos.sql",
           "6. cargue inicial timbradas_segmentos_anio.sql", "7. trigger de conteo.sql",
           "99. prueba de segmentacion.sql"]
TABLAS_SCRIPT1 = ["rutas_segmentos_porcion", "rutas_segmentos", "timbradas_segmentos", "timbradas_segmentos_anio",
                  "timbradas_segmentos_anio_trazabilidad", "timbradas_segmentos_consolidado"]


def _sha(ruta) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def _sumas() -> dict[str, str]:
    sumas = {}
    for linea in (EXTREME / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        h, nombre = linea.split(" ", 1)
        sumas[nombre.lstrip(" *")] = h
    return sumas


def test_hash_scripts_identicos():
    """replica/extreme = SHA256SUMS = originales entregados por Extreme (byte a byte, con sus CRLF)."""
    sumas = _sumas()
    assert sorted(sumas) == sorted(SCRIPTS)
    assert sorted(p.name for p in EXTREME.glob("*.sql")) == sorted(SCRIPTS)
    for nombre in SCRIPTS:
        assert _sha(EXTREME / nombre) == sumas[nombre], nombre
        if ORIGINALES.exists():
            assert (EXTREME / nombre).read_bytes() == (ORIGINALES / nombre).read_bytes(), nombre


def test_init_registrado(admin):
    """Cada paso de la inicialización quedó en replica_meta.paso con los errores esperados y el sha256 del archivo."""
    with admin.cursor() as cur:
        cur.execute("""SELECT paso, archivo, sha256, errores, errores_esperados, salida FROM replica_meta.paso
                       WHERE paso NOT LIKE 'carga%' AND paso NOT LIKE 'post-carga%' ORDER BY n""")
        pasos = cur.fetchall()
    assert [p[0] for p in pasos] == ["E1", "1", "E2", "2", "3", "4", "7", "99", "5", "6"]
    sumas = _sumas()
    for paso, archivo, sha, errores, esperados, _ in pasos:
        assert errores == esperados, paso
        if archivo.startswith("/extreme/"):
            assert sha == sumas[archivo.removeprefix("/extreme/")], archivo
    script1 = next(p for p in pasos if p[0] == "1")
    assert script1[3] == 1
    assert 'tablas.sql:38: ERROR:  syntax error at or near ";"' in script1[5]


def test_objetos_extreme(admin):
    with admin.cursor() as cur:
        cur.execute("""SELECT proname FROM pg_proc WHERE pronamespace = 'public'::regnamespace
                       AND proname IN ('fn_segmentar_ruta', 'fn_insert_timbradas_anio',
                                       'fn_consolidar_timbradas_historicas', 'fn_tg_timbrada_segmento')""")
        assert len(cur.fetchall()) == 4
        cur.execute("""SELECT t.tgrelid::regclass::text, t.tgenabled, p.proname FROM pg_trigger t
                       JOIN pg_proc p ON p.oid = t.tgfoid WHERE t.tgname = 'tg_timbrada_segmento'""")
        assert cur.fetchone() == ("conteo_pasajeros", "O", "fn_tg_timbrada_segmento")
        cur.execute("SELECT relname FROM pg_class WHERE relnamespace = 'public'::regnamespace AND relkind = 'r'")
        tablas = {r[0] for r in cur.fetchall()}
        assert set(TABLAS_SCRIPT1) | {"rutas_segmentos_config"} <= tablas
        cur.execute("""SELECT column_name FROM information_schema.columns
                       WHERE table_name = 'rutas_segmentos_config' AND column_name = 'activo'""")
        assert cur.fetchone() is not None


def _errores(salida: str) -> list[str]:
    return [linea for linea in salida.splitlines() if "ERROR:" in linea]


def _tablas(nombre_base: str) -> set[str]:
    with psycopg.connect(url_base(nombre_base)) as cx, cx.cursor() as cur:
        cur.execute("SELECT relname FROM pg_class WHERE relnamespace = 'public'::regnamespace AND relkind = 'r'")
        return {r[0] for r in cur.fetchall()}


def test_script1_sin_errata_falla(base_desechable):
    """Sin E1 el script 1 deja 1 error de sintaxis (línea 38) y 5 en cascada; solo crea rutas_segmentos_porcion."""
    base = base_desechable()
    r = rc.psql(base, "-v", "ON_ERROR_STOP=0", "-f", "/extreme/1. tablas.sql")
    errores = _errores(r.stdout + r.stderr)
    assert len(errores) == 6, errores
    assert re.search(r'tablas\.sql:38: ERROR:  syntax error at or near ";"', errores[0])
    assert sum("does not exist" in e for e in errores) == 5
    creadas = _tablas(base) & (set(TABLAS_SCRIPT1) | {"rutas_segmentos_config"})
    assert creadas == {"rutas_segmentos_porcion"}


def test_script1_con_E1(base_desechable):
    """Con E1 antes, el mismo script 1 (sin cambios) deja solo el error esperado y crea sus otras 6 tablas."""
    base = base_desechable()
    r = rc.psql(base, "-v", "ON_ERROR_STOP=1", "-f", "/errata/E1_rutas_segmentos_config.sql")
    assert r.returncode == 0, r.stderr
    r = rc.psql(base, "-v", "ON_ERROR_STOP=0", "-f", "/extreme/1. tablas.sql")
    salida = r.stdout + r.stderr
    assert len(_errores(salida)) == 1
    assert salida.count("CREATE TABLE") == 6
    assert set(TABLAS_SCRIPT1) | {"rutas_segmentos_config"} <= _tablas(base)


def _base_con_trigger(base_desechable, con_e2: bool) -> str:
    base = base_desechable()
    pasos = ["/errata/E1_rutas_segmentos_config.sql", "/extreme/1. tablas.sql"]
    if con_e2:
        pasos.append("/errata/E2_unique_timbradas_segmentos.sql")
    pasos.append("/extreme/7. trigger de conteo.sql")
    for archivo in pasos:
        stop = "0" if archivo.endswith("1. tablas.sql") else "1"
        r = rc.psql(base, "-q", "-v", f"ON_ERROR_STOP={stop}", "-f", archivo)
        assert r.returncode == 0, r.stderr
    with psycopg.connect(url_base(base), autocommit=True) as cx, cx.cursor() as cur:
        cur.execute("INSERT INTO rutas (idruta, proceso, idrutageo) VALUES (2, 'sobusa', 3)")
        cur.execute("INSERT INTO progvehiculos (idprogramacion, idruta, proceso) VALUES (1, 2, 'sobusa')")
        cur.execute("""INSERT INTO rutas_segmentos_config (idruta, idrutageo, tipo_agrupacion, "tamaño_segmento_m")
                       VALUES (2, 3, 'distancia', 500) RETURNING id""")
        idc = cur.fetchone()[0]
        cur.execute("""INSERT INTO rutas_segmentos (id_config, idruta, idrutageo, nro_segmento, activo, porciones_ids,
                                                    longitud_m, geom_segmento)
                       VALUES (%s, 2, 3, 1, true, '[]', 1096.0,
                               'SRID=4326;LINESTRING(-74.80 10.98, -74.79 10.98)')""", (idc,))
    return base


INSERT_CONTEO = """INSERT INTO conteo_pasajeros (id, fecha, idprogramacion, latitud, longitud, cantidad_subida,
                   cantidad_bajada, acumulada_subida, acumulada_bajada)
                   VALUES (%s, %s, 1, 10.98, -74.795, %s, 0, %s, 0)"""


def test_E2_sin_errata_pierde_filas(base_desechable):
    """Con la llave del script 1, un viaje que pasa por el mismo segmento en dos bloques de 15 min pierde la 2.ª fila
    cruda: el INSERT del trigger viola UNIQUE (id_segmento, id_viaje) y aborta también el INSERT en conteo_pasajeros."""
    base = _base_con_trigger(base_desechable, con_e2=False)
    with psycopg.connect(url_base(base), autocommit=True) as cx, cx.cursor() as cur:
        cur.execute(INSERT_CONTEO, (1, "2023-02-07 06:05:00", 3, 3))
        with pytest.raises(psycopg.errors.UniqueViolation) as exc:
            cur.execute(INSERT_CONTEO, (2, "2023-02-07 06:20:00", 2, 5))
        assert exc.value.diag.constraint_name == "timbradas_segmentos_id_segmento_id_viaje_key"
        cur.execute("SELECT (SELECT count(*) FROM conteo_pasajeros), (SELECT count(*) FROM timbradas_segmentos)")
        assert cur.fetchone() == (1, 1)


def test_E2_con_errata_conserva_filas(base_desechable):
    base = _base_con_trigger(base_desechable, con_e2=True)
    with psycopg.connect(url_base(base), autocommit=True) as cx, cx.cursor() as cur:
        cur.execute(INSERT_CONTEO, (1, "2023-02-07 06:05:00", 3, 3))
        cur.execute(INSERT_CONTEO, (2, "2023-02-07 06:20:00", 2, 5))
        cur.execute("SELECT (SELECT count(*) FROM conteo_pasajeros), count(*), sum(subidas), "
                    "array_agg(hora_inicio::text ORDER BY hora_inicio) FROM timbradas_segmentos")
        assert cur.fetchone() == (2, 2, 5, ["06:00:00", "06:15:00"])


def test_H1_sin_armonizar_liquidacion_falla(cargada):
    """Sin H1 fn_insert_timbradas_anio devuelve FALSE para un viaje de Sobusa (no hay estacionalidad del proceso);
    con H1 el mismo viaje se liquida. Todo en transacciones que se deshacen: la réplica no cambia."""
    with psycopg.connect(url_base("operacional")) as cx, cx.cursor() as cur:
        cur.execute("SET client_min_messages = warning")
        cur.execute("""SELECT r.idprogramacion FROM replica_meta.viajes_reservados r
                       JOIN public.progvehiculos p USING (idprogramacion)
                       WHERE p.apto_estadisticas_historicas ORDER BY 1 LIMIT 10""")
        viajes = [v[0] for v in cur.fetchall()]
        cx.rollback()
        assert viajes, "no hay viajes reservados aptos para estadísticas"
        elegido = None
        for viaje in viajes:
            cur.execute("SELECT public.fn_insert_timbradas_anio(%s)", (viaje,))
            ok = cur.fetchone()[0]
            cx.rollback()
            if ok:
                elegido = viaje
                break
        assert elegido is not None, "ningún viaje se liquidó con H1"
        cur.execute("UPDATE public.estacionalidades_anio SET proceso = 'cootransoriente'")  # deshace H1
        cur.execute("SELECT public.fn_insert_timbradas_anio(%s)", (elegido,))
        assert cur.fetchone()[0] is False
        cx.rollback()
        cur.execute("SELECT count(*) FROM public.estacionalidades_anio WHERE proceso = 'sobusa'")
        assert cur.fetchone()[0] == 231
