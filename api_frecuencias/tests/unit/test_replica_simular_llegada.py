"""scripts/replica_simular_llegada.py, sin base: el informe de la llegada (docs/evidencias/replica/replica_llegada.txt)
dice cuántas migraciones aplicó alembic como escritor_ia y cuáles, todas (la cabeza final, no solo las últimas)."""
from __future__ import annotations

from scripts import replica_simular_llegada as sim


def _salida_alembic(n: int) -> str:
    lineas = ["INFO  [alembic.runtime.migration] Context impl PostgresqlImpl.",
              "INFO  [alembic.runtime.migration] Will assume transactional DDL."]
    previa = ""
    for i in range(1, n + 1):
        actual = f"{i:04d}"
        lineas.append(f"INFO  [alembic.runtime.migration] Running upgrade {previa} -> {actual}, migración {actual}")
        previa = actual
    return "\n".join(lineas) + "\n"


def test_el_informe_cuenta_y_nombra_todas_las_migraciones_aplicadas():
    aplicadas = sim.migraciones_aplicadas(_salida_alembic(14))
    assert len(aplicadas) == 14 and aplicadas[0].endswith("-> 0001, migración 0001")
    assert aplicadas[-1].endswith("0013 -> 0014, migración 0014")
    informe = {"ciclo_api": {"preparacion": {"alembic_upgrade_head_como_escritor_ia": True, "alembic_segundos": 3.1,
                                             "alembic_salida": aplicadas},
                             "corridas": []}}
    texto = sim.texto_informe(informe)
    assert "alembic upgrade head como escritor_ia: True en 3.1 s (14 migraciones)" in texto
    assert "      0013 -> 0014, migración 0014" in texto and "      -> 0001, migración 0001" in texto


def test_un_error_de_alembic_se_conserva_sin_contar_como_migracion():
    aplicadas = sim.migraciones_aplicadas(_salida_alembic(2) + "sqlalchemy.exc.ProgrammingError: permiso denegado\n")
    assert len(aplicadas) == 3 and aplicadas[-1].startswith("sqlalchemy.exc.ProgrammingError")
    informe = {"ciclo_api": {"preparacion": {"alembic_salida": aplicadas}, "corridas": []}}
    assert "(2 migraciones)" in sim.texto_informe(informe)
    assert sim.migraciones_aplicadas(None) == []
