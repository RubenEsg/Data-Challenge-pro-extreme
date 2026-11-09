Evidencias del contrato de la API (spec v1.5 §12.1, §12.2, §8.1, RNF-006, RNF-009 y §14.1 «Contrato»)
Fecha: 09-11-2026. Base local de pruebas: PostgreSQL 14 + PostGIS 3.4 en Docker (puerto 5433), autenticación encendida.

Archivos
- operaciones_codigos.txt   Todas las operaciones del OpenAPI con su rol mínimo, los estados que declaran, los tipos
                            de contenido del éxito y los valores de «codigo» propios de cada error (x-codigos-error);
                            generado desde app.openapi(). Los conteos están en su encabezado: 59 rutas y 62
                            operaciones.
- schemathesis.txt          Resumen de la última corrida de Schemathesis con cinco chequeos en TODAS las operaciones
                            (not_a_server_error, status_code_conformance, content_type_conformance,
                            response_schema_conformance, response_headers_conformance); la hora, la versión y los
                            ejemplos por operación están en su encabezado. Resultado: 62 de 62 operaciones sin fallas.
- schemathesis_junit.xml    Reporte junit de esa corrida (una subprueba por operación).
- generar_evidencia_contrato.py  Regenera los tres archivos anteriores (corre tests/contrato/test_schemathesis.py con la
                            base local de pruebas): python docs/evidencias/contrato/generar_evidencia_contrato.py
- pytest_contrato.txt       Corrida de tests/contrato completa (OpenAPI, compatibilidad, presentación y guarda NUL,
                            Schemathesis) con los conteos exactos: 178 casos (116 pruebas y 62 subpruebas de
                            Schemathesis), 0 fallas, 0 errores, 0 omitidas y sin xfail.
- traza_entre_replicas.txt  RNF-006: la réplica que toma un trabajo de la cola continúa la traza W3C de la petición
                            que lo encoló (mismo trace_id, padre remoto = span guardado en execution_log.traceparent).
- en_vivo_uvicorn.txt       Las mismas garantías con el servidor real (uvicorn): byte NUL en consulta, ruta y cuerpo
                            -> 422 uniforme con X-Correlation-Id; horizonte fuera de rango -> 422; /metrics text/plain.
- suite_completa_junit.xml  Junit de una corrida intermedia de la suite completa (unit, integracion, replica,
                            contrato, datos_ml) del 09-11-2026 a las 03:42: 828 casos, 0 fallas, 0 errores, 4
                            omitidas a propósito. La suite vigente es la que cita la tabla «Cifras vigentes» de
                            ../README.md.

Qué garantiza el contrato (y qué prueba lo demuestra)
- §12.1 errores uniformes: todo 4xx/5xx es {"error": {codigo, mensaje, detalle, correlation_id}} y está declarado con
  el esquema RespuestaError en su operación: test_errores_documentados_en_openapi, test_422_formato_uniforme,
  test_404_formato_uniforme, test_401_sin_clave_o_clave_invalida_en_todas_las_operaciones,
  test_403_rol_insuficiente_en_escrituras y Schemathesis (status_code_conformance + response_schema_conformance).
- Cada error enumera los valores posibles de «codigo» en «x-codigos-error» (los generales, como «no_autenticado» o
  «validacion», y los propios de la operación, que también van en su descripción: 422 «ventana_en_muestra»,
  «motivo_requerido» y «rango_invalido», 409 «requiere_forzar», 404 «sin_calcular» y «sin_datos», entre otros).
  test_codigos_que_lanza_el_codigo_estan_documentados exige que cada ErrorApi(<estado>, "<código>") del router esté
  declarado con su estado; test_errores_propios_en_vivo_son_uniformes_y_declarados los provoca con llamadas reales.
- Escrituras de §5.1 y §7.1: POST /api/v1/respuesta/calcular responde 202 con analista (la foto se calcula en la cola),
  403 con operador y 404 «sin_datos» para 2030-01-01 sin encolar nada; POST /api/v1/thresholds/{version}/aprobar es
  solo de admin, idempotente (conserva la primera firma), 403 con analista, 404 con una versión inexistente:
  test_calcular_respuesta_202_analista_403_operador_404_sin_datos y test_aprobar_umbrales_admin_idempotente_403_404_422.
- Lo que el código lanza está declarado: test_codigos_que_lanza_el_codigo_estan_documentados revisa cada endpoint y
  sus auxiliares (ErrorApi(<código>) y no_encontrado).
- Degradación declarada (RNF-010): sin réplica ni exportaciones (una máquina limpia o GitHub Actions) los catálogos
  que dependen de ellas responden 503 «catalogo_no_disponible» y, con la réplica configurada pero caída, 503
  «fuente_no_disponible»; nunca 500. El 503 está declarado en cada operación degradable
  (test_503_documentado_donde_la_ruta_se_degrada) y la matriz de roles y Schemathesis solo lo aceptan si lo está
  (tests/integracion/test_seguridad.py y test_schemathesis.py). Corrida limpia: ../pruebas/ci_limpio.txt.
- Entradas límite sin 500: enteros acotados (desplazamiento, horizonte_min), byte NUL rechazado con 422 en ruta,
  consulta, cabeceras y cuerpo, cuerpo ilegible con 400 documentado y fechas extremas con 422: test_byte_nul_es_422_
  uniforme, test_valores_fuera_de_rango_son_422, test_cuerpo_ilegible_es_400_uniforme_y_documentado y Schemathesis.
- Tipos de contenido veraces: /metrics text/plain; 13 exportaciones text/csv y xlsx: test_tipos_de_contenido_
  documentados y content_type_conformance.
- Cabeceras: X-Correlation-Id obligatorio en toda respuesta, WWW-Authenticate en el 401, Content-Disposition en las
  exportaciones: test_cabeceras_y_etiquetas_documentadas y response_headers_conformance.
- §8.1: todo instante (también dentro de los JSONB y de las celdas JSON de las exportaciones) en -05:00:
  tests/integracion/test_catalogos_api.py::test_toda_la_api_presenta_los_instantes_en_bogota (estricto) y
  tests/contrato/test_presentacion_y_guarda.py.
- RNF-009 (API documentada y versionada): docs/openapi.json al día («python scripts/ci_local.py openapi» = sin deriva)
  y compatibilidad hacia atrás en tests/contrato/test_compatibilidad_openapi.py.
- Filtro espacial de alertas (geography(Point,4326) + GiST, ST_DWithin; haversine sin PostGIS):
  test_filtro_espacial_de_alertas y test_alerta_sin_postgis_usa_haversine.

Cómo reproducir (desde EntregaFinal/api_frecuencias, con el PostgreSQL local de pruebas arriba)
  TEST_DATABASE_NAME=ai_frecuencias_pruebas_contrato python -m pytest tests/contrato -q
  python scripts/ci_local.py openapi
Implementación: app/openapi_doc.py (hook openapi(), guarda NUL, manejador de fuera de rango), app/routers/comun.py
(cotas de consulta), app/esquemas.py (presentación §8.1), app/observabilidad.py (RNF-006), app/routers/alertas.py.
