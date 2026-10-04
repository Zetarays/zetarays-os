#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Ricompila Hyprland 0.55.2 (sorgente Debian ufficiale, trixie-backports) con
# la correzione ufficiale #15416 (Hyprland 0.56.0): «desktop/popup: fix crash
# on destroy». Senza, chiudere di colpo un programma che ha un menu a comparsa
# aperto (Firefox che si pianta, uscita forzata) fa cadere tutto il desktop.
#   tools/build-hyprland-zeta.sh arm64|amd64
set -euo pipefail
ARCH="$1"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/cache/hyprland-zeta/$ARCH"
mkdir -p "$OUT"
docker run --rm --platform "linux/$ARCH" -e PARALLELO="${PARALLELO:-}" -v "$OUT:/out" debian:trixie bash -euxo pipefail -c '
  echo "deb http://deb.debian.org/debian trixie-backports main" > /etc/apt/sources.list.d/bp.list
  echo "deb-src http://deb.debian.org/debian trixie-backports main" >> /etc/apt/sources.list.d/bp.list
  apt-get update -qq
  apt-get install -y -qq --no-install-recommends build-essential devscripts dpkg-dev fakeroot python3 >/dev/null
  # Stesse librerie dell Hyprland ufficiale di trixie-backports (compilato con
  # aquamarine 0.11 -> dipende da libaquamarine10): nel frattempo i backports
  # sono passati ad aquamarine 0.14, ma il binario ufficiale e le immagini usano
  # la 0.11. Si ricompila aquamarine 0.11 (sorgente Debian ufficiale) e la si
  # blocca, cosi l unica differenza rispetto al pacchetto ufficiale resta la correzione.
  AQ=0.11.0-2~bpo13+1
  apt-get build-dep -y -qq aquamarine=$AQ >/dev/null
  mkdir -p /aq && cd /aq
  apt-get source -qq aquamarine=$AQ
  (cd aquamarine-0.11.0 && DEB_BUILD_OPTIONS="nocheck parallel=${PARALLELO:-$(nproc)}" dpkg-buildpackage -b -uc -us 2>&1 | tail -2)
  apt-get install -y -qq --allow-downgrades ./libaquamarine10_${AQ}_*.deb ./libaquamarine-dev_${AQ}_*.deb >/dev/null
  apt-mark hold libaquamarine-dev libaquamarine10
  cd /
  apt-get build-dep -y -qq -t trixie-backports hyprland >/dev/null
  dpkg -l libaquamarine-dev | tail -1
  mkdir -p /src && cd /src
  apt-get source -qq -t trixie-backports hyprland
  cd hyprland-0.55.2*/
  python3 - <<PY
import io
p = "src/desktop/view/Popup.cpp"
s = io.open(p, encoding="utf-8").read()
def rep(a, b):
    global s
    assert s.count(a) == 1, ("NON TROVATO", a)
    s = s.replace(a, b)
rep("""    if (!m_resource)
        return m_lastPos;

    WP<CPopup> current = m_self;""", """    if (!m_resource || m_resource->m_surface.expired())
        return m_lastPos;

    WP<CPopup> current = m_self;""")
rep("""    while (current->m_parent && current->m_resource) {

        offset += current->wlSurface()->resource()->m_current.offset;""",
"""    while (current->m_parent && current->m_resource) {
        const auto SURFACE = current->wlSurface();
        if (!SURFACE || !SURFACE->resource())
            return m_lastPos;

        offset += SURFACE->resource()->m_current.offset;""")
io.open(p, "w", encoding="utf-8").write(s)
print("correzione 1/2 applicata")
PY
  grep -n -A4 "const auto SURFACE = current->wlSurface();" src/desktop/view/Popup.cpp
  python3 - <<PY
import io, re
p = "src/desktop/view/Popup.cpp"
s = io.open(p, encoding="utf-8").read()
m = re.search(r"CPopup::popupTreeExtents\(\) const \{[\s\S]*?if \(!popup\)\n(\s*)continue;\n", s)
assert m, "popupTreeExtents non trovato"
ind = m.group(1)
agg = (ind + "// a popup whose xdg surface has been destroyed but the XDGPopupResource not yet received onDestroy()\n"
       + ind + "if (popup->m_resource && popup->m_resource->m_surface.expired())\n" + ind + "    continue;\n")
s = s[:m.end()] + "\n" + agg + s[m.end():]
io.open(p, "w", encoding="utf-8").write(s)
print("correzione 2/2 applicata")
PY
  DEBEMAIL="zeta@zetarays.org" DEBFULLNAME="ZETA RAYS" dch --local +zeta "Correzione ufficiale #15416 (Hyprland 0.56.0): niente crash quando un menu a comparsa viene distrutto con la sua finestra."
  DEB_BUILD_OPTIONS="nocheck parallel=${PARALLELO:-$(nproc)}" dpkg-buildpackage -b -uc -us 2>&1 | tail -5
  dpkg-deb -f ../hyprland_*zeta1_*.deb Depends | tr "," "\n" | grep -E "aquamarine|hypr"
  dpkg-deb -f ../hyprland_*zeta1_*.deb Depends | grep -q "libaquamarine10 " || { echo "DIPENDENZE DIVERSE DALL UFFICIALE"; exit 1; }
  rm -f /out/*.deb
  cp -v ../*.deb /out/
  # le intestazioni di aquamarine 0.11 servono anche per compilare hyprbars
  cp -v /aq/libaquamarine10_*.deb /aq/libaquamarine-dev_*.deb /out/
'
ls -la "$OUT"
