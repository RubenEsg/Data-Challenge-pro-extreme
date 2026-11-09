# Ciclo diario: tiempo antes y después de la optimización

**Qué se midió.** El ciclo diario completo (`POST /api/v1/frequency/executions`) con cortes fijos, igual que la
demostración de §14.2:

1. **carga inicial**: todo el histórico hasta el 30-08-2025 (49.623 filas), sin marca de agua;
2. **día nuevo**: el 31-08-2025 (51 filas, solo lo posterior a la marca de agua);
3. **repetición** del mismo corte (0 filas nuevas).

Cada corrida usa una base PostgreSQL local nueva (migraciones 0001 a 0005), una copia temporal de `datos/` y la serie
empaquetada como fuente. Script: `scripts/medir_ciclo.py`. Cifras: `ciclo_antes_despues.json` (esta carpeta).
Perfiles de cProfile (25 funciones con más tiempo, acumulado y propio): `perfil_ciclo_antes.txt` y
`perfil_ciclo_despues.txt`.

Equipo: portátil de desarrollo (Windows 11, 6 núcleos lógicos, Python 3.13.3, scikit-learn 1.5.2, PuLP 2.9.0 con CBC),
con otros procesos en marcha. Por eso los segundos cambian de una corrida a otra; los conteos de llamadas del
perfilador no dependen de la carga del equipo.

## Dónde se iba el tiempo

El perfil de la versión 8d4e651 (`perfil_ciclo_antes.txt`, 183,3 s bajo cProfile) muestra dos focos:

| Foco | Llamadas | Tiempo bajo cProfile | Causa |
|---|---:|---:|---|
| expresión generadora de `contexto_observado` (app/servicios/ejecucion.py) | 944.079 | 87,7 s propios | para hallar los días completos del lote, por cada (fecha, hora) recorría otra vez todo el lote: costo cuadrático; en la carga inicial son unas 16.500 horas por ruta |
| `optimizacion.recomendacion_franja` | 18 (24 solucionadas con CBC) | 4,0 s acumulados | se resolvía una vez por horizonte aunque los tres horizontes de la ruta cayeran en la misma franja, con la misma demanda por hora y la misma banda |

## Qué se cambió (sin cambiar resultados)

- **Días completos en una pasada** (`_dias_completos`): las horas de servicio de cada día se cuentan con un
  `Counter` sobre el lote. El conjunto de días es el mismo; el costo pasa de cuadrático a lineal.
- **Una recomendación por ruta y franja en cada ejecución** (`_RecomendacionesDeLaEjecucion`): la clave es (ruta,
  fecha, hora, demanda por hora, P90 y P10 de la franja). Si dos horizontes coinciden, el segundo recibe una copia
  del resultado ya resuelto, con su propia `franja_prediccion`; si el optimizador falla, el error no se guarda y se
  registra en cada horizonte, como antes. Se siguen guardando 9 recomendaciones por ejecución (una por predicción).
- El resto de la recomendación ya se reutilizaba: los parámetros de la franja, los factores de carga y las tipologías
  se leen una vez por proceso (`lru_cache`); después del cambio, `recomendacion_franja` tarda unos 0,1 s por franja,
  casi todo en la llamada a CBC.

## Resultados

Segundos de la petición `POST /api/v1/frequency/executions` (la ejecución se procesa en la misma petición):

| Corrida | Versión 8d4e651 | Antes | Después |
|---|---:|---:|---:|
| Carga inicial (49.623 filas) | 94,5 | 109,8 | **27,7** |
| Día nuevo (51 filas) | 18,9 | 12,2 | **7,9** |
| Repetición (0 filas) | 0,2 | 0,2 | 0,1 |

«Antes» es el mismo código que «después» salvo los archivos de este cambio; sirve para aislar el efecto y comparar
resultados. La versión 8d4e651 es la anterior a otros ajustes posteriores de las reglas de alertas, y por eso
produce otras alertas.

Etapas de la carga inicial (segundos; la etapa «calidad» va desde la validación hasta el monitoreo, e incluye la
evaluación del error del modelo):

| Etapa | Versión 8d4e651 | Antes | Después |
|---|---:|---:|---:|
| lectura incremental | 0,3 | 0,3 | 0,4 |
| calidad, histórico, evaluación y monitoreo | 10,3 | 26,8 | 7,6 |
| predicciones y recomendaciones | 3,3 | 7,9 | 5,4 |
| alertas (de pronóstico y observadas) | **80,2** | **74,6** | **14,0** |
| notificaciones y cierre | 0,4 | 0,2 | 0,2 |

Bajo cProfile, el total del ciclo pasa de 183,3 s a 21,3 s; la expresión generadora cuadrática desaparece (las
expresiones generadoras de ejecucion.py suman 0,03 s), `recomendacion_franja` baja de 18 a 6 llamadas y las
soluciones con CBC de 24 a 8.

Una segunda corrida de cada versión, con el equipo más cargado, da el mismo orden de magnitud. Las corridas están en
`ciclo_antes_despues.json`, con las claves `*_repeticion`:

| Corrida | Versión 8d4e651 | Antes | Después |
|---|---:|---:|---:|
| Carga inicial | 157,2 | 125,4 | **10,8** |
| Día nuevo | 24,0 | 9,6 | **5,6** |
| Repetición | 0,2 | 0,1 | 0,2 |

## Mismos resultados

`medir_ciclo.py` guarda las predicciones, recomendaciones, alertas e historial de alertas de las tres ejecuciones,
sin identificadores, sin marcas de tiempo del reloj y sin latencias, y calcula su SHA-256:

- antes: `ab003a1fa8f15299501c0f79a68160c560f048e2e7ac86b30d532cacc2ee831b` (18 predicciones, 18 recomendaciones,
  16 alertas, 16 registros de historial);
- después: el mismo SHA-256, también en la corrida bajo cProfile y en la segunda corrida;
- `python scripts/medir_ciclo.py --comparar antes.json despues.json` da «resultado idéntico (SHA-256): True» y
  métricas de las tres ejecuciones iguales.

## Lo que queda

El costo que queda está en la inferencia. Cada ejecución pide 51 pronósticos horarios para las alertas observadas
(17 horas por ruta) y cada uno ejecuta tres modelos de 400 árboles sobre una o dos filas (en los perfiles, 120
llamadas a `inferencia.predecir`, 396 a `predict` y 158.400 recorridos de árbol). Además, la carga inicial evalúa
el error del modelo activo sobre todo el histórico. Un pronóstico por lotes (todas las horas del día de una ruta en
una sola llamada a los modelos) ahorraría la mayor parte de esos segundos sin cambiar el resultado.

## Cómo repetirlo

```
python scripts/medir_ciclo.py --etiqueta despues --salida despues.json [--perfil perfil.txt]
python scripts/medir_ciclo.py --etiqueta antes --raiz <copia de la API sin el cambio> --salida antes.json
python scripts/medir_ciclo.py --comparar antes.json despues.json
```

El script solo acepta un servidor PostgreSQL local y una base cuyo nombre empiece por `ai_frecuencias_pruebas`
(la borra y la crea en cada corrida); nunca escribe en `datos/`.
