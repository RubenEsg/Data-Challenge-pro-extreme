// Sobusa Despacho · pantallas/metodo.js — Método y datos · ¿De dónde sale todo?
// Sigue el contrato de app/DISEÑO.md §5 (registrarPantalla con render, actualizar y salir) y el wireframe de §7.
// De qué datos se parte, qué viajes cuentan, lo que mandaron los organizadores (capacidad real de la flota y el último
// día de cada mes), cómo se mide, el índice de experimentos con su revisión, las cifras que tienen varias bases, cómo se
// verificó la app, el equipo y las herramientas, y al final el tablero del análisis exploratorio (módulo embebido que
// monta app.js a partir de «modulo» de esta definición). Ninguna cifra está escrita aquí: todas salen de
// window.DATOS_APP (app/datos_app.js, generado por app/generar_datos_app.py) y cada una lleva su botón «fuente».
//
// Ids que lee: metodo_datos_crudos, metodo_tablas_exportadas, metodo_reglas_limpieza, metodo_protocolo, metodo_variables,
// metodo_experimentos, metodo_rondas_verificacion, metodo_equipo, metodo_herramientas, metodo_pesos_entrenamiento,
// metodo_sin_fugas, metodo_capacidad_flota y metodo_ultimo_dia_mes; además DATOS_APP.meta (generador, verificador,
// contrato, notas) y DATOS_APP.contradicciones. Si un id falta, la pantalla lo dice en un aviso y pinta «—».
(function (global) {
  'use strict';

  const ID = 'metodo';
  const F = COMPONENTES.formato;
  const icono = function (nombre, clase) { return ICONOS.svg(nombre, clase); };
  const FINO = ' ';   // espacio fino antes de % y de la unidad

  let D = null;            // window.DATOS_APP
  let cont = null;         // div.pantalla
  let faltantes = [];      // ids que no están en DATOS_APP
  let temas = {};          // código interno de una contradicción → su tema (para no mostrar códigos)

  // ---- Acceso a los datos -----------------------------------------------------------------------------------------
  function app() { return global.app; }
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
    return app().normalizarCifra(e);
  }
  function V(id) { const c = C(id); return c && c.valor !== undefined && c.valor !== null ? c.valor : null; }
  function esNum(v) { return typeof v === 'number' && isFinite(v); }
  function n(v, d) { return esNum(v) ? F.numero(v, d || 0) : '—'; }
  function pct(v, d) { return esNum(v) ? F.numero(v, d === undefined ? 0 : d) + FINO + '%' : '—'; }
  function esc(s) { return String(s === undefined || s === null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'); }
  function llano(t) { return String(t || '').replace(/`/g, '').replace(/\*\*/g, ''); }
  function fechaL(iso) { return esc(F.fechaLarga(iso)); }
  function porRuta(v, ruta) {
    if (!ruta) return v;
    const partes = String(ruta).split('.');
    for (let i = 0; i < partes.length; i++) { if (v === null || v === undefined) return undefined; v = v[partes[i]]; }
    return v;
  }
  // Los textos del inventario citan otras filas por su código interno; aquí se nombran por su tema.
  function sinCodigos(t) {
    return llano(t).replace(/\bC(\d{1,2})\b/g, function (todo, num) { const tema = temas['C' + num]; return tema ? '«' + tema + '»' : todo; });
  }

  // ---- Fuente: popover (una vez por id y parte) y botón --------------------------------------------------------------
  function fuente(id, titulo, ruta, extra) {
    const c = C(id);
    if (!c) return '';
    const idPop = 'fm-' + id + (ruta ? '-' + String(ruta).replace(/[^\w-]/g, '_') : '');
    if (!document.getElementById(idPop)) {
      const ex = Object.assign({}, c, { que_mide: esc(c.que_es || '') });
      if (ruta) {
        ex.clave = (c.clave || '') + ' → ' + String(ruta).replace(/\./g, ' → ');
        const sub = porRuta(c.valor, ruta);
        ex.valor = typeof sub === 'number' || typeof sub === 'string' ? sub : undefined;
      }
      app().popoverFuente(idPop, Object.assign(ex, extra || {}), titulo);
    }
    return app().botonFuente(idPop);
  }
  // Fuente de algo que no es una cifra del inventario (el recuento de la app, la tabla de bases).
  function fuenteObjeto(idPop, obj, titulo) {
    if (!document.getElementById(idPop)) app().popoverFuente(idPop, obj, titulo);
    return app().botonFuente(idPop);
  }

  // ---- Piezas de HTML -----------------------------------------------------------------------------------------------
  function seccion(id, titulo, intro, cuerpo) {
    return '<section class="seccion" id="' + id + '" aria-labelledby="' + id + '-t"><div class="seccion__cab"><h2 class="seccion__titulo" id="' + id + '-t">' + titulo + '</h2></div>' +
      (intro ? '<p class="seccion__intro">' + intro + '</p>' : '') + '<div class="seccion__cuerpo">' + cuerpo + '</div></section>';
  }
  function aviso(tipo, titulo, cuerpo) {
    const ic = tipo === 'canje' ? 'canje' : tipo === 'bien' ? 'bien' : tipo === 'nota' ? 'info' : 'alerta';
    return '<div class="aviso' + (tipo && tipo !== 'nota' ? ' aviso--' + tipo : '') + '" role="note">' + icono(ic) + '<div class="aviso__cuerpo">' + (titulo ? '<h3 class="aviso__titulo">' + titulo + '</h3>' : '') + cuerpo + '</div></div>';
  }
  function ficha(etiqueta, valorHtml, unidad, nota, botonFuente, claseValor) {
    return '<article class="cifra"><header class="cifra__cab"><h3 class="cifra__etiqueta">' + etiqueta + '</h3>' + (botonFuente || '') + '</header>' +
      '<p class="cifra__valor' + (claseValor ? ' ' + claseValor : '') + '"><span class="num">' + valorHtml + '</span>' + (unidad ? '<span class="cifra__unidad">' + esc(unidad) + '</span>' : '') + '</p>' +
      (nota ? '<p class="cifra__nota">' + nota + '</p>' : '') + '</article>';
  }
  function desplegable(id, titulo, cuerpo) {
    return '<details class="desplegable" id="' + id + '"><summary class="desplegable__resumen">' + icono('chevron-derecha', 'icono desplegable__chevron') + titulo + '</summary><div class="desplegable__cuerpo">' + cuerpo + '</div></details>';
  }
  // Tabla: la primera columna es cabecera de fila; las demás son números (alineados a la derecha) salvo las de textoEn.
  // Con apilable, bajo 600 px cada fila se apila con el rótulo de su columna (data-rotulo).
  function tabla(caption, cabeceras, filas, opciones) {
    opciones = opciones || {};
    const esTexto = function (i) { return opciones.textoEn && opciones.textoEn.indexOf(i) >= 0; };
    let h = '<div class="tabla-marco"><table class="tabla' + (opciones.compacta ? ' tabla--compacta' : '') + (opciones.apilable ? ' metodo__apilable' : '') + (opciones.clase ? ' ' + opciones.clase : '') + '">';
    if (caption) h += '<caption>' + caption + '</caption>';
    h += '<thead><tr>' + cabeceras.map(function (c, i) { return '<th scope="col"' + (i > 0 && !esTexto(i) ? ' class="num"' : '') + '>' + c + '</th>'; }).join('') + '</tr></thead><tbody>';
    filas.forEach(function (fila) {
      h += '<tr' + (fila.clase ? ' class="' + fila.clase + '"' : '') + '>' + fila.celdas.map(function (c, i) {
        if (i === 0) return '<th scope="row">' + c + '</th>';
        return '<td' + (esTexto(i) ? '' : ' class="num"') + (opciones.apilable ? ' data-rotulo="' + esc(cabeceras[i].replace(/<[^>]+>/g, '')) + '"' : '') + '>' + c + '</td>';
      }).join('') + '</tr>';
    });
    return h + '</tbody></table></div>';
  }
  function chipSiNo(ok, texto) {
    return '<span class="chip chip--' + (ok ? 'bien' : 'critico') + '">' + icono(ok ? 'bien' : 'alerta') + esc(texto) + '</span>';
  }
  function chipVeredicto(v) {
    if (!v) return '';
    const t = String(v).replace(/_/g, ' ');
    const clase = /^no\b/.test(t) ? 'critico' : /reservas/.test(t) ? '' : /confiable|utilizable/.test(t) ? 'bien' : '';
    return '<span class="chip' + (clase ? ' chip--' + clase : '') + '">' + icono(clase === 'bien' ? 'bien' : clase === 'critico' ? 'alerta' : 'info') + esc(t) + '</span>';
  }

  // ---- Estilos propios (solo tokens) --------------------------------------------------------------------------------
  function estilos() {
    if (document.getElementById('estilos-metodo')) return;
    const st = document.createElement('style');
    st.id = 'estilos-metodo';
    st.textContent = [
      '#metodo-cuerpo { display: grid; gap: var(--e-8); }',
      '@media (max-width: 600px) { #metodo-cuerpo { gap: var(--e-7); } }',
      '.metodo__lista { margin: 0; padding-left: 20px; display: grid; gap: var(--e-2); max-width: var(--ancho-texto); text-wrap: pretty; }',
      '.metodo__lista strong { font-weight: var(--peso-fuerte); }',
      // Dentro de un desplegable (rejilla) un elemento con una palabra larga (una ruta de archivo) no ensancha la rejilla.
      '#metodo-cuerpo .desplegable__cuerpo > * { min-width: 0; }',
      '.metodo__notas li, .metodo__notas p { overflow-wrap: anywhere; }',
      '.metodo__chips { display: flex; flex-wrap: wrap; align-items: center; gap: var(--e-2); }',
      '.metodo__h3 { margin: 0; font: var(--peso-fuerte) var(--t-l) / 1.2 var(--fuente-titulos); letter-spacing: var(--ls-titulo); color: var(--tinta); }',
      '.metodo__enlaces { display: flex; flex-wrap: wrap; gap: var(--e-2) var(--e-4); margin: 0; font-size: var(--t-s); }',
      '.metodo__enlaces a { display: inline-flex; align-items: center; gap: 4px; }',
      '.metodo__enlaces .icono { width: 14px; height: 14px; }',
      '.metodo__tarjeta { display: grid; gap: var(--e-3); align-content: start; }',
      '.metodo__tarjeta .resumen-datos { grid-template-columns: minmax(0, 1fr) auto; }',
      '.metodo__nombres { display: flex; flex-wrap: wrap; gap: var(--e-2) var(--e-5); margin: 0; padding: 0; list-style: none; font-size: var(--t-m); font-weight: var(--peso-medio); }',
      '.metodo__texto-largo { max-width: var(--ancho-texto); text-wrap: pretty; }',
      '.metodo__texto-largo .fuente { vertical-align: middle; }',
      '.metodo__apilable td, .metodo__apilable th { white-space: normal; }',
      '.metodo__apilable td:not(.num) { min-width: 14em; }',
      '.metodo__apilable tbody th { font-weight: var(--peso-medio); }',
      '.metodo__indice tbody th { min-width: 7em; white-space: nowrap; }',
      '.metodo__indice .chip { margin-left: var(--e-1); }',
      '.metodo__pie-tabla { margin: 0; font-size: var(--t-s); color: var(--tinta-2); max-width: var(--ancho-texto); text-wrap: pretty; }',
      '.metodo__pie-tabla .fuente { vertical-align: middle; }',
      '@media (max-width: 600px) {',
      '  .metodo__apilable thead { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); }',
      '  .metodo__apilable tbody tr { display: grid; gap: var(--e-2); padding: var(--e-3) var(--e-4); border-bottom: 1px solid var(--linea); }',
      '  .metodo__apilable tbody tr:last-child { border-bottom: 0; }',
      '  .metodo__apilable tbody th, .metodo__apilable td, .metodo__apilable td.num { display: block; padding: 0; border: 0; min-width: 0; text-align: left; white-space: normal; }',
      '  .metodo__apilable td::before { content: attr(data-rotulo); display: block; color: var(--tinta-3); font-size: var(--t-xs); margin-bottom: 2px; }',
      '  .metodo__apilable tbody tr:hover td { background: transparent; }',
      '}',
    ].join('\n');
    document.head.appendChild(st);
  }

  // ---- 0. Entradilla -------------------------------------------------------------------------------------------------
  function entradilla() {
    const tab = C('metodo_tablas_exportadas');
    const regla = tab && tab.nota ? esc(tab.nota) : 'La base de datos del reto es compartida y de solo lectura: la app no la consulta; todo sale de archivos locales.';
    return '<p class="entradilla">Ninguna cifra de la app está escrita a mano: cada número se lee de un archivo de resultados del proyecto, lleva su botón de fuente (archivo, clave, experimento y revisor) y un verificador lo vuelve a leer y lo compara. ' + regla + '</p>';
  }

  // ---- 1. De qué datos partimos ---------------------------------------------------------------------------------------
  function seccionDatos() {
    const c = C('metodo_datos_crudos');
    const v = (c && c.valor) || {};
    const periodo = (c && c.periodo) || [];
    const fichas = '<div class="cifras">' +
      ficha('Días con datos', n(v.dias), 'días', periodo.length === 2 ? 'Del ' + fechaL(periodo[0]) + ' al ' + fechaL(periodo[1]) + '.' : '', fuente('metodo_datos_crudos', 'días con datos', 'dias')) +
      ficha('Viajes válidos', n(v.viajes_validos), 'viajes', 'De ' + n(v.viajes_programados) + ' programados; válido es finalizado y no cancelado. ' + fuente('metodo_datos_crudos', 'viajes programados', 'viajes_programados'), fuente('metodo_datos_crudos', 'viajes válidos', 'viajes_validos')) +
      ficha('Pasajeros', n(esNum(v.pasajeros_total) ? v.pasajeros_total / 1e6 : null, 1), 'millones', 'Subidas contadas en los viajes válidos de los tres años.', fuente('metodo_datos_crudos', 'pasajeros', 'pasajeros_total', { nota: 'La ficha lo muestra en millones, con un decimal.' })) +
      ficha('Eventos GPS', n(esNum(v.eventos_gps) ? v.eventos_gps / 1e6 : null, 1), 'millones', 'Subidas y bajadas que registra el equipo de a bordo; se resumieron en el servidor sin descargarlos.', fuente('metodo_datos_crudos', 'eventos GPS', 'eventos_gps', { nota: 'La ficha lo muestra en millones, con un decimal.' })) +
      ficha('Vehículos', n(v.vehiculos_distintos), 'vehículos', 'Usados en viajes válidos de las tres rutas.', fuente('metodo_datos_crudos', 'vehículos', 'vehiculos_distintos')) +
      ficha('Códigos de conductor', n(v.conductores), 'códigos', 'Códigos distintos en los tres años; no se publica ninguno.', fuente('metodo_datos_crudos', 'códigos de conductor', 'conductores')) +
      '</div>';
    // Por año
    const anios = Object.keys(v.pasajeros_por_anio || {}).sort();
    const tAnios = anios.length ? tabla('Por año', ['Año', 'Pasajeros', 'Viajes válidos'], anios.map(function (a) {
      return { celdas: [esc(a), n(v.pasajeros_por_anio[a]) + ' ' + fuente('metodo_datos_crudos', 'pasajeros ' + a, 'pasajeros_por_anio.' + a), n((v.viajes_por_anio || {})[a]) + ' ' + fuente('metodo_datos_crudos', 'viajes ' + a, 'viajes_por_anio.' + a)] };
    }), { compacta: true }) : '';
    // Tablas exportadas
    const lista = V('metodo_tablas_exportadas');
    let tTablas = '';
    if (Array.isArray(lista) && lista.length) {
      tTablas = desplegable('metodo-tablas', 'Las tablas exportadas de la base',
        '<p>' + n(lista.length) + ' archivos locales: las tablas de la base copiadas tal cual y los resúmenes de los eventos GPS calculados en el servidor. ' + fuente('metodo_tablas_exportadas', 'tablas exportadas') + '</p>' +
        tabla('', ['Archivo', 'Cómo se produjo', 'Filas', 'Columnas', 'Tamaño (MB)'], lista.map(function (t) {
          return { celdas: [esc(t.archivo), esc(t.origen), n(t.filas), n(t.columnas), n(t.MB, t.MB < 1 ? 2 : 1)] };
        }), { compacta: true, textoEn: [1] }));
    }
    const notas = (c && c.notas) || [];
    const tNotas = notas.length ? desplegable('metodo-notas-datos', 'Cómo se contaron', '<ul class="metodo__notas">' + notas.map(function (t) { return '<li>' + esc(llano(t)) + '</li>'; }).join('') + '</ul><p class="texto-2">' + fuente('metodo_datos_crudos', 'notas del tablero', 'notas') + ' Notas del tablero del análisis exploratorio.</p>') : '';
    return seccion('metodo-datos', 'De qué datos partimos',
      'Los viajes programados de las tres rutas, con sus pasajeros contados a bordo, y los eventos de subida y bajada que registra el GPS de cada bus, exportados de la base del reto a archivos locales.',
      fichas + tAnios + tTablas + tNotas);
  }

  // ---- 2. Qué viajes cuentan -------------------------------------------------------------------------------------------
  const EMBUDO = [
    ['programados', 'Programados'],
    ['validos', 'Válidos: finalizados y no cancelados'],
    ['pax_ok', 'Válidos con dato de pasajeros plausible (ceros incluidos)'],
    ['limpios', 'Limpios: duración y pasajeros plausibles (para promedios por viaje)'],
    ['sin_registro', 'Válidos sin registro: sin pasajeros y casi sin eventos GPS'],
    ['fantasmas', 'De los sin registro, fantasmas: el mismo bus hizo otro viaje poco después'],
    ['corrieron', 'Recorrieron la ruta según el GPS, válidos o no'],
    ['cancelados_que_corrieron', 'Marcados cancelados que sí recorrieron la ruta'],
    ['operaron', 'Operaron: recorrieron la ruta o válidos sin registro'],
    ['parciales', 'De los que operaron, con registro parcial'],
  ];
  function seccionReglas() {
    const c = C('metodo_reglas_limpieza');
    const v = (c && c.valor) || {};
    const viajes = v.viajes || {};
    const filas = EMBUDO.filter(function (e) { return esNum(viajes[e[0]]); }).map(function (e) {
      return { celdas: [esc(e[1]), n(viajes[e[0]]) + ' ' + fuente('metodo_reglas_limpieza', e[1].toLowerCase(), 'viajes.' + e[0])] };
    });
    const tEmbudo = filas.length ? tabla('Viajes en la ventana del modelo: ' + esc(v.unidad || ''), ['Grupo', 'Viajes'], filas, { compacta: true }) +
      '<p class="metodo__pie-tabla">Las fichas de arriba cuentan todo el día; esta tabla, solo la ventana de salida del modelo: por eso difieren en unos pocos viajes.</p>' : '';
    const reglas = Array.isArray(v.reglas) ? '<ul class="metodo__lista">' + v.reglas.map(function (r) { return '<li>' + esc(llano(r)) + '</li>'; }).join('') + '</ul>' +
      '<p class="metodo__pie-tabla">' + fuente('metodo_reglas_limpieza', 'reglas de limpieza', 'reglas') + ' Las reglas numeradas del análisis exploratorio, de la validez a la consistencia de los contadores GPS, están en el cuaderno del EDA de la primera entrega y en el código de la ingeniería de variables. El filtro de distancia que allí se reservaba para la tabla de modelado no se adoptó.</p>' : '';
    const marca = aviso('nota', 'La marca oficial no sirve para separar',
      '<p>La base trae una marca de aptitud para estadísticas históricas, pero está en verdadero en todos los viajes de las tres rutas, así que no distingue nada. También trae una fecha de fin de liquidación que siempre está vacía. La validez propia (finalizado y no cancelado) es la que vale, y se confirmó con los archivos que mandaron los organizadores.</p>');
    const cancel = esNum(viajes.cancelados_que_corrieron) ? aviso('atencion', 'Viajes marcados cancelados que sí corrieron',
      '<p>El sistema marca como cancelados ' + n(viajes.cancelados_que_corrieron) + ' viajes que, según el GPS, sí recorrieron la ruta. ' + fuente('metodo_reglas_limpieza', 'cancelados que corrieron', 'viajes.cancelados_que_corrieron') + ' Las cifras oficiales del modelo usan el objetivo original (solo viajes válidos); el objetivo corregido de E13, que cuenta también esos pasajeros, se muestra aparte en <a href="#demanda">Demanda</a>.</p>') : '';
    const unidad = '<div class="cifras">' +
      ficha('Filas de la tabla de modelado', n(v.filas), 'franjas', esc(v.unidad || ''), fuente('metodo_reglas_limpieza', 'filas de la tabla', 'filas')) +
      ficha('Columnas', n(v.columnas), 'variables', 'Identificación, objetivos, calendario, clima y rezagos; el modelo usa una parte según la antelación.', fuente('metodo_reglas_limpieza', 'columnas de la tabla', 'columnas')) +
      '</div>';
    return seccion('metodo-reglas', 'Qué viajes cuentan',
      'Un viaje cuenta como válido cuando el sistema lo da por finalizado y no cancelado. Para los promedios por viaje se exigen además una duración y un número de pasajeros plausibles.',
      tEmbudo + reglas + marca + cancel + unidad);
  }

  // ---- 3. Lo que mandaron los organizadores ---------------------------------------------------------------------------
  // El año de la clave «vehiculos_<año>» del archivo (no se escribe aquí): rótulo «Vehículos que corrieron en <año>».
  const ROTULOS_CAPACIDAD = { mediana_total: 'Mediana (sentados + de pie)', media_sentados: 'Media de sentados', media_depie: 'Media de pie',
    vehiculos_con_dato: 'Vehículos con dato en el reporte' };
  function anioVehiculos(v) { const k = Object.keys(v || {}).filter(function (x) { return /^vehiculos_\d{4}$/.test(x); })[0]; return k ? k.slice(-4) : ''; }
  function fichaCapacidad() {
    const c = C('metodo_capacidad_flota');
    if (!c) return '';
    const v = c.valor || {};
    const d = typeof c.decimales === 'number' ? c.decimales : 1;
    const u = c.unidad ? ' ' + esc(c.unidad) : '';
    const anio = anioVehiculos(v);
    const rotulos = Object.assign({}, ROTULOS_CAPACIDAD);
    if (anio) rotulos['vehiculos_' + anio] = 'Vehículos que corrieron en ' + anio;
    let dl = Object.keys(rotulos).filter(function (k) { return k in v; }).map(function (k) {
      const x = v[k];
      return '<dt>' + esc(rotulos[k]) + '</dt><dd class="num">' + n(x, Number.isInteger(x) ? 0 : d) + (k.indexOf('vehiculos') !== 0 ? u : '') + '</dd>';
    }).join('');
    if (Array.isArray(c.p25_p75) && c.p25_p75.length === 2) dl += '<dt>Cuartiles</dt><dd class="num">' + n(c.p25_p75[0]) + ' – ' + n(c.p25_p75[1]) + u + '</dd>';
    if (esNum(c.mediana_parquet_D1)) dl += '<dt>Mediana del catálogo que usó D1</dt><dd class="num">' + n(c.mediana_parquet_D1) + u + '</dd>';
    if (esNum(c.capacidad_usada_en_D1_D5)) dl += '<dt>Capacidad con la que se calculó todo (D1, D5, simulador y motor)</dt><dd class="num">' + n(c.capacidad_usada_en_D1_D5) + u + '</dd>';
    const sostiene = esNum(c.capacidad_usada_en_D1_D5) && esNum(v.mediana_total) && c.capacidad_usada_en_D1_D5 === v.mediana_total;
    return '<article class="cifra metodo__tarjeta"><header class="cifra__cab"><h3 class="cifra__etiqueta">Capacidad real de la flota</h3>' + fuente('metodo_capacidad_flota', 'capacidad real de la flota') + '</header>' +
      '<p class="cifra__nota">Reporte de flota de Sobusa: los vehículos que corrieron ' + (anio ? 'en ' + anio : 'ese año') + ' en las tres rutas, una placa por vehículo.</p>' +
      '<dl class="resumen-datos">' + dl + '</dl>' +
      '<p class="cifra__variacion ' + (sostiene ? 'cifra__variacion--bien' : '') + '">' + icono(sostiene ? 'bien' : 'info') + (sostiene ? 'La capacidad con la que se calcularon la flota, el horario y el simulador coincide con la mediana real: no hubo que rehacer nada.' : 'Compara la capacidad usada con la mediana del reporte.') + '</p></article>';
  }
  // La línea sobre el último día de cada mes (qué tiene cargado la base), como la pinta app.js en la versión breve.
  function lineaUltimoDia() {
    const c = C('metodo_ultimo_dia_mes');
    if (!c) return '';
    const v = c.valor || {};
    const fecha = function (iso) { return esc(F.fecha(iso)); };
    const cargados = (c.dias_cargados || []).map(fecha).join(', ');
    const pendientes = (c.dias_pendientes || []).map(fecha).join(', ');
    const total = (esNum(v.cargados) ? v.cargados : 0) + (esNum(v.pendientes) ? v.pendientes : 0);
    const ene = c.viajes_31_enero || {};
    // El año sale de las fechas del archivo (dias_cargados / dias_pendientes), no se escribe aquí.
    const anio = String(((c.dias_cargados || [])[0] || (c.dias_pendientes || [])[0] || '')).slice(0, 4);
    let texto = 'En la tabla de conteo, la base tiene eventos en ' + n(v.cargados) + ' de los ' + n(total) + ' últimos días de mes' + (anio ? ' de ' + anio : ' del año de estudio') +
      (cargados ? ' (' + cargados + ')' : '') + '; los otros ' + n(v.pendientes) + ' siguen vacíos (comprobado el ' + fechaL(v.fecha_comprobacion) +
      '). Los datos del proyecto se exportaron antes de esa carga, así que nada de lo calculado cambia todavía. ' + fuente('metodo_ultimo_dia_mes', 'último día de cada mes');
    if (esNum(ene.viajes_con_eventos) && esNum(ene.viajes_programados)) texto += '</p><p>El día cargado tiene eventos en ' + n(ene.viajes_con_eventos) + ' de sus ' + n(ene.viajes_programados) + ' viajes. ' + fuente('metodo_ultimo_dia_mes', 'viajes del día cargado', 'viajes_31_enero');
    if (pendientes) texto += '</p><p class="texto-2">Pendientes: ' + pendientes + '.';
    texto += '</p><p>Cuando los organizadores avisen que están los doce, habría que exportar de nuevo las tablas, rehacer los resúmenes GPS y las cachés, y los días que se pueden reproducir en la consola y en la vista de la ciudad pasarían a ser todos los del año; la regla de despacho, los costos y la elasticidad no dependen de esos días.';
    return '<div class="aviso" role="note" id="metodo-ultimo-dia">' + icono('info') + '<div class="aviso__cuerpo"><h3 class="aviso__titulo">Último día de cada mes' + (anio ? ' de ' + anio : '') + '</h3><p>' + texto + '</p></div></div>';
  }
  function seccionInsumos() {
    const u = V('metodo_ultimo_dia_mes') || {};
    const cuando = u.fecha_comprobacion ? ' el ' + fechaL(u.fecha_comprobacion) : '';
    const lista = '<ul class="metodo__lista">' +
      '<li><strong>El reporte de flota de la empresa.</strong> De él se deriva una tabla sin datos personales (placa, ruta, modelo, marca, clase, carrocería, tipo de GPS, sentados y de pie); el original trae nombres, cédulas y teléfonos y no se versiona. Es lo único que se usa, y para una sola cosa: confirmar la capacidad de la ficha de arriba.</li>' +
      '<li><strong>El archivo de vehículos de la empresa.</strong> Coincide con la tabla de vehículos ya exportada, columna por columna; no aporta una variable nueva y no se usa.</li>' +
      '<li><strong>Los scripts SQL de los organizadores.</strong> La tubería con la que producen las tablas de timbradas por segmento de ruta. Se guardan como referencia y no se ejecutan: la base es compartida y de solo lectura, y las tablas que crean ya estaban exportadas.</li>' +
      '<li><strong>Los campos de despacho de la tabla de rutas.</strong> Frecuencias, tiempos y flota programada de las tres rutas: idénticos en la base y en la copia local; nada estaba en cero ni cambió.</li>' +
      '</ul>';
    return seccion('metodo-insumos', 'Lo que mandaron los organizadores',
      'Cerca del final del reto llegaron un reporte de flota, un archivo de vehículos, los scripts de preparación de la base y cuatro avisos. Se comprobó todo' + cuando + ': lo que traen confirma lo que ya se usaba y no cambia ningún resultado.',
      fichaCapacidad() + lineaUltimoDia() + lista);
  }

  // ---- 4. Cómo se mide -------------------------------------------------------------------------------------------------
  const ROTULOS_PESOS = { filas_peso_1: 'Filas con peso completo', filas_0_25: 'Filas con peso bajo: día atípico no predecible', filas_0_1: 'Filas con peso muy bajo: franja con fallas de registro',
    filas_ambas_reglas: 'Filas con las dos reglas', dias_atipicos_no_predecibles: 'Días atípicos no predecibles', dias_atipicos_total: 'Días atípicos investigados' };
  function seccionProtocolo() {
    const p = V('metodo_protocolo') || {};
    const bases = p.bases_WAPE || {};
    const lineas = Array.isArray(p.lineas_base) ? p.lineas_base : [];
    const filasBases = Object.keys(bases).map(function (k) {
      const texto = lineas.filter(function (t) { return llano(t).indexOf(k) === 0; })[0];
      return { celdas: [esc(texto ? llano(texto) : k), pct(bases[k], 2) + ' ' + fuente('metodo_protocolo', 'error de la línea base ' + k, 'bases_WAPE.' + k)] };
    });
    const tBases = filasBases.length ? tabla('Las líneas base obligatorias y su error a una semana', ['Línea base', 'Error (WAPE)'], filasBases, { compacta: true }) : '';
    const metricas = Array.isArray(p.metricas) ? '<ul class="metodo__lista">' + p.metricas.map(function (t) { return '<li>' + esc(llano(t)) + '</li>'; }).join('') + '</ul><p class="metodo__pie-tabla">' + fuente('metodo_protocolo', 'métricas del protocolo', 'metricas') + ' Las métricas del protocolo común.</p>' : '';
    const fichas = '<div class="cifras">' +
      ficha('Franjas de prueba', n(p.franjas_prueba), 'franjas', 'Ruta × día × hora de salida del último año, en pliegues mensuales con entrenamiento estrictamente anterior.', fuente('metodo_protocolo', 'franjas de prueba', 'franjas_prueba')) +
      (function () {
        const vv = V('metodo_variables') || {}; const cnt = vv.conteos || {};
        return ficha('Variables que usa el modelo', n(cnt.h7), 'a una semana', 'A un día de antelación usa ' + n(cnt.h1) + '. ' + fuente('metodo_variables', 'variables a un día', 'conteos.h1') + ' El primer modelo usaba ' + n(cnt.e1_h7) + '. ' + fuente('metodo_variables', 'variables del primer modelo', 'conteos.e1_h7'), fuente('metodo_variables', 'variables a una semana', 'conteos.h7'));
      })() +
      '</div>';
    // Variables por familia
    const vv = V('metodo_variables') || {};
    const fam = vv.por_familia || {};
    const ks = Object.keys(fam);
    let tFam = '';
    if (ks.length) {
      const total = ks.reduce(function (s, k) { return s + (esNum(fam[k]) ? fam[k] : 0); }, 0);
      tFam = desplegable('metodo-variables', 'Las variables por familia',
        tabla('', ['Familia', 'Columnas'], ks.map(function (k) { return { celdas: [esc(k), n(fam[k])] }; }).concat([{ clase: 'tabla__fila-total', celdas: ['Todas', n(total)] }]), { compacta: true }) +
        '<p class="texto-2">' + fuente('metodo_variables', 'variables por familia', 'por_familia') + ' Columnas de la tabla de modelado por familia; el total es la suma hecha en la pantalla.</p>');
    }
    // Pesos
    const pe = V('metodo_pesos_entrenamiento') || {};
    const filasPesos = Object.keys(ROTULOS_PESOS).filter(function (k) { return esNum(pe[k]); }).map(function (k) {
      return { celdas: [esc(ROTULOS_PESOS[k]), n(pe[k]) + ' ' + fuente('metodo_pesos_entrenamiento', ROTULOS_PESOS[k].toLowerCase(), k)] };
    });
    const pesos = filasPesos.length ? desplegable('metodo-pesos', 'Lo único que mejoró el modelo: no aprender de datos corruptos',
      '<p>Las franjas con fallas de registro y los días atípicos que no se pueden prever pesan menos en el entrenamiento; no se eliminan ni se imputan.</p>' +
      tabla('', ['Grupo', 'Filas o días'], filasPesos, { compacta: true })) : '';
    // Fugas
    const fg = V('metodo_sin_fugas') || {};
    const chips = ['h7_ok', 'h1_ok', 'controles_ok', 'determinismo_ok'].filter(function (k) { return typeof fg[k] === 'boolean'; }).map(function (k) {
      const txt = { h7_ok: 'a una semana', h1_ok: 'a un día', controles_ok: 'controles', determinismo_ok: 'determinismo' }[k];
      return chipSiNo(fg[k], txt);
    }).join('');
    const fugas = chips ? '<div class="metodo__chips"><span class="texto-2 pequeno">Prueba de fugas de la ingeniería de variables' + (fg.T ? ' (corte el ' + fechaL(fg.T) + ')' : '') + ':</span>' + chips + fuente('metodo_sin_fugas', 'prueba de fugas') + '</div>' : '';
    return seccion('metodo-protocolo', 'Cómo se mide',
      'Todos los experimentos de pronóstico comparten un protocolo: pliegues mensuales del último año, entrenamiento solo con lo anterior a cada pliegue, las mismas líneas base y el error medido sobre las mismas franjas. Ningún rezago mira al futuro.',
      fichas + tBases + metricas + tFam + pesos + fugas);
  }

  // ---- 5. Índice de experimentos --------------------------------------------------------------------------------------
  // Una línea por experimento (sin cifras); la fecha y el veredicto de la revisión salen de metodo_experimentos.
  const INDICE = [
    ['E1_lgbm_salida', 'E1', 'Primer modelo: árboles por hora de salida con calendario y demanda reciente, frente a la regla manual.'],
    ['E2_granularidad', 'E2', 'Granularidad: a qué nivel de ruta, día y hora conviene pronosticar.'],
    ['E3_cuantiles_decision', 'E3', 'Pronóstico por cuantiles y su uso en la decisión de buses por hora.'],
    ['E4_clasicos', 'E4', 'Modelos clásicos con el mismo protocolo.'],
    ['E5_plantillas', 'E5', 'Plantillas de hoja de cálculo que Sobusa podría usar sin modelo.'],
    ['E6_por_ruta', 'E6', 'Un modelo por ruta frente a uno conjunto; las rutas se mueven juntas.'],
    ['E7_elasticidad', 'E7', 'Elasticidad β: cuántos pasajeros se pierden al quitar salidas, medida con fallas reales.'],
    ['E8_validacion_2026', 'E8', 'Validación con los datos nuevos del año siguiente.'],
    ['E9_clima', 'E9', 'Lluvia y demanda: cuánto explica y cuánto pesa.'],
    ['E10_dias_atipicos', 'E10', 'Días atípicos y calendarios escolar y universitario, con fuentes.'],
    ['E11_modelo_mejorado', 'E11', 'Modelo final: variantes, pesos a los datos corruptos y script de producción.'],
    ['E12_comparacion_modelos', 'E12', 'Comparación de muchos modelos con el mismo protocolo; el híbrido recomendado para producción.'],
    ['E13_limpieza_datos', 'E13', 'Limpieza de datos: el objetivo corregido con los viajes cancelados que corrieron; imputar empeora.'],
    ['D1_optimizacion', 'D1', 'Frecuencia recomendada por hora frente al oráculo.'],
    ['D2_flota', 'D2', 'Flota necesaria por hora: picos y valles de cada ruta.'],
    ['D3_recorridos_cortos', 'D3', 'Recorridos cortos: cuándo convienen.'],
    ['D4_regularidad', 'D4', 'Regularidad de los intervalos y espera en el paradero.'],
    ['D5_optimizacion_milp', 'D5', 'Optimización del horario con programación entera.'],
    ['D6_simulador', 'D6', 'Simulador de la ruta, salida a salida.'],
    ['P1_planificador', 'P1', 'Pruebas del planificador interactivo y de sus costos.'],
    ['P2_piloto_beta', 'P2', 'Diseño del piloto para medir β en la calle.'],
    ['costos', 'Costos', 'Costos con fuente pública, línea base y ahorro de cada escenario.'],
    ['simulacion_ahorro', 'Simulación', 'Simulación de ahorro día a día y análisis de conductores.'],
    ['sistema_tiempo_real', 'Tiempo real', 'Motor de despacho en tiempo real, backtest, replay y vista de la ciudad.'],
  ];
  function seccionExperimentos() {
    const c = C('metodo_experimentos');
    const v = (c && c.valor) || {};
    const filas = INDICE.map(function (e) {
      const r = v[e[0]];
      let rev;
      if (r && (r.fecha || r.veredicto)) {
        rev = (r.fecha ? esc(F.fecha(r.fecha)) : '—') + (r.veredicto ? chipVeredicto(r.veredicto) : '') + ' ' + fuente('metodo_experimentos', 'revisión de ' + e[1], e[0]);
      } else {
        rev = '<span class="texto-3">No registrada en su archivo de resultados; la revisión está en su README.</span>';
      }
      return { celdas: [esc(e[1]), esc(e[2]), rev] };
    });
    const tIndice = tabla('', ['Experimento', 'Qué responde', 'Revisión independiente'], filas, { compacta: true, apilable: true, textoEn: [1, 2], clase: 'metodo__indice' });
    const pie = '<p class="metodo__pie-tabla">' + fuente('metodo_experimentos', 'índice de experimentos') + ' Fecha y veredicto que guarda el archivo de resultados de cada experimento. Cada carpeta tiene el código que lo reproduce, su README con la sección de verificación, sus resultados y sus figuras.</p>';
    const rondas = C('metodo_rondas_verificacion');
    const tRondas = rondas && typeof rondas.valor === 'string' ? aviso('nota', 'Tres rondas de revisión adversarial', '<p class="metodo__texto-largo">' + esc(llano(rondas.valor)) + ' ' + fuente('metodo_rondas_verificacion', 'rondas de verificación') + '</p>') : '';
    return seccion('metodo-experimentos', 'Los experimentos y su revisión',
      'Cada pregunta del proyecto tiene su experimento reproducible. Un revisor independiente volvió a calcular las cifras de cada uno con código propio y dejó su veredicto.',
      tIndice + pie + tRondas);
  }

  // ---- 6. Las cifras con varias bases ----------------------------------------------------------------------------------
  function seccionBases() {
    const lista = Array.isArray(D && D.contradicciones) ? D.contradicciones : [];
    if (!lista.length) return '';
    const meta = (D && D.meta) || {};
    const pop = fuenteObjeto('fm-bases', { archivo: meta.contrato || 'app/inventario_cifras.json', clave: 'contradicciones', experimento: 'inventario de cifras de la app',
      verificado: 'parcial', revision: 'Cada cifra citada tiene su propia revisión en la pantalla que la usa; esta tabla copia el texto del inventario.' }, 'cifras con varias bases');
    const filas = lista.map(function (x) {
      return { celdas: [esc(sinCodigos(x.tema)), esc(sinCodigos(x.fuentes)), esc(sinCodigos(x.prevalece))] };
    });
    const t = tabla('', ['Qué cifra', 'Qué bases hay', 'Cuál usa la app y por qué'], filas, { compacta: true, apilable: true, textoEn: [1, 2] });
    return seccion('metodo-bases', 'Las cifras con varias bases',
      'Una misma cantidad puede salir distinta según la fuente: otra base de días, otra contabilidad o una corrida más nueva. La app no las mezcla en una misma tarjeta: cada pantalla usa la base de su fuente y la rotula. Esta tabla dice cuál se usa y por qué.',
      t + '<p class="metodo__pie-tabla">' + pop + ' ' + n(lista.length) + ' cifras con más de una base, tal como las registra el inventario de cifras de la app.</p>');
  }

  // ---- 7. Cómo se verificó la app ------------------------------------------------------------------------------------
  function recuento() {
    const p = (D && D.pantallas) || {};
    const porPantalla = [];
    const tot = { n: 0, si: 0, parcial: 0, no: 0 };
    (app().pantallas || []).forEach(function (m) {
      const cifras = p[m.id] || {};
      const r = { id: m.id, nombre: m.nombre, n: 0, si: 0, parcial: 0, no: 0 };
      Object.keys(cifras).forEach(function (k) {
        const x = cifras[k];
        if (k === 'ficha' || !x || typeof x !== 'object') return;
        const ver = String(app().normalizarCifra(x).verificado || 'no').toLowerCase();
        r.n += 1;
        if (ver === 'sí' || ver === 'si') r.si += 1; else if (ver === 'parcial') r.parcial += 1; else r.no += 1;
      });
      porPantalla.push(r);
      ['n', 'si', 'parcial', 'no'].forEach(function (k) { tot[k] += r[k]; });
    });
    return { porPantalla: porPantalla, tot: tot };
  }
  function seccionVerificacion() {
    const meta = (D && D.meta) || {};
    const rc = recuento();
    const notas = Array.isArray(meta.notas) ? meta.notas : [];
    const pop = fuenteObjeto('fm-recuento', { archivo: 'app/datos_app.js', clave: 'pantallas.<pantalla>.<id>.verificado → n por valor (sí, parcial, no)', experimento: meta.generador || 'generador de la app',
      verificado: 'parcial', revision: 'Recuento hecho en la pantalla al abrirla; el verificador comprueba cada cifra con su archivo, no este recuento.', nota: notas[3] ? llano(notas[3]) : '' }, 'cifras de la app');
    const fichas = '<div class="cifras">' +
      ficha('Cifras en la app', n(rc.tot.n), 'cifras', 'Cada una con archivo, clave, experimento y revisor en su botón de fuente.', pop) +
      ficha('Con revisor independiente', n(rc.tot.si), 'cifras', 'Recalculadas por un revisor con código propio' + (rc.tot.n ? ': ' + pct(rc.tot.si / rc.tot.n * 100, 0) + ' del total.' : '.'), pop) +
      ficha('Con revisión parcial', n(rc.tot.parcial), 'cifras', 'El archivo se revisó, pero no esa cifra o esa corrida.', pop) +
      ficha('Sin revisor', n(rc.tot.no), 'cifras', 'Se dice en cada una; la mayoría son del prototipo de tiempo real.', pop) +
      '</div>';
    const tPant = tabla('Por pantalla', ['Pantalla', 'Cifras', 'Con revisor', 'Parcial', 'Sin revisor'], rc.porPantalla.map(function (r) {
      return { celdas: ['<a href="#' + esc(r.id) + '">' + esc(r.nombre) + '</a>', n(r.n), n(r.si), n(r.parcial), n(r.no)] };
    }).concat([{ clase: 'tabla__fila-total', celdas: ['Todas', n(rc.tot.n), n(rc.tot.si), n(rc.tot.parcial), n(rc.tot.no)] }]), { compacta: true });
    const generado = meta.generado ? fechaL(String(meta.generado).slice(0, 10)) + (String(meta.generado).length > 10 ? ' a las ' + esc(String(meta.generado).slice(11)) : '') : '';
    const pasos = '<ol class="metodo__lista">' +
      '<li><strong>Un contrato.</strong> El inventario de cifras (<code>' + esc(meta.contrato || 'app/inventario_cifras.json') + '</code>) dice, para cada id, de qué archivo y con qué clave se lee.</li>' +
      '<li><strong>Un generador.</strong> <code>' + esc(meta.generador || 'app/generar_datos_app.py') + '</code> lee cada cifra de su archivo de resultados y escribe <code>app/datos_app.js</code>, con el archivo, la clave, el experimento y la marca de revisión de cada una' + (generado ? ' (última corrida: ' + generado + ')' : '') + '.</li>' +
      '<li><strong>Un verificador.</strong> <code>' + esc(meta.verificador || 'app/verificar_datos_app.py') + '</code> vuelve a leer cada cifra con código propio y la compara; termina con error si alguna difiere.</li>' +
      '<li><strong>Los revisores.</strong> Las marcas «sí», «parcial» y «no» vienen de las revisiones adversariales de cada experimento, no de la app; la app solo las copia y las muestra.</li>' +
      '</ol>';
    const tNotas = notas.length ? desplegable('metodo-notas-app', 'Notas del generador', '<ul class="metodo__notas">' + notas.map(function (t) { return '<li>' + esc(llano(t)) + '</li>'; }).join('') + '</ul>') : '';
    return seccion('metodo-verificacion', 'Cómo se verificó la app',
      'Ninguna cifra se escribe a mano: un generador las lee de los resultados, un verificador las vuelve a leer y cada una conserva la marca del revisor independiente de su experimento.',
      fichas + pasos + tPant + tNotas);
  }

  // ---- 8. Quiénes y con qué ---------------------------------------------------------------------------------------------
  function seccionEquipo() {
    const equipo = V('metodo_equipo');
    const nombres = Array.isArray(equipo) ? '<ul class="metodo__nombres">' + equipo.map(function (x) { return '<li>' + esc(x) + '</li>'; }).join('') + '</ul>' +
      '<p class="texto-2">Universidad del Norte, Barranquilla. ' + fuente('metodo_equipo', 'equipo') + '</p>' : '';
    const h = V('metodo_herramientas') || {};
    const python = typeof h.python === 'string' ? esc(llano(h.python).replace(/\s*En otro equipo:\s*$/, '')) : '';
    const e12 = typeof h.e12 === 'string' ? esc(llano(h.e12)) : '';
    const herramientas = (python || e12) ? '<div class="prosa">' + (python ? '<p class="metodo__texto-largo">' + python + ' ' + fuente('metodo_herramientas', 'entorno de Python', 'python') + '</p>' : '') +
      (e12 ? '<p class="metodo__texto-largo">' + e12 + ' ' + fuente('metodo_herramientas', 'entorno de la comparación de modelos', 'e12') + '</p>' : '') +
      '<p class="metodo__texto-largo">La app y las páginas interactivas son HTML, CSS y JavaScript sin servidor: se abren con doble clic, cargan sus bibliotecas y su mapa de copias locales y funcionan sin internet, salvo el mapa base del tablero y de la consola.</p></div>' : '';
    const limites = '<ul class="metodo__lista">' +
      '<li>El hallazgo honesto de un día cargado, en el que el plan pone menos salidas de las que hicieron falta: en <a href="#inicio">Inicio</a> y en <a href="#ciudad">Ciudad</a>.</li>' +
      '<li>Los problemas de los datos (viajes marcados cancelados que corrieron, días con fallas de registro) y el objetivo corregido: en <a href="#demanda">Demanda</a>.</li>' +
      '<li>El cambio de nivel del año siguiente, que el modelo no puede prever: en <a href="#modelo">Modelo</a>.</li>' +
      '<li>Las dos contabilidades del saldo y la β medida con fallas en vez de con recortes planificados: en <a href="#resultado">Resultado</a> y en <a href="#piloto">Piloto</a>.</li>' +
      '<li>La corrida vigente del backtest, que no tuvo revisor: en <a href="#despacho">Despacho</a>.</li>' +
      '</ul>';
    const enlaces = '<p class="metodo__enlaces texto-3">Diseño de la app: ' +
      '<a href="app/paleta.html" target="_blank" rel="noopener">Paleta de colores' + icono('externo') + '</a>' +
      '<a href="app/DISEÑO.md" target="_blank" rel="noopener">Guía del sistema de diseño' + icono('externo') + '</a>' +
      '<a href="app/DATOS.md" target="_blank" rel="noopener">Inventario de cifras' + icono('externo') + '</a></p>';
    return seccion('metodo-equipo', 'Quiénes y con qué',
      'El equipo, las herramientas y dónde están los límites que cada pantalla declara.',
      nombres + herramientas + '<h3 class="metodo__h3">Dónde están los límites</h3>' + limites + enlaces);
  }

  // ---- 9. El tablero (el iframe lo monta app.js a partir de «modulo») ---------------------------------------------
  function seccionTablero() {
    return seccion('metodo-tablero', 'Explorar los datos',
      'Debajo queda el tablero del análisis exploratorio, abierto en su pestaña de datos: el inventario de tablas, la calidad y la cobertura. Desde allí se cambia de pestaña (mapa, demanda, horas, operación, ocupación, flota) o se abre aparte.',
      '');
  }

  // ---- Contrato de la pantalla ---------------------------------------------------------------------------------------
  function render(contenedor, datos) {
    cont = contenedor;
    D = datos || global.DATOS_APP || {};
    faltantes = [];
    temas = {};
    (Array.isArray(D.contradicciones) ? D.contradicciones : []).forEach(function (x) { if (x && x.id) temas[x.id] = llano(x.tema); });
    estilos();
    if (!C('metodo_datos_crudos')) {
      cont.innerHTML = aviso('atencion', 'Sin datos del método', '<p>Falta app/datos_app.js o no trae las cifras de esta pantalla. Se genera con «python app/generar_datos_app.py» desde la carpeta del proyecto.</p>');
      return;
    }
    const partes = [entradilla(), seccionDatos(), seccionReglas(), seccionInsumos(), seccionProtocolo(), seccionExperimentos(), seccionBases(), seccionVerificacion(), seccionEquipo(), seccionTablero()];
    const cab = faltantes.length ? aviso('atencion', 'Faltan datos en app/datos_app.js', '<p>Esta pantalla no encontró ' + n(faltantes.length) + ' ids: <code>' + faltantes.map(esc).join('</code>, <code>') + '</code>. Donde faltan se muestra «—».</p>') : '';
    cont.innerHTML = '<div id="metodo-cuerpo">' + cab + partes.join('') + '</div>';
    COMPONENTES.fuentes(cont);
  }

  function registrar(d) { (typeof global.registrarPantalla === 'function' ? global.registrarPantalla : function (x) { (global.__pantallasRegistradas = global.__pantallasRegistradas || []).push(x); })(d); }
  registrar({
    id: ID,
    pregunta: '¿De dónde sale todo?',
    subtitulo: 'Los datos, las reglas, los experimentos y las revisiones que hay detrás de cada cifra de la app: todo se lee de archivos del proyecto y se vuelve a comprobar.',
    icono: 'metodo',
    interruptor: [],
    modulo: { pagina: 'EDA_visual.html', hash: 'datos', nombre: 'Tablero del análisis exploratorio' },
    render: render,
    actualizar: function () {},
    salir: function () { cont = null; },
  });
})(window);
