"""Kataloge: Gerätetypen, Hersteller und Modelle (in der Oberfläche pflegbar).

Geräte speichern Haupttyp, Hersteller und Modell weiterhin als Text (geraet.typ / .hersteller / .modell);
die weiteren Typen eines Geräts stehen in ni_geraet_typ. Der Katalog liefert die Auswahllisten und wächst
automatisch mit: Was ein Gerät beim Übernehmen/Speichern an Hersteller/Modell bekommt, wird eingetragen.
Umbenennen im Katalog benennt die Angaben an allen Geräten mit um.
"""
from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import delete, func, select, update

from kern import protokoll, sitzung
from modelle import Geraet, GeraetTyp, Hersteller, Modell, Typ
from zugang import ADMIN, LESER, OPERATOR, client_ip

router = APIRouter(prefix="/api/katalog")

# Schlüssel, Name, Symbol, mdi-Icon für Home Assistant
STANDARD_TYPEN = [
    ("pc", "PC", "🖥", "mdi:desktop-tower-monitor"), ("laptop", "Laptop", "💻", "mdi:laptop"),
    ("server", "Server", "🗄", "mdi:server"), ("vm", "Virtuelle Maschine", "◫", "mdi:server-network"),
    ("nas", "NAS", "🗃", "mdi:nas"), ("netzwerk", "Switch / Access-Point", "⇄", "mdi:switch"),
    ("router", "Router / Firewall", "🛡", "mdi:router-network"), ("drucker", "Drucker", "🖨", "mdi:printer"),
    ("telefon", "Telefon / Smartphone", "📱", "mdi:cellphone"), ("tablet", "Tablet", "▭", "mdi:tablet"),
    ("tv", "TV / Medien", "📺", "mdi:television"), ("kamera", "Kamera", "📷", "mdi:cctv"),
    ("iot", "IoT / Smart Home", "💡", "mdi:home-automation"), ("konsole", "Spielkonsole", "🎮", "mdi:gamepad-variant"),
    ("sonstiges", "Sonstiges", "◇", "mdi:devices"), ("unbekannt", "Unbekannt", "?", "mdi:help-network"),
]


def standard_typen_anlegen(s) -> None:
    for i, (k, n, sym, ic) in enumerate(STANDARD_TYPEN):
        s.add(Typ(schluessel=k, name=n, symbol=sym, icon=ic, reihenfolge=(i + 1) * 10, system=(k == "unbekannt")))


# ------------------------------------------------------------------ Hilfen für andere Module
def typen(s) -> list[Typ]:
    return list(s.scalars(select(Typ).order_by(Typ.reihenfolge, Typ.name)))


def typ_ids(s) -> dict[str, int]:
    return {t.schluessel: t.id for t in s.scalars(select(Typ))}


def gueltiger_typ(s, key: str) -> str:
    return key if s.scalar(select(Typ.id).where(Typ.schluessel == key)) else "unbekannt"


def geraet_typen(s, gid: int) -> list[str]:
    return [k for k, in s.execute(select(Typ.schluessel).join(GeraetTyp, GeraetTyp.typ_id == Typ.id)
                                  .where(GeraetTyp.geraet_id == gid).order_by(Typ.reihenfolge))]


def alle_geraet_typen(s) -> dict[int, list[str]]:
    out: dict[int, list[str]] = {}
    for gid, k in s.execute(select(GeraetTyp.geraet_id, Typ.schluessel).join(Typ, Typ.id == GeraetTyp.typ_id).order_by(Typ.reihenfolge)):
        out.setdefault(gid, []).append(k)
    return out


def geraet_typen_setzen(s, g: Geraet, keys: list[str] | None) -> None:
    """Haupttyp (g.typ) ist immer dabei; weitere Typen aus keys."""
    ids = typ_ids(s)
    if g.typ not in ids:
        g.typ = "unbekannt"
    wahl = [g.typ] + [k for k in (keys or []) if k in ids and k != g.typ]
    s.execute(delete(GeraetTyp).where(GeraetTyp.geraet_id == g.id))
    for k in dict.fromkeys(wahl):
        s.add(GeraetTyp(geraet_id=g.id, typ_id=ids[k]))


def eintragen(s, hersteller: str, modell: str, typ_key: str = "") -> None:
    """Hersteller/Modell eines Geräts in den Katalog übernehmen (wenn noch nicht vorhanden)."""
    hersteller, modell = (hersteller or "").strip(), (modell or "").strip()
    if not hersteller:
        return
    h = s.scalars(select(Hersteller).where(func.lower(Hersteller.name) == hersteller.lower())).first()
    if not h:
        h = Hersteller(name=hersteller[:128])
        s.add(h)
        s.flush()
    if modell:
        m = s.scalars(select(Modell).where(Modell.hersteller_id == h.id, func.lower(Modell.name) == modell.lower())).first()
        if not m:
            tid = typ_ids(s).get(typ_key) if typ_key and typ_key != "unbekannt" else None
            s.add(Modell(hersteller_id=h.id, name=modell[:128], typ_id=tid))


# ------------------------------------------------------------------ Lesen
def _typ_json(s, t: Typ) -> dict:
    return {"id": t.id, "schluessel": t.schluessel, "name": t.name, "symbol": t.symbol, "icon": t.icon,
            "reihenfolge": t.reihenfolge, "system": t.system,
            "geraete": s.scalar(select(func.count()).select_from(GeraetTyp).where(GeraetTyp.typ_id == t.id)) or 0}


@router.get("")
def katalog(ich: dict = Depends(LESER)):
    """Alles für Auswahllisten: Typen, Hersteller mit Modellen (Modell mit Typ-Schlüssel)."""
    with sitzung() as s:
        tmap = {t.id: t.schluessel for t in s.scalars(select(Typ))}
        anzahl_h = dict(s.execute(select(Geraet.hersteller, func.count(Geraet.id)).group_by(Geraet.hersteller)).all())
        anzahl_m = dict(((h, m), n) for h, m, n in s.execute(select(Geraet.hersteller, Geraet.modell, func.count(Geraet.id))
                                                               .group_by(Geraet.hersteller, Geraet.modell)).all())
        hs = []
        for h in s.scalars(select(Hersteller).order_by(func.lower(Hersteller.name))):
            ms = [{"id": m.id, "name": m.name, "typ": tmap.get(m.typ_id, ""), "notizen": m.notizen,
                   "geraete": anzahl_m.get((h.name, m.name), 0)}
                  for m in s.scalars(select(Modell).where(Modell.hersteller_id == h.id).order_by(func.lower(Modell.name)))]
            hs.append({"id": h.id, "name": h.name, "webseite": h.webseite, "notizen": h.notizen, "modelle": ms,
                       "geraete": anzahl_h.get(h.name, 0)})
        return {"typen": [_typ_json(s, t) for t in typen(s)], "hersteller": hs}


# ------------------------------------------------------------------ Typen
@router.post("/typen")
async def typ_speichern(req: Request, ich: dict = Depends(ADMIN)):
    d = await req.json()
    name = str(d.get("name") or "").strip()[:64]
    if not name:
        raise HTTPException(400, "Name fehlt")
    with sitzung() as s:
        if d.get("id"):
            t = s.get(Typ, int(d["id"]))
            if not t:
                raise LookupError("Typ gibt es nicht")
        else:
            key = str(d.get("schluessel") or "").strip().lower() or re.sub(r"[^a-z0-9]+", "_", name.lower()
                                                                             .replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")).strip("_")
            if not re.fullmatch(r"[a-z0-9_]{1,32}", key):
                raise HTTPException(400, "Schlüssel: 1–32 Zeichen, nur a–z, 0–9 und _")
            if s.scalar(select(Typ.id).where(Typ.schluessel == key)):
                raise HTTPException(400, f"Den Schlüssel „{key}“ gibt es schon")
            t = Typ(schluessel=key)
            s.add(t)
        t.name = name
        t.symbol = str(d.get("symbol") or "")[:16]
        t.icon = str(d.get("icon") or "").strip()[:64]
        t.reihenfolge = int(d.get("reihenfolge") or 100)
        s.flush()
        out = _typ_json(s, t)
    protokoll(ich["name"], "katalog", "Typ gespeichert", name, ip=client_ip(req))
    return out


@router.delete("/typen/{tid}")
def typ_loeschen(tid: int, req: Request, ich: dict = Depends(ADMIN)):
    with sitzung() as s:
        t = s.get(Typ, tid)
        if not t:
            raise LookupError("Typ gibt es nicht")
        if t.system:
            raise HTTPException(400, "Dieser Typ wird gebraucht und kann nicht gelöscht werden")
        # Geräte mit diesem Haupttyp bekommen ihren nächsten Typ (sonst „unbekannt“)
        for g in s.scalars(select(Geraet).where(Geraet.typ == t.schluessel)):
            rest = [k for k in geraet_typen(s, g.id) if k != t.schluessel]
            g.typ = rest[0] if rest else "unbekannt"
        s.execute(delete(GeraetTyp).where(GeraetTyp.typ_id == tid))
        s.flush()
        for g in s.scalars(select(Geraet).where(Geraet.typ == "unbekannt")):
            if not geraet_typen(s, g.id):
                geraet_typen_setzen(s, g, [])
        name = t.name
        s.delete(t)
    protokoll(ich["name"], "katalog", "Typ gelöscht", name, ip=client_ip(req))
    return {"ok": True}


# ------------------------------------------------------------------ Hersteller / Modelle
@router.post("/hersteller")
async def hersteller_speichern(req: Request, ich: dict = Depends(OPERATOR)):
    d = await req.json()
    name = str(d.get("name") or "").strip()[:128]
    if not name:
        raise HTTPException(400, "Name fehlt")
    with sitzung() as s:
        doppelt = s.scalars(select(Hersteller).where(func.lower(Hersteller.name) == name.lower(),
                                                     Hersteller.id != int(d.get("id") or 0))).first()
        if doppelt:
            raise HTTPException(400, f"Den Hersteller „{doppelt.name}“ gibt es schon")
        if d.get("id"):
            h = s.get(Hersteller, int(d["id"]))
            if not h:
                raise LookupError("Hersteller gibt es nicht")
            if h.name != name:      # an allen Geräten mit umbenennen
                s.execute(update(Geraet).where(Geraet.hersteller == h.name).values(hersteller=name))
        else:
            h = Hersteller()
            s.add(h)
        h.name, h.webseite, h.notizen = name, str(d.get("webseite") or "")[:255], str(d.get("notizen") or "")
        s.flush()
        hid = h.id
    protokoll(ich["name"], "katalog", "Hersteller gespeichert", name, ip=client_ip(req))
    return {"ok": True, "id": hid}


@router.delete("/hersteller/{hid}")
def hersteller_loeschen(hid: int, req: Request, ich: dict = Depends(ADMIN)):
    with sitzung() as s:
        h = s.get(Hersteller, hid)
        if not h:
            raise LookupError("Hersteller gibt es nicht")
        name = h.name
        s.delete(h)            # Modelle fallen mit weg; Geräte behalten ihren Text
    protokoll(ich["name"], "katalog", "Hersteller gelöscht", name, ip=client_ip(req))
    return {"ok": True}


@router.post("/modelle")
async def modell_speichern(req: Request, ich: dict = Depends(OPERATOR)):
    d = await req.json()
    name = str(d.get("name") or "").strip()[:128]
    if not name:
        raise HTTPException(400, "Modell fehlt")
    with sitzung() as s:
        h = s.get(Hersteller, int(d.get("hersteller_id") or 0))
        if not h:
            raise HTTPException(400, "Hersteller wählen")
        doppelt = s.scalars(select(Modell).where(Modell.hersteller_id == h.id, func.lower(Modell.name) == name.lower(),
                                                 Modell.id != int(d.get("id") or 0))).first()
        if doppelt:
            raise HTTPException(400, f"Das Modell „{doppelt.name}“ gibt es bei {h.name} schon")
        if d.get("id"):
            m = s.get(Modell, int(d["id"]))
            if not m:
                raise LookupError("Modell gibt es nicht")
            alt_h = s.get(Hersteller, m.hersteller_id)
            if alt_h and (m.name != name or alt_h.id != h.id):
                s.execute(update(Geraet).where(Geraet.hersteller == alt_h.name, Geraet.modell == m.name)
                          .values(hersteller=h.name, modell=name))
        else:
            m = None
        tid = typ_ids(s).get(str(d.get("typ") or ""))
        if m is None:
            m = Modell()
            s.add(m)
        m.hersteller_id, m.name, m.typ_id, m.notizen = h.id, name, tid, str(d.get("notizen") or "")
        s.flush()
        mid = m.id
    protokoll(ich["name"], "katalog", "Modell gespeichert", f"{h.name} {name}", ip=client_ip(req))
    return {"ok": True, "id": mid}


@router.delete("/modelle/{mid}")
def modell_loeschen(mid: int, req: Request, ich: dict = Depends(ADMIN)):
    with sitzung() as s:
        m = s.get(Modell, mid)
        if not m:
            raise LookupError("Modell gibt es nicht")
        name = m.name
        s.delete(m)
    protokoll(ich["name"], "katalog", "Modell gelöscht", name, ip=client_ip(req))
    return {"ok": True}


@router.post("/aus-inventar")
def aus_inventar(req: Request, ich: dict = Depends(OPERATOR)):
    """Hersteller/Modelle aller Geräte im Inventar in den Katalog übernehmen."""
    with sitzung() as s:
        vorher = (s.scalar(select(func.count(Hersteller.id))) or 0) + (s.scalar(select(func.count(Modell.id))) or 0)
        for g in s.scalars(select(Geraet).where(Geraet.status == "aktiv", Geraet.hersteller != "")):
            eintragen(s, g.hersteller, g.modell, g.typ)
        s.flush()
        nachher = (s.scalar(select(func.count(Hersteller.id))) or 0) + (s.scalar(select(func.count(Modell.id))) or 0)
    protokoll(ich["name"], "katalog", "aus Inventar übernommen", ip=client_ip(req))
    return {"ok": True, "neu": nachher - vorher}
