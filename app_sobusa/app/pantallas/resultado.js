// Sobusa Despacho · pantallas/resultado.js
// Pantalla «Resultado · ¿Qué gana Sobusa?». Sigue el contrato de app/DISEÑO.md §5 (registrarPantalla con render,
// actualizar y salir) y el wireframe de §7. Ninguna cifra está escrita aquí: todas salen de window.DATOS_APP
// (app/datos_app.js, generado por app/generar_datos_app.py) y cada una lleva su botón «fuente».
//
// Ids que lee (contrato del inventario de cifras de la app): resultado_linea_base_2025, resultado_d5_reoptimizado,
// resultado_simulacion_plan_a, resultado_simulacion_plan_b, resultado_por_tipo_dia, resultado_por_mes (id nuevo,
// barras por mes del saldo), resultado_sensibilidad_beta, resultado_beta_equilibrio, resultado_tornado_d5,
// resultado_costos_unitarios_2026, resultado_ahorros_por_escenario, resultado_costo_conductor,
// resultado_conductores_2025, resultado_verificaciones_costos, resultado_demanda_dia_d5, resultado_e7_netos_supuestos;
// y de otras pantallas: inicio_error_regla_manual, inicio_error_modelo_final, inicio_error_hibrido, inicio_salidas_dia_hoy,
// inicio_buses_hora_hoy, inicio_espera_hoy, inicio_sobrecapacidad_hoy, inicio_beta, inicio_beta_rango, inicio_beta_origen,
// inicio_beta_equilibrio_d5, despacho_decision_vs_oraculo_h7 (o inicio_backtest_plan_vs_oraculo) y ciudad_2025_saldo
// (o inicio_persona_a_persona_saldo). Si un id falta, la pantalla lo dice en un aviso y pinta «—» en su lugar.
//
// Interruptor: Hoy (oferta real de 2025 y línea base a precios de 2026) / Con el modelo (plan que reasigna; un segmentado
// secundario muestra el plan que recorta) / Oráculo. No existe una corrida del oráculo con costos con fuente para el año
// completo: con «Oráculo» las fichas cambian de base y muestran los días del backtest (despacho_decision_vs_oraculo_h7),
// con su rótulo y comparadas con lo que Sobusa hizo esos mismos días; nunca se mezclan las dos bases en una ficha.
// Cada cifra lleva su botón «fuente»; cuando la cifra es una parte del valor, la clave exacta sale de su «origen».
(function (global) {
  'use strict';

  const ID = 'resultado';
  // Años del estudio (como en modelo.js): el texto no los escribe sueltos.
  const ANIO = '2025', ANIO_SIGUE = '2026';
  const F = global.COMPONENTES.formato;
  const icono = function (nombre, clase) { return global.ICONOS.svg(nombre, clase); };
  const MESES = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic'];
  const PLAN_NOMBRE = { b: 'Reasigna (b)', a: 'Recorta (a)' };

  // ---- Estado de la pantalla -----------------------------------------------------------------------------------
  let D = null;                 // window.DATOS_APP
  let cont = null;              // div.pantalla que nos da la app
  let escenario = 'hoy';        // 'hoy' | 'modelo' | 'oraculo'
  let plan = 'b';               // plan mostrado en «Con el modelo»: 'b' reasigna (la propuesta) | 'a' recorta
  let graficos = {};            // clave → instancia de ECharts
  let limpiezas = [];           // funciones que deshacen observadores y temporizadores
  let faltantes = [];           // ids que no están en DATOS_APP
  let archivosUsados = {};      // archivo → verificado (para la sección «Fuentes»)
  let nPop = 0;
  let fichas = [];              // fichas de cifra gobernadas por el interruptor

  // ---- Formato -------------------------------------------------------------------------------------------------
  const n = function (v, d) { return F.numero(v, d); };
  const s = function (v, d, u) { return F.signo(v, d, u); };
  function pct(nuevo, base) { return base ? (nuevo - base) / base * 100 : 0; }
  function esc(t) { return String(t === null || t === undefined ? '' : t).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
  function num(v) { return typeof v === 'number' && !isNaN(v); }

  // ---- Acceso a los datos (tolerante con la forma del inventario y con la de la muestra) ------------------------
  function entrada(id) {
    const p = D && D.pantallas;
    if (!p) return null;
    if (p[ID] && p[ID][id]) return p[ID][id];
    for (const k in p) if (p[k] && p[k][id]) return p[k][id];
    return null;
  }
  function anotarFaltante(id) { if (faltantes.indexOf(id) < 0) faltantes.push(id); }
  function valor(id, ruta, porDefecto) {
    const e = entrada(id);
    if (!e) { anotarFaltante(id); return porDefecto; }
    let v = e.valor !== undefined ? e.valor : e.valor_actual;
    if (ruta) {
      const partes = ruta.split('.');
      for (let i = 0; i < partes.length; i++) { if (v === null || v === undefined) return porDefecto; v = v[partes[i]]; }
    }
    return v === undefined || v === null ? porDefecto : v;
  }
  // El primer valor numérico de una lista de [id, ruta]; devuelve {v, id, ruta}.
  function primero(lista) {
    for (let i = 0; i < lista.length; i++) {
      const e = entrada(lista[i][0]);
      if (!e) continue;
      const v = valor(lista[i][0], lista[i][1], null);
      if (num(v)) return { v: v, id: lista[i][0], ruta: lista[i][1] };
    }
    anotarFaltante(lista[0][0]);
    return { v: null, id: lista[0][0], ruta: lista[0][1] };
  }
  function fuenteDe(id, extra) {
    const e = entrada(id) || {};
    const conf = e.confianza || {};
    return Object.assign({
      archivo: e.archivo || '—',
      clave: e.clave || '—',
      experimento: e.experimento || '—',
      verificado: e.verificado || conf.verificado_independiente || 'no',
      revision: e.revision || conf.donde || '',
      nota: e.nota || '',
    }, extra || {});
  }
  // Un campo de la cifra fuera de «valor» (p. ej. n_dias, dias, por_grupo).
  function extraDe(id, campo) { const e = entrada(id); return e && e[campo] !== undefined ? e[campo] : null; }
  // Referencia exacta (archivo y clave) de una parte de la cifra, tomada de su «origen»: [[ruta], {a, c, x}].
  function refDe(id, ruta) {
    const e = entrada(id);
    if (!e || !Array.isArray(e.origen) || ruta === null || ruta === undefined) return null;
    const partes = (Array.isArray(ruta) ? ruta : String(ruta).split('.')).map(String);
    const conValor = ['valor'].concat(partes);
    const igual = function (r, p) { return r.length === p.length && p.every(function (x, i) { return String(r[i]) === x; }); };
    const empieza = function (r, p) { return r.length >= p.length && p.every(function (x, i) { return String(r[i]) === x; }); };
    let ref = null;
    e.origen.forEach(function (o) { if (!ref && Array.isArray(o) && Array.isArray(o[0]) && (igual(o[0], conValor) || igual(o[0], partes))) ref = o[1]; });
    if (!ref) e.origen.forEach(function (o) { if (!ref && Array.isArray(o) && Array.isArray(o[0]) && (empieza(o[0], conValor) || empieza(o[0], partes))) ref = o[1]; });
    if (!ref) return null;
    if (typeof ref === 'string') return { clave: ref };
    return { archivo: ref.a, clave: (ref.c || JSON.stringify(ref)) + (ref.x !== undefined && ref.x !== 1 ? ' (× ' + ref.x + ')' : '') };
  }
  // Popover de una parte de la cifra: archivo y clave exactos si «origen» los trae; si no, la clave de la cifra y la ruta.
  function popRuta(id, ruta, titulo, extra) {
    const base = fuenteDe(id);
    const r = refDe(id, ruta);
    const sitio = r ? { archivo: r.archivo || base.archivo, clave: r.clave } : (ruta ? { clave: base.clave + ' → ' + (Array.isArray(ruta) ? ruta.join(' → ') : ruta) } : {});
    const m = marcaCampo(id, ruta);
    if (m) sitio.verificado = m;
    return popover(fuenteDe(id, Object.assign(sitio, extra || {})), titulo);
  }
  // Marca de revisión de una parte de la cifra cuando la cifra la trae por columna (verificado_campos):
  // {plan: {campo: marca}} o {grupo: marca}. Sin eso, la marca es la de la cifra entera.
  function marcaCampo(id, ruta) {
    const vc = extraDe(id, 'verificado_campos');
    if (!vc || ruta === null || ruta === undefined) return null;
    const partes = Array.isArray(ruta) ? ruta.map(String) : String(ruta).split('.');
    const g = vc[partes[0]];
    if (typeof g === 'string') return g;
    return g && partes.length > 1 && typeof g[partes[1]] === 'string' ? g[partes[1]] : null;
  }

  // ---- Fuente: popover y botón ---------------------------------------------------------------------------------
  function claseVerificado(v) { v = String(v || '').toLowerCase(); return v === 'sí' || v === 'si' ? 'bien' : v === 'parcial' ? 'atencion' : 'critico'; }
  function chipVerificado(v, corto) {
    const c = claseVerificado(v);
    const texto = c === 'bien' ? 'Verificado: sí' : c === 'atencion' ? 'Verificado: parcial' : 'Sin revisor independiente';
    return '<span class="chip chip--' + c + '">' + icono(c === 'bien' ? 'bien' : 'alerta') + (corto ? (c === 'bien' ? 'sí' : c === 'atencion' ? 'parcial' : 'no') : texto) + '</span>';
  }
  function popover(f, titulo) {
    nPop += 1;
    const id = 'res-f-' + nPop;
    const caja = cont.querySelector('#res-popovers');
    const div = document.createElement('div');
    div.id = id; div.className = 'fuente-pop'; div.setAttribute('popover', '');
    div.innerHTML = '<div class="fuente-pop__cab"><span class="fuente-pop__titulo">' + icono('fuente') + 'Fuente' + (titulo ? ' · ' + esc(titulo) : '') + '</span>' +
      '<button class="boton boton--fantasma boton--icono boton--pequeno" type="button" data-cerrar aria-label="Cerrar">' + icono('cerrar') + '</button></div>' +
      '<dl class="fuente-pop__datos"><dt>Archivo</dt><dd><code>' + esc(f.archivo) + '</code></dd><dt>Clave</dt><dd>' + esc(f.clave) + '</dd>' +
      '<dt>Experimento</dt><dd>' + esc(f.experimento) + '</dd><dt>Revisor</dt><dd>' + chipVerificado(f.verificado, true) + (f.revision ? ' <span class="texto-2">' + esc(f.revision) + '</span>' : '') + '</dd>' +
      (f.nota ? '<dt>Nota</dt><dd>' + esc(f.nota) + '</dd>' : '') + '</dl>' +
      '<div class="fuente-pop__pie">Ninguna cifra está escrita a mano: app/verificar_datos_app.py compara este valor con el archivo.</div>';
    caja.appendChild(div);
    String(f.archivo || '').split(/ y |; /).forEach(function (a) { a = a.trim(); if (a && a !== '—' && !archivosUsados[a]) archivosUsados[a] = f.verificado; });
    return id;
  }
  function botonFuente(popId, texto) {
    if (texto) return '<button class="fuente fuente--texto" type="button" popovertarget="' + popId + '" aria-expanded="false">' + icono('fuente') + esc(texto) + '</button>';
    return '<button class="fuente" type="button" popovertarget="' + popId + '" aria-expanded="false" aria-label="Fuente de la cifra">' + icono('fuente') + '</button>';
  }
  function popoverId(id, titulo, extra) { return popover(fuenteDe(id, extra), titulo); }

  // ---- Piezas de HTML -------------------------------------------------------------------------------------------
  function seccion(id, titulo, intro, cuerpo, extraCab) {
    return '<section class="seccion" id="' + id + '"><div class="seccion__cab"><h2 class="seccion__titulo">' + titulo + '</h2>' + (extraCab || '') + '</div>' +
      (intro ? '<p class="seccion__intro">' + intro + '</p>' : '') + '<div class="seccion__cuerpo">' + cuerpo + '</div></section>';
  }
  function aviso(tipo, titulo, cuerpo) {
    const ic = tipo === 'canje' ? 'canje' : tipo === 'bien' ? 'bien' : tipo === 'nota' ? 'info' : 'alerta';
    return '<div class="aviso' + (tipo && tipo !== 'nota' ? ' aviso--' + tipo : '') + '">' + icono(ic) + '<div class="aviso__cuerpo"><h3 class="aviso__titulo">' + titulo + '</h3>' + cuerpo + '</div></div>';
  }
  function cifraLlana(etiqueta, valorHtml, unidad, variacion, nota, popId) {
    return '<article class="cifra cifra--llana"><header class="cifra__cab"><h3 class="cifra__etiqueta">' + etiqueta + '</h3>' + (popId ? botonFuente(popId) : '') + '</header>' +
      '<p class="cifra__valor"><span class="num">' + valorHtml + '</span>' + (unidad ? '<span class="cifra__unidad">' + unidad + '</span>' : '') + '</p>' +
      (variacion ? '<p class="cifra__variacion' + (variacion.clase ? ' ' + variacion.clase : '') + '">' + variacion.html + '</p>' : '') +
      (nota ? '<p class="cifra__nota">' + nota + '</p>' : '') + '</article>';
  }
  // Tabla de datos: la primera columna (y las de opciones.textoEn) son texto; las demás, números alineados a la derecha.
  // opciones.sinMarco devuelve solo la <table> (para la tabla gemela de un gráfico, que ya tiene su marco).
  function tabla(caption, cabeceras, filas, opciones) {
    opciones = opciones || {};
    const esTexto = function (i) { return i === 0 || (opciones.textoEn && opciones.textoEn.indexOf(i) >= 0); };
    let h = (opciones.sinMarco ? '' : '<div class="tabla-marco">') + '<table class="tabla' + (opciones.compacta ? ' tabla--compacta' : '') + '">';
    if (caption) h += '<caption>' + caption + '</caption>';
    h += '<thead><tr>' + cabeceras.map(function (c, i) { return '<th scope="col"' + (esTexto(i) ? '' : ' class="num"') + '>' + c + '</th>'; }).join('') + '</tr></thead><tbody>';
    filas.forEach(function (fila) {
      h += '<tr' + (fila.clase ? ' class="' + fila.clase + '"' : '') + '>' + fila.celdas.map(function (c, i) { return '<td' + (esTexto(i) ? '' : ' class="num"') + '>' + c + '</td>'; }).join('') + '</tr>';
    });
    return h + '</tbody></table>' + (opciones.sinMarco ? '' : '</div>');
  }
  // Popover de una cifra encontrada con primero(): añade la ruta dentro del archivo a la clave del inventario.
  function popDe(x, titulo) { return popRuta(x.id, x.ruta, titulo); }
  function betaCentral() { return primero([['inicio_beta'], ['resultado_costos_unitarios_2026', 'beta']]).v; }
  function figura(id, titulo, sub, lienzoHtml, tablaHtml, pieHtml, leyenda, ariaLabel) {
    return '<figure class="grafico" id="' + id + '"><figcaption class="grafico__cab"><div class="grafico__titulos"><h3 class="grafico__titulo">' + titulo + '</h3>' +
      (sub ? '<p class="grafico__sub">' + sub + '</p>' : '') + '</div><div class="grafico__acciones">' +
      '<button class="boton boton--secundario boton--pequeno" type="button" data-tabla-gemela aria-controls="' + id + '-tabla">' + icono('tabla') + '<span data-texto>Ver tabla</span></button></div></figcaption>' +
      (leyenda ? '<ul class="leyenda">' + leyenda + '</ul>' : '') +
      '<div class="grafico__lienzo' + (lienzoHtml ? ' resultado__facetas' : '') + '" id="' + id + '-lienzo" role="img" aria-label="' + esc(ariaLabel || titulo) + '">' + (lienzoHtml || '') + '</div>' +
      '<div class="grafico__tabla tabla-marco" id="' + id + '-tabla" hidden>' + tablaHtml + '</div>' +
      '<div class="grafico__pie">' + (pieHtml || '') + '</div></figure>';
  }
  // Leyenda en HTML. Con estatico = true es solo informativa (un gráfico de una sola serie con colores por barra).
  function itemLeyenda(nombre, clase, estilo, estatico) {
    const muestra = '<span class="leyenda__muestra ' + (clase || '') + '" style="' + (estilo || '') + '"></span>' + esc(nombre);
    if (estatico) return '<li><span class="leyenda__item">' + muestra + '</span></li>';
    return '<li><button class="leyenda__item" type="button" data-serie="' + esc(nombre) + '" aria-pressed="true">' + muestra + '</button></li>';
  }
  // Liga la leyenda una sola vez y, cada vez que el gráfico se vuelve a crear, le aplica lo que el usuario había apagado.
  function ligarLeyenda(ul, obtener) {
    if (!ul) return;
    if (!ul._ligada) { ul._ligada = true; global.COMPONENTES.leyenda(ul, obtener); }
    const g = obtener();
    if (g) ul.querySelectorAll('.leyenda__item[aria-pressed="false"]').forEach(function (b) { g.dispatchAction({ type: 'legendUnSelect', name: b.dataset.serie }); });
  }
  function faceta(clave, titulo) { return '<div class="resultado__faceta"><span class="resultado__faceta-titulo">' + titulo + '</span><div class="resultado__faceta-lienzo" data-faceta="' + clave + '"></div></div>'; }

  // ---- Estilos propios de la pantalla (solo tokens) --------------------------------------------------------------
  function estilos() {
    if (document.getElementById('estilos-resultado')) return;
    const st = document.createElement('style');
    st.id = 'estilos-resultado';
    st.textContent = [
      '.grafico__lienzo.resultado__facetas { height: auto; display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: var(--e-3) var(--e-4); }',
      '.grafico__lienzo.resultado__facetas[hidden] { display: none; }',
      '.resultado__faceta { display: grid; gap: 2px; min-width: 0; }',
      '.resultado__faceta-titulo { font-size: var(--t-xs); font-weight: var(--peso-medio); color: var(--tinta-2); }',
      '.resultado__faceta-lienzo { height: 132px; min-width: 0; }',
      '.resultado__muestra--hueca { background: var(--superficie-2); border: 1.5px solid var(--serie-modelo); box-sizing: border-box; }',
      '.resultado__muestra--oraculo { background: transparent; border: 1.5px dashed var(--serie-oraculo); box-sizing: border-box; }',
      '.resultado__muestra--rayas { background: repeating-linear-gradient(135deg, var(--serie-modelo) 0 2px, var(--superficie) 2px 5px); }',
      '.resultado__comparacion { display: grid; gap: var(--e-3); }',
      '.resultado__comparacion .tabla__fila-propuesta td { font-weight: var(--peso-fuerte); }',
      '.resultado__propuesta td { background: var(--acento-suave); }',
      '#res-corridas .tabla td:first-child { min-width: 13em; max-width: 19em; }',
      '.resultado__propuesta td:first-child { color: var(--acento-sobre-suave, var(--acento)); font-weight: var(--peso-fuerte); }',
      '.resultado__modulo { height: clamp(520px, 78vh, 900px); }',
      '.resultado__modulo-cuerpo { position: relative; flex: 1 1 auto; min-height: 0; display: flex; }',
      '.resultado__modulo-cuerpo .modulo__marco { height: 100%; }',
      '.resultado__lista { margin: 0; padding-left: 20px; display: grid; gap: var(--e-2); max-width: var(--ancho-texto); color: var(--tinta-2); font-size: var(--t-s); }',
      '.resultado__lista strong { color: var(--tinta); }',
      '.resultado__fila { display: grid; gap: var(--e-3); }',
      '.resultado__fila-cifras { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: var(--e-3); }',
      '.resultado__fuentes { margin: 0; padding: 0; list-style: none; display: grid; gap: var(--e-2); font-size: var(--t-s); }',
      '.resultado__fuentes li { display: flex; flex-wrap: wrap; align-items: center; gap: var(--e-2); }',
      '.resultado__enlace { display: inline-flex; align-items: center; gap: 4px; }',
      '.cifra__base { margin: 0; font-size: var(--t-s); color: var(--tinta-3); letter-spacing: 0; text-transform: none; }',
      '.resultado__que { display: grid; grid-template-columns: minmax(0, 14em) minmax(0, 1fr); gap: var(--e-2) var(--e-4); margin: 0; font-size: var(--t-s); }',
      '.resultado__que dt { color: var(--tinta-2); } .resultado__que dd { margin: 0; }',
      '@media (max-width: 600px) { .resultado__que { grid-template-columns: minmax(0, 1fr); } .resultado__que dd { margin-bottom: var(--e-2); } }',
      '.resultado__base { margin: 0; font-size: var(--t-s); line-height: 1.6; color: var(--tinta-2); max-width: var(--ancho-texto); text-wrap: pretty; }',
      '.resultado__base .chip { margin-left: var(--e-1); vertical-align: middle; }',
      '#res-popovers { display: contents; }',
      '#res-cuerpo { gap: var(--e-7); }',
      '#res-cuerpo .cifra__variacion { display: block; line-height: 1.5; text-wrap: pretty; }',
      '#res-cuerpo .cifra__variacion > .icono:first-child { display: inline-block; vertical-align: -2px; margin-right: 4px; }',
      '#res-cuerpo .cifra__variacion .fuente, .resultado__base .fuente, .resultado__bases .fuente { vertical-align: middle; }',
      '@media (min-width: 900px) { #res-fichas { grid-template-columns: repeat(3, minmax(0, 1fr)); } }',
      // Etiqueta y cifra arriba, la variación al pie: en cada fila las cifras quedan a la misma altura y las notas alineadas abajo.
      '#res-fichas .cifra { grid-template-rows: auto auto 1fr; align-content: stretch; }',
      '#res-fichas .cifra__variacion { align-self: end; }',
      '.resultado__bases { margin: 0; padding-left: 20px; display: grid; gap: var(--e-2); font-size: var(--t-s); color: var(--tinta-2); }',
    ].join('\n');
    document.head.appendChild(st);
  }

  // ---- Backtest: hoy, plan semanal, motor y oráculo en los días del backtest --------------------------------------
  const ID_BT = 'despacho_decision_vs_oraculo_h7';
  function datosBacktest() {
    const v = valor(ID_BT, null, null);
    const res = { id: ID_BT, k: {}, dias: null, horasDesde: null };
    if (!v || typeof v !== 'object') return res;
    const buscar = function (parte) { return Object.keys(v).filter(function (x) { return x.toLowerCase().indexOf(parte) >= 0; })[0] || null; };
    res.k = { plan: buscar('plan semanal'), real: buscar('oferta real'), motor: buscar('con nowcast'), orac: buscar('oráculo') || buscar('oraculo') };
    Object.keys(res.k).forEach(function (q) { res[q] = res.k[q] ? v[res.k[q]] : null; });
    res.dias = res.plan && num(res.plan.dias) ? res.plan.dias : null;
    const grupos = extraDe(ID_BT, 'por_grupo');
    const g = Array.isArray(grupos) ? grupos.filter(function (x) { return x && num(x.horas_desde); })[0] : null;
    res.horasDesde = g ? g.horas_desde : null;
    return res;
  }
  function cifraBt(bt, quien, campo) {
    const x = bt[quien];
    return { v: x && num(x[campo]) ? x[campo] : null, id: bt.id, ruta: bt.k[quien] ? [bt.k[quien], campo] : null };
  }
  // Textos de base (sin números escritos: los días salen de los datos).
  function textoBaseAnual() {
    const d = extraDe('resultado_demanda_dia_d5', 'n_dias');
    return 'Base: promedio por día de ' + (num(d) ? 'los ' + n(d, 0) + ' días de ' : '') + ANIO + ', tres rutas, viajes válidos (contabilidad de D5).';
  }
  function textoBaseBacktest(bt) {
    return 'Base: ' + (num(bt.dias) ? 'los ' + n(bt.dias, 0) + ' días' : 'los días') + ' del backtest de ' + ANIO + (num(bt.horasDesde) ? ', desde las ' + n(bt.horasDesde, 0) + ' h' : '') +
      ', cuando decide la consola. Es otra base: no se compara con las cifras del año.';
  }

  // ---- Las seis fichas que gobierna el interruptor -------------------------------------------------------------
  function rutaPlan(p, campo) { return (p === 'b' ? 'b_D5_reoptimizado_e05' : 'a_D5_original') + '.' + campo; }
  function definirFichas() {
    const bt = datosBacktest();
    const lineaBase = primero([['resultado_linea_base_2025', 'costo_total_Mcop']]);
    const ahorroB = primero([['resultado_d5_reoptimizado', rutaPlan('b', 'ahorro_operativo_Mcop')], ['resultado_simulacion_plan_b', 'ahorro_por_km_Mcop']]);
    const ahorroA = primero([['resultado_d5_reoptimizado', rutaPlan('a', 'ahorro_operativo_Mcop')]]);
    const fichasDef = [
      { clave: 'salidas', etiqueta: 'Salidas válidas por día', unidad: 'salidas/día', dec: 0, mejorSiBaja: null,
        nota: 'El plan que reasigna quita salidas en los valles y las pone en los picos y en CL 72.',
        hoy: primero([['inicio_salidas_dia_hoy'], ['resultado_simulacion_plan_b', 'salidas_dia_real']]),
        b: primero([['resultado_d5_reoptimizado', rutaPlan('b', 'salidas_dia')], ['resultado_simulacion_plan_b', 'salidas_dia_plan']]),
        a: primero([['resultado_d5_reoptimizado', rutaPlan('a', 'salidas_dia')], ['resultado_simulacion_plan_a', 'salidas_dia_plan']]),
        etiquetaO: 'Salidas por día', notaO: 'El oráculo decide con la demanda que de verdad llegó: nadie puede hacerlo mejor.',
        orac: cifraBt(bt, 'orac', 'salidas_dia'), hoyBt: cifraBt(bt, 'real', 'salidas_dia'), planBt: cifraBt(bt, 'plan', 'salidas_dia') },
      { clave: 'buses_hora', etiqueta: 'Buses-hora por día', unidad: 'buses-hora/día', dec: 0, mejorSiBaja: null,
        nota: 'Horas de bus en ruta por día. Con el plan que reasigna casi no cambian: el ahorro viene de los kilómetros y de las horas de los valles.',
        hoy: primero([['inicio_buses_hora_hoy'], ['resultado_simulacion_plan_b', 'buses_hora_real']]),
        b: primero([['resultado_d5_reoptimizado', rutaPlan('b', 'buses_hora_dia')], ['resultado_simulacion_plan_b', 'buses_hora_plan']]),
        a: primero([['resultado_d5_reoptimizado', rutaPlan('a', 'buses_hora_dia')], ['resultado_simulacion_plan_a', 'buses_hora_plan']]),
        notaO: 'Horas de bus en ruta por día en los días del backtest.',
        orac: cifraBt(bt, 'orac', 'buses_hora_dia'), hoyBt: cifraBt(bt, 'real', 'buses_hora_dia'), planBt: cifraBt(bt, 'plan', 'buses_hora_dia') },
      { clave: 'costo', etiqueta: 'Costo de operación del año', unidad: 'M COP/año', dec: 0, mejorSiBaja: true,
        nota: 'La operación de ' + ANIO + ' a precios de ' + ANIO_SIGUE + ' (combustible, mantenimiento, llantas, lubricantes, conductores y fijos). Con el plan: la línea base menos el ahorro evitable (km y conductor por hora).',
        hoy: lineaBase,
        b: { v: num(lineaBase.v) && num(ahorroB.v) ? lineaBase.v - ahorroB.v : null, id: 'resultado_d5_reoptimizado', derivada: true, ahorro: ahorroB },
        a: { v: num(lineaBase.v) && num(ahorroA.v) ? lineaBase.v - ahorroA.v : null, id: 'resultado_d5_reoptimizado', derivada: true, ahorro: ahorroA },
        etiquetaO: 'Costo generalizado por día', unidadO: 'M COP/día', decO: 1,
        notaO: 'Operación con los costos de fuente pública más la espera y la sobrecarga valoradas en plata (supuestos de D5), sin la elasticidad. No es el costo del año.',
        orac: cifraBt(bt, 'orac', 'costo_Mcop_dia'), hoyBt: cifraBt(bt, 'real', 'costo_Mcop_dia'), planBt: cifraBt(bt, 'plan', 'costo_Mcop_dia') },
      { clave: 'espera', etiqueta: 'Espera media en el paradero', unidad: 'min', dec: 1, mejorSiBaja: true,
        nota: 'Intervalo del punto medio con la irregularidad medida en D4. Misma fórmula para hoy y para los dos planes.',
        hoy: primero([['inicio_espera_hoy'], ['resultado_simulacion_plan_b', 'espera_real_min']]),
        b: primero([['resultado_d5_reoptimizado', rutaPlan('b', 'espera_min')], ['resultado_simulacion_plan_b', 'espera_plan_min']]),
        a: primero([['resultado_d5_reoptimizado', rutaPlan('a', 'espera_min')], ['resultado_simulacion_plan_a', 'espera_plan_min']]),
        notaO: 'El oráculo espera un poco más: ahorra salidas donde sobran puestos y las pone donde hay gente de pie.',
        orac: cifraBt(bt, 'orac', 'espera_min'), hoyBt: cifraBt(bt, 'real', 'espera_min'), planBt: cifraBt(bt, 'plan', 'espera_min') },
      { clave: 'sobrecap', etiqueta: 'Pasajeros por día por encima de la capacidad', unidad: 'pasajeros/día', dec: 0, mejorSiBaja: true,
        nota: 'Medidos en el tramo crítico de cada viaje. Menos pasajeros de pie en el pico: a eso se destinan las salidas que se mueven.',
        hoy: primero([['inicio_sobrecapacidad_hoy'], ['resultado_simulacion_plan_b', 'sobre_capacidad_real']]),
        b: primero([['resultado_d5_reoptimizado', rutaPlan('b', 'sobrecap_dia')], ['resultado_simulacion_plan_b', 'sobre_capacidad_plan']]),
        a: primero([['resultado_d5_reoptimizado', rutaPlan('a', 'sobrecap_dia')], ['resultado_simulacion_plan_a', 'sobre_capacidad_plan']]),
        notaO: 'En el tramo crítico de cada viaje, en las horas del backtest.',
        orac: cifraBt(bt, 'orac', 'sobrecap_dia'), hoyBt: cifraBt(bt, 'real', 'sobrecap_dia'), planBt: cifraBt(bt, 'plan', 'sobrecap_dia') },
      { clave: 'riesgo', etiqueta: 'Pasajeros en riesgo por día', unidad: 'pasajeros/día', dec: 0, mejorSiBaja: true,
        nota: 'Contabilidad conservadora: los pasajeros que se perderían donde el plan quita salidas (β de E7). Debajo, los netos si se cuentan también los ganados donde las añade.',
        hoy: { v: 0, id: 'resultado_d5_reoptimizado', cero: true },
        b: primero([['resultado_d5_reoptimizado', rutaPlan('b', 'pax_perdidos_dia')], ['resultado_simulacion_plan_b', 'pasajeros_en_riesgo_dia']]),
        a: primero([['resultado_d5_reoptimizado', rutaPlan('a', 'pax_perdidos_dia')], ['resultado_simulacion_plan_a', 'pasajeros_en_riesgo_dia']]),
        netos: { b: primero([['resultado_d5_reoptimizado', rutaPlan('b', 'pax_netos_simetrico_dia')], ['resultado_simulacion_plan_b', 'pasajeros_netos_simetrica_dia']]),
                 a: primero([['resultado_d5_reoptimizado', rutaPlan('a', 'pax_netos_simetrico_dia')], ['resultado_simulacion_plan_a', 'pasajeros_netos_simetrica_dia']]) },
        notaO: 'El backtest no cuenta pasajeros en riesgo: compara decisiones hora a hora, no pasajes.',
        orac: { v: null, id: bt.id, ruta: null, sinDato: true }, hoyBt: { v: null }, planBt: { v: null } },
    ];
    fichasDef.forEach(function (f) {
      f.pop = {};
      ['hoy', 'b', 'a', 'orac'].forEach(function (k) {
        const x = f[k];
        const titulo = { hoy: 'hoy', b: 'plan que reasigna (b)', a: 'plan que recorta (a)', orac: 'oráculo del backtest' }[k];
        if (x.derivada) {
          const fb = fuenteDe(lineaBase.id); const fa = fuenteDe(x.ahorro.id);
          const rb = refDe(lineaBase.id, lineaBase.ruta) || {}; const ra = refDe(x.ahorro.id, x.ahorro.ruta) || {};
          f.pop[k] = popover(fuenteDe(lineaBase.id, { archivo: fb.archivo + ' y ' + (ra.archivo || fa.archivo),
            clave: (rb.clave || 'costo_total_Mcop') + ' − ' + (ra.clave || x.ahorro.ruta) + ' (resta hecha en la pantalla: ' + n(lineaBase.v, 0) + ' − ' + n(x.ahorro.v, 0) + ')',
            experimento: fb.experimento + ' / ' + fa.experimento,
            verificado: claseVerificado(fa.verificado) === 'bien' && claseVerificado(fb.verificado) === 'bien' ? 'sí' : 'parcial' }), titulo);
        } else if (x.cero) {
          f.pop[k] = popover(fuenteDe(x.id, { clave: 'Hoy no hay plan que quite salidas: el riesgo es cero por definición (pax_perdidos_dia mide el riesgo de cada plan frente a la oferta real)' }), titulo);
        } else if (x.sinDato) {
          f.pop[k] = popover(fuenteDe(x.id, { clave: 'Sin columna de pasajeros en riesgo en el backtest', nota: '' }), titulo);
        } else {
          f.pop[k] = popRuta(x.id, x.ruta, titulo);
        }
      });
      if (f.netos) f.popNetos = { b: popDe(f.netos.b, 'pasajeros netos, plan (b)'), a: popDe(f.netos.a, 'pasajeros netos, plan (a)') };
      if (f.hoyBt && num(f.hoyBt.v)) f.popHoyBt = popRuta(f.hoyBt.id, f.hoyBt.ruta, 'hoy en los días del backtest');
      if (f.planBt && num(f.planBt.v)) f.popPlanBt = popRuta(f.planBt.id, f.planBt.ruta, 'plan semanal en los días del backtest');
    });
    fichasDef.bt = bt;
    return fichasDef;
  }
  function claveEscenario() { return escenario === 'hoy' ? 'hoy' : escenario === 'oraculo' ? 'orac' : plan; }
  function htmlFichas() {
    return '<div class="cifras" id="res-fichas">' + fichas.map(function (f) {
      return '<article class="cifra" data-ficha="' + f.clave + '"><header class="cifra__cab"><h3 class="cifra__etiqueta" data-etiqueta>' + f.etiqueta + '</h3>' +
        '<button class="fuente" type="button" popovertarget="' + f.pop.hoy + '" aria-expanded="false" aria-label="Fuente de la cifra" data-fuente-ficha>' + icono('fuente') + '</button></header>' +
        '<p class="cifra__valor"><span data-cifra="' + (num(f.hoy.v) ? f.hoy.v : '') + '" data-decimales="' + f.dec + '">' + (num(f.hoy.v) ? n(f.hoy.v, f.dec) : '—') + '</span><span class="cifra__unidad" data-unidad>' + f.unidad + '</span></p>' +
        '<p class="cifra__variacion" data-variacion></p></article>';
    }).join('') + '</div>' +
      '<details class="desplegable desplegable--llano" id="res-fichas-que"><summary class="desplegable__resumen">' + icono('chevron-derecha', 'icono desplegable__chevron') + 'Qué mide cada cifra</summary>' +
      '<div class="desplegable__cuerpo"><dl class="resultado__que" id="res-fichas-notas"></dl></div></details>';
  }
  function pintarFichas(animar) {
    const k = claveEscenario();
    const oraculo = k === 'orac';
    fichas.forEach(function (f) {
      const art = cont.querySelector('[data-ficha="' + f.clave + '"]');
      if (!art) return;
      const span = art.querySelector('[data-cifra]');
      const x = f[k];
      const dec = oraculo && f.decO !== undefined ? f.decO : f.dec;
      const unidad = oraculo && f.unidadO ? f.unidadO : f.unidad;
      art.querySelector('[data-etiqueta]').textContent = oraculo && f.etiquetaO ? f.etiquetaO : f.etiqueta;
      art.querySelector('[data-unidad]').textContent = unidad;

      // Al cambiar de base no se anima (no es el mismo número que cambia, es otra medida).
      const cambiaBase = (span.dataset.medida || 'anual') !== (oraculo ? 'bt' : 'anual');
      span.dataset.medida = oraculo ? 'bt' : 'anual';
      span.dataset.decimales = String(dec);
      if (num(x.v)) { if (animar && !cambiaBase) global.COMPONENTES.ponerCifra(span, x.v); else { span.dataset.cifra = String(x.v); span.textContent = n(x.v, dec); } }
      else { span.dataset.cifra = ''; span.textContent = '—'; }
      art.querySelector('[data-fuente-ficha]').setAttribute('popovertarget', f.pop[k]);
      const v = art.querySelector('[data-variacion]');
      art.classList.toggle('cifra--hoy', k === 'hoy');
      if (k === 'hoy') {
        v.className = 'cifra__variacion';
        // «Lo que Sobusa hace hoy» ya lo dice la línea de arriba de las fichas: aquí solo lo que es propio de la ficha.
        v.innerHTML = f.clave === 'riesgo' ? icono('igual') + 'Nadie queda en riesgo: no se quita ninguna salida' : f.clave === 'costo' ? icono('igual') + 'Línea base: la operación real de ' + ANIO + ' a precios de ' + ANIO_SIGUE : '';
        return;
      }
      if (oraculo) {
        if (!num(x.v) || !num(f.hoyBt.v)) { v.className = 'cifra__variacion'; v.innerHTML = icono('info') + 'No se mide en el backtest'; return; }
        const difO = x.v - f.hoyBt.v;
        const buenaO = f.mejorSiBaja === null ? null : (f.mejorSiBaja ? difO <= 0 : difO >= 0);
        v.className = 'cifra__variacion' + (buenaO === null ? '' : buenaO ? ' cifra__variacion--bien' : ' cifra__variacion--mal');
        v.innerHTML = icono(difO < 0 ? 'flecha-abajo' : difO > 0 ? 'flecha-arriba' : 'igual') + s(difO, dec) + ' frente a hoy en esos días (' + n(f.hoyBt.v, dec) + ' ' + botonFuente(f.popHoyBt) + ')' +
          (num(f.planBt.v) ? '; plan semanal: ' + n(f.planBt.v, dec) + ' ' + botonFuente(f.popPlanBt) : '');
        return;
      }
      if (!num(x.v) || !num(f.hoy.v)) { v.className = 'cifra__variacion'; v.innerHTML = icono('info') + 'Sin dato para comparar'; return; }
      const dif = x.v - f.hoy.v;
      if (f.clave === 'riesgo') {
        const netos = f.netos[plan];
        v.className = 'cifra__variacion ' + (num(netos.v) && netos.v > 0 ? 'cifra__variacion--bien' : 'cifra__variacion--mal');
        v.innerHTML = icono('canje') + (num(netos.v) ? (netos.v > 0 ? 'Ganados: ' : 'Perdidos: ') + s(netos.v, 0, 'netos por día') + ' con la contabilidad simétrica ' + botonFuente(f.popNetos[plan]) : 'Sin dato de la contabilidad simétrica');
        return;
      }
      const buena = f.mejorSiBaja === null ? null : (f.mejorSiBaja ? dif <= 0 : dif >= 0);
      v.className = 'cifra__variacion' + (buena === null ? '' : buena ? ' cifra__variacion--bien' : ' cifra__variacion--mal');
      const unidadDif = f.unidad === 'min' ? 'min' : f.unidad === 'M COP/año' ? 'M COP/año' : f.unidad.replace('/día', '');
      v.innerHTML = icono(dif < 0 ? 'flecha-abajo' : dif > 0 ? 'flecha-arriba' : 'igual') + s(dif, f.dec, unidadDif) + ' frente a hoy (' + s(pct(x.v, f.hoy.v), 1, '%') + ')';
    });
    const sel = cont.querySelector('#res-plan');
    if (sel) { sel.disabled = escenario !== 'modelo'; sel.parentNode.classList.toggle('con-tooltip', sel.disabled); }
    const notas = cont.querySelector('#res-fichas-notas');
    if (notas) notas.innerHTML = fichas.map(function (f) {
      return '<dt>' + esc(oraculo && f.etiquetaO ? f.etiquetaO : f.etiqueta) + '</dt><dd>' + esc(oraculo && f.notaO ? f.notaO : f.nota) + '</dd>';
    }).join('');
    const nota = cont.querySelector('#res-fichas-nota');
    if (nota) {
      const p = notaFichas[k === 'hoy' ? 'hoy' : oraculo ? 'orac' : plan];
      nota.innerHTML = p;
    }
    global.COMPONENTES.fuentes(cont);
  }
  // Rótulo de base sobre las fichas: qué se está mirando, con la fuente de los días.
  let notaFichas = {};
  function prepararNotaFichas() {
    const bt = fichas.bt;
    const pDias = popRuta('resultado_demanda_dia_d5', 'n_dias', 'días de la base anual');
    const pDiasBt = popRuta(bt.id, bt.k.plan ? [bt.k.plan, 'dias'] : null, 'días del backtest');
    const plan_ = valor('resultado_d5_reoptimizado', null, {}) || {};
    const nombre = function (p) { const c = plan_[p === 'b' ? 'b_D5_reoptimizado_e05' : 'a_D5_original']; return c && c.corrida ? ' (' + esc(c.corrida) + ')' : ''; };
    const anual = '<span>' + textoBaseAnual() + '</span>' + botonFuente(pDias, 'fuente');
    notaFichas = {
      hoy: '<strong>Hoy:</strong> la oferta real de ' + ANIO + ' y su costo a precios de ' + ANIO_SIGUE + '. ' + anual,
      b: '<strong>Con el modelo:</strong> el plan que reasigna' + nombre('b') + ', la propuesta. ' + anual,
      a: '<strong>Con el modelo:</strong> el plan que recorta' + nombre('a') + ', revalorado con costos de fuente pública. No es la propuesta. ' + anual,
      orac: '<strong>Oráculo:</strong> la decisión con la demanda que de verdad llegó. ' + '<span>' + textoBaseBacktest(bt) + '</span>' + botonFuente(pDiasBt, 'fuente') + ' ' + chipVerificado(fuenteDe(bt.id).verificado),
    };
  }

  // ---- Secciones ------------------------------------------------------------------------------------------------
  function seccionDia() {
    fichas = definirFichas();
    prepararNotaFichas();
    // Pronóstico: regla manual frente a los dos modelos.
    const eManual = primero([['inicio_error_regla_manual']]);
    const eFinal = primero([['inicio_error_modelo_final']]);
    const eHib = primero([['inicio_error_hibrido']]);
    const pManual = popoverId('inicio_error_regla_manual', 'regla manual');
    const pFinal = popoverId('inicio_error_modelo_final', 'modelo final (E11)');
    const pHib = popoverId('inicio_error_hibrido', 'híbrido (E12)');
    const regla = valor('inicio_regla_manual_definicion', null, null);
    const pRegla = typeof regla === 'string' ? popoverId('inicio_regla_manual_definicion', 'regla manual') : null;
    const filasPron = [
      { celdas: ['Sin el modelo: la regla manual' + (pRegla ? ' (' + esc(regla.replace(/\.$/, '')) + ') ' + botonFuente(pRegla) : ''), '<span class="tabla__peor">' + n(eManual.v, 2) + '&nbsp;%</span>', '—', botonFuente(pManual, 'fuente')] },
      { celdas: ['Con el modelo: modelo final (E11, LightGBM con calendario y demanda reciente)', n(eFinal.v, 2) + '&nbsp;%', num(eFinal.v) && num(eManual.v) ? s(eFinal.v - eManual.v, 2, 'puntos') : '—', botonFuente(pFinal, 'fuente')] },
      { celdas: ['Con el modelo: híbrido (E12, con las variables de Chronos-2) <span class="chip chip--acento">producción</span>', '<span class="tabla__mejor">' + n(eHib.v, 2) + '&nbsp;%</span>', num(eHib.v) && num(eManual.v) ? s(eHib.v - eManual.v, 2, 'puntos') : '—', botonFuente(pHib, 'fuente')] },
    ];
    const tPron = tabla('Sin el modelo frente a con el modelo: el pronóstico (pasajeros mal estimados de cada 100, WAPE a una semana, ' + ANIO + ', viajes válidos)', ['Quién pronostica', 'Error', 'Frente a la regla', 'Fuente'], filasPron, { compacta: true, textoEn: [3] });
    // Operación: hoy frente al plan elegido (tabla gemela de las fichas).
    const tOp = '<div id="res-tabla-operacion">' + tablaOperacion() + '</div>';
    // Facetas: barras hoy / reasigna / recorta por métrica.
    const claves = ['salidas', 'buses_hora', 'espera', 'sobrecap', 'riesgo'];
    const fichaDe = function (c) { return fichas.filter(function (x) { return x.clave === c; })[0]; };
    const lienzo = claves.map(function (c) { const f = fichaDe(c); return faceta(c, f.etiqueta + ' (' + f.unidad + ')'); }).join('');
    const filasFac = claves.map(function (c) { const f = fichaDe(c); return { celdas: [f.etiqueta + ' (' + f.unidad + ')', num(f.hoy.v) ? n(f.hoy.v, f.dec) : '—', num(f.b.v) ? n(f.b.v, f.dec) : '—', num(f.a.v) ? n(f.a.v, f.dec) : '—'] }; });
    const leyenda = itemLeyenda('Hoy', 'leyenda__muestra--barra', '--c: var(--serie-hoy)', true) + itemLeyenda('Reasigna (b): la propuesta', 'leyenda__muestra--barra', '--c: var(--serie-modelo)', true) + itemLeyenda('Recorta (a)', 'leyenda__muestra--barra resultado__muestra--hueca', '', true);
    const fig = figura('res-g-facetas', 'Hoy frente a los dos planes, métrica por métrica', 'Gris: lo que Sobusa hizo en ' + ANIO + '. Acento: el plan que reasigna (la propuesta). Hueco: el plan que recorta, que hoy no proponemos. ' + textoBaseAnual(), lienzo,
      tabla(null, ['Qué se mide', 'Hoy', 'Reasigna (b)', 'Recorta (a)'], filasFac, { compacta: true, sinMarco: true }), 'Mismas cifras que las fichas, con su fuente en cada ficha; el plan que recorta sale de D5 con sus supuestos y se revalora con costos de fuente pública.', leyenda, 'Barras por métrica: hoy, plan que reasigna y plan que recorta');
    const selector = '<div class="control-rotulado"><span class="control-rotulado__rotulo" aria-hidden="true">Plan:</span><fieldset class="segmentado segmentado--pequeno" id="res-plan" aria-label="Plan mostrado en «Con el modelo»"><legend>Plan</legend>' +
      '<label class="segmentado__opcion"><input type="radio" name="res-plan" value="b"' + (plan === 'b' ? ' checked' : '') + '><span class="segmentado__etiqueta">Reasigna (b) · la propuesta</span></label>' +
      '<label class="segmentado__opcion"><input type="radio" name="res-plan" value="a"' + (plan === 'a' ? ' checked' : '') + '><span class="segmentado__etiqueta">Recorta (a)</span></label></fieldset>' +
      '<span class="tooltip tooltip--izq" data-tooltip-plan>Se elige con el interruptor en «Con el modelo»</span></div>';
    return seccion('res-dia', 'Sin el modelo frente a con el modelo, en un día promedio',
      'Lo que Sobusa hizo en ' + ANIO + ' frente a lo que habría pasado con el plan del modelo, hecho una semana antes con el pronóstico y medido con la demanda real de cada día. Ese pronóstico es el del primer modelo (E1, con los rangos de E3): es el que usó el optimizador. El modelo final y el híbrido se equivocan menos, pero el plan del año no se volvió a calcular con ellos, así que su efecto en el saldo no está medido. El interruptor de arriba cambia las fichas; este selector elige cuál de los dos planes se compara.',
      '<p class="resultado__base" id="res-fichas-nota"></p>' + htmlFichas() + '<div class="rejilla-2 resultado__comparacion">' + tPron + tOp + '</div>' + fig + desplegableBases(), selector);
  }
  function tablaOperacion() {
    const filasOp = fichas.filter(function (f) { return f.clave !== 'costo' && f.clave !== 'riesgo'; }).map(function (f) {
      const x = f[plan];
      const dif = num(x.v) && num(f.hoy.v) ? x.v - f.hoy.v : null;
      return { celdas: [f.etiqueta, num(f.hoy.v) ? n(f.hoy.v, f.dec) : '—', num(x.v) ? n(x.v, f.dec) : '—', dif === null ? '—' : s(dif, f.dec) + ' (' + s(pct(x.v, f.hoy.v), 1, '%') + ')'] };
    });
    return tabla('Sin el modelo frente a con el modelo: la operación (' + PLAN_NOMBRE[plan] + '; promedio por día de ' + ANIO + ')', ['Qué se mide', 'Hoy', 'Con el modelo', 'Diferencia'], filasOp, { compacta: true });
  }
  // Las cifras que tienen varias bases, cada una con su rótulo y su fuente (contradicciones C5, C6 y C7 del inventario).
  function desplegableBases() {
    const item = function (id, ruta, dec, texto, titulo) {
      const v = ruta ? valor(id, ruta, null) : valor(id, null, null);
      if (!num(v)) return '';
      return '<li><strong>' + n(v, dec) + '</strong> ' + texto + ' ' + botonFuente(popRuta(id, ruta, titulo)) + '</li>';
    };
    const diasD5 = extraDe('resultado_demanda_dia_d5', 'n_dias');
    const diasGps = valor('ciudad_2025_real', 'dias', null);
    const sufD5 = num(diasD5) ? ' (' + n(diasD5, 0) + ' días)' : '';
    const sufGps = num(diasGps) ? ' (' + n(diasGps, 0) + ' días con GPS)' : '';
    const salidas = [
      item('inicio_salidas_dia_hoy', null, 0, 'salidas válidas por día: promedio de ' + ANIO + sufD5 + ', contabilidad de D5. Es la base de esta pantalla y de Inicio.', 'salidas de hoy, base D5'),
      item('horario_dia_promedio_2025', 'salidas_hoy', 0, 'salidas por día en el día típico (medianas por hora), la base de Horario.', 'salidas de hoy, día típico'),
      item('ciudad_2025_real', 'por_dia.salidas', 0, 'salidas por día con GPS, todos los viajes con trayectoria' + sufGps + ', la base de Ciudad.', 'salidas de hoy, persona a persona'),
    ].join('');
    const pasajeros = [
      item('resultado_demanda_dia_d5', null, 0, 'pasajeros por día en viajes válidos' + sufD5 + ': la base del riesgo del plan en esta pantalla.', 'pasajeros por día, base D5'),
      item('ciudad_2025_real', 'por_dia.pax', 0, 'pasajeros por día en todos los viajes con trayectoria, incluidos los marcados como cancelados que sí corrieron' + sufGps + ': solo en Ciudad y en «Otra forma de medirlo».', 'pasajeros por día, persona a persona'),
    ].join('');
    return '<details class="desplegable desplegable--llano" id="res-bases"><summary class="desplegable__resumen">' + icono('chevron-derecha', 'icono desplegable__chevron') + 'Por qué hay varias cifras de salidas y de pasajeros de hoy</summary><div class="desplegable__cuerpo">' +
      '<p class="texto-2">Cada fuente cuenta sobre su propia base. La app nunca las mezcla en una misma ficha y rotula cuál usa.</p>' +
      '<p><strong>Salidas por día hoy</strong></p><ul class="resultado__bases">' + salidas + '</ul><p><strong>Pasajeros por día</strong></p><ul class="resultado__bases">' + pasajeros + '</ul></div></details>';
  }

  function seccionCanje() {
    const cons = primero([['resultado_d5_reoptimizado', rutaPlan('b', 'neto_pago_hora_Mcop')], ['resultado_simulacion_plan_b', 'neto_hora_Mcop']]);
    const sim = primero([['resultado_d5_reoptimizado', rutaPlan('b', 'neto_simetrico_Mcop')], ['resultado_simulacion_plan_b', 'neto_hora_simetrica_Mcop']]);
    const ahorro = primero([['resultado_d5_reoptimizado', rutaPlan('b', 'ahorro_operativo_Mcop')]]);
    const riesgo = primero([['resultado_d5_reoptimizado', rutaPlan('b', 'pax_perdidos_dia')]]);
    const netos = primero([['resultado_d5_reoptimizado', rutaPlan('b', 'pax_netos_simetrico_dia')]]);
    const consA = primero([['resultado_d5_reoptimizado', rutaPlan('a', 'neto_pago_hora_Mcop')], ['resultado_simulacion_plan_a', 'neto_hora_Mcop']]);
    const simA = primero([['resultado_d5_reoptimizado', rutaPlan('a', 'neto_simetrico_Mcop')]]);
    const riesgoA = primero([['resultado_d5_reoptimizado', rutaPlan('a', 'pax_perdidos_dia')]]);
    const netosA = primero([['resultado_d5_reoptimizado', rutaPlan('a', 'pax_netos_simetrico_dia')], ['resultado_simulacion_plan_a', 'pasajeros_netos_simetrica_dia']]);
    const beta = primero([['inicio_beta'], ['resultado_costos_unitarios_2026', 'beta']]);
    const betaEq = primero([['inicio_beta_equilibrio_d5'], ['resultado_beta_equilibrio', 'D5.hora']]);
    const tarifa = primero([['resultado_costos_unitarios_2026', 'tarifa_efectiva'], ['inicio_tarifa_neta']]);
    const paxDia = primero([['resultado_demanda_dia_d5']]);
    const P = function (x, t) { return botonFuente(popDe(x, t)); };
    const rango = valor('inicio_beta_rango', null, null);
    const rInf = rango && typeof rango === 'object' ? (Array.isArray(rango) ? rango[0] : rango.inf) : null;
    const rSup = rango && typeof rango === 'object' ? (Array.isArray(rango) ? rango[1] : rango.sup) : null;
    const textoRango = num(rInf) && num(rSup) ? ' (rango creíble de ' + n(rInf, 2) + ' a ' + n(rSup, 2) + ' ' + botonFuente(popoverId('inicio_beta_rango', 'rango de β')) + ')' : '';
    const origen = entrada('inicio_beta_origen');
    const textoOrigen = origen && num(origen.valor) ? n(origen.valor, 0) + ' viajes registrados que no salieron' + (num(origen.pct) ? ' (' + n(origen.pct, 1) + ' % de los registrados)' : '') + ' ' + botonFuente(popoverId('inicio_beta_origen', 'con qué se midió β')) : 'fallas imprevistas, no recortes planificados';

    const avisoCanje = aviso('canje', 'Canje: el saldo depende de cuántos pasajeros atraen las salidas nuevas, y por eso se mide antes',
      '<p><strong>Conservadora:</strong> se cuentan solo los pasajes perdidos donde el plan quita salidas. El ahorro de operación (' + s(ahorro.v, 0, 'M COP/año') + ' ' + P(ahorro, 'ahorro de operación') + ') no alcanza a pagar los ' + n(riesgo.v, 0) + ' pasajeros en riesgo por día ' + P(riesgo, 'pasajeros en riesgo') +
        ' (' + (num(riesgo.v) && num(paxDia.v) ? n(riesgo.v / paxDia.v * 100, 1) : '—') + ' % de los ' + n(paxDia.v, 0) + ' diarios de la base de D5 ' + P(paxDia, 'pasajeros por día') + ') a ' + n(tarifa.v, 0) + ' COP cada uno ' + P(tarifa, 'tarifa neta') + '. Saldo: ' + s(cons.v, 0, 'M COP/año') + ' ' + P(cons, 'saldo conservador') + '.</p>' +
      '<p><strong>Simétrica:</strong> se cuentan también los pasajeros ganados donde el plan añade salidas, con la misma β: quedan ' + s(netos.v, 0, 'pasajeros netos por día') + ' ' + P(netos, 'pasajeros netos') + ' y el saldo pasa a ' + s(sim.v, 0, 'M COP/año') + ' ' + P(sim, 'saldo simétrico') + '. Las dos cuentas usan β = ' + n(beta.v, 2) + ' de E7. Ninguna es un pronóstico, y no hay base para decir cuál es más probable: cuántos pasajeros atraen las salidas añadidas nunca se ha medido. Por eso el plan no se aplica sin el piloto, y solo se adopta si las salidas añadidas atraen suficientes pasajeros (el umbral y lo que cuesta el piloto están en el tablero, Inicio).</p>' +
      '<p>Con la contabilidad conservadora, recortar no paga: el plan que recorta (a) deja ' + s(consA.v, 0, 'M COP/año') + ' ' + P(consA, 'saldo conservador, plan (a)') + ' (' + s(simA.v, 0) + ' ' + P(simA, 'saldo simétrico, plan (a)') + ' con la simétrica, pero ' + s(netosA.v, 0, 'pasajeros netos por día') + ' ' + P(netosA, 'pasajeros netos, plan (a)') + ') y pone en riesgo ' + n(riesgoA.v, 0) + ' pasajeros por día ' + P(riesgoA, 'pasajeros en riesgo, plan (a)') + '; solo pagaría si β fuera menor que ' + n(betaEq.v, 2) + ' ' + P(betaEq, 'β de equilibrio') + '.</p>');
    const fichasSaldo = '<div class="pila">' +
      cifraLlana('Saldo anual del plan que reasigna si las salidas nuevas no atraen a nadie (contabilidad conservadora)', s(cons.v, 0), 'M COP/año', { html: icono('canje') + 'Ahorro de operación menos pasajes perdidos, pago por hora, sin contar ninguno ganado: lo que dejaría aplicarlo sin medir', clase: '' }, null, popDe(cons, 'saldo conservador')) +
      cifraLlana('El mismo plan si atraen lo mismo que se pierde al quitar (contabilidad simétrica)', s(sim.v, 0), 'M COP/año', { html: icono('canje') + 'Cuenta también los pasajeros ganados donde se añaden salidas, con la misma β, que al añadir no se ha medido', clase: '' }, null, popDe(sim, 'saldo simétrico')) +
      cifraLlana('Pasajeros en riesgo por día (conservadora)', n(riesgo.v, 0), 'pasajeros/día', { html: icono('info') + 'frente a ' + s(netos.v, 0, 'netos') + ' con la simétrica ' + P(netos, 'pasajeros netos'), clase: '' }, null, popDe(riesgo, 'pasajeros en riesgo')) + '</div>';
    const avisoBeta = aviso('atencion', 'β se midió con fallas, no con recortes planificados',
      '<p>β es la fracción de pasajeros que se pierde por cada punto de salidas que se quita en una franja: β = ' + n(beta.v, 2) + ' ' + P(beta, 'β') + textoRango + ', medida en E7 con ' + textoOrigen + '. Un recorte planificado y anunciado puede perder menos (o más). Por eso el saldo depende tanto de β y por eso el piloto la mide en la calle antes de recortar. <a class="resultado__enlace" href="#piloto">Ver el piloto' + icono('chevron-derecha') + '</a></p>');

    // Sensibilidad a β: líneas de los dos planes.
    const sens = valor('resultado_sensibilidad_beta', null, null);
    let figBeta = '';
    const betas = sens && sens.b ? (sens.b.beta || sens.betas) : null;
    if (Array.isArray(betas)) {
      const pSens = popoverId('resultado_sensibilidad_beta', 'sensibilidad a β');
      const filas = betas.map(function (bt, i) { return { celdas: [n(bt, 2), s(sens.b.neto_hora_Mcop[i], 0), sens.a ? s(sens.a.neto_hora_Mcop[i], 0) : '—', n(sens.b.pasajeros_en_riesgo_dia[i], 0), sens.a ? n(sens.a.pasajeros_en_riesgo_dia[i], 0) : '—'] }; });
      figBeta = figura('res-g-beta', 'Cuánto cambia el saldo con β', 'Saldo anual (pago por hora, contabilidad conservadora) según la elasticidad β. Acento continuo: el plan que reasigna; a trazos: el que recorta. Las líneas verticales marcan β = ' + n(betaEq.v, 2) + ' (equilibrio del plan que recorta) y β = ' + n(beta.v, 2) + ' (la central de E7).', null,
        tabla(null, ['β', 'Reasigna (b): saldo', 'Recorta (a): saldo', 'Reasigna (b): en riesgo/día', 'Recorta (a): en riesgo/día'], filas, { compacta: true, sinMarco: true }),
        'M COP/año y pasajeros en riesgo por día. ' + botonFuente(pSens, 'Fuente'), itemLeyenda('Reasigna (b)', '', '--c: var(--serie-modelo)') + itemLeyenda('Recorta (a)', 'leyenda__muestra--trazos', '--c: var(--serie-modelo)'), 'Líneas: saldo anual de los dos planes según β');
      graficos._beta = { sens: sens, betas: betas, betaEq: betaEq.v, beta: beta.v };
    }
    return seccion('res-canje', 'Lo que gana Sobusa, con el canje completo',
      'El plan que reasigna mejora el servicio; en plata, el resultado depende de cómo se cuenten los pasajeros que se ganan donde se añaden salidas. Se muestran las dos cuentas.',
      '<div class="rejilla-lado">' + avisoCanje + fichasSaldo + '</div>' + avisoBeta + figBeta);
  }

  function seccionCorridas() {
    const v = valor('resultado_d5_reoptimizado', null, null);
    if (!v) return seccion('res-corridas', 'Todas las corridas del optimizador', null, aviso('atencion', 'Sin datos', '<p>Falta resultado_d5_reoptimizado en los datos de la app.</p>'));
    let corridas = Array.isArray(v.corridas) ? v.corridas : [];
    const nombreB = v.b_D5_reoptimizado_e05 && v.b_D5_reoptimizado_e05.corrida;
    const nombreA = v.a_D5_original && v.a_D5_original.corrida;
    const propuesta = v.propuesta || nombreB || null;
    if (!corridas.length) {
      corridas = [v.a_D5_original || {}, v.b_D5_reoptimizado_e05 || {}];
      Object.keys(v.otras_corridas || {}).forEach(function (k) { corridas.push(Object.assign({ corrida: k }, v.otras_corridas[k])); });
    }
    const pop = popoverId('resultado_d5_reoptimizado', 'corridas del optimizador');
    // Marca de una fila: «parcial» si el revisor reprodujo solo algunas columnas; «sí» si las reprodujo todas.
    const marcaFila = function (plan) {
      const g = (extraDe('resultado_d5_reoptimizado', 'verificado_campos') || {})[plan];
      if (!g || typeof g !== 'object') return null;
      const m = Object.keys(g).map(function (k) { return g[k]; });
      return m.every(function (x) { return x === 'sí'; }) ? 'sí' : m.some(function (x) { return x === 'sí'; }) ? 'parcial' : 'no';
    };
    const chipRevisorFila = function (m) {
      const c = claseVerificado(m);
      return '<span class="chip chip--' + c + '">' + icono(c === 'bien' ? 'bien' : 'alerta') + (c === 'bien' ? 'Revisor: sí' : c === 'atencion' ? 'Revisor: en parte' : 'Sin revisor') + '</span>';
    };
    const celda = function (x, d, signo) { return num(x) ? (signo ? s(x, d) : n(x, d)) : '—'; };
    const filas = corridas.map(function (c) {
      const esProp = propuesta && c.corrida === propuesta;
      const esA = nombreA && c.corrida === nombreA;
      const marca = esProp ? marcaFila('b_D5_reoptimizado_e05') : esA ? marcaFila('a_D5_original') : marcaCampo('resultado_d5_reoptimizado', 'otras_corridas');
      return { clase: esProp ? 'resultado__propuesta' : '', celdas: [esc(c.corrida) + (esProp ? ' <span class="chip chip--acento">La que proponemos · reasigna (b)</span>' : esA ? ' <span class="chip">Recorta (a)</span>' : '') + (marca ? ' ' + chipRevisorFila(marca) : ''), celda(c.salidas_dia, 0), celda(c.buses_hora_dia, 0), celda(c.espera_min, 1), celda(c.sobrecap_dia, 0), celda(c.pax_perdidos_dia, 0), celda(c.ahorro_operativo_Mcop, 0, true), celda(c.neto_pago_hora_Mcop, 0, true), celda(c.neto_simetrico_Mcop, 0, true), celda(c.pax_netos_simetrico_dia, 0, true)] };
    });
    const t = tabla('Las corridas del optimizador con costos de fuente pública (promedio por día de ' + ANIO + ' y saldo anual con β = ' + n(betaCentral(), 2) + ')',
      ['Corrida', 'Salidas/día', 'Buses-hora/día', 'Espera (min)', 'Sobre capacidad/día', 'En riesgo/día', 'Ahorro operativo (M COP/año)', 'Saldo conservador (M COP/año)', 'Saldo simétrico (M COP/año)', 'Pasajeros netos/día'], filas, { compacta: true });
    return seccion('res-corridas', 'Todas las corridas del optimizador', 'Una fila por corrida de costos/resultados/d5_reoptimizado.csv. La resaltada es la que proponemos; la marcada «Recorta (a)» es D5 con sus supuestos. Las demás cambian la elasticidad que usa el optimizador para decidir, ponen la caja del operador como único objetivo o pagan por producido: con la contabilidad conservadora, todas pierden más. La marca de cada fila dice qué comprobó un revisor independiente: en la propuesta y en la que recorta, parte de las columnas (el botón «fuente» de cada ficha lo dice cifra a cifra); las demás corridas no tienen revisión.',
      t + '<p class="texto-3 pequeno">En el nombre de cada corrida, e es la elasticidad con la que decide el optimizador; β = ' + n(betaCentral(), 2) + ' es la que se usa para valorar el resultado de todas. ' + botonFuente(pop, 'Fuente') + '</p>');
  }

  function seccionPorFecha() {
    const tipo = valor('resultado_por_tipo_dia', null, null);
    let tTipo = '';
    if (tipo && tipo.b) {
      const pop = popoverId('resultado_por_tipo_dia', 'saldo por tipo de día');
      const filas = [];
      ['b', 'a'].forEach(function (p) {
        Object.keys(tipo[p] || {}).forEach(function (k) {
          const x = tipo[p][k];
          filas.push({ clase: p === 'b' ? '' : 'texto-2', celdas: [PLAN_NOMBRE[p] + ' · ' + esc(k) + (num(x.dias) ? ' (' + n(x.dias, 0) + ' días)' : ''), s(x.neto_anual_Mcop, 0), s(x.neto_dia_Mcop, 2), num(x.neto_simetrico_anual_Mcop) ? s(x.neto_simetrico_anual_Mcop, 0) : '—', n(x.pax_riesgo_dia, 0), n(x.dias_positivos, 0)] });
        });
      });
      const pagan = function (p) { return Object.keys(tipo[p] || {}).filter(function (k) { return tipo[p][k].neto_anual_Mcop > 0; }); };
      const pierden = function (p) { return Object.keys(tipo[p] || {}).filter(function (k) { return tipo[p][k].neto_anual_Mcop <= 0; }); };
      const lista = function (ks) { return ks.map(function (k) { return k.toLowerCase(); }).join(' y '); };
      const pB = pagan('b'); const pA = pagan('a');
      let frase;
      if (!pB.length && !pA.length) frase = 'Con la contabilidad conservadora ningún tipo de día paga.';
      else {
        const union = pB.concat(pA.filter(function (k) { return pB.indexOf(k) < 0; }));
        const partes = [];
        if (pB.length) partes.push(pB.map(function (k) { return s(tipo.b[k].neto_anual_Mcop, 0, 'M COP/año'); }).join(', ') + ' con el plan que reasigna');
        if (pA.length) partes.push(pA.map(function (k) { return s(tipo.a[k].neto_anual_Mcop, 0, 'M COP/año') + ' con el que recorta, a costa de ' + n(tipo.a[k].pax_riesgo_dia, 0) + ' pasajeros en riesgo cada día'; }).join('; '));
        const pierdenB = pierden('b');
        frase = 'Con la contabilidad conservadora solo paga' + (union.length > 1 ? 'n' : '') + ' ' + lista(union) + ': ' + partes.join(' y ') + '.' + (pierdenB.length ? ' Con el plan que reasigna pierde' + (pierdenB.length > 1 ? 'n' : '') + ' ' + lista(pierdenB) + '.' : '');
      }
      tTipo = tabla('Saldo por tipo de día (pago por hora; M COP)', ['Plan y tipo de día', 'Saldo del año', 'Saldo por día', 'Saldo simétrico del año', 'En riesgo por día', 'Días con saldo positivo'], filas, { compacta: true }) +
        '<p class="texto-2 pequeno">' + frase + ' ' + botonFuente(pop, 'Fuente') + '</p>';
    }
    const mes = valor('resultado_por_mes', null, null);
    let figMes = '';
    if (mes && mes.b && Array.isArray(mes.b.neto_hora_Mcop)) {
      const pop = popoverId('resultado_por_mes', 'saldo por mes');
      const nombres = (mes.b.mes || mes.meses || []).map(function (m) { return MESES[m - 1] || String(m); });
      const filas = nombres.map(function (m, i) { return { celdas: [m + (mes.b.dias ? ' (' + n(mes.b.dias[i], 0) + ' días)' : ''), s(mes.b.neto_hora_Mcop[i], 0), s(mes.b.neto_hora_simetrica_Mcop[i], 0), mes.a ? s(mes.a.neto_hora_Mcop[i], 0) : '—', mes.b.pasajeros_en_riesgo ? n(mes.b.pasajeros_en_riesgo[i], 0) : '—'] }; });
      const mesesPaganCons = mes.b.neto_hora_Mcop.filter(function (x) { return x > 0; }).length;
      const mesesPaganSim = mes.b.neto_hora_simetrica_Mcop.filter(function (x) { return x > 0; }).length;
      figMes = figura('res-g-mes', 'Saldo mes a mes del plan que reasigna', 'Barras llenas: contabilidad conservadora; rayadas: simétrica. Con la conservadora pagan ' + n(mesesPaganCons, 0) + ' de ' + n(nombres.length, 0) + ' meses; con la simétrica, ' + n(mesesPaganSim, 0) + '. La simulación recalcula cada día de ' + ANIO + ' con la demanda real de ese día.', null,
        tabla(null, ['Mes de ' + ANIO, 'Reasigna (b): conservadora', 'Reasigna (b): simétrica', 'Recorta (a): conservadora', 'Reasigna (b): pasajeros en riesgo en el mes'], filas, { compacta: true, sinMarco: true }),
        'M COP por mes, pago por hora, β = ' + n(betaCentral(), 2) + '. ' + botonFuente(pop, 'Fuente'),
        itemLeyenda('Conservadora', 'leyenda__muestra--barra', '--c: var(--serie-modelo)') + itemLeyenda('Simétrica', 'leyenda__muestra--barra resultado__muestra--rayas', ''), 'Barras por mes: saldo conservador y simétrico del plan que reasigna');
      graficos._mes = { nombres: nombres, b: mes.b };
    }
    const modulo = '<div class="modulo resultado__modulo" id="res-modulo"><div class="modulo__barra"><span class="modulo__nombre">' + icono('calendario') + 'Simulador de ahorro por fecha</span>' +
      '<span class="modulo__estado"><span id="res-modulo-estado" aria-live="polite">Se carga al llegar aquí</span>' +
      '<a class="boton boton--secundario boton--pequeno boton--icono con-tooltip" href="simulador_ahorro.html#fecha&plan=b" target="_blank" rel="noopener" aria-label="Abrir aparte">' + icono('externo') + '<span class="tooltip tooltip--izq">Abrir aparte</span></a></span></div>' +
      '<div class="resultado__modulo-cuerpo" id="res-modulo-cuerpo"><div class="modulo__cargando" id="res-modulo-cargando" hidden><span class="estado-carga"><span class="giro" aria-hidden="true"></span>Cargando el simulador…</span></div></div></div>';
    return seccion('res-fecha', 'Por tipo de día, por mes y por fecha',
      'La simulación recorre cada día de ' + ANIO + ' con la demanda real: qué habría ahorrado, cuántos pasajeros habría puesto en riesgo y cuántos conductores habría necesitado. Abajo, el simulador deja cambiar la fecha, el plan, la forma de pago, los precios y β.',
      tTipo + figMes + modulo);
  }

  function seccionConductores() {
    const c = valor('resultado_conductores_2025', null, null) || {};
    const pb = valor('resultado_simulacion_plan_b', null, null) || {};
    const pa = valor('resultado_simulacion_plan_a', null, null) || {};
    const cc = valor('resultado_costo_conductor', null, null) || {};
    const cu = valor('resultado_costos_unitarios_2026', null, null) || {};
    const horasMes = primero([['resultado_costos_unitarios_2026', 'horas_mes_2026']]);
    const C = function (ruta, t) { return popRuta('resultado_conductores_2025', ruta, t); };
    const B = function (ruta, t) { return botonFuente(popRuta('resultado_simulacion_plan_b', ruta, t)); };
    const cpd = c.conductores_por_dia || {};
    const reg = c.mes_regulares || {};
    const fichasC = '<div class="cifras">' +
      cifraLlana('Conductores que trabajaron cada día en ' + ANIO, num(cpd.cota_baja) ? n(cpd.cota_baja, 0) + ' a ' + n(cpd.cota_alta, 0) : '—', 'por día', { html: icono('info') + n(cpd.identificados_media, 0) + ' identificados ' + botonFuente(C('conductores_por_dia.identificados_media', 'conductores identificados por día')) + ' más los que haya detrás del código genérico del primer viaje del día', clase: '' }, 'Rango, no una cifra: el código genérico no dice cuántas personas son.', C('conductores_por_dia.cota_baja', 'cotas de conductores por día')) +
      cifraLlana('Horas en ruta al mes de un conductor regular', num(reg.ruta_mediana_h) ? n(reg.ruta_mediana_h, 0) : '—', 'h/mes', { html: icono('alerta') + 'frente a ' + n(horasMes.v, 0) + ' h de la jornada legal de ' + ANIO_SIGUE + ' ' + botonFuente(popDe(horasMes, 'jornada legal')) + '; el ' + n(reg.pct_ruta_mayor_182, 0) + ' % la pasa ' + botonFuente(C('mes_regulares.pct_ruta_mayor_182', 'regulares por encima de la jornada')), clase: 'cifra__variacion--mal' }, 'Mediana de los conductores regulares del mes; solo las horas en ruta, sin las pausas.', C('mes_regulares.ruta_mediana_h', 'horas en ruta de los regulares')) +
      cifraLlana('Conductores que pide el plan que reasigna', num(pb.conductores_dia_plan) ? n(pb.conductores_dia_plan, 1) : '—', 'por día', { html: icono('flecha-arriba') + (num(pb.conductores_dia_plan) && num(pb.conductores_dia_real) ? s(pb.conductores_dia_plan - pb.conductores_dia_real, 1) + ' frente a los ' + n(pb.conductores_dia_real, 1) + ' que la misma regla da hoy ' + B('conductores_dia_real', 'conductores de hoy con la regla') : 'sin dato'), clase: 'cifra__variacion--mal' }, 'Regla de horas observadas por ruta. Plantilla: ' + n(pb.plantilla_plan, 0) + ' frente a ' + n(pb.plantilla_real, 0) + '.', popRuta('resultado_simulacion_plan_b', 'conductores_dia_plan', 'conductores con el plan (b)')) +
      cifraLlana('Conductores que pide el plan que recorta', num(pa.conductores_dia_plan) ? n(pa.conductores_dia_plan, 1) : '—', 'por día', { html: icono('flecha-abajo') + (num(pa.conductores_dia_plan) && num(pa.conductores_dia_real) ? s(pa.conductores_dia_plan - pa.conductores_dia_real, 1) + ' frente a hoy' : 'sin dato'), clase: 'cifra__variacion--bien' }, 'Ahorra conductores, pero pone en riesgo ' + n(pa.pasajeros_en_riesgo_dia, 0) + ' pasajeros por día.', popRuta('resultado_simulacion_plan_a', 'conductores_dia_plan', 'conductores con el plan (a)')) +
      cifraLlana('Lo que cuesta un conductor', num(cc.costo_bus_hora) ? n(cc.costo_bus_hora, 0) : '—', 'COP por bus-hora', { html: icono('info') + (num(cc.costo_mes_conductor) ? n(cc.costo_mes_conductor, 0) + ' COP al mes con prestaciones ' + botonFuente(popRuta('resultado_costo_conductor', 'costo_mes_conductor', 'costo mensual del conductor')) : 'sin dato'), clase: '' }, 'Pago por hora: ' + n(cu.multiplo_salario, 1) + ' salarios mínimos de ' + ANIO_SIGUE + ' con prestaciones, ' + n(horasMes.v, 0) + ' h al mes y ' + n(cu.factor_horas_pagadas, 2) + ' h pagadas por hora en ruta.', popRuta('resultado_costo_conductor', 'costo_bus_hora', 'costo del conductor por bus-hora')) + '</div>';
    const salvedad = aviso('atencion', 'Salvedad: antes de prometer ahorros de nómina hay que confirmar la jornada y la forma de pago',
      '<p>Los datos muestran jornadas por encima de la legal (' + n(reg.ruta_mediana_h, 0) + ' h en ruta al mes los regulares, ' + n(reg.jornada_mediana_h, 0) + ' h contando las pausas ' + botonFuente(C('mes_regulares.jornada_mediana_h', 'jornada de los regulares')) + '): turnos largos, horas extra o pago por producido; el sistema no registra cómo se paga ni los relevos. Con pago por producido el ahorro en conductores es cero; con salario fijo depende de reducir la plantilla, y el plan que reasigna la sube (' + n(pb.plantilla_plan, 0) + ' frente a ' + n(pb.plantilla_real, 0) + ' ' + B('plantilla_plan', 'plantilla con el plan (b)') + '). Sin datos personales: solo conteos agregados.</p>');
    return seccion('res-conductores', 'Conductores', 'Cuántos trabajan hoy, cuántos pediría cada plan y qué cuesta cada uno. La cifra de hoy es un rango porque el código genérico del primer viaje del día esconde cuántas personas son.', fichasC + salvedad);
  }

  function seccionBacktest() {
    const bt = fichas.bt || datosBacktest();
    const f = fuenteDe(bt.id);
    const P = function (quien, campo, t) { return popRuta(bt.id, bt.k[quien] ? [bt.k[quien], campo] : null, t); };
    const val = function (quien, campo) { return bt[quien] && num(bt[quien][campo]) ? bt[quien][campo] : null; };
    const errPlan = val('plan', 'error_salidas_h'), errReal = val('real', 'error_salidas_h'), errMotor = val('motor', 'error_salidas_h');
    const exPlan = val('plan', 'pct_exactas'), exReal = val('real', 'pct_exactas'), exMotor = val('motor', 'pct_exactas');
    const motorMejora = num(errMotor) && num(errPlan) ? errMotor < errPlan : null;
    const fichasBt = '<div class="cifras">' +
      cifraLlana('Plan semanal frente al oráculo', num(errPlan) ? n(errPlan, 2) : '—', 'salidas/h de error', { html: icono('bien') + (num(exPlan) ? n(exPlan, 1) + ' % de las horas con el número exacto de salidas ' + botonFuente(P('plan', 'pct_exactas', 'horas exactas, plan semanal')) : ''), clase: 'cifra__variacion--bien' }, 'Plan hecho una semana antes con el pronóstico y los costos de fuente pública; error medio por hora frente a la decisión óptima con la demanda que llegó.', P('plan', 'error_salidas_h', 'error del plan semanal')) +
      cifraLlana('La operación real frente al oráculo', num(errReal) ? n(errReal, 2) : '—', 'salidas/h de error', { html: icono('alerta') + (num(exReal) ? n(exReal, 1) + ' % de horas exactas ' + botonFuente(P('real', 'pct_exactas', 'horas exactas, operación real')) : ''), clase: 'cifra__variacion--mal' }, 'Lo que Sobusa despachó esos mismos días.', P('real', 'error_salidas_h', 'error de la operación real')) +
      cifraLlana('Reoptimizar en el día (con el pronóstico del mismo día)', num(errMotor) ? n(errMotor, 2) : '—', 'salidas/h de error', { html: icono(motorMejora ? 'bien' : 'igual') + (motorMejora === null ? '' : motorMejora ? 'mejora un poco al plan semanal' : 'no mejora al plan semanal') + (num(exMotor) ? ' (' + n(exMotor, 1) + ' % de horas exactas ' + botonFuente(P('motor', 'pct_exactas', 'horas exactas, motor')) + ')' : ''), clase: '' }, 'La consola vale por las alertas y la vigilancia, no por cambiar el plan cada hora.', P('motor', 'error_salidas_h', 'error del motor')) + '</div>';
    let fig = '';
    if (bt.plan && bt.real && bt.orac) {
      const metricas = [
        { clave: 'bt_salidas', titulo: 'Salidas por día', campo: 'salidas_dia', dec: 0, unidad: 'salidas/día' },
        { clave: 'bt_buses', titulo: 'Buses-hora por día', campo: 'buses_hora_dia', dec: 0, unidad: 'buses-hora/día' },
        { clave: 'bt_espera', titulo: 'Espera media (min)', campo: 'espera_min', dec: 1, unidad: 'min' },
        { clave: 'bt_sobrecap', titulo: 'Pasajeros sobre la capacidad por día', campo: 'sobrecap_dia', dec: 0, unidad: 'pasajeros/día' },
        { clave: 'bt_costo', titulo: 'Costo generalizado por día (M COP)', campo: 'costo_Mcop_dia', dec: 1, unidad: 'M COP/día' },
      ];
      graficos._bt = { metricas: metricas, hoy: bt.real, plan: bt.plan, oraculo: bt.orac };
      const lienzo = metricas.map(function (m) { return faceta(m.clave, m.titulo); }).join('');
      const filas = metricas.map(function (m) { return { celdas: [m.titulo, n(bt.real[m.campo], m.dec), n(bt.plan[m.campo], m.dec), n(bt.orac[m.campo], m.dec), bt.motor ? n(bt.motor[m.campo], m.dec) : '—'] }; });
      const pop = popoverId(bt.id, 'backtest');
      fig = figura('res-g-backtest', 'Hoy, el plan y el oráculo en los ' + n(bt.dias, 0) + ' días del backtest', 'Gris: lo que Sobusa despachó. Acento: el plan semanal del modelo. A trazos: el oráculo, que decide con la demanda que de verdad llegó. ' + textoBaseBacktest(bt), lienzo,
        tabla(null, ['Qué se mide', 'Hoy', 'Plan semanal', 'Oráculo', 'Motor'], filas, { compacta: true, sinMarco: true }),
        'Muestra de días de ' + ANIO + ' con laborales, sábados, domingos, festivos, Carnaval, lluvia fuerte y días atípicos. ' + botonFuente(pop, 'Fuente'),
        itemLeyenda('Hoy', 'leyenda__muestra--barra', '--c: var(--serie-hoy)', true) + itemLeyenda('Plan semanal (con el modelo)', 'leyenda__muestra--barra', '--c: var(--serie-modelo)', true) + itemLeyenda('Oráculo', 'leyenda__muestra--barra resultado__muestra--oraculo', '', true), 'Barras por métrica: hoy, plan semanal y oráculo en el backtest');
    }
    const fecha = (String(f.experimento || '') + ' ' + String(f.nota || '')).match(/\d{2}-\d{2}-\d{4}/);
    const verificado = claseVerificado(f.verificado) === 'bien';
    const notaCorrida = aviso(verificado ? 'bien' : 'atencion', 'Corrida ' + (fecha ? 'del ' + esc(fecha[0]) : 'vigente') + ' del backtest: ' + (verificado ? 'con revisor independiente' : 'sin revisor independiente'),
      '<p>' + chipVerificado(f.verificado) + ' ' + esc(f.revision) + '</p>');
    return seccion('res-backtest', 'Qué tan cerca del óptimo: el backtest', 'El oráculo decide cada hora con la demanda que de verdad llegó: nadie puede hacerlo mejor. Aquí se mide cuánto se alejan de él el plan semanal, la operación real y el motor que reoptimiza en el día. <a class="resultado__enlace" href="#despacho">Ver la consola' + icono('chevron-derecha') + '</a>',
      notaCorrida + fichasBt + fig);
  }

  function seccionPersona() {
    const id = entrada('ciudad_2025_saldo') ? 'ciudad_2025_saldo' : 'inicio_persona_a_persona_saldo';
    const v = valor(id, null, null) || {};
    const dias = num(v.dias) ? v.dias : extraDe(id, 'dias');
    const f = fuenteDe(id);
    const Pp = function (campo, t) { return popRuta(id, campo, t); };
    const real = valor('ciudad_2025_real', 'por_dia', null) || {};
    const cuerpo = '<div class="resultado__fila-cifras">' +
      cifraLlana('Ahorro de operación', num(v.ahorro_operacion_Mcop) ? s(v.ahorro_operacion_Mcop, 0) : '—', 'M COP', null, null, Pp('ahorro_operacion_Mcop', 'ahorro de operación, persona a persona')) +
      cifraLlana('Pasajes perdidos', num(v.pasajes_perdidos_Mcop) ? s(-v.pasajes_perdidos_Mcop, 0) : '—', 'M COP', null, null, Pp('pasajes_perdidos_Mcop', 'pasajes perdidos, persona a persona')) +
      cifraLlana('Saldo conservador', num(v.saldo_conservador_Mcop) ? s(v.saldo_conservador_Mcop, 0) : '—', 'M COP', null, null, Pp('saldo_conservador_Mcop', 'saldo conservador, persona a persona')) +
      cifraLlana('Saldo simétrico', num(v.saldo_simetrico_Mcop) ? s(v.saldo_simetrico_Mcop, 0) : '—', 'M COP', null, null, Pp('saldo_simetrico_Mcop', 'saldo simétrico, persona a persona')) +
      cifraLlana('Pasajeros en riesgo', num(v.pasajeros_en_riesgo_dia) ? n(v.pasajeros_en_riesgo_dia, 0) : '—', 'por día', { html: num(v.perdidos_beta_dia) ? icono('info') + n(v.perdidos_beta_dia, 0) + ' por β ' + botonFuente(Pp('perdidos_beta_dia', 'perdidos por β')) + ' y ' + n(v.perdidos_sin_bus_dia, 0) + ' que no encuentran bus a tiempo ' + botonFuente(Pp('perdidos_sin_bus_dia', 'perdidos sin bus')) : '', clase: '' }, null, Pp('pasajeros_en_riesgo_dia', 'pasajeros en riesgo, persona a persona')) + '</div>';
    const pPax = num(real.pax) ? popRuta('ciudad_2025_real', 'por_dia.pax', 'pasajeros por día, persona a persona') : null;
    const pSal = num(real.salidas) ? popRuta('ciudad_2025_real', 'por_dia.salidas', 'salidas por día, persona a persona') : null;
    const base = '<p class="resultado__base">Base: ' + (num(dias) ? n(dias, 0) + ' días de ' + ANIO + ' con GPS' : 'los días de ' + ANIO + ' con GPS') +
      (pPax ? '; ' + n(real.pax, 0) + ' pasajeros por día ' + botonFuente(pPax) : '') + (pSal ? ' y ' + n(real.salidas, 0) + ' salidas por día hoy ' + botonFuente(pSal) : '') +
      ', todos los viajes con trayectoria. No son las cifras de la contabilidad de D5 de arriba.</p>';
    return seccion('res-persona', 'Otra forma de medirlo: el modelo persona a persona de la vista 3D',
      'La vista Ciudad sortea a cada pasajero de cada viaje real de ' + ANIO + ' y lo sube al primer bus del plan que pasa. Castiga más al plan que la contabilidad de D5: cuenta a quien no encuentra bus a tiempo, usa todos los viajes con trayectoria (no solo los válidos) y no pone tope de cupo. Se muestra como hallazgo, no se esconde.',
      '<div class="tarjeta resultado__fila"><div class="fila">' + chipVerificado(f.verificado) + '<span class="chip">Otra medida, sin recálculo independiente de la suma anual</span><a class="boton boton--secundario boton--pequeno" href="#ciudad">Ver en Ciudad' + icono('chevron-derecha') + '</a></div>' + base + cuerpo +
      '<p class="texto-3 pequeno">Las cifras principales de esta pantalla son las de la contabilidad de D5, con revisor independiente; estas miden el mismo plan con otra base. ' + esc(f.revision) + '</p></div>');
  }

  function seccionNoPrometemos() {
    const pb = valor('resultado_simulacion_plan_b', null, null) || {};
    const pPl = popRuta('resultado_simulacion_plan_b', 'plantilla_plan', 'plantilla con el plan (b)');
    const lista = [
      '<li><strong>No prometemos ahorro de nómina.</strong> El ahorro de conductores supone pago por hora; con salario fijo el plan que reasigna pide más plantilla (' + n(pb.plantilla_plan, 0) + ' frente a ' + n(pb.plantilla_real, 0) + ' ' + botonFuente(pPl) + ') y con pago por producido el ahorro es cero. Hay que confirmar con Sobusa la jornada real y la forma de pago.</li>',
      '<li><strong>No prometemos el saldo simétrico.</strong> Que los pasajeros ganados donde se añaden salidas existan de verdad depende de que la demanda responda a la oferta; β se midió con fallas, no con mejoras anunciadas.</li>',
      '<li><strong>Lo que el piloto decide y lo que no.</strong> El piloto mide con buena precisión cuántos pasajeros se pierden al quitar salidas: eso decide el plan que recorta, que no proponemos. Al plan que reasigna lo decide cuántos pasajeros atraen las salidas añadidas; el piloto lo mide en dos franjas de refuerzo, con menos precisión (ver Piloto). Si atraen pocos, el saldo se acerca al de la cuenta conservadora, que es negativo, y lo prudente es no cambiar el horario.</li>',
      '<li><strong>No prometemos recortar.</strong> Con costos de fuente pública y la contabilidad conservadora, el plan que recorta no paga: pierde más en pasajes que lo que ahorra, salvo en los días de menos demanda; con la simétrica paga, pero pierde pasajeros netos y sube los pasajeros sobre la capacidad.</li>',
      '<li><strong>No prometemos menos flota ni menos despachadores.</strong> El plan mueve salidas de hora; el pico sigue pidiendo casi los mismos buses y los puestos de despacho no cambian.</li>',
      '<li><strong>No prometemos el ahorro de ' + ANIO + ' para ' + ANIO_SIGUE + '.</strong> La demanda de ' + ANIO_SIGUE + ' cambió de nivel; el plan se recalcula cada semana con el pronóstico, y el piloto mide β antes de cualquier recorte.</li>',
    ];
    return seccion('res-no-prometemos', 'Qué no prometemos', null, '<ul class="resultado__lista">' + lista.join('') + '</ul>');
  }

  function seccionLimites() {
    const lb = valor('resultado_linea_base_2025', null, null) || {};
    const pMargen = popRuta('resultado_linea_base_2025', 'margen_pct', 'margen de la línea base');
    const lista = [
      '<li><strong>La línea base da un margen negativo (' + (num(lb.margen_pct) ? n(lb.margen_pct, 1) + ' %' : '—') + ' ' + botonFuente(pMargen) + ') que es orientativo:</strong> carga los costos fijos y los conductores completos contra la tarifa neta; sirve para comparar, no para juzgar la empresa.</li>',
      '<li><strong>Dos contabilidades del mismo plan:</strong> la de D5 (viajes válidos, β por franja) y la persona a persona (todos los viajes con trayectoria, sin tope de cupo) dan saldos distintos; se muestran las dos y se dice cuál tuvo revisor.</li>',
      '<li><strong>El backtest vigente no tiene revisor independiente:</strong> la corrida con costos de fuente pública reusa el código de la corrida verificada; el plan se reproduce hora a hora con el optimizador de D5.</li>',
      '<li><strong>Conductores:</strong> el código genérico del primer viaje del día y los relevos sin registrar dejan la cifra de hoy en un rango; la regla de conductores se aplica igual a hoy y al plan, así que la diferencia es lo que importa.</li>',
      '<li><strong>Espera y sobrecapacidad</strong> salen de fórmulas (intervalo del punto medio, capacidad del bus en el tramo crítico), no de mediciones en la calle.</li>',
      '<li><strong>Los costos son de ' + ANIO_SIGUE + ' con fuentes públicas</strong> (ACPM, salario mínimo, tarifa); si Sobusa entrega los suyos, el planificador y el simulador los reciben como parámetros.</li>',
      '<li><strong>El año completo no tiene oráculo con costos de fuente pública:</strong> con «Oráculo» las fichas pasan a la base del backtest y no se comparan con las del año.</li>',
    ];
    return seccion('res-limites', 'Límites', null, '<ul class="resultado__lista">' + lista.join('') + '</ul>');
  }

  // Parámetros del tornado: enteros grandes sin decimales; fracciones con dos.
  function numParam(v) { return num(v) ? n(v, Math.abs(v) < 10 && v % 1 !== 0 ? 2 : 0) : esc(v); }
  function seccionComoSeCalculo() {
    const cu = valor('resultado_costos_unitarios_2026', null, null) || {};
    const pCu = popoverId('resultado_costos_unitarios_2026', 'costos unitarios ' + ANIO_SIGUE);
    const filasCu = [
      { celdas: ['Combustible (ACPM a ' + n(cu.precio_acpm_2026, 0) + ' COP/gal, ' + n(cu.rendimiento_km_gal, 2) + ' km/gal)', n(cu.combustible_km, 0) + ' COP/km'] },
      { celdas: ['Mantenimiento', n(cu.mant_km, 0) + ' COP/km'] }, { celdas: ['Llantas', n(cu.llantas_km, 0) + ' COP/km'] }, { celdas: ['Lubricantes', n(cu.lub_km, 0) + ' COP/km'] },
      { clase: 'tabla__fila-total', celdas: ['Costo evitable por km', n(cu.costo_km_evitable, 0) + ' COP/km'] },
      { celdas: ['Conductor por bus-hora en ruta (' + n(cu.multiplo_salario, 1) + ' salarios mínimos de ' + n(cu.smmlv_2026, 0) + ' COP con factor ' + n(cu.factor_prestacional, 2) + ', ' + n(cu.horas_mes_2026, 0) + ' h/mes, ' + n(cu.factor_horas_pagadas, 2) + ' h pagadas por hora en ruta)', n(cu.bus_hora_conductor, 0) + ' COP/bus-hora'] },
      { celdas: ['Costo fijo por bus al año', n(cu.fijo_bus_anio, 0) + ' COP'] },
      { celdas: ['Tarifa neta (tarifa de ' + n(cu.tarifa_2026, 0) + ' COP × ' + n(cu.factor_ingreso, 2) + ' que retiene el operador)', n(cu.tarifa_efectiva, 0) + ' COP/pasajero'] },
      { celdas: ['Valor social de la espera', n(cu.valor_espera, 0) + ' COP/h'] }, { celdas: ['Elasticidad β para valorar', n(cu.beta, 2)] },
    ];
    const ae = valor('resultado_ahorros_por_escenario', null, null);
    let tAe = '';
    if (ae) {
      const pAe = popoverId('resultado_ahorros_por_escenario', 'ahorros por escenario');
      const filas = Object.keys(ae).map(function (k) { const x = ae[k]; return { celdas: [esc(x.escenario || k), s(x.neto_pago_por_hora, 0), Array.isArray(x.rango) ? s(x.rango[0], 0) + ' a ' + s(x.rango[1], 0) : '—', num(x.neto_producido) ? s(x.neto_producido, 0) : '—', num(x.neto_simetrico) ? s(x.neto_simetrico, 0) : '—', num(x.pax_perdidos_dia) ? n(x.pax_perdidos_dia, 0) : '—'] }; });
      tAe = tabla('Los ' + n(filas.length, 0) + ' escenarios revalorados con costos de fuente pública (M COP/año; pasajeros por día)', ['Escenario', 'Saldo, pago por hora', 'Rango bajo a alto', 'Saldo, pago por producido', 'Saldo simétrico', 'En riesgo por día'], filas, { compacta: true, textoEn: [2] }) + '<p class="texto-3 pequeno">' + botonFuente(pAe, 'Fuente') + '</p>';
    }
    const be = valor('resultado_beta_equilibrio', null, null);
    let tBe = '';
    if (be) {
      const pBe = popoverId('resultado_beta_equilibrio', 'β de equilibrio');
      const c = function (y) { return num(y) ? n(y, 2) : esc(y); };
      const filas = Object.keys(be).map(function (k) { const x = be[k]; return { celdas: [esc(k), typeof x === 'object' ? c(x.hora) : c(x), typeof x === 'object' ? c(x.producido) : '—', typeof x === 'object' ? c(x.supuestos_D5) : '—'] }; });
      tBe = tabla('β a partir de la cual cada escenario deja de pagar', ['Escenario', 'Pago por hora', 'Pago por producido', 'Supuestos de D5'], filas, { compacta: true }) + '<p class="texto-3 pequeno">Con los supuestos antiguos de D5 el recorte parecía pagar hasta β = ' + (be.D5 && typeof be.D5 === 'object' ? c(be.D5.supuestos_D5) : '—') + '; con costos de fuente pública, solo hasta ' + (be.D5 && typeof be.D5 === 'object' ? c(be.D5.hora) : '—') + '. ' + botonFuente(pBe, 'Fuente') + '</p>';
    }
    const tn = valor('resultado_tornado_d5', null, null);
    let tTn = '';
    if (tn && Array.isArray(tn.filas)) {
      const pTn = popoverId('resultado_tornado_d5', 'tornado de D5');
      const filas = tn.filas.map(function (x) { const r = num(x.rango_Mcop) ? x.rango_Mcop : Math.abs(x.neto_con_alto_Mcop - x.neto_con_bajo_Mcop); return { r: r, celdas: [esc(x.parametro) + ' (' + numParam(x.valor_bajo) + ' a ' + numParam(x.valor_alto) + ')', s(x.neto_con_bajo_Mcop, 0), s(x.neto_con_alto_Mcop, 0), n(r, 0)] }; })
        .sort(function (p, q) { return q.r - p.r; });
      // La fila de β del tornado sale de la curva ajustada; al lado, el saldo exacto de la sensibilidad con la β alta.
      const sensA = valor('resultado_sensibilidad_beta', 'a', null);
      const filaB = tn.filas.filter(function (x) { return x.clave === 'beta'; })[0];
      const iB = filaB && sensA && Array.isArray(sensA.beta) && Array.isArray(sensA.neto_hora_Mcop) ? sensA.beta.indexOf(filaB.valor_alto) : -1;
      const notaB = iB >= 0 && num(sensA.neto_hora_Mcop[iB]) ? 'La fila de β usa una curva ajustada a las corridas; calculado exacto, con β = ' + n(filaB.valor_alto, 2) + ' el saldo es ' + s(sensA.neto_hora_Mcop[iB], 0) + ' ' + botonFuente(popRuta('resultado_sensibilidad_beta', 'a.neto_hora_Mcop', 'saldo exacto según β, plan (a)')) + '. ' : '';
      tTn = tabla('Qué parámetro mueve más el saldo del plan que recorta (M COP/año' + (num(tn.neto_central_Mcop) ? '; central ' + s(tn.neto_central_Mcop, 0) : '') + ')', ['Parámetro (bajo a alto)', 'Saldo con el bajo', 'Saldo con el alto', 'Rango'], filas, { compacta: true }) + '<p class="texto-3 pequeno">Ordenado por el rango: lo que más mueve el saldo va primero. ' + notaB + botonFuente(pTn, 'Fuente') + '</p>';
    }
    const ver = valor('resultado_verificaciones_costos', null, null) || {};
    const pVer = popoverId('resultado_verificaciones_costos', 'verificaciones');
    const textoVer = (num(ver.celdas_excel) ? n(ver.celdas_excel, 0) + ' celdas de la hoja de cálculo reproducidas' : '') + (num(ver.cifras_informe) ? (num(ver.celdas_excel) ? ' y ' : '') + n(ver.cifras_informe, 0) + ' cifras del informe recalculadas' : '') + ', con diferencias relativas del orden del redondeo de la máquina';
    const e7 = valor('resultado_e7_netos_supuestos', null, null);
    const pE7 = e7 ? popoverId('resultado_e7_netos_supuestos', 'saldos de E7 (historia)') : null;
    const textoE7 = e7 && e7.netos ? 'Historia: los saldos de E7 con los supuestos antiguos (' + Object.keys(e7.netos).map(function (k) { return esc(k) + ' ' + s(e7.netos[k], 0); }).join(', ') + ' M COP/año) quedaron superados por los costos de fuente pública y no se usan. ' + botonFuente(pE7, 'fuente') : '';
    const plan_ = valor('resultado_d5_reoptimizado', null, {}) || {};
    const nombreB = plan_.b_D5_reoptimizado_e05 && plan_.b_D5_reoptimizado_e05.corrida ? ' (' + esc(plan_.b_D5_reoptimizado_e05.corrida) + ')' : '';
    const cuerpo = '<p><strong>Ahorro de operación</strong> = kilómetros que se dejan de recorrer × costo evitable por km + buses-hora que se dejan de operar × costo del conductor por bus-hora (pago por hora). <strong>Pasajes perdidos</strong> = pasajeros en riesgo por día × tarifa neta × días del año. <strong>Saldo conservador</strong> = ahorro − pasajes perdidos. <strong>Saldo simétrico</strong> = el mismo, sumando los pasajeros ganados donde se añaden salidas, valorados a la misma tarifa.</p>' +
      '<p><strong>Pasajeros en riesgo</strong> por franja = pasajeros de la franja × β × (salidas quitadas ÷ salidas de hoy), con β = ' + n(cu.beta, 2) + ' de E7; la simulación lo hace para cada día de ' + ANIO + ' con la demanda real de ese día y los dos planes.</p>' +
      '<ol><li>Costos unitarios de ' + ANIO_SIGUE + ' con fuente pública (precio del ACPM, salario mínimo, tarifa, rendimiento del sistema).</li><li>Línea base: la operación real de ' + ANIO + ' (viajes válidos) valorada a esos precios.</li><li>Plan (b): D5 vuelto a optimizar con esos costos y el pronóstico a una semana' + nombreB + '; plan (a): D5 original revalorado.</li><li>Simulación de cada día de ' + ANIO + '; agregados por tipo de día, mes y año; sensibilidad a β y tornado.</li><li>Verificación: ' + textoVer + '. ' + botonFuente(pVer, 'fuente') + '</li></ol>' +
      tabla('Costos unitarios de ' + ANIO_SIGUE + ' con fuente', ['Rubro', 'Valor'], filasCu, { compacta: true }) + '<p class="texto-3 pequeno">' + botonFuente(pCu, 'Fuente') + '</p>' + tAe + tBe + tTn + (textoE7 ? '<p class="texto-3 pequeno">' + textoE7 + '</p>' : '');
    return '<details class="desplegable" id="res-como"><summary class="desplegable__resumen">' + icono('chevron-derecha', 'icono desplegable__chevron') + 'Ver cómo se calculó</summary><div class="desplegable__cuerpo">' + cuerpo + '</div></details>';
  }

  function seccionFuentes() {
    const items = Object.keys(archivosUsados).sort().map(function (a) { return '<li>' + chipVerificado(archivosUsados[a], true) + '<code>' + esc(a) + '</code></li>'; });
    const meta = (D && D.meta) || {};
    return seccion('res-fuentes', 'Fuentes', 'Archivos de resultados de los que sale cada cifra de esta pantalla (rutas relativas a la raíz del proyecto) y si un revisor independiente los recalculó. El botón «fuente» de cada cifra da el archivo, la clave y la revisión.',
      '<ul class="resultado__fuentes">' + items.join('') + '</ul><p class="texto-3 pequeno">' + (meta.generado ? 'Datos generados el ' + esc(meta.generado) + (meta.generador ? ' por ' + esc(meta.generador) : '') + (meta.verificador ? ' y comprobados por ' + esc(meta.verificador) : '') + '. ' : '') + 'La base de datos de Sobusa es compartida y de solo lectura: la app no la consulta.</p>');
  }

  // ---- Gráficos --------------------------------------------------------------------------------------------------
  function estiloBarra(rol, t) {
    if (rol === 'hoy') return { color: t.serieHoy, borderRadius: [0, 4, 4, 0] };
    if (rol === 'b') return { color: t.serieModelo, borderRadius: [0, 4, 4, 0] };
    if (rol === 'a') return { color: t.superficie2, borderColor: t.serieModelo, borderWidth: 1.5, borderRadius: [0, 4, 4, 0] };
    if (rol === 'oraculo') return { color: 'transparent', borderColor: t.serieOraculo, borderWidth: 1.5, borderType: 'dashed', borderRadius: [0, 4, 4, 0] };
    return {};
  }
  function opcionFaceta(categorias, valores, roles, unidad, dec, t) {
    return {
      grid: { left: 4, right: 64, top: 4, bottom: 4, containLabel: true },
      tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, valueFormatter: function (v) { return n(v, dec) + ' ' + unidad; } },
      xAxis: { type: 'value', min: 0, axisLabel: { show: false }, splitLine: { show: false } },
      yAxis: { type: 'category', data: categorias, inverse: true, axisLine: { show: false }, axisTick: { show: false }, axisLabel: { color: t.tinta2, fontSize: 12 } },
      series: [{ type: 'bar', barWidth: 16, barCategoryGap: '30%', data: valores.map(function (v, i) { return { value: num(v) ? v : 0, itemStyle: estiloBarra(roles[i], t) }; }),
        label: { show: true, position: 'right', color: t.tinta2, fontSize: 12, formatter: function (p) { return num(valores[p.dataIndex]) ? n(valores[p.dataIndex], dec) : '—'; } } }],
    };
  }
  function pintarFacetasAnuales(t) {
    const cats = ['Hoy', 'Reasigna (b)', 'Recorta (a)'];
    ['salidas', 'buses_hora', 'espera', 'sobrecap', 'riesgo'].forEach(function (c) {
      const f = fichas.filter(function (x) { return x.clave === c; })[0];
      const el = cont.querySelector('#res-g-facetas [data-faceta="' + c + '"]');
      if (!f || !el) return;
      const g = global.TEMA_ECHARTS.init(global.echarts, el);
      g.setOption(opcionFaceta(cats, [f.hoy.v, f.b.v, f.a.v], ['hoy', 'b', 'a'], f.unidad, f.dec, t));
      graficos['faceta_' + c] = g;
    });
  }
  function pintarFacetasBacktest(t) {
    const bt = graficos._bt;
    if (!bt) return;
    const cats = ['Hoy', 'Plan semanal', 'Oráculo'];
    bt.metricas.forEach(function (m) {
      const el = cont.querySelector('#res-g-backtest [data-faceta="' + m.clave + '"]');
      if (!el) return;
      const g = global.TEMA_ECHARTS.init(global.echarts, el);
      g.setOption(opcionFaceta(cats, [bt.hoy[m.campo], bt.plan[m.campo], bt.oraculo[m.campo]], ['hoy', 'b', 'oraculo'], m.unidad, m.dec, t));
      graficos[m.clave] = g;
    });
  }
  function pintarMes(t) {
    const mes = graficos._mes;
    const el = cont.querySelector('#res-g-mes-lienzo');
    if (!mes || !el) return;
    const g = global.TEMA_ECHARTS.init(global.echarts, el);
    g.setOption({
      legend: { show: false, data: ['Conservadora', 'Simétrica'] },
      tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, valueFormatter: function (v) { return s(v, 0, 'M COP'); } },
      xAxis: { type: 'category', data: mes.nombres },
      yAxis: { type: 'value', name: 'M COP/mes', nameLocation: 'end', nameGap: 12, axisLabel: { formatter: function (v) { return s(v, 0); } } },
      series: [
        { name: 'Conservadora', type: 'bar', data: mes.b.neto_hora_Mcop, itemStyle: { color: t.serieModelo, borderRadius: 4 } },
        { name: 'Simétrica', type: 'bar', data: mes.b.neto_hora_simetrica_Mcop, itemStyle: { color: t.serieModelo, borderRadius: 4, decal: { symbol: 'rect', symbolSize: 1, dashArrayX: [1, 0], dashArrayY: [2, 3], rotation: Math.PI / 4, color: t.superficie } } },
      ],
    });
    graficos.mes = g;
    ligarLeyenda(cont.querySelector('#res-g-mes .leyenda'), function () { return graficos.mes; });
  }
  function pintarBeta(t) {
    const b = graficos._beta;
    const el = cont.querySelector('#res-g-beta-lienzo');
    if (!b || !el) return;
    const g = global.TEMA_ECHARTS.init(global.echarts, el);
    const puntos = function (arr) { return b.betas.map(function (x, i) { return [x, arr[i]]; }); };
    g.setOption({
      legend: { show: false, data: ['Reasigna (b)', 'Recorta (a)'] },
      tooltip: { trigger: 'axis', valueFormatter: function (v) { return s(v, 0, 'M COP/año'); } },
      xAxis: { type: 'value', min: b.betas[0], max: b.betas[b.betas.length - 1], name: 'β', nameLocation: 'end', nameGap: 8, axisLabel: { formatter: function (v) { return n(v, 2); } }, splitLine: { show: false } },
      yAxis: { type: 'value', name: 'M COP/año', nameLocation: 'end', nameGap: 12, axisLabel: { formatter: function (v) { return s(v, 0); } } },
      series: [
        Object.assign({ name: 'Reasigna (b)', type: 'line', data: puntos(b.sens.b.neto_hora_Mcop), showSymbol: true, z: 3 }, global.TEMA_ECHARTS.serie('modelo')),
        Object.assign({ name: 'Recorta (a)', type: 'line', data: puntos(b.sens.a.neto_hora_Mcop), showSymbol: true, z: 2,
          markLine: { silent: true, symbol: 'none', lineStyle: { color: t.tinta3, type: 'dashed', width: 1 }, label: { color: t.tinta2, fontSize: 11 },
            data: [{ yAxis: 0, label: { show: false } }, { xAxis: b.betaEq, label: { formatter: 'β = ' + n(b.betaEq, 2), position: 'insideEndTop' } }, { xAxis: b.beta, label: { formatter: 'β = ' + n(b.beta, 2), position: 'insideEndTop' } }] } }, global.TEMA_ECHARTS.serie('motor')),
      ],
    });
    graficos.beta = g;
    ligarLeyenda(cont.querySelector('#res-g-beta .leyenda'), function () { return graficos.beta; });
  }
  function destruirGraficos() {
    Object.keys(graficos).forEach(function (k) { if (k.charAt(0) !== '_' && graficos[k] && graficos[k].dispose) { graficos[k].dispose(); delete graficos[k]; } });
  }
  function pintarGraficos() {
    if (!global.echarts || !global.TEMA_ECHARTS) { cont.querySelectorAll('.grafico').forEach(function (fig) { const b = fig.querySelector('[data-tabla-gemela]'); const t = fig.querySelector('.grafico__tabla'); if (b && t && t.hidden) b.click(); }); return; }
    destruirGraficos();
    const t = global.TEMA_ECHARTS.tokens();
    pintarFacetasAnuales(t);
    pintarFacetasBacktest(t);
    pintarMes(t);
    pintarBeta(t);
  }

  // ---- Tabla gemela y módulo -------------------------------------------------------------------------------------
  function ligarTablas() {
    cont.querySelectorAll('[data-tabla-gemela]').forEach(function (b) {
      const fig = b.closest('.grafico');
      const lienzo = fig.querySelector('.grafico__lienzo');
      const tab = fig.querySelector('.grafico__tabla');
      const ley = fig.querySelector('.leyenda');
      b.addEventListener('click', function () {
        const mostrar = tab.hidden;
        tab.hidden = !mostrar; lienzo.hidden = mostrar; if (ley) ley.hidden = mostrar;
        b.querySelector('[data-texto]').textContent = mostrar ? 'Ver gráfico' : 'Ver tabla';
        if (!mostrar) global.dispatchEvent(new Event('resize'));
      });
    });
  }
  function montarModulo() {
    const cuerpo = cont.querySelector('#res-modulo-cuerpo');
    if (!cuerpo || cuerpo.querySelector('iframe')) return;
    const marco = document.createElement('iframe');
    marco.className = 'modulo__marco';
    marco.title = 'Simulador de ahorro por fecha';
    marco.src = 'simulador_ahorro.html?embebido=1#fecha&plan=b';
    const estado = cont.querySelector('#res-modulo-estado');
    const cargando = cont.querySelector('#res-modulo-cargando');
    const listo = function () { if (cargando) cargando.hidden = true; if (estado) estado.textContent = 'Plan (b), todas las rutas; cambia la fecha o los parámetros'; };
    marco.addEventListener('load', function () { listo(); try { marco.contentWindow.postMessage({ tipo: 'tema', tema: 'light' }, '*'); } catch (e) { /* origen opaco */ } });   // solo modo claro
    const oyente = function (ev) { if (ev.source === marco.contentWindow && ev.data && ev.data.tipo === 'listo') listo(); };
    global.addEventListener('message', oyente);
    limpiezas.push(function () { global.removeEventListener('message', oyente); });
    if (cargando) cargando.hidden = false;
    if (estado) estado.textContent = 'Cargando…';
    cuerpo.insertBefore(marco, cuerpo.firstChild);
    graficos._marco = marco;
  }
  function vigilarModulo() {
    const mod = cont.querySelector('#res-modulo');
    if (!mod) return;
    if (!('IntersectionObserver' in global)) { montarModulo(); return; }
    const io = new IntersectionObserver(function (entradas) { if (entradas.some(function (e) { return e.isIntersecting; })) { montarModulo(); io.disconnect(); } }, { rootMargin: '300px 0px' });
    io.observe(mod);
    limpiezas.push(function () { io.disconnect(); });
  }

  // ---- Contrato de la pantalla ----------------------------------------------------------------------------------
  function render(contenedor, datos, estado) {
    salir();
    cont = contenedor; D = datos || global.DATOS_APP || {};
    escenario = escenarioDe(estado);
    plan = estado && estado.plan === 'a' ? 'a' : 'b';
    faltantes = []; archivosUsados = {}; nPop = 0; graficos = {};
    estilos();
    cont.innerHTML = '<div id="res-popovers"></div>';
    const partes = [];
    partes.push(seccionDia());
    partes.push(seccionCanje());
    partes.push(seccionCorridas());
    partes.push(seccionPorFecha());
    partes.push(seccionConductores());
    partes.push(seccionBacktest());
    partes.push(seccionPersona());
    partes.push(seccionNoPrometemos());
    partes.push(seccionLimites());
    partes.push(seccionComoSeCalculo());
    partes.push(seccionFuentes());
    const cab = faltantes.length ? aviso('atencion', 'Faltan datos en app/datos_app.js', '<p>Esta pantalla no encontró ' + n(faltantes.length, 0) + ' ids: <code>' + faltantes.map(esc).join('</code>, <code>') + '</code>. Donde faltan se muestra «—».</p>') : '';
    cont.insertAdjacentHTML('beforeend', '<div class="pila pila--ancha" id="res-cuerpo">' + cab + partes.join('') + '</div>');
    pintarFichas(false);
    global.COMPONENTES.fuentes(cont);
    global.COMPONENTES.cifras(cont);
    ligarTablas();
    const sel = cont.querySelector('#res-plan');
    global.COMPONENTES.segmentado(sel, function (v) {
      plan = v; pintarFichas(true); refrescarTablaOperacion();
      if (global.app && typeof global.app.ponerEstado === 'function') global.app.ponerEstado({ plan: v });
    });
    pintarGraficos();
    const vigilante = new ResizeObserver(function () { Object.keys(graficos).forEach(function (k) { if (k.charAt(0) !== '_' && graficos[k] && graficos[k].resize) graficos[k].resize(); }); });
    cont.querySelectorAll('.resultado__faceta-lienzo, .grafico__lienzo').forEach(function (el) { vigilante.observe(el); });
    limpiezas.push(function () { vigilante.disconnect(); });
    vigilarModulo();
  }
  function escenarioDe(estado) { return estado && (estado.escenario === 'modelo' || estado.escenario === 'oraculo') ? estado.escenario : 'hoy'; }
  function refrescarTablaOperacion() {
    const caja = cont.querySelector('#res-tabla-operacion');
    if (caja) caja.innerHTML = tablaOperacion();
  }
  function actualizar(estado) {
    if (!cont) return;
    const nuevo = escenarioDe(estado);
    const nuevoPlan = estado && estado.plan === 'a' ? 'a' : 'b';
    if (nuevoPlan !== plan) {
      plan = nuevoPlan;
      const r = cont.querySelector('#res-plan input[value="' + plan + '"]');
      if (r) r.checked = true;
      refrescarTablaOperacion();
      if (nuevo === escenario) pintarFichas(true);
    }
    if (nuevo !== escenario) { escenario = nuevo; pintarFichas(true); }
  }
  function salir() {
    destruirGraficos();
    limpiezas.forEach(function (f) { try { f(); } catch (e) { /* nada */ } });
    limpiezas = [];
  }

  const definicion = {
    id: ID,
    pregunta: '¿Qué gana Sobusa?',
    subtitulo: 'El plan que reasigna pone menos pasajeros de pie y los hace esperar casi lo mismo, con casi los mismos buses; en plata, el saldo cambia de signo según cómo se cuenten los pasajeros ganados.',
    icono: 'resultado',
    interruptor: [
      { valor: 'hoy', tooltip: 'Lo que Sobusa hizo en ' + ANIO },
      { valor: 'modelo', tooltip: 'El plan del modelo; abajo se elige entre el que reasigna y el que recorta' },
      { valor: 'oraculo', tooltip: 'Otra base: los días del backtest (no hay oráculo del año con costos de fuente pública)' },
    ],
    modulo: null,
    render: render,
    actualizar: actualizar,
    salir: salir,
  };
  // app.html define registrarPantalla antes de cargar las pantallas; si no existiera, se deja en la misma cola que lee app.js.
  if (typeof global.registrarPantalla === 'function') global.registrarPantalla(definicion);
  else (global.__pantallasRegistradas = global.__pantallasRegistradas || []).push(definicion);
})(window);
