# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA RAYS Monitor — geolocalizzazione IP (richieste esterne, esplicite e disattivabili).

Usa ipwho.is via HTTPS. Risultati in cache (memoria + ~/.cache/zeta/geo.json)
per non ripetere le richieste. Gli indirizzi privati/locali non escono mai.
"""
import ipaddress
import json
import os
import threading
import time
import urllib.request

CACHE = os.path.expanduser("~/.cache/zeta/geo.json")
TTL = 7 * 24 * 3600
_lock = threading.Lock()
_mem = None


def _load():
    global _mem
    if _mem is None:
        try:
            with open(CACHE) as f:
                _mem = json.load(f)
        except (OSError, ValueError):
            _mem = {}
    return _mem


def _save():
    try:
        os.makedirs(os.path.dirname(CACHE), exist_ok=True)
        with open(CACHE + ".tmp", "w") as f:
            json.dump(_mem, f)
        os.replace(CACHE + ".tmp", CACHE)
    except OSError:
        pass


def is_public(ip):
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return not (a.is_private or a.is_loopback or a.is_link_local or a.is_multicast
                or a.is_reserved or a.is_unspecified)


def _query(ip=""):
    req = urllib.request.Request("https://ipwho.is/%s" % ip, headers={"User-Agent": "Zeta-Monitor"})
    with urllib.request.urlopen(req, timeout=6) as resp:
        d = json.loads(resp.read().decode("utf-8"))
    if not d.get("success", True):
        return None
    conn = d.get("connection") or {}
    return {"ip": d.get("ip"), "city": d.get("city") or "", "region": d.get("region") or "",
            "country": d.get("country") or "", "iso": d.get("country_code") or "",
            "lat": d.get("latitude"), "lon": d.get("longitude"),
            "isp": conn.get("isp") or conn.get("org") or "", "asn": conn.get("asn") or "",
            "t": time.time()}


def me():
    """Posizione dell'IP pubblico (None se offline o disattivata a monte)."""
    try:
        return _query("")
    except Exception:  # noqa: BLE001
        return None


def lookup(ip):
    """Posizione di un IP pubblico, dalla cache se possibile."""
    if not is_public(ip):
        return None
    with _lock:
        c = _load().get(ip)
        if c and time.time() - c.get("t", 0) < TTL:
            return c
    try:
        r = _query(ip)
    except Exception:  # noqa: BLE001
        return None
    if r:
        with _lock:
            _load()[ip] = r
            _save()
    return r


def cached(ip):
    with _lock:
        return _load().get(ip)
