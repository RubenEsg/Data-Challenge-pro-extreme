"""Las tablas por segmento de Extreme con filas REALES de la liquidación (§6.1 «prom_…_x_segmento», §6.3, §11.2;
hallazgos H4 y H10; app/servicios/consolidados.py).

En la réplica timbradas_segmentos_anio y timbradas_segmentos_consolidado no tienen filas de Sobusa (H4), así que el
contraste por segmento solo se había probado con filas sintéticas. Aquí, en UNA transacción de extreme_dba que se
revierte (con el candado de la réplica): llegan por el trigger las filas crudas de tres viajes reservados,
fn_insert_timbradas_anio liquida cada viaje y fn_consolidar_timbradas_historicas cierra. Con esas filas, que solo ve
esa transacción, corre la calidad de §6.3 y EL CONTRASTE DEL CICLO sin cambiarle nada (consolidados._contraste_de):
- la fuente son las consultas del ciclo (consolidados._SQL_FUENTE y _SQL_PRIMER_ANO) sobre la conexión de la
  transacción, porque las filas sin confirmar no se ven desde otra;
- la agregación propia es ai_frecuencias.segmento_estadistica_dia de la base LOCAL de pruebas, con el grano diario de
  las MISMAS filas de timbradas_segmentos (segmentos_refresco.SQL_FUENTE_DIA y copiar_dia: lo que materializa el
  trabajo «segmentos»), en otra transacción que también se revierte.

Resultado: las filas reales pasan la calidad sin errores y los totales cuadran. La liquidación asigna TODOS los
segmentos de un viaje al bloque de 15 minutos de su fin (como el consolidado por ruta, H10), y la agregación propia a
la hora en que el bus pasó por cada segmento. Con la hora en el grano (lo que hacía el ciclo) la mayoría de las llaves
no encuentra la agregación propia y salen diferencias groseras falsas; el contraste del ciclo, que ya no depende del
bloque de Extreme, compara todas las llaves y no da ninguna grosera. Y sigue viendo una diferencia real: con las
subidas de un segmento alteradas dentro de la misma transacción, esa llave, y solo esa, queda bloqueada.

Las pocas diferencias no bloqueantes que quedan tienen causa medida: salen solo en segmentos donde un viaje tiene dos
filas en timbradas_segmentos (pasó por el segmento en dos bloques de 15 minutos). La liquidación de Extreme deja de ese
par (segmento, viaje) los conteos de una sola de las dos filas; la agregación propia suma las dos y, si caen en horas
distintas, cuenta el viaje en cada hora.

Escribe en la réplica (y avanza sus secuencias aunque se revierta): solo corre con REPLICA_PRUEBAS_ESCRITURA=1, como
tests/replica/test_llegada.py. Con GENERAR_EVIDENCIAS=1 deja docs/evidencias/consolidados/segmentos_filas_reales.json.
"""
from __future__ import annotations

import os
import uuid
from dataclasses import replace
from datetime import datetime

import pandas as pd
import pytest

from scripts import replica_comun as rc
from tests.evidencia import guardar_evidencia

psycopg = pytest.importorskip("psycopg")
pytestmark = pytest.mark.skipif(os.environ.get("REPLICA_PRUEBAS_ESCRITURA") != "1",
                                reason="escribe en la réplica como extreme_dba (transacción revertida que avanza "
                                       "secuencias): REPLICA_PRUEBAS_ESCRITURA=1")
VIAJES = 3
PROCESO = "sobusa"
SIN_VIAJES_MINIMOS = {"contraste_viajes_minimos": 1}      # tres viajes: se comparan todas las llaves
PRUEBA = ("tests/replica/test_consolidados_segmentos.py::"
          "test_con_filas_reales_de_la_liquidacion_el_contraste_del_ciclo_no_da_groseras_falsas_h10")
# La diferencia real sembrada (dentro de la transacción que se revierte): las subidas de un segmento, alteradas
# Los segmentos donde algún viaje tiene más de una fila en timbradas_segmentos (dos bloques de 15 minutos)
SQL_EN_DOS_BLOQUES = ("SELECT id_segmento, id_viaje, count(*) AS filas FROM public.timbradas_segmentos "
                      "WHERE id_viaje = ANY(:viajes) GROUP BY id_segmento, id_viaje HAVING count(*) > 1 ORDER BY 1, 2")
SQL_ALTERAR_SUBIDAS = ("UPDATE public.{tabla} SET subidas = 3 * subidas + 10 * nro_viajes, "
                       "promedio_subidas = 3 * promedio_subidas + 10 WHERE proceso = :proceso AND id_segmento = :seg")


class _FuenteEnLaTransaccion:
    """Las consultas del ciclo a la fuente (fuente.consultar) sobre la conexión de la transacción de extreme_dba: las
    filas de la liquidación están sin confirmar y solo se ven ahí. Solo SELECT, con la validación de la fuente."""

    proceso = PROCESO

    def __init__(self, conn) -> None:
        self.conn = conn

    def consultar(self, sql: str, parametros: dict | None = None) -> pd.DataFrame:
        from sqlalchemy import text

        from app.servicios import fuentes

        fuentes.validar_solo_select(sql)
        return pd.DataFrame(self.conn.execute(text(sql), parametros or {}).mappings().all())


def _url_sa(rol: str) -> str:
    url = rc.url_rol(rol)
    if not url:
        pytest.skip(f"falta la clave de {rol}")
    return url.replace("postgresql://", "postgresql+psycopg://")


def _sin_tolerancias(resumen: dict) -> dict:
    return {k: v for k, v in resumen.items() if k != "tolerancias"}


def _por_codigo(incidencias: list[dict]) -> dict:
    """{código: {bloqueantes, no_bloqueantes}} de las incidencias del contraste."""
    salida: dict = {}
    for i in incidencias:
        conteo = salida.setdefault(i["codigo"], {"bloqueantes": 0, "no_bloqueantes": 0})
        conteo["bloqueantes" if i["bloqueante"] else "no_bloqueantes"] += 1
    return salida


def _con_la_hora_en_el_grano(consolidados, paso, filas: pd.DataFrame) -> dict:
    """Lo que hacía el ciclo antes: la misma comparación con la hora del bloque de Extreme en el grano (los días
    propios de cada llave con su hora). Deja medido por qué el grano que bloquea ya no la lleva (H10)."""
    cfg = paso.cfg
    ids = sorted(int(x) for x in filas["id_segmento"].unique())
    leido = consolidados._agregado_fuente(paso.fuente, cfg, ids)
    periodo = consolidados._periodo(paso.fuente, cfg, leido)
    propia = consolidados._agregado_propio(paso.s, consolidados._SQL_PROPIA_POR_HORA[cfg.nombre], cfg.grano_rango, ids,
                                           periodo)
    por_hora = replace(cfg, grano=cfg.grano_rango)
    ext = leido.drop(columns=["marca"])
    consolidados._dias_propios(ext, por_hora, propia, consolidados.ano_abierto(leido) if cfg.por_ano else None)
    r = consolidados.contrastar(ext, propia, por_hora, paso.tolerancias, "prueba_segmentos", PROCESO)
    return _sin_tolerancias(r.resumen)


def _diferencia_sembrada(consolidados, conn, paso, filas: pd.DataFrame) -> dict:
    """Altera las subidas del segmento con más viajes (en la transacción que se revierte) y vuelve a correr el contraste
    del ciclo: la diferencia real debe salir grosera y bloquear esa llave, y ninguna otra."""
    from sqlalchemy import text

    tabla = paso.cfg.nombre
    segmento = int(filas.groupby("id_segmento")["nro_viajes"].sum().sort_values(kind="stable").index[-1])
    conn.execute(text(SQL_ALTERAR_SUBIDAS.format(tabla=tabla)), {"proceso": PROCESO, "seg": segmento})
    r = consolidados._contraste_de(paso, filas)
    bloqueantes = [i for i in r.incidencias if i["bloqueante"]]
    return {"segmento": segmento, "cambio": "subidas = 3 × subidas + 10 × nro_viajes",
            "groseras": r.resumen["groseras"], "llaves_bloqueadas": r.resumen["llaves_bloqueadas"],
            "segmentos_bloqueados": sorted({i["llave"]["id_segmento"] for i in bloqueantes}),
            "campos": sorted({i["campo"] for i in bloqueantes}), "codigos": sorted({i["codigo"] for i in bloqueantes}),
            "llave_con_hora": any("hora" in i["llave"] for i in bloqueantes)}


def _tabla(consolidados, calidad, conn, paso, del_dia: pd.DataFrame, catalogos: dict) -> dict:
    """Calidad de §6.3 y contraste del ciclo de una tabla por segmento con las filas reales de la transacción."""
    from sqlalchemy import text

    cfg = paso.cfg
    filas = pd.DataFrame(conn.execute(text(f"SELECT * FROM public.{cfg.nombre} "  # noqa: S608 - constante
                                           "WHERE proceso = :proceso"), {"proceso": PROCESO}).mappings().all())
    validas, errores = calidad.validar_lote(filas[[c for c in filas.columns if not c.startswith("id_timbrada")]],
                                            "prueba_segmentos", esquema=cfg.esquema, catalogos=catalogos)
    ids = sorted(int(x) for x in filas["id_segmento"].unique())
    propias = del_dia[del_dia["id_segmento"].isin(ids)]
    r = consolidados._contraste_de(paso, filas)
    por_defecto = consolidados._contraste_de(replace(paso, tolerancias={}), filas)
    return {
        "filas_de_sobusa": len(filas), "validas": len(validas), "errores_de_calidad": len(errores),
        "segmentos": len(ids), "bloques_hora_inicio": sorted(str(b) for b in set(filas["hora_inicio"])),
        "horas_de_paso_propias": sorted(int(h) for h in set(propias["hora"])),
        "viajes_segmento": {"extreme": float(filas["nro_viajes"].sum()), "propia": float(propias["nro_viajes"].sum())},
        "subidas": {"extreme": float(filas["subidas"].sum()), "propia": float(propias["suma_subidas"].sum())},
        "contraste_del_ciclo": _sin_tolerancias(r.resumen), "incidencias_por_codigo": _por_codigo(r.incidencias),
        "segmentos_con_diferencias": sorted({i["llave"]["id_segmento"] for i in r.incidencias
                                             if i["codigo"] == cfg.codigo}),
        "con_las_tolerancias_por_defecto": {k: por_defecto.resumen[k] for k in ("llaves", "comparadas", "pocos_viajes",
                                                                                "diferencias", "groseras")},
        "con_la_hora_en_el_grano": _con_la_hora_en_el_grano(consolidados, paso, filas),
        "diferencia_sembrada": _diferencia_sembrada(consolidados, conn, paso, filas)}


def _liquidar(conn, sim) -> tuple[list[int], pd.DataFrame, list]:
    """Llegada por el trigger de los viajes reservados, liquidación de cada uno y cierre, en la transacción de `conn`.
    Devuelve los viajes, sus filas crudas y el fin de cada viaje."""
    from sqlalchemy import text

    cur = conn.connection.cursor()
    viajes = sim.elegir_viajes(cur, VIAJES)
    crudas = sim.filas_muestra(viajes)
    columnas = [c for c in sim.columnas_conteo(cur) if c in crudas.columns]
    valores = [{c: (None if pd.isna(v) else (v.item() if hasattr(v, "item") else v)) for c, v in f.items()}
               for f in crudas[columnas].to_dict("records")]
    conn.execute(text(f"INSERT INTO public.conteo_pasajeros ({', '.join(columnas)}) "  # noqa: S608
                      f"VALUES ({', '.join(':' + c for c in columnas)})"), valores)
    liquidados = [bool(conn.execute(text("SELECT public.fn_insert_timbradas_anio(:v)"), {"v": v}).scalar())
                  for v in viajes]
    assert liquidados == [True] * VIAJES
    assert conn.execute(text("SELECT public.fn_consolidar_timbradas_historicas()")).scalar() is True
    fines = conn.execute(text("SELECT idprogramacion, coalesce(fecha_fin_liquidacion, fechafin) FROM progvehiculos "
                              "WHERE idprogramacion = ANY(:v) ORDER BY 1"), {"v": viajes}).all()
    return viajes, crudas, fines


def _grano_diario(conn, s, crudas: pd.DataFrame, segmentos_refresco) -> pd.DataFrame:
    """El grano diario de las filas de timbradas_segmentos de la transacción (lo que lee el trabajo «segmentos»),
    copiado a segmento_estadistica_dia de la base local en la transacción de `s`, que el llamador revierte. Antes saca
    de esa tabla lo que tuviera de esos segmentos: los dos lados deben salir de las mismas filas."""
    from sqlalchemy import text

    fechas = sorted({pd.Timestamp(x).date() for x in crudas["fecha"]})
    lineas = conn.execute(text(segmentos_refresco.SQL_FUENTE_DIA),
                          {"desde": fechas[0], "hasta": fechas[-1], "idruta": None}).scalars().all()
    dia = pd.DataFrame([linea.split(",") for linea in lineas], columns=list(segmentos_refresco.COLUMNAS_DIA))
    for columna in ("id_segmento", "hora", "nro_viajes", "suma_subidas"):
        dia[columna] = pd.to_numeric(dia[columna])
    s.execute(text("DELETE FROM ai_frecuencias.segmento_estadistica_dia WHERE id_segmento = ANY(:ids)"),
              {"ids": sorted(int(x) for x in dia["id_segmento"].unique())})
    assert segmentos_refresco.copiar_dia(s, pd.DataFrame({"linea": lineas}), None) == len(lineas) > 0
    return dia


def test_con_filas_reales_de_la_liquidacion_el_contraste_del_ciclo_no_da_groseras_falsas_h10(cargada, admin):
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import Session

    from app.servicios import calidad, consolidados, segmentos_refresco
    from app.servicios.fuentes import FuentePostgresSoloLectura
    from scripts import replica_simular_llegada as sim
    from tests.integracion import conftest as base_local

    lector = FuentePostgresSoloLectura(url=_url_sa("lector_ia"))
    catalogos = calidad.catalogos_desde_fuente(lector)
    lector._engine().dispose()
    base_local._alembic("upgrade", "head")
    # sesión explícita sobre la base LOCAL de pruebas (como tests/replica/test_consolidados.py): nunca otra base
    propia = create_engine(base_local.requerir_base(), connect_args={"options": "-c timezone=America/Bogota"})
    motor = create_engine(_url_sa("extreme_dba"), pool_size=1, max_overflow=0)
    informe: dict = {"prueba": PRUEBA, "generado": datetime.now().astimezone().isoformat(timespec="seconds"),
                     "metodo": ("una transacción de extreme_dba que se revierte: llegada por el trigger, "
                                "fn_insert_timbradas_anio por viaje y fn_consolidar_timbradas_historicas; calidad de "
                                "§6.3 y el contraste del ciclo (consolidados._contraste_de) con las consultas del "
                                "ciclo sobre esa transacción y, como agregación propia, segmento_estadistica_dia de la "
                                "base local con el grano diario de las mismas filas de timbradas_segmentos "
                                "(segmentos_refresco.SQL_FUENTE_DIA y copiar_dia, en otra transacción que se "
                                "revierte); contraste_viajes_minimos = 1"),
                     "tablas": {}}
    with sim.candado(admin, espera_s=600), motor.connect() as conn, Session(propia) as s:
        tx = conn.begin()
        try:
            viajes, crudas, fines = _liquidar(conn, sim)
            bloques_de_fin = {(f.replace(minute=15 * (f.minute // 15), second=0, microsecond=0)).time()
                              for _, f in fines}
            dia = _grano_diario(conn, s, crudas, segmentos_refresco)
            en_dos_bloques = conn.execute(text(SQL_EN_DOS_BLOQUES), {"viajes": viajes}).mappings().all()
            for tabla in (consolidados.TABLA_SEGMENTOS_ANIO, consolidados.TABLA_SEGMENTOS):
                paso = consolidados.Paso(consolidados.CONFIG[tabla], _FuenteEnLaTransaccion(conn), s, uuid.uuid4(),
                                         SIN_VIAJES_MINIMOS, catalogos, [], datetime.now())
                informe["tablas"][tabla] = _tabla(consolidados, calidad, conn, paso, dia, catalogos)
        finally:
            tx.rollback()
            s.rollback()
    motor.dispose()
    propia.dispose()
    dos_bloques = sorted({int(f["id_segmento"]) for f in en_dos_bloques})
    informe.update(viajes=viajes, filas_crudas=len(crudas), fin_de_los_viajes=[f"{v}: {f}" for v, f in fines],
                   bloques_del_fin=sorted(str(b) for b in bloques_de_fin),
                   segmentos_con_un_viaje_en_dos_bloques={
                       "segmentos": dos_bloques, "pares_segmento_viaje": len(en_dos_bloques),
                       "nota": ("un viaje con dos filas en timbradas_segmentos para el mismo segmento (dos bloques de "
                                "15 minutos): la liquidación de Extreme deja los conteos de una sola de las dos filas; "
                                "la agregación propia suma las dos y, si caen en horas distintas, cuenta el viaje en "
                                "cada hora. Las diferencias no bloqueantes del contraste salen solo en estos "
                                "segmentos")})
    with admin.cursor() as cur:                                      # revertido: la réplica no cambió (H4)
        cur.execute("SELECT (SELECT count(*) FROM public.timbradas_segmentos_anio), "
                    "(SELECT count(*) FROM public.timbradas_segmentos_consolidado), "
                    "(SELECT count(*) FROM public.timbradas_segmentos WHERE id_viaje = ANY(%s))", (viajes,))
        assert cur.fetchone() == (0, 0, 0)
    for tabla, t in informe["tablas"].items():
        # §6.3 sin falsos errores con filas reales, y los totales de los dos lados cuadran (±2 %)
        assert t["filas_de_sobusa"] > 0 and t["validas"] == t["filas_de_sobusa"] and t["errores_de_calidad"] == 0, tabla
        for medida in ("viajes_segmento", "subidas"):
            assert t[medida]["extreme"] == pytest.approx(t[medida]["propia"], rel=0.02), (tabla, medida)
        # H10 por segmento: la liquidación pone cada viaje en el bloque de su fin; lo propio, en la hora de paso
        assert {datetime.strptime(b, "%H:%M:%S").time() for b in t["bloques_hora_inicio"]} <= bloques_de_fin, tabla
        assert len(t["horas_de_paso_propias"]) > len({b[:2] for b in t["bloques_hora_inicio"]}), tabla
        # el contraste del ciclo no depende del bloque de Extreme: compara todas las llaves y no da ninguna grosera
        ciclo, antes = t["contraste_del_ciclo"], t["con_la_hora_en_el_grano"]
        assert "hora" not in ciclo["grano"] and ciclo["sin_agregacion_propia"] == 0, (tabla, ciclo)
        assert ciclo["comparadas"] == ciclo["llaves"] == t["segmentos"] > 0, (tabla, ciclo)
        assert ciclo["groseras"] == 0 and ciclo["llaves_bloqueadas"] == 0, (tabla, ciclo)
        assert all(c["bloqueantes"] == 0 for c in t["incidencias_por_codigo"].values()), (tabla, t)
        # las diferencias no bloqueantes que quedan salen solo donde un viaje tiene dos filas del mismo segmento
        assert set(t["segmentos_con_diferencias"]) <= set(dos_bloques) and dos_bloques, (tabla, t, dos_bloques)
        # por hora solo queda el rango, que no bloquea: la mayoría de los bloques de Extreme no tiene esa hora propia
        hora = ciclo["por_hora"]
        assert hora["grano"] == [*ciclo["grano"], "hora"] and hora["sin_agregacion_propia"] > 0, (tabla, hora)
        assert hora["fuera_de_rango"] == t["incidencias_por_codigo"].get("CONTR-003", {}).get("no_bloqueantes", 0)
        # lo de antes, con la hora en el grano: llaves sin agregación propia y diferencias groseras FALSAS
        assert antes["sin_agregacion_propia"] > 0 and antes["groseras"] > 0 and antes["llaves_bloqueadas"] > 0, tabla
        # con las tolerancias por defecto (30 viajes) tres viajes no alcanzan para comparar nada
        assert t["con_las_tolerancias_por_defecto"]["comparadas"] == 0, tabla
        # y la diferencia real sembrada sale grosera y bloquea su llave, sin la hora, y ninguna otra
        sembrada = t["diferencia_sembrada"]
        assert sembrada["segmentos_bloqueados"] == [sembrada["segmento"]], (tabla, sembrada)
        assert sembrada["groseras"] >= 1, (tabla, sembrada)
        assert sembrada["codigos"] == ["CONTR-002"] and "promedio_subidas" in sembrada["campos"], (tabla, sembrada)
        assert sembrada["llaves_bloqueadas"] == 1 and sembrada["llave_con_hora"] is False, (tabla, sembrada)
    guardar_evidencia("consolidados/segmentos_filas_reales.json", informe)
