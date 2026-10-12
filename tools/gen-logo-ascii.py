#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Prepare the ZETA RAYS ASCII logo for fastfetch.

The supplied drawing (ZETA_RAYS_ASCII.txt) is a negative: the full block is
the background and the logo is the empty space. Printed in color it would
show a colored slab with the logo cut out of it. Here only the half that
carries the ink is inverted — the drawing is neither redrawn nor simplified —
so the logo comes out light on the terminal's black.

Three renderings of the exact same drawing are produced, for windows of
different sizes. The drawing is 119 columns wide: in a normal terminal it
would not fit next to the information.

    zeta-white.txt           one line of text per drawing row (67×119)
    zeta-white-compact.txt   two rows in one, with half blocks (34×119)
    zeta-white-tiny.txt      two rows and two columns in one character, with
                             quarter blocks (17×60): fits anywhere

    tools/gen-logo-ascii.py <source.txt> <destination folder>
"""
import sys

SOURCE = sys.argv[1]
DEST = sys.argv[2].rstrip("/")

lines = open(SOURCE).read().splitlines()
while lines and not lines[-1].strip():
    lines.pop()
width = max(len(r) for r in lines)

# True where the original drawing had EMPTY space, i.e. the logo
pixel = [[(r[x] if x < len(r) else " ") == " " for x in range(width)]
         for r in lines]

# Useless border: the supplied drawing has a full frame all around, which
# becomes empty space once inverted. It is removed, otherwise the logo ends up
# offset and wider than needed.
def is_blank(line):
    return not any(line)

while pixel and is_blank(pixel[0]):
    pixel.pop(0)
while pixel and is_blank(pixel[-1]):
    pixel.pop()
filled_columns = [x for x in range(width) if any(line[x] for line in pixel)]
if filled_columns:
    a, b = filled_columns[0], filled_columns[-1] + 1
    pixel = [line[a:b] for line in pixel]
width = len(pixel[0]) if pixel else 0

# --- full rendering: one character per drawing row ---
full = ["$1" + "".join("█" if p else " " for p in line) for line in pixel]
open("%s/zeta-white.txt" % DEST, "w").write("\n".join(full) + "\n")

# --- compact rendering: two drawing rows in one, with half blocks ---
HALF_BLOCKS = {(False, False): " ", (True, False): "▀", (False, True): "▄", (True, True): "█"}
compact = []
for y in range(0, len(pixel), 2):
    above = pixel[y]
    below = pixel[y + 1] if y + 1 < len(pixel) else [False] * width
    compact.append("$1" + "".join(HALF_BLOCKS[(above[x], below[x])] for x in range(width)))
open("%s/zeta-white-compact.txt" % DEST, "w").write("\n".join(compact) + "\n")

# --- tiny rendering: the same drawing at half resolution ---
# Quarter blocks are not enough: they halve the columns but not the rows, and
# the logo would come out stretched vertically. Here the drawing is first
# halved in both directions — a 2×2 square becomes one dot, lit if at least
# one of the four was, so thin lines do not vanish — and then printed with
# half blocks like the compact rendering. The proportions stay correct.
#
# At this size the ZETA RAYS lettering would be unreadable: it would turn into
# a row of smudges. Only the symbol is kept, which is recognizable even when
# small; fastfetch writes the system name next to it anyway.
symbol_only = pixel
for y in range(len(pixel) - 1, 0, -1):
    if not any(pixel[y]) and any(any(r) for r in pixel[:y]):
        # first empty band from the bottom: the lettering is below it
        empty_rows = y
        while empty_rows > 0 and not any(pixel[empty_rows - 1]):
            empty_rows -= 1
        if any(any(r) for r in pixel[y + 1:]):
            symbol_only = pixel[:empty_rows]
        break

reduced = []
for y in range(0, len(symbol_only), 2):
    r0 = symbol_only[y]
    r1 = symbol_only[y + 1] if y + 1 < len(symbol_only) else [False] * width
    line = []
    for x in range(0, width, 2):
        x2 = x + 1 if x + 1 < width else x
        line.append(r0[x] or r0[x2] or r1[x] or r1[x2])
    reduced.append(line)
reduced_width = len(reduced[0]) if reduced else 0

tiny = []
for y in range(0, len(reduced), 2):
    above = reduced[y]
    below = reduced[y + 1] if y + 1 < len(reduced) else [False] * reduced_width
    tiny.append("$1" + "".join(HALF_BLOCKS[(above[x], below[x])] for x in range(reduced_width)))
open("%s/zeta-white-tiny.txt" % DEST, "w").write("\n".join(tiny) + "\n")

print("zeta-white.txt:         %d rows × %d columns" % (len(full), width))
print("zeta-white-compact.txt: %d rows × %d columns" % (len(compact), width))
print("zeta-white-tiny.txt:    %d rows × %d columns" % (len(tiny), reduced_width))
