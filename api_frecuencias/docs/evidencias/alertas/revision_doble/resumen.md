# Revisión doble de alertas y conciliación (§18 «Etiquetas incorrectas → métricas engañosas»)

> **Revisión automatizada, no humana.** Los dos revisores (A y B) y el conciliador son **agentes de modelo de
> lenguaje** que siguen el protocolo escrito `protocolo.md`; la muestra y las tarjetas también las preparó un agente.
> El acuerdo entre ellos mide la consistencia del protocolo, no la verdad operativa. **La validación por el área de
> operaciones de Sobusa está pendiente**; hasta entonces estas cifras son una estimación reproducible.

## 1. Método

- **Mitigación de §18**: muestra revisada dos veces de forma independiente y conciliada. Cada revisor etiquetó las 96
  tarjetas (`muestra/M001.md` a `M096.md`) como verdadera, falsa o indeterminada sin ver al otro ni la confirmación
  aproximada del backtest, con el orden de decisión de `protocolo.md` §2: calidad del dato, calendario, ruido
  transitorio, situación de §5.2 ocurrida e indeterminada solo si la tarjeta no permite decidir.
- **Conciliación**: si A y B coinciden, la etiqueta queda. Si difieren, el conciliador relee la tarjeta y las dos
  justificaciones y decide con el mismo orden de decisión.
- **Métricas**: acuerdo bruto y kappa de Cohen (3 categorías) **antes** de conciliar. Después, la precisión por
  código, verdaderas / (verdaderas + falsas), con las indeterminadas aparte, su intervalo de Wilson al 95 %, la tasa
  de falsas (1 − precisión) y la precisión global **reponderada** por población / muestra. Todo sale de
  `conciliar.py` → `conciliacion.json`.

## 2. Muestra

Población: las 858 alertas que producen las reglas del commit `3d6781d` (copia congelada) del 2025-09-15 al
2025-12-31 (324 días-ruta, 3 rutas), con el modelo `hgb_fv2_20250831_s42`, la banda calibrada v2 y `umbrales-v2`. La
muestra es estratificada por código, proporcional, con un mínimo de 8 por código y la semilla 42 (`protocolo.md` §1).
Son 96 alertas: 64 de pronóstico (ALT-001 a ALT-003) y 32 observadas (ALT-005 a ALT-008). ALT-004 y ALT-009 no
tuvieron alertas, y ALT-010 no lo evalúa el backtest.

## 3. Acuerdo entre revisores (antes de conciliar)

| Bloque | Tarjetas | Coinciden | Acuerdo bruto | Kappa de Cohen |
|---|---|---|---|---|
| **Global** | 96 | 94 | **97,9 %** | **0,943** (IC 95 % bootstrap 0,854-1,000) |
| Pronóstico (ALT-001 a ALT-003) | 64 | 64 | 100 % | 1,000 |
| Observadas (ALT-005 a ALT-008) | 32 | 30 | 93,8 % | 0,888 |
| ALT-006 | 8 | 7 | 87,5 % | 0,778 |
| ALT-008 | 8 | 7 | 87,5 % | 0,800 |
| ALT-001, ALT-003, ALT-005, ALT-007 | 28, 10, 8, 8 | todas | 100 % | 1,000 |
| ALT-002 | 26 | 26 | 100 % | no definida (los dos marcaron todo verdadera) |

Matriz A × B: 73 verdadera/verdadera, 20 falsa/falsa, 1 indeterminada/indeterminada (M028), 1 falsa/indeterminada
(M048) y 1 indeterminada/verdadera (M092). **No hubo ningún choque verdadera/falsa.** El acuerdo es muy alto, en parte
porque dos agentes con el mismo protocolo razonan parecido. Con revisores humanos se espera menos acuerdo, y por eso
la validación de Sobusa sigue siendo necesaria.

### Desacuerdos conciliados

| Id | Alerta | A | B | Final | Motivo del conciliador |
|---|---|---|---|---|---|
| M048 | ALT-006, CL 72, 31-dic, 14-20 h | falsa | indeterminada | **indeterminada** | Las cifras cumplen la definición de verdadera: 4 de 31 salidas (déficit 87 %), con 169 y 226 subidas por salida en 15-16 h frente a 82-109 en los días previos. La falsa (c) exige salidas parecidas a las de días del mismo calendario y no lo son: 4 frente a 10 el 24-dic y 28-34 el 26-30 dic. Pero el 24-dic también cerró temprano, así que decidir entre un cierre programado de víspera y una falla depende del plan del 31-dic, que la tarjeta no trae (2.5). |
| M092 | ALT-008, CRA 54, 31-dic, día | indeterminada | verdadera | **verdadera** | Día atípico (z −6,7 y −6,9) con la causa en el dato: corte abrupto de 461 subidas a las 16 h a 0 pasajeros y 0 salidas en 17-20 h. La excepción de calendario de ALT-008 exige un perfil completo, y aquí faltan 4 horas. Para ALT-008 el problema del dato es la situación que se busca (verdadera a). |

## 4. Precisión con las etiquetas conciliadas

| Código | Población | Muestra | V | F | I | Precisión | IC 95 % (Wilson) | Tasa de falsas | Backtest: precisión proxy / lift | Lift implícito* |
|---|---|---|---|---|---|---|---|---|---|---|
| ALT-001 Alta demanda prevista | 295 | 28 | 25 | 3 | 0 | **0,893** | 0,728-0,963 | 0,107 | 0,924 / 1,12 | 1,09 |
| ALT-002 Sobreocupación | 282 | 26 | 26 | 0 | 0 | **1,000** | 0,871-1,000 | 0,000 | 0,968 / 1,14 | 1,18 |
| ALT-003 Frecuencia insuficiente | 108 | 10 | 8 | 2 | 0 | **0,800** | 0,490-0,943 | 0,200 | no evaluado | — |
| ALT-005 Caída anormal | 46 | 8 | 4 | 4 | 0 | **0,500** | 0,215-0,785 | 0,500 | 0,359 / 4,69 | 6,49 |
| ALT-006 Despacho ausente | 41 | 8 | 4 | 3 | 1 | **0,571** | 0,251-0,842 | 0,429 | 0,390 / 8,30 | 12,16 |
| ALT-007 Desviación del pronóstico | 66 | 8 | 4 | 4 | 0 | **0,500** | 0,215-0,785 | 0,500 | 0,270 / 1,34 | 2,48 |
| ALT-008 Consolidado anómalo | 20 | 8 | 3 | 4 | 1 | **0,429** | 0,158-0,750 | 0,571 | 0,700 / 3,78 | 2,32 |

\* Lift implícito = precisión conciliada / tasa base que el backtest informa para su condición proxy. Es indicativo,
porque la verdad del protocolo y el proxy del backtest no son la misma condición.

**Precisión global reponderada** (pesos = población del código / 858; indeterminadas fuera):

| Conjunto | Precisión | Intervalo 95 % (Jeffreys, Monte Carlo) | Tasa de falsas | Si las indeterminadas fueran falsas / verdaderas |
|---|---|---|---|---|
| **Todas** | **0,839** | 0,757-0,882 | **0,161** | 0,834 / 0,843 |
| Pronóstico | 0,922 | 0,830-0,961 | 0,078 | 0,922 / 0,922 |
| Observadas | 0,509 | 0,340-0,673 | 0,491 | 0,486 / 0,530 |

Sin reponderar (74 V, 20 F, 2 I) la precisión sería 0,787: la muestra sobrerrepresenta a las observadas por el
mínimo de 8 por código. Los intervalos reponderados son asimétricos porque ALT-002 tiene 26 de 26 (estimación en el
borde). La «tasa de falsas» es la proporción de alertas emitidas que no debían salir. La tasa de falsos positivos
clásica (falsas / horas sin incidente) no se puede calcular, porque solo se revisaron alertas.

### Comparación con el backtest

- **ALT-001 y ALT-002**: la precisión conciliada (0,89 y 1,00) es compatible con la del backtest (0,924 y 0,968,
  dentro del IC). El lift, en cambio, es bajo (1,1-1,2): a las 6:00 la demanda real supera la capacidad nominal en
  el 82-85 % de las horas. Las alertas aciertan, pero informan poco más que la tasa base.
- **ALT-005, ALT-006 y ALT-007**: la precisión conciliada (0,50, 0,57 y 0,50) es **mayor** que el proxy de
  persistencia del backtest (0,36, 0,39 y 0,27). El proxy cuenta como falsa una alerta cuyo episodio no siguió en la
  hora siguiente, aunque la situación ocurrió. Con la tasa base del backtest, el lift implícito sería de 6,5, 12,2 y
  2,5. Con 8 tarjetas por código los intervalos son anchos (±0,3), así que la conclusión es solo que **el backtest no
  sobrestima** estas precisiones.
- **ALT-008**: la precisión conciliada (0,43) es **menor** que la del backtest (0,70). El proxy del backtest cuenta
  como confirmada una alerta en un día especial o excluido. El protocolo hace lo contrario: un día que el calendario
  explica con un perfil completo es falsa. **Esa métrica del backtest es engañosa en el sentido que advierte §18** y
  no debería citarse como precisión.
- ALT-003 no tiene precisión en el backtest del commit `3d6781d`. La versión publicada de
  `../backtest_alertas_pronostico.md` (06:32) ya corresponde a código posterior (factor de carga; 141, 102, 123 y 10
  alertas) y no es comparable con esta población (295, 282 y 108).

## 5. Causas principales de las falsas alertas (20 falsas)

1. **Calendario que la regla no tiene en cuenta (13 de 20)**. Son el 31-dic, el 24-dic, Navidad, el festivo del
   8-dic, domingos y festivos.
   - ALT-008: las 4 falsas son días de calendario: M091 y M024 (Navidad, 1.776 y 3.395 subidas, perfil completo de
     festivo), M080 (24-dic, perfil completo con servicio reducido desde las 13 h) y M067 (sábado de vacaciones
     comparado con sábados de clases).
   - ALT-006: M004 (Navidad, 18-20 h, igual que el festivo del 8-dic) y M007 (31-dic, 13 salidas frente a 15 el 24-dic).
   - ALT-005: M041 (31-dic SILENCIO, 1.125 subidas frente a 1.025 el 24-dic) y M053 (31-dic CRA 54).
   - Pronóstico: las 5 falsas de ALT-001 y ALT-003 son domingos o festivos a las 6:00. M042 y M079 tuvieron 149 y
     160 subidas frente a 268 puestos/h y M050 654 frente a 659. En ALT-003, M018 (festivo del 13-oct) tuvo 177
     subidas, el 66 % de la capacidad y bajo el 85 %, y M085 tuvo 93 (35 %). En días comunes, las de pronóstico no
     tuvieron ninguna falsa (0 de 51).
2. **Ruido marginal en el borde de la banda (4 de 20, todas las falsas de ALT-007)**. El real quedó solo un 1,2-6,3 %
   más allá del P10/P90 y la hora siguiente volvió a la banda (M062 +1,2 %, M035 −4,0 %, M081 −4,2 %, M038 +6,3 %).
   Las 4 verdaderas tuvieron márgenes de 8,2-13,4 % o siguieron fuera de la banda en la hora siguiente.
3. **Horas de borde y huecos de registro (2 de 20, ALT-005)**. M089 cumple la persistencia de 2 h solo con la 20 h
   (última hora, 90 subidas con 1 salida). M075 suma un hueco de 0 pasajeros y 0 salidas a la 19 h y la 20 h. M053,
   contada en la causa 1, también incluye 17-20 h en cero.
4. **Déficit apenas sobre la tolerancia en vacaciones (1 de 20)**: M013 (ALT-006, 29-dic, déficit 57,4 % frente a
   la tolerancia del 50 %, sin acumulación de subidas por salida).

## 6. Recomendaciones de umbrales (proponer y validar con backtest y con Sobusa antes de cambiar `threshold_config`)

1. **ALT-008**: compararlo con días del **mismo calendario** (festivos con festivos, 24 y 31-dic con su víspera,
   vacaciones con vacaciones). Si el perfil horario está completo en un día especial, bajarlo a informativa. Las 3
   verdaderas (M022, M074 y M092) tienen cortes o horas en cero, y esa señal hay que conservarla. Además, dejar de
   usar «día especial» como confirmación en el backtest.
2. **ALT-005**: excluir de la persistencia la **20 h** (última hora de salidas), igual que ya hace ALT-006, y no
   contar las horas en 0 pasajeros y 0 salidas, que le tocan a ALT-008 y ALT-009. Usar la referencia de calendario
   para el 24 y el 31-dic y los festivos.
3. **ALT-007**: exigir un **margen mínimo fuera de la banda** (probar 5-10 % más allá del P10/P90) o que la hora
   siguiente siga fuera. En la muestra, un margen de alrededor del 7 % separa las 4 falsas de las 4 verdaderas, pero
   con n = 8 eso es una hipótesis para el análisis de sensibilidad, no un umbral. Subir la persistencia a 3 h no
   ayuda (el backtest da 0,238).
4. **ALT-006**: en días de calendario especial, comparar las salidas con las del mismo calendario y no con la
   programación laboral, y considerar una tolerancia mayor (alrededor del 60 %) o exigir acumulación de subidas por
   salida en 18-20 h.
5. **ALT-001 a ALT-003**: revisar el pronóstico de domingos y festivos a las 6:00, porque las 5 falsas están ahí.
   Por el lift de 1,1-1,2, conviene priorizar las de ALT-001 y ALT-002 por el exceso sobre la capacidad y no
   emitirlas todas con la misma severidad.
6. **31 de diciembre**: pedir a Sobusa el plan de operación de las vísperas para resolver M048 (indeterminada) y
   tratar el cierre anticipado como servicio programado si se confirma.

## 7. Limitaciones y lo pendiente

- Los revisores y el conciliador son agentes de modelo de lenguaje y comparten sesgos: un kappa de 0,94 entre ellos
  no garantiza que las etiquetas sean correctas. **Falta la validación del área de operaciones de Sobusa**, idealmente
  sobre estas mismas 96 tarjetas, para estimar el error de las etiquetas automatizadas.
- Los estratos observados tienen n = 8: sus intervalos son anchos y las recomendaciones de umbral son hipótesis.
- Las tarjetas solo traen datos horarios (sin GPS, sin horas exactas de despacho ni registro de eventos), y la
  capacidad es nominal (50 puestos por bus).
- La población es la del código congelado `3d6781d`. Si las reglas cambian, la muestra hay que volver a sacarla.
