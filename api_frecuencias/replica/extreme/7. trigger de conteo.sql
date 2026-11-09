-- DROP FUNCTION public.fn_tg_timbrada_segmento();

CREATE OR REPLACE FUNCTION public.fn_tg_timbrada_segmento()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
DECLARE
    v_idruta       INTEGER;
    v_hora_inicio  TIME;
    v_hora_fin     TIME;
    v_rec          RECORD;
    v_id_existente BIGINT;
BEGIN
    IF NEW.idprogramacion IS NULL THEN
        RETURN NEW;
    END IF;

    SELECT r.idruta
    INTO   v_idruta
    FROM   progvehiculos pv
    INNER JOIN rutas r
            ON pv.idruta  = r.idruta
           AND pv.proceso = r.proceso
    WHERE  pv.idprogramacion = NEW.idprogramacion;

    IF NOT FOUND THEN
        RETURN NEW;
    END IF;

    v_hora_inicio := (
        DATE_TRUNC('hour', NEW.fecha) +
        INTERVAL '15 minutes' * FLOOR(EXTRACT(MINUTE FROM NEW.fecha) / 15)
    )::TIME;
    v_hora_fin := v_hora_inicio + INTERVAL '15 minutes';

    FOR v_rec IN (
        WITH conteos AS (
            SELECT
                cp.ctid,
                cp.idprogramacion,
                cp.cantidad_subida,
                cp.cantidad_bajada,
                cp.acumulada_subida,
                cp.acumulada_bajada,
                cp.fecha,
                ST_SetSRID(ST_MakePoint(cp.longitud, cp.latitud), 4326) AS punto
            FROM conteo_pasajeros cp
            WHERE cp.idprogramacion = NEW.idprogramacion
              AND cp.fecha::TIME >= v_hora_inicio
              AND cp.fecha::TIME <  v_hora_fin
        ),
        conteos_segmento AS (
            SELECT DISTINCT ON (c.ctid)
                c.idprogramacion,
                c.cantidad_subida,
                c.cantidad_bajada,
                c.acumulada_subida,
                c.acumulada_bajada,
                c.fecha,
                rs.id AS id_segmento
            FROM conteos c
            INNER JOIN rutas_segmentos_config rsc
                    ON rsc.idruta = v_idruta
                   AND rsc.activo = TRUE
            INNER JOIN rutas_segmentos rs
                    ON rs.id_config = rsc.id
                   AND rs.activo    = TRUE
            ORDER BY c.ctid, c.punto <-> rs.geom_segmento
        )
        SELECT
            id_segmento,
            idprogramacion,
            MIN(fecha)::DATE                AS fecha,
            SUM(cantidad_subida)            AS subidas,
            SUM(cantidad_bajada)            AS bajadas,
            GREATEST(
                (ARRAY_AGG(acumulada_subida ORDER BY fecha DESC))[1] -
                (ARRAY_AGG(acumulada_bajada ORDER BY fecha DESC))[1],
            0)                              AS pasajeros
        FROM conteos_segmento
        GROUP BY id_segmento, idprogramacion
    )
    LOOP
        -- Verificar si ya existe el registro
        SELECT id_timbrada_segmento
        INTO   v_id_existente
        FROM   timbradas_segmentos
        WHERE  id_segmento = v_rec.id_segmento
          AND  id_viaje    = v_rec.idprogramacion
          AND  hora_inicio = v_hora_inicio;

        IF FOUND THEN
            -- Actualizar sin tocar el ID
            UPDATE timbradas_segmentos
               SET subidas             = v_rec.subidas,
                   bajadas             = v_rec.bajadas,
                   pasajeros           = v_rec.pasajeros,
                   ultimaactualizacion = NOW()
             WHERE id_timbrada_segmento = v_id_existente;
        ELSE
            -- Insertar solo cuando es genuinamente nuevo
            INSERT INTO timbradas_segmentos (
                id_segmento, id_viaje, fecha,
                hora_inicio, hora_fin,
                subidas, bajadas, pasajeros,
                ultimaactualizacion
            ) VALUES (
                v_rec.id_segmento,
                v_rec.idprogramacion,
                v_rec.fecha,
                v_hora_inicio,
                v_hora_fin,
                v_rec.subidas,
                v_rec.bajadas,
                v_rec.pasajeros,
                NOW()
            );
        END IF;

    END LOOP;

    RETURN NEW;
END;
$function$
;


create trigger tg_timbrada_segmento after
insert
    or
update
    on
    public.conteo_pasajeros for each row execute function fn_tg_timbrada_segmento()