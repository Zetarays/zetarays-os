# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA RAYS — the official wallpapers installed with the system.

They live in /usr/share/zeta/wallpapers, with a small thumbnail in
thumbnails/ (the Settings gallery must not load eight large images just to
show them at 190 pixels). This module only holds the list with the display
names and the lookup by name, also used by ZETA («metti lo sfondo onde
rosse»). The wallpaper itself is always applied by zeta-wallpaper.
"""
from __future__ import annotations

import os

from i18n import tr

FOLDER = "/usr/share/zeta/wallpapers"
THUMBNAILS = os.path.join(FOLDER, "thumbnails")

# file: display name, and the names it can be searched by (in English and in
# Italian: «metti lo sfondo onde rosse» and «red waves» both work, whatever
# the system language). The order is the gallery order.
# i18n-data-begin
CATALOG = [
    ("zeta-blue-waves.jpg", tr("Blue waves"), ("blue waves", "onde blu")),
    ("zeta-green-circuits.jpg", tr("Green circuits"), ("green circuits", "circuiti verdi")),
    ("zeta-red-waves.jpg", tr("Red waves"), ("red waves", "onde rosse")),
    ("zeta-terminal.jpg", tr("Terminal"), ("terminal", "terminale")),
    ("zeta-blue.jpg", tr("Blue logo"), ("blue logo", "logo blu")),
    ("zeta-green.jpg", tr("Green logo"), ("green logo", "logo verde")),
    ("zeta-red.jpg", tr("Red logo"), ("red logo", "logo rosso")),
    ("zeta-white.jpg", tr("White logo"), ("white logo", "logo bianco")),
]
# i18n-data-end


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
    match: «onde rosse», «circuiti», «terminale»), None if there is none or if
    the name matches more than one."""
    t = _simple(text)
    for prefix in ("sfondo ", "wallpaper ", "background "):  # i18n-data
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
