#!/usr/bin/python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Offline tests for the minimized-windows state (usr/lib/zeta/system/windows.py):
a fake hyprctl stands in for Hyprland.

    python3 tools/tests/test-windows-state.py

Checks that a window hidden in a special workspace that the state file does
not know (zeta-minimize crashed, state file lost) is adopted and offered
again, that a busy Hyprland does not make the list forget windows, and that
an adopted window is restored to the workspace on screen.
"""
import json
import os
import sys
import tempfile

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..",
                    "live-build", "config", "includes.chroot", "usr", "lib", "zeta")
sys.path.insert(0, os.path.normpath(ROOT))

from system import windows  # noqa: E402

failed = 0


def check(name, cond, detail=""):
    global failed
    if not cond:
        failed += 1
        print("FAIL", name, detail)


tmp = tempfile.mkdtemp()
windows.STATE = os.path.join(tmp, "windows.json")
windows.PREVIEWS = os.path.join(tmp, "minimized")
windows._notify_bar = lambda: None
placeholders = []
windows.compose_preview = lambda src, dest, cls="": placeholders.append(dest)

CLIENTS = []
ANSWER = {"up": True}
DISPATCHED = []


def fake_hyprctl(args, as_json=False):
    if not ANSWER["up"]:
        return None
    if args == ["clients"]:
        return json.loads(json.dumps(CLIENTS))
    if args == ["activeworkspace"]:
        return {"id": 2, "name": "2"}
    if args[:1] == ["dispatch"]:
        DISPATCHED.append(args[1])
        # apply workspace moves to the fake clients
        lua = args[1]
        if "workspace = " in lua and "window = \"address:" in lua:
            ws = lua.split('workspace = "', 1)[1].split('"', 1)[0]
            addr = lua.split('window = "address:', 1)[1].split('"', 1)[0]
            for c in CLIENTS:
                if c["address"] == addr:
                    c["workspace"] = {"name": ws}
        return "ok"
    if args[:1] == ["plugin"]:
        return ANSWER.get("plugins", "Plugin hyprbars by Vaxry")
    return ""


windows._hyprctl = fake_hyprctl

# 1. a window hidden behind our back is adopted
CLIENTS[:] = [
    {"address": "0xa", "title": "Editor", "class": "editor", "mapped": True,
     "workspace": {"name": "special:zetamin"}, "at": [0, 0], "size": [800, 600]},
    {"address": "0xb", "title": "Files", "class": "thunar", "mapped": True,
     "workspace": {"name": "1"}, "at": [0, 0], "size": [800, 600]},
    {"address": "0xc", "title": "Scratch", "class": "term", "mapped": True,
     "workspace": {"name": "special:other"}, "at": [0, 0], "size": [800, 600]},
]
got = [w["address"] for w in windows.minimized()]
check("adopted from special:zetamin", "0xa" in got, got)
check("adopted from another special workspace", "0xc" in got, got)
check("visible window not adopted", "0xb" not in got, got)
check("adopted are in the state file", set(windows._load()) == {"0xa", "0xc"}, windows._load())
check("placeholder thumbnails", len(placeholders) == 2, placeholders)
check("in bar order", [a for a, _i in windows.minimized_in_order()] == ["0xa", "0xc"])

# 2. Hyprland busy: nothing is forgotten
ANSWER["up"] = False
got = [w["address"] for w in windows.minimized()]
check("busy Hyprland keeps the list", got == ["0xa", "0xc"], got)
check("busy Hyprland keeps the state", set(windows._load()) == {"0xa", "0xc"})
ANSWER["up"] = True

# 3. an adopted window comes back to the workspace on screen
check("restore ok", windows.restore("0xa"))
check("restored to the active workspace", any('workspace = "2"' in d and "0xa" in d for d in DISPATCHED), DISPATCHED)
check("restored is out of the state", "0xa" not in windows._load())

# 4. a minimized window with a recorded workspace goes back there
CLIENTS[1]["workspace"] = {"name": "3"}
DISPATCHED.clear()
CLIENTS.append({"address": "0xd", "title": "Mail", "class": "mail", "mapped": True,
                "workspace": {"name": "3"}, "at": [100, 100], "size": [800, 600]})
check("minimize ok", windows.minimize("0xd"))
check("state records the time", "time" in windows._load().get("0xd", {}))
check("restore ok 2", windows.restore("0xd"))
check("restored to its workspace", any('workspace = "3"' in d and "0xd" in d for d in DISPATCHED), DISPATCHED)

# 5. closed windows are dropped
CLIENTS[:] = [c for c in CLIENTS if c["address"] != "0xc"]
got = [w["address"] for w in windows.minimized()]
check("closed window dropped", "0xc" not in got and "0xc" not in windows._load(), got)

# 6. title bars: flag file first, plugin list as a fallback
os.environ["XDG_RUNTIME_DIR"] = tmp
with open(os.path.join(tmp, "zeta-title-bars"), "w") as f:
    f.write("1\n")
ANSWER["plugins"] = "no plugins loaded"
check("flag 1: title bars", windows.title_bars_present() is True)
with open(os.path.join(tmp, "zeta-title-bars"), "w") as f:
    f.write("0\n")
check("flag 0, plugin not loaded: no title bars", windows.title_bars_present() is False)
ANSWER["plugins"] = "Plugin hyprbars by Vaxry"
check("flag 0, plugin loaded (reload pending): title bars", windows.title_bars_present() is True)
os.unlink(os.path.join(tmp, "zeta-title-bars"))
check("no flag: plugin list says yes", windows.title_bars_present() is True)

print("windows state: %s" % ("all passed" if not failed else "%d failed" % failed))
sys.exit(1 if failed else 0)
