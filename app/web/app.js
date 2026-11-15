/* NINA – Oberfläche: Kern, Navigation, Anmeldung, Einrichtung */
"use strict";

// ------------------------------------------------------------------ Hilfen
const $ = (s, r = document) => r.querySelector(s);
const ANSICHT = {};
let ICH = null, META = { typen: [], zusatzfelder: [], name: "NINA" };

function h(tag, attrs, ...kinder) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === undefined || v === null || v === false) continue;
    if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v);
    else if (k === "class") el.className = v;
    else if (k === "style" && typeof v === "object") Object.assign(el.style, v);
    else if (k === "value") el.value = v;
    else if (k === "checked" || k === "disabled" || k === "selected" || k === "multiple") el[k] = !!v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const k of kinder.flat(Infinity)) {
    if (k === null || k === undefined || k === false) continue;
    el.append(k instanceof Node ? k : document.createTextNode(String(k)));
  }
  return el;
}
const leeren = (el, ...neu) => { el.replaceChildren(...neu.flat().filter(x => x !== null && x !== undefined && x !== false)); return el; };

async function api(methode, pfad, daten, extra = {}) {
  const opt = { method: methode, headers: { "X-NI": "1", ...(extra.headers || {}) }, credentials: "same-origin" };
  if (daten !== undefined) { opt.body = JSON.stringify(daten); opt.headers["Content-Type"] = "application/json"; }
  const r = await fetch(pfad, opt);
  if (extra.roh) { if (!r.ok) throw new Error(`Fehler ${r.status}`); return r; }
  let d = null;
  try { d = await r.json(); } catch { d = null; }
  if (r.status === 401 && !extra.still) { ICH = null; zeigeAnmeldung(); throw new Error("Bitte anmelden"); }
  if (!r.ok) {
    let t = d && d.detail;
    if (Array.isArray(t)) t = t.map(x => `${(x.loc || []).slice(1).join(".")}: ${x.msg}`).join("\n");
    throw new Error(t || `Fehler ${r.status}`);
  }
  return d;
}

let hinweisZeit;
function hinweis(text, fehler = false) {
  const el = $("#hinweis");
  el.textContent = text; el.className = fehler ? "bad" : ""; el.style.display = "block";
  clearTimeout(hinweisZeit);
  hinweisZeit = setTimeout(() => (el.style.display = "none"), fehler ? 9000 : 3500);
}
async function versuch(fn, ok) {
  try { const r = await fn(); if (ok) hinweis(typeof ok === "function" ? ok(r) : ok); return r; }
  catch (e) { hinweis(e.message, true); throw e; }
}

function dialog(titel, inhalt, knoepfe = [["Schließen", null]], breit = false) {
  return new Promise(res => {
    const hg = h("div", { class: "dialog-hg" });
    const zu = v => { hg.remove(); res(v); };
    hg.addEventListener("mousedown", e => { if (e.target === hg) zu(null); });
    const kn = knoepfe.map(([t, wert, art]) => h("button", { class: art || "", onclick: async () => {
      if (typeof wert === "function") { try { const r = await wert(); if (r !== false) zu(r ?? true); } catch (e) { hinweis(e.message, true); } }
      else zu(wert);
    } }, t));
    hg.append(h("div", { class: "dialog", style: breit ? { width: "min(980px,100%)" } : null }, h("h3", {}, titel), inhalt, h("div", { class: "knoepfe" }, kn)));
    document.body.append(hg);
    const f = hg.querySelector("input:not([type=checkbox]),select,textarea"); if (f) f.focus();
  });
}
const bestaetigen = (text, knopf = "Ja", gefahr = true) =>
  dialog("Bitte bestätigen", h("p", {}, text), [["Abbrechen", false], [knopf, true, gefahr ? "p gefahr" : "p"]]);

function feld(titel, eingabe, hilfe) {
  return h("label", { class: "feld" }, h("span", {}, titel), eingabe, hilfe ? h("small", {}, hilfe) : null);
}
function haken(titel, an, hilfe, name) {
  const i = h("input", { type: "checkbox", checked: an, name });
  return { el: h("label", { class: "haken" }, i, h("span", {}, titel, hilfe ? h("small", {}, hilfe) : null)), i };
}
function eingabe(name, wert = "", attrs = {}) { return h("input", { name, value: wert ?? "", ...attrs }); }
function auswahl(name, optionen, wert, attrs = {}) {
  return h("select", { name, ...attrs }, optionen.map(o => { const [v, t] = Array.isArray(o) ? o : [o, o]; return h("option", { value: v, selected: String(v) === String(wert ?? "") }, t); }));
}
function lesenForm(el) {
  const d = {};
  el.querySelectorAll("[name]").forEach(i => {
    if (i.type === "checkbox") d[i.name] = i.checked;
    else if (i.type === "radio") { if (i.checked) d[i.name] = i.value; }
    else d[i.name] = i.value;
  });
  return d;
}

/** Tabelle: spalten = [{t, w: zeile => wert|Node, z: rechtsbündig, sort: zeile => Sortierwert}] */
function tabelle(spalten, zeilen, { klick, leer = "Keine Einträge", an, sortierbar, klebend } = {}) {
  if (!zeilen || !zeilen.length) return h("div", { class: "leer" }, leer);
  const wrap = h("div", { class: "tab-wrap" + (klebend ? " klebend" : "") });   // klebend: letzte Spalte (Knöpfe) bleibt rechts sichtbar
  let sortSp = null, auf = true;
  const zeichnen = () => {
    let z = zeilen.slice();
    if (sortSp) {
      const f = sortSp.sort || (x => { const v = sortSp.w(x); return v instanceof Node ? v.textContent : v; });
      z.sort((a, b) => { const x = f(a), y = f(b); const r = typeof x === "number" && typeof y === "number" ? x - y : String(x ?? "").localeCompare(String(y ?? ""), "de", { numeric: true }); return auf ? r : -r; });
    }
    leeren(wrap, h("table", {},
      h("thead", {}, h("tr", {}, spalten.map(s => h("th", { class: s.z ? "z" : "", style: sortierbar ? { cursor: "pointer" } : null,
        onclick: sortierbar ? () => { if (sortSp === s) auf = !auf; else { sortSp = s; auf = true; } zeichnen(); } : null },
        s.t, sortSp === s ? (auf ? " ▴" : " ▾") : "")))),
      h("tbody", {}, z.map(r => h("tr", { class: (klick ? "klick " : "") + (an && an(r) ? "an" : ""), onclick: klick ? e => { if (!e.target.closest("button,a,input,select")) klick(r); } : null },
        spalten.map(s => { const v = s.w(r); return h("td", { class: s.z ? "z" : "" }, v === null || v === undefined ? "" : v); }))))));
  };
  zeichnen();
  return wrap;
}
const marke = (t, art = "") => h("span", { class: "marke " + art }, t);
const punkt = art => h("span", { class: "punkt " + art });
const datum = s => { if (!s) return ""; const d = new Date(s); return isNaN(d) ? s : d.toLocaleString("de-DE", { dateStyle: "short", timeStyle: "short" }); };
function vorZeit(s) {
  if (!s) return "nie";
  const d = (Date.now() - new Date(s).getTime()) / 1000;
  if (d < 60) return "gerade eben";
  if (d < 3600) return `vor ${Math.round(d / 60)} min`;
  if (d < 86400) return `vor ${Math.round(d / 3600)} h`;
  if (d < 86400 * 30) return `vor ${Math.round(d / 86400)} Tagen`;
  return datum(s);
}
const darf = r => ICH && ({ leser: 1, operator: 2, admin: 3 }[ICH.rolle] || 0) >= ({ leser: 1, operator: 2, admin: 3 }[r]);
function zufallsPasswort(n = 16) {
  const abc = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789!$%&*+-?";
  const a = new Uint32Array(n); crypto.getRandomValues(a);
  return Array.from(a, x => abc[x % abc.length]).join("");
}
function pwFeld(name, titel = "Passwort", hilfe) {
  const i = eingabe(name, "", { type: "text", autocomplete: "new-password" });
  return feld(titel, h("div", { style: { display: "flex", gap: "6px" } }, i,
    h("button", { type: "button", onclick: () => { i.value = zufallsPasswort(); } }, "Erzeugen")), hilfe);
}
function tabs(namen, aktiv, wechsel) {
  return h("div", { class: "tabs" }, namen.map(([k, t]) => h("button", { class: k === aktiv ? "an" : "", onclick: () => wechsel(k) }, t)));
}
function themeWahl(klasse = "") {
  return h("select", { class: "theme-wahl " + klasse, title: "Aussehen", onchange: e => themeSetzen(e.target.value) },
    window.NINA_THEMES.map(([k, t]) => h("option", { value: k, selected: k === themeAktuell() }, t)));
}
function kopieren(text) {
  if (navigator.clipboard && window.isSecureContext) return navigator.clipboard.writeText(text).then(() => hinweis("Kopiert"));
  const t = h("textarea", { style: { position: "fixed", opacity: 0 } }, text); document.body.append(t); t.select();
  try { document.execCommand("copy"); hinweis("Kopiert"); } finally { t.remove(); }
}

// ------------------------------------------------------------------ Navigation / Rahmen
const NAVI = [
  ["", [["uebersicht", "Übersicht"], ["ereignisse", "Ereignisse"]]],
  ["Inventar", [["geraete", "Geräte"], ["neu", "Nicht zugewiesen", null, null, "neu"]]],
  ["HASS.Agent", [["agenten", "Agenten"]]],
];
// abgesetzter Einstellungsbereich unten in der Seitenleiste
const NAVI_SYSTEM = [["einstellungen", "Einstellungen", null, "admin"], ["netzwerke", "Netzwerke"], ["kataloge", "Kataloge"],
  ["muster", "HASS.Agent Sensor-Erkennung"], ["benutzer", "Benutzer & API", null, "admin"], ["protokoll", "Protokoll", null, "operator"]];
let ZAHLEN = {};
let AKTUALISIEREN = null;   // Timer der aktuellen Ansicht

function aktuelleRoute() { const [n, q] = location.hash.slice(1).split("?"); return { name: n || "uebersicht", q: new URLSearchParams(q || "") }; }

function rahmen() {
  const r = aktuelleRoute();
  const navi = h("aside", { id: "navi" },
    h("div", { class: "logo" }, h("img", { src: "/static/logo-kurz-dunkel.svg", alt: "NINA", class: "wortmarke nur-dunkel" }), h("img", { src: "/static/logo-kurz-hell.svg", alt: "NINA", class: "wortmarke nur-hell" }),
      h("small", {}, META.name !== "NINA" ? META.name : "Network INventory Assistant")),
    NAVI.map(([gruppe, eintraege]) => [gruppe ? h("h4", {}, gruppe) : null, eintraege.map(navLink)]),
    h("div", { class: "navi-system" }, h("h4", {}, h("span", { class: "navi-system-symbol" }, "⚙"), "System & Einstellungen"),
      NAVI_SYSTEM.map(navLink)));
  function navLink([k, t, , rolle, zahl]) {
    if (rolle && !darf(rolle)) return null;
    return h("a", { class: "nav" + (r.name === k || (k === "geraete" && r.name === "geraet") ? " an" : ""), href: "#" + k,
      onclick: () => $("#navi").classList.remove("offen") }, t, zahl && ZAHLEN[zahl] ? h("span", { class: "zahl" }, ZAHLEN[zahl]) : null);
  }
  const oben = h("div", { class: "oben" },
    h("button", { class: "menu-knopf", onclick: () => $("#navi").classList.toggle("offen") }, "☰"),
    h("h1", { id: "titel" }, ""),
    h("div", { class: "rechts" }, themeWahl(), h("span", { class: "leise klein-t" }, ICH.anzeigename), marke(ICH.rolle, "akz"),
      h("button", { class: "klein", onclick: eigenesPasswort }, "Passwort"),
      h("button", { class: "klein", onclick: async () => { await api("POST", "/api/abmelden"); ICH = null; start(); } }, "Abmelden")));
  const main = h("main", { id: "inhalt" });
  leeren($("#app"), h("div", { class: "rahmen" }, navi, h("div", {}, oben, main)));
  return main;
}

async function zeige() {
  if (!ICH) return;
  clearInterval(AKTUALISIEREN); AKTUALISIEREN = null;
  const r = aktuelleRoute();
  const a = ANSICHT[r.name] || ANSICHT.uebersicht;
  await zahlenLaden();
  const main = rahmen();
  $("#titel").textContent = a.titel;
  document.title = `${a.titel} – NINA`;
  main.append(h("div", { class: "leer" }, "Lädt …"));
  try { await a.zeigen(main, r.q); }
  catch (e) { leeren(main, h("div", { class: "karte" }, h("h2", {}, punkt("bad"), "Fehler"), h("pre", {}, e.message))); }
}
/** Ansicht regelmäßig neu laden (nur solange sie sichtbar ist und kein Dialog offen ist). */
function alle(sekunden, fn) {
  clearInterval(AKTUALISIEREN);
  AKTUALISIEREN = setInterval(() => { if (!document.hidden && !$(".dialog-hg")) fn().catch(() => {}); }, sekunden * 1000);
}
window.addEventListener("hashchange", () => { if (ICH) zeige(); });

async function zahlenLaden() {
  try { const u = await api("GET", "/api/uebersicht"); ZAHLEN = { neu: u.neu + (u.agenten_frei || 0) }; } catch { /* egal */ }
}

async function start() {
  try {
    const st = await api("GET", "/api/status", undefined, { still: true });
    if (!st.eingerichtet) return zeigeEinrichtung(st);
    ICH = await api("GET", "/api/ich", undefined, { still: true });
    META = await api("GET", "/api/meta");
    await zahlenLaden();
    zeige();
  } catch (e) { zeigeAnmeldung(); }
}

function logoGross(unter) {
  return h("div", { class: "logo-gross" }, h("img", { src: "/static/icon.svg", alt: "", class: "symbol" }),
    h("img", { src: "/static/logo-dunkel.svg", alt: "NINA – Network Inventory Assistant", class: "wortmarke nur-dunkel" }),
    h("img", { src: "/static/logo-hell.svg", alt: "NINA – Network Inventory Assistant", class: "wortmarke nur-hell" }), unter ? h("div", {}, unter) : null);
}

// ------------------------------------------------------------------ Anmeldung
function zeigeAnmeldung() {
  const f = h("form", { onsubmit: async e => {
    e.preventDefault();
    try { await api("POST", "/api/anmeldung", lesenForm(f), { still: true }); start(); }
    catch (er) { hinweis(er.message, true); }
  } },
    feld("Benutzer", eingabe("benutzer", "", { autocomplete: "username", required: true })),
    feld("Passwort", eingabe("passwort", "", { type: "password", autocomplete: "current-password", required: true })),
    h("button", { class: "p voll", type: "submit" }, "Anmelden"));
  leeren($("#app"), h("div", { class: "ecke" }, themeWahl()), h("div", { class: "mitte" }, logoGross(""), h("div", { class: "karte" }, f)));
}

async function eigenesPasswort() {
  const f = h("div", {}, feld("Altes Passwort", eingabe("alt", "", { type: "password" })), pwFeld("neu", "Neues Passwort", "mindestens 10 Zeichen"));
  await dialog("Eigenes Passwort ändern", f, [["Abbrechen", null], ["Speichern", () => versuch(() => api("POST", "/api/ich/passwort", lesenForm(f)), "Passwort geändert"), "p"]]);
}

// ------------------------------------------------------------------ Einrichtung
const E = { code: "", schritt: 0, dbTyp: "sqlite", vorhanden: 0 };
const eapi = (m, p, d) => api(m, "/api/einrichtung" + p, d, { headers: { "X-NI-Einrichtung": E.code }, still: true });

function zeigeEinrichtung(st) {
  const titel = ["Code", "Datenbank", "Admin"];
  const box = h("div", { class: "karte" });
  const zeichnen = () => {
    leeren($("#app"), h("div", { class: "ecke" }, themeWahl()), h("div", { class: "mitte breit" },
      logoGross(`Einrichtung · Version ${st.version}`),
      h("div", { class: "schritte" }, titel.map((t, i) => h("div", { class: (i === E.schritt ? "an " : "") + (i < E.schritt ? "fertig" : "") }, h("b", {}, t), `Schritt ${i + 1}`))),
      box));
    leeren(box, SCHRITT[E.schritt](zeichnen));
  };
  zeichnen();
}
const weiter = z => { E.schritt++; z(); };
const zurueck = z => h("button", { onclick: () => { E.schritt--; z(); } }, "Zurück");

const SCHRITT = [
  z => {
    const i = eingabe("code", E.code, { placeholder: "XXXX-XXXX-XXXX", style: { fontFamily: "monospace", fontSize: "18px", textAlign: "center" } });
    return [h("h2", {}, "Willkommen"),
      h("p", {}, "NINA wird zum ersten Mal gestartet. Zum Schutz steht ein Einrichtungs-Code im Log des Containers (Unraid: Docker › NINA › Logs) und in /config/einrichtungs-code.txt."),
      feld("Einrichtungs-Code", i),
      h("div", { class: "leiste" }, h("span", { class: "rechts" }, h("button", { class: "p", onclick: async () => {
        E.code = i.value.trim().toUpperCase();
        const r = await versuch(() => eapi("POST", "/code"));
        E.dbDa = r.db_vorhanden; E.vorhanden = r.benutzer;
        weiter(z);
      } }, "Weiter")))];
  },
  z => {
    const typ = E.dbTyp;
    const wahlEl = h("div", { class: "wahl" },
      [["sqlite", "Eingebaut (SQLite)", "Datei in /config – nichts weiter nötig."],
       ["mariadb", "MariaDB / MySQL", "Vorhandene Datenbank, z. B. der MariaDB-Container auf Unraid. Empfohlen für Sicherungen und spätere Erweiterungen."]]
        .map(([v, t, b]) => h("label", {}, h("input", { type: "radio", name: "typ", value: v, checked: typ === v, onchange: () => { E.dbTyp = v; z(); } }), h("span", { class: "t" }, t), h("div", { class: "b" }, b))));
    const md = h("div", { class: typ === "mariadb" ? "" : "versteckt" },
      h("div", { class: "raster" }, feld("Server", eingabe("host", "", { placeholder: "<IP_MariaDB>" })), feld("Port", eingabe("port", "3306")),
        feld("Datenbank", eingabe("name", "nina")), feld("Benutzer", eingabe("benutzer", "nina")), feld("Passwort", eingabe("passwort", "", { type: "password" }))));
    const anl = haken("Datenbank und Benutzer jetzt anlegen (mit Root-Zugang)", false, "Nur wenn es sie noch nicht gibt. Der Root-Zugang wird nicht gespeichert.", "anlegen");
    const root = h("div", { class: "raster versteckt" }, feld("Root-Benutzer", eingabe("root_benutzer", "root")), feld("Root-Passwort", eingabe("root_passwort", "", { type: "password" })));
    anl.i.addEventListener("change", () => root.classList.toggle("versteckt", !anl.i.checked));
    md.append(anl.el, root);
    const daten = () => ({ typ, ...lesenForm(md) });
    return [h("h2", {}, "Wo sollen die Daten liegen?"),
      h("p", { class: "leise" }, "Geräte, Netzwerke, Einstellungen, Benutzer und das Protokoll. Das Schema hat eine Versionsnummer – neue Container-Versionen aktualisieren die Datenbank beim Start selbst."),
      wahlEl, md,
      E.dbDa ? h("p", { class: "marke ok" }, "Es ist bereits eine Datenbank eingerichtet – „Weiter“ ohne Änderung übernimmt sie.") : null,
      h("div", { class: "leiste" }, zurueck(z), h("span", { class: "rechts" },
        typ === "mariadb" ? h("button", { onclick: () => versuch(() => eapi("POST", "/db", { ...daten(), nur_testen: true }), "Verbindung klappt") }, "Testen") : null,
        h("button", { class: "p", onclick: async () => {
          if (E.dbDa && !E.dbGewaehlt && typ === "sqlite") return weiter(z);
          const r = await versuch(() => eapi("POST", "/db", daten()));
          E.vorhanden = r.benutzer; E.dbGewaehlt = true;
          if (r.benutzer) hinweis(`In der Datenbank sind schon ${r.benutzer} Benutzer – können übernommen werden.`);
          weiter(z);
        } }, "Weiter")))];
  },
  z => {
    const uebernehmen = haken(`Vorhandene Benutzer aus der Datenbank übernehmen (${E.vorhanden})`, E.vorhanden > 0, "Dann wird kein neuer Admin angelegt.", "uebernehmen");
    const neu = h("div", { class: E.vorhanden ? "versteckt" : "" }, h("div", { class: "raster" },
      feld("Benutzername", eingabe("benutzer", "admin", { autocomplete: "off" })), feld("Anzeigename", eingabe("anzeigename", "Administrator")),
      pwFeld("passwort", "Passwort", "mindestens 10 Zeichen")));
    uebernehmen.i.addEventListener("change", () => neu.classList.toggle("versteckt", uebernehmen.i.checked));
    const nw = h("div", {}, feld("Erstes Netzwerk (optional)", eingabe("netzwerk", "", { placeholder: "z. B. 192.168.10.0/24" }), "Kann später unter Netzwerke ergänzt werden – dort auch mehrere Netze/VLANs."));
    return [h("h2", {}, "Admin-Zugang"),
      E.vorhanden ? uebernehmen.el : null, neu, nw,
      h("div", { class: "leiste" }, zurueck(z), h("span", { class: "rechts" }, h("button", { class: "p", onclick: async () => {
        const d = { ...lesenForm(neu), ...lesenForm(nw), uebernehmen: E.vorhanden > 0 && uebernehmen.i.checked };
        await versuch(() => eapi("POST", "/abschluss", d), "Eingerichtet – bitte anmelden");
        location.hash = ""; start();
      } }, "Fertig")))];
  },
];

document.addEventListener("DOMContentLoaded", () => setTimeout(start, 0));
