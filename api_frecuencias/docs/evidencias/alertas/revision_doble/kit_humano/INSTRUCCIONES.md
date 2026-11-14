# Revisión doble HUMANA de alertas: instrucciones para el área operativa de Sobusa

La §18 de la especificación v1.5 pide mitigar el riesgo «Etiquetas incorrectas → métricas engañosas» con una «muestra
manual revisada dos veces y conciliación». La revisión doble de la carpeta de arriba (`../`) la hicieron agentes de
modelo de lenguaje, y por eso la fila **18-R2** de la matriz sigue en Parcial. Con este kit, dos personas del área
operativa de Sobusa revisan a mano y a ciegas las mismas 96 alertas, y un script saca solo la conciliación y las
métricas.

## Quiénes y cuánto tarda

| Papel | Quién | Tiempo |
|---|---|---|
| Revisor 1 y revisor 2 | Dos personas del área operativa de Sobusa (despacho o supervisión de turno) que conozcan la operación de SILENCIO, CRA 54 y CL 72. Mejor quienes **no** hayan leído `../resumen.md` ni las etiquetas automatizadas. | 10 min para leer el protocolo y unos 45 min para las 96 alertas (unos 30 s por alerta), cada uno por su lado |
| Moderador | Una tercera persona que no revisa, del área operativa o del equipo del proyecto: recibe los dos archivos, corre el script (paso 4, con el entorno de la API) y lleva la reunión. Si no hay tercera persona, un revisor puede moderar, pero solo después de entregar su propio archivo. | 1 min para correr el script y 15 a 30 min de reunión, según cuántos desacuerdos haya |

## 1. Reglas para que la revisión sea ciega e independiente

1. **Cada revisor trabaja solo.** No hablen de las alertas hasta que los dos hayan entregado su archivo.
2. **Solo la página.** `revisar.html` trae las tarjetas y el protocolo; no abran nada más de esta carpeta ni de la de
   arriba: ni `etiquetas_A.json`, `etiquetas_B.json`, `conciliacion.json`, `resumen.md` y `README.md` (traen etiquetas y
   cifras de la revisión automatizada), ni `conciliar.py` (trae las decisiones del conciliador automatizado), ni la base
   de datos o el backtest.
3. **Cada uno en su navegador.** El avance se guarda en el navegador con el nombre del revisor. Si comparten
   computador, cada uno usa su propio perfil del navegador y al terminar borra sus datos (paso 3).
4. **Si alguien ya vio la revisión automatizada**, no pasa nada grave, pero hay que anotarlo en `notas` del archivo de
   decisiones (paso 4): queda como limitación en la evidencia.

## 2. Revisar (cada revisor)

1. Abra `revisar.html` con doble clic (Edge, Chrome o Firefox). No necesita internet ni instalar nada.
2. Escriba su nombre (va en el archivo que descarga) y pulse «Empezar».
3. Lea el **protocolo** una vez: el orden de decisión (pasos 2.1 a 2.5) y qué cuenta como verdadera, falsa o
   indeterminada en cada código. Luego pulse «Empezar a revisar».
4. Por cada alerta: lea la tarjeta (secciones 1 a 8), aplique el orden de decisión y elija:
   - **Etiqueta**: verdadera, falsa o indeterminada. «Indeterminada» solo cuando la tarjeta no permite decidir
     (paso 2.5), no por comodidad.
   - **Confianza**: alta, media o baja.
   - **Justificación corta**: el paso que decidió y las cifras clave, por ejemplo «2.4: 420 subidas frente a 318
     puestos/h, sin calendario» (cifras inventadas, como los ejemplos del protocolo). Sirve para la reunión.

   Junto a cada alerta el panel muestra la definición de su código. Atajos de teclado: `V` `F` `I` (etiqueta),
   `A` `M` `B` (confianza), `J` (escribir la justificación; `Esc` sale), `←` `→` (anterior y siguiente).
5. Arriba se ve el avance («n de 96 terminadas»). La pestaña «Lista» muestra las 96 con lo que lleva y deja saltar a
   cualquiera; «Siguiente sin terminar» lleva a la próxima pendiente.
6. Se guarda solo. Para seguir otro día, abra el archivo y escriba **el mismo nombre**. Si la página dice «Este
   navegador no deja guardar el avance», descargue el archivo antes de cerrar y luego cárguelo en «Descargar → Cargar
   un archivo guardado».

En el celular también funciona (se copia el archivo al teléfono y se abre con el navegador), pero las tablas se leen
mejor en un portátil.

## 3. Descargar y entregar (cada revisor)

1. En «Descargar», pulse «Descargar mis etiquetas». Baja `etiquetas_humano_<su nombre>.json` a la carpeta de
   descargas. Tiene el mismo formato que `../etiquetas_A.json` (`id`, `etiqueta`, `confianza`, `razon`) más `revisor`,
   `fecha` (la hora de cada etiqueta) y `origen` = `"humano"`.
2. Envíe el archivo **al moderador, no al otro revisor**.
3. Si el computador es compartido, pulse «Borrar mis datos de este navegador».

## 4. Conciliar (moderador)

Copie los dos archivos a esta carpeta (`kit_humano/`) y, desde ella, corra el script con el entorno de la API (trae
numpy, que usa `../conciliar.py`):

```
cd EntregaFinal\api_frecuencias\docs\evidencias\alertas\revision_doble\kit_humano
..\..\..\..\..\.venv\Scripts\python.exe -I conciliar_humanos.py etiquetas_humano_revisor_a.json etiquetas_humano_revisor_b.json
```

(Los nombres son de ejemplo: use los de los archivos que recibió; cada archivo lleva el nombre que escribió su revisor,
en minúsculas, sin tildes y con `_` en lugar de los espacios.) El script:

- comprueba que cada archivo cubra las 96 alertas, con etiquetas del protocolo y origen «humano»; si falta algo, dice
  qué alertas faltan o qué corregir y no escribe nada;
- muestra el acuerdo y la kappa de Cohen con su intervalo, y la lista de desacuerdos;
- escribe `resumen_humano.md` (acuerdo, kappa y los desacuerdos con las dos justificaciones: es la agenda de la
  reunión), `conciliacion_humana.json` y `decisiones_plantilla.json`.

Mientras haya desacuerdos sin decidir, la salida **no muestra nada de la revisión automatizada**, para que la reunión
también sea ciega.

**Reunión de conciliación** (los dos revisores y el moderador, 15 a 30 min). Para cada desacuerdo: abran la alerta en
`revisar.html` (pestaña «Lista»), relean la tarjeta, apliquen el orden de decisión del protocolo y acuerden la
etiqueta final. Si la tarjeta no permite decidir, queda «indeterminada». Copien `decisiones_plantilla.json` como
`decisiones_conciliacion.json` y llenen, por cada desacuerdo, `etiqueta`, `criterio` (opcional) y `motivo`, y arriba
`fecha`, `participantes` y `notas`:

```json
{
  "conciliacion": {"fecha": "2026-11-12", "participantes": "Revisor A y revisor B (área operativa) y el moderador", "notas": ""},
  "decisiones": {
    "Mxxx": {"etiqueta": "indeterminada", "criterio": "2.5", "motivo": "La tarjeta no trae el dato que decide."}
  }
}
```

(`Mxxx` es un ejemplo: la plantilla ya trae los id de los desacuerdos.)

Reglas del archivo de decisiones: solo se deciden alertas en desacuerdo (si los dos coinciden, la etiqueta queda);
`etiqueta` es verdadera, falsa o indeterminada (vacía = sigue pendiente); `motivo` es obligatorio; las claves que
empiezan con «_» son contexto de la plantilla y no se leen.

Luego vuelvan a correr el script con las decisiones:

```
..\..\..\..\..\.venv\Scripts\python.exe -I conciliar_humanos.py etiquetas_humano_revisor_a.json etiquetas_humano_revisor_b.json --decisiones decisiones_conciliacion.json
```

Con todas las decisiones, `resumen_humano.md` y `conciliacion_humana.json` traen además la precisión por código con
intervalo de Wilson, la precisión global reponderada por población y el acuerdo entre la etiqueta humana conciliada y
la automatizada (kappa humano frente a automatizado, global, por familia, por código y por revisor, con la lista de
alertas donde difieren).

## 5. Qué queda como evidencia

Se versionan en esta carpeta:

| Archivo | Qué es |
|---|---|
| `etiquetas_humano_<revisor 1>.json`, `etiquetas_humano_<revisor 2>.json` | Las dos revisiones independientes, tal como salieron de `revisar.html` |
| `decisiones_conciliacion.json` | Las decisiones de la reunión, con su motivo, fecha y participantes |
| `conciliacion_humana.json` | Acuerdo y kappa antes de conciliar, desacuerdos, etiqueta final de las 96, precisión por código y global, y comparación con la revisión automatizada |
| `resumen_humano.md` | El resumen legible de todo lo anterior |

`decisiones_plantilla.json` es intermedio: se puede borrar cuando exista `decisiones_conciliacion.json`. Los archivos
llevan el nombre que cada revisor escribió.

## 6. Qué fila de la matriz cierra

**18-R2** (§18, «Etiquetas incorrectas → muestra manual revisada dos veces y conciliación»). Hoy está en «Parcial»:
su evidencia es la revisión doble automatizada de `../`, y este kit queda listo para el área operativa de Sobusa.
Cuando el área entregue los archivos del paso 5, la mitigación queda hecha por personas que conocen la operación: dos
revisiones independientes y a ciegas, conciliación con motivo y kappa. La fila puede pasar entonces a «Cumple» con
`resumen_humano.md` y `conciliacion_humana.json` como evidencia. La revisión automatizada queda como complemento: la
kappa humano frente a automatizado dice cuánto se puede confiar en ella.

## 7. Archivos del kit

| Archivo | Qué es |
|---|---|
| `revisar.html` | La página de revisión: un solo archivo, sin internet ni librerías externas. Es generada: no se edita a mano. |
| `generar_kit.py` | La regenera desde `../muestra.json`, `../muestra/<id>.md` y `../protocolo.md`, con los tokens, la fuente y los iconos del tablero (`dash_app/`). Solo biblioteca estándar: `python -I generar_kit.py`. No lee ninguna etiqueta. |
| `plantilla/` | `pagina.html`, `estilos.css` y `app.js`, que `generar_kit.py` junta en `revisar.html`. |
| `conciliar_humanos.py` | La conciliación del paso 4. Reutiliza las funciones de `../conciliar.py` sin modificarlo. |

La prueba automática del kit está en `api_frecuencias/tests/unit/test_kit_revision_humana.py`.
