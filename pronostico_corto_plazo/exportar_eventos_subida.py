"""Exporta los EVENTOS DE SUBIDA de conteo_pasajeros_destino (los que tienen cantidad_subida > 0), por tramos de
idprogramacion, usando el único índice de la tabla. Solo lectura (sesión readonly, COPY de un SELECT a la salida
estándar). Reanudable: omite los tramos ya terminados (marca .ok).

Para qué: con el instante y la posición de cada subida se arma, en la capa analítica propia, la demanda por ruta,
sentido, segmento y franja de 15 minutos de 2023 a 2025 (la tabla timbradas_segmentos de la base solo cubre enero y
febrero de 2023), con la misma regla de Extreme: cada evento va al segmento más cercano.

Salida: datos/eventos_subida/eventos_<inicio>.parquet con idprogramacion, t (segundos desde 1970 de `fecha`, sin zona),
lat, lon (6 decimales, ~0,1 m; nulos si el evento no trae posición) y subidas.

Necesita credenciales.py en la raíz del proyecto (el acceso de solo lectura a la base del reto), que no viaja en la
entrega: quien no lo tenga parte de panel/, que ya trae el resultado.

Uso (desde la raíz del proyecto):  python EntregaFinal/pronostico_corto_plazo/exportar_eventos_subida.py
                                   ... --tramo 6240000   (solo el tramo de 20.000 ids que empieza ahí, para pruebas;
                                                          debe ser múltiplo de 20.000 para no repetir eventos)
"""
import io
import sys
import time
from pathlib import Path

import psycopg2
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.csv as pacsv
import pyarrow.parquet as pq

PROYECTO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROYECTO))  # credenciales.py vive en la raíz del proyecto
from credenciales import BASE_DE_DATOS, CLAVE, HOST, PUERTO, USUARIO  # credenciales.py no se sube al repositorio

CONN = dict(host=HOST, port=PUERTO, dbname=BASE_DE_DATOS, user=USUARIO, password=CLAVE, connect_timeout=30)
SALIDA = PROYECTO / "datos" / "eventos_subida"
ANCHO = 20_000            # ids de programación por tramo (~4.500 viajes, ~1,4 M eventos, ~0,3 M con subidas)
PAUSA = 2                 # segundos entre tramos, para no saturar el servidor compartido
TIMEOUT = "15min"

Q = """
copy (
  select c.idprogramacion, extract(epoch from c.fecha)::bigint as t,
         round(c.latitud::numeric, 6) as lat, round(c.longitud::numeric, 6) as lon, c.cantidad_subida as subidas
  from conteo_pasajeros_destino c
  where c.idprogramacion between {a} and {b} and c.cantidad_subida > 0
) to stdout with (format csv)
"""
ESQUEMA = pa.schema([("idprogramacion", pa.int64()), ("t", pa.int64()), ("lat", pa.float64()), ("lon", pa.float64()),
                     ("subidas", pa.int32())])


def procesar_tramo(cur, a, b):
    tag = f"{a:08d}"
    if (SALIDA / f"tramo_{tag}.ok").exists():
        return None
    t0 = time.time()
    buf = io.BytesIO()
    cur.copy_expert(Q.format(a=int(a), b=int(b)), buf)
    t1 = time.time()
    buf.seek(0)
    if buf.getbuffer().nbytes:
        tabla = pacsv.read_csv(buf, read_options=pacsv.ReadOptions(column_names=[f.name for f in ESQUEMA]),
                               convert_options=pacsv.ConvertOptions(column_types=ESQUEMA))
    else:
        tabla = ESQUEMA.empty_table()
    pq.write_table(tabla, SALIDA / f"eventos_{tag}.parquet", compression="zstd")
    subidas = int(pc.sum(tabla["subidas"]).as_py() or 0)
    (SALIDA / f"tramo_{tag}.ok").write_text(f"{a}-{b} eventos={tabla.num_rows} subidas={subidas}\n")
    return dict(eventos=tabla.num_rows, subidas=subidas, mb=buf.getbuffer().nbytes / 1e6, t_consulta=t1 - t0,
                total=time.time() - t0)


def main():
    SALIDA.mkdir(parents=True, exist_ok=True)
    conn = psycopg2.connect(**CONN)
    conn.set_session(readonly=True, autocommit=True)
    cur = conn.cursor()
    cur.execute(f"set statement_timeout = '{TIMEOUT}'")
    cur.execute("select min(idprogramacion), max(idprogramacion) from progvehiculos")
    lo, hi = cur.fetchone()
    if "--tramo" in sys.argv:
        inicios = [int(sys.argv[sys.argv.index("--tramo") + 1])]
        if inicios[0] % ANCHO:
            sys.exit(f"--tramo debe ser múltiplo de {ANCHO}: si no, sus eventos se repiten con los de la rejilla")
    else:
        inicios = list(range(lo - lo % ANCHO, hi + 1, ANCHO))
    hechos = eventos = 0
    t0 = time.time()
    for i, a in enumerate(inicios, 1):
        try:
            r = procesar_tramo(cur, a, a + ANCHO - 1)
        except psycopg2.Error as exc:
            print(f"tramo {a}: error de la base ({type(exc).__name__}); se reintenta con una conexión nueva", flush=True)
            try:
                conn.close()
            except psycopg2.Error:
                pass
            time.sleep(10)
            conn = psycopg2.connect(**CONN)
            conn.set_session(readonly=True, autocommit=True)
            cur = conn.cursor()
            cur.execute(f"set statement_timeout = '{TIMEOUT}'")
            r = procesar_tramo(cur, a, a + ANCHO - 1)
        if r is None:
            continue
        hechos += 1
        eventos += r["eventos"]
        print(f"[{i}/{len(inicios)}] tramo {a}: {r['eventos']:,} eventos, {r['subidas']:,} subidas, {r['mb']:.1f} MB, "
              f"consulta {r['t_consulta']:.1f} s, total {r['total']:.1f} s; acumulado {eventos:,} en "
              f"{(time.time() - t0) / 60:.1f} min", flush=True)
        time.sleep(PAUSA)
    conn.close()
    print(f"listo: {hechos} tramos nuevos, {eventos:,} eventos")


if __name__ == "__main__":
    main()
