"""Carga en la fuente del ciclo intradía (§10.1, PLAN_INTRADIA_CRON) frente al ciclo diario, medida en la réplica
local en solo lectura (RNF-001, RNF-005; §14.1 «lectura incremental sin degradar el esquema actual»).

Como lector_ia (READ ONLY, statement_timeout, ROLLBACK: nada se escribe en la réplica), con la misma clase que usa el
ciclo (app/servicios/fuentes.FuentePostgresSoloLectura) y sus SELECT de la lista blanca, mide --repeticiones veces cada
lectura que hace un ciclo en la base de Extreme:

- la lectura incremental de demanda_segmentos sin nada nuevo desde la marca, de todas las rutas y de una ruta
  (RNF-005): su costo es fijo, porque timbradas_segmentos no tiene índice por su marca (hallazgo H12), y es el piso de
  lo que paga cada ciclo intradía aunque la hora no traiga datos;
- la ocupación por segmento (leer_carga_segmentos) de las franjas cerradas que trae un ciclo intradía a las (h+1):05
  (las 4 últimas horas de cada ruta, cuyos viajes de unas 3,5 h siguen llegando) y la de un día completo (51 franjas),
  que es lo que lee el ciclo de la madrugada; esta lectura cruza timbradas_segmentos por id_viaje (sin índice, H12) y
  también acota la parte de la lectura incremental que re-agrega las franjas tocadas;
- los viajes del día de cada ruta (progvehiculos, §5.3, con el conteo de sus filas de timbradas_segmentos, que cruza
  la tabla por id_viaje sin índice), la ubicación del despacho, "Procesos" y los catálogos de la calidad (§6.3);
- lo que el ciclo intradía no repite y el diario sí: los tres consolidados de Extreme leídos con su marca
  (app/servicios/consolidados.py) y la ventana del refresco de la agregación de segmentos (segmentos_refresco.py).

Con eso estima la carga en la fuente de un ciclo intradía, la de los 15 diarios del cron por omisión («5 6-20 * * *») y
la del ciclo diario. La réplica tiene 2,77 millones de filas de timbradas_segmentos (ene.-feb. 2023); con el histórico
completo (unos 58 millones, H12) el recorrido sin índice crece con la tabla: el informe lo estima escalando en
proporción a las filas las lecturas que recorren timbradas_segmentos (incluidos los viajes del día).

Uso:  python scripts/medir_ciclo_intradia.py [--dia 2023-02-08] [--repeticiones 3]
          [--salida docs/evidencias/ocupacion/ciclo_intradia_fuente.json]
Solo se conecta a la réplica LOCAL (scripts/replica_comun.py); la clave sale del .env y no se imprime.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from collections.abc import Callable
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

Z = ZoneInfo("America/Bogota")
RUTAS = ("SILENCIO", "CRA 54", "CL 72")
EVIDENCIA = RAIZ / "docs" / "evidencias" / "ocupacion" / "ciclo_intradia_fuente.json"
CICLOS_INTRADIA_POR_DIA = 15            # «5 6-20 * * *»
HORAS_EN_CURSO = 4                      # franjas cerradas cuyos viajes siguen llegando a las (h+1):05
CONSOLIDADOS = ("timbradas_consolidado", "timbradas_segmentos_anio", "timbradas_segmentos_consolidado")
# H12: con el histórico completo, unos 58 M de filas; las lecturas que recorren timbradas_segmentos sin índice. Los
# viajes del día también: su conteo de segmentos por viaje (fuentes.sql_viajes_ruta, CTE «segmentos») cruza
# timbradas_segmentos por id_viaje, que no tiene índice (EXPLAIN en la réplica: Seq Scan de la tabla entera), y
# progvehiculos por la hora de salida, tampoco indexada (índices 2 y 3 de la propuesta).
FILAS_HISTORICO_COMPLETO = 58_000_000
RECORREN_TIMBRADAS = frozenset({"incremental_todas", "incremental_una_ruta", "ocupacion_en_curso", "ocupacion_dia",
                                "viajes_del_dia", "ventana_refresco"})


def _fuente(tabla: str = "demanda_segmentos"):
    from app.servicios import fuentes
    from scripts import replica_comun as rc

    url = rc.url_rol("lector_ia")
    if not url:
        raise SystemExit("Falta la clave de lector_ia en el entorno o en el .env local (ver .env.example).")
    return fuentes.FuentePostgresSoloLectura(url=url.replace("postgresql://", "postgresql+psycopg://"), tabla=tabla,
                                             proceso="sobusa")


def medir(nombre: str, leer: Callable[[], object], repeticiones: int) -> dict:
    """La mediana (y el mínimo y el máximo) de `repeticiones` lecturas, con las filas que trajo la última."""
    tiempos, filas = [], None
    for _ in range(repeticiones):
        t0 = time.perf_counter()
        r = leer()
        tiempos.append(time.perf_counter() - t0)
        filas = _filas(r)
    print(f"  {nombre}: {statistics.median(tiempos):.2f} s (filas {filas})", flush=True)
    return {"lectura": nombre, "mediana_s": round(statistics.median(tiempos), 3), "min_s": round(min(tiempos), 3),
            "max_s": round(max(tiempos), 3), "filas": filas, "repeticiones": repeticiones}


def _filas(r) -> int | None:
    if r is None:
        return None
    if hasattr(r, "df"):
        return len(r.df)
    if isinstance(r, tuple):
        return _filas(r[0])
    if isinstance(r, dict):
        return sum(len(v) if hasattr(v, "__len__") else 1 for v in r.values())
    return len(r) if hasattr(r, "__len__") else None


def _marca_mayor(fuente) -> datetime:
    d = fuente.consultar("SELECT max(ultimaactualizacion) AS marca FROM timbradas_segmentos")
    return d["marca"].iloc[0].to_pydatetime().replace(tzinfo=Z)


def _franjas(dia: date, horas) -> list[tuple[str, date, int]]:
    return [(r, dia, h) for r in RUTAS for h in horas]


def lecturas(dia: date, repeticiones: int) -> dict:
    """Cada lectura de un ciclo en la base de Extreme, medida en la réplica como lector_ia."""
    from app.servicios import fuentes, segmentos_refresco

    f = _fuente()
    marca = _marca_mayor(f) + timedelta(hours=1)          # nada nuevo desde la marca: el costo fijo de cada ciclo
    todas = fuentes.Particion(proceso="sobusa", marca_resto=marca)
    una = fuentes.Particion(proceso="sobusa", rutas=("CL 72",), marcas={"CL 72": marca}, marca_resto=marca)
    inicio = datetime(dia.year, dia.month, dia.day, tzinfo=Z)
    segmentos = _fuente("timbradas_segmentos")
    r = {
        "incremental_todas": medir("incremental demanda_segmentos, todas las rutas, sin nada nuevo",
                                   lambda: f.leer_particion(todas), repeticiones),
        "incremental_una_ruta": medir("incremental demanda_segmentos, una ruta (RNF-005), sin nada nuevo",
                                      lambda: f.leer_particion(una), repeticiones),
        "ocupacion_en_curso": medir(f"ocupación por segmento de {HORAS_EN_CURSO} h × 3 rutas (ciclo intradía a las "
                                    "10:05)", lambda: f.leer_carga_segmentos(_franjas(dia, range(6, 10))),
                                    repeticiones),
        "ocupacion_dia": medir("ocupación por segmento de un día completo (51 franjas, ciclo de la madrugada)",
                               lambda: f.leer_carga_segmentos(_franjas(dia, range(4, 21))), repeticiones),
        "viajes_del_dia": medir("viajes del día de las 3 rutas (progvehiculos, §5.3)",
                                lambda: [f.viajes(ruta, inicio, inicio + timedelta(days=1)) for ruta in RUTAS],
                                repeticiones),
        "contexto": medir("ubicación del despacho de las 3 rutas, Procesos y catálogos de la calidad",
                          lambda: _contexto(), repeticiones),
        "consolidados": medir("los 3 consolidados con su marca, sin nada nuevo (solo el ciclo diario)",
                              lambda: [f.para_tabla(t).leer_incremental(marca_agua=marca) for t in CONSOLIDADOS],
                              repeticiones),
        "ventana_refresco": medir("ventana del refresco de segmentos (solo el ciclo diario y PLAN_SEGMENTOS_CRON)",
                                  lambda: segmentos.consultar(segmentos_refresco.SQL_FUENTE_VENTANA,
                                                              {"marca": marca}), repeticiones),
    }
    r["filas_timbradas_segmentos"] = int(f.consultar("SELECT count(*) AS n FROM timbradas_segmentos")["n"].iloc[0])
    return r


def _contexto():
    f = _fuente()
    return [f.ubicacion_despacho(r) for r in RUTAS] + [f.procesos(), f.catalogos_calidad()]


def _intradia(m: dict) -> float:
    """Segundos de la fuente de un ciclo intradía con las medianas `m`."""
    return m["incremental_todas"] + 2 * m["ocupacion_en_curso"] + m["viajes_del_dia"] + m["contexto"]


def estimar(r: dict) -> dict:
    """Segundos de la fuente por ciclo: el intradía lee lo incremental, la ocupación de sus horas en curso, los viajes
    del día y el contexto; el diario, además, la ocupación de un día, dos días de viajes, los consolidados y la ventana
    del refresco de segmentos. La parte de la lectura incremental que re-agrega las franjas tocadas se acota con la
    lectura de la ocupación de esas mismas franjas (las dos cruzan timbradas_segmentos por id_viaje): por eso cuenta dos
    veces. La proyección al histórico completo (H12) escala las lecturas que recorren timbradas_segmentos
    (RECORREN_TIMBRADAS, también los viajes del día) en proporción a sus filas: es una estimación sin los índices de la
    propuesta, no una medición."""
    m = {k: v["mediana_s"] for k, v in r.items() if isinstance(v, dict)}
    factor = FILAS_HISTORICO_COMPLETO / max(int(r["filas_timbradas_segmentos"]), 1)
    escalado = {k: v * (factor if k in RECORREN_TIMBRADAS else 1.0) for k, v in m.items()}
    diario = (m["incremental_todas"] + 2 * m["ocupacion_dia"] + 2 * m["viajes_del_dia"] + m["contexto"]
              + m["consolidados"] + m["ventana_refresco"])
    uno = _intradia(m)
    return {"intradia_s": round(uno, 2), "diario_s": round(diario, 2),
            "intradia_dia_s": round(CICLOS_INTRADIA_POR_DIA * uno, 1),
            "fraccion_de_la_hora_intradia": round(uno / 3600, 5),
            "intradia_sobre_diario": round(uno / diario, 3) if diario else None,
            "dia_con_intradia_sobre_dia_sin_intradia": round((diario + CICLOS_INTRADIA_POR_DIA * uno) / diario, 2)
            if diario else None,
            "proyeccion_historico_completo": {"factor_filas": round(factor, 1),
                                              "intradia_s": round(_intradia(escalado), 1),
                                              "fraccion_de_la_hora_intradia": round(_intradia(escalado) / 3600, 4)}}


def _es(valor: float, decimales: int = 2) -> str:
    """Un número con la coma decimal y el punto de miles, como el resto de la documentación."""
    return f"{valor:,.{decimales}f}".replace(",", "_").replace(".", ",").replace("_", ".")


def _fila_tabla(v: dict) -> str:
    filas = "—" if v["filas"] is None else _es(v["filas"], 0)
    return f"| {v['lectura']} | {_es(v['mediana_s'])} | {_es(v['min_s'])} a {_es(v['max_s'])} | {filas} |"


def informe(resultado: dict) -> str:
    e = resultado["estimacion"]
    p = e["proyeccion_historico_completo"]
    filas = [_fila_tabla(v) for v in resultado["lecturas"].values() if isinstance(v, dict)]
    n = _es(resultado["lecturas"]["filas_timbradas_segmentos"], 0)
    return "\n".join([
        "# Carga en la fuente del ciclo intradía (§10.1, PLAN_INTRADIA_CRON)", "",
        f"Generado por `scripts/medir_ciclo_intradia.py` el {resultado['generado_en']} en la réplica local, como "
        f"`lector_ia` (READ ONLY, `statement_timeout`, ROLLBACK), con {resultado['repeticiones']} repeticiones por "
        f"lectura y el día {resultado['dia']}. `timbradas_segmentos` tiene {n} filas. La columna Filas es lo que trajo "
        "la última repetición (en los viajes del día, el contexto y los consolidados, cuántas lecturas devolvieron "
        "algo).", "",
        "| Lectura | Mediana (s) | Rango (s) | Filas |", "|---|---:|---|---:|", *filas, "",
        "## Estimación por ciclo", "",
        f"- Ciclo intradía (lectura incremental, ocupación de sus {HORAS_EN_CURSO} horas en curso contada dos veces, "
        f"viajes del día y contexto): **{_es(e['intradia_s'], 1)} s** de la fuente, el "
        f"{_es(100 * e['fraccion_de_la_hora_intradia'])} % de la hora.",
        f"- Los {CICLOS_INTRADIA_POR_DIA} ciclos del cron por omisión («5 6-20 * * *»): "
        f"{_es(e['intradia_dia_s'], 0)} s al día.",
        f"- Ciclo diario (además, la ocupación de un día dos veces, dos días de viajes, los consolidados y la ventana "
        f"del refresco de segmentos): {_es(e['diario_s'], 1)} s. El día con los ciclos intradía lee "
        f"{_es(e['dia_con_intradia_sobre_dia_sin_intradia'], 1)} veces lo que leía solo con el diario.",
        f"- Proyección al histórico completo (unos 58 millones de filas, H12; {_es(p['factor_filas'], 1)} veces la "
        "réplica) sin los índices de la propuesta, escalando en proporción a las filas las lecturas que recorren "
        f"`timbradas_segmentos` (también los viajes del día, que la cruzan por `id_viaje`): "
        f"{_es(p['intradia_s'], 0)} s por ciclo intradía, el {_es(100 * p['fraccion_de_la_hora_intradia'], 1)} % de "
        "la hora. Es una estimación, no una medición.", "",
        "## Lectura", "",
        "- El piso de cada ciclo es la lectura incremental: recorre `timbradas_segmentos` entera porque no tiene "
        "índice por `ultimaactualizacion` (H12). Un ciclo intradía sin datos nuevos solo paga eso (y la frescura): no "
        "rehace predicciones ni plan.",
        "- El ciclo intradía no lee los consolidados ni la ventana del refresco de segmentos, y su ocupación es de sus "
        "horas cerradas en curso, no de un día.",
        "- Con los índices de `docs/evidencias/replica/propuesta_indices.sql` (los de `timbradas_segmentos` por "
        "`ultimaactualizacion` y por `id_viaje`, y el de `progvehiculos` por ruta y hora de salida) la lectura de una "
        "hora deja de depender del tamaño de las tablas; sin ellos, el costo de los ciclos intradía crece con el "
        "histórico. Por eso PLAN_INTRADIA_CRON se puede espaciar (por ejemplo «5 6-20/2 * * *») o apagar (vacío) sin "
        "tocar el código.",
        "- La efectividad dentro del día depende además de cuándo llegan las filas crudas a `conteo_pasajeros` "
        "(H10, H11): la sección «En tiempo real» de `backtest_restriccion_reactiva.md` lo mide.", ""])


def main(argv=None) -> dict:
    a = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    a.add_argument("--dia", type=date.fromisoformat, default=date(2023, 2, 8))
    a.add_argument("--repeticiones", type=int, default=3)
    a.add_argument("--salida", type=Path, default=EVIDENCIA)
    args = a.parse_args(argv)
    print(f"Lecturas de un ciclo en la réplica (lector_ia, solo lectura), día {args.dia}:", flush=True)
    resultado = {"generado_en": datetime.now(Z).isoformat(timespec="seconds"), "dia": args.dia.isoformat(),
                 "repeticiones": args.repeticiones, "lecturas": lecturas(args.dia, args.repeticiones)}
    resultado["estimacion"] = estimar(resultado["lecturas"])
    args.salida.parent.mkdir(parents=True, exist_ok=True)
    args.salida.write_text(json.dumps(resultado, ensure_ascii=False, indent=1, default=str) + "\n", encoding="utf-8")
    args.salida.with_suffix(".md").write_text(informe(resultado), encoding="utf-8")
    print(json.dumps(resultado["estimacion"], ensure_ascii=False), flush=True)
    return resultado


if __name__ == "__main__":
    main()
