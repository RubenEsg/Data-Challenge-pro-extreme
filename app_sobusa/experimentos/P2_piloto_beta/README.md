# P2 · Diseño del piloto para medir β (cuántos pasajeros se pierden o se ganan al cambiar las salidas)

**Pregunta.** ¿Cómo puede Sobusa **medir en la calle**, con poco riesgo y en pocas semanas, cuántos pasajeros pierde cuando en una franja salen menos buses y cuántos gana cuando salen más? Ese número, la elasticidad β (por cada 1 % de salidas, β % de pasajeros), decide si recortar paga: con los costos con fuente el plan D5 deja de pagar con β mayor que 0,53, y hoy β solo se conoce por E7 (0,70; rango creíble 0,55-0,90), estimado con **fallas no planificadas** (viajes que se registraron y no salieron), no con recortes programados y parejos como los que haría un plan.

**Respuesta corta.**

1. **Qué hacer.** Un piloto de **8 semanas en CRA 54 (y CL 72) por días alternos sorteados**: en los días «R» se quitan **3 salidas por hora de 9 a 11 h y 4 de 17 a 19 h** (el valle laboral, que es donde el plan con costos con fuente recorta); en los días «F» se añaden **4 salidas por hora de 14 a 15 h** (el pico de carga, donde el plan añade); en CL 72, en sus días «F», **+2 por hora de 12 a 15 h**; y en **4 de los 8 domingos**, −4 por hora de 9 a 13 h. Todo lo demás sigue igual. Cada día de la semana queda la mitad de las veces tratado y la mitad normal, en bloques de dos semanas, así que el calendario (fig. 4, `calendario_piloto.csv`) ya está sorteado con semilla 42 y la planilla del despachador (`planilla_piloto.csv`) dice cuántas salidas van en cada hora de cada tipo de día.
2. **Qué se mide.** Con lo que `progvehiculos` ya registra (salidas y `numeropasajeros` por viaje) se calcula, por franja, β = cambio de log(pasajeros) ÷ cambio de log(salidas) entre días tratados y normales, con efectos fijos de día de la semana × hora y de semana, errores agrupados por día y **la asignación sorteada como instrumento** (sección 2). Se mide también lo que pasa en las horas vecinas, en la misma hora de SILENCIO, en la hora de control (7 h, que nunca cambia) y en el total del día.
3. **Cuánto se aprende.** El valle de la mañana de CRA 54 es muy estable (la desviación típica del residuo diario de log(pax) es 0,048; sección 3), así que en 8 semanas la **β de recorte conjunta** (9-11 h, 17-19 h y domingos) se estima con un error estándar de **0,056 analítico y 0,066 en la simulación** (IC 95 % de ±0,11 a ±0,13): alcanza para **distinguir β = 0,70 de 0,53** (potencia 0,92 analítica, 0,89 simulada). Cada franja por separado queda en ±0,15-0,19 (9-11 h) a ±0,3-0,4 (domingos); los domingos solos necesitarían más de 20 semanas. Los refuerzos dicen con potencia ≈ 1 si los buses añadidos atraen pasajeros (β > 0), pero no fijan cuántos con precisión (±0,2 en CRA 54 14-15 h, ±0,13 en CL 72).
4. **Validación in silico.** En 500 pilotos sintéticos (bootstrap por semanas de 2025 con β inyectado) el estimador recupera β sin sesgo: con β = 0,70 la media de las 500 estimaciones es 0,704 (9-11 h), 0,718 (17-19 h), 0,703 (domingos), 0,709 (14-15 h), 0,706 (CL 72) y 0,703 (β conjunta), y con β = 0,30 y 1,00 el sesgo queda entre −0,03 y +0,05; los IC 95 % cubren el valor verdadero el 90-94 % de las veces. La MCO sobre las salidas realizadas, que es lo que se haría «mirando los datos sin sortear», queda sesgada hacia 0,53-0,64 con β = 0,70 (la misma contaminación que E7 encontró en la asociación de 0,53): por eso el sorteo es lo que hace útil al piloto.
5. **Qué arriesga Sobusa.** Con β = 0,70, cada día «R» pone en riesgo 566 pasajeros en 9-11 h (1,8 M COP de pasajes) y 524 en 17-19 h (1,7 M), y cada domingo tratado 822 (2,6 M); a cambio ahorra 1,9, 2,4 y 3,8 M COP de operación (conductor por hora + km). En todo el piloto: **22.900 pasajeros en riesgo (el 0,30 % de los que CRA 54 mueve en un año), 73 M COP de pasajes, 93 M COP de ahorro operativo** (neto de los recortes +20 M); los refuerzos cuestan 72 M COP y, si la elasticidad es simétrica, ganan 23.300 pasajeros (74 M). El piloto completo queda entre **−52 M COP** (si los buses añadidos no atraen a nadie) y **+22 M COP**, con reglas de parada (sección 5).
6. **Qué decide.** Al cierre: si el IC 95 % de la β de recorte queda **por debajo de 0,53**, los recortes moderados del valle pagan y D5 puede recortar; si queda **por encima de 0,53**, recortar no paga y solo se reasigna (si además supera 0,70, se confirma E7); si cubre 0,53, reasignar y, si la gerencia necesita la decisión de recortar, extender 4 semanas. Para los refuerzos: la reasignación 9-11 h → 14-15 h no pierde pasajeros si la β de refuerzo es ≥ 0,66 y no pierde dinero si es ≥ 0,62 (con β de recorte 0,70).

## 0. Qué tiene que medir el piloto y por qué así

- **E7 midió fallas, no recortes.** Una falla deja un hueco doble sin aviso (en una hora de 10 salidas sube la espera un ≈ 20 %); un recorte programado reparte los buses parejos (≈ 11 %). Si los pasajeros responden a la espera, un recorte planificado podría tener β de 0,4-0,5; si responden a «qué bus pasa primero» en un corredor compartido, ≈ 0,7-0,9 (E7, sección 6). Entre 0,53 y 0,70 está la decisión: con los costos con fuente, S1 deja de pagar con β > 0,36, D5 con β > 0,53 y D5 con intervalo máximo de 15 min con β > 0,76 (`costos/`).
- **Los refuerzos nunca se han medido.** Las fallas solo informan de reducciones. Que reasignar pague con la contabilidad conservadora depende de que las salidas añadidas en las horas cargadas atraigan pasajeros (`costos/README.md`, sección 6; informe, recomendación 4).
- **Por qué días alternos y no «antes y después».** Un antes/después de 4 semanas (D1, recomendación 5) confunde el recorte con la tendencia (−8 % al año), el calendario escolar y el clima. Alternar días dentro de la misma semana, balanceando el día de la semana, deja esas cosas iguales en los dos brazos; el sorteo evita que el despachador elija recortar los días que «parecen flojos» (la contaminación que hace que la MCO de E7 dé 0,53).
- **Por qué no hace falta anunciarlo al público.** Lo que distingue un recorte de una falla es que las salidas quedan parejas y que el despachador lo decide de antemano; si, como suponemos, Sobusa no publica horarios, el pasajero ve lo mismo que vería con el plan: buses cada 5 min en vez de cada 4. Anunciar los días tratados contaminaría los días normales. Lo de los horarios es un **supuesto de diseño, no un resultado de los datos**: que Sobusa no los publica, y que por eso el pasajero no distingue el recorte de la variación habitual, hay que confirmarlo con la empresa antes de arrancar.
- **Con qué pasajeros.** Con los de **todos los viajes que corrieron** (distancia ≥ 20 km, sin importar la marca `cancelada`; E7, E13), no con los «válidos»: la tabla corregida tiene entre un 6 % y un 32 % menos de ruido residual por hora (sección 3) y es la que E13 recomienda para despachar.

## 1. Franjas candidatas y franjas elegidas

De `costos/resultados/d5_reoptimizado_decisiones.parquet` (columna `x_corrida_1` = D5 reoptimizado con costos con fuente, `n_S0` = salidas válidas reales) se calcula, por ruta × tipo de día × hora, el cambio medio de salidas del plan frente a hoy (`franjas_candidatas.csv`, fig. 1). Donde más quita: CRA 54 domingo y festivo de 7 a 13 h (−3,6 a −5,0 salidas por hora sobre 10,6-12,3; −34 % a −41 %) y CRA 54 laboral de 17 a 19 h (−4,4 / −4,2 / −4,0 sobre 15,0 / 13,3 / 12,3), seguido del valle laboral de 9 a 11 h (−2,3 / −3,1 / −3,9). Donde más añade: CRA 54 laboral 14 y 15 h (+5,1 y +3,6 sobre 16,3 y 15,1; +31 % y +24 %) y CL 72 laboral de 11 a 16 h (+2,2 a +2,8 sobre 3,9-5,4). Los picos (5-6 h) y las horas con menos de 5 salidas quedan fuera: ahí no hay nada que recortar o el conteo es casi binario.

**Franjas del piloto** (`franjas_piloto.csv`; «habitual» = mediana de 2025 de los viajes que corrieron, días limpios; pasajeros = media 2025 por hora):

| Franja | Ruta, tipo de día y horas | Salidas habituales → día tratado (por hora) | Intervalo medio | Pasajeros por hora | Cambio del plan D5 | Vecinas | Interruptor |
|---|---|---|---|---|---|---|---|
| **R1** recorte | CRA 54 laboral 9, 10, 11 h | 16 / 15 / 16 → 13 / 12 / 13 (−3) | 3,8-4,0 → 4,6-5,0 min | 1.433 / 1.261 / 1.341 | −2,3 / −3,1 / −3,9 | 8 h y 12 h | «recorte» |
| **R2** recorte | CRA 54 laboral 17, 18, 19 h | 16 / 14 / 13 → 12 / 10 / 9 (−4) | 3,8-4,6 → 5,0-6,7 min | 1.092 / 812 / 692 | −4,4 / −4,2 / −4,0 | 16 h y 20 h | «recorte» |
| **R3** recorte | CRA 54 domingo 9-13 h | 14 / 14 / 12 / 12 / 14 → 10 / 10 / 8 / 8 / 10 (−4) | 4,3-5,0 → 6,0-7,5 min | 777 / 731 / 696 / 722 / 718 | −5,0 / −4,6 / −4,2 / −3,6 / −4,4 | 8 h y 14 h | «recorte» (domingo) |
| **F1** refuerzo | CRA 54 laboral 14, 15 h | 18 / 17 → 22 / 21 (+4) | 3,3-3,5 → 2,7-2,9 min | 2.028 / 1.757 | +5,1 / +3,6 | 13 h y 16 h | «refuerzo» |
| **F2** refuerzo | CL 72 laboral 12-15 h | 5 / 6 / 6 / 5 → 7 / 8 / 8 / 7 (+2) | 10-12 → 7,5-8,6 min | 534 / 645 / 683 / 523 | +2,3 / +2,4 / +2,8 / +2,3 | 11 h y 16 h | «refuerzo» (CL 72) |
| **C** control | CRA 54 laboral 7 h | 19 (sin cambio) | 3,2 min | 1.751 | −0,8 | — | ninguno |

- Los k siguen al plan: en 17-19 h y en domingo el plan quita ≈ 4 por hora; en 9-11 h, ≈ 3; en 14-15 h añade ≈ 4; en CL 72, ≈ 2,5. Son cambios del 19 % (R1), 28 % (R2), 31 % (R3), +24 % (F1) y +38 % (F2) de las salidas: dentro de lo que el plan haría y lejos del «12 → 7» de D1, que estaría fuera del soporte de los datos.
- En domingo las salidas habituales son 14 y no las 12,3 «válidas» de la tabla de E3: el 12 % de los viajes dominicales está marcado como cancelado y sí corrió. La planilla se hace con lo que de verdad sale.
- La hora de control (7 h) no cambia en el plan (−0,8), no es vecina de ninguna franja y es tan estable como el valle (0,079). Sirve de placebo: en los días tratados no debería pasar nada allí.

## 2. Diseño del experimento

**Unidad y sorteo.** La unidad de asignación es el **día** (toda la franja a la vez), porque un pasajero elige entre horas y no entre minutos. CRA 54 laboral tiene **dos interruptores independientes**: «recorte» (R1 y R2 juntos) y «refuerzo» (F1); CL 72 tiene el suyo («refuerzo», F2) y los domingos el de R3. Cada interruptor se sortea en **bloques de dos semanas**: de los dos lunes del bloque uno es tratado y otro normal, y así con cada día de la semana (`asignar` en `run.py`); los domingos, en bloques de cuatro (dos tratados, dos normales). Resultado: cuatro planillas posibles en CRA 54 laboral (N, R, F y RF = plan reasignado), balanceadas por día de la semana y por momento del piloto. Con 8 semanas desde el lunes 19 de octubre de 2026 (3 festivos dentro): 37 días laborales (18 con recorte, 19 sin; 20 con refuerzo, 17 sin; en CL 72, 19 con refuerzo) y 8 domingos (4 y 4). Las planillas de CRA 54 quedan en 13 RF, 5 R, 7 F y 12 N.

**Respuesta.** Pasajeros y salidas por hora de los viajes que corrieron, de `progvehiculos` (`fechasalida`, `distancia_recorrida ≥ 20 km`, `numeropasajeros` ≤ 300). Se miran: la franja tratada; sus dos horas vecinas (traslado de pasajeros); la misma hora en SILENCIO y en CL 72 (captación interna entre rutas de Sobusa); la hora de control; el efecto de que el día anterior haya sido tratado, descontado el propio día (arrastre); y el total del día de la ruta (si lo perdido en la franja se recupera en el resto del día, como preguntó E7 con su diseño C).

**Estimador.** Para cada franja, con las horas tratadas:

log(pax_dh) = β · log(salidas_dh) + α_(día de la semana × hora) + γ_semana + ε_dh,

con errores agrupados por día (corrección de muestra pequeña y valores críticos de la t con G − 1 grados de libertad, como `reghdfe`). En domingo los efectos fijos son hora y bloque de cuatro semanas (el efecto de semana absorbería el día entero). La **asignación sorteada T (0/1 por día) instrumenta log(salidas)**: β_VI = (efecto de T sobre log pax) ÷ (efecto de T sobre log salidas) = forma reducida ÷ primera etapa. La primera etapa es conocida de antemano (Δ log salidas = −0,22 en R1, −0,33 en R2, −0,37 en R3, +0,21 en F1, +0,32 en F2) y el estimador no se contamina con la variación natural de la oferta (±15 % día a día en 9-11 h, ±25 % en 17-19 h) ni con que el despachador cumpla la planilla a medias (si cumple a medias, la primera etapa lo mide). La MCO sobre las salidas realizadas se reporta como comparación. La **β conjunta de recorte** apila R1, R2 y R3 con efectos fijos franja × día de la semana × hora y franja × periodo. Las vecinas, el control, la otra ruta, el arrastre y el total del día se reportan como forma reducida (efecto de T sobre log pax, que debe ser ≈ 0 salvo traslado).

Todo esto lo hace `analizar_piloto` en `run.py`, la **misma función** que corre la simulación (sección 4) y el análisis semanal del piloto real (`run.py --analizar`, sección 6).

**Qué no se hace y por qué.** Usar la misma hora de SILENCIO como control restando (diferencia en diferencias) no ayuda en 9-11 h ni en 14-15 h: la correlación de los residuos diarios entre rutas es de 0,21 y 0,11 y la diferencia tiene **más** ruido que CRA 54 sola (0,070 frente a 0,048; 0,102 frente a 0,076). Solo en 17-19 h correlacionan (0,72): la diferencia baja el ruido de 0,098 a 0,081 y SILENCIO como covariable, a 0,068; se deja como opción del análisis, no del diseño. Tampoco se alternan horas dentro del día (el traslado entre horas contaminaría) ni se recorta de 12 a 7 (fuera del soporte).

## 3. Potencia: cuántas semanas hacen falta

**Ruido.** Con la tabla ruta × día × hora de 2025 (días limpios: sin Carnaval, Semana Santa, 1 de enero, 25 de diciembre, vacaciones escolares ni los dos días excluidos del EDA) se quitaron los efectos fijos día de la semana × hora y semana (bloque de cuatro semanas en domingo) y se midió la desviación típica del residuo de log(pax) por hora y la del residuo medio del día (`ruido_residual.csv`):

| Franja | SD residuo por hora 2025 (válidos → corregida) | **SD residuo diario 2025** (corregida) | SD residuo diario 2024 | Asociación natural (MCO) | SD natural de log(salidas) |
|---|---|---|---|---|---|
| R1 · 9-11 h | 0,107 → 0,101 | **0,048** | 0,061 | 0,43 | 0,15 |
| R2 · 17-19 h | 0,195 → 0,172 | **0,098** | 0,190 | 0,49 | 0,26 |
| R3 · domingo 9-13 h | 0,170 → 0,116 | **0,085** | 0,102 | 0,41 | 0,12 |
| F1 · 14-15 h | 0,144 → 0,124 | **0,076** | 0,103 | 0,62 | 0,17 |
| F2 · CL 72 12-15 h | 0,232 → 0,172 | **0,068** | 0,097 | 0,59 | 0,22 |
| C · 7 h | 0,085 → 0,079 | 0,079 | 0,119 | 0,40 | 0,11 |

- El valle de la mañana es el lugar más estable de toda la operación: el residuo diario es de ±4,8 %. La tarde (17-19 h) es el doble de ruidosa y en 2024 fue el cuádruple (0,190): es la franja donde más conviene cumplir la planilla también los días normales (sección 4).
- La tabla corregida (viajes que corrieron) baja el ruido por hora entre un 6 % (R1) y un 32 % (R3; F2 26 %) respecto de los «válidos»: en el pico de carga y en domingo, buena parte del «ruido» de los válidos son viajes marcados como cancelados que sí llevaron pasajeros.
- La asociación natural (MCO con los mismos efectos fijos) es de 0,41-0,62: el mismo rango de la MCO de E7 (0,53), contaminada por la decisión del despachador. Es lo que daría un análisis «observacional» del valle, y por eso no sirve.

**Fórmula.** Para una franja con SD del residuo diario σ, cambio de log(salidas) Δ y n días por brazo: EE(β) ≈ σ · √(1/n_T + 1/n_C) / |Δ|; la β conjunta combina 1/EE² = Σ 1/EE_f². Con 4,5 días laborales por semana (festivos descontados) y un domingo:

**Tabla 1. Semanas necesarias (fórmula analítica) según el tamaño del cambio y las franjas de recorte usadas** (`potencia.csv`; entre paréntesis, semanas calibradas con la simulación: analíticas × 1,40, sección 4)

| Objetivo | k (salidas por hora) | Solo R1 | R1 + R2 | R1 + R2 + R3 |
|---|---|---|---|---|
| EE ≤ 0,10 (IC 95 % de ±0,2) | −2 | 11 (16) | 9 (13) | 8 (12) |
| | **−3** | **5 (8)** | 4 (6) | 4 (6) |
| | −4 | 3 (5) | 2 (3) | 2 (3) |
| | −5 | 2 (3) | 2 (3) | 2 (3) |
| Detectar β = 0,53 frente a 0 (potencia 80 %) | −2 | 4 (6) | 3 (5) | 3 (5) |
| | **−3** | **2 (3)** | 1 (2) | 1 (2) |
| | −4 | 1 (2) | 1 (2) | 1 (2) |
| Distinguir β = 0,70 de 0,53 (una cola, potencia 80 %) | −2 | 24 (34) | 18 (26) | 17 (24) |
| | **−3** | **10 (15)** | 8 (12) | 7 (10) |
| | −4 | 5 (8) | 4 (6) | 4 (6) |
| | −5 | 3 (5) | 3 (5) | 3 (5) |

Con k = −1 harían falta 47 / 37 / 34 semanas (66 / 52 / 48 calibradas) para EE ≤ 0,10 y 100 / 78 / 72 (141 / 110 / 102) para distinguir 0,70 de 0,53: **un cambio de una salida por hora no se puede medir**. Para los refuerzos (solos): F1 con +4 necesita 12 semanas (17 calibradas) para EE ≤ 0,10, 4 (6) para detectar β = 0,53 y 25 (36) para distinguir 0,70 de 0,53; con +6, 6 (9), 2 (3) y 12 (17); F2 con +2 necesita 5 (8), 2 (3) y 9 (13). En días: una semana son ≈ 4,5 días laborales, la mitad tratados por cada interruptor, y un domingo.

**Tabla 2. Con el diseño propuesto (8 semanas; 18 días por brazo en laboral, 4 en domingo)**

| Franja | Cambio de salidas | Efecto esperado en pasajeros (β = 0,70) | EE analítico 2025 (2024) | IC 95 % | Potencia β = 0,53 frente a 0 | Potencia 0,70 frente a 0,53 |
|---|---|---|---|---|---|---|
| R1 · 9-11 h (−3) | −19 % | −14 % | 0,075 (0,094) | ±0,15 | 1,00 | 0,74 |
| R2 · 17-19 h (−4) | −28 % | −21 % | 0,099 (0,193) | ±0,19 | 1,00 | 0,53 |
| R3 · domingo (−4) | −31 % | −23 % | 0,163 (0,198) | ±0,32 | 0,90 | 0,27 |
| **R1 + R2 + R3 (β conjunta)** | | | **0,056 (0,078)** | **±0,11** | **1,00** | **0,92** |
| F1 · 14-15 h (+4) | +24 % | +16 % | 0,119 (0,162) | ±0,23 | 0,99 | 0,41 |
| F2 · CL 72 (+2) | +38 % | +25 % | 0,071 (0,101) | ±0,14 | 1,00 | 0,77 |

La fig. 2 muestra las curvas EE × semanas. Lectura: **8 semanas bastan para la decisión de recortar** (β conjunta); **la pregunta de los refuerzos se responde en signo** (¿atraen pasajeros?) con potencia ≈ 1 y en magnitud con ±0,2. Si 2026 se parece a 2024 en vez de a 2025, los EE suben un 25-95 % (columna entre paréntesis) y la β conjunta queda en ±0,15.

## 4. Simulación in silico: ¿el estimador recupera β?

Se generaron **500 pilotos sintéticos de 8 semanas** por escenario (`simular_piloto`): se sortean con reemplazo 8 de las 34 semanas limpias de 2025 (todas las rutas, horas y días laborales y domingos de cada semana, con sus pasajeros y salidas reales), se sortea el calendario del diseño con la misma regla del piloto, y en cada día-hora tratado se inyecta el efecto: salidas' = salidas + k y pasajeros' = pasajeros × (salidas'/salidas)^β. Los días de control conservan su oferta natural. Luego se corre `analizar_piloto` exactamente como se correría con los datos reales (`simulacion.csv`, `simulacion_replicas.parquet`, fig. 3).

**Tabla 3. VI con la asignación sorteada frente a MCO sobre las salidas realizadas (500 réplicas por β)**

| Franja | β = 0,30: VI (EE empírico) · MCO | β = 0,70: VI (EE empírico) · MCO | β = 1,00: VI (EE empírico) · MCO | Cobertura del IC 95 % (VI; β = 0,3 / 0,7 / 1,0) |
|---|---|---|---|---|
| R1 · 9-11 h (−3) | 0,299 (0,084) · 0,380 | 0,704 (0,096) · 0,528 | 1,010 (0,137) · 0,638 | 0,91 / 0,94 / 0,90 |
| R2 · 17-19 h (−4) | 0,288 (0,087) · 0,410 | 0,718 (0,115; mediana 0,705) · 0,578 | 1,048 (0,264; mediana 1,002) · 0,706 | 0,93 / 0,93 / 0,91 |
| R3 · domingo 9-13 h (−4) | 0,268 (0,216) · 0,332 | 0,703 (0,223) · 0,613 | 1,024 (0,232) · 0,831 | 0,93 / 0,91 / 0,94 |
| F1 · 14-15 h (+4) | 0,285 (0,134) · 0,537 | 0,709 (0,093) · 0,638 | 1,034 (0,144) · 0,712 | 0,93 / 0,93 / 0,94 |
| F2 · CL 72 12-15 h (+2) | 0,297 (0,070) · 0,499 | 0,706 (0,066) · 0,633 | 1,001 (0,070) · 0,730 | 0,92 / 0,92 / 0,93 |
| **R1 + R2 + R3 (β conjunta)** | 0,292 (0,062) · 0,398 | **0,703 (0,066)** · 0,575 | 1,009 (0,092) · 0,709 | 0,94 / 0,94 / 0,92 |

El EE que estima el propio análisis (media de las réplicas, β = 0,70) es 0,090 (R1), 0,099 (R2), 0,182 (R3), 0,080 (F1), 0,056 (F2) y 0,060 (conjunta): algo por debajo del empírico, de ahí coberturas del 90-94 % en vez del 95 %. Potencia con β = 0,70 para rechazar β ≤ 0,53 (una cola): 0,64 (R1), 0,80 (R2), 0,24 (R3), 0,73 (F1), 0,89 (F2) y **0,89 (conjunta)**; para rechazar β = 0 con β = 0,30: 0,93 (R1), 0,43 (R3), 0,97 (conjunta).

- **La VI recupera β en los tres valores y en todas las franjas** (sesgo de −0,03 a +0,05; 0,003 en la conjunta con β = 0,70), con EE empíricos de 0,066 (conjunta y CL 72), 0,09-0,10 (9-11 h y 14-15 h), 0,12 (17-19 h) y 0,22 (domingos). La tarde tiene colas pesadas (con β = 1 el EE es 0,26 pero el rango intercuartílico equivale a 0,12): su oferta natural varía ±25 % y en algunas réplicas la primera etapa queda débil; es la franja donde más importa cumplir la planilla también los días normales (abajo).
- **La MCO sobre las salidas realizadas no sirve**: con β = 0,70 da 0,53-0,64 y con β = 1,0 da 0,64-0,83, porque mezcla el cambio sorteado con la variación natural de la oferta, cuya asociación con los pasajeros es de 0,4-0,6 (tabla de la sección 3). Es el mismo sesgo que E7 encontró entre su MCO (0,53) y su VI (0,73). Si Sobusa hace el piloto pero analiza «comparando días con más y menos salidas», medirá mal.
- **Placebos y vecinas** (`simulacion_vecinas.csv`): sin traslado inyectado, el efecto medio en las horas vecinas, en la hora de control y en la misma hora de SILENCIO y de CL 72 es de −0,003 a +0,009 (± 0,03-0,11 por réplica) y resulta «significativo» en el 5-9 % de las réplicas (nivel nominal 5 %); el arrastre del día anterior (estimado con todos los días, descontado el propio tratamiento) da −0,005 a +0,001 (± 0,03-0,09), pero su EE estimado queda corto con 30 días útiles (9-14 % de «significativos» espurios), así que se lee con cautela. El total del día de CRA 54 cae un 4,5 % en los días con recorte (−0,045 ± 0,014 con β = 0,70; −6,2 % con β = 1) y un 7,7 % en los domingos tratados: lo que se pierde en la franja no se recupera en el resto del día, como en el diseño C de E7; en los días con refuerzo sube un 2,6 % (CRA 54) y un 7,1 % (CL 72).
- **Traslado del 15 % a la hora siguiente** (escenario «derrame»): si el 15 % de los pasajeros perdidos en cada hora recortada espera a la hora siguiente, la β de la franja baja a 0,61-0,63 (conjunta 0,61) (es la elasticidad **neta** del bloque, que es la que importa para el negocio) y la vecina posterior sube +0,015 (EE 0,04) a las 12 h y +0,06 (EE 0,06) a las 20 h (solo recibe lo de la última hora recortada), un efecto demasiado pequeño para detectarlo en 8 semanas. Para medir el traslado con precisión harían falta recortes de una sola hora, que pierden potencia; se prefiere medir la β neta del bloque, que es lo que un plan por franjas necesita.
- **Planilla fija también los días normales**: si los días N siguen la planilla (mediana de 2025) en las horas del piloto en vez de la oferta natural, la β conjunta sale igual de precisa (EE 0,069 frente a 0,066; 9-11 h 0,108 frente a 0,096), desaparecen las colas pesadas de la tarde (EE de 17-19 h de 0,115 a 0,090) y la MCO deja de estar sesgada (0,69), porque ya no hay variación natural que la contamine. No ahorra semanas, pero convierte el experimento en exactamente «plan frente a hoy» y hace que cualquier analista llegue al mismo número; por eso se recomienda, sobre todo de 17 a 19 h.
- **EE analítico frente a simulado**: la fórmula de la sección 3 queda corta porque no cuenta los grados de libertad que consumen los efectos fijos ni el ruido de la primera etapa; la razón EE simulado / EE analítico de la β conjunta es 1,18, y las semanas calibradas de la tabla 1 son las analíticas × 1,40. Los EE agrupados que estima el análisis, con la corrección de muestra pequeña y la t con G − 1 grados de libertad, cubren el valor verdadero el 90-94 % de las veces (nominal 95 %).

## 5. Riesgo y costo del piloto para Sobusa

Para cada franja se aplica la fórmula del proyecto (`perdida_asimetrica` de `costos/datos_operacion.py`: pasajeros × (1 − (n/n0)^β) en las horas con menos salidas) con los pasajeros y las salidas medias de 2025 por hora, tarifa neta de 3.182 COP, 26.400 COP por bus-hora de conductor (pago por hora) y 1.991 COP por km (56,4 km por salida en CRA 54, 57,0 en CL 72; ciclo por hora de D1). Para los refuerzos se calcula el costo extra y los pasajeros que **podrían** ganarse si la elasticidad fuera simétrica, que es justamente lo que el piloto va a medir (`riesgo_costo.csv`, `riesgo_costo_por_hora.csv`, fig. 5).

**Tabla 4. Por día tratado (precios 2026) y total del piloto de 8 semanas**

| Franja | Salidas movidas por día | Buses-hora y km movidos | Pasajeros en riesgo por día tratado (β = 0,55 / **0,70** / 0,90 / 1,0) | Pasajes en riesgo (M COP) | Ahorro operativo por día (M COP) | Neto por día | Días tratados | Pasajeros en riesgo en el piloto | Neto del piloto (M COP) |
|---|---|---|---|---|---|---|---|---|---|
| R1 · 9-11 h | −9 | 35,4 h, 508 km | 452 / **566** / 712 / 783 (de 4.034) | 1,80 | 1,95 | +0,14 | 18 | 10.183 | +2,6 |
| R2 · 17-19 h | −12 | 38,8 h, 677 km | 422 / **524** / 653 / 715 (de 2.597) | 1,67 | 2,37 | +0,71 | 18 | 9.433 | +12,7 |
| R3 · domingo | −20 | 57,6 h, 1.128 km | 663 / **822** / 1.021 / 1.115 (de 3.645) | 2,62 | 3,77 | +1,15 | 4 | 3.288 | +4,6 |
| F1 · 14-15 h | +8 | 34,8 h, 451 km | podrían ganarse **603** (de 3.785) | (+1,92) | −1,82 (costo) | +0,10 si simétrica | 20 | (12.063 ganados) | +2,1 si simétrica |
| F2 · CL 72 | +8 | 36,4 h, 456 km | podrían ganarse **589** (de 2.385) | (+1,87) | −1,87 (costo) | +0,01 si simétrica | 19 | (11.190 ganados) | +0,1 si simétrica |
| **Total** | | | | **72,9** | **92,8 (recortes); −71,8 (refuerzos)** | | | **22.904 en riesgo** (0,30 % de los 7,6 M anuales de CRA 54); hasta 31.420 si β = 1 | **+19,9 recortes; −51,9 a +22,1 total** |

- **Cada día tratado de recorte es casi neutro en caja con β = 0,70** (+0,1 a +1,2 M COP; del ahorro de R1, 0,93 M son de conductor y 1,01 de km; en R2, 1,03 y 1,35; en domingo, 1,52 y 2,25): el piloto no es una apuesta, es la propia política de D5 probada a pequeña escala. El refuerzo cuesta 1,8-1,9 M COP por día y se paga solo si atrae ≈ 600 pasajeros (β de refuerzo ≈ 0,62-0,66).
- **Reasignar 9-11 h → 14-15 h** (día RF) ahorra 1,95 y gasta 1,82 M COP; pierde 566 y, con la misma β, gana 603 pasajeros: queda en +0,25 M COP por día. La β de refuerzo que iguala pasajeros es 0,66 y la que iguala dinero 0,62. Si el piloto mide una β de refuerzo por debajo, la reasignación de D5 pierde pasajeros aunque ahorre; si está por encima, gana en las dos cuentas.
- **Lo que se pierde es poco frente al año**: 22.900 pasajeros en 8 semanas son el 0,30 % de los 7,6 millones anuales de CRA 54, 73 M COP de pasajes frente a 93 M COP de ahorro operativo en los días recortados.

**Reglas de parada** (`resultados.json`, `reglas_de_parada`; se miran al cierre de cada bloque de dos semanas con `run.py --analizar`):

1. **Pérdida mayor que proporcional.** Si el límite inferior del IC 95 % de la β conjunta de recorte supera 1,0 (se pierden más pasajeros que salidas en proporción), se suspenden los recortes y siguen solo los refuerzos.
2. **Hacinamiento.** En las horas recortadas, si el porcentaje de viajes con ocupación máxima ≥ 50 pasajeros (contadores de `conteo_viajes`) supera el doble del valor de 2025 (mínimo 5 %), k baja en una salida por hora. Valores de 2025 (días limpios, viajes con contador): 9,8 % en 9-11 h (umbral 19,6 %), 4,3 % en 17-19 h (8,5 %) y 0,8 % en domingo (5 %). En 14-15 h el 63 % de los viajes ya supera los 50 pasajeros (mediana 54): ahí se añade, no se quita.
3. **Presupuesto de pasajeros.** Si la pérdida acumulada medida (forma reducida × pasajeros de la franja) supera la proporcional (β = 1: 31.420 en todo el piloto), se para.
4. **Parada temprana por decisión.** Mirada intermedia al cierre de la semana 4 con z = 2,5 (no 1,96, para no inflar el error tipo I): si el IC de la β conjunta queda entero por debajo de 0,53 o entero por encima de 0,90, se decide y se para; si no, se completan las 8 semanas.
5. **Operación.** Un día con caída del registro, bloqueo vial o más del 10 % de viajes sin registro (E13) se marca y se excluye; no se recupera.

## 6. Operación: qué hace cada quien

**El despachador** recibe el calendario (`calendario_piloto.csv`, fig. 4) y la planilla (`planilla_piloto.csv`): para cada tipo de día (N, R, F, RF en CRA 54 laboral; N o F en CL 72; N o R en domingo) dice cuántas salidas van en cada hora y el intervalo medio (por ejemplo, día R: 13, 12 y 13 salidas de 9 a 12 h, cada 4,6-5,0 min; 12, 10 y 9 de 17 a 20 h, cada 5,0-6,7 min; día F: 22 y 21 salidas de 14 a 16 h, cada 2,7-2,9 min). Lo único que cambia respecto de hoy es el número de salidas de esas horas y que los intervalos deben quedar parejos (nada de dos buses pegados y un hueco doble, que es la falla que E7 midió). En las horas vecinas y en la de control, nada cambia. Los días N conviene que también sigan la planilla (mediana de 2025), sobre todo de 17 a 19 h (sección 4). Los buses que no salen en 9-11 h entran a las 14-15 h los días RF; los días R quedan en patio y los días F salen de reserva. Los festivos no entran al piloto.

**Qué se registra.** Nada nuevo: `progvehiculos` ya guarda `idprogramacion`, `fechasalida`, `distancia_recorrida` y `numeropasajeros` de cada viaje; el conteo por contadores (`conteo_viajes`) da la ocupación máxima para la regla de hacinamiento. Hace falta solo una bitácora de una línea por día: qué planilla se aplicó (N, R, F, RF) y cualquier novedad (bloqueo, caída del sistema, bus varado), para construir las columnas `recorte` y `refuerzo` del archivo de análisis y aplicar la regla 5.

**Cómo se analiza cada semana.** Un CSV con una fila por ruta × día × hora (`ruta, dia, hora, salidas, pasajeros, recorte, refuerzo`; salidas y pasajeros de los viajes que corrieron) y:

```
PYTHONIOENCODING=utf-8 python experimentos/P2_piloto_beta/run.py --analizar datos_piloto.csv
```

imprime y escribe (`datos_piloto.analisis.csv`, `datos_piloto.vecinas.csv`) la tabla por franja (días tratados y de control, primera etapa, forma reducida, β VI con su EE e IC 95 %, β MCO), la β conjunta de recorte y los efectos en vecinas, control, otras rutas, arrastre y total del día, con una lectura en palabras frente a 0,53 y 0,70. `ejemplo_piloto_sintetico.csv` es un piloto simulado con β = 0,70 en ese formato, y `ejemplo_piloto_sintetico.analisis.csv` su análisis: en ese piloto sorteado la β VI sale 0,84 ± 0,11 (9-11 h), 0,69 ± 0,04 (17-19 h), 0,77 ± 0,07 (domingos, 4 y 4), 0,55 ± 0,08 (14-15 h), 0,79 ± 0,07 (CL 72) y **0,74 ± 0,04 en la conjunta (IC 95 % 0,65-0,83)** para un β inyectado de 0,70; la MCO da 0,55-0,73. La lectura automática: «recortar no paga (todo el IC por encima del equilibrio 0,53): solo reasignar». De las 22 comprobaciones de placebo (la tabla de vecinas tiene 26 filas, pero 4 son totales del día, donde sí se espera efecto), una sale con |t| > 2 (16 h en CL 72, −0,18 ± 0,07), lo esperable por azar con tantas pruebas: las vecinas se leen en conjunto, no una a una.

**Cuándo se decide.** Mirada intermedia en la semana 4 (regla 4) y decisión en la semana 8: si el IC 95 % de la β conjunta de recorte queda por debajo de 0,53, el plan D5 puede recortar en el valle; por encima de 0,53, recortar no paga y solo se reasigna (por encima de 0,70 se confirma E7); si cubre 0,53, reasignar y extender 4 semanas si la decisión de recortar está en juego. En paralelo, la β de refuerzo decide si la reasignación paga con la contabilidad conservadora (≥ 0,62-0,66) y la β dominical si el recorte de domingos (+181 M COP al año en `simulacion_ahorro/`) es real.

**Duración recomendada: 8 semanas**, fuera de Carnaval, Semana Santa y vacaciones escolares (16 de diciembre a 31 de enero y junio-julio): del 19 de octubre al 13 de diciembre de 2026 si arranca ya (el calendario se regenera para otro lunes con `P2_INICIO=AAAA-MM-DD`), o del 15 de febrero al 11 de abril de 2027 saltando la Semana Santa. Doce semanas si 2026 resulta tan ruidoso como 2024 en la tarde.

## 7. Para Sobusa en una página

**Qué harían.** Durante 8 semanas, en CRA 54, unos días (sorteados de antemano y marcados en un calendario) salen 3 buses menos por hora entre las 9 y las 12 y 4 menos entre las 17 y las 20, con los buses repartidos parejos; otros días salen 4 buses más por hora entre las 14 y las 16; otros días las dos cosas (que es el plan que recomienda el estudio: mover buses del valle al pico), y otros días todo como siempre. En CL 72, la mitad de los días salen 2 buses más por hora entre las 12 y las 16. Cuatro domingos de ocho salen 4 buses menos por hora entre las 9 y las 14. El despachador solo necesita el calendario y una planilla con las salidas por hora de cada tipo de día. Si se confirma que Sobusa no publica horarios, no hay que avisar a los pasajeros: el servicio sigue siendo cada 5-7 minutos donde hoy es cada 4-5.

**Cuánto dura.** 8 semanas (37 días laborales y 8 domingos), por ejemplo del 19 de octubre al 13 de diciembre de 2026, con una revisión a las 4 semanas.

**Qué arriesgan.** En los días con menos buses, unos 570 pasajeros de la mañana y 520 de la tarde pueden no subir a un bus de Sobusa (y 820 cada domingo tratado): 22.900 en todo el piloto, el 0,3 % de los pasajeros del año de CRA 54, unos 73 millones de pesos en pasajes. Esos mismos días se ahorran 93 millones en conductores y kilómetros, así que, con el pago por hora, el recorte sale a cuenta aun perdiendo los pasajeros que E7 predice (con pago por producido el ahorro de conductor desaparece y los recortes no pagan ni en el piloto; sección 8). Los días con más buses cuestan 72 millones y, si atraen a la gente que hoy ve el bus lleno, los devuelven (23.300 pasajeros). En el peor caso (los buses de más no atraen a nadie) el piloto cuesta 52 millones; en el esperado, deja 22. Y si en cualquier momento se pierde más de lo esperado o los buses van hacinados, el piloto se detiene (cinco reglas de parada).

**Qué aprenden.** El número que hoy decide todo y nadie ha medido: cuántos pasajeros se pierden por cada bus que se deja de despachar en el valle (con un margen de ±0,1) y cuántos se ganan por cada bus que se añade en el pico. Con él: si los recortes moderados pagan (β por debajo de 0,53), si solo conviene reasignar (por encima de 0,53), si recortar los domingos es un ahorro real, y si lo que se pierde en una franja se recupera después o se va a la competencia. Además, se comprueba que el despacho con planilla funciona en la práctica, un paso previo a la consola de tiempo real.

**Qué necesitan.** Nada que no tengan: los registros de viajes y pasajeros de siempre, una bitácora de una línea por día y una persona que corra el análisis cada semana (`run.py --analizar`). Sobusa decide con la gerencia dos cosas antes de empezar: la fecha de arranque y si los días «normales» también siguen la planilla (recomendado).

## 8. Límites

- **β a corto plazo.** El piloto alterna días, así que mide la respuesta inmediata; la literatura encuentra elasticidades mayores a largo plazo (los pasajeros cambian de modo con el tiempo). Un recorte permanente perdería al menos lo que mide el piloto, probablemente más. El arrastre (días normales tras un día tratado) se comprueba, pero un efecto lento no se ve en 8 semanas.
- **Ruido de 2026.** Los cálculos de potencia usan el ruido de 2025; 2024 fue entre un 25 % y un 95 % más ruidoso según la franja. Si 2026 se parece a 2024, los IC se ensanchan y harían falta 12 semanas. El aumento de oferta de 2026 (E8: +14,6 % de viajes) también cambia el nivel de partida de la planilla: conviene recalcular las salidas habituales con las semanas previas al arranque.
- **Simulación con datos reales, efecto inyectado.** El bootstrap por semanas conserva el ruido real, pero el efecto se inyecta con el modelo pax × (n'/n)^β y sin heterogeneidad entre días; los placebos y las vecinas se comportan como se espera, pero la simulación no puede probar supuestos que no contiene (por ejemplo, que un recorte avisado cambie el comportamiento más que uno no avisado).
- **Traslado entre horas.** Con recortes por bloques de tres horas, el traslado a la hora siguiente queda dentro del bloque y la β medida es la neta del bloque; la vecina solo recibe lo de la última hora y no se detecta. Es lo que un plan por franjas necesita, pero no es la β «pura» de una hora.
- **Captación entre rutas.** Se mide si SILENCIO o CL 72 ganan pasajeros a la misma hora cuando CRA 54 recorta (captación interna), pero no se puede ver lo que se va a otras empresas o al transporte informal; esa pérdida es la que β recoge.
- **Cumplimiento.** El despacho es en tiempo real y sin horario publicado; si la planilla se cumple a medias, la VI sigue siendo insesgada (la primera etapa lo mide) pero pierde potencia. Los días con incidencias se excluyen por regla, no a criterio.
- **Costos.** Los COP usan los costos con fuente y el pago por hora; con pago por producido el ahorro de conductor desaparece y los recortes no pagan ni en el piloto (`costos/README.md`).

## 9. Archivos y cómo reproducir

Desde la carpeta del proyecto (≈ 3-5 min según el equipo: 260 s en la corrida original, 163 s en la de la verificación; solo archivos locales, nunca la base de datos):

```
PYTHONIOENCODING=utf-8 MPLBACKEND=Agg python experimentos/P2_piloto_beta/run.py
```

Variables opcionales: `P2_INICIO` (lunes de arranque del calendario; por defecto 2026-10-19), `P2_SEMANAS` (8), `P2_REPLICAS` (500). Semilla 42 en el sorteo del calendario y en la simulación.

| Archivo | Contenido |
|---|---|
| `run.py` | Todo el experimento y el modo `--analizar` para el piloto real (la misma función `analizar_piloto` en los dos usos). |
| `resultados.json` | Parámetros, franjas candidatas y elegidas, ruido, potencia (fórmula, diseño propuesto, tabla de semanas analíticas y calibradas), simulación (resumen, vecinas, EE analítico frente a empírico, ejemplo), calendario, riesgo y costo, reglas de parada, planilla. |
| `franjas_candidatas.csv` | Ruta × tipo de día × hora: salidas hoy, plan D5 original y con costos con fuente, diferencia, pasajeros, ciclo, km, intervalos. |
| `franjas_piloto.csv` | Las franjas del piloto hora a hora: habituales, tratadas, intervalos, pasajeros, cambio del plan, vecinas. |
| `ruido_residual.csv` | SD del residuo (por hora y diario), correlación dentro del día, asociación natural y SD de log(salidas) por franja, año (2025, 2024) y tabla (válidos, corregida). |
| `potencia.csv` | Semanas necesarias por objetivo × franjas × k (analíticas y calibradas), con días laborales, domingos y días tratados. |
| `simulacion.csv`, `simulacion_replicas.parquet`, `simulacion_vecinas.csv` | Resumen por escenario × β × franja × estimador (sesgo, EE empírico y estimado, cobertura, potencias, cuantiles), las 2.500 réplicas y los placebos y vecinas. |
| `riesgo_costo.csv`, `riesgo_costo_por_hora.csv` | Pasajeros en riesgo (β = 0,55 / 0,70 / 0,90 / 1,0) o ganables, pasajes, ahorro de conductor y de km, neto, por día tratado y en el piloto; detalle por hora. |
| `calendario_piloto.csv` | Las 8 semanas: fecha, día de la semana, festivo y planilla de cada ruta (N, R, F, RF; «—» = sin piloto). |
| `planilla_piloto.csv` | Para el despachador: por ruta, tipo de día y hora, salidas habituales y del día tratado, intervalos e instrucción. |
| `ejemplo_piloto_sintetico.csv`, `ejemplo_piloto_sintetico.analisis.csv` | Un piloto simulado (β = 0,70) en el formato del análisis semanal, y su análisis. |
| `fig1_franjas_candidatas.png` … `fig5_riesgo_costo.png` | Franjas candidatas; potencia (EE × semanas); simulación (β estimado por franja y estimador); calendario sorteado; riesgo y costo por día tratado. |
| `run.log` | Salida de la última ejecución. |

Insumos: `experimentos/E3_cuantiles_decision/tabla_salida.parquet`, `datos/progvehiculos.parquet` (tabla corregida), `datos/conteo_viajes.parquet` (ocupación), `costos/resultados/d5_reoptimizado_decisiones.parquet`, `costos/resultados/costos_unitarios.json`, `costos/resultados/operacion_2025_por_ruta.csv`, `experimentos/D1_optimizacion/parametros_operativos.parquet` (ciclo y km por ruta) y `costos/datos_operacion.py` (`perdida_asimetrica`).

## 10. Verificación

- **Cifras del README frente a los archivos.** Un script de trabajo recalculó desde `resultados.json`, `franjas_piloto.csv`, `potencia.csv`, `simulacion.csv`, `riesgo_costo.csv` y el calendario las 269 cifras citadas aquí (franjas, ruido, potencia analítica y calibrada, tabla 3 de la simulación, placebos, ejemplo, riesgo y costo, reglas de parada, calendario) y comprobó que aparecen en el texto con el mismo valor (formato español y el mismo redondeo que las tablas de `run.log`): 269 de 269. En la primera pasada corrigió dos redondeos a mano (1.092 pasajeros a las 17 h y 0,77 en el ejemplo dominical).
- **Reproducibilidad.** Dos corridas completas con semilla 42 (261 y 260 s) dieron las mismas β, EE y coberturas; el núcleo de estimación sobre numpy reprodujo coeficiente a coeficiente la primera versión sobre pandas (0,810 / 0,680 / 0,837 / 0,739 / 0,760 / 0,756 en un piloto sintético de prueba) y las secciones 1, 2, 3, 5 y 6 no dependen del número de réplicas (idénticas con 4 y con 500).
- **Controles internos del método.** (i) Con β inyectado la VI recupera 0,30 / 0,70 / 1,00 en todas las franjas y la MCO no (tabla 3). (ii) En el escenario de planilla fija, sin variación natural de la oferta, VI y MCO coinciden (0,69), como debe ser. (iii) Los placebos (hora de control, otras rutas, vecinas sin traslado) quedan en cero con 5-9 % de falsos positivos; el arrastre, en cero pero con 9-14 %, y así se declara. (iv) El EE analítico y el empírico difieren un 18 % en la β conjunta y la tabla de semanas se calibró con esa razón; los EE agrupados con corrección de muestra pequeña y t(G − 1) cubren el 90-94 %. (v) `run.py --analizar` sobre `ejemplo_piloto_sintetico.csv` reproduce `ejemplo_piloto_sintetico.analisis.csv` y emite la lectura automática («recortar no paga: solo reasignar» para una β conjunta de 0,74 [0,65; 0,83]).
- **Revisión independiente (13-oct-2026).** Un verificador distinto del autor revisó `run.py`, las salidas y este README y recalculó con código propio (statsmodels y numpy), sin consultar la base de datos ni tocar los archivos del experimento:
  - *Reproducción byte a byte.* Una copia de `run.py` con semilla 42 y 500 réplicas (163 s) regeneró los 12 CSV y `simulacion_replicas.parquet` idénticos (md5); `resultados.json` solo difiere en `tiempo_s`. `run.py --analizar` sobre una copia del ejemplo da la misma tabla y la misma lectura («recortar no paga: solo reasignar», 0,74 [0,65; 0,83]).
  - *Ruido residual.* Tabla corregida armada por su cuenta desde `tabla_salida.parquet` y `progvehiculos` (≥ 20 km, 0-300 pasajeros) y MCO con efectos fijos explícitos de día de la semana × hora y semana: las 24 celdas (6 franjas × 2 años × 2 tablas) coinciden con `ruido_residual.csv` (diferencia máxima 1e-14).
  - *Potencia.* EE = σ·√(1/nT + 1/nC)/|Δlog| con nT = nC = 18,05: EE 0,0746 / 0,0994 / 0,1633 / 0,1192 / 0,0710 y 0,0560 en la conjunta; potencias para distinguir 0,70 de 0,53 de 0,737 / 0,526 / 0,273 / 0,413 / 0,773 y 0,918, iguales al JSON. Tabla de semanas: 68 de 69 celdas iguales (la diferencia es un defecto del script del verificador) y factor de calibración 1,4037 reproducido.
  - *Simulación propia.* 100 réplicas con otra semilla (2024) y el sorteo y el estimador reescritos: con β = 0,7 la VI da 0,70-0,74 por franja y 0,712 en la conjunta, con EE empírico 0,065 (frente a 0,066); con β = 0,3 y 1,0, medias de 0,29-0,32 y 1,02-1,04; la MCO queda sesgada en 0,53-0,64, como en la tabla 3; potencia conjunta 0,92 (0,89 aquí).
  - *Riesgo y totales.* Precios recalculados desde `costos/parametros.py` (26.400 COP por bus-hora, 1.991 COP por km, tarifa 3.182) y pérdida recalculada también a mano: 566 / 524 / 822 pasajeros por día tratado; días tratados contados desde `calendario_piloto.csv` (18 / 18 / 4 / 20 / 19); totales de 22.904 pasajeros, 72,9 M en pasajes, 92,8 M de ahorro y −51,9 a +22,1 M en todo el piloto, el 0,301 % de los pasajeros anuales de CRA 54; β de refuerzo de equilibrio 0,659 y 0,615 (aquí 0,660 y 0,616). También coinciden el hacinamiento, los festivos dentro del calendario y las correlaciones con SILENCIO.
  - *Datos.* No usa `idconductor` ni la base de datos; los archivos nuevos no tienen datos personales.

  **Veredicto: confiable.** Las cifras son correctas y el README es honesto con sus límites. Hallazgos, todos de gravedad baja y de redacción:
  - El conteo decía «26 placebos, uno con |t| > 2», pero 4 de las 26 filas son totales del día: **corregido** a 22 placebos (sección 6).
  - La página gerencial afirmaba que el recorte sale a cuenta sin la salvedad del pago por producido: **corregido** (sección 7).
  - «Sobusa no publica horarios» se presentaba como hecho: **corregido**, ahora es un supuesto a confirmar con la empresa (secciones 0 y 7).
  - El tiempo de ejecución decía ≈ 5 min y el docstring de `run.py` ≈ 3 min: **corregido** en este README (3-5 min según el equipo); el docstring no se tocó.
  - Las semanas calibradas se redondean dos veces (ceil(semanas enteras × 1,40)), lo que puede añadir una semana (por ejemplo, 8 en vez de 7 para R1 con k = −3 y EE ≤ 0,10). Es conservador y no cambia la recomendación de 8 semanas: **se deja así** y queda anotado.
- **Lo que no se verificó.** La fórmula de pasajeros en riesgo es la misma función `perdida_asimetrica` de `costos/`, aunque la revisión independiente la comprobó también a mano. El calendario y la planilla se revisaron a mano (37 días laborales, 3 festivos fuera, balance por día de la semana en bloques de dos semanas, 4 de 8 domingos) y el verificador recontó desde el calendario los días tratados y las planillas (13 RF, 5 R, 7 F, 12 N).
