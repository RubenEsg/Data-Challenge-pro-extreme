-- ARMONIZACIÓN H1 (solo réplica, de DATOS; hallazgo H1 para Extreme). La aplica scripts/replica_cargar.py después de
-- cargar las exportaciones, salvo con REPLICA_ARMONIZAR_ESTACIONALIDADES=0.
--
-- Defecto: las 231 filas de estacionalidades_anio tienen proceso = 'cootransoriente', mientras que "Procesos",
-- progvehiculos y rutas son de 'sobusa' y "Procesos".ultima_estacionalidad está en NULL. El paso 5 de
-- fn_insert_timbradas_anio busca la estacionalidad por proceso y devuelve FALSE en todos los viajes de Sobusa, así
-- que ninguna liquidación escribe nada.
-- Corrección: marcar las estacionalidades con el proceso de los datos. No cambia fechas ni ids.
-- La prueba tests/replica/test_scripts_extreme.py::test_H1_sin_armonizar_liquidacion_falla lo demuestra en una
-- transacción que se deshace (FALSE sin H1, TRUE con H1).
UPDATE public.estacionalidades_anio
   SET proceso = 'sobusa'
 WHERE proceso = 'cootransoriente';
