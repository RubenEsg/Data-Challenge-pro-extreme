"""Controles compartidos por varias pantallas, con los nombres y el orden fijos de DISENO.md §6 (regla 13):
el selector de día de 2025 (solo los días con datos), el de ruta («Las tres rutas» · SILENCIO · CRA 54 · CL 72) y el de
modelo (regla manual · E1 · modelo final (E11) · híbrido (E12), con el híbrido elegido por defecto)."""
from functools import lru_cache

import pandas as pd
from dash import dcc, html

import datos_app as D
import ui

FECHA_INICIAL = "2025-06-03"     # el día de ejemplo de la app HTML (martes laboral)
RUTAS = [("Las tres rutas", "todas"), ("SILENCIO", "SILENCIO"), ("CRA 54", "CRA 54"), ("CL 72", "CL 72")]
RUTA_INICIAL = "CRA 54"
MODELO_INICIAL = "E12"           # el híbrido, el recomendado para producción


@lru_cache(maxsize=1)
def _fechas():
    dias = pd.to_datetime(sorted(D.pronosticos()["dia"].unique()))
    hay = set(dias)
    faltan = tuple(d.strftime("%Y-%m-%d") for d in pd.date_range("2025-01-01", "2025-12-31") if d not in hay)
    return dias[0], dias[-1], faltan


def selector_fecha(id_base, valor=FECHA_INICIAL):
    """Botón redondo «Día anterior» → dcc.DatePickerSingle (36 px, borde --linea-fuerte) → «Día siguiente». Los ids
    «<id_base>-ant» y «<id_base>-sig» son los de los botones (mover_fecha da el día con datos)."""
    ini, fin, faltan = _fechas()
    return html.Div([
        html.Button(ui.icono("chevron-izquierda", "glifo--m"), id=f"{id_base}-ant", type="button",
                    className="boton boton--secundario boton--icono", title="Día anterior", **{"aria-label": "Día anterior"}),
        dcc.DatePickerSingle(id=id_base, date=valor, min_date_allowed=ini.date(), max_date_allowed=fin.date(),
                             disabled_days=list(faltan), display_format="DD/MM/YYYY", month_format="MM/YYYY", first_day_of_week=1,
                             clearable=False, placeholder="Elige un día", persistence=True, persistence_type="session", className="fecha"),
        html.Button(ui.icono("chevron-derecha", "glifo--m"), id=f"{id_base}-sig", type="button",
                    className="boton boton--secundario boton--icono", title="Día siguiente", **{"aria-label": "Día siguiente"}),
    ], className="selector-fecha")


def mover_fecha(fecha, paso):
    """Día anterior (paso = −1) o siguiente (+1) con datos, sin salir de 2025."""
    ini, fin, faltan = _fechas()
    f = pd.Timestamp(fecha) + pd.Timedelta(days=paso)
    while f.strftime("%Y-%m-%d") in faltan and ini <= f <= fin:
        f += pd.Timedelta(days=paso)
    return min(max(f, ini), fin).strftime("%Y-%m-%d")


def selector_ruta(id_, valor=RUTA_INICIAL):
    """Segmentado de ruta: «Las tres rutas» · SILENCIO · CRA 54 · CL 72 (los mismos nombres en Pronóstico y en Horario)."""
    return ui.segmentado(id_, [{"label": a, "value": b} for a, b in RUTAS], valor)


def selector_modelo(id_, modelos=("E11", "E12"), valor=MODELO_INICIAL, nombres=None, pequeno=False):
    """Segmentado de modelos en el orden fijo (regla manual · E1 · E11 · E12), con el híbrido por defecto. `nombres` cambia
    el rótulo de alguno (p. ej. {"E1": "E1 (plan publicado)"} en Horario o {"E12": "Híbrido (E12) · recomendado"})."""
    rotulos = dict(ui.NOMBRE_MODELO, **(nombres or {}))
    orden = [m for m in ui.ORDEN_MODELOS if m in modelos]
    return ui.segmentado(id_, [{"label": rotulos[m], "value": m} for m in orden], valor if valor in orden else orden[-1], pequeno)
