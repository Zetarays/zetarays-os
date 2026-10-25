#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Downloads the local AI models shipped with ZETA RAYS from the official
# Ollama registry into the folder that ends up in the image.
#
# The (small) manifest of each model lives in the repository and pins its
# version: this script only downloads the missing files and checks that the
# SHA-256 digest of each one matches the one written in the manifest. The
# models (gigabytes) are not in the repository: GitHub does not accept files
# that large.
#
# The models and why they were chosen: docs/AI.md ("Choosing the model");
# which one a computer uses: /usr/lib/zeta/intelligence/models.py.
#
#   tools/download-ai-model.sh        (build.sh calls it if anything is missing)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
M="$ROOT/live-build/config/includes.chroot/usr/share/ollama/.ollama/models"
# name:tag of every model in the image (keep in step with models.py)
MODELS="qwen3:4b-instruct granite4:micro-h"

mkdir -p "$M/blobs"
for model in $MODELS; do
    name=${model%%:*} tag=${model#*:}
    manifest="$M/manifests/registry.ollama.ai/library/$name/$tag"
    registry="https://registry.ollama.ai/v2/library/$name/blobs"
    [ -s "$manifest" ] || { echo "model manifest is missing: $manifest" >&2; exit 1; }
    for d in $(python3 -c "
import json,sys
m=json.load(open(sys.argv[1]))
print(m['config']['digest'])
for l in m['layers']: print(l['digest'])" "$manifest"); do
        f="$M/blobs/${d/:/-}"
        if [ -s "$f" ] && [ "$(shasum -a 256 "$f" | cut -d' ' -f1)" = "${d#sha256:}" ]; then
            continue
        fi
        echo "downloading $model ${d:0:19}…"
        curl -fL --retry 3 -o "$f.partial" "$registry/$d"
        [ "$(shasum -a 256 "$f.partial" | cut -d' ' -f1)" = "${d#sha256:}" ] \
            || { rm -f "$f.partial"; echo "wrong digest for $d" >&2; exit 1; }
        mv "$f.partial" "$f"
    done
    echo "AI model $model ready (digests verified)"
done
