#!/bin/bash
# Prepara una VM di PROVA a partire dalla OVA: la importa, la accende e vi
# installa gli strumenti di collaudo (ssh, ydotool). Questi NON stanno
# nell'immagine consegnata: servono solo qui, per poterla guidare da fuori.
#   tools/vm-prepara.sh [arm64|amd64]
set -uo pipefail
ARCH="${1:-arm64}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OVA="$ROOT/out/zetarays-1.7-$ARCH.ova"
VBM=/Applications/VirtualBox.app/Contents/MacOS/VBoxManage
NAME="ZETA RAYS prova ($ARCH)"
T="$ROOT/tools/vbox-tasti.py"
PORTA=$([ "$ARCH" = arm64 ] && echo 2222 || echo 2223)
PUB=~/.zeta-test/id_vm.pub

scrivi() { python3 "$T" "$NAME" "$1" --invio; sleep "${2:-2}"; }

[ -f "$OVA" ] || { echo "OVA non trovata: $OVA"; exit 1; }

if "$VBM" list vms | grep -q "\"$NAME\""; then
  "$VBM" controlvm "$NAME" poweroff >/dev/null 2>&1; sleep 3
  "$VBM" unregistervm "$NAME" --delete >/dev/null 2>&1
fi

echo "[$(date +%H:%M:%S)] importo la OVA…"
"$VBM" import "$OVA" --vsys 0 --vmname "$NAME" >/dev/null 2>&1 || { echo "import fallito"; exit 1; }
"$VBM" modifyvm "$NAME" --graphicscontroller vmsvga --accelerate3d on \
    --vram 128 --memory 6144 --cpus 4 >/dev/null 2>&1
"$VBM" modifyvm "$NAME" --natpf1 "ssh,tcp,127.0.0.1,$PORTA,,22" >/dev/null 2>&1

# La chiave pubblica di collaudo viaggia via HTTP dall'host (10.0.2.2 in NAT):
# scriverla a mano con gli scancode sarebbe lungo e fragile.
python3 -m http.server 8899 --directory ~/.zeta-test --bind 127.0.0.1 >/dev/null 2>&1 &
SERVER=$!
trap 'kill $SERVER 2>/dev/null' EXIT

echo "[$(date +%H:%M:%S)] accendo…"
"$VBM" startvm "$NAME" --type gui >/dev/null 2>&1 || \
  "$VBM" startvm "$NAME" --type headless >/dev/null 2>&1
sleep 100

echo "[$(date +%H:%M:%S)] apro il terminale (Super+Invio)"
"$VBM" controlvm "$NAME" keyboardputscancode e0 5b 1c 9c e0 db >/dev/null 2>&1
sleep 6

echo "[$(date +%H:%M:%S)] installo gli strumenti di collaudo"
scrivi "echo zeta | sudo -S nft add rule inet zeta input tcp dport 22 accept" 3
scrivi "echo zeta | sudo -S apt-get -y install openssh-server ydotool > /tmp/prov.log 2>&1; echo FINITO-APT" 5
# apt può metterci qualche minuto: si aspetta che la riga compaia
for i in $(seq 1 40); do
  sleep 15
  scrivi "grep -c FINITO-APT /tmp/prov.log > /dev/null; true" 1
  if "$VBM" showvminfo "$NAME" >/dev/null 2>&1; then :; fi
  # la verifica vera è il tentativo di connessione, più sotto
  ssh -p "$PORTA" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
      -o ConnectTimeout=5 -o BatchMode=yes -o LogLevel=ERROR zeta@127.0.0.1 true 2>/dev/null && break
  # se ssh risponde ma senza chiave, la installiamo
  if nc -z 127.0.0.1 "$PORTA" 2>/dev/null; then
    echo "[$(date +%H:%M:%S)] ssh risponde: installo la chiave"
    scrivi "mkdir -p \$HOME/.ssh; curl -s http://10.0.2.2:8899/id_vm.pub > \$HOME/.ssh/authorized_keys" 3
    scrivi "chmod 700 \$HOME/.ssh; chmod 600 \$HOME/.ssh/authorized_keys" 2
  fi
done

echo "[$(date +%H:%M:%S)] avvio ydotoold (serve per i clic automatici)"
scrivi "echo zeta | sudo -S bash -c 'ydotoold --socket-path=/tmp/.ydotool_socket --socket-own=1000:1000 &' " 3

if ssh -p "$PORTA" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
       -i ~/.zeta-test/id_vm -o ConnectTimeout=8 -o BatchMode=yes -o LogLevel=ERROR \
       zeta@127.0.0.1 'echo PRONTA' 2>/dev/null; then
  echo "[$(date +%H:%M:%S)] VM di prova pronta sulla porta $PORTA"
else
  echo "[$(date +%H:%M:%S)] ATTENZIONE: ssh non risponde ancora"
fi
