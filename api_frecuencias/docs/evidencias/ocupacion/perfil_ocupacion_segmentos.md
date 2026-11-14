# Ocupación histórica por segmento (§10.1)

Generado por `scripts/preparar_ocupacion_segmentos.py` el 2026-11-10T04:54:03-05:00 con las exportaciones de 2023-01-01 a 2023-02-27 (timbradas_segmentos). Método: `app/servicios/ocupacion.py` (el mismo del ciclo).

## Datos

- Viajes con segmentos: 27025; en el perfil (válidos, limpios y con un tramo de al menos 50 % de la ruta): 26350.
- Filas del perfil: 64848 ({'dia_semana': 45548, 'tipo_dia': 19300}).
- Estacionalidad: nula en todas las filas (hallazgo H1: `estacionalidades_anio` es de otro proceso). El código agrupa por ella, así que el perfil se separa por estacionalidad cuando Extreme la entregue.

## Validación del método frente a la ocupación máxima del dispositivo (mismos viajes)

| Variante | Viajes | Correlación | Razón mediana | Diferencia p5 / p50 / p95 |
|---|---|---|---|---|
| Acotada en 0 en cada segmento (la que usa la API) | 21511 | 0,96 | 0,95 | -10,0 / -1,0 / 3,0 |
| Literal max(0, Σ subidas − bajadas) | 21511 | 0,93 | 0,93 | -15,0 / -2,0 / 2,0 |

Con el orden de `nro_segmento`, la suma sin acotar baja de −3 en el 21,9 % de los viajes (en el dispositivo, ordenado por hora del evento, en el 18,0 %). Σ subidas de los segmentos = Σ subidas del dispositivo en los mismos viajes (2241832 = 2241832): el trigger asigna cada evento al segmento más cercano y en un ciclo de ida y regreso por la misma vía eso desordena algunos eventos. Acotar en cada segmento evita que esa bajada de más se arrastre y por eso se acerca más al dispositivo.

## Comparación con el factor de carga 2025 (ruta × tipo de día × hora)

| Comparación | Franjas | Error absoluto medio | Sesgo | Correlación |
|---|---|---|---|---|
| f_seg_igual vs f_dev_igual | 150 | 0,029 | -0,028 | 0,932 |
| f_seg vs f_dev | 150 | 0,039 | -0,036 | 0,886 |
| f_dev vs f_2025_ene_feb | 150 | 0,037 | -0,024 | 0,770 |
| f_dev vs f_2025 | 150 | 0,033 | -0,024 | 0,849 |
| f_seg vs f_2025 | 150 | 0,062 | -0,060 | 0,797 |
| f_2025_ene_feb vs f_2025 | 150 | 0,019 | 0,000 | 0,908 |

f_seg: factor con la carga de los segmentos (ene-feb 2023); f_dev: el mismo factor con la ocupación máxima del dispositivo (ene-feb 2023, viajes con contadores consistentes, como 2025); «_igual»: los mismos viajes en los dos; f_2025: el factor que usa hoy el optimizador.

## Factor 2025 por día de la semana

- Celdas ruta × día de operación × hora con al menos 10 días: 355 (por tipo de día: 151).
- Entre los días laborales de una misma ruta y hora el factor cambia en promedio 0,034 (máximo 0,095).

## Segmento crítico en las horas pico laborales

| Ruta | Día | Hora | Segmento | Sentido | Carga media | Ocupación media | Ocupación P90 | Viajes |
|---|---|---|---|---|---|---|---|---|
| CL 72 | lunes | 6 | 34 | ida | 36,7 | 73 % | 97 % | 45 |
| CL 72 | lunes | 7 | 33 | ida | 29,1 | 58 % | 98 % | 43 |
| CL 72 | lunes | 17 | 91 | regreso | 25,0 | 50 % | 82 % | 34 |
| CL 72 | lunes | 18 | 91 | regreso | 23,8 | 48 % | 78 % | 31 |
| CL 72 | martes | 6 | 34 | ida | 34,8 | 70 % | 94 % | 50 |
| CL 72 | martes | 7 | 35 | ida | 29,5 | 59 % | 81 % | 36 |
| CL 72 | martes | 17 | 91 | regreso | 21,9 | 44 % | 71 % | 26 |
| CL 72 | martes | 18 | 91 | regreso | 27,9 | 56 % | 95 % | 27 |
| CL 72 | miércoles | 6 | 34 | ida | 38,1 | 76 % | 102 % | 52 |
| CL 72 | miércoles | 7 | 33 | ida | 28,7 | 57 % | 92 % | 44 |
| CL 72 | miércoles | 17 | 91 | regreso | 24,4 | 49 % | 80 % | 30 |
| CL 72 | miércoles | 18 | 91 | regreso | 24,0 | 48 % | 78 % | 25 |
| CL 72 | jueves | 6 | 34 | ida | 40,2 | 80 % | 106 % | 53 |
| CL 72 | jueves | 7 | 34 | ida | 31,0 | 62 % | 92 % | 53 |
| CL 72 | jueves | 17 | 91 | regreso | 21,4 | 43 % | 70 % | 39 |
| CL 72 | jueves | 18 | 91 | regreso | 21,1 | 42 % | 72 % | 41 |
| CL 72 | viernes | 6 | 34 | ida | 39,1 | 78 % | 100 % | 62 |
| CL 72 | viernes | 7 | 33 | ida | 26,2 | 52 % | 80 % | 51 |
| CL 72 | viernes | 17 | 91 | regreso | 22,6 | 45 % | 71 % | 37 |
| CL 72 | viernes | 18 | 107 | regreso | 15,1 | 30 % | 60 % | 34 |
| CRA 54 | lunes | 6 | 28 | ida | 46,6 | 93 % | 118 % | 193 |
| CRA 54 | lunes | 7 | 28 | ida | 36,1 | 72 % | 106 % | 178 |
| CRA 54 | lunes | 17 | 53 | ida | 25,0 | 50 % | 80 % | 131 |
| CRA 54 | lunes | 18 | 91 | regreso | 23,4 | 47 % | 80 % | 117 |
| CRA 54 | martes | 6 | 28 | ida | 45,7 | 91 % | 116 % | 171 |
| CRA 54 | martes | 7 | 27 | ida | 34,5 | 69 % | 106 % | 162 |
| CRA 54 | martes | 17 | 94 | regreso | 22,4 | 45 % | 80 % | 112 |
| CRA 54 | martes | 18 | 91 | regreso | 24,3 | 48 % | 87 % | 96 |
| CRA 54 | miércoles | 6 | 28 | ida | 44,8 | 90 % | 114 % | 198 |
| CRA 54 | miércoles | 7 | 27 | ida | 35,8 | 72 % | 112 % | 170 |
| CRA 54 | miércoles | 17 | 53 | ida | 22,6 | 45 % | 76 % | 134 |
| CRA 54 | miércoles | 18 | 91 | regreso | 24,1 | 48 % | 82 % | 120 |
| CRA 54 | jueves | 6 | 28 | ida | 44,7 | 89 % | 116 % | 233 |
| CRA 54 | jueves | 7 | 27 | ida | 33,0 | 66 % | 96 % | 200 |
| CRA 54 | jueves | 17 | 53 | ida | 24,1 | 48 % | 83 % | 148 |
| CRA 54 | jueves | 18 | 91 | regreso | 22,1 | 44 % | 78 % | 135 |
| CRA 54 | viernes | 6 | 28 | ida | 44,9 | 90 % | 116 % | 234 |
| CRA 54 | viernes | 7 | 27 | ida | 34,4 | 69 % | 101 % | 195 |
| CRA 54 | viernes | 17 | 94 | regreso | 23,5 | 47 % | 78 % | 149 |
| CRA 54 | viernes | 18 | 94 | regreso | 21,1 | 42 % | 78 % | 135 |
| SILENCIO | lunes | 6 | 39 | ida | 37,0 | 74 % | 103 % | 86 |
| SILENCIO | lunes | 7 | 39 | ida | 26,0 | 52 % | 79 % | 72 |
| SILENCIO | lunes | 17 | 93 | regreso | 21,9 | 44 % | 69 % | 54 |
| SILENCIO | lunes | 18 | 93 | regreso | 19,6 | 39 % | 70 % | 57 |
| SILENCIO | martes | 6 | 40 | ida | 38,1 | 76 % | 103 % | 76 |
| SILENCIO | martes | 7 | 39 | ida | 24,5 | 49 % | 81 % | 58 |
| SILENCIO | martes | 17 | 93 | regreso | 17,5 | 35 % | 80 % | 53 |
| SILENCIO | martes | 18 | 93 | regreso | 20,7 | 41 % | 70 % | 48 |
| SILENCIO | miércoles | 6 | 40 | ida | 36,8 | 74 % | 106 % | 91 |
| SILENCIO | miércoles | 7 | 39 | ida | 27,4 | 55 % | 94 % | 66 |
| SILENCIO | miércoles | 17 | 93 | regreso | 17,6 | 35 % | 60 % | 50 |
| SILENCIO | miércoles | 18 | 93 | regreso | 19,6 | 39 % | 71 % | 54 |
| SILENCIO | jueves | 6 | 40 | ida | 36,5 | 73 % | 104 % | 101 |
| SILENCIO | jueves | 7 | 39 | ida | 25,5 | 51 % | 85 % | 76 |
| SILENCIO | jueves | 17 | 93 | regreso | 17,9 | 36 % | 62 % | 66 |
| SILENCIO | jueves | 18 | 93 | regreso | 22,4 | 45 % | 81 % | 54 |
| SILENCIO | viernes | 6 | 40 | ida | 38,0 | 76 % | 101 % | 104 |
| SILENCIO | viernes | 7 | 39 | ida | 24,8 | 50 % | 81 % | 77 |
| SILENCIO | viernes | 17 | 93 | regreso | 16,9 | 34 % | 61 % | 77 |
| SILENCIO | viernes | 18 | 93 | regreso | 14,9 | 30 % | 50 % | 55 |

## Limitaciones

- timbradas_segmentos solo trae 2023-01-01 a 2023-02-27: el perfil es de enero (vacaciones escolares) y febrero (inicio de clases y Carnaval); no ve Semana Santa, mitad de año ni diciembre, ni los cambios de ruta posteriores.
- La hora es la de salida del viaje (la franja que decide el despacho), no la hora en que el bus pasa por el segmento: los segmentos del regreso se recorren una hora o más después de la salida.
- El trigger de Extreme asigna cada evento al segmento más cercano: en los tramos donde la ida y el regreso van por la misma vía algunos eventos caen en el segmento del otro sentido (ver la validación).
- El sentido es una aproximación geométrica (mitad de la longitud del ciclo), no un campo de Extreme.
- La ocupación es carga / 50 puestos (el catálogo del reto); la API la recalcula con la capacidad gobernada.
- La estacionalidad oficial es nula para Sobusa (H1); el perfil se separará por ella cuando Extreme la entregue.
