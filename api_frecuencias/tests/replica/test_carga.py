"""Réplica cargada desde las exportaciones Parquet: conteos, ids originales, secuencias, geometría, integridad."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from scripts import replica_comun as rc

# las exportaciones del reto con que se cargó la réplica: REPLICA_DATOS_DIR (la misma regla que
# scripts/replica_cargar.py; p. ej. desde un worktree, que no tiene datos/) o la carpeta datos/ del proyecto
DATOS = Path(os.environ.get("REPLICA_DATOS_DIR") or rc.RAIZ.parents[1] / "datos")


def _exportacion() -> dict:
    archivo = DATOS / "_exportacion.json"
    return json.loads(archivo.read_text(encoding="utf-8")) if archivo.exists() else {}


def test_conteos_igual_exportacion(cargada):
    """Cada tabla tiene las filas exportadas (timbradas_segmentos menos las de los viajes reservados)."""
    exportacion = _exportacion()
    with cargada.cursor() as cur:
        cur.execute("SELECT tabla, filas, filas_exportadas, excluidas FROM replica_meta.carga ORDER BY tabla")
        filas = cur.fetchall()
        assert len(filas) == 15
        for tabla, cargadas, exportadas, excluidas in filas:
            cur.execute(f'SELECT count(*) FROM public."{tabla}"')
            assert cur.fetchone()[0] == cargadas, tabla
            assert cargadas + excluidas == exportadas, tabla
            if exportacion:
                assert exportadas == exportacion[tabla]["filas_exportadas"] == exportacion[tabla]["filas_en_servidor"]
        total = sum(f[1] for f in filas)
    assert total > 3_000_000  # RNF-003: más de 100.000 registros sobre PostgreSQL real


def test_viajes_reservados_fuera_de_timbradas_segmentos(cargada):
    with cargada.cursor() as cur:
        cur.execute("""SELECT count(*), sum(filas_crudas), sum(filas_timbradas_segmentos_excluidas)
                       FROM replica_meta.viajes_reservados""")
        viajes, crudas, excluidas = cur.fetchone()
        assert (viajes, crudas) == (265, 93_091)
        cur.execute("SELECT excluidas FROM replica_meta.carga WHERE tabla = 'timbradas_segmentos'")
        assert cur.fetchone()[0] == excluidas == 25_915
        cur.execute("""SELECT count(*) FROM public.timbradas_segmentos t
                       WHERE t.id_viaje IN (SELECT idprogramacion FROM replica_meta.viajes_reservados)""")
        assert cur.fetchone()[0] == 0
        # los viajes reservados sí están en progvehiculos (el trigger los necesita) y conteo_pasajeros empieza vacía
        cur.execute("""SELECT count(*) FROM public.progvehiculos
                       WHERE idprogramacion IN (SELECT idprogramacion FROM replica_meta.viajes_reservados)""")
        assert cur.fetchone()[0] == 265


def test_rutasgeograficas_longitud(cargada):
    """La línea reconstruida de cada ruta mide lo mismo que la suma de sus segmentos exportados (|Δ| < 0,1 m)."""
    with cargada.cursor() as cur:
        cur.execute("""SELECT r.idruta, ST_GeometryType(g.geom), ST_Length(g.geom::geography),
                              (SELECT sum(s.longitud_m) FROM public.rutas_segmentos s
                               WHERE s.idruta = r.idruta AND s.idrutageo = r.idrutageo AND s.activo)
                       FROM public.rutas r JOIN public.rutasgeograficas g ON g.idruta = r.idrutageo ORDER BY 1""")
        filas = cur.fetchall()
    assert [f[0] for f in filas] == [2, 16, 21]
    for idruta, tipo, longitud, suma in filas:
        assert tipo == "ST_LineString", idruta
        assert abs(float(longitud) - float(suma)) < 0.1, (idruta, longitud, suma)


@pytest.mark.parametrize(("tabla", "llave"), [("progvehiculos", "idprogramacion"),
                                              ("timbradas_anio", "id_timbrada_anio"),
                                              ("timbradas_consolidado", "id_timbrada_consolidado"),
                                              ("rutas_segmentos", "id"), ("rutas_segmentos_config", "id")])
def test_ids_originales(cargada, tabla, llave):
    pq = pytest.importorskip("pyarrow.parquet")
    archivo = DATOS / f"{tabla}.parquet"
    if not archivo.exists():
        pytest.skip("exportaciones Parquet no disponibles")
    ids = pq.read_table(archivo, columns=[llave])[llave]
    import pyarrow.compute as pc

    with cargada.cursor() as cur:
        cur.execute(f"SELECT min({llave}), max({llave}), count(DISTINCT {llave}), sum({llave}::numeric) "
                    f"FROM public.{tabla}")
        mn, mx, n, suma = cur.fetchone()
    assert (mn, mx, n) == (pc.min(ids).as_py(), pc.max(ids).as_py(), len(ids))
    assert int(suma) == pc.sum(ids).as_py()


def test_secuencias_ajustadas(cargada):
    """El siguiente valor de cada secuencia es mayor que el máximo id cargado (sin consumir valores)."""
    with cargada.cursor() as cur:
        cur.execute("""SELECT s.oid::regclass::text, t.oid::regclass::text, a.attname,
                              pg_sequence_last_value(s.oid)
                       FROM pg_class s JOIN pg_depend d ON d.objid = s.oid AND d.deptype IN ('a', 'i')
                       JOIN pg_class t ON t.oid = d.refobjid
                       JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = d.refobjsubid
                       WHERE s.relkind = 'S' AND t.relnamespace = 'public'::regnamespace""")
        secuencias = cur.fetchall()
        assert len(secuencias) >= 5
        for seq, tabla, col, ultimo in secuencias:
            cur.execute(f'SELECT max("{col}") FROM {tabla}')
            maximo = cur.fetchone()[0]
            if maximo is not None:
                assert ultimo is not None and ultimo >= maximo, seq
        # conteo_pasajeros arranca vacía, pero su secuencia queda por encima de los ids de la muestra real (93.091 filas
        # de los viajes reservados), para que el simulador nunca choque con ellos
        cur.execute("SELECT pg_sequence_last_value('public.conteo_pasajeros_id_seq')")
        assert cur.fetchone()[0] >= 644_349_911


def test_llaves_foraneas_sin_huerfanas(cargada):
    """La carga masiva no revisa llaves foráneas fila por fila: aquí se comprueban todas, completas."""
    with cargada.cursor() as cur:
        cur.execute("""SELECT c.conname, c.conrelid::regclass::text, c.confrelid::regclass::text,
                              array_agg(a.attname ORDER BY k.ord), array_agg(af.attname ORDER BY k.ord)
                       FROM pg_constraint c
                       CROSS JOIN LATERAL unnest(c.conkey, c.confkey) WITH ORDINALITY AS k(col, fcol, ord)
                       JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = k.col
                       JOIN pg_attribute af ON af.attrelid = c.confrelid AND af.attnum = k.fcol
                       WHERE c.contype = 'f' AND c.connamespace = 'public'::regnamespace GROUP BY 1, 2, 3""")
        fks = cur.fetchall()
        assert len(fks) >= 10
        for nombre, hija, madre, cols, fcols in fks:
            union = " AND ".join(f'm."{f}" = h."{c}"' for c, f in zip(cols, fcols, strict=True))
            cur.execute(f"SELECT count(*) FROM {hija} h WHERE NOT EXISTS (SELECT 1 FROM {madre} m WHERE {union})")
            assert cur.fetchone()[0] == 0, nombre


def test_columnas_sensibles_en_null(cargada):
    with cargada.cursor() as cur:
        cur.execute("""SELECT count(clave_interfaz_despacho) + count(usuario_interfaz_despacho)
                              + count(url_interfaz_despacho) FROM public."Procesos" """)
        assert cur.fetchone()[0] == 0
        cur.execute("""SELECT count(modem_passwd) + count(modem_user) + count(modem_puk) + count(modem_passwd_2)
                              + count(modem_user_2) + count(modem_puk_2) FROM public.vehiculos""")
        assert cur.fetchone()[0] == 0


def test_armonizacion_h1_aplicada(cargada):
    with cargada.cursor() as cur:
        cur.execute("SELECT proceso, count(*) FROM public.estacionalidades_anio GROUP BY 1")
        assert dict(cur.fetchall()) == {"sobusa": 231}
        cur.execute("SELECT nota FROM replica_meta.paso WHERE paso = 'carga H1'")
        assert "231 filas" in cur.fetchone()[0]


def test_scripts_99_5_6_no_procesan_datos_de_sobusa(cargada):
    with cargada.cursor() as cur:
        cur.execute("SELECT paso, nota FROM replica_meta.paso WHERE paso LIKE 'post-carga%' ORDER BY n")
        pasos = cur.fetchall()
    assert [p[0] for p in pasos] == ["post-carga 99", "post-carga 5", "post-carga 6"]
    for _, nota in pasos:
        antes = nota.split("antes=")[1].split(" después=")[0]
        despues = nota.split("después=")[1].split(" (")[0]
        assert antes == despues
