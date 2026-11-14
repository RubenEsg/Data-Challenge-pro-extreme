# Revisión doble de alertas (§18 de la especificación v1.5)

> **Revisión automatizada, no humana.** La muestra y las tarjetas las preparó un agente, y los revisores A y B y el
> conciliador son **agentes de modelo de lenguaje** que siguen el protocolo escrito. **La validación por el área de
> operaciones de Sobusa está pendiente.**

Esta carpeta es la evidencia de la mitigación «Muestra manual revisada dos veces y conciliación» del riesgo
«Etiquetas incorrectas → métricas engañosas» (§18), aplicada a las alertas ALT-001 a ALT-010 (§5.2) del backtest de
2025 (`../backtest_alertas.md` y `../backtest_alertas_pronostico.md`).

## Archivos

| Archivo | Qué es |
|---|---|
| `protocolo.md` | Población, diseño de la muestra (estratos por código, mínimo de 8, semilla 42), orden de decisión y definición de verdadera, falsa e indeterminada por código. |
| `muestra.json` | Las 96 alertas sorteadas: id, código, familia, ruta, fecha, ventana, clave del episodio, población y asignación por estrato. |
| `muestra/M001.md` … `M096.md` | Una tarjeta por alerta, **sin etiqueta**, con la regla, las cifras con unidades, la serie horaria, los 4 días previos del mismo tipo, las horas siguientes, el calendario y la calidad del dato. |
| `etiquetas_A.json`, `etiquetas_B.json` | Las etiquetas independientes de los revisores A y B (etiqueta, confianza y justificación; B también trae el criterio). |
| `conciliar.py` | Script de conciliación. Calcula el acuerdo y la kappa, aplica las decisiones del conciliador a los desacuerdos (`DECISIONES`, con su motivo), la precisión por código con IC de Wilson, la tasa de falsas, la precisión reponderada y la comparación con el backtest. |
| `conciliacion.json` | Salida de `conciliar.py`: acuerdo antes de conciliar (global, por familia y por código, con la matriz A × B), desacuerdos con su motivo, etiqueta final de las 96 alertas, precisión por código y global, y cifras del backtest usadas. |
| `resumen.md` | Resumen para el jurado: método, muestra, kappa, tabla de precisión, causas de las falsas alertas con ejemplos, recomendaciones de umbrales y limitaciones. |
| `kit_humano/` | El kit para que dos revisores del área operativa de Sobusa repitan la revisión a mano y a ciegas sobre las mismas 96 tarjetas: `revisar.html` (un solo archivo, sin red), `conciliar_humanos.py` (acuerdo, kappa, desacuerdos y, con las decisiones de la reunión, la precisión), `generar_kit.py` y `plantilla/` (de donde sale la página) e `INSTRUCCIONES.md`. Lo prueba `api_frecuencias/tests/unit/test_kit_revision_humana.py`. Todavía no hay etiquetas humanas. |

## Cifras clave

- Acuerdo bruto 97,9 % (94 de 96) y kappa de Cohen 0,943 (IC 95 % 0,854-1,000), sin ningún choque verdadera/falsa.
  En pronóstico, 100 % y kappa 1,000; en observadas, 93,8 % y kappa 0,888.
- Hubo 2 desacuerdos: M048 quedó indeterminada y M092 verdadera.
- Precisión reponderada global 0,839 (0,757-0,882): pronóstico 0,922 y observadas 0,509. ALT-008 tiene 0,43 frente
  al 0,70 del proxy del backtest, que cuenta los días especiales como confirmación.

## Cómo reproducir

1. Requisitos: Python 3.11 o superior con `numpy` (sirve el entorno de la API, `api_frecuencias/.venv`). No hace
   falta red ni base de datos.
2. Desde cualquier carpeta:

   ```
   <ruta>/api_frecuencias/.venv/Scripts/python.exe -I <ruta>/docs/evidencias/alertas/revision_doble/conciliar.py
   ```

   El script lee `muestra.json`, `etiquetas_A.json`, `etiquetas_B.json` y las tarjetas (solo para las marcas de
   calendario) y reescribe `conciliacion.json`. Si aparece un desacuerdo sin decisión en `DECISIONES`, se detiene.
   Los intervalos con remuestreo usan la semilla 42, así que todo es determinista salvo el campo `generado`.
3. La muestra se sacó con la copia congelada del commit `3d6781d` (`protocolo.md` §1). Regenerarla con un código
   distinto cambia la población: las reglas de pronóstico ya cambiaron después de ese commit, y
   `../backtest_alertas_pronostico.md` (06:32) informa otra población.

## Pendiente

- Validación humana por el área de operaciones de Sobusa, sobre estas mismas 96 tarjetas, para estimar el error de
  las etiquetas automatizadas. El kit está listo en `kit_humano/` (`kit_humano/INSTRUCCIONES.md`): dos revisiones
  independientes y a ciegas, una reunión de conciliación con motivo y la comparación con la revisión automatizada.
- Resolver M048 con el plan de operación del 31 de diciembre.
- Probar en el backtest las recomendaciones de umbral de `resumen.md` §6 antes de cambiar `threshold_config`.
