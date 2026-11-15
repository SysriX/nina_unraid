"""Netzwerk-Werkzeuge: Scan (nmap oder Ping), ARP-Tabelle, Erreichbarkeit, Wake-on-LAN, MAC-Hersteller.

Im Container (Unraid br0 mit eigener IP) sieht nmap im eigenen Netz auch MAC-Adressen (ARP).
In gerouteten Netzen gibt es nur IP/Name – MACs kommen dann von der OPNsense (ARP/DHCP).
"""
from __future__ import annotations

import ipaddress
import os
import platform
import re
import shutil
import socket
import subprocess
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor

WINDOWS = platform.system() == "Windows"
MAX_HOSTS = 4096
_MAC_RX = re.compile(r"^([0-9a-f]{2})[:-]?([0-9a-f]{2})[:-]?([0-9a-f]{2})[:-]?([0-9a-f]{2})[:-]?([0-9a-f]{2})[:-]?([0-9a-f]{2})$", re.I)
_hersteller: dict[str, str] | None = None


def mac_norm(s: str | None) -> str:
    m = _MAC_RX.match((s or "").strip().replace(".", ""))
    if not m:
        return ""
    mac = ":".join(x.lower() for x in m.groups())
    return "" if mac in ("00:00:00:00:00:00", "ff:ff:ff:ff:ff:ff") else mac


def ist_mac(s: str) -> bool:
    return bool(mac_norm(s))


def ip_gueltig(s: str) -> bool:
    try:
        ipaddress.ip_address((s or "").strip())
        return True
    except ValueError:
        return False


def netz(cidr: str) -> ipaddress.IPv4Network:
    return ipaddress.ip_network(cidr.strip(), strict=False)


def im_netz(ip: str, cidr: str) -> bool:
    try:
        return ipaddress.ip_address(ip) in netz(cidr)
    except ValueError:
        return False


def mac_hersteller(mac: str) -> str:
    """Hersteller aus der nmap-Datenbank (wenn nmap installiert ist)."""
    global _hersteller
    if _hersteller is None:
        _hersteller = {}
        for pfad in ("/usr/share/nmap/nmap-mac-prefixes", "/usr/local/share/nmap/nmap-mac-prefixes",
                     r"C:\Program Files (x86)\Nmap\nmap-mac-prefixes", r"C:\Program Files\Nmap\nmap-mac-prefixes"):
            if os.path.exists(pfad):
                with open(pfad, encoding="utf-8", errors="replace") as f:
                    for z in f:
                        if z and not z.startswith("#") and len(z) > 7:
                            _hersteller[z[:6].upper()] = z[7:].strip()
                break
    mac = mac_norm(mac)
    if not mac:
        return ""
    if int(mac[1], 16) & 2:
        return "(zufällige MAC)"
    return _hersteller.get(mac.replace(":", "")[:6].upper(), "")


def nmap_da() -> bool:
    return bool(shutil.which("nmap"))


# ------------------------------------------------------------------ Scan
def scan_nmap(cidr: str, timeout: int = 600) -> list[dict]:
    n = netz(cidr)
    if n.num_addresses > MAX_HOSTS:
        raise ValueError(f"Netz {cidr} ist zu groß (höchstens {MAX_HOSTS} Adressen)")
    r = subprocess.run(["nmap", "-sn", "-T4", "--max-retries", "1", "-oX", "-", str(n)],
                       capture_output=True, text=True, errors="replace", timeout=timeout)
    if r.returncode != 0 and not r.stdout:
        raise RuntimeError((r.stderr or "nmap fehlgeschlagen").strip()[:400])
    out = []
    for host in ET.fromstring(r.stdout).findall("host"):
        st = host.find("status")
        if st is None or st.get("state") != "up":
            continue
        d = {"ip": "", "mac": "", "hostname": "", "hersteller": ""}
        for a in host.findall("address"):
            if a.get("addrtype") == "ipv4":
                d["ip"] = a.get("addr", "")
            elif a.get("addrtype") == "mac":
                d["mac"] = mac_norm(a.get("addr"))
                d["hersteller"] = a.get("vendor", "") or ""
        hn = host.find("hostnames/hostname")
        if hn is not None:
            d["hostname"] = hn.get("name", "")
        if d["ip"]:
            out.append(d)
    return out


def ping(ip: str, timeout: float = 1.0) -> bool:
    if not ip_gueltig(ip):
        return False
    if WINDOWS:
        cmd = ["ping", "-n", "1", "-w", str(int(timeout * 1000)), ip]
    else:
        cmd = ["ping", "-c", "1", "-W", str(max(1, int(round(timeout)))), "-q", ip]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=timeout + 3,
                           creationflags=0x08000000 if WINDOWS else 0)
        if WINDOWS:   # Windows meldet auch "Zielhost nicht erreichbar" mit 0 – TTL= ist der sichere Treffer
            return "TTL=" in r.stdout.upper()
        return r.returncode == 0
    except Exception:  # noqa: BLE001
        return False


def tcp_offen(ip: str, ports=(445, 22, 80, 443, 3389, 8080), timeout: float = 0.6) -> bool:
    for p in ports:
        try:
            with socket.create_connection((ip, p), timeout=timeout):
                return True
        except ConnectionRefusedError:
            return True       # Host antwortet (Port zu) = erreichbar
        except OSError:
            continue
    return False


def erreichbar(ip: str) -> bool:
    return ping(ip) or tcp_offen(ip, ports=(445, 3389, 22), timeout=0.5)


def arp_tabelle() -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        if os.path.exists("/proc/net/arp"):
            with open("/proc/net/arp", encoding="utf-8") as f:
                for z in f.readlines()[1:]:
                    t = z.split()
                    if len(t) >= 4 and t[2] != "0x0":
                        mac = mac_norm(t[3])
                        if mac:
                            out[t[0]] = mac
        elif WINDOWS:
            r = subprocess.run(["arp", "-a"], capture_output=True, text=True, errors="replace", timeout=10, creationflags=0x08000000)
            for ip, mac in re.findall(r"(\d+\.\d+\.\d+\.\d+)\s+([0-9a-f-]{17})", r.stdout, re.I):
                mac = mac_norm(mac)
                if mac and not mac.startswith("01:00:5e"):
                    out[ip] = mac
    except Exception:  # noqa: BLE001
        pass
    return out


def rdns(ip: str) -> str:
    try:
        old = socket.getdefaulttimeout()
        socket.setdefaulttimeout(2)
        try:
            return socket.gethostbyaddr(ip)[0]
        finally:
            socket.setdefaulttimeout(old)
    except Exception:  # noqa: BLE001
        return ""


def scan_ping(cidr: str) -> list[dict]:
    n = netz(cidr)
    if n.num_addresses > 1024:
        raise ValueError(f"Ping-Scan nur bis /22 – {cidr} ist zu groß (nmap installieren)")
    ips = [str(i) for i in (n.hosts() if n.num_addresses > 2 else n)]
    with ThreadPoolExecutor(64) as ex:
        an = [ip for ip, ok in zip(ips, ex.map(lambda i: ping(i, 1.0), ips)) if ok]
        namen = dict(zip(an, ex.map(rdns, an)))
    arp = arp_tabelle()
    return [{"ip": ip, "mac": arp.get(ip, ""), "hostname": namen.get(ip, ""), "hersteller": mac_hersteller(arp.get(ip, ""))}
            for ip in an]


def eigene_adressen() -> list[ipaddress.IPv4Interface]:
    """IPv4-Adressen (mit Netz) des Containers – für WoL „auto“ und die Netz-Vorschläge."""
    out = []
    try:
        if not WINDOWS and shutil.which("ip"):
            r = subprocess.run(["ip", "-o", "-4", "addr", "show"], capture_output=True, text=True, errors="replace", timeout=5)
            for m in re.finditer(r"inet (\d+\.\d+\.\d+\.\d+/\d+)", r.stdout):
                i = ipaddress.ip_interface(m.group(1))
                if not i.ip.is_loopback:
                    out.append(i)
        if not out:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                s.connect(("192.0.2.1", 9))
                out.append(ipaddress.ip_interface(s.getsockname()[0] + "/24"))
            finally:
                s.close()
    except Exception:  # noqa: BLE001
        pass
    return out


def eigene_ip() -> str:
    a = os.environ.get("NINA_ADRESSE", "").strip()
    if a:
        return a
    e = eigene_adressen()
    return str(e[0].ip) if e else "127.0.0.1"


def direkt_erreichbar(cidr: str) -> bool:
    try:
        n = netz(cidr)
        return any(i.ip in n for i in eigene_adressen())
    except ValueError:
        return False


# ------------------------------------------------------------------ Wake-on-LAN
def magic_ethernet(mac: str, wiederholen: int = 3) -> list[str]:
    """Magic Packet als rohes Ethernet-Paket (EtherType 0x0842) an ff:ff:ff:ff:ff:ff auf allen Schnittstellen (nur Linux)."""
    mac = mac_norm(mac)
    if WINDOWS or not mac or not hasattr(socket, "AF_PACKET"):
        return []
    nutz = b"\xff" * 6 + bytes.fromhex(mac.replace(":", "")) * 16
    out = []
    for _, name in socket.if_nameindex():
        if name == "lo":
            continue
        try:
            s = socket.socket(socket.AF_PACKET, socket.SOCK_RAW)
            try:
                s.bind((name, 0))
                eigen = s.getsockname()[4][:6]
                rahmen = b"\xff" * 6 + eigen + b"\x08\x42" + nutz
                for _ in range(wiederholen):
                    s.send(rahmen)
                out.append(f"Ethernet {name}")
            finally:
                s.close()
        except OSError:
            continue
    return out


def magic_paket(mac: str, ziele: list[str], port: int = 9, wiederholen: int = 3) -> list[str]:
    mac = mac_norm(mac)
    if not mac:
        raise ValueError("Keine gültige MAC-Adresse")
    paket = b"\xff" * 6 + bytes.fromhex(mac.replace(":", "")) * 16
    gesendet = []
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        for ziel in dict.fromkeys(z for z in ziele if z):
            for _ in range(wiederholen):
                s.sendto(paket, (ziel, port))
            gesendet.append(f"{ziel}:{port}")
    finally:
        s.close()
    return gesendet
