#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Rebuilds Hyprland 0.55.2 (official Debian source, trixie-backports) with
# two fixes:
#  - the official #15416 (Hyprland 0.56.0), «desktop/popup: fix crash on
#    destroy»: without it, abruptly closing a program with a popup menu open
#    (Firefox hanging, a forced quit) takes down the whole desktop;
#  - the request for a maximized window made at startup, which was discarded
#    (the official Blender stayed tiny).
#   tools/build-hyprland-zeta.sh arm64|amd64
set -euo pipefail
ARCH="$1"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/cache/hyprland-zeta/$ARCH"
mkdir -p "$OUT"
# Debian backports keep changing: since October 3, 2026 hyprutils 0.14 no
# longer builds aquamarine 0.11 or Hyprland 0.55.2. We build against the
# backports as they were on September 27, 2026 (snapshot.debian.org), i.e.
# the same libraries as the official package and the images: reproducible build.
SNAP="${SNAPSHOT:-20260927T000000Z}"
docker run --rm --platform "linux/$ARCH" -e PARALLEL="${PARALLEL:-}" -e SNAP="$SNAP" -v "$OUT:/out" debian:trixie bash -euxo pipefail -c '
  echo "deb [check-valid-until=no] http://snapshot.debian.org/archive/debian/$SNAP trixie-backports main" > /etc/apt/sources.list.d/bp.list
  echo "deb-src [check-valid-until=no] http://snapshot.debian.org/archive/debian/$SNAP trixie-backports main" >> /etc/apt/sources.list.d/bp.list
  echo "Acquire::Retries \"5\";" > /etc/apt/apt.conf.d/80retry
  apt-get update -qq
  apt-get install -y -qq --no-install-recommends build-essential devscripts dpkg-dev fakeroot python3 >/dev/null
  # Same libraries as the official trixie-backports Hyprland (built with
  # aquamarine 0.11 -> depends on libaquamarine10): meanwhile the backports
  # moved to aquamarine 0.14, but the official binary and the images use
  # 0.11. We rebuild aquamarine 0.11 (official Debian source) and hold it,
  # so the only difference from the official package remains the fix.
  AQ=0.11.0-2~bpo13+1
  apt-get build-dep -y -qq aquamarine=$AQ >/dev/null
  mkdir -p /aq && cd /aq
  apt-get source -qq aquamarine=$AQ
  (cd aquamarine-0.11.0 && DEB_BUILD_OPTIONS="nocheck parallel=${PARALLEL:-$(nproc)}" dpkg-buildpackage -b -uc -us 2>&1 | tail -15)
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
    assert s.count(a) == 1, ("NOT FOUND", a)
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
print("fix 1/2 applied")
PY
  grep -n -A4 "const auto SURFACE = current->wlSurface();" src/desktop/view/Popup.cpp
  python3 - <<PY
import io, re
p = "src/desktop/view/Popup.cpp"
s = io.open(p, encoding="utf-8").read()
m = re.search(r"CPopup::popupTreeExtents\(\) const \{[\s\S]*?if \(!popup\)\n(\s*)continue;\n", s)
assert m, "popupTreeExtents not found"
indent = m.group(1)
addition = (indent + "// a popup whose xdg surface has been destroyed but the XDGPopupResource not yet received onDestroy()\n"
       + indent + "if (popup->m_resource && popup->m_resource->m_surface.expired())\n" + indent + "    continue;\n")
s = s[:m.end()] + "\n" + addition + s[m.end():]
io.open(p, "w", encoding="utf-8").write(s)
print("fix 2/2 applied")
PY
  # Fix 3: a request for a maximized window made by a program BEFORE it
  # appears (xdg_toplevel.set_maximized before the first commit, or
  # _NET_WM_STATE_MAXIMIZED on X11) was discarded: onUpdateState handled it
  # only for already mapped windows, while the fullscreen request is
  # remembered (m_wantsInitialFullscreen). The program (the official Blender,
  # which starts that way) believes it is maximized and stays at the
  # provisional size, sometimes tiny. Now the request is remembered and
  # applied on map, honoring suppress_event maximize as onMap already does.
  python3 - <<PY
import io
def rep(p, a, b):
    s = io.open(p, encoding="utf-8").read()
    assert s.count(a) == 1, ("NOT FOUND", p, a)
    io.open(p, "w", encoding="utf-8").write(s.replace(a, b))
rep("src/desktop/view/Window.hpp",
    "        bool      m_wantsInitialFullscreen        = false;\n",
    "        bool      m_wantsInitialFullscreen        = false;\n        bool      m_wantsInitialMaximize          = false;\n")
rep("src/desktop/view/Window.cpp",
    """    if (requestsMX.has_value() && !(m_suppressedEvents & SUPPRESS_MAXIMIZE)) {
        if (m_isMapped) {""",
    """    if (requestsMX.has_value() && !(m_suppressedEvents & SUPPRESS_MAXIMIZE)) {
        if (!m_isMapped)
            m_wantsInitialMaximize = requestsMX.value();
        if (m_isMapped) {""")
rep("src/desktop/view/Window.cpp",
    """    if (m_wantsInitialFullscreen || (m_isX11 && m_xwaylandSurface->m_fullscreen))
        requestedClientFSMode = FSMODE_FULLSCREEN;
""",
    """    if (m_wantsInitialFullscreen || (m_isX11 && m_xwaylandSurface->m_fullscreen))
        requestedClientFSMode = FSMODE_FULLSCREEN;
    else if (m_wantsInitialMaximize)
        requestedClientFSMode = FSMODE_MAXIMIZED;
""")
print("fix 3 applied (initial maximize)")
PY
  DEBEMAIL="zeta@zetarays.org" DEBFULLNAME="ZETA RAYS" dch -v "$(dpkg-parsechangelog -S Version)+zeta2" "Official fix #15416 (Hyprland 0.56.0): no crash when a popup menu is destroyed together with its window. A maximized window requested at startup is now honored (previously it was discarded)."
  DEB_BUILD_OPTIONS="nocheck parallel=${PARALLEL:-$(nproc)}" dpkg-buildpackage -b -uc -us 2>&1 | tail -5
  dpkg-deb -f ../hyprland_*zeta2_*.deb Depends | tr "," "\n" | grep -E "aquamarine|hypr"
  dpkg-deb -f ../hyprland_*zeta2_*.deb Depends | grep -q "libaquamarine10 " || { echo "DEPENDENCIES DIFFER FROM THE OFFICIAL PACKAGE"; exit 1; }
  rm -f /out/*.deb
  cp -v ../*.deb /out/
  # the aquamarine 0.11 headers are also needed to build hyprbars
  cp -v /aq/libaquamarine10_*.deb /aq/libaquamarine-dev_*.deb /out/
'
ls -la "$OUT"
