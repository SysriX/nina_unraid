"""NINA – Schema-Versionen und Aktualisierung der Datenbank.

So funktioniert ein Update des Containers:
  * Neue, leere Datenbank: alle Tabellen nach modelle.py anlegen, Version = AKTUELL.
  * Vorhandene Datenbank mit kleinerer Version: SQLite wird vorher als Kopie gesichert
    (<datei>.vor-v<alt>), dann laufen die SCHRITTE alt+1 … AKTUELL nacheinander, jeder in einer Transaktion.
  * Datenbank NEUER als dieses Programm (z. B. nach Rückkehr zu einem älteren Image): Start wird verweigert,
    damit nichts kaputtgeschrieben wird.
  * Danach legt create_all() noch fehlende (neue) Tabellen an.

Neuen Schritt hinzufügen (Beispiel Version 2):
    AKTUELL = 4
    def _v2(c):
        spalte_neu(c, "ni_geraet", Column("garantie_bis", Date, nullable=True))
    SCHRITTE[2] = ("Garantie-Datum für Geräte", _v2)
und die Spalte auch in modelle.py eintragen. Die Hilfen sind idempotent (prüfen vorher, ob es die Spalte schon gibt).
"""
from __future__ import annotations

import os
import shutil
from typing import Callable

from sqlalchemy import Column, Index, inspect, select, text
from sqlalchemy.engine import Connection
from sqlalchemy.schema import CreateIndex

import kern
from modelle import Basis, Schema

AKTUELL = 4
SCHRITTE: dict[int, tuple[str, Callable[[Connection], None]]] = {}


# ------------------------------------------------------------------ Hilfen für Schritte
def spalte_neu(c: Connection, tabelle: str, spalte: Column) -> None:
    if spalte.name in {x["name"] for x in inspect(c).get_columns(tabelle)}:
        return
    typ = spalte.type.compile(dialect=c.dialect)
    sql = f"ALTER TABLE {tabelle} ADD COLUMN {spalte.name} {typ}"
    if spalte.server_default is not None:
        arg = spalte.server_default.arg
        sql += f" DEFAULT {arg}" if (not isinstance(arg, str) or arg.isdigit()) else f" DEFAULT '{arg}'"
    if not spalte.nullable and spalte.server_default is not None:
        sql += " NOT NULL"
    c.execute(text(sql))


def index_neu(c: Connection, tabelle: str, name: str, *spalten: str, unique: bool = False) -> None:
    if name in {x["name"] for x in inspect(c).get_indexes(tabelle)}:
        return
    from sqlalchemy import MetaData, Table
    t = Table(tabelle, MetaData(), autoload_with=c)
    c.execute(CreateIndex(Index(name, *[t.c[s] for s in spalten], unique=unique)))


def spalte_weg(c: Connection, tabelle: str, spalte: str) -> None:
    if spalte in {x["name"] for x in inspect(c).get_columns(tabelle)}:
        c.execute(text(f"ALTER TABLE {tabelle} DROP COLUMN {spalte}"))


# ------------------------------------------------------------------ Schritte
def _v2(c: Connection) -> None:
    """Kataloge: Gerätetypen (mehrere je Gerät), Hersteller, Modelle."""
    from sqlalchemy.orm import Session
    import katalog
    from modelle import Einstellung, Geraet, GeraetTyp, Hersteller, Modell, Typ
    for t in (Typ, GeraetTyp, Hersteller, Modell):
        t.__table__.create(c, checkfirst=True)
    s = Session(bind=c)
    if s.scalar(select(Typ.id).limit(1)) is None:
        katalog.standard_typen_anlegen(s)
        s.flush()
    ids = {t.schluessel: t.id for t in s.scalars(select(Typ))}
    for g in s.scalars(select(Geraet)):
        if g.typ not in ids:
            g.typ = "unbekannt"
        if s.get(GeraetTyp, (g.id, ids[g.typ])) is None:
            s.add(GeraetTyp(geraet_id=g.id, typ_id=ids[g.typ]))
    s.flush()
    for g in s.scalars(select(Geraet).where(Geraet.status == "aktiv", Geraet.hersteller != "")):
        katalog.eintragen(s, g.hersteller, g.modell, g.typ)
    # Neu gefundene Geräte kommen nicht mehr direkt ins Inventar
    e = s.get(Einstellung, "allgemein")
    if e and isinstance(e.wert, dict) and e.wert.get("neue_geraete") == "anlegen":
        e.wert = {**e.wert, "neue_geraete": "pruefen"}
    s.flush()
    s.close()


SCHRITTE[2] = ("Kataloge: Gerätetypen, Hersteller, Modelle", _v2)


def _v3(c: Connection) -> None:
    """Nicht zugewiesene Funde in eigener Tabelle: Geräte mit Status neu/ignoriert und Agenten ohne Gerät → ni_fund."""
    from sqlalchemy.orm import Session
    import funde
    from modelle import Agent, Fund, Geraet
    Fund.__table__.create(c, checkfirst=True)
    from sqlalchemy import String
    spalte_neu(c, "ni_geraet", Column("wol_mac", String(17), server_default="", nullable=False))
    s = Session(bind=c)
    for g in list(s.scalars(select(Geraet).where(Geraet.status.in_(("neu", "ignoriert"))))):
        ignoriert = g.status == "ignoriert"
        vorher_ids = {f.id for f in s.scalars(select(Fund))}
        funde.geraet_aufheben(s, g)
        for f in s.scalars(select(Fund)):
            if f.id not in vorher_ids:
                f.ignoriert = ignoriert
                f.daten = {}          # war nie zugewiesen – keine „vorher“-Angaben
    for a in s.scalars(select(Agent).where(Agent.geraet_id.is_(None))):
        funde.agent_fund(s, a)
    s.flush()
    s.close()


SCHRITTE[3] = ("Nicht zugewiesene Funde in eigener Tabelle (ni_fund), WoL-MAC je Gerät", _v3)


def _v4(c: Connection) -> None:
    """Art der Netzwerkschnittstelle (RJ45, 10G, WLAN, virtuell) – für die automatische WoL-MAC."""
    from sqlalchemy import Boolean, String
    import netz
    spalte_neu(c, "ni_schnittstelle", Column("art", String(16), server_default="", nullable=False))
    spalte_neu(c, "ni_schnittstelle", Column("art_fest", Boolean, server_default="0", nullable=False))
    spalte_neu(c, "ni_schnittstelle", Column("beschreibung", String(255), server_default="", nullable=False))
    for sid, name, hst, mac in c.execute(text("SELECT id, name, mac_hersteller, mac FROM ni_schnittstelle")).all():
        art = netz.nic_art(name or "", hst or "", mac or "")
        if art:
            c.execute(text("UPDATE ni_schnittstelle SET art = :a WHERE id = :i"), {"a": art, "i": sid})


SCHRITTE[4] = ("Art der Netzwerkschnittstelle (RJ45/10G/WLAN/virtuell)", _v4)


# ------------------------------------------------------------------ Ablauf
def _version_lesen(c: Connection) -> int | None:
    if not inspect(c).has_table("ni_schema"):
        return None
    v = c.execute(select(Schema.version).where(Schema.id == 1)).scalar()
    return int(v) if v is not None else None


def _version_setzen(c: Connection, v: int) -> None:
    if c.execute(select(Schema.id).where(Schema.id == 1)).scalar() is None:
        c.execute(Schema.__table__.insert().values(id=1, version=v, programm=kern.VERSION, aktualisiert=kern.jetzt()))
    else:
        c.execute(Schema.__table__.update().where(Schema.id == 1).values(version=v, programm=kern.VERSION,
                                                                          aktualisiert=kern.jetzt()))


def _sqlite_sichern(url: str, alt: int) -> None:
    pfad = url.split("sqlite:///", 1)[-1]
    if os.path.exists(pfad):
        ziel = f"{pfad}.vor-v{alt}"
        shutil.copy2(pfad, ziel)
        kern.log("Datenbank gesichert:", ziel)


def ausfuehren(engine, url: str) -> int:
    with engine.connect() as c:
        v = _version_lesen(c)
    if v is None:
        with engine.begin() as c:
            Basis.metadata.create_all(c)
            _version_setzen(c, AKTUELL)
        kern.log(f"Datenbank neu angelegt (Schema {AKTUELL})")
        _standard_daten(engine)
        return AKTUELL
    if v > AKTUELL:
        raise RuntimeError(f"Die Datenbank hat Schema {v}, dieses Programm kennt nur {AKTUELL}. "
                           "Bitte das neuere Image verwenden (oder die Sicherung zurückspielen).")
    if v < AKTUELL:
        if url.startswith("sqlite"):
            _sqlite_sichern(url, v)
        else:
            kern.log("Hinweis: MariaDB wird aktualisiert – vorher eine Sicherung (mysqldump) ist empfehlenswert.")
        for n in range(v + 1, AKTUELL + 1):
            titel, fn = SCHRITTE[n]
            kern.log(f"Datenbank-Update auf Schema {n}: {titel}")
            with engine.begin() as c:
                fn(c)
                _version_setzen(c, n)
    with engine.begin() as c:
        Basis.metadata.create_all(c)     # neue Tabellen
    _standard_daten(engine)
    return AKTUELL


def schema_info() -> dict:
    with kern.engine().connect() as c:
        v = _version_lesen(c)
        zeile = c.execute(select(Schema.programm, Schema.aktualisiert).where(Schema.id == 1)).first()
    return {"schema": v, "programm_schema": AKTUELL, "zuletzt_von": zeile[0] if zeile else "",
            "aktualisiert": kern.iso(zeile[1]) if zeile else None,
            "schritte": [{"version": k, "titel": t} for k, (t, _) in sorted(SCHRITTE.items())]}


def _standard_daten(engine) -> None:
    """Füllt leere Tabellen mit Vorgaben (z. B. Erkennungs-Muster). Läuft bei jedem Start, ändert nie Vorhandenes."""
    from sqlalchemy.orm import Session
    from modelle import Muster, Typ
    import katalog
    import muster
    with Session(engine) as s:
        if s.scalar(select(Typ.id).limit(1)) is None:
            katalog.standard_typen_anlegen(s)
            s.commit()
        if s.scalar(select(Muster.id).limit(1)) is None:
            for m in muster.STANDARD:
                s.add(Muster(**m))
            s.commit()
            kern.log(f"{len(muster.STANDARD)} Standard-Erkennungsmuster angelegt")
