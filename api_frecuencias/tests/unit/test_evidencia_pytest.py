"""scripts/evidencia_pytest.py: el archivo de evidencia de una corrida de pytest sale de la salida de pytest.

Los conteos por estado y por archivo se cuentan de las líneas de «pytest -rA»; el encabezado dice el comando, las
variables de entorno que cambian la corrida y la fecha; y nunca copia una variable que no esté en su lista.
"""
from __future__ import annotations

from datetime import datetime

from scripts import evidencia_pytest as ev

SALIDA = """\
...s.                                                                    [100%]
==================================== PASSES ====================================
------------------------------ Captured log call -------------------------------
ERROR [api_frecuencias.cola] Ejecución 1 falló (registro capturado de una prueba que pasa)
ERROR tests/unit/test_a.py registro capturado que parece una línea del resumen
=========================== short test summary info ============================
PASSED tests/unit/test_a.py::test_uno
PASSED tests/unit/test_a.py::test_dos[x y]
PASSED tests/integracion/test_b.py::test_tres
SKIPPED [1] tests/unit/test_a.py:12: sin réplica
FAILED tests/integracion/test_b.py::test_cuatro - AssertionError: 1 != 2
3 passed, 1 failed, 1 skipped in 2.10s
"""
INICIO = datetime(2026, 11, 13, 22, 0, 0, tzinfo=ev.ZONA)
FIN = datetime(2026, 11, 13, 22, 0, 42, tzinfo=ev.ZONA)


def test_las_lineas_de_estado_traen_el_estado_y_el_archivo():
    filas = ev.lineas_de_estado(SALIDA)
    assert [(e, a) for e, a, _ in filas] == [
        ("PASSED", "tests/unit/test_a.py"), ("PASSED", "tests/unit/test_a.py"),
        ("PASSED", "tests/integracion/test_b.py"), ("SKIPPED", "tests/unit/test_a.py"),
        ("FAILED", "tests/integracion/test_b.py")]
    assert filas[1][2] == "PASSED tests/unit/test_a.py::test_dos[x y]"


def test_el_archivo_cuenta_lo_que_dijo_pytest_y_dice_el_comando():
    entorno = {"TEST_DATABASE_NAME": "ai_frecuencias_pruebas_x", "GENERAR_EVIDENCIAS": "1",
               "DATABASE_URL": "postgresql://u:secreto@h/b", "SOBUSA_API_KEY": "secreto"}
    texto = ev.armar("Pruebas de un área", ["tests/unit/test_a.py", "tests/integracion/test_b.py"], entorno, INICIO,
                     FIN, SALIDA, 1, ["una nota"])
    lineas = texto.splitlines()
    assert lineas[0] == "Pruebas de un área"
    assert ("  GENERAR_EVIDENCIAS=1 TEST_DATABASE_NAME=ai_frecuencias_pruebas_x python -m pytest tests/unit/test_a.py "
            "tests/integracion/test_b.py -rA") in lineas
    assert "Corrida del 2026-11-13, de 22:00:00 a 22:00:42 (America/Bogota); 42 s." in lineas
    assert "Resultado: 5 casos; 3 PASSED, 1 FAILED, 1 SKIPPED (código de salida de pytest: 1)." in lineas
    assert "Por archivo: tests/integracion/test_b.py: 2; tests/unit/test_a.py: 3." in lineas
    assert "Nota: una nota" in lineas
    assert lineas[-1].startswith("FAILED tests/integracion/test_b.py::test_cuatro")
    assert "secreto" not in texto


def test_sin_fallas_el_resultado_dice_cero_fallidas():
    texto = ev.armar("t", ["tests/unit"], {}, INICIO, FIN, "PASSED tests/unit/test_a.py::test_uno\n", 0, [])
    assert "Resultado: 1 casos; 1 PASSED, 0 FAILED (código de salida de pytest: 0)." in texto
    assert "  python -m pytest tests/unit -rA" in texto
