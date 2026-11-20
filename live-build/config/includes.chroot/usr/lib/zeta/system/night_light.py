# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA RAYS — Night light: warmer screen colors in the evening.

A single long-running `wlsunset` process does the work (Hyprland 0.55
implements wlr-gamma-control-unstable-v1). This module only writes its
command line from the settings and starts or replaces it: nothing polls.

Settings in ~/.config/zeta/night-light.json:

    enabled      true | false
    schedule     "always" | "sunset" (sunset to sunrise) | "custom"
    temperature  1500–6000 K (default 4000)
    from, to     "HH:MM": custom schedule, on at `from`, off at `to`
    latitude, longitude   optional: otherwise derived from the time zone
                          (/usr/share/zoneinfo/zone1970.tab), never online

Kept free of GTK: the command-line tool and the Control Center import it.
"""
import json
import math
import os
import re
import shutil
import subprocess
import time

CONFIG = os.path.expanduser("~/.config/zeta/night-light.json")
SCHEDULES = ("always", "sunset", "custom")
T_MIN, T_MAX, T_DEFAULT = 1500, 6000, 4000
DAY_TEMPERATURE = 6500            # wlsunset's neutral daylight
RAMP_SECONDS = 600                # custom schedule: gradual change, 10 minutes
DEFAULTS = {"enabled": False, "schedule": "sunset", "temperature": T_DEFAULT,
            "from": "21:00", "to": "07:00"}
# used when the time zone gives no position (UTC, unknown): sunset to sunrise
# then behaves like these fixed times
FALLBACK_FROM, FALLBACK_TO = "20:00", "07:00"
ZONEINFO = "/usr/share/zoneinfo"
_TIME_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


# ------------------------------------------------------------------ settings
def valid_time(value):
    return isinstance(value, str) and bool(_TIME_RE.match(value))


def minutes(value):
    h, m = value.split(":")
    return int(h) * 60 + int(m)


def hhmm(total_minutes):
    total_minutes = int(round(total_minutes)) % 1440
    return "%02d:%02d" % (total_minutes // 60, total_minutes % 60)


def clamp_temperature(value):
    try:
        value = int(value)
    except (TypeError, ValueError):
        return T_DEFAULT
    return max(T_MIN, min(T_MAX, value))


def load():
    """The settings, every value checked (a broken file gives the defaults)."""
    conf = dict(DEFAULTS)
    try:
        with open(CONFIG, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    if isinstance(data.get("enabled"), bool):
        conf["enabled"] = data["enabled"]
    if data.get("schedule") in SCHEDULES:
        conf["schedule"] = data["schedule"]
    if "temperature" in data:
        conf["temperature"] = clamp_temperature(data["temperature"])
    for key in ("from", "to"):
        if valid_time(data.get(key)):
            conf[key] = data[key]
    for key, limit in (("latitude", 90), ("longitude", 180)):
        v = data.get(key)
        if isinstance(v, (int, float)) and not isinstance(v, bool) and -limit <= v <= limit:
            conf[key] = float(v)
    return conf


def save(conf):
    os.makedirs(os.path.dirname(CONFIG), exist_ok=True)
    tmp = CONFIG + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(conf, f, indent=2)
        f.write("\n")
    os.replace(tmp, CONFIG)


def update(**values):
    """Change some settings (checked) and save; returns the new settings."""
    conf = load()
    for key, value in values.items():
        if key == "enabled":
            conf["enabled"] = bool(value)
        elif key == "schedule":
            if value not in SCHEDULES:
                raise ValueError("schedule")
            conf["schedule"] = value
        elif key == "temperature":
            conf["temperature"] = clamp_temperature(value)
        elif key in ("from", "to"):
            if not valid_time(value):
                raise ValueError(key)
            conf[key] = "%02d:%02d" % divmod(minutes(value), 60)
        else:
            raise ValueError(key)
    if conf["from"] == conf["to"]:
        raise ValueError("from")
    save(conf)
    return conf


# ------------------------------------------------------------------ location
def timezone_name():
    """"Europe/Rome", or None."""
    tz = os.environ.get("TZ", "").lstrip(":")
    if tz and "/" in tz and not tz.startswith("/"):
        return tz
    try:
        target = os.readlink("/etc/localtime")
        if "zoneinfo/" in target:
            return target.split("zoneinfo/", 1)[1]
    except OSError:
        pass
    try:
        with open("/etc/timezone", encoding="utf-8") as f:
            return f.read().strip() or None
    except OSError:
        return None


def _iso6709(text):
    """"+4154+01229" or "+415400+0122900" -> (41.9, 12.48)."""
    m = re.match(r"^([+-])(\d{2})(\d{2})(\d{2})?([+-])(\d{3})(\d{2})(\d{2})?$", text)
    if not m:
        return None
    s1, d1, m1, x1, s2, d2, m2, x2 = m.groups()
    lat = int(d1) + int(m1) / 60 + int(x1 or 0) / 3600
    lon = int(d2) + int(m2) / 60 + int(x2 or 0) / 3600
    return (-lat if s1 == "-" else lat, -lon if s2 == "-" else lon)


def _tab_coordinates(name):
    for tab in ("zone1970.tab", "zone.tab"):
        try:
            with open(os.path.join(ZONEINFO, tab), encoding="utf-8") as f:
                for line in f:
                    if line.startswith("#"):
                        continue
                    parts = line.rstrip("\n").split("\t")
                    if len(parts) >= 3 and parts[2] == name:
                        return _iso6709(parts[1])
        except OSError:
            continue
    return None


def _link_target(name):
    """Old names ("Asia/Calcutta", "US/Eastern") point to a current zone."""
    path = os.path.join(ZONEINFO, name)
    try:
        real = os.path.realpath(path)
        base = os.path.realpath(ZONEINFO) + os.sep
        if real.startswith(base) and real[len(base):] != name:
            return real[len(base):]
    except OSError:
        pass
    try:
        with open(os.path.join(ZONEINFO, "tzdata.zi"), encoding="utf-8") as f:
            for line in f:
                parts = line.split()
                if len(parts) == 3 and parts[0] == "L" and parts[2] == name:
                    return parts[1]
    except OSError:
        pass
    return None


def location(conf=None):
    """(latitude, longitude) of the settings or of the time zone, or None."""
    conf = conf or load()
    if "latitude" in conf and "longitude" in conf:
        return conf["latitude"], conf["longitude"]
    name = timezone_name()
    if not name or name.startswith("Etc/") or name in ("UTC", "GMT", "Universal", "Zulu"):
        return None
    found = _tab_coordinates(name)
    if found is None:
        target = _link_target(name)
        if target:
            found = _tab_coordinates(target)
    return found


# ------------------------------------------------------------------ the sun
def sun_times(lat, lon, day=None, utc_offset_minutes=None):
    """Local sunrise and sunset in minutes after midnight (NOAA algorithm).

    Returns (sunrise, sunset), or "day" / "night" where the sun does not
    set or rise that day.
    """
    day = day or time.localtime()
    if utc_offset_minutes is None:
        utc_offset_minutes = (day.tm_gmtoff or 0) / 60
    n = day.tm_yday
    gamma = 2 * math.pi / 365 * (n - 1)
    eqtime = 229.18 * (0.000075 + 0.001868 * math.cos(gamma) - 0.032077 * math.sin(gamma)
                       - 0.014615 * math.cos(2 * gamma) - 0.040849 * math.sin(2 * gamma))
    decl = (0.006918 - 0.399912 * math.cos(gamma) + 0.070257 * math.sin(gamma)
            - 0.006758 * math.cos(2 * gamma) + 0.000907 * math.sin(2 * gamma)
            - 0.002697 * math.cos(3 * gamma) + 0.00148 * math.sin(3 * gamma))
    phi = math.radians(lat)
    cos_ha = (math.cos(math.radians(90.833)) / (math.cos(phi) * math.cos(decl))
              - math.tan(phi) * math.tan(decl))
    if cos_ha < -1:
        return "day"
    if cos_ha > 1:
        return "night"
    ha = math.degrees(math.acos(cos_ha))
    sunrise = 720 - 4 * (lon + ha) - eqtime + utc_offset_minutes
    sunset = 720 - 4 * (lon - ha) - eqtime + utc_offset_minutes
    return sunrise % 1440, sunset % 1440


def window(conf=None, now=None):
    """The night period for today: {"kind": "always"|"window"|"never",
    "from": minutes, "to": minutes, "located": bool}."""
    conf = conf or load()
    now = now or time.localtime()
    if conf["schedule"] == "always":
        return {"kind": "always", "located": True}
    if conf["schedule"] == "custom":
        return {"kind": "window", "from": minutes(conf["from"]), "to": minutes(conf["to"]),
                "located": True}
    loc = location(conf)
    if loc is None:
        return {"kind": "window", "from": minutes(FALLBACK_FROM), "to": minutes(FALLBACK_TO),
                "located": False}
    times = sun_times(loc[0], loc[1], now)
    if times == "day":
        return {"kind": "never", "located": True}
    if times == "night":
        return {"kind": "always", "located": True}
    return {"kind": "window", "from": times[1], "to": times[0], "located": True}


def is_night(win, now=None):
    now = now or time.localtime()
    if win["kind"] != "window":
        return win["kind"] == "always"
    t = now.tm_hour * 60 + now.tm_min
    start, end = win["from"], win["to"]
    if start <= end:
        return start <= t < end
    return t >= start or t < end


# ------------------------------------------------------------------ wlsunset
def _posix_tz(offset_seconds):
    """A fixed POSIX time zone east of UTC by offset_seconds ("<ZRN>-02:30").
    The name needs at least three letters: glibc rejects a shorter one and
    silently falls back to UTC."""
    offset_seconds = int(offset_seconds) % 86400
    if offset_seconds > 43200:
        offset_seconds -= 86400
    sign = "-" if offset_seconds >= 0 else "+"       # POSIX: west is positive
    a = abs(offset_seconds)
    return "<ZRN>%s%02d:%02d" % (sign, a // 3600, (a % 3600) // 60)


def command(conf=None, temperature=None, now=None):
    """(argv, extra environment) of the wlsunset process for these settings.

    wlsunset knows "sunrise" and "sunset": the night runs from the sunset
    time to the sunrise time of the next morning. A custom period inside a
    single day (for example 00:30 to 06:00) cannot be written that way, so
    wlsunset gets a shifted clock (its own TZ) where that period crosses
    midnight; it only uses the time of day, so the result is the same.
    """
    conf = conf or load()
    now = now or time.localtime()
    temp = clamp_temperature(conf["temperature"] if temperature is None else temperature)
    if temperature is not None or conf["schedule"] == "always":
        # always: day and night differ by 1 K, so it is warm all day long
        return (["wlsunset", "-t", str(temp), "-T", str(temp + 1),
                 "-S", "06:00", "-s", "18:00", "-d", "0"], {})
    base = ["wlsunset", "-t", str(temp), "-T", str(DAY_TEMPERATURE)]
    loc = location(conf) if conf["schedule"] == "sunset" else None
    if conf["schedule"] == "sunset" and loc is not None:
        return base + ["-l", "%.4f" % loc[0], "-L", "%.4f" % loc[1]], {}
    if conf["schedule"] == "sunset":
        start, end = minutes(FALLBACK_FROM), minutes(FALLBACK_TO)
    else:
        start, end = minutes(conf["from"]), minutes(conf["to"])
    env = {}
    if start <= end:
        # the middle of the night period becomes midnight on wlsunset's clock
        shift = -((start + end) // 2)
        start, end = (start + shift) % 1440, (end + shift) % 1440
        env["TZ"] = _posix_tz((now.tm_gmtoff or 0) + shift * 60)
    return base + ["-S", hhmm(end), "-s", hhmm(start), "-d", str(RAMP_SECONDS)], env


def available():
    return shutil.which("wlsunset") is not None


def _uid():
    return str(os.getuid())


def running():
    try:
        r = subprocess.run(["pgrep", "-x", "-u", _uid(), "wlsunset"],
                           capture_output=True, text=True, timeout=3)
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def stop():
    """End our wlsunset and wait for it: Hyprland gives each display's gamma
    to one program at a time, a new one started too early would be refused."""
    try:
        subprocess.run(["pkill", "-x", "-u", _uid(), "wlsunset"],
                       capture_output=True, timeout=3)
    except (OSError, subprocess.SubprocessError):
        return
    for _ in range(30):
        if not running():
            time.sleep(0.1)       # the compositor drops the old gamma control
            return
        time.sleep(0.05)
    try:
        subprocess.run(["pkill", "-KILL", "-x", "-u", _uid(), "wlsunset"],
                       capture_output=True, timeout=3)
    except (OSError, subprocess.SubprocessError):
        pass
    time.sleep(0.15)


def _start(argv, env):
    if not os.environ.get("WAYLAND_DISPLAY") or not available():
        return False
    try:
        subprocess.Popen(argv, start_new_session=True, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         env=dict(os.environ, **env))
        return True
    except OSError:
        return False


def apply(conf=None):
    """Make the screen follow the settings: one wlsunset, or none when off."""
    conf = conf or load()
    stop()
    if not conf["enabled"]:
        return True
    argv, env = command(conf)
    return _start(argv, env)


def preview(temperature):
    """Show a temperature right away (Settings slider), without saving it.
    `apply()` goes back to the saved settings."""
    stop()
    argv, env = command(load(), temperature=temperature)
    return _start(argv, env)


def status(conf=None):
    conf = conf or load()
    now = time.localtime()
    win = window(conf, now)
    night = conf["enabled"] and is_night(win, now)
    out = {"enabled": conf["enabled"], "schedule": conf["schedule"],
           "mode": conf["schedule"] if conf["enabled"] else "off",
           "temperature": conf["temperature"], "from": conf["from"], "to": conf["to"],
           "active": night, "available": available(), "located": win.get("located", True),
           "running": running()}
    if win["kind"] == "window":
        out["night_from"], out["night_to"] = hhmm(win["from"]), hhmm(win["to"])
    loc = location(conf) if conf["schedule"] == "sunset" else None
    if loc:
        out["latitude"], out["longitude"] = round(loc[0], 2), round(loc[1], 2)
    return out
