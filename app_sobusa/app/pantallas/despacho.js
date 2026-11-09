// Sobusa Despacho · pantallas/despacho.js — Despacho · ¿Qué hago ahora?
// Resumen propio encima de la consola embebida (consola_despacho.html?embebido=1#dia=…&hora=…), según el wireframe de
// app/DISEÑO.md §7: lo que ve la consola a las 7:30 del día de ejemplo (despacho_pantalla_7_30), las fichas de plan,
// oferta real y motor frente al oráculo (despacho_decision_vs_oraculo_h7, con el interruptor Hoy / Con el modelo /
// Oráculo), la cobertura del intervalo, el aviso de atención (reoptimizar en el día no aporta; la corrida vigente no
// tiene revisor) y «Ver cómo se calculó» con el resto de los ids. Ninguna cifra está escrita aquí: todas salen de
// window.DATOS_APP (app/datos_app.js) y cada una lleva su botón «fuente» (clave exacta tomada de «origen» cuando existe).
//
// Ids que lee (pantalla despacho): despacho_pantalla_7_30, despacho_dia_ejemplo, despacho_decision_vs_oraculo_h7,
// despacho_decision_vs_oraculo_h4, despacho_cobertura_intervalo, despacho_nowcast_wape, despacho_backtest_muestra,
// despacho_alertas, despacho_metodo_solucion, despacho_guarda_datos, despacho_simulador_d6, despacho_verificacion_plan,
// despacho_indice_replay (despacho_latencias no existe en los archivos de resultados: no se muestra).
//
// El módulo (iframe) lo crea y lo conserva app.js a partir de «modulo» (completo: false → debajo del resumen, con la
// altura de la ventana menos la cabecera compacta). El día y la hora siguen viajando como hoy: la consola avisa
// {tipo:'estado', dia, hora}, app.js los guarda en el estado y los manda a la vista 3D de Ciudad con {tipo:'dia'};
// esta pantalla solo los lee (actualizar) para decir en qué día está la consola.
(function (global) {
  'use strict';

  const ID = 'despacho';
  const PREFIJO = 'fd-';
  const ANIO = '2025';
  const F = global.COMPONENTES.formato;
  const icono = function (nombre, clase) { return global.ICONOS.svg(nombre, clase); };
  const FINO = ' ';
  const RUTAS = ['SILENCIO', 'CRA 54', 'CL 72'];
  const RUTA_TOKEN = { 'SILENCIO': '--ruta-silencio', 'CRA 54': '--ruta-cra54', 'CL 72': '--ruta-cl72' };
  const BT = 'despacho_decision_vs_oraculo_h7';

  let D = null, cont = null, est = null, nPop = 0, faltantes = [], fichasDef = [], limpiezas = [];

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
  function muestraRuta(r) { return '<span class="tabla__clave"><span class="tabla__muestra" style="--c: var(' + (RUTA_TOKEN[r] || '--acento') + ')"></span>' + esc(r) + '</span>'; }

  // ---- Estilos propios (solo tokens) ------------------------------------------------------------------------------
  function estilos() {
    if (document.getElementById('estilos-despacho')) return;
    const st = document.createElement('style');
    st.id = 'estilos-despacho';
    st.textContent = [
      // La consola, debajo del resumen, con la altura de la ventana menos la cabecera compacta (64 px): «Ir a la consola»
      // la deja justo debajo y ocupa todo lo que queda. En el teléfono, menos la barra inferior.
      '.contenido--con-modulo > .modulo[data-modulo="despacho"]:not(.modulo--dormido) { height: calc(100dvh - 64px - var(--e-5)); min-height: 560px; margin-top: var(--e-7); scroll-margin-top: 64px; }',
      '.contenido--con-modulo > .modulo[data-modulo="despacho"] .modulo__marco { border-radius: var(--radio-l); background: var(--superficie); }',
      '@media (max-width: 760px) { .contenido--con-modulo > .modulo[data-modulo="despacho"]:not(.modulo--dormido) { height: calc(100dvh - var(--alto-pestanas-movil) - env(safe-area-inset-bottom, 0px) - 56px - var(--e-3)); min-height: 480px; scroll-margin-top: 56px; } }',
      '.despacho__acciones { display: flex; flex-wrap: wrap; align-items: center; gap: var(--e-3) var(--e-5); }',
      '.despacho__cuerpo .cifra__variacion { display: block; line-height: 1.5; text-wrap: pretty; }',
      '.despacho__cuerpo .cifra__variacion > .icono:first-child { display: inline-block; vertical-align: -2px; margin-right: 4px; }',
      '.despacho__cuerpo .tabla td .fuente, .despacho__cuerpo p .fuente, .despacho__cuerpo li .fuente, .despacho__cuerpo dd .fuente { vertical-align: middle; }',
      // Las listas clave / valor: dos columnas que pueden encoger (fr, no auto: un valor largo no ensancha la página); una sola en el teléfono.
      '.despacho__cuerpo .resumen-datos:not(.resumen-datos--apilado) { grid-template-columns: minmax(0, 1fr) minmax(0, 1.3fr); }',
      '.despacho__cuerpo .resumen-datos dd { font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }',
      '@media (max-width: 600px) { .despacho__cuerpo .resumen-datos:not(.resumen-datos--apilado) { grid-template-columns: minmax(0, 1fr); } .despacho__cuerpo .resumen-datos:not(.resumen-datos--apilado) dd { text-align: left; margin-bottom: var(--e-2); } }',
      // Las notas de los datos traen rutas de archivo largas: se parten donde haga falta para no salirse del teléfono.
      '.despacho__cuerpo p, .despacho__cuerpo li, .despacho__cuerpo dd, .despacho__cuerpo dt, .despacho__cuerpo .aviso__cuerpo, .despacho__cuerpo code { overflow-wrap: anywhere; }',
      // El cuerpo del desplegable es una rejilla implícita: su pista «auto» crecería hasta el ancho mínimo de la tabla más ancha y
      // sacaría todo del teléfono; con una pista 1fr que puede encoger, las tablas se desplazan dentro de su marco.
      '.despacho__cuerpo .desplegable__cuerpo { grid-template-columns: minmax(0, 1fr); }',
      '.despacho__cuerpo .desplegable__cuerpo > * { min-width: 0; }',
      '.despacho__lista { margin: 0; padding-left: 20px; display: grid; gap: var(--e-2); max-width: var(--ancho-texto); }',
      '.despacho__lista li { text-wrap: pretty; }',
      '.despacho__pie-fuentes { display: flex; flex-wrap: wrap; gap: var(--e-2) var(--e-3); align-items: center; font-size: var(--t-s); color: var(--tinta-3); }',
      '.despacho__base { margin: 0; font-size: var(--t-s); color: var(--tinta-2); max-width: var(--ancho-texto); text-wrap: pretty; }',
      '#despacho-fichas .cifra { grid-template-rows: auto auto 1fr; align-content: stretch; }',
      '#despacho-fichas .cifra__variacion { align-self: end; }',
      '@media (min-width: 900px) { #despacho-fichas { grid-template-columns: repeat(4, minmax(0, 1fr)); } }',
    ].join('\n');
    document.head.appendChild(st);
  }

  // ---- Backtest: los escenarios por su nombre ----------------------------------------------------------------------
  function escenariosBt(id) {
    const v = V(id) || {};
    const buscar = function (parte) { return Object.keys(v).filter(function (k) { return k.toLowerCase().indexOf(parte) >= 0; })[0] || null; };
    const k = { plan: buscar('plan semanal'), real: buscar('oferta real'), motor: buscar('con nowcast'), control: buscar('sin nowcast'), orac: buscar('oráculo') || buscar('oraculo') };
    const r = { k: k };
    Object.keys(k).forEach(function (q) { r[q] = k[q] ? v[k[q]] : null; });
    r.dias = r.plan && num(r.plan.dias) ? r.plan.dias : (r.real && num(r.real.dias) ? r.real.dias : null);
    return r;
  }
  function horasDesde(id) {
    const g = X(id, 'por_grupo');
    const f = Array.isArray(g) ? g.filter(function (x) { return x && num(x.horas_desde); })[0] : null;
    return f ? f.horas_desde : null;
  }

  // ---- 1. Lo que ve la consola a las 7:30 del día de ejemplo -----------------------------------------------------
  function seccionPantalla() {
    const p = V('despacho_pantalla_7_30') || {};
    const hora = X('despacho_pantalla_7_30', 'hora');
    const de = V('despacho_dia_ejemplo') || {};
    const fecha = de.fecha || null;
    const intro = (fecha ? 'El ' + esc(F.fechaLarga(fecha)) + (de.etiqueta ? ' (' + esc(String(de.etiqueta).toLowerCase()) + ')' : '') : 'El día de ejemplo') + (hora ? ', a las ' + esc(hhmm(hora)) : '') +
      ', la consola ve esto en cada ruta: cuántos buses hay en ruta y en patio, cuántas salidas van hechas frente al plan, cuántos pasajeros se han contado frente a los que esperaba el pronóstico, y con qué factor ajusta lo que queda del día. ' +
      (de.descripcion ? esc(de.descripcion) + ' ' : '') + fuentes([['despacho_pantalla_7_30', 'la pantalla de la consola a las ' + hhmm(hora || '')], ['despacho_dia_ejemplo', 'el día de ejemplo']]);
    const filas = RUTAS.filter(function (r) { return p[r]; }).map(function (r) {
      const x = p[r];
      return { celdas: [muestraRuta(r),
        n(x.en_ruta, 0) + ' / ' + n(x.en_patio, 0) + ' <span class="texto-3">de ' + n(x.flota, 0) + '</span> ' + fuente('despacho_pantalla_7_30', r + ': buses en ruta', [r, 'en_ruta']),
        n(x.salidas_real, 0) + ' / ' + n(x.salidas_plan, 0) + ' ' + fuente('despacho_pantalla_7_30', r + ': salidas hechas y del plan', [r, 'salidas_real']),
        n(x.pax_obs, 0) + ' / ' + n(x.pax_esp, 0) + ' ' + fuente('despacho_pantalla_7_30', r + ': pasajeros observados y esperados', [r, 'pax_obs']),
        n(x.factor, 2) + (num(x.f10) && num(x.f90) ? ' <span class="texto-3">(' + n(x.f10, 2) + ' a ' + n(x.f90, 2) + ')</span>' : '') + ' ' + fuente('despacho_pantalla_7_30', r + ': factor de ajuste', [r, 'factor']),
        esc(x.ultima_salida || '—')] };
    });
    let cuerpo = filas.length ? tabla('La consola a las ' + esc(hhmm(hora || '')) + (fecha ? ' del ' + esc(F.fecha(fecha)) : ''), ['Ruta', 'Buses en ruta / en patio', 'Salidas hechas / plan', 'Pasajeros contados / esperados', 'Factor de ajuste (f10 a f90)', 'Última salida'], filas, { textoEn: [5] }) : '<p class="texto-2">Sin la instantánea de la consola (despacho_pantalla_7_30).</p>';
    cuerpo += '<p class="texto-2 pequeno prosa">El factor de ajuste multiplica el pronóstico del resto del día por lo observado hasta esa hora, con su intervalo del 80 % (f10 a f90). Cada pocos minutos la consola vuelve a decidir las salidas de la hora siguiente con ese factor y avisa con alertas. ' + chip('despacho_pantalla_7_30') + '</p>';
    cuerpo += '<div class="despacho__acciones"><button class="boton boton--primario" type="button" id="despacho-ir">' + icono('flecha-abajo') + 'Ir a la consola</button><p class="despacho__base" id="despacho-dia-actual"></p></div>';
    return seccion('despacho-pantalla', 'Lo que ve la consola', intro, cuerpo, true);
  }
  function textoDiaActual() {
    if (!est || !est.dia) return '';
    return 'La consola, abajo, está en el ' + F.fechaLarga(est.dia) + (est.hora ? ' a las ' + hhmm(est.hora) : '') + '. Si cambias el día o la hora allí, la vista 3D de Ciudad se mueve al mismo momento.';
  }
  function pintarDiaActual() {
    const p = cont.querySelector('#despacho-dia-actual');
    if (p) p.textContent = textoDiaActual();
  }

  // ---- 2. Fichas frente al oráculo (gobernadas por el interruptor) -----------------------------------------------------
  function definirFichas() {
    const bt = escenariosBt(BT);
    const def = function (clave, etiqueta, campo, unidad, dec, mejorSiBaja, nota) {
      const parte = function (q, titulo) {
        const x = bt[q];
        return { v: x && num(x[campo]) ? x[campo] : null, pop: bt.k[q] ? popCifra(BT, etiqueta + ', ' + titulo, [bt.k[q], campo]) : null };
      };
      return { clave: clave, etiqueta: etiqueta, unidad: unidad, dec: dec, mejorSiBaja: mejorSiBaja, nota: nota,
        hoy: parte('real', 'oferta real de ' + ANIO), modelo: parte('plan', 'plan semanal'), oraculo: parte('orac', 'oráculo'), motor: parte('motor', 'motor con nowcast') };
    };
    const f = [
      def('error', 'Error medio de salidas por hora', 'error_salidas_h', 'salidas/h', 2, true, 'Cuántas salidas de más o de menos cada hora, frente a la decisión óptima con la demanda real.'),
      def('exactas', 'Horas con el número exacto de salidas', 'pct_exactas', '%', 1, false, 'Las horas en que la decisión coincide con la del oráculo.'),
      def('salidas', 'Salidas por día', 'salidas_dia', 'salidas/día', 0, null, 'Desde la hora en que arranca la consola; no es el día completo.'),
      def('buses_hora', 'Buses-hora por día', 'buses_hora_dia', 'buses-hora/día', 0, null, 'Horas de bus en ruta desde esa hora.'),
      def('espera', 'Espera media en el paradero', 'espera_min', 'min', 1, true, 'El oráculo espera un poco más: ahorra salidas donde sobran puestos.'),
      def('sobrecap', 'Pasajeros por día por encima de la capacidad', 'sobrecap_dia', 'pasajeros/día', 0, true, 'En el tramo más cargado de cada viaje.'),
      def('costo', 'Costo generalizado por día', 'costo_Mcop_dia', 'M COP/día', 1, true, 'Operación con los costos con fuente más la espera y la sobrecarga valoradas en plata.'),
    ];
    f.bt = bt;
    return f;
  }
  function htmlFicha(f) {
    return '<article class="cifra" data-ficha="' + f.clave + '"><header class="cifra__cab"><h3 class="cifra__etiqueta">' + f.etiqueta + '</h3>' +
      '<button class="fuente" type="button" popovertarget="' + (f.hoy.pop || f.modelo.pop || '') + '" aria-expanded="false" aria-label="Fuente de la cifra" data-fuente-ficha>' + icono('fuente') + '</button></header>' +
      '<p class="cifra__valor"><span class="num" data-cifra="' + (num(f.hoy.v) ? f.hoy.v : '') + '" data-decimales="' + f.dec + '">' + n(f.hoy.v, f.dec) + '</span>' + (f.unidad ? '<span class="cifra__unidad">' + esc(f.unidad) + '</span>' : '') + '</p>' +
      '<p class="cifra__variacion" data-variacion></p></article>';
  }
  function modoActual() { return est && (est.escenario === 'modelo' || est.escenario === 'oraculo') ? est.escenario : 'hoy'; }
  function pintarFichas(animar) {
    const modo = modoActual();
    fichasDef.forEach(function (f) {
      const art = cont.querySelector('[data-ficha="' + f.clave + '"]');
      if (!art) return;
      const x = f[modo];
      const span = art.querySelector('[data-cifra]');
      if (num(x.v)) { if (animar) global.COMPONENTES.ponerCifra(span, x.v); else { span.dataset.cifra = String(x.v); span.textContent = n(x.v, f.dec); } } else span.textContent = '—';
      const b = art.querySelector('[data-fuente-ficha]');
      if (b && x.pop) b.setAttribute('popovertarget', x.pop);
      const v = art.querySelector('[data-variacion]');
      const o = f.oraculo.v;
      if (modo === 'oraculo') {
        v.className = 'cifra__variacion';
        v.innerHTML = icono('igual') + '<span>La referencia: decide con la demanda que de verdad llegó.</span>';
      } else if (num(x.v) && num(o)) {
        const dif = x.v - o;
        const p = o ? dif / o * 100 : null;
        const buena = f.mejorSiBaja === null || f.mejorSiBaja === undefined || dif === 0 ? null : (f.mejorSiBaja ? dif < 0 : dif > 0);
        v.className = 'cifra__variacion' + (buena === null ? '' : buena ? ' cifra__variacion--bien' : ' cifra__variacion--mal');
        v.innerHTML = icono(dif < 0 ? 'flecha-abajo' : dif > 0 ? 'flecha-arriba' : 'igual') + '<span>' + F.signo(dif, f.dec, f.unidad === '%' ? 'puntos' : f.unidad) + ' frente al oráculo' + (num(p) && f.unidad !== '%' ? ' (' + F.signo(p, 1, '%') + ')' : '') +
          (modo === 'modelo' && num(f.motor.v) ? '; el motor con nowcast: <strong class="num">' + n(f.motor.v, f.dec) + '</strong>' : '') + '</span>';
      } else { v.className = 'cifra__variacion'; v.innerHTML = ''; }
    });
  }
  function seccionOraculo() {
    fichasDef = definirFichas();
    const bt = fichasDef.bt;
    const hd = horasDesde(BT);
    const base = 'Base: ' + (num(bt.dias) ? 'los ' + n(bt.dias, 0) + ' días' : 'los días') + ' del backtest de ' + ANIO + (num(hd) ? ', desde las ' + n(hd, 0) + ' h' : '') + ', cuando decide la consola. El interruptor de arriba elige quién decide: la oferta real de ' + ANIO + ' (Hoy), el plan semanal del modelo (Con el modelo) o el oráculo. ' + fuente(BT, 'decisiones frente al oráculo');
    let cuerpo = '<p class="despacho__base">' + base + '</p><div class="cifras" id="despacho-fichas">' + fichasDef.map(htmlFicha).join('') + '</div>';
    // Cobertura del intervalo
    const cob = C('despacho_cobertura_intervalo');
    if (cob) {
      cuerpo += '<div class="cifras">' + cifraLlana('Cobertura del intervalo del pronóstico por hora', pct(cob.valor, num(cob.decimales) ? cob.decimales : 1), '', { clase: 'cifra__variacion--mal', html: icono('alerta') + '<span>' + esc(cob.nota ? String(cob.nota).split('. ')[0] : 'El intervalo es estrecho') + '</span>' }, 'Fracción de las horas en que los pasajeros reales cayeron dentro del intervalo f10 a f90 que la consola muestra.', fuente('despacho_cobertura_intervalo', 'cobertura del intervalo')) + '</div>';
    }
    // Las cinco decisiones, lado a lado
    const orden = [['motor', 'Motor: reoptimiza cada 5 min con nowcast'], ['control', 'Motor sin nowcast (control)'], ['plan', 'Plan semanal (Con el modelo)'], ['real', 'Oferta real de ' + ANIO + ' (Hoy)'], ['orac', 'Oráculo']];
    const filas = orden.filter(function (o) { return bt[o[0]]; }).map(function (o) {
      const x = bt[o[0]];
      return { clase: o[0] === 'plan' ? 'tabla__fila-total' : '', celdas: [esc(o[1]), n(x.error_salidas_h, 2) + ' ' + fuente(BT, o[1] + ': error medio', [bt.k[o[0]], 'error_salidas_h']), pct(x.pct_exactas), pct(x.pct_sobre), pct(x.pct_sub), n(x.salidas_dia, 0), n(x.buses_hora_dia, 0), n(x.espera_min, 1), n(x.sobrecap_dia, 0), n(x.costo_Mcop_dia, 1)] };
    });
    cuerpo += desplegable('despacho-cinco', 'Las cinco decisiones, lado a lado', tabla(null, ['Quién decide', 'Error medio (salidas/h)', 'Horas exactas', 'Con más salidas', 'Con menos salidas', 'Salidas/día', 'Buses-hora/día', 'Espera (min)', 'Sobre capacidad/día', 'Costo (M COP/día)'], filas) + '<p class="texto-2 pequeno">' + chip(BT) + '</p>', true);
    return seccion('despacho-oraculo', 'Qué tan bien decide, frente al oráculo', 'El oráculo decide cada hora con la demanda que de verdad llegó: nadie puede hacerlo mejor. Cuanto más se parezca una decisión a la suya, mejor.', cuerpo);
  }

  // ---- 3. Aviso de atención: reoptimizar en el día no aporta; la corrida vigente no tiene revisor ------------------
  function seccionAtencion() {
    const bt = fichasDef.bt || escenariosBt(BT);
    const plan = bt.plan || {}, motor = bt.motor || {}, control = bt.control || {};
    const nw = V('despacho_nowcast_wape');
    const nwC = C('despacho_nowcast_wape');
    let nowTxt = '';
    if (Array.isArray(nw) && nw.length) {
      const primero = nw.slice().sort(function (a, b) { return a.corte_h - b.corte_h; })[0];
      const cal = nw.filter(function (r) { return r.corte_h === primero.corte_h && r.modo === 'calibrado'; })[0];
      const comun = nw.filter(function (r) { return r.corte_h === primero.corte_h && r.modo !== 'calibrado'; })[0];
      if (cal) nowTxt = ' El nowcast tampoco mejora el pronóstico: con corte a las ' + n(cal.corte_h, 0) + ' h, el error de la hora siguiente pasa de <strong class="num">' + pct(cal.wape_hora_semanal, 2) + '</strong> con el plan semanal a <strong class="num">' + pct(cal.wape_hora_ajustado, 2) + '</strong> ajustado y calibrado ' + fuente('despacho_nowcast_wape', 'nowcast con corte a las ' + cal.corte_h + ' h, calibrado', [nw.indexOf(cal), 'wape_hora_ajustado']) +
        (comun ? ', y sin calibrar lo empeora a <strong class="num">' + pct(comun.wape_hora_ajustado, 2) + '</strong> ' + fuente('despacho_nowcast_wape', 'nowcast sin calibrar', [nw.indexOf(comun), 'wape_hora_ajustado']) : '') + '.';
    }
    const metaNota = (D && D.meta && Array.isArray(D.meta.notas) ? D.meta.notas.filter(function (t) { return /backtest/i.test(t) && /revisor/i.test(t); })[0] : null) || (X('despacho_backtest_muestra', 'nota') || '');
    const cuerpo = '<p>Reoptimizar cada pocos minutos con lo que se va observando queda igual que seguir el plan semanal: el motor con nowcast tiene un error de <strong class="num">' + n(motor.error_salidas_h, 2) + '</strong> salidas por hora y acierta la hora exacta el <strong class="num">' + pct(motor.pct_exactas) + '</strong> de las veces, frente a <strong class="num">' + n(plan.error_salidas_h, 2) + '</strong> y <strong class="num">' + pct(plan.pct_exactas) + '</strong> del plan semanal' +
      (num(control.error_salidas_h) ? ' (sin nowcast: <strong class="num">' + n(control.error_salidas_h, 2) + '</strong>)' : '') + ' ' + fuentes([[BT, 'motor con nowcast: error medio', [bt.k.motor, 'error_salidas_h']], [BT, 'plan semanal: error medio', [bt.k.plan, 'error_salidas_h']], [BT, 'motor sin nowcast: error medio', [bt.k.control, 'error_salidas_h']]]) + '.' + nowTxt +
      ' Lo que sí aporta la consola es ver el día en marcha y avisar: huecos, apelotonamiento, sobrecupo y flota al límite.</p>' +
      // Una sola marca si las dos cifras llevan la misma (las dos son de la corrida del backtest sin revisor).
      '<p>' + esc(metaNota || 'La corrida vigente del backtest no tiene revisor independiente.') + ' ' + chip(BT) + (nwC && chip('despacho_nowcast_wape') !== chip(BT) ? ' ' + chip('despacho_nowcast_wape') : '') + '</p>';
    return seccion('despacho-atencion', 'Lo que no aporta', null, aviso('atencion', 'Reoptimizar en el día no aporta frente al plan semanal; la corrida vigente no tiene revisor', cuerpo), true);
  }

  // ---- 4. Ver cómo se calculó -----------------------------------------------------------------------------------------
  function seccionComoSeCalculo() {
    const partes = [];
    // La muestra del backtest
    const bm = V('despacho_backtest_muestra') || {};
    const mu = bm.muestra || {};
    if (mu.por_grupo) {
      const filas = Object.keys(mu.por_grupo).map(function (g) { return { celdas: [esc(g), n(mu.por_grupo[g], 0) + ' ' + fuente('despacho_backtest_muestra', 'días del grupo ' + g, ['muestra', 'por_grupo', g])] }; });
      filas.push({ clase: 'tabla__fila-total', celdas: ['Todos', n(mu.dias, 0) + ' ' + fuente('despacho_backtest_muestra', 'días del backtest', ['muestra', 'dias'])] });
      const pp = bm.plan_param || {};
      partes.push('<h3>La muestra del backtest</h3><p class="prosa"><strong class="num">' + n(mu.dias, 0) + '</strong> días de ' + ANIO + ' elegidos por grupo y <strong class="num">' + n(mu.corridas_motor, 0) + '</strong> corridas del motor ' + fuente('despacho_backtest_muestra', 'corridas del motor', ['muestra', 'corridas_motor']) +
        (pp.fuente ? '. Plan con ' + esc(pp.fuente) + ': bus-hora <strong class="num">' + n(pp.bus_hora, 0) + '</strong> COP, km <strong class="num">' + n(pp.km, 0) + '</strong> COP, tarifa <strong class="num">' + n(pp.tarifa, 0) + '</strong> COP, elasticidad <strong class="num">' + n(pp.elasticidad, 1) + '</strong> ' + fuente('despacho_backtest_muestra', 'parámetros del plan', ['plan_param']) : '') + '.</p>' +
        tabla(null, ['Grupo de días', 'Días'], filas) + '<p class="texto-2 pequeno">' + chip('despacho_backtest_muestra') + '</p>');
    }
    // Desde las 4 h (día completo)
    const b4 = escenariosBt('despacho_decision_vs_oraculo_h4');
    const hd4 = horasDesde('despacho_decision_vs_oraculo_h4');
    if (b4.plan) {
      const orden = [['motor', 'Motor con nowcast'], ['control', 'Motor sin nowcast'], ['plan', 'Plan semanal'], ['real', 'Oferta real de ' + ANIO], ['orac', 'Oráculo']];
      const filas = orden.filter(function (o) { return b4[o[0]]; }).map(function (o) { const x = b4[o[0]]; return { clase: o[0] === 'plan' ? 'tabla__fila-total' : '', celdas: [esc(o[1]), n(x.error_salidas_h, 2) + ' ' + fuente('despacho_decision_vs_oraculo_h4', o[1] + ': error medio desde las ' + hd4 + ' h', [b4.k[o[0]], 'error_salidas_h']), pct(x.pct_exactas), n(x.salidas_dia, 0), n(x.espera_min, 1), n(x.sobrecap_dia, 0), n(x.costo_Mcop_dia, 1)] }; });
      partes.push('<h3>Lo mismo contando el día completo' + (num(hd4) ? ' (desde las ' + n(hd4, 0) + ' h)' : '') + '</h3><p class="prosa">Las fichas de arriba cuentan desde la hora en que arranca la consola; aquí se cuenta desde la primera salida. Las horas exactas bajan un poco porque la salida de la flota de la madrugada es la más difícil de acertar.</p>' +
        tabla(null, ['Quién decide', 'Error medio (salidas/h)', 'Horas exactas', 'Salidas/día', 'Espera (min)', 'Sobre capacidad/día', 'Costo (M COP/día)'], filas) + '<p class="texto-2 pequeno">' + chip('despacho_decision_vs_oraculo_h4') + '</p>');
    }
    // Nowcast por hora de corte
    const nw = V('despacho_nowcast_wape');
    if (Array.isArray(nw) && nw.length) {
      const filas = nw.slice().sort(function (a, b) { return a.corte_h - b.corte_h || String(a.modo).localeCompare(String(b.modo)); }).map(function (r) {
        return { clase: r.modo === 'calibrado' ? '' : 'tabla__peor', celdas: [n(r.corte_h, 0) + ' h · ' + esc(r.modo), pct(r.wape_hora_semanal, 2), pct(r.wape_hora_ajustado, 2) + ' ' + fuente('despacho_nowcast_wape', 'corte ' + r.corte_h + ' h, ' + r.modo + ': error de la hora siguiente ajustado', [nw.indexOf(r), 'wape_hora_ajustado']), pct(r.wape_resto_dia_semanal, 2), pct(r.wape_resto_dia_ajustado, 2), pct(r.pct_ruta_dias_mejora, 1)] };
      });
      partes.push('<h3>El nowcast según la hora de corte</h3><p class="prosa">Error (WAPE) del pronóstico de la hora siguiente y del resto del día, con el plan semanal y ajustado con lo observado, calibrado o sin calibrar.</p>' +
        tabla(null, ['Corte y modo', 'Hora siguiente, semanal', 'Hora siguiente, ajustado', 'Resto del día, semanal', 'Resto del día, ajustado', 'Ruta-días que mejoran'], filas) + '<p class="texto-2 pequeno">' + chip('despacho_nowcast_wape') + '</p>');
    }
    // Alertas y método de solución
    const al = V('despacho_alertas') || {};
    const ms = V('despacho_metodo_solucion');
    let h3 = '';
    if (al.por_tipo) h3 += '<h3>' + esc((C('despacho_alertas') || {}).que_es || 'Alertas por ruta y día') + '</h3>' + dl(Object.keys(al.por_tipo).map(function (k) { return [esc(k), n(al.por_tipo[k], 2) + ' ' + fuente('despacho_alertas', 'alertas de ' + k, ['por_tipo', k])]; })) + '<p class="texto-2 pequeno">' + chip('despacho_alertas') + '</p>';
    if (ms && typeof ms === 'object') h3 += '<h3>Cómo resolvió el motor cada corrida</h3>' + dl(Object.keys(ms).map(function (k) { return [esc(k), pct(ms[k], 1) + ' ' + fuente('despacho_metodo_solucion', k, [k])]; })) + '<p class="texto-2 pequeno">' + chip('despacho_metodo_solucion') + '</p>';
    if (h3) partes.push(h3);
    // Guarda de datos
    const gd = V('despacho_guarda_datos');
    const gdC = C('despacho_guarda_datos');
    if (gd && typeof gd === 'object' && Object.keys(gd).length) {
      const filas = Object.keys(gd).sort().map(function (f) { const x = gd[f] || {}; return { celdas: [esc(F.fecha(f)), n(x.corridas, 0) + ' ' + fuente('despacho_guarda_datos', 'guarda de datos el ' + F.fecha(f), [f, 'corridas']), esc(x.primera || '—'), esc(x.ultima || '—')] }; });
      partes.push('<h3>Cuándo la guarda de datos devolvió el motor al plan</h3><p class="prosa">Si las salidas se registran tarde, el motor no confía en lo observado y vuelve al plan semanal.' + (gdC && gdC.nota ? ' ' + esc(gdC.nota) : '') + '</p>' + tabla(null, ['Día', 'Corridas con guarda', 'Primera', 'Última'], filas, { textoEn: [2, 3] }) + '<p class="texto-2 pequeno">' + chip('despacho_guarda_datos') + '</p>');
    }
    // Simulador D6
    const s6 = V('despacho_simulador_d6') || {};
    if (Array.isArray(s6.promedio) && s6.promedio.length) {
      const filas = s6.promedio.map(function (r, i) { return { clase: /plan/i.test(String(r.escenario)) ? 'tabla__fila-total' : '', celdas: [esc(r.escenario), n(r.salidas, 0), n(r.espera_media_min, 1) + ' ' + fuente('despacho_simulador_d6', r.escenario + ': espera media', ['promedio', i, 'espera_media_min']), pct(r.pct_viajes_llenos, 1), n(r.buses_hora, 0), n(r.pasajeros_dejados_acum, 0)] }; });
      partes.push('<h3>Los días de enero y febrero en el simulador de operación (D6, CRA 54)</h3><p class="prosa">El motor, el plan semanal y el oráculo pasados por el simulador: el oráculo ahorra salidas, pero deja esperar más y llena más viajes.</p>' +
        tabla(null, ['Quién decide', 'Salidas', 'Espera media (min)', 'Viajes llenos', 'Buses-hora', 'Pasajeros dejados (acumulado)'], filas) + '<p class="texto-2 pequeno">' + chip('despacho_simulador_d6') + '</p>');
    }
    // Verificación del plan y el índice del replay
    const vp = V('despacho_verificacion_plan') || {};
    const ir = V('despacho_indice_replay') || {};
    const pd = ir.por_dia || {};
    let h4 = '';
    if (num(vp.horas_iguales)) h4 += '<h3>El plan semanal se reproduce con el MILP de D5</h3><p class="prosa"><strong class="num">' + n(vp.horas_iguales, 0) + '</strong> horas iguales en <strong class="num">' + n(vp.ruta_dias, 0) + '</strong> ruta-días; <strong class="num">' + n(vp.salidas_plan, 0) + '</strong> salidas en el plan y <strong class="num">' + n(vp.salidas_ref, 0) + '</strong> en la referencia ' + fuente('despacho_verificacion_plan', 'verificación del plan', ['horas_iguales']) + '. ' + chip('despacho_verificacion_plan') + '</p>';
    if (num(pd.generados) || ir.tipo_dia) {
      h4 += '<h3>Los días que se pueden reproducir en la consola</h3><p class="prosa">' + (num(pd.generados) ? '<strong class="num">' + n(pd.generados, 0) + '</strong> días de ' + ANIO + ' generados' + (num(pd.mb_total) ? ' (' + n(pd.mb_total, 1) + ' MB)' : '') + ' ' + fuente('despacho_indice_replay', 'días generados', ['por_dia', 'generados']) : '') +
        (Array.isArray(ir.sin_gps) ? '; <strong class="num">' + n(ir.sin_gps.length, 0) + '</strong> días sin GPS no se reproducen ' + fuente('despacho_indice_replay', 'días sin GPS', ['sin_gps']) : '') + '.</p>' +
        (ir.tipo_dia ? dl(Object.keys(ir.tipo_dia).map(function (k) { return [esc(k), n(ir.tipo_dia[k], 0) + ' días']; })) : '') + '<p class="texto-2 pequeno">' + chip('despacho_indice_replay') + '</p>';
    }
    if (h4) partes.push(h4);
    // Día de ejemplo: plan, real y oráculo por hora en CRA 54
    const de = V('despacho_dia_ejemplo') || {};
    const pl = de.plan && de.plan['CRA 54'], re = de.real && de.real['CRA 54'];
    if (pl && Array.isArray(pl.salidas_hora)) {
      const filas = pl.salidas_hora.map(function (s, i) { const hr = 4 + i; return { celdas: [n(hr, 0) + ' h', n(re && re.salidas_hora && re.salidas_hora[i], 0), n(s, 0), n(pl.oraculo_hora && pl.oraculo_hora[i], 0), n(re && re.pax_hora && re.pax_hora[i], 0), n(pl.pax_plan_hora && pl.pax_plan_hora[i], 0)] }; });
      partes.push('<h3>CRA 54 el ' + esc(de.fecha ? F.fecha(de.fecha) : 'día de ejemplo') + ', hora a hora</h3><p class="prosa">Salidas reales, salidas del plan semanal y las que habría puesto el oráculo; pasajeros reales y previstos por el plan. Flota del plan: <strong class="num">' + n(pl.flota, 0) + '</strong> buses ' + fuente('despacho_dia_ejemplo', 'CRA 54: plan por hora', ['plan', 'CRA 54', 'salidas_hora']) + '.</p>' +
        tabla(null, ['Hora de salida', 'Salidas reales', 'Salidas del plan', 'Oráculo', 'Pasajeros reales', 'Pasajeros previstos'], filas) + '<p class="texto-2 pequeno">' + chip('despacho_dia_ejemplo') + '</p>');
    }
    return seccion('despacho-como', 'Cómo se calculó', null, desplegable('despacho-desplegable', 'Ver cómo se calculó', partes.join('')), true);
  }

  // ---- El módulo -----------------------------------------------------------------------------------------------------
  function irAlModulo() {
    const m = app().modulo(ID);
    if (!m || !m.elemento) return;
    try { m.elemento.scrollIntoView({ behavior: reducido() ? 'auto' : 'smooth', block: 'start' }); } catch (e) { m.elemento.scrollIntoView(); }
  }
  function ligar() {
    const ir = cont.querySelector('#despacho-ir');
    if (ir) ir.addEventListener('click', irAlModulo);
  }

  // ---- Contrato de la pantalla --------------------------------------------------------------------------------------
  function render(contenedor, datos, estado) {
    salir();
    cont = contenedor; D = datos || global.DATOS_APP || {}; est = estado || {};
    faltantes = []; nPop = 0;
    estilos();
    if (!C(BT)) {
      cont.innerHTML = aviso('atencion', 'Sin datos del despacho', '<p>Falta app/datos_app.js o no trae las cifras de esta pantalla. La consola, abajo, funciona igual.</p>');
      return;
    }
    const partes = [seccionPantalla(), seccionOraculo(), seccionAtencion(), seccionComoSeCalculo()];
    const cab = faltantes.length ? aviso('atencion', 'Faltan datos en app/datos_app.js', '<p>Esta pantalla no encontró ' + n(faltantes.length, 0) + ' ids: <code>' + faltantes.map(esc).join('</code>, <code>') + '</code>. Donde faltan se muestra «—».</p>') : '';
    cont.innerHTML = '<div class="pila pila--ancha despacho__cuerpo">' + cab + partes.join('') + '</div>';
    pintarFichas(false);
    pintarDiaActual();
    ligar();
    global.COMPONENTES.fuentes(cont);
    global.COMPONENTES.cifras(cont);
  }
  function actualizar(estado) {
    if (!cont) return;
    const antes = est || {};
    est = estado || {};
    if (antes.escenario !== est.escenario) pintarFichas(true);
    if (antes.dia !== est.dia || antes.hora !== est.hora) pintarDiaActual();
  }
  function salir() {
    limpiezas.forEach(function (f) { try { f(); } catch (e) { /* nada */ } });
    limpiezas = [];
  }

  const definicion = {
    id: ID,
    pregunta: '¿Qué hago ahora?',
    subtitulo: function (datos) {
      D = datos || global.DATOS_APP || {};
      const bt = escenariosBt(BT);
      if (!bt.plan) return 'La consola de despacho: lo que pasa en las tres rutas a esta hora y qué conviene hacer.';
      return 'Seguir el plan semanal: en ' + n(bt.dias, 0) + ' días de ' + ANIO + ' acierta la hora exacta el ' + pct(bt.plan.pct_exactas, 1) + ' de las veces (la oferta real, el ' + pct(bt.real.pct_exactas, 1) + ') y reoptimizar en el día no lo mejora. La consola muestra el día en marcha y avisa.';
    },
    icono: 'despacho',
    // Los tooltips van cortos: el de la cabecera no parte líneas y se centra bajo la opción (en el teléfono caben unos 24 caracteres).
    interruptor: [
      { valor: 'hoy', tooltip: 'La oferta real de ' + ANIO },
      { valor: 'modelo', tooltip: 'El plan semanal' },
      { valor: 'oraculo', tooltip: 'Decide con demanda real' },
    ],
    modulo: { pagina: 'consola_despacho.html', nombre: 'Consola de despacho', icono: 'despacho', completo: false,
      hash: function (e) { return 'dia=' + e.dia + '&hora=' + hhmm(e.hora); } },
    render: render,
    actualizar: actualizar,
    salir: salir,
  };
  if (typeof global.registrarPantalla === 'function') global.registrarPantalla(definicion);
  else (global.__pantallasRegistradas = global.__pantallasRegistradas || []).push(definicion);
})(window);
