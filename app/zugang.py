"""Einrichtung beim ersten Start, Anmeldung, Benutzer und API-Schlüssel (für Home Assistant).

Einrichtung: geschützt durch einen Code im Container-Log (oder NINA_SETUP_TOKEN).
  1. Datenbank: eingebaut (SQLite) oder MariaDB (vorhanden oder mit Root-Zugang anlegen)
  2. Admin-Benutzer anlegen (oder vorhandene Benutzer aus der Datenbank übernehmen)
Rollen: leser (nur ansehen) < operator (wecken, Befehle, Scan) < admin (alles).
API-Schlüssel: Bearer-Token, nur der SHA-256-Hash liegt in der Datenbank.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import time
from datetime import timedelta
from urllib.parse import quote_plus

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import func, select

import kern
from kern import jetzt, protokoll, sitzung
from modelle import ApiSchluessel, Benutzer, Sitzung

COOKIE = "ni_sitzung"
DAUER = timedelta(hours=12)
ROLLEN = {"leser": 1, "operator": 2, "admin": 3}
CODE_DATEI = os.path.join(kern.DATA, "einrichtungs-code.txt")
_ph = PasswordHasher()
_fehl: dict[str, list] = {}
_code: str | None = None

router = APIRouter()


# ------------------------------------------------------------------ Hilfen
def pw_hash(pw: str) -> str:
    return _ph.hash(pw)


def pw_pruefen(h: str | None, pw: str) -> bool:
    if not h:
        return False
    try:
        return _ph.verify(h, pw)
    except (VerifyMismatchError, Exception):  # noqa: BLE001
        return False


def client_ip(req: Request) -> str:
    return req.client.host if req.client else ""


def https(req: Request) -> bool:
    return req.url.scheme == "https" or req.headers.get("x-forwarded-proto", "").lower() == "https"


def _bremse(ip: str) -> None:
    n, seit = _fehl.get(ip, [0, time.time()])
    if n >= 5 and time.time() - seit < 300:
        raise HTTPException(429, "Zu viele Fehlversuche – bitte 5 Minuten warten")


def _fehler(ip: str) -> None:
    n, seit = _fehl.get(ip, [0, time.time()])
    if time.time() - seit >= 300:
        n, seit = 0, time.time()
    _fehl[ip] = [n + 1, seit]


def _hash(tok: str) -> str:
    return hashlib.sha256(tok.encode()).hexdigest()


def eingerichtet() -> bool:
    return bool(kern.konfig_lesen().get("eingerichtet")) and kern.db_bereit()


def code() -> str:
    global _code
    if _code:
        return _code
    _code = os.environ.get("NINA_SETUP_TOKEN", "").strip()
    if not _code:
        if os.path.exists(CODE_DATEI):
            with open(CODE_DATEI, encoding="utf-8") as f:
                _code = f.read().strip()
        else:
            abc = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
            _code = "-".join("".join(secrets.choice(abc) for _ in range(4)) for _ in range(3))
            os.makedirs(kern.DATA, exist_ok=True)
            with open(CODE_DATEI, "w", encoding="utf-8") as f:
                f.write(_code)
    return _code


def code_melden():
    if not eingerichtet():
        c = code()
        kern.log("=" * 60)
        kern.log(f"EINRICHTUNG: Code für den Assistenten:  {c}")
        kern.log(f"(steht auch in {CODE_DATEI})")
        kern.log("=" * 60)


# ------------------------------------------------------------------ Abhängigkeiten
def aktueller(req: Request) -> dict:
    """Angemeldeter Benutzer (Cookie) oder API-Schlüssel (Authorization: Bearer …)."""
    if not kern.db_bereit():
        raise HTTPException(409, "NINA ist noch nicht eingerichtet")
    auth = req.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        h = _hash(auth[7:].strip())
        with sitzung() as s:
            k = s.scalars(select(ApiSchluessel).where(ApiSchluessel.token_hash == h)).first()
            if not k:
                _fehler(client_ip(req))
                raise HTTPException(401, "API-Schlüssel ungültig")
            if not k.zuletzt or (jetzt() - kern.utc(k.zuletzt)).total_seconds() > 300:
                k.zuletzt, k.zuletzt_ip = jetzt(), client_ip(req)
            return {"id": -k.id, "name": f"api:{k.name}", "anzeigename": k.name, "rolle": k.rolle, "api": True}
    tok = req.cookies.get(COOKIE)
    if not tok:
        raise HTTPException(401, "Nicht angemeldet")
    with sitzung() as s:
        si = s.get(Sitzung, _hash(tok))
        if not si or kern.utc(si.ablauf) < jetzt():
            raise HTTPException(401, "Sitzung abgelaufen")
        b = s.get(Benutzer, si.benutzer_id)
        if not b or not b.aktiv:
            raise HTTPException(401, "Benutzer gesperrt")
        return {"id": b.id, "name": b.name, "anzeigename": b.anzeigename or b.name, "rolle": b.rolle, "api": False}


def rolle(mindestens: str):
    def pruefen(ich: dict = Depends(aktueller)) -> dict:
        if ROLLEN.get(ich["rolle"], 0) < ROLLEN[mindestens]:
            raise HTTPException(403, f"Dafür ist die Rolle „{mindestens}“ nötig")
        return ich
    return pruefen


LESER, OPERATOR, ADMIN = rolle("leser"), rolle("operator"), rolle("admin")


# ------------------------------------------------------------------ Anmeldung
@router.get("/api/status")
def status():
    k = kern.konfig_lesen()
    return {"eingerichtet": eingerichtet(), "db": (k.get("db") or {}).get("typ"), "version": kern.VERSION}


@router.post("/api/anmeldung")
async def anmelden(req: Request):
    ip = client_ip(req)
    _bremse(ip)
    d = await req.json()
    name, pw = str(d.get("benutzer", "")).strip(), str(d.get("passwort", ""))
    with sitzung() as s:
        b = s.scalars(select(Benutzer).where(func.lower(Benutzer.name) == name.lower())).first()
        if not b or not b.aktiv or not pw_pruefen(b.pw_hash, pw):
            _fehler(ip)
            protokoll(name, "anmeldung", "fehlgeschlagen", ok=False, ip=ip)
            raise HTTPException(401, "Benutzer oder Passwort falsch")
        tok = secrets.token_urlsafe(32)
        s.add(Sitzung(token_hash=_hash(tok), benutzer_id=b.id, ablauf=jetzt() + DAUER, ip=ip))
        b.letzte_anmeldung = jetzt()
        bname = b.name
    _fehl.pop(ip, None)
    protokoll(bname, "anmeldung", "angemeldet", ip=ip)
    resp = JSONResponse({"ok": True})
    resp.set_cookie(COOKIE, tok, httponly=True, samesite="lax", secure=https(req),
                    max_age=int(DAUER.total_seconds()), path="/")
    return resp


@router.post("/api/abmelden")
def abmelden(req: Request):
    tok = req.cookies.get(COOKIE)
    if tok and kern.db_bereit():
        with sitzung() as s:
            si = s.get(Sitzung, _hash(tok))
            if si:
                s.delete(si)
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(COOKIE, path="/")
    return resp


@router.get("/api/ich")
def ich(ich: dict = Depends(LESER)):
    return ich


@router.post("/api/ich/passwort")
async def eigenes_passwort(req: Request, ich: dict = Depends(LESER)):
    if ich.get("api"):
        raise HTTPException(400, "Nicht für API-Schlüssel")
    d = await req.json()
    if len(d.get("neu", "")) < 10:
        raise HTTPException(400, "Das neue Passwort braucht mindestens 10 Zeichen")
    with sitzung() as s:
        b = s.get(Benutzer, ich["id"])
        if not pw_pruefen(b.pw_hash, d.get("alt", "")):
            raise HTTPException(400, "Altes Passwort falsch")
        b.pw_hash = pw_hash(d["neu"])
    protokoll(ich["name"], "benutzer", "eigenes Passwort geändert", ip=client_ip(req))
    return {"ok": True}


# ------------------------------------------------------------------ Benutzer (admin)
def _b_json(b: Benutzer) -> dict:
    return {"id": b.id, "name": b.name, "anzeigename": b.anzeigename, "rolle": b.rolle, "aktiv": b.aktiv,
            "erstellt": kern.iso(b.erstellt), "letzte_anmeldung": kern.iso(b.letzte_anmeldung)}


@router.get("/api/benutzer")
def benutzer_liste(ich: dict = Depends(ADMIN)):
    with sitzung() as s:
        return {"benutzer": [_b_json(b) for b in s.scalars(select(Benutzer).order_by(Benutzer.name))]}


@router.post("/api/benutzer")
async def benutzer_speichern(req: Request, ich: dict = Depends(ADMIN)):
    d = await req.json()
    if d.get("rolle") not in ROLLEN:
        raise HTTPException(400, "Unbekannte Rolle")
    with sitzung() as s:
        if d.get("id"):
            b = s.get(Benutzer, int(d["id"]))
            if not b:
                raise LookupError("Benutzer gibt es nicht")
            if b.id == ich["id"] and (d["rolle"] != "admin" or not d.get("aktiv", True)):
                raise HTTPException(400, "Die eigene Admin-Rolle kann man sich nicht selbst nehmen")
        else:
            name = str(d.get("name", "")).strip()
            if not re.fullmatch(r"[A-Za-z0-9._@-]{2,64}", name):
                raise HTTPException(400, "Benutzername: 2–64 Zeichen, nur Buchstaben, Ziffern, . _ @ -")
            if s.scalars(select(Benutzer).where(func.lower(Benutzer.name) == name.lower())).first():
                raise HTTPException(400, "Den Benutzer gibt es schon")
            if len(d.get("passwort", "")) < 10:
                raise HTTPException(400, "Passwort: mindestens 10 Zeichen")
            b = Benutzer(name=name)
            s.add(b)
        b.anzeigename = str(d.get("anzeigename", "")).strip()
        b.rolle = d["rolle"]
        b.aktiv = bool(d.get("aktiv", True))
        if d.get("passwort"):
            if len(d["passwort"]) < 10:
                raise HTTPException(400, "Passwort: mindestens 10 Zeichen")
            b.pw_hash = pw_hash(d["passwort"])
        s.flush()
        out = _b_json(b)
    protokoll(ich["name"], "benutzer", "gespeichert", out["name"], ip=client_ip(req))
    return out


@router.delete("/api/benutzer/{bid}")
def benutzer_loeschen(bid: int, req: Request, ich: dict = Depends(ADMIN)):
    if bid == ich["id"]:
        raise HTTPException(400, "Sich selbst löschen geht nicht")
    with sitzung() as s:
        b = s.get(Benutzer, bid)
        if not b:
            raise LookupError("Benutzer gibt es nicht")
        name = b.name
        s.delete(b)
    protokoll(ich["name"], "benutzer", "gelöscht", name, ip=client_ip(req))
    return {"ok": True}


# ------------------------------------------------------------------ API-Schlüssel (admin)
@router.get("/api/schluessel")
def schluessel_liste(ich: dict = Depends(ADMIN)):
    with sitzung() as s:
        return {"schluessel": [{"id": k.id, "name": k.name, "anfang": k.anfang, "rolle": k.rolle,
                                "erstellt": kern.iso(k.erstellt), "zuletzt": kern.iso(k.zuletzt), "zuletzt_ip": k.zuletzt_ip}
                               for k in s.scalars(select(ApiSchluessel).order_by(ApiSchluessel.name))]}


@router.post("/api/schluessel")
async def schluessel_neu(req: Request, ich: dict = Depends(ADMIN)):
    d = await req.json()
    name = str(d.get("name") or "Home Assistant").strip()[:128]
    r = d.get("rolle") or "operator"
    if r not in ROLLEN:
        raise HTTPException(400, "Unbekannte Rolle")
    tok = "ni_" + secrets.token_urlsafe(32)
    with sitzung() as s:
        s.add(ApiSchluessel(name=name, token_hash=_hash(tok), anfang=tok[:8], rolle=r))
    protokoll(ich["name"], "api", "Schlüssel erzeugt", name, ip=client_ip(req))
    return {"token": tok, "name": name}


@router.delete("/api/schluessel/{kid}")
def schluessel_weg(kid: int, req: Request, ich: dict = Depends(ADMIN)):
    with sitzung() as s:
        k = s.get(ApiSchluessel, kid)
        if not k:
            raise LookupError("Schlüssel gibt es nicht")
        name = k.name
        s.delete(k)
    protokoll(ich["name"], "api", "Schlüssel gelöscht", name, ip=client_ip(req))
    return {"ok": True}


# ------------------------------------------------------------------ Einrichtung
def _e_pruefen(req: Request):
    if eingerichtet():
        raise HTTPException(409, "NINA ist bereits eingerichtet")
    if not hmac.compare_digest(req.headers.get("x-ni-einrichtung", ""), code()):
        raise HTTPException(403, "Einrichtungs-Code falsch – er steht im Log des Containers")


@router.post("/api/einrichtung/code")
def e_code(req: Request):
    _e_pruefen(req)
    vorhanden = 0
    if kern.db_bereit():
        with sitzung() as s:
            vorhanden = s.scalar(select(func.count(Benutzer.id))) or 0
    return {"ok": True, "db_vorhanden": kern.db_bereit(), "benutzer": vorhanden}


def _mariadb_url(d, benutzer=None, pw=None, db=True):
    return (f"mysql+pymysql://{quote_plus(benutzer or d['benutzer'])}:{quote_plus(pw if pw is not None else d.get('passwort', ''))}"
            f"@{d['host']}:{int(d.get('port') or 3306)}/{d['name'] if db else ''}?charset=utf8mb4")


@router.post("/api/einrichtung/db")
async def e_db(req: Request):
    _e_pruefen(req)
    d = await req.json()
    typ = d.get("typ", "sqlite")
    k = kern.konfig_lesen()
    if typ == "sqlite":
        k["db"] = {"typ": "sqlite", "datei": "nina.db"}
    elif typ == "mariadb":
        for f in ("host", "name", "benutzer"):
            if not str(d.get(f, "")).strip():
                raise HTTPException(400, f"Feld „{f}“ fehlt")
        if not re.fullmatch(r"[A-Za-z0-9_]{1,64}", d["name"]) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,32}", d["benutzer"]):
            raise HTTPException(400, "Datenbank-/Benutzername: nur Buchstaben, Ziffern und _")
        if d.get("anlegen"):
            from sqlalchemy import text
            root = kern.engine_bauen(_mariadb_url(d, d.get("root_benutzer") or "root", d.get("root_passwort", ""), db=False))
            try:
                with root.begin() as c:
                    c.execute(text(f"CREATE DATABASE IF NOT EXISTS `{d['name']}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"))
                    c.execute(text(f"CREATE USER IF NOT EXISTS '{d['benutzer']}'@'%' IDENTIFIED BY :pw"), {"pw": d.get("passwort", "")})
                    c.execute(text(f"GRANT ALL PRIVILEGES ON `{d['name']}`.* TO '{d['benutzer']}'@'%'"))
                    c.execute(text("FLUSH PRIVILEGES"))
            except Exception as e:  # noqa: BLE001
                raise HTTPException(400, f"Anlegen fehlgeschlagen: {e}") from e
            finally:
                root.dispose()
        try:
            kern.db_testen(_mariadb_url(d))
        except Exception as e:  # noqa: BLE001
            raise HTTPException(400, f"Verbindung fehlgeschlagen: {e}") from e
        if d.get("nur_testen"):
            return {"ok": True}
        k["db"] = {"typ": "mariadb", "host": d["host"], "port": int(d.get("port") or 3306), "name": d["name"],
                   "benutzer": d["benutzer"], "passwort_enc": kern.verschluesseln({"p": d.get("passwort", "")})}
    else:
        raise HTTPException(400, "Unbekannter Datenbanktyp")
    kern.konfig_schreiben(k)
    try:
        kern.db_starten()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"Datenbank: {e}") from e
    with sitzung() as s:
        n = s.scalar(select(func.count(Benutzer.id))) or 0
    return {"ok": True, "benutzer": n}


@router.post("/api/einrichtung/abschluss")
async def e_abschluss(req: Request):
    _e_pruefen(req)
    if not kern.db_bereit():
        raise HTTPException(400, "Erst die Datenbank einrichten")
    d = await req.json()
    with sitzung() as s:
        n = s.scalar(select(func.count(Benutzer.id))) or 0
        if d.get("uebernehmen") and n:
            pass
        else:
            name = str(d.get("benutzer", "")).strip()
            if not re.fullmatch(r"[A-Za-z0-9._@-]{2,64}", name):
                raise HTTPException(400, "Benutzername: 2–64 Zeichen, nur Buchstaben, Ziffern, . _ @ -")
            if len(d.get("passwort", "")) < 10:
                raise HTTPException(400, "Passwort: mindestens 10 Zeichen")
            b = s.scalars(select(Benutzer).where(func.lower(Benutzer.name) == name.lower())).first()
            if not b:
                b = Benutzer(name=name)
                s.add(b)
            b.anzeigename, b.rolle, b.aktiv, b.pw_hash = d.get("anzeigename") or name, "admin", True, pw_hash(d["passwort"])
    if d.get("netzwerk"):
        import inventar
        try:
            inventar.netzwerk_anlegen_einfach(d["netzwerk"])
        except Exception as e:  # noqa: BLE001
            kern.log("Erstes Netzwerk nicht angelegt:", e)
    k = kern.konfig_lesen()
    k["eingerichtet"] = True
    kern.konfig_schreiben(k)
    kern.instanz_id()
    try:
        os.remove(CODE_DATEI)
    except OSError:
        pass
    protokoll("einrichtung", "system", "Einrichtung abgeschlossen", ip=client_ip(req))
    return {"ok": True}
