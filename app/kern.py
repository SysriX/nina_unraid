"""NINA – Kern: Startkonfiguration, Verschlüsselung, Datenbank-Verbindung, Einstellungen, Protokoll.

Startkonfiguration  <NINA_DATA>/nina.json  (welche Datenbank, ob eingerichtet, Instanz-ID)
Schlüssel           <NINA_DATA>/schluessel.key     (oder Umgebungsvariable NINA_KEY)
Alles andere liegt in der Datenbank (Tabellen ni_*). Das Schema wird über migrationen.py versioniert,
damit neue Container-Versionen eine vorhandene Datenbank selbst aktualisieren können.
Geheimnisse (Passwörter, API-Schlüssel) werden vor dem Speichern mit Fernet verschlüsselt.
"""
from __future__ import annotations

import json
import os
import secrets
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

VERSION = "1.3.0"
DATA = os.environ.get("NINA_DATA", "/config")
KONFIG_DATEI = os.path.join(DATA, "nina.json")
SCHLUESSEL_DATEI = os.path.join(DATA, "schluessel.key")


def jetzt() -> datetime:
    return datetime.now(timezone.utc)


def utc(d: datetime | None) -> datetime | None:
    """SQLite liefert Zeiten ohne Zeitzone zurück – immer als UTC behandeln."""
    if d is None:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def iso(d: datetime | None) -> str | None:
    d = utc(d)
    return d.isoformat() if d else None


def log(*a):
    print("[nina]", *a, flush=True)


# ------------------------------------------------------------------ Startkonfiguration
_konfig_lock = threading.Lock()


def konfig_lesen() -> dict:
    try:
        with open(KONFIG_DATEI, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def konfig_schreiben(k: dict) -> None:
    with _konfig_lock:
        os.makedirs(DATA, exist_ok=True)
        tmp = KONFIG_DATEI + ".neu"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(k, f, indent=2, ensure_ascii=False)
        os.replace(tmp, KONFIG_DATEI)
        try:
            os.chmod(KONFIG_DATEI, 0o600)
        except OSError:
            pass


def instanz_id() -> str:
    """Feste ID dieser Installation (für Home Assistant: ein Eintrag je Instanz)."""
    k = konfig_lesen()
    if not k.get("instanz"):
        k["instanz"] = uuid.uuid4().hex[:12]
        konfig_schreiben(k)
    return k["instanz"]


# ------------------------------------------------------------------ Verschlüsselung
_fernet: Fernet | None = None


def fernet() -> Fernet:
    global _fernet
    if _fernet:
        return _fernet
    key = os.environ.get("NINA_KEY", "").strip()
    if not key:
        if os.path.exists(SCHLUESSEL_DATEI):
            with open(SCHLUESSEL_DATEI, encoding="utf-8") as f:
                key = f.read().strip()
        else:
            os.makedirs(DATA, exist_ok=True)
            key = Fernet.generate_key().decode()
            with open(SCHLUESSEL_DATEI, "w", encoding="utf-8") as f:
                f.write(key + "\n")
            try:
                os.chmod(SCHLUESSEL_DATEI, 0o600)
            except OSError:
                pass
            log("Neuer Schlüssel angelegt:", SCHLUESSEL_DATEI, "– mit sichern, sonst sind gespeicherte Passwörter verloren!")
    _fernet = Fernet(key.encode())
    return _fernet


def verschluesseln(daten: Any) -> str:
    return fernet().encrypt(json.dumps(daten).encode()).decode()


def entschluesseln(token: str | None) -> Any:
    if not token:
        return {}
    try:
        return json.loads(fernet().decrypt(token.encode()))
    except InvalidToken as e:
        raise RuntimeError("Gespeicherte Geheimnisse lassen sich nicht entschlüsseln – falscher Schlüssel?") from e


# ------------------------------------------------------------------ Datenbank
_engine = None
_SessionLocal: sessionmaker | None = None


def db_url(k: dict | None = None) -> str | None:
    k = konfig_lesen() if k is None else k
    db = k.get("db")
    if not db:
        return None
    if db.get("typ") == "sqlite":
        return "sqlite:///" + os.path.join(DATA, db.get("datei") or "nina.db")
    if db.get("typ") == "mariadb":
        from urllib.parse import quote_plus
        pw = entschluesseln(db.get("passwort_enc")).get("p", "") if db.get("passwort_enc") else ""
        return (f"mysql+pymysql://{quote_plus(db['benutzer'])}:{quote_plus(pw)}@{db['host']}:{int(db.get('port') or 3306)}/"
                f"{db['name']}?charset=utf8mb4")
    raise RuntimeError("unbekannter Datenbanktyp")


def engine_bauen(url: str):
    args: dict = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        args["connect_args"] = {"check_same_thread": False, "timeout": 30}
    else:
        args["pool_recycle"] = 1800
    e = create_engine(url, **args)
    if url.startswith("sqlite"):
        from sqlalchemy import event

        @event.listens_for(e, "connect")
        def _pragma(con, _):
            cur = con.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=WAL")
            cur.close()
    return e


def db_starten() -> bool:
    """Verbindet mit der konfigurierten Datenbank und bringt das Schema auf den aktuellen Stand."""
    global _engine, _SessionLocal
    url = db_url()
    if not url:
        return False
    import migrationen
    e = engine_bauen(url)
    migrationen.ausfuehren(e, url)
    _engine = e
    _SessionLocal = sessionmaker(_engine, expire_on_commit=False)
    return True


def engine():
    return _engine


def db_bereit() -> bool:
    return _SessionLocal is not None


def db_testen(url: str) -> str:
    e = engine_bauen(url)
    try:
        with e.connect() as c:
            c.execute(text("SELECT 1"))
        return "ok"
    finally:
        e.dispose()


@contextmanager
def sitzung() -> Session:
    if not _SessionLocal:
        raise RuntimeError("Datenbank ist noch nicht eingerichtet")
    s = _SessionLocal()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def einstellung(schluessel: str, standard: Any = None) -> Any:
    from modelle import Einstellung
    with sitzung() as s:
        e = s.get(Einstellung, schluessel)
        return e.wert if e else standard


def einstellung_setzen(schluessel: str, wert: Any) -> None:
    from modelle import Einstellung
    with sitzung() as s:
        e = s.get(Einstellung, schluessel)
        if e:
            e.wert = wert
        else:
            s.add(Einstellung(schluessel=schluessel, wert=wert))


def geheim(schluessel: str) -> dict:
    """Verschlüsselt gespeicherte Zugangsdaten (Einstellung '<schluessel>.geheim')."""
    return entschluesseln(einstellung(schluessel + ".geheim", "")) or {}


def geheim_setzen(schluessel: str, werte: dict) -> None:
    alt = geheim(schluessel)
    for k, v in werte.items():
        if v is None:
            continue           # None = unverändert lassen
        if v == "":
            alt.pop(k, None)
        else:
            alt[k] = v
    einstellung_setzen(schluessel + ".geheim", verschluesseln(alt) if alt else "")


def protokoll(benutzer: str, bereich: str, aktion: str, ziel: str = "", ok: bool = True, details: str = "",
              ip: str = "") -> None:
    from modelle import Protokoll
    try:
        with sitzung() as s:
            s.add(Protokoll(benutzer=benutzer, bereich=bereich, aktion=aktion, ziel=str(ziel)[:512], ok=ok,
                            details=str(details)[:8000], ip=ip))
    except Exception as e:  # noqa: BLE001  – Protokoll darf nie die eigentliche Aktion abbrechen
        log("Protokoll fehlgeschlagen:", e)


def zufall(n: int = 32) -> str:
    return secrets.token_urlsafe(n)
