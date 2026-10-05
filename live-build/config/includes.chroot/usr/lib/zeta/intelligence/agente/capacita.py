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


def _sel(w):
    return "address:%s" % w["address"]


# ================================================================ APP
def _app_o_errore(args):
    nome = (args.get("app") or "").strip()
    if not nome:
        return None, Esito(False, "Quale applicazione?")
    a = S.trova_app(nome)
    if a is None:
        return None, Esito(False, "Non trovo «%s» tra le applicazioni installate." % nome)
    return a, None


def _perche_no():
    """Il motivo piu' comune per cui una finestra non si muove: lo schermo bloccato."""
    rc, _o, _e = S.run(["pgrep", "-x", "hyprlock"], timeout=3)
    return " (lo schermo è bloccato: sbloccalo e riprova)" if rc == 0 else ""


def _porta_avanti(w):
    ws = str((w.get("workspace") or {}).get("name", ""))
    if ws.startswith("special:"):
        import sys
        sys.path.insert(0, "/usr/lib/zeta")
        from system import windows
        return windows.restore(w["address"])
    return S.dispatch('hl.dsp.focus({ window = "%s" })' % _sel(w))


@capacita("open_application", "Apre un'applicazione (o la porta in primo piano se e' gia' aperta).",
          {"app": "nome dell'app, es. firefox, posta, terminale, impostazioni"}, ["app"])
def open_application(args):
    a, err = _app_o_errore(args)
    if err:
        return err
    gia = S.finestre_di(a)
    if gia:
        _porta_avanti(gia[0])
        # si controlla davvero: prima lo diceva anche a schermo bloccato
        if S.attendi(lambda: (S.finestra_attiva() or {}).get("address") == gia[0]["address"], 3):
            return Esito(True, "%s era già aperto: l'ho portato in primo piano." % a.nome)
        return Esito(False, "%s è aperto ma non sono riuscito a portarlo in primo piano%s." % (
            a.nome, _perche_no()))
    if not a.argv or not shutil.which(a.argv[0]):
        return Esito(False, "%s risulta installato ma il suo programma (%s) manca." % (a.nome, a.argv[:1]))
    try:
        S.avvia(a.argv)
    except OSError as e:
        return Esito(False, "Non riesco ad avviare %s: %s" % (a.nome, e))
    if not S.desktop_attivo():
        return Esito(True, "Ho avviato %s." % a.nome)
    # verifica: compare una sua finestra (Firefox, Thunderbird: qualche secondo)
    if S.attendi(lambda: S.finestre_di(a), 25):
        return Esito(True, "%s è aperto." % a.nome)
    if S.processi_di(a):
        return Esito(True, "%s è partito, la finestra sta ancora arrivando." % a.nome)
    return Esito(False, "Ho provato ad aprire %s ma non è partito." % a.nome)


def _chiudi_finestre(a, secondi=10):
    ww = S.finestre_di(a)
    for w in ww:
        S.dispatch('hl.dsp.window.close({ window = "%s" })' % _sel(w))
    return S.attendi(lambda: not S.finestre_di(a), secondi)


@capacita("close_application", "Chiude un'applicazione in modo normale (puo' chiedere di salvare).",
          {"app": "nome dell'app"}, ["app"])
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
            return Esito(True, "%s non è aperto." % a.nome, {"gia": True})
        # senza finestre (es. in background): gli si chiede di uscire (TERM),
        # mai d'autorita' (KILL): quello e' «forza la chiusura», con conferma
        for pid in pids:
            if not windows.protetto(pid):
                windows.force_quit(pid, attesa=4.0, forza=False)
        ok = S.attendi(lambda: not S.processi_di(a), 5)
        if ok:
            return Esito(True, "%s è chiuso." % a.nome)
        return Esito(False, "%s non si è chiuso da solo. Se è bloccato: «forza la chiusura di %s»."
                     % (a.nome, a.nome.lower()))
    if any(windows.protetto(int(w.get("pid") or 0)) for w in ww):
        return Esito(False, "%s fa parte del desktop: non lo chiudo." % a.nome)
    if _chiudi_finestre(a, 10):
        # l'ultima finestra chiusa: il processo esce da se' (Firefox salva la sessione)
        S.attendi(lambda: not S.processi_di(a), 6)
        return Esito(True, "%s è chiuso." % a.nome)
    rimaste = S.finestre_di(a)
    titoli = ", ".join((w.get("title") or "")[:40] for w in rimaste[:2])
    return Esito(False, "%s non si è chiuso: probabilmente chiede qualcosa (%s). "
                 "Se è bloccato: «forza la chiusura di %s»." % (a.nome, titoli, a.nome.lower()),
                 {"aperte": len(rimaste)})


@capacita("force_close_application", "Chiude d'autorita' un'app bloccata, con i suoi sottoprocessi.",
          {"app": "nome dell'app"}, ["app"], rischio="conferma",
          anteprima=lambda a: "Chiudere d'autorità %s (il lavoro non salvato va perso)" % a.get("app", ""))
def force_close_application(args):
    a, err = _app_o_errore(args)
    if err:
        return err
    import sys
    sys.path.insert(0, "/usr/lib/zeta")
    from system import windows
    pids = {int(w["pid"]) for w in S.finestre_di(a) if w.get("pid")} | set(S.processi_di(a))
    if not pids:
        return Esito(True, "%s non è aperto." % a.nome)
    for pid in pids:
        if windows.protetto(pid):
            return Esito(False, "%s fa parte del desktop: non lo chiudo." % a.nome)
        windows.force_quit(pid, attesa=3.0)
    ok = S.attendi(lambda: not S.processi_di(a) and not S.finestre_di(a), 5)
    return Esito(ok, ("%s è stato chiuso d'autorità." if ok else "%s non si chiude nemmeno così.") % a.nome)


@capacita("restart_application", "Chiude e riapre un'applicazione.", {"app": "nome dell'app"}, ["app"])
def restart_application(args):
    a, err = _app_o_errore(args)
    if err:
        return err
    if S.finestre_di(a) or S.processi_di(a):
        c = close_application({"app": a.id})
        if not c.ok:
            return Esito(False, "Non l'ho riavviato: %s" % c.messaggio)
        S.attendi(lambda: not S.processi_di(a), 5)
    o = open_application({"app": a.id})
    return Esito(o.ok, ("%s è stato riavviato." % a.nome) if o.ok else o.messaggio)


# ================================================================ FINESTRE
def _finestra_bersaglio(args):
    """La finestra dell'app indicata, oppure quella attiva."""
    if (args.get("app") or "").strip():
        a, err = _app_o_errore(args)
        if err:
            return None, None, err
        ww = S.finestre_di(a)
        if not ww:
            return a, None, Esito(False, "%s non è aperto." % a.nome)
        return a, ww[0], None
    w = S.finestra_attiva()
    if not w:
        return None, None, Esito(False, "Non c'è nessuna finestra attiva.")
    return S.app_di_finestra(w), w, None


def _nome(a, w):
    return a.nome if a else (w.get("class") or "la finestra")


@capacita("focus_application", "Porta in primo piano un'app aperta (passa a quell'app).",
          {"app": "nome dell'app"}, ["app"])
def focus_application(args):
    a, w, err = _finestra_bersaglio(args)
    if err:
        return err
    _porta_avanti(w)
    ok = S.attendi(lambda: (S.finestra_attiva() or {}).get("address") == w["address"], 3)
    return Esito(ok, ("Ora sei su %s." % _nome(a, w)) if ok else
                 ("Non sono riuscito a passare a %s%s." % (_nome(a, w), _perche_no())))


@capacita("minimize_window", "Riduce a icona un'app (o la finestra attiva).", {"app": "nome dell'app (facoltativo)"})
def minimize_window(args):
    a, w, err = _finestra_bersaglio(args)
    if err:
        return err
    # come il pulsante della barra del titolo: foto per la barra e animazione
    S.run(["zeta-riduci", "riduci", w["address"]], timeout=10)
    ok = S.attendi(lambda: any(x["address"] == w["address"] and
                               str(x["workspace"]["name"]).startswith("special:") for x in S.finestre()), 3)
    return Esito(ok, ("%s è ridotto a icona." % _nome(a, w)) if ok else
                 ("Non sono riuscito a ridurre %s%s." % (_nome(a, w), _perche_no())))


def _stato_schermo(w_addr):
    for x in S.finestre():
        if x["address"] == w_addr:
            return x.get("fullscreen", 0)
    return None


@capacita("maximize_window", "Ingrandisce (o riporta normale) un'app o la finestra attiva.",
          {"app": "nome dell'app (facoltativo)"})
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
        return Esito(False, "Non sono riuscito a ingrandire %s." % _nome(a, w))
    return Esito(True, ("%s è ingrandito." if ora else "%s è tornato alla dimensione normale.") % _nome(a, w))


@capacita("fullscreen_window", "Mette a schermo intero (o toglie) un'app o la finestra attiva.",
          {"app": "nome dell'app (facoltativo)"})
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
        return Esito(False, "Non sono riuscito a cambiare lo schermo intero di %s." % _nome(a, w))
    return Esito(True, ("%s è a schermo intero." if ora else "%s non è più a schermo intero.") % _nome(a, w))


@capacita("close_window", "Chiude la finestra attiva (non tutta l'app).", {})
def close_window(args):
    w = S.finestra_attiva()
    if not w:
        return Esito(False, "Non c'è nessuna finestra attiva.")
    a = S.app_di_finestra(w)
    S.dispatch('hl.dsp.window.close({ window = "%s" })' % _sel(w))
    ok = S.attendi(lambda: all(x["address"] != w["address"] for x in S.finestre()), 6)
    return Esito(ok, ("Ho chiuso la finestra di %s." if ok else
                      "La finestra di %s non si è chiusa: forse chiede di salvare.") % _nome(a, w))


@capacita("list_running_applications", "Elenca le applicazioni aperte adesso.", {}, rischio="lettura")
def list_running_applications(args):
    nomi = []
    for w in S.finestre():
        a = S.app_di_finestra(w)
        n = a.nome if a else (w.get("class") or "?")
        rid = str((w.get("workspace") or {}).get("name", "")).startswith("special:")
        n += " (ridotta a icona)" if rid else ""
        if n not in nomi:
            nomi.append(n)
    if not nomi:
        return Esito(True, "Non c'è nessuna applicazione aperta.", {"app": []})
    return Esito(True, "Aperte: %s." % ", ".join(nomi), {"app": nomi})


@capacita("list_installed_applications", "Elenca le applicazioni installate.", {}, rischio="lettura")
def list_installed_applications(args):
    nomi = sorted({a.nome for a in S.app_installate() if not a.nascosta}, key=str.lower)
    return Esito(True, "%d applicazioni: %s." % (len(nomi), ", ".join(nomi)), {"app": nomi})


@capacita("is_installed", "Dice se un'applicazione o un programma e' installato.",
          {"app": "nome"}, ["app"], rischio="lettura")
def is_installed(args):
    nome = (args.get("app") or "").strip()
    a = S.trova_app(nome)
    if a:
        return Esito(True, "Sì, %s è installato." % a.nome)
    if shutil.which(nome):
        return Esito(True, "Sì, il comando %s è installato (%s)." % (nome, shutil.which(nome)))
    return Esito(True, "No, «%s» non è installato. Si può cercare con «installa %s»." % (nome, nome),
                 {"installato": False})


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
}
_XDG = {}


def cartella_di(luogo: str) -> str | None:
    """«scrivania» -> /home/zeta/Scrivania; un percorso -> lui stesso."""
    if not luogo:
        return None
    l = S.norm(luogo)
    l = re.sub(r"^(la|il|lo|le|i|gli|nella|nel|nei|negli|sulla|sul|in|su|alla|al)\s+", "", l)
    l = l.replace("cartella ", "") if l.startswith("cartella ") and l[9:] in LUOGHI else l
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
        return None, Esito(False, "Non trovo la cartella «%s»." % dove)
    t = cerca_elementi(nome, d, solo_cartelle=solo_cartelle, limite=6)
    if not t:
        return None, Esito(False, "Non trovo «%s»%s." % (nome, (" in %s" % dove) if dove else ""))
    if len(t) > 1:
        elenco = "; ".join(_breve(x) for x in t[:5])
        return None, Esito(False, "Ci sono più «%s»: %s. Quale? Indica anche la cartella." % (nome, elenco),
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


@capacita("create_folder", "Crea una cartella.", {"nome": "nome della nuova cartella",
          "dove": "dove crearla: scrivania, documenti, download... o un percorso (predefinito: cartella personale)"},
          ["nome"])
def create_folder(args):
    nome = (args.get("nome") or "").strip().strip("«»\"'")
    if not nome or "/" in nome:
        return Esito(False, "Il nome della cartella non va bene.")
    base = cartella_di(args.get("dove") or "home")
    if not base:
        return Esito(False, "Non trovo la cartella «%s»." % args.get("dove"))
    dest = os.path.join(base, nome)
    if not _dentro_casa(dest):
        return Esito(False, "Creo cartelle solo nella tua cartella personale o nei dischi esterni.")
    if os.path.isdir(dest):
        return Esito(True, "La cartella %s esiste già." % _breve(dest), {"percorso": dest})
    try:
        os.makedirs(dest)
    except OSError as e:
        return Esito(False, "Non ho potuto creare %s: %s" % (_breve(dest), e.strerror))
    return Esito(os.path.isdir(dest), "Ho creato la cartella %s." % _breve(dest), {"percorso": dest})


@capacita("create_file", "Crea un file di testo, eventualmente con un contenuto.",
          {"nome": "nome del file, es. appunti.txt", "dove": "cartella (predefinito: documenti)",
           "testo": "contenuto (facoltativo)"}, ["nome"])
def create_file(args):
    nome = (args.get("nome") or "").strip().strip("«»\"'")
    if not nome or "/" in nome:
        return Esito(False, "Il nome del file non va bene.")
    base = cartella_di(args.get("dove") or "documenti")
    if not base:
        return Esito(False, "Non trovo la cartella «%s»." % args.get("dove"))
    dest = os.path.join(base, nome)
    if not _dentro_casa(dest):
        return Esito(False, "Creo file solo nella tua cartella personale o nei dischi esterni.")
    if os.path.exists(dest):
        return Esito(False, "Esiste già %s: non lo sovrascrivo." % _breve(dest))
    try:
        with open(dest, "x", encoding="utf-8") as f:
            f.write(args.get("testo") or "")
    except OSError as e:
        return Esito(False, "Non ho potuto creare %s: %s" % (_breve(dest), e.strerror))
    return Esito(os.path.isfile(dest), "Ho creato %s." % _breve(dest), {"percorso": dest})


@capacita("rename_item", "Rinomina un file o una cartella.",
          {"elemento": "file o cartella da rinominare", "nuovo_nome": "il nuovo nome", "dove": "cartella in cui si trova (facoltativo)"},
          ["elemento", "nuovo_nome"])
def rename_item(args):
    src, err = _uno(args.get("elemento", ""), args.get("dove"))
    if err:
        return err
    nuovo = (args.get("nuovo_nome") or "").strip().strip("«»\"'")
    if not nuovo or "/" in nuovo:
        return Esito(False, "Il nuovo nome non va bene.")
    if "." not in nuovo and os.path.isfile(src) and os.path.splitext(src)[1]:
        nuovo += os.path.splitext(src)[1]          # «rinomina nota.txt in appunti» tiene .txt
    dest = os.path.join(os.path.dirname(src), nuovo)
    if not _dentro_casa(src):
        return Esito(False, "Rinomino solo nella tua cartella personale o nei dischi esterni.")
    if os.path.exists(dest):
        return Esito(False, "Esiste già %s." % _breve(dest))
    try:
        os.rename(src, dest)
    except OSError as e:
        return Esito(False, "Non ho potuto rinominare: %s" % e.strerror)
    ok = os.path.exists(dest) and not os.path.exists(src)
    return Esito(ok, "Ho rinominato %s in %s." % (os.path.basename(src), nuovo), {"percorso": dest})


def _destinazione(args):
    d = args.get("destinazione") or args.get("dove_va") or ""
    base = cartella_di(d) if d else None
    if not base:
        return None, Esito(False, "Non trovo la cartella di destinazione «%s»." % d)
    if not _dentro_casa(base):
        return None, Esito(False, "Scrivo solo nella tua cartella personale o nei dischi esterni.")
    return base, None


@capacita("copy_item", "Copia un file o una cartella in un'altra cartella.",
          {"elemento": "file o cartella", "destinazione": "cartella di arrivo (scrivania, documenti, ... o percorso)",
           "dove": "cartella in cui si trova (facoltativo)"}, ["elemento", "destinazione"])
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
        return Esito(False, "Copia non riuscita: %s" % e)
    ok = os.path.exists(dest) and (os.path.isdir(src) or os.path.getsize(dest) == os.path.getsize(src))
    return Esito(ok, "Ho copiato %s in %s." % (os.path.basename(src), _breve(dest)), {"percorso": dest})


@capacita("move_item", "Sposta un file o una cartella in un'altra cartella.",
          {"elemento": "file o cartella", "destinazione": "cartella di arrivo", "dove": "cartella di partenza (facoltativo)"},
          ["elemento", "destinazione"])
def move_item(args):
    src, err = _uno(args.get("elemento", ""), args.get("dove"))
    if err:
        return err
    base, err = _destinazione(args)
    if err:
        return err
    if not _dentro_casa(src):
        return Esito(False, "Sposto solo file della tua cartella personale o dei dischi esterni.")
    if os.path.dirname(os.path.realpath(src)) == os.path.realpath(base):
        return Esito(True, "%s è già in %s." % (os.path.basename(src), _breve(base)))
    dest = _nome_libero(base, os.path.basename(src))
    try:
        shutil.move(src, dest)
    except (OSError, shutil.Error) as e:
        return Esito(False, "Spostamento non riuscito: %s" % e)
    ok = os.path.exists(dest) and not os.path.exists(src)
    return Esito(ok, "Ho spostato %s in %s." % (os.path.basename(src), _breve(base)), {"percorso": dest})


_VAGHI = {"tutto", "tutti", "tutte", "ogni cosa", "qualcosa", "tutto quanto", "tutti i file", "questo", "quello"}


def _controlla_elimina(args):
    """L'oggetto da eliminare: uno solo, esistente, non protetto."""
    if S.norm(args.get("elemento", "")) in _VAGHI:
        return Esito(False, "Non elimino «%s»: dimmi il nome del file o della cartella." % args["elemento"])
    src, err = _uno(args.get("elemento", ""), args.get("dove"))
    if err:
        return err
    if not _dentro_casa(src) or os.path.realpath(src) in (os.path.realpath(S.HOME),) or \
            os.path.realpath(src) in {cartella_di(x) for x in LUOGHI if LUOGHI[x] != "HOME"}:
        return Esito(False, "%s non si elimina da qui." % _breve(src))
    args["_percorso"] = src
    return None


@capacita("delete_item", "Sposta nel cestino un file o una cartella (si puo' ripristinare).",
          {"elemento": "file o cartella", "dove": "cartella in cui si trova (facoltativo)"}, ["elemento"],
          rischio="conferma", controlla=_controlla_elimina,
          anteprima=lambda a: "Mettere nel cestino %s" % (_breve(a["_percorso"]) if a.get("_percorso")
                                                         else "«%s»" % a.get("elemento", "")))
def delete_item(args):
    err = _controlla_elimina(args)
    if err:
        return err
    src = args["_percorso"]
    rc, _o, e = S.run(["gio", "trash", "--", src], timeout=30)
    ok = rc == 0 and not os.path.exists(src)
    return Esito(ok, ("Ho messo %s nel cestino (si può ripristinare)." % os.path.basename(src)) if ok
                 else "Non sono riuscito a eliminarlo: %s" % (e or "errore"))


@capacita("search_files", "Cerca file e cartelle per nome.",
          {"testo": "parte del nome, o *.pdf", "dove": "cartella in cui cercare (predefinito: tutta la cartella personale)"},
          ["testo"], rischio="lettura")
def search_files(args):
    q = (args.get("testo") or "").strip().strip("«»\"'")
    if not q:
        return Esito(False, "Cosa devo cercare?")
    base = cartella_di(args["dove"]) if args.get("dove") else S.HOME
    if not base:
        return Esito(False, "Non trovo la cartella «%s»." % args.get("dove"))
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
        return Esito(True, "Nessun file o cartella con «%s»%s." % (q, "" if base == S.HOME else " in " + _breve(base)),
                     {"trovati": []})
    elenco = "\n".join("  " + _breve(x) for x in trovati[:15])
    altri = " (e altri)" if len(trovati) > 15 else ""
    return Esito(True, "Trovati %d%s:\n%s" % (len(trovati), altri, elenco), {"trovati": trovati})


def _apri_e_verifica(cmd, cosa, secondi=15):
    prima = {w["address"] for w in S.finestre()}
    try:
        S.avvia(cmd)
    except OSError as e:
        return Esito(False, "Non riesco ad aprire %s: %s" % (cosa, e))
    if not S.desktop_attivo():
        return Esito(True, "Ho aperto %s." % cosa)
    nuova = S.attendi(lambda: {w["address"] for w in S.finestre()} - prima, secondi)
    return Esito(bool(nuova), ("Ho aperto %s." % cosa) if nuova else
                 "Ho chiesto di aprire %s ma non è comparsa nessuna finestra." % cosa)


@capacita("open_file", "Apre un file con il programma predefinito.",
          {"elemento": "file da aprire", "dove": "cartella (facoltativo)"}, ["elemento"])
def open_file(args):
    src, err = _uno(args.get("elemento", ""), args.get("dove"))
    if err:
        return err
    if os.path.isdir(src):
        return open_folder({"cartella": src})
    return _apri_e_verifica(["xdg-open", src], os.path.basename(src))


@capacita("open_folder", "Apre una cartella nel gestore file.",
          {"cartella": "scrivania, documenti, download, immagini, musica, video, home, cestino o un percorso/nome"},
          ["cartella"])
def open_folder(args):
    c = (args.get("cartella") or "home").strip()
    if S.norm(c) in ("cestino", "il cestino", "trash"):
        return _apri_e_verifica(["zeta-predefinita", "file", "trash:///"], "il cestino")
    d = cartella_di(c)
    if not d:
        d_, err = _uno(c, solo_cartelle=True)
        if err:
            return err
        d = d_
    return _apri_e_verifica(["zeta-predefinita", "file", d], "la cartella %s" % _breve(d))


@capacita("show_location", "Mostra la cartella in cui si trova un file.",
          {"elemento": "file o cartella"}, ["elemento"])
def show_location(args):
    src, err = _uno(args.get("elemento", ""), args.get("dove"))
    if err:
        return err
    r = _apri_e_verifica(["zeta-predefinita", "file", os.path.dirname(src)], "la cartella che contiene %s" % os.path.basename(src))
    if r.ok:
        r.messaggio = "%s si trova in %s: ho aperto la cartella." % (os.path.basename(src), _breve(os.path.dirname(src)))
    return r


@capacita("download_file", "Scarica un file da internet in una cartella.",
          {"url": "indirizzo http(s)", "dove": "cartella (predefinito: download)"}, ["url"])
def download_file(args):
    import urllib.parse
    import urllib.request
    url = (args.get("url") or "").strip()
    if not re.match(r"^https?://", url):
        return Esito(False, "Serve un indirizzo che cominci con http:// o https://.")
    base = cartella_di(args.get("dove") or "download")
    if not base or not _dentro_casa(base):
        return Esito(False, "Cartella di destinazione non valida.")
    nome = os.path.basename(urllib.parse.unquote(urllib.parse.urlparse(url).path)) or "scaricato"
    dest = _nome_libero(base, nome)
    tmp = dest + ".parziale"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ZETA-RAYS/1.7"})
        with urllib.request.urlopen(req, timeout=30) as r, open(tmp, "wb") as f:
            cd = r.headers.get("Content-Disposition", "")
            m = re.search(r'filename="?([^";]+)"?', cd)
            if m and nome == "scaricato":
                dest = _nome_libero(base, os.path.basename(m.group(1)))
            shutil.copyfileobj(r, f, 1 << 20)
        os.replace(tmp, dest)
    except Exception as e:  # noqa: BLE001 - rete, disco, indirizzo: si dice cosa e' successo
        try:
            os.unlink(tmp)
        except OSError:
            pass
        return Esito(False, "Download non riuscito: %s" % e)
    ok = os.path.isfile(dest) and os.path.getsize(dest) > 0
    return Esito(ok, "Ho scaricato %s in %s (%.1f MB)." % (os.path.basename(dest), _breve(base),
                                                          os.path.getsize(dest) / 1e6), {"percorso": dest})


# ================================================================ SISTEMA
PAGINE = {"aspetto": "aspetto", "tema": "aspetto", "colori": "aspetto", "sfondo": "aspetto",
          "dock": "dock", "barra": "dock", "schermo": "schermo", "blocco": "schermo", "display": "schermo",
          "luminosita": "schermo", "monitor": "schermo",
          "notifiche": "notifiche", "rete": "rete", "wifi": "rete", "wi-fi": "rete", "internet": "rete",
          "bluetooth": "bluetooth", "audio": "audio", "suono": "audio", "volume": "audio",
          "stampanti": "stampanti", "stampante": "stampanti", "stampa": "stampanti",
          "ai": "ai", "intelligenza": "ai", "intelligenza artificiale": "ai", "zeta": "ai",
          "informazioni": "info", "info": "info", "sistema": "info",
          "app predefinite": "predefinite", "applicazioni predefinite": "predefinite", "predefinite": "predefinite"}
APP_IMPOSTAZIONI = {"sicurezza": "zeta-sicurezza", "firewall": "zeta-sicurezza",
                    "pacchetti": "synaptic"}


@capacita("open_settings", "Apre le Impostazioni, anche su una pagina (aspetto, dock, schermo, notifiche, "
          "rete, bluetooth, audio, stampanti, ai, informazioni, app predefinite).", {"pagina": "facoltativa"})
def open_settings(args):
    p = S.norm(args.get("pagina") or "")
    p = re.sub(r"^(di |del |della |dello |dei |delle |per |su |sul |sulla )", "", p)
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
                r.messaggio += " Le sue impostazioni sono nel suo menu."
            return r
        return Esito(False, "Non conosco la pagina «%s» delle Impostazioni." % p)
    r = _apri_e_verifica(["zeta-impostazioni"] + ([pagina] if pagina else []),
                         "le Impostazioni" + (" › %s" % pagina if pagina else ""))
    return r


def _volume():
    rc, out, _ = S.run(["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"], timeout=4)
    if rc != 0:
        return None, None
    m = re.search(r"Volume:\s*([\d.]+)", out)
    return (round(float(m.group(1)) * 100) if m else None), ("MUTED" in out)


@capacita("set_volume", "Imposta il volume (0-100), lo alza/abbassa di un passo, o lo silenzia.",
          {"livello": "0-100 (facoltativo)", "variazione": "+N o -N (facoltativo)",
           "muto": "true per silenziare, false per riattivare (facoltativo)"})
def set_volume(args):
    vol, muto = _volume()
    if vol is None:
        return Esito(False, "Non trovo l'uscita audio.")
    if "muto" in args and args["muto"] is not None:
        voglio = bool(args["muto"]) if not isinstance(args["muto"], str) else args["muto"].lower() in ("true", "si", "1")
        S.run(["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "1" if voglio else "0"])
        _, m2 = _volume()
        S.run(["pkill", "-RTMIN+11", "-x", "waybar"])
        return Esito(m2 == voglio, "Audio %s." % ("silenziato" if voglio else "riattivato"))
    if args.get("livello") is not None:
        try:
            obiettivo = int(float(str(args["livello"]).rstrip("%")))
        except ValueError:
            return Esito(False, "Livello del volume non valido.")
    elif args.get("variazione") is not None:
        try:
            obiettivo = vol + int(float(str(args["variazione"]).rstrip("%")))
        except ValueError:
            return Esito(False, "Variazione non valida.")
    else:
        return Esito(True, "Il volume è al %d%%%s." % (vol, " (silenziato)" if muto else ""), {"volume": vol})
    obiettivo = max(0, min(100, obiettivo))
    S.run(["zeta-volume", "imposta", str(obiettivo)])
    if muto and obiettivo > 0:
        S.run(["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "0"])
    ora, _ = _volume()
    return Esito(ora is not None and abs(ora - obiettivo) <= 1, "Volume al %d%%." % (ora or 0), {"volume": ora})


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


@capacita("set_brightness", "Imposta la luminosità dello schermo (0-100) o la cambia di un passo.",
          {"livello": "0-100 (facoltativo)", "variazione": "+N o -N (facoltativo)"})
def set_brightness(args):
    dev, ora = _retroilluminazione()
    if dev is None:
        return Esito(False, "Questo schermo non ha una luminosità regolabile dal computer "
                            "(succede con i monitor esterni e le macchine virtuali): usa i tasti del monitor.")
    if args.get("livello") is not None:
        obiettivo = int(float(str(args["livello"]).rstrip("%")))
    elif args.get("variazione") is not None:
        obiettivo = ora + int(float(str(args["variazione"]).rstrip("%")))
    else:
        return Esito(True, "La luminosità è al %d%%." % ora, {"luminosita": ora})
    obiettivo = max(1, min(100, obiettivo))
    rc, _o, e = S.run(["brightnessctl", "-d", dev, "set", "%d%%" % obiettivo], timeout=5)
    _d, dopo = _retroilluminazione()
    ok = rc == 0 and dopo is not None and abs(dopo - obiettivo) <= 2
    return Esito(ok, ("Luminosità al %d%%." % dopo) if ok else "Non ho potuto cambiare la luminosità: %s" % (e or "errore"))


def _power():
    import sys
    sys.path.insert(0, "/usr/lib/zeta")
    from system import power
    return power


@capacita("lock_screen", "Blocca lo schermo.", {})
def lock_screen(args):
    _power().lock()
    ok = S.attendi(lambda: S.run(["pgrep", "-x", "hyprlock"])[0] == 0, 4)
    return Esito(ok, "Schermo bloccato." if ok else "Non sono riuscito a bloccare lo schermo.")


@capacita("suspend_system", "Mette il computer in sospensione (standby).", {})
def suspend_system(args):
    p = _power()
    p.suspend()
    return Esito(True, "Metto il computer in sospensione." if p.can_suspend() else
                 "Qui la sospensione non è sicura: ho bloccato lo schermo e lo spengo.")


@capacita("logout", "Esce dalla sessione (chiude tutte le app).", {}, rischio="conferma",
          anteprima=lambda a: "Uscire dalla sessione: tutte le app vengono chiuse")
def logout(args):
    ok = S.dispatch("hl.dsp.exit()")          # risposta «ok» di Hyprland
    return Esito(ok, "Esco dalla sessione." if ok else "Hyprland non ha accettato l'uscita dalla sessione.")


@capacita("restart_system", "Riavvia il computer.", {}, rischio="conferma",
          anteprima=lambda a: "Riavviare il computer: le app aperte vengono chiuse")
def restart_system(args):
    return _energia("reboot", "Il computer si sta riavviando.")


@capacita("shutdown_system", "Spegne il computer.", {}, rischio="conferma",
          anteprima=lambda a: "Spegnere il computer: le app aperte vengono chiuse")
def shutdown_system(args):
    return _energia("poweroff", "Il computer si sta spegnendo.")


def _energia(azione, messaggio):
    """Riavvio e spegnimento: si aspetta la risposta di systemd. Prima si
    lanciava il comando e si diceva «Riavvio il computer» anche quando il
    sistema rifiutava (visto: da una sessione non locale il riavvio non
    partiva e ZETA diceva di averlo fatto)."""
    rc, out, err = S.run(["systemctl", azione, "--no-ask-password"], timeout=20)
    if rc == 0:
        return Esito(True, messaggio)
    motivo = (err or out or "").strip().splitlines()
    motivo = motivo[-1][:160] if motivo else "motivo sconosciuto"
    if "authentication" in motivo.lower() or "autenticazione" in motivo.lower():
        motivo = "serve essere nella sessione locale del computer (o la password dell'amministratore)"
    return Esito(False, "Il sistema non ha accettato: %s." % motivo)


@capacita("set_theme", "Tema chiaro o scuro.", {"tema": "chiaro o scuro"}, ["tema"])
def set_theme(args):
    t = "chiaro" if S.norm(args.get("tema", "")).startswith("chiar") else "scuro"
    S.run(["zeta-aspetto", "set", "tema", t], timeout=40)      # applica anche
    try:
        ora = open(os.path.join(S.HOME, ".config/zeta/tema")).read().strip()
    except OSError:
        ora = ""
    return Esito(ora == t, "Tema %s attivato." % t if ora == t else "Il tema non è cambiato.")


@capacita("set_wallpaper", "Cambia lo sfondo con un'immagine, con uno degli sfondi di ZETA RAYS "
          "(Onde blu, Circuiti verdi, Onde rosse, Terminale, Logo blu/verde/rosso/bianco) "
          "o torna a quello di ZETA RAYS.",
          {"immagine": "file immagine, nome di uno sfondo di ZETA RAYS, oppure «predefinito»"}, ["immagine"])
def set_wallpaper(args):
    nome = (args.get("immagine") or "").strip()
    if S.norm(nome) in ("predefinito", "originale", "zeta", "zeta rays", "di zeta rays"):
        rc, _o, e = S.run(["zeta-sfondo", "reset"], timeout=30)
        return Esito(rc == 0, "Rimesso lo sfondo di ZETA RAYS." if rc == 0 else "Non riuscito: %s" % e)
    # prima gli sfondi di ZETA RAYS per nome («onde rosse»), poi i file dell'utente
    from system import sfondi
    ufficiale = sfondi.cerca(nome)
    if ufficiale:
        rc, _o, e = S.run(["zeta-sfondo", "set", ufficiale], timeout=30)
        # verifica: zeta-sfondo deve rispondere con lo sfondo scelto
        _r, ora, _e = S.run(["zeta-sfondo", "get"])
        ok = rc == 0 and ora.split("\n")[0].strip() == ufficiale
        return Esito(ok, ("Sfondo cambiato: %s." % sfondi.nome_di(ufficiale)) if ok
                     else "Non riuscito: %s" % (e or "lo sfondo non è cambiato"))
    src, err = _uno(nome, args.get("dove"))
    if err:
        return err
    rc, _o, e = S.run(["zeta-sfondo", "set", src], timeout=30)
    return Esito(rc == 0, ("Sfondo cambiato: %s." % os.path.basename(src)) if rc == 0 else "Non riuscito: %s" % e)


# ================================================================ RETE
def _wifi_radio():
    rc, out, _ = S.run(["nmcli", "radio", "wifi"], timeout=5)
    return out.strip() == "enabled" if rc == 0 else None


def _wifi_dev():
    rc, out, _ = S.run(["nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device"], timeout=5)
    for r in out.splitlines():
        p = r.split(":")
        if len(p) >= 4 and p[1] == "wifi":
            return {"device": p[0], "state": p[2], "connection": p[3]}
    return None


@capacita("wifi_on", "Accende il Wi-Fi.", {})
def wifi_on(args):
    if _wifi_dev() is None:
        return Esito(False, "Questo computer non ha una scheda Wi-Fi.")
    S.run(["nmcli", "radio", "wifi", "on"], timeout=10)
    ok = S.attendi(lambda: _wifi_radio() is True, 5)
    return Esito(ok, "Wi-Fi acceso." if ok else "Non sono riuscito ad accendere il Wi-Fi.")


@capacita("wifi_off", "Spegne il Wi-Fi.", {})
def wifi_off(args):
    if _wifi_dev() is None:
        return Esito(False, "Questo computer non ha una scheda Wi-Fi.")
    S.run(["nmcli", "radio", "wifi", "off"], timeout=10)
    ok = S.attendi(lambda: _wifi_radio() is False, 5)
    return Esito(ok, "Wi-Fi spento." if ok else "Non sono riuscito a spegnere il Wi-Fi.")


@capacita("wifi_list", "Elenca le reti Wi-Fi vicine.", {}, rischio="lettura")
def wifi_list(args):
    if _wifi_dev() is None:
        return Esito(False, "Questo computer non ha una scheda Wi-Fi.")
    if _wifi_radio() is False:
        return Esito(False, "Il Wi-Fi è spento: «accendi il Wi-Fi».")
    rc, out, _ = S.run(["nmcli", "-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY", "device", "wifi", "list",
                        "--rescan", "auto"], timeout=20)
    reti = []
    for r in out.splitlines():
        p = r.replace("\\:", "\x00").split(":")
        if len(p) >= 4 and p[1]:
            reti.append(("● " if p[0] == "*" else "") + "%s (%s%%%s)" % (p[1].replace("\x00", ":"), p[2],
                                                                        ", aperta" if not p[3] else ""))
    if not reti:
        return Esito(True, "Nessuna rete Wi-Fi trovata qui intorno.", {"reti": []})
    return Esito(True, "Reti Wi-Fi: %s." % "; ".join(dict.fromkeys(reti)), {"reti": reti})


@capacita("wifi_connect", "Si collega a una rete Wi-Fi (con la password, se serve).",
          {"rete": "nome della rete (SSID)", "password": "facoltativa"}, ["rete"])
def wifi_connect(args):
    import sys
    sys.path.insert(0, "/usr/lib/zeta")
    from system import network
    ssid = (args.get("rete") or "").strip().strip("«»\"'")
    if _wifi_dev() is None:
        return Esito(False, "Questo computer non ha una scheda Wi-Fi.")
    if _wifi_radio() is False:
        wifi_on({})
    ok, msg, motivo = network.connect_wifi_esito(ssid, args.get("password") or None)
    if ok:
        return Esito(True, "Connesso a «%s»." % ssid)
    if motivo == "password":
        return Esito(False, "La password di «%s» non è giusta (o manca): dimmela di nuovo, "
                            "es. «connettiti a %s con password …»." % (ssid, ssid), {"motivo": "password"})
    if motivo == "non trovata":
        return Esito(False, "Non vedo nessuna rete chiamata «%s» qui intorno." % ssid, {"motivo": motivo})
    return Esito(False, "Non mi sono collegato a «%s»: %s" % (ssid, msg), {"motivo": motivo})


@capacita("wifi_disconnect", "Si scollega dalla rete Wi-Fi attuale (il Wi-Fi resta acceso).", {})
def wifi_disconnect(args):
    d = _wifi_dev()
    if d is None:
        return Esito(False, "Questo computer non ha una scheda Wi-Fi.")
    if not d["state"].startswith("connected"):
        return Esito(True, "Il Wi-Fi non è collegato a nessuna rete.")
    S.run(["nmcli", "device", "disconnect", d["device"]], timeout=15)
    ok = S.attendi(lambda: not (_wifi_dev() or {}).get("state", "").startswith("connected"), 6)
    return Esito(ok, ("Scollegato da «%s»." % d["connection"]) if ok else "Non sono riuscito a scollegarmi.")


@capacita("network_status", "Stato della rete: connessione, Wi-Fi, indirizzi IP.", {}, rischio="lettura")
def network_status(args):
    import sys
    sys.path.insert(0, "/usr/lib/zeta")
    from system import network
    rc, out, _ = S.run(["nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device"], timeout=5)
    righe = []
    for r in out.splitlines():
        p = r.replace("\\:", "\x00").split(":")
        p = [x.replace("\x00", ":") for x in p]
        if len(p) < 4 or p[1] not in ("ethernet", "wifi") or p[2] == "unmanaged":
            continue                 # le schede non gestite (es. un punto di accesso) non contano
        tipo = "Wi-Fi" if p[1] == "wifi" else "Cavo"
        if p[2].startswith("connected"):
            _rc2, ip, _ = S.run(["ip", "-4", "-br", "addr", "show", p[0]], timeout=3)
            ind = ip.split()[2].split("/")[0] if len(ip.split()) > 2 else ""
            righe.append("%s: collegato a «%s»%s" % (tipo, network.nice_name(p[3], p[1]),
                                                     (", indirizzo " + ind) if ind else ""))
        else:
            righe.append("%s: %s" % (tipo, {"disconnected": "scollegato", "unavailable": "non disponibile"
                                            }.get(p[2], p[2])))
    radio = _wifi_radio()
    if radio is False:
        righe.append("Wi-Fi spento")
    rc, gw, _ = S.run(["ip", "route", "show", "default"], timeout=3)
    righe.append("Internet: %s" % ("sì, tramite %s" % gw.split()[2] if gw else "nessuna uscita"))
    return Esito(True, ". ".join(righe) + ".")


# ================================================================ APP PREDEFINITE
def _predefinite():
    import sys
    if "/usr/lib/zeta" not in sys.path:
        sys.path.insert(0, "/usr/lib/zeta")
    from system import predefinite
    return predefinite


@capacita("set_default_app", "Imposta l'app predefinita per un ruolo (browser, posta, file, terminale, "
          "editor, video, immagini, pdf).",
          {"ruolo": "browser, posta, file, terminale, editor, video, immagini o pdf", "app": "nome dell'app"},
          ["ruolo", "app"])
def set_default_app(args):
    P = _predefinite()
    r = S.norm(args.get("ruolo", ""))
    ruolo = S.RUOLI.get(r, r)
    if ruolo not in P.CATEGORIE:
        return Esito(False, "Non conosco il ruolo «%s»: posso impostare browser, posta, file, terminale, "
                            "editor, video, immagini o pdf." % args.get("ruolo"))
    # qui il nome indica un'app, non un ruolo: «l'editor di testo» e' l'app
    # che si chiama cosi', non l'editor predefinito di adesso
    a = S.trova_app(args.get("app", ""), ruoli=False)
    if a is None:
        return Esito(False, "Non trovo «%s» tra le applicazioni installate." % args.get("app"))
    candidate = [c[0] for c in P.candidate(ruolo)]
    if a.id + ".desktop" not in candidate:
        return Esito(False, "%s non si può usare per: %s." % (a.nome, P.CATEGORIE[ruolo][0]))
    ok, msg = P.imposta(ruolo, a.id + ".desktop")
    return Esito(ok, msg)


@capacita("list_default_apps", "Quali sono le app predefinite (browser, posta, terminale...).", {},
          rischio="lettura")
def list_default_apps(args):
    from gi.repository import Gio
    P = _predefinite()
    righe = []
    for c in P.ORDINE:
        aid = P.attuale(c)
        info = Gio.DesktopAppInfo.new(aid) if aid else None
        righe.append("%s: %s" % (P.CATEGORIE[c][0], P.nome(aid, info) if info else "nessuna"))
    return Esito(True, "App predefinite — " + "; ".join(righe) + ".")


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
        return bt, None, Esito(False, "Questo computer non ha il Bluetooth (o è disattivato nel BIOS).")
    return bt, a, None


@capacita("bluetooth_on", "Accende il Bluetooth.", {})
def bluetooth_on(args):
    bt, a, err = _bt_pronto()
    if err:
        return err
    bt.set_power(True)
    ok = S.attendi(lambda: (bt.adapter() or {}).get("powered"), 5)
    return Esito(bool(ok), "Bluetooth acceso." if ok else "Non sono riuscito ad accendere il Bluetooth.")


@capacita("bluetooth_off", "Spegne il Bluetooth.", {})
def bluetooth_off(args):
    bt, a, err = _bt_pronto()
    if err:
        return err
    bt.set_power(False)
    ok = S.attendi(lambda: not (bt.adapter() or {}).get("powered", True), 5)
    return Esito(bool(ok), "Bluetooth spento." if ok else "Non sono riuscito a spegnere il Bluetooth.")


@capacita("bluetooth_devices", "Elenca i dispositivi Bluetooth (collegati, associati, vicini).",
          {}, rischio="lettura")
def bluetooth_devices(args):
    bt, a, err = _bt_pronto()
    if err:
        return err
    if not a["powered"]:
        return Esito(True, "Il Bluetooth è spento.")
    bt.scan(6)
    dd = bt.devices()
    if not dd:
        return Esito(True, "Nessun dispositivo Bluetooth trovato.", {"dispositivi": []})
    righe = ["%s%s" % (d["name"], " (collegato)" if d["connected"] else " (associato)" if d["paired"] else "")
             for d in dd[:12]]
    return Esito(True, "Dispositivi: %s." % "; ".join(righe), {"dispositivi": dd})


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


@capacita("bluetooth_connect", "Collega un dispositivo Bluetooth (cuffie, mouse, ...).",
          {"dispositivo": "nome del dispositivo"}, ["dispositivo"])
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
        return Esito(False, "Non trovo «%s»: accendilo e mettilo in modalità di associazione." % args.get("dispositivo"))
    if d["connected"]:
        return Esito(True, "%s è già collegato." % d["name"])
    bt.connect(d["mac"])
    ok = S.attendi(lambda: (_bt_dispositivo(d["mac"]) or {}).get("connected"), 10)
    return Esito(bool(ok), ("%s collegato." if ok else "Non sono riuscito a collegare %s.") % d["name"])


@capacita("bluetooth_disconnect", "Scollega un dispositivo Bluetooth.", {"dispositivo": "nome"}, ["dispositivo"])
def bluetooth_disconnect(args):
    bt, a, err = _bt_pronto()
    if err:
        return err
    d = _bt_dispositivo(args.get("dispositivo", ""))
    if d is None:
        return Esito(False, "Non trovo il dispositivo «%s»." % args.get("dispositivo"))
    if not d["connected"]:
        return Esito(True, "%s non è collegato." % d["name"])
    bt.disconnect(d["mac"])
    ok = S.attendi(lambda: not (_bt_dispositivo(d["mac"]) or {}).get("connected", True), 8)
    return Esito(bool(ok), ("%s scollegato." if ok else "Non sono riuscito a scollegare %s.") % d["name"])


# ================================================================ DOCK
def _dock():
    import sys
    sys.path.insert(0, "/usr/lib/zeta")
    from system import dock
    return dock


@capacita("dock_add", "Aggiunge un'app al dock.", {"app": "nome dell'app"}, ["app"])
def dock_add(args):
    a, err = _app_o_errore(args)
    if err:
        return err
    d = _dock()
    voci = d.load_dock()
    if any(S.norm(v.get("name", "")) == S.norm(a.nome) or v.get("cmd", "").split()[0] == a.binario for v in voci):
        return Esito(True, "%s è già nel dock." % a.nome)
    voci.append({"cmd": " ".join(a.argv), "name": a.nome, "icon": a.icona})
    d.save_dock(voci)
    d.apply(voci)
    ok = any(v.get("name") == a.nome for v in d.load_dock())
    return Esito(ok, "Ho aggiunto %s al dock." % a.nome)


@capacita("dock_remove", "Toglie un'app dal dock (non la disinstalla).", {"app": "nome dell'app"}, ["app"])
def dock_remove(args):
    nome = (args.get("app") or "").strip()
    a = S.trova_app(nome)
    d = _dock()
    voci = d.load_dock()
    tenute = [v for v in voci if not (S.norm(v.get("name", "")) in {S.norm(nome), S.norm(a.nome) if a else ""}
                                       or (a and v.get("cmd", "").split()[:1] == [a.binario]))]
    if len(tenute) == len(voci):
        return Esito(True, "«%s» non è nel dock." % nome)
    d.save_dock(tenute)
    d.apply(tenute)
    return Esito(len(d.load_dock()) == len(tenute), "Ho tolto %s dal dock." % (a.nome if a else nome))


# ================================================================ PROCESSI E STATO
@capacita("system_status", "Uso di CPU, memoria, disco e batteria.", {"cosa": "cpu, ram, disco, batteria o tutto"},
          rischio="lettura")
def system_status(args):
    import psutil
    cosa = S.norm(args.get("cosa") or "tutto")
    parti = []
    if cosa in ("tutto", "cpu", "processore"):
        parti.append("CPU al %d%% (carico %.1f su %d core)" % (psutil.cpu_percent(0.4), os.getloadavg()[0],
                                                               psutil.cpu_count() or 1))
    if cosa in ("tutto", "ram", "memoria"):
        vm = psutil.virtual_memory()
        parti.append("memoria %.1f GB usati su %.1f (%d%%), %.1f GB liberi" %
                     ((vm.total - vm.available) / 1e9, vm.total / 1e9, vm.percent, vm.available / 1e9))
    if cosa in ("tutto", "disco", "spazio"):
        du = psutil.disk_usage(S.HOME)
        parti.append("disco %.0f GB liberi su %.0f (%d%% usato)" % (du.free / 1e9, du.total / 1e9, du.percent))
    if cosa in ("tutto", "batteria"):
        b = psutil.sensors_battery() if hasattr(psutil, "sensors_battery") else None
        if b:
            parti.append("batteria al %d%%%s" % (b.percent, " in carica" if b.power_plugged else ""))
        elif cosa == "batteria":
            parti.append("nessuna batteria (computer fisso o macchina virtuale)")
    t = "; ".join(parti)
    return Esito(True, t[:1].upper() + t[1:] + ".")


@capacita("list_processes", "I programmi che usano piu' CPU o memoria.", {"per": "cpu o memoria"},
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
        return Esito(True, "Nessun programma sta usando la CPU in modo significativo: il computer è a riposo.")
    ord_ = sorted(somme.items(), key=lambda kv: -(kv[1][1] if per_mem else kv[1][0]))[:6]
    righe = ["%s %s" % (n, ("%.0f MB" % (r / 1e6)) if per_mem else ("%.0f%% CPU" % c)) for n, (c, r) in ord_]
    return Esito(True, "Usano più %s: %s." % ("memoria" if per_mem else "CPU", ", ".join(righe)))


# ================================================================ SOFTWARE
def _pacchetto(nome):
    """nome di pacchetto plausibile: lettere, cifre e + - . (niente opzioni)"""
    n = S.norm(nome).replace(" ", "-")
    return n if re.fullmatch(r"[a-z0-9][a-z0-9+.\-]{0,80}", n) else None


def _apt_nel_terminale(azione, pkg):
    """apt nel terminale (la password la chiede pkexec, si vede cosa fa);
    alla fine una notifica dice com'e' andata davvero (dpkg)."""
    script = r'''
foot -e sh -c 'printf "\033[1;34mZETA — %s di %s\033[0m\n\n" "$1" "$2"; pkexec apt-get "$1" -y -- "$2"; printf "\nPremi Invio per chiudere."; read _' _ "$1" "$2"
if dpkg-query -W -f='${Status}' "$2" 2>/dev/null | grep -q "install ok installed"; then st=installato; else st=assente; fi
if [ "$1" = install ] && [ "$st" = installato ]; then notify-send -a ZETA -i zeta-ai "Installato: $2" "Si può aprire da ora.";
elif [ "$1" = install ]; then notify-send -a ZETA -i dialog-warning "$2 non è stato installato" "L'installazione non è andata a buon fine o è stata annullata.";
elif [ "$st" = assente ]; then notify-send -a ZETA -i zeta-ai "Rimosso: $2" "";
else notify-send -a ZETA -i dialog-warning "$2 è ancora installato" "La rimozione non è andata a buon fine o è stata annullata."; fi
'''
    S.avvia(["sh", "-c", script, "_", azione, pkg])


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
        return Esito(False, "«%s» non è un nome di pacchetto valido." % args.get("pacchetto"))
    p = _pacchetti()
    d = p.disponibilita([pkg])[pkg]
    if d["installato"]:
        return Esito(True, "%s è già installato (versione %s)." % (pkg, d["installato"]))
    if not d["candidato"]:
        return Esito(False, "Non si può installare %s: %s" % (pkg, p.perche_manca(pkg)))
    args["_pkg"] = pkg
    return None


def _controlla_rimuovi(args):
    pkg = _pacchetto(args.get("pacchetto", ""))
    if not pkg:
        return Esito(False, "«%s» non è un nome di pacchetto valido." % args.get("pacchetto"))
    if not _pacchetti().disponibilita([pkg])[pkg]["installato"]:
        return Esito(True, "%s non è installato: non c'è niente da disinstallare." % pkg)
    if pkg in _PROTETTI:
        return Esito(False, "%s serve al sistema: non lo disinstallo." % pkg)
    args["_pkg"] = pkg
    return None


@capacita("install_package", "Installa un programma dai repository (chiede la password).",
          {"pacchetto": "nome del pacchetto"}, ["pacchetto"], rischio="conferma", controlla=_controlla_installa,
          anteprima=lambda a: "Installare il pacchetto «%s» (serve la password)" % a.get("_pkg", a.get("pacchetto", "")))
def install_package(args):
    err = _controlla_installa(args)
    if err:
        return err
    pkg = args["_pkg"]
    _apt_nel_terminale("install", pkg)
    return Esito(True, "Installazione di %s avviata nel terminale: ti chiede la password, "
                       "e alla fine una notifica dice se è andata a buon fine." % pkg, {"in_corso": True})


@capacita("remove_package", "Disinstalla un programma (chiede la password).",
          {"pacchetto": "nome del pacchetto"}, ["pacchetto"], rischio="conferma", controlla=_controlla_rimuovi,
          anteprima=lambda a: "Disinstallare il pacchetto «%s» (serve la password)" % a.get("_pkg", a.get("pacchetto", "")))
def remove_package(args):
    err = _controlla_rimuovi(args)
    if err:
        return err
    pkg = args["_pkg"]
    _apt_nel_terminale("remove", pkg)
    return Esito(True, "Disinstallazione di %s avviata nel terminale; una notifica dirà com'è andata." % pkg,
                 {"in_corso": True})


# ================================================================ VARIE
@capacita("current_time", "Che ore sono / che giorno e'.", {}, rischio="lettura")
def current_time(args):
    giorni = ("lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica")
    mesi = ("gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto",
            "settembre", "ottobre", "novembre", "dicembre")
    t = time.localtime()
    return Esito(True, "Sono le %02d:%02d di %s %d %s %d." % (t.tm_hour, t.tm_min, giorni[t.tm_wday],
                                                            t.tm_mday, mesi[t.tm_mon - 1], t.tm_year))


@capacita("screenshot", "Salva una foto dello schermo nella cartella Immagini.", {})
def screenshot(args):
    base = cartella_di("immagini") or S.HOME
    dest = os.path.join(base, time.strftime("Schermata %Y-%m-%d %H-%M-%S.png"))
    rc, _o, e = S.run(["grim", dest], timeout=15)
    ok = rc == 0 and os.path.isfile(dest) and os.path.getsize(dest) > 0
    return Esito(ok, ("Schermata salvata in %s." % _breve(dest)) if ok else "Schermata non riuscita: %s" % e,
                 {"percorso": dest})


@capacita("close_all_windows", "Chiude tutte le finestre aperte.", {}, rischio="conferma",
          anteprima=lambda a: "Chiudere tutte le finestre (ogni app può chiedere di salvare)")
def close_all_windows(args):
    ww = S.finestre()
    for w in ww:
        S.dispatch('hl.dsp.window.close({ window = "%s" })' % _sel(w))
    rimaste = []
    S.attendi(lambda: not S.finestre(), 10)
    rimaste = S.finestre()
    if not rimaste:
        return Esito(True, "Ho chiuso tutte le %d finestre." % len(ww))
    return Esito(False, "Ne restano %d aperte (forse chiedono di salvare): %s." % (
        len(rimaste), ", ".join((w.get("class") or "?") for w in rimaste[:4])))


@capacita("open_url", "Apre un sito nel browser.", {"url": "indirizzo, es. www.example.org"}, ["url"])
def open_url(args):
    url = (args.get("url") or "").strip()
    if not url:
        return Esito(False, "Quale sito?")
    if not re.match(r"^https?://", url):
        url = "https://" + url
    if re.search(r"\s", url) or not re.match(r"^https?://[\w.-]+\.[a-z]{2,}(?:[:/?#]|$)", url, re.I):
        return Esito(False, "«%s» non sembra l'indirizzo di un sito." % args.get("url"))
    # il browser predefinito scelto dall'utente, non uno qualsiasi
    _rc, pred, _e = S.run(["xdg-mime", "query", "default", "x-scheme-handler/https"], timeout=5)
    a = next((x for x in S.app_installate() if x.id == pred.strip().removesuffix(".desktop")), None) \
        or S.trova_app("browser")
    try:
        S.avvia(["xdg-open", url])
    except OSError as e:
        return Esito(False, "Non riesco ad aprire il sito: %s" % e)
    if not a or not S.desktop_attivo():
        return Esito(True, "Ho aperto %s." % url)
    ok = S.attendi(lambda: S.finestre_di(a), 20)
    return Esito(bool(ok), ("Ho aperto %s nel browser." % url) if ok else "Il browser non si è aperto.")
