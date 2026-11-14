/* Kit de revisión humana · lógica de revisar.html (sin librerías y sin red).
   - El avance se guarda en localStorage con una clave por revisor; todo acceso va en try/catch: si el navegador no deja
     guardar (modo privado, archivo local bloqueado), la página sigue funcionando y pide descargar el archivo.
   - La descarga tiene el formato de etiquetas_A.json (id, etiqueta, confianza, razon) más revisor, fecha y
     origen = "humano". La página no trae etiquetas de nadie: la revisión es ciega. */
(function () {
  "use strict";

  var datos = JSON.parse(document.getElementById("datos-kit").textContent);
  var ALERTAS = datos.alertas;
  var TOTAL = ALERTAS.length;
  var POS = Object.create(null);
  ALERTAS.forEach(function (a, i) { POS[a.id] = i; });
  var ETIQUETAS = ["verdadera", "falsa", "indeterminada"];
  var CONFIANZAS = ["alta", "media", "baja"];
  var NOMBRES = { verdadera: "Verdadera", falsa: "Falsa", indeterminada: "Indeterminada", alta: "alta", media: "media", baja: "baja" };
  var PREFIJO = "sobusa-revision-humana/" + datos.kit + "/";
  var CAMPOS_ARCHIVO = ["id", "etiqueta", "confianza", "razon", "revisor", "fecha", "origen"];

  var estado = null;          // {version, kit, clave, revisor, creado, actual, etiquetas: {id: {...}}}
  var vista = "inicio";
  var filtro = "todas";
  var temporizador = null;
  var guardadoOk = true;
  var sinDescargar = false;
  var almacen = abrirAlmacen();
  var tarjetas = Object.create(null);

  function $(sel, raiz) { return (raiz || document).querySelector(sel); }
  function $$(sel, raiz) { return Array.prototype.slice.call((raiz || document).querySelectorAll(sel)); }

  $$(".tarjeta-alerta").forEach(function (t) { tarjetas[t.getAttribute("data-id")] = t; });

  // --- Almacenamiento local (opcional) ---------------------------------------------------------------------------
  function abrirAlmacen() {
    try {
      var ls = window.localStorage;
      var k = PREFIJO + "prueba";
      ls.setItem(k, "1");
      ls.removeItem(k);
      return ls;
    } catch (err) {
      return null;
    }
  }

  function leerGuardado(clave) {
    if (!almacen) { return null; }
    try {
      var crudo = almacen.getItem(PREFIJO + clave);
      if (!crudo) { return null; }
      var e = JSON.parse(crudo);
      if (!e || typeof e !== "object" || typeof e.revisor !== "string" || !e.etiquetas || typeof e.etiquetas !== "object") {
        return null;
      }
      return e;
    } catch (err) {
      return null;
    }
  }

  function guardar() {
    if (temporizador) { clearTimeout(temporizador); temporizador = null; }
    if (!estado) { return; }
    var ok = false;
    if (almacen) {
      try {
        almacen.setItem(PREFIJO + estado.clave, JSON.stringify(estado));
        ok = true;
      } catch (err) {
        ok = false;
      }
    }
    guardadoOk = ok;
    var p = $("#estado-guardado");
    if (ok) {
      p.textContent = "Guardado en este navegador a las " + horaCorta(new Date()) + ".";
      p.classList.remove("estado-guardado--mal");
    } else {
      p.textContent = "Este navegador no deja guardar el avance: descarga tus etiquetas antes de cerrar la página.";
      p.classList.add("estado-guardado--mal");
    }
  }

  function guardarLuego() {
    if (temporizador) { clearTimeout(temporizador); }
    temporizador = setTimeout(guardar, 400);
  }

  // --- Utilidades ------------------------------------------------------------------------------------------------
  function dos(n) { return (n < 10 ? "0" : "") + n; }

  function isoLocal(d) {
    var off = -d.getTimezoneOffset();
    var signo = off >= 0 ? "+" : "-";
    off = Math.abs(off);
    return d.getFullYear() + "-" + dos(d.getMonth() + 1) + "-" + dos(d.getDate()) + "T" + dos(d.getHours()) + ":" +
      dos(d.getMinutes()) + ":" + dos(d.getSeconds()) + signo + dos(Math.floor(off / 60)) + ":" + dos(off % 60);
  }

  function horaCorta(d) { return dos(d.getHours()) + ":" + dos(d.getMinutes()); }

  function normalizar(nombre) { return String(nombre || "").replace(/\s+/g, " ").trim(); }

  function claveDe(nombre) {
    var s = normalizar(nombre);
    if (s.normalize) { s = s.normalize("NFD").replace(/[̀-ͯ]/g, ""); }
    return s.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
  }

  function completa(e) { return !!(e && e.etiqueta && e.confianza); }

  function terminadas() {
    var n = 0;
    ALERTAS.forEach(function (a) { if (completa(estado.etiquetas[a.id])) { n += 1; } });
    return n;
  }

  function registro(id) {
    if (!estado.etiquetas[id]) { estado.etiquetas[id] = { etiqueta: null, confianza: null, razon: "", fecha: null }; }
    return estado.etiquetas[id];
  }

  function tocar(e) {
    e.fecha = isoLocal(new Date());
    sinDescargar = true;
  }

  function nombreArchivo() { return "etiquetas_humano_" + estado.clave + ".json"; }

  function mensaje(sel, texto, tipo) {
    var p = $(sel);
    p.textContent = texto;
    p.classList.remove("mensaje--bien", "mensaje--mal");
    if (tipo) { p.classList.add("mensaje--" + tipo); }
  }

  // --- Pantallas -------------------------------------------------------------------------------------------------
  function mostrar(nueva) {
    if (nueva !== "inicio" && !estado) { nueva = "inicio"; }
    if (vista === "revisar" && nueva !== "revisar") { guardar(); }
    vista = nueva;
    $$(".vista").forEach(function (v) { v.hidden = v.id !== "vista-" + nueva; });
    $$(".nav__boton").forEach(function (b) {
      if (b.getAttribute("data-vista") === nueva) { b.setAttribute("aria-current", "page"); } else { b.removeAttribute("aria-current"); }
    });
    if (nueva === "revisar") { pintarAlerta(); }
    if (nueva === "lista") { pintarLista(); }
    if (nueva === "descargar") { pintarDescarga(); }
    window.scrollTo(0, 0);
    ajustarCabecera();
  }

  function entrar(primera) {
    $("#nav").hidden = false;
    $("#barra-derecha").hidden = false;
    $("#chip-revisor").textContent = estado.revisor;
    actualizarAvance();
    guardar();
    mostrar(primera);
  }

  function salir() {
    guardar();
    estado = null;
    $("#nav").hidden = true;
    $("#barra-derecha").hidden = true;
    $("#nombre").value = "";
    document.title = "Revisión de alertas";
    mostrar("inicio");
  }

  function ajustarCabecera() {
    var b = $(".barra");
    if (b) { document.documentElement.style.setProperty("--alto-cabecera", b.offsetHeight + "px"); }
  }

  // --- Inicio ----------------------------------------------------------------------------------------------------
  $("#form-inicio").addEventListener("submit", function (ev) {
    ev.preventDefault();
    var nombre = normalizar($("#nombre").value);
    var clave = claveDe(nombre);
    var error = $("#error-nombre");
    if (nombre.length < 2 || clave.length < 2) {
      error.textContent = "Escribe tu nombre (al menos dos letras).";
      error.hidden = false;
      $("#nombre").focus();
      return;
    }
    error.hidden = true;
    var previo = leerGuardado(clave);
    if (previo && previo.kit === datos.kit) {
      estado = previo;
      estado.clave = clave;
      if (typeof estado.actual !== "number" || estado.actual < 0 || estado.actual >= TOTAL) { estado.actual = 0; }
      entrar("revisar");
    } else {
      estado = { version: 1, kit: datos.kit, clave: clave, revisor: nombre, creado: isoLocal(new Date()), actual: 0, etiquetas: {} };
      entrar("protocolo");
    }
  });

  $$(".nav__boton").forEach(function (b) {
    b.addEventListener("click", function () { mostrar(b.getAttribute("data-vista")); });
  });
  $("#empezar-revision").addEventListener("click", function () { mostrar("revisar"); });
  $("#salir").addEventListener("click", salir);

  // --- Revisión de una alerta ------------------------------------------------------------------------------------
  function pintarSeleccion() {
    var a = ALERTAS[estado.actual];
    var e = estado.etiquetas[a.id] || {};
    $$("#vista-revisar .opcion").forEach(function (b) {
      var campo = b.getAttribute("data-campo");
      b.setAttribute("aria-pressed", String(e[campo] === b.getAttribute("data-valor")));
    });
    var p = $("#estado-alerta");
    if (completa(e)) {
      p.textContent = a.id + ": " + NOMBRES[e.etiqueta] + ", confianza " + NOMBRES[e.confianza] + ".";
    } else if (e.etiqueta) {
      p.textContent = a.id + ": falta la confianza.";
    } else {
      p.textContent = a.id + ": sin etiqueta todavía.";
    }
  }

  function pintarAlerta() {
    var i = estado.actual;
    var a = ALERTAS[i];
    Object.keys(tarjetas).forEach(function (id) { tarjetas[id].hidden = id !== a.id; });
    $("#panel-id").textContent = a.id;
    $("#panel-pos").textContent = "Alerta " + (i + 1) + " de " + TOTAL + " · " + a.codigo;
    $("#def-codigo").textContent = a.codigo;
    $$(".def").forEach(function (d) { d.hidden = d.getAttribute("data-codigo") !== a.codigo; });
    var e = estado.etiquetas[a.id] || {};
    $("#razon").value = e.razon || "";
    $("#anterior").disabled = i === 0;
    $("#siguiente").disabled = i === TOTAL - 1;
    pintarSeleccion();
  }

  function ir(i) {
    if (i < 0 || i >= TOTAL) { return; }
    guardar();
    estado.actual = i;
    guardar();
    pintarAlerta();
    window.scrollTo(0, 0);
    var t = tarjetas[ALERTAS[i].id];
    var h = t && t.querySelector(".alerta__titulo");
    if (h) { h.focus({ preventScroll: true }); }
  }

  function siguientePendiente() {
    for (var k = 1; k <= TOTAL; k += 1) {
      var j = (estado.actual + k) % TOTAL;
      if (!completa(estado.etiquetas[ALERTAS[j].id])) { ir(j); return; }
    }
    $("#estado-alerta").textContent = "No queda ninguna alerta sin terminar.";
  }

  function elegir(campo, valor) {
    var a = ALERTAS[estado.actual];
    var e = registro(a.id);
    e[campo] = valor;
    tocar(e);
    guardar();
    pintarSeleccion();
    actualizarAvance();
  }

  $$("#vista-revisar .opcion").forEach(function (b) {
    b.addEventListener("click", function () { elegir(b.getAttribute("data-campo"), b.getAttribute("data-valor")); });
  });

  $("#razon").addEventListener("input", function () {
    var e = registro(ALERTAS[estado.actual].id);
    e.razon = this.value;
    tocar(e);
    guardarLuego();
  });
  $("#razon").addEventListener("keydown", function (ev) {
    if (ev.key === "Enter" && (ev.ctrlKey || ev.metaKey)) { ev.preventDefault(); ir(estado.actual + 1); }
    if (ev.key === "Escape") { this.blur(); }
  });

  $("#anterior").addEventListener("click", function () { ir(estado.actual - 1); });
  $("#siguiente").addEventListener("click", function () { ir(estado.actual + 1); });
  $("#pendiente").addEventListener("click", siguientePendiente);
  $$(".ir-decision").forEach(function (b) {
    b.addEventListener("click", function () { $("#panel").scrollIntoView({ block: "start" }); });
  });

  var ATAJOS = { v: ["etiqueta", "verdadera"], f: ["etiqueta", "falsa"], i: ["etiqueta", "indeterminada"],
                 a: ["confianza", "alta"], m: ["confianza", "media"], b: ["confianza", "baja"] };

  document.addEventListener("keydown", function (ev) {
    if (vista !== "revisar" || !estado || ev.ctrlKey || ev.metaKey || ev.altKey) { return; }
    var t = ev.target;
    if (t && (t.tagName === "TEXTAREA" || t.tagName === "INPUT" || t.isContentEditable)) { return; }
    var k = String(ev.key || "");
    var atajo = ATAJOS[k.toLowerCase()];
    if (atajo) { ev.preventDefault(); elegir(atajo[0], atajo[1]); return; }
    if (k === "ArrowRight") { ev.preventDefault(); ir(estado.actual + 1); }
    else if (k === "ArrowLeft") { ev.preventDefault(); ir(estado.actual - 1); }
    else if (k.toLowerCase() === "j") { ev.preventDefault(); $("#razon").focus(); }
  });

  function actualizarAvance() {
    var n = terminadas();
    $("#avance-n").textContent = String(n);
    $("#avance-relleno").style.setProperty("--p", (100 * n / TOTAL).toFixed(1) + "%");
    document.title = n + "/" + TOTAL + " · Revisión de alertas";
    $("#aviso-terminado").hidden = n !== TOTAL;
  }

  // --- Lista -----------------------------------------------------------------------------------------------------
  function celda(tr, texto, clase) {
    var td = document.createElement("td");
    td.textContent = texto;
    if (clase) { td.className = clase; }
    tr.appendChild(td);
  }

  function pintarLista() {
    var cuerpo = $("#cuerpo-lista");
    cuerpo.textContent = "";
    var n = 0;
    ALERTAS.forEach(function (a, i) {
      var e = estado.etiquetas[a.id];
      var ok = completa(e);
      if ((filtro === "pendientes" && ok) || (filtro === "terminadas" && !ok)) { return; }
      n += 1;
      var tr = document.createElement("tr");
      celda(tr, String(i + 1), "num");
      var td = document.createElement("td");
      var b = document.createElement("button");
      b.type = "button";
      b.className = "boton boton--fantasma boton--pequeno";
      b.textContent = a.id;
      b.setAttribute("aria-label", "Ir a " + a.id);
      b.addEventListener("click", function () { estado.actual = i; mostrar("revisar"); });
      td.appendChild(b);
      tr.appendChild(td);
      celda(tr, a.codigo + " " + a.nombre);
      celda(tr, a.ruta);
      celda(tr, a.fecha);
      celda(tr, a.ventana);
      celda(tr, e && e.etiqueta ? NOMBRES[e.etiqueta] : "—");
      celda(tr, e && e.confianza ? NOMBRES[e.confianza] : "—");
      celda(tr, e && e.razon && e.razon.trim() ? "sí" : "—");
      cuerpo.appendChild(tr);
    });
    $("#lista-vacia").hidden = n !== 0;
  }

  $$(".segmentado--filtro .opcion-filtro").forEach(function (b) {
    b.addEventListener("click", function () {
      filtro = b.getAttribute("data-filtro");
      $$(".segmentado--filtro .opcion-filtro").forEach(function (o) { o.setAttribute("aria-pressed", String(o === b)); });
      pintarLista();
    });
  });

  // --- Descarga, carga y borrado ---------------------------------------------------------------------------------
  function fila(objeto) {
    return "{" + CAMPOS_ARCHIVO.map(function (k) { return JSON.stringify(k) + ": " + JSON.stringify(objeto[k]); }).join(", ") + "}";
  }

  function exportar() {
    var filas = [];
    ALERTAS.forEach(function (a) {
      var e = estado.etiquetas[a.id];
      if (!e || !e.etiqueta) { return; }
      filas.push(fila({
        id: a.id, etiqueta: e.etiqueta, confianza: e.confianza || null, razon: normalizar(e.razon),
        revisor: estado.revisor, fecha: e.fecha || isoLocal(new Date()), origen: "humano"
      }));
    });
    return filas.length ? "[\n  " + filas.join(",\n  ") + "\n]\n" : "[]\n";
  }

  function pintarDescarga() {
    var n = terminadas();
    var pendientes = ALERTAS.filter(function (a) { return !completa(estado.etiquetas[a.id]); });
    $("#descarga-resumen").textContent = n === TOTAL
      ? "Terminaste las " + TOTAL + " alertas. Descarga tu archivo y envíalo a quien modera la conciliación."
      : "Llevas " + n + " de " + TOTAL + " alertas terminadas (etiqueta y confianza).";
    $("#descarga-nombre").textContent = nombreArchivo();
    var caja = $("#lista-pendientes");
    caja.textContent = "";
    pendientes.slice(0, 12).forEach(function (a) {
      var b = document.createElement("button");
      b.type = "button";
      b.className = "boton boton--secundario boton--pequeno";
      b.textContent = a.id;
      b.addEventListener("click", function () { estado.actual = POS[a.id]; mostrar("revisar"); });
      caja.appendChild(b);
    });
    if (pendientes.length > 12) {
      var resto = document.createElement("span");
      resto.className = "nota";
      resto.textContent = "y " + (pendientes.length - 12) + " más (en «Lista», filtro «Sin terminar»).";
      caja.appendChild(resto);
    }
    $("#aviso-pendientes").hidden = pendientes.length === 0;
    $("#n-pendientes").textContent = String(pendientes.length);
    $("#vista-json").value = exportar();
  }

  $("#descargar").addEventListener("click", function () {
    guardar();
    var texto = exportar();
    try {
      var blob = new Blob([texto], { type: "application/json;charset=utf-8" });
      var url = URL.createObjectURL(blob);
      var enlace = document.createElement("a");
      enlace.href = url;
      enlace.download = nombreArchivo();
      document.body.appendChild(enlace);
      enlace.click();
      enlace.remove();
      setTimeout(function () { URL.revokeObjectURL(url); }, 4000);
      sinDescargar = false;
      mensaje("#mensaje-descarga", "Listo: se descargó " + nombreArchivo() + ".", "bien");
    } catch (err) {
      $("#detalle-json").open = true;
      mensaje("#mensaje-descarga", "No se pudo descargar. Copia el contenido de abajo en un archivo llamado " +
        nombreArchivo() + ".", "mal");
    }
  });

  $("#copiar").addEventListener("click", function () {
    var caja = $("#vista-json");
    caja.value = exportar();
    var hecho = function () { mensaje("#mensaje-descarga", "Copiado al portapapeles.", "bien"); };
    var aMano = function () {
      try {
        caja.focus();
        caja.select();
        if (document.execCommand("copy")) { hecho(); return; }
      } catch (err) { /* sigue abajo */ }
      mensaje("#mensaje-descarga", "Selecciona el texto y cópialo a mano (Ctrl+C).", "mal");
    };
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(caja.value).then(hecho, aMano);
        return;
      }
    } catch (err) { /* sigue abajo */ }
    aMano();
  });

  function importar(texto) {
    var lista = JSON.parse(texto);
    if (!Array.isArray(lista)) { throw new Error("El archivo no tiene el formato de las etiquetas (una lista)."); }
    var nuevas = Object.create(null);
    lista.forEach(function (f) {
      if (!f || typeof f !== "object" || typeof f.id !== "string" || POS[f.id] === undefined) {
        throw new Error("El archivo trae una alerta que no es de esta muestra.");
      }
      if (f.origen !== "humano") { throw new Error("Solo se cargan archivos descargados de esta página (origen «humano»)."); }
      if (claveDe(f.revisor) !== estado.clave) {
        throw new Error("Ese archivo es de otro revisor. La revisión es individual: carga solo el tuyo.");
      }
      if (ETIQUETAS.indexOf(f.etiqueta) < 0) { throw new Error("La etiqueta de " + f.id + " no es del protocolo."); }
      if (f.confianza !== null && f.confianza !== undefined && CONFIANZAS.indexOf(f.confianza) < 0) {
        throw new Error("La confianza de " + f.id + " no es alta, media ni baja.");
      }
      nuevas[f.id] = { etiqueta: f.etiqueta, confianza: f.confianza || null,
                       razon: typeof f.razon === "string" ? f.razon : "", fecha: typeof f.fecha === "string" ? f.fecha : null };
    });
    var ids = Object.keys(nuevas);
    ids.forEach(function (id) { estado.etiquetas[id] = nuevas[id]; });
    guardar();
    actualizarAvance();
    return ids.length;
  }

  $("#cargar").addEventListener("change", function () {
    var entrada = this;
    var archivo = entrada.files && entrada.files[0];
    if (!archivo) { return; }
    var lector = new FileReader();
    lector.onload = function () {
      try {
        var n = importar(String(lector.result));
        pintarDescarga();
        mensaje("#mensaje-carga", "Se cargaron " + n + " etiquetas.", "bien");
      } catch (err) {
        mensaje("#mensaje-carga", "No se cargó: " + err.message, "mal");
      }
    };
    lector.onerror = function () { mensaje("#mensaje-carga", "No se pudo leer el archivo.", "mal"); };
    lector.readAsText(archivo, "utf-8");
    entrada.value = "";
  });

  $("#borrar").addEventListener("click", function () {
    if (!window.confirm("¿Borrar tus etiquetas de este navegador? Si no las descargaste, se pierden.")) { return; }
    try { if (almacen) { almacen.removeItem(PREFIJO + estado.clave); } } catch (err) { /* no hay nada que borrar */ }
    estado = null;
    sinDescargar = false;
    $("#nav").hidden = true;
    $("#barra-derecha").hidden = true;
    $("#nombre").value = "";
    document.title = "Revisión de alertas";
    mostrar("inicio");
  });

  window.addEventListener("beforeunload", function (ev) {
    if (estado && !guardadoOk && sinDescargar) { ev.preventDefault(); ev.returnValue = ""; }
  });
  window.addEventListener("resize", ajustarCabecera);

  // --- Arranque --------------------------------------------------------------------------------------------------
  $("#aviso-almacen").hidden = !!almacen;
  ajustarCabecera();
})();
