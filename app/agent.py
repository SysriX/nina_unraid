"""HASS.Agent über MQTT: erkennt Agenten an ihrer Home-Assistant-Discovery, liest Sensoren und führt Befehle aus.

HASS.Agent (2.x, .NET) meldet sich mit MQTT-Discovery beim Broker von Home Assistant an:
  <präfix>/<komponente>/<gerät>/<objekt>/config   (Sensoren, binäre Sensoren, Knöpfe, Schalter …)
NINA hört mit (nur lesend) und schickt Befehle auf das command_topic – genau wie Home Assistant.
Erkannt wird ein Agent am Gerät der Discovery (identifiers/manufacturer/model/sw_version passt zum Erkennungs-Muster).
"""
from __future__ import annotations

import json
import re
import ssl
import threading
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, or_, select

import kern
import muster
import netz
from kern import iso, jetzt, protokoll, sitzung
from modelle import Agent, AgentBefehl, AgentWert, Geraet, Schnittstelle
from zugang import ADMIN, LESER, client_ip

router = APIRouter(prefix="/api")

STANDARD_MQTT = {"aktiv": False, "host": "", "port": 1883, "tls": False, "tls_pruefen": True, "praefix": "homeassistant",
                 "erkennung": r"hass\.?agent|lab02", "client_id": ""}
SENSOR_ARTEN = ("sensor", "binary_sensor")
BEFEHL_ARTEN = ("button", "switch", "lock")
ABK = {"stat_t": "state_topic", "cmd_t": "command_topic", "dev": "device", "ids": "identifiers", "mf": "manufacturer",
       "mdl": "model", "sw": "sw_version", "avty_t": "availability_topic", "avty": "availability", "unit_of_meas": "unit_of_measurement",
       "dev_cla": "device_class", "stat_cla": "state_class", "val_tpl": "value_template", "json_attr_t": "json_attributes_topic",
       "uniq_id": "unique_id", "pl_prs": "payload_press", "pl_on": "payload_on", "pl_off": "payload_off", "ic": "icon",
       "pl_avail": "payload_available", "pl_not_avail": "payload_not_available", "pl_lock": "payload_lock",
       "pl_unlk": "payload_unlock", "t": "topic", "obj_id": "object_id"}


# Sensoren von HASS.Agent .NET10: Schlüssel -> (Einheit, device_class, state_class, Symbol)
NET10_SENSOREN = {
    "cpu_usage": ("%", "", "measurement", "mdi:cpu-64-bit"), "gpu_usage": ("%", "", "measurement", "mdi:expansion-card"),
    "memory_usage": ("%", "", "measurement", "mdi:memory"), "memory_available": ("MiB", "data_size", "measurement", "mdi:memory"),
    "system_drive_free_percent": ("%", "", "measurement", "mdi:harddisk"), "system_drive": ("GiB", "data_size", "measurement", "mdi:harddisk"),
    "drive_health": ("", "", "", "mdi:harddisk"), "drive_space": ("%", "", "measurement", "mdi:harddisk"),
    "uptime_seconds": ("s", "duration", "", "mdi:timer-outline"), "idle_time_seconds": ("s", "duration", "", "mdi:account-clock"),
    "battery_time_remaining": ("s", "duration", "", "mdi:battery-clock"), "boot_time": ("", "timestamp", "", "mdi:clock-start"),
    "volume": ("%", "", "measurement", "mdi:volume-high"), "battery_level": ("%", "battery", "measurement", "mdi:battery"),
    "wifi_signal": ("%", "", "measurement", "mdi:wifi-strength-3"), "logged_in_users": ("", "", "measurement", "mdi:account-multiple"),
    "rdp_sessions": ("", "", "measurement", "mdi:remote-desktop"), "audio_sessions": ("", "", "measurement", "mdi:tune-vertical"),
    "event_log_errors_recent": ("", "", "measurement", "mdi:alert-circle"), "logged_in_user": ("", "", "", "mdi:account"),
    "network_address": ("", "", "", "mdi:ip-network"),
}


NET10_ALT = ("memory_available_mb", "system_drive_free_gb")


def _wert_text(v) -> str:
    if v is True:
        return "on"
    if v is False:
        return "off"
    return "" if v is None else str(v)


def konfig() -> dict:
    return {**STANDARD_MQTT, **(kern.einstellung("mqtt", {}) or {})}


def _expand(d):
    if isinstance(d, dict):
        return {ABK.get(k, k): _expand(v) for k, v in d.items()}
    if isinstance(d, list):
        return [_expand(x) for x in d]
    return d


def _basis(cfg: dict) -> dict:
    """'~' (Basis-Topic) in allen *_topic-Feldern ersetzen."""
    b = cfg.get("~")
    if not b:
        return cfg
    for k, v in list(cfg.items()):
        if isinstance(v, str) and k.endswith("topic"):
            cfg[k] = v.replace("~", b) if v.startswith("~") or v.endswith("~") else v
    return cfg


_TPL = re.compile(r"^\{\{\s*value_json((?:\.[A-Za-z_][A-Za-z0-9_]*|\[\s*['\"][^'\"]+['\"]\s*\]|\[\s*\d+\s*\])+)\s*(\|[^}]*)?\}\}$")


def wert_aus_template(payload: str, tpl: str) -> str:
    tpl = (tpl or "").strip()
    if not tpl:
        return payload
    m = _TPL.match(tpl)
    if not m:
        return payload
    try:
        v = json.loads(payload)
        for teil in re.findall(r"\.([A-Za-z_][A-Za-z0-9_]*)|\[\s*['\"]([^'\"]+)['\"]\s*\]|\[\s*(\d+)\s*\]", m.group(1)):
            k = teil[0] or teil[1]
            v = v[int(teil[2])] if teil[2] else v[k]
        return v if isinstance(v, str) else json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else str(v)
    except Exception:  # noqa: BLE001
        return payload


class Dienst:
    def __init__(self):
        self.client = None
        self.verbunden = False
        self.status = "aus"
        self.lock = threading.RLock()
        self.ziele: dict[str, list] = {}           # topic -> [(art, agent_id, schluessel, template/payloads)]
        self.werte: dict[tuple, dict] = {}         # (agent_id, schluessel) -> {wert, attribute, zeit, neu}
        self.zustaende: dict[tuple, str] = {}      # (agent_id, befehl) -> Zustand (Schalter)
        self.online: dict[int, tuple[bool, float]] = {}
        self.verfuegbar: dict[int, bool] = {}      # Agent hat availability_topic
        self.empfangen = 0
        self._re = None
        self.net10: dict[str, dict] = {}         # serial -> {aid, app, dienst, schluessel}
        self.net10_warte: dict[str, dict] = {}
        self.ips: dict[int, set] = {}            # Agent -> gemeldete IP-Adressen   # serial -> {topic: payload} bis das Gerät bekannt ist

    # -------------------------------------------------------------- Start/Stopp
    def start(self):
        self.stop()
        k = konfig()
        g = kern.geheim("mqtt")
        if not k["aktiv"] or not k["host"]:
            self.status = "aus"
            return
        try:
            self._re = re.compile(k["erkennung"] or STANDARD_MQTT["erkennung"], re.I)
        except re.error:
            self._re = re.compile(STANDARD_MQTT["erkennung"], re.I)
        import paho.mqtt.client as mqtt
        cid = k.get("client_id") or f"nina-{kern.instanz_id()}"
        c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=cid, clean_session=True)
        if g.get("benutzer"):
            c.username_pw_set(g["benutzer"], g.get("passwort") or None)
        if k["tls"]:
            ctx = ssl.create_default_context()
            if not k["tls_pruefen"]:
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
            c.tls_set_context(ctx)
        c.on_connect = self._verbunden
        c.on_disconnect = self._getrennt
        c.on_message = self._nachricht
        c.reconnect_delay_set(2, 60)
        self.client = c
        self.status = f"verbinde mit {k['host']}:{k['port']} …"
        try:
            c.connect_async(k["host"], int(k["port"] or 1883), keepalive=60)
            c.loop_start()
        except Exception as e:  # noqa: BLE001
            self.status = f"Fehler: {e}"
        self._ziele_aus_db()

    def stop(self):
        c, self.client = self.client, None
        if c:
            try:
                c.loop_stop()
                c.disconnect()
            except Exception:  # noqa: BLE001
                pass
        self.verbunden = False
        self.status = "aus"

    def _verbunden(self, c, ud, flags, rc, props=None):
        if getattr(rc, "is_failure", False) or (isinstance(rc, int) and rc != 0):
            self.verbunden = False
            self.status = f"Anmeldung abgelehnt: {rc}"
            return
        self.verbunden = True
        self.status = "verbunden"
        p = konfig()["praefix"].strip("/") or "homeassistant"
        c.subscribe([(f"{p}/+/+/config", 0), (f"{p}/+/+/+/config", 0),
                     # HASS.Agent .NET10 (eigenes Protokoll)
                     ("hass.agent/devices/+", 0), ("hass.agent/devices/+/availability", 0),
                     ("hass.agent/system/+/state", 0), ("hass.agent/sensors/+/state", 0)])
        with self.lock:
            topics = list(self.ziele)
        for t in topics:
            c.subscribe(t, 0)
        kern.log("MQTT verbunden")

    def _getrennt(self, c, ud, flags, rc, props=None):
        self.verbunden = False
        if self.client is c:
            self.status = f"getrennt ({rc}) – verbinde neu …"

    # -------------------------------------------------------------- Nachrichten
    def _nachricht(self, c, ud, msg):
        self.empfangen += 1
        try:
            payload = msg.payload.decode("utf-8", errors="replace")
            if msg.topic.startswith("hass.agent/"):
                self._net10(msg.topic, payload)
                return
            if msg.topic.endswith("/config"):
                self._discovery(msg.topic, payload)
                return
            with self.lock:
                ziele = list(self.ziele.get(msg.topic, ()))
            for art, aid, key, extra in ziele:
                if art == "wert":
                    self._wert(aid, key, wert_aus_template(payload, extra))
                elif art == "attr":
                    try:
                        attrs = json.loads(payload)
                    except ValueError:
                        continue
                    self._wert(aid, key, None, attrs if isinstance(attrs, dict) else {"wert": attrs})
                elif art == "avail":
                    an_p, aus_p = extra
                    if payload == an_p:
                        self._online(aid, True)
                    elif payload == aus_p:
                        self._online(aid, False)
                elif art == "zustand":
                    with self.lock:
                        self.zustaende[(aid, key)] = payload
        except Exception as e:  # noqa: BLE001
            kern.log("MQTT-Nachricht:", msg.topic, e)

    def _wert(self, aid: int, key: str, wert, attrs: dict | None = None):
        with self.lock:
            w = self.werte.setdefault((aid, key), {"wert": None, "attribute": None, "zeit": 0, "neu": False})
            if wert is not None:
                w["wert"] = str(wert)
            if attrs is not None:
                w["attribute"] = attrs
            w["zeit"], w["neu"] = time.time(), True
            if not self.verfuegbar.get(aid):
                self.online[aid] = (True, time.time())
        if attrs is not None:
            self._macs_merken(aid, attrs)

    def _online(self, aid: int, an: bool):
        with self.lock:
            alt = self.online.get(aid, (None, 0))[0]
            self.online[aid] = (an, time.time())
        if alt != an:
            self._online_speichern(aid, an)

    def _online_speichern(self, aid: int, an: bool):
        import inventar
        try:
            with sitzung() as s:
                a = s.get(Agent, aid)
                if not a:
                    return
                a.online = an
                if an:
                    a.zuletzt = jetzt()
                if a.geraet_id:
                    inventar.ereignis(s, a.geraet_id, "agent", "HASS.Agent online" if an else "HASS.Agent offline")
                    inventar.online_aktualisieren(s, [a.geraet_id])
        except Exception as e:  # noqa: BLE001
            kern.log("Agent-Status:", e)

    def _ist_agent(self, dev: dict) -> bool:
        if not dev or not self._re:
            return False
        ids = dev.get("identifiers") or []
        teile = [*(ids if isinstance(ids, list) else [ids]), dev.get("manufacturer", ""), dev.get("model", ""),
                 dev.get("sw_version", ""), dev.get("name", "")]
        return any(self._re.search(str(t)) for t in teile if t)

    def _discovery(self, topic: str, payload: str):
        teile = topic.split("/")
        komp, key = teile[1], teile[-2]
        if komp not in SENSOR_ARTEN + BEFEHL_ARTEN:
            return
        if not payload.strip():
            self._entfernen(topic, komp, key)
            return
        try:
            cfg = _basis(_expand(json.loads(payload)))
        except ValueError:
            return
        dev = cfg.get("device") or {}
        if not self._ist_agent(dev):
            return
        ids = dev.get("identifiers") or [dev.get("name", "")]
        kennung = str(ids[0] if isinstance(ids, list) else ids)[:191]
        if not kennung:
            return
        avty = cfg.get("availability_topic") or ""
        an_p, aus_p = cfg.get("payload_available", "online"), cfg.get("payload_not_available", "offline")
        if not avty and isinstance(cfg.get("availability"), list) and cfg["availability"]:
            a0 = cfg["availability"][0]
            avty = a0.get("topic", "")
            an_p, aus_p = a0.get("payload_available", an_p), a0.get("payload_not_available", aus_p)
        with sitzung() as s:
            a = s.scalars(select(Agent).where(Agent.kennung == kennung)).first()
            neu = a is None
            if neu:
                a = Agent(kennung=kennung, name=str(dev.get("name") or kennung)[:128])
                s.add(a)
            a.name = str(dev.get("name") or a.name)[:128]
            a.hersteller = str(dev.get("manufacturer") or "")[:128]
            a.modell = str(dev.get("model") or "")[:255]
            a.version = str(dev.get("sw_version") or "")[:64]
            if avty:
                a.verfuegbar_topic = avty
            s.flush()
            aid = a.id
            name = str(cfg.get("name") or key)
            if komp in SENSOR_ARTEN:
                w = s.scalars(select(AgentWert).where(AgentWert.agent_id == aid, AgentWert.schluessel == key[:160])).first()
                if not w:
                    w = AgentWert(agent_id=aid, schluessel=key[:160])
                    s.add(w)
                w.name, w.art = name[:255], komp
                w.einheit = str(cfg.get("unit_of_measurement") or "")[:32]
                w.device_class = str(cfg.get("device_class") or "")[:48]
                w.state_class = str(cfg.get("state_class") or "")[:32]
                w.icon = str(cfg.get("icon") or "")[:64]
                w.state_topic = str(cfg.get("state_topic") or "")[:255]
                w.value_template = str(cfg.get("value_template") or "")[:255]
                attr_t = str(cfg.get("json_attributes_topic") or "")
                ziele = [(w.state_topic, ("wert", aid, w.schluessel, w.value_template))] + \
                        ([(attr_t, ("attr", aid, w.schluessel, None))] if attr_t else [])
            else:
                b = s.scalars(select(AgentBefehl).where(AgentBefehl.agent_id == aid, AgentBefehl.schluessel == key[:160])).first()
                if not b:
                    b = AgentBefehl(agent_id=aid, schluessel=key[:160])
                    s.add(b)
                b.name, b.art = name[:255], komp
                b.command_topic = str(cfg.get("command_topic") or "")[:255]
                b.payload_an = str(cfg.get("payload_press") or cfg.get("payload_on") or cfg.get("payload_lock") or "")[:64]
                b.payload_aus = str(cfg.get("payload_off") or cfg.get("payload_unlock") or "")[:64]
                b.state_topic = str(cfg.get("state_topic") or "")[:255]
                b.icon = str(cfg.get("icon") or "")[:64]
                ziele = [(b.state_topic, ("zustand", aid, b.schluessel, None))] if b.state_topic else []
            if neu:
                kern.log(f"HASS.Agent erkannt: {a.name}")
            self._verknuepfen(s, a)
        if avty:
            self.verfuegbar[aid] = True
            ziele.append((avty, ("avail", aid, "", (an_p, aus_p))))
        for t, z in ziele:
            self._ziel(t, z)

    def _ziel(self, topic: str, ziel: tuple):
        if not topic:
            return
        with self.lock:
            liste = self.ziele.setdefault(topic, [])
            if ziel in liste:
                return
            liste[:] = [x for x in liste if not (x[0] == ziel[0] and x[1] == ziel[1] and x[2] == ziel[2])] + [ziel]
            erst = len(liste) == 1
        if erst and self.client and self.verbunden:
            self.client.subscribe(topic, 0)

    def _entfernen(self, topic, komp, key):
        try:
            with sitzung() as s:
                modell = AgentWert if komp in SENSOR_ARTEN else AgentBefehl
                knoten = topic.split("/")[2]
                for x in s.scalars(select(modell).where(modell.schluessel == key[:160])):
                    a = s.get(Agent, x.agent_id)
                    if a and (knoten == key or knoten.lower() in (a.name.lower(), a.kennung.lower())):
                        s.delete(x)
        except Exception as e:  # noqa: BLE001
            kern.log("Discovery entfernen:", e)

    def _ziele_aus_db(self):
        """Bekannte Topics schon vor der (retained) Discovery abonnieren."""
        if not kern.db_bereit():
            return
        with sitzung() as s:
            for a in s.scalars(select(Agent)):
                if a.verfuegbar_topic:
                    self.verfuegbar[a.id] = True
                    self._ziel(a.verfuegbar_topic, ("avail", a.id, "", ("online", "offline")))
            for w in s.scalars(select(AgentWert)):
                self._ziel(w.state_topic, ("wert", w.agent_id, w.schluessel, w.value_template))
            for b in s.scalars(select(AgentBefehl).where(AgentBefehl.state_topic != "")):
                self._ziel(b.state_topic, ("zustand", b.agent_id, b.schluessel, None))

    # -------------------------------------------------------------- HASS.Agent .NET10
    def _net10(self, topic: str, payload: str):
        """Protokoll von HASS.Agent .NET10 (v1k70rk4):
        hass.agent/devices/<serial>               Gerät + apis (Befehle, Sensorliste), retained
        hass.agent/devices/<serial>/availability  online/offline der Tray-App
        hass.agent/system/<serial>/state          Windows-Dienst: online, Befehle, Sensoren
        hass.agent/sensors/<serial>/state         Messwerte als JSON {schlüssel: wert, attributes: {...}}
        Befehle: JSON {"command": …} an hass.agent/system/<serial>/cmd (Dienst) oder hass.agent/buttons/<serial>/cmd (App)."""
        teile = topic.split("/")
        if len(teile) < 3:
            return
        art, serial = teile[1], teile[2]
        if art == "devices" and len(teile) == 3:
            try:
                d = json.loads(payload) if payload.strip() else None
            except ValueError:
                return
            if isinstance(d, dict):
                self._net10_geraet(serial, d)
            return
        st = self.net10.get(serial)
        if not st or "aid" not in st:
            # Gerät noch unbekannt (seine Meldung kommt retained gleich) – letzte Nachricht je Topic aufheben
            self.net10_warte.setdefault(serial, {})[topic] = payload
            return
        aid = st["aid"]
        if art == "devices" and len(teile) == 4 and teile[3] == "availability":
            st["app"] = payload.strip().lower() == "online"
        elif art == "system" and teile[-1] == "state":
            try:
                d = json.loads(payload)
            except ValueError:
                return
            if isinstance(d, dict):
                st["dienst"] = d
                self._net10_befehle(aid, serial, d.get("commands"), d.get("custom_commands"), "system")
                self._net10_sensorliste(aid, st, d.get("standard_sensors"), d.get("custom_sensors"))
        elif art == "sensors" and teile[-1] == "state":
            try:
                d = json.loads(payload)
            except ValueError:
                return
            if not isinstance(d, dict):
                return
            attrs = d.get("attributes") if isinstance(d.get("attributes"), dict) else {}
            neu = []
            for k, v in d.items():
                if k in ("attributes", "custom_sensors", "updated_at") or isinstance(v, (dict, list)):
                    continue
                if k in NET10_ALT:     # alte Namen (Client < 10.9.3), kommen zusätzlich
                    continue
                if k not in st["schluessel"]:
                    neu.append((k, k, None))
                self._wert(aid, k, _wert_text(v), attrs.get(k) if isinstance(attrs.get(k), dict) else None)
            for cs in d.get("custom_sensors") or []:
                if isinstance(cs, dict) and cs.get("id"):
                    k = "custom_" + str(cs["id"])
                    if k not in st["schluessel"]:
                        neu.append((k, cs.get("name") or k, cs))
                    self._wert(aid, k, _wert_text(cs.get("value")),
                               cs.get("attributes") if isinstance(cs.get("attributes"), dict) else None)
            if neu:
                self._net10_werte_anlegen(aid, st, neu)
            if isinstance(attrs.get("network_address"), dict):
                self._ips_merken(aid, attrs["network_address"])
        an = bool(st.get("app")) or bool((st.get("dienst") or {}).get("online"))
        self._online(aid, an)

    def _net10_geraet(self, serial: str, d: dict):
        dev = d.get("device") if isinstance(d.get("device"), dict) else {}
        apis = d.get("apis") if isinstance(d.get("apis"), dict) else {}
        with sitzung() as s:
            kennung = f"net10:{serial}"[:191]
            a = s.scalars(select(Agent).where(Agent.kennung == kennung)).first()
            if not a:
                a = Agent(kennung=kennung, name=str(dev.get("name") or serial)[:128])
                s.add(a)
                kern.log(f"HASS.Agent .NET10 erkannt: {a.name}")
            a.name = str(dev.get("name") or a.name)[:128]
            a.hersteller = str(dev.get("manufacturer") or "")[:128]
            a.modell = str(dev.get("model") or "HASS.Agent .NET10")[:255]
            a.version = str(dev.get("sw_version") or "")[:64]
            a.verfuegbar_topic = f"hass.agent/devices/{serial}/availability"
            s.flush()
            aid = a.id
            bekannt = {w.schluessel for w in s.scalars(select(AgentWert).where(AgentWert.agent_id == aid))}
            self._verknuepfen(s, a)
        st = self.net10.setdefault(serial, {"app": None, "dienst": {}, "schluessel": set()})
        st["aid"], st["apis"] = aid, apis
        st["schluessel"] |= bekannt
        self.verfuegbar[aid] = True
        if apis.get("buttons"):
            self._net10_befehle(aid, serial, apis.get("commands"), apis.get("custom_commands"), "buttons")
        if apis.get("system_sensors"):
            self._net10_sensorliste(aid, st, apis.get("standard_sensors"), apis.get("custom_sensors"))
        for t, p in self.net10_warte.pop(serial, {}).items():
            self._net10(t, p)

    def _net10_sensorliste(self, aid: int, st: dict, standard, custom):
        neu = []
        for x in standard or []:
            if isinstance(x, dict) and isinstance(x.get("key"), str) and x["key"] not in st["schluessel"] \
                    and x["key"] not in NET10_ALT:
                neu.append((x["key"], x.get("name") or x["key"], None))
        for x in custom or []:
            if isinstance(x, dict) and x.get("id") and "custom_" + str(x["id"]) not in st["schluessel"]:
                neu.append(("custom_" + str(x["id"]), x.get("name") or str(x["id"]), x))
        if neu:
            self._net10_werte_anlegen(aid, st, neu)

    def _net10_werte_anlegen(self, aid: int, st: dict, neu: list):
        with sitzung() as s:
            for key, name, meta in neu:
                key = key[:160]
                vorhanden = s.scalars(select(AgentWert).where(AgentWert.agent_id == aid, AgentWert.schluessel == key)).first()
                if vorhanden:
                    if name != key and vorhanden.name == key:
                        vorhanden.name = str(name)[:255]
                    st["schluessel"].add(key)
                    continue
                m = NET10_SENSOREN.get(key, ("", "", "", ""))
                meta = meta or {}
                s.add(AgentWert(agent_id=aid, schluessel=key, name=str(name)[:255], art="sensor",
                                einheit=str(meta.get("unit") or m[0])[:32], device_class=str(meta.get("device_class") or m[1])[:48],
                                state_class=str(meta.get("state_class") or m[2])[:32], icon=str(meta.get("icon") or m[3])[:64]))
                st["schluessel"].add(key)

    def _net10_befehle(self, aid: int, serial: str, befehle, eigene, seite: str):
        """Befehle anlegen; art 'net10', payload_an merkt sich, wer ihn ausführen kann (buttons/system)."""
        liste = [(str(b["name"]), str(b.get("display_name") or b["name"])) for b in befehle or []
                 if isinstance(b, dict) and isinstance(b.get("name"), str)]
        liste += [("custom:" + str(b["id"]), str(b.get("name") or b["id"])) for b in eigene or []
                  if isinstance(b, dict) and b.get("id")]
        if not liste:
            return
        with sitzung() as s:
            for key, name in liste:
                b = s.scalars(select(AgentBefehl).where(AgentBefehl.agent_id == aid, AgentBefehl.schluessel == key[:160])).first()
                if not b:
                    b = AgentBefehl(agent_id=aid, schluessel=key[:160], art="net10", payload_an="")
                    s.add(b)
                b.name = name[:255]
                seiten = set(filter(None, (b.payload_an or "").split(",")))
                seiten.add(seite)
                b.payload_an = ",".join(sorted(seiten))
                b.command_topic = "hass.agent/{seite}/" + serial + "/cmd"

    def _ips_merken(self, aid: int, attrs: dict):
        """network_address-Attribute: Adapter mit IP → passende (neu gefundene) Schnittstelle übernehmen."""
        ips = [x.get("address") for x in attrs.get("addresses") or [] if isinstance(x, dict) and x.get("address")]
        if not ips:
            return
        self.ips[aid] = set(ips)
        try:
            with sitzung() as s:
                a = s.get(Agent, aid)
                if not a or not a.geraet_id:
                    return
                for sch in s.scalars(select(Schnittstelle).where(Schnittstelle.ip.in_(ips))):
                    if sch.geraet_id == a.geraet_id:
                        continue
                    alt = s.get(Geraet, sch.geraet_id)
                    ziel = s.get(Geraet, a.geraet_id)
                    if alt and alt.status == "neu" and ziel and ziel.status == "aktiv":
                        sch.geraet_id, sch.primaer = a.geraet_id, False
                        s.flush()
                        if not s.scalar(select(func.count(Schnittstelle.id)).where(Schnittstelle.geraet_id == alt.id)):
                            s.delete(alt)
                        g = s.get(Geraet, a.geraet_id)
                        if g and sch.mac and not g.wol_aktiv:
                            g.wol_aktiv = True
        except Exception as e:  # noqa: BLE001
            kern.log("Agent-IP:", e)

    def net10_seite(self, aid: int, schluessel: str, seiten: str) -> str:
        """Dienst bevorzugen, wenn er online ist und den Befehl kennt (wie die HA-Integration)."""
        for st in self.net10.values():
            if st.get("aid") == aid:
                d = st.get("dienst") or {}
                namen = {b.get("name") for b in d.get("commands") or [] if isinstance(b, dict)}
                namen |= {"custom:" + str(b.get("id")) for b in d.get("custom_commands") or [] if isinstance(b, dict)}
                if d.get("online") and schluessel in namen:
                    return "system"
                if st.get("app") is not False and "buttons" in seiten:
                    return "buttons"
                return "system" if "system" in seiten else "buttons"
        return "buttons" if "buttons" in seiten else "system"

    # -------------------------------------------------------------- Gerät verknüpfen
    def _verknuepfen(self, s, a: Agent):
        import inventar
        if a.geraet_id and s.get(Geraet, a.geraet_id):
            return
        import katalog
        n = a.name.lower()
        # nur Geräte, die schon im Inventar sind; neue Funde führt der Benutzer beim Übernehmen zusammen
        g = s.scalars(select(Geraet).where(func.lower(Geraet.name) == n, Geraet.status == "aktiv")).first()
        if not g:
            sch = s.scalars(select(Schnittstelle).join(Geraet, Geraet.id == Schnittstelle.geraet_id).where(
                Geraet.status == "aktiv", or_(func.lower(Schnittstelle.hostname) == n,
                                              func.lower(Schnittstelle.hostname).like(n + ".%")))).first()
            g = s.get(Geraet, sch.geraet_id) if sch else None
        if not g and inventar.allgemein().get("agent_geraete_anlegen", True):
            g = Geraet(name=a.name, typ=katalog.gueltiger_typ(s, "pc"), quelle="agent", status="neu", betriebssystem=a.modell[:128])
            s.add(g)
            s.flush()
            katalog.geraet_typen_setzen(s, g, [])
            inventar.ereignis(s, g.id, "neu", "von HASS.Agent gefunden")
        if g:
            a.geraet_id = g.id
            g.ueberwachen = True          # PC: schnell merken, wenn er aus- oder angeht
            if not g.betriebssystem and a.modell:
                g.betriebssystem = a.modell[:128]

    def _macs_merken(self, aid: int, attrs: dict):
        """Netzwerk-Sensoren von HASS.Agent liefern MAC + IP je Adapter → als Schnittstellen übernehmen."""
        paare = []

        def gehen(x):
            if isinstance(x, dict):
                mac = next((netz.mac_norm(v) for k, v in x.items() if isinstance(v, str) and "mac" in k.lower() and netz.ist_mac(v)), "")
                ip = ""
                for k, v in x.items():
                    if "ip" in k.lower() and "6" not in k:
                        kand = v if isinstance(v, list) else [v]
                        ip = next((str(i) for i in kand if isinstance(i, str) and re.fullmatch(r"\d+\.\d+\.\d+\.\d+", i)
                                   and not i.startswith(("169.254.", "127."))), "")
                        if ip:
                            break
                if mac:
                    paare.append((mac, ip, str(x.get("Name") or x.get("name") or x.get("Description") or "")[:64]))
                    if ip:
                        self.ips.setdefault(aid, set()).add(ip)
                for v in x.values():
                    gehen(v)
            elif isinstance(x, list):
                for v in x:
                    gehen(v)
        gehen(attrs)
        if not paare:
            return
        import inventar
        try:
            with sitzung() as s:
                a = s.get(Agent, aid)
                if not a or not a.geraet_id:
                    return
                gid = a.geraet_id
                netze = list(s.scalars(select(inventar.Netzwerk)))
                for mac, ip, name in paare:
                    sch = s.scalars(select(Schnittstelle).where(Schnittstelle.mac == mac)).first()
                    if sch and sch.geraet_id != gid:
                        alt = s.get(Geraet, sch.geraet_id)
                        ziel = s.get(Geraet, gid)
                        # vom Scan doppelt gefunden → nur übernehmen, wenn das Agent-Gerät schon im Inventar ist
                        if alt and alt.status == "neu" and ziel and ziel.status == "aktiv":
                            sch.geraet_id, sch.primaer = gid, False
                            s.flush()
                            if not s.scalar(select(func.count(Schnittstelle.id)).where(Schnittstelle.geraet_id == alt.id)):
                                s.delete(alt)
                            g = s.get(Geraet, gid)
                            if g and not g.wol_aktiv:
                                g.wol_aktiv = True
                        continue
                    if not sch:
                        if not ip:
                            continue
                        nw = inventar.netzwerk_fuer_ip(netze, ip)
                        sch = Schnittstelle(geraet_id=gid, mac=mac, ip=ip, name=name, quelle="agent",
                                            mac_hersteller=netz.mac_hersteller(mac), netzwerk_id=nw.id if nw else None,
                                            online=True, zuletzt=jetzt())
                        s.add(sch)
                        g = s.get(Geraet, gid)
                        if g and not g.wol_aktiv:
                            g.wol_aktiv = True
                    elif ip and sch.ip != ip and not sch.feste_ip:
                        sch.ip = ip
                    if not sch.name and name:
                        sch.name = name
                s.flush()
                if not s.scalar(select(func.count(Schnittstelle.id)).where(Schnittstelle.geraet_id == gid, Schnittstelle.primaer.is_(True))):
                    erste = s.scalars(select(Schnittstelle).where(Schnittstelle.geraet_id == gid)).first()
                    if erste:
                        erste.primaer = True
        except Exception as e:  # noqa: BLE001
            kern.log("Agent-MAC:", e)

    # -------------------------------------------------------------- Speichern / Abfragen
    def speichern(self):
        """Neue Werte gesammelt in die Datenbank (alle 30 s) und Agenten ohne Lebenszeichen offline setzen."""
        if not kern.db_bereit():
            return
        with self.lock:
            neu = {k: dict(v) for k, v in self.werte.items() if v["neu"]}
            for k in neu:
                self.werte[k]["neu"] = False
            jetzt_t = time.time()
            abgelaufen = [aid for aid, (an, t) in self.online.items()
                          if an and not self.verfuegbar.get(aid) and jetzt_t - t > 600]
        if neu:
            with sitzung() as s:
                for (aid, key), v in neu.items():
                    w = s.scalars(select(AgentWert).where(AgentWert.agent_id == aid, AgentWert.schluessel == key)).first()
                    if not w:
                        continue
                    if v["wert"] is not None:
                        w.wert = v["wert"][:4000]
                    if v["attribute"] is not None:
                        w.attribute = v["attribute"]
                    w.geaendert = jetzt()
                aids = {aid for aid, _ in neu}
                for aid in aids:
                    a = s.get(Agent, aid)
                    if a:
                        a.zuletzt = jetzt()
                        if not self.verfuegbar.get(aid) and not a.online:
                            a.online = True
        for aid in abgelaufen:
            self._online(aid, False)

    def wert(self, aid: int, key: str):
        with self.lock:
            return self.werte.get((aid, key))


DIENST = Dienst()


def agent_ips(aid: int) -> set:
    """IP-Adressen, die der Agent gemeldet hat (Netzwerk-Sensoren)."""
    out = set(DIENST.ips.get(aid, set()))
    try:
        with sitzung() as s:
            for w in s.scalars(select(AgentWert).where(AgentWert.agent_id == aid)):
                for x in (w.attribute or {}).get("addresses") or []:
                    if isinstance(x, dict) and x.get("address"):
                        out.add(x["address"])
                if w.schluessel == "network_address" and netz.ip_gueltig(w.wert or ""):
                    out.add(w.wert)
    except Exception:  # noqa: BLE001
        pass
    return out


def angemeldet(aid: int) -> str:
    """Wert des Sensors, der als „benutzer“ erkannt wird (z. B. LoggedUser)."""
    try:
        with sitzung() as s:
            a = s.get(Agent, aid)
            for w in s.scalars(select(AgentWert).where(AgentWert.agent_id == aid)):
                if muster.erkennen("sensor", w.schluessel, w.name, a.name if a else "")["kategorie"] == "benutzer":
                    live = DIENST.wert(aid, w.schluessel)
                    v = (live or {}).get("wert") or w.wert
                    if v and v.lower() not in ("unknown", "none", "unavailable", ""):
                        return v
    except Exception:  # noqa: BLE001
        pass
    return ""


def _schoen(name: str, agent_name: str) -> str:
    n = name or ""
    if agent_name and n.lower().startswith(agent_name.lower()):
        n = n[len(agent_name):].lstrip(" _-")
    return n.replace("_", " ").strip() or name


def agent_json(s, a: Agent, voll: bool = False) -> dict:
    d = {"id": a.id, "kennung": a.kennung, "name": a.name, "hersteller": a.hersteller, "modell": a.modell, "version": a.version,
         "online": a.online, "zuletzt": iso(a.zuletzt), "geraet_id": a.geraet_id, "erstellt": iso(a.erstellt)}
    g = s.get(Geraet, a.geraet_id) if a.geraet_id else None
    d["geraet"] = g.name if g else ""
    d["geraet_status"] = g.status if g else ""
    if not voll:
        d["werte"] = s.scalar(select(func.count(AgentWert.id)).where(AgentWert.agent_id == a.id)) or 0
        d["befehle"] = s.scalar(select(func.count(AgentBefehl.id)).where(AgentBefehl.agent_id == a.id)) or 0
        return d
    werte = []
    for w in s.scalars(select(AgentWert).where(AgentWert.agent_id == a.id).order_by(AgentWert.name)):
        e = muster.erkennen("sensor", w.schluessel, w.name, a.name)
        live = DIENST.wert(a.id, w.schluessel) or {}
        werte.append({"schluessel": w.schluessel, "name": w.name, "anzeige": e["bezeichnung"] or _schoen(w.name, a.name),
                      "art": w.art, "wert": live.get("wert") if live.get("wert") is not None else w.wert,
                      "attribute": live.get("attribute") if live.get("attribute") is not None else (w.attribute or {}),
                      "einheit": w.einheit or e["einheit"], "device_class": w.device_class or e["device_class"],
                      "state_class": w.state_class or e["state_class"], "icon": w.icon or e["icon"],
                      "kategorie": e["kategorie"], "importieren": e["importieren"], "muster_id": e["id"],
                      "geaendert": iso(w.geaendert)})
    befehle = []
    for b in s.scalars(select(AgentBefehl).where(AgentBefehl.agent_id == a.id).order_by(AgentBefehl.name)):
        e = muster.erkennen("befehl", b.schluessel, b.name, a.name)
        befehle.append({"schluessel": b.schluessel, "name": b.name, "anzeige": e["bezeichnung"] or _schoen(b.name, a.name),
                        "art": b.art, "icon": b.icon or e["icon"], "kategorie": e["kategorie"], "gefahr": e["gefahr"],
                        "importieren": e["importieren"], "zustand": DIENST.zustaende.get((a.id, b.schluessel), ""),
                        "muster_id": e["id"]})
    d.update(werte=werte, befehle=befehle)
    return d


def befehl(gid: int, befehl_name: str, wer: str, ip: str = "", wert=None) -> dict:
    import inventar
    b_low = befehl_name.strip().lower()
    if b_low in ("wake", "wecken", "wol", "einschalten", "turn_on"):
        return inventar.wecken(gid, wer, ip)
    with sitzung() as s:
        g = s.get(Geraet, gid)
        if not g:
            raise LookupError("Gerät gibt es nicht")
        a = s.scalars(select(Agent).where(Agent.geraet_id == gid)).first()
        if not a:
            raise HTTPException(400, f"„{g.name}“ hat keinen HASS.Agent")
        bs = list(s.scalars(select(AgentBefehl).where(AgentBefehl.agent_id == a.id)))
        treffer = next((b for b in bs if b.schluessel.lower() == b_low), None) \
            or next((b for b in bs if muster.erkennen("befehl", b.schluessel, b.name, a.name)["kategorie"] == b_low), None) \
            or next((b for b in bs if _schoen(b.name, a.name).lower() == b_low or b.name.lower() == b_low), None)
        if not treffer:
            raise HTTPException(400, f"Befehl „{befehl_name}“ gibt es bei „{g.name}“ nicht. Vorhanden: "
                                + ", ".join(b.schluessel for b in bs))
        if not treffer.command_topic:
            raise HTTPException(400, "Der Befehl hat kein command_topic")
        treffer_topic = treffer.command_topic
        if treffer.art == "net10":
            seite = DIENST.net10_seite(a.id, treffer.schluessel, treffer.payload_an)
            if treffer.schluessel.startswith("custom:"):
                daten = {"command": treffer.schluessel[7:]}
            elif treffer.schluessel in ("shutdown", "restart"):
                verz = int(wert) if str(wert or "").strip().isdigit() else 60
                daten = {"command": treffer.schluessel, "force": False, "time": verz, "comment": f"NINA ({wer})"}
            elif treffer.schluessel == "restart_cancel":
                daten = {"restart_cancel": True}
            else:
                daten = {"command": treffer.schluessel}
            payload = json.dumps(daten)
            treffer_topic = treffer.command_topic.replace("{seite}", seite)
        elif treffer.art == "button":
            payload = treffer.payload_an or "PRESS"
        elif treffer.art == "switch":
            if wert is None:
                z = DIENST.zustaende.get((a.id, treffer.schluessel), "")
                payload = (treffer.payload_aus or "OFF") if z.upper() in ((treffer.payload_an or "ON").upper(), "ON") \
                    else (treffer.payload_an or "ON")
            else:
                payload = (treffer.payload_an or "ON") if str(wert).lower() in ("1", "true", "on", "an", "ein") else (treffer.payload_aus or "OFF")
        else:
            payload = treffer.payload_an or "LOCK"
        topic, name, gname, aname = treffer_topic, treffer.name, g.name, a.name
        if not a.online:
            kern.log(f"Befehl an {aname}, obwohl der Agent offline ist")
    if not DIENST.client or not DIENST.verbunden:
        raise HTTPException(503, "MQTT ist nicht verbunden")
    info = DIENST.client.publish(topic, payload, qos=1)
    ok = info.rc == 0
    with sitzung() as s:
        inventar.ereignis(s, gid, "befehl", f"{_schoen(name, aname)} ({wer})")
    protokoll(wer, "befehl", _schoen(name, aname), gname, ok=ok, details=f"{topic} = {payload}", ip=ip)
    if not ok:
        raise HTTPException(502, f"Senden fehlgeschlagen ({info.rc})")
    return {"ok": True, "befehl": name, "topic": topic}


# ------------------------------------------------------------------ Routen
@router.get("/agenten")
def agenten(ich: dict = Depends(LESER)):
    k = konfig()
    with sitzung() as s:
        return {"mqtt": {"aktiv": k["aktiv"], "host": k["host"], "verbunden": DIENST.verbunden, "status": DIENST.status,
                         "nachrichten": DIENST.empfangen},
                "agenten": [agent_json(s, a) for a in s.scalars(select(Agent).order_by(Agent.name))]}


@router.get("/agenten/{aid}")
def agent_detail(aid: int, ich: dict = Depends(LESER)):
    with sitzung() as s:
        a = s.get(Agent, aid)
        if not a:
            raise LookupError("Agent gibt es nicht")
        return agent_json(s, a, voll=True)


@router.post("/agenten/{aid}/verknuepfen")
async def agent_verknuepfen(aid: int, req: Request, ich: dict = Depends(ADMIN)):
    import inventar
    d = await req.json()
    with sitzung() as s:
        a = s.get(Agent, aid)
        if not a:
            raise LookupError("Agent gibt es nicht")
        alt = a.geraet_id
        if d.get("neu"):
            import katalog
            g = Geraet(name=a.name, typ=katalog.gueltiger_typ(s, "pc"), quelle="agent", status="neu", betriebssystem=a.modell[:128])
            s.add(g)
            s.flush()
            katalog.geraet_typen_setzen(s, g, [])
            a.geraet_id = g.id
        else:
            gid = int(d.get("geraet_id") or 0) or None
            if gid and not s.get(Geraet, gid):
                raise LookupError("Gerät gibt es nicht")
            a.geraet_id = gid
        s.flush()
        inventar.online_aktualisieren(s, [alt, a.geraet_id])
        name = a.name
    protokoll(ich["name"], "agent", "verknüpft", name, ip=client_ip(req))
    return {"ok": True}


@router.delete("/agenten/{aid}")
def agent_loeschen(aid: int, req: Request, ich: dict = Depends(ADMIN)):
    with sitzung() as s:
        a = s.get(Agent, aid)
        if not a:
            raise LookupError("Agent gibt es nicht")
        name = a.name
        s.delete(a)
    with DIENST.lock:
        for k in [k for k in DIENST.werte if k[0] == aid]:
            DIENST.werte.pop(k, None)
    protokoll(ich["name"], "agent", "entfernt", name, ip=client_ip(req))
    return {"ok": True}
