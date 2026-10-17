#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Downloads ZETA's local AI model from the official Ollama registry into the
# folder that ends up in the image. The model is chosen here (MODEL_NAME,
# MODEL_TAG) and pinned by the manifest committed in the repository.
#
# The (small) manifest lives in the repository and pins the version: this
# script only downloads the missing files and checks that the SHA-256 digest
# of each one matches the one written in the manifest. The model (1.3 GB) is
# not in the repository: GitHub does not accept files that large.
#
# 2.1: Qwen3 4B Instruct (2507), Ollama tag qwen3:4b-instruct, Apache-2.0,
# 2.5 GB, about 3.7 GB of RAM when loaded. Chosen over llama3.2:1b after a
# benchmark of commands, Italian/English answers, use of web sources and
# conversation memory (see docs/AI.md).
#
#   tools/download-ai-model.sh        (build.sh calls it if anything is missing)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
M="$ROOT/live-build/config/includes.chroot/usr/share/ollama/.ollama/models"
MODEL_NAME=qwen3
MODEL_TAG=4b-instruct
MANIFEST="$M/manifests/registry.ollama.ai/library/$MODEL_NAME/$MODEL_TAG"
REGISTRY="https://registry.ollama.ai/v2/library/$MODEL_NAME/blobs"

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
