#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Canale verso la VM di prova (solo prove: openssh non è mai nell'immagine).
#   tools/vm.sh sh 'comando'          esegue nella VM e stampa l'uscita
#   tools/vm.sh push <locale> <dest>  copia un file (anche in /usr, con sudo)
#   tools/vm.sh sync                  copia tutto l'albero ZETA RAYS modificato
#   tools/vm.sh log                   ultimi errori della sessione
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
KEY="$HOME/.raix-test/id_vm"
COMMON=(-i "$KEY" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null
        -o ConnectTimeout=15 -o LogLevel=ERROR)
SSHOPT=(-p 2222 "${COMMON[@]}")
SCPOPT=(-P 2222 "${COMMON[@]}")   # scp vuole -P maiuscola per la porta
H=zeta@127.0.0.1

case "${1:-}" in
  run)  # avvia un programma nella sessione grafica, scollegato da ssh
        shift
        "$0" sh "(setsid $* >/tmp/zeta-run.log 2>&1 </dev/null &); sleep 2; true"
        ;;
  clic) # clic assoluto nella VM: tools/vm.sh clic x y [destro|doppio]
        # ydotool usa un dispositivo virtuale la cui scala, qui, è 2:1
        # (chiedere 640,300 porta il cursore a 1280,600): si dimezza.
        X=$(( $2 / 2 )); Y=$(( $3 / 2 )); TIPO="${4:-sinistro}"
        BTN=0xC0; [ "$TIPO" = destro ] && BTN=0xC1
        CMD="ydotool mousemove -a -x $X -y $Y; sleep 0.15; ydotool click $BTN"
        [ "$TIPO" = doppio ] && CMD="$CMD; sleep 0.08; ydotool click 0xC0"
        "$0" sh "export YDOTOOL_SOCKET=/tmp/.ydotool_socket; $CMD >/dev/null 2>&1; true" ;;
  trascina) # tools/vm.sh trascina x1 y1 x2 y2   (coordinate dello schermo)
        AX=$(( $2 / 2 )); AY=$(( $3 / 2 )); BX=$(( $4 / 2 )); BY=$(( $5 / 2 ))
        MX=$(( (AX + BX) / 2 )); MY=$(( (AY + BY) / 2 ))
        "$0" sh "export YDOTOOL_SOCKET=/tmp/.ydotool_socket
          ydotool mousemove -a -x $AX -y $AY; sleep 0.3; ydotool click 0x40; sleep 0.3
          ydotool mousemove -a -x $MX -y $MY; sleep 0.3
          ydotool mousemove -a -x $BX -y $BY; sleep 0.4; ydotool click 0x80 >/dev/null 2>&1; true" ;;
  tasti) shift; "$0" sh "export YDOTOOL_SOCKET=/tmp/.ydotool_socket; ydotool type -- '$*' >/dev/null 2>&1; true" ;;
  sh)   shift
        # ambiente della sessione grafica: serve a hyprctl, gsettings, gio...
        # Ambiente della sessione grafica. Nelle VM serve GSK_RENDERER=cairo:
        # senza, GTK4 chiede buffer dmabuf che il driver virtuale rifiuta.
        PRE='export XDG_RUNTIME_DIR=/run/user/$(id -u);
             export WAYLAND_DISPLAY=wayland-1;
             export DISPLAY=:0;
             export DBUS_SESSION_BUS_ADDRESS=unix:path=$XDG_RUNTIME_DIR/bus;
             export HYPRLAND_INSTANCE_SIGNATURE=$(ls -t $XDG_RUNTIME_DIR/hypr 2>/dev/null | head -1);
             export GSK_RENDERER=${GSK_RENDERER:-cairo};
             export XWAYLAND_NO_GLAMOR=1;'
        ssh "${SSHOPT[@]}" "$H" "$PRE $*" ;;
  push)
    L="$2"; D="$3"
    scp "${SCPOPT[@]}" -q "$L" "$H:/tmp/.push" || exit 1
    ssh "${SSHOPT[@]}" "$H" "echo zeta | sudo -S install -m ${4:-755} /tmp/.push '$D' 2>/dev/null && echo ok" ;;
  sync)
    # tutto ciò che sta in usr/local/bin e usr/lib/zeta, in un colpo solo
    cd "$ROOT/live-build/config/includes.chroot" || exit 1
    tar czf /tmp/zeta-sync.tgz usr/local/bin usr/lib/zeta usr/share/zeta usr/share/icons/zeta usr/share/glib-2.0/schemas etc/skel/.config etc/xdg 2>/dev/null
    scp "${SCPOPT[@]}" -q /tmp/zeta-sync.tgz "$H:/tmp/" || exit 1
    ssh "${SSHOPT[@]}" "$H" 'echo zeta | sudo -S tar xzf /tmp/zeta-sync.tgz -C / --no-same-owner 2>/dev/null
      echo zeta | sudo -S chmod 755 /usr/local/bin/* 2>/dev/null
      # la configurazione utente viene da etc/skel
      cp -r /etc/skel/.config/hypr /etc/skel/.config/waybar $HOME/.config/ 2>/dev/null
      echo sincronizzato' ;;
  log)
    ssh "${SSHOPT[@]}" "$H" 'journalctl --user -p warning -n 40 --no-pager 2>/dev/null | tail -40;
      echo "--- hyprland ---"; grep -iE "error|traceback|critical" $HOME/.local/share/zeta/hyprland.log 2>/dev/null | tail -20' ;;
  *) sed -n '2,7p' "$0" ;;
esac
