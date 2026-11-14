"""Inventar: Geräte, Schnittstellen, Netzwerke, Scans, Online-Status, Wake-on-LAN, Ereignisse."""
from __future__ import annotations

import re
import threading
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import delete, func, or_, select

import kern
import netz
import opnsense
from kern import iso, jetzt, protokoll, sitzung
from modelle import Agent, Ereignis, Geraet, Netzwerk, Schnittstelle
from zugang import ADMIN, LESER, OPERATOR, client_ip

router = APIRouter(prefix="/api")

TYPEN = [("pc", "PC"), ("laptop", "Laptop"), ("server", "Server"), ("vm", "Virtuelle Maschine"), ("nas", "NAS"),
         ("netzwerk", "Switch / Access-Point"), ("router", "Router / Firewall"), ("drucker", "Drucker"),
         ("telefon", "Telefon / Smartphone"), ("tablet", "Tablet"), ("tv", "TV / Medien"), ("kamera", "Kamera"),
         ("iot", "IoT / Smart Home"), ("konsole", "Spielkonsole"), ("sonstiges", "Sonstiges"), ("unbekannt", "Unbekannt")]
TYP_NAMEN = dict(TYPEN)
STATUS = ("aktiv", "neu", "ignoriert", "ausgemustert")

STANDARD_ALLGEMEIN = {"name": "NetInventory", "neue_geraete": "pruefen", "ueberwachen_intervall": 60,
                      "wol_port": 9, "agent_geraete_anlegen": True, "ereignisse_tage": 90, "zusatzfelder": []}

_scan_lock: dict[int, threading.Lock] = {}


def allgemein() -> dict:
    return {**STANDARD_ALLGEMEIN, **(kern.einstellung("allgemein", {}) or {})}


# ------------------------------------------------------------------ Typ raten
def typ_raten(hersteller: str, hostname: str, mac: str = "") -> str:
    v, n = (hersteller or "").lower(), (hostname or "").lower()
    if mac.startswith("52:54:00") or re.search(r"vmware|qemu|xensource|proxmox|parallels|hyper-v", v):
        return "vm"
    if re.search(r"iphone|android|pixel|galaxy|handy|phone", n):
        return "telefon"
    if re.search(r"ipad|tab", n):
        return "tablet"
    if re.search(r"print|drucker|^brn|^npi|^hp[0-9a-f]{6}", n) or re.search(r"brother|canon|epson|kyocera|lexmark|xerox|ricoh", v):
        return "drucker"
    if re.search(r"espressif|tuya|shelly|sonoff|itead|tasmota|signify|philips lighting|bosch|homematic|eq-3|ikea|xiaomi|nuki|ring", v) \
            or re.search(r"esp|shelly|tasmota|tuya|sonoff", n):
        return "iot"
    if re.search(r"synology|qnap|western digital|asustor", v) or re.search(r"nas|diskstation", n):
        return "nas"
    if re.search(r"hikvision|dahua|reolink|axis|foscam|amcrest", v) or re.search(r"cam", n):
        return "kamera"
    if re.search(r"opnsense|pfsense|fritz|router|gateway|fw", n) or re.search(r"avm|deciso|protectli", v):
        return "router"
    if re.search(r"ubiquiti|tp-link|netgear|mikrotik|cisco|aruba|zyxel|d-link|juniper|lancom|ruckus", v) \
            or re.search(r"switch|^ap-|unifi|^sw", n):
        return "netzwerk"
    if re.search(r"sony interactive|nintendo|microsoft.*xbox", v) or re.search(r"playstation|ps[45]|xbox|switch", n):
        return "konsole"
    if re.search(r"tv|chromecast|fire|roku|apple-tv|appletv|kodi|shield", n):
        return "tv"
    if re.search(r"raspberry|supermicro", v) or re.search(r"server|srv|unraid|proxmox|pve|esx|truenas|^dc\d|^ha$|homeassistant", n):
        return "server"
    if re.search(r"laptop|notebook|^nb|book|thinkpad|surface", n):
        return "laptop"
    if re.search(r"intel|realtek|micro-star|asustek|gigabyte|dell|lenovo|hewlett|fujitsu|asrock|apple", v) or \
            re.search(r"^pc|desktop|workstation|^ws", n):
        return "pc"
    return "unbekannt"


def kurzname(hostname: str) -> str:
    h = (hostname or "").strip().rstrip(".")
    if not h or netz.ip_gueltig(h):
        return h
    return h.split(".")[0]


# ------------------------------------------------------------------ Ereignisse
def ereignis(s, geraet_id: int | None, art: str, text: str) -> None:
    s.add(Ereignis(geraet_id=geraet_id, art=art, text=text[:512]))


def online_aktualisieren(s, geraet_ids) -> None:
    """Gerät ist online, wenn eine Schnittstelle oder der HASS.Agent online ist."""
    for gid in set(i for i in geraet_ids if i):
        g = s.get(Geraet, gid)
        if not g:
            continue
        an = bool(s.scalar(select(func.count(Schnittstelle.id)).where(Schnittstelle.geraet_id == gid,
                                                                       Schnittstelle.online.is_(True))))
        if not an:
            an = bool(s.scalar(select(func.count(Agent.id)).where(Agent.geraet_id == gid, Agent.online.is_(True))))
        if an:
            g.zuletzt_online = jetzt()
        if an != g.online:
            g.online = an
            if g.status == "aktiv":
                ereignis(s, gid, "online" if an else "offline", "ist online" if an else "ist offline")


# ------------------------------------------------------------------ Scan-Ergebnisse einspielen
def netzwerk_fuer_ip(netze: list[Netzwerk], ip: str) -> Netzwerk | None:
    beste = None
    for n in netze:
        if netz.im_netz(ip, n.cidr) and (not beste or netz.netz(n.cidr).prefixlen > netz.netz(beste.cidr).prefixlen):
            beste = n
    return beste


def einspielen(hosts: list[dict], quelle: str, netzwerk_id: int | None = None, offline_markieren: bool = False) -> dict:
    """Gefundene Hosts ({ip, mac, hostname, hersteller}) mit dem Inventar abgleichen."""
    modus = allgemein()["neue_geraete"]
    neu = geaendert = 0
    betroffen: set[int] = set()
    with sitzung() as s:
        netze = list(s.scalars(select(Netzwerk)))
        gesehen: set[int] = set()
        for h in hosts:
            ip, mac = (h.get("ip") or "").strip(), netz.mac_norm(h.get("mac"))
            if not ip and not mac:
                continue
            nw = s.get(Netzwerk, netzwerk_id) if netzwerk_id else netzwerk_fuer_ip(netze, ip)
            sch = None
            if mac:
                sch = s.scalars(select(Schnittstelle).where(Schnittstelle.mac == mac).order_by(Schnittstelle.id)).first()
            if not sch and ip:
                q = select(Schnittstelle).where(Schnittstelle.ip == ip, Schnittstelle.mac == "")
                if nw:
                    q = q.where(or_(Schnittstelle.netzwerk_id == nw.id, Schnittstelle.netzwerk_id.is_(None)))
                sch = s.scalars(q).first()
            hn = (h.get("hostname") or "").strip().rstrip(".")
            if sch:
                if ip and sch.ip != ip and not sch.feste_ip:
                    if sch.ip:
                        ereignis(s, sch.geraet_id, "ip", f"IP {sch.ip} → {ip}")
                    sch.ip = ip
                    geaendert += 1
                if mac and not sch.mac:
                    sch.mac = mac
                if hn and (not sch.hostname or sch.quelle != "manuell"):
                    sch.hostname = hn
                if h.get("hersteller") and not sch.mac_hersteller:
                    sch.mac_hersteller = h["hersteller"]
                if nw and sch.netzwerk_id != nw.id:
                    sch.netzwerk_id = nw.id
                if h.get("online", True):
                    sch.online, sch.zuletzt = True, jetzt()
                gesehen.add(sch.id)
                betroffen.add(sch.geraet_id)
                continue
            if modus == "nein" or not h.get("online", True):
                continue
            hersteller = h.get("hersteller") or netz.mac_hersteller(mac)
            g = Geraet(name=kurzname(hn) or ip or mac, typ=typ_raten(hersteller, hn, mac),
                       hersteller="" if "zufällig" in hersteller else hersteller.split(" ")[0][:128],
                       status="neu" if modus == "pruefen" else "aktiv", quelle=quelle, online=True, zuletzt_online=jetzt())
            s.add(g)
            s.flush()
            sch = Schnittstelle(geraet_id=g.id, mac=mac, ip=ip, hostname=hn, mac_hersteller=hersteller,
                                netzwerk_id=nw.id if nw else None, primaer=True, quelle=quelle, online=True, zuletzt=jetzt())
            s.add(sch)
            s.flush()
            gesehen.add(sch.id)
            ereignis(s, g.id, "neu", f"gefunden per {quelle}: {ip} {mac}".strip())
            neu += 1
        if offline_markieren and netzwerk_id:
            for sch in s.scalars(select(Schnittstelle).where(Schnittstelle.netzwerk_id == netzwerk_id,
                                                             Schnittstelle.online.is_(True))):
                if sch.id not in gesehen:
                    sch.online = False
                    betroffen.add(sch.geraet_id)
        online_aktualisieren(s, betroffen)
    return {"gefunden": len(hosts), "neu": neu, "geaendert": geaendert}


def scan(netzwerk_id: int, wer: str = "zeitplan") -> dict:
    lock = _scan_lock.setdefault(netzwerk_id, threading.Lock())
    if not lock.acquire(blocking=False):
        raise HTTPException(409, "Für dieses Netz läuft schon ein Scan")
    try:
        with sitzung() as s:
            nw = s.get(Netzwerk, netzwerk_id)
            if not nw:
                raise LookupError("Netzwerk gibt es nicht")
            cidr, methode = nw.cidr, nw.scan_methode or "auto"
        hosts: list[dict] = []
        teile = []
        try:
            if methode in ("auto", "nmap", "ping"):
                if methode == "nmap" or (methode == "auto" and netz.nmap_da()):
                    hosts = netz.scan_nmap(cidr)
                    teile.append("nmap")
                else:
                    hosts = netz.scan_ping(cidr)
                    teile.append("ping")
            if methode in ("auto", "opnsense") and opnsense.eingerichtet():
                try:
                    bekannt = [x for x in opnsense.bekannte_hosts() if netz.im_netz(x["ip"], cidr)]
                    nach_ip = {x["ip"]: x for x in hosts}
                    for x in bekannt:
                        y = nach_ip.get(x["ip"])
                        if y:
                            y["mac"] = y.get("mac") or x["mac"]
                            y["hostname"] = y.get("hostname") or x["hostname"]
                            y["hersteller"] = y.get("hersteller") or x["hersteller"]
                        elif methode == "opnsense" or x.get("online"):
                            hosts.append(x)
                    teile.append("opnsense")
                except opnsense.Fehler as e:
                    teile.append(f"opnsense: {e}")
            erg = einspielen(hosts, "scan", netzwerk_id, offline_markieren=True)
            text = f"{erg['gefunden']} erreichbar, {erg['neu']} neu ({', '.join(teile)})"
            ok = True
        except Exception as e:  # noqa: BLE001
            erg, text, ok = {"fehler": str(e)}, f"Fehler: {e}", False
        with sitzung() as s:
            nw = s.get(Netzwerk, netzwerk_id)
            if nw:
                nw.letzter_scan, nw.scan_status = jetzt(), text[:512]
        if wer != "zeitplan" or not ok:
            protokoll(wer, "scan", "Scan", cidr, ok=ok, details=text)
        return {"ok": ok, "status": text, **erg}
    finally:
        lock.release()


def opnsense_abgleich() -> dict:
    """ARP/DHCP der OPNsense über alle Netze einspielen (ohne Offline-Markierung)."""
    if not opnsense.eingerichtet():
        return {"ok": False}
    hosts = opnsense.bekannte_hosts()
    return einspielen(hosts, "opnsense")


def ueberwachen() -> int:
    """Überwachte Geräte anpingen (schnelle Online-Erkennung, z. B. nach Wake-on-LAN)."""
    with sitzung() as s:
        ziele = [(sch.id, sch.ip) for sch in s.scalars(
            select(Schnittstelle).join(Geraet).where(Geraet.ueberwachen.is_(True), Geraet.status == "aktiv",
                                                     Schnittstelle.ip != ""))]
    if not ziele:
        return 0
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(32) as ex:
        ergebnis = list(ex.map(lambda z: (z[0], netz.erreichbar(z[1])), ziele))
    with sitzung() as s:
        betroffen = set()
        for sid, an in ergebnis:
            sch = s.get(Schnittstelle, sid)
            if not sch:
                continue
            if an:
                sch.zuletzt = jetzt()
            if sch.online != an:
                sch.online = an
            betroffen.add(sch.geraet_id)
        online_aktualisieren(s, betroffen)
    return len(ziele)


def aufraeumen() -> None:
    tage = int(allgemein().get("ereignisse_tage") or 90)
    from modelle import Protokoll, Sitzung
    with sitzung() as s:
        s.execute(delete(Ereignis).where(Ereignis.zeit < jetzt() - timedelta(days=tage)))
        s.execute(delete(Protokoll).where(Protokoll.zeit < jetzt() - timedelta(days=max(tage, 180))))
        s.execute(delete(Sitzung).where(Sitzung.ablauf < jetzt()))


# ------------------------------------------------------------------ Wake-on-LAN
def wol_ziel(s, g: Geraet) -> tuple[Schnittstelle | None, Netzwerk | None]:
    schs = list(s.scalars(select(Schnittstelle).where(Schnittstelle.geraet_id == g.id, Schnittstelle.mac != "")
                          .order_by(Schnittstelle.primaer.desc(), Schnittstelle.id)))
    if not schs:
        return None, None
    sch = schs[0]
    nw = s.get(Netzwerk, sch.netzwerk_id) if sch.netzwerk_id else None
    if not nw and sch.ip:
        nw = netzwerk_fuer_ip(list(s.scalars(select(Netzwerk))), sch.ip)
    return sch, nw


def wol_methode(g: Geraet, nw: Netzwerk | None) -> str:
    m = g.wol_methode or (nw.wol_methode if nw else "") or "auto"
    if m != "auto":
        return m
    if nw and netz.direkt_erreichbar(nw.cidr):
        return "container"
    if nw and nw.opnsense_interface and opnsense.eingerichtet():
        return "opnsense"
    return "container"


def wecken(gid: int, wer: str, ip: str = "") -> dict:
    with sitzung() as s:
        g = s.get(Geraet, gid)
        if not g:
            raise LookupError("Gerät gibt es nicht")
        sch, nw = wol_ziel(s, g)
        if not sch:
            raise HTTPException(400, "Das Gerät hat keine MAC-Adresse – Wake-on-LAN geht nicht")
        methode = wol_methode(g, nw)
        mac, name = sch.mac, g.name
        ziele = []
        if nw:
            ziele.append(nw.wol_broadcast or str(netz.netz(nw.cidr).broadcast_address))
            if netz.direkt_erreichbar(nw.cidr):
                ziele.append("255.255.255.255")
        else:
            ziele.append("255.255.255.255")
        iface = nw.opnsense_interface if nw else ""
    wege, fehler = [], []
    if methode in ("container", "beide"):
        try:
            wege += netz.magic_paket(mac, ziele, int(allgemein().get("wol_port") or 9))
        except Exception as e:  # noqa: BLE001
            fehler.append(f"Container: {e}")
    if methode in ("opnsense", "beide"):
        try:
            wege.append(opnsense.wecken(mac, iface))
        except Exception as e:  # noqa: BLE001
            fehler.append(str(e))
    ok = bool(wege)
    with sitzung() as s:
        ereignis(s, gid, "wol", f"Wake-on-LAN ({methode}) von {wer}: " + (", ".join(wege) or "; ".join(fehler)))
        g = s.get(Geraet, gid)
        if g and not g.ueberwachen:
            g.ueberwachen = True      # damit der Start schnell erkannt wird
    protokoll(wer, "wol", "Wecken", name, ok=ok, details="; ".join(wege + fehler), ip=ip)
    if not ok:
        raise HTTPException(502, "Wake-on-LAN fehlgeschlagen: " + "; ".join(fehler))
    return {"ok": True, "methode": methode, "wege": wege, "fehler": fehler, "mac": mac}


# ------------------------------------------------------------------ JSON
def _sch_json(x: Schnittstelle, netze: dict) -> dict:
    return {"id": x.id, "name": x.name, "mac": x.mac, "ip": x.ip, "hostname": x.hostname, "mac_hersteller": x.mac_hersteller,
            "netzwerk_id": x.netzwerk_id, "netzwerk": netze.get(x.netzwerk_id, ""), "primaer": x.primaer,
            "feste_ip": x.feste_ip, "quelle": x.quelle, "online": x.online, "erstmals": iso(x.erstmals), "zuletzt": iso(x.zuletzt)}


def geraet_json(s, g: Geraet, detail: bool = False, netze: dict | None = None, agenten: dict | None = None) -> dict:
    import agent as agent_mod
    if netze is None:
        netze = {n.id: n.name for n in s.scalars(select(Netzwerk))}
    schs = sorted(s.scalars(select(Schnittstelle).where(Schnittstelle.geraet_id == g.id)),
                  key=lambda x: (not x.primaer, not x.online, x.id))
    p = schs[0] if schs else None
    ag = agenten.get(g.id) if agenten is not None else s.scalars(select(Agent).where(Agent.geraet_id == g.id)).first()
    d = {"id": g.id, "name": g.name, "typ": g.typ, "typ_name": TYP_NAMEN.get(g.typ, g.typ), "hersteller": g.hersteller,
         "modell": g.modell, "benutzer": g.benutzer, "raum": g.raum, "standort": g.standort, "status": g.status,
         "quelle": g.quelle, "online": g.online, "zuletzt_online": iso(g.zuletzt_online), "tags": g.tags or [],
         "ip": p.ip if p else "", "mac": next((x.mac for x in schs if x.mac), ""), "hostname": p.hostname if p else "",
         "netzwerk": netze.get(p.netzwerk_id, "") if p else "", "anzahl_schnittstellen": len(schs),
         "wol": bool(g.wol_aktiv and any(x.mac for x in schs)), "ueberwachen": g.ueberwachen, "ha_import": g.ha_import,
         "agent": {"id": ag.id, "name": ag.name, "online": ag.online} if ag else None,
         "angemeldet": agent_mod.angemeldet(ag.id) if ag else "", "geaendert": iso(g.geaendert)}
    if detail:
        sch_nw = s.get(Netzwerk, p.netzwerk_id) if p and p.netzwerk_id else None
        _, wnw = wol_ziel(s, g)
        d.update({"seriennummer": g.seriennummer, "inventarnummer": g.inventarnummer, "betriebssystem": g.betriebssystem,
                  "notizen": g.notizen, "extra": g.extra or {}, "wol_aktiv": g.wol_aktiv, "wol_methode": g.wol_methode,
                  "wol_methode_wirksam": wol_methode(g, wnw) if any(x.mac for x in schs) else "",
                  "wol_netz": wnw.name if wnw else "", "erstellt": iso(g.erstellt),
                  "schnittstellen": [_sch_json(x, netze) for x in schs],
                  "netzwerk_cidr": sch_nw.cidr if sch_nw else "",
                  "agent": agent_mod.agent_json(s, ag, voll=True) if ag else None,
                  "ereignisse": [{"zeit": iso(e.zeit), "art": e.art, "text": e.text} for e in s.scalars(
                      select(Ereignis).where(Ereignis.geraet_id == g.id).order_by(Ereignis.zeit.desc()).limit(60))]})
    return d


# ------------------------------------------------------------------ Routen: Übersicht, Geräte
@router.get("/meta")
def meta(ich: dict = Depends(LESER)):
    a = allgemein()
    return {"typen": TYPEN, "status": STATUS, "name": a["name"], "zusatzfelder": a.get("zusatzfelder") or [],
            "version": kern.VERSION, "nmap": netz.nmap_da(), "opnsense": opnsense.eingerichtet()}


@router.get("/uebersicht")
def uebersicht(ich: dict = Depends(LESER)):
    with sitzung() as s:
        def zahl(*w):
            return s.scalar(select(func.count(Geraet.id)).where(*w)) or 0
        typen = dict(s.execute(select(Geraet.typ, func.count(Geraet.id)).where(Geraet.status == "aktiv").group_by(Geraet.typ)).all())
        ev = s.execute(select(Ereignis, Geraet.name).outerjoin(Geraet, Geraet.id == Ereignis.geraet_id)
                       .order_by(Ereignis.zeit.desc()).limit(25)).all()
        netze = [{"id": n.id, "name": n.name, "cidr": n.cidr, "letzter_scan": iso(n.letzter_scan), "scan_status": n.scan_status,
                  "geraete": s.scalar(select(func.count(func.distinct(Schnittstelle.geraet_id))).where(Schnittstelle.netzwerk_id == n.id)) or 0,
                  "online": s.scalar(select(func.count(func.distinct(Schnittstelle.geraet_id))).where(
                      Schnittstelle.netzwerk_id == n.id, Schnittstelle.online.is_(True))) or 0}
                 for n in s.scalars(select(Netzwerk).order_by(Netzwerk.name))]
        return {"geraete": zahl(Geraet.status == "aktiv"), "online": zahl(Geraet.status == "aktiv", Geraet.online.is_(True)),
                "neu": zahl(Geraet.status == "neu"), "ignoriert": zahl(Geraet.status == "ignoriert"),
                "agenten": s.scalar(select(func.count(Agent.id))) or 0,
                "agenten_online": s.scalar(select(func.count(Agent.id)).where(Agent.online.is_(True))) or 0,
                "typen": [{"typ": k, "name": TYP_NAMEN.get(k, k), "anzahl": v} for k, v in sorted(typen.items(), key=lambda x: -x[1])],
                "netze": netze,
                "ereignisse": [{"zeit": iso(e.zeit), "art": e.art, "text": e.text, "geraet_id": e.geraet_id, "geraet": n or ""} for e, n in ev]}


def geraete_liste(s, status: str = "aktiv", nur_ha: bool = False) -> list[dict]:
    netze = {n.id: n.name for n in s.scalars(select(Netzwerk))}
    agenten = {a.geraet_id: a for a in s.scalars(select(Agent).where(Agent.geraet_id.is_not(None)))}
    q = select(Geraet).order_by(func.lower(Geraet.name))
    if status != "alle":
        q = q.where(Geraet.status == status)
    if nur_ha:
        q = q.where(Geraet.ha_import.is_(True))
    return [geraet_json(s, g, netze=netze, agenten=agenten) for g in s.scalars(q)]


@router.get("/geraete")
def geraete(status: str = "aktiv", ich: dict = Depends(LESER)):
    with sitzung() as s:
        return {"geraete": geraete_liste(s, status)}


@router.get("/geraete/{gid}")
def geraet(gid: int, ich: dict = Depends(LESER)):
    with sitzung() as s:
        g = s.get(Geraet, gid)
        if not g:
            raise LookupError("Gerät gibt es nicht")
        return geraet_json(s, g, detail=True)


FELDER = ("name", "typ", "hersteller", "modell", "seriennummer", "inventarnummer", "betriebssystem", "standort", "raum",
          "benutzer", "notizen", "status", "wol_methode")
BOOL_FELDER = ("ueberwachen", "ha_import", "wol_aktiv")


@router.post("/geraete")
async def geraet_speichern(req: Request, ich: dict = Depends(OPERATOR)):
    d = await req.json()
    name = str(d.get("name", "")).strip()
    if not name:
        raise HTTPException(400, "Name fehlt")
    if d.get("typ") and d["typ"] not in TYP_NAMEN:
        raise HTTPException(400, "Unbekannter Typ")
    if d.get("status") and d["status"] not in STATUS:
        raise HTTPException(400, "Unbekannter Status")
    if d.get("raum") and not re.fullmatch(r"[a-z0-9_]{1,32}", d["raum"]):
        raise HTTPException(400, "Raum-Kürzel: nur Kleinbuchstaben, Ziffern und _ (z. B. bu, wz)")
    with sitzung() as s:
        if d.get("id"):
            g = s.get(Geraet, int(d["id"]))
            if not g:
                raise LookupError("Gerät gibt es nicht")
        else:
            g = Geraet(quelle="manuell", status="aktiv")
            s.add(g)
        for f in FELDER:
            if f in d and d[f] is not None:
                setattr(g, f, str(d[f]).strip())
        for f in BOOL_FELDER:
            if f in d:
                setattr(g, f, bool(d[f]))
        if "tags" in d:
            g.tags = [t.strip() for t in (d["tags"] if isinstance(d["tags"], list) else str(d["tags"]).split(",")) if t.strip()]
        if "extra" in d and isinstance(d["extra"], dict):
            g.extra = {**(g.extra or {}), **d["extra"]}
        g.geaendert = jetzt()
        s.flush()
        neu = not d.get("id")
        if neu and (d.get("mac") or d.get("ip")):
            mac = netz.mac_norm(d.get("mac"))
            if d.get("mac") and not mac:
                raise HTTPException(400, "MAC-Adresse ungültig")
            ip = str(d.get("ip") or "").strip()
            if ip and not netz.ip_gueltig(ip):
                raise HTTPException(400, "IP-Adresse ungültig")
            nw = netzwerk_fuer_ip(list(s.scalars(select(Netzwerk))), ip) if ip else None
            s.add(Schnittstelle(geraet_id=g.id, mac=mac, ip=ip, mac_hersteller=netz.mac_hersteller(mac), primaer=True,
                                netzwerk_id=nw.id if nw else None, feste_ip=bool(d.get("feste_ip"))))
            if mac and "wol_aktiv" not in d and g.typ in ("pc", "laptop", "server", "nas"):
                g.wol_aktiv = True
        if neu:
            ereignis(s, g.id, "neu", f"von Hand angelegt ({ich['name']})")
        gid = g.id
        out = geraet_json(s, g, detail=True)
    protokoll(ich["name"], "geraet", "angelegt" if neu else "geändert", name, ip=client_ip(req))
    if neu:
        _start_ping(gid)
    return out


def _start_ping(gid: int):
    def lauf():
        try:
            with sitzung() as s:
                ziele = [(x.id, x.ip) for x in s.scalars(select(Schnittstelle).where(Schnittstelle.geraet_id == gid, Schnittstelle.ip != ""))]
            erg = [(i, netz.erreichbar(ip)) for i, ip in ziele]
            with sitzung() as s:
                for i, an in erg:
                    x = s.get(Schnittstelle, i)
                    if x:
                        x.online = an
                        if an:
                            x.zuletzt = jetzt()
                online_aktualisieren(s, [gid])
        except Exception as e:  # noqa: BLE001
            kern.log("Ping nach Anlegen:", e)
    threading.Thread(target=lauf, daemon=True).start()


@router.post("/geraete/{gid}/status")
async def geraet_status(gid: int, req: Request, ich: dict = Depends(OPERATOR)):
    d = await req.json()
    if d.get("status") not in STATUS:
        raise HTTPException(400, "Unbekannter Status")
    with sitzung() as s:
        g = s.get(Geraet, gid)
        if not g:
            raise LookupError("Gerät gibt es nicht")
        g.status, g.geaendert = d["status"], jetzt()
        for f in ("name", "typ", "benutzer", "raum"):
            if d.get(f):
                setattr(g, f, str(d[f]).strip())
        name = g.name
    protokoll(ich["name"], "geraet", f"Status {d['status']}", name, ip=client_ip(req))
    return {"ok": True}


@router.post("/geraete/{gid}/zusammenfuehren")
async def zusammenfuehren(gid: int, req: Request, ich: dict = Depends(OPERATOR)):
    """Schnittstellen (und Agent) von Gerät gid in das Ziel-Gerät verschieben, gid löschen."""
    d = await req.json()
    ziel = int(d.get("ziel") or 0)
    if not ziel or ziel == gid:
        raise HTTPException(400, "Ziel-Gerät wählen")
    with sitzung() as s:
        g, z = s.get(Geraet, gid), s.get(Geraet, ziel)
        if not g or not z:
            raise LookupError("Gerät gibt es nicht")
        for x in s.scalars(select(Schnittstelle).where(Schnittstelle.geraet_id == gid)):
            x.geraet_id, x.primaer = ziel, False
        for a in s.scalars(select(Agent).where(Agent.geraet_id == gid)):
            a.geraet_id = ziel
        for e in s.scalars(select(Ereignis).where(Ereignis.geraet_id == gid)):
            e.geraet_id = ziel
        ereignis(s, ziel, "neu", f"zusammengeführt mit „{g.name}“")
        name = g.name
        s.delete(g)
        s.flush()
        online_aktualisieren(s, [ziel])
    protokoll(ich["name"], "geraet", "zusammengeführt", f"{name} → {ziel}", ip=client_ip(req))
    return {"ok": True, "ziel": ziel}


@router.delete("/geraete/{gid}")
def geraet_loeschen(gid: int, req: Request, ich: dict = Depends(ADMIN)):
    with sitzung() as s:
        g = s.get(Geraet, gid)
        if not g:
            raise LookupError("Gerät gibt es nicht")
        name = g.name
        s.execute(delete(Schnittstelle).where(Schnittstelle.geraet_id == gid))
        s.execute(delete(Ereignis).where(Ereignis.geraet_id == gid))
        for a in s.scalars(select(Agent).where(Agent.geraet_id == gid)):
            a.geraet_id = None
        s.delete(g)
    protokoll(ich["name"], "geraet", "gelöscht", name, ip=client_ip(req))
    return {"ok": True}


@router.post("/geraete/{gid}/schnittstellen")
async def schnittstelle_speichern(gid: int, req: Request, ich: dict = Depends(OPERATOR)):
    d = await req.json()
    mac = netz.mac_norm(d.get("mac"))
    if d.get("mac") and not mac:
        raise HTTPException(400, "MAC-Adresse ungültig")
    ip = str(d.get("ip") or "").strip()
    if ip and not netz.ip_gueltig(ip):
        raise HTTPException(400, "IP-Adresse ungültig")
    if not mac and not ip:
        raise HTTPException(400, "MAC oder IP angeben")
    with sitzung() as s:
        if not s.get(Geraet, gid):
            raise LookupError("Gerät gibt es nicht")
        if mac:
            anders = s.scalars(select(Schnittstelle).where(Schnittstelle.mac == mac, Schnittstelle.id != int(d.get("id") or 0))).first()
            if anders:
                og = s.get(Geraet, anders.geraet_id)
                raise HTTPException(400, f"Die MAC gehört schon zu „{og.name if og else anders.geraet_id}“ – dort entfernen oder Geräte zusammenführen")
        if d.get("id"):
            x = s.get(Schnittstelle, int(d["id"]))
            if not x or x.geraet_id != gid:
                raise LookupError("Schnittstelle gibt es nicht")
        else:
            x = Schnittstelle(geraet_id=gid, quelle="manuell")
            s.add(x)
        nid = d.get("netzwerk_id")
        if nid in ("", None) and ip:
            nw = netzwerk_fuer_ip(list(s.scalars(select(Netzwerk))), ip)
            nid = nw.id if nw else None
        x.name, x.mac, x.ip = str(d.get("name") or "")[:64], mac, ip
        x.hostname = str(d.get("hostname") or "").strip()
        x.mac_hersteller = x.mac_hersteller or netz.mac_hersteller(mac)
        x.netzwerk_id = int(nid) if nid not in ("", None) else None
        x.feste_ip = bool(d.get("feste_ip"))
        if d.get("primaer"):
            for y in s.scalars(select(Schnittstelle).where(Schnittstelle.geraet_id == gid)):
                y.primaer = False
            x.primaer = True
        s.flush()
        if not s.scalar(select(func.count(Schnittstelle.id)).where(Schnittstelle.geraet_id == gid, Schnittstelle.primaer.is_(True))):
            x.primaer = True
    _start_ping(gid)
    return {"ok": True}


@router.delete("/schnittstellen/{sid}")
def schnittstelle_weg(sid: int, ich: dict = Depends(OPERATOR)):
    with sitzung() as s:
        x = s.get(Schnittstelle, sid)
        if not x:
            raise LookupError("Schnittstelle gibt es nicht")
        gid = x.geraet_id
        s.delete(x)
        s.flush()
        online_aktualisieren(s, [gid])
    return {"ok": True}


@router.post("/geraete/{gid}/wecken")
def geraet_wecken(gid: int, req: Request, ich: dict = Depends(OPERATOR)):
    return wecken(gid, ich["name"], client_ip(req))


@router.post("/geraete/{gid}/pruefen")
def geraet_pruefen(gid: int, ich: dict = Depends(LESER)):
    with sitzung() as s:
        ziele = [(x.id, x.ip) for x in s.scalars(select(Schnittstelle).where(Schnittstelle.geraet_id == gid, Schnittstelle.ip != ""))]
    erg = [(i, ip, netz.erreichbar(ip)) for i, ip in ziele]
    with sitzung() as s:
        for i, _, an in erg:
            x = s.get(Schnittstelle, i)
            if x:
                x.online = an
                if an:
                    x.zuletzt = jetzt()
        online_aktualisieren(s, [gid])
    return {"ergebnis": [{"ip": ip, "erreichbar": an} for _, ip, an in erg]}


@router.post("/geraete/{gid}/befehl")
async def geraet_befehl(gid: int, req: Request, ich: dict = Depends(OPERATOR)):
    import agent as agent_mod
    d = await req.json()
    return agent_mod.befehl(gid, str(d.get("befehl") or ""), ich["name"], client_ip(req), d.get("wert"))


@router.get("/ereignisse")
def ereignisse(art: str = "", grenze: int = 200, ich: dict = Depends(LESER)):
    with sitzung() as s:
        q = select(Ereignis, Geraet.name).outerjoin(Geraet, Geraet.id == Ereignis.geraet_id).order_by(Ereignis.zeit.desc())
        if art:
            q = q.where(Ereignis.art == art)
        return {"ereignisse": [{"zeit": iso(e.zeit), "art": e.art, "text": e.text, "geraet_id": e.geraet_id, "geraet": n or ""}
                               for e, n in s.execute(q.limit(min(grenze, 1000))).all()]}


# ------------------------------------------------------------------ Routen: Netzwerke
def _nw_json(s, n: Netzwerk) -> dict:
    return {"id": n.id, "name": n.name, "cidr": n.cidr, "vlan": n.vlan, "beschreibung": n.beschreibung,
            "scan_aktiv": n.scan_aktiv, "scan_intervall": n.scan_intervall, "scan_methode": n.scan_methode,
            "opnsense_interface": n.opnsense_interface, "wol_methode": n.wol_methode, "wol_broadcast": n.wol_broadcast,
            "letzter_scan": iso(n.letzter_scan), "scan_status": n.scan_status, "direkt": netz.direkt_erreichbar(n.cidr),
            "geraete": s.scalar(select(func.count(func.distinct(Schnittstelle.geraet_id))).where(Schnittstelle.netzwerk_id == n.id)) or 0,
            "laeuft": _scan_lock.get(n.id).locked() if n.id in _scan_lock else False}


@router.get("/netzwerke")
def netzwerke(ich: dict = Depends(LESER)):
    with sitzung() as s:
        return {"netzwerke": [_nw_json(s, n) for n in s.scalars(select(Netzwerk).order_by(Netzwerk.name))],
                "eigene": [str(i) for i in netz.eigene_adressen()], "nmap": netz.nmap_da(),
                "opnsense": opnsense.eingerichtet()}


def netzwerk_anlegen_einfach(cidr: str) -> None:
    n = netz.netz(cidr)
    with sitzung() as s:
        if not s.scalars(select(Netzwerk).where(Netzwerk.cidr == str(n))).first():
            s.add(Netzwerk(name=f"Netz {n}", cidr=str(n)))


@router.post("/netzwerke")
async def netzwerk_speichern(req: Request, ich: dict = Depends(ADMIN)):
    d = await req.json()
    try:
        n = netz.netz(str(d.get("cidr", "")))
    except ValueError as e:
        raise HTTPException(400, "Netz ungültig – Schreibweise z. B. 192.168.10.0/24") from e
    if n.version != 4:
        raise HTTPException(400, "Nur IPv4-Netze")
    if n.num_addresses > netz.MAX_HOSTS:
        raise HTTPException(400, f"Netz zu groß (höchstens {netz.MAX_HOSTS} Adressen, also /20)")
    if d.get("scan_methode", "auto") not in ("auto", "nmap", "ping", "opnsense"):
        raise HTTPException(400, "Unbekannte Scan-Methode")
    if d.get("wol_methode", "auto") not in ("auto", "container", "opnsense", "beide"):
        raise HTTPException(400, "Unbekannte WoL-Methode")
    if d.get("wol_broadcast") and not netz.ip_gueltig(d["wol_broadcast"]):
        raise HTTPException(400, "Broadcast-Adresse ungültig")
    with sitzung() as s:
        if d.get("id"):
            x = s.get(Netzwerk, int(d["id"]))
            if not x:
                raise LookupError("Netzwerk gibt es nicht")
        else:
            x = Netzwerk()
            s.add(x)
        x.name = str(d.get("name") or f"Netz {n}").strip()[:128]
        x.cidr = str(n)
        x.vlan = int(d["vlan"]) if str(d.get("vlan") or "").strip().isdigit() else None
        x.beschreibung = str(d.get("beschreibung") or "")
        x.scan_aktiv = bool(d.get("scan_aktiv", True))
        x.scan_intervall = max(1, min(1440, int(d.get("scan_intervall") or 15)))
        x.scan_methode = d.get("scan_methode") or "auto"
        x.opnsense_interface = str(d.get("opnsense_interface") or "").strip()
        x.wol_methode = d.get("wol_methode") or "auto"
        x.wol_broadcast = str(d.get("wol_broadcast") or "").strip()
        s.flush()
        nid = x.id
        # Schnittstellen ohne Netz, die hineinpassen, zuordnen
        for sch in s.scalars(select(Schnittstelle).where(Schnittstelle.netzwerk_id.is_(None), Schnittstelle.ip != "")):
            if netz.im_netz(sch.ip, x.cidr):
                sch.netzwerk_id = nid
        out = _nw_json(s, x)
    protokoll(ich["name"], "netzwerk", "gespeichert", str(n), ip=client_ip(req))
    return out


@router.delete("/netzwerke/{nid}")
def netzwerk_loeschen(nid: int, req: Request, ich: dict = Depends(ADMIN)):
    with sitzung() as s:
        x = s.get(Netzwerk, nid)
        if not x:
            raise LookupError("Netzwerk gibt es nicht")
        for sch in s.scalars(select(Schnittstelle).where(Schnittstelle.netzwerk_id == nid)):
            sch.netzwerk_id = None
        cidr = x.cidr
        s.delete(x)
    protokoll(ich["name"], "netzwerk", "gelöscht", cidr, ip=client_ip(req))
    return {"ok": True}


@router.post("/netzwerke/{nid}/scan")
def netzwerk_scan(nid: int, req: Request, ich: dict = Depends(OPERATOR)):
    return scan(nid, ich["name"])
