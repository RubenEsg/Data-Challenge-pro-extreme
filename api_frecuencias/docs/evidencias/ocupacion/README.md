# Evidencias: ocupación por segmento, histórica y actual (§10.1)

Método y decisiones: `docs/ocupacion_segmentos.md`. Código: `app/servicios/ocupacion.py`.

| Archivo | Qué muestra | Cómo se regenera |
|---|---|---|
| `perfil_ocupacion_segmentos.md` / `.json` | Perfil histórico por segmento × día de operación × hora (ene-feb 2023). Incluye la validación del método contra la ocupación máxima del dispositivo en los mismos viajes, la comparación con el factor de carga 2025 y con el mismo factor del dispositivo en ene-feb 2023, la cobertura del factor 2025 por día de la semana y el segmento crítico de las horas pico laborales | `python scripts/preparar_ocupacion_segmentos.py --origen ../../datos` |
| `backtest_restriccion_reactiva.md` / `.json` | Efecto de la restricción reactiva con datos reales: persistencia de la sobreocupación, salidas que agregaría, horas y pasajeros sobre la ocupación crítica con y sin la regla, y su efecto sobre el plan del día con el camino real del código. Estas cifras usan la hora cerrada con todos sus viajes completos (cota superior). La sección «En tiempo real» repite la medición con los viajes todavía en curso, como en un ciclo intradía a las (h+1):05 y (h+1):30 | `python scripts/backtest_ocupacion_reactiva.py --origen ../../datos --plan` |
| `planificador_intradia.txt` / `.json` | El ciclo intradía en la operación PROGRAMADA (10.1-d): el planificador real (APScheduler) y la cola real, sin POST, en un día comprimido (8:05, 9:05, 10:05 y 11:05, con la franja del `PLAN_INTRADIA_CRON` por omisión). Cada franja se encola una vez aunque otra réplica la dispare; cada ciclo lee solo la hora que llegó; la restricción reactiva actúa a las 8 y a las 9 h en el plan del día en curso y en las recomendaciones de 30 y 60 min, y deja de actuar cuando la ocupación baja del umbral. La ALT-002 del episodio de las 7 y 8 h sale a las 9:05 en el segmento crítico, con la hora de las 7 que midió y guardó el ciclo anterior. Trae la duración y lo escrito por cada ciclo, y la latencia de una consulta paginada con un ciclo en curso (RNF-002). La captura en vivo y los viajes por segmento son de prueba | `PRUEBA_PLANIFICADOR=1 GENERAR_EVIDENCIAS=1 pytest tests/integracion/test_planificador_programado.py` (corre `scripts/evidencia_planificador_intradia.py`) |
| `ciclo_intradia_fuente.md` / `.json` | Carga en la base de Extreme de un ciclo intradía frente al ciclo diario, medida en la réplica local como `lector_ia` (solo lectura): cada lectura del ciclo, la estimación por ciclo y por día con el cron por omisión, y la proyección al histórico completo sin los índices de H12 | `python scripts/medir_ciclo_intradia.py` (réplica local) |

El perfil queda versionado en `datos/ocupacion_segmentos_hora.parquet` y lo lee la API.

Las exportaciones (`timbradas_segmentos`, `rutas_segmentos`, `progvehiculos`, `conteo_viajes`, `rutas` y
`estacionalidades_anio`) están en la carpeta `datos/` de la raíz del checkout, que es git-ignorada. Ninguno de los
scripts consulta la base del reto: `medir_ciclo_intradia.py` lee la réplica local en solo lectura y
`evidencia_planificador_intradia.py` usa una base local desechable.
