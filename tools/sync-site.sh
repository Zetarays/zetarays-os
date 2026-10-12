#!/bin/bash
# Puts the delivery's README.txt and SHA256SUMS into the site (the page links
# look for them next to index.html) and exports the site to the Desktop.
set -e
DS="${ZETA_DELIVERY_DIR:-$HOME/Desktop/ZETA RAYS 2.0}"
SITE="$HOME/RAiX/site-zetarays"
cd "$DS"
: > "$SITE/SHA256SUMS"
for f in zetarays-2.0-amd64.iso zetarays-2.0-arm64.iso zetarays-2.0-amd64.ova zetarays-2.0-arm64.ova; do
    cat "$f.sha256" >> "$SITE/SHA256SUMS"
done
cp -f README.txt "$SITE/README.txt"
rsync -a --delete --exclude index-original.html --exclude .DS_Store "$SITE/" "$DS/site-zetarays.org/"
echo "site exported with README.txt and SHA256SUMS"
