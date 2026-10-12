#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# ZETA RAYS — boot menu assets: GRUB (UEFI, USB stick and installed system)
# and isolinux (BIOS, USB stick). One style for all of them: black, small
# logo at the top, entries in a column, the selection marked by a slightly
# lighter band with a small blue bar on the left. No icons, no rounded
# boxes, normal-sized text.
#
#   tools/gen-grub-theme.sh
#
# Produces:
#   live-build/config/bootloaders/grub-pc/live-theme/
#     roboto-medium-16.pf2, roboto-medium-13.pf2   GRUB fonts
#     select_*.png                                 band of the selected entry
#     logo.png                                     symbol + wordmark
#   live-build/config/bootloaders/syslinux_common/splash.png
#     isolinux background 1024x768 (live-build does not reconvert it from
#     splash.svg to 640x480 if splash.png already exists)
# Runs in a Debian container (grub-mkfont and rsvg-convert are not available
# on the Mac). The generated assets are committed to the project: the build
# does not call this script.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$ROOT/live-build/config/bootloaders/grub-pc/live-theme"
SYSL="$ROOT/live-build/config/bootloaders/syslinux_common"
# temporary folder inside the project: colima only mounts the home directory
mkdir -p "$ROOT/.cache"; TMP="$(mktemp -d "$ROOT/.cache/grub-theme.XXXXXX")"
trap 'rm -rf "${TMP:?}"' EXIT
mkdir -p "$DEST"

# Logo drawings (official paths, tools/wordmark-zeta.json)
python3 - "$TMP" "$ROOT" <<'PY'
import json, os, sys
out, root = sys.argv[1], sys.argv[2]
M = json.load(open(os.path.join(root, "tools", "wordmark-zeta.json")))
X = 'xmlns="http://www.w3.org/2000/svg"'
# The full official logo (symbol and wordmark in the proportions of the
# original drawing), as on the login screen
ix, iy, iw, ih = M["bbox_full"]
mark = '<path d="%s"/>' % M["symbol"] + "".join('<path d="%s"/>' % d for d in M["wordmark"])


def logo(H):
    W = H * iw / ih
    body = ('<svg width="%.2f" height="%.2f" viewBox="%g %g %g %g"><g fill="#FFFFFF" '
             'fill-rule="nonzero">%s</g></svg>' % (W, H, ix, iy, iw, ih, mark))
    return W, H, body


# GRUB: 84 px tall (previously 120)
W, H, body = logo(84)
W, H = int(round(W)) + 2, int(round(H)) + 2
open(os.path.join(out, "logo.svg"), "w").write(
    '<svg %s width="%d" height="%d"><g transform="translate(1 1)">%s</g></svg>' % (X, W, H, body))
open(os.path.join(out, "logo.size"), "w").write("%d %d\n" % (W, H))

# isolinux 1024x768: the menu column starts at row 19 (y 304), the logo
# sits above it, centered
W2, H2, body2 = logo(88)
top = 304 - 52 - H2
open(os.path.join(out, "splash.svg"), "w").write(
    '<svg %s width="1024" height="768"><rect width="1024" height="768" fill="#000000"/>'
    '<g transform="translate(%.2f %.2f)">%s</g></svg>' % (X, (1024 - W2) / 2, top, body2))
PY

docker run --rm -v "$DEST:/out" -v "$SYSL:/sysl" -v "$TMP:/tmp/zeta:ro" debian:trixie bash -euo pipefail -c '
export DEBIAN_FRONTEND=noninteractive; apt-get update -qq >/dev/null
apt-get install -y -qq --no-install-recommends grub-common fonts-roboto-unhinted librsvg2-bin >/dev/null
F=/usr/share/fonts/truetype/roboto/unhinted/RobotoTTF
# Latin, Latin Extended, Greek, Cyrillic, arrows and punctuation: the
# entries of the installed system may be translated; for other scripts
# GRUB falls back to unicode.pf2 by itself
R=0x20-0x24F,0x370-0x3FF,0x400-0x4FF,0x2010-0x2027,0x2190-0x2193,0x25B8-0x25B8
# GRUB renders fonts without antialiasing (1-bit bitmaps): Medium with
# autohinting stays clean. 16 px for entries, 13 px for hints: real-screen
# sizes (the resolution is now the native one, not a stretched 1280x800).
rm -f /out/roboto-*.pf2
grub-mkfont -r $R -s 16 -a -n "Roboto Medium" -o /out/roboto-medium-16.pf2 $F/Roboto-Medium.ttf
grub-mkfont -r $R -s 13 -a -n "Roboto Medium" -o /out/roboto-medium-13.pf2 $F/Roboto-Medium.ttf

svg() { rsvg-convert -o "$1" /dev/stdin; }
X="xmlns=\"http://www.w3.org/2000/svg\""
# Band of the selected entry, nine pieces (GRUB stretches it to the size of
# the entry): solid #16161A fill, 3 px blue bar on the left, sharp corners.
# The left piece is 18 px wide: that is also the text indent.
FILL="#16161A"; BLUE="#3A8DFF"
piece() {  # name width height bar(0/1)
  if [ "$4" = 1 ]; then
    printf "%s" "<svg $X width=\"$2\" height=\"$3\"><rect width=\"$2\" height=\"$3\" fill=\"$FILL\"/><rect width=\"3\" height=\"$3\" fill=\"$BLUE\"/></svg>" | svg "/out/select_$1.png"
  else
    printf "%s" "<svg $X width=\"$2\" height=\"$3\"><rect width=\"$2\" height=\"$3\" fill=\"$FILL\"/></svg>" | svg "/out/select_$1.png"
  fi
}
piece nw 18 1 1; piece n 1 1 0; piece ne 10 1 0
piece w 18 1 1;  piece c 1 1 0; piece e 10 1 0
piece sw 18 1 1; piece s 1 1 0; piece se 10 1 0
rsvg-convert -o /out/logo.png /tmp/zeta/logo.svg
rsvg-convert -o /sysl/splash.png /tmp/zeta/splash.svg
# entry icons are no longer used
rm -rf /out/icons
chown -R '"$(id -u):$(id -g)"' /out /sysl/splash.png
'
echo "logo: $(cat "$TMP/logo.size")"
ls -la "$DEST" "$SYSL/splash.png"
