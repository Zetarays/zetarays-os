#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""README.txt della consegna dal modello docs/README-1.7.txt.in.

Dimensioni e SHA-256 si leggono dalle immagini e dai file .sha256 nella
cartella di consegna, la versione del kernel dal registro della costruzione:
niente si copia a mano.

  tools/genera-readme.py CARTELLA_CONSEGNA
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMMAGINI = ["amd64.iso", "arm64.iso", "amd64.ova", "arm64.ova"]


def main(dest):
    testo = open(os.path.join(ROOT, "docs", "README-1.7.txt.in"), encoding="ascii").read()
    for nome in IMMAGINI:
        f = os.path.join(dest, "zetarays-1.7-%s" % nome)
        n = os.path.getsize(f)
        testo = testo.replace("{SIZE_%s}" % nome, "{:,} bytes ({:.2f} GB)".format(n, n / 1e9))
        sha = open(f + ".sha256").read().split()[0]
        if not re.fullmatch(r"[0-9a-f]{64}", sha):
            sys.exit("impronta non valida in %s.sha256" % f)
        testo = testo.replace("{SHA_%s}" % nome, sha)
    log = open(os.path.join(ROOT, "out", "run-arm64.log"), errors="replace").read()
    m = re.findall(r"linux-image-(\d+\.\d+\.\d+)\+deb13", log)
    if not m:
        sys.exit("versione del kernel non trovata nel registro")
    testo = testo.replace("{KERNEL}", m[-1])
    resto = re.findall(r"\{[A-Za-z_0-9.]+\}", testo)
    if resto:
        sys.exit("segnaposto non riempiti: %s" % resto)
    for i, riga in enumerate(testo.split("\n"), 1):
        if len(riga) > 79 or any(ord(c) > 127 for c in riga):
            sys.exit("riga %d non ASCII o piu' lunga di 79" % i)
    open(os.path.join(dest, "README.txt"), "w", encoding="ascii").write(testo)
    print("README.txt scritto (kernel %s)" % m[-1])


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/Desktop/ZETA RAYS 1.7"))
