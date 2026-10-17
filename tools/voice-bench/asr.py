# SPDX-License-Identifier: GPL-3.0-or-later
"""Transcribe every WAV of the given candidate folders and analyse the audio.

    python asr.py MODEL_SIZE LANG DIR [DIR...]

Writes DIR/asr-<size>.json (transcripts) and DIR/audio.json (clipping,
silences, level) next to the WAVs. Skips folders already transcribed.
"""
import glob
import json
import os
import sys

import numpy as np
import soundfile as sf
from faster_whisper import WhisperModel

size, lang, dirs = sys.argv[1], sys.argv[2], sys.argv[3:]
model = None


def analyse(path):
    x, rate = sf.read(path, dtype="float32")
    peak = float(np.max(np.abs(x))) if len(x) else 0.0
    clipped = int(np.sum(np.abs(x) >= 0.999))
    frame = int(rate * 0.02)
    n = len(x) // frame
    rms = np.sqrt(np.mean(x[:n * frame].reshape(n, frame) ** 2, axis=1) + 1e-12)
    db = 20 * np.log10(rms)
    voiced = db > -45
    idx = np.where(voiced)[0]
    lead = idx[0] * 0.02 if len(idx) else len(x) / rate
    trail = (n - 1 - idx[-1]) * 0.02 if len(idx) else 0
    longest = 0
    run = 0
    if len(idx):
        for v in voiced[idx[0]:idx[-1] + 1]:
            run = 0 if v else run + 1
            longest = max(longest, run)
    return {"dur": round(len(x) / rate, 3), "peak": round(peak, 3), "clipped": clipped,
            "lead_s": round(lead, 3), "trail_s": round(trail, 3),
            "longest_gap_s": round(longest * 0.02, 3),
            "rms_db": round(float(20 * np.log10(np.sqrt(np.mean(x ** 2)) + 1e-12)), 1)}


for d in dirs:
    out = os.path.join(d, "asr-%s.json" % size)
    wavs = sorted(glob.glob(os.path.join(d, "*.wav")))
    if not os.path.exists(os.path.join(d, "audio.json")):
        json.dump({os.path.basename(w): analyse(w) for w in wavs},
                  open(os.path.join(d, "audio.json"), "w"), indent=1)
    if os.path.exists(out):
        continue
    if model is None:
        model = WhisperModel(size, device="cpu", compute_type="int8", cpu_threads=4)
    res = {}
    for w in wavs:
        segs, _ = model.transcribe(w, language=lang, beam_size=5, temperature=0.0,
                                   condition_on_previous_text=False, vad_filter=False)
        res[os.path.basename(w)] = " ".join(s.text.strip() for s in segs)
    json.dump(res, open(out, "w"), indent=1, ensure_ascii=False)
    print(d, "done", flush=True)
