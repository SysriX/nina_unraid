# Entwicklung

## Aufbau

| Datei | Inhalt |
| --- | --- |
| `app/main.py` | FastAPI-Start, Schutz (CSRF-Header `X-NI`, Sicherheits-Header), Lebenszyklus |
| `app/kern.py` | Startkonfiguration, Fernet-Verschlüsselung, Datenbank-Verbindung, Einstellungen, Protokoll, `VERSION` |
| `app/modelle.py` | SQLAlchemy-Modelle – **immer der neueste Schema-Stand** |
| `app/migrationen.py` | Schema-Version (`AKTUELL`) und Schritte für vorhandene Datenbanken |
| `app/zugang.py` | Einrichtung, Anmeldung, Benutzer, API-Schlüssel, Rollen |
| `app/inventar.py` | Geräte, Schnittstellen, Netzwerke, Scan-Abgleich, Online-Status, Wake-on-LAN, Übernehmen/Zusammenführen |
| `app/katalog.py` | Kataloge: Gerätetypen (n:m zu Geräten), Hersteller, Modelle |
| `app/netz.py` | nmap/Ping-Scan, ARP, Erreichbarkeit, Magic Packet |
| `app/opnsense.py` | OPNsense-API (ARP, DHCP, WoL) |
| `app/agent.py` | HASS.Agent über MQTT (klassische Discovery und .NET10-Protokoll), Befehle |
| `app/muster.py` | Erkennungs-Muster für Sensoren/Befehle (Vorgaben in `STANDARD`) |
| `app/haapi.py` | API für Home Assistant `/api/ha/v1` |
| `app/zeitplan.py` | Zeitplan der automatischen Läufe (Scan, OPNsense, Agent-Abgleich), Zeitfenster, Laufstatus, „Jetzt ausführen“ |
| `app/dienste.py` | Hintergrund-Takt (Zeitplan, Ping-Überwachung, Agent-Werte speichern, Aufräumen), mDNS |
| `app/web/` | Oberfläche (Vanilla-JS, Stil wie MIRA) |

## Schema-Versionen

| Schema | Version | Inhalt |
| --- | --- | --- |
| 1 | 1.0.0 | Grundschema |
| 2 | 1.1.0 | `ni_typ`, `ni_geraet_typ`, `ni_hersteller`, `ni_modell`; Geräte mit ihrem Typ verknüpft, Hersteller/Modelle aus dem Inventar übernommen |

## Datenbank ändern

1. Spalte/Tabelle in `modelle.py` eintragen.
2. In `migrationen.py` `AKTUELL` um 1 erhöhen und einen Schritt anlegen:
   ```python
   AKTUELL = 2

   def _v2(c):
       spalte_neu(c, "ni_geraet", Column("garantie_bis", Date, nullable=True))
       index_neu(c, "ni_geraet", "ix_ni_geraet_garantie", "garantie_bis")

   SCHRITTE[2] = ("Garantie-Datum für Geräte", _v2)
   ```
   Neue **Tabellen** brauchen keinen Schritt (werden angelegt). Die Hilfen sind idempotent.
3. `VERSION` in `kern.py` erhöhen (der Workflow baut daraus die Image-Tags).

Neue Felder, die nur angezeigt/gespeichert werden sollen, gehen oft ohne Schema-Änderung über `Geraet.extra` (Zusatzfelder).

## Lokal starten

```bash
pip install -r requirements.txt
NINA_DATA=./daten NINA_PORT=18095 NINA_SETUP_TOKEN=TEST-TEST-TEST python app/main.py
```
Ohne nmap scannt NINA per Ping (bis /22).

## Icon-Liste (mdi)

`app/web/mdi.json` (Name, Pfad, Aliasse, Kategorien) wird aus dem npm-Paket @mdi/svg erzeugt:

```bash
npm pack @mdi/svg@7.4.47 && tar -xzf mdi-svg-7.4.47.tgz
node werkzeuge/mdi-liste.js package app/web/mdi.json
```
Deutsche Suchbegriffe stehen in `app/web/icons.js` (`MDI_DE`), die Zeichen/Emoji-Auswahl in `ZEICHEN`.

## Logo und Symbol

`werkzeuge/nina-logo.js` erzeugt `app/web/logo*.svg` (das dort erzeugte Schild-Icon wird nicht verwendet), `werkzeuge/nina-icon.js` das Icon (`icon-d.svg` eingesetzt: n als zentraler Knoten ohne Rahmen; a/b/c sind die Vorstufen) (Schrift **Dream MMA**, dafont, 100 % kostenlos, als Pfade; Aufbau wie MIRA, Akzent Blau). Braucht opentype.js und die TTF-Datei:

```bash
DREAM_BASIS=<ordner mit otjs/node_modules/opentype.js und dreammma-dl/x/Dream MMA.ttf> node werkzeuge/nina-logo.js app/web <pfad zu mira icon.svg>
```
Die Unterzeilen sind Text in Segoe UI Semibold (zum Messen wird `C:/Windows/Fonts/seguisb.ttf` gelesen).
