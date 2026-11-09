// Sobusa Despacho · tema_echarts.js
// Tema de ECharts derivado de los tokens de tokens.css. No contiene ningún color escrito a mano:
// lee los tokens de :root y construye window.TEMA_ECHARTS.claro (la app es solo clara desde el
// 19-oct-2026: ya no hay tema oscuro de ECharts ni hay que observar el cambio de tema). Sigue el método dataviz: marcas finas, rejilla hairline sólida,
// barras de 24 px como máximo con la punta redondeada, líneas de 2 px, marcadores de 8 px con anillo
// del color de la superficie, tooltip con todas las series y texto en los tokens de texto.
//
// Uso:
//   TEMA_ECHARTS.registrar(echarts);                       // registra 'sobusa-claro'
//   const g = TEMA_ECHARTS.init(echarts, el);              // init con el tema claro
//   g.setOption({ series: [ Object.assign({ name: 'Con el modelo', type: 'line', data }, TEMA_ECHARTS.serie('modelo')) ] });
//
// Roles de serie: 'hoy' (gris de desénfasis), 'modelo' (acento), 'oraculo' (tinta a trazos),
// 'real' (tinta, más gruesa), 'motor' (acento a trazos), 'silencio', 'cra54', 'cl72' (rutas).
(function (global) {
  'use strict';

  const TOKENS = {
    fondo: '--fondo', superficie: '--superficie', superficie2: '--superficie-2', linea: '--linea', lineaFuerte: '--linea-fuerte',
    tinta: '--tinta', tinta2: '--tinta-2', tinta3: '--tinta-3', acento: '--acento', acentoSuave: '--acento-suave',
    serieModelo: '--serie-modelo', serieHoy: '--serie-hoy', serieReal: '--serie-real', serieOraculo: '--serie-oraculo',
    rutaSilencio: '--ruta-silencio', rutaCra54: '--ruta-cra54', rutaCl72: '--ruta-cl72',
    bien: '--bien', atencion: '--atencion', critico: '--critico', rejilla: '--rejilla', eje: '--eje',
    sombra: '--sombra-3', fuente: '--fuente-texto',
  };
  const NOMBRE = { claro: 'sobusa-claro' };
  const cache = {};
  let avisado = false;

  function leerTokens() {
    const estilo = getComputedStyle(document.documentElement);
    const t = {};
    Object.keys(TOKENS).forEach(function (k) { t[k] = estilo.getPropertyValue(TOKENS[k]).trim(); });
    if (!t.tinta && !avisado) {
      avisado = true;
      console.warn('TEMA_ECHARTS: no encuentro los tokens; ¿está cargado app/tokens.css?');
    }
    return t;
  }

  function construir(t) {
    const ejeCategoria = {
      axisLine: { show: true, lineStyle: { color: t.eje, width: 1 } },
      axisTick: { show: false },
      axisLabel: { color: t.tinta3, fontSize: 12, margin: 10 },
      splitLine: { show: false },
      splitArea: { show: false },
      nameTextStyle: { color: t.tinta2, fontSize: 12 },
    };
    const ejeValor = {
      splitNumber: 4,
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: t.tinta3, fontSize: 12, margin: 10 },
      splitLine: { show: true, lineStyle: { color: t.rejilla, width: 1, type: 'solid' } },
      splitArea: { show: false },
      nameTextStyle: { color: t.tinta3, fontSize: 12 },
    };
    // Movimiento corto; ninguno si el sistema pide movimiento reducido.
    const reducido = !!(global.matchMedia && global.matchMedia('(prefers-reduced-motion: reduce)').matches);
    return {
      animationDuration: reducido ? 0 : 500,
      animationDurationUpdate: reducido ? 0 : 300,
      animationEasing: 'cubicOut',
      // Orden categórico fijo: las tres rutas (nunca se cicla); después, el modelo y el hoy.
      color: [t.rutaSilencio, t.rutaCra54, t.rutaCl72, t.serieModelo, t.serieHoy],
      backgroundColor: 'transparent',
      textStyle: { fontFamily: t.fuente, color: t.tinta2, fontSize: 12 },
      title: {
        textStyle: { color: t.tinta, fontFamily: t.fuente, fontWeight: 600, fontSize: 15 },
        subtextStyle: { color: t.tinta2, fontFamily: t.fuente, fontSize: 12 },
      },
      grid: { left: 8, right: 16, top: 24, bottom: 8, containLabel: true },
      legend: {
        textStyle: { color: t.tinta2, fontSize: 12, fontFamily: t.fuente },
        inactiveColor: t.linea,
        icon: 'roundRect',
        itemWidth: 14,
        itemHeight: 8,
        itemGap: 16,
        lineStyle: { width: 2 },
      },
      tooltip: {
        backgroundColor: t.superficie,
        borderColor: t.linea,
        borderWidth: 1,
        padding: [8, 12],
        textStyle: { color: t.tinta, fontFamily: t.fuente, fontSize: 13 },
        extraCssText: 'box-shadow:' + t.sombra + ';border-radius:8px;',
        axisPointer: {
          type: 'line',
          lineStyle: { color: t.eje, width: 1, type: 'solid' },
          crossStyle: { color: t.eje, width: 1, type: 'solid' },
          shadowStyle: { color: t.superficie2, opacity: 0.6 },
        },
      },
      axisPointer: {
        lineStyle: { color: t.eje, width: 1, type: 'solid' },
        label: { backgroundColor: t.tinta, color: t.fondo, fontFamily: t.fuente },
      },
      categoryAxis: ejeCategoria,
      timeAxis: ejeCategoria,
      valueAxis: ejeValor,
      logAxis: ejeValor,
      line: {
        lineStyle: { width: 2, cap: 'round', join: 'round' },
        symbol: 'circle',
        symbolSize: 8,
        showSymbol: false,
        smooth: false,
        itemStyle: { borderWidth: 2, borderColor: t.superficie },
        emphasis: { lineStyle: { width: 3 }, focus: 'none' },
        label: { color: t.tinta2, fontFamily: t.fuente },
        endLabel: { color: t.tinta2, fontFamily: t.fuente, fontSize: 12 },
      },
      bar: {
        barMaxWidth: 24,
        barGap: '12%',
        barCategoryGap: '30%',
        itemStyle: { borderRadius: [4, 4, 0, 0] },
        label: { color: t.tinta2, fontFamily: t.fuente, fontSize: 11 },
      },
      scatter: { symbolSize: 8, itemStyle: { borderWidth: 2, borderColor: t.superficie } },
      heatmap: { itemStyle: { borderColor: t.superficie, borderWidth: 2 } },
      markLine: { lineStyle: { color: t.tinta3, width: 1, type: 'dashed' }, label: { color: t.tinta2, fontFamily: t.fuente } },
      markPoint: { label: { color: t.tinta, fontFamily: t.fuente } },
      dataZoom: {
        borderColor: t.linea,
        fillerColor: t.acentoSuave,
        handleStyle: { color: t.superficie, borderColor: t.lineaFuerte },
        moveHandleStyle: { color: t.lineaFuerte },
        textStyle: { color: t.tinta2 },
        dataBackground: { lineStyle: { color: t.lineaFuerte }, areaStyle: { color: t.superficie2 } },
        selectedDataBackground: { lineStyle: { color: t.acento }, areaStyle: { color: t.acentoSuave } },
      },
      visualMap: { textStyle: { color: t.tinta2, fontFamily: t.fuente } },
      timeline: { lineStyle: { color: t.linea }, itemStyle: { color: t.tinta3 }, label: { color: t.tinta2 }, controlStyle: { color: t.tinta2, borderColor: t.tinta2 }, checkpointStyle: { color: t.acento, borderColor: t.acentoSuave } },
      toolbox: { iconStyle: { borderColor: t.tinta3 }, emphasis: { iconStyle: { borderColor: t.acento } } },
    };
  }

  // Solo modo claro: «modo» se acepta por compatibilidad y siempre es 'claro'.
  function tokens() {
    if (!cache.claro) cache.claro = leerTokens();
    return cache.claro;
  }

  function tema() {
    if (!cache.tema_claro) cache.tema_claro = construir(tokens());
    return cache.tema_claro;
  }

  function modoActual() { return 'claro'; }

  // Estilo por rol de serie (color y tipo de línea). Se mezcla con Object.assign en la serie.
  function serie(rol) {
    const t = tokens();
    switch (rol) {
      case 'hoy': return { color: t.serieHoy, lineStyle: { type: 'solid', width: 2 }, itemStyle: { color: t.serieHoy } };
      case 'modelo': return { color: t.serieModelo, lineStyle: { type: 'solid', width: 2 }, itemStyle: { color: t.serieModelo } };
      case 'motor': return { color: t.serieModelo, lineStyle: { type: 'dashed', width: 2 }, itemStyle: { color: t.serieModelo } };
      case 'oraculo': return { color: t.serieOraculo, lineStyle: { type: 'dashed', width: 2 }, itemStyle: { color: t.serieOraculo } };
      case 'real': return { color: t.serieReal, lineStyle: { type: 'solid', width: 2.5 }, itemStyle: { color: t.serieReal } };
      case 'silencio': return { color: t.rutaSilencio, itemStyle: { color: t.rutaSilencio } };
      case 'cra54': return { color: t.rutaCra54, itemStyle: { color: t.rutaCra54 } };
      case 'cl72': return { color: t.rutaCl72, itemStyle: { color: t.rutaCl72 } };
      default: return {};
    }
  }

  // Color de un rol o de una ruta por su nombre tal como aparece en los datos.
  function color(rolORuta) {
    const t = tokens();
    const mapa = { hoy: t.serieHoy, modelo: t.serieModelo, motor: t.serieModelo, oraculo: t.serieOraculo, real: t.serieReal,
      silencio: t.rutaSilencio, SILENCIO: t.rutaSilencio, cra54: t.rutaCra54, 'CRA 54': t.rutaCra54, cl72: t.rutaCl72, 'CL 72': t.rutaCl72,
      bien: t.bien, atencion: t.atencion, critico: t.critico, acento: t.acento };
    return mapa[rolORuta] || t.tinta2;
  }

  function registrar(echarts) {
    echarts.registerTheme(NOMBRE.claro, tema());
    return NOMBRE;
  }

  function init(echarts, el, opciones) {
    if (!echarts._temaSobusa) { registrar(echarts); echarts._temaSobusa = true; }
    return echarts.init(el, NOMBRE.claro, Object.assign({ renderer: 'canvas' }, opciones || {}));
  }

  function refrescar() { Object.keys(cache).forEach(function (k) { delete cache[k]; }); }

  global.TEMA_ECHARTS = {
    get claro() { return tema(); },
    nombres: NOMBRE,
    tokens: tokens,
    tema: tema,
    modoActual: modoActual,
    nombre: function () { return NOMBRE.claro; },
    serie: serie,
    color: color,
    registrar: registrar,
    init: init,
    refrescar: refrescar,
  };
})(window);
