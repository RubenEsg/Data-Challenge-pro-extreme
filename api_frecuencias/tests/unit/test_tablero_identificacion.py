"""Tablero, detalle de una alerta (§5.3): un viaje, un vehículo o un conductor vacío dice el motivo real que declara la
alerta en variables.identificacion_5_3, y solo dice «no aplica» cuando la regla no mira un viaje.

La página (EntregaFinal/dash_app/paginas/alertas.py) registra una ruta de Dash al importarse, así que la prueba toma
del código fuente solo las constantes y la función que arman ese texto, y las ejecuta con la identificación que
produce de verdad la API (app/servicios/alertas.py)."""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.servicios import alertas as A

PAGINA = Path(__file__).resolve().parents[3] / "dash_app" / "paginas" / "alertas.py"
NOMBRES = {"NO_APLICA", "SIN_IDENTIFICAR", "_campo_5_3"}
pytestmark = pytest.mark.skipif(not PAGINA.exists(), reason="sin el tablero (EntregaFinal/dash_app/paginas/alertas.py)")


def _nombre(nodo: ast.stmt) -> str | None:
    if isinstance(nodo, ast.FunctionDef):
        return nodo.name
    if isinstance(nodo, ast.Assign) and isinstance(nodo.targets[0], ast.Name):
        return nodo.targets[0].id
    return None


@pytest.fixture(scope="module")
def pagina() -> dict:
    arbol = ast.parse(PAGINA.read_text(encoding="utf-8"))
    cuerpo = [n for n in arbol.body if _nombre(n) in NOMBRES]
    assert {_nombre(n) for n in cuerpo} == NOMBRES
    espacio: dict = {}
    exec(compile(ast.Module(body=cuerpo, type_ignores=[]), str(PAGINA), "exec"), espacio)  # noqa: S102  # nosec B102
    return espacio


def _alerta(codigo: str, resultado: str | None = None, variante: str | None = None, **campos) -> dict:
    return {"codigo": codigo, "viaje": None, "vehiculo": "", "conductor": None, "sentido": None,
            "variables": {"identificacion_5_3": A.identificacion_5_3(codigo, resultado, variante)}} | campos


@pytest.mark.parametrize("codigo", ["ALT-006", "ALT-009"])
def test_una_regla_de_viaje_sin_viajes_en_la_fuente_dice_el_motivo_y_no_que_no_aplica(pagina, codigo):
    campo, tabla = pagina["_campo_5_3"], pagina["SIN_IDENTIFICAR"]
    for resultado in ("fuente_sin_viajes", "fuente_sin_viajes_del_dia"):
        alerta = _alerta(codigo, resultado)
        for nombre in A.CAMPOS_VIAJE:
            assert campo(alerta, nombre) == tabla[resultado] != pagina["NO_APLICA"]
        assert campo(alerta, "sentido") == pagina["NO_APLICA"]     # el sentido no aplica a las reglas por ruta


def test_una_regla_de_la_ruta_sigue_diciendo_que_no_aplica(pagina):
    for codigo in ("ALT-001", "ALT-005", "ALT-008", "ALT-010"):
        alerta = _alerta(codigo)
        assert {pagina["_campo_5_3"](alerta, n) for n in ("sentido", *A.CAMPOS_VIAJE)} == {pagina["NO_APLICA"]}
    # una alerta vieja sin la variable, o sin variables, tampoco rompe el detalle
    assert pagina["_campo_5_3"]({"viaje": None}, "viaje") == pagina["NO_APLICA"]
    assert pagina["_campo_5_3"]({"viaje": None, "variables": None}, "viaje") == pagina["NO_APLICA"]


def test_un_campo_con_valor_se_muestra_tal_cual(pagina):
    alerta = _alerta("ALT-006", "identificado", viaje=5141355, vehiculo="V-12", conductor="c-9f2")
    assert [pagina["_campo_5_3"](alerta, n) for n in A.CAMPOS_VIAJE] == [5141355, "V-12", "c-9f2"]


def test_el_tablero_tiene_un_texto_para_cada_resultado_que_emite_la_api(pagina):
    tabla = pagina["SIN_IDENTIFICAR"]
    resultados = {"fuente_sin_viajes", "fuente_sin_viajes_del_dia", "sin_viaje_cancelado_ni_tardio",
                  "sin_viajes_incompletos", "solo_frescura", "segmento_sin_viaje"}
    assert set(A.FRASES_SIN_VIAJES) <= resultados <= set(tabla)
    # la variante de ALT-002 medida en el segmento crítico aplica el sentido y el viaje: sin viaje, lo dice
    alerta = _alerta("ALT-002", "segmento_sin_viaje", "segmento_critico", sentido="ida")
    assert pagina["_campo_5_3"](alerta, "sentido") == "ida"
    assert pagina["_campo_5_3"](alerta, "viaje") == tabla["segmento_sin_viaje"]
    # un resultado que el tablero todavía no conoce sale con su nombre, nunca como «no aplica»
    assert pagina["_campo_5_3"](_alerta("ALT-006", "otro_motivo"), "viaje") == "— sin identificar (otro_motivo)"
