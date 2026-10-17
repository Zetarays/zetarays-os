#!/bin/bash
# REAL test of the image: boots the ISO in QEMU without a window and lets you
# drive it (keyboard) and capture it (screenshot) from the terminal.
#
#   tools/vm-test.sh start           starts the test machine
#   tools/vm-test.sh keys "hello"    types some text
#   tools/vm-test.sh key ret         presses a key (ret, tab, esc, spc, meta_l…)
#   tools/vm-test.sh click x y       clicks at screen coordinates
#   tools/vm-test.sh screenshot NAME saves a screenshot to .cache/vm/NAME.png
#   tools/vm-test.sh stop            shuts it down
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VERSION="$(tr -d '[:space:]' < "$ROOT/VERSION")"   # release version (VERSION file)
ISO="${ZETA_ISO:-$ROOT/out/zetarays-$VERSION-arm64.iso}"
VM="$ROOT/.cache/vm"
SOCK="$VM/qmp.sock"
mkdir -p "$VM"

qmp() {
  python3 - "$SOCK" "$1" <<'PY'
import json, socket, sys
sock, payload = sys.argv[1], sys.argv[2]
s = socket.socket(socket.AF_UNIX); s.settimeout(20); s.connect(sock)
f = s.makefile("rw")
f.readline()                                    # greeting
f.write(json.dumps({"execute": "qmp_capabilities"}) + "\n"); f.flush(); f.readline()
f.write(payload + "\n"); f.flush()
print(f.readline().strip())
PY
}

case "${1:-}" in
  start)
    [ -f "$ISO" ] || { echo "ISO not found: $ISO"; exit 1; }
    [ -f "$VM/vars.fd" ] || cp /opt/homebrew/share/qemu/edk2-arm-vars.fd "$VM/vars.fd"
    rm -f "$SOCK"
    qemu-system-aarch64 -M virt -accel hvf -cpu host -smp 4 -m 6G \
      -drive if=pflash,format=raw,readonly=on,file=/opt/homebrew/share/qemu/edk2-aarch64-code.fd \
      -drive if=pflash,format=raw,file="$VM/vars.fd" \
      -device qemu-xhci -device usb-kbd -device usb-tablet \
      -device virtio-gpu-gl-pci,xres=1440,yres=900 \
      -drive file="$ISO",media=cdrom,if=none,id=cd -device virtio-scsi-pci -device scsi-cd,drive=cd \
      -nic user,model=virtio-net-pci \
      -display cocoa,gl=on -qmp "unix:$SOCK,server,nowait" -daemonize
    echo "test machine started"
    ;;
  key)
    qmp "$(python3 -c 'import json,sys; print(json.dumps({"execute":"send-key","arguments":{"keys":[{"type":"qcode","data":k} for k in sys.argv[1].split("+")]}}))' "$2")" >/dev/null
    ;;
  keys)
    python3 - "$SOCK" "$2" <<'PY'
import json, socket, sys, time
sock, text = sys.argv[1], sys.argv[2]
SHIFT = {"!":"1","@":"2","#":"3","$":"4","%":"5","^":"6","&":"7","*":"8","(":"9",")":"0",
         "_":"minus","+":"equal",":":"semicolon","\"":"apostrophe","<":"comma",">":"dot","?":"slash","~":"grave_accent","|":"backslash"}
PLAIN = {" ":"spc",".":"dot",",":"comma","-":"minus","=":"equal","/":"slash","\\":"backslash",
         ";":"semicolon","'":"apostrophe","[":"bracket_left","]":"bracket_right","`":"grave_accent"}
s = socket.socket(socket.AF_UNIX); s.settimeout(20); s.connect(sock)
f = s.makefile("rw"); f.readline()
f.write(json.dumps({"execute":"qmp_capabilities"})+"\n"); f.flush(); f.readline()
for ch in text:
    keys = []
    if ch.isupper() or ch in SHIFT:
        keys.append({"type":"qcode","data":"shift"})
        keys.append({"type":"qcode","data": SHIFT.get(ch, ch.lower())})
    elif ch in PLAIN:
        keys.append({"type":"qcode","data": PLAIN[ch]})
    elif ch.isdigit():
        keys.append({"type":"qcode","data": ch})
    else:
        keys.append({"type":"qcode","data": ch})
    f.write(json.dumps({"execute":"send-key","arguments":{"keys":keys}})+"\n"); f.flush(); f.readline()
    time.sleep(0.02)
PY
    ;;
  click)
    python3 - "$SOCK" "$2" "$3" <<'PY2'
import json, socket, sys, time
sock, x, y = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
W, H = 1440, 900
ax, ay = int(x * 32767 / W), int(y * 32767 / H)
s = socket.socket(socket.AF_UNIX); s.settimeout(20); s.connect(sock)
f = s.makefile("rw"); f.readline()
f.write(json.dumps({"execute": "qmp_capabilities"}) + "\n"); f.flush(); f.readline()
def send(events):
    f.write(json.dumps({"execute": "input-send-event", "arguments": {"events": events}}) + "\n")
    f.flush(); f.readline()
send([{"type": "abs", "data": {"axis": "x", "value": ax}},
      {"type": "abs", "data": {"axis": "y", "value": ay}}])
time.sleep(0.2)
send([{"type": "btn", "data": {"down": True,  "button": "left"}}])
time.sleep(0.1)
send([{"type": "btn", "data": {"down": False, "button": "left"}}])
PY2
    ;;
  screenshot)
    NAME="${2:-screen}"
    qmp "$(python3 -c 'import json,sys; print(json.dumps({"execute":"screendump","arguments":{"filename":sys.argv[1]}}))' "$VM/$NAME.ppm")" >/dev/null
    sleep 1
    sips -s format png "$VM/$NAME.ppm" --out "$VM/$NAME.png" >/dev/null 2>&1
    echo "$VM/$NAME.png"
    ;;
  stop)
    qmp '{"execute":"quit"}' >/dev/null 2>&1; echo "machine shut down" ;;
  *) sed -n '2,10p' "$0" ;;
esac
