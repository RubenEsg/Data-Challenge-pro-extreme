-- Base de RESULTADOS (servicio «db» de docker-compose.yml): estadísticas de las consultas de la API sobre el esquema
-- ai_frecuencias (§8.2 y §18 «rendimiento»: ver las consultas más lentas sin instrumentar el código).
-- La librería se carga con shared_preload_libraries=pg_stat_statements (command del servicio); este script crea la
-- extensión al inicializar un volumen nuevo. En un volumen que ya existía, una sola vez:
--   docker compose -p sobusa_api exec db psql -U sobusa -d ai_frecuencias -c "CREATE EXTENSION IF NOT EXISTS pg_stat_statements"
-- Consulta típica:
--   SELECT calls, round(mean_exec_time::numeric, 1) AS media_ms, left(query, 120) FROM pg_stat_statements
--   ORDER BY mean_exec_time DESC LIMIT 10;
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
