-- =====================================================================
-- FUNCIÓN COMPLETA
-- =====================================================================
CREATE OR REPLACE FUNCTION public.fn_insert_timbradas_anio(p_idprogramacion bigint)
 RETURNS boolean
 LANGUAGE plpgsql
AS $function$
DECLARE

    -- =====================================================================
    -- VARIABLES GENERALES (pasos 1-6)
    -- =====================================================================
    v_progvehiculos               progvehiculos%ROWTYPE;
    v_fecha_fin_real              TIMESTAMP;
    v_fecha_estacionalidad        DATE;
    v_estacionalidad_anio         INT;
    v_id_dia_semana               INT;
    v_bloque_fecha                TIME;
    v_fecha_fin                   DATE;
    v_hora_fin                    TIME;

    -- =====================================================================
    -- VARIABLES TIMBRADAS GENERALES (pasos 7-10)
    -- =====================================================================
    v_id_timbrada_anio            INT;
    v_subidas                     INT;
    v_bajadas                     INT;
    v_timbradas_anio_trazabilidad timbradas_anio_trazabilidad%ROWTYPE;

    -- =====================================================================
    -- VARIABLES DEBUG TIMBRADAS GENERALES (pasos 7-10)
    -- =====================================================================
    v_snap_subidas                INT;
    v_snap_bajadas                INT;
    v_snap_nro_viajes             INT;
    v_snap_prom_subidas           INT;
    v_snap_prom_bajadas           INT;

    -- =====================================================================
    -- VARIABLES TIMBRADAS POR ZONAS (paso 12)
    -- =====================================================================
    v_zona                        RECORD;
    v_id_timbrada_anio_zona       BIGINT;
    v_subidas_zona                INT;
    v_bajadas_zona                INT;
    v_timbrada_zona_trazabilidad  timbradas_anio_zonas_trazabilidad%ROWTYPE;

    -- =====================================================================
    -- VARIABLES DEBUG TIMBRADAS POR ZONAS (paso 12)
    -- =====================================================================
    v_snap_subidas_zona           INT;
    v_snap_bajadas_zona           INT;
    v_snap_nro_viajes_zona        INT;

    -- =====================================================================
    -- VARIABLES TIMBRADAS SEGMENTOS ANIO (paso 13)
    -- =====================================================================
    v_segmento                    RECORD;
    v_id_timbrada_segmento_anio   BIGINT;
    v_timbrada_seg_trazabilidad   timbradas_segmentos_anio_trazabilidad%ROWTYPE;

BEGIN

    RAISE NOTICE 'ENTRO A LA FUNCION fn_insert_timbradas_anio CON IDPROGRAMACION = %', p_idprogramacion;

    -- =====================================================================
    -- 1. Cargar datos de la programacion del vehiculo
    -- =====================================================================
    SELECT *
    INTO v_progvehiculos
    FROM progvehiculos
    WHERE idprogramacion = p_idprogramacion;

    RAISE NOTICE '[1] progvehiculos cargado: proceso=%, idruta=%, fechafin=%, fecha_fin_liquidacion=%',
        v_progvehiculos.proceso,
        v_progvehiculos.idruta,
        v_progvehiculos.fechafin,
        v_progvehiculos.fecha_fin_liquidacion;

    -- =====================================================================
    -- 2. Verificar que el viaje este apto para estadisticas historicas
    -- =====================================================================
    IF v_progvehiculos.apto_estadisticas_historicas IS NOT TRUE THEN
        RAISE NOTICE '[2] Viaje no apto para estadisticas historicas. Abortando.';
        RETURN FALSE;
    END IF;

    -- =====================================================================
    -- 3. Determinar fecha_fin_real
    -- =====================================================================
    IF v_progvehiculos.fecha_fin_liquidacion IS NOT NULL THEN
        v_fecha_fin_real := v_progvehiculos.fecha_fin_liquidacion;
    ELSE
        v_fecha_fin_real := v_progvehiculos.fechafin;
    END IF;

    RAISE NOTICE '[3] fecha_fin_real definida: %', v_fecha_fin_real;

    -- =====================================================================
    -- 4. Leer la ultima estacionalidad registrada para el proceso
    -- =====================================================================
    SELECT ultima_estacionalidad
    INTO v_fecha_estacionalidad
    FROM "Procesos" p
    WHERE p.proceso = v_progvehiculos.proceso;

    RAISE NOTICE '[4] ultima_estacionalidad en Procesos: %', v_fecha_estacionalidad;

    -- =====================================================================
    -- 5. Actualizar estacionalidad en Procesos si la fecha cambio o es NULL
    -- =====================================================================
    IF v_fecha_estacionalidad != CAST(v_fecha_fin_real AS DATE) OR v_fecha_estacionalidad IS NULL THEN

        SELECT ea.id_estacionalidad_anio
        INTO v_estacionalidad_anio
        FROM public.estacionalidades_anio ea
        WHERE ea.proceso      = v_progvehiculos.proceso
          AND ea.fecha_inicio <= v_fecha_fin_real
          AND ea.fecha_fin + INTERVAL '1 day' > v_fecha_fin_real
        ORDER BY
            (ea.fecha_fin - ea.fecha_inicio) ASC,
            ea.fecha_inicio DESC,
            ea.id_estacionalidad_anio DESC
        LIMIT 1;

        IF v_estacionalidad_anio IS NULL THEN
            RETURN FALSE;
        END IF;

        UPDATE "Procesos" p
        SET
            id_estacionalidad     = v_estacionalidad_anio,
            ultima_estacionalidad = CAST(v_fecha_fin_real AS DATE),
            id_diasemana          = EXTRACT(ISODOW FROM v_fecha_fin_real)::INT
        WHERE p.proceso = v_progvehiculos.proceso;

        RAISE NOTICE '[5] Procesos actualizado: id_estacionalidad=%, ultima_estacionalidad=%, id_diasemana=%',
            v_estacionalidad_anio,
            CAST(v_fecha_fin_real AS DATE),
            EXTRACT(ISODOW FROM v_fecha_fin_real)::INT;

    END IF;

    -- =====================================================================
    -- 6. Releer estado actual de Procesos
    -- =====================================================================
    SELECT ultima_estacionalidad, id_diasemana, id_estacionalidad,
           CAST(v_progvehiculos.fechafin AS DATE),
           CAST(v_progvehiculos.fechafin AS TIME)
    INTO v_fecha_estacionalidad, v_id_dia_semana, v_estacionalidad_anio, v_fecha_fin, v_hora_fin
    FROM "Procesos" p
    WHERE p.proceso = v_progvehiculos.proceso;

    RAISE NOTICE '[6] Estado Procesos: ultima_estacionalidad=%, id_diasemana=%, id_estacionalidad=%, fecha_fin=%, hora_fin=%',
        v_fecha_estacionalidad, v_id_dia_semana, v_estacionalidad_anio, v_fecha_fin, v_hora_fin;

    -- =====================================================================
    -- 7. Calcular bloque de 15 minutos
    -- =====================================================================
    v_bloque_fecha := (date_trunc('hour', v_fecha_fin_real)
                      + floor(date_part('minute', v_fecha_fin_real) / 15) * interval '15 minute')::time;

    RAISE NOTICE '[7] Bloque 15min: v_bloque_fecha=% (fecha_fin_real=%)', v_bloque_fecha, v_fecha_fin_real;

    -- =====================================================================
    -- 8. Buscar registro existente en timbradas_anio
    -- =====================================================================
    SELECT id_timbrada_anio
    INTO v_id_timbrada_anio
    FROM timbradas_anio
    WHERE proceso                = v_progvehiculos.proceso
      AND ano                    = EXTRACT(YEAR FROM v_fecha_fin_real)
      AND id_ruta                = v_progvehiculos.idruta
      AND id_dia_semana          = v_id_dia_semana
      AND id_estacionalidad_anio = v_estacionalidad_anio
      AND hora_inicio            = v_bloque_fecha;

    RAISE NOTICE '[8] timbradas_anio existente: v_id_timbrada_anio=%', v_id_timbrada_anio;

    -- =====================================================================
    -- 9. Obtener totales del viaje desde conteo_pasajeros
    -- =====================================================================
    SELECT COALESCE(SUM(cantidad_subida), 0), COALESCE(SUM(cantidad_bajada), 0)
    INTO v_subidas, v_bajadas
    FROM conteo_pasajeros
    WHERE idprogramacion = p_idprogramacion;

    RAISE NOTICE '[9] Pasajeros del viaje: subidas=%, bajadas=%', v_subidas, v_bajadas;

    -- =====================================================================
    -- 10. Actualizar o insertar en timbradas_anio
    -- =====================================================================
    IF v_id_timbrada_anio IS NOT NULL THEN

        SELECT *
        INTO v_timbradas_anio_trazabilidad
        FROM timbradas_anio_trazabilidad
        WHERE id_timbrada_anio = v_id_timbrada_anio
          AND vigente;

        IF v_timbradas_anio_trazabilidad.id_timbrada_anio IS NOT NULL THEN

            RAISE NOTICE '[10a] ANTES  de restar  >> subidas=%, bajadas=%, nro_viajes=%, prom_subidas=%, prom_bajadas=%',
                v_snap_subidas, v_snap_bajadas, v_snap_nro_viajes, v_snap_prom_subidas, v_snap_prom_bajadas;

            UPDATE timbradas_anio
            SET
                subidas          = subidas - COALESCE(v_timbradas_anio_trazabilidad.subidas, 0),
                bajadas          = bajadas - COALESCE(v_timbradas_anio_trazabilidad.bajadas, 0),
                nro_viajes       = nro_viajes - 1,
                promedio_subidas = CASE WHEN (nro_viajes - 1) > 0
                                        THEN CEIL((subidas - COALESCE(v_timbradas_anio_trazabilidad.subidas, 0))::numeric / (nro_viajes - 1))
                                        ELSE 0 END,
                promedio_bajadas = CASE WHEN (nro_viajes - 1) > 0
                                        THEN CEIL((bajadas - COALESCE(v_timbradas_anio_trazabilidad.bajadas, 0))::numeric / (nro_viajes - 1))
                                        ELSE 0 END
            WHERE id_timbrada_anio = v_timbradas_anio_trazabilidad.id_timbrada_anio;

            RAISE NOTICE '[10a] DESPUES de restar  >> subidas=%, bajadas=%, nro_viajes=%, prom_subidas=%, prom_bajadas=%',
                v_snap_subidas, v_snap_bajadas, v_snap_nro_viajes, v_snap_prom_subidas, v_snap_prom_bajadas;

            UPDATE timbradas_anio_trazabilidad
            SET vigente = FALSE
            WHERE id_timbrada_anio = v_id_timbrada_anio
              AND vigente;

        END IF;

        RAISE NOTICE '[10a] ANTES  de sumar    >> subidas=%, bajadas=%, nro_viajes=%, prom_subidas=%, prom_bajadas=%',
            v_snap_subidas, v_snap_bajadas, v_snap_nro_viajes, v_snap_prom_subidas, v_snap_prom_bajadas;

        UPDATE timbradas_anio
        SET
            subidas              = subidas + COALESCE(v_subidas, 0),
            bajadas              = bajadas + COALESCE(v_bajadas, 0),
            nro_viajes           = nro_viajes + 1,
            promedio_subidas     = CEIL((subidas + COALESCE(v_subidas, 0))::numeric / (nro_viajes + 1)),
            promedio_bajadas     = CEIL((bajadas + COALESCE(v_bajadas, 0))::numeric / (nro_viajes + 1)),
            ultima_actualizacion = CURRENT_TIMESTAMP
        WHERE id_timbrada_anio = v_id_timbrada_anio;

        RAISE NOTICE '[10a] DESPUES de sumar   >> subidas=%, bajadas=%, nro_viajes=%, prom_subidas=%, prom_bajadas=%',
            v_snap_subidas, v_snap_bajadas, v_snap_nro_viajes, v_snap_prom_subidas, v_snap_prom_bajadas;

    ELSE

        INSERT INTO timbradas_anio (
            proceso, ano, id_ruta, id_dia_semana, id_estacionalidad_anio,
            hora, hora_inicio, hora_fin,
            subidas, bajadas, nro_viajes,
            promedio_subidas, promedio_bajadas, ultima_actualizacion
        )
        VALUES (
            v_progvehiculos.proceso,
            EXTRACT(YEAR FROM v_fecha_fin_real),
            v_progvehiculos.idruta,
            v_id_dia_semana,
            v_estacionalidad_anio,
            v_bloque_fecha,
            v_bloque_fecha,
            v_bloque_fecha + interval '15 minutes',
            COALESCE(v_subidas, 0),
            COALESCE(v_bajadas, 0),
            1,
            COALESCE(v_subidas, 0),
            COALESCE(v_bajadas, 0),
            CURRENT_TIMESTAMP
        )
        RETURNING id_timbrada_anio INTO v_id_timbrada_anio;

        RAISE NOTICE '[10b] INSERT exitoso >> id_timbrada_anio=%, subidas=%, bajadas=%, nro_viajes=1',
            v_id_timbrada_anio, v_subidas, v_bajadas;

    END IF;

    -- =====================================================================
    -- 11. Insertar trazabilidad del viaje general
    -- =====================================================================
    INSERT INTO timbradas_anio_trazabilidad (id_timbrada_anio, idprogramacion, subidas, bajadas, vigente)
    VALUES (v_id_timbrada_anio, p_idprogramacion, COALESCE(v_subidas, 0), COALESCE(v_bajadas, 0), TRUE);

    RAISE NOTICE '[11] Trazabilidad insertada >> id_timbrada_anio=%, idprogramacion=%, subidas=%, bajadas=%, vigente=TRUE',
        v_id_timbrada_anio, p_idprogramacion, v_subidas, v_bajadas;

    -- =====================================================================
    -- 12. Procesar zonas
    -- =====================================================================
    FOR v_zona IN
        SELECT ac.idarea AS idzona,
               SUM(cp.cantidad_subida) AS subidas,
               SUM(cp.cantidad_bajada) AS bajadas
        FROM public.conteo_pasajeros cp
        INNER JOIN public.progvehiculos pv
            ON cp.idprogramacion = pv.idprogramacion
        INNER JOIN public.rutas r
            ON pv.idruta = r.idruta
        INNER JOIN public.areascontrol ac
            ON ac.idarea = COALESCE(r.zona_tolerancia_inicio, r.zona_tolerancia_fin)
           AND ST_Contains(ac.geom, ST_SetSRID(ST_Point(cp.longitud, cp.latitud), 4326))
        WHERE cp.idprogramacion = p_idprogramacion
          AND r.id_tipo_tarifa  = 2
        GROUP BY ac.idarea
    LOOP

        v_subidas_zona := COALESCE(v_zona.subidas, 0);
        v_bajadas_zona := COALESCE(v_zona.bajadas, 0);

        RAISE NOTICE '[12-ZONA-%] INICIO: subidas_viaje=%, bajadas_viaje=%',
            v_zona.idzona, v_subidas_zona, v_bajadas_zona;

        SELECT id_timbrada_anio_zona
        INTO v_id_timbrada_anio_zona
        FROM timbradas_anio_zonas
        WHERE id_timbrada_anio = v_id_timbrada_anio
          AND id_zona_tarifa   = v_zona.idzona;

        IF v_id_timbrada_anio_zona IS NOT NULL THEN

            SELECT *
            INTO v_timbrada_zona_trazabilidad
            FROM timbradas_anio_zonas_trazabilidad
            WHERE id_timbrada_anio_zona = v_id_timbrada_anio_zona
              AND vigente;

            IF v_timbrada_zona_trazabilidad.id_timbrada_anio_zona IS NOT NULL THEN

                RAISE NOTICE '[12-ZONA-%] ANTES  de restar  >> subidas=%, bajadas=%, nro_viajes=%',
                    v_zona.idzona, v_snap_subidas_zona, v_snap_bajadas_zona, v_snap_nro_viajes_zona;

                UPDATE timbradas_anio_zonas
                SET
                    subidas          = subidas - COALESCE(v_timbrada_zona_trazabilidad.subidas, 0),
                    bajadas          = bajadas - COALESCE(v_timbrada_zona_trazabilidad.bajadas, 0),
                    nro_viajes       = nro_viajes - 1,
                    promedio_subidas = CASE WHEN (nro_viajes - 1) > 0
                                            THEN CEIL((subidas - COALESCE(v_timbrada_zona_trazabilidad.subidas, 0))::numeric / (nro_viajes - 1))
                                            ELSE 0 END,
                    promedio_bajadas = CASE WHEN (nro_viajes - 1) > 0
                                            THEN CEIL((bajadas - COALESCE(v_timbrada_zona_trazabilidad.bajadas, 0))::numeric / (nro_viajes - 1))
                                            ELSE 0 END
                WHERE id_timbrada_anio_zona = v_id_timbrada_anio_zona;

                RAISE NOTICE '[12-ZONA-%] DESPUES de restar  >> subidas=%, bajadas=%, nro_viajes=%',
                    v_zona.idzona, v_snap_subidas_zona, v_snap_bajadas_zona, v_snap_nro_viajes_zona;

                UPDATE timbradas_anio_zonas_trazabilidad
                SET vigente = FALSE
                WHERE id_timbrada_anio_zona = v_id_timbrada_anio_zona
                  AND vigente;

            END IF;

            RAISE NOTICE '[12-ZONA-%] ANTES  de sumar    >> subidas=%, bajadas=%, nro_viajes=%',
                v_zona.idzona, v_snap_subidas_zona, v_snap_bajadas_zona, v_snap_nro_viajes_zona;

            UPDATE timbradas_anio_zonas
            SET
                subidas              = subidas + COALESCE(v_subidas_zona, 0),
                bajadas              = bajadas + COALESCE(v_bajadas_zona, 0),
                nro_viajes           = nro_viajes + 1,
                promedio_subidas     = CEIL((subidas + COALESCE(v_subidas_zona, 0))::numeric / (nro_viajes + 1)),
                promedio_bajadas     = CEIL((bajadas + COALESCE(v_bajadas_zona, 0))::numeric / (nro_viajes + 1)),
                ultima_actualizacion = CURRENT_TIMESTAMP
            WHERE id_timbrada_anio_zona = v_id_timbrada_anio_zona;

            RAISE NOTICE '[12-ZONA-%] DESPUES de sumar   >> subidas=%, bajadas=%, nro_viajes=%',
                v_zona.idzona, v_snap_subidas_zona, v_snap_bajadas_zona, v_snap_nro_viajes_zona;

        ELSE

            INSERT INTO timbradas_anio_zonas (
                id_timbrada_anio, id_zona_tarifa,
                subidas, bajadas, nro_viajes,
                promedio_subidas, promedio_bajadas,
                ultima_actualizacion
            )
            VALUES (
                v_id_timbrada_anio,
                v_zona.idzona,
                COALESCE(v_subidas_zona, 0),
                COALESCE(v_bajadas_zona, 0),
                1,
                COALESCE(v_subidas_zona, 0),
                COALESCE(v_bajadas_zona, 0),
                CURRENT_TIMESTAMP
            )
            RETURNING id_timbrada_anio_zona INTO v_id_timbrada_anio_zona;

            RAISE NOTICE '[12-ZONA-%] INSERT exitoso >> id_timbrada_anio_zona=%, subidas=%, bajadas=%, nro_viajes=1',
                v_zona.idzona, v_id_timbrada_anio_zona, v_subidas_zona, v_bajadas_zona;

        END IF;

        INSERT INTO timbradas_anio_zonas_trazabilidad (
            id_timbrada_anio_zona, idprogramacion,
            subidas, bajadas, vigente
        )
        VALUES (
            v_id_timbrada_anio_zona,
            p_idprogramacion,
            COALESCE(v_subidas_zona, 0),
            COALESCE(v_bajadas_zona, 0),
            TRUE
        );

        RAISE NOTICE '[12-ZONA-%] Trazabilidad insertada >> id_timbrada_anio_zona=%, vigente=TRUE',
            v_zona.idzona, v_id_timbrada_anio_zona;

    END LOOP;

    -- =====================================================================
    -- 13. Procesar timbradas_segmentos_anio
    --     Lee desde timbradas_segmentos los datos del viaje actual.
    --     Para cada segmento aplica el patron resta-anterior / suma-nueva.
    --     pasajeros se acumula igual que subidas y bajadas → promedio exacto.
    -- =====================================================================
    FOR v_segmento IN
        SELECT
            ts.id_segmento,
            COALESCE(ts.subidas,   0) AS subidas,
            COALESCE(ts.bajadas,   0) AS bajadas,
            COALESCE(ts.pasajeros, 0) AS pasajeros
        FROM timbradas_segmentos ts
        WHERE ts.id_viaje = p_idprogramacion
    LOOP

        RAISE NOTICE '[13-SEG-%] INICIO: subidas=%, bajadas=%, pasajeros=%',
            v_segmento.id_segmento,
            v_segmento.subidas,
            v_segmento.bajadas,
            v_segmento.pasajeros;

        -- Buscar registro existente para este segmento en el bloque actual
        SELECT id_timbrada_segmento_anio
        INTO   v_id_timbrada_segmento_anio
        FROM   timbradas_segmentos_anio
        WHERE  id_segmento            = v_segmento.id_segmento
          AND  proceso                = v_progvehiculos.proceso
          AND  ano                    = EXTRACT(YEAR FROM v_fecha_fin_real)
          AND  id_ruta                = v_progvehiculos.idruta
          AND  id_dia_semana          = v_id_dia_semana
          AND  id_estacionalidad_anio = v_estacionalidad_anio
          AND  hora_inicio            = v_bloque_fecha;

        IF v_id_timbrada_segmento_anio IS NOT NULL THEN

            -- Buscar trazabilidad vigente de este segmento para este viaje
            SELECT *
            INTO   v_timbrada_seg_trazabilidad
            FROM   timbradas_segmentos_anio_trazabilidad
            WHERE  id_timbrada_segmento_anio = v_id_timbrada_segmento_anio
              AND  idprogramacion            = p_idprogramacion
              AND  vigente;

            IF v_timbrada_seg_trazabilidad.id_timbrada_segmento_anio IS NOT NULL THEN

                -- Restar contribucion anterior del mismo viaje
                UPDATE timbradas_segmentos_anio
                SET
                    subidas            = subidas   - v_timbrada_seg_trazabilidad.subidas,
                    bajadas            = bajadas   - v_timbrada_seg_trazabilidad.bajadas,
                    pasajeros          = pasajeros - v_timbrada_seg_trazabilidad.pasajeros,
                    nro_viajes         = nro_viajes - 1,
                    promedio_subidas   = CASE WHEN (nro_viajes - 1) > 0
                                              THEN CEIL((subidas   - v_timbrada_seg_trazabilidad.subidas)::numeric   / (nro_viajes - 1))
                                              ELSE 0 END,
                    promedio_bajadas   = CASE WHEN (nro_viajes - 1) > 0
                                              THEN CEIL((bajadas   - v_timbrada_seg_trazabilidad.bajadas)::numeric   / (nro_viajes - 1))
                                              ELSE 0 END,
                    promedio_pasajeros = CASE WHEN (nro_viajes - 1) > 0
                                              THEN CEIL((pasajeros - v_timbrada_seg_trazabilidad.pasajeros)::numeric / (nro_viajes - 1))
                                              ELSE 0 END,
                    ultima_actualizacion = CURRENT_TIMESTAMP
                WHERE id_timbrada_segmento_anio = v_id_timbrada_segmento_anio;

                -- Invalidar trazabilidad anterior
                UPDATE timbradas_segmentos_anio_trazabilidad
                SET vigente = FALSE
                WHERE id_timbrada_segmento_anio = v_id_timbrada_segmento_anio
                  AND idprogramacion            = p_idprogramacion
                  AND vigente;

                RAISE NOTICE '[13-SEG-%] Restada contribucion anterior: subidas=%, bajadas=%, pasajeros=%',
                    v_segmento.id_segmento,
                    v_timbrada_seg_trazabilidad.subidas,
                    v_timbrada_seg_trazabilidad.bajadas,
                    v_timbrada_seg_trazabilidad.pasajeros;

            END IF;

            -- Sumar nueva contribucion del viaje
            UPDATE timbradas_segmentos_anio
            SET
                subidas            = subidas   + v_segmento.subidas,
                bajadas            = bajadas   + v_segmento.bajadas,
                pasajeros          = pasajeros + v_segmento.pasajeros,
                nro_viajes         = nro_viajes + 1,
                promedio_subidas   = CEIL((subidas   + v_segmento.subidas)::numeric   / (nro_viajes + 1)),
                promedio_bajadas   = CEIL((bajadas   + v_segmento.bajadas)::numeric   / (nro_viajes + 1)),
                promedio_pasajeros = CEIL((pasajeros + v_segmento.pasajeros)::numeric / (nro_viajes + 1)),
                ultima_actualizacion = CURRENT_TIMESTAMP
            WHERE id_timbrada_segmento_anio = v_id_timbrada_segmento_anio;

            RAISE NOTICE '[13-SEG-%] UPDATE exitoso: subidas=%, bajadas=%, pasajeros=%',
                v_segmento.id_segmento,
                v_segmento.subidas,
                v_segmento.bajadas,
                v_segmento.pasajeros;

        ELSE

            -- No existe → insertar con nro_viajes = 1, promedios = valores del viaje
            INSERT INTO timbradas_segmentos_anio (
                id_segmento,
                proceso,
                ano,
                id_ruta,
                id_dia_semana,
                id_estacionalidad_anio,
                hora,
                hora_inicio,
                hora_fin,
                subidas,
                bajadas,
                pasajeros,
                nro_viajes,
                promedio_subidas,
                promedio_bajadas,
                promedio_pasajeros,
                ultima_actualizacion
            )
            VALUES (
                v_segmento.id_segmento,
                v_progvehiculos.proceso,
                EXTRACT(YEAR FROM v_fecha_fin_real),
                v_progvehiculos.idruta,
                v_id_dia_semana,
                v_estacionalidad_anio,
                v_bloque_fecha,
                v_bloque_fecha,
                v_bloque_fecha + interval '15 minutes',
                v_segmento.subidas,
                v_segmento.bajadas,
                v_segmento.pasajeros,
                1,
                v_segmento.subidas,
                v_segmento.bajadas,
                v_segmento.pasajeros,
                CURRENT_TIMESTAMP
            )
            RETURNING id_timbrada_segmento_anio INTO v_id_timbrada_segmento_anio;

            RAISE NOTICE '[13-SEG-%] INSERT exitoso >> id_timbrada_segmento_anio=%, nro_viajes=1',
                v_segmento.id_segmento,
                v_id_timbrada_segmento_anio;

        END IF;

        -- Insertar trazabilidad del segmento para este viaje
        INSERT INTO timbradas_segmentos_anio_trazabilidad (
            id_timbrada_segmento_anio,
            idprogramacion,
            subidas,
            bajadas,
            pasajeros,
            vigente
        )
        VALUES (
            v_id_timbrada_segmento_anio,
            p_idprogramacion,
            v_segmento.subidas,
            v_segmento.bajadas,
            v_segmento.pasajeros,
            TRUE
        );

        RAISE NOTICE '[13-SEG-%] Trazabilidad insertada >> id_timbrada_segmento_anio=%, vigente=TRUE',
            v_segmento.id_segmento,
            v_id_timbrada_segmento_anio;

    END LOOP;

    RAISE NOTICE 'Proceso finalizado correctamente para idprogramacion=%', p_idprogramacion;
    RETURN TRUE;

END;
$function$;