#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Imports and starts the ZETA RAYS OVA in VirtualBox, then saves a REAL
# screenshot of the VM contents to the Desktop (useful if the window stays
# black: the screenshot still shows what is going on inside the machine).
#
# Usage:  tools/vbox-run.sh [arm64|amd64]
set -uo pipefail
ARCH="${1:-arm64}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VERSION="$(tr -d '[:space:]' < "$ROOT/VERSION")"   # release version (VERSION file)
OVA="$ROOT/out/zetarays-$VERSION-$ARCH.ova"
VBM=/Applications/VirtualBox.app/Contents/MacOS/VBoxManage
NAME="ZETA RAYS $VERSION ($ARCH)"

[ -f "$OVA" ] || { echo "OVA not found: $OVA"; exit 1; }

HOSTARCH="$(uname -m)"
if [ "$ARCH" = "amd64" ] && [ "$HOSTARCH" = "arm64" ]; then
  echo "WARNING: on Apple Silicon Macs the amd64 OVA CANNOT boot"
  echo "         (VirtualBox for ARM does not emulate x86). Use: tools/vbox-run.sh arm64"
  exit 2
fi

# if a VM with this name already exists, remove it to start clean
if "$VBM" list vms | grep -q "\"$NAME\""; then
  "$VBM" controlvm "$NAME" poweroff >/dev/null 2>&1 || true
  sleep 2
  "$VBM" unregistervm "$NAME" --delete >/dev/null 2>&1 || true
fi

echo "== Importing $OVA"
"$VBM" import "$OVA" >/dev/null 2>&1 || { echo "import failed"; exit 1; }

echo "== Starting the VM (window)"
"$VBM" startvm "$NAME" --type gui >/dev/null 2>&1 || \
  "$VBM" startvm "$NAME" --type headless >/dev/null 2>&1

echo "== Waiting for boot (30s) and capturing a real screenshot…"
sleep 30
SHOT="$HOME/Desktop/zeta-vm-$ARCH.png"
if "$VBM" controlvm "$NAME" screenshotpng "$SHOT" >/dev/null 2>&1; then
  echo "== Screenshot saved: $SHOT"
  echo "   If you see the ZETA RAYS login screen here but the window is black,"
  echo "   it is only the window not repainting: resize the window"
  echo "   (or press Host+Home) and it will appear. Login: user 'zeta' / password 'zeta'."
else
  echo "== Could not capture a screenshot (is the VM running?)"
fi