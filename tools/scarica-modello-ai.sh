#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Scarica il modello AI locale di ZETA (llama3.2:1b) nella cartella che finisce
# nell'immagine, dal registro ufficiale di Ollama.
#
# Il manifesto (piccolo) e' nel repository e fissa la versione: qui si
# scaricano solo i file che mancano e si controlla che l'impronta SHA-256 di
# ognuno sia quella scritta nel manifesto. Il modello (1,3 GB) non sta nel
# repository: GitHub non accetta file cosi' grandi.
#
#   tools/scarica-modello-ai.sh        (lo chiama build.sh se manca qualcosa)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
M="$ROOT/live-build/config/includes.chroot/usr/share/ollama/.ollama/models"
MANIFESTO="$M/manifests/registry.ollama.ai/library/llama3.2/1b"
REGISTRO="https://registry.ollama.ai/v2/library/llama3.2/blobs"

[ -s "$MANIFESTO" ] || { echo "manca il manifesto del modello: $MANIFESTO" >&2; exit 1; }
mkdir -p "$M/blobs"
for d in $(python3 -c "
import json,sys
m=json.load(open(sys.argv[1]))
print(m['config']['digest'])
for l in m['layers']: print(l['digest'])" "$MANIFESTO"); do
    f="$M/blobs/${d/:/-}"
    if [ -s "$f" ] && [ "$(shasum -a 256 "$f" | cut -d' ' -f1)" = "${d#sha256:}" ]; then
        continue
    fi
    echo "scarico ${d:0:19}…"
    curl -fL --retry 3 -o "$f.parziale" "$REGISTRO/$d"
    [ "$(shasum -a 256 "$f.parziale" | cut -d' ' -f1)" = "${d#sha256:}" ] \
        || { rm -f "$f.parziale"; echo "impronta sbagliata per $d" >&2; exit 1; }
    mv "$f.parziale" "$f"
done
echo "modello AI pronto (impronte verificate)"
