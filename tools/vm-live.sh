#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Test VM booted from the live ISO, with 3D enabled. Used to try out changes
# without rebuilding the image: files are pushed in with tools/vm.sh push.
#   tools/vm-live.sh start | screenshot [NAME] | key CODES... | stop | delete
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VERSION="$(tr -d '[:space:]' < "$ROOT/VERSION")"   # release version (VERSION file)
ISO="${ZETA_ISO:-$HOME/Desktop/ZETA RAYS $VERSION/zetarays-$VERSION-arm64.iso}"
VBM=/Applications/VirtualBox.app/Contents/MacOS/VBoxManage
NAME="ZETA RAYS test"
SHOTS="$ROOT/.cache/vm"; mkdir -p "$SHOTS"

case "${1:-}" in
  start)
    [ -f "$ISO" ] || { echo "ISO not found: $ISO"; exit 1; }
    if "$VBM" list vms | grep -q "\"$NAME\""; then
      "$VBM" controlvm "$NAME" poweroff >/dev/null 2>&1; sleep 2
      "$VBM" unregistervm "$NAME" --delete >/dev/null 2>&1
    fi
    "$VBM" createvm --name "$NAME" --platform-architecture=arm --ostype Debian_arm64 --register >/dev/null
    # USB keyboard and mouse: on ARM the VM has no PS/2 and would get no keys
    "$VBM" modifyvm "$NAME" --memory 6144 --cpus 4 --vram 128 \
        --graphicscontroller vmsvga --accelerate-3d on --firmware efi \
        --nic1 nat --mouse usbtablet --keyboard usb --usb-xhci on --rtc-use-utc on \
        --audio-enabled on --audio-controller hda --audio-out on --audio-in on >/dev/null
    # port 2222 -> 22 to copy files in (test VM only, never in the image)
    "$VBM" modifyvm "$NAME" --nat-pf1 "push,tcp,127.0.0.1,2222,,22" >/dev/null 2>&1
    "$VBM" storagectl "$NAME" --name SATA --add sata --portcount 2 >/dev/null
    "$VBM" storageattach "$NAME" --storagectl SATA --port 0 --device 0 --type dvddrive --medium "$ISO" >/dev/null
    "$VBM" startvm "$NAME" --type gui >/dev/null 2>&1 || "$VBM" startvm "$NAME" --type headless >/dev/null 2>&1
    echo "Test VM started from the live ISO"
    ;;
  screenshot) "$VBM" controlvm "$NAME" screenshotpng "$SHOTS/${2:-screen}.png" >/dev/null 2>&1 && echo "$SHOTS/${2:-screen}.png" || echo "screenshot failed" ;;
  key) shift; "$VBM" controlvm "$NAME" keyboardputscancode "$@" ;;
  stop) "$VBM" controlvm "$NAME" poweroff >/dev/null 2>&1; echo "powered off" ;;
  delete) "$VBM" controlvm "$NAME" poweroff >/dev/null 2>&1; sleep 2; "$VBM" unregistervm "$NAME" --delete >/dev/null 2>&1; echo deleted ;;
  *) sed -n '2,5p' "$0" ;;
esac
