"""scripts/replica_indices_candidatos.py (§8.3, H12): cada índice candidato se mide dentro de una transacción que se
revierte (nunca se confirma), la decisión sigue el criterio declarado y la propuesta para el DBA sale de una sola
fuente (la misma de scripts/replica_explain.py). Sin base: la conexión es un doble que registra las sentencias."""
from __future__ import annotations

import re

from scripts import replica_explain as rx
from scripts import replica_indices_candidatos as R


def _plan(ms: float, indice: str | None = None) -> list[dict]:
    hoja = {"Node Type": "Index Scan" if indice else "Seq Scan", "Relation Name": "timbradas_segmentos",
            "Shared Hit Blocks": 1, "Shared Read Blocks": 0}
    if indice:
        hoja["Index Name"] = indice
    return [{"Plan": {"Node Type": "Limit", "Actual Rows": 0, "Plans": [hoja]}, "Execution Time": ms,
             "Planning Time": 0.1}]


class _Resultado:
    def __init__(self, valor):
        self.valor = valor

    def scalar(self):
        return self.valor

    def one(self):
        return (True, False, 1024 * 1024)


class _Conexion:
    """Registra las sentencias; el EXPLAIN tarda `ms_sin` antes del CREATE INDEX y `ms_con` después."""

    def __init__(self, ms_sin: float, ms_con: float, indice: str):
        self.sentencias, self.creado, self.revertida, self.confirmada = [], False, False, False
        self.ms_sin, self.ms_con, self.indice = ms_sin, ms_con, indice

    def exec_driver_sql(self, sql, params=None):
        self.sentencias.append(sql)
        if sql.startswith("CREATE INDEX"):
            self.creado = True
        if sql.startswith("EXPLAIN"):
            return _Resultado(_plan(self.ms_con, self.indice) if self.creado else _plan(self.ms_sin))
        return _Resultado(None)

    def rollback(self):
        self.revertida = True

    def commit(self):  # pragma: no cover - si se llamara, la prueba lo detecta
        self.confirmada = True

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class _Motor:
    def __init__(self, conexion):
        self.conexion = conexion

    def connect(self):
        return self.conexion


def test_cada_escenario_es_una_transaccion_que_se_revierte():
    cand = next(c for c in R.CANDIDATOS if c.nombre == "ix_ia_timbradas_segmentos_ultimaactualizacion")
    consulta = R.Consulta("segmentos_ventana_sin_novedades", "ventana", "segmentos_refresco", "SELECT 1", {})
    cx = _Conexion(120.0, 0.02, cand.nombre)
    r = R.medir_escenario(_Motor(cx), cand.nombre, [cand], [consulta])
    assert cx.revertida and not cx.confirmada                     # el índice muere con el ROLLBACK
    assert cx.sentencias[:3] == ["SET LOCAL lock_timeout = '2s'", f"SET LOCAL statement_timeout = "
                                 f"{R.TIEMPO_MAXIMO_MS}", "SET LOCAL TimeZone = 'America/Bogota'"]
    assert cand.ddl in cx.sentencias and "CONCURRENTLY" not in cand.ddl     # no cabe dentro de una transacción
    assert not any(s.upper().startswith(("ANALYZE", "COMMIT", "DROP")) for s in cx.sentencias)
    comparacion = R.comparar(r)
    assert comparacion["segmentos_ventana_sin_novedades"]["usa_indice"] and R.respalda(comparacion)
    assert r["creados"][cand.nombre] == {"segundos": r["creados"][cand.nombre]["segundos"], "valido": True,
                                         "indcheckxmin": False, "mb": 1.0}


def _comparacion(ms_sin: float, ms_con: float, usa: bool = True) -> dict:
    return {"ms_sin": ms_sin, "ms_con": ms_con, "ahorro_ms": ms_sin - ms_con, "mejora": 1 - ms_con / ms_sin,
            "usa_indice": usa, "escaneos_con": ["Index Scan t ix_ia_x"] if usa else ["Seq Scan t"]}


def test_el_criterio_exige_mejora_ahorro_uso_y_ningun_empeoramiento():
    assert R.respalda({"a": _comparacion(870, 125)})
    assert not R.respalda({"a": _comparacion(870, 125, usa=False)})                   # el plan no lo usa
    assert not R.respalda({"a": _comparacion(4.6, 2.7)})                              # ahorro menor de 10 ms
    assert not R.respalda({"a": _comparacion(279, 231)})                              # mejora menor de 30 %
    assert not R.respalda({"a": _comparacion(870, 125), "b": _comparacion(1541, 1791)})   # otra empeora 16 %
    assert not R.respalda({})


def test_un_indice_se_respalda_solo_o_con_los_que_se_usan_junto():
    combinado = {"escenario": "lectura_incremental_1_2_3", "respaldado": True,
                 "indices": ["ix_ia_timbradas_segmentos_id_viaje", "ix_ia_progvehiculos_ruta_hora_salida"],
                 "comparacion": {"viajes_de_una_ruta": dict(_comparacion(877, 9.7), escaneos_con=[
                     "Bitmap Index Scan  ix_ia_progvehiculos_ruta_hora_salida",
                     "Index Only Scan timbradas_segmentos ix_ia_timbradas_segmentos_id_viaje"])}}
    solo = {"escenario": "ix_ia_progvehiculos_ruta_hora_salida", "respaldado": False,
            "indices": ["ix_ia_progvehiculos_ruta_hora_salida"],
            "comparacion": {"viajes_de_una_ruta": _comparacion(923, 788)}}
    decision = {d["indice"]: d for d in R.decision({"escenarios": [solo, combinado]})}
    tres = decision["ix_ia_progvehiculos_ruta_hora_salida"]
    assert tres["respaldado_por_la_medicion"] and tres["escenarios_que_lo_respaldan"] == ["lectura_incremental_1_2_3"]
    assert decision["ix_ia_timbradas_segmentos_fecha"]["respaldado_por_la_medicion"] is None      # no se midió
    assert all(d["nota"] for d in decision.values())


def test_el_informe_de_explain_nombra_la_propuesta_aplicada_y_las_condiciones():
    """explain_incremental.txt dice qué índices de la propuesta se aplicaron (tabla y columnas), que se borraron todos y
    en qué condiciones se midió; un informe sin esos datos (anterior) se sigue escribiendo."""
    nombres = rx._indices_propuestos()
    medida = {"filas": 0, "ms_ejecucion": 0.01, "escaneos": ["Seq Scan timbradas_segmentos_anio"], "texto": "plan"}
    volumen = {"timbradas_segmentos_filas": 10, "tamano_mb": 1.0, "viajes_con_segmentos": 1, "filas_por_viaje": 10.0,
               "dias_con_datos": 1, "progvehiculos_viajes": 1, "progvehiculos_periodo": "2023-01-01 a 2023-01-01",
               "filas_proyectadas_historico_completo": 10, "filas_por_dia": 10,
               "fraccion_leida_por_ejecucion_diaria": 1.0}
    inf = {"generado_en": "2026-11-11T04:44:45-05:00", "rol_indices": "extreme_dba", "volumen": volumen,
           "indices_previos": [], "indices_aplicados_s": dict.fromkeys(nombres, 0.01), "indices_borrados": nombres,
           "sesiones_ajenas_al_empezar": 0, "nota_medicion": "equipo sin otras suites de pruebas",
           "antes": {"timbradas_segmentos_anio": medida}, "despues": {"timbradas_segmentos_anio": medida}}
    texto = rx._texto(inf)
    assert ("ix_ia_timbradas_segmentos_anio_proceso_marca · timbradas_segmentos_anio (proceso, ultima_actualizacion)"
            in texto)
    assert "ix_ia_progvehiculos_ruta_hora_salida · progvehiculos (idruta, (date_trunc('hour', fechasalida)))" in texto
    assert all(f"   {n} · " in texto for n in nombres)
    assert f"Índices ix_ia_* antes de medir: ninguno · borrados al terminar: {len(nombres)} de {len(nombres)}" in texto
    assert "Sesiones de otros clientes en la réplica al empezar: 0" in texto
    assert "Condiciones de la medición: equipo sin otras suites de pruebas" in texto
    anterior = {k: v for k, v in inf.items() if k not in ("indices_aplicados_s", "indices_borrados",
                                                          "sesiones_ajenas_al_empezar", "nota_medicion")}
    assert "== Propuesta aplicada" not in rx._texto(anterior)


def test_la_propuesta_sale_de_una_sola_fuente_y_es_la_de_replica_explain():
    sql = R.propuesta_sql()
    assert sql == rx.PROPUESTA_SQL
    assert ";" not in "".join(linea for linea in sql.splitlines() if linea.strip().startswith("--"))
    nombres = re.findall(r"IF NOT EXISTS (\w+)", sql)
    propuestos = [c.nombre for c in R.CANDIDATOS if c.propuesto] + [n for n, _t, _c, _m in R.OTROS_CONSOLIDADOS]
    assert nombres == propuestos == rx._indices_propuestos()
    assert all(len(n) <= 63 for n in nombres)                       # sin truncar (límite de identificadores)
    assert "ix_ia_timbradas_segmentos_fecha" not in nombres and "ix_ia_progvehiculos_ruta_fechasalida" not in nombres
    # las tablas por segmento (sin filas de Sobusa, de otros operadores en Extreme, H4): por proceso y marca
    for tabla in ("timbradas_segmentos_anio", "timbradas_segmentos_consolidado"):
        assert f"ON public.{tabla} (proceso, ultima_actualizacion);" in sql
    assert all(len(linea) <= 120 for linea in sql.splitlines())
    assert all(re.fullmatch(r"ix_ia_\w+", c.nombre) and c.ddl.startswith(f"CREATE INDEX {c.nombre} ON public.")
               for c in R.CANDIDATOS)
    # la medición de la propuesta entera crea esos mismos índices, sin CONCURRENTLY (no cabe en una transacción)
    enteros = R.indices_de_la_propuesta()
    assert [n for n, _ddl in enteros] == nombres
    assert all(ddl.startswith(f"CREATE INDEX {n} ON public.") and "CONCURRENTLY" not in ddl for n, ddl in enteros)
    assert {t for t in R.TABLAS_DE_LA_PROPUESTA} == set(re.findall(r"ON public\.(\w+) ", sql))


# ---------------------------------------------------------------- la propuesta entera, con ANALYZE
REFERENCIA = "demanda_segmentos_bloque" + R.CON_UNION_FINAL


def test_la_propuesta_entera_se_mide_con_analyze_en_los_dos_lados_y_se_revierte():
    """Un índice que solo no cambia un plan puede cambiarlo junto con los demás y con las estadísticas al día: toda la
    propuesta, todas las consultas y ANALYZE antes y después de crear los índices, en UNA transacción que se
    revierte."""
    consultas = [R.Consulta("demanda_segmentos_bloque", "bloque", "fuentes", "SELECT 1", {}),
                 R.Consulta(REFERENCIA, "la de antes", "formulación anterior", "SELECT 2", {}, referencia=True)]
    cx = _Conexion(3500.0, 1500.0, "ix_ia_timbradas_segmentos_id_viaje")
    r = R.medir_propuesta_entera(_Motor(cx), consultas)
    assert cx.revertida and not cx.confirmada                 # los índices y las estadísticas mueren con el ROLLBACK
    hechas = [s for s in cx.sentencias if not s.startswith("SELECT i.indisvalid")]
    analyze = [f"ANALYZE public.{t}" for t in R.TABLAS_DE_LA_PROPUESTA]
    ddl = [d for _n, d in R.indices_de_la_propuesta()]
    explain = [f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {c.sql}" for c in consultas for _ in range(R.REPETICIONES)]
    assert hechas[3:] == [*analyze, *explain, *ddl, *analyze, *explain]
    assert len(ddl) == 7 and not any(s.upper().startswith(("COMMIT", "DROP")) for s in hechas)
    assert r["escenario"] == R.ENTERA and r["indices"] == [n for n, _d in R.indices_de_la_propuesta()]
    assert r["referencias"] == [REFERENCIA] and r["analyze"] == list(R.TABLAS_DE_LA_PROPUESTA)
    assert set(r["creados"]) == set(r["indices"]) and "error" not in r and r["omitidos"] == []
    comparacion = R.comparar(r)
    assert comparacion["demanda_segmentos_bloque"]["mejora"] == round(1 - 1500 / 3500, 3)
    assert comparacion["demanda_segmentos_bloque"]["descartadas_por_union_con"] == 0


def test_la_misma_medicion_sin_el_indice_3_dice_cual_cambia_el_plan():
    """Para saber qué índice cambia un plan, la propuesta entera se mide también sin el índice sobre la expresión de la
    hora de salida: los otros seis, con ANALYZE en los dos lados, en otra transacción que se revierte."""
    consultas = [R.Consulta(k, k, "fuentes", "SELECT 1", {}, referencia=k.endswith(R.CON_UNION_FINAL))
                 for k in R.CONSULTAS_DEL_INDICE_3]
    cx = _Conexion(810.0, 91.0, "ix_ia_timbradas_segmentos_id_viaje")
    r = R.medir_propuesta_entera(_Motor(cx), consultas, sin=(R.INDICE_3,))
    creados = [s for s in cx.sentencias if s.startswith("CREATE INDEX")]
    assert cx.revertida and len(creados) == 6 and not any(R.INDICE_3 in s for s in creados)
    assert r["escenario"] == R.SIN_EL_3 and r["omitidos"] == [R.INDICE_3] and R.INDICE_3 not in r["indices"]
    assert r["referencias"] == [REFERENCIA] and REFERENCIA in R.CONSULTAS_DEL_INDICE_3
    assert R.INDICE_3 in [n for n, _d in R.indices_de_la_propuesta()]       # sigue en la propuesta


def _medida(ms_sin: float, ms_con: float, union: int = 0) -> dict:
    return {**_comparacion(ms_sin, ms_con), "descartadas_por_union_sin": 0, "descartadas_por_union_con": union}


def test_el_criterio_de_ningun_empeoramiento_se_evalua_con_la_propuesta_entera():
    """Lo que la medición de cada índice por separado no veía: con la propuesta entera y ANALYZE, la lectura del bloque
    pasaba de 3,5 a 9,3 s. El veredicto nombra las lecturas de la API que empeoran más de 15 %; la formulación anterior
    (referencia) y el ruido de centésimas de milisegundo no cuentan."""
    entera = {"referencias": [REFERENCIA], "comparacion": {
        "demanda_segmentos_bloque": _medida(3500, 1500), "viajes_de_una_ruta": _medida(810, 9),
        # la ocupación actual ya descartaba filas en su unión sin los índices: no es algo que traiga la propuesta
        "ocupacion_actual": {**_medida(697, 712, union=2_950_340), "descartadas_por_union_sin": 2_950_340},
        "consolidado_sin_novedades": _medida(0.01, 0.03),
        REFERENCIA: _medida(3500, 9300, union=87_967_780)}}
    assert R.veredicto_de_la_propuesta(entera) == {
        "medida": True, "sin_empeoramiento": True, "empeoran": [],
        "mejoran": ["demanda_segmentos_bloque", "viajes_de_una_ruta"], "con_filtro_de_union": []}
    assert R.empeora(entera["comparacion"][REFERENCIA])                              # empeora, pero es referencia
    assert not R.empeora(entera["comparacion"]["consolidado_sin_novedades"])        # −200 %, pero 0,02 ms: ruido
    assert not R.empeora(entera["comparacion"]["ocupacion_actual"])                 # 2 %
    mala = {"referencias": [], "comparacion": {"demanda_segmentos_bloque": _medida(3561.5, 9264.2, 87_967_780),
                                              "viajes_de_una_ruta": _medida(810, 9)}}
    veredicto = R.veredicto_de_la_propuesta(mala)
    assert veredicto["sin_empeoramiento"] is False and veredicto["empeoran"] == ["demanda_segmentos_bloque"]
    assert veredicto["con_filtro_de_union"] == ["demanda_segmentos_bloque"]
    # un índice solo tampoco se respalda si otra de sus consultas empeora así
    assert not R.respalda(mala["comparacion"]) and R.respalda({"a": _medida(810, 9)})
    for sin_medir in (None, {}, {"error": "otro escritor tiene el candado"}):
        assert R.veredicto_de_la_propuesta(sin_medir)["sin_empeoramiento"] is None


def test_el_informe_trae_la_propuesta_entera_y_dice_si_alguna_lectura_empeora():
    entera = {"indices": [n for n, _d in R.indices_de_la_propuesta()], "analyze": list(R.TABLAS_DE_LA_PROPUESTA),
              "referencias": [REFERENCIA],
              "comparacion": {"demanda_segmentos_bloque": _medida(3532.1, 1539.8),
                              REFERENCIA: _medida(3532.1, 9334.5, union=87_967_780)}}
    texto = "\n".join(R._informe_entera({R.ENTERA: entera}))
    assert "## La propuesta entera, con las estadísticas al día (ANALYZE)" in texto
    assert "CREATE INDEX de los 7 índices de la propuesta; ANALYZE otra vez" in texto
    assert "| demanda_segmentos_bloque | 3.532,1 | 1.539,8 | 56 % | 0 → 0 | no |" in texto
    assert f"| {REFERENCIA} (referencia) | 3.532,1 | 9.334,5 | −164 % | 0 → 87.967.780 | sí |" in texto
    assert "**Ninguna lectura de la API empeora** más de 15 %" in texto and "`demanda_segmentos_bloque`" in texto
    assert "no es una lectura de la API" in texto and "ya no vuelve a unir `rutas`" in texto
    entera["referencias"] = []                                    # si esa lectura fuera de la API, el informe lo diría
    malo = "\n".join(R._informe_entera({R.ENTERA: entera}))
    assert f"**Con la propuesta entera empeoran más de 15 %: `{REFERENCIA}`.**" in malo and "NO se cumple" in malo
    assert f"sin ella no descartaba, en: `{REFERENCIA}`." in malo
    assert R._informe_entera({}) == []                             # un informe anterior, sin esa medición
    assert "No se pudo medir: candado." in "\n".join(R._informe_entera({R.ENTERA: {"error": "candado"}}))
    # con la medición sin el índice 3, el informe dice cuál cambia el plan y qué se perdería sin él
    entera["referencias"] = [REFERENCIA]
    entera["comparacion"] |= {"viajes_de_una_ruta": _medida(819.2, 9.4), "demanda_segmentos_sin_novedades": _medida(
        166.2, 0.1)}
    sin_3 = {"indices": [n for n, _d in R.indices_de_la_propuesta(sin=(R.INDICE_3,))], "referencias": [REFERENCIA],
             "comparacion": {REFERENCIA: _medida(3600.0, 3438.2), "viajes_de_una_ruta": _medida(810.0, 90.9),
                             "demanda_segmentos_sin_novedades": _medida(160.0, 46.0)}}
    con_sin_3 = "\n".join(R._informe_entera({R.ENTERA: entera, R.SIN_EL_3: sin_3}))
    assert "### La misma medición sin el índice 3" in con_sin_3
    assert f"los 6 índices de la propuesta menos `{R.INDICE_3}`:" in con_sin_3
    assert f"| {REFERENCIA} (referencia) | 3.600,0 | 3.438,2 | 4 % | 0 → 0 | no |" in con_sin_3
    assert "la formulación anterior del bloque, 3.438,2 ms sin el índice 3 frente a 9.334,5 ms con la propuesta" in (
        con_sin_3)
    assert "los viajes de una ruta y un día (§5.3), 90,9 ms sin el índice 3 frente a 9,4 ms" in con_sin_3
    assert "la lectura sin novedades de cada ciclo, 46,0 ms sin el índice 3 frente a 0,1 ms" in con_sin_3
    assert "el índice sigue en la propuesta y lo que se corrigió fue la lectura" in con_sin_3


def test_la_formulacion_anterior_de_la_lectura_solo_se_mide_como_referencia():
    """La lectura compuesta ya no vuelve a unir rutas al final. El script arma la formulación anterior (con esa unión)
    solo para medirla de referencia en la propuesta entera; es un SELECT de la lista blanca como la de hoy."""
    from app.servicios import fuentes

    hoy = fuentes._SQL_DEMANDA_SEGMENTOS.format(filtro_hasta="", filtro_rutas="")
    antes = R.con_union_final_de_rutas(hoy)
    union = "JOIN rutas r ON r.idruta = v.idruta"
    assert union in antes and union not in hoy and antes.count("JOIN rutas r") == 2
    assert "SELECT r.nombre AS ruta, v.idruta, v.proceso, r.idempresa," in antes
    assert "r.nombre, r.idempresa" not in antes.split("), viajes AS (")[0]
    assert fuentes.validar_solo_select(antes) and antes.count(":marca") == hoy.count(":marca") == 1
    try:
        R.con_union_final_de_rutas(antes)
    except ValueError as exc:
        assert "UNION_FINAL_DE_RUTAS" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("la formulación anterior no se puede volver a transformar")
