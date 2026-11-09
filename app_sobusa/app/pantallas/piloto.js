// Sobusa Despacho · pantallas/piloto.js — Piloto · ¿Cómo lo comprobamos?
// La pantalla completa del diseño del piloto (experimentos/P2_piloto_beta): qué harían, cuándo, cuánto dura y qué se
// aprende; las franjas; el calendario; la potencia; la simulación que recupera β; el riesgo y el costo; las reglas de
// parada; la operación; «Ver cómo se calculó»; los límites y el enlace al README de P2. Sigue el contrato de
// app/DISEÑO.md §5 (registrarPantalla con render, actualizar y salir) y el wireframe de §7.
//
// Ninguna cifra está escrita aquí: todas salen de window.DATOS_APP (app/datos_app.js, generado por
// app/generar_datos_app.py) y cada una lleva su botón «fuente». Ids que lee, de pantallas.piloto: piloto_parametros,
// piloto_franjas, piloto_potencia, piloto_simulacion, piloto_calendario, piloto_riesgo_por_franja, piloto_totales,
// piloto_reglas_de_parada, piloto_planilla, piloto_ejemplo_analisis, piloto_por_que; de Inicio: inicio_beta_origen.
// Si un id falta, la pantalla lo dice en un aviso y pinta «—» en su lugar. Sin interruptor y sin módulo.
(function (global) {
  'use strict';

  const ID = 'piloto';
  // Años del ruido con que P2 calculó la potencia (como ANIO en resultado.js): el texto no los escribe sueltos.
  const ANIO_RUIDO = '2025', ANIO_RUIDO_ALT = '2024';
  const F = COMPONENTES.formato;
  const icono = function (nombre, clase) { return ICONOS.svg(nombre, clase); };
  const FINO = ' ';
  const CONJ = 'recorte conjunta';
  const VI = 'VI', MCO = 'MCO';
  const ORDEN_FRANJAS = ['R1', 'R2', 'R3', 'F1', 'F2'];
  const ROL = { recorte: 'recorte', refuerzo: 'refuerzo', control: 'control' };

  // ---- Estado de la pantalla -----------------------------------------------------------------------------------
  let cont = null;              // div.pantalla que nos da la app
  let graficos = {};            // clave → instancia de ECharts
  let limpiezas = [];           // funciones que deshacen observadores
  let nPop = 0;                 // popovers creados en este render
  let faltantes = [];           // ids que no están en DATOS_APP

  // ---- Acceso a los datos --------------------------------------------------------------------------------------
  function app() { return global.app; }
  function anotar(id) { if (faltantes.indexOf(id) < 0) faltantes.push(id); }
  function C(id) { const c = app().cifra(ID, id); if (!c) anotar(id); return c; }
  function CX(pantalla, id) { const c = app().cifra(pantalla, id); if (!c) anotar(id); return c; }
  function V(id) { const c = C(id); return c && c.valor !== undefined && c.valor !== null ? c.valor : null; }

  // ---- Formato -------------------------------------------------------------------------------------------------
  function esNum(v) { return typeof v === 'number' && isFinite(v); }
  function n(v, d) { return esNum(v) ? F.numero(v, d || 0) : '—'; }
  function pct(v, d) { return esNum(v) ? F.numero(v, d === undefined ? 0 : d) + FINO + '%' : '—'; }
  function pctPot(v) { return esNum(v) ? n(v * 100, 0) + FINO + '%' : '—'; }   // potencia 0-1 → %
  function signoU(v, d, u) { return esNum(v) ? F.signo(v, d) + (u ? FINO + u : '') : '—'; }
  function esc(s) { return String(s === undefined || s === null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'); }
  function llano(t) { return String(t || '').replace(/`/g, '').replace(/\*\*/g, ''); }
  function lista(a, d) { return Array.isArray(a) && a.length ? a.map(function (x) { return n(x, d); }).join(' / ') : '—'; }
  function rango(a, d) { if (!Array.isArray(a) || !a.length) return '—'; const mn = Math.min.apply(null, a), mx = Math.max.apply(null, a); return mn === mx ? n(mn, d) : n(mn, d) + '-' + n(mx, d); }
  function horasDe(f) { const h = (f && f.horas) || []; return h.length ? n(h[0]) + '-' + n(h[h.length - 1]) + FINO + 'h' : '—'; }
  function entreHoras(f) { const h = (f && f.horas) || []; return h.length ? 'entre las ' + n(h[0]) + ' y las ' + n(h[h.length - 1] + 1) : ''; }
  // Fechas AAAA-MM-DD sin husos horarios (como COMPONENTES.formato).
  function sumarDias(iso, k) {
    const p = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(iso || ''));
    if (!p) return iso;
    return new Date(Date.UTC(+p[1], +p[2] - 1, +p[3]) + k * 86400000).toISOString().slice(0, 10);
  }
  function diasEntre(a, b) {
    const pa = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(a || '')), pb = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(b || ''));
    if (!pa || !pb) return null;
    return Math.round((Date.UTC(+pb[1], +pb[2] - 1, +pb[3]) - Date.UTC(+pa[1], +pa[2] - 1, +pa[3])) / 86400000);
  }

  // ---- Fuente: popover y botón (uno por botón, para que cada popover se abra bajo el botón que lo invoca) --------
  function popoverDe(c, titulo, extra) {
    nPop += 1;
    const idPop = 'pil-f-' + nPop;
    app().popoverFuente(idPop, Object.assign({}, c, extra || {}), titulo);
    return idPop;
  }
  // Botón «fuente» de una cifra de esta pantalla (o de otra, con o.pantalla).
  // o: { clave (la clave exacta dentro del archivo), ruta (se añade a la clave de la cifra), valor (el valor crudo de
  // esa parte), que_mide, texto (botón con texto) }.
  function fuente(id, titulo, o) {
    o = o || {};
    const c = o.pantalla ? CX(o.pantalla, id) : C(id);
    if (!c) return '';
    const extra = {};
    if (o.clave) extra.clave = o.clave; else if (o.ruta) extra.clave = (c.clave || '') + ' → ' + o.ruta;
    extra.valor = typeof o.valor === 'number' || typeof o.valor === 'string' ? o.valor
      : (typeof c.valor === 'number' || typeof c.valor === 'string' ? c.valor : undefined);
    if (o.que_mide) extra.que_mide = o.que_mide;
    return app().botonFuente(popoverDe(c, titulo, extra), o.texto);
  }
  // Un solo botón «Fuentes (n)» con varias cifras: [[id, título, pantalla?], …]; soloIcono para la cabecera de una ficha.
  function fuentes(lista_, titulo, soloIcono) {
    const pares = [];
    lista_.forEach(function (x) { const c = x[2] ? CX(x[2], x[0]) : C(x[0]); if (c) pares.push([c, x[1]]); });
    if (!pares.length) return '';
    nPop += 1;
    const idPop = 'pil-f-' + nPop;
    app().popoverFuentes(idPop, pares, titulo);
    return app().botonFuente(idPop, soloIcono ? undefined : 'Fuentes (' + n(pares.length) + ')');
  }
  function chip(id) { const c = C(id); return c ? app().chipVerificado(c.verificado) : ''; }

  // ---- Piezas de HTML -------------------------------------------------------------------------------------------
  function seccion(id, titulo, intro, cuerpo) {
    return '<section class="seccion" id="' + id + '"><div class="seccion__cab"><h2 class="seccion__titulo">' + titulo + '</h2></div>' +
      (intro ? '<p class="seccion__intro">' + intro + '</p>' : '') + '<div class="seccion__cuerpo">' + cuerpo + '</div></section>';
  }
  function aviso(tipo, titulo, cuerpo) {
    const ic = tipo === 'canje' ? 'canje' : tipo === 'bien' ? 'bien' : tipo === 'nota' ? 'info' : 'alerta';
    return '<div class="aviso' + (tipo && tipo !== 'nota' ? ' aviso--' + tipo : '') + '">' + icono(ic) + '<div class="aviso__cuerpo"><h3 class="aviso__titulo">' + titulo + '</h3>' + cuerpo + '</div></div>';
  }
  function ficha(etiqueta, valorHtml, unidad, o) {
    o = o || {};
    return '<article class="cifra' + (o.llana ? ' cifra--llana' : '') + '"><header class="cifra__cab"><h3 class="cifra__etiqueta">' + etiqueta + '</h3>' + (o.fuente || '') + '</header>' +
      '<p class="cifra__valor' + (o.frase ? ' cifra__valor--frase' : '') + '"><span class="num">' + valorHtml + '</span>' + (unidad ? '<span class="cifra__unidad">' + esc(unidad) + '</span>' : '') + '</p>' +
      (o.variacion ? '<p class="cifra__variacion' + (o.variacionClase ? ' ' + o.variacionClase : '') + '">' + o.variacion + '</p>' : '') +
      (o.nota ? '<p class="cifra__nota">' + o.nota + '</p>' : '') + '</article>';
  }
  // Tabla de datos: la primera columna (y las de opciones.textoEn) son texto; las demás, números alineados a la derecha.
  function tabla(caption, cabeceras, filas, opciones) {
    opciones = opciones || {};
    const esTexto = function (i) { return i === 0 || (opciones.textoEn && opciones.textoEn.indexOf(i) >= 0); };
    const claseDe = function (i) { const c = []; if (!esTexto(i)) c.push('num'); if (opciones.enteraEn && opciones.enteraEn.indexOf(i) >= 0) c.push('piloto__celda-entera'); return c.length ? ' class="' + c.join(' ') + '"' : ''; };
    let h = (opciones.sinMarco ? '' : '<div class="tabla-marco">') + '<table class="tabla' + (opciones.compacta ? ' tabla--compacta' : '') + '">';
    if (caption) h += '<caption>' + caption + '</caption>';
    h += '<thead><tr>' + cabeceras.map(function (c, i) { return '<th scope="col"' + claseDe(i) + '>' + c + '</th>'; }).join('') + '</tr></thead><tbody>';
    filas.forEach(function (fila) {
      h += '<tr' + (fila.clase ? ' class="' + fila.clase + '"' : '') + '>' + fila.celdas.map(function (c, i) {
        return i === 0 ? '<th scope="row">' + c + '</th>' : '<td' + claseDe(i) + '>' + c + '</td>';
      }).join('') + '</tr>';
    });
    return h + '</tbody></table>' + (opciones.sinMarco ? '' : '</div>');
  }
  function figura(id, titulo, sub, leyendaHtml, tablaHtml, pieHtml, aria) {
    return '<figure class="grafico" id="' + id + '"><figcaption class="grafico__cab"><div class="grafico__titulos"><h3 class="grafico__titulo">' + titulo + '</h3>' +
      (sub ? '<p class="grafico__sub">' + sub + '</p>' : '') + '</div><div class="grafico__acciones">' +
      '<button class="boton boton--secundario boton--pequeno" type="button" data-ver-tabla>' + icono('tabla') + '<span data-texto>Ver tabla</span></button></div></figcaption>' +
      (leyendaHtml ? '<ul class="leyenda">' + leyendaHtml + '</ul>' : '') +
      '<div class="grafico__lienzo" id="' + id + '-lienzo" role="img" aria-label="' + esc(aria || titulo) + '"></div>' +
      '<div class="grafico__tabla tabla-marco" id="' + id + '-tabla" hidden>' + tablaHtml + '</div>' +
      '<div class="grafico__pie">' + (pieHtml || '') + '</div></figure>';
  }
  // Leyenda en HTML: el color va como token (--c: var(--serie-…)), nunca escrito.
  function itemLeyenda(nombre, token, variante) {
    return '<li><button class="leyenda__item" type="button" data-serie="' + esc(nombre) + '" aria-pressed="true"><span class="leyenda__muestra leyenda__muestra--' + (variante || 'barra') + '" style="--c: var(' + token + ')"></span>' + esc(nombre) + '</button></li>';
  }
  function ligarLeyenda(ul, obtener) {
    if (!ul || ul._ligada) return;
    ul._ligada = true;
    COMPONENTES.leyenda(ul, obtener);
  }
  function desplegable(id, titulo, cuerpo, llano_) {
    return '<details class="desplegable' + (llano_ ? ' desplegable--llano' : '') + '" id="' + id + '"><summary class="desplegable__resumen">' + icono('chevron-derecha', 'icono desplegable__chevron') + titulo + '</summary><div class="desplegable__cuerpo">' + cuerpo + '</div></details>';
  }

  // ---- Estilos propios de la pantalla (solo tokens) --------------------------------------------------------------
  function estilos() {
    if (document.getElementById('estilos-piloto')) return;
    const st = document.createElement('style');
    st.id = 'estilos-piloto';
    st.textContent = [
      '.piloto__graficos { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 400px), 1fr)); gap: var(--e-4); }',
      '.piloto__tarjetas { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 300px), 1fr)); gap: var(--e-4); align-items: start; }',
      '.piloto__tarjetas .tarjeta, .piloto__tarjeta { display: grid; gap: var(--e-3); align-content: start; }',
      '.piloto__tarjetas h3, .piloto__tarjeta h3 { font-size: var(--t-l); }',
      '.piloto__tarjetas p, .piloto__tarjeta p { max-width: var(--ancho-texto); text-wrap: pretty; }',
      '.piloto__lista { margin: 0; padding-left: 20px; display: grid; gap: var(--e-2); max-width: var(--ancho-texto); text-wrap: pretty; }',
      '.piloto__lista li { min-width: 0; }',
      '.piloto__lista .tabla-marco { max-width: 100%; margin-top: var(--e-2); }',
      '.piloto__lista strong { color: var(--tinta); }',
      '.piloto__lista--numerada li::marker { font-weight: var(--peso-fuerte); color: var(--tinta-2); }',
      '.piloto__sub { display: block; font-size: var(--t-s); color: var(--tinta-3); font-weight: var(--peso-normal); }',
      '.piloto__pie { font-size: var(--t-s); color: var(--tinta-3); display: flex; flex-wrap: wrap; gap: var(--e-2) var(--e-4); align-items: center; }',
      '.piloto__pie a { color: var(--acento); }',
      '.piloto__nota { font-size: var(--t-s); color: var(--tinta-2); max-width: var(--ancho-texto); text-wrap: pretty; }',
      '.piloto__nota .fuente, .piloto__lista .fuente, .entradilla .fuente, .aviso .fuente, .cifra__nota .fuente { vertical-align: middle; }',
      '.piloto__cifras-tarjeta { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 180px), 1fr)); gap: var(--e-3) var(--e-4); }',
      '.piloto__calendario .linea-tiempo--horizontal .hito__texto { font-size: var(--t-xs); }',
      '.piloto__calendario .hito__fecha { white-space: nowrap; }',
      '.piloto__planillas { margin: 0; display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 160px), 1fr)); gap: var(--e-3) var(--e-4); font-size: var(--t-s); }',
      '.piloto__planillas div { display: grid; gap: 2px; }',
      '.piloto__planillas dt { color: var(--tinta-2); }',
      '.piloto__planillas dd { margin: 0; font-family: var(--fuente-titulos); font-size: var(--t-xl); font-weight: var(--peso-fuerte); font-variant-numeric: tabular-nums; letter-spacing: var(--ls-titulo); }',
      '.piloto__planillas dd span { font-family: var(--fuente-texto); font-size: var(--t-s); font-weight: var(--peso-normal); color: var(--tinta-2); letter-spacing: 0; margin-left: 4px; }',
      '.piloto__que { display: grid; grid-template-columns: minmax(0, 12em) minmax(0, 1fr); gap: var(--e-2) var(--e-4); margin: 0; font-size: var(--t-s); }',
      '.piloto__que dt { color: var(--tinta-2); } .piloto__que dd { margin: 0; }',
      '@media (max-width: 600px) { .piloto__que { grid-template-columns: minmax(0, 1fr); } .piloto__que dd { margin-bottom: var(--e-2); } }',
      '.piloto__formula { font-family: var(--fuente-mono); font-size: var(--t-s); background: var(--superficie-2); border-radius: var(--radio-s); padding: var(--e-2) var(--e-3); overflow-wrap: anywhere; }',
      '#pil-fichas .cifra { grid-template-rows: auto auto 1fr; align-content: stretch; }',
      '#pil-fichas .cifra__nota { align-self: end; }',
      '#pil-riesgo-fichas { grid-template-columns: repeat(auto-fit, minmax(min(100%, 190px), 1fr)); }',
      '.piloto__celda-entera { white-space: nowrap; }',
    ].join('\n');
    document.head.appendChild(st);
  }

  // ---- Datos derivados ------------------------------------------------------------------------------------------
  function parametros() { return V('piloto_parametros') || {}; }
  function betaYEquilibrio() { const par = parametros(); return { beta: par.beta_e7, eq: par.beta_equilibrio_costos_fuente, rango: par.beta_rango_e7 || [] }; }
  function franjas() { return V('piloto_franjas') || {}; }
  function franjasOrdenadas() { const fr = franjas(); return ORDEN_FRANJAS.filter(function (k) { return fr[k]; }); }
  function filasSim() { const s = V('piloto_simulacion'); return s && Array.isArray(s.resumen) ? s.resumen : []; }
  function filaSim(franja, beta, estimador, escenario) {
    escenario = escenario || 'principal';
    return filasSim().filter(function (r) {
      return r.franja === franja && esNum(r.beta_verdadero) && Math.abs(r.beta_verdadero - beta) < 1e-9 &&
        String(r.estimador).indexOf(estimador) === 0 && String(r.escenario).indexOf(escenario) === 0;
    })[0] || null;
  }
  function claveSim(r, campo) {
    return 'simulacion.resumen[escenario=' + r.escenario + '&beta_verdadero=' + r.beta_verdadero + '&franja=' + r.franja + '&estimador=' + r.estimador + '].' + campo;
  }
  function betasSimuladas() {
    const b = {};
    filasSim().forEach(function (r) { if (String(r.escenario).indexOf('principal') === 0 && esNum(r.beta_verdadero)) b[r.beta_verdadero] = true; });
    return Object.keys(b).map(Number).sort(function (x, y) { return x - y; });
  }
  function eeSim() { const s = V('piloto_simulacion'); return (s && s.ee_analitico_vs_empirico) || {}; }
  function riesgoFranja(k) { return (V('piloto_riesgo_por_franja') || []).filter(function (r) { return r.franja === k; })[0] || null; }
  // Nombre corto de una franja para tablas: «R1 · 9-11 h», «R3 · domingo 9-13 h», «F2 · CL 72 12-15 h».
  function nombreCorto(k) {
    if (k === CONJ) return 'Recorte conjunta';
    const f = franjas()[k] || {};
    const dom = /domingo/i.test(f.tipo_dia || '') ? 'domingo ' : '';
    const ruta = f.ruta && f.ruta !== 'CRA 54' ? f.ruta + ' ' : '';
    return k + ' · ' + ruta + dom + horasDe(f);
  }
  // Etiqueta de eje en dos líneas (cabe a 400 px): «R1» / «9-11 h»; la conjunta, «Conjunta» / «R1+R2+R3».
  function etiquetaEje(k) {
    if (k === CONJ) return 'Conjunta\n' + franjasOrdenadas().filter(function (x) { return (franjas()[x] || {}).rol === ROL.recorte; }).join('+');
    const f = franjas()[k] || {};
    const dom = /domingo/i.test(f.tipo_dia || '') ? 'dom ' : '';
    const ruta = f.ruta && f.ruta !== 'CRA 54' ? f.ruta + '\n' : '';
    return k + '\n' + ruta + dom + horasDe(f);
  }
  function queHace(f) {
    if (!f) return '—';
    if (f.rol === ROL.recorte) return 'Quita ' + n(Math.abs(f.k)) + ' salidas por hora';
    if (f.rol === ROL.refuerzo) return 'Añade ' + n(Math.abs(f.k)) + ' salidas por hora';
    return 'No cambia (control)';
  }

  // ---- 1. Resumen: qué, cuándo, cuánto dura, qué se aprende -----------------------------------------------------
  function resumen() {
    const par = parametros(), cal = V('piloto_calendario') || {}, pot = V('piloto_potencia') || {}, tot = V('piloto_totales') || {}, fr = franjas();
    const be = betaYEquilibrio();
    const conj = pot[CONJ] || {};
    const simConj = filaSim(CONJ, be.beta, VI) || {};
    const trat = cal.dias_tratados || {};
    const R1 = fr.R1 || {}, R2 = fr.R2 || {}, R3 = fr.R3 || {}, F1 = fr.F1 || {}, F2 = fr.F2 || {};
    const menos = function (f) { return n(Math.abs(f.k || 0)) + ' buses menos por hora ' + entreHoras(f); };
    const mas = function (f) { return n(Math.abs(f.k || 0)) + ' buses más por hora ' + entreHoras(f); };
    const entradilla = '<p class="entradilla">Durante <strong>' + n(par.semanas_piloto) + ' semanas</strong>, en ' + esc(R1.ruta || '') + ', unos días sorteados de antemano y marcados en un calendario salen ' +
      menos(R1) + ' y ' + menos(R2) + ', con los buses repartidos parejos; otros días salen ' + mas(F1) + '; otros días las dos cosas (el plan que reasigna, el que recomienda el estudio); y otros, todo como siempre. ' +
      'En ' + esc(F2.ruta || '') + ', la mitad de los días salen ' + mas(F2) + '. Y ' + n(trat.R3) + ' de los ' + n(cal.domingos) + ' domingos salen ' + menos(R3) + '. ' +
      'El despachador solo necesita el calendario y una planilla con las salidas por hora de cada tipo de día. ' +
      fuentes([['piloto_franjas', 'franjas: cuántas salidas y a qué horas'], ['piloto_calendario', 'calendario: domingos tratados'], ['piloto_parametros', 'semanas del piloto']], 'qué harían') + '</p>';

    const fichas = '<div class="cifras" id="pil-fichas">' +
      ficha('Cuánto dura', n(par.semanas_piloto), 'semanas', {
        nota: 'Del ' + esc(F.fechaLarga(cal.inicio)) + ' al ' + esc(F.fechaLarga(cal.fin)) + ': ' + n(cal.dias_laborales) + ' días laborales y ' + n(cal.domingos) + ' domingos, con una revisión a la mitad.',
        fuente: fuente('piloto_calendario', 'calendario', { clave: 'calendario.semanas; calendario.inicio; calendario.fin; calendario.dias_laborales; calendario.domingos', que_mide: 'Semanas del piloto y días que entran en él; los festivos quedan fuera.' }) }) +
      ficha('Lo que hay que distinguir', 'β = ' + n(be.beta, 2) + ' frente a ' + n(be.eq, 2), '', { frase: true,
        nota: 'La β que E7 midió con fallas (rango creíble de ' + n(be.rango[0], 2) + ' a ' + n(be.rango[1], 2) + ') frente a la β a partir de la cual el plan que recorta deja de pagar.',
        fuente: fuente('piloto_parametros', 'parámetros del diseño', { clave: 'parametros.beta_e7; parametros.beta_rango_e7; parametros.beta_equilibrio_costos_fuente', que_mide: 'β: por cada parte de las salidas que se quita en una franja, se pierde β veces esa parte de sus pasajeros.' }) }) +
      ficha('Precisión de la β de recorte', '±' + n(conj.ic95_semiancho_2025, 2), '', {
        nota: 'Intervalo del 95' + FINO + '% de la β conjunta (recortes de mañana, tarde y domingo) con el ruido de ' + ANIO_RUIDO + '. Potencia para distinguir las dos β: ' + pctPot(conj.potencia_070_vs_053_una_cola) + ' con la fórmula y ' + pctPot(simConj.potencia_beta_mayor_053) + ' en la simulación.',
        fuente: fuentes([['piloto_potencia', 'intervalo y potencia (fórmula)'], ['piloto_simulacion', 'potencia (simulación)']], 'precisión de la β conjunta', true) }) +
      ficha('Pasajeros en riesgo', n(tot.pax_riesgo_piloto_beta070), 'pasajeros', {
        nota: 'En todo el piloto, con β = ' + n(be.beta, 2) + ': el ' + pct(tot.pax_riesgo_piloto_pct_pax_anual_cra54, 2) + ' de los que ' + esc(R1.ruta || '') + ' mueve en un año. Saldo entre ' + F.signo(tot.neto_total_piloto_Mcop_conservador, 1) + ' y ' + signoU(tot.neto_total_piloto_Mcop_simetrico, 1, 'M COP') + ' según cómo se cuenten los pasajeros ganados.',
        fuente: fuente('piloto_totales', 'totales del piloto', { clave: 'riesgo_costo.totales_piloto.pax_riesgo_piloto_beta070; …pax_riesgo_piloto_pct_pax_anual_cra54; …neto_total_piloto_Mcop_conservador; …neto_total_piloto_Mcop_simetrico', valor: tot.pax_riesgo_piloto_beta070 }) }) +
      '</div>';

    const re = tot.reasignacion_R1_a_F1 || {};
    const aprende = '<div class="tarjeta piloto__tarjeta"><h3>Qué se aprende al cierre</h3><ul class="piloto__lista">' +
      '<li><strong>Si el intervalo de la β de recorte queda por debajo de ' + n(be.eq, 2) + ':</strong> los recortes moderados del valle pagan y el plan puede recortar.</li>' +
      '<li><strong>Si queda por encima de ' + n(be.eq, 2) + ':</strong> recortar no paga y solo se reasigna (por encima de ' + n(be.beta, 2) + ' se confirma lo que E7 midió).</li>' +
      '<li><strong>Si cubre ' + n(be.eq, 2) + ':</strong> se reasigna y, si la gerencia necesita decidir sobre recortar, se extiende el piloto.</li>' +
      '<li><strong>Para los refuerzos:</strong> mover buses del valle de la mañana al pico de la tarde no pierde pasajeros si la β de refuerzo llega a ' + n(re.beta_refuerzo_que_iguala_pasajeros, 2) + ' y no pierde dinero si llega a ' + n(re.beta_refuerzo_que_iguala_dinero, 2) + '.</li>' +
      '<li><strong>Además:</strong> si recortar los domingos es un ahorro real, y si lo que se pierde en una franja se recupera en las horas vecinas o se va a otra ruta de Sobusa.</li>' +
      '</ul><p class="piloto__nota">' + fuentes([['piloto_parametros', 'β de E7 y β de equilibrio'], ['piloto_totales', 'β de refuerzo que iguala pasajeros y dinero']], 'qué se aprende') + ' ' + chip('piloto_totales') + '</p></div>';

    return '<section class="seccion" id="piloto-resumen" aria-labelledby="pil-resumen-t"><h2 class="oculto" id="pil-resumen-t">El piloto en una página</h2>' + entradilla + fichas + aprende + '</section>';
  }

  // Por qué hace falta: β se midió con fallas, no con recortes (aviso de atención).
  function porQue() {
    const pq = C('piloto_por_que');
    const origen = CX('inicio', 'inicio_beta_origen');
    let p = '';
    if (origen && esNum(origen.valor)) {
      p += '<p>β se midió con ' + n(origen.valor) + ' viajes registrados que no salieron (el ' + pct(origen.pct, 1) + ' de los ' + n(origen.viajes_registrados) + ' registrados): fallas sin aviso, no recortes planificados. ' +
        fuente('inicio_beta_origen', 'con qué se midió β', { pantalla: 'inicio' }) + '</p>';
    }
    if (pq && typeof pq.valor === 'string') p += '<p>' + esc(llano(pq.valor)) + ' ' + fuente('piloto_por_que', 'por qué hace falta el piloto') + '</p>';
    p += '<p>Los refuerzos nunca se han medido: las fallas solo informan de reducciones. Que reasignar pague con la contabilidad conservadora depende de que las salidas añadidas en las horas cargadas atraigan pasajeros. Por eso el piloto alterna días dentro de la misma semana y sortea cuáles: un antes y después confundiría el recorte con la tendencia, el calendario escolar y el clima, y dejar que el despachador elija los días «flojos» es la contaminación que hace que una regresión sin sorteo dé menos.</p>';
    return aviso('atencion', 'Por qué hace falta el piloto: β se midió con fallas, no con recortes', p);
  }

  function queDecide() {
    const pot = V('piloto_potencia') || {};
    const be = betaYEquilibrio();
    const f1 = pot.F1 || {}, f2 = pot.F2 || {};
    const p = '<p>Las franjas de <strong>recorte</strong> miden cuántos pasajeros se pierden al quitar salidas planificadas: eso decide el plan que recorta, que no proponemos. ' +
      'Las franjas de <strong>refuerzo</strong> miden cuántos pasajeros atraen las salidas añadidas en los picos: eso es lo que decide la propuesta, que reasigna. ' +
      'Esa segunda medida es menos precisa: potencia de ' + pctPot(f1.potencia_070_vs_053_una_cola) + ' y ' + pctPot(f2.potencia_070_vs_053_una_cola) +
      ' en las dos franjas de refuerzo para distinguir β = ' + n(be.beta, 2) + ' de ' + n(be.eq, 2) + '; en cambio, dicen con potencia casi total si los buses añadidos atraen pasajeros (β mayor que cero). ' +
      fuente('piloto_potencia', 'potencia en las franjas de refuerzo', { clave: 'potencia.diseno_propuesto["F1"].potencia_070_vs_053_una_cola; potencia.diseno_propuesto["F2"].potencia_070_vs_053_una_cola' }) + '</p>' +
      '<p>Si las salidas añadidas atraen pocos pasajeros, el saldo del plan se acerca al de la cuenta conservadora, que es negativo (ver <a href="#resultado">Resultado</a>), y lo prudente es no cambiar el horario.</p>';
    return aviso('canje', 'Qué decide el piloto y qué no', p);
  }

  // ---- 2. Las franjas ---------------------------------------------------------------------------------------------
  function tablaFranjas() {
    const fr = franjas(), pot = V('piloto_potencia') || {}, cal = V('piloto_calendario') || {};
    const trat = cal.dias_tratados || {}, ctrl = cal.dias_control || {};
    const ks = Object.keys(fr);
    if (!ks.length) return '<p class="texto-2">Sin datos de las franjas.</p>';
    const be = betaYEquilibrio();
    const filas = ks.map(function (k) {
      const f = fr[k] || {}, p = pot[k] || {};
      return { celdas: [
        esc(llano(f.nombre || k)) + ' ' + fuente('piloto_franjas', 'franja ' + k, { clave: 'franjas_piloto.' + k }),
        esc(queHace(f)),
        esc(f.tipo_dia || '—') + ', ' + horasDe(f),
        lista(f.salidas_habituales) + ' → ' + lista(f.salidas_dia_tratado),
        rango(f.intervalo_habitual_min, 1) + ' → ' + rango(f.intervalo_tratado_min, 1),
        lista(f.pasajeros_media_hora_2025),
        esNum(trat[k]) ? n(trat[k]) + ' / ' + n(ctrl[k]) : (f.rol === ROL.control ? 'todos' : '—'),
        esNum(p.potencia_070_vs_053_una_cola) ? pctPot(p.potencia_070_vs_053_una_cola) : '',
      ] };
    });
    return tabla('Las franjas del piloto', ['Franja', 'Qué se hace', 'Tipo de día y horas', 'Salidas por hora: hoy → día tratado', 'Intervalo medio (min): hoy → tratado', 'Pasajeros por hora en ' + ANIO_RUIDO, 'Días tratados / de control', 'Potencia (β ' + n(be.beta, 2) + ' frente a ' + n(be.eq, 2) + ')'], filas, { compacta: true, textoEn: [1, 2], enteraEn: [1, 2] }) +
      '<p class="piloto__nota">Cada día se sortea si la franja va tratada o normal, en bloques de pocas semanas balanceados por día de la semana, así que el calendario ya está sorteado de antemano. ' +
      'Los cambios siguen al plan que recorta con costos con fuente: donde quita cerca de cuatro salidas por hora, el piloto quita cuatro; donde añade, añade. La hora de control nunca cambia y sirve de placebo: en los días tratados no debería pasar nada allí. ' +
      fuentes([['piloto_franjas', 'salidas, intervalos y pasajeros por franja'], ['piloto_calendario', 'días tratados y de control'], ['piloto_potencia', 'potencia por franja']], 'franjas') + '</p>';
  }

  // ---- 3. Calendario: línea de tiempo de las semanas ---------------------------------------------------------------
  function calendario() {
    const cal = V('piloto_calendario') || {};
    const par = parametros();
    const semanas = esNum(cal.semanas) ? cal.semanas : par.semanas_piloto;
    if (!esNum(semanas) || !cal.inicio) return '<p class="texto-2">Sin calendario.</p>';
    const festivos = Array.isArray(cal.festivos_dentro) ? cal.festivos_dentro : [];
    const mitad = semanas % 2 === 0 ? semanas / 2 : null;
    let hitos = '';
    for (let i = 0; i < semanas; i++) {
      const lunes = sumarDias(cal.inicio, 7 * i), domingo = sumarDias(cal.inicio, 7 * i + 6);
      const fest = festivos.filter(function (f) { const d = diasEntre(lunes, f); return d !== null && d >= 0 && d <= 6; });
      const partes = [];
      let clase = '';
      if (i === 0) partes.push('Arranque: el despachador recibe el calendario y la planilla.');
      if (mitad !== null && i + 1 === mitad) { partes.push('Revisión intermedia: se estima la β conjunta y, si ya decide, el piloto se para (regla de parada temprana).'); clase = ' hito--activo'; }
      if (i === semanas - 1) partes.push('Cierre: análisis final y decisión.');
      fest.forEach(function (f) { partes.push('Festivo el ' + esc(F.fechaCorta(f)) + ': ese día no entra al piloto.'); });
      hitos += '<li class="hito' + clase + '"><span class="hito__fecha">' + esc(F.fechaCorta(lunes)) + ' a ' + esc(F.fechaCorta(domingo)) + '</span><p class="hito__titulo">Semana ' + n(i + 1) + '</p>' +
        (partes.length ? '<p class="hito__texto">' + partes.join(' ') + '</p>' : '') + '</li>';
    }
    const pl = cal.planillas_cra54_laboral || {};
    const nombresPl = { N: 'N: todo como siempre', R: 'R: solo recorte', F: 'F: solo refuerzo', RF: 'RF: recorte y refuerzo (el plan que reasigna)' };
    const planillas = ['N', 'R', 'F', 'RF'].filter(function (k) { return esNum(pl[k]); }).map(function (k) {
      return '<div><dt>' + esc(nombresPl[k]) + '</dt><dd>' + n(pl[k]) + '<span>días</span></dd></div>';
    }).join('');
    const sinPiloto = esNum(pl['—']) ? pl['—'] : null;
    return '<div class="piloto__calendario pila"><ol class="linea-tiempo linea-tiempo--horizontal">' + hitos + '</ol>' +
      '<p class="piloto__nota">Del ' + esc(F.fechaLarga(cal.inicio)) + ' al ' + esc(F.fechaLarga(cal.fin)) + ': ' + n(cal.dias_laborales) + ' días laborales (' + n(festivos.length) + ' festivos quedan fuera) y ' + n(cal.domingos) + ' domingos. ' +
      'El calendario se sortea con una semilla fija (' + n(par.semilla) + ') y se puede regenerar para otro lunes de arranque, fuera de Carnaval, Semana Santa y vacaciones escolares. ' +
      fuentes([['piloto_calendario', 'inicio, fin, días laborales, festivos y domingos'], ['piloto_parametros', 'semilla del sorteo']], 'calendario') + '</p>' +
      (planillas ? '<div class="tarjeta piloto__tarjeta"><h3>Los días laborales de ' + esc((franjas().R1 || {}).ruta || '') + ', por planilla</h3><dl class="piloto__planillas">' + planillas + '</dl>' +
        '<p class="piloto__nota">Cada tipo de día tiene su planilla; los demás días de la ventana' + (sinPiloto !== null ? ' (' + n(sinPiloto) + ': sábados, domingos y festivos)' : '') + ' no entran a las franjas laborales. ' +
        fuente('piloto_calendario', 'planillas de CRA 54 laboral', { clave: 'calendario.planillas_cra54_laboral' }) + '</p></div>' : '') + '</div>';
  }

  // ---- 4. Potencia: dos gráficos (error estándar y potencia) con tabla gemela ---------------------------------------
  function categoriasPotencia() { return franjasOrdenadas().concat([CONJ]); }
  function datosPotencia() {
    const pot = V('piloto_potencia') || {}, ee = eeSim(), be = betaYEquilibrio();
    const par = parametros();
    const cats = categoriasPotencia();
    const filas = cats.map(function (k) {
      const p = pot[k] || {}, e = ee[k] || {}, s = filaSim(k, be.beta, VI) || {};
      return { k: k, nombre: nombreCorto(k), p: p, e: e, s: s };
    });
    return { cats: cats, filas: filas, replicas: par.replicas, be: be };
  }
  function seccionPotencia() {
    const d = datosPotencia();
    const potC = C('piloto_potencia') || {};
    const nombreFormula = 'Fórmula (ruido de ' + ANIO_RUIDO + ')', nombreSim = 'Simulación (' + n(d.replicas) + ' réplicas)';
    const leyenda = itemLeyenda(nombreFormula, '--serie-hoy') + itemLeyenda(nombreSim, '--serie-modelo');
    const tablaEE = tabla('Error estándar de β por franja', ['Franja', 'Cambio de salidas', 'Efecto esperado en pasajeros (β = ' + n(d.be.beta, 2) + ')', 'EE fórmula ' + ANIO_RUIDO, 'EE fórmula ' + ANIO_RUIDO_ALT, 'EE simulación', 'Intervalo del 95' + FINO + '% (±)'],
      d.filas.map(function (f) { return { celdas: [esc(f.nombre), esNum(f.p.cambio_pct_salidas) ? signoU(f.p.cambio_pct_salidas, 0, '%') : '', esNum(f.p.efecto_esperado_pct_pax_beta070) ? signoU(f.p.efecto_esperado_pct_pax_beta070, 0, '%') : '', n(f.p.ee_2025, 3), n(f.p.ee_2024, 3), n(f.e.ee_empirico_simulacion, 3), '±' + n(f.p.ic95_semiancho_2025, 2)], clase: f.k === CONJ ? 'tabla__fila-total' : '' }; }),
      { compacta: true, sinMarco: true });
    const tablaPot = tabla('Potencia por franja', ['Franja', 'Distinguir β = ' + n(d.be.beta, 2) + ' de ' + n(d.be.eq, 2) + ' (fórmula)', 'Lo mismo (simulación)', 'Detectar β = ' + n(d.be.eq, 2) + ' frente a ninguna pérdida (fórmula)', 'Días por brazo'],
      d.filas.map(function (f) { return { celdas: [esc(f.nombre), pctPot(f.p.potencia_070_vs_053_una_cola), pctPot(f.s.potencia_beta_mayor_053), pctPot(f.p.potencia_beta053_vs_0), esNum(f.p.n_dias_por_brazo) ? n(f.p.n_dias_por_brazo, 0) : ''], clase: f.k === CONJ ? 'tabla__fila-total' : '' }; }),
      { compacta: true, sinMarco: true });
    const pieEE = fuentes([['piloto_potencia', 'EE por franja (fórmula, ' + ANIO_RUIDO + ' y ' + ANIO_RUIDO_ALT + ')'], ['piloto_simulacion', 'EE empírico de la simulación']], 'error estándar') + ' ' + chip('piloto_potencia');
    const piePot = fuentes([['piloto_potencia', 'potencia (fórmula)'], ['piloto_simulacion', 'potencia (simulación)']], 'potencia') + ' ' + chip('piloto_simulacion');
    const conj = d.filas.filter(function (f) { return f.k === CONJ; })[0] || { p: {}, e: {}, s: {} };
    const intro = 'La β conjunta de recorte (mañana, tarde y domingo juntos) es la que decide: con el ruido de ' + ANIO_RUIDO + ' se estima con un error estándar de ' + n(conj.p.ee_2025, 3) + ' según la fórmula y ' + n(conj.e.ee_empirico_simulacion, 3) + ' en la simulación (intervalo de ±' + n(conj.p.ic95_semiancho_2025, 2) + '), suficiente para distinguir β = ' + n(d.be.beta, 2) + ' de ' + n(d.be.eq, 2) + ' con potencia de ' + pctPot(conj.p.potencia_070_vs_053_una_cola) + ' y ' + pctPot(conj.s.potencia_beta_mayor_053) + '. Cada franja por separado es menos precisa; los domingos solos necesitarían muchas más semanas. ' +
      fuentes([['piloto_potencia', 'EE, intervalo y potencia de la β conjunta (fórmula)'], ['piloto_simulacion', 'EE y potencia de la β conjunta (simulación)']], 'β conjunta');
    const cuerpo = '<div class="piloto__graficos">' +
      figura('pil-g-ee', 'Error estándar de β por franja', 'Cuanto más bajo, más precisa la β. Gris: la fórmula con el ruido de ' + ANIO_RUIDO + '; verde azulado: la simulación.', leyenda, tablaEE, pieEE, 'Barras del error estándar de β por franja y para la β conjunta, según la fórmula y según la simulación') +
      figura('pil-g-pot', 'Potencia para distinguir β = ' + n(d.be.beta, 2) + ' de ' + n(d.be.eq, 2), 'Probabilidad de rechazar la β de equilibrio si la verdadera es la de E7 (una cola). Gris: fórmula; verde azulado: simulación.', leyenda, tablaPot, piePot, 'Barras de la potencia por franja y para la β conjunta, según la fórmula y según la simulación') +
      '</div>' +
      '<p class="piloto__nota">La fórmula queda corta porque no cuenta los grados de libertad de los efectos fijos ni el ruido de la primera etapa: la simulación da errores un ' + pct(esNum(potC.factor_calibracion) ? (potC.factor_calibracion - 1) * 100 : null, 0) + ' mayores en la β conjunta, y con esa razón se calibró la tabla de semanas necesarias. ' +
      fuente('piloto_potencia', 'factor de calibración', { clave: 'potencia.factor_calibracion_ee_empirico_sobre_analitico', valor: potC.factor_calibracion }) + '</p>';
    return seccion('piloto-potencia', 'Cuánto se aprende: la precisión de β', intro, cuerpo);
  }

  // ---- 5. Simulación: ¿el estimador recupera β? ---------------------------------------------------------------------
  function seccionSimulacion() {
    const par = parametros(), be = betaYEquilibrio();
    const betas = betasSimuladas();
    if (!betas.length) return seccion('piloto-simulacion', 'La simulación recupera β', '', '<p class="texto-2">Sin datos de la simulación.</p>');
    const filas = betas.map(function (b) { return { b: b, vi: filaSim(CONJ, b, VI) || {}, mco: filaSim(CONJ, b, MCO) || {} }; });
    const fichas = '<div class="cifras">' + filas.map(function (f) {
      return ficha('Si la β verdadera fuera ' + n(f.b, 2), n(f.vi.beta_medio, 2), '± ' + n(f.vi.ee_empirico, 2), {
        variacion: icono('alerta') + 'Sin el sorteo (MCO) daría ' + n(f.mco.beta_medio, 2), variacionClase: 'cifra__variacion--mal',
        nota: 'Media de las ' + n(f.vi.replicas) + ' estimaciones de la β conjunta con el sorteo como instrumento; ± es el error estándar empírico. El intervalo cubre el valor verdadero el ' + pctPot(f.vi.cobertura_ic95) + ' de las veces.',
        fuente: fuente('piloto_simulacion', 'β conjunta recuperada con β verdadera ' + n(f.b, 2), { clave: f.vi.escenario ? claveSim(f.vi, 'beta_medio') + '; …ee_empirico; …cobertura_ic95' : undefined, valor: f.vi.beta_medio }) });
    }).join('') + '</div>';
    const nombreVerd = 'β verdadera', nombreVI = 'Con el sorteo (VI)', nombreMCO = 'Sin sorteo (MCO)';
    const leyenda = itemLeyenda(nombreVerd, '--serie-real') + itemLeyenda(nombreVI, '--serie-modelo') + itemLeyenda(nombreMCO, '--serie-hoy');
    const tablaSim = tabla('β conjunta recuperada en la simulación', ['β verdadera', nombreVI, 'EE empírico (VI)', 'Cobertura del intervalo (VI)', nombreMCO, 'EE empírico (MCO)'],
      filas.map(function (f) { return { celdas: [n(f.b, 2), n(f.vi.beta_medio, 3), n(f.vi.ee_empirico, 3), pctPot(f.vi.cobertura_ic95), n(f.mco.beta_medio, 3), n(f.mco.ee_empirico, 3)] }; }), { compacta: true, sinMarco: true });
    const f07 = filas.filter(function (f) { return Math.abs(f.b - be.beta) < 1e-9; })[0] || { vi: {}, mco: {} };
    const intro = 'Se generaron ' + n(par.replicas) + ' pilotos sintéticos de ' + n(par.semanas_piloto) + ' semanas por escenario: se sortean semanas limpias de ' + ANIO_RUIDO + ' con sus pasajeros y salidas reales, se sortea el calendario con la misma regla del piloto y en cada hora tratada se inyecta una β conocida. Luego se corre el mismo análisis que se correría con los datos reales. ' +
      'Con β = ' + n(be.beta, 2) + ' el estimador con el sorteo devuelve ' + n(f07.vi.beta_medio, 2) + '; la regresión sobre las salidas realizadas, sin sorteo, devuelve ' + n(f07.mco.beta_medio, 2) + ', porque mezcla el cambio sorteado con la variación natural de la oferta. Es el mismo sesgo que E7 encontró entre su MCO y su VI: si Sobusa hace el piloto pero analiza «comparando días con más y menos salidas», medirá mal. ' +
      fuentes([['piloto_parametros', 'réplicas y semanas'], ['piloto_simulacion', 'β media con y sin sorteo']], 'simulación');
    const cuerpo = fichas +
      figura('pil-g-sim', 'La β conjunta recuperada frente a la verdadera', 'Tinta: la β inyectada; verde azulado: la media con el sorteo como instrumento; gris: la media sin sorteo.', leyenda, tablaSim,
        fuente('piloto_simulacion', 'resumen de la simulación', { clave: 'simulacion.resumen[escenario=principal&franja=' + CONJ + ']' }) + ' ' + chip('piloto_simulacion'), 'Barras de la β conjunta recuperada por la simulación para cada β verdadera, con el sorteo y sin él');
    return seccion('piloto-simulacion', 'La simulación recupera β', intro, cuerpo);
  }

  // ---- 6. Riesgo y costo ---------------------------------------------------------------------------------------------
  function seccionRiesgo() {
    const tot = V('piloto_totales') || {}, be = betaYEquilibrio(), par = parametros();
    const rf = V('piloto_riesgo_por_franja') || [];
    const ruta = (franjas().R1 || {}).ruta || '';
    const fTot = function (titulo, clave, valor) { return fuente('piloto_totales', titulo, { clave: 'riesgo_costo.totales_piloto.' + clave, valor: valor }); };
    const fichas = '<div class="cifras" id="pil-riesgo-fichas">' +
      ficha('Pasajeros en riesgo en todo el piloto', n(tot.pax_riesgo_piloto_beta070), 'pasajeros', {
        variacion: icono('info') + 'El ' + pct(tot.pax_riesgo_piloto_pct_pax_anual_cra54, 2) + ' de los ' + n(tot.pax_anual_cra54_2025) + ' que ' + esc(ruta) + ' mueve en un año',
        nota: 'Con β = ' + n(be.beta, 2) + '. Tope si se perdieran en la misma proporción que las salidas: ' + n(tot.pax_riesgo_piloto_beta100) + '.',
        fuente: fTot('pasajeros en riesgo', 'pax_riesgo_piloto_beta070; …pax_riesgo_piloto_pct_pax_anual_cra54; …pax_anual_cra54_2025; …pax_riesgo_piloto_beta100', tot.pax_riesgo_piloto_beta070) }) +
      ficha('Pasajes en riesgo', n(tot.pasajes_riesgo_piloto_Mcop, 1), 'M COP', { nota: 'A la tarifa neta de ' + n(par.tarifa_neta) + ' COP por pasajero, en los días con recorte.', fuente: fTot('pasajes en riesgo', 'pasajes_riesgo_piloto_Mcop', tot.pasajes_riesgo_piloto_Mcop) }) +
      ficha('Ahorro de operación en los días con recorte', n(tot.ahorro_operativo_recortes_piloto_Mcop, 1), 'M COP', {
        variacion: icono('flecha-arriba') + 'Neto de los recortes: ' + signoU(tot.neto_recortes_piloto_Mcop, 1, 'M COP'), variacionClase: 'cifra__variacion--bien',
        nota: 'Conductores por hora y kilómetros que no se pagan.', fuente: fTot('ahorro de los recortes', 'ahorro_operativo_recortes_piloto_Mcop; …neto_recortes_piloto_Mcop', tot.ahorro_operativo_recortes_piloto_Mcop) }) +
      ficha('Costo de los refuerzos', n(tot.costo_extra_refuerzos_piloto_Mcop, 1), 'M COP', {
        variacion: icono('canje') + 'Podrían ganar ' + n(tot.pax_ganados_refuerzos_piloto_beta070) + ' pasajeros si la elasticidad es simétrica',
        nota: 'Es justo lo que el piloto va a medir: si los buses añadidos atraen a la gente que hoy ve el bus lleno.', fuente: fTot('costo y pasajeros de los refuerzos', 'costo_extra_refuerzos_piloto_Mcop; …pax_ganados_refuerzos_piloto_beta070', tot.costo_extra_refuerzos_piloto_Mcop) }) +
      ficha('Saldo del piloto', F.signo(tot.neto_total_piloto_Mcop_conservador, 1) + ' a ' + F.signo(tot.neto_total_piloto_Mcop_simetrico, 1), 'M COP', { frase: true,
        nota: 'De la cuenta conservadora (los buses de más no atraen a nadie) a la simétrica (atraen tantos como pierden los recortes).', fuente: fTot('saldo conservador y simétrico', 'neto_total_piloto_Mcop_conservador; …neto_total_piloto_Mcop_simetrico', tot.neto_total_piloto_Mcop_conservador) }) +
      '</div>';
    const filas = rf.map(function (r) {
      const rec = r.rol === ROL.recorte;
      const pax = rec ? n(r.pax_riesgo_dia_beta070) + ' en riesgo' : n(r.pax_ganados_dia_beta070) + ' podrían ganarse';
      const pasajes = rec ? signoU(-r.pasajes_riesgo_dia_Mcop, 2) : signoU(-r.pasajes_riesgo_dia_Mcop, 2) + ' si simétrica';
      const oper = rec ? signoU(r.ahorro_operativo_dia_Mcop, 2) + ' (ahorro)' : signoU(r.ahorro_operativo_dia_Mcop, 2) + ' (costo)';
      return { celdas: [
        esc(nombreCorto(r.franja)) + ' ' + fuente('piloto_riesgo_por_franja', 'riesgo y costo de ' + r.franja, { clave: 'riesgo_costo.por_franja[franja=' + r.franja + ']' }),
        n(r.salidas_movidas_dia), pax, pasajes, oper, signoU(r.neto_dia_Mcop, 2) + (rec ? '' : ' si simétrica'), n(r.dias_tratados_piloto),
        rec ? n(r.pax_riesgo_piloto_beta070) : n(r.pax_ganados_piloto_beta070) + ' ganados', signoU(r.neto_piloto_Mcop, 1) + (rec ? '' : ' si simétrica'),
      ], clase: '' };
    });
    filas.push({ celdas: ['Total de los recortes ' + fTot('totales de los recortes', 'pasajes_riesgo_piloto_Mcop; …ahorro_operativo_recortes_piloto_Mcop; …neto_recortes_piloto_Mcop; …pax_riesgo_piloto_beta070'), '', '', signoU(-tot.pasajes_riesgo_piloto_Mcop, 1), signoU(tot.ahorro_operativo_recortes_piloto_Mcop, 1), '', '', n(tot.pax_riesgo_piloto_beta070), signoU(tot.neto_recortes_piloto_Mcop, 1)], clase: 'tabla__fila-total' });
    filas.push({ celdas: ['Total de los refuerzos ' + fTot('totales de los refuerzos', 'costo_extra_refuerzos_piloto_Mcop; …pax_ganados_refuerzos_piloto_beta070; …neto_refuerzos_piloto_Mcop_si_simetrico'), '', '', '', signoU(-tot.costo_extra_refuerzos_piloto_Mcop, 1), '', '', n(tot.pax_ganados_refuerzos_piloto_beta070) + ' ganados', signoU(tot.neto_refuerzos_piloto_Mcop_si_simetrico, 1) + ' si simétrica'], clase: 'tabla__fila-total' });
    const tablaRiesgo = tabla('Por día tratado y en todo el piloto (β = ' + n(be.beta, 2) + ', precios con fuente)',
      ['Franja', 'Salidas movidas por día', 'Pasajeros por día tratado', 'Pasajes (M COP por día)', 'Operación (M COP por día)', 'Neto por día (M COP)', 'Días tratados', 'Pasajeros en el piloto', 'Neto del piloto (M COP)'],
      filas, { compacta: true, textoEn: [2, 3, 4, 5, 8] });
    const re = tot.reasignacion_R1_a_F1 || {};
    const R1 = franjas().R1 || {}, F1 = franjas().F1 || {};
    const notaRe = '<p class="piloto__nota">Un día RF (quita en ' + horasDe(R1) + ' y añade en ' + horasDe(F1) + ') es la propuesta a pequeña escala: ahorra ' + n(re.ahorro_R1_dia_Mcop, 2) + ' y gasta ' + n(re.costo_F1_dia_Mcop, 2) + ' M COP; pierde ' + n(re.pax_perdidos_R1_dia_beta070) + ' pasajeros y, con la misma β, gana ' + n(re.pax_ganados_F1_dia_beta070) + ': queda en ' + signoU(re.neto_dia_Mcop_si_beta_refuerzo_070, 2, 'M COP') + ' por día. ' +
      'La β de refuerzo que iguala pasajeros es ' + n(re.beta_refuerzo_que_iguala_pasajeros, 2) + ' y la que iguala dinero, ' + n(re.beta_refuerzo_que_iguala_dinero, 2) + '. Cada día tratado de recorte es casi neutro en caja: el piloto no es una apuesta, es la política del plan probada a pequeña escala. ' +
      fTot('reasignación de la mañana al pico', 'reasignacion_R1_a_F1') + '</p>';
    const intro = 'Para cada franja se aplica la fórmula del proyecto (pasajeros que se pierden donde hay menos salidas, con la β de E7) con los pasajeros y las salidas medias de ' + ANIO_RUIDO + ' por hora, la tarifa neta, el costo por bus-hora de conductor y el costo por kilómetro. Para los refuerzos se calcula el costo extra y los pasajeros que podrían ganarse si la elasticidad fuera simétrica.';
    return seccion('piloto-riesgo', 'Qué arriesga Sobusa y cuánto cuesta', intro, fichas + tablaRiesgo + notaRe);
  }

  // ---- 7. Reglas de parada -----------------------------------------------------------------------------------------
  function seccionReglas() {
    const r = V('piloto_reglas_de_parada') || {};
    const nombres = { '1_perdida_mayor_que_proporcional': 'Pérdida mayor que proporcional', '2_hacinamiento': 'Hacinamiento', '3_presupuesto_de_pasajeros': 'Presupuesto de pasajeros', '4_parada_temprana_por_decision': 'Parada temprana por decisión', '5_operacion': 'Días con fallas de operación' };
    const items = Object.keys(r).sort().map(function (k) {
      const v = r[k];
      const texto = typeof v === 'string' ? v : v && typeof v.regla === 'string' ? v.regla : '';
      if (!texto) return '';
      let extra = '';
      if (v && v.valores_2025) {
        const val = v.valores_2025;
        const filas = Object.keys(val).map(function (fk) {
          const x = val[fk] || {};
          const f = franjas()[fk] || {};
          const esRefuerzo = f.rol === ROL.refuerzo;
          return { celdas: [esc(nombreCorto(fk)), pct(x.pct_viajes_ocupacion_max_50_o_mas, 1), n(x.ocupacion_max_mediana), esRefuerzo ? 'no aplica: ahí se añade, no se quita' : pct(x.umbral_parada_pct, 1), n(x.viajes_con_contador)] };
        });
        extra = tabla('Ocupación en ' + ANIO_RUIDO + ' y umbral de parada por franja', ['Franja', 'Viajes con ocupación máxima alta en ' + ANIO_RUIDO, 'Ocupación máxima mediana', 'Umbral de parada', 'Viajes con contador'], filas, { compacta: true, textoEn: [3] });
      }
      if (v && esNum(v.pax_esperados_en_riesgo_piloto_beta070)) {
        extra = '<p class="piloto__nota">Pasajeros esperados en riesgo con la β de E7: ' + n(v.pax_esperados_en_riesgo_piloto_beta070) + '; tope proporcional: ' + n(v.tope_pax_piloto_beta100) + '.</p>';
      }
      return '<li><strong>' + esc(nombres[k] || k.replace(/^\d+_/, '').replace(/_/g, ' ')) + '.</strong> ' + esc(llano(texto)) + extra + '</li>';
    }).join('');
    return '<ol class="piloto__lista piloto__lista--numerada">' + items + '</ol>' +
      '<p class="piloto__nota">Las reglas se fijan antes de empezar y se miran al cierre de cada bloque con el mismo programa del análisis semanal. ' + fuente('piloto_reglas_de_parada', 'reglas de parada', { texto: 'Fuente' }) + ' ' + chip('piloto_reglas_de_parada') + '</p>';
  }

  // ---- 8. Operación: qué hace cada quien --------------------------------------------------------------------------
  function tablaPlanilla() {
    const pl = V('piloto_planilla') || [];
    if (!pl.length) return '<p class="texto-2">Sin planilla.</p>';
    const filas = pl.map(function (x) {
      return { celdas: [esc(x.ruta) + ', ' + esc(x.tipo_dia), n(x.hora) + FINO + 'h', esc(x.franja || '—'), n(x.salidas_habituales), n(x.intervalo_habitual_min, 1), n(x.planilla_tratada), n(x.intervalo_tratado_min, 1), esc(x.instruccion || '')] };
    });
    return tabla('La planilla del despachador', ['Ruta y tipo de día', 'Hora', 'Franja', 'Salidas habituales', 'Intervalo habitual (min)', 'Salidas en el día tratado', 'Intervalo tratado (min)', 'Instrucción'], filas, { compacta: true, textoEn: [1, 2, 7] }) +
      '<p class="piloto__nota">Las horas que no aparecen no cambian. ' + fuente('piloto_planilla', 'planilla operativa', { texto: 'Fuente' }) + '</p>';
  }
  function seccionOperacion() {
    const ej = (V('piloto_ejemplo_analisis') || []).filter(function (x) { return x.franja === CONJ; })[0] || null;
    const be = betaYEquilibrio();
    const fr = franjas(), R1 = fr.R1 || {}, F1 = fr.F1 || {};
    const fija = filaSim(CONJ, be.beta, VI, 'planilla') || {}, prin = filaSim(CONJ, be.beta, VI) || {};
    const fijaR2 = filaSim('R2', be.beta, VI, 'planilla') || {}, prinR2 = filaSim('R2', be.beta, VI) || {};
    const fijaMCO = filaSim(CONJ, be.beta, MCO, 'planilla') || {};
    const despachador = '<div class="tarjeta piloto__tarjeta"><h3>' + icono('bus') + ' El despachador</h3>' +
      '<p>Recibe el calendario y la planilla. Para cada tipo de día (N, R, F o RF en ' + esc(R1.ruta || '') + ' laboral; N o F en ' + esc((fr.F2 || {}).ruta || '') + '; N o R en domingo) la planilla dice cuántas salidas van en cada hora y el intervalo medio. Lo único que cambia respecto de hoy es el número de salidas de esas horas, con los intervalos parejos: nada de dos buses pegados y un hueco doble, que es la falla que E7 midió.</p>' +
      '<p>En las horas vecinas y en la de control, nada cambia. Los buses que no salen en ' + horasDe(R1) + ' entran en ' + horasDe(F1) + ' los días RF; los días R quedan en patio y los días F salen de reserva. Los festivos no entran al piloto.</p>' +
      '<p>Conviene que los días N también sigan la planilla: la β conjunta queda igual de precisa (error de ' + n(fija.ee_empirico, 3) + ' frente a ' + n(prin.ee_empirico, 3) + '), la tarde pierde las colas pesadas (de ' + n(prinR2.ee_empirico, 3) + ' a ' + n(fijaR2.ee_empirico, 3) + ') y hasta la regresión sin sorteo deja de estar sesgada (' + n(fijaMCO.beta_medio, 2) + '), porque ya no hay variación natural que la contamine. ' +
      fuente('piloto_simulacion', 'escenario con planilla fija los días de control', { clave: 'simulacion.resumen[escenario=planilla fija también los días de control&beta_verdadero=' + be.beta + ']' }) + '</p></div>';
    const registra = '<div class="tarjeta piloto__tarjeta"><h3>' + icono('tabla') + ' Qué se registra</h3>' +
      '<p>Nada nuevo: la tabla de viajes ya guarda la salida, la distancia recorrida y los pasajeros de cada viaje, y los contadores dan la ocupación máxima para la regla de hacinamiento. Solo con lo que se registra hoy se calcula, por franja, cuántos pasajeros cambiaron frente a cuántas salidas cambiaron entre los días tratados y los normales.</p>' +
      '<p>Hace falta solo una bitácora de una línea por día: qué planilla se aplicó (N, R, F, RF) y cualquier novedad (bloqueo, caída del sistema, bus varado), para marcar los días tratados en el archivo de análisis y aplicar la regla de los días con fallas.</p></div>';
    let ejemplo = '';
    if (ej) {
      const semi = esNum(ej.t_crit) && esNum(ej.ee_iv) ? ej.t_crit * ej.ee_iv : null;
      const inf = esNum(semi) ? ej.beta_iv - semi : null, sup = esNum(semi) ? ej.beta_iv + semi : null;
      const lectura = esNum(inf) && esNum(sup) ? (inf > be.eq ? 'recortar no paga: solo reasignar' : sup < be.eq ? 'los recortes moderados pagan' : 'el intervalo cubre la β de equilibrio: reasignar y extender') : '—';
      ejemplo = ficha('Ejemplo con un piloto sintético (β inyectada de ' + n(be.beta, 2) + ')', n(ej.beta_iv, 2), '± ' + n(ej.ee_iv, 2), { llana: true,
        variacion: icono('info') + 'Intervalo del 95' + FINO + '%: ' + n(inf, 2) + ' a ' + n(sup, 2) + ' → lectura automática: «' + lectura + '»',
        nota: 'β conjunta de recorte con ' + n(ej.n_dias_tratados) + ' días tratados y ' + n(ej.n_dias_control) + ' de control. Es un ejemplo con datos sintéticos, no un resultado.',
        fuente: fuente('piloto_ejemplo_analisis', 'ejemplo de análisis', { clave: '[franja=' + CONJ + '].beta_iv; …ee_iv; …t_crit; …n_dias_tratados; …n_dias_control', valor: ej.beta_iv }) });
    }
    const analiza = '<div class="tarjeta piloto__tarjeta"><h3>' + icono('grafico') + ' Cómo se analiza cada semana</h3>' +
      '<p>Un archivo con una fila por ruta, día y hora (salidas y pasajeros de los viajes que corrieron, y si el día fue de recorte o de refuerzo) y el programa de análisis de P2 (<code>run.py --analizar</code>), el mismo que corrió la simulación. Imprime la tabla por franja: días tratados y de control, primera etapa, β con su error estándar e intervalo, la β conjunta de recorte, los efectos en las horas vecinas, en la hora de control y en las otras rutas, y una lectura en palabras frente a las dos β de la decisión.</p>' +
      ejemplo + '</div>';
    const intro = 'El piloto no necesita nada que Sobusa no tenga: los registros de viajes y pasajeros de siempre, una bitácora de una línea por día y una persona que corra el análisis cada semana. Antes de empezar, la gerencia decide la fecha de arranque y si los días normales también siguen la planilla (recomendado), y confirma el supuesto de diseño: que Sobusa no publica horarios y por eso el pasajero no distingue el recorte de la variación habitual.';
    return seccion('piloto-operacion', 'Cómo se opera', intro, '<div class="piloto__tarjetas">' + despachador + registra + analiza + '</div>' +
      desplegable('pil-planilla', 'Ver la planilla del despachador', tablaPlanilla()));
  }

  // ---- 9. Ver cómo se calculó -----------------------------------------------------------------------------------------
  function comoSeCalculo() {
    const par = parametros(), be = betaYEquilibrio(), potC = C('piloto_potencia') || {};
    const fPar = function (titulo, clave, valor) { return fuente('piloto_parametros', titulo, { clave: 'parametros.' + clave, valor: valor }); };
    const paramFichas = '<div class="piloto__cifras-tarjeta">' +
      ficha('Réplicas por escenario', n(par.replicas), '', { llana: true, fuente: fPar('réplicas', 'replicas', par.replicas) }) +
      ficha('Semilla del sorteo', n(par.semilla), '', { llana: true, fuente: fPar('semilla', 'semilla', par.semilla) }) +
      ficha('Tarifa neta', n(par.tarifa_neta), 'COP', { llana: true, fuente: fPar('tarifa neta', 'tarifa_neta', par.tarifa_neta) }) +
      ficha('Conductor por bus-hora', n(par.costo_bus_hora_conductor), 'COP', { llana: true, fuente: fPar('costo por bus-hora', 'costo_bus_hora_conductor', par.costo_bus_hora_conductor) }) +
      ficha('Costo evitable por km', n(par.costo_km_evitable), 'COP', { llana: true, fuente: fPar('costo por km', 'costo_km_evitable', par.costo_km_evitable) }) +
      ficha('Viaje que cuenta', '≥ ' + n(par.dist_operado_km), 'km', { llana: true, nota: 'Todos los viajes que corrieron, sin importar la marca de cancelado.', fuente: fPar('distancia mínima de un viaje', 'dist_operado_km', par.dist_operado_km) }) +
      '</div>';
    const cats = categoriasPotencia();
    const filasSim07 = cats.map(function (k) {
      const vi = filaSim(k, be.beta, VI) || {}, mco = filaSim(k, be.beta, MCO) || {};
      return { celdas: [esc(nombreCorto(k)), n(vi.beta_medio, 3), n(vi.ee_empirico, 3), n(vi.ee_estimado_medio, 3), pctPot(vi.cobertura_ic95), pctPot(vi.potencia_beta_mayor_053), n(mco.beta_medio, 3)], clase: k === CONJ ? 'tabla__fila-total' : '' };
    });
    const tablaSim07 = tabla('Simulación por franja con β = ' + n(be.beta, 2) + ' (escenario principal)', ['Franja', 'β media (VI)', 'EE empírico', 'EE que estima el análisis', 'Cobertura del intervalo', 'Potencia frente a ' + n(be.eq, 2), 'β media sin sorteo (MCO)'], filasSim07, { compacta: true });
    const derr = filaSim(CONJ, be.beta, VI, 'derrame') || {};
    const cuerpo = '<p><strong>El estimador.</strong> Para cada franja, con las horas tratadas:</p>' +
      '<p class="piloto__formula">log(pasajeros) = β · log(salidas) + efecto de día de la semana × hora + efecto de semana + error</p>' +
      '<p>con errores agrupados por día (corrección de muestra pequeña y valores críticos de la t con un grado de libertad menos que días). La asignación sorteada (tratado o no, por día) instrumenta log(salidas): β = efecto del sorteo sobre los pasajeros ÷ efecto del sorteo sobre las salidas. Así el estimador no se contamina con la variación natural de la oferta ni con que el despachador cumpla la planilla a medias (si cumple a medias, la primera etapa lo mide). La β conjunta de recorte apila las tres franjas de recorte. Las vecinas, el control, la otra ruta y el total del día se reportan como el efecto del sorteo sobre los pasajeros, que debe ser cero salvo traslado.</p>' +
      '<p><strong>El error estándar (fórmula).</strong> Con la desviación típica del residuo diario de log(pasajeros) σ (sin los efectos fijos, en los días limpios de ' + ANIO_RUIDO + '), el cambio de log(salidas) Δ y n días por brazo:</p>' +
      '<p class="piloto__formula">EE(β) ≈ σ · √(1/n_tratados + 1/n_control) ÷ |Δ|; la β conjunta combina 1/EE² = Σ 1/EE_franja²</p>' +
      '<p>La simulación da errores un ' + pct(esNum(potC.factor_calibracion) ? (potC.factor_calibracion - 1) * 100 : null, 0) + ' mayores en la β conjunta; la tabla de semanas necesarias se calibró con esa razón. ' + fuente('piloto_potencia', 'factor de calibración', { clave: 'potencia.factor_calibracion_ee_empirico_sobre_analitico', valor: potC.factor_calibracion }) + '</p>' +
      '<p><strong>La simulación.</strong> ' + n(par.replicas) + ' pilotos sintéticos por escenario: se sortean con reemplazo ' + n(par.semanas_piloto) + ' de las semanas limpias de ' + ANIO_RUIDO + ' (todas las rutas, horas y días, con sus pasajeros y salidas reales), se sortea el calendario con la regla del piloto y en cada hora tratada se inyecta el efecto: salidas′ = salidas + k y pasajeros′ = pasajeros × (salidas′ ÷ salidas)^β. Los días de control conservan su oferta natural. Luego se corre el mismo análisis. Con un derrame del ' + pct(esNum(par.derrame_simulado) ? par.derrame_simulado * 100 : null, 0) + ' de los pasajeros perdidos a la hora siguiente, la β conjunta medida baja a ' + n(derr.beta_medio, 2) + ' (es la elasticidad neta del bloque, la que importa para un plan por franjas). ' +
      fuentes([['piloto_parametros', 'réplicas, semanas y derrame simulado'], ['piloto_simulacion', 'β conjunta en el escenario con derrame']], 'simulación') + '</p>' +
      tablaSim07 +
      '<p><strong>El riesgo y el costo.</strong> Pasajeros en riesgo = pasajeros de la hora × (1 − (salidas tratadas ÷ salidas habituales)^β) en las horas con menos salidas, con los pasajeros y las salidas medias de ' + ANIO_RUIDO + '; en pasajes, a la tarifa neta; el ahorro de operación, con el costo por bus-hora de conductor (pago por hora) y el costo evitable por kilómetro, según el ciclo de cada ruta. Los parámetros:</p>' + paramFichas +
      '<p><strong>Quién lo verificó.</strong> ' + chip('piloto_potencia') + ' <span class="texto-2">' + esc(potC.revision || '') + '</span></p>';
    return desplegable('pil-como', 'Ver cómo se calculó', cuerpo);
  }

  // ---- 10. Límites ----------------------------------------------------------------------------------------------------
  function seccionLimites() {
    const pot = V('piloto_potencia') || {}, par = parametros(), be = betaYEquilibrio();
    const conj = pot[CONJ] || {};
    const derr = filaSim(CONJ, be.beta, VI, 'derrame') || {};
    const items = [
      '<li><strong>β a corto plazo.</strong> El piloto alterna días, así que mide la respuesta inmediata; a largo plazo las elasticidades suelen ser mayores, porque los pasajeros cambian de modo con el tiempo. Un recorte permanente perdería al menos lo que mide el piloto, probablemente más. El arrastre (días normales tras un día tratado) se comprueba, pero un efecto lento no se ve en ' + n(par.semanas_piloto) + ' semanas.</li>',
      '<li><strong>Ruido del año del piloto.</strong> La potencia se calculó con el ruido de ' + ANIO_RUIDO + '; ' + ANIO_RUIDO_ALT + ' fue más ruidoso según la franja. Con el ruido de ' + ANIO_RUIDO_ALT + ' el error estándar de la β conjunta sube de ' + n(conj.ee_2025, 3) + ' a ' + n(conj.ee_2024, 3) + ': los intervalos se ensanchan y harían falta más semanas. El aumento de oferta del año también cambia el nivel de partida: conviene recalcular las salidas habituales con las semanas previas al arranque. ' +
        fuente('piloto_potencia', 'EE de la β conjunta con el ruido de ' + ANIO_RUIDO + ' y de ' + ANIO_RUIDO_ALT, { clave: 'potencia.diseno_propuesto["' + CONJ + '"].ee_2025; potencia.diseno_propuesto["' + CONJ + '"].ee_2024', valor: conj.ee_2024 }) + '</li>',
      '<li><strong>Simulación con datos reales y efecto inyectado.</strong> El bootstrap por semanas conserva el ruido real, pero el efecto se inyecta con una fórmula y sin diferencias entre días; la simulación no puede probar supuestos que no contiene (por ejemplo, que un recorte avisado cambie el comportamiento más que uno no avisado).</li>',
      '<li><strong>Traslado entre horas.</strong> Con recortes por bloques de varias horas, el traslado a la hora siguiente queda dentro del bloque y la β medida es la neta del bloque (con un derrame simulado del ' + pct(esNum(par.derrame_simulado) ? par.derrame_simulado * 100 : null, 0) + ', ' + n(derr.beta_medio, 2) + ' en vez de ' + n(be.beta, 2) + '); la vecina solo recibe lo de la última hora y no se detecta. Es lo que un plan por franjas necesita, pero no es la β «pura» de una hora. ' +
        fuentes([['piloto_parametros', 'derrame simulado'], ['piloto_simulacion', 'β conjunta con derrame']], 'traslado') + '</li>',
      '<li><strong>Captación entre rutas.</strong> Se mide si las otras rutas de Sobusa ganan pasajeros a la misma hora cuando ' + esc((franjas().R1 || {}).ruta || '') + ' recorta, pero no se puede ver lo que se va a otras empresas o al transporte informal; esa pérdida es la que β recoge.</li>',
      '<li><strong>Cumplimiento.</strong> El despacho es en tiempo real y sin horario publicado; si la planilla se cumple a medias, el estimador sigue siendo insesgado (la primera etapa lo mide) pero pierde potencia. Los días con incidencias se excluyen por regla, no a criterio.</li>',
      '<li><strong>Costos.</strong> Los pesos usan los costos con fuente y el pago por hora al conductor; con pago por producido el ahorro de conductor desaparece y los recortes no pagan ni en el piloto.</li>',
      '<li><strong>Supuesto de diseño.</strong> Que Sobusa no publica horarios, y que por eso el pasajero no distingue el recorte de la variación habitual, hay que confirmarlo con la empresa antes de arrancar; anunciar los días tratados contaminaría los días normales.</li>',
    ];
    return seccion('piloto-limites', 'Límites', 'Lo que el piloto no puede medir o depende de supuestos.', '<ul class="piloto__lista">' + items.join('') + '</ul>');
  }

  // ---- 11. Pie: enlace discreto al README de P2 ---------------------------------------------------------------------------
  function pie() {
    return '<p class="piloto__pie">Diseño completo del piloto, archivos y cómo reproducirlo: <a href="experimentos/P2_piloto_beta/README.md" target="_blank" rel="noopener">README de P2</a>' + icono('externo') + ' <span>·</span> ' + chip('piloto_potencia') + '</p>';
  }

  // ---- Gráficos ----------------------------------------------------------------------------------------------------------
  // Barras por categoría. categorias: [{ corto (etiqueta del eje, con saltos de línea), largo (título del tooltip) }].
  function opcionBarras(categorias, series, yNombre, fmtTooltip, fmtEje, max) {
    return {
      legend: { show: false, data: series.map(function (s) { return s.name; }) },
      tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' },
        formatter: function (params) {
          const lista_ = Array.isArray(params) ? params : [params];
          if (!lista_.length) return '';
          const i = lista_[0].dataIndex;
          return '<strong>' + esc((categorias[i] || {}).largo || lista_[0].name) + '</strong><br>' + lista_.map(function (p) {
            return p.marker + esc(p.seriesName) + ': <span class="num">' + esc(esNum(p.value) ? fmtTooltip(p.value) : '—') + '</span>';
          }).join('<br>');
        } },
      grid: { left: 8, right: 12, top: 36, bottom: 4, containLabel: true },
      xAxis: { type: 'category', data: categorias.map(function (c) { return c.corto; }), axisLabel: { interval: 0, width: 54, overflow: 'break', lineHeight: 13, fontSize: 11 } },
      yAxis: { type: 'value', name: yNombre, nameLocation: 'end', nameGap: 14, nameTextStyle: { align: 'left' }, max: max, axisLabel: { formatter: fmtEje } },
      series: series,
    };
  }
  function barra(nombre, datos, color) {
    return { name: nombre, type: 'bar', data: datos.map(function (v) { return esNum(v) ? v : null; }), barMaxWidth: 24, itemStyle: { color: color, borderRadius: 4 } };
  }
  function pintarGraficos() {
    if (!global.echarts || !global.TEMA_ECHARTS) {
      // Sin ECharts, cada figura muestra su tabla gemela.
      cont.querySelectorAll('.grafico [data-ver-tabla]').forEach(function (b) { const t = b.closest('.grafico').querySelector('.grafico__tabla'); if (t && t.hidden) b.click(); });
      return;
    }
    destruirGraficos();
    const t = global.TEMA_ECHARTS.tokens();
    const d = datosPotencia();
    const cats = d.filas.map(function (f) { return { corto: etiquetaEje(f.k), largo: f.nombre }; });
    const nombreFormula = 'Fórmula (ruido de ' + ANIO_RUIDO + ')', nombreSim = 'Simulación (' + n(d.replicas) + ' réplicas)';
    const elEE = cont.querySelector('#pil-g-ee-lienzo');
    if (elEE) {
      const g = global.TEMA_ECHARTS.init(global.echarts, elEE);
      g.setOption(opcionBarras(cats, [
        barra(nombreFormula, d.filas.map(function (f) { return f.p.ee_2025; }), t.serieHoy),
        barra(nombreSim, d.filas.map(function (f) { return f.e.ee_empirico_simulacion; }), t.serieModelo),
      ], 'EE de β', function (v) { return n(v, 3); }, function (v) { return n(v, 2); }));
      graficos.ee = g;
      ligarLeyenda(cont.querySelector('#pil-g-ee .leyenda'), function () { return graficos.ee; });
    }
    const elPot = cont.querySelector('#pil-g-pot-lienzo');
    if (elPot) {
      const g = global.TEMA_ECHARTS.init(global.echarts, elPot);
      g.setOption(opcionBarras(cats, [
        barra(nombreFormula, d.filas.map(function (f) { return esNum(f.p.potencia_070_vs_053_una_cola) ? f.p.potencia_070_vs_053_una_cola * 100 : null; }), t.serieHoy),
        barra(nombreSim, d.filas.map(function (f) { return esNum(f.s.potencia_beta_mayor_053) ? f.s.potencia_beta_mayor_053 * 100 : null; }), t.serieModelo),
      ], 'potencia (%)', function (v) { return pct(v, 0); }, function (v) { return n(v, 0); }, 100));
      graficos.pot = g;
      ligarLeyenda(cont.querySelector('#pil-g-pot .leyenda'), function () { return graficos.pot; });
    }
    const elSim = cont.querySelector('#pil-g-sim-lienzo');
    if (elSim) {
      const betas = betasSimuladas();
      const filas = betas.map(function (b) { return { b: b, vi: filaSim(CONJ, b, VI) || {}, mco: filaSim(CONJ, b, MCO) || {} }; });
      const g = global.TEMA_ECHARTS.init(global.echarts, elSim);
      g.setOption(opcionBarras(filas.map(function (f) { return { corto: 'β = ' + n(f.b, 2), largo: 'β verdadera = ' + n(f.b, 2) }; }), [
        barra('β verdadera', filas.map(function (f) { return f.b; }), t.serieReal),
        barra('Con el sorteo (VI)', filas.map(function (f) { return f.vi.beta_medio; }), t.serieModelo),
        barra('Sin sorteo (MCO)', filas.map(function (f) { return f.mco.beta_medio; }), t.serieHoy),
      ], 'β', function (v) { return n(v, 3); }, function (v) { return n(v, 1); }));
      graficos.sim = g;
      ligarLeyenda(cont.querySelector('#pil-g-sim .leyenda'), function () { return graficos.sim; });
    }
  }
  function destruirGraficos() {
    Object.keys(graficos).forEach(function (k) { if (graficos[k] && graficos[k].dispose) graficos[k].dispose(); delete graficos[k]; });
  }

  // ---- Contrato de la pantalla ---------------------------------------------------------------------------------------------
  function render(contenedor) {
    salir();
    cont = contenedor;
    nPop = 0; faltantes = []; graficos = {};
    estilos();
    if (!app().cifra(ID, 'piloto_parametros')) {
      cont.innerHTML = aviso('atencion', 'Sin datos del piloto', '<p>Falta app/datos_app.js o no trae las cifras del piloto (las genera app/generar_datos_app.py).</p>');
      return;
    }
    const partes = [];
    partes.push(resumen());
    partes.push(porQue());
    partes.push(queDecide());
    partes.push(seccion('piloto-franjas', 'Qué se cambia en cada franja', 'Cada franja cambia unas pocas salidas por hora en los días tratados y vuelve a lo de siempre en los de control; los cambios son los que haría el plan, lejos de recortes fuera del soporte de los datos.', tablaFranjas()));
    partes.push(seccion('piloto-calendario', 'Cuándo', 'Las semanas del piloto, con la revisión intermedia y los festivos que quedan fuera.', calendario()));
    partes.push(seccionPotencia());
    partes.push(seccionSimulacion());
    partes.push(seccionRiesgo());
    partes.push(seccion('piloto-reglas', 'Cuándo se para', 'Reglas fijadas antes de empezar, para no poner en riesgo más pasajeros de los previstos.', seccionReglas()));
    partes.push(seccionOperacion());
    partes.push(comoSeCalculo());
    partes.push(seccionLimites());
    partes.push(pie());
    const cab = faltantes.length ? aviso('atencion', 'Faltan datos en app/datos_app.js', '<p>Esta pantalla no encontró ' + n(faltantes.length) + ' ids: <code>' + faltantes.map(esc).join('</code>, <code>') + '</code>. Donde faltan se muestra «—».</p>') : '';
    cont.innerHTML = cab + partes.join('');
    COMPONENTES.fuentes(cont);
    COMPONENTES.cifras(cont);
    COMPONENTES.tablaGrafico(cont);
    pintarGraficos();
    if ('ResizeObserver' in global) {
      const vigilante = new ResizeObserver(function () { Object.keys(graficos).forEach(function (k) { if (graficos[k] && graficos[k].resize) graficos[k].resize(); }); });
      cont.querySelectorAll('.grafico__lienzo').forEach(function (el) { vigilante.observe(el); });
      limpiezas.push(function () { vigilante.disconnect(); });
    }
  }
  function salir() {
    destruirGraficos();
    limpiezas.forEach(function (f) { try { f(); } catch (e) { /* nada */ } });
    limpiezas = [];
  }

  const definicion = {
    id: ID,
    pregunta: '¿Cómo lo comprobamos?',
    subtitulo: function () {
      const par = parametros();
      const ruta = (franjas().R1 || {}).ruta || '';
      return esNum(par.semanas_piloto)
        ? 'Un piloto de ' + n(par.semanas_piloto) + ' semanas en ' + ruta + ': quitar salidas en los valles y añadirlas en los picos, por sorteo, para medir cuántos pasajeros se pierden y cuántos se ganan.'
        : 'Un piloto para medir en la calle cuántos pasajeros se pierden y cuántos se ganan al mover salidas.';
    },
    icono: 'piloto',
    interruptor: [],
    modulo: null,
    render: render,
    actualizar: function () {},
    salir: salir,
  };
  // app.html define registrarPantalla antes de cargar las pantallas; si no existiera, se deja en la misma cola que lee app.js.
  if (typeof global.registrarPantalla === 'function') global.registrarPantalla(definicion);
  else (global.__pantallasRegistradas = global.__pantallasRegistradas || []).push(definicion);
})(window);
