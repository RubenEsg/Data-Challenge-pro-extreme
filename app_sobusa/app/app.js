// Sobusa Despacho · app.js
// La app: registro de pantallas, enrutado por hash (#pantalla?clave=valor), estado compartido, cabecera única con el
// interruptor Hoy / Con el modelo / Oráculo, módulos embebidos (iframes que nunca se ocultan con display:none; siempre en claro) y
// datos. Sigue la sección 5 de app/DISEÑO.md. Se carga el último; las pantallas (app/pantallas/*.js) se registran antes
// con registrarPantalla({...}) y aquí se recogen.
//
// Lo que ofrece a las pantallas (window.app):
//   app.estado                      copia de solo lectura del estado compartido
//   app.ponerEstado({ escenario })  pide un cambio; la app guarda el hash y llama actualizar(estado) (o render)
//   app.irA('ciudad', { dia, hora })  cambia de pantalla con parámetros
//   app.datos / app.cifra('inicio', 'inicio_beta')  las cifras de datos_app.js, normalizadas
//   app.popoverFuente(id, cifra, titulo) / app.botonFuente(id) / app.chipVerificado(v) / app.activarFuentes()
//   app.modulo('horario') → { iframe, enviar(msg), irA(hash) }   el iframe de una pantalla con módulo
(function (global) {
  'use strict';

  const doc = document;
  const icono = ICONOS.svg;

  // ---- 1. Las nueve pantallas, en el orden de la barra lateral (sección 7 de DISEÑO.md) ---------------------------
  // Aquí solo va lo que necesita la barra (nombre, pregunta, icono): las nueve tienen archivo propio en app/pantallas/
  // y cada una declara en su definición el subtítulo, el interruptor y su módulo embebido (3-nov-2026). En el módulo,
  // completo: true → ocupa toda la zona de contenido; si no (Demanda, Horario, Despacho, Ciudad, Método), va al final
  // de la pantalla, debajo del resumen. Su hash puede depender del estado (día y hora en consola y vista 3D).
  function hhmm(h) { return String(h || '').slice(0, 5); }
  const PANTALLAS = [
    { id: 'inicio', nombre: 'Inicio', pregunta: '¿Qué proponemos?', icono: 'inicio' },
    { id: 'demanda', nombre: 'Demanda', pregunta: '¿Cuántos pasajeros habrá?', icono: 'demanda' },
    { id: 'modelo', nombre: 'Modelo', pregunta: '¿Qué modelo es y por qué?', icono: 'modelo' },
    { id: 'horario', nombre: 'Horario', pregunta: '¿Cuántos buses y cada cuánto?', icono: 'horario' },
    { id: 'despacho', nombre: 'Despacho', pregunta: '¿Qué hago ahora?', icono: 'despacho' },
    { id: 'ciudad', nombre: 'Ciudad', pregunta: '¿Cómo se ve en la calle?', icono: 'ciudad' },
    { id: 'resultado', nombre: 'Resultado', pregunta: '¿Qué gana Sobusa?', icono: 'resultado' },
    { id: 'piloto', nombre: 'Piloto', pregunta: '¿Cómo lo comprobamos?', icono: 'piloto' },
    { id: 'metodo', nombre: 'Método y datos', pregunta: '¿De dónde sale todo?', icono: 'metodo' },
  ];
  const POR_ID = {};
  PANTALLAS.forEach(function (p) { POR_ID[p.id] = p; });

  const ESCENARIOS = ['hoy', 'modelo', 'oraculo'];
  const TOOLTIP_NO_APLICA = 'No aplica a esta pantalla';

  // ---- 2. Estado compartido (de solo lectura para las pantallas) -------------------------------------------------
  const POR_DEFECTO = { escenario: 'hoy', modelo: 'final', ruta: 'Todas', dia: '2025-06-03', hora: '07:30', plan: 'b' };
  const VALIDOS = {
    escenario: function (v) { return ESCENARIOS.indexOf(v) >= 0; },
    modelo: function (v) { return v === 'final' || v === 'hibrido'; },
    ruta: function (v) { return ['Todas', 'SILENCIO', 'CRA 54', 'CL 72'].indexOf(v) >= 0; },
    dia: function (v) { return /^\d{4}-\d{2}-\d{2}$/.test(v); },
    hora: function (v) { return /^\d{2}:\d{2}(:\d{2})?$/.test(v); },
    plan: function (v) { return v === 'a' || v === 'b'; },
  };
  const CLAVES = Object.keys(POR_DEFECTO);
  const estado = Object.assign({ pantalla: null }, POR_DEFECTO);
  function estadoLectura() { return Object.freeze(Object.assign({}, estado)); }

  const registro = {};    // id → definición registrada
  const instancias = {};  // id → { contenedor, pintada }
  const modulos = {};     // id → { elemento, iframe, listo, cargado, pagina }
  let datos = null;
  let activa = null;
  let primeraApertura = true;
  let irArriba = false;            // V14: un clic en un enlace abre la pantalla arriba; Atrás/Adelante vuelve al punto de lectura
  let cabeceraCompacta = function () {};
  // Pantallas fijas de la barra del teléfono; el resto va en la hoja «Más» (A07).
  const PRIMARIAS = ['inicio', 'modelo', 'horario', 'resultado'];

  function esc(s) { return String(s === undefined || s === null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'); }

  // ---- 3. Datos: app/datos_app.js, con los ids del inventario de cifras ----------------------------------------------
  function normalizarCifra(c) {
    if (c === null || c === undefined) return null;
    if (typeof c !== 'object') return { valor: c };
    const conf = c.confianza || {};
    const n = Object.assign({}, c);
    if (!('valor' in n) && 'valor_actual' in n) n.valor = n.valor_actual;
    if (!n.verificado) n.verificado = conf.verificado_independiente || 'no';
    if (!n.revision && conf.donde) n.revision = conf.donde;
    return n;
  }
  function cifra(pantalla, id) {
    if (!datos) return null;
    const p = datos.pantallas && datos.pantallas[pantalla];
    const c = (p && p[id]) || (datos.cifras && datos.cifras[id]) || null;
    return normalizarCifra(c);
  }

  // Sin app/datos_app.js la app se abre igual, sin cifras, con un aviso que dice cómo generarlo.
  function cargarDatos(cb) {
    if (global.DATOS_APP && global.DATOS_APP.pantallas) { cb(global.DATOS_APP); return; }
    console.error('Sobusa Despacho: falta app/datos_app.js (lo genera app/generar_datos_app.py); la app se abre sin cifras.');
    global.DATOS_APP = { sinDatos: true, pantallas: {} };
    cb(global.DATOS_APP);
  }

  // ---- 4. Fuentes: popover por cifra ------------------------------------------------------------------------------
  function chipVerificado(v) {
    const ver = String(v || 'no').toLowerCase();
    const clase = ver === 'sí' || ver === 'si' ? 'bien' : ver === 'parcial' ? 'atencion' : 'critico';
    const texto = clase === 'bien' ? 'sí' : clase === 'atencion' ? 'parcial' : 'no';
    const ver2 = clase === 'bien' ? 'si' : clase === 'atencion' ? 'parcial' : 'no';
    return '<span class="verificado verificado--' + ver2 + '">' + icono(clase === 'bien' ? 'bien' : 'alerta') + 'Revisor independiente: ' + texto + '</span>';
  }
  function popoverFuente(id, c, titulo) {
    c = normalizarCifra(c) || {};
    const cont = doc.getElementById('popovers');
    const viejo = doc.getElementById(id);
    if (viejo) viejo.remove();
    const div = doc.createElement('div');
    div.id = id; div.className = 'fuente-pop'; div.setAttribute('popover', '');
    const crudo = typeof c.valor === 'number' || typeof c.valor === 'string' ? String(c.valor) : null;
    let h = '<div class="fuente-pop__cab"><span class="fuente-pop__titulo">' + icono('fuente') + 'Fuente' + (titulo ? ' · ' + esc(titulo) : '') + '</span>' +
      '<button class="boton boton--fantasma boton--icono boton--pequeno" type="button" data-cerrar aria-label="Cerrar">' + icono('cerrar') + '</button></div><dl class="fuente-pop__datos">';
    if (c.que_mide) h += '<dt>Qué mide</dt><dd>' + c.que_mide + '</dd>';   // HTML armado en la pantalla con cifras de datos_app.js
    if (c.archivo) h += '<dt>Archivo</dt><dd><code>' + esc(c.archivo) + '</code></dd>';
    if (c.clave) h += '<dt>Clave</dt><dd>' + esc(c.clave) + '</dd>';
    if (c.experimento) h += '<dt>Experimento</dt><dd>' + esc(c.experimento) + '</dd>';
    if (crudo !== null) {
      // El valor del archivo, escrito en español (coma decimal) y con toda su precisión, hasta cuatro decimales.
      const dec = typeof c.valor === 'number' ? Math.min(4, (String(c.valor).split('.')[1] || '').length) : 0;
      const texto = typeof c.valor === 'number' ? COMPONENTES.formato.numero(c.valor, dec) : crudo;
      h += '<dt>Valor en el archivo</dt><dd><span class="num">' + esc(texto) + '</span>' + (c.unidad ? ' <span class="texto-2">' + esc(c.unidad) + '</span>' : '') + '</dd>';
    }
    h += '<dt>Revisor</dt><dd>' + chipVerificado(c.verificado) + (c.revision ? '<span class="oculto">. </span> <span class="texto-2">' + esc(c.revision) + '</span>' : '') + '</dd>';
    if (c.nota) h += '<dt>Nota</dt><dd>' + esc(c.nota) + '</dd>';
    h += '</dl><div class="fuente-pop__pie">Ninguna cifra está escrita a mano: app/verificar_datos_app.py compara este valor con el archivo.' + '</div>';
    div.innerHTML = h;
    cont.appendChild(div);
    return div;
  }
  // Un solo popover con las fuentes de varias cifras: [[cifra, título], …] (la fila de botones de un aviso se junta en uno).
  function popoverFuentes(id, lista, titulo) {
    const cont = doc.getElementById('popovers');
    const viejo = doc.getElementById(id);
    if (viejo) viejo.remove();
    const div = doc.createElement('div');
    div.id = id; div.className = 'fuente-pop'; div.setAttribute('popover', '');
    let h = '<div class="fuente-pop__cab"><span class="fuente-pop__titulo">' + icono('fuente') + 'Fuentes' + (titulo ? ' · ' + esc(titulo) : '') + '</span>' +
      '<button class="boton boton--fantasma boton--icono boton--pequeno" type="button" data-cerrar aria-label="Cerrar">' + icono('cerrar') + '</button></div>';
    lista.forEach(function (par) {
      const c = normalizarCifra(par[0]) || {};
      h += '<div class="fuente-pop__grupo"><p class="fuente-pop__subtitulo">' + esc(par[1]) + '</p><dl class="fuente-pop__datos">';
      if (c.archivo) h += '<dt>Archivo</dt><dd><code>' + esc(c.archivo) + '</code></dd>';
      if (c.clave) h += '<dt>Clave</dt><dd>' + esc(c.clave) + '</dd>';
      if (c.experimento) h += '<dt>Experimento</dt><dd>' + esc(c.experimento) + '</dd>';
      if (typeof c.valor === 'number') {
        const dec = Math.min(4, (String(c.valor).split('.')[1] || '').length);
        h += '<dt>Valor en el archivo</dt><dd><span class="num">' + esc(COMPONENTES.formato.numero(c.valor, dec)) + '</span>' + (c.unidad ? ' <span class="texto-2">' + esc(c.unidad) + '</span>' : '') + '</dd>';
      }
      h += '<dt>Revisor</dt><dd>' + chipVerificado(c.verificado) + (c.revision ? '<span class="oculto">. </span> <span class="texto-2">' + esc(c.revision) + '</span>' : '') + '</dd>';
      if (c.nota) h += '<dt>Nota</dt><dd>' + esc(c.nota) + '</dd>';
      h += '</dl></div>';
    });
    h += '<div class="fuente-pop__pie">Ninguna cifra está escrita a mano: app/verificar_datos_app.py compara estos valores con los archivos.</div>';
    div.innerHTML = h;
    cont.appendChild(div);
    return div;
  }
  function botonFuente(idPop, texto) {
    return '<button class="fuente' + (texto ? ' fuente--texto' : '') + '" type="button" popovertarget="' + esc(idPop) + '" aria-expanded="false" aria-label="Fuente de la cifra">' + icono('fuente') + (texto ? esc(texto) : '') + '</button>';
  }
  function activarFuentes() { COMPONENTES.fuentes(doc); }

  // ---- 5. Barra lateral ---------------------------------------------------------------------------------------------
  // Cada pantalla tiene su color (tokens --pantalla-<id> de tokens.css): su ícono va en blanco dentro de un cuadro
  // redondeado de ese color, como en Ajustes del iPhone. Es lo único que se pinta con él.
  function cuadro(id, nombreIcono, clase) {
    return '<span class="cuadro-color' + (clase ? ' ' + clase : '') + '" style="--cuadro: var(--pantalla-' + id + ')" aria-hidden="true">' + icono(nombreIcono) + '</span>';
  }
  function pintarBarra() {
    doc.getElementById('nav-pantallas').innerHTML = PANTALLAS.map(function (p) {
      return '<li' + (PRIMARIAS.indexOf(p.id) < 0 ? ' class="lateral__item--sec"' : '') + '><a class="lateral__enlace" href="#' + p.id + '" data-pantalla="' + p.id + '">' + cuadro(p.id, p.icono) +
        '<span class="lateral__texto"><span class="lateral__titulo">' + esc(p.nombre) + '</span><span class="lateral__pregunta">' + esc(p.pregunta) + '</span></span></a></li>';
    }).join('') +
      '<li class="lateral__item--mas"><button class="lateral__enlace" type="button" id="boton-mas" aria-haspopup="dialog" aria-controls="hoja-mas" aria-label="Más pantallas">' +
      '<span class="cuadro-color" data-mas-icono aria-hidden="true">' + icono('mas') + '</span><span class="lateral__texto"><span class="lateral__titulo" data-mas-nombre>Más</span></span></button></li>';
    doc.getElementById('hoja-lista').innerHTML = PANTALLAS.map(function (p) {
      return '<li><a class="hoja__enlace" href="#' + p.id + '" data-pantalla="' + p.id + '">' + cuadro(p.id, p.icono) +
        '<span class="hoja__texto"><span class="hoja__nombre">' + esc(p.nombre) + '</span><span class="hoja__pregunta">' + esc(p.pregunta) + '</span></span></a></li>';
    }).join('');
  }
  function iniciarHoja() {
    const hoja = doc.getElementById('hoja-mas');
    const boton = doc.getElementById('boton-mas');
    if (!hoja || !boton) return;
    boton.addEventListener('click', function () {
      if (typeof hoja.showModal === 'function') hoja.showModal(); else hoja.setAttribute('open', '');
    });
    const cerrar = function () { if (typeof hoja.close === 'function') hoja.close(); else hoja.removeAttribute('open'); };
    // Se cierra con Esc (lo hace el navegador), con la X, al tocar el fondo y al elegir una pantalla.
    hoja.addEventListener('click', function (e) {
      if (e.target === hoja || e.target.closest('[data-cerrar-hoja]')) { cerrar(); return; }
      const a = e.target.closest('a.hoja__enlace');
      if (a) { irArriba = true; cerrar(); }
    });
  }
  function marcarEnlace(id) {
    doc.querySelectorAll('#nav-pantallas a.lateral__enlace, #hoja-lista .hoja__enlace').forEach(function (a) {
      if (a.dataset.pantalla === id) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current');
    });
    // Si la pantalla abierta no está entre las cuatro fijas del teléfono, «Más» toma su icono y su nombre.
    const mas = doc.getElementById('boton-mas');
    if (!mas) return;
    const meta = POR_ID[id];
    const fuera = meta && PRIMARIAS.indexOf(id) < 0;
    mas.classList.toggle('lateral__enlace--activo', !!fuera);
    const cuadroMas = mas.querySelector('[data-mas-icono]');
    cuadroMas.innerHTML = icono(fuera ? meta.icono : 'mas');
    if (fuera) cuadroMas.style.setProperty('--cuadro', 'var(--pantalla-' + id + ')'); else cuadroMas.style.removeProperty('--cuadro');
    // En la barra cabe una sola palabra («Método y datos» → «Método»); el nombre completo va en aria-label.
    mas.querySelector('[data-mas-nombre]').textContent = fuera ? meta.nombre.split(' ')[0] : 'Más';
    mas.setAttribute('aria-label', fuera ? 'Más pantallas (ahora: ' + meta.nombre + ')' : 'Más pantallas');
    if (fuera) mas.setAttribute('aria-current', 'page'); else mas.removeAttribute('aria-current');
  }
  // La pregunta de cada pantalla va como title del enlace (en la barra se lee solo el nombre).
  function titulosBarra() {
    doc.querySelectorAll('#nav-pantallas a.lateral__enlace').forEach(function (a) {
      const p = POR_ID[a.dataset.pantalla];
      if (p) a.title = p.nombre + ' · ' + p.pregunta;
    });
  }

  // ---- 6. Cabecera única e interruptor -----------------------------------------------------------------------------
  function opcionesDe(def) {
    const lista = (def && def.interruptor) || [];
    return lista.map(function (o) { return typeof o === 'string' ? { valor: o } : o; }).filter(function (o) { return o && VALIDOS.escenario(o.valor); });
  }
  function pintarCabecera(meta, def, opciones) {
    doc.getElementById('cab-rotulo').textContent = meta.nombre;
    const cabCuadro = doc.getElementById('cab-cuadro');
    if (cabCuadro && meta.id) { cabCuadro.style.setProperty('--cuadro', 'var(--pantalla-' + meta.id + ')'); cabCuadro.innerHTML = icono(meta.icono); }
    doc.getElementById('cab-pregunta').textContent = (def && def.pregunta) || meta.pregunta;
    doc.getElementById('cab-compacta-titulo').textContent = (def && def.pregunta) || meta.pregunta;
    let sub = '';
    if (def) {
      try { sub = typeof def.subtitulo === 'function' ? def.subtitulo(datos, estadoLectura()) : def.subtitulo; } catch (e) { console.error('Sobusa Despacho: el subtítulo de «' + def.id + '» falló', e); }
    }   // sin definición (su archivo no cargó): cabecera sin subtítulo
    doc.getElementById('cab-subtitulo').textContent = sub || '';
    // Una pantalla sin escenarios (Modelo, Piloto) no muestra el interruptor: un «Hoy» marcado y apagado confunde.
    doc.getElementById('escenario').hidden = !opciones.length;
    doc.getElementById('escenario-compacto').hidden = !opciones.length;
    ESCENARIOS.forEach(function (v) {
      const input = doc.getElementById('esc-' + v);
      const label = doc.getElementById('op-' + v);
      const op = opciones.filter(function (o) { return o.valor === v; })[0];
      input.disabled = !op;
      input.checked = estado.escenario === v;
      const etiqueta = (op && op.etiqueta) || { hoy: 'Hoy', modelo: 'Con el modelo', oraculo: 'Oráculo' }[v];
      label.querySelector('[data-etiqueta]').textContent = etiqueta;
      const tip = label.querySelector('[data-tooltip]');
      const texto = op ? (op.tooltip || '') : ((def && def.tooltipInterruptor) || TOOLTIP_NO_APLICA);
      tip.textContent = texto;
      tip.hidden = !texto;
      label.classList.toggle('con-tooltip', !!texto);
      // La cabecera compacta lleva el mismo interruptor; si una opción no aplica, no se muestra.
      const inputC = doc.getElementById('escc-' + v);
      inputC.disabled = !op;
      inputC.checked = estado.escenario === v;
      doc.getElementById('opc-' + v).hidden = !op;
      doc.getElementById('opc-' + v).querySelector('[data-etiqueta]').textContent = etiqueta;
    });
  }
  function sincronizarInterruptor() {
    ESCENARIOS.forEach(function (v) {
      doc.getElementById('esc-' + v).checked = estado.escenario === v;
      doc.getElementById('escc-' + v).checked = estado.escenario === v;
    });
  }
  // A14: la cabecera compacta aparece cuando el título sale de la vista por arriba (solo si la pantalla tiene interruptor).
  function vigilarCabecera() {
    const h1 = doc.getElementById('cab-pregunta');
    const barra = doc.getElementById('cab-compacta');
    if (!h1 || !barra || !('IntersectionObserver' in global)) return;
    let fuera = false;
    cabeceraCompacta = function () {
      const ver = fuera && !doc.getElementById('escenario').hidden && !doc.getElementById('contenido').classList.contains('contenido--modulo');
      barra.classList.toggle('cabecera-compacta--visible', ver);
    };
    new IntersectionObserver(function (entradas) {
      const e = entradas[entradas.length - 1];
      fuera = !e.isIntersecting && e.boundingClientRect.top < 0;
      cabeceraCompacta();
    }).observe(h1);
  }
  // V19: los cambios de escenario se anuncian a los lectores de pantalla.
  function anunciar(texto) {
    const p = doc.getElementById('anuncio');
    if (!p) return;
    p.textContent = '';
    global.setTimeout(function () { p.textContent = texto; }, 50);
  }
  function mostrarAviso(html, clase) {
    const cont = doc.getElementById('avisos-app');
    cont.querySelectorAll('[data-aviso-navegacion]').forEach(function (n) { n.remove(); });
    if (html) {
      cont.insertAdjacentHTML('beforeend', '<div class="aviso aviso--' + (clase || 'atencion') + '" role="status" data-aviso-navegacion>' + icono('alerta') + '<div class="aviso__cuerpo"><p>' + html + '</p></div></div>');
    }
    cont.hidden = !cont.children.length;
  }
  function avisoSinDatos() {
    if (!datos || !datos.sinDatos) return;
    const cont = doc.getElementById('avisos-app');
    cont.insertAdjacentHTML('beforeend', '<div class="aviso aviso--critico" role="alert" data-aviso-sin-datos>' + icono('alerta') + '<div class="aviso__cuerpo"><h2 class="aviso__titulo">Faltan los datos de la app</h2><p>No se encontró app/datos_app.js. Se genera con «python app/generar_datos_app.py» desde la carpeta del proyecto y se comprueba con «python app/verificar_datos_app.py».</p></div></div>');
    cont.hidden = false;
  }

  // ---- 7. Hash: #pantalla?clave=valor ---------------------------------------------------------------------------------
  function leerHash() {
    const h = location.hash.replace(/^#/, '');
    const i = h.indexOf('?');
    let id = i < 0 ? h : h.slice(0, i);
    try { id = decodeURIComponent(id); } catch (e) { /* se deja tal cual */ }
    const q = new URLSearchParams(i < 0 ? '' : h.slice(i + 1));
    const cambios = {};
    q.forEach(function (v, k) { if (VALIDOS[k] && VALIDOS[k](v)) cambios[k] = v; });
    return { id: id.trim() || 'inicio', cambios: cambios };
  }
  function hashDe(id) {
    const partes = [];
    CLAVES.forEach(function (k) {
      if (estado[k] !== POR_DEFECTO[k]) partes.push(k + '=' + encodeURIComponent(estado[k]).replace(/%3A/gi, ':').replace(/%20/g, '+'));
    });
    return '#' + id + (partes.length ? '?' + partes.join('&') : '');
  }
  function escribirHash() {
    const nuevo = hashDe(estado.pantalla);
    if (location.hash !== nuevo) { try { history.replaceState(null, '', nuevo); } catch (e) { location.hash = nuevo; } }
  }
  function enrutar() {
    const r = leerHash();
    Object.assign(estado, r.cambios);
    abrir(r.id);
    avisarDia(null);
  }
  // El día y la hora viajan a los módulos (consola, vista 3D, simulador) cada vez que cambian, vengan de donde vengan.
  let diaAvisado = null;
  function avisarDia(origen) {
    const k = estado.dia + '|' + estado.hora;
    if (diaAvisado === null) { diaAvisado = k; return; }   // al arrancar, los módulos se crean ya con el día en el hash
    if (k === diaAvisado) return;
    diaAvisado = k;
    enviarATodos({ tipo: 'dia', dia: estado.dia, hora: hhmm(estado.hora) }, origen);
  }

  // ---- 8. Abrir una pantalla ------------------------------------------------------------------------------------------
  function instanciaDe(id) {
    if (!instancias[id]) {
      const div = doc.createElement('div');
      div.className = 'pantalla';
      div.dataset.pantalla = id;
      div.hidden = true;
      doc.getElementById('pantallas').appendChild(div);
      instancias[id] = { contenedor: div, pintada: false };
    }
    return instancias[id];
  }
  // El módulo de una pantalla: el que declara su definición (null o ausente = sin módulo). La versión breve que app.js
  // pintaba para las pantallas sin archivo (tarjetaPendiente) se quitó el 3-nov-2026: las nueve tienen archivo propio.
  function moduloDe(id) {
    const def = registro[id];
    return (def && def.modulo) || null;
  }
  // Una pantalla que no se ve se oculta con hidden, salvo que tenga un iframe dentro: entonces se duerme fuera de
  // pantalla (nunca display:none sobre un iframe) y se vuelve inerte para el teclado y los lectores de pantalla.
  function mostrarContenedor(inst, visible) {
    const c = inst.contenedor;
    if (visible) { c.hidden = false; c.classList.remove('pantalla--dormida'); c.removeAttribute('inert'); c.removeAttribute('aria-hidden'); return; }
    if (c.querySelector('iframe')) {
      c.hidden = false;
      c.classList.add('pantalla--dormida');
      c.setAttribute('inert', '');
      c.setAttribute('aria-hidden', 'true');
    } else { c.hidden = true; c.classList.remove('pantalla--dormida'); }
  }
  function tarjetaError(meta, e) {
    return '<div class="aviso aviso--critico" role="alert">' + icono('alerta') + '<div class="aviso__cuerpo"><h2 class="aviso__titulo">La pantalla «' + esc(meta.nombre) + '» no se pudo pintar</h2><p>' + esc(e && e.message ? e.message : e) + '. Abre la consola del navegador para ver el detalle y vuelve a cargar la página.</p></div></div>';
  }
  function pintar(inst, def, meta) {
    if (!def) {   // su archivo no cargó: la pantalla queda vacía (cabecera sola) y la consola ya lo dijo
      if (!inst.pintada) { inst.contenedor.innerHTML = ''; inst.pintada = true; }
      return;
    }
    if (inst.pintada && inst.def !== def) inst.pintada = false;   // la definición llegó (o cambió) después de pintar
    inst.def = def;
    if (inst.pintada && typeof def.actualizar === 'function') {
      try { def.actualizar(estadoLectura()); } catch (e) { console.error('Sobusa Despacho: la pantalla «' + def.id + '» falló al actualizarse', e); }
      return;
    }
    if (inst.pintada && typeof def.salir === 'function') { try { def.salir(); } catch (e) { /* ya se va a repintar */ } }
    inst.contenedor.innerHTML = '';
    try { def.render(inst.contenedor, datos, estadoLectura()); }
    catch (e) { console.error('Sobusa Despacho: la pantalla «' + def.id + '» falló al pintarse', e); inst.contenedor.innerHTML = tarjetaError(meta, e); }
    inst.pintada = true;
    COMPONENTES.cifras(inst.contenedor);
    COMPONENTES.tablaGrafico(inst.contenedor);
    activarFuentes();
  }
  // Al salir: salir() libera gráficos y temporizadores, así que al volver la pantalla se pinta de nuevo con render
  // (actualizar solo se usa mientras la pantalla está abierta).
  function salirDe(id) {
    const def = registro[id];
    const inst = instancias[id];
    if (def && typeof def.salir === 'function' && inst && inst.pintada) {
      try { def.salir(); } catch (e) { console.error('Sobusa Despacho: salir() de «' + id + '» falló', e); }
      inst.pintada = false;
    }
    if (inst) inst.scroll = global.scrollY;
    if (modulos[id]) modulos[id].elemento.classList.add('modulo--dormido');
  }
  function enfocarTitulo() {
    const h1 = doc.getElementById('cab-pregunta');
    try { h1.focus({ preventScroll: true }); } catch (e) { h1.focus(); }
  }
  function abrir(id) {
    let meta = POR_ID[id];
    let aviso = null;
    if (!meta) { aviso = 'No existe la pantalla «' + esc(id) + '». Se abre Inicio.'; id = 'inicio'; meta = POR_ID.inicio; }
    const def = registro[id] || null;
    const cambio = activa !== id;
    if (cambio && activa) salirDe(activa);
    activa = id;
    estado.pantalla = id;
    const opciones = opcionesDe(def);
    if (opciones.length && !opciones.some(function (o) { return o.valor === estado.escenario; })) {
      estado.escenario = opciones.some(function (o) { return o.valor === 'modelo'; }) ? 'modelo' : opciones[0].valor;
    }
    pintarCabecera(meta, def, opciones);
    marcarEnlace(id);
    mostrarAviso(aviso);
    const inst = instanciaDe(id);
    const modulo = moduloDe(id);
    const main = doc.getElementById('contenido');
    main.classList.toggle('contenido--modulo', !!(modulo && modulo.completo));
    main.classList.toggle('contenido--con-modulo', !!(modulo && !modulo.completo));
    main.classList.toggle('contenido--ancho', !!(def && def.ancho === 'completo'));
    Object.keys(modulos).forEach(function (k) { if (k !== id) modulos[k].elemento.classList.add('modulo--dormido'); });
    Object.keys(instancias).forEach(function (k) { if (k !== id) mostrarContenedor(instancias[k], false); });
    mostrarContenedor(inst, true);
    pintar(inst, def, meta);
    if (modulo) despertarModulo(id, modulo);
    sincronizarAparte();
    escribirHash();
    doc.title = id === 'inicio' ? 'Sobusa Despacho' : meta.nombre + ' · Sobusa Despacho';
    if (cambio) {
      global.scrollTo(0, (!irArriba && inst.scroll) || 0);
      if (!primeraApertura) {
        enfocarTitulo();
        // A13: la pantalla entra con un fundido corto (no en las de módulo a pantalla completa: no se repinta WebGL).
        if (!(modulo && modulo.completo)) {
          [doc.getElementById('zona-cabecera'), inst.contenedor].forEach(function (el) { el.classList.remove('entrar'); void el.offsetWidth; el.classList.add('entrar'); });
        }
      }
    }
    irArriba = false;
    cabeceraCompacta();
    primeraApertura = false;
  }

  // ---- 9. Estado: cambios pedidos por las pantallas o por los módulos ---------------------------------------------
  function ponerEstado(cambios, opciones) {
    const origen = opciones && opciones.origen;
    let hubo = false;
    Object.keys(cambios || {}).forEach(function (k) {
      const v = cambios[k] === undefined || cambios[k] === null ? null : String(cambios[k]);
      if (v !== null && VALIDOS[k] && VALIDOS[k](v) && estado[k] !== v) { estado[k] = v; hubo = true; }
    });
    if (!hubo) return false;
    escribirHash();
    sincronizarInterruptor();
    const def = registro[activa];
    const inst = instancias[activa];
    if (def && inst && inst.pintada) pintar(inst, def, POR_ID[activa]);
    avisarDia(origen);
    return true;
  }
  function irA(pantalla, parametros) {
    if (!POR_ID[pantalla]) { console.warn('Sobusa Despacho: irA(«' + pantalla + '») no es una pantalla'); return; }
    Object.keys(parametros || {}).forEach(function (k) { const v = String(parametros[k]); if (VALIDOS[k] && VALIDOS[k](v)) estado[k] = v; });
    irArriba = true;
    const nuevo = hashDe(pantalla);
    if (location.hash === nuevo) abrir(pantalla); else location.hash = nuevo;
  }

  // ---- 10. Módulos embebidos (iframes de las páginas existentes) ---------------------------------------------------
  function hashModulo(m) {
    return typeof m.hash === 'function' ? (m.hash(estadoLectura()) || '') : (m.hash || '');
  }
  function crearModulo(id, m) {
    const meta = POR_ID[id] || {};
    const nombre = m.nombre || meta.nombre || id;
    const hash = hashModulo(m);
    const src = m.pagina + (m.pagina.indexOf('?') >= 0 ? '&' : '?') + 'embebido=1' + (hash ? '#' + hash : '');
    const aparte = m.pagina + (hash ? '#' + hash : '');
    const el = doc.createElement('section');
    el.className = 'modulo modulo--dormido';
    el.dataset.modulo = id;
    el.setAttribute('aria-label', nombre);
    el.innerHTML = '<div class="modulo__barra"><span class="modulo__nombre">' + icono(m.icono || meta.icono || 'panel') + esc(nombre) + '</span>' +
      '<span class="modulo__estado"><span data-estado aria-live="polite">Cargando…</span>' +
      '<a class="boton boton--secundario boton--pequeno boton--icono con-tooltip" href="' + esc(aparte) + '" target="_blank" rel="noopener" aria-label="Abrir aparte" data-aparte>' + icono('externo') + '<span class="tooltip tooltip--der">Abrir aparte</span></a></span></div>' +
      '<iframe class="modulo__marco" title="' + esc(nombre) + '" src="' + esc(src) + '"></iframe>' +
      '<div class="modulo__cargando"><span class="estado-carga"><span class="giro" aria-hidden="true"></span>Cargando ' + esc(nombre) + '…</span></div>';
    doc.getElementById('contenido').appendChild(el);
    const mod = { id: id, elemento: el, iframe: el.querySelector('iframe'), listo: false, cargado: false, pagina: m.pagina };
    mod.iframe.addEventListener('load', function () {
      mod.cargado = true;
      if (!mod.listo) { estadoModulo(mod, 'Cargado'); el.querySelector('.modulo__cargando').hidden = true; }
      enviar(id, { tipo: 'tema', tema: 'light' });   // solo modo claro
    });
    modulos[id] = mod;
    return mod;
  }
  // En los módulos a pantalla completa, «Abrir aparte» vive en la cabecera, con el mismo enlace que el del módulo.
  function sincronizarAparte() {
    const boton = doc.getElementById('cab-aparte');
    if (!boton) return;
    const m = moduloDe(activa), mod = modulos[activa];
    const origen = m && m.completo && mod ? mod.elemento.querySelector('[data-aparte]') : null;
    boton.hidden = !origen;
    if (origen) boton.setAttribute('href', origen.getAttribute('href'));
  }
  function estadoModulo(mod, texto) { const s = mod.elemento.querySelector('[data-estado]'); if (s) s.textContent = texto; }
  function despertarModulo(id, m) {
    const mod = modulos[id] || crearModulo(id, m);
    mod.elemento.classList.remove('modulo--dormido');
  }
  function enviar(id, msg) {
    const mod = modulos[id];
    if (!mod || !mod.cargado) return false;
    try { mod.iframe.contentWindow.postMessage(msg, '*'); return true; } catch (e) { return false; }
  }
  function enviarATodos(msg, salvo) { Object.keys(modulos).forEach(function (k) { if (k !== salvo) enviar(k, msg); }); }
  function pantallaDePagina(pagina) {
    if (!pagina) return null;
    const base = String(pagina).split(/[?#]/)[0].split('/').pop();
    return PANTALLAS.map(function (p) { return p.id; }).filter(function (k) { const m = moduloDe(k); return m && m.pagina.split(/[?#]/)[0].split('/').pop() === base; })[0] || null;
  }
  function irAHashModulo(id, hash) {
    const mod = modulos[id];
    if (!mod) return false;
    const base = mod.iframe.getAttribute('src').split('#')[0];
    mod.iframe.src = base + (hash ? '#' + hash : '');   // navegación de fragmento: no recarga el documento
    const aparte = mod.elemento.querySelector('[data-aparte]');
    if (aparte) aparte.href = mod.pagina + (hash ? '#' + hash : '');
    if (id === activa) sincronizarAparte();
    return true;
  }
  global.addEventListener('message', function (e) {
    const id = Object.keys(modulos).filter(function (k) { return modulos[k].iframe.contentWindow === e.source; })[0];
    if (!id || !e.data || typeof e.data !== 'object') return;
    const msg = e.data;
    const mod = modulos[id];
    if (msg.tipo === 'listo') {
      mod.listo = true; mod.cargado = true;
      estadoModulo(mod, 'Listo');
      mod.elemento.querySelector('.modulo__cargando').hidden = true;
      enviar(id, { tipo: 'tema', tema: 'light' });   // solo modo claro
    } else if (msg.tipo === 'estado') {
      const c = {};
      if (msg.dia) c.dia = msg.dia;
      if (msg.hora) c.hora = msg.hora;
      ponerEstado(c, { origen: id });
    } else if (msg.tipo === 'navegar') {
      const destino = msg.pantalla || pantallaDePagina(msg.pagina);
      if (!destino) return;
      const p = Object.assign({}, msg.parametros || {});
      if (typeof msg.hash === 'string') new URLSearchParams(msg.hash.replace(/^#/, '')).forEach(function (v, k) { p[k] = v; });
      ['dia', 'hora', 'ruta', 'escenario', 'modelo'].forEach(function (k) { if (msg[k] !== undefined && p[k] === undefined) p[k] = msg[k]; });
      irA(destino, p);
    }
  });

  // ---- 12. Registro único ------------------------------------------------------------------------------------------------
  // Una sola puerta: registrarPantalla(def). Las pantallas que cargan antes que app.js dejan su definición en
  // window.__pantallasRegistradas (app.html define en <head> un registrarPantalla de espera que la llena). Al cargar
  // app.js se recoge esa cola y se cambia por un objeto cuyo push registra en el acto: el orden de carga no importa.
  const COLAS = ['__pantallasRegistradas'];
  function registrarPantalla(def) {
    if (!def || !def.id || typeof def.render !== 'function') { console.warn('Sobusa Despacho: registrarPantalla recibió una definición incompleta', def); return; }
    if (!POR_ID[def.id]) console.warn('Sobusa Despacho: la pantalla «' + def.id + '» no está en la lista de app.js y no saldrá en la barra.');
    if (registro[def.id] === def) return;
    registro[def.id] = def;
    if (activa === def.id && datos) abrir(def.id);   // llegó tarde y es la que se ve: se pinta ya
  }
  function recogerColas() {
    COLAS.forEach(function (nombre) {
      const cola = global[nombre];
      if (Array.isArray(cola)) cola.splice(0).forEach(registrarPantalla);
      global[nombre] = { push: function () { Array.prototype.forEach.call(arguments, registrarPantalla); return 0; }, length: 0 };
    });
  }
  global.registrarPantalla = registrarPantalla;
  recogerColas();

  // ---- 13. Arranque ------------------------------------------------------------------------------------------------------
  function iniciar() {
    pintarBarra();
    const app = doc.getElementById('app');
    COMPONENTES.lateral(app);
    titulosBarra();
    iniciarHoja();
    vigilarCabecera();
    const alCambiarEscenario = function (v, input) {
      ponerEstado({ escenario: v });
      const et = input && input.parentNode.querySelector('[data-etiqueta]');
      anunciar('Escenario: ' + (et ? et.textContent : v));
    };
    COMPONENTES.segmentado(doc.getElementById('escenario'), alCambiarEscenario);
    COMPONENTES.segmentado(doc.getElementById('escenario-compacto'), alCambiarEscenario);
    // V14: un clic en cualquier enlace interno abre la pantalla arriba; Atrás y Adelante devuelven el punto de lectura.
    doc.addEventListener('click', function (e) { const a = e.target.closest && e.target.closest('a[href^="#"]'); if (a) irArriba = true; }, true);
    // «Saltar al contenido» no es una pantalla: lleva el foco al título sin tocar el hash.
    doc.getElementById('saltar').addEventListener('click', function (e) { e.preventDefault(); enfocarTitulo(); });
    // Pulsar en la barra la pantalla ya abierta: arriba y al título (el hash no cambia, así que no habría hashchange).
    doc.getElementById('nav-pantallas').addEventListener('click', function (e) {
      const a = e.target.closest('a.lateral__enlace');
      if (a && a.dataset.pantalla === activa && location.hash === hashDe(activa)) { e.preventDefault(); global.scrollTo(0, 0); enfocarTitulo(); }
    });
    global.addEventListener('hashchange', enrutar);
    cargarDatos(function (d) {
      datos = d;
      avisoSinDatos();
      if (!location.hash) { try { history.replaceState(null, '', '#inicio'); } catch (e) { /* sin historial */ } }
      enrutar();
      global.__appLista = true;
    });
  }

  global.app = {
    get estado() { return estadoLectura(); },
    get datos() { return datos; },
    pantallas: PANTALLAS,
    registrar: registrarPantalla,
    ponerEstado: ponerEstado,
    irA: irA,
    cifra: cifra,
    normalizarCifra: normalizarCifra,
    popoverFuente: popoverFuente,
    popoverFuentes: popoverFuentes,
    botonFuente: botonFuente,
    chipVerificado: chipVerificado,
    activarFuentes: activarFuentes,
    sinDatos: function () { return !!(datos && datos.sinDatos); },
    modulo: function (id) { const m = modulos[id]; return m ? { iframe: m.iframe, elemento: m.elemento, listo: m.listo, enviar: function (msg) { return enviar(id, msg); }, irA: function (hash) { return irAHashModulo(id, hash); } } : null; },
  };

  if (doc.readyState === 'loading') doc.addEventListener('DOMContentLoaded', iniciar); else iniciar();
})(window);
