# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA RAYS — power and session: lock, suspend, switch user, log out, restart, shut down."""
import glob
import os

from i18n import tr

from . import run, spawn


def lock():
    """Lock the screen (hyprlock). Does not wait."""
    if run(["pgrep", "-x", "hyprlock"]).strip():
        return
    spawn(["hyprlock"])


def suspend():
    """Standby. Where suspend isn't safe (virtual machines: they wouldn't
    resume) the session is locked and the screen turned off; the keyboard or
    mouse turns it back on."""
    lock()
    if can_suspend():
        spawn(["sh", "-c", "sleep 1; systemctl suspend"])
    else:
        spawn(["sh", "-c", "sleep 1.5; hyprctl dispatch 'hl.dsp.dpms({action = \"off\"})'"])


def can_suspend():
    return (run(["busctl", "call", "org.freedesktop.login1", "/org/freedesktop/login1",
                 "org.freedesktop.login1.Manager", "CanSuspend"]) or "").strip() == 's "yes"'


def switch_user():
    """Show the login screen for another user, without locking.

    The session is deliberately not locked: hyprlock can't be unlocked
    programmatically (it ignores SIGUSR1 and `loginctl unlock-session`, and has
    no unlock command), so locking here would force the user to type the
    password TWICE on return — first on the login screen and then on the lock.
    The login screen already protects the display; to really lock there is the
    "Lock" button.
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
    """(percentage, device), or (None, None) if the screen has no backlight."""
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
    """None, or {percent, charging, state}."""
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
    names = {"Charging": tr("Charging"), "Discharging": tr("On battery"), "Full": tr("Charged"),
             "Not charging": tr("Plugged in"), "Unknown": ""}
    return {"percent": cap, "charging": st == "Charging", "state": names.get(st, st)}
