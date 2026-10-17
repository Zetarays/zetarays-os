# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA RAYS — customizable dock.

The dock is not fixed: the user chooses which applications to show (from
Settings › Dock). The choice is saved in ~/.config/zeta/dock.json and from it
the Waybar configuration (~/.config/waybar/config.jsonc) is regenerated and
hot-reloaded. If something goes wrong, the existing bar stays intact: a
broken file is never generated.
"""
from __future__ import annotations

import json
import locale
import shlex
import os
import signal
import subprocess
import sys
from pathlib import Path

if "/usr/lib/zeta" not in sys.path:
    sys.path.insert(0, "/usr/lib/zeta")
from i18n import tr  # noqa: E402

HOME = Path(os.path.expanduser("~"))
CFG = HOME / ".config" / "zeta"
DOCK_FILE = CFG / "dock.json"
WAYBAR = HOME / ".config" / "waybar" / "config.jsonc"

DOCK_SIGNAL = 12        # SIGRTMIN+12: windows opened/closed (sent by zeta-workspaces)

# Default dock: quick access to the system's main functions.
DEFAULT = [
    {"cmd": "thunar",             "name": tr("Files"),     "icon": "org.xfce.thunar"},
    {"cmd": "foot",               "name": tr("Terminal"),  "icon": "foot"},
    {"cmd": "firefox-esr",        "name": "Firefox",       "icon": "firefox-esr"},
    # Mail (Thunderbird): tooltip, a dot while it is open, "New Message" in
    # the menu. The dock asks for the state only when a window opens or closes
    # (signal from zeta-workspaces): no periodic polling.
    {"cmd": "zeta-mail",         "name": tr("Mail"),      "icon": "zeta-mail",
     "status": "zeta-mail status", "actions": [[tr("New Message"), "zeta-mail new"]]},
    {"cmd": "gnome-text-editor",  "name": tr("Editor"),    "icon": "org.gnome.TextEditor"},
    {"cmd": "zeta-monitor",       "name": tr("Monitor"),   "icon": "zeta-monitor"},
    {"cmd": "zeta-security",     "name": tr("Security"),  "icon": "zeta-security"},
    {"cmd": "synaptic-pkexec",    "name": tr("Packages"),  "icon": "synaptic"},
    {"cmd": "zeta-settings",  "name": tr("Settings"),  "icon": "zeta-settings"},
]


def _app_registry():
    import sys
    if "/usr/lib/zeta" not in sys.path:
        sys.path.insert(0, "/usr/lib/zeta")
    from system import applications
    return applications


def resolve_icon(name: str) -> str:
    """Icon name -> file path: the same result as the app menu (ZETA RAYS
    theme, Adwaita, hicolor in every size, Flatpak and home-directory apps,
    pixmaps). Previously only three folders were checked here, and apps whose
    icon existed only as PNG (48x48, 256x256...) got the generic one in the
    Dock."""
    return _app_registry().icon_file(name)


def installed_apps() -> list[dict]:
    """Applications offered for the Dock: the same as in the menu."""
    return [{"id": a.id, "name": a.name, "icon": a.icon, "exec": a.command}
            for a in _app_registry().menu()]


def entry_from_app(app) -> dict:
    """Dock entry for an app from the registry: it launches as from the menu
    (zeta-app launch), and the id avoids duplicates and is used to remove it."""
    return {"app": app.id, "cmd": "zeta-app launch %s" % shlex.quote(app.id),
            "name": app.name, "icon": app.icon}


def load_dock() -> list[dict]:
    try:
        with open(DOCK_FILE) as f:
            data = json.load(f)
        if isinstance(data, list) and data:
            entries = [e for e in data if isinstance(e, dict) and e.get("cmd")]
            for e in entries:
                # docks saved by the earlier 1.7: Mail's own menu became an
                # entry of the shared menu
                if e.pop("menu", None) == "zeta-mail menu":
                    e.setdefault("actions", [[tr("New Message"), "zeta-mail new"]])
            return entries
    except (OSError, ValueError):
        pass
    return list(DEFAULT)


def save_dock(entries: list[dict]) -> None:
    CFG.mkdir(parents=True, exist_ok=True)
    tmp = DOCK_FILE.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(entries, f, indent=2, ensure_ascii=False)
    tmp.replace(DOCK_FILE)


def entry_from_desktop(app: dict) -> dict:
    """Turn an app from installed_apps() into a dock entry."""
    a = _app_registry().find(app.get("id", ""))
    if a is not None:
        return entry_from_app(a)
    return {"cmd": app["exec"], "name": app["name"], "icon": app.get("icon", "")}


def present() -> set:
    """Ids of the apps already in the Dock (including old entries without an id)."""
    reg = _app_registry()
    ids = set()
    for e in load_dock():
        if e.get("app"):
            ids.add(e["app"])
        else:
            a = reg.from_command(e.get("cmd", ""))
            if a is not None:
                ids.add(a.id)
    return ids


def position() -> str:
    """Bar at the bottom or at the top (Settings › Dock)."""
    try:
        v = (CFG / "dock-position").read_text().strip()
    except OSError:
        return "bottom"
    return v if v in ("bottom", "top") else "bottom"


def bar_icon(name: str, fallback: str) -> str:
    """Bar icon recolored for the theme (generated by zeta-accent)."""
    p = CFG / "bar" / name
    return str(p) if p.exists() else fallback


def icon_size() -> int:
    """Dock icon size chosen in Settings > Appearance."""
    try:
        v = int((CFG / "icon-size").read_text().strip())
    except (OSError, ValueError):
        return 42
    return v if 28 <= v <= 64 else 42


def _clock_locale() -> str:
    """Language of the bar clock: the user's (LC_ALL, LC_TIME, LANG), if it
    is actually installed. Waybar cannot use a missing locale (the clock
    would disappear): in that case C.UTF-8."""
    loc = ""
    for var in ("LC_ALL", "LC_TIME", "LANG"):
        loc = os.environ.get(var, "")
        if loc:
            break
    if not loc or loc in ("C", "POSIX"):
        return "C.UTF-8"
    try:
        previous = locale.setlocale(locale.LC_TIME)
    except locale.Error:
        return "C.UTF-8"
    try:
        locale.setlocale(locale.LC_TIME, loc)
        return loc
    except locale.Error:
        return "C.UTF-8"
    finally:
        try:
            locale.setlocale(locale.LC_TIME, previous)
        except locale.Error:
            pass


def render_config(dock: list[dict]) -> dict:
    """Full Waybar configuration with the requested dock."""
    dock_modules = []
    images = {}
    size = icon_size()
    reg = _app_registry()
    # Date formats (strftime) for the clock: the order of day and month
    # changes from language to language, so they go through translations.
    # xgettext:no-python-format
    short_date = tr("%a %b %d")              # below the time, in the bar
    # xgettext:no-python-format
    long_date = tr("%A, %B %d, %Y")         # tooltip above the calendar
    for i, e in enumerate(dock):
        key = "image#dock%d" % i
        dock_modules.append(key)
        # the icon comes from the app registry: if the app changes it (an
        # update, or "Change icon…") the Dock follows
        icon = e.get("icon", "")
        app = reg.find(e["app"]) if e.get("app") else reg.from_command(e.get("cmd", ""))
        if app is not None and (e.get("app") or app.custom_icon) and app.icon:
            icon = app.icon
        images[key] = {
            "path": resolve_icon(icon),
            "size": size, "tooltip": False,
            "on-click": e["cmd"],
        }
        if e.get("status"):
            # icon and tooltip come from a short command, rerun on the
            # SIGRTMIN+12 signal (windows opened or closed); the long
            # interval is only a safety net
            del images[key]["path"]
            images[key].update({"exec": e["status"], "signal": DOCK_SIGNAL,
                                "interval": 300, "tooltip": True})
        # right click: the same menu for every icon (Open, Close if open,
        # Remove from Dock, Options, App settings)
        images[key]["on-click-right"] = "zeta-dock menu %d" % i

    cfg = {
        "layer": "top", "position": position(), "height": max(60, size + 18),
        "margin-left": 12, "margin-right": 12, "spacing": 0,
        ("margin-bottom" if position() == "bottom" else "margin-top"): 12,
        "modules-left": ["image#launcher", "group/workspaces"],
        "modules-center": ["group/dock", "group/minimized"],
        "modules-right": ["custom/windowlist", "custom/keyboard", "image#search", "image#net",
                          "image#vol", "image#bat", "clock", "image#power"],
        # Windows list button, only when the windows have no title bars
        # (hyprbars not loaded): then it is the mouse way to reach, close and
        # minimize every window. Otherwise zeta-windows prints nothing and
        # Waybar hides the module.
        "custom/windowlist": {
            "exec": "zeta-windows button", "interval": 30, "signal": 9,
            "on-click": "zeta-windows", "tooltip": False,
        },
        # Current keyboard (IT, US, GB...), only with more than one layout
        # (with a single one zeta-keyboard prints nothing and Waybar hides
        # it). A click switches to the next one, like Alt+Shift; zeta-workspaces
        # updates it on change.
        "custom/keyboard": {
            "exec": "zeta-keyboard status", "return-type": "json",
            "interval": 300, "signal": 14,
            "on-click": "zeta-keyboard next", "tooltip": True,
        },
        "image#launcher": {
            "exec": "echo $HOME/.config/zeta/launcher.svg",
            # The logo is the bar's identity element. It is a thin-line
            # drawing: at 20 it vanished, and even at 34 the lines dropped to
            # about one pixel and antialiasing washed them out. At 42 it is as
            # tall as the dock tiles and the lines stay sharp.
            "size": 42, "signal": 8, "tooltip": False, "on-click": "zeta-panel launcher",
        },
        # Minimized windows: one thumbnail per window next to the dock, as on
        # macOS (zeta-minimize takes a snapshot before hiding it). A slot with
        # no window has no image and Waybar does not show it. Updated at once
        # by zeta-minimize and zeta-workspaces (SIGRTMIN+9).
        "group/minimized": {"orientation": "horizontal",
                            "modules": ["image#minimized%d" % n for n in range(8)]},
        **{"image#minimized%d" % n: {
            "exec": "zeta-windows preview %d" % n, "signal": 9, "interval": 300,
            "size": int(size * 1.6), "tooltip": True,
            "on-click": "zeta-minimize restore-n %d" % n,
            "on-click-right": "zeta-minimize menu %d" % n,
            "on-click-middle": "zeta-windows close-n %d" % n,
        } for n in range(8)},
        "image#search": {
            "path": bar_icon("search.svg", "/usr/share/zeta/status/search.svg"),
            "size": 18, "tooltip": False, "on-click": "zeta-panel search",
        },
        # Workspaces: "hyprland/workspaces" is not used because, to switch to
        # one, it sends Hyprland the legacy syntax, which the Lua
        # configuration of Hyprland 0.55 rejects — clicking a number in the
        # bar did nothing. zeta-workspaces listens to Hyprland's events (no
        # continuous polling) and uses the correct syntax.
        "group/workspaces": {
            "orientation": "horizontal",
            "modules": ["custom/workspace%d" % n for n in (1, 2, 3)],
        },
        # Short commands that exit on their own, refreshed by the signal sent
        # by "zeta-workspaces listen". A module that stays running would be left
        # behind as a zombie process on every bar reload.
        **{"custom/workspace%d" % n: {
            "exec": "zeta-workspaces status %d" % n, "return-type": "json",
            "interval": 120, "signal": 10,
            "on-click": "zeta-workspaces go %d" % n, "tooltip": False,
        } for n in (1, 2, 3)},
        "group/dock": {"orientation": "horizontal", "modules": dock_modules},
        # the network: updated by NetworkManager when it changes (SIGRTMIN+13,
        # /etc/NetworkManager/dispatcher.d/90-zeta-bar); the long interval
        # is only a safety net
        "image#net": {"exec": "zeta-status net", "interval": 60, "signal": 13, "size": 18,
                      "tooltip": False, "on-click": "zeta-panel network"},
        # The volume is updated through a signal (zeta-volume sends it as soon
        # as it changes), not by rereading the state every 2 seconds: the
        # periodic read remains only as a safety net.
        "image#vol": {"exec": "zeta-status vol", "interval": 60, "signal": 11,
                      "size": 18,
                      "tooltip": False, "on-click": "zeta-panel audio",
                      "on-scroll-up": "zeta-volume up",
                      "on-scroll-down": "zeta-volume down"},
        "image#bat": {"exec": "zeta-status bat", "interval": 60, "size": 20,
                      "tooltip": False, "on-click": "zeta-panel control"},
        "image#power": {"path": bar_icon("power.svg", "/usr/share/zeta/status/power.svg"),
                        "size": 18,
                        "tooltip": False, "on-click": "zeta-panel power"},
        "clock": {
            "format": "<span weight='500'>{0:%H:%M}</span>\n<span size='8.5pt' foreground='#8A8A8E'>{0:L"
                      + short_date + "}</span>",
            "locale": _clock_locale(), "justify": "right",
            "tooltip-format": "<span size='11pt'>{0:L" + long_date
                              + "}</span>\n\n<tt>{calendar}</tt>",
            "calendar": {"mode": "month", "weeks-pos": "",
                         "format": {"months": "<span color='#EDEDEA'><b>{}</b></span>",
                                    "weekdays": "<span color='#8A8A8E'>{}</span>",
                                    "today": "<span color='#3A8DFF'><b>{}</b></span>"}},
            "on-click": "zeta-panel control",
        },
    }
    cfg.update(images)
    return cfg


def reload_waybar() -> None:
    """Hot-reload Waybar through zeta-bar: one reload at a time, then a
    check that only one bar is left (back-to-back SIGUSR2 reloads sometimes
    duplicated it). Does not wait: returns immediately."""
    try:
        subprocess.Popen(["zeta-bar", "reload"], stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError:
        try:   # zeta-bar missing (old system): reload directly
            out = subprocess.run(["pgrep", "-x", "waybar"], capture_output=True, text=True)
            for pid in out.stdout.split()[:1]:
                os.kill(int(pid), signal.SIGUSR2)
        except (OSError, ValueError, subprocess.SubprocessError):
            pass


def apply_if_changed() -> bool:
    """Regenerate the bar only if the result differs from the current one
    (changed icons, removed apps): no needless Waybar reloads."""
    try:
        current = WAYBAR.read_text()
        current = json.loads(current[current.index("{"):])
    except (OSError, ValueError):
        current = None
    if current == json.loads(json.dumps(render_config(load_dock()))):
        return False
    return apply()


def apply(dock: list[dict] | None = None, reload: bool = True) -> bool:
    """Generate config.jsonc from the dock (or from dock.json) and reload Waybar.

    With reload=False the bar is not touched: for callers that reload only
    once at the end (two back-to-back reloads crash Waybar)."""
    if dock is None:
        dock = load_dock()
    cfg = render_config(dock)
    WAYBAR.parent.mkdir(parents=True, exist_ok=True)
    tmp = WAYBAR.with_suffix(".tmp")
    header = ("// ZETA RAYS — bottom bar with dock (generated by zeta-dock;\n"
              "// customize it in Settings › Dock, do not edit by hand)\n")
    try:
        with open(tmp, "w") as f:
            f.write(header)
            json.dump(cfg, f, indent=2, ensure_ascii=False)
            f.write("\n")
        tmp.replace(WAYBAR)
    except OSError:
        return False
    if reload:
        reload_waybar()
    return True
