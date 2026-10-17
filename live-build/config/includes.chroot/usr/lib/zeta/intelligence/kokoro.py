# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA RAYS Intelligence — Kokoro, the natural Italian voice (Sara).

Kokoro-82M (Apache-2.0) is a neural speech model; ZETA runs its int8 ONNX
export on the processor with Debian's onnxruntime. Text becomes phonemes
with espeak-ng (the library already in the system), phonemes become token
ids, and the model turns them into 24 kHz audio, one sentence at a time so
the reading starts while the rest is still being computed.

The phoneme step follows what the kokoro-onnx package does through
phonemizer (espeak backend, punctuation preserved, stress marks kept): the
voice was chosen by listening to samples made that way, so the same text must
give the same phonemes here (checked by tools/voice-bench/kokoro-check.py).
Only the parts of those projects that ZETA needs are reproduced, with Debian
packages only: no Python packages from outside the distribution.

Used by /usr/libexec/zeta-kokoro, a separate process: the speech module
stops a reading by ending that process, and the model's memory (about 400
MB) is freed as soon as the reading ends.
"""
from __future__ import annotations

import ctypes
import ctypes.util
import json
import os
import re

MODEL_DIR = "/usr/share/zeta/voices/kokoro"
MODEL = os.path.join(MODEL_DIR, "kokoro-v1.0.int8.onnx")
VOICES = os.path.join(MODEL_DIR, "voices-v1.0.bin")
VOCAB = os.path.join(MODEL_DIR, "vocab.json")
SAMPLE_RATE = 24000
MAX_PHONEMES = 510          # the model's context, in phonemes
SENTENCE_MARKS = ".!?…"
CLAUSE_MARKS = ",;:"


def available() -> bool:
    """True when the model files, onnxruntime and espeak-ng are all present."""
    import importlib.util
    return (all(os.path.isfile(p) for p in (MODEL, VOICES, VOCAB))
            and importlib.util.find_spec("onnxruntime") is not None
            and importlib.util.find_spec("numpy") is not None
            and ctypes.util.find_library("espeak-ng") is not None)


# --- text to phonemes (espeak-ng) -------------------------------------------
class Espeak:
    """espeak-ng's phonemizer, called through its C library."""

    def __init__(self, voice: str):
        path = ctypes.util.find_library("espeak-ng")
        if not path:
            raise RuntimeError("espeak-ng library not found")
        self._lib = ctypes.cdll.LoadLibrary(path)
        # AUDIO_OUTPUT_SYNCHRONOUS, no buffer, default data path, no options
        if self._lib.espeak_Initialize(0x02, 0, None, 0) <= 0:
            raise RuntimeError("espeak-ng did not start")
        self._lib.espeak_SetVoiceByName.argtypes = [ctypes.c_char_p]
        if self._lib.espeak_SetVoiceByName(voice.encode("utf-8")) != 0:
            raise RuntimeError("espeak-ng has no voice %r" % voice)
        self._ttp = self._lib.espeak_TextToPhonemes
        self._ttp.restype = ctypes.c_char_p
        self._ttp.argtypes = [ctypes.POINTER(ctypes.c_char_p), ctypes.c_int, ctypes.c_int]

    def text_to_phonemes(self, text: str) -> str:
        """IPA phonemes separated by "_", words by spaces; espeak returns one
        clause per call and advances the pointer until the text ends."""
        ptr = ctypes.pointer(ctypes.c_char_p(text.encode("utf-8")))
        mode = ord("_") << 8 | 0x02          # IPA, "_" between phonemes
        out = []
        while ptr.contents.value is not None:
            ph = self._ttp(ptr, 1, mode)      # 1: UTF-8 input
            if ph:
                out.append(ph.decode("utf-8"))
        return " ".join(out)


# Punctuation is invisible to espeak-ng: it is cut out of the text before the
# phonemes are computed and put back afterwards, so the model sees it and
# pauses or changes intonation (same marks and placement as phonemizer).
_MARKS = ';:,.!?¡¿—…"«»“”(){}[]'
_MARKS_RE = re.compile(r"(\s*[%s]+\s*)+" % re.escape(_MARKS))


def _preserve(line: str):
    """"hello, my world!" -> ["hello", "my world"], [(", ", "I"), ("!", "E")]."""
    matches = list(_MARKS_RE.finditer(line))
    if not matches:
        return [line], []
    if len(matches) == 1 and matches[0].group() == line:
        return [], [(line, "A")]
    marks = []
    for m in matches:
        where = "I"
        if m is matches[0] and line.startswith(m.group()):
            where = "B"
        elif m is matches[-1] and line.endswith(m.group()):
            where = "E"
        marks.append((m.group(), where))
    chunks = []
    for mark, _where in marks:
        head, _, line = line.partition(mark)
        chunks.append(head)
    return [c for c in chunks + [line] if c], marks


def _restore(chunks: list, marks: list) -> list:
    """The reverse of _preserve on the phonemized chunks (word separator " ").

    All marks of a line carry the line's index (0) in phonemizer: after the
    first chunk that ends with a mark, the remaining marks are no longer
    matched to a chunk and are appended at the end. Reproduced as is."""
    out, pos = [], 0
    marks = [(0, m, w) for m, w in marks]
    while chunks or marks:
        if not marks:
            out += [c if c.endswith(" ") else c + " " for c in chunks]
            chunks = []
        elif not chunks:
            out.append("".join(m for _, m, _ in marks))
            marks = []
        else:
            index, mark, where = marks[0]
            if index != pos:
                out.append(chunks[0])
                chunks = chunks[1:]
                pos += 1
                continue
            marks = marks[1:]
            if chunks[0].endswith(" "):
                chunks[0] = chunks[0][:-1]
            if where == "B":
                chunks[0] = mark + chunks[0]
            elif where == "E":
                out.append(chunks[0] + mark + ("" if mark.endswith(" ") else " "))
                chunks = chunks[1:]
                pos += 1
            elif where == "A":
                out.append(mark + ("" if mark.endswith(" ") else " "))
                pos += 1
            elif len(chunks) == 1:
                chunks[0] = chunks[0] + mark
            else:
                first = chunks[0]
                chunks = chunks[1:]
                chunks[0] = first + mark + chunks[0]
    return out


def _clean_line(raw: str) -> str:
    """espeak's output for one chunk: words followed by a space, without the
    "_" between phonemes; stress marks and language flags such as "(en)"
    are kept (the model's vocabulary drops what it does not know)."""
    line = raw.strip().replace("\n", " ").replace("  ", " ")
    line = re.sub(r"_+", "_", line)
    line = re.sub(r"_ ", " ", line)
    if not line:
        return ""
    return "".join(w.strip().replace("_", "") + " " for w in line.split(" "))


def phonemize(espeak: Espeak, text: str, vocab: dict) -> str:
    """The phonemes of `text` that the model knows, spaces collapsed."""
    lines = [ln.strip("\n") for ln in text.strip("\n").split("\n")]
    out = []
    for line in (ln for ln in lines if ln.strip()):
        chunks, marks = _preserve(line)
        out += _restore([_clean_line(espeak.text_to_phonemes(c)) for c in chunks], marks)
    phonemes = "".join(p for p in "\n".join(out) if p in vocab).strip()
    return " ".join(phonemes.split())


# --- splitting ------------------------------------------------------------
_SENTENCE_END = re.compile(r"(?<=[.!?…])\s+|\n+")


def sentences(text: str) -> list[str]:
    """The text cut into sentences: each one is synthesized and played while
    the next is computed."""
    return [s.strip() for s in _SENTENCE_END.split(text or "") if s.strip()]


def split_phonemes(phonemes: str, limit: int = MAX_PHONEMES) -> list[str]:
    """Pieces within the model's context: at clause marks, then at spaces,
    and only as a last resort in the middle of a word."""
    if len(phonemes) <= limit:
        return [phonemes] if phonemes else []
    for boundary in (r"(?<=[%s])\s+" % re.escape(CLAUSE_MARKS + SENTENCE_MARKS), r"\s+"):
        parts = re.split(boundary, phonemes)
        if len(parts) > 1:
            pieces, cur = [], ""
            for p in parts:
                if cur and len(cur) + 1 + len(p) > limit:
                    pieces.append(cur)
                    cur = p
                else:
                    cur = "%s %s" % (cur, p) if cur else p
            if cur:
                pieces.append(cur)
            return [q for piece in pieces for q in split_phonemes(piece, limit)]
    return [phonemes[i:i + limit] for i in range(0, len(phonemes), limit)]


# --- phonemes to audio ----------------------------------------------------
class Synth:
    """The loaded model with one voice."""

    def __init__(self, voice: str, espeak_voice: str):
        import numpy as np
        import onnxruntime as rt
        self.np = np
        opts = rt.SessionOptions()
        opts.log_severity_level = 3          # no warnings on the terminal
        self.sess = rt.InferenceSession(MODEL, sess_options=opts,
                                        providers=["CPUExecutionProvider"])
        styles = np.load(VOICES)
        if voice not in styles:
            raise RuntimeError("Kokoro has no voice %r" % voice)
        self.style = styles[voice]
        with open(VOCAB, encoding="utf-8") as f:
            self.vocab = json.load(f)
        self.espeak = Espeak(espeak_voice)
        inputs = {i.name: i.type for i in self.sess.get_inputs()}
        # older exports name the token input "tokens", newer ones "input_ids"
        self.tokens_input = "input_ids" if "input_ids" in inputs else "tokens"
        self.speed_type = np.int32 if inputs.get("speed") == "tensor(int32)" else np.float32

    def phonemes(self, text: str) -> str:
        return phonemize(self.espeak, text, self.vocab)

    def audio(self, phonemes: str, speed: float = 1.0):
        """float32 samples for phonemes within the context (MAX_PHONEMES)."""
        np = self.np
        tokens = [self.vocab[p] for p in phonemes if p in self.vocab]
        if not tokens:
            return np.zeros(0, dtype=np.float32)
        style = self.style[min(len(tokens), len(self.style)) - 1]
        out = self.sess.run(None, {
            self.tokens_input: np.array([[0, *tokens, 0]], dtype=np.int64),
            "style": np.asarray(style, dtype=np.float32),
            "speed": np.array([speed], dtype=self.speed_type)})
        return trim(np, np.asarray(out[0], dtype=np.float32).ravel())


def trim(np, audio, top_db: float = 60.0, frame: int = 2048, hop: int = 512):
    """Leading and trailing silence removed (frames 60 dB below the loudest,
    as librosa.effects.trim, which kokoro-onnx follows): the pauses between
    sentences are then the ones ZETA adds, the same every time."""
    if audio.size < frame:
        return audio
    padded = np.pad(audio, frame // 2)
    n = 1 + (padded.size - frame) // hop
    idx = np.arange(frame)[None, :] + hop * np.arange(n)[:, None]
    rms = np.sqrt(np.mean(padded[idx] ** 2, axis=1))
    peak = rms.max()
    if peak <= 0:
        return audio
    loud = np.nonzero(20 * np.log10(np.maximum(rms, 1e-10) / peak) > -top_db)[0]
    if loud.size == 0:
        return audio[:0]
    return audio[loud[0] * hop:min(audio.size, (loud[-1] + 1) * hop)]


def to_pcm16(np, audio):
    """16-bit samples; the model can go past full scale: scale, don't clip."""
    peak = float(np.max(np.abs(audio))) if audio.size else 0.0
    if peak > 0.99:
        audio = audio * (0.99 / peak)
    return (np.clip(audio, -1.0, 1.0) * 32767).astype("<i2").tobytes()
