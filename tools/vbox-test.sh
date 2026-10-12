#!/bin/bash
# REAL test in VirtualBox: imports the OVA, powers on the machine with 3D and
# lets you drive it and take screenshots from the terminal.
#
#   tools/vbox-test.sh start          import and power on (3D enabled)
#   tools/vbox-test.sh keys "text"    type text
#   tools/vbox-test.sh key <codes>    e.g. "1c" (enter), "01" (esc)
#   tools/vbox-test.sh click x y      absolute click
#   tools/vbox-test.sh screenshot name  screenshot to .cache/vm/name.png
#   tools/vbox-test.sh stop
set -uo pipefail
ARCH="${ZETA_ARCH:-arm64}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OVA="${ZETA_OVA:-$ROOT/out/zetarays-2.0-$ARCH.ova}"
VBM=/Applications/VirtualBox.app/Contents/MacOS/VBoxManage
NAME="ZETA RAYS 2.0 ($ARCH)"
SHOTS="$ROOT/.cache/vm"
mkdir -p "$SHOTS"

case "${1:-}" in
  start)
    [ -f "$OVA" ] || { echo "OVA not found: $OVA"; exit 1; }
    if "$VBM" list vms | grep -q "\"$NAME\""; then
      "$VBM" controlvm "$NAME" poweroff >/dev/null 2>&1
      sleep 2
      "$VBM" unregistervm "$NAME" --delete >/dev/null 2>&1
    fi
    echo "importing the OVA…"
    "$VBM" import "$OVA" >/dev/null 2>&1 || { echo "import failed"; exit 1; }
    "$VBM" modifyvm "$NAME" --graphicscontroller vmsvga --accelerate3d on \
        --vram 128 --memory 6144 --cpus 4 >/dev/null 2>&1
    "$VBM" startvm "$NAME" --type gui >/dev/null 2>&1 || \
      "$VBM" startvm "$NAME" --type headless >/dev/null 2>&1
    echo "machine started"
    ;;
  keys)    "$VBM" controlvm "$NAME" keyboardputstring "$2" ;;
  key)     shift; "$VBM" controlvm "$NAME" keyboardputscancode "$@" ;;
  click)
    # absolute click: x y (needs the tablet mouse, the VirtualBox default)
    "$VBM" controlvm "$NAME" mouseputeventabs "$2" "$3" 0 0 0x01 >/dev/null 2>&1
    "$VBM" controlvm "$NAME" mouseputeventabs "$2" "$3" 0 0 0x00 >/dev/null 2>&1
    ;;
  screenshot)
    OUT="$SHOTS/${2:-screen}.png"
    "$VBM" controlvm "$NAME" screenshotpng "$OUT" >/dev/null 2>&1 && echo "$OUT" \
      || echo "screenshot failed"
    ;;
  stop) "$VBM" controlvm "$NAME" poweroff >/dev/null 2>&1; echo "powered off" ;;
  *) sed -n '2,10p' "$0" ;;
esac
