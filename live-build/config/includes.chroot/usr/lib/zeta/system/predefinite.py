# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA RAYS — applicazioni predefinite (browser, posta, file, terminale...).

La scelta si scrive dove la leggono tutti i programmi, non in un file solo
nostro:
  - per i tipi di file e gli indirizzi (browser, posta, file, editor, video,
    immagini, PDF) in ~/.config/mimeapps.list, con le funzioni di GIO: lo
    usano xdg-open, gio open, Firefox, Thunar, la Scrivania;
  - per il terminale, che non ha un tipo di file, in
    ~/.config/xdg-terminals.list (lo standard di xdg-terminal-exec, usato
    anche da GLib per le app «da terminale»); le scorciatoie di ZETA RAYS
    passano da «zeta-predefinita terminale», che legge lo stesso file.
Dopo ogni scrittura si rilegge: si dice «fatto» solo se il sistema risponde
davvero con l'app scelta.
"""
from __future__ import annotations

import os

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio  # noqa: E402

from i18n import tr  # noqa: E402

TERMINALI = os.path.expanduser("~/.config/xdg-terminals.list")

# categoria: (titolo, tipi da impostare, categoria .desktop preferita, app di ripiego)
CATEGORIE = {
    "browser": (tr("Browser"), ["x-scheme-handler/https", "x-scheme-handler/http", "text/html",
                            "application/xhtml+xml"], "WebBrowser", "firefox-esr.desktop"),
    "posta": (tr("Mail"), ["x-scheme-handler/mailto", "message/rfc822"], "Email", "thunderbird.desktop"),
    "file": (tr("File Manager"), ["inode/directory"], "FileManager", "thunar.desktop"),
    "terminale": (tr("Terminal"), [], "TerminalEmulator", "foot.desktop"),
    "editor": (tr("Text Editor"), ["text/plain", "text/markdown", "text/x-python", "application/x-shellscript",
                                   "application/json", "text/csv"], "TextEditor", "org.gnome.TextEditor.desktop"),
    "video": (tr("Music and Video"), ["video/mp4", "video/x-matroska", "video/webm", "video/quicktime",
                                 "video/x-msvideo", "audio/mpeg", "audio/flac", "audio/ogg", "audio/x-wav",
                                 "audio/mp4", "audio/aac"], "Player", "mpv.desktop"),
    "immagini": (tr("Images"), ["image/png", "image/jpeg", "image/gif", "image/webp", "image/bmp",
                              "image/tiff", "image/svg+xml"], "Viewer", "org.gnome.eog.desktop"),
    "pdf": ("PDF", ["application/pdf"], "Viewer", "org.gnome.Evince.desktop"),
}
ORDINE = ["browser", "posta", "file", "terminale", "editor", "video", "immagini", "pdf"]
# app di servizio che si dichiarano capaci ma non sono una scelta sensata
ESCLUSE = {"footclient.desktop", "foot-server.desktop", "zeta-scrivania.desktop", "zeta-testo.desktop",
           "thunar-bulk-rename.desktop", "thunar-settings.desktop", "display-im6.q16.desktop"}


# Nomi propri delle app: qui si sceglie tra programmi, e i nomi brevi del
# dock («File», «Documenti») dicevano il ruolo invece dell'app.
NOMI_PROPRI = {
    "firefox-esr.desktop": "Firefox", "thunderbird.desktop": "Thunderbird", "thunar.desktop": "Thunar",
    "foot.desktop": "Foot", "org.gnome.TextEditor.desktop": tr("GNOME Text Editor"),
    "mpv.desktop": "mpv", "org.gnome.eog.desktop": "Eye of GNOME", "org.gnome.Evince.desktop": "Evince",
    "org.xfce.mousepad.desktop": "Mousepad", "debian-xterm.desktop": "XTerm", "debian-uxterm.desktop": "UXTerm",
    "chromium.desktop": "Chromium", "org.gnome.Nautilus.desktop": "Nautilus", "vlc.desktop": "VLC",
}


def nome(aid: str, app=None) -> str:
    if aid in NOMI_PROPRI:
        return NOMI_PROPRI[aid]
    app = app or Gio.DesktopAppInfo.new(aid)
    return (app.get_name() or app.get_display_name()) if app else aid


def _categorie(app) -> list:
    return [c for c in (app.get_categories() or "").split(";") if c]


def candidate(cat: str) -> list:
    """Le app installate che possono fare quel lavoro: [(id, nome, icona)]."""
    _t, tipi, preferita, _r = CATEGORIE[cat]
    viste, out = set(), []
    if cat == "terminale":
        tutte = [a for a in Gio.AppInfo.get_all() if "TerminalEmulator" in _categorie(a)]
    else:
        tutte = Gio.AppInfo.get_all_for_type(tipi[0])
        if cat == "posta":
            tutte = [a for a in tutte if "Email" in _categorie(a) or a.get_id() == "thunderbird.desktop"]
    for a in tutte:
        aid = a.get_id() or ""
        if aid in viste or aid in ESCLUSE or not a.should_show():
            continue
        viste.add(aid)
        icona = a.get_icon().to_string() if a.get_icon() else ""
        out.append((aid, nome(aid, a), icona, preferita in _categorie(a)))
    # prima quelle fatte apposta per quel lavoro (un browser prima di un editor)
    out.sort(key=lambda x: (not x[3], x[1].lower()))
    return [(i, n, ic) for i, n, ic, _p in out]


def _terminale_scelto() -> str | None:
    try:
        with open(TERMINALI) as f:
            for riga in f:
                riga = riga.split("#")[0].strip()
                if riga.endswith(".desktop") and Gio.DesktopAppInfo.new(riga) is not None:
                    return riga
    except OSError:
        pass
    return None


def attuale(cat: str) -> str | None:
    """L'id .desktop dell'app predefinita per la categoria (None se nessuna)."""
    if cat == "terminale":
        return _terminale_scelto() or (CATEGORIE[cat][3] if Gio.DesktopAppInfo.new(CATEGORIE[cat][3]) else None)
    a = Gio.AppInfo.get_default_for_type(CATEGORIE[cat][1][0], False)
    return a.get_id() if a else None


def imposta(cat: str, app_id: str) -> tuple:
    """(ok, messaggio). Scrive la scelta e la verifica rileggendola."""
    if cat not in CATEGORIE:
        return False, tr("Unknown category: {category}").format(category=cat)
    app = Gio.DesktopAppInfo.new(app_id)
    if app is None:
        return False, tr("The application {app} is not installed.").format(app=app_id)
    titolo = CATEGORIE[cat][0]
    nome_app = nome(app_id, app)
    if cat == "terminale":
        try:
            os.makedirs(os.path.dirname(TERMINALI), exist_ok=True)
            tmp = TERMINALI + ".tmp"
            with open(tmp, "w") as f:
                f.write("# chosen in Settings › Default Apps\n%s\n" % app_id)
            os.replace(tmp, TERMINALI)
        except OSError as e:
            return False, tr("Could not save the choice: {error}").format(error=e.strerror or e)
        ok = _terminale_scelto() == app_id
    else:
        supportati = set(app.get_supported_types() or [])
        tipi = CATEGORIE[cat][1]
        errori = []
        for t in tipi:
            # solo i tipi che l'app sa aprire (lo schema http va sempre col browser)
            if t != tipi[0] and supportati and t not in supportati and not t.startswith("x-scheme-handler/"):
                continue
            try:
                app.set_as_default_for_type(t)
            except Exception as e:  # noqa: BLE001 - GLib.Error
                errori.append("%s (%s)" % (t, e))
        verifica = Gio.AppInfo.get_default_for_type(tipi[0], False)
        ok = bool(verifica and verifica.get_id() == app_id) and not errori
    if ok:
        return True, tr("{app} is now the default app for: {category}.").format(app=nome_app, category=titolo)
    return False, tr("Could not make {app} the default app for: {category}.").format(
        app=nome_app, category=titolo)


def avvia(cat: str, argomenti=()) -> tuple:
    """Apre l'app predefinita della categoria (con file o indirizzi)."""
    aid = attuale(cat) or CATEGORIE.get(cat, ("", [], "", ""))[3]
    app = Gio.DesktopAppInfo.new(aid) if aid else None
    if app is None:
        return False, tr("No default app for {category}.").format(category=CATEGORIE.get(cat, (cat,))[0])
    uris = []
    for a in argomenti:
        if "://" in a or a.startswith(("mailto:", "data:")):
            uris.append(a)
        else:
            uris.append(Gio.File.new_for_path(os.path.abspath(a)).get_uri())
    try:
        ok = app.launch_uris(uris, None)
    except Exception as e:  # noqa: BLE001 - GLib.Error
        return False, tr("Could not open {app}: {error}").format(app=app.get_display_name(), error=e)
    return bool(ok), app.get_display_name()
