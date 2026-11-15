"""Zeitplan der automatischen Läufe: Netzwerk-Scan, OPNsense-Abfrage, Agent-Abgleich.

Einstellung "zeitplan" (JSON):
  scan      {aktiv, von, bis, tage}                 – Intervall je Netzwerk (Netzwerk.scan_intervall)
  opnsense  {aktiv, intervall, von, bis, tage}      – ARP + DHCP der OPNsense über alle Netze
  agent     {aktiv, intervall, von, bis, tage, offline_nach, neu_melden}
von/bis = "HH:MM" (leer = ganztägig, über Mitternacht erlaubt), tage = Liste 0–6 (Mo–So, leer = alle).
"""
from __future__ import annotations

import threading
import time
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select

import kern
from kern import iso, protokoll, sitzung
from zugang import ADMIN, LESER, OPERATOR, client_ip

router = APIRouter(prefix="/api/zeitplan")

STANDARD = {
    "scan": {"aktiv": True, "von": "", "bis": "", "tage": []},
    "opnsense": {"aktiv": True, "intervall": 5, "von": "", "bis": "", "tage": []},
    "agent": {"aktiv": True, "intervall": 5, "von": "", "bis": "", "tage": [], "offline_nach": 10, "neu_melden": False},
}
QUELLEN = {"scan": "Netzwerk-Scan", "opnsense": "OPNsense-Abfrage", "agent": "Agent-Abgleich"}

# Laufzustand (nur im Speicher): quelle -> {zuletzt, dauer, ok, ergebnis, laeuft}
ZUSTAND: dict[str, dict] = {q: {"zuletzt": None, "dauer": 0, "ok": None, "ergebnis": "", "laeuft": False} for q in QUELLEN}
_locks = {q: threading.Lock() for q in QUELLEN}


def konfig() -> dict:
    gespeichert = kern.einstellung("zeitplan", {}) or {} if kern.db_bereit() else {}
    return {q: {**STANDARD[q], **(gespeichert.get(q) or {})} for q in STANDARD}


def _minuten(hhmm: str) -> int | None:
    try:
        h, m = (int(x) for x in str(hhmm).strip().split(":"))
    except (ValueError, AttributeError):
        return None
    return h * 60 + m if 0 <= h <= 23 and 0 <= m <= 59 else None


def im_fenster(c: dict, jetzt: datetime | None = None) -> bool:
    jetzt = jetzt or datetime.now()
    if c.get("tage") and jetzt.weekday() not in c["tage"]:
        return False
    a, b = _minuten(c.get("von") or ""), _minuten(c.get("bis") or "")
    if a is None or b is None or a == b:
        return True
    m = jetzt.hour * 60 + jetzt.minute
    return a <= m < b if a < b else (m >= a or m < b)     # über Mitternacht


def faellig(quelle: str, c: dict) -> bool:
    if not c.get("aktiv") or not im_fenster(c):
        return False
    z = ZUSTAND[quelle]["zuletzt"]
    return z is None or time.time() - z >= max(1, int(c.get("intervall") or 5)) * 60


def ausfuehren(quelle: str, wer: str = "zeitplan") -> dict:
    """Einen Lauf ausführen (auch „Jetzt ausführen“). Ergebnis landet im ZUSTAND."""
    lock = _locks[quelle]
    if not lock.acquire(blocking=False):
        raise HTTPException(409, f"{QUELLEN[quelle]} läuft gerade")
    z = ZUSTAND[quelle]
    z["laeuft"], start = True, time.time()
    try:
        erg = {"scan": _scan, "opnsense": _opnsense, "agent": _agent}[quelle](wer)
        z.update(ok=True, ergebnis=erg)
    except Exception as e:  # noqa: BLE001
        z.update(ok=False, ergebnis=f"Fehler: {e}")
        kern.log(f"{QUELLEN[quelle]}:", e)
    finally:
        z.update(zuletzt=time.time(), dauer=round(time.time() - start, 1), laeuft=False)
        lock.release()
    if wer != "zeitplan":
        protokoll(wer, "zeitplan", f"{QUELLEN[quelle]} von Hand", ok=bool(z["ok"]), details=z["ergebnis"])
    return dict(z)


def _scan(wer: str) -> str:
    """Alle Netzwerke mit aktivem Scan, deren Intervall abgelaufen ist (von Hand: alle aktiven)."""
    import inventar
    from modelle import Netzwerk
    with sitzung() as s:
        netze = [(n.id, n.name, n.letzter_scan, n.scan_intervall) for n in s.scalars(select(Netzwerk).where(Netzwerk.scan_aktiv.is_(True)))]
    teile = []
    for nid, name, letzter, intervall in netze:
        if wer == "zeitplan" and letzter and (kern.jetzt() - kern.utc(letzter)).total_seconds() < intervall * 60:
            continue
        try:
            r = inventar.scan(nid, wer)
            teile.append(f"{name}: {r.get('status')}")
        except HTTPException as e:
            teile.append(f"{name}: {e.detail}")
    return "; ".join(teile) or "kein Netz fällig"


def _scan_faellig() -> bool:
    from modelle import Netzwerk
    with sitzung() as s:
        return any(not n.letzter_scan or (kern.jetzt() - kern.utc(n.letzter_scan)).total_seconds() >= n.scan_intervall * 60
                   for n in s.scalars(select(Netzwerk).where(Netzwerk.scan_aktiv.is_(True))))


def _opnsense(wer: str) -> str:
    import inventar
    import opnsense
    if not opnsense.eingerichtet():
        return "OPNsense ist nicht eingerichtet"
    r = inventar.opnsense_abgleich()
    return f"{r.get('gefunden', 0)} bekannt, {r.get('neu', 0)} neu, {r.get('geaendert', 0)} IP geändert"


def _agent(wer: str) -> str:
    import agent
    c = konfig()["agent"]
    r = agent.abgleich(int(c.get("offline_nach") or 10), bool(c.get("neu_melden")))
    return (f"{r['agenten']} Agenten, {r['online']} online, {r['verknuepft']} neu unter „Nicht zugewiesen“, {r['offline']} offline gesetzt"
            + (", um neue Meldung gebeten" if r.get("gemeldet") else ""))


def schleife_einmal() -> None:
    """Vom Hintergrund-Takt (alle 30 s) aufgerufen."""
    if not kern.db_bereit():
        return
    c = konfig()
    if c["scan"]["aktiv"] and im_fenster(c["scan"]) and not _locks["scan"].locked() and _scan_faellig():
        try:
            ausfuehren("scan")
        except HTTPException:
            pass
    for q in ("opnsense", "agent"):
        if faellig(q, c[q]) and not _locks[q].locked():
            try:
                ausfuehren(q)
            except HTTPException:
                pass


# ------------------------------------------------------------------ Routen
def _naechster(q: str, c: dict) -> str | None:
    if not c.get("aktiv"):
        return None
    z = ZUSTAND[q]["zuletzt"]
    t = time.time() if z is None else z + max(1, int(c.get("intervall") or 5)) * 60
    return iso(datetime.fromtimestamp(max(t, time.time()), tz=kern.jetzt().tzinfo))


@router.get("")
def zeitplan(ich: dict = Depends(LESER)):
    from modelle import Netzwerk
    c = konfig()
    with sitzung() as s:
        netze = [{"id": n.id, "name": n.name, "cidr": n.cidr, "scan_aktiv": n.scan_aktiv, "scan_intervall": n.scan_intervall,
                  "scan_methode": n.scan_methode, "letzter_scan": iso(n.letzter_scan), "scan_status": n.scan_status,
                  "naechster": iso(datetime.fromtimestamp(
                      max(time.time(), (kern.utc(n.letzter_scan).timestamp() if n.letzter_scan else 0) + n.scan_intervall * 60),
                      tz=kern.jetzt().tzinfo)) if n.scan_aktiv else None}
                 for n in s.scalars(select(Netzwerk).order_by(Netzwerk.name))]
    zustand = {}
    for q in QUELLEN:
        z = ZUSTAND[q]
        zustand[q] = {"titel": QUELLEN[q], "zuletzt": iso(datetime.fromtimestamp(z["zuletzt"], tz=kern.jetzt().tzinfo)) if z["zuletzt"] else None,
                      "dauer": z["dauer"], "ok": z["ok"], "ergebnis": z["ergebnis"], "laeuft": z["laeuft"],
                      "im_fenster": im_fenster(c[q]),
                      "naechster": _naechster(q, c[q]) if q != "scan" else None}
    return {"zeitplan": c, "zustand": zustand, "netze": netze}


def _pruefen(q: str, d: dict) -> dict:
    out = {"aktiv": bool(d.get("aktiv"))}
    for f in ("von", "bis"):
        v = str(d.get(f) or "").strip()
        if v and _minuten(v) is None:
            raise HTTPException(400, f"{QUELLEN[q]}: Uhrzeit „{v}“ ungültig (HH:MM)")
        out[f] = v
    out["tage"] = sorted({int(t) for t in d.get("tage") or [] if str(t).isdigit() and 0 <= int(t) <= 6})
    if q != "scan":
        out["intervall"] = max(1, min(1440, int(d.get("intervall") or 5)))
    if q == "agent":
        out["offline_nach"] = max(2, min(1440, int(d.get("offline_nach") or 10)))
        out["neu_melden"] = bool(d.get("neu_melden"))
    return out


@router.post("")
async def speichern(req: Request, ich: dict = Depends(ADMIN)):
    from modelle import Netzwerk
    d = await req.json()
    alt = konfig()
    neu = {q: _pruefen(q, {**alt[q], **d[q]}) if isinstance(d.get(q), dict) else alt[q] for q in QUELLEN}
    kern.einstellung_setzen("zeitplan", neu)
    for n in d.get("netze") or []:          # Intervalle je Netzwerk gleich mit
        with sitzung() as s:
            x = s.get(Netzwerk, int(n.get("id") or 0))
            if x:
                x.scan_aktiv = bool(n.get("scan_aktiv"))
                x.scan_intervall = max(1, min(1440, int(n.get("scan_intervall") or 15)))
    protokoll(ich["name"], "einstellungen", "Zeitplan gespeichert", ip=client_ip(req))
    return {"ok": True}


@router.post("/{quelle}/jetzt")
def jetzt_ausfuehren(quelle: str, req: Request, ich: dict = Depends(OPERATOR)):
    if quelle not in QUELLEN:
        raise LookupError("Unbekannte Quelle")
    z = ausfuehren(quelle, ich["name"])
    return {"ok": z["ok"], "ergebnis": z["ergebnis"], "dauer": z["dauer"]}
