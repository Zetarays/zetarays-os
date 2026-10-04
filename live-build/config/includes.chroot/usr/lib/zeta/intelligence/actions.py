# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA RAYS Intelligence — motore azioni (allowlist + livelli di permesso).

L'AI non esegue comandi shell arbitrari. Può solo richiedere azioni definite
qui, ognuna con un livello di permesso:

  LIVELLO 0  conversazione
  LIVELLO 1  lettura informazioni di sistema
  LIVELLO 2  azioni utente su app/file
  LIVELLO 3  configurazione di sistema      -> richiede conferma
  LIVELLO 4  azioni amministrative/root      -> richiede conferma

Ogni azione richiesta viene registrata in ~/.local/share/zeta/actions.log.
Le azioni di livello 3 e 4 restituiscono prima un'anteprima; vengono eseguite
solo dopo autorizzazione esplicita.
"""
from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


from .providers.base import ToolSpec


def _popen(*a, **kw):
    """Popen che aspetta la fine del programma in sottofondo (niente zombie
    nel processo di ZETA, che resta aperto)."""
    import threading
    p = subprocess.Popen(*a, **kw)
    threading.Thread(target=p.wait, daemon=True).start()
    return p


LOG_FILE = Path(os.path.expanduser("~/.local/share/zeta/actions.log"))


@dataclass
class ActionResult:
    ok: bool
    output: str
    # se serve conferma, l'azione non è ancora stata eseguita:
    needs_confirmation: bool = False
    preview: str = ""
    impact: str = ""
    level: int = 0


Handler = Callable[[dict], ActionResult]


@dataclass
class Action:
    name: str
    level: int
    description: str
    schema: dict
    handler: Handler


class ActionEngine:
    def __init__(self):
        self.actions: dict[str, Action] = {}
        self._register_builtin()

    # --- registrazione ---
    def register(self, action: Action) -> None:
        self.actions[action.name] = action

    def tool_specs(self) -> list[ToolSpec]:
        return [ToolSpec(name=a.name, description=a.description, schema=a.schema)
                for a in self.actions.values()]

    # --- esecuzione ---
    def run(self, name: str, args: dict, *, authorized: bool = False) -> ActionResult:
        action = self.actions.get(name)
        if action is None:
            return ActionResult(False, "Azione sconosciuta: %s" % name)
        self._log(name, args, action.level)
        # livelli 3/4: prima l'anteprima, poi l'esecuzione autorizzata
        if action.level >= 3 and not authorized:
            preview, impact = self._preview(action, args)
            return ActionResult(True, "", needs_confirmation=True,
                                preview=preview, impact=impact, level=action.level)
        try:
            return action.handler(args)
        except Exception as e:  # noqa: BLE001 — mai far cadere ZETA
            return ActionResult(False, "Errore durante '%s': %s" % (name, e))

    def _preview(self, action: Action, args: dict) -> tuple[str, str]:
        arg_txt = ", ".join("%s=%s" % (k, v) for k, v in args.items())
        preview = "%s(%s)" % (action.name, arg_txt)
        impact = "Livello %d — %s" % (action.level, action.description)
        return preview, impact

    def _log(self, name: str, args: dict, level: int) -> None:
        try:
            LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(LOG_FILE, "a") as f:
                f.write(json.dumps({"t": time.strftime("%Y-%m-%dT%H:%M:%S"),
                                    "action": name, "level": level, "args": args},
                                   ensure_ascii=False) + "\n")
        except OSError:
            pass

    # --- azioni predefinite ---
    def _register_builtin(self) -> None:
        # LIVELLO 1 — sola lettura
        self.register(Action(
            "system_info", 1, "Mostra le informazioni di ZETA RAYS OS (versione, kernel, CPU, memoria).",
            {"type": "object", "properties": {}},
            lambda a: ActionResult(True, _system_info())))
        self.register(Action(
            "process_list", 1, "Elenca i processi che consumano più CPU.",
            {"type": "object", "properties": {}},
            lambda a: ActionResult(True, _run(["sh", "-c",
                "ps -eo pcpu,pmem,comm --sort=-pcpu | head -n 12"]))))
        self.register(Action(
            "disk_usage", 1, "Mostra lo spazio usato e libero sui dischi.",
            {"type": "object", "properties": {}},
            lambda a: ActionResult(True, _run(["df", "-h", "--output=source,size,used,avail,pcent,target"]))))
        self.register(Action(
            "network_status", 1, "Mostra lo stato delle connessioni di rete.",
            {"type": "object", "properties": {}},
            lambda a: ActionResult(True, _run(["sh", "-c",
                "nmcli -t -f DEVICE,TYPE,STATE device 2>/dev/null || ip -brief addr"]))))
        self.register(Action(
            "find_files", 1, "Cerca file nella cartella personale per nome o estensione, anche solo quelli modificati di recente.",
            {"type": "object",
             "properties": {"pattern": {"type": "string", "description": "es. *.pdf oppure *fattura*; più estensioni separate da virgola: *.jpg,*.png"},
                            "oggi": {"type": "boolean", "description": "solo i file modificati oggi"},
                            "giorni": {"type": "integer", "description": "solo i file modificati negli ultimi N giorni"}},
             "required": ["pattern"]},
            _find_files))
        self.register(Action(
            "read_file", 1, "Legge un file di testo nella cartella personale.",
            {"type": "object",
             "properties": {"path": {"type": "string"}},
             "required": ["path"]},
            _read_file))
        self.register(Action(
            "security_status", 1, "Riepilogo dello stato di sicurezza (firewall, aggiornamenti...).",
            {"type": "object", "properties": {}},
            lambda a: ActionResult(True, _security_status())))

        self.register(Action(
            "cpu_usage", 1, "Mostra l'uso attuale della CPU in percentuale.",
            {"type": "object", "properties": {}},
            lambda a: ActionResult(True, _cpu_usage())))
        self.register(Action(
            "memory_usage", 1, "Mostra quanta memoria (RAM) è in uso e quanta è libera.",
            {"type": "object", "properties": {}},
            lambda a: ActionResult(True, _memory_usage())))
        self.register(Action(
            "uptime", 1, "Da quanto tempo è acceso il sistema.",
            {"type": "object", "properties": {}},
            lambda a: ActionResult(True, _run(["sh", "-c", "uptime -p 2>/dev/null || uptime"]))))
        self.register(Action(
            "ip_address", 1, "Mostra gli indirizzi IP locali del sistema.",
            {"type": "object", "properties": {}},
            lambda a: ActionResult(True, _ip_address())))
        self.register(Action(
            "list_applications", 1, "Elenca le applicazioni grafiche installate che si possono aprire.",
            {"type": "object", "properties": {}},
            lambda a: ActionResult(True, _list_applications())))

        # LIVELLO 2 — azioni utente
        self.register(Action(
            "open_application", 2, "Apre un'applicazione installata (nome comune o eseguibile).",
            {"type": "object",
             "properties": {"app": {"type": "string"}},
             "required": ["app"]},
            _open_application))
        self.register(Action(
            "open_folder", 2, "Apre una cartella nel gestore file (es. documenti, download, immagini, o un percorso).",
            {"type": "object",
             "properties": {"name": {"type": "string", "description": "documenti, download, immagini, musica, video, scrivania, home, o un percorso"}},
             "required": ["name"]},
            _open_folder))
        self.register(Action(
            "open_settings", 2, "Apre le Impostazioni di ZETA RAYS, eventualmente su una pagina precisa.",
            {"type": "object",
             "properties": {"page": {"type": "string", "description": "aspetto, rete, bluetooth, audio, ai, sicurezza, pacchetti, informazioni"}}},
            _open_settings))
        self.register(Action(
            "open_system_monitor", 2, "Apre il Monitor di sistema di ZETA RAYS (CPU, rete, processi, firewall...).",
            {"type": "object", "properties": {"section": {"type": "string"}}},
            lambda a: _launch("zeta-monitor", [a["section"]] if a.get("section") else [], "Monitor di sistema")))
        self.register(Action(
            "open_security", 2, "Apre ZETA RAYS Security (firewall, strumenti di sicurezza, stato del sistema).",
            {"type": "object", "properties": {}},
            lambda a: _launch("zeta-sicurezza", [], "ZETA RAYS Security")))
        # Quando nessuna delle azioni qui sopra basta, ZETA non si arrende:
        # scrive il comando che servirebbe, lo mette negli appunti e apre il
        # terminale. A premere Invio sei tu. Cosi ZETA puo aiutare su
        # qualunque cosa senza che un modello da un miliardo di parametri
        # possa eseguire da solo qualcosa di irreversibile.
        # --- energia: livello 3, perche interrompono il lavoro dell utente ---
        self.register(Action(
            "lock_screen", 2, "Blocca lo schermo.",
            {"type": "object", "properties": {}},
            lambda a: _energia("lock", "Blocco lo schermo.")))
        self.register(Action(
            "log_out", 3, "Chiude la sessione e torna alla schermata di accesso.",
            {"type": "object", "properties": {}},
            lambda a: _energia("logout", "Chiudo la sessione.")))
        self.register(Action(
            "suspend", 3, "Sospende il computer.",
            {"type": "object", "properties": {}},
            lambda a: _energia("suspend", "Sospendo il computer.")))
        self.register(Action(
            "reboot", 4, "Riavvia il computer.",
            {"type": "object", "properties": {}},
            lambda a: _semplice(["systemctl", "reboot"], "Riavvio.")))
        self.register(Action(
            "power_off", 4, "Spegne il computer.",
            {"type": "object", "properties": {}},
            lambda a: _semplice(["systemctl", "poweroff"], "Spengo.")))

        # --- suono e schermo ---
        self.register(Action(
            "set_volume", 2, "Imposta il volume (0-100), lo alza o abbassa di un passo, oppure silenzia.",
            {"type": "object",
             "properties": {"level": {"type": "integer", "description": "da 0 a 100"},
                            "step": {"type": "string", "enum": ["su", "giu"],
                                     "description": "alza o abbassa rispetto al volume attuale"},
                            "amount": {"type": "integer", "description": "di quanti punti (predefinito 10)"},
                            "mute": {"type": "boolean"}}},
            _set_volume))
        self.register(Action(
            "set_brightness", 2, "Imposta la luminosità dello schermo (0-100).",
            {"type": "object",
             "properties": {"level": {"type": "integer", "description": "da 0 a 100"}},
             "required": ["level"]},
            _set_brightness))

        # --- file e cartelle ---
        self.register(Action(
            "create_folder", 2, "Crea una cartella nella cartella personale.",
            {"type": "object",
             "properties": {"name": {"type": "string", "description": "nome o percorso della nuova cartella"}},
             "required": ["name"]},
            _create_folder))
        self.register(Action(
            "screen_off", 2, "Spegne lo schermo (non blocca e non spegne il computer).",
            {"type": "object", "properties": {}},
            _screen_off))
        self.register(Action(
            "close_application", 2, "Chiude un programma aperto, indicandolo per nome (es. Firefox).",
            {"type": "object",
             "properties": {"app": {"type": "string", "description": "nome del programma"}},
             "required": ["app"]},
            _close_application))
        self.register(Action(
            "screenshot", 2, "Salva una schermata dello schermo nella cartella Immagini.",
            {"type": "object", "properties": {}},
            _screenshot))
        self.register(Action(
            "search_content", 1,
            "Cerca una parola dentro il contenuto dei file, compreso il testo dei PDF e quello nelle immagini.",
            {"type": "object",
             "properties": {"text": {"type": "string", "description": "parola o frase da cercare"}},
             "required": ["text"]},
            _search_content))
        self.register(Action(
            "rename_file", 3, "Rinomina un file o una cartella.",
            {"type": "object",
             "properties": {"name": {"type": "string", "description": "nome o percorso attuale"},
                            "new_name": {"type": "string", "description": "nome nuovo, senza percorsi"}},
             "required": ["name", "new_name"]},
            _rename_file))
        self.register(Action(
            "move_file", 3, "Sposta un file o una cartella in un'altra cartella.",
            {"type": "object",
             "properties": {"name": {"type": "string", "description": "nome o percorso del file"},
                            "folder": {"type": "string", "description": "cartella di destinazione (documenti, immagini...)"}},
             "required": ["name", "folder"]},
            _move_file))
        self.register(Action(
            "trash_file", 3, "Sposta un file o una cartella nel cestino (recuperabile).",
            {"type": "object",
             "properties": {"name": {"type": "string", "description": "nome o percorso"}},
             "required": ["name"]},
            _trash_file))
        self.register(Action(
            "empty_trash", 3, "Svuota il cestino. Non si torna indietro.",
            {"type": "object", "properties": {}},
            lambda a: _semplice(["sh", "-c", "gio trash --empty"], "Cestino svuotato.")))

        # --- programmi ---
        self.register(Action(
            "install_package", 4, "Installa un programma dagli archivi del sistema.",
            {"type": "object",
             "properties": {"name": {"type": "string"}},
             "required": ["name"]},
            lambda a: _pacchetto("install", a)))
        self.register(Action(
            "remove_package", 4, "Rimuove un programma installato.",
            {"type": "object",
             "properties": {"name": {"type": "string"}},
             "required": ["name"]},
            lambda a: _pacchetto("remove", a)))

        # --- rete ---
        self.register(Action(
            "wifi_toggle", 3, "Accende o spegne il Wi-Fi.",
            {"type": "object",
             "properties": {"on": {"type": "boolean"}},
             "required": ["on"]},
            lambda a: _semplice(["nmcli", "radio", "wifi", "on" if a.get("on") else "off"],
                                "Wi-Fi %s." % ("acceso" if a.get("on") else "spento"))))

        # Nessuna azione «esegui un comando qualunque»: c'era (livello 4, con
        # conferma e perfino come amministratore) e va contro una regola di
        # ZETA RAYS: l'AI non ha mai accesso libero al sistema, men che meno
        # da root. Quando nessuna azione basta, ZETA prepara il comando nel
        # terminale e lo lascia decidere a chi sta davanti allo schermo.
        self.register(Action(
            "propose_command", 2,
            "Prepara un comando nel terminale per l utente, senza eseguirlo. "
            "Da usare quando nessuna altra azione copre la richiesta.",
            {"type": "object",
             "properties": {
                 "command": {"type": "string",
                             "description": "il comando, come si scriverebbe nel terminale"},
                 "why": {"type": "string",
                         "description": "a cosa serve, in una riga"}},
             "required": ["command"]},
            _propose_command))
        self.register(Action(
            "open_file", 2, "Apre un file con il programma predefinito (documento, immagine, video, archivio...).",
            {"type": "object",
             "properties": {"name": {"type": "string",
                                     "description": "nome o percorso del file, dentro la cartella personale"}},
             "required": ["name"]},
            _open_file))
        self.register(Action(
            "open_url", 2, "Apre un indirizzo web nel navigatore.",
            {"type": "object",
             "properties": {"url": {"type": "string", "description": "indirizzo http o https"}},
             "required": ["url"]},
            _open_url))
        self.register(Action(
            "set_wallpaper", 3, "Cambia lo sfondo della scrivania, o ripristina quello di ZETA RAYS.",
            {"type": "object",
             "properties": {"name": {"type": "string",
                                     "description": "percorso dell'immagine, oppure «predefinito» per tornare a quello di ZETA RAYS"}}},
            _set_wallpaper))
        self.register(Action(
            "open_terminal", 2, "Apre il terminale.",
            {"type": "object", "properties": {}},
            lambda a: _launch("foot", [], "il terminale")))
        self.register(Action(
            "close_active_window", 2, "Chiude la finestra attiva sul desktop.",
            {"type": "object", "properties": {}},
            lambda a: _close_active_window()))
        self.register(Action(
            "minimize_window", 2, "Riduce a icona la finestra attiva.",
            {"type": "object", "properties": {}},
            lambda a: _minimize_window()))
        self.register(Action(
            "maximize_window", 2, "Ingrandisce (o ripristina) la finestra attiva.",
            {"type": "object", "properties": {}},
            lambda a: _maximize_window()))
        self.register(Action(
            "list_windows", 1, "Elenca le finestre aperte e quelle ridotte a icona.",
            {"type": "object", "properties": {}},
            lambda a: _list_windows()))
        self.register(Action(
            "current_time", 1, "Dice l'ora attuale.",
            {"type": "object", "properties": {}},
            lambda a: _current_time()))
        self.register(Action(
            "current_date", 1, "Dice la data di oggi.",
            {"type": "object", "properties": {}},
            lambda a: _current_date()))
        self.register(Action(
            "battery_status", 1, "Stato della batteria.",
            {"type": "object", "properties": {}},
            lambda a: _battery_status()))
        self.register(Action(
            "volume_status", 1, "Volume attuale dell'audio.",
            {"type": "object", "properties": {}},
            lambda a: _volume_status()))

        # LIVELLO 3 — configurazione (conferma richiesta)
        self.register(Action(
            "set_theme", 3, "Passa al tema chiaro o scuro.",
            {"type": "object",
             "properties": {"tema": {"type": "string", "description": "chiaro o scuro"}},
             "required": ["tema"]},
            _set_theme))
        self.register(Action(
            "set_accent", 3, "Cambia il colore d'accento del sistema (#RRGGBB).",
            {"type": "object",
             "properties": {"color": {"type": "string", "description": "#RRGGBB"}},
             "required": ["color"]},
            _set_accent))


# ------------------------------------------------------------------ helper

def _run(cmd: list[str], timeout: float = 15.0) -> str:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return (p.stdout or p.stderr or "").strip()
    except (subprocess.SubprocessError, FileNotFoundError) as e:
        return "Comando non disponibile (%s)." % e


def _system_info() -> str:
    info = {}
    try:
        with open("/etc/os-release") as f:
            for line in f:
                if "=" in line:
                    k, v = line.strip().split("=", 1)
                    info[k] = v.strip('"')
    except OSError:
        pass
    import platform
    lines = [
        "OS:            %s" % info.get("PRETTY_NAME", "ZETA RAYS OS"),
        "Versione:      %s" % info.get("VERSION_ID", "1.7"),
        "Architettura:  %s" % platform.machine(),
        "Kernel:        Linux %s" % platform.release(),
        "Ambiente:      ZETA RAYS Shell",
    ]
    return "\n".join(lines)


def _security_status() -> str:
    fw = _run(["sh", "-c", "systemctl is-active nftables 2>/dev/null || echo inattivo"])
    return "Firewall: %s" % (fw or "sconosciuto")


def _home() -> Path:
    return Path(os.path.expanduser("~")).resolve()


def _safe_path(raw: str) -> Path | None:
    """Confina un percorso nella cartella personale (niente '..' o percorsi assoluti fuori)."""
    p = (_home() / raw).resolve() if not os.path.isabs(raw) else Path(raw).resolve()
    return p if str(p).startswith(str(_home())) else None


def _find_files(args: dict) -> ActionResult:
    """Cerca nella cartella personale, i più recenti prima.

    Le cartelle nascoste (.cache, .config, .local...) restano fuori: prima
    «cerca i png» restituiva le miniature della cache invece delle foto.
    Il comando si passa come elenco di argomenti, senza shell.
    """
    pattern = (args.get("pattern") or "*").strip() or "*"
    casa = str(_home())
    cmd = ["find", casa, "-maxdepth", "8"]
    if args.get("oggi"):
        cmd.append("-daystart")          # «oggi» = da mezzanotte, non «ultime 24 ore»
    # più estensioni separate da virgola: «*.jpg,*.png» = l'una o l'altra
    nomi = [p.strip() for p in pattern.split(",") if p.strip()] or ["*"]
    cmd += ["-not", "-path", "*/.*", "("]
    for i, nome in enumerate(nomi):
        cmd += (["-o"] if i else []) + ["-iname", nome]
    cmd += [")"]
    if args.get("oggi"):
        cmd += ["-mtime", "0"]
    else:
        try:
            giorni = int(args.get("giorni") or 0)
        except (TypeError, ValueError):
            giorni = 0
        if giorni > 0:
            cmd += ["-mtime", "-%d" % giorni]
    cmd += ["-printf", "%T@\t%y\t%p\n"]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=20).stdout
    except subprocess.TimeoutExpired:
        return ActionResult(False, "La ricerca ci mette troppo: prova con un nome più preciso.")
    righe = []
    for riga in out.splitlines():
        try:
            t, tipo, percorso = riga.split("\t", 2)
            righe.append((float(t), tipo, percorso))
        except ValueError:
            continue
    quando = " modificati oggi" if args.get("oggi") else (
        " modificati negli ultimi %s giorni" % args.get("giorni") if args.get("giorni") else "")
    if not righe:
        return ActionResult(True, "Nessun file «%s»%s nella tua cartella." % (pattern, quando))
    righe.sort(reverse=True)
    elenco = ["~" + p[len(casa):] + ("/" if tipo == "d" else "") for _t, tipo, p in righe[:40]]
    n = len(righe)
    quanti = "Trovato 1 file" if n == 1 else "Trovati %d file" % n
    if quando and n == 1:
        quando = quando.replace("modificati", "modificato")
    testa = ("%s%s:" % (quanti, quando)) if n <= 40 else \
            ("%s%s, ecco i 40 più recenti:" % (quanti, quando))
    return ActionResult(True, testa + "\n" + "\n".join(elenco))


def _read_file(args: dict) -> ActionResult:
    p = _safe_path(args.get("path", ""))
    if p is None or not p.is_file():
        return ActionResult(False, "File non accessibile nella cartella personale.")
    try:
        text = p.read_text(errors="replace")[:8000]
        return ActionResult(True, text)
    except OSError as e:
        return ActionResult(False, "Impossibile leggere: %s" % e)


# nomi comuni -> eseguibile reale
APP_ALIASES = {
    "browser": "firefox-esr", "internet": "firefox-esr", "web": "firefox-esr",
    "firefox": "firefox-esr", "navigatore": "firefox-esr",
    "terminale": "foot", "terminal": "foot", "console": "foot", "shell": "foot",
    "file": "thunar", "files": "thunar", "cartelle": "thunar", "gestore file": "thunar",
    "editor": "gnome-text-editor", "testo": "gnome-text-editor", "blocco note": "gnome-text-editor",
    "impostazioni": "zeta-impostazioni", "settings": "zeta-impostazioni", "preferenze": "zeta-impostazioni",
    "monitor": "zeta-monitor", "monitor di sistema": "zeta-monitor", "sistema": "zeta-monitor",
    "sicurezza": "zeta-sicurezza", "security": "zeta-sicurezza",
    "calcolatrice": "gnome-calculator", "calcolatore": "gnome-calculator",
    "immagini": "eog", "foto": "eog", "documenti pdf": "evince", "pdf": "evince",
    "musica": "mpv", "video": "mpv", "pacchetti": "synaptic-pkexec",
    "core": "zeta-core", "assistente": "zeta-core",
}


def _resolve_app(app: str) -> str | None:
    key = app.strip().lower()
    cand = APP_ALIASES.get(key, app)
    if shutil.which(cand):
        return cand
    # prova anche l'eseguibile scritto così com'è
    return shutil.which(app)


def _launch(cmd: str, extra: list, label: str) -> ActionResult:
    exe = shutil.which(cmd)
    if not exe:
        return ActionResult(False, "%s non è disponibile su questo sistema." % label)
    try:
        _popen([exe] + [str(x) for x in extra], start_new_session=True)
        return ActionResult(True, "Apro %s." % label)
    except OSError as e:
        return ActionResult(False, "Impossibile avviare %s: %s" % (label, e))


def _open_application(args: dict) -> ActionResult:
    app = args.get("app", "")
    exe = _resolve_app(app)
    if not exe:
        return ActionResult(False, "Non trovo un'applicazione chiamata '%s'." % app)
    try:
        _popen([exe], start_new_session=True)
        return ActionResult(True, "Apro %s." % app)
    except OSError as e:
        return ActionResult(False, "Impossibile avviare: %s" % e)


# cartelle comuni -> directory reale (usa xdg-user-dir quando disponibile)
FOLDER_KEYS = {
    "documenti": "DOCUMENTS", "documents": "DOCUMENTS",
    "download": "DOWNLOAD", "scaricati": "DOWNLOAD", "downloads": "DOWNLOAD",
    "immagini": "PICTURES", "foto": "PICTURES", "pictures": "PICTURES",
    "musica": "MUSIC", "music": "MUSIC",
    "video": "VIDEOS", "filmati": "VIDEOS", "videos": "VIDEOS",
    "scrivania": "DESKTOP", "desktop": "DESKTOP",
    "pubblici": "PUBLICSHARE", "modelli": "TEMPLATES",
}


def _xdg_dir(key: str) -> str:
    out = _run(["xdg-user-dir", key], timeout=4)
    if out and os.path.isdir(out):
        return out
    return str(_home())


def _open_folder(args: dict) -> ActionResult:
    name = (args.get("name") or "").strip()
    low = name.lower()
    if low in ("", "home", "personale", "casa", "cartella personale"):
        target = str(_home())
    elif low in ("cestino", "trash"):
        # il cestino non e una cartella qualunque: il gestore file lo apre
        # come luogo speciale, da cui si possono ripristinare i file
        try:
            _popen(["thunar", "trash:///"], start_new_session=True)
            return ActionResult(True, "Apro il cestino.")
        except OSError as e:
            return ActionResult(False, "Impossibile aprire il cestino: %s" % e)
    elif low in FOLDER_KEYS:
        target = _xdg_dir(FOLDER_KEYS[low])
    else:
        p = _safe_path(name)
        target = str(p) if p and p.is_dir() else ""
    if not target or not os.path.isdir(target):
        return ActionResult(False, "Cartella '%s' non trovata." % name)
    fm = shutil.which("thunar") or shutil.which("xdg-open")
    if not fm:
        return ActionResult(False, "Nessun gestore file disponibile.")
    try:
        _popen([fm, target], start_new_session=True)
        return ActionResult(True, "Apro la cartella %s." % os.path.basename(target.rstrip("/")))
    except OSError as e:
        return ActionResult(False, "Impossibile aprire: %s" % e)


def _energia(azione: str, messaggio: str) -> ActionResult:
    """Blocco, sospensione, disconnessione: passano dal modulo power, che sa
    come farlo davvero (hyprlock, hl.dsp.exit, systemctl), invece di un comando
    inventato che non esisterebbe."""
    try:
        import sys
        sys.path.insert(0, "/usr/lib/zeta")
        from system import power
        getattr(power, azione)()
        return ActionResult(True, messaggio)
    except Exception as e:  # noqa: BLE001
        return ActionResult(False, "Non riuscito: %s" % e)


def _semplice(cmd: list, messaggio: str) -> ActionResult:
    """Esegue un comando gia scritto qui dentro (non arriva dal modello)."""
    if not shutil.which(cmd[0]):
        return ActionResult(False, "Comando non disponibile: %s" % cmd[0])
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as e:
        return ActionResult(False, "Non riuscito: %s" % e)
    if r.returncode != 0:
        return ActionResult(False, (r.stderr or "").strip() or "Non riuscito.")
    return ActionResult(True, messaggio)


def _set_volume(args: dict) -> ActionResult:
    # Passa da zeta-volume, lo stesso comando delle scorciatoie e della
    # rotella sulla barra: cosi l'icona del volume si aggiorna subito anche
    # quando e ZETA a cambiarlo, invece di aspettare la lettura periodica.
    if not shutil.which("zeta-volume"):
        return ActionResult(False, "Controllo del volume non disponibile.")
    if args.get("mute") is not None:
        # «muto» e un interruttore: si legge lo stato e si agisce solo se serve
        atteso = bool(args.get("mute"))
        try:
            letto = subprocess.run(["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"],
                                   capture_output=True, text=True, timeout=5).stdout
            gia_muto = "MUTED" in letto
        except Exception:
            gia_muto = not atteso
        if gia_muto != atteso:
            return _semplice(["zeta-volume", "muto"],
                             "Audio %s." % ("silenziato" if atteso else "riattivato"))
        return ActionResult(True, "Audio già %s." % ("silenziato" if atteso else "attivo"))
    if args.get("step") in ("su", "giu"):
        # «alza il volume» e relativo: prima lo portava sempre all'80%,
        # cosi da 95 «alza» lo abbassava.
        try:
            passo = max(1, min(50, int(args.get("amount") or 10)))
        except (TypeError, ValueError):
            passo = 10
        r = _semplice(["zeta-volume", args["step"], str(passo)], "")
        if not r.ok:
            return r
        ora = _volume_attuale()
        verbo = "alzato" if args["step"] == "su" else "abbassato"
        return ActionResult(True, "Volume %s%s." % (verbo, (": ora al %d%%" % ora) if ora is not None else ""))
    try:
        livello = int(args.get("level", -1))
    except (TypeError, ValueError):
        return ActionResult(False, "Livello non valido.")
    if not 0 <= livello <= 100:
        return ActionResult(False, "Il volume va da 0 a 100.")
    return _semplice(["zeta-volume", "imposta", str(livello)],
                     "Volume al %d%%." % livello)


def _volume_attuale():
    """Volume in percentuale (None se non leggibile)."""
    try:
        out = subprocess.run(["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"],
                             capture_output=True, text=True, timeout=5).stdout
        return round(float(out.split()[1]) * 100)
    except (OSError, subprocess.SubprocessError, IndexError, ValueError):
        return None


def _set_brightness(args: dict) -> ActionResult:
    if not shutil.which("brightnessctl"):
        return ActionResult(False, "Questo schermo non permette di regolare la luminosità.")
    try:
        livello = int(args.get("level", -1))
    except (TypeError, ValueError):
        return ActionResult(False, "Livello non valido.")
    if not 0 <= livello <= 100:
        return ActionResult(False, "La luminosità va da 0 a 100.")
    return _semplice(["brightnessctl", "set", "%d%%" % livello],
                     "Luminosita al %d%%." % livello)


def _create_folder(args: dict) -> ActionResult:
    nome = (args.get("name") or "").strip()
    if not nome:
        return ActionResult(False, "Come si deve chiamare?")
    p = _safe_path(nome)
    if p is None:
        return ActionResult(False, "Posso creare cartelle solo dentro la tua cartella personale.")
    if p.exists():
        return ActionResult(False, "«%s» esiste già." % p.name)
    try:
        p.mkdir(parents=True)
    except OSError as e:
        return ActionResult(False, "Non riuscito: %s" % e)
    return ActionResult(True, "Creata la cartella %s." % p.name)


def _trash_file(args: dict) -> ActionResult:
    nome = (args.get("name") or "").strip()
    p = _safe_path(nome) if nome else None
    if p is None or not p.exists():
        return ActionResult(False, "Non trovo «%s»." % nome)
    if not shutil.which("gio"):
        return ActionResult(False, "Il cestino non è disponibile.")
    return _semplice(["gio", "trash", str(p)],
                     "«%s» è nel cestino: si può ancora recuperare." % p.name)


def _screen_off(args: dict) -> ActionResult:
    """Spegne lo schermo, senza bloccare la sessione.

    Non e' lo spegnimento del computer ne' il blocco: e' il monitor che si
    spegne e si riaccende al primo tasto. Serve a chi si allontana un momento.
    """
    if not shutil.which("hyprctl"):
        return ActionResult(False, "Comando non disponibile fuori dalla scrivania.")
    r = subprocess.run(["hyprctl", "eval", 'hl.dsp.dpms({ action = "off" })'],
                       capture_output=True, text=True, timeout=10)
    if r.returncode != 0:
        return ActionResult(False, (r.stderr or "").strip() or "Non riuscito.")
    return ActionResult(True, "Schermo spento: premi un tasto per riaccenderlo.")


def _rename_file(args: dict) -> ActionResult:
    """Rinomina un file o una cartella, senza spostarlo altrove.

    Il nome nuovo non puo' contenere percorsi: «../..» o «/etc/passwd» come
    nome nuovo sposterebbero il file fuori dalla cartella personale, che e'
    esattamente cio' che _safe_path serve a impedire.
    """
    nome = (args.get("name") or "").strip()
    nuovo = (args.get("new_name") or "").strip()
    if not nome or not nuovo:
        return ActionResult(False, "Servono il nome attuale e quello nuovo.")
    if "/" in nuovo or nuovo in (".", ".."):
        return ActionResult(False, "Il nome nuovo non può contenere percorsi.")
    p = _safe_path(nome)
    if p is None or not p.exists():
        return ActionResult(False, "Non trovo «%s»." % nome)
    dest = p.parent / nuovo
    if dest.exists():
        return ActionResult(False, "«%s» esiste già." % nuovo)
    try:
        p.rename(dest)
    except OSError as e:
        return ActionResult(False, "Non riuscito: %s" % e)
    return ActionResult(True, "«%s» ora si chiama «%s»." % (p.name, nuovo))


def _move_file(args: dict) -> ActionResult:
    """Sposta un file o una cartella dentro un'altra cartella."""
    nome = (args.get("name") or "").strip()
    dove = (args.get("folder") or "").strip()
    if not nome or not dove:
        return ActionResult(False, "Servono il file e la cartella di destinazione.")
    p = _safe_path(nome)
    low = dove.lower()
    if low in FOLDER_KEYS:
        d = Path(_xdg_dir(FOLDER_KEYS[low]))
    elif low in ("", "home", "personale", "casa"):
        d = _home()
    else:
        d = _safe_path(dove)
    if p is None or not p.exists():
        return ActionResult(False, "Non trovo «%s»." % nome)
    if d is None or not d.is_dir():
        return ActionResult(False, "«%s» non è una cartella." % dove)
    dest = d / p.name
    if dest.exists():
        return ActionResult(False, "In «%s» c'è già un «%s»." % (d.name, p.name))
    try:
        shutil.move(str(p), str(dest))
    except (OSError, shutil.Error) as e:
        return ActionResult(False, "Non riuscito: %s" % e)
    return ActionResult(True, "«%s» spostato in %s." % (p.name, d.name))


def _close_application(args: dict) -> ActionResult:
    """Chiude un programma per nome, con garbo: la stessa chiusura dell'agente
    (finestre chiuse con la richiesta normale, verifica che siano sparite, mai
    KILL). Prima qui c'era «pkill -f <nome>», che chiudeva qualunque processo
    con quella parola nella riga di comando e diceva «chiuso» senza guardare."""
    from .agente import capacita
    es = capacita.close_application({"app": (args.get("app") or "").strip()})
    return ActionResult(bool(es.ok), es.messaggio)


def _screenshot(args: dict) -> ActionResult:
    """Salva una schermata nella cartella Immagini."""
    if not shutil.which("grim"):
        return ActionResult(False, "Lo strumento per le schermate non è disponibile.")
    cartella = _home() / "Immagini"
    cartella.mkdir(parents=True, exist_ok=True)
    dest = cartella / ("schermata-%s.png" % time.strftime("%Y%m%d-%H%M%S"))
    # Con un limite di tempo: se il compositore non risponde alla richiesta di
    # copia dello schermo, meglio un messaggio dopo dodici secondi che una
    # finestra ferma per sempre.
    try:
        r = subprocess.run(["grim", str(dest)], capture_output=True, text=True, timeout=12)
    except subprocess.TimeoutExpired:
        return ActionResult(False, "La schermata non è stata prodotta in tempo: "
                                   "il compositore non ha risposto.")
    if r.returncode != 0 or not dest.exists():
        return ActionResult(False, (r.stderr or "").strip() or "Schermata non riuscita.")
    return ActionResult(True, "Schermata salvata in Immagini: %s" % dest.name)


def _search_content(args: dict) -> ActionResult:
    """Cerca una parola DENTRO i file, non solo nei nomi.

    Usa l'indice di zeta-cerca, che legge anche il testo dei PDF e quello
    riconosciuto nelle immagini: e' l'unico modo per trovare «la fattura di
    marzo» quando il file si chiama «scan_0012.pdf».
    """
    testo = (args.get("text") or "").strip()
    if not testo:
        return ActionResult(False, "Che cosa devo cercare?")
    if not shutil.which("zeta-index"):
        return ActionResult(False, "La ricerca nei contenuti non è disponibile.")
    try:
        r = subprocess.run(["zeta-index", "cerca", testo], capture_output=True,
                           text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as e:
        return ActionResult(False, "Ricerca non riuscita: %s" % e)
    righe = [x for x in (r.stdout or "").splitlines() if x.strip()][:15]
    if not righe:
        return ActionResult(True, "Nessun file contiene «%s»." % testo)
    return ActionResult(True, "Trovato in %d file:\n%s" % (len(righe), "\n".join(righe)))


def _pacchetto(azione: str, args: dict) -> ActionResult:
    nome = (args.get("name") or "").strip()
    if not nome or not all(c.isalnum() or c in ".+-" for c in nome):
        return ActionResult(False, "Nome del programma non valido.")
    if not shutil.which("pkexec"):
        return ActionResult(False, "Non posso chiedere i permessi di amministratore.")
    return _semplice(["pkexec", "apt-get", "-y", azione, nome],
                     "%s %s." % ("Installato" if azione == "install" else "Rimosso", nome))


def _propose_command(args: dict) -> ActionResult:
    """Prepara un comando per l utente: negli appunti e con il terminale aperto.

    Non esegue nulla. E il modo di dire «so cosa serve, eccolo» lasciando la
    decisione a chi sta davanti allo schermo.
    """
    comando = (args.get("command") or "").strip()
    if not comando:
        return ActionResult(False, "Nessun comando da proporre.")
    perche = (args.get("why") or "").strip()
    copiato = False
    for strumento in (["wl-copy"], ["xclip", "-selection", "clipboard"]):
        if shutil.which(strumento[0]):
            try:
                subprocess.run(strumento, input=comando, text=True, timeout=5)
                copiato = True
                break
            except (OSError, subprocess.SubprocessError):
                pass
    terminale = shutil.which("foot")
    if terminale:
        try:
            _popen([terminale], start_new_session=True)
        except OSError:
            pass
    testo = "Serve questo comando:\n\n    %s\n" % comando
    if perche:
        testo += "\n(%s)\n" % perche
    testo += ("\nL'ho copiato negli appunti e ho aperto il terminale: incollalo "
              "con Ctrl+Maiusc+V e premi Invio." if copiato
              else "\nHo aperto il terminale: scrivilo lì e premi Invio.")
    return ActionResult(True, testo)


def _open_file(args: dict) -> ActionResult:
    """Apre un file con il programma predefinito del sistema.

    Il percorso resta confinato nella cartella personale, come per le
    cartelle: ZETA non deve poter aprire file di sistema a comando.
    """
    nome = (args.get("name") or "").strip()
    if not nome:
        return ActionResult(False, "Quale file?")
    p = _safe_path(nome)
    if p is None or not p.is_file():
        # non è un percorso: si cerca per nome nella cartella personale
        trovati = _run(["sh", "-c",
                        "find %s -maxdepth 6 -iname %s -type f 2>/dev/null | head -n 5"
                        % (shlex.quote(str(_home())), shlex.quote("*%s*" % nome))])
        righe = [r for r in trovati.splitlines() if r.strip()]
        if not righe:
            return ActionResult(False, "Non trovo nessun file che si chiami «%s»." % nome)
        if len(righe) > 1:
            elenco = "\n".join("  " + os.path.relpath(r, str(_home())) for r in righe)
            return ActionResult(False, "Ce n'è più di uno, dimmi quale:\n%s" % elenco)
        p = Path(righe[0])
    apri = shutil.which("gio") or shutil.which("xdg-open")
    if not apri:
        return ActionResult(False, "Nessun programma per aprire i file.")
    cmd = [apri, "open", str(p)] if os.path.basename(apri) == "gio" else [apri, str(p)]
    try:
        _popen(cmd, start_new_session=True)
        return ActionResult(True, "Apro %s." % p.name)
    except OSError as e:
        return ActionResult(False, "Impossibile aprire: %s" % e)


def _open_url(args: dict) -> ActionResult:
    """Apre un indirizzo nel navigatore.

    Solo http e https: altri schemi (file://, comandi, percorsi locali) non
    passano di qui, altrimenti ZETA diventerebbe un modo per far
    aprire al sistema qualunque cosa.
    """
    url = (args.get("url") or "").strip()
    if not url:
        return ActionResult(False, "Quale indirizzo?")
    if "://" not in url:
        url = "https://" + url
    if not url.lower().startswith(("http://", "https://")):
        return ActionResult(False, "Posso aprire solo indirizzi web (http o https).")
    browser = shutil.which("firefox-esr") or shutil.which("firefox") or shutil.which("xdg-open")
    if not browser:
        return ActionResult(False, "Nessun navigatore disponibile.")
    try:
        _popen([browser, url], start_new_session=True)
        return ActionResult(True, "Apro %s nel navigatore." % url)
    except OSError as e:
        return ActionResult(False, "Impossibile aprire: %s" % e)


def _set_wallpaper(args: dict) -> ActionResult:
    """Cambia lo sfondo, o torna a quello generato da ZETA RAYS."""
    nome = (args.get("name") or "").strip()
    if not shutil.which("zeta-sfondo"):
        return ActionResult(False, "Il comando dello sfondo non è disponibile.")
    if not nome or nome.lower() in ("predefinito", "default", "zeta", "zeta rays", "originale"):
        r = _run(["zeta-sfondo", "reset"])
        return ActionResult(True, "Rimesso lo sfondo di ZETA RAYS." + (" " + r if r else ""))
    from system import sfondi
    ufficiale = sfondi.cerca(nome)
    if ufficiale:
        _run(["zeta-sfondo", "set", ufficiale])
        # si dice «fatto» solo se zeta-sfondo conferma davvero la scelta
        if _run(["zeta-sfondo", "get"]).split("\n")[0].strip() != ufficiale:
            return ActionResult(False, "Non sono riuscito a cambiare lo sfondo.")
        return ActionResult(True, "Sfondo cambiato: %s." % sfondi.nome_di(ufficiale))
    p = _safe_path(nome)
    if p is None or not p.is_file():
        return ActionResult(False, "Non trovo l'immagine «%s»." % nome)
    r = _run(["zeta-sfondo", "set", str(p)])
    return ActionResult(True, "Sfondo cambiato in %s." % p.name + (" " + r if r else ""))


SETTINGS_PAGES = {"aspetto", "rete", "bluetooth", "audio", "ai", "sicurezza", "pacchetti", "informazioni"}
SETTINGS_ALIASES = {"wifi": "rete", "wi-fi": "rete", "network": "rete", "suono": "audio",
                    "intelligenza": "ai", "assistente": "ai", "tema": "aspetto", "colore": "aspetto",
                    "info": "informazioni", "sistema": "informazioni"}


def _open_settings(args: dict) -> ActionResult:
    exe = shutil.which("zeta-impostazioni")
    if not exe:
        return ActionResult(False, "Le Impostazioni non sono disponibili.")
    page = (args.get("page") or "").strip().lower()
    page = SETTINGS_ALIASES.get(page, page)
    cmd = [exe] + ([page] if page in SETTINGS_PAGES else [])
    try:
        _popen(cmd, start_new_session=True)
        return ActionResult(True, "Apro le Impostazioni" + (" › %s." % page if page in SETTINGS_PAGES else "."))
    except OSError as e:
        return ActionResult(False, "Impossibile aprire le Impostazioni: %s" % e)


_GIORNI = ("lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica")
_MESI = ("gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio",
         "agosto", "settembre", "ottobre", "novembre", "dicembre")


def _current_time() -> ActionResult:
    import datetime
    ora = datetime.datetime.now()
    return ActionResult(True, "Sono le %s." % ora.strftime("%H:%M"))


def _current_date() -> ActionResult:
    import datetime
    o = datetime.date.today()
    return ActionResult(True, "Oggi è %s %d %s %d."
                        % (_GIORNI[o.weekday()], o.day, _MESI[o.month - 1], o.year))


def _battery_status() -> ActionResult:
    import sys
    if "/usr/lib/zeta" not in sys.path:
        sys.path.insert(0, "/usr/lib/zeta")
    from system import power
    b = power.battery()
    if not b:
        return ActionResult(True, "Questo computer non ha una batteria.")
    stato = b.get("state") or ""
    return ActionResult(True, "Batteria al %s%%%s."
                        % (b.get("percent", "?"), (" — " + stato) if stato else ""))


def _volume_status() -> ActionResult:
    out = _run(["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"], timeout=4)
    if not out or "Volume" not in out:
        return ActionResult(False, "Non riesco a leggere il volume.")
    muto = "MUTED" in out
    try:
        valore = float(out.split()[1])
    except (IndexError, ValueError):
        return ActionResult(False, "Non riesco a leggere il volume.")
    return ActionResult(True, "Volume al %d%%%s." % (round(valore * 100),
                                                     " (muto)" if muto else ""))


def _windows():
    import sys
    if "/usr/lib/zeta" not in sys.path:
        sys.path.insert(0, "/usr/lib/zeta")
    from system import windows
    return windows


def _minimize_window() -> ActionResult:
    if not os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
        return ActionResult(False, "Nessuna sessione desktop attiva.")
    if _windows().minimize():
        return ActionResult(True, "Fatto: la trovi nella barra, in «ridotte».")
    return ActionResult(False, "Non c'è una finestra da ridurre a icona.")


def _maximize_window() -> ActionResult:
    if not os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
        return ActionResult(False, "Nessuna sessione desktop attiva.")
    if _windows().toggle_maximize():
        return ActionResult(True, "Ho ingrandito la finestra attiva.")
    return ActionResult(False, "Non sono riuscito a ingrandire la finestra.")


def _list_windows() -> ActionResult:
    if not os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
        return ActionResult(False, "Nessuna sessione desktop attiva.")
    w = _windows()
    aperte = w.open_windows()
    ridotte = w.minimized()
    righe = ["Finestre aperte:"]
    righe += ["  • %s (scrivania %s)" % (x["title"][:50], x["workspace"]) for x in aperte] or ["  (nessuna)"]
    righe.append("Ridotte a icona:")
    righe += ["  • %s" % x["title"][:50] for x in ridotte] or ["  (nessuna)"]
    return ActionResult(True, "\n".join(righe))


def _set_theme(args: dict) -> ActionResult:
    tema = (args.get("tema") or "").strip().lower()
    if tema not in ("chiaro", "scuro"):
        return ActionResult(False, "Tema non valido: usa «chiaro» o «scuro».")
    p = subprocess.run(["zeta-aspetto", "set", "tema", tema],
                       capture_output=True, text=True)
    if p.returncode == 0:
        return ActionResult(True, "Tema %s applicato." % tema)
    return ActionResult(False, "Non sono riuscito a cambiare tema.")


def _close_active_window() -> ActionResult:
    if not os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
        return ActionResult(False, "Nessuna sessione desktop attiva.")
    # Hyprland di ZETA RAYS usa i dispatcher Lua: la forma classica non funziona.
    p = subprocess.run(["hyprctl", "dispatch", "hl.dsp.window.close()"],
                       capture_output=True, text=True)
    if p.returncode == 0 and "ok" in (p.stdout or "").lower():
        return ActionResult(True, "Ho chiuso la finestra attiva.")
    return ActionResult(False, "Non sono riuscito a chiudere la finestra.")


def _cpu_usage() -> str:
    try:
        with open("/proc/stat") as f:
            a = [float(x) for x in f.readline().split()[1:]]
        time.sleep(0.4)
        with open("/proc/stat") as f:
            b = [float(x) for x in f.readline().split()[1:]]
        idle = (b[3] + b[4]) - (a[3] + a[4])
        total = sum(b) - sum(a)
        pct = 100.0 * (1 - idle / total) if total > 0 else 0.0
        return "Uso della CPU: %.0f%%" % pct
    except (OSError, ValueError, IndexError):
        return "Non riesco a leggere l'uso della CPU."


def _memory_usage() -> str:
    info = {}
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                k, _, v = line.partition(":")
                info[k] = float(v.strip().split()[0]) * 1024
    except (OSError, ValueError):
        return "Non riesco a leggere la memoria."
    total = info.get("MemTotal", 0)
    avail = info.get("MemAvailable", 0)
    used = total - avail
    g = 1024 ** 3
    pct = 100 * used / total if total else 0
    return "Memoria: %.1f GB su %.1f GB in uso (%.0f%%), %.1f GB liberi." % (
        used / g, total / g, pct, avail / g)


def _ip_address() -> str:
    out = _run(["sh", "-c",
                "ip -brief -4 addr show scope global 2>/dev/null | awk '{print $1\": \"$3}'"])
    return out or "Nessun indirizzo IP attivo."


def _list_applications() -> str:
    apps = []
    seen = set()
    for d in ("/usr/share/applications", os.path.expanduser("~/.local/share/applications")):
        for path in sorted(Path(d).glob("*.desktop")) if os.path.isdir(d) else []:
            try:
                txt = path.read_text(errors="replace")
            except OSError:
                continue
            if "NoDisplay=true" in txt or "Type=Application" not in txt:
                continue
            name = ""
            for line in txt.splitlines():
                if line.startswith("Name="):
                    name = line[5:].strip()
                    break
            if name and name not in seen:
                seen.add(name)
                apps.append(name)
    apps.sort(key=str.lower)
    return "Applicazioni disponibili:\n" + ", ".join(apps[:60]) if apps else "Nessuna applicazione trovata."


def _set_accent(args: dict) -> ActionResult:
    color = args.get("color", "")
    exe = shutil.which("zeta-accent")
    if not exe:
        return ActionResult(False, "Comando zeta-accent non disponibile.")
    p = subprocess.run([exe, color], capture_output=True, text=True)
    if p.returncode == 0:
        return ActionResult(True, "Colore d'accento impostato su %s." % color)
    return ActionResult(False, (p.stderr or "Colore non valido.").strip())
