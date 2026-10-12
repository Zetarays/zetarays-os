#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Downloads ZETA's local AI model (llama3.2:1b) from the official Ollama
# registry into the folder that ends up in the image.
#
# The (small) manifest lives in the repository and pins the version: this
# script only downloads the missing files and checks that the SHA-256 digest
# of each one matches the one written in the manifest. The model (1.3 GB) is
# not in the repository: GitHub does not accept files that large.
#
#   tools/download-ai-model.sh        (build.sh calls it if anything is missing)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
M="$ROOT/live-build/config/includes.chroot/usr/share/ollama/.ollama/models"
MANIFEST="$M/manifests/registry.ollama.ai/library/llama3.2/1b"
REGISTRY="https://registry.ollama.ai/v2/library/llama3.2/blobs"

[ -s "$MANIFEST" ] || { echo "model manifest is missing: $MANIFEST" >&2; exit 1; }
mkdir -p "$M/blobs"
for d in $(python3 -c "
import json,sys
m=json.load(open(sys.argv[1]))
print(m['config']['digest'])
for l in m['layers']: print(l['digest'])" "$MANIFEST"); do
    f="$M/blobs/${d/:/-}"
    if [ -s "$f" ] && [ "$(shasum -a 256 "$f" | cut -d' ' -f1)" = "${d#sha256:}" ]; then
        continue
    fi
    echo "downloading ${d:0:19}…"
    curl -fL --retry 3 -o "$f.partial" "$REGISTRY/$d"
    [ "$(shasum -a 256 "$f.partial" | cut -d' ' -f1)" = "${d#sha256:}" ] \
        || { rm -f "$f.partial"; echo "wrong digest for $d" >&2; exit 1; }
    mv "$f.partial" "$f"
done
echo "AI model ready (digests verified)"
