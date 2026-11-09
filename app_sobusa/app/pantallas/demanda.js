// Sobusa Despacho · pantallas/demanda.js
// Pantalla «Demanda · ¿Cuántos pasajeros habrá?». Sigue el contrato de app/DISEÑO.md §5 (registrarPantalla con render,
// actualizar y salir) y el wireframe de §7. Ninguna cifra está escrita aquí: todas salen de window.DATOS_APP
// (app/datos_app.js, generado por app/generar_datos_app.py) y cada una lleva su botón «fuente» (app.popoverFuente).
//
// Ids que lee (contrato del inventario de cifras de la app), de la pantalla Demanda: demanda_wape_por_ruta,
// demanda_wape_por_tipo_dia, demanda_wape_por_franja, demanda_wape_antelacion, demanda_hibrido_antelacion_emulacion,
// demanda_wape_h1, demanda_sesgo, demanda_wape_total_diario, demanda_festivos, demanda_serie_diaria_2025,
// demanda_serie_hora_ejemplo, demanda_pronostico_2026_enero, demanda_objetivo_corregido,
// demanda_error_total_diario_corregido, demanda_horas_faltan_buses, demanda_horas_buses_exactos,
// demanda_pax_cancelados_corrieron_2025, demanda_dias_con_problema_datos, demanda_2026_variacion,
// demanda_elasticidad_aparente_2026, demanda_lluvia, demanda_correlacion_rutas, demanda_un_modelo_por_ruta,
// demanda_otras_rutas_como_variable, demanda_lo_que_no_ayuda, demanda_lo_que_si_ayuda, demanda_dias_atipicos,
// demanda_protocolo, demanda_otros_metodos, demanda_intervalo_e3; y de otras pantallas: inicio_error_regla_manual,
// inicio_error_modelo_final, inicio_error_hibrido, inicio_error_e1, inicio_regla_manual_definicion,
// modelo_limite_nivel_2026; de datos.contradicciones, la C17 (y la C2 por la nota de los festivos).
// Si un id falta, la pantalla lo dice en un aviso y pinta «—» en su lugar.
//
// Interruptor: Hoy (la regla manual de Sobusa) / Con el modelo (el modelo final de E11 o el híbrido de E12, elegido con un
// segmentado secundario «Modelo:»). «Oráculo» no aplica: el pronóstico no tiene oráculo. Los chips de ruta gobiernan los
// dos gráficos de series (la serie diaria de 2025 y el día de ejemplo por hora) y viajan al estado compartido (ruta).
// El módulo al final de la pantalla es el tablero (EDA_visual.html, pestaña «demanda»); la app lo monta y lo duerme.
(function (global) {
  'use strict';

  const ID = 'demanda';
  // Años del estudio (como en resultado.js y modelo.js): el texto no los escribe sueltos.
  const ANIO = '2025', ANIO_PRUEBA = '2024', ANIO_INICIO = '2023', ANIO_SIGUE = '2026';
  const IC = '95';                 // nivel de los intervalos de confianza del protocolo (convención, no una cifra del proyecto)
  const FINO = ' ';           // espacio fino antes de % y de la unidad
  const F = global.COMPONENTES.formato;
  const icono = function (nombre, clase) { return global.ICONOS.svg(nombre, clase); };
  const RUTAS = ['SILENCIO', 'CRA 54', 'CL 72'];
  const RUTA_CLASE = { 'SILENCIO': 'silencio', 'CRA 54': 'cra54', 'CL 72': 'cl72' };
  const TODAS = 'Todas';
  const SERIES = { real: 'Real', B1: 'Regla manual', E1_V0: 'Primer modelo (E1)', E11_V4: 'Modelo final', hibrido: 'Híbrido' };
  const COLS = ['real', 'B1', 'E1_V0', 'E11_V4', 'hibrido'];
  const MODELO_CLAVE = { final: 'E11_V4', hibrido: 'hibrido' };
  const MESES = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic'];
  const MESES_LARGOS = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre'];
  const PESTANAS_TABLERO = [['demanda', 'Demanda por día'], ['horas', 'Demanda por hora'], ['mapa', 'Mapa de las rutas']];

  // ---- Estado de la pantalla -----------------------------------------------------------------------------------
  let D = null;                 // window.DATOS_APP
  let cont = null;              // div.pantalla que nos da la app
  let escenario = 'hoy';        // 'hoy' | 'modelo'
  let modelo = 'final';         // 'final' | 'hibrido' (segmentado secundario)
  let ruta = TODAS;             // 'Todas' | 'SILENCIO' | 'CRA 54' | 'CL 72' (chips)
  let graficos = {};            // clave → instancia de ECharts
  let limpiezas = [];           // funciones que deshacen observadores y oyentes
  let faltantes = [];           // ids que no están en DATOS_APP
  let pops = {};                // clave → id del popover ya creado
  let nPop = 0;
  let fichas = [];              // fichas de cifra gobernadas por el interruptor
  let serieDiaria = null;       // demanda_serie_diaria_2025 indexada
  let serieHora = null;         // demanda_serie_hora_ejemplo indexada

  // ---- Formato ---------------------------------------------------------------------------------------------------
  function num(v) { return typeof v === 'number' && isFinite(v); }
  const n = function (v, d) { return num(v) ? F.numero(v, d || 0) : '—'; };
  const pct = function (v, d) { return num(v) ? F.numero(v, d === undefined ? 2 : d) + FINO + '%' : '—'; };
  const sg = function (v, d) { return num(v) ? F.signo(v, d === undefined ? 2 : d) : '—'; };
  const pp = function (v, d) { return num(v) ? F.signo(v, d === undefined ? 2 : d) + ' puntos' : '—'; };
  function esc(t) { return String(t === null || t === undefined ? '' : t).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
  // Texto de los archivos con **negritas** y `código`: se escapa y se convierte solo eso.
  function md(t) { return esc(t).replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>').replace(/`([^`]+)`/g, '<code>$1</code>'); }
  function ic(inf, sup, d) { return num(inf) && num(sup) ? '[' + sg(inf, d) + '; ' + sg(sup, d) + ']' : ''; }
  function rutaTexto() { return ruta === TODAS ? 'las tres rutas' : ruta; }
  function claveModelo() { return MODELO_CLAVE[modelo] || 'E11_V4'; }
  function claveActual() { return escenario === 'hoy' ? 'B1' : claveModelo(); }

  // ---- Acceso a los datos ----------------------------------------------------------------------------------------
  function entrada(id) {
    const p = D && D.pantallas;
    if (!p) return null;
    if (p[ID] && p[ID][id]) return p[ID][id];
    for (const k in p) if (p[k] && p[k][id]) return p[k][id];
    return null;
  }
  function anotarFaltante(id) { if (faltantes.indexOf(id) < 0) faltantes.push(id); }
  function cifra(id) {
    const e = entrada(id);
    if (!e) { anotarFaltante(id); return null; }
    return global.app && global.app.normalizarCifra ? global.app.normalizarCifra(e) : e;
  }
  function valor(id, ruta, porDefecto) {
    const e = entrada(id);
    if (!e) { anotarFaltante(id); return porDefecto; }
    let v = e.valor !== undefined ? e.valor : e.valor_actual;
    if (ruta !== undefined && ruta !== null && ruta !== '') {
      const partes = String(ruta).split('.');
      for (let i = 0; i < partes.length; i++) { if (v === null || v === undefined) return porDefecto; v = v[partes[i]]; }
    }
    return v === undefined || v === null ? porDefecto : v;
  }
  // Un campo de la cifra fuera de «valor» (p. ej. textos, semanas, columnas, filas, dia).
  function campo(id, nombre) { const e = entrada(id); return e && e[nombre] !== undefined ? e[nombre] : null; }
  // El primer valor numérico de una lista de [id, ruta]; devuelve {v, id, ruta}.
  function primero(lista) {
    for (let i = 0; i < lista.length; i++) {
      if (!entrada(lista[i][0])) continue;
      const v = valor(lista[i][0], lista[i][1], null);
      if (num(v)) return { v: v, id: lista[i][0], ruta: lista[i][1] };
    }
    anotarFaltante(lista[0][0]);
    return { v: null, id: lista[0][0], ruta: lista[0][1] };
  }
  // Referencia exacta (archivo y clave) de una parte de la cifra, tomada de su «origen»: [[ruta], {a, c}].
  function refDe(id, ruta) {
    const e = entrada(id);
    if (!e || !Array.isArray(e.origen) || ruta === null || ruta === undefined || ruta === '') return null;
    const partes = String(ruta).split('.');
    const conValor = ['valor'].concat(partes);
    const igual = function (r, p) { return r.length === p.length && p.every(function (x, i) { return String(r[i]) === x; }); };
    let ref = null;
    e.origen.forEach(function (o) { if (!ref && Array.isArray(o) && Array.isArray(o[0]) && (igual(o[0], conValor) || igual(o[0], partes))) ref = o[1]; });
    if (!ref || typeof ref !== 'object') return null;
    if (ref.t === 'f' || !ref.c) return { archivo: ref.a, clave: ref.expr ? 'fórmula ' + ref.expr + ' con partes del archivo (ver «origen» en app/datos_app.js)' : (e.clave || '—') };
    return { archivo: ref.a, clave: ref.c + (ref.op ? ' → ' + ref.op : '') };
  }
  // Las contradicciones del inventario (datos.contradicciones): la C17 y la C2 se citan en esta pantalla.
  function contradiccion(idC) {
    const lista = D && D.contradicciones;
    if (!Array.isArray(lista)) return null;
    return lista.filter(function (c) { return c && c.id === idC; })[0] || null;
  }

  // ---- Fuente: popover (lo crea la app en #popovers) y botón --------------------------------------------------------
  function pop(id, ruta, titulo, extra) {
    const k = id + '|' + (ruta === undefined || ruta === null ? '' : ruta) + '|' + (titulo || '') + '|' + (extra ? JSON.stringify(extra) : '');
    if (pops[k]) return pops[k];
    const c = cifra(id);
    if (!c || !global.app || typeof global.app.popoverFuente !== 'function') return null;
    nPop += 1;
    const idPop = 'dem-f-' + nPop;
    const cambios = {};
    if (ruta !== undefined && ruta !== null && ruta !== '') {
      const r = refDe(id, ruta);
      if (r) { if (r.archivo) cambios.archivo = r.archivo; cambios.clave = r.clave; }
      else cambios.clave = (c.clave || '—') + ' → ' + String(ruta).split('.').join(' → ');
      const v = valor(id, ruta, null);
      cambios.valor = typeof v === 'number' || typeof v === 'string' ? v : undefined;
    }
    if (c.que_es) cambios.que_mide = esc(c.que_es);
    global.app.popoverFuente(idPop, Object.assign({}, c, cambios, extra || {}), titulo || c.que_es || id);
    pops[k] = idPop;
    return idPop;
  }
  function fuente(id, ruta, titulo, extra) { const p = pop(id, ruta, titulo, extra); return p ? global.app.botonFuente(p) : ''; }
  function fuenteDe(x, titulo) { return x && x.id ? fuente(x.id, x.ruta, titulo) : ''; }
  // Un solo botón «Fuentes (n)» con varias cifras: [[id, título], …].
  function fuentes(lista, titulo) {
    const pares = lista.map(function (par) { return [cifra(par[0]), par[1]]; }).filter(function (par) { return par[0]; });
    if (!pares.length || !global.app || typeof global.app.popoverFuentes !== 'function') return '';
    nPop += 1;
    const idPop = 'dem-f-' + nPop;
    global.app.popoverFuentes(idPop, pares, titulo);
    return global.app.botonFuente(idPop, 'Fuentes (' + n(pares.length) + ')');
  }
  function chipVerificado(id) { const c = cifra(id); return c && global.app ? global.app.chipVerificado(c.verificado) : ''; }

  // ---- Piezas de HTML -------------------------------------------------------------------------------------------
  function seccion(id, titulo, intro, cuerpo, extraCab) {
    return '<section class="seccion" id="' + id + '" aria-labelledby="' + id + '-t"><div class="seccion__cab"><h2 class="seccion__titulo" id="' + id + '-t">' + titulo + '</h2>' + (extraCab || '') + '</div>' +
      (intro ? '<p class="seccion__intro">' + intro + '</p>' : '') + '<div class="seccion__cuerpo">' + cuerpo + '</div></section>';
  }
  function aviso(tipo, titulo, cuerpo, id) {
    const ico = tipo === 'canje' ? 'canje' : tipo === 'bien' ? 'bien' : tipo === 'nota' ? 'info' : 'alerta';
    return '<div class="aviso' + (tipo && tipo !== 'nota' ? ' aviso--' + tipo : '') + '"' + (id ? ' id="' + id + '"' : '') + '>' + icono(ico) + '<div class="aviso__cuerpo"><h3 class="aviso__titulo">' + titulo + '</h3>' + cuerpo + '</div></div>';
  }
  function cifraLlana(etiqueta, valorHtml, unidad, nota, botonFuente, claseValor) {
    return '<article class="cifra cifra--llana"><header class="cifra__cab"><h3 class="cifra__etiqueta">' + etiqueta + '</h3>' + (botonFuente || '') + '</header>' +
      '<p class="cifra__valor' + (claseValor ? ' ' + claseValor : '') + '"><span class="num">' + valorHtml + '</span>' + (unidad ? '<span class="cifra__unidad">' + unidad + '</span>' : '') + '</p>' +
      (nota ? '<p class="cifra__nota">' + nota + '</p>' : '') + '</article>';
  }
  function desplegable(id, titulo, cuerpo, llano) {
    return '<details class="desplegable' + (llano ? ' desplegable--llano' : '') + '" id="' + id + '"><summary class="desplegable__resumen">' + icono('chevron-derecha', 'icono desplegable__chevron') + titulo + '</summary><div class="desplegable__cuerpo">' + cuerpo + '</div></details>';
  }
  // Tabla de datos. filas: [{ celdas, clase, mejor }] o [{ grupo, extra }] (una fila de cabecera de grupo en su propio tbody).
  // La primera celda es la cabecera de fila; las demás, números a la derecha (salvo las de opciones.textoEn).
  function tabla(caption, cabeceras, filas, o) {
    o = o || {};
    const esTexto = function (i) { return i === 0 || (o.textoEn && o.textoEn.indexOf(i) >= 0); };
    let h = (o.sinMarco ? '' : '<div class="tabla-marco">') + '<table class="tabla' + (o.compacta ? ' tabla--compacta' : '') + '">' + (caption ? '<caption>' + caption + '</caption>' : '') +
      '<thead><tr>' + cabeceras.map(function (c, i) { return '<th scope="col"' + (esTexto(i) ? '' : ' class="num"') + '>' + c + '</th>'; }).join('') + '</tr></thead>';
    let abierto = false;
    filas.forEach(function (f) {
      if (f.grupo !== undefined) {
        if (abierto) h += '</tbody>';
        h += '<tbody><tr class="demanda__grupo"><th scope="rowgroup" colspan="' + cabeceras.length + '">' + f.grupo + (f.extra ? ' ' + f.extra : '') + '</th></tr>';
        abierto = true;
        return;
      }
      if (!abierto) { h += '<tbody>'; abierto = true; }
      h += '<tr' + (f.clase ? ' class="' + f.clase + '"' : '') + '>' + f.celdas.map(function (c, i) {
        if (i === 0) return '<th scope="row">' + c + '</th>';
        const clases = [];
        if (!esTexto(i)) clases.push('num');
        if (f.mejor === i) clases.push('tabla__mejor');
        return '<td' + (clases.length ? ' class="' + clases.join(' ') + '"' : '') + '>' + c + '</td>';
      }).join('') + '</tr>';
    });
    if (abierto) h += '</tbody>';
    return h + '</table>' + (o.sinMarco ? '' : '</div>');
  }
  // Índice (1 + posición) del mejor valor de una lista de números: el menor, o el mayor si mayorEsMejor.
  function mejorIndice(valores, mayorEsMejor) {
    let mejor = -1;
    valores.forEach(function (v, i) {
      if (!num(v)) return;
      if (mejor < 0 || (mayorEsMejor ? v > valores[mejor] : v < valores[mejor])) mejor = i;
    });
    return mejor < 0 ? -1 : mejor + 1;
  }
  function claveRuta(r) { const c = RUTA_CLASE[r]; return c ? '<span class="tabla__clave"><span class="tabla__muestra" style="--c: var(--ruta-' + c + ')"></span>' + esc(r) + '</span>' : esc(r); }
  function figura(o) {
    // o: { id, titulo, sub, aria, leyenda (html), tabla (html), pie (html), bajo }
    return '<figure class="grafico" id="' + o.id + '"><figcaption class="grafico__cab"><div class="grafico__titulos"><h3 class="grafico__titulo">' + o.titulo + '</h3><p class="grafico__sub" data-sub>' + o.sub + '</p></div>' +
      '<div class="grafico__acciones"><button class="boton boton--secundario boton--pequeno" type="button" data-ver-tabla data-texto-tabla="Ver tabla" data-texto-grafico="Ver gráfico">' + icono('tabla') + '<span data-texto>Ver tabla</span></button></div></figcaption>' +
      '<ul class="leyenda" data-leyenda>' + (o.leyenda || '') + '</ul>' +
      '<div class="grafico__lienzo' + (o.bajo ? ' grafico__lienzo--bajo' : '') + '" id="' + o.id + '-lienzo" role="img" aria-label="' + esc(o.aria) + '"></div>' +
      '<div class="grafico__tabla tabla-marco" id="' + o.id + '-tabla" hidden>' + (o.tabla || '') + '</div>' +
      '<div class="grafico__pie">' + (o.pie || '') + '</div></figure>';
  }
  // Leyenda en HTML: rol 'real' | 'hoy' | 'modelo' | 'final' (modelo con rayas) ; tenue = la serie desenfatizada por el interruptor.
  function itemLeyenda(nombre, rol, tenue, barra) {
    let clase = barra ? 'leyenda__muestra--barra' : rol === 'real' ? 'leyenda__muestra--gruesa' : '';
    if (rol === 'final') clase += ' demanda__rayas';
    const color = rol === 'final' ? 'var(--serie-modelo)' : 'var(--serie-' + rol + ')';
    return '<li><button class="leyenda__item" type="button" data-serie="' + esc(nombre) + '" aria-pressed="true"><span class="leyenda__muestra ' + clase + (tenue ? ' demanda__muestra--tenue' : '') + '" style="--c: ' + color + '"></span>' + esc(nombre) + '</button></li>';
  }
  // Pone (o repone) la leyenda de una figura y la liga al gráfico; aplica lo que el usuario había apagado.
  function ponerLeyenda(fig, html, obtener) {
    const ul = fig.querySelector('[data-leyenda]');
    if (!ul) return;
    const apagadas = Array.from(ul.querySelectorAll('.leyenda__item[aria-pressed="false"]')).map(function (b) { return b.dataset.serie; });
    ul.innerHTML = html;
    global.COMPONENTES.leyenda(ul, obtener);
    const g = obtener();
    ul.querySelectorAll('.leyenda__item').forEach(function (b) {
      if (apagadas.indexOf(b.dataset.serie) >= 0) { b.setAttribute('aria-pressed', 'false'); if (g) g.dispatchAction({ type: 'legendUnSelect', name: b.dataset.serie }); }
    });
  }

  // ---- Estilos propios de la pantalla (solo tokens) --------------------------------------------------------------
  function estilos() {
    if (document.getElementById('estilos-demanda')) return;
    const st = document.createElement('style');
    st.id = 'estilos-demanda';
    st.textContent = [
      '#dem-cuerpo { gap: var(--e-8); }',
      '@media (max-width: 600px) { #dem-cuerpo { gap: var(--e-7); } }',
      '#dem-fichas .cifra { grid-template-rows: auto auto 1fr; align-content: stretch; }',
      '#dem-fichas .cifra__variacion { align-self: end; display: block; line-height: 1.5; text-wrap: pretty; }',
      '#dem-fichas .cifra__variacion > .icono:first-child { display: inline-block; vertical-align: -2px; margin-right: 4px; }',
      '#dem-fichas .cifra__nota[hidden] { display: none; }',
      '@media (min-width: 900px) { #dem-fichas { grid-template-columns: repeat(4, minmax(0, 1fr)); } }',
      '.demanda__rayas { background: repeating-linear-gradient(135deg, var(--serie-modelo) 0 2px, var(--superficie) 2px 5px); }',
      '.demanda__muestra--tenue { opacity: 0.45; }',
      '.demanda__grupo th { background: var(--superficie-2); color: var(--tinta-2); font-weight: var(--peso-medio); font-size: var(--t-xs); padding: 6px 14px; }',
      '.demanda__grupo .fuente { vertical-align: middle; margin-left: 4px; }',
      '.demanda__que { display: grid; grid-template-columns: minmax(0, 14em) minmax(0, 1fr); gap: var(--e-2) var(--e-4); margin: 0; font-size: var(--t-s); }',
      '.demanda__que dt { color: var(--tinta-2); } .demanda__que dd { margin: 0; }',
      '@media (max-width: 600px) { .demanda__que { grid-template-columns: minmax(0, 1fr); } .demanda__que dd { margin-bottom: var(--e-2); } }',
      '.demanda__lista { margin: 0; padding-left: 20px; display: grid; gap: var(--e-2); max-width: var(--ancho-texto); }',
      '.demanda__lista li { text-wrap: pretty; }',
      '.demanda__tarjetas { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 300px), 1fr)); gap: var(--e-4); align-items: start; }',
      '.demanda__tarjeta h3 { font-size: var(--t-m); font-weight: var(--peso-fuerte); }',
      '.demanda__tarjeta .cifras { grid-template-columns: repeat(auto-fit, minmax(min(100%, 150px), 1fr)); }',
      '.demanda__tarjeta .cifra__valor { font-size: var(--t-xl); }',
      '.demanda__tarjeta p, .demanda__tarjeta li { font-size: var(--t-s); color: var(--tinta-2); text-wrap: pretty; }',
      '.demanda__tarjeta p strong { color: var(--tinta); }',
      '.demanda__aviso-tabla { margin-top: var(--e-3); }',
      '.demanda__aviso-tabla .tabla-marco { background: var(--superficie-2); }',
      '.demanda__prosa { max-width: var(--ancho-texto); text-wrap: pretty; }',
      '.demanda__prosa .fuente, .seccion__intro .fuente, .aviso__cuerpo .fuente, .cifra__variacion .fuente, .cifra__nota .fuente { vertical-align: middle; }',
      '.demanda__nota-verificado { display: inline-flex; align-items: center; gap: var(--e-2); flex-wrap: wrap; }',
    ].join('\n');
    document.head.appendChild(st);
  }

  // ---- Horizonte principal y pliegues, tomados de los datos --------------------------------------------------------
  function hClave() {
    const b1 = valor('demanda_wape_antelacion', 'B1', null);
    if (b1 && typeof b1 === 'object') {
      const ks = Object.keys(b1).map(Number).filter(num).sort(function (a, b) { return a - b; });
      if (ks.length) return String(ks[0]);
    }
    const hs = valor('demanda_protocolo', 'horizontes_E11', null);
    if (hs && typeof hs === 'object') {
      const ks = Object.keys(hs).map(Number).filter(num).sort(function (a, b) { return b - a; });
      if (ks.length) return String(ks[0]);
    }
    return null;
  }
  function hTexto() { const h = hClave(); return h ? n(+h) + ' días' : 'una semana'; }
  function pliegues() { const p = valor('demanda_protocolo', 'pliegues', null); return num(p) ? p : null; }
  function deMeses(k) { const p = pliegues(); return num(k) ? n(k) + (num(p) ? ' de ' + n(p) + ' meses' : ' meses') : '—'; }

  // ---- Las fichas que gobierna el interruptor ----------------------------------------------------------------------
  function definirFichas() {
    const H = hClave();
    const global_ = function (clave) {
      if (clave === 'B1') return primero([['inicio_error_regla_manual', null], ['demanda_wape_antelacion', H ? 'B1.' + H : null]]);
      if (clave === 'E11_V4') return primero([['inicio_error_modelo_final', null], ['demanda_wape_antelacion', H ? 'E11_V4.' + H : null]]);
      return primero([['inicio_error_hibrido', null]]);
    };
    const def = [
      { clave: 'global', etiqueta: 'Pasajeros mal estimados de cada 100', unidad: '%', dec: 2,
        que: 'El error a ' + hTexto() + ' de antelación en ' + ANIO + ' (WAPE): la suma de los errores absolutos de cada franja ruta × día × hora de salida, sobre la suma de los pasajeros reales.',
        B1: global_('B1'), E11_V4: global_('E11_V4'), hibrido: global_('hibrido') },
      { clave: 'h1', etiqueta: 'A un día de antelación', unidad: '%', dec: 2,
        que: 'Lo mismo con el pronóstico hecho la víspera. El híbrido solo se evaluó a ' + hTexto() + ', así que aquí no tiene cifra.',
        B1: primero([['demanda_wape_h1', 'B1']]), E11_V4: primero([['demanda_wape_h1', 'E11_V4']]),
        hibrido: { v: null, id: 'demanda_wape_h1', ruta: null, sinDato: 'El híbrido no se midió a un día' } },
      { clave: 'diario', etiqueta: 'Error del total diario por ruta', unidad: '%', dec: 2,
        que: 'El error cuando se suman las horas del día de cada ruta: los errores de una hora y otra se compensan en parte.',
        B1: primero([['demanda_wape_total_diario', 'B1']]), E11_V4: primero([['demanda_wape_total_diario', 'E11_V4']]), hibrido: primero([['demanda_wape_total_diario', 'hibrido']]) },
      { clave: 'festivos', etiqueta: 'En los festivos de ' + ANIO, unidad: '%', dec: 1,
        que: 'El error en los festivos del año, donde la regla manual más se equivoca. Son las cifras del primer modelo (E1, variante c), no del modelo final ni del híbrido: no se recalcularon.',
        B1: primero([['demanda_festivos', 'B1']]), E11_V4: primero([['demanda_festivos', 'modelo_E1']]), hibrido: primero([['demanda_festivos', 'modelo_E1']]),
        nota: 'Cifra del primer modelo (E1): no se recalculó para el modelo final ni para el híbrido.' },
    ];
    def.forEach(function (f) {
      f.pop = {};
      ['B1', 'E11_V4', 'hibrido'].forEach(function (k) {
        const x = f[k];
        const titulo = f.etiqueta + ' · ' + (k === 'B1' ? 'regla manual' : SERIES[k].toLowerCase());
        if (x.sinDato) f.pop[k] = pop(x.id, null, titulo, { clave: x.sinDato + ' (el archivo solo trae la regla manual, E1 y el modelo final a h = 1)', valor: undefined });
        else f.pop[k] = pop(x.id, x.ruta, titulo);
      });
    });
    return def;
  }
  function htmlFichas() {
    return '<div class="cifras" id="dem-fichas">' + fichas.map(function (f) {
      return '<article class="cifra" data-ficha="' + f.clave + '"><header class="cifra__cab"><h3 class="cifra__etiqueta">' + f.etiqueta + '</h3>' +
        '<button class="fuente" type="button" popovertarget="' + (f.pop.B1 || '') + '" aria-expanded="false" aria-label="Fuente de la cifra" data-fuente-ficha>' + icono('fuente') + '</button></header>' +
        '<p class="cifra__valor"><span data-cifra="' + (num(f.B1.v) ? f.B1.v : '') + '" data-decimales="' + f.dec + '">' + (num(f.B1.v) ? n(f.B1.v, f.dec) : '—') + '</span><span class="cifra__unidad">' + f.unidad + '</span></p>' +
        '<p class="cifra__variacion" data-variacion></p>' + (f.nota ? '<p class="cifra__nota" data-nota hidden>' + f.nota + '</p>' : '') + '</article>';
    }).join('') + '</div>' +
      desplegable('dem-fichas-que', 'Qué mide cada cifra', '<dl class="demanda__que">' + fichas.map(function (f) { return '<dt>' + f.etiqueta + '</dt><dd>' + f.que + '</dd>'; }).join('') + '</dl>', true);
  }
  function pintarFichas(animar) {
    const k = claveActual();
    fichas.forEach(function (f) {
      const art = cont.querySelector('[data-ficha="' + f.clave + '"]');
      if (!art) return;
      const span = art.querySelector('[data-cifra]');
      const x = f[k];
      if (num(x.v)) { if (animar) global.COMPONENTES.ponerCifra(span, x.v); else { span.dataset.cifra = String(x.v); span.textContent = n(x.v, f.dec); } }
      else { span.dataset.cifra = ''; span.textContent = '—'; }
      if (f.pop[k]) art.querySelector('[data-fuente-ficha]').setAttribute('popovertarget', f.pop[k]);
      art.classList.toggle('cifra--hoy', k === 'B1');
      const nota = art.querySelector('[data-nota]');
      if (nota) nota.hidden = k === 'B1';
      const v = art.querySelector('[data-variacion]');
      // En «Hoy» no se repite por ficha «lo que Sobusa hace hoy»: lo dice la intro (DISEÑO.md §10).
      if (k === 'B1') { v.className = 'cifra__variacion'; v.innerHTML = ''; return; }
      if (x.sinDato || !num(x.v)) { v.className = 'cifra__variacion'; v.innerHTML = icono('info') + esc(x.sinDato || 'Sin cifra en los datos'); return; }
      if (!num(f.B1.v)) { v.className = 'cifra__variacion'; v.innerHTML = ''; return; }
      const dif = x.v - f.B1.v;
      v.className = 'cifra__variacion' + (dif < 0 ? ' cifra__variacion--bien' : dif > 0 ? ' cifra__variacion--mal' : '');
      v.innerHTML = icono(dif < 0 ? 'flecha-abajo' : dif > 0 ? 'flecha-arriba' : 'igual') + pp(dif, f.dec) + ' frente a hoy (' + pct(f.B1.v, f.dec) + ')';
    });
  }
  function selectorModelo() {
    return '<div class="control-rotulado"><span class="control-rotulado__rotulo" aria-hidden="true">Modelo:</span>' +
      '<fieldset class="segmentado segmentado--pequeno" id="dem-modelo" aria-label="Modelo mostrado en «Con el modelo»"><legend>Modelo</legend>' +
      '<label class="segmentado__opcion"><input type="radio" name="dem-modelo" value="final"' + (modelo === 'final' ? ' checked' : '') + '><span class="segmentado__etiqueta">Modelo final (E11)</span></label>' +
      '<label class="segmentado__opcion"><input type="radio" name="dem-modelo" value="hibrido"' + (modelo === 'hibrido' ? ' checked' : '') + '><span class="segmentado__etiqueta">Híbrido (E12)</span></label>' +
      '</fieldset></div>';
  }

  // ---- 1. Entradilla y fichas ------------------------------------------------------------------------------------
  function seccionFichas() {
    const definicion = valor('inicio_regla_manual_definicion', null, '');
    const intro = '«Hoy» es la regla manual de Sobusa' + (definicion ? ': ' + esc(String(definicion).replace(/\.$/, '')) + ' ' + fuente('inicio_regla_manual_definicion', null, 'Qué hace Sobusa hoy') : '') +
      '. «Con el modelo» es el pronóstico del modelo final (E11) o del híbrido (E12), el recomendado para producción. El error se mide en ' + ANIO + ' como pasajeros mal estimados de cada 100, a ' + hTexto() + ' de antelación.';
    return seccion('dem-error', 'El error a ' + hTexto(), intro, htmlFichas(), selectorModelo());
  }

  // ---- 2. Las series: real, regla manual y modelo ------------------------------------------------------------------
  function indexarSerie(id) {
    const cols = campo(id, 'columnas'), filas = campo(id, 'filas');
    if (!Array.isArray(cols) || !Array.isArray(filas)) { anotarFaltante(id); return null; }
    const ix = {};
    cols.forEach(function (c, i) { ix[c] = i; });
    return { ix: ix, filas: filas };
  }
  // Suma las filas de la ruta elegida (o de las tres) por la columna x: { xs: [...], por: { real: [], B1: [], … } }.
  function agregar(s, colX, rutaSel) {
    const acum = new Map();
    s.filas.forEach(function (fila) {
      if (rutaSel !== TODAS && fila[s.ix.ruta] !== rutaSel) return;
      const x = fila[s.ix[colX]];
      let a = acum.get(x);
      if (!a) { a = {}; COLS.forEach(function (c) { a[c] = 0; }); acum.set(x, a); }
      COLS.forEach(function (c) { const v = fila[s.ix[c]]; if (num(v)) a[c] += v; });
    });
    const xs = Array.from(acum.keys()).sort(function (a, b) { return typeof a === 'number' && typeof b === 'number' ? a - b : (a < b ? -1 : a > b ? 1 : 0); });
    const por = {};
    COLS.forEach(function (c) { por[c] = xs.map(function (x) { return acum.get(x)[c]; }); });   // sin redondear: se redondea solo al mostrar
    return { xs: xs, por: por };
  }
  function chipsRuta() {
    return '<div class="chips" role="group" aria-label="Ruta" id="dem-rutas">' + [TODAS].concat(RUTAS).map(function (r) {
      const c = RUTA_CLASE[r];
      return '<button class="chip" type="button" data-ruta="' + esc(r) + '" aria-pressed="' + (r === ruta ? 'true' : 'false') + '"' + (c ? ' style="--c: var(--ruta-' + c + ')"' : '') + '>' +
        (c ? '<span class="chip__punto" aria-hidden="true"></span>' : '') + esc(r === TODAS ? 'Todas las rutas' : r) + '</button>';
    }).join('') + '</div>';
  }
  function marcarChips() {
    cont.querySelectorAll('#dem-rutas .chip').forEach(function (b) { b.setAttribute('aria-pressed', b.dataset.ruta === ruta ? 'true' : 'false'); });
  }
  function seriesDe(d) {
    const mk = claveModelo();
    return [
      { nombre: SERIES.real, rol: 'real', datos: d.por.real, z: 3 },
      { nombre: SERIES.B1, rol: 'hoy', datos: d.por.B1, tenue: escenario !== 'hoy', z: 2 },
      { nombre: SERIES[mk], rol: 'modelo', datos: d.por[mk], tenue: escenario === 'hoy', z: 2 },
    ];
  }
  function leyendaSeries(series) { return series.map(function (s) { return itemLeyenda(s.nombre, s.rol, s.tenue); }).join(''); }
  function opcionLineas(etiquetasX, series, nombreEjeY, tituloTooltip, simbolos) {
    const T = global.TEMA_ECHARTS;
    return {
      legend: { show: false, data: series.map(function (s) { return s.nombre; }) },
      tooltip: { trigger: 'axis', formatter: function (ps) {
        return '<strong>' + esc(tituloTooltip(ps[0].dataIndex)) + '</strong><br>' + ps.map(function (q) { return q.marker + esc(q.seriesName) + ': ' + n(q.value, 0); }).join('<br>');
      } },
      grid: { left: 8, right: 16, top: 28, bottom: 8, containLabel: true },
      xAxis: { type: 'category', data: etiquetasX, boundaryGap: !!simbolos, axisLabel: { hideOverlap: true } },
      yAxis: { type: 'value', name: nombreEjeY, nameLocation: 'end', nameGap: 12, nameTextStyle: { align: 'left' }, axisLabel: { formatter: function (v) { return n(v, 0); } } },
      series: series.map(function (s) {
        const estilo = T.serie(s.rol);
        const base = { name: s.nombre, type: 'line', data: s.datos, showSymbol: !!simbolos, symbolSize: 7, z: s.z || 2, emphasis: { focus: 'none' } };
        if (s.tenue) { estilo.lineStyle = Object.assign({}, estilo.lineStyle, { opacity: 0.45 }); estilo.itemStyle = Object.assign({}, estilo.itemStyle, { opacity: 0.45 }); }
        return Object.assign(base, estilo);
      }),
    };
  }
  function grafico(clave, el) {
    if (graficos[clave] && !graficos[clave].isDisposed() && graficos[clave].getDom() === el) return graficos[clave];
    if (graficos[clave] && !graficos[clave].isDisposed()) graficos[clave].dispose();
    graficos[clave] = global.TEMA_ECHARTS.init(global.echarts, el);
    return graficos[clave];
  }
  function tablaMensual(d) {
    const meses = {}, orden = [];
    d.xs.forEach(function (dia, i) {
      const m = String(dia).slice(0, 7);
      if (!meses[m]) { meses[m] = { real: 0, B1: 0, E11_V4: 0, hibrido: 0 }; orden.push(m); }
      ['real', 'B1', 'E11_V4', 'hibrido'].forEach(function (c) { meses[m][c] += d.por[c][i] || 0; });
    });
    return tabla('Totales por mes, ' + rutaTexto() + ' (pasajeros)', ['Mes', SERIES.real, SERIES.B1, SERIES.E11_V4, SERIES.hibrido], orden.map(function (m) {
      const x = meses[m];
      return { celdas: [esc(MESES[+m.slice(5, 7) - 1] + ' ' + m.slice(0, 4)), n(x.real), n(x.B1), n(x.E11_V4), n(x.hibrido)] };
    }), { sinMarco: true, compacta: true });
  }
  function tablaHoras(d) {
    return tabla('Pasajeros por hora de salida, ' + rutaTexto(), ['Hora', SERIES.real, SERIES.B1, SERIES.E11_V4, SERIES.hibrido], d.xs.map(function (h, i) {
      return { celdas: [n(h) + FINO + 'h', n(d.por.real[i]), n(d.por.B1[i]), n(d.por.E11_V4[i]), n(d.por.hibrido[i])] };
    }), { sinMarco: true, compacta: true });
  }
  function pintarDiaria() {
    const fig = cont.querySelector('#dem-g-diaria');
    const el = fig && fig.querySelector('.grafico__lienzo');
    if (!el || !serieDiaria || !global.echarts) return;
    const d = agregar(serieDiaria, 'dia', ruta);
    const series = seriesDe(d);
    const g = grafico('diaria', el);
    g.setOption(opcionLineas(d.xs.map(function (x) { return F.fechaCorta(x); }), series, 'pasajeros/día', function (i) { return F.fechaLarga(d.xs[i]); }, false), { notMerge: true });
    ponerLeyenda(fig, leyendaSeries(series), function () { return graficos.diaria; });
    el.setAttribute('aria-label', 'Pasajeros por día en ' + ANIO + ', ' + rutaTexto() + ': lo real frente a la regla manual y al ' + SERIES[claveModelo()].toLowerCase());
    fig.querySelector('[data-sub]').textContent = 'Cada día de ' + ANIO + ', ' + rutaTexto() + ': lo que de verdad pasó (tinta), lo que decía la regla manual (gris) y lo que decía el ' + SERIES[claveModelo()].toLowerCase() + ' (verde azulado) a ' + hTexto() + '.';
    fig.querySelector('.grafico__tabla').innerHTML = tablaMensual(d);
  }
  function pintarHora() {
    const fig = cont.querySelector('#dem-g-hora');
    const el = fig && fig.querySelector('.grafico__lienzo');
    if (!el || !serieHora || !global.echarts) return;
    const d = agregar(serieHora, 'hora', ruta);
    const series = seriesDe(d);
    const dia = campo('demanda_serie_hora_ejemplo', 'dia');
    const g = grafico('hora', el);
    g.setOption(opcionLineas(d.xs.map(function (h) { return n(h) + FINO + 'h'; }), series, 'pasajeros/hora', function (i) { return (dia ? F.fechaLarga(dia) + ', ' : '') + n(d.xs[i]) + FINO + 'h'; }, true), { notMerge: true });
    ponerLeyenda(fig, leyendaSeries(series), function () { return graficos.hora; });
    el.setAttribute('aria-label', 'Pasajeros por hora de salida el ' + (dia ? F.fechaLarga(dia) : 'día de ejemplo') + ', ' + rutaTexto() + ': lo real frente a la regla manual y al ' + SERIES[claveModelo()].toLowerCase());
    fig.querySelector('[data-sub]').textContent = 'Un día de ejemplo, ' + rutaTexto() + ': los pasajeros que subieron en cada hora de salida frente a lo pronosticado a ' + hTexto() + ' por la regla manual y por el ' + SERIES[claveModelo()].toLowerCase() + '.';
    fig.querySelector('.grafico__tabla').innerHTML = tablaHoras(d);
  }
  function seccionSeries() {
    serieDiaria = indexarSerie('demanda_serie_diaria_2025');
    serieHora = indexarSerie('demanda_serie_hora_ejemplo');
    const dia = campo('demanda_serie_hora_ejemplo', 'dia');
    const tot = campo('demanda_serie_diaria_2025', 'total_2025') || {};
    const intro = 'Las tres líneas de cada gráfico son el mismo dato visto de tres formas: lo que pasó, lo que suponía la regla manual y lo que decía el modelo. Donde las líneas se separan está el error.' +
      (num(tot.real) ? ' En ' + ANIO + ' subieron ' + n(tot.real) + ' pasajeros ' + fuente('demanda_serie_diaria_2025', null, 'Serie diaria de ' + ANIO, { clave: 'total_2025.real (suma de la serie)', valor: tot.real }) + '.' : '');
    const diaria = figura({ id: 'dem-g-diaria', titulo: 'Pasajeros por día en ' + ANIO, sub: '', aria: 'Pasajeros por día en ' + ANIO, leyenda: '', tabla: '',
      pie: '<span>La tabla resume la serie diaria en totales por mes. Los pronósticos son a ' + hTexto() + '.</span>' + fuente('demanda_serie_diaria_2025', null, 'Serie diaria de ' + ANIO) });
    const hora = figura({ id: 'dem-g-hora', titulo: 'Un día por hora: ' + (dia ? F.fechaLarga(dia) : 'día de ejemplo'), sub: '', aria: 'Pasajeros por hora de salida del día de ejemplo', leyenda: '', tabla: '', bajo: true,
      pie: '<span>Es el día del hallazgo de la pantalla Ciudad: <a href="#ciudad">verlo en la calle</a>.</span>' + fuente('demanda_serie_hora_ejemplo', null, 'Día de ejemplo por hora') });
    return seccion('dem-series', 'Lo que pasó y lo que se pronosticó', intro, diaria + hora, chipsRuta());
  }

  // ---- 3. Dónde se equivoca más: la tabla de errores ---------------------------------------------------------------
  function filasTabla(id, claves, rotulo, titulo) {
    const v = valor(id, null, null);
    const filas = [{ grupo: titulo, extra: fuente(id, null, titulo) }];
    if (!v || typeof v !== 'object') { filas.push({ celdas: ['Sin datos (' + esc(id) + ')', '—', '—', '—', '—'] }); return filas; }
    const nombres = claves || Object.keys((v.B1 || v.E11_V4 || {}));
    nombres.forEach(function (k) {
      const vals = ['B1', 'E1_V0', 'E11_V4', 'hibrido'].map(function (m) { return v[m] && num(v[m][k]) ? v[m][k] : null; });
      filas.push({ celdas: [rotulo(k)].concat(vals.map(function (x) { return pct(x); })), mejor: mejorIndice(vals) });
    });
    return filas;
  }
  function seccionTabla() {
    const vt = valor('demanda_wape_por_tipo_dia', null, {}) || {};
    const vr = valor('demanda_wape_por_ruta', null, {}) || {};
    const peorDe = function (obj) { let k = null; Object.keys(obj || {}).forEach(function (x) { if (num(obj[x]) && (k === null || obj[x] > obj[k])) k = x; }); return k; };
    const tipoPeor = peorDe(vt.E11_V4), rutaPeor = peorDe(vr.E11_V4);
    let intro = '';
    if (tipoPeor && rutaPeor) {
      intro = 'Donde más se equivocan todos es en ' + esc(String(tipoPeor).toLowerCase()).replace('/', ' y ') + ': la regla manual, ' + pct(vt.B1 && vt.B1[tipoPeor]) + ' ' + fuente('demanda_wape_por_tipo_dia', 'B1.' + tipoPeor, 'Regla manual, ' + tipoPeor) +
        '; el modelo final, ' + pct(vt.E11_V4 && vt.E11_V4[tipoPeor]) + ' ' + fuente('demanda_wape_por_tipo_dia', 'E11_V4.' + tipoPeor, 'Modelo final, ' + tipoPeor) +
        '; el híbrido, ' + pct(vt.hibrido && vt.hibrido[tipoPeor]) + ' ' + fuente('demanda_wape_por_tipo_dia', 'hibrido.' + tipoPeor, 'Híbrido, ' + tipoPeor) +
        '. Por ruta, la más difícil es ' + esc(rutaPeor) + ' (modelo final: ' + pct(vr.E11_V4 && vr.E11_V4[rutaPeor]) + ' ' + fuente('demanda_wape_por_ruta', 'E11_V4.' + rutaPeor, 'Modelo final, ' + rutaPeor) + '). El mejor valor de cada fila va en color.';
    }
    const H = hClave();
    const filas = []
      .concat(filasTabla('demanda_wape_por_ruta', RUTAS, claveRuta, 'Por ruta'))
      .concat(filasTabla('demanda_wape_por_tipo_dia', null, function (k) { return esc(String(k).replace('/', ' y ')); }, 'Por tipo de día'))
      .concat(filasTabla('demanda_wape_por_franja', null, function (k) { return esc(String(k).replace('-', '–')); }, 'Por franja del día (hora de salida)'))
      .concat(filasTabla('demanda_wape_antelacion', null, function (k) { return n(+k) + ' días' + (String(k) === H ? ' (el horizonte principal)' : ''); }, 'Por antelación del pronóstico'));
    const t = tabla('', ['', SERIES.B1, SERIES.E1_V0, SERIES.E11_V4, SERIES.hibrido], filas);
    const notaFranja = campo('demanda_wape_por_franja', 'nota');
    const notaAntel = campo('demanda_wape_antelacion', 'nota');
    const notas = '<ul class="demanda__lista texto-2">' + (notaFranja ? '<li>' + esc(notaFranja) + '</li>' : '') + (notaAntel ? '<li>' + esc(notaAntel) + '</li>' : '') + '</ul>';

    // El híbrido por antelación: una simulación de uso real (sin revisor independiente).
    const em = valor('demanda_hibrido_antelacion_emulacion', null, null);
    let emul = '';
    if (em && typeof em === 'object') {
      const claves = Object.keys(em).filter(function (k) { return k !== 'total'; }).sort(function (a, b) { return parseInt(a.replace(/\D/g, ''), 10) - parseInt(b.replace(/\D/g, ''), 10); });
      const filasEm = claves.concat(em.total ? ['total'] : []).map(function (k) {
        const x = em[k] || {};
        const vals = [x.hibrido, x.V4];
        return { celdas: [k === 'total' ? 'Todas las antelaciones' : n(parseInt(k.replace(/\D/g, ''), 10)) + ' días', pct(x.hibrido), pct(x.V4), num(x.semanas_mejor) && num(x.semanas) ? n(x.semanas_mejor) + ' de ' + n(x.semanas) : '—'], mejor: mejorIndice(vals), clase: k === 'total' ? 'tabla__fila-total' : '' };
      });
      const tot = em.total || {};
      emul = '<div class="pila"><h3>El híbrido según la antelación, en uso real</h3><p class="demanda__prosa">' + esc(campo('demanda_hibrido_antelacion_emulacion', 'que_es') || '') +
        (num(tot.dif) ? '. En total, el híbrido mejora al modelo final en ' + pp(tot.dif) + ' ' + ic(tot.ic_inf, tot.ic_sup) + ' y gana en ' + n(tot.semanas_mejor) + ' de ' + n(tot.semanas) + ' semanas ' + fuente('demanda_hibrido_antelacion_emulacion', 'total.dif', 'Diferencia total híbrido − modelo final') : '') + '.</p>' +
        tabla('', ['Antelación', SERIES.hibrido, SERIES.E11_V4, 'Semanas en que gana el híbrido'], filasEm, { compacta: true, textoEn: [3] }) +
        '<p class="demanda__nota-verificado texto-2">' + chipVerificado('demanda_hibrido_antelacion_emulacion') + '<span>' + esc(campo('demanda_hibrido_antelacion_emulacion', 'revision') || '') + '</span>' + fuente('demanda_hibrido_antelacion_emulacion', null, 'Emulación de producción del híbrido') + '</p></div>';
    }
    return seccion('dem-tabla', 'Dónde se equivoca más', intro, t + notas + emul + seccionComoSeCalculo());
  }

  // ---- 4. Ver cómo se calculó ---------------------------------------------------------------------------------------
  function seccionComoSeCalculo() {
    const pr = valor('demanda_protocolo', null, {}) || {};
    const hs = pr.horizontes_E11 && typeof pr.horizontes_E11 === 'object' ? Object.keys(pr.horizontes_E11).map(Number).filter(num).sort(function (a, b) { return a - b; }) : [];
    const protocolo = '<div class="pila"><h3>El protocolo</h3><p>' +
      n(pr.pliegues) + ' pliegues mensuales de ' + ANIO + ' ' + fuente('demanda_protocolo', 'pliegues', 'Pliegues') + ', cada uno entrenado solo con datos anteriores al mes que se prueba. Se evalúan ' + n(pr.franjas_prueba) + ' franjas ruta × día × hora de salida ' + fuente('demanda_protocolo', 'franjas_prueba', 'Franjas de prueba') +
      ' de un panel de ' + n(pr.franjas_panel) + ' ' + fuente('demanda_protocolo', 'franjas_panel', 'Franjas del panel') + (hs.length ? ', con antelaciones de ' + hs.map(function (h) { return n(h); }).join(' y ') + ' días' : '') + '.</p>' +
      (pr.metrica ? '<p>Métricas: ' + md(pr.metrica) + ' ' + fuente('demanda_protocolo', 'metrica', 'Métricas del protocolo') + '</p>' : '') + '</div>';

    const sz = valor('demanda_sesgo', null, {}) || {};
    const filasSesgo = [['B1', 'B1'], ['E1_V0', 'E1_V0'], ['E11_V4', 'E11_V4'], ['hibrido', 'hibrido']].map(function (par) {
      const k = par[0];
      return { celdas: [SERIES[k], num(sz[k + '_pct']) ? sg(sz[k + '_pct']) + FINO + '%' : '—', num(sz[k + '_pax_franja']) ? sg(sz[k + '_pax_franja'], 1) : '—'] };
    });
    const sesgo = '<div class="pila"><h3>El sesgo</h3><p>Pronosticado menos real, sobre el real, a ' + hTexto() + ' en ' + ANIO + ': positivo es pronosticar de más. ' + fuente('demanda_sesgo', null, 'Sesgo del pronóstico') + '</p>' +
      tabla('', ['', 'Sesgo', 'Pasajeros por franja'], filasSesgo, { compacta: true }) + '</div>';

    const iv = valor('demanda_intervalo_e3', null, {}) || {};
    const intervalo = '<div class="pila"><h3>El intervalo del pronóstico</h3><p>El pronóstico por cuantiles de E3 da un intervalo p10–p90: en ' + ANIO + ' cubrió el ' + pct(iv.cobertura_p10_p90_pct, 1) + ' de las franjas ' + fuente('demanda_intervalo_e3', 'cobertura_p10_p90_pct', 'Cobertura del intervalo p10–p90') +
      ' (el ' + pct(iv.pct_bajo_p10, 1) + ' quedó por debajo ' + fuente('demanda_intervalo_e3', 'pct_bajo_p10', 'Por debajo del p10') + ' y el ' + pct(iv.pct_sobre_p90, 1) + ' por encima ' + fuente('demanda_intervalo_e3', 'pct_sobre_p90', 'Por encima del p90') +
      '). Para programar buses conviene un cuantil alto, no la mediana: quedarse corto cuesta más que sobrar.</p></div>';
    return desplegable('dem-como', 'Ver cómo se calculó', protocolo + sesgo + intervalo);
  }

  // ---- 5. Qué ayuda y qué no ---------------------------------------------------------------------------------------
  function veredicto(inf, sup) {
    if (num(sup) && sup < 0) return '<span class="chip chip--bien">' + icono('bien') + 'Ayuda</span>';
    if (num(inf) && inf > 0) return '<span class="chip chip--atencion">' + icono('alerta') + 'Empeora</span>';
    return '<span class="chip">' + icono('igual') + 'No cambia</span>';
  }
  function seccionAyuda() {
    const si = valor('demanda_lo_que_si_ayuda', null, {}) || {};
    const no = valor('demanda_lo_que_no_ayuda', null, {}) || {};
    const NOMBRES_SI = { V3_vs_V2: 'Peso bajo a los días atípicos y a las franjas con fallas (V3 frente a V2)', V4_vs_V0: 'Todo junto: el modelo final frente al primero (V4 frente a V0)' };
    const NOMBRES_NO = { calendarios_V1_vs_V0: 'Más variables de calendario (V1 frente a V0)', climatologia_V2_vs_V0: 'Climatología media (V2 frente a V0)', lluvia_observada_N_vs_V3: 'Lluvia observada (N frente a V3)', recencia_V5_vs_V3: 'Más peso a lo reciente (V5 frente a V3)', ajuste_hiperparametros: 'Ajuste de hiperparámetros' };
    const filas = [];
    Object.keys(NOMBRES_SI).forEach(function (k) {
      const x = si[k];
      if (!x || typeof x !== 'object') return;
      filas.push({ celdas: [NOMBRES_SI[k] + ' ' + fuente('demanda_lo_que_si_ayuda', k + '.dif', NOMBRES_SI[k]), pp(x.dif), ic(x.ic_inf, x.ic_sup), num(x.meses_mejor) ? 'Mejor en ' + deMeses(x.meses_mejor) : '', veredicto(x.ic_inf, x.ic_sup)] });
    });
    Object.keys(NOMBRES_NO).forEach(function (k) {
      const x = no[k];
      if (!x || typeof x !== 'object') return;
      filas.push({ celdas: [NOMBRES_NO[k] + ' ' + fuente('demanda_lo_que_no_ayuda', k + '.dif', NOMBRES_NO[k]), pp(x.dif), ic(x.ic_inf, x.ic_sup), '', veredicto(x.ic_inf, x.ic_sup)] });
    });
    const mes = num(si.mes_mayor_ganancia) ? MESES_LARGOS[si.mes_mayor_ganancia - 1] : null;
    const intro = 'De todo lo que se probó en E11, lo único que mejora el pronóstico es no aprender de datos corruptos: dar poco peso a los días atípicos y a las franjas con fallas de registro' +
      (si.V3_vs_V2 && num(si.V3_vs_V2.dif) ? ' (' + pp(si.V3_vs_V2.dif) + ' de WAPE ' + ic(si.V3_vs_V2.ic_inf, si.V3_vs_V2.ic_sup) + ' ' + fuente('demanda_lo_que_si_ayuda', 'V3_vs_V2.dif', 'V3 frente a V2') + ')' : '') +
      '. Más calendarios, el clima o la lluvia del día no cambian nada que el intervalo de confianza del ' + IC + FINO + '% distinga de cero.' +
      (mes && num(si.agosto_sesgo_V0_pct) && num(si.agosto_sesgo_V4_pct) ? ' La ganancia se concentra en ' + mes + ', el mes con más fallas: el primer modelo pronosticaba ' + sg(si.agosto_sesgo_V0_pct, 1) + FINO + '% ' + fuente('demanda_lo_que_si_ayuda', 'agosto_sesgo_V0_pct', 'Sesgo del primer modelo en ' + mes) + ' y el final, ' + sg(si.agosto_sesgo_V4_pct, 1) + FINO + '% ' + fuente('demanda_lo_que_si_ayuda', 'agosto_sesgo_V4_pct', 'Sesgo del modelo final en ' + mes) + '; sin ese mes la mejora es ' + pp(si.sin_agosto) + ' ' + fuente('demanda_lo_que_si_ayuda', 'sin_agosto', 'Mejora sin ' + mes) + '.' : '');
    const t = tabla('', ['Cambio probado', 'Diferencia de WAPE', 'IC ' + IC + FINO + '%', 'Meses', 'Veredicto'], filas, { textoEn: [2, 3, 4] });

    // Tarjetas: lluvia, rutas, días atípicos.
    const ll = valor('demanda_lluvia', null, {}) || {};
    const ciclo = ll.ciclo_pct_por_intensidad || {};
    const filasCiclo = Array.isArray(ciclo.intensidad) ? ciclo.intensidad.map(function (x, i) { return { celdas: [esc(typeof x === 'number' ? n(x) : x), sg(ciclo.desvio_ciclo_pct && ciclo.desvio_ciclo_pct[i], 2) + FINO + '%'] }; }) : [];
    const icLl = Array.isArray(ll.desvio_pax_lluvia_moderada_ic95) ? ll.desvio_pax_lluvia_moderada_ic95 : [];
    const lluvia = '<article class="tarjeta demanda__tarjeta pila"><h3>La lluvia</h3>' +
      '<div class="cifras">' + cifraLlana('De la variación diaria, la lluvia explica', num(ll.r2_variacion_diaria) ? pct(ll.r2_variacion_diaria * 100, 1) : '—', '', 'R² frente a la línea base', fuente('demanda_lluvia', 'r2_variacion_diaria', 'R² de la lluvia')) +
      cifraLlana('Pasajeros con lluvia moderada', num(ll.desvio_pax_lluvia_moderada_pct) ? sg(ll.desvio_pax_lluvia_moderada_pct, 1) + FINO + '%' : '—', '', 'IC ' + IC + FINO + '% ' + ic(icLl[0], icLl[1], 1), fuente('demanda_lluvia', 'desvio_pax_lluvia_moderada_pct', 'Desvío de pasajeros con lluvia moderada')) + '</div>' +
      (filasCiclo.length ? '<p>El tiempo de vuelta sí sube con la intensidad de la lluvia (mm/h):</p>' + tabla('', ['Lluvia (mm/h)', 'Tiempo de vuelta'], filasCiclo, { compacta: true }) : '') +
      (ll.mejor_variante ? '<p>' + esc(ll.mejor_variante) + ' ' + fuente('demanda_lluvia', 'mejor_variante', 'Variantes con clima') + '</p>' : '') + '</article>';

    const co = valor('demanda_correlacion_rutas', null, {}) || {};
    const um = valor('demanda_un_modelo_por_ruta', null, {}) || {};
    const ot = valor('demanda_otras_rutas_como_variable', null, {}) || {};
    const rutas = '<article class="tarjeta demanda__tarjeta pila"><h3>Las tres rutas se mueven juntas</h3>' +
      '<p>Correlación de los niveles diarios: ' + esc(RUTAS[0]) + ' y ' + esc(RUTAS[1]) + ', ' + n(co.corr_SIL_CRA54, 3) + ' ' + fuente('demanda_correlacion_rutas', 'corr_SIL_CRA54', 'Correlación ' + RUTAS[0] + ' y ' + RUTAS[1]) +
      '; ' + esc(RUTAS[0]) + ' y ' + esc(RUTAS[2]) + ', ' + n(co.corr_SIL_CL72, 3) + ' ' + fuente('demanda_correlacion_rutas', 'corr_SIL_CL72', 'Correlación ' + RUTAS[0] + ' y ' + RUTAS[2]) +
      '; ' + esc(RUTAS[1]) + ' y ' + esc(RUTAS[2]) + ', ' + n(co.corr_CRA54_CL72, 3) + ' ' + fuente('demanda_correlacion_rutas', 'corr_CRA54_CL72', 'Correlación ' + RUTAS[1] + ' y ' + RUTAS[2]) +
      '. El ' + pct(co.pct_var_componente_comun, 1) + ' del desvío diario es un choque común a las tres ' + fuente('demanda_correlacion_rutas', 'pct_var_componente_comun', 'Componente común del desvío') + '.</p>' +
      '<p><strong>Un modelo por ruta</strong> no mejora al conjunto: ' + pp(um.dif_media_mensual_pp) + ' al mes (p = ' + n(um.p_t_pareada, 2) + '; mejor en ' + deMeses(um.meses_mejor) + ') ' + fuente('demanda_un_modelo_por_ruta', 'dif_media_mensual_pp', 'Un modelo por ruta frente a uno conjunto') + '.</p>' +
      '<p><strong>La demanda reciente de las otras rutas</strong> como variable tampoco: ' + pp(ot.dif_media_mensual_pp) + ' (p = ' + n(ot.p_t_pareada, 2) + '; mejor en ' + deMeses(ot.meses_mejor) + ') ' + fuente('demanda_otras_rutas_como_variable', 'dif_media_mensual_pp', 'Otras rutas como variable') + '.</p></article>';

    const at = valor('demanda_dias_atipicos', null, {}) || {};
    const umbral = (/bajo_(\d+)_/.exec(Object.keys(at).join(' ')) || [])[1];
    const conf = at.confianza || {};
    const atipicos = '<article class="tarjeta demanda__tarjeta pila"><h3>Los días atípicos</h3>' +
      '<div class="cifras">' + cifraLlana('Días con las tres rutas' + (umbral ? ' más de un ' + n(+umbral) + FINO + '%' : '') + ' por debajo, fuera del calendario', n(at.dias_tres_rutas_bajo_10_fuera_calendario), 'días', '', fuente('demanda_dias_atipicos', 'dias_tres_rutas_bajo_10_fuera_calendario', 'Días con las tres rutas por debajo')) +
      cifraLlana('Días investigados uno a uno', n(at.dias_investigados), 'días', 'Causa con confianza alta en ' + n(conf.alta) + ', media en ' + n(conf.media) + ' y baja en ' + n(conf.baja) + '.', fuente('demanda_dias_atipicos', 'dias_investigados', 'Días investigados')) +
      cifraLlana('No predecibles, con peso bajo en el entrenamiento', n(at.no_predecibles_peso_025), 'días', n(at.filas_con_peso) + ' franjas con peso reducido.', fuente('demanda_dias_atipicos', 'no_predecibles_peso_025', 'Días no predecibles con peso bajo')) + '</div>' +
      '<p>Paros, aguaceros, fallas de registro y días sin explicación: el modelo no aprende de ellos, pero tampoco los anticipa.</p></article>';

    // Otros métodos en la misma banda.
    const om = valor('demanda_otros_metodos', null, {}) || {};
    const NOMBRES_OM = { clasicos_E4_mejor: 'Clásicos, el mejor de E4 (GLM + SARIMA)', cuantiles_E3_p50: 'Cuantiles de E3 (mediana)', plantillas_E5_k4: 'Plantillas de E5', chronos2_solo: 'Chronos-2 solo (fundacional)', timesfm25_xreg: 'TimesFM 2.5 con variables (fundacional)', tft: 'TFT (red neuronal)' };
    const wFinal = primero([['inicio_error_modelo_final', null]]).v;
    const filasOm = Object.keys(NOMBRES_OM).filter(function (k) { return num(om[k]); }).map(function (k) {
      return { celdas: [NOMBRES_OM[k] + ' ' + fuente('demanda_otros_metodos', k, NOMBRES_OM[k]), pct(om[k]), num(wFinal) ? pp(om[k] - wFinal) : '—'] };
    });
    const otros = '<div class="pila"><h3>Otros métodos, en la misma banda</h3><p class="demanda__prosa">Modelos clásicos, de cuantiles, plantillas, fundacionales y redes quedan todos cerca del modelo final' + (num(wFinal) ? ' (' + pct(wFinal) + ' ' + fuente('inicio_error_modelo_final', null, 'Modelo final') + ')' : '') + ': el techo lo ponen los datos, no el algoritmo. La comparación completa está en <a href="#modelo">Modelo</a>.</p>' +
      tabla('', ['Método', 'WAPE a ' + hTexto(), 'Frente al modelo final'], filasOm, { compacta: true }) +
      '<p class="demanda__nota-verificado texto-2">' + chipVerificado('demanda_otros_metodos') + '<span>' + esc(campo('demanda_otros_metodos', 'revision') || '') + '</span></p></div>';

    return seccion('dem-ayuda', 'Qué ayuda y qué no', intro, t + '<div class="demanda__tarjetas">' + lluvia + rutas + atipicos + '</div>' + otros);
  }

  // ---- 6. Los datos tienen problemas (aviso de atención) ----------------------------------------------------------
  function seccionDatos() {
    const dp = valor('demanda_dias_con_problema_datos', null, {}) || {};
    const textos = campo('demanda_dias_con_problema_datos', 'textos') || {};
    const alg = dp.algun_problema || {};
    const lista = Object.keys(dp).filter(function (k) { return k !== 'algun_problema' && dp[k] && typeof dp[k] === 'object'; }).map(function (k) {
      return '<li>' + n(dp[k].dias) + ' días (' + pct(dp[k].pct, 1) + '): ' + esc(textos[k] || k.replace(/_/g, ' ')) + ' ' + fuente('demanda_dias_con_problema_datos', k + '.dias', textos[k] || k) + '</li>';
    }).join('');
    const pc = valor('demanda_pax_cancelados_corrieron_2025', null, {}) || {};
    const p1 = '<p>' + n(alg.dias) + ' días de ' + ANIO_INICIO + ' a ' + ANIO + ' (el ' + pct(alg.pct, 1) + ') tienen algún problema de datos ' + fuente('demanda_dias_con_problema_datos', 'algun_problema.dias', 'Días con algún problema') + ':</p><ul class="demanda__lista">' + lista + '</ul>';
    const p2 = '<p>El más grande: ' + n(pc.pasajeros) + ' pasajeros de ' + ANIO + ' viajaron en buses marcados como cancelados que sí corrieron ' + fuente('demanda_pax_cancelados_corrieron_2025', 'pasajeros', 'Pasajeros en viajes cancelados que corrieron') +
      '. El objetivo con el que se entrenó y se midió el modelo (viajes válidos) los pierde: son el ' + pct(pc.pct_del_corregido, 1) + ' del objetivo corregido ' + fuente('demanda_pax_cancelados_corrieron_2025', 'pct_del_corregido', 'Parte del objetivo corregido') +
      ', que queda ' + sg(pc.corregido_sobre_original_pct, 2) + FINO + '% por encima del original ' + fuente('demanda_pax_cancelados_corrieron_2025', 'corregido_sobre_original_pct', 'Corregido sobre original') + '.</p>';

    // E13: el modelo contra el objetivo corregido.
    const oc = valor('demanda_objetivo_corregido', null, {}) || {};
    const a25 = oc[ANIO] || {}, a24 = oc[ANIO_PRUEBA] || {};
    const COLS_E13 = ['V4', 'V4_reescalado', 'V4c', 'hibrido_V4c'];
    const fila = function (rotulo, id, obj, mapa, mayorEsMejor, dec) {
      const vals = COLS_E13.map(function (c) { const k = mapa ? mapa[c] : c; return obj && num(obj[k]) ? obj[k] : null; });
      return { celdas: [rotulo + ' ' + fuente(id, null, rotulo)].concat(vals.map(function (v) { return pct(v, dec); })), mejor: mejorIndice(vals, mayorEsMejor) };
    };
    const MAPA_OC = { V4: 'V4', V4_reescalado: 'V4_reescalado', V4c: 'V4c_reentrenado', hibrido_V4c: 'hibrido_V4c' };
    const filasE13 = [
      fila('Error de ' + ANIO + ' (WAPE)', 'demanda_objetivo_corregido', a25, MAPA_OC, false, 2),
      fila('Error de ' + ANIO_PRUEBA + ' (WAPE)', 'demanda_objetivo_corregido', a24, MAPA_OC, false, 2),
      fila('Error medio del total diario', 'demanda_error_total_diario_corregido', valor('demanda_error_total_diario_corregido', null, null), null, false, 1),
      fila('Horas en que faltarían buses', 'demanda_horas_faltan_buses', valor('demanda_horas_faltan_buses', null, null), null, false, 1),
      fila('Horas con los buses exactos', 'demanda_horas_buses_exactos', valor('demanda_horas_buses_exactos', null, null), null, true, 1),
    ];
    const tE13 = '<div class="demanda__aviso-tabla">' + tabla('', ['Contra el objetivo corregido', 'Modelo final tal cual', 'Modelo final reescalado', 'Reentrenado (V4c)', 'Híbrido sobre V4c'], filasE13, { compacta: true }) + '</div>';

    // La nota de la contradicción C17: el objetivo corregido no es comparable con el error oficial.
    const g1 = oc['ganancia_V4c_vs_V4_reescalado_' + ANIO] || {}, g2 = oc['ganancia_hibrido_vs_V4c_' + ANIO] || {};
    const total = num(a25.V4) && num(a25.V4c_reentrenado) ? a25.V4 - a25.V4c_reentrenado : null;
    const nivel = num(a25.V4) && num(a25.V4_reescalado) ? a25.V4 - a25.V4_reescalado : null;
    const c17 = contradiccion('C17');
    const p3 = '<p><strong>Estas cifras no se comparan con el error de arriba</strong>: el objetivo es otro (más grande), así que el error baja aunque el modelo sea el mismo.' +
      (num(total) && num(nivel) ? ' De ' + pct(a25.V4) + ' a ' + pct(a25.V4c_reentrenado) + ' hay ' + n(total, 2) + ' puntos, pero ' + n(nivel, 2) + ' son solo cambio de nivel ' + fuente('demanda_objetivo_corregido', ANIO + '.V4_reescalado', 'Modelo final reescalado, ' + ANIO) + '.' : '') +
      (num(g1.dif) ? ' La comparación justa, reentrenar contra el objetivo corregido frente a reescalar, es ' + pp(g1.dif) + ' ' + ic(g1.ic_inf, g1.ic_sup) + ' (mejor en ' + deMeses(g1.meses_mejor) + ') ' + fuente('demanda_objetivo_corregido', 'ganancia_V4c_vs_V4_reescalado_' + ANIO + '.dif', 'Ganancia de reentrenar') + ';' : '') +
      (num(g2.dif) ? ' el híbrido sobre el reentrenado añade ' + pp(g2.dif) + ' ' + ic(g2.ic_inf, g2.ic_sup) + ' ' + fuente('demanda_objetivo_corregido', 'ganancia_hibrido_vs_V4c_' + ANIO + '.dif', 'Ganancia del híbrido sobre V4c') + '.' : '') + '</p>' +
      (c17 ? '<p class="texto-2">Contradicción ' + esc(c17.id) + ' del inventario (' + esc(c17.tema) + '). Prevalece: ' + esc(c17.prevalece) + '</p>' : '');
    const pie = '<p>' + fuentes([['demanda_dias_con_problema_datos', 'Días con problemas de datos'], ['demanda_pax_cancelados_corrieron_2025', 'Pasajeros en viajes cancelados que corrieron'], ['demanda_objetivo_corregido', 'Error contra el objetivo corregido'],
      ['demanda_error_total_diario_corregido', 'Error medio del total diario (corregido)'], ['demanda_horas_faltan_buses', 'Horas en que faltarían buses'], ['demanda_horas_buses_exactos', 'Horas con los buses exactos']], 'Los datos tienen problemas') + '</p>';
    return seccion('dem-datos', 'Los datos tienen problemas', 'El modelo aprende de los registros de Sobusa, y una parte de ellos está incompleta o mal marcada. E13 midió cuánto.',
      aviso('atencion', 'Una parte de los pasajeros no está en el objetivo del modelo', p1 + p2 + tE13 + p3 + pie, 'dem-aviso-datos'));
  }

  // ---- 7. 2026 ---------------------------------------------------------------------------------------------------
  function datosEnero() {
    const sem = campo('demanda_pronostico_2026_enero', 'semanas');
    if (!Array.isArray(sem)) return null;
    const por = {}, orden = [];
    sem.forEach(function (r) {
      if (!r || !num(r.semana)) return;
      const k = r.semana;
      if (!por[k]) { por[k] = { semana: k, desde: r.desde, hasta: r.hasta, real: 0, E11: 0, hib: 0, E8: 0 }; orden.push(k); }
      ['real_2025_alineado', 'pronostico_E11', 'pronostico', 'E8_ensamble_diario'].forEach(function (c, i) { const v = r[c]; if (num(v)) por[k][['real', 'E11', 'hib', 'E8'][i]] += v; });
    });
    orden.sort(function (a, b) { return a - b; });
    return orden.map(function (k) { return por[k]; });
  }
  function opcionBarrasEnero(sem) {
    const T = global.TEMA_ECHARTS, t = T.tokens();
    const nombres = [ANIO + ' alineado', SERIES.E11_V4, SERIES.hibrido];
    return {
      legend: { show: false, data: nombres },
      tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, formatter: function (ps) {
        const s = sem[ps[0].dataIndex];
        return '<strong>Semana ' + n(s.semana) + (s.desde && s.hasta ? ' (' + esc(F.fechaCorta(s.desde)) + ' – ' + esc(F.fechaCorta(s.hasta)) + ')' : '') + '</strong><br>' + ps.map(function (q) { return q.marker + esc(q.seriesName) + ': ' + n(q.value, 0); }).join('<br>');
      } },
      grid: { left: 8, right: 16, top: 28, bottom: 8, containLabel: true },
      xAxis: { type: 'category', data: sem.map(function (s) { return 'Semana ' + n(s.semana); }), axisLabel: { interval: 0, hideOverlap: true } },
      yAxis: { type: 'value', name: 'pasajeros/semana', nameLocation: 'end', nameGap: 12, nameTextStyle: { align: 'left' }, axisLabel: { formatter: function (v) { return n(v, 0); } } },
      series: [
        Object.assign({ name: nombres[0], type: 'bar', data: sem.map(function (s) { return Math.round(s.real); }) }, T.serie('real')),
        { name: nombres[1], type: 'bar', data: sem.map(function (s) { return Math.round(s.E11); }), itemStyle: { color: t.serieModelo, decal: { symbol: 'rect', symbolSize: 1, dashArrayX: [1, 0], dashArrayY: [2, 4], rotation: Math.PI / 4, color: t.superficie } } },
        Object.assign({ name: nombres[2], type: 'bar', data: sem.map(function (s) { return Math.round(s.hib); }) }, T.serie('modelo')),
      ],
    };
  }
  function pintarEnero() {
    const fig = cont.querySelector('#dem-g-enero');
    const el = fig && fig.querySelector('.grafico__lienzo');
    const sem = datosEnero();
    if (!el || !sem || !sem.length || !global.echarts) return;
    const g = grafico('enero', el);
    g.setOption(opcionBarrasEnero(sem), { notMerge: true });
    ponerLeyenda(fig, itemLeyenda(ANIO + ' alineado', 'real', false, true) + itemLeyenda(SERIES.E11_V4, 'final', false, true) + itemLeyenda(SERIES.hibrido, 'modelo', false, true), function () { return graficos.enero; });
  }
  function seccion2026() {
    const va = valor('demanda_2026_variacion', null, {}) || {};
    const sub = va.subidas_pct || {}, vj = va.viajes_pct || {};
    const el = valor('demanda_elasticidad_aparente_2026', null, null);
    const pe = valor('demanda_pronostico_2026_enero', null, {}) || {};
    const intro = 'En ' + ANIO_SIGUE + ' Sobusa puso más viajes y subieron más pasajeros. Ningún modelo entrenado con datos hasta ' + ANIO + ' anticipa ese cambio de nivel: hay que reentrenar cada semana con los datos nuevos.';
    const fichasV = '<div class="cifras">' +
      cifraLlana('Pasajeros, ' + ANIO_SIGUE + ' frente a ' + ANIO, num(sub.TOTAL) ? sg(sub.TOTAL, 1) : '—', '%', 'Las tres rutas, en las mismas fechas de los dos años.', fuente('demanda_2026_variacion', 'subidas_pct.TOTAL', 'Variación de pasajeros ' + ANIO_SIGUE)) +
      cifraLlana('Viajes, ' + ANIO_SIGUE + ' frente a ' + ANIO, num(vj.TOTAL) ? sg(vj.TOTAL, 1) : '—', '%', 'La oferta creció más que la demanda.', fuente('demanda_2026_variacion', 'viajes_pct.TOTAL', 'Variación de viajes ' + ANIO_SIGUE)) +
      cifraLlana('Pronóstico de largo plazo para ' + ANIO_SIGUE, num(va.error_ENS_2026_pct) ? sg(va.error_ENS_2026_pct, 1) : '—', '%', 'El ensamble de E8 se quedó corto; en la retroprueba de ' + ANIO + ' su error fue ' + sg(va.retroprueba_2025_error_pct, 1) + FINO + '% ' + fuente('demanda_2026_variacion', 'retroprueba_2025_error_pct', 'Retroprueba ' + ANIO) + '.', fuente('demanda_2026_variacion', 'error_ENS_2026_pct', 'Error del pronóstico de largo plazo')) +
      cifraLlana('Elasticidad aparente pasajeros/viajes', n(el, 2), '', 'Descriptiva y frágil: ' + esc(campo('demanda_elasticidad_aparente_2026', 'nota') || 'no es causal') + '', fuente('demanda_elasticidad_aparente_2026', null, 'Elasticidad aparente')) + '</div>';
    const filasR = RUTAS.concat(['TOTAL']).map(function (r) {
      return { celdas: [r === 'TOTAL' ? 'Las tres rutas' : claveRuta(r), num(sub[r]) ? sg(sub[r], 1) + FINO + '%' : '—', num(vj[r]) ? sg(vj[r], 1) + FINO + '%' : '—'], clase: r === 'TOTAL' ? 'tabla__fila-total' : '' };
    });
    const tR = tabla('', ['Ruta', 'Pasajeros', 'Viajes'], filasR, { compacta: true });

    const sem = datosEnero() || [];
    const tEnero = tabla('Enero de ' + ANIO_SIGUE + ', las tres rutas (pasajeros por semana)', ['Semana', ANIO + ' alineado', SERIES.E11_V4, SERIES.hibrido, 'Ensamble de E8'], sem.map(function (s) {
      return { celdas: ['Semana ' + n(s.semana) + (s.desde && s.hasta ? ' (' + esc(F.fechaCorta(s.desde)) + ' – ' + esc(F.fechaCorta(s.hasta)) + ')' : ''), n(s.real), n(s.E11), n(s.hib), n(s.E8)] };
    }), { sinMarco: true, compacta: true });
    const figEnero = figura({ id: 'dem-g-enero', titulo: 'Enero de ' + ANIO_SIGUE + ', semana a semana', sub: 'Lo que pronostican el modelo final y el híbrido para cada semana (las tres rutas) frente a las mismas fechas de ' + ANIO + '.',
      aria: 'Pronóstico de enero de ' + ANIO_SIGUE + ' por semana: ' + ANIO + ' alineado, modelo final e híbrido', leyenda: '', tabla: tEnero, bajo: true,
      pie: '<span class="demanda__nota-verificado">' + chipVerificado('demanda_pronostico_2026_enero') + '<span>' + esc(campo('demanda_pronostico_2026_enero', 'revision') || '') + '</span></span>' + fuente('demanda_pronostico_2026_enero', null, 'Pronóstico de enero de ' + ANIO_SIGUE) });
    const pron = '<p class="demanda__prosa">Para el mes, el híbrido pronostica ' + n(pe.hibrido) + ' pasajeros ' + fuente('demanda_pronostico_2026_enero', 'hibrido', 'Pronóstico del híbrido') + ' y el modelo final, ' + n(pe.E11_V4) + ' ' + fuente('demanda_pronostico_2026_enero', 'E11_V4', 'Pronóstico del modelo final') +
      ': ' + sg(pe.hibrido_vs_2025_pct, 1) + FINO + '% ' + fuente('demanda_pronostico_2026_enero', 'hibrido_vs_2025_pct', 'Híbrido frente a ' + ANIO) + ' y ' + sg(pe.E11_vs_2025_pct, 1) + FINO + '% ' + fuente('demanda_pronostico_2026_enero', 'E11_vs_2025_pct', 'Modelo final frente a ' + ANIO) +
      ' frente a las mismas fechas de ' + ANIO + ' (' + n(pe.real_2025_alineado) + ' ' + fuente('demanda_pronostico_2026_enero', 'real_2025_alineado', ANIO + ' alineado') + '). Los dos siguen la caída de los años anteriores, no la subida de ' + ANIO_SIGUE + '.' +
      (campo('demanda_pronostico_2026_enero', 'nota') ? ' ' + esc(campo('demanda_pronostico_2026_enero', 'nota')) : '') + '</p>';
    const lim = cifra('modelo_limite_nivel_2026');
    const limite = lim ? aviso('atencion', 'El límite: el cambio de nivel de ' + ANIO_SIGUE, '<p>' + esc(lim.que_es || '') + '</p><p>' + md(String(lim.valor || '')) + ' ' + fuente('modelo_limite_nivel_2026', null, 'Límite del cambio de nivel') + '</p>' +
      '<p class="demanda__nota-verificado texto-2">' + chipVerificado('modelo_limite_nivel_2026') + '<span>' + esc(lim.revision || '') + '</span></p>') : '';
    return seccion('dem-2026', 'Y en ' + ANIO_SIGUE + '', intro, fichasV + tR + figEnero + pron + limite);
  }

  // ---- 8. Explorar los datos (el tablero, montado por la app al final de la pantalla) ------------------------------
  function seccionExplorar() {
    return seccion('dem-explorar', 'Explorar los datos', 'Debajo está el tablero de ' + ANIO_INICIO + '-' + ANIO + ' con la demanda por día y por hora y el mapa de las tres rutas; estas pestañas lo cambian.',
      '<div class="chips" role="group" aria-label="Pestaña del tablero" id="dem-pestanas">' + PESTANAS_TABLERO.map(function (p, i) {
        return '<button class="chip" type="button" data-pestana="' + p[0] + '" aria-pressed="' + (i === 0 ? 'true' : 'false') + '">' + esc(p[1]) + '</button>';
      }).join('') + '</div>');
  }
  function ligarExplorar() {
    const caja = cont.querySelector('#dem-pestanas');
    if (!caja) return;
    caja.addEventListener('click', function (e) {
      const b = e.target.closest('button[data-pestana]');
      if (!b) return;
      caja.querySelectorAll('button[data-pestana]').forEach(function (x) { x.setAttribute('aria-pressed', x === b ? 'true' : 'false'); });
      const m = global.app && global.app.modulo ? global.app.modulo(ID) : null;
      if (m) {
        if (!m.enviar({ tipo: 'pestana', pestana: b.dataset.pestana })) m.irA(b.dataset.pestana);
        if (m.elemento && m.elemento.scrollIntoView) m.elemento.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
    });
  }

  // ---- Oyentes de los controles propios ----------------------------------------------------------------------------
  function ligarControles() {
    const sel = cont.querySelector('#dem-modelo');
    global.COMPONENTES.segmentado(sel, function (v) {
      modelo = v === 'hibrido' ? 'hibrido' : 'final';
      pintarFichas(true); pintarDiaria(); pintarHora();
      if (global.app && typeof global.app.ponerEstado === 'function') global.app.ponerEstado({ modelo: modelo });
    });
    const chips = cont.querySelector('#dem-rutas');
    if (chips) chips.addEventListener('click', function (e) {
      const b = e.target.closest('button[data-ruta]');
      if (!b || b.dataset.ruta === ruta) return;
      ruta = b.dataset.ruta;
      marcarChips(); pintarDiaria(); pintarHora();
      if (global.app && typeof global.app.ponerEstado === 'function') global.app.ponerEstado({ ruta: ruta });
    });
    ligarExplorar();
  }
  function destruirGraficos() {
    Object.keys(graficos).forEach(function (k) { try { if (graficos[k] && !graficos[k].isDisposed()) graficos[k].dispose(); } catch (e) { /* ya destruido */ } });
    graficos = {};
  }
  function pintarGraficos() {
    if (!global.echarts || !global.TEMA_ECHARTS) {
      // Sin ECharts, cada figura abre su tabla gemela.
      cont.querySelectorAll('.grafico').forEach(function (fig) { const t = fig.querySelector('.grafico__tabla'), l = fig.querySelector('.grafico__lienzo'), ley = fig.querySelector('.leyenda'); if (t) t.hidden = false; if (l) l.hidden = true; if (ley) ley.hidden = true; });
      return;
    }
    pintarDiaria(); pintarHora(); pintarEnero();
  }

  // ---- Contrato de la pantalla ----------------------------------------------------------------------------------
  function estadoDe(estado) {
    escenario = estado && estado.escenario === 'modelo' ? 'modelo' : 'hoy';
    modelo = estado && estado.modelo === 'hibrido' ? 'hibrido' : 'final';
    ruta = estado && [TODAS].concat(RUTAS).indexOf(estado.ruta) >= 0 ? estado.ruta : TODAS;
  }
  function render(contenedor, datos, estado) {
    salir();
    cont = contenedor; D = datos || global.DATOS_APP || {};
    estadoDe(estado);
    faltantes = []; pops = {}; nPop = 0; graficos = {};
    estilos();
    cont.classList.add('demanda');
    fichas = definirFichas();
    const partes = [seccionFichas(), seccionSeries(), seccionTabla(), seccionAyuda(), seccionDatos(), seccion2026(), seccionExplorar()];
    const cab = faltantes.length ? aviso('atencion', 'Faltan datos en app/datos_app.js', '<p>Esta pantalla no encontró ' + n(faltantes.length) + ' ids: <code>' + faltantes.map(esc).join('</code>, <code>') + '</code>. Donde faltan se muestra «—».</p>') : '';
    cont.innerHTML = '<div class="pila pila--ancha" id="dem-cuerpo">' + cab + partes.join('') + '</div>';
    pintarFichas(false);
    global.COMPONENTES.cifras(cont);
    global.COMPONENTES.fuentes(document);
    global.COMPONENTES.tablaGrafico(cont);
    ligarControles();
    pintarGraficos();
    if ('ResizeObserver' in global) {
      const vigilante = new ResizeObserver(function () { Object.keys(graficos).forEach(function (k) { if (graficos[k] && !graficos[k].isDisposed()) graficos[k].resize(); }); });
      cont.querySelectorAll('.grafico__lienzo').forEach(function (el) { vigilante.observe(el); });
      limpiezas.push(function () { vigilante.disconnect(); });
    }
  }
  function actualizar(estado) {
    if (!cont) return;
    const antes = { escenario: escenario, modelo: modelo, ruta: ruta };
    estadoDe(estado);
    if (antes.modelo !== modelo) { const r = cont.querySelector('#dem-modelo input[value="' + modelo + '"]'); if (r) r.checked = true; }
    if (antes.ruta !== ruta) marcarChips();
    if (antes.escenario !== escenario || antes.modelo !== modelo) pintarFichas(true);
    if (antes.escenario !== escenario || antes.modelo !== modelo || antes.ruta !== ruta) { pintarDiaria(); pintarHora(); }
  }
  function salir() {
    destruirGraficos();
    limpiezas.forEach(function (f) { try { f(); } catch (e) { /* nada */ } });
    limpiezas = [];
  }
  // Subtítulo con las cifras de la app (la app lo llama con datos y estado).
  function subtitulo(datos) {
    const antes = D;
    D = datos || global.DATOS_APP || D;
    let s = 'Cuánto se equivoca el pronóstico de pasajeros frente a la regla manual de Sobusa: por ruta, por tipo de día, por franja y según la antelación.';
    try {
      const b = primero([['inicio_error_regla_manual', null]]).v, f = primero([['inicio_error_modelo_final', null]]).v, h = primero([['inicio_error_hibrido', null]]).v;
      // Misma forma que el subtítulo de Modelo: a H días, el error de cada uno en % de los pasajeros.
      if (num(b) && num(f)) s = 'A ' + hTexto() + ', el modelo final se equivoca en el ' + pct(f) + ' de los pasajeros' + (num(h) ? ' y el híbrido, recomendado para producción, en el ' + pct(h) : '') + '; la regla manual de Sobusa, en el ' + pct(b) + '.';
    } catch (e) { /* se deja el texto general */ }
    faltantes = [];
    if (antes) D = antes;
    return s;
  }

  const definicion = {
    id: ID,
    pregunta: '¿Cuántos pasajeros habrá?',
    subtitulo: subtitulo,
    icono: 'demanda',
    interruptor: [
      { valor: 'hoy', tooltip: 'La regla manual de Sobusa' },
      { valor: 'modelo', tooltip: 'El modelo final o el híbrido: se elige debajo del título' },
    ],
    tooltipInterruptor: 'No aplica al pronóstico: el oráculo es la demanda que de verdad llegó',
    modulo: { pagina: 'EDA_visual.html', hash: 'demanda', nombre: 'Tablero ' + ANIO_INICIO + '-' + ANIO },
    render: render,
    actualizar: actualizar,
    salir: salir,
  };
  // app.html define registrarPantalla antes de cargar las pantallas; si no existiera, se deja en la misma cola que lee app.js.
  if (typeof global.registrarPantalla === 'function') global.registrarPantalla(definicion);
  else (global.__pantallasRegistradas = global.__pantallasRegistradas || []).push(definicion);
  global.PANTALLA_DEMANDA = definicion;
})(window);
