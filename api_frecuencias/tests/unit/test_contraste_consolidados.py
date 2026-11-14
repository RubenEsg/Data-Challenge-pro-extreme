"""Unidad de scripts/contraste_consolidados.py (evidencia de docs/evidencias/consolidados/): la sección de las tablas
por segmento dice que no tienen filas del proceso (H4) y con qué grano las contrasta el ciclo, que sale de
consolidados.CONFIG y no lleva la hora del bloque de Extreme (H10)."""
from __future__ import annotations

import pandas as pd

from app.servicios import consolidados as C
from scripts import contraste_consolidados as cc


class _FuenteSinFilas:
    """Una fuente cuyas tablas por segmento no tienen filas del proceso (como la réplica, H4)."""

    def __init__(self) -> None:
        self.consultas: list[tuple[str, dict]] = []

    def para_tabla(self, tabla: str):
        return self

    def consultar(self, sql: str, parametros: dict) -> pd.DataFrame:
        self.consultas.append((sql, parametros))
        return pd.DataFrame({"filas": [0]})


def test_las_tablas_por_segmento_sin_filas_dicen_el_grano_del_ciclo_sin_la_hora():
    fuente = _FuenteSinFilas()
    r = cc.segmentos_sin_filas(fuente)
    assert list(r) == [C.TABLA_SEGMENTOS_ANIO, C.TABLA_SEGMENTOS]
    assert [p for _sql, p in fuente.consultas] == [{"proceso": "sobusa"}] * 2
    for tabla, d in r.items():
        cfg = C.CONFIG[tabla]
        assert d["filas_del_proceso"] == 0 and d["resultado_del_ciclo"] == "sin_filas_fuente" and "H4" in d["motivo"]
        assert d["grano_del_contraste"] == list(cfg.grano) and "hora" not in d["grano_del_contraste"]
        assert d["grano_del_rango"] == [*cfg.grano, "hora"] and d["nota_del_grano"] == cfg.nota


def test_el_informe_de_las_tablas_por_segmento_nombra_el_grano_y_la_evidencia_con_filas_reales():
    texto = "\n".join(cc._informe_segmentos(cc.segmentos_sin_filas(_FuenteSinFilas())))
    assert "## timbradas_segmentos_anio y timbradas_segmentos_consolidado" in texto
    assert "(CONTR-002) va por id_segmento × ano × id_dia_semana × id_estacionalidad, y" in texto
    assert "(CONTR-002) va por id_segmento × id_dia_semana × id_estacionalidad, y" in texto
    assert "(CONTR-003, no bloqueante), por id_segmento × id_dia_semana × id_estacionalidad × hora." in texto
    assert texto.count("H10") == 1 and "segmentos_filas_reales.json" in texto        # una sola nota para las dos
