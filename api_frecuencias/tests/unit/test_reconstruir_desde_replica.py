"""scripts/reconstruir_desde_replica.py --linaje (§16 «trazabilidad y reproducibilidad», RF-001, RF-014): cada archivo
empaquetado de datos/ tiene su linaje (se reconstruye desde la réplica o se dice por qué no) y las piezas sin base de
la comparación. La reconstrucción contra la réplica la prueba
tests/replica/test_integrado.py::test_linaje_el_historico_empaquetado_se_reconstruye_identico_desde_la_replica."""
from __future__ import annotations

from datetime import date

import pandas as pd

from scripts import reconstruir_desde_replica as R


def test_cada_archivo_empaquetado_de_datos_tiene_su_linaje():
    """Un .parquet nuevo en datos/ (como bajadas_horaria, subidas_segmento_hora u ocupacion_segmentos_hora) obliga a
    decidir: se reconstruye desde la réplica (RECONSTRUIDOS) o se declara por qué no (SIN_RECONSTRUIR)."""
    empaquetados = {p.name for p in R.DATOS.glob("*.parquet")}
    assert set(R.RECONSTRUIDOS).isdisjoint(R.SIN_RECONSTRUIR)
    assert empaquetados == set(R.RECONSTRUIDOS) | set(R.SIN_RECONSTRUIR)
    assert {"bajadas_horaria.parquet", "subidas_segmento_hora.parquet"} <= set(R.RECONSTRUIDOS)
    assert all(m.strip().endswith(".") for m in R.SIN_RECONSTRUIR.values())
    nuevos = {f"{n}.parquet" for n in ("bajadas_horaria", "subidas_segmento_hora")}
    assert nuevos <= set(R.COMPARACION_ARCHIVOS)


def test_la_normalizacion_no_depende_del_orden_de_las_filas_y_conserva_el_texto():
    d = pd.DataFrame({"ruta": ["CL 72", "CL 72", "CRA 54"],
                      "fecha": [date(2023, 1, 2), date(2023, 1, 1), date(2023, 1, 1)], "hora": [5, 5, 5],
                      "id_segmento": [2, 1, 1], "subidas": [3, 0, 7], "sentido": ["ida", "regreso", "ida"],
                      "km_inicio": [0.5, 0.0, 0.0]})
    columnas = list(d.columns)
    llave = ["ruta", "fecha", "hora", "id_segmento"]
    texto = R.normalizada(d, columnas, llave)
    assert texto == R.normalizada(d.iloc[::-1], columnas, llave)
    assert texto.splitlines() == ["ruta,fecha,hora,id_segmento,subidas,sentido,km_inicio",
                                  "CL 72,2023-01-01,5,1,0,regreso,0.0", "CL 72,2023-01-02,5,2,3,ida,0.5",
                                  "CRA 54,2023-01-01,5,1,7,ida,0.0"]
    # sin `orden`, la de siempre (las tres primeras columnas): las huellas de demanda y contexto no cambian
    serie = pd.DataFrame({"ruta": ["CL 72"], "idruta": [21], "fecha": [date(2023, 1, 1)], "hora": [4],
                          "pasajeros": [12.0], "salidas": [2.0]})
    assert R.normalizada(serie, list(serie.columns)).splitlines() == ["ruta,idruta,fecha,hora,pasajeros,salidas",
                                                                      "CL 72,21,2023-01-01,4,12,2"]


class _Fuente:
    def __init__(self, filas: pd.DataFrame):
        self.filas, self.sql, self.parametros = filas, None, None

    def consultar(self, sql, parametros=None):
        self.sql, self.parametros = sql, parametros
        return self.filas.copy()


def test_las_bajadas_se_reconstruyen_con_la_regla_de_los_pasajeros_y_la_grilla(monkeypatch):
    """Σ numerobajadas de los viajes válidos (dato no nulo y <= 300) por la hora de salida, y 0 donde no hubo viajes;
    una ruta fuera del catálogo no entra."""
    monkeypatch.setattr(R, "_rutas", lambda: {21: "CL 72"})
    f = _Fuente(pd.DataFrame({"idruta": [21, 99], "fecha": [date(2023, 1, 1)] * 2, "hora": [5, 5],
                              "bajadas_viajes": [74, 9]}))
    t = R.bajadas_reconstruidas(f)
    assert "numerobajadas <= 300" in f.sql and "finalizado = 'S'" in f.sql and "cancelada = 'N'" in f.sql
    assert list(t.columns) == ["ruta", "fecha", "hora", "bajadas_viajes"]
    assert len(t) == len(pd.date_range(R.DESDE, R.HASTA)) * len(R.HORAS) and set(t["ruta"]) == {"CL 72"}
    assert t["bajadas_viajes"].sum() == 74
    assert t.loc[(t["fecha"] == date(2023, 1, 1)) & (t["hora"] == 5), "bajadas_viajes"].item() == 74


def test_el_dia_reservado_de_la_replica_solo_se_quita_de_sus_rutas(monkeypatch):
    """Los viajes reservados para simular la llegada (2023-02-07, rutas 2 y 21) no están en timbradas_segmentos de la
    réplica: la comparación sin ese día quita solo esas filas; CRA 54 de ese día sigue."""
    monkeypatch.setattr(R, "_rutas", lambda: {2: "SILENCIO", 16: "CRA 54", 21: "CL 72"})
    d = pd.DataFrame({"ruta": ["SILENCIO", "CL 72", "CRA 54", "CL 72"],
                      "fecha": [R.DIA_RESERVADO, R.DIA_RESERVADO, R.DIA_RESERVADO, date(2023, 2, 8)]})
    assert R._sin_el_dia_reservado(d)["ruta"].tolist() == ["CRA 54", "CL 72"]
