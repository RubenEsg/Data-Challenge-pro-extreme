-- Propuesta de índices para el DBA de Extreme Technologies (§8.3: se piden después de revisar
-- EXPLAIN (ANALYZE, BUFFERS) y los aplica el responsable de la base). Medidos SOLO en la réplica local, cada uno dentro
-- de una transacción que se revierte, y la propuesta ENTERA con las estadísticas al día (ANALYZE) frente a todas las
-- lecturas del módulo de IA (scripts/replica_indices_candidatos.py, docs/evidencias/replica/indices_candidatos.md).
-- En producción, CONCURRENTLY no bloquea las escrituras de la captura ni de los triggers. Después de crearlos conviene
-- ANALYZE de esas tablas. Ninguno cambia tablas, triggers, funciones ni scripts: solo acelera las lecturas.

-- 1) Lectura incremental de timbradas_segmentos (lo que escribe tg_timbrada_segmento) por marca de agua y ventana de
-- solape del refresco de la agregación de segmentos.
CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_ia_timbradas_segmentos_ultimaactualizacion
    ON public.timbradas_segmentos (ultimaactualizacion);
-- 2) Segmentos de un viaje: re-agregación de las franjas tocadas, ocupación actual por segmento y conteo de segmentos
-- de los viajes de §5.3 (la llave foránea id_viaje no tiene índice).
CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_ia_timbradas_segmentos_id_viaje
    ON public.timbradas_segmentos (id_viaje);
-- 3) Viajes de una ruta en una hora de salida (las franjas de la demanda horaria y la ventana de los viajes de §5.3).
CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_ia_progvehiculos_ruta_hora_salida
    ON public.progvehiculos (idruta, (date_trunc('hour', fechasalida)));
-- 4) Marca de agua de los consolidados (§8.3: «consultar los incrementos por ultima_actualizacion»).
CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_ia_timbradas_consolidado_ultima_actualizacion
    ON public.timbradas_consolidado (ultima_actualizacion);
-- 5) Marca de agua de timbradas_anio (§8.3), con el mismo argumento que el de timbradas_consolidado.
CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_ia_timbradas_anio_ultima_actualizacion
    ON public.timbradas_anio (ultima_actualizacion);
-- 6) Lectura incremental de las tablas por segmento de UN proceso (proceso = :proceso desde su marca). En la base de
-- Extreme son de otros operadores (hallazgo H4) y, sin filas del proceso, la lectura empieza en la marca inicial: la
-- marca sola no evita recorrerlas. Medido con ese volumen en una tabla temporal
-- (docs/evidencias/consolidados/lectura_por_proceso.md).
CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_ia_timbradas_segmentos_anio_proceso_marca
    ON public.timbradas_segmentos_anio (proceso, ultima_actualizacion);
CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_ia_timbradas_segmentos_consolidado_proceso_marca
    ON public.timbradas_segmentos_consolidado (proceso, ultima_actualizacion);
