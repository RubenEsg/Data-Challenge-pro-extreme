DO $$
DECLARE
    v_ruta     RECORD;
    v_tipo     VARCHAR(20);
    v_valor    NUMERIC;
    v_porcion  NUMERIC;
    v_minimo   NUMERIC;
BEGIN
    FOR v_ruta IN
        SELECT a.idruta
        FROM   rutas a
        INNER JOIN rutasgeograficas b ON a.idrutageo = b.idruta
        WHERE  a.proceso = 'cootransoriente'
        ORDER  BY a.idruta
    LOOP
        -- Par → distancia | Impar → cantidad
        IF MOD(v_ruta.idruta, 2) = 0 THEN
            v_tipo := 'distancia';
            v_valor := CASE MOD(v_ruta.idruta, 8)
                WHEN 0 THEN 100     -- 100 m
                WHEN 2 THEN 250     -- 250 m
                WHEN 4 THEN 500     -- 500 m
                WHEN 6 THEN 1000    -- 1 km
            END;
            v_porcion := CASE MOD(v_ruta.idruta, 4)
                WHEN 0 THEN 0.20    -- 20 cm (default)
                WHEN 2 THEN 0.50    -- 50 cm
            END;
        ELSE
            v_tipo := 'cantidad';
            v_valor := CASE MOD(v_ruta.idruta, 6)
                WHEN 1 THEN 5
                WHEN 3 THEN 8
                WHEN 5 THEN 12
            END;
            v_porcion := CASE MOD(v_ruta.idruta, 3)
                WHEN 1 THEN 0.20    -- 20 cm
                WHEN 0 THEN 0.50    -- 50 cm
                WHEN 2 THEN 1.00    -- 1 m
            END;
        END IF;

        v_minimo := v_porcion;  -- mínimo igual al tamaño de porción elegido

        RAISE NOTICE '→ idruta: % | tipo: % | valor: % | porción: % m',
            v_ruta.idruta, v_tipo, v_valor, v_porcion;

        BEGIN
            PERFORM fn_segmentar_ruta(
                v_ruta.idruta,
                v_tipo,
                v_valor,
                v_porcion,
                v_minimo
            );
        EXCEPTION WHEN OTHERS THEN
            RAISE WARNING 'Error en ruta %: %', v_ruta.idruta, SQLERRM;
        END;

    END LOOP;
END;
$$;