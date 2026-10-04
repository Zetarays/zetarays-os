# SPDX-License-Identifier: GPL-3.0-or-later
"""Colore d'accento del sistema, in un posto solo.

Chi disegna qualcosa con il colore scelto dall'utente lo chiede qui, invece di
tenersi una propria tavolozza. Prima la sfera di ZETA aveva quattro colori
suoi, salvati in un file separato e cambiati con dei tasti: era un secondo
sistema di temi che viveva accanto a quello vero, e bastava cambiare accento
dalle Impostazioni perché i due non coincidessero più.

    da ui.accento import colore_rgb, segui
"""
from __future__ import annotations

import os

# Il colore *reso*: quello scelto dall'utente, già adattato al tema in uso
# (il bianco su tema chiaro diventa un grigio leggibile). Se manca si ricade
# sulla scelta grezza, e infine sul blu di ZETA RAYS.
CFG = os.path.expanduser("~/.config/zeta")
RESO = os.path.join(CFG, "accent-reso")
SCELTO = os.path.join(CFG, "accent")
PREDEFINITO = "#3A8DFF"


def colore_hex() -> str:
    for percorso in (RESO, SCELTO):
        try:
            with open(percorso) as f:
                v = f.read().strip()
        except OSError:
            continue
        if len(v) == 7 and v.startswith("#"):
            try:
                int(v[1:], 16)
                return v.upper()
            except ValueError:
                pass
    return PREDEFINITO


def colore_rgb() -> tuple[float, float, float]:
    """Il colore d'accento come terna 0–1, pronta per Cairo."""
    h = colore_hex().lstrip("#")
    return (int(h[0:2], 16) / 255.0,
            int(h[2:4], 16) / 255.0,
            int(h[4:6], 16) / 255.0)


def segui(quando_cambia):
    """Chiama «quando_cambia» ogni volta che l'utente cambia accento.

    Restituisce i sorveglianti, che vanno tenuti vivi: se il chiamante li
    lascia raccogliere, GLib smette di avvisare e il colore resterebbe fermo
    a quello di partenza.
    """
    from gi.repository import Gio

    sorveglianti = []
    for percorso in (RESO, SCELTO):
        try:
            m = Gio.File.new_for_path(percorso).monitor_file(
                Gio.FileMonitorFlags.NONE, None)
        except Exception:  # noqa: BLE001
            continue
        m.connect("changed", lambda *_a: quando_cambia(colore_rgb()))
        sorveglianti.append(m)
    return sorveglianti
