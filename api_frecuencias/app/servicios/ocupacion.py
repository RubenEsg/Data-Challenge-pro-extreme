"""Ocupación de los buses por segmento, histórica y actual (especificación v1.5, §10.1, §5.2 ALT-002 y §11.1).

§10.1 pide como variables de decisión la «ocupación histórica de los buses por segmento, estacionalidad, día de la
semana y rango de horas» y la «ocupación actual por segmento, estacionalidad actual, día de la semana y hora».
timbradas_segmentos.pasajeros no sirve para eso (hallazgo H9: es la diferencia de los contadores acumulados del
dispositivo), pero las subidas y las bajadas por segmento de cada viaje sí, y §11.1 permite hacer en la capa propia
cualquier transformación adicional. El método es el MISMO para el histórico y para el ciclo (cargas_por_segmento):

- unidad: un viaje (id_viaje = progvehiculos.idprogramacion) en un segmento, con las subidas y las bajadas sumadas en
  todos sus bloques de 15 minutos (un viaje puede cruzar un segmento en dos bloques, errata E2);
- los segmentos del viaje en el orden de nro_segmento (cada ruta es un ciclo que empieza en el segmento 1);
- carga al salir del segmento k = max(0, carga al salir del segmento k − 1 + subidas_k − bajadas_k), con carga 0 al
  empezar el viaje: la suma de (subidas − bajadas) de los segmentos 1..k acotada en 0 en cada segmento. Así una
  bajada de más (un evento que el trigger asignó al segmento vecino, o una subida que el contador no vio) no deja la
  carga negativa ni se arrastra a los segmentos siguientes. Es la carga a bordo; la ocupación es carga / puestos;
- un viaje cuenta en los segmentos entre el primero y el último que registró; en un segmento sin eventos la carga es
  la del anterior. Su carga máxima y su segmento crítico (el primero que la alcanza) salen de ahí;
- sentido aproximado: «ida» los segmentos cuyo punto medio cae en la primera mitad de la longitud del ciclo de la ruta,
  «regreso» el resto (la regla de scripts/preparar_segmentos.py: las exportaciones no traen el sentido).
Supuestos, validación contra la ocupación máxima del dispositivo y alternativas: docs/ocupacion_segmentos.md.

Histórico (segmento_critico_historico): datos/ocupacion_segmentos_hora.parquet, que arma
scripts/preparar_ocupacion_segmentos.py con las exportaciones de 2023-01-01 a 2023-02-27 (lo único que llenaron los
triggers de segmentación): carga media, P50, P90 y máxima por segmento, estacionalidad (nula para Sobusa por H1), día
de operación ISO (7 = domingo o festivo, como el tipo de día del plan D5) y hora de salida del viaje, y la misma tabla
por tipo de día como respaldo de las celdas con pocos días.

Actual (del_ciclo): el ciclo lee, viaje por viaje y en solo lectura, las franjas (ruta, fecha, hora de salida) que le
entregó la lectura incremental en las últimas VENTANA_ACTUAL_H horas de cada ruta (franjas_del_lote; el ciclo de las
5:15 ya trae las primeras salidas del día en curso y así mide también el día que acaba de terminar) con
fuentes.FuentePostgresSoloLectura.leer_carga_segmentos (las mismas franjas, así que convive con la marca de agua por
ruta sin una marca propia), calcula la ocupación por segmento y la guarda en
ai_frecuencias.ocupacion_segmento (migración 0011) con el segmento crítico de cada hora marcado, el día ISO de la fecha
y la estacionalidad actual (la que trae el lote de la lectura integrada; si no, la dimensión de §8.3). El optimizador la
recibe como una restricción reactiva de seguridad (restriccion_reactiva) y ALT-002 observada la mide en el segmento
crítico, con el viaje, el vehículo y el conductor (solo seudónimo, §18) del viaje más cargado.
"""
from __future__ import annotations

import logging
import uuid
from datetime import date, datetime
from functools import lru_cache
from typing import Any

import numpy as np
import pandas as pd

log = logging.getLogger("api_frecuencias.ocupacion")

ARCHIVO_PERFIL = "ocupacion_segmentos_hora.parquet"
PERIODO_HISTORICO = "2023-01-01 a 2023-02-27"
NIVEL_DIA, NIVEL_TIPO = "dia_semana", "tipo_dia"
MIN_DIAS_CELDA = 4             # celda día de la semana × hora con menos días: se usa la del tipo de día
MIN_VIAJES_CELDA = 20          # ... o con menos viajes
MAX_HORAS_SIN_DATO = 2         # la hora cerrada sirve para la siguiente programable si no está a más de 2 h
VENTANA_ACTUAL_H = 24          # ocupación actual: las franjas del lote en las últimas 24 h de cada ruta
CAPACIDAD_POR_OMISION = 50.0   # puestos por bus del catálogo del proyecto (regla del reto)
HORA_ULTIMA_SERVICIO = 20
EPS = 1e-9
TIPOS_DIA = ("Laboral", "Sábado", "Domingo/festivo")
DIAS = {1: "lunes", 2: "martes", 3: "miércoles", 4: "jueves", 5: "viernes", 6: "sábado", 7: "domingo o festivo"}
METODO = ("carga al salir del segmento k = max(0, carga al salir del segmento k − 1 + subidas_k − bajadas_k) en el "
          "orden de nro_segmento (la suma de subidas − bajadas de los segmentos 1..k acotada en 0 en cada segmento); "
          "ocupación = carga / puestos por bus")
FUENTE_HISTORICA = ("datos/ocupacion_segmentos_hora.parquet: subidas y bajadas por segmento de cada viaje "
                    "(timbradas_segmentos 2023-01-01 a 2023-02-27, scripts/preparar_ocupacion_segmentos.py)")
FUENTE_ACTUAL = ("ai_frecuencias.ocupacion_segmento: subidas y bajadas por segmento de los viajes de las franjas que "
                 "trajo la lectura incremental (timbradas_segmentos que llena tg_timbrada_segmento)")
NATURALEZA_REACTIVA = ("restricción reactiva de seguridad con la ocupación observada; no es un re-pronóstico (en el "
                       "backtest del proyecto, re-pronosticar dentro del día no mejoró la precisión)")
COLUMNAS_FILAS = ("ruta", "idruta", "fecha", "hora", "id_viaje", "vehiculo", "conductor", "terminado", "id_segmento",
                  "nro_segmento", "subidas", "bajadas")


def _f(x, d=1):
    """Número con coma decimal (es-CO) para las explicaciones."""
    return f"{x:,.{d}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _pct(x) -> str:
    return f"{_f(100 * float(x), 0)} %"


def _fecha(valor) -> date:
    """La fecha (date) de un valor date, datetime, Timestamp o texto. Las llaves (fecha, hora) de la ocupación observada
    se comparan con date: un Timestamp nunca es igual a un date (pandas 2), y la llave quedaría sin encontrar."""
    if isinstance(valor, datetime):
        return valor.date()
    return valor if isinstance(valor, date) else pd.Timestamp(valor).date()


# ---------------------------------------------------------------- método (histórico y ciclo)
def cargas_por_segmento(filas: pd.DataFrame) -> pd.DataFrame:
    """Carga a bordo al salir de cada segmento que registró cada viaje: [id_viaje, nro_segmento, id_segmento,
    subidas, bajadas, carga], en el orden de nro_segmento. Usa la forma cerrada de la recursión acotada en 0:
    carga_k = S_k − min(0, min_{j<=k} S_j), con S_k = Σ (subidas − bajadas) de los segmentos 1..k."""
    columnas = ["id_viaje", "nro_segmento", "id_segmento", "subidas", "bajadas", "carga"]
    if filas is None or not len(filas):
        return pd.DataFrame(columns=columnas)
    d = (filas.groupby(["id_viaje", "nro_segmento"], as_index=False, sort=True)
         .agg(id_segmento=("id_segmento", "first"), subidas=("subidas", "sum"), bajadas=("bajadas", "sum")))
    acumulada = (d["subidas"] - d["bajadas"]).astype(float).groupby(d["id_viaje"]).cumsum()
    d["carga"] = acumulada - acumulada.groupby(d["id_viaje"]).cummin().clip(upper=0.0)
    return d[columnas]


def cargas_en_el_tramo(cargas: pd.DataFrame) -> pd.DataFrame:
    """[id_viaje, nro_segmento, carga] de cada viaje en TODOS los segmentos entre el primero y el último que registró:
    en un segmento sin eventos la carga es la del anterior (nadie subió ni bajó)."""
    if not len(cargas):
        return pd.DataFrame(columns=["id_viaje", "nro_segmento", "carga"])
    g = cargas.groupby("id_viaje", sort=True)["nro_segmento"].agg(["min", "max"])
    largo = (g["max"] - g["min"] + 1).to_numpy(dtype=np.int64)
    inicio = np.repeat(g["min"].to_numpy(dtype=np.int64), largo)
    desplazamiento = np.arange(int(largo.sum())) - np.repeat(np.cumsum(largo) - largo, largo)
    malla = pd.DataFrame({"id_viaje": np.repeat(g.index.to_numpy(), largo), "nro_segmento": inicio + desplazamiento})
    malla = malla.merge(cargas[["id_viaje", "nro_segmento", "carga"]], on=["id_viaje", "nro_segmento"], how="left")
    malla["carga"] = malla.groupby("id_viaje")["carga"].ffill()
    return malla


def resumen_viajes(cargas: pd.DataFrame) -> pd.DataFrame:
    """Por viaje: subidas, bajadas, segmentos registrados, primero y último, carga máxima y su segmento crítico (el
    primero que la alcanza)."""
    if not len(cargas):
        return pd.DataFrame(columns=["id_viaje", "subidas", "bajadas", "segmentos", "primero", "ultimo", "carga_max",
                                     "nro_segmento_critico", "id_segmento_critico"])
    g = cargas.groupby("id_viaje", sort=True).agg(subidas=("subidas", "sum"), bajadas=("bajadas", "sum"),
                                                  segmentos=("nro_segmento", "size"), primero=("nro_segmento", "min"),
                                                  ultimo=("nro_segmento", "max"))
    criticos = cargas.loc[cargas.groupby("id_viaje", sort=True)["carga"].idxmax().to_numpy()]
    criticos = criticos.set_index("id_viaje")[["carga", "nro_segmento", "id_segmento"]].rename(
        columns={"carga": "carga_max", "nro_segmento": "nro_segmento_critico", "id_segmento": "id_segmento_critico"})
    return g.join(criticos).reset_index()


def sentidos(segmentos: pd.DataFrame) -> pd.DataFrame:
    """sentido («ida» / «regreso») y km de inicio de cada segmento [idruta, nro_segmento, longitud_m, ...]: «ida» si el
    punto medio del segmento cae en la primera mitad de la longitud acumulada del ciclo de su ruta (aproximación
    declarada: las exportaciones no traen el sentido)."""
    partes = []
    for _, g in segmentos.sort_values(["idruta", "nro_segmento"]).groupby("idruta", sort=True):
        acumulada = g["longitud_m"].astype(float).cumsum()
        medio = acumulada - g["longitud_m"].astype(float) / 2
        partes.append(g.assign(sentido=np.where(medio <= float(g["longitud_m"].sum()) / 2, "ida", "regreso"),
                               km_inicio=(acumulada - g["longitud_m"].astype(float)) / 1000))
    return pd.concat(partes, ignore_index=True) if partes else segmentos.assign(sentido=None, km_inicio=None)


# ---------------------------------------------------------------- histórico (§10.1, perfil versionado)
def perfil_historico() -> pd.DataFrame | None:
    """El perfil histórico empaquetado (datos/ocupacion_segmentos_hora.parquet); None si no está."""
    from app.servicios import datos

    return datos.ocupacion_segmentos_historica()


def catalogo_segmentos() -> pd.DataFrame:
    """[ruta, idruta, id_segmento, nro_segmento, sentido, km_inicio, longitud_m] de los segmentos del perfil."""
    p = perfil_historico()
    columnas = ["ruta", "idruta", "id_segmento", "nro_segmento", "sentido", "km_inicio", "longitud_m"]
    if p is None or p.empty:
        return pd.DataFrame(columns=columnas)
    return p[columnas].drop_duplicates(["idruta", "nro_segmento"]).reset_index(drop=True)


@lru_cache(maxsize=2)
def _criticos(huella: float) -> dict:
    """{(ruta, nivel, día o tipo de día, hora): el segmento con la mayor carga media} del perfil histórico."""
    p = perfil_historico()
    if huella < 0 or p is None or p.empty:
        return {}
    clave = np.where(p["nivel"] == NIVEL_DIA, p["id_dia_semana"].fillna(0), p["tipo_dia"].fillna(0)).astype(int)
    p = p.assign(clave=clave)
    filas = p.loc[p.groupby(["ruta", "nivel", "clave", "hora"])["carga_media"].idxmax().to_numpy()]
    return {(str(f["ruta"]), str(f["nivel"]), int(f["clave"]), int(f["hora"])): f for f in filas.to_dict("records")}


def _suficiente(fila: dict) -> bool:
    return int(fila.get("dias") or 0) >= MIN_DIAS_CELDA and int(fila.get("nro_viajes") or 0) >= MIN_VIAJES_CELDA


def _texto_historico(c: dict) -> str:
    """La frase de la explicación: cuál es el segmento crítico y su ocupación histórica."""
    cuando = (f"los {DIAS.get(c['id_dia_semana'], c['id_dia_semana'])}" if c["nivel"] == NIVEL_DIA
              else f"los días de tipo {TIPOS_DIA[c['tipo_dia']].lower()}")
    return (f"Segmento crítico histórico de la franja: el {c['nro_segmento']} ({c['sentido'] or 'sentido sin dato'}, "
            f"desde el km {_f(c['km_inicio'] or 0.0)}), con {_f(c['carga_media'])} pasajeros a bordo en promedio al "
            f"salir de él ({_pct(c['ocupacion_media'])} de {_f(c['capacidad'], 0)} puestos; P90 "
            f"{_f(c['carga_p90'])}, {_pct(c['ocupacion_p90'])}) en {c['nro_viajes']} viajes de {c['dias']} días "
            f"({cuando} a las {c['hora']}:00, {PERIODO_HISTORICO}); fue el tramo más cargado del "
            f"{_pct(c['fraccion_viajes_criticos'])} de esos viajes.")


def _describir_critico(fila: dict, capacidad: float) -> dict:
    nivel = str(fila["nivel"])
    salida = {
        "id_segmento": int(fila["id_segmento"]), "nro_segmento": int(fila["nro_segmento"]),
        "sentido": fila.get("sentido"), "km_inicio": round(float(fila.get("km_inicio") or 0.0), 3),
        "nivel": nivel, "id_dia_semana": int(fila["id_dia_semana"]) if nivel == NIVEL_DIA else None,
        "tipo_dia": int(fila["tipo_dia"]), "hora": int(fila["hora"]),
        "id_estacionalidad": None if pd.isna(fila.get("id_estacionalidad")) else int(fila["id_estacionalidad"]),
        "nro_viajes": int(fila["nro_viajes"]), "dias": int(fila["dias"]),
        "carga_media": round(float(fila["carga_media"]), 2), "carga_p50": round(float(fila["carga_p50"]), 2),
        "carga_p90": round(float(fila["carga_p90"]), 2), "carga_max": int(fila["carga_max"]),
        "capacidad": float(capacidad), "ocupacion_media": round(float(fila["carga_media"]) / capacidad, 4),
        "ocupacion_p90": round(float(fila["carga_p90"]) / capacidad, 4),
        "fraccion_viajes_criticos": round(float(fila["viajes_criticos"]) / max(int(fila["nro_viajes"]), 1), 4),
        "periodo": PERIODO_HISTORICO, "metodo": METODO, "fuente": FUENTE_HISTORICA}
    salida["texto"] = _texto_historico(salida)
    return salida


def segmento_critico_historico(ruta: str, fecha: Any, hora: int, capacidad: float | None = None) -> dict | None:
    """§10.1 ocupación histórica: el segmento con la mayor carga media de la ruta en el día de operación ISO de la
    fecha (7 = domingo o festivo) y la hora de salida, con su ocupación (carga / `capacidad`, 50 puestos por omisión).
    Con menos de MIN_DIAS_CELDA días o MIN_VIAJES_CELDA viajes en esa celda, el del tipo de día de la operación. None
    si la ruta o la hora no tienen perfil. La estacionalidad queda nula para Sobusa (hallazgo H1)."""
    from app.servicios import datos, optimizacion

    criticos = _criticos(datos.huella_archivo(ARCHIVO_PERFIL))
    if not criticos:
        return None
    dia = optimizacion.dia_semana_operacion(fecha)
    fila = criticos.get((ruta, NIVEL_DIA, int(dia), int(hora))) if dia else None
    if fila is None or not _suficiente(fila):
        fila = criticos.get((ruta, NIVEL_TIPO, optimizacion.tipo_dia_operacion(fecha), int(hora)))
    cap = float(capacidad) if capacidad else CAPACIDAD_POR_OMISION
    return None if fila is None else _describir_critico(fila, cap)


def limpiar_cache() -> None:
    _criticos.cache_clear()


# ---------------------------------------------------------------- actual (§10.1): ocupación observada en el ciclo
def _viajes_de(filas: pd.DataFrame) -> pd.DataFrame:
    """Un registro por viaje con su franja y sus datos operativos (el vehículo y el conductor, ya seudónimo)."""
    columnas = [c for c in ("id_viaje", "ruta", "idruta", "fecha", "hora", "vehiculo", "conductor", "terminado")
                if c in filas.columns]
    return filas[columnas].drop_duplicates("id_viaje").set_index("id_viaje")


def _metadatos_segmentos(filas: pd.DataFrame) -> pd.DataFrame:
    """id_segmento, sentido y km de cada (idruta, nro_segmento): del perfil empaquetado y, si falta, de lo leído."""
    leidos = filas[["idruta", "nro_segmento", "id_segmento"]].drop_duplicates(["idruta", "nro_segmento"])
    cat = catalogo_segmentos()[["idruta", "nro_segmento", "id_segmento", "sentido", "km_inicio"]]
    unidos = leidos.merge(cat, on=["idruta", "nro_segmento"], how="outer", suffixes=("", "_perfil"))
    unidos["id_segmento"] = unidos["id_segmento"].fillna(unidos.pop("id_segmento_perfil"))
    return unidos


def _por_segmento(malla: pd.DataFrame) -> pd.DataFrame:
    """Ocupación por (ruta, fecha, hora, segmento): viajes medidos, carga media y máxima y el viaje de la máxima."""
    llave = ["ruta", "idruta", "fecha", "hora", "nro_segmento"]
    g = malla.groupby(llave, sort=True)
    tabla = g.agg(nro_viajes=("carga", "size"), carga_media=("carga", "mean"), carga_max=("carga", "max"),
                  carga_total=("carga", "sum")).reset_index()
    maximos = malla.loc[g["carga"].idxmax().to_numpy(), [*llave, "id_viaje"]]
    return tabla.merge(maximos.rename(columns={"id_viaje": "id_viaje_max"}), on=llave, how="left")


def _marcar_criticos(tabla: pd.DataFrame) -> pd.DataFrame:
    """critico = el segmento con la mayor carga media de cada franja (el primero si empatan)."""
    tabla["critico"] = False
    indices = tabla.groupby(["ruta", "fecha", "hora"], sort=False)["carga_media"].idxmax().to_numpy()
    tabla.loc[indices, "critico"] = True
    return tabla


def calcular_observada(filas: pd.DataFrame, capacidades: dict[str, float]) -> pd.DataFrame:
    """Ocupación actual por segmento de las franjas leídas: una fila por (ruta, fecha, hora de salida, segmento) con
    los viajes medidos, la carga media, la máxima, la ocupación (carga / puestos de la ruta), el viaje de la carga
    máxima, el sentido aproximado y el segmento crítico de la franja marcado. Vacía si no hay filas."""
    if filas is None or not len(filas):
        return pd.DataFrame()
    viajes = _viajes_de(filas)
    malla = cargas_en_el_tramo(cargas_por_segmento(filas))
    malla = malla.join(viajes[["ruta", "idruta", "fecha", "hora"]], on="id_viaje")
    tabla = _por_segmento(malla).merge(_metadatos_segmentos(filas), on=["idruta", "nro_segmento"], how="left")
    tabla = tabla[tabla["id_segmento"].notna()].reset_index(drop=True)
    tabla["capacidad"] = tabla["ruta"].map(lambda r: float(capacidades.get(r) or CAPACIDAD_POR_OMISION))
    tabla["ocupacion_media"] = tabla["carga_media"] / tabla["capacidad"]
    tabla["ocupacion_max"] = tabla["carga_max"] / tabla["capacidad"]
    terminados = viajes.groupby(["ruta", "fecha", "hora"])["terminado"].sum() if "terminado" in viajes else None
    if terminados is not None:
        tabla = tabla.join(terminados.rename("viajes_terminados"), on=["ruta", "fecha", "hora"])
    return _marcar_criticos(tabla)


def _viaje_critico(viajes: pd.DataFrame, fila: dict) -> dict:
    """El viaje con la mayor carga en el segmento crítico de la franja: id, vehículo y conductor (seudónimo). `viajes`
    es _viajes_de(filas), calculado una sola vez para todas las franjas."""
    from app.servicios.fuentes import identificador_entero

    ident = fila.get("id_viaje_max")
    if ident is None or ident not in viajes.index:
        return {"id_viaje": None, "vehiculo": None, "conductor": None}
    v = viajes.loc[ident]
    return {"id_viaje": int(ident),
            "vehiculo": None if pd.isna(v.get("vehiculo")) else str(identificador_entero(v.get("vehiculo"))),
            "conductor": None if pd.isna(v.get("conductor")) else str(v.get("conductor")),
            "carga": round(float(fila["carga_max"]), 1)}


def resumen_por_hora(tabla: pd.DataFrame, filas: pd.DataFrame) -> dict[str, dict]:
    """{ruta: {(fecha, hora): resumen}} del segmento crítico de cada franja: segmento, sentido, viajes medidos, carga
    media y máxima, ocupación, carga crítica de la hora (Σ de la carga de los viajes en ese segmento, pasajeros/h) y el
    viaje más cargado con su vehículo y su conductor (solo seudónimo)."""
    salida: dict[str, dict] = {}
    if tabla is None or not len(tabla):
        return salida
    viajes = _viajes_de(filas)
    for fila in tabla[tabla["critico"]].to_dict("records"):
        fecha = _fecha(fila["fecha"])
        salida.setdefault(str(fila["ruta"]), {})[(fecha, int(fila["hora"]))] = {
            "ruta": str(fila["ruta"]), "fecha": fecha, "hora": int(fila["hora"]),
            "id_segmento": int(fila["id_segmento"]), "nro_segmento": int(fila["nro_segmento"]),
            "sentido": fila.get("sentido") if isinstance(fila.get("sentido"), str) else None,
            "km_inicio": None if pd.isna(fila.get("km_inicio")) else round(float(fila["km_inicio"]), 3),
            "nro_viajes": int(fila["nro_viajes"]),
            "viajes_terminados": None if pd.isna(fila.get("viajes_terminados")) else int(fila["viajes_terminados"]),
            "carga_media": round(float(fila["carga_media"]), 2), "carga_max": round(float(fila["carga_max"]), 1),
            "carga_total": round(float(fila["carga_total"]), 1), "capacidad": float(fila["capacidad"]),
            "ocupacion_media": round(float(fila["ocupacion_media"]), 4),
            "ocupacion_max": round(float(fila["ocupacion_max"]), 4),
            "viaje": _viaje_critico(viajes, fila), "metodo": METODO, "fuente": FUENTE_ACTUAL}
    return salida


def franjas_del_lote(validos, cerradas_hasta: datetime | None = None) -> list[tuple[str, date, int]]:
    """(ruta, fecha, hora) del lote validado en las últimas VENTANA_ACTUAL_H horas de cada ruta, contadas hacia atrás
    desde su franja más reciente: las horas que acaban de llegar (la ocupación actual). No basta el último día del
    lote: con la captura en vivo, el ciclo programado de las 5:15 ya trae las primeras salidas del día en curso (sus
    viajes van por la mitad), y con solo ese día nunca mediría ni guardaría el día que acaba de terminar. Lo anterior a
    la ventana (la carga inicial o un dato tardío) no se relee viaje por viaje: su ocupación es histórica.

    Con `cerradas_hasta` (la referencia del ciclo), solo las horas ya cerradas: aquellas cuyas salidas ya ocurrieron
    (inicio + 1 h <= referencia). La hora en curso no se mide ni se guarda: ni la restricción reactiva ni ALT-002 la
    usan, y sus viajes siguen llegando, así que el ciclo siguiente la trae otra vez en su lote."""
    if validos is None or not len(validos) or not {"ruta", "fecha", "hora"} <= set(validos.columns):
        return []
    d = validos[["ruta", "fecha", "hora"]].drop_duplicates().copy()
    d["fecha"] = pd.to_datetime(d["fecha"]).dt.date
    inicio = pd.to_datetime(d["fecha"]) + pd.to_timedelta(d["hora"].astype(int), unit="h")
    vigentes = inicio > inicio.groupby(d["ruta"]).transform("max") - pd.Timedelta(hours=VENTANA_ACTUAL_H)
    if cerradas_hasta is not None:
        limite = pd.Timestamp(_local_sin_zona(cerradas_hasta))
        vigentes &= inicio + pd.Timedelta(hours=1) <= limite
    return sorted((str(r), f, int(h)) for r, f, h in d[vigentes].itertuples(index=False))


def _local_sin_zona(instante: datetime) -> datetime:
    """El instante en hora de Bogotá sin zona (las franjas del lote son horas locales sin zona)."""
    from app.servicios.ejecucion import ZONA

    local = instante.astimezone(ZONA) if instante.tzinfo else instante
    return local.replace(tzinfo=None)


def capacidades_de(rutas, umbrales: dict | None, version: int | None) -> dict[str, float]:
    """Puestos por bus de cada ruta, los mismos del plan: el ajuste local gobernado si lo hay, si no el catálogo."""
    from app.servicios import datos, optimizacion

    salida = {}
    for ruta in rutas:
        gobernada = optimizacion._capacidad_gobernada(ruta, umbrales or {}, version)
        if gobernada.get("fuente") == optimizacion.AJUSTE_LOCAL and gobernada.get("capacidad"):
            salida[ruta] = float(gobernada["capacidad"])
            continue
        try:
            salida[ruta] = float(datos.ruta_info(ruta).get("capacidad") or CAPACIDAD_POR_OMISION)
        except KeyError:
            salida[ruta] = CAPACIDAD_POR_OMISION
    return salida


def leer_franjas(fuente: Any, franjas: list[tuple[str, date, int]]) -> pd.DataFrame | None:
    """Las filas viaje × segmento de las franjas, si la fuente las expone (la réplica o producción); None si no (el
    modo offline no tiene datos por segmento y viaje)."""
    leer = getattr(fuente, "leer_carga_segmentos", None)
    if leer is None or not franjas:
        return None
    return leer(franjas)


def del_ciclo(s, fuente: Any, validos, execution_id: uuid.UUID | None, umbrales: dict | None,
              version: int | None, cerradas_hasta: datetime | None = None) -> dict[str, Any]:
    """§10.1 ocupación actual en el ciclo: lee viaje por viaje las franjas del lote (con `cerradas_hasta`, solo las
    horas ya cerradas a esa referencia), guarda su ocupación por segmento (guardar) y devuelve {"por_ruta": {ruta:
    {(fecha, hora): resumen}}, "resumen": métricas}. Sin datos por segmento (modo offline o sin franjas nuevas)
    devuelve por_ruta vacío y dice por qué."""
    franjas = franjas_del_lote(validos, cerradas_hasta)
    filas = leer_franjas(fuente, franjas)
    if filas is None or not len(filas):
        motivo = ("la fuente no expone viajes por segmento (modo offline)" if filas is None and franjas
                  else "sin franjas nuevas con viajes medidos por segmento")
        return {"por_ruta": {}, "resumen": {"franjas_leidas": len(franjas), "filas": 0, "nota": motivo}}
    tabla = calcular_observada(filas, capacidades_de(sorted({r for r, _, _ in franjas}), umbrales, version))
    guardadas = guardar(s, tabla, franjas, execution_id, estacionalidades_del_lote(validos))
    por_ruta = resumen_por_hora(tabla, filas)
    return {"por_ruta": por_ruta, "resumen": {
        "franjas_leidas": len(franjas), "filas": int(len(filas)), "viajes": int(filas["id_viaje"].nunique()),
        "filas_guardadas": guardadas, "franjas_con_ocupacion": sum(len(v) for v in por_ruta.values()),
        "lectura": getattr(fuente, "resumen_carga", None), "metodo": METODO}}


# ---------------------------------------------------------------- persistencia (migración 0011)
def estacionalidades_del_lote(validos) -> dict[tuple[str, date], int | None]:
    """§10.1 «estacionalidad actual»: la id_estacionalidad que trae el lote de la lectura integrada por (ruta, fecha)
    (fuentes._SQL_DEMANDA_SEGMENTOS la une con estacionalidades_anio vigente en la fecha). Vacío si el lote no la trae
    (modo offline): entonces rige la dimensión de §8.3 (nula para Sobusa con las exportaciones, hallazgo H1)."""
    if validos is None or not len(validos) or "id_estacionalidad" not in validos.columns:
        return {}
    d = validos[["ruta", "fecha", "id_estacionalidad"]].dropna().drop_duplicates(["ruta", "fecha"])
    return {(str(r), pd.Timestamp(f).date()): int(e) for r, f, e in d.itertuples(index=False)}


def _dimensiones(ruta: str, fecha: date, estacionalidad: int | None) -> dict:
    from app.servicios.ejecucion import dimensiones_fila

    d = dimensiones_fila(ruta, fecha)
    return {"id_dia_semana": d.get("id_dia_semana") or fecha.isoweekday(),
            "id_estacionalidad": estacionalidad if estacionalidad is not None else d.get("id_estacionalidad")}


def _filas_tabla(tabla: pd.DataFrame, execution_id: uuid.UUID | None, estaciones: dict | None = None) -> list[dict]:
    """Las filas de ai_frecuencias.ocupacion_segmento, con las dimensiones de §8.3 de la franja (la estacionalidad
    actual del lote si la trae)."""
    dims: dict[tuple, dict] = {}
    filas = []
    for f in tabla.to_dict("records"):
        fecha = _fecha(f["fecha"])
        clave = (f["ruta"], fecha)
        if clave not in dims:
            dims[clave] = _dimensiones(f["ruta"], fecha, (estaciones or {}).get(clave))
        filas.append({"ruta": str(f["ruta"]), "idruta": int(f["idruta"]), "fecha": fecha, "hora": int(f["hora"]),
                      "nro_segmento": int(f["nro_segmento"]), "id_segmento": int(f["id_segmento"]),
                      "sentido": f.get("sentido") if isinstance(f.get("sentido"), str) else None,
                      "nro_viajes": int(f["nro_viajes"]), "carga_media": float(f["carga_media"]),
                      "carga_max": float(f["carga_max"]), "capacidad": float(f["capacidad"]),
                      "ocupacion_media": float(f["ocupacion_media"]), "ocupacion_max": float(f["ocupacion_max"]),
                      "id_viaje_max": None if pd.isna(f.get("id_viaje_max")) else int(f["id_viaje_max"]),
                      "critico": bool(f["critico"]), "execution_id": execution_id, **dims[clave]})
    return filas


def guardar(s, tabla: pd.DataFrame, franjas: list[tuple[str, date, int]], execution_id: uuid.UUID | None,
            estaciones: dict | None = None) -> int:
    """Reemplaza, en la transacción del ciclo, las filas de las franjas leídas en ai_frecuencias.ocupacion_segmento:
    una franja releída (llegó otro viaje o se corrigió uno) queda con su cálculo completo nuevo, nunca duplicada.
    estaciones = {(ruta, fecha): id_estacionalidad} de la lectura (estacionalidades_del_lote)."""
    from sqlalchemy import delete, insert, tuple_

    from app.modelos_db import OcupacionSegmento

    if franjas:
        s.execute(delete(OcupacionSegmento).where(
            tuple_(OcupacionSegmento.ruta, OcupacionSegmento.fecha, OcupacionSegmento.hora).in_(franjas)))
    filas = _filas_tabla(tabla, execution_id, estaciones) if tabla is not None and len(tabla) else []
    if filas:
        s.execute(insert(OcupacionSegmento), filas)
    return len(filas)


# ---------------------------------------------------------------- restricción reactiva (§10.1 actual → optimizador)
def _hora_del_instante(instante: datetime | None, fecha_plan: date) -> int | None:
    """La hora del instante del ciclo en Bogotá si cae en el día del plan; None si no (ciclo nocturno o re-plan)."""
    if instante is None:
        return None
    from app.servicios.ejecucion import ZONA

    local = instante.astimezone(ZONA) if instante.tzinfo else instante
    return local.hour if local.date() == fecha_plan else None


def _no_aplica(base: dict, motivo: str) -> dict:
    return dict(base, aplica=False, motivo=motivo)


def _ultima_cerrada(observada: dict, fecha_plan: date, hora_instante: int, minimo: int) -> tuple[int, dict] | None:
    """(hora, resumen) de la última hora del día del plan cuyas salidas ya ocurrieron (antes de la hora del instante)
    con al menos `minimo` viajes medidos en su segmento crítico. Sus viajes pueden ir todavía en curso (duran unas
    3,5 h en Sobusa): la ocupación es la de los viajes que ya pasaron por cada segmento (viajes_terminados lo dice)."""
    cerradas = [(h, r) for (f, h), r in observada.items()
                if f == fecha_plan and h < hora_instante and int(r.get("nro_viajes") or 0) >= minimo]
    return max(cerradas, key=lambda x: x[0]) if cerradas else None


def restriccion_reactiva(observada: dict | None, fecha_plan: date, instante: datetime | None,
                         umbrales: dict | None) -> dict | None:
    """§10.1 ocupación actual como entrada del optimizador (una restricción reactiva de seguridad, no un re-pronóstico).

    Si en la última hora cerrada del día del plan la ocupación observada del segmento crítico alcanza el umbral crítico
    (ocupacion_critica de la versión de umbrales del ciclo, 0,90 por omisión), la hora siguiente que todavía se puede
    programar (la siguiente a la cerrada, o la del instante si ya pasó, a lo sumo MAX_HORAS_SIN_DATO horas después) no
    puede tener menos salidas que las que esa carga exige: el plan del día las calcula con la fórmula de §10.3,
    ceil(carga crítica observada / (puestos × ocupación objetivo máxima)). observada = {(fecha, hora): resumen} de la
    ruta (resumen_por_hora). None si no hay ocupación observada; si no aplica, dice por qué."""
    if not observada:
        return None
    u = umbrales or {}
    critico = float(u.get("ocupacion_critica", 0.90))
    minimo = max(int(float(u.get("salidas_minimas_ocupacion", 2))), 1)
    base = {"naturaleza": NATURALEZA_REACTIVA, "umbral_critico": critico, "fecha_plan": fecha_plan.isoformat(),
            "minimo_viajes_medidos": minimo, "fuente": FUENTE_ACTUAL}
    hora_instante = _hora_del_instante(instante, fecha_plan)
    if hora_instante is None:
        return _no_aplica(base, "El instante del ciclo no está en el día del plan: la ocupación observada solo "
                                "restringe las horas que faltan del mismo día (ciclo intradía).")
    cerrada = _ultima_cerrada(observada, fecha_plan, hora_instante, minimo)
    if cerrada is None:
        return _no_aplica(base, f"Antes de las {hora_instante}:00 del día del plan no hay una hora cerrada con al "
                                f"menos {minimo} viajes medidos por segmento.")
    return _evaluar_cerrada(base, cerrada, hora_instante, critico)


_SQL_OBSERVADA_GUARDADA = """
SELECT hora, nro_segmento, id_segmento, sentido, nro_viajes, carga_media, carga_max, capacidad, ocupacion_media,
       ocupacion_max, id_viaje_max, actualizado_en
  FROM ai_frecuencias.ocupacion_segmento
 WHERE ruta = :ruta AND fecha = :fecha AND critico AND actualizado_en <= :medida_hasta
"""


def observada_guardada(s, ruta: str, fecha: date, medida_hasta: datetime) -> dict:
    """§10.1 la ocupación actual que ya midieron los ciclos (ai_frecuencias.ocupacion_segmento) para una recomendación
    pedida fuera del ciclo: {(fecha, hora): resumen del segmento crítico}, como resumen_por_hora, con solo lo medido
    hasta `medida_hasta` (el instante de la predicción: §9.3, ninguna variable posterior al instante; la medición de
    una hora se completa mientras sus viajes terminan). Vacío si no hay nada medido."""
    from sqlalchemy import text

    filas = s.execute(text(_SQL_OBSERVADA_GUARDADA),
                      {"ruta": ruta, "fecha": fecha, "medida_hasta": medida_hasta}).mappings().all()
    return {(fecha, int(f["hora"])): _resumen_guardado(ruta, fecha, f) for f in filas}


def _resumen_guardado(ruta: str, fecha: date, f) -> dict:
    """Una franja guardada en el formato de resumen_por_hora. La tabla guarda solo el id del viaje más cargado
    (id_viaje_max, progvehiculos.idprogramacion), sin su vehículo ni su conductor: «viaje» queda vacío y el id va
    aparte, para que ALT-002 lo identifique con los viajes del día que ya leyó el ciclo
    (alertas._viaje_del_segmento)."""
    viajes = int(f["nro_viajes"])
    ident = f.get("id_viaje_max")
    return {"ruta": ruta, "fecha": fecha, "hora": int(f["hora"]), "id_segmento": int(f["id_segmento"]),
            "nro_segmento": int(f["nro_segmento"]), "sentido": f["sentido"], "nro_viajes": viajes,
            "viajes_terminados": None, "carga_media": round(float(f["carga_media"]), 2),
            "carga_max": round(float(f["carga_max"]), 1), "carga_total": round(float(f["carga_media"]) * viajes, 1),
            "capacidad": float(f["capacidad"]), "ocupacion_media": round(float(f["ocupacion_media"]), 4),
            "ocupacion_max": round(float(f["ocupacion_max"]), 4), "viaje": None,
            "id_viaje_max": None if ident is None or pd.isna(ident) else int(ident), "medida_en": f["actualizado_en"],
            "metodo": METODO, "fuente": FUENTE_ACTUAL}


def reactiva_guardada(s, ruta: str, fecha: date, instante: datetime | None, umbrales: dict | None) -> dict | None:
    """La restricción reactiva (restriccion_reactiva) de una recomendación pedida fuera del ciclo (POST
    /predictions/run) con la ocupación actual guardada hasta su instante (observada_guardada). None sin instante o sin
    nada medido: la recomendación es la de siempre."""
    if instante is None:
        return None
    return restriccion_reactiva(observada_guardada(s, ruta, fecha, instante), fecha, instante, umbrales)


def _evaluar_cerrada(base: dict, cerrada: tuple[int, dict], hora_instante: int, critico: float) -> dict:
    """La restricción de la última hora cerrada: dónde aplica y si su ocupación observada supera el umbral."""
    hora, r = cerrada
    aplica_en = max(hora + 1, hora_instante)
    base = dict(base, hora_cerrada=hora, hora_aplica=aplica_en, segmento=r["nro_segmento"],
                id_segmento=r["id_segmento"], sentido=r.get("sentido"), nro_viajes=r["nro_viajes"],
                viajes_terminados=r.get("viajes_terminados"),
                ocupacion_observada=r["ocupacion_media"], carga_critica_pax_h=r["carga_total"],
                capacidad_observada=r["capacidad"], viaje=r.get("viaje"))
    if aplica_en > HORA_ULTIMA_SERVICIO or aplica_en - hora > MAX_HORAS_SIN_DATO:
        return _no_aplica(base, f"La última hora cerrada con datos ({hora}:00) no sirve para programar: la hora "
                                f"siguiente programable sería las {aplica_en}:00.")
    texto = (f"En la última hora cerrada ({hora}:00) la ocupación observada del segmento crítico {r['nro_segmento']} "
             f"({r.get('sentido') or 'sentido sin dato'}) fue {_pct(r['ocupacion_media'])} en {r['nro_viajes']} "
             f"viajes, con {_f(r['carga_total'])} pasajeros a bordo en ese segmento en la hora")
    if float(r["ocupacion_media"]) < critico - EPS:
        return _no_aplica(base, texto + f", por debajo del umbral crítico de {_pct(critico)}: no restringe el plan.")
    return dict(base, aplica=True, motivo=texto + f", que alcanza el umbral crítico de {_pct(critico)}: las salidas "
                                                  f"de las {aplica_en}:00 no pueden ser menos de las que exige esa "
                                                  f"carga.")


def _tope_por_flota(entradas: dict) -> int | None:
    """Buses/h que la flota disponible sostiene en la franja con el ciclo de la ruta: floor(flota × 60 / ciclo), la
    restricción de flota y ciclo del MILP de la franja (vehículos = ceil(ciclo × buses/h / 60) <= flota). None si la
    franja no conoce la flota o el ciclo."""
    import math

    flota, ciclo = entradas.get("flota_disponible"), entradas.get("tiempo_ciclo_min")
    if not flota or not ciclo or float(ciclo) <= 0:
        return None
    return int(math.floor(float(flota) * 60.0 / float(ciclo) + EPS))


def _acotar_piso(pedidas: int, tope_headway: int, tope_flota: int | None) -> tuple[int, str]:
    """Las salidas que se exigen (las pedidas, sin pasar el tope del headway mínimo ni lo que la flota sostiene) y la
    cola de la fórmula que lo dice."""
    if tope_flota is not None and tope_flota < min(pedidas, tope_headway):
        return tope_flota, f" → acotado por la flota disponible y el ciclo a {tope_flota}"
    if pedidas > tope_headway:
        return tope_headway, f" → acotado por el headway mínimo a {tope_headway}"
    return pedidas, ""


def piso_de_la_franja(reactiva: dict | None, fecha: date, hora: int, entradas: dict) -> dict | None:
    """§10.1 y §10.2: la restricción reactiva en la recomendación de una franja (las de 30, 60 y 120 min del ciclo y la
    de POST /predictions/run, con reactiva_guardada), la misma que recibe el plan del día. Si aplica
    (restriccion_reactiva) y la franja es la hora en que actúa, del mismo día del plan, la franja no puede tener menos
    buses/h que ceil(carga crítica observada / (puestos × ocupación objetivo máxima)), con los puestos y la ocupación
    objetivo de la franja (`entradas` de
    optimizacion.recomendacion_franja); es la fórmula del piso del plan con la hora entera. Como en el plan, el piso no
    pasa del tope del headway mínimo (floor(60 / headway_min)) y, en la franja, tampoco de lo que la flota disponible
    sostiene con el ciclo de la ruta (_tope_por_flota): el MILP de la franja dimensiona la flota en régimen (vehículos =
    ciclo × buses/h / 60), mientras que el del plan sigue los buses en ruta cada 15 minutos. None si no aplica."""
    import math

    if not (reactiva and reactiva.get("aplica")) or reactiva.get("fecha_plan") != _fecha(fecha).isoformat() \
            or int(reactiva.get("hora_aplica", -1)) != int(hora):
        return None
    cap = float(entradas.get("capacidad") or CAPACIDAD_POR_OMISION)
    occ = float(entradas.get("ocupacion_objetivo") or 0.85)
    carga = float(reactiva["carga_critica_pax_h"])
    pedidas = int(math.ceil(carga / (cap * occ) - EPS))
    tope_headway = int(math.floor(60.0 / float(entradas.get("headway_min") or 2.0) + EPS))
    tope_flota = _tope_por_flota(entradas)
    minimas, cola = _acotar_piso(pedidas, tope_headway, tope_flota)
    return {"hora_cerrada": reactiva.get("hora_cerrada"), "hora_aplica": int(hora),
            "segmento": reactiva.get("segmento"), "sentido": reactiva.get("sentido"),
            "ocupacion_observada": reactiva.get("ocupacion_observada"),
            "carga_critica_pax_h": carga, "capacidad": cap, "ocupacion_objetivo_max": occ, "salidas_pedidas": pedidas,
            "salidas_minimas": minimas, "limitada_por_headway_minimo": pedidas > tope_headway,
            "limitada_por_flota": minimas < min(pedidas, tope_headway), "tope_por_flota": tope_flota,
            "formula": f"buses_minimos = ceil({_f(carga)} / ({_f(cap, 0)} × {_f(occ, 2)})) = {pedidas}" + cola,
            "naturaleza": NATURALEZA_REACTIVA, "fuente": reactiva.get("fuente")}


def piso_acotado(piso: dict, salidas: int) -> dict:
    """El piso de la franja con las salidas que de verdad se pueden ejecutar (el MILP de la franja no es viable con
    más: la flota disponible de cada tipología con el ciclo de la ruta). Igual si no cambia."""
    if int(salidas) >= int(piso["salidas_minimas"]):
        return piso
    base = str(piso["formula"]).split(" → ")[0]
    return dict(piso, salidas_minimas=int(salidas), limitada_por_flota=True,
                formula=f"{base} → acotado por la flota disponible de cada tipología y el ciclo a {int(salidas)}")


__all__ = ["ARCHIVO_PERFIL", "METODO", "NATURALEZA_REACTIVA", "PERIODO_HISTORICO", "calcular_observada",
           "capacidades_de", "cargas_en_el_tramo", "cargas_por_segmento", "catalogo_segmentos", "del_ciclo",
           "guardar", "leer_franjas", "limpiar_cache", "observada_guardada", "perfil_historico", "piso_acotado",
           "piso_de_la_franja", "reactiva_guardada", "restriccion_reactiva", "resumen_por_hora", "resumen_viajes",
           "segmento_critico_historico", "sentidos"]
