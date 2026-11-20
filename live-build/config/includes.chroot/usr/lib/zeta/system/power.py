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


# ---------------------------------------------------------------- power modes
# power-profiles-daemon: the current D-Bus name first, then the old one.
_PROFILES_BUS = (("org.freedesktop.UPower.PowerProfiles", "/org/freedesktop/UPower/PowerProfiles"),
                 ("net.hadess.PowerProfiles", "/net/hadess/PowerProfiles"))
PROFILE_ORDER = ("power-saver", "balanced", "performance")


def _busctl_json(args, timeout=3):
    import json
    out = run(["busctl", "--system", "--json=short"] + args, timeout=timeout)
    try:
        return json.loads(out) if out else None
    except ValueError:
        return None


def _profiles_property(name):
    for bus, path in _PROFILES_BUS:
        d = _busctl_json(["get-property", bus, path, bus, name])
        if d is not None:
            return bus, path, d.get("data")
    return None, None, None


def power_profiles():
    """None without power-profiles-daemon, else {"active": "balanced",
    "available": [...] in PROFILE_ORDER, "degraded": reason or ""}."""
    bus, path, data = _profiles_property("Profiles")
    if bus is None or not isinstance(data, list):
        return None
    names = set()
    for p in data:
        v = (p.get("Profile") or {}).get("data") if isinstance(p, dict) else None
        if v in PROFILE_ORDER:
            names.add(v)
    act = _busctl_json(["get-property", bus, path, bus, "ActiveProfile"]) or {}
    deg = _busctl_json(["get-property", bus, path, bus, "PerformanceDegraded"]) or {}
    return {"active": act.get("data") if act.get("data") in PROFILE_ORDER else "balanced",
            "available": [n for n in PROFILE_ORDER if n in names],
            "degraded": deg.get("data") or ""}


def set_power_profile(name):
    """Switch power mode (polkit lets the active session do it); True if done."""
    if name not in PROFILE_ORDER:
        return False
    for bus, path in _PROFILES_BUS:
        if run(["busctl", "--system", "set-property", bus, path, bus,
                "ActiveProfile", "s", name], timeout=5, check=True) is not None:
            return True
    return False


# ------------------------------------------------------------- battery detail
def _read(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return None


def _number(path):
    v = _read(path)
    try:
        return int(v) if v is not None else None
    except ValueError:
        return None


def on_ac_power():
    """True when a charger is plugged in, None when unknown (no battery)."""
    for d in glob.glob("/sys/class/power_supply/*"):
        if _read(d + "/type") == "Mains":
            return _read(d + "/online") == "1"
    return None


def battery_details():
    """None, or what battery() gives plus health (% of the design capacity),
    minutes left (to empty or to full), cycle count, model."""
    info = battery()
    if info is None:
        return None
    b = sorted(glob.glob("/sys/class/power_supply/BAT*"))[0]
    now = _number(b + "/energy_now")
    full = _number(b + "/energy_full")
    design = _number(b + "/energy_full_design")
    rate = _number(b + "/power_now")
    if now is None:                     # charge (µAh) instead of energy (µWh)
        now = _number(b + "/charge_now")
        full = _number(b + "/charge_full")
        design = _number(b + "/charge_full_design")
        rate = _number(b + "/current_now")
    status = _read(b + "/status") or "Unknown"
    health = round(full * 100 / design) if full and design else None
    minutes = None
    if rate and rate > 0 and now is not None:
        if status == "Discharging":
            minutes = round(now * 60 / rate)
        elif status == "Charging" and full:
            minutes = round(max(0, full - now) * 60 / rate)
    cycles = _number(b + "/cycle_count")
    model = " ".join(x for x in (_read(b + "/manufacturer"), _read(b + "/model_name")) if x)
    info.update(status=status, health=min(health, 100) if health else None,
                minutes=minutes if minutes and minutes < 100 * 60 else None,
                cycles=cycles if cycles else None, model=model or None,
                ac=on_ac_power())
    return info


# ---------------------------------------------------------------- power button
POWER_BUTTON_ACTIONS = ("poweroff", "suspend", "lock", "ignore")
POWER_BUTTON_HELPER = "/usr/libexec/zeta-power-button"


def power_button_action():
    """What logind does with the power button (HandlePowerKey), as read from
    its configuration files; the drop-ins win, in name order."""
    value = "poweroff"
    dropins = {}                         # same name: /etc wins over /usr/lib
    for d in ("/usr/lib/systemd/logind.conf.d", "/etc/systemd/logind.conf.d"):
        for path in glob.glob(d + "/*.conf"):
            dropins[os.path.basename(path)] = path
    files = ["/usr/lib/systemd/logind.conf", "/etc/systemd/logind.conf"]
    files += [dropins[n] for n in sorted(dropins)]
    for path in files:
        text = _read(path)
        for line in (text or "").splitlines():
            line = line.strip()
            if line.startswith("HandlePowerKey="):
                value = line.split("=", 1)[1].strip()
    return value


def set_power_button_action(action):
    """Through the polkit helper (asks for the administrator password).
    Returns True when done."""
    if action not in POWER_BUTTON_ACTIONS or not os.path.exists(POWER_BUTTON_HELPER):
        return False
    return run(["pkexec", POWER_BUTTON_HELPER, action], timeout=120, check=True) is not None
