# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA RAYS Intelligence — sintesi vocale offline.

Voce naturale con Piper (sintesi neurale, sul computer): Paola in italiano,
Lessac in inglese. Per le altre lingue espeak-ng, che le ha tutte ma suona
sintetico.

Legge ad alta voce le risposte di ZETA. Tutto in locale: nessun testo
lascia il computer. Se espeak-ng non è installato, `available()` è falso e
ZETA non mostra il pulsante invece di fingere che funzioni.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import threading

from i18n import language, tr

# La voce segue la stessa lingua che il microfono ascolta: sentirsi rispondere
# in italiano dopo aver parlato in inglese e' straniante, e viceversa. La
# decisione sta in un posto solo, voice.lingua_scelta(), che senza scelte
# dell'utente segue la lingua del sistema (i18n.language()).
# espeak-ng (con espeak-ng-data) ha una voce per ogni lingua di ZETA.
def _voce() -> str:
    try:
        from . import voice
        return voice.lingua_scelta()
    except Exception:  # noqa: BLE001 - la voce non deve mai far cadere ZETA
        return language()


VOICE = "en"   # ripiego, se la lingua non si riesce a determinare
SPEED = "165"        # parole al minuto: leggibile, non frettoloso
PITCH = "42"

_lock = threading.Lock()
_proc: subprocess.Popen | None = None


PIPER = "/usr/lib/zeta-piper/piper"
VOCI_DIR = "/usr/share/zeta/voci"
# la voce naturale di ogni lingua (file in VOCI_DIR)
VOCI = {"it": "it_IT-paola-medium", "en": "en_US-lessac-high"}


def _voce_naturale(lingua: str):
    """(modello, frequenza) della voce Piper per la lingua, o None."""
    nome = VOCI.get((lingua or "").split("_")[0])
    if not nome or not os.access(PIPER, os.X_OK) or not shutil.which("pw-play"):
        return None
    modello = os.path.join(VOCI_DIR, nome + ".onnx")
    try:
        with open(modello + ".json", encoding="utf-8") as f:
            rate = int(json.load(f).get("audio", {}).get("sample_rate", 22050))
    except (OSError, ValueError):
        return None
    return (modello, rate) if os.path.isfile(modello) else None


def available() -> bool:
    return _voce_naturale(_voce()) is not None or shutil.which("espeak-ng") is not None


def why_unavailable() -> str:
    if available():
        return ""
    return tr("Text-to-speech isn't installed. "
              "Install it with “sudo apt install espeak-ng” to let ZETA RAYS speak.")


def _clean(text: str) -> str:
    """Toglie ciò che non ha senso pronunciare (codice, elenchi, simboli)."""
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"[*_#>|]+", " ", text)
    text = re.sub(r"https?://\S+", tr("link"), text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:1200]


def stop() -> None:
    """Interrompe la lettura in corso."""
    global _proc
    with _lock:
        p, _proc = _proc, None
    if p and p.poll() is None:
        # tutta la catena (sintesi e riproduzione) e' un gruppo a parte
        try:
            os.killpg(p.pid, signal.SIGTERM)
        except OSError:
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
    naturale = _voce_naturale(_voce())
    try:
        if naturale:
            # l'audio esce mentre viene generato (niente file intermedi)
            modello, rate = naturale
            p = subprocess.Popen(
                ["sh", "-c", '"$0" --model "$1" --output-raw 2>/dev/null '
                 '| pw-play --raw --rate "$2" --channels 1 --format s16 -',
                 PIPER, modello, str(rate)],
                stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, start_new_session=True)
            try:
                p.stdin.write((clean + "\n").encode("utf-8"))
                p.stdin.close()
            except OSError:
                pass
        else:
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
            # ha finito di parlare ma non esce: lo si chiude (tutto il gruppo)
            try:
                os.killpg(p.pid, signal.SIGTERM)
            except OSError:
                pass
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
