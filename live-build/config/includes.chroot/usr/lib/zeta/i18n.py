# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA RAYS translations (gettext domain "zetarays").

The source text in the code is English. A language with a complete catalog
in /usr/share/locale/<lang>/LC_MESSAGES/zetarays.mo is shown in that
language; every other language falls back to English, never to a mix.

Use tr() (not _: many modules use _ as a throwaway variable):

    from i18n import tr, ntr
    label = tr("Open file location")
    toast = tr("Removed {name}").format(name=app.name)
    count = ntr("{n} file", "{n} files", n).format(n=n)
    state = trc("wifi network", "Saved")   # same English, different translation

gettext reads LANGUAGE, LC_ALL, LC_MESSAGES and LANG, like every other
program of the system, so ZETA follows the language chosen in Settings or in
the installer.
"""
import gettext
import os

DOMAIN = "zetarays"
LOCALEDIR = "/usr/share/locale"

_catalog = gettext.translation(DOMAIN, LOCALEDIR, fallback=True)


def tr(text):
    return _catalog.gettext(text)


def ntr(singular, plural, n):
    return _catalog.ngettext(singular, plural, n)


def trc(context, text):
    """tr() for a word whose translation depends on what it describes
    ("Open" a file vs an "Open" Wi-Fi network)."""
    return _catalog.pgettext(context, text)


def language():
    """Two-letter code of the language ZETA is shown in ("en" when the
    chosen language has no ZETA catalog)."""
    for var in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        value = os.environ.get(var, "")
        for code in value.split(":"):
            code = code.split(".")[0].split("@")[0]
            if not code or code in ("C", "POSIX"):
                continue
            base = code.split("_")[0]
            if base == "en":
                return "en"
            if gettext.find(DOMAIN, LOCALEDIR, languages=[code]):
                return base
        if value:
            break
    return "en"
