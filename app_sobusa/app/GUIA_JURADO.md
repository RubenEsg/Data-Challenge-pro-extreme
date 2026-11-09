# Sobusa Despacho · Guía para el jurado

Abrahan Basto Martínez, Rubén Esguerra Fernández y Paula Gómez · Universidad del Norte, Data Challenge Pro Extreme 2026 · Rutas SILENCIO, CRA 54 y CL 72 de Sobusa, 2023–2025.

## Cómo abrir la app

Doble clic en `app.html` (raíz del proyecto), en Edge o Chrome, sin internet ni servidor; también se ve en un teléfono. Solo el mapa base gris del tablero y de la consola pide internet; sin él, rutas y buses se siguen viendo.

## Las nueve pantallas

1. **Inicio · ¿Qué proponemos?** Cambiar buses de hora, no quitarlos; la cifra protagonista pasa de 20,04 % a 13,94 % con el interruptor.
2. **Demanda · ¿Cuántos pasajeros habrá?** El error del pronóstico por ruta, tipo de día, franja y antelación.
3. **Modelo · ¿Qué modelo es y por qué?** La ficha de los dos modelos y la comparación de 51 candidatos.
4. **Horario · ¿Cuántos buses y cada cuánto?** El planificador: salidas por ruta, tipo de día y hora.
5. **Despacho · ¿Qué hago ahora?** La consola: cualquier día de 2025 como si fuera en vivo.
6. **Ciudad · ¿Cómo se ve en la calle?** La vista 3D del mismo día, real y con nuestro plan, persona a persona.
7. **Resultado · ¿Qué gana Sobusa?** Salidas, buses-hora, espera, pasajeros de pie y saldo anual, con el simulador por fecha.
8. **Piloto · ¿Cómo lo comprobamos?** Ocho semanas en la calle para medir β.
9. **Método y datos · ¿De dónde sale todo?** Datos, protocolo, experimentos con su fecha de verificación y el tablero del EDA.

## El interruptor Hoy / Con el modelo / Oráculo

**Hoy**: lo que Sobusa hace (la regla manual, promedio de las ocho semanas anteriores; la oferta real de 2025). **Con el modelo**: lo que proponemos. **Oráculo**: la decisión con la demanda que de verdad llegó, el techo contra el que se mide el plan. Está en Inicio, Demanda, Horario, Despacho, Ciudad y Resultado (en Ciudad la tercera opción se llama «Los dos» y mueve el modo Real / Plan / Los dos de la vista 3D; en Demanda y Horario «Oráculo» no aplica y sale apagado). Modelo, Piloto y Método y datos no lo muestran: no tienen escenarios.

## Los dos modelos

- **Final (E11)**: LightGBM con calendario y demanda reciente; 13,94 % de error (WAPE) a una semana frente a 20,04 % de la regla manual.
- **Híbrido (E12)**: el mismo LightGBM con cuatro variables de Chronos-2; 13,62 %, −0,32 puntos en 2025 y −0,33 en 2024, fuera de la muestra de selección. Recomendado para producción; corre en CPU.

Su ficha completa está en la pantalla Modelo (viene de `app/ficha_modelos.json`, contrastada por `app/verificar_ficha_modelos.py`); el código, en `experimentos/E11_modelo_mejorado/modelo_final.py` y `experimentos/E12_comparacion_modelos/modelo_final_hibrido.py`.

## De dónde sale cada cifra

Ninguna está escrita a mano. Cada una lleva un botón **«fuente»** con su archivo, su clave, el experimento y el valor crudo. `app/DATOS.md` es el inventario legible: 202 cifras y las 23 contradicciones entre fuentes con cuál prevalece.

## Cómo se verificó

`app/generar_datos_app.py` lee cada cifra de su archivo de resultados; `app/verificar_datos_app.py` la relee con código propio y falla si algo difiere. Antes, revisores independientes recalcularon los experimentos en tres rondas. Cada fuente trae la marca **Revisor independiente: sí / parcial / no**: «sí», un revisor recalculó la cifra; «parcial», el experimento tuvo revisión pero esa corrida no se contrastó aparte (el modelo persona a persona); «no», sin revisor (el backtest del 13 de octubre de 2026).

## Lo que es honesto saber

- **El canje.** El plan no recorta: 460 → 451 salidas al día, espera 4,43 → 4,30 min, 317 → 267 pasajeros sobre la capacidad. Pero el saldo cambia de signo según cómo se cuenten los pasajeros: solo los perdidos donde se quitan salidas (conservadora, β = 0,70), 2.864 al día y −2.825 M COP al año; también los ganados (simétrica), +946 al día y +1.600 M COP. Con la conservadora, recortar no paga (−1.029 M COP; +1.939 con la simétrica, pero −1.512 pasajeros netos al día); solo domingos y festivos (+181 M COP, con 3.810 pasajeros en riesgo cada uno).
- **β se midió con fallas** (27.754 viajes que no salieron sin aviso), no con recortes planificados: 0,70 (rango 0,55–0,90); recortar deja de pagar desde 0,53. El piloto la mide en la calle con potencia 0,89 y 22.904 pasajeros en riesgo.
- **El hallazgo persona a persona.** Día a día, el plan recorta las tardes de CRA 54 más de lo que dice su promedio: el 3 de junio de 2025 pone 507 salidas frente a 600 reales (548 válidas) y pierde 5.879 pasajeros; los 353 días de 2025 dan −3.212 M COP con la contabilidad conservadora (+2.312 con la simétrica). Falta una restricción de cupo en el optimizador; se muestra con su aviso.
- **Sin medir:** los pasajeros ganados, los costos reales de Sobusa (los nuestros son de fuentes públicas de 2026), la latencia de los datos en vivo y 2026 (14,6 % más viajes, sin confirmar).

## Código y datos

`experimentos/` (E1–E13, D1–D6, P1, P2: `run.py`, `README.md` con su verificación, `resultados.json`), `costos/`, `simulacion_ahorro/`, `sistema_tiempo_real/`, `app/`, los cuadernos en la raíz, `Entrega1/` y `documentos/` (informe y propuesta). `datos/` (copias Parquet de la base, de solo lectura) no se versiona: se regenera con `scripts/`.

## Cómo reproducir las cifras

Desde la carpeta del proyecto, con Python 3.13 (`PYTHONIOENCODING=utf-8` en Windows); cada experimento se reproduce con su `run.py`:

```
python app/generar_datos_app.py     # app/datos_app.js y app/DATOS.md desde los resultados
python app/verificar_datos_app.py   # relee cada cifra con código propio; termina sin fallos
python app/probar_app.py            # Edge sin interfaz y sin internet: 9 pantallas × 2 anchos
python app/probar_paginas.py        # las cinco páginas sueltas
```
