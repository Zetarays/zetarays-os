# SPDX-License-Identifier: GPL-3.0-or-later
"""How the desktop icons look and behave: one file, two writers.

~/.config/zeta/desktop-look.json is written by Settings > Desktop & Icons
and by the desktop's own right-click View menu; zeta-desktop watches it and
applies every change at once, without restarting. Where each icon sits is a
different thing and stays in ~/.config/zeta/desktop.json, written only by
zeta-desktop (positions are the user's arrangement, never a preference).

Older versions kept the size, grid, side and order in desktop.json and the
spacing in ~/.config/zeta/icon-spacing: load() reads them as defaults, so an
upgraded desktop looks exactly as before until something is changed.
"""
import json
import os

CFG = os.path.expanduser("~/.config/zeta")
PATH = os.path.join(CFG, "desktop-look.json")
STATE = os.path.join(CFG, "desktop.json")

ICON_SIZES = (32, 40, 48, 56, 64, 72, 80, 96)
LABEL_SIZES = (9.0, 10.0, 11.5, 13.0, 14.5, 16.0)
LABEL_COLORS = ("auto", "light", "dark", "accent")
LABEL_EFFECTS = ("shadow", "plate", "none")
ORDERS = ("name", "type", "date", "size")

DEFAULTS = {
    "icon_size": None,        # None: the size chosen in Settings > Appearance (icon-size)
    "spacing": 14,            # pixels between cells
    "grid": True,             # Align to Grid; False = icons stay exactly where dropped
    "side": "left",           # new icons fill the desktop from the left or the right
    "direction": "columns",   # fill down the columns, or across the rows
    "order": "name",          # Sort By
    "labels": True,           # show the names
    "label_size": 11.5,       # points
    "label_lines": 2,         # lines before the name is shortened with "…"
    "label_bold": False,
    "label_color": "auto",    # auto (theme), light, dark, accent
    "label_effect": "shadow",  # shadow (halo), plate (dark band behind), none
    "click": "double",        # double or single click opens
}


def _legacy():
    """Values of older versions, used where the new file has none."""
    out = {}
    try:
        with open(STATE, encoding="utf-8") as f:
            st = json.load(f)
        if isinstance(st, dict):
            if isinstance(st.get("icon_size"), int):
                out["icon_size"] = st["icon_size"]
            if st.get("grid") is False:
                out["grid"] = False
            if st.get("side") in ("left", "right"):
                out["side"] = st["side"]
            if st.get("order") in ORDERS:
                out["order"] = st["order"]
    except (OSError, ValueError):
        pass
    try:
        with open(os.path.join(CFG, "icon-spacing"), encoding="utf-8") as f:
            out["spacing"] = int(f.read().strip())
    except (OSError, ValueError):
        pass
    return out


def clean(d):
    """Only known keys, each one valid; anything else falls back to default."""
    out = dict(DEFAULTS)
    if not isinstance(d, dict):
        return out
    v = d.get("icon_size")
    if v is None or (isinstance(v, int) and 24 <= v <= 128):
        out["icon_size"] = v
    v = d.get("spacing")
    if isinstance(v, int) and 0 <= v <= 64:
        out["spacing"] = v
    for key in ("grid", "labels", "label_bold"):
        if isinstance(d.get(key), bool):
            out[key] = d[key]
    for key, allowed in (("side", ("left", "right")), ("direction", ("columns", "rows")),
                         ("order", ORDERS), ("label_color", LABEL_COLORS),
                         ("label_effect", LABEL_EFFECTS), ("click", ("double", "single"))):
        if d.get(key) in allowed:
            out[key] = d[key]
    v = d.get("label_size")
    if isinstance(v, (int, float)) and 8 <= v <= 20:
        out["label_size"] = float(v)
    v = d.get("label_lines")
    if isinstance(v, int) and 1 <= v <= 4:
        out["label_lines"] = v
    return out


def load():
    merged = _legacy()
    try:
        with open(PATH, encoding="utf-8") as f:
            saved = json.load(f)
        if isinstance(saved, dict):
            merged.update(saved)
    except (OSError, ValueError):
        pass
    return clean(merged)


def save(look):
    """Atomic write; returns True when the file changed."""
    look = clean(look)
    text = json.dumps(look, indent=2, sort_keys=True) + "\n"
    try:
        with open(PATH, encoding="utf-8") as f:
            if f.read() == text:
                return False
    except OSError:
        pass
    os.makedirs(CFG, exist_ok=True)
    tmp = PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, PATH)
    return True


def update(**changes):
    look = load()
    look.update(changes)
    return save(look)


def reset():
    """Every look setting back to default; where the icons sit is kept."""
    return save(dict(DEFAULTS))
