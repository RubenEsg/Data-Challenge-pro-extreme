-- ERRATA E2 (solo réplica; hallazgo H3 para Extreme). Se ejecuta DESPUÉS de «1. tablas.sql». Se desactiva con
-- REPLICA_ERRATA_E2=0 al crear el volumen.
--
-- Defecto: «1. tablas.sql» define timbradas_segmentos con UNIQUE (id_segmento, id_viaje), pero el
-- ON CONFLICT (id_segmento, id_viaje, hora_inicio) del script 5 y la búsqueda del trigger del script 7 usan 3
-- columnas. Con la llave de 2 columnas, cuando un viaje pasa por el mismo segmento en dos bloques de 15 minutos el
-- INSERT del trigger viola la llave y, como el trigger es AFTER INSERT, se pierde también la fila cruda de
-- conteo_pasajeros (en el prototipo: 91 de 777 filas, 11,7 %). El script 5 solo pudo correr en la base de Extreme si
-- existía la llave de 3 columnas: hay que confirmarlo con su pg_indexes.
-- La prueba tests/replica/test_scripts_extreme.py::test_E2_sin_errata_pierde_filas muestra la pérdida sin esta
-- corrección y que con ella las dos filas se conservan.
ALTER TABLE public.timbradas_segmentos
    DROP CONSTRAINT timbradas_segmentos_id_segmento_id_viaje_key;
ALTER TABLE public.timbradas_segmentos
    ADD CONSTRAINT timbradas_segmentos_id_segmento_id_viaje_hora_inicio_key
        UNIQUE (id_segmento, id_viaje, hora_inicio);
