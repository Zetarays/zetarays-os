#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Genera gli SVG del marchio ZETA RAYS dal file vettoriale originale.

Il logo nasce come file Illustrator (ZETA_RAYS_LOGO.ai, che è un PDF); da lì
si ricavano i tracciati una volta sola e si costruiscono i modelli che il
sistema usa. I modelli contengono la parola ACCENT al posto del colore: chi
disegna la sostituisce con il colore d'accento scelto.

    zeta-simbolo.svg.in     solo il triangolo (simbolo della barra, icone)
    zeta-logo.svg.in        simbolo + scritta ZETA RAYS
    zeta-logo-bianco.svg    lo stesso, bianco fisso
    zeta-logo-nero.svg      lo stesso, nero fisso
    zeta-wallpaper.svg.in   sfondo 4K con il marchio al centro

    tools/gen-marchio.py <logo.svg convertito> <cartella di destinazione>
"""
import re
import sys

SORGENTE = sys.argv[1]
DEST = sys.argv[2].rstrip("/")

testo = open(SORGENTE).read()
tracciati = re.findall(r'<path[^>]*d="([^"]+)"', testo)
if len(tracciati) < 2:
    sys.exit("nel file convertito non ci sono i tracciati attesi")

SIMBOLO = tracciati[0]          # il triangolo
SCRITTA = tracciati[1:]         # le lettere di ZETA RAYS


def riquadro(ds):
    xs, ys = [], []
    for d in ds:
        n = [float(v) for v in re.findall(r"-?\d+\.?\d*", d)]
        xs += n[0::2]
        ys += n[1::2]
    return min(xs), min(ys), max(xs), max(ys)


def svg(ds, colore, larghezza=None, altezza=None, margine=0.0):
    x0, y0, x1, y1 = riquadro(ds)
    x0 -= margine; y0 -= margine; x1 += margine; y1 += margine
    w, h = x1 - x0, y1 - y0
    attr = ""
    if larghezza:
        attr = ' width="%g" height="%g"' % (larghezza, larghezza * h / w)
    corpo = "".join('<path d="%s"/>' % d for d in ds)
    return ('<svg xmlns="http://www.w3.org/2000/svg"%s '
            'viewBox="%.3f %.3f %.3f %.3f" fill="%s" fill-rule="nonzero">'
            '%s</svg>\n' % (attr, x0, y0, w, h, colore, corpo))


def scrivi(nome, contenuto):
    with open("%s/%s" % (DEST, nome), "w") as f:
        f.write(contenuto)
    print("  %s  (%d byte)" % (nome, len(contenuto)))


print("genero il marchio in %s" % DEST)
scrivi("zeta-simbolo.svg.in", svg([SIMBOLO], "ACCENT", larghezza=22))
scrivi("zeta-logo.svg.in", svg([SIMBOLO] + SCRITTA, "ACCENT"))
scrivi("zeta-logo-bianco.svg", svg([SIMBOLO] + SCRITTA, "#FFFFFF"))
scrivi("zeta-logo-nero.svg", svg([SIMBOLO] + SCRITTA, "#000000"))

# --- sfondo 4K: marchio al centro, nelle stesse proporzioni dell'originale ---
x0, y0, x1, y1 = riquadro([SIMBOLO] + SCRITTA)
LW, LH = 339, 354                 # misurati sullo sfondo fornito
LX, LY = (3840 - LW) / 2, (2160 - LH) / 2
interno = "".join('<path d="%s"/>' % d for d in [SIMBOLO] + SCRITTA)
sfondo = ('<svg xmlns="http://www.w3.org/2000/svg" width="3840" height="2160" '
          'viewBox="0 0 3840 2160">'
          '<rect width="3840" height="2160" fill="SFONDO"/>'
          '<svg x="%g" y="%g" width="%g" height="%g" viewBox="%.3f %.3f %.3f %.3f">'
          '<g fill="ACCENT" fill-rule="nonzero">%s</g></svg></svg>\n'
          % (LX, LY, LW, LH, x0, y0, x1 - x0, y1 - y0, interno))
scrivi("zeta-wallpaper.svg.in", sfondo)
