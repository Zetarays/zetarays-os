#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-or-later
# ZETA's voice bench: synthesizes the test sentences (sentences.py) with each
# Piper voice in cache/piper/voices, transcribes them with Whisper "medium"
# (faster-whisper) and estimates quality with torchaudio's SQUIM models, then
# prints word error rate, quality, speed and memory for each voice.
#
#   tools/voice-bench/run.sh [OUTDIR]        (default: .cache/voice-bench)
#
# Runs in a Docker container (linux/arm64 Debian trixie, 4 CPUs) with the
# Piper 2023.11.14-2 binary that ZETA ships. Needs the network once, for the
# Python packages and the Whisper and SQUIM weights. Extra variables:
#   VOICES="it_IT-serena-high it_IT-paola-medium"   voices to test
#   EXTRA="--length 1.05 --noise 0.6 --noisew 0.4"  Piper options
set -eu
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
OUT="${1:-$ROOT/.cache/voice-bench}"
NAME=z21-voice-bench
VOICES="${VOICES:-$(cd "$ROOT/cache/piper/voices" && ls it_IT-*.onnx | sed 's/\.onnx$//')}"
mkdir -p "$OUT/hf"
docker rm -f "$NAME" >/dev/null 2>&1 || true
docker run -d --name "$NAME" --platform linux/arm64 --cpus=4 --memory=8g \
    -v "$ROOT:/repo:ro" -v "$OUT:/out" -v "$OUT/hf:/root/.cache/huggingface" \
    debian:trixie sleep infinity >/dev/null
trap 'docker rm -f "$NAME" >/dev/null 2>&1' EXIT
docker exec "$NAME" sh -c '
set -e
apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq python3 python3-venv time ca-certificates curl >/dev/null
python3 -m venv /venv
/venv/bin/pip install -q faster-whisper "av<16" numpy soundfile
/venv/bin/pip install -q torch torchaudio --index-url https://download.pytorch.org/whl/cpu
mkdir -p /opt/piper /out/voices /out/ref
# clean human speech as the non-matching reference of SQUIM (CC0 1.0)
R=https://huggingface.co/datasets/paolapersico1/Voice-Dataset-Italian/resolve/main/wav/4000000001_4000000300_CustomerService
for i in 4000000002 4000000003; do [ -s /out/ref/$i.wav ] || curl -sfL -o /out/ref/$i.wav $R/$i.wav; done
tar -xzf /repo/cache/piper/piper_linux_aarch64.tar.gz -C /opt/piper --strip-components=1
# the same phoneme table reduction as hook 0210
for v in /repo/cache/piper/voices/*.onnx; do
    ln -sf "$v" /out/voices/; cp "$v.json" /out/voices/
done
python3 - /out/voices/*.onnx.json <<PY
import json, sys
for p in sys.argv[1:]:
    c = json.load(open(p)); c["phoneme_id_map"] = {k: v for k, v in c["phoneme_id_map"].items() if len(k) == 1}
    json.dump(c, open(p, "w"), ensure_ascii=False)
PY
'
for v in $VOICES; do
    docker exec "$NAME" /venv/bin/python /repo/tools/voice-bench/synth.py piperbin \
        "/out/voices/$v.onnx" "/out/$v" --norm 2 ${EXTRA:-} 2>/dev/null
done
dirs=$(for v in $VOICES; do printf '/out/%s ' "$v"; done)
docker exec "$NAME" sh -c "/venv/bin/python /repo/tools/voice-bench/asr.py medium it $dirs && \
    /venv/bin/python /repo/tools/voice-bench/mos.py $dirs" 2>&1 | grep -v -i affinity || true
python3 "$ROOT/tools/voice-bench/score.py" $(for v in $VOICES; do printf '%s/%s ' "$OUT" "$v"; done)
