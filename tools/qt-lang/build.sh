#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-or-later
# Qt translations of the QML screens that are not GTK apps: the SDDM login
# theme and the Calamares slideshow. Their QML uses qsTr() with the English
# text; the translations are the .ts files in this folder, compiled to the .qm
# files the image ships:
#
#   sddm-zeta_<lang>.ts      -> usr/share/sddm/themes/zeta/translations/<lang>.qm
#                               (SDDM: TranslationsDirectory in metadata.desktop)
#   calamares-zeta_<lang>.ts -> etc/calamares/branding/zeta/lang/calamares-zeta_<lang>.qm
#                               (Calamares: lang/ folder of the branding)
#
# After changing a QML text: lupdate FILE.qml -ts THIS.ts -locations none,
# translate, then run this script (needs lrelease: package qt6-l10n-tools).
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
CHROOT="$HERE/../../live-build/config/includes.chroot"
LRELEASE=$(command -v lrelease || echo /usr/lib/qt6/bin/lrelease)
SDDM="$CHROOT/usr/share/sddm/themes/zeta/translations"
CAL="$CHROOT/etc/calamares/branding/zeta/lang"
mkdir -p "$SDDM" "$CAL"
for ts in "$HERE"/sddm-zeta_*.ts; do
    lang=${ts##*/sddm-zeta_}
    "$LRELEASE" -silent "$ts" -qm "$SDDM/${lang%.ts}.qm"
done
for ts in "$HERE"/calamares-zeta_*.ts; do
    "$LRELEASE" -silent "$ts" -qm "$CAL/$(basename "${ts%.ts}").qm"
done
