# Protocolo común de evaluación (experimentos nocturnos, 2026-10-04)

Todos los experimentos de pronóstico de demanda usan el mismo protocolo para que sus resultados sean comparables.

## Unidad de análisis
- **Unidad de decisión:** ruta × día × **hora de salida** (4 a 21 h). Es la unidad en la que Sobusa decide cuántos buses despachar.
- Variantes permitidas (hora real de abordaje, franjas de 15 min, totales diarios × perfil) deben reportar además sus métricas traducidas a la unidad de decisión cuando sea posible.

## Variables objetivo
| Objetivo | Definición | Base |
|---|---|---|
| `pasajeros_total` | suma de `numeropasajeros` de los viajes válidos que salen en esa ruta, día y hora | viajes válidos con dato de pasajeros y ≤ 300 (se conservan los ceros) |
| `pasajeros_por_viaje` | promedio de `numeropasajeros` por viaje | `limpios` (duración 30–360 min, pasajeros 1–300) |
| `carga_max` | mediana de la ocupación máxima por viaje (`conteo_viajes.ocupacion_max`) | viajes limpios con contadores consistentes (`ocupacion_min` ≥ −3) |
| `viajes_validos` | número de viajes válidos que salen en la franja | viajes válidos |

## Validación temporal (obligatoria)
- **12 pliegues**: cada mes de 2025 es un conjunto de prueba; el entrenamiento usa todos los datos estrictamente anteriores a ese mes.
- **Dos horizontes**: `h=1` (se permiten rezagos de 1 día o más: pronóstico para mañana) y `h=7` (solo rezagos de 7 días o más: pronóstico para la programación de la próxima semana).
- Semilla fija (`random_state=42`). `n_jobs ≤ 2` para no bloquear el equipo. Tiempo máximo por experimento: 40 minutos.

## Líneas base obligatorias
- **B1 manual**: promedio de las 8 semanas anteriores, misma ruta, hora y día de la semana (lo que hace Sobusa hoy).
- **B2 ingenua**: el valor de hace 7 días.
- **B3 perfil**: promedio histórico por ruta × hora × tipo de día × mes.

## Métricas
- `MAE`, `RMSE`, `WAPE` = Σ|error| / Σ real (la principal), devianza de Poisson para conteos.
- Desagregadas por ruta, por tipo de día (laboral, sábado, domingo/festivo) y por franja (4–8, 9–15, 16–21 h).
- **Métrica de decisión**: buses necesarios por hora = ⌈carga_max prevista / (capacidad 50 × factor de carga objetivo 0,85)⌉ comparado con el mismo cálculo sobre el valor real; se reporta el error medio en buses y el % de horas con sub-oferta (buses previstos < reales).

## Salidas de cada experimento (carpeta `experimentos/<nombre>/`)
- `run.py` reproducible (`python run.py` desde la carpeta del proyecto) y los módulos que necesite.
- `resultados.json`: `{experimento, descripcion, variantes: [{nombre, horizonte, metricas_global, metricas_por_ruta, metricas_por_tipo_dia, notas}], mejor_variante, tiempo_s}`.
- Figuras PNG con títulos en español y `README.md` con hallazgos (en español, con cifras).
- Predicciones de la mejor variante para 2025 en `predicciones_2025.parquet` (ruta, dia, hora, real, prediccion, horizonte).
