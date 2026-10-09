#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# ZETA RAYS — risorse del menu di avvio: GRUB (UEFI, chiavetta e sistema
# installato) e isolinux (BIOS, chiavetta). Uno stile solo per tutti:
# nero, logo piccolo in alto, voci in colonna, la scelta segnata da una
# fascia appena piu' chiara con una barretta blu a sinistra. Niente icone,
# niente riquadri arrotondati, testo di misura normale.
#
#   tools/gen-tema-grub.sh
#
# Produce:
#   live-build/config/bootloaders/grub-pc/live-theme/
#     roboto-medium-16.pf2, roboto-medium-13.pf2   font di GRUB
#     select_*.png                                 fascia della voce scelta
#     logo.png                                     simbolo + scritta
#   live-build/config/bootloaders/syslinux_common/splash.png
#     sfondo di isolinux 1024x768 (live-build non lo riconverte da
#     splash.svg a 640x480 se trova gia' splash.png)
# Gira in un contenitore Debian (grub-mkfont e rsvg-convert): sul Mac non ci
# sono. Le risorse prodotte stanno nel progetto: la costruzione non lo richiama.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$ROOT/live-build/config/bootloaders/grub-pc/live-theme"
SYSL="$ROOT/live-build/config/bootloaders/syslinux_common"
# cartella temporanea sotto il progetto: colima monta solo la home
mkdir -p "$ROOT/.cache"; TMP="$(mktemp -d "$ROOT/.cache/tema-grub.XXXXXX")"
trap 'rm -rf "${TMP:?}"' EXIT
mkdir -p "$DEST"

# Disegni del marchio (tracciati ufficiali, tools/marchio-zeta.json)
python3 - "$TMP" "$ROOT" <<'PY'
import json, os, sys
out, root = sys.argv[1], sys.argv[2]
M = json.load(open(os.path.join(root, "tools", "marchio-zeta.json")))
X = 'xmlns="http://www.w3.org/2000/svg"'
# Il marchio ufficiale intero (simbolo e scritta nelle proporzioni del
# disegno originale), come sulla schermata di accesso
ix, iy, iw, ih = M["riquadro_intero"]
marchio = '<path d="%s"/>' % M["simbolo"] + "".join('<path d="%s"/>' % d for d in M["scritta"])


def logo(H):
    W = H * iw / ih
    corpo = ('<svg width="%.2f" height="%.2f" viewBox="%g %g %g %g"><g fill="#FFFFFF" '
             'fill-rule="nonzero">%s</g></svg>' % (W, H, ix, iy, iw, ih, marchio))
    return W, H, corpo


# GRUB: 84 px di altezza (prima 120)
W, H, corpo = logo(84)
W, H = int(round(W)) + 2, int(round(H)) + 2
open(os.path.join(out, "logo.svg"), "w").write(
    '<svg %s width="%d" height="%d"><g transform="translate(1 1)">%s</g></svg>' % (X, W, H, corpo))
open(os.path.join(out, "logo.size"), "w").write("%d %d\n" % (W, H))

# isolinux 1024x768: la colonna del menu comincia alla riga 19 (y 304), il
# logo sta sopra, centrato
W2, H2, corpo2 = logo(88)
top = 304 - 52 - H2
open(os.path.join(out, "splash.svg"), "w").write(
    '<svg %s width="1024" height="768"><rect width="1024" height="768" fill="#000000"/>'
    '<g transform="translate(%.2f %.2f)">%s</g></svg>' % (X, (1024 - W2) / 2, top, corpo2))
PY

docker run --rm -v "$DEST:/out" -v "$SYSL:/sysl" -v "$TMP:/tmp/zeta:ro" debian:trixie bash -euo pipefail -c '
export DEBIAN_FRONTEND=noninteractive; apt-get update -qq >/dev/null
apt-get install -y -qq --no-install-recommends grub-common fonts-roboto-unhinted librsvg2-bin >/dev/null
F=/usr/share/fonts/truetype/roboto/unhinted/RobotoTTF
# latino, latino esteso, greco, cirillico, frecce e punteggiatura: le voci
# del sistema installato possono essere tradotte; per gli altri alfabeti
# GRUB ripiega da solo su unicode.pf2
R=0x20-0x24F,0x370-0x3FF,0x400-0x4FF,0x2010-0x2027,0x2190-0x2193,0x25B8-0x25B8
# GRUB disegna i font senza smussatura (bitmap a 1 bit): Medium con
# autohinting resta pulito. 16 px le voci, 13 px le indicazioni: misure da
# schermo vero (la risoluzione ora e quella nativa, non 1280x800 stirato).
rm -f /out/roboto-*.pf2
grub-mkfont -r $R -s 16 -a -n "Roboto Medium" -o /out/roboto-medium-16.pf2 $F/Roboto-Medium.ttf
grub-mkfont -r $R -s 13 -a -n "Roboto Medium" -o /out/roboto-medium-13.pf2 $F/Roboto-Medium.ttf

svg() { rsvg-convert -o "$1" /dev/stdin; }
X="xmlns=\"http://www.w3.org/2000/svg\""
# Fascia della voce scelta, nove pezzi (GRUB la allarga alla misura della
# voce): fondo #16161A pieno, barretta blu di 3 px a sinistra, angoli vivi.
# Il pezzo di sinistra e largo 18 px: e anche il rientro del testo.
FONDO="#16161A"; BLU="#3A8DFF"
pezzo() {  # nome larghezza altezza barretta(0/1)
  if [ "$4" = 1 ]; then
    printf "%s" "<svg $X width=\"$2\" height=\"$3\"><rect width=\"$2\" height=\"$3\" fill=\"$FONDO\"/><rect width=\"3\" height=\"$3\" fill=\"$BLU\"/></svg>" | svg "/out/select_$1.png"
  else
    printf "%s" "<svg $X width=\"$2\" height=\"$3\"><rect width=\"$2\" height=\"$3\" fill=\"$FONDO\"/></svg>" | svg "/out/select_$1.png"
  fi
}
pezzo nw 18 1 1; pezzo n 1 1 0; pezzo ne 10 1 0
pezzo w 18 1 1;  pezzo c 1 1 0; pezzo e 10 1 0
pezzo sw 18 1 1; pezzo s 1 1 0; pezzo se 10 1 0
rsvg-convert -o /out/logo.png /tmp/zeta/logo.svg
rsvg-convert -o /sysl/splash.png /tmp/zeta/splash.svg
# le icone delle voci non si usano piu
rm -rf /out/icons
chown -R '"$(id -u):$(id -g)"' /out /sysl/splash.png
'
echo "logo: $(cat "$TMP/logo.size")"
ls -la "$DEST" "$SYSL/splash.png"
