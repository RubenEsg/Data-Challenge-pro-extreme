# Documentos de entrega (E01, E02 y presentación final de E11)

| Archivo | Entregable (especificación v1.5, §15) | Presupuesto |
|---|---|---|
| `E01_documento_ejecutivo.pdf` | E01 · problema, valor, resultados, limitaciones y recomendación | exactamente 2 páginas |
| `E02_especificacion_tecnica.pdf` | E02 · arquitectura, datos, modelo, optimización, alertas, base de datos, integración, API, RNF, pruebas, seguridad y decisiones técnicas | 12 a 16 páginas |
| `presentacion_final.pdf` y `.pptx` | E11 · presentación final, una diapositiva por criterio de §16, el ciclo de §14.2 y la respuesta a la pregunta del reto; el `.pptx` lleva las notas del orador | 12 a 15 diapositivas |
| `video/E11_video_demostracion.mp4` | E11 · video de la demostración, con subtítulos (`video/E11_video_demostracion.srt`) y guion (`video/guion.md`); cómo se grabó y se verificó: `api_frecuencias/docs/evidencias/video/` | máximo 5 minutos |

## Compilar

El entorno virtual va fuera del repositorio (por ejemplo, en la carpeta temporal):

```
python -m venv %TEMP%\venv_documentos
%TEMP%\venv_documentos\Scripts\python -m pip install -r EntregaFinal/documentos/requisitos_documentos.txt
%TEMP%\venv_documentos\Scripts\python EntregaFinal/documentos/compilar.py
```

`compilar.py` regenera las cifras, las figuras y la tabla de endpoints; compila los tres documentos con Tectonic; revisa
cada `.log` (referencias o citas sin resolver, cajas desbordadas de más de 10 pt, caracteres sin glifo); cuenta las
páginas y falla si se sale de un presupuesto; busca en el texto cadenas de conexión o claves y cifras sin dato
(«s. d.»), y arma el `.pptx` con las notas de `notas_orador.txt`. Sale con código 1 si algo falla.

## De dónde sale cada cifra

- `datos_documentos.py` lee las evidencias de `api_frecuencias/docs/evidencias/` y escribe `generado/cifras.tex`: una
  macro por cifra, con el archivo de origen en un comentario. Ningún número de los documentos se escribe a mano, salvo
  los que citan otro archivo en el texto (el informe técnico, `PLAN_EVOLUCION.md` y los resultados de la réplica en
  `docs/integracion_postgresql.md`).
- La corrida de pruebas citada es la suite completa final, `api_frecuencias/docs/evidencias/pruebas/suite_final.xml`,
  con la cobertura de `pruebas/coverage_final.xml`. Mientras no existan, los documentos citan la última corrida completa
  versionada (`contrato/suite_completa_junit.xml`, con `sonarqube/coverage.xml`) y lo dicen en el texto. Los casos de
  Testcontainers se cuentan en `pruebas/ci/pytest.xml`; SonarQube sale de `sonarqube/measures.json`, y la línea de la
  integración continua, de `pruebas/ci_github.txt` (si no existe, el texto dice «reproducida en local»). Para citar otra
  corrida se fijan las variables `EVIDENCIA_PRUEBAS`, `EVIDENCIA_COBERTURA` y `EVIDENCIA_CI_GITHUB`.
- El calendario (conexión en las semanas 1 a 4, modo sombra en las 5 a 8 y piloto en las 9 a 16), los costos de
  infraestructura y el criterio para salir del modo sombra, por horizonte, salen de `../PLAN_EVOLUCION.md` (secciones
  1.1, 3.1 y 6.3), que es la única fuente.
- El modelo de los documentos es el del producto, `hgb_fv2_20250831_s42`. Las cifras de los experimentos 11 y 12 del
  informe académico (13,94 % y 13,62 %) usan otro protocolo; cuando aparecen, se dice por qué difieren
  (`../README.md`, «Las cifras principales»).
- `tabla_api.py` genera la tabla de endpoints de E02 desde la aplicación FastAPI (con el Python del venv de la API,
  variable `API_PYTHON`) y, si no puede importarla, desde `api_frecuencias/docs/openapi.json`.
- La diapositiva de la respuesta a la pregunta del reto lee `api_frecuencias/docs/evidencias/respuesta/respuesta_*.json`
  (la fecha se elige con `RESPUESTA_FECHA`).

## Estilo

El mismo del tablero (`dash_app/DISENO.md`): letra Inter (`fuentes/`, generada con `generar_fuentes.py` desde la del
tablero; licencia SIL OFL 1.1 en `fuentes/OFL.txt`) y colores por rol leídos de `dash_app/tokens.py`
(`generado/colores.tex`). Los gráficos usan un solo eje, rótulos directos y leyenda cuando hay dos series o más. La
figura del plan que reasigna (`figuras/plan_reasigna.pdf`) la regenera `datos_documentos.py` con la paleta del tablero
desde los mismos resultados del informe técnico; si no existe, la presentación usa la del informe
(`informe/figuras/fig_plan_reasigna.pdf`).
