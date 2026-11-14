"""§11.2 «Las novedades viales se cruzan por fecha, rango horario y ruta para generar variables de impacto», sin base.

Con tablas sintéticas de novedades_viales_fecha y novedades_viales_ruta (las de Extreme): una novedad con filas en
novedades_viales_ruta afecta solo a sus rutas del catálogo; una sin filas, a todas (el supuesto declarado de Sobusa,
donde la tabla está vacía); las filas que no se pueden aplicar se cuentan y no reparten la novedad. Las variables
nov_impacto y nov_sube de la tabla del modelo toman, en cada ruta, el máximo entre lo general y lo de su ruta, y sin
novedades por ruta la tabla queda exactamente igual.
"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

from app.servicios import novedades as N
from app.servicios import variables

NOMBRES = {2: "SILENCIO", 16: "CRA 54", 21: "CL 72"}
DIA = date(2024, 3, 9)


def _novedad(i, fecha, inicio, fin, efecto, impacto):
    return {"id_novedad_vial_fecha": i, "proceso": "sobusa", "id_novedad_vial": 10 + i, "novedad": f"N{i}",
            "nombre": f"novedad {i}", "fecha": fecha, "hora_inicio": inicio, "hora_fin": fin,
            "potencial_efecto": efecto, "porcentaje_impacto": impacto}


NOV = pd.DataFrame([_novedad(1, DIA, "06:00:00", "08:30:00", "SUBE", 30.0),       # de todas las rutas
                    _novedad(2, DIA, "07:00:00", "09:00:00", "BAJA", 80.0),       # solo CL 72 (idruta 21)
                    _novedad(3, DIA + timedelta(days=1), "10:00:00", "10:45:00", "SUBE", 50.0)])   # solo la ruta 99
POR_RUTA = pd.DataFrame([{"id_novedad_vial_ruta": 1, "id_novedad_vial_fecha": 2, "id_ruta": 21},
                         {"id_novedad_vial_ruta": 2, "id_novedad_vial_fecha": 3, "id_ruta": 99},     # otra empresa
                         {"id_novedad_vial_ruta": 3, "id_novedad_vial_fecha": 77, "id_ruta": 2}])    # sin novedad
VACIA = POR_RUTA.iloc[0:0]
EA = pd.DataFrame([{"id_estacionalidad_anio": 1, "proceso": "sobusa", "id_estacionalidad": 5, "ano": 2024,
                    "fecha_inicio": date(2024, 3, 25), "fecha_fin": date(2024, 3, 25)}])
EST = pd.DataFrame([{"id_estacionalidad": 5, "estacionalidad": "FESTIVO_NACIONAL"}])


def _contexto(por_ruta):
    from scripts.preparar_datos_api import contexto_y_novedades_por_ruta

    return contexto_y_novedades_por_ruta(NOV, por_ruta, EA, EST, "2024-01-01", "2024-03-31", NOMBRES)


def _en(ctx, fecha, hora, ruta=None):
    filas = ctx[(ctx["fecha"] == fecha) & (ctx["hora"] == hora) & ((ctx["ruta"] == ruta) if ruta else True)]
    return (float(filas["nov_impacto"].iloc[0]), int(filas["nov_sube"].iloc[0])) if len(filas) else None


def test_horas_afectadas_por_el_rango_horario():
    assert list(N.horas_afectadas("14:30:00", "18:00:00")) == [14, 15, 16, 17, 18]
    assert list(N.horas_afectadas("02:00", "05:10")) == [4, 5] and list(N.horas_afectadas("19:00", "23:59")) == [19, 20]
    assert list(N.horas_afectadas("21:00", "22:00")) == []


def test_una_novedad_con_rutas_afecta_solo_a_sus_rutas_y_una_sin_rutas_a_todas():
    ctx, por_ruta, info = _contexto(POR_RUTA)
    # lo general (todas las rutas): solo la novedad 1
    assert _en(ctx, DIA, 6) == (30.0, 1) and _en(ctx, DIA, 8) == (30.0, 1) and _en(ctx, DIA, 9) == (0.0, 0)
    assert _en(ctx, DIA + timedelta(days=1), 10) == (0.0, 0)          # la de la ruta 99 no se reparte
    # lo de rutas dadas: la novedad 2 solo en CL 72, sus horas 7 a 9
    assert set(por_ruta["ruta"]) == {"CL 72"} and sorted(por_ruta["hora"]) == [7, 8, 9]
    assert _en(por_ruta, DIA, 7, "CL 72") == (80.0, 0) and _en(por_ruta, DIA, 9, "CL 72") == (80.0, 0)
    assert info["filas_novedades_viales_ruta"] == 3 and info["novedades_por_ruta"] == 2
    assert info["novedades_todas_las_rutas"] == 1 and info["rutas_fuera_del_catalogo"] == 1
    assert info["filas_sin_novedad"] == 1 and info["filas_novedades_por_ruta"] == 3 and info["novedades"] == 3


def test_sin_filas_en_novedades_viales_ruta_cada_novedad_es_de_todas_las_rutas():
    """El caso de Sobusa (la tabla vacía en la base del reto y en la réplica): el contexto es el de siempre, por fecha y
    hora, y no hay contexto por ruta."""
    from scripts.preparar_datos_api import contexto_desde_tablas

    ctx, por_ruta, info = _contexto(VACIA)
    assert por_ruta.empty and info["filas_novedades_viales_ruta"] == 0 and info["novedades_todas_las_rutas"] == 3
    assert _en(ctx, DIA, 7) == (80.0, 1) and _en(ctx, DIA, 9) == (80.0, 0)      # el máximo de las que cruzan la hora
    assert _en(ctx, DIA + timedelta(days=1), 10) == (50.0, 1)
    solo, _info = contexto_desde_tablas(NOV, VACIA, EA, EST, "2024-01-01", "2024-03-31", NOMBRES)
    pd.testing.assert_frame_equal(solo, ctx)
    assert int(ctx.loc[ctx["fecha"] == date(2024, 3, 25), "festivo_oficial"].max()) == 1


def test_rutas_por_novedad_y_novedades_de_todas_las_rutas():
    assert N.rutas_por_novedad(POR_RUTA) == {2: [21], 3: [99], 77: [2]} and N.rutas_por_novedad(None) == {}
    assert list(N.de_todas_las_rutas(NOV, N.rutas_por_novedad(POR_RUTA))["id_novedad_vial_fecha"]) == [1]
    assert N.de_todas_las_rutas(NOV, {}) is NOV
    assert N.impacto_por_ruta(NOV, {}, NOMBRES).empty


# ---------------------------------------------------------------- en la tabla de variables del modelo
def _serie() -> pd.DataFrame:
    inicio = date(2024, 1, 1)
    filas = [{"ruta": ruta, "fecha": inicio + timedelta(days=i), "hora": h, "pasajeros": 100.0 + h, "excluido": 0,
              "festivo": 0, "tipo_dia": 0}
             for i in range(80) for ruta in NOMBRES.values() for h in range(5, 11)]
    return pd.DataFrame(filas)


def _fila(tabla, ruta, fecha, hora):
    t = tabla[(tabla["ruta"] == ruta) & (tabla["fecha"] == fecha) & (tabla["hora"] == hora)]
    assert len(t) == 1
    return t.iloc[0]


def test_las_variables_de_cada_ruta_toman_su_novedad_y_las_demas_no_cambian():
    ctx, por_ruta, _info = _contexto(POR_RUTA)
    tabla = variables.construir_variables(_serie(), contexto=ctx)
    aplicada = N.aplicar_por_ruta(tabla, por_ruta)
    assert list(aplicada.columns) == list(tabla.columns) and len(aplicada) == len(tabla)
    assert (_fila(aplicada, "CL 72", DIA, 7)["nov_impacto"], _fila(aplicada, "CL 72", DIA, 7)["nov_sube"]) == (80, 1)
    assert (_fila(aplicada, "CL 72", DIA, 9)["nov_impacto"], _fila(aplicada, "CL 72", DIA, 9)["nov_sube"]) == (80, 0)
    for ruta in ("SILENCIO", "CRA 54"):            # la novedad 2 no es de estas rutas
        assert _fila(aplicada, ruta, DIA, 9)["nov_impacto"] == 0 and _fila(aplicada, ruta, DIA, 7)["nov_impacto"] == 30
    otras = [c for c in tabla.columns if c not in ("nov_impacto", "nov_sube")]
    pd.testing.assert_frame_equal(aplicada[otras], tabla[otras])
    cambiadas = (aplicada["nov_impacto"] != tabla["nov_impacto"]) | (aplicada["nov_sube"] != tabla["nov_sube"])
    assert set(aplicada.loc[cambiadas, "ruta"]) == {"CL 72"} and cambiadas.sum() == 3
    assert aplicada["nov_impacto"].dtype == tabla["nov_impacto"].dtype


def test_sin_novedades_por_ruta_la_tabla_es_la_misma():
    ctx, por_ruta, _info = _contexto(VACIA)
    tabla = variables.construir_variables(_serie(), contexto=ctx)
    assert N.aplicar_por_ruta(tabla, por_ruta) is tabla and N.aplicar_por_ruta(tabla, None) is tabla


def test_entrenar_e_inferir_usan_el_mismo_paso_con_las_novedades_por_ruta(monkeypatch):
    """inferencia.variables_de (lo que usan la tabla empaquetada, la serie validada y el entrenamiento) pone encima las
    novedades de datos/novedades_por_ruta.parquet; sin ese archivo es construir_variables tal cual."""
    from app.servicios import datos, inferencia

    ctx, por_ruta, _info = _contexto(POR_RUTA)
    monkeypatch.setattr(datos, "novedades_por_ruta", lambda: por_ruta)
    con = inferencia.variables_de(_serie(), contexto=ctx)
    assert _fila(con, "CL 72", DIA, 9)["nov_impacto"] == 80 and _fila(con, "SILENCIO", DIA, 9)["nov_impacto"] == 0
    monkeypatch.setattr(datos, "novedades_por_ruta", lambda: por_ruta.iloc[0:0])
    pd.testing.assert_frame_equal(inferencia.variables_de(_serie(), contexto=ctx),
                                  variables.construir_variables(_serie(), contexto=ctx))


def test_el_archivo_de_novedades_por_ruta_es_opcional(tmp_path, monkeypatch):
    from app.servicios import datos
    from scripts.preparar_datos_api import escribir_novedades_por_ruta

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    datos.limpiar_cache()
    try:
        assert datos.novedades_por_ruta().empty and list(datos.novedades_por_ruta().columns) == N.COLUMNAS_POR_RUTA
        _ctx, por_ruta, _info = _contexto(POR_RUTA)
        assert escribir_novedades_por_ruta(tmp_path, por_ruta) is True
        datos.limpiar_cache()
        leida = datos.novedades_por_ruta()
        assert len(leida) == 3 and set(leida["ruta"]) == {"CL 72"} and leida["fecha"].iloc[0] == DIA
        assert escribir_novedades_por_ruta(tmp_path, por_ruta.iloc[0:0]) is False       # sin filas: se quita
        assert not (tmp_path / "novedades_por_ruta.parquet").exists()
    finally:
        datos.limpiar_cache()


@pytest.mark.parametrize("impacto", [None, float("nan")])
def test_una_novedad_sin_porcentaje_no_suma_impacto(impacto):
    nov = pd.DataFrame([_novedad(5, DIA, "07:00", "07:30", "SUBE", impacto)])
    por_ruta = pd.DataFrame([{"id_novedad_vial_ruta": 1, "id_novedad_vial_fecha": 5, "id_ruta": 2}])
    filas = N.impacto_por_ruta(nov, N.rutas_por_novedad(por_ruta), NOMBRES)
    assert list(filas["ruta"]) == ["SILENCIO"] and int(filas["nov_sube"].iloc[0]) == 1
