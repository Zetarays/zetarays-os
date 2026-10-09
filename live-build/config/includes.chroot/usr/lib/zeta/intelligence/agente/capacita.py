# SPDX-License-Identifier: GPL-3.0-or-later
"""Le capacita' di ZETA Core: azioni vere, ciascuna con la sua verifica.

Ogni capacita' ha:
  - un nome (open_application, create_folder, ...) e i suoi parametri;
  - un livello di rischio: «lettura» (solo guarda), «normale» (cambia qualcosa
    che si rimette a posto da se': aprire, spostare, cambiare volume) e
    «conferma» (va chiesto prima: eliminare, spegnere, installare);
  - una funzione che esegue E controlla lo stato vero dopo averlo fatto.
L'esito dice la verita': ok=True solo se la verifica ha confermato.

Aggiungere una capacita' = scrivere una funzione e registrarla qui sotto:
la comprensione locale, il modello e i servizi in rete la vedono subito.
"""
from __future__ import annotations

import os
import re
import shutil
import time
from dataclasses import dataclass, field
from typing import Callable

from i18n import ntr, tr

from . import stato as S


@dataclass
class Esito:
    ok: bool
    messaggio: str
    dati: dict = field(default_factory=dict)


@dataclass
class Capacita:
    nome: str
    descrizione: str
    parametri: dict                  # nome -> descrizione
    obbligatori: list
    rischio: str                     # lettura | normale | conferma
    esegui: Callable[[dict], Esito]
    anteprima: Callable[[dict], str] | None = None
    # prima della conferma: None se si puo' procedere, altrimenti l'Esito da
    # dare subito (non si chiede «confermi?» per qualcosa che non esiste)
    controlla: Callable[[dict], "Esito | None"] | None = None


REGISTRO: dict[str, Capacita] = {}


def capacita(nome, descrizione, parametri=None, obbligatori=(), rischio="normale", anteprima=None,
             controlla=None):
    def dec(fn):
        REGISTRO[nome] = Capacita(nome, descrizione, parametri or {}, list(obbligatori),
                                  rischio, fn, anteprima, controlla)
        return fn
    return dec


# Cosa manca, detto all'utente («Mi manca un'informazione: ...»). Le
# descrizioni dei parametri qui sotto sono per i modelli (in inglese).
def etichetta(parametro):
    return {
        "app": tr("the app name (e.g. firefox, mail, terminal, settings)"),
        "nome": tr("the name"),
        "elemento": tr("the file or folder"),
        "nuovo_nome": tr("the new name"),
        "destinazione": tr("the destination folder"),
        "testo": tr("what to search for"),
        "cartella": tr("the folder"),
        "url": tr("the address"),
        "tema": tr("light or dark"),
        "immagine": tr("the image or wallpaper"),
        "rete": tr("the network name"),
        "ruolo": tr("the role (browser, mail, files, terminal, editor, video, images or pdf)"),
        "dispositivo": tr("the device name"),
        "pacchetto": tr("the package name"),
    }.get(parametro, parametro)


def _sel(w):
    return "address:%s" % w["address"]


# ================================================================ APP
def _app_o_errore(args):
    nome = (args.get("app") or "").strip()
    if not nome:
        return None, Esito(False, tr("Which app?"))
    a = S.trova_app(nome)
    if a is None:
        return None, Esito(False, tr("I can't find “{name}” among the installed apps.").format(name=nome))
    return a, None


def _perche_no():
    """Il motivo piu' comune per cui una finestra non si muove: lo schermo bloccato."""
    rc, _o, _e = S.run(["pgrep", "-x", "hyprlock"], timeout=3)
    return tr(" (the screen is locked: unlock it and try again)") if rc == 0 else ""


def _porta_avanti(w):
    ws = str((w.get("workspace") or {}).get("name", ""))
    if ws.startswith("special:"):
        import sys
        sys.path.insert(0, "/usr/lib/zeta")
        from system import windows
        return windows.restore(w["address"])
    return S.dispatch('hl.dsp.focus({ window = "%s" })' % _sel(w))


@capacita("open_application", "Opens an app (or brings it to the front if it is already open).",
          {"app": "app name, e.g. firefox, mail, terminal, settings"}, ["app"])
def open_application(args):
    # several installations of the same app: never pick one at random
    scelta, domanda = scegli_installazione(args.get("app") or "")
    if domanda:
        return Esito(False, domanda)
    if scelta is not None:
        if _programmi().reg.avvia(scelta):
            return Esito(True, tr("I started {app} ({source}).").format(
                app=scelta.nome, source=_programmi().reg.FONTI.get(scelta.fonte, scelta.fonte)))
        return Esito(False, tr("I can't start {app}.").format(app=scelta.nome))
    a, err = _app_o_errore(args)
    if err:
        return err
    gia = S.finestre_di(a)
    if gia:
        _porta_avanti(gia[0])
        # si controlla davvero: prima lo diceva anche a schermo bloccato
        if S.attendi(lambda: (S.finestra_attiva() or {}).get("address") == gia[0]["address"], 3):
            return Esito(True, tr("{app} was already open: I brought it to the front.").format(app=a.nome))
        return Esito(False, tr("{app} is open but I couldn't bring it to the front{reason}.").format(
            app=a.nome, reason=_perche_no()))
    if not a.argv or not shutil.which(a.argv[0]):
        return Esito(False, tr("{app} appears to be installed but its program ({program}) is missing.").format(
            app=a.nome, program=a.argv[:1]))
    try:
        S.avvia(a.argv)
    except OSError as e:
        return Esito(False, tr("I can't start {app}: {error}").format(app=a.nome, error=e))
    if not S.desktop_attivo():
        return Esito(True, tr("I started {app}.").format(app=a.nome))
    # verifica: compare una sua finestra (Firefox, Thunderbird: qualche secondo)
    if S.attendi(lambda: S.finestre_di(a), 25):
        return Esito(True, tr("{app} is open.").format(app=a.nome))
    if S.processi_di(a):
        return Esito(True, tr("{app} has started; its window is still on the way.").format(app=a.nome))
    return Esito(False, tr("I tried to open {app} but it didn't start.").format(app=a.nome))


def _chiudi_finestre(a, secondi=10):
    ww = S.finestre_di(a)
    for w in ww:
        S.dispatch('hl.dsp.window.close({ window = "%s" })' % _sel(w))
    return S.attendi(lambda: not S.finestre_di(a), secondi)


@capacita("close_application", "Closes an app normally (it may ask to save).",
          {"app": "app name"}, ["app"])
def close_application(args):
    a, err = _app_o_errore(args)
    if err:
        return err
    import sys
    sys.path.insert(0, "/usr/lib/zeta")
    from system import windows
    ww = S.finestre_di(a)
    if not ww:
        pids = S.processi_di(a)
        if not pids:
            return Esito(True, tr("{app} isn't open.").format(app=a.nome), {"gia": True})
        # senza finestre (es. in background): gli si chiede di uscire (TERM),
        # mai d'autorita' (KILL): quello e' «forza la chiusura», con conferma
        for pid in pids:
            if not windows.protetto(pid):
                windows.force_quit(pid, attesa=4.0, forza=False)
        ok = S.attendi(lambda: not S.processi_di(a), 5)
        if ok:
            return Esito(True, tr("{app} is closed.").format(app=a.nome))
        return Esito(False, tr("{app} didn't close by itself. If it's stuck, say “force quit {name}”.").format(
            app=a.nome, name=a.nome.lower()))
    if any(windows.protetto(int(w.get("pid") or 0)) for w in ww):
        return Esito(False, tr("{app} is part of the desktop: I won't close it.").format(app=a.nome))
    if _chiudi_finestre(a, 10):
        # l'ultima finestra chiusa: il processo esce da se' (Firefox salva la sessione)
        S.attendi(lambda: not S.processi_di(a), 6)
        return Esito(True, tr("{app} is closed.").format(app=a.nome))
    rimaste = S.finestre_di(a)
    titoli = ", ".join((w.get("title") or "")[:40] for w in rimaste[:2])
    return Esito(False, tr("{app} didn't close: it's probably asking something ({titles}). "
                           "If it's stuck, say “force quit {name}”.").format(
                               app=a.nome, titles=titoli, name=a.nome.lower()),
                 {"aperte": len(rimaste)})


@capacita("force_close_application", "Force quits a frozen app, together with its child processes.",
          {"app": "app name"}, ["app"], rischio="conferma",
          anteprima=lambda a: tr("Force quit {app} (unsaved work will be lost)").format(app=a.get("app", "")))
def force_close_application(args):
    a, err = _app_o_errore(args)
    if err:
        return err
    import sys
    sys.path.insert(0, "/usr/lib/zeta")
    from system import windows
    pids = {int(w["pid"]) for w in S.finestre_di(a) if w.get("pid")} | set(S.processi_di(a))
    if not pids:
        return Esito(True, tr("{app} isn't open.").format(app=a.nome))
    for pid in pids:
        if windows.protetto(pid):
            return Esito(False, tr("{app} is part of the desktop: I won't close it.").format(app=a.nome))
        windows.force_quit(pid, attesa=3.0)
    ok = S.attendi(lambda: not S.processi_di(a) and not S.finestre_di(a), 5)
    return Esito(ok, (tr("{app} was force quit.") if ok else
                      tr("{app} won't close even this way.")).format(app=a.nome))


@capacita("restart_application", "Closes and reopens an app.", {"app": "app name"}, ["app"])
def restart_application(args):
    a, err = _app_o_errore(args)
    if err:
        return err
    if S.finestre_di(a) or S.processi_di(a):
        c = close_application({"app": a.id})
        if not c.ok:
            return Esito(False, tr("I didn't restart it: {reason}").format(reason=c.messaggio))
        S.attendi(lambda: not S.processi_di(a), 5)
    o = open_application({"app": a.id})
    return Esito(o.ok, tr("{app} has been restarted.").format(app=a.nome) if o.ok else o.messaggio)


# ================================================================ FINESTRE
def _finestra_bersaglio(args):
    """La finestra dell'app indicata, oppure quella attiva."""
    if (args.get("app") or "").strip():
        a, err = _app_o_errore(args)
        if err:
            return None, None, err
        ww = S.finestre_di(a)
        if not ww:
            return a, None, Esito(False, tr("{app} isn't open.").format(app=a.nome))
        return a, ww[0], None
    w = S.finestra_attiva()
    if not w:
        return None, None, Esito(False, tr("There's no active window."))
    return S.app_di_finestra(w), w, None


def _nome(a, w):
    return a.nome if a else (w.get("class") or tr("the window"))


@capacita("focus_application", "Brings an open app to the front (switches to that app).",
          {"app": "app name"}, ["app"])
def focus_application(args):
    a, w, err = _finestra_bersaglio(args)
    if err:
        return err
    _porta_avanti(w)
    ok = S.attendi(lambda: (S.finestra_attiva() or {}).get("address") == w["address"], 3)
    return Esito(ok, tr("You're now on {app}.").format(app=_nome(a, w)) if ok else
                 tr("I couldn't switch to {app}{reason}.").format(app=_nome(a, w), reason=_perche_no()))


@capacita("minimize_window", "Minimizes an app (or the active window).", {"app": "app name (optional)"})
def minimize_window(args):
    a, w, err = _finestra_bersaglio(args)
    if err:
        return err
    # come il pulsante della barra del titolo: foto per la barra e animazione
    S.run(["zeta-riduci", "riduci", w["address"]], timeout=10)
    ok = S.attendi(lambda: any(x["address"] == w["address"] and
                               str(x["workspace"]["name"]).startswith("special:") for x in S.finestre()), 3)
    return Esito(ok, tr("{app} is minimized.").format(app=_nome(a, w)) if ok else
                 tr("I couldn't minimize {app}{reason}.").format(app=_nome(a, w), reason=_perche_no()))


def _stato_schermo(w_addr):
    for x in S.finestre():
        if x["address"] == w_addr:
            return x.get("fullscreen", 0)
    return None


@capacita("maximize_window", "Maximizes (or restores) an app or the active window.",
          {"app": "app name (optional)"})
def maximize_window(args):
    a, w, err = _finestra_bersaglio(args)
    if err:
        return err
    prima = _stato_schermo(w["address"])
    _porta_avanti(w)
    S.dispatch('hl.dsp.window.fullscreen({ mode = "maximized", window = "%s" })' % _sel(w))
    ok = S.attendi(lambda: _stato_schermo(w["address"]) != prima, 3)
    ora = _stato_schermo(w["address"])
    if not ok:
        return Esito(False, tr("I couldn't maximize {app}.").format(app=_nome(a, w)))
    return Esito(True, (tr("{app} is maximized.") if ora else
                        tr("{app} is back to its normal size.")).format(app=_nome(a, w)))


@capacita("fullscreen_window", "Toggles full screen for an app or the active window.",
          {"app": "app name (optional)"})
def fullscreen_window(args):
    a, w, err = _finestra_bersaglio(args)
    if err:
        return err
    prima = _stato_schermo(w["address"])
    _porta_avanti(w)
    S.dispatch('hl.dsp.window.fullscreen({ window = "%s" })' % _sel(w))
    ok = S.attendi(lambda: _stato_schermo(w["address"]) != prima, 3)
    ora = _stato_schermo(w["address"])
    if not ok:
        return Esito(False, tr("I couldn't toggle full screen for {app}.").format(app=_nome(a, w)))
    return Esito(True, (tr("{app} is in full screen.") if ora else
                        tr("{app} is no longer in full screen.")).format(app=_nome(a, w)))


@capacita("close_window", "Closes the active window (not the whole app).", {})
def close_window(args):
    w = S.finestra_attiva()
    if not w:
        return Esito(False, tr("There's no active window."))
    a = S.app_di_finestra(w)
    S.dispatch('hl.dsp.window.close({ window = "%s" })' % _sel(w))
    ok = S.attendi(lambda: all(x["address"] != w["address"] for x in S.finestre()), 6)
    return Esito(ok, (tr("I closed the {app} window.") if ok else
                      tr("The {app} window didn't close: it may be asking you to save.")).format(app=_nome(a, w)))


@capacita("list_running_applications", "Lists the apps that are open right now.", {}, rischio="lettura")
def list_running_applications(args):
    nomi = []
    for w in S.finestre():
        a = S.app_di_finestra(w)
        n = a.nome if a else (w.get("class") or "?")
        rid = str((w.get("workspace") or {}).get("name", "")).startswith("special:")
        n = tr("{app} (minimized)").format(app=n) if rid else n
        if n not in nomi:
            nomi.append(n)
    if not nomi:
        return Esito(True, tr("No apps are open."), {"app": []})
    return Esito(True, tr("Open: {apps}.").format(apps=", ".join(nomi)), {"app": nomi})


@capacita("list_installed_applications", "Lists the installed apps.", {}, rischio="lettura")
def list_installed_applications(args):
    nomi = sorted({a.nome for a in S.app_installate() if not a.nascosta}, key=str.lower)
    return Esito(True, ntr("{n} app: {apps}.", "{n} apps: {apps}.", len(nomi)).format(
        n=len(nomi), apps=", ".join(nomi)), {"app": nomi})


@capacita("is_installed", "Tells whether an app or a program is installed.",
          {"app": "name"}, ["app"], rischio="lettura")
def is_installed(args):
    nome = (args.get("app") or "").strip()
    a = S.trova_app(nome)
    if a:
        return Esito(True, tr("Yes, {app} is installed.").format(app=a.nome))
    if shutil.which(nome):
        return Esito(True, tr("Yes, the {command} command is installed ({path}).").format(
            command=nome, path=shutil.which(nome)))
    return Esito(True, tr("No, “{name}” isn't installed. You can look for it with “install {name}”.").format(
        name=nome), {"installato": False})


def _programmi():
    import sys
    if "/usr/lib/zeta" not in sys.path:
        sys.path.insert(0, "/usr/lib/zeta")
    from system import programmi
    return programmi


@capacita("where_is_program",
          "Tells where an installed program is and how to start it: every installation (APT, Flatpak, "
          "AppImage, /opt...), launch command, executable path, desktop entry, package and version; "
          "also command-line tools (nmap, git, python3) and system services.",
          {"app": "program or command name"}, ["app"], rischio="lettura")
def where_is_program(args):
    nome = (args.get("app") or "").strip()
    if not nome:
        return Esito(False, tr("Which program?"))
    trovati = _programmi().find(nome, services_too=True)
    if not trovati:
        return Esito(True, tr("Nothing called “{name}” is installed.").format(name=nome), {"trovati": []})
    righe = []
    for r in trovati[:8]:
        if r["kind"] == "app":
            righe.append(tr("{name} — app, {source}").format(name=r["name"], source=r["source_label"]))
            righe.append("  " + tr("start: {command}").format(command=r["launch"]))
            if r["path"]:
                righe.append("  " + tr("program: {path}").format(path=_breve(r["path"])))
            righe.append("  " + tr("desktop entry: {path}").format(path=_breve(r["desktop"])))
            if r["flatpak_id"]:
                righe.append("  " + tr("Flatpak ID: {id}").format(id=r["flatpak_id"]))
            if r["package"]:
                righe.append("  " + tr("package: {name} {version}").format(name=r["package"], version=r["version"]))
            elif r["version"]:
                righe.append("  " + tr("version: {version}").format(version=r["version"]))
        elif r["kind"] == "command":
            righe.append(tr("{name} — command").format(name=r["name"]))
            righe.append("  " + tr("path: {path}").format(path=_breve(r["path"])))
            if not r["in_path"]:
                righe.append("  " + tr("not in your PATH: run it as {path}").format(path=r["path"]))
            if r["package"]:
                righe.append("  " + tr("package: {name} {version}").format(name=r["package"], version=r["version"]))
        elif r["kind"] == "service":
            righe.append(tr("{name} — system service ({state})").format(name=r["name"], state=r["active"]))
    return Esito(True, "\n".join(righe), {"trovati": trovati})


@capacita("list_appimages", "Lists the AppImages on this computer and whether they are in the app menu.",
          {}, rischio="lettura")
def list_appimages(args):
    elenco = _programmi().appimages()
    if not elenco:
        return Esito(True, tr("There are no AppImages on this computer. Put them in the Applications "
                              "or Downloads folder and they join the app menu by themselves."), {"appimage": []})
    righe = [ntr("{n} AppImage:", "{n} AppImages:", len(elenco)).format(n=len(elenco))]
    for r in elenco:
        stato = tr("in the menu") if r["in_menu"] else tr("not in the menu")
        righe.append("  %s — %s (%s)" % (r["name"], _breve(r["path"]), stato))
    return Esito(True, "\n".join(righe), {"appimage": elenco})


# the same app installed more than once (APT, Flatpak, AppImage): which one
_FONTI_PAROLE = {"flatpak": "flatpak", "appimage": "appimage", "apt": "apt", "debian": "apt",
                 "deb": "apt", "opt": "opt", "user": "utente", "utente": "utente", "local": "locale",
                 "locale": "locale"}
# the word to say for each source (the first word above that selects it)
_PAROLA_FONTE = {"apt": "APT", "flatpak": "Flatpak", "appimage": "AppImage", "opt": "opt",
                 "utente": "user", "locale": "local"}


def scegli_installazione(nome):
    """(app of the registry, "") for the one installation the user means;
    (None, question) when several installations match and the request does
    not say which; (None, "") when the registry has no such app."""
    programmi = _programmi()
    parole = nome.casefold().split()
    fonte = next((_FONTI_PAROLE[p] for p in parole if p in _FONTI_PAROLE), "")
    resto = " ".join(p for p in parole if p not in _FONTI_PAROLE and p not in ("version", "versione"))
    esatte = [r for r in programmi.apps(resto) if r["name"].casefold() == resto]
    if fonte:
        esatte = [r for r in esatte if r["source"] == fonte]
    if len(esatte) <= 1:
        if esatte and fonte:
            return programmi.reg.trova(esatte[0]["id"]), ""
        return None, ""
    elenco = ", ".join("%s (%s)" % (r["name"], r["source_label"]) for r in esatte)
    con_parola = [r for r in esatte if r["source"] in _PAROLA_FONTE] or esatte
    esempio = "%s %s" % (con_parola[0]["name"], _PAROLA_FONTE.get(con_parola[0]["source"], ""))
    return None, tr("There are {n} installations: {list}. Which one? For example: “open {example}”.").format(
        n=len(esatte), list=elenco, example=esempio)


# ================================================================ FILE E CARTELLE
LUOGHI = {
    "scrivania": "DESKTOP", "desktop": "DESKTOP",
    "documenti": "DOCUMENTS", "documents": "DOCUMENTS",
    "download": "DOWNLOAD", "downloads": "DOWNLOAD", "scaricati": "DOWNLOAD",
    "immagini": "PICTURES", "foto": "PICTURES", "pictures": "PICTURES",
    "musica": "MUSIC", "music": "MUSIC",
    "video": "VIDEOS", "filmati": "VIDEOS", "videos": "VIDEOS",
    "modelli": "TEMPLATES", "pubblici": "PUBLICSHARE",
    "home": "HOME", "casa": "HOME", "cartella personale": "HOME", "personale": "HOME",
    # in inglese
    "photos": "PICTURES", "templates": "TEMPLATES", "public": "PUBLICSHARE",
    "home folder": "HOME", "personal folder": "HOME",
}
_XDG = {}


def cartella_di(luogo: str) -> str | None:
    """«scrivania» -> /home/zeta/Scrivania; un percorso -> lui stesso."""
    if not luogo:
        return None
    l = S.norm(luogo)
    l = re.sub(r"^(la|il|lo|le|i|gli|nella|nel|nei|negli|sulla|sul|in|su|alla|al)\s+", "", l)
    l = re.sub(r"^(?:(?:in|on|to|into|inside|from)\s+)?(?:(?:the|my)\s+)?", "", l)
    l = l.replace("cartella ", "") if l.startswith("cartella ") and l[9:] in LUOGHI else l
    l = l[:-7] if l.endswith(" folder") and l[:-7] in LUOGHI else l       # «documents folder»
    if l in LUOGHI:
        k = LUOGHI[l]
        if k == "HOME":
            return S.HOME
        if k not in _XDG:
            rc, out, _ = S.run(["xdg-user-dir", k], timeout=3)
            _XDG[k] = out if rc == 0 and out and os.path.isdir(out) else None
        return _XDG[k]
    p = os.path.expanduser(luogo.strip())
    if os.path.isabs(p) and os.path.isdir(p):
        return p
    # una cartella per nome, cercata come gli altri elementi
    trov = cerca_elementi(luogo, solo_cartelle=True, limite=2)
    return trov[0] if len(trov) == 1 else None


_ESCLUSE = {".cache", ".local", ".config", ".mozilla", ".thunderbird", "node_modules", ".git", ".var"}


def cerca_elementi(nome: str, dove: str | None = None, solo_cartelle=False, limite=20) -> list[str]:
    """File o cartelle con quel nome (esatto, senza badare a maiuscole o
    all'estensione), prima nei posti soliti poi in tutta la cartella personale."""
    nome = nome.strip().strip("«»\"'")
    p = os.path.expanduser(nome)
    if os.path.isabs(p):
        return [p] if os.path.exists(p) else []
    cercato = nome.lower()

    def combacia(n, pieno):
        if solo_cartelle and not os.path.isdir(pieno):
            return False
        low = n.lower()
        return low == cercato or os.path.splitext(low)[0] == cercato
    trovati = []
    radici = [dove] if dove else [cartella_di(x) for x in ("scrivania", "documenti", "download",
                                                           "immagini", "musica", "video")] + [S.HOME]
    for r in [x for x in radici if x]:
        try:
            for n in os.listdir(r):
                pieno = os.path.join(r, n)
                if combacia(n, pieno) and pieno not in trovati:
                    trovati.append(pieno)
        except OSError:
            continue
    if trovati:
        return trovati[:limite]
    base = dove or S.HOME
    for cart, sotto, files in os.walk(base):
        prof = cart[len(base):].count(os.sep)
        sotto[:] = [d for d in sotto if not d.startswith(".") and d not in _ESCLUSE] if prof < 6 else []
        for n in (sotto if solo_cartelle else sotto + files):
            pieno = os.path.join(cart, n)
            if combacia(n, pieno):
                trovati.append(pieno)
                if len(trovati) >= limite:
                    return trovati
    return trovati


def _dentro_casa(p: str) -> bool:
    """Si scrive solo nella cartella personale e nei dischi montati dall'utente."""
    r = os.path.realpath(p)
    return any(r == b or r.startswith(b + os.sep) for b in
               (os.path.realpath(S.HOME), "/media", "/run/media", "/mnt"))


def _uno(nome, dove=None, solo_cartelle=False):
    """(percorso, None) oppure (None, Esito di errore) se manca o e' ambiguo."""
    if os.path.isabs(nome or "") and os.path.exists(nome) and \
            (not solo_cartelle or os.path.isdir(nome)):
        return nome, None                   # gia' un percorso preciso
    d = cartella_di(dove) if dove else None
    if dove and not d:
        return None, Esito(False, tr("I can't find the folder “{folder}”.").format(folder=dove))
    t = cerca_elementi(nome, d, solo_cartelle=solo_cartelle, limite=6)
    if not t:
        if dove:
            return None, Esito(False, tr("I can't find “{name}” in {folder}.").format(name=nome, folder=dove))
        return None, Esito(False, tr("I can't find “{name}”.").format(name=nome))
    if len(t) > 1:
        elenco = "; ".join(_breve(x) for x in t[:5])
        return None, Esito(False, tr("There's more than one “{name}”: {list}. Which one? "
                                     "Tell me the folder too.").format(name=nome, list=elenco),
                           {"ambiguo": t})
    return t[0], None


def _breve(p):
    return p.replace(S.HOME, "~", 1)


def _nome_libero(cartella, nome):
    dest = os.path.join(cartella, nome)
    base, ext = os.path.splitext(nome)
    n = 2
    while os.path.exists(dest):
        dest = os.path.join(cartella, "%s (%d)%s" % (base, n, ext))
        n += 1
    return dest


@capacita("create_folder", "Creates a folder.", {"nome": "name of the new folder",
          "dove": "where to create it: desktop, documents, downloads... or a path (default: home folder)"},
          ["nome"])
def create_folder(args):
    nome = (args.get("nome") or "").strip().strip("«»\"'")
    if not nome or "/" in nome:
        return Esito(False, tr("That folder name isn't valid."))
    base = cartella_di(args.get("dove") or "home")
    if not base:
        return Esito(False, tr("I can't find the folder “{folder}”.").format(folder=args.get("dove")))
    dest = os.path.join(base, nome)
    if not _dentro_casa(dest):
        return Esito(False, tr("I only create folders in your home folder or on external drives."))
    if os.path.isdir(dest):
        return Esito(True, tr("The folder {path} already exists.").format(path=_breve(dest)), {"percorso": dest})
    try:
        os.makedirs(dest)
    except OSError as e:
        return Esito(False, tr("I couldn't create {path}: {error}").format(path=_breve(dest), error=e.strerror))
    return Esito(os.path.isdir(dest), tr("I created the folder {path}.").format(path=_breve(dest)),
                 {"percorso": dest})


@capacita("create_file", "Creates a text file, optionally with some content.",
          {"nome": "file name, e.g. notes.txt", "dove": "folder (default: documents)",
           "testo": "content (optional)"}, ["nome"])
def create_file(args):
    nome = (args.get("nome") or "").strip().strip("«»\"'")
    if not nome or "/" in nome:
        return Esito(False, tr("That file name isn't valid."))
    base = cartella_di(args.get("dove") or "documenti")
    if not base:
        return Esito(False, tr("I can't find the folder “{folder}”.").format(folder=args.get("dove")))
    dest = os.path.join(base, nome)
    if not _dentro_casa(dest):
        return Esito(False, tr("I only create files in your home folder or on external drives."))
    if os.path.exists(dest):
        return Esito(False, tr("{path} already exists: I won't overwrite it.").format(path=_breve(dest)))
    try:
        with open(dest, "x", encoding="utf-8") as f:
            f.write(args.get("testo") or "")
    except OSError as e:
        return Esito(False, tr("I couldn't create {path}: {error}").format(path=_breve(dest), error=e.strerror))
    return Esito(os.path.isfile(dest), tr("I created {path}.").format(path=_breve(dest)), {"percorso": dest})


@capacita("rename_item", "Renames a file or a folder.",
          {"elemento": "file or folder to rename", "nuovo_nome": "the new name",
           "dove": "folder it is in (optional)"},
          ["elemento", "nuovo_nome"])
def rename_item(args):
    src, err = _uno(args.get("elemento", ""), args.get("dove"))
    if err:
        return err
    nuovo = (args.get("nuovo_nome") or "").strip().strip("«»\"'")
    if not nuovo or "/" in nuovo:
        return Esito(False, tr("That new name isn't valid."))
    if "." not in nuovo and os.path.isfile(src) and os.path.splitext(src)[1]:
        nuovo += os.path.splitext(src)[1]          # «rinomina nota.txt in appunti» tiene .txt
    dest = os.path.join(os.path.dirname(src), nuovo)
    if not _dentro_casa(src):
        return Esito(False, tr("I only rename things in your home folder or on external drives."))
    if os.path.exists(dest):
        return Esito(False, tr("{path} already exists.").format(path=_breve(dest)))
    try:
        os.rename(src, dest)
    except OSError as e:
        return Esito(False, tr("I couldn't rename it: {error}").format(error=e.strerror))
    ok = os.path.exists(dest) and not os.path.exists(src)
    return Esito(ok, tr("I renamed {old} to {new}.").format(old=os.path.basename(src), new=nuovo),
                 {"percorso": dest})


def _destinazione(args):
    d = args.get("destinazione") or args.get("dove_va") or ""
    base = cartella_di(d) if d else None
    if not base:
        return None, Esito(False, tr("I can't find the destination folder “{folder}”.").format(folder=d))
    if not _dentro_casa(base):
        return None, Esito(False, tr("I only write to your home folder or to external drives."))
    return base, None


@capacita("copy_item", "Copies a file or a folder into another folder.",
          {"elemento": "file or folder", "destinazione": "destination folder (desktop, documents, ... or a path)",
           "dove": "folder it is in (optional)"}, ["elemento", "destinazione"])
def copy_item(args):
    src, err = _uno(args.get("elemento", ""), args.get("dove"))
    if err:
        return err
    base, err = _destinazione(args)
    if err:
        return err
    dest = _nome_libero(base, os.path.basename(src))
    try:
        if os.path.isdir(src):
            shutil.copytree(src, dest, symlinks=True)
        else:
            shutil.copy2(src, dest)
    except (OSError, shutil.Error) as e:
        return Esito(False, tr("Copy failed: {error}").format(error=e))
    ok = os.path.exists(dest) and (os.path.isdir(src) or os.path.getsize(dest) == os.path.getsize(src))
    return Esito(ok, tr("I copied {name} to {path}.").format(name=os.path.basename(src), path=_breve(dest)),
                 {"percorso": dest})


@capacita("move_item", "Moves a file or a folder into another folder.",
          {"elemento": "file or folder", "destinazione": "destination folder",
           "dove": "folder it is in now (optional)"},
          ["elemento", "destinazione"])
def move_item(args):
    src, err = _uno(args.get("elemento", ""), args.get("dove"))
    if err:
        return err
    base, err = _destinazione(args)
    if err:
        return err
    if not _dentro_casa(src):
        return Esito(False, tr("I only move files from your home folder or from external drives."))
    if os.path.dirname(os.path.realpath(src)) == os.path.realpath(base):
        return Esito(True, tr("{name} is already in {path}.").format(name=os.path.basename(src), path=_breve(base)))
    dest = _nome_libero(base, os.path.basename(src))
    try:
        shutil.move(src, dest)
    except (OSError, shutil.Error) as e:
        return Esito(False, tr("Move failed: {error}").format(error=e))
    ok = os.path.exists(dest) and not os.path.exists(src)
    return Esito(ok, tr("I moved {name} to {path}.").format(name=os.path.basename(src), path=_breve(base)),
                 {"percorso": dest})


_VAGHI = {"tutto", "tutti", "tutte", "ogni cosa", "qualcosa", "tutto quanto", "tutti i file", "questo", "quello",
          "everything", "all", "all of it", "all files", "all the files", "all my files", "every file",
          "anything", "something", "this", "that", "it", "them", "these", "those", "stuff", "all of them",
          "files", "my files", "the files", "every thing"}


def _controlla_elimina(args):
    """L'oggetto da eliminare: uno solo, esistente, non protetto."""
    if S.norm(args.get("elemento", "")) in _VAGHI:
        return Esito(False, tr("I won't delete “{name}”: tell me the name of the file or folder.").format(
            name=args["elemento"]))
    src, err = _uno(args.get("elemento", ""), args.get("dove"))
    if err:
        return err
    if not _dentro_casa(src) or os.path.realpath(src) in (os.path.realpath(S.HOME),) or \
            os.path.realpath(src) in {cartella_di(x) for x in LUOGHI if LUOGHI[x] != "HOME"}:
        return Esito(False, tr("{path} can't be deleted from here.").format(path=_breve(src)))
    args["_percorso"] = src
    return None


@capacita("delete_item", "Moves a file or a folder to the trash (it can be restored).",
          {"elemento": "file or folder", "dove": "folder it is in (optional)"}, ["elemento"],
          rischio="conferma", controlla=_controlla_elimina,
          anteprima=lambda a: tr("Move {name} to the trash").format(
              name=_breve(a["_percorso"]) if a.get("_percorso") else "«%s»" % a.get("elemento", "")))
def delete_item(args):
    err = _controlla_elimina(args)
    if err:
        return err
    src = args["_percorso"]
    rc, _o, e = S.run(["gio", "trash", "--", src], timeout=30)
    ok = rc == 0 and not os.path.exists(src)
    return Esito(ok, tr("I moved {name} to the trash (it can be restored).").format(name=os.path.basename(src))
                 if ok else tr("I couldn't delete it: {error}").format(error=e or tr("error")))


@capacita("search_files", "Searches files and folders by name.",
          {"testo": "part of the name, or *.pdf", "dove": "folder to search in (default: the whole home folder)"},
          ["testo"], rischio="lettura")
def search_files(args):
    q = (args.get("testo") or "").strip().strip("«»\"'")
    if not q:
        return Esito(False, tr("What should I search for?"))
    base = cartella_di(args["dove"]) if args.get("dove") else S.HOME
    if not base:
        return Esito(False, tr("I can't find the folder “{folder}”.").format(folder=args.get("dove")))
    fd = shutil.which("fdfind") or shutil.which("fd")
    if fd:
        cmd = [fd, "--max-results", "30", "--ignore-case"]
        cmd += (["--glob", q] if any(c in q for c in "*?") else ["--fixed-strings", q])
        # con una cartella assoluta fd restituisce percorsi assoluti
        _rc, out, _e = S.run(cmd + [base], timeout=20)
        trovati = [x for x in out.splitlines() if x]
    else:
        trovati = [p for p in cerca_elementi(q, base, limite=30)]
    if not trovati:
        if base == S.HOME:
            return Esito(True, tr("No files or folders matching “{text}”.").format(text=q), {"trovati": []})
        return Esito(True, tr("No files or folders matching “{text}” in {folder}.").format(
            text=q, folder=_breve(base)), {"trovati": []})
    elenco = "\n".join("  " + _breve(x) for x in trovati[:15])
    if len(trovati) > 15:
        testa = tr("Found {n} (and more):").format(n=len(trovati))
    else:
        testa = tr("Found {n}:").format(n=len(trovati))
    return Esito(True, testa + "\n" + elenco, {"trovati": trovati})


def _apri_e_verifica(cmd, cosa, secondi=15):
    prima = {w["address"] for w in S.finestre()}
    try:
        S.avvia(cmd)
    except OSError as e:
        return Esito(False, tr("I can't open {item}: {error}").format(item=cosa, error=e))
    if not S.desktop_attivo():
        return Esito(True, tr("I opened {item}.").format(item=cosa))
    nuova = S.attendi(lambda: {w["address"] for w in S.finestre()} - prima, secondi)
    return Esito(bool(nuova), tr("I opened {item}.").format(item=cosa) if nuova else
                 tr("I asked to open {item} but no window appeared.").format(item=cosa))


@capacita("open_file", "Opens a file with its default app.",
          {"elemento": "file to open", "dove": "folder (optional)"}, ["elemento"])
def open_file(args):
    src, err = _uno(args.get("elemento", ""), args.get("dove"))
    if err:
        return err
    if os.path.isdir(src):
        return open_folder({"cartella": src})
    return _apri_e_verifica(["xdg-open", src], os.path.basename(src))


@capacita("open_folder", "Opens a folder in the file manager.",
          {"cartella": "desktop, documents, downloads, pictures, music, videos, home, trash, or a path/name"},
          ["cartella"])
def open_folder(args):
    c = (args.get("cartella") or "home").strip()
    if S.norm(c) in ("cestino", "il cestino", "trash", "the trash", "trash can", "recycle bin"):
        return _apri_e_verifica(["zeta-predefinita", "file", "trash:///"], tr("the trash"))
    d = cartella_di(c)
    if not d:
        d_, err = _uno(c, solo_cartelle=True)
        if err:
            return err
        d = d_
    return _apri_e_verifica(["zeta-predefinita", "file", d], tr("the folder {path}").format(path=_breve(d)))


@capacita("show_location", "Shows the folder a file is in.",
          {"elemento": "file or folder"}, ["elemento"])
def show_location(args):
    src, err = _uno(args.get("elemento", ""), args.get("dove"))
    if err:
        return err
    r = _apri_e_verifica(["zeta-predefinita", "file", os.path.dirname(src)],
                         tr("the folder containing {name}").format(name=os.path.basename(src)))
    if r.ok:
        r.messaggio = tr("{name} is in {folder}: I opened the folder.").format(
            name=os.path.basename(src), folder=_breve(os.path.dirname(src)))
    return r


@capacita("download_file", "Downloads a file from the internet into a folder.",
          {"url": "http(s) address", "dove": "folder (default: downloads)"}, ["url"])
def download_file(args):
    import urllib.parse
    import urllib.request
    url = (args.get("url") or "").strip()
    if not re.match(r"^https?://", url):
        return Esito(False, tr("I need an address that starts with http:// or https://."))
    base = cartella_di(args.get("dove") or "download")
    if not base or not _dentro_casa(base):
        return Esito(False, tr("Invalid destination folder."))
    anonimo = tr("download")                # nome del file quando l'indirizzo non ne ha uno
    nome = os.path.basename(urllib.parse.unquote(urllib.parse.urlparse(url).path)) or anonimo
    dest = _nome_libero(base, nome)
    tmp = dest + ".parziale"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ZETA-RAYS/2.0"})
        with urllib.request.urlopen(req, timeout=30) as r, open(tmp, "wb") as f:
            cd = r.headers.get("Content-Disposition", "")
            m = re.search(r'filename="?([^";]+)"?', cd)
            if m and nome == anonimo:
                dest = _nome_libero(base, os.path.basename(m.group(1)))
            shutil.copyfileobj(r, f, 1 << 20)
        os.replace(tmp, dest)
    except Exception as e:  # noqa: BLE001 - rete, disco, indirizzo: si dice cosa e' successo
        try:
            os.unlink(tmp)
        except OSError:
            pass
        return Esito(False, tr("Download failed: {error}").format(error=e))
    ok = os.path.isfile(dest) and os.path.getsize(dest) > 0
    return Esito(ok, tr("I downloaded {name} to {folder} ({size} MB).").format(
        name=os.path.basename(dest), folder=_breve(base), size="%.1f" % (os.path.getsize(dest) / 1e6)),
        {"percorso": dest})


# ================================================================ SISTEMA
PAGINE = {"aspetto": "aspetto", "tema": "aspetto", "colori": "aspetto", "sfondo": "aspetto",
          "dock": "dock", "barra": "dock", "schermo": "schermo", "blocco": "schermo", "display": "schermo",
          "luminosita": "schermo", "monitor": "schermo",
          "notifiche": "notifiche", "rete": "rete", "wifi": "rete", "wi-fi": "rete", "internet": "rete",
          "bluetooth": "bluetooth", "audio": "audio", "suono": "audio", "volume": "audio",
          "stampanti": "stampanti", "stampante": "stampanti", "stampa": "stampanti",
          "ai": "ai", "intelligenza": "ai", "intelligenza artificiale": "ai", "zeta": "ai",
          "informazioni": "info", "info": "info", "sistema": "info",
          "app predefinite": "predefinite", "applicazioni predefinite": "predefinite", "predefinite": "predefinite",
          # in inglese
          "appearance": "aspetto", "theme": "aspetto", "colors": "aspetto", "colours": "aspetto",
          "wallpaper": "aspetto", "background": "aspetto", "bar": "dock", "taskbar": "dock", "panel": "dock",
          "screen": "schermo", "lock screen": "schermo", "brightness": "schermo",
          "notifications": "notifiche", "network": "rete", "sound": "audio",
          "printers": "stampanti", "printer": "stampanti", "printing": "stampanti",
          "artificial intelligence": "ai", "assistant": "ai", "about": "info", "information": "info",
          "system": "info", "default apps": "predefinite", "default applications": "predefinite"}
APP_IMPOSTAZIONI = {"sicurezza": "zeta-sicurezza", "firewall": "zeta-sicurezza",
                    "pacchetti": "synaptic", "security": "zeta-sicurezza", "packages": "synaptic"}


def _nome_pagina(pagina):
    """Il nome mostrato di una pagina delle Impostazioni."""
    return {"aspetto": tr("Appearance"), "dock": tr("Dock"), "schermo": tr("Display"),
            "notifiche": tr("Notifications"), "rete": tr("Network"), "bluetooth": "Bluetooth",
            "audio": tr("Sound"), "stampanti": tr("Printers"), "ai": "AI", "info": tr("About"),
            "predefinite": tr("Default Apps")}.get(pagina, pagina)


@capacita("open_settings", "Opens Settings, optionally on a page (appearance, dock, display, notifications, "
          "network, bluetooth, sound, printers, ai, about, default apps).", {"pagina": "optional"})
def open_settings(args):
    p = S.norm(args.get("pagina") or "")
    p = re.sub(r"^(di |del |della |dello |dei |delle |per |su |sul |sulla )", "", p)
    p = re.sub(r"^(?:(?:of|for|on|about)\s+)?(?:(?:the|my)\s+)?", "", p)
    if p in APP_IMPOSTAZIONI:
        return open_application({"app": APP_IMPOSTAZIONI[p]})
    a = S.trova_app("impostazioni")
    if a:
        for w in S.finestre_di(a):          # una sola finestra delle Impostazioni
            S.dispatch('hl.dsp.window.close({ window = "%s" })' % _sel(w))
        S.attendi(lambda: not S.finestre_di(a), 3)
    pagina = PAGINE.get(p)
    if p and not pagina:
        # impostazioni di un'app: si apre l'app (le sue preferenze sono dentro)
        app = S.trova_app(p)
        if app:
            r = open_application({"app": app.id})
            if r.ok:
                r.messaggio += " " + tr("Its settings are in its own menu.")
            return r
        return Esito(False, tr("I don't know the Settings page “{page}”.").format(page=p))
    r = _apri_e_verifica(["zeta-impostazioni"] + ([pagina] if pagina else []),
                         tr("Settings › {page}").format(page=_nome_pagina(pagina)) if pagina
                         else tr("the Settings app"))
    return r


def _volume():
    rc, out, _ = S.run(["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"], timeout=4, c_locale=True)
    if rc != 0:
        return None, None
    m = re.search(r"Volume:\s*([\d.]+)", out)
    return (round(float(m.group(1)) * 100) if m else None), ("MUTED" in out)


@capacita("set_volume", "Sets the volume (0-100), raises/lowers it by a step, or mutes it.",
          {"livello": "0-100 (optional)", "variazione": "+N or -N (optional)",
           "muto": "true to mute, false to unmute (optional)"})
def set_volume(args):
    vol, muto = _volume()
    if vol is None:
        return Esito(False, tr("I can't find the audio output."))
    if "muto" in args and args["muto"] is not None:
        voglio = bool(args["muto"]) if not isinstance(args["muto"], str) else \
            args["muto"].lower() in ("true", "si", "sì", "yes", "1")
        S.run(["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "1" if voglio else "0"])
        _, m2 = _volume()
        S.run(["pkill", "-RTMIN+11", "-x", "waybar"])
        return Esito(m2 == voglio, tr("Sound muted.") if voglio else tr("Sound unmuted."))
    if args.get("livello") is not None:
        try:
            obiettivo = int(float(str(args["livello"]).rstrip("%")))
        except ValueError:
            return Esito(False, tr("Invalid volume level."))
    elif args.get("variazione") is not None:
        try:
            obiettivo = vol + int(float(str(args["variazione"]).rstrip("%")))
        except ValueError:
            return Esito(False, tr("Invalid volume change."))
    else:
        return Esito(True, (tr("The volume is at {level}% (muted).") if muto else
                            tr("The volume is at {level}%.")).format(level=vol), {"volume": vol})
    obiettivo = max(0, min(100, obiettivo))
    S.run(["zeta-volume", "imposta", str(obiettivo)])
    if muto and obiettivo > 0:
        S.run(["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "0"])
    ora, _ = _volume()
    return Esito(ora is not None and abs(ora - obiettivo) <= 1, tr("Volume at {level}%.").format(level=ora or 0),
                 {"volume": ora})


def _retroilluminazione():
    import glob
    for d in sorted(glob.glob("/sys/class/backlight/*")):
        try:
            cur = int(open(d + "/brightness").read())
            mx = int(open(d + "/max_brightness").read()) or 1
            return os.path.basename(d), round(cur * 100 / mx)
        except (OSError, ValueError):
            continue
    return None, None


@capacita("set_brightness", "Sets the screen brightness (0-100) or changes it by a step.",
          {"livello": "0-100 (optional)", "variazione": "+N or -N (optional)"})
def set_brightness(args):
    dev, ora = _retroilluminazione()
    if dev is None:
        return Esito(False, tr("This screen's brightness can't be adjusted from the computer "
                               "(this happens with external monitors and virtual machines): "
                               "use the monitor's buttons."))
    if args.get("livello") is not None:
        obiettivo = int(float(str(args["livello"]).rstrip("%")))
    elif args.get("variazione") is not None:
        obiettivo = ora + int(float(str(args["variazione"]).rstrip("%")))
    else:
        return Esito(True, tr("Brightness is at {level}%.").format(level=ora), {"luminosita": ora})
    obiettivo = max(1, min(100, obiettivo))
    rc, _o, e = S.run(["brightnessctl", "-d", dev, "set", "%d%%" % obiettivo], timeout=5)
    _d, dopo = _retroilluminazione()
    ok = rc == 0 and dopo is not None and abs(dopo - obiettivo) <= 2
    return Esito(ok, tr("Brightness at {level}%.").format(level=dopo) if ok else
                 tr("I couldn't change the brightness: {error}").format(error=e or tr("error")))


def _power():
    import sys
    sys.path.insert(0, "/usr/lib/zeta")
    from system import power
    return power


@capacita("lock_screen", "Locks the screen.", {})
def lock_screen(args):
    _power().lock()
    ok = S.attendi(lambda: S.run(["pgrep", "-x", "hyprlock"])[0] == 0, 4)
    return Esito(ok, tr("Screen locked.") if ok else tr("I couldn't lock the screen."))


@capacita("suspend_system", "Puts the computer to sleep (suspend).", {})
def suspend_system(args):
    p = _power()
    p.suspend()
    return Esito(True, tr("Putting the computer to sleep.") if p.can_suspend() else
                 tr("Sleep isn't safe here: I locked the screen and I'm turning it off."))


@capacita("logout", "Logs out of the session (closes all apps).", {}, rischio="conferma",
          anteprima=lambda a: tr("Log out: all apps will be closed"))
def logout(args):
    ok = S.dispatch("hl.dsp.exit()")          # risposta «ok» di Hyprland
    return Esito(ok, tr("Logging out.") if ok else tr("Hyprland didn't accept the logout."))


@capacita("restart_system", "Restarts the computer.", {}, rischio="conferma",
          anteprima=lambda a: tr("Restart the computer: open apps will be closed"))
def restart_system(args):
    return _energia("reboot", tr("The computer is restarting."))


@capacita("shutdown_system", "Shuts down the computer.", {}, rischio="conferma",
          anteprima=lambda a: tr("Shut down the computer: open apps will be closed"))
def shutdown_system(args):
    return _energia("poweroff", tr("The computer is shutting down."))


def _energia(azione, messaggio):
    """Riavvio e spegnimento: si aspetta la risposta di systemd. Prima si
    lanciava il comando e si diceva «Riavvio il computer» anche quando il
    sistema rifiutava (visto: da una sessione non locale il riavvio non
    partiva e ZETA diceva di averlo fatto)."""
    rc, out, err = S.run(["systemctl", azione, "--no-ask-password"], timeout=20)
    if rc == 0:
        return Esito(True, messaggio)
    motivo = (err or out or "").strip().splitlines()
    motivo = motivo[-1][:160] if motivo else tr("unknown reason")
    if "authentication" in motivo.lower() or "autenticazione" in motivo.lower():
        motivo = tr("you need to be in the computer's local session (or have the administrator password)")
    return Esito(False, tr("The system refused: {reason}.").format(reason=motivo))


@capacita("set_theme", "Light or dark theme.", {"tema": "light or dark"}, ["tema"])
def set_theme(args):
    t = "chiaro" if S.norm(args.get("tema", "")).startswith(("chiar", "light")) else "scuro"
    S.run(["zeta-aspetto", "set", "tema", t], timeout=40)      # applica anche
    try:
        ora = open(os.path.join(S.HOME, ".config/zeta/tema")).read().strip()
    except OSError:
        ora = ""
    if ora != t:
        return Esito(False, tr("The theme didn't change."))
    return Esito(True, tr("Light theme on.") if t == "chiaro" else tr("Dark theme on."))


@capacita("set_wallpaper", "Changes the wallpaper to an image, to one of the ZETA RAYS wallpapers "
          "(Blue waves, Green circuits, Red waves, Terminal, Blue/green/red/white logo) "
          "or back to the ZETA RAYS default.",
          {"immagine": "image file, name of a ZETA RAYS wallpaper, or \"default\""}, ["immagine"])
def set_wallpaper(args):
    nome = (args.get("immagine") or "").strip()
    if S.norm(nome) in ("predefinito", "originale", "zeta", "zeta rays", "di zeta rays",
                        "default", "the default", "the default one", "original", "the original",
                        "the original one", "zeta rays default"):
        rc, _o, e = S.run(["zeta-sfondo", "reset"], timeout=30)
        return Esito(rc == 0, tr("The ZETA RAYS wallpaper is back.") if rc == 0 else
                     tr("That didn't work: {error}").format(error=e))
    # prima gli sfondi di ZETA RAYS per nome («onde rosse»), poi i file dell'utente
    from system import sfondi
    ufficiale = sfondi.cerca(nome)
    if ufficiale:
        rc, _o, e = S.run(["zeta-sfondo", "set", ufficiale], timeout=30)
        # verifica: zeta-sfondo deve rispondere con lo sfondo scelto
        _r, ora, _e = S.run(["zeta-sfondo", "get"])
        ok = rc == 0 and ora.split("\n")[0].strip() == ufficiale
        return Esito(ok, tr("Wallpaper changed: {name}.").format(name=sfondi.nome_di(ufficiale)) if ok
                     else tr("That didn't work: {error}").format(error=e or tr("the wallpaper didn't change")))
    src, err = _uno(nome, args.get("dove"))
    if err:
        return err
    rc, _o, e = S.run(["zeta-sfondo", "set", src], timeout=30)
    return Esito(rc == 0, tr("Wallpaper changed: {name}.").format(name=os.path.basename(src)) if rc == 0
                 else tr("That didn't work: {error}").format(error=e))


# ================================================================ RETE
def _wifi_radio():
    # uscita letta e confrontata: in inglese fisso (in italiano diceva «abilitato»)
    rc, out, _ = S.run(["nmcli", "-t", "radio", "wifi"], timeout=5, c_locale=True)
    return out.strip() == "enabled" if rc == 0 else None


def _wifi_dev():
    rc, out, _ = S.run(["nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device"], timeout=5, c_locale=True)
    for r in out.splitlines():
        p = r.split(":")
        if len(p) >= 4 and p[1] == "wifi":
            return {"device": p[0], "state": p[2], "connection": p[3]}
    return None


@capacita("wifi_on", "Turns Wi-Fi on.", {})
def wifi_on(args):
    if _wifi_dev() is None:
        return Esito(False, tr("This computer has no Wi-Fi adapter."))
    S.run(["nmcli", "radio", "wifi", "on"], timeout=10)
    ok = S.attendi(lambda: _wifi_radio() is True, 5)
    return Esito(ok, tr("Wi-Fi is on.") if ok else tr("I couldn't turn Wi-Fi on."))


@capacita("wifi_off", "Turns Wi-Fi off.", {})
def wifi_off(args):
    if _wifi_dev() is None:
        return Esito(False, tr("This computer has no Wi-Fi adapter."))
    S.run(["nmcli", "radio", "wifi", "off"], timeout=10)
    ok = S.attendi(lambda: _wifi_radio() is False, 5)
    return Esito(ok, tr("Wi-Fi is off.") if ok else tr("I couldn't turn Wi-Fi off."))


@capacita("wifi_list", "Lists nearby Wi-Fi networks.", {}, rischio="lettura")
def wifi_list(args):
    if _wifi_dev() is None:
        return Esito(False, tr("This computer has no Wi-Fi adapter."))
    if _wifi_radio() is False:
        return Esito(False, tr("Wi-Fi is off: say “turn on Wi-Fi”."))
    rc, out, _ = S.run(["nmcli", "-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY", "device", "wifi", "list",
                        "--rescan", "auto"], timeout=20, c_locale=True)
    reti = []
    for r in out.splitlines():
        p = r.replace("\\:", "\x00").split(":")
        if len(p) >= 4 and p[1]:
            nome = p[1].replace("\x00", ":")
            voce = (tr("{name} ({signal}%, open)") if not p[3] else tr("{name} ({signal}%)")).format(
                name=nome, signal=p[2])
            reti.append(("● " if p[0] == "*" else "") + voce)
    if not reti:
        return Esito(True, tr("No Wi-Fi networks found nearby."), {"reti": []})
    return Esito(True, tr("Wi-Fi networks: {list}.").format(list="; ".join(dict.fromkeys(reti))), {"reti": reti})


@capacita("wifi_connect", "Connects to a Wi-Fi network (with its password, if needed).",
          {"rete": "network name (SSID)", "password": "optional"}, ["rete"])
def wifi_connect(args):
    import sys
    sys.path.insert(0, "/usr/lib/zeta")
    from system import network
    ssid = (args.get("rete") or "").strip().strip("«»\"'")
    if _wifi_dev() is None:
        return Esito(False, tr("This computer has no Wi-Fi adapter."))
    if _wifi_radio() is False:
        wifi_on({})
    ok, msg, motivo = network.connect_wifi_esito(ssid, args.get("password") or None)
    if ok:
        return Esito(True, tr("Connected to “{name}”.").format(name=ssid))
    if motivo == "password":
        return Esito(False, tr("The password for “{name}” is wrong (or missing): tell me again, "
                               "e.g. “connect to {name} with password …”.").format(name=ssid),
                     {"motivo": "password"})
    if motivo == "non trovata":
        return Esito(False, tr("I don't see any network called “{name}” nearby.").format(name=ssid),
                     {"motivo": motivo})
    return Esito(False, tr("I didn't connect to “{name}”: {reason}").format(name=ssid, reason=msg),
                 {"motivo": motivo})


@capacita("wifi_disconnect", "Disconnects from the current Wi-Fi network (Wi-Fi stays on).", {})
def wifi_disconnect(args):
    d = _wifi_dev()
    if d is None:
        return Esito(False, tr("This computer has no Wi-Fi adapter."))
    if not d["state"].startswith("connected"):
        return Esito(True, tr("Wi-Fi isn't connected to any network."))
    S.run(["nmcli", "device", "disconnect", d["device"]], timeout=15)
    ok = S.attendi(lambda: not (_wifi_dev() or {}).get("state", "").startswith("connected"), 6)
    return Esito(ok, tr("Disconnected from “{name}”.").format(name=d["connection"]) if ok else
                 tr("I couldn't disconnect."))


@capacita("network_status", "Network status: connection, Wi-Fi, IP addresses.", {}, rischio="lettura")
def network_status(args):
    import sys
    sys.path.insert(0, "/usr/lib/zeta")
    from system import network
    rc, out, _ = S.run(["nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device"], timeout=5, c_locale=True)
    righe = []
    for r in out.splitlines():
        p = r.replace("\\:", "\x00").split(":")
        p = [x.replace("\x00", ":") for x in p]
        if len(p) < 4 or p[1] not in ("ethernet", "wifi") or p[2] == "unmanaged":
            continue                 # le schede non gestite (es. un punto di accesso) non contano
        tipo = "Wi-Fi" if p[1] == "wifi" else tr("Cable")
        if p[2].startswith("connected"):
            _rc2, ip, _ = S.run(["ip", "-4", "-br", "addr", "show", p[0]], timeout=3)
            ind = ip.split()[2].split("/")[0] if len(ip.split()) > 2 else ""
            nome = network.nice_name(p[3], p[1])
            if ind:
                righe.append(tr("{type}: connected to “{name}”, address {ip}").format(type=tipo, name=nome, ip=ind))
            else:
                righe.append(tr("{type}: connected to “{name}”").format(type=tipo, name=nome))
        else:
            stato = {"disconnected": tr("not connected"), "unavailable": tr("unavailable")}.get(p[2], p[2])
            righe.append("%s: %s" % (tipo, stato))
    radio = _wifi_radio()
    if radio is False:
        righe.append(tr("Wi-Fi off"))
    rc, gw, _ = S.run(["ip", "route", "show", "default"], timeout=3)
    if gw:
        righe.append(tr("Internet: yes, via {gateway}").format(gateway=gw.split()[2]))
    else:
        righe.append(tr("Internet: no route"))
    return Esito(True, ". ".join(righe) + ".")


# ================================================================ APP PREDEFINITE
def _predefinite():
    import sys
    if "/usr/lib/zeta" not in sys.path:
        sys.path.insert(0, "/usr/lib/zeta")
    from system import predefinite
    return predefinite


# ruoli detti in inglese che non sono anche nomi di app (quelli stanno in S.RUOLI)
_RUOLI_EN = {"mail": "posta", "email": "posta", "e-mail": "posta", "terminal": "terminale",
             "images": "immagini", "pictures": "immagini", "photos": "immagini", "videos": "video",
             "music": "video", "pdfs": "pdf"}


@capacita("set_default_app", "Sets the default app for a role (browser, mail, files, terminal, "
          "editor, video, images, pdf).",
          {"ruolo": "browser, posta (mail), file, terminale (terminal), editor, video, immagini (images) or pdf",
           "app": "app name"},
          ["ruolo", "app"])
def set_default_app(args):
    P = _predefinite()
    r = S.norm(args.get("ruolo", ""))
    ruolo = S.RUOLI.get(r) or _RUOLI_EN.get(r, r)
    if ruolo not in P.CATEGORIE:
        return Esito(False, tr("I don't know the role “{role}”: I can set browser, mail, files, terminal, "
                               "editor, video, images or pdf.").format(role=args.get("ruolo")))
    # qui il nome indica un'app, non un ruolo: «l'editor di testo» e' l'app
    # che si chiama cosi', non l'editor predefinito di adesso
    a = S.trova_app(args.get("app", ""), ruoli=False)
    if a is None:
        return Esito(False, tr("I can't find “{name}” among the installed apps.").format(name=args.get("app")))
    candidate = [c[0] for c in P.candidate(ruolo)]
    if a.id + ".desktop" not in candidate:
        return Esito(False, tr("{app} can't be used for: {role}.").format(app=a.nome, role=P.CATEGORIE[ruolo][0]))
    ok, msg = P.imposta(ruolo, a.id + ".desktop")
    return Esito(ok, msg)


@capacita("list_default_apps", "Which apps are the defaults (browser, mail, terminal...).", {},
          rischio="lettura")
def list_default_apps(args):
    from gi.repository import Gio
    P = _predefinite()
    righe = []
    for c in P.ORDINE:
        aid = P.attuale(c)
        info = Gio.DesktopAppInfo.new(aid) if aid else None
        righe.append("%s: %s" % (P.CATEGORIE[c][0], P.nome(aid, info) if info else tr("not set")))
    return Esito(True, tr("Default apps — {list}.").format(list="; ".join(righe)))


# ================================================================ BLUETOOTH
def _bt():
    import sys
    sys.path.insert(0, "/usr/lib/zeta")
    from system import bluetooth
    return bluetooth


def _bt_pronto():
    bt = _bt()
    a = bt.adapter()
    if a is None:
        return bt, None, Esito(False, tr("This computer has no Bluetooth (or it's disabled in the BIOS)."))
    return bt, a, None


@capacita("bluetooth_on", "Turns Bluetooth on.", {})
def bluetooth_on(args):
    bt, a, err = _bt_pronto()
    if err:
        return err
    bt.set_power(True)
    ok = S.attendi(lambda: (bt.adapter() or {}).get("powered"), 5)
    return Esito(bool(ok), tr("Bluetooth is on.") if ok else tr("I couldn't turn Bluetooth on."))


@capacita("bluetooth_off", "Turns Bluetooth off.", {})
def bluetooth_off(args):
    bt, a, err = _bt_pronto()
    if err:
        return err
    bt.set_power(False)
    ok = S.attendi(lambda: not (bt.adapter() or {}).get("powered", True), 5)
    return Esito(bool(ok), tr("Bluetooth is off.") if ok else tr("I couldn't turn Bluetooth off."))


@capacita("bluetooth_devices", "Lists Bluetooth devices (connected, paired, nearby).",
          {}, rischio="lettura")
def bluetooth_devices(args):
    bt, a, err = _bt_pronto()
    if err:
        return err
    if not a["powered"]:
        return Esito(True, tr("Bluetooth is off."))
    bt.scan(6)
    dd = bt.devices()
    if not dd:
        return Esito(True, tr("No Bluetooth devices found."), {"dispositivi": []})
    righe = [tr("{name} (connected)").format(name=d["name"]) if d["connected"] else
             tr("{name} (paired)").format(name=d["name"]) if d["paired"] else d["name"]
             for d in dd[:12]]
    return Esito(True, tr("Devices: {list}.").format(list="; ".join(righe)), {"dispositivi": dd})


def _bt_dispositivo(nome):
    bt = _bt()
    n = S.norm(nome)
    dd = bt.devices()
    for d in dd:
        if S.norm(d["name"]) == n or d["mac"].lower() == n:
            return d
    for d in dd:
        if n and n in S.norm(d["name"]):
            return d
    return None


@capacita("bluetooth_connect", "Connects a Bluetooth device (headphones, mouse, ...).",
          {"dispositivo": "device name"}, ["dispositivo"])
def bluetooth_connect(args):
    bt, a, err = _bt_pronto()
    if err:
        return err
    if not a["powered"]:
        bluetooth_on({})
    d = _bt_dispositivo(args.get("dispositivo", ""))
    if d is None:
        bt.scan(8)
        d = _bt_dispositivo(args.get("dispositivo", ""))
    if d is None:
        return Esito(False, tr("I can't find “{name}”: turn it on and put it in pairing mode.").format(
            name=args.get("dispositivo")))
    if d["connected"]:
        return Esito(True, tr("{name} is already connected.").format(name=d["name"]))
    bt.connect(d["mac"])
    ok = S.attendi(lambda: (_bt_dispositivo(d["mac"]) or {}).get("connected"), 10)
    return Esito(bool(ok), (tr("{name} connected.") if ok else
                            tr("I couldn't connect {name}.")).format(name=d["name"]))


@capacita("bluetooth_disconnect", "Disconnects a Bluetooth device.", {"dispositivo": "name"}, ["dispositivo"])
def bluetooth_disconnect(args):
    bt, a, err = _bt_pronto()
    if err:
        return err
    d = _bt_dispositivo(args.get("dispositivo", ""))
    if d is None:
        return Esito(False, tr("I can't find the device “{name}”.").format(name=args.get("dispositivo")))
    if not d["connected"]:
        return Esito(True, tr("{name} isn't connected.").format(name=d["name"]))
    bt.disconnect(d["mac"])
    ok = S.attendi(lambda: not (_bt_dispositivo(d["mac"]) or {}).get("connected", True), 8)
    return Esito(bool(ok), (tr("{name} disconnected.") if ok else
                            tr("I couldn't disconnect {name}.")).format(name=d["name"]))


# ================================================================ DOCK
def _dock():
    import sys
    sys.path.insert(0, "/usr/lib/zeta")
    from system import dock
    return dock


@capacita("dock_add", "Adds an app to the dock.", {"app": "app name"}, ["app"])
def dock_add(args):
    a, err = _app_o_errore(args)
    if err:
        return err
    _dock()                                  # mette /usr/lib/zeta nel percorso
    from system import applicazioni as reg   # stesso registro del menu
    r = reg.trova(a.id)
    if r is None:
        return Esito(False, tr("I can't find the menu entry for {app}.").format(app=a.nome))
    # gia' nel dock: si guarda lo stato, non il testo del messaggio (che
    # ora dipende dalla lingua)
    if reg.nel_dock(r):
        return Esito(True, tr("{app} is already in the dock.").format(app=a.nome))
    ok, msg = reg.aggiungi_dock(r)
    return Esito(ok and reg.nel_dock(r), tr("I added {app} to the dock.").format(app=a.nome) if ok else msg)


@capacita("dock_remove", "Removes an app from the dock (doesn't uninstall it).", {"app": "app name"}, ["app"])
def dock_remove(args):
    nome = (args.get("app") or "").strip()
    a = S.trova_app(nome)
    d = _dock()
    if a is not None:
        from system import applicazioni as reg
        r = reg.trova(a.id)
        if r is not None and reg.nel_dock(r):
            ok, msg = reg.togli_dock(r)
            return Esito(ok, tr("I removed {app} from the dock.").format(app=r.nome) if ok else msg)
    voci = d.load_dock()
    tenute = [v for v in voci if not (S.norm(v.get("name", "")) in {S.norm(nome), S.norm(a.nome) if a else ""}
                                       or (a and v.get("cmd", "").split()[:1] == [a.binario]))]
    if len(tenute) == len(voci):
        return Esito(True, tr("“{app}” isn't in the dock.").format(app=nome))
    d.save_dock(tenute)
    d.apply(tenute)
    return Esito(len(d.load_dock()) == len(tenute),
                 tr("I removed {app} from the dock.").format(app=a.nome if a else nome))


# ================================================================ PROCESSI E STATO
@capacita("system_status", "CPU, memory, disk and battery usage.", {"cosa": "cpu, ram, disk, battery or all"},
          rischio="lettura")
def system_status(args):
    import psutil
    cosa = S.norm(args.get("cosa") or "tutto")
    cosa = {"all": "tutto", "everything": "tutto", "processor": "cpu", "memory": "ram", "disk": "disco",
            "storage": "disco", "space": "disco", "battery": "batteria"}.get(cosa, cosa)
    parti = []
    if cosa in ("tutto", "cpu", "processore"):
        parti.append(tr("CPU at {percent}% (load {load} on {cores} cores)").format(
            percent=int(psutil.cpu_percent(0.4)), load="%.1f" % os.getloadavg()[0], cores=psutil.cpu_count() or 1))
    if cosa in ("tutto", "ram", "memoria"):
        vm = psutil.virtual_memory()
        parti.append(tr("memory {used} GB used of {total} ({percent}%), {free} GB free").format(
            used="%.1f" % ((vm.total - vm.available) / 1e9), total="%.1f" % (vm.total / 1e9),
            percent=int(vm.percent), free="%.1f" % (vm.available / 1e9)))
    if cosa in ("tutto", "disco", "spazio"):
        du = psutil.disk_usage(S.HOME)
        parti.append(tr("disk {free} GB free of {total} ({percent}% used)").format(
            free="%.0f" % (du.free / 1e9), total="%.0f" % (du.total / 1e9), percent=int(du.percent)))
    if cosa in ("tutto", "batteria"):
        b = psutil.sensors_battery() if hasattr(psutil, "sensors_battery") else None
        if b:
            parti.append((tr("battery at {percent}%, charging") if b.power_plugged else
                          tr("battery at {percent}%")).format(percent=int(b.percent)))
        elif cosa == "batteria":
            parti.append(tr("no battery (desktop computer or virtual machine)"))
    t = "; ".join(parti)
    return Esito(True, t[:1].upper() + t[1:] + ".")


@capacita("list_processes", "The programs using the most CPU or memory.", {"per": "cpu or memory"},
          rischio="lettura")
def list_processes(args):
    import psutil
    per_mem = S.norm(args.get("per") or "").startswith(("mem", "ram"))
    procs = list(psutil.process_iter(["name", "memory_info", "cmdline"]))
    for p in procs:
        try:
            p.cpu_percent(None)
        except psutil.Error:
            pass
    time.sleep(0.6)
    somme = {}
    for p in procs:
        try:
            n = S.nome_programma(p.info["cmdline"] or [p.info["name"] or "?"]) or p.info["name"]
            c, r = somme.get(n, (0.0, 0))
            somme[n] = (c + p.cpu_percent(None), r + (p.info["memory_info"].rss if p.info["memory_info"] else 0))
        except psutil.Error:
            continue
    # solo chi consuma davvero: i processi del kernel a zero non dicono nulla
    somme = {n: v for n, v in somme.items() if (v[1] > 20e6 if per_mem else v[0] >= 0.5)}
    if not somme:
        return Esito(True, tr("No program is using the CPU significantly: the computer is idle."))
    ord_ = sorted(somme.items(), key=lambda kv: -(kv[1][1] if per_mem else kv[1][0]))[:6]
    righe = ["%s %s" % (n, ("%.0f MB" % (r / 1e6)) if per_mem else ("%.0f%% CPU" % c)) for n, (c, r) in ord_]
    return Esito(True, (tr("Using the most memory: {list}.") if per_mem else
                        tr("Using the most CPU: {list}.")).format(list=", ".join(righe)))


# ================================================================ SOFTWARE
def _pacchetto(nome):
    """nome di pacchetto plausibile: lettere, cifre e + - . (niente opzioni)"""
    n = S.norm(nome).replace(" ", "-")
    return n if re.fullmatch(r"[a-z0-9][a-z0-9+.\-]{0,80}", n) else None


def _apt_nel_terminale(azione, pkg):
    """apt nel terminale (la password la chiede pkexec, si vede cosa fa);
    alla fine una notifica dice com'e' andata davvero (dpkg).
    I testi arrivano gia' tradotti come argomenti ($3...$8)."""
    if azione == "install":
        testi = [tr("ZETA — Installing {package}").format(package=pkg),
                 tr("Installed: {package}").format(package=pkg), tr("You can open it now."),
                 tr("{package} was not installed").format(package=pkg),
                 tr("The installation failed or was canceled.")]
    else:
        testi = [tr("ZETA — Removing {package}").format(package=pkg),
                 tr("Removed: {package}").format(package=pkg), "",
                 tr("{package} is still installed").format(package=pkg),
                 tr("The removal failed or was canceled.")]
    titolo, ok_t, ok_c, no_t, no_c = testi
    script = r'''
foot -e sh -c 'printf "\033[1;34m%s\033[0m\n\n" "$3"; pkexec apt-get "$1" -y -- "$2"; printf "\n%s" "$4"; read _' _ "$1" "$2" "$3" "$4"
if dpkg-query -W -f='${Status}' "$2" 2>/dev/null | grep -q "install ok installed"; then st=installato; else st=assente; fi
if [ "$1" = install ] && [ "$st" = installato ]; then notify-send -a ZETA -i zeta-ai "$5" "$6";
elif [ "$1" = install ]; then notify-send -a ZETA -i dialog-warning "$7" "$8";
elif [ "$st" = assente ]; then notify-send -a ZETA -i zeta-ai "$5" "$6";
else notify-send -a ZETA -i dialog-warning "$7" "$8"; fi
'''
    S.avvia(["sh", "-c", script, "_", azione, pkg, titolo, tr("Press Enter to close."), ok_t, ok_c, no_t, no_c])


def _pacchetti():
    import sys
    if "/usr/lib/zeta" not in sys.path:
        sys.path.insert(0, "/usr/lib/zeta")
    from system import pacchetti
    return pacchetti


_PROTETTI = {"hyprland", "systemd", "sudo", "network-manager", "zeta", "calamares", "linux-image-amd64",
             "linux-image-arm64", "sddm", "waybar", "python3", "bash", "dbus", "apt", "dpkg"}


def _controlla_installa(args):
    pkg = _pacchetto(args.get("pacchetto", ""))
    if not pkg:
        return Esito(False, tr("“{name}” isn't a valid package name.").format(name=args.get("pacchetto")))
    p = _pacchetti()
    d = p.disponibilita([pkg])[pkg]
    if d["installato"]:
        return Esito(True, tr("{package} is already installed (version {version}).").format(
            package=pkg, version=d["installato"]))
    if not d["candidato"]:
        return Esito(False, tr("{package} can't be installed: {reason}").format(package=pkg, reason=p.perche_manca(pkg)))
    args["_pkg"] = pkg
    return None


def _controlla_rimuovi(args):
    pkg = _pacchetto(args.get("pacchetto", ""))
    if not pkg:
        return Esito(False, tr("“{name}” isn't a valid package name.").format(name=args.get("pacchetto")))
    if not _pacchetti().disponibilita([pkg])[pkg]["installato"]:
        return Esito(True, tr("{package} isn't installed: there's nothing to uninstall.").format(package=pkg))
    if pkg in _PROTETTI:
        return Esito(False, tr("{package} is needed by the system: I won't uninstall it.").format(package=pkg))
    args["_pkg"] = pkg
    return None


@capacita("install_package", "Installs a program from the repositories (asks for the password).",
          {"pacchetto": "package name"}, ["pacchetto"], rischio="conferma", controlla=_controlla_installa,
          anteprima=lambda a: tr("Install the package “{package}” (password required)").format(
              package=a.get("_pkg", a.get("pacchetto", ""))))
def install_package(args):
    err = _controlla_installa(args)
    if err:
        return err
    pkg = args["_pkg"]
    _apt_nel_terminale("install", pkg)
    return Esito(True, tr("Installation of {package} started in the terminal: it will ask for your password, "
                          "and a notification will tell you whether it succeeded.").format(package=pkg),
                 {"in_corso": True})


@capacita("remove_package", "Uninstalls a program (asks for the password).",
          {"pacchetto": "package name"}, ["pacchetto"], rischio="conferma", controlla=_controlla_rimuovi,
          anteprima=lambda a: tr("Uninstall the package “{package}” (password required)").format(
              package=a.get("_pkg", a.get("pacchetto", ""))))
def remove_package(args):
    err = _controlla_rimuovi(args)
    if err:
        return err
    pkg = args["_pkg"]
    _apt_nel_terminale("remove", pkg)
    return Esito(True, tr("Uninstallation of {package} started in the terminal; "
                          "a notification will tell you how it went.").format(package=pkg),
                 {"in_corso": True})


# ================================================================ VARIE
@capacita("current_time", "What time / what day it is.", {}, rischio="lettura")
def current_time(args):
    giorni = (tr("Monday"), tr("Tuesday"), tr("Wednesday"), tr("Thursday"), tr("Friday"), tr("Saturday"),
              tr("Sunday"))
    mesi = (tr("January"), tr("February"), tr("March"), tr("April"), tr("May"), tr("June"), tr("July"),
            tr("August"), tr("September"), tr("October"), tr("November"), tr("December"))
    t = time.localtime()
    return Esito(True, tr("It's {time} on {weekday}, {month} {day}, {year}.").format(
        time="%02d:%02d" % (t.tm_hour, t.tm_min), weekday=giorni[t.tm_wday], day=t.tm_mday,
        month=mesi[t.tm_mon - 1], year=t.tm_year))


@capacita("screenshot", "Saves a screenshot to the Pictures folder.", {})
def screenshot(args):
    base = cartella_di("immagini") or S.HOME
    dest = os.path.join(base, tr("Screenshot {date}.png").format(date=time.strftime("%Y-%m-%d %H-%M-%S")))
    rc, _o, e = S.run(["grim", dest], timeout=15)
    ok = rc == 0 and os.path.isfile(dest) and os.path.getsize(dest) > 0
    return Esito(ok, tr("Screenshot saved to {path}.").format(path=_breve(dest)) if ok else
                 tr("Screenshot failed: {error}").format(error=e),
                 {"percorso": dest})


@capacita("close_all_windows", "Closes all open windows.", {}, rischio="conferma",
          anteprima=lambda a: tr("Close all windows (each app may ask to save)"))
def close_all_windows(args):
    ww = S.finestre()
    for w in ww:
        S.dispatch('hl.dsp.window.close({ window = "%s" })' % _sel(w))
    rimaste = []
    S.attendi(lambda: not S.finestre(), 10)
    rimaste = S.finestre()
    if not rimaste:
        return Esito(True, ntr("I closed {n} window.", "I closed all {n} windows.", len(ww)).format(n=len(ww)))
    return Esito(False, ntr("{n} is still open (it may be asking to save): {list}.",
                            "{n} are still open (they may be asking to save): {list}.", len(rimaste)).format(
        n=len(rimaste), list=", ".join((w.get("class") or "?") for w in rimaste[:4])))


@capacita("open_url", "Opens a website in the browser.", {"url": "address, e.g. www.example.org"}, ["url"])
def open_url(args):
    url = (args.get("url") or "").strip()
    if not url:
        return Esito(False, tr("Which website?"))
    if not re.match(r"^https?://", url):
        url = "https://" + url
    if re.search(r"\s", url) or not re.match(r"^https?://[\w.-]+\.[a-z]{2,}(?:[:/?#]|$)", url, re.I):
        return Esito(False, tr("“{address}” doesn't look like a website address.").format(address=args.get("url")))
    # il browser predefinito scelto dall'utente, non uno qualsiasi
    _rc, pred, _e = S.run(["xdg-mime", "query", "default", "x-scheme-handler/https"], timeout=5)
    a = next((x for x in S.app_installate() if x.id == pred.strip().removesuffix(".desktop")), None) \
        or S.trova_app("browser")
    try:
        S.avvia(["xdg-open", url])
    except OSError as e:
        return Esito(False, tr("I can't open the website: {error}").format(error=e))
    if not a or not S.desktop_attivo():
        return Esito(True, tr("I opened {item}.").format(item=url))
    ok = S.attendi(lambda: S.finestre_di(a), 20)
    return Esito(bool(ok), tr("I opened {address} in the browser.").format(address=url) if ok else
                 tr("The browser didn't open."))
