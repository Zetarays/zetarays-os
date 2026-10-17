#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Test the ZETA RAYS arm64 ISO in a fast virtual machine on the Mac (QEMU + HVF).
# Usage: tools/vm-arm64.sh            -> opens a window with ZETA RAYS
#        tools/vm-arm64.sh --headless -> no window (control via QMP in .cache/vm)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VERSION="$(tr -d '[:space:]' < "$ROOT/VERSION")"   # release version (VERSION file)
ISO="$ROOT/out/zetarays-$VERSION-arm64.iso"
VM="$ROOT/.cache/vm"
mkdir -p "$VM"
[ -f "$ISO" ] || { echo "ISO not found: run ./build.sh arm64 first"; exit 1; }
[ -f "$VM/vars.fd" ] || cp /opt/homebrew/share/qemu/edk2-arm-vars.fd "$VM/vars.fd"

DISPLAY_OPTS=(-display cocoa -device virtio-gpu-pci,xres=1440,yres=900)
if [ "${1:-}" = "--headless" ]; then
  DISPLAY_OPTS=(-display none -device virtio-gpu-pci,xres=1440,yres=900 -qmp "unix:$VM/qmp.sock,server,nowait" -daemonize)
fi

exec qemu-system-aarch64 -M virt -accel hvf -cpu host -smp 4 -m 6G \
  -drive if=pflash,format=raw,readonly=on,file=/opt/homebrew/share/qemu/edk2-aarch64-code.fd \
  -drive if=pflash,format=raw,file="$VM/vars.fd" \
  -device qemu-xhci -device usb-kbd -device usb-tablet \
  -drive file="$ISO",media=cdrom,if=none,id=cd -device virtio-scsi-pci -device scsi-cd,drive=cd \
  -nic user,model=virtio-net-pci \
  "${DISPLAY_OPTS[@]}"
