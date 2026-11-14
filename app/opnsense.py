"""OPNsense-API: ARP-Tabelle und DHCP-Leases aller Netze (Quelle für MAC/Name), Wake-on-LAN über das Plugin os-wol.

Zugang: System › Zugang › Benutzer › API-Schlüssel (Key + Secret). Nötige Rechte:
  Diagnostics: ARP Table, Services: DHCP leases (ISC/Kea/Dnsmasq – je nach Version), Services: Wake on LAN,
  Interfaces (Namen der Schnittstellen).
"""
from __future__ import annotations

import httpx

import kern
import netz


class Fehler(Exception):
    pass


def konfig() -> dict:
    k = kern.einstellung("opnsense", {}) or {}
    g = kern.geheim("opnsense")
    return {"url": (k.get("url") or "").rstrip("/"), "pruefen": k.get("tls_pruefen", True), "aktiv": k.get("aktiv", False),
            "arp": k.get("arp", True), "dhcp": k.get("dhcp", True), "key": g.get("key", ""), "secret": g.get("secret", "")}


def eingerichtet() -> bool:
    k = konfig()
    return bool(k["aktiv"] and k["url"] and k["key"] and k["secret"])


def _client(k: dict | None = None) -> httpx.Client:
    k = k or konfig()
    if not (k["url"] and k["key"] and k["secret"]):
        raise Fehler("OPNsense ist nicht eingerichtet")
    return httpx.Client(base_url=k["url"], auth=(k["key"], k["secret"]), verify=bool(k["pruefen"]), timeout=20)


def _get(c: httpx.Client, *pfade: str):
    """Erster Pfad, der antwortet (die API-Namen haben sich zwischen Versionen geändert)."""
    letzter = None
    for p in pfade:
        try:
            r = c.get(p)
        except httpx.HTTPError as e:
            raise Fehler(f"OPNsense nicht erreichbar: {e}") from e
        if r.status_code == 200:
            try:
                return r.json()
            except ValueError:
                letzter = f"{p}: keine JSON-Antwort"
                continue
        if r.status_code in (401, 403):
            raise Fehler(f"OPNsense: Zugriff verweigert ({r.status_code}) – Key/Secret bzw. Rechte prüfen")
        letzter = f"{p}: HTTP {r.status_code}"
    raise Fehler(letzter or "keine Antwort")


def testen(k: dict | None = None) -> dict:
    with _client(k) as c:
        namen = _get(c, "/api/diagnostics/interface/get_interface_names", "/api/diagnostics/interface/getInterfaceNames")
    return {"ok": True, "interfaces": namen}


def interfaces() -> dict:
    """{'lan': 'LAN', 'opt1': 'IoT', …}"""
    with _client() as c:
        namen = _get(c, "/api/diagnostics/interface/get_interface_names", "/api/diagnostics/interface/getInterfaceNames")
    # Antwort ist {Gerätename: Beschreibung}; für WoL braucht es den Schlüssel (lan/opt1) – aus der Übersicht
    try:
        with _client() as c:
            ov = _get(c, "/api/interfaces/overview/interfaces_info", "/api/interfaces/overview/interfacesInfo")
        rows = ov.get("rows", ov) if isinstance(ov, dict) else ov
        out = {}
        for r in rows or []:
            ident = r.get("identifier") or ""
            if ident:
                out[ident] = r.get("description") or r.get("device") or ident
        if out:
            return out
    except Fehler:
        pass
    return {k: v for k, v in (namen or {}).items()}


def arp() -> list[dict]:
    with _client() as c:
        d = _get(c, "/api/diagnostics/interface/get_arp", "/api/diagnostics/interface/getArp",
                 "/api/diagnostics/interface/search_arp")
    rows = d.get("rows", d) if isinstance(d, dict) else d
    out = []
    for r in rows or []:
        mac, ip = netz.mac_norm(r.get("mac")), r.get("ip", "")
        if not mac or not ip or r.get("expired"):
            continue
        out.append({"ip": ip, "mac": mac, "hostname": r.get("hostname") or "",
                    "hersteller": r.get("manufacturer") or netz.mac_hersteller(mac), "interface": r.get("intf", "")})
    return out


def leases() -> list[dict]:
    out = []
    with _client() as c:
        for pfad, ip_k, mac_k, name_k in (("/api/dnsmasq/leases/search", "address", "hwaddr", "hostname"),
                                          ("/api/kea/leases4/search", "address", "hwaddr", "hostname"),
                                          ("/api/dhcpv4/leases/search_lease", "address", "mac", "hostname"),
                                          ("/api/dhcpv4/leases/searchLease", "address", "mac", "hostname")):
            try:
                r = c.get(pfad)
            except httpx.HTTPError:
                continue
            if r.status_code != 200:
                continue
            try:
                rows = r.json().get("rows", [])
            except ValueError:
                continue
            for x in rows:
                mac = netz.mac_norm(x.get(mac_k))
                if mac and x.get(ip_k):
                    out.append({"ip": x[ip_k], "mac": mac, "hostname": x.get(name_k) or "",
                                "hersteller": x.get("man") or netz.mac_hersteller(mac), "interface": x.get("if", "")})
    return out


def bekannte_hosts() -> list[dict]:
    """ARP + DHCP zusammen (ARP gewinnt bei der IP, DHCP liefert oft den Namen)."""
    k = konfig()
    nach_mac: dict[str, dict] = {}
    if k["dhcp"]:
        for x in leases():
            nach_mac[x["mac"]] = x
    if k["arp"]:
        for x in arp():
            alt = nach_mac.get(x["mac"], {})
            x["hostname"] = x["hostname"] or alt.get("hostname", "")
            x["online"] = True
            nach_mac[x["mac"]] = x
    return list(nach_mac.values())


def wecken(mac: str, interface: str) -> str:
    mac = netz.mac_norm(mac)
    if not mac:
        raise Fehler("Keine gültige MAC-Adresse")
    if not interface:
        raise Fehler("Für dieses Netz ist keine OPNsense-Schnittstelle (z. B. lan, opt1) eingetragen")
    with _client() as c:
        try:
            r = c.post("/api/wol/wol/set", json={"wake": {"interface": interface, "mac": mac}})
        except httpx.HTTPError as e:
            raise Fehler(f"OPNsense nicht erreichbar: {e}") from e
    if r.status_code == 404:
        raise Fehler("OPNsense: Wake-on-LAN-API fehlt – Plugin os-wol installieren")
    if r.status_code != 200:
        raise Fehler(f"OPNsense WoL: HTTP {r.status_code} {r.text[:200]}")
    try:
        d = r.json()
    except ValueError:
        d = {}
    if isinstance(d, dict) and str(d.get("status", "ok")).lower() not in ("ok", "success", "done", ""):
        raise Fehler(f"OPNsense WoL: {d}")
    return f"OPNsense ({interface})"
