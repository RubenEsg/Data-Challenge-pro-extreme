-- =====================================================================
-- FUNCIÓN COMPLETA
-- =====================================================================
CREATE OR REPLACE FUNCTION public.fn_consolidar_timbradas_historicas()
 RETURNS boolean
 LANGUAGE plpgsql
AS $function$

DECLARE
    v_anio_limite int;
    v_fecha_limite date;

BEGIN

    /*
        Determina el ultimo año cerrado
        Ejemplo: hoy 2026 → toma hasta 2025
    */
    v_anio_limite  := EXTRACT(YEAR FROM CURRENT_DATE)::int - 1;
    v_fecha_limite := make_date(v_anio_limite, 12, 31);

    RAISE NOTICE 'Consolidando información hasta %', v_anio_limite;
    RAISE NOTICE 'Consolidando información hasta %', v_fecha_limite;


    -- =====================================================================
    -- CONSOLIDADO PRINCIPAL
    -- =====================================================================
    WITH base AS (
        SELECT
            ta.proceso,
            ta.id_ruta,
            ta.id_dia_semana,
            ea.id_estacionalidad,
            ta.hora,
            ta.hora_inicio,
            ta.hora_fin,
            SUM(ta.subidas)    AS subidas,
            SUM(ta.bajadas)    AS bajadas,
            SUM(ta.nro_viajes) AS nro_viajes,
            CEIL(SUM(ta.subidas)::numeric / NULLIF(SUM(ta.nro_viajes), 0)) AS promedio_subidas,
            CEIL(SUM(ta.bajadas)::numeric / NULLIF(SUM(ta.nro_viajes), 0)) AS promedio_bajadas
        FROM timbradas_anio ta
        INNER JOIN estacionalidades_anio ea
            ON ta.id_estacionalidad_anio = ea.id_estacionalidad_anio
        WHERE ta.ano <= v_anio_limite
        GROUP BY
            ta.proceso,
            ta.id_ruta,
            ta.id_dia_semana,
            ea.id_estacionalidad,
            ta.hora,
            ta.hora_inicio,
            ta.hora_fin
    )
    INSERT INTO timbradas_consolidado (
        proceso, id_ruta, id_dia_semana, id_estacionalidad,
        hora, hora_inicio, hora_fin,
        subidas, bajadas, nro_viajes,
        promedio_subidas, promedio_bajadas,
        ultima_actualizacion
    )
    SELECT
        proceso, id_ruta, id_dia_semana, id_estacionalidad,
        hora, hora_inicio, hora_fin,
        subidas, bajadas, nro_viajes,
        promedio_subidas, promedio_bajadas,
        CURRENT_TIMESTAMP
    FROM base
    ON CONFLICT (proceso, id_ruta, id_dia_semana, id_estacionalidad, hora, hora_inicio, hora_fin)
    DO UPDATE SET
        subidas              = EXCLUDED.subidas,
        bajadas              = EXCLUDED.bajadas,
        nro_viajes           = EXCLUDED.nro_viajes,
        promedio_subidas     = EXCLUDED.promedio_subidas,
        promedio_bajadas     = EXCLUDED.promedio_bajadas,
        ultima_actualizacion = CURRENT_TIMESTAMP;


    -- =====================================================================
    -- CONSOLIDADO POR ZONA
    -- =====================================================================
    WITH base_zonas AS (
        SELECT
            ta.proceso,
            ta.id_ruta,
            ta.id_dia_semana,
            ea.id_estacionalidad,
            ta.hora,
            ta.hora_inicio,
            ta.hora_fin,
            taz.id_zona_tarifa,
            SUM(taz.subidas)    AS subidas,
            SUM(taz.bajadas)    AS bajadas,
            SUM(taz.nro_viajes) AS nro_viajes,
            CEIL(SUM(taz.subidas)::numeric / NULLIF(SUM(taz.nro_viajes), 0)) AS promedio_subidas,
            CEIL(SUM(taz.bajadas)::numeric / NULLIF(SUM(taz.nro_viajes), 0)) AS promedio_bajadas
        FROM timbradas_anio ta
        INNER JOIN timbradas_anio_zonas taz
            ON ta.id_timbrada_anio = taz.id_timbrada_anio
        INNER JOIN estacionalidades_anio ea
            ON ta.id_estacionalidad_anio = ea.id_estacionalidad_anio
        WHERE ta.ano <= v_anio_limite
        GROUP BY
            ta.proceso,
            ta.id_ruta,
            ta.id_dia_semana,
            ea.id_estacionalidad,
            ta.hora,
            ta.hora_inicio,
            ta.hora_fin,
            taz.id_zona_tarifa
    ),
    datos_finales AS (
        SELECT
            tc.id_timbrada_consolidado,
            bz.id_zona_tarifa,
            bz.subidas,
            bz.bajadas,
            bz.nro_viajes,
            bz.promedio_subidas,
            bz.promedio_bajadas
        FROM base_zonas bz
        INNER JOIN timbradas_consolidado tc
            ON  tc.proceso           = bz.proceso
            AND tc.id_ruta           = bz.id_ruta
            AND tc.id_dia_semana     = bz.id_dia_semana
            AND tc.id_estacionalidad = bz.id_estacionalidad
            AND tc.hora              = bz.hora
            AND tc.hora_inicio       = bz.hora_inicio
            AND tc.hora_fin          = bz.hora_fin
    )
    INSERT INTO timbradas_consolidado_zonas (
        id_timbrada_consolidado, id_zona_tarifa,
        subidas, bajadas, nro_viajes,
        promedio_subidas, promedio_bajadas,
        ultima_actualizacion
    )
    SELECT
        id_timbrada_consolidado, id_zona_tarifa,
        subidas, bajadas, nro_viajes,
        promedio_subidas, promedio_bajadas,
        CURRENT_TIMESTAMP
    FROM datos_finales
    ON CONFLICT (id_timbrada_consolidado, id_zona_tarifa)
    DO UPDATE SET
        subidas              = EXCLUDED.subidas,
        bajadas              = EXCLUDED.bajadas,
        nro_viajes           = EXCLUDED.nro_viajes,
        promedio_subidas     = EXCLUDED.promedio_subidas,
        promedio_bajadas     = EXCLUDED.promedio_bajadas,
        ultima_actualizacion = CURRENT_TIMESTAMP;


    -- =====================================================================
    -- CONSOLIDADO POR SEGMENTO
    --   Fuente: timbradas_segmentos_anio
    --   Colapsa todos los años cerrados en un único registro por
    --   (id_segmento, proceso, id_dia_semana, id_estacionalidad, bloque)
    --   mapeando id_estacionalidad_anio → id_estacionalidad via JOIN
    -- =====================================================================
    WITH base_segmentos AS (
        SELECT
            tsa.id_segmento,
            tsa.proceso,
            tsa.id_ruta,
            tsa.id_dia_semana,
            ea.id_estacionalidad,
            tsa.hora,
            tsa.hora_inicio,
            tsa.hora_fin,
            SUM(tsa.subidas)    AS subidas,
            SUM(tsa.bajadas)    AS bajadas,
            SUM(tsa.pasajeros)  AS pasajeros,
            SUM(tsa.nro_viajes) AS nro_viajes,
            CEIL(SUM(tsa.subidas)::numeric   / NULLIF(SUM(tsa.nro_viajes), 0)) AS promedio_subidas,
            CEIL(SUM(tsa.bajadas)::numeric   / NULLIF(SUM(tsa.nro_viajes), 0)) AS promedio_bajadas,
            CEIL(SUM(tsa.pasajeros)::numeric / NULLIF(SUM(tsa.nro_viajes), 0)) AS promedio_pasajeros
        FROM timbradas_segmentos_anio tsa
        INNER JOIN estacionalidades_anio ea
            ON tsa.id_estacionalidad_anio = ea.id_estacionalidad_anio
        WHERE tsa.ano <= v_anio_limite
        GROUP BY
            tsa.id_segmento,
            tsa.proceso,
            tsa.id_ruta,
            tsa.id_dia_semana,
            ea.id_estacionalidad,
            tsa.hora,
            tsa.hora_inicio,
            tsa.hora_fin
    )
    INSERT INTO timbradas_segmentos_consolidado (
        id_segmento, proceso, id_ruta, id_dia_semana, id_estacionalidad,
        hora, hora_inicio, hora_fin,
        subidas, bajadas, pasajeros, nro_viajes,
        promedio_subidas, promedio_bajadas, promedio_pasajeros,
        ultima_actualizacion
    )
    SELECT
        id_segmento, proceso, id_ruta, id_dia_semana, id_estacionalidad,
        hora, hora_inicio, hora_fin,
        subidas, bajadas, pasajeros, nro_viajes,
        promedio_subidas, promedio_bajadas, promedio_pasajeros,
        CURRENT_TIMESTAMP
    FROM base_segmentos
    ON CONFLICT (id_segmento, proceso, id_dia_semana, id_estacionalidad, hora, hora_inicio, hora_fin)
    DO UPDATE SET
        subidas            = EXCLUDED.subidas,
        bajadas            = EXCLUDED.bajadas,
        pasajeros          = EXCLUDED.pasajeros,
        nro_viajes         = EXCLUDED.nro_viajes,
        promedio_subidas   = EXCLUDED.promedio_subidas,
        promedio_bajadas   = EXCLUDED.promedio_bajadas,
        promedio_pasajeros = EXCLUDED.promedio_pasajeros,
        ultima_actualizacion = CURRENT_TIMESTAMP;


    RAISE NOTICE 'Consolidación finalizada correctamente';
    RETURN TRUE;

END;
$function$;