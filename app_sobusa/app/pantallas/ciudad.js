// Sobusa Despacho · pantallas/ciudad.js — Ciudad · ¿Cómo se ve en la calle?
// Resumen propio encima de la vista 3D embebida (vista_3d.html?embebido=1#dia=…&hora=…&ver=…&pausa=1), según el
// wireframe de app/DISEÑO.md §7: fichas del 3 de junio real frente a plan con el interruptor Hoy / Con el modelo /
// Los dos (en esta pantalla el tercer botón es «Los dos» y cambia el modo «ver» de la vista 3D), el aviso crítico de
// CRA 54 de 17 a 19 h, «Todo 2025 con el mismo modelo» (fichas, tabla por tipo de día y el aviso de canje conservadora
// frente a simétrica, con la comparación con D5), «Ver cómo se calculó» y los límites. Ninguna cifra está escrita aquí:
// todas salen de window.DATOS_APP (app/datos_app.js) y cada una lleva su botón «fuente» (clave exacta de «origen»).
//
// Ids que lee (pantalla ciudad): ciudad_3jun_real, ciudad_3jun_plan, ciudad_3jun_balance, ciudad_3jun_pronostico,
// ciudad_3jun_por_hora, ciudad_3jun_cra54_17_19, ciudad_plan_meta, ciudad_2025_real, ciudad_2025_plan,
// ciudad_2025_saldo, ciudad_2025_por_tipo_dia, ciudad_2025_por_hora, ciudad_dias_saldo_negativo, ciudad_version_calles;
// y de Inicio, si existen, inicio_saldo_conservador, inicio_saldo_simetrico e inicio_pax_riesgo_plan (contabilidad de D5).
// ciudad_cobertura_trayectorias y ciudad_alertas_3jun_0730 no existen en los archivos de resultados: no se muestran.
//
// El módulo (iframe) lo crea y lo conserva app.js a partir de «modulo» (completo: false → debajo del resumen, con la
// altura de la ventana menos la cabecera compacta). El modo de la vista sigue al interruptor: en el hash al crearse
// (ver = real | plan | ambos según el escenario) y después con {tipo:'ver'}; si el usuario cambia el modo dentro de la
// vista, esta pantalla lee su {tipo:'estado', ver} y mueve el interruptor. El día y la hora llegan de Despacho por
// app.js ({tipo:'dia'}), como hoy.
(function (global) {
  'use strict';

  const ID = 'ciudad';
  const PREFIJO = 'fc-';
  const ANIO = '2025';
  const F = global.COMPONENTES.formato;
  const icono = function (nombre, clase) { return global.ICONOS.svg(nombre, clase); };
  const FINO = ' ';
  const TIPOS = ['Laboral', 'Sábado', 'Domingo/festivo'];
  const TIPO_TEXTO = { 'Laboral': 'Laboral', 'Sábado': 'Sábado', 'Domingo/festivo': 'Domingo o festivo' };
  const VER_DE = { hoy: 'real', modelo: 'plan', oraculo: 'ambos' };
  const ESC_DE = { real: 'hoy', plan: 'modelo', ambos: 'oraculo' };

  let D = null, cont = null, est = null, nPop = 0, faltantes = [], fichasDia = [], fichasAnio = [], limpiezas = [];

  // ---- Utilidades ----------------------------------------------------------------------------------------------
  function app() { return global.app; }
  function num(v) { return typeof v === 'number' && isFinite(v); }
  function n(v, d) { return num(v) ? F.numero(v, d || 0) : '—'; }
  function pct(v, d) { return num(v) ? F.numero(v, d === undefined ? 1 : d) + FINO + '%' : '—'; }
  function esc(s) { return String(s === undefined || s === null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'); }
  function hhmm(h) { return String(h || '').slice(0, 5); }
  function reducido() { return global.matchMedia && global.matchMedia('(prefers-reduced-motion: reduce)').matches; }

  // ---- Datos ---------------------------------------------------------------------------------------------------
  function entrada(id) {
    const p = D && D.pantallas;
    if (!p) return null;
    if (p[ID] && p[ID][id]) return p[ID][id];
    for (const k in p) if (p[k] && p[k][id]) return p[k][id];
    return null;
  }
  function C(id, opcional) {
    const e = entrada(id);
    if (!e) { if (!opcional && faltantes.indexOf(id) < 0) faltantes.push(id); return null; }
    return app() && app().normalizarCifra ? app().normalizarCifra(e) : e;
  }
  function V(id, ruta, opcional) {
    const c = C(id, opcional);
    if (!c) return null;
    let v = c.valor;
    if (ruta) for (let i = 0; i < ruta.length; i++) { if (v === null || v === undefined) return null; v = v[ruta[i]]; }
    return v === undefined ? null : v;
  }
  function X(id, campo) { const c = C(id); return c && c[campo] !== undefined ? c[campo] : null; }

  // ---- Fuentes -------------------------------------------------------------------------------------------------
  function describirRef(r) {
    if (typeof r === 'string') return { clave: r };
    if (!r || typeof r !== 'object') return null;
    if (r.t === 'f' && r.v) {
      const partes = Object.keys(r.v).map(function (k) { return k + ' = ' + (r.v[k].c || r.v[k].a || '?'); });
      const archivos = Object.keys(r.v).map(function (k) { return r.v[k].a; }).filter(function (a, i, l) { return a && l.indexOf(a) === i; });
      return { archivo: archivos.join(' y '), clave: r.expr + ' (' + partes.join('; ') + ')' };
    }
    if (r.t === 'calles') return { archivo: r.a, clave: (r.medida || '') + (r.tipo ? ' (' + r.tipo + ')' : '') + ' en resumen.dia de cada archivo AAAA-MM-DD.js' };
    return { archivo: r.a, clave: (r.c || '') + (r.op ? ' → ' + r.op : '') + (r.x !== undefined && r.x !== 1 ? ' (× ' + r.x + ')' : '') };
  }
  function refDe(c, ruta) {
    if (!c || !Array.isArray(c.origen) || !ruta || !ruta.length) return null;
    const buscada = ['valor'].concat(ruta.map(String));
    let mejor = null, largo = 0;
    c.origen.forEach(function (o) {
      if (!Array.isArray(o) || !Array.isArray(o[0])) return;
      const p = o[0].map(String);
      if (p.length <= buscada.length && p.length > largo && p.every(function (x, i) { return x === buscada[i]; })) { mejor = o[1]; largo = p.length; }
    });
    return mejor === null ? null : describirRef(mejor);
  }
  function popCifra(id, titulo, ruta, extra) {
    const c = C(id, !!(extra && extra.opcional));
    if (!c) return null;
    nPop += 1;
    const idPop = PREFIJO + nPop;
    const ajuste = { que_mide: esc(c.que_es || '') };
    if (ruta && ruta.length) {
      const r = refDe(c, ruta);
      if (r) { if (r.archivo) ajuste.archivo = r.archivo; ajuste.clave = r.clave; } else ajuste.clave = (c.clave || '—') + ' → ' + ruta.join(' → ');
      const v = V(id, ruta, true);
      ajuste.valor = typeof v === 'number' || typeof v === 'string' ? v : undefined;
    }
    Object.assign(ajuste, extra || {});   // lo que pide la pantalla (clave, nota, valor) manda sobre lo deducido de «origen»
    delete ajuste.opcional;
    app().popoverFuente(idPop, Object.assign({}, c, ajuste), titulo || c.que_es || id);
    return idPop;
  }
  function fuente(id, titulo, ruta, texto, extra) { const p = popCifra(id, titulo, ruta, extra); return p ? app().botonFuente(p, texto) : ''; }
  function fuentes(pares, titulo) {
    const validos = pares.filter(function (p) { return !!C(p[0], true); });
    if (!validos.length) return '';
    nPop += 1;
    const idPop = PREFIJO + nPop;
    app().popoverFuentes(idPop, validos.map(function (p) {
      const c = C(p[0]);
      const r = p[2] ? refDe(c, p[2]) : null;
      return [r ? Object.assign({}, c, r, { valor: undefined }) : c, p[1]];
    }), titulo);
    return app().botonFuente(idPop, validos.length > 1 ? 'Fuentes (' + n(validos.length) + ')' : 'Fuente');
  }
  function chip(id) { const c = C(id, true); return c ? app().chipVerificado(c.verificado) : ''; }

  // ---- Piezas de HTML -------------------------------------------------------------------------------------------
  function seccion(id, titulo, intro, cuerpo, oculto) {
    return '<section class="seccion" id="' + id + '" aria-labelledby="' + id + '-t"><div class="seccion__cab"><h2 class="seccion__titulo' + (oculto ? ' oculto' : '') + '" id="' + id + '-t">' + titulo + '</h2></div>' +
      (intro ? '<p class="seccion__intro">' + intro + '</p>' : '') + '<div class="seccion__cuerpo">' + cuerpo + '</div></section>';
  }
  function aviso(tipo, titulo, cuerpo) {
    const ic = tipo === 'canje' ? 'canje' : tipo === 'bien' ? 'bien' : tipo === 'nota' ? 'info' : 'alerta';
    return '<div class="aviso' + (tipo && tipo !== 'nota' ? ' aviso--' + tipo : '') + '"' + (tipo === 'critico' ? ' role="note"' : '') + '>' + icono(ic) + '<div class="aviso__cuerpo"><h3 class="aviso__titulo">' + titulo + '</h3>' + cuerpo + '</div></div>';
  }
  function tabla(caption, cabeceras, filas, opciones) {
    opciones = opciones || {};
    const esTexto = function (i) { return i === 0 || (opciones.textoEn && opciones.textoEn.indexOf(i) >= 0); };
    let h = '<div class="tabla-marco"><table class="tabla tabla--compacta">';
    if (caption) h += '<caption>' + caption + '</caption>';
    h += '<thead><tr>' + cabeceras.map(function (c, i) { return '<th scope="col"' + (esTexto(i) ? '' : ' class="num"') + '>' + c + '</th>'; }).join('') + '</tr></thead><tbody>';
    filas.forEach(function (fila) {
      h += '<tr' + (fila.clase ? ' class="' + fila.clase + '"' : '') + '>' + fila.celdas.map(function (c, i) {
        return i === 0 ? '<th scope="row">' + c + '</th>' : '<td' + (esTexto(i) ? '' : ' class="num"') + '>' + c + '</td>';
      }).join('') + '</tr>';
    });
    return h + '</tbody></table></div>';
  }
  function dl(pares, apilado) {
    return '<dl class="resumen-datos' + (apilado ? ' resumen-datos--apilado' : '') + '">' + pares.map(function (p) { return '<dt>' + p[0] + '</dt><dd>' + p[1] + '</dd>'; }).join('') + '</dl>';
  }
  function desplegable(id, titulo, cuerpo, llano) {
    return '<details class="desplegable' + (llano ? ' desplegable--llano' : '') + '" id="' + id + '"><summary class="desplegable__resumen">' + icono('chevron-derecha', 'icono desplegable__chevron') + titulo + '</summary><div class="desplegable__cuerpo">' + cuerpo + '</div></details>';
  }
  function cifraLlana(etiqueta, valorHtml, unidad, variacion, nota, botonFuente, claseValor) {
    return '<article class="cifra cifra--llana"><header class="cifra__cab"><h3 class="cifra__etiqueta">' + etiqueta + '</h3>' + (botonFuente || '') + '</header>' +
      '<p class="cifra__valor' + (claseValor ? ' ' + claseValor : '') + '"><span class="num">' + valorHtml + '</span>' + (unidad ? '<span class="cifra__unidad">' + esc(unidad) + '</span>' : '') + '</p>' +
      (variacion ? '<p class="cifra__variacion' + (variacion.clase ? ' ' + variacion.clase : '') + '">' + variacion.html + '</p>' : '') +
      (nota ? '<p class="cifra__nota">' + nota + '</p>' : '') + '</article>';
  }
  function flecha(a, b, d) { return '<span class="num">' + n(a, d) + '</span> <span class="texto-3">→</span> <span class="num">' + n(b, d) + '</span>'; }

  // ---- Estilos propios (solo tokens) ------------------------------------------------------------------------------
  function estilos() {
    if (document.getElementById('estilos-ciudad')) return;
    const st = document.createElement('style');
    st.id = 'estilos-ciudad';
    st.textContent = [
      // La vista 3D, debajo del resumen, con la altura de la ventana menos la cabecera compacta (64 px): «Ir a la vista
      // 3D» la deja justo debajo y ocupa todo lo que queda. En el teléfono, menos la barra inferior.
      '.contenido--con-modulo > .modulo[data-modulo="ciudad"]:not(.modulo--dormido) { height: calc(100dvh - 64px - var(--e-5)); min-height: 560px; margin-top: var(--e-7); scroll-margin-top: 64px; }',
      '.contenido--con-modulo > .modulo[data-modulo="ciudad"] .modulo__marco { border-radius: var(--radio-l); background: var(--superficie); }',
      '@media (max-width: 760px) { .contenido--con-modulo > .modulo[data-modulo="ciudad"]:not(.modulo--dormido) { height: calc(100dvh - var(--alto-pestanas-movil) - env(safe-area-inset-bottom, 0px) - 56px - var(--e-3)); min-height: 480px; scroll-margin-top: 56px; } }',
      '.ciudad__acciones { display: flex; flex-wrap: wrap; align-items: center; gap: var(--e-3) var(--e-5); }',
      '.ciudad__cuerpo .cifra__variacion { display: block; line-height: 1.5; text-wrap: pretty; }',
      '.ciudad__cuerpo .cifra__variacion > .icono:first-child { display: inline-block; vertical-align: -2px; margin-right: 4px; }',
      '.ciudad__cuerpo .tabla td .fuente, .ciudad__cuerpo p .fuente, .ciudad__cuerpo li .fuente, .ciudad__cuerpo dd .fuente { vertical-align: middle; }',
      // Las listas clave / valor: dos columnas que pueden encoger (fr, no auto: un valor largo no ensancha la página); una sola en el teléfono.
      '.ciudad__cuerpo .resumen-datos:not(.resumen-datos--apilado) { grid-template-columns: minmax(0, 1fr) minmax(0, 1.3fr); }',
      '.ciudad__cuerpo .resumen-datos dd { font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }',
      '@media (max-width: 600px) { .ciudad__cuerpo .resumen-datos:not(.resumen-datos--apilado) { grid-template-columns: minmax(0, 1fr); } .ciudad__cuerpo .resumen-datos:not(.resumen-datos--apilado) dd { text-align: left; margin-bottom: var(--e-2); } }',
      // Las notas de los datos traen rutas de archivo largas: se parten donde haga falta para no salirse del teléfono.
      '.ciudad__cuerpo p, .ciudad__cuerpo li, .ciudad__cuerpo dd, .ciudad__cuerpo dt, .ciudad__cuerpo .aviso__cuerpo, .ciudad__cuerpo code { overflow-wrap: anywhere; }',
      // El cuerpo del desplegable es una rejilla implícita: su pista «auto» crecería hasta el ancho mínimo de la tabla más ancha y
      // sacaría todo del teléfono; con una pista 1fr que puede encoger, las tablas se desplazan dentro de su marco.
      '.ciudad__cuerpo .desplegable__cuerpo { grid-template-columns: minmax(0, 1fr); }',
      '.ciudad__cuerpo .desplegable__cuerpo > * { min-width: 0; }',
      '.ciudad__lista { margin: 0; padding-left: 20px; display: grid; gap: var(--e-2); max-width: var(--ancho-texto); }',
      '.ciudad__lista li { text-wrap: pretty; }',
      '.ciudad__pie-fuentes { display: flex; flex-wrap: wrap; gap: var(--e-2) var(--e-3); align-items: center; font-size: var(--t-s); color: var(--tinta-3); }',
      '.ciudad__base { margin: 0; font-size: var(--t-s); color: var(--tinta-2); max-width: var(--ancho-texto); text-wrap: pretty; }',
      // La pareja real / plan de la ficha en el modo «Los dos».
      '.ciudad__par { display: flex; flex-wrap: wrap; gap: var(--e-1) var(--e-4); margin: 0; }',
      '.ciudad__par[hidden], .ciudad__cuerpo .cifra__valor[hidden] { display: none; }',
      '.ciudad__lado { display: grid; gap: 0; min-width: 0; }',
      '.ciudad__quien { font-size: var(--t-xs); color: var(--tinta-3); }',
      '.ciudad__lado .num { font: var(--peso-fuerte) var(--t-xl) / 1.1 var(--fuente-titulos); font-variant-numeric: tabular-nums; letter-spacing: var(--ls-titulo); color: var(--tinta); }',
      '.ciudad__lado--real .num { color: var(--tinta-2); }',
      '.ciudad__lado .cifra__unidad { font-size: var(--t-s); }',
      '.ciudad__fichas .cifra { grid-template-rows: auto auto 1fr; align-content: stretch; }',
      '.ciudad__fichas .cifra__variacion { align-self: end; }',
      '@media (min-width: 900px) { .ciudad__fichas { grid-template-columns: repeat(4, minmax(0, 1fr)); } }',
    ].join('\n');
    document.head.appendChild(st);
  }

  // ---- Fichas real / plan / los dos (gobernadas por el interruptor) ----------------------------------------------------
  // f: { clave, etiqueta, unidad, dec, mejorSiBaja, real: {v, pop}, plan: {v, pop}, nota }
  function parDe(idReal, idPlan, campo, etiqueta, rutaBase, campoPlan) {
    const rb = rutaBase || [];
    const vr = V(idReal, rb.concat([campo])), vp = V(idPlan, rb.concat([campoPlan || campo]));
    return { real: { v: num(vr) ? vr : null, pop: popCifra(idReal, etiqueta + ', real', rb.concat([campo])) }, plan: { v: num(vp) ? vp : null, pop: popCifra(idPlan, etiqueta + ', con el plan', rb.concat([campoPlan || campo])) } };
  }
  function htmlFicha(f) {
    return '<article class="cifra" data-ficha="' + f.clave + '"><header class="cifra__cab"><h3 class="cifra__etiqueta">' + f.etiqueta + '</h3>' +
      '<button class="fuente" type="button" popovertarget="' + (f.real.pop || f.plan.pop || '') + '" aria-expanded="false" aria-label="Fuente de la cifra" data-fuente-ficha>' + icono('fuente') + '</button></header>' +
      '<p class="cifra__valor" data-valor><span class="num" data-cifra="' + (num(f.real.v) ? f.real.v : '') + '" data-decimales="' + f.dec + '">' + n(f.real.v, f.dec) + '</span>' + (f.unidad ? '<span class="cifra__unidad">' + esc(f.unidad) + '</span>' : '') + '</p>' +
      '<p class="ciudad__par" data-par hidden><span class="ciudad__lado ciudad__lado--real"><span class="ciudad__quien">Real</span><span><span class="num">' + n(f.real.v, f.dec) + '</span>' + (f.unidad ? ' <span class="cifra__unidad">' + esc(f.unidad) + '</span>' : '') + '</span></span>' +
      '<span class="ciudad__lado"><span class="ciudad__quien">Con el plan</span><span><span class="num">' + n(f.plan.v, f.dec) + '</span>' + (f.unidad ? ' <span class="cifra__unidad">' + esc(f.unidad) + '</span>' : '') + '</span></span></p>' +
      '<p class="cifra__variacion" data-variacion></p>' + (f.nota ? '<p class="cifra__nota">' + f.nota + '</p>' : '') + '</article>';
  }
  function modoActual() { return est && (est.escenario === 'modelo' || est.escenario === 'oraculo') ? est.escenario : 'hoy'; }
  // Cada lista vive en su propia rejilla (las claves se repiten entre el día y el año): se busca dentro de ella.
  function pintarLista(lista, idRejilla, animar) {
    const modo = modoActual();
    const rejilla = cont.querySelector('#' + idRejilla);
    if (!rejilla) return;
    lista.forEach(function (f) {
      const art = rejilla.querySelector('[data-ficha="' + f.clave + '"]');
      if (!art) return;
      const valor = art.querySelector('[data-valor]'), par = art.querySelector('[data-par]'), span = art.querySelector('[data-cifra]');
      const x = modo === 'modelo' ? f.plan : f.real;
      valor.hidden = modo === 'oraculo';
      par.hidden = modo !== 'oraculo';
      if (modo !== 'oraculo') {
        if (num(x.v)) { if (animar) global.COMPONENTES.ponerCifra(span, x.v); else { span.dataset.cifra = String(x.v); span.textContent = n(x.v, f.dec); } } else span.textContent = '—';
      }
      const b = art.querySelector('[data-fuente-ficha]');
      if (b) b.setAttribute('popovertarget', modo === 'hoy' ? (f.real.pop || f.plan.pop) : (f.plan.pop || f.real.pop));
      const v = art.querySelector('[data-variacion]');
      if (modo !== 'hoy' && num(f.real.v) && num(f.plan.v)) {
        const dif = f.plan.v - f.real.v;
        const p = f.real.v ? dif / f.real.v * 100 : null;
        const buena = f.mejorSiBaja === null || f.mejorSiBaja === undefined || dif === 0 ? null : (f.mejorSiBaja ? dif < 0 : dif > 0);
        v.className = 'cifra__variacion' + (buena === null ? '' : buena ? ' cifra__variacion--bien' : ' cifra__variacion--mal');
        v.innerHTML = icono(dif < 0 ? 'flecha-abajo' : dif > 0 ? 'flecha-arriba' : 'igual') + '<span>' + F.signo(dif, f.dec, f.unidad) + ' con el plan frente a lo real' + (num(p) ? ' (' + F.signo(p, 1, '%') + ')' : '') + '</span>';
      } else { v.className = 'cifra__variacion'; v.innerHTML = icono('igual') + '<span>' + (f.textoReal || 'Lo que de verdad pasó') + '</span>'; }
    });
  }
  function pintarFichas(animar) { pintarLista(fichasDia, 'ciudad-fichas-dia', animar); pintarLista(fichasAnio, 'ciudad-fichas-anio', animar); }

  // ---- 1. El 3 de junio: real frente a plan -------------------------------------------------------------------------------
  function fechaDia() {
    const c = C('ciudad_3jun_real');
    const m = c && /(\d{4}-\d{2}-\d{2})/.exec(String(c.archivo || ''));
    return m ? m[1] : null;
  }
  function seccionDia() {
    const R = 'ciudad_3jun_real', P = 'ciudad_3jun_plan';
    const fecha = fechaDia();
    const r = V(R) || {}, p = V(P) || {};
    const mk = function (clave, etiqueta, campo, unidad, dec, mejorSiBaja, nota, campoPlan) { return Object.assign({ clave: clave, etiqueta: etiqueta, unidad: unidad, dec: dec, mejorSiBaja: mejorSiBaja, nota: nota }, parDe(R, P, campo, etiqueta, null, campoPlan)); };
    fichasDia = [
      mk('salidas', 'Salidas en el día', 'salidas', 'salidas', 0, null, (num(r.salidas_validas) ? 'De las reales, ' + n(r.salidas_validas, 0) + ' con trayectoria completa; ' : '') + (num(p.salidas_programar) ? 'el plan tendría que programar ' + n(p.salidas_programar, 0) + ' para que corran las suyas.' : '')),
      mk('pax', 'Pasajeros que subieron', 'pax', 'pasajeros', 0, false, 'Con el plan suben menos: los que no encuentran bus a tiempo se pierden.'),
      mk('buses_hora', 'Buses-hora', 'buses_hora', 'buses-hora', 0, null, 'Horas de bus en ruta en el día.'),
      mk('km', 'Kilómetros', 'km', 'km', 0, true, ''),
      mk('espera', 'Espera media en el paradero', 'espera_media_min', 'min', 1, true, 'Persona a persona: cuánto esperó cada pasajero sorteado.'),
      mk('sobrecap', 'Personas por encima de la capacidad', 'sobre_capacidad', 'personas', 0, true, 'Sin tope de cupo: con el plan suben todos los que llegan.'),
      mk('costo', 'Costo de operación', 'costo_Mcop', 'M COP', 1, true, 'Bus-hora y kilómetros con los costos con fuente.'),
    ];
    const bal = V('ciudad_3jun_balance') || {};
    const pron = V('ciudad_3jun_pronostico') || {};
    const pronC = C('ciudad_3jun_pronostico');
    const intro = 'Un martes corriente' + (fecha ? ', el ' + esc(F.fechaLarga(fecha)) : '') + ', reconstruido persona a persona desde el GPS y los conteos: lo que pasó (Hoy) y el mismo día con las salidas del plan (Con el modelo). «Los dos» muestra las dos cifras y pone en la vista 3D los buses reales sólidos y los del plan como fantasmas. ' + fuentes([[R, 'el día, lado real'], [P, 'el día, lado plan']]);
    let cuerpo = '<div class="cifras ciudad__fichas" id="ciudad-fichas-dia">' + fichasDia.map(htmlFicha).join('') + '</div>';
    // El balance del día
    cuerpo += '<div class="cifras">' +
      cifraLlana('Ahorro de operación con el plan', F.signo(bal.ahorro_operacion_Mcop, 1), 'M COP', null, 'Costo real menos costo del plan.', fuente('ciudad_3jun_balance', 'ahorro de operación', ['ahorro_operacion_Mcop'])) +
      cifraLlana('Pasajes perdidos', F.signo(num(bal.pasajes_perdidos_Mcop) ? -bal.pasajes_perdidos_Mcop : undefined, 1), 'M COP', null, (num(p.perdidos_beta) ? n(p.perdidos_beta, 0) + ' pasajeros perdidos por β y ' + n(p.perdidos_sin_bus, 0) + ' sin bus en el tiempo máximo de espera, a la tarifa neta.' : ''), fuente('ciudad_3jun_balance', 'pasajes perdidos', ['pasajes_perdidos_Mcop'])) +
      cifraLlana('Saldo con la cuenta conservadora', F.signo(bal.saldo_conservador_Mcop, 1), 'M COP', { clase: num(bal.saldo_conservador_Mcop) && bal.saldo_conservador_Mcop < 0 ? 'cifra__variacion--mal' : 'cifra__variacion--bien', html: icono(num(bal.saldo_conservador_Mcop) && bal.saldo_conservador_Mcop < 0 ? 'flecha-abajo' : 'flecha-arriba') + '<span>Solo cuenta los pasajeros perdidos</span>' }, '', fuente('ciudad_3jun_balance', 'saldo conservador', ['saldo_conservador_Mcop'])) +
      cifraLlana('Saldo con la cuenta simétrica', F.signo(bal.saldo_simetrico_Mcop, 1), 'M COP', { clase: num(bal.saldo_simetrico_Mcop) && bal.saldo_simetrico_Mcop < 0 ? 'cifra__variacion--mal' : 'cifra__variacion--bien', html: icono(num(bal.saldo_simetrico_Mcop) && bal.saldo_simetrico_Mcop < 0 ? 'flecha-abajo' : 'flecha-arriba') + '<span>Cuenta también ' + (num(p.ganados_simetrico) ? n(p.ganados_simetrico, 0) + ' pasajeros ganados donde el plan añade salidas (' + F.signo(bal.valor_ganados_Mcop, 1, 'M COP') + ')' : 'los pasajeros ganados') + '</span>' }, '', fuente('ciudad_3jun_balance', 'saldo simétrico', ['saldo_simetrico_Mcop'])) +
      '</div>';
    if (num(pron.pax_previsto)) {
      cuerpo += '<p class="prosa">Ese día el plan esperaba <strong class="num">' + n(pron.pax_previsto, 0) + '</strong> pasajeros y la tabla de viajes registró <strong class="num">' + n(pron.pax_real_tabla, 0) + '</strong>' + (num(pron.pax_previsto) && pron.pax_previsto ? ' (' + F.signo((pron.pax_real_tabla - pron.pax_previsto) / pron.pax_previsto * 100, 1, '%') + ')' : '') + (pron.fuente ? '; pronóstico ' + esc(pron.fuente) : '') + ' ' + fuente('ciudad_3jun_pronostico', 'pronóstico del día') + '.' +
        (pronC && pronC.nota ? ' <span class="texto-2">' + esc(pronC.nota) + '</span>' : '') + '</p>';
    }
    // Aviso crítico: CRA 54 de 17 a 19 h
    const cr = V('ciudad_3jun_cra54_17_19') || {};
    const crC = C('ciudad_3jun_cra54_17_19');
    if (Array.isArray(cr.horas) && Array.isArray(cr.plan)) {
      const h0 = cr.horas[0], h1 = cr.horas[cr.horas.length - 1];
      const filas = cr.horas.map(function (hr, i) { return { celdas: [n(hr, 0) + ' h', n(cr.salidas_real_registradas && cr.salidas_real_registradas[i], 0), n(cr.plan[i], 0) + ' ' + fuente('ciudad_3jun_cra54_17_19', hr + ' h: salidas del plan', ['plan', i])] }; });
      cuerpo += aviso('critico', 'El hallazgo honesto: en CRA 54 de ' + n(h0, 0) + ' a ' + n(h1, 0) + ' h el plan pone ' + cr.plan.map(function (x) { return n(x, 0); }).join(' / ') + ' salidas donde se registraron ' + (cr.salidas_real_registradas || []).map(function (x) { return n(x, 0); }).join(' / '),
        '<p>El plan semanal se hizo con el pronóstico a siete días y el día típico; la tarde de ese martes trajo más gente de la prevista y el modelo persona a persona castiga al plan: los pasajeros que no encuentran bus en ' + (num(V('ciudad_plan_meta', ['espera_max_min'], true)) ? n(V('ciudad_plan_meta', ['espera_max_min'], true), 0) + ' minutos' : 'el tiempo máximo de espera') + ' se pierden. Es la hora que hay que mirar en la vista 3D.' + (crC && crC.nota ? ' ' + esc(crC.nota) : '') + ' ' + fuentes([['ciudad_3jun_cra54_17_19', 'CRA 54 de ' + h0 + ' a ' + h1 + ' h']]) + '</p>' +
        tabla(null, ['Hora de salida', 'Salidas registradas', 'Salidas del plan'], filas) + '<p class="texto-2 pequeno">' + chip('ciudad_3jun_cra54_17_19') + '</p>');
    }
    cuerpo += '<div class="ciudad__acciones"><button class="boton boton--primario" type="button" id="ciudad-ir">' + icono('flecha-abajo') + 'Ir a la vista 3D</button><p class="ciudad__base" id="ciudad-dia-actual"></p></div>';
    return seccion('ciudad-dia', 'El ' + (fecha ? esc(F.fechaLarga(fecha)) : 'día de ejemplo') + ', en la calle', intro, cuerpo);
  }
  function textoDiaActual() {
    if (!est || !est.dia) return '';
    return 'La vista 3D, abajo, está en el ' + F.fechaLarga(est.dia) + (est.hora ? ' a las ' + hhmm(est.hora) : '') + ', el mismo momento que la consola de Despacho. El interruptor de arriba cambia lo que muestra: lo real, el plan o los dos.';
  }
  function pintarDiaActual() {
    const p = cont.querySelector('#ciudad-dia-actual');
    if (p) p.textContent = textoDiaActual();
  }

  // ---- 2. Todo 2025 con el mismo modelo ---------------------------------------------------------------------------------
  function seccionAnio() {
    const R = 'ciudad_2025_real', P = 'ciudad_2025_plan';
    const dias = V(R, ['dias']);
    const mk = function (clave, etiqueta, campo, unidad, dec, mejorSiBaja, nota) { return Object.assign({ clave: clave, etiqueta: etiqueta, unidad: unidad, dec: dec, mejorSiBaja: mejorSiBaja, nota: nota, textoReal: 'Lo que pasó, promedio por día' }, parDe(R, P, campo, etiqueta, ['por_dia'])); };
    fichasAnio = [
      mk('salidas', 'Salidas por día', 'salidas', 'salidas/día', 1, null, 'Todas las salidas con trayectoria, también las marcadas canceladas que corrieron.'),
      mk('pax', 'Pasajeros por día', 'pax', 'pasajeros/día', 0, false, 'Incluye los viajes cancelados que corrieron: por eso no son los pasajeros de los viajes válidos de Inicio.'),
      mk('sobrecap', 'Personas por día por encima de la capacidad', 'sobre_capacidad', 'personas/día', 0, true, 'Sin tope de cupo.'),
      mk('costo', 'Costo de operación por día', 'costo_Mcop', 'M COP/día', 1, true, ''),
    ];
    // La espera del año está en los totales, no en por_dia.
    const esperaR = V(R, ['totales', 'espera_media_min']), esperaP = V(P, ['totales', 'espera_media_min']);
    fichasAnio.push({ clave: 'espera', etiqueta: 'Espera media en el paradero', unidad: 'min', dec: 2, mejorSiBaja: true, nota: 'Persona a persona, todo el año.', textoReal: 'Lo que pasó, todo el año',
      real: { v: num(esperaR) ? esperaR : null, pop: popCifra(R, 'espera media, real', ['totales', 'espera_media_min']) }, plan: { v: num(esperaP) ? esperaP : null, pop: popCifra(P, 'espera media, con el plan', ['totales', 'espera_media_min']) } });
    const s = V('ciudad_2025_saldo') || {};
    const neg = V('ciudad_dias_saldo_negativo') || {};
    const intro = 'El mismo modelo persona a persona, día por día, en los <strong class="num">' + n(dias, 0) + '</strong> días de ' + ANIO + ' con GPS ' + fuente(R, 'días con GPS', ['dias']) + '. Es otra base que la de Inicio y Resultado (ahí, los viajes válidos de los 365 días con la contabilidad de D5): aquí se cuentan todos los viajes con trayectoria y se asigna cada pasajero a un bus del plan.';
    let cuerpo = '<div class="cifras ciudad__fichas" id="ciudad-fichas-anio">' + fichasAnio.map(htmlFicha).join('') + '</div>';
    const cS = function (campo, t) { return fuente('ciudad_2025_saldo', t, [campo]); };
    cuerpo += '<div class="cifras">' +
      cifraLlana('Ahorro de operación en el año', F.signo(s.ahorro_operacion_Mcop, 0), 'M COP', null, (num(s.dias) ? 'En ' + n(s.dias, 0) + ' días.' : ''), cS('ahorro_operacion_Mcop', 'ahorro de operación')) +
      cifraLlana('Pasajes perdidos en el año', F.signo(num(s.pasajes_perdidos_Mcop) ? -s.pasajes_perdidos_Mcop : undefined, 0), 'M COP', null, (num(s.pasajeros_en_riesgo_dia) ? n(s.pasajeros_en_riesgo_dia, 0) + ' pasajeros en riesgo por día (' + n(s.perdidos_beta_dia, 0) + ' por β y ' + n(s.perdidos_sin_bus_dia, 0) + ' sin bus).' : ''), cS('pasajes_perdidos_Mcop', 'pasajes perdidos')) +
      cifraLlana('Saldo con la cuenta conservadora', F.signo(s.saldo_conservador_Mcop, 0), 'M COP', { clase: num(s.saldo_conservador_Mcop) && s.saldo_conservador_Mcop < 0 ? 'cifra__variacion--mal' : 'cifra__variacion--bien', html: icono(num(s.saldo_conservador_Mcop) && s.saldo_conservador_Mcop < 0 ? 'flecha-abajo' : 'flecha-arriba') + '<span>' + (num(neg.total) ? 'Pierde en ' + n(neg.total, 0) + ' de ' + n(neg.de, 0) + ' días ' + fuente('ciudad_dias_saldo_negativo', 'días con saldo negativo', ['total']) : 'Solo cuenta los pasajeros perdidos') + '</span>' }, '', cS('saldo_conservador_Mcop', 'saldo conservador')) +
      cifraLlana('Saldo con la cuenta simétrica', F.signo(s.saldo_simetrico_Mcop, 0), 'M COP', { clase: num(s.saldo_simetrico_Mcop) && s.saldo_simetrico_Mcop < 0 ? 'cifra__variacion--mal' : 'cifra__variacion--bien', html: icono(num(s.saldo_simetrico_Mcop) && s.saldo_simetrico_Mcop < 0 ? 'flecha-abajo' : 'flecha-arriba') + '<span>Cuenta también los ganados: ' + (num(s.pasajeros_netos_dia_simetrico) ? F.signo(s.pasajeros_netos_dia_simetrico, 0, 'pasajeros netos por día') : '') + '</span>' }, '', cS('saldo_simetrico_Mcop', 'saldo simétrico')) +
      '</div>';
    // Tabla por tipo de día
    const pt = V('ciudad_2025_por_tipo_dia') || {};
    const scd = X('ciudad_2025_por_tipo_dia', 'saldo_conservador_Mcop_dia') || {};
    const filas = TIPOS.filter(function (t) { return pt[t]; }).map(function (t) {
      const x = pt[t], re = (x.real && x.real.por_dia) || {}, pl = (x.plan && x.plan.por_dia) || {}, ng = neg[t] || {};
      return { celdas: [esc(TIPO_TEXTO[t] || t), n(x.dias, 0), flecha(re.salidas, pl.salidas, 0), flecha(re.pax, pl.pax, 0), flecha(re.sobre_capacidad, pl.sobre_capacidad, 0), flecha(re.costo_Mcop, pl.costo_Mcop, 1),
        F.signo(scd[t], 1) + ' ' + fuente('ciudad_2025_por_tipo_dia', TIPO_TEXTO[t] + ': saldo conservador por día', [t, 'plan', 'por_dia', 'costo_Mcop'], null, { clave: 'saldo_conservador_Mcop_dia[' + t + ']: (por_tipo_dia[' + t + '].real.total.costo_Mcop − plan.total.costo_Mcop − plan.total.pasajes_perdidos_Mcop) / dias', valor: num(scd[t]) ? scd[t] : undefined }),
        num(ng.negativos) ? n(ng.negativos, 0) + ' de ' + n(ng.dias, 0) : '—'] };
    });
    if (filas.length) cuerpo += tabla('Por tipo de día (promedio por día): real → con el plan', ['Tipo de día', 'Días', 'Salidas', 'Pasajeros', 'Sobre capacidad', 'Costo (M COP)', 'Saldo conservador (M COP/día)', 'Días que pierden'], filas);
    // Aviso de canje: conservadora frente a simétrica; comparación con D5 (C8)
    const d5c = V('inicio_saldo_conservador', null, true), d5s = V('inicio_saldo_simetrico', null, true), d5p = V('inicio_pax_riesgo_plan', null, true);
    const conD5 = num(d5c) && num(d5s) ? ' Con la contabilidad de D5 (viajes válidos de todo el año, con revisor independiente), que es la principal en Inicio y Resultado, el mismo plan da <strong class="num">' + F.signo(d5c, 0, 'M COP') + '</strong> con la conservadora y <strong class="num">' + F.signo(d5s, 0, 'M COP') + '</strong> con la simétrica' + (num(d5p) ? ', con <strong class="num">' + n(d5p, 0) + '</strong> pasajeros en riesgo por día' : '') + ' ' + fuentes([['inicio_saldo_conservador', 'saldo conservador (D5)'], ['inicio_saldo_simetrico', 'saldo simétrico (D5)'], ['inicio_pax_riesgo_plan', 'pasajeros en riesgo (D5)']]) + '. Las dos bases cuentan pasajeros distintos y por eso no coinciden; el signo del saldo depende de la cuenta en las dos.' : '';
    cuerpo += aviso('canje', 'Conservadora frente a simétrica: el signo del saldo depende de a quién se cuenta',
      '<p>La cuenta <strong>conservadora</strong> resta solo los pasajes de quienes se pierden donde el plan quita salidas (β de E7 y quienes no encuentran bus): <strong class="num">' + F.signo(s.saldo_conservador_Mcop, 0, 'M COP') + '</strong> en el año' + (num(neg.total) ? ', con pérdida en <strong class="num">' + n(neg.total, 0) + '</strong> de <strong class="num">' + n(neg.de, 0) + '</strong> días' : '') + '. La <strong>simétrica</strong> suma también los pasajes de quienes suben donde el plan añade salidas: <strong class="num">' + F.signo(s.saldo_simetrico_Mcop, 0, 'M COP') + '</strong> ' + fuentes([['ciudad_2025_saldo', 'saldo de ' + ANIO + ' persona a persona'], ['ciudad_dias_saldo_negativo', 'días con saldo negativo']]) + '.' + conD5 + '</p>' +
      '<p class="texto-2 pequeno">Persona a persona: ' + chip('ciudad_2025_saldo') + '; días con saldo negativo: ' + chip('ciudad_dias_saldo_negativo') + '.</p>');
    return seccion('ciudad-anio', 'Todo ' + ANIO + ' con el mismo modelo', intro, cuerpo);
  }

  // ---- 3. Ver cómo se calculó y límites ------------------------------------------------------------------------------------
  function seccionComoSeCalculo() {
    const partes = [];
    const pm = V('ciudad_plan_meta') || {};
    if (pm.fuente || pm.metodo) {
      partes.push('<h3>Los supuestos del lado plan</h3>' + dl([
        ['Costos', esc(pm.fuente || '—') + ': bus-hora ' + n(pm.bus_hora, 0) + ' COP, km ' + n(pm.km, 0) + ' COP, tarifa neta ' + n(pm.tarifa, 0) + ' COP ' + fuente('ciudad_plan_meta', 'costos del plan', ['bus_hora'])],
        ['Elasticidad del plan', n(pm.elasticidad_plan, 1) + ' ' + fuente('ciudad_plan_meta', 'elasticidad', ['elasticidad_plan'])],
        ['β (pasajeros que se pierden al quitar una salida)', n(pm.beta, 2) + ' ' + fuente('ciudad_plan_meta', 'β', ['beta'])],
        ['Tiempo máximo que espera un pasajero', n(pm.espera_max_min, 0) + ' min ' + fuente('ciudad_plan_meta', 'espera máxima', ['espera_max_min'])],
      ]) + (pm.metodo ? '<p class="prosa texto-2 pequeno">' + esc(pm.metodo) + '</p>' : '') + '<p class="texto-2 pequeno">' + chip('ciudad_plan_meta') + '</p>');
    }
    const ver = V('ciudad_version_calles') || {};
    if (num(ver.version)) partes.push('<h3>La versión del modelo persona a persona</h3><p class="prosa">Versión <strong class="num">' + n(ver.version, 0) + '</strong>, generada el ' + esc(ver.generado || '—') + ': <strong class="num">' + n(ver.dias, 0) + '</strong> días' + (num(ver.pendientes) ? ' y ' + n(ver.pendientes, 0) + ' pendientes' : ', ninguno pendiente') + ' ' + fuente('ciudad_version_calles', 'versión', ['version']) + '. ' + chip('ciudad_version_calles') + '</p>');
    // El 3 de junio hora a hora
    const ph = V('ciudad_3jun_por_hora') || {};
    const horas = Object.keys(ph).map(Number).filter(function (h) { return !isNaN(h); }).sort(function (a, b) { return a - b; });
    if (horas.length) {
      const filas = horas.map(function (h) { const x = ph[String(h)] || {}, re = x.real || {}, pl = x.plan || {}, pr = x.pronostico || {}; return { celdas: [n(h, 0) + ' h', flecha(re.salidas, pl.salidas, 0), flecha(re.pax, pl.pax, 0), n(pr.pax_previsto, 0), n(pl.perdidos_beta, 0) + ' + ' + n(pl.perdidos_sin_bus, 0) + ' ' + fuente('ciudad_3jun_por_hora', h + ' h: perdidos con el plan', [String(h), 'plan', 'perdidos_beta']), n(pl.ganados_simetrico, 0), flecha(re.espera_media_min, pl.espera_media_min, 1)] }; });
      partes.push('<h3>El ' + esc(fechaDia() ? F.fecha(fechaDia()) : 'día') + ', hora a hora (real → plan)</h3>' + tabla(null, ['Hora de salida', 'Salidas', 'Pasajeros', 'Previstos por el plan', 'Perdidos (β + sin bus)', 'Ganados (simétrica)', 'Espera (min)'], filas) + '<p class="texto-2 pequeno">' + chip('ciudad_3jun_por_hora') + '</p>');
    }
    // Todo 2025 por hora
    const ah = V('ciudad_2025_por_hora') || {};
    const horasA = Object.keys(ah).map(Number).filter(function (h) { return !isNaN(h); }).sort(function (a, b) { return a - b; });
    if (horasA.length) {
      const filas = horasA.map(function (h) { const x = ah[String(h)] || {}, re = (x.real && x.real.por_dia) || {}, pl = (x.plan && x.plan.por_dia) || {}; return { celdas: [n(h, 0) + ' h', flecha(re.salidas, pl.salidas, 1), flecha(re.pax, pl.pax, 0), flecha(re.sobre_capacidad, pl.sobre_capacidad, 0), n(pl.perdidos_beta, 0) + ' + ' + n(pl.perdidos_sin_bus, 0) + ' ' + fuente('ciudad_2025_por_hora', h + ' h: perdidos por día con el plan', [String(h), 'plan', 'por_dia', 'perdidos_beta']), n(pl.ganados_simetrico, 0)] }; });
      partes.push('<h3>Todo ' + ANIO + ' por hora de salida (promedio por día, real → plan)</h3><p class="prosa">Dónde pierde y dónde gana el plan a lo largo del día: quita salidas en el valle de la mañana y la tarde y las pone en los picos.</p>' + tabla(null, ['Hora de salida', 'Salidas', 'Pasajeros', 'Sobre capacidad', 'Perdidos (β + sin bus)', 'Ganados (simétrica)'], filas) + '<p class="texto-2 pequeno">' + chip('ciudad_2025_por_hora') + '</p>');
    }
    const limites = '<h3>Límites</h3><ul class="ciudad__lista">' +
      '<li><strong>Sin tope de cupo.</strong> Los buses del plan cargan a todos los que llegan: la cifra de personas por encima de la capacidad sube con el plan y mide apretura, no pasajeros dejados.</li>' +
      '<li><strong>La demanda real se asigna a los buses del plan.</strong> Cada pasajero sorteado toma el primer bus del plan que pasa' + (num(pm.espera_max_min) ? ' en ' + n(pm.espera_max_min, 0) + ' minutos' : '') + '; si no pasa ninguno, se pierde. No hay elasticidad: nadie cambia de hora ni de ruta.</li>' +
      '<li><strong>Dos bases de salidas.</strong> Aquí cuentan todas las salidas con trayectoria GPS (también las marcadas canceladas que corrieron); Inicio y Resultado cuentan los viajes válidos de la tabla de viajes. Por eso las salidas y los pasajeros por día no coinciden entre pantallas.</li>' +
      '<li><strong>Revisión parcial.</strong> El modelo persona a persona y el día de ejemplo se revisaron; la suma anual no tuvo recálculo independiente, y los días con saldo negativo se cuentan al generar los datos de la app.</li>' +
      '</ul>';
    return seccion('ciudad-como', 'Cómo se calculó', null, desplegable('ciudad-desplegable', 'Ver cómo se calculó', partes.join('') + limites), true);
  }

  // ---- El módulo: modo «ver» y desplazamiento ---------------------------------------------------------------------------
  function verActual() { return VER_DE[modoActual()] || 'ambos'; }
  let verEnviado = null;
  function enviarVer() {
    const m = app().modulo(ID);
    if (!m) return;
    const ver = verActual();
    if (m.enviar({ tipo: 'ver', ver: ver })) verEnviado = ver;
  }
  function irAlModulo() {
    const m = app().modulo(ID);
    if (!m || !m.elemento) return;
    try { m.elemento.scrollIntoView({ behavior: reducido() ? 'auto' : 'smooth', block: 'start' }); } catch (e) { m.elemento.scrollIntoView(); }
  }
  function ligar() {
    const ir = cont.querySelector('#ciudad-ir');
    if (ir) ir.addEventListener('click', irAlModulo);
    // La vista 3D avisa «listo» (se le manda el modo elegido) y «estado» con su modo «ver»: si el usuario lo cambió
    // dentro de la vista, el interruptor de la app lo sigue.
    const oyente = function (e) {
      const m = app().modulo(ID);
      if (!m || !e.data || typeof e.data !== 'object' || e.source !== m.iframe.contentWindow) return;
      if (e.data.tipo === 'listo') { enviarVer(); return; }
      if (e.data.tipo === 'estado' && ESC_DE[e.data.ver] && ESC_DE[e.data.ver] !== modoActual()) app().ponerEstado({ escenario: ESC_DE[e.data.ver] });
    };
    global.addEventListener('message', oyente);
    limpiezas.push(function () { global.removeEventListener('message', oyente); });
  }

  // ---- Contrato de la pantalla --------------------------------------------------------------------------------------
  function render(contenedor, datos, estado) {
    salir();
    cont = contenedor; D = datos || global.DATOS_APP || {}; est = estado || {};
    faltantes = []; nPop = 0;
    estilos();
    if (!C('ciudad_3jun_real')) {
      cont.innerHTML = aviso('atencion', 'Sin datos de la ciudad', '<p>Falta app/datos_app.js o no trae las cifras de esta pantalla. La vista 3D, abajo, funciona igual.</p>');
      return;
    }
    const partes = [seccionDia(), seccionAnio(), seccionComoSeCalculo()];
    const cab = faltantes.length ? aviso('atencion', 'Faltan datos en app/datos_app.js', '<p>Esta pantalla no encontró ' + n(faltantes.length, 0) + ' ids: <code>' + faltantes.map(esc).join('</code>, <code>') + '</code>. Donde faltan se muestra «—».</p>') : '';
    cont.innerHTML = '<div class="pila pila--ancha ciudad__cuerpo">' + cab + partes.join('') + '</div>';
    pintarFichas(false);
    pintarDiaActual();
    ligar();
    global.COMPONENTES.fuentes(cont);
    global.COMPONENTES.cifras(cont);
    // Si el módulo ya existe (se vuelve a la pantalla), se le manda el modo del interruptor.
    global.setTimeout(enviarVer, 0);
  }
  function actualizar(estado) {
    if (!cont) return;
    const antes = est || {};
    est = estado || {};
    if (antes.escenario !== est.escenario) { pintarFichas(true); enviarVer(); }
    if (antes.dia !== est.dia || antes.hora !== est.hora) pintarDiaActual();
  }
  function salir() {
    limpiezas.forEach(function (f) { try { f(); } catch (e) { /* nada */ } });
    limpiezas = [];
  }

  const definicion = {
    id: ID,
    pregunta: '¿Cómo se ve en la calle?',
    subtitulo: function (datos) {
      D = datos || global.DATOS_APP || {};
      const b = V('ciudad_3jun_balance', null, true) || {}, s = V('ciudad_2025_saldo', null, true) || {};
      if (!num(b.ahorro_operacion_Mcop) || !num(s.saldo_conservador_Mcop)) return 'La vista 3D: los buses y los pasajeros por las calles, un día a la vez, lo real frente al plan.';
      return 'Persona a persona, el ' + (fechaDia() ? F.fechaLarga(fechaDia()) : 'día de ejemplo') + ' el plan ahorra ' + n(b.ahorro_operacion_Mcop, 1) + ' M COP de operación pero pierde ' + n(b.pasajes_perdidos_Mcop, 1) + ' M en pasajes; en todo ' + ANIO + ' el saldo es ' + F.signo(s.saldo_conservador_Mcop, 0) + ' M con la cuenta conservadora y ' + F.signo(s.saldo_simetrico_Mcop, 0) + ' M con la simétrica.';
    },
    icono: 'ciudad',
    // Los tooltips van cortos: el de la cabecera no parte líneas y se centra bajo la opción (en el teléfono caben unos 24 caracteres).
    interruptor: [
      { valor: 'hoy', tooltip: 'Lo que pasó ese día' },
      { valor: 'modelo', tooltip: 'El mismo día con el plan' },
      { valor: 'oraculo', etiqueta: 'Los dos', tooltip: 'Lo real y el plan a la vez' },
    ],
    modulo: { pagina: 'vista_3d.html', nombre: 'Vista 3D', icono: 'ciudad', completo: false,
      hash: function (e) { return 'dia=' + e.dia + '&hora=' + hhmm(e.hora) + '&ver=' + (VER_DE[e.escenario] || 'ambos') + '&pausa=1'; } },
    render: render,
    actualizar: actualizar,
    salir: salir,
  };
  if (typeof global.registrarPantalla === 'function') global.registrarPantalla(definicion);
  else (global.__pantallasRegistradas = global.__pantallasRegistradas || []).push(definicion);
})(window);
