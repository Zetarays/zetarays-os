#!/bin/bash
# Puts the delivery's README.txt and SHA256SUMS into the site (the page links
# look for them next to index.html) and exports the site to the Desktop.
# The version (image names, delivery folder) comes from the VERSION file.
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VERSION="$(tr -d '[:space:]' < "$ROOT/VERSION")"
[[ "$VERSION" =~ ^[0-9]+\.[0-9]+(\.[0-9]+)?$ ]] || { echo "VERSION missing or invalid: '$VERSION'" >&2; exit 1; }
DS="${ZETA_DELIVERY_DIR:-$HOME/Desktop/ZETA RAYS $VERSION}"
SITE="$ROOT/site-zetarays"
cd "$DS"
: > "$SITE/SHA256SUMS"
for a in amd64.iso arm64.iso amd64.ova arm64.ova; do
    cat "zetarays-$VERSION-$a.sha256" >> "$SITE/SHA256SUMS"
done
cp -f README.txt "$SITE/README.txt"
rsync -a --delete --exclude index-original.html --exclude .DS_Store "$SITE/" "$DS/site-zetarays.org/"
echo "site exported with README.txt and SHA256SUMS ($VERSION)"
