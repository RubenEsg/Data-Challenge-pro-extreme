"""Lectura de los archivos de dash_app/datos/ (los deja ahí preparar_datos.py). Todo se lee una vez y queda en memoria."""
import json
import re
from functools import lru_cache

import pandas as pd

from motor import comun as C

DATOS = C.DATOS


@lru_cache(maxsize=1)
def cifras_app():
    """Objeto window.DATOS_APP de app/datos_app.js: pantallas -> clave -> {valor, unidad, archivo, clave, que_es, ...}."""
    return json.loads((DATOS / "cifras_app.json").read_text(encoding="utf-8"))


def cifra(pantalla, clave):
    return cifras_app()["pantallas"][pantalla][clave]


def valor(pantalla, clave):
    return cifra(pantalla, clave)["valor"]


def fuente(pantalla, clave):
    """Texto corto con el archivo y la clave de donde sale una cifra."""
    c = cifra(pantalla, clave)
    return f"{c.get('archivo', '')} · {c.get('clave', '')}"


@lru_cache(maxsize=1)
def ficha_modelos():
    return json.loads((DATOS / "ficha_modelos.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def sensibilidad_beta():
    return pd.read_csv(DATOS / "sensibilidad_beta.csv", sep=";", decimal=",", encoding="utf-8-sig")


@lru_cache(maxsize=1)
def beta_equilibrio():
    return pd.read_csv(DATOS / "beta_equilibrio.csv", sep=";", encoding="utf-8-sig")


@lru_cache(maxsize=1)
def pronosticos():
    p = pd.read_parquet(DATOS / "pronosticos_2025.parquet")
    p["dia"] = pd.to_datetime(p["dia"])
    return p


@lru_cache(maxsize=1)
def ahorro_anual():
    """datos/ahorro_anual.json: hoy, el plan que reasigna y el que recorta (planes), por_ruta, por_hora, contexto,
    palancas (aparte, no se suman), convenciones, campos (qué es cada cifra) y origen (archivo y clave de cada una)."""
    return json.loads((DATOS / "ahorro_anual.json").read_text(encoding="utf-8"))


def fuentes_ahorro(*rutas):
    """Archivos del proyecto de donde salen las cifras de ahorro_anual.json en esas rutas ('planes.reasigna.salidas_anio'...),
    sin repetir y en el orden en que aparecen."""
    org = ahorro_anual()["origen"]
    vistos = []
    for r in rutas:
        for a in str(org[r]["archivo"]).split(";"):
            a = re.sub(r"\s*\(.*\)$", "", a.strip())
            if a and a not in ("definición", "sin fuente") and a not in vistos:
                vistos.append(a)
    return vistos


@lru_cache(maxsize=1)
def modelo_producto():
    """datos/modelo_producto.json: el modelo que ejecuta la API (id, error en la prueba de nov–dic 2025 frente a la regla
    manual, intervalo bootstrap, cobertura de la banda con la calibración v2 y la v1) con el archivo y la clave de cada
    cifra en «origen». Vacío si falta (la pantalla lo dice)."""
    try:
        return json.loads((DATOS / "modelo_producto.json").read_text(encoding="utf-8"))
    except OSError:
        return {}


def fuentes_producto(*claves):
    """Archivos de donde salen esas cifras de modelo_producto.json, sin repetir."""
    org = modelo_producto().get("origen") or {}
    vistos = []
    for c in claves or org:
        a = (org.get(c) or {}).get("archivo")
        if a and a not in vistos:
            vistos.append(a)
    return vistos


@lru_cache(maxsize=1)
def origen():
    try:
        return json.loads((DATOS / "origen.json").read_text(encoding="utf-8"))
    except OSError:
        return {}


def faltan_datos():
    """Lista de archivos de datos/ que faltan (la app avisa en vez de fallar)."""
    necesarios = ["pronosticos_2025.parquet", "insumos_d5_2025.parquet", "costos_fuente.json", "cifras_app.json",
                  "ficha_modelos.json", "sensibilidad_beta.csv", "beta_equilibrio.csv", "ahorro_anual.json"]
    return [n for n in necesarios if not (DATOS / n).exists()]
