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
- Datos: el panel de 15 minutos de datos/corto_plazo (subidas por segmento y salidas por bloque, 2023-2025, del
  experimento E14). Un instante t usa solo lo observado antes de t.

Este modelo no reemplaza al modelo horario de inferencia.py: aquel pronostica con siete días de antelación y sirve
para el plan del día siguiente; este, con lo que ya pasó hoy, sirve para operar en las próximas dos horas.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import math
import threading
import time
from datetime import UTC, date, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np

from . import datos
from . import variables_corto_plazo as V

MODEL_ID_E14 = "cp_lgbm_20250630_s42"
TIPO = "lgbm_poisson_corto_plazo"
ARCHIVO_MANIFIESTO = "manifest.json"
ARCHIVO_REGISTRO = "registro.json"
ARCHIVOS_CODIGO = ("variables_corto_plazo.py", "corto_plazo.py")
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
    ruta.write_text(json.dumps(reg, ensure_ascii=False, indent=1), encoding="utf-8")
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
    clave = f"{carpeta_modelos().resolve()}::{mid}"
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
    return {"model_id": mid, "manifiesto": man, "arboles": arboles}


def limpiar_cache() -> None:
    with _CANDADO:
        _CACHE.clear()
    _serie.cache_clear()
    _dia_en.cache_clear()


def ficha(modelo: dict) -> dict:
    """Versión del modelo que acompaña cada pronóstico (§9.2: model_id, feature_version, data_cutoff, SHA-256)."""
    man = modelo["manifiesto"]
    return {"model_id": modelo["model_id"], "tipo": man.get("tipo"), "feature_version": man.get("feature_version"),
            "data_cutoff": man.get("data_cutoff"), "entrenado_con": man.get("entrenado_con"),
            "semilla": man.get("semilla"), "estructura": man.get("estructura"),
            "banda": (man.get("banda") or {}).get("metodo"),
            "sha256": {k: a["sha256"] for k, a in man["artefactos"].items()},
            "version_datos": man.get("version_datos"), "metricas_prueba": man.get("metricas_prueba"),
            "origen": man.get("origen"), "evaluacion": "pronostico_corto_plazo/README.md (experimento E14)"}


# ----------------------------------------------------------------------------------------------- datos
def idruta_de(ruta: str | int) -> int:
    """El idruta de la ruta (por nombre del catálogo o por idruta). FueraDeCobertura si no es una de las tres."""
    texto = str(ruta).strip()
    for idruta, nombre in V.RUTAS.items():
        if texto in (nombre, str(idruta)):
            return idruta
    raise FueraDeCobertura(f"Ruta sin pronóstico de corto plazo: {ruta!r}. Rutas: {list(V.RUTAS.values())}")


def serie(idruta: int) -> V.Ruta:
    """La serie de 15 minutos de la ruta (se lee una vez por proceso y carpeta de datos)."""
    return _serie(idruta, str(carpeta_datos()))


@lru_cache(maxsize=6)
def _serie(idruta: int, carpeta: str) -> V.Ruta:
    return V.cargar_ruta(idruta, Path(carpeta))


def fecha_de_dia(d: int) -> date:
    return (V.DIA0 + timedelta(days=d)).date()


def dia_de_fecha(fecha: date) -> int:
    return (fecha - V.DIA0.date()).days


def cobertura() -> dict:
    """Las fechas que se pueden pronosticar: desde el día ARRANQUE (hacen falta 8 semanas de historia) hasta el
    último día del panel; las de la prueba reservada son las que el modelo no vio al entrenar."""
    r = serie(next(iter(V.RUTAS)))
    a, b = V.rango_dias("prueba")
    return {"desde": fecha_de_dia(V.ARRANQUE), "hasta": fecha_de_dia(len(r.cal) - 1),
            "fuera_de_muestra_desde": fecha_de_dia(a), "fuera_de_muestra_hasta": fecha_de_dia(min(b, len(r.cal) - 1))}


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
def _dia(model_id: str, idruta: int, d: int, horizonte_min: int) -> dict:
    """Todo el día d de la ruta para el horizonte: los 35 instantes de 04:00 a 21:00, por ruta, sentido y segmento,
    con banda, líneas base y lo real de cada ventana. Cada instante solo usa lo observado antes de él."""
    return _dia_en(model_id, idruta, d, horizonte_min, str(carpeta_datos()), str(carpeta_modelos()))


@lru_cache(maxsize=64)
def _dia_en(model_id: str, idruta: int, d: int, horizonte_min: int, _datos: str, _modelos: str) -> dict:
    modelo = cargar(model_id)
    man = modelo["manifiesto"]
    r = serie(idruta)
    if not V.ARRANQUE <= d < len(r.cal):
        cob = cobertura()
        raise FueraDeCobertura(f"La fecha {fecha_de_dia(d)} no se puede pronosticar: hay datos de corto plazo del "
                               f"{cob['desde']} al {cob['hasta']} (hacen falta 8 semanas de historia)")
    rr = r.recorte(d - V.ARRANQUE, d)
    nombre = V.RUTAS[idruta]
    i = len(V.INSTANTES)
    out: dict = {"idruta": idruta, "ruta": nombre, "dia": d, "horizonte_min": horizonte_min,
                 "dia_con_datos": bool(r.ok[d])}
    for nivel in NIVELES_CON_MODELO:
        v = V.variables(rr, nivel, horizonte_min, man["conjunto"][nivel])
        g = v["forma"][2]
        ult = slice(len(v["y"]) - i * g, len(v["y"]))
        x = v["x"][ult]
        # float32, como en el experimento (la banda se asigna por tramo del pronóstico)
        arbol = modelo["arboles"][clave_artefacto(nivel, horizonte_min, idruta)]
        p = np.clip(arbol.predict(x), 0, None).astype(np.float32)
        out[nivel] = {"p": p.reshape(i, g), "y": v["y"][ult].reshape(i, g),
                      "base": {k: b[ult].reshape(i, g) for k, b in v["base"].items()},
                      "x": x.reshape(i, g, -1), "nombres": v["nombres"]}
        out[nivel]["p10"], out[nivel]["p90"] = (b.reshape(i, g) for b in V.conformal_aplicar(
            p, man["banda"]["calibracion"][nivel][str(horizonte_min)][nombre]))
    # sentido = suma de sus segmentos (estructura elegida en la validación), con su propia banda calibrada
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


def pronosticar(ruta: str | int, instante: datetime, horizonte_min: int, model_id: str | None = None,
                incluir_segmentos: bool = True) -> dict:
    """El pronóstico de la ventana [t, t + h) de la ruta: total, por sentido y por segmento, con banda P10-P90,
    líneas base, explicación local y lo real (si la ventana ya está en los datos, para comparar)."""
    t0 = time.perf_counter()
    if horizonte_min not in V.HORIZONTES:
        raise FueraDeCobertura(f"Horizonte {horizonte_min}: el pronóstico de corto plazo es a 30, 60 o 120 minutos")
    idruta = idruta_de(ruta)
    fecha, bloque, usado = instante_local(instante)
    modelo = cargar(model_id)
    mid = modelo["model_id"]
    d = dia_de_fecha(fecha)
    dia = _dia(mid, idruta, d, horizonte_min)
    j = int(np.flatnonzero(V.INSTANTES == bloque)[0])
    r = serie(idruta)
    con_real = dia["dia_con_datos"]
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
    salida["latencia_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    return salida


def pronosticar_dia(ruta: str | int, fecha: date, horizonte_min: int, model_id: str | None = None) -> dict:
    """La curva del día: los 35 instantes de 04:00 a 21:00 de la ruta y de cada sentido (para el tablero)."""
    if horizonte_min not in V.HORIZONTES:
        raise FueraDeCobertura(f"Horizonte {horizonte_min}: el pronóstico de corto plazo es a 30, 60 o 120 minutos")
    idruta = idruta_de(ruta)
    modelo = cargar(model_id)
    d = dia_de_fecha(fecha)
    dia = _dia(modelo["model_id"], idruta, d, horizonte_min)
    con_real = dia["dia_con_datos"]
    puntos = []
    for j, bloque in enumerate(V.INSTANTES.tolist()):
        hora = datetime(fecha.year, fecha.month, fecha.day, bloque // 4, (bloque % 4) * 15, tzinfo=ZONA)
        puntos.append({"instante": hora.isoformat(), "franja": V.franja_de(bloque),
                       **_celda(dia["ruta"], j, 0, con_real),
                       "sentidos": [{"sentido": s, **_celda(dia["sentido"], j, k, con_real)}
                                    for k, s in enumerate(SENTIDOS)]})
    return {"ruta": V.RUTAS[idruta], "idruta": idruta, "fecha": fecha.isoformat(), "horizonte_min": horizonte_min,
            "model_id": modelo["model_id"], "en_muestra": d <= V.rango_dias("validacion")[1],
            "dia_con_datos": con_real, "instantes": puntos}


# ---------------------------------------------------------------------------------------- recomendación y guardado
def recomendacion(sesion, r: dict, info: dict) -> dict:
    """§10.2 con el pronóstico de la ventana llevado a ritmo por hora (× 60 / horizonte), en la hora del punto medio
    de la ventana, con la misma función y la misma restricción reactiva que la recomendación de /predictions/run.
    Las subidas de la ventana y los pasajeros por hora de salida del modelo horario miden lo mismo (cada pasajero
    sube una vez); el panel cuenta por instante de la subida y el modelo horario por hora de salida del viaje."""
    from app.servicios import ejecucion, ocupacion

    escala = 60.0 / float(r["horizonte_min"])
    instante = datetime.fromisoformat(r["instante"])
    medio = instante + timedelta(minutes=r["horizonte_min"] / 2)
    hora = min(max(medio.hour, min(datos.HORAS_SERVICIO)), max(datos.HORAS_SERVICIO))
    franja = {"fecha": medio.date(), "hora": hora, "demanda_hora": float(r["pasajeros"]) * escala,
              "p10_hora": None if r.get("p10") is None else float(r["p10"]) * escala,
              "p90_hora": None if r.get("p90") is None else float(r["p90"]) * escala}
    version_u, umbrales = ejecucion.umbrales_vigentes(sesion)
    reactiva = ocupacion.reactiva_guardada(sesion, info["ruta"], franja["fecha"], instante, umbrales)
    rec_d, _ = ejecucion.recomendacion_con_ocupacion(info, franja, umbrales, version_u, reactiva)
    claves = ("buses_hora", "headway_min", "vehiculos_requeridos", "viable", "motivo", "capacidad_efectiva",
              "ocupacion_esperada", "frecuencia_actual_min", "diferencia_min", "frecuenciadespachos_min",
              "diferencia_frecuenciadespachos_min", "formula")
    return {"fecha": franja["fecha"].isoformat(), "hora": hora, "demanda_hora": round(franja["demanda_hora"], 1),
            "demanda_p10": None if franja["p10_hora"] is None else round(franja["p10_hora"], 1),
            "demanda_p90": None if franja["p90_hora"] is None else round(franja["p90_hora"], 1),
            "umbrales_version": version_u,
            "fuente": "pronóstico de corto plazo de la ventana llevado a ritmo por hora (× 60 / horizonte)",
            **{k: ejecucion.json_seguro(rec_d.get(k)) for k in claves},
            "restriccion_reactiva": ejecucion.json_seguro(rec_d.get("restriccion_reactiva"))}


def guardar(sesion, r: dict, execution_id=None):
    """RF-006 y §9.2: guarda el pronóstico (la ruta, sus sentidos y sus segmentos) con su banda, sus líneas base, el
    modelo, la versión de variables, la fecha de corte, cuándo se generó y la latencia. Devuelve el grupo_id."""
    import uuid

    from app.modelos_db import PrediccionCortoPlazo

    grupo = uuid.uuid4()
    instante = datetime.fromisoformat(r["instante"])
    objetivo = datetime.fromisoformat(r["ventana"]["hasta"])
    generada = datetime.fromisoformat(r["generated_at"]) if r.get("generated_at") else datetime.now(UTC)
    comun = {"grupo_id": grupo, "execution_id": execution_id, "ruta": r["ruta"], "idruta": r["idruta"],
             "instante": instante, "horizonte_min": r["horizonte_min"], "objetivo": objetivo,
             "fecha": instante.date(), "franja": r.get("franja"), "model_id": r["model_id"],
             "feature_version": r["feature_version"], "data_cutoff": date.fromisoformat(r["data_cutoff"]),
             "generated_at": generada, "latencia_ms": r.get("latencia_ms")}

    def fila(nivel: str, celda: dict, **extra):
        return PrediccionCortoPlazo(prediction_id=uuid.uuid4(), nivel=nivel, pasajeros=celda["pasajeros"],
                                    p10=celda.get("p10"), p90=celda.get("p90"),
                                    promedio_dia_hora=celda.get("promedio_dia_hora"),
                                    ultima_semana=celda.get("ultima_semana"), **comun, **extra)

    sesion.add(fila("ruta", r, explicacion=r.get("explicacion") or {},
                    variables={"observado": r.get("observado"), "en_muestra": r.get("en_muestra"),
                               "dia_con_datos": r.get("dia_con_datos"),
                               "instante_solicitado": r.get("instante_solicitado")},
                    recomendacion=r.get("recomendacion")))
    for s in r.get("sentidos") or []:
        sesion.add(fila("sentido", s, sentido=s["sentido"]))
    for s in r.get("segmentos") or []:
        sesion.add(fila("segmento", s, sentido=s["sentido"], nro_segmento=s["nro_segmento"],
                        variables={"km_inicio": s.get("km_inicio")}))
    return grupo
