"""Política de aprendizaje continuo (RF-018, RF-019, §9.5): umbrales, serie validada, compuerta y registro protegido."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.servicios import datos, inferencia, politica


def test_umbrales_por_defecto_y_versionados():
    u = politica.umbrales_politica({"sombra_dias": "7", "wape_max": 0.18, "otro": "texto"})
    assert u["sombra_dias"] == 7.0 and u["wape_max"] == 0.18
    assert u["reentreno_periodicidad_dias"] == 28 and u["activacion_automatica"] == 1


def test_datos_vistos_hasta():
    corte = datetime(2025, 8, 31, tzinfo=inferencia.ZONA)
    m = SimpleNamespace(metricas={}, data_cutoff=corte)
    assert politica.datos_vistos_hasta(m) == date(2025, 8, 31) + timedelta(days=61)
    m2 = SimpleNamespace(metricas={"sombra": {"datos_hasta": "2025-12-01"}}, data_cutoff=corte)
    assert politica.datos_vistos_hasta(m2) == date(2025, 12, 1)


class _Sesion:
    def __init__(self, filas):
        self.filas = filas

    def execute(self, _consulta):
        return SimpleNamespace(all=lambda: self.filas)


def test_serie_validada_reemplaza_y_trunca():
    base = datos.demanda_horaria(desde=date(2025, 3, 1), hasta=date(2025, 3, 3))
    fila = base.iloc[0]
    obs = [(fila["ruta"], fila["fecha"], int(fila["hora"]), 12345.0, 99)]
    serie, info = politica.serie_validada(_Sesion(obs), date(2025, 3, 3))
    assert serie["fecha"].max() == date(2025, 3, 3)
    v = serie[(serie["ruta"] == fila["ruta"]) & (serie["fecha"] == fila["fecha"]) & (serie["hora"] == fila["hora"])]
    assert float(v["pasajeros"].iloc[0]) == 12345.0
    assert info["filas_reemplazadas"] == 1 and info["filas_demanda_observada"] == 1
    assert len(serie) == len(datos.demanda_horaria(hasta=date(2025, 3, 3)))


def test_serie_validada_sin_observados_es_la_empaquetada():
    serie, info = politica.serie_validada(_Sesion([]), date(2024, 1, 31))
    assert serie["fecha"].max() == date(2024, 1, 31) and info["filas_demanda_observada"] == 0


def _eval(wapes: dict, cob=80.0, sesgo=1.0):
    def evaluar(mid, desde, hasta, *a, **k):
        return {"wape": wapes[mid], "mae": 1, "rmse": 1, "sesgo_pct": sesgo, "cobertura_p10_p90": cob,
                "cobertura_p10_p90_conformal": cob, "n": 100}
    return evaluar


@pytest.mark.parametrize("wapes, cob, sesgo, aprobado, falla", [
    ({"c": 14.0, "a": 15.0}, 80.0, 1.0, True, None),
    ({"c": 15.5, "a": 15.0}, 80.0, 1.0, False, "≤ WAPE del activo"),
    ({"c": 21.0, "a": 22.0}, 80.0, 1.0, False, "wape_max"),
    ({"c": 14.0, "a": 15.0}, 70.0, 1.0, False, "cobertura"),
    ({"c": 14.0, "a": 15.0}, 80.0, -7.0, False, "sesgo"),
])
def test_compuerta_de_activacion(monkeypatch, wapes, cob, sesgo, aprobado, falla):
    monkeypatch.setattr(inferencia, "evaluar", _eval(wapes, cob, sesgo))
    comp = politica.compuerta("c", "a", date(2025, 9, 1), date(2025, 9, 14), {"wape_max": 0.20})
    assert comp["aprobado"] is aprobado
    if falla:
        assert any(falla in c["criterio"] for c in comp["criterios"] if not c["ok"])
    assert comp["ventana"] == {"desde": date(2025, 9, 1), "hasta": date(2025, 9, 14)}


def test_id_libre_nunca_pisa_el_activo(tmp_path):
    (tmp_path / "registro.json").write_text('{"activo": "hgb_fv2_20250831_s42", "modelos": {}}', encoding="utf-8")
    assert inferencia.id_libre("hgb_fv2_20250831_s42", tmp_path) == "hgb_fv2_20250831_s42_r2"
    (tmp_path / "hgb_fv2_20250831_s42_r2").mkdir()
    assert inferencia.id_libre("hgb_fv2_20250831_s42", tmp_path) == "hgb_fv2_20250831_s42_r3"
    assert inferencia.id_libre("hgb_fv2_20251001_s42", tmp_path) == "hgb_fv2_20251001_s42"
    assert inferencia.id_libre("x", tmp_path, {"x"}) == "x_r2"


def test_registrar_modelo_no_sobrescribe_el_activo():
    from app.servicios import ejecucion

    activo = SimpleNamespace(model_id="m1", estado="activo", sha256="aaa", metricas={"wape": 1}, auditoria=[])

    class S:
        def scalar(self, _q):
            return activo

    r = ejecucion.registrar_modelo(S(), {"model_id": "m1", "sha256": "bbb", "metricas": {"wape": 9}})
    assert r is activo and activo.sha256 == "aaa" and activo.metricas == {"wape": 1}
    assert activo.auditoria[-1]["evento"] == "registro_omitido" and activo.auditoria[-1]["sha256_recibido"] == "bbb"


def test_iniciar_sombra_desde_el_dia_siguiente_a_los_datos():
    reg = SimpleNamespace(estado="candidato", metricas={"m": 1}, auditoria=[])
    politica.iniciar_sombra(reg, {"datos_hasta": "2025-10-31", "serie": {"origen": "x"}}, {"sombra_dias": 14})
    s = reg.metricas["sombra"]
    assert s["estado"] == "en_sombra" and s["inicio"] == "2025-11-01" and s["fin"] == "2025-11-14"
    assert reg.metricas["m"] == 1 and reg.auditoria[-1]["evento"] == "sombra_iniciada"
    activo = SimpleNamespace(estado="activo", metricas={}, auditoria=[])
    politica.iniciar_sombra(activo, {"datos_hasta": "2025-10-31"}, {})
    assert "sombra" not in activo.metricas


def test_entrenamiento_manual_sin_datos_hasta_no_va_a_sombra():
    reg = SimpleNamespace(estado="candidato", metricas={}, auditoria=[])
    politica.iniciar_sombra(reg, {"datos_hasta": "2025-12-31", "sombra_aplica": False}, {})
    assert reg.metricas["sombra"]["estado"] == "no_aplica" and "activate" in reg.metricas["sombra"]["motivo"]


class _SesionRegistro:
    """Sesión mínima para antiguedad_de_datos: los candidatos del registro."""

    def __init__(self, candidatos=()):
        self.candidatos = list(candidatos)

    def scalars(self, _consulta):
        return SimpleNamespace(all=lambda: self.candidatos)


def test_antiguedad_nunca_es_negativa_y_usa_el_reloj_de_los_datos():
    """GET /monitoring/policy: si el modelo ya vio datos posteriores a datos_hasta, no hay días nuevos (0, no -58)."""
    activo = SimpleNamespace(metricas={}, data_cutoff=date(2025, 8, 31))      # vio hasta 2025-10-31 (validación)
    a = politica.antiguedad_de_datos(_SesionRegistro(), activo, date(2025, 9, 3))
    assert a["ultimo_dato_visto"] == date(2025, 10, 31) and a["dias_desde_ultimo_entrenamiento"] == 0
    assert "2025-10-31" in a["nota_antiguedad"] and "America/Bogota" in a["reloj_antiguedad"]
    b = politica.antiguedad_de_datos(_SesionRegistro(), activo, date(2025, 11, 30))
    assert b["dias_desde_ultimo_entrenamiento"] == 30 and "nota_antiguedad" not in b
    cand = SimpleNamespace(metricas={"sombra": {"datos_hasta": "2025-11-20"}}, data_cutoff=date(2025, 9, 20))
    c = politica.antiguedad_de_datos(_SesionRegistro([cand]), activo, date(2025, 11, 30))
    assert c["ultimo_dato_visto"] == date(2025, 11, 20) and c["dias_desde_ultimo_entrenamiento"] == 10
    assert politica.antiguedad_de_datos(_SesionRegistro(), SimpleNamespace(metricas={}, data_cutoff=None),
                                        date(2025, 9, 3)) == {"ultimo_dato_visto": None}
    assert politica._motivo_periodicidad(b, politica.umbrales_politica({})) == [
        "periodicidad: 30 días de datos nuevos desde 2025-10-31 (cada 28)"]
    assert politica._motivo_periodicidad(a, politica.umbrales_politica({})) == []


def test_sombra_guarda_creado_en_en_bogota_y_la_calibracion_del_candidato():
    reg = SimpleNamespace(estado="candidato", metricas={}, auditoria=[])
    cal = {"version": "v2", "archivo": "calibracion_v2.json", "sha256": "a" * 64, "grupos": ["bloque"]}
    politica.iniciar_sombra(reg, {"datos_hasta": "2025-10-31", "calibracion": cal}, {})
    s = reg.metricas["sombra"]
    assert s["creado_en"].endswith("-05:00") and datetime.fromisoformat(s["creado_en"]).utcoffset() == timedelta(
        hours=-5)
    assert s["calibracion"] == cal


def test_compuerta_dice_que_calibracion_midio_en_cada_modelo(monkeypatch):
    def evaluar(mid, desde, hasta, *a, **k):
        return {"wape": 14.0 if mid == "c" else 15.0, "mae": 1, "rmse": 1, "sesgo_pct": 1.0, "n": 100,
                "cobertura_p10_p90": 79.0, "cobertura_p10_p90_conformal": 80.0,
                "cobertura_p10_p90_conformal_v1": 81.0, "calibracion_version": "v2"}

    monkeypatch.setattr(inferencia, "evaluar", evaluar)
    comp = politica.compuerta("c", "a", date(2025, 9, 1), date(2025, 9, 14), {"wape_max": 0.20})
    assert comp["calibracion"] == {"candidato": "v2", "activo": "v2", "misma_version": True}
    assert comp["metricas_candidato"]["calibracion_version"] == "v2"
    assert comp["metricas_activo"]["cobertura_p10_p90_conformal_v1"] == 81.0
    cobertura = next(c for c in comp["criterios"] if c["criterio"].startswith("cobertura"))
    assert cobertura["candidato"] == pytest.approx(0.80)       # la banda calibrada propia del candidato
    sin_activo = politica.compuerta("c", None, date(2025, 9, 1), date(2025, 9, 14), {})
    assert sin_activo["calibracion"] == {"candidato": "v2", "activo": None, "misma_version": True}


def test_el_candidato_se_calibra_con_los_grupos_del_activo(monkeypatch):
    from app.servicios import ejecucion

    monkeypatch.setattr(ejecucion, "modelo_activo", lambda s: SimpleNamespace(model_id="m_activo"))
    monkeypatch.setattr(inferencia, "cargar", lambda mid, *a, **k: {"calibracion": {"grupos": ["ruta", "bloque"]}})
    assert politica.grupos_calibracion_del_activo(None) == ("ruta", "bloque")
    monkeypatch.setattr(inferencia, "cargar", lambda mid, *a, **k: {"calibracion": None})
    assert politica.grupos_calibracion_del_activo(None) == inferencia.CALIBRACION_GRUPOS_DEFECTO

    def falla(mid, *a, **k):
        raise inferencia.ModeloNoEncontrado(mid)

    monkeypatch.setattr(inferencia, "cargar", falla)
    assert politica.grupos_calibracion_del_activo(None) == inferencia.CALIBRACION_GRUPOS_DEFECTO
    monkeypatch.setattr(ejecucion, "modelo_activo", lambda s: None)
    assert politica.grupos_calibracion_del_activo(None) == inferencia.CALIBRACION_GRUPOS_DEFECTO


# ---------------------------------------------------------------- un corte que no se puede entrenar no se encola
def test_corte_sin_datos_es_la_particion_del_entrenamiento(tmp_path):
    """La política pregunta con la misma función que usa entrenar, no con una copia de su regla. Al comienzo de la
    serie, el corte 61 días antes cae antes de los datos: no hay filas útiles para entrenar, y entrenar() falla con
    ese mismo motivo antes de escribir nada."""
    serie = datos.demanda_horaria(hasta=date(2023, 1, 26))
    falta = inferencia.corte_sin_datos(serie, date(2022, 11, 26))
    assert falta["motivo"] == "No hay datos suficientes para entrenar y validar con ese corte"
    assert falta["corte"] == date(2022, 11, 26) and falta["filas_entrenamiento"] == 0 and falta["filas_validacion"] > 0
    with pytest.raises(inferencia.CorteSinDatos, match=falta["motivo"]) as fallo:
        inferencia.entrenar(date(2022, 11, 26), serie=serie, dir_modelos=tmp_path)
    assert isinstance(fallo.value, ValueError) and (fallo.value.entrenamiento, fallo.value.validacion) == (
        0, falta["filas_validacion"])
    assert list(tmp_path.iterdir()) == []                       # no dejó ni la carpeta del candidato
    # con filas útiles a los dos lados del corte se puede; con el corte en el último día no queda validación
    assert inferencia.corte_sin_datos(serie, date(2023, 1, 15)) is None
    sin_validar = inferencia.corte_sin_datos(serie, date(2023, 1, 26))
    assert sin_validar["filas_validacion"] == 0 and sin_validar["filas_entrenamiento"] > 0


def test_una_serie_vacia_es_un_corte_sin_datos_y_no_otro_error():
    """Sin ninguna fila hasta datos_hasta (antes del comienzo de la serie empaquetada y sin días validados), armar las
    variables fallaba con «cannot convert float NaN to integer». Ese error salía de la decisión de la política, que
    ahora consulta la partición en cada ciclo con motivo, en GET /monitoring/policy y en la revisión del planificador.
    Una serie vacía es el mismo caso: cero filas para entrenar y cero para validar."""
    vacia = datos.demanda_horaria(hasta=date(2022, 12, 1))
    assert vacia.empty
    falta = inferencia.corte_sin_datos(vacia, date(2022, 10, 1))
    assert falta == {"motivo": "No hay datos suficientes para entrenar y validar con ese corte",
                     "corte": date(2022, 10, 1), "filas_entrenamiento": 0, "filas_validacion": 0}
    with pytest.raises(inferencia.CorteSinDatos, match=falta["motivo"]):
        inferencia.entrenar(date(2022, 10, 1), serie=vacia)


def _politica_con(monkeypatch, motivos: list[str], bloqueos: list[str], falta: dict | None) -> list:
    """decidir_reentreno con el monitoreo y los bloqueos dados y la partición del entrenamiento respondiendo `falta`;
    devuelve la lista de las veces que se consultó la partición (serie, corte)."""
    from app.servicios import ejecucion

    consultas: list = []
    monkeypatch.setattr(ejecucion, "modelo_activo", lambda s: SimpleNamespace(model_id="hgb_activo"))
    monkeypatch.setattr(politica, "antiguedad_de_datos", lambda s, activo, hasta: {})
    monkeypatch.setattr(politica, "_motivos_monitoreo", lambda s, model_id, u: list(motivos))
    monkeypatch.setattr(politica, "_bloqueos_reentreno", lambda s: list(bloqueos))
    monkeypatch.setattr(politica, "serie_validada", lambda s, datos_hasta: (("serie hasta", datos_hasta), {}))

    def corte_sin_datos(serie, corte):
        consultas.append((serie, corte))
        return falta

    monkeypatch.setattr(inferencia, "corte_sin_datos", corte_sin_datos)
    return consultas


DERIVA = "deriva: lag7 PSI 0.412"
SIN_DATOS = {"motivo": "No hay datos suficientes para entrenar y validar con ese corte", "corte": date(2022, 11, 8),
             "filas_entrenamiento": 0, "filas_validacion": 51}


def test_la_politica_no_pide_un_reentrenamiento_cuyo_corte_no_se_puede_entrenar(monkeypatch):
    """El defecto: al comienzo de la serie cada ciclo veía deriva y encolaba un entrenamiento con el corte 61 días
    antes, anterior a los datos, que siempre fallaba. Ahora no se pide: la decisión lo dice en sus bloqueos, con el
    motivo, y encolar_entrenamiento no crea el trabajo."""
    consultas = _politica_con(monkeypatch, [DERIVA], [], SIN_DATOS)
    d = politica.decidir_reentreno(None, {}, date(2023, 1, 8))
    assert d["motivos"] == [DERIVA] and d["reentrenar"] is False
    assert d["hasta"] == "2022-11-08" and d["datos_hasta"] == "2023-01-08"
    assert d["bloqueos"] == ["reentrenamiento omitido: datos insuficientes antes del corte 2022-11-08 (la serie "
                             "validada hasta 2023-01-08 deja 0 filas útiles para entrenar y 51 para validar)"]
    assert d["bloqueos"][0].startswith(politica.OMITIDO_SIN_DATOS)
    # la partición se consultó con la serie validada hasta datos_hasta (la que usaría el entrenamiento) y el corte
    assert consultas == [(("serie hasta", date(2023, 1, 8)), date(2022, 11, 8))]
    assert politica.encolar_entrenamiento(None, d, "ciclo_diario") is None       # sin sesión: no llega a usarla


def test_con_historico_suficiente_la_politica_pide_el_reentrenamiento_como_antes(monkeypatch):
    consultas = _politica_con(monkeypatch, [DERIVA], [], None)
    d = politica.decidir_reentreno(None, {}, date(2025, 9, 20))
    assert d["reentrenar"] is True and d["bloqueos"] == [] and d["motivos"] == [DERIVA]
    assert d["hasta"] == "2025-07-21" and d["datos_hasta"] == "2025-09-20"
    assert consultas == [(("serie hasta", date(2025, 9, 20)), date(2025, 7, 21))]


@pytest.mark.parametrize("motivos, bloqueos", [([], []), ([DERIVA], ["1 entrenamiento(s) en cola o corriendo"]),
                                               ([DERIVA], ["retador en sombra: hgb_candidato"])])
def test_la_particion_solo_se_consulta_si_la_politica_iba_a_pedir_el_reentrenamiento(monkeypatch, motivos, bloqueos):
    """Sin motivos, o con otro bloqueo (un entrenamiento en cola o un retador en sombra), la decisión es la de antes y
    no se recorre la serie."""
    consultas = _politica_con(monkeypatch, motivos, bloqueos, SIN_DATOS)
    d = politica.decidir_reentreno(None, {}, date(2023, 1, 8))
    assert consultas == [] and d["reentrenar"] is False and d["bloqueos"] == bloqueos and d["motivos"] == motivos
