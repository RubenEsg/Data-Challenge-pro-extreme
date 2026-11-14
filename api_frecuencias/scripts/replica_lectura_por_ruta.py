"""RNF-005 · lectura incremental POR RUTA sobre la réplica de Extreme, SOLO LECTURA como lector_ia (§11.2, §11.3).

1. Lectura completa de demanda_segmentos (la de un trabajo de todas las rutas, desde la marca inicial).
2. Por cada ruta, la lectura de su trabajo (FuentePostgresSoloLectura.leer_particion con rutas = [ruta]): el mismo
   SELECT de la lista blanca con «r.nombre = ANY(:rutas)», en la transacción READ ONLY con statement_timeout. Debe
   entregar exactamente las filas de esa ruta de la lectura completa (llave y valores).
3. Desde una marca intermedia (la mediana de las marcas de la ruta) y desde la marca mayor (sin novedades): la
   lectura de la ruta frente a la de siempre filtrada por esa ruta, y EXPLAIN (ANALYZE, BUFFERS) de las dos
   variantes del SELECT con la misma marca (tiempo, filas y bloques).
Guarda docs/evidencias/cola/lectura_por_ruta_replica.txt y .json. No escribe nada en la réplica. Los tiempos dependen de
la carga del equipo: --nota deja dicho en el informe en qué condiciones se midió.

Uso: .venv\\Scripts\\python -m scripts.replica_lectura_por_ruta [--nota "equipo sin otras suites"]
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

import pandas as pd

from scripts import replica_comun as rc
from scripts import replica_explain as rx

SALIDA = rc.RAIZ / "docs" / "evidencias" / "cola"
CLAVE = ["ruta", "fecha", "hora"]
VALORES = ["pasajeros", "salidas", "subidas", "bajadas", "id_estacionalidad"]


def _url() -> str:
    url = rc.url_rol("lector_ia")
    if not url:
        raise SystemExit("Falta LECTOR_IA_PASSWORD en el entorno o en el .env local.")
    return url.replace("postgresql://", "postgresql+psycopg://")


def _fuente(motor):
    from app.servicios.fuentes import FuentePostgresSoloLectura

    return FuentePostgresSoloLectura(url="postgresql+psycopg://lector_ia@localhost/x", tabla="demanda_segmentos",
                                     motor=motor)


def _ordenado(d: pd.DataFrame) -> pd.DataFrame:
    return d[CLAVE + VALORES].sort_values(CLAVE).reset_index(drop=True)


def _iguales(a: pd.DataFrame, b: pd.DataFrame) -> bool:
    try:
        pd.testing.assert_frame_equal(_ordenado(a), _ordenado(b), check_dtype=False)
        return True
    except AssertionError:
        return False


def _explicar(motor, con_rutas: bool, marca: datetime, ruta: str | None) -> dict:
    f = _fuente(motor)
    compilado = f.consulta_incremental(con_rutas=con_rutas).compile(dialect=motor.dialect)
    params = dict(compilado.params) | {"marca": marca, "limite": f.limite, "proceso": f.proceso}
    if con_rutas:
        params["rutas"] = [ruta]
    r = rx.explicar(motor, str(compilado), params)
    return {k: r.get(k) for k in ("ms_ejecucion", "ms_planificacion", "filas", "buffers_hit", "buffers_read",
                                  "escaneos")}


def _desde_marca(motor, ruta: str, marca: datetime) -> dict:
    from app.servicios.fuentes import Particion

    d_legado, _ = _fuente(motor).leer_incremental(marca)
    de_la_ruta = d_legado[d_legado["ruta"] == ruta] if len(d_legado) else d_legado
    f = _fuente(motor)
    lectura = f.leer_particion(Particion(proceso="sobusa", rutas=(ruta,), marcas={ruta: marca}))
    desde = marca - timedelta(minutes=f.solape_min)
    iguales = _iguales(lectura.df, de_la_ruta) if len(de_la_ruta) else not len(lectura.df)
    return {"marca": marca.isoformat(), "filas_ruta": len(lectura.df),
            "filas_lectura_de_siempre_de_la_ruta": len(de_la_ruta), "iguales": iguales,
            "explain_todas": _explicar(motor, False, desde, None), "explain_ruta": _explicar(motor, True, desde, ruta)}


def medir() -> dict:
    from sqlalchemy import create_engine

    from app.servicios.fuentes import Particion

    motor = create_engine(_url(), pool_size=1, max_overflow=0)
    informe: dict = {"generado_en": datetime.now().astimezone().isoformat(), "rol": "lector_ia",
                     "tabla": "demanda_segmentos", "rutas": {}}
    try:
        completa, _ = _fuente(motor).leer_incremental(None)
        informe["filas_lectura_completa"] = len(completa)
        for ruta in sorted(completa["ruta"].unique()):
            f = _fuente(motor)
            propia = f.leer_particion(Particion(proceso="sobusa", rutas=(ruta,))).df
            marcas = pd.to_datetime(completa.loc[completa["ruta"] == ruta, "ultima_actualizacion"]).sort_values()
            mediana = pd.Timestamp(marcas.iloc[len(marcas) // 2]).to_pydatetime()
            mayor = pd.Timestamp(marcas.iloc[-1]).to_pydatetime()
            informe["rutas"][ruta] = {
                "carga_inicial": {"filas_ruta": len(propia), "filas_de_la_ruta_en_la_completa":
                                  int((completa["ruta"] == ruta).sum()),
                                  "iguales": _iguales(propia, completa[completa["ruta"] == ruta]),
                                  "solo_su_ruta": set(propia["ruta"]) == {ruta}},
                "desde_marca_intermedia": _desde_marca(motor, ruta, mediana),
                "desde_la_marca_mayor": _desde_marca(motor, ruta, mayor)}
    finally:
        motor.dispose()
    return informe


def _texto(inf: dict) -> str:
    lineas = [f"RNF-005 · lectura incremental por ruta en la réplica ({inf['generado_en']}), como {inf['rol']}, en "
              "transacción READ ONLY con statement_timeout (FuentePostgresSoloLectura.consultar)",
              *([f"Condiciones de la medición: {inf['nota_medicion']}"] if inf.get("nota_medicion") else []),
              f"Lectura completa de {inf['tabla']} desde la marca inicial: {inf['filas_lectura_completa']} filas", ""]
    for ruta, r in inf["rutas"].items():
        c = r["carga_inicial"]
        lineas.append(f"Ruta {ruta}: carga inicial de su trabajo {c['filas_ruta']} filas = "
                      f"{c['filas_de_la_ruta_en_la_completa']} de la completa; iguales en llave y valores: "
                      f"{c['iguales']}; solo su ruta: {c['solo_su_ruta']}")
        for nombre in ("desde_marca_intermedia", "desde_la_marca_mayor"):
            m = r[nombre]
            et, er = m["explain_todas"], m["explain_ruta"]
            lineas.append(f"   {nombre.replace('_', ' ')} ({m['marca']}): su trabajo {m['filas_ruta']} filas; la "
                          f"lectura de siempre, filtrada por la ruta, {m['filas_lectura_de_siempre_de_la_ruta']}; "
                          f"iguales: {m['iguales']}")
            lineas.append(f"      EXPLAIN todas las rutas: {et['ms_ejecucion']} ms, {et['filas']} filas, bloques "
                          f"{et['buffers_hit']} en caché + {et['buffers_read']} leídos")
            lineas.append(f"      EXPLAIN solo la ruta:    {er['ms_ejecucion']} ms, {er['filas']} filas, bloques "
                          f"{er['buffers_hit']} en caché + {er['buffers_read']} leídos")
    ok = all(r["carga_inicial"]["iguales"] and r["carga_inicial"]["solo_su_ruta"]
             and r["desde_marca_intermedia"]["iguales"] and r["desde_la_marca_mayor"]["iguales"]
             for r in inf["rutas"].values())
    lineas += ["", _lectura_de_los_planes(inf),
               f"RESULTADO: {'TODO OK' if ok else 'FALLAS'} (cada ruta lee exactamente lo suyo, desde su marca)"]
    return "\n".join(lineas) + "\n"


def _lectura_de_los_planes(inf: dict) -> str:
    """Qué dicen los planes medidos: tiempo medio de cada variante y las tablas que se recorren completas."""
    planes = [m for r in inf["rutas"].values() for m in (r["desde_marca_intermedia"], r["desde_la_marca_mayor"])]
    media = {k: sum(m[k]["ms_ejecucion"] for m in planes) / len(planes) for k in ("explain_todas", "explain_ruta")}
    completas = sorted({e for m in planes for e in m["explain_ruta"]["escaneos"] if e.startswith("Seq Scan")})
    return (f"Tiempo medio del SELECT: todas las rutas {media['explain_todas']:.0f} ms; una ruta "
            f"{media['explain_ruta']:.0f} ms. Recorridos completos en la variante por ruta: {', '.join(completas)}. "
            "La réplica no conserva los índices propuestos (docs/evidencias/replica/propuesta_indices.sql): cada "
            "lectura, de una ruta o de todas, busca lo cambiado recorriendo timbradas_segmentos; la de una ruta "
            "re-agrega solo sus franjas. Con la ejecución partida cada trabajo de ruta hace su propia lectura.\n")


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--nota", default="", help="condiciones de la medición (por ejemplo, la carga del equipo); va al "
                                              "encabezado del informe")
    a = p.parse_args(argv)
    informe = medir()
    if a.nota:
        informe["nota_medicion"] = a.nota
    SALIDA.mkdir(parents=True, exist_ok=True)
    (SALIDA / "lectura_por_ruta_replica.json").write_text(json.dumps(informe, ensure_ascii=False, indent=1,
                                                                     default=str), encoding="utf-8")
    texto = _texto(informe)
    (SALIDA / "lectura_por_ruta_replica.txt").write_text(texto, encoding="utf-8")
    print(texto)
    return 0 if "TODO OK" in texto else 1


if __name__ == "__main__":
    raise SystemExit(main())
