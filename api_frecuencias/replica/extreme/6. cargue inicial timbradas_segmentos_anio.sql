DO $$
DECLARE
    v_prog RECORD;
BEGIN

    FOR v_prog IN
        SELECT DISTINCT ts.id_viaje AS idprogramacion, pv.fechainicio, pv.fechafin
        FROM timbradas_segmentos ts
        INNER JOIN progvehiculos pv ON ts.id_viaje = pv.idprogramacion
        INNER JOIN rutas r ON pv.idruta = r.idruta AND r.proceso = 'cootransoriente'
        ORDER BY ts.id_viaje
    LOOP

        RAISE NOTICE 'Procesando idprogramacion: % | fechainicio: % | fechafin: %',
            v_prog.idprogramacion, v_prog.fechainicio, v_prog.fechafin;

        WITH dim AS (
            SELECT DISTINCT ON (pv.idprogramacion)
                pv.idprogramacion,
                pv.idruta,
                r.proceso,
                EXTRACT(YEAR   FROM COALESCE(pv.fecha_fin_liquidacion, pv.fechafin))::INT AS ano,
                EXTRACT(ISODOW FROM COALESCE(pv.fecha_fin_liquidacion, pv.fechafin))::INT AS id_dia_semana,
                ea.id_estacionalidad_anio
            FROM progvehiculos pv
            INNER JOIN rutas r
                ON  pv.idruta = r.idruta
                AND r.proceso = 'cootransoriente'
            INNER JOIN estacionalidades_anio ea
                ON  ea.proceso      = r.proceso
                AND ea.fecha_inicio <= COALESCE(pv.fecha_fin_liquidacion, pv.fechafin)
                AND ea.fecha_fin + INTERVAL '1 day' > COALESCE(pv.fecha_fin_liquidacion, pv.fechafin)
            WHERE pv.idprogramacion = v_prog.idprogramacion
            ORDER BY
                pv.idprogramacion,
                (ea.fecha_fin - ea.fecha_inicio) ASC,
                ea.fecha_inicio DESC,
                ea.id_estacionalidad_anio DESC
        )
        INSERT INTO timbradas_segmentos_anio (
            id_segmento, proceso, ano, id_ruta, id_dia_semana,
            id_estacionalidad_anio, hora, hora_inicio, hora_fin,
            subidas, bajadas, pasajeros, nro_viajes,
            promedio_subidas, promedio_bajadas, promedio_pasajeros,
            ultima_actualizacion
        )
        SELECT
            ts.id_segmento,
            d.proceso, d.ano, d.idruta, d.id_dia_semana, d.id_estacionalidad_anio,
            ts.hora_inicio, ts.hora_inicio, ts.hora_fin,
            SUM(ts.subidas),
            SUM(ts.bajadas),
            SUM(ts.pasajeros),
            COUNT(*),
            CEIL(SUM(ts.subidas)::numeric   / NULLIF(COUNT(*), 0)),
            CEIL(SUM(ts.bajadas)::numeric   / NULLIF(COUNT(*), 0)),
            CEIL(SUM(ts.pasajeros)::numeric / NULLIF(COUNT(*), 0)),
            CURRENT_TIMESTAMP
        FROM timbradas_segmentos ts
        INNER JOIN dim d ON ts.id_viaje = d.idprogramacion
        WHERE ts.id_viaje = v_prog.idprogramacion
        GROUP BY
            ts.id_segmento, d.proceso, d.ano, d.idruta,
            d.id_dia_semana, d.id_estacionalidad_anio,
            ts.hora_inicio, ts.hora_fin
        ON CONFLICT (id_segmento, proceso, ano, id_ruta, id_dia_semana, id_estacionalidad_anio, hora, hora_inicio, hora_fin)
        DO UPDATE SET
            subidas            = timbradas_segmentos_anio.subidas    + EXCLUDED.subidas,
            bajadas            = timbradas_segmentos_anio.bajadas    + EXCLUDED.bajadas,
            pasajeros          = timbradas_segmentos_anio.pasajeros  + EXCLUDED.pasajeros,
            nro_viajes         = timbradas_segmentos_anio.nro_viajes + EXCLUDED.nro_viajes,
            promedio_subidas   = CEIL((timbradas_segmentos_anio.subidas   + EXCLUDED.subidas)::numeric   / NULLIF(timbradas_segmentos_anio.nro_viajes + EXCLUDED.nro_viajes, 0)),
            promedio_bajadas   = CEIL((timbradas_segmentos_anio.bajadas   + EXCLUDED.bajadas)::numeric   / NULLIF(timbradas_segmentos_anio.nro_viajes + EXCLUDED.nro_viajes, 0)),
            promedio_pasajeros = CEIL((timbradas_segmentos_anio.pasajeros + EXCLUDED.pasajeros)::numeric / NULLIF(timbradas_segmentos_anio.nro_viajes + EXCLUDED.nro_viajes, 0)),
            ultima_actualizacion = CURRENT_TIMESTAMP;

    END LOOP;

END;
$$;