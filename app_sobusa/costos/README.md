# Costos y ahorros de las políticas de despacho de Sobusa

**Pregunta.** ¿Cuánto cuesta operar las rutas SILENCIO, CRA 54 y CL 72 (combustible, mantenimiento, llantas, lubricantes, conductor y costos fijos) y cuánto ahorraría Sobusa con los escenarios de despacho ya estudiados (D1, D5, D6, D3), descontando los pasajes que se pierden cuando salen menos buses (β de E7)?

Hasta ahora D1, D5 y D6 usaban tres supuestos sin fuente: **60.000 COP por bus-hora, 1.500 COP por km y tarifa de 3.000 COP**. Este módulo los reemplaza por valores con fuente y rango. No se consultó la base de datos: solo se usaron los Parquet de `datos/`, las salidas guardadas de los experimentos y fuentes web (consultadas el 6 de octubre de 2026). M COP = millones de pesos; las cifras de ahorro están a precios de 2026.

## Respuesta corta

1. **Cada km que se deja de recorrer ahorra unos 1.990 COP** (rango 1.450–2.720) a precios de 2026: 900 de ACPM, 735 de mantenimiento, 230 de llantas y 125 de lubricantes y filtros. El supuesto anterior (1.500 COP/km) se quedaba corto.
2. **Cada bus-hora que se deja de operar ahorra unos 26.400 COP de conductor** (rango 19.700–35.900), pero **solo si el conductor se paga por hora o por turno**. El valor usa la jornada de 42 h semanales vigente desde el 15-jul-2026 (Ley 2101 de 2021). Si se paga por producido (un porcentaje del recaudo), no se ahorra nada por hora.
   - Una bus-hora completa con sus ~16 km cuesta unos **57.900 COP** evitables con pago por hora y unos **31.500** con pago por producido.
   - La pareja de supuestos anterior (60.000 COP/h + 1.500 COP/km) implicaba 83.800 COP: **sobreestimaba el ahorro entre 45 % y 166 %**, porque el bus-hora de 60.000 incluía costos fijos que no se ahorran.
3. **Línea base 2025** (viajes que realmente corrieron): 10,4 millones de km, 658.800 buses-hora, unos 830.000 galones de ACPM y 7.600 t de CO2 fósil. El costo total es de unos **45.800 M COP** (4.390 COP/km; 3.306 COP por pasajero) con conductores formales pagados por hora, o 40.500 M con pago por producido. El ingreso neto por pasajes es de 39.300 M COP, así que el margen aproximado es de −16,5 % o −3 %, según el esquema. Es un chequeo grueso, no un estado financiero (ver Limitaciones).
4. **La optimización D5 (penalidad de 10.000 COP) ahorraría entre 1.520 y 2.850 M COP al año en combustible, mantenimiento, llantas y lubricantes** (central 2.090 M COP, de ellos 940 M en ACPM: 83.500 galones y 765 t de CO2). Con pago por hora se suman 1.200–2.180 M COP de conductor. **Pero con β = 0,70 pierde unos 4.720 M COP en pasajes** (3.830–5.990 si β va de 0,55 a 0,90 y la tarifa de 3.700 a 3.800; contabilidad conservadora). El neto queda en **−1.030 M COP al año** (−3.270 a +1.200) con pago por hora y en −1.690 M COP con pago por producido.
5. **Con los costos con fuente, D5 deja de pagar con β mayor que 0,53** (antes 0,85). S5 deja de pagar con β mayor que 0,63 (antes ≈ 1) y D5 con máx. 15 min con β mayor que 0,76 (antes nunca en el rango de E7). Con β = 0,70 y contabilidad conservadora:
   - solo **D5 con máx. 15 min (+390 M COP)** y el **giro corto en el punto 35 (+250 M COP)** quedan positivos;
   - **S1 (−1.710 M COP)** y **D5 con penalidad 30.000 (−2.460 M COP)** pierden en todo el rango.
6. **Si los pasajeros que se ganan al añadir salidas cuentan igual que los que se pierden** (contabilidad simétrica), los cinco escenarios de D1 y D5 ganan entre 1.530 y 2.530 M COP al año. El signo del resultado depende de esa pregunta y de β, más que de cualquier precio. Por eso el piloto para medir β (informe, recomendación 4) vale más que afinar el precio del ACPM, que es de los parámetros que menos pesan (solo la penalidad por edad del bus pesa menos).
7. **Reoptimizado con estos costos, D5 deja de recortar buses-hora y pasa a reasignar.** Con e = 0,5 programa 451 salidas/día (411 en el D5 original, 460 hoy) con casi los mismos buses-hora que hoy (−0,5 %): quita salidas en los valles de CRA 54 y SILENCIO y en domingos y festivos, y las pasa a CL 72 y a la franja de 13 a 15 h de los días laborales. Incluso con solo la caja del operador recorta apenas 1,5 %. El recorte de 9,6 % venía del supuesto de 60.000 COP por bus-hora (sección 6).
8. **Regularizar el despacho de CL 72 no cuesta ni ahorra caja**: las mismas salidas cada día, equiespaciadas. Baja la espera de 9,5 a 8,0 min, lo que equivale a unas 48.600 horas de espera al año, valoradas en ~340 M COP de valor social, no de caja.

## 1. Método y cómo reproducir

| Paso | Archivo | Qué hace |
|---|---|---|
| 1 | `parametros.py` → `parametros_costos.csv` | Parámetros con valor central, bajo, alto, unidad, tipo, fuente, URL, fecha y nota. |
| 2 | `datos_operacion.py` | Construye la línea base operativa 2025 y lee los cambios de cada escenario de las salidas guardadas de los experimentos. |
| 3 | `modelo_costos.py` | Calcula los costos unitarios, la línea base costeada, los ahorros por escenario, los rangos, el β de equilibrio, el tornado, las figuras y los valores para el planificador. Al final llama a `construir_excel.py` y `verificar_excel.py`. |
| 4 (opcional, ~17 min) | `reoptimizar_d5.py` | Vuelve a correr el optimizador de D5 (método exacto rápido) con los costos nuevos. Importa `experimentos/D5_optimizacion_milp/run.py` sin modificarlo. |

**Línea base operativa (`datos_operacion.py`).** Usa los viajes de 2025 que **realmente corrieron**: `distancia_recorrida` de al menos 20 km, **sin importar la marca `cancelada`**. Esa marca no es confiable: según E7, el 82 % de los viajes "cancelados" sí corrieron y unos 19.737 "válidos" no salieron.
- Viajes que corrieron: 173.881. De ellos, 13.299 estaban marcados como cancelados.
- Los 259 viajes con más de 100 km se recortan a la mediana de su ruta.
- Las horas son las de `fechainicio` a `fechafin`. Si la duración está fuera de 1,5–7 h, se imputa la mediana de la ruta y la hora de salida.
- El resultado es un poco mayor que las cifras previas del equipo (26.844 km/día en D1/D5), porque incluye los "cancelados" que corrieron y usa la distancia GPS en vez de la del catálogo.

| Ruta | Km/día | Km/año | Buses-hora/día | Pasajeros/año | Vehículos en uso/día | Km medio por viaje |
|---|---|---|---|---|---|---|
| SILENCIO | 8.762 | 3,20 M | 546 | 3,78 M | 48,3 | 63,1 |
| CRA 54 | 14.538 | 5,31 M | 934 | 7,60 M | 83,0 | 57,5 |
| CL 72 | 5.293 | 1,93 M | 325 | 2,48 M | 49,8 | 62,6 |
| **Total** | **28.593** | **10,44 M** | **1.805** | **13,86 M** | **181,1** | — |

**Flota (`vehiculos.parquet`; el consumo no está registrado).** Se agrupó por la marca escrita a mano, que tiene errores de digitación:

| Grupo | Participación en los km de las 3 rutas | Modelo medio |
|---|---|---|
| NQR (y "Chevrolet" sin línea) | 70–79 % | ≈ 2018 |
| NPR | 4–18 % | ≈ 2010 |
| FRR / Hino | 4–9 % | ≈ 2017 |
| B70 | 2–8 % | ≈ 2005 |
| Agrale | < 3 % | ≈ 2008 |

El rendimiento de cada ruta es la media armónica de los grupos, ponderada por km, con una penalidad por edad (`composicion_flota_por_ruta.csv`). Da 12,6 km/gal en el sistema.

**Costo de cada rubro y qué se puede evitar.**
- **Por km (evitable cuando se recortan salidas):** combustible = precio ÷ rendimiento, más mantenimiento, llantas y lubricantes.
- **Por bus-hora:** conductor = (SMMLV × múltiplo × factor prestacional + auxilio × 1,1766) × (1 + recargos) ÷ horas trabajadas al mes × horas pagadas por hora en ruta. Las horas al mes siguen la Ley 2101 de 2021: 195 h en 2025 (46 h semanales hasta el 15-jul-2025 y 44 h después) y 182 h en 2026 (42 h desde el 15-jul-2026).
  - Es evitable **solo con pago por hora o por turno**.
  - Con **pago por producido**, el conductor recibe el 20 % del recaudo neto. Quitar buses no ahorra conductor, pero cada pasaje perdido le quita a él ese 20 %, de modo que Sobusa pierde el 80 %.
- **Fijos por bus y año:** SOAT, pólizas RCC/RCE, revisión técnico-mecánica, impuesto (0 para servicio público), GPS, patio, administración y una anualidad de capital.
  - **No son evitables**, porque ninguna política baja los buses del pico (D6: 82 → 80 en CRA 54).

**Escenarios: de dónde sale cada número.**

| Escenario | Δ km y Δ buses-hora | Pasajeros perdidos (contabilidad conservadora) |
|---|---|---|
| S1, S5, D5 (10.000), D5 (30.000), D5 máx. 15 min | `experimentos/D5_optimizacion_milp/escenarios.csv`, fila Todas/Todos, columnas `km_ahorrados_anual` y `buses_hora_ahorrados_anual`, año 2025 completo. Los km son salidas × longitud del catálogo. | Fórmula de D1/D5/E7: pax × (1 − (n/n0)^β), solo en las horas donde se recorta. Para cada escenario se ajusta la curva **A × (1 − c^β)** a los seis puntos de `contabilidad_asimetrica.csv` (β de 0 a 0,78). La hoja de cálculo y el modelo usan esa misma curva, así que el β de 'Parámetros' es editable.<br>S1, S5 y D5: A se calibra con el cálculo exacto hora a hora de `decisiones_2025.parquet` para que la curva sea exacta en β = 0,70 (reproduce los 3.274 pasajeros/día de S1 que reporta E7). El error en 0,55 y 0,90 es como mucho de 0,06 % (`validacion_interpolacion_beta.csv`).<br>D5 30.000 y D5 máx. 15 min: solo el ajuste, porque D5 no guardó esas decisiones. |
| Giro corto en 35, CRA 54 (uno de cada dos buses, salidas de 7 a 15 h) | `experimentos/D6_simulador/escenarios_resumen.csv`, S0+G − S0: −35,6 buses-hora y −562 km por día laboral, × 245 días laborales de 2025. | Las 859 subidas diarias del lazo norte (D3, tabla de la sección 3) quedan con la mitad de la frecuencia: 859 × (1 − 0,5^β) = 272 / 330 / 399 por día laboral con β = 0,55 / 0,70 / 0,90 (A = 859 × 245/365, c = 0,5). **Supuesto de este módulo.** Además hay 562 bajadas forzadas por día, que no se valoran. |
| Regularizar CL 72 | D6, "S0 regularizada día a día" − S0: −0,43 buses-hora y 0 km por día. | Ninguno. Mismas salidas. |

**Rangos.** El valor central usa los parámetros centrales y β = 0,70.
- **Pesimista (bajo):** costos unitarios bajos (ACPM, mantenimiento, llantas, lubricantes, salario y horas pagadas), rendimiento alto, tarifa alta y β = 0,90.
- **Optimista (alto):** lo contrario, con β = 0,55.

El tornado mueve un parámetro a la vez sobre el neto de D5.

**Verificación.**
- La hoja de cálculo reproduce el modelo de Python en 249 comparaciones, con una diferencia relativa máxima de 1,1·10⁻¹⁴ (`resultados/verificacion_excel.csv`).
  - 84 de esas comparaciones se hacen después de cambiar β a 0,55 en 'Parámetros', para probar que β está conectado.
  - Las 337 fórmulas del libro se evalúan sin error.
  - LibreOffice no está instalado, así que las fórmulas se evaluaron con un intérprete propio (`verificar_excel.py`).
- La reoptimización de D5 con los supuestos originales reproduce exactamente a D5: 411,3 salidas/día, 60.754 buses-hora y 1.050.203 km ahorrados al año.
- Revisión independiente: sección 11.

## 2. Parámetros (central, rango y fuente)

La tabla completa, con URL, fecha y nota, está en `parametros_costos.csv` y en las hojas 'Parámetros' y 'Fuentes' de la calculadora. **Tipo**: F = fuente; F+C = cálculo a partir de fuentes; D = dato del proyecto; S = supuesto (reemplazar con datos de Sobusa).

| Parámetro | Central | Bajo – alto | Unidad | Tipo | Fuente principal |
|---|---|---|---|---|---|
| ACPM B10 Barranquilla, promedio 2025 | 10.585 | 10.410 – 10.861 | COP/gal | F+C | CREG, circulares de precios de referencia 122/2024 a 219/2025 |
| ACPM B10 Barranquilla, vigente oct-2026 | 11.291 | 10.951 – 11.900 | COP/gal | F+C (alto: S) | CREG, circulares 335 y 339 de 2026 (congelado en octubre). Sin precio especial para transporte público (el Decreto 1428 de 2025 lo excluye). |
| Rendimiento de la NQR urbana | 13,0 | 11,0 – 15,5 | km/gal | S | UPME, Balance de Energía Útil 2019 (buseta Barranquilla 16, bus 12); ARM Soacha dic-2025 (NPR 13); GIZ 2020. Ajustado por carga (~80 pasajeros por viaje) y pare-arranque. |
| Factores por grupo frente a la NQR | NPR 1,10; FRR/Hino 0,92; B70 y Agrale 0,85 | — | × | S | ANTP 2017 (micro / mini / midi); UPME BEU |
| Aumento de consumo por año de edad sobre 5 años | 0,75 % | 0,5 – 1 % | /año | S | Sin cifra verificada |
| Mantenimiento preventivo + correctivo (2025) | 700 | 450 – 1.050 | COP/km | S | ARM Soacha dic-2025 (buseta 1.010, flota de 27+ años); SICE-TAC 2018 camión ≤ 8 t ≈ 399 a 2025 |
| Llantas con reencauche y servicios (2025) | 220 | 150 – 310 | COP/km | F+C | ARM dic-2025 (229; 302 con servicios); precios Éxito oct-2026 |
| Lubricantes y filtros (2025) | 120 | 80 – 160 | COP/km | F | ARM dic-2025 (121,9); estudio de tarifa colectivo Soacha 2026 (159) |
| SMMLV 2025 / 2026 | 1.423.500 / 1.750.905 | — | COP/mes | F | Decreto 1572 de 2024; Decretos 1469 de 2025 y 0159 de 2026 (el valor de 2026 está sujeto a fallo del Consejo de Estado) |
| Auxilio de transporte 2025 / 2026 | 200.000 / 249.095 | — | COP/mes | F | Decretos 1573 de 2024 y 1470 de 2025 |
| Salario del conductor | 1,3 | 1,0 – 1,6 | × SMMLV | S | Sin cifra publicada para Barranquilla |
| Factor prestacional | 1,44 | 1,42 – 1,56 | × | F+C | Pensión, ARL IV (Decreto 768 de 2022), caja, cesantías, intereses, prima y vacaciones con exoneración (art. 114-1 ET), más dotación |
| Recargos nocturno y dominical | 0,16 | 0,12 – 0,25 | fracción | D | 18,1 % de los buses-hora 2025 son de 19 a 6 h (recargo 35 %, Ley 2466 de 2025) y 11,4 % en domingo o festivo (80–90 %) |
| Horas trabajadas al mes, 2025 | 195 | 190 – 230 | h | F+C | Ley 2101 de 2021: 46 h semanales hasta el 15-jul-2025 y 44 h después (45,1 h × 52/12). La Ley 2466 de 2025 solo cambió los recargos y la jornada nocturna. El alto de 230 h es un supuesto. |
| Horas trabajadas al mes, 2026 | 182 | 182 – 230 | h | F | Ley 2101 de 2021: 42 h semanales desde el 15-jul-2026 (42 × 52/12). Es el máximo ordinario legal, por eso también es el bajo. El alto de 230 h es un supuesto. |
| Horas pagadas por hora en ruta | 1,16 | 1,10 – 1,30 | × | D | D2: descanso de 37 min por vuelta |
| Pago por producido: parte del conductor | 20 % | 15 – 25 % | del recaudo | S | Los ayudantes reciben ≈ 10 % (El Heraldo 2019) |
| SOAT servicio público urbano 2025 | 640.300 | – 673.300 (2026) | COP/año | F | Previsora / Fasecolda, código 810 |
| Pólizas RCC/RCE | 3,5 M | 2 – 6 M | COP/año | S | Obligatorias (Decreto 1079 de 2015); la prima no está publicada |
| Revisión técnico-mecánica | 490.000 | 450.000 – 535.000 | COP/año | F+C | Grupo R5, tarifas 2026 |
| Impuesto vehicular | 0 | 0 – 300.000 | COP/año | F | Ley 488 de 1998, art. 141 (excluye el servicio público) |
| GPS / patio / administración | 80.000 / 290.000 / 750.000 | ver CSV | COP/mes | S | Sin cifras publicadas |
| Vehículo nuevo (≈ 90 % busetas) | 390 M | 320 – 480 M | COP | S | Cotización de NPR 2025 carrozada por 456 M (Colombia Compra, jul-2025); buses del Factor de Calidad ≈ 600 M |
| Vida útil / salvamento / tasa real | 20 años / 30 % / 11 % | 15–20 / 20–30 % / 10–12 % | — | F / F / S | Ley 105 de 1993; estudio de tarifa de Soacha 2026; La República jul-2026 |
| Tarifa 2025 / 2026 (día laboral) | 3.300 / 3.700 | 3.400 / 3.800 en domingo y festivo | COP | F | AMB, Resolución Metropolitana 396-2024; alza del 19-ene-2026 (El Tiempo, El Espectador) |
| Parte de la tarifa que retiene el operador | 0,86 | 0,83 – 0,90 | × | F+C | Res. AMB 396-2024: 3.300 − FET 200 − factor de calidad 100 − 1 % de la autoridad − 2,5 % de recaudo − ≤ 50 del socio tecnológico ≈ 2.830 |
| Factor de emisión del ACPM B10 (parte fósil) | 9,16 | 8,96 – 10,18 | kg CO2/gal | F+C | UPME/FunNatura, FECOC 2016 (diésel 10,18) |
| IPC 2025 (para pasar los rubros de 2025 a 2026) | 5,1 % | — | — | F | DANE (Portafolio, 8-ene-2026) |
| Valor de una hora de espera | 7.000 | 3.500 – 14.000 | COP/h | S | Supuesto de D5. Solo alimenta la columna de valor social, no la caja. |
| β (elasticidad a las salidas) | 0,70 | 0,55 – 0,90 | × | D | E7. Editable en la hoja: mueve los pasajeros perdidos de todos los escenarios. |

## 3. Costos unitarios que reemplazan los supuestos

| Concepto | 2025 | 2026 (central) | 2026 (rango) | Supuesto anterior |
|---|---|---|---|---|
| Combustible por km (12,6 km/gal) | 842 | 898 | — | — |
| Mantenimiento + llantas + lubricantes por km | 1.040 | 1.093 | 715 – 1.598 | — |
| **Costo evitable por km** | **1.882** | **1.991** | **1.445 – 2.716** | 1.500 |
| Hora de conductor (195 h/mes en 2025; 182 h/mes en 2026) | 17.252 | 22.759 | 17.938 – 27.580 | — |
| **Conductor por bus-hora en ruta, pago por hora o turno** | **20.012** | **26.400** | **19.732 – 35.854** | 60.000 (incluía fijos) |
| Conductor por bus-hora, pago por producido | 0 | 0 | — | — |
| Fijo por bus y año (no evitable; incluye 47,2 M de anualidad de capital) | 65,2 M | 68,5 M | — | — |
| Fijo por bus-hora (referencia) | 19.719 | — | — | — |
| Ingreso neto por pasajero | 2.838 | 3.182 | 3.071 – 3.420 | 3.000 |

El rango del ingreso neto combina la tarifa (3.700–3.800) con la parte que retiene el operador (0,83–0,90). El rango del conductor solo mueve el salario y las horas pagadas por hora en ruta; si también se mueven el factor prestacional, los recargos y las horas al mes, es más ancho (sección 11).

**Recomendación para D1, D5, D6 y el planificador:**
- **2.000 COP/km**;
- **26.400 COP por bus-hora** con pago por hora, o 0 COP con pago por producido;
- una tarifa neta de **3.180 COP**.

Los valores centrales, bajos y altos están en `resultados/costos_para_planificador.json`.

## 4. Línea base 2025 por ruta (precios 2025, valores centrales)

| | SILENCIO | CRA 54 | CL 72 | Total |
|---|---|---|---|---|
| Km/año | 3,20 M | 5,31 M | 1,93 M | 10,44 M |
| Buses-hora/año | 199.273 | 340.936 | 118.614 | 658.823 |
| Rendimiento (km/gal) | 12,6 | 12,5 | 12,8 | 12,6 |
| Galones de ACPM/año | 253.531 | 425.304 | 151.379 | 830.214 |
| CO2 fósil (t/año) | 2.322 | 3.896 | 1.387 | 7.605 |
| Combustible (M COP) | 2.684 | 4.502 | 1.602 | 8.788 |
| Mantenimiento (M COP) | 2.239 | 3.714 | 1.352 | 7.305 |
| Llantas (M COP) | 704 | 1.167 | 425 | 2.296 |
| Lubricantes y filtros (M COP) | 384 | 637 | 232 | 1.252 |
| Conductor, pago por hora (M COP) | 3.988 | 6.823 | 2.374 | 13.185 |
| Fijos, flota equivalente de 53 / 91 / 55 (M COP) | 3.464 | 5.953 | 3.574 | 12.991 |
| **Costo total (M COP)** | **13.461** | **22.796** | **9.560** | **45.817** |
| Costo por km (COP) | 4.209 | 4.296 | 4.948 | 4.390 |
| **Costo por pasajero (COP)** | **3.561** | **3.000** | **3.853** | **3.306** |
| Ingreso neto por pasajes (M COP) | 10.728 | 21.566 | 7.042 | 39.336 |
| Margen aproximado, pago por hora | −25,5 % | −5,7 % | −35,8 % | −16,5 % |
| Margen aproximado, pago por producido (20 %) | −8,3 % | +5,9 % | −22,0 % | −3,0 % |

![Costos por ruta](resultados/fig1_costos_por_ruta.png)

**Cómo leer el margen.** Los costos siguen el estándar de un estudio tarifario: conductores formales y capital a precio de vehículo nuevo. Ese estándar supera lo que retiene el operador, sobre todo en CL 72, que lleva pocos pasajeros por km. Es coherente con el alza de tarifa de 2026 (+12 %, justificada por la AMB con costos), pero no prueba pérdidas, por cuatro razones:
- Si se paga por producido, el costo baja a 40.500 M COP.
- Parte de la flota está depreciada; hay modelos 2003–2010.
- El ingreso podría estar subcontado: los contadores son consistentes solo en el 74–78 % de los viajes (E3), y E8 encontró brechas entre `timbradas` y `progvehiculos`.
- Hay rutas de Sobusa que no están en estos datos.

CRA 54 es la ruta más eficiente (3.000 COP por pasajero) y CL 72 la más cara (3.853).

## 5. Ahorro por escenario (M COP/año, precios 2026, β = 0,70, contabilidad conservadora)

| Escenario | Δ km/año | Δ buses-hora/año | Galones ahorrados | CO2 evitado (t) | Ahorro por km [rango] | Ahorro de conductor, pago por hora [rango] | Pasajes perdidos [rango] | **Neto, pago por hora [rango]** | **Neto, pago por producido [rango]** | Neto simétrico¹ | Espera valorada² |
|---|---|---|---|---|---|---|---|---|---|---|---|
| S1 regla uniforme (D1) | 629.896 | 31.638 | 50.108 | 459 | 1.254 [910; 1.711] | 835 [624; 1.134] | 3.803 [3.074; 4.837] | **−1.713** [−3.303; −229] | **−1.788** [−2.960; −748] | +1.722 | −122 |
| S5 máx. 15 min (D1) | 1.139.177 | 64.580 | 90.622 | 830 | 2.268 [1.646; 3.094] | 1.705 [1.274; 2.315] | 4.382 [3.548; 5.562] | **−409** [−2.641; +1.861] | **−1.237** [−2.803; +256] | +2.239 | −666 |
| D5 penalidad 10.000 | 1.050.203 | 60.754 | 83.544 | 765 | 2.091 [1.518; 2.853] | 1.604 [1.199; 2.178] | 4.724 [3.829; 5.989] | **−1.029** [−3.273; +1.202] | **−1.688** [−3.274; −210] | +1.939 | −469 |
| D5 penalidad 30.000 | 295.940 | 11.019 | 23.542 | 216 | 589 [428; 804] | 291 [217; 395] | 3.342 [2.697; 4.259] | **−2.462** [−3.614; −1.498] | **−2.084** [−2.979; −1.354] | +1.528 | +105 |
| D5 máx. 15 min | 1.639.033 | 99.119 | 130.385 | 1.194 | 3.264 [2.369; 4.452] | 2.617 [1.956; 3.554] | 5.491 [4.458; 6.944] | **+390** [−2.619; +3.548] | **−1.129** [−3.186; +886] | +2.530 | −1.138 |
| Giro corto en 35, CRA 54 (D6) | 137.646 | 8.720 | 11.032 | 101 | 275 [200; 375] | 230 [172; 313] | 257 [212; 319] | **+248** [+52; +475] | **+69** [−56; +205] | +248 | −144 |
| Regularizar CL 72 (D6) | 0 | 105 | 0 | 0 | 0 | 3 | 0 | **+3** | 0 | +3 | **+340** |

¹ Neto simétrico: los pasajeros ganados donde se añaden salidas cuentan igual que los perdidos (contabilidad lineal de D5 con β = 0,70) y el conductor se paga por hora.

² Espera valorada: valor social del cambio en la espera media, con 7.000 COP por hora de espera. No es caja y no entra en los netos; un valor negativo indica más espera. Usa la espera media de D5 (35.267 pasajeros/día) y la de D6 (CRA 54 y CL 72, días laborales).

Desglose del ahorro por km del escenario D5 (10.000), en M COP/año: combustible 943, mantenimiento 773, llantas 243 y lubricantes 132.

![Ahorro por escenario](resultados/fig2_ahorro_por_escenario.png)

## 6. Qué cambia en las conclusiones de D5

**β de equilibrio** (por encima de este valor el escenario pierde dinero; contabilidad conservadora; `resultados/beta_equilibrio.csv` y columnas AB–AC de 'Escenarios'):

| Escenario | Supuestos de D5 (60.000 / 1.500 / 3.000) | Costos con fuente, pago por hora | Costos con fuente, pago por producido |
|---|---|---|---|
| S1 | 0,54 | **0,36** | 0,27 |
| S5 | ≈ 1,0 (D5: > 1) | **0,63** | 0,43 |
| D5 penalidad 10.000 | 0,85 | **0,53** | 0,36 |
| D5 penalidad 30.000 | 0,23 | **0,17** | 0,14 |
| D5 máx. 15 min | 1,29 (nunca en el rango de E7) | **0,76** | 0,50 |
| Giro corto en 35 | ninguno | **2,0** (nunca en el rango) | 1,04 |

- **El ahorro operativo de D5 se reduce de 5.221 M COP/año a 3.695 M con pago por hora, o a 2.091 M con pago por producido.** Además, el pasaje perdido vale más: 3.182 COP netos frente a 3.000. Por eso el "rentable hasta β ≈ 0,85" del informe pasa a **β ≈ 0,53**, casi el valor de la literatura (0,5) y por debajo del rango de E7 (0,55–0,90).
- **Lo que más pesa en el neto de D5** (tornado, `resultados/tornado_D5.csv`):
  1. β, de −133 a −2.137 M COP (−2.140 con el cálculo exacto de `simulacion_ahorro/`; el tornado interpola la curva A(1 − c^β));
  2. el salario del conductor, de −1.369 a −689;
  3. el mantenimiento por km, de −1.305 a −643;
  4. la parte de la tarifa que retiene el operador, de −864 a −1.249;
  5. las horas trabajadas al mes y el rendimiento.
  
  **El precio del ACPM es de los que menos mueven el neto**, entre −1.058 y −978 M COP; solo la penalidad por edad del bus mueve menos (−1.037 a −1.021).
- Conclusiones que **no** cambian: D5 sigue siendo mejor que S1, porque con el mismo intervalo máximo pierde menos por cada bus-hora ahorrado. El máximo de 15 min sigue siendo la palanca de mayor ahorro. La penalidad de 30.000 sigue dependiendo de que los buses añadidos en CL 72 atraigan pasajeros.

![Tornado](resultados/fig3_tornado_D5.png)

**D5 reoptimizado con los costos nuevos** (`reoptimizar_d5.py`; año 2025 con el pronóstico a 7 días; método exacto de D5; 1.991 COP/km, 26.400 COP por bus-hora con 182 h/mes y tarifa neta de 3.182).

| Corrida | Salidas/día | Buses-hora/día | Buses-hora ahorrados/año | Km ahorrados/año | Espera (min) | Pasajeros sobre la capacidad/día | Pasajeros perdidos/día (β 0,70, conservadora) | Neto conservador, pago por hora (M COP/año) | Neto simétrico, pago por hora (M COP/año) |
|---|---|---|---|---|---|---|---|---|---|
| S0 oferta real | 459,9 | 1.731,7 | — | — | 4,43 | 317 | — | — | — |
| D5 original (60.000 / 1.500 / 3.000; e = 0,5) | 411,3 | 1.565,2 | 60.754 | 1.050.203 | 4,74 | 530 | 4.068 | −1.029 | +1.939 |
| Costos nuevos, pago por hora, e = 0,5 | 450,9 | 1.722,5 | 3.348 | 207.275 | 4,30 | 267 | 2.864 | −2.825 | +1.600 |
| Costos nuevos, pago por hora, e = 0,70 | 514,3 | 1.971,6 | −87.550 | −1.130.081 | 3,80 | 223 | 2.062 | −6.957 | +1.162 |
| Solo caja del operador (espera = 0; sobrecarga = pasaje neto), pago por hora, e = 0,70 | 444,2 | 1.705,0 | 9.739 | 358.418 | 4,54 | 486 | 3.867 | −3.521 | +2.168 |
| Costos nuevos, pago por producido, e = 0,70 | 609,8 | 2.305,7 | −209.523 | −3.155.577 | 3,20 | 209 | 908 | −12.870 (−7.128 por producido) | −842 |

Un valor negativo de ahorro significa que se añaden buses-hora o km. Neto simétrico: los pasajeros ganados donde se añaden salidas cuentan igual que los perdidos (contabilidad lineal de D5 con β = 0,70).

- **Con los costos con fuente, D5 ya no recorta buses-hora.**
  - Con e = 0,5 reasigna: 451 salidas/día con casi los mismos buses-hora que hoy (−0,5 %), pero con menos espera (4,30 min) y menos sobrecarga (267 pasajeros/día frente a 317; horas con factor de carga > 1: 6,8 % frente a 11,7 %).
  - **Dónde reasigna** (`d5_reoptimizado_decisiones.parquet`, salidas por día promedio del año): CL 72 sube de 80,8 a 103,7 (sobre todo de 10 a 18 h, por el intervalo máximo de 10 min); CRA 54 baja de 247,0 a 226,7 (valles de 7 a 12 h y de 16 a 19 h, domingos y festivos) y sube de 45,3 a 49,3 de 13 a 15 h; SILENCIO baja de 132,1 a 120,5. En días laborales, la franja de 13 a 15 h de las tres rutas pasa de 88,7 a 110,2 salidas por día laboral.
  - Con e = 0,70, o con pago por producido, añade oferta: +14 % y +33 % de buses-hora.
  - Aun mirando solo la caja del operador, el óptimo recorta apenas 1,5 % de los buses-hora (444 salidas/día).
  
  **El recorte de 9,6 % de buses-hora de D5 venía del supuesto de 60.000 COP por bus-hora.** Esto respalda con números la recomendación 2 del informe: reasignar, no recortar. Es coherente con el tornado de D5: con 40.000 COP por bus-hora, D5 ya subía de 1.572 a 1.663 buses-hora por día, y el valor con fuente, ~26.400 COP, está por debajo de ese extremo.
- **Ojo con la contabilidad.** Estas soluciones pasan salidas del valle a las horas cargadas, y el objetivo de D5 acredita los pasajeros ganados (contabilidad simétrica). Con la contabilidad conservadora todas pierden, entre 2.800 y 12.900 M COP al año: los recortes en el valle sí pierden pasajeros y las ganancias no se cuentan. Con la simétrica, las de pago por hora ganan entre 1.162 y 2.168 M COP al año. Si esas ganancias existen es justo lo que debe medir el piloto.
- **Ajuste a D6.** Con estos costos, D5 sigue ganando a S1 en CRA 54 mientras la hora de espera valga menos de unos 22.900 COP con pago por hora (12.200 con producido), frente a ~33.500 con los supuestos según este cálculo (el propio D6 reporta ~32.000–32.400; umbrales calculados con 25.289 COP por bus-hora; con 26.400 suben un poco). El valor usado (7.000) queda por debajo de ambos umbrales, así que el orden de D6 se mantiene.
- **Sobre `d5_reoptimizado.csv`.** Se volvió a generar el 6-oct-2026 con 182 h/mes (26.400 COP por bus-hora), con las columnas de contabilidad simétrica y el Parquet de decisiones hora a hora (`d5_reoptimizado_decisiones.parquet`, columnas `x_corrida_0` a `x_corrida_4` en el orden de la tabla). La corrida con los supuestos originales sigue reproduciendo D5 exactamente.

## 7. Conclusiones en lenguaje sencillo

- **Un km evitado vale unos 2.000 COP; una hora de bus evitada, unos 58.000 COP si el conductor cobra por hora y unos 31.500 si cobra por producido.** Un pasajero perdido le cuesta a Sobusa unos 3.180 COP. Quitar un bus de una hora del valle ahorra ~58.000 COP y solo se paga si se pierden menos de unos 18 pasajeros, o menos de unos 12 con pago por producido (31.500 ÷ 80 % de 3.180).
- **D5 ahorraría entre 1.500 y 2.850 M COP al año en combustible, mantenimiento, llantas y lubricantes** (central ~2.090 M), unos 83.500 galones de ACPM y 765 t de CO2 al año. Si el conductor se paga por hora, se suman 1.200–2.180 M de conductor. **Pero** con la elasticidad medida (β ≈ 0,70) los pasajes perdidos (unos 4.700 M COP; 3.800–6.000 con β entre 0,55 y 0,90) superan ese ahorro, salvo que los pasajeros ganados en las horas reforzadas compensen.
- **Recortar en bloque (S1) no paga con ningún costo razonable.** Las variantes que sí pueden pagar son las de intervalo máximo de 15 min (D5 máx. 15 min, S5) y el giro corto en 35, siempre que se acepte más ocupación y espera.
- **Antes de recortar, Sobusa debe saber cómo paga a sus conductores.** Con pago por producido, el ahorro de recortar se reduce a la mitad, porque solo se ahorran los km.
- **Lo barato y seguro:** regularizar el despacho de CL 72 (−1,5 min de espera sin costo; ~340 M COP al año de valor social) y reasignar salidas sin cambiar el total.

## 8. Limitaciones

- **No hay datos de costos de Sobusa.** El rendimiento, el mantenimiento, los seguros, la administración y el pago de conductores son supuestos anclados en estudios de otras ciudades (Soacha, con flota más vieja y en altura), en fuentes nacionales (UPME, SICE-TAC) y en precios de mercado.
- **El mantenimiento se trata como 100 % proporcional a los km.** En la práctica una parte depende del tiempo, así que el ahorro por km podría ser menor. Tampoco se modela que los buses más llenos de D5 consumen algo más por km (+6–8 % por tonelada) ni el ciclo 4 min más largo que encontró D6.
- **Fijos sin cambio.** El pico de buses en ruta no baja (D6), así que no se ahorran SOAT, pólizas ni capital. Los domingos D5 usa casi la mitad de los buses, pero eso solo ahorra si la flota se reduce o se arrienda.
- **Pasajes.** β viene de fallas imprevistas; un recorte anunciado podría tener β de 0,4–0,5 (E7), y entonces S5 y D5 pagan. La contabilidad conservadora no cuenta pasajeros ganados.
  - En la hoja, los pasajeros perdidos siguen la curva A × (1 − c^β), exacta en β = 0,70 para S1, S5 y D5 y aproximada (≤ 0,06 %) en el resto del rango. Fuera de 0,55–0,90 es una extrapolación.
  - En el giro corto, aplicar β a las subidas del lazo es un supuesto propio. Las 562 bajadas forzadas por día no se valoran.
  - Los días de D6 se anualizan con 245 días laborales; el giro en sábado (D3) no se cuenta.
- **Km de los escenarios.** Son salidas × longitud del catálogo (D5): 62,9 / 56,4 / 57,0 km. Los viajes reales miden 63,1 / 57,5 / 62,6 km según el GPS, así que el ahorro en km podría ser hasta 10 % mayor en CL 72.
- **Precios y jornada 2026.**
  - El SMMLV de 2026 está sujeto a un fallo del Consejo de Estado.
  - Las 182 h/mes rigen desde el 15-jul-2026; de enero a julio de 2026 eran 44 h semanales (≈ 190 h/mes).
  - El ACPM está congelado en octubre de 2026.
  - La resolución de tarifa 2026 del AMB no se ubicó, así que los descuentos SIBUS de 2026 se suponen iguales a los de 2025.
  - El CO2 cuenta solo la parte fósil del B10.
- **Margen.** Es un orden de magnitud: rutas parciales de Sobusa, pasajeros posiblemente subcontados y estructura propietario–empresa no modelada.

## 9. Qué debe entregar Sobusa para reemplazar los supuestos

1. **Combustible:** facturas o tanqueos por vehículo y mes (galones), con el odómetro o los km GPS. Con eso se obtiene el rendimiento real por grupo y edad.
2. **Mantenimiento:** órdenes de trabajo con repuestos y mano de obra por vehículo, separando preventivo y correctivo, más compras de llantas y reencauches y cambios de aceite y filtros.
3. **Conductores:** el esquema de pago (salario, por vuelta o porcentaje del producido), las horas y turnos reales, cuántos conductores hay por bus y el costo de nómina con prestaciones.
4. **Fijos:** primas de las pólizas RCC/RCE, cuota de administración o rodamiento, patio, GPS y plataforma SIBUS, financiación de los vehículos y precio de compra de la flota reciente.
5. **Ingresos:** el recaudo neto por pasajero después de los descuentos del SIBUS (FET, factor de calidad, comisiones) y el reparto de la tarifa integrada con Transmetro.
6. **Datos:** aclarar la marca `cancelada` (E7), qué vehículos atienden otras rutas y la flota total adscrita.

## 10. Archivos

| Archivo | Contenido |
|---|---|
| `calculadora_ahorros.xlsx` | Calculadora con fórmulas vivas. Hojas: 'Parámetros' (celdas amarillas editables y costos unitarios derivados), 'Línea base', 'Escenarios', 'Sensibilidad' (incluye el tornado como valores) y 'Fuentes'.<br>Al cambiar el precio del ACPM, el rendimiento, el salario o **β**, todo se recalcula: β mueve los pasajeros perdidos de cada escenario (curva A × (1 − c^β)). El valor de la hora de espera alimenta la columna "valor social de la espera", que no es caja.<br>'Escenarios' también calcula el **β de equilibrio** de cada escenario, con pago por hora y por producido. |
| `parametros_costos.csv` | Parámetros con rango, fuente, URL, fecha y nota (separador `;`, decimales con coma). |
| `modelo_costos.py`, `parametros.py`, `datos_operacion.py`, `construir_excel.py`, `verificar_excel.py`, `reoptimizar_d5.py` | Código reproducible. |
| `resultados/costos_para_planificador.json` | Valores por defecto para el planificador (P1), D1, D5 y D6, con bajo y alto: `costo_bus_hora` (pago por hora), `costo_km` y `tarifa_neta_2026`, más β y la participación del producido. |
| `resultados/linea_base_2025.csv`, `linea_base_2025_a_precios_2026.csv`, `operacion_2025_por_ruta.csv`, `composicion_flota_por_ruta.csv` | Línea base operativa y costeada. |
| `resultados/escenarios_insumos.csv`, `ahorros_por_escenario.csv`, `beta_equilibrio.csv`, `tornado_D5.csv`, `costos_unitarios.csv/json`, `d5_reoptimizado.csv`, `d5_reoptimizado_decisiones.parquet` | Escenarios (con A y c de la curva de β), ahorros, rangos y sensibilidad; D5 reoptimizado con los costos nuevos (182 h/mes) y sus decisiones hora a hora (sección 6). |
| `resultados/validacion_interpolacion_beta.csv`, `verificacion_excel.csv`, `modelo_costos.log`, `reoptimizar_d5.log`, `resumen.json` | Verificaciones y registros de ejecución. |
| `resultados/fig1_costos_por_ruta.png`, `fig2_ahorro_por_escenario.png`, `fig3_tornado_D5.png` | Figuras. |

## 11. Verificación independiente (6-oct-2026)

Revisión adversarial hecha con scripts propios (sin conectarse a la base de datos y sin importar el código del módulo, salvo para volver a correrlo en una copia). **Veredicto: confiable con reservas.** Las cifras de la respuesta corta se reproducen; las reservas cambian matices, no el signo de ninguna conclusión. Las cifras de esta sección son las de la versión verificada (190 h/mes); las correcciones aplicadas después están al final.

**Fuentes abiertas y valores confirmados.**
- CREG, circular 219 de 2025 (19-dic-2025): ACPM Barranquilla 10.861 COP/gal desde el 20-dic-2025. Circulares 335 (26-ago-2026) y 339 (28-ago-2026): 11.291 COP/gal de junio a agosto de 2026 (Bogotá 11.616). El promedio 2025 de 10.585 se reproduce con la senda de precios por días.
- AMB, Resolución Metropolitana 396-2024 (30-dic-2024): 3.300 COP día hábil y 3.400 domingo y festivo; 200 de FET y 100 de factor de calidad; SIBUS hasta 1 % (autoridad), hasta 2,5 % (recargas) y hasta 50 COP (aliado tecnológico). Retención: 2.834 COP de 3.300 = 0,86.
- El Tiempo (21-ene-2026): 3.700 / 3.800 COP desde el 19-ene-2026.
- UPME/FunNatura, FECOC 2016, tabla 5: diésel 74.233 kg CO2/TJ = 10,180 kg CO2/gal (B10 fósil = 9,16).
- ARM, estudio de costos TPM Soacha 2026 (dic-2025): buseta NPR 1998, 13 km/gal; mantenimiento 1.010 COP/km; lubricantes 121,93 (bus 140,81); llantas con servicios 302,18.
- SMMLV 2025 de 1.423.500 (Decreto 1572 de 2024) con auxilio de 200.000; SMMLV 2026 de 1.750.905 (Decreto 1469 de 2025, suspendido el 12-feb-2026; Decreto 0159 de 19-feb-2026); IPC 2025 de 5,1 % (Portafolio, 8-ene-2026); SOAT 2025 código 810 de 640.300 (419.700 + 218.200 + 2.400).
- **No verificables:** el estudio de tarifa del colectivo de Soacha (la página devuelve 403; de él salen el salvamento de 30 % y algunos rangos); la cifra de SICE-TAC (262 COP/km de 2018), que no tiene URL; el congelamiento del ACPM en octubre de 2026 y las tarifas de Grupo R5.

**Cita corregida.** La reducción a 44 y 42 horas semanales es de la Ley 2101 de 2021, no de la Ley 2466 de 2025 (que cambió los recargos y la jornada nocturna desde las 19 h). Desde el 15-jul-2026 rigen 42 h, así que a precios de 2026 el valor coherente sería 182 h/mes y no 190: el conductor costaría ~26.400 COP por bus-hora (+4 %) y el neto de D5 subiría unos 70 M COP (tornado). La cita de `parametros.py` (y, por tanto, del CSV y de la hoja 'Fuentes') sigue diciendo Ley 2466 y debe corregirse allí. **Aplicado después de la verificación** (ver al final).

**Línea base 2025, recalculada desde `progvehiculos.parquet`.**
- Con un filtro propio estricto (20–100 km **y** duración de 0,5 a 6 h, sin imputar): 151.754 viajes, 9,05 M km, 571.400 buses-hora y 720.000 galones, un 13 % menos que el autor.
- La diferencia se explica casi entera por los 13.299 viajes marcados como cancelados que sí corrieron: **ninguno tiene `fechafin`**, aunque llevan 76 pasajeros y 64 km de media (el 99 % tiene pasajeros). Si se conservan y se les imputa la duración media de la ruta, quedan 10,42 M km (−0,2 %), 654.100 buses-hora (−0,7 %) y 829.000 galones, en línea con el autor.
- En total, el 13,6 % de los viajes (23.700) tiene horas imputadas: sin `fechafin`, más de 7 h o menos de 1,5 h.

**Costos unitarios y escenarios recalculados** (versión verificada). Leídos de `parametros_costos.csv`, salen 1.991 COP/km (898 + 736 + 231 + 126), 25.289 COP por bus-hora, una tarifa neta de 3.182 y 56.800 COP por bus-hora completa (15,8 km), frente a 83.800 con los supuestos.
- Los Δ km y Δ buses-hora de D5 son anuales (por día × 365) y salen de las columnas correctas.
- Los pasajeros perdidos, recalculados hora a hora desde `decisiones_2025.parquet`, coinciden con E7 (S1: 3.274,4 por día con β = 0,70).
- Los netos de S1, S5, D5 y el giro corto coinciden al millón (−1.749, −481, −1.097 y +238). D5 30.000 y D5 máx. 15 min dan −2.464 y +299 con interpolación lineal en β, frente a −2.474 y +280 con el ajuste A·(1 − c^β).
- El β de equilibrio de D5, calculado con las decisiones exactas, es 0,52.

**Reoptimización de D5.** `reoptimizar_d5.py` importa `run.py` de D5 sin modificarlo; al importarlo no se escribe nada. Las corridas cambian solo los parámetros declarados y se comparan con el mismo S0. La corrida con los supuestos originales reproduce D5 exactamente, y las filas de `d5_reoptimizado.csv` son aritméticamente consistentes. No se volvió a correr el optimizador.

**Calculadora y reproducibilidad.** Volver a correr `modelo_costos.py` y `verificar_excel.py` en una copia da archivos CSV y JSON idénticos byte a byte y las mismas 132 celdas (diferencia máxima de 3·10⁻¹⁵).
- El libro tiene 302 fórmulas y ningún número de parámetro escrito a mano dentro de ellas: solo constantes como 365, 10⁶ o el piso de 0,5 del rendimiento.
- Las celdas de β y del valor de la espera son amarillas, pero ninguna fórmula las usa (ver sección 10). **Corregido después de la verificación** (ver al final).

**Otras reservas.**
- El rango del bus-hora (18.900–34.300) solo mueve el salario y las horas pagadas. Si también se mueven el factor prestacional, los recargos y las horas al mes, va de ~14.900 a 41.600.
- La flota de los costos fijos usa los vehículos promedio por día, incluidos los domingos (199 buses). Con la mediana de vehículos distintos por día serían ~213: +0,9 mil M COP de fijos y un margen de ~−20 % en vez de −17 %. No afecta los ahorros.
- La retención de 0,86 sobre la tarifa de 2026 supone que los descuentos crecen en proporción. Si siguen iguales en pesos, sería 0,87 (3.220 COP), y el neto de D5 bajaría unos 60 M COP.

**Cambios hechos en este README durante la verificación:**
- punto 4 de la respuesta corta y sección 7: el rango de pasajes perdidos (3.830–5.990) corresponde a β de 0,55 a 0,90, no a β = 0,70 (central: 4.720);
- punto 6 y sección 6: el ACPM no es el parámetro que menos pesa (la penalidad por edad pesa menos);
- sección 2: cita de la jornada (Ley 2101 de 2021) y tipo del ACPM 2026 (F+C, alto supuesto, como en el CSV);
- sección 10: aviso sobre las celdas inertes de β y del valor de la espera;
- esta sección 11.

No se modificó código, datos ni resultados.

**Correcciones aplicadas después de la verificación (6-oct-2026).** Se regeneraron `parametros_costos.csv`, `resultados/*`, las figuras y `calculadora_ahorros.xlsx`, y `verificar_excel.py` pasa.
1. **Jornada.** `parametros.py` cita la Ley 2101 de 2021 y separa las horas trabajadas de 2025 (195 h/mes: 46 h hasta el 15-jul-2025 y 44 h después) de las de 2026 (182 h/mes: 42 h desde el 15-jul-2026).
   - El conductor por bus-hora pasa de 25.289 a **26.400 COP** a precios de 2026 (+4,4 %, como estimó el verificador) y de 20.539 a 20.012 a precios de 2025.
   - Netos con β = 0,70 y pago por hora (M COP/año): S1 de −1.749 a −1.713; S5 de −481 a −409; **D5 de −1.097 a −1.029** (+68 M); D5 30.000 de −2.474 a −2.462; D5 máx. 15 min de +280 a +390; giro corto de +238 a +248.
   - β de equilibrio con pago por hora: D5 de 0,52 a 0,53; S1 de 0,35 a 0,36; S5 de 0,61 a 0,63; D5 máx. 15 min de 0,74 a 0,76.
   - Línea base 2025: costo total de 46.164 a 45.817 M COP y margen de −17,4 % a −16,5 %. Los netos con pago por producido no cambian.
   - `reoptimizar_d5.py` se volvió a correr después con 182 h/mes (punto 4).
2. **β y valor de la espera conectados.**
   - 'Escenarios' calcula los pasajeros perdidos como A × (1 − c^β) con el β de 'Parámetros'. A y c por escenario se ajustan a la contabilidad hora a hora de D5 y son exactos en β = 0,70 (error ≤ 0,06 % en 0,55 y 0,90). 'Sensibilidad' usa los β bajo y alto.
   - El modelo de Python usa la misma curva, de modo que hoja y modelo coinciden para cualquier β. La verificación cambia β a 0,55 en la hoja y compara 84 celdas con el modelo: 249 comparaciones en total, con diferencia máxima de 1,1·10⁻¹⁴; las 337 fórmulas se evalúan sin error.
   - El valor de la hora de espera alimenta una columna de **valor social de la espera** (no es caja).
   - Se añadieron columnas de **β de equilibrio** calculadas con fórmulas (pago por hora y por producido).
   - Efecto en los números: los pasajes perdidos de S1, S5 y D5 con β de 0,55 y 0,90 salen ahora de la curva en vez del cálculo exacto. Eso mueve los extremos de "Pasajes perdidos" de la sección 5 en 3 M COP o menos; el resto del cambio de los rangos viene de la corrección de la jornada.
3. **Planificador.** Nuevo `resultados/costos_para_planificador.json`, con valores por defecto, bajo y alto:
   - `costo_bus_hora` 26.400 (19.732–35.854 COP);
   - `costo_km` 1.991 (1.445–2.716 COP);
   - `tarifa_neta_2026` 3.182 (3.071–3.420 COP).
4. **D5 reoptimizado con 182 h/mes.** `reoptimizar_d5.py` se volvió a correr con 26.400 COP por bus-hora (antes 25.289) y ahora guarda la contabilidad simétrica y las decisiones hora a hora. Cambios (antes → después): con e = 0,5, 453,9 → 450,9 salidas/día, 1.734,6 → 1.722,5 buses-hora/día, espera 4,27 → 4,30 min, sobrecarga 260 → 267 pasajeros/día, neto conservador −2.998 → −2.825 M COP; con e = 0,70, 520,6 → 514,3 salidas/día y +15 % → +14 % de buses-hora; caja del operador, 451,1 → 444,2 salidas/día (de 0 % a −1,5 % de buses-hora). La dirección no cambia: reasignar, no recortar. La fila del D5 original ya se valora con 26.400 (−1.029, igual que en la sección 5).
