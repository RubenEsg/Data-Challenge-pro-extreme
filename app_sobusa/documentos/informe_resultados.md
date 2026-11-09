# Informe de resultados: ¿cuántos buses despachar y cada cuánto? (Sobusa, rutas SILENCIO, CRA 54 y CL 72)

Equipo Data Challenge Pro Extreme 2026, Universidad del Norte. 13 de octubre de 2026 (sexta versión: el plan con costos con fuente en el motor y la consola de tiempo real, el modelo persona a persona de la vista 3D con todo 2025, el piloto para medir β y la propuesta para Sobusa; la quinta añadió la limpieza de datos y el objetivo corregido, E13; la cuarta, la comparación de 51 modelos, la simulación de ahorro por fecha con conductores, la consola de despacho v2 y la investigación internacional). Cada cifra, verificada por revisores independientes, cita el experimento que la produjo (E1–E13 demanda, D1–D6 despacho, P1 planificador, P2 piloto; carpetas en `experimentos/`), el módulo de costos (`costos/`), la simulación de ahorro (`simulacion_ahorro/`), el prototipo de tiempo real (`sistema_tiempo_real/`) o el análisis exploratorio (EDA). M COP = millones de pesos.

## 1. Resumen ejecutivo

1. **El problema.** Sobusa programa cada ruta y hora con una regla manual: el promedio de las ocho semanas anteriores, mismo día y hora. De 2023 a 2025 la demanda cayó un 8 % al año, de 15,31 a 12,87 millones de pasajeros, con casi la misma flota en la calle (EDA, D2).
2. **Qué se construyó.** Un pronóstico por ruta, día y hora de salida; una medición de cuántos pasajeros se pierden cuando salen menos buses; un optimizador de salidas por hora; un simulador de la operación; un planificador interactivo; un módulo de costos con fuente y su calculadora, un simulador de ahorro por fecha con los conductores necesarios, y un prototipo de despacho en tiempo real con su consola y una vista 3D del día real y del mismo día con nuestro plan; además, el diseño de un piloto para medir β en la calle y una propuesta de dos páginas para Sobusa (punto 10). Revisores independientes recalcularon los 19 experimentos y los tres módulos nuevos.
3. **Precisión.** A una semana, la regla manual se equivoca en 20,0 de cada 100 pasajeros (WAPE 20,0 %) y el modelo final en 13,9 (E11); a cuatro semanas, en 14,4. Calendarios escolares, clima y modelos por ruta no aportan: basta un modelo para las tres rutas (E6, E9, E11). Al ampliar la comparación a 51 candidatos (otros árboles, redes neuronales, modelos fundacionales como TimesFM de Google y Chronos de Amazon, clásicos y combinaciones), ningún modelo solo supera al LightGBM; combinar familias sí. El recomendado para producción es el híbrido LightGBM + Chronos-2: 13,6 %, con una mejora que se repite en 2024 (E12). Lo que más mejora el plan, sin embargo, es pronosticar lo que de verdad sube a los buses, incluidos los viajes marcados como cancelados que sí corrieron (7,7 % de los pasajeros de 2025). Con ese objetivo, el error del total diario baja de 8,1 % a 5,0 % y las horas con buses de menos pasan del 44 % al 27 % (E13).
4. **La demanda responde a la oferta.** Con 10 % menos salidas en una franja se pierde cerca del 7 % de sus pasajeros (elasticidad β ≈ 0,70, rango creíble 0,55–0,90; E7). En 2026 Sobusa registró 14,6 % más viajes y 7,5 % más subidas que en las mismas fechas de 2025, tras tres años de caída: coherente con lo anterior, aunque sin confirmar (E8).
5. **Cuánto cuesta operar.** Con precios de 2026 y fuentes públicas, cada km que un bus deja de recorrer ahorra unos 1.990 COP (ACPM 898, mantenimiento 736, llantas 231, lubricantes 126) y cada bus-hora, 26.400 COP de conductor si se le paga por hora (nada si se le paga por producido). En 2025 las tres rutas recorrieron 10,4 millones de km con unos 830.000 galones de ACPM (7.600 t de CO2) y costaron unos 45.800 M COP a precios de 2025 (`costos/`).
6. **Recortar no paga; reasignar mejora el servicio al mismo costo.** Con esos costos, β = 0,70 y la contabilidad conservadora (solo cuenta pasajeros perdidos), la regla de recorte S1 pierde 1.713 M COP al año, y el optimizador D5, que con los supuestos iniciales recortaba el 9,6 % de las horas de bus en operación (buses-hora), pierde 1.029 M: lo que ahorra en operación (3.695 M) no cubre los pasajes perdidos (4.724 M). D5 deja de pagar con β mayor que 0,53, no 0,85 como con los supuestos. Solo quedan positivos D5 con intervalo máximo de 15 min entre buses (+390 M COP) y el giro corto en el punto 35 de CRA 54 (+248 M). Reoptimizado con los costos con fuente, D5 ya no recorta: mantiene los buses-hora de hoy (−0,5 %) y pasa salidas de los valles a CL 72 y a la franja de 13 a 15 h, con menos espera (4,43 → 4,30 min) y menos sobrecarga (317 → 267 pasajeros al día) (`costos/`). La simulación de cada fecha de 2025 lo confirma: el único recorte que paga es el de domingos y festivos (+181 M COP al año con pago por hora), y cuesta unos 3.800 pasajeros en riesgo por domingo (`simulacion_ahorro/`).
7. **El precio es la ocupación.** Con sus supuestos, D5 deja 530 pasajeros al día por encima de la capacidad (317 hoy); con una penalidad de 30.000 COP deja 264 y aún ahorra 1,7 % (D5). El simulador confirma en CRA 54 un 12,1 % menos de buses-hora sin cambio significativo en la espera, pero con buses más llenos y sin bajar los buses del pico (D6).
8. **Despacho en tiempo real.** Un motor que cada pocos minutos lee el estado del día sin mirar al futuro, da la hora exacta de las próximas salidas y avisa de huecos, buses llenos o pegados y fallas de datos; se probó en 79 días de 2025 como si fueran en vivo y se muestra en una consola. Corregir la demanda con lo visto en el día no mejora el pronóstico (WAPE a las 12 h: 14,25 % → 14,27 %) ni las decisiones: con el plan que reasigna (corrida del 13 de octubre), el plan semanal queda a 1,05 salidas por hora del óptimo conocida la demanda que llegó y acierta el 54 % de sus horas, el motor queda a 1,08, y la oferta real de 2025 a 2,8 salidas por hora con el 14 % de horas exactas (con el D5 original y sus supuestos: 0,56 y 70 % el plan, 0,61 el motor, 2,61 y 15 % la oferta real). El valor del tiempo real está en ejecutar bien el plan, no en cambiar cuántos buses salen (`sistema_tiempo_real/`).
9. **Decisiones para Sobusa.** Adoptar el plan semanal optimizado con costos reales y una penalidad por hacinamiento, usando el planificador (P1); reasignar en vez de recortar; fijar el intervalo máximo, que decide CL 72; confirmar β con un piloto, porque pesa más que cualquier precio; despachar con la consola, primero en modo sombra; entregar costos reales (combustible, mantenimiento y forma de pago del conductor) y aclarar los datos: el 82 % de los viajes marcados como cancelados sí recorrió la ruta (E7), y según los registros los conductores regulares suman unas 247 h en ruta al mes, por encima de las 182 h de la jornada ordinaria de 2026, algo que hay que confirmar (`simulacion_ahorro/`).
10. **Lo nuevo del 13 de octubre.** El motor y la consola de tiempo real ejecutan ya el plan de D5 con los costos con fuente (26.400 COP por bus-hora de conductor, 1.991 por km, tarifa neta 3.182, e = 0,5), el que reasigna en vez de recortar, y los 353 días de demostración se regeneraron con él; el backtest con ese plan y su oráculo ya corrió (sección 6): el plan queda a 1,05 salidas por hora del óptimo y el motor a 1,08, con los mismos buses-hora que la operación real (−0,2 %), menos espera (4,99 frente a 5,16 min) y menos sobrecarga (68 frente a 107 pasajeros al día). La vista 3D muestra el mismo día persona a persona con nuestro plan y deja un hallazgo: visto día a día, el plan recorta las tardes de CRA 54, los domingos y los festivos más de lo que sugiere su promedio anual (el martes 3 de junio pone 507 salidas frente a 600 reales, 548 válidas, y de 17 a 19 h en CRA 54 10 / 9 / 7 frente a 15 / 19 / 14 válidas; el domingo 8 de junio, 234 frente a 402), y como el modelo asigna la demanda real a los buses del plan sin limitar el cupo, las personas por encima de 50 a bordo pasan de 516 a 3.838 el 3 de junio y ese día pierde 5.879 pasajeros (−4,1 M COP con la contabilidad conservadora). D5 no lo ve porque reparte la carga de la hora entre los buses de la hora: es un hallazgo para el equipo (una restricción de cupo o una penalidad mayor en el optimizador) y refuerza el piloto (`sistema_tiempo_real/README.md`, «El mismo día con nuestro plan»). Sumados con ese modelo los 353 días de 2025 con GPS (`resumen_calles.py`), el plan pone 451 salidas por día frente a 491 reales (452 válidas), ahorra 3,9 M COP de operación al día (−3,8 %) y pierde 4.092 pasajeros al día (10,7 %: 3.130 por la regla de β y 962 que no encuentran bus del plan en 20 minutos), con 2.742 personas al día sobre la capacidad frente a 388 y la espera media de 3,53 a 4,07 minutos: saldo del año de −3.212 M COP con la contabilidad conservadora y de +2.312 M con la simétrica (el mismo orden que la sección 4.3: −2.825 y +1.600 M), negativo en 231 de los 237 días laborales y positivo en 57 de los 65 domingos y festivos (+5,1 M al día), los únicos que pagan con la cuenta conservadora. El piloto P2 mide β en la calle: 8 semanas en CRA 54 y CL 72 por días alternos sorteados, error estándar 0,066 y potencia 0,89 para distinguir 0,70 de 0,53, con 22.904 pasajeros en riesgo (0,30 % del año de CRA 54) y un saldo entre −52 y +22 M COP. Y `propuesta_sobusa.md` lo resume en dos páginas para la gerencia: los mismos buses, mejor repartidos; la consola primero en modo sombra; el piloto; un cronograma de 12 semanas.

## 2. Datos y método

**Fuentes.** 1.096 días de 2023–2025: `progvehiculos` (520.639 viajes válidos, 42,17 millones de pasajeros), 175,9 millones de eventos GPS resumidos y catálogos, limpiados con las reglas R1–R9 del EDA; además, agregados de Sobusa de enero a agosto de 2026 (E8), lluvia horaria de Open-Meteo (E9) y prensa y calendarios escolares y universitarios (E10). Sin nuevas consultas al servidor.

**Actualización del 2 de noviembre de 2026 (`insumos_sobusa/`).** Los organizadores entregaron el reporte de flota de Sobusa (643 vehículos con sentados y de pie; se versiona sin sus datos personales) y los scripts de segmentación de Extreme. La capacidad de 50 pasajeros que usan D1 y D5 se confirma con ese reporte: de los 418 vehículos que corrieron en 2025 en las tres rutas, 417 traen capacidad, con mediana 50 (33,5 sentados y 18,4 de pie en promedio), así que ningún resultado cambia. El campo `apto_estadisticas_historicas` de `progvehiculos` es True en todas las filas de las tres rutas y no discrimina, de modo que la regla de validez propia (finalizado = S y cancelada = N) se mantiene; y el último día de cada mes de 2025 sigue sin eventos de conteo en la base salvo el 31 de enero (comprobado ese día), por lo que E3 y el replay siguen excluyendo esos días.

**Costos.** Sobusa no entregó costos, así que se construyeron con fuentes públicas a precios de 2026: ACPM de la CREG, tarifa y descuentos del AMB, salario mínimo y jornada de 42 h semanales (Ley 2101 de 2021), y estudios de costos del transporte urbano para mantenimiento, llantas y lubricantes. El rendimiento (12,6 km/gal) se estimó por tipo de bus porque la base no registra consumo (`costos/`).

**Protocolo.** Cada mes de 2025 se pronostica por ruta × día × hora de salida entrenando solo con lo anterior (12 pliegues), a uno y a siete días (h = 1, h = 7), frente a la regla manual (B1). WAPE = suma de errores absolutos ÷ suma de pasajeros reales.

**Verificación.** Primera ronda (E1–E5, D1–D4): 9 de 9 utilizables, 26 cifras corregidas. Segunda ronda (E6–E11, D5, D6, P1): 9 de 9 confiables con reservas; por ejemplo, D5 se resolvió de nuevo con otra formulación y otro programa (1.093 de 1.095 ruta-días idénticos) y β se reprodujo exactamente desde los datos crudos. Una afirmación de E9 se refutó y no hay fugas de información. Tercera ronda (módulo de costos y prototipo de tiempo real): ambos confiables con reservas. Se corrigieron la jornada del conductor (182 h al mes en 2026, no 190), la conexión de β en la calculadora y tres fallas menores del motor en tiempo real.

**Una sola escala para la elasticidad.** **β** es la elasticidad de los pasajeros **totales** al número de salidas: con 10 % menos salidas, una franja pierde β × 10 % de sus pasajeros (β = 0: demanda cautiva; β = 1: cada bus que falta se lleva sus pasajeros). D5 y el planificador usan esta definición (allí se llama e; 0,5 por defecto, de la literatura: TCRP Report 95). D1 usaba la escala inversa por viaje, e = 1 − β: su equilibrio de 0,46 es β = 0,54 y su caso "pesimista" de 0,22 es β = 0,78, y así se citan aquí. Importa porque, si β es alto, cada bus que se quita pierde pasajes y pasajeros que se van a otras empresas o al mototaxi.

## 3. Qué tan bien se puede pronosticar la demanda

**Tabla 1. WAPE de pasajeros por ruta × día × hora de salida a una semana (h = 7), 12 pliegues de 2025**

| Método | WAPE | Diferencia frente a E1, en puntos [IC 95 %]¹ | Fuente |
|---|---|---|---|
| B1 regla manual (práctica actual) | 20,04 % | +5,65 [+4,38; +7,24] | E11 |
| **E1: LightGBM (árboles de decisión) con calendario y demanda reciente** | **14,40 %** | — | E1 |
| E1 + calendarios escolar y universitario | 14,35 % | −0,05 [−0,13; +0,03] | E11 |
| E1 + calendarios + lluvia típica del mes y la hora | 14,32 % | −0,08 [−0,15; 0,00] | E11 |
| E1 + lluvia observada del mismo día (no se conoce con una semana) | 14,63 % | +0,23 [+0,12; +0,36] | E9 |
| Un modelo por ruta en lugar de uno conjunto | 14,25 % | −0,14 de media mensual (p = 0,36) | E6 |
| E1 + demanda reciente de las otras rutas | 14,42 % | +0,01 de media mensual (p = 0,70) | E6 |
| **Modelo final: E1 con menos peso a días atípicos y franjas sin registro** | **13,94 %** | **−0,46 [−0,60; −0,33]** | E11 |

¹ IC 95 %: intervalo de confianza; si incluye el 0, la diferencia puede ser azar. p: probabilidad de verla por azar.

Otros métodos quedan en la misma banda: estadística clásica 14,3 %, cuantiles 14,6 % y cuatro plantillas de día tipo 14,9 % (E3–E5). El modelo final se equivoca 11,5 % en CRA 54, 15,5 % en SILENCIO y 19,1 % en CL 72, y 19,7 % en domingos y festivos frente a 48,6 % de la regla manual (E11).

**Qué importa.**

- **Lo único que mejora es no aprender de datos corruptos**: el modelo final da menos peso a 31 días atípicos (paro, aguaceros, transición al Sibus, fallas de datos; E10) y a las franjas con viajes sin registro. La ganancia viene sobre todo de agosto de 2025 (sin agosto, −0,21 puntos) y cuesta un leve exceso de pronóstico (+1,4 %) (E11).
- **La antelación casi no cuesta**: a 7, 14, 21 y 28 días el modelo final da 13,9 / 14,1 / 14,3 / 14,4 % y la regla manual 20,0 / 20,5 / 20,9 / 21,2 % (E11).
- **Basta un modelo conjunto**: las tres rutas correlacionan 0,97 día a día y el 95,1 % de sus desvíos es un choque común, casi todo calendario (E6).
- **El calendario explica las caídas grandes**: la regla manual falla en festivos (145,8 % de error frente a 25,0 % del modelo; E1). De los 58 días ordinarios con las tres rutas más de 10 % abajo, la mitad fueron vacaciones escolares o universitarias y 15 coincidieron con la transición al Sibus de 2024; el 6 de septiembre de 2024 (−82,8 %) hubo bloqueos de conductores tras el asesinato de un conductor (E10).
- **La lluvia casi no mueve la demanda**: explica el 1,9 % de la variación diaria; con 5–10 mm/h hay 1,8 % menos pasajeros, pero la vuelta tarda 2,7 % más, así que se necesitan los mismos buses. No conviene cambiar el plan por el pronóstico del tiempo ni retirar buses en un aguacero (E9).

**Validación con 2026 (E8).** El modelo de largo plazo, que había pronosticado 2025 con 1,4 % de error, se quedó 14,6 % corto en 2026 (1 de enero a 10 de agosto; todos los modelos, entre 7,2 % y 16,5 %). Es un error de nivel, no de forma: negativo en las 21 combinaciones de ruta y día de la semana, con festivos, Carnaval y Semana Santa dentro de ±8 %. Según los agregados de Sobusa, los viajes crecieron 14,6 % y las subidas 7,5 % frente a las mismas fechas de 2025, cuando habían caído 9,2 %. Falta confirmarlo con `progvehiculos` 2026, porque el aumento cae en los días corrientes, donde ya había una brecha inexplicada entre `timbradas` y `progvehiculos`. Si es real, hay que recalibrar el nivel del pronóstico.

**Comparación ampliada: 51 candidatos con el mismo protocolo (E12).** Mismos 12 meses de 2025, una semana de antelación, las mismas 18.615 franjas y el mismo tratamiento de días atípicos que el modelo final. La regla de selección se fijó antes de ver resultados: mejorar a E11 con IC 95 % por debajo de 0 y en al menos 7 de 12 meses. Los finalistas se repitieron en 2024 como prueba fuera de la muestra de selección.

**Tabla 1b. Mejores de cada familia y combinaciones (WAPE a una semana)**

| Candidato | WAPE 2025 | Diferencia con E11 [IC 95 %] | Meses mejor | Diferencia en 2024 |
|---|---|---|---|---|
| Regla manual (B1) | 20,04 % | +6,11 | — | — |
| TimesFM 2.5 de Google sin reentrenar, con calendario | 14,96 % | +1,02 [+0,67; +1,43] | 0/12 | +0,72 |
| Chronos-2 de Amazon sin reentrenar, con calendario | 14,71 % | +0,77 [+0,47; +1,14] | 2/12 | — |
| Mejor clásico (AutoETS con calendario; Prophet 14,67 %) | 14,62 % | +0,68 [+0,38; +1,04] | 2/12 | — |
| Mejor red neuronal (TFT; N-HiTS 15,17 %, CNN sobre la cuadrícula del año 15,06 %) | 14,19 % | +0,26 [+0,01; +0,50] | 5/12 | — |
| Otros árboles (XGBoost 13,94 %, CatBoost 14,01 %, LightGBM Tweedie 13,91 %) | 13,91–14,01 % | dentro del ruido | — | — |
| **Modelo final de E11 (LightGBM)** | **13,94 %** | — | — | (15,73 % en 2024) |
| Media de 5 árboles de boosting | 13,76 % | −0,18 [−0,23; −0,12] | 11/12 | — |
| **Híbrido LightGBM + Chronos-2 (recomendado)** | **13,62 %** | **−0,32 [−0,43; −0,22]** | 11/12 | **−0,33 [−0,50; −0,14]** |
| Media de E11 con el mejor de cada familia | 13,59 % | −0,35 [−0,48; −0,21] | 12/12 | −0,49 [−0,71; −0,26] |
| Apilamiento rodante de 40 modelos (ganador según la regla) | 13,39 % | −0,55 [−0,69; −0,41] | 12/12 | no probado (40 modelos) |

- **Ningún modelo solo supera a LightGBM.** Los otros árboles empatan, con diferencias del tamaño del ruido de cambiar la semilla. Las redes, los fundacionales y los clásicos quedan entre 0,3 y 4 puntos peor.
- **TimesFM de Google y Chronos, usados sin reentrenar, necesitan el calendario local:** sin él quedan entre 17,1 % y 18,4 %, porque fallan en los festivos (pronostican casi el doble) y los domingos. TimesFM no le gana a E11 en ningún mes.
- **La ganancia viene de combinar modelos que se equivocan distinto.** El ganador formal, un apilamiento de 40 modelos, no se pudo repetir en 2024, y un apilamiento parecido de 6 modelos no se sostuvo ahí (−0,23 [−0,49; +0,09]). Por eso se recomienda el híbrido: es la misma cadena de LightGBM con 4 columnas más, el pronóstico de Chronos-2 con calendario. Chronos-2 no se reentrena ni necesita GPU (unos 4 min de CPU por semana), y su mejora se repite igual en 2024.
- **Cautela:** escoger entre 51 candidatos en los mismos 12 meses infla un poco la ventaja del ganador. Por eso cuentan la corrección por comparaciones múltiples (la sobreviven los finalistas) y la prueba de 2024.

**Limpieza de datos: pronosticar lo que de verdad sube a los buses (E13).** El 20,8 % de los días de 2023–2025 tiene algún problema de datos. El más extendido es la marca `cancelada`: en el 18,8 % de los días, más del 10 % de los pasajeros viajó en buses marcados como cancelados que sí recorrieron la ruta. El objetivo usado hasta E12 (viajes válidos) deja fuera a esos pasajeros, y por eso el total real es 5,6 %, 6,7 % y 7,7 % mayor en 2023, 2024 y 2025.

**Tabla 1c. Objetivo corregido: todos los viajes que corrieron (2025; error contra lo que de verdad subió)**

| Modelo | WAPE | Error del total diario por ruta | Horas con buses de menos | Horas con el número exacto de buses |
|---|---|---|---|---|
| E11 sin corregir | 13,55 % | 8,1 % | 44,4 % | 35,7 % |
| E11 reescalado al objetivo corregido | 12,07 % | 5,5 % | 28,1 % | 39,4 % |
| E11 reentrenado con el objetivo corregido | 11,77 % | 5,2 % | 26,9 % | 40,3 % |
| **Híbrido con Chronos-2, objetivo corregido** | **11,38 %** | **5,0 %** | **27,0 %** | **41,4 %** |

- **Con el objetivo viejo el plan se queda corto de buses en el 44 % de las horas; con el corregido, en el 27–28 %.** Casi todo ese cambio es de nivel: el objetivo viejo subestima la demanda. Reentrenar con el objetivo corregido añade poco (−0,31 puntos de WAPE, o −0,15 con un reescalado más fino), y el híbrido añade −0,39 más. Las dos mejoras se repiten en 2024 (−0,41 y −0,41).
- **Rellenar los viajes sin registro, completar registros parciales o depurar más empeora.** Entre el 21 % y el 30 % de los viajes "sin registro" son registros duplicados: el mismo bus tuvo otro viaje real a menos de 90 minutos. La detección automática de anomalías rinde casi igual que la lista manual de E10.
- **Parte de la caída de la demanda era la marca.** Con el objetivo corregido, la caída anual es de 7,7 % (2024) y 7,1 % (2025), no de 8,6 % y 8,0 %.
- Un revisor independiente reprodujo las cifras y no encontró fugas.

**Modelo recomendado.** `experimentos/E12_comparacion_modelos/modelo_final_hibrido.py` entrena con 2023–2025 el LightGBM con las variables de Chronos-2 y pronostica cualquier fecha futura con 7, 14, 21 o 28 días de antelación.
- Corre en CPU: unos 2 minutos para cuatro semanas, más 4–6 minutos de Chronos-2 por cada semana nueva.
- Entrena en sombra el modelo de E11 como respaldo.
- En una simulación de uso real, con 11 orígenes de fin de mes de 2025 y cuatro semanas por delante cada uno, se equivoca 13,70 % frente a 13,99 % de E11 (−0,30 puntos [−0,45; −0,15]; mejor en 9 de 11).

`modelo_final.py` (E11) sigue disponible sin Chronos-2. Respaldo auditable en hoja de cálculo: las plantillas de E5. Para las primeras semanas de 2026 los dos pronostican de 11 % a 14 % menos que 2025, y quedarían cortos si se confirma el aumento de oferta de 2026 (E8). Reentrenar cada semana con los datos de 2026 corrige ese nivel.

## 4. De la demanda al despacho

### 4.1 Cuánto responde la demanda a la oferta (E7, E8)

27.754 viajes (4,9 %) se registraron y no salieron (menos de 20 km recorridos). Esas fallas no dependen de la demanda esperada ni se reponen: son un experimento natural.

**Tabla 2. Elasticidad de los pasajeros a las salidas (β)**

| Medición | β | Qué mide |
|---|---|---|
| Por hora | 0,73 (0,70–0,75) | pérdida en la hora; SILENCIO 0,67, CRA 54 0,66, CL 72 0,80 |
| Por ruta-día | 0,66 (0,54–0,78) | lo perdido no se recupera en el resto del día |
| Derrame | 0,80–0,90 | de 83,8 pasajeros esperados en el viaje que falló, los 4 buses siguientes recogen el 16,8 % |
| **Síntesis** | **0,70 (0,55–0,90)** | rango creíble |
| Literatura (TCRP Report 95) | ≈ 0,5 | promedio internacional |

Sobusa pierde más que el promedio de la literatura, probablemente porque compite en corredores compartidos: el pasajero toma otro bus (otras empresas, Transmetro o transporte informal). La asociación del EDA (β = 0,78), que D1 llamaba pesimista, resulta cercana al efecto causal. Reserva: β sale de fallas imprevistas y pequeñas; un recorte planificado y anunciado podría tener β de 0,4–0,5 (E7). En 2026, SILENCIO y CL 72 añadieron cerca del 24 % de viajes y CRA 54 un 6 %, y sus subidas crecieron 14 %, 13 % y 2,5 %: una elasticidad aparente de 0,66 que E8 califica de frágil (daba 0,46 antes de limpiar contadores corruptos y es casi nula en festivos).

### 4.2 Dónde sobra y dónde falta oferta (D1, D2)

La regla de "punto de máxima carga" (D1) pide las salidas para que el tramo más cargado vaya al 85 % de la capacidad de 50 pasajeros (factor de carga 0,85; 1,0 = bus lleno), con intervalo de 3 a 10 min (15 en domingo). La oferta de 2025 coincide con ella en el 15,3 % de las horas; sobran salidas en el 44,7 % y faltan en el 40,0 % (D1).

- **Sobra** (factor 0,3–0,55) en CRA 54 domingo y festivo de 9 a 14 h (12 salidas por hora donde bastan 6 o 7), en sus tardes laborales de 17 a 19 h y en su valle de 9 a 11 h; los fines de semana sobra entre el 15 % y el 42 % de los buses-hora (D1, D2).
- **Falta** (factor 1,0–1,1) en CRA 54 de 5 a 6 h (32 y 25 salidas; harían falta 38–39 y 32–33) y de 14 a 15 h (17 y 16; harían falta 21–22 y 18). A las 5–6 h manda la flota: esos buses forman el pico de las 8 h, que ya llega a 79,7 buses en ruta frente a 79 disponibles (D1, P1).
- **CL 72** no tiene déficit de demanda sino de política: opera con 12–15 min entre buses y la cota de 10 min le obliga a añadir salidas (D1).

### 4.3 Recortar o reasignar (D1, D5, E7)

El optimizador D5 (programación entera: prueba de forma exacta las combinaciones de salidas por hora y elige la más barata que cumple las reglas) suma el costo de operar (60.000 COP por bus-hora y 1.500 COP por km), la espera (7.000 COP por hora), una penalidad por pasajero sobre la capacidad (10.000 COP) y los pasajes ganados o perdidos según β (tarifa 3.000 COP), todos supuestos, con límites de intervalo y flota. Se aplicó a los 365 días de 2025 con el pronóstico a una semana y se evaluó con la demanda real y con la contabilidad conservadora de D1: pasajeros perdidos donde se recorta, ninguno ganado donde se añade. Esos supuestos se reemplazaron después por costos con fuente (sección 5): la Tabla 3 muestra las decisiones de D5 tal como se optimizaron, su valor con los costos nuevos y, en la última fila, D5 reoptimizado con ellos (`costos/`).

**Tabla 3. Escenarios 2025, tres rutas, promedio por día**

| Escenario | Salidas/día | Buses-hora/día | Espera media (min)¹ | Pasajeros sobre la capacidad/día | Horas con factor de carga > 1 | Neto con costos con fuente, β = 0,70 (M COP/año)² | β de equilibrio, costos con fuente³ | β de equilibrio, supuestos de D5 |
|---|---|---|---|---|---|---|---|---|
| S0 oferta real | 460 | 1.732 | 4,43 | 317 | 11,7 % | — | — | — |
| S1 regla D1 (factor 0,85, máx. 10 min) | 431 | 1.645 | 4,51 | 384 | 9,9 % | −1.713 | 0,36 | 0,54 |
| S5 regla D1 (máx. 15 min) | 407 | 1.555 | 4,87 | 422 | 12,4 % | −409 | 0,63 | ninguno |
| **D5 (penalidad 10.000 COP, máx. 10 min)** | **411** | **1.565** | **4,74** | **530** | **15,6 %** | **−1.029** | **0,53** | **0,85** |
| D5 con máx. 15 min | 384 | 1.460 | 5,19 | 593 | 19,6 % | +390 | 0,76 | ninguno |
| D5 con penalidad 30.000 COP | 447 | 1.702 | 4,36 | 264 | 7,1 % | −2.462 | 0,17 | 0,23 |
| D5 reoptimizado con costos con fuente (e = 0,5) | 451 | 1.723 | 4,30 | 267 | 6,8 % | −2.825 (simétrica: +1.600) | — | — |

¹ Con la irregularidad de los intervalos del punto medio de la ida (D4); D1, con otra medida, daba 5,06 min para S0. ² Ahorro en km (1.991 COP) y en conductor pagado por hora (26.400 COP por bus-hora) menos los pasajes perdidos (3.182 COP netos), con la contabilidad conservadora (`costos/`, sección 5). Con los supuestos de D5 y β = 0,5, los netos eran +183 (S1), +2.511 (S5), +1.905 (D5), +4.543 (D5 con máx. 15 min) y −1.228 (D5 con 30.000) M COP al año. ³ β por encima del cual el escenario pierde dinero; "ninguno": gana con cualquier β del rango medido.

- **Recortar con una regla fija no paga**: S1 quita 72 salidas diarias y añade 43; con costos con fuente y β = 0,70 pierde 1.713 M COP al año (de −3.303 a −229 en el rango de costos y de β) y su equilibrio (0,36) está muy por debajo de todas las mediciones (E7, `costos/`).
- **D5 recorta mejor que una regla, pero tampoco paga**: con β = 0,5 programa 10,6 % menos salidas y 9,6 % menos buses-hora (60.754 al año, y 1,05 millones de km), con la espera de 4,43 a 4,74 min. Ese recorte venía del supuesto de 60.000 COP por bus-hora: con costos con fuente ahorra 3.695 M COP al año (2.091 en km y 1.604 en conductor), pierde 4.724 M en pasajes con β = 0,70 y deja de pagar con β mayor que 0,53. Acierta las salidas que habría elegido conociendo la demanda real en el 64,6 % de las horas; la oferta actual, en el 16,9 % (D5).
- **Con los costos con fuente, el óptimo reasigna**: reoptimizado con el mismo método (e = 0,5, conductor por hora), D5 programa 451 salidas al día con casi los mismos buses-hora de hoy (−0,5 %), menos espera (4,30 min) y menos sobrecarga (267 pasajeros al día sobre la capacidad; horas con factor de carga > 1 de 11,7 % a 6,8 %). Quita salidas en los valles de CRA 54 (7–12 h y 16–19 h), en SILENCIO y en domingos y festivos, y las pasa a CL 72 (de 81 a 104 salidas al día) y a la franja de 13 a 15 h de los días laborales (de 88,7 a 110,2 salidas por día laboral en las tres rutas). Aun mirando solo la caja del operador (con β = 0,70) recorta apenas 1,5 %. Con la contabilidad conservadora pierde 2.825 M COP al año, porque los recortes del valle pierden pasajeros y las ganancias de las horas reforzadas no se cuentan; contándolas, gana 1.600 M. Medir esas ganancias es tarea del piloto (`costos/README.md`, sección 6).
- **El canje es el hacinamiento**: con 10.000 COP de penalidad, en CRA 54 las horas con factor de carga > 1 pasan del 17,3 % al 27,3 %. Con 30.000 COP la sobrecarga queda por debajo de la actual y aún se ahorra 1,7 % de buses-hora, pasando buses de SILENCIO (−8,5 %) y CRA 54 (−7,2 %) a CL 72 (+25,6 %); pero solo paga si los buses añadidos en CL 72 atraen pasajeros (+1.541 M COP al año si se cuentan los ganados, con los supuestos de D5) (D5).
- **CL 72 lo decide la política de intervalo máximo**: con 10 min, D5 la sube de 87 a 105 salidas laborales (unos 1.900 M COP más de costo operativo al año con los supuestos de D5); con 15 min queda como hoy (D5).
- **Lo que más pesa**: en el neto de D5 con costos con fuente, β (de −133 a −2.140 M COP al año en su rango), seguido del salario del conductor y del mantenimiento por km; el precio del ACPM es de los que menos lo mueven (`costos/`). Reoptimizar cada día con el pronóstico rinde 371 M COP al año más que una plantilla fija (D5, con sus supuestos).

### 4.4 Lo que dice el simulador (D6)

D6 reproduce la operación bus por bus: tiempos por tramo, pasajeros que esperan y suben si hay cupo, tiempo en paradas. En 18 días laborales de 2025 que no se usaron para construirlo se equivoca 1,4–1,9 % en el tiempo de vuelta y 3–5 % en los pasajeros por viaje; llena los buses más que la realidad, así que sus esperas son pesimistas.

**Tabla 4. CRA 54, día laboral típico, promedio de 30 días simulados por política (D6)**

| Política | Buses-hora/día | Espera media (min) | Viajes que llegan a 50 a bordo | Buses en ruta en el pico | Costo generalizado (M COP/día)⁴ |
|---|---|---|---|---|---|
| S0 real | 1.031 | 4,78 | 38,4 % | 82 | 160,9 |
| S0 regularizada (mismas salidas por hora, equiespaciadas) | 1.036 | 4,44 | 35,5 % | 79 | 160,2 |
| S1 (D1) | 966 | 4,23 | 38,9 % | 81 | 154,0 |
| D5 | 910 | 4,58 | 45,9 % | 80 | 150,5 |
| D5 + retención en 3 puntos | 913 | 4,58 | 46,8 % | 80 | 150,7 |
| D5 + giro corto en el punto 35 | 880 | 4,87 | 46,8 % | 80 | 148,1 |

⁴ 60.000 COP por bus-hora, 1.500 COP por km, 7.000 COP por hora de espera y 3.500 COP por hora a bordo (supuestos de D5; la sección 5 revalora los escenarios con costos con fuente).

- **D5 se confirma, con su canje**: frente a las salidas actuales equiespaciadas ahorra 126 buses-hora al día (−12,1 %) con un cambio de espera (+0,14 min) indistinguible del azar, pero el 46 % de los viajes llega a 50 a bordo (frente a 35,5 %). Con capacidad 60 su espera empeora 0,39 min: el ahorro es robusto, la mejora de servicio no. Ni D5 ni S1 bajan los buses del pico: ahorran horas fuera de él.
- **La retención rinde poco**: la irregularidad de los intervalos (CV = desviación ÷ media; 0 es regular) crece a lo largo de la ruta (CRA 54: de 0,57–0,67 al salir a 0,99–1,09 al volver; D4) y la mitad ya viene del despacho. Hacer esperar hasta 4 min al bus que va pegado al anterior baja el CV del punto medio de 0,73 a 0,64, no a 0,3: la espera allí baja 7,6 % (D4 suponía 29–33 %), y la espera total no cambia en CRA 54 y baja apenas 0,24–0,25 min en SILENCIO y CL 72 (D6).
- **Giro corto en el punto 35** (uno de cada dos buses de 7 a 15 h vuelve sin hacer el lazo norte, que recoge el 4,7–7,1 % de las subidas; D3): sobre la oferta actual ahorra 35,6 buses-hora al día en CRA 54 (−3,5 %) y 3,0 M COP de costo generalizado, pero obliga a bajarse antes a 562 pasajeros al día (D6).
- **CL 72**: lo más barato es regularizar el despacho actual: las mismas salidas, equiespaciadas, bajan la espera de 9,5 a 6,9 min sin un bus más (8,0 min si se conservan las salidas de cada día); S1 y D5 añaden 17 % de buses-hora por el máximo de 10 min para bajarla cerca de 1 min más, lo que no se paga. En SILENCIO, D5 con retención ahorra 8,7 % de buses-hora con casi la misma espera (D6).

### 4.5 El planificador (P1)

`planificador.html` lleva D5 al navegador: se elige ruta y tipo de día, se cambian costos, tarifa, valor de la espera, penalidad, β, factor de carga, margen de seguridad, intervalos y flota, y recalcula al instante las salidas por hora frente a hoy, los buses en ruta frente a la flota y el horario minuto a minuto. Planifica un día típico, no una fecha concreta. Un selector ofrece tres juegos de costos: con fuente y conductor por hora (por defecto), con fuente y conductor por producido, y los supuestos de D5. Con estos últimos reproduce exactamente a D5 (153 de 153 horas, las 1.092 salidas del horario y las 54 soluciones con 6 valores de β); en 300 casos aleatorios coincide con el modelo de D5 en 208 de 215 factibles y en el resto avisa de una brecha de a lo sumo 1,77 %. Con los costos con fuente da la misma solución que el modelo de D5 en las 153 horas, con β de 0,5 y de 0,70; solo con pago por producido y β = 0,70 difiere, en 5 de los 9 días tipo, con una brecha de a lo sumo 1,98 % que la página avisa (P1).

Con los costos con fuente, el plan del día típico casi no recorta: en el día promedio de 2025 de las tres rutas pasa de 467 a 453 salidas y de 1.755 a 1.728 buses-hora (−1,5 %), con la misma espera (4,32 min) y menos pasajeros esperados sobre la capacidad (de 464 a 311); con los supuestos de D5 eran 411 salidas y 1.565 buses-hora (−10,8 %), con 654 pasajeros sobre la capacidad. CRA 54 laboral pasa de 277 a 261 salidas y de 1.054 a 1.004 buses-hora, y CL 72 laboral sube de 87 a 114 salidas (P1). Las cifras del día típico no son las de la Tabla 3, que evalúa cada fecha de 2025.

## 5. Cuánto cuesta operar y cuánto se ahorra (`costos/`)

Hasta la segunda versión, D1, D5 y D6 valoraban la operación con tres supuestos sin fuente: 60.000 COP por bus-hora, 1.500 COP por km y tarifa de 3.000 COP. El módulo `costos/` los reemplaza por valores con fuente y rango, construye la línea base de 2025 y recalcula el valor de cada escenario. Lo que se ahorra al quitar un bus es lo que depende del km (combustible, mantenimiento, llantas, lubricantes) y, solo si el conductor se paga por hora o por turno, su salario; los seguros, la administración y el capital no bajan, porque ninguna política reduce los buses del pico (D6).

**Tabla 5. Costos unitarios evitables (precios de 2026)**

| Concepto | Central | Rango | Supuesto anterior | Fuente principal |
|---|---|---|---|---|
| Combustible por km | 898 COP | — | — | ACPM de 11.291 COP/gal en Barranquilla (CREG, circulares 335 y 339 de 2026) ÷ 12,6 km/gal estimados por tipo de bus |
| Mantenimiento, llantas, lubricantes y filtros por km | 1.093 COP | 715–1.598 | — | Estudio de costos del transporte público de Soacha 2026 (ARM), SICE-TAC y precios de mercado, llevados a 2026 con el IPC |
| **Costo evitable por km** | **1.991 COP** | 1.445–2.716 | 1.500 | — |
| **Conductor por bus-hora en ruta, pago por hora o turno** | **26.400 COP** | 19.732–35.854 | 60.000 (incluía costos fijos) | Salario de 1,3 SMMLV 2026, prestaciones, recargos nocturno y dominical y 42 h semanales (Ley 2101 de 2021) |
| Conductor por bus-hora, pago por producido | 0 | — | — | El conductor recibe cerca del 20 % del recaudo: quitar buses no ahorra salario |
| **Ingreso neto por pasajero** | **3.182 COP** | 3.071–3.420 | 3.000 | Tarifa de 3.700 COP (2026) × 0,86 que retiene el operador tras FET, factor de calidad y descuentos del SIBUS (Res. AMB 396-2024) |

**Tabla 6. Línea base 2025 (viajes que corrieron, con o sin la marca `cancelada`; precios de 2025)**

| | SILENCIO | CRA 54 | CL 72 | Total |
|---|---|---|---|---|
| Km al año | 3,20 M | 5,31 M | 1,93 M | 10,44 M |
| Buses-hora al año¹ | 199.273 | 340.936 | 118.614 | 658.823 |
| Galones de ACPM | 253.531 | 425.304 | 151.379 | 830.214 |
| CO2 fósil (t) | 2.322 | 3.896 | 1.387 | 7.605 |
| Costo total, conductor por hora (M COP) | 13.461 | 22.796 | 9.560 | 45.817 |
| Costo por pasajero (COP) | 3.561 | 3.000 | 3.853 | 3.306 |

¹ Incluye los viajes marcados como cancelados que sí corrieron y usa la duración de cada viaje, de inicio a fin (imputada si falta); por eso supera los 1.732 buses-hora diarios de la Tabla 3.

El combustible costó unos 8.788 M COP en 2025 y el mantenimiento 7.305 M. El costo estimado supera el ingreso neto por pasajes (39.336 M COP): margen aproximado de −16,5 % con conductores pagados por hora y −3 % por producido. Es un orden de magnitud, no un estado financiero: el estándar es el de un estudio tarifario (vehículo nuevo, conductores formales), parte de la flota está depreciada y el recaudo podría estar subcontado (los contadores son consistentes en el 74–78 % de los viajes, E3). CRA 54 es la ruta más eficiente por pasajero y CL 72 la más cara.

**Tabla 7. Ahorro por escenario (M COP al año, precios de 2026, β = 0,70, contabilidad conservadora)**

| Escenario | Km al año | Buses-hora al año | Galones de ACPM | Ahorro en operación² | Pasajes perdidos | **Neto, conductor por hora [rango]³** | Neto, por producido | β de equilibrio |
|---|---|---|---|---|---|---|---|---|
| S1 regla D1 (máx. 10 min) | 629.896 | 31.638 | 50.108 | 2.090 | 3.803 | **−1.713** [−3.303; −229] | −1.788 | 0,36 |
| S5 regla D1 (máx. 15 min) | 1.139.177 | 64.580 | 90.622 | 3.973 | 4.382 | **−409** [−2.641; +1.861] | −1.237 | 0,63 |
| D5 (penalidad 10.000 COP) | 1.050.203 | 60.754 | 83.544 | 3.695 | 4.724 | **−1.029** [−3.273; +1.202] | −1.688 | 0,53 |
| D5 (penalidad 30.000 COP) | 295.940 | 11.019 | 23.542 | 880 | 3.342 | **−2.462** [−3.614; −1.498] | −2.084 | 0,17 |
| D5 con máx. 15 min | 1.639.033 | 99.119 | 130.385 | 5.880 | 5.491 | **+390** [−2.619; +3.548] | −1.129 | 0,76 |
| Giro corto en el punto 35, CRA 54 (D6)⁴ | 137.646 | 8.720 | 11.032 | 505 | 257 | **+248** [+52; +475] | +69 | ninguno |
| Regularizar CL 72 (D6) | 0 | 105 | 0 | 3 | 0 | **+3** | 0 | — |

² Km × 1.991 COP más buses-hora × 26.400 COP (conductor pagado por hora). ³ Pesimista: costos unitarios bajos, tarifa alta y β = 0,90; optimista: lo contrario con β = 0,55. ⁴ Uno de cada dos buses de 7 a 15 h en días laborales; los pasajes perdidos son un supuesto del módulo (859 subidas diarias del lazo norte con la mitad de la frecuencia) y no se valoran las 562 bajadas forzadas al día.

- **El ahorro físico es real**: D5 dejaría de recorrer 1,05 millones de km al año, unos 83.500 galones de ACPM (940 M COP) y 765 t de CO2.
- **Pero con β = 0,70 pesan más los pasajes perdidos.** Un bus-hora de valle con sus ~16 km ahorra unos 57.900 COP si el conductor cobra por hora (31.500 si cobra por producido): solo se paga si se pierden menos de unos 18 pasajeros (12 con producido). Así, D5 deja de pagar con β mayor que 0,53, cuando con los supuestos de D5 lo hacía en 0,85; S1, en 0,36. Solo quedan positivos D5 con máx. 15 min (+390 M COP; equilibrio 0,76) y el giro corto en el punto 35, positivo en todo el rango con pago por hora.
- **La forma de pago del conductor cambia el ahorro casi a la mitad**: con pago por producido solo se ahorran los km, y cada pasaje perdido le quita el 20 % al conductor y el 80 % a Sobusa.
- **El signo depende de β y de cómo se cuentan los pasajeros, no de los precios.** Si los pasajeros que se ganan donde se añaden salidas cuentan igual que los perdidos (contabilidad simétrica), los cinco escenarios de D1 y D5 ganan entre 1.528 y 2.530 M COP al año. En el neto de D5, β mueve de −133 a −2.140 M COP; el salario del conductor y el mantenimiento le siguen, y el precio del ACPM es de los que menos lo mueven (−1.058 a −978). Medir β con un piloto vale más que afinar cualquier precio.
- **Regularizar CL 72 no cuesta caja**: las mismas salidas de cada día, equiespaciadas, bajan la espera de 9,5 a 8,0 min, unas 48.600 horas de espera al año, que valen unos 340 M COP de valor social (7.000 COP por hora).
- **Calculadora.** `costos/calculadora_ahorros.xlsx` tiene fórmulas vivas: al cambiar el precio del ACPM, el rendimiento, el salario, la tarifa o β se recalculan la línea base, los escenarios y el β de equilibrio. Reproduce el modelo de Python en 249 comparaciones (diferencia máxima de 1,1·10⁻¹⁴).

**Simulación por fecha real y conductores (`simulacion_ahorro/`, `simulador_ahorro.html`).** Para cada día de 2025 se compara la operación real con lo que habría programado el modelo con el pronóstico de una semana antes: el plan (a), D5 con sus supuestos, que recorta, y el plan (b), D5 con costos con fuente, que reasigna. La página permite elegir la fecha y ajustar el salario por conductor, la forma de pago, las horas por turno, el ACPM, el rendimiento, el mantenimiento, la tarifa y β. Muestra el ahorro del día, del mes y del año, y en rojo los pasajeros que ese ahorro pone en riesgo. La simulación suma exactamente las cifras de la Tabla 7 y un revisor independiente la reprodujo.

**Tabla 7b. Ahorro neto del plan (a) por tipo de día en 2025 (M COP, β = 0,70, contabilidad conservadora)**

| Tipo de día | Días | Conductor por hora | Conductor por producido | Pasajeros en riesgo por día |
|---|---|---|---|---|
| Laboral | 245 | −1.096 | −1.375 | 4.046 |
| Sábado | 52 | −114 | −255 | 4.509 |
| Domingo y festivo | 68 | **+181** | −59 | 3.810 |
| **Año** | 365 | **−1.029** | **−1.688** | 4.068 |

- **Solo pagan los recortes de domingos y festivos**, donde sobra oferta (D1, D2), y siempre a costa de pasajeros. Si la prioridad es no perder clientes, ningún recorte cumple: el modelo sirve para reasignar y para despachar mejor, no para bajar costos de caja.
- **Conductores.** Los datos de 2025 identifican a 628 conductores. Cada día trabajan entre 181 y 216: el rango se debe al código genérico 799, que es casi siempre el primer viaje del día de cada bus. La plantilla mensual es de 314 a 341 conductores distintos. Con el plan (a) harían falta unos 172 conductores por día en vez de 184 (plantilla de 337 a 316), y con el plan (b) unos 189.
- **Jornada.** Los conductores regulares suman unas 247 h en ruta al mes y el 85 % supera las 182 h de la jornada ordinaria de 2026. Con la jornada legal (7 h por día y 26 días al mes), la operación de hoy pediría unos 288 conductores de turno por día. Antes de prometer ahorros de nómina hay que confirmar con Sobusa la jornada real, los relevos y la forma de pago. Como referencia, Bogotá opera con unos 2,3 conductores por bus y Sobusa con 1,8–2,2 (`documentos/investigacion_internacional.md`).

## 6. Despacho en tiempo real (`sistema_tiempo_real/`, `consola_despacho.html`)

**Qué hace.** Cada 1 a 5 minutos, un motor lee el estado del día (despachos, GPS y contadores de puertas de los viajes de hoy) sin mirar al futuro y compara los pasajeros vistos con los que esperaba el plan semanal. Luego reoptimiza las horas que faltan con el mismo modelo de D5: las salidas hechas no se deshacen y los buses en la calle ocupan flota. Entrega las próximas salidas a la hora exacta, contadas desde la última salida real, y alertas: hueco de más de dos intervalos, buses con 50 o más a bordo, buses que pasan pegados por el primer punto de control, flota al límite y fallas de datos. Si los pasajeros vistos de las tres rutas son menos de la mitad o más del doble de lo esperado, declara una falla de datos y vuelve al plan semanal hasta que lo visto en las últimas 2 h se normaliza. Cada corrida tarda 0,2–0,5 s. No hay transmisión en vivo: se probó reproduciendo días de 2025 con los Parquet del proyecto. `consola_despacho.html` reproduce cualquiera de los 353 días de 2025 con GPS como si fueran en vivo, que se eligen en un calendario. Corre en tiempo real (1 s = 1 s) o acelerada hasta 900 veces. Muestra el mapa de los buses y una lista de **despachos en orden** con las tres rutas mezcladas, pensada para las dos personas que despachan en Sobusa: hora exacta, bus, estado (hecho, próximo, atrasado o ajustado) y motivo de cada ajuste. También muestra las salidas por hora frente al plan, los pasajeros vistos frente a los esperados y las alertas.

**Backtest.** 79 días de 2025 (24 laborales, 8 sábados, 8 domingos, 9 festivos, 4 de Carnaval, 6 de lluvia fuerte y 20 atípicos de E10), con el motor cada 15 min de 4 a 21 h en las tres rutas (16.353 recomendaciones). El plan semanal de esta prueba es, desde la corrida del 13 de octubre, el D5 reoptimizado con los costos con fuente (sección 4.3), el que ejecutan el motor y la consola; reproduce su horario en las 4.029 horas evaluadas (`verificar_plan.py`) y el óptimo de referencia se recalcula con los mismos costos. Un revisor independiente comprobó, sobre la corrida del 7 de octubre con el D5 original y sus supuestos, que el motor no usa información posterior a cada instante; el código del motor no cambió, solo los costos del plan. El error del pronóstico (Tabla 8) es idéntico en las dos corridas.

**Tabla 8. Error del pronóstico de las horas que faltan (WAPE por ruta y hora de salida, 79 días)**

| Hora del corte | 7 h | 9 h | 12 h | 15 h |
|---|---|---|---|---|
| Plan semanal | 13,76 % | 13,97 % | 14,25 % | 16,13 % |
| Plan corregido con lo visto en el día (motor) | 13,74 % | 13,97 % | 14,27 % | 16,05 % |

**Tabla 9. Decisiones frente al óptimo con la demanda que llegó (horas 7–20, promedio diario de las tres rutas)**

| Escenario | Error medio (salidas por hora) | Horas exactas | Pasajeros sobre la capacidad/día | Costo generalizado (M COP/día)¹ |
|---|---|---|---|---|
| Plan semanal (D5 con costos con fuente) | 1,05 | 53,9 % | 68 | 86,2 |
| Motor (plan corregido en el día) | 1,08 | 52,6 % | 77 | 86,5 |
| Oferta real 2025 | 2,80 | 13,9 % | 107 | 87,9 |
| Óptimo con la demanda realizada | 0 | 100 % | 7 | 81,6 |

¹ Operación con los costos con fuente (26.400 COP por bus-hora, 1.991 por km), espera a 7.000 COP por hora y sobrecarga a 10.000 COP por pasajero, sin el término de elasticidad. Son las horas de 7 a 20 de los 79 días del backtest. Con el D5 original y los supuestos (corrida del 7 de octubre) la tabla daba 0,56 / 69,8 % / 233 / 112,3 para el plan, 0,61 / 69,0 % / 239 / 112,7 para el motor, 2,61 / 14,9 % / 107 / 121,0 para la oferta real y 0 / 100 % / 37 / 107,3 para el óptimo; en todo 2025 y todas las horas, ese D5 acierta el 64,6 % y la oferta real el 16,9 % (sección 4.3).

- **Corregir la demanda en el día no aporta.** El pronóstico semanal ya acierta el total del resto del día con 5–8 % de error por ruta hasta el mediodía (9 % a las 15 h), y lo que se ve en la mañana dice poco del resto: aun conociendo exactamente los pasajeros de las horas pasadas, su desvío correlaciona 0,2–0,4 con el del resto del día en días normales y casi 0 en los especiales. La primera versión del ajuste, sin calibrar, empeoraba el error (a las 12 h, de 14,2 % a 18,3 %).
- **Las decisiones tampoco mejoran.** El motor queda tan cerca del óptimo como el plan semanal (1,08 frente a 1,05 salidas por hora; 0,2 M COP al día de diferencia), y en el simulador de CRA 54 (8 días laborales, 10 réplicas) la espera es 4,76 frente a 4,65 min con 0,5 % menos buses-hora: equivalentes. La brecha grande está en la operación real: se aleja 2,8 salidas por hora del óptimo, y el plan semanal, con los mismos buses-hora que ella (−0,2 %), da menos espera (4,99 frente a 5,16 min), menos pasajeros sobre la capacidad (68 frente a 107 al día) y 1,7 M COP al día menos de costo generalizado (con los supuestos de D5, que valoraban el bus-hora en 60.000 COP, el plan que recortaba costaba 8,7 M menos). El plan acierta menos horas del óptimo que el D5 original (54 % frente a 70 %) porque, con el bus-hora a 26.400 COP, el óptimo de cada hora depende más de la demanda que llegó y el mismo error de pronóstico se vuelve más salidas de diferencia: el plan pone más que el óptimo en el 37 % de las horas y menos en el 10 % (D6, `sistema_tiempo_real/`).
- **Lo que sí sirve en tiempo real es ejecutar bien el plan**: la hora exacta de cada salida desde la última que salió de verdad, cerrar huecos, no despachar buses pegados, saber cuántos buses hay en la calle y en el patio y detectar fallas de datos. La guarda reconoce los tres días de 2025 en que falló el registro (19 de junio, 9 y 29 de julio) y mantiene el plan mientras dura la falla; en el resto de 2025 solo saltó en una mañana floja con datos completos (20 de noviembre, 05:50–07:40).
- **Por pulir antes de un piloto**: las alertas saltan demasiado (sobrecupo en 21,7, regularidad en 16,9 y flota al límite en 6,2 de las 69 corridas por ruta y día; con el D5 original, 21,7, 18,1 y 1,9), el intervalo de 80 % de la demanda cubre el 66 % de los casos, y la salida del patio se detecta con retraso (mediana 3,4 min) porque los datos resumidos no marcan el momento en que el bus sale; en producción vendría del registro del despacho o de una geocerca del patio con el GPS en vivo.

## 7. Recomendación para Sobusa (por prioridad)

1. **Plan semanal del modelo, optimizado con D5 con costos reales y una penalidad explícita por hacinamiento.** Cada semana: pronóstico de `modelo_final.py` (E11; para producción, con las variables de Chronos-2 del híbrido de E12, que baja el error de 13,9 % a 13,6 %), entrenado con el objetivo corregido de E13 (pasajeros de todos los viajes que corrieron, también los marcados como cancelados). Con el objetivo viejo, el plan queda corto de buses en el 44 % de las horas; con el corregido, en el 27 %. Luego, salidas por hora de D5, horario y salidas a programar. Reentrenar cada semana basta (E11, investigación internacional). Fijar los parámetros con la gerencia en el planificador, que ya trae por defecto los costos con fuente, empezando por la penalidad: con los supuestos de D5, 10.000 COP sube la sobrecarga de 317 a 530 pasajeros al día y 30.000 COP la deja por debajo de la de hoy (D5). Falta conectar el pronóstico de E11 con los cuantiles de carga (E3) y con el planificador, y recalibrar el nivel con 2026 (E8).
2. **Reasignar, no recortar.** Mover salidas del fin de semana y del valle laboral de CRA 54 (9–12 h y 17–20 h) a CRA 54 de 13 a 15 h y, hasta donde alcance la flota, de 5 a 6 h; para las 5–6 h harían falta buses más grandes o vehículos de CL 72, que usa 56 para un pico de 24 (D2; a confirmar). Nada de recortes generales: con costos con fuente, S1 y D5 pierden dinero con cualquier β por encima de 0,36 y 0,53, y lo medido es 0,70 (E7, `costos/`). Reoptimizado con esos costos, el propio D5 deja de recortar y reasigna (sección 4.3). En Houston, el rediseño hacia alta frecuencia sin más presupuesto coincidió con 6,8 % más abordajes de bus y tren ligero, aunque el bus local solo creció 1,2 % (estado del arte).
3. **Fijar por escrito el intervalo máximo.** Con 10 min, CL 72 pasa de 87 a 105 salidas laborales para bajar la espera cerca de 1 min (unos 1.900 M COP más al año con los supuestos de D5); con 15 min queda como hoy, y D5 con máx. 15 min es la única variante de D5 que paga con β = 0,70 (+390 M COP al año; equilibrio 0,76), a cambio de más espera (5,19 min) y más buses llenos (D5, D6, `costos/`). Es una decisión de servicio de la gerencia.
4. **Piloto controlado para medir β** (`experimentos/P2_piloto_beta/`). Ocho semanas en CRA 54 (y CL 72) por días alternos sorteados, sin anunciar al público: los días con recorte salen 3 buses menos por hora en las horas 9 a 11 y 4 menos en las 17 a 19, repartidos parejos; los días con refuerzo, 4 más por hora en las horas 14 y 15 (en CL 72, 2 más en las 12 a 15); y en 4 de los 8 domingos, 4 menos en las horas 9 a 13. Con 37 días laborales y 8 domingos, la β de recorte se mide con un margen de ±0,11 a ±0,13, suficiente para distinguir 0,70 de 0,53 (potencia 0,89–0,92), con 22.904 pasajeros en riesgo (0,30 % de los de CRA 54 en un año) y un saldo entre −52 y +22 M COP, con cinco reglas de parada; el calendario y la planilla del despachador están hechos. Reemplaza al piloto de cuatro semanas en domingos (de 12 a 7 salidas por hora, anunciado) de D1 y E7: ese recorte queda fuera del soporte de los datos y anunciar los días tratados contaminaría los de comparación. Si β de un recorte planificado resulta de 0,4–0,5, los recortes moderados pagan (D5 deja de pagar en 0,53); si es ≈ 0,7, solo se reasigna. El piloto mide también si las salidas añadidas en horas cargadas atraen pasajeros: de eso depende que reasignar pague con la contabilidad conservadora (la reasignación no pierde pasajeros si la β de refuerzo llega a 0,66, ni dinero si llega a 0,62). El neto de cualquier política depende más de β que de cualquier precio (`costos/`). El aumento de oferta de 2026 será un segundo experimento cuando llegue `progvehiculos` 2026 (E8).
5. **Despachar con la consola en tiempo real.** Primero cuatro semanas en modo sombra en las tres rutas: el motor corre cada 5 min y registra sus recomendaciones sin mostrarlas, para compararlas con lo que hizo el despachador y con la demanda que llegó. Luego, un despachador de CRA 54 con la lista de próximas salidas y las alertas, después de subir los umbrales de sobrecupo y apelotonamiento, que hoy saltan en una de cada tres o cuatro corridas. El número de buses por hora sale del plan semanal; el valor del tiempo real está en la hora exacta de cada salida, en cerrar huecos, en no despachar buses pegados y en detectar fallas de datos (sección 6).
6. **Palancas secundarias.** Regularizar el despacho desde el patio, empezando por CL 72 (espera de 9,5 a 6,9 min sin buses extra, u 8,0 min si se conservan las salidas de cada día; unos 340 M COP al año de valor social; D6, `costos/`), y el giro corto en el punto 35 en el valle de CRA 54 (+248 M COP al año con β = 0,70), sobre todo en vacaciones universitarias, cuando las subidas del lazo caen 17–29 % (D6, E10), nunca de 4 a 6 h ni de 16 a 18 h (D3). La retención en ruta, solo como complemento.
7. **Datos y costos que Sobusa debe entregar o aclarar.** (a) `cancelada`: el 81,9 % de los viajes "cancelados automáticamente" sí recorrió la ruta y llevó 2,85 millones de pasajeros (6,3 % del total), que faltan en los objetivos; y 19.737 viajes "válidos" no salieron (E7). La parte que falta crece (5,5 % de los pasajeros en 2023, 7,3 % en 2025) y en el 18,8 % de los días pasa del 10 % (E13). Además, entre el 21 % y el 30 % de los viajes "sin registro" son despachos duplicados del mismo bus (E13). (b) El 2,37 % de los viajes válidos tiene 0 pasajeros y casi ningún evento GPS: ¿equipo apagado (E10) o viaje que no salió (E7)? (c) El GPS no tiene el último día de cada mes (E2). (d) 192 vehículos sin capacidad (EDA). (e) Costos reales: galones por vehículo y mes, órdenes de mantenimiento, llantas y reencauches, y cómo se paga a los conductores (por hora, por turno o por producido) (`costos/`). (f) Cierre tardío de viajes: los cerrados al día siguiente pasaron del 1,8 % en enero al 10,0 % en diciembre de 2025 (E8). (g) `progvehiculos` 2026 (E8). (h) Acceso de lectura casi en vivo (réplica de la base o API del SIBUS) a despachos, GPS y contadores, con la hora real de salida del patio, para conectar el motor de tiempo real (`sistema_tiempo_real/`). (i) Conductores: la jornada real, los relevos y la forma de pago. Según los registros, los regulares suman unas 247 h en ruta al mes, por encima de la jornada ordinaria, y el código 799 agrupa el primer viaje del día de cada bus sin identificar al conductor (`simulacion_ahorro/`).

## 8. Limitaciones y preguntas abiertas

- **Costos con fuente, pero no de Sobusa**: el rendimiento, el mantenimiento, los seguros y el pago de los conductores salen de estudios de otras ciudades (Soacha, con flota más vieja), de fuentes nacionales y de precios de mercado; el mantenimiento se trata como 100 % proporcional a los km; el valor de la hora de espera (7.000 COP) y la penalidad por sobrecarga (10.000 COP) siguen siendo supuestos. D5 se optimizó con sus supuestos (60.000 COP por bus-hora, 1.500 COP por km, tarifa de 3.000 COP), y con ellos están hechos los horarios que simula D6 (sección 4.4); la sección 5 revalora esos escenarios y la 4.3 reoptimiza D5 con los costos nuevos, y ese plan reoptimizado, el que reasigna en vez de recortar, es desde el 13 de octubre el plan semanal que ejecutan el motor y la consola de tiempo real, con el que se rehicieron el backtest (sección 6) y los 353 días de demostración (`costos/`, `sistema_tiempo_real/`).
- **β viene de fallas imprevistas y pequeñas**: un recorte planificado puede responder distinto; con β de 0,4–0,5, D5 sí pagaría (equilibrio 0,53). Si los viajes "sin registro" de E10, casi todos fallas de E7, en realidad corrieron, β estaría más cerca de 1 (E7).
- **Pasajeros ganados sin medir**: contados igual que los perdidos, S1 daría +1.722 M COP al año con β = 0,70 y costos con fuente (`costos/`); la contabilidad conservadora es un piso.
- **D5 se evalúa con la misma función que optimiza** (su ventaja es en parte por construcción) y con la demanda observada bajo la oferta real (D5).
- **El simulador** llena los buses más que la realidad, no tiene elasticidad (su ahorro es un techo), supone ejecución perfecta y cubre un solo día laboral típico de 2025 (D6).
- **Tiempo real sin datos en vivo**: el motor se probó reproduciendo 2025; no se conoce la latencia real de los datos de Sobusa, los pasajeros se conocen al terminar cada tramo entre puntos de control (10–25 min), las posiciones de la consola están interpoladas entre puntos y el plan usa la flota y el ciclo de D5, sin asignar vehículos ni conductores a cada salida (`sistema_tiempo_real/`).
- **Selección entre muchos modelos**: E12 eligió entre 51 candidatos en los mismos 12 meses de 2025, lo que infla algo la ventaja del ganador. La corrección por comparaciones múltiples y la prueba de 2024 lo acotan, pero el apilamiento de 40 modelos no se pudo repetir en 2024 (E12).
- **Objetivo corregido**: cuenta los viajes de al menos 20 km según `distancia_recorrida`, pero no lo que el equipo a bordo dejó de registrar. Su ventaja sobre V4 viene casi toda del nivel: reentrenar con él gana entre 0,15 y 0,31 puntos de WAPE en 2025, según el reescalado de V4 con que se compare, y el híbrido gana 0,4 más. Los pronósticos de E1–E12 usan el objetivo viejo, que subestima lo que sube a los buses en un 5,6–7,7 % (E13).
- **Conductores**: el código del conductor es el del despacho; puede haber relevos sin registrar, y el código 799 no identifica a nadie. Las horas por conductor y la plantilla necesaria son estimaciones a confirmar con Sobusa (`simulacion_ahorro/`).
- **Otros**: 2026 sin confirmar (E8); demanda observada = demanda servida (E1); variantes elegidas sobre los mismos pliegues que se reportan (E11); solo el 73,5–78 % de los viajes tiene contadores consistentes (E3); la lluvia de Open-Meteo suaviza los aguaceros (E9).

## 9. Archivos entregados

| Archivo | Contenido |
|---|---|
| `app.html` (+ `app/`) | La app «Sobusa Despacho»: nueve pantallas que reúnen todo el proyecto y embeben el tablero, el planificador, la consola, la vista 3D y el simulador; cada cifra se genera desde los resultados (`app/generar_datos_app.py`) y se verifica (`app/verificar_datos_app.py`). |
| `EDA_Sobusa.ipynb` / `.html` | Análisis exploratorio (210 celdas, 55 figuras) y reglas R1–R9. |
| `EDA_visual.html` | Tablero interactivo del EDA: mapa de subidas, series, perfiles, intervalos, buses en ruta, ocupación y flota. |
| `documentos/propuesta_sobusa.md` | Propuesta de dos páginas para la gerencia de Sobusa: diagnóstico, qué proponemos, qué gana, qué necesitamos, el piloto en una página, cronograma de 12 semanas, indicadores y riesgos, con cada cifra referida a su fuente. |
| `planificador.html` (+ `planificador_datos.js`) | Planificador interactivo de despacho (P1), con los costos con fuente por defecto; funciona sin internet (bibliotecas y fuentes en `lib/`). |
| `consola_despacho.html` | Consola de despacho en tiempo real: reproduce cualquiera de los 353 días de 2025 con GPS como si fueran en vivo, en tiempo real o acelerada, con la lista de despachos en orden de las tres rutas, el mapa, las salidas por hora, los pasajeros y las alertas; el plan semanal es el de D5 con los costos con fuente. |
| `vista_3d.html` (+ `lib/`, `mapa_local/`) | Vista 3D del mismo día: buses por las calles y personas que suben y bajan según los conteos; modos Real, Plan y Los dos (el mismo día con nuestro plan, persona a persona), panel «Hoy con el plan» con las cifras del día y de todo 2025, luz por hora, alertas, modo cine y recorrido guiado; funciona sin internet. |
| `experimentos/P2_piloto_beta/` | Diseño del piloto de ocho semanas para medir β en la calle: franjas, calendario sorteado, planilla del despachador, potencia, simulación, riesgo y costo, reglas de parada y el análisis semanal (`run.py --analizar`). |
| `sistema_tiempo_real/` | Prototipo del motor de despacho en tiempo real, backtest en 79 días de 2025, verificación y datos de la consola. |
| `costos/` (`README.md`, `calculadora_ahorros.xlsx`) | Costos con fuente, línea base 2025, ahorro por escenario, β de equilibrio y calculadora con fórmulas vivas. |
| `simulador_ahorro.html` (+ `simulacion_ahorro/`) | Simulación de ahorro por fecha real de 2025: plan del modelo frente a la operación real, conductores necesarios, ahorro por día, mes y año con parámetros editables (salario por conductor, forma de pago, ACPM, β…). |
| `experimentos/E12_comparacion_modelos/` | Comparación de 51 modelos (árboles, redes, fundacionales como TimesFM y Chronos, clásicos y combinaciones) con el protocolo de E11, prueba en 2024 y verificación. |
| `experimentos/E13_limpieza_datos/` | Diagnóstico de datos atípicos (porcentaje de días y franjas) y limpieza: objetivo corregido con los viajes "cancelados" que corrieron, imputación, anomalías automáticas, métricas en buses por hora y prueba en 2024. |
| `documentos/investigacion_internacional.md` | 69 hallazgos internacionales con fuente: qué modelos funcionan, cada cuánto reentrenar, cómo no perder clientes y cuánto se ha ahorrado en otros países. |
| `02_Modelado_demanda.ipynb` / `.html` | Pronóstico: E1–E6 y E8–E11 (59 figuras). |
| `03_Despacho_recomendado.ipynb` / `.html` | Decisión: D1–D6, E7 y P1 (43 figuras). |
| `experimentos/` | E1–E11, D1–D6 y P1: `run.py`, `README.md` con su verificación, `resultados.json`, tablas y figuras; `protocolo_evaluacion.md`. |
| `experimentos/E11_modelo_mejorado/modelo_final.py` | Pronóstico de producción para cualquier fecha futura (7 a 28 días de antelación). |
| `documentos/estado_del_arte_despacho_buses.md` | Cómo lo han resuelto otras ciudades y empresas (85 hallazgos con fuente). |
| `datos/` | Copias Parquet de las tablas analíticas, resúmenes GPS y lluvia. |
| `README.md`, `bitacoras/plan_nocturno.md`, `bitacoras/plan_nocturno_2.md`, `bitacoras/plan_nocturno_3.md`, `bitacoras/plan_nocturno_4.md`, `bitacoras/plan_app.md`, `documentos/Diccionario de Variables.csv` | Guía, bitácoras de las sesiones de trabajo y de la app, y diccionario de la base. |

**Cómo volver a ejecutar.** Desde la carpeta del proyecto: `PYTHONIOENCODING=utf-8 MPLBACKEND=Agg python experimentos/<carpeta>/run.py` (semilla 42), con las librerías del `README.md` más LightGBM, statsmodels, scikit-learn, linearmodels y PuLP (solver CBC). Orden: E1 antes de D1; E1, E3, D1 y D4 antes de D5; D5 antes de D6 (`escenarios.py`) y P1; E9 antes de E7; E9 y E10 antes de E11. Los más largos (E1, E11, D5) tardan 25–27 min. Después, `costos/modelo_costos.py` (y, opcional, `costos/reoptimizar_d5.py`, unos 17 min) y, para el tiempo real, `sistema_tiempo_real/preparar_cache.py`, `calibrar_nowcast.py` (usa la muestra de días que ya viene en `backtest/muestra_dias.csv`), `backtest.py` (unos 11 min con 2 procesos de prioridad baja), `generar_replay.py` (con `--por-dia --baja-prioridad --procesos 3` para los 353 días, unas 2 horas), `calles.py --todos --procesos 3` (unos 6 min) y `resumen_calles.py` (segundos). La simulación de ahorro se rehace con `simulacion_ahorro/analisis_conductores.py` y `simulacion_por_fecha.py` (menos de un minuto). E12 usa un entorno de Python aparte con XGBoost, CatBoost, PyTorch, neuralforecast, Chronos, TimesFM, Prophet y statsforecast (`experimentos/E12_comparacion_modelos/requisitos_e12.txt` y `HARNESS.md`); sus familias tardan de minutos a unas 2 horas. Nada necesita conexión a la base de datos.
