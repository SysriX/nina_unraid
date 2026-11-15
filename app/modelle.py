"""NINA – Datenbank-Modelle (immer der NEUESTE Stand des Schemas).

Wichtig für Erweiterungen: Jede Änderung hier braucht einen passenden Schritt in migrationen.py
(Version hochzählen), damit vorhandene Datenbanken beim Update mitziehen. Neue Tabellen legt
migrationen.ausfuehren() automatisch an; neue Spalten/Indizes müssen als Schritt eingetragen werden.
Für frei definierbare Zusatzangaben ohne Schema-Änderung gibt es Geraet.extra (JSON).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from kern import jetzt


class Basis(DeclarativeBase):
    pass


class Schema(Basis):
    __tablename__ = "ni_schema"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version: Mapped[int] = mapped_column(Integer)
    programm: Mapped[str] = mapped_column(String(32), default="")
    aktualisiert: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=jetzt)


class Benutzer(Basis):
    __tablename__ = "ni_benutzer"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    anzeigename: Mapped[str] = mapped_column(String(255), default="")
    rolle: Mapped[str] = mapped_column(String(16), default="leser")           # admin | operator | leser
    pw_hash: Mapped[str] = mapped_column(String(255), default="")
    aktiv: Mapped[bool] = mapped_column(Boolean, default=True)
    erstellt: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=jetzt)
    letzte_anmeldung: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Sitzung(Basis):
    __tablename__ = "ni_sitzung"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    benutzer_id: Mapped[int] = mapped_column(ForeignKey("ni_benutzer.id", ondelete="CASCADE"))
    ablauf: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ip: Mapped[str] = mapped_column(String(64), default="")


class ApiSchluessel(Basis):
    """Zugang für Home Assistant und andere Programme (Bearer-Token, nur der Hash wird gespeichert)."""
    __tablename__ = "ni_api_schluessel"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    anfang: Mapped[str] = mapped_column(String(12), default="")        # erste Zeichen zum Wiedererkennen
    rolle: Mapped[str] = mapped_column(String(16), default="operator")
    erstellt: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=jetzt)
    zuletzt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    zuletzt_ip: Mapped[str] = mapped_column(String(64), default="")


class Einstellung(Basis):
    __tablename__ = "ni_einstellung"
    schluessel: Mapped[str] = mapped_column(String(64), primary_key=True)
    wert: Mapped[Any] = mapped_column(JSON)


class Protokoll(Basis):
    __tablename__ = "ni_protokoll"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    zeit: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=jetzt, index=True)
    benutzer: Mapped[str] = mapped_column(String(128), default="")
    ip: Mapped[str] = mapped_column(String(64), default="")
    bereich: Mapped[str] = mapped_column(String(32), default="")
    aktion: Mapped[str] = mapped_column(String(128), default="")
    ziel: Mapped[str] = mapped_column(String(512), default="")
    ok: Mapped[bool] = mapped_column(Boolean, default=True)
    details: Mapped[str] = mapped_column(Text, default="")


class Netzwerk(Basis):
    __tablename__ = "ni_netzwerk"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    cidr: Mapped[str] = mapped_column(String(64))                       # z. B. 192.168.10.0/24
    vlan: Mapped[int | None] = mapped_column(Integer, nullable=True)
    beschreibung: Mapped[str] = mapped_column(Text, default="")
    scan_aktiv: Mapped[bool] = mapped_column(Boolean, default=True)
    scan_intervall: Mapped[int] = mapped_column(Integer, default=15)    # Minuten
    scan_methode: Mapped[str] = mapped_column(String(16), default="auto")  # auto | nmap | ping | opnsense
    opnsense_interface: Mapped[str] = mapped_column(String(32), default="")  # z. B. lan, opt1 (WoL über OPNsense)
    wol_methode: Mapped[str] = mapped_column(String(16), default="auto")   # auto | container | opnsense | beide
    wol_broadcast: Mapped[str] = mapped_column(String(64), default="")      # leer = aus CIDR
    letzter_scan: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    scan_status: Mapped[str] = mapped_column(String(512), default="")
    erstellt: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=jetzt)


class Geraet(Basis):
    __tablename__ = "ni_geraet"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), index=True)
    typ: Mapped[str] = mapped_column(String(32), default="unbekannt")
    hersteller: Mapped[str] = mapped_column(String(128), default="")
    modell: Mapped[str] = mapped_column(String(128), default="")
    seriennummer: Mapped[str] = mapped_column(String(128), default="")
    inventarnummer: Mapped[str] = mapped_column(String(64), default="")
    betriebssystem: Mapped[str] = mapped_column(String(128), default="")
    standort: Mapped[str] = mapped_column(String(128), default="")
    raum: Mapped[str] = mapped_column(String(32), default="")           # Kürzel für HA (wz, bu, …) – leer = haus
    benutzer: Mapped[str] = mapped_column(String(128), default="")      # wer an dem Gerät arbeitet
    notizen: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[list] = mapped_column(JSON, default=list)
    extra: Mapped[dict] = mapped_column(JSON, default=dict)             # Zusatzfelder (frei definierbar)
    status: Mapped[str] = mapped_column(String(16), default="aktiv", index=True)  # aktiv | neu | ignoriert | ausgemustert
    quelle: Mapped[str] = mapped_column(String(16), default="manuell")  # manuell | scan | opnsense | agent
    ueberwachen: Mapped[bool] = mapped_column(Boolean, default=False)   # regelmäßig anpingen
    ha_import: Mapped[bool] = mapped_column(Boolean, default=True)      # an Home Assistant geben
    wol_aktiv: Mapped[bool] = mapped_column(Boolean, default=False)
    wol_methode: Mapped[str] = mapped_column(String(16), default="")    # leer = wie Netzwerk
    wol_mac: Mapped[str] = mapped_column(String(17), default="")        # leer = MAC der primären Schnittstelle (ab Schema 3)
    online: Mapped[bool] = mapped_column(Boolean, default=False)
    zuletzt_online: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    erstellt: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=jetzt)
    geaendert: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=jetzt)


class Schnittstelle(Basis):
    __tablename__ = "ni_schnittstelle"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    geraet_id: Mapped[int] = mapped_column(ForeignKey("ni_geraet.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(64), default="")
    mac: Mapped[str] = mapped_column(String(17), default="", index=True)  # aa:bb:cc:dd:ee:ff
    ip: Mapped[str] = mapped_column(String(64), default="", index=True)
    art: Mapped[str] = mapped_column(String(16), default="")            # rj45 | 10g | wifi | virtuell | "" (ab Schema 4)
    art_fest: Mapped[bool] = mapped_column(Boolean, default=False)      # von Hand gesetzt – Erkennung überschreibt nicht
    beschreibung: Mapped[str] = mapped_column(String(255), default="")  # Adapter laut HASS.Agent, z. B. „Intel 82599 10 Gigabit“
    hostname: Mapped[str] = mapped_column(String(255), default="")
    mac_hersteller: Mapped[str] = mapped_column(String(128), default="")
    netzwerk_id: Mapped[int | None] = mapped_column(ForeignKey("ni_netzwerk.id", ondelete="SET NULL"), nullable=True)
    primaer: Mapped[bool] = mapped_column(Boolean, default=False)
    feste_ip: Mapped[bool] = mapped_column(Boolean, default=False)
    quelle: Mapped[str] = mapped_column(String(16), default="manuell")
    online: Mapped[bool] = mapped_column(Boolean, default=False)
    erstmals: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=jetzt)
    zuletzt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Agent(Basis):
    """Ein HASS.Agent (über MQTT-Discovery erkannt)."""
    __tablename__ = "ni_agent"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kennung: Mapped[str] = mapped_column(String(191), unique=True)   # device.identifiers[0]
    name: Mapped[str] = mapped_column(String(128))
    hersteller: Mapped[str] = mapped_column(String(128), default="")
    modell: Mapped[str] = mapped_column(String(255), default="")
    version: Mapped[str] = mapped_column(String(64), default="")
    verfuegbar_topic: Mapped[str] = mapped_column(String(255), default="")
    online: Mapped[bool] = mapped_column(Boolean, default=False)
    zuletzt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    geraet_id: Mapped[int | None] = mapped_column(ForeignKey("ni_geraet.id", ondelete="SET NULL"), nullable=True)
    erstellt: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=jetzt)


class AgentWert(Basis):
    __tablename__ = "ni_agent_wert"
    __table_args__ = (UniqueConstraint("agent_id", "schluessel", name="uq_agent_wert"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("ni_agent.id", ondelete="CASCADE"), index=True)
    schluessel: Mapped[str] = mapped_column(String(160))          # object_id aus dem Discovery-Topic
    name: Mapped[str] = mapped_column(String(255), default="")
    art: Mapped[str] = mapped_column(String(16), default="sensor")  # sensor | binary_sensor
    wert: Mapped[str] = mapped_column(Text, default="")
    attribute: Mapped[dict] = mapped_column(JSON, default=dict)
    einheit: Mapped[str] = mapped_column(String(32), default="")
    device_class: Mapped[str] = mapped_column(String(48), default="")
    state_class: Mapped[str] = mapped_column(String(32), default="")
    icon: Mapped[str] = mapped_column(String(64), default="")
    state_topic: Mapped[str] = mapped_column(String(255), default="")
    value_template: Mapped[str] = mapped_column(String(255), default="")
    geaendert: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AgentBefehl(Basis):
    __tablename__ = "ni_agent_befehl"
    __table_args__ = (UniqueConstraint("agent_id", "schluessel", name="uq_agent_befehl"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("ni_agent.id", ondelete="CASCADE"), index=True)
    schluessel: Mapped[str] = mapped_column(String(160))
    name: Mapped[str] = mapped_column(String(255), default="")
    art: Mapped[str] = mapped_column(String(16), default="button")  # button | switch | lock
    command_topic: Mapped[str] = mapped_column(String(255), default="")
    payload_an: Mapped[str] = mapped_column(String(64), default="")
    payload_aus: Mapped[str] = mapped_column(String(64), default="")
    state_topic: Mapped[str] = mapped_column(String(255), default="")
    zustand: Mapped[str] = mapped_column(String(64), default="")
    icon: Mapped[str] = mapped_column(String(64), default="")


class Muster(Basis):
    """Namensmuster zur Erkennung von Sensoren und Befehlen (Einheit, Geräteklasse, Symbol, Import)."""
    __tablename__ = "ni_muster"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    reihenfolge: Mapped[int] = mapped_column(Integer, default=100)
    ziel: Mapped[str] = mapped_column(String(16), default="sensor")   # sensor | befehl
    muster: Mapped[str] = mapped_column(String(255))                   # Platzhalter * ? oder re:<Regex>
    kategorie: Mapped[str] = mapped_column(String(32), default="")
    bezeichnung: Mapped[str] = mapped_column(String(128), default="")
    einheit: Mapped[str] = mapped_column(String(32), default="")
    device_class: Mapped[str] = mapped_column(String(48), default="")
    state_class: Mapped[str] = mapped_column(String(32), default="")
    icon: Mapped[str] = mapped_column(String(64), default="")
    importieren: Mapped[bool] = mapped_column(Boolean, default=True)
    gefahr: Mapped[bool] = mapped_column(Boolean, default=False)
    aktiv: Mapped[bool] = mapped_column(Boolean, default=True)


class Ereignis(Basis):
    __tablename__ = "ni_ereignis"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    zeit: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=jetzt, index=True)
    geraet_id: Mapped[int | None] = mapped_column(ForeignKey("ni_geraet.id", ondelete="CASCADE"), nullable=True, index=True)
    art: Mapped[str] = mapped_column(String(24), default="")    # neu | online | offline | ip | wol | befehl | agent
    text: Mapped[str] = mapped_column(String(512), default="")


# ------------------------------------------------------------------ ab Schema 2: Kataloge
class Typ(Basis):
    """Gerätetyp (Katalog, in der Oberfläche pflegbar). Ein Gerät kann mehrere Typen haben."""
    __tablename__ = "ni_typ"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    schluessel: Mapped[str] = mapped_column(String(32), unique=True)    # z. B. server, vm (auch für Home Assistant)
    name: Mapped[str] = mapped_column(String(64))
    symbol: Mapped[str] = mapped_column(String(16), default="")         # Zeichen/Emoji in der Oberfläche
    icon: Mapped[str] = mapped_column(String(64), default="")           # mdi-Symbol für Home Assistant
    reihenfolge: Mapped[int] = mapped_column(Integer, default=100)
    system: Mapped[bool] = mapped_column(Boolean, default=False)        # nicht löschbar (unbekannt)


class GeraetTyp(Basis):
    __tablename__ = "ni_geraet_typ"
    geraet_id: Mapped[int] = mapped_column(ForeignKey("ni_geraet.id", ondelete="CASCADE"), primary_key=True)
    typ_id: Mapped[int] = mapped_column(ForeignKey("ni_typ.id", ondelete="CASCADE"), primary_key=True)


class Hersteller(Basis):
    __tablename__ = "ni_hersteller"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True)
    webseite: Mapped[str] = mapped_column(String(255), default="")
    notizen: Mapped[str] = mapped_column(Text, default="")
    erstellt: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=jetzt)


class Modell(Basis):
    __tablename__ = "ni_modell"
    __table_args__ = (UniqueConstraint("hersteller_id", "name", name="uq_modell"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    hersteller_id: Mapped[int] = mapped_column(ForeignKey("ni_hersteller.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(128))
    typ_id: Mapped[int | None] = mapped_column(ForeignKey("ni_typ.id", ondelete="SET NULL"), nullable=True)
    notizen: Mapped[str] = mapped_column(Text, default="")
    erstellt: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=jetzt)


# ------------------------------------------------------------------ ab Schema 3: Nicht zugewiesene Funde
class Fund(Basis):
    """Ein noch nicht zugewiesener Fund (Netzwerk-Scan, OPNsense, HASS.Agent, …).

    Erst beim Zuweisen entsteht daraus ein Gerät (ni_geraet) mit Schnittstelle bzw. Agent-Verknüpfung;
    der Fund wird dabei gelöscht. „Zuweisung aufheben“ macht aus einem Gerät wieder Funde.
    """
    __tablename__ = "ni_fund"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    schluessel: Mapped[str] = mapped_column(String(160), unique=True)   # mac:aa:bb… | ip:<netz>:<ip> | agent:<id> | geraet:<n>
    name: Mapped[str] = mapped_column(String(128), default="")
    hostname: Mapped[str] = mapped_column(String(255), default="")
    ip: Mapped[str] = mapped_column(String(64), default="", index=True)
    mac: Mapped[str] = mapped_column(String(17), default="", index=True)
    mac_hersteller: Mapped[str] = mapped_column(String(128), default="")
    hersteller: Mapped[str] = mapped_column(String(128), default="")
    modell: Mapped[str] = mapped_column(String(128), default="")
    typ: Mapped[str] = mapped_column(String(32), default="unbekannt")    # Vermutung
    netzwerk_id: Mapped[int | None] = mapped_column(ForeignKey("ni_netzwerk.id", ondelete="SET NULL"), nullable=True)
    agent_id: Mapped[int | None] = mapped_column(ForeignKey("ni_agent.id", ondelete="CASCADE"), nullable=True, index=True)
    quellen: Mapped[list] = mapped_column(JSON, default=list)            # ["scan", "opnsense", "agent", "manuell"]
    online: Mapped[bool] = mapped_column(Boolean, default=False)
    ignoriert: Mapped[bool] = mapped_column(Boolean, default=False)
    daten: Mapped[dict] = mapped_column(JSON, default=dict)               # z. B. {"vorher": {…}} nach „Zuweisung aufheben“
    erstmals: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=jetzt)
    zuletzt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
