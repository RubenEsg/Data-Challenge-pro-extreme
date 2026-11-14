// Prueba de carga k6 de la capa analítica de segmentos (spec v1.5 §6.1, §7.1, §14.1 «Carga», RNF-002, RNF-004):
// consultas paginadas concurrentes de GET /api/v1/segmentos/estadisticas (sin filtros, por ruta, por ruta y día, por
// hora, por segmento, por estacionalidad, con rango de fechas de un día y de una semana, con orden) y de
// GET /api/v1/catalogos/segmentos (páginas con geometría simplificada) MIENTRAS corre un refresco COMPLETO de la
// agregación materializada como trabajo de la cola (POST /api/v1/segmentos/estadisticas/refrescar, rol analista).
//  - setup(): verifica que la agregación existe (disponible=true) y encola el refresco completo;
//  - escenario «consultas»: rampa 0 -> 25 -> 50 usuarios virtuales en 60 s; cada petición lleva la etiqueta
//    fase=durante_refresco o fase=sin_refresco según el estado del trabajo (sondeado cada 3 s);
//  - escenario «refresco»: 1 usuario que sondea el trabajo hasta «ok» o «error» y registra su duración.
// Umbrales: p95 < 2 s en total, por consulta y durante el refresco (RNF-002), < 1 % de fallos y el refresco en ok.
//
// Uso (Docker, grafana/k6:1.4.2; la clave de rol analista SOLO por entorno):
//   docker run --rm -e BASE=http://host.docker.internal:8310 -e SOBUSA_API_KEY \
//     -v "$PWD/k6:/scripts" -v "$PWD/docs/evidencias/pruebas:/salida" grafana/k6:1.4.2 \
//     run --summary-export /salida/k6_segmentos.json /scripts/segmentos.js
// (scripts/medir_segmentos.py la corre así contra una API propia en modo integrado y deja la evidencia).
import http from 'k6/http';
import { check, sleep } from 'k6';
import { Rate, Trend } from 'k6/metrics';

const BASE = __ENV.BASE || 'http://host.docker.internal:8310';
const CLAVE = __ENV.SOBUSA_API_KEY || '';
const REFRESCAR = (__ENV.REFRESCAR || '1') === '1';
const errores = new Rate('errores_funcionales');
const refrescoOk = new Rate('refresco_ok');
const duracionRefresco = new Trend('refresco_duracion_ms', true);

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
      exec: 'consultas',
    },
    refresco: { executor: 'per-vu-iterations', vus: 1, iterations: 1, maxDuration: '120s', exec: 'refresco' },
  },
  thresholds: {
    http_req_failed: ['rate<0.01'],
    'http_req_duration{tipo:consulta}': ['p(95)<2000'],
    'http_req_duration{fase:durante_refresco}': ['p(95)<2000'],
    'http_req_duration{fase:sin_refresco}': ['p(95)<2000'],
    'http_req_duration{consulta:estadisticas}': ['p(95)<2000'],
    'http_req_duration{consulta:estadisticas_ruta}': ['p(95)<2000'],
    'http_req_duration{consulta:estadisticas_ruta_dia}': ['p(95)<2000'],
    'http_req_duration{consulta:estadisticas_hora_orden}': ['p(95)<2000'],
    'http_req_duration{consulta:estadisticas_segmento}': ['p(95)<2000'],
    'http_req_duration{consulta:estadisticas_estacionalidad}': ['p(95)<2000'],
    'http_req_duration{consulta:estadisticas_un_dia}': ['p(95)<2000'],
    'http_req_duration{consulta:estadisticas_semana_ruta}': ['p(95)<2000'],
    'http_req_duration{consulta:catalogo_segmentos}': ['p(95)<2000'],
    errores_funcionales: ['rate<0.01'],
    refresco_ok: ['rate==1'],
  },
  summaryTrendStats: ['avg', 'min', 'med', 'p(90)', 'p(95)', 'p(99)', 'max'],
};

const E = '/api/v1/segmentos/estadisticas';
// [nombre, ruta con sus filtros (sin limite ni desplazamiento), peso relativo]; el desplazamiento al azar recorre el
// total de cada consulta
const CONSULTAS = [
  ['estadisticas', `${E}?`, 3],
  ['estadisticas_ruta', `${E}?idruta=2&`, 3],
  ['estadisticas_ruta_dia', `${E}?idruta=16&id_dia_semana=2&`, 2],
  ['estadisticas_hora_orden', `${E}?hora=7&orden=-max_subidas&`, 2],
  ['estadisticas_segmento', `${E}?id_segmento=__SEGMENTO__&`, 1],
  ['estadisticas_estacionalidad', `${E}?id_estacionalidad=25&`, 1],
  ['estadisticas_un_dia', `${E}?desde=2023-02-14&hasta=2023-02-14&`, 1],
  ['estadisticas_semana_ruta', `${E}?idruta=21&desde=2023-02-06&hasta=2023-02-12&orden=-prom_pasajeros&`, 1],
  ['catalogo_segmentos', '/api/v1/catalogos/segmentos?', 2],
];
const BOLSA = CONSULTAS.flatMap((c) => Array(c[2]).fill(c));

function cabeceras(cid) {
  return { 'X-API-Key': CLAVE, 'X-Correlation-Id': cid, 'Content-Type': 'application/json' };
}

function url(ruta, seg, limite, desplazamiento) {
  return `${BASE}${ruta.replace('__SEGMENTO__', seg)}limite=${limite}&desplazamiento=${desplazamiento}`;
}

export function setup() {
  const r = http.get(`${BASE}${E}?limite=1`, { headers: cabeceras('k6-seg-setup'), tags: { tipo: 'setup' } });
  if (r.status !== 200 || r.json('disponible') !== true) {
    throw new Error(`${E} respondió ${r.status} sin agregación disponible: refresque antes de medir`);
  }
  const seg = r.json('items.0.id_segmento');
  const totales = {};
  for (const [nombre, ruta] of CONSULTAS) {
    const t = http.get(url(ruta, seg, 1, 0), { headers: cabeceras('k6-seg-total'), tags: { tipo: 'setup' } });
    totales[nombre] = t.status === 200 ? t.json('total') : 0;
  }
  let id = null;
  if (REFRESCAR) {
    const p = http.post(`${BASE}${E}/refrescar`, JSON.stringify({ modo: 'completo' }),
      { headers: cabeceras('k6-seg-refresco'), tags: { tipo: 'setup' } });
    if (p.status !== 202) {
      throw new Error(`POST ${E}/refrescar respondió ${p.status}: ${p.body}`);
    }
    id = p.json('execution_id');
  }
  return { id, seg, totales, inicio: Date.now() };
}

let enCurso = REFRESCAR;
let ultimoSondeo = 0;

function refrescoEnCurso(id) {
  if (!id) {
    return false;
  }
  if (enCurso && Date.now() - ultimoSondeo > 3000) {
    ultimoSondeo = Date.now();
    const d = http.get(`${BASE}/api/v1/frequency/executions/${id}`,
      { headers: cabeceras(`k6-seg-sondeo-${__VU}`), tags: { tipo: 'sondeo' } });
    if (d.status === 200) {
      enCurso = d.json('estado') === 'corriendo' || d.json('estado') === 'en_cola';
    }
  }
  return enCurso;
}

export function consultas(datos) {
  const fase = refrescoEnCurso(datos.id) ? 'durante_refresco' : 'sin_refresco';
  const [nombre, ruta] = BOLSA[Math.floor(Math.random() * BOLSA.length)];
  const total = datos.totales[nombre] || 0;
  const desplazamiento = total > 50 ? Math.floor(Math.random() * (total - 50)) : 0;
  const cid = `k6s-${__VU}-${__ITER}`;
  const r = http.get(url(ruta, datos.seg, 50, desplazamiento),
    { headers: cabeceras(cid), tags: { tipo: 'consulta', consulta: nombre, fase } });
  const ok = check(r, {
    'estado 200': (x) => x.status === 200,
    'página con total e items': (x) => x.status === 200 && Array.isArray(x.json('items')) && x.json('total') >= 0,
    'agregación disponible': (x) => nombre === 'catalogo_segmentos' || (x.status === 200 && x.json('disponible')),
    'correlation id devuelto': (x) => x.headers['X-Correlation-Id'] === cid,
  });
  errores.add(!ok);
  sleep(0.2 + Math.random() * 0.3);
}

export function refresco(datos) {
  if (!datos.id) {
    refrescoOk.add(true);
    return;
  }
  let detalle = null;
  let estado = 'en_cola';
  while (Date.now() - datos.inicio < 115000 && estado !== 'ok' && estado !== 'error') {
    sleep(1);
    const d = http.get(`${BASE}/api/v1/frequency/executions/${datos.id}`,
      { headers: cabeceras('k6-seg-refresco-sondeo'), tags: { tipo: 'sondeo' } });
    if (d.status === 200) {
      detalle = d.json();
      estado = detalle.estado;
    }
  }
  duracionRefresco.add(Date.now() - datos.inicio);
  refrescoOk.add(estado === 'ok');
  const m = detalle ? detalle.metricas || {} : {};
  console.log(`refresco ${datos.id}: estado=${estado} modo=${m.modo} tramos=${m.tramos} ` +
    `fechas=${m.fechas_releidas} filas_leidas=${m.filas_leidas} filas=${m.filas} ` +
    `duracion_trabajo_s=${m.duracion_s} (${(Date.now() - datos.inicio) / 1000} s desde el POST)`);
}
