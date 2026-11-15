/* NINA – Ansichten: Agenten, Sensor-Erkennung, Einstellungen, Benutzer & API, Protokoll */
"use strict";

// ------------------------------------------------------------------ Agenten
ANSICHT.agenten = { titel: "HASS.Agent", async zeigen(main) {
  const laden = async () => {
    const d = await api("GET", "/api/agenten");
    const offen = d.agenten.filter(a => !a.geraet_id || a.geraet_status !== "aktiv").length;
    d.agenten = d.agenten.filter(a => a.geraet_id && a.geraet_status === "aktiv");   // nicht zugewiesene stehen unter Inventar › Nicht zugewiesen
    const m = d.mqtt;
    leeren(main,
      h("div", { class: "karte" }, h("h2", {}, "MQTT-Verbindung", m.verbunden ? marke("verbunden", "ok") : m.aktiv ? marke("getrennt", "bad") : marke("aus"),
        h("span", { class: "rechts" }, darf("admin") ? h("a", { href: "#einstellungen?tab=mqtt" }, h("button", { class: "klein" }, "Einstellungen")) : null)),
        h("p", { class: "leise", style: { margin: 0 } }, m.aktiv ? `${m.host} · ${m.status} · ${m.nachrichten} Nachrichten empfangen`
          : "Noch nicht eingerichtet. HASS.Agent schickt seine Sensoren und Befehle an den MQTT-Broker von Home Assistant (z. B. das Mosquitto-Add-on). NINA hört dort mit – unter Einstellungen › MQTT den Broker eintragen.")),
      offen ? h("div", { class: "karte" }, h("p", { style: { margin: 0 } }, `${offen} ${offen === 1 ? "Agent ist" : "Agenten sind"} noch keinem Gerät im Inventar zugewiesen – `,
        h("a", { href: "#neu" }, "unter „Nicht zugewiesen“ übernehmen"), ".")) : null,
      h("div", { class: "karte" }, h("h2", {}, `${d.agenten.length} zugewiesene Agenten`),
        tabelle([
          { t: "", w: a => punkt(a.online ? "ok" : "") },
          { t: "Name", w: a => h("div", { class: "zwei-zeilen" }, h("b", {}, a.name), h("small", {}, a.kennung)) },
          { t: "Version", w: a => a.version }, { t: "System", w: a => a.modell },
          { t: "Werte / Befehle", w: a => `${a.werte} / ${a.befehle}`, z: 1 },
          { t: "Gerät", w: a => h("a", { href: `#geraet?id=${a.geraet_id}` }, a.geraet) },
          { t: "Zuletzt", w: a => vorZeit(a.zuletzt) },
          { t: "", w: a => darf("admin") ? h("div", { class: "knopfreihe" },
            h("button", { class: "klein", onclick: () => verknuepfenDialog(a).then(r => r && laden()) }, "Verknüpfen"),
            h("button", { class: "klein gefahr", onclick: async () => { if (await bestaetigen(`Agent „${a.name}“ entfernen? Meldet er sich wieder, taucht er neu auf.`, "Entfernen")) { await versuch(() => api("DELETE", `/api/agenten/${a.id}`), "Entfernt"); laden(); } } }, "Entfernen")) : null },
        ], d.agenten, { leer: offen ? "Noch kein Agent zugewiesen." : "Noch kein HASS.Agent gefunden.", klick: a => a.geraet_id && (location.hash = `#geraet?id=${a.geraet_id}`) })));
  };
  await laden();
  alle(15, laden);
} };

async function verknuepfenDialog(a) {
  const geraete = (await api("GET", "/api/geraete?status=alle")).geraete;
  const f = h("div", {}, feld("Gerät", auswahl("geraet_id", [["", "– keines –"], ["neu", "Neues Gerät anlegen"], ...geraete.map(g => [g.id, `${g.name}${g.ip ? " – " + g.ip : ""}`])], a.geraet_id || "")));
  return dialog(`Agent „${a.name}“ verknüpfen`, f, [["Abbrechen", null], ["Speichern", () => {
    const v = lesenForm(f).geraet_id;
    return versuch(() => api("POST", `/api/agenten/${a.id}/verknuepfen`, v === "neu" ? { neu: true } : { geraet_id: v || null }), "Verknüpft");
  }, "p"]]);
}

// ------------------------------------------------------------------ Sensor-Erkennung
ANSICHT.muster = { titel: "HASS.Agent Sensor-Erkennung", async zeigen(main) {
  const [d] = await Promise.all([api("GET", "/api/muster"), mdiLaden().catch(() => {})]);
  const ziel = new URLSearchParams(location.hash.split("?")[1] || "").get("ziel") || "sensor";
  const liste = d.muster.filter(m => m.ziel === ziel);
  const bsp = d.beispiele.filter(b => b.ziel === ziel);
  leeren(main,
    h("p", { class: "leise" }, "Namensmuster ordnen die Sensoren und Befehle der HASS.Agents ein: Bezeichnung, Einheit, Geräteklasse und Symbol für Home Assistant – und ob sie überhaupt übernommen werden. ",
      "Das erste passende Muster (kleinste Reihenfolge) gewinnt. Platzhalter: * und ?, oder ein regulärer Ausdruck mit „re:“ davor. Der Gerätename vorne im Sensornamen wird ignoriert."),
    h("div", { class: "leiste" }, tabs([["sensor", "Sensoren"], ["befehl", "Befehle"]], ziel, k => { location.hash = `#muster?ziel=${k}`; }),
      h("span", { class: "rechts" }, darf("admin") ? [
        h("button", { onclick: async () => { if (await bestaetigen("Alle Muster auf die Vorgaben zurücksetzen? Eigene Änderungen gehen verloren.", "Zurücksetzen")) { await versuch(() => api("POST", "/api/muster/standard"), "Zurückgesetzt"); zeige(); } } }, "Vorgaben"),
        h("button", { class: "p", onclick: () => musterDialog({ ziel, reihenfolge: 100, importieren: true, aktiv: true }) }, "Muster hinzufügen")] : null)),
    h("div", { class: "zwei" },
      h("div", { class: "karte" }, h("h2", {}, "Muster"), tabelle([
        { t: "#", w: m => m.reihenfolge, z: 1 },
        { t: "Muster", w: m => h("span", { class: "mono" }, m.muster) },
        { t: "Bezeichnung", w: m => h("div", { class: "zwei-zeilen" }, m.bezeichnung || h("span", { class: "leise" }, "(Name des Sensors)"), m.kategorie ? h("small", {}, m.kategorie) : null) },
        ziel === "sensor" ? { t: "Einheit / Klasse", w: m => [m.einheit, m.device_class].filter(Boolean).join(" · ") } : { t: "Rückfrage", w: m => m.gefahr ? marke("ja", "warn") : "" },
        { t: "Symbol", w: m => h("span", { class: "status-zeile" }, mdiSvg(m.icon, 18), h("span", { class: "mono leise" }, m.icon)) },
        { t: "HA", w: m => m.importieren ? marke("ja", "ok") : marke("nein") },
        { t: "", w: m => m.aktiv ? "" : marke("aus") },
      ], liste, { klick: darf("admin") ? m => musterDialog(m) : null })),
      h("div", { class: "karte" }, h("h2", {}, "Vorhandene Werte der Agenten"), tabelle([
        { t: "Agent", w: b => b.agent }, { t: "Name", w: b => h("div", { class: "zwei-zeilen" }, b.name, h("small", {}, b.schluessel)) },
        { t: "Erkannt als", w: b => h("div", { class: "zwei-zeilen" }, b.treffer.bezeichnung || h("span", { class: "leise" }, "–"), h("small", {}, [b.treffer.kategorie, b.treffer.einheit].filter(Boolean).join(" · "))) },
        { t: "HA", w: b => b.treffer.importieren ? marke("ja", "ok") : marke("nein") },
      ], bsp, { leer: "Noch keine Agenten-Werte" }))));
} };

async function musterDialog(m) {
  const sensor = m.ziel === "sensor";
  const f = h("div", {},
    h("div", { class: "raster" },
      feld("Muster *", eingabe("muster", m.muster, { placeholder: "*cpu*  oder  re:^(cpu|prozessor)" })),
      feld("Reihenfolge", eingabe("reihenfolge", m.reihenfolge, { type: "number" })),
      feld("Bezeichnung", eingabe("bezeichnung", m.bezeichnung, { placeholder: "Anzeigename (leer = Name des Sensors)" })),
      feld("Kategorie", eingabe("kategorie", m.kategorie, { placeholder: sensor ? "cpu, speicher, benutzer …" : "shutdown, restart, lock …" }),
        sensor ? "„benutzer“ = angemeldeter Benutzer in der Geräteliste" : "Für Automationen: nina_inventory.command mit command: <kategorie>"),
      sensor ? feld("Einheit", eingabe("einheit", m.einheit, { placeholder: "%, °C, GB" })) : null,
      sensor ? feld("Geräteklasse (HA)", eingabe("device_class", m.device_class, { placeholder: "temperature, timestamp, battery …" })) : null,
      sensor ? feld("state_class (HA)", auswahl("state_class", ["", "measurement", "total", "total_increasing"], m.state_class)) : null,
      feld("Symbol (Home Assistant)", symbolFeld("icon", m.icon, "mdi"))),
    h("div", { class: "raster" },
      haken("An Home Assistant geben", m.importieren, null, "importieren").el,
      sensor ? null : haken("Vor dem Ausführen nachfragen", m.gefahr, null, "gefahr").el,
      haken("Aktiv", m.aktiv, null, "aktiv").el));
  const kn = [["Abbrechen", null]];
  if (m.id) kn.push(["Löschen", () => versuch(() => api("DELETE", `/api/muster/${m.id}`), "Gelöscht"), "gefahr"]);
  kn.push(["Speichern", () => versuch(() => api("POST", "/api/muster", { ...lesenForm(f), ziel: m.ziel, id: m.id }), "Gespeichert"), "p"]);
  if (await dialog(m.id ? "Muster bearbeiten" : "Muster hinzufügen", f, kn)) zeige();
}

// ------------------------------------------------------------------ Einstellungen
ANSICHT.einstellungen = { titel: "Einstellungen", async zeigen(main, q) {
  const tab = q.get("tab") || "allgemein";
  const e = await api("GET", "/api/einstellungen");
  const sys = await api("GET", "/api/system");
  const inhalt = { allgemein: () => allgemeinTab(e.allgemein), zeitplan: () => zeitplanTab(), mqtt: () => mqttTab(e.mqtt), opnsense: () => opnsenseTab(e.opnsense),
    sicherung: () => sicherungTab(sys) }[tab]();
  leeren(main, h("div", { class: "leiste" }, tabs([["allgemein", "Allgemein"], ["zeitplan", "Zeitplan"], ["mqtt", "MQTT / HASS.Agent"], ["opnsense", "OPNsense"], ["sicherung", "Datenbank & Sicherung"]], tab,
    k => { location.hash = `#einstellungen?tab=${k}`; })), inhalt);
} };

function allgemeinTab(a) {
  const felder = (a.zusatzfelder || []).map(z => ({ ...z }));
  const zf = h("div");
  const zfZeichnen = () => leeren(zf, felder.map((z, i) => h("div", { class: "leiste" },
    eingabe("", z.titel, { placeholder: "Titel", oninput: ev => { z.titel = ev.target.value; if (!z.fest) z.name = ev.target.value.toLowerCase().replace(/ä/g, "ae").replace(/ö/g, "oe").replace(/ü/g, "ue").replace(/ß/g, "ss").replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, ""); } }),
    auswahl("", [["text", "Text"], ["zahl", "Zahl"], ["datum", "Datum"], ["auswahl", "Auswahl"]], z.art, { onchange: ev => { z.art = ev.target.value; zfZeichnen(); } }),
    z.art === "auswahl" ? eingabe("", z.optionen, { placeholder: "Werte, kommagetrennt", oninput: ev => { z.optionen = ev.target.value; } }) : null,
    h("button", { class: "klein gefahr", onclick: () => { felder.splice(i, 1); zfZeichnen(); } }, "✕"))),
    h("button", { class: "klein", onclick: () => { felder.push({ titel: "", name: "", art: "text", optionen: "" }); zfZeichnen(); } }, "Feld hinzufügen"));
  felder.forEach(z => (z.fest = true));
  zfZeichnen();
  const f = h("div", {},
    h("div", { class: "raster" },
      feld("Name dieser Installation", eingabe("name", a.name), "erscheint in Home Assistant"),
      feld("Neu gefundene Geräte", auswahl("neue_geraete", [["pruefen", "Unter „Nicht zugewiesen“ aufführen"], ["nein", "Nicht anlegen (nur Bekannte aktualisieren)"]], a.neue_geraete), "Ins Inventar kommt ein Gerät nur, wenn es übernommen wird"),
      feld("Überwachte Geräte anpingen alle … s", eingabe("ueberwachen_intervall", a.ueberwachen_intervall, { type: "number", min: 15 })),
      feld("WoL-Port", auswahl("wol_port", [["9", "9 (Standard)"], ["7", "7"]], a.wol_port)),
      feld("Ereignisse aufheben (Tage)", eingabe("ereignisse_tage", a.ereignisse_tage, { type: "number", min: 7 }))),
    haken("Für neue HASS.Agents gleich einen Fund anlegen", a.agent_geraete_anlegen, "Sonst steht der Agent ohne Gerät unter „Nicht zugewiesen“ (Übernehmen legt es dann an); mit gleichnamigem Inventar-Gerät wird immer verknüpft", "agent_geraete_anlegen").el);
  return h("div", {}, h("div", { class: "karte" }, h("h2", {}, "Allgemein"), f),
    h("div", { class: "karte" }, h("h2", {}, "Zusatzfelder für Geräte"), h("p", { class: "leise klein-t" }, "Eigene Angaben je Gerät (z. B. Garantie bis, Kostenstelle, Lieferant) – ohne Datenbank-Umbau, gespeichert im Feld „extra“ und auch an Home Assistant übergeben."), zf),
    h("div", { class: "leiste" }, h("span", { class: "rechts" }, h("button", { class: "p", onclick: async () => {
      await versuch(() => api("POST", "/api/einstellungen/allgemein", { ...lesenForm(f), zusatzfelder: felder.filter(z => z.titel && z.name) }), "Gespeichert");
      META = await api("GET", "/api/meta"); zeige();
    } }, "Speichern"))));
}

function mqttTab(m) {
  const f = h("div", {},
    haken("HASS.Agent über MQTT einbinden", m.aktiv, null, "aktiv").el,
    h("div", { class: "raster" },
      feld("Broker (Host/IP)", eingabe("host", m.host, { placeholder: "<IP_HomeAssistant>" }), "der Broker, den HASS.Agent und Home Assistant nutzen"),
      feld("Port", eingabe("port", m.port, { type: "number" })),
      feld("Benutzer", eingabe("benutzer", m.benutzer, { autocomplete: "off" })),
      feld("Passwort", eingabe("passwort", "", { type: "password", autocomplete: "new-password", placeholder: m.passwort_gesetzt ? "•••••• (unverändert)" : "" })),
      feld("Discovery-Präfix", eingabe("praefix", m.praefix)),
      feld("Client-ID", eingabe("client_id", m.client_id, { placeholder: "leer = nina-<id>" })),
      feld("Erkennung (Regex)", eingabe("erkennung", m.erkennung), "trifft auf identifiers/Hersteller/Modell/Version des Discovery-Geräts")),
    h("div", { class: "raster" }, haken("TLS", m.tls, null, "tls").el, haken("Zertifikat prüfen", m.tls_pruefen, null, "tls_pruefen").el));
  return h("div", {}, h("div", { class: "karte" }, h("h2", {}, "MQTT / HASS.Agent"),
    h("p", { class: "leise klein-t" }, "Im Mosquitto-Add-on von Home Assistant am besten einen eigenen Benutzer für NINA anlegen. Unterstützt den klassischen HASS.Agent (MQTT-Discovery) und HASS.Agent .NET10 (hass.agent/…). NINA liest mit und sendet Befehle wie Home Assistant – dessen eigene Integration bleibt unberührt."),
    f), h("div", { class: "leiste" }, h("span", { class: "rechts" }, h("button", { class: "p", onclick: async () => {
      const r = await versuch(() => api("POST", "/api/einstellungen/mqtt", lesenForm(f)));
      hinweis("Gespeichert – " + r.status); setTimeout(zeige, 2500);
    } }, "Speichern & verbinden"))));
}

function opnsenseTab(o) {
  const f = h("div", {},
    haken("OPNsense nutzen", o.aktiv, "ARP-Tabelle + DHCP-Leases aller Netze (MAC-Adressen auch aus fremden VLANs) und Wake-on-LAN in andere Netze", "aktiv").el,
    h("div", { class: "raster" },
      feld("Adresse", eingabe("url", o.url, { placeholder: "https://<IP_OPNsense>" })),
      feld("API-Key", eingabe("key", "", { autocomplete: "off", placeholder: o.key_gesetzt ? "•••••• (unverändert)" : "" })),
      feld("API-Secret", eingabe("secret", "", { type: "password", autocomplete: "new-password", placeholder: o.secret_gesetzt ? "•••••• (unverändert)" : "" }))),
    h("div", { class: "raster" }, haken("Zertifikat prüfen", o.tls_pruefen, "aus bei selbstsigniertem Zertifikat", "tls_pruefen").el,
      haken("ARP-Tabelle lesen", o.arp, null, "arp").el, haken("DHCP-Leases lesen", o.dhcp, null, "dhcp").el));
  const erg = h("div");
  return h("div", {}, h("div", { class: "karte" }, h("h2", {}, "OPNsense"),
    h("p", { class: "leise klein-t" }, "System › Zugang › Benutzer: einen Benutzer nur für die API anlegen, Rechte „Diagnostics: ARP Table“, „Status: DHCP leases“ (bzw. Kea/Dnsmasq), „Services: Wake on LAN“ und „Interfaces“; dann API-Schlüssel erzeugen. Für WoL das Plugin os-wol installieren und bei jedem Netzwerk die Schnittstelle (lan, opt1 …) eintragen."),
    f, erg), h("div", { class: "leiste" }, h("span", { class: "rechts" },
      h("button", { onclick: async () => {
        await versuch(() => api("POST", "/api/einstellungen/opnsense", lesenForm(f)));
        const r = await versuch(() => api("POST", "/api/opnsense/testen"));
        leeren(erg, h("p", { class: "marke ok" }, `Verbindung klappt – ${r.hosts} Geräte bekannt`), h("pre", {}, Object.entries(r.interfaces || {}).map(([k, v]) => `${k}: ${v}`).join("\n")));
      } }, "Speichern & testen"),
      h("button", { class: "p", onclick: () => versuch(() => api("POST", "/api/einstellungen/opnsense", lesenForm(f)), "Gespeichert") }, "Speichern"))));
}

function sicherungTab(s) {
  const datei = h("input", { type: "file", accept: ".json,application/json" });
  return h("div", {},
    h("div", { class: "karte" }, h("h2", {}, "Datenbank"),
      h("dl", { class: "daten" }, [["Programm", s.version], ["Datenbank", s.db.typ === "mariadb" ? `MariaDB ${s.db.benutzer}@${s.db.host}:${s.db.port}/${s.db.name}` : `SQLite (/config/${s.db.datei})`],
        ["Schema-Version", `${s.schema} (Programm kennt ${s.programm_schema})`], ["Zuletzt aktualisiert", `${datum(s.aktualisiert)} von ${s.zuletzt_von}`],
        ["Instanz-ID", s.instanz], ["mDNS", s.mdns], ["MQTT", s.mqtt], ["nmap", s.nmap ? "vorhanden" : "fehlt – Ping-Scan"], ["Adressen", s.adressen.join(", ")]]
        .map(([k, v]) => [h("dt", {}, k), h("dd", {}, v)])),
      h("p", { class: "leise klein-t" }, "Beim Start eines neueren Containers wird das Schema automatisch hochgezogen (SQLite wird vorher als <datei>.vor-v<alt> kopiert). Ein älteres Image startet nicht mit einer neueren Datenbank – so geht nichts kaputt.")),
    h("div", { class: "karte" }, h("h2", {}, "Sicherung"),
      h("p", { class: "leise klein-t" }, "Export: Kataloge (Typen, Hersteller, Modelle), Netzwerke, Geräte, Schnittstellen, Erkennungs-Muster und allgemeine Einstellungen als JSON. Zugangsdaten (MQTT, OPNsense), Benutzer und API-Schlüssel sind nicht enthalten."),
      h("div", { class: "knopfreihe" },
        h("button", { class: "p", onclick: async () => {
          const r = await versuch(() => api("GET", "/api/sicherung", undefined, { roh: true }));
          const b = await r.blob(); const a = h("a", { href: URL.createObjectURL(b), download: (r.headers.get("content-disposition") || "").split('"')[1] || "nina.json" });
          document.body.append(a); a.click(); a.remove();
        } }, "Sicherung herunterladen")),
      h("h4", {}, "Wiederherstellen"), h("div", { class: "leiste" }, datei, h("button", { class: "gefahr", onclick: async () => {
        if (!datei.files[0]) return hinweis("Erst eine Datei wählen", true);
        let d; try { d = JSON.parse(await datei.files[0].text()); } catch { return hinweis("Keine gültige JSON-Datei", true); }
        if (!(await bestaetigen(`Kataloge, Netzwerke, Geräte, Schnittstellen und Muster durch die Sicherung vom ${datum(d.erstellt)} ersetzen?`, "Ersetzen"))) return;
        const r = await versuch(() => api("POST", "/api/sicherung", d));
        hinweis(`Wiederhergestellt: ${r.geraete} Geräte, ${r.netzwerke} Netzwerke`);
      } }, "Einspielen"))));
}

// ------------------------------------------------------------------ Benutzer & API-Schlüssel
ANSICHT.benutzer = { titel: "Benutzer & API", async zeigen(main) {
  const [b, k, sys] = await Promise.all([api("GET", "/api/benutzer"), api("GET", "/api/schluessel"), api("GET", "/api/system")]);
  leeren(main,
    h("div", { class: "karte" }, h("h2", {}, "Benutzer", h("span", { class: "rechts" }, h("button", { class: "p klein", onclick: () => benutzerDialog() }, "Benutzer anlegen"))),
      tabelle([{ t: "Name", w: x => h("div", { class: "zwei-zeilen" }, h("b", {}, x.name), x.anzeigename ? h("small", {}, x.anzeigename) : null) },
        { t: "Rolle", w: x => marke(x.rolle, "akz") }, { t: "", w: x => x.aktiv ? "" : marke("gesperrt", "bad") },
        { t: "Letzte Anmeldung", w: x => datum(x.letzte_anmeldung) }], b.benutzer, { klick: x => benutzerDialog(x) }),
      h("p", { class: "leise klein-t" }, "leser: nur ansehen · operator: wecken, Befehle, Scans, Geräte bearbeiten · admin: alles")),
    h("div", { class: "karte" }, h("h2", {}, "API-Schlüssel (Home Assistant)", h("span", { class: "rechts" }, h("button", { class: "p klein", onclick: schluesselDialog }, "Schlüssel erzeugen"))),
      h("p", { class: "leise klein-t" }, `Home Assistant findet NINA automatisch (mDNS: ${sys.mdns}). Beim Hinzufügen der Integration „NINA“ fragt sie nach einem dieser Schlüssel. Adresse für die manuelle Einrichtung: ${location.host}`),
      tabelle([{ t: "Name", w: x => x.name }, { t: "Beginnt mit", w: x => h("span", { class: "mono" }, x.anfang + "…") }, { t: "Rolle", w: x => marke(x.rolle) },
        { t: "Zuletzt benutzt", w: x => x.zuletzt ? `${vorZeit(x.zuletzt)} (${x.zuletzt_ip})` : "nie" },
        { t: "", w: x => h("button", { class: "klein gefahr", onclick: async () => { if (await bestaetigen(`Schlüssel „${x.name}“ löschen? Programme damit verlieren den Zugang.`, "Löschen")) { await versuch(() => api("DELETE", `/api/schluessel/${x.id}`), "Gelöscht"); zeige(); } } }, "Löschen") }],
      k.schluessel, { leer: "Noch kein Schlüssel" })));
} };

async function benutzerDialog(b = null) {
  const f = h("div", { class: "raster" },
    b ? null : feld("Benutzername *", eingabe("name", "")),
    feld("Anzeigename", eingabe("anzeigename", b?.anzeigename)),
    feld("Rolle", auswahl("rolle", [["leser", "leser"], ["operator", "operator"], ["admin", "admin"]], b?.rolle || "leser")),
    pwFeld("passwort", b ? "Neues Passwort (leer = unverändert)" : "Passwort *", "mindestens 10 Zeichen"),
    h("div", {}, haken("Aktiv", b ? b.aktiv : true, null, "aktiv").el));
  const kn = [["Abbrechen", null]];
  if (b) kn.push(["Löschen", async () => { if (!(await bestaetigen(`Benutzer „${b.name}“ löschen?`, "Löschen"))) return false; return versuch(() => api("DELETE", `/api/benutzer/${b.id}`), "Gelöscht"); }, "gefahr"]);
  kn.push(["Speichern", () => versuch(() => api("POST", "/api/benutzer", { ...lesenForm(f), id: b?.id }), "Gespeichert"), "p"]);
  if (await dialog(b ? `Benutzer „${b.name}“` : "Benutzer anlegen", f, kn)) zeige();
}

async function schluesselDialog() {
  const f = h("div", { class: "raster" }, feld("Name", eingabe("name", "Home Assistant")),
    feld("Rolle", auswahl("rolle", [["operator", "operator (lesen + wecken/Befehle)"], ["leser", "leser (nur lesen)"]], "operator")));
  const r = await dialog("API-Schlüssel erzeugen", f, [["Abbrechen", null], ["Erzeugen", () => versuch(() => api("POST", "/api/schluessel", lesenForm(f))), "p"]]);
  if (!r) return;
  await dialog("Neuer API-Schlüssel", h("div", {}, h("p", {}, "Der Schlüssel wird nur jetzt angezeigt – in Home Assistant bei der Integration eintragen:"),
    h("pre", {}, r.token), h("button", { onclick: () => kopieren(r.token) }, "Kopieren")));
  zeige();
}

// ------------------------------------------------------------------ Protokoll
ANSICHT.protokoll = { titel: "Protokoll", async zeigen(main) {
  const d = await api("GET", "/api/protokoll?grenze=500");
  leeren(main, h("div", { class: "karte" }, tabelle([
    { t: "Zeit", w: p => datum(p.zeit) }, { t: "Benutzer", w: p => p.benutzer }, { t: "Bereich", w: p => p.bereich },
    { t: "Aktion", w: p => [p.ok ? "" : punkt("bad"), " ", p.aktion] }, { t: "Ziel", w: p => p.ziel },
    { t: "Details", w: p => h("span", { class: "leise klein-t" }, (p.details || "").slice(0, 160)) }, { t: "IP", w: p => p.ip },
  ], d.eintraege, { leer: "Noch keine Einträge" })));
} };

// ------------------------------------------------------------------ Zeitplan
const TAGE = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"];

function zeitplanTab() {
  const box = h("div", {}, h("div", { class: "leer" }, "Lädt …"));
  let d = null;
  const statusEls = {};
  const statusZeile = q => {
    const z = d.zustand[q];
    return h("div", { class: "status-zeile klein-t" },
      z.laeuft ? [punkt("warn"), "läuft gerade …"] : z.ok === null ? [punkt(""), "noch nicht gelaufen"] : [punkt(z.ok ? "ok" : "bad"), `zuletzt ${vorZeit(z.zuletzt)} (${z.dauer} s)`],
      z.naechster && d.zeitplan[q].aktiv ? h("span", { class: "leise" }, `· nächster Lauf ${z.im_fenster ? datum(z.naechster) : "im nächsten Zeitfenster"}`) : null,
      !d.zeitplan[q].aktiv ? marke("aus") : !z.im_fenster ? marke("außerhalb des Zeitfensters", "warn") : null,
      z.ergebnis ? h("div", { class: "leise", style: { flexBasis: "100%" } }, z.ergebnis) : null);
  };
  const zeichneStatus = () => { for (const q of Object.keys(statusEls)) leeren(statusEls[q], statusZeile(q)); };
  const fenster = (c, mitIntervall) => {
    const tage = new Set(c.tage || []);
    const el = h("div", {},
      h("div", { class: "raster" },
        h("div", {}, haken("Automatisch ausführen", c.aktiv, null, "aktiv").el),
        mitIntervall ? feld("Alle … Minuten", eingabe("intervall", c.intervall, { type: "number", min: 1 })) : null,
        feld("Von", eingabe("von", c.von, { type: "time" }), "leer = ganztägig"),
        feld("Bis", eingabe("bis", c.bis, { type: "time" }), "über Mitternacht möglich, z. B. 22:00–06:00")),
      h("div", { class: "feld" }, h("span", {}, "Tage"), h("div", { class: "chips" }, TAGE.map((t, i) => h("label", { class: "chip" + (tage.has(i) ? " an" : "") },
        h("input", { type: "checkbox", checked: tage.has(i), "data-tag": i, onchange: e => e.target.parentNode.classList.toggle("an", e.target.checked) }), t))),
        h("small", {}, "keiner gewählt = jeden Tag")));
    el.werte = () => ({ ...lesenForm(el), tage: [...el.querySelectorAll("input[data-tag]")].filter(i => i.checked).map(i => +i.dataset.tag) });
    return el;
  };
  const karte = (q, inhalt, hilfe) => {
    statusEls[q] = h("div", { style: { margin: "-4px 0 12px" } });
    return h("div", { class: "karte" },
      h("h2", {}, d.zustand[q].titel, h("span", { class: "rechts" }, darf("operator") ? h("button", { class: "klein", onclick: async e => {
        e.target.disabled = true; e.target.textContent = "Läuft …";
        try { const r = await api("POST", `/api/zeitplan/${q}/jetzt`); hinweis(`${d.zustand[q].titel}: ${r.ergebnis}`, !r.ok); }
        catch (er) { hinweis(er.message, true); }
        await laden(true); e.target.disabled = false; e.target.textContent = "Jetzt ausführen";
      } }, "Jetzt ausführen") : null)),
      statusEls[q], h("p", { class: "leise klein-t", style: { marginTop: 0 } }, hilfe), inhalt);
  };
  const laden = async (nurStatus) => {
    d = await api("GET", "/api/zeitplan");
    if (nurStatus && Object.keys(statusEls).length) return zeichneStatus();
    const scan = fenster(d.zeitplan.scan, false), ops = fenster(d.zeitplan.opnsense, true), ag = fenster(d.zeitplan.agent, true);
    const agExtra = h("div", { class: "raster" },
      feld("Offline nach … Minuten ohne Daten", eingabe("offline_nach", d.zeitplan.agent.offline_nach, { type: "number", min: 2 }), "falls ein Agent sich nicht abmeldet (Absturz, Strom weg)"),
      h("div", {}, haken("Agenten um neue Meldung bitten", d.zeitplan.agent.neu_melden, "Sendet „online“ an <präfix>/status – klassischer HASS.Agent meldet dann Sensoren/Befehle neu (wie nach einem HA-Neustart). HASS.Agent .NET10 braucht das nicht.", "neu_melden").el));
    const netzWerte = new Map(d.netze.map(n => [n.id, { id: n.id, scan_aktiv: n.scan_aktiv, scan_intervall: n.scan_intervall }]));
    const netzTab = tabelle([
      { t: "An", w: n => h("input", { type: "checkbox", checked: n.scan_aktiv, onchange: e => { netzWerte.get(n.id).scan_aktiv = e.target.checked; } }) },
      { t: "Netzwerk", w: n => h("div", { class: "zwei-zeilen" }, h("b", {}, n.name), h("small", { class: "mono" }, n.cidr)) },
      { t: "Alle … min", w: n => h("input", { type: "number", min: 1, value: n.scan_intervall, style: { width: "80px" }, oninput: e => { netzWerte.get(n.id).scan_intervall = +e.target.value; } }) },
      { t: "Methode", w: n => n.scan_methode },
      { t: "Letzter Scan", w: n => h("div", { class: "zwei-zeilen" }, vorZeit(n.letzter_scan), h("small", {}, n.scan_status)) },
      { t: "Nächster", w: n => n.scan_aktiv && n.naechster ? datum(n.naechster) : "–" },
    ], d.netze, { leer: "Noch kein Netzwerk – unter Inventar › Netzwerke anlegen." });
    leeren(box,
      karte("scan", h("div", {}, scan, h("h4", {}, "Intervall je Netzwerk"), netzTab),
        "Ping/nmap-Scan der eingetragenen Netze (je Netz eigenes Intervall). Das Zeitfenster gilt für alle Netze."),
      karte("opnsense", ops, "ARP-Tabelle und DHCP-Leases der OPNsense über alle VLANs – findet auch Geräte in fremden Netzen samt MAC."),
      karte("agent", h("div", {}, ag, agExtra), "HASS.Agent-Werte kommen laufend per MQTT. Der Abgleich verknüpft Agenten mit Geräten, übernimmt gemeldete Adressen und setzt stumme Agenten offline."),
      h("div", { class: "leiste" }, h("span", { class: "leise klein-t" }, "Neue Funde aus allen Läufen landen unter Inventar › Nicht zugewiesen."),
        h("span", { class: "rechts" }, darf("admin") ? h("button", { class: "p", onclick: async () => {
          await versuch(() => api("POST", "/api/zeitplan", { scan: scan.werte(), opnsense: ops.werte(), agent: { ...ag.werte(), ...lesenForm(agExtra) }, netze: [...netzWerte.values()] }), "Zeitplan gespeichert");
          laden();
        } }, "Speichern") : null)));
    zeichneStatus();
  };
  laden().catch(e => leeren(box, h("div", { class: "karte" }, h("pre", {}, e.message))));
  alle(10, () => laden(true));
  return box;
}
