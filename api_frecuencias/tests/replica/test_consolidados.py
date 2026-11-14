"""Consolidados de Extreme y bajadas con la réplica operacional LOCAL, en solo lectura (lector_ia; §5.2 ALT-008, §6.1,
§6.3, §7.3 paso 3, §11.2). Nada de esto escribe en la réplica: cada consulta pasa por
FuentePostgresSoloLectura.consultar (READ ONLY, statement_timeout, ROLLBACK).

- El ciclo lee timbradas_consolidado de la réplica sin romperse: las 10.731 filas pasan la calidad con las reglas
  nuevas (CONS-001 con CEIL, VAL-007, VAL-008, REL-007) sin falsos errores, la segunda lectura las descarta por huella
  (H7) y el contraste con el histórico encuentra lo que se ve a simple vista en los totales (bajadas de la ruta 21).
- Las tablas por segmento no tienen filas de Sobusa (H4): el ciclo lo dice.
- Las bajadas empaquetadas (datos/bajadas_horaria.parquet) y las de la lectura integrada son las de la réplica.
- Por hora de fin el consolidado se reproduce casi exacto y por hora de salida no (H10): el grano del contraste.
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from scripts import replica_comun as rc

ZONA = ZoneInfo("America/Bogota")


@pytest.fixture
def fuente(cargada):
    if not rc.url_rol("lector_ia"):
        pytest.skip("falta la clave de lector_ia")
    from scripts import contraste_consolidados

    f = contraste_consolidados.fuente()
    yield f
    f._engine().dispose()


def test_el_ciclo_lee_valida_y_contrasta_el_consolidado_real_sin_romperse(fuente):
    from scripts import contraste_consolidados

    r = contraste_consolidados.contraste_ruta(fuente)
    assert r["filas"] == 10731 and r["lectura"]["entregadas"] == 10731
    assert r["calidad"]["validas"] == 10731 and r["calidad"]["errores_por_codigo"] == {}
    assert {"dias_semana", "dias_estacionalidad", "segmentos_ruta"} <= set(r["calidad"]["catalogos"])
    # el resellado sin cambios no se vuelve a entregar (huella de contenido, H7)
    assert r["segunda_lectura_con_huellas"] == {"leidas": 10731, "entregadas": 0, "repetidas_solape": 10731}
    c = r["contraste"]
    assert r["periodo"] == ["2023-01-01", "2025-12-31"] and c["comparadas"] >= 150
    # los promedios de subidas cuadran (mediana < 3 %); las bajadas de la ruta 21 no (total +58 %): grosera
    assert r["distribucion_diferencias"]["promedio_subidas"]["mediana"] < 0.03
    t21 = r["totales_por_ruta"][21]
    assert t21["bajadas_extreme"] > 1.5 * t21["bajadas_propia"]
    assert any(i["llave"]["id_ruta"] == 21 and i["campo"] == "promedio_bajadas" and i["bloqueante"]
               for i in r["incidencias"])
    assert c["groseras"] == sum(1 for i in r["incidencias"] if i["bloqueante"])


def test_el_paso_del_ciclo_lee_la_replica_y_escribe_solo_en_la_base_local(fuente, monkeypatch):
    """consolidados.en_ciclo, el mismo paso que corre el ciclo, con la réplica como base operacional (lector_ia, solo
    lectura) y la base LOCAL de pruebas como esquema propio (TEST_DATABASE_NAME, migrada a head): lee las 10.731
    filas, no da falsos errores de calidad, registra las dos tablas por segmento sin filas (H4) y deja la marca de la
    tabla; la segunda vez no hay nada nuevo (huellas)."""
    from sqlalchemy import create_engine, delete, select
    from sqlalchemy.orm import Session

    from app.modelos_db import Ejecucion, ErrorCalidad, MarcaAguaTabla
    from app.servicios import consolidados, ejecucion, segmentos
    from tests.integracion import conftest as base_local

    url = base_local.requerir_base()
    base_local._alembic("upgrade", "head")
    # sesión explícita sobre la base LOCAL de pruebas (como tests/replica/test_segmentos.py): nunca otra base
    propia = create_engine(url, connect_args={"options": "-c timezone=America/Bogota"})
    monkeypatch.setattr(segmentos, "fuente_configurada", lambda: True)
    monkeypatch.setattr(segmentos, "fuente", lambda motor=None: fuente)
    ids: list = []
    resultados: list[dict] = []
    try:
        with Session(propia) as s:
            s.execute(delete(MarcaAguaTabla).where(MarcaAguaTabla.proceso == "sobusa"))
            s.commit()
            for _ in range(2):
                eid = ejecucion.crear_ejecucion(s, "frecuencia", {"prueba": "consolidados_replica"}, None).execution_id
                ids.append(eid)
                fallos: list = []
                resultados.append(consolidados.en_ciclo(s, eid, {}, fallos))
                s.commit()
                assert fallos == []
            codigos = set(s.scalars(select(ErrorCalidad.codigo).where(ErrorCalidad.execution_id == ids[0])))
            marca = s.get(MarcaAguaTabla, ("sobusa", "timbradas_consolidado"))
            assert marca is not None and marca.execution_id == ids[0] and marca.filas_leidas == 10731
        primera, segunda = resultados
        t = primera["tablas"]["timbradas_consolidado"]
        assert t["resultado"] == "contrastado" and t["filas"] == 10731 and t["filas_validas"] == 10731
        # sin falsos errores de calidad: lo único que puede quedar es el contraste con el histórico de la base local
        assert set(t["errores_por_codigo"]) <= {"CONTR-001"} and codigos <= {"CONTR-001"}
        assert t["contraste"]["periodo"] == ["2023-01-01T00:00:00", "2025-12-31T00:00:00"]
        for tabla in ("timbradas_segmentos_anio", "timbradas_segmentos_consolidado"):
            assert primera["tablas"][tabla]["resultado"] == "sin_filas_fuente"
            assert "H4" in primera["tablas"][tabla]["detalle"]
        t = segunda["tablas"]["timbradas_consolidado"]
        assert t["resultado"] == "sin_cambios" and t["lectura"]["repetidas_solape"] == 10731
        assert segunda["resultados"] == {"sin_cambios": 1, "sin_filas_fuente": 2}
    finally:
        with Session(propia) as s:
            s.execute(delete(Ejecucion).where(Ejecucion.execution_id.in_(ids)))
            s.commit()
        propia.dispose()


def test_h17_festivos_con_dos_filas_cuentan_dos_veces_y_los_dias_corrientes_suman_de_mas(fuente):
    """H17 (de dónde salen las diferencias groseras de viajes por día del contraste): los festivos de un día
    con dos filas en estacionalidades_anio aparecen con las dos en timbradas_anio, cada una con los viajes aptos de esa
    fecha de fin; y DIAS_CORRIENTES suma más viajes que los aptos de los días corrientes, en todas las rutas y años."""
    from datetime import date

    from scripts import contraste_consolidados

    repetidos = [x for x in contraste_consolidados.festivos_repetidos(fuente) if x["aptos_fecha_de_fin"] > 0]
    assert len(repetidos) >= 4
    for x in repetidos:
        viajes = set(x["viajes_timbradas_anio"].values())
        assert len(viajes) == 1 and abs(viajes.pop() - x["aptos_fecha_de_fin"]) <= 0.1 * x["aptos_fecha_de_fin"]
    filas = contraste_consolidados.anio_frente_a_aptos(fuente, (date(2023, 1, 1), date(2025, 12, 31)))
    assert len(filas) == 9 and all(f["viajes_corrientes"] > f["aptos_corrientes"] for f in filas)


def test_la_lectura_filtra_el_proceso_en_el_sql_sin_cambiar_lo_de_sobusa(fuente):
    """La lectura incremental de timbradas_consolidado filtra el proceso en el SQL (fuentes.TABLAS_CON_PROCESO): con la
    réplica, en solo lectura, entrega las mismas filas de Sobusa y la misma marca que leer todos los procesos y
    filtrar después, y sus huellas son solo de filas de Sobusa."""
    from app.servicios.fuentes import FuentePostgresSoloLectura

    def lectura(proceso):
        f = FuentePostgresSoloLectura(motor=fuente._engine(), tabla="timbradas_consolidado", proceso=proceso,
                                      statement_timeout_ms=120000)
        d, marca = f.leer_incremental(None)
        return f, d, marca

    filtrada, d, marca = lectura("sobusa")
    _todas, d_todas, _marca_todas = lectura("*")
    sobusa = d_todas[d_todas["proceso"].astype(str) == "sobusa"]
    assert filtrada.filtra_proceso and len(d) == len(sobusa) == 10731 and set(d["proceso"]) == {"sobusa"}
    columnas = ["id_timbrada_consolidado", "subidas", "bajadas", "nro_viajes"]
    assert d.sort_values(columnas[0])[columnas].reset_index(drop=True).equals(
        sobusa.sort_values(columnas[0])[columnas].reset_index(drop=True))
    assert pd.Timestamp(marca) == pd.Timestamp(sobusa["ultima_actualizacion"].max())
    assert all(k.startswith("sobusa|") for k in filtrada.estado_incremental["huellas"])


def test_la_frecuencia_vigente_sale_de_la_tabla_rutas_de_la_replica(fuente, monkeypatch):
    """§6.1 «frecuenciadespachos» y §6.2 «headway vigente» (supuesto S14): en modo integrado datos.ruta_info toma
    rutas.frecuenciadespachos de la réplica (lector_ia, lista blanca de fuentes.py, solo lectura), dice de dónde salió
    (frecuencia_fuente) y la recomendación lee ese valor (optimizacion.frecuenciadespachos_min)."""
    from app.servicios import datos, fuentes, optimizacion, segmentos

    fuentes.limpiar_frecuencias()
    monkeypatch.setattr(segmentos, "fuente_configurada", lambda: True)
    monkeypatch.setattr(segmentos, "fuente", lambda motor=None: fuente)
    tabla = fuente.leer_contexto("frecuencias")
    try:
        for r in datos.catalogo_rutas():
            info = datos.ruta_info(r["ruta"])
            esperado = tabla.loc[pd.to_numeric(tabla["idruta"]) == int(r["idruta"]), "frecuenciadespachos"].iloc[0]
            assert info["frecuencia_fuente"] == datos.FRECUENCIA_DE_LA_FUENTE, info
            assert info["frecuenciadespachos_tabla_rutas"] == esperado
            assert optimizacion.frecuenciadespachos_min(info) == float(str(esperado).replace(",", "."))
    finally:
        fuentes.limpiar_frecuencias()


def test_las_tablas_por_segmento_no_tienen_filas_de_sobusa_h4(fuente):
    from scripts import contraste_consolidados

    r = contraste_consolidados.segmentos_sin_filas(fuente)
    assert set(r) == {"timbradas_segmentos_anio", "timbradas_segmentos_consolidado"}
    assert all(t["filas_del_proceso"] == 0 and "H4" in t["motivo"] for t in r.values())


SQL_BAJADAS = """
SELECT pv.idruta, CAST(pv.fechasalida AS date) AS fecha, CAST(EXTRACT(HOUR FROM pv.fechasalida) AS integer) AS hora,
       COALESCE(SUM(pv.numerobajadas) FILTER (WHERE pv.numerobajadas <= 300), 0) AS bajadas
  FROM progvehiculos pv
 WHERE pv.finalizado = 'S' AND pv.cancelada = 'N' AND pv.fechasalida >= :desde AND pv.fechasalida < :hasta
   AND EXTRACT(HOUR FROM pv.fechasalida) BETWEEN 4 AND 20
 GROUP BY 1, 2, 3
"""


def test_las_bajadas_empaquetadas_son_las_de_la_replica(fuente):
    """Linaje de datos/bajadas_horaria.parquet: Σ numerobajadas de los viajes válidos por ruta, fecha y hora de salida
    de la réplica, franja por franja (una franja sin viajes válidos vale 0, como pasajeros)."""
    from app.servicios import datos

    empaquetadas = datos.bajadas_horaria()
    if empaquetadas is None:
        pytest.skip("sin datos/bajadas_horaria.parquet")
    d = fuente.consultar(SQL_BAJADAS, {"desde": datetime(2023, 1, 1, tzinfo=ZONA),
                                       "hasta": datetime(2026, 1, 1, tzinfo=ZONA)})
    idruta = {r["ruta"]: int(r["idruta"]) for r in datos.catalogo_rutas()}
    e = empaquetadas.assign(idruta=empaquetadas["ruta"].map(idruta))
    d["fecha"] = pd.to_datetime(d["fecha"]).dt.date
    m = e.merge(d, on=["idruta", "fecha", "hora"], how="left")
    m["bajadas"] = pd.to_numeric(m["bajadas"], errors="coerce").fillna(0.0)
    assert len(m) == 55896 and (m["bajadas"] == m["bajadas_viajes"]).all()
    assert int(m["bajadas"].sum()) == int(d["bajadas"].astype(float).sum())     # ninguna franja de la réplica sobra


def test_la_lectura_integrada_trae_las_bajadas_de_la_definicion_de_pasajeros(fuente):
    """Las franjas que lee el ciclo (demanda_segmentos, 2.757 en la réplica) traen bajadas_viajes iguales a las
    empaquetadas, además de las subidas y bajadas de los segmentos y su cobertura."""
    from app.servicios import datos
    from app.servicios.fuentes import FuentePostgresSoloLectura

    integrada = FuentePostgresSoloLectura(motor=fuente._engine(), tabla="demanda_segmentos", proceso="sobusa",
                                          statement_timeout_ms=120000)
    d, _ = integrada.leer_incremental(None)
    assert {"bajadas_viajes", "subidas", "bajadas", "viajes_con_timbradas"} <= set(d.columns)
    d["fecha"] = pd.to_datetime(d["fecha"]).dt.date
    m = d.merge(datos.bajadas_horaria(), on=["ruta", "fecha", "hora"], how="inner", suffixes=("", "_empaquetadas"))
    assert len(m) == len(d) >= 2700
    assert (m["bajadas_viajes"] == m["bajadas_viajes_empaquetadas"]).all()


def test_por_hora_de_fin_el_consolidado_se_reproduce_y_por_hora_de_salida_no_h10(fuente):
    from datetime import date

    from scripts import contraste_consolidados

    r = contraste_consolidados.analisis_h10(fuente, (date(2023, 1, 1), date(2025, 12, 31)))
    assert r["por_hora_de_fin"]["promedio_subidas"]["mediana"] < 0.03
    assert r["por_hora_de_fin"]["promedio_bajadas"]["mediana"] < 0.03
    assert r["por_hora_de_salida"]["promedio_subidas"]["mediana"] > 0.10


def test_en_los_mismos_viajes_las_bajadas_de_los_segmentos_son_numerobajadas(fuente):
    from scripts import contraste_consolidados

    t = contraste_consolidados.definicion_bajadas(fuente)["total"]
    assert abs(t["diferencia_mismos_viajes"]) < 0.005 and t["diferencia_total"] < -0.03
    assert t["viajes_con_timbradas"] < t["viajes_validos"]
