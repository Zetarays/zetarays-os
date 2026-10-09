#!/bin/bash
# Mette nel sito README.txt e SHA256SUMS della consegna (i link della pagina
# li cercano accanto a index.html) ed esporta il sito sulla Scrivania.
set -e
DS="${ZETA_CONSEGNA:-$HOME/Desktop/ZETA RAYS 2.0}"
SITO="$HOME/RAiX/sito-zetarays"
cd "$DS"
: > "$SITO/SHA256SUMS"
for f in zetarays-2.0-amd64.iso zetarays-2.0-arm64.iso zetarays-2.0-amd64.ova zetarays-2.0-arm64.ova; do
    cat "$f.sha256" >> "$SITO/SHA256SUMS"
done
cp -f README.txt "$SITO/README.txt"
rsync -a --delete --exclude index-ORIGINALE.html --exclude .DS_Store "$SITO/" "$DS/sito-zetarays.org/"
echo "sito esportato con README.txt e SHA256SUMS"
