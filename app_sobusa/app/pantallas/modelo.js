// Sobusa Despacho · pantallas/modelo.js
// Pantalla «Modelo · ¿Qué modelo es y por qué?». Muestra los dos modelos de pronóstico de pasajeros frente a la
// regla manual de Sobusa: el modelo final de E11 (LightGBM V4) y el híbrido de E12 (el mismo LightGBM con las
// variables de Chronos-2, recomendado para producción).
//
// Datos: todo sale de window.DATOS_APP.pantallas.modelo, que trae los ids modelo_* del inventario de cifras
// ({valor, unidad, decimales, archivo, clave, experimento, verificado, revision}) y, en .ficha, la ficha completa
// de los dos modelos (estructura de ficha_modelos.json: comun, convenciones, modelos.E11_V4, modelos.E12_hibrido,
// comparacion_E12, avisos_y_contradicciones). Ninguna cifra está escrita aquí: los textos con números se arman
// con los valores de los datos y cada cifra lleva su botón «fuente» (archivo, clave, experimento y revisor).
//
// Contrato: registrarPantalla({...}) de DISEÑO.md §5.1. El interruptor Hoy / Con el modelo / Oráculo no aplica
// (interruptor: []); en su lugar hay un interruptor secundario «Modelo final (E11) / Híbrido (E12)» que cambia las
// fichas de detalle y sigue estado.modelo ('final' | 'hibrido'). Los gráficos usan el tema de ECharts, llevan
// role="img" con aria-label y tabla gemela, y usan siempre el tema claro.
(function (global) {
  'use strict';

  // Claves de la ficha para cada modelo y rótulos cortos.
  const CLAVE = { final: 'E11_V4', hibrido: 'E12_hibrido' };
  const EXP = { final: 'E11', hibrido: 'E12' };
  const NOMBRE = { final: 'Modelo final (E11)', hibrido: 'Híbrido (E12)' };
  // Etiquetas de los periodos de evaluación (son rótulos de los datos, no resultados).
  const ANIO_EVAL = '2025';
  const ANIO_PRUEBA = '2024';

  let D = null;            // DATOS_APP.pantallas.modelo
  let INI = null;          // DATOS_APP.pantallas.inicio: las tres cifras de cabecera (regla manual, final, híbrido) con todos sus decimales
  let FI = null;           // D.ficha
  let CONTRA = null;       // DATOS_APP.contradicciones (si el generador las trae)
  let cont = null;         // div.pantalla
  let estadoApp = null;
  let modeloActual = 'hibrido';
  let popovers = null;     // contenedor de los popovers de fuente
  let popMapa = null;      // clave → id del popover (para no duplicar)
  let nPop = 0;
  let lienzos = {};        // id → { el, opcion }
  let graficos = {};       // id → gráfico de ECharts
  let vigilante = null;    // ResizeObserver
  let mq = null;           // matchMedia del teléfono
  let mqOyente = null;

  // ---- Utilidades ---------------------------------------------------------------------------------------------
  function F() { return global.COMPONENTES.formato; }
  function icono(nombre, clase) { return global.ICONOS ? global.ICONOS.svg(nombre, clase) : ''; }
  function esc(s) { return String(s === null || s === undefined ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'); }
  function md(s) { return esc(s).replace(/`([^`]+)`/g, '<code>$1</code>'); }
  function g(o, ruta, defecto) {
    let v = o;
    const partes = String(ruta).split('.');
    for (let i = 0; i < partes.length; i++) { if (v === null || v === undefined) return defecto; v = v[partes[i]]; }
    return v === undefined ? defecto : v;
  }
  function esNum(v) { return typeof v === 'number' && !isNaN(v); }
  function num(v, dec) { return esNum(v) ? F().numero(v, dec || 0) : (v === null || v === undefined ? '—' : String(v)); }
  function pct(v, dec) { return esNum(v) ? F().numero(v, dec === undefined ? 2 : dec) + ' %' : num(v); }
  function sig(v, dec, unidad) { return esNum(v) ? F().signo(v, dec || 0, unidad) : num(v); }
  function dec(v) { // decimales que trae la fuente (como mucho 2)
    if (!esNum(v)) return 0;
    const s = String(v); const i = s.indexOf('.');
    return i < 0 ? 0 : Math.min(2, s.length - i - 1);
  }
  function claves(o) { return o && typeof o === 'object' ? Object.keys(o) : []; }
  // El peso va en el nombre de la clave del archivo (filas_peso_0_25 → 0,25): se lee de ahí, no se escribe a mano.
  function claveCon(o, prefijo) { return claves(o).filter(function (k) { return k.indexOf(prefijo) === 0; })[0]; }
  function pesoDeClave(o, prefijo) { const k = claveCon(o, prefijo); const n = k ? parseFloat(k.slice(prefijo.length).replace('_', '.')) : NaN; return esNum(n) ? num(n, dec(n)) : '—'; }
  function cifra(id) {
    if (D && D[id]) return D[id];
    if (INI && INI[id]) return INI[id];
    const P = global.DATOS_APP && global.DATOS_APP.pantallas;   // cifras de otras pantallas (Demanda, Método) que Modelo cita
    if (P) for (const k in P) if (P[k] && P[k][id] && k !== 'modelo') return P[k][id];
    return null;
  }
  function valor(id, ruta) { const c = cifra(id); if (!c) return undefined; return ruta ? g(c.valor, ruta) : c.valor; }
  function horizonteNumero(clave) { return parseInt(String(clave).replace(/\D/g, ''), 10); }
  function horizontes() { return claves(g(FI, 'modelos.E11_V4.errores.por_antelacion.V4', {})).map(horizonteNumero); }
  function hPrincipal() { const hs = horizontes(); return hs.length ? hs[0] : null; }
  function mesNombre(k) { const M = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre']; const i = parseInt(k, 10) - 1; return M[i] || String(k); }
  function rutaClase(r) { return r === 'SILENCIO' ? 'silencio' : r === 'CRA 54' ? 'cra54' : r === 'CL 72' ? 'cl72' : null; }

  // ---- Fuentes y popovers -------------------------------------------------------------------------------------
  // Revisión que respalda cada entrada de la ficha, según el experimento y si el revisor recalculó esa parte.
  function revision(ver) {
    const v11 = g(FI, 'modelos.E11_V4.verificacion', {}), v12 = g(FI, 'modelos.E12_hibrido.verificacion', {});
    const r11 = 'Revisión independiente de E11 del ' + F().fecha(v11.fecha) + ': ' + (v11.veredicto || '');
    const r12 = 'Revisión independiente de E12 del ' + F().fecha(v12.fecha) + ': ' + (v12.veredicto || '');
    switch (ver) {
      case 'E11': return { verificado: 'sí', revision: r11 };
      case 'E12': return { verificado: 'sí', revision: r12 };
      case 'E11E12': return { verificado: 'sí', revision: r11 + ' · ' + r12 };
      case 'parcial': return { verificado: 'parcial', revision: 'Cifra del autor (tiempos o conteos de su máquina); el revisor no la recalculó' };
      default: return { verificado: 'no', revision: 'Dato del autor, sin revisor independiente' };
    }
  }
  // Fuente de un id del inventario (el generador trae archivo, clave, experimento, verificado y revisión).
  // El texto de E12 sobre por qué el híbrido nombra variantes internas (V4, «(a)», NNLS, TFT): se dice en llano.
  function porQueLlano(t) {
    t = String(t || '');
    const i = t.indexOf('. (a)');
    const base = (i > 0 ? t.slice(0, i + 1) : t).replace(/al de V4/g, 'al del modelo final').replace(/V4/g, 'el modelo final');
    return i > 0 ? base + ' Las otras candidatas rinden igual con más piezas y más sesgo, o no se sostuvieron en ' + ANIO_PRUEBA + '; el ganador formal exige muchos más modelos y no se pudo validar en otro año.' : base;
  }
  function fId(id, titulo) {
    const c = cifra(id);
    if (!c) return { archivo: 'sin datos: ' + id, clave: '—', experimento: '—', verificado: 'no', revision: 'El generador de datos no trajo esta cifra', titulo: titulo || id };
    return { archivo: c.archivo, clave: c.clave, experimento: c.experimento, verificado: c.verificado, revision: c.revision, nota: c.nota, titulo: titulo || c.que_es };
  }
  // Fuente de una sola parte de una cifra (su archivo y su clave, tomados de «origen»), para no citar claves de otra parte.
  function fIdParte(id, parte, titulo) {
    const f = fId(id, titulo), c = cifra(id);
    const o = c && Array.isArray(c.origen) ? c.origen.filter(function (x) { return Array.isArray(x) && Array.isArray(x[0]) && x[0][x[0].length - 1] === parte; })[0] : null;
    if (o && o[1] && o[1].a) { f.archivo = o[1].a; f.clave = o[1].c || f.clave; }
    return f;
  }
  // Fuente de una entrada de la ficha: ruta_json («archivo: clave · archivo: clave») o fuente (README y secciones).
  function fFicha(entrada, exp, ver, titulo) {
    const rj = entrada && entrada.ruta_json, ft = entrada && entrada.fuente;
    let archivo = '—', clave = '—';
    if (rj) {
      const partes = String(rj).split(' · ').map(function (p) { const i = p.indexOf(': '); return i > 0 ? [p.slice(0, i), p.slice(i + 2)] : [p, '—']; });
      archivo = partes.map(function (p) { return p[0]; }).join(' y ');
      clave = partes.map(function (p) { return p[1]; }).join('; ');
    } else if (ft) {
      const m = /^(\S+\.(?:md|json|py|csv|txt|parquet))\b[,;]?\s*(.*)$/.exec(String(ft));
      archivo = m ? m[1] : String(ft);
      clave = m && m[2] ? m[2] : '—';
    }
    const r = revision(ver);
    return { archivo: archivo, clave: clave, experimento: exp, verificado: r.verificado, revision: r.revision, nota: rj && ft ? ft : null, titulo: titulo, verificador: 'app/verificar_ficha_modelos.py' };
  }
  function fTexto(fuenteTexto, exp, ver, titulo) { return fFicha({ fuente: fuenteTexto }, exp, ver, titulo); }
  function chipVerificado(ver) {
    const v = String(ver || 'no').toLowerCase();
    const clase = v === 'sí' || v === 'si' ? 'bien' : v === 'parcial' ? 'atencion' : 'critico';
    return '<span class="chip chip--' + clase + '">' + icono(clase === 'bien' ? 'bien' : 'alerta') + esc(ver || 'no') + '</span>';
  }
  function pop(src) {
    const clave = JSON.stringify([src.archivo, src.clave, src.experimento, src.verificado, src.titulo || '', src.queMide || '']);
    if (popMapa.has(clave)) return popMapa.get(clave);
    const id = 'modelo-f-' + (++nPop);
    const div = document.createElement('div');
    div.id = id; div.className = 'fuente-pop'; div.setAttribute('popover', '');
    div.innerHTML = '<div class="fuente-pop__cab"><span class="fuente-pop__titulo">' + icono('fuente') + 'Fuente' + (src.titulo ? ' · ' + esc(src.titulo) : '') + '</span>' +
      '<button class="boton boton--fantasma boton--icono boton--pequeno" type="button" data-cerrar aria-label="Cerrar">' + icono('cerrar') + '</button></div>' +
      '<dl class="fuente-pop__datos">' + (src.queMide ? '<dt>Qué mide</dt><dd>' + src.queMide + '</dd>' : '') + '<dt>Archivo</dt><dd><code>' + esc(src.archivo) + '</code></dd><dt>Clave</dt><dd>' + esc(src.clave) + '</dd>' +
      '<dt>Experimento</dt><dd>' + esc(src.experimento) + '</dd><dt>Revisor</dt><dd>' + chipVerificado(src.verificado) + (src.revision ? '<span class="texto-2">' + esc(src.revision) + '</span>' : '') + '</dd>' +
      (src.nota ? '<dt>Nota</dt><dd>' + md(src.nota) + '</dd>' : '') + '</dl>' +
      '<div class="fuente-pop__pie">Ninguna cifra está escrita a mano: ' + esc(src.verificador || 'app/verificar_datos_app.py') + ' compara este valor con el archivo.</div>';
    popovers.appendChild(div);
    popMapa.set(clave, id);
    return id;
  }
  function fte(src, etiqueta) {
    return '<button class="fuente" type="button" popovertarget="' + pop(src) + '" aria-expanded="false" aria-label="' + esc(etiqueta || 'Fuente de la cifra') + '">' + icono('fuente') + '</button>';
  }
  function fteT(src) {
    return '<button class="fuente fuente--texto" type="button" popovertarget="' + pop(src) + '" aria-expanded="false">' + icono('fuente') + 'Fuente</button>';
  }

  // ---- Piezas de HTML -----------------------------------------------------------------------------------------
  function p(texto, boton, clase) { return ph(md(texto), boton, clase); }
  // Párrafo con HTML ya armado (las partes de texto se escapan con esc o md antes de llegar aquí).
  function ph(html, boton, clase) { return '<p' + (clase ? ' class="' + clase + '"' : '') + '>' + html + (boton ? ' ' + boton : '') + '</p>'; }
  // Intervalo de confianza en es-CO: [−0,43; −0,22].
  function ic(inf, sup, d) { return esNum(inf) && esNum(sup) ? '[' + sig(inf, d === undefined ? 2 : d) + '; ' + sig(sup, d === undefined ? 2 : d) + ']' : ''; }
  // Diferencia en puntos con su intervalo: −0,32 puntos [−0,43; −0,22].
  function difIc(dif, inf, sup) { return esNum(dif) ? sig(dif, 2, 'puntos') + (ic(inf, sup) ? ' ' + ic(inf, sup) : '') : '—'; }
  function h4(t) { return '<h3 class="modelo__h4">' + esc(t) + '</h3>'; }
  function lista(items, ordenada) {
    const tag = ordenada ? 'ol' : 'ul';
    return '<' + tag + ' class="modelo__lista">' + items.map(function (it) { return '<li>' + it + '</li>'; }).join('') + '</' + tag + '>';
  }
  // El icono y el texto de la variación van en dos piezas para que el texto no se parta en varios hijos del flex.
  function envolverVariacion(html) { const i = html.indexOf('</svg>'); return i < 0 ? '<span>' + html + '</span>' : html.slice(0, i + 6) + '<span>' + html.slice(i + 6) + '</span>'; }
  function tarjetaCifra(o) {
    const unidad = o.unidad ? '<span class="cifra__unidad">' + esc(o.unidad) + '</span>' : '';
    const texto = esNum(o.valor) ? (o.signo ? sig(o.valor, o.decimales) : num(o.valor, o.decimales)) : esc(o.valor === undefined || o.valor === null ? '—' : o.valor);
    return '<article class="cifra' + (o.clase ? ' ' + o.clase : '') + '">' +
      '<header class="cifra__cab"><h3 class="cifra__etiqueta">' + esc(o.etiqueta) + '</h3>' + (o.fuente ? fte(o.nota ? Object.assign({}, o.fuente, { queMide: md(o.nota) }) : o.fuente) : '') + '</header>' +
      '<p class="cifra__valor"><span' + (esNum(o.valor) ? ' data-cifra="' + o.valor + '" data-decimales="' + (o.decimales || 0) + '"' : '') + '>' + texto + '</span>' + unidad + '</p>' +
      (o.variacion ? '<p class="cifra__variacion' + (o.variacionClase ? ' ' + o.variacionClase : '') + '">' + envolverVariacion(o.variacion) + '</p>' : '') +
      (o.nota && !o.fuente ? '<p class="cifra__nota">' + md(o.nota) + '</p>' : '') + '</article>';
  }
  function tabla(cab, filas, opciones) {
    const o = opciones || {};
    return '<div class="tabla-marco' + (o.marcoClase ? ' ' + o.marcoClase : '') + '"><table class="tabla' + (o.compacta ? ' tabla--compacta' : '') + '">' +
      (o.titulo ? '<caption>' + md(o.titulo) + '</caption>' : '') +
      '<thead><tr>' + cab.map(function (c) { return '<th scope="col"' + (c.num ? ' class="num"' : '') + '>' + md(c.texto) + '</th>'; }).join('') + '</tr></thead>' +
      '<tbody>' + filas.join('') + '</tbody></table></div>';
  }
  function fila(celdas, clase) { return '<tr' + (clase ? ' class="' + clase + '"' : '') + '>' + celdas.join('') + '</tr>'; }
  function td(contenido, clase) { return '<td' + (clase ? ' class="' + clase + '"' : '') + '>' + contenido + '</td>'; }
  function th(contenido) { return '<th scope="row">' + contenido + '</th>'; }
  // Celdas numéricas de una fila con el mejor valor (el menor) en el acento.
  function celdasMejor(valores, decs) {
    const nums = valores.filter(esNum);
    const min = nums.length ? Math.min.apply(null, nums) : null;
    return valores.map(function (v, i) { return td(esNum(v) ? pct(v, decs[i]) : esc(v === undefined || v === null ? '—' : v), 'num' + (esNum(v) && v === min && nums.length > 1 ? ' tabla__mejor' : '')); });
  }
  function clave(r) { const c = rutaClase(r); return c ? '<span class="tabla__clave"><span class="tabla__muestra" style="--c: var(--ruta-' + c + ')"></span>' + esc(r) + '</span>' : esc(r); }
  function aviso(tipo, titulo, cuerpo) {
    const ic = tipo === 'canje' ? 'canje' : tipo === 'bien' ? 'bien' : tipo === 'nota' ? 'info' : 'alerta';
    return '<div class="aviso' + (tipo && tipo !== 'nota' ? ' aviso--' + tipo : '') + '">' + icono(ic) + '<div class="aviso__cuerpo"><h3 class="aviso__titulo">' + esc(titulo) + '</h3>' + cuerpo + '</div></div>';
  }
  function barras(objeto, dec, maxFilas) {
    const ks = claves(objeto).slice(0, maxFilas || 99);
    const max = Math.max.apply(null, ks.map(function (k) { return objeto[k]; }).filter(esNum)) || 1;
    return '<div class="modelo__barras">' + ks.map(function (k) {
      return '<div class="modelo__barra"><span class="modelo__barra-nombre"><code>' + esc(k) + '</code></span><span class="modelo__barra-valor num">' + pct(objeto[k], dec) + '</span>' +
        '<span class="modelo__barra-pista"><span class="modelo__barra-relleno" style="width: ' + (100 * objeto[k] / max).toFixed(1) + '%"></span></span></div>';
    }).join('') + '</div>';
  }
  function chipsCodigo(nombres) { return '<div class="chips">' + nombres.map(function (v) { return '<span class="chip"><code>' + esc(v) + '</code></span>'; }).join('') + '</div>'; }
  function dl(pares) { return '<dl class="modelo__dl">' + pares.map(function (par) { return '<dt>' + esc(par[0]) + '</dt><dd>' + par[1] + '</dd>'; }).join('') + '</dl>'; }
  function figura(o) {
    // o: { id, titulo, sub, aria, series: [{nombre, rol, rayas}], tabla (html), nota, fuente (botón), opcion (fn) }
    lienzos[o.id] = { el: null, opcion: o.opcion };
    const leyenda = '<ul class="leyenda" id="' + o.id + '-leyenda">' + o.series.map(function (s) {
      const c = s.rol === 'hoy' ? 'var(--serie-hoy)' : 'var(--serie-modelo)';
      return '<li><button class="leyenda__item" type="button" data-serie="' + esc(s.nombre) + '" aria-pressed="true"><span class="leyenda__muestra leyenda__muestra--barra' + (s.rayas ? ' modelo__rayas' : '') + '" style="--c: ' + c + '"></span>' + esc(s.nombre) + '</button></li>';
    }).join('') + '</ul>';
    return '<figure class="grafico" id="' + o.id + '-figura">' +
      '<figcaption class="grafico__cab"><div class="grafico__titulos"><h3 class="grafico__titulo">' + esc(o.titulo) + '</h3><p class="grafico__sub">' + md(o.sub) + '</p></div>' +
      '<div class="grafico__acciones"><button class="boton boton--secundario boton--pequeno" type="button" data-ver-tabla data-texto-tabla="Ver tabla" data-texto-grafico="Ver gráfico">' + icono('tabla') + '<span data-texto>Ver tabla</span></button></div></figcaption>' +
      leyenda +
      '<div class="grafico__lienzo' + (o.bajo ? ' grafico__lienzo--bajo' : '') + '" id="' + o.id + '" role="img" aria-label="' + esc(o.aria) + '"></div>' +
      '<div class="grafico__tabla tabla-marco" hidden>' + o.tabla + '</div>' +
      '<div class="grafico__pie"><span>' + md(o.nota || '') + '</span>' + (o.fuente || '') + '</div></figure>';
  }

  // ---- Gráficos de barras (ECharts) ---------------------------------------------------------------------------
  function conAlfa(hex, alfa) {
    const m = /^#([0-9a-f]{6})$/i.exec(String(hex || '').trim());
    if (!m) return hex;
    const n = parseInt(m[1], 16);
    return 'rgba(' + (n >> 16) + ', ' + ((n >> 8) & 255) + ', ' + (n & 255) + ', ' + alfa + ')';
  }
  // series: [{ nombre, rol: 'hoy' | 'final' | 'hibrido', datos: [], dec }]
  function opcionBarras(categorias, series, nombreEje) {
    return function () {
      const T = global.TEMA_ECHARTS, t = T.tokens();
      const decs = {};
      series.forEach(function (s) { decs[s.nombre] = s.dec; });
      return {
        legend: { show: false, data: series.map(function (s) { return s.nombre; }) },
        tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, formatter: function (ps) {
          return '<strong>' + esc(ps[0].axisValueLabel) + '</strong><br>' + ps.map(function (q) { return q.marker + esc(q.seriesName) + ': ' + pct(q.value, decs[q.seriesName]); }).join('<br>');
        } },
        grid: { left: 8, right: 12, top: 28, bottom: 8, containLabel: true },
        xAxis: { type: 'category', data: categorias, axisLabel: { interval: 0, hideOverlap: true } },
        yAxis: { type: 'value', name: nombreEje || '% de pasajeros mal estimados', nameLocation: 'end', nameGap: 12, nameTextStyle: { align: 'left' }, axisLabel: { formatter: function (v) { return num(v, 0); } } },
        series: series.map(function (s) {
          const base = { name: s.nombre, type: 'bar', data: s.datos };
          if (s.rol === 'hoy') return Object.assign(base, T.serie('hoy'));
          const est = Object.assign(base, T.serie('modelo'));
          if (s.rol === 'final') est.itemStyle = { color: t.serieModelo, decal: { symbol: 'rect', symbolSize: 1, dashArrayX: [1, 0], dashArrayY: [2, 4], rotation: Math.PI / 4, color: conAlfa(t.superficie, 0.55) } };
          return est;
        }),
      };
    };
  }
  function crearGrafico(id) {
    const L = lienzos[id];
    if (!L || !L.el || !L.el.clientWidth || !global.echarts) return;
    if (graficos[id]) graficos[id].dispose();
    graficos[id] = global.TEMA_ECHARTS.init(global.echarts, L.el);
    graficos[id].setOption(L.opcion());
  }

  // ---- Resumen: los dos modelos lado a lado ------------------------------------------------------------------
  // La ficha redondea a tres decimales; las de cabecera salen de los ids de Inicio, que traen el valor del archivo.
  function b1() { const v = valor('inicio_error_regla_manual'); return esNum(v) ? v : g(FI, 'comun.regla_manual_B1.wape_h7.valor'); }
  function wapeFinal() { const v = valor('inicio_error_modelo_final'); return esNum(v) ? v : g(FI, 'modelos.E11_V4.errores.global_h7.WAPE.valor'); }
  function wapeHibrido() { const v = valor('modelo_hibrido_wape_2025', 'WAPE'); return esNum(v) ? v : g(FI, 'modelos.E12_hibrido.errores.global_2025.WAPE.valor'); }
  function fB1() { if (cifra('inicio_error_regla_manual')) return fId('inicio_error_regla_manual', 'Regla manual (B1), WAPE a ' + hPrincipal() + ' días'); return fFicha(g(FI, 'comun.regla_manual_B1.wape_h7'), 'E11', 'E11', 'Regla manual (B1), WAPE a ' + hPrincipal() + ' días'); }
  function fFinal() { if (cifra('inicio_error_modelo_final')) return fId('inicio_error_modelo_final', 'Modelo final, WAPE a ' + hPrincipal() + ' días'); return fFicha(g(FI, 'modelos.E11_V4.errores.global_h7.WAPE'), 'E11', 'E11', 'Modelo final, WAPE a ' + hPrincipal() + ' días'); }

  function tarjetaModelo(m) {
    const X = FI.modelos[CLAVE[m]], E = X.errores || {};
    const h = hPrincipal();
    const w25 = m === 'final' ? wapeFinal() : wapeHibrido();
    const f25 = m === 'final' ? fFinal() : fId('modelo_hibrido_wape_2025');
    const w24 = m === 'final' ? valor('modelo_final_2024') : valor('modelo_hibrido_wape_2024', 'WAPE_hibrido');
    const f24 = fId(m === 'final' ? 'modelo_final_2024' : 'modelo_hibrido_wape_2024');
    const sesgo = m === 'final' ? g(E, 'global_h7.sesgo_pct.valor') : valor('modelo_hibrido_sesgo', '2025_pct');
    const fSesgo = m === 'final' ? fFicha(g(E, 'global_h7.sesgo_pct'), 'E11 / E12', 'E12', 'Sesgo del modelo final') : fIdParte('modelo_hibrido_sesgo', '2025_pct', 'Sesgo del híbrido, ' + ANIO_EVAL);
    const nVar = m === 'final' ? valor('modelo_final_variables', 'E11_h7') : g(X, 'variables.total.valor');
    const fVar = m === 'final' ? fId('modelo_final_variables') : fFicha(g(X, 'variables.total'), 'E12', 'E12', 'Variables del híbrido');
    const difB1 = esNum(w25) && esNum(b1()) ? w25 - b1() : null;
    const var24 = m === 'final'
      ? icono('igual') + 'Referencia de la prueba de ' + ANIO_PRUEBA + ' (la del híbrido se mide frente a esta)'
      : icono('flecha-abajo') + difIc(valor('modelo_hibrido_wape_2024', 'dif'), valor('modelo_hibrido_wape_2024', 'ic_inf'), valor('modelo_hibrido_wape_2024', 'ic_sup')) + ' frente al modelo final; mejor en ' + num(valor('modelo_hibrido_wape_2024', 'meses_mejor')) + ' meses';
    const costo = (g(FI, 'comparacion_E12.costo_y_riesgo.tabla', []) || []).filter(function (r) { return m === 'final' ? /E11/.test(r.modelo) : /H[ií]brido/.test(r.modelo); })[0];
    const fCosto = fFicha(g(FI, 'comparacion_E12.costo_y_riesgo'), 'E12', 'parcial', 'Costo y riesgo');
    const porQue = m === 'final' ? X.rol : porQueLlano(valor('modelo_por_que_hibrido'));
    const fPorQue = m === 'final' ? fTexto(g(X, 'que_es.fuente'), 'E11', 'E11', 'Papel del modelo final') : fId('modelo_por_que_hibrido');
    const papel = '<p class="modelo__papel" data-modelo-chip="' + m + '">' + esc(NOMBRE[m]) + ' · ' + (m === 'hibrido' ? 'recomendado para producción' : 'respaldo en producción') + '</p>';
    return '<article class="tarjeta modelo__tarjeta' + (m === 'hibrido' ? ' modelo__tarjeta--recomendado' : '') + '" id="modelo-tarjeta-' + m + '">' +
      '<div class="pila" style="gap: var(--e-1)"><h3>' + esc(X.nombre) + '</h3>' + papel + '</div>' +
      p(X.resumen_para_jurado, fteT(fTexto(g(X, 'que_es.fuente'), EXP[m], EXP[m], 'Qué es el ' + NOMBRE[m].toLowerCase())), 'prosa') +
      '<div class="cifras">' +
      tarjetaCifra({ etiqueta: 'Pasajeros mal estimados de cada 100, a ' + h + ' días (' + ANIO_EVAL + ')', valor: w25, unidad: '%', decimales: 2, fuente: f25,
        variacion: esNum(difB1) ? icono('flecha-abajo') + sig(difB1, 2, 'puntos') + ' frente a la regla manual (' + pct(b1()) + ')' : '', variacionClase: 'cifra__variacion--bien',
        nota: 'WAPE con h = ' + h + ', ' + num(g(FI, 'comun.protocolo_validacion.cifras.pliegues')) + ' pliegues mensuales, objetivo original (viajes válidos).' }) +
      tarjetaCifra({ etiqueta: 'En ' + ANIO_PRUEBA + ', prueba fuera de la muestra de selección', valor: w24, unidad: '%', decimales: 2, fuente: f24, variacion: var24,
        variacionClase: m === 'hibrido' ? 'cifra__variacion--bien' : '', nota: 'Mismo protocolo repetido en ' + ANIO_PRUEBA + ' (E12), ' + num(g(FI, 'comun.protocolo_validacion.cifras.franjas_prueba_2024.valor')) + ' franjas.' }) +
      tarjetaCifra({ etiqueta: 'Sesgo del total en ' + ANIO_EVAL, valor: sesgo, unidad: '%', decimales: 2, signo: true, fuente: fSesgo,
        nota: 'Positivo: se pasa un poco en el total del año. Para despachar, pasarse un poco es preferible a quedarse corto; conviene vigilarlo.' }) +
      tarjetaCifra({ etiqueta: 'Variables', valor: nVar, unidad: 'variables', decimales: 0, fuente: fVar,
        nota: m === 'final' ? 'Calendario, demanda reciente y oferta reciente; la ruta como categoría.' : 'Las del modelo final más ' + num(g(X, 'variables.grupo_nuevo.n')) + ' del pronóstico de Chronos-2.' }) +
      '</div>' +
      (costo ? '<div class="pila"><span class="rotulo">Costo y riesgo ' + fte(fCosto, 'Fuente de costo y riesgo') + '</span>' + dl([
        ['Modelos a mantener', esc(costo.modelos_a_mantener)], ['Librerías', esc(costo.librerias)], ['GPU', esc(costo.gpu)], ['Entrenamiento', esc(costo.entrenamiento)], ['Riesgo', esc(costo.riesgo)]]) + '</div>' : '') +
      '<div class="pila"><span class="rotulo">' + (m === 'hibrido' ? 'Por qué lo recomendamos' : 'Qué papel tiene') + '</span>' + p(porQue, fteT(fPorQue), 'pequeno texto-2') + '</div>' +
      '</article>';
  }

  function avisoGanador() {
    const c = cifra('modelo_comparacion_51');
    if (!c) return '';
    const v = c.valor || {};
    const w24 = cifra('modelo_hibrido_wape_2024') ? cifra('modelo_hibrido_wape_2024').valor : {};
    const texto = 'En la comparación ampliada de E12 (' + num(v.candidatos) + ' candidatos, ' + num(v.cumplen_regla) + ' cumplen la regla de selección) el ganador formal es ' +
      '<code>' + esc(v.ganador_formal) + '</code>, con ' + pct(v.ganador_WAPE) + ' (' + difIc(v.ganador_dif, v.ganador_ic_inf, v.ganador_ic_sup) + ' frente al modelo final). ' +
      'Recomendamos el híbrido, con ' + pct(wapeHibrido()) + ', porque es la única mejora que se sostuvo fuera de la muestra de selección: en ' + ANIO_PRUEBA + ' vuelve a ganarle al modelo final por ' +
      difIc(w24.dif, w24.ic_inf, w24.ic_sup) + ', con un costo casi igual y sin GPU. El ganador formal combina muchos modelos y no se pudo validar en otro año. El detalle está en «¿Qué se probó y se descartó?».';
    return aviso('canje', 'Canje: el ganador formal no es el recomendado', '<p>' + texto + ' ' + fteT(fId('modelo_comparacion_51')) + ' ' + fteT(fId('modelo_hibrido_wape_2024')) + ' ' + fteT(fId('modelo_por_que_hibrido')) + '</p>');
  }

  function htmlResumen() {
    const h = hPrincipal();
    const intro = 'Los dos pronostican lo mismo, pasajeros por ruta, día y hora de salida, y se evaluaron con el mismo protocolo: ' + num(g(FI, 'comun.protocolo_validacion.cifras.pliegues')) +
      ' pliegues mensuales de ' + ANIO_EVAL + ' con ' + h + ' días de antelación, frente a la regla manual de Sobusa, que se equivoca en ' + pct(b1()) + ' de los pasajeros.';
    const pestanas = '<div class="pestanas modelo__pestanas" role="tablist" aria-label="Modelo" id="modelo-pestanas">' +
      ['final', 'hibrido'].map(function (m) { return '<button class="pestana" role="tab" id="modelo-pestana-' + m + '" aria-selected="' + (m === modeloActual ? 'true' : 'false') + '" aria-controls="modelo-tarjeta-' + m + '" data-modelo="' + m + '">' + esc(NOMBRE[m]) + '</button>'; }).join('') + '</div>';
    return '<section class="seccion" aria-labelledby="modelo-resumen-t">' +
      '<div class="seccion__cab"><h2 class="seccion__titulo" id="modelo-resumen-t">Dos modelos, una misma regla de juego</h2></div>' +
      '<p class="seccion__intro">' + intro + ' ' + fte(fB1(), 'Fuente de la regla manual') + '</p>' + pestanas +
      '<div class="rejilla-2" id="modelo-tarjetas">' + tarjetaModelo('final') + tarjetaModelo('hibrido') + '</div>' +
      avisoGanador() + '</section>';
  }

  // ---- Cómo leer las cifras (convenciones) --------------------------------------------------------------------
  function htmlLectura() {
    const C = FI.convenciones || {};
    const items = [['WAPE', C.WAPE], ['Intervalo de confianza del 95 %', C.IC_95], ['h y H', C.h_y_H], ['Puntos', C.puntos]].filter(function (x) { return x[1]; });
    return '<details class="desplegable" id="modelo-lectura"><summary class="desplegable__resumen">' + icono('chevron-derecha', 'icono desplegable__chevron') + 'Cómo leer las cifras: WAPE, intervalos, h y H, puntos</summary>' +
      '<div class="desplegable__cuerpo">' + items.map(function (x) { return ph('<strong>' + esc(x[0]) + '.</strong> ' + md(x[1].texto), fteT(fTexto(x[1].fuente, 'E11 / E12', 'E11E12', x[0]))); }).join('') + '</div></details>';
  }

  // ---- Secciones de detalle -----------------------------------------------------------------------------------
  function sPredice(m) {
    const X = FI.modelos[CLAVE[m]], C = FI.comun || {};
    const ob = C.objetivo || {};
    return p(g(C, 'unidad_de_prediccion.texto', ''), fteT(fTexto(g(C, 'unidad_de_prediccion.fuente'), 'E1 / E11', 'E11', 'Unidad de predicción'))) +
      h4('El objetivo: ' + ob.nombre_columna) + p(ob.texto || '', fteT(fTexto(ob.fuente, 'E1 / E11', 'E11', 'Objetivo'))) +
      '<div class="cifras">' +
      tarjetaCifra({ etiqueta: 'Pasajeros en el periodo de entrenamiento', valor: g(ob, 'cifras.pasajeros_2023_2025.valor'), unidad: 'pasajeros', decimales: 0, fuente: Object.assign(fTexto(g(ob, 'cifras.pasajeros_2023_2025.fuente'), 'E1', 'E11', 'Pasajeros del periodo'), { verificado: fId('metodo_datos_crudos').verificado, revision: fId('metodo_datos_crudos').revision }), nota: g(ob, 'cifras.pasajeros_2023_2025.texto') }) +
      tarjetaCifra({ etiqueta: 'Pasajeros en ' + ANIO_EVAL + ' (objetivo de prueba)', valor: g(ob, 'cifras.pasajeros_2025.valor'), unidad: 'pasajeros', decimales: 0, fuente: fTexto(g(ob, 'cifras.pasajeros_2025.fuente'), 'E11', 'E11', 'Pasajeros de ' + ANIO_EVAL), nota: g(ob, 'cifras.pasajeros_2025.texto') }) +
      '</div>' +
      h4('Con cuánta antelación') + p(g(X, 'que_predice.antelacion', ''), fteT(fTexto(g(X, 'que_predice.fuente'), EXP[m], EXP[m], 'Antelación'))) +
      h4('Qué entrega') + p(g(X, 'que_predice.salida', '')) +
      (m === 'final' ? h4('De dónde viene') + p(g(X, 'que_es.origen', '')) + p(g(X, 'que_es.texto', ''), fteT(fTexto(g(X, 'que_es.fuente'), 'E11', 'E11', 'Qué es'))) :
        h4('Qué es Chronos-2') + p(g(X, 'que_es.chronos2', ''), fteT(fTexto(g(X, 'que_es.fuente'), 'E12', 'E12', 'Chronos-2'))) + p(g(X, 'que_es.texto', ''))) +
      h4('En términos técnicos') + p(valor(m === 'final' ? 'modelo_final_nombre' : 'modelo_hibrido_nombre') || '', fteT(fId(m === 'final' ? 'modelo_final_nombre' : 'modelo_hibrido_nombre')));
  }

  function sDatos(m) {
    const X = FI.modelos[CLAVE[m]], DT = X.datos_entrenamiento || {};
    let html = p(DT.periodo || '', fteT(fTexto(DT.fuente, EXP[m], EXP[m], 'Datos de entrenamiento')));
    if (m === 'final') {
      const fil = DT.filas || {};
      const aviso0 = (FI.avisos_y_contradicciones || []).filter(function (a) { return a.tipo === 'inconsistencia_documental'; })[0];
      const hor = cifra('modelo_final_horizontes');
      const reales = g(FI, 'modelos.E12_hibrido.datos_entrenamiento.filas.produccion_por_H', {});
      html += '<div class="cifras">' +
        tarjetaCifra({ etiqueta: 'Filas del panel', valor: g(fil, 'panel.valor'), unidad: 'filas', decimales: 0, fuente: fFicha(fil.panel, 'E11', 'E11', 'Filas del panel'), nota: g(fil, 'panel.texto') }) +
        tarjetaCifra({ etiqueta: 'Franjas de prueba en ' + ANIO_EVAL, valor: g(fil, 'prueba_2025.valor'), unidad: 'franjas', decimales: 0, fuente: fFicha(fil.prueba_2025, 'E11', 'E11', 'Franjas de prueba') }) +
        tarjetaCifra({ etiqueta: 'Días del panel', valor: valor('modelo_final_pliegues', 'dias'), unidad: 'días', decimales: 0, fuente: fId('modelo_final_pliegues') }) +
        '</div>';
      if (hor && hor.valor) {
        const arch = hor.valor.archivos || {};
        html += h4('Un modelo de producción por antelación') +
          tabla([{ texto: 'Antelación' }, { texto: 'Archivo del modelo' }, { texto: 'Filas con que entrena (medidas en E12)', num: true }],
            claves(arch).map(function (k) { return fila([th('H = ' + horizonteNumero(k)), td('<code>' + esc(arch[k]) + '</code>'), td(num(reales[k]), 'num')]); }), { compacta: true }) +
          '<p class="pequeno">' + fteT(fId('modelo_final_horizontes')) + ' ' + fteT(fFicha(g(FI, 'modelos.E12_hibrido.datos_entrenamiento.filas'), 'E12', 'E12', 'Filas del V4 en sombra')) + '</p>' +
          (hor.valor.texto_filas ? ph('<strong>Lo que dice el README de E11:</strong> ' + md(hor.valor.texto_filas), null, 'pequeno texto-2') : '') +
          (aviso0 ? aviso('nota', 'Salvedad documental', '<p>' + md(String(aviso0.texto).replace(/\s*Para la app[\s\S]*$/, '')) + '</p>') : '');
      }
      html += h4('Filtros y pesos') + lista((DT.filtros || []).map(md), true);
      const pesos = cifra('modelo_final_pesos');
      if (pesos && pesos.valor) {
        const v = pesos.valor, f = fId('modelo_final_pesos');
        html += '<div class="cifras">' +
          tarjetaCifra({ etiqueta: 'Días atípicos no predecibles (peso bajo)', valor: v.dias_atipicos_no_predecibles, unidad: 'días', decimales: 0, fuente: f }) +
          tarjetaCifra({ etiqueta: 'Filas con peso ' + pesoDeClave(v, 'filas_peso_'), valor: v[claveCon(v, 'filas_peso_')], unidad: 'filas', decimales: 0, fuente: f }) +
          tarjetaCifra({ etiqueta: 'Franjas con fallas de registro (peso ' + pesoDeClave(v, 'franjas_con_fallas_peso_') + ')', valor: v[claveCon(v, 'franjas_con_fallas_peso_')], unidad: 'franjas', decimales: 0, fuente: f, nota: 'El ' + pct(v.pct_franjas_con_fallas) + ' de las franjas.' }) +
          '</div>';
      }
      html += h4('De dónde salen los datos') + p(DT.fuentes_de_datos || '');
    } else {
      const fil = DT.filas || {};
      const ks = claves(fil.produccion_por_H);
      html += h4('Filas de entrenamiento por antelación (modelos de producción)') +
        tabla([{ texto: 'Antelación' }, { texto: 'Filas', num: true }, { texto: 'Desde' }, { texto: 'Con variables de Chronos-2', num: true }],
          ks.map(function (k) { return fila([th('H = ' + horizonteNumero(k)), td(num(fil.produccion_por_H[k]), 'num'), td(esc(F().fecha(g(fil, 'desde_por_H.' + k))), ''), td(num(g(fil, 'filas_con_variables_chronos_por_H.' + k)), 'num')]); }), { compacta: true }) +
        p((fil.texto || '') + (fil.hasta ? ' Último día observado: ' + F().fechaLarga(fil.hasta) + '.' : ''), fteT(fFicha(fil, 'E12', 'E12', 'Filas por antelación'))) +
        h4('Filtros y pesos') + p(DT.filtros_y_pesos || '') +
        h4('Qué ve Chronos-2') + p(DT.contexto_de_chronos2 || '') +
        h4('La historia de Chronos-2 para entrenar') + p(DT.historia_de_chronos2 || '');
    }
    return html;
  }

  function grupoVariables(gr, exp) {
    return '<details class="desplegable desplegable--llano"><summary class="desplegable__resumen">' + icono('chevron-derecha', 'icono desplegable__chevron') + esc(gr.nombre) + ' · ' + num(gr.n) + ' variables</summary>' +
      '<div class="desplegable__cuerpo">' + ph('<strong>Por qué.</strong> ' + md(gr.por_que || ''), fteT(fTexto(gr.fuente, exp, exp === 'E12' ? 'no' : 'E11', gr.nombre))) +
      (gr.definiciones ? ph('<strong>Qué son.</strong> ' + md(gr.definiciones)) : '') +
      (gr.objetivos ? ph('Objetivos: ' + gr.objetivos.map(function (o) { return '<code>' + esc(o) + '</code>'; }).join(', ') + '. Sufijos: ' + (gr.sufijos || []).map(function (o) { return '<code>' + esc(o) + '</code>'; }).join(', ') + '.') : '') +
      chipsCodigo(gr.variables || []) + '</div></details>';
  }
  function sVariables(m) {
    const X = FI.modelos[CLAVE[m]], V = X.variables || {}, V11 = g(FI, 'modelos.E11_V4.variables', {});
    let html = p(g(V, 'total.texto', ''), fteT(m === 'final' ? fId('modelo_final_variables') : fTexto(g(V, 'total.fuente'), 'E12', 'E12', 'Total de variables')));
    if (m === 'hibrido' && V.grupo_nuevo) {
      html += h4('Lo nuevo: ' + V.grupo_nuevo.nombre + ' (' + num(V.grupo_nuevo.n) + ' variables)') +
        '<div class="tarjeta pila">' + chipsCodigo(V.grupo_nuevo.variables || []) + ph('<strong>Qué son.</strong> ' + md(V.grupo_nuevo.definiciones || '')) +
        ph('<strong>Por qué.</strong> ' + md(V.grupo_nuevo.por_que || ''), fteT(fTexto(V.grupo_nuevo.fuente, 'E12', 'E12', 'Variables de Chronos-2'))) + '</div>' +
        h4('Lo heredado del modelo final') + p(V.grupos_heredados_de_V4 || '');
    } else {
      html += h4('Los grupos, con su porqué') + (V.categoricas ? p('Categóricas: ' + V.categoricas.map(function (c) { return '`' + c + '`'; }).join(', ') + '.') : '');
    }
    html += '<div class="pila">' + (V11.grupos || []).map(function (gr) { return grupoVariables(gr, 'E11'); }).join('') + '</div>';
    if (V11.no_incluidas) {
      html += h4('Lo que no entra, y por qué') + lista(V11.no_incluidas.map(function (x) { return '<strong>' + md(x.que) + '</strong> ' + md(x.por_que) + ' ' + fteT(fTexto(x.fuente, 'E11', 'E11', 'No incluida')); }));
    }
    const I = V.importancia_modelo_final_H7;
    if (I) {
      const fI = m === 'final' ? fId('modelo_final_importancia') : fFicha(I, 'E12', 'no', 'Importancia de variables');
      html += h4('Qué variables pesan más (modelo de producción H = ' + hPrincipal() + ')') + p(I.texto || '', fteT(fI)) +
        '<div class="rejilla-2"><div class="pila"><span class="rotulo">Las diez primeras, % de la ganancia</span>' + barras(I.top, 2, 10) + '</div>' +
        '<div class="pila"><span class="rotulo">Por grupo</span>' + barras(I.por_grupo, 2) +
        (I.ganancia_chronos_por_H ? p('Parte que se lleva Chronos-2 según la antelación: ' + claves(I.ganancia_chronos_por_H).map(function (k) { return 'H = ' + horizonteNumero(k) + ': ' + pct(I.ganancia_chronos_por_H[k], 1); }).join('; ') + '. En los pliegues de ' + ANIO_EVAL + ': ' + String(I.en_los_12_pliegues || '—') + '.', fteT(fId('modelo_hibrido_ganancia_chronos'))) : '') +
        (I.nota ? p(I.nota) : '') + '</div></div>';
    }
    const H = X.hiperparametros;
    if (H) {
      html += h4('Hiperparámetros') + p(H.texto || '', fteT(m === 'final' ? fId('modelo_final_hiperparametros') : fFicha(H, 'E12', 'E12', 'Hiperparámetros'))) +
        '<div class="chips">' + claves(H.valores || {}).map(function (k) { return '<span class="chip"><code>' + esc(k) + '</code>&nbsp;' + esc(num(H.valores[k], dec(H.valores[k]))) + '</span>'; }).join('') + '</div>';
    }
    return html;
  }

  function sValidacion(m) {
    const X = FI.modelos[CLAVE[m]], PV = g(FI, 'comun.protocolo_validacion', {}), c = PV.cifras || {};
    let html = p(PV.texto || '', fteT(fTexto(PV.fuente, 'E11 / E12', 'E11E12', 'Protocolo'))) +
      '<div class="cifras">' +
      tarjetaCifra({ etiqueta: 'Pliegues mensuales de ' + ANIO_EVAL, valor: valor('modelo_final_pliegues', 'pliegues_mensuales_2025'), unidad: 'pliegues', decimales: 0, fuente: fId('modelo_final_pliegues') }) +
      tarjetaCifra({ etiqueta: 'Franjas de prueba en ' + ANIO_EVAL, valor: g(c, 'franjas_prueba_2025.valor'), unidad: 'franjas', decimales: 0, fuente: fFicha(c.franjas_prueba_2025, 'E11', 'E11', 'Franjas de prueba ' + ANIO_EVAL) }) +
      tarjetaCifra({ etiqueta: 'Franjas de prueba en ' + ANIO_PRUEBA, valor: g(c, 'franjas_prueba_2024.valor'), unidad: 'franjas', decimales: 0, fuente: fFicha(c.franjas_prueba_2024, 'E12', 'E12', 'Franjas de prueba ' + ANIO_PRUEBA) }) +
      tarjetaCifra({ etiqueta: 'Réplicas del bootstrap (E12), semilla ' + num(c.semilla), valor: c.bootstrap_replicas_E12, unidad: 'réplicas', decimales: 0, fuente: fTexto(PV.fuente, 'E12', 'E12', 'Bootstrap') }) +
      '</div>';
    html += h4('La regla de selección') + p(g(X, 'protocolo_validacion.texto', ''), fteT(fFicha(X.protocolo_validacion, EXP[m], EXP[m], 'Regla de selección')));
    if (m === 'final') {
      const cand = cifra('modelo_final_candidatos'), sel = cifra('modelo_final_seleccion');
      if (cand && cand.valor) html += ph('<strong>Variantes probadas:</strong> ' + esc((cand.valor.variantes || []).join(' · ')) + '. <strong>Regla:</strong> ' + esc(cand.valor.regla) + '. <strong>Cumplieron:</strong> ' + esc((cand.valor.significativas || []).join(', ')) + '.', fteT(fId('modelo_final_candidatos')));
      if (sel) html += ph('<strong>Ganancia de la variante elegida frente a E1:</strong> ' + difIc(sel.valor, sel.ic_inf, sel.ic_sup) + '; mejor en ' + num(sel.meses_mejor) + ' meses y peor en ' + num(sel.meses_peor) +
        '; p de Wilcoxon ' + num(sel.p_wilcoxon, 3) + ', p de la t pareada ' + num(sel.p_t_pareada, 2) + '.', fteT(fId('modelo_final_seleccion')));
      if (g(X, 'protocolo_validacion.reservas')) html += h4('Reservas de la verificación') + lista(X.protocolo_validacion.reservas.map(md));
    } else {
      const cm = cifra('modelo_correccion_multiple');
      html += p(valor('modelo_regla_seleccion_e12') || '', fteT(fId('modelo_regla_seleccion_e12')));
      if (cm && cm.valor) html += ph('<strong>Corrección por comparaciones múltiples:</strong> p de Holm ' + num(cm.valor.p_holm, 3) + ' (' + (cm.valor.sobrevive_holm ? 'sobrevive' : 'no sobrevive') + '); intervalo corregido de Bonferroni ' +
        ic(cm.valor.ic_bonf_inf, cm.valor.ic_bonf_sup) + ' (' + (cm.valor.sobrevive_bonferroni ? 'queda entero bajo cero' : 'cruza el cero') + ').', fteT(fId('modelo_correccion_multiple')));
      html += h4('La prueba en ' + ANIO_PRUEBA) + p(PV.prueba_2024_E12 || '') + p(g(X, 'errores.en_2024.dif_pp.texto', ''), fteT(fId('modelo_hibrido_wape_2024'))) + p('Estabilidad: ' + g(X, 'errores.en_2024.estabilidad', ''));
    }
    const FU = valor('modelo_fugas') || {}, PF = FU.prueba_fugas_panel || {};
    const okPF = ['h7_ok', 'h1_ok', 'controles_ok', 'determinismo_ok'].filter(function (k) { return k in PF; });
    html += h4('Sin fugas de información') + p(PV.sin_fuga || '') +
      (m === 'hibrido' ? p(FU.prueba_empirica_hibrido || '') + p(FU.diseno_y_fugas || '') : '') +
      (okPF.length ? ph('<strong>Prueba de fugas del panel</strong> (corte simulado el ' + esc(F().fechaLarga(PF.T)) + '): ' +
        (okPF.every(function (k) { return PF[k] === true; }) ? 'pasa sus ' + num(okPF.length) + ' comprobaciones (antelación de una semana, de un día, controles y determinismo).' : 'alguna comprobación no pasa; ver la fuente.'), fteT(fId('modelo_fugas'))) : fteT(fId('modelo_fugas')));
    return html;
  }

  // Errores: los tres frente a frente (compartida).
  function sErrores() {
    const E11 = g(FI, 'modelos.E11_V4.errores', {}), E12 = g(FI, 'modelos.E12_hibrido.errores', {}), B = g(FI, 'comun.regla_manual_B1', {});
    const h = hPrincipal();
    const fE11 = function (ent, t) { return fFicha(ent, 'E11', 'E11', t); }, fE12 = function (ent, t) { return fFicha(ent, 'E12', 'E12', t); };
    const fB = fB1();
    // Tabla resumen.
    const filasResumen = [
      ['WAPE a ' + h + ' días, ' + ANIO_EVAL, [b1(), wapeFinal(), wapeHibrido()], [2, 2, 2], fB, fFinal(), fId('modelo_hibrido_wape_2025')],
      ['WAPE con datos de ayer (h = ' + horizonteNumero('H1') + '), ' + ANIO_EVAL, [b1(), g(E11, 'global_h1.WAPE.valor'), null], [2, 2, 0], fB, fE11(g(E11, 'global_h1.WAPE'), 'WAPE con h = 1'), null],
      ['Error medio por franja (MAE, pasajeros)', [g(B, 'mae_h7.valor'), g(E11, 'global_h7.MAE.valor'), g(E12, 'global_2025.MAE.valor')], [1, 1, 1], fTexto(B.fuente, 'E11', 'E11', 'MAE de la regla manual'), fTexto(g(E11, 'global_h7.fuente'), 'E11', 'E11', 'MAE del modelo final'), fTexto(g(E12, 'global_2025.fuente'), 'E12', 'E12', 'MAE del híbrido'), 'pasajeros'],
      ['WAPE del total diario por ruta', [g(B, 'total_diario_por_ruta.valor'), g(E11, 'global_h7.total_diario_por_ruta_WAPE.valor'), g(E12, 'global_2025.total_diario_por_ruta_WAPE.valor')], [2, 2, 2], fTexto(B.fuente, 'E11', 'E11', 'Total diario, regla manual'), fTexto(g(E11, 'global_h7.fuente'), 'E11', 'E11', 'Total diario, modelo final'), fTexto(g(E12, 'global_2025.fuente'), 'E12', 'E12', 'Total diario, híbrido')],
      ['Sesgo del total, ' + ANIO_EVAL, [null, g(E11, 'global_h7.sesgo_pct.valor'), g(E12, 'global_2025.sesgo_pct.valor')], [0, 2, 2], null, fFicha(g(E11, 'global_h7.sesgo_pct'), 'E11 / E12', 'E12', 'Sesgo del modelo final'), fIdParte('modelo_hibrido_sesgo', '2025_pct', 'Sesgo del híbrido, ' + ANIO_EVAL), 'signo'],
      ['WAPE en ' + ANIO_PRUEBA + ' (misma regla, otro año)', [null, valor('modelo_final_2024'), valor('modelo_hibrido_wape_2024', 'WAPE_hibrido')], [0, 2, 2], null, fId('modelo_final_2024'), fId('modelo_hibrido_wape_2024')],
    ];
    const tResumen = tabla([{ texto: 'Medida' }, { texto: 'Regla manual (hoy)', num: true }, { texto: 'Modelo final (E11)', num: true }, { texto: 'Híbrido (E12)', num: true }],
      filasResumen.map(function (r) {
        const vals = r[1], decs = r[2], unidad = r[6];
        const nums = vals.filter(esNum), min = nums.length > 1 ? Math.min.apply(null, nums) : null;
        return fila([th(esc(r[0]))].concat(vals.map(function (v, i) {
          const f = r[3 + i];
          const texto = !esNum(v) ? '—' : unidad === 'pasajeros' ? num(v, decs[i]) : unidad === 'signo' ? sig(v, decs[i], '%') : pct(v, decs[i]);
          return td(texto + (f && esNum(v) ? ' ' + fte(f) : ''), 'num' + (esNum(v) && unidad !== 'signo' && v === min ? ' tabla__mejor' : ''));
        })));
      }), { titulo: 'Resumen: ' + esc(E11.nota || '') });
    const H25 = cifra('modelo_hibrido_wape_2025') ? cifra('modelo_hibrido_wape_2025').valor : {};
    const escala = g(E12, 'frente_a_V4_2025.frente_a_V4_con_escala_corregida', '');
    const frente = ph('<strong>Híbrido frente a modelo final:</strong> ' + difIc(H25.dif, H25.ic_inf, H25.ic_sup) + ', mejor en ' + num(H25.meses_mejor) + ' de ' + num(H25.meses) + ' meses; ' + md(g(E12, 'frente_a_V4_2025.pruebas', '')) + '.' + (escala ? ' ' + md(typeof escala === 'object' ? escala.texto || '' : escala) + '.' : ''), fteT(fId('modelo_hibrido_wape_2025'))) +
      ph('<strong>Modelo final frente a la regla manual:</strong> ' + md(g(E11, 'frente_a_B1_h7.texto', '')) + ' <strong>Frente al primer modelo (E1):</strong> ' + md(g(E11, 'frente_a_V0_h7.dif_pp.texto', '')) + ', mejor en ' + md(g(E11, 'frente_a_V0_h7.meses_mejor', '')) + '; ' + md(g(E11, 'frente_a_V0_h7.pruebas', '')) + '.', fteT(fE11(g(E11, 'frente_a_B1_h7'), 'Frente a la regla manual')) + ' ' + fteT(fId('modelo_final_seleccion')));

    // Gráficos por ruta, tipo de día y franja: B1 de E11 (una cifra decimal) y los dos modelos del arnés de E12.
    function trio(id, titulo, sub, aria, catsObj, b1Obj, v4Obj, hibObj, difObj, texto, fB1x, fMod, nombreCat) {
      const cats = claves(catsObj);
      const sHoy = cats.map(function (k) { return b1Obj[k]; }), sFin = cats.map(function (k) { return v4Obj[k]; }), sHib = cats.map(function (k) { return hibObj[k]; });
      // Todos los porcentajes de error con dos decimales (DISEÑO.md §6): así las restas de la tabla cuadran a la vista.
      const series = [{ nombre: 'Regla manual (hoy)', rol: 'hoy', datos: sHoy, dec: 2 }, { nombre: 'Modelo final (E11)', rol: 'final', datos: sFin, dec: 2, rayas: true }, { nombre: 'Híbrido (E12)', rol: 'hibrido', datos: sHib, dec: 2 }];
      const t = tabla([{ texto: nombreCat }, { texto: 'Regla manual', num: true }, { texto: 'Modelo final', num: true }, { texto: 'Híbrido', num: true }, { texto: 'Híbrido − final (IC 95 %)' }],
        cats.map(function (k, i) { return fila([th(clave(k))].concat(celdasMejor([sHoy[i], sFin[i], sHib[i]], [series[0].dec, series[1].dec, series[2].dec])).concat([td(esc(difObj && difObj[k] || '—'), 'num')])); }), { compacta: true });
      return figura({ id: id, titulo: titulo, sub: sub, aria: aria, series: series, tabla: t, nota: texto, fuente: fteT(fB1x) + ' ' + fteT(fMod), opcion: opcionBarras(cats, series) });
    }
    const graficosHTML = '<div class="rejilla-3 modelo__graficos">' +
      trio('modelo-g-ruta', 'Por ruta', 'Pasajeros mal estimados de cada 100 a ' + h + ' días, ' + ANIO_EVAL + '. Gris: regla manual; rayado: modelo final; liso: híbrido.', 'Barras: error por ruta de la regla manual, el modelo final y el híbrido',
        g(E11, 'por_ruta_h7.B1', {}), g(E11, 'por_ruta_h7.B1', {}), g(E12, 'por_ruta_2025.V4', {}), g(E12, 'por_ruta_2025.hibrido', {}), g(E12, 'por_ruta_2025.dif'), g(E11, 'por_ruta_h7.texto', ''), fE11(E11.por_ruta_h7, 'Por ruta, regla manual y modelo final'), fE12(E12.por_ruta_2025, 'Por ruta, híbrido'), 'Ruta') +
      trio('modelo-g-tipo', 'Por tipo de día', 'Donde más gana el modelo es en domingos y festivos.', 'Barras: error por tipo de día de la regla manual, el modelo final y el híbrido',
        g(E11, 'por_tipo_dia_h7.B1', {}), g(E11, 'por_tipo_dia_h7.B1', {}), g(E12, 'por_tipo_dia_2025.V4', {}), g(E12, 'por_tipo_dia_2025.hibrido', {}), g(E12, 'por_tipo_dia_2025.dif'), g(E12, 'por_tipo_dia_2025.texto', ''), fE11(E11.por_tipo_dia_h7, 'Por tipo de día, regla manual y modelo final'), fE12(E12.por_tipo_dia_2025, 'Por tipo de día, híbrido'), 'Tipo de día') +
      trio('modelo-g-franja', 'Por franja de hora de salida', 'Las tardes son la franja más difícil en todas las rutas.', 'Barras: error por franja horaria de la regla manual, el modelo final y el híbrido',
        g(E11, 'por_franja_h7.B1', {}), g(E11, 'por_franja_h7.B1', {}), g(E12, 'por_franja_2025.V4', {}), g(E12, 'por_franja_2025.hibrido', {}), g(E12, 'por_franja_2025.dif'), g(E12, 'por_franja_2025.texto', ''), fE11(E11.por_franja_h7, 'Por franja, regla manual y modelo final'), fE12(E12.por_franja_2025, 'Por franja, híbrido'), 'Franja') +
      '</div>';

    // Antelación: protocolo de E11 (regla manual y modelo final) y simulación del modo producción de E12 (final e híbrido).
    const PA = E11.por_antelacion || {}, PE = E12.por_antelacion_modo_produccion_2025 || {};
    const ksA = claves(PA.V4), catsA = ksA.map(function (k) { return 'H = ' + horizonteNumero(k); });
    const aHoy = ksA.map(function (k) { return g(PA, 'B1.' + k); }), aFin = ksA.map(function (k) { return PA.V4[k]; });
    const seriesA = [{ nombre: 'Regla manual (hoy)', rol: 'hoy', datos: aHoy, dec: 2 }, { nombre: 'Modelo final (E11)', rol: 'final', datos: aFin, dec: 2, rayas: true }];
    const tA = tabla([{ texto: 'Antelación' }, { texto: 'Regla manual', num: true }, { texto: 'Modelo final', num: true }],
      ksA.map(function (k, i) { return fila([th('H = ' + horizonteNumero(k))].concat(celdasMejor([aHoy[i], aFin[i]], [2, 2]))); }), { compacta: true });
    const ksE = claves(PE.hibrido).filter(function (k) { return /^H\d+$/.test(k); }), catsE = ksE.map(function (k) { return 'H = ' + horizonteNumero(k); });
    const eFin = ksE.map(function (k) { return g(PE, 'V4.' + k); }), eHib = ksE.map(function (k) { return g(PE, 'hibrido.' + k); }), eChr = ksE.map(function (k) { return g(PE, 'chronos2_solo.' + k); });
    const seriesE = [{ nombre: 'Modelo final (E11)', rol: 'final', datos: eFin, dec: 2, rayas: true }, { nombre: 'Híbrido (E12)', rol: 'hibrido', datos: eHib, dec: 2 }];
    const tE = tabla([{ texto: 'Antelación' }, { texto: 'Modelo final', num: true }, { texto: 'Híbrido', num: true }, { texto: 'Chronos-2 solo', num: true }, { texto: 'Semanas en que gana el híbrido' }],
      ksE.map(function (k, i) { return fila([th('H = ' + horizonteNumero(k))].concat(celdasMejor([eFin[i], eHib[i], eChr[i]], [2, 2, 2])).concat([td(esc(g(PE, 'semanas_mejor_por_H.' + k, '—')))])); })
        .concat([fila([th('Las cuatro antelaciones')].concat(celdasMejor([g(PE, 'V4.total'), g(PE, 'hibrido.total'), g(PE, 'chronos2_solo.total')], [2, 2, 2])).concat([td(esc(g(PE, 'dif_total.texto', '')))]), 'tabla__fila-total')]), { compacta: true });
    const antelacionHTML = '<div class="rejilla-2">' +
      figura({ id: 'modelo-g-antelacion', titulo: 'Según la antelación: protocolo de E11', sub: 'Pronosticar con más semanas de antelación cuesta poco. Doce pliegues de ' + ANIO_EVAL + '.', aria: 'Barras: error de la regla manual y del modelo final según la antelación, protocolo de E11', series: seriesA, tabla: tA, nota: g(PA, 'texto', ''), fuente: fteT(fE11(PA, 'Por antelación, protocolo de E11')), opcion: opcionBarras(catsA, seriesA), bajo: true }) +
      figura({ id: 'modelo-g-emulacion', titulo: 'Según la antelación: simulación del modo producción', sub: 'Modelos entrenados solo hasta cada origen; prueba también las antelaciones largas del híbrido, que el protocolo no evaluó.', aria: 'Barras: error del modelo final y del híbrido según la antelación en la simulación del modo producción', series: seriesE, tabla: tE, nota: g(PE, 'texto', ''), fuente: fteT(fId('modelo_hibrido_emulacion')) + ' ' + fteT(fFicha(PE, 'E12', 'no', 'Simulación del modo producción')), opcion: opcionBarras(catsE, seriesE), bajo: true }) +
      '</div>';

    // Tabla por mes con el sesgo.
    const PM11 = E11.por_mes_h7 || {}, PM12 = E12.por_mes_2025 || {};
    const meses = claves(PM11.B1);
    const tMes = tabla([{ texto: 'Mes de ' + ANIO_EVAL }, { texto: 'Regla manual', num: true }, { texto: 'Modelo final', num: true }, { texto: 'Híbrido', num: true }, { texto: 'Híbrido − final', num: true }, { texto: 'Sesgo final', num: true }, { texto: 'Sesgo híbrido', num: true }],
      meses.map(function (k) {
        const vals = [g(PM11, 'B1.' + k), g(PM11, 'V4.' + k), g(PM12, 'hibrido.' + k)];
        return fila([th(esc(mesNombre(k)))].concat(celdasMejor(vals, [2, 2, 2])).concat([td(sig(g(PM12, 'dif_vs_V4.' + k), 2), 'num'), td(sig(g(E11, 'sesgo.por_mes_pct.' + k), 2, '%'), 'num'), td(sig(g(E12, 'sesgo.por_mes_pct_2025.' + k), 2, '%'), 'num')]));
      }), { titulo: 'Por mes: WAPE a ' + h + ' días y sesgo del total', compacta: true });
    const mesHTML = h4('Mes a mes') + tMes +
      '<p class="pequeno">' + fteT(fE11(PM11, 'Por mes, regla manual y modelo final')) + ' ' + fteT(fE12(PM12, 'Por mes, híbrido')) + ' ' + fteT(fE11(E11.sesgo, 'Sesgo por mes del modelo final')) + ' ' + fteT(fE12(E12.sesgo, 'Sesgo por mes del híbrido')) + '</p>' +
      p(g(PM11, 'texto', '')) + p(g(E11, 'sesgo.texto', '')) + p(g(E12, 'sesgo.texto', '')) + (PM11.nota_redondeo ? p(PM11.nota_redondeo, null, 'pequeno texto-3') : '');

    // Por subconjunto de días (etiquetas de E11, con conteos; emparejadas con las de E12 sin el paréntesis).
    const S11 = E11.por_subconjunto_h7 || {}, S12 = E12.por_subconjunto_2025 || {};
    const normal = function (s) { return String(s).toLowerCase().replace(/\s*\(.*?\)/g, '').replace(/\s+de e10/g, '').trim(); };
    const sub12 = {};
    claves(S12.hibrido).forEach(function (k) { sub12[normal(k)] = { hib: S12.hibrido[k], v4: g(S12, 'V4.' + k) }; });
    const tSub = tabla([{ texto: 'Subconjunto de ' + ANIO_EVAL }, { texto: 'Regla manual', num: true }, { texto: 'Modelo final', num: true }, { texto: 'Híbrido', num: true }],
      claves(S11.V4).map(function (k) { const e = sub12[normal(k)] || {}; return fila([th(esc(k))].concat(celdasMejor([g(S11, 'B1.' + k), esNum(e.v4) ? e.v4 : S11.V4[k], e.hib], [2, 2, 2]))); }), { titulo: 'Por subconjunto de días y franjas: WAPE a ' + h + ' días', compacta: true });
    const subHTML = h4('Dónde rinde igual y dónde no') + tSub + '<p class="pequeno">' + fteT(fE11(S11, 'Por subconjunto, regla manual y modelo final')) + ' ' + fteT(fE12(S12, 'Por subconjunto, híbrido')) + '</p>' + p(g(S11, 'texto', '')) + p(g(S12, 'grupos_de_dias.texto', ''), fteT(fTexto(g(S12, 'grupos_de_dias.fuente'), 'E12', 'E12', 'Grupos de días')));

    return tResumen + frente + h4('Por ruta, tipo de día y franja') + graficosHTML + h4('Según la antelación') + antelacionHTML + mesHTML + subHTML;
  }

  function sProbado() {
    const CE = FI.comparacion_E12 || {}, E11 = FI.modelos.E11_V4 || {}, E12 = FI.modelos.E12_hibrido || {};
    const c51 = cifra('modelo_comparacion_51');
    let html = p(g(CE, 'candidatos.texto', ''), fteT(fId('modelo_comparacion_51'))) + p(g(CE, 'respuesta_corta.texto', ''), fteT(fTexto(g(CE, 'respuesta_corta.fuente'), 'E12', 'E12', 'Respuesta corta de E12')));
    if (c51 && c51.valor) {
      const v = c51.valor, f = fId('modelo_comparacion_51');
      html += '<div class="cifras">' + tarjetaCifra({ etiqueta: 'Candidatos comparados', valor: v.candidatos, unidad: 'candidatos', decimales: 0, fuente: f, nota: num(v.resultados) + ' resultados; ' + num(v.elegibles) + ' elegibles.' }) +
        tarjetaCifra({ etiqueta: 'Cumplen la regla de selección', valor: v.cumplen_regla, unidad: 'candidatos', decimales: 0, fuente: f, nota: num(v.elegibles_cumplen) + ' de ellos elegibles.' }) +
        tarjetaCifra({ etiqueta: 'Ganador formal: ' + v.ganador_formal, valor: v.ganador_WAPE, unidad: '%', decimales: 2, fuente: f, nota: difIc(v.ganador_dif, v.ganador_ic_inf, v.ganador_ic_sup) + ' frente al modelo final; mejor en ' + num(v.ganador_meses_mejor) + ' meses.' }) + '</div>';
    }
    // Finalistas.
    const fin = cifra('modelo_finalistas');
    if (fin && fin.valor) {
      html += h4('Los finalistas de E12') + tabla([{ texto: 'Candidato' }, { texto: 'WAPE ' + ANIO_EVAL, num: true }, { texto: 'Frente al final, ' + ANIO_EVAL, num: true }, { texto: 'Frente al final, ' + ANIO_PRUEBA, num: true }, { texto: '¿Se sostiene en ' + ANIO_PRUEBA + '?' }],
        claves(fin.valor).map(function (k) {
          const r = fin.valor[k];
          const sost = r.cumple_2024 === true ? '<span class="chip chip--bien">sí</span>' : r.cumple_2024 === false ? '<span class="chip chip--critico">no</span>' : '—';
          return fila([th('<code>' + esc(k) + '</code>'), td(pct(r.WAPE), 'num' + (/hibrido/.test(k) ? ' tabla__mejor' : '')), td(difIc(r.dif, r.ic_inf, r.ic_sup), 'num'), td(difIc(r.dif_2024, r.ic_inf_2024, r.ic_sup_2024), 'num'), td(sost)]);
        }), { compacta: true }) +
        '<p class="pequeno">' + fteT(fId('modelo_finalistas')) + '</p>';
    }
    // Familias.
    const fuentesFamilia = { 'Árboles': 'modelo_otros_arboles', 'Clásicos': 'modelo_clasicos', 'Redes': 'modelo_redes', 'Fundacionales': 'modelo_fundacionales', 'Combinaciones': 'modelo_finalistas' };
    html += h4('Las familias y sus mejores');
    (CE.familias || []).forEach(function (fam) {
      const idF = claves(fuentesFamilia).filter(function (k) { return fam.familia.indexOf(k) === 0; }).map(function (k) { return fuentesFamilia[k]; })[0];
      html += '<details class="desplegable desplegable--llano"><summary class="desplegable__resumen">' + icono('chevron-derecha', 'icono desplegable__chevron') + esc(fam.familia) + ' · ' + num((fam.mejores || []).length) + ' resultados</summary><div class="desplegable__cuerpo">' +
        p(fam.por_que || '', fteT(idF ? fId(idF) : fTexto(fam.fuente, 'E12', 'E12', fam.familia))) +
        tabla([{ texto: 'Modelo' }, { texto: 'WAPE ' + ANIO_EVAL, num: true }, { texto: 'Frente al final', num: true }, { texto: 'Meses mejor', num: true }, { texto: 'En ' + ANIO_PRUEBA }],
          (fam.mejores || []).map(function (r) { return fila([th(esc(r.modelo)), td(esNum(r.WAPE) ? pct(r.WAPE) : esc(r.WAPE), 'num' + (r.cumple_regla ? ' tabla__mejor' : '')), td(esc(r.dif) + (r.nota ? ' (' + esc(r.nota) + ')' : ''), 'num'), td(esc(r.meses_mejor || '—'), 'num'), td(esc(r.en_2024 || '—'))]); }), { compacta: true }) + '</div></details>';
    });
    html += h4('Los modelos fundacionales: TimesFM y Chronos-2') + p(g(CE, 'timesfm.texto', ''), fteT(fTexto(g(CE, 'timesfm.fuente'), 'E12', 'E12', 'TimesFM'))) + p(g(CE, 'chronos.texto', ''), fteT(fTexto(g(CE, 'chronos.fuente'), 'E12', 'E12', 'Chronos-2'))) +
      h4('Por qué gana la combinación') + p(g(CE, 'por_que_gana_la_combinacion.texto', ''), fteT(fFicha(CE.por_que_gana_la_combinacion, 'E12', 'E12', 'Correlación de errores')));
    // Ganador formal frente a recomendado.
    const cr = g(CE, 'costo_y_riesgo.tabla', []);
    html += h4('Ganador formal frente a recomendado') +
      aviso('canje', 'Por qué el híbrido y no el ganador formal', p(porQueLlano(valor('modelo_por_que_hibrido')), fteT(fId('modelo_por_que_hibrido')))) +
      tabla([{ texto: 'Opción' }, { texto: 'WAPE ' + ANIO_EVAL, num: true }, { texto: 'Prueba ' + ANIO_PRUEBA }, { texto: 'Modelos a mantener' }, { texto: 'Librerías' }, { texto: 'GPU' }, { texto: 'Entrenamiento' }, { texto: 'Riesgo' }],
        cr.map(function (r) { return fila([th(esc(r.modelo)), td(esc(r.WAPE_2025), 'num' + (/H[ií]brido/.test(r.modelo) ? ' tabla__mejor' : '')), td(esc(r.prueba_2024)), td(esc(r.modelos_a_mantener)), td(esc(r.librerias)), td(esc(r.gpu)), td(esc(r.entrenamiento)), td(esc(r.riesgo))]); }), { titulo: 'Costo, complejidad y riesgo de cada opción', compacta: true }) +
      '<p class="pequeno">' + fteT(fFicha(CE.costo_y_riesgo, 'E12', 'parcial', 'Costo y riesgo')) + '</p>';
    // Lo que compitió con el híbrido y las variantes de E11.
    html += h4('Lo que compitió con el híbrido por el puesto de producción') + p(g(E12, 'probado_y_descartado.nota', '')) +
      tabla([{ texto: 'Alternativa' }, { texto: 'Resultado' }], (g(E12, 'probado_y_descartado.alternativas', []) || []).map(function (r) { return fila([th(md(r.que)), td(md(r.resultado) + ' ' + fteT(fTexto(r.fuente, 'E12', 'E12', 'Alternativa')))]); }), { compacta: true }) +
      h4('Lo que se probó al construir el modelo final (E11 y antes)') +
      tabla([{ texto: 'Qué' }, { texto: 'Resultado' }], (E11.probado_y_descartado || []).map(function (r) { return fila([th(md(r.que)), td(md(r.resultado) + ' ' + fteT(fTexto(r.fuente, 'E11', 'E11', 'Variante')))]); }), { compacta: true });
    const pl = cifra('modelo_plantillas_hoja_calculo');
    if (pl) html += ph('<strong>Alternativa auditable en hoja de cálculo (E5):</strong> ' + esc(pl.que_es) + ': ' + pct(pl.valor) + '.', fteT(fId('modelo_plantillas_hoja_calculo')));
    const ent = cifra('modelo_entorno');
    if (ent && ent.valor && ent.valor.e12_entorno_aparte) html += ph('<strong>Para repetir la comparación:</strong> ' + md(ent.valor.e12_entorno_aparte), fteT(fId('modelo_entorno')));
    return html;
  }

  function sDecisiones(m) {
    const X = FI.modelos[CLAVE[m]], DD = X.decisiones_de_diseno || {};
    const col = function (titulo, items, bien) {
      return '<div class="pila"><h3 class="modelo__h4">' + esc(titulo) + '</h3>' + lista((items || []).map(function (x) {
        return '<span class="verificado verificado--' + (bien ? 'si' : 'no') + '">' + icono(bien ? 'bien' : 'cerrar') + '</span> <strong>' + md(x.decision) + '</strong> ' + md(x.evidencia) + ' ' + fteT(fTexto(x.fuente, EXP[m], EXP[m], 'Decisión'));
      })) + '</div>';
    };
    return '<div class="rejilla-2">' + col('Lo que ayudó', DD.ayuda, true) + col('Lo que no ayudó', DD.no_ayuda, false) + '</div>';
  }

  function sProduccion(m) {
    const X = FI.modelos[CLAVE[m]], P = X.produccion || {}, C = P.computo || {};
    let html = dl([['Script', '<code>' + esc(P.script) + '</code>'], ['Comando', '<code class="modelo__comando">' + esc(P.comando) + '</code>']]) +
      h4('Qué hace') + p(P.que_hace || '', fteT(fTexto(P.fuente, EXP[m], EXP[m], 'Producción'))) +
      h4('Cada cuánto se reentrena') + p(P.reentrenar_cada || '') +
      (P.calendarios_futuros ? h4('Calendarios futuros') + p(P.calendarios_futuros) : '') +
      (P.requisitos ? h4('Requisitos') + p(P.requisitos) : '');
    const ent = cifra('modelo_entorno');
    if (m === 'hibrido' && ent && ent.valor) html += ph('<strong>Entorno:</strong> ' + md(ent.valor.hibrido_python || '') + ' ' + md(ent.valor.hibrido_sin_gpu || ''), fteT(fId('modelo_entorno')));
    html += h4('Tiempos y cómputo') + p(C.hardware || '');
    if (m === 'final') {
      const t = cifra('modelo_final_tiempo_entrenamiento');
      if (t && t.valor) html += '<div class="cifras">' +
        tarjetaCifra({ etiqueta: 'Corrida completa de la evaluación', valor: t.valor.evaluacion_completa_s, unidad: 's', decimales: 0, fuente: fId('modelo_final_tiempo_entrenamiento'), nota: g(C, 'evaluacion_completa_min.texto', '') }) + '</div>' +
        ph('<strong>Reentrenar:</strong> ' + md(t.valor.por_reentrenamiento || '') + '. ' + md(t.valor.texto_produccion || ''), fteT(fId('modelo_final_tiempo_entrenamiento')));
    } else {
      const t = cifra('modelo_hibrido_tiempos'), cpu = cifra('modelo_hibrido_costo_cpu');
      const seg = function (v) { return esNum(v) ? num(v, 1) + ' s' : '—'; };
      if (t && t.valor) html += tabla([{ texto: 'Paso' }, { texto: 'Tiempo', num: true }], [
        fila([th('Armar el panel'), td(seg(t.valor.panel_s), 'num')]),
        fila([th('Cargar Chronos-2'), td(seg(t.valor.carga_chronos2_s), 'num')]),
        fila([th('Pronóstico de Chronos-2 desde el origen'), td(seg(t.valor.chronos2_origen_s), 'num')]),
        fila([th('Entrenar y predecir con LightGBM'), td(seg(t.valor.lightgbm_s), 'num')]),
        fila([th('Total'), td(seg(t.valor.total), 'num')], 'tabla__fila-total'),
      ], { titulo: 'Tiempos de la corrida de enero de 2026, en CPU', compacta: true }) + '<p class="pequeno">' + fteT(fId('modelo_hibrido_tiempos')) + ' ' + fteT(fFicha(C, 'E12', 'no', 'Cómputo')) + '</p>';
      if (cpu && cpu.valor) html += '<div class="cifras">' +
        tarjetaCifra({ etiqueta: 'Una semana de Chronos-2 en CPU', valor: cpu.valor.inferencia_s, unidad: 's', decimales: 1, fuente: fId('modelo_hibrido_costo_cpu'), nota: 'Prueba con ' + num(cpu.valor.franjas) + ' franjas; el WAPE entre CPU y GPU difiere en ' + pct(cpu.valor.wape_cpu_vs_gpu_pct, 2) + '.' }) +
        tarjetaCifra({ etiqueta: 'Diferencia media frente a la GPU', valor: cpu.valor.dif_media_pax_vs_gpu, unidad: 'pasajeros', decimales: 2, fuente: fId('modelo_hibrido_costo_cpu'), nota: 'Máxima: ' + num(cpu.valor.dif_max_pax, 0) + ' pasajeros sobre una predicción media de ' + num(cpu.valor.media_prediccion, 1) + '.' }) + '</div>';
    }
    html += h4('Qué sale') + dl(claves(P.salidas || {}).map(function (k) { return [k, md(P.salidas[k])]; }));
    const PR = P.pronostico_enero_2026;
    if (PR) {
      const fPR = fFicha(PR, EXP[m], m === 'final' ? 'E11' : 'parcial', 'Pronóstico de enero de 2026');
      // La suma de E8 no está en el archivo del pronóstico del modelo: sale de la columna E8_ensamble_diario de la tabla semanal de E12.
      const fSem = fId('demanda_pronostico_2026_enero');
      const fE8 = Object.assign({}, fPR, { archivo: fPR.archivo + ' y ' + fSem.archivo, clave: fPR.clave + '; ' + fSem.archivo + ': suma de la columna E8_ensamble_diario', titulo: 'Frente al ensamble diario de E8' });
      html += h4('El primer pronóstico: enero de 2026') + '<div class="cifras">' +
        tarjetaCifra({ etiqueta: 'Pasajeros pronosticados, cuatro semanas', valor: g(PR, 'total.valor'), unidad: 'pasajeros', decimales: 0, fuente: fPR, nota: g(PR, 'total.texto') }) +
        tarjetaCifra({ etiqueta: 'Frente a las mismas fechas de ' + ANIO_EVAL, valor: g(PR, 'frente_a_2025_alineado.valor'), unidad: '%', decimales: 1, signo: true, fuente: fPR, nota: g(PR, 'frente_a_2025_alineado.texto') }) +
        tarjetaCifra({ etiqueta: 'Frente al ensamble diario de E8', valor: g(PR, 'frente_a_E8.valor'), unidad: '%', decimales: 1, signo: true, fuente: fE8, nota: g(PR, 'frente_a_E8.texto') }) +
        (PR.frente_a_E11 ? tarjetaCifra({ etiqueta: 'Frente al modelo final', valor: g(PR, 'frente_a_E11.valor'), unidad: '%', decimales: 1, signo: true, fuente: fPR, nota: g(PR, 'frente_a_E11.texto') }) : '') + '</div>' +
        '<div class="rejilla-2">' +
        tabla([{ texto: 'Ruta' }, { texto: 'Pasajeros', num: true }], claves(PR.por_ruta || {}).map(function (r) { return fila([th(clave(r)), td(num(PR.por_ruta[r]), 'num')]); }), { compacta: true }) +
        tabla([{ texto: 'Semana' }, { texto: 'Pasajeros', num: true }], claves(PR.por_semana || {}).map(function (s) { return fila([th(esc(s)), td(num(PR.por_semana[s]), 'num')]); }), { compacta: true }) + '</div>' +
        p(PR.forma || '') + (PR.V4_en_sombra ? p('V4 en sombra: ' + g(PR, 'V4_en_sombra.texto', '')) : '');
    }
    if (m === 'hibrido') {
      const em = cifra('modelo_hibrido_emulacion');
      if (em && em.valor) html += h4('Simulación de uso real en ' + ANIO_EVAL) + '<div class="cifras">' +
        tarjetaCifra({ etiqueta: 'Híbrido, cuatro semanas por delante', valor: em.valor.hibrido, unidad: '%', decimales: 2, fuente: fId('modelo_hibrido_emulacion'), variacion: icono('flecha-abajo') + difIc(em.valor.dif, em.valor.ic_inf, em.valor.ic_sup) + ' frente al modelo final', variacionClase: 'cifra__variacion--bien', nota: 'Mejor en ' + num(em.valor.semanas_mejor) + ' de ' + num(em.valor.semanas) + ' semanas y en ' + num(em.valor.origenes_mejor) + ' de ' + num(em.valor.origenes) + ' orígenes.' }) +
        tarjetaCifra({ etiqueta: 'Modelo final en la misma simulación', valor: em.valor.V4, unidad: '%', decimales: 2, fuente: fId('modelo_hibrido_emulacion'), nota: g(FI, 'modelos.E12_hibrido.errores.por_antelacion_modo_produccion_2024.texto', '') }) + '</div>';
    }
    return html;
  }

  function sVerificacion(m) {
    const X = FI.modelos[CLAVE[m]], V = X.verificacion || {};
    const exp = EXP[m];
    return aviso('bien', 'Revisión independiente del ' + F().fechaLarga(V.fecha), '<p>' + md(V.veredicto || '') + ' ' + fteT(fFicha(V, exp, exp, 'Verificación')) + '</p>') +
      h4('Qué se comprobó') + lista((V.que_se_comprobo || []).map(md)) +
      h4('Correcciones que dejó') + lista((V.correcciones || V.correcciones_al_readme || []).map(md)) +
      h4('Reservas') + lista((V.reservas || []).map(md));
  }

  function sLimites(m) {
    const X = FI.modelos[CLAVE[m]];
    const lim = cifra('modelo_limite_nivel_2026');
    return (lim ? aviso('atencion', 'Límite: el nivel de 2026', '<p>' + esc(lim.que_es) + '. ' + esc(lim.valor) + '. ' + fteT(fId('modelo_limite_nivel_2026')) + '</p>') : '') +
      lista((X.limites_y_riesgos || []).map(function (x) { return '<strong>' + md(x.limite) + '.</strong> ' + md(x.texto) + ' ' + fteT(fTexto(x.fuente, EXP[m], EXP[m], x.limite)); }));
  }

  function sE13() {
    const rec = cifra('modelo_e13_recomendacion'), imp = cifra('modelo_e13_imputar_empeora');
    const limObj = (g(FI, 'modelos.E11_V4.limites_y_riesgos', []) || []).filter(function (x) { return /^Objetivo viejo/.test(x.limite); })[0];
    const avisoScript = (FI.avisos_y_contradicciones || []).filter(function (a) { return a.tipo === 'recomendacion_sin_script'; })[0];
    let html = aviso('atencion', 'Dos objetivos distintos: no se mezclan',
      p('Las cifras oficiales de esta pantalla (' + pct(wapeFinal()) + ' el modelo final y ' + pct(wapeHibrido()) + ' el híbrido, frente a ' + pct(b1()) + ' de la regla manual) se miden con el objetivo original: los pasajeros de los viajes marcados como válidos. E13 propone un objetivo corregido, los pasajeros de todos los viajes que de verdad corrieron, y reentrena los dos modelos contra él. Sus errores son más bajos sobre todo porque el objetivo es más grande, así que no son comparables con los de arriba.') +
      (limObj ? p(limObj.texto, fteT(fTexto(limObj.fuente, 'E13', 'E11', 'Objetivo viejo'))) : '') +
      (avisoScript ? p('Pasar el objetivo corregido a producción es un paso pendiente: los programas que entrenan los dos modelos todavía usan el objetivo original. Por eso las cifras de E13 se citan aparte y siempre con su objetivo.', fteT(fTexto(avisoScript.donde || avisoScript.fuente || 'experimentos/E13_limpieza_datos/README.md', 'E13', 'no', 'Objetivo corregido en producción'))) : ''));
    if (rec && rec.valor) {
      const v = rec.valor, f = fId('modelo_e13_recomendacion');
      html += tabla([{ texto: 'Modelo reentrenado con el objetivo corregido' }, { texto: 'WAPE ' + ANIO_EVAL, num: true }, { texto: 'WAPE ' + ANIO_PRUEBA, num: true }], [
        fila([th('Modelo final (V4c)'), td(pct(v.V4c_2025) + ' ' + fte(f), 'num'), td(pct(v.V4c_2024) + ' ' + fte(f), 'num')]),
        fila([th('Híbrido (V4c + Chronos-2), el que E13 recomienda para despachar'), td(pct(v.hibrido_V4c_2025) + ' ' + fte(f), 'num tabla__mejor'), td(pct(v.hibrido_V4c_2024) + ' ' + fte(f), 'num tabla__mejor')]),
      ], { titulo: esc(rec.que_es) + ' (' + esc(rec.unidad) + ')', compacta: true });
    }
    if (imp && imp.valor) {
      const nombres = { imputacion_2025: 'Imputar los viajes sin registro', registro_parcial_2025: 'Completar los viajes con registro parcial', anomalias_automaticas_vs_E10_2025: 'Detectar anomalías de forma automática en vez de con las etiquetas de E10' };
      html += h4(imp.que_es) + tabla([{ texto: 'Qué se probó' }, { texto: 'Diferencia frente a V4c, ' + ANIO_EVAL + ' (positivo: empeora)', num: true }, { texto: 'Meses en que mejora', num: true }],
        claves(imp.valor).map(function (k) { const r = imp.valor[k] || {}; return fila([th(esc(nombres[k] || k)), td(difIc(r.dif, r.ic_inf, r.ic_sup) + ' ' + fte(fId('modelo_e13_imputar_empeora')), 'num'), td(num(r.meses_mejor), 'num')]); }), { compacta: true });
    }
    return html;
  }

  const SECCIONES = [
    { id: 'predice', titulo: '¿Qué predice?', porModelo: true, html: sPredice },
    { id: 'datos', titulo: '¿Con qué datos aprende?', porModelo: true, html: sDatos },
    { id: 'variables', titulo: '¿Qué variables usa y por qué?', porModelo: true, html: sVariables },
    { id: 'validacion', titulo: '¿Cómo se validó?', porModelo: true, html: sValidacion },
    { id: 'errores', titulo: '¿Cuánto se equivoca? Los tres frente a frente', porModelo: false, abierto: true, html: sErrores },
    { id: 'probado', titulo: '¿Qué se probó y se descartó?', porModelo: false, html: sProbado },
    { id: 'decisiones', titulo: 'Decisiones de diseño: qué ayudó y qué no', porModelo: true, html: sDecisiones },
    { id: 'produccion', titulo: 'En producción: reentrenar, tiempos y salidas', porModelo: true, html: sProduccion },
    { id: 'verificacion', titulo: '¿Cómo se verificó?', porModelo: true, html: sVerificacion },
    { id: 'limites', titulo: 'Límites y riesgos', porModelo: true, html: sLimites },
    { id: 'e13', titulo: 'Siguiente paso: el objetivo corregido (E13)', porModelo: false, abierto: true, html: sE13 },
  ];

  function htmlSeccion(s) {
    return '<details class="desplegable" id="modelo-s-' + s.id + '"' + (s.porModelo ? ' data-por-modelo' : '') + (s.abierto ? ' open' : '') + '>' +
      '<summary class="desplegable__resumen">' + icono('chevron-derecha', 'icono desplegable__chevron') + esc(s.titulo) +
      (s.porModelo ? '<span class="chip modelo__chip-seccion" data-modelo-chip="seccion">' + esc(NOMBRE[modeloActual]) + '</span>' : '<span class="chip">Los dos modelos</span>') + '</summary>' +
      '<div class="desplegable__cuerpo">' + (s.porModelo ? s.html(modeloActual) : s.html()) + '</div></details>';
  }
  function htmlDetalle() {
    const seg = '<fieldset class="segmentado" id="modelo-cual" aria-label="Modelo del detalle"><legend>Modelo del detalle</legend>' +
      ['final', 'hibrido'].map(function (m) { return '<label class="segmentado__opcion"><input type="radio" name="modelo-cual" value="' + m + '"' + (m === modeloActual ? ' checked' : '') + '><span class="segmentado__etiqueta">' + esc(NOMBRE[m]) + '</span></label>'; }).join('') + '</fieldset>';
    return '<section class="seccion seccion--separada" aria-labelledby="modelo-detalle-t">' +
      '<div class="seccion__cab"><h2 class="seccion__titulo" id="modelo-detalle-t">El detalle, modelo por modelo</h2>' + seg + '</div>' +
      '<p class="seccion__intro">Este selector cambia las secciones marcadas con el nombre del modelo; las que ponen frente a frente a los dos modelos y a la regla manual no cambian.</p>' +
      '<div class="pila" id="modelo-secciones">' + SECCIONES.map(htmlSeccion).join('') + '</div></section>';
  }

  function estilos() {
    return '<style>' +
      '.modelo__pestanas { display: none; }' +
      '.modelo__tarjeta { display: grid; gap: var(--e-4); align-content: start; }' +

      '.modelo__h4 { margin-top: var(--e-2); color: var(--tinta); font-size: var(--t-m); }' +
      '.modelo__dl { display: grid; grid-template-columns: max-content minmax(0, 1fr); gap: var(--e-1) var(--e-3); margin: 0; font-size: var(--t-s); }' +
      '.modelo__dl dt { color: var(--tinta-3); } .modelo__dl dd { margin: 0; min-width: 0; overflow-wrap: anywhere; }' +
      '.modelo__lista { margin: 0; padding-left: 20px; display: grid; gap: 6px; } .modelo__lista li { max-width: var(--ancho-texto); }' +
      '.modelo__barras { display: grid; gap: 6px; }' +
      '.modelo__barra { display: grid; grid-template-columns: minmax(0, 200px) 64px minmax(0, 1fr); gap: var(--e-2); align-items: center; font-size: var(--t-s); }' +
      '.modelo__barra-nombre { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }' +
      '.modelo__barra-pista { display: block; height: 8px; border-radius: 4px; background: var(--superficie-2); overflow: hidden; }' +
      '.modelo__barra-relleno { display: block; height: 100%; border-radius: 4px; background: var(--serie-modelo); }' +
      '.modelo__rayas { background-color: var(--c, var(--serie-modelo)); background-image: repeating-linear-gradient(-45deg, transparent 0 2px, var(--superficie) 2px 3.5px); }' +
      '.modelo__comando { display: block; white-space: pre-wrap; padding: var(--e-2) var(--e-3); border-radius: var(--radio-s); background: var(--superficie-2); font-size: 12px; }' +
      '.modelo__chip-seccion { margin-left: auto; }' +
      '.modelo .desplegable__cuerpo > .cifras + .modelo__h4, .modelo .desplegable__cuerpo > .tabla-marco + .modelo__h4 { margin-top: var(--e-3); }' +
      '.modelo .desplegable__cuerpo .tabla td .fuente { width: 24px; height: 24px; margin: -4px 0 -4px 2px; vertical-align: middle; }' +
      '.modelo__papel { color: var(--acento); font-size: var(--t-s); font-weight: var(--peso-fuerte); }' +
      '.modelo .grafico__sub { max-width: none; }' +
      '@media (max-width: 900px) { .modelo__graficos { grid-template-columns: minmax(0, 1fr); } }' +
      '@media (max-width: 600px) { .modelo__pestanas { display: flex; } .modelo__barra { grid-template-columns: minmax(0, 1fr) 64px; } .modelo__barra-pista { grid-column: 1 / -1; } }' +
      '</style>';
  }

  // ---- Comportamiento -----------------------------------------------------------------------------------------
  function enTelefono() { return mq ? mq.matches : false; }
  function aplicarPestanas() {
    const telefono = enTelefono();
    ['final', 'hibrido'].forEach(function (m) {
      const tarjeta = cont.querySelector('#modelo-tarjeta-' + m), tab = cont.querySelector('#modelo-pestana-' + m);
      if (tarjeta) {
        tarjeta.hidden = telefono && m !== modeloActual;
        if (telefono) { tarjeta.setAttribute('role', 'tabpanel'); tarjeta.setAttribute('aria-labelledby', 'modelo-pestana-' + m); }
        else { tarjeta.removeAttribute('role'); tarjeta.removeAttribute('aria-labelledby'); }
      }
      if (tab) { tab.setAttribute('aria-selected', m === modeloActual ? 'true' : 'false'); tab.tabIndex = m === modeloActual ? 0 : -1; }
    });
  }
  function pintarDetalle() {
    cont.querySelectorAll('details[data-por-modelo]').forEach(function (det) {
      const s = SECCIONES.filter(function (x) { return 'modelo-s-' + x.id === det.id; })[0];
      const cuerpo = det.querySelector('.desplegable__cuerpo');
      if (s && cuerpo) cuerpo.innerHTML = s.html(modeloActual);
    });
    cont.querySelectorAll('[data-modelo-chip="seccion"]').forEach(function (ch) { ch.textContent = NOMBRE[modeloActual]; });
    global.COMPONENTES.cifras(cont);
    global.COMPONENTES.fuentes(cont);
  }
  function cambiarModelo(m, avisarApp) {
    if (m !== 'final' && m !== 'hibrido') return;
    const cambia = m !== modeloActual;
    modeloActual = m;
    const radio = cont && cont.querySelector('#modelo-cual input[value="' + m + '"]');
    if (radio && !radio.checked) radio.checked = true;
    if (cambia) { pintarDetalle(); aplicarPestanas(); }
    if (avisarApp && global.app && typeof global.app.ponerEstado === 'function') global.app.ponerEstado({ modelo: m });
  }
  function conectar() {
    const C = global.COMPONENTES;
    C.cifras(cont); C.fuentes(cont); C.tablaGrafico(cont);
    C.segmentado(cont.querySelector('#modelo-cual'), function (v) { cambiarModelo(v, true); });
    // Pestañas del teléfono: eligen la tarjeta visible y, de paso, el modelo del detalle.
    const tabs = Array.prototype.slice.call(cont.querySelectorAll('#modelo-pestanas [role="tab"]'));
    tabs.forEach(function (tab, i) {
      tab.addEventListener('click', function () { cambiarModelo(tab.dataset.modelo, true); aplicarPestanas(); });
      tab.addEventListener('keydown', function (e) {
        const d = e.key === 'ArrowRight' ? 1 : e.key === 'ArrowLeft' ? -1 : e.key === 'Home' ? -i : e.key === 'End' ? tabs.length - 1 - i : 0;
        if (d) { e.preventDefault(); const t = tabs[(i + d + tabs.length) % tabs.length]; cambiarModelo(t.dataset.modelo, true); aplicarPestanas(); t.focus(); }
      });
    });
    mq = global.matchMedia ? global.matchMedia('(max-width: 600px)') : null;
    if (mq) { mqOyente = function () { aplicarPestanas(); }; mq.addEventListener('change', mqOyente); }
    aplicarPestanas();
    // Gráficos: se crean la primera vez que su lienzo tiene tamaño (al abrir la sección) y se redimensionan después.
    Object.keys(lienzos).forEach(function (id) {
      lienzos[id].el = cont.querySelector('#' + id);
      C.leyenda(cont.querySelector('#' + id + '-leyenda'), function () { return graficos[id]; });
    });
    if (global.ResizeObserver) {
      vigilante = new ResizeObserver(function (entradas) {
        entradas.forEach(function (en) {
          const id = en.target.id;
          if (!en.target.clientWidth) return;
          if (graficos[id]) graficos[id].resize(); else crearGrafico(id);
        });
      });
      Object.keys(lienzos).forEach(function (id) { if (lienzos[id].el) vigilante.observe(lienzos[id].el); });
    } else {
      Object.keys(lienzos).forEach(crearGrafico);
    }
  }

  // ---- Contrato de la pantalla --------------------------------------------------------------------------------
  function render(contenedor, datos, estado) {
    salir();
    cont = contenedor; estadoApp = estado || {};
    D = g(datos, 'pantallas.modelo') || {}; INI = g(datos, 'pantallas.inicio') || null; FI = D.ficha || null; CONTRA = (datos && datos.contradicciones) || null;
    modeloActual = estadoApp.modelo === 'final' ? 'final' : 'hibrido';
    popMapa = new Map(); nPop = 0; lienzos = {}; graficos = {};
    popovers = document.createElement('div'); popovers.className = 'modelo__popovers';
    cont.classList.add('modelo');
    if (!FI || !FI.modelos) {
      cont.innerHTML = aviso('atencion', 'Faltan los datos de la pantalla', '<p>No encuentro <code>DATOS_APP.pantallas.modelo.ficha</code>. Genera <code>app/datos_app.js</code> con <code>app/generar_datos_app.py</code> y vuelve a abrir la app.</p>');
      return;
    }
    cont.innerHTML = estilos() + htmlResumen() + htmlLectura() + htmlDetalle();
    cont.appendChild(popovers);
    conectar();
  }
  function actualizar(estado) {
    estadoApp = estado || estadoApp;
    if (estadoApp && (estadoApp.modelo === 'final' || estadoApp.modelo === 'hibrido') && estadoApp.modelo !== modeloActual) cambiarModelo(estadoApp.modelo, false);
  }
  function salir() {
    Object.keys(graficos).forEach(function (id) { try { graficos[id].dispose(); } catch (e) { /* ya destruido */ } });
    graficos = {}; lienzos = {};
    if (vigilante) { vigilante.disconnect(); vigilante = null; }
    if (mq && mqOyente) { mq.removeEventListener('change', mqOyente); mqOyente = null; }
  }
  function subtituloInicial() {
    const datos = global.DATOS_APP;
    const fi = g(datos, 'pantallas.modelo.ficha');
    if (fi && fi.modelos) {
      D = g(datos, 'pantallas.modelo'); INI = g(datos, 'pantallas.inicio') || null; FI = fi;
      const h = hPrincipal();
      const s = 'A ' + h + ' días, el modelo final se equivoca en el ' + pct(wapeFinal()) + ' de los pasajeros y el híbrido, recomendado para producción, en el ' + pct(wapeHibrido()) + '; la regla manual de Sobusa, en el ' + pct(b1()) + '.';
      D = null; INI = null; FI = null;
      return s;
    }
    return 'Dos modelos de árboles frente a la regla manual de Sobusa: el final de E11 y el híbrido de E12, recomendado para producción.';
  }

  const def = {
    id: 'modelo',
    pregunta: '¿Qué modelo es y por qué?',
    subtitulo: subtituloInicial(),
    icono: 'modelo',
    interruptor: [],      // Hoy / Con el modelo / Oráculo no aplica: la pantalla compara los dos modelos con la regla manual.
    modulo: null,
    render: render,
    actualizar: actualizar,
    salir: salir,
  };
  // app.html define registrarPantalla antes de cargar las pantallas; si faltara, queda en la cola que app.js recoge al arrancar.
  if (typeof global.registrarPantalla === 'function') global.registrarPantalla(def);
  else (global.__pantallasRegistradas = global.__pantallasRegistradas || []).push(def);
  global.PANTALLA_MODELO = def;
})(window);
