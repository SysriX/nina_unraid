"""Erkennung von Sensoren und Befehlen über Namensmuster.

Ein Muster ist ein Platzhalter-Ausdruck (* und ?, ohne Groß/Klein) oder ein regulärer Ausdruck mit Präfix "re:".
Geprüft wird gegen den Schlüssel (object_id) und den Namen des Sensors bzw. Befehls. Das erste passende
aktive Muster (nach Reihenfolge) gewinnt. Ergebnis: Kategorie, Bezeichnung, Einheit, Geräteklasse,
state_class, Symbol, ob es an Home Assistant geht und ob ein Befehl eine Rückfrage braucht.
"""
from __future__ import annotations

import fnmatch
import re
import threading

from sqlalchemy import select

import kern

S, B = "sensor", "befehl"


def _m(ziel, reihenfolge, muster, kategorie, bezeichnung, einheit="", device_class="", state_class="", icon="",
       importieren=True, gefahr=False):
    return dict(ziel=ziel, reihenfolge=reihenfolge, muster=muster, kategorie=kategorie, bezeichnung=bezeichnung,
                einheit=einheit, device_class=device_class, state_class=state_class, icon=icon,
                importieren=importieren, gefahr=gefahr, aktiv=True)


# Vorgaben passend zu den Sensor-/Befehlsnamen von HASS.Agent (2.x / .NET)
STANDARD = [
    # HASS.Agent .NET10 (Schlüssel wie cpu_usage, logged_in_user …)
    _m(S, 1, "logged_in_users", "benutzer_anzahl", "Angemeldete Benutzer (Anzahl)", "", "", "measurement", "mdi:account-multiple"),
    _m(S, 2, "*loggedinuser", "benutzer", "Angemeldeter Benutzer", "", "", "", "mdi:account"),
    _m(S, 3, "*memory*avail*", "speicher_frei", "Freier Arbeitsspeicher", "MiB", "data_size", "measurement", "mdi:memory"),
    _m(S, 4, "system_drive_free_percent", "datentraeger", "Systemlaufwerk frei", "%", "", "measurement", "mdi:harddisk"),
    _m(S, 5, "system_drive", "datentraeger_frei", "Systemlaufwerk frei (GiB)", "GiB", "data_size", "measurement", "mdi:harddisk"),
    _m(S, 6, "drive_health", "datentraeger_zustand", "Laufwerkszustand", icon="mdi:harddisk"),
    _m(S, 7, "boot_time", "start", "Letzter Start", "", "timestamp", "", "mdi:clock-start"),
    _m(S, 8, "*gpu*usage*", "gpu", "GPU-Last", "%", "", "measurement", "mdi:expansion-card"),
    _m(S, 9, "rdp_sessions", "rdp", "RDP-Sitzungen", "", "", "measurement", "mdi:remote-desktop"),
    _m(S, 9, "session_locked", "gesperrt", "Sitzung gesperrt", icon="mdi:lock-check"),
    _m(S, 9, "user_present", "anwesend", "Benutzer anwesend", icon="mdi:account-check"),
    _m(S, 9, "pending_reboot", "neustart_ausstehend", "Neustart ausstehend", icon="mdi:update"),
    _m(S, 9, "sleep_blocked", "energiesparen_blockiert", "Energiesparen blockiert", icon="mdi:sleep-off"),
    _m(S, 9, "last_shutdown_reason", "shutdown_grund", "Letzter Shutdown-Grund", icon="mdi:power-plug-off"),
    _m(S, 9, "last_wake_reason", "weck_grund", "Letzter Weckgrund", icon="mdi:alarm"),
    _m(S, 9, "event_log_errors_recent", "fehler", "Ereignisprotokoll-Fehler", "", "", "measurement", "mdi:alert-circle"),
    _m(S, 9, "vpn_connected", "vpn", "VPN verbunden", icon="mdi:vpn"),
    _m(S, 9, "network_address", "netz", "Netzwerkadresse", icon="mdi:ip-network"),
    _m(S, 9, "power_status", "energie", "Stromversorgung", icon="mdi:power-plug"),
    _m(S, 9, "uptime_seconds", "laufzeit", "Laufzeit", "s", "duration", "", "mdi:timer-outline"),
    _m(S, 9, "idle_time_seconds", "aktivitaet", "Leerlauf seit", "s", "duration", "", "mdi:account-clock"),
    _m(B, 1, "*monitoroff*", "bildschirm_aus", "Bildschirm aus", icon="mdi:monitor-off"),
    _m(B, 2, "*restartcancel*", "restart_cancel", "Herunterfahren abbrechen", icon="mdi:cancel"),
    _m(B, 3, "*volumeup*", "lauter", "Lauter", icon="mdi:volume-plus"),
    _m(B, 4, "*volumedown*", "leiser", "Leiser", icon="mdi:volume-minus"),
    _m(S, 10, "*cpu*temp*", "temperatur", "CPU-Temperatur", "°C", "temperature", "measurement", "mdi:thermometer"),
    _m(S, 11, "*gpu*temp*", "temperatur", "GPU-Temperatur", "°C", "temperature", "measurement", "mdi:thermometer"),
    _m(S, 12, "*gpu*load*", "gpu", "GPU-Last", "%", "", "measurement", "mdi:expansion-card"),
    _m(S, 13, "*cpu*", "cpu", "CPU-Last", "%", "", "measurement", "mdi:cpu-64-bit"),
    _m(S, 20, "*memory*", "speicher", "Arbeitsspeicher", "%", "", "measurement", "mdi:memory"),
    _m(S, 21, "*ram*", "speicher", "Arbeitsspeicher", "%", "", "measurement", "mdi:memory"),
    _m(S, 30, "*storage*", "datentraeger", "Datenträger", "", "", "", "mdi:harddisk"),
    _m(S, 31, "*disk*", "datentraeger", "Datenträger", "", "", "", "mdi:harddisk"),
    _m(S, 32, "*drive*", "datentraeger", "Laufwerk", "", "", "", "mdi:harddisk"),
    _m(S, 40, "*lastboot*", "start", "Letzter Start", "", "timestamp", "", "mdi:restart"),
    _m(S, 41, "*uptime*", "laufzeit", "Laufzeit", "", "", "", "mdi:timer-outline"),
    _m(S, 42, "*lastactive*", "aktivitaet", "Letzte Aktivität", "", "timestamp", "", "mdi:account-clock"),
    _m(S, 43, "*idle*", "aktivitaet", "Leerlauf", "", "", "", "mdi:sleep"),
    _m(S, 50, "*loggeduser*", "benutzer", "Angemeldeter Benutzer", "", "", "", "mdi:account"),
    _m(S, 51, "*currentuser*", "benutzer", "Angemeldeter Benutzer", "", "", "", "mdi:account"),
    _m(S, 52, "*session*", "sitzung", "Sitzung", "", "", "", "mdi:monitor-account"),
    _m(S, 53, "*activewindow*", "fenster", "Aktives Fenster", "", "", "", "mdi:application-outline"),
    _m(S, 60, "*battery*", "akku", "Akku", "%", "battery", "measurement", "mdi:battery"),
    _m(S, 61, "*power*", "energie", "Energie", "", "", "", "mdi:power-plug"),
    _m(S, 70, "*network*", "netz", "Netzwerk", "", "", "", "mdi:lan"),
    _m(S, 71, "*wifi*", "netz", "WLAN", "", "", "", "mdi:wifi"),
    _m(S, 72, "*bluetooth*", "netz", "Bluetooth", "", "", "", "mdi:bluetooth"),
    _m(S, 80, "*windowsupdate*", "updates", "Windows-Updates", "", "", "", "mdi:microsoft-windows"),
    _m(S, 81, "*volume*", "audio", "Lautstärke", "%", "", "", "mdi:volume-high"),
    _m(S, 82, "*audio*", "audio", "Audio", "", "", "", "mdi:speaker"),
    _m(S, 83, "*webcam*", "kamera", "Webcam", "", "", "", "mdi:webcam"),
    _m(S, 84, "*microphone*", "mikrofon", "Mikrofon", "", "", "", "mdi:microphone"),
    _m(S, 85, "*display*", "bildschirm", "Bildschirm", "", "", "", "mdi:monitor"),
    _m(S, 86, "*monitor*", "bildschirm", "Bildschirm", "", "", "", "mdi:monitor"),
    _m(S, 90, "*process*", "prozess", "Prozess", "", "", "", "mdi:application-cog"),
    _m(S, 91, "*service*", "dienst", "Dienst", "", "", "", "mdi:cog"),
    _m(S, 999, "*", "", "", "", "", "", "", True),
    _m(B, 10, "*monitorsleep*", "bildschirm_aus", "Bildschirm aus", icon="mdi:monitor-off"),
    _m(B, 11, "*monitorwake*", "bildschirm_an", "Bildschirm an", icon="mdi:monitor"),
    _m(B, 20, "*shutdown*", "shutdown", "Herunterfahren", icon="mdi:power", gefahr=True),
    _m(B, 21, "*restart*", "restart", "Neu starten", icon="mdi:restart", gefahr=True),
    _m(B, 22, "*reboot*", "restart", "Neu starten", icon="mdi:restart", gefahr=True),
    _m(B, 23, "*hibernate*", "hibernate", "Ruhezustand", icon="mdi:power-sleep", gefahr=True),
    _m(B, 24, "*sleep*", "sleep", "Energie sparen", icon="mdi:sleep", gefahr=True),
    _m(B, 25, "*logoff*", "logoff", "Abmelden", icon="mdi:logout", gefahr=True),
    _m(B, 26, "*lock*", "lock", "Sperren", icon="mdi:lock"),
    _m(B, 30, "*mute*", "mute", "Stumm", icon="mdi:volume-off"),
    _m(B, 31, "*media*", "medien", "Medien", icon="mdi:play-pause"),
    _m(B, 999, "*", "", "", icon="mdi:console"),
]

_cache: list | None = None
_lock = threading.Lock()


def neu_laden() -> None:
    global _cache
    with _lock:
        _cache = None


def _liste() -> list[dict]:
    global _cache
    with _lock:
        if _cache is not None:
            return _cache
    from modelle import Muster
    with kern.sitzung() as s:
        zeilen = s.scalars(select(Muster).where(Muster.aktiv.is_(True)).order_by(Muster.reihenfolge, Muster.id)).all()
        out = []
        for m in zeilen:
            pat = m.muster.strip()
            try:
                rx = re.compile(pat[3:], re.I) if pat.lower().startswith("re:") else \
                    re.compile(fnmatch.translate(pat.lower()), re.I)
            except re.error:
                continue
            out.append({"id": m.id, "ziel": m.ziel, "rx": rx, "regex": pat.lower().startswith("re:"), "kategorie": m.kategorie, "bezeichnung": m.bezeichnung,
                        "einheit": m.einheit, "device_class": m.device_class, "state_class": m.state_class,
                        "icon": m.icon, "importieren": m.importieren, "gefahr": m.gefahr})
    with _lock:
        _cache = out
    return out


def _norm(t: str) -> str:
    return re.sub(r"[^a-z0-9*?]", "", (t or "").lower())


def erkennen(ziel: str, schluessel: str, name: str = "", geraetename: str = "") -> dict:
    """Liefert die Erkennung für einen Sensor/Befehl. Der Gerätename vorn wird ignoriert (HASS.Agent hängt ihn an)."""
    kandidaten = []
    for t in (schluessel, name):
        if not t:
            continue
        kandidaten.append(t.lower())
        n = _norm(t)
        g = _norm(geraetename)
        if g and n.startswith(g):
            n = n[len(g):]
        kandidaten.append(n)
    for m in _liste():
        if m["ziel"] != ziel:
            continue
        if any((m["rx"].search(k) if m["regex"] else m["rx"].fullmatch(k)) for k in kandidaten):
            return {k: v for k, v in m.items() if k not in ("rx", "regex")}
    return {"id": None, "kategorie": "", "bezeichnung": "", "einheit": "", "device_class": "", "state_class": "",
            "icon": "", "importieren": True, "gefahr": False}
