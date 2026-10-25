# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA RAYS Intelligence — offline text-to-speech.

Natural voices, computed on the computer: Sara (Kokoro) for Italian, with
Serena and Paola (Piper) as alternatives; Lessac (Piper) for English. Other
languages use espeak-ng, which covers them all but sounds synthetic.

Reads ZETA's answers aloud, on by default since 2.5. Everything is local: no
text leaves the computer. If neither Piper nor espeak-ng is usable,
`available()` is false and ZETA hides the button instead of pretending it
works.

Two ways in: say(text) reads a finished text (previews, "read again");
Stream reads a reply while the model is still writing it, sentence by
sentence, so the voice starts with the first sentence. One reading at a
time: a new one stops the previous one (stop(), pause(), resume()).

Before synthesis the reply goes through speech_text.normalize(): Markdown,
URLs and emoji are removed, numbers, times, dates and units become words.
Settings › AI › Voice chooses the voice and the speaking speed; the choice is
stored in ~/.config/zeta/speech.json.
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import shutil
import signal
import subprocess
import threading

from i18n import language, tr
from i18n_data import load

from .speech_text import normalize


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
SPEED = "165"        # espeak-ng words per minute: clear, not rushed
PITCH = "42"

_lock = threading.Lock()
_proc: "_Reading | None" = None

PIPER = "/usr/lib/zeta-piper/piper"
KOKORO = "/usr/libexec/zeta-kokoro"
VOICES_DIR = "/usr/share/zeta/voices"
SETTINGS = os.path.expanduser("~/.config/zeta/speech.json")

# The default natural voice of each language (files in VOICES_DIR). The
# choice is backed by tools/voice-bench (intelligibility measured with a
# speech recognizer, speed, size, license).
# A Kokoro voice is a small description file, <name>.onnx.json with
# "engine": "kokoro" (the model is shared, in VOICES_DIR/kokoro).
VOICES = {"it": "it_IT-sara-kokoro", "en": "en_US-lessac-high"}
# Kokoro needs about 400 MB while it reads: with less free memory than this
# the next voice of the language (Piper, about 100 MB) reads instead.
KOKORO_MIN_FREE_MB = 900

# Synthesis settings per voice: pace (length_scale, > 1 is slower), the
# variation of the voice (noise_scale) and of the rhythm (noise_w), and the
# pause after each sentence in seconds. Tuned with tools/voice-bench.
TUNING = {
    # model default 1.0/0.6/0.4: average WER 4.2% over 5 runs; 1.05/0.4-0.5/0.3
    # was clearer (WER 2.8%) with the same predicted MOS (4.4)
    "it_IT-serena-high": {"length_scale": 1.05, "noise_scale": 0.5, "noise_w": 0.3,
                          "sentence_silence": 0.25},
    "it_IT-serena-medium": {"length_scale": 1.05, "noise_scale": 0.5, "noise_w": 0.3,
                            "sentence_silence": 0.25},
    # model default 1.0/0.8/0.8: WER 5.5-9.2%; tuned: 1.8%
    "it_IT-paola-medium": {"length_scale": 1.05, "noise_scale": 0.5, "noise_w": 0.5,
                           "sentence_silence": 0.25},
    "en_US-lessac-high": {"length_scale": 1.0, "noise_scale": 0.667, "noise_w": 0.8,
                          "sentence_silence": 0.2},
    # Kokoro: the model's own pace; the pause is the one kokoro-onnx uses
    "it_IT-sara-kokoro": {"length_scale": 1.0, "sentence_silence": 0.25},
}

# Speaking speed chosen in Settings: a factor on the voice's length_scale.
SPEEDS = {"slow": 1.15, "normal": 1.0, "fast": 0.87}
# Volume of the voice (Settings › AI › Voice), relative to the system volume
VOLUMES = (25, 50, 75, 100)

# Silence played before the first word. When the sound card wakes up from
# power saving, the first tenths of a second can be lost: the reply would
# start mid-word.
LEAD_IN = 0.25
# A larger pipe between synthesis and playback: Piper is never blocked while
# the previous sentence plays, so the next one is ready in time (no gaps).
PIPE_SIZE = 1 << 20


# --- settings ------------------------------------------------------------
def _settings() -> dict:
    try:
        with open(SETTINGS, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_settings(data: dict) -> None:
    os.makedirs(os.path.dirname(SETTINGS), exist_ok=True)
    tmp = SETTINGS + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)
    os.replace(tmp, SETTINGS)


def _voice_config(name: str) -> dict:
    try:
        with open(os.path.join(VOICES_DIR, name + ".onnx.json"), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _kokoro_ready() -> bool:
    try:
        from . import kokoro
        return os.access(KOKORO, os.X_OK) and kokoro.available()
    except Exception:  # noqa: BLE001 - the voice must never bring ZETA down
        return False


def _usable(name: str) -> bool:
    """A Piper voice needs its model; a Kokoro voice needs Kokoro."""
    if os.path.isfile(os.path.join(VOICES_DIR, name + ".onnx")):
        return True
    return _voice_config(name).get("engine") == "kokoro" and _kokoro_ready()


def installed_voices(lang: str) -> list[str]:
    """Names of the natural voices installed for a language, default first."""
    prefix = (lang or "").split("_")[0] + "_"
    try:
        names = sorted(f[:-10] for f in os.listdir(VOICES_DIR)
                       if f.startswith(prefix) and f.endswith(".onnx.json"))
    except OSError:
        return []
    names = [n for n in names if _usable(n)]
    default = VOICES.get(prefix[:-1])
    return sorted(names, key=lambda n: (n != default, n))


def voice_label(name: str) -> str:
    """"Serena · high quality" for it_IT-serena-high."""
    parts = name.split("-")
    if len(parts) < 3:
        return name
    quality = {"high": tr("high quality"), "medium": tr("medium quality"),
               "low": tr("low quality"), "x_low": tr("low quality"),
               "kokoro": "Kokoro"}.get(parts[2], parts[2])
    return "%s · %s" % (parts[1].capitalize(), quality)


def chosen_voice(lang: str) -> str | None:
    """The voice the user chose for the language, else the default, else any."""
    base = (lang or "").split("_")[0]
    installed = installed_voices(base)
    choice = _settings().get("voices", {}).get(base)
    if choice in installed:
        return choice
    return installed[0] if installed else None


def set_voice(lang: str, name: str) -> None:
    data = _settings()
    data.setdefault("voices", {})[(lang or "").split("_")[0]] = name
    _save_settings(data)


def speed() -> str:
    value = _settings().get("speed", "normal")
    return value if value in SPEEDS else "normal"


def set_speed(value: str) -> None:
    if value not in SPEEDS:
        raise ValueError(value)
    data = _settings()
    data["speed"] = value
    _save_settings(data)


def volume() -> int:
    value = _settings().get("volume", 100)
    return value if value in VOLUMES else 100


def set_volume(value: int) -> None:
    if value not in VOLUMES:
        raise ValueError(value)
    data = _settings()
    data["volume"] = value
    _save_settings(data)


# --- availability ----------------------------------------------------------
def _free_mb() -> int:
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) // 1024
    except (OSError, ValueError, IndexError):
        pass
    return 1 << 20


def _natural_voice(lang: str, name: str | None = None):
    """The natural voice that will read, as a dict (name, engine, model, rate,
    config), or None. A Kokoro voice gives way to the next voice of the
    language when memory is short."""
    name = name or chosen_voice(lang)
    if not name or not shutil.which("pw-play"):
        return None
    cfg = _voice_config(name)
    rate = int(cfg.get("audio", {}).get("sample_rate", 22050) or 22050)
    if cfg.get("engine") == "kokoro":
        if _kokoro_ready() and _free_mb() >= KOKORO_MIN_FREE_MB:
            return {"name": name, "engine": "kokoro", "rate": rate, "config": cfg}
        others = [n for n in installed_voices(lang)
                  if n != name and _voice_config(n).get("engine") != "kokoro"]
        return _natural_voice(lang, others[0]) if others else None
    model = os.path.join(VOICES_DIR, name + ".onnx")
    if not os.access(PIPER, os.X_OK) or not os.path.isfile(model):
        return None
    return {"name": name, "engine": "piper", "model": model, "rate": rate, "config": cfg}


def available() -> bool:
    return _natural_voice(_voice()) is not None or shutil.which("espeak-ng") is not None


def why_unavailable() -> str:
    if available():
        return ""
    return tr("Text-to-speech isn't installed. "
              "Install it with “sudo apt install espeak-ng” to let ZETA RAYS speak.")


def _clean(text: str, lang: str = "en") -> str:
    """The words to read aloud: no code, Markdown, symbols; numbers as words."""
    text = (text or "")[:4000]
    if len(text) == 4000:                 # cut at the end of a sentence
        end = max(text.rfind(". "), text.rfind("! "), text.rfind("? "), text.rfind("\n"))
        text = text[:end + 1] if end > 1000 else text
    return normalize(text, lang)


def piper_options(name: str, speed_name: str | None = None) -> list[str]:
    """Command-line options of the Piper binary for a voice at a speed."""
    tuning = TUNING.get(name, {})
    length = tuning.get("length_scale", 1.0) * SPEEDS.get(speed_name or speed(), 1.0)
    options = ["--length_scale", "%.3f" % length]
    for key in ("noise_scale", "noise_w", "sentence_silence"):
        if key in tuning:
            options += ["--" + key, str(tuning[key])]
    return options


# --- reading -------------------------------------------------------------
class _Reading:
    """A reading in progress: synthesis and playback, one process group."""

    def __init__(self, group: int, waited: subprocess.Popen, others=()):
        self.group = group
        self.waited = waited          # done when this process ends (playback)
        self.others = list(others)

    def running(self) -> bool:
        return self.waited.poll() is None

    def signal(self, sig) -> None:
        try:
            os.killpg(self.group, sig)
        except OSError:
            pass

    def kill(self) -> None:
        try:
            os.killpg(self.group, signal.SIGTERM)
        except OSError:
            for p in [self.waited] + self.others:
                try:
                    p.terminate()
                except OSError:
                    pass

    def reap(self) -> None:
        for p in self.others:
            try:
                p.wait(timeout=2)
            except (OSError, subprocess.SubprocessError):
                try:
                    p.kill()
                except OSError:
                    pass


def stop() -> None:
    """Stops the reading in progress (immediately: the whole group is killed)."""
    global _proc, _paused
    with _lock:
        r, _proc = _proc, None
        _paused = False
    if r and r.running():
        r.signal(signal.SIGCONT)          # a stopped process can't act on SIGTERM
        r.kill()


_paused = False


def pause() -> bool:
    """Pauses the reading (synthesis and playback are suspended)."""
    global _paused
    with _lock:
        r = _proc
        if r is None or not r.running() or _paused:
            return False
        _paused = True
    r.signal(signal.SIGSTOP)
    return True


def resume() -> bool:
    global _paused
    with _lock:
        r = _proc
        if r is None or not _paused:
            return False
        _paused = False
    r.signal(signal.SIGCONT)
    return True


def paused() -> bool:
    with _lock:
        return _paused and _proc is not None


def speaking() -> bool:
    with _lock:
        return _proc is not None and _proc.running()


def kokoro_options(name: str, cfg: dict, speed_name: str | None = None) -> list[str]:
    """Command-line options of zeta-kokoro for a voice at a speed."""
    tuning = TUNING.get(name, {})
    length = tuning.get("length_scale", 1.0) * SPEEDS.get(speed_name or speed(), 1.0)
    k = cfg.get("kokoro", {})
    return ["--voice", str(k.get("voice", "if_sara")), "--espeak", str(k.get("espeak", "it")),
            "--speed", "%.3f" % (1.0 / length),
            "--pause", str(tuning.get("sentence_silence", 0.25))]


def _estimated_duration(text: str) -> float:
    """How long the reading should take, with a generous margin.

    Used by the watchdog: if the synthesis program hangs after it has
    finished speaking, it must be terminated, otherwise a stuck process stays
    around forever. This happens when the sound card does not report the end
    of playback — typical of virtual machines.
    """
    words = max(1, len(text.split()))
    seconds = words / (float(SPEED) / 60.0) * SPEEDS["slow"]
    return seconds * 1.5 + 3.0 + LEAD_IN


def _start_voice(voice: dict, text: str | None):
    """Synthesis → pipe → pw-play: audio plays while it is being generated.

    With text None the synthesis program is left waiting for lines on its
    standard input, which is returned with the reading (Stream)."""
    rate, name = voice["rate"], voice["name"]
    if voice["engine"] == "kokoro":
        command = [KOKORO] + kokoro_options(name, voice["config"])
    else:
        command = [PIPER, "--model", voice["model"], "--output_raw", "-q"] + piper_options(name)
    read_end, write_end = os.pipe()
    try:
        try:
            fcntl.fcntl(write_end, fcntl.F_SETPIPE_SZ, PIPE_SIZE)
        except (OSError, AttributeError):
            pass                          # the default pipe works too
        os.write(write_end, b"\0" * (int(rate * LEAD_IN) * 2))
        # a little below the desktop's priority: the voice must never make
        # the windows stutter (the language model runs at the same level)
        if shutil.which("nice"):
            command = ["nice", "-n", "5"] + command
        synth = subprocess.Popen(
            command, stdin=subprocess.PIPE, stdout=write_end, stderr=subprocess.DEVNULL,
            process_group=0)
        try:
            player = subprocess.Popen(
                ["pw-play", "--raw", "--rate", str(rate), "--channels", "1",
                 "--format", "s16", "--volume", "%.2f" % (volume() / 100.0), "-"],
                stdin=read_end, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                process_group=synth.pid)
        except OSError:
            synth.kill()
            raise
    finally:
        os.close(read_end)
        os.close(write_end)
    reading = _Reading(synth.pid, player, [synth])
    if text is None:
        return reading, synth.stdin
    try:
        synth.stdin.write((text.replace("\n", " ") + "\n").encode("utf-8"))
        synth.stdin.close()
    except OSError:
        pass
    return reading


def say(text: str, on_done=None, lang: str | None = None, voice_name: str | None = None) -> bool:
    """Reads the text without blocking. False if speech synthesis is unavailable.

    lang and voice_name are for previews (Settings): by default the language
    is the one ZETA listens in and the voice is the user's choice."""
    global _proc
    lang = (lang or _voice() or VOICE).split("_")[0]
    natural = _natural_voice(lang, voice_name)
    if natural is None and shutil.which("espeak-ng") is None:
        return False
    clean = _clean(text, lang)
    if not clean:
        return False
    stop()
    try:
        reading = _start_voice(natural, clean) if natural else _espeak(clean, lang)
    except OSError:
        return False
    with _lock:
        _proc = reading

    limit = _estimated_duration(clean)
    if natural and natural["engine"] == "kokoro":
        # loading the model takes a few seconds, and an old processor may
        # compute little faster than it speaks
        limit = limit * 2 + 15
    _watch(reading, limit, on_done)
    return True


def _watch(reading: _Reading, limit: float, on_done=None) -> None:
    """Wait for the reading to end (in a thread), with a watchdog."""
    def wait():
        try:
            reading.waited.wait(timeout=limit)
        except subprocess.TimeoutExpired:
            # it finished speaking but does not exit: close it (the whole group)
            reading.kill()
            for operation in (reading.waited.terminate, reading.waited.kill):
                try:
                    operation()
                    reading.waited.wait(timeout=2)
                    break
                except (OSError, subprocess.SubprocessError):
                    continue
        if reading.waited.returncode not in (0, None):
            reading.kill()                # playback failed: do not leave Piper behind
        reading.reap()
        with _lock:
            global _proc
            if _proc is reading:
                _proc = None
        if on_done is not None:
            on_done()

    threading.Thread(target=wait, daemon=True).start()


def _espeak(text: str, lang: str) -> _Reading:
    espeak_speed = str(int(int(SPEED) / SPEEDS[speed()]))
    amplitude = str(int(100 * volume() / 100))
    p = subprocess.Popen(
        ["espeak-ng", "-v", lang, "-s", espeak_speed, "-p", PITCH, "-a", amplitude, "--", text],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, process_group=0)
    return _Reading(p.pid, p)


def sample_sentence(lang: str) -> str:
    """What the voice says in the Settings preview."""
    if (lang or "").startswith("it"):
        return load("speech")["preview"]["it"]
    return "Hi, I'm ZETA. It's 2:30 PM and the Wi-Fi is on."


def enabled() -> bool:
    """User preference: is the voice on? On by default since 2.5 (text and
    voice together); a choice the user made earlier ("0") is kept."""
    path = os.path.expanduser("~/.config/zeta/speech")
    try:
        return open(path).read().strip() != "0"
    except OSError:
        return True


def set_enabled(value: bool) -> None:
    path = os.path.expanduser("~/.config/zeta/speech")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write("1" if value else "0")



# --- a reply read while it is written ------------------------------------
# Where a reply can be cut into lines for the voice: after the end of a
# sentence (with any closing quote or bracket) or at a line break.
_CUT = re.compile(r"(?<=[.!?…:;])[\"'»”)\]]*\s+|\n+")
FIRST_PIECE = 12      # characters: a shorter first sentence waits for more
PIECE = 60            # later lines: fewer, longer lines sound more natural


class Stream:
    """A reply read aloud while the model is still writing it.

    prepare() starts the voice at once, so its model loads while the
    language model works; feed() receives the reply as it arrives, and every
    finished sentence is cleaned (speech_text.normalize) and written to the
    synthesis program as one line. Piper and zeta-kokoro synthesize line by
    line and pw-play plays while the next line is computed: the voice starts
    after the first sentence instead of after the whole reply. Code blocks
    are skipped. finish() says what is left; cancel() stops everything.
    """

    def __init__(self, lang: str | None = None, on_done=None):
        self.lang = (lang or _voice() or VOICE).split("_")[0]
        self.on_done = on_done
        self._raw = ""            # received, not yet spoken
        self._fenced = False      # inside a ``` code block
        self._spoken = ""         # everything given to the voice
        self._reading: _Reading | None = None
        self._stdin = None
        self._engine = ""
        self._espeak_text: list[str] | None = None
        self._closed = False
        self._lock = threading.Lock()

    def prepare(self) -> bool:
        """Start the voice now. False when no voice can read."""
        global _proc
        natural = _natural_voice(self.lang)
        stop()
        if natural is None:
            if shutil.which("espeak-ng") is None:
                return False
            self._espeak_text = []          # espeak-ng reads the whole text at the end
            return True
        try:
            self._reading, self._stdin = _start_voice(natural, None)
        except OSError:
            return False
        self._engine = natural["engine"]
        with _lock:
            _proc = self._reading
        return True

    def feed(self, chunk: str) -> None:
        with self._lock:
            if self._closed:
                return
            self._raw += chunk or ""
            self._flush(final=False)

    def finish(self) -> None:
        """The reply is complete: say what is left, then let the voice end."""
        global _proc
        with self._lock:
            if self._closed:
                return
            self._flush(final=True)
            self._closed = True
        if self._espeak_text is not None:
            text = " ".join(self._espeak_text).strip()
            if not text:
                if self.on_done:
                    self.on_done()
                return
            try:
                reading = _espeak(text, self.lang)
            except OSError:
                if self.on_done:
                    self.on_done()
                return
            with _lock:
                _proc = reading
            _watch(reading, _estimated_duration(text), self.on_done)
            return
        if self._stdin is not None:
            try:
                self._stdin.close()
            except OSError:
                pass
        if self._reading is None:
            if self.on_done:
                self.on_done()
            return
        limit = _estimated_duration(self._spoken)
        if self._engine == "kokoro":
            limit = limit * 2 + 15
        _watch(self._reading, limit + 15, self.on_done)

    def cancel(self) -> None:
        with self._lock:
            self._closed = True
        with _lock:
            mine = _proc is self._reading and self._reading is not None
        if mine:
            stop()

    @property
    def spoken(self) -> str:
        return self._spoken.strip()

    # --- text to lines -----------------------------------------------------
    def _flush(self, final: bool) -> None:
        while True:
            cut = self._next_cut(final)
            if cut is None:
                return
            piece, self._raw = self._raw[:cut], self._raw[cut:]
            self._say_piece(piece)

    def _next_cut(self, final: bool):
        if not self._raw.strip():
            if final:
                self._raw = ""
            return None
        minimum = FIRST_PIECE if not self._spoken else PIECE
        for m in _CUT.finditer(self._raw):
            if m.end() >= minimum and not self._inside_code(self._raw[:m.end()]):
                return m.end()
        return len(self._raw) if final else None

    def _inside_code(self, text: str) -> bool:
        return (int(self._fenced) + text.count("```")) % 2 == 1

    def _say_piece(self, piece: str) -> None:
        from .context import NOTE_ECHO
        if NOTE_ECHO.fullmatch(piece):               # the model copied ZETA's note back
            return
        raw = ("```" + piece) if self._fenced else piece   # a code block still open
        self._fenced = (int(self._fenced) + piece.count("```")) % 2 == 1
        clean = normalize(raw, self.lang)
        if not clean:
            return
        self._spoken += " " + clean
        if self._espeak_text is not None:
            self._espeak_text.append(clean)
            return
        try:
            self._stdin.write((clean + "\n").encode("utf-8"))
            self._stdin.flush()
        except (OSError, ValueError, AttributeError):
            pass                                # stopped meanwhile
