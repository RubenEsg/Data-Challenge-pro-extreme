"""Modo integrado y controles de no interferencia (§8.1, §8.3, §11.2, §11.3; RF-001, RF-002, RF-013, RF-014).

La API lee las tablas de Extreme con lector_ia y escribe sus resultados en ai_frecuencias con escritor_ia, en la MISMA
base de la réplica. Estas pruebas demuestran que ni el proceso de la API ni sus dos usuarios pueden escribir en las
tablas de Extreme, que la lectura corrige los defectos del esquema real ("Procesos", ultimaactualizacion, zona horaria)
y que Alembic migra como escritor_ia sin crear nada fuera de ai_frecuencias.

Las que ESCRIBEN en la réplica (ciclo completo con llegada de datos) solo corren con REPLICA_PRUEBAS_ESCRITURA=1 y se
serializan con un candado de la base: varias suites pueden correr a la vez sobre la misma réplica.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import date, timedelta

import pytest

from scripts import replica_comun as rc

psycopg = pytest.importorskip("psycopg")
from psycopg import errors  # noqa: E402

ESCRITURA = os.environ.get("REPLICA_PRUEBAS_ESCRITURA") == "1"
requiere_escritura = pytest.mark.skipif(
    not ESCRITURA, reason="escribe en la réplica (llegada de datos y ai_frecuencias): REPLICA_PRUEBAS_ESCRITURA=1")

# §8.3: «No crear INSERT, UPDATE ni DELETE sobre timbradas_anio, timbradas_consolidado, timbradas_segmentos,
# timbradas_segmentos_consolidados ni sus tablas por zona desde el módulo de IA» (más las fuentes y catálogos).
TABLAS_EXTREME = ("timbradas_anio", "timbradas_anio_zonas", "timbradas_consolidado", "timbradas_consolidado_zonas",
                  "timbradas_segmentos", "timbradas_segmentos_anio", "timbradas_segmentos_consolidado",
                  "conteo_pasajeros", "progvehiculos", "rutas", "Procesos", "estacionalidades_anio",
                  "novedades_viales_fecha", "rutas_segmentos")


def _url_sa(rol: str) -> str:
    url = rc.url_rol(rol)
    if not url:
        pytest.skip(f"falta la clave de {rol}")
    return url.replace("postgresql://", "postgresql+psycopg://")


def _q(tabla: str) -> str:
    return f'public."{tabla}"'


@pytest.mark.parametrize("tabla", TABLAS_EXTREME)
@pytest.mark.parametrize("sentencia", ["INSERT INTO {t} DEFAULT VALUES", "DELETE FROM {t} WHERE false",
                                       "TRUNCATE {t}", "ALTER TABLE {t} ADD COLUMN intruso_ia integer",
                                       "CREATE INDEX ON {t} ((1))", "LOCK TABLE {t} IN EXCLUSIVE MODE"])
def test_escritor_ia_no_puede_escribir_ni_alterar_tablas_de_extreme(escritor, tabla, sentencia):
    """§11.3: el usuario que escribe resultados no tiene NINGÚN permiso de escritura ni DDL fuera de ai_frecuencias."""
    with escritor.cursor() as cur, pytest.raises(errors.InsufficientPrivilege):
        if sentencia.startswith("LOCK"):
            with escritor.transaction():
                cur.execute(sentencia.format(t=_q(tabla)))
        else:
            cur.execute(sentencia.format(t=_q(tabla)))


def test_nadie_de_la_ia_puede_deshabilitar_el_trigger_ni_tocar_funciones(lector, escritor):
    """§11.3 «No deshabilitar triggers» y «No modificar las funciones»: ni lector_ia ni escritor_ia pueden."""
    for cx in (lector, escritor):
        with cx.cursor() as cur:
            cur.execute("SET default_transaction_read_only = off")
            for sql in ("ALTER TABLE public.conteo_pasajeros DISABLE TRIGGER tg_timbrada_segmento",
                        "DROP TRIGGER tg_timbrada_segmento ON public.conteo_pasajeros",
                        "CREATE OR REPLACE FUNCTION public.fn_consolidar_timbradas_historicas() RETURNS boolean "
                        "LANGUAGE sql AS 'SELECT true'"):
                with pytest.raises(errors.InsufficientPrivilege):
                    cur.execute(sql)
    with lector.cursor() as cur:
        cur.execute("""SELECT tgenabled FROM pg_trigger WHERE tgname = 'tg_timbrada_segmento'""")
        assert cur.fetchone()[0] == "O"


def test_privilegios_efectivos_de_los_usuarios_de_la_ia(admin):
    """Prueba exhaustiva por catálogo: sobre TODAS las tablas de public, lector_ia solo tiene SELECT y escritor_ia
    nada; ninguno puede crear en public ni en la base; escritor_ia es dueño solo de objetos de ai_frecuencias."""
    with admin.cursor() as cur:
        escritura = "INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER"
        cur.execute("""SELECT c.relname,
                              has_table_privilege('lector_ia', c.oid, 'SELECT'),
                              has_table_privilege('lector_ia', c.oid, %(e)s),
                              has_table_privilege('escritor_ia', c.oid, %(e)s)
                         FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                        WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p', 'v', 'm')
                          AND c.relname <> 'spatial_ref_sys'""", {"e": escritura})
        filas = cur.fetchall()
        assert len(filas) >= 25
        assert all(sel for _, sel, _, _ in filas), "lector_ia debe poder leer todas las tablas de Extreme"
        assert not [t for t, _, esc_l, _ in filas if esc_l], "lector_ia tiene algún permiso de escritura"
        assert not [t for t, _, _, esc_e in filas if esc_e], "escritor_ia tiene algún permiso sobre public"
        cur.execute("""SELECT has_schema_privilege('lector_ia', 'public', 'CREATE'),
                              has_schema_privilege('escritor_ia', 'public', 'CREATE'),
                              has_database_privilege('lector_ia', current_database(), 'CREATE'),
                              has_database_privilege('escritor_ia', current_database(), 'CREATE'),
                              has_schema_privilege('lector_ia', 'ai_frecuencias', 'CREATE'),
                              has_schema_privilege('escritor_ia', 'ai_frecuencias', 'CREATE')""")
        assert cur.fetchone() == (False, False, False, False, False, True)
        cur.execute("""SELECT DISTINCT n.nspname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                        WHERE pg_get_userbyid(c.relowner) IN ('lector_ia', 'escritor_ia')
                          AND n.nspname <> 'pg_toast'""")      # las TOAST de sus propias tablas viven en pg_toast
        assert {r[0] for r in cur.fetchall()} <= {"ai_frecuencias"}


def test_la_fuente_de_la_api_es_de_solo_lectura_en_tres_capas(cargada):
    """1) el validador rechaza sin conectar; 2) la transacción READ ONLY rechaza (25006); 3) aun sin READ ONLY, el
    usuario no tiene permiso (42501). Es el mismo código que usa la API en modo integrado."""
    from sqlalchemy import create_engine, text

    from app.servicios.fuentes import FuentePostgresSoloLectura, OperacionNoPermitida

    url = _url_sa("lector_ia")
    f = FuentePostgresSoloLectura(url=url, tabla="timbradas_consolidado")
    with pytest.raises(OperacionNoPermitida):
        f.consultar("UPDATE timbradas_consolidado SET subidas = subidas WHERE false")
    assert f._motor is None                       # ni siquiera se creó el motor: no se tocó la base
    motor = create_engine(url, pool_size=1, max_overflow=0)
    try:
        with motor.connect() as conn:
            conn.execute(text("SET TRANSACTION READ ONLY"))
            with pytest.raises(Exception) as exc:
                conn.execute(text("UPDATE public.timbradas_consolidado SET subidas = subidas WHERE false"))
            assert isinstance(exc.value.orig, errors.ReadOnlySqlTransaction)
            conn.rollback()
        with motor.connect() as conn:
            conn.execute(text("SET TRANSACTION READ WRITE"))
            with pytest.raises(Exception) as exc:
                conn.execute(text("UPDATE public.timbradas_consolidado SET subidas = subidas WHERE false"))
            assert isinstance(exc.value.orig, errors.InsufficientPrivilege)
            conn.rollback()
    finally:
        motor.dispose()


def test_procesos_con_comillas_y_contexto_operacional(cargada):
    """"Procesos" (mayúscula y comillas) y las tablas de contexto que usa el modelo, leídas por la API (RF-003)."""
    from app.servicios.fuentes import FuentePostgresSoloLectura

    url = _url_sa("lector_ia")
    p = FuentePostgresSoloLectura(url=url, tabla="Procesos")
    d, _ = p.leer_incremental()
    assert list(d["proceso"]) == ["sobusa"]
    assert len(p.leer_contexto("rutas")) == 3
    assert len(p.estacionalidades_anio()) == 231
    nov = p.novedades_viales()
    assert len(nov) == 28 and {"porcentaje_impacto", "potencial_efecto", "rutas"} <= set(nov.columns)
    assert "clave_interfaz_despacho" not in p.procesos().columns      # minimización: credenciales no se leen
    p._engine().dispose()


def test_marca_sin_zona_se_compara_en_hora_de_bogota(cargada, lector):
    """H10: ultimaactualizacion es timestamp SIN zona (NOW() del servidor en Bogotá). La fuente fija TimeZone y lee
    exactamente las filas posteriores a la marca; con la sesión en UTC la misma marca se correría 5 horas."""
    from app.servicios.fuentes import FuentePostgresSoloLectura

    with lector.cursor() as cur:
        cur.execute("SELECT max(ultimaactualizacion) FROM public.timbradas_segmentos")
        maximo = cur.fetchone()[0]
        corte = maximo - timedelta(minutes=30)                # naive, hora de Bogotá
        cur.execute("SELECT count(*) FROM public.timbradas_segmentos WHERE ultimaactualizacion > %s",
                    (corte - timedelta(minutes=15),))
        esperado = cur.fetchone()[0]
    import pandas as pd

    f = FuentePostgresSoloLectura(url=_url_sa("lector_ia"), tabla="timbradas_segmentos", limite=10_000_000)
    marca = pd.Timestamp(corte).tz_localize("America/Bogota").to_pydatetime()
    d, nueva = f.leer_incremental(marca)
    assert f.resumen_lectura["leidas"] == esperado > 0
    assert pd.Timestamp(nueva) == pd.Timestamp(maximo).tz_localize("America/Bogota")
    f._engine().dispose()
    with lector.cursor() as cur:                              # el defecto que se corrige: sesión en UTC
        cur.execute("BEGIN")
        cur.execute("SET LOCAL TimeZone = 'UTC'")
        cur.execute("SELECT count(*) FROM public.timbradas_segmentos WHERE ultimaactualizacion > %s",
                    (marca - timedelta(minutes=15),))
        en_utc = cur.fetchone()[0]
        cur.execute("ROLLBACK")
    assert en_utc != esperado


def test_alembic_upgrade_head_como_escritor_ia(cargada, admin):
    """§8.1 y §11.3: Alembic migra con el usuario de escritura (sin CREATE en la base) y todo queda en
    ai_frecuencias, incluida la tabla de versiones. Antes fallaba con 42501 en CREATE SCHEMA IF NOT EXISTS."""
    from scripts.replica_simular_llegada import candado

    entorno = {k: v for k, v in os.environ.items() if not k.startswith(("DATABASE_URL", "TEST_DATABASE"))}
    entorno["DATABASE_URL"] = _url_sa("escritor_ia")
    with candado(admin, espera_s=300):
        r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=rc.RAIZ, env=entorno,  # noqa: S603
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300,
                           check=False)
    assert r.returncode == 0, (r.stderr or r.stdout)[-1500:]
    with admin.cursor() as cur:
        cur.execute("SELECT count(*) FROM ai_frecuencias.alembic_version")
        assert cur.fetchone()[0] == 1
        cur.execute("""SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                        WHERE pg_get_userbyid(c.relowner) = 'escritor_ia'
                          AND n.nspname NOT IN ('ai_frecuencias', 'pg_toast')""")
        assert cur.fetchone()[0] == 0
        cur.execute("SELECT to_regclass('public.alembic_version')")
        assert cur.fetchone()[0] is None


@requiere_escritura
def test_ciclo_integrado_lee_exactamente_lo_nuevo_y_luego_nada(cargada, tmp_path):
    """§14.2 (llegada, lectura incremental, sin reprocesar): carga inicial, llegada de un viaje por el trigger de
    Extreme, ejecución que lee solo su franja y ejecución siguiente sin datos nuevos. La réplica queda restaurada."""
    salida = tmp_path / "informe.json"
    entorno = {k: v for k, v in os.environ.items() if not k.startswith(("DATABASE_URL", "TEST_DATABASE"))}
    r = subprocess.run([sys.executable, "-m", "scripts.replica_simular_llegada", "--viajes", "1", "--filas-max", "60",
                        "--ciclo-api", "--sin-evidencia", "--salida", str(salida)], cwd=rc.RAIZ, env=entorno,  # noqa: S603
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900, check=False)
    assert r.returncode == 0, (r.stderr or r.stdout)[-2000:]
    inf = json.loads(salida.read_text(encoding="utf-8"))
    corridas = inf["ciclo_api"]["corridas"]
    assert [c["estado"] for c in corridas] == ["ok", "ok", "ok"]
    nuevas = inf["lecturas_lector_ia"]["demanda_segmentos"]["primera"]["entregadas"]
    assert nuevas >= 1
    assert corridas[1]["filas_leidas"] == nuevas and corridas[1]["lectura"]["nuevas"] == nuevas
    assert corridas[2]["filas_leidas"] == 0 and corridas[2]["predicciones"] == 0
    assert inf["tablas_de_escritor_ia_por_esquema"].keys() == {"ai_frecuencias"}
    assert inf["tras_restaurar"] == inf["antes"]


def test_demanda_segmentos_usa_la_definicion_del_modelo_con_proceso_y_estacionalidad(cargada):
    """La lectura integrada entrega la misma medida que el histórico empaquetado y el objetivo del modelo
    (Σ numeropasajeros de los viajes válidos; docs/evidencias/datos/definicion_pasajeros.md), con proceso, idempresa
    e id_estacionalidad (§8.3, §11.2). Σ subidas de los segmentos queda aparte, en la columna subidas."""
    from app.servicios import datos
    from app.servicios.fuentes import FuentePostgresSoloLectura

    f = FuentePostgresSoloLectura(url=_url_sa("lector_ia"), tabla="demanda_segmentos")
    d, _ = f.leer_incremental(None)
    f._engine().dispose()
    assert len(d) > 2000 and set(d["proceso"]) == {"sobusa"} and set(d["tipo_llegada"]) == {"carga_inicial"}
    assert d["id_estacionalidad"].notna().all()
    servicio = d[d["hora"].between(4, 20)]
    emp = datos.demanda_horaria(desde=date(2023, 1, 1), hasta=date(2023, 2, 27))
    m = servicio.merge(emp, on=["ruta", "fecha", "hora"], suffixes=("", "_empaquetado"))
    assert len(m) == len(servicio)
    assert (m["pasajeros"] == m["pasajeros_empaquetado"]).all()
    assert (m["salidas"] == m["salidas_empaquetado"].astype(int)).all()
    assert {"subidas", "bajadas", "viajes_con_timbradas"} <= set(d.columns) and float(m["subidas"].sum()) > 0


def test_ubicacion_despacho_de_la_replica_coincide_con_la_empaquetada(cargada):
    """C5: el inicio del segmento 1 (ST_StartPoint, solo lectura) es el punto que usa el modo offline."""
    from app.servicios import calidad
    from app.servicios import fuentes as F

    f = F.FuentePostgresSoloLectura(url=_url_sa("lector_ia"))
    for ruta in ("SILENCIO", "CRA 54", "CL 72"):
        real, empaquetado = f.ubicacion_despacho(ruta), F.FuenteParquet().ubicacion_despacho(ruta)
        assert real["type"] == "Point" and real["coordinates"] == pytest.approx(empaquetado["coordinates"], abs=1e-6)
    cat = calidad.catalogos_desde_fuente(f)
    f._engine().dispose()
    assert cat["procesos"] == {"sobusa"} and cat["idrutas"] == {2, 16, 21} and len(cat["estacionalidades"]) == 24
    assert len(cat["segmentos"]) == 2695 and len(cat["novedades"]) == 59


def test_consolidado_real_sin_falsos_errores_de_calidad(cargada):
    """§6.3 con el esquema consolidado real: las 10.731 filas de timbradas_consolidado (bloques de 15 min, hora de
    tipo time, bloque 23:45-00:00) pasan sin UNI-001 ni VAL-004 con la llave de 7 columnas."""
    from app.servicios import calidad
    from app.servicios.fuentes import FuentePostgresSoloLectura

    f = FuentePostgresSoloLectura(url=_url_sa("lector_ia"), tabla="timbradas_consolidado")
    d = f.consultar("SELECT * FROM timbradas_consolidado")
    cat = calidad.catalogos_desde_fuente(f)
    f._engine().dispose()
    validos, errores = calidad.validar_lote(d.drop(columns=["id_timbrada_consolidado"]), "consolidado", catalogos=cat)
    assert len(d) == 10731 and len(validos) == len(d)
    assert not [e for e in errores if e["codigo"] in ("UNI-001", "VAL-004")]


def test_la_ia_no_puede_apagar_triggers_por_sesion_y_su_unico_privilegio_de_base_es_temporary(lector, escritor):
    """§11.3 «no deshabilitar triggers»: session_replication_role = replica (lo único que usa la carga de la réplica,
    como extreme_dba) da 42501 a los dos usuarios de la IA. escritor_ia solo tiene TEMPORARY en la base (la tabla
    temporal de la ingesta, que vive en su sesión); ninguno tiene CREATE."""
    for cx in (lector, escritor):
        with cx.cursor() as cur:
            with pytest.raises(errors.InsufficientPrivilege):
                cur.execute("SET session_replication_role = replica")
    with lector.cursor() as cur:
        cur.execute("SELECT has_database_privilege(current_user, current_database(), 'TEMPORARY'), "
                    "has_database_privilege(current_user, current_database(), 'CREATE')")
        assert cur.fetchone() == (False, False)
    with escritor.cursor() as cur:
        cur.execute("SELECT has_database_privilege(current_user, current_database(), 'TEMPORARY'), "
                    "has_database_privilege(current_user, current_database(), 'CREATE')")
        assert cur.fetchone() == (True, False)


def test_linaje_el_historico_empaquetado_se_reconstruye_identico_desde_la_replica(cargada):
    """Trazabilidad y reproducibilidad (§16): datos/demanda_horaria.parquet (pasajeros y salidas) y
    datos/contexto_operacional.parquet salen de las tablas de Extreme con contenido idéntico (mismo SHA-256 del
    contenido normalizado). Es lo que escribe «python -m scripts.reconstruir_desde_replica --linaje»."""
    from scripts import reconstruir_desde_replica as R

    f = R._fuente()
    r = R.linaje(f)
    f._engine().dispose()
    dh, cx = r["demanda_horaria"], r["contexto_operacional"]
    assert dh["contenido_identico"] and cx["contenido_identico"]
    assert dh["comparacion"]["pasajeros"]["distintas"] == 0 and dh["comparacion"]["salidas"]["distintas"] == 0
    assert dh["comparacion"]["filas_empaquetadas"] == dh["comparacion"]["filas_reconstruidas"] == 55896
    assert r["entradas"]["progvehiculos"]["filas_2023_2025"] == 564837
