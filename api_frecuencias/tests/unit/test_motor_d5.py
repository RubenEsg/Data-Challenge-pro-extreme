"""motor_d5: resolver_dia y resolver_dia_detalle devuelven tuplas de largo fijo (SonarQube python:S8495) y el mismo
plan que la versión original de D5 (ver app/servicios/motor_d5/PROCEDENCIA.md)."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pytest

from app.servicios.motor_d5 import comun as C
from app.servicios.motor_d5 import milp, plan_base

ORIGINAL = Path(__file__).resolve().parents[3] / "dash_app" / "motor" / "milp.py"


def _entradas(ruta: str = "CRA 54", fecha: str = "2025-03-04"):
    sub = plan_base.insumos(fecha, ruta)
    return plan_base.entradas_d5(sub), sub["ciclo"].values, float(sub["flota_disp"].iloc[0])


def test_resolver_dia_devuelve_siempre_tres_valores():
    ent, ciclo, flota = _entradas()
    resultado = milp.resolver_dia(ent, ciclo, flota, C.param_d5())
    assert len(resultado) == 3
    x, estado, holgura = resultado
    assert len(x) == len(ent) and estado == "Optimal" and holgura >= 0


def test_resolver_dia_detalle_agrega_los_componentes_del_costo():
    ent, ciclo, flota = _entradas()
    P = C.param_d5()
    x, estado, holgura = milp.resolver_dia(ent, ciclo, flota, P)
    x2, estado2, holgura2, comp = milp.resolver_dia_detalle(ent, ciclo, flota, P)
    assert np.array_equal(x, x2) and estado == estado2 and holgura == pytest.approx(holgura2)
    assert set(comp) == {"op", "espera", "sobrecarga", "ingreso"}


@pytest.mark.skipif(not ORIGINAL.exists(), reason="sin la copia original de D5 (EntregaFinal/dash_app/motor/milp.py)")
def test_mismo_plan_que_la_version_original_de_d5():
    spec = importlib.util.spec_from_file_location("milp_original_d5", ORIGINAL)
    original = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(original)
    P = C.param_d5()
    for ruta in ("SILENCIO", "CL 72"):
        ent, ciclo, flota = _entradas(ruta, "2025-06-14")
        a = original.resolver_dia(ent, ciclo, flota, P, solver="cbc", devolver_detalle=True)
        b = milp.resolver_dia_detalle(ent, ciclo, flota, P, solver="cbc")
        assert np.array_equal(a[0], b[0]) and a[1] == b[1] and a[2] == b[2] and a[3] == b[3]
