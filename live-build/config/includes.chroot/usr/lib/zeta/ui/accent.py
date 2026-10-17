# SPDX-License-Identifier: GPL-3.0-or-later
"""The system accent color, in a single place.

Anything that draws with the color chosen by the user asks for it here,
instead of keeping its own palette. The ZETA orb used to have four colors of
its own, saved in a separate file and switched with keys: it was a second
theming system living alongside the real one, and changing the accent in
Settings was enough for the two to stop matching.

    from ui.accent import color_rgb, follow
"""
from __future__ import annotations

import os

# The *rendered* color: the one chosen by the user, already adapted to the
# current theme (white on a light theme becomes a readable gray). If it is
# missing we fall back to the raw choice, and finally to ZETA RAYS blue.
CFG = os.path.expanduser("~/.config/zeta")
RENDERED = os.path.join(CFG, "accent-rendered")
CHOSEN_FILE = os.path.join(CFG, "accent")
DEFAULT = "#3A8DFF"

# The ZETA RAYS accent colors: the system's only palette. It is used by
# Settings › Appearance, the account picture colors and spoken or typed
# commands ("set the red one", in any language). (key, color, English name to translate)
PALETTE = (
    ("blue", "#3A8DFF", "Blue"),
    ("red", "#C8102E", "Red"),
    ("green", "#4CC94A", "Green"),
    ("white", "#FFFFFF", "White"),
)


def color_name(key: str) -> str:
    """The translated color name (the strings are spelled out here so that
    tools/i18n.py can find them)."""
    from i18n import tr
    return {"blue": tr("Blue"), "red": tr("Red"), "green": tr("Green"),
            "white": tr("White")}.get(key, key)


def color_of(key: str) -> str | None:
    """The color of a palette entry ("blue", "red"…), or None."""
    for k, color, _name in PALETTE:
        if k == key:
            return color
    return None


def chosen_hex() -> str:
    """The user's choice as is (not adapted to the theme)."""
    try:
        with open(CHOSEN_FILE) as f:
            v = f.read().strip().upper()
        if len(v) == 7 and v.startswith("#"):
            int(v[1:], 16)
            return v
    except (OSError, ValueError):
        pass
    return DEFAULT


def color_hex() -> str:
    for path in (RENDERED, CHOSEN_FILE):
        try:
            with open(path) as f:
                v = f.read().strip()
        except OSError:
            continue
        if len(v) == 7 and v.startswith("#"):
            try:
                int(v[1:], 16)
                return v.upper()
            except ValueError:
                pass
    return DEFAULT


def color_rgb() -> tuple[float, float, float]:
    """The accent color as a 0–1 triple, ready for Cairo."""
    h = color_hex().lstrip("#")
    return (int(h[0:2], 16) / 255.0,
            int(h[2:4], 16) / 255.0,
            int(h[4:6], 16) / 255.0)


def follow(on_change):
    """Call `on_change` every time the user changes the accent.

    Returns the file monitors, which must be kept alive: if the caller lets
    them be garbage-collected, GLib stops notifying and the color would stay
    stuck at its initial value.
    """
    from gi.repository import Gio

    watchers = []
    for path in (RENDERED, CHOSEN_FILE):
        try:
            m = Gio.File.new_for_path(path).monitor_file(
                Gio.FileMonitorFlags.NONE, None)
        except Exception:  # noqa: BLE001
            continue
        m.connect("changed", lambda *_a: on_change(color_rgb()))
        watchers.append(m)
    return watchers
