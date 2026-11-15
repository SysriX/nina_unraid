"""Nicht zugewiesene Funde (Tabelle ni_fund): anlegen/aktualisieren aus Scan, OPNsense und HASS.Agent,
zuweisen (→ Gerät), Vorschläge zum Zusammenführen, „Zuweisung aufheben“ (Gerät → Funde).

Ein Fund ist ein physisches Ding, so wie es erkannt wurde: Schlüssel ist die MAC (sonst Netz + IP) bzw. der Agent.
Er merkt sich alle Quellen, die ihn gesehen haben. Geräte (ni_geraet) entstehen nur durch Zuweisen.
"""
from __future__ import annotations

import os
import shutil

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import delete, func, select

import katalog
import kern
import netz
from kern import iso, jetzt, protokoll, sitzung
from modelle import Agent, Ereignis, Fund, Geraet, GeraetTyp, Netzwerk, Schnittstelle, Typ
from zugang import ADMIN, LESER, OPERATOR, client_ip

router = APIRouter(prefix="/api")
QUELLEN = {"scan": "Netzwerk-Scan", "opnsense": "OPNsense", "agent": "HASS.Agent", "manuell": "von Hand"}


def _kurz(hostname: str) -> str:
    h = (hostname or "").strip().rstrip(".")
    return h if not h or netz.ip_gueltig(h) else h.split(".")[0]


# ------------------------------------------------------------------ Funde aus Scan / OPNsense
def aus_host(s, h: dict, quelle: str, nw: Netzwerk | None, modus: str) -> Fund | None:
    """Host ohne Gerät: passenden Fund aktualisieren oder neu anlegen. None = nichts angelegt."""
    import inventar
    ip, mac = (h.get("ip") or "").strip(), netz.mac_norm(h.get("mac"))
    hn = (h.get("hostname") or "").strip().rstrip(".")
    f = s.scalars(select(Fund).where(Fund.schluessel == f"mac:{mac}")).first() if mac else None
    if not f and ip:
        f = s.scalars(select(Fund).where(Fund.schluessel == f"ip:{nw.id if nw else 0}:{ip}")).first()
        if f and mac:           # jetzt mit MAC bekannt → Schlüssel umstellen (wenn frei)
            if not s.scalars(select(Fund).where(Fund.schluessel == f"mac:{mac}")).first():
                f.schluessel = f"mac:{mac}"
    if not f:
        if modus == "nein" or not h.get("online", True):
            return None
        hersteller = h.get("hersteller") or netz.mac_hersteller(mac)
        f = Fund(schluessel=f"mac:{mac}" if mac else f"ip:{nw.id if nw else 0}:{ip}", name=_kurz(hn) or ip or mac,
                 typ=katalog.gueltiger_typ(s, inventar.typ_raten(hersteller, hn, mac)),
                 hersteller="" if "zufällig" in hersteller else hersteller.split(" ")[0][:128], quellen=[])
        s.add(f)
    if ip:
        f.ip = ip
    if mac:
        f.mac = mac
    if hn:
        f.hostname = hn
        if not f.name or f.name in (f.ip, f.mac):
            f.name = _kurz(hn)
    if h.get("hersteller") and not f.mac_hersteller:
        f.mac_hersteller = str(h["hersteller"])[:128]
    if nw:
        f.netzwerk_id = nw.id
    if quelle not in (f.quellen or []):
        f.quellen = [*(f.quellen or []), quelle]
    if h.get("online", True):
        f.online, f.zuletzt = True, jetzt()
    return f


# ------------------------------------------------------------------ Funde aus HASS.Agent
def agent_fund(s, a: Agent) -> Fund | None:
    """Jeder Agent ohne Gerät steht als Fund unter „Nicht zugewiesen“ (nie automatisch zugewiesen)."""
    if a.geraet_id:
        return None
    f = s.scalars(select(Fund).where(Fund.agent_id == a.id)).first()
    if not f:
        f = Fund(schluessel=f"agent:{a.id}", agent_id=a.id, name=a.name, typ=katalog.gueltiger_typ(s, "pc"), quellen=["agent"])
        s.add(f)
    f.name = f.name or a.name
    f.online = a.online
    if a.online:
        f.zuletzt = jetzt()
    return f


# ------------------------------------------------------------------ Gerät → Funde (Zuweisung aufheben)
def geraet_aufheben(s, g: Geraet) -> int:
    """Macht aus einem Gerät wieder Funde (je Schnittstelle einer, je Agent einer) und löscht das Gerät."""
    vorher = {"name": g.name, "typ": g.typ, "typen": katalog.geraet_typen(s, g.id), "hersteller": g.hersteller, "modell": g.modell,
              "benutzer": g.benutzer, "raum": g.raum, "standort": g.standort, "betriebssystem": g.betriebssystem,
              "seriennummer": g.seriennummer, "inventarnummer": g.inventarnummer, "notizen": g.notizen, "tags": g.tags or [],
              "extra": g.extra or {}, "wol_aktiv": g.wol_aktiv, "wol_mac": g.wol_mac, "ueberwachen": g.ueberwachen, "ha_import": g.ha_import}
    n = 0
    for x in s.scalars(select(Schnittstelle).where(Schnittstelle.geraet_id == g.id)):
        key = f"mac:{x.mac}" if x.mac else f"ip:{x.netzwerk_id or 0}:{x.ip}" if x.ip else f"geraet:{g.id}:{x.id}"
        f = s.scalars(select(Fund).where(Fund.schluessel == key)).first() or Fund(schluessel=key, quellen=[])
        if f.id is None:
            s.add(f)
        q = x.quelle if x.quelle in QUELLEN else "scan"
        f.name, f.hostname, f.ip, f.mac, f.mac_hersteller = g.name, x.hostname, x.ip, x.mac, x.mac_hersteller
        f.hersteller, f.modell, f.typ, f.netzwerk_id = g.hersteller, g.modell, g.typ, x.netzwerk_id
        f.quellen = list(dict.fromkeys([*(f.quellen or []), q]))
        f.online, f.zuletzt, f.daten = x.online, x.zuletzt, {"vorher": vorher}
        n += 1
    for a in s.scalars(select(Agent).where(Agent.geraet_id == g.id)):
        a.geraet_id = None
        s.flush()
        f = agent_fund(s, a)
        f.name, f.typ, f.hersteller, f.modell = g.name, g.typ, g.hersteller, g.modell
        f.daten = {"vorher": vorher}
        n += 1
    if n == 0 and g.quelle == "manuell":      # von Hand angelegtes Gerät ohne Adresse: als Fund „von Hand“ behalten
        s.add(Fund(schluessel=f"geraet:{g.id}", name=g.name, typ=g.typ, hersteller=g.hersteller, modell=g.modell,
                   quellen=["manuell"], daten={"vorher": vorher}))
        n = 1
    s.execute(delete(Schnittstelle).where(Schnittstelle.geraet_id == g.id))
    s.execute(delete(GeraetTyp).where(GeraetTyp.geraet_id == g.id))
    s.execute(delete(Ereignis).where(Ereignis.geraet_id == g.id))
    s.delete(g)
    s.flush()
    return n


# ------------------------------------------------------------------ JSON / Abfragen
def _agent_ips(s, f: Fund) -> set:
    if not f.agent_id:
        return set()
    import agent as agent_mod
    return agent_mod.agent_ips(f.agent_id)


def fund_json(s, f: Fund, netze: dict | None = None, tnamen: dict | None = None) -> dict:
    if netze is None:
        netze = {n.id: n.name for n in s.scalars(select(Netzwerk))}
    if tnamen is None:
        tnamen = {t.schluessel: t.name for t in s.scalars(select(Typ))}
    a = s.get(Agent, f.agent_id) if f.agent_id else None
    d = {"id": f.id, "name": f.name, "hostname": f.hostname, "ip": f.ip, "mac": f.mac, "mac_hersteller": f.mac_hersteller,
         "hersteller": f.hersteller, "modell": f.modell, "typ": f.typ, "typ_name": tnamen.get(f.typ, f.typ),
         "netzwerk": netze.get(f.netzwerk_id, ""), "quellen": f.quellen or [], "online": f.online, "ignoriert": f.ignoriert,
         "erstmals": iso(f.erstmals), "zuletzt": iso(f.zuletzt), "vorher": (f.daten or {}).get("vorher"),
         "agent": {"id": a.id, "name": a.name, "version": a.version, "modell": a.modell, "online": a.online} if a else None}
    if a:
        ips = sorted(_agent_ips(s, f))
        cidrs = [n.cidr for n in s.scalars(select(Netzwerk))]
        ips.sort(key=lambda ip: not any(netz.im_netz(ip, c) for c in cidrs))    # Adressen aus eigenen Netzen zuerst
        d["agent_ips"] = ips
        if not d["ip"] and ips:
            d["ip"] = ips[0]
    return d


@router.get("/funde")
def funde(ignoriert: int = 0, ich: dict = Depends(LESER)):
    with sitzung() as s:
        for a in s.scalars(select(Agent).where(Agent.geraet_id.is_(None))):   # Agenten ohne Fund nachziehen
            if not s.scalars(select(Fund.id).where(Fund.agent_id == a.id)).first():
                agent_fund(s, a)
        s.flush()
        netze = {n.id: n.name for n in s.scalars(select(Netzwerk))}
        tn = {t.schluessel: t.name for t in s.scalars(select(Typ))}
        q = select(Fund).where(Fund.ignoriert.is_(bool(ignoriert))).order_by(func.lower(Fund.name))
        return {"funde": [fund_json(s, f, netze, tn) for f in s.scalars(q)]}


@router.get("/funde/{fid}")
def fund(fid: int, ich: dict = Depends(LESER)):
    with sitzung() as s:
        f = s.get(Fund, fid)
        if not f:
            raise LookupError("Fund gibt es nicht (schon zugewiesen?)")
        return fund_json(s, f)


@router.get("/funde/{fid}/vorschlaege")
def vorschlaege(fid: int, ich: dict = Depends(LESER)):
    """Andere Funde und Inventar-Geräte, die wahrscheinlich dasselbe Gerät sind – mit Grund."""
    import inventar
    with sitzung() as s:
        f = s.get(Fund, fid)
        if not f:
            raise LookupError("Fund gibt es nicht")
        namen = {x.lower() for x in (_kurz(f.name), _kurz(f.hostname)) if x}
        ips = ({f.ip} if f.ip else set()) | _agent_ips(s, f)
        macs = {f.mac} if f.mac else set()
        netze = {n.id: n.name for n in s.scalars(select(Netzwerk))}
        tn = {t.schluessel: t.name for t in s.scalars(select(Typ))}
        out = []
        for o in s.scalars(select(Fund).where(Fund.id != fid, Fund.ignoriert.is_(False))):
            onamen = {x.lower() for x in (_kurz(o.name), _kurz(o.hostname)) if x}
            oips = ({o.ip} if o.ip else set()) | _agent_ips(s, o)
            gruende = (["gleicher Name"] if namen & onamen else []) + (["gleiche MAC"] if o.mac and o.mac in macs else []) \
                + (["gleiche IP"] if ips & oips else [])
            j = fund_json(s, o, netze, tn)
            j.update(art="fund", gruende=gruende)
            out.append(j)
        gt = katalog.alle_geraet_typen(s)
        for g in s.scalars(select(Geraet).where(Geraet.status == "aktiv")):
            schs = list(s.scalars(select(Schnittstelle).where(Schnittstelle.geraet_id == g.id)))
            gnamen = {_kurz(g.name).lower()} | {_kurz(x.hostname).lower() for x in schs if x.hostname}
            gruende = (["gleicher Name"] if namen & gnamen else []) + (["gleiche MAC"] if macs & {x.mac for x in schs if x.mac} else []) \
                + (["gleiche IP"] if ips & {x.ip for x in schs if x.ip} else [])
            if not gruende:
                continue
            j = inventar.geraet_json(s, g, netze=netze, tnamen=tn, gtypen=gt)
            j.update(art="geraet", gruende=gruende)
            out.append(j)
        out.sort(key=lambda x: (-len(x["gruende"]), x["art"] != "fund", x["name"].lower()))
        return {"vorschlaege": out}


# ------------------------------------------------------------------ Zuweisen
def _uebernehmen(s, f: Fund, g: Geraet) -> None:
    """Inhalt eines Funds an das Gerät hängen (Schnittstelle, Agent) und den Fund löschen."""
    if f.mac or f.ip:
        x = s.scalars(select(Schnittstelle).where(Schnittstelle.mac == f.mac)).first() if f.mac else None
        if x and x.geraet_id != g.id:
            raise HTTPException(400, f"Die MAC {f.mac} gehört schon zu einem anderen Gerät")
        if not x:
            primaer = not s.scalar(select(func.count(Schnittstelle.id)).where(Schnittstelle.geraet_id == g.id))
            q = next((q for q in (f.quellen or []) if q != "agent"), "scan")
            s.add(Schnittstelle(geraet_id=g.id, mac=f.mac, ip=f.ip, hostname=f.hostname, mac_hersteller=f.mac_hersteller,
                                netzwerk_id=f.netzwerk_id, primaer=primaer, quelle=q, online=f.online, zuletzt=f.zuletzt,
                                art=netz.nic_art("", f.mac_hersteller, f.mac)))
            if f.mac:
                g.wol_aktiv = g.wol_aktiv or g.typ in ("pc", "laptop", "server", "nas")
    if f.agent_id:
        a = s.get(Agent, f.agent_id)
        if a:
            a.geraet_id = g.id
            g.ueberwachen = True
            if not g.betriebssystem and a.modell:
                g.betriebssystem = a.modell[:128]
    for k in ("hersteller", "modell"):
        if not getattr(g, k) and getattr(f, k):
            setattr(g, k, getattr(f, k))
    s.delete(f)
    s.flush()


@router.post("/funde/{fid}/zuweisen")
async def zuweisen(fid: int, req: Request, ich: dict = Depends(OPERATOR)):
    """Fund (+ weitere) einem neuen Gerät oder einem vorhandenen (ziel) zuweisen."""
    import inventar
    d = await req.json()
    with sitzung() as s:
        f = s.get(Fund, fid)
        if not f:
            raise LookupError("Fund gibt es nicht (schon zugewiesen?)")
        weitere = [s.get(Fund, int(i)) for i in d.get("weitere") or [] if int(i) != fid]
        weitere = [x for x in weitere if x]
        if d.get("ziel"):
            g = s.get(Geraet, int(d["ziel"]))
            if not g:
                raise LookupError("Gerät gibt es nicht")
            neu = False
        else:
            name = str(d.get("name") or f.name or f.ip or "Gerät").strip()[:128]
            typ = d.get("typ") or f.typ
            if not s.scalar(select(Typ.id).where(Typ.schluessel == typ)):
                typ = "unbekannt"
            g = Geraet(name=name, typ=typ, status="aktiv", quelle=(f.quellen or ["manuell"])[0])
            for k in ("benutzer", "raum", "standort", "hersteller", "modell"):
                if d.get(k) is not None:
                    setattr(g, k, str(d[k]).strip())
            vorher = (f.daten or {}).get("vorher") or {}
            for k in ("betriebssystem", "seriennummer", "inventarnummer", "notizen"):
                if vorher.get(k):
                    setattr(g, k, vorher[k])
            if vorher.get("tags"):
                g.tags = vorher["tags"]
            if vorher.get("wol_mac"):
                g.wol_mac = vorher["wol_mac"]
                g.wol_aktiv = True
            if vorher.get("extra"):
                g.extra = vorher["extra"]
            g.ha_import = vorher.get("ha_import", True)
            s.add(g)
            s.flush()
            neu = True
        namen = []
        for x in [f, *weitere]:
            namen.append(x.name)
            _uebernehmen(s, x, g)
        if neu or d.get("typen"):
            katalog.geraet_typen_setzen(s, g, d.get("typen") or katalog.geraet_typen(s, g.id))
        katalog.eintragen(s, g.hersteller, g.modell, g.typ)
        inventar.ereignis(s, g.id, "neu", ("zugewiesen: " if neu else "hinzugefügt: ") + ", ".join(namen) + f" ({ich['name']})")
        g.geaendert = jetzt()
        s.flush()
        inventar.online_aktualisieren(s, [g.id])
        gid, gname = g.id, g.name
    protokoll(ich["name"], "zuweisung", "zugewiesen" if neu else "hinzugefügt", gname, details=", ".join(namen), ip=client_ip(req))
    return {"ok": True, "geraet_id": gid, "funde": len(namen)}


@router.post("/funde/{fid}/ignorieren")
async def ignorieren(fid: int, req: Request, ich: dict = Depends(OPERATOR)):
    d = await req.json()
    with sitzung() as s:
        f = s.get(Fund, fid)
        if not f:
            raise LookupError("Fund gibt es nicht")
        f.ignoriert = bool(d.get("an", True))
    return {"ok": True}


@router.delete("/funde/{fid}")
def vergessen(fid: int, req: Request, ich: dict = Depends(OPERATOR)):
    """Fund löschen – taucht beim nächsten Scan wieder auf, wenn das Gerät noch da ist."""
    with sitzung() as s:
        f = s.get(Fund, fid)
        if not f:
            raise LookupError("Fund gibt es nicht")
        if f.agent_id:
            raise HTTPException(400, "Agent-Funde lassen sich nicht vergessen – den Agenten unter HASS.Agent entfernen oder ignorieren")
        s.delete(f)
    return {"ok": True}


# ------------------------------------------------------------------ Zuweisung aufheben
@router.post("/geraete/{gid}/aufheben")
def aufheben(gid: int, req: Request, ich: dict = Depends(ADMIN)):
    with sitzung() as s:
        g = s.get(Geraet, gid)
        if not g:
            raise LookupError("Gerät gibt es nicht")
        name = g.name
        n = geraet_aufheben(s, g)
    protokoll(ich["name"], "zuweisung", "Zuweisung aufgehoben", name, details=f"{n} Funde", ip=client_ip(req))
    return {"ok": True, "funde": n}


def _sicherung_vorher() -> str:
    """Vor dem Aufheben aller Zuweisungen: SQLite-Datei kopieren bzw. JSON-Sicherung ablegen."""
    import json
    import verwaltung
    stempel = kern.jetzt().strftime("%Y%m%d-%H%M%S")
    url = kern.db_url() or ""
    if url.startswith("sqlite"):
        pfad = url.split("sqlite:///", 1)[-1]
        ziel = f"{pfad}.vor-neustart-{stempel}"
        shutil.copy2(pfad, ziel)
        return ziel
    ziel = os.path.join(kern.DATA, f"sicherung-vor-neustart-{stempel}.json")
    with open(ziel, "w", encoding="utf-8") as fh:
        json.dump(verwaltung.sicherung_daten(), fh, ensure_ascii=False, indent=1)
    return ziel


@router.post("/zuweisungen/aufheben")
async def alle_aufheben(req: Request, ich: dict = Depends(ADMIN)):
    """Alle Geräte wieder zu Funden machen (sauberer Neustart). Vorher wird gesichert."""
    d = await req.json()
    if d.get("bestaetigung") != "NEUSTART":
        raise HTTPException(400, "Zur Bestätigung NEUSTART eintippen")
    sicherung = _sicherung_vorher()
    with sitzung() as s:
        ids = [g.id for g in s.scalars(select(Geraet))]
        funde_n = 0
        for gid in ids:
            g = s.get(Geraet, gid)
            if g:
                funde_n += geraet_aufheben(s, g)
    protokoll(ich["name"], "zuweisung", "alle Zuweisungen aufgehoben", details=f"{len(ids)} Geräte → {funde_n} Funde, Sicherung {sicherung}",
              ip=client_ip(req))
    return {"ok": True, "geraete": len(ids), "funde": funde_n, "sicherung": sicherung}


# ------------------------------------------------------------------ Sammel-Aktionen (Mehrfachauswahl)
@router.post("/funde/sammel")
async def sammel(req: Request, ich: dict = Depends(OPERATOR)):
    """{aktion: ignorieren | anzeigen | entfernen, ids: [...]}.
    Entfernen löscht Funde (tauchen beim nächsten Scan wieder auf, wenn das Gerät noch da ist). HASS.Agent-Funde werden
    dabei übersprungen – ein laufender Agent meldet sich sofort wieder; für die gibt es „Ignorieren“."""
    d = await req.json()
    aktion, ids = d.get("aktion"), [int(i) for i in d.get("ids") or []]
    if aktion not in ("ignorieren", "anzeigen", "entfernen"):
        raise HTTPException(400, "Unbekannte Aktion")
    erledigt, agenten = 0, 0
    with sitzung() as s:
        for fid in ids:
            f = s.get(Fund, fid)
            if not f:
                continue
            if aktion in ("ignorieren", "anzeigen"):
                f.ignoriert = aktion == "ignorieren"
                erledigt += 1
            elif f.agent_id:
                agenten += 1
            else:
                s.delete(f)
                erledigt += 1
    protokoll(ich["name"], "funde", f"Sammel-Aktion {aktion}", details=f"{erledigt} Funde, {agenten} HASS.Agent übersprungen",
              ip=client_ip(req))
    return {"ok": True, "erledigt": erledigt, "agenten_uebersprungen": agenten}


# ------------------------------------------------------------------ Gerät → passende offene Funde
@router.get("/geraete/{gid}/funde")
def funde_fuer_geraet(gid: int, ich: dict = Depends(LESER)):
    """Alle offenen Funde, die einem Gerät hinzugefügt werden können – passende (Name/IP/MAC) zuerst, mit Grund."""
    with sitzung() as s:
        g = s.get(Geraet, gid)
        if not g:
            raise LookupError("Gerät gibt es nicht")
        schs = list(s.scalars(select(Schnittstelle).where(Schnittstelle.geraet_id == gid)))
        namen = {_kurz(g.name).lower()} | {_kurz(x.hostname).lower() for x in schs if x.hostname}
        ips, macs = {x.ip for x in schs if x.ip}, {x.mac for x in schs if x.mac}
        a = s.scalars(select(Agent).where(Agent.geraet_id == gid)).first()
        if a:
            import agent as agent_mod
            namen.add(a.name.lower())
            ips |= agent_mod.agent_ips(a.id)
        netze = {n.id: n.name for n in s.scalars(select(Netzwerk))}
        tn = {t.schluessel: t.name for t in s.scalars(select(Typ))}
        out = []
        for f in s.scalars(select(Fund).where(Fund.ignoriert.is_(False))):
            fn = {x.lower() for x in (_kurz(f.name), _kurz(f.hostname)) if x}
            fips = ({f.ip} if f.ip else set()) | _agent_ips(s, f)
            j = fund_json(s, f, netze, tn)
            j["gruende"] = (["gleicher Name"] if namen & fn else []) + (["gleiche MAC"] if f.mac and f.mac in macs else []) \
                + (["gleiche IP"] if ips & fips else [])
            out.append(j)
        out.sort(key=lambda x: (-len(x["gruende"]), (x["name"] or "").lower()))
        return {"funde": out}
