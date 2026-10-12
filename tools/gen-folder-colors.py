#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Generate the folder accent color artwork (run from the repository root).

  usr/share/icons/zeta/scalable/emblems/emblem-zeta-folder-<key>.svg
      colored dot that the file manager draws on a folder icon
  usr/share/zeta/folders/folder-<key>.svg
      the whole folder in that color, drawn by the ZETA RAYS Desktop

The colors must match COLORS in usr/lib/zeta/system/folder_colors.py.
"""
import os

ROOT = "live-build/config/includes.chroot"
COLORS = {"red": "#C8102E", "white": "#FFFFFF", "green": "#4CC94A",
          "blue": "#3A8DFF", "purple": "#A855F7"}
XMLNS = 'xmlns="http://www.w3.org/2000/svg"'


def shade(hex_color, factor):
    """Same hue, darker (factor < 1)."""
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return "#%02X%02X%02X" % tuple(max(0, min(255, round(c * factor))) for c in (r, g, b))


def emblem(color):
    ring = "#8A8A8E" if color == "#FFFFFF" else "#FFFFFF"
    return ('<svg %s width="16" height="16" viewBox="0 0 16 16">'
            '<circle cx="8" cy="8" r="6" fill="%s" stroke="%s" stroke-width="1.5"/></svg>\n'
            % (XMLNS, color, ring))


def folder(color):
    if color == "#FFFFFF":
        back, front, line = "#D9D9DE", "#F4F4F6", ' stroke="#A1A1A6" stroke-width="1"'
    else:
        back, front, line = shade(color, 0.72), color, ""
    return ('<svg %s width="64" height="64" viewBox="0 0 64 64">'
            '<path d="M6 14a4 4 0 0 1 4-4h14l5 5h25a4 4 0 0 1 4 4v31a4 4 0 0 1-4 4H10a4 4 0 0 1-4-4z" fill="%s"%s/>'
            '<rect x="6" y="21" width="52" height="33" rx="4" fill="%s"%s/>'
            '</svg>\n' % (XMLNS, back, line, front, line))


def write(rel, text):
    p = os.path.join(ROOT, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as f:
        f.write(text)


for key, color in COLORS.items():
    write("usr/share/icons/zeta/scalable/emblems/emblem-zeta-folder-%s.svg" % key, emblem(color))
    write("usr/share/zeta/folders/folder-%s.svg" % key, folder(color))
print("folder color artwork written for:", ", ".join(COLORS))
