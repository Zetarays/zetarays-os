#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Anteprima dell'interfaccia ZETA RAYS senza costruire l'ISO:
# avvia un compositor Wayland "headless" in un container Debian 13 e
# fa screenshot di barra, launcher, Impostazioni e schermata di accesso.
# Nota: l'anteprima usa sway (headless) al posto di Hyprland, quindi
# sfocatura, ombre e bordi delle finestre qui non si vedono.
# Uso: tools/preview.sh [#RRGGBB]
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/.cache/preview"
ACCENT="${1:-#3A8DFF}"
mkdir -p "$OUT"
python3 "$ROOT/tools/gen-assets.py" >/dev/null

cat > "$OUT/session.sh" <<'EOS'
export XDG_RUNTIME_DIR=/tmp/xdg LANG=it_IT.UTF-8 HOME=/home/zeta
export WLR_BACKENDS=headless WLR_LIBINPUT_NO_DEVICES=1 WLR_RENDERER=pixman
printf 'output HEADLESS-1 resolution 1440x900\ndefault_border none\n' > /tmp/sway.conf
sway -c /tmp/sway.conf >/tmp/sway.log 2>&1 &
for i in $(seq 50); do [ -S /tmp/xdg/wayland-1 ] && break; sleep 0.2; done
export WAYLAND_DISPLAY=wayland-1

zeta-accent "$ACCENT"
swaybg -m fill -i ~/.config/zeta/wallpaper.png >/dev/null 2>&1 &
waybar >/tmp/waybar.log 2>&1 &
sleep 4
grim /out/1-desktop.png

zeta-launcher >/tmp/launcher.log 2>&1 &
LP=$!
sleep 4
grim /out/2-launcher.png
kill $LP 2>/dev/null || true
sleep 1

zeta-impostazioni >/tmp/impostazioni.log 2>&1 &
IP=$!
sleep 4
grim /out/3-impostazioni.png
kill $IP 2>/dev/null || true
sleep 1

QT_QPA_PLATFORM=wayland sddm-greeter-qt6 --test-mode --theme /usr/share/sddm/themes/zeta >/tmp/greeter.log 2>&1 &
GP=$!
sleep 6
grim /out/4-accesso.png
kill $GP 2>/dev/null || true
EOS

docker run --rm --privileged --platform linux/arm64 \
  -v "$ROOT/live-build/config/includes.chroot:/zeta:ro" -v "$OUT:/out" \
  debian:trixie bash -euc '
    export DEBIAN_FRONTEND=noninteractive
    echo "deb http://deb.debian.org/debian trixie-backports main" > /etc/apt/sources.list.d/bp.list
    apt-get update -qq >/dev/null
    apt-get install -y -qq --no-install-recommends \
      sway waybar swaybg mako-notifier foot grim librsvg2-bin fonts-roboto-unhinted fonts-jetbrains-mono fonts-font-awesome \
      python3 python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 gir1.2-gtk4layershell-1.0 libgtk4-layer-shell0 \
      adwaita-icon-theme gnome-calculator gnome-text-editor thunar mpv evince eog file-roller firefox-esr synaptic \
      gnome-system-monitor sddm qml6-module-qtquick qt6-svg-plugins qt6-wayland locales dbus dbus-user-session procps \
      >/dev/null 2>&1
    sed -i "s/^# *it_IT.UTF-8/it_IT.UTF-8/" /etc/locale.gen && locale-gen >/dev/null
    cp -r /zeta/usr/local/bin/* /usr/local/bin/ && chmod +x /usr/local/bin/zeta-*
    cp -r /zeta/usr/share/. /usr/share/
    gtk-update-icon-cache -f /usr/share/icons/zeta >/dev/null 2>&1 || true
    useradd -m -s /bin/bash zeta && cp -r /zeta/etc/skel/.config /home/zeta/ && chown -R zeta /home/zeta
    mkdir -p /tmp/xdg && chown zeta /tmp/xdg && chmod 700 /tmp/xdg
    su zeta -c "ACCENT=\"'"$ACCENT"'\" dbus-run-session -- bash /out/session.sh" || true
    for f in waybar launcher impostazioni greeter; do
      echo "===== $f"; grep -viE "^$|debug|\] \[info\]" /tmp/$f.log | tail -12 || true
    done
  '
rm -f "$OUT/session.sh"
echo "Screenshot in $OUT"
