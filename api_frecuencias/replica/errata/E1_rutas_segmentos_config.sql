-- ERRATA E1 (solo réplica; hallazgo H2 para Extreme). Se ejecuta ANTES de «1. tablas.sql», que sigue sin cambios.
--
-- Defecto: en «1. tablas.sql» la línea 31 termina en «;» dentro del CREATE TABLE rutas_segmentos_config
-- («tamaño_minimo_porcion_m NUMERIC(12, 4) NOT NULL DEFAULT 0.20;»). psql envía el bloque hasta la línea 38 y el
-- servidor lo rechaza con un error de sintaxis; además la tabla no tiene la columna «activo» que usan los scripts 2 y
-- 7. Sin la tabla fallan en cascada otras 5: rutas_segmentos, timbradas_segmentos, timbradas_segmentos_anio,
-- timbradas_segmentos_anio_trazabilidad y timbradas_segmentos_consolidado.
--
-- Corrección: crear la tabla como está en la base real, con las columnas de la exportación
-- (datos/rutas_segmentos_config.parquet, incluida «activo») y la llave única y los CHECK del script 1. Después el
-- script 1 se ejecuta tal cual y deja registrado 1 error esperado (el de la línea 38).
-- La prueba tests/replica/test_scripts_extreme.py::test_script1_sin_errata_falla muestra el fallo sin esta corrección.
CREATE TABLE rutas_segmentos_config (
    id                  BIGSERIAL       PRIMARY KEY,
    idruta              INTEGER         NOT NULL,
    idrutageo           INTEGER         NOT NULL,
    tipo_agrupacion     VARCHAR(20)     NOT NULL
                            CHECK (tipo_agrupacion IN ('distancia', 'cantidad')),
    tamaño_segmento_m   NUMERIC(12, 3),
    numero_segmentos    INTEGER,
    fecha_creacion      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    tamaño_porcion_m         NUMERIC(12, 4) NOT NULL DEFAULT 0.20,
    tamaño_minimo_porcion_m  NUMERIC(12, 4) NOT NULL DEFAULT 0.20,
    activo              BOOLEAN         NOT NULL DEFAULT TRUE,
    UNIQUE (idruta, idrutageo),
    CHECK (
        (tipo_agrupacion = 'distancia' AND tamaño_segmento_m IS NOT NULL AND numero_segmentos IS NULL)
        OR
        (tipo_agrupacion = 'cantidad'  AND numero_segmentos IS NOT NULL  AND tamaño_segmento_m IS NULL)
    )
);
