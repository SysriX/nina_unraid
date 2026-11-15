/* NINA – Auswahl für Symbole: Material Design Icons (mdi:…, für Home Assistant) und Zeichen/Emoji (Listen in NINA) */
"use strict";

let MDI = null;
async function mdiLaden() {
  if (!MDI) {
    const r = await fetch("/static/mdi.json", { credentials: "same-origin" });
    const j = await r.json();
    MDI = { v: j.v, k: j.k, i: j.i.map(([n, d, a, t]) => ({ n, d, a, t, s: (n + " " + a + " " + t.map(x => j.k[x]).join(" ")).toLowerCase() })) };
    MDI.nach = Object.fromEntries(MDI.i.map(x => [x.n, x]));
  }
  return MDI;
}

/** SVG eines mdi-Icons (wenn die Liste schon geladen ist), sonst leer. */
function mdiSvg(name, groesse = 22) {
  const x = MDI && MDI.nach[String(name || "").replace(/^mdi:/, "")];
  if (!x) return h("span", { class: "mdi-leer", style: { width: groesse + "px", height: groesse + "px" } });
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24"); svg.setAttribute("width", groesse); svg.setAttribute("height", groesse); svg.setAttribute("class", "mdi");
  const p = document.createElementNS("http://www.w3.org/2000/svg", "path"); p.setAttribute("d", x.d); svg.append(p);
  return svg;
}

// Deutsche Suchbegriffe → englische Namensteile der Icons
const MDI_DE = {
  drucker: "printer", rechner: "desktop computer monitor", computer: "desktop computer laptop", pc: "desktop-tower desktop-classic",
  server: "server", netzwerk: "network lan ethernet", netz: "network lan", switch: "switch", router: "router", firewall: "firewall shield wall",
  wlan: "wifi access-point", accesspoint: "access-point", zugangspunkt: "access-point", kamera: "camera cctv webcam", überwachung: "cctv cctv",
  telefon: "phone deskphone", handy: "cellphone", smartphone: "cellphone", tablet: "tablet", fernseher: "television", tv: "television",
  medien: "multimedia play television", lautsprecher: "speaker", musik: "music", licht: "lightbulb", lampe: "lamp lightbulb",
  steckdose: "power-socket", stecker: "power-plug", strom: "flash lightning power", akku: "battery", batterie: "battery",
  speicher: "harddisk nas database", festplatte: "harddisk", laufwerk: "harddisk", datenbank: "database", nas: "nas",
  konsole: "gamepad controller console", spiel: "gamepad", uhr: "clock", haus: "home house", gebäude: "office-building",
  heizung: "radiator thermostat heat", thermostat: "thermostat", temperatur: "thermometer", sensor: "motion-sensor sensor",
  bewegung: "motion", tür: "door", fenster: "window", schloss: "lock", schlüssel: "key", virtuell: "server-network cloud vm",
  cloud: "cloud", wolke: "cloud", laptop: "laptop", notebook: "laptop", maus: "mouse", tastatur: "keyboard", bildschirm: "monitor",
  monitor: "monitor", scanner: "scanner", usb: "usb", kabel: "cable", antenne: "antenna", satellit: "satellite", auto: "car",
  waschmaschine: "washing-machine", trockner: "tumble-dryer", kühlschrank: "fridge", staubsauger: "robot-vacuum", roboter: "robot",
  smarthome: "home-automation", unbekannt: "help", fragezeichen: "help", sonstiges: "devices dots", geräte: "devices", gerät: "devices",
  hypervisor: "server-network cube", container: "docker cube", docker: "docker", sicherheit: "shield security", warnung: "alert",
  internet: "web earth", welt: "earth web", signal: "signal", benutzer: "account", person: "account", werkzeug: "tools wrench",
  einstellungen: "cog", zahnrad: "cog", uhrzeit: "clock", kalender: "calendar", wetter: "weather", sonne: "sunny", mond: "moon",
  garten: "flower tree", pflanze: "sprout flower", wasser: "water", tropfen: "water", feuer: "fire", rauch: "smoke",
  klingel: "doorbell bell", glocke: "bell", mikrofon: "microphone", kopfhörer: "headphones", projektor: "projector", beamer: "projector",
  raspberry: "raspberry-pi", chip: "chip memory", prozessor: "cpu chip", grafikkarte: "expansion-card", arbeitsspeicher: "memory",
  ups: "battery-charging power", usv: "battery-charging power-plug", rack: "server", schrank: "server",
};
// Kategorien auf Deutsch (nur die wichtigsten, sonst englisch)
const MDI_KAT_DE = { "Home Automation": "Smart Home", "Device / Tech": "Geräte / Technik", "Hardware / Tools": "Hardware / Werkzeug",
  "Account / User": "Benutzer", "Alert / Error": "Warnung / Fehler", "Audio": "Audio", "Cloud": "Cloud", "Database": "Datenbank",
  "Gaming / RPG": "Spiele", "Lock": "Schloss", "Notification": "Benachrichtigung", "Photography": "Foto", "Settings": "Einstellungen",
  "Battery": "Akku", "Weather": "Wetter", "Date / Time": "Datum / Zeit", "Places": "Orte", "Video / Movie": "Video / Film",
  "Printer": "Drucker", "Cellphone / Phone": "Telefon", "Wifi": "WLAN", "Network": "Netzwerk", "Power": "Strom" };

function mdiSuche(text, kategorie) {
  const woerter = text.toLowerCase().split(/\s+/).filter(Boolean);
  const begriffe = woerter.map(w => [w, ...((MDI_DE[w] || "").split(" ").filter(Boolean))]);
  return MDI.i.filter(x => (kategorie === "" || x.t.includes(+kategorie)) && begriffe.every(b => b.some(t => x.s.includes(t))));
}

/** Dialog: mdi-Icon wählen. Gibt "mdi:name" zurück (oder null). */
async function mdiWaehlen(aktuell = "") {
  await mdiLaden();
  let gewaehlt = String(aktuell || "").replace(/^mdi:/, "");
  const suche = eingabe("", gewaehlt, { placeholder: "Suchen – englisch oder deutsch, z. B. drucker, server, wlan" });
  const kat = h("select", {}, h("option", { value: "" }, "Alle Kategorien"),
    MDI.k.map((k, i) => [i, MDI_KAT_DE[k] || k]).sort((a, b) => a[1].localeCompare(b[1], "de")).map(([i, t]) => h("option", { value: i }, t)));
  const raster = h("div", { class: "icon-raster" });
  const info = h("div", { class: "leise klein-t" });
  const anzeige = h("div", { class: "icon-gewaehlt" });
  const zeigeGewaehlt = () => leeren(anzeige, gewaehlt ? [mdiSvg(gewaehlt, 30), h("b", { class: "mono" }, "mdi:" + gewaehlt)] : h("span", { class: "leise" }, "noch nichts gewählt"));
  const zeichne = () => {
    const treffer = suche.value.trim() || kat.value !== "" ? mdiSuche(suche.value.trim(), kat.value) : MDI.i;
    const max = 360;
    leeren(raster, treffer.slice(0, max).map(x => h("button", { type: "button", class: "icon-kachel" + (x.n === gewaehlt ? " an" : ""), title: x.n + (x.a ? "\n" + x.a : ""),
      onclick: e => { gewaehlt = x.n; raster.querySelectorAll(".an").forEach(b => b.classList.remove("an")); e.currentTarget.classList.add("an"); zeigeGewaehlt(); },
      ondblclick: () => { gewaehlt = x.n; okKlick(); } },
      mdiSvg(x.n, 26), h("span", {}, x.n))));
    info.textContent = treffer.length > max ? `${treffer.length} Treffer – die ersten ${max} werden gezeigt, Suche verfeinern` : `${treffer.length} Treffer`;
  };
  let t; suche.addEventListener("input", () => { clearTimeout(t); t = setTimeout(zeichne, 150); });
  kat.addEventListener("change", zeichne);
  zeigeGewaehlt(); zeichne();
  const r = await dialog("HA-Symbol wählen", h("div", {},
    h("div", { class: "leiste" }, suche, kat), info, raster, anzeige,
    h("p", { class: "leise klein-t" }, `Material Design Icons ${MDI.v} – wie in Home Assistant. Doppelklick übernimmt sofort.`)),
    [["Abbrechen", null], ["Leeren", ""], ["Übernehmen", () => gewaehlt || false, "p"]], true);
  return r === null ? null : r === "" ? "" : "mdi:" + r;
}

// Zeichen / Emoji für die Listen in NINA: [Zeichen, Suchbegriffe]
const ZEICHEN = [
  ["Geräte", [["🖥", "desktop pc rechner computer bildschirm"], ["💻", "laptop notebook"], ["🖨", "drucker printer"], ["📱", "handy smartphone telefon"],
    ["☎", "telefon festnetz"], ["📞", "telefon hörer"], ["📠", "fax"], ["⌨", "tastatur keyboard"], ["🖱", "maus"], ["🗄", "server schrank rack"],
    ["🗃", "nas speicher kartei"], ["💽", "festplatte disk"], ["💾", "diskette speichern"], ["💿", "cd dvd"], ["📺", "tv fernseher medien"],
    ["📻", "radio"], ["📷", "kamera foto"], ["📹", "videokamera überwachung"], ["🎥", "kamera film"], ["🎮", "konsole spiel gamepad"],
    ["🕹", "joystick spiel"], ["🔊", "lautsprecher audio"], ["🎧", "kopfhörer"], ["🎙", "mikrofon"], ["⌚", "uhr smartwatch"],
    ["🔋", "akku batterie usv"], ["🔌", "stecker steckdose strom"], ["💡", "licht lampe iot smart home"], ["🌡", "thermometer temperatur sensor"],
    ["📡", "antenne satellit funk"], ["🛰", "satellit"], ["🤖", "roboter"], ["🧹", "staubsauger"], ["🚪", "tür"], ["🔒", "schloss sicherheit"],
    ["🔑", "schlüssel"], ["🛡", "firewall schutz schild router"], ["🧱", "firewall mauer"], ["☁", "cloud wolke"], ["🌐", "internet netz welt"],
    ["🔗", "verbindung link"], ["📶", "wlan signal funk"], ["⚙", "zahnrad einstellungen"], ["🔧", "werkzeug"], ["🧰", "werkzeugkasten"],
    ["🏠", "haus home"], ["🏢", "büro gebäude"], ["🚗", "auto"], ["🧩", "modul erweiterung"], ["📦", "paket container"], ["🐳", "docker container"]]],
  ["Zeichen", [["⇄", "switch netzwerk pfeile"], ["⇆", "pfeile"], ["↔", "pfeil verbindung"], ["◫", "vm virtuell fenster"], ["▭", "tablet rechteck"],
    ["▣", "quadrat"], ["◇", "raute sonstiges"], ["◆", "raute"], ["●", "punkt kreis"], ["○", "kreis"], ["■", "quadrat"], ["□", "quadrat leer"],
    ["▲", "dreieck"], ["△", "dreieck"], ["★", "stern"], ["☆", "stern leer"], ["✚", "plus kreuz"], ["⚡", "blitz strom"], ["♻", "recycling"],
    ["⧉", "fenster hypervisor kopie"], ["⊞", "raster"], ["⌂", "haus"], ["⏻", "power ein aus"], ["⚠", "warnung"], ["?", "unbekannt fragezeichen"],
    ["✓", "haken ok"], ["✗", "kreuz fehler"], ["∞", "unendlich"], ["#", "raute nummer"], ["@", "at"]]],
];

/** Dialog: Zeichen/Emoji wählen. */
async function zeichenWaehlen(aktuell = "") {
  let gewaehlt = aktuell || "";
  const suche = eingabe("", "", { placeholder: "Suchen, z. B. drucker, server, wlan" });
  const eigen = eingabe("", gewaehlt, { placeholder: "oder eigenes Zeichen eintippen", style: { width: "220px" }, oninput: e => { gewaehlt = e.target.value; } });
  const raster = h("div");
  const zeichne = () => {
    const q = suche.value.trim().toLowerCase();
    leeren(raster, ZEICHEN.map(([gruppe, liste]) => {
      const t = liste.filter(([z, s]) => !q || s.includes(q) || z === q);
      return t.length ? [h("h4", {}, gruppe), h("div", { class: "icon-raster zeichen" }, t.map(([z, s]) => h("button", {
        type: "button", class: "icon-kachel" + (z === gewaehlt ? " an" : ""), title: s,
        onclick: e => { gewaehlt = z; eigen.value = z; raster.querySelectorAll(".an").forEach(b => b.classList.remove("an")); e.currentTarget.classList.add("an"); },
        ondblclick: () => { gewaehlt = z; okKlick(); } }, h("span", { class: "zeichen-gross" }, z), h("span", {}, s.split(" ")[0]))))] : [];
    }).flat());
  };
  suche.addEventListener("input", zeichne);
  zeichne();
  const r = await dialog("Symbol wählen", h("div", {}, h("div", { class: "leiste" }, suche, eigen), raster,
    h("p", { class: "leise klein-t" }, "Wird in den Listen von NINA vor dem Namen gezeigt. Doppelklick übernimmt sofort.")),
    [["Abbrechen", null], ["Übernehmen", () => gewaehlt, "p"]], true);
  return r === null ? null : r;
}

/** Eingabefeld mit Vorschau + Auswahl-Knopf. art: "mdi" oder "zeichen" */
function symbolFeld(name, wert, art) {
  const i = eingabe(name, wert || "", { placeholder: art === "mdi" ? "mdi:server" : "z. B. 🖥", style: { flex: "1" } });
  const vorschau = h("span", { class: "symbol-vorschau" });
  const zeige = () => leeren(vorschau, art === "mdi" ? mdiSvg(i.value, 22) : i.value || "");
  i.addEventListener("input", zeige);
  if (art === "mdi") mdiLaden().then(zeige).catch(() => {}); else zeige();
  const knopf = h("button", { type: "button", onclick: async () => {
    const r = art === "mdi" ? await mdiWaehlen(i.value) : await zeichenWaehlen(i.value);
    if (r !== null) { i.value = r; zeige(); }
  } }, "Auswählen …");
  return h("div", { style: { display: "flex", gap: "6px", alignItems: "center" } }, vorschau, i, knopf);
}

/** „Übernehmen“ des obersten (zuletzt geöffneten) Dialogs auslösen – Auswahl-Dialoge liegen über dem Typ-Dialog. */
function okKlick() { const hg = [...document.querySelectorAll(".dialog-hg")].pop(); if (hg) hg.querySelector(".knoepfe button.p").click(); }
