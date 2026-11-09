"""Modelos de demanda: entrenamiento, registro, carga verificada, predicción y evaluación (especificación §9).

- Línea base (§9.1): B1 = regla manual (media de la misma hora y día de la semana de las 8 semanas anteriores) y
  B2 = última semana (misma hora hace 7 días). No tienen artefacto: se calculan con las variables b8 y lag7.
- Candidato tabular: HistGradientBoostingRegressor (pérdida Poisson) + dos modelos de cuantiles (P10 y P90, RF-006).
- División cronológica (§9.3): entrenamiento <= hasta, validación los 61 días siguientes, prueba el resto.
- Artefactos: datos/modelos/<model_id>/modelo.joblib + manifest.json (sha256, feature_version, data_cutoff, métricas,
  semilla, hiperparámetros, filas). cargar() lee el artefacto UNA vez y verifica el hash (§9.2).
- predecir(): pronóstico horario prorrateado por minutos en [instante, instante + horizonte], ajustado con un factor
  intradía calculado con observado / esperado en las 2 h previas (recortado a 0,8-1,25), usando solo horas
  cerradas antes del instante.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from datetime import UTC, date, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.inspection import permutation_importance

from . import datos, variables

ZONA = ZoneInfo("America/Bogota")
HORIZONTES = (30, 60, 120)
NOWCAST_MIN, NOWCAST_MAX = 0.8, 1.25
NOWCAST_VENTANA_H = 2
NOWCAST_MIN_ESPERADOS = 50.0  # con menos pasajeros esperados en las 2 h previas el factor queda en 1
# factor = clip(1 + peso * (observado / esperado - 1), 0,8, 1,25). El peso se calibra en la validación de cada modelo
# (entrenar); con la razón sin encoger (peso 1) el error sube, como ya advertía sistema_tiempo_real/nowcast.py.
NOWCAST_PESO_DEFECTO = 0.1
NOWCAST_PESOS = (0.0, 0.1, 0.2, 0.3, 0.5, 1.0)
DIAS_VALIDACION = 61
HIPER_DEFECTO = {
    "learning_rate": 0.05,
    "max_iter": 400,
    "max_leaf_nodes": 31,
    "min_samples_leaf": 40,
    "l2_regularization": 1.0,
}
LINEAS_BASE = {
    "b1_manual_8sem": {
        "variable": "b8",
        "descripcion": "Regla manual de Sobusa: media de la misma hora y el mismo día "
        "de la semana de las 8 semanas anteriores",
    },
    "b2_ultima_semana": {"variable": "lag7", "descripcion": "Última semana: pasajeros de la misma hora hace 7 días"},
}
REFERENCIAS_PROYECTO = [
    {
        "model_id": "ref_B1_regla_manual",
        "wape_pct": 20.04,
        "fuente": "app/DATOS.md (C1); experimentos/E11_modelo_mejorado/resultados.json",
    },
    {"model_id": "ref_E1_lightgbm", "wape_pct": 14.40, "fuente": "experimentos/E1_lgbm_salida/README.md"},
    {
        "model_id": "ref_E11_modelo_final",
        "wape_pct": 13.94,
        "fuente": "app/DATOS.md (C1); experimentos/E11_modelo_mejorado",
    },
    {
        "model_id": "ref_E12_hibrido",
        "wape_pct": 13.62,
        "fuente": "app/DATOS.md (C1, C18); experimentos/E12_comparacion_modelos",
    },
]
NOTA_REFERENCIAS = (
    "Modelos publicados por el proyecto (WAPE horario 2025, horizonte de una semana, validación mensual "
    "expansiva). Se registran como referencia: no se ejecutan dentro de la API."
)
DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


class ErrorIntegridadModelo(RuntimeError):
    """El sha256 del artefacto no coincide con el del manifiesto."""


class ModeloNoEncontrado(LookupError):
    """No existe el modelo pedido."""


_CACHE_MODELOS: dict[str, dict] = {}
_CANDADO = threading.Lock()


# ----------------------------------------------------------------------------------------------- utilidades
def _sha256(ruta: Path) -> str:
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for bloque in iter(lambda: f.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()


def metricas(y, yhat, horas=None, rutas=None, p10=None, p90=None) -> dict:
    """MAE, RMSE, WAPE (%), sesgo (%), por ruta y en horas pico (6-8 y 17-19 h) frente a valle."""
    y = np.asarray(y, dtype=float)
    yhat = np.asarray(yhat, dtype=float)

    def _basicas(m):
        if m.sum() == 0:
            return {"n": 0, "mae": None, "rmse": None, "wape": None, "sesgo_pct": None}
        e = yhat[m] - y[m]
        tot = y[m].sum()
        return {
            "n": int(m.sum()),
            "mae": round(float(np.abs(e).mean()), 3),
            "rmse": round(float(np.sqrt((e**2).mean())), 3),
            "wape": round(float(np.abs(e).sum() / tot * 100), 3) if tot > 0 else None,
            "sesgo_pct": round(float(e.sum() / tot * 100), 3) if tot > 0 else None,
        }

    todo = np.ones(len(y), dtype=bool)
    out = _basicas(todo)
    if p10 is not None and p90 is not None:
        out["cobertura_p10_p90"] = round(float(((y >= np.asarray(p10)) & (y <= np.asarray(p90))).mean() * 100), 2)
    if rutas is not None:
        rutas = np.asarray(rutas)
        out["por_ruta"] = {str(r): _basicas(rutas == r) for r in sorted(set(rutas))}
    if horas is not None:
        pico = np.isin(np.asarray(horas), datos.HORAS_PICO)
        out["pico"] = _basicas(pico)
        out["valle"] = _basicas(~pico)
    return out


@lru_cache(maxsize=2)
def _tabla_bundled(ruta_archivo: str, mtime: float) -> pd.DataFrame:
    tabla = variables.construir_variables(datos.demanda_horaria())
    return tabla.set_index(["ruta", "fecha", "hora"]).sort_index()


def tabla_variables() -> pd.DataFrame:
    """Variables de toda la serie empaquetada (se calculan una vez por versión del archivo)."""
    archivo = datos.carpeta_datos() / "demanda_horaria.parquet"
    return _tabla_bundled(str(archivo), archivo.stat().st_mtime)


def _filas_utiles(tabla: pd.DataFrame) -> pd.DataFrame:
    t = tabla.reset_index() if "ruta" not in tabla.columns else tabla
    return t[t["pasajeros"].notna() & t["b8"].notna()].copy()


def _modelo_hgb(perdida: str, semilla: int, hiper: dict, cuantil: float | None = None) -> HistGradientBoostingRegressor:
    extra = {"quantile": cuantil} if perdida == "quantile" else {}
    cats = [variables.COLUMNAS_MODELO.index(c) for c in variables.CATEGORICAS]
    return HistGradientBoostingRegressor(
        loss=perdida, random_state=semilla, early_stopping=False, categorical_features=cats, **hiper, **extra
    )


def calibrar_nowcast(parte: pd.DataFrame, pred: np.ndarray, pesos=NOWCAST_PESOS) -> dict:
    """WAPE de la hora h pronosticada a las h:00 con el factor de las horas h-1 y h-2 (cerradas), para cada peso."""
    d = parte[["ruta", "fecha", "hora", "pasajeros"]].copy()
    d["pred"] = np.asarray(pred, dtype=float)
    previa = d.rename(columns={"pasajeros": "o", "pred": "e"})
    a = d.merge(previa.assign(hora=previa["hora"] + 1), on=["ruta", "fecha", "hora"], how="left")
    a = a.merge(previa.assign(hora=previa["hora"] + 2), on=["ruta", "fecha", "hora"], how="left", suffixes=("1", "2"))
    obs, esp = a["o1"] + a["o2"], a["e1"] + a["e2"]
    ok = (obs.notna() & (esp >= NOWCAST_MIN_ESPERADOS)).to_numpy()
    v = (a["hora"] >= 6).to_numpy()
    y = a["pasajeros"].to_numpy(float)
    razon = np.where(ok, obs / esp.where(esp > 0, 1.0), 1.0)
    res = {}
    for k in pesos:
        f = np.where(ok, np.clip(1 + k * (razon - 1), NOWCAST_MIN, NOWCAST_MAX), 1.0)
        yh = a["pred"].to_numpy(float) * f
        res[str(k)] = (
            round(float(np.abs(yh[v] - y[v]).sum() / y[v].sum() * 100), 3) if v.any() and y[v].sum() > 0 else None
        )
    validos = {k: w for k, w in res.items() if w is not None}
    mejor = float(min(validos, key=validos.get)) if validos else NOWCAST_PESO_DEFECTO
    return {"peso": mejor, "wape_por_peso": res, "regla": "factor = clip(1 + peso*(obs/esp - 1), 0,8, 1,25)"}


def _pred_linea_base(nombre: str, t: pd.DataFrame) -> np.ndarray:
    var = LINEAS_BASE[nombre]["variable"]
    return t[var].fillna(t["b8"]).to_numpy(dtype=float)


# ----------------------------------------------------------------------------------------------- registro
def _ruta_registro(dir_modelos: Path) -> Path:
    return dir_modelos / "registro.json"


def registro(dir_modelos: Path | None = None) -> dict:
    dm = Path(dir_modelos) if dir_modelos else datos.carpeta_modelos()
    ruta = _ruta_registro(dm)
    if ruta.exists():
        return json.loads(ruta.read_text(encoding="utf-8"))
    return {"activo": "b1_manual_8sem", "modelos": {}, "historial_activacion": []}


def _guardar_registro(reg: dict, dir_modelos: Path) -> None:
    dir_modelos.mkdir(parents=True, exist_ok=True)
    reg["referencias_proyecto"] = {"nota": NOTA_REFERENCIAS, "modelos": REFERENCIAS_PROYECTO}
    for nombre, info in LINEAS_BASE.items():
        reg["modelos"].setdefault(
            nombre,
            {
                "model_id": nombre,
                "tipo": "linea_base",
                "estado": "referencia",
                "descripcion": info["descripcion"],
                "artefacto": None,
                "feature_version": variables.FEATURE_VERSION,
            },
        )
    _ruta_registro(dir_modelos).write_text(json.dumps(reg, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def modelo_activo(dir_modelos: Path | None = None) -> str:
    return registro(dir_modelos).get("activo") or "b1_manual_8sem"


def listar_modelos(dir_modelos: Path | None = None) -> list[dict]:
    reg = registro(dir_modelos)
    filas = [dict(m, activo=(k == reg.get("activo"))) for k, m in reg.get("modelos", {}).items()]
    for nombre, info in LINEAS_BASE.items():
        if nombre not in reg.get("modelos", {}):
            filas.append(
                {
                    "model_id": nombre,
                    "tipo": "linea_base",
                    "descripcion": info["descripcion"],
                    "activo": reg.get("activo") == nombre,
                }
            )
    filas += [
        dict(r, tipo="referencia_proyecto", ejecutable_en_api=False, nota=NOTA_REFERENCIAS)
        for r in REFERENCIAS_PROYECTO
    ]
    return filas


def activar(model_id: str, usuario: str = "sistema", motivo: str = "", dir_modelos: Path | None = None) -> dict:
    """Activa una versión registrada (también sirve para volver atrás, RF-019)."""
    dm = Path(dir_modelos) if dir_modelos else datos.carpeta_modelos()
    reg = registro(dm)
    if model_id not in reg.get("modelos", {}) and model_id not in LINEAS_BASE:
        raise ModeloNoEncontrado(f"Modelo no registrado: {model_id}")
    anterior = reg.get("activo")
    reg["activo"] = model_id
    reg.setdefault("historial_activacion", []).append(
        {
            "en": datetime.now(UTC).isoformat(timespec="seconds"),
            "de": anterior,
            "a": model_id,
            "usuario": usuario,
            "motivo": motivo,
        }
    )
    _guardar_registro(reg, dm)
    return {"activo": model_id, "anterior": anterior}


# ----------------------------------------------------------------------------------------------- entrenamiento
def entrenar(
    hasta: date = date(2025, 8, 31),
    semilla: int = 42,
    *,
    serie: pd.DataFrame | None = None,
    dir_modelos: Path | None = None,
    hiper: dict | None = None,
    activar_si_mejora: bool = True,
) -> dict:
    """Entrena el candidato (punto + P10 + P90) con datos <= hasta, lo compara con B1/B2 y lo guarda.

    Escribe el artefacto y su manifiesto en dir_modelos/<model_id>/ y actualiza registro.json.
    """
    dm = Path(dir_modelos) if dir_modelos else datos.carpeta_modelos()
    hp = dict(HIPER_DEFECTO, **(hiper or {}))
    serie = datos.demanda_horaria() if serie is None else serie
    t = _filas_utiles(variables.construir_variables(serie))
    t = t[t["fecha"] <= serie["fecha"].max()]
    fin_val = hasta + timedelta(days=DIAS_VALIDACION)
    tr, va, te = t[t["fecha"] <= hasta], t[(t["fecha"] > hasta) & (t["fecha"] <= fin_val)], t[t["fecha"] > fin_val]
    if len(tr) == 0 or len(va) == 0:
        raise ValueError("No hay datos suficientes para entrenar y validar con ese corte")

    x_tr, y_tr = variables.matriz_x(tr), tr["pasajeros"].to_numpy(float)
    t0 = time.perf_counter()
    punto = _modelo_hgb("poisson", semilla, hp).fit(x_tr, y_tr)
    q10 = _modelo_hgb("quantile", semilla, hp, 0.1).fit(x_tr, y_tr)
    q90 = _modelo_hgb("quantile", semilla, hp, 0.9).fit(x_tr, y_tr)
    seg_entrenamiento = round(time.perf_counter() - t0, 2)

    def _eval(parte: pd.DataFrame) -> dict:
        if len(parte) == 0:
            return {}
        x = variables.matriz_x(parte)
        p, lo, hi = _ordenar(punto.predict(x), q10.predict(x), q90.predict(x))
        args = {"horas": parte["hora"].to_numpy(), "rutas": parte["ruta"].to_numpy()}
        res = {"candidato": metricas(parte["pasajeros"], p, p10=lo, p90=hi, **args)}
        for nombre in LINEAS_BASE:
            res[nombre] = metricas(parte["pasajeros"], _pred_linea_base(nombre, parte), **args)
        res["desde"], res["hasta"] = str(parte["fecha"].min()), str(parte["fecha"].max())
        return res

    met = {"validacion": _eval(va), "prueba": _eval(te)}
    nowcast = calibrar_nowcast(va, punto.predict(variables.matriz_x(va)))
    nowcast["calibrado_en"] = f"validación {va['fecha'].min()} a {va['fecha'].max()}"
    if len(te):
        nowcast["prueba"] = calibrar_nowcast(te, punto.predict(variables.matriz_x(te)), (0.0, nowcast["peso"], 1.0))
    muestra = va.sample(min(3000, len(va)), random_state=semilla)
    pi = permutation_importance(
        punto,
        variables.matriz_x(muestra),
        muestra["pasajeros"].to_numpy(float),
        n_repeats=3,
        random_state=semilla,
        scoring="neg_mean_absolute_error",
    )
    importancia = sorted(
        (
            {"variable": c, "aumento_mae": round(float(v), 3)}
            for c, v in zip(variables.COLUMNAS_MODELO, pi.importances_mean, strict=False)
        ),
        key=lambda x: -x["aumento_mae"],
    )
    wape_c = met["validacion"]["candidato"]["wape"]
    wape_b1 = met["validacion"]["b1_manual_8sem"]["wape"]
    supera = wape_c is not None and wape_b1 is not None and wape_c < wape_b1

    model_id = f"hgb_{variables.FEATURE_VERSION.split('-')[0]}_{hasta:%Y%m%d}_s{semilla}"
    carpeta = dm / model_id
    carpeta.mkdir(parents=True, exist_ok=True)
    artefacto = carpeta / "modelo.joblib"
    joblib.dump(
        {
            "punto": punto,
            "p10": q10,
            "p90": q90,
            "columnas": variables.COLUMNAS_MODELO,
            "feature_version": variables.FEATURE_VERSION,
            "codigo_ruta": variables.CODIGO_RUTA,
        },
        artefacto,
        compress=3,
    )
    sha = _sha256(artefacto)
    manifiesto = {
        "model_id": model_id,
        "tipo": "candidato",
        "algoritmo": "hist_gradient_boosting",
        "estado": "activo" if (supera and activar_si_mejora) else "candidato",
        "artefacto": "modelo.joblib",
        "sha256": sha,
        "feature_version": variables.FEATURE_VERSION,
        "data_cutoff": str(hasta),
        "semilla": semilla,
        "hiperparametros": hp,
        "perdidas": {"punto": "poisson", "p10": "quantile 0.1", "p90": "quantile 0.9"},
        "variables": variables.COLUMNAS_MODELO,
        "filas_entrenamiento": len(tr),
        "filas_validacion": len(va),
        "filas_prueba": len(te),
        "particion": {
            "entrenamiento": f"{tr['fecha'].min()} a {hasta}",
            "validacion": f"{hasta + timedelta(days=1)} a {fin_val}",
            "prueba": f"{te['fecha'].min()} a {te['fecha'].max()}" if len(te) else None,
        },
        "metricas": met,
        "supera_linea_base_validacion": bool(supera),
        "nowcast": nowcast,
        "importancia_global": importancia,
        "nota_importancia": "aumento del MAE (pasajeros) al permutar la variable en 3000 horas de validación",
        "segundos_entrenamiento": seg_entrenamiento,
        "creado_en": datetime.now(UTC).isoformat(timespec="seconds"),
        "versiones": {"sklearn": __import__("sklearn").__version__, "pandas": pd.__version__, "numpy": np.__version__},
        "version_datos": {
            "sha256_serie": _huella_serie(serie),
            "filas_serie": len(serie),
            "desde": str(serie["fecha"].min()),
            "hasta": str(serie["fecha"].max()),
        },
        "codigo_sha256": {n: _sha256(Path(__file__).with_name(n)) for n in ("variables.py", "inferencia.py")},
    }
    (carpeta / "manifest.json").write_text(
        json.dumps(manifiesto, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )

    reg = registro(dm)
    reg.setdefault("modelos", {})[model_id] = {
        k: manifiesto[k]
        for k in (
            "model_id",
            "tipo",
            "algoritmo",
            "estado",
            "artefacto",
            "sha256",
            "feature_version",
            "data_cutoff",
            "semilla",
            "supera_linea_base_validacion",
            "creado_en",
        )
    }
    reg["modelos"][model_id]["wape_validacion"] = wape_c
    reg["modelos"][model_id]["wape_prueba"] = (met["prueba"].get("candidato") or {}).get("wape")
    decision = (
        "activado: mejora a B1 en validación" if supera else "se conserva el activo: no mejora a B1 en validación"
    )
    if supera and activar_si_mejora and reg.get("activo") != model_id:
        anterior = reg.get("activo")
        reg["activo"] = model_id
        reg.setdefault("historial_activacion", []).append(
            {
                "en": manifiesto["creado_en"],
                "de": anterior,
                "a": model_id,
                "usuario": "entrenamiento",
                "motivo": decision,
            }
        )
    _guardar_registro(reg, dm)
    with _CANDADO:
        _CACHE_MODELOS.pop(model_id, None)
    return {
        "model_id": model_id,
        "tipo": manifiesto["tipo"],
        "metricas": met,
        "artefacto": str(artefacto),
        "sha256": sha,
        "feature_version": variables.FEATURE_VERSION,
        "data_cutoff": hasta,
        "supera_linea_base": bool(supera),
        "decision": decision,
        "manifiesto": str(carpeta / "manifest.json"),
    }


def _huella_serie(serie: pd.DataFrame) -> str:
    """sha256 del contenido de la serie usada (ruta, fecha, hora, pasajeros): versión de los datos de entrenamiento."""
    s = serie[["ruta", "fecha", "hora", "pasajeros"]].sort_values(["ruta", "fecha", "hora"]).astype(str)
    return hashlib.sha256(pd.util.hash_pandas_object(s, index=False).to_numpy().tobytes()).hexdigest()


def _ordenar(p, lo, hi):
    p = np.clip(np.asarray(p, float), 0, None)
    lo = np.clip(np.minimum(np.asarray(lo, float), p), 0, None)
    hi = np.maximum(np.asarray(hi, float), p)
    return p, lo, hi


# ----------------------------------------------------------------------------------------------- carga
def cargar(model_id: str | None = None, dir_modelos: Path | None = None) -> dict:
    """Carga el modelo una sola vez (caché en memoria) y verifica su sha256 contra el manifiesto."""
    dm = Path(dir_modelos) if dir_modelos else datos.carpeta_modelos()
    mid = model_id or modelo_activo(dm)
    clave = f"{dm.resolve()}::{mid}"
    with _CANDADO:
        if clave in _CACHE_MODELOS:
            return _CACHE_MODELOS[clave]
        if mid in LINEAS_BASE:
            info = {
                "model_id": mid,
                "tipo": "linea_base",
                "feature_version": variables.FEATURE_VERSION,
                "data_cutoff": None,
                "manifiesto": {"descripcion": LINEAS_BASE[mid]["descripcion"]},
            }
            _CACHE_MODELOS[clave] = info
            return info
        carpeta = dm / mid
        ruta_man = carpeta / "manifest.json"
        if not ruta_man.exists():
            raise ModeloNoEncontrado(f"No existe el manifiesto del modelo {mid} en {carpeta}")
        man = json.loads(ruta_man.read_text(encoding="utf-8"))
        artefacto = carpeta / man["artefacto"]
        sha = _sha256(artefacto)
        if sha != man["sha256"]:
            raise ErrorIntegridadModelo(
                f"El hash del artefacto de {mid} no coincide con el manifiesto "
                f"(esperado {man['sha256'][:12]}..., calculado {sha[:12]}...)"
            )
        if man.get("feature_version") != variables.FEATURE_VERSION:
            raise ErrorIntegridadModelo(
                f"{mid} usa variables {man.get('feature_version')} y el código {variables.FEATURE_VERSION}"
            )
        obj = joblib.load(artefacto)
        info = {
            "model_id": mid,
            "tipo": man["tipo"],
            "feature_version": man["feature_version"],
            "data_cutoff": date.fromisoformat(man["data_cutoff"]),
            "sha256": sha,
            "manifiesto": man,
            "punto": obj["punto"],
            "p10": obj["p10"],
            "p90": obj["p90"],
        }
        _CACHE_MODELOS[clave] = info
        return info


def precalentar(model_id: str | None = None) -> dict:
    """Carga el modelo activo y las variables al arrancar la API (la primera predicción no paga ese costo)."""
    t0 = time.perf_counter()
    info = cargar(model_id)
    tabla_variables()
    return {"model_id": info["model_id"], "segundos": round(time.perf_counter() - t0, 2)}


def limpiar_cache() -> None:
    with _CANDADO:
        _CACHE_MODELOS.clear()
    _tabla_bundled.cache_clear()


def _predecir_filas(modelo: dict, filas: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    if modelo["tipo"] == "linea_base":
        p = _pred_linea_base(modelo["model_id"], filas)
        sd = filas["sd8"].fillna(0).to_numpy(float)
        return _ordenar(p, p - 1.2816 * sd, p + 1.2816 * sd)
    x = variables.matriz_x(filas)
    return _ordenar(modelo["punto"].predict(x), modelo["p10"].predict(x), modelo["p90"].predict(x))


def _predecir_punto(modelo: dict, filas: pd.DataFrame) -> np.ndarray:
    """Solo el pronóstico puntual (lo que necesita el factor intradía)."""
    if modelo["tipo"] == "linea_base":
        return np.clip(_pred_linea_base(modelo["model_id"], filas), 0, None)
    return np.clip(modelo["punto"].predict(variables.matriz_x(filas)), 0, None)


# ----------------------------------------------------------------------------------------------- predicción
def _a_bogota(instante: datetime | str) -> datetime:
    if isinstance(instante, str):
        instante = datetime.fromisoformat(instante)
    instante = pd.Timestamp(instante).to_pydatetime()
    if instante.tzinfo is None:
        return instante.replace(tzinfo=ZONA)
    return instante.astimezone(ZONA)


def _tramos(inicio: datetime, fin: datetime) -> list[tuple[date, int, float]]:
    """Horas (fecha, hora) que cruzan [inicio, fin) con la fracción de la hora cubierta (minutos / 60)."""
    out = []
    h = inicio.replace(minute=0, second=0, microsecond=0)
    while h < fin:
        sig = h + timedelta(hours=1)
        minutos = (min(sig, fin) - max(h, inicio)).total_seconds() / 60.0
        if minutos > 0:
            out.append((h.date(), h.hour, minutos / 60.0))
        h = sig
    return out


def _filas_variables(tabla: pd.DataFrame, ruta: str, tramos: list) -> pd.DataFrame:
    claves = [(ruta, f, h) for f, h, _ in tramos if h in datos.HORAS_SERVICIO]
    if not claves:
        return pd.DataFrame(columns=list(tabla.columns) + ["ruta", "fecha", "hora"])
    faltan = [c for c in claves if c not in tabla.index]
    if faltan:
        lo, hi = datos.rango_fechas()
        raise ValueError(
            f"Sin variables para {faltan[0][1]} {faltan[0][2]}:00: el pronóstico cubre {lo} a "
            f"{hi + timedelta(days=variables.DIAS_EXTRA)} (rezagos de 7 días o más)"
        )
    return tabla.loc[claves].reset_index()


def _num(x: float, dec: int = 2) -> str:
    """Número con coma decimal (es-CO)."""
    return f"{x:.{dec}f}".replace(".", ",")


def _observado(
    serie: pd.DataFrame | None, ruta: str, f: date, h: int, tabla: pd.DataFrame | None = None
) -> float | None:
    if serie is None and tabla is not None:
        try:
            v = tabla.at[(ruta, f, h), "pasajeros"]  # las horas excluidas ya vienen como faltantes
        except KeyError:
            return None
        return None if pd.isna(v) else float(v)
    if serie is None:
        serie = datos.demanda_horaria(desde=f, hasta=f, rutas=[ruta])
    fila = serie[(serie["ruta"] == ruta) & (serie["fecha"] == f) & (serie["hora"] == h)]
    if fila.empty or pd.isna(fila["pasajeros"].iloc[0]):
        return None
    if "excluido" in fila.columns and int(fila["excluido"].iloc[0]) == 1:
        return None
    return float(fila["pasajeros"].iloc[0])


def factor_nowcast(
    ruta: str, instante: datetime, modelo: dict, tabla: pd.DataFrame, serie_observada: pd.DataFrame | None = None
) -> dict:
    """observado / esperado en las 2 h previas, solo con horas cerradas antes del instante (sin fuga)."""
    inicio = instante - timedelta(hours=NOWCAST_VENTANA_H)
    tramos = [
        (f, h, fr)
        for f, h, fr in _tramos(inicio, instante)
        if h in datos.HORAS_SERVICIO
        and datetime(f.year, f.month, f.day, h, tzinfo=ZONA) + timedelta(hours=1) <= instante
    ]
    obs = esp = 0.0
    usados = []
    peso = float((modelo.get("manifiesto") or {}).get("nowcast", {}).get("peso", NOWCAST_PESO_DEFECTO))
    if tramos:
        try:
            filas = _filas_variables(tabla, ruta, tramos)
        except ValueError:
            filas = None
        if filas is not None and len(filas):
            p = _predecir_punto(modelo, filas)
            for (f, h, fr), pe in zip(tramos, p, strict=False):
                o = _observado(serie_observada, ruta, f, h, tabla)
                if o is None:
                    continue
                obs += fr * o
                esp += fr * float(pe)
                usados.append(
                    {
                        "fecha": str(f),
                        "hora": h,
                        "fraccion": round(fr, 3),
                        "observado": o,
                        "esperado": round(float(pe), 1),
                    }
                )
    if usados and esp >= NOWCAST_MIN_ESPERADOS:
        crudo = obs / esp
        return {
            "factor": float(np.clip(1 + peso * (crudo - 1), NOWCAST_MIN, NOWCAST_MAX)),
            "razon_cruda": round(crudo, 4),
            "peso": peso,
            "observado_2h": round(obs, 1),
            "esperado_2h": round(esp, 1),
            "horas": usados,
            "aplicado": True,
        }
    return {
        "factor": 1.0,
        "razon_cruda": None,
        "observado_2h": round(obs, 1),
        "esperado_2h": round(esp, 1),
        "horas": usados,
        "aplicado": False,
        "peso": peso,
    }


def predecir(
    ruta: str,
    instante: datetime,
    horizonte_min: int,
    model_id: str | None = None,
    *,
    usar_nowcast: bool = True,
    serie_observada: pd.DataFrame | None = None,
    dir_modelos: Path | None = None,
) -> dict:
    """Pasajeros esperados en [instante, instante + horizonte] para la ruta, con P10/P90 y explicación."""
    t0 = time.perf_counter()
    if int(horizonte_min) not in HORIZONTES:
        raise ValueError(f"horizonte_min debe ser uno de {HORIZONTES}")
    try:
        ruta = datos.ruta_info(ruta)["ruta"]
    except KeyError as exc:
        raise ValueError(str(exc)) from exc
    inst = _a_bogota(instante)
    fin = inst + timedelta(minutes=int(horizonte_min))
    modelo = cargar(model_id, dir_modelos)
    tabla = tabla_variables()
    tramos = _tramos(inst, fin)
    filas = _filas_variables(tabla, ruta, tramos)
    servicio = [(f, h, fr) for f, h, fr in tramos if h in datos.HORAS_SERVICIO]
    if len(filas):
        p, lo, hi = _predecir_filas(modelo, filas)
    else:
        p = lo = hi = np.zeros(0)
    fr = np.array([x[2] for x in servicio], dtype=float)
    base, base_lo, base_hi = float((fr * p).sum()), float((fr * lo).sum()), float((fr * hi).sum())
    nc = (
        factor_nowcast(ruta, inst, modelo, tabla, serie_observada)
        if usar_nowcast
        else {
            "factor": 1.0,
            "aplicado": False,
            "observado_2h": None,
            "esperado_2h": None,
            "horas": [],
            "razon_cruda": None,
            "peso": None,
        }
    )
    k = nc["factor"]

    if len(filas):
        i = int(np.argmax(fr))
        r = filas.iloc[i]
        principal = {
            "fecha": str(r["fecha"]),
            "hora": int(r["hora"]),
            "dia_semana": DIAS[int(r["dia_semana"])],
            "tipo_dia": datos.TIPOS_DIA[int(r["tipo_dia"])],
            "festivo": bool(r["festivo"]),
            "lag7": None if pd.isna(r["lag7"]) else float(r["lag7"]),
            "b8_regla_manual": None if pd.isna(r["b8"]) else round(float(r["b8"]), 1),
            "nivel_7_34": None if pd.isna(r["nivel_7_34"]) else round(float(r["nivel_7_34"]), 1),
        }
    else:
        principal = {"hora": inst.hour, "dia_semana": DIAS[inst.weekday()], "fuera_de_servicio": True}
    explicacion = []
    if len(filas):
        explicacion.append(
            f"Hora {principal['hora']}:00 del {principal['dia_semana']} ({principal['tipo_dia'].lower()}"
            f"{', festivo' if principal['festivo'] else ''})"
        )
        if principal["lag7"] is not None:
            explicacion.append(f"Misma hora hace 7 días: {principal['lag7']:.0f} pasajeros")
        if principal["b8_regla_manual"] is not None:
            explicacion.append(f"Regla manual (media de 8 semanas): {principal['b8_regla_manual']:.0f} pasajeros")
    else:
        explicacion.append("La ventana cae fuera del horario de salidas (4-20 h): demanda 0")
    if nc["aplicado"]:
        explicacion.append(
            f"Factor intradía {_num(k)}: observado {nc['observado_2h']:.0f} frente a esperado "
            f"{nc['esperado_2h']:.0f} en las 2 h previas (razón {_num(nc['razon_cruda'])}, peso "
            f"{_num(nc['peso'], 1)}, recortado a {_num(NOWCAST_MIN, 1)}-{_num(NOWCAST_MAX)})"
        )
    else:
        explicacion.append("Sin observaciones suficientes en las 2 h previas: factor intradía 1,00")
    explicacion.append(
        f"Ventana de {int(horizonte_min)} min prorrateada por minutos sobre {len(servicio)} hora(s) de servicio"
    )
    imp = (modelo.get("manifiesto") or {}).get("importancia_global") or []
    if imp:
        explicacion.append("Variables más influyentes del modelo: " + ", ".join(x["variable"] for x in imp[:3]))

    por_hora = [
        {
            "fecha": str(f),
            "hora": h,
            "fraccion": round(x, 3),
            "pasajeros_hora": round(float(a), 1),
            "p10_hora": round(float(b), 1),
            "p90_hora": round(float(c), 1),
        }
        for (f, h, x), a, b, c in zip(servicio, p, lo, hi, strict=False)
    ]
    return {
        "ruta": ruta,
        "instante": inst,
        "horizonte_min": int(horizonte_min),
        "ventana_inicio": inst,
        "ventana_fin": fin,
        "pasajeros": round(base * k, 2),
        "p10": round(base_lo * k, 2),
        "p90": round(base_hi * k, 2),
        "pasajeros_sin_ajuste": round(base, 2),
        "model_id": modelo["model_id"],
        "tipo_modelo": modelo["tipo"],
        "feature_version": modelo["feature_version"],
        "data_cutoff": modelo["data_cutoff"],
        "generated_at": datetime.now(UTC),
        "latencia_ms": round((time.perf_counter() - t0) * 1000, 2),
        "explicacion": explicacion,
        "variables": dict(
            principal,
            factor_nowcast=round(k, 4),
            nowcast_aplicado=nc["aplicado"],
            observado_2h=nc["observado_2h"],
            esperado_2h=nc["esperado_2h"],
            razon_cruda=nc["razon_cruda"],
            horas_nowcast=nc["horas"],
            por_hora=por_hora,
        ),
    }


# ----------------------------------------------------------------------------------------------- evaluación
def evaluar(model_id: str | None, desde: date, hasta: date, dir_modelos: Path | None = None) -> dict:
    """Métricas del modelo (o de una línea base) sobre los datos reales entre desde y hasta."""
    modelo = cargar(model_id, dir_modelos)
    desde, hasta = pd.Timestamp(desde).date(), pd.Timestamp(hasta).date()
    t = _filas_utiles(tabla_variables())
    t = t[(t["fecha"] >= desde) & (t["fecha"] <= hasta)]
    if t.empty:
        raise ValueError(f"No hay datos reales entre {desde} y {hasta}")
    p, lo, hi = _predecir_filas(modelo, t)
    m = metricas(t["pasajeros"], p, horas=t["hora"].to_numpy(), rutas=t["ruta"].to_numpy(), p10=lo, p90=hi)
    m.update(
        {
            "model_id": modelo["model_id"],
            "desde": desde,
            "hasta": hasta,
            "fuera_de_muestra": modelo["data_cutoff"] is None or desde > modelo["data_cutoff"],
        }
    )
    return m
