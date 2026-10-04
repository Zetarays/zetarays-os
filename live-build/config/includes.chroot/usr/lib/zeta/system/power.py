# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA RAYS — energia e sessione: blocca, sospendi, cambia utente, esci, riavvia, spegni."""
import glob
import os

from . import run, spawn


def lock():
    """Blocca lo schermo (hyprlock). Non attende."""
    if run(["pgrep", "-x", "hyprlock"]).strip():
        return
    spawn(["hyprlock"])


def suspend():
    """Standby. Dove la sospensione non è sicura (macchine virtuali: non si
    riprenderebbero) si blocca la sessione e si spegne lo schermo; tastiera o
    mouse lo riaccendono."""
    lock()
    if can_suspend():
        spawn(["sh", "-c", "sleep 1; systemctl suspend"])
    else:
        spawn(["sh", "-c", "sleep 1.5; hyprctl dispatch 'hl.dsp.dpms({action = \"off\"})'"])


def can_suspend():
    return (run(["busctl", "call", "org.freedesktop.login1", "/org/freedesktop/login1",
                 "org.freedesktop.login1.Manager", "CanSuspend"]) or "").strip() == 's "yes"'


def switch_user():
    """Mostra la schermata di accesso per un altro utente, senza bloccare.

    Non si blocca la sessione di proposito: hyprlock non si può sbloccare da
    programma (ignora SIGUSR1 e `loginctl unlock-session`, e non ha un comando
    di sblocco), quindi bloccare qui costringerebbe a digitare la password DUE
    volte al rientro — prima nella schermata di accesso e poi nel blocco.
    La schermata di accesso protegge già lo schermo; per bloccare davvero c'è
    il pulsante «Blocca».
    """
    run(["dbus-send", "--system", "--type=method_call", "--print-reply",
         "--dest=org.freedesktop.DisplayManager",
         os.environ.get("XDG_SEAT_PATH", "/org/freedesktop/DisplayManager/Seat0"),
         "org.freedesktop.DisplayManager.Seat.SwitchToGreeter"], timeout=6)


def logout():
    spawn(["hyprctl", "dispatch", "hl.dsp.exit()"])


def reboot():
    spawn(["systemctl", "reboot"])


def poweroff():
    spawn(["systemctl", "poweroff"])


def backlight():
    """(percentuale, device) oppure (None, None) se lo schermo non ha retroilluminazione."""
    devs = glob.glob("/sys/class/backlight/*")
    if not devs:
        return None, None
    d = devs[0]
    try:
        cur = int(open(d + "/brightness").read())
        mx = int(open(d + "/max_brightness").read()) or 1
        return round(cur * 100 / mx), os.path.basename(d)
    except (OSError, ValueError):
        return None, None


def set_backlight(percent):
    run(["brightnessctl", "set", "%d%%" % max(1, min(100, int(percent)))], timeout=3)


def battery():
    """None oppure {percent, charging, state}."""
    bats = glob.glob("/sys/class/power_supply/BAT*")
    if not bats:
        return None
    b = bats[0]
    try:
        cap = int(open(b + "/capacity").read())
    except (OSError, ValueError):
        cap = None
    try:
        st = open(b + "/status").read().strip()
    except OSError:
        st = "Unknown"
    names = {"Charging": "In carica", "Discharging": "A batteria", "Full": "Carica",
             "Not charging": "Collegata", "Unknown": ""}
    return {"percent": cap, "charging": st == "Charging", "state": names.get(st, st)}
