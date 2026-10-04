#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Prova finale automatica dell'immagine arm64 in VirtualBox: avvia la VM,
# esegue una sequenza di controlli e salva gli screenshot in .cache/vm/finale-*.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VM="ZETA RAYS 1.7 (arm64)"
T="$ROOT/tools/vbox-tasti.py"
P="$ROOT/tools/vbox-prova.sh"
VBM=/Applications/VirtualBox.app/Contents/MacOS/VBoxManage

foto() { "$P" foto "finale-$1" >/dev/null; echo "  foto: finale-$1"; }
scrivi() { "$T" "$VM" "$1" --invio; sleep "${2:-3}"; }
supertasto() { "$VBM" controlvm "$VM" keyboardputscancode e0 5b "$1" "$2" e0 db; sleep "${3:-4}"; }

echo "== avvio"
"$P" avvia || exit 1
sleep 95
foto 01-scrivania

echo "== terminale (Super+Invio) e barra del titolo"
supertasto 1c 9c 5
foto 02-terminale

echo "== la tastiera raggiunge la finestra?"
scrivi "echo TASTIERA-OK" 3
foto 03-tastiera

echo "== plugin delle barre del titolo"
scrivi "hyprctl plugin list | head -4" 3
foto 04-hyprbars

echo "== file sulla scrivania"
scrivi 'mkdir -p $HOME/Scrivania/Progetti; echo ciao > $HOME/Scrivania/appunti.txt; ls $HOME/Scrivania' 5
foto 05-icone

echo "== riduci a icona e ripristina"
scrivi "zeta-finestre minimizza" 4
foto 06-ridotta
supertasto 11 91 4          # Super+W
foto 07-pannello-finestre
"$VBM" controlvm "$VM" keyboardputscancode 01 81; sleep 2

echo "== tema chiaro"
supertasto 1c 9c 5
scrivi "zeta-aspetto set tema chiaro" 12
foto 08-tema-chiaro
supertasto 1c 9c 6
foto 09-terminale-chiaro
scrivi "zeta-aspetto set tema scuro" 12
foto 10-tema-scuro

echo "== fastfetch"
scrivi "clear; fastfetch | head -20" 5
foto 11-fastfetch
scrivi "echo zeta | sudo -S fastfetch | head -12" 6
foto 12-fastfetch-sudo

echo "fatto: screenshot in $ROOT/.cache/vm/finale-*.png"
