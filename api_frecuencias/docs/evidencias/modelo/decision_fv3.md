# Decisión: modelo fv3 (calendario escolar y universitario), registrado como candidato

Fecha: 2026-11-16. Todas las cifras salen de archivos de esta carpeta, generados con los scripts del repositorio:
`entrenamiento_fv3.json`, `candidato_fv3/evaluacion_modelo.json` y `.md`, `candidato_fv3/horizontes.json`,
`candidato_fv3/explicacion_local_y_bandas.json`, `calibracion_condicional_hgb_fv3_20250831_s42.md` y
`../monitoreo/onnx_paridad_hgb_fv3_20250831_s42.json`.

**En corto.** fv3 se equivoca menos que fv2 en la validación y en los dos años congelados, con el intervalo de
confianza de la diferencia entero por debajo de cero. Queda registrado como **candidato**
(`hgb_fv3_20250831_s42`): **fv2 sigue activo** y toda la evidencia de operación de la entrega (ciclo diario, alertas,
monitoreo, respuestas al reto) sigue siendo la de fv2. Su activación pasa por la gobernanza de la API: 14 días en
sombra y la compuerta de cuatro criterios (RF-019).

## Qué cambia frente a fv2

- **Variables fv3-2026-11-16** (`app/servicios/variables.py`): las de fv2 más cinco de calendario académico, las
  mismas de E11:
  - `vac_escolar`: el día cae en un receso de los colegios oficiales de Barranquilla.
  - `vac_univ`: el día cae fuera de los periodos de clases universitarias (mediana de inicio y fin entre las
    universidades de E10).
  - `frac_vac_escolar_ventana`, `frac_vac_univ_ventana` y `frac_especial_ventana`: la fracción de los 4 días de
    referencia de los rezagos (D−7, D−14, D−21 y D−28) en receso escolar, en vacaciones universitarias o en festivo,
    Carnaval o Semana Santa. Le dicen al modelo cuándo la base de las semanas anteriores viene de otro periodo (el
    regreso a clases, el inicio de vacaciones).
- **Fuente del calendario** (`datos/calendario_academico.csv`): 20 recesos escolares (resoluciones de la Secretaría
  de Educación de Barranquilla, 2023 a 2026) y 8 periodos de clases universitarias (2023-1 a 2026-2), cada uno con su
  fuente, enlace y confianza. Es calendario publicado con antelación: no usa pasajeros ni nada posterior al
  pronóstico. Fuera de los años que cubre (hasta 2026), esas variables quedan como dato faltante; para 2027 hay que
  añadir sus filas.
- **Sin fuga y verificado.** Las cinco variables que calcula la API son idénticas a las del panel de E13 en las 55.896
  filas de 2023 a 2025.
- **Lo que se probó y no se adoptó.** Es una exploración previa con el mismo corte y las mismas filas, pero con un
  arnés aparte que no se guardó como evidencia; por eso aquí no lleva decimales y ninguna de estas variantes está en
  el código:
  - **Pesos a días atípicos** (E11 V3: 0,25 en los días atípicos no predecibles y 0,1 en las franjas con 25 % o más
    de viajes sin registro): sobre los calendarios no movieron el error de 2024 y en 2025 lo cambiaron en centésimas.
  - **Climatología:** nada.
  - **Ajuste fino de hiperparámetros** y **promedio de cinco semillas:** nada que se sostenga.
  - **El conteo corregido de pasajeros de E13** (los viajes que corrieron aunque se marcaron cancelados) bajaría el
    WAPE a cerca de 12,4 %. Cambia, sin embargo, qué se mide como demanda y, con ella, el plan y las cifras de
    dinero. Queda como siguiente paso (`experimentos/E13_limpieza_datos`).

## Reproducibilidad

`scripts/entrenar.py --hasta 2025-08-31 --semilla 42 --compuerta-activo --sin-activar --verificar-reproducible`
(`entrenamiento_fv3.json`): dos entrenamientos en carpetas temporales dan el **mismo SHA-256**,
`3e97dca70fc146e5702b87c9ccba78993c7423184986d95ee8802ee763c61190`, idéntico al del artefacto registrado. La
compuerta de entrenamiento decide «activar» (mejora a B1 y no empeora al activo en la validación) y, por
`--sin-activar`, solo lo registra (`compuerta.activado = false`): el candidato queda para la sombra.

**El código nuevo no cambia el modelo activo.** Registrar fv3 cambió `variables.py`. Por eso se comprobó con
`scripts/evaluar_codigo_modelo.py --compatibilidad` que el código actual da, para las 23 columnas de fv2, las mismas
variables en las 56.253 filas de la serie, con los mismos datos faltantes, y los mismos pronósticos de punto, P10 y
P90, con diferencia 0, que el `variables.py` con que se entrenó fv2 (blob de git `a02f804f…`). El resultado queda en
el manifiesto de fv2 (clave `compatibilidad_codigo`), y la prueba `test_preprocesamiento_es_el_del_entrenamiento_del_activo`
exige esa verificación cuando el archivo cambia.

## Cómo se eligió fv3: validación y backtests congelados

**Criterio de selección.** El mismo del protocolo y de fv2: la validación temporal (2025-09-01 a 2025-10-31) y los
backtests con modelos congelados un año antes de 2024 y de 2025.

| Evidencia de selección | fv3 | fv2 (activo) | B1 (regla manual) |
|---|---|---|---|
| Validación 2025-09-01 a 2025-10-31, WAPE % | **12,96** | 13,55 | 15,12 |
| 2024, entrenado hasta 2023-12-31, WAPE % [IC95] | **15,76** [14,63–17,21] | 16,26 [14,97–17,91] | 21,55 |
| 2025, entrenado hasta 2024-12-31, WAPE % [IC95] | **14,08** [13,52–14,69] | 14,48 [13,78–15,28] | 20,04 |

- **fv3 − fv2 en los backtests:** 2024 de −0,81 a −0,25 pp (fv3 mejora en 11 de 12 meses); 2025 de −0,78 a
  −0,12 pp (8 de 12 meses). **A diferencia de fv2 frente a fv1, la mejora no está dentro del ruido.**
- **Dónde mejora** (WAPE %, fv2 → fv3; `candidato_fv3/evaluacion_modelo.md`, «Horas afectadas»):
  - Recesos escolares: 2024 de 20,17 a 18,27 (n = 4.386); 2025 de 17,36 a 15,61 (n = 4.335).
  - Vacaciones universitarias: 2024 de 20,40 a 19,22; 2025 de 16,07 a 15,46.
  - Cambio de periodo entre el día y sus 4 días de referencia: 2024 de 17,61 a 16,91; 2025 de 15,28 a 14,87.
  - Víspera de festivo: 2024 de 23,40 a 22,13; 2025 de 20,18 a 18,35.
- **Dónde no mejora:** las horas con novedad vial de 2024 empeoran de 25,15 a 27,33 (n = 246). En 2025 mejoran, de
  33,49 a 32,77.
- **En E11** (un LightGBM con más variables) los calendarios bajaron solo 0,05 puntos. El HGB de la API no tenía cómo
  distinguir el receso escolar salvo por `vacaciones` y el mes, y ahí bajan entre 0,4 y 0,5.

## Prueba reservada (2025-11-01 a 2025-12-31, informativa)

| Modelo | WAPE % [IC95, bloques de 7 días] | Sesgo % |
|---|---|---|
| fv3 (candidato) | **14,36** [12,98–16,13] | 1,23 |
| fv2 (activo) | 14,77 [13,10–16,87] | 2,75 |
| B1 regla manual | 21,18 [16,61–26,79] | 5,85 |

- fv3 − fv2: de −1,02 a +0,06 pp, P(mejora) 0,94. fv3 − B1: de −11,23 a −3,34 pp.
- Estas cifras se calcularon también en la exploración, antes de registrar fv3. Por eso la prueba es un reporte
  informativo y no una muestra nunca vista; así lo dice la clave `historial_prueba_reservada` del manifiesto. La
  elección se apoya en la validación y en los dos backtests.

## Bandas, horizontes, factor intradía, ONNX y explicación

- **Banda P10–P90.** El protocolo de `scripts/calibrar_por_grupo.py` (criterio fijado de antemano, solo con la
  validación) adopta para fv3 el conformal de Mondrian **por ruta × bloque horario**: peor desviación de 6,34 pp en la
  validación cruzada frente a 10,05 de la v1, con el ancho medio sin subir (306 frente a 311 pasajeros). La
  calibración queda versionada junto al modelo (`calibracion_v2.json`, SHA-256 en el manifiesto). En la prueba la
  cobertura es de 77,95 % (fv2: 77,82 %), con un intervalo medio de 297,6 pasajeros.
- **Horizontes** (`candidato_fv3/horizontes.json`, modelo congelado hasta 2024-12-31, evaluado de marzo a diciembre
  de 2025), WAPE % de fv2 → fv3:
  - 30 minutos con el perfil intrahorario: de 19,43 a 19,33.
  - 60 minutos con el factor intradía: de 14,71 a 14,60.
  - 120 minutos: de 10,87 a 10,68.
- **Factor intradía (nowcast).** Su peso se elige en la validación de cada modelo. Para fv3 sale **0,0** (WAPE 13,45 %
  frente a 13,50 % con 0,1): con los calendarios, el modelo ya recoge en septiembre y octubre lo que el factor
  corregía. El mecanismo sigue igual (RF-005) y el peso se vuelve a elegir en cada entrenamiento. fv2 usa 0,1.
- **ONNX** (`../monitoreo/onnx_paridad_hgb_fv3_20250831_s42.json`): mismo WAPE con los dos motores y 0,07 ms por fila
  frente a 5 ms.
  - El criterio de paridad pasó a la regla de `numpy.isclose`: en cada fila, |ONNX − scikit-learn| ≤ 0,01 +
    0,001 · |scikit-learn|.
  - El criterio anterior exigía por separado una diferencia absoluta máxima menor de 0,01 y una relativa máxima menor
    de 0,001 sobre max(|y|, 1). Con fv3 el P90 de una hora casi vacía (1,5 pasajeros) difirió 0,0015 pasajeros,
    1,04e-3 relativo.
  - La diferencia máxima es de 0,005 pasajeros en el punto, 0,0018 en P10 y 0,0015 en P90.
- **Explicación SHAP** (`candidato_fv3/explicacion_local_y_bandas.json`, `scripts/evidencia_explicacion_local.py`):
  - Reconstruye el pronóstico de las 3.111 horas de la prueba con un error relativo máximo de 2,7e-14.
  - `predecir()` completo tarda 30 ms en la mediana.
  - Entre las 28 variables, las cinco nuevas quedan en los puestos 9, 11, 14, 15 y 17 de la importancia media
    |SHAP|. La primera sigue siendo la media de 8 semanas (la regla manual).
- **Reversión.** fv2 y fv1 siguen cargando y prediciendo con el código actual, cada uno con sus columnas
  (`reversion_modelos_anteriores`).

## Decisión

**Se registra `hgb_fv3_20250831_s42` como candidato y se recomienda activarlo después de la sombra.**

- Pasa la compuerta de entrenamiento: mejora a B1 y no empeora al activo en la validación (12,96 % ≤ 13,55 %).
- Mejora a fv2 en los dos backtests congelados, con el intervalo de la diferencia entero bajo cero.
- Trae banda calibrada versionada, exportación ONNX y explicación exacta.

No se activa en esta entrega porque activar cambia los pronósticos que usan unas 25 evidencias de operación:

- el ciclo diario y sus mediciones;
- los backtests de alertas y su revisión humana, que no se puede repetir;
- el monitoreo y los ejemplos del optimizador;
- las respuestas a la pregunta del reto.

Esas evidencias se midieron con fv2 y siguen valiendo para fv2.

**Cómo activarlo:**
1. La política de la API pone el candidato 14 días en sombra en el ciclo diario.
2. La compuerta de cuatro criterios decide sobre esa ventana: WAPE no peor que el activo ni que `wape_max`, cobertura
   P10–P90 entre 75 % y 90 %, y sesgo dentro de `sesgo_max`.
3. La activación a mano es `POST /api/v1/models/hgb_fv3_20250831_s42/activate`, con rol admin, y pasa por la misma
   compuerta.
4. Para volver atrás se reactiva `hgb_fv2_20250831_s42`.
