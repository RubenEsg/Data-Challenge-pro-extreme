# SonarQube: análisis del backend de frecuencias

- Servidor: SonarQube 26.11.0.134175 (Community Build) en Docker, contenedor `sobusa_sonar`, 127.0.0.1:9000.
- Proyecto: `sobusa-api-frecuencias` (código analizado: `app/`; pruebas: `tests/`).
- Análisis: 2026-11-19T02:29:35+0000 · evidencia generada 2026-11-18T21:30:35-05:00.
- Perfil de calidad: «Reto Sobusa v1.5» (hereda de «Sonar way comprehensive», el perfil integrado más completo de SonarQube para Python, y activa además todas las reglas de seguridad de Python): 408 reglas activas, 62 de seguridad (61 del perfil padre más python:S5439).

## Puerta de calidad «Reto Sobusa v1.5»: **APROBADA**

Se evalúa sobre todo el código (no solo el código nuevo). Cada condición falla si se cumple la comparación.

| Condición | Falla si | Valor medido | Resultado |
|---|---|---|---|
| Cobertura de pruebas (%) (`coverage`) | < 85 | 95.8 | cumple |
| Líneas duplicadas (%) (`duplicated_lines_density`) | > 3 | 0.0 | cumple |
| Hallazgos bloqueantes (`blocker_violations`) | > 0 | 0 | cumple |
| Bugs (`bugs`) | > 0 | 0 | cumple |
| Hallazgos críticos (`critical_violations`) | > 0 | 0 | cumple |
| Vulnerabilidades (`vulnerabilities`) | > 0 | 0 | cumple |

Condiciones sin valor en este análisis (no aplican): security_hotspots_reviewed. `security_hotspots_reviewed` no tiene valor cuando no hay security hotspots.

## Medidas (todo el código)

| Medida | Valor |
|---|---|
| Líneas de código (ncloc) | 20875 |
| Bugs | 0 |
| Vulnerabilidades | 0 |
| Security hotspots (revisados) | 0 (— %) |
| Code smells | 1741 |
| Cobertura de pruebas | 95.8 % (líneas por cubrir: 16148, sin cubrir: 684) |
| Duplicación | 0.0 % |
| Confiabilidad / Seguridad / Mantenibilidad | A / A / A |
| Confiabilidad / Seguridad / Mantenibilidad, vista por impacto (la del tablero) | B (4 hallazgos) / A (0) / A (1740) |
| Revisión de seguridad | A |
| Hallazgos aceptados con justificación | 1 |
| Deuda técnica | 8689 min (1.4 %) |
| Pruebas importadas (junit) | 1800 (fallas 0, errores 0, omitidas 10) |

Hallazgos abiertos: 1741 (MAJOR: 1703, MINOR: 38). El detalle de cada uno está en `issues.json`; los security hotspots y su revisión, en `hotspots.json`.

### Deuda de mantenibilidad aceptada con justificación

1 hallazgos de mantenibilidad (code smells) se aceptaron uno por uno con su justificación, que queda como comentario en SonarQube y en `issues.json` (`aceptados_con_justificacion`). Las decisiones están versionadas en `scripts/sonar_decisiones.json`; ningún bug, vulnerabilidad ni hallazgo de seguridad se acepta por esta vía.

| Regla | Severidad | Archivo:línea |
|---|---|---|
| `python:S3776` | CRITICAL | `app/servicios/motor_d5/milp.py:139` |

## Pruebas y análisis estático que alimentan el análisis

- pytest (todas las suites salvo Testcontainers): 1810 pruebas, 0 fallas, 0 errores, 10 omitidas, código de salida 0, 2289.7 s. La cobertura que lee SonarQube incluye todo `app/` (también `app/servicios/motor_d5/`).
- ruff (todo el repositorio de la API): 0 hallazgos (`docs/evidencias/calidad/ruff.txt`).
- bandit `-r app` (todas las severidades): 0 hallazgos; bandit `-r scripts -ll`: 0 (`docs/evidencias/calidad/bandit.txt`).
- sonar-scanner-cli terminó con código 0 (0 = puerta aprobada; el registro está en `scanner.log`).

## Alcance y límites

- La edición Community de SonarQube no incluye el análisis de flujo de datos (taint analysis) que detecta inyecciones; el tablero lo advierte. Ese frente lo cubren bandit (`-r app`, todas las severidades), la regla de solo lectura de la fuente (`app/servicios/fuentes.py`: solo SELECT, transacción READ ONLY y statement_timeout) y las pruebas de seguridad de `tests/unit` y `tests/integracion`.
- La base embebida de SonarQube (H2) sirve para evaluación, como advierte el tablero; el análisis es completo y se reproduce con el script de abajo.

## Cómo reproducirlo

```
cd EntregaFinal/api_frecuencias
.venv/Scripts/python.exe scripts/sonar_local.py --archivo-clave <ruta fuera del repositorio>/sonar_admin.txt
```

El script arranca SonarQube en Docker, crea el perfil y la puerta, corre las pruebas con cobertura, ruff y bandit, ejecuta sonar-scanner-cli y reescribe esta carpeta. La clave de admin se guarda solo en el archivo indicado (fuera del repositorio) y el token de análisis vive en memoria y se revoca al terminar.

Archivos: `quality_gate.json` (estado y definición de la puerta), `measures.json`, `issues.json`, `hotspots.json`, `perfil_calidad.json`, `scanner.log` y `tablero_sonarqube.png` (tablero del proyecto, código completo).
