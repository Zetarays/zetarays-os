# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA RAYS — simple, friendly names for the main apps (.desktop id -> name).

Shared by the launcher and the app switcher (Ctrl+Tab), so the same app has
the same name everywhere.
"""
from i18n import tr

NAMES = {
    "foot.desktop": tr("Terminal"),
    "thunar.desktop": tr("Files"),
    "firefox-esr.desktop": "Firefox",
    "org.gnome.TextEditor.desktop": tr("Text Editor"),
    "org.gnome.eog.desktop": tr("Images"),
    "org.gnome.FileRoller.desktop": tr("Archives"),
    "org.gnome.Evince.desktop": tr("Documents"),
    "mpv.desktop": tr("Video and Music"),
    "org.gnome.Calculator.desktop": tr("Calculator"),
    "org.gnome.SystemMonitor.desktop": tr("System Monitor"),
    "gnome-system-monitor.desktop": tr("System Monitor"),
    "synaptic.desktop": tr("Packages"),
    "zeta-settings.desktop": tr("Settings"),
    "zeta-security.desktop": tr("Security"),
    "zeta-core.desktop": "ZETA",
    "zeta-monitor.desktop": tr("Monitor"),
    "zeta-install-system.desktop": tr("Install ZETA RAYS"),
    "zeta-share.desktop": "ZETA Share",
    "thunderbird.desktop": "Thunderbird",
    "localsend_app.desktop": "ZETA Share",
}
