"""scripts/medir_ciclo_intradia.py (§10.1, PLAN_INTRADIA_CRON): la estimación de la carga en la fuente de un ciclo
intradía y su proyección al histórico completo de timbradas_segmentos (H12), sin base.

La proyección escala en proporción a las filas cada lectura del ciclo que recorre timbradas_segmentos sin índice. Los
viajes del día son una de ellas: su conteo de segmentos por viaje cruza la tabla por id_viaje (en la réplica, EXPLAIN
muestra un Seq Scan de la tabla entera), así que quedan escalados como la lectura incremental y la ocupación.
"""
from __future__ import annotations

LECTURAS = ("incremental_todas", "incremental_una_ruta", "ocupacion_en_curso", "ocupacion_dia", "viajes_del_dia",
            "contexto", "consolidados", "ventana_refresco")


def test_la_proyeccion_escala_cada_lectura_que_recorre_timbradas_segmentos():
    from app.servicios import fuentes
    from scripts import medir_ciclo_intradia as m

    assert "timbradas_segmentos" in fuentes.sql_viajes_ruta(True)        # la lectura de viajes del ciclo la cruza
    assert {"incremental_todas", "ocupacion_en_curso", "viajes_del_dia"} <= m.RECORREN_TIMBRADAS
    assert "contexto" not in m.RECORREN_TIMBRADAS
    lecturas: dict = {k: {"mediana_s": 1.0} for k in LECTURAS}
    lecturas["filas_timbradas_segmentos"] = m.FILAS_HISTORICO_COMPLETO // 10     # el histórico completo, 10 veces
    e = m.estimar(lecturas)
    # un ciclo intradía: incremental + 2 × ocupación de sus horas en curso + viajes del día + contexto
    assert e["intradia_s"] == 5.0 and e["intradia_dia_s"] == 15 * 5.0
    proyeccion = e["proyeccion_historico_completo"]
    assert proyeccion["factor_filas"] == 10.0
    assert proyeccion["intradia_s"] == 10 * (1 + 2 + 1) + 1                 # todo escala salvo el contexto
