"""Pronóstico de corto plazo de la demanda: las subidas de los próximos 30, 60 y 120 minutos por ruta, sentido y
segmento, con lo observado hasta el instante (spec v1.5 §2.2 «horizontes configurables de 30, 60 y 120 minutos»,
RF-005, RF-006, §3.1 M3 «por ruta, sentido, segmento y franja horaria → pronóstico e intervalo de confianza», §9.1,
§9.2, §9.4).

Es el modelo del experimento E14 (pronostico_corto_plazo/ de la entrega), elegido en la validación de enero a junio de
2025 y medido una sola vez en la prueba reservada de julio a diciembre de 2025. scripts/entrenar_corto_plazo.py lo
reentrena con la misma configuración y semilla y lo registra; scripts/verificar_corto_plazo.py comprueba que la API
reproduce las predicciones guardadas de esa prueba.

- Modelos: LightGBM Poisson por nivel («ruta» y «segmento»), horizonte y ruta (18 artefactos), en el registro propio
  datos/modelos/corto_plazo/registro.json. cargar() verifica el SHA-256 de cada artefacto y la versión de variables
  antes de usarlo, y lo deja en memoria (§9.2: se carga una vez, se verifica su hash).
- Sentido: la suma de sus segmentos (la estructura elegida en la validación). El sentido de cada segmento es la mitad
  del ciclo (supuesto S9).
- Banda P10-P90: conformal por tramo del pronóstico, ajustada en la validación por nivel, horizonte y ruta.
- Líneas base (§9.1): el promedio por día y hora (las 8 semanas anteriores en el mismo día y hora) y la última semana.
- Explicación local (§9.4): las contribuciones exactas de cada variable a la predicción de la ruta (TreeSHAP de
  LightGBM, pred_contrib), en escala logarítmica porque el modelo es de Poisson: exp(contribución) es el factor por el
  que esa variable multiplica el pronóstico.
- ONNX (§9.1, §9.2): scripts/exportar_onnx_corto_plazo.py traduce los 18 árboles a ONNX (app/servicios/
  onnx_corto_plazo.py) con su SHA-256 y su paridad; con MOTOR_INFERENCIA=onnx el pronóstico sale de ONNX Runtime (la
  explicación local sigue siendo el TreeSHAP de LightGBM).
- Datos: el panel de 15 minutos de datos/corto_plazo (subidas por segmento y salidas por bloque, 2023-2025, del
  experimento E14) más lo que lee cada ciclo (app/servicios/panel_corto_plazo.py: tablas subidas_15min y
  salidas_15min, con la sesión de con_sesion). Un instante t usa solo lo observado antes de t; con `hasta` (la marca de
  agua de la ejecución) tampoco usa nada posterior a lo leído.
- Calidad (VAL-009): las celdas por encima de cp_tope_subidas_bloque_segmento se excluyen al cargar la serie y la
  respuesta lo dice (calidad). sin_calidad() la apaga para reproducir la prueba reservada tal como se midió.

Este modelo no reemplaza al modelo horario de inferencia.py: aquel pronostica con siete días de antelación y sirve
para el plan del día siguiente; este, con lo que ya pasó hoy, sirve para operar en las próximas dos horas.
"""
from __future__ import annotations

import contextvars
import gzip
import hashlib
import json
import math
import os
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np

from . import datos
from . import panel_corto_plazo as P
from . import variables_corto_plazo as V

MODEL_ID_E14 = "cp_lgbm_20250630_s42"
TIPO = "lgbm_poisson_corto_plazo"
ARCHIVO_MANIFIESTO = "manifest.json"
ARCHIVO_REGISTRO = "registro.json"
ARCHIVOS_CODIGO = ("variables_corto_plazo.py", "corto_plazo.py")
CARPETA_ONNX = "onnx"
ARCHIVO_ONNX = "manifest_onnx.json"
ZONA = ZoneInfo("America/Bogota")
NIVELES_CON_MODELO = ("ruta", "segmento")
SENTIDOS = ("ida", "regreso")
FACTORES_EXPLICACION = 5
CLAVES_REGISTRO = ("model_id", "tipo", "feature_version", "data_cutoff", "entrenado_con", "generado_en")

# Lo que significa cada variable, en lenguaje de la operación (RF-015, §9.4)
DESCRIPCION = {
    "l7": "la misma ventana hace 7 días", "l14": "la misma ventana hace 14 días",
    "m4": "el promedio de la misma ventana en las 4 semanas anteriores",
    "m8": "el promedio de la misma ventana en las 8 semanas anteriores",
    "sd8": "cuánto varía la misma ventana en las 8 semanas anteriores", "ayer": "la misma ventana ayer",
    "m7d": "el promedio de la misma ventana en los 7 días anteriores",
    "p15": "lo que subió en los 15 minutos anteriores", "p30": "lo que subió en los 30 minutos anteriores",
    "p60": "lo que subió en los 60 minutos anteriores", "p120": "lo que subió en las 2 horas anteriores",
    "hoy": "lo acumulado hoy hasta el instante", "e120": "lo habitual en las 2 horas anteriores",
    "ehoy": "lo habitual acumulado a esta hora", "r120": "las 2 horas anteriores frente a lo habitual",
    "rhoy": "lo acumulado hoy frente a lo habitual",
    "sal60": "las salidas de la última hora", "sal120": "las salidas de las 2 últimas horas",
    "sal240": "las salidas de las 4 últimas horas",
    "R_m4": "lo habitual en toda la ruta", "R_p30": "lo que subió en toda la ruta en los 30 minutos anteriores",
    "R_p60": "lo que subió en toda la ruta en los 60 minutos anteriores",
    "R_p120": "lo que subió en toda la ruta en las 2 horas anteriores", "R_hoy": "lo acumulado hoy en toda la ruta",
    "R_ehoy": "lo habitual acumulado en toda la ruta", "R_rhoy": "lo acumulado hoy en la ruta frente a lo habitual",
    "sal_llegan": "las salidas que pasarán por el segmento en la ventana",
    "sal_pasaron": "las salidas que pasaron por el segmento en la última media hora",
    "sal_conocida": "qué parte de la oferta de la ventana ya salió",
    "arriba30": "lo que subió antes en la ruta (30 min)",
    "arriba60": "lo que subió antes en la ruta (60 min)", "abajo30": "lo que subió después en la ruta (30 min)",
    "vec_m4": "lo habitual en los segmentos vecinos", "dia_semana": "el día de la semana", "tipo_dia": "el tipo de día",
    "festivo": "si es festivo", "carnaval": "si es Carnaval", "semana_santa": "si es Semana Santa",
    "vacaciones": "si son vacaciones", "navidad": "si es Navidad", "primero_enero": "si es 1 de enero",
    "vac_escolar": "si son vacaciones escolares", "vac_univ": "si son vacaciones universitarias", "mes": "el mes",
    "dia_mes": "el día del mes", "instante": "la hora del instante", "nro_segmento": "el número del segmento",
    "sentido": "el sentido", "minutos_desde_inicio": "los minutos desde el inicio del recorrido",
}

_CANDADO = threading.Lock()
_CACHE: dict[str, dict] = {}


class ErrorCortoPlazo(RuntimeError):
    """El modelo de corto plazo no se puede usar (artefacto que no coincide con su SHA-256, versión de variables)."""


class ModeloCortoPlazoNoEncontrado(LookupError):
    """El model_id no está en el registro de corto plazo."""


class FueraDeCobertura(ValueError):
    """La ruta, la fecha o el instante pedidos no se pueden pronosticar con los datos disponibles."""


# ----------------------------------------------------------------------------------------------- carpetas y registro
def carpeta_datos() -> Path:
    return datos.carpeta_datos() / "corto_plazo"


def carpeta_modelos() -> Path:
    return datos.carpeta_modelos() / "corto_plazo"


def clave_artefacto(nivel: str, horizonte_min: int, idruta: int) -> str:
    return f"{nivel}_h{horizonte_min}_r{idruta}"


def _sha256(ruta: Path) -> str:
    h = hashlib.sha256()
    with ruta.open("rb") as f:
        for bloque in iter(lambda: f.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()


def huellas_codigo() -> dict:
    """SHA-256 (fin de línea LF) del código que arma las variables y sirve el modelo, completo y sin el docstring del
    módulo (§9.3 «registrar … código»): la documentación puede cambiar sin cambiar el preprocesamiento."""
    from app.servicios.inferencia import sha256_codigo, sin_docstring_de_modulo

    aqui = Path(__file__).resolve().parent
    huellas = {}
    for n in ARCHIVOS_CODIGO:
        texto = (aqui / n).read_text(encoding="utf-8")
        huellas[n] = sha256_codigo(texto)
        huellas[f"{n}_sin_docstring"] = sha256_codigo(sin_docstring_de_modulo(texto))
    return huellas


def registro() -> dict:
    ruta = carpeta_modelos() / ARCHIVO_REGISTRO
    if ruta.exists():
        return json.loads(ruta.read_text(encoding="utf-8"))
    return {"activo": None, "modelos": {}, "historial_activacion": []}


def modelo_activo() -> str | None:
    return registro().get("activo")


def registrar(manifiesto: dict, *, activar: bool, motivo: str, usuario: str = "entrenamiento") -> dict:
    """Agrega el modelo al registro de corto plazo; con activar=True queda activo y la decisión va al historial."""
    reg = registro()
    mid = manifiesto["model_id"]
    reg.setdefault("modelos", {})[mid] = {k: manifiesto.get(k) for k in CLAVES_REGISTRO}
    if activar and reg.get("activo") != mid:
        reg.setdefault("historial_activacion", []).append(
            {"en": datetime.now(UTC).isoformat(timespec="seconds"), "de": reg.get("activo"), "a": mid,
             "usuario": usuario, "motivo": motivo})
        reg["activo"] = mid
    for k, m in reg["modelos"].items():
        m["estado"] = "activo" if k == reg.get("activo") else "candidato"
    ruta = carpeta_modelos() / ARCHIVO_REGISTRO
    ruta.parent.mkdir(parents=True, exist_ok=True)
    temporal = ruta.with_name(f".{ARCHIVO_REGISTRO}.{os.getpid()}.tmp")
    temporal.write_text(json.dumps(reg, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(temporal, ruta)
    return reg


def cargar(model_id: str | None = None) -> dict:
    """El modelo de corto plazo verificado y en memoria (una sola vez por proceso): manifiesto, árboles y
    calibración."""
    reg = registro()
    mid = model_id or reg.get("activo")
    if not mid:
        raise ErrorCortoPlazo(f"No hay modelo de corto plazo activo en {carpeta_modelos()}: ejecute "
                              "scripts/entrenar_corto_plazo.py")
    if mid not in reg.get("modelos", {}):
        raise ModeloCortoPlazoNoEncontrado(f"Modelo de corto plazo no registrado: {mid}")
    from app.servicios.onnx_motor import motor_configurado

    clave = f"{carpeta_modelos().resolve()}::{mid}::{motor_configurado()}"
    with _CANDADO:
        if clave not in _CACHE:
            _CACHE[clave] = _leer_verificado(carpeta_modelos() / mid, mid)
        return _CACHE[clave]


def _leer_verificado(carpeta: Path, mid: str) -> dict:
    import lightgbm as lgb

    ruta_man = carpeta / ARCHIVO_MANIFIESTO
    if not ruta_man.exists():
        raise ModeloCortoPlazoNoEncontrado(f"No existe el manifiesto del modelo de corto plazo {mid}")
    man = json.loads(ruta_man.read_text(encoding="utf-8"))
    if man.get("feature_version") != V.VERSION_VARIABLES:
        raise ErrorCortoPlazo(f"{mid} usa variables {man.get('feature_version')}; el código tiene "
                              f"{V.VERSION_VARIABLES}")
    arboles = {}
    for clave, a in man["artefactos"].items():
        archivo = carpeta / a["archivo"]
        if not archivo.exists() or _sha256(archivo) != a["sha256"]:
            raise ErrorCortoPlazo(f"El artefacto {a['archivo']} de {mid} no coincide con el SHA-256 de su manifiesto")
        booster = lgb.Booster(model_str=gzip.decompress(archivo.read_bytes()).decode("utf-8"))
        # se entrenó con la matriz de variables_corto_plazo.variables() (sin nombres: «Column_0», …): basta que tenga
        # el mismo número de columnas; el orden lo fija ese código, cuya huella guarda el manifiesto
        nombres = booster.feature_name()
        if len(nombres) != len(a["variables"]) or (nombres != a["variables"]
                                                   and nombres != [f"Column_{j}" for j in range(len(nombres))]):
            raise ErrorCortoPlazo(f"El artefacto {a['archivo']} de {mid} no tiene las variables de su manifiesto")
        arboles[clave] = booster
    salida = {"model_id": mid, "manifiesto": man, "arboles": arboles, "motor": "lightgbm"}
    from app.servicios.onnx_motor import motor_configurado

    if motor_configurado() == "onnx":
        salida["onnx"] = _onnx_verificado(carpeta, mid, list(arboles))
        salida["motor"] = "onnx"
    return salida


def _onnx_verificado(carpeta: Path, mid: str, claves: list[str]) -> dict:
    """MOTOR_INFERENCIA=onnx: las sesiones de ONNX Runtime de los 18 artefactos, cada una con su SHA-256 verificado
    contra manifest_onnx.json (la exportación de scripts/exportar_onnx_corto_plazo.py)."""
    from app.servicios import onnx_corto_plazo

    ruta = carpeta / CARPETA_ONNX / ARCHIVO_ONNX
    if not ruta.exists():
        raise ErrorCortoPlazo(f"MOTOR_INFERENCIA=onnx y {mid} no tiene exportación ONNX: corra "
                              "scripts/exportar_onnx_corto_plazo.py")
    man = json.loads(ruta.read_text(encoding="utf-8"))
    sesiones = {}
    for clave in claves:
        a = (man.get("artefactos") or {}).get(clave)
        archivo = carpeta / CARPETA_ONNX / a["archivo"] if a else None
        if archivo is None or not archivo.exists() or _sha256(archivo) != a["sha256"]:
            raise ErrorCortoPlazo(f"El ONNX de {clave} de {mid} falta o no coincide con su SHA-256")
        sesiones[clave] = onnx_corto_plazo.sesion(gzip.decompress(archivo.read_bytes()))
    return sesiones


def predecir_artefacto(modelo: dict, clave: str, x: np.ndarray) -> np.ndarray:
    """Las predicciones de un artefacto con el motor configurado (LightGBM o ONNX Runtime)."""
    if "onnx" in modelo:
        from app.servicios import onnx_corto_plazo

        return onnx_corto_plazo.predecir(modelo["onnx"][clave], x)
    return modelo["arboles"][clave].predict(x)


def limpiar_cache() -> None:
    with _CANDADO:
        _CACHE.clear()
        _UNIDAS.clear()
    _serie.cache_clear()
    _base.cache_clear()
    _dia_en.cache_clear()
    P._LEIDOS.invalidar()


def ficha(modelo: dict) -> dict:
    """Versión del modelo que acompaña cada pronóstico (§9.2: model_id, feature_version, data_cutoff, SHA-256)."""
    man = modelo["manifiesto"]
    return {"model_id": modelo["model_id"], "tipo": man.get("tipo"), "feature_version": man.get("feature_version"),
            "data_cutoff": man.get("data_cutoff"), "entrenado_con": man.get("entrenado_con"),
            "semilla": man.get("semilla"), "estructura": man.get("estructura"),
            "banda": (man.get("banda") or {}).get("metodo"),
            "sha256": {k: a["sha256"] for k, a in man["artefactos"].items()},
            "version_datos": man.get("version_datos"), "metricas_prueba": man.get("metricas_prueba"),
            "origen": man.get("origen"), "evaluacion": "pronostico_corto_plazo/README.md (experimento E14)",
            "motor": modelo.get("motor", "lightgbm")}


# ----------------------------------------------------------------------------------------------- datos
def idruta_de(ruta: str | int) -> int:
    """El idruta de la ruta (por nombre del catálogo o por idruta). FueraDeCobertura si no es una de las tres."""
    texto = str(ruta).strip()
    for idruta, nombre in V.RUTAS.items():
        if texto in (nombre, str(idruta)):
            return idruta
    raise FueraDeCobertura(f"Ruta sin pronóstico de corto plazo: {ruta!r}. Rutas: {list(V.RUTAS.values())}")


_SESION: contextvars.ContextVar = contextvars.ContextVar("sesion_corto_plazo", default=None)
_CALIDAD: contextvars.ContextVar = contextvars.ContextVar("calidad_corto_plazo", default=True)
_TOPE: contextvars.ContextVar = contextvars.ContextVar("tope_corto_plazo", default=None)


@contextmanager
def con_sesion(sesion):
    """Dentro del bloque, la serie incluye lo que leyó la lectura incremental (subidas_15min y salidas_15min) y la
    regla de calidad usa el tope vigente de threshold_config."""
    t1, t2 = _SESION.set(sesion), _TOPE.set(_tope_vigente(sesion))
    try:
        yield
    finally:
        _SESION.reset(t1)
        _TOPE.reset(t2)


@contextmanager
def sin_calidad():
    """Sin la regla VAL-009: los datos tal como se midió la prueba reservada (scripts/verificar_corto_plazo.py)."""
    t = _CALIDAD.set(False)
    try:
        yield
    finally:
        _CALIDAD.reset(t)


def tope_actual() -> float:
    return float(_TOPE.get() or P.TOPE_POR_OMISION)


def _tope_vigente(sesion) -> float:
    if sesion is None:
        return P.TOPE_POR_OMISION
    try:
        from app.servicios import ejecucion

        return P.tope(ejecucion.umbrales_vigentes(sesion)[1])
    except Exception:  # noqa: BLE001 - sin umbrales legibles rige el tope por omisión
        return P.TOPE_POR_OMISION


@dataclass(frozen=True)
class Serie:
    """La serie de 15 minutos de una ruta lista para pronosticar."""
    ruta: V.Ruta
    version: str            # llave de caché: carpeta, calidad, tope y versión de lo leído
    excluidas: tuple        # celdas excluidas por VAL-009 (del panel empaquetado)
    hasta: dict             # {fecha: instante hasta el que se leyó} de lo leído en la base
    fin_panel: int          # último día del panel empaquetado


def serie(idruta: int) -> V.Ruta:
    """La serie de 15 minutos de la ruta: el panel empaquetado (con la regla de calidad) y, con con_sesion, lo
    leído."""
    return serie_completa(idruta).ruta


def serie_completa(idruta: int) -> Serie:
    carpeta = str(carpeta_datos())
    calidad = bool(_CALIDAD.get())
    tope = float(_TOPE.get() or P.TOPE_POR_OMISION)
    base, excluidas = _base(idruta, carpeta, calidad, tope)
    fin = len(base.cal) - 1
    sesion = _SESION.get()
    lei = P.leidos(sesion, idruta) if sesion is not None else None
    if lei is None or not lei.hasta:
        return Serie(base, f"{carpeta}|{calidad}|{tope}|-", excluidas, {}, fin)
    version = f"{carpeta}|{calidad}|{tope}|{lei.version}"
    with _CANDADO:
        unida = _UNIDAS.get((idruta, version))
    if unida is None:
        unida = P.unir(base, lei, V.DIA0.date())[0]
        with _CANDADO:
            if len(_UNIDAS) >= 6:
                _UNIDAS.pop(next(iter(_UNIDAS)))
            _UNIDAS[(idruta, version)] = unida
    return Serie(unida, version, excluidas, dict(lei.hasta), fin)


_UNIDAS: dict[tuple[int, str], V.Ruta] = {}


@lru_cache(maxsize=12)
def _base(idruta: int, carpeta: str, calidad: bool, tope: float) -> tuple[V.Ruta, tuple]:
    r = _serie(idruta, carpeta)
    if not calidad:
        return r, ()
    y = r.y.copy()
    excluidas = P.excluir_imposibles(y, V.DIA0.date(), idruta, tope)
    if not excluidas:
        return r, ()
    return V.Ruta(r.idruta, r.nombre, y, r.sal, r.seg, r.cal, V.dias_con_datos(y.sum(axis=(1, 2)))), tuple(excluidas)


@lru_cache(maxsize=6)
def _serie(idruta: int, carpeta: str) -> V.Ruta:
    return V.cargar_ruta(idruta, Path(carpeta))


def fecha_de_dia(d: int) -> date:
    return (V.DIA0 + timedelta(days=d)).date()


def dia_de_fecha(fecha: date) -> int:
    return (fecha - V.DIA0.date()).days


def cobertura() -> dict:
    """Las fechas que se pueden pronosticar: desde el día ARRANQUE (hacen falta 8 semanas de historia) hasta el
    último día de la serie (el panel empaquetado y lo leído; tras el último día leído, su primer instante); las de la
    prueba reservada son las que el modelo no vio al entrenar."""
    sc = serie_completa(next(iter(V.RUTAS)))
    a, b = V.rango_dias("prueba")
    return {"desde": fecha_de_dia(V.ARRANQUE), "hasta": fecha_de_dia(len(sc.ruta.cal) - 1),
            "panel_hasta": fecha_de_dia(sc.fin_panel),
            "leido_hasta": max(sc.hasta.values()).astimezone(ZONA).isoformat() if sc.hasta else None,
            "fuera_de_muestra_desde": fecha_de_dia(a), "fuera_de_muestra_hasta": fecha_de_dia(min(b, sc.fin_panel))}


def limite_lectura(sc: Serie, fecha: date) -> datetime | None:
    """Hasta qué instante se puede pronosticar un día. None: un día del panel empaquetado (sin límite). Un día leído
    o posterior al panel: lo leído de ese día; y, si el día anterior se leyó completo, al menos el primer instante (a
    las 04:00 todavía no ha subido nadie: todo lo que usa es del día anterior)."""
    d = dia_de_fecha(fecha)
    if fecha not in sc.hasta and d <= sc.fin_panel:
        return None
    candidatos = [sc.hasta[fecha].astimezone(ZONA)] if fecha in sc.hasta else []
    previo = fecha - timedelta(days=1)
    fin_previo = datetime(fecha.year, fecha.month, fecha.day, tzinfo=ZONA) - timedelta(seconds=1)
    if (previo in sc.hasta and sc.hasta[previo].astimezone(ZONA) >= fin_previo) or \
            (previo not in sc.hasta and dia_de_fecha(previo) <= sc.fin_panel):
        candidatos.append(datetime(fecha.year, fecha.month, fecha.day, int(V.INSTANTES[0]) // 4, tzinfo=ZONA))
    return max(candidatos) if candidatos else datetime(fecha.year, fecha.month, fecha.day, tzinfo=ZONA)


def bloques_leidos(fecha: date, hasta: datetime | None) -> int | None:
    """Cuántos bloques de 15 minutos del día ya se leyeron con la marca de agua `hasta` (None: todos)."""
    if hasta is None:
        return None
    h = hasta.astimezone(ZONA)
    if h.date() < fecha:
        return 0
    if h.date() > fecha:
        return None
    if (h.hour, h.minute, h.second) == (23, 59, 59):     # la marca del día completo
        return None
    return min(V.BLOQUES, (h.hour * 60 + h.minute) // 15)   # un bloque cuenta si terminó antes de la marca


def instante_local(instante: datetime) -> tuple[date, int, datetime]:
    """(fecha, bloque de 15 minutos, instante usado) del instante en America/Bogota, redondeado hacia abajo a la media
    hora (el modelo se eligió y se midió en las medias horas de 04:00 a 21:00)."""
    local = instante.astimezone(ZONA) if instante.tzinfo else instante.replace(tzinfo=ZONA)
    bloque = local.hour * 4 + (local.minute // 30) * 2
    if bloque not in set(V.INSTANTES.tolist()):
        raise FueraDeCobertura(f"El instante {local.isoformat(timespec='minutes')} está fuera de 04:00-21:00: el "
                               "pronóstico de corto plazo cubre las medias horas de 04:00 a 21:00")
    usado = local.replace(hour=bloque // 4, minute=(bloque % 4) * 15, second=0, microsecond=0)
    return local.date(), bloque, usado


# ----------------------------------------------------------------------------------------------- pronóstico de un día
def _dia(model_id: str, idruta: int, d: int, horizonte_min: int, bloques: int | None = None,
         niveles: tuple = NIVELES_CON_MODELO) -> dict:
    """Todo el día d de la ruta para el horizonte: los 35 instantes de 04:00 a 21:00, por ruta, sentido y segmento,
    con banda, líneas base y lo real de cada ventana. Cada instante solo usa lo observado antes de él; con `bloques`,
    lo posterior a esos bloques del día cuenta como no leído (la marca de agua de la ejecución)."""
    sc = serie_completa(idruta)
    return _dia_en(model_id, idruta, d, horizonte_min, str(carpeta_modelos()), sc.version, bloques, niveles)


@lru_cache(maxsize=64)
def _dia_en(model_id: str, idruta: int, d: int, horizonte_min: int, _modelos: str, _version: str,
            bloques: int | None, niveles: tuple) -> dict:
    modelo = cargar(model_id)
    man = modelo["manifiesto"]
    r = serie(idruta)
    if not V.ARRANQUE <= d < len(r.cal):
        cob = cobertura()
        raise FueraDeCobertura(f"La fecha {fecha_de_dia(d)} no se puede pronosticar: hay datos de corto plazo del "
                               f"{cob['desde']} al {cob['hasta']} (hacen falta 8 semanas de historia)")
    rr = r.recorte(d - V.ARRANQUE, d)
    if bloques is not None:      # lo que la ejecución todavía no leyó de ese día no existe para el pronóstico
        y, sal = rr.y.copy(), rr.sal.copy()
        y[-1, bloques:], sal[-1, bloques:] = 0, 0
        rr = V.Ruta(rr.idruta, rr.nombre, y, sal, rr.seg, rr.cal, rr.ok)
    nombre = V.RUTAS[idruta]
    i = len(V.INSTANTES)
    out: dict = {"idruta": idruta, "ruta": nombre, "dia": d, "horizonte_min": horizonte_min,
                 "dia_con_datos": bool(r.ok[d]) and bloques is None}
    for nivel in niveles:
        v = V.variables(rr, nivel, horizonte_min, man["conjunto"][nivel])
        g = v["forma"][2]
        ult = slice(len(v["y"]) - i * g, len(v["y"]))
        x = v["x"][ult]
        # float32, como en el experimento (la banda se asigna por tramo del pronóstico)
        p = np.clip(predecir_artefacto(modelo, clave_artefacto(nivel, horizonte_min, idruta), x), 0,
                    None).astype(np.float32)
        out[nivel] = {"p": p.reshape(i, g), "y": v["y"][ult].reshape(i, g),
                      "base": {k: b[ult].reshape(i, g) for k, b in v["base"].items()},
                      "x": x.reshape(i, g, -1), "nombres": v["nombres"]}
        out[nivel]["p10"], out[nivel]["p90"] = (b.reshape(i, g) for b in V.conformal_aplicar(
            p, man["banda"]["calibracion"][nivel][str(horizonte_min)][nombre]))
    # sentido = suma de sus segmentos (estructura elegida en la validación), con su propia banda calibrada
    if "segmento" not in out:
        return out
    seg = out["segmento"]
    ida = (r.seg["sentido"] == "ida").to_numpy()

    def por_sentido(a: np.ndarray) -> np.ndarray:
        return np.stack([a[:, ida].sum(axis=1), a[:, ~ida].sum(axis=1)], axis=1)

    p_sen = por_sentido(seg["p"])
    lo, hi = V.conformal_aplicar(p_sen.reshape(-1), man["banda"]["calibracion"]["sentido"][str(horizonte_min)][nombre])
    out["sentido"] = {"p": p_sen, "y": por_sentido(seg["y"]), "p10": lo.reshape(i, 2), "p90": hi.reshape(i, 2),
                      "base": {k: por_sentido(b) for k, b in seg["base"].items()}}
    return out


def _num(x, dec: int = 1) -> float | None:
    if x is None:
        return None
    x = float(x)
    return None if math.isnan(x) else round(x, dec)


def _celda(nivel: dict, j: int, g: int, con_real: bool) -> dict:
    base = nivel["base"]
    return {"pasajeros": _num(nivel["p"][j, g]), "p10": _num(nivel["p10"][j, g]), "p90": _num(nivel["p90"][j, g]),
            "promedio_dia_hora": _num(base["promedio_dia_hora"][j, g]),
            "ultima_semana": _num(base["ultima_semana"][j, g]),
            "real": _num(nivel["y"][j, g]) if con_real else None}


def explicar(modelo: dict, clave: str, x: np.ndarray, nombres: list[str]) -> dict:
    """§9.4: las variables que más mueven ESTA predicción. TreeSHAP exacto de LightGBM (pred_contrib) en escala
    logarítmica: exp(contribución) es el factor que esa variable aplica sobre el valor base del modelo."""
    contrib = modelo["arboles"][clave].predict(x[None, :], pred_contrib=True)[0]
    base, c = float(contrib[-1]), contrib[:-1]
    orden = np.argsort(-np.abs(c))[:FACTORES_EXPLICACION]
    factores = [{"variable": nombres[j], "descripcion": DESCRIPCION.get(nombres[j], nombres[j]),
                 "valor": _num(x[j], 2), "contribucion_log": round(float(c[j]), 4),
                 "factor": round(float(math.exp(c[j])), 3),
                 "sentido": "sube" if c[j] > 0 else "baja"} for j in orden]
    return {"metodo": "TreeSHAP de LightGBM (pred_contrib), escala log del modelo de Poisson",
            "valor_base": round(math.exp(base), 1), "factores": factores}


def _observado(nivel_ruta: dict, j: int) -> dict:
    """Lo que ya se sabe en el instante (las variables de lo observado de la ruta)."""
    x, nombres = nivel_ruta["x"][j, 0], nivel_ruta["nombres"]
    valor = {n: _num(x[k]) for k, n in enumerate(nombres)}
    return {"ultimos_15_min": valor.get("p15"), "ultimos_30_min": valor.get("p30"), "ultimos_60_min": valor.get("p60"),
            "ultimas_2_horas": valor.get("p120"), "acumulado_hoy": valor.get("hoy"),
            "habitual_acumulado": valor.get("ehoy"), "salidas_ultima_hora": valor.get("sal60")}


def _calidad(sc: Serie, d: int) -> dict | None:
    """VAL-009 en lo que usa el pronóstico del día d (el día y sus 8 semanas de historia): las celdas excluidas."""
    if not sc.excluidas:
        return None
    desde, hasta = fecha_de_dia(d - V.ARRANQUE).isoformat(), fecha_de_dia(d).isoformat()
    usadas = [c for c in sc.excluidas if desde <= c["fecha"] <= hasta]
    if not usadas:
        return None
    return {"regla": P.CODIGO_CALIDAD, "tope_subidas_bloque_segmento": float(_TOPE.get() or P.TOPE_POR_OMISION),
            "celdas_excluidas": usadas,
            "nota": "estas celdas superan el tope creíble de subidas de un segmento en 15 minutos; se excluyeron del "
                    "pronóstico (cuentan como no observadas)"}


def pronosticar(ruta: str | int, instante: datetime, horizonte_min: int, model_id: str | None = None,
                incluir_segmentos: bool = True, hasta: datetime | None = None) -> dict:
    """El pronóstico de la ventana [t, t + h) de la ruta: total, por sentido y por segmento, con banda P10-P90,
    líneas base, explicación local y lo real (si la ventana ya está en los datos, para comparar). Con `hasta` (la marca
    de agua de una ejecución), lo que todavía no se leyó del día no se usa ni se muestra como real."""
    t0 = time.perf_counter()
    if horizonte_min not in V.HORIZONTES:
        raise FueraDeCobertura(f"Horizonte {horizonte_min}: el pronóstico de corto plazo es a 30, 60 o 120 minutos")
    idruta = idruta_de(ruta)
    fecha, bloque, usado = instante_local(instante)
    modelo = cargar(model_id)
    mid = modelo["model_id"]
    d = dia_de_fecha(fecha)
    sc = serie_completa(idruta)
    limite = limite_lectura(sc, fecha)
    if limite is not None and usado > limite:
        raise FueraDeCobertura(f"Del {fecha} solo hay datos leídos hasta las {limite:%H:%M}: el pronóstico de corto "
                               f"plazo usa lo observado hasta el instante y no se adelanta a la lectura")
    bloques = bloques_leidos(fecha, hasta)
    dia = _dia(mid, idruta, d, horizonte_min, bloques)
    j = int(np.flatnonzero(V.INSTANTES == bloque)[0])
    r = sc.ruta
    con_real = dia["dia_con_datos"]
    if con_real and limite is not None:
        fin = usado + timedelta(minutes=horizonte_min)
        con_real = fin <= limite      # lo real de una ventana que todavía no se leyó entera no se conoce
    man = modelo["manifiesto"]
    a_val = V.rango_dias("validacion")[1]
    salida = {
        "ruta": V.RUTAS[idruta], "idruta": idruta, "instante_solicitado": instante.isoformat(),
        "instante": usado.isoformat(), "horizonte_min": horizonte_min,
        "ventana": {"desde": usado.isoformat(), "hasta": (usado + timedelta(minutes=horizonte_min)).isoformat()},
        "franja": V.franja_de(bloque), "model_id": mid, "feature_version": man["feature_version"],
        "data_cutoff": man["data_cutoff"], "en_muestra": d <= a_val, "dia_con_datos": con_real,
        **_celda(dia["ruta"], j, 0, con_real),
        "sentidos": [{"sentido": s, **_celda(dia["sentido"], j, k, con_real)} for k, s in enumerate(SENTIDOS)],
        "observado": _observado(dia["ruta"], j),
        "explicacion": explicar(modelo, clave_artefacto("ruta", horizonte_min, idruta), dia["ruta"]["x"][j, 0],
                                dia["ruta"]["nombres"]),
    }
    if incluir_segmentos:
        s = r.seg
        salida["segmentos"] = [
            {"nro_segmento": int(s["nro_segmento"].iloc[g]), "sentido": str(s["sentido"].iloc[g]),
             "km_inicio": float(s["km_inicio"].iloc[g]), "lat": float(s["lat"].iloc[g]),
             "lon": float(s["lon"].iloc[g]), **_celda(dia["segmento"], j, g, con_real)} for g in range(len(s))]
        if "id_segmento" in s.columns:
            for x, idseg in zip(salida["segmentos"], s["id_segmento"], strict=True):
                x["id_segmento"] = int(idseg)
    salida["datos_hasta"] = None if limite is None and hasta is None else \
        min(x for x in (limite, hasta) if x is not None).astimezone(ZONA).isoformat()
    salida["calidad"] = _calidad(sc, d)
    salida["latencia_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    return salida


def pronosticar_dia(ruta: str | int, fecha: date, horizonte_min: int, model_id: str | None = None) -> dict:
    """La curva del día: los 35 instantes de 04:00 a 21:00 de la ruta y de cada sentido (para el tablero)."""
    if horizonte_min not in V.HORIZONTES:
        raise FueraDeCobertura(f"Horizonte {horizonte_min}: el pronóstico de corto plazo es a 30, 60 o 120 minutos")
    idruta = idruta_de(ruta)
    modelo = cargar(model_id)
    d = dia_de_fecha(fecha)
    sc = serie_completa(idruta)
    limite = limite_lectura(sc, fecha)
    dia = _dia(modelo["model_id"], idruta, d, horizonte_min)
    con_real = dia["dia_con_datos"]
    puntos = []
    for j, bloque in enumerate(V.INSTANTES.tolist()):
        hora = datetime(fecha.year, fecha.month, fecha.day, bloque // 4, (bloque % 4) * 15, tzinfo=ZONA)
        if limite is not None and hora > limite:
            break             # un día leído a medias: solo los instantes que ya se pueden pronosticar
        real = con_real and (limite is None or hora + timedelta(minutes=horizonte_min) <= limite)
        puntos.append({"instante": hora.isoformat(), "franja": V.franja_de(bloque),
                       **_celda(dia["ruta"], j, 0, real),
                       "sentidos": [{"sentido": s, **_celda(dia["sentido"], j, k, real)}
                                    for k, s in enumerate(SENTIDOS)]})
    return {"ruta": V.RUTAS[idruta], "idruta": idruta, "fecha": fecha.isoformat(), "horizonte_min": horizonte_min,
            "model_id": modelo["model_id"], "en_muestra": d <= V.rango_dias("validacion")[1],
            "dia_con_datos": con_real, "datos_hasta": None if limite is None else limite.isoformat(),
            "calidad": _calidad(sc, d), "instantes": puntos}


# ---------------------------------------------------------------------------------------- recomendación y guardado
def franja_hora(r: dict) -> dict:
    """La franja horaria que se recomienda con el pronóstico de la ventana: la hora del punto medio de la ventana, con
    las subidas llevadas a ritmo por hora (× 60 / horizonte). Las subidas de la ventana y los pasajeros por hora de
    salida del modelo horario miden lo mismo (cada pasajero sube una vez); el panel cuenta por instante de la subida y
    el modelo horario por hora de salida del viaje."""
    escala = 60.0 / float(r["horizonte_min"])
    medio = datetime.fromisoformat(r["instante"]) + timedelta(minutes=r["horizonte_min"] / 2)
    hora = min(max(medio.hour, min(datos.HORAS_SERVICIO)), max(datos.HORAS_SERVICIO))
    return {"fecha": medio.date(), "hora": hora, "demanda_hora": float(r["pasajeros"]) * escala,
            "p10_hora": None if r.get("p10") is None else float(r["p10"]) * escala,
            "p90_hora": None if r.get("p90") is None else float(r["p90"]) * escala,
            "fuente": "pronóstico de corto plazo de la ventana llevado a ritmo por hora (× 60 / horizonte)"}


def recomendacion_completa(sesion, r: dict, info: dict) -> tuple[dict, dict, dict, int | None]:
    """§10.2 con el pronóstico de la ventana, con la misma función y la misma restricción reactiva (§10.1: la
    ocupación medida antes del instante) que el resto de la API. (franja, recomendación, entradas, versión de los
    umbrales)."""
    from app.servicios import ejecucion, ocupacion

    franja = franja_hora(r)
    version_u, umbrales = ejecucion.umbrales_vigentes(sesion)
    # la ocupación medida antes de la hora del pedido (a las 9:10 ya se sabe lo medido a las 9:06, aunque el pronóstico
    # use la media hora de las 9:00)
    pedido = datetime.fromisoformat(r.get("instante_solicitado") or r["instante"])
    if pedido.tzinfo is None:
        pedido = pedido.replace(tzinfo=ZONA)
    reactiva = ocupacion.reactiva_guardada(sesion, info["ruta"], franja["fecha"], pedido, umbrales)
    rec_d, entradas = ejecucion.recomendacion_con_ocupacion(info, franja, umbrales, version_u, reactiva)
    return franja, rec_d, entradas, version_u


def resumen_recomendacion(franja: dict, rec_d: dict, version_u: int | None) -> dict:
    """La recomendación que se guarda con el pronóstico de corto plazo (columna recomendacion)."""
    from app.servicios import ejecucion

    claves = ("buses_hora", "headway_min", "vehiculos_requeridos", "viable", "motivo", "capacidad_efectiva",
              "ocupacion_esperada", "frecuencia_actual_min", "diferencia_min", "frecuenciadespachos_min",
              "diferencia_frecuenciadespachos_min", "formula")
    return {"fecha": franja["fecha"].isoformat(), "hora": franja["hora"],
            "demanda_hora": round(franja["demanda_hora"], 1),
            "demanda_p10": None if franja["p10_hora"] is None else round(franja["p10_hora"], 1),
            "demanda_p90": None if franja["p90_hora"] is None else round(franja["p90_hora"], 1),
            "umbrales_version": version_u,
            "fuente": "pronóstico de corto plazo de la ventana llevado a ritmo por hora (× 60 / horizonte)",
            **{k: ejecucion.json_seguro(rec_d.get(k)) for k in claves},
            "restriccion_reactiva": ejecucion.json_seguro(rec_d.get("restriccion_reactiva"))}


def recomendacion(sesion, r: dict, info: dict) -> dict:
    """§10.2 con el pronóstico de la ventana (recomendacion_completa), en el formato que se guarda con él."""
    franja, rec_d, _, version_u = recomendacion_completa(sesion, r, info)
    return resumen_recomendacion(franja, rec_d, version_u)


def guardar(sesion, r: dict, execution_id=None):
    """RF-006 y §9.2: guarda el pronóstico (la ruta, sus sentidos y sus segmentos) con su banda, sus líneas base, el
    modelo, la versión de variables, la fecha de corte, cuándo se generó y la latencia. Devuelve el grupo_id y deja en
    r["prediction_id"] el de la fila de la ruta."""
    import uuid

    from app.modelos_db import PrediccionCortoPlazo
    from app.servicios.ejecucion import dimensiones_fila

    grupo = uuid.uuid4()
    r["prediction_id"] = id_ruta = uuid.uuid4()
    instante = datetime.fromisoformat(r["instante"])
    objetivo = datetime.fromisoformat(r["ventana"]["hasta"])
    generada = datetime.fromisoformat(r["generated_at"]) if r.get("generated_at") else datetime.now(UTC)
    dims = {k: v for k, v in dimensiones_fila(r["ruta"], instante.date()).items() if k != "idruta"}
    comun = {"grupo_id": grupo, "execution_id": execution_id, "ruta": r["ruta"], "idruta": r["idruta"],
             "instante": instante, "horizonte_min": r["horizonte_min"], "objetivo": objetivo,
             "fecha": instante.date(), "franja": r.get("franja"), "model_id": r["model_id"],
             "feature_version": r["feature_version"], "data_cutoff": date.fromisoformat(r["data_cutoff"]),
             "generated_at": generada, "latencia_ms": r.get("latencia_ms"), **dims}

    def fila(nivel: str, celda: dict, prediction_id=None, **extra):
        return PrediccionCortoPlazo(prediction_id=prediction_id or uuid.uuid4(), nivel=nivel,
                                    pasajeros=celda["pasajeros"], p10=celda.get("p10"), p90=celda.get("p90"),
                                    promedio_dia_hora=celda.get("promedio_dia_hora"),
                                    ultima_semana=celda.get("ultima_semana"), **comun, **extra)

    sesion.add(fila("ruta", r, prediction_id=id_ruta, explicacion=r.get("explicacion") or {},
                    variables={"observado": r.get("observado"), "en_muestra": r.get("en_muestra"),
                               "dia_con_datos": r.get("dia_con_datos"), "datos_hasta": r.get("datos_hasta"),
                               "calidad": r.get("calidad"), "instante_solicitado": r.get("instante_solicitado")},
                    recomendacion=r.get("recomendacion")))
    for s in r.get("sentidos") or []:
        sesion.add(fila("sentido", s, sentido=s["sentido"]))
    for s in r.get("segmentos") or []:
        sesion.add(fila("segmento", s, sentido=s["sentido"], nro_segmento=s["nro_segmento"],
                        id_segmento=s.get("id_segmento"), variables={"km_inicio": s.get("km_inicio")}))
    return grupo


def importancia_global(modelo: dict) -> dict:
    """§9.4 importancia global: la ganancia de LightGBM de cada variable (normalizada a 1 en cada artefacto),
    promediada en las tres rutas, por nivel y horizonte, de mayor a menor, con lo que significa cada variable."""
    acumulado: dict[tuple[str, int], dict[str, list[float]]] = {}
    for a in modelo["manifiesto"]["artefactos"].values():
        por_var = acumulado.setdefault((a["nivel"], int(a["horizonte_min"])), {})
        for var, g in (a.get("importancia_ganancia") or {}).items():
            por_var.setdefault(var, []).append(float(g))
    salida: dict[str, dict] = {}
    for (nivel, h), por_var in sorted(acumulado.items()):
        filas = sorted(((v, sum(gs) / len(gs)) for v, gs in por_var.items()), key=lambda x: -x[1])
        salida.setdefault(nivel, {})[str(h)] = [
            {"variable": v, "descripcion": DESCRIPCION.get(v, v), "ganancia": round(g, 4)} for v, g in filas]
    return {"metodo": "ganancia total de LightGBM por variable, normalizada a 1 en cada artefacto y promediada en las "
                      "tres rutas", "por_nivel": salida}
