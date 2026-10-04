#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Prepara il logo ASCII di ZETA RAYS per fastfetch.

Il disegno consegnato (ZETA_RAYS_ASCII.txt) è in negativo: il blocco pieno è
lo sfondo e il marchio è il vuoto. Stampato a colori si vedrebbe una lastra
colorata con il marchio ritagliato dentro. Qui si inverte solo quale metà
porta l'inchiostro — il disegno non viene ridisegnato né semplificato — così
il marchio esce chiaro sul nero del terminale.

Si producono tre rese dello stesso identico disegno, per finestre di misure
diverse. Il disegno è largo 119 colonne: in un terminale normale, accanto alle
informazioni, non ci starebbe.

    zeta-bianco.txt           una riga di testo per riga del disegno (67×119)
    zeta-bianco-compatto.txt  due righe in una, coi mezzi blocchi (34×119)
    zeta-bianco-minuto.txt    due righe e due colonne in un carattere, coi
                              quarti di blocco (17×60): entra ovunque

    tools/gen-logo-ascii.py <sorgente.txt> <cartella di destinazione>
"""
import sys

SORGENTE = sys.argv[1]
DEST = sys.argv[2].rstrip("/")

righe = open(SORGENTE).read().splitlines()
while righe and not righe[-1].strip():
    righe.pop()
larghezza = max(len(r) for r in righe)

# True dove nel disegno originale c'era il VUOTO, cioè il marchio
pixel = [[(r[x] if x < len(r) else " ") == " " for x in range(larghezza)]
         for r in righe]

# Bordo inutile: il disegno consegnato ha una cornice piena tutt'intorno, che
# invertita diventa spazio vuoto. Si toglie, altrimenti il logo risulta
# spostato e più largo del necessario.
def vuota(riga):
    return not any(riga)

while pixel and vuota(pixel[0]):
    pixel.pop(0)
while pixel and vuota(pixel[-1]):
    pixel.pop()
colonne_piene = [x for x in range(larghezza) if any(riga[x] for riga in pixel)]
if colonne_piene:
    a, b = colonne_piene[0], colonne_piene[-1] + 1
    pixel = [riga[a:b] for riga in pixel]
larghezza = len(pixel[0]) if pixel else 0

# --- resa intera: un carattere per riga del disegno ---
intero = ["$1" + "".join("█" if p else " " for p in riga) for riga in pixel]
open("%s/zeta-bianco.txt" % DEST, "w").write("\n".join(intero) + "\n")

# --- resa compatta: due righe del disegno in una, con i mezzi blocchi ---
MEZZI = {(False, False): " ", (True, False): "▀", (False, True): "▄", (True, True): "█"}
compatto = []
for y in range(0, len(pixel), 2):
    sopra = pixel[y]
    sotto = pixel[y + 1] if y + 1 < len(pixel) else [False] * larghezza
    compatto.append("$1" + "".join(MEZZI[(sopra[x], sotto[x])] for x in range(larghezza)))
open("%s/zeta-bianco-compatto.txt" % DEST, "w").write("\n".join(compatto) + "\n")

# --- resa minuta: stesso disegno alla metà della risoluzione ---
# Non bastano i quarti di blocco: dimezzano le colonne ma non le righe, e il
# marchio verrebbe fuori stirato in altezza. Qui si dimezza prima il disegno
# in entrambe le direzioni — un quadratino 2×2 diventa un punto, acceso se
# almeno uno dei quattro lo era, così le linee sottili non spariscono — e poi
# lo si stampa coi mezzi blocchi come la resa compatta. Le proporzioni restano
# quelle giuste.
#
# A questa misura la scritta ZETA RAYS non si leggerebbe: diventerebbe una
# riga di macchie. Si tiene il solo simbolo, che è ciò che si riconosce anche
# in piccolo; il nome del sistema fastfetch lo scrive comunque accanto.
solo_simbolo = pixel
for y in range(len(pixel) - 1, 0, -1):
    if not any(pixel[y]) and any(any(r) for r in pixel[:y]):
        # prima banda vuota partendo dal basso: sotto c'è la scritta
        vuote = y
        while vuote > 0 and not any(pixel[vuote - 1]):
            vuote -= 1
        if any(any(r) for r in pixel[y + 1:]):
            solo_simbolo = pixel[:vuote]
        break

ridotto = []
for y in range(0, len(solo_simbolo), 2):
    r0 = solo_simbolo[y]
    r1 = solo_simbolo[y + 1] if y + 1 < len(solo_simbolo) else [False] * larghezza
    riga = []
    for x in range(0, larghezza, 2):
        x2 = x + 1 if x + 1 < larghezza else x
        riga.append(r0[x] or r0[x2] or r1[x] or r1[x2])
    ridotto.append(riga)
largh_r = len(ridotto[0]) if ridotto else 0

minuto = []
for y in range(0, len(ridotto), 2):
    sopra = ridotto[y]
    sotto = ridotto[y + 1] if y + 1 < len(ridotto) else [False] * largh_r
    minuto.append("$1" + "".join(MEZZI[(sopra[x], sotto[x])] for x in range(largh_r)))
open("%s/zeta-bianco-minuto.txt" % DEST, "w").write("\n".join(minuto) + "\n")

print("zeta-bianco.txt:          %d righe × %d colonne" % (len(intero), larghezza))
print("zeta-bianco-compatto.txt: %d righe × %d colonne" % (len(compatto), larghezza))
print("zeta-bianco-minuto.txt:   %d righe × %d colonne" % (len(minuto), largh_r))
