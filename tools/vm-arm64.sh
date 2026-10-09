#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Prova l'ISO arm64 di ZETA RAYS in una macchina virtuale veloce sul Mac (QEMU + HVF).
# Uso: tools/vm-arm64.sh            -> apre una finestra con ZETA RAYS
#      tools/vm-arm64.sh --headless -> senza finestra (controllo via QMP in .cache/vm)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ISO="$ROOT/out/zetarays-2.0-arm64.iso"
VM="$ROOT/.cache/vm"
mkdir -p "$VM"
[ -f "$ISO" ] || { echo "ISO non trovata: esegui prima ./build.sh arm64"; exit 1; }
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
