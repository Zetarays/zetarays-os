# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA RAYS — Bluetooth (BlueZ).

Lo stato si legge da D-Bus con `busctl` (risposta immediata). `bluetoothctl`
si usa solo per le azioni (associa, connetti, cerca) e mai se non c'è un
adattatore: senza adattatore `bluetoothctl show` resta in attesa per sempre.
"""
import glob
import json
import os

from . import run


def _adapter_path():
    hcis = sorted(glob.glob("/sys/class/bluetooth/hci*"))
    if not hcis:
        return None
    return "/org/bluez/" + os.path.basename(hcis[0])


def _prop(path, iface, name):
    out = run(["busctl", "--system", "--json=short", "get-property", "org.bluez", path, iface, name], timeout=3)
    try:
        return json.loads(out)["data"] if out else None
    except (ValueError, KeyError):
        return None


def adapter():
    """None se non c'è un adattatore, altrimenti {powered, name}."""
    path = _adapter_path()
    if not path:
        return None
    powered = _prop(path, "org.bluez.Adapter1", "Powered")
    if powered is None:
        return None
    alias = _prop(path, "org.bluez.Adapter1", "Alias") or "Bluetooth"
    return {"powered": bool(powered), "name": alias}


def set_power(on):
    path = _adapter_path()
    if not path:
        return
    if on:
        run(["rfkill", "unblock", "bluetooth"], timeout=4)
    run(["busctl", "--system", "set-property", "org.bluez", path, "org.bluez.Adapter1",
         "Powered", "b", "true" if on else "false"], timeout=5)


def devices():
    """Dispositivi noti: [{mac, name, paired, connected, icon}]."""
    if not _adapter_path():
        return []
    out = run(["busctl", "--system", "--json=short", "call", "org.bluez", "/",
               "org.freedesktop.DBus.ObjectManager", "GetManagedObjects"], timeout=4)
    try:
        objs = json.loads(out)["data"][0] if out else {}
    except (ValueError, KeyError, IndexError):
        return []
    rows = []
    for _path, ifaces in objs.items():
        dev = ifaces.get("org.bluez.Device1")
        if not dev:
            continue
        val = lambda k, d=None: (dev.get(k) or {}).get("data", d)  # noqa: E731
        rows.append({"mac": val("Address", ""), "name": val("Alias") or val("Name") or val("Address", ""),
                     "paired": bool(val("Paired", False)), "connected": bool(val("Connected", False)),
                     "icon": val("Icon", "bluetooth")})
    return sorted(rows, key=lambda d: (not d["connected"], not d["paired"], d["name"].lower()))


def scan(seconds=8):
    if _adapter_path():
        run(["bluetoothctl", "--timeout", str(seconds), "scan", "on"], timeout=seconds + 4)


def connect(mac):
    if not _adapter_path():
        return False
    run(["bluetoothctl", "--timeout", "15", "pair", mac], timeout=20)
    run(["bluetoothctl", "--timeout", "5", "trust", mac], timeout=8)
    return run(["bluetoothctl", "--timeout", "15", "connect", mac], timeout=20, check=True) is not None


def disconnect(mac):
    if _adapter_path():
        run(["bluetoothctl", "--timeout", "8", "disconnect", mac], timeout=10)


def forget(mac):
    if _adapter_path():
        run(["bluetoothctl", "--timeout", "8", "remove", mac], timeout=10)
