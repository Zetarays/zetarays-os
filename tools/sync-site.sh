#!/bin/bash
# Puts the delivery's README.txt and SHA256SUMS into the site (the page links
# look for them next to index.html), writes the sizes and SHA-256 checksums
# of the four images and the two upgrade files into index.html
# (tools/site-downloads.py) and exports the site to the Desktop.
# The version (image names, delivery folder) comes from the VERSION file.
# Running it again gives the same result.
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VERSION="$(tr -d '[:space:]' < "$ROOT/VERSION")"
[[ "$VERSION" =~ ^[0-9]+\.[0-9]+(\.[0-9]+)?$ ]] || { echo "VERSION missing or invalid: '$VERSION'" >&2; exit 1; }
DS="${ZETA_DELIVERY_DIR:-$HOME/Desktop/ZETA RAYS $VERSION}"
SITE="$ROOT/site-zetarays"
cd "$DS"
# The upgrade files (tools/make-upgrade.sh writes them to out/) are published
# next to the images: copy them into the delivery folder if they are not there
for a in amd64 arm64; do
    f="zetarays-$VERSION-upgrade-$a.run"
    for g in "$f" "$f.sha256"; do
        if [ ! -e "$g" ] && [ -e "$ROOT/out/$g" ]; then
            cp -f "$ROOT/out/$g" ".$g.partial" && mv -f ".$g.partial" "$g"
            echo "copied $g from out/"
        fi
    done
done
python3 "$ROOT/tools/site-downloads.py" "$SITE/index.html" "$DS" "$VERSION"
: > "$SITE/SHA256SUMS"
for a in amd64.iso arm64.iso amd64.ova arm64.ova upgrade-amd64.run upgrade-arm64.run; do
    cat "zetarays-$VERSION-$a.sha256" >> "$SITE/SHA256SUMS"
done
cp -f README.txt "$SITE/README.txt"
rsync -a --delete --exclude index-original.html --exclude .DS_Store "$SITE/" "$DS/site-zetarays.org/"
echo "site exported with README.txt, SHA256SUMS, sizes and checksums ($VERSION)"
