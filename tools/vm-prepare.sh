#!/bin/bash
# Prepares a TEST VM from the OVA: imports it, starts it and installs the
# testing tools in it (ssh, ydotool). These are NOT part of the shipped
# image: they are needed only here, to drive the VM from outside.
#   tools/vm-prepare.sh [arm64|amd64]
set -uo pipefail
ARCH="${1:-arm64}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OVA="$ROOT/out/zetarays-2.0-$ARCH.ova"
VBM=/Applications/VirtualBox.app/Contents/MacOS/VBoxManage
NAME="ZETA RAYS test ($ARCH)"
T="$ROOT/tools/vbox-keys.py"
PORT=$([ "$ARCH" = arm64 ] && echo 2222 || echo 2223)
PUB=~/.zeta-test/id_vm.pub

type_line() { python3 "$T" "$NAME" "$1" --enter; sleep "${2:-2}"; }

[ -f "$OVA" ] || { echo "OVA not found: $OVA"; exit 1; }

if "$VBM" list vms | grep -q "\"$NAME\""; then
  "$VBM" controlvm "$NAME" poweroff >/dev/null 2>&1; sleep 3
  "$VBM" unregistervm "$NAME" --delete >/dev/null 2>&1
fi

echo "[$(date +%H:%M:%S)] importing the OVA…"
"$VBM" import "$OVA" --vsys 0 --vmname "$NAME" >/dev/null 2>&1 || { echo "import failed"; exit 1; }
"$VBM" modifyvm "$NAME" --graphicscontroller vmsvga --accelerate3d on \
    --vram 128 --memory 6144 --cpus 4 >/dev/null 2>&1
"$VBM" modifyvm "$NAME" --natpf1 "ssh,tcp,127.0.0.1,$PORT,,22" >/dev/null 2>&1

# The test public key travels over HTTP from the host (10.0.2.2 under NAT):
# typing it by hand with scancodes would be slow and fragile.
python3 -m http.server 8899 --directory ~/.zeta-test --bind 127.0.0.1 >/dev/null 2>&1 &
SERVER=$!
trap 'kill $SERVER 2>/dev/null' EXIT

echo "[$(date +%H:%M:%S)] starting…"
"$VBM" startvm "$NAME" --type gui >/dev/null 2>&1 || \
  "$VBM" startvm "$NAME" --type headless >/dev/null 2>&1
sleep 100

echo "[$(date +%H:%M:%S)] opening the terminal (Super+Enter)"
"$VBM" controlvm "$NAME" keyboardputscancode e0 5b 1c 9c e0 db >/dev/null 2>&1
sleep 6

echo "[$(date +%H:%M:%S)] installing the testing tools"
type_line "echo zeta | sudo -S nft add rule inet zeta input tcp dport 22 accept" 3
type_line "echo zeta | sudo -S apt-get -y install openssh-server ydotool > /tmp/provision.log 2>&1; echo APT-DONE" 5
# apt may take a few minutes: wait for the line to appear
for i in $(seq 1 40); do
  sleep 15
  type_line "grep -c APT-DONE /tmp/provision.log > /dev/null; true" 1
  if "$VBM" showvminfo "$NAME" >/dev/null 2>&1; then :; fi
  # the real check is the connection attempt below
  ssh -p "$PORT" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
      -o ConnectTimeout=5 -o BatchMode=yes -o LogLevel=ERROR zeta@127.0.0.1 true 2>/dev/null && break
  # if ssh answers but the key isn't there yet, install it
  if nc -z 127.0.0.1 "$PORT" 2>/dev/null; then
    echo "[$(date +%H:%M:%S)] ssh is answering: installing the key"
    type_line "mkdir -p \$HOME/.ssh; curl -s http://10.0.2.2:8899/id_vm.pub > \$HOME/.ssh/authorized_keys" 3
    type_line "chmod 700 \$HOME/.ssh; chmod 600 \$HOME/.ssh/authorized_keys" 2
  fi
done

echo "[$(date +%H:%M:%S)] starting ydotoold (needed for automated clicks)"
type_line "echo zeta | sudo -S bash -c 'ydotoold --socket-path=/tmp/.ydotool_socket --socket-own=1000:1000 &' " 3

if ssh -p "$PORT" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
       -i ~/.zeta-test/id_vm -o ConnectTimeout=8 -o BatchMode=yes -o LogLevel=ERROR \
       zeta@127.0.0.1 'echo READY' 2>/dev/null; then
  echo "[$(date +%H:%M:%S)] test VM ready on port $PORT"
else
  echo "[$(date +%H:%M:%S)] WARNING: ssh is not answering yet"
fi
