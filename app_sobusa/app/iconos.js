// Sobusa Despacho · iconos.js
// Una sola familia de iconos (trazo de 1,75 px, rejilla de 24 × 24, puntas redondas), inyectada como
// sprite SVG en línea porque <use href="archivo.svg#id"> no funciona desde file://.
// Uso en HTML:  <svg class="icono" aria-hidden="true"><use href="#i-inicio"></use></svg>
// Uso en JS:    ICONOS.svg('inicio', 'icono icono--l')  →  cadena con el SVG.
(function (global) {
  'use strict';
  const ICONOS = {
    inicio: '<path d="M3 11l9-8 9 8"/><path d="M5 10v10h14V10"/><path d="M10 20v-6h4v6"/>',
    demanda: '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20a6.5 6.5 0 0 1 13 0"/><circle cx="17" cy="9" r="2.5"/><path d="M15.5 20h6a5.5 5.5 0 0 0-4-5.3"/>',
    modelo: '<rect x="6" y="6" width="12" height="12" rx="2"/><rect x="9.5" y="9.5" width="5" height="5" rx="1"/><path d="M9 2v4M15 2v4M9 18v4M15 18v4M2 9h4M2 15h4M18 9h4M18 15h4"/>',
    horario: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    despacho: '<circle cx="12" cy="12" r="2.5"/><path d="M7.5 7.5a6.5 6.5 0 0 0 0 9M16.5 7.5a6.5 6.5 0 0 1 0 9"/><path d="M4.5 4.5a10.5 10.5 0 0 0 0 15M19.5 4.5a10.5 10.5 0 0 1 0 15"/>',
    ciudad: '<path d="M3 21h18"/><path d="M5 21V8l6-3v16"/><path d="M11 21V11l8 2v8"/><path d="M8 9v.01M8 12v.01M8 15v.01M15 15v.01M15 18v.01"/>',
    resultado: '<path d="M3 17l6-6 4 4 8-8"/><path d="M15 7h6v6"/>',
    piloto: '<path d="M9 3h6"/><path d="M10 3v6L4.5 19a1.5 1.5 0 0 0 1.3 2.2h12.4a1.5 1.5 0 0 0 1.3-2.2L14 9V3"/><path d="M7 15h10"/>',
    metodo: '<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v14c0 1.7 3.6 3 8 3s8-1.3 8-3V5"/><path d="M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3"/>',
    bus: '<rect x="4" y="3" width="16" height="15" rx="3"/><path d="M4 10h16"/><path d="M7 18v2.5M17 18v2.5"/><path d="M8 14h.01M16 14h.01"/>',
    fuente: '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/><path d="M9 13h6M9 17h6"/>',
    info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5"/><path d="M12 8v.01"/>',
    'chevron-derecha': '<path d="M9 6l6 6-6 6"/>',
    'chevron-abajo': '<path d="M6 9l6 6 6-6"/>',
    'chevron-izquierda': '<path d="M15 6l-6 6 6 6"/>',
    panel: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M9 4v16"/>',
    bien: '<path d="M5 12l5 5 9-10"/>',
    alerta: '<path d="M12 3l10 18H2z"/><path d="M12 10v4M12 17.5v.01"/>',
    cerrar: '<path d="M6 6l12 12M18 6L6 18"/>',
    mas: '<circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/>',
    tabla: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 10h18M3 15h18M9 4v16"/>',
    grafico: '<path d="M3 20h18"/><path d="M6 17V11M11 17V6M16 17v-4M21 17V9"/>',
    externo: '<path d="M14 4h6v6"/><path d="M20 4l-9 9"/><path d="M19 13v6a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1h6"/>',
    'flecha-arriba': '<path d="M12 19V5"/><path d="M6 11l6-6 6 6"/>',
    'flecha-abajo': '<path d="M12 5v14"/><path d="M6 13l6 6 6-6"/>',
    'flecha-derecha': '<path d="M5 12h14"/><path d="M13 6l6 6-6 6"/>',
    igual: '<path d="M5 9h14M5 15h14"/>',
    canje: '<path d="M4 8h16"/><path d="M16 4l4 4-4 4"/><path d="M20 16H4"/><path d="M8 12l-4 4 4 4"/>',
    play: '<path d="M7 4l13 8-13 8z"/>',
    pausa: '<path d="M7 4h4v16H7zM13 4h4v16h-4z"/>',
    descargar: '<path d="M12 4v11"/><path d="M7 10l5 5 5-5"/><path d="M4 20h16"/>',
    reloj: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    calendario: '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/>',
    mapa: '<path d="M3 6l6-2 6 2 6-2v14l-6 2-6-2-6 2z"/><path d="M9 4v14M15 6v14"/>',
    lupa: '<circle cx="11" cy="11" r="6.5"/><path d="M20 20l-4.2-4.2"/>',
    equipo: '<circle cx="12" cy="7" r="3.5"/><path d="M5 20a7 7 0 0 1 14 0"/>',
    balanza: '<path d="M12 3v18"/><path d="M5 7h14"/><path d="M8 21h8"/><path d="M2 14l3-7 3 7a3 3 0 0 1-6 0z"/><path d="M16 14l3-7 3 7a3 3 0 0 1-6 0z"/>',
  };
  function simbolo(nombre, trazos) {
    return '<symbol id="i-' + nombre + '" viewBox="0 0 24 24">' + trazos + '</symbol>';
  }
  function sprite() {
    return '<svg xmlns="http://www.w3.org/2000/svg" style="position:absolute;width:0;height:0;overflow:hidden" aria-hidden="true" focusable="false">' +
      Object.keys(ICONOS).map(function (n) { return simbolo(n, ICONOS[n]); }).join('') + '</svg>';
  }
  function inyectar() {
    if (document.getElementById('sprite-iconos')) return;
    const cont = document.createElement('div');
    cont.id = 'sprite-iconos';
    cont.innerHTML = sprite();
    document.body.insertBefore(cont, document.body.firstChild);
  }
  if (document.body) inyectar(); else document.addEventListener('DOMContentLoaded', inyectar);
  global.ICONOS = {
    nombres: Object.keys(ICONOS),
    svg: function (nombre, clase) {
      return '<svg class="' + (clase || 'icono') + '" aria-hidden="true"><use href="#i-' + nombre + '"></use></svg>';
    },
    inyectar: inyectar,
  };
})(window);
