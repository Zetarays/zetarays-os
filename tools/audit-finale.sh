#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Audit finale di ZETA RAYS: guida la macchina virtuale e raccoglie le prove.
# Presuppone una VM già accesa e raggiungibile via ssh (tools/vm.sh).
#   tools/audit-finale.sh
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VM="$ROOT/tools/vm.sh"
FOTO="$ROOT/.cache/audit"
VBM=/Applications/VirtualBox.app/Contents/MacOS/VBoxManage
NOME="${ZETA_VM:-ZETA prova (arm64)}"
mkdir -p "$FOTO"

titolo() { printf "\n\033[1m== %s\033[0m\n" "$*"; }
foto()   { "$VBM" controlvm "$NOME" screenshotpng "$FOTO/$1.png" >/dev/null 2>&1 && echo "   foto: $1.png"; }
esito()  { [ "$1" = 0 ] && echo "   OK   $2" || echo "   KO   $2"; }

titolo "Identità del sistema"
"$VM" sh '
echo "  nome:      $(grep ^PRETTY_NAME= /etc/os-release | cut -d= -f2- | tr -d \")"
echo "  computer:  $(uname -n)"
echo "  utente:    $(whoami)"
echo "  prompt:    $(whoami)@$(uname -n)"
'

titolo "Nessuna traccia del nome precedente"
"$VM" sh '
n=$(grep -rli "ra""ix" /usr/local/bin /usr/share/zeta /etc/xdg /usr/share/applications 2>/dev/null | grep -v zeta-prove | wc -l)
echo "  file che lo contengono: $n"
echo "  nel menù: $(python3 -c "
import gi; gi.require_version(\"Gtk\",\"4.0\")
from gi.repository import Gio
print(sum(1 for a in Gio.AppInfo.get_all() if a.should_show() and (\"ra\"+\"ix\") in (a.get_display_name() or \"\").lower()))")"
'

titolo "Prove automatiche"
"$VM" sh 'zeta-prove 2>&1 | tail -32'

titolo "Il marchio nel terminale"
"$VM" sh 'pkill -x foot 2>/dev/null; sleep 1; (setsid foot >/dev/null 2>&1 &); sleep 6; true' >/dev/null 2>&1
"$VM" clic 640 400 >/dev/null 2>&1; sleep 1
"$VM" sh 'export YDOTOOL_SOCKET=/tmp/.ydotool_socket; ydotool type "fastfetch"; sleep 0.4; ydotool key 28:1 28:0; true' >/dev/null 2>&1
sleep 6; foto 01-terminale-logo

titolo "Aprire i file"
"$VM" sh '
mkdir -p ~/prova-formati && cd ~/prova-formati
echo "ciao" > a.txt; printf "a,b\n1,2\n" > a.csv
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
  printf "  %-10s %s\n" "$f" "${app:-(nessun programma)}"
done
'

titolo "Stato del sistema"
"$VM" sh '
echo "  unità fallite:     $(systemctl --failed --no-legend --no-pager | grep -vc ydotool || echo 0)"
echo "  unità utente:      $(systemctl --user --failed --no-legend --no-pager | wc -l)"
echo "  processi zombie:   $(ps -eo stat | grep -c "^Z")"
echo "  CPU a riposo:      $(top -bn1 | head -3 | tail -1 | grep -oE "[0-9,]+ id" | head -1)"
echo "  memoria:           $(free -h | awk "/^Mem/{print \$3\" su \"\$2}")"
echo "  avvio:             $(systemd-analyze 2>/dev/null | head -1)"
'

titolo "Documenti legali"
"$VM" sh '
for f in LICENZE.md LICENZE.it.md PRIVACY.md PRIVACY.it.md CONDIZIONI.md CONDIZIONI.it.md COMPONENTI.csv; do
  p=/usr/share/zeta/legale/$f
  [ -f "$p" ] && printf "  %-16s %6s byte\n" "$f" "$(stat -c%s "$p")" || echo "  $f MANCA"
done
echo "  componenti elencati: $(($(wc -l < /usr/share/zeta/legale/COMPONENTI.csv) - 1))"
grep -m1 "installed packages\*\*" /usr/share/zeta/legale/LICENZE.md | sed "s/^/  /"
'

titolo "Scrivania"
"$VM" sh 'pkill -x foot 2>/dev/null; sleep 2; true' >/dev/null 2>&1
foto 02-scrivania
"$VM" clic 65 450 destro >/dev/null 2>&1; sleep 2; foto 03-menu-tasto-destro
"$VM" sh 'export YDOTOOL_SOCKET=/tmp/.ydotool_socket; ydotool key 1:1 1:0; true' >/dev/null 2>&1

titolo "Impostazioni e documenti legali nell'interfaccia"
"$VM" run "zeta-impostazioni info" >/dev/null 2>&1; sleep 8; foto 04-informazioni
"$VM" sh 'pkill -x zeta-impostazioni 2>/dev/null; true' >/dev/null 2>&1

echo
echo "Prove raccolte in $FOTO"
