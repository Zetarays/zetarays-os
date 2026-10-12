#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Generates the ZETA RAYS logo SVGs from the original vector file.

The logo started life as an Illustrator file (ZETA_RAYS_LOGO.ai, which is a
PDF); the paths are extracted from it once and used to build the templates
the system uses. The templates contain the word ACCENT instead of a color:
whoever renders them replaces it with the chosen accent color.

    zeta-symbol.svg.in      triangle only (bar symbol, icons)
    zeta-logo.svg.in        symbol + ZETA RAYS lettering
    zeta-logo-white.svg     the same, fixed white
    zeta-logo-black.svg     the same, fixed black
    zeta-wallpaper.svg.in   4K wallpaper with the logo in the center

    tools/gen-wordmark.py <converted logo.svg> <destination directory>
"""
import re
import sys

SOURCE = sys.argv[1]
DEST = sys.argv[2].rstrip("/")

text = open(SOURCE).read()
path_data = re.findall(r'<path[^>]*d="([^"]+)"', text)
if len(path_data) < 2:
    sys.exit("the converted file does not contain the expected paths")

SYMBOL = path_data[0]          # the triangle
WORDMARK = path_data[1:]         # the ZETA RAYS letters


def bounding_box(ds):
    xs, ys = [], []
    for d in ds:
        n = [float(v) for v in re.findall(r"-?\d+\.?\d*", d)]
        xs += n[0::2]
        ys += n[1::2]
    return min(xs), min(ys), max(xs), max(ys)


def svg(ds, color, width=None, height=None, margin=0.0):
    x0, y0, x1, y1 = bounding_box(ds)
    x0 -= margin; y0 -= margin; x1 += margin; y1 += margin
    w, h = x1 - x0, y1 - y0
    attr = ""
    if width:
        attr = ' width="%g" height="%g"' % (width, width * h / w)
    body = "".join('<path d="%s"/>' % d for d in ds)
    return ('<svg xmlns="http://www.w3.org/2000/svg"%s '
            'viewBox="%.3f %.3f %.3f %.3f" fill="%s" fill-rule="nonzero">'
            '%s</svg>\n' % (attr, x0, y0, w, h, color, body))


def write(name, content):
    with open("%s/%s" % (DEST, name), "w") as f:
        f.write(content)
    print("  %s  (%d bytes)" % (name, len(content)))


print("generating the logo in %s" % DEST)
write("zeta-symbol.svg.in", svg([SYMBOL], "ACCENT", width=22))
write("zeta-logo.svg.in", svg([SYMBOL] + WORDMARK, "ACCENT"))
write("zeta-logo-white.svg", svg([SYMBOL] + WORDMARK, "#FFFFFF"))
write("zeta-logo-black.svg", svg([SYMBOL] + WORDMARK, "#000000"))

# --- 4K wallpaper: logo in the center, in the same proportions as the original ---
x0, y0, x1, y1 = bounding_box([SYMBOL] + WORDMARK)
LW, LH = 339, 354                 # measured on the supplied wallpaper
LX, LY = (3840 - LW) / 2, (2160 - LH) / 2
internal = "".join('<path d="%s"/>' % d for d in [SYMBOL] + WORDMARK)
background = ('<svg xmlns="http://www.w3.org/2000/svg" width="3840" height="2160" '
          'viewBox="0 0 3840 2160">'
          '<rect width="3840" height="2160" fill="BGCOLOR"/>'
          '<svg x="%g" y="%g" width="%g" height="%g" viewBox="%.3f %.3f %.3f %.3f">'
          '<g fill="ACCENT" fill-rule="nonzero">%s</g></svg></svg>\n'
          % (LX, LY, LW, LH, x0, y0, x1 - x0, y1 - y0, internal))
write("zeta-wallpaper.svg.in", background)
