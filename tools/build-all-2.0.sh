#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Builds the four ZETA RAYS 2.0 images and copies them to the release
# folder.
#
# Rules, learned the hard way:
#  - ALWAYS start from scratch. Previously, if an arm64 ISO already existed it
#    was silently reused: all it took was a failed manual delete, and an old
#    image shipped next to three new ones.
#  - stop at the first error. Previously a failed OVA was merely noted, and
#    the release step copied the others, leaving the old OVA on the Desktop.
#  - release only if all four succeeded, and every copy is compared with the
#    original.
set -uo pipefail
# The path is derived from this script's location instead of being
# hard-coded: that way the working folder on the Mac can be renamed
# without breaking anything.
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/out"
DEST="${ZETA_DELIVERY_DIR:-$HOME/Desktop/ZETA RAYS 2.0}"
IMAGES="zetarays-2.0-arm64.iso zetarays-2.0-arm64.ova zetarays-2.0-amd64.iso zetarays-2.0-amd64.ova"
log() { echo "[$(date '+%H:%M:%S')] $*"; }
fail() { log "FAILED: $* — no release, the folder on the Desktop is left as it was"; exit 1; }

# "deliver": only copies to the Desktop the images already built and
# checked in out/ (after a build with BUILD_ONLY=1)
if [ "${1:-}" = deliver ]; then
    for f in $IMAGES; do
        [ -s "$OUT/$f" ] || fail "$f missing in out/"
    done
    SKIP_BUILD=1
else
    SKIP_BUILD=0
fi

# 1) no build in progress, no old images lying around
if [ "$SKIP_BUILD" = 1 ]; then :; elif pgrep -f "build.sh (arm64|amd64)" >/dev/null || pgrep -f "make-ova.sh" >/dev/null; then
    fail "a build is already in progress"
fi
if [ "$SKIP_BUILD" = 0 ]; then
for f in $IMAGES zetarays-2.0-arm64.vmdk zetarays-2.0-amd64.vmdk; do
    rm -f "$OUT/$f"
done
log "out/ folder cleaned: starting from scratch"

# 2) the four images, in order; each one must succeed
log "building the arm64 ISO"
"$ROOT/build.sh" arm64 > "$OUT/run-arm64.log" 2>&1 || fail "arm64 ISO (see run-arm64.log)"
log "arm64 ISO ready ($(du -h "$OUT/zetarays-2.0-arm64.iso" | cut -f1))"

# Colima's virtual disk does not give freed space back on its own: after the
# amd64 build the Mac was left with a couple of GB and the OVA export failed
# with a full disk. The space is given back before each OVA.
free_space() {
    command -v colima >/dev/null && colima ssh -- sudo fstrim -a >/dev/null 2>&1 || true
    log "free space: $(df -h "$OUT" | awk 'NR==2{print $4}')"
}

free_space
log "creating the arm64 OVA"
ZETA_ARCH=arm64 "$ROOT/tools/make-ova.sh" > "$OUT/run-ova-arm64.log" 2>&1 || fail "arm64 OVA (see run-ova-arm64.log)"
log "arm64 OVA ready ($(du -h "$OUT/zetarays-2.0-arm64.ova" | cut -f1))"

free_space
log "building the amd64 ISO"
"$ROOT/build.sh" amd64 > "$OUT/run-amd64.log" 2>&1 || fail "amd64 ISO (see run-amd64.log)"
log "amd64 ISO ready ($(du -h "$OUT/zetarays-2.0-amd64.iso" | cut -f1))"

free_space
log "creating the amd64 OVA"
ZETA_ARCH=amd64 "$ROOT/tools/make-ova.sh" > "$OUT/run-ova-amd64.log" 2>&1 || fail "amd64 OVA (see run-ova-amd64.log)"
log "amd64 OVA ready ($(du -h "$OUT/zetarays-2.0-amd64.ova" | cut -f1))"

for f in $IMAGES; do
    [ -s "$OUT/$f" ] || fail "$f missing"
done

fi   # end of the build (skipped with "deliver")

# With BUILD_ONLY=1 we stop here: the images stay in out/ for the full
# check, and are released later with: tools/build-all-2.0.sh deliver
if [ "${BUILD_ONLY:-0}" = 1 ]; then
    log "BUILT — not released: run the full check first (images in $OUT)"
    exit 0
fi

# 3) release: copy under a temporary name and then rename, so an interruption
#    never leaves a half-written file on the Desktop
mkdir -p "$DEST"
for f in $IMAGES; do
    cp -f "$OUT/$f" "$DEST/.$f.partial" || fail "copying $f"
    if [ "$(stat -f%z "$OUT/$f")" != "$(stat -f%z "$DEST/.$f.partial")" ]; then
        rm -f "$DEST/.$f.partial"; fail "incomplete copy of $f"
    fi
    mv -f "$DEST/.$f.partial" "$DEST/$f"
    log "copied $f"
done
log "DONE — images in $DEST"
ls -la "$DEST"
