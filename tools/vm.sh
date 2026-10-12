#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Channel to the test VM (testing only: openssh is never in the image).
#   tools/vm.sh sh 'command'          runs in the VM and prints the output
#   tools/vm.sh push <local> <dest>   copies a file (even into /usr, with sudo)
#   tools/vm.sh sync                  copies the whole modified ZETA RAYS tree
#   tools/vm.sh log                   latest errors of the session
#   tools/vm.sh run 'program'         starts a program in the graphical session
#   tools/vm.sh click x y [right|double], drag x1 y1 x2 y2, keys 'text'
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
KEY="$HOME/.raix-test/id_vm"
COMMON=(-i "$KEY" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null
        -o ConnectTimeout=15 -o LogLevel=ERROR)
SSHOPT=(-p 2222 "${COMMON[@]}")
SCPOPT=(-P 2222 "${COMMON[@]}")   # scp wants an uppercase -P for the port
H=zeta@127.0.0.1

case "${1:-}" in
  run)  # starts a program in the graphical session, detached from ssh
        shift
        "$0" sh "(setsid $* >/tmp/zeta-run.log 2>&1 </dev/null &); sleep 2; true"
        ;;
  click) # absolute click in the VM: tools/vm.sh click x y [right|double]
        # ydotool uses a virtual device whose scale here is 2:1
        # (asking for 640,300 moves the cursor to 1280,600): so halve it.
        X=$(( $2 / 2 )); Y=$(( $3 / 2 )); KIND="${4:-left}"
        BTN=0xC0; [ "$KIND" = right ] && BTN=0xC1
        CMD="ydotool mousemove -a -x $X -y $Y; sleep 0.15; ydotool click $BTN"
        [ "$KIND" = double ] && CMD="$CMD; sleep 0.08; ydotool click 0xC0"
        "$0" sh "export YDOTOOL_SOCKET=/tmp/.ydotool_socket; $CMD >/dev/null 2>&1; true" ;;
  drag) # tools/vm.sh drag x1 y1 x2 y2   (screen coordinates)
        AX=$(( $2 / 2 )); AY=$(( $3 / 2 )); BX=$(( $4 / 2 )); BY=$(( $5 / 2 ))
        MX=$(( (AX + BX) / 2 )); MY=$(( (AY + BY) / 2 ))
        "$0" sh "export YDOTOOL_SOCKET=/tmp/.ydotool_socket
          ydotool mousemove -a -x $AX -y $AY; sleep 0.3; ydotool click 0x40; sleep 0.3
          ydotool mousemove -a -x $MX -y $MY; sleep 0.3
          ydotool mousemove -a -x $BX -y $BY; sleep 0.4; ydotool click 0x80 >/dev/null 2>&1; true" ;;
  keys) shift; "$0" sh "export YDOTOOL_SOCKET=/tmp/.ydotool_socket; ydotool type -- '$*' >/dev/null 2>&1; true" ;;
  sh)   shift
        # graphical session environment: needed by hyprctl, gsettings, gio...
        # In VMs GSK_RENDERER=cairo is needed: without it, GTK4 asks for
        # dmabuf buffers that the virtual driver rejects.
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
    # everything in usr/local/bin and usr/lib/zeta, in one go
    cd "$ROOT/live-build/config/includes.chroot" || exit 1
    tar czf /tmp/zeta-sync.tgz usr/local/bin usr/lib/zeta usr/share/zeta usr/share/icons/zeta usr/share/glib-2.0/schemas etc/skel/.config etc/xdg 2>/dev/null
    scp "${SCPOPT[@]}" -q /tmp/zeta-sync.tgz "$H:/tmp/" || exit 1
    ssh "${SSHOPT[@]}" "$H" 'echo zeta | sudo -S tar xzf /tmp/zeta-sync.tgz -C / --no-same-owner 2>/dev/null
      echo zeta | sudo -S chmod 755 /usr/local/bin/* 2>/dev/null
      # the user configuration comes from etc/skel
      cp -r /etc/skel/.config/hypr /etc/skel/.config/waybar $HOME/.config/ 2>/dev/null
      echo synced' ;;
  log)
    ssh "${SSHOPT[@]}" "$H" 'journalctl --user -p warning -n 40 --no-pager 2>/dev/null | tail -40;
      echo "--- hyprland ---"; grep -iE "error|traceback|critical" $HOME/.local/share/zeta/hyprland.log 2>/dev/null | tail -20' ;;
  *) sed -n '2,9p' "$0" ;;
esac
