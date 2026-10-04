# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA RAYS — accesso al sistema (audio, rete, Bluetooth, energia) per le app ZETA RAYS.

Funzioni semplici e senza stato che chiamano gli strumenti standard
(wpctl, nmcli, busctl, systemctl, loginctl). Non sollevano eccezioni:
se qualcosa manca restituiscono valori vuoti e la UI si adegua.
"""
import os
import signal
import subprocess


def run(cmd, timeout=6, check=False):
    """Esegue un comando; restituisce lo stdout ("" in caso di errore, None con check).

    Allo scadere del tempo termina l'intero gruppo di processi: nessun comando
    resta appeso in background.
    """
    try:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                             stdin=subprocess.DEVNULL, text=True, start_new_session=True)
    except OSError:
        return None if check else ""
    try:
        out, _ = p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except OSError:
            pass
        p.communicate()
        return None if check else ""
    if check and p.returncode != 0:
        return None
    return out


def spawn(cmd):
    """Avvia un programma staccato dall'app (non attende)."""
    try:
        subprocess.Popen(cmd, start_new_session=True, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except OSError:
        return False
