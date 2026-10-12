# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA RAYS Intelligence — offline text-to-speech.

Natural voice with Piper (neural synthesis, on the computer): Paola for
Italian, Lessac for English. Other languages use espeak-ng, which covers them
all but sounds synthetic.

Reads ZETA's answers aloud. Everything is local: no text leaves the computer.
If espeak-ng is not installed, `available()` is false and ZETA hides the
button instead of pretending it works.
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

# The voice uses the same language the microphone listens in: getting an
# answer in Italian after speaking English is disorienting, and vice versa.
# The decision lives in a single place, voice.chosen_language(), which follows
# the system language (i18n.language()) unless the user chose otherwise.
# espeak-ng (with espeak-ng-data) has a voice for every ZETA language.
def _voice() -> str:
    try:
        from . import voice
        return voice.chosen_language()
    except Exception:  # noqa: BLE001 - the voice must never bring ZETA down
        return language()


VOICE = "en"   # fallback, if the language cannot be determined
SPEED = "165"        # words per minute: clear, not rushed
PITCH = "42"

_lock = threading.Lock()
_proc: subprocess.Popen | None = None


PIPER = "/usr/lib/zeta-piper/piper"
VOICES_DIR = "/usr/share/zeta/voices"
# the natural voice for each language (files in VOICES_DIR)
VOICES = {"it": "it_IT-paola-medium", "en": "en_US-lessac-high"}


def _natural_voice(lang: str):
    """(model, sample rate) of the Piper voice for the language, or None."""
    name = VOICES.get((lang or "").split("_")[0])
    if not name or not os.access(PIPER, os.X_OK) or not shutil.which("pw-play"):
        return None
    model = os.path.join(VOICES_DIR, name + ".onnx")
    try:
        with open(model + ".json", encoding="utf-8") as f:
            rate = int(json.load(f).get("audio", {}).get("sample_rate", 22050))
    except (OSError, ValueError):
        return None
    return (model, rate) if os.path.isfile(model) else None


def available() -> bool:
    return _natural_voice(_voice()) is not None or shutil.which("espeak-ng") is not None


def why_unavailable() -> str:
    if available():
        return ""
    return tr("Text-to-speech isn't installed. "
              "Install it with “sudo apt install espeak-ng” to let ZETA RAYS speak.")


def _clean(text: str) -> str:
    """Removes what makes no sense to read aloud (code, lists, symbols)."""
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"[*_#>|]+", " ", text)
    text = re.sub(r"https?://\S+", tr("link"), text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:1200]


def stop() -> None:
    """Stops the reading in progress."""
    global _proc
    with _lock:
        p, _proc = _proc, None
    if p and p.poll() is None:
        # the whole pipeline (synthesis and playback) is a separate process group
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


def _estimated_duration(text: str) -> float:
    """How long the reading should take, with a generous margin.

    Used by the watchdog: if the synthesis program hangs after it has
    finished speaking, it must be terminated, otherwise a stuck process stays
    around forever. This happens when the sound card does not report the end
    of playback — typical of virtual machines.
    """
    words = max(1, len(text.split()))
    seconds = words / (float(SPEED) / 60.0)
    return seconds * 1.5 + 3.0


def say(text: str, on_done=None) -> bool:
    """Reads the text without blocking. False if speech synthesis is unavailable."""
    global _proc
    if not available():
        return False
    clean = _clean(text)
    if not clean:
        return False
    stop()
    natural = _natural_voice(_voice())
    try:
        if natural:
            # audio plays while it is being generated (no intermediate files)
            model, rate = natural
            p = subprocess.Popen(
                ["sh", "-c", '"$0" --model "$1" --output-raw 2>/dev/null '
                 '| pw-play --raw --rate "$2" --channels 1 --format s16 -',
                 PIPER, model, str(rate)],
                stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, start_new_session=True)
            try:
                p.stdin.write((clean + "\n").encode("utf-8"))
                p.stdin.close()
            except OSError:
                pass
        else:
            p = subprocess.Popen(
                ["espeak-ng", "-v", _voice() or VOICE, "-s", SPEED, "-p", PITCH, "--", clean],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True)
    except OSError:
        return False
    with _lock:
        _proc = p

    limit = _estimated_duration(clean)

    def wait():
        try:
            p.wait(timeout=limit)
        except subprocess.TimeoutExpired:
            # it finished speaking but does not exit: close it (the whole group)
            try:
                os.killpg(p.pid, signal.SIGTERM)
            except OSError:
                pass
            for operation in (p.terminate, p.kill):
                try:
                    operation()
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

    threading.Thread(target=wait, daemon=True).start()
    return True


def enabled() -> bool:
    """User preference: is the voice on? (default: no)"""
    path = os.path.expanduser("~/.config/zeta/speech")
    try:
        return open(path).read().strip() == "1"
    except OSError:
        return False


def set_enabled(value: bool) -> None:
    path = os.path.expanduser("~/.config/zeta/speech")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write("1" if value else "0")
