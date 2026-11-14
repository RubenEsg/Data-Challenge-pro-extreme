// Prueba de carga k6 (spec v1.5 §14.1 «Carga | Consultas e ingesta con el volumen acordado», RNF-002, RNF-004, E08):
// consultas paginadas concurrentes MIENTRAS la API procesa una ingesta incremental como job (POST
// /api/v1/frequency/executions: lectura incremental, calidad, COPY al histórico, predicción, recomendación y alertas).
//  - setup(): crea la ejecución (HASTA, por omisión 2025-12-31) y pasa su id a todos los usuarios virtuales;
//  - escenario «consultas»: 30 usuarios virtuales constantes durante 60 s; cada uno consulta cada 3 s el estado del
//    job y etiqueta sus peticiones con fase=durante_ingesta o fase=sin_ingesta;
//  - escenario «ingesta»: 1 usuario que sondea el job hasta «ok» o «error» y registra filas y duración.
// Umbrales: p95 < 2 s de las consultas DURANTE la ingesta (RNF-002), < 1 % de fallos y la ingesta termina en ok.
//
// Uso (Docker, grafana/k6:1.4.2; la clave de rol analista SOLO por entorno):
//   docker run --rm -e BASE=http://host.docker.internal:8305 -e SOBUSA_API_KEY -e HASTA=2025-12-31 \
//     -v "$PWD/k6:/scripts" -v "$PWD/docs/evidencias/pruebas:/salida" grafana/k6:1.4.2 \
//     run --summary-export /salida/k6_ingesta.json /scripts/consultas_durante_ingesta.js
import http from 'k6/http';
import { check, sleep } from 'k6';
import { Counter, Rate, Trend } from 'k6/metrics';

const BASE = __ENV.BASE || 'http://host.docker.internal:8305';
const CLAVE = __ENV.SOBUSA_API_KEY || '';
const HASTA = __ENV.HASTA || '2025-12-31';
// Duración de la carga y espera máxima de la ingesta (s). En modo integrado la ingesta lee la réplica y tarda más:
// DURACION_S=240 LIMITE_INGESTA_S=230 cubren la ingesta completa (por omisión, 60 y 85 como antes).
const DURACION_S = Number(__ENV.DURACION_S || 60);
const LIMITE_INGESTA_S = Number(__ENV.LIMITE_INGESTA_S || 85);
const errores = new Rate('errores_funcionales');
const duracionIngesta = new Trend('ingesta_duracion_ms', true);
const ingestaOk = new Rate('ingesta_ok');
const filasIngeridas = new Counter('ingesta_filas_leidas');
const consultasDurante = new Counter('consultas_durante_ingesta');

export const options = {
  scenarios: {
    consultas: { executor: 'constant-vus', vus: 30, duration: `${DURACION_S}s`, exec: 'consultas' },
    ingesta: { executor: 'per-vu-iterations', vus: 1, iterations: 1, maxDuration: `${LIMITE_INGESTA_S + 5}s`,
      exec: 'ingesta' },
  },
  thresholds: {
    'http_req_failed{fase:durante_ingesta}': ['rate<0.01'],
    'http_req_duration{fase:durante_ingesta}': ['p(95)<2000'],
    'http_req_duration{fase:sin_ingesta}': ['p(95)<2000'],
    consultas_durante_ingesta: ['count>100'],
    errores_funcionales: ['rate<0.01'],
    ingesta_ok: ['rate==1'],
  },
  summaryTrendStats: ['avg', 'min', 'med', 'p(90)', 'p(95)', 'p(99)', 'max'],
};

const RECURSOS = [
  ['predictions', '/api/v1/predictions?limite=50'],
  ['recommendations', '/api/v1/recommendations?limite=50'],
  ['alerts', '/api/v1/alerts?limite=50'],
  ['executions', '/api/v1/frequency/executions?limite=20'],
];
// INCLUIR_SEGMENTOS=1 (modo integrado): también la capa de segmentos, que el ciclo con datos nuevos manda refrescar
if (__ENV.INCLUIR_SEGMENTOS === '1') {
  RECURSOS.push(['segmentos', '/api/v1/segmentos/estadisticas?limite=50']);
  RECURSOS.push(['segmentos_ruta', '/api/v1/segmentos/estadisticas?limite=50&idruta=2']);
}

function cabeceras(cid) {
  return { 'X-API-Key': CLAVE, 'X-Correlation-Id': cid, 'Content-Type': 'application/json' };
}

export function setup() {
  const r = http.post(`${BASE}/api/v1/frequency/executions`, JSON.stringify({ hasta: HASTA }),
    { headers: cabeceras('k6-ingesta'), tags: { recurso: 'executions_post', fase: 'setup' } });
  if (r.status !== 202) {
    throw new Error(`POST /frequency/executions respondió ${r.status}: ${r.body}`);
  }
  return { id: r.json('execution_id'), inicio: Date.now() };
}

let enCurso = true;
let ultimoSondeo = 0;

function estadoIngesta(id) {
  if (Date.now() - ultimoSondeo > 3000) {
    ultimoSondeo = Date.now();
    const d = http.get(`${BASE}/api/v1/frequency/executions/${id}`,
      { headers: cabeceras(`k6-sondeo-${__VU}`), tags: { recurso: 'executions_get', fase: 'sondeo' } });
    if (d.status === 200) {
      enCurso = d.json('estado') === 'corriendo' || d.json('estado') === 'en_cola';
    }
  }
  return enCurso;
}

export function consultas(datos) {
  const fase = estadoIngesta(datos.id) ? 'durante_ingesta' : 'sin_ingesta';
  const [recurso, ruta] = RECURSOS[Math.floor(Math.random() * RECURSOS.length)];
  const cid = `k6i-${__VU}-${__ITER}`;
  const r = http.get(`${BASE}${ruta}&desplazamiento=${Math.floor(Math.random() * 20)}`,
    { headers: cabeceras(cid), tags: { recurso, fase } });
  const ok = check(r, {
    'estado 200': (x) => x.status === 200,
    'correlation id devuelto': (x) => x.headers['X-Correlation-Id'] === cid,
  });
  errores.add(!ok);
  if (fase === 'durante_ingesta') {
    consultasDurante.add(1);
  }
  sleep(0.2 + Math.random() * 0.3);
}

export function ingesta(datos) {
  let detalle = null;
  let estado = 'en_cola';
  while (Date.now() - datos.inicio < LIMITE_INGESTA_S * 1000 && estado !== 'ok' && estado !== 'error') {
    sleep(1);
    const d = http.get(`${BASE}/api/v1/frequency/executions/${datos.id}`,
      { headers: cabeceras('k6-ingesta-sondeo'), tags: { recurso: 'executions_get', fase: 'sondeo' } });
    if (d.status === 200) {
      detalle = d.json();
      estado = detalle.estado;
    }
  }
  duracionIngesta.add(Date.now() - datos.inicio);
  ingestaOk.add(estado === 'ok');
  if (detalle && detalle.filas_leidas) {
    filasIngeridas.add(detalle.filas_leidas);
  }
  console.log(`ingesta ${datos.id}: estado=${estado} filas_leidas=${detalle ? detalle.filas_leidas : '?'} ` +
    `predicciones=${detalle ? detalle.predicciones : '?'} iniciado=${detalle ? detalle.iniciado_en : '?'} ` +
    `terminado=${detalle ? detalle.terminado_en : '?'} (${(Date.now() - datos.inicio) / 1000} s)`);
}
