# SPDX-License-Identifier: GPL-3.0-or-later
"""Reference-free quality estimates of every WAV with torchaudio's SQUIM models.

    python mos.py DIR [DIR...]      -> DIR/mos.json

SQUIM_SUBJECTIVE predicts MOS (1..5, trained on BVCC, i.e. listener ratings
of synthetic speech) given a non-matching clean human reference (two clips of
the CC0 Paola dataset, in $REF_DIR, default /out/ref). SQUIM_OBJECTIVE estimates STOI (0..1,
intelligibility) and PESQ (1..4.5, quality) without any reference.
"""
import glob
import json
import os
import sys

import soundfile as sf
import torch
import torchaudio
from torchaudio.pipelines import SQUIM_OBJECTIVE, SQUIM_SUBJECTIVE

torch.set_num_threads(4)
subjective = SQUIM_SUBJECTIVE.get_model()
objective = SQUIM_OBJECTIVE.get_model()


def load(path):
    x, rate = sf.read(path, dtype="float32")
    t = torch.from_numpy(x)[None]
    return torchaudio.functional.resample(t, rate, 16000) if rate != 16000 else t


refs = [load(p) for p in sorted(glob.glob(os.path.join(os.environ.get("REF_DIR", "/out/ref"), "*.wav")))]

for d in sys.argv[1:]:
    out = os.path.join(d, "mos.json")
    if os.path.exists(out):
        continue
    res = {}
    for w in sorted(glob.glob(os.path.join(d, "*.wav"))):
        x = load(w)
        with torch.no_grad():
            mos = sum(float(subjective(x, r)) for r in refs) / len(refs)
            stoi, pesq, sisdr = (float(v) for v in objective(x))
        res[os.path.basename(w)] = {"mos": round(mos, 3), "stoi": round(stoi, 3), "pesq": round(pesq, 3)}
    json.dump(res, open(out, "w"), indent=1)
    v = list(res.values())
    print(d, "MOS %.2f STOI %.3f PESQ %.2f" % tuple(sum(x[k] for x in v) / len(v) for k in ("mos", "stoi", "pesq")),
          flush=True)
