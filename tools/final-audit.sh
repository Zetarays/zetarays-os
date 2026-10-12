#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# ZETA RAYS final audit: drives the virtual machine and collects the evidence.
# Assumes a VM that is already running and reachable over ssh (tools/vm.sh).
#   tools/final-audit.sh
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VM="$ROOT/tools/vm.sh"
SHOTS="$ROOT/.cache/audit"
VBM=/Applications/VirtualBox.app/Contents/MacOS/VBoxManage
VM_NAME="${ZETA_VM:-ZETA test (arm64)}"
mkdir -p "$SHOTS"

title()   { printf "\n\033[1m== %s\033[0m\n" "$*"; }
shot()    { "$VBM" controlvm "$VM_NAME" screenshotpng "$SHOTS/$1.png" >/dev/null 2>&1 && echo "   screenshot: $1.png"; }
outcome() { [ "$1" = 0 ] && echo "   OK   $2" || echo "   KO   $2"; }

title "System identity"
"$VM" sh '
echo "  name:      $(grep ^PRETTY_NAME= /etc/os-release | cut -d= -f2- | tr -d \")"
echo "  computer:  $(uname -n)"
echo "  user:      $(whoami)"
echo "  prompt:    $(whoami)@$(uname -n)"
'

title "No trace of the previous name"
"$VM" sh '
n=$(grep -rli "ra""ix" /usr/local/bin /usr/share/zeta /etc/xdg /usr/share/applications 2>/dev/null | grep -v zeta-selftest | wc -l)
echo "  files containing it: $n"
echo "  in the menu: $(python3 -c "
import gi; gi.require_version(\"Gtk\",\"4.0\")
from gi.repository import Gio
print(sum(1 for a in Gio.AppInfo.get_all() if a.should_show() and (\"ra\"+\"ix\") in (a.get_display_name() or \"\").lower()))")"
'

title "Automatic tests"
"$VM" sh 'zeta-selftest 2>&1 | tail -32'

title "The brand in the terminal"
"$VM" sh 'pkill -x foot 2>/dev/null; sleep 1; (setsid foot >/dev/null 2>&1 &); sleep 6; true' >/dev/null 2>&1
"$VM" click 640 400 >/dev/null 2>&1; sleep 1
"$VM" sh 'export YDOTOOL_SOCKET=/tmp/.ydotool_socket; ydotool type "fastfetch"; sleep 0.4; ydotool key 28:1 28:0; true' >/dev/null 2>&1
sleep 6; shot 01-terminal-logo

title "Opening files"
"$VM" sh '
mkdir -p ~/format-test && cd ~/format-test
echo "hello" > a.txt; printf "a,b\n1,2\n" > a.csv
python3 -c "
import zlib,struct
def png(p):
    d=b\"\\x89PNG\\r\\n\\x1a\\n\"
    def c(t,x):
        import struct,zlib
        return struct.pack(\">I\",len(x))+t+x+struct.pack(\">I\",zlib.crc32(t+x))
    d+=c(b\"IHDR\",struct.pack(\">IIBBBBB\",4,4,8,2,0,0,0))
    raw=b\"\".join(b\"\\x00\"+b\"\\xff\\x00\\x00\"*4 for _ in range(4))
    d+=c(b\"IDAT\",zlib.compress(raw))+c(b\"IEND\",b\"\")
    open(p,\"wb\").write(d)
png(\"a.png\")"
tar czf a.tar.gz a.txt 2>/dev/null; zip -q a.zip a.txt 2>/dev/null
printf "%%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\ntrailer<</Root 1 0 R>>\n%%%%EOF\n" > a.pdf
for f in a.txt a.csv a.png a.tar.gz a.zip a.pdf; do
  app=$(gio mime "$(gio info -a standard::content-type "$f" 2>/dev/null | grep content-type | cut -d: -f2 | tr -d " ")" 2>/dev/null | head -1)
  printf "  %-10s %s\n" "$f" "${app:-(no program)}"
done
'

title "System state"
"$VM" sh '
echo "  failed units:      $(systemctl --failed --no-legend --no-pager | grep -vc ydotool || echo 0)"
echo "  user units:        $(systemctl --user --failed --no-legend --no-pager | wc -l)"
echo "  zombie processes:  $(ps -eo stat | grep -c "^Z")"
echo "  idle CPU:          $(top -bn1 | head -3 | tail -1 | grep -oE "[0-9,.]+ id" | head -1)"
echo "  memory:            $(free -h | awk "/^Mem/{print \$3\" of \"\$2}")"
echo "  startup:           $(systemd-analyze 2>/dev/null | head -1)"
'

title "Legal documents"
"$VM" sh '
for f in LICENSES.md LICENSES.it.md PRIVACY.md PRIVACY.it.md TERMS.md TERMS.it.md COMPONENTS.csv; do
  p=/usr/share/zeta/legal/$f
  [ -f "$p" ] && printf "  %-16s %6s bytes\n" "$f" "$(stat -c%s "$p")" || echo "  $f MISSING"
done
echo "  components listed: $(($(wc -l < /usr/share/zeta/legal/COMPONENTS.csv) - 1))"
grep -m1 "installed packages\*\*" /usr/share/zeta/legal/LICENSES.md | sed "s/^/  /"
'

title "Desktop"
"$VM" sh 'pkill -x foot 2>/dev/null; sleep 2; true' >/dev/null 2>&1
shot 02-desktop
"$VM" click 65 450 right >/dev/null 2>&1; sleep 2; shot 03-right-click-menu
"$VM" sh 'export YDOTOOL_SOCKET=/tmp/.ydotool_socket; ydotool key 1:1 1:0; true' >/dev/null 2>&1

title "Settings and legal documents in the interface"
"$VM" run "zeta-settings info" >/dev/null 2>&1; sleep 8; shot 04-about
"$VM" sh 'pkill -x zeta-settings 2>/dev/null; true' >/dev/null 2>&1

echo
echo "Evidence collected in $SHOTS"
