#!/bin/bash
# Prova REALE in VirtualBox: importa la OVA, accende la macchina con 3D e
# permette di guidarla e fotografarla dal terminale.
#
#   tools/vbox-prova.sh avvia          importa e accende (3D attivo)
#   tools/vbox-prova.sh tasti "testo"  scrive
#   tools/vbox-prova.sh tasto <codici> es. "1c" (invio), "01" (esc)
#   tools/vbox-prova.sh foto nome      screenshot in .cache/vm/nome.png
#   tools/vbox-prova.sh spegni
set -uo pipefail
ARCH="${ZETA_ARCH:-arm64}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OVA="${ZETA_OVA:-$ROOT/out/zetarays-2.0-$ARCH.ova}"
VBM=/Applications/VirtualBox.app/Contents/MacOS/VBoxManage
NAME="ZETA RAYS 2.0 ($ARCH)"
SHOTS="$ROOT/.cache/vm"
mkdir -p "$SHOTS"

case "${1:-}" in
  avvia)
    [ -f "$OVA" ] || { echo "OVA non trovata: $OVA"; exit 1; }
    if "$VBM" list vms | grep -q "\"$NAME\""; then
      "$VBM" controlvm "$NAME" poweroff >/dev/null 2>&1
      sleep 2
      "$VBM" unregistervm "$NAME" --delete >/dev/null 2>&1
    fi
    echo "importo la OVA…"
    "$VBM" import "$OVA" >/dev/null 2>&1 || { echo "import fallito"; exit 1; }
    "$VBM" modifyvm "$NAME" --graphicscontroller vmsvga --accelerate3d on \
        --vram 128 --memory 6144 --cpus 4 >/dev/null 2>&1
    "$VBM" startvm "$NAME" --type gui >/dev/null 2>&1 || \
      "$VBM" startvm "$NAME" --type headless >/dev/null 2>&1
    echo "macchina avviata"
    ;;
  tasti)   "$VBM" controlvm "$NAME" keyboardputstring "$2" ;;
  tasto)   shift; "$VBM" controlvm "$NAME" keyboardputscancode "$@" ;;
  clic)
    # clic assoluto: x y (richiede il mouse tablet, predefinito in VirtualBox)
    "$VBM" controlvm "$NAME" mouseputeventabs "$2" "$3" 0 0 0x01 >/dev/null 2>&1
    "$VBM" controlvm "$NAME" mouseputeventabs "$2" "$3" 0 0 0x00 >/dev/null 2>&1
    ;;
  foto)
    OUT="$SHOTS/${2:-schermo}.png"
    "$VBM" controlvm "$NAME" screenshotpng "$OUT" >/dev/null 2>&1 && echo "$OUT" \
      || echo "cattura non riuscita"
    ;;
  spegni) "$VBM" controlvm "$NAME" poweroff >/dev/null 2>&1; echo "spenta" ;;
  *) sed -n '2,10p' "$0" ;;
esac
