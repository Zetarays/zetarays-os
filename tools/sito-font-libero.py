#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Copy of the website with a free display font, for redistribution.

The live site (zetarays.org, own hosting) uses Clash Display, whose ITF Free
Font License allows self-hosting on one's own website but forbids
redistribution: no public repository, no copy inside the ISO images. This
script writes a copy of sito-zetarays/ where Clash Display is replaced by
Syne (SIL Open Font License 1.1, redistributable), embedded in the page like
Clash was (browsers do not load a font from a sibling file when the page is
opened from disk, as Firefox's offline start page is).

Used by build.sh (offline copy in the images) and for the public GitHub repo.

  sito-font-libero.py <site dir> <output dir>
"""
import base64
import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SYNE = os.path.join(HERE, "font-libero", "Syne.woff2")
SYNE_OFL = os.path.join(HERE, "font-libero", "OFL-Syne.txt")


def main(site, out):
    page = open(os.path.join(site, "index.html"), encoding="utf-8").read()

    blocks = re.findall(r'@font-face\{font-family:"Clash Display";[^}]*\}', page)
    if not blocks:
        sys.exit("nessun @font-face di Clash Display trovato: il sito e' cambiato?")
    syne = base64.b64encode(open(SYNE, "rb").read()).decode()
    nuovo = ('@font-face{font-family:"Syne"; font-weight:400 800; font-style:normal;\n'
             '    font-display:swap; src:url(data:font/woff2;base64,%s) format("woff2")}' % syne)
    page = page.replace(blocks[0], nuovo, 1)
    for b in blocks[1:]:
        page = page.replace(b, "", 1)
    page = page.replace("/* --- Clash Display (Indian Type Foundry, ITF Free Font License) ---",
                        "/* --- Syne (SIL Open Font License 1.1, fonts/OFL-Syne.txt) ---", 1)
    page = page.replace('--display:"Clash Display",', '--display:"Syne",', 1)
    # Syne a parita' di peso e' piu' leggero di Clash: titoli e marchio un
    # gradino piu' pieni (600 -> 700), per un aspetto vicino all'originale.
    assert page.count("</style>") >= 1
    page = page.replace("</style>",
                        "  /* Syne: un gradino piu' pieno, vicino al carattere del sito online */\n"
                        "  h1,h2,h3{font-weight:700}\n</style>", 1)
    if "Clash Display" in page:
        sys.exit("Clash Display e' ancora citato nella pagina")

    if os.path.isdir(out):
        shutil.rmtree(out)
    shutil.copytree(site, out, ignore=shutil.ignore_patterns(
        "index.html", "index-ORIGINALE.html", ".DS_Store", "ClashDisplay-*", "LICENZA-ClashDisplay.txt"))
    os.makedirs(os.path.join(out, "fonts"), exist_ok=True)
    shutil.copy2(SYNE_OFL, os.path.join(out, "fonts", "OFL-Syne.txt"))
    with open(os.path.join(out, "index.html"), "w", encoding="utf-8") as f:
        f.write(page)
    for root, _dirs, files in os.walk(out):
        for n in files:
            if "clash" in n.lower():
                sys.exit("file di Clash Display rimasto: %s" % os.path.join(root, n))
    print("sito con font libero (Syne): %s" % out)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
