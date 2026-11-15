/* NINA – Kataloge (Gerätetypen, Hersteller, Modelle) und die Auswahlfelder dafür */
"use strict";

let KATALOG = null;
async function katalogLaden(neu = false) {
  if (!KATALOG || neu) KATALOG = await api("GET", "/api/katalog");
  return KATALOG;
}

/** Felder Haupttyp + weitere Typen + Hersteller + Modell, Hersteller/Modelle passend zu den gewählten Typen.
 *  Rückgabe: { el, werte() -> {typ, typen, hersteller, modell} } */
function typHerstellerFelder(w, kat) {
  const id = "k" + Math.random().toString(36).slice(2, 8);
  let haupt = w.typ || "unbekannt";
  const weitere = new Set((w.typen || []).filter(k => k !== haupt));
  const hauptSel = auswahl("", META.typen, haupt);
  const chips = h("div", { class: "chips" });
  const hIn = eingabe("", w.hersteller, { placeholder: "aus Liste wählen oder neu eintragen" });
  const mIn = eingabe("", w.modell, { placeholder: "aus Liste wählen oder neu eintragen" });
  let hVor = [], mVor = [];
  vorschlaege(hIn, () => hVor);
  vorschlaege(mIn, () => mVor);
  const hinweis = h("small", { class: "leise" });
  const gewaehlt = () => new Set([haupt, ...weitere]);
  const zeichneChips = () => leeren(chips, META.typen.filter(([k]) => k !== haupt && k !== "unbekannt").map(([k, n, sym]) => {
    const an = weitere.has(k);
    return h("label", { class: "chip" + (an ? " an" : ""), style: { paddingRight: "10px", cursor: "pointer" } },
      h("input", { type: "checkbox", checked: an, style: { margin: "0 4px 0 0" }, onchange: e => { e.target.checked ? weitere.add(k) : weitere.delete(k); zeichneChips(); listen(); } }),
      sym ? sym + " " : "", n);
  }));
  const listen = () => {
    const t = gewaehlt(), hn = hIn.value.trim().toLowerCase();
    const passt = m => !m.typ || t.has(m.typ);
    const hs = kat.hersteller.map(x => ({ x, treffer: x.modelle.some(m => m.typ && t.has(m.typ)) }))
      .sort((a, b) => (b.treffer - a.treffer) || a.x.name.localeCompare(b.x.name, "de"));
    hVor = hs.map(({ x, treffer }) => ({ wert: x.name, info: treffer ? `${x.modelle.filter(m => m.typ && t.has(m.typ)).length} passende Modelle` : `${x.modelle.length} Modelle`,
      gruppe: hs.some(y => y.treffer) ? (treffer ? "Passend zum Typ" : "Weitere Hersteller") : "" }));
    const her = kat.hersteller.find(x => x.name.toLowerCase() === hn);
    const ms = her ? her.modelle.map(m => ({ m, h: her })) : kat.hersteller.flatMap(x => x.modelle.filter(m => m.typ && t.has(m.typ)).map(m => ({ m, h: x })));
    ms.sort((a, b) => (passt(b.m) - passt(a.m)) || a.m.name.localeCompare(b.m.name, "de"));
    mVor = ms.map(({ m, h: x }) => ({ wert: m.name, info: [her ? "" : x.name, m.typ ? typName(m.typ) : ""].filter(Boolean).join(" · ") }));
    hinweis.textContent = her ? `${her.modelle.length} Modelle von ${her.name} im Katalog` : (hn ? "neuer Hersteller – wird beim Speichern in den Katalog übernommen" : "");
  };
  mIn.addEventListener("change", () => {     // Modell gewählt: Hersteller und Typ ergänzen
    const name = mIn.value.trim().toLowerCase();
    const hn = hIn.value.trim().toLowerCase();
    for (const x of kat.hersteller) {
      const m = x.modelle.find(y => y.name.toLowerCase() === name);
      if (m && (!hn || x.name.toLowerCase() === hn)) {
        if (!hn) hIn.value = x.name;
        if (m.typ && !gewaehlt().has(m.typ)) { if (haupt === "unbekannt") { haupt = m.typ; hauptSel.value = haupt; } else weitere.add(m.typ); zeichneChips(); }
        break;
      }
    }
    listen();
  });
  hIn.addEventListener("input", listen);
  hauptSel.addEventListener("change", () => { weitere.delete(hauptSel.value); haupt = hauptSel.value; zeichneChips(); listen(); });
  zeichneChips(); listen();
  const el = h("div", {},
    h("div", { class: "raster" }, feld("Haupttyp", hauptSel, "bestimmt Symbol und Home-Assistant-Modell"),
      feld("Hersteller", hIn, null), feld("Modell", mIn, null)),
    hinweis,
    h("div", { class: "feld" }, h("span", {}, "Weitere Typen"), chips, h("small", {}, "Ein Gerät kann mehrere Typen haben, z. B. Server + Virtuelle Maschine")));
  return { el, werte: () => ({ typ: haupt, typen: [haupt, ...weitere], hersteller: hIn.value.trim(), modell: mIn.value.trim() }) };
}

// ------------------------------------------------------------------ Seite Kataloge
ANSICHT.kataloge = { titel: "Kataloge", async zeigen(main, q) {
  const tab = q.get("tab") || "typen";
  const kat = await katalogLaden(true);
  if (tab === "typen") await mdiLaden().catch(() => {});
  const inhalt = tab === "typen" ? typenTab(kat) : herstellerTab(kat);
  leeren(main, h("div", { class: "leiste" }, tabs([["typen", "Gerätetypen"], ["hersteller", "Hersteller & Modelle"]], tab, k => { location.hash = `#kataloge?tab=${k}`; })), inhalt);
} };

async function neuLaden() { await katalogLaden(true); META = await api("GET", "/api/meta"); zeige(); }

function typenTab(kat) {
  return h("div", { class: "karte" },
    h("h2", {}, "Gerätetypen", h("span", { class: "rechts" }, darf("admin") ? h("button", { class: "p klein", onclick: () => typDialog() }, "Typ hinzufügen") : null)),
    h("p", { class: "leise klein-t" }, "Die Typen stehen im Geräteformular zur Wahl; ein Gerät kann mehrere haben. Der Schlüssel landet in Home Assistant (z. B. für Filter), das Symbol (mdi) dort am Gerät."),
    tabelle([
      { t: "", w: t => h("span", { class: "typ-symbol" }, t.symbol) },
      { t: "Name", w: t => h("b", {}, t.name) },
      { t: "Schlüssel", w: t => h("span", { class: "mono" }, t.schluessel) },
      { t: "HA-Symbol", w: t => h("span", { class: "status-zeile" }, mdiSvg(t.icon, 20), h("span", { class: "mono leise" }, t.icon)) },
      { t: "Geräte", w: t => t.geraete, z: 1 },
      { t: "Reihenfolge", w: t => t.reihenfolge, z: 1 },
      { t: "", w: t => t.system ? marke("fest") : "" },
    ], kat.typen, { klick: darf("admin") ? t => typDialog(t) : null }));
}

async function typDialog(t = null) {
  await mdiLaden().catch(() => {});
  const f = h("div", { class: "raster" },
    feld("Name *", eingabe("name", t?.name, { placeholder: "z. B. Hypervisor" })),
    t ? feld("Schlüssel", eingabe("", t.schluessel, { disabled: true }), "nicht änderbar") : feld("Schlüssel", eingabe("schluessel", "", { placeholder: "leer = aus dem Namen" }), "a–z, 0–9, _"),
    feld("Symbol in NINA", symbolFeld("symbol", t?.symbol, "zeichen"), "Zeichen oder Emoji für die Listen"),
    feld("HA-Symbol", symbolFeld("icon", t?.icon, "mdi"), "Material Design Icon – wie in Home Assistant"),
    feld("Reihenfolge", eingabe("reihenfolge", t?.reihenfolge ?? 100, { type: "number" })));
  const kn = [["Abbrechen", null]];
  if (t && !t.system) kn.push(["Löschen", async () => {
    if (!(await bestaetigen(`Typ „${t.name}“ löschen?${t.geraete ? ` ${t.geraete} Geräte verlieren ihn (Haupttyp wird der nächste Typ bzw. „Unbekannt“).` : ""}`, "Löschen"))) return false;
    return versuch(() => api("DELETE", `/api/katalog/typen/${t.id}`), "Gelöscht");
  }, "gefahr"]);
  kn.push(["Speichern", () => versuch(() => api("POST", "/api/katalog/typen", { ...lesenForm(f), id: t?.id }), "Gespeichert"), "p"]);
  if (await dialog(t ? `Typ „${t.name}“` : "Typ hinzufügen", f, kn)) neuLaden();
}

function herstellerTab(kat) {
  return h("div", {},
    h("div", { class: "leiste" },
      h("span", { class: "leise klein-t" }, "Wächst mit: Hersteller/Modelle, die ein Gerät beim Übernehmen oder Speichern bekommt, werden eingetragen. Umbenennen ändert die Angabe auch an allen Geräten."),
      h("span", { class: "rechts" }, darf("operator") ? [
        h("button", { onclick: async () => { const r = await versuch(() => api("POST", "/api/katalog/aus-inventar")); hinweis(`${r.neu} Einträge übernommen`); neuLaden(); } }, "Aus Inventar übernehmen"),
        h("button", { onclick: () => modellDialog(kat) }, "Modell hinzufügen"),
        h("button", { class: "p", onclick: () => herstellerDialog() }, "Hersteller hinzufügen")] : null)),
    kat.hersteller.length ? kat.hersteller.map(x => h("div", { class: "karte" },
      h("h2", {}, x.name, h("span", { class: "marke" }, `${x.geraete} Geräte`), x.webseite ? h("a", { href: x.webseite, target: "_blank", rel: "noopener", class: "klein-t" }, "Webseite") : null,
        h("span", { class: "rechts" }, darf("operator") ? [h("button", { class: "klein", onclick: () => modellDialog(kat, { hersteller_id: x.id }) }, "Modell"),
          h("button", { class: "klein", onclick: () => herstellerDialog(x) }, "Bearbeiten")] : null)),
      x.notizen ? h("p", { class: "leise klein-t" }, x.notizen) : null,
      tabelle([
        { t: "Modell", w: m => h("b", {}, m.name) },
        { t: "Typ", w: m => m.typ ? h("span", {}, typSymbol(m.typ), " ", typName(m.typ)) : h("span", { class: "leise" }, "–") },
        { t: "Geräte", w: m => m.geraete, z: 1 },
        { t: "Notizen", w: m => h("span", { class: "leise klein-t" }, m.notizen) },
      ], x.modelle, { leer: "Noch keine Modelle", klick: darf("operator") ? m => modellDialog(kat, { ...m, hersteller_id: x.id }) : null })))
      : h("div", { class: "karte leer" }, "Noch keine Hersteller. „Aus Inventar übernehmen“ trägt die Hersteller und Modelle aller Geräte ein."));
}

async function herstellerDialog(x = null) {
  const f = h("div", {}, h("div", { class: "raster" }, feld("Name *", eingabe("name", x?.name, { placeholder: "z. B. Brother" })),
    feld("Webseite", eingabe("webseite", x?.webseite, { placeholder: "https://…" }))),
    feld("Notizen", h("textarea", { name: "notizen", rows: 2 }, x?.notizen || "")));
  const kn = [["Abbrechen", null]];
  if (x && darf("admin")) kn.push(["Löschen", async () => {
    if (!(await bestaetigen(`Hersteller „${x.name}“ mit ${x.modelle.length} Modellen aus dem Katalog löschen? Die Geräte behalten ihre Angaben.`, "Löschen"))) return false;
    return versuch(() => api("DELETE", `/api/katalog/hersteller/${x.id}`), "Gelöscht");
  }, "gefahr"]);
  kn.push(["Speichern", () => versuch(() => api("POST", "/api/katalog/hersteller", { ...lesenForm(f), id: x?.id }), "Gespeichert"), "p"]);
  if (await dialog(x ? `Hersteller „${x.name}“` : "Hersteller hinzufügen", f, kn)) neuLaden();
}

async function modellDialog(kat, m = {}) {
  if (!kat.hersteller.length) return hinweis("Erst einen Hersteller anlegen", true);
  const f = h("div", {}, h("div", { class: "raster" },
    feld("Hersteller *", auswahl("hersteller_id", kat.hersteller.map(x => [x.id, x.name]), m.hersteller_id ?? kat.hersteller[0].id)),
    feld("Modell *", eingabe("name", m.name, { placeholder: "z. B. HL-2040" })),
    feld("Typ", auswahl("typ", [["", "–"], ...META.typen.filter(([k]) => k !== "unbekannt")], m.typ || ""), "bestimmt, bei welchem Gerätetyp das Modell vorgeschlagen wird")),
    feld("Notizen", h("textarea", { name: "notizen", rows: 2 }, m.notizen || "")));
  const kn = [["Abbrechen", null]];
  if (m.id && darf("admin")) kn.push(["Löschen", () => versuch(() => api("DELETE", `/api/katalog/modelle/${m.id}`), "Gelöscht"), "gefahr"]);
  kn.push(["Speichern", () => versuch(() => api("POST", "/api/katalog/modelle", { ...lesenForm(f), id: m.id }), "Gespeichert"), "p"]);
  if (await dialog(m.id ? `Modell „${m.name}“` : "Modell hinzufügen", f, kn)) neuLaden();
}
