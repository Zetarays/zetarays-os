#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Importa e avvia l'OVA ZETA RAYS in VirtualBox, poi salva sul Desktop uno
# screenshot REALE del contenuto della VM (utile se la finestra resta nera:
# lo screenshot mostra comunque cosa c'è dentro la macchina).
#
# Uso:  tools/vbox-run.sh [arm64|amd64]
set -uo pipefail
ARCH="${1:-arm64}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OVA="$ROOT/out/zetarays-2.0-$ARCH.ova"
VBM=/Applications/VirtualBox.app/Contents/MacOS/VBoxManage
NAME="ZETA RAYS 2.0 ($ARCH)"

[ -f "$OVA" ] || { echo "OVA non trovata: $OVA"; exit 1; }

HOSTARCH="$(uname -m)"
if [ "$ARCH" = "amd64" ] && [ "$HOSTARCH" = "arm64" ]; then
  echo "ATTENZIONE: su Mac Apple Silicon la OVA amd64 NON può avviarsi"
  echo "            (VirtualBox ARM non emula x86). Usa: tools/vbox-run.sh arm64"
  exit 2
fi

# se esiste già una VM con questo nome, rimuovila per partire pulito
if "$VBM" list vms | grep -q "\"$NAME\""; then
  "$VBM" controlvm "$NAME" poweroff >/dev/null 2>&1 || true
  sleep 2
  "$VBM" unregistervm "$NAME" --delete >/dev/null 2>&1 || true
fi

echo "== Importo $OVA"
"$VBM" import "$OVA" >/dev/null 2>&1 || { echo "import fallito"; exit 1; }

echo "== Avvio la VM (finestra)"
"$VBM" startvm "$NAME" --type gui >/dev/null 2>&1 || \
  "$VBM" startvm "$NAME" --type headless >/dev/null 2>&1

echo "== Attendo l'avvio (30s) e catturo uno screenshot reale…"
sleep 30
SHOT="$HOME/Desktop/zeta-vm-$ARCH.png"
if "$VBM" controlvm "$NAME" screenshotpng "$SHOT" >/dev/null 2>&1; then
  echo "== Screenshot salvato: $SHOT"
  echo "   Se qui vedi la schermata di login ZETA RAYS ma la finestra è nera,"
  echo "   è solo il ridisegno della finestra: ridimensiona la finestra"
  echo "   (o Host+Home) e apparirà. Login: utente 'zeta' / password 'zeta'."
else
  echo "== Non sono riuscito a catturare (VM non in esecuzione?)"
fi