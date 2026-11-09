#!/usr/bin/env bash
# Réplica operacional, paso 30: usuarios técnicos de la IA (§11.3).
#  - lector_ia: solo SELECT sobre public, transacciones de solo lectura por defecto y tiempos máximos.
#  - escritor_ia: dueño del esquema ai_frecuencias; no puede leer ni escribir las tablas de Extreme.
# Las claves llegan por el entorno del contenedor (LECTOR_IA_PASSWORD, ESCRITOR_IA_PASSWORD, desde el .env local)
# y se pasan a psql con -v: no se escriben en ningún archivo.
set -Eeo pipefail

if [ -z "${LECTOR_IA_PASSWORD:-}" ] || [ -z "${ESCRITOR_IA_PASSWORD:-}" ]; then
    echo "replica: defina LECTOR_IA_PASSWORD y ESCRITOR_IA_PASSWORD en el .env" >&2
    exit 1
fi

psql -X -q -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
    -v lector_clave="$LECTOR_IA_PASSWORD" -v escritor_clave="$ESCRITOR_IA_PASSWORD" <<'SQL'
-- PostgreSQL 14 deja crear objetos en public y tablas temporales a cualquier usuario: se cierra para todos y se
-- abre solo a quien lo necesita. extreme_dba (dueño de la base) no se ve afectado.
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
REVOKE CONNECT, TEMPORARY ON DATABASE :"DBNAME" FROM PUBLIC;

-- ---------------------------------------------------------------- lector_ia
CREATE ROLE lector_ia LOGIN PASSWORD :'lector_clave'
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS CONNECTION LIMIT 20;
COMMENT ON ROLE lector_ia IS 'IA de frecuencias: solo lectura de las tablas de Extreme (§11.3)';
GRANT CONNECT ON DATABASE :"DBNAME" TO lector_ia;
GRANT USAGE ON SCHEMA public TO lector_ia;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO lector_ia;
-- las tablas que Extreme cree después también quedan legibles (y solo legibles)
ALTER DEFAULT PRIVILEGES FOR ROLE extreme_dba IN SCHEMA public GRANT SELECT ON TABLES TO lector_ia;
ALTER ROLE lector_ia SET default_transaction_read_only = on;
ALTER ROLE lector_ia SET statement_timeout = '30s';
ALTER ROLE lector_ia SET idle_in_transaction_session_timeout = '60s';
-- nunca hace esperar a la operación de Extreme: si una tabla está bloqueada, la lectura falla rápido (§9.5)
ALTER ROLE lector_ia SET lock_timeout = '5s';
-- las funciones de Extreme que escriben no las puede llamar nadie más que su dueño (PostGIS no se toca)
REVOKE EXECUTE ON FUNCTION public.fn_insert_timbradas_anio(bigint) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.fn_consolidar_timbradas_historicas() FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.fn_segmentar_ruta(bigint, varchar, numeric, numeric, numeric) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.fn_tg_timbrada_segmento() FROM PUBLIC;

-- ---------------------------------------------------------------- escritor_ia
CREATE ROLE escritor_ia LOGIN PASSWORD :'escritor_clave'
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS CONNECTION LIMIT 40;
COMMENT ON ROLE escritor_ia IS 'IA de frecuencias: escribe solo en su esquema ai_frecuencias (§8.1, §11.3)';
-- TEMPORARY: la ingesta de la API puede usar tablas temporales de paso (COPY + INSERT ... ON CONFLICT)
GRANT CONNECT, TEMPORARY ON DATABASE :"DBNAME" TO escritor_ia;
CREATE SCHEMA ai_frecuencias AUTHORIZATION escritor_ia;
COMMENT ON SCHEMA ai_frecuencias IS 'Esquema independiente de la IA de frecuencias (§8.1)';
REVOKE ALL ON SCHEMA ai_frecuencias FROM PUBLIC;
GRANT USAGE ON SCHEMA ai_frecuencias TO lector_ia;
SQL

{
    echo "== Roles creados $(date -Iseconds)"
    psql -X -At --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" -c \
        "SELECT rolname || ' ' || array_to_string(rolconfig, ', ') FROM pg_roles WHERE rolname IN ('lector_ia','escritor_ia') ORDER BY 1"
} >>"$PGDATA/replica_init.log"
