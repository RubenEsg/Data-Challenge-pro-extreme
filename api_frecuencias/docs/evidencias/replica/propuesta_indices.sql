-- Propuesta de índices para el DBA de Extreme Technologies (§8.3: se piden después de revisar
-- EXPLAIN (ANALYZE, BUFFERS) y los aplica el responsable de la base). Generada por scripts/replica_explain.py y medida
-- SOLO en la réplica local. En producción, CONCURRENTLY no bloquea las escrituras de la captura ni de los triggers.
-- Ninguno cambia tablas, triggers, funciones ni scripts: solo acelera las lecturas incrementales del módulo de IA.

-- 1) Lectura incremental de timbradas_segmentos (lo que escribe tg_timbrada_segmento) por marca de agua.
CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_ia_timbradas_segmentos_ultimaactualizacion
    ON public.timbradas_segmentos (ultimaactualizacion);
-- 2) Re-agregación de las franjas tocadas: segmentos de un viaje (la llave foránea id_viaje no tiene índice).
CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_ia_timbradas_segmentos_id_viaje
    ON public.timbradas_segmentos (id_viaje);
-- 3) Viajes de una ruta en una hora de salida (franja de la demanda horaria).
CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_ia_progvehiculos_ruta_hora_salida
    ON public.progvehiculos (idruta, (date_trunc('hour', fechasalida)));
-- 4) Marca de agua de los consolidados (§8.3: «consultar los incrementos por ultima_actualizacion»).
CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_ia_timbradas_consolidado_ultima_actualizacion
    ON public.timbradas_consolidado (ultima_actualizacion);
CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_ia_timbradas_anio_ultima_actualizacion
    ON public.timbradas_anio (ultima_actualizacion);
CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_ia_timbradas_segmentos_anio_ultima_actualizacion
    ON public.timbradas_segmentos_anio (ultima_actualizacion);
CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_ia_timbradas_segmentos_consolidado_ultima_actualizacion
    ON public.timbradas_segmentos_consolidado (ultima_actualizacion);
