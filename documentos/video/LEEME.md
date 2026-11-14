# Video de demostración (E11): con qué evidencia se grabó

`E11_video_demostracion.mp4`, sus subtítulos (`E11_video_demostracion.srt`) y `guion.md` son lo que se grabó. No se
cambian después: el guion es el registro de lo narrado y de lo que se ve en pantalla.

## Cuándo y con qué se grabó

- Las escenas 11 y 12 se grabaron el 9-11-2026 con las evidencias de ese día (commit `b76546d`). Las demás escenas son
  de la grabación del commit `8d4e651`.
- El registro de producción está en `../../api_frecuencias/docs/evidencias/video/registro.txt`.

## Nota del 14-11-2026: cifras que cambiaron después de la grabación

El código siguió cambiando después del 9-11-2026 y la evidencia se regeneró. El video y el guion conservan las cifras
de la grabación. Las vigentes están en `../../MATRIZ_CUMPLIMIENTO.md`, bloque «Cifras vigentes», que sale de
`../../api_frecuencias/scripts/cifras_vigentes.py`.

| Lo que dice el video | Cifra vigente | Por qué cambió |
|---|---|---|
| 1.060 pruebas automáticas, sin fallas, con 5 omitidas | 1.770 casos, 0 fallas, 0 errores y 0 omitidas (`pruebas/suite_final.xml`, 14-11-2026) | Se agregaron pruebas, y la suite final corre también los procesos reales y las pruebas de escritura en la réplica |
| 94,3 % de cobertura | 95,70 % (`pruebas/coverage_final.xml`) | La misma razón |
| Alertas observadas por ruta y día: de 6,083 a 0,534 | De 6,083 a 0,543 (ALT-005 a ALT-009); con todas las reglas observadas, 1,265 (`alertas/backtest_alertas.md`) | ALT-008 evalúa también las bajadas y el backtest usa el factor de carga del ciclo |
| k6: p95 de 451,3 ms en consultas y 627,5 ms con un año de resultados | Medición vigente del 13-11-2026: p95 de 864,1 ms con 50 usuarios (`pruebas/k6_segmentos.txt`) | Se midió otra vez con el código final y un volumen sembrado mayor; las del video quedan como corridas anteriores |
| Ciclo de §14.2 en la pila creada desde cero | Las mismas filas, el mismo candidato y la misma decisión; cambian las alertas de cada paso (`despliegue/demo_esperado.md`) | Las alertas observadas evalúan ahora cada día del lote |

Las rutas de la tabla son relativas a `../../api_frecuencias/docs/evidencias/`. No cambian el modelo activo, su WAPE,
la cobertura de la banda, la decisión de la compuerta ni la puerta de SonarQube, que sigue aprobada.
