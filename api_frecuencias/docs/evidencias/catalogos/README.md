# Evidencias de los catálogos operacionales

Requisitos que cubren: §3.1 «Gestión operacional», §3.2, §6.1, §8.1, §8.3, RF-014, RF-016, RF-017 y RNF-002.

Se regeneran con `.venv\Scripts\python docs\evidencias\catalogos\generar_evidencias.py`. Ese script usa la base local de pruebas y la réplica con el rol `lector_ia`. No escribe en `datos/` ni en las tablas de Extreme.

## Qué expone la API

Todas las rutas cuelgan de `/api/v1/catalogos` y exigen `X-API-Key`:

- **Procesos y empresas.**
- **Rutas.** Traen `frecuenciadespachos` y la capacidad. Si la tabla las tiene, también `cap_min_autorizada` y `cap_max_autorizada`. Suman el ciclo, la flota y los parámetros por hora.
- **Segmentos.** Traen la longitud y la geometría en GeoJSON: simplificada a unos 1 m, completa solo para la página pedida, o sin geometría.
- **Vehículos.** Traen sentados más de pie y la tipología del reporte de flota.
- **Viajes.** Es la programación.
- **Despachos.** Son las salidas reales, con su retraso.

Cada colección acepta filtros, paginación (`limite` y `desplazamiento`) y orden (`orden`, con `-` para descendente), siempre sobre una lista blanca de campos. Cada una tiene además `/export` en CSV o XLSX.

### Fuentes

1. **La réplica**, en solo lectura. Cada consulta pasa por `app.servicios.fuentes.FuentePostgresSoloLectura.consultar`, en este orden: `validar_solo_select`, `SET TRANSACTION READ ONLY`, `SET LOCAL statement_timeout`, la consulta, `ROLLBACK` y el circuit breaker. El SQL no se arma concatenando texto: son literales fijos o SQLAlchemy Core con parámetros enlazados (bandit y ruff sin hallazgos).
2. **Las exportaciones Parquet**, si no hay réplica configurada.
3. **El reporte de flota** (`insumos_sobusa/flota_sobusa.csv`), si tampoco están las exportaciones.

### Datos que no salen nunca

La placa, el conductor, el propietario, los contactos, el módem, la póliza y la posición GPS.

## El ajuste local

**`GET` y `PUT /catalogos/capacidad`**, más `GET /catalogos/capacidad/historial`. Fijan la capacidad operativa por ruta y tipología:

- Vive solo en `ai_frecuencias.threshold_config`, como parámetro gobernado del conjunto versionado, con el prefijo `capacidad_override.`.
- Solo el rol admin puede cambiarla.
- Firma el usuario autenticado, no el que viene en el cuerpo.
- El motivo es obligatorio.
- El historial muestra la acción, el valor anterior, el nuevo, quién y cuándo.
- La versión queda en `umbrales_version` de cada recomendación.

El optimizador la lee con `app.servicios.catalogos.capacidad_vigente(ruta, tipologia=None, *, umbrales=None, umbrales_version=None, sesion=None)`. Devuelve `capacidad`, `capacidad_catalogo`, `fuente` (`ajuste_local` o `catalogo`), `clave`, `umbrales_version` y `por_tipologia`.

## Archivos

| Archivo | Qué muestra |
|---|---|
| `catalogos_replica.json` · `catalogos_archivos.json` | Cada catálogo con su fuente, su total, el tiempo de la primera petición y una muestra. |
| `fidelidad_y_relaciones.txt` | La sesión de lectura (`lector_ia`, `transaction_read_only=on`, America/Bogota, 30 s). Los conteos de la réplica coinciden con las exportaciones: viajes 564.837 = 564.837 y despachos 520.648 = 520.648, por ruta y período. Además, las llaves y las longitudes de los segmentos. |
| `rendimiento.txt` | p50 y p95 de cada ruta (RNF-002: p95 < 2 s). |
| `sin_datos_personales.txt` | Comprueba que no sale ninguna columna prohibida en la réplica ni en los archivos, y muestra la cabecera del CSV de vehículos. |
| `ajuste_capacidad.txt` | El flujo completo: 403 para operador y analista, 200 para admin, una versión nueva y la lectura del optimizador. El optimizador recomienda 9, 10 y 15 buses/h con capacidades de 50, 46 y 30. Termina con el historial y el retiro del ajuste. |
| `fechas_8_1.json` | El recorrido de **todas** las rutas GET de `/api/v1` (§8.1): 47 verificadas, 2 omitidas porque exigen un filtro (422) y 0 instantes sin zona o en UTC. |
| `pytest_catalogos.txt` | 42 pruebas propias: 33 unitarias y 9 de integración, todas en verde (09-11-2026, 05:35 a 05:36). |
| `rendimiento_exportaciones.txt` · `medir_exportaciones.py` | Antes y después de acelerar `segmentos?geometria=completa` (primera petición de 8,09 s a 1,68 s) y la exportación XLSX de 100.000 despachos (de 27,6–40,3 s a 18,3–18,4 s), con el guion que lo mide. |

## Sin réplica ni exportaciones (máquina limpia, GitHub Actions)

En un clon recién descargado no hay réplica ni las exportaciones Parquet de la raíz (`datos/` no se versiona). La política es la misma en todos los catálogos y está en `app/routers/catalogos.py::_ejecutar`:

- `rutas`, `rutas/{idruta}`, `rutas/export`, `capacidad` y `capacidad/historial` responden **200** con el catálogo empaquetado de la API (`datos/catalogo_rutas.json`, `fuente = archivos_api`).
- `procesos`, `empresas`, `segmentos`, `vehiculos`, `viajes`, `despachos` y sus exportaciones responden **503 `catalogo_no_disponible`**, con el error uniforme y la variable que falta definir (`CATALOGOS_DATABASE_URL` o `CATALOGOS_DATOS_DIR`). El 503 está declarado en el OpenAPI de cada operación.
- Si la réplica está configurada pero no responde (conexión rechazada, tiempo de espera o circuito abierto), la respuesta es **503 `fuente_no_disponible`** desde la primera petición, nunca un 500.

Lo prueban `tests/integracion/test_catalogos_api.py::test_sin_replica_ni_exportaciones_cada_catalogo_responde_200_o_503_declarado` y `::test_replica_configurada_pero_caida_responde_503_y_no_500`, que corren en cualquier máquina, y la matriz de roles de `tests/integracion/test_seguridad.py`, que solo acepta un 503 si la operación lo declara. La corrida en una copia limpia está en `../pruebas/ci_limpio.txt`.

## Hallazgos de los datos

- La tabla `rutas` exportada solo trae las rutas del reto: 2, 16 y 21. `rutas_segmentos` tiene 22 configuraciones de otras rutas, así que 2.309 de sus 2.695 segmentos no tienen una ruta en esa tabla. El catálogo los muestra con `ruta = null` y se pueden filtrar por `idruta`.
- La suma de `longitud_m` coincide al decímetro con la longitud de la geometría en todas las configuraciones activas.
- 5 de los 656 vehículos usan la placa como `idvehiculo`. Es la llave de Extreme y se conserva sin cambiar su semántica (RF-014). La columna `placa` no se publica.
- Algunos despachos tienen retrasos de semanas, por ejemplo `fechainicio` un mes después de `fechasalida`. El catálogo los muestra tal cual: corregirlos le toca a la operación o a la capa de calidad.
