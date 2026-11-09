// Prueba de carga k6 (spec v1.5 §14.1 «Carga | k6 | Consultas e ingesta con el volumen acordado», RNF-002, E08):
// consultas PAGINADAS concurrentes (limite y desplazamiento al azar dentro del total real de cada colección).
// Rampa 0 -> 25 -> 50 usuarios virtuales en 60 s. Umbrales: p95 < 2 s (RNF-002) en total y por recurso, < 1 % de fallos.
//
// Volumen acordado (un año de resultados, scripts/sembrar_volumen.py): con -e MIN_PREDICCIONES=3300 -e MIN_ALERTAS=8000
// la prueba se niega a empezar si la base tiene menos filas (así no se mide por error contra una base pequeña).
//
// Uso (Docker, imagen grafana/k6:1.4.2; la clave SOLO por entorno, nunca en el repositorio):
//   docker run --rm -e BASE=http://host.docker.internal:8305 -e SOBUSA_API_KEY \
//     -v "$PWD/k6:/scripts" -v "$PWD/docs/evidencias/pruebas:/salida" grafana/k6:1.4.2 \
//     run --summary-export /salida/k6_consultas.json /scripts/consultas.js
import http from 'k6/http';
import { check, sleep } from 'k6';
import { Rate } from 'k6/metrics';

const MINIMOS = { predictions: Number(__ENV.MIN_PREDICCIONES || 0), alerts: Number(__ENV.MIN_ALERTAS || 0) };

const BASE = __ENV.BASE || 'http://host.docker.internal:8305';
const CLAVE = __ENV.SOBUSA_API_KEY || '';
const errores = new Rate('errores_funcionales');

export const options = {
  scenarios: {
    consultas: {
      executor: 'ramping-vus',
      startVUs: 0,
      stages: [
        { duration: '10s', target: 25 },
        { duration: '40s', target: 50 },
        { duration: '10s', target: 0 },
      ],
      gracefulRampDown: '5s',
    },
  },
  thresholds: {
    http_req_failed: ['rate<0.01'],
    http_req_duration: ['p(95)<2000'],
    'http_req_duration{recurso:predictions}': ['p(95)<2000'],
    'http_req_duration{recurso:recommendations}': ['p(95)<2000'],
    'http_req_duration{recurso:alerts}': ['p(95)<2000'],
    'http_req_duration{recurso:executions}': ['p(95)<2000'],
    'http_req_duration{recurso:models}': ['p(95)<2000'],
    errores_funcionales: ['rate<0.01'],
  },
  summaryTrendStats: ['avg', 'min', 'med', 'p(90)', 'p(95)', 'p(99)', 'max'],
};

const RECURSOS = [
  ['predictions', '/api/v1/predictions', 50],
  ['recommendations', '/api/v1/recommendations', 50],
  ['alerts', '/api/v1/alerts', 50],
  ['executions', '/api/v1/frequency/executions', 20],
  ['models', '/api/v1/models', 20],
];

function cabeceras(cid) {
  return { 'X-API-Key': CLAVE, 'X-Correlation-Id': cid };
}

// totales reales de cada colección (una vez, antes de la carga) para paginar dentro del rango
export function setup() {
  const totales = {};
  for (const [recurso, ruta] of RECURSOS) {
    const r = http.get(`${BASE}${ruta}?limite=1`, { headers: cabeceras('k6-setup') });
    if (r.status !== 200) {
      throw new Error(`${ruta} respondió ${r.status}: revise BASE y SOBUSA_API_KEY`);
    }
    totales[recurso] = r.json('total');
  }
  for (const [recurso, minimo] of Object.entries(MINIMOS)) {
    if ((totales[recurso] || 0) < minimo) {
      throw new Error(`${recurso}: ${totales[recurso]} filas, menos que el volumen acordado (${minimo})`);
    }
  }
  return { totales };
}

export default function (datos) {
  const [recurso, ruta, limite] = RECURSOS[Math.floor(Math.random() * RECURSOS.length)];
  const total = datos.totales[recurso] || 0;
  const desplazamiento = total > limite ? Math.floor(Math.random() * (total - limite)) : 0;
  const cid = `k6-${__VU}-${__ITER}`;
  const r = http.get(`${BASE}${ruta}?limite=${limite}&desplazamiento=${desplazamiento}`,
    { headers: cabeceras(cid), tags: { recurso } });
  const ok = check(r, {
    'estado 200': (x) => x.status === 200,
    'página con total e items': (x) => x.status === 200 && Array.isArray(x.json('items')) && x.json('total') >= 0,
    'correlation id devuelto': (x) => x.headers['X-Correlation-Id'] === cid,
  });
  errores.add(!ok);
  sleep(0.2 + Math.random() * 0.3);
}
