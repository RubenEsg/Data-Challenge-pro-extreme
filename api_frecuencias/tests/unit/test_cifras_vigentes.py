"""scripts/cifras_vigentes.py: el total combinado de alertas por ruta y día (observadas + pronóstico, §18 «Alertas
excesivas») sale de los dos backtests y, si falta uno, dice «sin evidencia» (nunca inventa un valor). Las cifras del
ciclo intradía (§10.1, 10.1-d) salen de ocupacion/ciclo_intradia_fuente.json y ocupacion/planificador_intradia.json,
con «sin evidencia» si falta el archivo o un campo."""
from __future__ import annotations

import json

import pytest

from scripts import cifras_vigentes as CV

TOTAL = "Alertas por ruta y día para el operador, observadas + pronóstico (15-sep a 31-dic-2025)"
PERIODO = ["2025-09-15", "2025-12-31"]


def _escribir(raiz, rel: str, contenido: dict) -> None:
    p = raiz / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(contenido), encoding="utf-8")


def _pronostico(alertas: dict[str, int], dias_ruta: int = 324, periodo=PERIODO) -> dict:
    return {"dias_ruta": dias_ruta, "periodo": periodo,
            "variantes": {"franja": {"por_codigo": {c: {"alertas": n, "por_ruta_dia": round(n / dias_ruta, 3),
                                                        "lift": 1.5} for c, n in alertas.items()}}}}


def _fila(nombre: str) -> tuple[str, str, str]:
    return next(f for f in CV.cifras() if f[0] == nombre)


@pytest.fixture
def evidencia(tmp_path, monkeypatch):
    monkeypatch.setattr(CV, "EVID", tmp_path)
    return tmp_path


def test_el_total_suma_las_observadas_y_las_de_pronostico_con_sus_conteos(evidencia):
    _escribir(evidencia, "alertas/backtest_alertas.json",
              {"periodo": PERIODO, "por_defecto": {"observadas_por_ruta_dia": 1.265}})
    _escribir(evidencia, "alertas/backtest_alertas_pronostico.json",
              _pronostico({"ALT-001": 141, "ALT-002": 102, "ALT-003": 123, "ALT-004": 10}))
    _n, valor, rel = _fila(TOTAL)
    # 376 / 324 = 1,160 (no la suma de los cuatro valores redondeados, 1,161)
    assert valor == "2,425 (1,265 observadas + 1,160 de pronóstico)"
    assert rel == "alertas/backtest_alertas.json y alertas/backtest_alertas_pronostico.json"
    assert CV._rutas(rel, "docs/evidencias/", "{}") == ("docs/evidencias/alertas/backtest_alertas.json y "
                                                         "docs/evidencias/alertas/backtest_alertas_pronostico.json")


def test_sin_uno_de_los_dos_backtests_no_hay_total(evidencia):
    _escribir(evidencia, "alertas/backtest_alertas.json", {"por_defecto": {"observadas_por_ruta_dia": 1.265}})
    assert _fila(TOTAL)[1] == CV.SIN
    _escribir(evidencia, "alertas/backtest_alertas_pronostico.json", _pronostico({"ALT-001": 141, "ALT-002": 102}))
    assert _fila(TOTAL)[1] == CV.SIN                                  # le faltan códigos: tampoco se inventa


def test_el_total_dice_si_los_periodos_no_coinciden(evidencia):
    _escribir(evidencia, "alertas/backtest_alertas.json",
              {"periodo": ["2025-01-15", "2025-12-31"], "por_defecto": {"observadas_por_ruta_dia": 0.5}})
    _escribir(evidencia, "alertas/backtest_alertas_pronostico.json",
              _pronostico({"ALT-001": 3, "ALT-002": 3, "ALT-003": 3, "ALT-004": 3}, dias_ruta=12))
    assert _fila(TOTAL)[1].startswith("1,500 (0,500 observadas + 1,000 de pronóstico; periodos distintos")


INTRADIA = ("Ciclo intradía (PLAN_INTRADIA_CRON) en la réplica: lectura de la fuente por ciclo y fracción de la hora; "
            "todos los ciclos del día")
DIARIO = "Ciclo diario en la réplica: lectura de la fuente por ciclo"
PROYECCION = ("Ciclo intradía con el histórico completo y sin los índices de H12: lectura de la fuente estimada por "
              "ciclo (proyección lineal, no medición)")
DURACION = ("Ciclo intradía programado en un día comprimido (planificador y cola reales, captura de prueba): duración "
            "de cada ciclo")
LATENCIA = "Consulta paginada GET /api/v1/recommendations (50 filas) durante los ciclos intradía programados"
FILAS_INTRADIA = (INTRADIA, DIARIO, PROYECCION, DURACION, LATENCIA)


def _fuente_intradia(**cambios) -> dict:
    estimacion = {"intradia_s": 3.49, "diario_s": 7.59, "intradia_dia_s": 52.4, "fraccion_de_la_hora_intradia": 0.00097,
                  "dia_con_intradia_sobre_dia_sin_intradia": 7.9,
                  "proyeccion_historico_completo": {"factor_filas": 20.9, "intradia_s": 70.8,
                                                    "fraccion_de_la_hora_intradia": 0.0197}}
    return {"estimacion": dict(estimacion, **cambios)}


def _planificador(duraciones=(7.19, 3.56, 3.41, 3.63), **latencia) -> dict:
    lat = {"con_ciclo_en_curso": {"n": 61, "p50_s": 0.035, "p95_s": 0.048},
           "sin_ciclo": {"n": 738, "p50_s": 0.033, "p95_s": 0.042}, "respuestas_no_200": 0}
    return {"franjas": [{"duracion_s": d} for d in duraciones], "latencia_consulta_paginada": dict(lat, **latencia)}


def test_las_cifras_del_ciclo_intradia_salen_de_su_evidencia(evidencia):
    _escribir(evidencia, "ocupacion/ciclo_intradia_fuente.json", _fuente_intradia())
    _escribir(evidencia, "ocupacion/planificador_intradia.json", _planificador())
    assert _fila(INTRADIA)[1:] == ("3,49 s (0,10 % de la hora); 52,4 s al día con el cron por omisión",
                                   "ocupacion/ciclo_intradia_fuente.json")
    assert _fila(DIARIO)[1] == "7,59 s; el día con los ciclos intradía lee 7,9 veces lo que lee solo con el diario"
    assert _fila(PROYECCION)[1] == "70,8 s por ciclo (1,97 % de la hora), con 20,9 veces las filas de la réplica"
    assert _fila(DURACION)[1:] == ("de 3,41 a 7,19 s por ciclo (4 ciclos)", "ocupacion/planificador_intradia.json")
    assert _fila(LATENCIA)[1] == ("p95 0,048 s con un ciclo en curso (61 consultas) y 0,042 s sin ciclo (738); "
                                  "respuestas distintas de 200: 0")


def test_sin_la_evidencia_del_ciclo_intradia_no_hay_cifras(evidencia):
    assert {_fila(n)[1] for n in FILAS_INTRADIA} == {CV.SIN}
    # con los archivos pero sin un campo, la cifra que lo usa tampoco se inventa; las demás siguen
    _escribir(evidencia, "ocupacion/ciclo_intradia_fuente.json",
              _fuente_intradia(diario_s=None, proyeccion_historico_completo={"factor_filas": 20.9}))
    _escribir(evidencia, "ocupacion/planificador_intradia.json",
              _planificador(duraciones=(7.19, None), sin_ciclo={"n": 738}))
    assert _fila(INTRADIA)[1].startswith("3,49 s")
    assert [_fila(n)[1] for n in (DIARIO, PROYECCION, DURACION, LATENCIA)] == [CV.SIN] * 4
    _escribir(evidencia, "ocupacion/planificador_intradia.json", _planificador(duraciones=()))
    assert _fila(DURACION)[1] == CV.SIN and _fila(LATENCIA)[1].startswith("p95 0,048 s")


NIVELES = "Suite completa final, casos por nivel"
CICLO = ("Ciclo diario de punta a punta (lectura, calidad, predicción, plan y alertas): carga inicial / día nuevo / "
         "repetición del mismo día")
CONTRASTE = ("Contraste por segmento con filas reales de la liquidación en la réplica (3 viajes, "
             "contraste_viajes_minimos = 1; transacción revertida)")
INDICES = ("Propuesta de índices entera con ANALYZE en la réplica (transacción revertida): lectura incremental de la "
           "demanda por segmentos y lectura de viajes, sin → con los índices")


def _junit(evidencia, casos: dict[str, int]) -> None:
    cuerpo = "".join(f'<testcase classname="{clase}.test_x" name="t{i}"/>' for clase, n in casos.items()
                     for i in range(n))
    p = evidencia / "pruebas" / "suite_final.xml"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f'<testsuites><testsuite name="pytest" tests="{sum(casos.values())}">{cuerpo}</testsuite>'
                 "</testsuites>", encoding="utf-8")


def test_los_casos_por_nivel_salen_del_junit_de_la_suite_final(evidencia):
    assert _fila(NIVELES)[1] == CV.SIN
    _junit(evidencia, {"tests.unit": 1089, "tests.replica": 2, "tests.integracion": 3, "tests.contrato": 4,
                       "tests.datos_ml": 5, "tests.testcontainers": 1, "otra_cosa": 2})
    assert _fila(NIVELES)[1:] == ("unitarias 1.089, integración 3, réplica 2, contrato 4, datos y ML 5, otros 2, "
                                  "testcontainers 1", "pruebas/suite_final.xml")
    _junit(evidencia, {})
    assert _fila(NIVELES)[1] == CV.SIN


def _corrida(nombre: str, segundos: float, filas: int, estado: str = "ok") -> dict:
    return {"corrida": nombre, "estado": estado, "segundos_peticion": segundos, "filas_leidas": filas}


def test_el_ciclo_diario_sale_de_las_tres_corridas_medidas(evidencia):
    assert _fila(CICLO)[1] == CV.SIN
    corridas = [_corrida("carga_inicial", 27.51, 49623), _corrida("dia_nuevo", 20.68, 51),
                _corrida("repeticion", 0.18, 0)]
    _escribir(evidencia, "rendimiento/ciclo_final.json", {"corridas": corridas})
    assert _fila(CICLO)[1:] == ("27,5 s (49.623 filas) / 20,7 s (51 filas) / 0,2 s (0 filas)",
                                "rendimiento/ciclo_final.json")
    # una corrida que falta o que no terminó ok deja la cifra sin valor: no se publica una parte
    _escribir(evidencia, "rendimiento/ciclo_final.json", {"corridas": corridas[:2]})
    assert _fila(CICLO)[1] == CV.SIN
    _escribir(evidencia, "rendimiento/ciclo_final.json",
              {"corridas": [*corridas[:2], _corrida("repeticion", 0.18, 0, estado="error")]})
    assert _fila(CICLO)[1] == CV.SIN


def _tabla_contraste(groseras: int = 0, **cambios) -> dict:
    ciclo = {"llaves": 90, "comparadas": 90, "diferencias": 5, "groseras": groseras, "llaves_bloqueadas": 0}
    return {"contraste_del_ciclo": dict(ciclo, **cambios),
            "con_la_hora_en_el_grano": {"groseras": 129, "llaves_bloqueadas": 56}}


def test_el_contraste_por_segmento_con_filas_reales_sale_de_su_evidencia(evidencia):
    rel = "consolidados/segmentos_filas_reales.json"
    assert _fila(CONTRASTE.replace("(3 viajes", "(? viajes"))[1] == CV.SIN
    tablas = {"timbradas_segmentos_anio": _tabla_contraste(), "timbradas_segmentos_consolidado": _tabla_contraste()}
    _escribir(evidencia, rel, {"viajes": [1, 2, 3], "tablas": tablas})
    una = ("90 de 90 llaves comparadas, 5 diferencias no bloqueantes, 0 groseras y 0 llaves bloqueadas; con la hora "
           "del bloque en el grano serían 129 groseras y 56 llaves bloqueadas")
    assert _fila(CONTRASTE)[1:] == (f"en cada tabla, {una}", rel)
    # si las dos tablas no dan lo mismo, cada una sale con su nombre; si a una le falta un campo, no hay cifra
    tablas["timbradas_segmentos_consolidado"] = _tabla_contraste(groseras=2)
    _escribir(evidencia, rel, {"viajes": [1, 2, 3], "tablas": tablas})
    assert _fila(CONTRASTE)[1] == (f"timbradas_segmentos_anio: {una}; timbradas_segmentos_consolidado: "
                                   f"{una.replace('0 groseras', '2 groseras')}")
    tablas["timbradas_segmentos_consolidado"] = _tabla_contraste(groseras=None)
    _escribir(evidencia, rel, {"viajes": [1, 2, 3], "tablas": tablas})
    assert _fila(CONTRASTE)[1] == CV.SIN


def test_la_propuesta_de_indices_entera_sale_de_su_evidencia(evidencia):
    rel = "replica/indices_candidatos.json"
    assert _fila(INDICES)[1] == CV.SIN
    comparacion = {"demanda_segmentos_bloque": {"ms_sin": 3613.25, "ms_con": 1537.68},
                   "demanda_segmentos_sin_novedades": {"ms_sin": 168.59, "ms_con": 0.09},
                   "viajes_de_una_ruta": {"ms_sin": 810.6, "ms_con": 8.88}}
    _escribir(evidencia, rel, {"propuesta_entera": {"comparacion": comparacion}, "veredicto": {"empeoran": []}})
    assert _fila(INDICES)[1:] == ("bloque de llegada, 3.613,2 → 1.537,7 ms; sin novedades, 168,6 → 0,1 ms; viajes de "
                                  "una ruta, 810,6 → 8,9 ms; lecturas de la API que empeoran: 0", rel)
    _escribir(evidencia, rel, {"propuesta_entera": {"comparacion": comparacion},
                               "veredicto": {"empeoran": ["demanda_segmentos_bloque"]}})
    assert _fila(INDICES)[1].endswith("lecturas de la API que empeoran: 1")
    # sin el veredicto o sin una de las tres lecturas no se publica nada
    _escribir(evidencia, rel, {"propuesta_entera": {"comparacion": comparacion}})
    assert _fila(INDICES)[1] == CV.SIN
    del comparacion["viajes_de_una_ruta"]
    _escribir(evidencia, rel, {"propuesta_entera": {"comparacion": comparacion}, "veredicto": {"empeoran": []}})
    assert _fila(INDICES)[1] == CV.SIN


def test_la_capa_de_segmentos_se_lee_de_la_corrida_vigente_y_no_de_la_revision_anterior(evidencia):
    _escribir(evidencia, "pruebas/revision_segmentos/k6_segmentos_carga.json",
              {"metrics": {"http_req_duration{tipo:consulta}": {"p(95)": 1163.1}}})
    fila = _fila("k6, capa de segmentos con 50 usuarios durante un refresco completo")
    assert fila[1:] == (CV.SIN, "pruebas/k6_segmentos_carga.json")
    _escribir(evidencia, "pruebas/k6_segmentos_carga.json",
              {"metrics": {"http_req_duration{tipo:consulta}": {"p(95)": 372.32},
                           "http_req_duration{consulta:estadisticas_semana_ruta}": {"p(95)": 410.9515},
                           "http_req_failed": {"value": 0.0003}}})
    assert _fila(fila[0])[1] == "p95 372,3 ms (la consulta más lenta, 411,0 ms), errores 0,03 %"


def test_las_corridas_anteriores_de_k6_dicen_que_lo_son(evidencia):
    metricas = {"metrics": {"http_req_duration": {"p(95)": 627.5}, "http_req_failed": {"value": 0}}}
    _escribir(evidencia, "pruebas/k6_volumen.json", {"fecha": "2026-11-09", "carga": metricas})
    _escribir(evidencia, "pruebas/k6_segmentos_consultas.json", metricas)
    assert _fila("k6 con un año de resultados (corrida anterior, del 2026-11-09)")[1] == "p95 627,5 ms, errores 0,00 %"
    assert _fila("k6, consultas paginadas con un mes de resultados (corrida anterior)")[1] == CV.SIN
    vigente = _fila("k6, consultas paginadas con el volumen acordado (50 usuarios; corrida vigente)")
    assert vigente[1].startswith("p95 627,5")
