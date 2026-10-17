# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA RAYS — the official wallpapers installed with the system.

They live in /usr/share/zeta/wallpapers, with a small thumbnail in
thumbnails/ (the Settings gallery must not load eight large images just to
show them at 190 pixels). This module only holds the list with the display
names and the lookup by name, also used by ZETA ("set the red waves
wallpaper"). The wallpaper itself is always applied by zeta-wallpaper.
"""
from __future__ import annotations

import os

from i18n import tr
from i18n_data import load

FOLDER = "/usr/share/zeta/wallpapers"
THUMBNAILS = os.path.join(FOLDER, "thumbnails")

# Names a wallpaper can be searched by, in English and in Italian whatever the
# system language, and the words that may precede them: language data in
# /usr/share/zeta/i18n-data/wallpapers.json.
_DATA = load("wallpapers")

# file: display name, and the names it can be searched by. The order is the
# gallery order.
CATALOG = [(f, name, tuple(_DATA["search_names"][f])) for f, name in (
    ("zeta-goddess.jpg", tr("Goddess")),
    ("zeta-blue-waves.jpg", tr("Blue waves")),
    ("zeta-green-circuits.jpg", tr("Green circuits")),
    ("zeta-red-waves.jpg", tr("Red waves")),
    ("zeta-terminal.jpg", tr("Terminal")),
    ("zeta-blue.jpg", tr("Blue logo")),
    ("zeta-green.jpg", tr("Green logo")),
    ("zeta-red.jpg", tr("Red logo")),
    ("zeta-white.jpg", tr("White logo")),
)]


def listing() -> list:
    """[(path, name, thumbnail)] of the wallpapers actually present on disk."""
    out = []
    for f, name, _search in CATALOG:
        p = os.path.join(FOLDER, f)
        if os.path.isfile(p):
            m = os.path.join(THUMBNAILS, f)
            out.append((p, name, m if os.path.isfile(m) else p))
    return out


def name_of(path: str) -> str | None:
    """The display name of an official wallpaper, None if it is not one."""
    for p, name, _m in listing():
        if os.path.abspath(path or "") == p:
            return name
    return None


def _simple(t: str) -> str:
    return " ".join(t.lower().replace("-", " ").replace("_", " ").split())


def _names(path: str, name: str) -> list:
    """All the names of a wallpaper: the displayed one and the fixed search names."""
    f = os.path.basename(path)
    fixed_names = next((c for file, _n, c in CATALOG if file == f), ())
    return [_simple(name)] + [_simple(c) for c in fixed_names]


def search(text: str) -> str | None:
    """The path of the official wallpaper with that name (even a partial
    match: "red waves", "circuits", "terminal"), None if there is none or if
    the name matches more than one."""
    t = _simple(text)
    for prefix in _DATA["prefixes"]:
        if t.startswith(prefix):
            t = t[len(prefix):]
            break
    if not t:
        return None
    entries = listing()
    for p, name, _m in entries:
        if t in _names(p, name) + [_simple(os.path.basename(p)[:-4]), _simple(os.path.basename(p))]:
            return p
    found = [p for p, name, _m in entries if any(t in n for n in _names(p, name))]
    return found[0] if len(found) == 1 else None
