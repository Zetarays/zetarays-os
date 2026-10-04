#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Genera il logo ASCII «positivo» per fastfetch.

Il disegno ufficiale (zeta-original.txt) è in negativo: il carattere «#» è il
pieno intorno al simbolo, e il simbolo è lo spazio vuoto. Stampato a colori si
vede una lastra colorata con il marchio ritagliato dentro.

Qui si inverte soltanto quale metà porta l'inchiostro — il disegno non viene
toccato, ridisegnato né semplificato: ogni pieno diventa vuoto e viceversa.
Il risultato è il simbolo bianco sul nero del terminale.

    zeta-bianco.txt           47 righe, un carattere per pixel
    zeta-bianco-compatto.txt  24 righe, mezzi blocchi (stesso disegno)
"""
import pathlib
import sys

BASE = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else
                    "live-build/config/includes.chroot/usr/share/zeta/fastfetch")
SORGENTE = BASE / "zeta-original.txt"

righe = SORGENTE.read_text().splitlines()
larghezza = max(len(r) for r in righe)
# matrice di pieni: True dove nel disegno originale c'era il VUOTO (il simbolo)
pixel = [[(r[x] if x < len(r) else " ") == " " for x in range(larghezza)]
         for r in righe]

# --- versione intera: un carattere per pixel -------------------------------
intero = []
for riga in pixel:
    # niente rstrip: le righe devono coprire per intero ciò che sta sotto
    intero.append("$1" + "".join("█" if p else " " for p in riga))
(BASE / "zeta-bianco.txt").write_text("\n".join(intero) + "\n")

# --- versione compatta: due righe del disegno in una riga di testo ---------
MEZZI = {(False, False): " ", (True, False): "▀", (False, True): "▄", (True, True): "█"}
compatto = []
for y in range(0, len(pixel), 2):
    sopra = pixel[y]
    sotto = pixel[y + 1] if y + 1 < len(pixel) else [False] * larghezza
    compatto.append("$1" + "".join(MEZZI[(sopra[x], sotto[x])] for x in range(larghezza)))
(BASE / "zeta-bianco-compatto.txt").write_text("\n".join(compatto) + "\n")

print("zeta-bianco.txt:          %d righe × %d colonne" % (len(intero), larghezza))
print("zeta-bianco-compatto.txt: %d righe × %d colonne" % (len(compatto), larghezza))
