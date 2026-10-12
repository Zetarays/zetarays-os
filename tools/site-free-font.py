#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Copy of the website with a free display font, for redistribution.

The live site (zetarays.org, own hosting) uses Clash Display, whose ITF Free
Font License allows self-hosting on one's own website but forbids
redistribution: no public repository, no copy inside the ISO images. This
script writes a copy of site-zetarays/ where Clash Display is replaced by
Syne (SIL Open Font License 1.1, redistributable), embedded in the page like
Clash was (browsers do not load a font from a sibling file when the page is
opened from disk, as Firefox's offline start page is).

Used by build.sh (offline copy in the images) and for the public GitHub repo.

  site-free-font.py <site dir> <output dir>
"""
import base64
import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SYNE = os.path.join(HERE, "free-font", "Syne.woff2")
SYNE_OFL = os.path.join(HERE, "free-font", "OFL-Syne.txt")


def main(site, out):
    page = open(os.path.join(site, "index.html"), encoding="utf-8").read()

    blocks = re.findall(r'@font-face\{font-family:"Clash Display";[^}]*\}', page)
    if not blocks:
        sys.exit("no Clash Display @font-face found: has the site changed?")
    syne = base64.b64encode(open(SYNE, "rb").read()).decode()
    new = ('@font-face{font-family:"Syne"; font-weight:400 800; font-style:normal;\n'
             '    font-display:swap; src:url(data:font/woff2;base64,%s) format("woff2")}' % syne)
    page = page.replace(blocks[0], new, 1)
    for b in blocks[1:]:
        page = page.replace(b, "", 1)
    page = page.replace("/* --- Clash Display (Indian Type Foundry, ITF Free Font License) ---",
                        "/* --- Syne (SIL Open Font License 1.1, fonts/OFL-Syne.txt) ---", 1)
    page = page.replace('--display:"Clash Display",', '--display:"Syne",', 1)
    # At the same weight Syne is lighter than Clash: headings and wordmark one
    # step bolder (600 -> 700), for a look close to the original.
    assert page.count("</style>") >= 1
    page = page.replace("</style>",
                        "  /* Syne: one step bolder, close to the font of the online site */\n"
                        "  h1,h2,h3{font-weight:700}\n</style>", 1)
    if "Clash Display" in page:
        sys.exit("Clash Display is still mentioned in the page")

    if os.path.isdir(out):
        shutil.rmtree(out)
    shutil.copytree(site, out, ignore=shutil.ignore_patterns(
        "index.html", "index-original.html", ".DS_Store", "ClashDisplay-*", "LICENSE-ClashDisplay.txt"))
    os.makedirs(os.path.join(out, "fonts"), exist_ok=True)
    shutil.copy2(SYNE_OFL, os.path.join(out, "fonts", "OFL-Syne.txt"))
    with open(os.path.join(out, "index.html"), "w", encoding="utf-8") as f:
        f.write(page)
    for root, _dirs, files in os.walk(out):
        for n in files:
            if "clash" in n.lower():
                sys.exit("Clash Display file left: %s" % os.path.join(root, n))
    print("site with free font (Syne): %s" % out)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
