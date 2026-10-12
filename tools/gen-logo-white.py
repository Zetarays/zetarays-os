#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Generate the "positive" ASCII logo for fastfetch.

The official drawing (zeta-original.txt) is a negative: the "#" character is
the fill around the symbol, and the symbol is the empty space. Printed in
color it shows a colored slab with the logo cut out of it.

Here only the half that carries the ink is inverted — the drawing is not
touched, redrawn or simplified: every filled cell becomes empty and vice
versa. The result is the symbol in white on the terminal's black.

    zeta-white.txt           47 lines, one character per pixel
    zeta-white-compact.txt   24 lines, half blocks (same drawing)
"""
import pathlib
import sys

BASE = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else
                    "live-build/config/includes.chroot/usr/share/zeta/fastfetch")
SOURCE = BASE / "zeta-original.txt"

lines = SOURCE.read_text().splitlines()
width = max(len(r) for r in lines)
# fill matrix: True where the original drawing had EMPTY space (the symbol)
pixel = [[(r[x] if x < len(r) else " ") == " " for x in range(width)]
         for r in lines]

# --- full version: one character per pixel ---------------------------------
full = []
for line in pixel:
    # no rstrip: the lines must fully cover whatever is underneath
    full.append("$1" + "".join("█" if p else " " for p in line))
(BASE / "zeta-white.txt").write_text("\n".join(full) + "\n")

# --- compact version: two drawing rows in one line of text -----------------
HALF_BLOCKS = {(False, False): " ", (True, False): "▀", (False, True): "▄", (True, True): "█"}
compact = []
for y in range(0, len(pixel), 2):
    above = pixel[y]
    below = pixel[y + 1] if y + 1 < len(pixel) else [False] * width
    compact.append("$1" + "".join(HALF_BLOCKS[(above[x], below[x])] for x in range(width)))
(BASE / "zeta-white-compact.txt").write_text("\n".join(compact) + "\n")

print("zeta-white.txt:         %d rows × %d columns" % (len(full), width))
print("zeta-white-compact.txt: %d rows × %d columns" % (len(compact), width))
