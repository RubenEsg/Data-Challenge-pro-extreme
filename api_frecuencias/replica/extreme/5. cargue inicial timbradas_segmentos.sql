DO $$
DECLARE
    v_prog RECORD;
BEGIN

    FOR v_prog IN
        SELECT DISTINCT pv.idprogramacion, pv.fechainicio, pv.fechafin
        FROM progvehiculos pv
        INNER JOIN rutas r
            ON  pv.idruta = r.idruta
            AND r.proceso = 'cootransoriente'
        WHERE pv.apto_estadisticas_historicas = TRUE
          AND COALESCE(pv.fecha_fin_liquidacion, pv.fechafin) IS NOT NULL
        ORDER BY pv.idprogramacion
    LOOP

        RAISE NOTICE 'Procesando idprogramacion: % | fechainicio: % | fechafin: %',
            v_prog.idprogramacion, v_prog.fechainicio, v_prog.fechafin;

        INSERT INTO timbradas_segmentos (
            id_segmento, id_viaje, fecha,
            hora_inicio, hora_fin,
            subidas, bajadas, pasajeros, ultimaactualizacion
        )
        SELECT
            seg.id,
            cp.idprogramacion,
            pv.fechainicio::DATE,
            bloque.hora_inicio,
            bloque.hora_inicio + interval '15 minutes',
            SUM(cp.cantidad_subida),
            SUM(cp.cantidad_bajada),
            MAX(cp.acumulada_subida - cp.acumulada_bajada),
            CURRENT_TIMESTAMP
        FROM conteo_pasajeros cp
        INNER JOIN progvehiculos pv ON cp.idprogramacion = pv.idprogramacion
        INNER JOIN rutas r ON pv.idruta = r.idruta AND r.proceso = 'cootransoriente'
        CROSS JOIN LATERAL (
            SELECT rs.id
            FROM   rutas_segmentos rs
            WHERE  rs.idruta = r.idruta AND rs.activo = TRUE
            ORDER BY rs.geom_segmento <-> ST_SetSRID(ST_Point(cp.longitud, cp.latitud), 4326)
            LIMIT 1
        ) seg
        CROSS JOIN LATERAL (
            SELECT (
                date_trunc('hour', COALESCE(pv.fecha_fin_liquidacion, pv.fechafin)) +
                floor(date_part('minute', COALESCE(pv.fecha_fin_liquidacion, pv.fechafin)) / 15) * interval '15 minute'
            )::time AS hora_inicio
        ) bloque
        WHERE cp.idprogramacion = v_prog.idprogramacion
          AND COALESCE(pv.fecha_fin_liquidacion, pv.fechafin) IS NOT NULL
        GROUP BY seg.id, cp.idprogramacion, pv.fechainicio::DATE, bloque.hora_inicio
        ON CONFLICT (id_segmento, id_viaje, hora_inicio)
        DO UPDATE SET
            subidas             = EXCLUDED.subidas,
            bajadas             = EXCLUDED.bajadas,
            pasajeros           = EXCLUDED.pasajeros,
            ultimaactualizacion = CURRENT_TIMESTAMP;

    END LOOP;

END;
$$;