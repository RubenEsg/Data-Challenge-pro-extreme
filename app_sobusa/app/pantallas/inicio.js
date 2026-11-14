// Sobusa Despacho · pantallas/inicio.js — Inicio · ¿Qué proponemos?
// Sigue el wireframe de Inicio (DISEÑO.md §7): entradilla, cifra protagonista que cuenta de «hoy» a «con el modelo»,
// cuatro fichas hoy → modelo, el problema en una imagen (barras de CRA 54 laboral), lo que gana Sobusa con sus canjes,
// β y el piloto, el hallazgo honesto, cómo se decide cada día y el pie con las fuentes de contexto.
// Todas las cifras salen de window.DATOS_APP.pantallas.inicio (ids del inventario de cifras); ningún número va escrito
// en una frase: los textos se arman aquí con las cifras. Si una cifra falta en app/datos_app.js, se muestra como
// pendiente, nunca inventada.
(function (global) {
  'use strict';

  const F = COMPONENTES.formato;
  const icono = ICONOS.svg;
  const FINO = ' '; // espacio fino antes de la unidad
  // Años del estudio (como en modelo.js): el texto no los escribe sueltos.
  const ANIO_INICIO = '2023', ANIO_PRUEBA = '2024', ANIO = '2025', ANIO_SIGUE = '2026';
  const ID_SERIE_HORAS = 'inicio_salidas_hora_cra54_laboral'; // serie por hora (hoy / plan) de CRA 54 laboral, como salidas_hora de la muestra
  const DEC = { inicio_error_regla_manual: 2, inicio_error_modelo_final: 2, inicio_error_hibrido: 2, inicio_error_e1: 2, inicio_espera_hoy: 1, inicio_espera_plan: 1, inicio_beta: 2, inicio_beta_equilibrio_d5: 2 };
  const ETIQUETA_ESC = { hoy: 'Hoy', modelo: 'Con el modelo' };

  let cont = null;
  let estado = null;
  let grafico = null;
  let vigilante = null;
  let serieHoras = null;
  let interactivas = [];

  // ---- Acceso a las cifras ---------------------------------------------------------------------------------------
  function app() { return global.app; }
  function C(id) { return app().cifra('inicio', id); }
  function CH(id) { return app().cifra('horario', id); }
  // Una parte de una cifra de otra pantalla (p. ej. una columna de una corrida), con el archivo y la clave exactos de su
  // «origen» y su marca de revisión por campo; null si el valor no está en app/datos_app.js.
  function parteDe(pantalla, id, ruta, unidadParte) {
    const e = app().cifra(pantalla, id);
    const baja = function (o) { return ruta.reduce(function (x, k) { return x && typeof x === 'object' ? x[k] : undefined; }, o); };
    const v = e ? baja(e.valor) : undefined;
    if (typeof v !== 'number' || !isFinite(v)) return null;
    const camino = ['valor'].concat(ruta).join('.');
    const o = (Array.isArray(e.origen) ? e.origen : []).filter(function (x) { return Array.isArray(x) && Array.isArray(x[0]) && x[0].join('.') === camino; })[0];
    const ref = o && o[1] && typeof o[1] === 'object' ? o[1] : null;
    const marca = baja(e.verificado_campos);
    return Object.assign({}, e, { valor: v, unidad: unidadParte, archivo: ref && ref.a ? ref.a : e.archivo, clave: ref && ref.c ? ref.c + (ref.x !== undefined && ref.x !== 1 ? ' × ' + ref.x : '') : e.clave + ' → ' + ruta.join(' → '),
      verificado: typeof marca === 'string' ? marca : e.verificado, nota: undefined });
  }
  function esNum(c) { return !!c && typeof c.valor === 'number' && isFinite(c.valor); }
  function esTexto(c) { return !!c && typeof c.valor === 'string' && c.valor.trim() !== ''; }
  function esObj(c) { return !!c && !!c.valor && typeof c.valor === 'object'; }
  function dec(id, c) { if (c && typeof c.decimales === 'number') return c.decimales; return DEC[id] !== undefined ? DEC[id] : 0; }
  function unidad(c) { return String((c && c.unidad) || '').trim().replace(/\s*\(.*\)\s*$/, ''); } // «% (WAPE, h = 7)» → «%»
  function n(v, d) { return F.numero(v, d); }
  function conU(v, d, u) { return n(v, d) + (u ? FINO + u : ''); }
  function signoU(v, d, u) { return F.signo(v, d) + (u ? FINO + u : ''); }
  function esc(s) { return String(s === undefined || s === null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'); }
  function suma(a) { return a.reduce(function (x, y) { return x + (y || 0); }, 0); }
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

  // ---- Piezas de HTML ----------------------------------------------------------------------------------------------
  function enlace(hash, texto) { return '<a class="enlace-flecha" href="#' + hash + '">' + texto + icono('flecha-derecha') + '</a>'; }
  function pendiente(etiqueta, clase) {
    return '<article class="' + (clase || 'cifra') + ' cifra--pendiente" aria-busy="true"><header class="cifra__cab"><h3 class="cifra__etiqueta">' + etiqueta + '</h3></header>' +
      '<p class="cifra__valor"><span class="cargando" aria-hidden="true"></span></p><p class="cifra__nota pendiente">Pendiente: esta cifra llega con app/datos_app.js.</p></article>';
  }
  function textoPendiente(que) { return '<span class="pendiente">Pendiente: ' + (que || 'este texto') + ' se arma con app/datos_app.js.</span>'; }
  // Ficha de cifra (numérica o de texto) con botón de fuente. Si falta, ficha pendiente.
  function ficha(id, etiqueta, o) {
    o = o || {};
    const c = C(id);
    const clase = 'cifra' + (o.clase ? ' ' + o.clase : '');
    if (!esNum(c) && !esTexto(c) && !(o.texto !== undefined && esObj(c))) return pendiente(etiqueta, clase);
    const idPop = 'f-' + id;
    app().popoverFuente(idPop, o.nota ? Object.assign({}, c, { que_mide: o.nota }) : c, o.titulo || etiqueta);
    const d = dec(id, c);
    const u = o.unidad !== undefined ? o.unidad : unidad(c);
    const valor = o.texto !== undefined
      ? '<span class="num">' + o.texto + '</span>' + (u ? '<span class="cifra__unidad">' + esc(u) + '</span>' : '')
      : esNum(c)
        ? '<span class="num" data-cifra="' + c.valor + '" data-decimales="' + d + '">' + (o.signo ? F.signo(c.valor, d) : n(c.valor, d)) + '</span>' + (u ? '<span class="cifra__unidad">' + esc(u) + '</span>' : '')
        : '<span class="cifra__valor--texto">' + esc(c.valor) + '</span>';
    return '<article class="' + clase + '" id="c-' + id + '"><header class="cifra__cab"><h3 class="cifra__etiqueta">' + etiqueta + '</h3>' + app().botonFuente(idPop) + '</header>' +
      '<p class="cifra__valor">' + valor + '</p>' +
      (o.variacion ? '<p class="cifra__variacion' + (o.variacionClase ? ' ' + o.variacionClase : '') + '">' + o.variacion + '</p>' : '') +
      (o.notaVisible ? '<p class="cifra__nota">' + o.notaVisible + '</p>' : '') + (o.pie || '') + '</article>';
  }
  // Ficha que cambia con el interruptor: hoy ↔ con el modelo (cuenta al cambiar).
  function fichaDoble(f) {
    const hoy = C(f.hoy), modelo = C(f.modelo);
    if (!esNum(hoy) || !esNum(modelo)) return pendiente(f.etiqueta, f.clase ? 'cifra ' + f.clase : 'cifra');
    app().popoverFuente('f-' + f.hoy, f.nota ? Object.assign({}, hoy, { que_mide: f.nota }) : hoy, 'hoy');
    app().popoverFuente('f-' + f.modelo, f.nota ? Object.assign({}, modelo, { que_mide: f.nota }) : modelo, 'con el modelo');
    const d = f.dec !== undefined ? f.dec : dec(f.hoy, hoy);
    interactivas.push({ id: f.id, hoy: hoy, modelo: modelo, idHoy: f.hoy, idModelo: f.modelo, dec: d, unidad: f.unidad !== undefined ? f.unidad : unidad(hoy), mejorSiBaja: f.mejorSiBaja, textoHoy: f.textoHoy, frente: f.frente, otroEnHoy: f.otroEnHoy });
    return '<article class="cifra' + (f.clase ? ' ' + f.clase : '') + '" id="c-' + f.id + '"><header class="cifra__cab"><h3 class="cifra__etiqueta">' + f.etiqueta + '</h3>' +
      '<button class="fuente" type="button" id="b-' + f.id + '" popovertarget="f-' + f.hoy + '" aria-expanded="false" aria-label="Fuente de la cifra">' + icono('fuente') + '</button></header>' +
      '<p class="cifra__valor"><span class="num" id="v-' + f.id + '" data-decimales="' + d + '"></span>' + (interactivas[interactivas.length - 1].unidad ? '<span class="cifra__unidad">' + esc(interactivas[interactivas.length - 1].unidad) + '</span>' : '') + '</p>' +
      '<p class="cifra__variacion" id="var-' + f.id + '"></p></article>';
  }
  function pintarEscenario(animar) {
    const modo = estado.escenario === 'modelo' ? 'modelo' : 'hoy';
    interactivas.forEach(function (f) {
      const c = modo === 'modelo' ? f.modelo : f.hoy;
      const el = cont.querySelector('#v-' + f.id);
      if (!el) return;
      if (animar) COMPONENTES.ponerCifra(el, c.valor); else { el.dataset.cifra = String(c.valor); el.textContent = n(c.valor, f.dec); }
      const v = cont.querySelector('#var-' + f.id);
      const dif = f.modelo.valor - f.hoy.valor;
      const pct = f.hoy.valor ? dif / f.hoy.valor * 100 : 0;
      if (modo === 'modelo') {
        const buena = f.mejorSiBaja === null || f.mejorSiBaja === undefined ? null : (f.mejorSiBaja ? dif < 0 : dif > 0);
        v.className = 'cifra__variacion' + (buena === null ? '' : buena ? ' cifra__variacion--bien' : ' cifra__variacion--mal');
        v.innerHTML = icono(dif < 0 ? 'flecha-abajo' : dif > 0 ? 'flecha-arriba' : 'igual') + signoU(dif, f.dec, f.unidad === '%' ? 'puntos' : f.unidad) + ' frente a ' + (f.frente || 'hoy') + ' (' + F.signo(pct, f.unidad === '%' ? 0 : 1, '%') + ')';
      } else if (f.otroEnHoy) {
        // La cifra protagonista no esconde la otra: en «Hoy» se ve también la del modelo, con su propia fuente.
        v.className = 'cifra__variacion cifra__variacion--bien';
        v.innerHTML = icono(dif < 0 ? 'flecha-abajo' : 'flecha-arriba') + '<span>' + f.otroEnHoy + ': <strong class="num">' + n(f.modelo.valor, f.dec) + (f.unidad === '%' ? FINO + '%' : '') + '</strong> (' + signoU(dif, f.dec, f.unidad === '%' ? 'puntos' : f.unidad) + ')</span> ' +
          app().botonFuente('f-' + f.idModelo);
      } else {
        v.className = 'cifra__variacion';
        v.innerHTML = f.textoHoy ? icono('igual') + f.textoHoy : '';
      }
      const b = cont.querySelector('#b-' + f.id);
      if (b) b.setAttribute('popovertarget', 'f-' + (modo === 'modelo' ? f.idModelo : f.idHoy));
    });
    atenuarSeries();
  }
  function fuentesTexto(pares) {
    // [[id, etiqueta], …] → botones «fuente» pequeños para los avisos con varias cifras
    // Popover propio («ft-») aunque la misma cifra tenga ficha: cada botón coloca su popover debajo de sí mismo.
    // p[0] es el id de una cifra de Inicio o, para una parte de una cifra de otra pantalla, la cifra ya armada (parteDe).
    const cif = function (p) { return typeof p[0] === 'string' ? C(p[0]) : p[0]; };
    const validos = pares.filter(function (p) { return !!cif(p); });
    if (!validos.length) return '';
    const id = 'ftl-' + (typeof validos[0][0] === 'string' ? validos[0][0] : 'parte');
    app().popoverFuentes(id, validos.map(function (p) { return [cif(p), p[1]]; }));
    return '<p class="fila">' + app().botonFuente(id, validos.length > 1 ? 'Fuentes (' + n(validos.length) + ')' : 'Fuente: ' + validos[0][1]) + '</p>';
  }

  // ---- 1 y 2. Entradilla y cifra protagonista -----------------------------------------------------------------------
  function entradilla() {
    return '<p class="lema">No quitar buses: cambiarlos de hora.</p>';
  }
  function hero() {
    const regla = C('inicio_regla_manual_definicion');
    const r = C('inicio_error_regla_manual'), m = C('inicio_error_modelo_final');
    const etiqueta = 'Pasajeros mal estimados de cada 100, a una semana';
    let principal;
    if (esNum(r) && esNum(m)) {
      app().popoverFuente('f-inicio_error_regla_manual', r, 'hoy, regla manual');
      app().popoverFuente('f-inicio_error_modelo_final', m, 'con el modelo final (E11)');
      const dif = m.valor - r.valor;
      const lado = function (quien, c, id, clase) {
        return '<div class="heroe__lado' + (clase ? ' ' + clase : '') + '"><span class="heroe__quien">' + quien + app().botonFuente('f-' + id) + '</span>' +
          '<p class="heroe__valor"><span class="num">' + n(c.valor, 2) + '</span><span class="cifra__unidad">%</span></p></div>';
      };
      const nota = 'WAPE a una semana de antelación, sobre todo ' + ANIO + ', en las tres rutas. Hoy: la regla manual de Sobusa' + (esTexto(regla) ? ' (' + esc(regla.valor).replace(/\.$/, '') + ')' : '') +
        '. Con el modelo: el modelo final (E11), la cifra oficial del proyecto. El híbrido (E12), aquí debajo, es la recomendación para producción.';
      principal = '<article class="cifra heroe__tarjeta" id="c-error"><header class="cifra__cab"><h3 class="cifra__etiqueta">' + etiqueta + '</h3></header>' +
        '<div class="heroe__par">' + lado('Hoy · regla manual', r, 'inicio_error_regla_manual', 'heroe__lado--hoy') + '<span class="heroe__flecha" aria-hidden="true">' + icono('flecha-derecha') + '</span>' +
        lado('Con el modelo final (E11)', m, 'inicio_error_modelo_final') + '</div>' +
        '<p class="cifra__variacion cifra__variacion--bien">' + icono(dif < 0 ? 'flecha-abajo' : 'flecha-arriba') + '<span>' + signoU(dif, 2, 'puntos') + ' frente a la regla manual</span></p>' +
        '<details class="desplegable desplegable--llano"><summary class="desplegable__resumen">' + icono('chevron-derecha', 'icono desplegable__chevron') + 'Cómo se mide</summary><div class="desplegable__cuerpo"><p>' + nota + '</p></div></details></article>';
    } else principal = pendiente(etiqueta, 'cifra heroe__tarjeta');
    // Debajo: el híbrido (recomendado para producción) y el primer modelo (E1).
    const hib = C('inicio_error_hibrido');
    let fila = '';
    if (esNum(hib)) {
      const m25 = C('inicio_mejora_hibrido_2025'), m24 = C('inicio_mejora_hibrido_2024');
      const partes = [];
      if (m25) partes.push('en ' + ANIO + ', ' + textoMejora(m25));
      if (m24) partes.push('en ' + ANIO_PRUEBA + ', fuera de la muestra de selección, ' + textoMejora(m24));
      const extra = [];
      if (m25) extra.push(['inicio_mejora_hibrido_2025', 'mejora frente al modelo final, ' + ANIO]);
      if (m24) extra.push(['inicio_mejora_hibrido_2024', 'mejora frente al modelo final, ' + ANIO_PRUEBA]);
      fila += ficha('inicio_error_hibrido', 'Híbrido (E12): LightGBM con las variables de Chronos-2', { clase: 'cifra--media', unidad: '%',
        variacion: '<span class="cifra__destacado">Recomendado para producción</span>',
        notaVisible: partes.length ? 'Frente al modelo final: ' + partes.join('; ') + '.' : '',
        nota: 'La cifra oficial del modelo es la del final (E11); el híbrido es la recomendación para producción.', pie: fuentesTexto(extra) });
    } else fila += pendiente('Híbrido (E12), recomendado para producción', 'cifra cifra--media');
    fila += ficha('inicio_error_e1', 'Primer modelo (E1)', { clase: 'cifra--media', unidad: '%', nota: 'LightGBM con calendario y demanda reciente, antes de las mejoras de E11.' });
    return '<section class="heroe" aria-labelledby="heroe-t">' + entradilla() + '<h2 class="oculto" id="heroe-t">La cifra principal</h2>' + principal + '<div class="cifras">' + fila + '</div></section>';
  }
  function textoMejora(c) {
    if (esTexto(c)) return esc(c.valor);
    if (esNum(c)) {
      const d = dec('', c) || 2;
      const extra = [];
      if (typeof c.ic_inf === 'number' && typeof c.ic_sup === 'number') extra.push('IC 95' + FINO + '%: ' + F.signo(c.ic_inf, d) + ' a ' + F.signo(c.ic_sup, d));
      if (typeof c.meses_mejor === 'number') extra.push('mejor en ' + n(c.meses_mejor) + (typeof c.meses === 'number' ? ' de ' + n(c.meses) : '') + ' meses');
      return signoU(c.valor, d, 'puntos') + (extra.length ? ' (' + extra.join('; ') + ')' : '');
    }
    if (esObj(c)) {
      const v = c.valor;
      const d = typeof v.dif === 'number' ? v.dif : typeof v.dif_pp === 'number' ? v.dif_pp : null;
      if (d === null) return '';
      let t = signoU(d, 2, 'puntos');
      if (typeof v.ic_inf === 'number' && typeof v.ic_sup === 'number') t += ' [' + F.signo(v.ic_inf, 2) + '; ' + F.signo(v.ic_sup, 2) + ']';
      if (typeof v.meses_mejor === 'number') t += '; mejor en ' + n(v.meses_mejor) + ' meses';
      return t;
    }
    return '';
  }

  // ---- 3. Cuatro fichas hoy → con el modelo ---------------------------------------------------------------------------
  function fichasDia() {
    return '<section class="seccion" aria-label="Un día promedio de ' + ANIO + ', hoy y con el modelo"><div class="seccion__cab"><h2 class="seccion__titulo">Un día promedio de ' + ANIO + ', hoy y con el modelo</h2><span class="texto-3 pequeno">Promedio de todos los días del año, tres rutas (viajes válidos). En «Hoy», lo que Sobusa programó en ' + ANIO + ' (oferta real); el interruptor cambia las fichas.</span></div><div class="cifras">' +
      fichaDoble({ id: 'salidas', hoy: 'inicio_salidas_dia_hoy', modelo: 'inicio_salidas_dia_plan', etiqueta: 'Salidas válidas por día', dec: 0, mejorSiBaja: null, nota: 'El plan reasigna: casi las mismas salidas, en otras horas.' }) +
      fichaDoble({ id: 'buses', hoy: 'inicio_buses_hora_hoy', modelo: 'inicio_buses_hora_plan', etiqueta: 'Buses-hora por día', dec: 0, mejorSiBaja: true, nota: 'Horas de bus en ruta, que se pagan al conductor.' }) +
      fichaDoble({ id: 'espera', hoy: 'inicio_espera_hoy', modelo: 'inicio_espera_plan', etiqueta: 'Espera media en el paradero', dec: 1, mejorSiBaja: true, nota: 'Intervalo del punto medio con la irregularidad observada.' }) +
      fichaDoble({ id: 'sobrecap', hoy: 'inicio_sobrecapacidad_hoy', modelo: 'inicio_sobrecapacidad_plan', etiqueta: 'Pasajeros por día por encima de la capacidad', dec: 0, mejorSiBaja: true, nota: 'En el tramo más cargado de cada viaje.' }) +
      '</div></section>';
  }

  // ---- 4. El problema en una imagen ---------------------------------------------------------------------------------------
  function serieDe(c) {
    if (!c) return null;
    const s = c.valor && typeof c.valor === 'object' && c.valor.horas ? Object.assign({}, c.valor) : c;
    if (typeof s.total_hoy !== 'number' && typeof c.total_hoy === 'number') s.total_hoy = c.total_hoy;
    if (typeof s.total_plan !== 'number' && typeof c.total_plan === 'number') s.total_plan = c.total_plan;
    return Array.isArray(s.horas) && Array.isArray(s.hoy) && Array.isArray(s.plan) ? s : null;
  }
  function problema() {
    const frase = CH('horario_frase');
    const c = C(ID_SERIE_HORAS);
    serieHoras = serieDe(c);
    let h = '<section class="seccion" id="inicio-problema"><div class="seccion__cab"><h2 class="seccion__titulo">El problema en una imagen</h2><span class="texto-3 pequeno">CRA 54 en un día laboral: sobran salidas en el valle y faltan en los picos</span></div>';
    h += '<p class="seccion__intro">' + (esTexto(frase) ? esc(String(frase.valor).replace(/\s*\([^)]*e = [^)]*\)/, ' (costos de ' + ANIO_SIGUE + ' con fuente pública y conductor pagado por hora)')) : 'El plan quita salidas donde sobran y las pone donde faltan, con casi los mismos buses.') + '</p>';
    if (serieHoras) {
      const s = serieHoras;
      const fh = s.fuente_hoy || c, fp = s.fuente_plan || c;
      app().popoverFuente('f-horas', { archivo: [fh.archivo, fp.archivo].filter(function (x, i, a) { return x && a.indexOf(x) === i; }).join(' y '), clave: 'Hoy: ' + (fh.clave || '') + '. Plan: ' + (fp.clave || ''),
        experimento: fp.experimento || fh.experimento, verificado: fp.verificado || c.verificado, revision: fp.revision || c.revision }, 'salidas por hora');
      const totalHoy = typeof s.total_hoy === 'number' ? s.total_hoy : suma(s.hoy);
      const totalPlan = typeof s.total_plan === 'number' ? s.total_plan : suma(s.plan);
      h += '<figure class="grafico" id="g-horas"><figcaption class="grafico__cab"><div class="grafico__titulos"><h3 class="grafico__titulo">' + esc(s.titulo || 'CRA 54, día laboral típico: salidas por hora') + '</h3>' +
        '<p class="grafico__sub">Salidas por hora de salida: lo que Sobusa programa hoy (gris) y lo que recomienda el plan (acento). El interruptor resalta un escenario.</p></div>' +
        '<div class="grafico__acciones"><button class="boton boton--secundario boton--pequeno" type="button" data-ver-tabla data-texto-tabla="Ver tabla" data-texto-grafico="Ver gráfico">' + icono('tabla') + '<span data-texto>Ver tabla</span></button></div></figcaption>' +
        '<ul class="leyenda" id="ley-horas"></ul>' +
        '<div class="grafico__lienzo" id="lienzo-horas" role="img" aria-label="Barras: salidas por hora en CRA 54 un día laboral, hoy y con el modelo"></div>' +
        '<div class="grafico__tabla tabla-marco" hidden>' + tablaHoras(s, totalHoy, totalPlan) + '</div>' +
        '<div class="grafico__pie"><span>Hoy: ' + n(totalHoy) + ' salidas al día (mediana de ' + ANIO + ' por hora); con el modelo: ' + n(totalPlan) + '.</span>' + app().botonFuente('f-horas', 'Fuente') + '</div></figure>';
    } else {
      h += '<div class="tarjeta pila"><span class="rotulo">Salidas por hora, CRA 54 laboral</span>' + textoPendiente('el gráfico de salidas por hora (' + ID_SERIE_HORAS + ')') + '</div>';
    }
    // Picos y valles con las cifras de D2 (mediana diaria 2023-2025) y sus horas de salida (contradicción C14: rótulo de D2).
    const sobran = C('inicio_salidas_sobran_cra54'), faltan = C('inicio_salidas_faltan_cra54');
    const d2 = CH('horario_exceso_deficit_d2');
    const d2cra = esObj(d2) && d2.valor['CRA 54'] ? d2.valor['CRA 54'] : null;
    const hExc = rangos((sobran && sobran.horas) || (d2cra && d2cra.horas_exceso_laboral));
    const hDef = rangos((faltan && faltan.horas) || (d2cra && d2cra.horas_deficit_laboral));
    h += '<div class="cifras">' +
      ficha('inicio_salidas_cra54_laboral_hoy', 'Salidas que programa hoy CRA 54 en un día laboral', { clase: 'cifra--llana', nota: 'Mediana de los días laborales de ' + ANIO_INICIO + ' a ' + ANIO + ', del estudio de capacidad. El gráfico de arriba usa solo ' + ANIO + ': por eso las dos cifras no coinciden.' }) +
      ficha('inicio_salidas_cra54_laboral_necesarias', 'Salidas que necesita según la carga máxima', { clase: 'cifra--llana', nota: 'Las que harían falta para que ningún viaje pase de la ocupación máxima admisible (mismo periodo). Es una cota del estudio de capacidad, no el plan: el plan pesa el costo de cada salida frente a los pasajeros que gana y por eso propone menos.' }) +
      ficha('inicio_salidas_sobran_cra54', 'Salidas que sobran en el valle', { clase: 'cifra--llana', variacion: hExc ? 'Horas de salida ' + hExc : 'En las horas de valle' }) +
      ficha('inicio_salidas_faltan_cra54', 'Salidas que faltan en los picos', { clase: 'cifra--llana', variacion: hDef ? 'Horas de salida ' + hDef : 'En las horas pico' }) +
      '</div>' + enlace('horario', 'Ver el horario recomendado hora a hora') + '</section>';
    return h;
  }
  function tablaHoras(s, totalHoy, totalPlan) {
    let h = '<table class="tabla tabla--compacta"><caption>Salidas por hora de salida, CRA 54 laboral</caption><thead><tr><th scope="col">Hora de salida</th><th scope="col" class="num">Hoy</th><th scope="col" class="num">Con el modelo</th><th scope="col" class="num">Diferencia</th></tr></thead><tbody>';
    s.horas.forEach(function (hr, i) { h += '<tr><td>' + esc(hr) + ' h</td><td class="num">' + n(s.hoy[i]) + '</td><td class="num">' + n(s.plan[i]) + '</td><td class="num">' + F.signo(s.plan[i] - s.hoy[i], 0) + '</td></tr>'; });
    h += '<tr class="tabla__fila-total"><td>Día</td><td class="num">' + n(totalHoy) + '</td><td class="num">' + n(totalPlan) + '</td><td class="num">' + F.signo(totalPlan - totalHoy, 0) + '</td></tr>';
    return h + '</tbody></table>';
  }
  function opcionBarras() {
    const s = serieHoras;
    return {
      legend: { show: false, data: [ETIQUETA_ESC.hoy, ETIQUETA_ESC.modelo] },
      tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, valueFormatter: function (v) { return n(v) + ' salidas'; } },
      xAxis: { type: 'category', data: s.horas.map(function (hr) { return hr + ' h'; }), axisLabel: { interval: 1 } },
      yAxis: { type: 'value', name: 'salidas/h', nameLocation: 'end', nameGap: 12 },
      series: [
        Object.assign({ name: ETIQUETA_ESC.hoy, type: 'bar', data: s.hoy }, TEMA_ECHARTS.serie('hoy')),
        Object.assign({ name: ETIQUETA_ESC.modelo, type: 'bar', data: s.plan }, TEMA_ECHARTS.serie('modelo')),
      ],
    };
  }
  function atenuarSeries() {
    if (!grafico) return;
    const modo = estado.escenario === 'modelo' ? 'modelo' : 'hoy';
    grafico.setOption({ series: [{ itemStyle: { opacity: modo === 'hoy' ? 1 : 0.4 } }, { itemStyle: { opacity: modo === 'modelo' ? 1 : 0.4 } }] });
  }
  function dibujarGrafico() {
    const el = cont && cont.querySelector('#lienzo-horas');
    if (!el || !serieHoras) return;
    if (grafico) { grafico.dispose(); grafico = null; }
    grafico = TEMA_ECHARTS.init(echarts, el);
    grafico.setOption(opcionBarras());
    atenuarSeries();
    const t = TEMA_ECHARTS.tokens();
    const ul = cont.querySelector('#ley-horas');
    ul.innerHTML = [{ nombre: ETIQUETA_ESC.hoy, color: t.serieHoy }, { nombre: ETIQUETA_ESC.modelo, color: t.serieModelo }].map(function (it) {
      return '<li><button class="leyenda__item" type="button" data-serie="' + it.nombre + '" aria-pressed="true"><span class="leyenda__muestra leyenda__muestra--barra" style="--c: ' + it.color + '"></span>' + it.nombre + '</button></li>';
    }).join('');
    COMPONENTES.leyenda(ul, function () { return grafico; });
    if (!vigilante) { vigilante = new ResizeObserver(function () { if (grafico) grafico.resize(); }); }
    vigilante.observe(el);
  }

  // ---- 5. Lo que gana Sobusa (con los canjes) ---------------------------------------------------------------------------
  function gana() {
    const ahorro = C('inicio_ahorro_operativo_plan'), riesgo = C('inicio_pax_riesgo_plan'), cons = C('inicio_saldo_conservador'), sim = C('inicio_saldo_simetrico'), netos = C('inicio_pax_netos_simetrica');
    const paxDia = C('inicio_pax_dia_2025'), beta = C('inicio_beta');
    const d5 = C('inicio_recorte_no_paga_d5'), s1 = C('inicio_recorte_no_paga_s1'), dom = C('inicio_domingos_pagan');
    // El plan que recorta con la contabilidad simétrica: la misma corrida que muestra Resultado (d5_reoptimizado.csv).
    const simA = parteDe('resultado', 'resultado_d5_reoptimizado', ['a_D5_original', 'neto_simetrico_Mcop'], 'M COP/año');
    const netosA = parteDe('resultado', 'resultado_d5_reoptimizado', ['a_D5_original', 'pax_netos_simetrico_dia'], 'pasajeros netos por día');
    let h = '<section class="seccion" id="inicio-gana"><div class="seccion__cab"><h2 class="seccion__titulo">Lo que gana Sobusa</h2><span class="texto-3 pequeno">Plan que reasigna, costos de fuente pública de ' + ANIO_SIGUE + ', conductor pagado por hora</span></div>';
    h += '<div class="cifras">' +
      ficha('inicio_ahorro_operativo_plan', 'Ahorro en operación al año', { signo: true, nota: 'Kilómetros y horas de conductor que deja de pagar.' }) +
      ficha('inicio_pax_riesgo_plan', 'Pasajeros en riesgo por día', { variacion: esNum(riesgo) && esNum(paxDia) && paxDia.valor ? n(riesgo.valor / paxDia.valor * 100, 1) + FINO + '% de los ' + n(paxDia.valor) + ' pasajeros diarios de ' + ANIO : '', nota: 'Contabilidad conservadora: solo los perdidos donde se quitan salidas.' }) +
      ficha('inicio_saldo_conservador', 'Saldo anual si las salidas nuevas no atraen a nadie (contabilidad conservadora)', { signo: true, nota: 'Ahorro de operación menos pasajes perdidos donde se quitan salidas, sin contar ninguno ganado. Es lo que dejaría aplicar el plan sin medir, y por eso se mide antes.' }) +
      ficha('inicio_saldo_simetrico', 'Saldo anual si atraen lo mismo que se pierde al quitar (contabilidad simétrica)', { signo: true, nota: 'Suma también los pasajes ganados donde se añaden salidas, con la misma β, que al añadir salidas no se ha medido.' }) +
      '</div>';
    // Aviso de canje: las dos contabilidades.
    if (esNum(cons) && esNum(sim)) {
      h += '<div class="aviso aviso--canje">' + icono('canje') + '<div class="aviso__cuerpo"><h3 class="aviso__titulo">Canje: el saldo depende de los pasajeros, y por eso se mide antes</h3>' +
        '<p>Conservadora: solo cuenta los pasajes perdidos donde se quitan salidas, y el saldo queda en ' + signoU(cons.valor, 0, unidad(cons)) + '. Simétrica: suma también los pasajeros ganados donde se añaden salidas' +
        (esNum(netos) ? ' (' + signoU(netos.valor, 0, 'pasajeros netos por día') + ')' : '') + ', y el saldo pasa a ' + signoU(sim.valor, 0, unidad(sim)) + '.' +
        (esNum(ahorro) ? ' El ahorro de operación es el mismo en las dos: ' + conU(ahorro.valor, 0, unidad(ahorro)) + '.' : '') + (esNum(beta) ? ' Las dos usan β = ' + n(beta.valor, 2) + '.' : '') + ' Ninguna es un pronóstico, y no hay base para decir cuál es más probable: cuántos pasajeros atraen las salidas añadidas nunca se ha medido. Por eso el plan no se aplica a ciegas: primero el piloto, y solo se adopta si las salidas añadidas atraen suficientes pasajeros (el umbral y lo que cuesta el piloto están en el tablero, Inicio).</p>' +
        fuentesTexto([['inicio_saldo_conservador', 'conservadora'], ['inicio_saldo_simetrico', 'simétrica'], ['inicio_pax_netos_simetrica', 'pasajeros netos'], ['inicio_ahorro_operativo_plan', 'ahorro']]) + '</div></div>';
    } else h += '<div class="aviso aviso--canje">' + icono('canje') + '<div class="aviso__cuerpo"><h3 class="aviso__titulo">Canje: el saldo depende de los pasajeros, y por eso se mide antes</h3><p>' + textoPendiente('el aviso') + '</p></div></div>';
    // Segundo aviso: con la contabilidad conservadora recortar no paga; al lado, el saldo simétrico del plan que recorta.
    if (esNum(d5) || esNum(s1) || esTexto(dom)) {
      let p = '';
      if (esNum(d5)) p += 'El plan que recorta (el del primer optimizador, con sus supuestos de costos, revalorado con los costos de fuente pública) deja ' + signoU(d5.valor, 0, unidad(d5)) +
        (esNum(simA) ? ' (' + signoU(simA.valor, 0, unidad(simA)) + ' con la simétrica' + (esNum(netosA) ? ', pero ' + signoU(netosA.valor, 0, unidad(netosA)) : '') + ')' : '') + '. ';
      if (esNum(s1)) p += 'Una regla fija de recorte (la misma proporción de salidas menos en todas las horas) deja ' + signoU(s1.valor, 0, unidad(s1)) + '. ';
      if (esTexto(dom)) p += 'Solo los domingos y festivos pagan: ' + esc(dom.valor) + '.';
      else if (esNum(dom)) p += 'Solo los domingos y festivos pagan: ' + signoU(dom.valor, 0, unidad(dom)) + '.';
      h += '<div class="aviso aviso--canje">' + icono('canje') + '<div class="aviso__cuerpo"><h3 class="aviso__titulo">Con la contabilidad conservadora, recortar no paga; reasignar sí cambia el día</h3><p>' + p + '</p>' +
        fuentesTexto([['inicio_recorte_no_paga_d5', 'plan que recorta'], [simA, 'plan que recorta, contabilidad simétrica'], [netosA, 'plan que recorta, pasajeros netos (simétrica)'], ['inicio_recorte_no_paga_s1', 'regla fija de recorte'], ['inicio_domingos_pagan', 'domingos y festivos']]) + '</div></div>';
    } else h += '<div class="aviso aviso--canje">' + icono('canje') + '<div class="aviso__cuerpo"><h3 class="aviso__titulo">Con la contabilidad conservadora, recortar no paga</h3><p>' + textoPendiente('el aviso') + '</p></div></div>';
    h += enlace('resultado', 'Ver el resultado completo') + '</section>';
    return h;
  }

  // ---- 6. β y el piloto ---------------------------------------------------------------------------------------------------
  function betaYPiloto() {
    const beta = C('inicio_beta'), equilibrio = C('inicio_beta_equilibrio_d5'), origen = C('inicio_beta_origen'), derrame = C('inicio_beta_derrame'), piloto = C('inicio_piloto_resumen');
    const rango = C('inicio_beta_rango'), porHora = C('inicio_beta_hora');
    const rangoTxt = esObj(rango) && typeof rango.valor.inf === 'number' && typeof rango.valor.sup === 'number' ? n(rango.valor.inf, 2) + ' a ' + n(rango.valor.sup, 2) : undefined;
    let h = '<section class="seccion" id="inicio-beta"><div class="seccion__cab"><h2 class="seccion__titulo">β y el piloto</h2><span class="texto-3 pequeno">Cuántos pasajeros se pierden al quitar salidas, y cómo comprobarlo en la calle</span></div>';
    h += '<div class="cifras">' +
      ficha('inicio_beta', 'Elasticidad β', { unidad: '', nota: 'Si una franja pierde una parte de sus salidas, pierde β veces esa parte de sus pasajeros.' }) +
      ficha('inicio_beta_rango', 'Rango creíble de β', { unidad: '', texto: rangoTxt }) +
      ficha('inicio_beta_hora', 'β por hora (variables instrumentales)', { unidad: '', variacion: esNum(porHora) && typeof porHora.ic_inf === 'number' ? 'Intervalo de 95 %: ' + n(porHora.ic_inf, 2) + ' a ' + n(porHora.ic_sup, 2) : '' }) +
      ficha('inicio_beta_equilibrio_d5', 'β de equilibrio del plan que recorta', { unidad: '', nota: 'Por encima de esta β, el plan que recorta deja de pagar.' }) +
      '</div>';
    if (origen) {
      let p = 'β se midió con viajes registrados que no salieron (fallas sin aviso): ' + (esTexto(origen) ? esc(origen.valor) : esNum(origen) ? conU(origen.valor, 0, 'viajes') + (typeof origen.pct === 'number' && typeof origen.viajes_registrados === 'number' ? ', el ' + n(origen.pct, 1) + FINO + '% de los ' + n(origen.viajes_registrados) + ' registrados' : '') : '') + '. Un recorte planificado y anunciado puede perder menos pasajeros, o más: por eso el piloto.';
      if (esObj(derrame) && typeof derrame.valor.bruto_pct === 'number') p += ' De los ' + n(derrame.valor.pax_esperados_viaje_fallido, 1) + ' pasajeros esperados en un viaje que falló, los buses siguientes recogen el ' + n(derrame.valor.bruto_pct, 1) + FINO + '% (' + n(derrame.valor.corregido_pct, 1) + FINO + '% descontando la tendencia previa).';
      h += '<div class="aviso aviso--atencion">' + icono('alerta') + '<div class="aviso__cuerpo"><h3 class="aviso__titulo">Atención: β se midió con fallas, no con recortes planificados</h3><p>' + p + '</p>' + (origen.nota ? '<p class="texto-2">' + esc(origen.nota) + '</p>' : '') +
        fuentesTexto([['inicio_beta_origen', 'fallas'], ['inicio_beta_derrame', 'derrame']]) + '</div></div>';
    } else h += '<div class="aviso aviso--atencion">' + icono('alerta') + '<div class="aviso__cuerpo"><h3 class="aviso__titulo">Atención: β se midió con fallas, no con recortes planificados</h3><p>' + textoPendiente('el aviso') + '</p></div></div>';
    if (esObj(piloto)) {
      const v = piloto.valor;
      app().popoverFuente('f-inicio_piloto_resumen', piloto, 'piloto');
      let p = 'Piloto de ' + n(v.semanas) + ' semanas en la calle para medir β con recortes planificados.';
      if (typeof v.potencia_simulada === 'number') p += ' Potencia de ' + n(v.potencia_simulada * 100, 0) + FINO + '% (simulada)' + (typeof v.potencia_analitica === 'number' ? ' y ' + n(v.potencia_analitica * 100, 0) + FINO + '% (analítica)' : '') + ' para distinguir' + (esNum(beta) && esNum(equilibrio) ? ' β = ' + n(beta.valor, 2) + ' de ' + n(equilibrio.valor, 2) : ' la β medida de la de equilibrio') + '.';
      if (typeof v.pax_riesgo === 'number') p += ' Pasajeros en riesgo durante el piloto: ' + n(v.pax_riesgo) + (typeof v.pct_pax_anual_cra54 === 'number' ? ' (' + n(v.pct_pax_anual_cra54, 1) + FINO + '% de los de CRA 54 en un año)' : '') + '.';
      if (typeof v.saldo_min_Mcop === 'number' && typeof v.saldo_max_Mcop === 'number') p += ' Saldo del piloto entre ' + F.signo(v.saldo_min_Mcop, 1) + ' y ' + signoU(v.saldo_max_Mcop, 1, 'M COP') + ' según la contabilidad.';
      p += ' ' + frasePilotoDecide(beta, equilibrio);
      h += '<div class="tarjeta pila"><h3>Cómo lo comprobamos</h3><p class="prosa">' + p + '</p><div class="fila">' + enlace('piloto', 'Ver el piloto de ' + n(v.semanas) + ' semanas') + app().botonFuente('f-inicio_piloto_resumen', 'Fuente') + app().chipVerificado(piloto.verificado) + '</div></div>';
    } else h += '<div class="tarjeta pila"><h3>Cómo lo comprobamos</h3><p>' + textoPendiente('el resumen del piloto') + '</p>' + enlace('piloto', 'Ver el piloto') + '</div>';
    return h + '</section>';
  }

  // Qué decide el piloto para la propuesta (reasignar) y qué mide peor: la β de las salidas añadidas.
  function frasePilotoDecide(beta, equilibrio) {
    const pot = app().cifra('piloto', 'piloto_potencia');
    const v = pot && pot.valor && typeof pot.valor === 'object' ? pot.valor : null;
    const f1 = v && v.F1 && typeof v.F1.potencia_070_vs_053_una_cola === 'number' ? v.F1.potencia_070_vs_053_una_cola : null;
    const f2 = v && v.F2 && typeof v.F2.potencia_070_vs_053_una_cola === 'number' ? v.F2.potencia_070_vs_053_una_cola : null;
    let t = 'Para la propuesta, que reasigna, lo que decide es otra cosa: cuántos pasajeros atraen las salidas añadidas en los picos. El piloto también lo mide, en dos franjas de refuerzo, pero con menos precisión';
    if (f1 !== null && f2 !== null) {
      app().popoverFuente('f-piloto_potencia_refuerzos', pot, 'potencia en las franjas de refuerzo');
      t += ' (potencia de ' + n(f1 * 100, 0) + FINO + '% y ' + n(f2 * 100, 0) + FINO + '% para distinguir' + (esNum(beta) && esNum(equilibrio) ? ' β = ' + n(beta.valor, 2) + ' de ' + n(equilibrio.valor, 2) : ' las dos β') + ') ' + app().botonFuente('f-piloto_potencia_refuerzos');
    }
    return t + '. Si las salidas añadidas atraen pocos pasajeros, el saldo del plan se acerca al de la cuenta conservadora, que es negativo, y lo prudente es no cambiar el horario.';
  }

  // ---- 7. Hallazgo honesto ------------------------------------------------------------------------------------------------
  function hallazgo() {
    const pp = C('inicio_persona_a_persona_saldo'), tres = C('inicio_hallazgo_3jun'), dias = C('inicio_dias_gps_2025');
    let h = '<section class="seccion" id="inicio-hallazgo"><div class="seccion__cab"><h2 class="seccion__titulo">Un hallazgo honesto</h2><span class="texto-3 pequeno">Visto persona a persona, el plan pierde más de lo que D5 estima</span></div>';
    if (esObj(pp) || esObj(tres)) {
      let p = '';
      if (esObj(pp)) {
        const v = pp.valor;
        p += 'Con el modelo persona a persona de la vista 3D' + (esNum(dias) ? ' (' + n(dias.valor) + ' días de ' + ANIO + ' con GPS' : ' (todo ' + ANIO) + ', sin tope de cupo), el plan ahorra ' + conU(v.ahorro_operacion_Mcop, 0, 'M COP') + ' en operación pero pierde ' + conU(v.pasajes_perdidos_Mcop, 0, 'M COP') + ' en pasajes: saldo de ' + signoU(v.saldo_conservador_Mcop, 0, 'M COP') + ' con la contabilidad conservadora y de ' + signoU(v.saldo_simetrico_Mcop, 0, 'M COP') + ' con la simétrica. ';
      }
      if (esObj(tres)) {
        const v = tres.valor;
        const veces = v.sobre_capacidad_real ? v.sobre_capacidad_plan / v.sobre_capacidad_real : null;
        const dia = tres.dia || v.dia || (/(\d{4}-\d{2}-\d{2})/.exec(tres.archivo || '') || [])[1] || '2025-06-03';
        p += 'El ' + F.fechaLarga(dia) + ' (un laboral cargado) el plan pone ' + n(v.salidas_plan) + ' salidas donde hubo ' + n(v.salidas_real) + ' reales (' + n(v.salidas_validas_real) + ' válidas), pierde ' + n((v.perdidos_beta || 0) + (v.perdidos_sin_bus || 0)) + ' pasajeros (' + n(v.perdidos_beta) + ' por β y ' + n(v.perdidos_sin_bus) + ' sin bus)' +
          (veces ? ' y multiplica por ' + n(veces, 1) + ' las personas por encima de la capacidad (' + n(v.sobre_capacidad_plan) + ' frente a ' + n(v.sobre_capacidad_real) + ')' : '') + (typeof v.balance_dia_Mcop === 'number' ? '; el balance del día es ' + signoU(v.balance_dia_Mcop, 1, 'M COP') : '') + '.';
      }
      h += '<div class="aviso aviso--critico">' + icono('alerta') + '<div class="aviso__cuerpo"><h3 class="aviso__titulo">Crítico: el modelo persona a persona castiga al plan</h3><p>' + p + '</p><p class="texto-2">Se muestra como hallazgo, con su propia forma de medir y sin revisor de la suma anual; las cifras principales siguen siendo las de costos y simulación, que sí tuvieron revisor.</p>' +
        fuentesTexto([['inicio_persona_a_persona_saldo', 'todo ' + ANIO + ''], ['inicio_hallazgo_3jun', '3 de junio']]) + '</div></div>';
    } else h += '<div class="aviso aviso--critico">' + icono('alerta') + '<div class="aviso__cuerpo"><h3 class="aviso__titulo">Crítico: el modelo persona a persona castiga al plan</h3><p>' + textoPendiente('el hallazgo') + '</p></div></div>';
    return h + enlace('ciudad', 'Ver cómo se ve en la calle') + '</section>';
  }

  // ---- 8. Cómo lo decide cada día ---------------------------------------------------------------------------------------------
  function decide() {
    const bt = C('inicio_backtest_plan_vs_oraculo');
    let h = '<section class="seccion" id="inicio-decide"><div class="seccion__cab"><h2 class="seccion__titulo">Cómo lo decide cada día</h2><span class="texto-3 pequeno">Qué tan cerca del óptimo (con la demanda que llegó) quedan el plan semanal y la operación real</span></div>';
    if (esObj(bt)) {
      const v = bt.valor;
      app().popoverFuente('f-inicio_backtest_plan_vs_oraculo', bt, 'plan frente a oráculo');
      // Cada ficha con su botón «fuente»: archivo y clave de su propio campo (tomados de «origen»).
      const popCampo = function (campo, titulo) {
        const o = (bt.origen || []).filter(function (x) { return Array.isArray(x) && Array.isArray(x[0]) && x[0][x[0].length - 1] === campo; })[0];
        const ref = o && o[1] && o[1].a ? o[1] : null;
        const id = 'f-inicio_bt-' + campo;
        app().popoverFuente(id, Object.assign({}, bt, { valor: v[campo], archivo: ref ? ref.a : bt.archivo, clave: ref ? ref.c : bt.clave }), titulo);
        return app().botonFuente(id);
      };
      const tarjeta = function (titulo, campo, campoPct, clase) {
        const err = v[campo], pct = v[campoPct];
        return '<article class="cifra cifra--llana' + (clase ? ' ' + clase : '') + '"><header class="cifra__cab"><h3 class="cifra__etiqueta">' + titulo + '</h3>' + popCampo(campo, titulo) + '</header><p class="cifra__valor"><span class="num">' + n(err, 2) + '</span><span class="cifra__unidad">salidas/h de error</span></p>' +
          (typeof pct === 'number' ? '<p class="cifra__variacion">' + n(pct, 1) + FINO + '% de las horas exactas</p>' : '') + '</article>';
      };
      h += '<div class="cifras">' + tarjeta('Con el modelo: plan semanal', 'plan_error_salidas_h', 'plan_pct_horas_exactas') + tarjeta('Hoy: operación real', 'real_error_salidas_h', 'real_pct_horas_exactas', 'cifra--hoy') + tarjeta('Reoptimizar en el día', 'motor_error_salidas_h', 'motor_pct_horas_exactas') + '</div>';
      const mejorMotor = typeof v.motor_error_salidas_h === 'number' && typeof v.plan_error_salidas_h === 'number' && v.motor_error_salidas_h < v.plan_error_salidas_h;
      h += '<div class="fila"><span class="texto-2 pequeno">Error medio por hora frente al oráculo (la decisión con la demanda que de verdad llegó)' + (typeof bt.dias === 'number' ? ', en ' + n(bt.dias) + ' días de ' + ANIO : ', en una muestra de días de ' + ANIO) + '. ' +
        (mejorMotor ? 'Reoptimizar en el día con el pronóstico del mismo día mejora al plan semanal.' : 'Reoptimizar en el día con el pronóstico del mismo día no mejora al plan semanal (' + n(v.motor_error_salidas_h, 2) + ' frente a ' + n(v.plan_error_salidas_h, 2) + ').') + '</span>' +
        app().chipVerificado(bt.verificado) + app().botonFuente('f-inicio_backtest_plan_vs_oraculo', 'Fuente') + '</div>';
      if (bt.nota) h += '<p class="texto-3 pequeno">' + esc(bt.nota) + '</p>';
    } else h += '<p>' + textoPendiente('la comparación con el oráculo') + '</p>';
    return h + enlace('despacho', 'Ver qué hace el despachador') + '</section>';
  }

  // ---- 9. Pie: contexto y fuentes --------------------------------------------------------------------------------------------
  function dato(id, rotulo, valorHTML, nota) {
    const c = C(id);
    if (!c || valorHTML === null) return '<div class="dato"><div class="dato__cab"><span class="rotulo">' + rotulo + '</span></div>' + textoPendiente('este dato') + '</div>';
    app().popoverFuente('f-' + id, c, rotulo);
    return '<div class="dato" id="d-' + id + '"><div class="dato__cab"><span class="rotulo">' + rotulo + '</span>' + app().botonFuente('f-' + id) + '</div><div class="dato__valor">' + valorHTML + '</div>' + (nota ? '<div class="dato__nota">' + nota + '</div>' : '') + '</div>';
  }
  function pie() {
    const rutas = C('inicio_rutas'), regla = C('inicio_regla_manual_definicion'), anio = C('inicio_demanda_por_anio'), caida = C('inicio_caida_anual'), v26 = C('inicio_2026_mas_viajes');
    const dias = C('inicio_dias_gps_2025'), cbh = C('inicio_costo_bus_hora'), ckm = C('inicio_costo_km'), tarifa = C('inicio_tarifa_neta'), pax = C('inicio_pax_dia_2025'), canc = C('inicio_cancelados_que_corrieron'), equipo = C('inicio_equipo'), fc = C('inicio_horas_fc_mayor_1');
    // inicio_rutas: lista de {id, nombre, km} (o, en datos viejos, un diccionario por nombre).
    const listaRutas = esObj(rutas) ? (Array.isArray(rutas.valor) ? rutas.valor : Object.keys(rutas.valor).map(function (r) { return Object.assign({ nombre: r }, rutas.valor[r]); })) : null;
    const chipsRutas = listaRutas ? listaRutas.map(function (ru) {
      const r = String(ru.nombre || '');
      const k = r === 'SILENCIO' ? 'silencio' : r === 'CRA 54' ? 'cra54' : 'cl72';
      const km = typeof ru.km === 'number' ? ' · ' + conU(ru.km, 1, 'km') : '';
      return '<span class="chip" style="--c: var(--ruta-' + k + ')"><span class="chip__punto"></span>' + esc(r) + km + '</span>';
    }).join('') : null;
    const equipoTxt = esTexto(equipo) ? esc(equipo.valor) : equipo && Array.isArray(equipo.valor) && equipo.valor.length ? equipo.valor.map(esc).join(', ') : null;
    const fcTxt = esTexto(fc) ? esc(fc.valor) : esNum(fc) ? conU(fc.valor, 1, '%') : esObj(fc) && typeof fc.valor.hoy === 'number' && typeof fc.valor.plan === 'number' ? conU(fc.valor.hoy, 1, '%') + ' hoy → ' + conU(fc.valor.plan, 1, '%') + ' con el modelo' : null;
    const anios = esObj(anio) ? '<div class="mini-cifras">' + Object.keys(anio.valor).sort().map(function (a) { return '<div class="mini-cifra"><span class="mini-cifra__rotulo">' + esc(a) + '</span><span class="mini-cifra__valor">' + n(anio.valor[a] / 1e6, 2) + '<span class="mini-cifra__unidad"> M</span></span></div>'; }).join('') + '</div>' : null;
    let caidaTxt = null;
    if (esObj(caida)) {
      const v = caida.valor;
      const orig = Object.keys(v).filter(function (k) { return /_original$/.test(k); }).sort();
      const corr = Object.keys(v).filter(function (k) { return /_corregido$/.test(k); }).sort();
      caidaTxt = orig.map(function (k) { return k.replace('_original', '') + ': ' + signoU(v[k], 1, '%'); }).join(' · ') + (corr.length ? ' (objetivo original); con los viajes marcados cancelados que corrieron: ' + corr.map(function (k) { return signoU(v[k], 1, '%'); }).join(' y ') : '');
    }
    const v26Txt = esObj(v26) ? signoU(v26.valor.viajes_pct, 1, '%') + ' de viajes y ' + signoU(v26.valor.subidas_pct, 1, '%') + ' de subidas frente a las mismas fechas de ' + ANIO : null;
    const cancTxt = esObj(canc) ? n(canc.valor.canceladas_que_si_operaron) + ' de ' + n(canc.valor.canceladas_bandera) + ' viajes marcados cancelados (' + n(canc.valor.pct, 1) + FINO + '%) sí recorrieron la ruta y llevaron ' + n(canc.valor.pasajeros) + ' pasajeros (' + n(canc.valor.pct_pasajeros_totales, 1) + FINO + '% del total)' : null;
    const costos = esNum(cbh) && esNum(ckm) && esNum(tarifa) ? '<div class="mini-cifras"><div class="mini-cifra"><span class="mini-cifra__rotulo">Bus-hora</span><span class="mini-cifra__valor">' + n(cbh.valor) + '<span class="mini-cifra__unidad"> COP</span></span></div><div class="mini-cifra"><span class="mini-cifra__rotulo">Kilómetro</span><span class="mini-cifra__valor">' + n(ckm.valor) + '<span class="mini-cifra__unidad"> COP</span></span></div><div class="mini-cifra"><span class="mini-cifra__rotulo">Tarifa neta</span><span class="mini-cifra__valor">' + n(tarifa.valor) + '<span class="mini-cifra__unidad"> COP/pasajero</span></span></div></div>' : null;
    let h = '<footer class="seccion seccion--separada" id="inicio-pie"><div class="seccion__cab"><h2 class="seccion__titulo">De dónde sale todo</h2><span class="texto-3 pequeno">Cada dato con su fuente; el detalle, en Método y datos</span></div><div class="datos-pie">';
    h += dato('inicio_rutas', 'Las tres rutas', chipsRutas && '<div class="chips">' + chipsRutas + '</div>');
    h += dato('inicio_regla_manual_definicion', 'Hoy Sobusa programa con', esTexto(regla) ? esc(regla.valor) : null);
    h += dato('inicio_demanda_por_anio', 'Pasajeros por año (viajes válidos)', anios, caidaTxt ? 'Variación anual ' + caidaTxt + '.' : null);
    h += dato('inicio_2026_mas_viajes', 'Y ' + ANIO_SIGUE + ' sube', v26Txt, v26 && v26.nota ? esc(v26.nota) : null);
    h += dato('inicio_pax_dia_2025', 'Pasajeros por día en ' + ANIO, esNum(pax) ? conU(pax.valor, 0, 'pasajeros/día') : null, 'Viajes válidos, tres rutas: la base del riesgo del plan.');
    h += dato('inicio_dias_gps_2025', 'Días de ' + ANIO + ' que se pueden reproducir', esNum(dias) ? conU(dias.valor, 0, 'días') : null, esNum(dias) && typeof dias.sin_gps === 'number' ? 'Faltan ' + n(dias.sin_gps) + ': el último de cada mes no tiene GPS.' : 'El último día de cada mes no tiene GPS.');
    h += dato('inicio_costo_bus_hora', 'Costos evitables de ' + ANIO_SIGUE, costos, 'Conductor por hora en ruta, kilómetro (combustible, mantenimiento, llantas, lubricantes) e ingreso neto por pasajero.');
    h += dato('inicio_horas_fc_mayor_1', 'Horas con factor de carga mayor que 1', fcTxt, 'Porcentaje de las horas, en las tres rutas.');
    h += dato('inicio_cancelados_que_corrieron', 'Viajes «cancelados» que sí corrieron', cancTxt, 'El objetivo oficial del modelo no los cuenta; E13 los incluye como siguiente paso.');
    h += dato('inicio_equipo', 'Equipo', equipoTxt);
    h += '</div>';
    h += fuentesTexto([['inicio_costo_bus_hora', 'bus-hora'], ['inicio_costo_km', 'kilómetro'], ['inicio_tarifa_neta', 'tarifa neta'], ['inicio_caida_anual', 'variación anual']]);
    h += enlace('metodo', 'Ver el método y los datos') + '</footer>';
    return h;
  }

  // ---- Registro de la pantalla -------------------------------------------------------------------------------------------------
  // Un único registro (DISEÑO.md §5.1): si app.js aún no cargó, la definición espera en window.__pantallasRegistradas.
  const registrar = typeof global.registrarPantalla === 'function' ? global.registrarPantalla : function (d) { (global.__pantallasRegistradas = global.__pantallasRegistradas || []).push(d); };
  registrar({
    id: 'inicio',
    pregunta: '¿Qué proponemos?',
    subtitulo: function () {
      const m = C('inicio_error_modelo_final'), r = C('inicio_error_regla_manual');
      if (esNum(m) && esNum(r)) return 'El modelo se equivoca en ' + n(Math.round(m.valor)) + ' de cada 100 pasajeros a una semana; la regla manual de Sobusa, en ' + n(Math.round(r.valor)) + '. Casi las mismas salidas, en otras horas.';
      return 'Pronóstico de demanda y horario recomendado para SILENCIO, CRA 54 y CL 72. No quitar buses: cambiarlos de hora.';
    },
    icono: 'inicio',
    interruptor: ['hoy', 'modelo'],
    tooltipInterruptor: 'No aplica a estas cifras',
    modulo: null,
    render: function (contenedor, datos, est) {
      cont = contenedor;
      estado = est;
      interactivas = [];
      serieHoras = null;
      contenedor.innerHTML = hero() + fichasDia() + problema() + gana() + betaYPiloto() + hallazgo() + decide() + pie();
      pintarEscenario(false);
      dibujarGrafico();
    },
    actualizar: function (est) {
      const cambioEscenario = !estado || est.escenario !== estado.escenario;
      estado = est;
      if (serieHoras && !grafico) dibujarGrafico();
      if (cambioEscenario) pintarEscenario(true); else atenuarSeries();
    },
    salir: function () {
      if (grafico) { grafico.dispose(); grafico = null; }
      if (vigilante) { vigilante.disconnect(); vigilante = null; }
    },
  });
})(window);
