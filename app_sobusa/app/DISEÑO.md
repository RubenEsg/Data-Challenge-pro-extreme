# Sobusa Despacho · Guía del sistema de diseño

Guía para construir la app (una sola aplicación web que reúne el proyecto) con el mismo lenguaje visual en todas las pantallas. Describe los principios, los tokens, los componentes y cómo usarlos, el esqueleto de `app.html` con el contrato de cada pantalla, las convenciones de texto y los wireframes de las nueve pantallas. La muestra viva de todo esto es `app/muestra.html` (se abre con doble clic y funciona sin internet).

Archivos del sistema de diseño:

| Archivo | Qué es |
|---|---|
| `app/tokens.css` | Los tokens: paleta clara (la app es solo clara), paleta de colores con nombre y color de cada pantalla, tipografía, espaciado, radios, sombras, movimiento, disposición; el puente para los módulos embebidos. |
| `app/componentes.css` | Los componentes, escritos solo con tokens. |
| `app/componentes.js` | El comportamiento mínimo (cifras que cuentan, popover de fuente, interruptor, pestañas, leyenda, tabla gemela, barra lateral, formato es-CO). |
| `app/tema_echarts.js` | El tema de ECharts (`window.TEMA_ECHARTS.claro`, el único) derivado de los tokens, con los roles de serie. |
| `app/iconos.js` | La familia de iconos (SVG en línea, un solo trazo). |
| `app/paleta.html` | La hoja de la paleta: cada color con su muestra, sus tonos, su contraste medido y su uso; también gráficos, rutas, estados y neutros. Se abre con doble clic. |
| `app/muestra.html` | La muestra de componentes con datos reales; `app/generar_muestra_datos.py` produce `app/muestra_datos.js`. |
| `app/probar_muestra.py` | La prueba de la muestra en Edge con Playwright (capturas en `app/capturas_muestra/`). |

## 1. Para quién y con qué principios

Primero el jurado (profesores), después la gerencia y los despachadores de Sobusa. Alguien que no conoce el proyecto debe entender en dos minutos qué problema resuelve, qué modelo usa y cuánto mejora frente a lo que Sobusa hace hoy.

1. **Correcta.** Ninguna cifra escrita a mano: todo número sale de `app/datos_app.js`, generado desde los resultados de los experimentos, y lleva un botón «fuente» con archivo, clave, experimento y si tuvo revisor independiente. `app/verificar_datos_app.py` compara los JSON con las fuentes y falla si algo difiere. La muestra sigue la misma regla con `generar_muestra_datos.py`.
2. **Clara.** Cada pantalla responde una pregunta (su título); primero el resumen (fichas de cifra, una frase), después el detalle («Ver cómo se calculó»).
3. **Honesta.** Los canjes se muestran completos con el aviso de canje: recortar frente a reasignar; contabilidad conservadora frente a simétrica; β medida con fallas y no con recortes planificados; el modelo persona a persona castiga al plan. Los límites tienen su apartado.
4. **Comparable.** En todas las pantallas el interruptor «Hoy / Con el modelo / Oráculo»; donde el oráculo no aplica, la opción se deshabilita con un tooltip que lo dice.
5. **Sobria.** Mucho espacio, tipografía del sistema, un acento, tarjetas solo donde separan algo, transiciones cortas, nada de emojis ni adornos. Los datos son lo único que puede ser llamativo.

## 2. Tokens

Todos los colores, tamaños y tiempos se usan como `var(--nombre)`; ningún componente lleva un color literal. **La app es solo clara** (desde el 19-oct-2026): todos los tokens nacen y viven en `:root`, con `color-scheme: light`; no hay bloque `@media (prefers-color-scheme: dark)`, ni `:root[data-theme="dark"]`, ni islas `.tema-claro` / `.tema-oscuro`, ni botón de tema. `app.html` lleva `data-theme="light"` fijo y `<meta name="color-scheme" content="light">`, así que se ve igual aunque el sistema esté en oscuro.

### 2.1 Color

Solo modo claro. El acento es un **verde azulado del Caribe** (tono OKLCH 190), `#0e7974`: funciona como texto y como botón, se distingue bajo deuteranopia y protanopia de los tres colores de ruta (azul, naranja, morado) y de los tres de estado (verde, ámbar, rojo), y coincide con el color que el simulador de ahorro ya da al plan (b), el que reasigna. Es también el color de Inicio y de la marca. La hoja con todos los colores, sus contrastes medidos y su uso es [`app/paleta.html`](paleta.html).

**Neutros y acento**

| Token | Valor | Uso |
|---|---|---|
| `--fondo` | `#f5f5f7` | plano de la página y de la barra lateral |
| `--superficie` | `#ffffff` | tarjetas, gráficos, tablas, avisos, popovers, barra inferior del teléfono |
| `--superficie-2` | `#ececf0` | selección de la barra lateral y de la hoja «Más» (el gris de iOS), pista del interruptor, botón secundario, ficha dentro de una tarjeta |
| `--superficie-hover` | `#f0f0f3` | fila o botón bajo el puntero |
| `--linea` / `--linea-fuerte` | `#e3e3e8` / `#d2d2d7` | separadores entre filas / bajo la cabecera de tabla y eje base (no hay bordes de tarjeta) |
| `--tinta` / `--tinta-2` / `--tinta-3` | `#1d1d1f` / `#5e5e63` / `#6e6e73` | texto principal (16,8:1 sobre blanco, 15,5:1 sobre el fondo) / secundario (6,5 / 5,9) / terciario: notas y ejes (5,1 / 4,7: no bajar más) |
| `--acento` / `--acento-fuerte` | `#0e7974` / `#0a625e` | texto, enlaces, botón primario (5,2:1) / hover y pulsado (7,2:1) |
| `--acento-suave` / `--acento-contraste` / `--foco` | `#e5f3f2` / `#ffffff` / `#11938d` | fondo de lo seleccionado / texto sobre el acento / anillo de foco |

**Paleta de colores con nombre (estilo Ajustes del iPhone).** Parte de los colores del sistema de Apple (blue `#007AFF`, indigo `#5856D6`, orange `#FF9500`, red `#FF3B30`, cyan `#32ADE6`, green `#34C759`, yellow `#FFCC00`, gray `#8E8E93`); a los que no daban el contraste se les bajó solo la luminosidad en OKLCH, con el mismo tono. Cada color tiene tres tonos: `--color-X` (el cuadro del ícono: glifo blanco ≥ 3:1, WCAG 1.4.11), `--color-X-texto` (≥ 4,5:1 sobre `#ffffff` y sobre `--fondo`) y `--color-X-suave` (tinte para fondos; el tono de texto se lee sobre él ≥ 4,5:1). El glifo es `--glifo-sobre-color` (`#ffffff`). Contrastes medidos con `contrastes_paleta.py`:

| Color | Pantalla (`--pantalla-<id>`) | Cuadro | Glifo blanco | Texto | Sobre blanco / fondo | Tinte | Texto sobre tinte |
|---|---|---|---|---|---|---|---|
| Turquesa | Inicio (y marca, acento) | `#0a9396` | 3,73:1 | `#0e7974` | 5,24 / 4,81 | `#e5f3f2` | 4,60 |
| Azul | Demanda | `#007aff` | 4,02:1 | `#0068db` | 5,25 / 4,82 | `#eff6ff` | 4,82 |
| Índigo | Modelo | `#5856d6` | 5,65:1 | `#5856d6` | 5,65 / 5,19 | `#f3f4ff` | 5,16 |
| Naranja | Horario | `#d37a03` | 3,20:1 | `#a45e03` | 5,02 / 4,61 | `#fef3e9` | 4,59 |
| Coral | Despacho | `#ff3b30` | 3,55:1 | `#d70015` | 5,38 / 4,94 | `#fff2f0` | 4,93 |
| Cian | Ciudad | `#0b99d1` | 3,24:1 | `#0677a4` | 5,02 / 4,61 | `#ebf7fe` | 4,61 |
| Verde | Resultado | `#06a63f` | 3,21:1 | `#01812f` | 5,02 / 4,61 | `#e8fbea` | 4,64 |
| Morado | Piloto | `#af52de` | 4,13:1 | `#8e3bb8` | 6,06 / 5,56 | `#f7effc` | 5,39 |
| Gris | Método y datos (y «Más») | `#8e8e93` | 3,26:1 | `#6e6e73` | 5,07 / 4,66 | `#f4f4fa` | 4,63 |

**Dónde se usa el color de pantalla, y dónde no.** Solo en el cuadro redondeado del ícono de cada pantalla (`.cuadro-color`, con `--cuadro: var(--pantalla-<id>)`): en la barra lateral (28 px, radio 7), en la barra inferior del teléfono (26 px), en la hoja «Más» (30 px, radio 8) y en la cabecera de cada pantalla (32 px, radio 8, encima del título grande). No tiñe fichas, secciones, gráficos ni textos: los gráficos conservan sus colores validados y los estados los suyos.

Series de los gráficos (roles, no colores sueltos):

| Token | Valor | Rol |
|---|---|---|
| `--serie-hoy` | `#8b9ca0` | **Hoy**: la regla manual, la oferta real de 2025. Gris de desénfasis (2,9:1 sobre blanco, por eso todo gráfico lleva leyenda y tabla gemela). |
| `--serie-modelo` | `#169a94` | **Con el modelo**: el pronóstico del modelo y el plan. Paso 500 de la rampa del acento (3,5:1). |
| `--serie-real` | `#162428` | Lo que de verdad pasó (pasajeros reales). Tinta, 2,5 px. |
| `--serie-oraculo` | `#162428` | La decisión óptima con la demanda que llegó. Tinta **a trazos**. |
| `--serie-recorta` | `#a33460` | **Plan que recorta** (los supuestos iniciales): el `--plan-a` del simulador de ahorro. Frente a `--serie-modelo` pasa el validador de dataviz (CVD ΔE 11,6; visión normal 28,1; 6,5:1). *Añadido el 8-nov-2026 desde el laboratorio Dash; la app todavía no lo usa.* |
| `--serie-contexto` | `#c4ccce` | **Contexto**: lo que acompaña sin ser el tema (salidas que se quitan, pasos de una cascada, «hoy» tenue). Es el gris de hoy con la luminosidad que la app logra al 45 % de opacidad, pero como token. Frente a `--serie-modelo`, CVD 18,5 y visión normal 23,8; frente a `--serie-hoy`, 15,5 y 15,9. Contraste 1,63:1: siempre con alivio (etiqueta, dirección o tabla gemela). *Añadido el 8-nov-2026 desde el laboratorio Dash.* |
| `--franja` · `--lavado` | `color-mix(in srgb, var(--acento) 8%, transparent)` · `10%` | Franja de rango o de selección en un gráfico (rango creíble de β, día elegido) y porcentaje del lavado de área (`color-mix(in srgb, var(--c) var(--lavado), transparent)`). *Añadidos el 8-nov-2026.* |
| `--ruta-silencio` / `--ruta-cra54` / `--ruta-cl72` | `#2f6fb3` / `#d9731a` / `#6a3d9a` | Las rutas, en este orden fijo (azul, naranja, morado), como en todas las páginas. |

Estado (siempre con icono y texto, nunca solo el color): `--bien` `#317229`, `--atencion` `#b26f0b` (y `--atencion-texto` `#925b08` para texto), `--critico` `#ba2b2e`, cada uno con su `-suave` para fondos de chips (`--critico-suave` `#fdf2f1` es el único aviso con fondo teñido). Mobiliario de gráficos: `--rejilla` `#e8e8ed` y `--eje` `#d2d2d7`.

Validación con el método dataviz (`validate_palette.js`, OKLab): las tres rutas pasan todos los controles sobre la lista de pares adyacentes (peor par CVD ΔE 23,5); rutas + modelo pasan (peor par 19,4); el verde azulado del modelo cumple banda de luminosidad, croma y contraste. Los roles neutros (hoy, real, oráculo) quedan fuera del control categórico a propósito: es la forma «énfasis», con identidad asegurada por la leyenda, las etiquetas directas, el grosor (real 2,5 px) y los trazos (oráculo). Nunca se mezclan en un gráfico las dos dimensiones (rutas y escenarios): se facetan por ruta.

### 2.2 Tipografía, espaciado, radios, sombras, movimiento

- Pila del sistema: `--fuente-texto` (`-apple-system, "SF Pro Text", "Segoe UI", Roboto, Helvetica, Arial, sans-serif`), `--fuente-titulos` (la misma con SF Pro Display y Segoe UI Variable Display delante) y `--fuente-mono` para rutas de archivo y claves.
- Escala (19-oct-2026, la de Apple): `--t-xs` 12 (pestañas del teléfono, ejes), `--t-s` 14 (secundario, tablas, notas), `--t-m` 17 (cuerpo), `--t-l` 21 (subtítulo de la pantalla, título de gráfico, h3), `--t-xl` 28 (h2), `--t-2xl` 32, `--t-3xl` clamp(34, 3,2vw, 44) (la pregunta de la pantalla), `--t-cifra` 36 (ficha de cifra), `--t-hero` clamp(48, 5vw, 64) (la pareja protagonista de Inicio). En el teléfono (≤ 600 px): h1 30, h2 22, cifra 32, héroe 44. Interlineados 1,47 texto / 1,1 títulos / 1,05 cifras (y `--lh-compacto` 1,35 para subtítulos y etiquetas, añadido el 8-nov-2026: la app lo escribe a mano); pesos 400, 500, 600; títulos con `letter-spacing` −0,02 em (el h1, −0,025 em: `--ls-h1`, añadido el 8-nov-2026) y `text-wrap: balance`; el cuerpo con `--ls-texto` −0,01 em. Sin rótulos en mayúsculas espaciadas: `--ls-etiqueta` queda solo para las páginas antiguas.
- Cifras con dígitos tabulares (`font-variant-numeric: tabular-nums`, clase `.num`) para que no salten al contar y se alineen en columnas.
- Espaciado en pasos de 8 px con medio paso: `--e-1` 4, `--e-2` 8, `--e-3` 12, `--e-4` 16, `--e-5` 24, `--e-6` 32, `--e-7` 48, `--e-8` 64, `--e-9` 96. Entre secciones de una pantalla, `--e-8` (64; 48 en el teléfono); dentro de una sección, `--e-5`; la diferencia se tiene que notar. Gutter lateral `max(16px, env(safe-area-inset-*))`; desde 1024 px, el contenido lleva 32 px a los lados y 48 / 96 arriba y abajo.
- Radios: `--radio-s` 8 (chips de código, foco), `--radio-m` 12 (controles, elementos anidados), `--radio-l` 18 (tarjetas, gráficos, avisos, desplegables, tablas), `--radio-pill` (botones e interruptor). Lo anidado nunca tiene más radio que su contenedor.
- Sombras: casi ninguna. `--sombra-1` solo para el segmento elegido del interruptor; `--sombra-2` para lo que flota (cabecera compacta, hoja «Más»); `--sombra-3` para los popovers. Las tarjetas en reposo no llevan sombra ni borde: se separan del fondo por tono.
- Movimiento: `--dur-1` 120 ms (hover, foco), `--dur-2` 200 (abrir, cambiar de estado), `--dur-3` 320 (plegar la barra, entrar una pantalla), `--dur-4` 600 (contar una cifra); curva `--curva` `cubic-bezier(0.2, 0, 0, 1)`. Con `prefers-reduced-motion: reduce` las cuatro duraciones valen 0 y las animaciones se apagan.
- Disposición: `--ancho-lateral` 240, `--ancho-lateral-plegada` 68, `--alto-pestanas-movil` 60, `--ancho-contenido` 1200, `--ancho-texto` 68ch; capas `--z-cabecera` 10, `--z-lateral` 20, `--z-popover` 100, `--z-tooltip` 110.

### 2.3 Puente para los módulos embebidos

Cuando una página existente (tablero, planificador, consola, vista 3D, simulador) se abre dentro de la app con `?embebido=1`, pone `html[data-embebido]` y añade `<link rel="stylesheet" href="app/tokens.css">` al final de su `<head>`. El bloque `:root[data-embebido][data-embebido]` de `tokens.css` vuelca los tokens de la app sobre los nombres que esas páginas ya usan (`--bg`, `--surface`, `--surface-2`, `--fg`, `--muted`, `--line`, `--accent`, `--accent-soft`, `--shadow`, `--font-body`, `--font-display`, `--hoy`, `--ok`, `--warn`, `--bad`, `--r-*`), con especificidad (0,2,1) para ganar al `:root` de cada página; solo con valores claros. Los tokens propios de cada página (`--occ-*`, `--plan`, `--plan-a`, `--plan-b`, `--div-*`, `--manana`, `--tarde`) se conservan. Cada página fija `data-theme="light"` en su `<head>` antes de pintar (también abierta sola) y ya no tiene bloque oscuro. La página oculta su marca, sus enlaces a otras páginas y su pie con reglas `html[data-embebido] … { display: none }` (los selectores de cada página están en el inventario técnico de los módulos).

## 3. Componentes y cómo usarlos

Clases en español con el patrón `bloque__elemento--variante`. Los iconos se escriben `<svg class="icono" aria-hidden="true"><use href="#i-nombre"></use></svg>` (nombres: inicio, demanda, modelo, horario, despacho, ciudad, resultado, piloto, metodo, bus, fuente, info, chevron-derecha, chevron-abajo, sol, luna, tema-auto, panel, bien, alerta, cerrar, tabla, grafico, externo, flecha-arriba, flecha-abajo, flecha-derecha, igual, canje, play, pausa, descargar, reloj, calendario, mapa, lupa, equipo, balanza); en JS, `ICONOS.svg('nombre')`.

### Barra lateral (`.lateral`)

240 px, pegada arriba, en el mismo plano que la página (`--fondo`, sin línea), con la marca, la lista de pantallas y el pie (plegar). Cada pantalla es un enlace `a.lateral__enlace[href="#id"]` con su ícono blanco dentro del cuadro de su color (`.cuadro-color`, 28 px, radio 7, como en Ajustes del iPhone) y su nombre en una sola línea de 15 px; la pregunta va como `title` del enlace (ya es el h1 de la pantalla). La activa lleva `aria-current="page"`: relleno gris redondeado (`--superficie-2`, el gris de selección de iOS), nombre en tinta y peso 600; el cuadro conserva su color. `.app--plegada` la reduce a 68 px con solo iconos; el botón dice «Plegar la barra» o «Desplegar la barra» según lo que hará. Bajo 760 px pasa a una barra inferior fija de cinco elementos sin desplazamiento (Inicio, Modelo, Horario, Resultado y «Más»; las demás llevan `li.lateral__item--sec`). Todos los cuadros van a pleno color, como el Dock; la activa lleva el nombre en tinta y peso 600 y un punto debajo. «Más» (gris) abre la hoja `dialog#hoja-mas` con las nueve pantallas (cuadro de 30 px, nombre en 17 px y pregunta en 14 px; separadores sangrados como en iOS; la activa con fondo gris); se cierra con Esc, con la X, al tocar el fondo y al elegir. Si la pantalla abierta no está entre las cuatro fijas, «Más» toma su icono, su color y su nombre.

```html
<div class="app" id="app">
  <aside class="lateral" aria-label="Pantallas">
    <a class="lateral__marca" href="#inicio"><span class="lateral__logo">…icono bus…</span><span><span class="lateral__nombre">Sobusa Despacho</span><span class="lateral__lema">Data Challenge 2026</span></span></a>
    <nav><ul class="lateral__nav">
      <li><a class="lateral__enlace" href="#inicio" aria-current="page"><span class="cuadro-color" style="--cuadro: var(--pantalla-inicio)" aria-hidden="true">…icono…</span><span class="lateral__texto"><span class="lateral__titulo">Inicio</span><span class="lateral__pregunta">¿Qué proponemos?</span></span></a></li>
    </ul></nav>
    <div class="lateral__pie"><button class="boton boton--secundario boton--icono" data-plegar aria-label="Plegar la barra">…</button></div>
  </aside>
  <main class="contenido" id="contenido"><div class="pantalla">…</div></main>
</div>
```

`COMPONENTES.lateral(app)` conecta plegar (guarda `sobusa-despacho-lateral` en `localStorage`, con `try/catch`). No hay botón de tema ni se lee o escribe un tema en `localStorage` (si quedó `sobusa-despacho-tema` de antes, se ignora).

### Cabecera de pantalla (`.cabecera`)

La pregunta como `h1.cabecera__pregunta` (sin rótulo encima: el nombre de la pantalla queda solo para lectores de pantalla, con `.oculto`), el subtítulo (una frase que responde, 21 px en `--tinta-2`) y a la derecha `.cabecera__acciones` con el interruptor. Al bajar, cuando el h1 sale de la vista, aparece `.cabecera-compacta` (52 px, fija arriba, fondo `--fondo` y una línea abajo) con la pregunta y una copia del interruptor sincronizada con el principal; solo en las pantallas con interruptor. El cambio de escenario se anuncia en `p#anuncio[aria-live=polite]`.

### Interruptor segmentado (`.segmentado`)

Radios de verdad dentro de un `fieldset` (teclado y lector de pantalla gratis). Sin puntos de color (los colores ya están en la leyenda de cada gráfico): las opciones van en `--tinta`, la elegida sobre `--superficie` en peso 600, y la que no aplica va `disabled`, en `--tinta-3`, con un tooltip. `.segmentado--pequeno` (28 px) es el selector secundario (el plan de Resultado), con su rótulo visible delante dentro de `.control-rotulado`. En el teléfono, cada opción mide 40 px de alto.

```html
<fieldset class="segmentado" id="escenario" aria-label="Escenario"><legend>Escenario</legend>
  <label class="segmentado__opcion"><input type="radio" name="escenario" value="hoy" checked><span class="segmentado__etiqueta"><span class="segmentado__punto" style="--c: var(--serie-hoy)"></span>Hoy</span></label>
  <label class="segmentado__opcion"><input type="radio" name="escenario" value="modelo"><span class="segmentado__etiqueta"><span class="segmentado__punto" style="--c: var(--serie-modelo)"></span>Con el modelo</span></label>
  <label class="segmentado__opcion con-tooltip"><input type="radio" name="escenario" value="oraculo" disabled><span class="segmentado__etiqueta"><span class="segmentado__punto segmentado__punto--trazos"></span>Oráculo</span><span class="tooltip">No aplica a estas cifras</span></label>
</fieldset>
```

`COMPONENTES.segmentado(fieldset, valor => …)` devuelve el valor inicial y llama al cambiar. `.segmentado--bloque` ocupa todo el ancho (para paneles estrechos).

### Ficha de cifra (`.cifra`) y botón «fuente»

Etiqueta (qué es), valor con unidad y una sola línea de variación (icono + texto + color de estado). La nota de qué mide va en el popover de fuente (fila «Qué mide», campo `que_mide` de `app.popoverFuente`) o en un desplegable común a la sección; solo queda a la vista (`.cifra__nota`, 14 px) cuando es parte de la respuesta. La ficha es una superficie blanca sin borde, radio 18 y 24 px de relleno; dentro de una tarjeta o de un desplegable va sobre `--superficie-2` con radio 12, nunca borde sobre borde. `.cifra--hero` para la cifra protagonista; `.cifra--llana` sin fondo; `.cifras` es la rejilla (`auto-fit, minmax(210px, 1fr)`, 16 px entre fichas). El valor lleva `data-cifra` y `data-decimales`; `COMPONENTES.ponerCifra(el, nuevoValor)` anima el cambio contando (600 ms, inmediato con movimiento reducido) y formatea en es-CO.

```html
<article class="cifra">
  <header class="cifra__cab"><h3 class="cifra__etiqueta">Pasajeros mal estimados de cada 100</h3>
    <button class="fuente" type="button" popovertarget="f-error" aria-expanded="false" aria-label="Fuente de la cifra">…icono fuente…</button></header>
  <p class="cifra__valor"><span data-cifra="13.94" data-decimales="2">13,94</span><span class="cifra__unidad">%</span></p>
  <p class="cifra__variacion cifra__variacion--bien">…flecha-abajo… −6,10 puntos frente a hoy</p>
  <p class="cifra__nota">WAPE a 7 días, 2025</p>
</article>
<div id="f-error" class="fuente-pop" popover>
  <div class="fuente-pop__cab"><span class="fuente-pop__titulo">Fuente</span><button class="boton boton--fantasma boton--icono boton--pequeno" data-cerrar aria-label="Cerrar">…</button></div>
  <dl class="fuente-pop__datos"><dt>Archivo</dt><dd><code>experimentos/E11_modelo_mejorado/resultados.json</code></dd><dt>Clave</dt><dd>horizontes.SEL_H7.global_.WAPE</dd><dt>Experimento</dt><dd>E11</dd><dt>Revisor</dt><dd><span class="chip chip--bien">…bien… sí</span></dd></dl>
</div>
```

El popover usa la Popover API (capa superior, cierre con Esc y clic fuera); `COMPONENTES.fuentes()` lo coloca bajo el botón que lo invoca (lo busca por `popovertarget` al abrirse, así un mismo botón puede cambiar de fuente al mover el interruptor) y, si el navegador no la tiene, lo simula con `hidden`. En la app, `datos_app.js` trae por cada cifra `{valor, unidad, decimales, archivo, clave, experimento, verificado, revision}` (`verificado` es «sí», «parcial» o «no»; `revision` dice qué revisión lo respalda) y el popover se genera de ahí.

### Sección (`.seccion`) y desplegable «Ver cómo se calculó» (`.desplegable`)

Una sección = título h2 (28 px) + subtítulo debajo, nunca a su derecha (`.seccion__cab` en columna: el control, si lo hay, en su propia línea) + intro en 17 px y `--tinta` + cuerpo. El desplegable es `details/summary` con chevron que gira, sin borde, sobre `--superficie`, con el cuerpo en 17 px; `.desplegable--llano` sin fondo. Dentro: la fórmula, los pasos numerados (solo si son una secuencia real) y quién lo verificó.

### Tabla de datos (`.tabla` dentro de `.tabla-marco`)

`.tabla-marco` da el fondo blanco, el radio 18 (sin borde) y el desplazamiento horizontal; las cabeceras son pegajosas, en tipo de frase (14 px, peso 600, `--tinta-2`) con una línea `--linea-fuerte` debajo; las cabeceras de fila (`tbody th`) son texto normal; todas las celdas usan dígitos tabulares; `.num` alinea a la derecha con dígitos tabulares; `.tabla__fila-total`, `.tabla__clave` + `.tabla__muestra` (cuadrito del color de la ruta o de la serie), `.tabla__mejor` (el mejor valor de la fila en el acento), `.tabla--compacta`.

### Contenedor de gráfico (`figure.grafico`) con leyenda y tabla gemela

Cabecera con título, subtítulo que dice qué significa cada color, acciones (segmentado, botón «Ver tabla» con `data-ver-tabla`); `ul.leyenda` en HTML (botones `data-serie` que aíslan la serie con `COMPONENTES.leyenda(ul, () => grafico)`); `.grafico__lienzo` (320 px; 260 en teléfono; `--bajo` 240, `--alto` 420); `.grafico__tabla` oculta con la tabla gemela (accesible y para imprimir); pie con la nota y el botón de fuente. Las muestras de la leyenda son línea (`.leyenda__muestra`), gruesa, barra, trazos o punto.

### Aviso (`.aviso`)

Rejilla icono + cuerpo (título + párrafos, 17 px). Variantes `--canje`, `--atencion`, `--critico`, `--bien`; sin variante es una nota. El fondo es la superficie neutra (o `--superficie-2` dentro de una tarjeta); el color va solo en el icono y el título. Solo `--critico` conserva un fondo teñido muy pálido, porque es el hallazgo honesto que tiene que verse. Una fila de botones de fuente al pie de un aviso se junta en un solo botón «Fuentes (n)» que abre `app.popoverFuentes(id, [[cifra, título], …])`; dentro del texto corrido, el botón «fuente» se dibuja con un icono de 12 px y conserva 24 px de zona de toque.

### Línea de tiempo (`ol.linea-tiempo`)

Hitos `li.hito` con fecha, título y texto; `--hecho`, `--activo`, `--critico`. Vertical por defecto; `.linea-tiempo--horizontal` la tiende en columnas a partir de 761 px.

### Pestañas, botones, chips, tooltip, carga

- `.pestanas[role=tablist]` con `button.pestana[role=tab][aria-controls]`; `COMPONENTES.pestanas(lista, cb)` gestiona `aria-selected`, `hidden` de los paneles y las flechas del teclado.
- `.boton` en píldora, con `--primario` (acento), `--secundario` (relleno gris, sin borde), `--fantasma`, `--pequeno`, `--icono` (redondo); al pulsar, `scale(0.97)`; `.botonera` los agrupa.
- `.chip` (`aria-pressed` cuando filtra; `--c` para el punto de la ruta) y `--bien`, `--atencion`, `--critico`, `--acento`; `.chips` los agrupa.
- `.con-tooltip` + `.tooltip` (al pasar el puntero, tras 400 ms; al enfocar con el teclado, al instante; `--izq` para los bordes).
- `.cargando` (esqueleto con brillo; `--texto`, `--bloque`), `.giro` y `.estado-carga`.

### Marco de módulo embebido (`.modulo`)

Barra discreta (sin fondo ni línea; el nombre, que repite el h1, solo para lectores de pantalla) con el estado (`aria-live`) y «Abrir aparte», y el `iframe.modulo__marco`; el marco no lleva borde y tiene radio 18. Dentro de las páginas embebidas, el puente de componentes de `tokens.css` (solo bajo `html[data-embebido]`) quita las mayúsculas espaciadas de pestañas, rótulos y cabeceras, deja las tarjetas internas sin borde ni sombra y pone los campos numéricos a 16 px en el teléfono. En una pantalla de módulo, `main.contenido--modulo` fija el alto a la ventana y el marco ocupa todo lo que queda bajo la cabecera. Los iframes se montan la primera vez que se abre su pantalla y se conservan; el que no se ve se «duerme» con `.modulo--dormido` (fuera de pantalla, con su tamaño), **nunca con `display:none`** (deck.gl de la vista 3D lanza un error al volver). `.modulo__cargando` tapa el marco hasta que el módulo avisa `{tipo:'listo'}`.

## 4. Gráficos: el tema de ECharts

`tema_echarts.js` lee los tokens de `:root` y construye un solo tema, `sobusa-claro`. Reglas:

- **Roles, no colores.** `TEMA_ECHARTS.serie('hoy' | 'modelo' | 'oraculo' | 'real' | 'motor' | 'silencio' | 'cra54' | 'cl72')` devuelve color y tipo de línea; se mezcla en la serie con `Object.assign`. El `color` por defecto del tema es el orden fijo de las rutas (SILENCIO, CRA 54, CL 72) y después modelo y hoy; nunca se cicla una novena serie.
- **Un solo eje Y** por gráfico; dos medidas de escala distinta son dos gráficos.
- **Marcas finas**: líneas de 2 px (real 2,5), barras de 24 px como máximo con la punta redondeada (4 px) y hueco entre barras, marcadores de 8 px con anillo del color de la superficie, rejilla hairline sólida en `--rejilla`, eje base en `--eje`, marcas de eje en `--tinta-3`.
- **Leyenda siempre** con dos o más series (en HTML con `.leyenda`, con la leyenda de ECharts oculta pero declarada para poder aislar) y **tabla gemela** en cada figura. Etiquetas directas solo donde cuentan algo (el extremo, el día del hallazgo), nunca un número en cada punto. El texto siempre en tokens de texto, nunca del color de la serie.
- **Tooltip con todas las series** (`trigger: 'axis'`), fondo `--superficie`, borde `--linea`, sombra `--sombra-3`.
- **Un solo tema**: la app es solo clara, así que no hay que observar el cambio de tema ni volver a crear los gráficos por él (`TEMA_ECHARTS.observar` se retiró; `modoActual()` devuelve siempre `'claro'`).

```js
TEMA_ECHARTS.registrar(echarts);
let g = TEMA_ECHARTS.init(echarts, document.getElementById('lienzo'));
g.setOption({
  legend: { show: false, data: ['Hoy', 'Con el modelo', 'Oráculo'] },
  tooltip: { trigger: 'axis' },
  xAxis: { type: 'category', data: horas }, yAxis: { type: 'value', name: 'salidas/h' },
  series: [
    Object.assign({ name: 'Hoy', type: 'bar', data: hoy }, TEMA_ECHARTS.serie('hoy')),
    Object.assign({ name: 'Con el modelo', type: 'bar', data: plan }, TEMA_ECHARTS.serie('modelo')),
    Object.assign({ name: 'Oráculo', type: 'line', data: oraculo }, TEMA_ECHARTS.serie('oraculo')),
  ],
});
```

## 5. Esqueleto de `app.html` y contrato de cada pantalla

```
app.html                 entrada única (en la raíz del proyecto)
app/tokens.css           tokens
app/componentes.css      componentes
app/iconos.js            iconos
app/tema_echarts.js      tema de ECharts
app/componentes.js       comportamiento de los componentes
app/datos_app.js         window.DATOS_APP, generado por generar_datos_app.py (cada cifra con su fuente)
app/app.js               la app: registro de pantallas, enrutado por hash, estado, módulos embebidos
app/pantallas/*.js       una pantalla por archivo: inicio.js, demanda.js, modelo.js, horario.js, despacho.js, ciudad.js, resultado.js, piloto.js, metodo.js
lib/, mapa_local/        bibliotecas y mapa locales (ya existen)
```

`app.html` carga, en este orden: `app/tokens.css`, `app/componentes.css`, `lib/echarts.min.js`, `app/iconos.js`, `app/tema_echarts.js`, `app/componentes.js`, `app/datos_app.js`, `app/pantallas/*.js` y, el último, `app/app.js`. El cuerpo es el esqueleto de la sección 3 (`.app` > `.lateral` + `main.contenido#contenido`), con un enlace «Saltar al contenido» (`.oculto`, visible al enfocar) antes de la barra.

### 5.1 Contrato de una pantalla

Cada archivo de `app/pantallas/` registra una pantalla:

```js
registrarPantalla({
  id: 'demanda',                                  // también el hash: #demanda
  pregunta: '¿Cuántos pasajeros habrá?',          // h1 de la cabecera y texto de la barra lateral
  subtitulo: 'El modelo se equivoca en 14 de cada 100 pasajeros a una semana; la regla manual, en 20.',
  icono: 'demanda',                               // nombre de iconos.js
  interruptor: ['hoy', 'modelo'],                 // opciones habilitadas; las demás salen deshabilitadas
  modulo: null,                                   // o { pagina: 'EDA_visual.html', hash: 'demanda', nombre: 'Tablero' } para una pantalla con iframe
  render(contenedor, datos, estado) { … },        // pinta la pantalla dentro de contenedor (div.pantalla) a partir de datos (DATOS_APP) y estado
  actualizar(estado) { … },                       // opcional: reacciona al interruptor o a la ruta sin volver a pintar todo
  salir() { … },                                  // opcional: dispose de gráficos, cancelar temporizadores
});
```

`estado` es un objeto compartido y de solo lectura para las pantallas: `{ pantalla, escenario: 'hoy' | 'modelo' | 'oraculo', modelo: 'final' | 'hibrido', ruta: 'Todas' | 'SILENCIO' | 'CRA 54' | 'CL 72', dia: 'AAAA-MM-DD', hora: 'HH:MM', tema: 'auto' | 'light' | 'dark' }`. Las pantallas piden cambios con `app.ponerEstado({ escenario: 'modelo' })`; la app guarda el estado en el hash (`#despacho?dia=2025-06-03&hora=07:30`) y vuelve a llamar `actualizar(estado)` o, si la pantalla no lo define, `render`.

### 5.2 `app.js`

1. **Registro**: `registrarPantalla` guarda la definición en orden de registro (el orden de la barra lateral es el de la lista de la sección 7, fijado en `app.js`, no el de carga). Hay un solo registro: si una pantalla carga antes que `app.js`, su definición espera en `window.__pantallasRegistradas` (app.html define en `<head>` un `registrarPantalla` de espera), y `app.js` la recoge al cargar; una pantalla que llega tarde se pinta en cuanto se registra. El orden de los scripts no importa. Al salir de una pantalla se llama `salir()` y, al volver, `render` otra vez (no `actualizar`), porque `salir()` ya liberó gráficos y oyentes.
2. **Enrutado por hash**: al cargar y en `hashchange` lee `#id` (y los parámetros tras `?`), marca el enlace activo (`aria-current`), pone la cabecera (rótulo, pregunta, subtítulo, interruptor con sus opciones) y llama a `render` la primera vez y `actualizar` después. Sin hash, abre `#inicio`. Un hash desconocido abre Inicio con un aviso.
3. **Cabecera e interruptor**: una sola cabecera para todas las pantallas; el interruptor cambia `estado.escenario` y avisa a la pantalla. En Inicio la cifra protagonista cuenta del valor de hoy al del modelo.
4. **Pantallas con módulo**: `main` recibe `.contenido--modulo`; el iframe se crea la primera vez con `src="<pagina>?embebido=1#<hash>"`, se escucha `message` (`listo`, `estado`, `navegar`) comprobando `event.source === iframe.contentWindow`, se envía `{tipo:'tema', tema:'light'}` al cargar cada iframe y `{tipo:'dia', dia, hora}` cuando otra pantalla cambió el día; al salir, el iframe se duerme con `.modulo--dormido`. El módulo lo declara la pantalla (`modulo`, con `completo: true` si ocupa toda la zona de contenido; con `completo: false`, o sin decirlo, va al final de la pantalla con alto propio, debajo del resumen). Desde el 3-nov-2026 las nueve pantallas tienen archivo propio en `app/pantallas/` y `app.js` ya no trae módulos por defecto ni versión breve: Demanda y Método llevan el tablero (`EDA_visual.html`, pestañas `demanda` y `datos`), Horario el planificador, Despacho la consola y Ciudad la vista 3D, todos con `completo: false`, es decir, resumen propio (fichas con fuente, para que el jurado lea primero) y el módulo debajo. Ciudad usa el interruptor con la etiqueta «Los dos» sobre el valor `escenario=oraculo` (`hoy` → `ver=real`, `modelo` → `ver=plan`, `oraculo` → `ver=ambos`), y sigue también al selector de la propia vista. Una pantalla que lleva un iframe dentro de su propio contenido (Resultado, con el simulador) se duerme también fuera de pantalla (`.pantalla--dormida`, inerte), nunca con `hidden`. Si el archivo de una pantalla no carga, la cabecera sale sola (sin subtítulo) y la consola lo dice.
5. **Tema**: solo claro; `html` lleva `data-theme="light"` fijo y no hay botón de tema. La cabecera pone a la izquierda, encima del título, el cuadro de color de la pantalla (`#cab-cuadro`).
6. **Accesibilidad**: la barra es `nav` con enlaces reales; el foco pasa al `h1` al cambiar de pantalla; todo control es un control nativo (botón, radio, details); los gráficos llevan `role="img"` con `aria-label` y la tabla gemela.
7. **Rendimiento**: cada pantalla se pinta la primera vez que se abre; los módulos pesados (vista 3D) solo cuando se entra en su pantalla; los gráficos se crean con `TEMA_ECHARTS.init` y se destruyen en `salir()`.

## 6. Convenciones de texto

- Español llano, frases cortas, voz activa. Se dice lo que es: «Hoy» (lo que Sobusa hace), «Con el modelo» (lo que proponemos), «Oráculo» (la decisión con la demanda que de verdad llegó). «Modelo final» es el de E11 (LightGBM con calendario y demanda reciente); «híbrido» es el de E12 (LightGBM con las variables de Chronos-2), el recomendado para producción. Los dos se muestran.
- Nada de emojis, ni adornos, ni puntos suspensivos de misterio. Sin mayúsculas de énfasis. Los nombres de las rutas van como en los datos: SILENCIO, CRA 54, CL 72.
- Números en es-CO: coma decimal, punto de miles, espacio fino antes de `%` y de la unidad (`13,94 %`, `2.825 M COP`, `4,3 min`); negativos con el signo menos tipográfico (−). Los decimales que trae la fuente, no más: dos en porcentajes de error, uno en minutos, ninguno en salidas y pasajeros. Fechas: «3 de junio de 2025» en texto (`formato.fechaLarga`), «3 jun 2025» en tablas y líneas de tiempo (`formato.fecha`), «3 jun» en ejes (`formato.fechaCorta`).
- Cada cifra se escribe una sola vez en `datos_app.js` y las pantallas la leen; un texto con una cifra se arma en JS con la cifra (`'β = ' + F.numero(beta, 2)`), nunca con el número escrito en la frase.
- Rótulos de los botones: lo que pasa («Reproducir el día», «Ver tabla», «Ver cómo se calculó»). Avisos: qué pasa y qué hacer, sin disculpas.
- Sin rutas absolutas, sin carpetas temporales, sin nombres de repositorios; las fuentes se citan relativas a la raíz del proyecto.

## 7. Wireframes de las nueve pantallas

Las cifras se nombran por su id en el inventario de cifras de la app (`inventario_cifras.md`, 200 cifras en 9 pantallas), que es el contrato de `generar_datos_app.py`. En todas: cabecera (rótulo, pregunta, subtítulo, interruptor), después el resumen, después el detalle, y al final los límites y las fuentes.

### Inicio · ¿Qué proponemos?

Interruptor: Hoy / Con el modelo (Oráculo deshabilitado).

1. Frase de la propuesta (entradilla): no quitar buses, cambiarlos de hora; un pronóstico que se equivoca en 14 de cada 100 pasajeros en vez de 20.
2. Cifra protagonista (`.cifra--hero`): `inicio_error_regla_manual` → `inicio_error_modelo_final` (cuenta al mover el interruptor), con nota del híbrido `inicio_error_hibrido` y su mejora `inicio_mejora_hibrido_2025` / `inicio_mejora_hibrido_2024`.
3. Fila de cuatro fichas hoy → modelo: `inicio_salidas_dia_hoy`/`_plan`, `inicio_buses_hora_hoy`/`_plan`, `inicio_espera_hoy`/`_plan`, `inicio_sobrecapacidad_hoy`/`_plan`.
4. El problema en una imagen: barras de CRA 54 laboral hoy frente al plan (como en la muestra), con la frase `horario_frase` y las cifras de picos y valles `inicio_salidas_cra54_laboral_hoy`, `_necesarias`, `inicio_salidas_sobran_cra54`, `inicio_salidas_faltan_cra54` (con el rótulo de horas de D2, no el de la propuesta: contradicción C14).
5. Lo que gana Sobusa, con aviso de canje: `inicio_ahorro_operativo_plan`, `inicio_pax_riesgo_plan`, `inicio_saldo_conservador` frente a `inicio_saldo_simetrico`, `inicio_pax_netos_simetrica`; segundo aviso: `inicio_recorte_no_paga_d5` y `inicio_recorte_no_paga_s1` (recortar no paga), `inicio_domingos_pagan`.
6. β y el piloto: `inicio_beta`, `inicio_beta_rango`, `inicio_beta_origen` (aviso de atención: medida con fallas), `inicio_beta_equilibrio_d5`, `inicio_piloto_resumen` → enlace a Piloto.
7. Hallazgo honesto (aviso crítico): `inicio_persona_a_persona_saldo` y `inicio_hallazgo_3jun` → enlace a Ciudad.
8. Cómo lo decide cada día: `inicio_backtest_plan_vs_oraculo` → enlace a Despacho.
9. Pie: `inicio_rutas`, `inicio_regla_manual_definicion`, `inicio_demanda_por_anio`, `inicio_caida_anual`, `inicio_2026_mas_viajes`, `inicio_dias_gps_2025`, `inicio_costo_bus_hora`, `inicio_costo_km`, `inicio_tarifa_neta`, `inicio_equipo`.

### Demanda · ¿Cuántos pasajeros habrá?

Interruptor: Hoy (regla manual) / Con el modelo (segmentado secundario: modelo final / híbrido). Módulo: `EDA_visual.html` en una pestaña «Explorar los datos» (pestañas `demanda`, `horas`, `mapa`).

1. Fichas: error a 7 días por escenario (`demanda_wape_por_ruta` global), `demanda_wape_h1`, `demanda_wape_total_diario`, `demanda_festivos` (de E1, con la nota de C2).
2. Gráfico de líneas real / regla manual / modelo (`demanda_serie_diaria_2025`, selector de ruta con chips) y, debajo, el día de ejemplo por hora (`demanda_serie_hora_ejemplo`, 3 de junio, CRA 54).
3. Tabla de errores por ruta, tipo de día, franja y antelación (`demanda_wape_por_ruta`, `_por_tipo_dia`, `_por_franja`, `_antelacion`, `demanda_hibrido_antelacion_emulacion`), con el mejor valor en el acento.
4. «Ver cómo se calculó»: `demanda_protocolo`, `demanda_sesgo`, `demanda_intervalo_e3`.
5. Qué ayuda y qué no: `demanda_lo_que_si_ayuda`, `demanda_lo_que_no_ayuda`, `demanda_lluvia`, `demanda_correlacion_rutas`, `demanda_un_modelo_por_ruta`, `demanda_otras_rutas_como_variable`, `demanda_dias_atipicos`, `demanda_otros_metodos`.
6. Los datos tienen problemas (aviso de atención): `demanda_dias_con_problema_datos`, `demanda_pax_cancelados_corrieron_2025`, `demanda_objetivo_corregido`, `demanda_error_total_diario_corregido`, `demanda_horas_faltan_buses`, `demanda_horas_buses_exactos` (con la nota de C17).
7. 2026: `demanda_2026_variacion`, `demanda_elasticidad_aparente_2026`, `demanda_pronostico_2026_enero` y el límite del cambio de nivel (`modelo_limite_nivel_2026`).

### Modelo · ¿Qué modelo es y por qué?

Interruptor: no aplica (deshabilitado con tooltip); en su lugar, dos fichas lado a lado (`.rejilla-2`) con pestañas en teléfono: **Modelo final (E11)** y **Híbrido (E12), recomendado para producción** (chip `--acento`).

1. Cada ficha: qué es (`modelo_final_nombre` / `modelo_hibrido_nombre`), error 2025 y 2024 (`modelo_final_*`, `modelo_hibrido_wape_2025`, `_2024`, `modelo_hibrido_sesgo`), variables (`modelo_final_variables`, importancia `modelo_final_importancia`; `modelo_hibrido_ganancia_chronos`), hiperparámetros (`modelo_final_hiperparametros`), tiempos y entorno (`modelo_final_tiempo_entrenamiento`, `modelo_hibrido_costo_cpu`, `modelo_hibrido_tiempos`, `modelo_entorno`), producción (`modelo_final_produccion`, `modelo_hibrido_emulacion`).
2. Por qué el híbrido y no el ganador formal (aviso de canje): `modelo_regla_seleccion_e12`, `modelo_comparacion_51`, `modelo_correccion_multiple`, `modelo_por_que_hibrido` (contradicción C18).
3. Tabla de la comparación: `modelo_finalistas`, `modelo_otros_arboles`, `modelo_redes`, `modelo_fundacionales`, `modelo_clasicos`, `modelo_plantillas_hoja_calculo`.
4. «Ver cómo se calculó»: `modelo_final_pliegues`, `modelo_final_horizontes`, `modelo_final_pesos`, `modelo_final_candidatos`, `modelo_final_seleccion`, `modelo_fugas`.
5. Límites: `modelo_limite_nivel_2026`, `modelo_e13_recomendacion`, `modelo_e13_imputar_empeora`.

### Horario · ¿Cuántos buses y cada cuánto?

Interruptor: Hoy / Con el modelo (y Oráculo solo en las tablas de calidad de decisión). Módulo: `planificador.html` (`?embebido=1#plan`), con chips de ruta y tipo de día enviados por mensaje.

1. Fichas del día promedio (`horario_dia_promedio_2025`): salidas, buses-hora, espera, sobrecapacidad, costo; frase `horario_frase`.
2. El gráfico de barras hoy / recomendado por hora (del planificador) con la tabla de las nueve combinaciones `horario_tabla_9_combinaciones` y `horario_aviso_flota`.
3. Módulo: el planificador completo (elegir ruta, tipo de día, costos, elasticidad; horario minuto a minuto `horario_recomendado_minuto_a_minuto`).
4. Aviso de canje: con los supuestos de D5 el plan recortaba (`horario_dia_promedio_supuestos`, `horario_dia_tipico_d5`, `horario_escenarios_d5`); con los costos con fuente reasigna.
5. «Ver cómo se calculó»: `horario_juegos_de_costos`, `horario_parametros_milp`, `horario_validacion_planificador`, `horario_datos_planificador_js`.
6. Qué tan cerca del óptimo (con Oráculo): `horario_calidad_decision_d5`, `horario_calidad_decision_d1`, `horario_beta_equilibrio_asimetrica_d5`; flota: `horario_flota_d2`, `horario_exceso_deficit_d2`, `horario_picos_y_valles_cra54`; simulador D6 `horario_simulador_d6`.

### Despacho · ¿Qué hago ahora?

Interruptor: Hoy (oferta real / sin nowcast) / Con el modelo (plan semanal y motor) / Oráculo. Módulo: `consola_despacho.html` (`?embebido=1#dia=2025-06-03&hora=07:30`), debajo del resumen con alto propio (`completo: false`); «Ir a la consola» desplaza hasta él, y un cambio de día en la consola llega al hash y a Ciudad.

1. Resumen antes de la consola: `despacho_pantalla_7_30` (texto), `despacho_decision_vs_oraculo_h7` como fichas (plan, real, motor frente al oráculo) y `despacho_cobertura_intervalo`.
2. Módulo: la consola (mapa, lista de despachos, reloj; el día y la hora viajan a Ciudad por `{tipo:'estado'}`).
3. «Ver cómo se calculó»: `despacho_backtest_muestra`, `despacho_decision_vs_oraculo_h4`, `despacho_nowcast_wape`, `despacho_alertas`, `despacho_metodo_solucion`, `despacho_guarda_datos`, `despacho_simulador_d6`, `despacho_verificacion_plan`, `despacho_latencias`, `despacho_indice_replay`.
4. Aviso de atención: reoptimizar en el día no aporta frente al plan semanal (motor 1,08 frente a 1,05); la corrida vigente no tiene revisor (C9).

### Ciudad · ¿Cómo se ve en la calle?

Interruptor: Hoy (real) / Con el modelo (plan) / Los dos (en esta pantalla, «Oráculo» se reemplaza por «Los dos», que es el modo de la vista 3D: `escenario=oraculo` → `ver=ambos`). Módulo: `vista_3d.html` (`?embebido=1#dia=…&hora=…&ver=…&pausa=1`), debajo del resumen con alto propio (`completo: false`); termina de cargar (y avisa «listo») cuando su iframe entra en la ventana.

1. Fichas del 3 de junio real frente a plan (`ciudad_3jun_real`, `ciudad_3jun_plan`, `ciudad_3jun_balance`, `ciudad_3jun_pronostico`) y el aviso crítico del hallazgo (`ciudad_3jun_cra54_17_19`: el plan pone 10 / 9 / 7 donde hubo 15 / 19 / 14).
2. Módulo: la vista 3D con sus modos (Real, Plan, Los dos; cine; recorrido).
3. Todo 2025 con el mismo modelo: `ciudad_2025_real`, `ciudad_2025_plan`, `ciudad_2025_saldo`, `ciudad_2025_por_tipo_dia`, `ciudad_2025_por_hora`, `ciudad_dias_saldo_negativo` (aviso de canje: contabilidad conservadora frente a simétrica; comparación con las cifras de D5, contradicción C8).
4. «Ver cómo se calculó»: `ciudad_plan_meta`, `ciudad_cobertura_trayectorias`, `ciudad_alertas_3jun_0730`, `ciudad_version_calles`; límites: sin tope de cupo, demanda real asignada a los buses del plan.

### Resultado · ¿Qué gana Sobusa?

Interruptor: Hoy (línea base) / Con el modelo (plan (b) que reasigna; segmentado secundario para el plan (a) que recorta). Módulo: `simulador_ahorro.html` (`?embebido=1#fecha&plan=b`).

1. Fichas del año: `resultado_linea_base_2025` (hoy) y `resultado_d5_reoptimizado` (plan a y b), `resultado_simulacion_plan_b` (conductores, plantilla, pasajeros en riesgo).
2. Aviso de canje con las dos contabilidades y `resultado_por_tipo_dia` (solo domingos y festivos pagan).
3. Gráfico de sensibilidad a β (`resultado_sensibilidad_beta`, `resultado_beta_equilibrio`) y tornado (`resultado_tornado_d5`).
4. Módulo: el simulador por fecha.
5. «Ver cómo se calculó»: `resultado_costos_unitarios_2026`, `resultado_ahorros_por_escenario`, `resultado_costo_conductor`, `resultado_conductores_2025`, `resultado_demanda_dia_d5`, `resultado_verificaciones_costos`, `resultado_e7_netos_supuestos` (solo como historia).

### Piloto · ¿Cómo lo comprobamos?

Sin interruptor (deshabilitado con tooltip). Sin módulo.

1. Por qué (`piloto_por_que`) y aviso de atención: β se midió con fallas.
2. Línea de tiempo de las 8 semanas (`piloto_calendario`: inicio, cierres de bloque, festivos, fin) y las seis franjas como tabla (`piloto_franjas`).
3. Fichas: potencia (`piloto_potencia`), riesgo (`piloto_riesgo_por_franja`, `piloto_totales`), parámetros (`piloto_parametros`).
4. «Ver cómo se calculó»: `piloto_simulacion`, `piloto_ejemplo_analisis`, `piloto_reglas_de_parada`, `piloto_planilla`.
5. Marcas del revisor: P2 sí tiene revisión independiente (13-oct-2026, registrada en la tanda B), así que sus cifras salen con «Revisor independiente: sí»; la pantalla pinta la marca que trae cada cifra de `datos_app.js`, sin escribirla a mano.

### Método y datos · ¿De dónde sale todo?

Sin interruptor. Módulo: `EDA_visual.html#datos`, debajo del resumen (`completo: false`). Como está hecha (`pantallas/metodo.js`, 3-nov-2026): entradilla («ninguna cifra está escrita a mano») y nueve secciones.

1. De qué datos partimos: `metodo_datos_crudos` (1.096 días, 520 mil viajes, 176 millones de eventos GPS), `metodo_tablas_exportadas` y el embudo de viajes.
2. Qué viajes cuentan: `metodo_reglas_limpieza`, los viajes marcados cancelados que sí corrieron y la unidad de análisis.
3. Lo que mandaron los organizadores: la ficha «Capacidad real de la flota» (`metodo_capacidad_flota`, con el año leído de la clave `vehiculos_<año>`), la línea «Último día de cada mes de <año>» (`metodo_ultimo_dia_mes`, año leído de sus fechas) y la lista de insumos (`insumos_sobusa/`).
4. Cómo se mide: `metodo_protocolo`, `metodo_variables`, `metodo_pesos_entrenamiento`, `metodo_sin_fugas`.
5. Los experimentos y su revisión: `metodo_experimentos` como tabla con la fecha de verificación y chips de estado; `metodo_rondas_verificacion`.
6. Las cifras con varias bases: las contradicciones del inventario (`DATOS_APP.contradicciones`) y cuál prevalece en la app.
7. Cómo se verificó la app: generador, verificador, pruebas (`DATOS_APP.meta`).
8. Quiénes y con qué: `metodo_equipo`, `metodo_herramientas`. Regla visible: la base de datos es compartida y de solo lectura; la app no la consulta.
9. Explorar los datos: el tablero embebido (`EDA_visual.html`, pestaña `datos`).

## 8. Verificación de la muestra

`app/probar_muestra.py` prueba `app/muestra.html` con Playwright en Microsoft Edge (canal `msedge`, sin interfaz, render por software con swiftshader), desde `file://`, con todas las peticiones a internet bloqueadas: con el sistema en claro y en oscuro (la muestra debe verse clara en los dos casos), a 1366 y 400 px de ancho, con la barra plegada, el interruptor, el popover de fuente (y que quede bajo su botón), la tabla gemela y las pestañas. Criterios: 0 errores de consola y de página, 0 peticiones a internet, sin desplazamiento horizontal del documento y sin elementos que se salgan del ancho de la ventana (salvo dentro de un contenedor con desplazamiento propio, como una tabla en `.tabla-marco`). Resultado del 18-10-2026: veredicto OK en las ocho vistas (0 errores, 0 avisos, 0 peticiones a internet, `scrollWidth` igual al ancho de la ventana en todas), popover bajo su botón, las pestañas inferiores del teléfono se desplazan (735 px de contenido en 400 de ventana). Las dieciséis capturas y `resultados.json` quedan en `app/capturas_muestra/`.

Uso, desde la carpeta del proyecto: `PYTHONIOENCODING=utf-8 python app/probar_muestra.py` (unos 20 s).

La app completa y las cinco páginas tienen su propia prueba de humo en las mismas condiciones (Edge sin interfaz, swiftshader, `file://`, internet bloqueado): `app/probar_app.py` recorre las nueve pantallas a 1366 y 400 px y falla si hay errores de página o de consola, desbordes, pantallas sin h1 o módulos embebidos que no cargan (opciones `--ancho`, `--pantalla`, `--capturas`); `app/probar_paginas.py` abre las cinco páginas y comprueba que sus datos JS cargan, que los gráficos y mapas se dibujan, que la consola abre el 3 de junio de 2025 a las 7:12 y que la vista 3D usa el mapa local. Resultado del 2-11-2026: OK en las dos (0 errores, 0 desbordes, los cinco módulos «Listo»; 56 s y 12 s). Las capturas van a `app/capturas_pruebas/` (no se versionan).

## 9. Decisiones y pendientes

- Las cinco páginas existentes ya tienen el modo embebido: con `?embebido=1` (o dentro de un iframe) ponen `html[data-embebido]`, ocultan marca, enlaces y pie, cargan `app/tokens.css`, no leen ni escriben `localStorage` y hablan con la app por mensajes. La app les manda `{tipo:'tema', tema:'light'}` al cargar (un tema que no sea claro se ignora), `{tipo:'dia', dia, hora}` (consola, vista 3D y simulador; el tablero y el planificador lo ignoran), `{tipo:'pestana', pestana}` (tablero, planificador, simulador), `{tipo:'ruta', ruta}` (planificador) y `{tipo:'ver', ver}` (vista 3D); ellas avisan `{tipo:'listo', pagina}` al cargar, `{tipo:'estado', pagina, dia, hora}` cuando el usuario cambia el día (o pausa, en consola y vista 3D) y `{tipo:'navegar', pantalla, parametros:{dia, hora}}` desde «Vista 3D →» (a `ciudad`) y «Consola de despacho →» (a `despacho`), que en modo embebido no navegan. El tablero, el planificador y la vista 3D atienden además `hashchange`. Abiertas solas no cambian.
- La vista 3D ya no tiene bloque oscuro (solo claro desde el 19-oct-2026): sus colores fijos de controles pasaron a tokens (`--control`, `--texto-invertido`, `--borde-hover`, `--deshabilitado`, `--linea-suave`, `--pista`, `--persona-baja`, `--borde-busito`, `--hora-actual`, `--surface-2`), que el puente de `tokens.css` también vuelca. Los colores del mapa y de las capas 3D siguen la hora del sol (luz por hora: de noche el mapa se oscurece y se encienden las ventanas de los buses): es la escena del día, no un tema, y se conserva; sus paneles son claros.
- Las fuentes Barlow Condensed e IBM Plex Sans de `lib/fuentes.css` siguen en las páginas sueltas; dentro de la app el puente las sustituye por la pila del sistema.
- Si el jurado prefiere ver un solo modelo, el interruptor secundario «final / híbrido» se deja en «híbrido» por defecto y la ficha del final queda en «Ver cómo se calculó».
- La vista 3D embebida (Ciudad) solo termina de cargar, y avisa `{tipo:'listo'}`, cuando su iframe entra en la ventana: el navegador no le da cuadros de animación mientras está fuera de la vista. Por eso `probar_app.py` desplaza hasta el módulo antes de esperar «Listo» (3-nov-2026). Sin internet, la consola y la vista 3D dejan en la consola del navegador una línea «Failed to load resource» por el intento del mapa en línea (`server.arcgisonline.com`, `tiles.openfreemap.org`) antes de caer a la copia local de `mapa_local/`; no es un error de la app y las pruebas lo descartan (`net::ERR_FAILED`).
- `EDA_visual.html` se embebe dos veces, en Demanda (pestaña `demanda`) y en Método (pestaña `datos`): son dos módulos distintos, con un iframe cada uno; el tablero se carga dos veces si se visitan las dos pantallas.

## 10. Pulido con las guías de Vercel y Taste Skill (19-oct-2026)

Se auditó la app con las Web Interface Guidelines de Vercel (accesibilidad, interacción, contenido) y con las reglas de la Taste Skill v2 (dirección de arte), tomando como referencia el estilo de apple.com y de las HIG de Apple (los valores están **inspirados en** esas convenciones públicas, no copiados). Cuando una regla de gusto chocaba con una de accesibilidad, ganó la accesibilidad; cuando una regla quitaba información que el jurado necesita, no se aplicó: las notas, los intervalos, los avisos y el hallazgo honesto se movieron (al popover de fuente o a un desplegable), no se borraron. Ninguna cifra cambió: todas siguen saliendo de `app/datos_app.js` y `verificar_datos_app.py` pasa.

**Qué se cambió y por qué**

- **Tokens (Apple).** Neutros grises sin sesgo verde (`#f5f5f7` / `#fff` / `#1d1d1f`; en oscuro `#000` / `#1c1c1e` / `#f5f5f7`), escala tipográfica con cuerpo de 17 px y títulos de 28-44 px, radios 8 / 12 / 18, casi sin sombras, `--e-9`. Las rutas, los estados y las series no cambian: codifican datos.
- **Superficies por tono, no por línea.** Fichas, gráficos, tablas, desplegables, tarjetas y módulos sin borde de 1 px, sobre el fondo gris; lo anidado va en `--superficie-2`. Las líneas entre filas de tabla y la rejilla de los gráficos se mantienen.
- **Jerarquía.** Sin rótulo en mayúsculas encima del h1; sin mayúsculas espaciadas en cabeceras de tabla, rótulos, fechas y popovers; texto corrido en 17 px y en tinta completa; el gris solo para notas y ejes; subtítulos de sección debajo del título.
- **Espacio.** 64 px entre secciones y 24 dentro; más margen en escritorio.
- **Inicio.** Una sola frase de apoyo («No quitar buses: cambiarlos de hora.») y el héroe como pareja Hoy → Con el modelo a todo el ancho; debajo, el híbrido («Recomendado para producción» como texto, no como píldora) y E1. «Cómo se mide» en un desplegable.
- **Fichas.** Etiqueta, valor y una línea; la nota de qué mide va al popover de fuente (Inicio, Modelo) o a «Qué mide cada cifra» (Resultado); en «Hoy» no se repite por ficha «lo que Sobusa hace hoy»: lo dice la intro.
- **Avisos.** Fondo neutro con el color solo en icono y título; el crítico, con un fondo teñido muy pálido. Las filas de botones de fuente se juntan en «Fuentes (n)».
- **Barra.** En escritorio, una línea por pantalla y selección gris; en el teléfono, cinco elementos fijos y la hoja «Más» (antes solo se veían 4 de 9 pestañas y la quinta cortada).
- **Interruptor.** Sin puntos de color; desactivado en `--tinta-3`; el selector de plan de Resultado es pequeño, con su rótulo «Plan:» y bajo el título; cabecera compacta fija al bajar.
- **Movimiento.** Fundido corto de 320 ms al entrar a una pantalla (no en las de módulo, para no repintar WebGL); gráficos con 500 ms `cubicOut`; todo a 0 con movimiento reducido.
- **Accesibilidad (Vercel).** Zonas de toque de 24 px en escritorio y 40-44 px en el teléfono (con `::after`, sin mover el diseño); `scroll-padding-bottom` para que la barra inferior no tape el foco; anillo de foco visible en las pestañas del teléfono; popover con alto máximo, desplazamiento propio y `overscroll-behavior: contain`; `meta theme-color` tomado de `--fondo`; `touch-action: manipulation` y resaltado de toque elegido; roles de pestaña de Modelo solo en el teléfono, con Inicio y Fin; sin saltos de nivel de encabezado (h2 ocultos donde faltaban; h4 → h3 en Modelo); dígitos tabulares en todas las tablas; «Cargando el simulador…» solo cuando de verdad carga; posición de lectura al volver con Atrás; nombres accesibles sin repeticiones; «Ver tabla» sin `aria-pressed` y con `aria-controls`; tooltips con retraso de 400 ms al pasar el puntero; el botón de plegar dice lo que hará; «tú» en todos los textos; sin «Versión breve… por ahora»; `aria-live` en el estado de los módulos y en el cambio de escenario; el plan de Resultado (`plan=a|b`) viaja en el hash.
- **Páginas embebidas.** Solo bajo `html[data-embebido]`: tipo de frase en pestañas y rótulos, tarjetas sin borde, campos de 16 px en el teléfono, y en la vista 3D oscura el magenta del plan, el rojo y el verde con contraste de unos 5,7:1. Abiertas solas, las cinco páginas no cambian (se comprobó con Playwright: mayúsculas de sus pestañas y `--plan` de la vista 3D, como antes). Nota del 3-nov-2026: la vista 3D embebida carga al entrar en la ventana (debajo del resumen de Ciudad), y sin internet la consola y la vista 3D dejan una línea «Failed to load resource» por el mapa en línea antes de usar la copia local (ver la sección 9).

**Reglas que se descartaron, y por qué**

- Transiciones solo de `transform`/`opacity` al plegar la barra (Vercel): la animación de `grid-template-columns` dura 320 ms, respeta el movimiento reducido y los gráficos esperan al final para redimensionarse; animar solo los textos dejaría la columna saltando.
- Quitar el nombre de la unidad de los ejes (Taste/Apple): no todos los subtítulos de gráfico la dicen; se dejó en `--tinta-3`.
- Icono de fuente con opacidad 0,55 dentro del texto: bajaría el contraste del control por debajo de 3:1 (WCAG 1.4.11). Se dejó en `--tinta-3` a 12 px.
- El número mismo como botón de fuente en los párrafos: habría que reescribir todos los avisos; el icono de 12 px que no altera el interlineado resuelve lo mismo.
- Ocultar `.modulo__barra` y dejar «Abrir aparte» flotando sobre el marco: taparía controles de las páginas embebidas; la barra queda discreta y sin fondo.
- Fotos reales, vídeo, escenas de desplazamiento, 8-16 elementos animados, 120-240 px entre secciones, cinco tamaños de letra como máximo, serif editorial, vidrio y desenfoque, doble bisel, grano de fondo, «un solo color»: son reglas de páginas de marca; en una herramienta de análisis distraen, y los colores de rutas, estados y series codifican datos.
- Formularios, hidratación, herramientas propias de Vercel, imágenes, fuentes externas, virtualización, Title Case, `Intl.DateTimeFormat`: no aplican a una app sin servidor que se abre con doble clic (ver la auditoría).
- Notas de las fichas de Piloto: comparten un mismo popover por archivo (`piloto_totales`), así que se dejaron visibles, en 14 px.

## 11. Solo modo claro y paleta (19-oct-2026)

Pedido de Rubén: «solamente deja el modo blanco, el claro, no el oscuro, y ten una paleta de colores». Ninguna cifra cambió (`verificar_datos_app.py`: 0 fallos).

**Solo modo claro**

- `tokens.css`: fuera el bloque `@media (prefers-color-scheme: dark)`, el `:root[data-theme="dark"]` y las islas `.tema-claro` / `.tema-oscuro`; `color-scheme: light`. El puente `:root[data-embebido]` solo tiene valores claros.
- `app.html`: `data-theme="light"` fijo, `meta color-scheme` en `light`, sin botón de tema y sin leer `sobusa-despacho-tema` de `localStorage`. `componentes.js` ya no tiene `aplicarTema`; `tema_echarts.js` tiene un solo tema (`sobusa-claro`) y no observa cambios de tema; `app.js`, Modelo y Resultado dejaron de vigilar el tema. Se retiraron los iconos `sol`, `luna` y `tema-auto`.
- Módulos embebidos: la app envía `{tipo:'tema', tema:'light'}` al cargar cada iframe (también el simulador dentro de Resultado). Cada una de las cinco páginas fija `data-theme="light"` en el `<script>` de su `<head>`, antes de pintar, esté embebida o abierta sola: no hay parpadeo oscuro aunque el sistema esté en oscuro. Su oyente de mensajes ignora un tema que no sea claro.
- Páginas abiertas solas (tablero, planificador, consola, vista 3D, simulador): sin bloque oscuro en su CSS, sin botón de tema (planificador, consola y simulador lo tenían) y sin leer el tema guardado (`sobusa-planificador-tema`, `sobusa-consola-tema`, `sobusa-simulador-tema`): si alguien eligió «oscuro» antes, se ignora. El tablero y la consola usan siempre el mapa base gris claro de Esri. La vista 3D conserva su luz por hora (escena del día, no tema).

**Paleta de colores**

- `tokens.css` define nueve colores con nombre (turquesa, azul, índigo, naranja, coral, cian, verde, morado y gris; el 19-oct el cuadro turquesa pasó a `#0a9396`, más vivo que el acento, y Piloto cambió el ámbar, que se veía mostaza, por el morado de Apple), cada uno con tono de cuadro, tono de texto y tinte (tabla en §2.1), y `--pantalla-<id>` para cada pantalla.
- Uso, como en Ajustes del iPhone: ícono blanco en un cuadro redondeado del color de la pantalla en la barra lateral (entrada activa con el gris de selección y el texto en tinta), en la barra del teléfono (todos a pleno color, la activa con su nombre en tinta y un punto, como el Dock), en la hoja «Más» y, discreto, encima del título de cada pantalla. Nada más se tiñe: los gráficos (gris = hoy, turquesa = modelo, tinta a trazos = oráculo, rutas azul / naranja / morado) y los estados conservan sus colores.
- Hoja de la paleta: [`app/paleta.html`](paleta.html) (doble clic, sin internet), enlazada también desde la pantalla Método y datos («Paleta de colores») y desde `muestra.html` (sección «Paleta de pantallas», que sustituye a «Los dos temas a la vez»). Los contrastes se calculan en la página a partir de los tokens y se comprobaron con un script (todos cumplen).

**Comprobado** con Playwright en Edge y el sistema en oscuro (`color_scheme="dark"`) y un «oscuro» guardado de antes en `localStorage`: las nueve pantallas a 1366 y 400 px con fondo `#f5f5f7`, `data-theme="light"`, sin errores ni desbordes; los iframes de Horario, Despacho, Ciudad y Método claros por dentro; las cinco páginas sueltas claras y sin botón de tema; `app/probar_muestra.py` OK.
