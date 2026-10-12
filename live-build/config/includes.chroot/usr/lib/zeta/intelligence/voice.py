# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA RAYS Intelligence — offline speech recognition.

Uses Vosk with a model for the selected language. Everything happens
locally: no audio leaves the computer. If something is missing, `status()`
says exactly what, and ZETA explains it instead of pretending it works.

Points that were given special care:
  • the model is loaded ONCE and stays in memory (loading it for every
    sentence cost seconds of waiting);
  • reading from the microphone can never block: a timeout is used, so a
    microphone that produces no data does not hang ZETA;
  • recording stops as soon as the person has finished speaking, instead of
    always waiting the same number of seconds;
  • the recording process is closed in every case.

Setup:
  1. install Vosk           (pip install vosk, or the ZETA RAYS package)
  2. download a model       into ~/.local/share/zeta/vosk/  or  /usr/share/vosk/
"""
from __future__ import annotations

import array
import json
import os
import select
import shutil
import subprocess
import threading
import time

from i18n import language, tr

# One model per language. Vosk loads only one and cannot tell by itself which
# language it is hearing: the system makes the choice (see chosen_language),
# not guesswork.
MODELS = {
    "it": ["/usr/share/vosk/model-it"],
    "en": ["/usr/share/vosk/model-en"],
}
# Folders searched anyway, for those who add a model by hand.
MODEL_DIRS = [
    os.path.expanduser("~/.local/share/zeta/vosk"),
    "/usr/share/vosk/model-it",
    "/usr/share/vosk/model-en",
    "/usr/share/vosk",
]
LANGUAGE_FILE = os.path.expanduser("~/.config/zeta/voice-language")

RATE = 16000
CHUNK = 3200                 # 0.1 s of audio at 16 kHz mono 16 bit
SPEECH_THRESHOLD = 450            # average level above which there is speech
INITIAL_WAIT = 6.0        # seconds of patience before someone speaks
MAX_DURATION = 15.0        # hard limit: never record forever
END_SILENCE = 1.1          # silence after speech = sentence finished

_model = None
_model_language = None       # language of the loaded model (for the second pass)
_lock = threading.Lock()


# --------------------------------------------------------------- availability
def _is_valid(d: str) -> bool:
    return os.path.isdir(d) and os.path.isfile(os.path.join(d, "conf", "model.conf"))


def available_languages() -> list:
    """The languages for which a model is actually installed."""
    return [lang for lang, dirs in MODELS.items() if any(_is_valid(d) for d in dirs)]


def chosen_language() -> str:
    """The language to listen for: the chosen one, otherwise the system's.

    Someone using the system in English expects the microphone to understand
    English without having to say so. Anyone who wants otherwise writes it
    once in ~/.config/zeta/voice-language. The system language is the one ZETA
    is displayed in (i18n.language()); without a model for it, English is
    preferred.
    """
    try:
        with open(LANGUAGE_FILE) as f:
            choice = f.read().strip().lower()[:2]
        if choice in MODELS and any(_is_valid(d) for d in MODELS[choice]):
            return choice
    except OSError:
        pass
    system_language = language()
    if system_language in MODELS and any(_is_valid(d) for d in MODELS[system_language]):
        return system_language
    available = available_languages()
    if "en" in available:
        return "en"
    return available[0] if available else system_language


def _model_path() -> str | None:
    for d in MODELS.get(chosen_language(), []):
        if _is_valid(d):
            return d
    for d in MODEL_DIRS:
        if _is_valid(d):
            return d
    return None


def _language_of(path: str | None) -> str:
    """The language of a model, from its folder."""
    for lang, dirs in MODELS.items():
        if path in dirs:
            return lang
    return chosen_language()


def _has_vosk() -> bool:
    try:
        import vosk  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


def _recorder() -> list | None:
    """Command that writes raw mono 16 kHz 16-bit audio to stdout."""
    if shutil.which("pw-record"):
        # --raw: without it, a WAV header would be written, which the
        # recognizer would interpret as noise.
        return ["pw-record", "--raw", "--rate=%d" % RATE, "--channels=1",
                "--format=s16", "-"]
    if shutil.which("parec"):
        return ["parec", "--format=s16le", "--rate=%d" % RATE, "--channels=1", "--raw"]
    if shutil.which("arecord"):
        return ["arecord", "-q", "-f", "S16_LE", "-r", str(RATE), "-c", "1", "-t", "raw"]
    return None


def _microphone_present() -> bool:
    """True if the audio system exposes at least one source."""
    try:
        # LC_ALL=C: we look for the "Sources:", "Sinks"... headers
        out = subprocess.run(["wpctl", "status"], capture_output=True, text=True,
                             timeout=4, env=dict(os.environ, LC_ALL="C")).stdout
    except (OSError, subprocess.SubprocessError):
        return True          # without wpctl we cannot tell: do not block
    inside = False
    for line in out.splitlines():
        if "Sources:" in line:
            inside = True
            continue
        if inside:
            if "Filters" in line or "Sinks" in line:
                inside = False
                continue
            if line.strip(" │├─└\t") and any(c.isdigit() for c in line):
                return True
    return False


def status() -> dict:
    """Why speech recognition is or is not available."""
    mic = _recorder() is not None
    return {
        "vosk": _has_vosk(),
        "model": _model_path(),
        "mic": mic,
        "source": mic and _microphone_present(),
        "loaded": _model is not None,
        "available": _has_vosk() and _model_path() is not None and mic,
    }


def available() -> bool:
    return status()["available"]


def why_unavailable() -> str:
    s = status()
    if not s["mic"]:
        return tr("No audio recording tool is available on the system.")
    if not s["vosk"]:
        return tr("The offline speech engine (Vosk) isn't installed. "
                  "Typed commands already work; for voice, install Vosk and "
                  "a model for your language.")
    if not s["model"]:
        return tr("The speech model for your language is missing. Copy it to "
                  "~/.local/share/zeta/vosk/ to enable voice commands.")
    if not s["source"]:
        return tr("No microphone connected.")
    return tr("Speech recognition isn't available.")


# --------------------------------------------------------------------- model
def preload() -> bool:
    """Load the model into memory. Can be called from a background thread."""
    global _model, _model_language
    if _model is not None:
        return True
    if not available():
        return False
    with _lock:
        if _model is not None:
            return True
        try:
            import vosk
            vosk.SetLogLevel(-1)          # no noise on the terminal
            path = _model_path()
            _model = vosk.Model(path)
            _model_language = _language_of(path)
        except Exception:  # noqa: BLE001
            _model = None
            return False
    return True


def _level(data: bytes) -> int:
    """Average level of the audio chunk (0 = silence)."""
    if len(data) < 2:
        return 0
    samples = array.array("h")
    samples.frombytes(data[: len(data) // 2 * 2])
    if not samples:
        return 0
    return int(sum(abs(c) for c in samples) / len(samples))


def _confidence(result: dict) -> float:
    """How confident the engine is about what it understood (0 = not at all)."""
    words = result.get("result") or []
    if not words:
        return 0.0
    values = [p.get("conf", 0.0) for p in words]
    return sum(values) / len(values)


class MicrophoneError(Exception):
    pass


# ------------------------------------------------ second pass for commands
# The small free-vocabulary model often gets precisely the command words
# wrong ("apri firefox" -> "app di firefox", "alza il volume" -> "al volume":
# verified). When the first transcription is not a command, the same audio is
# re-read with a vocabulary restricted to command words and the names of
# installed apps. It is used only if a valid command comes out of it.
# One vocabulary per language: the one of the loaded model is used.
# i18n-data-begin: Italian command vocabulary
_WORDS_IT = """
apri aprimi avvia lancia chiudi esci riavvia riapri passa vai torna mostrami mostra fammi vedere
crea nuova nuovo cerca trova dove elimina cancella sposta copia rinomina metti togli aggiungi
accendi spegni attiva disattiva alza abbassa aumenta diminuisci blocca sospendi riduci icona
ingrandisci schermo intero connetti collegati disconnetti installa disinstalla scarica
il lo la i gli le un una uno di del della dello dei delle nel nella nei sulla sul al alla allo a in
e poi dopo per con da dal dalla chiamata chiamato nome cartella file finestra
volume audio suono muto wifi rete internet bluetooth computer sistema
impostazioni terminale documenti download scaricati immagini foto musica video scrivania cestino
memoria ram cpu processore processi disco spazio batteria stato che ore sono giorno quanta quanto
sto usando lento rallenta dock sfondo tema chiaro scuro schermata screenshot più forte piano luminosità
sito pagina posta email browser editor testo calcolatrice
zero uno due tre quattro cinque sei sette otto nove dieci venti trenta quaranta cinquanta
sessanta settanta ottanta novanta cento percento
""".split()
# i18n-data-end
_WORDS_EN = """
open launch start run close quit exit restart reopen switch go back show me let see
create new make search find where delete remove move copy rename put take add
turn on off enable disable raise lower increase decrease up down lock suspend sleep minimize
maximize full screen fullscreen connect disconnect install uninstall download
the a an of to in on at for with from into and then after called named name folder file window
volume audio sound mute unmute wifi network internet bluetooth computer system
settings terminal documents downloads pictures images photos music videos video desktop trash
memory ram cpu processor processes disk space storage battery status what time is it day date
how much many am i using slow dock wallpaper background theme light dark screenshot louder
quieter brightness site page mail email browser editor text calculator
zero one two three four five six seven eight nine ten twenty thirty forty fifty
sixty seventy eighty ninety hundred percent
""".split()
_COMMAND_WORDS = {"it": _WORDS_IT, "en": _WORDS_EN}


def _vocabulary() -> list:
    words = set(_COMMAND_WORDS.get(_model_language or chosen_language(), _WORDS_EN))
    try:
        from .agent import state
        for a in state.installed_apps():
            if a.is_hidden:
                continue
            for n in list(a.names) + [a.name, a.binary]:
                for w in (n or "").lower().replace("-", " ").split():
                    if w.isalpha() and len(w) > 2:
                        words.add(w)
    except Exception:  # noqa: BLE001 - without app names only the commands are used
        pass
    return sorted(words) + ["[unk]"]


# Only commands with "closed" arguments (an installed app, a known folder, a
# number): the second pass replaces words it does not know with vocabulary
# words, and a file name like "viaggi" became "avvia" (verified). Creating,
# moving, searching or deleting files: never from here.
_VOICE_ACTIONS = {"open_application", "close_application", "restart_application", "focus_application",
            "minimize_window", "maximize_window", "fullscreen_window", "open_folder", "open_settings",
            "set_volume", "set_brightness", "set_theme", "wifi_on", "wifi_off", "wifi_list",
            "network_status", "bluetooth_on", "bluetooth_off", "bluetooth_devices", "system_status",
            "list_processes", "list_running_applications", "current_time", "screenshot", "lock_screen"}


def _valid_command(actions) -> bool:
    """Every app mentioned actually exists (not "chiudi video fox")."""
    from .agent import state
    for _name, args in actions:
        app = args.get("app")
        if app and not state.find_app(app):
            return False
    return True


def _reread_command(audio: bytes, rate: int, first: str) -> tuple:
    """(text, confidence) if the same audio, re-read with only the command
    words, yields a command ZETA understands; otherwise ("", 0)."""
    if not audio or _model is None:
        return "", 0.0
    try:
        import vosk
        from .agent.understanding import understanding
        from .agent import capabilities
        vosk.SetLogLevel(-2)        # words missing from the model: useless warnings
        k = vosk.KaldiRecognizer(_model, rate, json.dumps(_vocabulary(), ensure_ascii=False))
        k.SetWords(True)
        k.AcceptWaveform(bytes(audio))
        r = json.loads(k.FinalResult())
    except Exception:  # noqa: BLE001
        return "", 0.0
    text = (r.get("text") or "").strip()
    conf = _confidence(r)
    if not text or "[unk]" in text or conf < 0.6:
        return "", 0.0
    actions = understanding(text)
    if not actions or any(n not in _VOICE_ACTIONS for n, _a in actions) or not _valid_command(actions):
        return "", 0.0
    # There must be a link with what was heard first (a word in common),
    # unless the command is a simple read-only query ("che ore sono").
    common_words = {w for w in text.split() if len(w) > 3} & {w for w in first.lower().split() if len(w) > 3}
    read_only = all(capabilities.REGISTRY[n].risk == "read" for n, _a in actions if n in capabilities.REGISTRY)
    if not common_words and not read_only:
        return "", 0.0
    return text, conf


def transcribe(audio: bytes, rate: int = RATE) -> tuple:
    """(text, confidence) of already recorded audio (16-bit mono)."""
    if not preload():
        return "", 0.0
    import vosk
    k = vosk.KaldiRecognizer(_model, rate)
    k.SetWords(True)
    k.AcceptWaveform(bytes(audio))
    try:
        r = json.loads(k.FinalResult())
    except ValueError:
        return "", 0.0
    return _choose(r, audio, rate)


def _choose(result: dict, audio: bytes, rate: int) -> tuple:
    text = (result.get("text") or "").strip()
    conf = _confidence(result)
    try:
        from .agent.understanding import understanding
        actions = understanding(text) if text else None
        # a valid command is kept; "al volume" (without "alza") is almost
        # always a lost verb: re-read it
        if actions and _valid_command(actions) and not (
                len(actions) == 1 and actions[0][0] in ("set_volume", "set_brightness") and not actions[0][1]):
            return text, conf
    except Exception:  # noqa: BLE001
        return text, conf
    alt, conf_alt = _reread_command(audio, rate, text)
    return (alt, conf_alt) if alt else (text, conf)


class Recognizer:
    """Record a sentence and transcribe it. Never blocks indefinitely."""

    def __init__(self, wait: float = INITIAL_WAIT,
                 maximum: float = MAX_DURATION,
                 silence: float = END_SILENCE):
        self.wait = wait
        self.maximum = maximum
        self.silence = silence

    def listen(self, on_state=None) -> str:
        """Return the recognized text ("" if nothing was understood).

        on_state, if given, receives "idle" | "listening" | "processing".
        """
        if not preload():
            raise MicrophoneError(why_unavailable())
        import vosk

        command = _recorder()
        try:
            proc = subprocess.Popen(command, stdout=subprocess.PIPE,
                                    stderr=subprocess.DEVNULL)
        except OSError as e:
            raise MicrophoneError(tr("Can't open the microphone: {error}").format(error=e)) from e

        kaldi = vosk.KaldiRecognizer(_model, RATE)
        kaldi.SetWords(True)        # needed to know how confident the result is
        audio = bytearray()         # for the second pass (see _reread_command)
        start = time.monotonic()
        last_speech = None
        has_spoken = False
        if on_state:
            on_state("idle")
        try:
            while True:
                now = time.monotonic()
                if now - start > self.maximum:
                    break
                if not has_spoken and now - start > self.wait:
                    break                      # nobody spoke
                if has_spoken and last_speech and now - last_speech > self.silence:
                    break                      # sentence finished
                # read with a timeout: a silent microphone must not block us
                ready, _, _ = select.select([proc.stdout], [], [], 0.25)
                if not ready:
                    continue
                data = proc.stdout.read(CHUNK)
                if not data:
                    break
                if _level(data) >= SPEECH_THRESHOLD:
                    if not has_spoken and on_state:
                        on_state("listening")
                    has_spoken = True
                    last_speech = time.monotonic()
                kaldi.AcceptWaveform(data)
                audio.extend(data)
        finally:
            try:
                proc.terminate()
                proc.wait(timeout=2)
            except (OSError, subprocess.SubprocessError):
                try:
                    proc.kill()
                except OSError:
                    pass

        if not has_spoken:
            return ""
        if on_state:
            on_state("processing")
        try:
            result = json.loads(kaldi.FinalResult())
        except ValueError:
            return ""
        text, self.last_confidence = _choose(result, audio, RATE)
        return text

    last_confidence = 0.0
