# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA RAYS — nomi italiani semplici delle app principali (id del .desktop -> nome).

Condivisi dal launcher e dal selettore delle app (Ctrl+Tab), cosi' la stessa
app si chiama nello stesso modo ovunque.
"""
from i18n import tr

NOMI = {
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
    "zeta-impostazioni.desktop": tr("Settings"),
    "zeta-sicurezza.desktop": tr("Security"),
    "zeta-core.desktop": "ZETA",
    "zeta-monitor.desktop": tr("Monitor"),
    "zeta-installa.desktop": tr("Install ZETA RAYS"),
    "zeta-share.desktop": "ZETA Share",
    "thunderbird.desktop": "Thunderbird",
    "localsend_app.desktop": "ZETA Share",
}
