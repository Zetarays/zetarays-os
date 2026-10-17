# SPDX-License-Identifier: GPL-3.0-or-later
"""Synthesize the test set with one TTS candidate and measure speed and memory.

    python synth.py ENGINE MODEL OUTDIR [--lang it] [--voice if_sara] [--norm 0|1|2]
                    [--length L] [--noise N] [--noisew W] [--silence S] [--speed X]

ENGINE: piperbin (Piper 2023.11.14-2 binary, what ZETA ships), piper1
(piper-tts from OHF-Voice/piper1-gpl), kokoro (kokoro-onnx). --norm: 0 = raw
text, 1 = speech_text.normalize without the lexicon, 2 = with the lexicon.
"""
import argparse
import json
import os
import resource
import subprocess
import sys
import time
import wave

sys.path.insert(0, "/repo/live-build/config/includes.chroot/usr/lib/zeta")  # i18n_data
sys.path.insert(0, "/repo/live-build/config/includes.chroot/usr/lib/zeta/intelligence")
sys.path.insert(0, "/repo/tools/voice-bench")
import speech_text  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("engine")
ap.add_argument("model")
ap.add_argument("out")
ap.add_argument("--lang", default="it")
ap.add_argument("--voice", default="")
ap.add_argument("--norm", type=int, default=0)
ap.add_argument("--length", type=float)
ap.add_argument("--noise", type=float)
ap.add_argument("--noisew", type=float)
ap.add_argument("--silence", type=float, default=0.2)
ap.add_argument("--speed", type=float, default=1.0)
a = ap.parse_args()

from sentences import SENTENCES  # noqa: E402
texts = SENTENCES[a.lang]
if a.norm:
    texts = [speech_text.normalize(t, a.lang, lexicon=a.norm == 2) for t in texts]
os.makedirs(a.out, exist_ok=True)
metrics = {"engine": a.engine, "model": os.path.basename(a.model), "voice": a.voice,
           "args": vars(a), "texts": texts}


def wav_seconds(path):
    with wave.open(path) as w:
        return w.getnframes() / w.getframerate()


if a.engine == "piperbin":
    opts = []
    for flag, val in (("--length_scale", a.length), ("--noise_scale", a.noise), ("--noise_w", a.noisew)):
        if val is not None:
            opts += [flag, str(val)]
    opts += ["--sentence_silence", str(a.silence)]
    # 1) time to first audio, cold process, short sentence (what the user waits for)
    t0 = time.monotonic()
    p = subprocess.Popen(["/opt/piper/piper", "--model", a.model, "--output_raw", "-q"] + opts,
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    p.stdin.write((texts[0] + "\n").encode())
    p.stdin.close()
    p.stdout.read(512)
    metrics["first_audio_s"] = round(time.monotonic() - t0, 3)
    p.stdout.read()
    p.wait()
    # 2) the whole set in one process (load once), wall time and peak RSS
    lines = "".join(json.dumps({"text": t, "output_file": os.path.join(a.out, "%02d.wav" % i)}) + "\n"
                    for i, t in enumerate(texts, 1))
    t0 = time.monotonic()
    r = subprocess.run(["/usr/bin/time", "-f", "%M", "/opt/piper/piper", "--model", a.model,
                        "--json-input", "-q"] + opts, input=lines.encode(),
                       capture_output=True)
    wall = time.monotonic() - t0
    metrics["rss_mb"] = round(int(r.stderr.decode().strip().splitlines()[-1]) / 1024, 1)
    metrics["total_s"] = round(wall, 3)
    # load time of the model alone (empty input)
    t0 = time.monotonic()
    subprocess.run(["/opt/piper/piper", "--model", a.model, "--output_raw", "-q"], input=b"",
                   capture_output=True)
    metrics["load_s"] = round(time.monotonic() - t0, 3)
    metrics["synth_s"] = round(wall - metrics["load_s"], 3)
else:
    import numpy as np
    t0 = time.monotonic()
    if a.engine == "piper1":
        from piper import PiperVoice, SynthesisConfig
        voice = PiperVoice.load(a.model)
        cfg = SynthesisConfig(length_scale=a.length, noise_scale=a.noise, noise_w_scale=a.noisew)

        def synth(text):
            chunks = list(voice.synthesize(text, syn_config=cfg))
            rate = chunks[0].sample_rate
            gap = np.zeros(int(rate * a.silence), dtype=np.int16)
            parts = []
            for c in chunks:
                parts += [c.audio_int16_array, gap]
            return np.concatenate(parts), rate
    else:
        from kokoro_onnx import Kokoro
        k = Kokoro(a.model, os.path.join(os.path.dirname(a.model), "voices-v1.0.bin"))

        def synth(text):
            samples, rate = k.create(text, voice=a.voice, speed=a.speed, lang="it" if a.lang == "it" else "en-us")
            peak = float(np.max(np.abs(samples))) or 1.0
            if peak > 0.99:           # Kokoro can exceed full scale: scale, do not clip
                samples = samples * (0.99 / peak)
            return (np.clip(samples, -1, 1) * 32767).astype(np.int16), rate
    metrics["load_s"] = round(time.monotonic() - t0, 3)
    t1 = time.monotonic()
    audio, rate = synth(texts[0])
    metrics["first_audio_s"] = round(metrics["load_s"] + time.monotonic() - t1, 3)
    t1 = time.monotonic()
    for i, t in enumerate(texts, 1):
        audio, rate = synth(t)
        with wave.open(os.path.join(a.out, "%02d.wav" % i), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes(audio.tobytes())
    metrics["synth_s"] = round(time.monotonic() - t1, 3)
    metrics["total_s"] = round(metrics["load_s"] + metrics["synth_s"], 3)
    metrics["rss_mb"] = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)

audio_s = sum(wav_seconds(os.path.join(a.out, "%02d.wav" % i)) for i in range(1, len(texts) + 1))
metrics["audio_s"] = round(audio_s, 2)
metrics["rtf"] = round(metrics["synth_s"] / audio_s, 3)
json.dump(metrics, open(os.path.join(a.out, "metrics.json"), "w"), indent=1, ensure_ascii=False)
print(json.dumps({k: metrics[k] for k in ("model", "voice", "load_s", "first_audio_s", "synth_s",
                                          "audio_s", "rtf", "rss_mb")}))
