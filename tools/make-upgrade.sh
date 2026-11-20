#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Builds the in-place upgrade files: a system installed from 2.5 becomes the
# current release (VERSION) without being reinstalled.
#
#   tools/make-upgrade.sh                 both architectures
#   tools/make-upgrade.sh arm64           one architecture
#   tools/make-upgrade.sh --accept-hooks  after reviewing build hooks that changed
#
# Output: out/zetarays-VERSION-upgrade-ARCH.run (+ .sha256), one per
# architecture because of the Ollama runtime. What goes in (everything is
# computed here, from the released 2.5 configuration and the current tree):
#   - the ZETA RAYS files of includes.chroot (tools/upgrade/zeta_files.py:
#     no AI models, nothing of the live session or the installer)
#   - the list of packages new since 2.5, the services the hooks enable
#   - the Ollama runtime from cache/ (without the GPU libraries)
#   - the build hooks that the upgrade repeats (tools/upgrade/hooks-reviewed.json)
#   - zeta-rays-release (package source of the ZETA RAYS updates), when the
#     repository key exists (tools/apt/gen-repo-key.py)
# How to use the result: docs/UPDATES.md.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FROM=2.5
VERSION="$(tr -d '[:space:]' < "$ROOT/VERSION" 2>/dev/null || true)"
[[ "$VERSION" =~ ^[0-9]+\.[0-9]+(\.[0-9]+)?$ ]] || { echo "VERSION missing or invalid: '$VERSION'" >&2; exit 1; }
VERSION="${ZETA_UPGRADE_VERSION:-$VERSION}"
ARCHES=()
EXTRA=()
for a in "$@"; do
  case "$a" in
    amd64|arm64) ARCHES+=("$a") ;;
    --accept-hooks) EXTRA+=("$a") ;;
    *) echo "usage: $0 [amd64|arm64] [--accept-hooks]" >&2; exit 2 ;;
  esac
done
[ ${#ARCHES[@]} -gt 0 ] || ARCHES=(arm64 amd64)
[ "$VERSION" != "$FROM" ] || { echo "VERSION is $FROM: set the new release number first" >&2; exit 1; }
OLD="$ROOT/.cache/src-$FROM-release-config"
[ -d "$OLD/includes.chroot" ] || { echo "the released $FROM configuration is missing: $OLD" >&2; exit 1; }

# The same generated files the ISO gets (build.sh): translations, assets,
# start page, boot theme. Every string must be translated, as for the ISO.
python3 "$ROOT/tools/gen-assets.py"
python3 "$ROOT/tools/i18n.py" check >/dev/null || { python3 "$ROOT/tools/i18n.py" check | tail -20; echo "translations incomplete" >&2; exit 1; }
python3 "$ROOT/tools/i18n.py" compile
FREE_FONT_SITE="$ROOT/.cache/site-free-font"
python3 "$ROOT/tools/site-free-font.py" "$ROOT/site-zetarays" "$FREE_FONT_SITE"
python3 "$ROOT/tools/gen-firefox-start-page.py" "$FREE_FONT_SITE" "$ROOT/live-build/config/includes.chroot/usr/share/zetarays/start"
rm -rf "${ROOT:?}/live-build/config/includes.chroot/usr/share/grub/themes/zeta"
mkdir -p "$ROOT/live-build/config/includes.chroot/usr/share/grub/themes/zeta"
cp -Rf "$ROOT"/live-build/config/bootloaders/grub-pc/live-theme/. "$ROOT/live-build/config/includes.chroot/usr/share/grub/themes/zeta/"
find "$ROOT/live-build/config/includes.chroot" -name __pycache__ -type d -prune -exec rm -rf {} +

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
REL=()
if [ -s "$ROOT/tools/apt/zeta-rays-archive-keyring.gpg" ]; then
  python3 "$ROOT/tools/make-zeta-debs.py" --release-only --version "$VERSION" --out "$WORK" >/dev/null
  REL=(--release-deb "$WORK/zeta-rays-release_${VERSION}_all.deb")
else
  echo "WARNING: no repository key: the upgrade will not add the ZETA RAYS updates source" >&2
fi

mkdir -p "$ROOT/out"
for ARCH in "${ARCHES[@]}"; do
  OLLAMA="$ROOT/cache/ollama-linux-$ARCH.tar.zst"
  [ -s "$OLLAMA" ] || { echo "Ollama runtime not cached for $ARCH: $OLLAMA (build.sh downloads it)" >&2; exit 1; }
  echo "== $ARCH"
  python3 "$ROOT/tools/upgrade/make_bundle.py" --arch "$ARCH" --to "$VERSION" --from "$FROM" \
      --old-config "$OLD" --ollama "$OLLAMA" \
      --out "$ROOT/out/zetarays-$VERSION-upgrade-$ARCH.run" ${REL[@]+"${REL[@]}"} ${EXTRA[@]+"${EXTRA[@]}"}
  EXTRA=()   # hooks accepted once
done
find "$ROOT/tools" -name __pycache__ -type d -prune -exec rm -rf {} +
echo "Upgrade files ready in $ROOT/out (see docs/UPDATES.md)"
