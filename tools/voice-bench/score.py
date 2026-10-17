# SPDX-License-Identifier: GPL-3.0-or-later
"""Word/character error rate of the ASR transcripts against the input text.

    python3 score.py [--asr medium] [--lang it] DIR [DIR...]

Both sides go through speech_text.normalize (numbers, times, units become
words, so "14:30" and the time written in words compare equal), then lowercase,
no accents, no punctuation. CER is computed without spaces ("wi fi" = "wifi").
The spellings merged afterwards are in data/score.json.
"""
import json
import os
import re
import sys
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "../../live-build/config/includes.chroot/usr/lib/zeta"))  # i18n_data
sys.path.insert(0, os.path.join(HERE, "../../live-build/config/includes.chroot/usr/lib/zeta/intelligence"))
sys.path.insert(0, HERE)
import speech_text  # noqa: E402

args = sys.argv[1:]
asr = "medium"
lang = "it"
while args and args[0].startswith("--"):
    if args[0] == "--asr":
        asr = args[1]
    elif args[0] == "--lang":
        lang = args[1]
    args = args[2:]

from sentences import SENTENCES as ALL  # noqa: E402
SENTENCES = ALL[lang]
with open(os.path.join(HERE, "data", "score.json"), encoding="utf-8") as _f:
    MERGE = [tuple(pair) for pair in json.load(_f)["merge"]]


def canon(text):
    text = speech_text.normalize(text, lang, lexicon=False)
    text = unicodedata.normalize("NFD", text.lower())
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    # brand spellings the recognizer cannot know ("Z", "race" for ZETA RAYS)
    text = re.sub(r"\bz\b", "zeta", text)
    text = re.sub(r"\bzeta (race|reis|rais|ray|raise|reys)\b", "zeta rays", text)
    text = re.sub(r"\bzetaris\b", "zeta rays", text)
    for a, b in MERGE:
        text = text.replace(a, b)
    return text


def edits(a, b):
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i]
        for j, y in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y)))
        prev = cur
    return prev[-1]


def plain(i):
    t = SENTENCES[i]
    return not re.search(r"\d", t) and speech_text.normalize(t, lang) == speech_text.normalize(t, lang, lexicon=False)


def score(d):
    tr = json.load(open(os.path.join(d, "asr-%s.json" % asr)))
    audio = json.load(open(os.path.join(d, "audio.json")))
    m = json.load(open(os.path.join(d, "metrics.json")))
    we = wn = ce = cn = pwe = pwn = 0
    worst = []
    for i, ref in enumerate(SENTENCES):
        name = "%02d.wav" % (i + 1)
        r, h = canon(ref).split(), canon(tr.get(name, "")).split()
        e = edits(r, h)
        we += e
        wn += len(r)
        ce += edits("".join(r), "".join(h))
        cn += len("".join(r))
        if plain(i):
            pwe += e
            pwn += len(r)
        if e:
            worst.append((e, name, " ".join(h)))
    a = list(audio.values())
    return {
        "dir": os.path.basename(d.rstrip("/")),
        "wer": round(100.0 * we / wn, 1), "cer": round(100.0 * ce / cn, 1),
        "wer_plain": round(100.0 * pwe / pwn, 1) if pwn else None,
        "rtf": m["rtf"], "first_audio_s": m["first_audio_s"], "rss_mb": m["rss_mb"],
        "audio_s": m["audio_s"], "clipped": sum(x["clipped"] for x in a),
        "max_gap_s": max(x["longest_gap_s"] for x in a), "max_lead_s": max(x["lead_s"] for x in a),
        "peak": max(x["peak"] for x in a),
        "errors": sorted(worst, reverse=True),
    }


if __name__ == "__main__":
    rows = [score(d) for d in args if os.path.exists(os.path.join(d, "asr-%s.json" % asr))]
    for r in rows:
        mos_file = os.path.join([d for d in args if d.rstrip("/").endswith(r["dir"])][0], "mos.json")
        if os.path.exists(mos_file):
            v = list(json.load(open(mos_file)).values())
            r["mos"] = round(sum(x["mos"] for x in v) / len(v), 2)
            r["pesq"] = round(sum(x["pesq"] for x in v) / len(v), 2)
    print("%-34s %5s %5s %6s %5s %5s %6s %6s %6s %5s %6s %5s" % (
        "candidate", "WER", "CER", "WERpl", "MOS", "PESQ", "RTF", "first", "RSSMB", "clip", "maxgap", "peak"))
    for r in rows:
        print("%-34s %5.1f %5.1f %6s %5s %5s %6.3f %6.2f %6.0f %5d %6.2f %5.2f" % (
            r["dir"], r["wer"], r["cer"], r["wer_plain"], r.get("mos", "-"), r.get("pesq", "-"), r["rtf"],
            r["first_audio_s"], r["rss_mb"], r["clipped"], r["max_gap_s"], r["peak"]))
    if "-v" in os.environ.get("SCORE_FLAGS", "").split():
        for r in rows:
            print("\n==", r["dir"])
            for e, name, h in r["errors"]:
                print("  %d %s | %s" % (e, name, h))
