"""Hintergrund-Dienste: Zeitplan für Scans, Ping-Überwachung, OPNsense-Abgleich, Agent-Werte speichern,
Aufräumen – und die Bekanntgabe per mDNS/Zeroconf (_nina._tcp), damit Home Assistant den Dienst findet."""
from __future__ import annotations

import asyncio
import os
import socket


import kern
import netz

MDNS_TYP = "_nina._tcp.local."


def port() -> int:
    return int(os.environ.get("NINA_PORT", "8080"))


class Mdns:
    def __init__(self):
        self.zc = None
        self.info = None
        self.status = "aus"

    def start(self):
        if os.environ.get("NINA_MDNS", "1").lower() in ("0", "nein", "false", "aus"):
            self.status = "abgeschaltet (NINA_MDNS=0)"
            return
        try:
            from zeroconf import IPVersion, ServiceInfo, Zeroconf
            ip = netz.eigene_ip()
            name = (kern.einstellung("allgemein", {}) or {}).get("name") or "NINA" if kern.db_bereit() else "NINA"
            inst = kern.instanz_id()
            self.info = ServiceInfo(MDNS_TYP, f"{name} {inst[:4]}.{MDNS_TYP}", addresses=[socket.inet_aton(ip)], port=port(),
                                    properties={"id": inst, "version": kern.VERSION, "pfad": "/api/ha/v1", "name": name},
                                    server=f"nina-{inst}.local.")
            self.zc = Zeroconf(ip_version=IPVersion.V4Only, interfaces=[ip] if ip != "127.0.0.1" else None)
            self.zc.register_service(self.info, allow_name_change=True)
            self.status = f"angekündigt als {self.info.name} auf {ip}:{port()}"
            kern.log("mDNS:", self.status)
        except Exception as e:  # noqa: BLE001
            self.status = f"Fehler: {e}"
            kern.log("mDNS nicht möglich:", e)

    def stop(self):
        if self.zc:
            try:
                if self.info:
                    self.zc.unregister_service(self.info)
                self.zc.close()
            except Exception:  # noqa: BLE001
                pass
        self.zc = None


MDNS = Mdns()


async def _schleife(name: str, fn, intervall_fn, verzoegerung: float = 5):
    await asyncio.sleep(verzoegerung)
    while True:
        try:
            if kern.db_bereit():
                await asyncio.to_thread(fn)
        except Exception as e:  # noqa: BLE001
            kern.log(f"{name}:", e)
        await asyncio.sleep(max(5, intervall_fn()))


def _zeitplan():
    import zeitplan
    zeitplan.schleife_einmal()


def _ueberwachen():
    import inventar
    inventar.ueberwachen()


def _intervall_ueberwachen():
    if not kern.db_bereit():
        return 60
    import inventar
    return int(inventar.allgemein().get("ueberwachen_intervall") or 60)


def _agent_speichern():
    import agent
    agent.DIENST.speichern()


def _aufraeumen():
    import inventar
    inventar.aufraeumen()


def starten() -> list[asyncio.Task]:
    return [asyncio.create_task(_schleife("Zeitplan", _zeitplan, lambda: 30, 10)),
            asyncio.create_task(_schleife("Überwachung", _ueberwachen, _intervall_ueberwachen, 15)),
            asyncio.create_task(_schleife("Agent", _agent_speichern, lambda: 30, 30)),
            asyncio.create_task(_schleife("Aufräumen", _aufraeumen, lambda: 6 * 3600, 120))]
