
CREATE OR REPLACE FUNCTION fn_segmentar_ruta(
    p_idruta               BIGINT,
    p_tipo_agrupacion      VARCHAR(20),
    p_valor                NUMERIC,
    p_tamaño_porcion_m     NUMERIC DEFAULT 0.20,
    p_tamaño_minimo_m      NUMERIC DEFAULT 0.20
)
RETURNS VOID
LANGUAGE plpgsql
AS $$
DECLARE
    v_idrutageo_actual    INTEGER;
    v_geom                GEOMETRY;
    v_longitud_m          NUMERIC;
    v_n_completos         INTEGER;
    v_id_config           BIGINT;
    v_id_config_geo_prev  BIGINT;
    v_tamaño_porcion_prev NUMERIC;
    v_total_porciones     INTEGER;
    v_regenerar_porciones BOOLEAN := FALSE;
BEGIN
    -- ------------------------------------------------
    -- 1. Obtener geometría actual de la ruta
    -- ------------------------------------------------
    SELECT a.idrutageo, b.geom, ST_Length(b.geom::geography)
    INTO   v_idrutageo_actual, v_geom, v_longitud_m
    FROM   rutas a
    INNER JOIN rutasgeograficas b ON a.idrutageo = b.idruta
    WHERE  a.idruta = p_idruta;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Ruta % no encontrada o sin geometría asociada', p_idruta;
    END IF;

    -- ------------------------------------------------
    -- 2. Validaciones
    -- ------------------------------------------------
    IF p_tipo_agrupacion NOT IN ('distancia', 'cantidad') THEN
        RAISE EXCEPTION 'tipo_agrupacion debe ser "distancia" o "cantidad"';
    END IF;

    IF p_valor IS NULL OR p_valor <= 0 THEN
        RAISE EXCEPTION 'p_valor debe ser mayor a cero';
    END IF;

    IF p_tipo_agrupacion = 'cantidad' AND p_valor != FLOOR(p_valor) THEN
        RAISE EXCEPTION 'Cuando tipo_agrupacion es "cantidad", p_valor debe ser un entero';
    END IF;

    IF p_tamaño_porcion_m <= 0 OR p_tamaño_minimo_m <= 0 THEN
        RAISE EXCEPTION 'tamaño_porcion_m y tamaño_minimo_porcion_m deben ser mayores a cero';
    END IF;

    IF p_tamaño_porcion_m < p_tamaño_minimo_m THEN
        RAISE EXCEPTION 'tamaño_porcion_m (%) no puede ser menor al mínimo aceptable (%)',
            p_tamaño_porcion_m, p_tamaño_minimo_m;
    END IF;

    IF p_tamaño_porcion_m >= v_longitud_m THEN
        RAISE EXCEPTION 'tamaño_porcion_m (%) supera o iguala la longitud de la ruta (% m)',
            p_tamaño_porcion_m, ROUND(v_longitud_m::NUMERIC, 3);
    END IF;

    IF p_tipo_agrupacion = 'distancia' THEN
        IF p_tamaño_porcion_m > p_valor THEN
            RAISE EXCEPTION 'tamaño_porcion_m (%) no puede ser mayor al tamaño del segmento (% m)',
                p_tamaño_porcion_m, p_valor;
        END IF;
        IF p_valor > v_longitud_m THEN
            RAISE EXCEPTION 'Tamaño de segmento (% m) supera la longitud de la ruta (% m)',
                p_valor, ROUND(v_longitud_m::NUMERIC, 3);
        END IF;
    ELSIF p_tipo_agrupacion = 'cantidad' THEN
        IF FLOOR(v_longitud_m / p_tamaño_porcion_m) < p_valor THEN
            RAISE EXCEPTION 'Con porciones de % m la ruta genera % porciones, insuficientes para % segmentos',
                p_tamaño_porcion_m,
                FLOOR(v_longitud_m / p_tamaño_porcion_m)::INTEGER,
                p_valor::INTEGER;
        END IF;
        IF (v_longitud_m / p_valor) < p_tamaño_minimo_m THEN
            RAISE EXCEPTION 'Con % segmentos cada uno mediría % m, por debajo del mínimo (% m)',
                p_valor::INTEGER,
                ROUND((v_longitud_m / p_valor)::NUMERIC, 3),
                p_tamaño_minimo_m;
        END IF;
    END IF;

    -- ------------------------------------------------
    -- 3. Detectar cambio de ruta geográfica
    --    Si existe un config ACTIVO con diferente idrutageo
    --    → desactivar config anterior y sus segmentos (preservar historial)
    --    → forzar regeneración de porciones
    -- ------------------------------------------------
    SELECT id
    INTO   v_id_config_geo_prev
    FROM   rutas_segmentos_config
    WHERE  idruta    = p_idruta
      AND  idrutageo != v_idrutageo_actual
      AND  activo    = TRUE;

    IF FOUND THEN
        UPDATE rutas_segmentos_config
           SET activo = FALSE
         WHERE id = v_id_config_geo_prev;

        UPDATE rutas_segmentos
           SET activo = FALSE
         WHERE id_config = v_id_config_geo_prev;

        v_regenerar_porciones := TRUE;

        RAISE NOTICE 'Ruta %: cambio de ruta geográfica detectado. Config % desactivada, se crea nueva segmentación.',
            p_idruta, v_id_config_geo_prev;
    END IF;

    -- ------------------------------------------------
    -- 4. Detectar cambio de tamaño de porción
    --    Si existe config activa para el mismo idrutageo
    --    pero con tamaño_porcion_m diferente
    --    → borrar porciones y regenerar
    -- ------------------------------------------------
    IF NOT v_regenerar_porciones THEN
        SELECT tamaño_porcion_m
        INTO   v_tamaño_porcion_prev
        FROM   rutas_segmentos_config
        WHERE  idruta    = p_idruta
          AND  idrutageo = v_idrutageo_actual
          AND  activo    = TRUE;

        IF FOUND AND v_tamaño_porcion_prev IS DISTINCT FROM p_tamaño_porcion_m THEN
            v_regenerar_porciones := TRUE;
            RAISE NOTICE 'Ruta %: tamaño de porción cambió (% m → % m). Porciones regeneradas.',
                p_idruta, v_tamaño_porcion_prev, p_tamaño_porcion_m;
        END IF;
    END IF;

    IF v_regenerar_porciones THEN
        DELETE FROM rutas_segmentos_porcion
        WHERE  idruta    = p_idruta
          AND  idrutageo = v_idrutageo_actual;
    END IF;

    -- ------------------------------------------------
    -- 5. Llenar rutas_segmentos_porcion
    --    DO NOTHING si ya existen con el mismo tamaño
    -- ------------------------------------------------
    v_n_completos := FLOOR(v_longitud_m / p_tamaño_porcion_m)::INTEGER;

    INSERT INTO rutas_segmentos_porcion (
        idruta, idrutageo, nro_porcion,
        inicio_m, fin_m, longitud_porcion_m,
        punto_inicio, punto_fin, geom_porcion
    )
    WITH series AS (
        SELECT generate_series(0, v_n_completos) AS i
    ),
    porciones AS (
        SELECT
            i,
            ST_LineSubstring(
                v_geom,
                (i * p_tamaño_porcion_m) / v_longitud_m,
                LEAST((i + 1) * p_tamaño_porcion_m / v_longitud_m, 1.0)
            ) AS geom_porcion
        FROM series
        WHERE i * p_tamaño_porcion_m < v_longitud_m
    )
    SELECT
        p_idruta,
        v_idrutageo_actual,
        i + 1,
        ROUND((i * p_tamaño_porcion_m)::NUMERIC, 4),
        ROUND(LEAST((i + 1) * p_tamaño_porcion_m, v_longitud_m)::NUMERIC, 4),
        ROUND((LEAST((i + 1) * p_tamaño_porcion_m, v_longitud_m)
               - i * p_tamaño_porcion_m)::NUMERIC, 4),
        ST_StartPoint(geom_porcion),
        ST_EndPoint(geom_porcion),
        geom_porcion
    FROM porciones
    ON CONFLICT (idruta, idrutageo, nro_porcion) DO NOTHING;

    -- ------------------------------------------------
    -- 6. Upsert configuración
    -- ------------------------------------------------
    INSERT INTO rutas_segmentos_config (
        idruta, idrutageo, tipo_agrupacion,
        tamaño_segmento_m, numero_segmentos,
        tamaño_porcion_m, tamaño_minimo_porcion_m,
        activo
    )
    VALUES (
        p_idruta,
        v_idrutageo_actual,
        p_tipo_agrupacion,
        CASE WHEN p_tipo_agrupacion = 'distancia' THEN p_valor        ELSE NULL END,
        CASE WHEN p_tipo_agrupacion = 'cantidad'  THEN p_valor::INTEGER ELSE NULL END,
        p_tamaño_porcion_m,
        p_tamaño_minimo_m,
        TRUE
    )
    ON CONFLICT (idruta, idrutageo) DO UPDATE
        SET tipo_agrupacion         = EXCLUDED.tipo_agrupacion,
            tamaño_segmento_m       = EXCLUDED.tamaño_segmento_m,
            numero_segmentos        = EXCLUDED.numero_segmentos,
            tamaño_porcion_m        = EXCLUDED.tamaño_porcion_m,
            tamaño_minimo_porcion_m = EXCLUDED.tamaño_minimo_porcion_m,
            activo                  = TRUE,
            fecha_creacion          = NOW()
    RETURNING id INTO v_id_config;

    -- ------------------------------------------------
    -- 7. Total de porciones vigentes
    -- ------------------------------------------------
    SELECT COUNT(*)
    INTO   v_total_porciones
    FROM   rutas_segmentos_porcion
    WHERE  idruta    = p_idruta
      AND  idrutageo = v_idrutageo_actual;

    -- ------------------------------------------------
    -- 8. Recalcular segmentos (siempre)
    -- ------------------------------------------------
    DELETE FROM rutas_segmentos WHERE id_config = v_id_config;

    INSERT INTO rutas_segmentos (
        id_config, idruta, idrutageo,
        nro_segmento, activo,
        porciones_ids, longitud_m, geom_segmento
    )
    WITH porciones_clasificadas AS (
        SELECT
            id,
            nro_porcion,
            longitud_porcion_m,
            geom_porcion,
            CASE p_tipo_agrupacion
                WHEN 'distancia' THEN
                    FLOOR(inicio_m / p_valor)::INTEGER + 1
                WHEN 'cantidad' THEN
                    CEIL(nro_porcion::FLOAT
                         / (v_total_porciones::FLOAT / p_valor::FLOAT))::INTEGER
            END AS nro_segmento
        FROM rutas_segmentos_porcion
        WHERE idruta    = p_idruta
          AND idrutageo = v_idrutageo_actual
    )
    SELECT
        v_id_config,
        p_idruta,
        v_idrutageo_actual,
        nro_segmento,
        TRUE,
        '[' || STRING_AGG(id::TEXT, ',' ORDER BY nro_porcion) || ']',
        ROUND(SUM(longitud_porcion_m)::NUMERIC, 3),
        ST_LineMerge(ST_Collect(array_agg(geom_porcion ORDER BY nro_porcion)))
    FROM porciones_clasificadas
    GROUP BY nro_segmento
    ORDER BY nro_segmento;

    RAISE NOTICE 'Ruta % | longitud: % m | porción: % m | % porciones → % segmentos por %',
        p_idruta,
        ROUND(v_longitud_m::NUMERIC, 2),
        p_tamaño_porcion_m,
        v_total_porciones,
        (SELECT COUNT(*) FROM rutas_segmentos WHERE id_config = v_id_config),
        p_tipo_agrupacion;

END;
$$;
