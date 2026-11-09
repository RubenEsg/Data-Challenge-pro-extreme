# Bibliotecas y fuentes locales

Copias de las bibliotecas y las fuentes que las páginas del proyecto cargaban desde internet, para que funcionen sin conexión (por ejemplo, en una presentación). Son exactamente las mismas versiones.

| Archivo | Origen | Uso |
|---|---|---|
| `maplibre-gl.js`, `maplibre-gl.css` | MapLibre GL JS 5.6.0 (`unpkg.com/maplibre-gl@5.6.0/dist/`), licencia BSD-3 | mapa de `vista_3d.html` |
| `deck.gl.min.js` | deck.gl 9.1.14 (`unpkg.com/deck.gl@9.1.14/dist.min.js`), licencia MIT | buses y personas en 3D de `vista_3d.html` |
| `echarts.min.js` | ECharts 5.5.1 (`cdn.jsdelivr.net/npm/echarts@5.5.1`), licencia Apache-2.0 | gráficos de la consola, el planificador, el simulador y el tablero |
| `leaflet.min.js`, `leaflet.min.css`, `images/` | Leaflet 1.9.4 (`cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4`), licencia BSD-2 | mapa de la consola y del tablero (sus teselas de Esri sí necesitan internet) |
| `fuentes.css`, `fuentes/*.woff2` | Barlow Condensed (500, 600, 700) e IBM Plex Sans (400, 500, 600) de Google Fonts, licencia OFL | tipografía de todas las páginas |

Las páginas cargan estas copias en vez de los CDN. `vista_3d.html` intenta además el mapa en línea y, si no responde, usa `mapa_local/`. La consola sondea internet antes de pedir las teselas de Esri (que no se pueden guardar) y, si no hay, deja el mapa en gris con una nota y sigue dibujando las rutas y los buses.

Se descargaron el 13 de octubre de 2026 de las direcciones de la tabla, con un script de la sesión de trabajo que no forma parte del proyecto; para actualizarlas basta volver a bajar las mismas versiones.
