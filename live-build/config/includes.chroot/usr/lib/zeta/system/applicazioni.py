# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA RAYS — registro unico delle applicazioni.

Prima ogni parte del sistema cercava le app per conto suo (menu, Dock,
ricerca, scrivania, assistente): cinque elenchi, cinque modi di trovare
l'icona, cinque modi di avviarle. La stessa app poteva avere l'icona giusta
nel menu e quella generica nel Dock, o comparire nella ricerca e non nel
menu. Qui c'e' un solo elenco, letto dai file .desktop standard:

  - pacchetti Debian (/usr/share/applications), anche quelli installati a mano
    in /usr/local o nella home;
  - Flatpak (cartelle «exports», anche se la sessione non le conosce);
  - AppImage: integrate da integra_appimage() con un .desktop proprio, senza
    mai eseguire il file per leggerne nome e icona;
  - programmi in /opt con un .desktop accanto.

Per ogni app: nome, icona (anche come file, per il Dock), descrizione,
categorie, comando, eseguibile, file .desktop, provenienza, e su richiesta
(dettagli()) pacchetto, versione, architettura e cartella di installazione.
Le app del sistema (ZETA, gestore file, terminale, Impostazioni...) sono
protette: non si nascondono e non si disinstallano dal menu.

Niente demoni: l'elenco si rilegge solo se una cartella delle app e' cambiata
(confronto delle date di modifica, qualche stat), le icone si indicizzano una
volta per processo.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import shutil
import struct
import subprocess
import tempfile
from dataclasses import dataclass, field

import gi
gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

from i18n import tr  # noqa: E402

try:
    from ui.nomi_app import NOMI
except ImportError:          # usato fuori da /usr/lib/zeta
    NOMI = {}

HOME = os.path.expanduser("~")
CFG = os.path.join(HOME, ".config", "zeta")
FILE_NASCOSTE = os.path.join(CFG, "app-nascoste.json")
CARTELLA_ICONE_APPIMAGE = os.path.join(HOME, ".local", "share", "zeta", "appimage")
APPS_UTENTE = os.path.join(HOME, ".local", "share", "applications")
PREFISSO_APPIMAGE = "zeta-appimage-"
ICONA_GENERICA = "/usr/share/icons/zeta/scalable/apps/zeta-app.svg"

FLATPAK_EXPORTS = ["/var/lib/flatpak/exports/share",
                   os.path.join(HOME, ".local", "share", "flatpak", "exports", "share")]



def _cartelle_appimage():
    """Cartelle dove si cercano le AppImage (le piu' comuni: dove le mette il
    browser, dove le mette chi le «installa», /opt per tutto il sistema).
    Download e Scrivania sono quelle XDG (il nome cambia con la lingua);
    ~/Applications e' la cartella standard delle AppImage. Restano anche le
    cartelle italiane delle installazioni precedenti, se esistono."""
    cartelle = [os.path.join(HOME, "Applications")]
    for quale in (GLib.UserDirectory.DIRECTORY_DOWNLOAD, GLib.UserDirectory.DIRECTORY_DESKTOP):
        d = GLib.get_user_special_dir(quale)
        if d and os.path.normpath(d) != os.path.normpath(HOME):
            cartelle.append(d)
    cartelle += [os.path.join(HOME, n) for n in ("Downloads", "Desktop", "Applicazioni",
                                                 "Scaricati", "Scrivania")]
    cartelle += [os.path.join(HOME, ".local", "bin"), "/opt"]
    visti, out = set(), []
    for d in cartelle:
        d = os.path.normpath(d)
        if d not in visti:
            visti.add(d)
            out.append(d)
    return out


CARTELLE_APPIMAGE = _cartelle_appimage()

# Voci di servizio: esistono per i programmi che le aprono, ma nel menu sono
# doppioni o strumenti tecnici gia' raggiungibili dalle Impostazioni.
SERVIZIO = {
    "footclient.desktop", "foot-server.desktop", "thunar-settings.desktop",
    "thunar-bulk-rename.desktop", "thunar-volman-settings.desktop",
    "nm-connection-editor.desktop", "blueman-manager.desktop", "blueman-adapters.desktop",
    "pavucontrol.desktop", "org.pulseaudio.pavucontrol.desktop", "lxpolkit.desktop",
    "debian-xterm.desktop", "debian-uxterm.desktop", "display-im6.q16.desktop",
    "org.gnome.Evince-previewer.desktop", "calamares-install-debian.desktop", "calamares.desktop",
    "vim.desktop", "nvim.desktop", "htop.desktop", "nm-applet.desktop",
    "org.freedesktop.IBus.Setup.desktop",
    # doppione: ZETA RAYS Monitor copre gia' processi, risorse e rete
    "org.gnome.SystemMonitor.desktop", "gnome-system-monitor.desktop",
}

# App che fanno parte del sistema: non si tolgono dal menu e non si
# disinstallano da qui (resta possibile dal terminale, per chi sa cosa fa).
PROTETTE = {
    "thunar.desktop", "org.xfce.thunar.desktop", "foot.desktop", "synaptic.desktop",
    "localsend_app.desktop", "system-config-printer.desktop",
}

# Pacchetti che una disinstallazione non deve mai portarsi via (anche come
# effetto collaterale di apt: togliere una libreria toglie chi la usa).
PACCHETTI_DI_SISTEMA = {
    "hyprland", "waybar", "sddm", "xwayland", "foot", "thunar", "network-manager",
    "nftables", "pipewire", "wireplumber", "pipewire-pulse", "python3", "python3-gi",
    "gir1.2-gtk-4.0", "gir1.2-adw-1", "libgtk-4-1", "libadwaita-1-0",
    "gir1.2-gtk4layershell-1.0", "libgtk4-layer-shell0", "mako-notifier", "swaybg",
    "hypridle", "hyprlock", "wl-clipboard", "xdg-desktop-portal", "xdg-desktop-portal-gtk",
    "xdg-desktop-portal-hyprland", "polkitd", "mate-polkit", "sudo", "apt", "dpkg",
    "systemd", "dbus", "cups", "avahi-daemon", "localsend", "synaptic", "flatpak",
    "calamares", "grub-common", "shim-signed", "linux-base", "zram-tools", "fonts-roboto",
}

FONTI = {
    "zeta": tr("ZETA RAYS system"),
    "apt": tr("System package (APT)"),
    "flatpak": "Flatpak",
    "appimage": "AppImage",
    "opt": tr("Installed manually (/opt)"),
    "locale": tr("Installed manually (/usr/local)"),
    "utente": tr("User shortcut"),
}

# codici dei campi di Exec (%f %U...): si tolgono; «%%» vale un «%» (specifica .desktop)
_CODICI = re.compile(r"%(.)")


def _senza_codici(comando):
    return _CODICI.sub(lambda m: "%" if m.group(1) == "%" else
                       "" if m.group(1) in "fFuUdDnNickvm" else m.group(0), comando)


@dataclass
class App:
    id: str
    nome: str
    descrizione: str
    icona: str                     # nome del tema o percorso
    categorie: list
    comando: str
    argv: list
    eseguibile: str                # percorso del programma ("" se non trovato)
    desktop: str                   # file .desktop
    fonte: str                     # chiave di FONTI
    protetta: bool
    nascosta: bool                 # nascosta dall'utente
    servizio: bool                 # voce tecnica, mai nel menu
    avviabile: bool
    parole: list = field(default_factory=list)
    flatpak_id: str = ""
    appimage: str = ""
    wm_class: str = ""
    originale: str = ""            # .desktop del pacchetto (anche con icona personale)
    icona_personale: bool = False

    @property
    def nel_menu(self):
        return not (self.nascosta or self.servizio) and self.avviabile

    def info(self):
        return Gio.DesktopAppInfo.new_from_filename(self.desktop) if self.desktop else None


# ------------------------------------------------------------- cartelle
def cartelle_dati():
    """Cartelle XDG dei dati, piu' quelle di Flatpak anche se la sessione
    non le ha in XDG_DATA_DIRS (per esempio dopo aver installato Flatpak senza
    rientrare)."""
    dirs = [GLib.get_user_data_dir()] + list(GLib.get_system_data_dirs())
    for d in FLATPAK_EXPORTS:
        if d not in dirs:
            dirs.append(d)
    visti, out = set(), []
    for d in dirs:
        d = os.path.normpath(d)
        if d not in visti:
            visti.add(d)
            out.append(d)
    return out


def cartelle_app():
    return [os.path.join(d, "applications") for d in cartelle_dati()]


def _firma():
    """Date di modifica delle cartelle delle app: se non cambiano, l'elenco
    letto prima e' ancora buono."""
    f = []
    for d in cartelle_app() + [CFG]:
        try:
            f.append((d, os.stat(d).st_mtime_ns))
        except OSError:
            f.append((d, 0))
    try:
        f.append((FILE_NASCOSTE, os.stat(FILE_NASCOSTE).st_mtime_ns))
    except OSError:
        pass
    return tuple(f)


# ------------------------------------------------------------- nascoste
def _leggi_nascoste():
    try:
        with open(FILE_NASCOSTE) as f:
            dati = json.load(f)
        return set(dati) if isinstance(dati, list) else set()
    except (OSError, ValueError):
        return set()


def _scrivi_nascoste(insieme):
    os.makedirs(CFG, exist_ok=True)
    tmp = FILE_NASCOSTE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(sorted(insieme), f, indent=1)
    os.replace(tmp, FILE_NASCOSTE)


# ------------------------------------------------------------- lettura
def _argv(comando):
    try:
        ok, argv = GLib.shell_parse_argv(_senza_codici(comando or "").strip())
    except GLib.Error:
        return []
    return list(argv) if ok else []


def _indice_programma(argv):
    """Posizione del programma in argv (salta «env VAR=...» e «env -u VAR»)."""
    i = 0
    if argv and os.path.basename(argv[0]) == "env":
        i = 1
        while i < len(argv) and ("=" in argv[i] or argv[i].startswith("-")):
            i += 2 if argv[i] in ("-u", "--unset") else 1
    return i


def _programma(argv, cartella_desktop=None):
    """Percorso reale del programma lanciato (salta «env VAR=...»)."""
    i = _indice_programma(argv)
    if i >= len(argv):
        return ""
    prog = argv[i]
    if os.path.isabs(prog):
        return prog if os.access(prog, os.X_OK) else ""
    trovato = GLib.find_program_in_path(prog)
    if trovato:
        return trovato
    if cartella_desktop:
        vicino = os.path.join(cartella_desktop, prog)
        if os.path.isfile(vicino) and os.access(vicino, os.X_OK):
            return vicino
    return ""


def _fonte(app_id, desktop, kf_get):
    if kf_get("X-ZETA-AppImage"):
        return "appimage"
    if kf_get("X-ZETA-Opt"):
        return "opt"
    if kf_get("X-Flatpak") or "/flatpak/exports/" in desktop:
        return "flatpak"
    if app_id.startswith(("zeta-", "org.zetarays.")) and not app_id.startswith(PREFISSO_APPIMAGE):
        return "zeta"
    reale = os.path.realpath(desktop)
    if reale.startswith("/opt/"):
        return "opt"
    if desktop.startswith(HOME):
        return "utente"
    if desktop.startswith("/usr/local/"):
        # copia di ZETA RAYS di una voce di un pacchetto (hook 0500, ZETA
        # Share): la provenienza resta il pacchetto
        if os.path.exists(os.path.join("/usr/share/applications", os.path.basename(desktop))):
            return "apt"
        return "locale"
    return "apt"


def _da_info(info, nascoste):
    app_id = info.get_id() or os.path.basename(info.get_filename() or "")
    desktop = info.get_filename() or ""

    def kf_get(chiave):
        try:
            return info.get_string(chiave) or ""
        except (TypeError, GLib.Error):
            return ""

    comando = info.get_commandline() or ""
    argv = _argv(comando)
    # icona cambiata dall'utente: la voce in ~/.local/share/applications e'
    # una copia di quella del pacchetto, che resta la provenienza vera
    originale = kf_get("X-ZETA-Originale") or desktop
    fonte = _fonte(app_id, originale, kf_get)
    eseguibile = _programma(argv, os.path.dirname(os.path.realpath(desktop)) if desktop else None)
    if fonte == "flatpak" and not eseguibile:
        eseguibile = shutil.which("flatpak") or ""
    if fonte == "utente" and eseguibile.startswith("/opt/"):
        fonte = "opt"
    icona = info.get_icon()
    if isinstance(icona, Gio.FileIcon):
        icona_s = icona.get_file().get_path() or ""
    elif isinstance(icona, Gio.ThemedIcon):
        nomi = icona.get_names()
        icona_s = nomi[0] if nomi else ""
    else:
        icona_s = ""
    nome = NOMI.get(app_id) or info.get_display_name() or info.get_name() or app_id
    if fonte == "appimage":
        nome = info.get_name() or nome
    return App(
        id=app_id, nome=nome, descrizione=info.get_description() or "",
        icona=icona_s, categorie=[c for c in (info.get_categories() or "").split(";") if c],
        comando=comando, argv=argv, eseguibile=eseguibile, desktop=desktop, fonte=fonte,
        protetta=(fonte == "zeta" or app_id in PROTETTE),
        nascosta=app_id in nascoste,
        servizio=app_id in SERVIZIO or (app_id == "zeta-installa.desktop"
                                        and not os.path.exists("/run/live/medium")),
        avviabile=bool(eseguibile),
        parole=list(info.get_keywords() or []),
        flatpak_id=kf_get("X-Flatpak"), appimage=kf_get("X-ZETA-AppImage"),
        wm_class=info.get_startup_wm_class() or "",
        originale=originale, icona_personale=bool(kf_get("X-ZETA-Icona-Personale")),
    )


_CACHE = {"firma": None, "app": []}


def _invalida():
    _CACHE["firma"] = None


def _voci_desktop():
    """(id, percorso) di tutte le voci .desktop, nell'ordine di precedenza
    XDG (utente, poi le cartelle di sistema, poi Flatpak). Le sottocartelle
    danno id con il trattino (kde/app.desktop -> kde-app.desktop)."""
    for cart in cartelle_app():
        if not os.path.isdir(cart):
            continue
        for radice, _dirs, files in os.walk(cart):
            rel = os.path.relpath(radice, cart)
            for n in sorted(files):
                if n.endswith(".desktop"):
                    aid = n if rel == "." else rel.replace(os.sep, "-") + "-" + n
                    yield aid, os.path.join(radice, n)


def tutte(rileggi=False):
    """Tutte le app (anche nascoste e di servizio: decide chi le mostra).

    I file si leggono direttamente, non dalla cache di GIO: quella si
    aggiorna in ritardo (con inotify), e subito dopo un cambio d'icona il
    menu o il Dock avrebbero mostrato ancora quella vecchia."""
    firma = _firma()
    if not rileggi and _CACHE["firma"] == firma:
        return _CACHE["app"]
    _INDICE.clear()                 # icone e versioni nuove con le app nuove
    _MANCANTI.clear()
    _VERSIONI.clear()
    nascoste = _leggi_nascoste()
    viste, app = set(), []
    for aid, percorso in _voci_desktop():
        if aid in viste:
            continue                # una voce con precedenza l'ha gia' definita
        viste.add(aid)
        try:
            info = Gio.DesktopAppInfo.new_from_filename(percorso)
        except TypeError:
            info = None
        # nascosta (Hidden=true) o programma di TryExec assente: per lo
        # standard la voce non esiste, e copre anche quelle sotto di lei
        if info is None or info.get_is_hidden() or not info.should_show():
            continue
        a = _da_info(info, nascoste)
        a.id = aid
        app.append(a)
    app.sort(key=lambda a: GLib.utf8_collate_key(a.nome.casefold(), -1))
    _CACHE.update(firma=firma, app=app)
    return app


def menu():
    """Le app da mostrare nel menu, nella ricerca e nelle scelte."""
    return [a for a in tutte() if a.nel_menu]


def trova(chiave):
    """Per id del .desktop (con o senza «.desktop»), file .desktop o nome."""
    if not chiave:
        return None
    k = chiave if chiave.endswith(".desktop") else chiave + ".desktop"
    elenco = tutte()
    for a in elenco:
        if a.id == k or a.desktop == chiave:
            return a
    if os.path.isabs(chiave):
        reale = os.path.realpath(chiave)
        for a in elenco:
            if a.desktop and os.path.realpath(a.desktop) == reale:
                return a
    basso = chiave.casefold()
    for a in elenco:
        if a.nome.casefold() == basso or a.id[:-8].casefold() == basso:
            return a
    # il nome del programma («gnome-calculator», «blender»)
    for a in elenco:
        if a.eseguibile and os.path.basename(a.eseguibile).casefold() == basso:
            return a
    return None


def da_comando(cmd):
    """L'app che corrisponde a un comando (voci del Dock salvate senza id)."""
    argv = _argv(cmd)
    if not argv:
        return None
    prog = _programma(argv) or argv[0]
    base = os.path.basename(prog)
    for a in tutte():
        if a.eseguibile and (a.eseguibile == prog or os.path.basename(a.eseguibile) == base) \
                and a.fonte != "flatpak":
            return a
    return None


# ------------------------------------------------------------- icone
_INDICE = {}
_MANCANTI = set()
_CONTESTI = ("apps", "applications", "categories", "mimetypes", "places", "devices", "status",
             "actions", "emblems", "ui", "legacy")


def _indicizza(base):
    """nome icona -> [(dimensione, percorso)] per un tema (una sola volta)."""
    if base in _INDICE:
        return _INDICE[base]
    idx = {}
    for radice, _dirs, files in os.walk(base):
        rel = os.path.relpath(radice, base)
        parti = rel.split(os.sep)
        if not any(p in _CONTESTI for p in parti):
            continue
        dim = 0
        for p in parti:
            m = re.match(r"^(\d+)(x\d+)?(@\d+x)?$", p)
            if m:
                dim = int(m.group(1))
            elif p == "scalable":
                dim = 10000
        for f in files:
            nome, ext = os.path.splitext(f)
            if ext in (".svg", ".png", ".xpm"):
                idx.setdefault(nome, []).append((dim, os.path.join(radice, f)))
    _INDICE[base] = idx
    return idx


def _temi():
    basi = [os.path.join(HOME, ".local", "share", "icons"), os.path.join(HOME, ".icons")]
    basi += [os.path.join(d, "icons") for d in cartelle_dati()]
    out = []
    for tema in ("zeta", "Adwaita", "hicolor"):
        for b in basi:
            p = os.path.join(b, tema)
            if os.path.isdir(p):
                out.append(p)
    return out


def icone_gtk(display=None):
    """Aggiunge al tema di GTK le icone di Flatpak e della home anche se la
    sessione e' partita prima che esistessero (prima app Flatpak installata
    a sessione aperta: nel menu compariva l'icona «immagine mancante")."""
    try:
        from gi.repository import Gdk, Gtk
        tema = Gtk.IconTheme.get_for_display(display or Gdk.Display.get_default())
    except (ImportError, ValueError, TypeError):
        return
    gia = set(tema.get_search_path() or [])
    for d in FLATPAK_EXPORTS + [os.path.join(HOME, ".local", "share")]:
        p = os.path.join(d, "icons")
        if os.path.isdir(p) and p not in gia:
            tema.add_search_path(p)


def icona_file(nome, dimensione=64):
    """Nome di un'icona (o percorso) -> file da mostrare, come farebbe GTK:
    tema di ZETA RAYS, poi Adwaita, hicolor (tutte le misure, anche delle app
    Flatpak e di quelle della home) e /usr/share/pixmaps. Serve a chi non usa
    GTK per disegnare (il Dock di Waybar vuole un file)."""
    if not nome:
        return ICONA_GENERICA
    if os.path.isabs(nome):
        return nome if os.path.exists(nome) else ICONA_GENERICA
    trovata = _cerca_icona(nome, dimensione)
    if trovata is None and _INDICE and nome not in _MANCANTI:
        # app appena installata: l'indice e' vecchio. Una volta sola per nome,
        # o un'icona che non esiste farebbe rifare l'indice a ogni disegno
        _MANCANTI.add(nome)
        _INDICE.clear()
        trovata = _cerca_icona(nome, dimensione)
    return trovata or ICONA_GENERICA


def _cerca_icona(nome, dimensione):
    for tema in _temi():
        candidati = _indicizza(tema).get(nome)
        if candidati:
            # scalabile prima, poi la misura piu' vicina non piu' piccola
            candidati = sorted(candidati, key=lambda c: (c[0] < dimensione, abs(c[0] - dimensione)))
            if any(c[0] == 10000 for c in candidati):
                return next(c[1] for c in candidati if c[0] == 10000)
            return candidati[0][1]
    for d in ["/usr/share/pixmaps"] + [os.path.join(x, "pixmaps") for x in cartelle_dati()]:
        for ext in (".svg", ".png", ".xpm"):
            p = os.path.join(d, nome + ext)
            if os.path.exists(p):
                return p
    return None


# ------------------------------------------------------------- dettagli
def _uscita(argv, timeout=8):
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout,
                           env=dict(os.environ, LANG="C", LC_ALL="C"))
        return r.stdout if r.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def pacchetto_di(percorso):
    """Il pacchetto Debian che ha installato un file ("" se nessuno)."""
    if not percorso:
        return ""
    for p in (percorso, os.path.realpath(percorso)):
        out = _uscita(["dpkg-query", "-S", p])
        if out:
            return out.split(":", 1)[0].split(",")[0].strip()
    return ""


def pacchetto_app(app):
    """Il pacchetto Debian di un'app (voce del menu, anche ridefinita da
    ZETA RAYS in /usr/local, o il suo programma)."""
    return (pacchetto_di(app.originale or app.desktop)
            or pacchetto_di(os.path.join("/usr/share/applications", app.id))
            or pacchetto_di(app.eseguibile))


def _ha(kf, gruppo, chiave):
    """GLib.KeyFile.has_key non e' disponibile da Python."""
    try:
        kf.get_value(gruppo, chiave)
        return True
    except GLib.Error:
        return False


def _arch_elf(percorso):
    try:
        with open(percorso, "rb") as f:
            testa = f.read(20)
    except OSError:
        return ""
    if testa[:4] != b"\x7fELF":
        return ""
    macchina = struct.unpack("<H", testa[18:20])[0]
    return {0x3E: "amd64 (x86-64)", 0xB7: "arm64 (aarch64)", 0x03: "i386",
            0x28: "armhf"}.get(macchina) or tr("other ({code})").format(code="%#x" % macchina)


def dettagli(app):
    """Le informazioni complete (piu' lente: interrogano dpkg o flatpak).
    Elenco di (etichetta, valore, percorso_da_aprire_o_None)."""
    righe = [(tr("Application"), app.nome, None)]
    if app.descrizione:
        righe.append((tr("Description"), app.descrizione, None))
    righe.append((tr("Source"), FONTI.get(app.fonte, app.fonte), None))
    versione, arch, cartella, voce = "", "", "", None
    if app.fonte == "flatpak":
        out = _uscita(["flatpak", "info", app.flatpak_id or app.id[:-8]])
        campi = {}
        for r in out.splitlines():
            if ":" in r:
                k, _, v = r.partition(":")
                campi[k.strip()] = v.strip()
        versione = campi.get("Version", "")
        arch = campi.get("Arch", "")
        cartella = campi.get("Location", "")
        voce = (tr("Flatpak ID"), app.flatpak_id or app.id[:-8], None)
        inst = campi.get("Installation", "")
        if inst:
            righe.append((tr("Installation"),
                          tr("For everyone") if inst == "system" else tr("Only for you"), None))
    elif app.fonte == "appimage":
        voce = (tr("AppImage file"), app.appimage, app.appimage)
        arch = _arch_elf(app.appimage)
        cartella = os.path.dirname(app.appimage)
        try:
            kf = GLib.KeyFile()
            kf.load_from_file(app.desktop, GLib.KeyFileFlags.NONE)
            versione = kf.get_string("Desktop Entry", "X-AppImage-Version")
        except GLib.Error:
            pass
    else:
        pkg = pacchetto_app(app)
        if pkg:
            out = _uscita(["dpkg-query", "-W", "-f", "${Version}\t${Architecture}", pkg])
            if "\t" in out:
                versione, arch = out.split("\t", 1)
            voce = (tr("Package"), pkg, None)
        if app.eseguibile:
            reale = os.path.realpath(app.eseguibile)
            cartella = os.path.dirname(reale)
            arch = arch or _arch_elf(reale)
    if voce:
        righe.append(voce)
    if versione:
        righe.append((tr("Version"), versione, None))
    if arch:
        righe.append((tr("Architecture"), arch, None))
    if app.eseguibile:
        righe.append((tr("Executable"), app.eseguibile, app.eseguibile))
    if app.desktop:
        righe.append((tr("Menu entry (.desktop)"), app.originale or app.desktop,
                      app.originale or app.desktop))
    if app.icona_personale:
        righe.append((tr("Icon you chose"), app.icona, app.icona))
    if cartella:
        righe.append((tr("Folder"), cartella, cartella))
    if app.protetta:
        righe.append((tr("Status"), tr("System component (protected)"), None))
    return righe


_VERSIONI = {}


def versione(app):
    """Solo la versione (per la ricerca), ricordata per processo."""
    if app.id in _VERSIONI:
        return _VERSIONI[app.id]
    v = ""
    if app.fonte == "flatpak":
        for r in _uscita(["flatpak", "info", app.flatpak_id or app.id[:-8]]).splitlines():
            if r.strip().startswith("Version:"):
                v = r.split(":", 1)[1].strip()
    elif app.fonte == "appimage":
        try:
            kf = GLib.KeyFile()
            kf.load_from_file(app.desktop, GLib.KeyFileFlags.NONE)
            v = kf.get_string("Desktop Entry", "X-AppImage-Version")
        except GLib.Error:
            pass
    elif app.fonte in ("apt", "zeta"):
        pkg = pacchetto_app(app)
        if pkg:
            v = _uscita(["dpkg-query", "-W", "-f", "${Version}", pkg]).strip()
    _VERSIONI[app.id] = v
    return v


def posizione(app):
    """Il file da mostrare con «Apri posizione file»."""
    if app.fonte == "appimage" and app.appimage:
        return app.appimage
    if app.fonte == "flatpak":
        for base in ("/var/lib/flatpak/app", os.path.join(HOME, ".local/share/flatpak/app")):
            p = os.path.join(base, app.flatpak_id or app.id[:-8], "current", "active")
            if os.path.exists(p):
                return os.path.realpath(p)
        return app.desktop
    if app.eseguibile:
        return os.path.realpath(app.eseguibile) if app.fonte == "opt" else app.eseguibile
    return app.desktop


_FIGLI = set()


def lancia(argv, **kw):
    """Avvia un programma staccato e ne raccoglie l'uscita (child watch di
    GLib): nei processi che restano accesi (menu, ricerca) un Popen
    dimenticato restava zombie. Il Popen si tiene finche' GLib non l'ha
    raccolto, cosi' Python non prova a raccoglierlo una seconda volta."""
    kw.setdefault("stdout", subprocess.DEVNULL)
    kw.setdefault("stderr", subprocess.DEVNULL)
    kw.setdefault("start_new_session", True)
    try:
        p = subprocess.Popen(argv, **kw)
    except OSError:
        return None
    _FIGLI.add(p)

    def finito(_pid, stato, proc=p):
        proc.returncode = stato
        _FIGLI.discard(proc)
    GLib.child_watch_add(GLib.PRIORITY_DEFAULT_IDLE, p.pid, finito)
    return p


def mostra_nel_gestore_file(percorso):
    """Apre il gestore file sulla cartella con il file selezionato (come
    «Mostra nel Finder»), tramite l'interfaccia standard FileManager1."""
    if not percorso:
        return False
    uri = Gio.File.new_for_path(percorso).get_uri()
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        bus.call_sync("org.freedesktop.FileManager1", "/org/freedesktop/FileManager1",
                      "org.freedesktop.FileManager1",
                      "ShowFolders" if os.path.isdir(percorso) else "ShowItems",
                      GLib.Variant("(ass)", ([uri], "")), None,
                      Gio.DBusCallFlags.NONE, 5000, None)
        return True
    except GLib.Error:
        cartella = percorso if os.path.isdir(percorso) else os.path.dirname(percorso)
        return lancia(["thunar", cartella]) is not None


# ------------------------------------------------------------- azioni
def _attiva_dbus(info, timeout_ms=30000):
    """Start a D-Bus-activatable app (DBusActivatable=true: many Flatpak and
    GNOME apps) and wait for its answer, like "gio launch" does. Needed by
    short-lived callers: if the caller exits before the reply, dbus-daemon
    drops the pending activation and the app starts without a window."""
    app_id = (info.get_id() or "")[:-len(".desktop")] if (info.get_id() or "").endswith(".desktop") else ""
    if not app_id:
        return False
    path = "/" + app_id.replace(".", "/").replace("-", "_")
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        bus.call_sync(app_id, path, "org.freedesktop.Application", "Activate",
                      GLib.Variant("(a{sv})", ({},)), None, Gio.DBusCallFlags.NONE, timeout_ms, None)
        return True
    except GLib.Error:
        return False


def avvia(app, contesto=None, attendi=False):
    """Avvia l'app come dal menu (stesso modo ovunque).
    attendi=True: the caller exits right after (zeta-app avvia, used by the
    Dock): a D-Bus-activated app is started synchronously, see _attiva_dbus."""
    info = app.info()
    if info is None:
        return False
    if attendi and info.get_boolean("DBusActivatable") and _attiva_dbus(info):
        return True
    if contesto is None:
        contesto = Gio.AppLaunchContext()
    contesto.unsetenv("LD_PRELOAD")
    try:
        return info.launch([], contesto)
    except GLib.Error:
        return False


def nascondi(app, nascosta=True):
    """Toglie l'app dal menu (non la disinstalla). Le protette no."""
    if app.protetta and nascosta:
        return False
    s = _leggi_nascoste()
    (s.add if nascosta else s.discard)(app.id)
    _scrivi_nascoste(s)
    _invalida()
    return True


def cartella_scrivania():
    d = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_DESKTOP)
    if d:
        return d
    vecchia = os.path.join(HOME, "Scrivania")       # installazioni precedenti
    return vecchia if os.path.isdir(vecchia) else os.path.join(HOME, "Desktop")


def sulla_scrivania(app):
    """Il collegamento gia' presente sulla Scrivania per questa app, o ""."""
    d = cartella_scrivania()
    try:
        nomi = os.listdir(d)
    except OSError:
        return ""
    reale = os.path.realpath(app.desktop) if app.desktop else ""
    # un programma di /opt: anche il collegamento al suo .desktop originale
    # (Invia a › Scrivania) o una copia con i percorsi completi e' «lui»
    origine = ""
    if app.fonte == "opt" and app.desktop:
        kfa = GLib.KeyFile()
        try:
            kfa.load_from_file(app.desktop, GLib.KeyFileFlags.NONE)
            origine = _kf_str(kfa, "X-ZETA-Opt")
        except GLib.Error:
            pass
    for n in nomi:
        if not n.endswith(".desktop"):
            continue
        p = os.path.join(d, n)
        if n == app.id or (reale and os.path.realpath(p) == reale) \
                or (origine and os.path.realpath(p) == origine):
            return p
        try:
            kf = GLib.KeyFile()
            kf.load_from_file(p, GLib.KeyFileFlags.NONE)
            if _kf_str(kf, "X-ZETA-App") == app.id or (origine and _kf_str(kf, "X-ZETA-Origine") == origine):
                return p
        except GLib.Error:
            continue
    return ""


def aggiungi_scrivania(app):
    """Collegamento sulla Scrivania: una copia della voce del menu (stesso
    nome, stessa icona, stesso comando), che funziona anche dopo il riavvio e
    si toglie come un file qualsiasi. Mai due volte la stessa app."""
    gia = sulla_scrivania(app) or appimage_sulla_scrivania(app)
    if gia:
        return False, tr("“{name}” is already on the Desktop.").format(name=app.nome)
    d = cartella_scrivania()
    os.makedirs(d, exist_ok=True)
    kf = GLib.KeyFile()
    try:
        kf.load_from_file(app.desktop, GLib.KeyFileFlags.KEEP_COMMENTS | GLib.KeyFileFlags.KEEP_TRANSLATIONS)
    except GLib.Error as e:
        return False, tr("Can't read {path}: {error}").format(path=app.desktop, error=e.message)
    kf.set_string("Desktop Entry", "X-ZETA-App", app.id)
    if app.nome != (kf.get_string("Desktop Entry", "Name") if _ha(kf, "Desktop Entry", "Name") else ""):
        kf.set_string("Desktop Entry", "Name", app.nome)
    # Exec relativo (programma in /opt accanto al suo .desktop): sulla
    # Scrivania la cartella cambia, quindi si scrive il percorso completo
    if app.eseguibile and app.argv and not os.path.isabs(app.argv[0]) \
            and not GLib.find_program_in_path(app.argv[0]):
        cmd = kf.get_string("Desktop Entry", "Exec")
        kf.set_string("Desktop Entry", "Exec", cmd.replace(app.argv[0], programma_exec(app.eseguibile), 1))
        if not _ha(kf, "Desktop Entry", "Path"):
            kf.set_string("Desktop Entry", "Path", os.path.dirname(app.eseguibile))
    if app.icona and not os.path.isabs(app.icona) and icona_file(app.icona) == ICONA_GENERICA:
        vicina = _icona_accanto(app)
        if vicina:
            kf.set_string("Desktop Entry", "Icon", vicina)
    dest = os.path.join(d, app.id)
    tmp = dest + ".tmp"
    with open(tmp, "w") as f:
        f.write(kf.to_data()[0])
    os.chmod(tmp, 0o755)
    os.replace(tmp, dest)
    try:
        Gio.File.new_for_path(dest).set_attribute_string(
            "metadata::trusted", "true", Gio.FileQueryInfoFlags.NONE, None)
    except GLib.Error:
        pass
    return True, tr("“{name}” added to the Desktop.").format(name=app.nome)


def _icona_accanto(app):
    for base in (app.eseguibile, app.desktop):
        if not base:
            continue
        cart = os.path.dirname(os.path.realpath(base))
        for est in ("svg", "png", "xpm"):
            p = os.path.join(cart, "%s.%s" % (app.icona, est))
            if os.path.isfile(p):
                return p
    return ""


# ------------------------------------------------------------- icona personale
CARTELLA_ICONE = os.path.join(HOME, ".local", "share", "zeta", "icone")


def _copia_icona(immagine, nome):
    """Copia l'immagine scelta tra le icone dell'utente (rimpicciolita se
    enorme: una foto da 4000 pixel non serve a 64)."""
    os.makedirs(CARTELLA_ICONE, exist_ok=True)
    base = re.sub(r"[^A-Za-z0-9._-]", "_", nome) or "icona"
    ext = os.path.splitext(immagine)[1].lower()
    if ext in (".svg", ".svgz"):
        dest = os.path.join(CARTELLA_ICONE, base + ext)
        shutil.copyfile(immagine, dest)
        return dest
    gi.require_version("GdkPixbuf", "2.0")
    from gi.repository import GdkPixbuf
    pix = GdkPixbuf.Pixbuf.new_from_file(immagine)
    lato = max(pix.get_width(), pix.get_height())
    if lato > 512:
        k = 512 / lato
        pix = pix.scale_simple(max(1, int(pix.get_width() * k)), max(1, int(pix.get_height() * k)),
                               GdkPixbuf.InterpType.BILINEAR)
    dest = os.path.join(CARTELLA_ICONE, base + ".png")
    pix.savev(dest, "png", [], [])
    return dest


def _impronta(percorso):
    """Impronta del contenuto: dpkg e Flatpak non cambiano la data dei file
    (hanno quella del pacchetto), il contenuto si'."""
    try:
        with open(percorso, "rb") as f:
            return hashlib.sha1(f.read()).hexdigest()
    except OSError:
        return ""


def _scrivi_kf(kf, dest):
    tmp = dest + ".tmp"
    with open(tmp, "w") as f:
        f.write(kf.to_data()[0])
    os.replace(tmp, dest)


def _icona_ovunque(app, icona):
    """La stessa icona nei collegamenti sulla Scrivania e nel Dock."""
    p = sulla_scrivania(app)
    if p and not os.path.islink(p):
        kf = GLib.KeyFile()
        try:
            kf.load_from_file(p, GLib.KeyFileFlags.KEEP_COMMENTS | GLib.KeyFileFlags.KEEP_TRANSLATIONS)
            kf.set_string("Desktop Entry", "Icon", icona)
            _scrivi_kf(kf, p)
        except (GLib.Error, OSError):
            pass
    try:
        from system import dock
        dock.apply()                 # il Dock prende l'icona dal registro
    except Exception:  # noqa: BLE001 — il Dock non deve fermare il cambio
        pass


def cambia_icona(app, immagine):
    """L'icona scelta vale ovunque: menu, ricerca, Dock, Scrivania, Ctrl+Tab.

    Per le app dei pacchetti si scrive una copia della loro voce in
    ~/.local/share/applications (che per lo standard XDG ha la precedenza)
    con l'icona nuova: il file del pacchetto non si tocca, e «Ripristina»
    toglie solo la copia. Le voci gia' dell'utente (AppImage, collegamenti
    creati a mano) si modificano direttamente, ricordando l'icona di prima."""
    try:
        icona = _copia_icona(immagine, app.id[:-8] if app.id.endswith(".desktop") else app.id)
    except (OSError, GLib.Error) as e:
        return False, tr("That image can't be used: {error}").format(error=e)
    os.makedirs(APPS_UTENTE, exist_ok=True)
    g = "Desktop Entry"
    kf = GLib.KeyFile()
    flag = GLib.KeyFileFlags.KEEP_COMMENTS | GLib.KeyFileFlags.KEEP_TRANSLATIONS
    proprio = app.desktop.startswith(APPS_UTENTE + os.sep) and not app.icona_personale \
        and app.originale == app.desktop
    try:
        if app.icona_personale or proprio:
            kf.load_from_file(app.desktop, flag)
            dest = app.desktop
            if proprio:
                kf.set_string(g, "X-ZETA-Icona-Originale", app.icona)
        else:
            kf.load_from_file(app.originale or app.desktop, flag)
            dest = os.path.join(APPS_UTENTE, app.id)
            kf.set_string(g, "X-ZETA-Originale", app.originale or app.desktop)
            kf.set_string(g, "X-ZETA-Originale-Firma", _impronta(app.originale or app.desktop))
        kf.set_string(g, "Icon", icona)
        kf.set_string(g, "X-ZETA-Icona-Personale", "true")
        _scrivi_kf(kf, dest)
    except (GLib.Error, OSError) as e:
        return False, tr("Couldn't change the icon: {error}").format(error=e)
    _invalida()
    _icona_ovunque(app, icona)
    return True, tr("New icon for “{name}”.").format(name=app.nome)


def ripristina_icona(app):
    """Rimette l'icona originale dell'app."""
    if not app.icona_personale:
        return False, tr("“{name}” already has its own icon.").format(name=app.nome)
    g = "Desktop Entry"
    kf = GLib.KeyFile()
    try:
        kf.load_from_file(app.desktop, GLib.KeyFileFlags.KEEP_COMMENTS | GLib.KeyFileFlags.KEEP_TRANSLATIONS)
    except GLib.Error as e:
        return False, e.message
    originale = _kf_str(kf, "X-ZETA-Originale")
    if originale:
        # copia fatta da ZETA: si toglie e torna valida la voce del pacchetto
        try:
            os.unlink(app.desktop)
        except OSError as e:
            return False, tr("Couldn't restore it: {error}").format(error=e.strerror)
        info = Gio.DesktopAppInfo.new_from_filename(originale) if os.path.exists(originale) else None
        icona = ""
        if info is not None and info.get_icon() is not None:
            icona = info.get_icon().to_string()
    else:
        icona = _kf_str(kf, "X-ZETA-Icona-Originale") or "application-x-executable"
        kf.set_string(g, "Icon", icona)
        for k in ("X-ZETA-Icona-Personale", "X-ZETA-Icona-Originale"):
            try:
                kf.remove_key(g, k)
            except GLib.Error:
                pass
        _scrivi_kf(kf, app.desktop)
    _invalida()
    _icona_ovunque(app, icona)
    return True, tr("“{name}” has its own icon again.").format(name=app.nome)


def _kf_str(kf, chiave):
    try:
        return kf.get_string("Desktop Entry", chiave)
    except GLib.Error:
        return ""


FILE_ORFANI = os.path.join(HOME, ".cache", "zeta", "app-orfane.json")
ATTESA_ORFANI = 20          # secondi: un'app assente cosi' a lungo e' davvero tolta
_GESTORI = {"apt", "apt-get", "aptitude", "dpkg", "synaptic", "flatpak", "unattended-upgr",
            "packagekitd", "zeta-pacchetti"}


def _gestore_pacchetti_attivo():
    """Vero se apt, dpkg, Synaptic o Flatpak stanno lavorando: in quei
    momenti un'app puo' mancare per qualche secondo (tolta e rimessa)."""
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            with open("/proc/%s/comm" % pid) as f:
                if f.read().strip() in _GESTORI:
                    return True
        except OSError:
            continue
    return False


def _orfane_confermate(mancanti):
    """Delle app mancanti, quelle che mancavano gia' da ATTESA_ORFANI secondi
    (e nessun gestore di pacchetti al lavoro). Le altre restano in attesa."""
    import time
    try:
        with open(FILE_ORFANI) as f:
            stato = json.load(f)
    except (OSError, ValueError):
        stato = {}
    ora = time.time()
    stato = {k: v for k, v in stato.items() if k in mancanti}
    for k in mancanti:
        stato.setdefault(k, ora)
    occupato = _gestore_pacchetti_attivo()
    confermate = set() if occupato else {k for k, v in stato.items() if ora - v >= ATTESA_ORFANI}
    for k in confermate:
        stato.pop(k, None)
    os.makedirs(os.path.dirname(FILE_ORFANI), exist_ok=True)
    with open(FILE_ORFANI, "w") as f:
        json.dump(stato, f)
    return confermate


def orfane_in_attesa():
    """Vero se qualche app mancante aspetta la conferma (il menu ricontrolla)."""
    try:
        with open(FILE_ORFANI) as f:
            return bool(json.load(f))
    except (OSError, ValueError):
        return False


def manutenzione():
    """Dopo ogni cambio delle app (installate, aggiornate, tolte anche da
    Synaptic o dal terminale), senza demoni: la chiama il menu delle app.

      - le copie con icona personale seguono la voce del pacchetto aggiornata
        (stesso comando nuovo, icona scelta tenuta) e spariscono se l'app e'
        stata disinstallata;
      - i collegamenti fatti da ZETA (Dock, Scrivania) di app che non ci sono
        piu' si tolgono; i file messi a mano dall'utente non si toccano;
      - il Dock si rigenera se un'icona e' cambiata.
    Restituisce i nomi delle app sparite."""
    g = "Desktop Entry"
    try:
        nomi = os.listdir(APPS_UTENTE)
    except OSError:
        nomi = []
    for n in nomi:
        p = os.path.join(APPS_UTENTE, n)
        if not n.endswith(".desktop"):
            continue
        kf = GLib.KeyFile()
        try:
            kf.load_from_file(p, GLib.KeyFileFlags.KEEP_COMMENTS | GLib.KeyFileFlags.KEEP_TRANSLATIONS)
        except GLib.Error:
            continue
        originale = _kf_str(kf, "X-ZETA-Originale")
        if not originale:
            continue
        if not os.path.exists(originale):
            if not _gestore_pacchetti_attivo():
                try:
                    os.unlink(p)          # app disinstallata: via anche la copia
                except OSError:
                    pass
            continue
        impronta = _impronta(originale)
        if impronta and impronta != _kf_str(kf, "X-ZETA-Originale-Firma"):
            # la voce del pacchetto e' cambiata (aggiornamento): la copia la
            # segue, tenendo solo l'icona scelta
            nuovo = GLib.KeyFile()
            try:
                nuovo.load_from_file(originale, GLib.KeyFileFlags.KEEP_COMMENTS | GLib.KeyFileFlags.KEEP_TRANSLATIONS)
                nuovo.set_string(g, "Icon", _kf_str(kf, "Icon"))
                nuovo.set_string(g, "X-ZETA-Originale", originale)
                nuovo.set_string(g, "X-ZETA-Originale-Firma", impronta)
                nuovo.set_string(g, "X-ZETA-Icona-Personale", "true")
                _scrivi_kf(nuovo, p)
            except (GLib.Error, OSError):
                pass
    _invalida()
    ids = {a.id for a in tutte(rileggi=True)}
    sparite = []
    # collegamenti di ZETA (Scrivania, Dock) che puntano ad app non installate
    d = cartella_scrivania()
    scrivania = {}
    try:
        for n in os.listdir(d):
            p = os.path.join(d, n)
            if not n.endswith(".desktop") or os.path.islink(p):
                continue
            kf = GLib.KeyFile()
            try:
                kf.load_from_file(p, GLib.KeyFileFlags.NONE)
            except GLib.Error:
                continue
            aid = _kf_str(kf, "X-ZETA-App")
            if aid and aid not in ids:
                try:
                    nome = kf.get_locale_string("Desktop Entry", "Name", None)   # the user's language
                except GLib.Error:
                    nome = ""
                scrivania[p] = (aid, nome or aid)
    except OSError:
        pass
    try:
        from system import dock
        voci = dock.load_dock()
    except Exception:  # noqa: BLE001 — senza Dock si pulisce il resto
        dock, voci = None, []
    nel_dock = {e["app"] for e in voci if e.get("app") and e["app"] not in ids}
    confermate = _orfane_confermate({a for a, _n in scrivania.values()} | nel_dock)
    for p, (aid, nome) in scrivania.items():
        if aid in confermate:
            try:
                Gio.File.new_for_path(p).trash(None)
                sparite.append(nome)
            except GLib.Error:
                pass
    if dock is not None:
        try:
            tenute = [e for e in voci if not (e.get("app") in confermate)]
            if len(tenute) != len(voci) and tenute:
                sparite += [e.get("name", e["app"]) for e in voci if e.get("app") in confermate]
                dock.save_dock(tenute)
            dock.apply_se_cambia()
        except Exception:  # noqa: BLE001 — il Dock non deve fermare la manutenzione
            pass
    return sparite


# ------------------------------------------------------------- Dock
def nel_dock(app):
    from system import dock
    for e in dock.load_dock():
        if e.get("app") == app.id:
            return True
        if not e.get("app") and app.eseguibile and app.fonte != "flatpak":
            a = da_comando(e.get("cmd", ""))
            if a is not None and a.id == app.id:
                return True
    return False


def aggiungi_dock(app):
    from system import dock
    if nel_dock(app):
        return False, tr("“{name}” is already in the Dock.").format(name=app.nome)
    voci = dock.load_dock()
    voci.append(dock.voce_da_app(app))
    dock.save_dock(voci)
    dock.apply(voci)
    return True, tr("“{name}” added to the Dock.").format(name=app.nome)


def togli_dock(app):
    from system import dock
    voci = dock.load_dock()
    resto = []
    for e in voci:
        if e.get("app") == app.id:
            continue
        if not e.get("app"):
            a = da_comando(e.get("cmd", ""))
            if a is not None and a.id == app.id:
                continue
        resto.append(e)
    if len(resto) == len(voci):
        return False, tr("“{name}” isn't in the Dock.").format(name=app.nome)
    if not resto:
        return False, tr("The Dock must have at least one app.")
    dock.save_dock(resto)
    dock.apply(resto)
    return True, tr("“{name}” removed from the Dock.").format(name=app.nome)


# ------------------------------------------------------------- disinstallazione
# apt in inglese: l'uscita si legge (Inst/Remv); LANGUAGE vale piu' di LC_ALL
_ENV_APT = dict({k: v for k, v in os.environ.items() if k != "LANGUAGE"},
                DEBIAN_FRONTEND="noninteractive", LANG="C.UTF-8", LC_ALL="C.UTF-8")


def pacchetto_di_sistema(pkg):
    """Vero per i pacchetti che non si tolgono mai da qui: quelli del sistema
    ZETA RAYS e quelli che Debian segna come essenziali o importanti."""
    base = pkg.split(":")[0]
    if base in PACCHETTI_DI_SISTEMA or base.startswith(("linux-image", "grub", "shim", "zeta")):
        return True
    out = _uscita(["dpkg-query", "-W", "-f", "${Essential} ${Priority}", base])
    return out.startswith("yes") or " required" in out or " important" in out


def simula_apt(argv):
    """apt-get -s (senza permessi): (codice, tolti, installati, messaggio)."""
    try:
        p = subprocess.run(["apt-get", "-s"] + argv, env=_ENV_APT, capture_output=True,
                           text=True, timeout=300)
    except (OSError, subprocess.SubprocessError) as e:
        return 1, [], [], str(e)
    via = re.findall(r"^Remv (\S+)", p.stdout, re.M)
    su = re.findall(r"^Inst (\S+)", p.stdout, re.M)
    return p.returncode, via, su, (p.stderr or p.stdout).strip()[-600:]


def disinstallabile(app):
    """(si/no, perche': frase intera da mostrare) — cosa offrire nel menu."""
    if app.protetta:
        return False, tr("“{name}” is part of the system.").format(name=app.nome)
    if app.fonte in ("opt", "locale"):
        return False, tr("“{name}” was installed manually: remove it by deleting its "
                         "folder.").format(name=app.nome)
    return True, ""


def togli_integrazione_appimage(app, ignora=True):
    """Toglie voce e icona di un'AppImage. ignora=True: il file resta e non
    va rimesso nel menu alla prossima scansione."""
    # the app's stable key is read before its entry is removed: it is
    # ignored by app, not by path, so moving the file does not bring it back
    chiave = ""
    kf = GLib.KeyFile()
    try:
        kf.load_from_file(app.desktop, GLib.KeyFileFlags.NONE)
        chiave = _kf_str(kf, "X-ZETA-AppImage-Chiave")
    except GLib.Error:
        pass
    _togli_file_appimage(app.desktop, os.path.basename(app.desktop)[:-len(".desktop")])
    if ignora:
        _ignora_appimage("app:" + chiave if chiave else app.appimage)
    _pulisci_collegamenti(app)


def _pulisci_collegamenti(app):
    """Dopo una disinstallazione: niente collegamenti morti sulla Scrivania,
    nel Dock e tra le app nascoste."""
    p = sulla_scrivania(app)
    if p:
        try:
            os.unlink(p)
        except OSError:
            pass
    try:
        togli_dock(app)
    except Exception:          # noqa: BLE001 — il Dock non deve fermare la pulizia
        pass
    s = _leggi_nascoste()
    if app.id in s:
        s.discard(app.id)
        _scrivi_nascoste(s)
    _invalida()


def dopo_disinstallazione(app):
    _pulisci_collegamenti(app)


# ------------------------------------------------------------- AppImage
FILE_IGNORATE = os.path.join(CFG, "appimage-ignorate.json")


def _ignora_appimage(percorso):
    try:
        with open(FILE_IGNORATE) as f:
            s = set(json.load(f))
    except (OSError, ValueError):
        s = set()
    s.add(percorso)
    os.makedirs(CFG, exist_ok=True)
    with open(FILE_IGNORATE, "w") as f:
        json.dump(sorted(s), f, indent=1)


def _ignorate():
    try:
        with open(FILE_IGNORATE) as f:
            return set(json.load(f))
    except (OSError, ValueError):
        return set()


def e_appimage(percorso):
    """Vero per un'AppImage (ELF con la firma «AI» tipo 1 o 2)."""
    try:
        with open(percorso, "rb") as f:
            testa = f.read(11)
    except OSError:
        return False
    return testa[:4] == b"\x7fELF" and testa[8:10] == b"AI" and testa[10] in (1, 2)


def _fine_elf(percorso):
    """Dove finisce la parte ELF: li' comincia il file system dell'AppImage."""
    with open(percorso, "rb") as f:
        h = f.read(64)
    if h[4] == 2:           # 64 bit
        e_shoff, = struct.unpack("<Q", h[40:48])
        e_shentsize, e_shnum = struct.unpack("<HH", h[58:62])
    else:
        e_shoff, = struct.unpack("<I", h[32:36])
        e_shentsize, e_shnum = struct.unpack("<HH", h[46:50])
    return e_shoff + e_shentsize * e_shnum


def _leggi_appimage(percorso, cartella):
    """Extract the desktop entry and the icon from the AppImage's own file
    system without running it (unsquashfs).
    Returns (KeyFile, icon path, desktop file name) or (None, None, None)."""
    try:
        off = _fine_elf(percorso)
    except (OSError, struct.error):
        return None, None, None
    unsq = shutil.which("unsquashfs")
    if not unsq:
        return None, None, None
    try:
        r = subprocess.run([unsq, "-o", str(off), "-l", "-d", "", percorso],
                           capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None, None, None
    # l'elenco arriva come «/nome» (o «squashfs-root/nome» con unsquashfs vecchi)
    nomi = []
    for x in r.stdout.splitlines():
        x = x.strip()
        if x.startswith("squashfs-root"):
            x = x[len("squashfs-root"):]
        nomi.append(x.lstrip("/"))
    radice = [n for n in nomi if n and "/" not in n]
    desktop = next((n for n in radice if n.endswith(".desktop")), None)
    if not desktop:
        return None, None, None

    def estrai(nomi):
        try:
            subprocess.run([unsq, "-o", str(off), "-f", "-d", cartella, percorso] + nomi,
                           capture_output=True, timeout=60)
        except (OSError, subprocess.SubprocessError):
            pass

    def reale(nome):
        """Le voci alla radice sono spesso collegamenti a file piu' interni
        (usr/share/applications/..., .DirIcon -> icona): si estrae anche il
        bersaglio, senza mai uscire dall'AppImage."""
        p = os.path.join(cartella, nome)
        for _ in range(4):
            if not os.path.islink(p):
                break
            dest = os.path.normpath(os.path.join(os.path.dirname(nome), os.readlink(p))).lstrip("/")
            if dest.startswith(".."):
                return None
            estrai([dest])
            nome, p = dest, os.path.join(cartella, dest)
        return p if os.path.isfile(p) and not os.path.islink(p) else None

    estrai([desktop, ".DirIcon"] + [n for n in radice if n.endswith((".png", ".svg"))])
    file_desktop = reale(desktop)
    if not file_desktop:
        return None, None, None
    kf = GLib.KeyFile()
    try:
        kf.load_from_file(file_desktop, GLib.KeyFileFlags.KEEP_TRANSLATIONS)
    except GLib.Error:
        return None, None, None
    icona = None
    try:
        nome_icona = kf.get_string("Desktop Entry", "Icon")
    except GLib.Error:
        nome_icona = ""
    for cand in ([nome_icona + ".svg", nome_icona + ".png"] if nome_icona else []) + [".DirIcon"]:
        if cand not in radice:
            continue
        p = reale(cand)
        if p and os.path.getsize(p) > 0:
            icona = p
            break
    return kf, icona, desktop


def quota_exec(percorso):
    """Un percorso dentro Exec= come vuole lo standard dei .desktop: tra
    virgolette doppie (non apici: altri programmi non li capiscono) e con \\,
    ", ` e $ protetti."""
    percorso = percorso.replace("%", "%%")          # «%» e' un codice di campo
    if re.fullmatch(r"[A-Za-z0-9_./+:@-]+", percorso):
        return percorso
    return '"%s"' % re.sub(r'([\\"`$])', r"\\\1", percorso)


def programma_exec(percorso):
    """Il programma all'inizio di Exec=. Con un «%» nel nome (AppImage
    scaricata come «App%20Nome») GIO scarta la voce: controlla che il
    programma esista senza prima trasformare «%%» in «%». Con «env» davanti
    il controllo trova /usr/bin/env, e all'avvio il percorso e' quello giusto."""
    return ("env " if "%" in percorso else "") + quota_exec(percorso)


# ------------------------------------------------------------- programmi fuori dal menu
# Un programma scaricato e scompattato (Blender da blender.org in /opt o in
# Download) porta un .desktop accanto a se' con «Exec=blender» e
# «Icon=blender»: nomi che valgono solo in quella cartella. Copiato altrove
# (trascinato sulla Scrivania, incollato, copiato dal gestore file) non
# trovava piu' il programma e la Scrivania lo mostrava «Blender (missing)».
# Ogni voce che esce dalla sua cartella viene quindi riscritta con i
# percorsi completi, e ricorda da dove viene (X-ZETA-Origine).

PREFISSO_OPT = "zeta-opt-"

# Blender scaricato da blender.org (5.x) si apre su Wayland e misura
# l'interfaccia solo con la scala dello schermo di Hyprland (1 su quasi tutti
# gli schermi): su uno schermo con piu' di 96 DPI risultava piccolo. Il
# Blender del pacchetto (Synaptic) passa da X11, dove Blender misura
# l'interfaccia con i DPI veri dello schermo, e si vede della misura giusta.
# Le sue voci (menu, Scrivania, Dock) lo avviano quindi allo stesso modo,
# senza toccare la scala del resto del sistema.
SENZA_WAYLAND = ("blender",)
_PREFISSO_X11 = "env -u WAYLAND_DISPLAY "


def _comando_adattato(comando, prog):
    """Exec con le correzioni per i programmi che si vedono male su Wayland
    (solo quelli scaricati a mano: i pacchetti del sistema restano come sono)."""
    if os.path.basename(prog) in SENZA_WAYLAND and not prog.startswith("/usr/") \
            and "WAYLAND_DISPLAY" not in comando:
        return _PREFISSO_X11 + comando
    return comando
_TOKEN = r"(?:(?<=\s)|^)%s(?=\s|$)"


def _sostituisci_programma(comando, vecchio, nuovo):
    """Il programma dentro Exec= (solo la parola intera, la prima volta)."""
    return re.sub(_TOKEN % re.escape(vecchio), lambda _m: nuovo, comando, count=1)



def voce_risolta(sorgente):
    """KeyFile di un .desktop con programma, icona e cartella resi assoluti
    rispetto alla cartella del file vero (seguendo i collegamenti simbolici).
    None se non e' un'applicazione o il programma non si trova."""
    g = "Desktop Entry"
    reale = os.path.realpath(sorgente)
    kf = GLib.KeyFile()
    try:
        kf.load_from_file(reale, GLib.KeyFileFlags.KEEP_COMMENTS | GLib.KeyFileFlags.KEEP_TRANSLATIONS)
    except GLib.Error:
        return None
    if (_kf_str(kf, "Type") or "Application") != "Application":
        return None
    comando = _kf_str(kf, "Exec")
    argv = _argv(comando)
    cartella = os.path.dirname(reale)
    origine = _kf_str(kf, "X-ZETA-Origine")
    i = _indice_programma(argv)
    if i >= len(argv):
        return None
    token = argv[i]
    prog = ""
    # il programma accanto al .desktop prima di quello nel PATH: con Blender
    # anche installato da Synaptic, «Exec=blender» del 5.2 in /opt avviava
    # /usr/bin/blender, cioe' l'altro Blender
    for base in [cartella] + ([os.path.dirname(origine)] if origine else []):
        vicino = os.path.join(base, token)
        if not os.path.isabs(token) and os.path.isfile(vicino) and os.access(vicino, os.X_OK):
            prog, cartella = vicino, base
            break
    if not prog:
        prog = _programma(argv, cartella)
    if not prog:
        return None
    if not os.path.isabs(token) and prog != GLib.find_program_in_path(token):
        kf.set_string(g, "Exec", _sostituisci_programma(comando, token, programma_exec(prog)))
        if not _kf_str(kf, "Path"):
            kf.set_string(g, "Path", os.path.dirname(prog))
    kf.set_string(g, "Exec", _comando_adattato(_kf_str(kf, "Exec"), prog))
    prova = _kf_str(kf, "TryExec")
    if prova and not os.path.isabs(prova) and not GLib.find_program_in_path(prova):
        vicino = os.path.join(cartella, prova)
        kf.set_string(g, "TryExec", vicino if os.access(vicino, os.X_OK) else prog)
    icona = _kf_str(kf, "Icon")
    if icona and not os.path.isabs(icona) and icona_file(icona) == ICONA_GENERICA:
        for base in (cartella, os.path.dirname(prog)):
            trovata = next((os.path.join(base, icona + e) for e in (".svg", ".png", ".xpm")
                            if os.path.isfile(os.path.join(base, icona + e))), "")
            if trovata:
                kf.set_string(g, "Icon", trovata)
                break
    if not origine:
        kf.set_string(g, "X-ZETA-Origine", reale)
    return kf


def _scrivi_collegamento(kf, dest):
    """Scrive il collegamento (eseguibile e «fidato», come quelli del menu)."""
    tmp = dest + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(kf.to_data()[0])
    os.chmod(tmp, 0o755)
    os.replace(tmp, dest)
    try:
        Gio.File.new_for_path(dest).set_attribute_string(
            "metadata::trusted", "true", Gio.FileQueryInfoFlags.NONE, None)
    except GLib.Error:
        pass


def _nome_libero(cartella, nome):
    dest = os.path.join(cartella, nome)
    base, ext = os.path.splitext(nome)
    base = re.sub(r" \(\d+\)$", "", base)          # «blender (3)», not «blender (2) (2)»
    n = 2
    while os.path.lexists(dest):
        dest = os.path.join(cartella, "%s (%d)%s" % (base, n, ext))
        n += 1
    return dest


def collegamento_esterno(sorgente, cartella=None, unico=True):
    """Collegamento sulla Scrivania (o in cartella) per un .desktop che non
    sta fra le applicazioni: una copia con i percorsi completi, che funziona
    ovunque venga spostata o copiata. Con unico=True, se ce n'e' gia' uno per
    lo stesso programma si restituisce quello. (percorso, "") o ("", errore)."""
    kf = voce_risolta(sorgente)
    nome = os.path.basename(sorgente)
    if kf is None:
        return "", tr("“{name}” doesn't start a program that can be found.").format(name=nome)
    cartella = cartella or cartella_scrivania()
    os.makedirs(cartella, exist_ok=True)
    origine = _kf_str(kf, "X-ZETA-Origine")
    if unico:
        for n in os.listdir(cartella):
            p = os.path.join(cartella, n)
            if not n.endswith(".desktop"):
                continue
            if os.path.realpath(p) == origine:
                return p, ""
            altro = GLib.KeyFile()
            try:
                altro.load_from_file(p, GLib.KeyFileFlags.NONE)
            except GLib.Error:
                continue
            if _kf_str(altro, "X-ZETA-Origine") == origine:
                return p, ""
    dest = _nome_libero(cartella, nome if nome.endswith(".desktop") else nome + ".desktop")
    try:
        _scrivi_collegamento(kf, dest)
    except OSError as e:
        return "", tr("Couldn't create the shortcut: {error}").format(error=e.strerror)
    return dest, ""


def voce_accanto(percorso):
    """Il .desktop accanto a un programma (blender -> blender.desktop) che
    lo avvia, o ""."""
    reale = os.path.realpath(percorso)
    cartella = os.path.dirname(reale)
    try:
        nomi = sorted(os.listdir(cartella))
    except OSError:
        return ""
    for n in nomi:
        if not n.endswith(".desktop"):
            continue
        kf = GLib.KeyFile()
        try:
            kf.load_from_file(os.path.join(cartella, n), GLib.KeyFileFlags.NONE)
        except GLib.Error:
            continue
        prog = _programma(_argv(_kf_str(kf, "Exec")), cartella)
        if prog and os.path.realpath(prog) == reale:
            return os.path.join(cartella, n)
    return ""


def collegamento_programma(percorso, cartella=None):
    """Un programma (binario ELF) trascinato sulla Scrivania: il collegamento
    della sua voce .desktop se ne ha una accanto, altrimenti uno nuovo con il
    suo nome. Mai una copia del programma: Blender ha bisogno delle sue
    librerie accanto e una copia non partirebbe."""
    voce = voce_accanto(percorso)
    if voce:
        return collegamento_esterno(voce, cartella)
    reale = os.path.realpath(percorso)
    g = "Desktop Entry"
    kf = GLib.KeyFile()
    nome = os.path.basename(reale)
    kf.set_string(g, "Type", "Application")
    kf.set_string(g, "Name", nome[:1].upper() + nome[1:])
    kf.set_string(g, "Exec", _comando_adattato(programma_exec(reale), reale))
    kf.set_string(g, "Path", os.path.dirname(reale))
    kf.set_string(g, "Terminal", "false")
    icona = next((os.path.join(os.path.dirname(reale), nome + e) for e in (".svg", ".png", ".xpm")
                  if os.path.isfile(os.path.join(os.path.dirname(reale), nome + e))), "")
    kf.set_string(g, "Icon", icona or "application-x-executable")
    kf.set_string(g, "X-ZETA-Origine", reale)
    cartella = cartella or cartella_scrivania()
    for n in os.listdir(cartella) if os.path.isdir(cartella) else []:
        p = os.path.join(cartella, n)
        if n.endswith(".desktop"):
            altro = GLib.KeyFile()
            try:
                altro.load_from_file(p, GLib.KeyFileFlags.NONE)
            except GLib.Error:
                continue
            if _kf_str(altro, "X-ZETA-Origine") == reale:
                return p, ""
    dest = _nome_libero(cartella, re.sub(r"[^\w.+-]+", "-", nome) + ".desktop")
    try:
        _scrivi_collegamento(kf, dest)
    except OSError as e:
        return "", tr("Couldn't create the shortcut: {error}").format(error=e.strerror)
    return dest, ""


def _candidati_origine(prog):
    """Le voci .desktop accanto a un programma con questo nome, nelle
    cartelle dei programmi scompattati a mano (fino a due livelli)."""
    basi = ["/opt", os.path.join(HOME, "Applications"), os.path.join(HOME, ".local", "opt")]
    for quale in (GLib.UserDirectory.DIRECTORY_DOWNLOAD,):
        d = GLib.get_user_special_dir(quale)
        if d:
            basi.append(d)
    basi += [os.path.join(HOME, n) for n in ("Downloads", "Scaricati")]
    visti = set()
    for b in basi:
        b = os.path.normpath(b)
        if b in visti or not os.path.isdir(b):
            continue
        visti.add(b)
        for radice, dirs, files in os.walk(b):
            livello = radice[len(b):].count(os.sep)
            if livello >= 2:
                dirs[:] = []
            if not os.path.isfile(os.path.join(radice, prog)):
                continue
            for f in sorted(files):
                if f.endswith(".desktop"):
                    yield os.path.join(radice, f)


def ripara_collegamento(percorso):
    """Un collegamento sulla Scrivania che non trova piu' il programma (copiato
    dal gestore file prima di questa correzione, o con un Exec relativo):
    si cerca la sua voce originale fra i programmi scompattati a mano e lo si
    riscrive con i percorsi completi. Vero se ora funziona."""
    if os.path.islink(percorso) or not percorso.endswith(".desktop"):
        return False
    kf = GLib.KeyFile()
    try:
        kf.load_from_file(percorso, GLib.KeyFileFlags.NONE)
    except GLib.Error:
        return False
    argv = _argv(_kf_str(kf, "Exec"))
    if not argv or _indice_programma(argv) >= len(argv) or _programma(argv, os.path.dirname(percorso)):
        return False
    nome = _kf_str(kf, "Name")
    prog = argv[_indice_programma(argv)]
    if os.sep in prog:
        return False                     # percorso scritto e sparito: il programma e' stato tolto
    trovate = []
    for cand in _candidati_origine(prog):
        altro = GLib.KeyFile()
        try:
            altro.load_from_file(cand, GLib.KeyFileFlags.NONE)
        except GLib.Error:
            continue
        if _kf_str(altro, "Name") == nome and _kf_str(altro, "Exec") == _kf_str(kf, "Exec") \
                and os.path.realpath(cand) not in trovate:
            trovate.append(os.path.realpath(cand))
    origine = _kf_str(kf, "X-ZETA-Origine")
    if origine and os.path.isfile(origine):
        trovate = [origine]
    if len(trovate) > 1:
        # lo stesso programma in Download (l'archivio scompattato) e in /opt
        # (dove lo si e' messo per usarlo): vale quello in /opt
        in_opt = [t for t in trovate if t.startswith("/opt/")]
        if len(in_opt) == 1:
            trovate = in_opt
    if len(trovate) != 1:
        return False                     # nessuna o piu' d'una: non si indovina
    nuova = voce_risolta(trovate[0])
    if nuova is None:
        return False
    # cio' che l'utente ha cambiato sul collegamento resta (icona scelta)
    if _kf_str(kf, "X-ZETA-Icona-Personale"):
        nuova.set_string("Desktop Entry", "Icon", _kf_str(kf, "Icon"))
        nuova.set_string("Desktop Entry", "X-ZETA-Icona-Personale", "true")
    try:
        _scrivi_collegamento(nuova, percorso)
    except OSError:
        return False
    return True


def voci_opt():
    """Le voci .desktop dei programmi scompattati in /opt (fino a due livelli:
    /opt/blender-5.2.2/blender.desktop, /opt/blender/5.2/blender.desktop)."""
    trovate = []
    if not os.path.isdir("/opt"):
        return trovate
    for radice, dirs, files in os.walk("/opt"):
        livello = radice[len("/opt"):].count(os.sep)
        if livello >= 2:
            dirs[:] = []
        if livello == 0:
            continue                       # /opt stesso: niente voci sciolte
        for f in sorted(files):
            if f.endswith(".desktop"):
                trovate.append(os.path.join(radice, f))
    return trovate


def _integra_opt():
    """Mette nel menu i programmi in /opt che hanno un .desktop accanto e non
    sono gia' nel menu con una voce loro (Chrome, VS Code... la installano).
    La voce generata ha i percorsi completi e sparisce con il programma.
    Restituisce i nomi delle app nuove."""
    g = "Desktop Entry"
    os.makedirs(APPS_UTENTE, exist_ok=True)
    attuali = {}
    for n in os.listdir(APPS_UTENTE):
        if n.startswith(PREFISSO_OPT) and n.endswith(".desktop"):
            attuali[n] = os.path.join(APPS_UTENTE, n)
    _invalida()
    gia, altri_nomi = set(), set()
    for a in tutte(rileggi=True):
        if a.id.startswith(PREFISSO_OPT) or not a.eseguibile:
            continue
        gia.add(os.path.realpath(a.eseguibile))
        altri_nomi.add(a.nome)
    voci, nomi = {}, {}
    for sorgente in voci_opt():
        kf = voce_risolta(sorgente)
        if kf is None or _kf_str(kf, "NoDisplay") == "true" or _kf_str(kf, "Hidden") == "true":
            continue
        prog = _programma(_argv(_kf_str(kf, "Exec")))
        if not prog or os.path.realpath(prog) in gia:
            continue
        rel = os.path.relpath(os.path.realpath(sorgente), "/opt")
        chiave = re.sub(r"[^a-z0-9._-]+", "-", rel[:-len(".desktop")].lower().replace(os.sep, "-")).strip(".-")
        ident = PREFISSO_OPT + chiave + ".desktop"
        kf.set_string(g, "TryExec", os.path.realpath(prog))
        kf.set_string(g, "X-ZETA-Opt", os.path.realpath(sorgente))
        voci[ident] = kf
        nomi.setdefault(_kf_str(kf, "Name"), []).append(ident)
    # due versioni dello stesso programma (o lo stesso nome di un pacchetto,
    # come Blender di Synaptic): il nome dice quale
    for nome, ids in nomi.items():
        if len(ids) < 2 and nome not in altri_nomi:
            continue
        for ident in ids:
            kf = voci[ident]
            cartella = os.path.basename(os.path.dirname(_kf_str(kf, "X-ZETA-Opt")))
            m = re.search(r"\d+(?:\.\d+)+", cartella)
            kf.set_string(g, "Name", "%s %s" % (nome, m.group(0) if m else cartella))
    aggiunte = []
    for ident, kf in voci.items():
        dest = os.path.join(APPS_UTENTE, ident)
        vecchia = attuali.pop(ident, None)
        testo = kf.to_data()[0]
        if vecchia:
            precedente = GLib.KeyFile()
            try:
                precedente.load_from_file(vecchia, GLib.KeyFileFlags.KEEP_COMMENTS | GLib.KeyFileFlags.KEEP_TRANSLATIONS)
                if _kf_str(precedente, "X-ZETA-Icona-Personale"):
                    kf.set_string(g, "Icon", _kf_str(precedente, "Icon"))
                    kf.set_string(g, "X-ZETA-Icona-Personale", "true")
                    testo = kf.to_data()[0]
                with open(vecchia, encoding="utf-8") as f:
                    if f.read() == testo:
                        continue
            except (GLib.Error, OSError):
                pass
        else:
            aggiunte.append(_kf_str(kf, "Name"))
        tmp = dest + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(testo)
        os.replace(tmp, dest)
    # programmi tolti da /opt: via anche la voce (Scrivania e Dock li pulisce
    # manutenzione(), come per le app disinstallate)
    for p in attuali.values():
        try:
            os.unlink(p)
        except OSError:
            pass
    _invalida()
    return aggiunte


FILE_META_APPIMAGE = os.path.join(HOME, ".cache", "zeta", "appimage-meta.json")
FILE_BLOCCO_APPIMAGE = os.path.join(HOME, ".cache", "zeta", "appimage.lock")
_ID_VECCHIO = re.compile(r"^%s[0-9a-f]{12}\.desktop$" % re.escape(PREFISSO_APPIMAGE))


def chiave_appimage(nome_desktop, nome_app=""):
    """Stable identity of an AppImage application: the name of the desktop
    entry it ships (blender.desktop -> "blender"). Never the path of the
    file: moving, renaming or updating the AppImage keeps the same app, the
    same menu entry and the same Desktop and Dock links."""
    base = nome_desktop[:-len(".desktop")] if nome_desktop.endswith(".desktop") else nome_desktop
    base = re.sub(r"[^a-z0-9._-]+", "-", base.lower()).strip(".-")
    if not base:
        base = re.sub(r"[^a-z0-9]+", "-", nome_app.lower()).strip("-") or "app"
    return base


def _id_appimage(chiave):
    return PREFISSO_APPIMAGE + chiave


def appimage_trovate():
    trovate = []
    for d in CARTELLE_APPIMAGE:
        profondita = 2 if d == "/opt" else 0
        for radice, dirs, files in os.walk(d) if os.path.isdir(d) else []:
            livello = radice[len(d):].count(os.sep)
            if livello >= profondita:
                dirs[:] = []
            for f in files:
                if f.lower().endswith(".appimage"):
                    p = os.path.join(radice, f)
                    if os.path.isfile(p) and e_appimage(p):
                        trovate.append(os.path.realpath(p))
    return sorted(set(trovate))


def _impronta_file(st):
    """Same file, even after a move or a rename on the same disk."""
    return "%d:%d:%d:%d" % (st.st_dev, st.st_ino, st.st_size, int(st.st_mtime))


def _firma_appimage(st):
    # "v4": the format of the generated entry; changing it regenerates them
    return "v4:%d:%d" % (st.st_size, int(st.st_mtime))


def _ordine_versione(meta, mtime):
    """Newest first: by the version the AppImage declares, then by date."""
    numeri = tuple(int(x) for x in re.findall(r"\d+", meta.get("versione") or "")[:6])
    return (numeri, mtime)


class _Blocco:
    """One AppImage scan at a time (the path unit, the session start and the
    app menu can all ask for one at the same moment)."""

    def __enter__(self):
        os.makedirs(os.path.dirname(FILE_BLOCCO_APPIMAGE), exist_ok=True)
        self.f = open(FILE_BLOCCO_APPIMAGE, "w")
        import fcntl
        fcntl.flock(self.f, fcntl.LOCK_EX)
        return self

    def __exit__(self, *_a):
        self.f.close()


def _leggi_json(percorso, vuoto):
    try:
        with open(percorso, encoding="utf-8") as f:
            dati = json.load(f)
        return dati if isinstance(dati, type(vuoto)) else vuoto
    except (OSError, ValueError):
        return vuoto


def _scrivi_json(percorso, dati):
    os.makedirs(os.path.dirname(percorso), exist_ok=True)
    with open(percorso + ".tmp", "w", encoding="utf-8") as f:
        json.dump(dati, f, indent=1, ensure_ascii=False)
    os.replace(percorso + ".tmp", percorso)


def integra_appimage():
    """Create, update or remove the menu entries of the AppImages found in
    the usual folders, and of the programs unpacked in /opt with a desktop
    entry next to them. Returns the names of the apps that are new."""
    with _Blocco():
        nuove = _integra_appimage()
        try:
            nuove += _integra_opt()
        except OSError:
            pass                  # /opt illeggibile: le AppImage restano
        return nuove


def _integra_appimage():
    g = "Desktop Entry"
    os.makedirs(APPS_UTENTE, exist_ok=True)
    os.makedirs(CARTELLA_ICONE_APPIMAGE, exist_ok=True)
    ignorate = _ignorate()

    # entries written by earlier scans: current ones (stable id) and old ones
    # named after a hash of the path (before 1.7), which are migrated
    attuali, vecchie = {}, {}
    for n in os.listdir(APPS_UTENTE):
        if not (n.startswith(PREFISSO_APPIMAGE) and n.endswith(".desktop")):
            continue
        p = os.path.join(APPS_UTENTE, n)
        kf = GLib.KeyFile()
        try:
            kf.load_from_file(p, GLib.KeyFileFlags.KEEP_TRANSLATIONS)
        except GLib.Error:
            try:
                os.unlink(p)
            except OSError:
                pass
            continue
        if _ID_VECCHIO.match(n) and not _kf_str(kf, "X-ZETA-AppImage-Chiave"):
            vecchie[n] = (p, kf)
        else:
            attuali[n[:-len(".desktop")]] = (p, kf)

    meta_cache = _leggi_json(FILE_META_APPIMAGE, {})
    nuova_cache = {}
    letti = {}                     # path -> (KeyFile, icon) read in this scan
    per_chiave = {}                # key -> [(order, path, stat, meta)]
    tmp_radice = tempfile.mkdtemp(prefix="zeta-appimage-")
    try:
        for p in appimage_trovate():
            if p in ignorate:
                continue
            try:
                st = os.stat(p)
            except OSError:
                continue                      # gone while we were looking
            imp = _impronta_file(st)
            meta = meta_cache.get(imp)
            if not meta:
                cartella = tempfile.mkdtemp(dir=tmp_radice)
                kf, icona, desktop = _leggi_appimage(p, cartella)
                if kf is None:
                    continue                  # no desktop entry inside: not an app
                nome = _kf_str(kf, "Name") or os.path.splitext(os.path.basename(p))[0]
                meta = {"chiave": chiave_appimage(desktop, nome), "nome": nome,
                        "versione": _kf_str(kf, "X-AppImage-Version")}
                letti[p] = (kf, icona)
            nuova_cache[imp] = meta
            if "app:" + meta["chiave"] in ignorate:
                continue
            per_chiave.setdefault(meta["chiave"], []).append(
                (_ordine_versione(meta, st.st_mtime), p, st, meta))
        _scrivi_json(FILE_META_APPIMAGE, nuova_cache)

        aggiunte, rinomina, tenuti = [], {}, set()
        for chiave, versioni in per_chiave.items():
            versioni.sort(key=lambda v: v[0], reverse=True)
            _ordine, p, st, meta = versioni[0]
            ident = _id_appimage(chiave)
            tenuti.add(ident)
            dest = os.path.join(APPS_UTENTE, ident + ".desktop")
            firma = _firma_appimage(st)
            esistente = attuali.get(ident)
            # old entries of any version of this app point here now
            percorsi = {v[1] for v in versioni}
            for n, (_vp, vkf) in vecchie.items():
                if _kf_str(vkf, "X-ZETA-AppImage") in percorsi:
                    rinomina[n] = ident + ".desktop"
            personale = ""
            for _x, kfv in ([esistente] if esistente else []) + \
                    [vecchie[n] for n in rinomina if rinomina[n] == ident + ".desktop"]:
                if _kf_str(kfv, "X-ZETA-Icona-Personale"):
                    personale = _kf_str(kfv, "Icon")
                    break
            if esistente:
                ekf = esistente[1]
                if _kf_str(ekf, "X-ZETA-AppImage-Firma") == firma:
                    if _kf_str(ekf, "X-ZETA-AppImage") != p:
                        # same file, moved or renamed: only the path changes
                        ekf.set_string(g, "Exec", programma_exec(p) + " %U")
                        ekf.set_string(g, "TryExec", p)
                        ekf.set_string(g, "Path", os.path.dirname(p))
                        ekf.set_string(g, "X-ZETA-AppImage", p)
                        _scrivi_kf(ekf, dest)
                    _rendi_eseguibile(p)
                    continue
            if p not in letti:
                cartella = tempfile.mkdtemp(dir=tmp_radice)
                kf, icona, _desktop = _leggi_appimage(p, cartella)
                if kf is None:
                    continue
                letti[p] = (kf, icona)
            kf, icona = letti[p]
            out = _voce_appimage(kf, icona, p, ident, chiave, firma, personale)
            _scrivi_kf(out, dest)
            _rendi_eseguibile(p)
            if not esistente and ident + ".desktop" not in rinomina.values():
                aggiunte.append(out.get_string(g, "Name"))
    finally:
        shutil.rmtree(tmp_radice, ignore_errors=True)

    # apps whose AppImage is gone: entry and icon go; Desktop and Dock links
    # are removed later by manutenzione(), only if still missing (two phases)
    for ident, (p, _kf) in attuali.items():
        if ident not in tenuti:
            _togli_file_appimage(p, ident)
    for n, (p, _kf) in vecchie.items():
        _togli_file_appimage(p, n[:-len(".desktop")])
    if rinomina:
        _rinomina_collegamenti(rinomina)
    _invalida()
    _allinea_collegamenti_appimage()
    return aggiunte


def _rendi_eseguibile(p):
    """A downloaded file is not executable: it becomes so here, so the menu
    can start it (only the user's own files, never system ones)."""
    try:
        st = os.stat(p)
        if not os.access(p, os.X_OK) and st.st_uid == os.getuid():
            os.chmod(p, st.st_mode | 0o100)
    except OSError:
        pass


def _voce_appimage(kf, icona, p, ident, chiave, firma, personale):
    g = "Desktop Entry"
    out = GLib.KeyFile()
    out.set_string(g, "Type", "Application")
    for k in ("Name", "GenericName", "Comment", "Categories", "Keywords",
              "StartupWMClass", "MimeType", "Terminal", "X-AppImage-Version"):
        if _ha(kf, g, k):
            out.set_string(g, k, kf.get_string(g, k))
    # translated names and descriptions shipped by the app
    for k in ("Name", "GenericName", "Comment"):
        try:
            chiavi = kf.get_keys(g)[0]
        except GLib.Error:
            chiavi = []
        for c in chiavi:
            if c.startswith(k + "[") and c.endswith("]"):
                out.set_string(g, c, kf.get_string(g, c))
    if not _ha(out, g, "Name"):
        out.set_string(g, "Name", os.path.splitext(os.path.basename(p))[0])
    if not _ha(out, g, "Categories"):
        out.set_string(g, "Categories", "Utility;")
    if not _ha(out, g, "Comment"):
        out.set_string(g, "Comment", "AppImage")
    dest_icona = ""
    if icona:
        with open(icona, "rb") as fi:
            svg = icona.endswith(".svg") or fi.read(5).startswith(b"<")
        ext = ".svg" if svg else ".png"
        dest_icona = os.path.join(CARTELLA_ICONE_APPIMAGE, ident + ext)
        altra = os.path.join(CARTELLA_ICONE_APPIMAGE, ident + (".png" if svg else ".svg"))
        shutil.copyfile(icona, dest_icona + ".tmp")
        os.replace(dest_icona + ".tmp", dest_icona)
        if os.path.exists(altra):
            os.unlink(altra)
    out.set_string(g, "Icon", dest_icona or "application-x-executable")
    if personale:
        out.set_string(g, "X-ZETA-Icona-Originale", out.get_string(g, "Icon"))
        out.set_string(g, "Icon", personale)
        out.set_string(g, "X-ZETA-Icona-Personale", "true")
    out.set_string(g, "Exec", programma_exec(p) + " %U")
    out.set_string(g, "TryExec", p)
    out.set_string(g, "Path", os.path.dirname(p))
    out.set_string(g, "X-ZETA-AppImage", p)
    out.set_string(g, "X-ZETA-AppImage-Chiave", chiave)
    out.set_string(g, "X-ZETA-AppImage-Firma", firma)
    return out


def _togli_file_appimage(p, ident):
    for f in (p, os.path.join(CARTELLA_ICONE_APPIMAGE, ident + ".png"),
              os.path.join(CARTELLA_ICONE_APPIMAGE, ident + ".svg")):
        try:
            os.unlink(f)
        except OSError:
            pass


def _rinomina_collegamenti(rinomina):
    """Old app id -> new app id in the Desktop links, the Dock and the list
    of apps removed from the menu (migration of the pre-1.7 ids)."""
    g = "Desktop Entry"
    d = cartella_scrivania()
    try:
        nomi = os.listdir(d)
    except OSError:
        nomi = []
    for n in nomi:
        p = os.path.join(d, n)
        if not n.endswith(".desktop") or os.path.islink(p):
            continue
        kf = GLib.KeyFile()
        try:
            kf.load_from_file(p, GLib.KeyFileFlags.KEEP_COMMENTS | GLib.KeyFileFlags.KEEP_TRANSLATIONS)
        except GLib.Error:
            continue
        nuovo = rinomina.get(_kf_str(kf, "X-ZETA-App"))
        if nuovo:
            kf.set_string(g, "X-ZETA-App", nuovo)
            _scrivi_kf(kf, p)
    try:
        from system import dock
        voci = dock.load_dock()
        cambiate = False
        for e in voci:
            if e.get("app") in rinomina:
                e["app"] = rinomina[e["app"]]
                e["cmd"] = "zeta-app avvia %s" % shlex.quote(e["app"])
                cambiate = True
        if cambiate:
            dock.save_dock(voci)
    except Exception:  # noqa: BLE001 - the Dock must not stop the migration
        pass
    s = _leggi_nascoste()
    if s & set(rinomina):
        _scrivi_nascoste({rinomina.get(x, x) for x in s})


def appimage_sulla_scrivania(app):
    """The AppImage file of this app, when the file itself is on the Desktop."""
    if not app.appimage:
        return ""
    d = os.path.realpath(cartella_scrivania())
    return app.appimage if os.path.dirname(os.path.realpath(app.appimage)) == d else ""


def _allinea_collegamenti_appimage():
    """Desktop links of AppImage apps follow the app: same command and icon
    after the file moved or the app was updated. A link is redundant when the
    AppImage file itself sits on the Desktop (two icons for one app): the
    link made by ZETA goes to the Trash, the user's file stays."""
    g = "Desktop Entry"
    app_per_id = {a.id: a for a in tutte() if a.fonte == "appimage"}
    d = cartella_scrivania()
    try:
        nomi = os.listdir(d)
    except OSError:
        return
    for n in nomi:
        p = os.path.join(d, n)
        if not n.endswith(".desktop") or os.path.islink(p):
            continue
        kf = GLib.KeyFile()
        try:
            kf.load_from_file(p, GLib.KeyFileFlags.KEEP_COMMENTS | GLib.KeyFileFlags.KEEP_TRANSLATIONS)
        except GLib.Error:
            continue
        app = app_per_id.get(_kf_str(kf, "X-ZETA-App"))
        if not app:
            continue
        if appimage_sulla_scrivania(app):
            try:
                Gio.File.new_for_path(p).trash(None)
            except GLib.Error:
                pass
            continue
        sorgente = GLib.KeyFile()
        try:
            sorgente.load_from_file(app.desktop, GLib.KeyFileFlags.NONE)
        except GLib.Error:
            continue
        cambiato = False
        for k in ("Exec", "TryExec", "Path", "Icon"):
            v = _kf_str(sorgente, k)
            if v and _kf_str(kf, k) != v:
                kf.set_string(g, k, v)
                cambiato = True
        if cambiato:
            _scrivi_kf(kf, p)
