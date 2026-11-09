// Sobusa Despacho · pantallas/horario.js — Horario · ¿Cuántos buses y cada cuánto?
// Resumen propio encima del planificador embebido (planificador.html?embebido=1#plan), según el wireframe de
// app/DISEÑO.md §7: fichas del día promedio de 2025 (hoy / con el modelo, con el interruptor), la frase de la
// diapositiva, las nueve combinaciones ruta × tipo de día, el aviso de canje (con los supuestos de D5 el plan recortaba;
// con los costos con fuente reasigna), qué tan cerca del óptimo quedan hoy y el plan (frente al oráculo), la flota y los
// picos y valles de CRA 54, y «Ver cómo se calculó». Ninguna cifra está escrita aquí: todas salen de window.DATOS_APP
// (app/datos_app.js) y cada una lleva su botón «fuente» (clave exacta tomada de «origen» cuando existe).
//
// Ids que lee (pantalla horario): horario_dia_promedio_2025, horario_dia_promedio_supuestos, horario_frase,
// horario_tabla_9_combinaciones, horario_aviso_flota, horario_juegos_de_costos, horario_parametros_milp,
// horario_validacion_planificador, horario_datos_planificador_js, horario_recomendado_minuto_a_minuto,
// horario_dia_tipico_d5, horario_escenarios_d5, horario_calidad_decision_d5, horario_beta_equilibrio_asimetrica_d5,
// horario_calidad_decision_d1, horario_picos_y_valles_cra54, horario_flota_d2, horario_exceso_deficit_d2,
// horario_simulador_d6, horario_dia_tipico_por_hora. Si un id falta, se dice en un aviso y se pinta «—».
//
// El módulo (iframe) lo crea y lo conserva app.js a partir de «modulo» (completo: false → va debajo del resumen, con
// alto propio: aquí se le da la altura de la ventana menos la cabecera compacta). Esta pantalla le manda {tipo:'ruta'}
// cuando cambian los chips de ruta (estado.ruta) y «Ir al planificador» desplaza hasta él.
(function (global) {
  'use strict';

  const ID = 'horario';
  const PREFIJO = 'fh-';
  const ANIO = '2025', ANIO_COSTOS = '2026';
  const F = global.COMPONENTES.formato;
  const icono = function (nombre, clase) { return global.ICONOS.svg(nombre, clase); };
  const FINO = ' ';
  const RUTAS = ['SILENCIO', 'CRA 54', 'CL 72'];
  const RUTA_TOKEN = { 'SILENCIO': '--ruta-silencio', 'CRA 54': '--ruta-cra54', 'CL 72': '--ruta-cl72' };
  const TIPOS = ['Laboral', 'Sábado', 'Domingo/festivo'];
  const TIPO_TEXTO = { 'Laboral': 'laboral', 'Sábado': 'sábado', 'Domingo/festivo': 'domingo o festivo' };

  let D = null, cont = null, est = null, nPop = 0, faltantes = [], fichasDef = [], limpiezas = [];

  // ---- Utilidades ----------------------------------------------------------------------------------------------
  function app() { return global.app; }
  function num(v) { return typeof v === 'number' && isFinite(v); }
  function n(v, d) { return num(v) ? F.numero(v, d || 0) : '—'; }
  function pct(v, d) { return num(v) ? F.numero(v, d === undefined ? 1 : d) + FINO + '%' : '—'; }
  function esc(s) { return String(s === undefined || s === null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'); }
  function suma(a) { return Array.isArray(a) ? a.reduce(function (x, y) { return x + (num(y) ? y : 0); }, 0) : null; }
  function reducido() { return global.matchMedia && global.matchMedia('(prefers-reduced-motion: reduce)').matches; }
  // [4,5,6,7,8,13,14,15] → «4-8 y 13-15»
  function rangos(horas) {
    if (!Array.isArray(horas) || !horas.length) return '';
    const h = horas.slice().sort(function (a, b) { return a - b; });
    const tramos = [];
    let ini = h[0], fin = h[0];
    for (let i = 1; i <= h.length; i++) {
      if (i < h.length && h[i] === fin + 1) { fin = h[i]; continue; }
      tramos.push(ini === fin ? String(ini) : ini + '-' + fin);
      if (i < h.length) { ini = h[i]; fin = h[i]; }
    }
    return tramos.length > 1 ? tramos.slice(0, -1).join(', ') + ' y ' + tramos[tramos.length - 1] : tramos[0];
  }

  // ---- Datos ---------------------------------------------------------------------------------------------------
  function entrada(id) {
    const p = D && D.pantallas;
    if (!p) return null;
    if (p[ID] && p[ID][id]) return p[ID][id];
    for (const k in p) if (p[k] && p[k][id]) return p[k][id];
    return null;
  }
  function C(id) {
    const e = entrada(id);
    if (!e) { if (faltantes.indexOf(id) < 0) faltantes.push(id); return null; }
    return app() && app().normalizarCifra ? app().normalizarCifra(e) : e;
  }
  function V(id, ruta) {
    const c = C(id);
    if (!c) return null;
    let v = c.valor;
    if (ruta) for (let i = 0; i < ruta.length; i++) { if (v === null || v === undefined) return null; v = v[ruta[i]]; }
    return v === undefined ? null : v;
  }
  function X(id, campo) { const c = C(id); return c && c[campo] !== undefined ? c[campo] : null; }

  // ---- Fuentes: popover por cifra o por parte de la cifra ------------------------------------------------------
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
  // La referencia exacta de una parte de la cifra: el «origen» cuya ruta es el prefijo más largo de la pedida.
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
    const c = C(id);
    if (!c) return null;
    nPop += 1;
    const idPop = PREFIJO + nPop;
    const ajuste = { que_mide: esc(c.que_es || '') };
    if (ruta && ruta.length) {
      const r = refDe(c, ruta);
      if (r) { if (r.archivo) ajuste.archivo = r.archivo; ajuste.clave = r.clave; } else ajuste.clave = (c.clave || '—') + ' → ' + ruta.join(' → ');
      const v = V(id, ruta);
      ajuste.valor = typeof v === 'number' || typeof v === 'string' ? v : undefined;
    }
    Object.assign(ajuste, extra || {});   // lo que pide la pantalla (clave, nota, valor) manda sobre lo deducido de «origen»
    app().popoverFuente(idPop, Object.assign({}, c, ajuste), titulo || c.que_es || id);
    return idPop;
  }
  function fuente(id, titulo, ruta, texto, extra) { const p = popCifra(id, titulo, ruta, extra); return p ? app().botonFuente(p, texto) : ''; }
  // Varias cifras en un solo botón «Fuentes (n)»: [[id, título, ruta?], …]
  function fuentes(pares, titulo) {
    const validos = pares.filter(function (p) { return !!C(p[0]); });
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
  function chip(id) { const c = C(id); return c ? app().chipVerificado(c.verificado) : ''; }

  // ---- Piezas de HTML -------------------------------------------------------------------------------------------
  function seccion(id, titulo, intro, cuerpo, oculto) {
    return '<section class="seccion" id="' + id + '" aria-labelledby="' + id + '-t"><div class="seccion__cab"><h2 class="seccion__titulo' + (oculto ? ' oculto' : '') + '" id="' + id + '-t">' + titulo + '</h2></div>' +
      (intro ? '<p class="seccion__intro">' + intro + '</p>' : '') + '<div class="seccion__cuerpo">' + cuerpo + '</div></section>';
  }
  function aviso(tipo, titulo, cuerpo) {
    const ic = tipo === 'canje' ? 'canje' : tipo === 'bien' ? 'bien' : tipo === 'nota' ? 'info' : 'alerta';
    return '<div class="aviso' + (tipo && tipo !== 'nota' ? ' aviso--' + tipo : '') + '">' + icono(ic) + '<div class="aviso__cuerpo"><h3 class="aviso__titulo">' + titulo + '</h3>' + cuerpo + '</div></div>';
  }
  function tabla(caption, cabeceras, filas, opciones) {
    opciones = opciones || {};
    const esTexto = function (i) { return i === 0 || (opciones.textoEn && opciones.textoEn.indexOf(i) >= 0); };
    let h = '<div class="tabla-marco"><table class="tabla' + (opciones.compacta === false ? '' : ' tabla--compacta') + '">';
    if (caption) h += '<caption>' + caption + '</caption>';
    h += '<thead><tr>' + cabeceras.map(function (c, i) { return '<th scope="col"' + (esTexto(i) ? '' : ' class="num"') + '>' + c + '</th>'; }).join('') + '</tr></thead><tbody>';
    filas.forEach(function (fila) {
      h += '<tr' + (fila.clase ? ' class="' + fila.clase + '"' : '') + (fila.datos ? ' ' + fila.datos : '') + '>' + fila.celdas.map(function (c, i) {
        return i === 0 && !opciones.sinCabeceraFila ? '<th scope="row">' + c + '</th>' : '<td' + (esTexto(i) ? '' : ' class="num"') + '>' + c + '</td>';
      }).join('') + '</tr>';
    });
    return h + '</tbody></table></div>';
  }
  function dl(pares, apilado) {
    return '<dl class="resumen-datos' + (apilado ? ' resumen-datos--apilado' : '') + '">' + pares.map(function (p) { return '<dt>' + p[0] + '</dt><dd>' + p[1] + '</dd>'; }).join('') + '</dl>';
  }
  function desplegable(id, titulo, cuerpo) {
    return '<details class="desplegable" id="' + id + '"><summary class="desplegable__resumen">' + icono('chevron-derecha', 'icono desplegable__chevron') + titulo + '</summary><div class="desplegable__cuerpo">' + cuerpo + '</div></details>';
  }
  function flecha(a, b, d) { return '<span class="num">' + n(a, d) + '</span> <span class="texto-3">→</span> <span class="num">' + n(b, d) + '</span>'; }
  function cifraLlana(etiqueta, valorHtml, unidad, nota, botonFuente, claseValor) {
    return '<article class="cifra cifra--llana"><header class="cifra__cab"><h3 class="cifra__etiqueta">' + etiqueta + '</h3>' + (botonFuente || '') + '</header>' +
      '<p class="cifra__valor' + (claseValor ? ' ' + claseValor : '') + '"><span class="num">' + valorHtml + '</span>' + (unidad ? '<span class="cifra__unidad">' + esc(unidad) + '</span>' : '') + '</p>' +
      (nota ? '<p class="cifra__nota">' + nota + '</p>' : '') + '</article>';
  }

  // ---- Estilos propios (solo tokens) ------------------------------------------------------------------------------
  function estilos() {
    if (document.getElementById('estilos-horario')) return;
    const st = document.createElement('style');
    st.id = 'estilos-horario';
    st.textContent = [
      // El planificador, debajo del resumen, con la altura de la ventana menos la cabecera compacta (64 px): «Ir al
      // planificador» lo deja justo debajo de ella y ocupa todo lo que queda. En el teléfono, menos la barra inferior.
      '.contenido--con-modulo > .modulo[data-modulo="horario"]:not(.modulo--dormido) { height: calc(100dvh - 64px - var(--e-5)); min-height: 520px; margin-top: var(--e-7); scroll-margin-top: 64px; }',
      '.contenido--con-modulo > .modulo[data-modulo="horario"] .modulo__marco { border-radius: var(--radio-l); background: var(--superficie); }',
      '@media (max-width: 760px) { .contenido--con-modulo > .modulo[data-modulo="horario"]:not(.modulo--dormido) { height: calc(100dvh - var(--alto-pestanas-movil) - env(safe-area-inset-bottom, 0px) - 56px - var(--e-3)); min-height: 440px; scroll-margin-top: 56px; } }',
      '.horario__acciones { display: flex; flex-wrap: wrap; align-items: center; gap: var(--e-3) var(--e-5); }',
      '.horario__acciones .chips { align-items: center; }',
      '.horario__cuerpo .cifra__variacion { display: block; line-height: 1.5; text-wrap: pretty; }',
      '.horario__cuerpo .cifra__variacion > .icono:first-child { display: inline-block; vertical-align: -2px; margin-right: 4px; }',
      '.horario__cuerpo .tabla td .fuente, .horario__cuerpo p .fuente, .horario__cuerpo li .fuente, .horario__cuerpo dd .fuente { vertical-align: middle; }',
      // Las listas clave / valor: dos columnas que pueden encoger (fr, no auto: un valor largo no ensancha la página); una sola en el teléfono.
      '.horario__cuerpo .resumen-datos:not(.resumen-datos--apilado) { grid-template-columns: minmax(0, 1fr) minmax(0, 1.3fr); }',
      '.horario__cuerpo .resumen-datos dd { font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }',
      '@media (max-width: 600px) { .horario__cuerpo .resumen-datos:not(.resumen-datos--apilado) { grid-template-columns: minmax(0, 1fr); } .horario__cuerpo .resumen-datos:not(.resumen-datos--apilado) dd { text-align: left; margin-bottom: var(--e-2); } }',
      // Las notas de los datos traen rutas de archivo largas: se parten donde haga falta para no salirse del teléfono.
      '.horario__cuerpo p, .horario__cuerpo li, .horario__cuerpo dd, .horario__cuerpo dt, .horario__cuerpo .aviso__cuerpo, .horario__cuerpo code { overflow-wrap: anywhere; }',
      '.horario__cuerpo .tabla tr[data-ruta] { transition: background var(--dur-1) var(--curva); }',
      '.horario__cuerpo .tabla tr.horario__fila-elegida td, .horario__cuerpo .tabla tr.horario__fila-elegida th { background: var(--acento-suave); }',
      // El cuerpo del desplegable es una rejilla implícita: su pista «auto» crecería hasta el ancho mínimo de la tabla más ancha y
      // sacaría todo del teléfono; con una pista 1fr que puede encoger, las tablas se desplazan dentro de su marco.
      '.horario__cuerpo .desplegable__cuerpo { grid-template-columns: minmax(0, 1fr); }',
      '.horario__cuerpo .desplegable__cuerpo > * { min-width: 0; }',
      '.horario__lista { margin: 0; padding-left: 20px; display: grid; gap: var(--e-2); max-width: var(--ancho-texto); }',
      '.horario__lista li { text-wrap: pretty; }',
      '.horario__pie-fuentes { display: flex; flex-wrap: wrap; gap: var(--e-2) var(--e-3); align-items: center; font-size: var(--t-s); color: var(--tinta-3); }',
      '@media (min-width: 900px) { #horario-fichas { grid-template-columns: repeat(3, minmax(0, 1fr)); } }',
    ].join('\n');
    document.head.appendChild(st);
  }

  // ---- 1. El día promedio: fichas que gobierna el interruptor -------------------------------------------------------
  const DP = 'horario_dia_promedio_2025';
  function definirFichas() {
    const d = V(DP) || {};
    const def = function (clave, etiqueta, campo, unidad, dec, mejorSiBaja, nota, factor) {
      const f = factor || 1;
      const hoyV = num(d[campo + '_hoy']) ? d[campo + '_hoy'] * f : null;
      const planV = num(d[campo + '_plan']) ? d[campo + '_plan'] * f : null;
      const conversion = f !== 1 ? { nota: 'Convertido en pantalla: el archivo trae COP por día y la ficha muestra millones de COP (× ' + f + ').' } : null;
      const popHoy = popCifra(DP, etiqueta + ', hoy', [campo + '_hoy'], conversion);
      const popPlan = popCifra(DP, etiqueta + ', con el modelo', [campo + '_plan'], conversion);
      return { clave: clave, etiqueta: etiqueta, unidad: unidad, dec: dec, mejorSiBaja: mejorSiBaja, nota: nota, hoy: { v: hoyV, pop: popHoy }, modelo: { v: planV, pop: popPlan } };
    };
    return [
      def('salidas', 'Salidas por día', 'salidas', 'salidas/día', 0, null, 'Las tres rutas, ponderadas por los días de cada tipo.'),
      def('buses_hora', 'Buses-hora por día', 'buses_hora', 'buses-hora/día', 0, null, 'Horas de bus en ruta: casi no cambian, porque el plan mueve salidas en vez de quitarlas.'),
      def('espera', 'Espera media en el paradero', 'espera_min', 'min', 1, true, 'Fórmula del intervalo con la irregularidad medida; la misma para hoy y para el plan.'),
      def('sobrecap', 'Pasajeros por día por encima de la capacidad', 'pax_sobre_capacidad', 'pasajeros/día', 0, true, 'En el tramo más cargado de cada viaje. A eso se destinan las salidas que se mueven.'),
      def('costo', 'Costo de operación por día', 'costo_op', 'M COP/día', 1, true, 'Conductor por hora y kilómetros, con los costos de ' + ANIO_COSTOS + ' de fuente pública.', 1e-6),
      def('km', 'Kilómetros por día', 'km', 'km/día', 0, true, 'Los kilómetros que recorre la flota en un día promedio.'),
    ];
  }
  function htmlFicha(f) {
    return '<article class="cifra" data-ficha="' + f.clave + '"><header class="cifra__cab"><h3 class="cifra__etiqueta">' + f.etiqueta + '</h3>' +
      '<button class="fuente" type="button" popovertarget="' + (f.hoy.pop || f.modelo.pop || '') + '" aria-expanded="false" aria-label="Fuente de la cifra" data-fuente-ficha>' + icono('fuente') + '</button></header>' +
      '<p class="cifra__valor"><span class="num" data-cifra="' + (num(f.hoy.v) ? f.hoy.v : '') + '" data-decimales="' + f.dec + '">' + n(f.hoy.v, f.dec) + '</span>' + (f.unidad ? '<span class="cifra__unidad">' + esc(f.unidad) + '</span>' : '') + '</p>' +
      '<p class="cifra__variacion" data-variacion></p>' + (f.nota ? '<p class="cifra__nota">' + f.nota + '</p>' : '') + '</article>';
  }
  function pintarFichas(animar) {
    const modo = est && est.escenario === 'modelo' ? 'modelo' : 'hoy';
    fichasDef.forEach(function (f) {
      const art = cont.querySelector('[data-ficha="' + f.clave + '"]');
      if (!art) return;
      const x = f[modo];
      const span = art.querySelector('[data-cifra]');
      if (num(x.v)) { if (animar) global.COMPONENTES.ponerCifra(span, x.v); else { span.dataset.cifra = String(x.v); span.textContent = n(x.v, f.dec); } } else span.textContent = '—';
      const b = art.querySelector('[data-fuente-ficha]');
      if (b && x.pop) b.setAttribute('popovertarget', x.pop);
      const v = art.querySelector('[data-variacion]');
      if (modo === 'modelo' && num(f.hoy.v) && num(f.modelo.v)) {
        const dif = f.modelo.v - f.hoy.v;
        const p = f.hoy.v ? dif / f.hoy.v * 100 : null;
        const buena = f.mejorSiBaja === null || f.mejorSiBaja === undefined ? null : (f.mejorSiBaja ? dif < 0 : dif > 0);
        v.className = 'cifra__variacion' + (buena === null || dif === 0 ? '' : buena ? ' cifra__variacion--bien' : ' cifra__variacion--mal');
        v.innerHTML = icono(dif < 0 ? 'flecha-abajo' : dif > 0 ? 'flecha-arriba' : 'igual') + '<span>' + F.signo(dif, f.dec, f.unidad) + ' frente a hoy' + (num(p) ? ' (' + F.signo(p, 1, '%') + ')' : '') + '</span>';
      } else {
        v.className = 'cifra__variacion';
        v.innerHTML = icono('igual') + '<span>Lo que Sobusa programa hoy (mediana de ' + ANIO + ')</span>';
      }
    });
  }
  function seccionDiaPromedio() {
    const frase = C('horario_frase');
    const c = C(DP);
    const d = V(DP) || {};
    fichasDef = definirFichas();
    let h = '';
    h += '<p class="entradilla">' + (frase && typeof frase.valor === 'string' ? esc(frase.valor) + ' ' + fuente('horario_frase', 'frase de la diapositiva') : 'El plan quita salidas donde sobran y las pone donde faltan, con casi los mismos buses.') + '</p>';
    h += '<p class="seccion__intro">' + (c ? esc(c.que_es) + '. ' : '') + (d.juego ? 'Juego de costos: ' + esc(d.juego) + (num(d.elasticidad) ? ', elasticidad ' + n(d.elasticidad, 1) : '') + '. ' : '') +
      'El interruptor de arriba cambia las fichas entre lo que Sobusa programa hoy y lo que recomienda el modelo. ' + fuente(DP, 'día promedio de ' + ANIO) + '</p>';
    h += '<div class="cifras" id="horario-fichas">' + fichasDef.map(htmlFicha).join('') + '</div>';
    if (num(d.neto_operador_dia) || num(d.neto_social_dia)) {
      h += '<p class="texto-2 pequeno prosa">Saldo del plan en ese día promedio: ' + (num(d.neto_operador_dia) ? '<strong class="num">' + F.signo(d.neto_operador_dia * 1e-6, 1, 'M COP/día') + '</strong> para el operador ' + fuente(DP, 'neto del operador por día', ['neto_operador_dia'], null, { nota: 'El archivo trae COP por día; la pantalla lo pasa a millones.' }) : '') +
        (num(d.neto_social_dia) ? ' y <strong class="num">' + F.signo(d.neto_social_dia * 1e-6, 1, 'M COP/día') + '</strong> contando también la espera y la sobrecarga de los pasajeros ' + fuente(DP, 'neto social por día', ['neto_social_dia'], null, { nota: 'El archivo trae COP por día; la pantalla lo pasa a millones.' }) : '') +
        '. Es el día típico del planificador (medianas por hora), no el promedio de todos los días del año que usan Inicio y Resultado.</p>';
    }
    // Acciones: ir al planificador y chips de ruta (se mandan al planificador por mensaje).
    h += '<div class="horario__acciones"><button class="boton boton--primario" type="button" id="horario-ir">' + icono('flecha-abajo') + 'Ir al planificador</button>' +
      '<div class="chips" role="group" aria-label="Ruta del planificador" id="horario-chips">' +
      ['Todas'].concat(RUTAS).map(function (r) {
        return '<button class="chip" type="button" data-ruta="' + esc(r) + '" aria-pressed="false"' + (RUTA_TOKEN[r] ? ' style="--c: var(' + RUTA_TOKEN[r] + ')"' : '') + '>' + (RUTA_TOKEN[r] ? '<span class="chip__punto"></span>' : '') + esc(r) + '</button>';
      }).join('') + '</div></div>';
    return seccion('horario-dia', 'El día promedio de ' + ANIO, null, h, true);
  }

  // ---- 2. Las nueve combinaciones y la flota -----------------------------------------------------------------------
  function seccionCombinaciones() {
    const t9 = V('horario_tabla_9_combinaciones');
    let cuerpo = '';
    if (Array.isArray(t9) && t9.length) {
      const filas = t9.map(function (r, i) {
        return { datos: 'data-ruta="' + esc(r.ruta) + '"', celdas: [
          '<span class="tabla__clave"><span class="tabla__muestra" style="--c: var(' + (RUTA_TOKEN[r.ruta] || '--acento') + ')"></span>' + esc(r.ruta) + '</span>', esc(TIPO_TEXTO[r.tipo_dia] || r.tipo_dia),
          flecha(r.salidas_hoy, r.salidas_plan, 0) + ' ' + fuente('horario_tabla_9_combinaciones', r.ruta + ' ' + TIPO_TEXTO[r.tipo_dia] + ': salidas', [i, 'salidas_plan']),
          n(r.programar_plan, 0), flecha(r.buses_hora_hoy, r.buses_hora_plan, 0), flecha(r.espera_min_hoy, r.espera_min_plan, 1), flecha(r.pax_sobre_capacidad_hoy, r.pax_sobre_capacidad_plan, 0),
          num(r.pico_en_ruta) ? n(r.pico_en_ruta, 1) + ' / ' + n(r.flota, 0) : '—',
        ] };
      });
      cuerpo += tabla('Hoy → con el modelo, por ruta y tipo de día (costos con fuente, conductor por hora)', ['Ruta', 'Día', 'Salidas por día', 'A programar', 'Buses-hora', 'Espera (min)', 'Sobre capacidad', 'Pico en ruta / flota'], filas, { textoEn: [1] });
      cuerpo += '<p class="texto-2 pequeno prosa">«A programar» son las salidas que hay que poner en la programación para que, con las fallas y cancelaciones de hoy, corran las del plan. «Pico en ruta» es el máximo de buses en ruta a la vez frente a la flota disponible' + (num(V('horario_parametros_milp', ['FACTOR_FLOTA'])) ? ' (el ' + pct(V('horario_parametros_milp', ['FACTOR_FLOTA']) * 100, 0) + ' de los vehículos ' + fuente('horario_parametros_milp', 'fracción de la flota disponible', ['FACTOR_FLOTA']) + ')' : '') + '. ' + fuente('horario_tabla_9_combinaciones', 'las nueve combinaciones') + ' ' + chip('horario_tabla_9_combinaciones') + '</p>';
    } else cuerpo += '<p class="texto-2">Sin la tabla de las nueve combinaciones (horario_tabla_9_combinaciones).</p>';
    const af = C('horario_aviso_flota');
    if (af && typeof af.valor === 'string') {
      cuerpo += aviso('nota', 'Lo que dice el planificador sobre la flota (CRA 54, día laboral)', '<p>' + esc(af.valor) + ' ' + fuente('horario_aviso_flota', 'aviso de flota') + '</p>' + (af.nota ? '<p class="texto-2 pequeno">' + esc(af.nota) + '</p>' : ''));
    }
    return seccion('horario-nueve', 'Ruta por ruta y día por día', 'Las mismas cifras para cada ruta y tipo de día. Los chips de arriba cambian la ruta del planificador y resaltan sus filas.', cuerpo);
  }

  // ---- 3. Aviso de canje: con los supuestos de D5 el plan recortaba; con los costos con fuente reasigna -------------
  function seccionCanje() {
    const a = V(DP) || {};
    const s = V('horario_dia_promedio_supuestos') || {};
    const e07 = X(DP, 'con_e07') || {};
    const prod = X(DP, 'producido_e05') || {};
    const juegos = V('horario_juegos_de_costos') || {};
    const jj = juegos.juegos || {};
    const filaJuego = function (nombre, d, j, id, ruta, extraFuente) {
      return { celdas: [nombre, j ? n(j.costoBH, 0) : '—', j ? n(j.costoKm, 0) : '—', j ? n(j.tarifa, 0) : '—', num(d.elasticidad) ? n(d.elasticidad, 1) : '—',
        n(d.salidas_plan, 0) + (id ? ' ' + fuente(id, nombre + ': salidas con el plan', ruta, null, extraFuente) : ''), n(d.buses_hora_plan, 0), n(d.espera_min_plan, 1), n(d.pax_sobre_capacidad_plan, 0)] };
    };
    const filas = [];
    filas.push({ celdas: ['Hoy (lo que Sobusa programa)', '—', '—', '—', '—', n(a.salidas_hoy, 0) + ' ' + fuente(DP, 'salidas hoy', ['salidas_hoy']), n(a.buses_hora_hoy, 0), n(a.espera_min_hoy, 1), n(a.pax_sobre_capacidad_hoy, 0)] });
    filas.push(Object.assign(filaJuego('Costos con fuente, conductor por hora (la propuesta)', a, jj.hora, DP, ['salidas_plan']), { clase: 'tabla__fila-total' }));
    if (e07.salidas_plan !== undefined) filas.push(filaJuego('Costos con fuente, elasticidad alta', e07, jj.hora, null));
    if (prod.salidas_plan !== undefined) filas.push(filaJuego('Costos con fuente, conductor por producido', prod, jj.producido, null));
    filas.push(filaJuego('Supuestos de D5 (los primeros)', s, jj.d5, 'horario_dia_promedio_supuestos', ['salidas_plan']));
    const t = tabla('Dos juegos de costos, dos planes (día promedio de ' + ANIO + ')', ['Juego de costos', 'Bus-hora (COP)', 'Km (COP)', 'Tarifa (COP)', 'Elasticidad', 'Salidas/día con el plan', 'Buses-hora', 'Espera (min)', 'Sobre capacidad'], filas);
    // El día típico de D5 (supuestos): salidas hoy (k0) frente a D5, sumando las nueve combinaciones.
    const dt = V('horario_dia_tipico_d5');
    let d5txt = '';
    if (Array.isArray(dt) && dt.length) {
      const k0 = suma(dt.map(function (r) { return r.k0; })), x = suma(dt.map(function (r) { return r.x_D5; }));
      d5txt = ' En el día típico de D5 (suma de las nueve combinaciones, sin ponderar por días), el horario original pasaba de <strong class="num">' + n(k0, 0) + '</strong> a <strong class="num">' + n(x, 0) + '</strong> salidas ' + fuente('horario_dia_tipico_d5', 'día típico de D5 (k0 y x_D5 por combinación; la suma se hace en pantalla)') + '.';
    }
    const esc5 = V('horario_escenarios_d5');
    let escTxt = '';
    if (Array.isArray(esc5)) {
      const s0 = esc5.filter(function (r) { return /S0/.test(String(r.escenario)); })[0];
      const d5 = esc5.filter(function (r) { return /^D5/.test(String(r.escenario)) && /pron/i.test(String(r.escenario)); })[0] || esc5.filter(function (r) { return /^D5/.test(String(r.escenario)); })[0];
      if (s0 && d5) escTxt = ' Sobre todo' + ANIO + ', con esos supuestos, D5 (' + esc(d5.escenario) + ') daba <strong class="num">' + n(d5.salidas_dia, 0) + '</strong> salidas al día frente a <strong class="num">' + n(s0.salidas_dia, 0) + '</strong> de la oferta real, con <strong class="num">' + n(d5.pax_sobre_capacidad_dia, 0) + '</strong> pasajeros sobre la capacidad frente a <strong class="num">' + n(s0.pax_sobre_capacidad_dia, 0) + '</strong> ' + fuentes([['horario_escenarios_d5', 'escenarios de D5 (promedio de todo el año)']]) + '.';
    }
    const cuerpo = '<p>Con los supuestos iniciales de D5 (bus-hora a <strong class="num">' + n(jj.d5 && jj.d5.costoBH, 0) + '</strong> COP) cada salida costaba mucho y el plan <strong>recortaba</strong>: ' +
      '<strong class="num">' + n(s.salidas_plan, 0) + '</strong> salidas al día frente a <strong class="num">' + n(s.salidas_hoy, 0) + '</strong> de hoy, y más pasajeros de pie (<strong class="num">' + n(s.pax_sobre_capacidad_plan, 0) + '</strong> frente a <strong class="num">' + n(s.pax_sobre_capacidad_hoy, 0) + '</strong>) ' +
      fuentes([['horario_dia_promedio_supuestos', 'día promedio con los supuestos de D5'], ['horario_juegos_de_costos', 'juegos de costos', ['juegos', 'd5', 'costoBH']]]) + '.</p>' +
      '<p>Con los costos de ' + ANIO_COSTOS + ' con fuente pública (bus-hora a <strong class="num">' + n(jj.hora && jj.hora.costoBH, 0) + '</strong> COP) el mismo modelo <strong>reasigna</strong>: ' +
      '<strong class="num">' + n(a.salidas_plan, 0) + '</strong> salidas al día, casi los mismos buses-hora (<strong class="num">' + n(a.buses_hora_plan, 0) + '</strong> frente a <strong class="num">' + n(a.buses_hora_hoy, 0) + '</strong>) y menos pasajeros de pie (<strong class="num">' + n(a.pax_sobre_capacidad_plan, 0) + '</strong>) ' +
      fuentes([[DP, 'día promedio con costos con fuente'], ['horario_juegos_de_costos', 'juegos de costos', ['juegos', 'hora', 'costoBH']]]) + '.' + d5txt + escTxt + '</p>' +
      '<p class="texto-2 pequeno">Las cifras con costos con fuente no tienen revisor independiente ' + chip(DP) + '; las de D5 con los supuestos, sí ' + chip('horario_dia_tipico_d5') + '.</p>' + t;
    return seccion('horario-canje', 'El canje que cambió la propuesta', null, aviso('canje', 'Con los supuestos de D5 el plan recortaba; con los costos con fuente, reasigna', cuerpo));
  }

  // ---- 4. Qué tan cerca del óptimo (con el oráculo) ----------------------------------------------------------------
  function seccionOraculo() {
    const q5 = V('horario_calidad_decision_d5') || {};
    const hoy5 = q5.S0_oferta_real || {}, mod5 = q5.D5_pronostico || {};
    const filas5 = [
      { celdas: ['Hoy (oferta real, S0)', n(hoy5.MAE_salidas, 2) + ' ' + fuente('horario_calidad_decision_d5', 'hoy: error medio', ['S0_oferta_real', 'MAE_salidas']), pct(hoy5.pct_exactas), pct(hoy5.pct_sub_oferta), pct(hoy5.pct_sobre_oferta)] },
      { celdas: ['Con el modelo (D5 con pronóstico)', n(mod5.MAE_salidas, 2) + ' ' + fuente('horario_calidad_decision_d5', 'con el modelo: error medio', ['D5_pronostico', 'MAE_salidas']), '<span class="tabla__mejor">' + pct(mod5.pct_exactas) + '</span>', pct(mod5.pct_sub_oferta), pct(mod5.pct_sobre_oferta)], clase: 'tabla__fila-total' },
      { celdas: ['Oráculo (decide con la demanda que llegó)', '<span class="texto-3">referencia</span>', '<span class="texto-3">referencia</span>', '<span class="texto-3">—</span>', '<span class="texto-3">—</span>'] },
    ];
    const t5 = tabla('Hora a hora en ' + ANIO + ', frente al óptimo con la demanda real (D5, supuestos iniciales)', ['Quién decide', 'Error medio (salidas/h)', 'Horas con el número exacto', 'Horas con menos salidas', 'Horas con más salidas'], filas5);
    const q1 = V('horario_calidad_decision_d1') || {};
    const f1 = function (nombre, k, clase) { const r = q1[k] || {}; return { clase: clase, celdas: [nombre, n(r.MAE_salidas, 2) + ' ' + fuente('horario_calidad_decision_d1', nombre + ': error medio', [k, 'MAE_salidas']), pct(r.pct_exacto), pct(r.pct_suboferta), pct(r.pct_sobreoferta), pct(r.WAPE_salidas)] }; };
    const t1 = tabla('La regla de intervalos (D1) según el pronóstico que use, frente al oráculo', ['Quién decide', 'Error medio (salidas/h)', 'Horas exactas', 'Con menos salidas', 'Con más salidas', 'Error de salidas (WAPE)'],
      [f1('Hoy (oferta real, S0)', 'S0_real_vs_oraculo'), f1('Regla con la regla manual (B1)', 'S1_B1_manual_vs_oraculo'), f1('Regla con el pronóstico del modelo', 'S1_lightgbm_vs_oraculo', 'tabla__fila-total')]);
    const porRuta = q1.por_ruta || {};
    const filasR = RUTAS.filter(function (r) { return porRuta[r]; }).map(function (r) {
      const x = porRuta[r];
      return { celdas: ['<span class="tabla__clave"><span class="tabla__muestra" style="--c: var(' + RUTA_TOKEN[r] + ')"></span>' + esc(r) + '</span>', pct(x.S0 && x.S0.pct_exacto), pct(x.B1 && x.B1.pct_exacto), pct(x.lightgbm && x.lightgbm.pct_exacto) + ' ' + fuente('horario_calidad_decision_d1', r + ': horas exactas con el modelo', ['por_ruta', r, 'lightgbm', 'pct_exacto'])] };
    });
    const tR = filasR.length ? tabla('Horas con el número exacto de salidas, por ruta (D1)', ['Ruta', 'Hoy (S0)', 'Regla con B1', 'Regla con el modelo'], filasR) : '';
    const be = V('horario_beta_equilibrio_asimetrica_d5') || {};
    const beC = C('horario_beta_equilibrio_asimetrica_d5');
    const beD5 = be['D5 MILP (pronóstico)'];
    const beTxt = beD5 !== undefined ? '<p class="texto-2 pequeno prosa">Con los supuestos de D5 y la contabilidad asimétrica, la β de equilibrio del plan era <strong class="num">' + (num(beD5) ? n(beD5, 3) : esc(beD5)) + '</strong> ' + fuente('horario_beta_equilibrio_asimetrica_d5', 'β de equilibrio, D5 MILP (pronóstico)', ['D5 MILP (pronóstico)']) + (beC && beC.nota ? '. ' + esc(beC.nota) : '') + '</p>' : '';
    const intro = 'El oráculo decide cada hora con la demanda que de verdad llegó: nadie puede hacerlo mejor. Cuanto más se parezca una decisión a la suya, mejor. El plan del modelo acierta la hora exacta ' +
      (num(mod5.pct_exactas) && num(hoy5.pct_exactas) ? '<strong class="num">' + pct(mod5.pct_exactas) + '</strong> de las veces frente a <strong class="num">' + pct(hoy5.pct_exactas) + '</strong> de la oferta real de hoy' : 'mucho más que la oferta real de hoy') + '. El interruptor «Oráculo» no aplica a las fichas del día promedio porque no hay corrida del oráculo con los costos con fuente: aquí está su comparación.';
    return seccion('horario-oraculo', 'Qué tan cerca del óptimo', intro, t5 + t1 + tR + beTxt + '<p class="horario__pie-fuentes">' + chip('horario_calidad_decision_d5') + ' ' + chip('horario_calidad_decision_d1') + '</p>');
  }

  // ---- 5. Flota, picos y valles ------------------------------------------------------------------------------------
  function seccionFlota() {
    const fl = V('horario_flota_d2') || {};
    const pico = fl.pico_buses_oper_laboral_mediana || {}, veh = fl.vehiculos_distintos_dia_laboral || {}, req = fl.flota_requerida_85_laboral || {};
    const filasF = RUTAS.map(function (r) {
      return { celdas: ['<span class="tabla__clave"><span class="tabla__muestra" style="--c: var(' + RUTA_TOKEN[r] + ')"></span>' + esc(r) + '</span>', n(pico[r], 1) + ' ' + fuente('horario_flota_d2', r + ': pico de buses en ruta', ['pico_buses_oper_laboral_mediana', r]), n(veh[r], 0), n(req[r], 1)] };
    });
    const factorFlota = V('horario_parametros_milp', ['FACTOR_FLOTA']);
    const tF = tabla('Flota por ruta en un día laboral (D2)', ['Ruta', 'Pico de buses en ruta (mediana)', 'Vehículos distintos por día', 'Flota requerida' + (num(factorFlota) ? ' al ' + pct(factorFlota * 100, 0) : '')], filasF);
    const ed = V('horario_exceso_deficit_d2') || {};
    const cra = ed['CRA 54'] || {};
    const lab = (cra.diario && cra.diario.Laboral) || {};
    const hExc = rangos(cra.horas_exceso_laboral), hDef = rangos(cra.horas_deficit_laboral);
    const fichas = '<div class="cifras">' +
      cifraLlana('Salidas que programa hoy CRA 54 en un día laboral', n(lab.salidas, 0), 'salidas/día', 'Mediana diaria de 2023 a ' + ANIO + ' (estudio de capacidad D2).', fuente('horario_exceso_deficit_d2', 'CRA 54 laboral: salidas', ['CRA 54', 'diario', 'Laboral', 'salidas'])) +
      cifraLlana('Salidas que necesita según la carga máxima', n(lab.salidas_nec, 0), 'salidas/día', 'Para que ningún viaje pase de la ocupación máxima admisible.', fuente('horario_exceso_deficit_d2', 'CRA 54 laboral: salidas necesarias', ['CRA 54', 'diario', 'Laboral', 'salidas_nec'])) +
      cifraLlana('Salidas que sobran en el valle', n(lab.salidas_exceso, 0), 'salidas/día', hExc ? 'Horas de salida ' + esc(hExc) + ' h.' : '', fuente('horario_exceso_deficit_d2', 'CRA 54 laboral: salidas que sobran', ['CRA 54', 'diario', 'Laboral', 'salidas_exceso'])) +
      cifraLlana('Salidas que faltan en los picos', n(lab.salidas_deficit, 0), 'salidas/día', hDef ? 'Horas de salida ' + esc(hDef) + ' h.' : '', fuente('horario_exceso_deficit_d2', 'CRA 54 laboral: salidas que faltan', ['CRA 54', 'diario', 'Laboral', 'salidas_deficit'])) +
      '</div>';
    const pv = V('horario_picos_y_valles_cra54') || {};
    const esCra = function (r) { return r && r.ruta === 'CRA 54' && r.tipo_dia === 'Laboral'; };
    const faltan = (pv.faltan_demanda || []).filter(esCra), sobran = (pv.sobran || []).filter(esCra);
    const filaH = function (lista, r, i) {
      return { celdas: [n(r.hora, 0) + ' h', n(r.salidas_reales_med, 0), n(r.need_oraculo_med, 0) + ' ' + fuente('horario_picos_y_valles_cra54', 'CRA 54 laboral, ' + r.hora + ' h: salidas que necesita la demanda', [lista, i, 'need_oraculo_med']), F.signo(r.exceso_demanda_oraculo_media, 1), pct(r.pct_dias_deficit_demanda, 0)] };
    };
    const filasPV = faltan.map(function (r) { return filaH('faltan_demanda', r, (pv.faltan_demanda || []).indexOf(r)); }).concat(sobran.map(function (r) { return filaH('sobran', r, (pv.sobran || []).indexOf(r)); }));
    const tPV = filasPV.length ? tabla('CRA 54 laboral: las horas donde más faltan y más sobran salidas (D1, medianas de ' + ANIO + ')', ['Hora de salida', 'Salidas hoy', 'Salidas que necesita la demanda', 'Sobran (+) o faltan (−) en promedio', 'Días con déficit'], filasPV) : '';
    return seccion('horario-flota', 'Flota, picos y valles', 'El plan tiene que caber en la flota de cada ruta. En CRA 54 sobran salidas en el valle y faltan en los picos; las horas son de salida (rótulo de D2).', tF + fichas + tPV + '<p class="horario__pie-fuentes">' + chip('horario_flota_d2') + ' ' + chip('horario_exceso_deficit_d2') + ' ' + chip('horario_picos_y_valles_cra54') + '</p>');
  }

  // ---- 6. Ver cómo se calculó -----------------------------------------------------------------------------------------
  function seccionComoSeCalculo() {
    const partes = [];
    // Juegos de costos
    const jc = V('horario_juegos_de_costos') || {};
    if (jc.juegos) {
      const filas = Object.keys(jc.juegos).map(function (k) { const j = jc.juegos[k]; return { clase: k === jc.defecto ? 'tabla__fila-total' : '', celdas: [esc(j.nombre || k) + (k === jc.defecto ? ' (por defecto)' : ''), n(j.costoBH, 0) + ' ' + fuente('horario_juegos_de_costos', (j.nombre || k) + ': costo del bus-hora', ['juegos', k, 'costoBH']), n(j.costoKm, 0), n(j.tarifa, 0)] }; });
      partes.push('<h3>Los juegos de costos del planificador</h3>' + tabla(null, ['Juego', 'Bus-hora (COP)', 'Km (COP)', 'Tarifa neta (COP)'], filas) +
        (num(jc.participacion_producido) ? '<p class="texto-2 pequeno">Con el pago por producido el conductor recibe una participación de <strong class="num">' + pct(jc.participacion_producido * 100, 0) + '</strong> del producido ' + fuente('horario_juegos_de_costos', 'participación por producido', ['participacion_producido']) + '. ' + chip('horario_juegos_de_costos') + '</p>' : ''));
    }
    // Parámetros del MILP
    const pm = V('horario_parametros_milp');
    if (pm && typeof pm === 'object') {
      const nombres = { VALOR_TIEMPO_ESPERA: 'Valor del tiempo de espera (COP/h)', PENALIDAD_SOBRECARGA: 'Penalidad por pasajero sobre la capacidad (COP)', CAPACIDAD: 'Capacidad (pasajeros por bus)', INTERVALO_MIN: 'Intervalo mínimo (min)', INTERVALO_MAX: 'Intervalo máximo (min)', DELTA: 'Cambio máximo de salidas entre horas seguidas', HORA_INICIO_SUAVIDAD: 'Hora desde la que se suaviza', FACTOR_FLOTA: 'Fracción de la flota disponible' };
      const pares = Object.keys(pm).map(function (k) {
        const v = pm[k];
        const txt = v && typeof v === 'object' ? Object.keys(v).map(function (t) { return esc(TIPO_TEXTO[t] || t) + ' ' + n(v[t], 0); }).join(', ') : n(v, k === 'FACTOR_FLOTA' ? 2 : 0);
        return [esc(nombres[k] || k), txt + ' ' + fuente('horario_parametros_milp', nombres[k] || k, [k])];
      });
      partes.push('<h3>Los parámetros comunes del MILP de D5</h3>' + dl(pares) + '<p class="texto-2 pequeno">' + chip('horario_parametros_milp') + '</p>');
    }
    // Validación del planificador
    const vp = V('horario_validacion_planificador') || {};
    const dtp = vp.dia_tipico_por_defecto || {}, el = vp.elasticidades_D5 || {}, al = vp.MILP_aleatoria || {};
    const ccf = Array.isArray(vp.costos_con_fuente) ? vp.costos_con_fuente[0] : null;
    if (dtp.horas_total || al.casos) {
      partes.push('<h3>El planificador reproduce el MILP de D5</h3><ul class="horario__lista">' +
        (dtp.horas_total ? '<li>Día típico por defecto: <strong class="num">' + n(dtp.horas_iguales, 0) + '</strong> de <strong class="num">' + n(dtp.horas_total, 0) + '</strong> horas iguales y <strong class="num">' + n(dtp.horarios_identicos, 0) + '</strong> de <strong class="num">' + n(dtp.combinaciones, 0) + '</strong> horarios idénticos ' + fuente('horario_validacion_planificador', 'día típico por defecto', ['dia_tipico_por_defecto', 'horas_iguales']) + '.</li>' : '') +
        (el.casos ? '<li>Elasticidades de D5: <strong class="num">' + n(el.iguales, 0) + '</strong> de <strong class="num">' + n(el.casos, 0) + '</strong> casos iguales ' + fuente('horario_validacion_planificador', 'elasticidades de D5', ['elasticidades_D5', 'iguales']) + '.</li>' : '') +
        (al.casos ? '<li>Casos aleatorios del MILP: <strong class="num">' + n(al.iguales, 0) + '</strong> de <strong class="num">' + n(al.casos, 0) + '</strong> iguales; brecha máxima <strong class="num">' + pct(al.brecha_max_pct, 2) + '</strong> y media <strong class="num">' + pct(al.brecha_media_pct, 3) + '</strong>; mediana de <strong class="num">' + n(al.ms_mediana, 1) + '</strong> ms por caso ' + fuente('horario_validacion_planificador', 'casos aleatorios', ['MILP_aleatoria', 'iguales']) + '.</li>' : '') +
        (ccf ? '<li>Costos con fuente (' + esc(ccf.juego) + ', e = ' + n(ccf.elasticidad, 1) + '): <strong class="num">' + n(ccf.horas_iguales_milp, 0) + '</strong> de <strong class="num">' + n(ccf.horas_total, 0) + '</strong> horas iguales al MILP y <strong class="num">' + n(ccf.dias_identicos_milp, 0) + '</strong> de <strong class="num">' + n(ccf.casos, 0) + '</strong> días idénticos ' + fuente('horario_validacion_planificador', 'costos con fuente', ['costos_con_fuente', 0, 'horas_iguales_milp']) + '.</li>' : '') +
        '</ul><p class="texto-2 pequeno">' + chip('horario_validacion_planificador') + '</p>');
    }
    // Datos que carga la página
    const dp = V('horario_datos_planificador_js') || {};
    if (dp.param) {
      const fp = dp.fuentes_param || {};
      partes.push('<h3>Lo que carga la página del planificador</h3><p class="prosa">Insumos por ruta (' + (Array.isArray(dp.rutas) ? dp.rutas.map(esc).join(', ') : '—') + '), tipo de día y hora' + (Array.isArray(dp.campos_hora) ? ', con <strong class="num">' + n(dp.campos_hora.length, 0) + '</strong> campos por hora' : '') + '. Los parámetros que trae el archivo y de dónde sale cada uno: ' + fuente('horario_datos_planificador_js', 'datos del planificador') + '</p>' +
        dl(Object.keys(dp.param).map(function (k) { const v = dp.param[k]; return [esc(k), (v && typeof v === 'object' ? Object.keys(v).map(function (t) { return esc(t) + ' ' + n(v[t], 0); }).join(', ') : (num(v) ? n(v, v < 1 ? 2 : 0) : esc(v))) + (fp[k] ? ' <span class="texto-3">· ' + esc(fp[k]) + '</span>' : '')]; }), true) +
        '<p class="texto-2 pequeno">' + chip('horario_datos_planificador_js') + '</p>');
    }
    // Horario minuto a minuto (D5 original)
    const mm = V('horario_recomendado_minuto_a_minuto') || {};
    const mmC = C('horario_recomendado_minuto_a_minuto');
    if (Array.isArray(mm.resumen)) {
      const filas = mm.resumen.slice().sort(function (a, b) { return RUTAS.indexOf(a.ruta) - RUTAS.indexOf(b.ruta) || TIPOS.indexOf(a.tipo_dia) - TIPOS.indexOf(b.tipo_dia); }).map(function (r, i) {
        return { celdas: [esc(r.ruta), esc(TIPO_TEXTO[r.tipo_dia] || r.tipo_dia), n(r.salidas, 0) + ' ' + fuente('horario_recomendado_minuto_a_minuto', r.ruta + ' ' + TIPO_TEXTO[r.tipo_dia] + ': salidas', ['resumen', mm.resumen.indexOf(r), 'salidas']), esc(r.primera), esc(r.ultima), n(r.intervalo_min, 0) + ' a ' + n(r.intervalo_max, 0)] };
      });
      partes.push('<h3>El horario minuto a minuto de D5 (supuestos iniciales)</h3><p class="prosa">' + (num(mm.filas) ? '<strong class="num">' + n(mm.filas, 0) + '</strong> salidas en nueve combinaciones ' + fuente('horario_recomendado_minuto_a_minuto', 'filas del horario', ['filas']) : '') + (mmC && mmC.nota ? ' ' + esc(mmC.nota) : '') + '</p>' +
        tabla(null, ['Ruta', 'Día', 'Salidas', 'Primera', 'Última', 'Intervalo (min)'], filas, { textoEn: [1, 3, 4] }) + '<p class="texto-2 pequeno">' + chip('horario_recomendado_minuto_a_minuto') + '</p>');
    }
    // Día típico por hora, CRA 54 laboral
    const dth = V('horario_dia_tipico_por_hora') || {};
    const cl = dth['CRA 54 | Laboral'];
    if (cl && Array.isArray(cl.horas)) {
      const filas = cl.horas.map(function (hr, i) { return { celdas: [n(hr, 0) + ' h', n(cl.pasajeros_p50 && cl.pasajeros_p50[i], 0), n(cl.salidas_hoy[i], 0), n(cl.plan_fuente && cl.plan_fuente[i], 0), n(cl.plan_fuente_e07 && cl.plan_fuente_e07[i], 0), n(cl.d5_supuestos && cl.d5_supuestos[i], 0)] }; });
      filas.push({ clase: 'tabla__fila-total', celdas: ['Día', n(suma(cl.pasajeros_p50), 0), n(suma(cl.salidas_hoy), 0), n(suma(cl.plan_fuente), 0), n(suma(cl.plan_fuente_e07), 0), n(suma(cl.d5_supuestos), 0)] });
      partes.push('<h3>CRA 54 en un día laboral típico, hora a hora</h3><p class="prosa">Pasajeros previstos (mediana), salidas de hoy (mediana de ' + ANIO + ') y el plan con costos con fuente (elasticidad baja y alta) y con los supuestos de D5. Es lo que dibuja el planificador. ' + fuente('horario_dia_tipico_por_hora', 'CRA 54 laboral por hora', ['CRA 54 | Laboral', 'plan_fuente']) + '</p>' +
        tabla(null, ['Hora de salida', 'Pasajeros previstos', 'Salidas hoy', 'Plan (e = ' + n(V(DP, ['elasticidad']), 1) + ')', 'Plan (e alta)', 'D5 supuestos'], filas) + '<p class="texto-2 pequeno">' + chip('horario_dia_tipico_por_hora') + '</p>');
    }
    // Simulador D6, CRA 54
    const d6 = V('horario_simulador_d6') || {};
    const cra6 = d6['CRA 54'];
    if (cra6) {
      const orden = ['S0', 'S0reg', 'S1', 'D5', 'D5+R', 'D5+G'];
      const filas = orden.filter(function (k) { return cra6[k]; }).map(function (k) { const p = cra6[k]; return { clase: k === 'D5' ? 'tabla__fila-total' : '', celdas: [esc(p.etiqueta || k), n(p.salidas, 0), n(p.espera_media, 1) + ' ' + fuente('horario_simulador_d6', (p.etiqueta || k) + ': espera media', ['CRA 54', k, 'espera_media']), pct(p.pct_viajes_llenos, 1), n(p.buses_hora, 0), n(p.buses_en_ruta_pico, 1)] }; });
      partes.push('<h3>El simulador de operación (D6), CRA 54 en un día laboral típico</h3><p class="prosa">' + esc((C('horario_simulador_d6') || {}).que_es || 'Réplicas de cada política con los supuestos de D5') + ': cómo cambian la espera, los viajes llenos, los buses-hora y el pico de flota según la política.</p>' +
        tabla(null, ['Política', 'Salidas', 'Espera media (min)', 'Viajes llenos', 'Buses-hora', 'Pico de buses en ruta'], filas) + '<p class="texto-2 pequeno">' + chip('horario_simulador_d6') + '</p>');
    }
    return seccion('horario-como', 'Cómo se calculó', null, desplegable('horario-desplegable', 'Ver cómo se calculó', partes.join('')), true);
  }

  // ---- Chips de ruta y el módulo -----------------------------------------------------------------------------------
  function rutaActual() { return est && est.ruta ? est.ruta : 'Todas'; }
  function marcarRuta() {
    const r = rutaActual();
    cont.querySelectorAll('#horario-chips .chip').forEach(function (b) { b.setAttribute('aria-pressed', String(b.dataset.ruta === r)); });
    cont.querySelectorAll('tr[data-ruta]').forEach(function (tr) { tr.classList.toggle('horario__fila-elegida', r !== 'Todas' && tr.dataset.ruta === r); });
  }
  function enviarRuta() {
    const r = rutaActual();
    const m = app().modulo(ID);
    if (m && r !== 'Todas') m.enviar({ tipo: 'ruta', ruta: r });
  }
  function irAlModulo() {
    const m = app().modulo(ID);
    if (!m || !m.elemento) return;
    try { m.elemento.scrollIntoView({ behavior: reducido() ? 'auto' : 'smooth', block: 'start' }); } catch (e) { m.elemento.scrollIntoView(); }
  }
  function ligar() {
    const ir = cont.querySelector('#horario-ir');
    if (ir) ir.addEventListener('click', irAlModulo);
    const chips = cont.querySelector('#horario-chips');
    if (chips) chips.addEventListener('click', function (e) {
      const b = e.target.closest('.chip[data-ruta]');
      if (!b) return;
      if (!app().ponerEstado({ ruta: b.dataset.ruta })) { marcarRuta(); enviarRuta(); }
    });
    // Cuando el planificador avisa «listo», se le manda la ruta elegida (si no es «Todas»).
    const oyente = function (e) {
      const m = app().modulo(ID);
      if (!m || !e.data || e.source !== m.iframe.contentWindow) return;
      if (e.data.tipo === 'listo') enviarRuta();
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
    if (!C(DP)) {
      cont.innerHTML = aviso('atencion', 'Sin datos del horario', '<p>Falta app/datos_app.js o no trae las cifras de esta pantalla. El planificador, abajo, funciona igual.</p>');
      return;
    }
    const partes = [seccionDiaPromedio(), seccionCombinaciones(), seccionCanje(), seccionOraculo(), seccionFlota(), seccionComoSeCalculo()];
    const cab = faltantes.length ? aviso('atencion', 'Faltan datos en app/datos_app.js', '<p>Esta pantalla no encontró ' + n(faltantes.length, 0) + ' ids: <code>' + faltantes.map(esc).join('</code>, <code>') + '</code>. Donde faltan se muestra «—».</p>') : '';
    cont.innerHTML = '<div class="pila pila--ancha horario__cuerpo">' + cab + partes.join('') + '</div>';
    pintarFichas(false);
    marcarRuta();
    ligar();
    global.COMPONENTES.fuentes(cont);
    global.COMPONENTES.cifras(cont);
    global.setTimeout(enviarRuta, 0);
  }
  function actualizar(estado) {
    if (!cont) return;
    const antes = est || {};
    est = estado || {};
    if (antes.escenario !== est.escenario) pintarFichas(true);
    if (antes.ruta !== est.ruta) { marcarRuta(); enviarRuta(); }
  }
  function salir() {
    limpiezas.forEach(function (f) { try { f(); } catch (e) { /* nada */ } });
    limpiezas = [];
  }

  const definicion = {
    id: ID,
    pregunta: '¿Cuántos buses y cada cuánto?',
    subtitulo: function (datos) {
      D = datos || global.DATOS_APP || {};
      const d = V(DP) || {};
      if (!num(d.salidas_hoy)) return 'El horario recomendado por ruta y por hora: las mismas horas de bus, mejor repartidas.';
      return 'En un día promedio de ' + ANIO + ': de ' + n(d.salidas_hoy, 0) + ' a ' + n(d.salidas_plan, 0) + ' salidas y de ' + n(d.buses_hora_hoy, 0) + ' a ' + n(d.buses_hora_plan, 0) + ' buses-hora, con menos pasajeros de pie y casi la misma espera.';
    },
    icono: 'horario',
    // Los tooltips van cortos: el de la cabecera no parte líneas y se centra bajo la opción (en el teléfono caben unos 24 caracteres).
    interruptor: [
      { valor: 'hoy', tooltip: 'Lo que programa Sobusa' },
      { valor: 'modelo', tooltip: 'El horario recomendado' },
    ],
    tooltipInterruptor: 'Sin corrida del oráculo',
    modulo: { pagina: 'planificador.html', hash: 'plan', nombre: 'Planificador de despacho', icono: 'horario', completo: false },
    render: render,
    actualizar: actualizar,
    salir: salir,
  };
  if (typeof global.registrarPantalla === 'function') global.registrarPantalla(definicion);
  else (global.__pantallasRegistradas = global.__pantallasRegistradas || []).push(definicion);
})(window);
