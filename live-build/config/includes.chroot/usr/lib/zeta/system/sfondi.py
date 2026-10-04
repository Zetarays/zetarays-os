# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA RAYS — gli sfondi ufficiali installati con il sistema.

Stanno in /usr/share/zeta/wallpapers, con una miniatura piccola in
miniature/ (la galleria delle Impostazioni non deve caricare otto immagini
grandi per mostrarle a 190 pixel). Qui c'è solo l'elenco con i nomi da
mostrare e la ricerca per nome, usata anche da ZETA («metti lo sfondo onde
rosse»). Lo sfondo lo applica sempre zeta-sfondo.
"""
from __future__ import annotations

import os

CARTELLA = "/usr/share/zeta/wallpapers"
MINIATURE = os.path.join(CARTELLA, "miniature")

# file: nome mostrato. L'ordine è quello della galleria.
CATALOGO = [
    ("zeta-onde-blu.jpg", "Onde blu"),
    ("zeta-circuiti-verdi.jpg", "Circuiti verdi"),
    ("zeta-onde-rosse.jpg", "Onde rosse"),
    ("zeta-terminale.jpg", "Terminale"),
    ("zeta-blu.jpg", "Logo blu"),
    ("zeta-verde.jpg", "Logo verde"),
    ("zeta-rosso.jpg", "Logo rosso"),
    ("zeta-bianco.jpg", "Logo bianco"),
]


def elenco() -> list:
    """[(percorso, nome, miniatura)] degli sfondi davvero presenti sul disco."""
    out = []
    for f, nome in CATALOGO:
        p = os.path.join(CARTELLA, f)
        if os.path.isfile(p):
            m = os.path.join(MINIATURE, f)
            out.append((p, nome, m if os.path.isfile(m) else p))
    return out


def nome_di(percorso: str) -> str | None:
    """Il nome mostrato di uno sfondo ufficiale, None se non lo è."""
    for p, nome, _m in elenco():
        if os.path.abspath(percorso or "") == p:
            return nome
    return None


def _semplice(t: str) -> str:
    return " ".join(t.lower().replace("-", " ").replace("_", " ").split())


def cerca(testo: str) -> str | None:
    """Il percorso dello sfondo ufficiale che si chiama così (anche solo in
    parte: «onde rosse», «circuiti», «terminale»), None se nessuno o se il
    nome ne indica più d'uno."""
    t = _semplice(testo)
    if t.startswith("sfondo "):
        t = t[7:]
    if not t:
        return None
    voci = elenco()
    for p, nome, _m in voci:
        if t in (_semplice(nome), _semplice(os.path.basename(p)[:-4]), _semplice(os.path.basename(p))):
            return p
    trovati = [p for p, nome, _m in voci if t in _semplice(nome)]
    return trovati[0] if len(trovati) == 1 else None
