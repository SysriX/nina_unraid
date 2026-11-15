"""Einstellungen (Allgemein, MQTT/HASS.Agent, OPNsense), Erkennungs-Muster, Sicherung, Protokoll, System."""
from __future__ import annotations

import json
import re
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy import delete, select

import kern
import migrationen
import muster
import netz
import opnsense
from kern import iso, protokoll, sitzung
from modelle import (Agent, AgentBefehl, AgentWert, Ereignis, Geraet, GeraetTyp, Hersteller, Modell, Muster, Netzwerk,
                     Protokoll, Schnittstelle, Typ)
from zugang import ADMIN, LESER, OPERATOR, client_ip

router = APIRouter(prefix="/api")


# ------------------------------------------------------------------ Einstellungen
@router.get("/einstellungen")
def einstellungen(ich: dict = Depends(ADMIN)):
    import agent
    import inventar
    mq, mg = agent.konfig(), kern.geheim("mqtt")
    op = opnsense.konfig()
    return {"allgemein": inventar.allgemein(),
            "mqtt": {**mq, "benutzer": mg.get("benutzer", ""), "passwort_gesetzt": bool(mg.get("passwort"))},
            "opnsense": {"aktiv": op["aktiv"], "url": op["url"], "tls_pruefen": op["pruefen"], "arp": op["arp"], "dhcp": op["dhcp"],
                         "key_gesetzt": bool(op["key"]), "secret_gesetzt": bool(op["secret"])}}


@router.post("/einstellungen/allgemein")
async def allgemein_speichern(req: Request, ich: dict = Depends(ADMIN)):
    import inventar
    d = await req.json()
    a = inventar.allgemein()
    if d.get("neue_geraete", a["neue_geraete"]) not in ("pruefen", "nein"):
        raise HTTPException(400, "Unbekannte Wahl für neue Geräte")
    felder = []
    for f in d.get("zusatzfelder") or []:
        n = re.sub(r"[^a-z0-9_]", "", str(f.get("name", "")).lower())
        if n and f.get("titel"):
            felder.append({"name": n, "titel": str(f["titel"])[:64], "art": f.get("art") if f.get("art") in ("text", "zahl", "datum", "auswahl") else "text",
                           "optionen": str(f.get("optionen") or "")[:500]})
    a.update(name=str(d.get("name") or a["name"])[:64], neue_geraete=d.get("neue_geraete", a["neue_geraete"]),
             ueberwachen_intervall=max(15, min(3600, int(d.get("ueberwachen_intervall") or 60))),
             wol_port=int(d.get("wol_port") or 9) if int(d.get("wol_port") or 9) in (7, 9) else 9,
             agent_geraete_anlegen=bool(d.get("agent_geraete_anlegen", True)),
             ereignisse_tage=max(7, min(3650, int(d.get("ereignisse_tage") or 90))), zusatzfelder=felder)
    kern.einstellung_setzen("allgemein", a)
    protokoll(ich["name"], "einstellungen", "Allgemein gespeichert", ip=client_ip(req))
    return a


@router.post("/einstellungen/mqtt")
async def mqtt_speichern(req: Request, ich: dict = Depends(ADMIN)):
    import agent
    d = await req.json()
    if d.get("erkennung"):
        try:
            re.compile(d["erkennung"])
        except re.error as e:
            raise HTTPException(400, f"Erkennungs-Muster ungültig: {e}") from e
    k = agent.konfig()
    k.update(aktiv=bool(d.get("aktiv")), host=str(d.get("host") or "").strip(), port=int(d.get("port") or 1883),
             tls=bool(d.get("tls")), tls_pruefen=bool(d.get("tls_pruefen", True)),
             praefix=str(d.get("praefix") or "homeassistant").strip().strip("/"),
             erkennung=str(d.get("erkennung") or agent.STANDARD_MQTT["erkennung"]),
             client_id=str(d.get("client_id") or "").strip())
    kern.einstellung_setzen("mqtt", k)
    kern.geheim_setzen("mqtt", {"benutzer": d.get("benutzer", None), "passwort": d.get("passwort") or None})
    if d.get("passwort_loeschen"):
        kern.geheim_setzen("mqtt", {"passwort": ""})
    agent.DIENST.start()
    protokoll(ich["name"], "einstellungen", "MQTT gespeichert", k["host"], ip=client_ip(req))
    return {"ok": True, "status": agent.DIENST.status}


@router.post("/einstellungen/opnsense")
async def opnsense_speichern(req: Request, ich: dict = Depends(ADMIN)):
    d = await req.json()
    url = str(d.get("url") or "").strip().rstrip("/")
    if url and not re.match(r"^https?://", url):
        raise HTTPException(400, "Adresse mit https:// angeben")
    kern.einstellung_setzen("opnsense", {"aktiv": bool(d.get("aktiv")), "url": url, "tls_pruefen": bool(d.get("tls_pruefen", True)),
                                         "arp": bool(d.get("arp", True)), "dhcp": bool(d.get("dhcp", True))})
    kern.geheim_setzen("opnsense", {"key": d.get("key") or None, "secret": d.get("secret") or None})
    protokoll(ich["name"], "einstellungen", "OPNsense gespeichert", url, ip=client_ip(req))
    return {"ok": True}


@router.post("/opnsense/testen")
def opnsense_testen(ich: dict = Depends(ADMIN)):
    try:
        r = opnsense.testen()
        try:
            r["interfaces"] = opnsense.interfaces()
        except opnsense.Fehler:
            pass
        r["hosts"] = len(opnsense.bekannte_hosts())
        return r
    except opnsense.Fehler as e:
        raise HTTPException(400, str(e)) from e


@router.post("/opnsense/abgleich")
def opnsense_abgleich(req: Request, ich: dict = Depends(OPERATOR)):
    import inventar
    try:
        r = inventar.opnsense_abgleich()
    except opnsense.Fehler as e:
        raise HTTPException(400, str(e)) from e
    protokoll(ich["name"], "scan", "OPNsense-Abgleich", details=json.dumps(r), ip=client_ip(req))
    return r


@router.get("/opnsense/interfaces")
def opnsense_interfaces(ich: dict = Depends(LESER)):
    if not opnsense.eingerichtet():
        return {"interfaces": {}}
    try:
        return {"interfaces": opnsense.interfaces()}
    except opnsense.Fehler as e:
        return {"interfaces": {}, "fehler": str(e)}


# ------------------------------------------------------------------ Erkennungs-Muster
def _m_json(m: Muster) -> dict:
    return {"id": m.id, "reihenfolge": m.reihenfolge, "ziel": m.ziel, "muster": m.muster, "kategorie": m.kategorie,
            "bezeichnung": m.bezeichnung, "einheit": m.einheit, "device_class": m.device_class, "state_class": m.state_class,
            "icon": m.icon, "importieren": m.importieren, "gefahr": m.gefahr, "aktiv": m.aktiv}


@router.get("/muster")
def muster_liste(ich: dict = Depends(LESER)):
    with sitzung() as s:
        ms = [_m_json(m) for m in s.scalars(select(Muster).order_by(Muster.ziel.desc(), Muster.reihenfolge, Muster.id))]
        beispiele = []
        for a in s.scalars(select(Agent)):
            for w in s.scalars(select(AgentWert).where(AgentWert.agent_id == a.id)):
                beispiele.append({"ziel": "sensor", "agent": a.name, "schluessel": w.schluessel, "name": w.name,
                                  "treffer": muster.erkennen("sensor", w.schluessel, w.name, a.name)})
            for b in s.scalars(select(AgentBefehl).where(AgentBefehl.agent_id == a.id)):
                beispiele.append({"ziel": "befehl", "agent": a.name, "schluessel": b.schluessel, "name": b.name,
                                  "treffer": muster.erkennen("befehl", b.schluessel, b.name, a.name)})
    return {"muster": ms, "beispiele": beispiele}


@router.post("/muster")
async def muster_speichern(req: Request, ich: dict = Depends(ADMIN)):
    d = await req.json()
    pat = str(d.get("muster") or "").strip()
    if not pat:
        raise HTTPException(400, "Muster fehlt")
    if pat.lower().startswith("re:"):
        try:
            re.compile(pat[3:])
        except re.error as e:
            raise HTTPException(400, f"Regulärer Ausdruck ungültig: {e}") from e
    if d.get("ziel") not in ("sensor", "befehl"):
        raise HTTPException(400, "Ziel: sensor oder befehl")
    with sitzung() as s:
        m = s.get(Muster, int(d["id"])) if d.get("id") else None
        if d.get("id") and not m:
            raise LookupError("Muster gibt es nicht")
        if not m:
            m = Muster(muster=pat)
            s.add(m)
        m.muster, m.ziel = pat[:255], d["ziel"]
        m.reihenfolge = int(d.get("reihenfolge") or 100)
        for f, n in (("kategorie", 32), ("bezeichnung", 128), ("einheit", 32), ("device_class", 48), ("state_class", 32), ("icon", 64)):
            setattr(m, f, str(d.get(f) or "").strip()[:n])
        m.importieren, m.gefahr, m.aktiv = bool(d.get("importieren", True)), bool(d.get("gefahr")), bool(d.get("aktiv", True))
        s.flush()
        out = _m_json(m)
    muster.neu_laden()
    return out


@router.delete("/muster/{mid}")
def muster_weg(mid: int, ich: dict = Depends(ADMIN)):
    with sitzung() as s:
        m = s.get(Muster, mid)
        if not m:
            raise LookupError("Muster gibt es nicht")
        s.delete(m)
    muster.neu_laden()
    return {"ok": True}


@router.post("/muster/standard")
def muster_standard(req: Request, ich: dict = Depends(ADMIN)):
    with sitzung() as s:
        s.execute(delete(Muster))
        for m in muster.STANDARD:
            s.add(Muster(**m))
    muster.neu_laden()
    protokoll(ich["name"], "muster", "auf Standard zurückgesetzt", ip=client_ip(req))
    return {"ok": True}


# ------------------------------------------------------------------ Sicherung
TABELLEN = [("typen", Typ), ("hersteller", Hersteller), ("modelle", Modell), ("netzwerke", Netzwerk), ("geraete", Geraet),
            ("geraet_typen", GeraetTyp), ("schnittstellen", Schnittstelle), ("muster", Muster)]


def _zeile(o) -> dict:
    d = {}
    for c in o.__table__.columns:
        v = getattr(o, c.key)
        d[c.key] = iso(v) if isinstance(v, datetime) else v
    return d


@router.get("/sicherung")
def sicherung(ich: dict = Depends(ADMIN)):
    import inventar
    with sitzung() as s:
        daten = {"format": "nina", "version": kern.VERSION, "schema": migrationen.AKTUELL, "erstellt": iso(kern.jetzt()),
                 "allgemein": inventar.allgemein()}
        for name, modell in TABELLEN:
            daten[name] = [_zeile(o) for o in s.scalars(select(modell))]
    protokoll(ich["name"], "sicherung", "exportiert")
    return Response(json.dumps(daten, ensure_ascii=False, indent=1), media_type="application/json",
                    headers={"Content-Disposition": f'attachment; filename="nina-{kern.jetzt():%Y%m%d-%H%M}.json"'})


def _ist_zeit(spalte) -> bool:
    try:
        return spalte.type.python_type is datetime
    except NotImplementedError:
        return False


@router.post("/sicherung")
async def wiederherstellen(req: Request, ich: dict = Depends(ADMIN)):
    """Ersetzt Kataloge, Netzwerke, Geräte, Schnittstellen und Muster durch den Inhalt der Sicherung.
    Eine Sicherung von 1.0 (ohne Kataloge) bekommt die Standard-Typen, Geräte werden mit ihrem Typ verknüpft."""
    d = await req.json()
    if d.get("format") != "nina":
        raise HTTPException(400, "Keine NINA-Sicherung")
    with sitzung() as s:
        for a in s.scalars(select(Agent)):
            a.geraet_id = None
        s.execute(delete(Ereignis))
        s.execute(delete(Schnittstelle))
        s.execute(delete(GeraetTyp))
        s.execute(delete(Geraet))
        s.execute(delete(Netzwerk))
        s.execute(delete(Muster))
        s.execute(delete(Modell))
        s.execute(delete(Hersteller))
        if d.get("typen"):
            s.execute(delete(Typ))
        s.flush()
        for name, modell in TABELLEN:
            if name == "typen" and not d.get("typen"):
                continue
            spalten = {c.key: c for c in modell.__table__.columns}
            for z in d.get(name) or []:
                werte = {}
                for k, v in z.items():
                    if k not in spalten:
                        continue            # Spalte aus neuerer/älterer Version – überspringen
                    if v and isinstance(v, str) and _ist_zeit(spalten[k]):
                        v = datetime.fromisoformat(v)
                    werte[k] = v
                s.add(modell(**werte))
            s.flush()
        if not d.get("geraet_typen"):          # Sicherung aus 1.0
            import katalog
            ids = katalog.typ_ids(s)
            for g in s.scalars(select(Geraet)):
                if g.typ not in ids:
                    g.typ = "unbekannt"
                s.add(GeraetTyp(geraet_id=g.id, typ_id=ids[g.typ]))
                if g.status == "aktiv":
                    katalog.eintragen(s, g.hersteller, g.modell, g.typ)
    if d.get("allgemein"):
        kern.einstellung_setzen("allgemein", d["allgemein"])
    muster.neu_laden()
    protokoll(ich["name"], "sicherung", "wiederhergestellt", ip=client_ip(req),
              details=", ".join(f"{len(d.get(n) or [])} {n}" for n, _ in TABELLEN))
    return {"ok": True, **{n: len(d.get(n) or []) for n, _ in TABELLEN}}


# ------------------------------------------------------------------ Protokoll, System
@router.get("/protokoll")
def protokoll_liste(grenze: int = 300, ich: dict = Depends(OPERATOR)):
    with sitzung() as s:
        return {"eintraege": [{"zeit": iso(p.zeit), "benutzer": p.benutzer, "ip": p.ip, "bereich": p.bereich, "aktion": p.aktion,
                               "ziel": p.ziel, "ok": p.ok, "details": p.details}
                              for p in s.scalars(select(Protokoll).order_by(Protokoll.zeit.desc()).limit(min(grenze, 2000)))]}


@router.get("/system")
def system(ich: dict = Depends(LESER)):
    import agent
    import dienste
    k = kern.konfig_lesen()
    db = dict(k.get("db") or {})
    db.pop("passwort_enc", None)
    return {"version": kern.VERSION, "instanz": kern.instanz_id(), "db": db, **migrationen.schema_info(),
            "nmap": netz.nmap_da(), "adressen": [str(i) for i in netz.eigene_adressen()], "mdns": dienste.MDNS.status,
            "mqtt": agent.DIENST.status, "port": dienste.port()}
