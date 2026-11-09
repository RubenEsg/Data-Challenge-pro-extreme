// Prueba k6 de peticiones EN FRÍO (spec v1.5 §14.1 «Carga», RNF-002): la PRIMERA petición a cada ruta de lectura
// justo después de arrancar la API, sin calentamiento ni caché, y luego una segunda pasada para comparar.
// Incluye las consultas pesadas: segmentos/estadisticas (lee la réplica operacional), catálogos, monitoreo,
// exportaciones y, si INCLUIR_PLAN=1, el plan del día y la respuesta del reto (FECHA_PLAN, RUTA_PLAN).
//
// Cada petición lleva la etiqueta {ruta, pasada}; el umbral p95 < 2 s se evalúa por pasada. En frío hay una sola
// muestra por ruta, así que el p95 de la pasada «frio» es, en la práctica, el máximo entre rutas.
//
// Uso (Docker, imagen grafana/k6:1.4.2; la clave SOLO por entorno):
//   docker run --rm -e BASE=http://host.docker.internal:8507 -e SOBUSA_API_KEY \
//     -v "$PWD/k6:/scripts" -v "$PWD/docs/evidencias/pruebas:/salida" grafana/k6:1.4.2 \
//     run --summary-export /salida/k6_en_frio.json /scripts/en_frio.js
import http from 'k6/http';
import { check } from 'k6';
import { Trend } from 'k6/metrics';

const BASE = __ENV.BASE || 'http://host.docker.internal:8507';
const CLAVE = __ENV.SOBUSA_API_KEY || '';
const FECHA_PLAN = __ENV.FECHA_PLAN || '2025-11-20';
const RUTA_PLAN = __ENV.RUTA_PLAN || 'CL 72';
const duracion = new Trend('duracion_por_ruta', true);

export const options = {
  scenarios: {
    en_frio: { executor: 'per-vu-iterations', vus: 1, iterations: 1, maxDuration: '10m' },
  },
  thresholds: {
    'http_req_duration{pasada:frio}': ['p(95)<2000'],
    'http_req_duration{pasada:caliente}': ['p(95)<2000'],
    'checks': ['rate>0.99'],
  },
  summaryTrendStats: ['avg', 'min', 'med', 'p(90)', 'p(95)', 'p(99)', 'max'],
};

const RUTAS = [
  ['predictions', '/api/v1/predictions?limite=50'],
  ['recommendations', '/api/v1/recommendations?limite=50'],
  ['alerts', '/api/v1/alerts?limite=50'],
  ['alerts_filtradas', '/api/v1/alerts?limite=50&severidad=critica'],
  ['executions', '/api/v1/frequency/executions?limite=20'],
  ['models', '/api/v1/models?limite=20'],
  ['thresholds', '/api/v1/thresholds'],
  ['monitoring', '/api/v1/monitoring?limite=20'],
  ['monitoring_policy', '/api/v1/monitoring/policy'],
  ['feature_snapshots', '/api/v1/monitoring/feature-snapshots?limite=20&ruta=CL%2072'],
  ['catalogos', '/api/v1/catalogos'],
  ['catalogos_rutas', '/api/v1/catalogos/rutas'],
  ['catalogos_empresas', '/api/v1/catalogos/empresas'],
  ['catalogos_procesos', '/api/v1/catalogos/procesos'],
  ['catalogos_segmentos', '/api/v1/catalogos/segmentos?limite=50'],
  ['catalogos_vehiculos', '/api/v1/catalogos/vehiculos?limite=50'],
  ['catalogos_capacidad', '/api/v1/catalogos/capacidad'],
  ['segmentos_estadisticas', '/api/v1/segmentos/estadisticas?limite=50'],
  ['segmentos_estadisticas_ruta', '/api/v1/segmentos/estadisticas?limite=50&idruta=2'],
  ['segmentos_zonas', '/api/v1/segmentos/zonas?limite=50'],
  ['predictions_export', '/api/v1/predictions/export?formato=csv'],
  ['alerts_export', '/api/v1/alerts/export?formato=csv'],
];
if (__ENV.INCLUIR_PLAN === '1') {
  RUTAS.push(['recommendations_plan', `/api/v1/recommendations/plan?ruta=${encodeURIComponent(RUTA_PLAN)}&fecha=${FECHA_PLAN}`]);
  RUTAS.push(['respuesta', `/api/v1/respuesta?fecha=${FECHA_PLAN}`]);
}

function pedir(nombre, ruta, pasada) {
  const cid = `k6-frio-${pasada}-${nombre}`;
  const r = http.get(`${BASE}${ruta}`, {
    headers: { 'X-API-Key': CLAVE, 'X-Correlation-Id': cid },
    tags: { ruta: nombre, pasada },
    timeout: '120s',
  });
  duracion.add(r.timings.duration, { ruta: nombre, pasada });
  // 200, o 503 declarado cuando la fuente de esa ruta no existe en la máquina (RNF-010), o 404 «sin_calcular»
  check(r, {
    'estado esperado': (x) => x.status === 200 || x.status === 503 || x.status === 404,
    'correlation id devuelto': (x) => x.headers['X-Correlation-Id'] === cid,
  }, { ruta: nombre, pasada });
  console.log(`${pasada}\t${nombre}\t${r.status}\t${r.timings.duration.toFixed(1)} ms`);
}

export default function () {
  for (const [nombre, ruta] of RUTAS) pedir(nombre, ruta, 'frio');
  for (const [nombre, ruta] of RUTAS) pedir(nombre, ruta, 'caliente');
}
