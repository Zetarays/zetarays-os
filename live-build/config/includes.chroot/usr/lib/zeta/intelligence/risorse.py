# SPDX-License-Identifier: GPL-3.0-or-later
"""Risorse della macchina: quanta memoria c'è davvero.

Il modello AI locale occupa circa 1,8 GB. Tenerlo in memoria rende le risposte
immediate, ma su un computer con poca RAM è proprio ciò che fa arrancare tutto
il resto: il desktop comincia a usare lo scambio su disco e l'utente vede
blocchi e lentezze. Qui si decide, una volta sola e in un posto solo, quanto
si può osare.
"""
from __future__ import annotations

from i18n import tr

# Soglie in GB di memoria di targa (vedi memoria_nominale_gb).
# Il modello si carica a freddo in 1-2 s (misurato): basta cominciare quando si
# apre ZETA (lo fa zeta-core) e intanto si scrive la domanda. Caricarlo gia'
# all'accesso teneva 1,8 GB occupati per 5 minuti a ogni avvio anche se ZETA
# non veniva aperto: lo si fa solo dove la memoria e' davvero abbondante.
SOGLIA_PRECARICO = 16.0    # sotto: non si carica il modello all'accesso
SOGLIA_AGIATA = 8.0        # sopra: lo si può tenere caldo a lungo
SOGLIA_STRETTA = 4.0       # sotto: lo si scarica quasi subito dopo l'uso


def memoria_totale_gb() -> float:
    """Memoria totale vista dal kernel, in GB (0.0 se non leggibile)."""
    try:
        with open("/proc/meminfo") as f:
            for riga in f:
                if riga.startswith("MemTotal:"):
                    return int(riga.split()[1]) / (1024 * 1024)
    except (OSError, ValueError, IndexError):
        pass
    return 0.0


def memoria_nominale_gb() -> float:
    """La RAM «di targa» della macchina: quella che si confronta con le soglie.

    Il kernel non vede mai tutta la memoria installata: una parte va al
    firmware, alla grafica integrata, alle proprie strutture. Un computer (o
    una macchina virtuale) da 8 GB dichiara circa 7,7 GB, uno da 4 circa 3,8.
    Confrontando quel valore con «8 GB» il precarico non scattava mai sulle
    macchine da 8 GB, cioè proprio quelle per cui la soglia era pensata.
    Arrotondando per eccesso all'intero si ritrova la taglia reale.
    """
    gb = memoria_totale_gb()
    if gb <= 0:
        return 0.0
    import math
    return float(math.ceil(gb - 0.05))


def memoria_disponibile_gb() -> float:
    """Memoria realmente disponibile ora, senza contare cache riutilizzabile."""
    try:
        with open("/proc/meminfo") as f:
            for riga in f:
                if riga.startswith("MemAvailable:"):
                    return int(riga.split()[1]) / (1024 * 1024)
    except (OSError, ValueError, IndexError):
        pass
    return 0.0


def keep_alive() -> str:
    """Per quanto tenere il modello in memoria dopo l'ultima domanda.

    Su una macchina capiente conviene tenerlo caldo a lungo: ricaricarlo costa
    decine di secondi. Su una macchina piccola conviene il contrario: 1,8 GB
    trattenuti per mezz'ora valgono meno di un desktop che resta fluido.
    """
    gb = memoria_nominale_gb()
    if gb <= 0:
        return "5m"
    if gb < SOGLIA_STRETTA:
        return "2m"
    if gb < SOGLIA_AGIATA:
        return "10m"
    return "30m"


def precarico_consentito() -> bool:
    """Se conviene portare il modello in memoria già all'accesso."""
    return memoria_nominale_gb() >= SOGLIA_PRECARICO


# Quanto occupa il modello locale una volta caricato, più il margine che il
# resto del sistema deve potersi tenere. Sotto questa soglia caricarlo non
# rallenta soltanto: manda il computer a scambiare su disco e lo pianta.
MODELLO_GB = 1.9
MARGINE_GB = 0.7


def memoria_per_il_modello() -> bool:
    """Vero se c'è spazio per caricare il modello senza piantare il computer.

    Il caso che conta è il sistema live: gira dall'immagine, la memoria è poca
    e non c'è spazio di scambio su disco. Caricare lì un modello da quasi due
    gigabyte significa il blocco che l'utente vede come «si è impallato».
    Meglio dirglielo.
    """
    disponibile = memoria_disponibile_gb()
    if disponibile <= 0:
        return True          # non si riesce a misurare: non si vieta nulla
    return disponibile >= MODELLO_GB + MARGINE_GB


def motivo_memoria() -> str:
    """Spiegazione da mostrare a chi chiede, quando la memoria non basta."""
    return tr("There isn't enough free memory for the local model "
              "(it needs about {needed} GB, {free} GB free). Close some "
              "apps and try again.").format(needed="%.1f" % (MODELLO_GB + MARGINE_GB),
                                            free="%.1f" % memoria_disponibile_gb())
