#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Generates the ZETA RAYS graphic assets (icons, logo, wallpaper, login icons)
# from the same shapes used in the design (design/gen.py).
import os
import pathlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHROOT = os.path.join(ROOT, "live-build", "config", "includes.chroot")

src = open(os.path.join(ROOT, "design", "gen.py")).read().split("desktop(); launcher()")[0]
ns = {"__file__": os.path.join(ROOT, "design", "gen.py")}
exec(src, ns)
ICONS = ns["ICONS"]
XMLNS = 'xmlns="http://www.w3.org/2000/svg"'

# The logo shape lives in one place only: tools/wordmark-zeta.json, extracted
# from the original vector file (tools/gen-wordmark.py). The paths are FILLED:
# they are drawn with fill, not with stroke like the previous logo.
import json
_M = json.load(open(os.path.join(ROOT, "tools", "wordmark-zeta.json")))
SYMBOL = '<path d="%s"/>' % _M["symbol"]
WORDMARK = "".join('<path d="%s"/>' % d for d in _M["wordmark"])
LOGO_MARK = SYMBOL + WORDMARK
# Where the symbol appears on its own, the official path from the supplied
# vector file is used: a single path with real curves, sharper and lighter
# than the segmented version built into the full logo.
SYMBOL_ONLY = '<path d="%s"/>' % _M["symbol_original"]


def vb(name):
    """viewBox of the requested bounding box, as a string."""
    return "%.3f %.3f %.3f %.3f" % tuple(_M["bbox_" + name])


def proportional_width(name, height):
    x, y, w, h = _M["bbox_" + name]
    return round(height * w / h)


def write(rel, text):
    path = os.path.join(CHROOT, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)


# --- Logo and symbol (ACCENT is replaced at runtime) ---
logo_in = ('<svg %s viewBox="%s" fill="ACCENT" fill-rule="nonzero">%s</svg>\n'
           % (XMLNS, vb("full"), LOGO_MARK))
# Large intrinsic size (256 px): at 22 px the symbol was drawn small and then
# scaled up by the bar, and came out blurry. Starting large, it stays sharp at
# any size and on high-density screens.
_sx, _sy, _sw, _sh = _M["bbox_symbol_original"]
symbol_in = ('<svg %s width="256" height="%d" viewBox="%s" fill="ACCENT" '
              'fill-rule="nonzero">%s</svg>\n'
              % (XMLNS, round(256 * _sh / _sw),
                 "%.3f %.3f %.3f %.3f" % (_sx, _sy, _sw, _sh), SYMBOL_ONLY))
write("usr/share/zeta/brand/zeta-logo.svg.in", logo_in)
write("usr/share/zeta/brand/zeta-symbol.svg.in", symbol_in)
for name, color in (("white", "#FFFFFF"), ("black", "#000000")):
    write("usr/share/zeta/brand/zeta-logo-%s.svg" % name, logo_in.replace("ACCENT", color))

# «Supported package» icon of Synaptic and the APT tools: in Debian it is the
# Debian swirl; here it is the ZETA RAYS symbol, in the system blue.
write("usr/share/icons/zeta/scalable/apps/package-supported.svg",
      symbol_in.replace("ACCENT", "#3A8DFF").replace('width="256"', 'width="64"')
      .replace('height="%d"' % round(256 * _sh / _sw), 'height="%d"' % round(64 * _sh / _sw)))

# --- 3840x2160 wallpaper: logo in the center, in the original proportions.
# The background color is the BGCOLOR placeholder: zeta-accent replaces it with
# black or a light color depending on the chosen theme. ---
lh = 354
lw = proportional_width("full", lh)
write("usr/share/zeta/brand/zeta-wallpaper.svg.in",
      '<svg %s width="3840" height="2160" viewBox="0 0 3840 2160">'
      '<rect width="3840" height="2160" fill="BGCOLOR"/>'
      '<svg x="%s" y="%s" width="%d" height="%d" viewBox="%s">'
      '<g fill="ACCENT" fill-rule="nonzero">%s</g></svg></svg>\n'
      % (XMLNS, (3840 - lw) / 2, (2160 - lh) / 2, lw, lh, vb("full"), LOGO_MARK))



ICONS["shield"] = '<path d="M12 3l7 3v5c0 4.5-3 8-7 10-4-2-7-5.5-7-10V6z"/><path d="M9 12l2 2 4-4"/>'
ICONS["core"] = '<circle cx="12" cy="12" r="2.2"/><circle cx="12" cy="12" r="7.5" stroke-opacity="0.5"/><circle cx="12" cy="4.5" r="0.9" fill="currentColor" stroke="none"/><circle cx="19" cy="14" r="0.9" fill="currentColor" stroke="none"/><circle cx="5.5" cy="15" r="0.9" fill="currentColor" stroke="none"/>'
ICONS["install"] = '<path d="M12 3v11M8 10l4 4 4-4"/><path d="M5 20h14"/>'
ICONS["gauge"] = '<path d="M4 15a8 8 0 0 1 16 0"/><path d="M12 15l4-4"/><circle cx="12" cy="15" r="1.3" fill="currentColor" stroke="none"/><path d="M4 15h1.5M18.5 15H20M12 7v1.5"/>'
ICONS["assistant"] = '<path d="M4 6.5A2.5 2.5 0 0 1 6.5 4h11A2.5 2.5 0 0 1 20 6.5v7A2.5 2.5 0 0 1 17.5 16H10l-4 4v-4H6.5A2.5 2.5 0 0 1 4 13.5z"/><path d="M9 10h0M12 10h0M15 10h0"/>'

# --- "zeta" icon theme: dark tiles with a light glyph ---
def tile(glyph):
    # 64x64 tile, 24x24 glyph scaled to 34px in the center
    return ('<svg %s width="64" height="64" viewBox="0 0 64 64">'
            '<rect x="0.5" y="0.5" width="63" height="63" rx="17" fill="#19191C" stroke="#FFFFFF" stroke-opacity="0.08"/>'
            '<g transform="translate(15 15) scale(1.4167)" fill="none" stroke="#EDEDEA" stroke-width="1.5" '
            'stroke-linecap="round" stroke-linejoin="round">%s</g></svg>\n' % (XMLNS, glyph))


# Printer: a sheet coming out of the body, in the same stroke as the others.
# Used both by the «Printers» entry in Settings and by the tile of the
# «Print Settings» app, which otherwise showed the standard colored icon.
ICONS["printer"] = ('<path d="M7 9V4.5h10V9"/>'
                    '<path d="M5.5 9h13a1.5 1.5 0 0 1 1.5 1.5v5a1.5 1.5 0 0 1-1.5 1.5H17"/>'
                    '<path d="M7 17H5.5A1.5 1.5 0 0 1 4 15.5v-5A1.5 1.5 0 0 1 5.5 9"/>'
                    '<path d="M7 13.5h10v6H7z"/><path d="M16.8 11.6h.01"/>')

# Place icons: Home and Trash on the desktop. The Adwaita ones (a light-blue
# house and a green bin with the recycling symbol) clash with the ZETA RAYS
# identity, so we draw versions in the system style.
# ZETA Share: the ZETA RAYS triangle (in the pyramid shape of the logo)
# sending out two waves, i.e. «to nearby devices». It used to be the generic
# share symbol (three connected dots), the same as a thousand Linux apps.
ICONS["share"] = ('<path d="M12 9.6L5.9 20.1h12.2z"/><path d="M12 9.6v6.6M12 16.2l-6.1 3.9M12 16.2l6.1 3.9" stroke-opacity="0.55"/><path d="M8.7 6.6a4.7 4.7 0 0 1 6.6 0"/><path d="M6 3.9a8.5 8.5 0 0 1 12 0"/>')
# Server: two stacked units with an indicator light, for «Connect to Server»
ICONS["server"] = ('<rect x="4" y="4" width="16" height="6.5" rx="1.6"/>'
                   '<rect x="4" y="13.5" width="16" height="6.5" rx="1.6"/>'
                   '<path d="M7.5 7.25h.01M7.5 16.75h.01M11 7.25h5.5M11 16.75h5.5"/>')
ICONS["search"] = '<circle cx="11" cy="11" r="7"/><path d="M16 16l5 5"/>'
ICONS["app"] = ('<rect x="4" y="4" width="7" height="7" rx="2"/><rect x="13" y="4" width="7" height="7" rx="2"/>'
                '<rect x="4" y="13" width="7" height="7" rx="2"/><rect x="13" y="13" width="7" height="7" rx="2"/>')
ICONS["home"] = '<path d="M3.5 11L12 4.5l8.5 6.5"/><path d="M6 9.8V19.5h12V9.8"/><path d="M10 19.5v-5h4v5"/>'
ICONS["trash"] = ('<path d="M4.5 7h15"/>'
                  '<path d="M9 7V5.2A1.7 1.7 0 0 1 10.7 3.5h2.6A1.7 1.7 0 0 1 15 5.2V7"/>'
                  '<path d="M6.6 7l1 12.3A1.7 1.7 0 0 0 9.3 21h5.4a1.7 1.7 0 0 0 1.7-1.7L17.4 7"/>'
                  '<path d="M10.3 10.8v6M13.7 10.8v6"/>')
ICONS["trash-full"] = ('<path d="M4.3 7.9l14.9-2.1"/>'
                       '<path d="M8.7 7.2l-.25-1.78A1.7 1.7 0 0 1 9.9 3.5l2.6-.36a1.7 1.7 0 0 1 1.92 1.45l.25 1.78"/>'
                       '<path d="M6.8 7.6l1.7 11.8A1.7 1.7 0 0 0 10.2 21h5.4a1.7 1.7 0 0 0 1.7-1.5l.9-11.9"/>'
                       '<path d="M10.5 11.3l.6 5.6M14 10.9l-.3 5.7"/>')

# File manager places (Thunar sidebar, disks, network, recent): without these
# the Adwaita ones showed up, colored and in different styles (the dark
# «Recent» one was almost invisible on the dark theme).
ICONS["computer"] = '<rect x="3.5" y="4.5" width="17" height="11.5" rx="2"/><path d="M9 20h6M12 16v4"/>'
ICONS["disk"] = ('<rect x="3.5" y="13" width="17" height="6.5" rx="2"/>'
                 '<path d="M5 13l2.2-7.2A1.8 1.8 0 0 1 9 4.5h6a1.8 1.8 0 0 1 1.8 1.3L19 13"/>'
                 '<path d="M16.5 16.25h.01"/>')
ICONS["network"] = ('<rect x="9" y="3.5" width="6" height="5" rx="1.2"/><rect x="3.5" y="15.5" width="6" height="5" rx="1.2"/>'
                    '<rect x="14.5" y="15.5" width="6" height="5" rx="1.2"/><path d="M12 8.5V12M6.5 15.5V12h11v3.5"/>')
ICONS["recent"] = '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>'
ICONS["usb"] = ('<path d="M8.5 3.5h7v5h-7z"/><rect x="6" y="8.5" width="12" height="12" rx="2.5"/>'
                '<path d="M10.5 6h.01M13.5 6h.01"/>')
ICONS["optical"] = '<circle cx="12" cy="12" r="8.5"/><circle cx="12" cy="12" r="2.2"/><path d="M12 6a6 6 0 0 0-6 6"/>'

APP_ICONS = {
    "computer": ["computer", "user-desktop-computer"],
    # not «user-desktop»: it is also the icon of the Desktop folder, which must
    # stay a folder like Documents and Downloads
    "disk": ["drive-harddisk", "drive-harddisk-system", "drive-harddisk-root", "drive-multidisk"],
    "network": ["network-workgroup", "folder-remote", "network-server"],
    "recent": ["document-open-recent"],
    "usb": ["drive-removable-media", "drive-removable-media-usb", "media-removable", "media-flash"],
    "optical": ["drive-optical", "media-optical"],
    "app": ["zeta-app", "application-x-executable"],
    "search": ["zeta-search"],
    "home": ["user-home", "folder-home", "go-home"],
    # not «user-trash-symbolic»: GTK recolors symbolic icons, and the tile
    # became a white square in every Delete button
    "trash": ["user-trash"],
    "trash-full": ["user-trash-full"],
    "files": ["org.xfce.thunar", "Thunar", "system-file-manager"],
    "terminal": ["foot", "utilities-terminal"],
    "browser": ["firefox-esr", "web-browser"],
    "editor": ["org.gnome.TextEditor", "accessories-text-editor"],
    "packages": ["synaptic", "system-software-install"],
    "settings": ["zeta-settings", "preferences-system"],
    "shield": ["zeta-security"],
    "core": ["zeta-core"],
    "assistant": ["zeta-assistant"],
    "monitor": ["org.gnome.SystemMonitor", "utilities-system-monitor"],
    "gauge": ["zeta-monitor"],
    "install": ["zeta-install-system"],
    "image": ["org.gnome.eog", "image-viewer"],
    "media": ["mpv", "multimedia-player"],
    "calc": ["org.gnome.Calculator", "accessories-calculator"],
    "docs": ["org.gnome.Evince"],
    "archive": ["org.gnome.FileRoller"],
    "share": ["zeta-share"],
    # app names only: «document-print» is the icon of the Print buttons in
    # toolbars and must stay small and symbolic
    "printer": ["printer", "system-config-printer"],
    "server": ["zeta-server"],
}
for glyph, names in APP_ICONS.items():
    for n in names:
        write("usr/share/icons/zeta/scalable/apps/%s.svg" % n, tile(ICONS[glyph]))

write("usr/share/icons/zeta/index.theme", """[Icon Theme]
Name=ZETA RAYS
Comment=ZETA RAYS icons
Inherits=Adwaita,hicolor
Directories=scalable/apps,scalable/emblems

[scalable/apps]
Size=64
MinSize=16
MaxSize=512
Type=Scalable
Context=Applications

[scalable/emblems]
Size=64
MinSize=8
MaxSize=512
Type=Scalable
Context=Emblems
""")

# --- Bar status icons (network, audio, battery) ---
STATUS = {
    "wifi": ICONS["wifi"],
    "wifi-off": '<path d="M4.5 10a11 11 0 0 1 15 0M7.5 13.3a6.5 6.5 0 0 1 9 0" stroke-opacity="0.35"/><circle cx="12" cy="17" r="1.2"/><path d="M4 4l16 16"/>',
    "ethernet": '<rect x="4" y="4" width="16" height="11" rx="2"/><path d="M8 15v3h8v-3M12 18v2.5M8.5 8v3M12 8v3M15.5 8v3"/>',
    "volume": ICONS["volume"],
    "volume-low": '<path d="M4 9.5h3l4.5-4v13l-4.5-4H4z"/><path d="M15.5 9a4 4 0 0 1 0 6"/>',
    "volume-mute": '<path d="M4 9.5h3l4.5-4v13l-4.5-4H4z"/><path d="M16 9.5l5 5M21 9.5l-5 5"/>',
    "battery-full": '<rect x="3" y="7.5" width="16" height="9" rx="2.5"/><path d="M21.5 10.5v3"/><rect x="5.5" y="10" width="11" height="4" rx="1" fill="currentColor" stroke="none"/>',
    "battery-half": ICONS["battery"],
    "battery-low": '<rect x="3" y="7.5" width="16" height="9" rx="2.5"/><path d="M21.5 10.5v3"/><rect x="5.5" y="10" width="3" height="4" rx="1" fill="#FF6B6B" stroke="none"/>',
    "power": ICONS["power"],
    "battery-charging": '<rect x="3" y="7.5" width="16" height="9" rx="2.5"/><path d="M21.5 10.5v3"/><path d="M11.5 9l-2.5 3.2h3L9.5 15" />',
}
for name, glyph in STATUS.items():
    write("usr/share/zeta/status/%s.svg" % name,
          '<svg %s width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="#A1A1A6" color="#A1A1A6" stroke-width="1.5" '
          'stroke-linecap="round" stroke-linejoin="round">%s</svg>\n' % (XMLNS, glyph))

# --- Interface icons (control center, power): 1.6 stroke, fixed color ---
UI_ICONS = {
    "lock": '<rect x="5" y="10.5" width="14" height="9.5" rx="2.5"/><path d="M8.5 10.5V8a3.5 3.5 0 0 1 7 0v2.5"/>',
    "moon": ICONS["moon"],
    "switch-user": '<circle cx="9" cy="8.5" r="3"/><path d="M3.5 19.5a5.5 5.5 0 0 1 11 0"/><circle cx="17" cy="9.5" r="2.3"/><path d="M16 14.3a4.5 4.5 0 0 1 4.5 4.7"/>',
    "logout": '<path d="M10 19.5H6.5a2 2 0 0 1-2-2v-11a2 2 0 0 1 2-2H10"/><path d="M15 8l4 4-4 4"/><path d="M19 12H9.5"/>',
    "restart": ICONS["restart"],
    "power": ICONS["power"],
    "wifi": ICONS["wifi"],
    "wifi-off": '<path d="M4.5 10a11 11 0 0 1 15 0M7.5 13.3a6.5 6.5 0 0 1 9 0" stroke-opacity="0.35"/><circle cx="12" cy="17" r="1.2"/><path d="M4 4l16 16"/>',
    "wifi-1": '<path d="M4.5 10a11 11 0 0 1 15 0M7.5 13.3a6.5 6.5 0 0 1 9 0" stroke-opacity="0.3"/><circle cx="12" cy="17" r="1.2"/>',
    "wifi-2": '<path d="M4.5 10a11 11 0 0 1 15 0" stroke-opacity="0.3"/><path d="M7.5 13.3a6.5 6.5 0 0 1 9 0"/><circle cx="12" cy="17" r="1.2"/>',
    "wifi-3": '<path d="M4.5 10a11 11 0 0 1 15 0M7.5 13.3a6.5 6.5 0 0 1 9 0"/><circle cx="12" cy="17" r="1.2"/>',
    "ethernet": '<rect x="4" y="4" width="16" height="11" rx="2"/><path d="M8 15v3h8v-3M12 18v2.5M8.5 8v3M12 8v3M15.5 8v3"/>',
    "bluetooth": ICONS["bluetooth"],
    "bell-off": '<path d="M6.5 16.5V11a5.5 5.5 0 0 1 9.2-4M17.5 10.5v6h-12"/><path d="M10 19.5a2 2 0 0 0 4 0"/><path d="M4 4l16 16"/>',
    "vpn": '<path d="M12 3.5l7 2.8v5.2c0 4.3-3 7.7-7 9-4-1.3-7-4.7-7-9V6.3z"/><path d="M9.2 12l2 2 3.6-3.8"/>',
    "volume": ICONS["volume"],
    "volume-low": '<path d="M4 9.5h3l4.5-4v13l-4.5-4H4z"/><path d="M15.5 9a4 4 0 0 1 0 6"/>',
    "volume-mute": '<path d="M4 9.5h3l4.5-4v13l-4.5-4H4z"/><path d="M16 9.5l5 5M21 9.5l-5 5"/>',
    "mic": '<rect x="9" y="3.5" width="6" height="11" rx="3"/><path d="M5.5 11.5a6.5 6.5 0 0 0 13 0M12 18v2.5"/>',
    "mic-off": '<rect x="9" y="3.5" width="6" height="11" rx="3"/><path d="M5.5 11.5a6.5 6.5 0 0 0 13 0M12 18v2.5"/><path d="M4 4l16 16"/>',
    "speaker": '<rect x="6" y="3" width="12" height="18" rx="2.5"/><circle cx="12" cy="14.5" r="3"/><circle cx="12" cy="7.5" r="1"/>',
    "sun": '<circle cx="12" cy="12" r="3.5"/><path d="M12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.6l1.4 1.4M17 17l1.4 1.4M5.6 18.4L7 17M17 7l1.4-1.4"/>',
    "battery": ICONS["battery"],
    # «settings» would collide with the zeta-settings app tile written above
    "settings-glyph": ICONS["settings"],
    "check": '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
    "chevron-down": '<path d="M7 10l5 5 5-5"/>',
    "offline": '<circle cx="12" cy="12" r="8.5"/><path d="M6 18L18 6"/>',
    "palette": ICONS["palette"],
    "info": ICONS["info"],
    "packages": ICONS["packages"],
    "shield": '<path d="M12 3.5l7 2.8v5.2c0 4.3-3 7.7-7 9-4-1.3-7-4.7-7-9V6.3z"/>',
    "ai": '<path d="M12 4l1.6 4.4L18 10l-4.4 1.6L12 16l-1.6-4.4L6 10l4.4-1.6z"/><path d="M18.5 15.5l.7 1.8 1.8.7-1.8.7-.7 1.8-.7-1.8-1.8-.7 1.8-.7z"/>',
    "printer": ICONS["printer"],
    "server-network": ICONS["server"],
    "language": '<circle cx="12" cy="12" r="8.5"/><path d="M3.5 12h17"/><path d="M12 3.5c2.4 2.3 3.6 5.1 3.6 8.5s-1.2 6.2-3.6 8.5c-2.4-2.3-3.6-5.1-3.6-8.5s1.2-6.2 3.6-8.5z"/>',
    "keyboard": '<rect x="3" y="6.5" width="18" height="11" rx="2"/><path d="M7 10h0M10 10h0M13 10h0M16 10h0M8 14h8"/>',
    "account": ICONS["user"],
    "displays": '<rect x="3" y="4.5" width="18" height="12" rx="2"/><path d="M9 20h6M12 16.5V20"/>',
    # font library: «Aa»
    "font": '<path d="M3.5 18.5L8.5 5.5l5 13M5.3 14h6.4"/><path d="M15.2 11.6a2.6 2.6 0 0 1 5.3.9v6M20.5 15c-.8-.4-1.7-.6-2.6-.6-1.6 0-2.7.9-2.7 2.1s1 2 2.3 2c1.4 0 2.6-.9 3-2.2"/>',
}
for name, glyph in UI_ICONS.items():
    write("usr/share/icons/zeta/scalable/apps/zeta-%s.svg" % name,
          '<svg %s width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#EDEDEA" '
          'stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">%s</svg>\n' % (XMLNS, glyph))

# --- Icons for the login screen (SDDM) ---
# eye: shows / hides the password while typing
ICONS["eye"] = ('<path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z"/>'
                '<circle cx="12" cy="12" r="3"/>')
ICONS["eye-off"] = ICONS["eye"] + '<path d="M4 4l16 16"/>'
for g in ("power", "restart", "moon", "user", "arrow", "eye", "eye-off"):
    write("usr/share/sddm/themes/zeta/icons/%s.svg" % g,
          '<svg %s width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="#FFFFFF" stroke-width="1.5" '
          'stroke-linecap="round" stroke-linejoin="round">%s</svg>\n' % (XMLNS, ICONS[g]))
_wm_h = 40
write("usr/share/sddm/themes/zeta/icons/wordmark.svg",
      '<svg %s width="%d" height="%d" viewBox="%s">'
      '<g fill="#EDEDEA" fill-rule="nonzero">%s</g></svg>\n'
      % (XMLNS, proportional_width("wordmark", _wm_h), _wm_h, vb("wordmark"), WORDMARK))

# --- Boot menu background (GRUB/syslinux, 800x600): logo at the top, menu below ---
bh = 191
bw = proportional_width("full", bh)
with open(os.path.join(ROOT, "live-build", "config", "bootloaders", "splash.svg"), "w") as f:
    f.write('<svg %s width="800" height="600" viewBox="0 0 800 600">'
            '<rect width="800" height="600" fill="#000000"/>'
            '<svg x="%s" y="%s" width="%d" height="%d" viewBox="%s">'
            '<g fill="#FFFFFF" fill-rule="nonzero">%s</g></svg></svg>\n'
            % (XMLNS, (800 - bw) / 2, (600 - bh) / 2, bw, bh, vb("full"), LOGO_MARK))

print("assets generated in", CHROOT)


# --- fastfetch ------------------------------------------------------------
# The three ASCII renderings of the logo are produced by tools/gen-logo-ascii.py
# from the official drawing: nothing is touched here, otherwise we would end up
# with two generators overwriting each other (it already happened).
import subprocess as _sp
_ff = os.path.join(CHROOT, "usr/share/zeta/fastfetch")
_src = os.path.join(_ff, "zeta-original-full.txt")
if os.path.exists(_src):
    _sp.run(["python3", os.path.join(ROOT, "tools", "gen-logo-ascii.py"), _src, _ff],
            check=True)


# Search icon for the bar: a simple mark, no tile (on the bar the dark tile
# would clash). Tiles remain for the app menu.
write("usr/share/zeta/status/search.svg",
      '<svg %s width="48" height="48" viewBox="0 0 24 24" fill="none" '
      'stroke="#A1A1A6" color="#A1A1A6" stroke-width="1.6" stroke-linecap="round" '
      'stroke-linejoin="round"><circle cx="11" cy="11" r="7"/><path d="M16 16l5 5"/></svg>\n'
      % XMLNS)
