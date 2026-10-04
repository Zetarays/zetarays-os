# SPDX-License-Identifier: GPL-3.0-or-later
"""Lo stato vero del computer: finestre, app installate, processi.

Tutto si legge dal sistema (Hyprland, file .desktop, /proc), niente si
indovina. Le funzioni sono veloci (millisecondi) e non bloccano: le chiamate
esterne hanno sempre un tempo massimo.
"""
from __future__ import annotations

import configparser
import glob
import json
import os
import re
import socket
import subprocess
import time
import unicodedata

HOME = os.path.expanduser("~")
RUNTIME = os.environ.get("XDG_RUNTIME_DIR") or "/run/user/%d" % os.getuid()


def norm(testo: str) -> str:
    """minuscole, senza accenti, spazi semplici"""
    t = unicodedata.normalize("NFD", (testo or "").lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", t).strip()


def run(cmd, timeout=10, input_=None):
    """(codice, uscita, errori) di un comando; mai un'eccezione."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, input=input_)
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except FileNotFoundError:
        return 127, "", "%s non installato" % cmd[0]
    except subprocess.TimeoutExpired:
        return 124, "", "tempo scaduto"
    except OSError as e:
        return 1, "", str(e)


def avvia(cmd, cwd=None, env=None):
    """Avvia un programma staccato da chi lo chiama: niente eredita' di
    ingresso/uscita (altrimenti chi aspetta l'uscita resterebbe bloccato
    finche' il programma e' aperto) e nessun legame col processo di ZETA."""
    p = subprocess.Popen(cmd, cwd=cwd or HOME, env=env, start_new_session=True,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
    raccogli(p)
    return p


def raccogli(p):
    """Aspetta in sottofondo che il programma finisca: senza, ogni app aperta
    da ZETA e poi chiusa restava come processo zombie finche' ZETA era aperto."""
    import threading
    threading.Thread(target=p.wait, daemon=True).start()


# ------------------------------------------------------------ Hyprland
def _firma():
    sig = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
    if sig and os.path.exists(os.path.join(RUNTIME, "hypr", sig)):
        return sig
    try:
        d = os.path.join(RUNTIME, "hypr")
        return sorted(os.listdir(d), key=lambda x: os.path.getmtime(os.path.join(d, x)))[-1]
    except (OSError, IndexError):
        return None


def hypr(msg: str, timeout: float = 2.0) -> str | None:
    sig = _firma()
    if not sig:
        return None
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect(os.path.join(RUNTIME, "hypr", sig, ".socket.sock"))
        s.sendall(msg.encode())
        parti = []
        while True:
            b = s.recv(65536)
            if not b:
                break
            parti.append(b)
        return b"".join(parti).decode(errors="replace")
    except OSError:
        return None
    finally:
        s.close()


def hypr_json(what: str):
    r = hypr("j/" + what)
    try:
        return json.loads(r) if r else None
    except ValueError:
        return None


def dispatch(lua: str) -> bool:
    """Dispatcher di Hyprland 0.55 (sintassi Lua). True se accettato."""
    r = hypr("dispatch " + lua)
    return r is not None and r.strip().lower().startswith("ok")


def finestre() -> list[dict]:
    return hypr_json("clients") or []


def finestra_attiva() -> dict | None:
    w = hypr_json("activewindow")
    return w if isinstance(w, dict) and w.get("address") else None


def desktop_attivo() -> bool:
    return _firma() is not None and hypr("j/version") is not None


# ------------------------------------------------------------ processi
def cmdline(pid: int) -> list[str]:
    try:
        with open("/proc/%d/cmdline" % pid, "rb") as f:
            return [x.decode(errors="replace") for x in f.read().split(b"\0") if x]
    except OSError:
        return []


def vivo(pid: int) -> bool:
    try:
        with open("/proc/%d/stat" % pid) as f:
            return f.read().split(") ", 1)[1][0] != "Z"
    except (OSError, IndexError):
        return False


def processi_utente() -> list[tuple[int, list[str]]]:
    uid = os.getuid()
    out = []
    for d in os.listdir("/proc"):
        if not d.isdigit():
            continue
        try:
            if os.stat("/proc/" + d).st_uid != uid:
                continue
        except OSError:
            continue
        c = cmdline(int(d))
        if c:
            out.append((int(d), c))
    return out


def nome_programma(cmd: list[str]) -> str:
    """firefox-esr, foot, zeta-impostazioni (anche per gli script python)."""
    if not cmd:
        return ""
    b = os.path.basename(cmd[0])
    if re.match(r"python3?(\.\d+)?$", b) and len(cmd) > 1:
        for x in cmd[1:]:
            if not x.startswith("-"):
                return os.path.basename(x)
    return b


# ------------------------------------------------------------ app installate
# nell'ordine di precedenza di XDG: una voce dell'utente o di /usr/local
# (es. LocalSend nascosto da ZETA Share) vince su quella del pacchetto
DIRS_DESKTOP = [os.path.join(HOME, ".local/share/applications"),
                "/usr/local/share/applications", "/usr/share/applications"]

# modi comuni di chiamare le app (dopo norm): -> id del .desktop, senza .desktop
SINONIMI = {
    "browser": "firefox-esr", "internet": "firefox-esr", "navigatore": "firefox-esr",
    "web": "firefox-esr", "firefox": "firefox-esr",
    "posta": "thunderbird", "email": "thunderbird", "e-mail": "thunderbird", "mail": "thunderbird",
    "posta elettronica": "thunderbird", "thunderbird": "thunderbird",
    "terminale": "foot", "console": "foot", "shell": "foot", "prompt dei comandi": "foot",
    "file": "thunar", "gestore file": "thunar", "gestore dei file": "thunar", "esplora file": "thunar",
    "esplora risorse": "thunar", "cartelle": "thunar", "thunar": "thunar",
    "editor": "org.gnome.TextEditor", "editor di testo": "org.gnome.TextEditor",
    "blocco note": "org.gnome.TextEditor", "note": "org.gnome.TextEditor",
    "calcolatrice": "org.gnome.Calculator", "calcolatore": "org.gnome.Calculator",
    "impostazioni": "zeta-impostazioni", "preferenze": "zeta-impostazioni", "settings": "zeta-impostazioni",
    "pannello di controllo": "zeta-impostazioni",
    "monitor": "zeta-monitor", "monitor di sistema": "zeta-monitor", "gestione attivita": "zeta-monitor",
    "task manager": "zeta-monitor", "gestione processi": "zeta-monitor",
    "sicurezza": "zeta-sicurezza", "security": "zeta-sicurezza",
    "zeta share": "zeta-share", "share": "zeta-share", "localsend": "zeta-share", "condivisione": "zeta-share",
    "pacchetti": "synaptic", "gestore pacchetti": "synaptic", "synaptic": "synaptic",
    "visualizzatore immagini": "org.gnome.eog", "foto": "org.gnome.eog", "immagini": "org.gnome.eog",
    "pdf": "org.gnome.Evince", "lettore pdf": "org.gnome.Evince", "documenti pdf": "org.gnome.Evince",
    "video": "mpv", "lettore video": "mpv", "musica": "mpv", "lettore multimediale": "mpv",
    "archivi": "org.gnome.FileRoller", "gestore archivi": "org.gnome.FileRoller",
    "zeta": "zeta-core", "zeta core": "zeta-core", "assistente": "zeta-core",
    "testo da immagine": "zeta-testo", "ocr": "zeta-testo", "stampanti": "system-config-printer",
    "cerca": "zeta-cerca", "ricerca": "zeta-cerca",
}

_PLACEHOLDER = re.compile(r"%[a-zA-Z]")


class App:
    __slots__ = ("id", "nome", "argv", "binario", "classi", "nomi", "nascosta", "icona")

    def __repr__(self):
        return "App(%s)" % self.id


def _leggi_desktop(percorso):
    cp = configparser.RawConfigParser(strict=False, interpolation=None)
    cp.optionxform = str
    try:
        cp.read(percorso, encoding="utf-8")
        d = dict(cp["Desktop Entry"])
    except (configparser.Error, KeyError, UnicodeDecodeError, OSError):
        return None
    if d.get("Type") != "Application" or not d.get("Exec"):
        return None
    return d


_CACHE = {"quando": 0.0, "app": []}


def app_installate(ricarica=False) -> list[App]:
    """Le app dai file .desktop (le voci nascoste restano, per riconoscere le
    finestre, ma non si propongono). Rilette al massimo ogni 30 secondi."""
    if not ricarica and _CACHE["app"] and time.monotonic() - _CACHE["quando"] < 30:
        return _CACHE["app"]
    try:
        import sys
        sys.path.insert(0, "/usr/lib/zeta")
        from ui.nomi_app import NOMI
    except ImportError:
        NOMI = {}
    viste, out = set(), []
    for d in DIRS_DESKTOP:
        for f in sorted(glob.glob(os.path.join(d, "*.desktop"))):
            aid = os.path.basename(f)[:-8]
            if aid in viste:
                continue                      # gia' vista in una cartella con precedenza
            info = _leggi_desktop(f)
            if not info:
                continue
            viste.add(aid)
            a = App()
            a.id = aid
            a.nome = NOMI.get(aid + ".desktop") or info.get("Name[it]") or info.get("Name") or aid
            try:
                import shlex
                a.argv = [x for x in shlex.split(_PLACEHOLDER.sub("", info["Exec"])) if x]
            except ValueError:
                a.argv = info["Exec"].split()
            while a.argv and (a.argv[0] == "env" or "=" in a.argv[0]):
                a.argv.pop(0)
            a.binario = os.path.basename(a.argv[0]) if a.argv else ""
            classi = {norm(aid), norm(aid.rsplit(".", 1)[-1]), norm(a.binario)}
            if info.get("StartupWMClass"):
                classi.add(norm(info["StartupWMClass"]))
            a.classi = {c for c in classi if c}
            nomi = {norm(a.nome), norm(info.get("Name", "")), norm(info.get("Name[it]", "")),
                    norm(info.get("GenericName[it]", "")), norm(info.get("GenericName", "")),
                    norm(aid), norm(aid.rsplit(".", 1)[-1]), norm(a.binario)}
            for k in ("Keywords[it]", "Keywords"):
                nomi |= {norm(x) for x in info.get(k, "").split(";") if len(x) > 2}
            a.nomi = {n for n in nomi if n}
            a.nascosta = info.get("NoDisplay", "").lower() == "true" or info.get("Hidden", "").lower() == "true"
            a.icona = info.get("Icon", "")
            out.append(a)
    _CACHE.update(quando=time.monotonic(), app=out)
    return out


# parole generiche che indicano un ruolo, non un'app: valgono per l'app scelta
# in Impostazioni › App predefinite («apri il browser» apre quello scelto)
RUOLI = {
    "browser": "browser", "internet": "browser", "navigatore": "browser", "web": "browser",
    "posta": "posta", "email": "posta", "e-mail": "posta", "mail": "posta", "posta elettronica": "posta",
    "terminale": "terminale", "console": "terminale", "shell": "terminale", "prompt dei comandi": "terminale",
    "file": "file", "gestore file": "file", "gestore dei file": "file", "esplora file": "file",
    "esplora risorse": "file",
    "editor": "editor", "editor di testo": "editor", "blocco note": "editor",
    "lettore video": "video", "lettore multimediale": "video",
    "visualizzatore immagini": "immagini", "lettore pdf": "pdf",
}


def _predefinita(ruolo: str) -> str | None:
    try:
        import sys
        if "/usr/lib/zeta" not in sys.path:
            sys.path.insert(0, "/usr/lib/zeta")
        from system import predefinite
        aid = predefinite.attuale(ruolo)
    except Exception:  # noqa: BLE001 - senza GIO si usano i sinonimi fissi
        return None
    return aid[:-8] if aid and aid.endswith(".desktop") else aid


def trova_app(testo: str, ruoli: bool = True) -> App | None:
    """La app di cui si parla: sinonimi, nome esatto, poi parole del nome."""
    t = norm(testo)
    t = re.sub(r"^(?:(?:il|lo|la|i|gli|le|un|una|uno)\s+|l'\s*)", "", t)
    t = re.sub(r"\s+(app|applicazione|programma)$", "", t)
    t = re.sub(r"^(app|applicazione|programma)\s+", "", t)
    if not t:
        return None
    tutte = app_installate()
    per_id = {a.id: a for a in tutte}
    if ruoli and t in RUOLI:
        scelta = _predefinita(RUOLI[t])
        if scelta in per_id:
            return per_id[scelta]
    if t in SINONIMI and SINONIMI[t] in per_id:
        return per_id[SINONIMI[t]]
    visibili = [a for a in tutte if not a.nascosta]
    # a parita' di eseguibile vince l'app vera, non la sua finestra di
    # impostazioni («mousepad» -> Mousepad, non «Impostazioni di Mousepad»)
    visibili.sort(key=lambda a: ("settings" in a.id.lower() or "preferen" in a.id.lower()))
    for a in visibili:
        if t == norm(a.nome) or t in (norm(a.id), norm(a.id.rsplit(".", 1)[-1])):
            return a
    for a in visibili:
        if t == a.binario.lower():
            return a
    for a in visibili:
        if t in a.nomi:
            return a
    # parola intera dentro un nome («text editor» -> «Editor di testo» no; «firefox esr» si')
    for a in visibili:
        if any(re.search(r"\b%s\b" % re.escape(t), n) for n in a.nomi if len(t) > 3):
            return a
    # una descrizione: «quel programma per le email», «qualcosa per la musica»
    m = re.match(r"^(?:quel|quello|qualcosa|qualche|un|una|il|la|l')?\s*"
                 r"(?:programma|app|applicazione|cosa|coso|roba)?\s*"
                 r"(?:per|della|delle|dei|del|di|da)\s+(?:(?:il|lo|la|l'|i|gli|le|un|una)\s*)?(.+)$", t)
    if m and m.group(1) != t:
        return trova_app(m.group(1), ruoli)
    return None


def app_di_finestra(w: dict) -> App | None:
    classe = norm(w.get("class") or w.get("initialClass") or "")
    prog = nome_programma(cmdline(int(w.get("pid") or 0))) if w.get("pid") else ""
    for a in app_installate():
        if classe and (classe in a.classi or classe.rsplit(".", 1)[-1] in a.classi):
            return a
    for a in app_installate():
        if prog and prog == a.binario:
            return a
    return None


def finestre_di(app: App) -> list[dict]:
    """Le finestre aperte di una app (dalla classe o dal processo)."""
    out = []
    for w in finestre():
        classe = norm(w.get("class") or w.get("initialClass") or "")
        if classe and (classe in app.classi or classe.rsplit(".", 1)[-1] in app.classi):
            out.append(w)
            continue
        if w.get("pid") and nome_programma(cmdline(int(w["pid"]))) == app.binario:
            out.append(w)
    out.sort(key=lambda w: w.get("focusHistoryID", 1 << 30))
    return out


def processi_di(app: App) -> list[int]:
    """Processi dell'utente che sono quella app (per nome del programma)."""
    return [pid for pid, c in processi_utente() if nome_programma(c) == app.binario]


def attendi(condizione, secondi: float, passo: float = 0.2) -> bool:
    fine = time.monotonic() + secondi
    while time.monotonic() < fine:
        try:
            if condizione():
                return True
        except Exception:  # noqa: BLE001 - una verifica che fallisce vale «non ancora»
            pass
        time.sleep(passo)
    try:
        return bool(condizione())
    except Exception:  # noqa: BLE001
        return False
