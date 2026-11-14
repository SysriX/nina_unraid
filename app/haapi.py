"""Schnittstelle für Home Assistant (und andere Programme): /api/ha/v1/…, Anmeldung per Bearer-Token.

Versioniert: Änderungen, die bestehende Felder brechen, kommen unter /api/ha/v2 – v1 bleibt dann bestehen.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select

import agent as agent_mod
import inventar
import kern
import migrationen
from kern import sitzung
from modelle import Agent, Geraet, Netzwerk
from zugang import LESER, OPERATOR, client_ip

router = APIRouter(prefix="/api/ha/v1")
API_VERSION = 1


@router.get("/info")
def info(ich: dict = Depends(LESER)):
    return {"id": kern.instanz_id(), "name": inventar.allgemein()["name"], "version": kern.VERSION, "api": API_VERSION,
            "schema": migrationen.AKTUELL, "rolle": ich["rolle"]}


def _ha_geraet(s, g: Geraet, d: dict) -> dict:
    out = {k: d.get(k) for k in ("id", "name", "typ", "typ_name", "hersteller", "modell", "raum", "standort", "benutzer",
                                 "angemeldet", "online", "zuletzt_online", "ip", "mac", "hostname", "netzwerk", "wol", "tags")}
    out.update(betriebssystem=g.betriebssystem, seriennummer=g.seriennummer, inventarnummer=g.inventarnummer,
               ueberwachen=g.ueberwachen, extra=g.extra or {})
    a = s.scalars(select(Agent).where(Agent.geraet_id == g.id)).first()
    if a:
        aj = agent_mod.agent_json(s, a, voll=True)
        out["agent"] = {"id": a.id, "name": a.name, "online": a.online, "version": a.version, "modell": a.modell,
                        "zuletzt": aj["zuletzt"],
                        "sensoren": [{k: w[k] for k in ("schluessel", "anzeige", "art", "wert", "einheit", "device_class",
                                                         "state_class", "icon", "kategorie", "attribute")}
                                     for w in aj["werte"] if w["importieren"]],
                        "befehle": [{k: b[k] for k in ("schluessel", "anzeige", "art", "icon", "kategorie", "gefahr", "zustand")}
                                    for b in aj["befehle"] if b["importieren"]]}
    else:
        out["agent"] = None
    return out


@router.get("/geraete")
def geraete(ich: dict = Depends(LESER)):
    with sitzung() as s:
        netze = {n.id: n.name for n in s.scalars(select(Netzwerk))}
        agenten = {a.geraet_id: a for a in s.scalars(select(Agent).where(Agent.geraet_id.is_not(None)))}
        out = []
        for g in s.scalars(select(Geraet).where(Geraet.status == "aktiv", Geraet.ha_import.is_(True)).order_by(Geraet.name)):
            out.append(_ha_geraet(s, g, inventar.geraet_json(s, g, netze=netze, agenten=agenten)))
    return {"id": kern.instanz_id(), "geraete": out}


@router.post("/geraete/{gid}/wecken")
def wecken(gid: int, req: Request, ich: dict = Depends(OPERATOR)):
    return inventar.wecken(gid, ich["name"], client_ip(req))


@router.post("/geraete/{gid}/befehl")
async def befehl(gid: int, req: Request, ich: dict = Depends(OPERATOR)):
    d = await req.json()
    return agent_mod.befehl(gid, str(d.get("befehl") or ""), ich["name"], client_ip(req), d.get("wert"))


@router.post("/geraete/{gid}/pruefen")
def pruefen(gid: int, ich: dict = Depends(LESER)):
    return inventar.geraet_pruefen(gid, ich)


@router.post("/scan")
async def scan(req: Request, ich: dict = Depends(OPERATOR)):
    import asyncio
    d = await req.json() if (await req.body()) else {}
    with sitzung() as s:
        ids = [int(d["netzwerk_id"])] if d.get("netzwerk_id") else [n.id for n in s.scalars(select(Netzwerk))]
    ergebnisse = []
    for nid in ids:
        try:
            ergebnisse.append({"netzwerk_id": nid, **(await asyncio.to_thread(inventar.scan, nid, ich["name"]))})
        except Exception as e:  # noqa: BLE001
            ergebnisse.append({"netzwerk_id": nid, "ok": False, "status": str(e)})
    return {"ergebnisse": ergebnisse}
