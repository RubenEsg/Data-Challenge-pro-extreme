#!/usr/bin/env bash
# Réplica operacional, paso 20: ejecuta los scripts de Extreme SIN MODIFICAR, en el orden de su numeración.
#  - Los scripts están en /extreme, copiados byte a byte; antes de nada se verifican contra SHA256SUMS.
#  - Las correcciones son archivos aparte en /errata (E1 antes del script 1, E2 después) y se pueden desactivar
#    con REPLICA_ERRATA_E1=0 / REPLICA_ERRATA_E2=0 al crear el volumen.
#  - Cada paso queda en replica_meta.paso (archivo, sha256, errores y errores esperados, salida de psql) y en
#    $PGDATA/replica_init.log. Si un paso deja un número de errores distinto del esperado, la inicialización se
#    detiene (el contenedor no arranca a medias).
# Lo ejecuta el entrypoint de postgres al crear el volumen (lo carga con «source» o lo ejecuta; sirve de las dos formas).
set -Eeo pipefail

REP_LOG="$PGDATA/replica_init.log"
REP_PSQL=(psql -X --username "$POSTGRES_USER" --dbname "$POSTGRES_DB")
REP_E1="${REPLICA_ERRATA_E1:-1}"
REP_E2="${REPLICA_ERRATA_E2:-1}"

rep_sha() { sha256sum "$1" | cut -d' ' -f1; }

rep_registrar() {  # paso archivo errores esperados nota inicio archivo_salida
    "${REP_PSQL[@]}" -q -v ON_ERROR_STOP=1 \
        -v paso="$1" -v archivo="$2" -v sha="$(rep_sha "$2")" -v errores="$3" -v esperados="$4" \
        -v nota="$5" -v inicio="$6" -v salida="$(cat "$7")" <<'SQL'
INSERT INTO replica_meta.paso (paso, archivo, sha256, errores, errores_esperados, nota, inicio, salida)
VALUES (:'paso', :'archivo', :'sha', :'errores'::int, :'esperados'::int, :'nota', :'inicio'::timestamptz, :'salida');
SQL
}

rep_ejecutar() {  # paso archivo on_error_stop errores_esperados nota
    local paso="$1" archivo="$2" stop="$3" esperados="$4" nota="$5"
    local salida inicio rc=0 errores
    salida="$(mktemp)"
    inicio="$(date -Iseconds)"
    "${REP_PSQL[@]}" -v ON_ERROR_STOP="$stop" -f "$archivo" >"$salida" 2>&1 || rc=$?
    errores="$(grep -c 'ERROR:' "$salida" || true)"
    {
        echo "== [$paso] $archivo"
        echo "   sha256=$(rep_sha "$archivo")  ON_ERROR_STOP=$stop  errores=$errores (esperados $esperados)  rc=$rc"
        echo "   $nota"
        sed 's/^/   | /' "$salida"
    } >>"$REP_LOG"
    rep_registrar "$paso" "$archivo" "$errores" "$esperados" "$nota" "$inicio" "$salida"
    rm -f "$salida"
    if [ "$rc" -ne 0 ] || [ "$errores" -ne "$esperados" ]; then
        echo "replica: el paso $paso dejó $errores errores (esperados $esperados, rc=$rc); ver $REP_LOG" >&2
        exit 1
    fi
}

{
    echo "== Réplica operacional de Extreme: inicialización $(date -Iseconds)"
    "${REP_PSQL[@]}" -At -c "SELECT version()" -c "SELECT postgis_full_version()" -c "SHOW timezone"
    echo "== Verificación de los scripts de Extreme contra SHA256SUMS (copia byte a byte)"
} >>"$REP_LOG"
if ! (cd /extreme && sha256sum -c SHA256SUMS) >>"$REP_LOG" 2>&1; then
    echo "replica: los scripts de /extreme no coinciden con SHA256SUMS" >&2
    exit 1
fi

if [ "$REP_E1" != "0" ]; then
    rep_ejecutar "E1" "/errata/E1_rutas_segmentos_config.sql" 1 0 \
        "Errata E1: rutas_segmentos_config como en la base real (con activo), antes del script 1."
    rep_ejecutar "1" "/extreme/1. tablas.sql" 0 1 \
        "Script 1 tal cual: 1 error esperado (sintaxis, línea 38: el «;» de la línea 31); crea las otras 6 tablas."
else
    rep_ejecutar "1" "/extreme/1. tablas.sql" 0 6 \
        "Script 1 tal cual SIN E1: 1 error de sintaxis y 5 en cascada (REPLICA_ERRATA_E1=0)."
fi

if [ "$REP_E2" != "0" ]; then
    rep_ejecutar "E2" "/errata/E2_unique_timbradas_segmentos.sql" 1 0 \
        "Errata E2: llave única (id_segmento, id_viaje, hora_inicio) que usan el script 5 y el trigger."
fi

rep_ejecutar "2" "/extreme/2. funcion para segmentar ruta.sql" 1 0 "Script 2 tal cual: fn_segmentar_ruta."
rep_ejecutar "3" "/extreme/3. fn_insert_timbradas_anio.sql" 1 0 "Script 3 tal cual: fn_insert_timbradas_anio."
rep_ejecutar "4" "/extreme/4. fn_consolidar_timbradas_historicas.sql" 1 0 \
    "Script 4 tal cual: fn_consolidar_timbradas_historicas."
rep_ejecutar "7" "/extreme/7. trigger de conteo.sql" 1 0 \
    "Script 7 tal cual: fn_tg_timbrada_segmento y el trigger tg_timbrada_segmento sobre conteo_pasajeros."
# 99, 5 y 6 filtran proceso = 'cootransoriente'; con la base aún vacía no procesan nada. scripts/replica_cargar.py los
# vuelve a ejecutar tal cual sobre la réplica cargada para dejar constancia de que tampoco procesan datos de 'sobusa'.
rep_ejecutar "99" "/extreme/99. prueba de segmentacion.sql" 1 0 \
    "Script 99 tal cual (bloque DO; filtra proceso = 'cootransoriente')."
rep_ejecutar "5" "/extreme/5. cargue inicial timbradas_segmentos.sql" 1 0 \
    "Script 5 tal cual (bloque DO; filtra proceso = 'cootransoriente')."
rep_ejecutar "6" "/extreme/6. cargue inicial timbradas_segmentos_anio.sql" 1 0 \
    "Script 6 tal cual (bloque DO; filtra proceso = 'cootransoriente')."

echo "== Scripts de Extreme listos $(date -Iseconds)" >>"$REP_LOG"
