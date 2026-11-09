-- Réplica operacional de Extreme (servicio «operacional», perfil compose «integracion»).
-- Paso 00: extensiones, zona horaria de la base y el esquema propio de la réplica (replica_meta, nunca public).
-- Este montaje reemplaza el 10_postgis.sh de la imagen postgis/postgis, así que PostGIS se crea aquí.
\set ON_ERROR_STOP on
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
-- las marcas de Extreme son timestamp SIN zona llenadas con CURRENT_TIMESTAMP/NOW(): se fija la zona de Bogotá (H10)
ALTER DATABASE :"DBNAME" SET timezone = 'America/Bogota';

CREATE SCHEMA replica_meta;
COMMENT ON SCHEMA replica_meta IS 'Metadatos de la réplica (pasos de inicialización, carga, viajes reservados). No existe en la base de Extreme.';

CREATE TABLE replica_meta.paso (
    n                 serial PRIMARY KEY,
    paso              text        NOT NULL,
    archivo           text        NOT NULL,
    sha256            text,
    errores           integer     NOT NULL,
    errores_esperados integer     NOT NULL,
    nota              text,
    inicio            timestamptz NOT NULL,
    fin               timestamptz NOT NULL DEFAULT clock_timestamp(),
    salida            text
);

CREATE TABLE replica_meta.carga (
    tabla             text PRIMARY KEY,
    filas             bigint      NOT NULL,
    filas_exportadas  bigint,
    excluidas         bigint      NOT NULL DEFAULT 0,
    segundos          numeric(10, 2),
    cargada_en        timestamptz NOT NULL DEFAULT clock_timestamp(),
    nota              text
);

-- viajes de la muestra real (rutas 2 y 21, 2023-02-07) que NO se cargan en timbradas_segmentos: los usa el
-- simulador de llegada de datos (P5) para insertarlos por el trigger de Extreme
CREATE TABLE replica_meta.viajes_reservados (
    idprogramacion bigint PRIMARY KEY,
    idruta         bigint,
    filas_crudas   integer NOT NULL,
    filas_timbradas_segmentos_excluidas integer NOT NULL DEFAULT 0
);
