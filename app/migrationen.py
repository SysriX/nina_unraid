"""NetInventory – Schema-Versionen und Aktualisierung der Datenbank.

So funktioniert ein Update des Containers:
  * Neue, leere Datenbank: alle Tabellen nach modelle.py anlegen, Version = AKTUELL.
  * Vorhandene Datenbank mit kleinerer Version: SQLite wird vorher als Kopie gesichert
    (<datei>.vor-v<alt>), dann laufen die SCHRITTE alt+1 … AKTUELL nacheinander, jeder in einer Transaktion.
  * Datenbank NEUER als dieses Programm (z. B. nach Rückkehr zu einem älteren Image): Start wird verweigert,
    damit nichts kaputtgeschrieben wird.
  * Danach legt create_all() noch fehlende (neue) Tabellen an.

Neuen Schritt hinzufügen (Beispiel Version 2):
    AKTUELL = 2
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

AKTUELL = 1
SCHRITTE: dict[int, tuple[str, Callable[[Connection], None]]] = {}


# ------------------------------------------------------------------ Hilfen für Schritte
def spalte_neu(c: Connection, tabelle: str, spalte: Column) -> None:
    if spalte.name in {x["name"] for x in inspect(c).get_columns(tabelle)}:
        return
    typ = spalte.type.compile(dialect=c.dialect)
    sql = f"ALTER TABLE {tabelle} ADD COLUMN {spalte.name} {typ}"
    if spalte.server_default is not None:
        sql += f" DEFAULT {spalte.server_default.arg}"
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
    from modelle import Muster
    import muster
    with Session(engine) as s:
        if s.scalar(select(Muster.id).limit(1)) is None:
            for m in muster.STANDARD:
                s.add(Muster(**m))
            s.commit()
            kern.log(f"{len(muster.STANDARD)} Standard-Erkennungsmuster angelegt")
