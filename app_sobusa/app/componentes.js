// Sobusa Despacho · componentes.js
// Comportamiento mínimo de los componentes de componentes.css (sin frameworks):
// cifras que cuentan al cambiar, popover de fuente, interruptor segmentado, pestañas, leyenda que
// aísla series, tabla gemela de un gráfico, barra lateral (plegar) y formato de números es-CO.
// Uso: COMPONENTES.iniciar(document) después de cargar el DOM; cada función se puede llamar aparte.
(function (global) {
  'use strict';

  const reducido = function () { return global.matchMedia && global.matchMedia('(prefers-reduced-motion: reduce)').matches; };
  const duracion = function (nombre, porDefecto) {
    const v = parseFloat(getComputedStyle(document.documentElement).getPropertyValue(nombre));
    return isNaN(v) ? porDefecto : v;
  };

  // ---- Formato -------------------------------------------------------------------------------
  const formato = {
    numero: function (v, decimales) {
      if (v === null || v === undefined || isNaN(v)) return '—';
      return new Intl.NumberFormat('es-CO', { minimumFractionDigits: decimales || 0, maximumFractionDigits: decimales || 0 }).format(v);
    },
    signo: function (v, decimales, unidad) {
      const s = v > 0 ? '+' : v < 0 ? '−' : '';
      return s + formato.numero(Math.abs(v), decimales) + (unidad ? ' ' + unidad : '');
    },
    // Fechas AAAA-MM-DD sin pasar por Date (sin husos horarios): «3 jun 2025», «3 jun», «3 de junio de 2025».
    fecha: function (iso) { const p = partesFecha(iso); return p ? p.d + ' ' + MESES[p.m - 1] + ' ' + p.a : iso; },
    fechaCorta: function (iso) { const p = partesFecha(iso); return p ? p.d + ' ' + MESES[p.m - 1] : iso; },
    fechaLarga: function (iso) { const p = partesFecha(iso); return p ? p.d + ' de ' + MESES_LARGOS[p.m - 1] + ' de ' + p.a : iso; },
  };
  const MESES = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic'];
  const MESES_LARGOS = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre'];
  function partesFecha(iso) {
    const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(iso || ''));
    return m ? { a: +m[1], m: +m[2], d: +m[3] } : null;
  }

  // ---- Cifras que cuentan --------------------------------------------------------------------
  // <span data-cifra="13.94" data-decimales="2">13,94</span>  → ponerCifra(el, nuevoValor) anima el cambio.
  function ponerCifra(el, valor, opciones) {
    const dec = parseInt(el.dataset.decimales || (opciones && opciones.decimales) || 0, 10);
    const desde = parseFloat(el.dataset.cifra);
    const hasta = Number(valor);
    el.dataset.cifra = String(hasta);
    const dur = duracion('--dur-4', 600);
    if (reducido() || isNaN(desde) || desde === hasta || dur === 0) { el.textContent = formato.numero(hasta, dec); return; }
    const t0 = performance.now();
    if (el._animacion) cancelAnimationFrame(el._animacion);
    const paso = function (ahora) {
      const p = Math.min(1, (ahora - t0) / dur);
      const suave = 1 - Math.pow(1 - p, 3);
      el.textContent = formato.numero(desde + (hasta - desde) * suave, dec);
      if (p < 1) el._animacion = requestAnimationFrame(paso); else el._animacion = null;
    };
    el._animacion = requestAnimationFrame(paso);
  }
  function cifras(raiz) {
    (raiz || document).querySelectorAll('[data-cifra]').forEach(function (el) {
      if (!el.textContent.trim()) el.textContent = formato.numero(parseFloat(el.dataset.cifra), parseInt(el.dataset.decimales || 0, 10));
    });
  }

  // ---- Popover de fuente ---------------------------------------------------------------------
  // <button class="fuente" popovertarget="f1" aria-expanded="false">…</button> <div id="f1" class="fuente-pop" popover>…</div>
  const soportaPopover = typeof HTMLElement !== 'undefined' && 'popover' in HTMLElement.prototype;
  function colocarPopover(pop, boton) {
    const r = boton.getBoundingClientRect();
    const ancho = pop.offsetWidth || 380;
    const alto = pop.offsetHeight || 200;
    let izq = Math.min(Math.max(16, r.left), global.innerWidth - ancho - 16);
    let arriba = r.bottom + 8;
    if (arriba + alto > global.innerHeight - 16) arriba = Math.max(16, r.top - alto - 8);
    pop.style.left = izq + 'px';
    pop.style.top = arriba + 'px';
  }
  // Cada popover busca su botón al abrirse (el que lleve popovertarget o data-fuente con su id): así un mismo botón
  // puede cambiar de fuente al mover el interruptor, y los popovers creados después también funcionan.
  function invocadorDe(pop) {
    return document.querySelector('[popovertarget="' + pop.id + '"], [data-fuente="' + pop.id + '"]');
  }
  // Nombre accesible del botón «fuente»: «Fuente: <cifra>», con la etiqueta de la ficha, la fila o el gráfico más
  // cercano y el título del popover. Así un lector de pantalla distingue un botón de otro.
  function nombrarFuente(boton) {
    const actual = boton.getAttribute('aria-label') || '';
    if (actual && actual !== 'Fuente de la cifra') return;
    const pop = document.getElementById(boton.getAttribute('popovertarget') || boton.getAttribute('data-fuente') || '');
    const tPop = pop ? ((pop.querySelector('.fuente-pop__titulo') || {}).textContent || '').replace(/^\s*Fuentes?\s*·?\s*/, '').trim() : '';
    const cerca = boton.closest('.cifra, tr, .grafico, .aviso, li, .tarjeta');
    let et = '';
    if (cerca) {
      const e = cerca.matches('tr') ? cerca.querySelector('th, td') : cerca.querySelector('.cifra__etiqueta, .grafico__titulo, .aviso__titulo, .rotulo, strong');
      et = e ? e.textContent.replace(/\s+/g, ' ').trim() : '';
    }
    const visible = (boton.textContent || '').trim();
    const partes = [et, tPop].filter(function (x, i, a) { return x && x !== visible && a.indexOf(x) === i; });
    if (partes.length) boton.setAttribute('aria-label', (visible || 'Fuente') + ': ' + partes.join(' · ').slice(0, 140));
    else if (visible) boton.removeAttribute('aria-label');
  }
  function fuentes(raiz) {
    const r = raiz || document;
    r.querySelectorAll('.fuente[popovertarget], .fuente[data-fuente]').forEach(function (boton) {
      if (!boton.hasAttribute('aria-expanded')) boton.setAttribute('aria-expanded', 'false');
      nombrarFuente(boton);
    });
    r.querySelectorAll('.fuente-pop').forEach(function (pop) {
      if (pop._fuenteLista) return;
      pop._fuenteLista = true;
      if (soportaPopover && pop.hasAttribute('popover')) {
        pop.addEventListener('beforetoggle', function (e) { if (e.newState === 'open') { pop.style.left = '-9999px'; pop.style.top = '0'; } });
        pop.addEventListener('toggle', function (e) {
          const abierto = e.newState === 'open';
          const boton = invocadorDe(pop);
          if (boton) boton.setAttribute('aria-expanded', abierto ? 'true' : 'false');
          if (abierto && boton) colocarPopover(pop, boton);
        });
        pop.querySelectorAll('[data-cerrar]').forEach(function (b) {
          b.addEventListener('click', function () { const boton = invocadorDe(pop); pop.hidePopover(); if (boton) boton.focus(); });
        });
      } else {
        // Alternativa sin Popover API: hidden + clic fuera + Esc, con delegación para que valga cualquier botón.
        pop.removeAttribute('popover');
        pop.hidden = true;
        const cerrar = function () { pop.hidden = true; const boton = invocadorDe(pop); if (boton) boton.setAttribute('aria-expanded', 'false'); document.removeEventListener('click', fuera, true); document.removeEventListener('keydown', tecla); };
        const fuera = function (e) { if (!pop.contains(e.target) && e.target !== invocadorDe(pop)) cerrar(); };
        const tecla = function (e) { if (e.key === 'Escape') { cerrar(); const boton = invocadorDe(pop); if (boton) boton.focus(); } };
        pop._abrir = function (boton) { pop.hidden = false; colocarPopover(pop, boton); boton.setAttribute('aria-expanded', 'true'); setTimeout(function () { document.addEventListener('click', fuera, true); document.addEventListener('keydown', tecla); }, 0); };
        pop._cerrar = cerrar;
        pop.querySelectorAll('[data-cerrar]').forEach(function (b) { b.addEventListener('click', function () { cerrar(); const boton = invocadorDe(pop); if (boton) boton.focus(); }); });
      }
    });
    if (!soportaPopover && !document._fuentesDelegado) {
      document._fuentesDelegado = true;
      document.addEventListener('click', function (e) {
        const boton = e.target.closest('.fuente[popovertarget], .fuente[data-fuente]');
        if (!boton) return;
        const pop = document.getElementById(boton.getAttribute('popovertarget') || boton.dataset.fuente);
        if (!pop || !pop._abrir) return;
        if (pop.hidden) pop._abrir(boton); else pop._cerrar();
      });
    }
  }

  // ---- Interruptor segmentado ---------------------------------------------------------------
  function segmentado(fieldset, callback) {
    if (!fieldset) return;
    fieldset.addEventListener('change', function (e) {
      if (e.target.matches('input[type="radio"]')) callback(e.target.value, e.target);
    });
    const marcado = fieldset.querySelector('input[type="radio"]:checked');
    return marcado ? marcado.value : null;
  }

  // ---- Pestañas ------------------------------------------------------------------------------
  // <div class="pestanas" role="tablist"><button class="pestana" role="tab" aria-selected="true" aria-controls="p1">…</button></div>
  function pestanas(lista, callback) {
    if (!lista) return;
    const tabs = Array.from(lista.querySelectorAll('[role="tab"]'));
    const activar = function (tab, foco) {
      tabs.forEach(function (t) {
        const activa = t === tab;
        t.setAttribute('aria-selected', activa ? 'true' : 'false');
        t.tabIndex = activa ? 0 : -1;
        const panel = document.getElementById(t.getAttribute('aria-controls'));
        if (panel) panel.hidden = !activa;
      });
      if (foco) tab.focus();
      if (callback) callback(tab.dataset.pestana || tab.id, tab);
    };
    tabs.forEach(function (tab, i) {
      tab.addEventListener('click', function () { activar(tab); });
      tab.addEventListener('keydown', function (e) {
        const d = e.key === 'ArrowRight' ? 1 : e.key === 'ArrowLeft' ? -1 : e.key === 'Home' ? -i : e.key === 'End' ? tabs.length - 1 - i : 0;
        if (d) { e.preventDefault(); activar(tabs[(i + d + tabs.length) % tabs.length], true); }
      });
    });
    const inicial = tabs.find(function (t) { return t.getAttribute('aria-selected') === 'true'; }) || tabs[0];
    if (inicial) activar(inicial);
    return activar;
  }

  // ---- Leyenda que aísla series de un gráfico ECharts ----------------------------------------
  // <ul class="leyenda"><li><button class="leyenda__item" data-serie="Hoy" aria-pressed="true">…</button></li></ul>
  function leyenda(ul, obtenerGrafico) {
    if (!ul) return;
    ul.querySelectorAll('.leyenda__item[data-serie]').forEach(function (b) {
      if (!b.hasAttribute('aria-pressed')) b.setAttribute('aria-pressed', 'true');
      b.addEventListener('click', function () {
        const g = typeof obtenerGrafico === 'function' ? obtenerGrafico() : obtenerGrafico;
        const activo = b.getAttribute('aria-pressed') !== 'false';
        b.setAttribute('aria-pressed', activo ? 'false' : 'true');
        if (g) g.dispatchAction({ type: activo ? 'legendUnSelect' : 'legendSelect', name: b.dataset.serie });
      });
    });
  }

  // ---- Tabla gemela de un gráfico ------------------------------------------------------------
  // <figure class="grafico"><button data-ver-tabla>Ver tabla</button><div class="grafico__lienzo"></div><div class="grafico__tabla" hidden>…</div></figure>
  function tablaGrafico(figura) {
    (figura || document).querySelectorAll('[data-ver-tabla]').forEach(function (b) {
      const fig = b.closest('.grafico');
      if (!fig || b._tablaLista) return;   // una sola vez por botón: la app y la pantalla pueden llamarla las dos
      b._tablaLista = true;
      const lienzo = fig.querySelector('.grafico__lienzo');
      const tabla = fig.querySelector('.grafico__tabla');
      const leyendaEl = fig.querySelector('.leyenda');
      if (!lienzo || !tabla) return;
      b.removeAttribute('aria-pressed');
      if (!tabla.id) tabla.id = (fig.id || 'grafico-' + Math.random().toString(36).slice(2, 8)) + '-tabla';
      b.setAttribute('aria-controls', tabla.id);
      const textoGrafico = b.dataset.textoGrafico || 'Ver gráfico';
      const textoTabla = b.dataset.textoTabla || b.textContent.trim() || 'Ver tabla';
      b.addEventListener('click', function () {
        const mostrarTabla = tabla.hidden;
        tabla.hidden = !mostrarTabla;
        lienzo.hidden = mostrarTabla;
        if (leyendaEl) leyendaEl.hidden = mostrarTabla;
        const texto = b.querySelector('[data-texto]') || b;
        texto.textContent = mostrarTabla ? textoGrafico : textoTabla;
      });
    });
  }

  // ---- Barra lateral: plegar (la app es solo clara: no hay botón de tema ni se guarda un tema) ----
  const CLAVE_LATERAL = 'sobusa-despacho-lateral';
  function guardar(clave, valor) { try { localStorage.setItem(clave, valor); } catch (e) { /* sin almacenamiento */ } }
  function leer(clave) { try { return localStorage.getItem(clave); } catch (e) { return null; } }
  function lateral(app) {
    app = app || document.querySelector('.app');
    if (!app) return;
    if (leer(CLAVE_LATERAL) === 'plegada') app.classList.add('app--plegada');
    const rotularPlegar = function (b, plegada) {
      const t = plegada ? 'Desplegar la barra' : 'Plegar la barra';
      b.setAttribute('aria-label', t);
      const tip = b.querySelector('.tooltip'); if (tip) tip.textContent = t;
    };
    app.querySelectorAll('[data-plegar]').forEach(function (b) {
      b.removeAttribute('aria-pressed');
      rotularPlegar(b, app.classList.contains('app--plegada'));
      b.addEventListener('click', function () {
        const plegada = app.classList.toggle('app--plegada');
        rotularPlegar(b, plegada);
        guardar(CLAVE_LATERAL, plegada ? 'plegada' : 'abierta');
        // Los gráficos se redimensionan cuando termina la transición de la rejilla, no durante ella.
        let hecho = false;
        const avisar = function () { if (hecho) return; hecho = true; app.removeEventListener('transitionend', alFinal); global.dispatchEvent(new Event('resize')); };
        const alFinal = function (e) { if (e.target === app) avisar(); };
        app.addEventListener('transitionend', alFinal);
        setTimeout(avisar, duracion('--dur-3', 320) + 50);
      });
    });
  }

  function iniciar(raiz) {
    raiz = raiz || document;
    cifras(raiz);
    fuentes(raiz);
    tablaGrafico(raiz);
    lateral(raiz.querySelector ? raiz.querySelector('.app') : null);
  }

  global.COMPONENTES = {
    formato: formato,
    ponerCifra: ponerCifra,
    cifras: cifras,
    fuentes: fuentes,
    segmentado: segmentado,
    pestanas: pestanas,
    leyenda: leyenda,
    tablaGrafico: tablaGrafico,
    lateral: lateral,
    iniciar: iniciar,
  };
})(window);
