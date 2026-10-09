#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Scarica in cache/ la voce di ZETA: Piper (sintesi vocale naturale) con le
# voci Paola (italiano) e Lessac (inglese), e Vosk (riconoscimento vocale) con
# i modelli italiano e inglese e i pacchetti Python per amd64 e arm64.
# build.sh li mette nell'immagine senza usare la rete; qui ogni file scaricato
# deve avere l'impronta SHA-256 scritta sotto.
#
#   tools/scarica-voce.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
C="$ROOT/cache"
mkdir -p "$C/piper/voci" "$C/vosk/modelli"

prendi() {   # URL DESTINAZIONE SHA256
    if [ -s "$2" ] && [ "$(shasum -a 256 "$2" | cut -d' ' -f1)" = "$3" ]; then return 0; fi
    echo "scarico $(basename "$2")…"
    curl -fL --retry 5 --retry-delay 3 -o "$2.parziale" "$1"
    if [ "$(shasum -a 256 "$2.parziale" | cut -d' ' -f1)" != "$3" ]; then
        rm -f "$2.parziale"; echo "impronta sbagliata: $(basename "$2")" >&2; exit 1
    fi
    mv "$2.parziale" "$2"
}

P=https://github.com/rhasspy/piper/releases/download/2023.11.14-2
prendi "$P/piper_linux_x86_64.tar.gz"  "$C/piper/piper_linux_x86_64.tar.gz"  a50cb45f355b7af1f6d758c1b360717877ba0a398cc8cbe6d2a7a3a26e225992
prendi "$P/piper_linux_aarch64.tar.gz" "$C/piper/piper_linux_aarch64.tar.gz" fea0fd2d87c54dbc7078d0f878289f404bd4d6eea6e7444a77835d1537ab88eb
V=https://huggingface.co/rhasspy/piper-voices/resolve/main
prendi "$V/it/it_IT/paola/medium/it_IT-paola-medium.onnx"      "$C/piper/voci/it_IT-paola-medium.onnx"      6fc918b5a0ea6137382833dddfa567bffbe6a5060c02043c87192ee59c04210c
prendi "$V/it/it_IT/paola/medium/it_IT-paola-medium.onnx.json" "$C/piper/voci/it_IT-paola-medium.onnx.json" aea19c0a7fce29fbc359b93f10e7902854401e4c95ae2ea328ae516b15d296cf
prendi "$V/en/en_US/lessac/high/en_US-lessac-high.onnx"        "$C/piper/voci/en_US-lessac-high.onnx"        4cabf7c3a638017137f34a1516522032d4fe3f38228a843cc9b764ddcbcd9e09
prendi "$V/en/en_US/lessac/high/en_US-lessac-high.onnx.json"   "$C/piper/voci/en_US-lessac-high.onnx.json"   db42b97d9859f257bc1561b8ed980e7fb2398402050a74ddd6cbec931a92412f
M=https://alphacephei.com/vosk/models
prendi "$M/vosk-model-small-it-0.22.zip"    "$C/vosk/modelli/vosk-model-small-it-0.22.zip"    9ec65e75861d1c6c2e457cccd932705340dcdf233f5b239f00733b4de0bf3267
prendi "$M/vosk-model-small-en-us-0.15.zip" "$C/vosk/modelli/vosk-model-small-en-us-0.15.zip" 30f26242c4eb449f948e42cb302dd7a686cb29a3423a8367f99ff41780942498

# pacchetti Python di Vosk (PyPI, per Python 3.13 di Debian 13); srt esiste
# solo in forma sorgente e si compila nell'immagine con setuptools
for a in x86_64 aarch64; do
    d="$C/vosk/$a"; mkdir -p "$d"
    for p in vosk cffi pycparser requests urllib3 idna charset_normalizer certifi tqdm websockets; do
        pip3 download --quiet --no-deps --only-binary=:all: \
            --platform manylinux2014_$a --platform manylinux_2_17_$a --platform manylinux_2_28_$a \
            --platform manylinux_2_12_$a --platform manylinux2010_$a \
            --python-version 3.13 --implementation cp --abi cp313 --abi abi3 --abi none -d "$d" "$p"
    done
    pip3 download --quiet --no-deps --no-binary=:all: -d "$d" srt
    pip3 download --quiet --no-deps --only-binary=:all: -d "$d" setuptools wheel
done
echo "voce pronta in $C/piper e $C/vosk"
