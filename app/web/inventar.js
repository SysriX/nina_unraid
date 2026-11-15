/* NINA – Ansichten: Übersicht, Geräte, Gerät, Neu gefunden, Netzwerke, Ereignisse */
"use strict";

const typSymbol = t => h("span", { class: "typ-symbol", title: typName(t) }, (META.typen.find(x => x[0] === t) || [])[2] || "◇");
const typName = t => (META.typen.find(x => x[0] === t) || [t, t])[1];
const onlineMarke = g => g.online ? h("span", { class: "status-zeile" }, punkt("ok"), "online") : h("span", { class: "status-zeile" }, punkt(""), h("span", { class: "leise" }, "offline"));
const WOL_METHODEN = [["auto", "Automatisch"], ["container", "Container (Broadcast)"], ["opnsense", "OPNsense"], ["beide", "Container + OPNsense"]];
const ART_NAMEN = { neu: "Neu", online: "Online", offline: "Offline", ip: "IP geändert", wol: "Wake-on-LAN", befehl: "Befehl", agent: "Agent" };

// ------------------------------------------------------------------ Übersicht
ANSICHT.uebersicht = { titel: "Übersicht", async zeigen(main) {
  const zeichnen = async () => {
    const u = await api("GET", "/api/uebersicht");
    ZAHLEN.neu = u.neu;
    const kachel = (w, l, ziel, art) => h("div", { class: "kachel" + (ziel ? " klick" : ""), onclick: ziel ? () => (location.hash = ziel) : null },
      h("div", { class: "w", style: art ? { color: `var(--${art})` } : null }, w), h("div", { class: "l" }, l));
    leeren(main,
      h("div", { class: "kacheln" },
        kachel(u.geraete, "Geräte im Inventar", "#geraete"),
        kachel(u.online, "davon online", "#geraete?filter=online", "ok"),
        kachel(u.neu, "neu gefunden", "#neu", u.neu ? "warn" : null),
        kachel(`${u.agenten_online}/${u.agenten}`, "HASS.Agents online", "#agenten"),
        kachel(u.netze.length, "Netzwerke", "#netzwerke")),
      h("div", { class: "zwei" },
        h("div", {},
          h("div", { class: "karte" }, h("h2", {}, "Netzwerke", h("span", { class: "rechts" }, h("a", { href: "#netzwerke" }, h("button", { class: "klein" }, "Verwalten")))),
            tabelle([{ t: "Name", w: n => n.name }, { t: "Netz", w: n => h("span", { class: "mono" }, n.cidr) },
              { t: "Online", w: n => `${n.online}/${n.geraete}`, z: 1 }, { t: "Letzter Scan", w: n => h("div", { class: "zwei-zeilen" }, vorZeit(n.letzter_scan), h("small", {}, n.scan_status)) }],
            u.netze, { leer: "Noch kein Netzwerk – unter Netzwerke anlegen, dann wird automatisch gescannt.", klick: () => (location.hash = "#netzwerke") })),
          h("div", { class: "karte" }, h("h2", {}, "Gerätetypen"),
            u.typen.length ? h("div", { class: "chips" }, u.typen.map(t => h("a", { href: `#geraete?typ=${t.typ}`, style: { textDecoration: "none", color: "inherit" } },
              h("span", { class: "chip", style: { paddingRight: "10px" } }, typSymbol(t.typ), t.name, " ", h("b", {}, t.anzahl))))) : h("div", { class: "leer" }, "Noch keine Geräte"))),
        h("div", { class: "karte" }, h("h2", {}, "Letzte Ereignisse", h("span", { class: "rechts" }, h("a", { href: "#ereignisse" }, h("button", { class: "klein" }, "Alle")))),
          ereignisListe(u.ereignisse, true))));
  };
  await zeichnen();
  alle(20, zeichnen);
} };

function ereignisListe(liste, mitGeraet) {
  if (!liste.length) return h("div", { class: "leer" }, "Noch nichts passiert");
  const art = { online: "ok", offline: "", neu: "warn", wol: "akz", befehl: "akz", ip: "warn", agent: "" };
  return h("div", { class: "log" }, liste.map(e => h("div", {},
    h("span", { style: { minWidth: "92px" }, class: "leise klein-t" }, vorZeit(e.zeit)),
    marke(ART_NAMEN[e.art] || e.art, art[e.art] || ""),
    h("span", {}, mitGeraet && e.geraet ? [h("a", { href: `#geraet?id=${e.geraet_id}` }, e.geraet), " "] : null, h("span", { class: "leise" }, e.text)))));
}

// ------------------------------------------------------------------ Geräte
const FILTER = { suche: "", typ: "", netz: "", online: "", status: "aktiv" };
ANSICHT.geraete = { titel: "Geräte", async zeigen(main, q) {
  if (q.get("typ")) FILTER.typ = q.get("typ");
  if (q.get("filter") === "online") FILTER.online = "online";
  let daten = [];
  const box = h("div");
  const zeichnen = () => {
    const s = FILTER.suche.toLowerCase();
    const liste = daten.filter(g => (!FILTER.typ || (g.typen || [g.typ]).includes(FILTER.typ)) && (!FILTER.netz || g.netzwerk === FILTER.netz)
      && (!FILTER.online || (FILTER.online === "online") === g.online)
      && (!s || [g.name, g.ip, g.mac, g.hostname, g.benutzer, g.angemeldet, g.hersteller, g.modell, g.standort, ...(g.tags || [])].some(x => (x || "").toLowerCase().includes(s))));
    leeren(box, h("div", { class: "karte" }, h("h2", {}, `${liste.length} von ${daten.length} Geräten`),
      tabelle([
        { t: "", w: g => g.online ? punkt("ok") : punkt(""), sort: g => g.online ? 0 : 1 },
        { t: "Name", w: g => h("div", { class: "zwei-zeilen" }, h("b", {}, g.name), g.hostname && g.hostname.split(".")[0].toLowerCase() !== g.name.toLowerCase() ? h("small", {}, g.hostname) : null), sort: g => g.name.toLowerCase() },
        { t: "Typ", w: g => h("div", { class: "zwei-zeilen" }, h("span", {}, typSymbol(g.typ), " ", g.typ_name),
            (g.typ_namen || []).length > 1 ? h("small", {}, "+ " + g.typ_namen.slice(1).join(", ")) : null), sort: g => g.typ_name },
        { t: "Benutzer", w: g => h("div", { class: "zwei-zeilen" }, g.benutzer || "", g.angemeldet && g.angemeldet !== g.benutzer ? h("small", {}, "angemeldet: " + g.angemeldet) : null) },
        { t: "IP", w: g => h("span", { class: "mono" }, g.ip), sort: g => (g.ip || "").split(".").map(x => x.padStart(3, "0")).join(".") },
        { t: "MAC", w: g => h("span", { class: "mono" }, g.mac) },
        { t: "Netz", w: g => g.netzwerk },
        { t: "Hersteller / Modell", w: g => [g.hersteller, g.modell].filter(Boolean).join(" · ") },
        { t: "", w: g => [g.agent ? marke("Agent", g.agent.online ? "ok" : "") : null, " ", g.wol && !g.online && darf("operator") ? h("button", { class: "klein", title: "Wake-on-LAN", onclick: () => wecken(g) }, "Wecken") : null] },
        { t: "Zuletzt online", w: g => g.online ? "jetzt" : vorZeit(g.zuletzt_online), sort: g => g.online ? "9" : g.zuletzt_online || "" },
      ], liste, { klick: g => (location.hash = `#geraet?id=${g.id}`), leer: daten.length ? "Kein Gerät passt zum Filter" : "Noch keine Geräte – Netzwerk anlegen und scannen oder von Hand hinzufügen", sortierbar: true })));
  };
  const laden = async () => { daten = (await api("GET", `/api/geraete?status=${FILTER.status}`)).geraete; zeichnen(); };
  const netze = [...new Set((await api("GET", "/api/netzwerke")).netzwerke.map(n => n.name))];
  const suche = eingabe("", FILTER.suche, { placeholder: "Suchen: Name, IP, MAC, Benutzer …", class: "suche", oninput: e => { FILTER.suche = e.target.value; zeichnen(); } });
  leeren(main, h("div", { class: "leiste" },
    suche,
    auswahl("", [["", "Alle Typen"], ...META.typen], FILTER.typ, { onchange: e => { FILTER.typ = e.target.value; zeichnen(); } }),
    auswahl("", [["", "Alle Netze"], ...netze], FILTER.netz, { onchange: e => { FILTER.netz = e.target.value; zeichnen(); } }),
    auswahl("", [["", "Online + offline"], ["online", "Nur online"], ["offline", "Nur offline"]], FILTER.online, { onchange: e => { FILTER.online = e.target.value; zeichnen(); } }),
    auswahl("", [["aktiv", "Inventar"], ["ignoriert", "Ignorierte"], ["ausgemustert", "Ausgemustert"], ["alle", "Alle"]], FILTER.status, { onchange: e => { FILTER.status = e.target.value; laden(); } }),
    h("span", { class: "rechts" }, darf("operator") ? h("button", { class: "p", onclick: () => geraetDialog() }, "Gerät hinzufügen") : null)),
    box);
  suche.focus();
  await laden();
  alle(15, laden);
} };

async function wecken(g) {
  const r = await versuch(() => api("POST", `/api/geraete/${g.id}/wecken`));
  hinweis(`Magic Packet für ${g.name} gesendet (${r.methode}: ${r.wege.join(", ")})` + (r.fehler.length ? "\n" + r.fehler.join("\n") : ""));
}

/** Gerät anlegen/bearbeiten */
async function geraetDialog(g = null) {
  const neu = !g;
  g = g || { typ: "pc", typen: ["pc"], status: "aktiv", ha_import: true, ueberwachen: false, wol_aktiv: false, wol_methode: "", tags: [], extra: {} };
  const th = typHerstellerFelder(g, await katalogLaden(true));
  const f = h("div", {},
    h("div", { class: "raster" },
      feld("Name *", eingabe("name", g.name, { required: true })),
      feld("Benutzer", eingabe("benutzer", g.benutzer, { placeholder: "wer arbeitet an dem Gerät" })),
      feld("Betriebssystem", eingabe("betriebssystem", g.betriebssystem)),
      feld("Seriennummer", eingabe("seriennummer", g.seriennummer)),
      feld("Inventarnummer", eingabe("inventarnummer", g.inventarnummer)),
      feld("Standort", eingabe("standort", g.standort, { placeholder: "z. B. Büro, Keller-Rack" })),
      feld("Raum-Kürzel (Home Assistant)", eingabe("raum", g.raum, { placeholder: "bu, wz, … leer = haus" }), "Vorne in der Entitäts-ID: <raum>_net_<gerät>_…"),
      feld("Schlagwörter", eingabe("tags", (g.tags || []).join(", "), { placeholder: "kommagetrennt" })),
      neu ? null : feld("Status", auswahl("status", [["aktiv", "Im Inventar"], ["neu", "Neu (ungeprüft)"], ["ignoriert", "Ignoriert"], ["ausgemustert", "Ausgemustert"]], g.status))),
    th.el,
    neu ? h("div", { class: "raster" }, feld("IP-Adresse", eingabe("ip", "", { placeholder: "192.168.10.20" })), feld("MAC-Adresse", eingabe("mac", "", { placeholder: "aa:bb:cc:dd:ee:ff" })),
      h("div", {}, haken("Feste IP (Scan ändert sie nicht)", false, null, "feste_ip").el)) : null,
    META.zusatzfelder.length ? h("div", { class: "raster", id: "zusatz" }, META.zusatzfelder.map(z => {
      const w = (g.extra || {})[z.name] ?? "";
      const i = z.art === "auswahl" ? auswahl("x_" + z.name, ["", ...z.optionen.split(",").map(x => x.trim()).filter(Boolean)], w)
        : eingabe("x_" + z.name, w, { type: z.art === "zahl" ? "number" : z.art === "datum" ? "date" : "text" });
      return feld(z.titel, i);
    })) : null,
    feld("Notizen", h("textarea", { name: "notizen", rows: 3 }, g.notizen || "")),
    h("div", { class: "raster" },
      haken("Wake-on-LAN erlauben", g.wol_aktiv, "Braucht eine MAC-Adresse", "wol_aktiv").el,
      feld("WoL-Weg", auswahl("wol_methode", [["", "Wie das Netzwerk"], ...WOL_METHODEN], g.wol_methode)),
      haken("Überwachen (regelmäßig anpingen)", g.ueberwachen, "Schnelle Online-Erkennung, z. B. für PCs", "ueberwachen").el,
      haken("An Home Assistant geben", g.ha_import, "Gerät mit Sensoren/Knöpfen in HA anlegen", "ha_import").el));
  const r = await dialog(neu ? "Gerät hinzufügen" : `„${g.name}“ bearbeiten`, f, [["Abbrechen", null], ["Speichern", async () => {
    const d = { ...lesenForm(f), ...th.werte() };
    d.extra = {};
    for (const k of Object.keys(d)) if (k.startsWith("x_")) { d.extra[k.slice(2)] = d[k]; delete d[k]; }
    if (!neu) d.id = g.id;
    return await versuch(() => api("POST", "/api/geraete", d), "Gespeichert");
  }, "p"]], true);
  if (r && neu) location.hash = `#geraet?id=${r.id}`;
  else if (r) zeige();
}

// ------------------------------------------------------------------ Gerät (Infokarte)
ANSICHT.geraet = { titel: "Gerät", async zeigen(main, q) {
  const id = Number(q.get("id"));
  const zeichnen = async () => {
    const g = await api("GET", `/api/geraete/${id}`);
    $("#titel").textContent = g.name; document.title = `${g.name} – NINA`;
    const links = h("div", {},
      h("div", { class: "karte" },
        h("h2", {}, typSymbol(g.typ), g.name, g.status !== "aktiv" ? marke(g.status, "warn") : null,
          h("span", { class: "rechts" }, darf("operator") ? h("button", { class: "klein", onclick: () => geraetDialog(g) }, "Bearbeiten") : null)),
        h("dl", { class: "daten" },
          [["Typ", (g.typ_namen || [g.typ_name]).join(", ")], ["Benutzer", g.benutzer], ["Angemeldet", g.angemeldet], ["Hersteller", g.hersteller], ["Modell", g.modell],
           ["Betriebssystem", g.betriebssystem], ["Seriennummer", g.seriennummer], ["Inventarnummer", g.inventarnummer],
           ["Standort", g.standort], ["Raum (HA)", g.raum], ["Schlagwörter", (g.tags || []).join(", ")],
           ...META.zusatzfelder.map(z => [z.titel, (g.extra || {})[z.name]]),
           ["Quelle", g.quelle], ["Angelegt", datum(g.erstellt)]]
            .filter(([, v]) => v).map(([k, v]) => [h("dt", {}, k), h("dd", {}, v)])),
        g.notizen ? h("pre", { style: { marginTop: "12px" } }, g.notizen) : null),
      schnittstellenKarte(g),
      h("div", { class: "karte" }, h("h2", {}, "Ereignisse"), ereignisListe(g.ereignisse, false)));
    const rechts = h("div", {}, statusKarte(g, zeichnen), g.agent ? agentKarte(g, zeichnen) : agentHinweis(g));
    leeren(main, h("div", { class: "leiste" }, h("a", { href: "#geraete" }, h("button", { class: "klein" }, "← Alle Geräte"))), h("div", { class: "zwei" }, links, rechts));
  };
  await zeichnen();
  alle(10, zeichnen);
} };

function statusKarte(g, neu) {
  return h("div", { class: "karte" },
    h("h2", {}, "Status", h("span", { class: "rechts" }, h("button", { class: "klein", onclick: async () => {
      const r = await versuch(() => api("POST", `/api/geraete/${g.id}/pruefen`));
      hinweis(r.ergebnis.length ? r.ergebnis.map(x => `${x.ip}: ${x.erreichbar ? "erreichbar" : "nicht erreichbar"}`).join("\n") : "Keine IP-Adresse"); neu();
    } }, "Jetzt prüfen"))),
    h("div", { class: "werte" },
      h("div", { class: "wert" }, h("div", { class: "l" }, "Zustand"), h("div", { class: "w" }, onlineMarke(g))),
      h("div", { class: "wert" }, h("div", { class: "l" }, "Zuletzt online"), h("div", { class: "w" }, g.online ? "jetzt" : vorZeit(g.zuletzt_online))),
      h("div", { class: "wert" }, h("div", { class: "l" }, "IP"), h("div", { class: "w mono" }, g.ip || "–")),
      h("div", { class: "wert" }, h("div", { class: "l" }, "MAC"), h("div", { class: "w mono" }, g.mac || "–"))),
    h("h2", { style: { marginTop: "16px" } }, "Wake-on-LAN"),
    g.mac ? h("div", {},
      h("p", { class: "leise klein-t" }, g.wol_aktiv ? `Weg: ${(WOL_METHODEN.find(x => x[0] === g.wol_methode_wirksam) || [, g.wol_methode_wirksam])[1]}` + (g.wol_netz ? ` · Netz ${g.wol_netz}` : "") : "Wake-on-LAN ist für dieses Gerät aus (Bearbeiten › Wake-on-LAN erlauben)."),
      g.wol_aktiv && darf("operator") ? h("button", { class: "p", onclick: () => wecken(g).then(neu) }, g.online ? "Trotzdem wecken" : "Einschalten (WoL)") : null)
      : h("p", { class: "leise" }, "Keine MAC-Adresse bekannt."));
}

function agentHinweis(g) {
  if (!["pc", "laptop", "server", "vm"].includes(g.typ)) return null;
  return h("div", { class: "karte" }, h("h2", {}, "HASS.Agent"),
    h("p", { class: "leise" }, "Kein HASS.Agent verknüpft. Läuft HASS.Agent auf dem Rechner und nutzt denselben MQTT-Broker, erscheint er unter „Agenten“ und wird über den Namen automatisch verknüpft."),
    h("a", { href: "#agenten" }, h("button", { class: "klein" }, "Zu den Agenten")));
}

const prozent = w => w.einheit === "%" && !isNaN(parseFloat(w.wert));
function wertAnzeige(w) {
  let v = w.wert ?? "";
  if (w.device_class === "timestamp" && v) v = datum(v);
  if (v === "" || v === null) v = "–";
  return h("div", { class: "wert", title: `${w.name}\n${w.schluessel}${w.kategorie ? "\nKategorie: " + w.kategorie : ""}` },
    h("div", { class: "l" }, w.anzeige), h("div", { class: "w" }, String(v), w.einheit && v !== "–" ? h("small", {}, w.einheit) : null),
    prozent(w) ? h("div", { class: "balken" }, h("i", { style: { width: Math.min(100, Math.max(0, parseFloat(w.wert))) + "%" } })) : null);
}

function agentKarte(g, neu) {
  const a = g.agent;
  const befehle = (a.befehle || []).filter(b => b.importieren || darf("admin"));
  return h("div", { class: "karte" },
    h("h2", {}, "HASS.Agent", a.online ? marke("online", "ok") : marke("offline", "bad"), h("span", { class: "rechts leise klein-t" }, a.version ? "v" + a.version : "")),
    h("p", { class: "leise klein-t", style: { marginTop: 0 } }, [a.name, a.modell, a.zuletzt ? "Daten " + vorZeit(a.zuletzt) : ""].filter(Boolean).join(" · ")),
    befehle.length ? [h("div", { class: "knopfreihe", style: { marginBottom: "14px" } }, befehle.map(b => h("button", {
      class: b.gefahr ? "gefahr" : "", disabled: !darf("operator"), title: `${b.name} (${b.schluessel})`,
      onclick: async () => {
        if (b.gefahr && !(await bestaetigen(`„${b.anzeige}“ auf ${g.name} ausführen?`, b.anzeige))) return;
        await versuch(() => api("POST", `/api/geraete/${g.id}/befehl`, { befehl: b.schluessel }), `${b.anzeige}: gesendet`); neu();
      } }, b.anzeige, b.art === "switch" && b.zustand ? ` (${b.zustand})` : "")))] : h("p", { class: "leise" }, "Keine Befehle (in HASS.Agent unter Befehle anlegen, z. B. Shutdown, Restart, Lock)."),
    a.werte.length ? h("div", { class: "werte" }, a.werte.filter(w => w.importieren || darf("admin")).map(wertAnzeige)) : h("p", { class: "leise" }, "Noch keine Sensorwerte."));
}

function schnittstellenKarte(g) {
  return h("div", { class: "karte" },
    h("h2", {}, "Netzwerk-Schnittstellen", h("span", { class: "rechts" }, darf("operator") ? h("button", { class: "klein", onclick: () => schnittstelleDialog(g) }, "Hinzufügen") : null)),
    tabelle([
      { t: "", w: x => punkt(x.online ? "ok" : "") },
      { t: "IP", w: x => h("div", { class: "zwei-zeilen" }, h("span", { class: "mono" }, x.ip), x.feste_ip ? h("small", {}, "fest") : null) },
      { t: "MAC", w: x => h("div", { class: "zwei-zeilen" }, h("span", { class: "mono" }, x.mac), x.mac_hersteller ? h("small", {}, x.mac_hersteller) : null) },
      { t: "Name / Host", w: x => h("div", { class: "zwei-zeilen" }, x.name || x.hostname, x.name && x.hostname ? h("small", {}, x.hostname) : null) },
      { t: "Netz", w: x => x.netzwerk },
      { t: "", w: x => [x.primaer ? marke("primär", "akz") : null, " ", marke(x.quelle)] },
      { t: "Zuletzt", w: x => x.online ? "jetzt" : vorZeit(x.zuletzt) },
    ], g.schnittstellen, { klick: darf("operator") ? x => schnittstelleDialog(g, x) : null, leer: "Keine Schnittstellen" }));
}

async function schnittstelleDialog(g, x = null) {
  const netze = (await api("GET", "/api/netzwerke")).netzwerke;
  const f = h("div", { class: "raster" },
    feld("IP-Adresse", eingabe("ip", x?.ip)), feld("MAC-Adresse", eingabe("mac", x?.mac, { placeholder: "aa:bb:cc:dd:ee:ff" })),
    feld("Bezeichnung", eingabe("name", x?.name, { placeholder: "z. B. LAN, WLAN" })), feld("Hostname", eingabe("hostname", x?.hostname)),
    feld("Netzwerk", auswahl("netzwerk_id", [["", "automatisch (nach IP)"], ...netze.map(n => [n.id, `${n.name} (${n.cidr})`])], x?.netzwerk_id ?? "")),
    h("div", {}, haken("Primäre Schnittstelle", x ? x.primaer : !g.schnittstellen.length, null, "primaer").el, haken("Feste IP (Scan ändert sie nicht)", x?.feste_ip, null, "feste_ip").el));
  const kn = [["Abbrechen", null]];
  if (x) kn.push(["Entfernen", async () => { if (!(await bestaetigen("Schnittstelle entfernen?", "Entfernen"))) return false; return versuch(() => api("DELETE", `/api/schnittstellen/${x.id}`), "Entfernt"); }, "gefahr"]);
  kn.push(["Speichern", () => versuch(() => api("POST", `/api/geraete/${g.id}/schnittstellen`, { ...lesenForm(f), id: x?.id }), "Gespeichert"), "p"]);
  if (await dialog(x ? "Schnittstelle bearbeiten" : "Schnittstelle hinzufügen", f, kn)) zeige();
}

// ------------------------------------------------------------------ Neu gefunden
ANSICHT.neu = { titel: "Neu gefunden", async zeigen(main) {
  const laden = async () => {
    const liste = (await api("GET", "/api/geraete?status=neu")).geraete;
    const alleG = (await api("GET", "/api/geraete?status=aktiv")).geraete;
    ZAHLEN.neu = liste.length;
    leeren(main,
      h("p", { class: "leise" }, "Vom Scan, der OPNsense oder einem HASS.Agent gefundene Geräte – sie kommen nie automatisch ins Inventar. Beim Übernehmen lassen sich doppelte Funde (z. B. Scan + Agent desselben PCs) gleich zusammenführen. Ignorierte tauchen nicht wieder auf."),
      h("div", { class: "karte" }, h("h2", {}, `${liste.length} neue Geräte`, liste.length && darf("operator") ? h("span", { class: "rechts" },
        h("button", { class: "klein", onclick: async () => { if (!(await bestaetigen(`Alle ${liste.length} ignorieren?`, "Alle ignorieren"))) return;
          for (const g of liste) await api("POST", `/api/geraete/${g.id}/status`, { status: "ignoriert" }); laden(); } }, "Alle ignorieren")) : null),
        tabelle([
          { t: "", w: g => punkt(g.online ? "ok" : "") },
          { t: "Name", w: g => h("b", {}, g.name) }, { t: "Vermutung", w: g => h("span", {}, typSymbol(g.typ), " ", g.typ_name) },
          { t: "IP", w: g => h("span", { class: "mono" }, g.ip) }, { t: "MAC", w: g => h("span", { class: "mono" }, g.mac) },
          { t: "Hersteller", w: g => g.hersteller }, { t: "Netz", w: g => g.netzwerk }, { t: "Quelle", w: g => g.agent ? "HASS.Agent" : g.quelle },
          { t: "", w: g => darf("operator") ? h("div", { class: "knopfreihe" },
            h("button", { class: "klein p", onclick: () => uebernehmenDialog(g).then(r => r && laden()) }, "Übernehmen"),
            h("button", { class: "klein", onclick: () => zusammenDialog(g, alleG).then(r => r && laden()) }, "Zusammenführen"),
            h("button", { class: "klein", onclick: async () => { await api("POST", `/api/geraete/${g.id}/status`, { status: "ignoriert" }); laden(); } }, "Ignorieren")) : null },
        ], liste, { leer: "Nichts Neues – alles im Inventar.", klick: g => (location.hash = `#geraet?id=${g.id}`) })));
  };
  await laden();
  alle(30, laden);
} };

/** Gerät ins Inventar übernehmen – dabei andere Funde (Scan, Agent, OPNsense) direkt zusammenführen. */
async function uebernehmenDialog(g) {
  const [v, kat] = await Promise.all([api("GET", `/api/geraete/${g.id}/vorschlaege`), katalogLaden(true)]);
  const wahl = new Set(v.vorschlaege.filter(x => x.status === "neu" && x.gruende.length).map(x => x.id));
  let ziel = null;     // gewähltes Inventar-Gerät, in das stattdessen alles einfließt
  const th = typHerstellerFelder(g, kat);
  const kopf = h("div", { class: "raster" }, feld("Name", eingabe("name", g.name)),
    feld("Benutzer", eingabe("benutzer", g.benutzer || "")), feld("Raum-Kürzel", eingabe("raum", g.raum || "", { placeholder: "optional" })),
    feld("Standort", eingabe("standort", g.standort || "")));
  const quelle = x => [x.agent_name ? "HASS.Agent" : "", x.quelle].filter(Boolean)[0] || x.quelle;
  const liste = h("div");
  const zeichne = () => leeren(liste, v.vorschlaege.length ? tabelle([
    { t: "", w: x => x.status === "neu"
        ? h("input", { type: "checkbox", checked: wahl.has(x.id), disabled: !!ziel, onchange: e => { e.target.checked ? wahl.add(x.id) : wahl.delete(x.id); } })
        : h("input", { type: "radio", name: "ziel", checked: ziel === x.id, title: "stattdessen in dieses Inventar-Gerät übernehmen",
            onclick: e => { ziel = ziel === x.id ? null : x.id; e.target.checked = ziel === x.id; zeichne(); } }) },
    { t: "Gerät", w: x => h("div", { class: "zwei-zeilen" }, h("b", {}, x.name), h("small", {}, x.status === "neu" ? "neu gefunden · " + quelle(x) : "im Inventar")) },
    { t: "Typ", w: x => h("span", {}, typSymbol(x.typ), " ", x.typ_name) },
    { t: "IP / MAC", w: x => h("div", { class: "zwei-zeilen mono" }, x.ip, h("small", {}, x.mac)) },
    { t: "Passt wegen", w: x => x.gruende.length ? x.gruende.map(r => marke(r, "ok")) : h("span", { class: "leise" }, "–") },
  ], v.vorschlaege) : h("p", { class: "leise" }, "Keine weiteren Funde."));
  zeichne();
  const f = h("div", {}, kopf, th.el,
    h("h4", {}, "Zusammenführen"),
    h("p", { class: "leise klein-t" }, "Haken: dieser Fund wird mit übernommen (Schnittstellen, HASS.Agent und Verlauf wandern in dieses Gerät, der Fund verschwindet). Vorausgewählt ist, was über Name, IP oder MAC passt. Kreis bei einem Inventar-Gerät: statt neu anzulegen, wird alles diesem Gerät zugeschlagen."),
    liste);
  return dialog(`„${g.name}“ übernehmen`, f, [["Abbrechen", null], ["Übernehmen", async () => {
    if (ziel) {
      await versuch(() => api("POST", `/api/geraete/${g.id}/zusammenfuehren`, { ziel }));
      for (const id of wahl) await api("POST", `/api/geraete/${id}/zusammenfuehren`, { ziel }).catch(() => {});
      hinweis("Zum Inventar-Gerät hinzugefügt");
      return true;
    }
    return versuch(() => api("POST", `/api/geraete/${g.id}/status`, { status: "aktiv", ...lesenForm(kopf), ...th.werte(), zusammen: [...wahl] }),
      wahl.size ? `Übernommen, ${wahl.size} zusammengeführt` : "Übernommen");
  }, "p"]], true);
}

async function zusammenDialog(g, alleG) {
  const f = h("div", {}, h("p", { class: "leise" }, `Die Schnittstellen von „${g.name}“ (${g.ip} ${g.mac}) wandern zum gewählten Gerät, „${g.name}“ wird entfernt.`),
    feld("Ziel-Gerät", auswahl("ziel", alleG.map(x => [x.id, `${x.name}${x.ip ? " – " + x.ip : ""}`]), "")));
  return dialog("Zusammenführen", f, [["Abbrechen", null], ["Zusammenführen", () => versuch(() => api("POST", `/api/geraete/${g.id}/zusammenfuehren`, lesenForm(f)), "Zusammengeführt"), "p"]]);
}

// ------------------------------------------------------------------ Netzwerke
ANSICHT.netzwerke = { titel: "Netzwerke", async zeigen(main) {
  const laden = async () => {
    const d = await api("GET", "/api/netzwerke");
    leeren(main,
      h("div", { class: "leiste" }, h("span", { class: "leise klein-t" }, `Container-Adressen: ${d.eigene.join(", ") || "?"} · Scanner: ${d.nmap ? "nmap" : "Ping (nmap fehlt)"} · OPNsense: ${d.opnsense ? "eingerichtet" : "nicht eingerichtet"}`),
        h("span", { class: "rechts" },
          d.opnsense && darf("operator") ? h("button", { onclick: async () => { const r = await versuch(() => api("POST", "/api/opnsense/abgleich")); hinweis(`OPNsense: ${r.gefunden} bekannt, ${r.neu} neu`); laden(); } }, "OPNsense abgleichen") : null,
          darf("admin") ? h("button", { class: "p", onclick: () => netzDialog(null, d).then(r => r && laden()) }, "Netzwerk hinzufügen") : null)),
      h("div", { class: "karte" }, tabelle([
        { t: "Name", w: n => h("div", { class: "zwei-zeilen" }, h("b", {}, n.name), n.beschreibung ? h("small", {}, n.beschreibung) : null) },
        { t: "Netz", w: n => h("div", { class: "zwei-zeilen" }, h("span", { class: "mono" }, n.cidr), n.vlan ? h("small", {}, "VLAN " + n.vlan) : null) },
        { t: "Erreichbar", w: n => n.direkt ? marke("direkt (L2)", "ok") : marke("geroutet") },
        { t: "Geräte", w: n => n.geraete, z: 1 },
        { t: "Scan", w: n => n.scan_aktiv ? `alle ${n.scan_intervall} min · ${n.scan_methode}` : marke("aus") },
        { t: "WoL", w: n => (WOL_METHODEN.find(x => x[0] === n.wol_methode) || [, n.wol_methode])[1] + (n.opnsense_interface ? ` (${n.opnsense_interface})` : "") },
        { t: "Letzter Scan", w: n => h("div", { class: "zwei-zeilen" }, n.laeuft ? marke("läuft …", "akz") : vorZeit(n.letzter_scan), h("small", {}, n.scan_status)) },
        { t: "", w: n => darf("operator") ? h("button", { class: "klein", disabled: n.laeuft, onclick: async e => {
            e.target.disabled = true; e.target.textContent = "Scannt …";
            try { const r = await api("POST", `/api/netzwerke/${n.id}/scan`); hinweis(`${n.name}: ${r.status}`, !r.ok); } catch (er) { hinweis(er.message, true); }
            laden(); } }, "Jetzt scannen") : null },
      ], d.netzwerke, { klick: darf("admin") ? n => netzDialog(n, d).then(r => r && laden()) : null, leer: "Noch kein Netzwerk. Für jedes Netz/VLAN einen Eintrag anlegen – im eigenen Netz findet der Scan auch MAC-Adressen, in anderen Netzen helfen ARP/DHCP der OPNsense." })));
  };
  await laden();
  alle(20, laden);
} };

async function netzDialog(n, d) {
  n = n || { scan_aktiv: true, scan_intervall: 15, scan_methode: "auto", wol_methode: "auto" };
  let ifs = {};
  if (d.opnsense) try { ifs = (await api("GET", "/api/opnsense/interfaces")).interfaces || {}; } catch { /* egal */ }
  const ifFeld = Object.keys(ifs).length ? auswahl("opnsense_interface", [["", "–"], ...Object.entries(ifs).map(([k, v]) => [k, `${k} – ${v}`])], n.opnsense_interface)
    : eingabe("opnsense_interface", n.opnsense_interface, { placeholder: "lan, opt1, …" });
  const f = h("div", {},
    h("div", { class: "raster" },
      feld("Name *", eingabe("name", n.name, { placeholder: "z. B. LAN, IoT, Server" })),
      feld("Netz (CIDR) *", eingabe("cidr", n.cidr, { placeholder: "192.168.10.0/24" })),
      feld("VLAN", eingabe("vlan", n.vlan ?? "", { type: "number" })),
      feld("Beschreibung", eingabe("beschreibung", n.beschreibung))),
    h("h4", {}, "Scan"),
    h("div", { class: "raster" },
      h("div", {}, haken("Automatisch scannen", n.scan_aktiv, null, "scan_aktiv").el),
      feld("Alle … Minuten", eingabe("scan_intervall", n.scan_intervall, { type: "number", min: 1 })),
      feld("Methode", auswahl("scan_methode", [["auto", "Automatisch (nmap/Ping + OPNsense)"], ["nmap", "nmap"], ["ping", "Ping"], ["opnsense", "Nur OPNsense (ARP/DHCP)"]], n.scan_methode))),
    h("h4", {}, "Wake-on-LAN"),
    h("div", { class: "raster" },
      feld("Weg", auswahl("wol_methode", WOL_METHODEN, n.wol_methode), "Automatisch: im eigenen Netz der Container, sonst die OPNsense"),
      feld("OPNsense-Schnittstelle", ifFeld, "für WoL über die OPNsense (Plugin os-wol)"),
      feld("Broadcast-Adresse", eingabe("wol_broadcast", n.wol_broadcast, { placeholder: "leer = aus dem Netz" }))));
  const kn = [["Abbrechen", null]];
  if (n.id) kn.push(["Löschen", async () => { if (!(await bestaetigen(`Netzwerk „${n.name}“ löschen? Geräte bleiben erhalten.`, "Löschen"))) return false; return versuch(() => api("DELETE", `/api/netzwerke/${n.id}`), "Gelöscht"); }, "gefahr"]);
  kn.push(["Speichern", () => versuch(() => api("POST", "/api/netzwerke", { ...lesenForm(f), id: n.id }), "Gespeichert"), "p"]);
  return dialog(n.id ? `Netzwerk „${n.name}“` : "Netzwerk hinzufügen", f, kn);
}

// ------------------------------------------------------------------ Ereignisse
ANSICHT.ereignisse = { titel: "Ereignisse", async zeigen(main, q) {
  let art = q.get("art") || "";
  const laden = async () => {
    const d = await api("GET", `/api/ereignisse?art=${art}&grenze=500`);
    leeren(main, h("div", { class: "leiste" }, auswahl("", [["", "Alle Arten"], ...Object.entries(ART_NAMEN)], art, { onchange: e => { art = e.target.value; laden(); } })),
      h("div", { class: "karte" }, ereignisListe(d.ereignisse, true)));
  };
  await laden();
  alle(30, laden);
} };
