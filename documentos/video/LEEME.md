# Video de demostración (E11): con qué evidencia se grabó

`E11_video_demostracion.mp4`, sus subtítulos (`E11_video_demostracion.srt`) y `guion.md` son lo que se grabó. No se
cambian después: el guion es el registro de lo narrado y de lo que se ve en pantalla.

## Cuándo y con qué se grabó

- Las escenas 11 y 12 se grabaron el 9-11-2026 con las evidencias de ese día (commit `b76546d`). Las demás escenas son
  de la grabación del commit `8d4e651`.
- El registro de producción está en `../../api_frecuencias/docs/evidencias/video/registro.txt`.

## Nota del 19-11-2026: lo que el video no muestra y las cifras que cambiaron

El video se grabó el 9-11-2026, antes de la retroalimentación del curso (17-11-2026). Muestra el modelo horario, el
que pronostica cada ruta y hora con siete días de antelación y hoy arma el plan del día siguiente y semanal. No
muestra el pronóstico que pide la especificación: las subidas de los siguientes 30, 60 y 120 minutos por ruta,
sentido y segmento, con lo observado hasta el instante. Ese pronóstico se hizo después, en
`../../pronostico_corto_plazo/`; la API lo sirve y el tablero lo muestra primero en Pronóstico, en la sección «Lo que
pide el enunciado: 30, 60 y 120 minutos». No hay un video que lo muestre.

El código siguió cambiando después de la grabación y la evidencia se regeneró. El video y el guion conservan las
cifras del día en que se grabaron. Las vigentes están en `../../MATRIZ_CUMPLIMIENTO.md`, bloque «Cifras vigentes», que
sale de `../../api_frecuencias/scripts/cifras_vigentes.py`.

| Lo que dice el video | Lo vigente | Por qué cambió |
|---|---|---|
| El pronóstico es el del modelo horario, por ruta y hora | El pronóstico del enunciado es el de corto plazo, a 30, 60 y 120 minutos por ruta, sentido y segmento (`../../pronostico_corto_plazo/README.md`); el horario queda para el plan del día siguiente y semanal | La retroalimentación del curso (17-11-2026) señaló que la entrega pronosticaba a siete días por ruta y hora, y no lo que pide la especificación |
| Ciclo de §14.2: el candidato da 14,108 % frente a 13,982 % del activo y la compuerta lo rechaza | El candidato `hgb_fv3_20250930_s42` (variables fv3) da 13,578 % frente a 13,982 % del activo en la misma ventana; la compuerta lo aprueba y lo activa, y al final la demostración lo revierte con `POST /api/v1/models/rollback`, así que el activo vuelve a ser `hgb_fv2_20250831_s42` (`despliegue/demo_ciclo_api.txt`, corrida del 18-11-2026) | Desde el 15-11-2026 el candidato de la demostración se entrena con las variables fv3, que suman el calendario escolar y universitario; el de la grabación tenía las variables fv2 |
| 1.060 pruebas automáticas, sin fallas, con 5 omitidas, y 94,3 % de cobertura | Ver «Cifras vigentes» (`pruebas/suite_final.xml`, `pruebas/coverage_final.xml`) | Se agregaron pruebas con cada cambio del código |
| Alertas observadas por ruta y día: de 6,083 a 0,534 | De 6,083 a 0,543 (ALT-005 a ALT-009); con todas las reglas observadas, 1,265 (`alertas/backtest_alertas.md`) | ALT-008 evalúa también las bajadas y el backtest usa el factor de carga del ciclo |
| k6: p95 de 451,3 ms en consultas y 627,5 ms con un año de resultados | Medición vigente del 13-11-2026: p95 de 864,1 ms con 50 usuarios (`pruebas/k6_segmentos.txt`) | Se midió otra vez con el código final y un volumen sembrado mayor; las del video quedan como corridas anteriores |
| SonarQube aprueba su puerta | Ver «Cifras vigentes» (`sonarqube/quality_gate.json`) | El análisis se repite sobre el código vigente |

Las rutas de la tabla que no empiezan por `../../` son relativas a `../../api_frecuencias/docs/evidencias/`. No
cambian el modelo horario activo, `hgb_fv2_20250831_s42`, su WAPE en la prueba reservada ni la cobertura de su banda.
