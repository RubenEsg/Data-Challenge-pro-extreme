"""Novedades viales por fecha, rango horario y ruta (§11.2 «Las novedades viales se cruzan por fecha, rango horario y
ruta para generar variables de impacto»; §6.1 potencial_efecto / porcentaje_impacto; RF-003).

Una novedad de novedades_viales_fecha afecta las horas de salida h (HORAS, 4 a 20) cuyo intervalo [h:00, h+1:00)
cruza [hora_inicio, hora_fin]: nov_impacto es su porcentaje_impacto y nov_sube = 1 si potencial_efecto = «SUBE». Si
varias novedades cruzan la misma hora, vale el máximo de cada variable (las variables nov_impacto y nov_sube de fv2,
app/servicios/variables.py).

Por ruta (novedades_viales_ruta, «rutas afectadas por cada novedad»):
- una novedad CON filas en novedades_viales_ruta afecta solo a esas rutas. Una fila con una ruta que no está en el
  catálogo de la API (otra empresa) o con una novedad que no existe se ignora y se cuenta: nunca se reparte la
  novedad a las demás rutas;
- una novedad SIN filas afecta a todas las rutas. Es el supuesto declarado para Sobusa: la tabla no tiene filas ni en
  la base del reto ni en la réplica, y sus 28 novedades (los días de Carnaval y sus eventos previos, los partidos de la
  Selección en el Metropolitano) son de toda la ciudad.

La parte de todas las rutas sigue en datos/contexto_operacional.parquet por fecha y hora (idéntica a la de antes
cuando novedades_viales_ruta está vacía: la reconstrucción desde la réplica lo comprueba); la de rutas dadas va
aparte, en datos/novedades_por_ruta.parquet (ruta, fecha, hora, nov_impacto, nov_sube; solo existe si hay novedades
por ruta), y aplicar_por_ruta la pone encima de la tabla de variables: en cada (ruta, fecha, hora), el máximo entre la
novedad de todas las rutas y la de su ruta. Lo hace inferencia.variables_de, el mismo paso al entrenar y al inferir.
Sin novedades por ruta la tabla queda exactamente igual, así que el modelo activo no cambia; si Extreme empieza a
llenar la tabla, el modelo siguiente aprende con el contexto por ruta.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

HORAS = (4, 20)
COLUMNAS_POR_RUTA = ["ruta", "fecha", "hora", "nov_impacto", "nov_sube"]
LLAVE = ["ruta", "fecha", "hora"]


def _hora(valor) -> int:
    return int(str(valor).split(":")[0])


def horas_afectadas(hora_inicio, hora_fin) -> range:
    """Horas de salida (HORAS) cuyo intervalo [h:00, h+1:00) cruza [hora_inicio, hora_fin]."""
    return range(max(HORAS[0], _hora(hora_inicio)), min(HORAS[1], _hora(hora_fin)) + 1)


def rutas_por_novedad(por_ruta: pd.DataFrame | None) -> dict[int, list[int]]:
    """{id_novedad_vial_fecha: [id_ruta, …]} de novedades_viales_ruta (vacío = todas las novedades son de todas las
    rutas)."""
    if por_ruta is None or por_ruta.empty:
        return {}
    limpias = por_ruta.dropna(subset=["id_novedad_vial_fecha", "id_ruta"])
    return {int(k): sorted({int(r) for r in g}) for k, g in limpias.groupby("id_novedad_vial_fecha")["id_ruta"]}


def de_todas_las_rutas(nov: pd.DataFrame, rutas_de: dict[int, list[int]]) -> pd.DataFrame:
    """Las novedades sin filas en novedades_viales_ruta (afectan a todas las rutas)."""
    if not rutas_de or nov.empty:
        return nov
    return nov[~nov["id_novedad_vial_fecha"].astype("int64").isin(list(rutas_de))]


def _efecto(r) -> dict:
    return {"fecha": pd.Timestamp(r.fecha).date(), "nov_impacto": float(r.porcentaje_impacto or 0),
            "nov_sube": int(str(r.potencial_efecto).upper() == "SUBE")}


def impacto_por_ruta(nov: pd.DataFrame, rutas_de: dict[int, list[int]], nombres: dict[int, str]) -> pd.DataFrame:
    """(ruta, fecha, hora, nov_impacto, nov_sube) de las novedades de rutas dadas, solo en sus rutas del catálogo
    (`nombres`: idruta -> nombre de la ruta); el máximo si varias cruzan la misma hora de la misma ruta."""
    filas = []
    for r in nov.itertuples():
        rutas = [nombres[i] for i in rutas_de.get(int(r.id_novedad_vial_fecha), ()) if i in nombres]
        filas += [{**_efecto(r), "ruta": ruta, "hora": h} for ruta in rutas
                  for h in horas_afectadas(r.hora_inicio, r.hora_fin)]
    salida = pd.DataFrame(filas, columns=COLUMNAS_POR_RUTA)
    if salida.empty:
        return salida
    return salida.groupby(LLAVE, as_index=False)[["nov_impacto", "nov_sube"]].max()[COLUMNAS_POR_RUTA]


def resumen(nov: pd.DataFrame, por_ruta: pd.DataFrame | None, nombres: dict[int, str]) -> dict:
    """Conteos para origen.json y la evidencia: cuántas novedades son de todas las rutas y cuántas de rutas dadas, y las
    filas de novedades_viales_ruta que no se pudieron aplicar (ruta fuera del catálogo o novedad inexistente)."""
    rutas_de = rutas_por_novedad(por_ruta)
    ids = {int(x) for x in nov["id_novedad_vial_fecha"].dropna()} if len(nov) else set()
    filas = 0 if por_ruta is None else len(por_ruta)
    fuera = sum(1 for rutas in rutas_de.values() for i in rutas if i not in nombres)
    huerfanas = sum(len(rutas) for k, rutas in rutas_de.items() if k not in ids)
    return {"filas_novedades_viales_ruta": int(filas), "novedades_por_ruta": len(ids & set(rutas_de)),
            "novedades_todas_las_rutas": len(ids - set(rutas_de)), "rutas_fuera_del_catalogo": int(fuera),
            "filas_sin_novedad": int(huerfanas)}


def aplicar_por_ruta(tabla: pd.DataFrame, por_ruta: pd.DataFrame | None) -> pd.DataFrame:
    """La tabla de variables (columnas ruta, fecha, hora, nov_impacto, nov_sube…) con las novedades de rutas dadas
    encima: en cada (ruta, fecha, hora) el máximo entre la de todas las rutas y la de su ruta. Sin novedades por ruta
    devuelve la MISMA tabla (ni una copia: nada cambia para el modelo activo)."""
    if por_ruta is None or por_ruta.empty:
        return tabla
    p = por_ruta.assign(fecha=pd.to_datetime(por_ruta["fecha"]).dt.date, hora=por_ruta["hora"].astype(int))
    p = p.groupby(LLAVE, as_index=False)[["nov_impacto", "nov_sube"]].max()
    p = p.rename(columns={"nov_impacto": "_nov_impacto_ruta", "nov_sube": "_nov_sube_ruta"})
    salida = tabla.merge(p, on=LLAVE, how="left", validate="many_to_one")
    for columna in ("nov_impacto", "nov_sube"):
        salida[columna] = np.fmax(salida[columna].astype(float), salida[f"_{columna}_ruta"].fillna(0).astype(float))
    salida.attrs = dict(tabla.attrs)
    return salida[list(tabla.columns)]


__all__ = ["HORAS", "COLUMNAS_POR_RUTA", "horas_afectadas", "rutas_por_novedad", "de_todas_las_rutas",
           "impacto_por_ruta", "resumen", "aplicar_por_ruta"]
