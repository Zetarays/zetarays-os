#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# VM di prova dalla ISO live, con 3D attivo. Serve per provare le modifiche
# senza ricostruire l'immagine: i file si spingono dentro con vm-push.sh.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ISO="${ZETA_ISO:-$HOME/Desktop/ZETA RAYS 2.0/zetarays-2.0-arm64.iso}"
VBM=/Applications/VirtualBox.app/Contents/MacOS/VBoxManage
NAME="ZETA RAYS prova"
SHOTS="$ROOT/.cache/vm"; mkdir -p "$SHOTS"

case "${1:-}" in
  avvia)
    [ -f "$ISO" ] || { echo "ISO non trovata: $ISO"; exit 1; }
    if "$VBM" list vms | grep -q "\"$NAME\""; then
      "$VBM" controlvm "$NAME" poweroff >/dev/null 2>&1; sleep 2
      "$VBM" unregistervm "$NAME" --delete >/dev/null 2>&1
    fi
    "$VBM" createvm --name "$NAME" --platform-architecture=arm --ostype Debian_arm64 --register >/dev/null
    # tastiera e mouse USB: su ARM la VM non ha PS/2 e non riceverebbe i tasti
    "$VBM" modifyvm "$NAME" --memory 6144 --cpus 4 --vram 128 \
        --graphicscontroller vmsvga --accelerate-3d on --firmware efi \
        --nic1 nat --mouse usbtablet --keyboard usb --usb-xhci on --rtc-use-utc on \
        --audio-enabled on --audio-controller hda --audio-out on --audio-in on >/dev/null
    # porta 2222 -> 22 per copiare i file dentro (solo VM di prova, mai nell'immagine)
    "$VBM" modifyvm "$NAME" --nat-pf1 "push,tcp,127.0.0.1,2222,,22" >/dev/null 2>&1
    "$VBM" storagectl "$NAME" --name SATA --add sata --portcount 2 >/dev/null
    "$VBM" storageattach "$NAME" --storagectl SATA --port 0 --device 0 --type dvddrive --medium "$ISO" >/dev/null
    "$VBM" startvm "$NAME" --type gui >/dev/null 2>&1 || "$VBM" startvm "$NAME" --type headless >/dev/null 2>&1
    echo "VM di prova avviata dalla ISO live"
    ;;
  foto)  "$VBM" controlvm "$NAME" screenshotpng "$SHOTS/${2:-schermo}.png" >/dev/null 2>&1 && echo "$SHOTS/${2:-schermo}.png" || echo "cattura non riuscita" ;;
  tasto) shift; "$VBM" controlvm "$NAME" keyboardputscancode "$@" ;;
  spegni) "$VBM" controlvm "$NAME" poweroff >/dev/null 2>&1; echo spenta ;;
  elimina) "$VBM" controlvm "$NAME" poweroff >/dev/null 2>&1; sleep 2; "$VBM" unregistervm "$NAME" --delete >/dev/null 2>&1; echo eliminata ;;
  *) sed -n '2,6p' "$0" ;;
esac
