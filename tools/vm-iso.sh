#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Boot a ZETA RAYS ISO in VirtualBox to test it live.
#   tools/vm-iso.sh start [arm64|amd64]
#   tools/vm-iso.sh stop [arm64|amd64]
#   tools/vm-iso.sh screenshot [arm64|amd64] [FILE.png]
set -uo pipefail
ARCH="${2:-arm64}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ISO="$ROOT/out/zetarays-2.0-$ARCH.iso"
VBM=/Applications/VirtualBox.app/Contents/MacOS/VBoxManage
NAME="ZETA test ($ARCH)"
PORT=$([ "$ARCH" = arm64 ] && echo 2222 || echo 2223)

case "${1:-start}" in
start)
  [ -f "$ISO" ] || { echo "ISO not found: $ISO"; exit 1; }
  if "$VBM" list vms | grep -q "\"$NAME\""; then
    "$VBM" controlvm "$NAME" poweroff >/dev/null 2>&1; sleep 3
    "$VBM" unregistervm "$NAME" --delete >/dev/null 2>&1
  fi
  OS_TYPE=$([ "$ARCH" = arm64 ] && echo Debian_arm64 || echo Debian_64)
  "$VBM" createvm --name "$NAME" --ostype "$OS_TYPE" --register >/dev/null
  "$VBM" modifyvm "$NAME" --memory 4096 --cpus 4 --vram 128 \
      --graphicscontroller vmsvga --accelerate3d on --firmware efi \
      --audio-enabled on --audio-controller hda --audio-out on --audio-in on \
      --nic1 nat --natpf1 "ssh,tcp,127.0.0.1,$PORT,,22" >/dev/null
  "$VBM" storagectl "$NAME" --name SATA --add sata --controller IntelAhci >/dev/null
  "$VBM" storageattach "$NAME" --storagectl SATA --port 0 --device 0 \
      --type dvddrive --medium "$ISO" >/dev/null
  "$VBM" startvm "$NAME" --type gui >/dev/null 2>&1 && echo "started: $NAME (ssh on port $PORT)"
  ;;
stop) "$VBM" controlvm "$NAME" poweroff >/dev/null 2>&1; echo "powered off" ;;
screenshot) "$VBM" controlvm "$NAME" screenshotpng "${3:-/tmp/zeta.png}" && echo "${3:-/tmp/zeta.png}" ;;
*) sed -n '2,6p' "$0" ;;
esac
