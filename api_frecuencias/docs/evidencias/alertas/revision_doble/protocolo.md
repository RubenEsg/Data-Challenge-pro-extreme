# Protocolo de revisión doble de alertas (§18 «Etiquetas incorrectas»)

> **Revisión automatizada.** Los revisores de esta muestra son **agentes de modelo de lenguaje** que siguen este
> protocolo escrito; la muestra y las tarjetas también las preparó un agente. No es una revisión humana. La
> **validación por el área de operaciones de Sobusa está pendiente**: hasta entonces las etiquetas son una estimación
> reproducible, no la verdad operativa.

La especificación v1.5 (§18) pide mitigar el riesgo «Etiquetas incorrectas → métricas engañosas» con una «muestra
manual revisada dos veces y conciliación». El backtest de 2025 no tiene incidentes etiquetados y aproxima la precisión
con reglas automáticas (persistencia en la hora siguiente, día especial o demanda real de la hora). Este protocolo
define qué es una alerta **verdadera**, **falsa** o **indeterminada** para cada código de §5.2, para que dos
revisores independientes etiqueten la misma muestra y se pueda medir su acuerdo.

## 1. La muestra

- **Población**: las alertas que producen las reglas del commit `3d6781d` (copia congelada del código y de `datos/`)
  en el periodo fuera de muestra 2025-09-15 a 2025-12-31 (324 días-ruta, 3 rutas), con el modelo activo
  `hgb_fv2_20250831_s42`, la banda calibrada v2 y los umbrales `umbrales-v2` de `threshold_config`.
  - Observadas (`scripts/backtest_alertas.py`): ALT-005 46, ALT-006 41, ALT-007 66, ALT-008 20, ALT-009 0. Coinciden
    con `../backtest_alertas.md`.
  - De pronóstico (`scripts/backtest_alertas.py --pronostico`, ciclo de las 6:00, variante actual «franja»): ALT-001
    295, ALT-002 282, ALT-003 108, ALT-004 0. **Diferencia con la evidencia publicada**: `../backtest_alertas_pronostico.md`
    dice 288, 278 y 103 porque se generó a las 05:03, antes de los cambios que entraron en el commit `3d6781d`
    (05:52). La muestra usa la población que da el código congelado; regenerar esa evidencia con el commit queda
    pendiente.
  - ALT-010 no tiene alertas: el backtest no lo evalúa (los contextos no traen `wape_movil`).
- **Diseño**: estratos = código. Asignación proporcional a la frecuencia con un mínimo de 8 por código (los códigos
  cuya cuota proporcional queda bajo 8 reciben 8, y el resto se reparte en proporción por restos mayores). El sorteo
  usa `numpy.random.default_rng(42)`, sin reemplazo, sobre la población ordenada por (fecha, ruta, inicio de la
  ventana). Una permutación con el mismo generador asigna los identificadores M001 a M096, así que el orden de
  revisión mezcla los códigos.

| Código | Población | Muestra | Fracción |
|---|---|---|---|
| ALT-001 | 295 | 28 | 9,5 % |
| ALT-002 | 282 | 26 | 9,2 % |
| ALT-003 | 108 | 10 | 9,3 % |
| ALT-005 | 46 | 8 | 17,4 % |
| ALT-006 | 41 | 8 | 19,5 % |
| ALT-007 | 66 | 8 | 12,1 % |
| ALT-008 | 20 | 8 | 40,0 % |
| **Total** | **858** | **96** | 11,2 % |

Por el mínimo de 8, las observadas pesan más en la muestra que en la población. Cualquier precisión global tiene que
**reponderar** cada estrato por población / muestra (la tabla de arriba y `muestra.json`).

Archivos: `muestra.json` (id, código, ruta, fecha, hora, estrato y clave del episodio) y una tarjeta
`muestra/<id>.md` por alerta, **sin etiqueta**. Cada tarjeta trae la regla, las cifras con unidades, la serie horaria
del día, la misma hora en los 4 días anteriores del mismo tipo, las 2 horas siguientes, el calendario y las notas de
calidad del dato.

## 2. Cómo se revisa

1. **Independencia.** Cada revisor etiqueta las 96 tarjetas sin ver las etiquetas del otro ni la confirmación
   aproximada del backtest. Solo usa la tarjeta y este protocolo, sin consultar la base del reto ni otros archivos.
2. **Orden de decisión** (el mismo para todos los códigos; el primer paso que decide, decide):
   1. **Calidad del dato** (sección 8 de la tarjeta). ¿La condición sale de una hora sin registro, de una hora con
      pasajeros y 0 salidas (CONS-002), de un hueco de 0 pasajeros y 0 salidas entre horas normales o de una hora
      de borde del servicio (4 h o 20 h)? Para los códigos de demanda, despacho y pronóstico (ALT-001 a ALT-007) eso
      es **falsa**, salvo las excepciones de cada código. Para ALT-008 y ALT-009 el problema del dato es justamente
      lo que buscan.
   2. **Calendario** (sección 7). ¿El día es festivo, Navidad, vacaciones, 1 de enero, Semana Santa o carnaval, y la
      desviación va en el sentido que ese calendario explica? Mira también la sección 5, que dice cómo fueron los
      días del mismo tipo. Lo que el calendario explica y la operación ya conoce es **falsa** donde el código lo dice.
   3. **Ruido transitorio.** ¿La desviación es marginal (menos del 10 % más allá del umbral), cabe en la variación de
      la misma hora en los 4 días anteriores del mismo tipo y desaparece en la hora siguiente? Entonces es **falsa**.
   4. Si no aplica nada de lo anterior y la situación de §5.2 **ocurrió de verdad** (cifras de las secciones 3 a 6),
      la alerta es **verdadera**: un operador debía hacer la acción sugerida de §5.2.
   5. **Indeterminada** solo cuando la tarjeta no permite decidir: falta el dato que decide, la evidencia se
      contradice o la respuesta depende de información que la tarjeta no tiene (por ejemplo, si hubo un evento
      programado). No se usa por comodidad.
3. **Formato de la respuesta**, una línea por tarjeta: `id`, `etiqueta` (verdadera | falsa | indeterminada),
   `criterio` (el número del paso 2.1 a 2.5 que decidió y la regla del código) y una `justificación` de 1 a 3 frases
   con las cifras de la tarjeta. Opcional: `confianza` (alta, media o baja).
4. **Conciliación.** Cuando los dos revisores coinciden, la etiqueta queda. Cuando difieren, un tercer paso (agente
   conciliador) relee la tarjeta con las dos justificaciones, aplica el orden de decisión y deja la etiqueta final con
   el motivo. Si no se resuelve con la tarjeta, queda «indeterminada». Se informan el acuerdo bruto y la kappa de
   Cohen antes de conciliar, la precisión por código (verdaderas / (verdaderas + falsas), con las indeterminadas
   aparte) y la precisión global reponderada.

## 3. Definiciones por código

Las convenciones son las del motor: capacidad = buses/h programados × 50 puestos (§10.2) frente a las subidas de la
hora; esperado, P10 y P90 = pronóstico horario del modelo con la banda calibrada v2. Con recambio de pasajeros, un bus
puede llevar más de 50 subidas por viaje sin ir sobrecupado. El revisor aplica la convención y, si las subidas por
salida real quedan en 50 o menos aunque la demanda supere la capacidad programada, lo anota en la justificación. Los
ejemplos son ilustrativos (cifras inventadas), no casos de la muestra.

### ALT-001 Alta demanda prevista (pronóstico; §5.2: «La demanda proyectada supera la capacidad disponible»)

- **Verdadera**: la demanda **real** de la hora de la alerta superó la capacidad programada por hora, con el dato de
  esa hora completo y un nivel coherente con la misma hora de los días anteriores del mismo tipo. Ejemplo: P90 650
  frente a 318 puestos/h; la hora tuvo 420 subidas reales con 6 salidas; los 4 días previos, entre 380 y 460.
- **Falsa**: la demanda real quedó en la capacidad o por debajo (el riesgo no se materializó), o el valor real es un
  artefacto (hora sin registro, pasajeros con 0 salidas). Ejemplo: P90 650 frente a 600 puestos/h y un real de 410.
  Si el día era festivo o de vacaciones y la demanda cayó por eso, también es falsa.
- **Indeterminada**: falta el real de la hora, o el real queda a ±2 % de la capacidad y la hora tiene una nota de
  calidad que pone en duda el conteo.

### ALT-002 Sobreocupación (pronóstico; §5.2: «Ocupación esperada u observada ≥ umbral crítico»)

- **Verdadera**: la ocupación **real** (subidas reales ÷ capacidad programada de la hora) llegó al 90 % o más, con el
  dato completo. Ejemplo: ocupación esperada 120 % y real 132 %.
- **Falsa**: la ocupación real quedó por debajo del 90 %, o sale de un artefacto o de un efecto de calendario que bajó
  la demanda. Ejemplo: esperada 95 % y real 71 % en un 24 de diciembre.
- **Indeterminada**: falta el real o el dato de la hora no es confiable.

### ALT-003 Frecuencia insuficiente (pronóstico; §5.2: «La frecuencia actual no cubre la demanda con el nivel de servicio»)

- **Verdadera**: con la demanda **real** de la hora, la oferta programada quedó por encima de la ocupación objetivo
  máxima: subidas reales > 85 % × capacidad programada, así que hacían falta más buses/h, como recomendó la
  optimización. Ejemplo: 6,4 buses/h programados (318 puestos/h), 7 recomendados y 380 subidas reales (119 %).
- **Falsa**: las subidas reales fueron el 85 % de la capacidad programada o menos (la frecuencia sí cubrió la demanda
  con el nivel de servicio), o el real es un artefacto o un efecto de calendario.
- **Indeterminada**: falta el real, o la ocupación real queda entre el 80 % y el 90 % y la diferencia entre
  programados y recomendados es menor de 1 bus/h (no se distingue del redondeo de la recomendación).

### ALT-004 Frecuencia excesiva (pronóstico; sin casos en la muestra: 0 alertas)

- **Verdadera**: la ocupación real con la oferta programada quedó por debajo del 30 % y la programación superaba la
  recomendada (se podía ampliar el intervalo). **Falsa**: la ocupación real llegó al 30 % o más, o la baja demanda es
  un artefacto (hueco de datos). **Indeterminada**: falta el real.

### ALT-005 Caída anormal de demanda (observada; §5.2: «La demanda real se desvía negativamente del patrón»; acción: «Validar evento, ruta o captura»)

- **Verdadera**: en la ventana la demanda real quedó claramente bajo lo habitual. Eso quiere decir bajo el esperado
  del modelo **y** bajo el mínimo de la misma hora en los 4 días anteriores del mismo tipo (o por debajo del 70 % de
  su mediana), en un día sin calendario que lo explique y con salidas registradas, es decir, con el servicio
  operando. Una **falla de captura** (buses con salidas normales y subidas casi nulas) es verdadera, porque la acción
  de §5.2 incluye «validar captura». Ejemplo: 11-13 h con 250 subidas frente a 430 esperadas y 380 a 450 en los días
  previos, con 4 salidas por hora.
- **Falsa**: (a) el calendario lo explica (festivo, Navidad, vacaciones, puente) y la sección 5 muestra niveles
  parecidos en días del mismo tipo; (b) hueco de registro: 0 pasajeros y 0 salidas entre horas normales, sin
  consecuencia en las horas siguientes (eso le toca a ALT-009); (c) la ventana es una hora de borde (4 h o 20 h);
  (d) ruido: el real cabe en el rango de los 4 días anteriores y vuelve a la banda en la hora siguiente.
- **Indeterminada**: la caída coincide con una novedad vial o con un posible evento que la tarjeta no confirma, y los
  días previos no permiten decidir si es habitual.

### ALT-006 Despacho ausente o tardío (observada; §5.2: «No hay despacho dentro de la tolerancia»; acción: «Verificar disponibilidad y operación»)

- **Verdadera**: en horas de servicio completo (5 a 19 h) salieron muchas menos salidas que las programadas (déficit
  > 50 %) mientras seguía habiendo demanda, o no hubo ninguna salida y hay señales de interrupción real: la demanda
  baja de forma gradual, en la hora siguiente se acumulan subidas por salida, o hay una novedad vial en la ventana.
  Ejemplo: 14-16 h con 3 de 9 salidas programadas, 210 subidas y 70 subidas por salida frente a 35 habituales.
- **Falsa**: (a) pasajeros con 0 salidas: las salidas no quedaron registradas (CONS-002), no faltó el bus; (b) hueco
  de registro: 0 pasajeros y 0 salidas en una hora rodeada de horas normales y sin acumulación después; (c) servicio
  reducido **planeado** por calendario (Navidad, 1 de enero, festivo, vacaciones), con salidas parecidas a las de la
  misma hora en días previos del mismo tipo o calendario; (d) la ventana toca el borde del servicio o el final del
  día (19-20 h con el servicio terminando antes de lo programado como en los días previos).
- **Indeterminada**: la evidencia no separa una interrupción real de un hueco de registro, por ejemplo una hora en
  cero entre horas algo bajas y sin datos de la hora siguiente.

### ALT-007 Desviación del pronóstico (observada; §5.2: «La demanda real supera el intervalo estimado por el modelo»; acción: «Revisar la frecuencia y recalibrar el escenario»)

- **Verdadera**: la demanda real quedó fuera de la banda P10-P90, en el mismo sentido, durante 2 horas o más, con
  datos completos. Es decir, el pronóstico de ese tramo falló de verdad y había que revisar la frecuencia. Valen los
  dos sentidos (sobre el P90, riesgo de falta de oferta; bajo el P10, oferta de sobra). Un efecto de calendario que
  el modelo **no anticipó** cuenta como verdadera, porque el escenario debía recalibrarse. Ejemplo: 16-18 h con 1.450
  subidas frente a un P90 de 1.200 y un pronóstico de 1.000, y días previos entre 1.050 y 1.150.
- **Falsa**: (a) la desviación sale de un artefacto: hora con 0 pasajeros por un hueco, pasajeros sin salidas, o una
  hora de borde (por ejemplo, la 4 h con 0 subidas y 1 salida, que arrastra el episodio); (b) ruido: el exceso sobre
  la banda es marginal (< 10 %) y la hora siguiente vuelve a la banda.
- **Indeterminada**: la desviación existe, pero la tarjeta no permite saber si el real es fiable (notas de calidad
  contradictorias).

### ALT-008 Consolidado anómalo (observada, diaria; §5.2: «Subidas, bajadas o número de viajes atípicos»; acción: «Validar fuente, trigger y período afectado»)

Este código busca problemas de la fuente o de la consolidación. Ahí un problema del dato **es** la situación.

- **Verdadera**: el total del día es atípico frente al mismo tipo de día y (a) la serie horaria muestra la causa en
  el dato: horas en cero o sin registro, salidas sin subidas o un corte abrupto, o (b) el día es atípico sin
  calendario que lo explique, con un perfil horario completo, y el operador debía validar el período. Ejemplo: 14.000
  subidas frente a una mediana de 20.000, con 3 horas de la tarde en 0 pasajeros y 0 salidas.
- **Falsa**: el calendario explica el total (festivo, Navidad, 24 o 31 de diciembre, vacaciones, 1 de enero, puente)
  con un perfil horario completo y de forma normal para ese día, o la referencia no es comparable (por ejemplo, días
  de vacaciones comparados con semanas de clases y el día se parece a los días previos de su mismo calendario). No
  hay nada que validar en la fuente.
- **Indeterminada**: el total es atípico con un perfil completo, pero los días previos del mismo calendario también
  son bajos y no está claro si la referencia o el día son el problema.

### ALT-009 Datos incompletos (calidad del dato; sin casos en la muestra: 0 alertas)

- **Verdadera**: faltó información obligatoria (horas de servicio sin registro, campos faltantes) o llegó con más de
  2 períodos de ingesta de atraso, y hacía falta reprocesar el lote. **Falsa**: las horas «faltantes» son horas sin
  servicio programado o el atraso viene del reloj de la ejecución y no de la fuente. **Indeterminada**: no se puede
  saber si la hora tenía servicio programado.

### ALT-010 Modelo degradado (modelo; sin casos: el backtest no lo evalúa)

- **Verdadera**: el WAPE móvil supera la tolerancia (20 %) con suficientes observaciones y sin que la ventana esté
  dominada por huecos de datos o por días especiales. **Falsa**: el WAPE sube por un artefacto (horas en cero de un
  hueco) o por pocos días festivos dentro de la ventana. **Indeterminada**: la ventana tiene muy pocas observaciones.

## 4. Limitaciones

- Los revisores son agentes de modelo de lenguaje: el acuerdo entre ellos mide la **consistencia del protocolo**, no
  la verdad operativa. La validación por el área de operaciones de Sobusa está pendiente, y lo ideal es que la haga
  sobre esta misma muestra para estimar el error de las etiquetas automatizadas.
- Las tarjetas solo tienen datos horarios empaquetados: no hay horas exactas de despacho, ni GPS, ni registro de
  eventos. Por eso algunas alertas de despacho quedarán indeterminadas.
- La capacidad es nominal (50 puestos por bus) frente a las subidas de la hora. Para ALT-001 y ALT-002 eso sobrestima
  la ocupación en hora pico.
