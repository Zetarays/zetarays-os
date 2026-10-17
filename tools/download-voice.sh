#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Downloads ZETA's voice into cache/: Kokoro-82M with the Italian voice Sara
# (the default), Piper (natural speech synthesis) with the Serena and Paola
# (Italian) and Lessac (English) voices, and Vosk (speech recognition)
# with the Italian and English models and the Python packages for amd64 and
# arm64. build.sh puts them into the image without using the network; every
# file downloaded here must match the SHA-256 checksum written below.
#
#   tools/download-voice.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
C="$ROOT/cache"
mkdir -p "$C/piper/voices" "$C/vosk/models" "$C/kokoro"

fetch() {   # URL DESTINATION SHA256
    if [ -s "$2" ] && [ "$(shasum -a 256 "$2" | cut -d' ' -f1)" = "$3" ]; then return 0; fi
    echo "downloading $(basename "$2")…"
    curl -fL --retry 5 --retry-delay 3 -o "$2.partial" "$1"
    if [ "$(shasum -a 256 "$2.partial" | cut -d' ' -f1)" != "$3" ]; then
        rm -f "$2.partial"; echo "wrong checksum: $(basename "$2")" >&2; exit 1
    fi
    mv "$2.partial" "$2"
}

P=https://github.com/rhasspy/piper/releases/download/2023.11.14-2
fetch "$P/piper_linux_x86_64.tar.gz"  "$C/piper/piper_linux_x86_64.tar.gz"  a50cb45f355b7af1f6d758c1b360717877ba0a398cc8cbe6d2a7a3a26e225992
fetch "$P/piper_linux_aarch64.tar.gz" "$C/piper/piper_linux_aarch64.tar.gz" fea0fd2d87c54dbc7078d0f878289f404bd4d6eea6e7444a77835d1537ab88eb
V=https://huggingface.co/rhasspy/piper-voices/resolve/main
fetch "$V/it/it_IT/paola/medium/it_IT-paola-medium.onnx"      "$C/piper/voices/it_IT-paola-medium.onnx"      6fc918b5a0ea6137382833dddfa567bffbe6a5060c02043c87192ee59c04210c
fetch "$V/it/it_IT/paola/medium/it_IT-paola-medium.onnx.json" "$C/piper/voices/it_IT-paola-medium.onnx.json" aea19c0a7fce29fbc359b93f10e7902854401e4c95ae2ea328ae516b15d296cf
# Serena (high): the default Italian voice since 2.1 (clearest and most natural
# in tools/voice-bench). Dataset CC BY 4.0: attribution in hook 0600.
fetch "$V/it/it_IT/serena/high/it_IT-serena-high.onnx"       "$C/piper/voices/it_IT-serena-high.onnx"       7462fbdf03727fb4c0c161286ad538fe6436b7e4b1c3059ef52930032475955f
fetch "$V/it/it_IT/serena/high/it_IT-serena-high.onnx.json"  "$C/piper/voices/it_IT-serena-high.onnx.json"  60597bac737a20766591fe24d1315df9a3811dc3509e69bc394cdee19eccbae7
fetch "$V/en/en_US/lessac/high/en_US-lessac-high.onnx"        "$C/piper/voices/en_US-lessac-high.onnx"        4cabf7c3a638017137f34a1516522032d4fe3f38228a843cc9b764ddcbcd9e09
fetch "$V/en/en_US/lessac/high/en_US-lessac-high.onnx.json"   "$C/piper/voices/en_US-lessac-high.onnx.json"   db42b97d9859f257bc1561b8ed980e7fb2398402050a74ddd6cbec931a92412f
# Kokoro-82M (Apache-2.0), int8 ONNX export and voice styles published by
# kokoro-onnx: Sara (if_sara) is ZETA's Italian voice since 2.1
K=https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0
fetch "$K/kokoro-v1.0.int8.onnx" "$C/kokoro/kokoro-v1.0.int8.onnx" 6e742170d309016e5891a994e1ce1559c702a2ccd0075e67ef7157974f6406cb
fetch "$K/voices-v1.0.bin"       "$C/kokoro/voices-v1.0.bin"       bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d
M=https://alphacephei.com/vosk/models
fetch "$M/vosk-model-small-it-0.22.zip"    "$C/vosk/models/vosk-model-small-it-0.22.zip"    9ec65e75861d1c6c2e457cccd932705340dcdf233f5b239f00733b4de0bf3267
fetch "$M/vosk-model-small-en-us-0.15.zip" "$C/vosk/models/vosk-model-small-en-us-0.15.zip" 30f26242c4eb449f948e42cb302dd7a686cb29a3423a8367f99ff41780942498

# Vosk Python packages (PyPI, for Debian 13's Python 3.13); srt exists only
# as a source distribution and is built inside the image with setuptools
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
echo "voice ready in $C/kokoro, $C/piper and $C/vosk"
