"""Genera replica/initdb/10_base_operacional.sql: las tablas que los scripts de Extreme dan por existentes.

Las columnas y tipos salen de los esquemas Parquet de la exportación de la base del reto (datos/*.parquet), con los
ids originales como llave primaria. Las tablas que no vinieron en la exportación (rutasgeograficas, areascontrol y las
de trazabilidad y zonas) se deducen del código de las funciones 3 y 4 de Extreme y quedan marcadas como deducidas.

El archivo generado se guarda en el repositorio; este script solo hace falta para regenerarlo:
    python -m scripts.replica_generar_ddl            (usa REPLICA_DATOS_DIR o ../../datos)
No se conecta a ninguna base de datos.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pyarrow.parquet as pq

RAIZ = Path(__file__).resolve().parents[1]
DATOS = Path(os.environ.get("REPLICA_DATOS_DIR") or RAIZ.parents[1] / "datos")
SALIDA = RAIZ / "replica" / "initdb" / "10_base_operacional.sql"

TIPOS = {"int64": "bigint", "int32": "integer", "string": "text", "large_string": "text",
         "double": "double precision", "bool": "boolean", "timestamp[us]": "timestamp",
         "date32[day]": "date", "time64[us]": "time"}

# (tabla en la base, archivo Parquet, llave primaria, columnas con tipo forzado, extra al final del CREATE TABLE)
TABLAS_EXPORTADAS = [
    ('"Procesos"', "Procesos.parquet", "proceso", {}, ""),
    # rutas.geom viene vacía en la exportación; en la base es geometría. zona_tolerancia_* las lee la función 3 y
    # no vinieron en la exportación: se agregan en NULL (ninguna ruta de Sobusa tiene id_tipo_tarifa = 2).
    ("rutas", "rutas.parquet", "idruta", {"geom": "geometry"}, ""),
    ("dias_semana", "dias_semana.parquet", "id_dia_semana", {}, ""),
    ("estacionalidades", "estacionalidades.parquet", "id_estacionalidad", {}, ""),
    ("estacionalidades_anio", "estacionalidades_anio.parquet", "id_estacionalidad_anio", {}, ""),
    ("progvehiculos", "progvehiculos.parquet", "idprogramacion", {}, ""),
    ("vehiculos", "vehiculos.parquet", "idvehiculo", {}, ""),
    ("novedades_viales", "novedades_viales.parquet", "id_novedad_vial", {}, ""),
    ("novedades_viales_fecha", "novedades_viales_fecha.parquet", "id_novedad_vial_fecha", {}, ""),
    ("novedades_viales_ruta", "novedades_viales_ruta.parquet", "id_novedad_vial_ruta", {}, ""),
    ("timbradas_anio", "timbradas_anio.parquet", "id_timbrada_anio", {}, ""),
    # el ON CONFLICT de fn_consolidar_timbradas_historicas (script 4) exige esta llave única
    ("timbradas_consolidado", "timbradas_consolidado.parquet", "id_timbrada_consolidado", {},
     ",\n    CONSTRAINT uq_timbradas_consolidado_bloque\n"
     "        UNIQUE (proceso, id_ruta, id_dia_semana, id_estacionalidad, hora, hora_inicio, hora_fin)"),
    # conteo_pasajeros: en el reto se llama conteo_pasajeros_destino; mismas 25 columnas (muestra real)
    ("conteo_pasajeros", "muestra_conteo_pasajeros_20230207_r2_r21.parquet", "id", {}, ""),
]

COLUMNAS_EXTRA = {"rutas": ["zona_tolerancia_inicio integer", "zona_tolerancia_fin integer"]}

# llaves que las funciones de Extreme insertan sin id (RETURNING id_...): secuencia como en un serial
SECUENCIAS = [("timbradas_anio", "id_timbrada_anio"), ("timbradas_consolidado", "id_timbrada_consolidado"),
              ("conteo_pasajeros", "id")]

DEDUCIDAS = """
-- ---------------------------------------------------------------------------------------------------------------
-- Tablas existentes en la base de Extreme que NO vinieron en la exportación. DDL DEDUCIDO del código de las
-- funciones 3 (fn_insert_timbradas_anio) y 4 (fn_consolidar_timbradas_historicas). Hallazgo H5: confirmar con Extreme.
-- ---------------------------------------------------------------------------------------------------------------
CREATE TABLE public.rutasgeograficas (
    idruta integer PRIMARY KEY,
    geom   geometry(LineString, 4326)
);

CREATE TABLE public.areascontrol (
    idarea integer PRIMARY KEY,
    geom   geometry(Polygon, 4326)
);

CREATE TABLE public.timbradas_anio_trazabilidad (
    id_timbrada_anio_trazabilidad bigserial PRIMARY KEY,
    id_timbrada_anio              bigint  NOT NULL REFERENCES public.timbradas_anio (id_timbrada_anio),
    idprogramacion                bigint  NOT NULL,
    subidas                       integer NOT NULL DEFAULT 0,
    bajadas                       integer NOT NULL DEFAULT 0,
    vigente                       boolean NOT NULL DEFAULT true
);

CREATE TABLE public.timbradas_anio_zonas (
    id_timbrada_anio_zona bigserial PRIMARY KEY,
    id_timbrada_anio      bigint NOT NULL REFERENCES public.timbradas_anio (id_timbrada_anio),
    id_zona_tarifa        bigint NOT NULL,
    subidas               integer,
    bajadas               integer,
    nro_viajes            integer,
    promedio_subidas      numeric(10, 2),
    promedio_bajadas      numeric(10, 2),
    ultima_actualizacion  timestamp
);

CREATE TABLE public.timbradas_anio_zonas_trazabilidad (
    id_trazabilidad       bigserial PRIMARY KEY,
    id_timbrada_anio_zona bigint  NOT NULL REFERENCES public.timbradas_anio_zonas (id_timbrada_anio_zona),
    idprogramacion        bigint  NOT NULL,
    subidas               integer NOT NULL DEFAULT 0,
    bajadas               integer NOT NULL DEFAULT 0,
    vigente               boolean NOT NULL DEFAULT true
);

CREATE TABLE public.timbradas_consolidado_zonas (
    id_timbrada_consolidado_zona bigserial PRIMARY KEY,
    id_timbrada_consolidado      bigint NOT NULL REFERENCES public.timbradas_consolidado (id_timbrada_consolidado),
    id_zona_tarifa               bigint NOT NULL,
    subidas                      integer,
    bajadas                      integer,
    nro_viajes                   integer,
    promedio_subidas             numeric(10, 2),
    promedio_bajadas             numeric(10, 2),
    ultima_actualizacion         timestamp,
    CONSTRAINT uq_timbradas_consolidado_zonas UNIQUE (id_timbrada_consolidado, id_zona_tarifa)
);
"""


def _columnas(archivo: str, forzados: dict[str, str]) -> list[str]:
    esquema = pq.read_schema(DATOS / archivo)
    salida = []
    for campo in esquema:
        tipo = forzados.get(campo.name) or TIPOS[str(campo.type)]
        salida.append(f'    "{campo.name}" {tipo}')
    return salida


def generar() -> str:
    partes = [
        "-- GENERADO por scripts/replica_generar_ddl.py desde los esquemas Parquet exportados. No editar a mano.",
        "-- Tablas que los scripts de Extreme (replica/extreme) dan por existentes; ids originales como PK.",
        "-- Lo ejecuta el entrypoint de postgres al crear el volumen, antes de 20_scripts_extreme.sh.",
        "\\set ON_ERROR_STOP on",
        "SET client_min_messages = warning;",
        "",
    ]
    for tabla, archivo, pk, forzados, extra in TABLAS_EXPORTADAS:
        nombre = tabla.strip('"')
        cols = _columnas(archivo, forzados) + [f"    {c}" for c in COLUMNAS_EXTRA.get(nombre, [])]
        partes.append(f"-- {archivo}")
        partes.append(f"CREATE TABLE public.{tabla} (\n" + ",\n".join(cols)
                      + f",\n    PRIMARY KEY ({pk}){extra}\n);")
        partes.append("")
    partes.append("CREATE INDEX ix_conteo_pasajeros_idprogramacion ON public.conteo_pasajeros (idprogramacion);")
    partes.append("")
    for tabla, col in SECUENCIAS:
        seq = f"{tabla}_{col}_seq"
        partes.append(f"CREATE SEQUENCE public.{seq} OWNED BY public.{tabla}.{col};")
        partes.append(f"ALTER TABLE public.{tabla} ALTER COLUMN {col} SET DEFAULT nextval('public.{seq}');")
    partes.append(DEDUCIDAS)
    return "\n".join(partes) + "\n"


def main() -> int:
    sql = generar()
    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    SALIDA.write_bytes(sql.encode("utf-8"))
    print(f"escrito {SALIDA.relative_to(RAIZ)} ({len(sql.splitlines())} líneas)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
