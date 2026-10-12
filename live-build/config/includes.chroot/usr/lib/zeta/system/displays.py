# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA RAYS — displays (monitors): reading, safe applying and memory.

Logic only, no UI (the page is ui/displays_page.py).

- The real state comes from Hyprland: "hyprctl -j monitors all" (including
  disabled displays), with the resolutions and refresh rates each display
  advertises.
- Changes are applied through Hyprland rules (hl.monitor, "hyprctl eval"),
  never through a shell: the values come only from this module and are
  validated.
- After applying, the state is read back and compared with what was requested.
- Memory is per display, not per position in the list: the key is
  make + model + serial number (Hyprland's "desc:" selector), so the same
  monitor gets its settings back even on a different port.
  Displays without this data (virtual machines) use the port name.
- Saved to ~/.config/zeta/displays.json and translated into
  ~/.config/hypr/zeta_displays.lua, which hyprland.lua reads at startup.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time

CFG = os.path.expanduser("~/.config/zeta")
MEMORY_FILE = os.path.join(CFG, "displays.json")
LUA = os.path.expanduser("~/.config/hypr/zeta_displays.lua")

# Hyprland: 0 normal, 1 90°, 2 180°, 3 270° (4-7 are the same, flipped)
ROTATIONS = (0, 1, 2, 3)
# offered scales; only those that divide the resolution exactly are kept
# (Hyprland rejects the others and picks a different one by itself)
SCALE = (1.0, 1.25, 1.5, 1.6, 1.75, 2.0, 2.5, 3.0)
INTERNAL_PREFIXES = ("eDP", "LVDS", "DSI")
_MODE_RE = re.compile(r"^(\d+)x(\d+)@([\d.]+)Hz$")
_SAFE = re.compile(r"^[A-Za-z0-9 _.,:()/+-]*$")


# ------------------------------------------------------------------ reading
def _hyprctl_json(*arguments):
    try:
        r = subprocess.run(["hyprctl", "-j", *arguments], capture_output=True,
                           text=True, timeout=5)
        return json.loads(r.stdout or "null")
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None


def _description(m: dict) -> str:
    # the way Hyprland builds the short description (m_shortDescription), which
    # is also what Lua reads at startup: the two must match exactly
    return ("%s %s %s" % (m.get("make", ""), m.get("model", ""), m.get("serial", ""))).strip()


def identity(m: dict) -> str:
    """The display's stable name: make model serial, or else the port."""
    return _description(m) or m.get("name", "")


def selector(m: dict) -> str:
    desc = _description(m)
    return ("desc:" + desc) if desc else m.get("name", "")


def read() -> list[dict]:
    """The connected displays, enabled and disabled, with the data we need."""
    data = _hyprctl_json("monitors", "all") or []
    out = []
    for m in data:
        modes = []
        for s in m.get("availableModes", []):
            g = _MODE_RE.match(s)
            if g:
                modes.append((int(g.group(1)), int(g.group(2)), float(g.group(3))))
        mirror = m.get("mirrorOf") or "none"
        out.append({
            "name": m.get("name", ""),
            "identity": identity(m),
            "selector": selector(m),
            "make": m.get("make", ""), "model": m.get("model", ""),
            "serial": m.get("serial", ""), "description": m.get("description", ""),
            "width": int(m.get("width", 0)), "height": int(m.get("height", 0)),
            "refresh": float(m.get("refreshRate", 0.0)),
            "x": int(m.get("x", 0)), "y": int(m.get("y", 0)),
            "scale": float(m.get("scale", 1.0)),
            "rotation": int(m.get("transform", 0)),
            "enabled": not m.get("disabled", False),
            "mirror": None if mirror in ("none", "", None) else str(mirror),
            "modes": modes,
            "mm": (int(m.get("physicalWidth", 0)), int(m.get("physicalHeight", 0))),
            "focused": bool(m.get("focused")),
            "internal": m.get("name", "").startswith(INTERNAL_PREFIXES),
            "vrr": bool(m.get("vrr")),
            "id": int(m.get("id", -1)),
        })
    # Hyprland refers to the mirrored display by its id: we need the name
    per_id = {str(m["id"]): m["name"] for m in out}
    for m in out:
        if m["mirror"] is not None:
            m["mirror"] = per_id.get(m["mirror"], m["mirror"])
    return out


# ------------------------------------------------------------- calculations
def exact(w: int, h: int, s: float) -> bool:
    return abs(w / s - round(w / s)) < 1e-6 and abs(h / s - round(h / s)) < 1e-6


# below this logical area the bar and windows no longer fit (tested:
# 1280x800 at 160% = 800x500 and the bar runs off the screen)
MIN_AREA = (1024, 600)


def valid_scales(w: int, h: int, current: float | None = None) -> list[float]:
    """The scales Hyprland accepts for this resolution that leave a usable
    desktop; 100% and the current scale are always included."""
    v = [s for s in SCALE if exact(w, h, s) and
         (s == 1.0 or (max(w, h) / s >= MIN_AREA[0] and min(w, h) / s >= MIN_AREA[1]))]
    if current and all(abs(current - s) > 1e-3 for s in v):
        v.append(round(current, 3))
    return sorted(v)


def resolutions(m: dict) -> list[tuple[int, int]]:
    """Distinct resolutions, largest first; the first one in Hyprland's list
    is the one the display prefers (the native one)."""
    seen, out = set(), []
    for w, h, _hz in m["modes"]:
        if (w, h) not in seen:
            seen.add((w, h))
            out.append((w, h))
    native_resolution = out[0] if out else None
    rest = sorted((r for r in out if r != native_resolution), key=lambda r: r[0] * r[1], reverse=True)
    return ([native_resolution] if native_resolution else []) + rest


def native_resolution(m: dict) -> tuple[int, int] | None:
    r = resolutions(m)
    return r[0] if r else None


def refresh_rates(m: dict, w: int, h: int) -> list[float]:
    return sorted({round(hz, 2) for mw, mh, hz in m["modes"] if (mw, mh) == (w, h)}, reverse=True)


def logical_size(c: dict) -> tuple[int, int]:
    """Width and height on the virtual screen (after scale and rotation)."""
    w, h = c["width"] / c["scale"], c["height"] / c["scale"]
    if c["rotation"] % 2 == 1:
        w, h = h, w
    return round(w), round(h)


def inches(m: dict) -> float | None:
    pw, ph = m["mm"]
    if pw <= 0 or ph <= 0:
        return None
    return round(((pw ** 2 + ph ** 2) ** 0.5) / 25.4, 1)


# -------------------------------------------------------- configuration
def configuration(displays: list[dict]) -> dict:
    """{name: settings} from the current state (to be edited and applied)."""
    out = {}
    for m in displays:
        out[m["name"]] = {
            "selector": m["selector"], "identity": m["identity"],
            "width": m["width"], "height": m["height"],
            "refresh": round(m["refresh"], 2), "x": m["x"], "y": m["y"],
            "scale": m["scale"], "rotation": m["rotation"],
            "enabled": m["enabled"], "mirror": m["mirror"],
        }
    return out


def check(conf: dict) -> str | None:
    """An error code, or None if the configuration can be applied."""
    names = set(conf)
    enabled_outputs = [n for n, c in conf.items() if c["enabled"] and not c["mirror"]]
    if not enabled_outputs:
        return "at-least-one"            # never all disabled or all mirrored
    for n, c in conf.items():
        if c["mirror"]:
            if c["mirror"] == n or c["mirror"] not in names:
                return "mirror-invalid"
            if conf[c["mirror"]]["mirror"] or not conf[c["mirror"]]["enabled"]:
                return "mirror-invalid"
        if c["rotation"] not in ROTATIONS:
            return "invalid"
        if c["width"] <= 0 or c["height"] <= 0 or c["scale"] <= 0:
            return "invalid"
        if not _SAFE.match(c["selector"]):
            return "invalid"
    return None


def _lua_line(c: dict, mirror_name: str | None) -> str:
    sel = json.dumps(c["selector"])
    if not c["enabled"]:
        return "hl.monitor({ output = %s, disabled = true })" % sel
    mode = "%dx%d@%.2f" % (c["width"], c["height"], c["refresh"])
    fields = ["output = %s" % sel, "disabled = false", "mode = %s" % json.dumps(mode),
             "position = %s" % json.dumps("%dx%d" % (c["x"], c["y"])),
             "scale = %s" % json.dumps("%g" % c["scale"]),
             "transform = %d" % c["rotation"]]
    fields.append("mirror = %s" % json.dumps(mirror_name or ""))
    return "hl.monitor({ %s })" % ", ".join(fields)


def lua_lines(conf: dict, primary: str | None = None, for_startup: bool = False) -> list[str]:
    """The Hyprland rules for the configuration. For mirroring, Hyprland
    wants the port name of the mirrored display."""
    lines = [_lua_line(c, c["mirror"]) for c in conf.values()]
    if primary and primary in conf:
        sel = conf[primary]["selector"]
        # the primary display: the one hosting the first workspace
        lines.append("hl.workspace_rule({ workspace = \"1\", monitor = %s, default = true })"
                     % json.dumps(sel))
    return lines


def _eval(code: str) -> tuple[bool, str]:
    try:
        r = subprocess.run(["hyprctl", "eval", code], capture_output=True, text=True, timeout=8)
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, str(e)
    output = (r.stdout or "").strip()
    return (r.returncode == 0 and output.startswith("ok")), output


def apply(conf: dict, primary: str | None = None) -> tuple[bool, str]:
    """Apply immediately (without saving). (ok, error)"""
    error = check(conf)
    if error:
        return False, error
    ok, msg = _eval("\n".join(lua_lines(conf, primary)))
    if not ok:
        return False, msg or "hyprctl"
    # after a display change, keep the windows inside the usable area
    _eval("if zeta_recover then zeta_recover() end")
    return True, ""


def verify(conf: dict, wait: float = 4.0) -> tuple[bool, list[str]]:
    """Re-read the real state until it matches the requested one (or the
    wait runs out). (ok, differences)"""
    deadline = time.monotonic() + wait
    while True:
        diff = _differences(conf, {m["name"]: m for m in read()})
        if not diff or time.monotonic() > deadline:
            if not diff:
                realign_layers(conf)
            return not diff, diff
        time.sleep(0.25)


def realign_layers(conf: dict) -> None:
    """Put the bar, desktop and wallpaper back in place after a move.

    Hyprland (0.55) arranges a display's layers (layer-shell) while it
    applies the rules one display at a time: if the position then changes
    again, they stay where they were (tested: the bar ended up shifted by
    106 px and cut off). Hyprland recomputes them when only a display's
    reserved area changes, without touching the video mode: so we set it to
    1 and back to 0, one frame after the other."""
    enabled_outputs = [c["selector"] for c in conf.values() if c["enabled"] and not c["mirror"]]
    for value in (1, 0):
        _eval("\n".join("hl.monitor({ output = %s, reserved = %d })" % (json.dumps(sel), value)
                         for sel in enabled_outputs))
        time.sleep(0.15)


def _differences(conf: dict, actual: dict) -> list[str]:
    diff = []
    for n, c in conf.items():
        m = actual.get(n)
        if m is None:
            diff.append("%s: missing" % n)
            continue
        if c["enabled"] != m["enabled"]:
            diff.append("%s: enabled" % n)
            continue
        if not c["enabled"]:
            continue
        if (c["mirror"] or None) != (m["mirror"] or None):
            diff.append("%s: mirror" % n)
            continue
        if c["mirror"]:
            continue
        if (c["width"], c["height"]) != (m["width"], m["height"]):
            diff.append("%s: resolution" % n)
        if abs(c["refresh"] - m["refresh"]) > 0.6:
            diff.append("%s: refresh" % n)
        if abs(c["scale"] - m["scale"]) > 0.01:
            diff.append("%s: scale" % n)
        if c["rotation"] != m["rotation"]:
            diff.append("%s: rotation" % n)
        if (c["x"], c["y"]) != (m["x"], m["y"]):
            diff.append("%s: position" % n)
    return diff


# ------------------------------------------------------------------- memory
def load_memory() -> dict:
    try:
        with open(MEMORY_FILE) as f:
            d = json.load(f)
        if isinstance(d, dict):
            d.setdefault("displays", {})
            return d
    except (OSError, ValueError):
        pass
    return {"displays": {}, "primary": None}


def save(conf: dict, primary: str | None = None) -> None:
    """Remember each display's configuration by identity and write the rules
    Hyprland reads at startup. Displays that are not connected right now
    stay remembered."""
    mem = load_memory()
    for n, c in conf.items():
        entry = {k: c[k] for k in ("width", "height", "refresh", "x", "y", "scale",
                                  "rotation", "enabled", "selector")}
        # the mirror is remembered by the identity of the mirrored display
        entry["mirror"] = conf[c["mirror"]]["identity"] if c["mirror"] in conf else None
        mem["displays"][c["identity"]] = entry
    if primary in conf:
        mem["primary"] = conf[primary]["identity"]
    os.makedirs(CFG, exist_ok=True)
    tmp = MEMORY_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(mem, f, indent=2)
    os.replace(tmp, MEMORY_FILE)
    write_lua(mem)


def write_lua(mem: dict) -> None:
    """~/.config/hypr/zeta_displays.lua: a function hyprland.lua calls after
    the generic rule. Mirroring uses the port name, which at startup is known
    only for the displays present: it is resolved in Lua."""
    lines = ["-- ZETA RAYS — generated by Settings › Displays (system/displays.py).",
             "-- One rule per display, identified by make, model and serial number.",
             "return function()",
             "    local ports = {}",
             "    for _, m in ipairs(hl.get_monitors()) do",
             "        local d = ((m.description or \"\") ~= \"\") and m.description or m.name",
             "        ports[d] = m.name",
             "    end"]
    for ident, c in sorted(mem.get("displays", {}).items()):
        if not _SAFE.match(ident) or not _SAFE.match(c.get("selector", "")):
            continue
        sel = json.dumps(c["selector"])
        if not c.get("enabled", True):
            lines.append("    hl.monitor({ output = %s, disabled = true })" % sel)
            continue
        if c.get("mirror") and _SAFE.match(c["mirror"]):
            lines.append("    if ports[%s] then hl.monitor({ output = %s, disabled = false, mirror = ports[%s] }) end"
                         % (json.dumps(c["mirror"]), sel, json.dumps(c["mirror"])))
            continue
        mode = "%dx%d@%.2f" % (c["width"], c["height"], c["refresh"])
        lines.append("    hl.monitor({ output = %s, disabled = false, mode = %s, position = %s, "
                     "scale = %s, transform = %d })"
                     % (sel, json.dumps(mode), json.dumps("%dx%d" % (c["x"], c["y"])),
                        json.dumps("%g" % c["scale"]), int(c["rotation"])))
    p = mem.get("primary")
    if p and p in mem.get("displays", {}) and _SAFE.match(p):
        lines.append("    hl.workspace_rule({ workspace = \"1\", monitor = %s, default = true })"
                     % json.dumps(mem["displays"][p]["selector"]))
    lines.append("end")
    os.makedirs(os.path.dirname(LUA), exist_ok=True)
    tmp = LUA + ".tmp"
    with open(tmp, "w") as f:
        f.write("\n".join(lines) + "\n")
    os.replace(tmp, LUA)


def saved_main(displays: list[dict]) -> str | None:
    p = load_memory().get("primary")
    for m in displays:
        if m["identity"] == p:
            return m["name"]
    return None
