"""scripts/replica_lectura_por_ruta.py, sin base: el informe (docs/evidencias/cola/lectura_por_ruta_replica.txt) dice
si cada ruta leyó exactamente lo suyo, el tiempo medio de cada variante del SELECT y en qué condiciones se midió."""
from __future__ import annotations

from scripts import replica_lectura_por_ruta as L


def _plan(ms: float, escaneos: list[str]) -> dict:
    return {"ms_ejecucion": ms, "filas": 10, "buffers_hit": 1, "buffers_read": 2, "escaneos": escaneos}


def _desde(ms_todas: float, ms_ruta: float) -> dict:
    return {"marca": "2026-08-14T00:52:39-05:00", "filas_ruta": 4, "filas_lectura_de_siempre_de_la_ruta": 4,
            "iguales": True, "explain_todas": _plan(ms_todas, ["Seq Scan timbradas_segmentos"]),
            "explain_ruta": _plan(ms_ruta, ["Seq Scan timbradas_segmentos", "Index Scan rutas rutas_pkey"])}


def _informe(**extra) -> dict:
    ruta = {"carga_inicial": {"filas_ruta": 4, "filas_de_la_ruta_en_la_completa": 4, "iguales": True,
                              "solo_su_ruta": True},
            "desde_marca_intermedia": _desde(4000.0, 3000.0), "desde_la_marca_mayor": _desde(3000.0, 2000.0)}
    return {"generado_en": "2026-11-11T05:16:26-05:00", "rol": "lector_ia", "tabla": "demanda_segmentos",
            "filas_lectura_completa": 12, "rutas": {"CL 72": ruta}, **extra}


def test_el_informe_dice_las_medias_el_resultado_y_las_condiciones_de_la_medicion():
    texto = L._texto(_informe(nota_medicion="equipo sin otras suites de pruebas"))
    assert texto.splitlines()[1] == "Condiciones de la medición: equipo sin otras suites de pruebas"
    assert "Tiempo medio del SELECT: todas las rutas 3500 ms; una ruta 2500 ms." in texto
    assert "Recorridos completos en la variante por ruta: Seq Scan timbradas_segmentos." in texto
    assert "RESULTADO: TODO OK" in texto
    sin_nota = L._texto(_informe())
    assert "Condiciones de la medición" not in sin_nota and sin_nota.splitlines()[1].startswith("Lectura completa")
