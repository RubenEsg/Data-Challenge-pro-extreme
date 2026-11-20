"""Reentrenamiento controlado del pronóstico de corto plazo (spec v1.5 RF-018c, §9.5-e, §9.5-j, §14.2 «Incremental 3»).

El modelo de 30, 60 y 120 minutos se reentrena como el horario (app/servicios/politica.py), con sus mismos umbrales
versionados de threshold_config:

- cuándo: al cerrar cada ciclo diario, la política mira la periodicidad (`reentreno_periodicidad_dias` días de datos
  nuevos desde lo último que vio una versión de la familia), la degradación (WAPE móvil sobre `wape_max` en las últimas
  `reentreno_dias_degradacion` filas de monitoreo), la deriva (PSI en alerta de una variable disparadora) y la cobertura
  P10-P90 baja (decidir). No se reemplaza el modelo con cada registro: el corte nuevo tiene que agregar al menos
  `reentreno_periodicidad_dias` días de entrenamiento al de la última versión, y no se pide otro con un entrenamiento
  en cola o un retador en sombra. `reentreno_en_ciclo` = 0 lo apaga, como al horario; la variable de entorno
  REENTRENO_CORTO_PLAZO_EN_CICLO=false lo apaga solo para el corto plazo (las pruebas generales la usan).
- con qué: el histórico VALIDADO de la API, el mismo que usa el pronóstico (corto_plazo.serie_completa con la sesión:
  el panel empaquetado con VAL-009 y lo que leyó la lectura de 15 minutos, truncado en datos_hasta). Entrenamiento:
  todo hasta el corte; validación: los 61 días siguientes (corte + 1 .. datos_hasta), con los que se ajusta la banda
  P10-P90 conformal por tramo, como en E14. La configuración es la elegida en la validación de E14 (variables,
  hiperparámetros, estructura y semilla): reentrenar no vuelve a elegir nada.
- cómo: un trabajo «entrenamiento» de la cola con familia=corto_plazo (RNF-004: tarda del orden de 15 minutos, con
  progreso y reintento), que escribe los 18 artefactos con su SHA-256 en una carpeta temporal, la publica de una vez y
  registra la versión como CANDIDATA (registro de artefactos y model_registry, familia corto_plazo). Nunca pisa la
  activa: el model_id lleva el corte (cp_lgbm_AAAAMMDD_sNN).
- y después: el candidato queda en sombra los `sombra_dias` días que siguen a datos_hasta; cuando el ciclo los leyó
  enteros, la compuerta de cuatro criterios (gobierno_corto_plazo.compuerta) lo compara con el activo en esa misma
  ventana y lo activa (activacion_automatica = 1), lo deja aprobado para un admin o lo rechaza (revisar_sombra). La
  activación y la reversión manuales siguen siendo POST /models/{model_id}/activate y POST /models/rollback.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import logging
import os
import platform
import shutil
import time
import uuid
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any

import numpy as np

from . import corto_plazo as cp
from . import variables_corto_plazo as V

LOG = logging.getLogger("api_frecuencias.reentreno_corto_plazo")
FAMILIA = "corto_plazo"
NIVELES_CON_MODELO = ("ruta", "segmento")
ENV_EN_CICLO = "REENTRENO_CORTO_PLAZO_EN_CICLO"
MINIMO_FILAS = 200                 # filas útiles por ruta, nivel y horizonte para entrenar y para ajustar la banda
MINIMO_DIAS_VALIDACION = 14
HISTORIA_MINIMA_DIAS = 180         # días de historia (después del arranque de 8 semanas) antes del corte
CONFIGURACION = ("la elegida en la validación de E14 (pronostico_corto_plazo/resultados/seleccion.json): mismas "
                 "variables, hiperparámetros, estructura y semilla; reentrenar no vuelve a elegir nada")


class ErrorReentreno(Exception):
    """Un reentrenamiento que no se puede hacer con esos datos (no mejora reintentando)."""


def en_ciclo_habilitado() -> bool:
    return os.environ.get(ENV_EN_CICLO, "true").strip().lower() not in ("0", "false", "no")


def model_id_de(corte: date, semilla: int = V.SEMILLA) -> str:
    return f"cp_lgbm_{corte:%Y%m%d}_s{int(semilla)}"


def _fecha(v) -> date | None:
    from app.servicios import politica

    return politica._fecha(v)


# ----------------------------------------------------------------------------------------------- entrenamiento
def _ajustar(x: np.ndarray, y: np.ndarray, hiper: dict, semilla: int):
    import lightgbm as lgb

    return lgb.LGBMRegressor(**dict(V.HIPER, **hiper), random_state=int(semilla), n_jobs=V.HILOS, verbose=-1,
                             deterministic=True, force_row_wise=True).fit(x, y)


def conformal_ajustar(y: np.ndarray, p: np.ndarray, n_tramos: int = 4) -> dict:
    """Banda P10-P90 conformal por tramo del pronóstico (Mondrian), la misma de E14 (pronostico_corto_plazo/comun.py):
    cuantiles 10 % y 90 % del puntaje (y - p) / raíz(p + 1) en cada tramo."""
    y, p = np.asarray(y, float), np.asarray(p, float)
    cortes = np.unique(np.quantile(p, np.linspace(0, 1, n_tramos + 1)[1:-1]))
    tramo = np.searchsorted(cortes, p)
    s = (y - p) / np.sqrt(p + 1)
    q = {int(t): [float(np.quantile(s[tramo == t], 0.10)), float(np.quantile(s[tramo == t], 0.90))]
         for t in np.unique(tramo)}
    return {"cortes": [float(c) for c in cortes], "q": q}


def _medidas(y: np.ndarray, p: np.ndarray, cal: dict) -> dict:
    lo, hi = V.conformal_aplicar(p, cal)
    m = V.metricas(y, p)
    m["cobertura_p10_p90"] = round(100 * float(((lo <= y) & (y <= hi)).mean()), 2) if len(y) else None
    return m


def _sha256(ruta) -> str:
    h = hashlib.sha256()
    with ruta.open("rb") as f:
        for bloque in iter(lambda: f.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()


def _por_sentido(a: np.ndarray, ida: np.ndarray) -> np.ndarray:
    return np.stack([a[:, :, ida].sum(axis=2), a[:, :, ~ida].sum(axis=2)], axis=2)


class _Entrenamiento:
    """Los 18 artefactos de una versión: estado del entrenamiento de una ruta, nivel y horizonte a la vez."""

    def __init__(self, base: dict, corte: date, datos_hasta: date, semilla: int, carpeta,
                 avance: Callable[[float, str], None] | None):
        self.base, self.semilla, self.carpeta, self.avance = base, semilla, carpeta, avance
        self.d_corte, self.d_hasta = cp.dia_de_fecha(corte), cp.dia_de_fecha(datos_hasta)
        self.artefactos: dict[str, dict] = {}
        self.banda: dict = {n: {str(h): {} for h in V.HORIZONTES} for n in V.NIVELES}
        self.validacion: dict = {n: {str(h): {} for h in V.HORIZONTES} for n in V.NIVELES}
        self.hechos = 0

    def ruta(self, r: V.Ruta) -> None:
        r = r.recorte(0, self.d_hasta)
        for nivel in NIVELES_CON_MODELO:
            for h in V.HORIZONTES:
                self._uno(r, nivel, h)

    def _uno(self, r: V.Ruta, nivel: str, h: int) -> None:
        import lightgbm as lgb

        t0 = time.time()
        v = V.variables(r, nivel, h, self.base["conjunto"][nivel])
        util = v["ok"] & ~np.isnan(v["base"]["promedio_dia_hora"])
        tr = util & (v["dia"] >= V.ARRANQUE) & (v["dia"] <= self.d_corte)
        bloque = (v["dia"] > self.d_corte) & (v["dia"] <= self.d_hasta)
        x_va, y_va, ok_va, forma, nombres = v["x"][bloque], v["y"][bloque], util[bloque], v["forma"], v["nombres"]
        x_tr, y_tr = v["x"][tr], v["y"][tr]
        del v
        if len(y_tr) < MINIMO_FILAS or int(ok_va.sum()) < MINIMO_FILAS:
            raise ErrorReentreno(f"{r.nombre}, {nivel}, {h} min: {len(y_tr)} filas útiles para entrenar y "
                                 f"{int(ok_va.sum())} para validar (hacen falta {MINIMO_FILAS})")
        modelo = _ajustar(x_tr, y_tr, self.base["hiperparametros"][nivel]["valores"], self.semilla)
        texto = modelo.booster_.model_to_string()
        clave = cp.clave_artefacto(nivel, h, r.idruta)
        archivo = self.carpeta / f"{clave}.txt.gz"
        archivo.write_bytes(gzip.compress(texto.encode("utf-8"), compresslevel=9, mtime=0))
        # la banda se ajusta con las predicciones del árbol tal como se servirá (leído del texto, float32, ≥ 0)
        p_va = np.clip(lgb.Booster(model_str=texto).predict(x_va), 0, None).astype(np.float32)
        g = modelo.booster_.feature_importance(importance_type="gain")
        self.artefactos[clave] = {
            "archivo": archivo.name, "sha256": _sha256(archivo), "nivel": nivel, "horizonte_min": h,
            "idruta": r.idruta, "ruta": r.nombre, "filas_entrenamiento": int(len(y_tr)), "variables": nombres,
            "importancia_ganancia": dict(zip(nombres, (g / max(g.sum(), 1e-12)).round(5).tolist(), strict=True)),
            "segundos": round(time.time() - t0, 1)}
        self._banda(r, nivel, h, y_va, p_va, ok_va, forma)
        self.hechos += 1
        if self.avance:
            total = len(V.RUTAS) * len(NIVELES_CON_MODELO) * len(V.HORIZONTES)
            self.avance(10 + 75 * self.hechos / total, f"{self.hechos} de {total} artefactos ({clave})")

    def _banda(self, r: V.Ruta, nivel: str, h: int, y: np.ndarray, p: np.ndarray, ok: np.ndarray, forma) -> None:
        cal = conformal_ajustar(y[ok], p[ok])
        self.banda[nivel][str(h)][r.nombre] = cal
        self.validacion[nivel][str(h)][r.nombre] = _medidas(y[ok], p[ok], cal)
        if nivel != "segmento":
            return
        # sentido = suma de sus segmentos (la estructura elegida en E14), con su propia banda
        dias = len(y) // (forma[1] * forma[2])
        ida = (r.seg["sentido"] == "ida").to_numpy()
        ok3 = ok.reshape(dias, forma[1], forma[2]).all(axis=2)
        y_s = _por_sentido(y.reshape(dias, forma[1], forma[2]), ida)[ok3].reshape(-1)
        p_s = _por_sentido(p.reshape(dias, forma[1], forma[2]), ida)[ok3].reshape(-1)
        cal_s = conformal_ajustar(y_s, p_s)
        self.banda["sentido"][str(h)][r.nombre] = cal_s
        self.validacion["sentido"][str(h)][r.nombre] = _medidas(y_s, p_s, cal_s)


def _validar_fechas(corte: date, datos_hasta: date, ultimo: date) -> None:
    if datos_hasta > ultimo:
        raise ErrorReentreno(f"datos_hasta {datos_hasta} es posterior al último día con datos leídos ({ultimo})")
    if (datos_hasta - corte).days < MINIMO_DIAS_VALIDACION:
        raise ErrorReentreno(f"La validación {corte + timedelta(days=1)}..{datos_hasta} tiene menos de "
                             f"{MINIMO_DIAS_VALIDACION} días: no alcanza para ajustar la banda")
    if cp.dia_de_fecha(corte) < V.ARRANQUE + HISTORIA_MINIMA_DIAS:
        raise ErrorReentreno(f"El corte {corte} deja menos de {HISTORIA_MINIMA_DIAS} días de historia después del "
                             f"arranque de {V.ARRANQUE} días")


def _manifiesto(mid: str, base_id: str, base: dict, ent: _Entrenamiento, corte: date, datos_hasta: date,
                leido: dict, origen: dict | None, t0: float) -> dict:
    import lightgbm
    import pandas as pd

    inicio_val = corte + timedelta(days=1)
    return {
        "model_id": mid, "tipo": cp.TIPO, "feature_version": V.VERSION_VARIABLES,
        "descripcion": base.get("descripcion"), "data_cutoff": corte.isoformat(),
        "datos_hasta": datos_hasta.isoformat(),
        "entrenado_con": f"{V.DIA0.date()} a {corte} (histórico validado de la API: el panel empaquetado con VAL-009 "
                         f"y lo leído en bloques de 15 minutos)",
        "periodos": {"entrenamiento": [V.DIA0.date().isoformat(), corte.isoformat()],
                     "validacion": [inicio_val.isoformat(), datos_hasta.isoformat()]},
        "semilla": ent.semilla, "conjunto": base["conjunto"], "estructura": base["estructura"],
        "hiperparametros": base["hiperparametros"],
        "banda": {"metodo": "conformal de Mondrian por tramo del pronóstico, puntaje (y - p) / raíz(p + 1), cuantiles "
                            f"10 % y 90 % ajustados en la validación ({inicio_val} a {datos_hasta})",
                  "calibracion": ent.banda},
        "artefactos": ent.artefactos,
        "version_datos": {"panel": base.get("version_datos"), "leido": leido},
        "origen": {"reentrenamiento": {"base": base_id, "configuracion": CONFIGURACION, **(origen or {})}},
        "metricas_prueba": None, "metricas_validacion": ent.validacion, "huella_codigo": cp.huellas_codigo(),
        "versiones": {"python": platform.python_version(), "lightgbm": lightgbm.__version__,
                      "numpy": np.__version__, "pandas": pd.__version__},
        "segundos": round(time.time() - t0, 1), "generado_en": datetime.now(UTC).isoformat(timespec="seconds")}


def _exportar_onnx(mid: str) -> dict:
    """La exportación ONNX del candidato si el conversor está disponible (necesita el paquete onnx, que la imagen no
    trae: el motor por omisión es LightGBM). Sin ella, MOTOR_INFERENCIA=onnx no puede servir esa versión."""
    try:
        import onnx  # noqa: F401
    except ImportError:
        return {"exportado": False, "motivo": "el paquete onnx no está instalado: el candidato se sirve con LightGBM "
                                              "(corra scripts/exportar_onnx_corto_plazo.py --model-id para exportarlo)"}
    from app.servicios import onnx_corto_plazo as O

    modelo = cp.cargar(mid)
    carpeta = cp.carpeta_modelos() / mid / cp.CARPETA_ONNX
    carpeta.mkdir(parents=True, exist_ok=True)
    man: dict = {"model_id": mid, "generado_en": datetime.now(UTC).isoformat(timespec="seconds"),
                 "conversor": "app/servicios/onnx_corto_plazo.py (TreeEnsembleRegressor ai.onnx.ml 3 + Exp)",
                 "artefactos": {}}
    for clave, booster in modelo["arboles"].items():
        datos = O.convertir(booster, clave).SerializeToString()
        comprimido = gzip.compress(datos, mtime=0)
        (carpeta / f"{clave}.onnx.gz").write_bytes(comprimido)
        man["artefactos"][clave] = {"archivo": f"{clave}.onnx.gz", "sha256": hashlib.sha256(comprimido).hexdigest()}
    (carpeta / cp.ARCHIVO_ONNX).write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"exportado": True, "artefactos": len(man["artefactos"])}


def _ya_registrado(mid: str) -> dict | None:
    """Un reintento del mismo trabajo (RNF-001) no vuelve a entrenar una versión que ya quedó registrada."""
    if mid not in (cp.registro().get("modelos") or {}):
        return None
    ruta = cp.carpeta_modelos() / mid / cp.ARCHIVO_MANIFIESTO
    return json.loads(ruta.read_text(encoding="utf-8")) if ruta.exists() else None


def preparar(s, corte: date, datos_hasta: date | None = None, semilla: int = V.SEMILLA) -> dict:
    """Lo que el entrenamiento necesita de la base, leído en una sola transacción corta: la configuración de la versión
    activa, las fechas validadas y la serie validada de cada ruta (el panel con VAL-009 más lo leído). ErrorReentreno
    si los datos no alcanzan; {"previo": manifiesto} si esa versión ya quedó registrada (un reintento)."""
    from app.servicios import ejecucion, gobierno_corto_plazo, politica
    from app.servicios import panel_corto_plazo as P

    activo = ejecucion.modelo_activo(s, FAMILIA)
    base_id = activo.model_id if activo else cp.modelo_activo()
    if not base_id:
        raise ErrorReentreno("No hay una versión de corto plazo de la que tomar la configuración")
    datos_hasta = datos_hasta or corte + timedelta(days=politica.DIAS_VALIDACION)
    mid = model_id_de(corte, semilla)
    previo = _ya_registrado(mid)
    if previo is not None:
        return {"model_id": mid, "previo": previo}
    if mid == base_id:
        raise ErrorReentreno(f"{mid} es la versión activa: el reentrenamiento nunca la pisa")
    with cp.con_sesion(s):
        _validar_fechas(corte, datos_hasta, gobierno_corto_plazo._ultimo_dia_con_datos())
        series = {idruta: cp.serie_completa(idruta).ruta for idruta in V.RUTAS}
        leido = {V.RUTAS[i]: P.leidos(s, i).version for i in V.RUTAS}
    return {"model_id": mid, "base_id": base_id, "base": cp.cargar(base_id)["manifiesto"], "corte": corte,
            "datos_hasta": datos_hasta, "semilla": int(semilla), "series": series, "leido": leido}


def entrenar_preparado(prep: dict, *, origen: dict | None = None,
                       avance: Callable[[float, str], None] | None = None) -> dict:
    """Entrena los 18 artefactos sin tocar la base, los publica de una vez (carpeta temporal y renombre) y registra la
    versión como candidata en el registro de artefactos. Devuelve el manifiesto."""
    if "previo" in prep:
        return prep["previo"]
    t0 = time.time()
    mid = prep["model_id"]
    temporal = cp.carpeta_modelos() / f".{mid}.{uuid.uuid4().hex[:8]}"
    temporal.mkdir(parents=True)
    try:
        ent = _Entrenamiento(prep["base"], prep["corte"], prep["datos_hasta"], prep["semilla"], temporal, avance)
        for r in prep["series"].values():
            ent.ruta(r)
        man = _manifiesto(mid, prep["base_id"], prep["base"], ent, prep["corte"], prep["datos_hasta"], prep["leido"],
                          origen, t0)
        (temporal / cp.ARCHIVO_MANIFIESTO).write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding="utf-8")
        destino = cp.carpeta_modelos() / mid
        if destino.exists():
            shutil.rmtree(destino)
        temporal.rename(destino)
    except BaseException:
        shutil.rmtree(temporal, ignore_errors=True)
        raise
    cp.registrar(man, activar=False, motivo="reentrenamiento",
                 usuario=(origen or {}).get("solicitado_por") or "entrenamiento")
    man["onnx"] = _exportar_onnx(mid)
    return man


def entrenar(s, corte: date, datos_hasta: date | None = None, semilla: int = V.SEMILLA, *,
             origen: dict | None = None, avance: Callable[[float, str], None] | None = None) -> dict:
    """preparar + entrenar_preparado (para scripts y pruebas; el trabajo de la cola cierra la sesión antes de
    entrenar)."""
    return entrenar_preparado(preparar(s, corte, datos_hasta, semilla), origen=origen, avance=avance)


# ----------------------------------------------------------------------------------------------- trabajo de la cola
def _progreso(execution_id: uuid.UUID, pct: float, detalle: str) -> None:
    """Avance dentro de la etapa «entrenamiento» (sin abrir otra medición de la etapa)."""
    from sqlalchemy import update

    from app.db import sesion_contexto
    from app.modelos_db import Ejecucion
    from app.servicios.ejecucion import ahora

    with sesion_contexto() as s:
        s.execute(update(Ejecucion).where(Ejecucion.execution_id == execution_id)
                  .values(progreso=pct, etapa=f"entrenamiento {detalle}", actualizado_en=ahora()))


def ciclo(execution_id: uuid.UUID, parametros: dict) -> None:
    """El trabajo «entrenamiento» con familia=corto_plazo: entrena, registra la candidata en model_registry y, si
    viene de la política (con datos_hasta), la deja en sombra."""
    from sqlalchemy import select

    from app.db import sesion_contexto
    from app.modelos_db import RegistroModelo
    from app.servicios import cola, ejecucion, gobierno_corto_plazo

    corte = _fecha(parametros.get("hasta"))
    if corte is None:
        raise ejecucion.ErrorNoReintentable("El entrenamiento del corto plazo necesita «hasta» (la fecha de corte)")
    pedido_hasta = _fecha(parametros.get("datos_hasta"))
    origen = {k: parametros.get(k) for k in ("solicitado_por", "origen", "motivo")} | {
        "execution_id": str(execution_id)}
    ejecucion._avance(execution_id, 5, "entrenamiento")
    try:
        with sesion_contexto() as s:
            prep = preparar(s, corte, pedido_hasta, int(parametros.get("semilla", V.SEMILLA)))
        man = entrenar_preparado(prep, origen=origen,
                                 avance=lambda pct, detalle: _progreso(execution_id, pct, detalle))
    except ErrorReentreno as exc:
        raise ejecucion.ErrorNoReintentable(str(exc)) from exc
    ejecucion._avance(execution_id, 90, "registro")
    with sesion_contexto() as s:
        gobierno_corto_plazo.sembrar(s)
        reg = s.scalar(select(RegistroModelo).where(RegistroModelo.model_id == man["model_id"]))
        _, umbrales = ejecucion.umbrales_vigentes(s)
        iniciar_sombra(reg, man, umbrales, sombra_aplica=pedido_hasta is not None)
        cola.cerrar_ok(s, execution_id, dict(
            estado="ok", etapa="terminada", progreso=100, model_id=man["model_id"],
            feature_version=man["feature_version"], data_cutoff=reg.data_cutoff if reg else None,
            metricas=ejecucion.json_seguro({"familia": FAMILIA, "validacion": _resumen_validacion(man),
                                            "segundos": man.get("segundos"), "onnx": man.get("onnx"),
                                            "sombra": ((reg.metricas or {}).get("sombra") if reg else None)}),
            mensaje=f"Candidato de corto plazo {man['model_id']} registrado", terminado_en=ejecucion.ahora(),
            actualizado_en=ejecucion.ahora()))


def _resumen_validacion(man: dict) -> dict:
    """WAPE y cobertura P10-P90 de la validación por nivel, horizonte y ruta."""
    out: dict = {}
    for nivel, por_h in (man.get("metricas_validacion") or {}).items():
        out[nivel] = {h: {"wape_por_ruta": {r: m.get("wape") for r, m in por_ruta.items()},
                          "cobertura_por_ruta": {r: m.get("cobertura_p10_p90") for r, m in por_ruta.items()}}
                      for h, por_ruta in por_h.items()}
    return out


# ----------------------------------------------------------------------------------------------- política
def datos_vistos_hasta(modelo) -> date | None:
    """Último día de datos que vio una versión: el fin de su validación (datos_hasta) o su fecha de corte."""
    m = modelo.metricas or {}
    fechas = [_fecha((m.get("sombra") or {}).get("datos_hasta")), _fecha(m.get("datos_hasta")),
              _fecha(modelo.data_cutoff)]
    fechas = [f for f in fechas if f is not None]
    return max(fechas) if fechas else None


def _versiones(s) -> list:
    from sqlalchemy import select

    from app.modelos_db import RegistroModelo

    return list(s.scalars(select(RegistroModelo).where(RegistroModelo.familia == FAMILIA)).all())


def en_sombra(s) -> list:
    return [m for m in _versiones(s) if m.estado == "candidato"
            and ((m.metricas or {}).get("sombra") or {}).get("estado") == "en_sombra"]


def _entrenamientos_pendientes(s) -> int:
    from sqlalchemy import func, select

    from app.modelos_db import Ejecucion

    return s.scalar(select(func.count()).select_from(Ejecucion).where(
        Ejecucion.tipo == "entrenamiento", Ejecucion.estado.in_(("en_cola", "corriendo")),
        Ejecucion.parametros["familia"].astext == FAMILIA)) or 0


def _bloqueos(s, versiones: list, corte: date, u: dict) -> list[str]:
    bloqueos = []
    pendientes = _entrenamientos_pendientes(s)
    if pendientes:
        bloqueos.append(f"{pendientes} entrenamiento(s) de corto plazo en cola o corriendo")
    sombra = [m.model_id for m in versiones if m.estado == "candidato"
              and ((m.metricas or {}).get("sombra") or {}).get("estado") == "en_sombra"]
    if sombra:
        bloqueos.append(f"retador de corto plazo en sombra: {', '.join(sombra)}")
    cortes = [c for c in (_fecha(m.data_cutoff) for m in versiones) if c is not None]
    minimo = int(u["reentreno_periodicidad_dias"])
    if cortes and (corte - max(cortes)).days < minimo:
        bloqueos.append(f"el corte {corte} no agrega {minimo} días de entrenamiento a la última versión (corte "
                        f"{max(cortes)})")
    if cp.dia_de_fecha(corte) < V.ARRANQUE + HISTORIA_MINIMA_DIAS:
        bloqueos.append(f"el corte {corte} deja menos de {HISTORIA_MINIMA_DIAS} días de historia")
    return bloqueos


def decidir(s, umbrales: dict | None, hasta: date | None) -> dict[str, Any]:
    """¿Hay que entrenar una versión nueva de corto plazo? Motivos (periodicidad, degradación, deriva, cobertura),
    bloqueos, el corte (hasta - 61 días) y la fecha final de los datos."""
    from app.servicios import ejecucion, politica

    u = politica.umbrales_politica(umbrales)
    activo = ejecucion.modelo_activo(s, FAMILIA)
    out: dict[str, Any] = {"familia": FAMILIA, "reentrenar": False, "motivos": [], "bloqueos": [],
                           "modelo_activo": activo.model_id if activo else None, "datos_hasta": hasta}
    if activo is None or hasta is None:
        out["bloqueos"].append("sin modelo de corto plazo activo o sin días leídos")
        return out
    versiones = _versiones(s)
    vistos = [d for d in (datos_vistos_hasta(m) for m in versiones) if d is not None]
    ultimo = max(vistos) if vistos else None
    dias = max((hasta - ultimo).days, 0) if ultimo else None
    out.update(ultimo_dato_visto=ultimo, dias_desde_ultimo_entrenamiento=dias,
               reloj_antiguedad=politica.RELOJ_ANTIGUEDAD)
    if dias is not None and dias >= u["reentreno_periodicidad_dias"]:
        out["motivos"].append(f"periodicidad: {dias} días de datos nuevos desde {ultimo} "
                              f"(cada {int(u['reentreno_periodicidad_dias'])})")
    out["motivos"] += politica._motivos_monitoreo(s, activo.model_id, u)
    corte = hasta - timedelta(days=politica.DIAS_VALIDACION)
    out["hasta"], out["datos_hasta"] = corte.isoformat(), hasta.isoformat()
    if out["motivos"]:
        out["bloqueos"] += _bloqueos(s, versiones, corte, u)
    out["reentrenar"] = bool(out["motivos"]) and not out["bloqueos"]
    return out


def encolar(s, decision: dict, origen: str, correlation_id: str | None = None) -> uuid.UUID | None:
    """Encola el entrenamiento en la transacción de `s` (queda confirmado junto con los resultados del ciclo)."""
    from app.modelos_db import Ejecucion
    from app.servicios import politica
    from app.servicios.ejecucion import json_seguro

    if not decision.get("reentrenar"):
        return None
    motivo = "; ".join(decision["motivos"])
    e = Ejecucion(execution_id=uuid.uuid4(), tipo="entrenamiento", estado="en_cola", progreso=0, intentos=0,
                  parametros=json_seguro({"familia": FAMILIA, "hasta": decision["hasta"],
                                          "datos_hasta": decision["datos_hasta"], "semilla": V.SEMILLA,
                                          "solicitado_por": politica.USUARIO_POLITICA, "origen": origen,
                                          "motivo": motivo}),
                  metricas={}, correlation_id=correlation_id or f"politica-corto-plazo-{origen}",
                  mensaje="Reentrenamiento del corto plazo por política: " + motivo)
    s.add(e)
    s.flush()
    return e.execution_id


# ----------------------------------------------------------------------------------------------- sombra
def iniciar_sombra(registro, man: dict, umbrales: dict | None, sombra_aplica: bool = True) -> None:
    """La candidata queda en sombra desde el día siguiente al último dato que vio (datos_hasta), los sombra_dias días
    de threshold_config. Un entrenamiento manual sin datos_hasta no tiene sombra: lo activa un admin con la compuerta
    de POST /models/{model_id}/activate."""
    from app.servicios import politica
    from app.servicios.ejecucion import ZONA, ahora, json_seguro

    if registro is None or registro.estado != "candidato":
        return
    fin_datos = _fecha(man.get("datos_hasta"))
    extra = {"datos_hasta": fin_datos, "metricas_validacion": man.get("metricas_validacion"),
             "periodos": man.get("periodos")}
    if not sombra_aplica:
        registro.metricas = json_seguro({**(registro.metricas or {}), **extra, "sombra": {
            "estado": "no_aplica", "datos_hasta": fin_datos,
            "motivo": "entrenamiento manual sin datos_hasta: la activación pasa por POST /models/{id}/activate"}})
        return
    u = politica.umbrales_politica(umbrales)
    inicio = fin_datos + timedelta(days=1)
    dias = int(u["sombra_dias"])
    registro.metricas = json_seguro({**(registro.metricas or {}), **extra, "sombra": {
        "estado": "en_sombra", "datos_hasta": fin_datos, "inicio": inicio, "dias": dias,
        "fin": inicio + timedelta(days=dias - 1), "creado_en": ahora().astimezone(ZONA).isoformat(timespec="seconds")}})
    politica._auditar(registro, "sombra_iniciada", desde=inicio, dias=dias, familia=FAMILIA)


def revisar_sombra(s, hasta: date | None, umbrales: dict | None, umbrales_version: int | None) -> list[dict]:
    """Cuando el ciclo leyó entera la ventana de sombra de una candidata, la compuerta de cuatro criterios la compara
    con el activo de la familia en esa ventana y decide (la misma decisión de la sombra del modelo horario)."""
    from app.servicios import ejecucion, gobierno_corto_plazo, politica

    u = politica.umbrales_politica(umbrales)
    salida = []
    for cand in en_sombra(s):
        sm = dict((cand.metricas or {}).get("sombra") or {})
        inicio, fin = _fecha(sm.get("inicio")), _fecha(sm.get("fin"))
        if inicio is None or fin is None:
            continue
        if hasta is None or hasta < fin:
            vistos = max((hasta - inicio).days + 1, 0) if hasta else 0
            salida.append({"model_id": cand.model_id, "estado": "en_sombra", "dias_observados": vistos,
                           "dias_requeridos": int(sm.get("dias") or 0)})
            continue
        activo = ejecucion.modelo_activo(s, FAMILIA)
        with cp.con_sesion(s):
            comp = gobierno_corto_plazo.compuerta(cand.model_id, activo.model_id if activo else None, inicio, fin, u)
        comp["umbrales_version"] = umbrales_version
        decision = politica._decidir_sombra(
            s, cand, sm, comp, activo, u, hasta,
            f"compuerta de sombra del corto plazo aprobada ({inicio}..{fin}, umbrales v{umbrales_version})")
        salida.append({"model_id": cand.model_id, "estado": decision, "ventana": {"desde": inicio, "hasta": fin},
                       "criterios": comp["criterios"], "activo": comp["activo"]})
    return salida


def despues_del_ciclo(s, c, monitoreo: dict) -> dict:
    """Al cerrar el ciclo diario (misma transacción): la compuerta de la sombra y la decisión de reentreno del corto
    plazo. Nunca detiene el ciclo: un fallo queda en sus fallos."""
    from app.servicios import politica

    hasta = _fecha((monitoreo or {}).get("hasta"))
    u = politica.umbrales_politica(c.umbrales)
    try:
        with s.begin_nested():
            out: dict[str, Any] = {"sombra": revisar_sombra(s, hasta, c.umbrales, c.version_u)}
            dec = decidir(s, c.umbrales, hasta)
            out["reentreno"] = dec
            if dec["reentrenar"] and u["reentreno_en_ciclo"] < 1:
                dec["nota"] = "reentreno_en_ciclo = 0 en threshold_config: no se encola"
            elif dec["reentrenar"] and not en_ciclo_habilitado():
                dec["nota"] = f"{ENV_EN_CICLO}=false: no se encola"
            elif dec["reentrenar"]:
                out["entrenamiento_encolado"] = encolar(s, dec, "ciclo_diario", f"politica-cp-{c.execution_id}")
        return out
    except Exception as exc:  # noqa: BLE001 - la política no detiene el ciclo
        LOG.warning("política del corto plazo: %s", exc, exc_info=True)
        c.fallos.append({"etapa": "politica_corto_plazo", "error": str(exc)})
        return {"error": str(exc)}
