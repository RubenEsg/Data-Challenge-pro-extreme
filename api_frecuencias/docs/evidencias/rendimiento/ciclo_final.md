# Ciclo diario con el código final: alertas observadas de cada día del lote, foto por segmento y plan con más detalle

Medido el 2026-11-13 a las 22:24 con `scripts/medir_ciclo.py`, con la misma secuencia y los mismos cortes de `ciclo_dimensiones_plan.md`: carga inicial hasta el 30-08-2025, día nuevo 31-08 y repetición. Corrió con el código final (migraciones 0001 a 0014) en una base local desechable y sobre una copia temporal de `datos/`. El JSON completo, con el resultado normalizado y su SHA-256, está en `ciclo_final.json`. No corría ninguna otra batería. Es la tercera medición con el mismo resultado: las del 11-11-2026 a las 06:36 y a las 06:39, antes de los arreglos del 13-11 (contraste por segmento, lectura `demanda_segmentos` y política de reentrenamiento), dieron 27,4 y 27,1 s, 20,5 y 20,6 s, y 0,1 y 0,2 s, con el mismo SHA-256 total. Esos arreglos no cambian este ciclo: la fuente es la serie empaquetada.

Qué hace el ciclo que no hacía en la medición anterior (9-11-2026, 07:29):

1. **Alertas observadas de cada día del lote.** Las reglas observadas (ALT-002 observada, ALT-005 a ALT-009 y la ruptura de comportamiento) evalúan hasta `VENTANA_OBSERVADA_DIAS` = 7 días del lote, cada uno con sus horas cerradas. En la carga inicial evalúan del 24 al 30-08-2025: 357 horas de las tres rutas en vez de 51. Abren 26 alertas observadas en vez de 3 (ALT-002 20, ALT-006 1 y ALT-007 5). El día nuevo evalúa solo el 31-08 (51 horas), como antes.
2. **Foto de variables por segmento y sentido (§7.3 paso 4).** Cada ejecución con predicciones guarda 1.170 filas de la foto: 12 de la ruta y 1.158 por segmento, con el modelo de segmentos activo `seg_hgb_jerarquico_20230227_s42`. Antes guardaba 12.
3. **Marcas de agua por ruta (migración 0009) y ocupación por segmento (migración 0011).** El ciclo guarda la marca de cada ruta y pide la ocupación de las 51 franjas. La serie empaquetada no trae viajes por segmento, así que no guarda filas de ocupación (`metricas.ocupacion_segmentos`: «la fuente no expone viajes por segmento (modo offline)»). Los consolidados de Extreme quedan «sin_fuente» por la misma razón.
4. **Plan del día con más detalle.** Cada hora del plan guarda además el headway vigente de `rutas.frecuenciadespachos` (migración 0010), la flota con el ciclo, la ocupación histórica y los componentes del costo. La versión de umbrales de esta base es la 9. La foto de la respuesta sigue reutilizando los tres planes del ciclo (`metricas.respuesta.planes_reutilizados`).

## Duración por corrida (segundos de la petición)

| Corrida | Filas leídas | Anterior (9-11, 07:29) | **Final (13-11, 22:24)** | Medición del 11-11 (06:36) |
|---|---:|---:|---:|---:|
| carga_inicial | 49.623 | 24,1 | **27,5** | 27,4 |
| dia_nuevo | 51 | 21,4 | **20,7** | 20,5 |
| repeticion | 0 | 0,1 | **0,2** | 0,1 |

## Duración por etapa (anterior → final, segundos)

| Corrida | lectura_incremental | calidad | prediccion | alertas | notificaciones | plan_dia (plan + foto) |
|---|---:|---:|---:|---:|---:|---:|
| carga_inicial | 0,2 → 0,3 | 4,3 → 4,2 | 1,2 → 1,4 | **16,3 → 18,9** | 0,0 → 0,0 | 2,0 → 2,7 |
| dia_nuevo | 0,1 → 0,1 | 1,0 → 0,8 | 1,0 → 1,0 | 17,2 → 16,0 | 0,0 → 0,0 | 2,2 → 2,8 |
| repeticion | 0,0 → 0,1 | 0,1 → 0,0 | — | — | — | — |

En la medición del 11-11-2026 a las 06:36 (la versión de `ciclo_final.json` del commit 5a59c1f) las etapas fueron casi las mismas: alertas 18,9 y 15,8 s, y plan del día 2,8 y 2,8 s.

## Lectura

- **La carga inicial tarda 3,4 s más (de 24,1 a 27,5 s) porque hace más trabajo.** La etapa de alertas pasa de 16,3 a 18,9 s: evalúa 7 días observados en vez de uno y abre 27 alertas en vez de 4. La del plan del día pasa de 2,0 a 2,7 s, con el detalle nuevo de cada hora.
- **El día nuevo no se encarece: 20,7 s frente a 21,4 s.** Su lote es de un día, así que las observadas evalúan las mismas 51 horas que antes. La mayor parte de la etapa de alertas sigue siendo la serie diaria de la ruptura de comportamiento (RF-009), unos 5 s por ruta según el registro del ciclo («serie diaria de … en x s»).
- La foto por segmento (1.158 filas más por ejecución) casi no se nota en la etapa de predicción: de 1,2 a 1,4 s en la carga inicial y 1,0 s en el día nuevo, como antes.
- La repetición sin filas nuevas sigue en una fracción de segundo y no escribe nada.
- Todo corre en la cola, en segundo plano (§7.1), y los GET solo leen lo guardado.

## Qué cambia en el resultado

- **Predicciones: no cambian.** El SHA-256 del resultado normalizado de las 18 predicciones es el de la medición anterior y el de `ciclo_dimensiones_plan.json` (`879d8ab2…e90601`).
- **Recomendaciones: las mismas 120 filas (18 de franja y 102 horas del plan del día), con el detalle nuevo.** Todas pasan de la versión de umbrales 5 a la 9 y traen `frecuenciadespachos_min`. En 5 de las 102 horas del plan el MILP da una salida más o una menos; por ejemplo, CL 72 a las 5 h del 1-09 pasa de 13 a 14 salidas. La hora de las 4 de SILENCIO del 31-08, con 0,2 minutos operados, pasa de «no viable», con 501 vehículos, a viable, con una salida y 2 vehículos. `vehiculos_requeridos` cambia en 19 horas del plan.
- **Alertas: 36 en vez de 14.** La carga inicial abre 27 (antes 4) por la ventana de 7 días. El día nuevo abre 9 (antes 10): ya no sale la ALT-003 de pronóstico de CL 72 de las 6 h del 1-09. Desde la migración 0014, ALT-003 exige además una probabilidad mínima de sobrecarga (`alt003_probabilidad_minima` = 0,30).
- **Historial de alertas:** 36 entradas, una «crear» por alerta.
- **SHA-256 total del resultado:** `8f1ae29f4b177a600cf5728790f5055242d6724c5f87362ce3201134e9b08da9`, el mismo en las tres mediciones (11-11 a las 06:36 y a las 06:39, y 13-11).

`python scripts/medir_ciclo.py --comparar <anterior> docs/evidencias/rendimiento/ciclo_final.json` lista estas diferencias; la medición anterior es la versión de `ciclo_final.json` del commit bb7a612.

Reproducir: `TEST_DATABASE_NAME=<base local desechable> CATALOGOS_DATOS_DIR=<datos/ de la raíz> python scripts/medir_ciclo.py --etiqueta final_plan_reutilizado --salida docs/evidencias/rendimiento/ciclo_final.json`. Sin `CATALOGOS_DATOS_DIR` el ciclo no tiene los viajes del día: dos alertas ALT-006 salen con `identificacion_5_3.resultado` = «fuente_sin_viajes», sin viaje ni vehículo, y el SHA-256 total cambia (`eb9cf7d3…bee00c`); todo lo demás es igual.
