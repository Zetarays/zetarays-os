# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA RAYS Intelligence — sintesi vocale offline (espeak-ng).

Legge ad alta voce le risposte di ZETA. Tutto in locale: nessun testo
lascia il computer. Se espeak-ng non è installato, `available()` è falso e
ZETA non mostra il pulsante invece di fingere che funzioni.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import threading

# La voce segue la stessa lingua che il microfono ascolta: sentirsi rispondere
# in italiano dopo aver parlato in inglese e' straniante, e viceversa. La
# decisione sta in un posto solo, voice.lingua_scelta().
def _voce() -> str:
    try:
        from . import voice
        return voice.lingua_scelta()
    except Exception:  # noqa: BLE001 - la voce non deve mai far cadere ZETA
        return "it"


VOICE = "it"   # ripiego, se la lingua non si riesce a determinare
SPEED = "165"        # parole al minuto: leggibile, non frettoloso
PITCH = "42"

_lock = threading.Lock()
_proc: subprocess.Popen | None = None


def available() -> bool:
    return shutil.which("espeak-ng") is not None


def why_unavailable() -> str:
    if available():
        return ""
    return ("La sintesi vocale (espeak-ng) non è installata. "
            "Installala con «sudo apt install espeak-ng» per far parlare ZETA RAYS.")


def _clean(text: str) -> str:
    """Toglie ciò che non ha senso pronunciare (codice, elenchi, simboli)."""
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"[*_#>|]+", " ", text)
    text = re.sub(r"https?://\S+", "collegamento", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:1200]


def stop() -> None:
    """Interrompe la lettura in corso."""
    global _proc
    with _lock:
        p, _proc = _proc, None
    if p and p.poll() is None:
        try:
            p.terminate()
        except OSError:
            pass


def speaking() -> bool:
    with _lock:
        return _proc is not None and _proc.poll() is None


def _durata_stimata(testo: str) -> float:
    """Quanto dovrebbe durare la lettura, con abbondante margine.

    Serve al guardiano: se il programma di sintesi resta appeso dopo aver
    finito di parlare, va terminato, altrimenti resta un processo fermo per
    sempre. Capita quando la scheda audio non segnala la fine della
    riproduzione — tipico delle macchine virtuali.
    """
    parole = max(1, len(testo.split()))
    secondi = parole / (float(SPEED) / 60.0)
    return secondi * 1.5 + 3.0


def say(text: str, on_done=None) -> bool:
    """Legge il testo senza bloccare. False se la sintesi non è disponibile."""
    global _proc
    if not available():
        return False
    clean = _clean(text)
    if not clean:
        return False
    stop()
    try:
        p = subprocess.Popen(
            ["espeak-ng", "-v", _voce() or VOICE, "-s", SPEED, "-p", PITCH, "--", clean],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True)
    except OSError:
        return False
    with _lock:
        _proc = p

    limite = _durata_stimata(clean)

    def attendi():
        try:
            p.wait(timeout=limite)
        except subprocess.TimeoutExpired:
            # ha finito di parlare ma non esce: lo si chiude
            for azione in (p.terminate, p.kill):
                try:
                    azione()
                    p.wait(timeout=2)
                    break
                except (OSError, subprocess.SubprocessError):
                    continue
        with _lock:
            global _proc
            if _proc is p:
                _proc = None
        if on_done is not None:
            on_done()

    threading.Thread(target=attendi, daemon=True).start()
    return True


def enabled() -> bool:
    """Preferenza dell'utente: la voce è attiva? (predefinito: no)"""
    path = os.path.expanduser("~/.config/zeta/voce")
    try:
        return open(path).read().strip() == "1"
    except OSError:
        return False


def set_enabled(value: bool) -> None:
    path = os.path.expanduser("~/.config/zeta/voce")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write("1" if value else "0")
