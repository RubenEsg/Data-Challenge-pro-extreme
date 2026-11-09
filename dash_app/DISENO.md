# Sistema de diseño del laboratorio Dash

> Fuente única: el bloque `:root` de `assets/estilos.css`. `tokens.py` lo lee y da a Python los roles (`ROL`, `VAR`);
> `ui.py` arma con ellos la plantilla de Plotly y los componentes. `verificar_estilo.py` comprueba todo lo de abajo.

## 1. Dirección: la referencia que eligió el usuario

El usuario descartó el estilo «Apple» (acento turquesa y barra lateral) y eligió como referencia el tablero
**«Dashboard for payment and business analytics»** de Outcrowd en Dribbble (el tablero «zentra»):
<https://dribbble.com/shots/26446179-Dashboard-for-payment-and-business-analytics>. De ella se toma:

- página gris claro y **tarjetas casi blancas** muy redondeadas (radio 26 px), con borde fino y sombra difusa;
- **navegación arriba**: logo + «Sobusa Despacho» a la izquierda, las siete pantallas como pestañas de texto (Inicio, Pronóstico, Horario, Despacho, Modelo, Resultado y Enlaces) (la activa en
  **píldora negra**), el chip «Cálculo en vivo» a la derecha; en el teléfono las pestañas se desplazan en horizontal;
- **título enorme en peso normal** (hasta 60 px, interletrado cerrado) y, en la misma fila a la derecha, los controles de
  la pantalla, **cada uno en su píldora gris** con el segmento elegido en blanco (como «Jan 01 – July 31 · compared to ·
  Aug 01 – Dec 31», «Daily» y «Add widget» de la referencia); si no caben junto al título bajan a la derecha y cada
  píldora abraza su contenido; en el teléfono va un control por línea y las opciones que no caben pasan a una segunda
  línea (la elegida siempre se ve);
- cada tarjeta con su título a 24 px y el **botón redondo «…»** arriba a la derecha (abre la tabla gemela y las fuentes);
- **cifras muy grandes en peso normal** (44 px; la protagonista hasta 72 px), lo secundario en gris;
- **chips en píldora blanca** con sombra suave («▲ 1,4 %», «Pico: 7:00»);
- **barras rayadas** en diagonal (azul sobre azul claro) con la columna en foco **sólida** y una banda azul clara detrás;
  escalón rosa con relleno de rayas verticales; barras de progreso rayadas; matriz de puntos; tarjeta «Insight» con
  degradado naranja → azul con grano y texto blanco.

Tipografía: **Inter** (SIL OFL 1.1), variable, en `assets/fuentes/` (`InterVariable.woff2` + `OFL.txt`), declarada con
`@font-face` y `font-display: swap`: funciona sin internet. Respaldo: Segoe UI Variable Display, Segoe UI, system-ui.

## 2. Colores por rol

Cada entidad tiene un rol y su color es el mismo en las siete pantallas. Nunca se escribe un color en `paginas/*.py`.

| Rol (`ui.ROL[…]`) | Token | Hex | Dónde |
|---|---|---|---|
| `modelo` — lo que proponemos (híbrido E12, plan que reasigna) | `--serie-modelo` | `#2457f0` | serie en foco (sólida); las demás de la familia, rayadas; enlaces y foco |
| `modelo_tinte` | `--serie-modelo-tinte` | `#dce5fd` | fondo del rayado azul, banda de foco (`--franja`, el azul al 9 %) |
| `hoy` — hoy, la regla manual, referencias | `--serie-hoy` | `#858585` | barras rayadas en gris, línea gris |
| `hoy_tinte` | `--serie-hoy-tinte` | `#e3e3e3` | fondo del rayado gris |
| `real` / `oraculo` — lo que pasó | `--serie-real` | `#141414` | línea de 2,5 px |
| `recorta` — el plan que recorta | `--serie-recorta` | `#b8235f` | rosa frambuesa: escalón con rayas verticales, barras |
| `recorta_tinte` | `--serie-recorta-tinte` | `#f6dbe6` | fondo del rayado rosa |
| `contexto` | `--serie-contexto` | `#c8c8c8` | contexto, lo que se quita (con rótulos o tabla: 1,6:1) |
| rutas SILENCIO · CRA 54 · CL 72 | `--ruta-*` | `#0d9488` · `#e8590c` · `#7048e8` | solo muestras de 10 px junto al nombre |
| `bien` · `atencion` · `critico` | `--bien` · `--atencion(-texto)` · `--critico` | `#18753a` · `#b26f0b`/`#925b08` · `#ba2b2e` | solo estados, siempre icono + palabra |

Neutros: página `--fondo #efefef`, tarjeta `--superficie #fafafa`, grupo de píldoras `--superficie-2 #e9e9e9`,
píldoras y anidados `--blanco #ffffff`, borde `--linea #e3e3e3`, texto `--tinta #141414`, `--tinta-2 #555555`,
`--tinta-3 #666666` (los grises claros de la referencia, oscurecidos lo justo para 4,5:1), `--tinta-tenue #8a8a8a`
(solo texto de 24 px o más: 3,3:1), rejilla `#ebebeb`.

**Validación** (`validate_palette.js` de dataviz, superficie `#fafafa`, todos los pares): azul solo; azul + rosa
(ΔE CVD 23,7); azul + gris (22); gris + rosa (8,9); azul + rosa + gris; real + azul + contexto (Pronóstico); azul + gris +
real/oráculo + rosa (Horario); las tres rutas (13,8). Pasan CVD, visión normal y contraste de marcas; los grises «fallan» el piso de croma por diseño (son
grises). El rosa se eligió más oscuro que el de la referencia porque el rosa claro se confunde con el gris en deuteranopía
(ΔE 1,8). Contraste de texto: 33 pares con su mínimo; el más justo, blanco sobre `--insight-3` (3,0:1, solo texto grande).

## 3. Escala

Letra: `--t-xs 12` · `--t-s 14` · `--t-m 16` (texto) · `--t-l 20` · `--t-xl 24` (título de tarjeta) · `--t-2xl 32`
(título de sección, saldos) · `--t-3xl 40–60` (título de pantalla) · `--t-cifra 44` · `--t-hero 52–72`. Pesos: 400 en
títulos y cifras (`--peso-titulo`, `--peso-cifra`), 500 en pestañas, chips y botones, 600 solo en rótulos pequeños.
Hasta 8 tamaños por pantalla. Radios: 3 (puntos), 10, 16 (anidados), 26 (tarjetas), 28, píldora. Sombras: `--sombra-2`
tarjetas, `--sombra-4` chips y segmento elegido, `--sombra-3` panel «…». Espaciado en pasos de 8 (`--e-1` … `--e-9`).

## 4. Componentes (`ui.py`)

- `encabezado(titulo, subtitulo, controles, respuesta)` (o `arriba(cabecera(…), controles, respuesta)`): título enorme a la
  izquierda y los controles a la derecha en la píldora gris.
- `rejilla(hijos, "2-1" | "1-2" | "1-1" | "3")`: el tablero de tarjetas.
- `tarjeta(cuerpo, titulo=…, detalles=…, fuentes=…)` / `bloque(titulo, cuerpo, detalles=…)`: tarjeta con «…».
- `grafico(id_o_fig, titulo, subtitulo, etiqueta, tabla, leyenda, nota, fuentes=…)`: el «…» trae la tabla gemela.
- `cifra(…)`, `heroe(…)` (con sus dos `saldo`), `antes_despues(…)`, `cifras`, `cambios`. En Inicio y en «¿Qué gana
  Sobusa?» la protagonista es una `tarjeta(…, clase="heroe cifra--hero", fuentes=…)` con las mismas partes
  (`heroe__principal` con el número, la unidad y el chip → `saldos` → `heroe__pie`), así las dos llevan título y «…».
- `chip(texto, tipo)`, `chip_cambio(valor, texto, tono)` (▲/▼), `chip_valor(rotulo, valor)`.
- `barra_rayas(etiqueta, valor, fraccion, rol)`, `puntos(cuentas, foco, rol)`, `tarjeta_insight(valor, titulo, texto)`.
- `segmentado`, `control`, `boton` (el primario es la píldora negra), `boton_redondo`, `desplegable`, `tabla`, `aviso`,
  `fuentes`, `destino`, `casilla`, `deslizador`.

Reglas de disposición en `estilos.css`: `.tarjeta` y `.grafico` llevan `align-content: start` (la rejilla estira la
tarjeta más corta de la fila y el alto sobrante queda abajo, no entre sus partes); los dos `saldo` lado a lado comparten
filas con `subgrid`, así sus cifras quedan a la misma altura aunque un título ocupe dos líneas; en una tabla, el mejor
valor de la fila va en negrita y debajo la palabra «mejor» en `.tabla__mejor-txt` (gris `--tinta-3`, 14 px: con 12 px Resultado pasaría de 8 tamaños), sin
color de serie; por
debajo de 420 px las celdas tienen menos relleno lateral.

## 5. Gráficos

Plantilla `sobusa`: Inter, rótulos de los ejes en `--tinta-3`, rejilla muy clara, sin títulos de eje (la unidad con
`unidad_eje`), etiqueta flotante en píldora blanca con borde fino, separadores `,.` y el menos «−» en el texto ya
formateado. Formas por rol con `traza(rol, forma)`: `foco`/`barra` (sólida), `rayada` (rayas diagonales sobre el tinte),
`escalon_rayado` (escalón «hv» con rayas verticales claras), `linea`, `gruesa`, `trazos`, `punteada`, `area`, `punto`.
Ayudas: `barras_foco(rol, categorias, foco)` (una columna sólida, las demás rayadas), `banda_foco(fig, x, categorias)`,
`etiquetas_columnas(fig, categorias, textos, foco)` (rótulos encima de cada columna, el de foco en tinta). Reglas: un solo
eje y; leyenda HTML cuando hay dos series o más; gris y rosa nunca con la misma forma; tabla gemela en el «…».

## 6. Reglas que no cambian

Las cifras salen de `datos/` (342 comprobaciones en `verificar_ahorro.py`); el ahorro en operación (+501 M COP) nunca va
sin sus dos saldos (−2.825 conservador, +1.600 simétrico) ni se llama «ganancia»; el plan que recorta muestra su canje
(más caja en las dos contabilidades, −1.512 pasajeros netos por día, 530 frente a 267 pasajeros por día sobre la
capacidad); formato
es-CO (miles «.», decimales «,», menos «−», también en Plotly); estados solo con icono y palabra; solo modo claro.

## 7. Verificación

`python verificar_estilo.py` (en el código: contraste, roles, CSS sin literales, Python sin colores ni tamaños, paleta) y
`python verificar_estilo.py --vivo PUERTO` (con Playwright: errores de consola, tamaños por pantalla, pesos, colores de la
paleta, encabezados, una protagonista con sus dos saldos, nada se sale a 400 px). Nunca el puerto 8050.
