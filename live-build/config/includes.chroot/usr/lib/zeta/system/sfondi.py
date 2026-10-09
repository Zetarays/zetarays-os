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

from i18n import tr

CARTELLA = "/usr/share/zeta/wallpapers"
MINIATURE = os.path.join(CARTELLA, "miniature")

# file: nome mostrato, e i nomi con cui lo si cerca (in inglese e in
# italiano: «metti lo sfondo onde rosse» e «red waves» vanno bene tutti e
# due, qualunque sia la lingua del sistema). L'ordine è quello della galleria.
CATALOGO = [
    ("zeta-onde-blu.jpg", tr("Blue waves"), ("blue waves", "onde blu")),
    ("zeta-circuiti-verdi.jpg", tr("Green circuits"), ("green circuits", "circuiti verdi")),
    ("zeta-onde-rosse.jpg", tr("Red waves"), ("red waves", "onde rosse")),
    ("zeta-terminale.jpg", tr("Terminal"), ("terminal", "terminale")),
    ("zeta-blu.jpg", tr("Blue logo"), ("blue logo", "logo blu")),
    ("zeta-verde.jpg", tr("Green logo"), ("green logo", "logo verde")),
    ("zeta-rosso.jpg", tr("Red logo"), ("red logo", "logo rosso")),
    ("zeta-bianco.jpg", tr("White logo"), ("white logo", "logo bianco")),
]


def elenco() -> list:
    """[(percorso, nome, miniatura)] degli sfondi davvero presenti sul disco."""
    out = []
    for f, nome, _cerca in CATALOGO:
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


def _nomi(percorso: str, nome: str) -> list:
    """Tutti i nomi di uno sfondo: quello mostrato e quelli fissi di ricerca."""
    f = os.path.basename(percorso)
    fissi = next((c for file, _n, c in CATALOGO if file == f), ())
    return [_semplice(nome)] + [_semplice(c) for c in fissi]


def cerca(testo: str) -> str | None:
    """Il percorso dello sfondo ufficiale che si chiama così (anche solo in
    parte: «onde rosse», «circuiti», «terminale»), None se nessuno o se il
    nome ne indica più d'uno."""
    t = _semplice(testo)
    for prefisso in ("sfondo ", "wallpaper ", "background "):
        if t.startswith(prefisso):
            t = t[len(prefisso):]
            break
    if not t:
        return None
    voci = elenco()
    for p, nome, _m in voci:
        if t in _nomi(p, nome) + [_semplice(os.path.basename(p)[:-4]), _semplice(os.path.basename(p))]:
            return p
    trovati = [p for p, nome, _m in voci if any(t in n for n in _nomi(p, nome))]
    return trovati[0] if len(trovati) == 1 else None
